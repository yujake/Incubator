"""表 CRUD 工具（A/B/C/D 共用的数据面原子动作）。
## 为什么这些工具长这样
`base.py` 已经把"工具"这件事的形状定下来了（名字 / JSON Schema / 副作用声明 /结构化返回）。本模块只负责把这些形状接上真实数据，因此有三条硬性
规矩：
1. 写操作一律走 `store.tx(...)`，并且显式声明它要碰的每一张表。包括 `counters` —— `alloc_id` 在事务内改计数器，没声明就会 
`StoreError`。更要紧的是：`Tx.rows()` 只允许读已声明的表，所以"声明"实际上就是"这次操作会依赖哪些表的一致性"，漏声明会在运行时报错而不是悄悄读到
脏数据。
2. 读操作不加锁。 `store.rows()` 是无锁快照读，只用于展示/统计。 C 的分析任务会对同一批数据反复组合查询；如果每次只读都去抢排他锁，就会把 A/B 的
写入挡在外面。写工具独占锁、读工具无锁 —— 这个分工是刻意的。
3. 业务性失败返回 `fail(...)`，不抛异常。"名字重复""被关系引用所以不能删""字段拼错了"这些都不是环境故障，而是调用方需要看到并纠正的信息。抛异常会打断智
能体的循环，而它恰恰是唯一能修好这个错误的一方。
## 派生字段：为什么工具要顺手补
`relations.concept_group_key` / `quote_normalized` / `dedup_key` 都是纯派生字段（见 
`agent_b.py` 的写入路径）。`verify` 会用 `textutil.concept_group_key(concept_ids)`独立复算并比对，不一致就是
`stale_group_key`（错误级）。工具建的行若不补这几个字段，就会造出"结构合法但 verify 报错"的行 ——所以 create 时字段为空就补、
update 时依赖变了且调用方没显式给就重算。调用方显式给的值永远优先（否则"给定字段被悄悄改写"比缺字段更难排查）。
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
from .. import store as _store_mod
from .. import textutil as _text
from ..interactions import IdSpaceExhausted, next_prefixed_id
from ..store import IdExhausted, Store, StoreError, Tx
from .base import ToolError, ToolRegistry, ToolResult, ToolSpec, fail, ok, tool

#: 各表的表名（从 schema 反射，不手抄）。
ALL_TABLES: tuple[str, ...] = tuple(S.TABLES)

#: 按 DESIGN-TOOLS.md §1.1，表与文件的 CRUD 对 A/B/C/D 全部开放。
TOOL_ROLES: tuple[str, ...] = ("A", "B", "C", "D")

#: `table.list` / `table.search` 的 limit 边界。上限 500 是防"一次把整表灌进上下文"：
#: 工具层的读者是 LLM，返回 1 万行对它是纯噪声（还会顶掉真正有用的内容）。
LIST_LIMIT_MIN, LIST_LIMIT_MAX, LIST_LIMIT_DEFAULT = 1, 500, 50
SEARCH_LIMIT_MIN, SEARCH_LIMIT_MAX, SEARCH_LIMIT_DEFAULT = 1, 500, 50

#: 建行前的"探针 ID"里那几位数字的取值（当前宽度下全 9）。见 `_probe_id`。
_PROBE_ID = "9" * S.ID_DIGITS


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

    `tasks` 是唯一带角色过滤的一张表（业主 2026-10-24 裁定「普通代理能追一层，
    M能想追几层追几层」）：通用读口不许把全表交给非主控角色，否则
    `table.list("tasks")` 就是那条"想追几层追几层"的绕过路径。过滤口径见
    `_visible_tasks`（本文件），全树那一半在 `conductor.watch`（只有 M 拿得到）。
    """
    _spec_of(table)  # 提前校验表名，给出比 KeyError 更清楚的错误
    rows = ctx.store.rows(table)
    if table == "tasks":
        return _visible_tasks(rows, role=_caller_role(), task_id=_caller_task_id())
    return rows


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
    except ValueError as e:
        # 2026-10-17（子代理 tools 根因 B）：`schema.PageRange.__post_init__` 抛的是
        # 「ValueError」（"页码必须 >= 1" / "start 不能大于 end"），原来只捕 TypeError
        # ⇒ 本该是 `validation` 的可读拒绝，被 `call` 兜成 "库内部出错"（`kind=unexpected`）。
        raise ToolError(f"{table} 行校验失败：{e}") from e
    try:
        obj.validate()
    except ValueError as e:
        raise ToolError(f"{table} 行校验失败：{e}") from e

    canonical = obj.to_dict()
    extra = {k: v for k, v in raw.items() if k not in canonical}
    return obj, {**extra, **canonical}


def _jsonable_default(value: Any) -> Any:
    """把反射出来的默认值转成"能落进 JSON"的形态。
    ## 为什么必须有这一级（2026-10-13 真机，`p9-t1-nolean` 的三跳那一趟）
    `statements.page_range` / `dependencies.page_range` 的默认值是一个 「`PageRange`实例」，而 
    `table.schema`（不带 `table` ⇒ 反射全部表）原先把它原样塞进返回里。后果不是"少看一眼结构"，而是「这一趟循环在落产出时崩」：子代理 B 被二级唤起
    做 `register_statement`，它第一步读了 `table.schema`，随后这一趟在记步/落产出时`json.dumps` 抛 
    `TypeError: Object of type PageRange is not JSON serializable`⇒ 整趟以 `failed` 收场（实测
    t-0020 / t-0021 / t-0024 三条全废）。
    口径：「只读工具的返回必须能被如实记录」 —— 记录不了就等于这一趟没有产出（"我查了"落不到盘上）。所以这里按对象自己的 `to_dict()`（schema 的行对象都
    有一份）→ `dataclasses.asdict` → 递归容器 的顺序降级；最后一档兜底成字符串，宁可让那一格读起来粗糙，也不许让一个只读工具的返回把整趟运行弄崩。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _jsonable_default(to_dict())
        except Exception:  # noqa: BLE001 —— 转不动就走下面的降级，不许在这里抛
            pass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable_default(dataclasses.asdict(value))
    if isinstance(value, (list, tuple, set)):
        return [_jsonable_default(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _jsonable_default(v) for k, v in value.items()}
    return str(value)


def _probe_id(table: str) -> str:
    """建行前用来"预演校验"的占位 ID（按这张表自己的 ID 契约造）。
    为什么需要预演：4 位 ID 是 `alloc_id` 在事务内发出去的，而只要发过号，计数器就已经脏了 —— 哪怕这行随后校验失败、什么都没落盘，号也收不回来，表现为 
    `verify` 的 `id_gap` 警告。所以先用一个合法占位 ID 把"字段/取值有没有问题"查一遍，只有真到了发号那一步才进入事务。
    ## 占位 ID 必须满足"这张表自己的 ID 契约"（`P-17`）
    `schema` 的过程记录契约是 `<前缀>-NNNN`（`PROCESS_ID_PREFIXES`：`search_requests` = `r`、
    `reprocess_requests` = `p`、`tasks` = `t`），而实体表用的是裸 4 位。此前这里对所有表都返回裸 `"9999"`，于是
    `schema` 把 `require_process_id` 接进 `SearchRequest.validate` 之后，
    `table.create(table="search_requests")` 在预演那一步就被自己的校验拒掉（实测原文：
    `search_requests 行校验失败：request 的过程记录 ID 必须是「前缀 'r' + 连接号 + 恰好 4 位数字」（如 r-0001），收到 '9999'`），
    连事务都进不去 —— 建行功能整个失效。占位值因此不能写死一种形态，而要从 `schema` 的声明面读前缀：前缀只有一处定义，这里不另抄一份。
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
    `interactions.next_prefixed_id` 负责取号规则（max+1、跳过已占用、前缀守卫），但它没有任何上限保护：表里已经用到`r-9999` 时，它会给出 `"r-10000"`。
    而 `r-NNNN` 是一个4 位契约，不是风格偏好：
    - `store.MAX_ID`：`MAX_ID = 9999`，"4 位 ID 的上限。用满即 fail-closed （DESIGN.md §0.1 C4）"——项目级的规则是宁可显式失败，也不静默升位宽；
    - `tests/test_agent_c_service.py` 里直接断言`S.is_valid_id(row["request_id"][2:])` —— `"10000"` 不是合法 4 位 ID；
    - `SearchRequest.validate` 现在也查前缀与 4 位形态（`P-17` 的`require_process_id`），但那只在落库那一刻生效，而取号发生在落库之前 ——越界号必须在发出
    来的那一刻就挡住，否则计数器已经脏了（`id_gap`）。判据在"发号"与"落库"两处都在，不是重复：一处保证不发，一处保证落了也非法。
    # 待修：按 FC-03 的口径，这道上限最好下沉进 `interactions.next_prefixed_id`# 本身（那才是取号的唯一实现，agent_c/d/f/cli/demo 都直接调它，它们现
    在同样# 没有上限 —— 也就是说直接调它的路径仍会产出 `r-10000`）。# `interactions.py` 是 FC-27 禁改区（auth-audit），我不改它，因此把守卫放在# 工具层的这一
    个函数里，并让 `research_tools` 也调它（不是各写一份）。
    """
    # 判据本体在 `_assert_process_id_in_space`（过程记录通用版）：这里只把
    # "哪张表用哪个前缀"这两个参数固定成 `search_requests` 与 `r`。
    # `research_tools` 与既有调用方按这个名字取用，名字与语义都不动。
    return _assert_process_id_in_space(new_id, prefix="r", table="search_requests")


def _assert_process_id_in_space(new_id: str, *, prefix: str, table: str) -> str:
    """`<前缀>-<号码>` 的编号空间守卫（过程记录通用版）。

    为什么参数化成"前缀 + 表名"而不是各写一份：过程记录不止 `search_requests`
    一张（`schema.PROCESS_ID_PREFIXES` 里还有 `p` 与 `t`），而"号必须落在编号
    空间内"这条判据只能有一处 —— 复制一份出来，两处的上限就会漂移，
    而漂移的表现是"一处 fail-closed、另一处静默升位宽"。

    宽度与上限都从 `schema` 现取（2026-10-14 四位改六位之后，这里原本写死的
    `9999` 与"4 位契约"会变成假读数）。
    """
    from ..store import MAX_ID as _MAX

    digits = new_id[len(prefix) + 1:] if new_id.startswith(f"{prefix}-") else ""
    if not digits.isdigit() or int(digits) > _MAX:
        raise ToolError(
            f"{table} 的 {prefix}-{'N' * S.ID_DIGITS} 编号空间已用尽（上限 {_MAX}），"
            f"取号器给出的是 {new_id!r} —— 超长号会静默违反 {S.ID_DIGITS} 位契约"
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
    见 `schema.ID_COUNTERS` 的注释：`search_requests` 的 id_kind 是 "request"，它不在 `ID_COUNTERS` 里，所以 `alloc_id("request")` 会直接报"未知
    ID 类别"。本函数原先自己扫描行取最小可用号，而 `research_tools` 里另有一份"取 max+1"的副本、`interactions.next_prefixed_id` 里还有第三份（带前缀守卫）—— 同一个
    `search_requests`表有三个取号器，语义互相冲突：表里只有 `r-0001`、`r-0003` 时这边给 `r-0000`、那边给 `r-0004`。"最小可用号"还有更坏的一面：它会复用已删行的号，而
    `literature.source_request_ids` 与 `research_questions.waiting_request_ids`都长期引用 `r-NNNN` —— 号一旦被复用，溯源会静默指向另一条请求。
    `interactions.next_prefixed_id` 的 docstring 自己写着"删除中间行不会导致撞号"。所以那个语义被放弃了（连同`tests/test_tools_table_fs.py`里断言 `"r-0000"` 的那
    一行一起改）——那是修正一条编码了错误行为的断言，不是放宽断言。`P-4` 之后：上限在 `next_prefixed_id` 里，类型在这里翻译`interactions.next_prefixed_id` 现在自己挡越界（判据只有一份）。它
    抛的是具名的 `IdSpaceExhausted`（继承`ValueError`），这里把它精确翻成工具层的`ToolError` —— 否则它会一路冒到 `ToolRegistry.call` 被兜成 `kind='unexpected'`，
    于是"编号空间用尽"（已知、可处理）与"工具内部有 bug"在下游同形。不把整个 `ValueError` 都翻掉：`next_prefixed_id` 也会因为"prefix 带了连接号"抛 `ValueError`，那是调用方编码错误，应当
    保持原样冒出去。实现只有一份：`_next_process_id`（过程记录通用），这里只固定"`request_id` + `r` + `search_requests`"这三个参数。
    """
    return _next_process_id(rows, id_field="request_id", prefix="r",
                            table="search_requests")


