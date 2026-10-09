# -*- coding: utf-8 -*-
"""并表过渡期：概念行的唯一读写口（S1r 的"两处同号合并"那一层）。

背景（`draft/97` §10.3 / §15.2）：`concepts` 要并进 `statements`（`kind="concept"`），
而这是一次动磁盘格式的迁移（`SCHEMA_VERSION 1→2`、`TABLES` 删表），属于
`AGENTS.md` 里"错误不可逆"的那一类。所以中间必须有一层过渡，让读侧可以一个一个搬：

- 写：新标准（`statements`）先写，老表（`concepts`）照旧镜像一份 —— 于是老读侧
  立刻看得到新写进来的概念，而新读侧（C 的依赖链、verify 的命题台账）也看得到；
- 读：合成一个视图（同一个号两边都有 ⇒ 新标准优先），于是读侧只用这一个口；
- 最后：迁移那一笔删掉老表、这一层的镜像与折叠随之退役（那时 `legacy_present`
  报 `False`，视图只剩 `statements`）。

## 契约（三条，改这一层的人必须一起守）

1. 一个身份一个号：过渡期写进去的概念行，`statements.stmt_id` 与老的
   `concepts.concept_id` 是同一个号。没有这一条，"两处同号合并"就无从谈起
   （读者会把同一个概念数两遍，或把两边的号当成两个概念）。
   迁移历史数据时号会重发（`migrate_concepts.plan_migration`）—— 那是另一条路：
   那一次之后老表不再存在，也就不存在"同号"这件事。
2. 新标准优先：同一个号两边都有 ⇒ 返回 `statements` 那一份（`via="statements"`）；
   只有老表有 ⇒ 就地把老字段折成新形状（`via="legacy"`，逐行可读，不是"大概等价"）。
3. 三态：老表读不成 / 新表读不成 ⇒ `checked=False` + `reason`，不许折成
   "只有一边"。`counts` 里 `statements` / `legacy` / `merged` / `legacy_only` 四个数
   分开给 —— "两边都有"与"只有一边"是不同的读数（前者说明镜像在工作，
   后者说明还有老写侧没搬完）。

## 为什么镜像不用自己发号（一个容易被忽略的细节）

镜像行的号沿用命题那个号（契约 1），所以老表的 `concept` 计数器不会跟着前进。
这不是漏洞：`Tx.alloc_id` 在发号时会跳过"已声明事务表里已被占用的号"
（`store.Tx.alloc_id` 的 docstring 逐字写着这条自愈），而 B 的写侧声明 `concepts`
⇒ 它下一次发号会自然跳过镜像占掉的那些号。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from . import schema as S
from . import textutil as T
from .migrate_concepts import PENDING_SEARCH, PRIMITIVE_PROOF, fold_concepts

#: 过渡期还在盘上的老表名（迁移那一笔之后它从 `TABLES` 里消失）。
LEGACY_TABLE = "concepts"


def legacy_present(store: Any) -> dict[str, Any]:
    """过渡期还作不作数（`present` = 老表还在 `TABLES` 里），以及盘上还剩什么。

    四种状态都要分得开：

    | `TABLES` 里 | 盘上 | 返回 |
    |---|---|---|
    | 有 | 有/没有 | `checked=True, present=True`（过渡期：写侧要镜像；文件还没建是常态） |
    | 没有 | 有 | `checked=True, present=False, stale_file=True` —— 迁移之后留下的老文件（必须点名：它装着没搬完的数据） |
    | 没有 | 没有 | `checked=True, present=False`（迁移干净了） |
    | 任意 | 读不成 | `checked=False` + `reason`（"没查成"不是"没有"） |

    为什么 `present` 判的是"表还在不在 schema 里"而不是"文件在不在"：
    镜像这件事的依据是这一版代码还认不认老表。拿文件判会把"新工作区还没写过概念"
    读成"过渡期结束了"，于是那些工作区里新概念不被镜像、老读侧看不到它 ——
    而两种情形在文件系统上长得一样（都没有那个文件）。
    文件在不在是另一个读数（`file`），没有它，迁移之后那份残留就没人看得见。
    """
    registered = LEGACY_TABLE in S.TABLES
    if not hasattr(store, "data"):
        return {"checked": False, "present": registered, "file": False, "stale_file": False,
                "reason": "这个 store 没有 data 目录句柄 ⇒ 盘上还剩什么判不了"}
    path = store.data / (S.TABLES[LEGACY_TABLE]["file"] if registered else "concepts.json")
    try:
        exists = path.is_file()
    except OSError as exc:  # noqa: BLE001 —— 读不成 ≠ 没有
        return {"checked": False, "present": registered, "file": False, "stale_file": False,
                "reason": f"看不了 {path.name}（{type(exc).__name__}: {exc}）"}
    stale = bool(exists and not registered)
    return {"checked": True, "present": registered, "file": bool(exists), "stale_file": stale,
            "reason": ("老表已退役而文件还在（迁移留下的老文件，里面可能还有没搬完的行）"
                       if stale else "")}


def _from_legacy(row: Mapping[str, Any]) -> dict[str, Any]:
    """老表一行 ⇒ 新标准形状的一行（号不变，这是过渡期的契约 1）。

    复用迁移内核 `fold_concepts`（同一个折叠口径），只把"发号"那一步钉成"原号"：
    预演与迁移那一条路会重发号（避免与既有命题撞号），而过渡期的镜像本来就是
    "同一个身份两个落点" ⇒ 号必须相同。
    """
    old_id = str(row.get("concept_id") or "")
    folded = fold_concepts([dict(row)], alloc=lambda: old_id)
    out = dict(folded["rows"][0])
    out["via"] = "legacy"
    return out


def concept_statement(*, stmt_id: str, label: str, definition: str = "", aliases: Iterable[str] = (),
                      source_lit_id: str = "", proof_text: str = "", doc_id: str = "",
                      actor: str = "agent-B") -> Any:
    """一条概念 ⇒ 一行 `Statement`（并表之后概念的落点，新标准的唯一构造口）。

    两档（`D12` 甲）：定义在 ⇒ `active`；定义还没抽到 ⇒ `pending_definition`
    + `quote_reason` 里的待补标记（`concept:pending_search`：等 A 检索回来，
    或基本概念由 B 自撰）。不许落成 `active` + 空定义，也不许干脆不落。
    良定义性证明那一格照旧：`proof_text`（原始概念写 `concept:primitive`）。
    """
    definition = str(definition or "")
    pending = not definition.strip()
    if pending:
        reason = (f"概念 {label!r} 的定义还没抽到（D12 甲）：{PENDING_SEARCH} —— "
                  "由直接父/A 检索回来，或基本概念由 B 自撰；定义到了就改回 active 并清掉"
                  "这一标记。良定义性证明那一格照旧记 proof_text（原始概念写 "
                  "concept:primitive）")
    else:
        reason = ("概念的良定义性证明记在 proof_text（原始概念写 concept:primitive）；定义来自 "
                  + (str(source_lit_id) if source_lit_id else "B 的消化（没有外部来源）"))
    return S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="concept", label=str(label or ""),
        statement_text=definition, statement_full=definition,
        proof_text=str(proof_text or PRIMITIVE_PROOF), source_lit_id=str(source_lit_id or "") or None,
        quote_verified=None, quote_reason=reason, evidence_kind="heuristic",
        aliases=[str(a) for a in (aliases or []) if str(a).strip()],
        status=("pending_definition" if pending else "active"),
        doc_id=str(doc_id or "") or None, created_at=S.now_iso(), created_by=actor)


def view(store: Any) -> dict[str, Any]:
    """概念行的合成视图（新标准形状 + 逐行 `via` + 四个计数）。

    返回 `{"checked", "rows", "counts", "legacy", "reason"}`：
    `counts` = `{"statements", "legacy", "merged", "legacy_only", "definition_only_in_legacy"}`。
    最后那一个是"新标准那一行还空着定义、而老行有"的条数 —— 它不自动合并
    （新标准优先），但必须可见：那是"两边不同步"的读数，不是可以顺手抹平的差异。
    """
    out: dict[str, Any] = {"checked": False, "rows": [], "legacy": {}, "reason": "",
                           "counts": {"statements": 0, "legacy": 0, "merged": 0,
                                      "legacy_only": 0, "definition_only_in_legacy": 0}}
    try:
        stmt_rows = [dict(r) for r in store.rows("statements") if str(r.get("kind") or "") == "concept"]
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报（不是"没有概念"）
        out["reason"] = f"statements 读不成（{type(exc).__name__}: {exc}）"
        return out
    by_id: dict[str, dict[str, Any]] = {}
    for row in stmt_rows:
        row = dict(row)
        row["via"] = "statements"
        by_id[str(row.get("stmt_id") or "")] = row
    out["counts"]["statements"] = len(by_id)

    legacy = legacy_present(store)
    out["legacy"] = legacy
    if not legacy.get("checked"):
        out["reason"] = str(legacy.get("reason") or "老表在不在判不了")
        return out
    if legacy.get("stale_file"):
        out["reason"] = str(legacy.get("reason") or "")
    if legacy.get("present"):
        try:
            legacy_rows = [dict(r) for r in store.rows(LEGACY_TABLE)]
        except Exception as exc:  # noqa: BLE001 —— 老表读不成 ⇒ 三态里的"没查成"
            out["reason"] = f"老表读不成（{type(exc).__name__}: {exc}）⇒ 视图不完整"
            return out
        out["counts"]["legacy"] = len(legacy_rows)
        for lrow in legacy_rows:
            folded = _from_legacy(lrow)
            key = str(folded.get("stmt_id") or "")
            if key in by_id:
                out["counts"]["merged"] += 1
                if (not str(by_id[key].get("statement_full") or "").strip()
                        and str(folded.get("statement_full") or "").strip()):
                    out["counts"]["definition_only_in_legacy"] += 1
                continue
            by_id[key] = folded
            out["counts"]["legacy_only"] += 1
    out["checked"] = True
    out["rows"] = list(by_id.values())
    return out


def write_concept(tx: Any, *, stmt_id: str, label: str, definition: str = "",
                  aliases: Iterable[str] = (), source_lit_id: str = "", proof_text: str = "",
                  doc_id: str = "", actor: str = "agent-B", mirror: bool = False) -> dict[str, Any]:
    """在已开的事务里写一条概念行（新标准那一行 + 可选的老表镜像）。

    为什么要有"事务内"这一档：B 的写入是一笔事务（命题 + 概念 + 依赖一起落，
    `Secretary.record_statement`），而 `upsert` 自己开事务 —— 事务不能嵌套
    （文件锁不可重入）。所以把"写哪两张表、怎么写"抽成这一个函数，
    `upsert`（单独写一条概念）与秘书那一笔都调它，口径只有一处。
    """
    row = concept_statement(stmt_id=stmt_id, label=label, definition=definition,
                            aliases=aliases, source_lit_id=source_lit_id,
                            proof_text=proof_text, doc_id=doc_id, actor=actor)
    row.validate()
    data = row.to_dict()
    tx.upsert("statements", data, note="concept_upsert")
    if mirror:
        crow = S.Concept(
            concept_id=stmt_id, name=str(label or ""), definition=str(definition or ""),
            related_concepts=[], normalized_name=T.normalize(str(label or "")),
            aliases=[str(a) for a in (aliases or []) if str(a).strip()],
            definition_source_lit_id=str(source_lit_id or "") or None,
            created_at=S.now_iso(), updated_at=S.now_iso())
        crow.validate()
        tx.upsert(LEGACY_TABLE, crow.to_dict(), note="concept_upsert:mirror")
    return data


def upsert(store: Any, *, label: str, definition: str = "", stmt_id: str = "",
           aliases: Iterable[str] = (), source_lit_id: str = "", proof_text: str = "",
           doc_id: str = "", actor: str = "agent-B") -> dict[str, Any]:
    """写一条概念行：新标准先写，老表照旧镜像（同号）。

    返回 `{"checked", "stmt_id", "mirrored", "tables", "reason"}`。
    老表已退役（`legacy_present` 报 `present=False`）时只写新标准 —— 那一支不是
    "降级"，而是迁移之后的正态；但老文件还在盘上（`stale_file`）时必须在返回值里
    读得到（它装着没搬完的数据）。
    """
    name = str(label or "").strip()
    if not name:
        return {"checked": False, "stmt_id": "", "mirrored": False, "tables": [],
                "reason": "一条概念至少要有 label（名字）—— 没有名字的行谁也认不出它"}
    legacy = legacy_present(store)
    if not legacy.get("checked"):
        return {"checked": False, "stmt_id": "", "mirrored": False, "tables": [],
                "reason": f"老表在不在判不了 ⇒ 这一笔不写（{legacy.get('reason')}）"}
    tables = ["statements"] + ([LEGACY_TABLE] if legacy.get("present") else [])
    try:
        with store.tx(*tables, actor=actor, note="concept_upsert") as tx:
            sid = str(stmt_id or "").strip() or tx.alloc_id(S.TABLES["statements"]["id_kind"])
            write_concept(tx, stmt_id=sid, label=name, definition=definition, aliases=aliases,
                          source_lit_id=source_lit_id, proof_text=proof_text, doc_id=doc_id,
                          actor=actor, mirror=bool(legacy.get("present")))
    except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
        return {"checked": False, "stmt_id": "", "mirrored": False, "tables": [],
                "reason": f"落盘没成（{type(exc).__name__}: {exc}）⇒ 这一笔按'没写成'读"}
    return {"checked": True, "stmt_id": sid, "mirrored": bool(legacy.get("present")),
            "tables": tables, "reason": str(legacy.get("reason") or "")}
