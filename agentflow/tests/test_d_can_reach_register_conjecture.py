# -*- coding: utf-8 -*-
"""判据 ③(a)(b)：D 够不到任何「登记一条猜想」的面（业主 2026-11-13 裁定甲）。

## 这一份改前钉的是相反的事

改前文件名就叫 `test_d_can_reach_register_conjecture.py`，判据是"D 在模型驱动模式下能
直接调到 `conjecture.register_conjecture`"（当时那一格还是个缺陷：名字对上了工具却没装配）。

业主 2026-11-13 的裁定把那条路整个撤了：「D 不该立项临时命题，D 只给研究方向让下面的
人去研究」。于是这一份按同一副骨架翻成反方向（对齐，不是放宽）：

| # | 判据 |
|---|---|
| a | D 的动作表里没有 `register_conjecture`（`capabilities` 也读不到这一对） |
| b | 共享工具面 / D 自己的工具面上都没有 `conjecture.register_conjecture`；真调一次 ⇒ 失败（不是静默成功） |
| c | 跑一轮 D 的循环，模型喊 `own.register_conjecture` ⇒ 这一步受控失败（`unknown_tool`），且 `conjectures` 零新增 |
| d | 反真空：同一轮里模型调一件 D 真有的工具 ⇒ 那一步成功（证明"零新增"不是因为这一轮什么都没跑成） |

零网络、零真实模型：替身模型只回剧本。
"""

from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_loop as AL
from agentflow import capabilities as C
from agentflow import specs
from agentflow.agent_d._support import install_d_tools
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

ACTION = "register_conjecture"
TOOL = "conjecture.register_conjecture"
OWN = "own.register_conjecture"


class _Scripted:
    """照剧本回答的替身模型：每次取一条，取完重复最后一条。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _world(tmp_path: pathlib.Path):
    st = Store(tmp_path / "ws")
    st.init()
    gw = _Scripted([])
    backend = AL.LlmBackend(inner=LocalBackend({}), loops={},
                            session_root=st.root, store=st, sid="t")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    return st, cond, reg, gw


def _drive(st: Store, cond, reg, gw, replies: list[str]) -> AL.LoopRun:
    gw.replies = list(replies)
    return AL.run_role("D", "研究：把一个研究方向推进一步", store=st, registry=reg,
                       conductor=cond, gateway=gw, session_root=st.root, sid="t",
                       from_env=False, max_steps=4)


# ---------------------------------------------------------------- a：动作面

def test_a_the_action_is_gone_from_ds_face() -> None:
    """a：D 的动作表里没有 `register_conjecture`（撤销之后不许被谁加回来）。"""
    acts = [str(a.action) for a in specs.builtin_specs()["D"].actions]
    assert ACTION not in acts, f"D 的动作面里又有它了：{acts}"
    assert ("D", ACTION) not in set(C.unmapped_actions()), (
        "`capabilities` 仍把它算成一条 D 的动作（登记过期）")


# ---------------------------------------------------------------- b：工具面

def test_b_no_face_carries_the_conjecture_tool(tmp_path: pathlib.Path) -> None:
    """b：共享工具面与 D 自己的工具面上都没有那件工具，真调一次也拿不到。"""
    st = Store(tmp_path / "ws")
    st.init()
    shared = build_registry(store=st, workspace_root=str(st.root)).registry
    assert TOOL not in set(shared.names()), (
        f"共享工具面上又有 `{TOOL}` 了 —— 台账的唯一写点在库层"
        "（`agentflow.conjectureledger`），工具面不该再有第二个入口")
    own = install_d_tools(st)
    assert TOOL not in set(own.names()), f"D 的自建工具面上还有 `{TOOL}`"
    res = own.call(TOOL, statement="谱落在 [-m, m] 内。", origin="gap")
    assert res.ok is False, f"喊一个不存在的工具却成功了：{res.data}"


# ---------------------------------------------------------------- c/d：跑一轮循环

def test_c_a_round_of_ds_loop_lands_zero_new_conjectures(tmp_path: pathlib.Path) -> None:
    """c：模型喊 `own.register_conjecture` ⇒ 受控失败，且 `conjectures` 零新增。"""
    st, cond, reg, gw = _world(tmp_path)
    run = _drive(st, cond, reg, gw, [
        json.dumps({"tool": OWN, "args": {"statement": "谱落在 [-m, m] 内。",
                                          "origin": "gap", "status": "needs_evidence",
                                          "notes": "夹具：D 想自己立一条"},
                    "why": "（找一条可判的猜想）"}, ensure_ascii=False),
        json.dumps({"final": "这一轮只给方向，没有立题", "evidence": []}, ensure_ascii=False),
    ])
    steps = [s for s in run.steps if s.shape == "tool"]
    assert steps, [(s.shape, s.result) for s in run.steps]
    first = dict(steps[0].result)
    assert first.get("ok") is False, f"D 竟然调到了 {OWN}：{first}"
    blob = json.dumps(first, ensure_ascii=False)
    assert ("unknown" in blob) or ("没有" in blob) or ("不存在" in blob), blob
    assert st.rows("conjectures") == [], f"D 自己立了一条：{st.rows('conjectures')}"


def test_d_the_same_round_can_still_call_a_tool_d_really_has(tmp_path: pathlib.Path) -> None:
    """d（反真空）：同一副夹具调一件 D 真有的工具 ⇒ 那一步成功。

    没有这一条，上面那条"零新增"可能只是"这一轮什么都没跑成"。
    """
    st, cond, reg, gw = _world(tmp_path)
    run = _drive(st, cond, reg, gw, [
        json.dumps({"tool": "research.list_gaps", "args": {},
                    "why": "先看工作台上的问题"}, ensure_ascii=False),
        json.dumps({"final": "看过了，给方向", "evidence": []}, ensure_ascii=False),
    ])
    steps = [s for s in run.steps if s.shape == "tool"]
    assert steps, [(s.shape, s.result) for s in run.steps]
    first = dict(steps[0].result)
    assert first.get("ok") is True, first
    assert st.rows("conjectures") == []
