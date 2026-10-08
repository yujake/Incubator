# -*- coding: utf-8 -*-
"""S1k-1：名册 + 对照表 + 接线员 + 退役三分支（秘书侧；`draft/90` §1 / §1.9、`draft/92` §3.3）。

## 这一批补的是什么

`draft/90` E16/E17 的实测：名册、对照表、本地名三样都不存在；子代理唯一的身份是
绝对编码 `t-00xx`。本批落秘书侧那一半（名字、电话簿、译码、退役三分支、销号名单），
名字面（形状 `retire`/`roster` 与提示词渲染）在 S1k-2。

## 判据（正控 3 / 负控 3 / 反真空 2 / 口径 1）

正控：① 造一个 D1 ⇒ 名册 +1、对照表 +1、两处 `task_id` 一致，且简介就是父给的那一句；
② 退役三分支各一条（活跃 ⇒ `reported` 带最近报告；名下还有活跃子 ⇒ `reported` 带那些活的简介；
都不在跑且名下空 ⇒ `retired`）；③ 对账读数（台账 → 名册两个方向）。
负控：① 名字用过就拒（含已销号 ⇒ "已销号"，不许静默改名）② 简介为空 / 超长、多行 ⇒ 拒
（内容面：秘书不许替它编、也不许替它删）③ 查只报不修（`roster_view` 不许写盘）。
反真空：① 未登记的名字退役 ⇒ `refused` ② 台账读不成 ⇒ 三态（`checked=False`）。
口径：四态折叠（活跃 / 待命 / 已停 / 已退役）只在一处做（`_state_from`）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary, retired_path, roster_index_path, roster_path
from agentflow.store import Store


def _env(tmp_path: pathlib.Path) -> tuple[Store, Conductor, Secretary]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return st, cond, Secretary("M", root=ws, store=st)


def _child(cond: Conductor, parent: str, *, role: str = "D", status: str = "done",
           key: str = "s1k@c") -> str:
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": status,
        "outcome": None if status in ("pending", "running") else "ok",
        "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-08T22:00:00+08:00",
        "ended_at": None if status in ("pending", "running") else "2026-10-08T22:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def _lines(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_add_writes_both_the_roster_and_the_index(tmp_path: pathlib.Path):
    """正控：造一个 D1 ⇒ 名册 +1、对照表 +1、两处 `task_id` 一致、简介就是父给的那句。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, owner)

    got = sec.roster_add(owner=owner, role="D", task_id=child,
                         brief="把 X 的族构造证据补齐")
    assert got["problem"] == "" and got["name"] == "D1", got
    roster = sec.roster_rows(owner)[0]
    assert [r["name"] for r in roster] == ["D1"], roster
    assert roster[0]["brief"] == "把 X 的族构造证据补齐", roster[0]
    index = sec.roster_index(owner)[0]
    assert index[0]["name"] == "D1" and index[0]["task_id"] == child, index
    assert roster[0]["task_id"] == index[0]["task_id"] == child, (roster, index)
    assert roster_path(tmp_path / "ws", owner).is_file()
    assert roster_index_path(tmp_path / "ws", owner).is_file()


def test_a_used_name_is_refused_and_never_silently_renamed(tmp_path: pathlib.Path):
    """负控：名字用过就拒（在用 / 已销号两种理由），不许静默改名（业主 B2）。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    first = _child(cond, owner, key="s1k@a")
    second = _child(cond, owner, key="s1k@b")
    assert sec.roster_add(owner=owner, role="D", task_id=first, brief="第一件").get("name") == "D1"
    dup = sec.roster_add(owner=owner, role="D", task_id=second, brief="第二件", want_name="D1")
    assert dup["problem"] and "已经用过" in dup["problem"], dup
    assert dup["name"] == "D1", ("受控拒绝时也要把父说的那个名字回给它（不许悄悄换）", dup)
    assert len(sec.roster_rows(owner)[0]) == 1, sec.roster_rows(owner)


def test_brief_is_mandatory_and_single_line(tmp_path: pathlib.Path):
    """负控（内容面）：简介为空 / 多行 / 超长 ⇒ 拒（秘书不替它编，也不替它删）。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, owner)
    empty = sec.roster_add(owner=owner, role="D", task_id=child, brief="   ")
    assert empty["problem"] and "简介" in empty["problem"], empty
    multi = sec.roster_add(owner=owner, role="D", task_id=child, brief="两行\n第二行")
    assert multi["problem"] and "单行" in multi["problem"], multi
    long = sec.roster_add(owner=owner, role="D", task_id=child, brief="字" * 61)
    assert long["problem"] and "60" in long["problem"], long
    assert sec.roster_rows(owner)[0] == [], ("拒了就不许留半份", sec.roster_rows(owner))


