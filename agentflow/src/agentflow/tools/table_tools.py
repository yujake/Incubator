"""表 CRUD 工具（A/B/C/D 共用的数据面原子动作）。

## 为什么这些工具长这样

`base.py` 已经把"工具"这件事的形状定下来了（名字 / JSON Schema / 副作用声明 /
结构化返回）。本模块只负责把这些形状接上真实数据，因此有三条硬性规矩：

1. 写操作一律走 `store.tx(...)`，并且显式声明它要碰的每一张表。
   包括 `counters` —— `alloc_id` 在事务内改计数器，没声明就会 `StoreError`。
   更要紧的是：`Tx.rows()` 只允许读已声明的表，所以"声明"实际上就是
   "这次操作会依赖哪些表的一致性"，漏声明会在运行时报错而不是悄悄读到脏数据。

2. 读操作不加锁。 `store.rows()` 是无锁快照读，只用于展示/统计。
   C 的分析任务会对同一批数据反复组合查询；如果每次只读都去抢排他锁，
   就会把 A/B 的写入挡在外面。写工具独占锁、读工具无锁 —— 这个分工是刻意的。

3. 业务性失败返回 `fail(...)`，不抛异常。
   "名字重复""被关系引用所以不能删""字段拼错了"这些都不是环境故障，
   而是调用方需要看到并纠正的信息。抛异常会打断智能体的循环，
   而它恰恰是唯一能修好这个错误的一方。

## 派生字段：为什么工具要顺手补

`relations.concept_group_key` / `quote_normalized` / `dedup_key` 都是纯派生字段
（见 `agent_b.py` 的写入路径）。`verify` 会用 `textutil.concept_group_key(concept_ids)`
独立复算并比对，不一致就是 `stale_group_key`（错误级）。
工具建的行若不补这几个字段，就会造出"结构合法但 verify 报错"的行 ——
所以 create 时字段为空就补、update 时依赖变了且调用方没显式给就重算。
调用方显式给的值永远优先（否则"给定字段被悄悄改写"比缺字段更难排查）。
"""

from __future__ import annotations

import dataclasses
import types
import typing
from dataclasses import dataclass, replace
from functools import partial
from typing import Any, Callable, Iterable, Mapping, Sequence

from .. import dedup as _dedup
from .. import schema as S
from .. import textutil as _text
from ..interactions import IdSpaceExhausted, next_prefixed_id
from ..store import IdExhausted, Store, StoreError, Tx
from .base import ToolError, ToolRegistry, ToolResult, ToolSpec, fail, ok, tool

#: 六张表的表名（从 schema 反射，不手抄）。
ALL_TABLES: tuple[str, ...] = tuple(S.TABLES)

#: 按 DESIGN-TOOLS.md §1.1，表与文件的 CRUD 对 A/B/C/D 全部开放。
TOOL_ROLES: tuple[str, ...] = ("A", "B", "C", "D")

#: `table.list` / `table.search` 的 limit 边界。上限 500 是防"一次把整表灌进上下文"：
#: 工具层的读者是 LLM，返回 1 万行对它是纯噪声（还会顶掉真正有用的内容）。
LIST_LIMIT_MIN, LIST_LIMIT_MAX, LIST_LIMIT_DEFAULT = 1, 500, 50
SEARCH_LIMIT_MIN, SEARCH_LIMIT_MAX, SEARCH_LIMIT_DEFAULT = 1, 500, 50

#: 建行前的"探针 ID"里那 4 位数字的取值。见 `_probe_id`。
_PROBE_ID = "9999"


@dataclass(frozen=True)
class TableContext:
    """工具执行所需的共享状态。注册时一次性绑定，handler 本身因此保持无状态。"""

    store: Store
    #: 写进 events.jsonl 的 actor，用于审计"这行是谁改的"。
    actor: str = "tool"


# ---------------------------------------------------------------- 通用小工具


def _spec_of(table: str) -> dict:
    if table not in S.TABLES:
        raise ToolError(f"未知表名 {table!r}；可用：{list(ALL_TABLES)}")
    return S.TABLES[table]


def _fields_of(table: str) -> list[dataclasses.Field]:
    return list(dataclasses.fields(_spec_of(table)["row"]))


def _field_names(table: str) -> set[str]:
    return {f.name for f in _fields_of(table)}


def _has_field(table: str, name: str) -> bool:
    return name in _field_names(table)


def _rows(ctx: TableContext, table: str) -> list[dict]:
    """无锁快照读。

    只读工具用它是对的（理由见模块 docstring），但它拿到的是某一瞬间的副本：
    读出来的行不能再 upsert 回去，否则会覆盖别人在这期间的修改。
    """
    _spec_of(table)  # 提前校验表名，给出比 KeyError 更清楚的错误
    return ctx.store.rows(table)


def _build_row(table: str, raw: Mapping[str, Any]) -> tuple[Any, dict]:
    """把 dict 规范化成 (行对象, 待落盘的整行)。任何问题抛 `ToolError`。

    - 未知字段直接拒绝：`S.row_from_dict` 会静默忽略未知键，于是一个拼错的字段名
      会表现为"我明明写了却没生效"。宁可在这里炸，也不要让智能体去猜。
      （以 `_` 开头的是诊断字段，如 `agent_a` 写的 `_keys`，允许保留。）
    - 保留 schema 之外的诊断字段：`store.rebuild()` 是刻意保留它们的
      （见其合并逻辑），工具若只写 `obj.to_dict()` 就会在一行 update 之后
      把 `_keys` / `_quote_check` 悄悄抹掉 —— 两条写入路径的行为必须一致。
    """
    cls = _spec_of(table)["row"]
    known = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(str(k) for k in raw if k not in known and not str(k).startswith("_"))
    if unknown:
        raise ToolError(f"{table} 没有字段 {unknown}；可用字段：{sorted(known)}")

    try:
        obj = S.row_from_dict(table, dict(raw))
    except TypeError as e:
        # 缺必填字段时 dataclass 抛的是 TypeError，不是 ValueError
        raise ToolError(f"{table} 缺少必填字段（{e}）") from e
    try:
        obj.validate()
    except ValueError as e:
        raise ToolError(f"{table} 行校验失败：{e}") from e

    canonical = obj.to_dict()
    extra = {k: v for k, v in raw.items() if k not in canonical}
    return obj, {**extra, **canonical}


def _probe_id(table: str) -> str:
    """建行前用来"预演校验"的占位 ID（按这张表自己的 ID 契约造）。

    为什么需要预演：4 位 ID 是 `alloc_id` 在事务内发出去的，而只要发过号，
    计数器就已经脏了 —— 哪怕这行随后校验失败、什么都没落盘，号也收不回来，
    表现为 `verify` 的 `id_gap` 警告。所以先用一个合法占位 ID 把
    "字段/取值有没有问题"查一遍，只有真到了发号那一步才进入事务。

    ## 占位 ID 必须满足"这张表自己的 ID 契约"（`P-17`）

    `schema` 的过程记录契约是 `<前缀>-NNNN`（`PROCESS_ID_PREFIXES`：
    `search_requests` = `r`、`reprocess_requests` = `p`、`tasks` = `t`），
    而实体表用的是裸 4 位。此前这里对所有表都返回裸 `"9999"`，于是
    `schema` 把 `require_process_id` 接进 `SearchRequest.validate` 之后，
    `table.create(table="search_requests")` 在预演那一步就被自己的校验拒掉
    （实测原文：`search_requests 行校验失败：request 的过程记录 ID 必须是
    「前缀 'r' + 连接号 + 恰好 4 位数字」（如 r-0001），收到 '9999'`），
    连事务都进不去 —— 建行功能整个失效。占位值因此不能写死一种形态，
    而要从 `schema` 的声明面读前缀：前缀只有一处定义，这里不另抄一份。
    """
    prefix = S.PROCESS_ID_PREFIXES.get(_spec_of(table)["id_kind"])
    return f"{prefix}-{_PROBE_ID}" if prefix else _PROBE_ID


