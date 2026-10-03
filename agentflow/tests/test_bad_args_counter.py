"""`draft/37` §65 的判据：工具「参数」坏 ≠ 模型「形状」漂移，两者分开计数与停止。

## 为什么要把这一条从 `bad_json` 里拆出来

`judge_bad_args` 是原生工具调用那条路特有的失败：工具名已经从传输层的结构化字段
拿到了（`llmseam.ToolFace.to_shape`），坏的只是 `arguments` 那个字符串不是合法 JSON。
DSH 的 `parseArguments` / `ToolArgsError` 口径是"参数错交回工具层" ——
它是一次可纠正的往返，不是"模型没按协议说话"。

框架此前把两者折进同一个 `run.bad_json`，于是 `max_bad_json=2` 之下
第三次参数写坏就把整趟运行判成 `bad_json_limit` 收场（`draft/37` §50.5 登记的欠账）。
两件事的处置方向不同：形状漂移要收紧协议（提示词/骨架），
参数写坏只要把"哪个函数的参数坏在哪"交回去让它重说一次。

三条判据（缺一条就有个静默方向）：
1. 正控：连着把参数写坏 ⇒ `bad_args_limit`，且 `bad_json` 保持 0；
2. 负控：连着回非 JSON 文本 ⇒ 仍然是 `bad_json_limit`，且 `bad_args` 保持 0
   （拆计数不许把老那条纪律放宽）；
3. 反真空：坏一次、下一次改对 ⇒ 循环继续跑完（`final`）—— 这才是"交回工具层"的意思。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import modelgw as MG
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import LocalBackend
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "bad-args"


class _StubGateway:
    """按脚本回原生 `tool_calls` 的替身网关（不联网）。"""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.prompts: list[str] = []
        self.spec = MG.ModelSpec(model="stub-model", api_key="x", base_url="http://stub")

    def complete(self, prompt: str, *, scope: str, system: Any = None, max_tokens: Any = None,
                 tools: Any = None, tool_choice: str = "auto") -> MG.ModelReply:
        self.prompts.append(prompt)
        item = self.script.pop(0) if self.script else {"tool_calls": []}
        return MG.ModelReply(ok=True, text=str(item.get("text") or ""),
                             tool_calls=tuple(item.get("tool_calls") or ()),
                             tokens_in=1, tokens_out=1, model="stub-model", scope=scope)


def _bad_args_call(name: str = "fs_read") -> dict:
    """一条「工具名对、参数坏」的原生调用（这正是 `judge_bad_args` 的形态）。"""
    return {"tool_calls": [{"id": "c1", "name": name, "arguments": "{这不是 JSON"}]}


def _good_call(name: str = "fs_read") -> dict:
    return {"tool_calls": [{"id": "c2", "name": name,
                            "arguments": json.dumps({"path": "data"}, ensure_ascii=False)}]}


def _final_call(text: str = "做完了") -> dict:
    return {"tool_calls": [{"id": "c9", "name": "framework_final",
                            "arguments": json.dumps({"final": text}, ensure_ascii=False)}]}


def _wired(tmp_path: pathlib.Path, script: list[dict], *, max_steps: int = 6):
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    gw = _StubGateway(script)
    seam = LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid=SID)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=lambda role: seam, max_steps=max_steps, store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    built = build_registry(store=st, conductor=cond, workspace_root=root)
    backend.registry = built.registry
    assert "fs.read" in built.registry.names(), built.skipped
    return st, cond, built.registry, gw, seam, root


def _run(tmp_path: pathlib.Path, script: list[dict], *, max_steps: int = 6):
    st, cond, registry, gw, seam, root = _wired(tmp_path, script, max_steps=max_steps)
    run = run_role("M", "把这件事做完", store=st, registry=registry, conductor=cond,
                   seam=seam, workspace_root=str(root), sid=SID, max_steps=max_steps,
                   from_env=False)
    return run, gw


def test_bad_arguments_have_their_own_stop_reason(tmp_path: pathlib.Path):
    """正控：连着三次参数写坏 ⇒ `bad_args_limit`，而 `bad_json` 一次都没涨。

    这一条正是 §50.5 欠账的判据：折叠计数时它会是 `bad_json_limit`
    （第三次就整趟作废），而参数错本来只需要交回去重说一次。
    """
    run, gw = _run(tmp_path, [_bad_args_call(), _bad_args_call(), _bad_args_call(),
                              _bad_args_call(), _bad_args_call()], max_steps=8)
    assert run.stop_reason == "bad_args_limit", run.to_dict()
    assert run.bad_args >= 3, run.to_dict()
    assert run.bad_json == 0, run.to_dict()
    # 纠正消息点名"是哪个函数的参数坏了"（不是笼统的"形状不合法"）
    joined = "\n".join(gw.prompts)
    assert "fs_read" in joined and "参数" in joined, joined[-600:]
    # 参数坏的那几步不许被当成有效动作（与坏 JSON 同一条纪律）
    assert not [s for s in run.steps if s.shape in ("tool", "summon", "message")], run.to_dict()


def test_shape_drift_still_stops_the_loop(tmp_path: pathlib.Path):
    """负控：连着回非 JSON 文本 ⇒ 仍然是 `bad_json_limit`，且 `bad_args` 是 0。

    拆分计数不许变成放宽：文本那条路（没有原生调用）一个字都没改。
    """
    run, _gw = _run(tmp_path, [{"text": "这不是 JSON"}, {"text": "{也不是}"},
                               {"text": "还是不是"}], max_steps=6)
    assert run.stop_reason == "bad_json_limit", run.to_dict()
    assert run.bad_json >= 3 and run.bad_args == 0, run.to_dict()


def test_one_bad_argument_batch_is_handed_back_and_the_run_continues(tmp_path: pathlib.Path):
    """反真空：坏一次、下一次改对 ⇒ 循环继续跑到 `final`（不是"错了就整趟作废"）。"""
    run, _gw = _run(tmp_path, [_bad_args_call(), _good_call(), _final_call("交回后改对了")],
                    max_steps=6)
    assert run.stop_reason == "final", run.to_dict()
    assert run.final == "交回后改对了", run.final
    assert run.bad_args == 1 and run.bad_json == 0, run.to_dict()
    assert [s.shape for s in run.steps] == ["invalid", "tool", "final"], run.to_dict()
