# -*- coding: utf-8 -*-
"""判据：被写口拒掉的派活，不许在收工兜底里被补成新名字；真孤儿仍要补。

## 业主 2026-11-02 的裁定（收窄 `retire` 的收工兜底）

上一版：`retire` 在解析名字之前先跑 `roster_repair`，把"台账有、名册没有"的行全部
补上。于是派活时被 `name_taken` / `task_id_reused` 拒掉的号，会在下一次任何人销号时
拿到一个新名字（`temp/probe_h11_leftovers.py` 的 L 读数：`adds_after_retire` 多出
`D2/t-000012 repaired=true`）。业主裁定：被拒是一次有记录的决定，收口时再把它变成
子节点等于悄悄改写事实 —— 而这正是这一轮在治的病。

收窄后的口径：只补"从未登记过、也没有一次被拒记录"的行。判别式为什么是"拒绝记录"
而不是时间戳：拒绝当时名册三份一个字节都没写，跨进程唯一靠得住的证据就是拒绝那一刻
落下的那一条流水（`out/roster/<父>-refused.jsonl`）。

## 这一组守什么

1. 正题（`name_taken`）：第二件活撞名被拒 ⇒ 销号 D1 之后，名册里仍然只有 D1/t1，
   t2 一行都不多（改前：多一行 `D2/t2 repaired=true`）；
2. 正题（`task_id_reused`）：同一个号登记到第二个名字被拒 ⇒ 销号之后也不许多一行；
3. 反真空（真孤儿）：台账里有、名册里没有、没有拒绝记录 ⇒ 收工兜底仍然要补，
   否则 79 那趟"11 个节点卡住"会复发；
4. 三态：拒绝流水读不出来 ⇒ `roster_repair` 不补（返回非空问题），不许把"读不到"
   当成"没被拒过"。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.secretary = Secretary("M", root=ws, store=st, enable_model=False)
    cond.roster_sink = cond.secretary
    top = cond.open_top_level_run("M", "顶趟这一趟")
    return cond, str(top), ws


def _child(cond: Conductor, parent: str, *, tag: str) -> str:
    return str(cond._write_new_row({
        "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 1, "input_key": f"judge:{tag}",
        "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "判据夹具：一条已经收口的子行", "error": None,
        "started_at": BR, "ended_at": BR,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="judge:child"))


def _orphan(cond: Conductor, parent: str) -> str:
    """真孤儿：台账里有一行、名册里没有、也没有任何拒绝记录（实例分派那条路留下的形态）。"""
    return str(cond._write_new_row({
        "role": "D", "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "@orphan", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "D#1", "detail": "",
        "error": None, "started_at": BR, "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": ["conductor:admitted"],
    }, note="judge:orphan"))


def _ids(cond: Conductor, parent: str) -> list[str]:
    rows, problems = cond.secretary.roster_rows(parent)
    assert problems == [], problems
    return [str(r.get("task_id")) for r in rows]


def _refused_lines(ws: pathlib.Path, owner: str) -> list[dict]:
    path = SEC.refusals_path(ws, owner)
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_a_name_taken_dispatch_is_not_backfilled_at_retire(tmp_path: pathlib.Path) -> None:
    """正题：撞名被拒的那件活，销号时不许被补成新名字。"""
    cond, parent, ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    t2 = _child(cond, parent, tag="second")
    rec = cond._register_roster(task_id=t2, role="D", owner=parent,
                                meta={"name": "D1", "brief": "第二件活", "task": "接着做"})
    assert str(rec.get("refusal_code") or "") == "name_taken", rec
    refused = _refused_lines(ws, parent)
    assert [str(r.get("task_id")) for r in refused] == [t2], refused
    assert str(refused[0].get("refusal_code")) == "name_taken", refused
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="判据")
    assert got.get("ok") is True, got
    assert _ids(cond, parent) == [t1], (
        "被拒的那件活在销号时被补成新名字了（等于悄悄改写那次拒绝）", _ids(cond, parent))


def test_a_task_id_reused_dispatch_is_not_backfilled_at_retire(
        tmp_path: pathlib.Path) -> None:
    """正题：同一个号登记到第二个名字被拒 ⇒ 销号之后也不许多出一行。"""
    cond, parent, ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    rec = cond._register_roster(task_id=t1, role="D", owner=parent,
                                meta={"name": "D2", "brief": "同一个号再登一次", "task": "做研究"})
    assert str(rec.get("refusal_code") or "") == "task_id_reused", rec
    assert [str(r.get("refusal_code")) for r in _refused_lines(ws, parent)] == ["task_id_reused"]
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="判据")
    assert got.get("ok") is True, got
    assert _ids(cond, parent) == [t1], _ids(cond, parent)


def test_a_real_orphan_is_still_backfilled(tmp_path: pathlib.Path) -> None:
    """反真空：台账有、名册没有、也没有拒绝记录 ⇒ 收工兜底仍然补（79 那趟的形态）。"""
    cond, parent, _ws = _env(tmp_path)
    orphan = _orphan(cond, parent)
    before = _ids(cond, parent)
    assert orphan not in before, before
    got = cond.secretary.retire(owner=parent, name="谁都不叫这个名字", by_task_id=parent)
    assert got.get("ok") is False, got            # 名字不存在 ⇒ 仍被拒
    assert orphan in _ids(cond, parent), (
        "真孤儿也没补上：收窄过头了（79 那趟'11 个节点卡住'会复发）", _ids(cond, parent))


def test_an_unreadable_refusal_ledger_is_not_an_empty_one(tmp_path: pathlib.Path) -> None:
    """三态：拒绝流水读不出来 ⇒ 不补（"读不到"不是"没被拒过"）。"""
    cond, parent, ws = _env(tmp_path)
    orphan = _orphan(cond, parent)
    ledger = SEC.refusals_path(ws, parent)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("这不是 JSON\n", encoding="utf-8")
    fixed, why = cond.secretary.roster_repair(owner=parent)
    assert fixed == 0, (fixed, why)
    assert why, ("拒绝流水读不出来却当成'没被拒过'补了行", _ids(cond, parent))
    assert orphan not in _ids(cond, parent), _ids(cond, parent)