def _touch_timestamps(table: str, data: dict, *, create: bool, patch: Mapping[str, Any] | None = None) -> None:
    """按需补 `created_at` / `updated_at`。

    这两个字段在 schema 里默认是空串，调用方不填就会永远空着（下游按时间排序会莫名奇妙）。
    规则刻意保守：只在字段存在、且调用方没给值时才写，绝不覆盖显式给的值。
    """
    now = S.now_iso()
    if create:
        if _has_field(table, "created_at") and not data.get("created_at"):
            data["created_at"] = now
        if _has_field(table, "updated_at") and not data.get("updated_at"):
            data["updated_at"] = now
        return
    # 更新：只有"改了这一行却不动 updated_at"才是 bug（调用方显式指定则尊重它）
    if _has_field(table, "updated_at") and (patch is None or "updated_at" not in patch):
        data["updated_at"] = now


def _fill_derived(table: str, data: dict, *, create: bool, patch: Mapping[str, Any] | None = None) -> None:
    """补齐 `relations` 的派生字段（只在"缺"或"依赖变了"时补，理由见模块 docstring）。"""
    if table != "relations":
        return
    p = patch or {}
    if create or not data.get("concept_group_key"):
        data["concept_group_key"] = _text.concept_group_key(data.get("concept_ids") or [])
    elif "concept_ids" in p and "concept_group_key" not in p:
        data["concept_group_key"] = _text.concept_group_key(data.get("concept_ids") or [])

    depends_on_quote = create or "quote" in p
    if (create or "quote_normalized" not in p) and (depends_on_quote or not data.get("quote_normalized")):
        data["quote_normalized"] = _text.normalize_for_quote(data.get("quote") or "")
    if (create or "dedup_key" not in p) and (depends_on_quote or "concept_ids" in p or not data.get("dedup_key")):
        data["dedup_key"] = _dedup.relation_dedup_key(data.get("concept_group_key", ""), data.get("quote") or "")


def assert_request_id_in_space(new_id: str) -> str:
    """`r-NNNN` 的编号空间守卫（全项目唯一实现）。

    ## 为什么"转发给 `next_prefixed_id`"还不够

    `interactions.next_prefixed_id` 负责取号规则
    （max+1、跳过已占用、前缀守卫），但它没有任何上限保护：表里已经用到
    `r-9999` 时，它会给出 `"r-10000"`。

    而 `r-NNNN` 是一个4 位契约，不是风格偏好：

    - `store.MAX_ID`：`MAX_ID = 9999`，"4 位 ID 的上限。用满即 fail-closed
      （DESIGN.md §0.1 C4）"——项目级的规则是宁可显式失败，也不静默升位宽；
    - `tests/test_agent_c_service.py` 里直接断言
      `S.is_valid_id(row["request_id"][2:])` —— `"10000"` 不是合法 4 位 ID；
    - `SearchRequest.validate` 现在也查前缀与 4 位形态（`P-17` 的
      `require_process_id`），但那只在落库那一刻生效，而取号发生在落库之前 ——
      越界号必须在发出来的那一刻就挡住，否则计数器已经脏了（`id_gap`）。
      判据在"发号"与"落库"两处都在，不是重复：一处保证不发，一处保证落了也非法。

    所以这里对结果做一道契约检查：取号仍然只有一份实现，但"号必须落在
    4 位空间内"这条判据只能有一处，且必须在写入之前生效。

    # 待修：按 FC-03 的口径，这道上限最好下沉进 `interactions.next_prefixed_id`
    # 本身（那才是取号的唯一实现，agent_c/d/f/cli/demo 都直接调它，它们现在同样
    # 没有上限 —— 也就是说直接调它的路径仍会产出 `r-10000`）。
    # `interactions.py` 是 FC-27 禁改区（auth-audit），我不改它，因此把守卫放在
    # 工具层的这一个函数里，并让 `research_tools` 也调它（不是各写一份）。
    """
    # 判据本体在 `_assert_process_id_in_space`（过程记录通用版）：这里只把
    # "哪张表用哪个前缀"这两个参数固定成 `search_requests` 与 `r`。
    # `research_tools` 与既有调用方按这个名字取用，名字与语义都不动。
    return _assert_process_id_in_space(new_id, prefix="r", table="search_requests")


def _assert_process_id_in_space(new_id: str, *, prefix: str, table: str) -> str:
    """`<前缀>-NNNN` 的 4 位空间守卫（过程记录通用版）。

    为什么参数化成"前缀 + 表名"而不是各写一份：过程记录不止 `search_requests`
    一张（`schema.PROCESS_ID_PREFIXES` 里还有 `p` 与 `t`），而"号必须落在 4 位
    空间内"这条判据只能有一处 —— 复制一份出来，两处的上限就会漂移，
    而漂移的表现是"一处 fail-closed、另一处静默升位宽"。
    """
    digits = new_id[len(prefix) + 1:] if new_id.startswith(f"{prefix}-") else ""
    if not digits.isdigit() or int(digits) > 9999:
        raise ToolError(
            f"{table} 的 {prefix}-NNNN 编号空间已用尽（上限 9999），"
            f"取号器给出的是 {new_id!r} —— 5 位号会静默违反 4 位契约"
            "（`store.MAX_ID` 的 fail-closed 规则），因此在这里就拒绝。"
        )
    return new_id


def _next_process_id(rows: Sequence[Mapping[str, Any]], *, id_field: str, prefix: str,
                     table: str) -> str:
    """过程记录取号（唯一实现 + 空间守卫）；主键字段名与前缀由调用方从 schema 传来。

    这里曾经把"不在 `ID_COUNTERS` 里的表"一律当成 `search_requests`：用写死的
    `"request_id"` 与 `"r"` 取号。`reprocess_requests`（id_kind `reprocess`、
    主键 `reprocess_id`、前缀 `p`）因此拿到一个 `r-NNNN` 塞进 `reprocess_id` ——
    `schema` 把 `require_process_id` 接进校验之前，这会静默落库（错误前缀的号）；
    之后就变成建行必失败。两种后果都不是取号规则的问题，而是"表与前缀的对应关系"
    被写死了第二份，所以这里改成由 `_allocate_id` 从 `schema.PROCESS_ID_PREFIXES` 读。
    """
    try:
        new_id = next_prefixed_id(rows, id_field, prefix)
    except IdSpaceExhausted as exc:
        raise ToolError(str(exc)) from exc
    return _assert_process_id_in_space(new_id, prefix=prefix, table=table)


