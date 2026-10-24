"""D-35 的判据（口径已改：从"取第一条"改为"逐条拆分执行"）。

## 这一条判据现在守什么（口径变更，逐字记下来）

改前的口径（方案 B）：一步给多条工具调用 ⇒ 只执行第 1 条，其余丢弃，只留一句 warn 点名。
它修掉的是更早那一版"多条 ⇒ 整步判 `judge_bad_json`"（r34b 现场：147 步里 10 步整步判废，
token 已经计费、产出全丢），但代价是"其余几条一个字节都没执行" ——
真机三趟（`projects/r34d` + `projects/cube2`）共 76 个多调用步、被丢 107 条，全部是只读。

现在的口径（2026-10-22，业主「multi_call 应该让系统自动整理拆分」）：
一步给 N 条 ⇒ 接住、按原顺序拆成 N 条条目、逐条执行（每条走完整准入/预算/参数校验）、
逐条记账、逐条计步；一条被拒不影响其余；汇总里逐条点名（第 k 条 / 工具名 / 结果一句话）。

所以本文件保留的是当时那三条边界（它们与口径无关，至今仍然成立）：
1. 一条都不给 ⇒ 仍判 invalid（不许因为放宽"多条"把空步也放过）；
2. JSON 真的解析不出 ⇒ 仍判 invalid，且不许记"多条"那条读数（两种错不被混成一类）；
3. 整步被"多条"作废是不允许的（改前更早那一版就是那样）；而"只跑第一条就完事"同样不允许
   （判据末尾核对：两条都真的执行了、步数是拆后的两条 + 收工那一步）。

判据里的模型是桩（`_StubGateway` 按脚本回原生 `tool_calls` 或文本），全程离线、零花销。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import llmseam as LL
from agentflow import modelgw as MG
from agentflow import stepdispatch as SD
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


def _summary_of(run: Any) -> str:
    """这一步的汇总（拆分口径下它挂在回合最后一条的 `warn` 上）。"""
    for step in run.steps:
        text = str(step.result.get("warn") or "")
        if "条调用，已按顺序逐条" in text:
            return text
    return ""


def _first_step_taken(run: Any, gw: _StubGateway) -> None:
    """判据 ①+② 的公共断言（⑤ 把它打桩成"整步作废"，验证这一份真的会红）。"""
    # ① 这一步不是 invalid，而且第一条真的执行了一次工具
    first = run.steps[0]
    assert first.shape == "tool", run.to_dict()
    assert first.problem == "", first.problem
    assert first.result.get("ok") is True, first.result
    assert first.result.get("tool") == "fs.read", first.result
    # 真调了一次工具：结果就是那个文件的内容 —— 而且它进了上下文（下一步的提示词里有它）
    assert SENTINEL in str(first.result), first.result
    assert len(gw.prompts) >= 2, gw.prompts
    assert SENTINEL in gw.prompts[1], gw.prompts[1][-600:]
    # 这一步不被计成坏 JSON（改前更早那一版：整步 invalid、`bad_json` 涨 1）
    assert run.bad_json == 0, run.to_dict()
    assert not [s for s in run.steps if s.problem == "judge_bad_json"], run.to_dict()
    # ② 口径：两条都被拆出来逐条执行（改前方案 B：只执行第 1 条、其余丢弃）
    assert [s.shape for s in run.steps] == ["tool", "tool", "final"], run.to_dict()
    second = run.steps[1]
    assert second.index == 1, run.to_dict()
    assert second.result.get("ok") is True, second.result
    assert second.result.get("tool") == "conductor.ledger", second.result
    # 汇总里逐条点名（第 k 条 / 工具名 / 结果一句话），不再是"只执行第 1 条"
    summary = _summary_of(run)
    assert "这一步给了 2 条调用，已按顺序逐条" in summary, summary
    assert "第 1 条 fs.read 成功" in summary, summary
    assert "第 2 条 conductor.ledger 成功" in summary, summary
    assert "丢弃" not in summary, summary
    # 步数统计：按拆分后的条目记（两条调用 + 收工那一步）
    assert run.stop_reason == "final", run.to_dict()


def test_two_calls_are_both_executed_and_said_so(tmp_path: pathlib.Path):
    """① 一步给 2 条 ⇒ 两条都真的执行、步不算 invalid、汇总里逐条点名。

    改前红（方案 B 那一版）：第 2 条被丢弃 —— `[s.shape for s in run.steps]` 会是
    `["tool", "final"]`、`second.result` 不存在、汇总里写的是"只执行第 1 条"。
    改前更早一版（整步作废）：`first.shape` 是 `invalid`、工具一次都没被调 ——
    那一档由判据 ⑤ 的桩继续守着。
    """
    run, gw = _run(tmp_path, [_two_calls(), _final_call("读完了")])
    _first_step_taken(run, gw)


def test_every_split_item_is_named_with_its_outcome(tmp_path: pathlib.Path):
    """② 三条调用 ⇒ 汇总逐条点名（第 k 条 / 动作真名 / 结果一句话），一条都不许"丢弃"。"""
    run, _gw = _run(tmp_path, [
        {"tool_calls": [
            _call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1"),
            _call("conductor_ledger", {"view": "stats"}, "c2"),
            _call("conductor_state", {}, "c3"),
        ]},
        _final_call("读完了"),
    ])
    summary = _summary_of(run)
    assert "这一步给了 3 条调用，已按顺序逐条" in summary, summary
    # 三条都被拆出来执行了（步数按条目记）
    assert [s.shape for s in run.steps] == ["tool", "tool", "tool", "final"], run.to_dict()
    assert [s.index for s in run.steps] == [0, 1, 2, 3], run.to_dict()
    # 点名用的是动作真名（不是函数广告名）
    for action in ("fs.read", "conductor.ledger", "conductor.state"):
        assert action in summary, summary
    assert "conductor_ledger" not in summary, summary
    assert "丢弃" not in summary, summary


def test_no_call_at_all_is_still_invalid(tmp_path: pathlib.Path):
    """③ 负控：一条都不给 ⇒ 仍判 invalid（放宽"多条"不许把空步也放过）。"""
    run, _gw = _run(tmp_path, [{"tool_calls": []}, _final_call("改对了")], max_steps=4)
    first = run.steps[0]
    assert first.shape == "invalid", run.to_dict()
    assert first.problem == "judge_bad_json", first.problem
    assert "warn" not in first.result, first.result
    assert "条调用，已按顺序逐条" not in json.dumps(first.result, ensure_ascii=False), first.result


def test_a_torn_json_is_still_invalid_and_is_not_called_multi(tmp_path: pathlib.Path):
    """④ 负控：JSON 真的解析不出（少逗号）⇒ 仍 invalid，且不许记"多条"那条读数。

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
    assert "条调用，已按顺序逐条" not in text and "丢弃" not in text, text


