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

#: `_to_legacy` 给"墓碑"投影出的哨兵值：非空（读侧据此跳过它），且绝不是一个合法 id
#: （`schema.is_valid_id` 为假 ⇒ 谁把它当号用都会当场看出不对，而不是去找一个不存在的概念）。
SUPERSEDED_INTO = "superseded"

#: `draft/97` §15.4 的①档标记：问直接父（最常见的场景里父就是 A —— 原文在它手里，
#: 就地就能给定义，不用惊动 M、也不用真的再上网搜）。
#:
#: 为什么它是一个行内标记而不是一列/一张表：它与 `pending_search` / `self_authored`
#: 是同一件事的三个取值（"这个定义最后由谁来补"），而"定义到底到了没有"由
#: `statement_full` 是否为空单独回答 —— 两件事折平就会把"已经问了父"读成"定义有了"。
ASK_PARENT = "concept:ask_parent"


def definition_supply(store: Any) -> dict[str, Any]:
    """概念行的定义来源逐档计数（`draft/97` §14.13 / §15.4：三档不许折平）。

    业主 2026-10-09 的两句口径合成这一格：

    > 「抽不到定义的概念就让A去网上搜，写入时定义内容留空，等A返回后写入；如果概念很基础，
    >  是数学基本概念，允许B自己写定义（我们相信LLM的智力）」
    > 「最常见的定义不明极可能是A查论文要B消化时遇到生僻定义，这时和父代理A交流即可」

    返回 `{"checked", "rows", "from_lit", "self_authored", "ask_parent",
    "pending_search", "waiting_ask_parent", "unmarked_empty", "reason"}`：

    | 桶 | 什么时候 |
    |---|---|
    | `from_lit` | 定义在，且有 `source_lit_id`（从某篇文献抽到） |
    | `ask_parent` | 定义在，理由里带着"父给的"这一档 |
    | `self_authored` | 定义在，没有外部来源（B 自撰：基本概念） |
    | `pending_search` | 定义不在，理由里写着等 A 搜（`concept:pending_search`） |
    | `waiting_ask_parent` | 定义不在，已经向父发出请求（`concept:ask_parent`） |
    | `unmarked_empty` | 定义不在、也没有任何待补标记 —— 这就是历史那 94 条的病根，它必须恒为 0 |

    两个半区（"定义到了"与"还没到"）分开报：把 `ask_parent` 折进"定义有了"会让
    "已经问了父"读成"父已经给了"。`checked=False` 时每个桶都是 0，但 `reason` 说清为什么
    （"没查成"不是"全是 0"）。
    """
    out: dict[str, Any] = {"checked": False, "rows": 0, "from_lit": 0, "self_authored": 0,
                           "ask_parent": 0, "pending_search": 0, "waiting_ask_parent": 0,
                           "unmarked_empty": 0, "reason": ""}
    try:
        rows = [dict(r) for r in store.rows("statements")
                if str(r.get("kind") or "") == "concept"]
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报
        out["reason"] = f"statements 读不成（{type(exc).__name__}: {exc}）"
        return out
    out["rows"] = len(rows)
    out["checked"] = True
    for r in rows:
        reason = str(r.get("quote_reason") or "")
        defined = bool(str(r.get("statement_full") or "").strip())
        if defined:
            if str(r.get("source_lit_id") or "").strip():
                out["from_lit"] += 1
            elif ASK_PARENT in reason:
                out["ask_parent"] += 1
            else:
                out["self_authored"] += 1
        elif ASK_PARENT in reason:
            out["waiting_ask_parent"] += 1
        elif PENDING_SEARCH in reason:
            out["pending_search"] += 1
        else:
            out["unmarked_empty"] += 1
    return out


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
    # `related_concepts` 是老表专有的一格（迁移内核刻意丢掉它：并表之后那件事由
    # `relations` 表管）。但过渡期的老字段名投影要忠实（`verify` 的
    # `related_drift` 判据与 `agentflow repair --related` 都靠它）⇒ 在这里带过来，
    # 并记明它是"过渡期的一格"，不是新标准的一部分。
    out["related_concepts"] = list(row.get("related_concepts") or [])
    out["legacy_related"] = True   # "这一格有权威值"（判据据此分档，见 `view` 的 docstring）
    # 墓碑（`merged_into`）必须带过来：它是"这一行不是活节点"的唯一机器可读标记，
    # 而读侧（`dedup.find_concept` / `decide_structural_duplicate`）判的正是这一格的真值性。
    # 丢弃它等于把墓碑重新变成活节点 —— 新知识会挂到幽灵节点上、survivor 永远接不到
    # （实测抓到，见 `_to_legacy` 的 docstring 与 `draft/97` §13.2l）。
    if str(row.get("merged_into") or ""):
        out["merged_into"] = str(row["merged_into"])
        out["status"] = "superseded"   # 与 `sync_from_legacy` 的墓碑映射同一档
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


