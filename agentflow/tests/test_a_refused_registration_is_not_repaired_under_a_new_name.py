# -*- coding: utf-8 -*-
"""判据：写口拒绝之后，那条子行不许被"兜底自愈"换个新名字补进名册。

## 业主 2026-11-02 的口径（改造后的七条之 ④）

撞名 = 受控拒绝（`name_taken`），交父决定；框架不替父改主意（`4e2963b4` 删掉了
`_register_roster` 里"撞名 ⇒ 静默换名"那一段）。这条判据钉的是同一件事的第二条入口：
拒绝之后若还跑 `roster_repair`（兜底自愈），那条"台账有、名册没有"的子行会被自愈
按一个新名字补上 —— 等于换个地方继续静默改名。

## 改前读数（`temp/probe_h11_leftovers.py`，2026-11-02 实测）

- H：`_register_roster(reuse=<已销号的名字>)` ⇒ 名册多出 `D2/t-000006 repaired=true`，
  回执 `state="written"`、`problem=""`、`note` 写"秘书那一侧报了问题（三份都已写成）"；
- I：`reuse=<名册里没有的名字>` ⇒ 回执 `state="missing"`，而盘上同样多出 `D2/t-000006`；
- J：简介为空（无 coded 拒绝）⇒ 回执 `state="missing"`，盘上仍然多出那一行。

## 这一组守什么

1. 正题：`reuse` 指向已销号的名字 ⇒ `member_retired` 受控拒绝，那个 `task_id`
   在名册里 0 行（改前：1 行，`repaired=true`）；
2. 正题：`reuse` 指向不存在的名字 ⇒ `not_in_roster` 受控拒绝，同样 0 行；
3. 正题：简介为空 ⇒ 拒绝，那个 `task_id` 同样 0 行（"任何拒绝"都算，不只三种 coded）；
4. 反真空：正常的登记仍然登记得上，且兜底自愈仍然在（补一条真正的漏行）——
   免得这一笔把"自愈"整个掐死，或把"登记"一起改坏。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.secretary = Secretary("M", root=ws, store=st, enable_model=False)
    cond.roster_sink = cond.secretary
    top = cond.open_top_level_run("M", "顶趟这一趟")
    return cond, str(top)


def _child(cond: Conductor, parent: str, *, tag: str) -> str:
    """在台账里造一条"父派下来的子行"（已收口 ⇒ 可以销号）。"""
    return str(cond._write_new_row({
        "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 1, "input_key": f"judge:{tag}",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "判据夹具：一条已经收口的子行", "error": None, "started_at": BR, "ended_at": BR,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="judge:child"))


def _rows(cond: Conductor, parent: str) -> list[dict]:
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    return rows


def _kinds(cond: Conductor, parent: str) -> list[tuple[str, str, bool]]:
    return [(str(r.get("name")), str(r.get("task_id")), bool(r.get("repaired")))
            for r in _rows(cond, parent)]


# ------------------------------------------------------------------ 1（reuse 已销号）
def test_a_reuse_of_a_retired_name_is_refused_and_not_repaired(tmp_path: pathlib.Path) -> None:
    """正题：`reuse=<已销号>` ⇒ `member_retired` 拒绝；那个号在名册里 0 行。"""
    cond, parent = _env(tmp_path)
    first = _child(cond, parent, tag="first")
    made = cond.secretary.roster_add(owner=parent, role="D", task_id=first,
                                     brief="第一件活", task="做研究")
    assert made.get("problem") == "", made
    dead = str(made.get("name") or "")
    gone = cond.secretary.retire(owner=parent, name=dead, by_task_id=parent, reason="判据")
    assert gone.get("ok") is True, gone
    second = _child(cond, parent, tag="second")
    rec = cond._register_roster(task_id=second, role="D", owner=parent,
                                meta={"reuse": dead, "brief": "第二件活", "task": "接着做"})
    assert str(rec.get("state") or "") == "missing", rec
    assert rec.get("problem"), rec
    assert str(rec.get("refusal_code") or "") == "member_retired", rec
    touched = [r for r in _rows(cond, parent) if str(r.get("task_id")) == second]
    assert touched == [], ("被拒的那一条被补进名册了（等于换个地方静默改名）", touched)


# ------------------------------------------------------------------ 2（reuse 不存在）
def test_a_reuse_of_an_unknown_name_is_refused_and_not_repaired(tmp_path: pathlib.Path) -> None:
    """正题：`reuse=<不存在>` ⇒ `not_in_roster` 拒绝；那个号在名册里 0 行。"""
    cond, parent = _env(tmp_path)
    first = _child(cond, parent, tag="first")
    cond.secretary.roster_add(owner=parent, role="D", task_id=first,
                              brief="第一件活", task="做研究")
    second = _child(cond, parent, tag="second")
    rec = cond._register_roster(task_id=second, role="D", owner=parent,
                                meta={"reuse": "D99", "brief": "第二件活", "task": "接着做"})
    assert str(rec.get("state") or "") == "missing", rec
    assert str(rec.get("refusal_code") or "") == "not_in_roster", rec
    touched = [r for r in _rows(cond, parent) if str(r.get("task_id")) == second]
    assert touched == [], ("被拒的那一条被补进名册了", touched)


# ------------------------------------------------------------------ 3（简介为空）
def test_a_registration_refused_without_a_code_is_not_repaired_either(
        tmp_path: pathlib.Path) -> None:
    """正题：没有机器码的拒绝（简介为空）同样不许被自愈补上 —— 判据是 `raised`，不是码。"""
    cond, parent = _env(tmp_path)
    orphan = _child(cond, parent, tag="nobrief")
    rec = cond._register_roster(task_id=orphan, role="D", owner=parent,
                                meta={"brief": "", "task": ""})
    assert str(rec.get("state") or "") == "missing", rec
    assert rec.get("problem"), rec
    touched = [r for r in _rows(cond, parent) if str(r.get("task_id")) == orphan]
    assert touched == [], ("被拒的那一条被补进名册了", touched)


# ------------------------------------------------------------------ 4（反真空）
def test_a_normal_registration_still_registers_and_the_backstop_still_runs(
        tmp_path: pathlib.Path) -> None:
    """反真空：正常登记照样写成；真正的漏行（历史）照样被兜底自愈补上。"""
    cond, parent = _env(tmp_path)
    orphan = _child(cond, parent, tag="orphan")
    mine = _child(cond, parent, tag="mine")
    rec = cond._register_roster(task_id=mine, role="D", owner=parent,
                                meta={"brief": "正常的一件活", "task": "做研究"})
    assert str(rec.get("state") or "") == "written", rec
    assert rec.get("problem") == "", rec
    ids = {str(r.get("task_id")) for r in _rows(cond, parent)}
    assert mine in ids, rec
    assert orphan in ids, ("兜底自愈被一起掐死了：这条漏行没补上", _kinds(cond, parent))