def _next_request_id(rows: Sequence[Mapping[str, Any]]) -> str:
    """`search_requests` 的主键是 `r-NNNN`（转发给唯一实现 + 空间守卫）。

    见 `schema.ID_COUNTERS` 的注释：`search_requests` 的 id_kind 是 "request"，
    它不在 `ID_COUNTERS` 里，所以 `alloc_id("request")` 会直接报"未知 ID 类别"。

    ## 这里曾经是第二份取号实现（已修）

    本函数原先自己扫描行取最小可用号，而 `research_tools` 里另有一份"取 max+1"
    的副本、`interactions.next_prefixed_id` 里还有第三份（带前缀守卫）—— 同一个
    `search_requests` 表有三个取号器，语义互相冲突：表里只有 `r-0001`、`r-0003` 时
    这边给 `r-0000`、那边给 `r-0004`。

    "最小可用号"还有更坏的一面：它会复用已删行的号，而
    `literature.source_request_ids` 与 `research_questions.waiting_request_ids`
    都长期引用 `r-NNNN` —— 号一旦被复用，溯源会静默指向另一条请求。
    这是"静默错误指向"，比崩溃危险。`interactions.next_prefixed_id` 的 docstring
    自己写着"删除中间行不会导致撞号"。所以那个语义被放弃了（连同
    `tests/test_tools_table_fs.py` 里断言 `"r-0000"` 的那一行一起改）——
    那是修正一条编码了错误行为的断言，不是放宽断言。

    ## `P-4` 之后：上限在 `next_prefixed_id` 里，类型在这里翻译

    `interactions.next_prefixed_id` 现在自己挡越界（判据只有一份）。它抛的是
    具名的 `IdSpaceExhausted`（继承 `ValueError`），这里把它精确翻成工具层的
    `ToolError` —— 否则它会一路冒到 `ToolRegistry.call` 被兜成 `kind='unexpected'`，
    于是"编号空间用尽"（已知、可处理）与"工具内部有 bug"在下游同形。
    不把整个 `ValueError` 都翻掉：`next_prefixed_id` 也会因为"prefix 带了连接号"
    抛 `ValueError`，那是调用方编码错误，应当保持原样冒出去。

    实现只有一份：`_next_process_id`（过程记录通用），这里只固定
    "`request_id` + `r` + `search_requests`"这三个参数。
    """
    return _next_process_id(rows, id_field="request_id", prefix="r",
                            table="search_requests")


def _allocate_id(tx: Tx, table: str) -> str:
    """按这张表在 `schema` 里的声明发一个主键。

    两类分开：`ID_COUNTERS` 覆盖的实体表走 4 位计数器（用满抛 `IdExhausted`）；
    过程记录表（`id_kind` 不在 `ID_COUNTERS` 里）走 `interactions.next_prefixed_id`。
    主键字段名与前缀一律从 `schema` 现取 —— 这里不再写死任何一张表的对应关系。
    """
    spec = _spec_of(table)
    kind = spec["id_kind"]
    if kind in S.ID_COUNTERS:
        return tx.alloc_id(kind)
    return _next_process_id(tx.rows(table), id_field=spec["id_field"],
                            prefix=S.PROCESS_ID_PREFIXES[kind], table=table)


def _mark_dirty(tx: Tx, table: str) -> None:
    """声明"这张表要写回"。

    `Tx` 的 docstring 说"用 `tx.mark_dirty(t)` 声明要写回"，但类里并没有这个方法
    （只有 `upsert` 会顺带置位）。而删除既不能 upsert 也不能不置位，所以这里退一步
    直接操作 dirty 集合。`Tx.rows()` 返回的就是内部那个 list，因此原地改它就等于改快照。
    若将来 `store.py` 补上公开方法，只需改这一处。
    """
    tx._dirty.add(table)  # noqa: SLF001 —— 见上面说明，这是当前唯一可行的写法


# ---------------------------------------------------------------- 外键检查
#: 删除某张表的行之前，必须查清"谁在引用它"。
#: 格式：被删表 -> ((引用表, 引用字段, 引用表的主键字段), ...)
#:
#: 为什么必须查：静默删掉被引用的行，`verify` 之后会报 `dangling_concept` /
#: `dangling_lit`（错误级），而那时"原来是谁引用的"已经查不出来了 ——
#: 证据在删除的那一刻就丢了。在删除前拦下，是唯一能给出可操作错误信息的时机。
_REF_SPECS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "concepts": (
        ("relations", "concept_ids", "relation_id"),
        # 概念之间也互相引用。`related_concepts` 虽由关系表派生，但可能残留旧值，
        # 漏掉这条会留下 verify 的 `dangling_related`（同样是错误级）。
        ("concepts", "related_concepts", "concept_id"),
        ("research_questions", "related_concept_ids", "question_id"),
    ),
    "literature": (
        ("relations", "lit_id", "relation_id"),
        ("search_requests", "result_lit_ids", "request_id"),
        ("research_questions", "evidence_lit_ids", "question_id"),
    ),
    "relations": (
        ("relations", "duplicate_of", "relation_id"),
        ("research_questions", "related_relation_ids", "question_id"),
    ),
    "search_requests": (
        ("literature", "source_request_ids", "lit_id"),
        ("research_questions", "waiting_request_ids", "question_id"),
    ),
    "research_questions": (),
    "analysis_reports": (),
}

#: 这些表的行一旦被引用，删除必须硬拒绝。
#: `relations` / `search_requests` 不在其中：DESIGN-TOOLS 明确"删 relations 没事"，
#: 且它们被引用的后果是可恢复的（`duplicate_of` 只是警告级）—— 所以对它们
#: 采取"放行但在 meta 里如实列出将变成悬空引用的行"，而不是一刀切拦住。
_BLOCKING_TARGETS: tuple[str, ...] = ("concepts", "literature")


def _ref_tables(target: str) -> tuple[str, ...]:
    return tuple({t for t, _, _ in _REF_SPECS.get(target, ())})


def _find_references(tx: Tx, target: str, target_id: str) -> list[dict]:
    """返回 [{table, field, row_id}, ...]，指出谁引用了 `target_id`。"""
    out: list[dict] = []
    for ref_table, ref_field, ref_id_field in _REF_SPECS.get(target, ()):
        for row in tx.rows(ref_table):
            if ref_table == target and row.get(ref_id_field) == target_id:
                continue  # 自己引用自己不算（删的就是它）
            val = row.get(ref_field)
            if val is None:
                continue
            values = val if isinstance(val, (list, tuple, set)) else (val,)
            if target_id in values:
                out.append({"table": ref_table, "field": ref_field, "row_id": row.get(ref_id_field)})
    return out


def _format_refs(refs: Sequence[Mapping[str, Any]], limit: int = 10) -> str:
    shown = [f"{r['table']}.{r['row_id']}({r['field']})" for r in refs[:limit]]
    more = f" 等共 {len(refs)} 处" if len(refs) > limit else ""
    return "、".join(shown) + more


# ---------------------------------------------------------------- 过滤 / 反射


def _match_filter(rows: Sequence[Mapping[str, Any]], filt: Mapping[str, Any] | None) -> list[dict]:
    """等值过滤。

    刻意只做等值：模糊匹配是 `table.search` 的活。把两种语义混在一个参数里，
    调用方就再也说不清"我这次到底要的是哪种匹配"。
    """
    if not filt:
        return [dict(r) for r in rows]
    return [dict(r) for r in rows if all(r.get(k) == v for k, v in filt.items())]


