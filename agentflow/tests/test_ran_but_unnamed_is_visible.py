# -*- coding: utf-8 -*-
"""判据：真跑过却名册上没有的子代理，收工读数必须点名（`draft/160` 三-3 的丙案）。

## 为什么要有这一格（81 趟的事实，逐条有盘上读数）

`t-000106`（父 `t-000016`、role E、03:08:42→03:16:18、`done/ok`、`out/tasks/t-000106.json`
在盘上）是一次真跑的召唤：父点名 `E2`，而 `E2` 已被 `t-000030` 占着（派活闸
`concurrency_exceeded` 拒掉、从没跑过，后来被兜底自愈补成名册项）⇒ 名册写口
`name_taken` 受控拒绝，派活照跑、子代理跑完，然后两条补名路都关着 ⇒ 它永久没有名字。
收工门只报「名册有 1 处没登记」，而那 1 处是另一个缺陷（`t-000007` 三份没写全），
跟它毫无关系 —— 它连那 1 都不进，因为可抢占派活在句柄没落定时提前返回，把
`roster_problem` 丢了（`agent_loop._do_summon` 早返支；81 的 2419 个 `agent_step`
只有 9 个带任何 `roster_*` 键）。

所以这一格不读会话、读盘：台账（谁真跑过）join 名册历史（谁有名字）join 拒绝流水
（它点的名字现在在谁手里）。四个条件全在 `secretary.ran_but_unnamed`，取数在
`Secretary.unnamed_children`，收工门那一格只转发。

## 这一组守什么（业主 2026-11-01 给的验收，逐条对应）

| 判据 | 它钉的是 | 反真空 / 负控 |
|---|---|---|
| ① `test_a_child_that_really_ran_but_has_no_name_is_named` | 真跑无名的号被列出，逐格正确（含"名字现在挂在谁身上"） | 负控：把四条件判据打桩成恒假 ⇒ ① 必红 |
| ② `test_a_gate_refused_number_is_not_counted_as_ran_but_unnamed` | 被派活闸拒掉的号不出现（"没跑过"与"跑过没名"的分界，也是本格不重开 d9ebb7fe/1cdacbf6 的证明） | 正控：同一夹具里的真子必须出现 |
| ③ `test_an_in_flight_child_is_not_counted` | 在飞的（`running`、无 `ended_at`）不出现（159 的洞） | 正控：它落定之后必须出现 |
| ④ `test_a_full_roster_makes_the_cell_empty_not_missing` | 名册齐全 ⇒ `count == 0` 且 `checked is True` | 反真空：同一个夹具里不登记那一条 ⇒ 必须非 0 |
| ⑤ `test_the_closing_summary_says_it_and_the_gate_does_not_get_stronger` | 收工那一行有半句，且不进 `status` / 不产生 `Finding` | 负控：把那一格删掉 ⇒ ⑤ 必红 |
| ⑥ `test_a_missing_artifact_is_named` | 产物不在盘上时逐条点名（"在不在"是这一格的一部分） | — |
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import closing as CL
from agentflow import secretary as SEC
from agentflow import sessions as SS
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

SID = "20261101"
BR = "2026-11-01T03:00:00+08:00"


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str, pathlib.Path, Store]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.secretary = Secretary("M", root=ws, store=st, enable_model=False)
    cond.roster_sink = cond.secretary
    top = str(cond.open_top_level_run("M", "160 丙案的顶趟"))
    return cond, top, ws, st


def _row(cond: Conductor, parent: str, role: str, *, key: str,
         status: str = "done", outcome: str | None = "ok", ended: bool = True,
         artifacts: tuple[str, ...] = (), kind: str = "") -> str:
    """台账里造一行（编号由台账分配；`ended=False` 就是在飞那一档）。

    `kind` 非空那一档是板项行（`message` / `notice` / …）：`schema.Task.validate` 要求
    它的 `expects` / `item_state` 也是受控词表里的值（空串是非法行）。
    """
    terminal = status not in ("pending", "running")
    item = bool(kind)
    return str(cond._write_new_row({
        "task_id": "", "role": role, "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": outcome if terminal else None,
        "refusal_reason": "concurrency_exceeded" if outcome == "refused" else None,
        "instance": "", "detail": "判据夹具：一行", "error": None,
        "started_at": BR, "ended_at": BR if ended else None,
        "tokens": 0, "usd": 0.0, "artifacts": list(artifacts), "inputs": [],
        "kind": kind, "expects": "ack" if item else "",
        "item_state": "queued" if item else "", "item_close": "",
    }, note=f"judge:{key}"))


def _register(cond: Conductor, owner: str, task_id: str, name: str,
              role: str = "E") -> None:
    got = cond.secretary.roster_add(owner=owner, role=role, task_id=task_id,
                                    brief=f"名册项 {name}", task="做研究", want_name=name)
    assert got.get("problem") == "", got
    assert str(got.get("name")) == name, got


def _refuse_name(cond: Conductor, owner: str, task_id: str, name: str) -> None:
    """把"这一号点名要 `name` 被写口拒了"落成流水（写侧唯一的落法）。"""
    ok, why = cond.secretary.roster_refusal_note(
        owner=owner, task_id=task_id, name=name, refusal_code="name_taken",
        problem=f"{name} 已经用过 ⇒ 受控拒绝（name_taken）")
    assert ok, why


def _ids(got: dict[str, Any]) -> list[str]:
    return [str(r.get("task_id") or "") for r in (got.get("rows") or [])]


def _one(got: dict[str, Any], task_id: str) -> dict[str, Any]:
    row = next((r for r in (got.get("rows") or [])
                if str(r.get("task_id") or "") == task_id), None)
    assert row is not None, (task_id, got)
    return row


def _built(tmp_path: pathlib.Path) -> tuple[Conductor, str, pathlib.Path, dict[str, str]]:
    """把 81 那三档都摆出来：真子无名 / 闸拒的号 / 在飞的号 / 板项行。

    顺序照 81 的时序：名册先有 E1 → 闸拒的号占掉 E2 并被销号 → 真子点名 E2 被拒、
    照跑、名册里没有它 → 另有一个在飞的、一个板项行。
    """
    cond, top, ws, _st = _env(tmp_path)
    first = _row(cond, top, "E", key="judge:first")
    _register(cond, top, first, "E1")
    phantom = _row(cond, top, "E", key="judge:phantom", outcome="refused")
    _register(cond, top, phantom, "E2")
    dead = cond.secretary.retire(owner=top, name="E2", reason="判据：销掉被闸拒的那个号")
    assert dead.get("ok") is True, dead
    real = _row(cond, top, "E", key="judge:real")
    _refuse_name(cond, top, real, "E2")
    flying = _row(cond, top, "E", key="judge:flying", status="running", ended=False)
    board = _row(cond, top, "E", key="judge:board", kind="message")
    return cond, top, ws, {"first": first, "phantom": phantom, "real": real,
                           "flying": flying, "board": board}


# ====================================================================== 判据①
def _a_really_ran_but_unnamed_is_named(cond: Conductor, top: str,
                                       ids: dict[str, str]) -> dict[str, Any]:
    """判据①的内容（正控；负控复用同一份断言）。"""
    got = cond.secretary.unnamed_children()
    assert got.get("checked") is True, got
    assert got.get("count") == 1, ("真跑无名的那一个必须被点名", got)
    row = _one(got, ids["real"])
    assert row["role"] == "E" and row["parent_task_id"] == top, row
    assert row["status"] == "done" and row["outcome"] == "ok", row
    assert row["started_at"] == BR and row["ended_at"] == BR, row
    assert row["artifacts"] == [] and row["artifacts_missing"] == [], row
    # 它当初点了什么名、被哪一档拒
    assert row["requested_name"] == "E2" and row["refusal_code"] == "name_taken", row
    # 那个名字现在挂在谁身上：被闸拒、从没跑过、已销号 —— 81 的同一形态
    held = row.get("held_by") or {}
    assert held.get("name") == "E2" and held.get("task_id") == ids["phantom"], row
    assert held.get("retired") is True and held.get("task_outcome") == "refused", row
    return got


def test_a_child_that_really_ran_but_has_no_name_is_named(tmp_path: pathlib.Path) -> None:
    """判据①：真跑无名的那一个被点名，逐格正确（含 `held_by` 指向占名的 phantom）。"""
    cond, top, _ws, ids = _built(tmp_path)
    _a_really_ran_but_unnamed_is_named(cond, top, ids)


def test_negctl_stubbing_the_judge_makes_it_red(tmp_path: pathlib.Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """判据①的负控：把四条件判据打桩成恒假 ⇒ ① 必红（这一格不是恒真）。"""
    cond, top, _ws, ids = _built(tmp_path)
    monkeypatch.setattr(SEC, "ran_but_unnamed", lambda row, known: False)
    with pytest.raises(AssertionError):
        _a_really_ran_but_unnamed_is_named(cond, top, ids)


# ====================================================================== 判据②
def test_a_gate_refused_number_is_not_counted_as_ran_but_unnamed(
        tmp_path: pathlib.Path) -> None:
    """判据②：被派活闸拒掉的号不出现在这一格（本格不重开 d9ebb7fe / 1cdacbf6 的证明）。"""
    cond, top, _ws, ids = _built(tmp_path)
    got = cond.secretary.unnamed_children()
    assert ids["phantom"] not in _ids(got), ("闸拒的号不许混进『真跑无名』", got)
    # 正控：同一夹具里的真子必须出现（否则"没混进来"只是因为整格是空的）
    assert ids["real"] in _ids(got), got
    # 三档里的另外两种拒绝同样按这一条界处理（任何 outcome=refused 都不算跑过）
    for outcome in ("refused",):
        tid = _row(cond, top, "E", key=f"judge:gate-{outcome}", outcome=outcome)
        assert tid not in _ids(cond.secretary.unnamed_children()), tid
    # 板项行也不是代理
    assert ids["board"] not in _ids(got), got


# ====================================================================== 判据③
def test_an_in_flight_child_is_not_counted(tmp_path: pathlib.Path) -> None:
    """判据③：在飞的（`running`、无 `ended_at`）不出现；它落定之后才出现。"""
    cond, top, _ws, ids = _built(tmp_path)
    got = cond.secretary.unnamed_children()
    assert ids["flying"] not in _ids(got), ("在飞的不许报成『跑过没名』", got)
    # 正控：把它落定（补 ended_at / outcome）⇒ 同一格必须出现
    row = dict(cond._task(ids["flying"]) or {})
    row.update({"status": "done", "outcome": "ok", "ended_at": BR})
    with cond.store.tx("tasks", actor="test", note="judge:settle") as tx:
        tx.upsert("tasks", row, note="judge:settle")
    assert ids["flying"] in _ids(cond.secretary.unnamed_children())


# ====================================================================== 判据④
def test_a_full_roster_makes_the_cell_empty_not_missing(tmp_path: pathlib.Path) -> None:
    """判据④：名册齐全 ⇒ `count == 0` 且 `checked is True`（不是"没查成"）。"""
    cond, top, _ws, _st = _env(tmp_path / "full")
    kid = _row(cond, top, "E", key="judge:ok")
    _register(cond, top, kid, "E1")
    got = cond.secretary.unnamed_children()
    assert got.get("checked") is True, got
    assert got.get("count") == 0 and got.get("rows") == [], got
    # 反真空：同一个夹具里再造一个"没登记"的号 ⇒ 同一个函数必须非 0
    loose = _row(cond, top, "E", key="judge:loose")
    got2 = cond.secretary.unnamed_children()
    assert got2.get("count") == 1 and _ids(got2) == [loose], got2


# ====================================================================== 判据⑤
def _summary_is_visible(rep: Any) -> None:
    """判据⑤的内容：summary 有半句、门强度一格没改。"""
    ros = rep.readings.get("roster_registration") or {}
    un = ros.get("unnamed") or {}
    assert un.get("checked") is True and un.get("count") == 1, ros
    assert "有 1 个真跑的子代理没有名字" in rep.summary(), rep.summary()
    assert not rep.blockers, ("这一格只可见、不许 fail", [f.to_dict() for f in rep.findings])
    assert "roster_registration" not in rep.status, ("它不是八格之一", rep.status)


def test_the_closing_summary_says_it_and_the_gate_does_not_get_stronger(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据⑤：收工那一行有半句；读数坏掉时不许升级成 blocker。"""
    cond, _top, ws, _ids = _built(tmp_path)
    SS.append(ws, {"kind": "agent_step", "role": "M", "index": 1, "shape": "summon",
                   "result": {"roster_name": "E1"}}, sid=SID)
    SS.append(ws, {"kind": "agent_run_end", "role": "M", "stop_reason": "final"}, sid=SID)
    rep = CL.check_closing(cond.store, session_root=ws, sid=SID, checks=())
    _summary_is_visible(rep)
    # 负控：把这一格删掉 ⇒ ⑤ 必红
    monkeypatch.setattr(CL, "unnamed_children_reading", lambda *a, **k: {})
    rep2 = CL.check_closing(cond.store, session_root=ws, sid=SID, checks=())
    with pytest.raises(AssertionError):
        _summary_is_visible(rep2)


# ====================================================================== 判据⑥
def test_a_missing_artifact_is_named(tmp_path: pathlib.Path) -> None:
    """判据⑥：产物不在盘上时逐条点名（"在不在"是这一格的一部分，不是附加信息）。"""
    cond, top, _ws, _ids = _env(tmp_path)
    kid = _row(cond, top, "E", key="judge:no-artifact",
               artifacts=("out/tasks/这不是一个真文件.json",))
    got = cond.secretary.unnamed_children()
    row = _one(got, kid)
    assert row["artifacts"] == ["out/tasks/这不是一个真文件.json"], row
    assert row["artifacts_missing"] == ["out/tasks/这不是一个真文件.json"], row