def test_the_rule_is_not_vacuous(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """⑤ 反真空：把"多条"打桩成"整步作废"（改前更早那一版）⇒ ① 必红。

    如果 ① 在"整步作废"的桩下也绿，那它证明的不是"这一条的处置对了"，
    而是"这一步根本没被检查"。
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


def test_the_old_take_first_branch_is_gone(tmp_path: pathlib.Path,
                                           monkeypatch: pytest.MonkeyPatch):
    """⑥ 反真空（口径那一侧）：把拆分打桩回"只跑第一条"⇒ ① 必红，且盘上没有逐条记录。

    这一条与 ⑤ 分开：⑤ 守"整步作废"那一档，本一条守"只执行第 1 条"那一档 ——
    两档都要有桩，否则口径一改就可能悄悄退回其中一档而判据全绿。
    """
    real = SD.catch_step_request

    def _only_first(request: SD.StepRequest, *, decode: Any) -> SD.StepDispatch:
        got = real(request, decode=decode)
        return SD.StepDispatch(items=got.items[:1], turn_index=got.turn_index, requested=1)

    monkeypatch.setattr(SD, "catch_step_request", _only_first)
    run, gw = _run(tmp_path, [_two_calls(), _final_call("读完了")])
    with pytest.raises(AssertionError):
        _first_step_taken(run, gw)
    assert [s.shape for s in run.steps] == ["tool", "final"], run.to_dict()
