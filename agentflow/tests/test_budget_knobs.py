# -*- coding: utf-8 -*-
"""预算旋钮的判据（`draft/37` §16 P0 后半 / §17 第一档）：步数、输出额度、墙钟、观测窗口。

为什么这四个数各要一条判据（真机读数，2026-10-01）：

· 步数：框架默认 `max_steps=6`，而一个被驱动的动作连「读完一段正文」都不够 ——
  G 那一轮拿了 151 步（89 次读、53 次写自己的笔记），最后还是没能落盘一处改动；
· 输出额度：网关缺省 4,096 token，而「写完一段 LaTeX + JSON 信封」动辄几千 token
  ⇒ 写稿步会被静默截断（表现是 `judge_bad_json` 或半句话）；
· 墙钟：写死的 900 秒是真机里第 8 次派活被挡下的那道门（`deadline_exceeded`）；
· 观测窗口：`RESULT_CHARS=3000` 必须容得下「一条定理」的切片（≤2,600 字），
  否则「拆条目逐条改」这条路在观测层就被掐断了。

判据一律是「旋钮真的接到了对方手上」，不是「我改了一个数字」：每个值都在
「被读走的那一处」断言，并各带一条负控（不给旋钮时不许假装给过）。
"""
from __future__ import annotations

import inspect
import pathlib
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import autonomy as AU
from agentflow import cli
from agentflow import host as H
from agentflow import modelgw as MG
from agentflow import policy as P
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools.conductor_tools import reset_cache

#: 一条「定理切片」的字符上限（`draft/37` §16 P0 第三行）。观测窗口必须容得下它。
STATEMENT_SLICE_CHARS = 2600
#: 写稿步输出额度的下限（`draft/37` §16 P0 第二行）。
WRITING_OUTPUT_TOKENS = 8192


