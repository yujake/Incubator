# -*- coding: utf-8 -*-
"""WF 判据：C13 多轮唤醒链（正控 / 反真空 / 负控），2026-11-16。

## 它钉的是什么（CC4 缺陷 1 的修复判据）

| 编号 | 它要证明的事 | 它能怎么红 |
|---|---|---|
| c13-a | 研究跑（`start --mode research` ⇒ `host.wired_llm_conductor`）里，M 批准之后
`wake_blocked` 真的把 owner 按同一个号跑起来：`started=True`、无 `wake_failed`、
板项从 `block` 推进（queued → seen）、`wake:` 落痕只有一条、owner 行 `done/ok`、
被唤醒的 D 有 `agent_run_start` / `agent_run_end` | 接线被摘掉（c13-b）或执行侧接上但
`LlmBackend.call` 少传 `token`（owner 行 `failed`）⇒ 本条的 problems 非空 |
| c13-b | 反真空：把 `host.wired_llm_conductor` 那一格接线换成"访问即 AttributeError"
（模拟那一行被注释掉）⇒ c13-a 必须绿转红，并且读数精确回到
`started=False` + `refusal_code=wake_failed` + 「没有接执行侧」 | 如果 c13-a 在没接线时
仍然绿 ⇒ 它量的不是接线，是别的东西 |
| c13-c | 负控：同一趟里不带 `approve="yes"` 的那一次逐条 `skip/not_approved`、
`started=False`、`mark=""`、`state=refused`、`count=0`；盘上唯一一条 `wake:` 落痕
来自批准那一趟（未批准那一趟一个字节都没写） | 把"未批准"折成"照样写" ⇒ 红 |

## 与 CC4 旧彩排的关系

执行体、夹具与出网替身全部复用 `tests/test_rehearsal_c13_wake.py` 的 `_run`
（CLI 真入口、真 `autonomy` 两轮、真 `stopctl.block_remaining_tasks`、只换
`modelgw.urllib_transport`）。本文件只加"缺陷 1 的接线判据"与两条控制，不重写彩排。

## 反真空怎么造（不往产品里加开关）

`monkeypatch.setattr(Conductor, "resume_dispatched", _NoResumeDispatched())`：
这个 descriptor 的 `__get__` 抛 `AttributeError` ⇒ `host` 里那句
`hasattr(cond, "resume_dispatched")` 为假、接线被跳过 —— 正是"那一行被注释掉"的
效果，产品代码里不需要开关变量。摘掉之后 `resume_runner` 仍是 `None`，
`wake_blocked` 走它自己的受控拒绝支（`wake_failed`）。
"""
from __future__ import annotations

import pathlib

import pytest

from test_rehearsal_c13_wake import (
    _cell,
    _chain_problems,
    _chain_reading,
    _run,
    _wakes,
)

from agentflow.conductor import Conductor


class _NoResumeDispatched:
    """访问即 AttributeError：模拟 `host` 里那一行 `resume_runner` 接线被注释掉。"""

    def __get__(self, obj: object, objtype: object = None) -> object:
        raise AttributeError("resume_dispatched 未接线（反真空：模拟 host 那一行被摘掉）")


def _wake_cell(reading: dict, index: int, item_id: str) -> dict:
    return _cell(reading["wakes"][index], item_id)


def _marks(reading: dict) -> list[str]:
    return [str(x) for x in (dict(reading["item"]).get("inputs") or [])
            if str(x).startswith("wake:")]


def _owner_runs(reading: dict, kind: str) -> list[dict]:
    owner_id = str(dict(reading["owner"]).get("task_id") or "")
    key = "runs" if kind == "start" else "ends"
    return [e for e in reading[key]
            if str(e.get("task_id") or "") == owner_id
            and str(e.get("role") or "") == "D"]


def _wake_problems(reading: dict, item_id: str) -> list[str]:
    """c13-a 的判据集合（空 = 通）；c13-b 用它证明"摘掉接线必须红"。"""
    problems: list[str] = []
    wakes = reading["wakes"]
    if len(wakes) != 3:
        return [f"M 应恰好调三次 conductor.wake_blocked，实得 {len(wakes)}"]
    second = dict(wakes[1]["data"])
    cell = _wake_cell(reading, 1, item_id)
    if str(cell.get("verdict") or "") != "resume":
        problems.append(f"批准那一趟的审计该判 resume：{cell!r}")
    if cell.get("started") is not True:
        problems.append(f"批准那一趟必须真的叫起来（started 该是 True）：{cell!r}")
    if str(cell.get("refusal_code") or ""):
        problems.append(f"叫起来了就不该有 refusal_code：{cell.get('refusal_code')!r}")
    if str(second.get("state") or "") != "woken":
        problems.append(f"叫起来了就该 state=woken：{second.get('state')!r}")
    if int(second.get("count") or 0) != 1:
        problems.append(f"叫起来了 count 该是 1：{second.get('count')!r}")
    item = dict(reading["item"])
    if str(item.get("item_state") or "") == "block":
        problems.append("板项还在 block：直写那一半没发生")
    if str(item.get("item_state") or "") not in ("queued", "seen", "done"):
        problems.append(f"板项该从 block 推进（queued/seen/done）："
                        f"{item.get('item_state')!r}")
    marks = _marks(reading)
    if len(marks) != 1:
        problems.append(f"wake: 落痕应恰好一条（幂等不翻倍）：{marks}")
    if str(dict(reading["owner"]).get("status") or "") != "done":
        problems.append(f"owner 行没有落终态 done："
                        f"{dict(reading['owner']).get('status')!r}")
    if str(dict(reading["owner"]).get("outcome") or "") != "ok":
        problems.append(f"owner 行的结局不是 ok："
                        f"{dict(reading['owner']).get('outcome')!r}")
    if not _owner_runs(reading, "start"):
        problems.append("被唤醒的 D 没有起跑（没有它的 agent_run_start）")
    if not _owner_runs(reading, "end"):
        problems.append("被唤醒的 D 没有 agent_run_end")
    return problems


