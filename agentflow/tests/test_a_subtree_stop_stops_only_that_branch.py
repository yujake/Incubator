# -*- coding: utf-8 -*-
"""S4-a：子树停 —— 一把开关只管它那一支（业主 S4=4a / `draft/90` E7）。

业主口径（`draft/84` §2.2 的表）：可停范围从"整个工作区"变成子树（"停 D 那一支"），
传达方式从"大家读同一个文件"变成"父把通知沿自己的出边传下去"；全局停只是"根是根"的特例。
这一批做前半：作用面（这把开关管哪一支）；后半（沿边下发 notice + ack 才消边）另作一批。

## 判据（正控 3 / 负控 2 / 反真空 1）

正控：① 子树开关：那一支里的循环停（`stop_reason="stop_file"`），别的支不停；
  ② 那一支的根自己撤开关，成员不撤（同支别的循环还要读到它）；
  ③ 缺省（没有 `root_task_id`）⇒ 全停 + 第一个读到的人撤（老行为逐字不变）。

负控：① 判不了（台账里没有我这一行 / 没给编号）⇒ 不停 + 一句读数；
  ② 别的支里那些循环不许因为"盘上有开关"就停（子树开关不是全停）。

反真空：消费留痕（`runs/stop-history.jsonl`）—— 成员那一笔 `removed=False`、
根那一笔 `removed=True`，两笔都在（"谁读到过、谁撤的"要能事后分辨）。
"""
from __future__ import annotations

import pathlib
from typing import Any

from agentflow import stopctl
from agentflow.agent_loop import AgentLoop, LoopRun
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

SID = "s4a"


