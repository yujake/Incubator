"""T0-8 的判据：五个角色的 LLM 插座（kwonly `llm=None`）与"默认零调用"。

依据 `draft/30` §T0-8。三条，缺一不可：

1. 插座存在且是关键字专用：`llm` 必须 `KEYWORD_ONLY` 且默认 `None`
   （位置传参才能传错的路径不存在；默认 None 才能"不接线 = 一个调用都不发"）；
2. 默认零调用：注入一个"任何属性访问就炸"的炸弹 llm，跑每个角色最便宜的离线路径，
   结果必须与 `llm=None` 时逐字段相同，且炸弹一次都没被碰；
3. 插座真的接到唯一缝上：把角色的 `llm` 交给 `judge.judge_json`，能拿到判定 ——
   证明这个插座不是装饰（否则第 2 条"没调用"是真空的）。

第 2 条为什么必须配第 3 条：一个"永远没人碰"的字段与"接上了但默认关"的字段，
在"没炸"这个读数上长得一模一样。第 3 条把两者分开。
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from agentflow import agent_a, agent_e, agent_f, agent_g, agent_h, judge as J
from agentflow.store import Store

ROLES = ("A", "E", "F", "G", "H")


class Bomb:
    """任何属性访问都炸：插座没接线时，绝不该有人碰它。"""

    def __getattr__(self, name: str):
        raise AssertionError(f"llm 被访问了：{name}")


class StubJudge:
    """一个最简的判定方：返回预先给好的 JSON。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete(self, prompt: str) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def _agent_class(role: str):
    """按角色字母取 Agent 类。

    刻意写死名字 `Agent<角色>`（与 `host.py` 的构造器、`agentspec` 的 `class_path` 同一个约定），
    而不是"在模块里扫第一个以 `Agent` 开头的类"：后者在模块 import 进任何 `Agent…` 名字时
    （`goal-7f5116c1` 的 M2 就把 `AgentBrief` 导进了角色模块）会静默取错类 ——
    `dir()` 是字母序，`AgentBrief` 排在 `AgentE` 前面。
    """
    mod = {"A": agent_a, "E": agent_e, "F": agent_f, "G": agent_g, "H": agent_h}[role]
    cls = getattr(mod, f"Agent{role}", None)
    assert inspect.isclass(cls), f"{mod.__name__} 里没有 Agent{role}"
    return cls


def _store(tmp_path: Path) -> Store:
    """一个初始化过的临时工作区。"""
    st = Store(tmp_path)
    st.init()
    return st


def _build(role: str, st: Store, *, llm):
    """按角色构造实例（每个角色的必需依赖不同，这里给最小可用的一组）。"""
    cls = _agent_class(role)
    if role == "A":
        return cls(st, providers=[], llm=llm)
    return cls(st, llm=llm)


def _cheap_call(role: str, agent):
    """每个角色最便宜的离线调用（实测：全都不会碰 llm）。"""
    return {
        "A": lambda: agent.run_once(),
        "E": lambda: agent.list_experiments(),
        "F": lambda: agent.list_plans(),
        "G": lambda: agent.check_claims([]),
        "H": lambda: agent.list_findings(),
    }[role]()


@pytest.mark.parametrize("role", ROLES)
def test_socket_is_keyword_only_with_none_default(role: str):
    """判据 1：插座是关键字专用、默认 None。"""
    cls = _agent_class(role)
    param = inspect.signature(cls.__init__).parameters.get("llm")
    assert param is not None, f"{cls.__name__} 没有 llm 插座"
    assert param.kind is inspect.Parameter.KEYWORD_ONLY, f"{cls.__name__}.llm 不是关键字专用"
    assert param.default is None, f"{cls.__name__}.llm 默认值是 {param.default!r}（应为 None）"


@pytest.mark.parametrize("role", ROLES)
def test_default_socket_makes_zero_calls_and_changes_nothing(role: str, tmp_path: Path):
    """判据 2：炸弹 llm 与 None 的结果逐字段相同，且炸弹一次都没被碰。"""
    bomb = Bomb()
    with_bomb = _cheap_call(role, _build(role, _store(tmp_path / "a"), llm=bomb))
    with_none = _cheap_call(role, _build(role, _store(tmp_path / "b"), llm=None))
    assert with_bomb == with_none, f"{role}: 插上炸弹后结果变了 ⇒ 说明它在用 llm"


@pytest.mark.parametrize("role", ROLES)
def test_socket_reaches_the_only_seam(role: str, tmp_path: Path):
    """判据 3：角色的 `llm` 交给唯一缝能拿到判定 —— 插座不是装饰。"""
    stub = StubJudge({"ok": True, "point": role})
    agent = _build(role, _store(tmp_path), llm=stub)
    data, why = J.judge_json(agent.llm, "probe", point=f"seam-{role}")
    assert why == "" and data == {"ok": True, "point": role}


def test_bomb_is_not_vacuous(tmp_path: Path):
    """判据的判据：炸弹真的会炸（否则上面那条"没碰它"什么都没证明）。"""
    with pytest.raises(AssertionError):
        Bomb().complete("x")
    # 换成一个会记账的判据方：插座被用过就换一个结果（证明"结果相同"是有牙的）
    calls: list[str] = []

    class Counting:
        def complete(self, prompt: str) -> str:
            calls.append(prompt)
            return json.dumps({"n": len(calls)})

    agent = _build("H", _store(tmp_path), llm=Counting())
    first, _why = J.judge_json(agent.llm, "p1")
    second, _why = J.judge_json(agent.llm, "p2")
    assert first != second, "会记账的判定方两次结果必须不同 ⇒ 比较是有牙的"