class _Recorder:
    """照剧本回答的替身模型：把每次调用收到的 `max_tokens` 逐个记下来。"""

    spec = type("Spec", (), {"model": "recorder", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """记下这次调用拿到了什么，然后回剧本里的下一条。"""
        self.calls.append({"prompt": prompt, "kw": dict(kw)})
        text = self.replies.pop(0) if self.replies else '{"final": "ok", "evidence": []}'
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()

    @property
    def max_tokens_seen(self) -> list[Any]:
        """每次调用收到的 `max_tokens`（没传就是 None，不许当成没发生）。"""
        return [c["kw"].get("max_tokens") for c in self.calls]


def _wired(tmp_path: pathlib.Path):
    """造一个工作区 + 主控 + 工具层（与 `test_agent_loop._wired` 同一条装配路）。"""
    st = Store(tmp_path / "ws")
    st.init()
    inner = LocalBackend({})
    cond = Conductor(st, policy=None, backend=inner)
    built = build_registry(store=st, conductor=cond)
    return st, cond, built.registry, tmp_path / "ws"


def test_the_step_budget_is_enough_to_finish_a_task() -> None:
    """步数默认值必须够做一件事，而且六个落点不许各写一个数。

    步数这一个旋钮在仓里有六个落点：循环本体、`run_role`、`LlmBackend`、
    `wired_llm_conductor`、`autonomy.run_autonomous`（自主多轮那条路）、CLI。
    它们分家时的表现是「看起来一样、跑起来不一样」，而没有任何一条测试会红 ——
    所以这里逐个读回来比对，而不是只看我自己改的那一处。
    （这一条判据第一次写的时候只列了五个落点，漏了 `autonomy.run_autonomous`：
    它当时还是 6 —— 漏掉的那一个正是判据本身要防的形态。）
    """
    seen = {
        "AgentLoop.max_steps": AL.AgentLoop.__dataclass_fields__["max_steps"].default,
        "LlmBackend.max_steps": AL.LlmBackend.__dataclass_fields__["max_steps"].default,
        "run_role(max_steps)": inspect.signature(AL.run_role).parameters["max_steps"].default,
        "wired_llm_conductor(max_steps)":
            inspect.signature(H.wired_llm_conductor).parameters["max_steps"].default,
        "run_autonomous(max_steps)":
            inspect.signature(AU.run_autonomous).parameters["max_steps"].default,
        "cli --max-steps": cli.build_parser().parse_args(
            ["run-agent", "M", "--task", "x"]).max_steps,
    }
    assert min(seen.values()) >= 20, (
        f"步数默认值太小：真机实测一个动作要几十步（G 一轮 151 步），默认 6 连读完一段正文"
        f"都不够。读到的落点是 {seen}")
    assert len(set(seen.values())) == 1, (
        f"同一个旋钮的落点分家了（{seen}）—— 这正是「看起来一样、跑起来不一样」的形态")


def test_the_writing_step_passes_a_larger_output_allowance(tmp_path: pathlib.Path) -> None:
    """写稿步必须显式把输出额度递到网关；不给旋钮的调用仍走网关缺省（负控）。"""
    st, cond, registry, root = _wired(tmp_path)
    gw = _Recorder(['{"final": "写完了", "evidence": []}'])
    seam = LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid="t")
    run = AL.run_role("M", "写一段", store=st, registry=registry, conductor=cond, seam=seam,
                      workspace_root=str(root), sid="t", from_env=False, max_steps=1)
    assert run.stop_reason == "final", run.to_dict()
    want = AL.AgentLoop.__dataclass_fields__["max_output_tokens"].default
    assert gw.max_tokens_seen == [want], (
        f"循环步应当把 max_output_tokens={want} 显式传给网关，实测收到 {gw.max_tokens_seen}")
    assert want >= WRITING_OUTPUT_TOKENS > MG.ModelSpec().max_tokens, (
        f"写稿步的输出额度 {want} 必须大于网关缺省 {MG.ModelSpec().max_tokens} —— "
        "否则「写一段 LaTeX + JSON 信封」会被静默截断")

    # 负控：不传旋钮的调用不许被这次改动顺手改掉（`None` ⇒ 网关按 spec 缺省兜底）
    gw2 = _Recorder(['{"ok": true}'])
    seam2 = LlmSeam(role="M", session_root=root, gateway=gw2, price=(0.0, 0.0), sid="t")
    data, call = seam2.ask_json("只要一份 JSON")
    assert data == {"ok": True} and call.ok, (data, call.problem)
    assert gw2.max_tokens_seen == [None], (
        "没有显式传 max_tokens 的调用必须把 None 交给网关（由 spec 缺省兜底），"
        f"实测收到 {gw2.max_tokens_seen}")


def test_the_observation_window_fits_one_statement_slice() -> None:
    """观测窗口（`RESULT_CHARS`）必须容得下「一条定理」的切片；超出时仍要截断（负控）。"""
    assert AL.RESULT_CHARS >= STATEMENT_SLICE_CHARS, (
        f"RESULT_CHARS={AL.RESULT_CHARS} 容不下 {STATEMENT_SLICE_CHARS} 字的定理切片 —— "
        "「拆条目逐条改」这条路会在观测层被掐断（§16 P0 第三行）")
    payload = "x" * STATEMENT_SLICE_CHARS
    assert payload in AL._clip_fields({"text": payload}), "一条 2,600 字的切片必须原样通过观测层"
    over = AL._clip_fields({"text": "y" * (AL.RESULT_CHARS + 50)})
    assert "…（该字段原" in over, (
        "超过窗口的字段必须被截断并写明「这是观测层的截断，不是内容没了」—— 不许静默丢内容；"
        f"实测：{over[:200]}")


def test_the_wall_clock_is_configurable_and_live(tmp_path: pathlib.Path) -> None:
    """墙钟可配：CLI 显式给值 ⇒ 一路进到主控的 policy；不给 ⇒ 用 policy 缺省（负控）。"""
    parser = cli.build_parser()
    assert parser.parse_args(["run-agent", "M", "--task", "x"]).wall_clock_sec == 3600.0
    assert parser.parse_args(["run-agent", "M", "--task", "x",
                              "--wall-clock-sec", "5"]).wall_clock_sec == 5.0
    assert P.Policy().wall_clock_sec == 900, (
        "policy 的缺省不该被这次改动顺手改掉：`run-agent` 的 CLI 缺省是 3600 秒，"
        "而框架缺省仍是 900 秒 —— 两者不同是刻意的，但都必须说得出出处")

    st, cond, registry, root = _wired(tmp_path)
    reset_cache()
    wiring = H.wired_llm_conductor(st, loops={}, session_root=root, sid="t",
                                   workspace_root=str(root),
                                   policy=P.Policy(wall_clock_sec=7.0))
    assert wiring["conductor"].policy.wall_clock_sec == 7.0, (
        "显式传进去的 policy 必须被主控真的用上（不是收下就扔）—— "
        "这一读数是反真空的：主控的 policy 是它在内部新建的，7.0 只可能来自这次的实参"
        "（缺省是 900，见下一条断言）")
    # 负控：非法值当场抛 —— 证明这个旋钮是活的，不是装饰
    with pytest.raises(ValueError):
        P.Policy(wall_clock_sec=0)