def test_retire_branches_active_and_with_children_report_instead(tmp_path: pathlib.Path):
    """正控（三分支前两支）：活跃 ⇒ 报最近报告；名下还有活跃子 ⇒ 报那些活的简介。都不退役。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    busy = _child(cond, owner, status="running", key="s1k@busy")
    parentish = _child(cond, owner, status="done", key="s1k@parent")
    _child(cond, parentish, status="running", key="s1k@grand")
    sec.roster_add(owner=owner, role="D", task_id=busy, brief="还在跑的那件")
    sec.roster_add(owner=owner, role="D", task_id=parentish, brief="带子的那件")

    hot = sec.retire(owner=owner, name="D1", by_task_id=owner)
    assert hot["action"] == "reported" and hot["ok"] is False, hot
    assert "还在跑" in "".join(hot["why"]), hot
    assert "checked" in hot["report"], hot["report"]        # 最近报告那一格（可以是"没有报告行"）

    withkids = sec.retire(owner=owner, name="D2", by_task_id=owner)
    assert withkids["action"] == "reported" and withkids["ok"] is False, withkids
    kids = withkids["report"]["children"]
    assert len(kids) == 1 and kids[0]["state"] == "活跃", kids
    assert not retired_path(tmp_path / "ws", owner).is_file(), "不退役就不许写销号名单"


def test_retire_executes_and_remembers_the_name(tmp_path: pathlib.Path):
    """正控（第三支）+ 负控（销号后不许复用）：都不在跑且名下空 ⇒ 退役；名字进销号名单。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    free = _child(cond, owner, status="done", key="s1k@free")
    later = _child(cond, owner, status="done", key="s1k@later")
    sec.roster_add(owner=owner, role="D", task_id=free, brief="可以退的那件")
    got = sec.retire(owner=owner, name="D1", by_task_id=owner)
    assert got["ok"] is True and got["action"] == "retired", got
    retired = _lines(retired_path(tmp_path / "ws", owner))
    assert [r["name"] for r in retired] == ["D1"], retired
    assert sec.roster_rows(owner)[0][0]["retired"] is True, sec.roster_rows(owner)
    # 父侧那一笔幂等落痕（S1h 的 note_edge_release）
    assert cond.released_edges(owner)["edges"] == [{"child_task_id": free, "attempt": 1}]
    # 已销号的名字不许再用（B1）
    again = sec.roster_add(owner=owner, role="D", task_id=later, brief="后来的那件",
                           want_name="D1")
    assert again["problem"] and "销号" in again["problem"], again
    assert sec.roster_add(owner=owner, role="D", task_id=later,
                          brief="后来的那件").get("name") == "D2", "序号不回收"


def test_retire_of_an_unknown_name_is_refused(tmp_path: pathlib.Path):
    """反真空：未登记的名字退役 ⇒ `refused`（不许猜、也不许当"已经退了"）。"""
    _st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    got = sec.retire(owner=owner, name="D9", by_task_id=owner)
    assert got["action"] == "refused" and got["ok"] is False, got
    assert "对照表" in "".join(got["why"]), got


def test_roster_view_reports_and_never_writes(tmp_path: pathlib.Path):
    """负控（查只报不修，I-15）+ 反真空（台账读不成 ⇒ 三态）：视图不许改盘上任何东西。"""
    st, cond, sec = _env(tmp_path)
    ws = tmp_path / "ws"
    owner = cond.open_top_level_run("M", "父那一趟")
    child = _child(cond, owner, status="done", key="s1k@view")
    sec.roster_add(owner=owner, role="D", task_id=child, brief="看得见的那件")
    before = {p.name: p.read_text(encoding="utf-8") for p in
              sorted((ws / "out" / "roster").glob("*.jsonl"))}
    view = sec.roster_view(owner=owner)
    after = {p.name: p.read_text(encoding="utf-8") for p in
             sorted((ws / "out" / "roster").glob("*.jsonl"))}
    assert before == after, "查不许写盘（只报不修）"
    assert view["checked"] is True and view["rows"][0]["name"] == "D1", view
    assert view["rows"][0]["brief"] == "看得见的那件", view["rows"]
    assert view["rows"][0]["state"] in ("活跃", "待命", "已停"), view["rows"]
    assert view["rows"][0]["retirable"] is True, view["rows"]

    # 台账读不成 ⇒ checked=False（不许报"名下没有子代理"）。
    # 注意：秘书的 `_conductor()` 每次现造一个只读句柄，所以这里要换掉它，
    # 而不是换测试里那个 `cond`（换了也影响不到秘书 —— 这一条本身就值得记下来）。
    class _Broken:
        def retire_ready(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("注入的台账故障")

    orig_factory = sec._conductor
    sec._conductor = lambda: _Broken()      # type: ignore[assignment]
    try:
        bad = sec.roster_view(owner=owner)
        assert bad["checked"] is False and "没读成" in bad["reason"], bad
    finally:
        sec._conductor = orig_factory       # type: ignore[assignment]


def test_states_are_folded_from_two_orthogonal_reads(tmp_path: pathlib.Path):
    """口径：待命（在等待 + 声明过 keep_alive）与已停（在等待 + 没声明）分得开。"""
    st, cond, sec = _env(tmp_path)
    owner = cond.open_top_level_run("M", "父那一趟")
    standby = _child(cond, owner, status="done", key="s1k@sb")
    stopped = _child(cond, owner, status="done", key="s1k@st")
    cond.open_item(kind="delegation", role="D", expects="work", action="run_once",
                   summary="派给 D 的活", called_by="M", parent_task_id=standby,
                   depth=3, input_key="s1k@ka", keep_alive=True)
    sec.roster_add(owner=owner, role="D", task_id=standby, brief="待命那件")
    sec.roster_add(owner=owner, role="D", task_id=stopped, brief="停掉那件")
    view = {r["name"]: r["state"] for r in sec.roster_view(owner=owner)["rows"]}
    assert view == {"D1": "待命", "D2": "已停"}, view
