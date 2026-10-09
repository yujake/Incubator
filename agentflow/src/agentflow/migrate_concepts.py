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

## 两步走：先算计划，再照抄进 `rebuild`（业主 2026-10-09「并干净」）

并表要动磁盘格式（`SCHEMA_VERSION 1→2`、`TABLES` 删 `concepts`、读侧统一新标准），
而迁移是错误不可逆的那一类（`AGENTS.md` 的七类之一）⇒ 顺序定成：

1. `plan_migration(...)`：把"这次迁移会长成什么样"整个算出来（纯函数、确定性、
   可在真盘上只读预演）—— 折出的行、改过的关系、逐条改号账、号冲突 / 悬空号 /
   定义待补 / 并表后同名四组读数；
2. `store.rebuild` 那一笔照抄它（同一套内核 ⇒ 预演与真跑不可能分家）。

真盘预演读数（2026-10-09，62 个工作区、28 个有概念；只读）：
2233 条概念、1752 条关系、既有 147 条命题；813 条要改号（其中 22 条与既有命题撞号
—— 不重发号就会静默顶掉那 22 行）、1342 条关系改号、悬空概念号 0、
定义待补 94 条（全在 p6c/p6e）、并表后同名 0。
报告：`D:\Incubator\temp\_s1r_plan_readings.txt`（脚本 `temp/_s1r_plan_readings.py`）。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

#: 待补标记（`draft/97` §14.13）：定义内容空着时必须带一个，写进 `quote_reason`。
PENDING_SEARCH = "concept:pending_search"
SELF_AUTHORED = "concept:self_authored"