def _type_hints(cls: type) -> dict[str, Any]:
    try:
        return typing.get_type_hints(cls)
    except Exception:  # noqa: BLE001 —— 反射失败不该让工具不可用
        return {f.name: f.type for f in dataclasses.fields(cls)}


def _type_name(tp: Any) -> str:
    """把注解渲染成人能读的短名（不用 repr，`Literal[...]` 的 repr 会长到没法看）。"""
    if tp is type(None):
        return "null"
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(_type_name(a) for a in typing.get_args(tp))
    if origin is typing.Literal:
        return "str(literal)"
    if origin in (list, tuple, set, frozenset, dict):
        args = typing.get_args(tp)
        inner = ", ".join(_type_name(a) for a in args) if args else "any"
        return f"{getattr(origin, '__name__', str(origin))}[{inner}]"
    return getattr(tp, "__name__", str(tp))


def _is_array_type(tp: Any) -> bool:
    return typing.get_origin(tp) in (list, tuple, set, frozenset)


def _mentions_str(tp: Any) -> bool:
    if tp is str:
        return True
    return any(getattr(a, "__name__", "") == "str" for a in typing.get_args(tp))


def _scalar_str_fields(table: str) -> list[str]:
    """默认的"全部字符串字段"。只取标量 str（含 `str | None`）。

    数组字段（`related_concepts` 等）不默认参与：它们是代号不是文本，
    默认搜进去会让一次搜 "0001" 命中半张表的每一行，噪声远大于收益。
    需要时用 `fields` 显式指定，那时按"任一元素命中即命中"处理。
    """
    hints = _type_hints(_spec_of(table)["row"])
    return [f.name for f in _fields_of(table) if not _is_array_type(hints.get(f.name)) and _mentions_str(hints.get(f.name))]


def _vocabularies() -> dict[str, list[str]]:
    """反射出 `schema` 模块里的全部受控词表。

    做法：模块级的"非空、元素全为 str 的 tuple"就是受控词表。这样新增词表会自动出现，
    而"手抄一份常量清单"必然会随 schema 演进悄悄过期 —— 过期的词表比没有词表更危险，
    因为调用方会照着它写出非法值。
    """
    return {
        name: list(val)
        for name, val in vars(S).items()
        if isinstance(val, tuple) and val and all(isinstance(x, str) for x in val)
    }


#: 字段 -> 词表属性名（不是值）。值一律 `getattr(S, name)` 现取，杜绝两处不一致。
_VOCAB_BY_FIELD: dict[tuple[str, str], str] = {
    ("search_requests", "mode"): "SEARCH_MODES",
    ("search_requests", "outcome"): "SEARCH_OUTCOMES",
    ("literature", "type"): "LIT_TYPES",
    ("relations", "status"): "RELATION_STATUS",
    ("research_questions", "status"): "QUESTION_STATUSES",
    ("research_questions", "priority"): "PRIORITIES",
    ("analysis_reports", "kind"): "REPORT_KINDS",
    # 猜想（`draft/30` §T1 第 6 处）：状态与形态各有受控词表，不登记就会被静默不校验。
    ("conjectures", "status"): "CONJECTURE_STATUSES",
    ("conjectures", "form"): "CONJECTURE_FORMS",
}

#: 嵌在 JSON 对象里的词表。`literature.download` 是自由 dict，但它的 `status`
#: 是 B 用来决定"要不要抽取这个文件"的开关（见 schema.DOWNLOAD_STATUSES 的长注释），
#: 因此必须让调用方在 schema 里就看到它 —— 而不是等 verify 报错才知道。
_NESTED_VOCAB: tuple[tuple[str, str, str], ...] = (("literature", "download.status", "DOWNLOAD_STATUSES"),)


# ---------------------------------------------------------------- 参数片段

_TABLE_PROP = {"type": "string", "enum": list(ALL_TABLES),
               "description": f"{len(ALL_TABLES)} 张表之一"}
_LIMIT_PROP = {
    "type": "integer",
    "minimum": LIST_LIMIT_MIN,
    "maximum": LIST_LIMIT_MAX,
    "default": LIST_LIMIT_DEFAULT,
    "description": f"返回条数上限（{LIST_LIMIT_MIN}-{LIST_LIMIT_MAX}）",
}
_FILTER_PROP = {"type": "object", "description": "等值过滤：{字段: 期望值}；模糊匹配请用 table.search"}


def _obj(props: Mapping[str, Any], required: Iterable[str] = ()) -> dict:
    """构造 object 根 schema 的小工具（`additionalProperties=False` 让拼错的参数立刻报错）。"""
    return {
        "type": "object",
        "properties": dict(props),
        "required": list(required),
        "additionalProperties": False,
    }


# ---------------------------------------------------------------- 工具实现


@tool(
    "table.list",
    "列出某张表的行（支持等值过滤与分页），并给出过滤后的总数。",
    _obj(
        {
            "table": _TABLE_PROP,
            "limit": _LIMIT_PROP,
            "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "跳过的行数"},
            "filter": _FILTER_PROP,
        },
        required=("table",),
    ),
    side_effect="read",
    roles=TOOL_ROLES,
    # 键名逐个从 `table_list` 的 ok(...) 读出。注意 `filtered` 不在 data 里，
    # 它只出现在 `table.count` 的 meta 里（两处不同，别混）。
    returns="{'table','rows','total','returned','limit','offset'}；meta 里重复关键计数便于断言。",
    tags=("table", "crud"),
)
def table_list(
    ctx: TableContext,
    *,
    table: str,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
    filter: Mapping[str, Any] | None = None,
) -> ToolResult:
    """列表 + 总数。

    `total` 是过滤后的总数而不是本页条数：调用方要靠它判断"还有没有下一页"，
    只给 `len(rows)` 的话分页逻辑只能靠"这页是不是满的"来猜，最后一页正好装满时会多跑一轮。
    """
    try:
        _spec_of(table)
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")
    matched = _match_filter(_rows(ctx, table), filter)
    page = matched[offset : offset + limit]
    return ok(
        {
            "table": table,
            "rows": page,
            "total": len(matched),
            "returned": len(page),
            "limit": limit,
            "offset": offset,
        },
        table=table,
        total=len(matched),
        returned=len(page),
        offset=offset,
        limit=limit,
    )


@tool(
    "table.get",
    "按主键取一行；不存在时返回 ok=True 且 data=None（会用 meta.found=False 说明）。",
    _obj({"table": _TABLE_PROP, "id": {"type": "string", "description": "主键值（4 位字符串，或 r-NNNN）"}}, required=("table", "id")),
    side_effect="read",
    roles=TOOL_ROLES,
    # 豁免清单成员：data 是行对象或 None —— 行对象的字段由那张表的 schema
    # 决定（concepts 12 个字段、literature 又是另一套），不是本工具的形状。
    # "到底有没有"由 meta.found 表达。
    returns="data=行对象或 None（**形状由表 schema 决定，本工具不承诺固定键集合**）；meta.found 表达到底有没有。",
    tags=("table", "crud"),
)
def table_get(ctx: TableContext, *, table: str, id: str) -> ToolResult:
    """「没找到」不是错误。

    它是最常见的一种有效结论（比如判重前先探一下），所以走 `ok(found=False)`。
    若返回 `fail`，调用方就得靠"错误文本里有没有'不存在'"来决定分支 —— 那太脆了。
    """
    try:
        idf = _spec_of(table)["id_field"]
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")
    for row in _rows(ctx, table):
        if row.get(idf) == id:
            return ok(dict(row), table=table, id=id, id_field=idf, found=True)
    return ok(None, table=table, id=id, id_field=idf, found=False)


