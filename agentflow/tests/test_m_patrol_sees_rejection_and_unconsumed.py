# -*- coding: utf-8 -*-
"""MPATROL1：M 的巡查读数补两格 —— ①「最近一次被拒」②「已落定但没被消费的子产出」。

## 现场（`agentflow/temp/inv7/INV7-REPORT.md` §5.4 / `projects/lp-ball-7` 09:59:41）

- `doing` 那格只有 task/action/step/step_at/stalled_sec/source ⇒ F（t-000033）在 step 4/5/6
  连着被拒（`dependency_row_unverified` / 参数错 / 缺 `cites`），而 09:59:41 的 patrol 只看到
  「待机、step=7、stalled_sec=105」—— M 看不到它卡在哪、为什么卡。
- item 的键集只有 doing/board/timers/last_guidance/notes ⇒ 「子代理已落定、产出没被消费」
  在巡查里没有格；挂机判据读的却是 `mailbox["children"]["settled"]`（`agent_loop.py:7313`）
  ⇒ 两处不同源。09:59:41 的现场：D 名下 B1（t-000021）09:48:17 就落定了，D 到那一刻
  还没在任何一步里指到它落的那行（B1 的 `stmt:000012` 是 10:00:31 才被 `table.get` 读到）。

## 判据（a–e）

a. 连续被拒三次 ⇒ `doing.last_rejection` 有最近一次的 `{at, step, tool, kind, why}` 且
   `streak=3`；同一件事在巡查句（`anomalies`）里也念出来。改前必红：这一格不存在
   （`doing` 的键集里没有 `last_rejection`）。
b. 负控：没有失败/受控拒 ⇒ 该格存在、`found=False`/`streak=0`，且不产生"连着被拒"的巡查句。
c. 子代理已落定、父代理后续步骤没指到它的产出 ⇒ `unconsumed` 逐条列出（task_id / role /
   产出路径 / 落定时刻 / 等了多久），巡查句也点名。改前必红：没有 `unconsumed` 这一格。
d. 负控：父代理后来指到了那条产出（`{"table": "statements", "id": "…"}` 点名同一行）⇒
   该格清空。
e. 反真空：把 ①/② 的接线各打桩成空（`_task_step_events` / `_settled_events`）⇒ a / c 的
   断言当场 AssertionError；恢复 ⇒ 绿。它同时证明两格读的就是那两条线，不是另写一份。

边界：全部 tmp 工作区、假时钟，零真实模型调用、不碰 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import clock as CLK
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT

SID = "probe-mpatrol1"
TS = "2026-11-18T09:00:00+08:00"
#: 三次被拒的时刻（与现场逐秒对齐：09:57:20 / 09:57:37 / 09:57:56）。
T4 = "2026-11-18T09:57:20+08:00"
T5 = "2026-11-18T09:57:37+08:00"
T6 = "2026-11-18T09:57:56+08:00"
#: 子代理 B1 的落定时刻（现场 09:48:14；09:59:41 那一拍它已经等了 687 秒）。
B_AT = "2026-11-18T09:48:14+08:00"
NOW = "2026-11-18T09:59:41+08:00"
WAIT_SEC = 687.0
B_OUT = "out/tasks/t-000021.json"


# ---------------------------------------------------------------- 夹具


def _ws(root: pathlib.Path) -> tuple[pathlib.Path, Store, Conductor, Any, str]:
    ws = root / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    top = cond.open_top_level_run("M", "MPATROL1 夹具的顶趟")
    return ws, st, cond, reg, top


def _child(cond: Conductor, parent: str, role: str, *, status: str = "running",
           detail: str = "", ended_at: str | None = None,
           artifacts: list[str] | None = None) -> str:
    """建一条子代理实例行（与 `summon` 建的那种同形；实例行的唯一建行点）。"""
    prow = cond._task(parent) or {}
    terminal = status in ("done", "cancelled", "failed")
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": f"mpatrol1:{role}:{detail[:16]}", "status": status,
        "outcome": "ok" if terminal else None, "refusal_reason": None,
        "instance": "", "detail": detail or f"{role} 这一趟的活", "error": None,
        "started_at": TS, "ended_at": ended_at,
        "tokens": 0, "usd": 0.0, "artifacts": list(artifacts or []), "inputs": [],
    }, note="start:mpatrol1")


def _sessions(ws: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path = ws / "sessions" / "2026-11-18.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8", newline="\n")


def _rejected_step(task_id: str, role: str, index: int, at: str,
                   *, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "agent_step", "role": role, "task_id": task_id, "index": index,
            "shape": "tool", "payload": dict(payload), "result": dict(result), "ts": at}


def _env(root: pathlib.Path, *, consumed: bool = False) -> dict[str, Any]:
    """一棵最小树：M 顶趟 → D（在飞）与 F（在飞）；D 名下 B1 已落定。

    - F 的 step 4/5/6 是现场那三次拒（两种写在 `data` 里、一种写在 `error`/`meta` 里）；
    - D 的 `agent_children` 在 `B_AT` 落了 B1；
    - `consumed=True` 时追加 D 的一步 `table.get(statements, 000012)`（= 消费了 B1 的产出）。
    """
    ws, st, cond, reg, top = _ws(root)
    d = _child(cond, top, "D", detail="查 3 维 l_p 球的最大中心截面（凸情形）")
    f = _child(cond, top, "F", detail="攻中心化引理：Brunn 凹性 ⇒ 最大面积截面可中心取到")
    b = _child(cond, d, "B", status="done", ended_at=B_AT,
               detail="从 König 2024 抽 Meyer–Pajor 单调性的逐字引文并落行",
               artifacts=[B_OUT])
    rows: list[dict[str, Any]] = [
        {"kind": "agent_run_start", "role": "F", "task_id": f, "ts": TS},
        # step 4：工具把拒因写在 data 里（ok 仍是 True）。
        _rejected_step(f, "F", 4, T4, payload={"name": "attack.step"},
                       result={"ok": True, "error": "", "meta": {}, "data": {
                           "deps_refused": "dependency_row_unverified",
                           "reason": "打回重写：依赖面这一遍核不过（dependency_row_unverified）"}}),
        # step 5：工具层失败（`meta.kind` 是框架的拒因键）。
        _rejected_step(f, "F", 5, T5, payload={"name": "attack.step"},
                       result={"ok": False, "meta": {"kind": "param_error"},
                               "error": "参数错误：出现未声明的参数：['self_assessment']",
                               "data": {}}),
        # step 6：工具把拒因写在正文里（「拒收」三处逐字之一）。
        _rejected_step(f, "F", 6, T6, payload={"name": "attack.step"},
                       result={"ok": True, "error": "", "meta": {}, "data": {
                           "reason": "子目标 s1 的这一轮**拒收**：steps[3..6] 既没有给 `cites`，"
                                     "也没有声明成前提（`assumption: true`）"}}),
        # D 的落定事件：`mailbox["children"]["settled"]` 的盘上落点。
        {"kind": "agent_children", "role": "D", "task_id": d, "ts": B_AT, "step": 12,
         "settled": [b], "settled_outcomes": ["ok"], "running": []},
        # B1 自己收工时报过的证据 id。
        {"kind": "agent_run_end", "role": "B", "task_id": b, "ts": B_AT,
         "evidence": ["stmt:000012"], "final": "落了 stmt:000012"},
    ]
    if consumed:
        rows.append(_rejected_step(
            d, "D", 13, "2026-11-18T10:00:31+08:00",
            payload={"name": "table.get", "args": {"id": "000012", "table": "statements"}},
            result={"ok": True, "error": "", "meta": {}, "data": {}}))
    _sessions(ws, rows)
    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "top": top,
            "d": d, "f": f, "b": b}


def _patrol(env: dict[str, Any]) -> dict[str, Any]:
    with calling_as(env["top"], "M", session_root=str(env["ws"]), sid=SID):
        res = env["reg"].call("conductor.patrol", role="M")
    assert res.ok, res.to_dict()
    return dict(res.data)


def _by_code(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("code") or ""): item for item in data.get("items") or ()}


@pytest.fixture()
def bench():
    """假时钟：等待时长可逐秒断言（`waited_sec` 不是"大于 0"）。"""
    CLK.reset()
    fake = CLK.use(CLK.FakeClock(wall=NOW, monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()


# ---------------------------------------------------------------- a) 连续被拒三次


def _assert_a(env: dict[str, Any], data: dict[str, Any] | None = None) -> None:
    data = data if data is not None else _patrol(env)
    item = _by_code(data)[env["f"]]
    rejection = dict((item.get("doing") or {}).get("last_rejection") or {})
    assert rejection, "doing 里没有 last_rejection 这一格（改前就是这样）：" + repr(item)
    assert rejection.get("checked") is True, rejection
    assert rejection.get("found") is True, rejection
    assert int(rejection.get("streak") or 0) == 3, rejection
    assert int(rejection.get("step") or -1) == 6, rejection
    assert str(rejection.get("at") or "") == T6, rejection
    assert str(rejection.get("tool") or "") == "attack.step", rejection
    assert str(rejection.get("kind") or "") == "handed_product_refused", rejection
    assert "拒收" in str(rejection.get("why") or ""), rejection
    lines = [str(x) for x in (data.get("anomalies") or ()) if env["f"] in str(x)]
    line = next((x for x in lines if "连着被拒 3 次" in x), "")
    assert line, lines
    assert "handed_product_refused" in line, line


def test_a_three_consecutive_rejections_are_visible(tmp_path: pathlib.Path, bench) -> None:
    env = _env(tmp_path)
    _assert_a(env)


# ---------------------------------------------------------------- b) 负控：没有拒绝


def test_b_no_rejection_is_an_empty_cell(tmp_path: pathlib.Path, bench) -> None:
    """b：没有失败/受控拒 ⇒ 格子存在、`found=False`/`streak=0`，且不出"连着被拒"的句子。"""
    env = _env(tmp_path)
    data = _patrol(env)
    rejection = dict((_by_code(data)[env["d"]].get("doing") or {}).get("last_rejection") or {})
    assert rejection.get("checked") is True, rejection
    assert rejection.get("found") is False, rejection
    assert int(rejection.get("streak") or 0) == 0, rejection
    assert int(rejection.get("count") or 0) == 0, rejection
    assert not [x for x in (data.get("anomalies") or ())
                if env["d"] in str(x) and "连着被拒" in str(x)], data["anomalies"]


# ---------------------------------------------------------------- c) 落定未消费


def _assert_c(env: dict[str, Any], data: dict[str, Any] | None = None) -> None:
    data = data if data is not None else _patrol(env)
    cell = dict(_by_code(data)[env["d"]].get("unconsumed") or {})
    assert cell, "patrol 的 item 里没有 unconsumed 这一格（改前就是这样）"
    assert cell.get("checked") is True, cell
    assert int(cell.get("count") or 0) == 1, cell
    row = dict((cell.get("items") or [])[0])
    assert str(row.get("task_id") or "") == env["b"], row
    assert str(row.get("role") or "") == "B", row
    assert str(row.get("output") or "") == B_OUT, row
    assert str(row.get("settled_at") or "") == B_AT, row
    assert float(row.get("waited_sec") or -1) == WAIT_SEC, row
    lines = [str(x) for x in (data.get("anomalies") or ()) if env["b"] in str(x)]
    line = next((x for x in lines if "还没在后续步骤里指到它" in x), "")
    assert line, lines
    assert B_OUT in line and "687.0s" in line, line


def test_c_a_settled_child_output_is_listed_until_consumed(
        tmp_path: pathlib.Path, bench) -> None:
    env = _env(tmp_path)
    _assert_c(env)


# ---------------------------------------------------------------- d) 负控：消费之后清空


def test_d_consuming_the_output_clears_the_cell(tmp_path: pathlib.Path, bench) -> None:
    """d：父代理后来按 `table` + `id` 点名了那条台账行 ⇒ 同一格清空（负控）。"""
    env = _env(tmp_path, consumed=True)
    data = _patrol(env)
    cell = dict(_by_code(data)[env["d"]].get("unconsumed") or {})
    assert cell.get("checked") is True, cell
    assert int(cell.get("count") or 0) == 0, cell
    assert cell.get("items") == [], cell
    assert not [x for x in (data.get("anomalies") or ()) if env["b"] in str(x)], data["anomalies"]
    # 同一份夹具里 F 的拒读一格不受影响（两格各读各的线，不互相顶替）。
    assert int(_by_code(data)[env["f"]]["doing"]["last_rejection"]["streak"]) == 3


# ---------------------------------------------------------------- e) 反真空：打桩接线


def test_e_stubbing_the_wiring_makes_a_and_c_red(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把 ①/② 的接线各打桩成空 ⇒ a / c 的断言当场红；恢复 ⇒ 绿。"""
    env = _env(tmp_path)
    real_steps = CT._task_step_events
    real_settled = CT._settled_events

    # ① 接线：假装"这一趟一步都没走过" ⇒ a 必红。
    monkeypatch.setattr(CT, "_task_step_events", lambda *a, **k: {
        "checked": True, "found": False, "count": 0, "events": [], "reason": ""})
    with pytest.raises(AssertionError):
        _assert_a(env)
    monkeypatch.setattr(CT, "_task_step_events", real_steps)
    _assert_a(env)

    # ② 接线：假装"这一支从来没有子代理落定" ⇒ c 必红。
    monkeypatch.setattr(CT, "_settled_events", lambda *a, **k: [])
    with pytest.raises(AssertionError):
        _assert_c(env)
    monkeypatch.setattr(CT, "_settled_events", real_settled)
    _assert_c(env)


# ---------------------------------------------------------------- 三态：读不成不等于没有


def test_unreadable_sessions_is_checked_false_not_empty(
        tmp_path: pathlib.Path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """读不成（会话目录读不出来）⇒ 两格 `checked=False` + 原因，不折成"没有拒绝 / 没有未消费"。"""
    env = _env(tmp_path)

    def broken(_cond: Any):
        return [], False, "判据：会话记录读不成"

    monkeypatch.setattr(CT, "_session_patrol_reading", broken)
    data = _patrol(env)
    rejection = dict(_by_code(data)[env["f"]]["doing"]["last_rejection"])
    cell = dict(_by_code(data)[env["d"]]["unconsumed"])
    assert rejection.get("checked") is False and rejection.get("streak") == 0, rejection
    assert cell.get("checked") is False and cell.get("count") == 0, cell
    assert "读不成" in str(rejection.get("reason") or ""), rejection
    assert "读不成" in str(cell.get("reason") or ""), cell
