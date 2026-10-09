# -*- coding: utf-8 -*-
"""把 `concepts` 折进 `statements`（S1r 的迁移内核）—— 纯函数，不碰盘。

业主 2026-10-09：「concept表真并进statements。由于你用"类型"标记了concept的身份，
proof里就证这个概念为什么是良定义的」+「并表了就并干净」。

## 为什么单独一个模块（而不是塞进 `store.rebuild`）

`rebuild` 是 FC-27 禁改区的写入路径（`schema-migration`），而折叠规则本身是纯数据变换：
把它单独放一处，判据可以直接喂夹具（不需要真工作区、不需要跑一次迁移），
`rebuild` 那一侧只留"读事件 → 调这里 → 写快照"三行。改口径只有一处可改。

## 口径（`draft/97` §10.1 / §10.3b / §14.4b / §14.13）

| 旧字段（`concepts`） | 新字段（`statements`） |
|---|---|
| `concept_id` | `stmt_id`（由调用方用同一分配器重发，见 `alloc` 参数 —— 业主 D2：「同表同分配器不可能撞号」） |
| `name` | `label` |
| `definition` | `statement_full`（可以为空，但必须带待补标记，见下） |
| `aliases` | `aliases`（留着：888 条有别名，且不可现算） |
| `definition_source_lit_id` | 有定义 ⇒ `source_lit_id`；没有定义 ⇒ 待补标记 `pending_search` + `quote_reason` 写清 |
| `merged_into` / `merge_reason` | 没有承载点（业主：秘书会查重 ⇒ 合并不会发生）。迁移若碰到非零值 ⇒ 进 `notes` 点名，不静默丢 |
| `normalized_name` | 丢弃（读侧用唯一实现 `textutil.normalize(label)` 现算；现场 640/2233 条与"lower+去空白"对不上，成因是 `pipeline.py:627` 把原始名字写进了这一格） |
| `related_concepts` | 丢弃（那件事由 `relations` 表管） |

固定三格：`kind="concept"`（身份标记）、`origin="own_result"`、
`proof_text="concept:primitive"` + `quote_verified=None` + `quote_reason` 写清
（`Statement.validate` 的硬要求：`quote_verified is not True` ⇒ `quote_reason` 必须非空）。

不许做的事：不许给迁移行编良定义性证明（`proof_text` 固定写"原始概念"这一档）；
不许把"定义空着"读成"定义就是空的"（空 ⇒ `pending_search`，等 A 去搜或 B 自撰）。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

#: 待补标记（`draft/97` §14.13）：定义内容空着时必须带一个，写进 `quote_reason`。
PENDING_SEARCH = "concept:pending_search"
SELF_AUTHORED = "concept:self_authored"

#: 定义待补那一行的建议状态（`STATEMENT_STATUSES` 今天没有这一档：`active` 要求
#: `statement_full` 非空，而 schema.py 里有一条边界注释写着"为'待补'加一个 status 取值
#: ……那是人裁的事"）。所以折叠函数只把它写进读数与待办清单，
#: 由 `draft/93·续` D12 请业主点头之后再决定最终落法（加取值 / 落标记 / 延后建行）。
PENDING_DEFINITION = "pending_definition"

#: 迁移行的良定义性证明那一格（原始概念：义务为空）。
PRIMITIVE_PROOF = "concept:primitive"


def fold_concepts(concept_rows: Iterable[Mapping[str, Any]],
                  *, alloc: Callable[[], str]) -> dict[str, Any]:
    """把 `concepts` 的行折成 `statements` 的行。

    `alloc()` 每调一次发一个新号（生产里传 `tx.alloc_id("statements")` 的包装）——
    概念的新号一律由它给，所以"与既有命题撞号"在结构上不可能（业主 D2 的口径）。

    返回 `{"rows": [...], "id_map": {旧号: 新号}, "notes": [...]}`：
    `notes` 是读数（不是错误）：合并痕迹、空定义待补、没有来源……逐条点名。
    """
    rows: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}
    notes: list[str] = []
    pending: list[dict[str, Any]] = []
    for raw in concept_rows:
        c = dict(raw)
        old_id = str(c.get("concept_id") or "")
        if not old_id:
            notes.append("跳过一行没有 concept_id 的记录（迁移不静默吞行，这里点名）")
            continue
        new_id = str(alloc())
        id_map[old_id] = new_id
        name = str(c.get("name") or "")
        definition = str(c.get("definition") or "")
        src_lit = str(c.get("definition_source_lit_id") or "")
        aliases = [str(a) for a in (c.get("aliases") or []) if str(a).strip()]
        if definition.strip():
            reason = f"迁移自 concepts {old_id}：定义来自 " + (f"literature {src_lit}"
                                                          if src_lit else "原 concepts 行")
            status = "active"
        else:
            reason = (f"迁移自 concepts {old_id}：**原行没有定义** ⇒ 待补"
                      f"（{PENDING_SEARCH}：由直接父/A 检索，或基本概念由 B 自撰）")
            status = PENDING_DEFINITION
            pending.append({"concept_id": old_id, "name": name, "reason": reason})
            notes.append(f"{old_id}（{name}）：定义为空 ⇒ {PENDING_SEARCH}")
        for key, label in (("merged_into", "merged_into"), ("merge_reason", "merge_reason")):
            if str(c.get(key) or "").strip():
                notes.append(f"{old_id}：原行带 {label}={c.get(key)!r} —— "
                             "并表之后没有承载点，这里点名（不静默丢）")
        rows.append({
            "stmt_id": new_id,
            "origin": "own_result",
            "kind": "concept",
            "label": name,
            "statement_text": definition,
            "statement_full": definition,
            "proof_text": PRIMITIVE_PROOF,
            "source_lit_id": (src_lit or None),
            "quote_verified": None,
            "quote_reason": reason,
            "evidence_kind": "heuristic",
            "aliases": aliases,
            "status": status,
            "derived_from": [],
            "doc_id": None,
            "line_range": "",
            "created_at": str(c.get("created_at") or ""),
            "created_by": str(c.get("created_by") or "migrate"),
        })
    if c_has_normalized(concept_rows):
        notes.append("`normalized_name` 一律丢弃（读侧用 `textutil.normalize(label)` 现算；"
                     "现场 640/2233 条与'lower+去空白'对不上，成因是 pipeline.py 把原始名字"
                     "写进了那一格）")
    return {"rows": rows, "id_map": id_map, "notes": notes,
            "pending_search": len(pending), "pending": pending}


def c_has_normalized(rows: Iterable[Mapping[str, Any]]) -> bool:
    """有没有行带 `normalized_name`（用来决定要不要记那条"丢弃"的读数）。"""
    return any(str((r or {}).get("normalized_name") or "").strip() for r in rows)


def remap_concept_ids(relation_rows: Iterable[Mapping[str, Any]],
                      id_map: Mapping[str, str]) -> dict[str, Any]:
    """把 `relations.concept_ids` 里的旧概念号换成新号（改号映射逐条落账）。

    返回 `{"rows": [...], "changed": [...], "missing": [...]}`：
    `changed` 是 `(rel_id, 旧号, 新号)`，`missing` 是"映射表里没有这个号"的那些
    （点名，不静默丢 —— 那说明关系表里挂着一个概念表里没有的号）。
    """
    rows: list[dict[str, Any]] = []
    changed: list[tuple[str, str, str]] = []
    missing: list[tuple[str, str]] = []
    for raw in relation_rows:
        r = dict(raw)
        rid = str(r.get("rel_id") or "")
        old_ids = [str(x) for x in (r.get("concept_ids") or [])]
        new_ids: list[str] = []
        for cid in old_ids:
            if cid in id_map:
                if id_map[cid] != cid:
                    changed.append((rid, cid, id_map[cid]))
                new_ids.append(id_map[cid])
            else:
                missing.append((rid, cid))
                new_ids.append(cid)          # 原样留着：丢掉会让"挂着一个不存在的号"这件事消失
        if new_ids != old_ids:
            r["concept_ids"] = sorted(set(new_ids))
        rows.append(r)
    return {"rows": rows, "changed": changed, "missing": missing}
