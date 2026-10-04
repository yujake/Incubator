# -*- coding: utf-8 -*-
"""判据（`draft/37` §115）：D 的 `propose_question` —— 从零做研究时"立起第一行问题"的通路。

真机读数（T2 第 1 趟）：主控把 D 的候选动作逐个试过，没有一个能创建第一行
`research_questions`（全部要 qid 已存在，或要一份 C 的分析报告）⇒ 那一趟的 R1 永远是 0 行。
这个动作就是补那一格；它必须 ① 真的落一行、② 拒绝时零写入、③ 出现在 D 的动作表里。
"""
from __future__ import annotations

from pathlib import Path

from agentflow import capabilities as C
from agentflow.agent_d import AgentD
from agentflow.store import Store


def _d(tmp_path: Path) -> tuple[Store, AgentD]:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    st = Store(ws)
    st.init()
    return st, AgentD(st)


def test_a_proposed_question_lands_as_a_row(tmp_path: Path):
    """正控：一句话问题 ⇒ `research_questions` 一行，字段齐全、状态 open。"""
    st, d = _d(tmp_path)
    out = d.propose_question(question="哪些 (m,k) 存在无限 R(m,k)-例子？",
                             kind="gap", priority="high")
    assert out.get("ok") is True, out
    assert out["question_id"] == "0000", out
    rows = st.rows("research_questions")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["question"].startswith("哪些 (m,k)") and row["status"] == "open", row
    assert row["kind"] == "gap" and row["priority"] == "high", row
    assert row["created_at"], "时间戳要落上（否则'什么时候立的'无从回答）"


def test_a_bad_question_is_refused_with_zero_writes(tmp_path: Path):
    """负控：空问题 / 坏 kind / 坏 priority ⇒ 统一拒绝形态，且一行都不许落。"""
    st, d = _d(tmp_path)
    empty = d.propose_question(question="   ")
    assert empty["ok"] is False and empty["kind"] == "bad_question", empty
    assert empty["refusal_reason"] == "invalid_params", empty
    bad_kind = d.propose_question(question="x", kind="nope")
    assert bad_kind["ok"] is False and bad_kind["kind"] == "bad_kind", bad_kind
    bad_prio = d.propose_question(question="x", priority="now")
    assert bad_prio["ok"] is False and bad_prio["kind"] == "bad_priority", bad_prio
    assert st.rows("research_questions") == [], "被拒的那几次不许留下半行"


def test_the_action_is_advertised_on_d_surface():
    """广告面（同一件事的两层）：动作要出现在 D 的动作表里，且带上必填参数提示。"""
    action = next((a for a in C.actions_for("D") if a.action == "propose_question"), None)
    assert action is not None, "D 的动作表里没有 propose_question（模型看不到它就等于没有）"
    props = (action.params or {}).get("properties") or {}
    assert "question" in props, props
    assert "question" in (action.params or {}).get("required", ()), action.params
