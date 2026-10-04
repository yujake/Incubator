# -*- coding: utf-8 -*-
"""续跑被拒时，拒信里要给出「检查点里那条任务原文」（`draft/37` §140）。

真机读数（2026-10-05）：驱动器用"原任务"去续一条以"续作任务"起的检查点 ⇒
`checkpoint_mismatch`；拒信只说"指纹不一致"，没有那句"照抄这个就能续"，
于是那一段成了空段（一步都没跑，而驱动器还以为它在跑）。这条判据守的是
"拒信要可操作"：把检查点里的 `task` 一字不改地交回去。
"""
from __future__ import annotations

import json
import pathlib

from agentflow.agent_loop import run_role, save_run_checkpoint
from agentflow.llmseam import LlmSeam
from agentflow.store import Store

import test_agent_loop as TAL


def test_the_refusal_hands_back_the_task_the_checkpoint_expects(tmp_path: pathlib.Path):
    """正控：`--resume` 拿错任务原文 ⇒ 拒信里逐字给出检查点里那条。"""
    scripts = {"M": [json.dumps({"final": "先跑一段"}, ensure_ascii=False)]}
    st, cond, registry, gw, root = TAL._wired(tmp_path, scripts, max_steps=4)

    first = run_role("M", "原任务：研究 R(m,k)", store=st, registry=registry, conductor=cond,
                     seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                  price=(0.0, 0.0), sid="test-run"),
                     workspace_root=str(root), sid="test-run", from_env=False)
    assert first.stop_reason == "final", first.to_dict()
    # 造一份"停在半路"的检查点（`final` 的检查点会被判 already_finished）
    problem = save_run_checkpoint(root, "M", "test-run", task="原任务：研究 R(m,k)",
                                 step=3, stop_reason="stop_file")
    assert not problem, problem

    second = run_role("M", "续作任务：再往前研究一轮", store=st, registry=registry,
                      conductor=cond,
                      seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                   price=(0.0, 0.0), sid="test-run"),
                      workspace_root=str(root), sid="test-run", from_env=False, resume=True)
    assert second.stop_reason == "checkpoint_mismatch", second.to_dict()
    assert "原任务：研究 R(m,k)" in second.final, second.final
    assert "task" in second.final and "照抄" in second.final, second.final


def test_an_empty_checkpoint_task_still_refuses_clearly(tmp_path: pathlib.Path):
    """三态：检查点里没有 `task` 字段时也要拒得清楚（不许印一个空的"照抄"）。"""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    st = Store(ws)
    st.init()
    cp = ws / "runs" / "agent-M-s.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({"role": "M", "sid": "s", "fingerprint": "deadbeef",
                             "step": 1, "stop_reason": "stop_file"}, ensure_ascii=False),
                  encoding="utf-8")
    run = run_role("M", "任何任务", store=st, registry=None, conductor=None,
                   seam=LlmSeam(role="M", session_root=ws, gateway=None, price=(0.0, 0.0), sid="s"),
                   workspace_root=str(ws), sid="s", from_env=False, resume=True)
    assert run.stop_reason == "checkpoint_mismatch", run.to_dict()
    assert "照抄" in run.final and run.final.strip().endswith("："), run.final