#: 过渡投影认得的字段（老名字 ⇒ 新标准的哪一格）。`shape="legacy"` 用它把视图
#: 反向投影回老字段名，好让读侧一次只搬一件事（先换读口，再逐处改字段名）。
LEGACY_VIEW_FIELDS: dict[str, str] = {
    "concept_id": "stmt_id",
    "name": "label",
    "definition": "statement_full",
    "normalized_name": "",      # 老表里可能有、新标准里没有 ⇒ 现算（见 `_to_legacy`）
    "related_concepts": "",     # 那件事由 `relations` 表管（并表之后更明确）
    "definition_source_lit_id": "source_lit_id",
    "merged_into": "",          # 新标准里用 `status="superseded"` + `quote_reason` 表达
}


def _to_legacy(row: Mapping[str, Any]) -> dict[str, Any]:
    """新标准形状的一行 ⇒ 老字段名的一行（过渡投影；只做名字映射，不改内容）。

    两条边界必须显式：

    - `normalized_name` 现算（`textutil.normalize(label)`）——老表那一格实测
      640/2233 条与现算不符（`pipeline.py` 当年把原始名字写了进去），投影里跟现算走，
      与 `migrate_concepts` 的"读侧现算、丢弃那一格"同一口径；
    - `related_concepts` 给 `[]`（并表之后那件事由 `relations` 表管）；
    - `merged_into`：新标准里没有这一列，墓碑用 `status="superseded"` 表达 ⇒
      这一格按 `status` 投影出一个非空哨兵（`SUPERSEDED_INTO`），不是编一个目标号
      （目标号在新标准里没有机器可读的落点，只有 `quote_reason` 里那句话）；
      老表那一档（`row["merged_into"]` 真的有值）原样带过来。
      为什么必须给非空：读侧判"这一行是不是活节点"读的正是这一格的真值性 ——
      `dedup.find_concept` 是 `if row.get("merged_into"): continue`，
      `agent_b.decide_structural_duplicate` 是 `if a.get("merged_into") or b.get("merged_into")`。
      投影恒给 `None` 会把墓碑重新变成活节点：新来的同名概念命中幽灵节点、
      survivor 永远接不到新知识，而盘上一切正常（实测抓到：让被合并方在
      `statements.json` 里排在前面，`find_concept(view_rows, "abelian group")`
      返回墓碑而不是 survivor）。
    """
    out: dict[str, Any] = {}
    for legacy_name, new_name in LEGACY_VIEW_FIELDS.items():
        if new_name:
            out[legacy_name] = row.get(new_name)
    out["normalized_name"] = T.normalize(str(row.get("label") or ""))
    # `related_concepts`：老表那一档原样带过来（它是真的数据，判据要拿它比派生结果）；
    # 新标准那一档没有这一格 ⇒ 空列表，而判据据 `via` 分辨"表里写着空"与"这一版没这一格"
    # （`verify._check_4` 那一档）。两件事折平会造出假红。
    out["related_concepts"] = list(row.get("related_concepts") or [])
    out["legacy_related"] = bool(row.get("legacy_related"))  # 见 `_from_legacy`
    superseded = str(row.get("status") or "") == "superseded"
    out["merged_into"] = (str(row["merged_into"]) if str(row.get("merged_into") or "")
                          else (SUPERSEDED_INTO if superseded else None))
    out["aliases"] = list(row.get("aliases") or [])
    out["status"] = row.get("status")
    out["via"] = row.get("via")
    return out