#: 定义待补那一行的状态（`D12` 已裁，2026-10-09 业主选甲）：`STATEMENT_STATUSES` 加了
#: 这一档，且它在 `STATEMENT_UNUSABLE_STATUSES` 里（定义还没到的概念不是依据）。
#: 折叠与写入都必须同时落"待补标记"（`PENDING_SEARCH` / `SELF_AUTHORED`）——
#: `Statement.validate` 会把"没有标记的待补行"当场拒掉（判据在 schema.py 那两条）。
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
            reason = (f"迁移自 concepts {old_id}：原行没有定义 ⇒ 待补"
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


def counter_alloc(start: int = 0, *, width: int = 4,
                  taken: Iterable[str] = ()) -> Callable[[], str]:
    """一个确定性的号分配器（纯函数世界的替身）：从 `start` 起发号、跳过 `taken`。

    生产路径上号由 `Tx.alloc_id("stmt")` 给（E5：唯一分配器、撞号在结构上不可能）；
    这个替身存在的理由是预演：迁移在真盘上会长成什么样，必须能在一张纸上算出来
    （不碰盘、不开事务），而"算出来的号"与"真跑出来的号"要能逐条对上 ——
    对不上就说明预演与迁移不是同一套口径（那正是预演最会骗人的地方）。
    """
    taken_set = {str(x) for x in taken}
    box = {"n": int(start)}

    def _next() -> str:
        while True:
            n = box["n"]
            box["n"] = n + 1
            cand = f"{n:0{width}d}"
            if cand not in taken_set:
                return cand

    return _next


def plan_migration(concept_rows: Iterable[Mapping[str, Any]],
                   relation_rows: Iterable[Mapping[str, Any]],
                   *, existing_stmt_ids: Iterable[str] = (),
                   alloc: Callable[[], str] | None = None,
                   start: int = 0) -> dict[str, Any]:
    """迁移的完整计划：`concepts` 并进 `statements` 会长成什么样（纯函数，不碰盘）。

    这是 `store.rebuild` 那一笔要照抄的东西 —— 预演与真跑必须是同一套口径，
    所以计划与执行共用 `fold_concepts` / `remap_concept_ids` 两个内核，这里只做三件
    "计划才需要"的事：

    1. 发号：不给 `alloc` 就用 `counter_alloc(start, taken=existing_stmt_ids)`
       （确定性替身）；给了就用它（生产传 `tx.alloc_id("stmt")` 的包装）。
    2. 逐条落账：`ledger` 每改一个号一行（旧号、新号、名字、有没有定义、待补标记），
       末行是汇总 —— "这次迁移到底动了什么"必须能逐条复算（`draft/97` §15.2）。
    3. 边界读数：号冲突（概念号与既有命题号撞上 —— 由分配器跳过，但要点名）、
       重复概念名（按 `textutil.normalize` 比）、悬空 `concept_ids`（关系表挂着概念表里
       没有的号）、定义待补条数。这些都是读数，不是错误：迁移照做，但读的人必须看得见。

    返回键：`statements` / `relations` / `id_map` / `ledger` / `changed` / `missing` /
    `notes` / `pending` / `duplicate_names` / `collisions` / `counts`。
    """
    concept_list = [dict(r) for r in concept_rows]
    relation_list = [dict(r) for r in relation_rows]
    taken = {str(x) for x in existing_stmt_ids}
    real_alloc = alloc or counter_alloc(start, taken=taken)
    folded = fold_concepts(concept_list, alloc=real_alloc)
    remapped = remap_concept_ids(relation_list, folded["id_map"])

    # 重复概念名：并表之后两类行住同一张表 ⇒ "同名两条"从"两个表各自的常态"
    # 变成"同一张表里的重名"（秘书查重就是为了让它不发生）。这里只报，不改。
    from . import textutil as _T   # 惰性：归一化的唯一实现

    by_name: dict[str, list[str]] = {}
    for row in concept_list:
        cid = str(row.get("concept_id") or "")
        key = _T.normalize(str(row.get("name") or ""))
        by_name.setdefault(key, []).append(cid)
    duplicate_names = {k: sorted(v) for k, v in by_name.items() if k and len(v) > 1}

    collisions = sorted(set(folded["id_map"]) & taken)
    had_definition = {str(r.get("concept_id") or ""): bool(str(r.get("definition") or "").strip())
                      for r in concept_list}
    names = {str(r.get("concept_id") or ""): str(r.get("name") or "") for r in concept_list}
    ledger: list[dict[str, Any]] = []
    for old_id, new_id in folded["id_map"].items():
        ledger.append({
            "kind": "concept→statement", "old_id": old_id, "new_id": new_id,
            "name": names.get(old_id, ""), "had_definition": had_definition.get(old_id, False),
            "marker": "" if had_definition.get(old_id, False) else PENDING_SEARCH,
        })
    counts = {
        "concepts": len(folded["rows"]),
        "relations": len(remapped["rows"]),
        "renumbered": sum(1 for o, n in folded["id_map"].items() if str(o) != str(n)),
        "collisions_with_existing_statements": len(collisions),
        "relations_changed": len(remapped["changed"]),
        "dangling_concept_ids": len(remapped["missing"]),
        "pending_search": int(folded["pending_search"]),
        "duplicate_names": len(duplicate_names),
    }
    ledger.append({"kind": "summary", **counts})
    return {
        "statements": folded["rows"],
        "relations": remapped["rows"],
        "id_map": dict(folded["id_map"]),
        "ledger": ledger,
        "changed": remapped["changed"],
        "missing": remapped["missing"],
        "notes": folded["notes"],
        "pending": folded["pending"],
        "duplicate_names": duplicate_names,
        "collisions": collisions,
        "counts": counts,
    }


def ledger_lines(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """计划 ⇒ 可以逐行写进 `out/migrate-map.jsonl` 的记录（append-only，一行一件事）。

    为什么单独一个函数：落账的形状由它一处决定，`store.rebuild` 与预演脚本
    因此写出来的是同一种行（读的人不必分辨"这条是预演写的还是迁移写的"）。
    """
    out: list[dict[str, Any]] = []
    for rec in plan.get("ledger") or []:
        out.append({"op": "migrate_map", **dict(rec)})
    for rel_id, old_id, new_id in plan.get("changed") or []:
        out.append({"op": "relation_renumbered", "rel_id": str(rel_id),
                    "old_id": str(old_id), "new_id": str(new_id)})
    for rel_id, missing_id in plan.get("missing") or []:
        out.append({"op": "relation_dangling_concept_id", "rel_id": str(rel_id),
                    "concept_id": str(missing_id),
                    "why": "关系表挂着概念表里没有的号：原样保留并点名（丢掉它等于让"
                           "'挂着一个不存在的号'这件事消失）"})
    return out


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
