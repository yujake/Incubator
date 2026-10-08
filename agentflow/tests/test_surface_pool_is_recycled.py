# -*- coding: utf-8 -*-
"""S1n：读写面的槽位池 —— 造子代理时预订面、退役时归档后归还、再分配拿到干净的面。

业主 T23 逐字：「子代理只能读写父代理切割给它的读写面，且父代理原则上必须把各子代理的
读写面拆开。当然若子代理想新写文件，这个是允许的」＋ 深夜补充：「退役后读写面释放进可分配池」。

本批只做池那一半（面的分配/归还/归档/三态读数，`draft/92` §3.3/§3.6）；
"子只能读写面内"的强制（每实例一个注册表、`FsContext.root` = 该实例的面）
另行一批（`S1n-b`），因为要动的是装配点而不是秘书。

## 判据（正控 3 / 负控 2 / 反真空 2）

正控：① 造一个 ⇒ 拿到一个槽位且目录建出来；② 退役 ⇒ 面里的东西归档、槽位回池；
③ 再分配 ⇒ 拿到同一个槽位且目录是干净的（新子代理看不到前任的文件）。
负控：① 点名的槽位在用 ⇒ 受控拒绝（不静默换一个）；② 面拿不到 ⇒ `roster_add` 受控拒绝
（不许造出"能说话但不能干活"的项）。
反真空：① 池事件坏行 ⇒ `checked=False`（不许当"都空闲"）；② 归档失败 ⇒ 槽位停在"待释放"、
不入池。
"""
from __future__ import annotations

import json
import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import (
    Secretary,
    archive_dir,
    surface_dir,
    surfaces_path,
)
from agentflow.store import Store


def _env(tmp_path: pathlib.Path) -> tuple[Store, Conductor, Secretary, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return st, cond, Secretary("M", root=ws, store=st), ws


def _child(cond: Conductor, parent: str, *, key: str, status: str = "done") -> str:
    """建一条真代理行（退那一支要读台账：`retire_ready` 不认手编的编号）。"""
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-08T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def test_alloc_makes_a_slot_and_a_directory(tmp_path: pathlib.Path):
    """正控：造一个子代理 ⇒ 名册里记着它的槽位，且那个目录真在盘上。"""
    _st, cond, sec, ws = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    got = sec.roster_add(owner=owner, role="D", task_id=_child(cond, owner, key="s1n@a"),
                         brief="第一件")
    assert got["problem"] == "" and got["surface"] == "S01", got
    row = sec.roster_rows(owner)[0][0]
    assert row["surface"] == "S01", row
    assert surface_dir(ws, owner, "S01").is_dir(), "面目录要建出来"
    state = sec.surface_state(owner)
    assert state["in_use"] == [{"slot": "S01", "name": "D1"}], state


def test_retire_archives_then_returns_the_slot(tmp_path: pathlib.Path):
    """正控：退役 ⇒ 面里的东西归档、槽位回池；再分配拿到干净的面。"""
    _st, cond, sec, ws = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    first = _child(cond, owner, key="s1n@b")
    got = sec.roster_add(owner=owner, role="D", task_id=first, brief="要退的那件")
    slot = got["surface"]
    (surface_dir(ws, owner, slot) / "draft.txt").write_text("前任的草稿", encoding="utf-8")

    retired = sec.retire(owner=owner, name="D1", by_task_id=owner)
    assert retired["ok"] is True and retired["surface"] == slot, retired
    assert "已归还池里" in " ".join(retired["why"]), retired
    state = sec.surface_state(owner)
    assert state["free"] == [slot] and not state["in_use"], state
    archived = archive_dir(ws, owner, "D1")
    assert (archived / "draft.txt").read_text(encoding="utf-8") == "前任的草稿", archived

    later = _child(cond, owner, key="s1n@c")
    again = sec.roster_add(owner=owner, role="D", task_id=later, brief="后来那件")
    assert again["surface"] == slot, ("退役的槽位应当被再分配", again)
    assert list(surface_dir(ws, owner, slot).iterdir()) == [], "新子代理拿到的面必须是干净的"


def test_allocating_someone_elses_slot_is_refused(tmp_path: pathlib.Path):
    """负控：点名的槽位在用 ⇒ 受控拒绝（不静默换一个）。"""
    _st, cond, sec, _ws = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    assert sec.roster_add(owner=owner, role="D", task_id="t-0002", brief="占位")["surface"] == "S01"
    got = sec.surface_alloc(owner=owner, want="S01", name="D2")
    assert got["slot"] == "S01" and "不在空闲池里" in got["problem"], got


def test_roster_add_refuses_when_no_surface_can_be_taken(tmp_path: pathlib.Path,
                                                         monkeypatch):
    """负控：面拿不到 ⇒ `roster_add` 受控拒绝（不许造出"能说话但不能干活"的项）。"""
    _st, cond, sec, _ws = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    monkeypatch.setattr(sec, "surface_alloc",
                        lambda **_kw: {"slot": "", "path": "", "problem": "注入的池故障"})
    got = sec.roster_add(owner=owner, role="D", task_id="t-0002", brief="拿不到面的那件")
    assert got["problem"] and "读写面没定下来" in got["problem"], got
    assert sec.roster_rows(owner)[0] == [], ("拒了就不许留名册项", sec.roster_rows(owner))


def test_a_broken_pool_event_is_three_state(tmp_path: pathlib.Path):
    """反真空：池事件有坏行 ⇒ `checked=False`（不许当"都空闲"）。"""
    _st, cond, sec, _ws = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    path = surfaces_path(sec.root, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{不是 JSON\n", encoding="utf-8")
    state = sec.surface_state(owner)
    assert state["checked"] is False and "读不出来" in state["reason"], state
    got = sec.surface_alloc(owner=owner, name="D1")
    assert got["problem"] and "池没读成" in got["problem"], got


def test_a_failed_archive_keeps_the_slot_out_of_the_pool(tmp_path: pathlib.Path,
                                                         monkeypatch):
    """反真空（第二处）：归档失败 ⇒ 槽位停在"待释放"、不入池（新子代理拿不到它）。"""
    _st, cond, sec, ws = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    got = sec.roster_add(owner=owner, role="D", task_id="t-0002", brief="归档会失败的那件")
    slot = got["surface"]
    (surface_dir(ws, owner, slot) / "x.txt").write_text("有内容", encoding="utf-8")

    import shutil as _sh

    def boom(*_a, **_kw):
        raise OSError("注入的归档故障")

    monkeypatch.setattr(_sh, "move", boom)
    state, why = sec.surface_release(owner=owner, name="D1", slot=slot)
    assert state == "待释放" and "归档" in why or "注入" in why, (state, why)
    pool = sec.surface_state(owner)
    assert [x["slot"] for x in pool["pending_release"]] == [slot], pool
    assert pool["free"] == [], ("没归档干净就不许放回池", pool)
    assert sec.surface_alloc(owner=owner, want=slot, name="D2")["problem"], "待释放的槽位不许被分配"
    assert json.dumps(pool, ensure_ascii=False)