def view(store: Any, *, shape: str = "statement") -> dict[str, Any]:
    """概念行的合成视图（新标准形状 + 逐行 `via` + 四个计数）。

    返回 `{"checked", "rows", "counts", "legacy", "reason"}`：
    `counts` = `{"statements", "legacy", "merged", "legacy_only", "definition_only_in_legacy"}`。
    最后那一个是"新标准那一行还空着定义、而老行有"的条数 —— 它不自动合并
    （新标准优先），但必须可见：那是"两边不同步"的读数，不是可以顺手抹平的差异。

    `shape="legacy"`（2026-10-09 加）：把每一行反向投影回老字段名
    （`concept_id`/`name`/`definition`…，见 `LEGACY_VIEW_FIELDS`）。它的用途只有一个 ——
    让读侧一次只搬一件事：先换读口（`store.rows("concepts")` ⇒ `view(…)[ "rows"]`），
    再逐处把字段名改成新标准。两件事一起做的话，红的时候分不清是"读口换错了"
    还是"字段名换错了"，而这两类错的处置完全不同。
    投影是单向的（老名字 ⇒ 新标准的那一格；新标准独有的 `bits`/`doc_id` 不丢，
    它们照旧在新名字下带着），所以它不会把视图变成"第二份老表"。
    """
    out: dict[str, Any] = {"checked": False, "rows": [], "legacy": {}, "reason": "",
                           "shape": str(shape or "statement"),
                           "counts": {"statements": 0, "legacy": 0, "merged": 0,
                                      "legacy_only": 0, "definition_only_in_legacy": 0}}
    try:
        stmt_rows = [dict(r) for r in store.rows("statements") if str(r.get("kind") or "") == "concept"]
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报（不是"没有概念"）
        out["reason"] = f"statements 读不成（{type(exc).__name__}: {exc}）"
        return out

    legacy = legacy_present(store)
    out["legacy"] = legacy
    if not legacy.get("checked"):
        out["reason"] = str(legacy.get("reason") or "老表在不在判不了")
        return out
    if legacy.get("stale_file"):
        out["reason"] = str(legacy.get("reason") or "")
    legacy_rows: list[dict[str, Any]] = []
    if legacy.get("present"):
        try:
            legacy_rows = [dict(r) for r in store.rows(LEGACY_TABLE)]
        except Exception as exc:  # noqa: BLE001 —— 老表读不成 ⇒ 三态里的"没查成"
            out["reason"] = f"老表读不成（{type(exc).__name__}: {exc}）⇒ 视图不完整"
            return out
    return _merge_rows(out, stmt_rows=stmt_rows, legacy_rows=legacy_rows)


def view_tx(tx: Any, *, shape: str = "statement") -> dict[str, Any]:
    """`view()` 的事务内形态：读己之写（同一笔事务里刚写的概念立刻看得见）。

    为什么必须与 `view()` 分开：事务里的读有"读己之写"的语义，而 `view()` 走的是
    `store.rows`（无锁快照，读不到本事务尚未提交的行）。B 的 `_apply_merge` 正是
    "读概念行 → 改写 → 写回"三件事在同一笔里（`tx.rows("concepts")`）——
    换成 `store.rows` 会让它读到上一次提交的版本，于是合并/别名同步落空，
    而盘上看起来一切正常（这一笔写完了，只是基于旧值）。

    两边的口径（合并、同号去重、`via`、计数、投影）必须同一份实现 ——
    所以这里只负责"从哪读"，合并那一段调 `_merge_rows`。
    """
    out: dict[str, Any] = {"checked": False, "rows": [], "legacy": {}, "reason": "",
                           "shape": str(shape or "statement"), "in_tx": True,
                           "counts": {"statements": 0, "legacy": 0, "merged": 0,
                                      "legacy_only": 0, "definition_only_in_legacy": 0}}
    try:
        stmt_rows = [dict(r) for r in tx.rows("statements")
                     if str(r.get("kind") or "") == "concept"]
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报
        out["reason"] = f"事务里的 statements 读不成（{type(exc).__name__}: {exc}）"
        return out
    present = LEGACY_TABLE in S.TABLES
    out["legacy"] = {"checked": True, "present": present, "file": None, "stale_file": False,
                     "reason": ""}
    legacy_rows: list[dict[str, Any]] = []
    if present:
        try:
            legacy_rows = [dict(r) for r in tx.rows(LEGACY_TABLE)]
        except Exception as exc:  # noqa: BLE001 —— 老表读不成 ⇒ 三态里的"没查成"
            out["reason"] = f"事务里的老表读不成（{type(exc).__name__}: {exc}）⇒ 视图不完整"
            return out
    return _merge_rows(out, stmt_rows=stmt_rows, legacy_rows=legacy_rows)


