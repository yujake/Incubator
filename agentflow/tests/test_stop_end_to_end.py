# -*- coding: utf-8 -*-
"""判据（`draft/37` §130）：主控「自己按停」之后，那一趟真的收工（端到端，不是只判谓词）。

为什么不满足于"直接调 `stopctl`"或"只判 `_user_stop_reason`"：真机的形态是
「模型调工具」 —— 它要看见 `conductor.stop` 的广告面、调得到、而且调完之后
「循环不再问模型第二步」（§125 的真机读数就是"叫停之后它继续跑到第 123 步"）。

这条走完整条路：脚本化模型 → 第二形是 `conductor.stop` 工具调用 → 断言
`stop_reason`、开关落盘、且「模型只被调了一次」（第二次一步都没发生）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import stopctl
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

LOOPS: dict[tuple[str, str], dict[str, Any]] = {}


class _Scripted:
    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def test_the_boss_calling_stop_ends_the_run_and_keeps_the_records(tmp_path: pathlib.Path):
    """M 调 `conductor.stop` ⇒ 这一步之后收工：开关落盘、只调了一次模型。"""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    st = Store(ws)
    st.init()
    gw = _Scripted([
        json.dumps({"tool": "conductor.stop", "args": {"reason": "user"},
                    "why": "用户叫停：收工并告诉同伴停掉子进程"}, ensure_ascii=False),
        json.dumps({"final": "已经停了", "evidence": []}, ensure_ascii=False),
    ])
    backend = LlmBackend(inner=LocalBackend({}), loops=LOOPS, session_root=ws,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=ws,
                                                           gateway=gw, price=(0.0, 0.0), sid="s"),
                         max_steps=5, store=st, sid="s")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg

    run = run_role("M", "用户叫停", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=ws, gateway=gw, price=(0.0, 0.0), sid="s"),
                   session_root=ws, workspace_root=str(ws), sid="s", max_steps=5, from_env=False)
    assert run.stop_reason == "stop_file", run.to_dict()
    assert len(run.steps) == 1, f"停在了第 {len(run.steps)} 步，应当在调完 stop 之后立刻收工"
    assert run.steps[0].shape == "tool", run.steps[0].to_dict()
    assert "叫停" in run.final, run.final
    assert len(gw.prompts) == 1, "停完之后不许再问模型第二步"
    # `draft/37` §140：开关是一次性信号 —— 停一趟、记一笔（`runs/stop-history.jsonl`）、
    # 撤走。改前它留在盘上，于是紧接着的 `--resume` 在第 0 步又被同一把开关停掉
    # （0 步 / 0 次模型调用），而这次停止的产物里写着"可续跑的步检查点 + 续跑简报"。
    assert stopctl.read_stop(ws) is None, "生效过的开关必须被消费掉（否则续跑一开头就被停）"
    history = stopctl.stop_history(ws)
    assert history and history[-1]["by"] == "M", history
    assert history[-1]["consumed_by_sid"] == "s", history
    assert history[-1]["level"] == "stop_file", history
    # 收尾记录照写（强杀那种"什么都不留"才是要避免的形态）
    from agentflow import sessions as SS

    events, problems = SS.read_session(ws, sid="s")
    assert not problems, problems
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    assert ends and ends[-1]["stop_reason"] == "stop_file", ends
