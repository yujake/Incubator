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

## 引用面（"B 侧有引用记录"）

顺着 `statements` 往外看的两格：

* `source_lit_id` —— B 登记这条命题时引的那篇文献；
* `doc_id` —— 这条命题出自哪一份手稿。

它们（连同命题自己）就是"B 有引用记录"的那一侧：G 写论文可以依赖这些，
不是"库里有什么就能引什么"。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["RESEARCH_BASE_STATES", "research_base"]


#: 三态（见模块 docstring）。`unreadable` 不是"没有成果"。
RESEARCH_BASE_STATES: tuple[str, ...] = ("ready", "insufficient", "unreadable")

#: 产出不足时的下一步（逐条给人话；G 要照着做，而不是自己想办法凑）。
_INSUFFICIENT_NEXT_STEPS: tuple[str, ...] = (
    "让 B 把命题与**证明正文**登记进 `statements`（`proof_text` 非空），"
    "或让 B 收一条逐字引文并回验通过（`quote_verified=true`）",
    "缺的是研究手稿时走正路：让 D 出研究手稿，再由 B 从手稿里收录命题（你 → D → B）",
    "**不许杜撰**：不得用工作区那份原稿、A 的元数据行、或你自己的复述去凑定理与参考文献",
    "确认研究面确实不够 ⇒ 用 `conductor.escalate` 上报父代理，要求扩大研究面（写明缺哪一类）",
)


def _rows(store: Any, table: str) -> tuple[list[Mapping[str, Any]] | None, str]:
    """读一张表；读不到就返回 `(None, 原因)` —— 不许把"读不到"折成空表。"""
    if store is None:
        return None, f"没有传 store（读不到 {table} 台账）"
    try:
        return list(store.rows(table)), ""
    except Exception as exc:  # noqa: BLE001 - 表坏了不许让"成文门"变成崩溃
        return None, f"读 {table} 台账失败：{type(exc).__name__}: {exc}"


def research_base(store: Any) -> dict[str, Any]:
    """读一次台账，回答"G 手上有没有可依赖的研究成果"（三态 + 逐格读数）。

    返回的键集合是固定的（调用方与判据都按它读）：

        checked        这一块是不是"查过了"的读数（读不到时 False）
        state          ready / insufficient / unreadable
        statements     命题台账行数
        with_proof     其中 `proof_text` 非空的行数
        verified_quotes 其中 `quote_verified is True` 的行数
        cited_literature / cited_documents  B 引到的文献与手稿（`lit_id` / `doc_id` 列表）
        missing        产出不足时缺的是哪一格（人话列表）
        next_steps     产出不足时的下一步（人话列表；见 `_INSUFFICIENT_NEXT_STEPS`）
        reason         一句话结论（给人读）
    """
    rows, problem = _rows(store, "statements")
    if rows is None:
        return {
            "checked": False, "state": "unreadable",
            "statements": None, "with_proof": None, "verified_quotes": None,
            "cited_literature": [], "cited_documents": [],
            "missing": [problem], "next_steps": list(_INSUFFICIENT_NEXT_STEPS),
            "reason": f"{problem} ⇒ 成文门**没查成**（不是「研究成果够用」）",
        }

    with_proof = 0
    verified = 0
    cited_lit: set[str] = set()
    cited_doc: set[str] = set()
    for row in rows:
        if str(row.get("proof_text") or "").strip():
            with_proof += 1
        if row.get("quote_verified") is True:
            verified += 1
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

    state = "insufficient" if missing else "ready"
    base: dict[str, Any] = {
        "checked": True,
        "state": state,
        "statements": len(rows),
        "with_proof": with_proof,
        "verified_quotes": verified,
        "cited_literature": cited_lit_sorted,
        "cited_documents": cited_doc_sorted,
        "missing": missing,
        "next_steps": list(_INSUFFICIENT_NEXT_STEPS) if missing else [],
        "reason": (
            (missing[0] + " ⇒ 按业主 2026-10-28 的口径：**不许成文**，"
             "要上报父代理要求扩大研究面") if missing else
            f"研究成果池可用：{len(rows)} 条命题（带证明 {with_proof} / 可核引文 "
            f"{verified}）；B 引到的文献 {len(cited_lit_sorted)} 篇、"
            f"手稿 {len(cited_doc_sorted)} 份"
        ),
    }
    return base