# ============================================================ c13-a 正控


def test_c13_a_the_approved_wake_really_runs_the_owner(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：研究跑的 CLI 两轮彩排，第 2 轮批准 ⇒ 执行侧真的按同号跑起来。"""
    got = _run(tmp_path, monkeypatch)
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    problems = _wake_problems(reading, got["item"])
    print(f"[c13-a] wakes={len(reading['wakes'])} "
          f"wake2={_wake_cell(reading, 1, got['item'])} "
          f"item={dict(reading['item']).get('item_state')} "
          f"owner={dict(reading['owner']).get('status')}/"
          f"{dict(reading['owner']).get('outcome')} "
          f"marks={_marks(reading)}")
    assert problems == [], problems
    # 整条彩排的其他格（钱账 / 会话归口 / 多轮）仍由 CC4 的判据链钉着。
    assert _chain_problems(reading, got["item"]) == [], _chain_problems(reading, got["item"])


# ============================================================ c13-b 反真空


def test_c13_b_without_the_wiring_the_positive_control_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：摘掉 `resume_runner` 接线 ⇒ c13-a 的判据必须绿转红（精确回到 wake_failed）。"""
    monkeypatch.setattr(Conductor, "resume_dispatched", _NoResumeDispatched())
    got = _run(tmp_path, monkeypatch)
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    cell = _wake_cell(reading, 1, got["item"])
    data = dict(reading["wakes"][1]["data"]) if len(reading["wakes"]) > 1 else {}
    print(f"[c13-b] wake2={cell} state={data.get('state')!r} "
          f"count={data.get('count')!r} "
          f"item={dict(reading['item']).get('item_state')} "
          f"owner={dict(reading['owner']).get('status')} "
          f"marks={_marks(reading)}")
    # 1. 受控读数逐字回到"没接执行侧"那一档。
    assert cell.get("started") is False, cell
    assert str(cell.get("refusal_code") or "") == "wake_failed", cell
    assert "没有接执行侧" in str(cell.get("why") or ""), cell
    assert str(data.get("state") or "") == "refused", data
    assert int(data.get("count") or 0) == 0, data
    # 2. 写侧照旧（板项 block→queued、wake: 一条），但 owner 没被叫起来。
    assert str(dict(reading["item"]).get("item_state") or "") == "queued", reading["item"]
    assert str(dict(reading["owner"]).get("status") or "") == "block", reading["owner"]
    assert _owner_runs(reading, "start") == [], _owner_runs(reading, "start")
    assert len(_marks(reading)) == 1, _marks(reading)
    # 3. 最要紧的一格：c13-a 的判据在这里必须非空（否则正控是真空的）。
    problems = _wake_problems(reading, got["item"])
    print(f"[c13-b] c13-a problems={problems}")
    assert problems, "摘掉接线之后 c13-a 的判据仍然是绿的 ⇒ 正控没有量到接线"
    assert any("started" in one or "agent_run_start" in one for one in problems), problems


# ============================================================ c13-c 负控


def test_c13_c_the_unapproved_pass_writes_nothing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：不批准的那一趟逐条 not_approved、零写入；唯一的 wake: 来自批准那一趟。"""
    got = _run(tmp_path, monkeypatch)
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    first = _wake_cell(reading, 0, got["item"])
    first_data = dict(reading["wakes"][0]["data"])
    approved = _wake_cell(reading, 1, got["item"])
    marks = _marks(reading)
    print(f"[c13-c] first={first} state={first_data.get('state')!r} "
          f"count={first_data.get('count')!r} marks={marks}")
    assert str(first.get("verdict") or "") == "skip", first
    assert str(first.get("refusal_code") or "") == "not_approved", first
    assert first.get("started") is False, first
    assert str(first.get("mark") or "") == "", first
    assert str(first_data.get("state") or "") == "refused", first_data
    assert int(first_data.get("count") or 0) == 0, first_data
    # 盘上唯一一条 wake: 落痕就是批准那一趟写的（未批准那一趟零写入）。
    assert len(marks) == 1, marks
    assert str(approved.get("mark") or "") == marks[0], (approved.get("mark"), marks)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
