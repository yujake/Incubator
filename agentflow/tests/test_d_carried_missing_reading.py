# -*- coding: utf-8 -*-
"""D 交付时的携带单缺口读数（`carried_missing`）：不许静默。

## 为什么要这一条（三件里的第三件的第二半）

改前真机（sylow 那一趟）：D 用 `fs.write` 手写了 `reports/RESEARCH.md` ——
自由格式、没有 `## 携带的证明手稿` 那一节 ⇒ B 读到"没有可携带的稿"。那个形态与
"这条证明确实自足"在盘上一模一样：`dependencies` 0 行、`manuscript_source=none`，
而没有任何一处把"这单是空的"报出来。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 缺携带单而有依赖 | 读数 `carried_missing=True`，点名那几条被引用的在册命题 | 改前没有这一格键（`last_delivery` 里根本没有 `carried_missing`） |
| b 携带单在 | `carried_missing=False`（正控：不是恒真的读数） | —— |
| c 反真空 | 把这个读数的算法打桩成"永远不缺" ⇒ a 必红 | —— |
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_d import AgentD
from agentflow.store import Store

THEOREM_A = S.format_id(0)
LEMMA_B = S.format_id(1)


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str, *, derived_from: list[str] | None = None,
                   proof_text: str = "") -> dict:
    """写一条在册命题（`proof_review` 档）。"""
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=proof_text or f"命题 {stmt_id} 的证明正文（判据夹具）。",
        derived_from=list(derived_from or []),
        evidence_kind="heuristic", status="active", quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B")
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    signed = VR.record_verification(
        store.root, statement_id=stmt_id,
        proof_text=str(row.proof_text),
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
        store=store, proof_no=1)
    assert signed.get("checked") is True, signed
    got = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == stmt_id)
    got["evidence_kind"] = "proof_review"
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", got)
    return got


def _d(store: Store) -> AgentD:
    """D 直调（没有 B 的入口）：携带单照样要算，缺口的读数照样要写。"""
    return AgentD(store, config={"workspace_root": store.root})


def _carried_missing(delivery: dict) -> bool:
    """判据本体（正控与反真空共用）：这一趟的读数说"携带单缺了"。"""
    return bool(delivery.get("carried_missing"))


def test_a_missing_carried_sheet_is_a_reading_not_a_silence(tmp_path: pathlib.Path) -> None:
    """a 判据：报告缺携带单、而账上有 statement 引用了在册命题 ⇒ `carried_missing=True`。

    改前红：`last_delivery` 里没有 `carried_missing` 这一格，也没有任何一处把
    "这张单是空的"写进报告 —— 于是"没有可携带的稿"与"这条证明确实自足"同形。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    # 一条引用了在册命题的命题，而盘上没有它的 f-proof 稿 ⇒ 携带单是空的
    _add_statement(store, LEMMA_B, derived_from=[THEOREM_A],
                   proof_text=f"1. 由在册定理得到（依据：stmt:{THEOREM_A}）。")

    d = _d(store)
    path = pathlib.Path(d.write_report())
    delivery = dict(d.last_delivery)

    assert _carried_missing(delivery) is True, delivery
    reason = str(delivery.get("carried_missing_reason") or "")
    assert THEOREM_A in reason, reason
    # 不许静默：这一格也要写进报告正文（下一个人从盘上读得到）
    text = path.read_text(encoding="utf-8")
    assert "carried_missing" in text, text[-2000:]
    assert THEOREM_A in text, text[-2000:]


def test_a_present_carried_sheet_is_not_missing(tmp_path: pathlib.Path) -> None:
    """b 判据（正控）：盘上有那份稿、携带单非空 ⇒ `carried_missing=False`（不是恒真）。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    lemma = _add_statement(store, LEMMA_B, derived_from=[THEOREM_A],
                           proof_text=f"1. 由在册定理得到（依据：stmt:{THEOREM_A}）。")
    # 盘上放一份盖过章的稿（框架渲染的那一版）⇒ 携带单非空
    raw = (DS.SECTION_PROOF + "\n\n"
           f"1. 由在册定理得到（依据：stmt:{THEOREM_A}）。\n\n"
           + DS.SECTION_HEADING + "\n\n"
           "| 引用 | 命题号 | 用在哪一步 | 路径号 |\n"
           "|---|---|---|---|\n"
           f"| 由在册定理 | stmt:{THEOREM_A} | 第 1 步 | 1 |\n")
    text = DS.mark_washed(raw, actor="secretary-F", filled="")
    rel = DS.manuscript_relpath(statement_id=str(lemma["stmt_id"]))
    target = pathlib.Path(store.root) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")

    d = _d(store)
    d.write_report()
    delivery = dict(d.last_delivery)
    assert _carried_missing(delivery) is False, delivery
    # 读数说清"不缺"的理由（携带单上有几条）——不是靠 `False` 这一个字自证
    assert "携带单上有" in str(delivery.get("carried_missing_reason") or ""), delivery


def test_stubbing_the_reading_out_turns_a_red(tmp_path: pathlib.Path,
                                              monkeypatch) -> None:
    """c 判据（反真空）：把这个读数打桩成"永远不缺" ⇒ a 必红。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    _add_statement(store, LEMMA_B, derived_from=[THEOREM_A],
                   proof_text=f"1. 由在册定理得到（依据：stmt:{THEOREM_A}）。")
    monkeypatch.setattr(AgentD, "_carried_missing_reading",
                        lambda self, rows: {"carried_missing": False, "checked": True,
                                            "statement_ids": [], "reason": "（反真空打桩）"})
    d = _d(store)
    d.write_report()
    # a 那条判据的断言是 `is True`；打桩之后同一个场景取到 `False` ⇒ a 必红。
    assert _carried_missing(dict(d.last_delivery)) is False, (
        "读数被打桩成『永远不缺』之后同一个场景还是 True ⇒ a 那条判据没有在核这个算法",
        d.last_delivery)