def _merge_rows(out: dict[str, Any], *, stmt_rows: list[dict[str, Any]],
                legacy_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """合成的唯一实现（`view` 与 `view_tx` 都走这里：两边口径分家会造两种真相）。"""
    by_id: dict[str, dict[str, Any]] = {}
    for row in stmt_rows:
        row = dict(row)
        row["via"] = "statements"
        by_id[str(row.get("stmt_id") or "")] = row
    out["counts"]["statements"] = len(by_id)
    out["counts"]["legacy"] = len(legacy_rows)
    for lrow in legacy_rows:
        folded = _from_legacy(lrow)
        key = str(folded.get("stmt_id") or "")
        if key in by_id:
            out["counts"]["merged"] += 1
            # 两边都有 ⇒ 新标准优先，但老表专有的那一格要带过来：
            # `related_concepts` 只有老表有（新标准里那件事由 `relations` 表管），
            # 而 `verify` 的 drift 判据要拿它比派生结果 —— 不带上它，一行"两边都有"的
            # 概念就会逃过 `related_drift`（新标准那一侧根本没有这一格）。
            # `legacy_related=True` 是"这一格有权威值"的显式标记（判据据它分辨，
            # 而不是据 `via`：`via` 说的是"这一行以谁为准"，不是"哪些格有值"）。
            by_id[key]["related_concepts"] = list(folded.get("related_concepts") or [])
            by_id[key]["legacy_related"] = True
            if (not str(by_id[key].get("statement_full") or "").strip()
                    and str(folded.get("statement_full") or "").strip()):
                out["counts"]["definition_only_in_legacy"] += 1
            continue
        by_id[key] = folded
        out["counts"]["legacy_only"] += 1
    out["checked"] = True
    rows = list(by_id.values())
    out["rows"] = [_to_legacy(r) for r in rows] if out["shape"] == "legacy" else rows
    return out


def push_counters(tx: Any, used_id: str) -> None:
    """把 `stmt` 与 `concept` 两个计数器都抬到 `used_id` 之后（只抬，不烧号）。

    为什么必须有这一格（实测抓到的一条真缺陷）：过渡期是"同一个号写在两张表里"，
    而两张表各有自己的计数器。B 的 pipeline 从 `concept` 计数器发号 ⇒ 写入 `statements`
    的那些镜像行会让 `stmt` 计数器落在后面（`verify` 的 `counter_behind` 当场报
    "stmt 计数器为 0，但表里已用到 3；继续分配会撞号"）；反过来，秘书那条路从 `stmt`
    发号 ⇒ `concept` 计数器落在后面。两个方向都要补。

    第一版是错的，记在这里（`test_demo_end_to_end` 的"零问题"判据当场抓出来）：
    它用"多调一次 `alloc_id` 把计数器顶上去"来修 —— 那会烧掉一个没建行的号，
    同一张表于是出现 `id_gap`（"分配了 ID 但未建成行"）。正确形状是
    `Tx.raise_counter_to(kind, used_id)`：把计数器设到 `max(used)+1`，一个号都不烧。
    """
    text = str(used_id or "")
    if not text.isdigit():
        return
    for kind in ("stmt", "concept"):
        try:
            tx.raise_counter_to(kind, text)
        except Exception:  # noqa: BLE001 —— 抬不动不影响这一笔已经写好的行
            continue


def tables_for_concept_write(*extra: str) -> tuple[str, ...]:
    """写一条概念要声明哪些表：`statements` + （老表还在时）`concepts` + 调用方给的。

    为什么要有这一格（它是"落刀不牵连夹具"的关键）：`Store.tx` 对未知表会拒，
    所以凡是"声明了 `concepts`"的地方在落刀之后都会当场报错 —— 实测这样的地方有
    29 处（`temp/_s1r_flip_inventory.py` 的 `tx_declare`：src 13 + tests 45 处里的
    去重文件数）。让调用方改成 `store.tx(*CR.tables_for_concept_write("relations"), …)`
    之后，老表在不在由这一处判断，夹具与测试在落刀前后都不用改一个字。
    """
    base = ["statements", *[str(x) for x in extra if str(x)]]
    if LEGACY_TABLE in S.TABLES:
        base.append(LEGACY_TABLE)
    return tuple(dict.fromkeys(base))


def upsert_legacy_shaped(tx: Any, row: Mapping[str, Any], *,
                         actor: str = "agent-B", note: str = "legacy_shaped") -> dict[str, Any] | None:
    """一条老形状的概念行 ⇒ 新标准写一份（老表还在时顺带镜像，同一个号）。

    这一格是给夹具、探针与自检用的（生产的写侧有自己的秘书那一套）：
    它们手里拿的是 `{"concept_id": …, "name": …, "definition": …}` 这种字典，
    而落刀之后"老表"不存在了 —— 让它们走这一处，含义就变成
    "写一条概念（哪张表由过渡层决定）"，于是它们在落笔前后行为不变。

    三态：老行没有 `concept_id` ⇒ 返回 `None`（不猜号）；
    老表还在 ⇒ 先写老表那一份（夹具的既有断言照旧成立）再同步新标准；
    老表已退役 ⇒ 只写新标准。
    """
    cid = str(row.get("concept_id") or "")
    if not cid:
        return None
    if LEGACY_TABLE in S.TABLES:
        tx.upsert(LEGACY_TABLE, dict(row), note=note)
    return sync_from_legacy(tx, row, actor=actor)


def mirror_gaps(store: Any) -> dict[str, Any]:
    """过渡期的镜像完整性读数：哪一号只在一张表里有（三态 + 逐号点名）。

    为什么必须有这一格：过渡期的"读侧走视图"能成立，靠的是两面都在 ——
    B 的 pipeline 里那几处 `tx.rows("concepts")`（查重、别名合并、related 重算）
    读的仍是老表；只要"新标准写进来的概念都被镜像了"，那些读就仍然看得全。
    反过来说：任何一处写侧忘了镜像，那一批概念就会在 pipeline 的查重里消失
    （静默漏判、可能重复建概念），而盘上看起来一切正常（两边行数都"有增长"）。

    这正是"写侧那几处 `tx.rows` 可以留到落刀那一笔再改"的前提 ——
    所以它是一个判据，不是一句注释：`statements_only` 非空 ⇒ 要么补镜像，
    要么把那一处写侧搬过来。

    返回 `{"checked", "statements_only", "legacy_only", "merged", "transition_over", "reason"}`。
    `transition_over=True`（S1r 落刀之后加的那一档）说的是"老表既不在 schema 里、
    盘上也没有老文件"⇒ 没有"另一侧"，缺口不成立、三个集合都为空 —— 不这样分档的话
    新标准里每一条概念都会被读成"缺镜像"。

    注意这里读的是两张表的原始行（不是合并视图）：合并视图里"两边都有"的那一行
    只带 `via="statements"`，从它看不出老表那一份在不在 —— 而这一格问的正是
    "老表那一份在不在"。
    """
    out: dict[str, Any] = {"checked": False, "statements_only": [], "legacy_only": [],
                           "merged": [], "transition_over": False, "reason": ""}
    try:
        stmt_ids = {str(r.get("stmt_id") or "") for r in store.rows("statements")
                    if str(r.get("kind") or "") == "concept"}
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报
        out["reason"] = f"statements 读不成（{type(exc).__name__}: {exc}）"
        return out
    state = legacy_present(store)
    if not state.get("checked"):
        out["reason"] = str(state.get("reason") or "老表在不在判不了 ⇒ 镜像完整性判不了")
        return out
    if not state.get("present") and not state.get("stale_file"):
        # 并表那一笔之后：老表既不在 schema 里、盘上也没有那份文件 ⇒ 没有"另一侧"，
        # 于是"缺口"这件事根本不成立。不加这一档的话，新标准里每一条概念都会被读成
        # "缺镜像"（`statements_only` = 全体）—— 一个永不消失的假告警，而假告警的
        # 代价是"这一格从此没人看"。
        # `stale_file` 那一支不走这里：老文件还在盘上（可能装着没搬完的行）⇒
        # 那不是"过渡结束"，是"还有一份没搬"，照旧按缺口报。
        out["checked"] = True
        out["transition_over"] = True
        out["reason"] = ("并表那一笔已经落刀（老表不在 schema 里、盘上也没有老文件）"
                         "⇒ 没有'另一侧'，镜像完整性这一格不再适用")
        return out
    legacy_ids: set[str] = set()
    if state.get("present"):
        try:
            legacy_ids = {str(r.get("concept_id") or "") for r in store.rows(LEGACY_TABLE)}
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"老表读不成（{type(exc).__name__}: {exc}）⇒ 镜像完整性判不了"
            return out
    out["statements_only"] = sorted(stmt_ids - legacy_ids)
    out["legacy_only"] = sorted(legacy_ids - stmt_ids)
    out["merged"] = sorted(stmt_ids & legacy_ids)
    out["checked"] = True
    return out


def write_concept(tx: Any, *, stmt_id: str, label: str, definition: str = "",
                  aliases: Iterable[str] = (), source_lit_id: str = "", proof_text: str = "",
                  doc_id: str = "", actor: str = "agent-B", mirror: bool = False) -> dict[str, Any]:
    """在已开的事务里写一条概念行（新标准那一行 + 可选的老表镜像）。

    为什么要有"事务内"这一档：B 的写入是一笔事务（命题 + 概念 + 依赖一起落，
    `Secretary.record_statement`），而 `upsert` 自己开事务 —— 事务不能嵌套
    （文件锁不可重入）。所以把"写哪两张表、怎么写"抽成这一个函数，
    `upsert`（单独写一条概念）与秘书那一笔都调它，口径只有一处。

    `mirror=True` 只在老表还在 schema 里时才有意义（落刀之后那张表不存在，
    硬写会以"未知表"整笔失败）⇒ 这里自己判、把判断收进这一处，
    与 `upsert` / `upsert_legacy_shaped` 同一口径（调用方不必知道过渡到哪一步了）。
    事务的表声明仍然由调用方负责：要镜像时得声明 `LEGACY_TABLE`，
    统一走 `tables_for_concept_write(...)`。
    """
    row = concept_statement(stmt_id=stmt_id, label=label, definition=definition,
                            aliases=aliases, source_lit_id=source_lit_id,
                            proof_text=proof_text, doc_id=doc_id, actor=actor)
    row.validate()
    data = row.to_dict()
    tx.upsert("statements", data, note="concept_upsert")
    if mirror and LEGACY_TABLE in S.TABLES:
        crow = S.Concept(
            concept_id=stmt_id, name=str(label or ""), definition=str(definition or ""),
            related_concepts=[], normalized_name=T.normalize(str(label or "")),
            aliases=[str(a) for a in (aliases or []) if str(a).strip()],
            definition_source_lit_id=str(source_lit_id or "") or None,
            created_at=S.now_iso(), updated_at=S.now_iso())
        crow.validate()
        tx.upsert(LEGACY_TABLE, crow.to_dict(), note="concept_upsert:mirror")
    push_counters(tx, stmt_id)   # 一个号空间、两个计数器（见 push_counters 的 docstring）
    return data


def _apply_merge_tombstone(row: dict[str, Any], legacy_row: Mapping[str, Any]) -> None:
    """把老表的墓碑（`merged_into`）落到新标准那一行上：`superseded` + 理由。

    新标准里没有 `merged_into` 这一列，但有语义等价的一档 `superseded`
    （"被后来的一条取代"，且在 `STATEMENT_UNUSABLE_STATUSES` 里 ⇒ 下游不许再当依据）。
    不映射的话，一次真的合并会在新标准那一边完全看不见 —— C 的依赖链与收工门会继续
    把被合并的那条当可用命题，而盘上没有任何地方会响。
    """
    into = str(legacy_row.get("merged_into") or "")
    if not into:
        return
    if into == SUPERSEDED_INTO:
        # 投影的哨兵被原样送了回来（`_to_legacy` 的输出当输入用）⇒ 状态对上了就到此为止：
        # 再写一次理由只会把 `quote_reason` 改成"已并入 superseded"这种没人看得懂的话，
        # 而真相（并入的是哪一条）已经写在那一格里了。
        row["status"] = "superseded"
        return
    why = str(legacy_row.get("merge_reason") or "").strip()
    row["status"] = "superseded"
    row["quote_reason"] = (f"已并入 {into}（同步自老表的 merged_into）"
                           + (f"；{why}" if why else ""))


def sync_from_legacy(tx: Any, legacy_row: Mapping[str, Any], *,
                     actor: str = "agent-B") -> dict[str, Any] | None:
    """把一条老表行同步成新标准那一行（同号）—— 写侧搬运的通用一格。

    为什么需要它（这是过渡期最容易漏的一格）：B 的 pipeline 里有好几处是"改一条老行"
    （合并别名、重算 `related_concepts`、结构重复合并），而不是"新建一条"。只把"新建"
    改成两处同号，那些改动就只落在老表上 ⇒ 新标准那一份悄悄过期，而盘上看起来
    一切正常（两边都有那一行，只是内容不同了）。

    口径（三态）：

    - 老行没有 `concept_id` ⇒ 返回 `None`（调用方点名；不猜号）；
    - 新标准里已有同号行 ⇒ 只更新"从老表推得出来的那几格"
      （`label` / `statement_full` / `aliases` / `source_lit_id`），并保留新标准独有的
      那些（`proof_text` 的良定义性证明、`doc_id`、`bits`、`created_at`、`created_by`）
      —— 那些信息老表里根本没有；定义从"没有"变成"有" ⇒ 状态从 `pending_definition`
      回到 `active`（`D12` 甲说的"定义到了就改回 active 并清掉标记"就是这一支）；
    - 新标准里没有 ⇒ 建一条（空定义自动落待补档）。

    返回写进新标准的那一行 dict（调用方可以拿去当读数）。
    """
    cid = str(legacy_row.get("concept_id") or "")
    if not cid:
        return None
    label = str(legacy_row.get("name") or "")
    definition = str(legacy_row.get("definition") or "")
    aliases = [str(a) for a in (legacy_row.get("aliases") or []) if str(a).strip()]
    source_lit = str(legacy_row.get("definition_source_lit_id") or "")
    existing = tx.find("statements", stmt_id=cid)
    if existing is None:
        row = concept_statement(stmt_id=cid, label=label, definition=definition,
                                aliases=aliases, source_lit_id=source_lit, actor=actor)
        data = row.to_dict()
        if str(legacy_row.get("merged_into") or ""):
            # 老表的墓碑在新标准里也要立起来（新建那一支同样要 —— 第一次同步就碰到
            # 一条已经被合并的老行是常事：迁移历史数据时全是这种）
            _apply_merge_tombstone(data, legacy_row)
        obj = S.row_from_dict("statements", data)
        obj.validate()
        data = obj.to_dict()
        tx.upsert("statements", data, note="concept_sync:create")
        push_counters(tx, cid)   # 一个号空间、两个计数器（见 push_counters）
        return data
    updated = dict(existing)
    updated["label"] = label
    updated["statement_text"] = definition
    updated["statement_full"] = definition
    updated["aliases"] = aliases
    updated["source_lit_id"] = source_lit or None
    merge_into = str(legacy_row.get("merged_into") or "")
    if merge_into:
        # 老表的墓碑（`merged_into`）在新标准里没有同名列，但有语义等价的一档：
        # `superseded`（"被后来的一条取代"）。不映射的话，一次真的合并会在新标准那一边
        # 完全看不见 —— 下游（C 的链、收工门）会继续把被合并的那条当可用命题。
        _apply_merge_tombstone(updated, legacy_row)
    elif definition.strip():
        if str(updated.get("status") or "") == "pending_definition":
            updated["status"] = "active"
            updated["quote_reason"] = ("定义已到（同步自老表）⇒ 回到 active；"
                                       + str(updated.get("quote_reason") or ""))
    elif str(updated.get("status") or "") == "active":
        # 反向：老表把定义清空了 ⇒ 新标准那一行不能继续假装有定义
        updated["status"] = "pending_definition"
        updated["quote_reason"] = f"定义被清空（同步自老表）⇒ 回到 {PENDING_SEARCH}"
    obj = S.row_from_dict("statements", updated)
    obj.validate()
    data = obj.to_dict()
    tx.upsert("statements", data, note="concept_sync:update")
    push_counters(tx, cid)   # 一个号空间、两个计数器（见 push_counters）
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