def _allocate_id(tx: Tx, table: str) -> str:
    """按这张表在 `schema` 里的声明发一个主键。

    两类分开：`ID_COUNTERS` 覆盖的实体表走编号计数器（用满抛 `IdExhausted`）；
    过程记录表（`id_kind` 不在 `ID_COUNTERS` 里）走 `interactions.next_prefixed_id`。
    主键字段名与前缀一律从 `schema` 现取 —— 这里不再写死任何一张表的对应关系。
    宽度同理：形态只有 `schema.format_id()` 一处（2026-10-14 由四位改六位）。
    """
    spec = _spec_of(table)
    kind = spec["id_kind"]
    if kind in S.ID_COUNTERS:
        return tx.alloc_id(kind)
    return _next_process_id(tx.rows(table), id_field=spec["id_field"],
                            prefix=S.PROCESS_ID_PREFIXES[kind], table=table)


# ---------------------------------------------------------------- 手填主键的受控拒绝（D4）
def _hand_typed_id_refusal(table: str, payload: Mapping[str, Any],
                           idf: str) -> ToolResult | None:
    """这一笔把"本该由台账分配的号"按前缀手填了吗？手填了 ⇒ 受控拒绝（`None` = 照常写）。

    ## 真机形态（`draft/156` 的 D4，已核）
    B 按 `rel-` 前缀的直觉给 `relations` 填了 `relation_id="rel-000001"`，拿到的拒信是
    "`relation_id` 必须是 6 位十进制字符串（如 000000…）"—— 那句话只说"位数不对"，
    模型据此只能猜"那我该填几位"，猜不到"这一格根本不该我填"。同族还有 `stmt-1` /
    `p-1`（按表名缩写手填）、`p-000001` 填进 `request_id`（前缀认错表）。

    ⇒ 拒信要说清三件事，一句话说完（模型读的是这一句，不是我们的注释）：
      ① 这一格由台账分配；② 不要手填，去掉它即可；③ 前缀号只有过程记录那种人工号才用
      （并且点名这一张表的人工号长什么样 —— 如果它允许手填）。

    ## 判据为什么是"带前缀"而不是"给了主键就拒"
    `000123` 这种当前宽度的裸号是合法的手工号（`Relation.validate` 认它，`create`
    也照收），所以不能一刀切 —— 那会误伤合法的显式建行（正控见
    `tests/test_hand_filled_ids_are_refused.py` 的 (c) 两档）。真正要堵的是"按前缀直觉
    编一个号"，而它有一个可判定的形态：`schema.looks_like_prefixed_id`。那一条是这条
    拒绝的检测谓词，单独成函数就是为了让"打桩成永假 ⇒ 本拒绝失效"这条负控可写。

    ## 为什么它先于兜底路由（`_direct_write_disposal`）
    手填的号是"这一笔输入本身错了"，与"该由谁执行"无关：`statements` 的 `stmt-1` 若先
    被路由给秘书，秘书会照它自己的判据发一个新号并把行落下 —— 于是模型的输入被静默
    改掉（正是本批 D5 要防的同一种形态）。先拒，模型读到的才是"这一格不该你填"。
    """
    if not idf or not payload or idf not in payload:
        return None
    value = payload.get(idf)
    if not isinstance(value, str) or not value.strip():
        # 空串 = "我不填，让台账发号"（`tests/test_direct_write_is_routed_to_the_secretary.py`
        # 就有一档显式传 `stmt_id=""`），不是手填。
        return None
    if not S.looks_like_prefixed_id(value):
        return None
    spec = S.TABLES.get(str(table or ""))
    if spec is None:
        return None
    manual_prefix = S.PROCESS_ID_PREFIXES.get(str(spec["id_kind"]))
    got = value.strip()
    if manual_prefix is not None and got.split("-", 1)[0] == manual_prefix:
        # 正控：这一张表的人工号就是这种前缀（`search_requests` 的 `r-000001`）⇒ 照常写。
        return None
    if manual_prefix is None:
        shape = (f"`{table}` 吃的是 {S.ID_DIGITS} 位十进制编号（如 {S.format_id(0)}，"
                 "也就是整格不写、让台账发）")
    else:
        shape = (f"`{table}` 的人工号前缀是 `{manual_prefix}`"
                 f"（如 {manual_prefix}-{S.format_id(1)}）")
    return fail(
        f"{idf} 由台账分配，这一格不要手填（去掉它即可）；前缀号只有 `r-` 那种"
        f"人工号才用 —— {shape}，收到 {got!r}。",
        table=table, kind="hand_filled_id", field=idf, got=got,
    )


