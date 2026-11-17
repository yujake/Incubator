# -*- coding: utf-8 -*-
"""研究成果池：G 写论文时唯一允许依赖的东西。

## 业主口径

G 写论文时能依赖的只有系统侧的研究成果（B 侧原文，或 B 侧有引用记录的其它角色的
手稿与参考文献）；产出不足时不可杜撰，应上报父代理要求扩大研究面。

## 为什么这条要写成读数而不是一句提示词

提示词里早有"落定才成文"，模型读了也照写 —— 所以这里要的是一条判据，而不是又
一句话。

## 三态（本项目的硬纪律）

```
unreadable   —— 台账读不到（没 store / 表坏了）⇒ 不许读成"没有成果"
insufficient —— 读到了：连一条可依赖的成果都没有 ⇒ G 不许成文，要上报父代理扩大研究面
ready        —— 读到了：至少有一条命题带证明正文，或一条可核引文
```

## "可依赖"的判据

一条 `statements` 行算"成果"，当且仅当它有其一：

* `proof_text` 非空 —— B 收录进来了证明正文（"B 侧原文"）；
* `quote_verified is True` —— 那一行的逐字引文回验通过（有可比的原文）。

这两样都没有的命题行只是"登记了个标题"：它不构成 G 可以据以写定理的原料。

## 第二张门票：V 的签（2026-11-17 DOCGATE1）

真机 `projects/lp-ball-6` 的事故现场钉死了另一条入口：`doc.build_document` 此前没有任何
签/地基判据（那道硬闸只装在 `doc.write_mapping` 上），于是 G 在零签（`out/vsigns/` 0 份、
`statements` 35 行里 `proof_text` 非空 0 行）时于 19:42:33 写出 `doc:000000`，而全趟第一份
V 签落在 19:43:40 —— 成文比签早 67 秒（`temp/inv1/REPORT-inv1.md` §2）。

所以"可依赖"多一条入口：`out/vsigns/` 里 ≥1 份签也算有料。理由不是放宽，而是那正是
"研究产出已经过 V 复核"在盘上的凭据 —— 签盖住的是稿的正文 sha，不是标题。反过来，签一份
都没有、`statements` 也一条有效的都没有时，任何成文都是凭空的，必须受控拒。

两个入口（`doc.write_mapping` / `doc.build_document`）都调本模块这一份判据，没有第二份实现。

## 引用面（"B 侧有引用记录"）

顺着 `statements` 往外看的两格：

* `source_lit_id` —— B 登记这条命题时引的那篇文献；
* `doc_id` —— 这条命题出自哪一份手稿。

它们（连同命题自己）就是"B 有引用记录"的那一侧：G 写论文可以依赖这些，
不是"库里有什么就能引什么"。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = ["RESEARCH_BASE_STATES", "research_base", "signs_reading", "writing_gate"]


#: 三态（见模块 docstring）。`unreadable` 不是"没有成果"。
RESEARCH_BASE_STATES: tuple[str, ...] = ("ready", "insufficient", "unreadable")

#: 「有稿无签」清单扫的那一处（与 `vsigns.SIGN_CARRIER_DIR` 同源：签的载体住在 `reports/`）。
_MANUSCRIPT_DIR = "reports"

#: 签落在哪里（只用于拒信里的人话；真身是 `vsigns.SIGNS_DIR`）。
_SIGNS_DIR = "out/vsigns"

#: 产出不足时的下一步（逐条给人话；G 要照着做，而不是自己想办法凑）。
_INSUFFICIENT_NEXT_STEPS: tuple[str, ...] = (
    "让 B 把命题与**证明正文**登记进 `statements`（`proof_text` 非空），"
    "或让 B 收一条逐字引文并回验通过（`quote_verified=true`）",
    "缺的是研究手稿时走正路：让 D 出研究手稿，再由 B 从手稿里收录命题（你 → D → B）",
    "**不许杜撰**：不得用工作区那份原稿、A 的元数据行、或你自己的复述去凑定理与参考文献",
    "确认研究面确实不够 ⇒ 用 `conductor.escalate` 上报父代理，要求扩大研究面（写明缺哪一类）",
)

#: 成文门拒绝时点名的"先拿签"那一步（只给 `doc.build_document` 这一处；
#: `doc.write_mapping` 的下一步仍是 `_INSUFFICIENT_NEXT_STEPS` —— 那一段不动）。
_GATE_NEXT_STEPS: tuple[str, ...] = (
    "先拿签：有稿无签 ⇒ 让产出方把稿送去 V 审（**谁产出谁送审**；G 不自己派 V），"
    "签到了（`out/vsigns/<正文 sha>.json`）再来成文",
    "先补地基：一条有效地基都没有 ⇒ 走 `你 → D → B`（D 出研究手稿、B 从手稿里收录命题），"
    "`proof_text` 或 `quote_verified` 至少有一条落盘再来成文",
)


def _rows(store: Any, table: str) -> tuple[list[Mapping[str, Any]] | None, str]:
    """读一张表；读不到就返回 `(None, 原因)` —— 不许把"读不到"折成空表。"""
    if store is None:
        return None, f"没有传 store（读不到 {table} 台账）"
    try:
        return list(store.rows(table)), ""
    except Exception as exc:  # noqa: BLE001 - 表坏了不许让"成文门"变成崩溃
        return None, f"读 {table} 台账失败：{type(exc).__name__}: {exc}"


def signs_reading(store: Any, *, root: Any = None) -> dict[str, Any]:
    """V 的签与"还在等签的稿"的读数（成文门的第二半，纯读）。

    为什么成文门要读这一格：真机 `projects/lp-ball-6` 里第一份签落在 19:43:40，而 G 在
    19:42:33 就把 `doc:000000` 写进了 `documents` —— 成文比签早 67 秒，当时 `statements`
    那一边一行有效的都没有。所以"签"是那一趟唯一能证明"研究产出已经过 V 复核"的凭据。

    三态（与 `research_base` 同一条纪律）：

        checked=False  —— 签目录列不出来 ⇒ 这一格没查成（不是「一份签都没有」）
        signs          —— `out/vsigns/` 里逐份签文件的份数（口径 `vsigns.signed_table`：
                          权威是逐份签文件，`issued.json` 只用来对账）
        pending        —— `reports/` 里是签载体（`vsigns.is_sign_carrier`）而一份签都
                          没有指到它的稿数；`pending_manuscripts` 逐份列路径

    返回 `{checked, signs, pending, signed_manuscripts, pending_manuscripts, problems, why}`。
    """
    out: dict[str, Any] = {
        "checked": False, "signs": None, "pending": None,
        "signed_manuscripts": [], "pending_manuscripts": [],
        "problems": [], "why": "",
    }
    base_root = root if root is not None else getattr(store, "root", None)
    if base_root is None:
        out["why"] = ("没有工作区根 ⇒ 签与待签稿这两格**没查成**"
                      "（不是「一份签都没有」）")
        return out
    from . import vsigns as _VS   # 惰性：`vsigns` 不反向依赖本模块（不新增模块级依赖边）

    table = _VS.signed_table(base_root)
    if not table.get("checked"):
        out["why"] = f"签目录列不出来（{table.get('why') or '没有理由'}）⇒ 这一格没查成"
        return out
    signed_paths: set[str] = set()
    signed_ids: set[str] = set()
    for entry in table.get("entries") or []:
        rel = str(entry.get("artifact_path") or "").replace("\\", "/")
        if rel:
            signed_paths.add(rel)
        mid = str(entry.get("manuscript_id") or "")
        if mid:
            signed_ids.add(mid)
    pending: list[str] = []
    carriers = 0
    reports = Path(str(base_root)) / _MANUSCRIPT_DIR
    if reports.is_dir():
        for path in sorted(reports.glob("*.md")):
            rel = f"{_MANUSCRIPT_DIR}/{path.name}"
            if not _VS.is_sign_carrier(rel):
                continue
            carriers += 1
            if rel in signed_paths or _VS.manuscript_id_of(rel) in signed_ids:
                continue
            pending.append(rel)
    out.update(
        checked=True, signs=len(table.get("entries") or []), pending=len(pending),
        signed_manuscripts=sorted(signed_paths), pending_manuscripts=pending,
        problems=list(table.get("problems") or []),
        why=(f"`{_SIGNS_DIR}/` 里签 {len(table.get('entries') or [])} 份；"
             f"`{_MANUSCRIPT_DIR}/` 里签载体 {carriers} 份，其中 {len(pending)} 份还没有签"),
    )
    return out


def _gate_readings(base: Mapping[str, Any], signing: Mapping[str, Any]) -> dict[str, str]:
    """四项读数的人话（拒信里逐项点名；两处成文入口共用这一份措辞）。"""
    pending = list(signing.get("pending_manuscripts") or [])
    named = ("、".join(pending[:3]) + (" 等" if len(pending) > 3 else "")) if pending else ""
    return {
        "signs": (f"签 {signing.get('signs')} 份" if signing.get("checked")
                  else "签数**没查成**"),
        "pending": (f"待签稿 {signing.get('pending')} 份" if signing.get("checked")
                    else "待签稿数**没查成**") + (f"（{named}）" if named else ""),
        "base": (f"有效地基 {base.get('effective')} 条（statements {base.get('statements')} 行："
                 f"proof_text 非空 {base.get('with_proof')} 行、"
                 f"quote_verified=true {base.get('verified_quotes')} 行）"),
        "missing": "；".join(str(x) for x in (base.get("missing") or []))
                   or "签与地基两格都没有：既没有一份 V 签，也没有一条带证明正文的命题",
    }


def writing_gate(store: Any, *, root: Any = None) -> dict[str, Any]:
    """成文门的唯一实现：`doc.build_document` 与 `doc.write_mapping` 共用这一份判据。

    真机事故（2026-11-17，`projects/lp-ball-6`）：唯一的硬闸只装在 `doc.write_mapping` 上，
    而 M 把 G 指到了 `doc.build_document`（那里只有机械检查 / 引用存在 / proof 证据锚 /
    覆盖守卫四道闸，一道与签或地基有关的都没有）⇒ G 在零签时成文，比第一份签早 67 秒。
    本函数把那道闸抽成一处实现，两个入口都问它（不是复制一份判据）。

    返回 `{checked, refuse, kind, reason, details, base, signing}`：

    - `refuse=True` ⇒ 调用方受控拒：`kind` 原样当失败码、`reason` 是拒信原文
      （含四项读数：当前签数 / 待签稿数 / 有效地基条数 / 缺哪一条，以及可执行的下一步）、
      `details` 并进工具返回（`research_base` / `signing` / `next_steps`）；
    - `refuse=False` ⇒ 这道门放行（不表示别的闸也会过）。

    放行条件（业主 2026-11-17，两条任一）：≥1 条有效地基（`proof_text` 非空或
    `quote_verified=true`），或 ≥1 份 V 签（`out/vsigns/`）。这不是"一刀切禁止成文"。
    """
    base = research_base(store, root=root)
    signing = dict(base.get("signing") or {})
    state = str(base.get("state") or "")
    if state == "ready":
        return {"checked": True, "refuse": False, "kind": "", "reason": "",
                "details": {}, "base": base, "signing": signing}
    if state == "unreadable":
        reason = (f"{base.get('reason')} ⇒ 成文**没查成**（不是「研究成果够用」，"
                  "也不是「没有成果」）：修好台账再来，一个字节都没写")
        return {"checked": False, "refuse": True, "kind": "ledger_unreadable",
                "reason": reason,
                "details": {"created": False, "written": False, "research_base": base,
                            "signing": signing},
                "base": base, "signing": signing}
    got = _gate_readings(base, signing)
    reason = (
        f"研究成果不足以成文：{got['signs']}、{got['pending']}、{got['base']}。"
        f"缺的是：{got['missing']}。"
        "⇒ **先拿签/先补地基，再来成文**：① 有稿无签 ⇒ 让产出方把稿送去 V 审"
        "（谁产出谁送审，G 不自己派 V），签到了再来；② 一条有效地基都没有 ⇒ 走 "
        "`你 → D → B`（D 出研究手稿、B 从手稿里收录命题）后再来；③ 两样都不够 ⇒ "
        "用 `conductor.escalate` 上报父代理要求扩大研究面。**不许杜撰**，也不许拿工作区那份"
        "原稿 / A 的元数据行凑 —— 这一趟一个字节都没写"
    )
    return {
        "checked": True, "refuse": True, "kind": "no_evidence_chain", "reason": reason,
        "details": {"created": False, "written": False, "research_base": base,
                    "signing": signing,
                    "next_steps": [*_GATE_NEXT_STEPS, *(base.get("next_steps") or [])]},
        "base": base, "signing": signing,
    }


def research_base(store: Any, *, root: Any = None) -> dict[str, Any]:
    """读一次台账，回答"G 手上有没有可依赖的研究成果"（三态 + 逐格读数）。

    返回的键集合是固定的（调用方与判据都按它读）：

        checked        这一块是不是"查过了"的读数（读不到时 False）
        state          ready / insufficient / unreadable
        statements     命题台账行数
        with_proof     其中 `proof_text` 非空的行数
        verified_quotes 其中 `quote_verified is True` 的行数
        effective      有效地基条数（`proof_text` 非空或 `quote_verified is True`；
                       一行同时满足两条只算一条）
        signing        签与待签稿的读数（见 `signs_reading`）
        cited_literature / cited_documents  B 引到的文献与手稿（`lit_id` / `doc_id` 列表）
        missing        产出不足时缺的是哪一格（人话列表）
        next_steps     产出不足时的下一步（人话列表；见 `_INSUFFICIENT_NEXT_STEPS`）
        reason         一句话结论（给人读）

    `ready` 有两个入口（2026-11-17 DOCGATE1）：有效地基 ≥1 条，或 V 的签 ≥1 份。
    两条都没有 ⇒ `insufficient`；`statements` 读不到 ⇒ `unreadable`（不许折成"没有成果"）。
    """
    rows, problem = _rows(store, "statements")
    signing = signs_reading(store, root=root)
    if rows is None:
        return {
            "checked": False, "state": "unreadable",
            "statements": None, "with_proof": None, "verified_quotes": None, "effective": None,
            "signing": signing, "cited_literature": [], "cited_documents": [],
            "missing": [problem], "next_steps": list(_INSUFFICIENT_NEXT_STEPS),
            "reason": f"{problem} ⇒ 成文门**没查成**（不是「研究成果够用」）",
        }

    with_proof = 0
    verified = 0
    effective = 0
    cited_lit: set[str] = set()
    cited_doc: set[str] = set()
    for row in rows:
        has_proof = bool(str(row.get("proof_text") or "").strip())
        is_verified = row.get("quote_verified") is True
        with_proof += 1 if has_proof else 0
        verified += 1 if is_verified else 0
        effective += 1 if (has_proof or is_verified) else 0
        lit = row.get("source_lit_id")
        if str(lit or "").strip():
            cited_lit.add(str(lit))
        doc = row.get("doc_id")
        if str(doc or "").strip():
            cited_doc.add(str(doc))
    cited_lit_sorted = sorted(cited_lit)
    cited_doc_sorted = sorted(cited_doc)

    missing: list[str] = []
    if not rows:
        missing.append("`statements` 一行都没有：没有任何 B 侧收录的命题与证明")
    elif not with_proof and not verified:
        missing.append(
            f"`statements` 有 {len(rows)} 行、但没有一行带证明正文（`proof_text` 全空）、"
            "也没有一行有可核引文（`quote_verified` 都不是 true）：这些只是登记过的标题，"
            "不是 G 可以据以写定理的原料")

    # 第二张门票（2026-11-17）：`out/vsigns/` 里 ≥1 份签也算有料；签这一格没查成时
    # 不许当成"有签"（三态纪律：没查成 ≠ 有）。
    signs = signing.get("signs") if signing.get("checked") else None
    sign_note = ("" if signing.get("checked") else
                 "；签这一格**没查成**（`out/vsigns/` 列不出来），不许读成「0 份签」")
    if not missing:
        state = "ready"
    elif signs:
        state = "ready"
    else:
        state = "insufficient"
    if state == "ready" and missing:
        reason = (f"研究成果池可用（凭据是 V 的签）：`{_SIGNS_DIR}/` 里已有 {signs} 份签；"
                  f"`statements` 那一边仍不足：{missing[0]}")
    elif missing:
        reason = (missing[0] + " ⇒ 按业主 2026-10-28 的口径：**不许成文**，"
                  "要上报父代理要求扩大研究面" + sign_note)
    else:
        reason = (f"研究成果池可用：{len(rows)} 条命题（带证明 {with_proof} / 可核引文 "
                  f"{verified}）；B 引到的文献 {len(cited_lit_sorted)} 篇、"
                  f"手稿 {len(cited_doc_sorted)} 份" + sign_note)
    base: dict[str, Any] = {
        "checked": True,
        "state": state,
        "statements": len(rows),
        "with_proof": with_proof,
        "verified_quotes": verified,
        "effective": effective,
        "signing": signing,
        "cited_literature": cited_lit_sorted,
        "cited_documents": cited_doc_sorted,
        "missing": missing,
        "next_steps": list(_INSUFFICIENT_NEXT_STEPS) if state == "insufficient" else [],
        "reason": reason,
    }
    return base