def _env(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run("M", "顶趟")
    return st, cond, ws, top


def _child(cond: Conductor, parent: str, *, role: str, key: str) -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-09T00:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:%s.run_once" % role)


def _loop(ws: pathlib.Path, cond: Conductor, *, task_id: str, role: str = "D") -> AgentLoop:
    loop = AgentLoop(role=role, session_root=ws, registry=None, seam=None, conductor=cond,
                     sid=SID, store=None, max_steps=1, auto_secretary=False)
    loop.my_task_id = task_id
    return loop


# ------------------------------------------------------------------ 作用面

def test_a_subtree_switch_only_stops_that_branch(tmp_path: pathlib.Path):
    """正控①：子树开关 ⇒ 那一支停、别的支不停（"停 D 那一支"不许停到 E）。

    顺序有讲究：先核别的支（那时开关还在盘上），再核那一支的成员（不撤），
    最后核那一支的根（读完就撤）—— 一次性信号在"根"那一步才消失。
    """
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4a@d")
    e = _child(cond, top, role="E", key="s4a@e")
    g = _child(cond, d, role="G", key="s4a@g")          # D 的孙

    stopctl.request_stop(ws, reason="user", by="M", root_task_id=d)
    assert stopctl.stop_scope(stopctl.read_stop(ws))["scope"] == "subtree"

    # 别的支：不停，且有一句读数（"这把开关只管 D 那一支"）
    outside = LoopRun(role="E", task="t")
    assert _loop(ws, cond, task_id=e, role="E")._user_stop_reason(outside) == "", "E 那一支不该停"
    assert outside.notes and "只管" in outside.notes[-1], outside.notes
    assert stopctl.read_stop(ws) is not None

    # 那一支：成员（孙）停，但开关还在（同支别人还要读）
    member = LoopRun(role="G", task="t")
    assert _loop(ws, cond, task_id=g, role="G")._user_stop_reason(member) == "stop_file"
    assert stopctl.read_stop(ws) is not None

    # 那一支的根：停，并且由它撤
    root = LoopRun(role="D", task="t")
    assert _loop(ws, cond, task_id=d)._user_stop_reason(root) == "stop_file"
    assert stopctl.read_stop(ws) is None


def test_the_root_of_the_branch_removes_the_switch_members_do_not(tmp_path: pathlib.Path):
    """正控②：那一支的根撤开关，成员不撤（后面的人还要读到它）。"""
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4a@d")
    g = _child(cond, d, role="G", key="s4a@g")
    stopctl.request_stop(ws, reason="user", by="M", root_task_id=d)

    member = _loop(ws, cond, task_id=g, role="G")
    assert member._user_stop_reason(LoopRun(role="G", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is not None, "成员读到之后开关必须还在（同支别人还要读）"

    root = _loop(ws, cond, task_id=d, role="D")
    assert root._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is None, "那一支的根读完就撤（一次性信号）"

    hist = stopctl.stop_history(ws, limit=10)
    assert [h["removed"] for h in hist] == [False, True], hist
    assert [str(h.get("root_task_id") or "") for h in hist] == [d, d], hist


def test_the_default_switch_still_stops_everyone(tmp_path: pathlib.Path):
    """正控③：缺省开关（没有 `root_task_id`）⇒ 全停 + 读到的人撤（老行为逐字不变）。"""
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4a@d")
    stopctl.request_stop(ws, reason="user", by="user")
    scope = stopctl.stop_scope(stopctl.read_stop(ws))
    assert scope["scope"] == "all" and scope["root_task_id"] == "", scope
    assert _loop(ws, cond, task_id=d)._user_stop_reason(LoopRun(role="D", task="t")) == "stop_file"
    assert stopctl.read_stop(ws) is None, "全工作区那一档仍然是'读到就撤'"


# ------------------------------------------------------------------ 判不了 / 别停错

def test_when_it_cannot_tell_it_does_not_stop(tmp_path: pathlib.Path):
    """负控①：判不了（台账里没有我这一行）⇒ 不停 + 一句读数（判不了 ≠ 适用）。

    "我不在那一支里"是确定的答案（那一条在 `test_a_switch_on_another_branch…` 里核）；
    这一条要的是真的判不了：连我这一行都不在台账里 ⇒ `checked=False`。
    """
    st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4a@d")
    stopctl.request_stop(ws, reason="user", by="M", root_task_id=d)
    loop = _loop(ws, cond, task_id="t-没这一行")
    run = LoopRun(role="M", task="t")
    assert loop._user_stop_reason(run) == "", "判不了就不许停（那会把局部叫停变成全停）"
    assert run.notes and "判不了" in run.notes[-1], run.notes
    assert stopctl.read_stop(ws) is not None, "没停就不许撤掉别人的开关"
    assert st is not None

    got = cond.inside_subtree(d, "t-没这一行")
    assert got["checked"] is False and "判不了" in got["reason"], got
    assert cond.inside_subtree(d, top)["inside"] is False, "别的支是确定的'不在里面'"


def test_a_switch_on_another_branch_does_not_stop_me(tmp_path: pathlib.Path):
    """负控②：别的支里那些循环不许因为"盘上有开关"就停。"""
    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4a@d")
    e = _child(cond, top, role="E", key="s4a@e")
    stopctl.request_stop(ws, reason="user", by="M", root_task_id=d)
    run = LoopRun(role="E", task="t")
    assert _loop(ws, cond, task_id=e, role="E")._user_stop_reason(run) == ""
    assert stopctl.read_stop(ws) is not None
    assert run.notes and "不在那一支里" in run.notes[-1], run.notes


def test_the_tool_can_aim_the_switch_at_a_branch(tmp_path: pathlib.Path):
    """反真空：`conductor.stop(root_task_id=…)` 真的把作用面写进开关（工具面那一格）。"""
    from agentflow.tools import build_registry

    _st, cond, ws, top = _env(tmp_path)
    d = _child(cond, top, role="D", key="s4a@d")
    reg = build_registry(store=cond.store, conductor=cond).registry
    out = reg.call("conductor.stop", role="M", reason="user", notify=False, root_task_id=d)
    assert out.ok is True, out
    state = stopctl.read_stop(ws)
    assert str(state.get("root_task_id") or "") == d, state
    assert stopctl.stop_scope(state)["scope"] == "subtree", state