# ---------------------------------------------------------------- 外键检查
#: 删除某张表的行之前，必须查清"谁在引用它"。
#: 格式：被删表 -> ((引用表, 引用字段, 引用表的主键字段), ...)
#:
#: 为什么必须查：静默删掉被引用的行，`verify` 之后会报 `dangling_concept` /
#: `dangling_lit`（错误级），而那时"原来是谁引用的"已经查不出来了 ——
#: 证据在删除的那一刻就丢了。在删除前拦下，是唯一能给出可操作错误信息的时机。
_REF_SPECS: dict[str, tuple[tuple[str, str, str], ...]] = {
    # S1r 并表之后概念行住 `statements`（`kind="concept"`）⇒ "删一条概念行之前
    # 先查谁引用了它"这件事挂在新家上：`relations.concept_ids` 与
    # `research_questions.related_concept_ids` 照旧，`statements.derived_from`
    # 是本表内互相引用（verify 的 `dangling_stmt_ref` 就是这条）。
    "statements": (
        ("relations", "concept_ids", "relation_id"),
        ("statements", "derived_from", "stmt_id"),
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
_BLOCKING_TARGETS: tuple[str, ...] = ("statements", "literature")


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
    # 命中校验（`draft/37` §2 R1b / §16 P2 的 A 行）：`matched` 参与判据分支
    # （`verify.mismatch_literature_processed` 读它决定"这一篇能不能被消化"）⇒
    # 必须登记；不登记 = 参数期静默不校验（与 `dependencies.status` 同一族）。
    ("literature", "matched"): "LIT_MATCH_STATUSES",
    ("relations", "status"): "RELATION_STATUS",
    ("research_questions", "status"): "QUESTION_STATUSES",
    ("research_questions", "priority"): "PRIORITIES",
    ("analysis_reports", "kind"): "REPORT_KINDS",
    # 猜想（`draft/30` §T1 第 6 处）：状态与形态各有受控词表，不登记就会被静默不校验。
    ("conjectures", "status"): "CONJECTURE_STATUSES",
    ("conjectures", "form"): "CONJECTURE_FORMS",
    # 命题台账（`draft/37` §16 P1 第 6 处触点）：`origin` / `status` / `evidence_kind`
    # 各有一条判据分支（`verify` 的不变量与"报告分栏"都读它们），所以必须登记 ——
    # 不登记的表现是参数层静默不校验，即"写进去一个谁都不认识的取值，没人响"。
    # `kind` 刻意不登记：它不是受控词表（理由见 `schema.Statement` 的 docstring）。
    ("statements", "origin"): "STATEMENT_ORIGINS",
    ("statements", "status"): "STATEMENT_STATUSES",
    ("statements", "evidence_kind"): "EVIDENCE_KINDS",
    # 依赖状态这一条是补的历史缺口：`DEP_STATUSES` 从 FC-23 起就有四档语义
    # （closed / dangling / external_unavailable，今天又加了 refuted / disputed），
    # 而它从来没登记在这里 ⇒ 走 `table.*` 写 dependencies 时 `status` 不受词表校验，
    # 只有 `schema.Dependency.validate()` 那一层拦得住（那是写盘期，不是参数期）。
    # 两层的区别：参数期拒绝会告诉调用方"允许哪些取值"，写盘期只给一句异常。
    ("dependencies", "status"): "DEP_STATUSES",
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


# ---------------------------------------------------------------- 直写兜底（路由）
#
# 历史（读这一节之前先看一眼，否则会以为"判据被放宽了"）：
#   2026-10-19 晚的形态是「拒 + 拒信里逐字指路」（`projects/mp2/sessions/mp2-7.jsonl`
#   第 97 行：`table.create(table="statements")` 手写 `bits={}` 与
#   `evidence_kind="heuristic"`）。业主 2026-10-24 的裁定把「处置」换掉了：
#   「不应该是提醒智能体要走秘书，而是自动将直写请求路由到秘书接管」。
#   模型那一侧现在读到的是 `_direct_write_disposal`（先兜底、兜不了才拒）；
#   判据本身仍是 `store.direct_write_refusal`（`Store.tx` 的提交块读同一个函数）。
#
# 业主 2026-10-24 两段逐字：
#   「关于直写statements的问题，不应该是提醒智能体要走秘书，而是自动将直写请求路由到秘书接管」
#   「还有哪些动作是被"需要经秘书"拦截的？都走自动路由。甚至包装得足够好后可以让智能体
#    对秘书的存在无感，只是知道某些动作会有人帮他兜底。」
#
# 分工（与 `store.DIRECT_WRITE_ROUTES` 那一格逐字对齐）：
#   判据 = `store.direct_write_refusal`（没变：通用写口就是不许自己写这些表）；
#   处置 = 本节的 `_direct_write_disposal`：先问"这一笔能不能交给兜底方"，
#          能就交（判据一条不跳过），不能才拒。
# 路由只换入口，不换判据：兜底方各自的校验（秘书的洗格式 / 出处 / 引文 / 升档，
# litstage 的受控理由码与配额，`register_dependency` 的"来源必须在册"）全部照跑，
# 所以"接管"不等于"放行"。
#
# 三态（返回形状见 `_routed_ok` / `_routed_refused` / `_route_unavailable`）：
#   | 结局 | ok | `state` | 读数 |
#   |---|---|---|---|
#   | 兜底方办成了 | True | routed | `backstop` / `what_happened` / `row` / 编号 |
#   | 兜底方拒（含它自己的校验） | False | refused_by_backstop | `refused_by_backstop` 原话 |
#   | 兜底方不可达（异常 / 没实现） | False | unknown | 不折成成功 |
#   | 野路（载荷碰派生面 / 意图不明 / 没有正路的表） | False | refused | `direct_write_refused` |
#
# 仍然要拒的（逐条，负控在 `tests/test_direct_write_is_routed_to_the_secretary.py`）：
#   1. 载荷带 `_NOT_ROUTABLE_KEYS` 里任何一格（`bits` / `verification_id` / `reviewed_by` /
#      `created_by`）—— 那是写入期现算的派生面与别人的签名面，接管它等于把"绕开推导"
#      洗成"系统代劳"；
#   2. `table.update` 只改 `proof_text` 而不改 `statement_full` —— 这一格的正路是 B 的
#      `own.register_statement`（同一条 `statement_full` + 新正文 ⇒ canonical 覆盖、
#      旧正文进 `proof_history`、旧签转 stale），通用写口不接管它（它同时能改
#      `bits` / `quote_verified`，而没有任何东西核过那些字段）；
#   3. 迁移 / 账本类表（`counters` / `tasks` / `usage_ledger` / `eval_results`）与
#      "意图读不出来"的 `lit_candidates` 更新；
#   4. 依赖边的"就地改"（没有这条正路：改来源就是另一条边）；
#   5. 带 `tool:` 记号的裸事务 —— 它根本不经这里，由 `Store.tx` 的提交块逐笔拒。

#: 兜底路由的类目名（`errorstats.ERROR_CATEGORIES` 的 `routed_to_backstop` 那一档）。
#: 结局码是 `<类目>.<兜底方>[.<结局>]`：类目一格、结局分开计（成功 / 兜底方拒 / 不可用）。
ROUTED_CATEGORY = "routed_to_backstop"

#: 全部结局码（逐条写出来，不靠运行时拼）。
#:
#: 为什么必须逐条写字面量：`errorstats` 的"码 → 类目"那张表要逐条登记出处，而它的判据
#: （`tests/test_error_action_stats.py::test_every_category_has_a_code_that_really_exists_in_the_source`）
#: 要求那个码真的出现在出处文件里。只在运行时用 f-string 拼出来的码，在那条判据眼里
#: 就是"编的"。所以字面量在这里、拼装只允许拼出这张表里的东西（`_route_code` 末尾那条断言）。
ROUTED_CODES: tuple[str, ...] = (
    "routed_to_backstop.secretary",
    "routed_to_backstop.literal",
    "routed_to_backstop.secretary_refused",
    "routed_to_backstop.literal_refused",
    "routed_to_backstop.secretary_unavailable",
    "routed_to_backstop.literal_unavailable",
)

#: 路由不接管的载荷键（"野路"的第二档，见上面"仍然要拒的"第 1 条）。
_NOT_ROUTABLE_KEYS: frozenset[str] = frozenset(
    {"bits", "verification_id", "reviewed_by", "created_by"})

#: `statements` 的登记归属（2026-10-26，D8）：只有 B 的 `register_statement` 能写。
#:
#: 为什么不是"路由到秘书就够"：路由把调用方的角色原样传给秘书，而非 B 的角色会被
#: 秘书按它自己的判据拒（`not_statement_writer`）—— 那道拒是"兜底方拒"，读数上分不清
#: "这次直写本来就该拒"与"兜底方今天不可用"。这一档的语义是前者：`statements` 的
#: 每一格都带语义（五元位 / 依赖面 / 非平凡度 / 定理名），而它们只长在 B 的那一笔上。
STATEMENTS_REGISTERED_BY_B = "statements_are_registered_by_b"

#: 这一档的拒信（逐字，见 D8 的裁定）：说清四样与出口，不把模型劝到墙角。
STATEMENTS_BY_B_REFUSAL = (
    "证明内容写进 statements 只能经 B 的 `register_statement`（它同时算五元位、读 "
    "`## 依赖` 落依赖边、判非平凡度、洗定理名）。你这一笔直写会让这四样全空 —— "
    "请把手稿与命题交给 B。"
)


def _statements_are_registered_by_b(role: str) -> bool:
    """这一次写 `statements` 的是不是 B 的登记那一笔（反真空的判据只有这一处）。

    空串 = 没有角色挂点（脚本 / 单测 / 直接调 handler），**不是"非 B"**。这一档刻意
    fail-open，理由三段：

    1. 三态纪律：`conductor.current_caller_role()` 的空串是"没有挂点 / 没查"，不是
       "查过了、结论是不是 B"。把空串判成非 B，等于把"没查"折成"查过且不合格"。
    2. 放行的只是这一格，兜底仍然 fail-closed：干净载荷会走 `_route_to_secretary`，
       用 `role=""` 调 `Secretary.record_statement`，被 `not_statement_writer` 拒
       （`routed_to_backstop.secretary_refused`）；带 `bits` 的载荷在
       `_NOT_ROUTABLE_KEYS` 那一档被拒（`direct_write_refused`）。两条都 0 行 ——
       所以"这里放行"不等于"能写"。
    3. 谁会走这一条：脚本、单测、直接调 `table_create` / `table_update` 的夹具
       （`ToolContext.actor` 恒为 `"tool"`，没有发起人这一格）。生产里
       `AgentLoop._do_tool` 用 `calling_as` 包住每一次工具调用，F / A / C / D / E / G /
       H / M / V 都会拿到可读角色并在这一格被拒；把空串也拒会误伤内部播种，
       且与 `test_statement_write_is_the_secretarys_only.py` 里"带 bits ⇒
       direct_write_refused"的既有读数分家。
    """
    got = str(role or "")
    return not got or got == "B"


def _wild_road_reason(table: str, why: str) -> str:
    """野路（兜底方也接不住）时的拒信正文：只说"这一笔为什么不能落"，不指路。

    业主 2026-10-24 的追加口径逐字：「只有真的办不成（秘书拒 / 参数非法）才把理由
    原样带回，且理由里不出现'请改用某个工具'的指路语」。所以这里不给工具名，
    只说这一笔缺什么 / 为什么不能落盘。
    """
    return (f"{_store_mod.DIRECT_WRITE_REFUSED}：这一笔写请求没有由通用写口落盘，"
            f"也没有兜底方接得住（表 {table!r}）：{why}"
            "整笔不写：盘上那一行一个字节都没变。")


def _route_code(backstop: str, state: str = "") -> str:
    """结局码：`routed_to_backstop.<兜底方>` / `.…_refused` / `.unavailable`。

    为什么结局写进码里：`errorstats`（只读、按码归类的那个读数）拿到的只有一段文本，
    "路由成功了"与"兜底方拒了"如果共用一个码，那一档就分不开 —— 而分开正是业主
    2026-10-24 第 3 条要的（"成功 / 被兜底方拒 分开计"）。
    """
    who = str(backstop or "unknown")
    tail = str(state or "")
    code = f"{ROUTED_CATEGORY}.{who}" if not tail else f"{ROUTED_CATEGORY}.{who}_{tail}"
    # 拼出来的码必须已经在 `ROUTED_CODES` 里登记过（否则 `errorstats` 那张表里没有它，
    # 这一笔就会掉进"没见过的东西不许编"那一档 —— 那比没有读数更坏）。
    # 没登记 ⇒ 退成裸类目名：`errorstats` 会把它读成"未归类"（看得见），而不是记到别的类目上。
    return code if code in ROUTED_CODES else ROUTED_CATEGORY


def _caller_role() -> str:
    """这一次工具调用是哪个角色发起的（空串 = 读不到，不是"没有角色"）。

    为什么从 `conductor.current_caller_role()` 现读：工具的形状里没有"我是谁"这一格
    （`TableContext.actor` 是装配期绑的常量 "tool"，不是发起人）。`conductor.calling_as`
    在 `AgentLoop._do_tool` 里包住每一次工具调用（agent_loop.py:6169），所以生产路径上
    这一格总是有值；只读工具、脚本与单测里没有挂点 ⇒ 空串。
    这个值只「转交」给兜底方（"谁要求写这一条命题"），不替兜底方放宽它的判据：
    秘书那条路有"只有 B 能交命题内容"的规矩，路由把它原样传过去。
    """
    try:
        from ..conductor import current_caller_role
    except Exception:  # noqa: BLE001 —— 读不到就是读不到（空串），不编一个角色出来
        return ""
    try:
        return str(current_caller_role() or "")
    except Exception:  # noqa: BLE001
        return ""


def _caller_task_id() -> str:
    """这一次工具调用是哪个台账号发起的（空串 = 读不到，不是"零号"）。

    与 `_caller_role` 同一处挂点（`AgentLoop._do_tool` 的 `calling_as`），但它是
    `tasks` 行级过滤唯一能用的身份：角色名只说"我是哪一类代理"，说不了"我这一支
    是哪一棵子树"。空串 = 没有挂点（脚本 / 单测），`_visible_tasks` 会据此拒读，
    而不是把"不知道我是谁"折成"可以看全表"。
    """
    try:
        from ..conductor import current_task_id
    except Exception:  # noqa: BLE001 - 读不到就是读不到（空串），不编一个号出来
        return ""
    try:
        return str(current_task_id() or "")
    except Exception:  # noqa: BLE001
        return ""


#: `tasks` 读侧的可见面：自己 + 直接下级 + 自己的父（父是向上的一格，不漏下去）。
#: 为什么不是"自己整棵子树"：普通代理只能追一层（业主 2026-10-24 原话），给子树
#: 等于让 `table.list("tasks")` 变回那条绕过路径。为什么留父那一行：它是"我这一趟
#: 从哪来"，本来就在提示词里（`{{parent_task_id}}`），读它不增加任何可见面。
_TASKS_VISIBLE_CHILD_DEPTH = 1

# ---------------------------------------------------------------- `tasks` 的写侧判据
#
# 这一节堵的是"通用写口能伪造任务台账"这个权限面缺口（D12，2026-10-27 实测）。
#
# 背景：`store.direct_write_refusal` 只拒 `statements` 与 `lit_candidates`（store.py:251），
# `tasks` 不在其中 —— 于是 `table.create(table="tasks")` 对任何角色都是敞开的。
# 改前实测（那一趟的一次性写宽探针，已随 temp 清理；D 角色，全部 ok=True）：
#
#     [1_给自己一条 work]            id=t-000004
#     [2_种到别人名下]               id=t-000005   ← 把一条 delegation 种进 E 的板，called_by 写成自己
#     [3_直接写成 done]              id=t-000006   ← 绕过状态机伪造一条"已收口"
#     [4_kind=notice+expects=ack]    id=t-000007
#
# 为什么这不是"参数校验"而是权限面：一条伪造的板项会让销号门的"板项没清"读数失真
# （`conductor_retire_child` 读的就是"名下还有几条 item_state != done"），也会让
# `Conductor._set_item` 的两条不变量（只许往后走 / 没 seen 不许 done）整个失效 ——
# 而盘上那一行看起来完全合法。
#
# 三条判据各有一个机器码（理由码进 `kind=`，拒信进 `error`）：
#   a) 板项只能由它的收件人自己落（`parent_task_id` 必须是调用者的台账号）；
#   b) 新行 / 补丁不许伪造收口（`item_state` 只许 queued，`item_close` 只许空）；
#   c) 不许绕过投递写"已读"（`item_state="seen"` 与 `seen_by` / `seen_step` 都拒）。
# 收口唯一的路仍是 `Conductor._set_item`（`conductor.ack` 与 `mark_item_seen` 的那两条）。
TASKS_POSTED_BY_THEIR_OWNER = "tasks_are_posted_by_their_owner"
TASKS_CLOSE_ONLY_THROUGH_THE_MACHINE = "tasks_close_only_through_the_item_state_machine"
TASKS_SEEN_ONLY_THROUGH_DELIVERY = "tasks_seen_only_through_delivery"


def _tasks_write_refusal(*, table: str, row: Mapping[str, Any],
                         op: str) -> ToolResult | None:
    """`tasks` 行的通用写口判据：返回 None = 放行，否则是受控拒绝的 `ToolResult`。

    `op` 只用于措辞（`create` / `update`）：两条路判的是同一件事 ——
    "这一笔改动替你改的是谁的任务台账"。

    三态纪律：判据只看调用上下文（`_caller_task_id` / `_caller_role`）与载荷。
    没有调用上下文（脚本 / 单测里没挂 `calling_as`）⇒ 一律拒（fail-closed）：
    "不知道是谁"不能读成"谁都可以"。
    """
    if str(table) != "tasks":
        return None
    payload = dict(row or {})
    me = _caller_task_id()
    role = _caller_role()
    where = "table.create" if op == "create" else "table.update"
    if not me:
        return fail(
            (f"{TASKS_POSTED_BY_THEIR_OWNER}：`{where}(table=\"tasks\")` 需要知道是哪一趟代理"
             "在写 —— 这一次没有调用上下文（没有台账号）⇒ 拒。"
             "任务台账的写者只有两条正路：`conductor.post_task`（给自己落一条活）与框架自己的"
             "收口路径（`conductor.ack` / `mark_item_seen` / `open_item`）。"),
            table="tasks", kind=TASKS_POSTED_BY_THEIR_OWNER)
    # ---- a) 只许给自己落项
    if "parent_task_id" in payload:
        owner = str(payload.get("parent_task_id") or "")
        if op == "create" or owner:
            if owner != me:
                return fail(
                    (f"{TASKS_POSTED_BY_THEIR_OWNER}：`parent_task_id` 是"
                     f"{owner or '（空）'}，不是你（{me}）⇒ 板项的收件人只能是调用者自己。"
                     "要让别人办一件事，走 `conductor.summon`（那条正路会自己建行、自己发号）。"),
                    table="tasks", kind=TASKS_POSTED_BY_THEIR_OWNER)
    elif op == "create":
        return fail(
            (f"{TASKS_POSTED_BY_THEIR_OWNER}：建 `tasks` 行必须写 `parent_task_id`（收件人 = 你自己 "
             f"{me}）—— 没有收件人的行是另一类东西（顶层运行由 `conductor` 发号），"
             "不是这里能建的。"),
            table="tasks", kind=TASKS_POSTED_BY_THEIR_OWNER)
    called_by = str(payload.get("called_by") or "")
    if called_by and role and called_by != role:
        return fail(
            (f"{TASKS_POSTED_BY_THEIR_OWNER}：`called_by` 是 {called_by!r}，而你这一趟是 "
             f"{role!r} ⇒ 板项的『谁开的』不许写成别人。"),
            table="tasks", kind=TASKS_POSTED_BY_THEIR_OWNER)
    row_role = str(payload.get("role") or "")
    if row_role and role and row_role != role:
        return fail(
            (f"{TASKS_POSTED_BY_THEIR_OWNER}：这一行的 `role` 是 {row_role!r}，而你这一趟是 "
             f"{role!r} ⇒ 只能给自己落项（给别人落项不是这条路的语义）。"),
            table="tasks", kind=TASKS_POSTED_BY_THEIR_OWNER)
    # ---- c) 不许绕过投递写"已读"
    state = str(payload.get("item_state") or "")
    if state == "seen" or payload.get("seen_by") or payload.get("seen_step") not in (None, ""):
        return fail(
            (f"{TASKS_SEEN_ONLY_THROUGH_DELIVERY}：`{where}` 不许写『已读』"
             "（`item_state=\"seen\"` / `seen_by` / `seen_step`）—— 那个读数只由投递那一拍"
             "（`Conductor.mark_item_seen`）写：谁在第几步读到的，是要被读的人自己说的。"),
            table="tasks", kind=TASKS_SEEN_ONLY_THROUGH_DELIVERY)
    # ---- b) 不许伪造收口
    if str(payload.get("item_close") or ""):
        return fail(
            (f"{TASKS_CLOSE_ONLY_THROUGH_THE_MACHINE}：`{where}` 不许写 `item_close`"
             "（`acked` / `completed`）—— 收口只有一处：`Conductor._set_item`，"
             "工具面走 `conductor.ack`。"),
            table="tasks", kind=TASKS_CLOSE_ONLY_THROUGH_THE_MACHINE)
    if state and state != "queued":
        return fail(
            (f"{TASKS_CLOSE_ONLY_THROUGH_THE_MACHINE}：新行 / 补丁里的 `item_state` 只许 "
             f"\"queued\"，收到 {state!r} —— 收口、接手、投递三档都只由状态机写"
             "（`_set_item`），通用写口不许替它走。"),
            table="tasks", kind=TASKS_CLOSE_ONLY_THROUGH_THE_MACHINE)
    return None


def _visible_tasks(rows: Iterable[Mapping[str, Any]], *, role: str,
                   task_id: str) -> list[dict[str, Any]]:
    """`tasks` 的读侧过滤（业主 2026-10-24 裁定的执行点）。

    三条口径：
    - 主控 M：全表（它能想追几层追几层；全树的正路是 `conductor.watch`）；
    - 非 M 且有台账号：自己那一行 + 直接下级（`parent_task_id` 等于我、且
      `kind == ""` 的实例行）+ 自己的父那一行；
    - 非 M 且没有台账号：受控拒绝。不许"没挂身份就按全表读"——那正是这次要关的
      那条路（`table.get` / `table.list` / `table.search` / `table.count` 都经
      `_rows`，所以关在这一处就够）。

    为什么要排除板项行：`tasks` 里板项（`kind` 非空）的 `parent_task_id` 口径是
    "收件人的编号"（D89），把它们当子代理会让"我的直接下级"多出一批通报项
    （与 `Conductor._children_of` 同一条出身过滤）。
    """
    if str(role or "") == S.CONDUCTOR_ROLE:
        return [dict(r) for r in rows]
    me = str(task_id or "")
    if not me:
        raise ToolError(
            "tasks 全表只有主控 M 能读；非主控角色必须带着自己的台账号来读，"
            "而这一次调用没有台账号 ⇒ 本次没查成（不按全表兜底）。"
            "看自己的直接下级用 trace.children；要看更深的分支请向 M 请求："
            "conductor.escalate(need=\"深看请求：…\", kind=\"other\")"
        )
    by_id = {str(r.get("task_id") or ""): dict(r) for r in rows}
    mine = by_id.get(me) or {}
    parent = str(mine.get("parent_task_id") or "")
    keep = {me}
    if parent:
        keep.add(parent)
    keep |= {
        str(r.get("task_id") or "") for r in rows
        if str(r.get("parent_task_id") or "") == me and not str(r.get("kind") or "")
    }
    return [dict(r) for r in rows if str(r.get("task_id") or "") in keep]



def _direct_write_intent(table: str, op: str, payload: Mapping[str, Any]) -> str:
    """从这一次写请求读出"想做的那件事"（`store.DIRECT_WRITE_ROUTES` 的第 3 列）。

    读不出来 ⇒ 空串 ⇒ 兜底不接管（"猜一个入口"等于换判据，比拒更坏）。
    口径：
      - `table.create`：`statements` / `dependencies` ⇒ register；`lit_candidates` ⇒ add；
      - `table.delete`：⇒ withdraw（`lit_candidates` 的"删掉"必须表现为"撤掉"）；
      - `table.update`：看载荷里的 `status` 与理由栏（admitted ⇒ admit、rejected /
        `reject_reason` ⇒ reject、withdrawn / `withdrawn_reason` ⇒ withdraw），其余 ⇒ 空串。
    """
    name = str(table or "")
    kind = str(op or "")
    if kind == "delete":
        return "withdraw"
    if kind in ("create", "update"):
        if name == "statements":
            # 新建 / 改 / 升档都走秘书那一条（它自己按 statement_full 查重、按 verifications 升档）
            return "register"
        if name == "dependencies":
            # 登记一条边可以兜底；"就地改一条已登记的边"没有正路（改来源就是另一条边），
            # 故意给它一个读不出入口的意图名 —— 于是它落到"兜底不接管"那一档。
            return "register" if kind == "create" else "amend"
        if name == "lit_candidates":
            if kind == "create":
                return "add"
            got = dict(payload or {})
            status = str(got.get("status") or "").strip()
            if status == "admitted":
                return "admit"
            if status == "rejected" or str(got.get("reject_reason") or "").strip():
                return "reject"
            if status == "withdrawn" or str(got.get("withdrawn_reason") or "").strip():
                return "withdraw"
            return ""
    return ""


def _routed_shape(*, backstop: str, entry: str, table: str, state: str,
                  what_happened: str, row: Mapping[str, Any] | None = None,
                  landed_id: str = "", changes: Sequence[Any] = (),
                  requested_id: str = "", dropped_keys: Sequence[str] = (),
                  refused: str = "", detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """一次兜底处置的完整读数（三态共用同一个形状，读的人不用猜缺了哪一格）。

    `backstop` 是"谁兜的底"（`secretary` / `literal`），`routed_to` 是那条正路的入口名，
    `routed_from` 固定是 `direct_write`（这次请求本来走的是通用写口）。
    成功与失败只在 `state` / `refused_by_backstop` 两格上分叉 —— 所以读的人不必
    从两套键名里推断"这到底成没成"。
    """
    payload: dict[str, Any] = {
        "backstop": str(backstop),
        "routed_to": str(entry),
        "routed_from": "direct_write",
        "table": str(table),
        "state": str(state),
        "what_happened": str(what_happened),
        "row": dict(row) if isinstance(row, Mapping) else None,
        "id": str(landed_id),
        "requested_id": str(requested_id),
        "changes": list(changes or ()),
        "dropped_keys": list(dropped_keys or ()),
        "refused_by_backstop": str(refused),
        # 秘书那一档另外留一个同名键（业主 2026-10-24 第一条裁定逐字用的是 "refused_by_secretary"）。
        "refused_by_secretary": str(refused) if str(backstop) == "secretary" else "",
    }
    if detail:
        payload["detail"] = dict(detail)
    return payload


def _routed_ok(*, backstop: str, entry: str, table: str, what_happened: str,
               row: Mapping[str, Any] | None = None, landed_id: str = "",
               changes: Sequence[Any] = (), requested_id: str = "",
               dropped_keys: Sequence[str] = (),
               detail: Mapping[str, Any] | None = None) -> ToolResult:
    """兜底方办成了：`ok=True`，`data` 是上面那个形状。

    为什么 `error` 那一格也带一句（`ok` 仍然是 True）：`errorstats` 那份按码归类的读数
    只读 `result.error` / `warn` / `problem` / `kind` 这几个通道（见 `errorstats._step_text`），
    而"这一笔被兜底接管了"正是业主第 3 条要计的事件。所以那一格写的是接管读数、
    不是失败：`ok=True` 说明这条路走通了。正文里逐字写明这一点，避免模型把
    "有人兜底"读成"我做错了"。
    """
    data = _routed_shape(backstop=backstop, entry=entry, table=table, state="routed",
                         what_happened=what_happened, row=row, landed_id=landed_id,
                         changes=changes, requested_id=requested_id,
                         dropped_keys=dropped_keys, detail=detail)
    note = (f"{_route_code(backstop)}：{what_happened}"
            "（这一格是兜底读数，不是失败读数：ok=true 就是'系统替你办成了'）")
    return ToolResult(True, data, note, {"kind": _route_code(backstop),
                                         **{k: v for k, v in data.items()
                                            if k not in ("row", "detail")}})


def _routed_refused(*, backstop: str, entry: str, table: str, why: str,
                    changes: Sequence[Any] = (), requested_id: str = "",
                    dropped_keys: Sequence[str] = (),
                    detail: Mapping[str, Any] | None = None) -> ToolResult:
    """兜底方自己拒了：理由原样带回（不翻译、不裁剪、不指路）。"""
    data = _routed_shape(backstop=backstop, entry=entry, table=table,
                         state="refused_by_backstop",
                         what_happened="系统替你转交过，兜底方按它自己的判据拒了；这一笔没有落盘",
                         changes=changes, requested_id=requested_id,
                         dropped_keys=dropped_keys, refused=why, detail=detail)
    return fail(f"{_route_code(backstop, 'refused')}：{why}",
                kind=_route_code(backstop, "refused"),
                **{k: v for k, v in data.items() if k not in ("row", "detail")},
                detail=dict(detail or {}))


def _route_unavailable(*, backstop: str, entry: str, table: str, why: str,
                       requested_id: str = "") -> ToolResult:
    """兜底方不可达 / 这一格没实现：`state="unknown"`，不许折成成功（三态纪律）。"""
    data = _routed_shape(backstop=backstop, entry=entry, table=table, state="unknown",
                         what_happened="系统没接上兜底方：这一笔既没落盘、也没被它判过（unknown）",
                         requested_id=requested_id, refused="",
                         detail={"why": why})
    return fail(f"{_route_code(backstop, 'unavailable')}：兜底方不可达（{why}）"
                "⇒ 这一笔按'没查成'读，不是'办成了'。",
                kind=_route_code(backstop, "unavailable"),
                **{k: v for k, v in data.items() if k not in ("row", "detail")},
                detail=dict(data.get("detail") or {}))


def _direct_write_disposal(ctx: TableContext, *, table: str, op: str,
                           payload: Mapping[str, Any], id: str = "",
                           idf: str = "") -> ToolResult | None:
    """通用写口碰到"只能经正路写"的表时，先算一次处置。返回 None = 照常写。

    调用点在三个写口的入口（`table_create` / `table_update` / `table_delete`），
    在进事务之前 —— 兜底方自己会开它自己的事务，两层事务叠在一起会死锁
    （`filelock` 不可重入），所以顺序必须是"先处置、后决定要不要自己写"。
    """
    name = str(table or "")
    if not _store_mod.direct_write_refusal(name):
        return None          # 不是禁区表：一个字节都不干预
    if str(op or "") == "delete" and name != "lit_candidates":
        # 删除不制造证据：`statements` / `dependencies` 的行删掉不算"直写"（判据同 `Store.tx`
        # 提交块那一段：只有 delete 的那一笔放行）。`lit_candidates` 是唯一的例外 ——
        # 它的"删掉"必须表现为"撤掉"，所以走下面的兜底。
        return None
    if name == "statements" and not _statements_are_registered_by_b(_caller_role()):
        # F 与其余非 B 角色对这张表的直写一律受控拒绝：它们没有"五元位 / 依赖面 /
        # 非平凡度 / 洗名"那四件活，路由到秘书也只会被秘书的角色判据拒一次。
        # 位置在 `_NOT_ROUTABLE_KEYS` 之前：带 `bits` 的载荷也归这一档（它同样是直写）。
        return fail(f"{STATEMENTS_REGISTERED_BY_B}：{STATEMENTS_BY_B_REFUSAL}",
                    table=name, kind=STATEMENTS_REGISTERED_BY_B,
                    actor_role=_caller_role())
    keys = {str(k) for k in (payload or {}) if not str(k).startswith("_")}
    if op and str(op) == "update" and idf and str(idf) in keys and str(payload.get(idf)) != str(id):
        # 改主键 = 把 delete+create 伪装成 update（所有外键都指向旧代号）⇒ 不接管。
        return fail(
            f"不允许修改主键 {idf}（{id} → {payload.get(idf)}）。"
            "主键是外键的锚点，改了会让所有引用它的行变成悬空引用。",
            table=name, id=id, kind="primary_key_change",
        )
    wild = sorted(_NOT_ROUTABLE_KEYS & keys)
    if wild:
        return fail(
            f"{_store_mod.DIRECT_WRITE_REFUSED}：这一笔要写 {wild} —— "
            "那几格是写入期现算的派生面（五元位）与别人的签名 / 审计面，"
            "手写它等于把推导整条跳过，所以兜底不接管它。整笔不写：盘上一个字节都没变。",
            table=name, kind=_store_mod.DIRECT_WRITE_REFUSED, wild_keys=wild,
        )
    if (str(op or "") == "update" and "proof_text" in keys and "statement_full" not in keys):
        # 这一格的拒信改过一次（2026-10-27，业主裁定 D7）：改前写着"证明正文变了就是
        # 另一条命题，不能就地替换已登记的那一份"—— 那句话与框架的实际能力相反。
        # `statements.proof_text` 是可以就地被覆盖的（正路是 B 的
        # `own.register_statement`：同一条 `statement_full` + 新的 `proof_text`，
        # 旧正文进 `proof_history`、旧签转 stale、需 V 重签）。真机上模型读到这句
        # "不能就地替换"，就在 handoff 里写"本面内无改行写口"、把整条链停在墙前。
        # 拒信要指回真有的做法，不能把模型劝到墙角。
        return fail(
            f"{_store_mod.DIRECT_WRITE_REFUSED}：`table.update` 改不了 `proof_text` —— "
            "这一格只有一条正路，不是这里的通用写口：再交一次 "
            "`own.register_statement`（`statement_full` 与在册那一行相同 + 新的 "
            "`proof_text`）。秘书判它同一条命题 ⇒ 就地覆盖 canonical 正文，旧正文整段"
            "进那一行的 `proof_history`（每条带 `sha`/`at`/`replaced_by`），盖在旧正文上的"
            "那一签读侧转 stale（台账里那一签不删，需要 V 重签）。整笔不写："
            "盘上一个字节都没变。",
            table=name, kind=_store_mod.DIRECT_WRITE_REFUSED, wild_keys=["proof_text"],
        )
    intent = _direct_write_intent(name, op, payload)
    route = _store_mod.direct_write_route(name, intent)
    if route is None:
        if name == "dependencies" and str(op or "") == "update":
            return fail(_wild_road_reason(
                name,
                "依赖边没有「就地改」这一条正路 —— 换一个来源就是另一条边，"
                "不是把这条边改掉（它的 status 由核对那一步写，不由通用写口写）。"),
                table=name, kind=_store_mod.DIRECT_WRITE_REFUSED, intent=intent)
        return fail(_wild_road_reason(
            name,
            f"这一笔的意图读不出来（动作 {op!r}，载荷键 {sorted(keys)}）⇒ "
            "系统不替你猜该走哪一条正路。要做的那件事得写进载荷"
            "（例如目标状态与受控理由码），再交一次。"),
            table=name, kind=_store_mod.DIRECT_WRITE_REFUSED, intent=intent)
    return _route_direct_write(ctx, route=route, table=name, op=str(op or ""),
                               payload=payload, id=id, idf=idf)


def _route_direct_write(ctx: TableContext, *, route: tuple[str, str, str, str, str],
                        table: str, op: str, payload: Mapping[str, Any],
                        id: str = "", idf: str = "") -> ToolResult:
    """按 `store.DIRECT_WRITE_ROUTES` 那一行把请求交给兜底方（分发器）。"""
    backstop, _intent, entry = route[1], route[2], route[3]
    if backstop == "secretary":
        return _route_to_secretary(ctx, entry=entry, table=table, op=op,
                                   payload=payload, id=id, idf=idf)
    if backstop == "literal" and table == "dependencies":
        return _route_to_dependency_register(ctx, entry=entry, payload=payload)
    if backstop == "literal" and table == "lit_candidates":
        return _route_to_lit_backstop(ctx, entry=entry, intent=_intent,
                                      payload=payload, id=id)
    if backstop not in _store_mod.DIRECT_WRITE_BACKSTOPS:
        return _route_unavailable(backstop=str(backstop), entry=str(entry), table=table,
                                  why=(f"兜底方 {backstop!r} 不在 "
                                       f"{sorted(_store_mod.DIRECT_WRITE_BACKSTOPS)} 里"))
    # 表里登记了兜底方、实现没接上：unknown（不许折成成功，也不许折成"拒"）
    return _route_unavailable(backstop=str(backstop), entry=str(entry), table=table,
                              why="工具层没有这一格的实现（表登记了入口、代码没接上）")


def _route_to_secretary(ctx: TableContext, *, entry: str, table: str, op: str,
                        payload: Mapping[str, Any], id: str = "",
                        idf: str = "") -> ToolResult:
    """`statements` 的直写 ⇒ 秘书那条正路（`Secretary.record_statement`）。

    改（`table.update`）走"同一份内容再交一次"：把盘上那一行读出来、叠上 patch、
    整份交给秘书 —— 于是查重、升档、出处核对都还是秘书那一条在判，
    而"改哪一格"由秘书决定（升档会就地改上去，内容没变则回"已在册、不新建"）。
    """
    role = _caller_role()
    body = dict(payload or {})
    # `dropped` 只算调用方自己交上来的键（改那一档的 patch）：合并出来的整行里
    # 有一堆行对象字段（`stmt_id` / `created_at` / `status` …）不是"被丢掉的载荷"。
    allowed = _secretary_keys()
    dropped = sorted(k for k in body
                     if allowed and k not in allowed and not str(k).startswith("_"))
    requested = str(payload.get(str(idf or "stmt_id")) or "") if idf else ""
    if op == "update":
        current = None
        if id:
            current = next((r for r in _rows(ctx, table)
                            if str(r.get(str(idf or "stmt_id")) or "") == str(id)), None)
        if current is None:
            # 与不带兜底那一档同形（`tx.find` 找不到就是 not_found）：空 id 也走这里，
            # 因为"要改哪一行"根本不知道（不是"路由没成"）。
            return fail(f"{table} 里没有主键 {id}", table=table, id=id, found=False,
                        kind="not_found")
        merged = dict(current)
        merged.update(dict(payload or {}))
        body = merged
        requested = str(id)
    try:
        # ---- 2026-10-26（真机 sylow5）：这一支必须带着缝造秘书。
        #
        # 改前是 `Secretary(role, root=..., store=...)` —— 没传 `seam=`，于是
        # `record_statement` 里那条命题同一性判定（`adjudicate_proposition` →
        # `judge`）每次都在第二道闸（`if self.seam is None`）上折成
        # `checked=False`，静默退回机械判据：相似度 0.15–0.33 ⇒ 判 different ⇒
        # 同一条定理被登记 2–3 次，而 `out/secretary/proposition_verdicts.jsonl`
        # 一次都没建出来（sylow5 的真机读数）。
        #
        # `for_role_wired` 与 `Secretary(...)` 只差一件事：造秘书之前先把缝拿来
        # （秘书档没配 key ⇒ 缝是 None + `model_source` 写明为什么）。判不了时
        # 返回值里的 `proposition_adjudication` 会把这一句原样透出来。
        from ..secretary import for_role_wired

        sec = for_role_wired(role, root=ctx.store.root, store=ctx.store)
        got = sec.record_statement(body, role=role)
    except Exception as exc:  # noqa: BLE001 —— 兜底方不可达必须回 unknown，不许折成成功
        return _route_unavailable(backstop="secretary", entry=str(entry), table=table,
                                  why=f"{type(exc).__name__}: {exc}", requested_id=requested)
    refused = str(got.get("refused") or "")
    reason = str(got.get("reason") or "")
    if refused:
        return _routed_refused(backstop="secretary", entry=str(entry), table=table,
                               why=(f"{refused}：{reason}" if reason else refused),
                               changes=list(got.get("changes") or ()),
                               requested_id=requested, dropped_keys=dropped, detail=got)
    if got.get("duplicate"):
        # 秘书的判据是"同一份 statement_full 只登记一次"：这不是失败，也不是"这次写成了"
        # —— 它是兜底方的"已在册、没新建"，按兜底方拒记，并把它的原话逐字带回。
        return _routed_refused(backstop="secretary", entry=str(entry), table=table,
                               why=(reason or "duplicate：同一条命题已在册，未新建行"),
                               changes=list(got.get("changes") or ()),
                               requested_id=requested, dropped_keys=dropped, detail=got)
    created = bool(got.get("created"))
    upgraded = bool(got.get("upgraded"))
    what = ("已由系统代为登记（秘书那条正路：洗格式 / 发编号 / 查重 / 改表一次做完）"
            if created else
            "已由系统代为升档（同一份内容、更强的证据档；没有新建行）" if upgraded else
            "已由系统代为处理（秘书那条正路没有新建行，读数见 detail）")
    row = got.get("row") if isinstance(got.get("row"), Mapping) else None
    return _routed_ok(backstop="secretary", entry=str(entry), table=table,
                      what_happened=what, row=row,
                      landed_id=str(got.get("stmt_id") or ""),
                      changes=list(got.get("changes") or ()),
                      requested_id=requested, dropped_keys=dropped, detail=got)


def _secretary_keys() -> frozenset[str]:
    """秘书那条路认得的载荷键（正名 ∪ 别名）；读不到 ⇒ 空集（那一格就不报 dropped）。"""
    try:
        from ..secretary import STATEMENT_KEY_ALIASES, STATEMENT_PARAM_KEYS
    except Exception:  # noqa: BLE001
        return frozenset()
    out = set(STATEMENT_PARAM_KEYS)
    for alts in STATEMENT_KEY_ALIASES.values():
        out.update(alts)
    return frozenset(out)


def _route_to_dependency_register(ctx: TableContext, *, entry: str,
                                  payload: Mapping[str, Any]) -> ToolResult:
    """`dependencies` 的直写 ⇒ `doc.register_dependency`（那条正路的函数本身）。

    它的判据（`kind` / `status` 词表、`status=closed` 时来源必须在册、规矩 A 的
    "`source_stmt_id` 要指向一条可用的命题"）一条都不跳过 —— 路由只换入口。
    """
    def _s(key: str) -> str:
        return str(payload.get(key) or "")

    #: 那条正路的参数表里没有的键（`source_doc_id` 不是 `register_dependency` 的入参 ——
    #: 它只收三种来源）。载荷里给了就进 `dropped_keys`（看得见，不静默丢）。
    dropped = sorted(k for k in ("source_doc_id", "dep_id", "created_at", "created_by")
                     if k in payload)
    try:
        from .doc_tools import register_dependency

        row = register_dependency(
            ctx.store,
            used_by=_s("used_by"),
            kind=_s("kind"),
            label=_s("label"),
            source_lit_id=_s("source_lit_id") or None,
            source_experiment_id=_s("source_experiment_id") or None,
            source_stmt_id=_s("source_stmt_id") or None,
            path_group=int(payload.get("path_group") or 1),
            proof_no=int(payload.get("proof_no") or 1),
            page_range=payload.get("page_range"),
            quote=_s("quote"),
            status=_s("status") or "dangling",
            status_reason=_s("status_reason"),
            actor=str(ctx.actor or "tool"),
        )
    except ValueError as exc:     # 它自己的受控拒绝（词表 / 来源不在册 / 缺必填）
        return _routed_refused(backstop="literal", entry=str(entry), table="dependencies",
                               why=str(exc), dropped_keys=dropped)
    except Exception as exc:  # noqa: BLE001
        return _route_unavailable(backstop="literal", entry=str(entry), table="dependencies",
                                  why=f"{type(exc).__name__}: {exc}")
    landed = dict(row or {})
    return _routed_ok(backstop="literal", entry=str(entry), table="dependencies",
                      what_happened="已由系统代为登记这条依赖边（来源在册性照核）",
                      row=landed, landed_id=str(landed.get("dep_id") or ""),
                      dropped_keys=dropped)


def _route_to_lit_backstop(ctx: TableContext, *, entry: str, intent: str,
                           payload: Mapping[str, Any], id: str = "") -> ToolResult:
    """`lit_candidates` 的直写 ⇒ 按意图分派到 `lit.*` 那四条正路。

    这里调的是 `litstage` 那几个函数本体（槽位发号、受控理由码、入库上限、报告刷新
    都在里面），不是抄一份判据：`search_tools` 的 `_h_lit_*` 只是给它们套了一层
    工具壳。`admit` 那一档是唯一例外 —— 它还需要"登记路径"那个闭包
    （`_registrar_from_candidate`，`lit.admit` 与 `lit.admit_all` 共用的那一份），
    所以那一档直接调 `_h_lit_admit`（同一份实现，不自造第二份）。
    """
    from ..litstage import LitStageError
    from ..litstage import reject as _lit_reject
    from ..litstage import stage_entries as _lit_stage_entries
    from ..litstage import withdraw as _lit_withdraw

    actor = str(ctx.actor or "tool")
    slot = str(id or payload.get("slot") or "")
    note = str(payload.get("note") or "")
    try:
        if intent == "add":
            got = _lit_stage_entries(ctx.store, [dict(payload)],
                                     request_id=str(payload.get("request_id") or ""),
                                     batch=payload.get("batch"), actor=actor)
            staged = list(got.get("staged") or ())
            row = dict(staged[0] or {}) if staged else None
            return _routed_ok(backstop="literal", entry=str(entry), table="lit_candidates",
                              what_happened="已由系统代为追加进待新增列表（槽位号只增不复用）",
                              row=row, landed_id=str((row or {}).get("slot") or ""),
                              detail=got)
        if intent == "withdraw":
            got = _lit_withdraw(ctx.store, slot, str(payload.get("reason_code") or ""),
                                str(payload.get("withdrawn_reason") or note), actor=actor)
            return _routed_ok(backstop="literal", entry=str(entry), table="lit_candidates",
                              what_happened="已由系统代为撤掉那一槽（行留在列表里、理由写在行上）",
                              row=dict(got), landed_id=str(got.get("slot") or ""))
        if intent == "reject":
            got = _lit_reject(ctx.store, slot, str(payload.get("reason_code") or ""),
                              str(payload.get("reject_reason") or note), actor=actor)
            return _routed_ok(backstop="literal", entry=str(entry), table="lit_candidates",
                              what_happened="已由系统代为拒收那一槽（理由写在行上、行没删）",
                              row=dict(got), landed_id=str(got.get("slot") or ""))
    except LitStageError as exc:          # 兜底方自己的受控拒绝（受控理由码 / 槽位 / 配额）
        return _routed_refused(backstop="literal", entry=str(entry), table="lit_candidates",
                               why=str(exc), detail=dict(getattr(exc, "detail", {}) or {}))
    except Exception as exc:  # noqa: BLE001
        return _route_unavailable(backstop="literal", entry=str(entry),
                                  table="lit_candidates", why=f"{type(exc).__name__}: {exc}")
    if intent != "admit":                 # 表里登记了意图、实现没接上
        return _route_unavailable(backstop="literal", entry=str(entry),
                                  table="lit_candidates",
                                  why=f"没有 {intent!r} 这一格的分派")
    try:
        from pathlib import Path

        from . import search_tools as ST

        tctx = ST._Ctx(Path(str(ctx.store.root)), store=ctx.store, actor=actor)
        got_res = ST._h_lit_admit(tctx, slots=[slot])
    except Exception as exc:  # noqa: BLE001
        return _route_unavailable(backstop="literal", entry=str(entry),
                                  table="lit_candidates", why=f"{type(exc).__name__}: {exc}")
    if not got_res.ok:
        return _routed_refused(backstop="literal", entry=str(entry), table="lit_candidates",
                               why=str(got_res.error or ""), detail=dict(got_res.meta or {}))
    body = dict(got_res.data or {})
    admitted = list(body.get("admitted") or ())
    if not admitted:
        why = "；".join(str(r.get("why") or r.get("code") or "")
                        for r in (body.get("refused") or ())) or str(body.get("reason") or "")
        return _routed_refused(backstop="literal", entry=str(entry), table="lit_candidates",
                               why=(why or "一条都没入库"), detail=body)
    row = dict(admitted[0] or {})
    return _routed_ok(backstop="literal", entry=str(entry), table="lit_candidates",
                      what_happened="已由系统代为入库（条数上限与重叠检查照核）",
                      row=row, landed_id=str(row.get("lit_id") or row.get("slot") or ""),
                      detail=body)



# ---------------------------------------------------------------- 工具实现


def _with_proof_routes(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """`statements` 行的读侧派生格：这一份证明走的是哪条路（读侧接线点）。

    为什么必须有这一格：路子住在 `secretary.PROOF_ROUTES_KEY` 里（由 `Secretary.record_statement`
    写进那一行，键名带下划线），而它在任何工具读数上都没有被翻出来过 ——
    `secretary.proof_routes_of` / `proof_route_of` 这两只读侧唯一口径全仓 0 个非测试
    调用点（`docs/WIRING-AUDIT-2026-10-27.md` 第四节第一行）。后果不是"少一格"：
    "这份证明走的是哪条路"在写侧存在、在读侧不存在，模型读得到行、读不到那句话。

    这一处就是那条线的落点（`table.get` 与 `table.list` 共用同一只函数）：
    `route` 是第 1 份证明的那一句（模型最常问的就是它），`proof_routes` 是
    `{证明号: 一句话}` 的全量（JSON 键必须是字符串）。下划线那个内部键原样留着
    （它是写侧的形态，读的人有权看见原样）；两只派生格由同一处算，不各写一份。

    三态：算不出来也如实落一格（`proof_routes_problem`），不折成"没有路线"。
    """
    out = dict(row)
    if str(table or "") != "statements":
        return out
    try:
        from ..secretary import proof_route_of, proof_routes_of

        routes = proof_routes_of(row)
        out["proof_routes"] = {str(no): text for no, text in sorted(routes.items())}
        out["route"] = proof_route_of(row, 1)
    except Exception as exc:  # noqa: BLE001 —— 派生格读不成不许把整行读数带走
        out["proof_routes"] = {}
        out["route"] = ""
        out["proof_routes_problem"] = f"{type(exc).__name__}: {exc}"
    return out


@tool(
    "table.list",
    "列出某张表的行（等值过滤 + 分页）与过滤后的总数。读 `statements` 行另带 route / proof_routes；算不出来时由 proof_routes_problem 说明。",
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
            "rows": [_with_proof_routes(table, row) for row in page],
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
    "按主键取一行；不存在时 ok=True 且 data=None（meta.found=False）。读 `statements` 行另带 route / proof_routes；算不出来时由 proof_routes_problem 说明。",
    _obj({"table": _TABLE_PROP, "id": {
        "type": "string",
        "description": (f"主键值（{S.ID_DIGITS} 位十进制字符串如 `000000`，"
                        "或 `r-000001`；旧数据里的 4 位号仍可读）")}},
         required=("table", "id")),
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
            return ok(_with_proof_routes(table, row), table=table, id=id, id_field=idf,
                      found=True)
    return ok(None, table=table, id=id, id_field=idf, found=False)


@tool(
    "table.create",
    "新建一行：主键由台账分配（这一格整格别写），校验通过才落盘。",
    _obj(
        {
            "table": _TABLE_PROP,
            "row": {"type": "object", "description":
                    "行内容；主键整格别写（由台账分配：知识实体是六位十进制如 000000，"
                    "过程记录是 r-/p-/t- 前缀号）"},
        },
        required=("table", "row"),
    ),
    side_effect="write_local",
    roles=TOOL_ROLES,
    # 豁免清单成员：data 是新主键字符串（标量），声明不出键集合。
    returns=("data=新主键字符串（标量）；meta.row 是实际落盘的整行；meta.normalized "
             "列出这一笔被排序去重过的集合字段（空列表 = 一个字节都没动）。"
             "被兜底接管那一档 data 是对象：{backstop, routed_to, routed_from, state, "
             "what_happened, row, id, requested_id, dropped_keys, refused_by_backstop}"),
    tags=("table", "crud", "write"),
)
def table_create(ctx: TableContext, *, table: str, row: Mapping[str, Any]) -> ToolResult:
    """建行。

    校验刻意放在进入事务之前先做一遍（用占位 ID），理由见 `_probe_id`：
    先发号再发现字段非法，会白白烧掉一个 4 位编号并留下 `id_gap`。

    本批（`draft/156`）在这一格上加了两条写侧行为，各自的判据只有一处：
      1. 手填主键 ⇒ 受控拒绝（`_hand_typed_id_refusal`，D4）；
      2. 集合字段 ⇒ 排序去重后照收（`schema.normalize_set_fields`，D5），
         改动过的字段名回在 `meta.normalized` 上。
    """
    try:
        spec = _spec_of(table)
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")
    idf: str = spec["id_field"]
    # ---- 手填主键的受控拒绝（D4，2026-10-28）：按前缀直觉编一个号 ⇒ 先说清"这一格不该你填"。
    # 位置刻意在兜底路由之前，理由见 `_hand_typed_id_refusal`：先路由会把模型的输入静默改掉。
    hand_filled = _hand_typed_id_refusal(table, dict(row or {}), idf)
    if hand_filled is not None:
        return hand_filled
    # ---- `tasks` 台账的写侧判据（D12）：不许伪造"谁开的项 / 已收口 / 已读过"。
    # 位置在兜底路由之前：这张表没有兜底方（`store.direct_write_refusal` 不拒它），
    # 路由层对它什么也不做，所以这条判据必须自己说话。
    tasks_refused = _tasks_write_refusal(table=table, row=dict(row or {}), op="create")
    if tasks_refused is not None:
        return tasks_refused
    # ---- 直写兜底（2026-10-24 业主裁定）：这两张表不由通用写口直写 —— 请求转交正路执行。
    # 判据只有一处（见 `_direct_write_disposal`）：能兜底的由兜底方办、兜不了的才拒。
    refused = _direct_write_disposal(ctx, table=table, op="create",
                                     payload=dict(row or {}), idf=idf)
    if refused is not None:
        return refused

    data: dict[str, Any] = dict(row or {})
    # ---- 集合字段写入前归一（D5，2026-10-28）：把 [`000004`,`000002`] 排成落盘形态而不是拒收。
    # 归一化必须发生在 `_fill_derived` 之前 ⇒ `concept_group_key` / `dedup_key` 看的是
    # 真正落盘的次序；也必须在预演校验之前 ⇒ 预演不会被"未升序"这一档挡下来。
    # 判据只有一处（`schema.normalize_set_fields`），"哪些字段是集合"由 `ARRAY_FIELD_KINDS` 声明。
    normalized = S.normalize_set_fields(table, data)
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
    return ok(new_id, table=table, id=new_id, id_field=idf, row=merged,
              normalized=normalized)


@tool(
    "table.update",
    "部分更新一行：只覆盖 patch 里的字段，其余原样保留；不允许改主键。",
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
    returns=("data=主键（标量）；meta.row 是合并后实际落盘的整行；meta.normalized 列出这一笔"
             "被排序去重过的集合字段（空列表 = 一个字节都没动）。"
             "被兜底接管那一档 data 是对象（同上：backstop / state / what_happened / row / "
             "refused_by_backstop …）。"),
    tags=("table", "crud", "write"),
)
def table_update(ctx: TableContext, *, table: str, id: str, patch: Mapping[str, Any]) -> ToolResult:
    """部分更新。

    实现上是"读整行 → 覆盖 patch → 整行校验 → 整行写回"，而不是"只写 patch 的字段"：
    后者要先做字段级校验，等于把 `validate()` 的逻辑拆开重写一遍，两套规则迟早会漂移。
    整行验证则天然保证"改完之后这一行仍然是合法的"（比如 `concept_ids` 改完必须仍是
    升序去重的形态 —— 那一档现在由 `schema.normalize_set_fields` 在写前排好序，
    读数落在 `meta.normalized` 上，见 `_hand_typed_id_refusal` 同批的 D5）。
    """
    try:
        idf = _spec_of(table)["id_field"]
    except ToolError as e:
        return fail(str(e), table=table, kind="unknown_table")
    # ---- 直写兜底：同 `table.create`（见 `_direct_write_disposal`）。
    # 这一格也是"V 签完之后把档位写强"那条路被接管的地方：同一份内容再交一次，
    # 秘书会按 `verifications` 里那一签决定升不升档（升档就地改那一行、不新建）。
    if not patch:
        return fail("patch 不能为空（空 patch 只会更新 updated_at，通常是调用方写错了）", table=table, id=id, kind="param_error")
    # ---- `tasks` 台账的写侧判据（D12）：与 `table.create` 同一处判据、同一组理由码。
    # 这一格堵的是同一形状的第二个口子：update 可以把一行直接改成 `item_state="done"`，
    # 而那条路的语义是"绕过状态机伪造收口"，与 create 写的 done 是同一件事。
    tasks_refused = _tasks_write_refusal(table=table, row=dict(patch or {}), op="update")
    if tasks_refused is not None:
        return tasks_refused
    refused = _direct_write_disposal(ctx, table=table, op="update",
                                     payload=dict(patch or {}), id=id, idf=idf)
    if refused is not None:
        return refused

    normalized: list[str] = []
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
            # ---- 集合字段写入前归一（D5）：与 `table.create` 同一处判据、同一份读数。
            # 位置同样在 `_fill_derived` 之前（派生字段要看落盘的那一份次序）。
            normalized = S.normalize_set_fields(table, merged_raw)
            _touch_timestamps(table, merged_raw, create=False, patch=patch)
            _fill_derived(table, merged_raw, create=False, patch=patch)
            try:
                _obj_row, merged = _build_row(table, merged_raw)
            except ToolError as e:
                return fail(str(e), table=table, id=id, kind="validation")
            tx.upsert(table, merged, note="tool:table.update")
    except (IdExhausted, StoreError) as e:
        return fail(f"{table} 更新失败：{e}", table=table, id=id, kind="store_error")
    return ok(id, table=table, id=id, id_field=idf, row=merged, normalized=normalized)


@tool(
    "table.delete",
    "删除一行；被引用的 concepts/literature 会被拒绝并列出引用者。",
    _obj({"table": _TABLE_PROP, "id": {"type": "string", "description": "要删的行主键"}}, required=("table", "id")),
    side_effect="write_local",
    roles=TOOL_ROLES,
    # 豁免清单成员：data 是布尔标量（是否真的删掉了），声明不出键集合。
    # 引用者清单在 meta.references 里（被拒时是原因，放行时是将会悬空的清单）。
    returns=("data=是否真的删掉了（布尔标量）；meta.references 列出引用者（被拒时是原因，"
             "放行时是将会悬空的清单）。被兜底接管那一档 data 是对象（同上）。"),
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
    # ---- 删除也走一次兜底：`lit_candidates` 的行「删掉」按意图分派成「撤掉」（见
    # `_direct_write_disposal`）—— 物理删会把"第 3 号被撤了哪一篇、为什么"永久抹掉，
    # 而序号不复用只有在那一行还在盘上时才成立。别的表的删除不制造证据 ⇒ 判据放行。
    no_delete = _direct_write_disposal(ctx, table=table, op="delete",
                                       payload={}, id=id, idf=idf)
    if no_delete is not None:
        return no_delete
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
            # `R-57`（`draft/28` §173 登记、§176 修）：必须走 `tx.delete`，不许就地改
            # `tx.rows(table)`。就地改的形态是"快照变了、事件流里没有痕迹" ⇒ `rebuild()`
            # 之后这一行复活，而返回的每个计数都"正常"（没有任何读数会告诉读的人
            # "恢复出来的数据比删之前多"）。
            # `tx.delete` 会追加一条 `op="delete"` 事件（含被删的整行，供审计）、
            # 在重建时被重放、并且自己把这张表标脏 —— 所以这里不再需要
            # §173 那会儿用来绕过 `mark_dirty` 缺失的 `_mark_dirty` helper
            # （那个 helper 与它的 `noqa: SLF001` 已随本次修法一起删除）。
            removed = tx.delete(table, id)
            if removed is None:
                # 走不到：上面 `tx.find(table, **{idf: id})` 已经找到过它，而 `tx.delete`
                # 用的是同一个比较（`r.get(idf) == key`）与同一份内存行。
                # 之所以留着这一格并让它响亮地失败（而不是返回 `ok(False, deleted=False)`）：
                # ① 三态纪律 —— "没删到"与"删的时候发现库里对不上"是两件事，后者不该折成
                #    "工具跑完了、什么都没删"；
                # ② `tests/test_tools_branch_key_sets.py` 把每个模块里看不清的 `ok(...)`
                #    调用点数钉在表里（`data` 不是字面量 dict 的那种就算看不清），
                #    而这里返回的是 bool 标量、静态读不出键 ⇒ 多一处就得多改一次那张表；
                #    走 `fail` 那条路（`except StoreError` 已经在下面）不占那一栏。
                raise StoreError(
                    f"{table} {id} 在本次事务里刚刚还在，删除却没命中 —— "
                    "内存行与主键比较出现了不一致，请先 `verify` 再继续（本次事务已放弃）"
                )
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
    # 张数必须现算（2026-10-07 修，R6 的 `draft/63 §3-2`）：这里原写死"返回 6 张表"，
    # 而 `ALL_TABLES` 的真身是 17 —— 模型看到的摘要因此是假的，且全仓没有任何判据
    # 看着那句话（改前实测：`grep "返回 6 张表"` 在 tests/scripts/tools 里零命中）。
    # 现算的判据在 `tests/test_tool_summary_readings.py`（含"写死 6 必红"的负控）。
    f"返回 {len(ALL_TABLES)} 张表的字段名/类型/是否必填/默认值，以及全部受控词表（从 dataclass 与 schema 反射）。",
    _obj({"table": {"type": "string", "maxLength": 60}}),
    side_effect="read",
    roles=TOOL_ROLES,
    # 键名从实现读出（`table_schema` 的 ok(...)）：tables 里每个表名 → {fields,
    # primary_key, vocabularies}，键名是表名（所以不能写进键集合）。
    returns="{'tables','vocabularies'}；tables 的键是表名，值是 {'fields','primary_key','vocabularies'}。",
    tags=("table", "meta"),
)
def table_schema(ctx: TableContext, table: str | None = None) -> ToolResult:  # noqa: ARG001
    """表结构自描述。

    为什么必须反射而不是手写：手写的 schema 说明是文档，文档会过期；
    过期的字段说明会直接导致智能体写出非法参数（然后被 validate 拒绝，白烧一轮）。
    同理，受控词表的取值一律 `getattr(S, name)` 现取，绝不在本模块复制一份。
    """
    vocabs = _vocabularies()
    tables: dict[str, Any] = {}
    # 2026-10-18（缺陷 ⑤）：`table="statements"` 只回一张表。真机（T4/T5）里模型要的是
    # 「一张表」的字段，而无参调用返回全部 17 张（47KB）⇒ 被上下文预算截断，于是它们改用
    # 「故意写错换字段名」那种笨办法（33 次失败调用里 15 次是 table.create）。
    _only = str(table or "").strip()
    for tname, spec in S.TABLES.items():
        if _only and tname != _only:
            continue
        cls = spec["row"]
        hints = _type_hints(cls)
        fields: list[dict] = []
        table_vocabs: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            tp = hints.get(f.name, f.type)
            required = f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
            if f.default is not dataclasses.MISSING:
                default = _jsonable_default(f.default)
            elif f.default_factory is not dataclasses.MISSING:
                # 只在反射期调用，用于把 [] 之类如实展示出来
                default = _jsonable_default(f.default_factory())
            else:
                default = None
            item: dict[str, Any] = {
                "name": f.name,
                "type": _type_name(tp),
                "required": required,
                "default": default,
                # 「这三格每个元素都要在」，哪怕它不适用（2026-10-15 修）。
                #
                # 改前它们只在适用时才 `item[...] = …`，于是同一个 `fields[]` 里
                # 「一部分元素有、另一部分没有」 —— 而本工具的用途恰恰是"让智能体
                # 读受控词表"：调用方按自己在别的字段上看到的形状去读 `field["enum"]`，
                # 在不带这三格的那些字段上会拿到 「KeyError」，而不是"这个字段没有词表"。
                # 实测（`test_tools_returns_declaration.py` 的逐元素判据）：
                # 全 79 个工具里只有这一件有这个形态，而它有 「132 处」。
                #
                # 为什么给"如实空值"而不是干脆不声明：三态纪律 ——
                # 「空集是有效读数」（"这个字段确实没有候选值"），
                # `None` 是"没有词表这件事本身"；两者都不等于"我没读到"。
                "literal_values": [],
                "vocabulary": None,
                "enum": [],
            }
            if typing.get_origin(tp) is typing.Literal:
                item["literal_values"] = list(typing.get_args(tp))
            vocab_name = _VOCAB_BY_FIELD.get((tname, f.name))
            if vocab_name:
                item["vocabulary"] = vocab_name
                item["enum"] = list(getattr(S, vocab_name))
                table_vocabs[f.name] = {"vocabulary": vocab_name, "values": item["enum"]}
            fields.append(item)
        for v_table, v_path, v_name in _NESTED_VOCAB:
            if v_table == tname:
                table_vocabs[v_path] = {"vocabulary": v_name, "values": list(getattr(S, v_name))}
        tables[tname] = {
            "file": spec["file"],
            "primary_key": spec["id_field"],
            "id_kind": spec["id_kind"],
            "uses_id_counter": spec["id_kind"] in S.ID_COUNTERS,
            "fields": fields,
            "required": [f["name"] for f in fields if f["required"]],
            "vocabularies": table_vocabs,
        }
    if _only and not tables:
        # 未知表 ⇒ 「可读拒信」（带在册表名），别让调用方读成"这张表没有字段"。
        return fail(
            f"没有名为 {_only!r} 的表；在册的是 {sorted(S.TABLES)}",
            kind="unknown_table", table=_only)
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

        # ---- (1) 逐张 schema / count（张数现算：别再写死"六张表"）
        print(f"\n[1] {len(ALL_TABLES)} 张表 schema / count")
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
        check("8 个受控词表全部反射出来",
              set(expected_vocabs) <= set(reflected),
              f"少了={sorted(set(expected_vocabs) - set(reflected))} 共反射 {len(reflected)} 个")
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
        # `r-NNNN` 是 `interactions.next_prefixed_id` 的 max+1 语义（不是"最小可用"）：
        # 空表给 `r-0001`（业主口径：删中间行不复用号，否则溯源会静默指向另一条请求）。
        # 这一格原先写死断言 `r-0000` —— 那是"最小可用号"时代的残留，
        # 与 `tests/test_tools_table_fs.py` 里被改掉的那一条同一形态。
        # 判据改成"号由那一处语义给出"并且后面一律用拿到的这个号，
        # 而不是再写死一次（写死第二处就是这次漂移的成因）。
        req_id = r.data
        check("search_requests 自动分配 r-NNNN（max+1 语义）",
              r.ok and req_id == f"r-{S.format_id(1)}", f"id={r.data}")
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
        lit_id = r.data
        check("literature 分配最小号", r.ok and lit_id == S.format_id(0),
              f"id={r.data} err={r.error}")
        # ---- 概念行（`statements` 里 `kind="concept"`）「走正路」：B 交内容、秘书落盘。
        #
        # 2026-10-19 晚：这一节原先用 `table.create(table="statements")` 铺样品，而那条路
        # 现在被 `store.direct_write_refusal` 受控拒绝（真机形态：`projects/mp2/sessions/
        # mp2-7.jsonl` 第 97 行 —— 手写 `bits={}` + `evidence_kind="heuristic"`）。
        # 自检的职责是"真走一遍生产路径"，所以这里改成「生产路径本身」：秘书落盘；
        # 而"直写被拒"这件事在 [4] 里单独判一次（否则这一节会变成一条恒真断言的集合）。
        #
        # 2026-10-24（本批缺陷 B）：夹具显式写了 origin="own_result"，就必须同时
        # 声明 self_authored=True —— `conceptrows.concept_origin_problem` 的 docstring
        # 第 3 条写着"它不是默认值"，秘书写入侧读的是同一份判据。此前的夹具只写了
        # origin，于是三条概念行都被 concept_origin_refused 拒掉，后面那条链
        # （relations / statements.count / 删除保护 / search / list）跟着一起红 14 项。
        # 错在夹具一侧，不在判据：判据的负控见
        # `tests/test_tools_table_fs.py::test_a_concept_declaring_own_result_without_self_authored_is_refused`。
        # 自检走的是生产路径，所以秘书也要按生产路径装（`for_role_wired`：先把缝拿来）。
        # 这一节铺的是概念行（`kind="concept"`），不参与命题同一性判定；但它与直写路由
        # 那条路必须是同一支构造点 —— 否则自检会在一条"没接线"的形态上永远亮绿
        # （2026-10-26 真机 sylow5：实现与判据都在，只有装配处漏了一根线）。
        from ..secretary import for_role_wired

        sec = for_role_wired("B", root=st.root, store=st)
        concept_ids: list[str] = []
        for name in ("群", "域", "环"):
            got = sec.record_statement(
                {"kind": "concept", "label": name, "origin": "own_result",
                 "self_authored": True,
                 "statement_full": f"{name}的陈述"}, role="B")
            check(f"概念行 {name} 经秘书落盘", bool(got.get("created")),
                  f"stmt_id={got.get('stmt_id')} refused={got.get('refused')}")
            concept_ids.append(str(got.get("stmt_id") or ""))
        r = reg.call(
            "table.create",
            table="relations",
            row={
                "concept_ids": [concept_ids[0], concept_ids[1]],
                "description": "群与域都由交换性刻画",
                "lit_id": lit_id,
                "page_range": {"start": 12, "end": 13, "label": "pp.12-13"},
                "quote": "A field is an abelian group",
            },
        )
        check("relations 分配最小号且派生字段已补",
              r.ok and r.data == S.format_id(0), f"err={r.error}")
        if r.ok:
            row0 = r.meta["row"]
            check("concept_group_key 派生正确",
                  row0.get("concept_group_key") == f"{concept_ids[0]}|{concept_ids[1]}",
                  repr(row0.get("concept_group_key")))
            check("dedup_key 派生正确", bool(row0.get("dedup_key")), repr(row0.get("dedup_key")))
        r = reg.call("table.count", table="statements")
        check("statements.count = 3", r.ok and r.data == 3, f"count={r.data}")

        # ---- (2) create → get → update → get，确认未给字段被保留
        # 样品从 `statements` 换成 `research_questions`：那两张表已不由通用写口直写
        # （见 [4]），而本节判的是「部分更新」这条机制，与样品挂在哪张表无关。
        print("\n[3] create → get → update → get（未给字段必须保留）")
        r = reg.call(
            "table.create",
            table="research_questions",
            row={"question": "环为什么可交换？", "origin": "fixture", "priority": "high",
                 "notes": "原始笔记", "gap_reason": "没查到", "_probe": "诊断字段"},
        )
        new_id = r.data
        check("建 research_questions 行", r.ok and new_id == S.format_id(0),
              f"id={new_id} err={r.error}")
        g1 = reg.call("table.get", table="research_questions", id=new_id)
        check("get 取回", g1.ok and g1.data["notes"] == "原始笔记",
              f"notes={g1.data.get('notes') if g1.ok else None}")
        u = reg.call("table.update", table="research_questions", id=new_id,
                     patch={"notes": "改过的笔记"})
        check("update 改一格", u.ok, f"err={u.error}")
        g2 = reg.call("table.get", table="research_questions", id=new_id)
        row2 = g2.data or {}
        check("改名生效", row2.get("notes") == "改过的笔记", repr(row2.get("notes")))
        check("未给的 question 被保留", row2.get("question") == "环为什么可交换？",
              repr(row2.get("question")))
        check("未给的 gap_reason 被保留", row2.get("gap_reason") == "没查到",
              repr(row2.get("gap_reason")))
        check("诊断字段 _probe 未被抹掉", row2.get("_probe") == "诊断字段",
              repr(row2.get("_probe")))
        check("created_at 已自动补", bool(row2.get("created_at")), repr(row2.get("created_at")))
        check("status 落成受控词表的默认档", row2.get("status") == "open", repr(row2.get("status")))

        # ---- 负面：改主键 / 校验失败 / 未知字段 / 野路受控拒绝
        print("\n[4] 负面用例（写操作）")
        bad = reg.call("table.update", table="research_questions", id=new_id,
                       patch={"question_id": S.format_id(9)})
        check("改主键被拒", not bad.ok and "不允许修改主键" in (bad.error or ""), f"error={bad.error}")
        bad = reg.call("table.create", table="literature",
                       row={"title": "", "type": "J", "summary": "s", "path": None})
        check("空 title 校验失败返回 fail 而不是抛异常",
              not bad.ok and "校验失败" in (bad.error or ""), f"error={bad.error}")
        bad = reg.call("table.create", table="research_questions",
                       row={"question": "q", "origin": "f", "nmae": "拼错"})
        check("未知字段被拒", not bad.ok and "没有字段" in (bad.error or ""), f"error={bad.error}")
        # ---- 直写兜底（2026-10-24 业主裁定）：`statements` / `dependencies` 的直写请求
        # 由系统转交正路执行 —— 通用写口不再自己写，也不再"拒 + 指路"。
        for tname in ("statements", "dependencies"):
            bad = reg.call("table.create", table=tname,
                           row={"origin": "own_result", "kind": "theorem",
                                "statement_full": "手写的", "quote_reason": "尚未逐字校验"})
            check(f"直写 {tname} 被转交正路（routed_to_backstop.*）",
                  not bad.ok and str(bad.meta.get("kind") or "").startswith(
                      "routed_to_backstop"),
                  f"ok={bad.ok} kind={bad.meta.get('kind')}")
            check(f"{tname} 的读数带着兜底方的原话（refused_by_backstop）",
                  bool(bad.meta.get("refused_by_backstop")), f"meta={bad.meta}")
        bad = reg.call("table.update", table="statements", id=concept_ids[0],
                       patch={"evidence_kind": "proof_review"})
        check("直改 statements 也被转交（升档由秘书按 V 那一签判）",
              not bad.ok and (str(bad.meta.get("kind") or "").startswith("routed_to_backstop")
                              or bad.meta.get("kind") == "not_found"),
              f"ok={bad.ok} kind={bad.meta.get('kind')}")
        check("野路被拒之后一行都没多", reg.call("table.count", table="statements").data == 3,
              "(statements 仍为 3 行)")
        # ---- D5（2026-10-28，`draft/156`）：集合字段写侧排序去重，不再拒收。
        # 这一条原先断言的是"未升序 → fail"—— 那是改前的行为，而真机上模型因此同一个坑
        # 连踩 3 次（把次序写错 → 读拒信 → 再猜）。现在的判据是"照收 + 读数点名归一化过"，
        # 正反两档都在这里：非法元素照旧拒（归一化不是放宽）。
        ok_set = reg.call(
            "table.create",
            table="relations",
            row={
                "concept_ids": [concept_ids[1], concept_ids[0]],
                "description": "乱序",
                "lit_id": lit_id,
                "page_range": {"start": 1, "end": 1, "label": "p.1"},
            },
        )
        check("concept_ids 未升序 → 排序去重后照收（不再拒收）",
              ok_set.ok and ok_set.meta.get("normalized") == ["concept_ids"],
              f"ok={ok_set.ok} normalized={ok_set.meta.get('normalized')} err={ok_set.error}")
        check("落盘的是升序去重形态",
              list((ok_set.meta.get("row") or {}).get("concept_ids") or [])
              == sorted(set(concept_ids[:2])),
              repr((ok_set.meta.get("row") or {}).get("concept_ids")))
        bad_set = reg.call(
            "table.create",
            table="relations",
            row={
                "concept_ids": ["abc", concept_ids[0]],
                "description": "坏号",
                "lit_id": lit_id,
                "page_range": {"start": 1, "end": 1, "label": "p.1"},
            },
        )
        check("非法的概念号仍被拒（归一化不放宽元素校验）",
              not bad_set.ok and "concept_ids[]" in (bad_set.error or ""),
              f"error={bad_set.error}")
        # 这一行只为核读数而造：删掉它，后面几节的行数假设与改前逐字一致。
        if ok_set.ok:
            reg.call("table.delete", table="relations", id=str(ok_set.data))
        bad = reg.call("table.list", table="nope")
        check("未知表名 → fail", not bad.ok, f"error={bad.error}")

        # ---- (3) 负面：删除被关系引用的一条概念行（概念行也在这一张表里）
        print("\n[5] 负面：删除被关系引用的 statement")
        d = reg.call("table.delete", table="statements", id=concept_ids[0])
        check("删除被引用的 statement 被拒 (ok=False)", not d.ok, f"ok={d.ok}")
        check("错误信息点名了引用它的关系",
              concept_ids[0] in (d.error or "") and "relations" in (d.error or ""), f"error={d.error}")
        check("meta.references 列出引用者",
              (d.meta.get("references") or [{}])[0].get("row_id") is not None,
              f"references={d.meta.get('references')}")
        check("被拒后行仍在",
              reg.call("table.get", table="statements", id=concept_ids[0]).meta.get("found") is True)

        # ---- 负面：删除被请求/关系引用的 literature
        r = reg.call(
            "table.create",
            table="literature",
            row={"title": "第二篇", "type": "M", "summary": "备胎", "path": None, "processed": False},
        )
        lit1 = r.data
        reg.call("table.update", table="search_requests", id=req_id,
                 patch={"result_lit_ids": [lit1], "done": True, "outcome": "ok"})
        d = reg.call("table.delete", table="literature", id=lit1)
        check("删除被 search_requests.result_lit_ids 引用的 literature 被拒", not d.ok, f"error={d.error}")

        # ---- 放行路径：先删关系，再删概念行/文献
        print("\n[6] 放行路径：relations 可直接删，随后概念行/文献可删")
        d = reg.call("table.delete", table="relations", id=S.format_id(0))
        check("删 relations 放行", d.ok and d.data is True, f"err={d.error}")
        d = reg.call("table.delete", table="statements", id=concept_ids[0])
        check("关系删掉后概念行可删", d.ok and d.data is True, f"err={d.error}")
        d = reg.call("table.delete", table="statements", id=concept_ids[0])
        check("重复删除返回 data=False（found=False）",
              d.ok and d.data is False and d.meta.get("found") is False, f"data={d.data}")

        # ---- search / filter / list
        print("\n[7] search / filter / list / get 未命中")
        s = reg.call("table.search", table="statements", query="环")
        check("search 命中 1 行", s.ok and s.meta.get("total") == 1,
              f"total={s.meta.get('total')} fields={s.data.get('fields') if s.ok else None}")
        s = reg.call("table.search", table="literature", query="ABELIAN")
        check("search 大小写不敏感", s.ok and s.meta.get("total") == 1, f"total={s.meta.get('total')}")
        s = reg.call("table.search", table="statements", query="x", fields=["nope"])
        check("search 未知字段 → fail", not s.ok, f"error={s.error}")
        li = reg.call("table.list", table="statements", limit=1, offset=0)
        check("list 分页 total=2 returned=1",
              li.ok and li.data["total"] == 2 and li.data["returned"] == 1,
              f"{li.data['total']}/{li.data['returned']}")
        cn = reg.call("table.count", table="search_requests", filter={"done": True})
        check("count + filter", cn.ok and cn.data == 1, f"count={cn.data}")
        g = reg.call("table.get", table="statements", id=S.format_id(9))
        check("get 未命中 → ok=True / found=False",
              g.ok and g.data is None and g.meta.get("found") is False)
        v = reg.call("table.update", table="research_questions", id=new_id, patch={})
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
