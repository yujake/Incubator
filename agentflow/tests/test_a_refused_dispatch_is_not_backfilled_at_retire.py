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
落下的那一条流水（`out/roster/refusals/<父>.jsonl`）。

## 这一组守什么

1. 正题（`name_taken`）：第二件活撞名被拒 ⇒ 销号 D1 之后，名册里仍然只有 D1/t1，
   t2 一行都不多（改前：多一行 `D2/t2 repaired=true`）；
2. 正题（`not_in_roster`，新号）：复用一个名册里没有的名字被拒 ⇒ 销号之后也不许多一行。
   为什么不再用 `task_id_reused`：那个理由码的前提恰恰是"这个号已经在 known 里"，
   于是销号兜底本来就不会补它 —— 实测（本笔的 temp 探针在两棵树上各跑一次）两棵树
   的 `adds_after_retire` 完全相同（都只有 `D1/t1`）⇒ 那条判据恒绿，等于没量。
   换成新号之后，改前（2c7b29da）销号会真的多出一行 `D2/t2`（行为红），改后才不多；
3. 反真空（真孤儿）：台账里有、名册里没有、没有拒绝记录 ⇒ 收工兜底仍然要补，
   否则 79 那趟"11 个节点卡住"会复发；
4. 三态：拒绝流水读不出来 ⇒ `roster_repair` 不补（返回非空问题），不许把"读不到"
   当成"没被拒过"；
5. 负控：把 `roster_repair` 打桩成 no-op ⇒ 第 3 条（真孤儿仍要补）必红。没有这一条，
   第 3 条的绿可能来自别处顺手补的行，"补的行为还在"就没有被人量过。

## 在旧树（2c7b29da）上怎么读

旧树没有 `SEC.refusals_path` 这个 API。若判据一开口就调它，红的是
`AttributeError: module 'agentflow.secretary' has no attribute 'refusals_path'`
—— 那是"新 API 不存在"，不是"retire 之后名册多一行"。所以本文件：

- 用 `_refusals_path()` 解析落点（新树走 API，旧树按同一份落点约定拼路径，只读）；
- 把"名册有没有多一行"的断言排在任何拒绝流水断言之前。

于是旧树上的红是行为红（`_ids` 多出被拒的号），而不是 API 缺失。
"""
from __future__ import annotations

import json
import pathlib

import pytest

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


def _refusals_path(ws: pathlib.Path, owner: str) -> pathlib.Path:
    """拒绝流水的落点：新树走 `secretary.refusals_path`，旧树（2c7b29da）没有这个 API。

    为什么判据自己拼一次旧落点：这一组要量的行为是"销号之后名册里有没有多一行"，
    它不依赖那个函数存在。旧树上一开口就调未定义的 API，红的是 AttributeError
    （量到的是"新 API 不存在"），而不是"被拒的号被补了一行"（行为红）。这里只解析
    路径（同一份落点约定 `out/roster/refusals/<父>.jsonl`），不碰写侧、不改断言。
    """
    fn = getattr(SEC, "refusals_path", None)
    if callable(fn):
        return pathlib.Path(fn(ws, owner))
    return pathlib.Path(ws).joinpath("out", "roster", "refusals", f"{owner}.jsonl")


def _refused_lines(ws: pathlib.Path, owner: str) -> list[dict]:
    path = _refusals_path(ws, owner)
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
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="判据")
    assert got.get("ok") is True, got
    # 行为断言排在流水断言之前：旧树（没有 refusals_path）先按"名册多一行"红。
    assert _ids(cond, parent) == [t1], (
        "被拒的那件活在销号时被补成新名字了（等于悄悄改写那次拒绝）", _ids(cond, parent))
    refused = _refused_lines(ws, parent)
    assert [str(r.get("task_id")) for r in refused] == [t2], refused
    assert str(refused[0].get("refusal_code")) == "name_taken", refused


def test_a_not_in_roster_dispatch_is_not_backfilled_at_retire(
        tmp_path: pathlib.Path) -> None:
    """正题：复用一个名册里没有的名字被拒（新号）⇒ 销号之后也不许多出一行。

    改前的夹具用的是 `task_id_reused`，而那个码的前提就是"这个号已经在 known 里"
    ⇒ 销号兜底本来就不会补它，改前/改后名册都不变（恒绿）。换成新号 + `not_in_roster`
    之后，改前（2c7b29da）销号会真的补一行 `D2/t2 repaired=true`，这条判据才量得到行为。
    """
    cond, parent, ws = _env(tmp_path)
    sec = cond.secretary
    t1 = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=t1, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    t2 = _child(cond, parent, tag="second")
    before = _ids(cond, parent)
    # 新号：名册里没有它（这正是"销号兜底会真的去补"的前提）。
    assert t2 not in before, before
    rec = cond._register_roster(task_id=t2, role="D", owner=parent,
                                meta={"reuse": "D9", "brief": "复用一个不存在的名字",
                                      "task": "接着做"})
    assert str(rec.get("refusal_code") or "") == "not_in_roster", rec
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="判据")
    assert got.get("ok") is True, got
    # 行为断言排在流水断言之前：旧树（没有 refusals_path）先按"名册多一行"红。
    assert _ids(cond, parent) == [t1], (
        "被 not_in_roster 拒掉的新号，销号时被补成新名字了", _ids(cond, parent))
    refused = _refused_lines(ws, parent)
    assert [str(r.get("task_id")) for r in refused] == [t2], refused
    assert [str(r.get("refusal_code")) for r in refused] == ["not_in_roster"], refused


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
    ledger = _refusals_path(ws, parent)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("这不是 JSON\n", encoding="utf-8")
    fixed, why = cond.secretary.roster_repair(owner=parent)
    assert fixed == 0, (fixed, why)
    assert why, ("拒绝流水读不出来却当成'没被拒过'补了行", _ids(cond, parent))
    assert orphan not in _ids(cond, parent), _ids(cond, parent)


def test_negative_control_a_noop_repair_makes_the_orphan_judgement_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：`roster_repair` 打桩成 no-op ⇒ 第 3 条（真孤儿仍要补）必红。

    为什么负控要写进判据文件：第 3 条绿只说明"孤儿在名册里"，不说明"是收工兜底补的"。
    只有在"把补登记拿掉它必红"时，"补的行为还在"才算被量过。打桩点取
    `Secretary.roster_repair`（`retire` 唯一的补登记入口），no-op 返回 `(0, "")`，
    不改生产代码、不放宽第 3 条的任何断言。
    """
    monkeypatch.setattr(Secretary, "roster_repair", lambda self, *, owner: (0, ""))
    with pytest.raises(AssertionError) as caught:
        test_a_real_orphan_is_still_backfilled(tmp_path)
    assert "真孤儿也没补上" in str(caught.value), caught.value
    # 另起一份干净夹具，把"打桩之后名册里确实没有孤儿"读出来（读数，不靠猜）。
    cond, parent, _ws = _env(tmp_path / "neg")
    orphan = _orphan(cond, parent)
    got = cond.secretary.retire(owner=parent, name="谁都不叫这个名字", by_task_id=parent)
    assert got.get("ok") is False, got
    assert orphan not in _ids(cond, parent), _ids(cond, parent)