@tool(
    "table.create",
    "新建一行：会自动分配主键（search_requests 用 r-NNNN），校验通过才落盘，返回新 ID。",
    _obj(
        {
            "table": _TABLE_PROP,
            "row": {"type": "object", "description": "行内容；主键可省略（省略则自动分配）"},
        },
        required=("table", "row"),
    ),
    side_effect="write_local",
    roles=TOOL_ROLES,
    # 豁免清单成员：data 是新主键字符串（标量），声明不出键集合。
    returns="data=新主键字符串（**标量，无键集合**）；meta.row 是实际落盘的整行。",
    tags=("table", "crud", "write"),
)
def table_create(ctx: TableContext, *, table: str, row: Mapping[str, Any]) -> ToolResult:
    """建行。

    校验刻意放在进入事务之前先做一遍（用占位 ID），理由见 `_probe_id`：
    先发号再发现字段非法，会白白烧掉一个 4 位编号并留下 `id_gap`。
    """
    try:
        spec = _spec_of(table)
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")
    idf: str = spec["id_field"]

    data: dict[str, Any] = dict(row or {})
    explicit_id = data.get(idf)
    probe = str(explicit_id) if explicit_id not in (None, "") else _probe_id(table)
    try:
        _build_row(table, {**data, idf: probe})
    except ToolError as e:
        return fail(str(e), table=table, kind="validation")

    try:
        with ctx.store.tx(table, "counters", actor=ctx.actor, note=f"tool:table.create:{table}") as tx:
            if explicit_id not in (None, ""):
                new_id = str(explicit_id)
                if tx.find(table, **{idf: new_id}) is not None:
                    return fail(
                        f"{table} 已存在主键 {new_id}；要改它请用 table.update（create 不允许覆盖既有行）",
                        table=table,
                        id=new_id,
                        kind="duplicate_id",
                    )
            else:
                new_id = _allocate_id(tx, table)
            data[idf] = new_id
            _touch_timestamps(table, data, create=True)
            # 派生字段要在时间戳之后、校验之前补：它们参与 schema 校验之外的一致性检查
            _fill_derived(table, data, create=True)
            try:
                _obj_row, merged = _build_row(table, data)
            except ToolError as e:
                return fail(str(e), table=table, id=new_id, kind="validation")
            tx.upsert(table, merged, note="tool:table.create")
    except (IdExhausted, StoreError) as e:
        return fail(f"{table} 建行失败：{e}", table=table, kind="store_error")
    return ok(new_id, table=table, id=new_id, id_field=idf, row=merged)


@tool(
    "table.update",
    "部分更新一行：只覆盖 patch 里给出的字段，其余字段（含诊断字段）原样保留；不允许改主键。",
    _obj(
        {
            "table": _TABLE_PROP,
            "id": {"type": "string", "description": "要改的行主键"},
            "patch": {"type": "object", "description": "只写要改的字段"},
        },
        required=("table", "id", "patch"),
    ),
    side_effect="write_local",
    roles=TOOL_ROLES,
    # 豁免清单成员：data 是主键字符串（标量），声明不出键集合。
    returns="data=主键（**标量，无键集合**）；meta.row 是合并后实际落盘的整行。",
    tags=("table", "crud", "write"),
)
def table_update(ctx: TableContext, *, table: str, id: str, patch: Mapping[str, Any]) -> ToolResult:
    """部分更新。

    实现上是"读整行 → 覆盖 patch → 整行校验 → 整行写回"，而不是"只写 patch 的字段"：
    后者要先做字段级校验，等于把 `validate()` 的逻辑拆开重写一遍，两套规则迟早会漂移。
    整行验证则天然保证"改完之后这一行仍然是合法的"（比如 `concept_ids` 改完必须仍升序去重）。
    """
    try:
        idf = _spec_of(table)["id_field"]
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")
    if not patch:
        return fail("patch 不能为空（空 patch 只会更新 updated_at，通常是调用方写错了）", table=table, id=id, kind="param_error")

    try:
        with ctx.store.tx(table, "counters", actor=ctx.actor, note=f"tool:table.update:{table}") as tx:
            current = tx.find(table, **{idf: id})
            if current is None:
                return fail(f"{table} 里没有主键 {id}", table=table, id=id, found=False, kind="not_found")
            # 主键是行的身份。允许"顺手改主键"等于允许把 delete+create 伪装成 update，
            # 而所有外键都指向旧代号 —— 那样会一次性造出一片悬空引用。
            if idf in patch and patch[idf] != id:
                return fail(
                    f"不允许修改主键 {idf}（{id} → {patch[idf]}）。"
                    "主键是外键的锚点，改了会让所有引用它的行变成悬空引用；"
                    "确实需要请先 table.delete 再 table.create，并自行迁移引用。",
                    table=table,
                    id=id,
                    kind="primary_key_change",
                )
            merged_raw = dict(current)  # 整行起步 = 未在 patch 里出现的字段自动保留
            merged_raw.update(patch)
            _touch_timestamps(table, merged_raw, create=False, patch=patch)
            _fill_derived(table, merged_raw, create=False, patch=patch)
            try:
                _obj_row, merged = _build_row(table, merged_raw)
            except ToolError as e:
                return fail(str(e), table=table, id=id, kind="validation")
            tx.upsert(table, merged, note="tool:table.update")
    except (IdExhausted, StoreError) as e:
        return fail(f"{table} 更新失败：{e}", table=table, id=id, kind="store_error")
    return ok(id, table=table, id=id, id_field=idf, row=merged)


@tool(
    "table.delete",
    "删除一行；被引用的 concepts/literature 会被拒绝并列出引用者。",
    _obj({"table": _TABLE_PROP, "id": {"type": "string", "description": "要删的行主键"}}, required=("table", "id")),
    side_effect="write_local",
    roles=TOOL_ROLES,
    # 豁免清单成员：data 是布尔标量（是否真的删掉了），声明不出键集合。
    # 引用者清单在 meta.references 里（被拒时是原因，放行时是将会悬空的清单）。
    returns="data=是否真的删掉了（**布尔标量，无键集合**）；meta.references 列出引用者（被拒时是原因，放行时是将会悬空的清单）。",
    tags=("table", "crud", "write"),
)
def table_delete(ctx: TableContext, *, table: str, id: str) -> ToolResult:
    """删除 + 外键保护。

    没有回收站：一行删掉就没了，连"原来是谁引用的"也一并消失。所以这里
    宁可误拒（调用方可以先删关系）也不能误删 —— 拒绝是可以用一句话解释的，
    而 `dangling_*` 是只能靠重建数据才能修的事故。
    """
    try:
        spec = _spec_of(table)
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")
    idf: str = spec["id_field"]
    # 声明所有会被读到的表（引用扫描要逐张查）+ counters。
    # counters 这次并不写，但写操作一律显式带上它：让"这张表会不会被动到"这件事
    # 在代码里一眼可见，而不是靠"tx() 会偷偷加"这条隐式知识。
    tables = tuple(sorted({table, "counters", *_ref_tables(table)}))

    try:
        with ctx.store.tx(*tables, actor=ctx.actor, note=f"tool:table.delete:{table}") as tx:
            row = tx.find(table, **{idf: id})
            if row is None:
                return ok(False, table=table, id=id, found=False, deleted=False)
            refs = _find_references(tx, table, id)
            if refs and table in _BLOCKING_TARGETS:
                return fail(
                    f"不能删除 {table} {id}：仍被 {len(refs)} 处引用（{_format_refs(refs)}）。"
                    "请先删除或改指这些引用 —— 静默删除会让 verify 报 dangling_*，"
                    "而那时已经查不出原来是谁引用的。",
                    table=table,
                    id=id,
                    found=True,
                    deleted=False,
                    references=refs,
                    kind="referenced",
                )
            rows = tx.rows(table)
            rows[:] = [r for r in rows if r.get(idf) != id]
            _mark_dirty(tx, table)
    except StoreError as e:
        return fail(f"{table} 删除失败：{e}", table=table, id=id, kind="store_error")
    return ok(True, table=table, id=id, found=True, deleted=True, references=refs)


