# -*- coding: utf-8 -*-
"""临时探针：把「优雅停止」这条路走一遍，看三件事 ——

1. `conductor.stop` 的返回载荷有没有完整落进会话（我在 §139 里怀疑它只剩 `{ok:true}`）；
2. 停止之后盘上有什么：开关 / 续跑简报 / 步检查点；
3. **同一把开关会不会把下一趟（含 `--resume`）在第 0 步就停掉**（这是我怀疑的那个 bug）。

跑法：python -B temp/_stop_probe.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
from typing import Any

sys.path.insert(0, r"D:\Incubator\agentflow")
sys.path.insert(0, r"D:\Incubator\agentflow\src")
sys.path.insert(0, r"D:\Incubator\agentflow\tests")

from agentflow import sessions as SS  # noqa: E402
from agentflow import stopctl  # noqa: E402
from agentflow.agent_loop import LlmBackend, run_role  # noqa: E402
from agentflow.conductor import Conductor, LocalBackend  # noqa: E402
from agentflow.llmseam import LlmSeam  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402


class Scripted:
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


def build(ws: pathlib.Path, replies: list[str]):
    st = Store(ws)
    st.init()
    gw = Scripted(replies)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=ws,
                                                           gateway=gw, price=(0.0, 0.0), sid="s"),
                         max_steps=5, store=st, sid="s")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg
    return st, cond, reg, gw


def run(ws: pathlib.Path, st, cond, reg, gw, *, resume: bool = False, stop_file: str = ""):
    return run_role("M", "用户叫停", store=st, registry=reg, conductor=cond,
                    seam=LlmSeam(role="M", session_root=ws, gateway=gw, price=(0.0, 0.0), sid="s"),
                    session_root=ws, workspace_root=str(ws), sid="s", max_steps=5,
                    from_env=False, resume=resume, stop_file=stop_file)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="probe-stop-") as td:
        ws = pathlib.Path(td) / "ws"
        (ws / "data").mkdir(parents=True)
        stop_call = json.dumps({"tool": "conductor.stop", "args": {"reason": "user"},
                                "why": "用户叫停"}, ensure_ascii=False)
        st, cond, reg, gw = build(ws, [stop_call, json.dumps({"final": "已停"})])
        first = run(ws, st, cond, reg, gw, stop_file=str(ws / ".agentflow-stop"))

        print("== 第 1 趟 ==")
        print("  stop_reason:", first.stop_reason, "| steps:", len(first.steps),
              "| 模型被问了几次:", len(gw.prompts))
        print("  第 1 步的 result（落档视图）:",
              json.dumps(first.steps[0].result, ensure_ascii=False)[:400])
        ev, _ = SS.read_session(ws, sid="s")
        step_ev = [e for e in ev if e.get("kind") == "agent_step"]
        print("  会话里那一步的 result:",
              json.dumps((step_ev[0].get("result") if step_ev else {}), ensure_ascii=False)[:400])
        print("  开关:", json.dumps(stopctl.read_stop(ws), ensure_ascii=False)[:200])
        print("  续跑简报:", (ws / "resume-brief.json").is_file())
        ck = ws / "runs" / "agent-M-s.json"
        print("  步检查点:", ck.is_file(),
              json.dumps(json.loads(ck.read_text(encoding='utf-8')), ensure_ascii=False)[:180]
              if ck.is_file() else "")

        print()
        print("== 第 2 趟（不清开关，直接 --resume）==")
        st2, cond2, reg2, gw2 = build(ws, [json.dumps({"final": "接着干"})])
        second = run(ws, st2, cond2, reg2, gw2, resume=True,
                     stop_file=str(ws / ".agentflow-stop"))
        print("  stop_reason:", second.stop_reason, "| steps:", len(second.steps),
              "| 模型被问了几次:", len(gw2.prompts))
        print("  resumed_from:", second.resumed_from)
        print("  开关还在:", stopctl.read_stop(ws) is not None)

        print()
        print("== 第 3 趟（撤掉开关之后，全新一趟）==")
        stopctl.clear_stop(ws)
        st3, cond3, reg3, gw3 = build(ws, [json.dumps({"final": "干净起步"})])
        third = run(ws, st3, cond3, reg3, gw3, stop_file=str(ws / ".agentflow-stop"))
        print("  stop_reason:", third.stop_reason, "| steps:", len(third.steps),
              "| 模型被问了几次:", len(gw3.prompts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
