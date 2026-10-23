"""D-35（方案 B）的判据：一步给多条工具调用 ⇒ 只执行第一条，其余丢弃但必须留读数。

## 这一条修的是什么（r34b 现场，硬证据）

147 步里有 10 步被整步判废：`agent_step.result.problem=judge_bad_json`，
`detail` 是"这一步给了 2 条工具调用；本循环一步只做一件事，请只留一条"。
代价不是"少一步"：token 已经计费（有的步 `tokens_out` 到 6000），而这一步的产出全丢。
同一趟里另有 1 条是 JSON 少逗号的解析错 —— 那是模型输出真的坏了，与"多条"不是一件事。

## 口径（方案 B：只改解析层）

1. 多条 ⇒ 执行第一条，其余丢弃；丢弃必须留读数（`result.warn` 里点名被丢的 action）；
2. 一条都不给 ⇒ 仍判 invalid（不许因为这次放宽把空步也放过）；
3. JSON 真的解析不出 ⇒ 仍判 invalid，且不许记"多条"那条 warning（两种错不被混成一类）；
4. 主循环结构、步数统计、停止条件都不动（判据末尾核对步数）。

判据里的模型是桩（`_StubGateway` 按脚本回原生 `tool_calls` 或文本），全程离线、零花销。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import llmseam as LL
from agentflow import modelgw as MG
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "d35"
#: 第一步那个工具真正读到的内容（它出现在第二步的提示词里 ⇒ "结果进上下文"可核）。
SENTINEL = "SENTINEL-D35-第一条被执行了"


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


def _call(name: str, args: dict, cid: str) -> dict:
    return {"id": cid, "name": name, "arguments": json.dumps(args, ensure_ascii=False)}


def _two_calls() -> dict:
    """一句回复里给两条原生调用：第一条是真能执行的文件读，第二条是另一件工具。"""
    return {"tool_calls": [
        _call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1"),
        _call("conductor_ledger", {"view": "stats"}, "c2"),
    ]}


def _final_call(text: str = "做完了") -> dict:
    return {"tool_calls": [_call("framework_final", {"final": text, "evidence": []}, "c9")]}


def _wired(tmp_path: pathlib.Path, script: list[dict], *, max_steps: int = 4):
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "sentinel.txt").write_text(SENTINEL, encoding="utf-8")
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


def _run(tmp_path: pathlib.Path, script: list[dict], *, max_steps: int = 4):
    st, cond, registry, gw, seam, root = _wired(tmp_path, script, max_steps=max_steps)
    run = run_role("M", "把 sentinel 读出来", store=st, registry=registry, conductor=cond,
                   seam=seam, workspace_root=str(root), sid=SID, max_steps=max_steps,
                   from_env=False)
    return run, gw


def _first_step_taken(run: Any, gw: _StubGateway) -> None:
    """判据 ①+② 的公共断言（⑤ 把它打桩成"全丢"，验证这一份真的会红）。"""
    # ① 第一步不是 invalid，而是真的执行了一次工具
    first = run.steps[0]
    assert first.shape == "tool", run.to_dict()
    assert first.problem == "", first.problem
    assert first.result.get("ok") is True, first.result
    assert first.result.get("tool") == "fs.read", first.result
    # 真调了一次工具：结果就是那个文件的内容 —— 而且它进了上下文（下一步的提示词里有它）
    assert SENTINEL in str(first.result), first.result
    assert len(gw.prompts) >= 2, gw.prompts
    assert SENTINEL in gw.prompts[1], gw.prompts[1][-600:]
    # 这一步不被计成坏 JSON（改前：整步 invalid、`bad_json` 涨 1）
    assert run.bad_json == 0, run.to_dict()
    assert not [s for s in run.steps if s.problem == "judge_bad_json"], run.to_dict()
    # ② 读数里点名被丢的那几条的 action（广告名映回真名，可核）
    warn = str(first.result.get("warn") or "")
    assert "只执行第 1 条" in warn, first.result
    assert "conductor.ledger" in warn, warn
    assert "其余 1 条丢弃" in warn, warn
    # 步数统计没被动（两步：工具一步 + 收工一步）
    assert [s.shape for s in run.steps] == ["tool", "final"], run.to_dict()
    assert run.stop_reason == "final", run.to_dict()


def test_two_calls_execute_the_first_and_say_so(tmp_path: pathlib.Path):
    """① 一步给 2 条 ⇒ 第一条被执行、步不算 invalid、读数里有"只执行第 1 条"的 warning。

    改前红：整步 `judge_bad_json`（`detail`="这一步给了 2 条工具调用…"），工具一次都没被调，
    于是 `first.shape == "tool"` 与 `SENTINEL in first.result` 两条先红。
    """
    run, gw = _run(tmp_path, [_two_calls(), _final_call("读完了")])
    _first_step_taken(run, gw)


def test_the_dropped_actions_are_named(tmp_path: pathlib.Path):
    """② 读数里点名被丢的那几条的 action（这里是 `conductor.ledger`，不是广告名）。"""
    run, _gw = _run(tmp_path, [
        {"tool_calls": [
            _call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1"),
            _call("conductor_ledger", {"view": "stats"}, "c2"),
            _call("conductor_state", {}, "c3"),
        ]},
        _final_call("读完了"),
    ])
    warn = str(run.steps[0].result.get("warn") or "")
    assert "只执行第 1 条" in warn, warn
    assert "其余 2 条丢弃" in warn, warn
    # 两条被丢的都点名，且是动作真名（不是函数广告名 conductor_ledger）
    for action in ("conductor.ledger", "conductor.state"):
        assert action in warn, warn
    assert "conductor_ledger" not in warn, warn


def test_no_call_at_all_is_still_invalid(tmp_path: pathlib.Path):
    """③ 负控：一条都不给 ⇒ 仍判 invalid（放宽"多条"不许把空步也放过）。"""
    run, _gw = _run(tmp_path, [{"tool_calls": []}, _final_call("改对了")], max_steps=4)
    first = run.steps[0]
    assert first.shape == "invalid", run.to_dict()
    assert first.problem == "judge_bad_json", first.problem
    assert "warn" not in first.result, first.result
    assert "只执行第 1 条" not in json.dumps(first.result, ensure_ascii=False), first.result


def test_a_torn_json_is_still_invalid_and_is_not_called_multi(tmp_path: pathlib.Path):
    """④ 负控：JSON 真的解析不出（少逗号）⇒ 仍 invalid，且不许记"多条"那条 warning。

    两种错的处置方向不同（一个要重说协议、一个只是多给了一条），
    混成一类会让"这一步到底怎么了"在台账上不可回答。
    """
    torn = '{"tool": "fs.read", "args": {"path": "data/sentinel.txt" "why": ""}}'
    run, _gw = _run(tmp_path, [{"text": torn}, _final_call("改对了")], max_steps=4)
    first = run.steps[0]
    assert first.shape == "invalid", run.to_dict()
    assert first.problem == "judge_bad_json", first.problem
    assert "解析报错" in str(first.result.get("detail") or ""), first.result
    assert "warn" not in first.result, first.result
    text = json.dumps(first.result, ensure_ascii=False)
    assert "只执行第 1 条" not in text and "丢弃" not in text, text


def test_the_rule_is_not_vacuous(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """⑤ 反真空：把"只取第一条"打桩成"全丢" ⇒ ① 必红。

    如果 ① 在"全丢"的桩下也绿，那它证明的不是"取第一条"，而是别的什么
    （例如"这一步根本没被检查"）。
    """
    real = LL.LlmSeam.ask_step

    def _drop_all(self: Any, prompt: str, **kw: Any):
        data, call = real(self, prompt, **kw)
        if len(getattr(call, "tool_call_list", ()) or ()) > 1:
            return None, LL.SeamCall(
                **{**call.__dict__, "ok": False, "problem": "judge_bad_json",
                   "detail": "这一步给了 2 条工具调用；本循环一步只做一件事，请只留一条"})
        return data, call

    monkeypatch.setattr(LL.LlmSeam, "ask_step", _drop_all)
    run, gw = _run(tmp_path, [_two_calls(), _final_call("读完了")])
    with pytest.raises(AssertionError):
        _first_step_taken(run, gw)