@tool(
    "table.count",
    "统计行数（可用 filter 做等值过滤）。",
    _obj({"table": _TABLE_PROP, "filter": _FILTER_PROP}, required=("table",)),
    side_effect="read",
    roles=TOOL_ROLES,
    # 豁免清单成员：data 是整数行数（标量），声明不出键集合。
    # 依据在实现里逐字写着（`table_count` 的 docstring："计数不该受 limit 影响"）。
    returns="data=整数行数（**标量，无键集合**）。",
    tags=("table", "crud"),
)
def table_count(ctx: TableContext, *, table: str, filter: Mapping[str, Any] | None = None) -> ToolResult:
    """计数。单独给一个工具（而不是让调用方拿 list 数长度）：计数不该受 limit 影响。"""
    try:
        _spec_of(table)
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")
    n = len(_match_filter(_rows(ctx, table), filter))
    return ok(n, table=table, total=n, filtered=bool(filter))


@tool(
    "table.schema",
    "返回 6 张表的字段名/类型/是否必填/默认值，以及全部受控词表（从 dataclass 与 schema 反射）。",
    _obj({}),
    side_effect="read",
    roles=TOOL_ROLES,
    # 键名从实现读出（`table_schema` 的 ok(...)）：tables 里每个表名 → {fields,
    # primary_key, vocabularies}，键名是表名（所以不能写进键集合）。
    returns="{'tables','vocabularies'}；tables 的键是表名，值是 {'fields','primary_key','vocabularies'}。",
    tags=("table", "meta"),
)
def table_schema(ctx: TableContext) -> ToolResult:  # noqa: ARG001 —— 纯反射，不需要 store
    """表结构自描述。

    为什么必须反射而不是手写：手写的 schema 说明是文档，文档会过期；
    过期的字段说明会直接导致智能体写出非法参数（然后被 validate 拒绝，白烧一轮）。
    同理，受控词表的取值一律 `getattr(S, name)` 现取，绝不在本模块复制一份。
    """
    vocabs = _vocabularies()
    tables: dict[str, Any] = {}
    for table, spec in S.TABLES.items():
        cls = spec["row"]
        hints = _type_hints(cls)
        fields: list[dict] = []
        table_vocabs: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            tp = hints.get(f.name, f.type)
            required = f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
            if f.default is not dataclasses.MISSING:
                default = f.default
            elif f.default_factory is not dataclasses.MISSING:
                default = f.default_factory()  # 只在反射期调用，用于把 [] 之类如实展示出来
            else:
                default = None
            item: dict[str, Any] = {
                "name": f.name,
                "type": _type_name(tp),
                "required": required,
                "default": default,
            }
            if typing.get_origin(tp) is typing.Literal:
                item["literal_values"] = list(typing.get_args(tp))
            vocab_name = _VOCAB_BY_FIELD.get((table, f.name))
            if vocab_name:
                item["vocabulary"] = vocab_name
                item["enum"] = list(getattr(S, vocab_name))
                table_vocabs[f.name] = {"vocabulary": vocab_name, "values": item["enum"]}
            fields.append(item)
        for v_table, v_path, v_name in _NESTED_VOCAB:
            if v_table == table:
                table_vocabs[v_path] = {"vocabulary": v_name, "values": list(getattr(S, v_name))}
        tables[table] = {
            "file": spec["file"],
            "primary_key": spec["id_field"],
            "id_kind": spec["id_kind"],
            "uses_id_counter": spec["id_kind"] in S.ID_COUNTERS,
            "fields": fields,
            "required": [f["name"] for f in fields if f["required"]],
            "vocabularies": table_vocabs,
        }
    return ok({"tables": tables, "vocabularies": vocabs}, table_count=len(tables), vocabulary_count=len(vocabs))


@tool(
    "table.search",
    "在指定（默认全部标量字符串）字段里做大小写不敏感的子串匹配。",
    _obj(
        {
            "table": _TABLE_PROP,
            "query": {"type": "string", "minLength": 1, "description": "要查找的子串（不做正则解释）"},
            "fields": {"type": "array", "items": {"type": "string"}, "description": "限定字段；省略=全部标量字符串字段"},
            "limit": {
                "type": "integer",
                "minimum": SEARCH_LIMIT_MIN,
                "maximum": SEARCH_LIMIT_MAX,
                "default": SEARCH_LIMIT_DEFAULT,
            },
        },
        required=("table", "query"),
    ),
    side_effect="read",
    roles=TOOL_ROLES,
    # 键名从实现读出（`table_search` 的 ok(...)）：`fields` 是本次实际扫描的字段名
    # （不是 data 里的字典键）；`matched_fields` 在 meta 里，键是主键值。
    returns="{'table','query','fields','rows','total','returned'}；meta.matched_fields 的键是主键、值是命中的字段名。",
    tags=("table", "read"),
)
def table_search(
    ctx: TableContext,
    *,
    table: str,
    query: str,
    fields: Sequence[str] | None = None,
    limit: int = SEARCH_LIMIT_DEFAULT,
) -> ToolResult:
    """子串搜索。

    刻意不做正则：这是数据面的"找一找"，正则属于文本面（`fs.search`）。
    大小写不敏感用 `casefold()` 而不是 `lower()` —— 后者对某些语言（如德语 ß）会漏匹配，
    而"大小写不敏感"的承诺必须是字面成立的。
    """
    try:
        _spec_of(table)
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")

    known = _field_names(table)
    scanned = list(fields) if fields else _scalar_str_fields(table)
    bad = sorted({f for f in scanned if f not in known})
    if bad:
        return fail(f"{table} 没有字段 {bad}；可用字段：{sorted(known)}", table=table, kind="param_error")
    if not scanned:
        return fail(f"{table} 没有可用于子串搜索的标量字符串字段；请用 fields 显式指定", table=table, kind="param_error")

    needle = query.casefold()
    hits: list[dict] = []
    matched: dict[str, list[str]] = {}
    for row in _rows(ctx, table):
        found_in: list[str] = []
        for name in scanned:
            val = row.get(name)
            if isinstance(val, str):
                if needle in val.casefold():
                    found_in.append(name)
            elif isinstance(val, (list, tuple)) and any(isinstance(x, str) and needle in x.casefold() for x in val):
                found_in.append(name)
        if found_in:
            hits.append(dict(row))
            rid = str(row.get(_spec_of(table)["id_field"]))
            matched[rid] = found_in
    page = hits[:limit]
    return ok(
        {"table": table, "query": query, "fields": scanned, "rows": page, "total": len(hits), "returned": len(page)},
        table=table,
        total=len(hits),
        returned=len(page),
        matched_fields=matched,
        truncated=len(hits) > len(page),
    )


