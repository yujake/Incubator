# -*- coding: utf-8 -*-
"""判据：可抢占派活的"还在跑"那一支，名册读数不许丢（`draft/160` 丙案第 3 点）。

## 真缺陷，不是读数口味

登记发生在 `Conductor.summon_begin` 的 [5b]（子代理跑起来之前），所以"登记成没成"在
派活那一刻就已有值。但 `agent_loop._do_summon` 在句柄没落定时提前 `return out`
（改前在 `agent_loop.py:10448-10460`），而名册两格只在"孩子落定之后"那一条路上才
交回 ⇒ 可抢占派活（真机上的绝大多数）把 `roster_problem` 丢了。

81 趟的盘上读数：2419 个 `agent_step` 里只有 9 个带任何 `roster_*` 键；派出
`t-000106` 的那一步（F 的第 19 步）键集是
`['action','detail','dispatched','ok','outcome','preemptible','refusal_reason',
'running','status','summoned','task_id','秘书']` —— 一个 `roster_*` 都没有。
于是收工门的 `roster_registration`（数 `roster_problem` 条数）看不见那次
`name_taken`，只报了另一个缺陷的 1 处。

## 这一组守什么

1. 正题：可抢占派活被写口拒（`name_taken`）⇒ 那一步的返回值必须带 `roster_problem`；
2. 正题：可抢占派活登记成功 ⇒ 必须带 `roster_name`（不是只有失败那一支才带）；
3. 负控：把 `SummonHandle.roster_reading` 打桩成空 ⇒ 上面两条必红（证明判据量的是
   新加的那一段，不是别处顺手给的）；
4. 三态：`roster_considered` 一起交回（"走过了、结论是不登记"与"根本没走过"要分得开）。
"""
from __future__ import annotations

import pathlib
import threading
from typing import Any

import pytest

from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, SummonHandle
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "s-preemptible-roster"
BR = "2026-11-01T03:00:00+08:00"


class _BlockingBackend:
    """一个"进来就卡住"的后端：把句柄钉在 `running`（`done()` 为假）上。"""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.store: Any = None

    def call(self, role, action, params, *, token, instance="", task_id=""):
        self.entered.set()
        self.release.wait(timeout=10.0)
        return {"outcome": "ok", "detail": "判据夹具：跑完了", "checked": True}


class _Gate:
    """seam 的替身（这一组判据不碰模型）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": "{}", "tool_calls": (),
                                  "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


def _env(tmp_path: pathlib.Path) -> tuple[AgentLoop, Conductor, str, _BlockingBackend]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    backend = _BlockingBackend()
    cond = Conductor(st, policy=None, backend=backend)
    reg = build_registry(store=st, conductor=cond).registry
    top = str(cond.open_top_level_run("M", "可抢占派活的顶趟"))
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2, child_step_wait_sec=0.0)
    loop.my_task_id = top
    assert loop.secretary is not None, "这一组要的是『名册在手上』那一档"
    return loop, cond, top, backend


def _seed_row(cond: Conductor, parent: str, *, key: str) -> str:
    """在台账里先放一行（只为了给"被占的名字"一个号）。"""
    return str(cond._write_new_row({
        "task_id": "", "role": "E", "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key,
        "status": "done", "outcome": "ok", "refusal_reason": None,
        "instance": "", "detail": "判据夹具：占名的那一行", "error": None,
        "started_at": BR, "ended_at": BR, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note=f"judge:seed:{key}"))


def _summon(loop: AgentLoop, name: str, task: str) -> dict[str, Any]:
    return loop._do_summon({"role": "E", "task": task, "brief": "判据：一件活",
                            "name": name})


def _finish(loop: AgentLoop, backend: _BlockingBackend) -> None:
    """放掉阻塞的后端并等它落定（判据之后收尾，别把在场线程留给下一个用例）。"""
    backend.release.set()
    loop._wait_for_children(timeout=10.0)


def test_a_refused_name_still_reports_on_the_preemptible_path(
        tmp_path: pathlib.Path) -> None:
    """正题：可抢占派活被写口拒（`name_taken`）⇒ 那一步必须带 `roster_problem`。"""
    loop, cond, top, backend = _env(tmp_path)
    taken = _seed_row(cond, top, key="taken")
    made = loop.secretary.roster_add(owner=top, role="E", task_id=taken,
                                     brief="占掉 E1", task="占名")
    assert made.get("problem") == "" and made.get("name") == "E1", made

    out = _summon(loop, "E1", "点名撞车的这一件")
    assert out.get("ok") is True, out
    assert out.get("status") == "running", ("这一支必须是『还在跑』那一档", out)
    assert str(out.get("roster_problem") or ""), (
        "可抢占派活把名册读数丢了（81 的 t-000106 就是这么消失的）", out)
    assert "name_taken" in str(out["roster_problem"]), out
    assert out.get("roster_considered") is True, out
    # 与 `_roster_reading` 同一口径：有 problem 时不许再交一个 `roster_name`
    # （回执里的 name 是"它点名要的那个"，写出来会被 `roster_registration.registered`
    # 数成一次登记成功 —— 本批的合成会话读数抓到的就是这一档）。
    assert not str(out.get("roster_name") or ""), out
    _finish(loop, backend)


def test_a_successful_preemptible_registration_reports_the_name(
        tmp_path: pathlib.Path) -> None:
    """正题：可抢占派活登记成功 ⇒ 必须带 `roster_name`（不是只有失败那支才带）。"""
    loop, _cond, _top, backend = _env(tmp_path)
    out = _summon(loop, "E1", "正常的一件")
    assert out.get("status") == "running", out
    assert str(out.get("roster_name") or "") == "E1", out
    assert not str(out.get("roster_problem") or ""), out
    _finish(loop, backend)


def test_negctl_an_emptied_handle_reading_makes_it_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：把句柄的名册读数打桩成空 ⇒ 上面两条必红（判据量的是新加那一段）。"""
    loop, cond, top, backend = _env(tmp_path)
    taken = _seed_row(cond, top, key="taken")
    loop.secretary.roster_add(owner=top, role="E", task_id=taken,
                              brief="占掉 E1", task="占名")
    monkeypatch.setattr(SummonHandle, "roster_reading",
                        lambda self: {"roster_name": "", "roster_problem": "",
                                      "roster_state": "", "roster_note": "",
                                      "roster_considered": False})
    out = _summon(loop, "E1", "点名撞车的这一件")
    assert out.get("status") == "running", out
    assert not str(out.get("roster_problem") or ""), (
        "打桩之后仍然读到了 problem ⇒ 判据没量在新加的那一段上", out)
    _finish(loop, backend)
