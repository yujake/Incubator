# -*- coding: utf-8 -*-
"""停机开关是「一次性信号」（`draft/37` §140 修的那个 bug）：停一趟、记一笔、撤走。

## 那个 bug 的真机形态（实测 `temp/_stop_probe.py`，2026-10-05）

```
第 1 趟：M 调 conductor.stop ⇒ stop_reason=stop_file，开关落盘，续跑简报写了，步检查点写了
第 2 趟：--resume（没人去撤开关）⇒ stop_reason=stop_file，0 步、0 次模型调用
```

于是"优雅停止 → 续跑"这条同一个工具自己承诺的路走不通：`conductor.stop` 的返回里
明明写着 `resume_brief`（"怎么接着跑"），而下一秒那趟续跑就被同一把开关按住了。
连带地，E 的实验子进程也会因为开关一直在盘上而"一出现就被杀"。

处置：把开关当一次性信号 —— 判定生效的那一刻 `stopctl.consume_stop(...)`：
审计写进 `runs/stop-history.jsonl`（谁、什么时候、为什么、被哪一趟用掉），开关文件撤走。
于是"用户第二次叫停"不会再被 `request_stop` 的幂等分支吃掉，续跑与子进程也都不再被旧开关卡住。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import stopctl
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


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


STOP_CALL = json.dumps({"tool": "conductor.stop", "args": {}, "why": "用户叫停"},
                       ensure_ascii=False)
FINISH = json.dumps({"final": "收工"}, ensure_ascii=False)


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    Store(ws).init()
    return ws


def _run(ws: pathlib.Path, replies: list[str], *, resume: bool = False,
         stop_file: str = ""):
    st = Store(ws)
    gw = _Scripted(replies)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=ws,
                                                           gateway=gw, price=(0.0, 0.0), sid="s"),
                         max_steps=5, store=st, sid="s")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg
    run = run_role("M", "用户叫停", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=ws, gateway=gw, price=(0.0, 0.0), sid="s"),
                   session_root=ws, workspace_root=str(ws), sid="s", max_steps=5,
                   from_env=False, resume=resume, stop_file=stop_file or str(ws / ".agentflow-stop"))
    return run, gw


def test_a_resume_after_a_graceful_stop_actually_continues(tmp_path: pathlib.Path):
    """正控（这就是那个 bug）：停完之后同一趟 `--resume` 能接着跑，不再第 0 步被停。

    改前：第 2 趟 `stop_reason=stop_file`、0 步、0 次模型调用（`temp/_stop_probe.py` 的读数）。
    """
    ws = _ws(tmp_path)
    first, gw1 = _run(ws, [STOP_CALL, FINISH])
    assert first.stop_reason == "stop_file" and len(first.steps) == 1, first.to_dict()
    assert stopctl.read_stop(ws) is None, "生效过的开关必须被消费掉"

    second, gw2 = _run(ws, [FINISH], resume=True)
    assert second.stop_reason == "final", second.to_dict()
    assert second.resumed_from == 1, second.to_dict()
    assert len(gw2.prompts) == 1, "续跑那一趟必须真的问了模型一次（改前是 0 次）"


def test_the_user_channel_stop_is_consumed_too(tmp_path: pathlib.Path):
    """正控（用户通道）：`request_stop` 写的开关同样在生效后被消费，之后新一趟照常跑。"""
    ws = _ws(tmp_path)
    stopctl.request_stop(ws, reason="user", by="user")          # 用户先按停
    first, _gw1 = _run(ws, [FINISH])
    assert first.stop_reason == "stop_file", first.to_dict()
    assert len(first.steps) == 0, "开关在跑之前就落了 ⇒ 第 0 步就该收工"
    assert stopctl.read_stop(ws) is None, "开关被这一趟用掉了"
    assert stopctl.stop_history(ws)[-1]["reason"] == "user", stopctl.stop_history(ws)

    later, gw = _run(ws, [FINISH])
    assert later.stop_reason == "final" and len(gw.prompts) == 1, later.to_dict()


def test_a_second_stop_is_not_swallowed_by_the_idempotent_branch(tmp_path: pathlib.Path):
    """负控（另一个方向）：第一把开关被消费之后，用户第二次叫停仍然要生效。

    为什么单列：`request_stop` 是幂等的（"第一次写下的理由不许被覆盖"）。如果开关
    消费后留在盘上，"第二次叫停"会命中幂等分支、什么也不改 —— 那是一个静默失效。
    """
    ws = _ws(tmp_path)
    first, _ = _run(ws, [STOP_CALL, FINISH])
    assert first.stop_reason == "stop_file"
    assert stopctl.read_stop(ws) is None

    second = stopctl.request_stop(ws, reason="user", by="user")
    assert stopctl.read_stop(ws) is not None, "第二次叫停必须重新落一份开关"
    assert second["at"], second
    third, _ = _run(ws, [FINISH])
    assert third.stop_reason == "stop_file" and len(third.steps) == 0, third.to_dict()


def test_a_forced_stop_is_consumed_as_forced(tmp_path: pathlib.Path):
    """正控（强制档）：`force=true` 的开关停成 `force_stop`，历史里记的是强制那一档。"""
    ws = _ws(tmp_path)
    stopctl.request_stop(ws, reason="user", by="user", force=True)
    run, _ = _run(ws, [FINISH])
    assert run.stop_reason == "force_stop", run.to_dict()
    assert stopctl.read_stop(ws) is None
    assert stopctl.stop_history(ws)[-1]["level"] == "force_stop", stopctl.stop_history(ws)


def test_clearing_before_it_takes_effect_leaves_the_run_alone(tmp_path: pathlib.Path):
    """边界：开关在生效之前被撤（`--clear`）⇒ 这一趟照常跑完，历史里不留消费记录。"""
    ws = _ws(tmp_path)
    stopctl.request_stop(ws, reason="写错了", by="user")
    assert stopctl.clear_stop(ws) is True
    run, gw = _run(ws, [FINISH])
    assert run.stop_reason == "final" and len(gw.prompts) == 1, run.to_dict()
    assert stopctl.stop_history(ws) == [], stopctl.stop_history(ws)


def test_consuming_nothing_is_a_no_op(tmp_path: pathlib.Path):
    """负控（反真空）：没有开关时消费它既不报错、也不写历史（不许凭空记一笔）。"""
    ws = _ws(tmp_path)
    assert stopctl.consume_stop(ws, sid="s") == {}
    assert stopctl.stop_history(ws) == []


def test_an_unreadable_switch_still_stops_and_is_consumed(tmp_path: pathlib.Path):
    """三态：坏掉的开关（不是 JSON）读成 `unreadable` ⇒ 照样停（不是"没叫停"），并消费掉。"""
    ws = _ws(tmp_path)
    (ws / ".agentflow-stop").write_text("{这不是 JSON", encoding="utf-8")
    state = stopctl.read_stop(ws)
    assert state is not None and "unreadable" in state, state
    run, _ = _run(ws, [FINISH])
    assert run.stop_reason == "stop_file", run.to_dict()
    assert stopctl.read_stop(ws) is None
    assert "unreadable" in stopctl.stop_history(ws)[-1], stopctl.stop_history(ws)


@pytest.mark.parametrize("lines", [1, 3])
def test_the_history_keeps_every_consumed_stop(tmp_path: pathlib.Path, lines: int):
    """读数面：消费几次就有几行历史（逐行 JSON，坏行不写）。"""
    ws = _ws(tmp_path)
    for i in range(lines):
        stopctl.request_stop(ws, reason=f"r{i}", by="user")
        run, _ = _run(ws, [FINISH])
        assert run.stop_reason == "stop_file"
    hist = stopctl.stop_history(ws)
    assert len(hist) == lines, hist
    assert [h["reason"] for h in hist] == [f"r{i}" for i in range(lines)], hist