# ---------------------------------------------------------------- 装配


#: 全部工具函数（保持声明顺序，便于按序注册与阅读）。
_TOOL_FUNCTIONS: tuple[Callable[..., ToolResult], ...] = (
    table_list,
    table_get,
    table_create,
    table_update,
    table_delete,
    table_count,
    table_schema,
    table_search,
)


def tool_specs() -> list[ToolSpec]:
    """未绑定 store 的工具清单（供装配前做目录/审计/文档生成）。"""
    return [fn.__tool_spec__ for fn in _TOOL_FUNCTIONS]  # type: ignore[attr-defined]


def _effective_roles(base: ToolSpec, injected: tuple[str, ...]) -> tuple[str, ...]:
    """把注入的角色集合按"只读角色不能拿写工具"过一遍。

    为什么要在这里做：`build_registry` 会把全部 `ROLES` 传进来，
    于是本模块的 8 个表工具（含 `create/update/delete`）会被声明给所有角色 ——
    包括只读的 C 与 H。实测过：`AgentH` 的工具面里出现了 `table.update`，
    即 审校者手里有能改稿件的刀。

    `ToolRegistry.for_role` 已经会做结构性拦截（防御不能只靠声明），
    但声明本身也应该对 —— 否则那条拦截会一直在“救火”，而调试者看到的
    角色工具数与声明不一致时会怀疑自己。
    """
    from . import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE

    if base.side_effect in SIDE_EFFECTS_WRITE:
        return tuple(r for r in injected if r not in READ_ONLY_ROLES)
    return injected

def register(
    registry: ToolRegistry,
    *,
    store: Store,
    roles: Iterable[str] = TOOL_ROLES,
    actor: str = "tool",
) -> list[ToolSpec]:
    """把 8 个表工具注册进 `registry`，并把 store 绑定进 handler。

    为什么用 `partial` 而不是让 handler 收 `store` 参数：`ToolRegistry.call` 只把
    工具参数转发给 handler，且 `spec.params` 会被原样喂给 function-calling。
    若 store 出现在参数表里，LLM 就会看到一个它永远填不对的必填参数。
    把依赖绑在注册期，工具参数表里就只剩"数据"。
    """
    ctx = TableContext(store=store, actor=actor)
    out: list[ToolSpec] = []
    for fn in _TOOL_FUNCTIONS:
        base_spec: ToolSpec = fn.__tool_spec__  # type: ignore[attr-defined]
        spec = replace(base_spec, handler=partial(fn, ctx), roles=_effective_roles(base_spec, tuple(roles)))
        out.append(registry.register(spec))
    return out


# ---------------------------------------------------------------- 自检


def _selftest() -> int:
    """端到端自检：真建库、真走 registry、真校验正/负用例。返回 0 表示全过。"""
    import shutil
    import tempfile
    from pathlib import Path

    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f" —— {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    def show(label: str, res: ToolResult, limit: int = 220) -> None:
        body = repr(res.to_dict())
        if len(body) > limit:
            body = body[:limit] + "…"
        print(f"  {label}: ok={res.ok} data={body}")

    tmp = Path(tempfile.mkdtemp(prefix="agentflow_table_selftest_"))
    try:
        st = Store(tmp)
        st.init()
        reg = ToolRegistry(name="selftest")
        # 绑定角色（`P-14`）：本自检要真的写表，而 `table.*` 的声明角色是 A/B/C/D ——
        # 取一个非只读角色（C 是只读，拿不到写工具）。
        reg.bound_role = "A"
        register(reg, store=st, roles=("A", "B", "C", "D"))
        print(f"[环境] 临时库={tmp}；已注册工具={reg.names()}")

        # ---- (1) 六张表逐张 schema / count
        print("\n[1] 六张表 schema / count")
        for t in ALL_TABLES:
            cr = reg.call("table.count", table=t)
            check(f"table.count {t}", cr.ok and cr.data == 0, f"count={cr.data}")
        sr = reg.call("table.schema")
        check("table.schema ok", sr.ok, f"vocabulary_count={sr.meta.get('vocabulary_count')}")
        schemas = sr.data["tables"]
        for t in ALL_TABLES:
            info = schemas[t]
            vocab_fields = list(info["vocabularies"])
            print(
                f"    {t:<18} 主键={info['primary_key']:<12} 字段={len(info['fields']):>2} "
                f"必填={info['required']} 词表字段={vocab_fields}"
            )
        reflected = sorted(sr.data["vocabularies"])
        expected_vocabs = sorted(
            [
                "LIT_TYPES",
                "SEARCH_MODES",
                "RELATION_STATUS",
                "SEARCH_OUTCOMES",
                "DOWNLOAD_STATUSES",
                "QUESTION_STATUSES",
                "PRIORITIES",
                "REPORT_KINDS",
            ]
        )
        check("8 个受控词表全部反射出来", reflected == expected_vocabs, f"{reflected}")
        for name in expected_vocabs:
            print(f"    词表 {name}: {sr.data['vocabularies'][name]}")
        check(
            "relations.concept_group_key 已补（依赖 concept_ids 派生）",
            "concept_group_key" in [f["name"] for f in schemas["relations"]["fields"]],
        )
        check(
            "literature 的嵌套词表 download.status 可见",
            "download.status" in schemas["literature"]["vocabularies"],
            str(schemas["literature"]["vocabularies"].get("download.status")),
        )

        # ---- 铺垫数据
        print("\n[2] 建行（含 r-NNNN 与派生字段）")
        r = reg.call(
            "table.create",
            table="search_requests",
            row={"timestamp": S.now_iso(), "topic": "群与域", "mode": "broad", "done": False},
        )
        check("search_requests 自动分配 r-NNNN", r.ok and r.data == "r-0000", f"id={r.data}")
        r = reg.call(
            "table.create",
            table="literature",
            row={
                "title": "Abelian groups and fields",
                "type": "J",
                "summary": "群与域的交换性",
                "path": None,
                "processed": True,
            },
        )
        check("literature 分配 0000", r.ok and r.data == "0000", f"id={r.data} err={r.error}")
        for name in ("群", "域"):
            r = reg.call("table.create", table="concepts", row={"name": name, "definition": f"{name}的定义", "related_concepts": []})
            check(f"concepts 建 {name}", r.ok, f"id={r.data} err={r.error}")
        r = reg.call(
            "table.create",
            table="relations",
            row={
                "concept_ids": ["0000", "0001"],
                "description": "群与域都由交换性刻画",
                "lit_id": "0000",
                "page_range": {"start": 12, "end": 13, "label": "pp.12-13"},
                "quote": "A field is an abelian group",
            },
        )
        check("relations 分配 0000 且派生字段已补", r.ok and r.data == "0000", f"err={r.error}")
        if r.ok:
            row0 = r.meta["row"]
            check("concept_group_key 派生正确", row0.get("concept_group_key") == "0000|0001", repr(row0.get("concept_group_key")))
            check("dedup_key 派生正确", bool(row0.get("dedup_key")), repr(row0.get("dedup_key")))
        r = reg.call("table.count", table="concepts")
        check("concepts.count = 2", r.ok and r.data == 2, f"count={r.data}")

        # ---- (2) create → get → update → get，确认未给字段被保留
        print("\n[3] create → get → update → get（未给字段必须保留）")
        r = reg.call(
            "table.create",
            table="concepts",
            row={"name": "环", "definition": "环的原始定义", "aliases": ["ring"], "related_concepts": [], "_probe": "诊断字段"},
        )
        new_id = r.data
        check("建 concept", r.ok and new_id == "0002", f"id={new_id} err={r.error}")
        g1 = reg.call("table.get", table="concepts", id=new_id)
        check("get 取回", g1.ok and g1.data["name"] == "环", f"name={g1.data.get('name') if g1.ok else None}")
        u = reg.call("table.update", table="concepts", id=new_id, patch={"name": "环（改）"})
        check("update 改名", u.ok, f"err={u.error}")
        g2 = reg.call("table.get", table="concepts", id=new_id)
        row2 = g2.data or {}
        check("改名生效", row2.get("name") == "环（改）", repr(row2.get("name")))
        check("未给的 definition 被保留", row2.get("definition") == "环的原始定义", repr(row2.get("definition")))
        check("未给的 aliases 被保留", row2.get("aliases") == ["ring"], repr(row2.get("aliases")))
        check("未给的 related_concepts 被保留", row2.get("related_concepts") == [], repr(row2.get("related_concepts")))
        check("诊断字段 _probe 未被抹掉", row2.get("_probe") == "诊断字段", repr(row2.get("_probe")))
        check("created_at 已自动补", bool(row2.get("created_at")), repr(row2.get("created_at")))
        check("updated_at 已自动补", bool(row2.get("updated_at")), repr(row2.get("updated_at")))

        # ---- 负面：改主键 / 校验失败 / 未知字段
        print("\n[4] 负面用例（写操作）")
        bad = reg.call("table.update", table="concepts", id=new_id, patch={"concept_id": "0009"})
        check("改主键被拒", not bad.ok and "不允许修改主键" in (bad.error or ""), f"error={bad.error}")
        bad = reg.call("table.create", table="concepts", row={"name": "  ", "definition": "x", "related_concepts": []})
        check("空 name 校验失败返回 fail 而不是抛异常", not bad.ok and "校验失败" in (bad.error or ""), f"error={bad.error}")
        bad = reg.call("table.create", table="concepts", row={"nmae": "拼错", "definition": "x"})
        check("未知字段被拒", not bad.ok and "没有字段" in (bad.error or ""), f"error={bad.error}")
        bad = reg.call(
            "table.create",
            table="relations",
            row={
                "concept_ids": ["0001", "0000"],
                "description": "乱序",
                "lit_id": "0000",
                "page_range": {"start": 1, "end": 1, "label": "p.1"},
            },
        )
        check("concept_ids 未升序 → fail", not bad.ok and "升序去重" in (bad.error or ""), f"error={bad.error}")
        bad = reg.call("table.list", table="nope")
        check("未知表名 → fail", not bad.ok, f"error={bad.error}")
        check("失败后没有烧掉编号", reg.call("table.count", table="concepts").data == 3, "(concepts 仍为 3 行)")

        # ---- (3) 负面：删除被关系引用的 concept
        print("\n[5] 负面：删除被关系引用的 concept")
        d = reg.call("table.delete", table="concepts", id="0000")
        check("删除被引用的 concept 被拒 (ok=False)", not d.ok, f"ok={d.ok}")
        check("错误信息点名了引用它的关系", "0000" in (d.error or "") and "relations" in (d.error or ""), f"error={d.error}")
        check("meta.references 列出引用者", (d.meta.get("references") or [{}])[0].get("row_id") == "0000", f"references={d.meta.get('references')}")
        check("被拒后行仍在", reg.call("table.get", table="concepts", id="0000").meta.get("found") is True)

        # ---- 负面：删除被请求/关系引用的 literature
        r = reg.call(
            "table.create",
            table="literature",
            row={"title": "第二篇", "type": "M", "summary": "备胎", "path": None, "processed": False},
        )
        lit1 = r.data
        reg.call("table.update", table="search_requests", id="r-0000", patch={"result_lit_ids": [lit1], "done": True, "outcome": "ok"})
        d = reg.call("table.delete", table="literature", id=lit1)
        check("删除被 search_requests.result_lit_ids 引用的 literature 被拒", not d.ok, f"error={d.error}")

        # ---- 放行路径：先删关系，再删概念/文献
        print("\n[6] 放行路径：relations 可直接删，随后概念/文献可删")
        d = reg.call("table.delete", table="relations", id="0000")
        check("删 relations 放行", d.ok and d.data is True, f"err={d.error}")
        d = reg.call("table.delete", table="concepts", id="0000")
        check("关系删掉后 concept 可删", d.ok and d.data is True, f"err={d.error}")
        d = reg.call("table.delete", table="concepts", id="0000")
        check("重复删除返回 data=False（found=False）", d.ok and d.data is False and d.meta.get("found") is False, f"data={d.data}")

        # ---- search / filter / list
        print("\n[7] search / filter / list / get 未命中")
        s = reg.call("table.search", table="concepts", query="环")
        check("search 命中 1 行", s.ok and s.meta.get("total") == 1, f"total={s.meta.get('total')} fields={s.data.get('fields') if s.ok else None}")
        s = reg.call("table.search", table="literature", query="ABELIAN")
        check("search 大小写不敏感", s.ok and s.meta.get("total") == 1, f"total={s.meta.get('total')}")
        s = reg.call("table.search", table="concepts", query="x", fields=["nope"])
        check("search 未知字段 → fail", not s.ok, f"error={s.error}")
        li = reg.call("table.list", table="concepts", limit=1, offset=0)
        check("list 分页 total=2 returned=1", li.ok and li.data["total"] == 2 and li.data["returned"] == 1, f"{li.data['total']}/{li.data['returned']}")
        cn = reg.call("table.count", table="search_requests", filter={"done": True})
        check("count + filter", cn.ok and cn.data == 1, f"count={cn.data}")
        g = reg.call("table.get", table="concepts", id="0009")
        check("get 未命中 → ok=True / found=False", g.ok and g.data is None and g.meta.get("found") is False)
        v = reg.call("table.update", table="concepts", id=new_id, patch={})
        check("空 patch → fail", not v.ok, f"error={v.error}")

        # ---- 交叉验证：工具写出来的库必须能过 verify 的错误级检查。
        # 这是"外键保护有没有真的起作用"的独立证据 —— 只测自己的返回值，
        # 有可能测的是自己的假设；用 verify 复算才是外部标准。
        from ..verify import verify_all

        rep = verify_all(st)
        errs = [f"{i.table}.{i.row_id}:{i.code}" for i in rep.errors]
        check("工具写入的库通过 verify（0 error）", rep.ok, f"errors={errs}")
        print(f"    verify checked={rep.checked} warnings={len(rep.warnings)}")

        print(f"\n[结果] 失败 {len(failures)} 项" + (f"：{failures}" if failures else "，全部通过"))
        return 1 if failures else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(_selftest())
