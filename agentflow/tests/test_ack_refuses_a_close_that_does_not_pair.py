# -*- coding: utf-8 -*-
"""`conductor.ack` 的收口方式与 expects 不配对时：必须在动盘之前拒（2026-10-29 第 15 轮）。

改前的形态（真缺陷，不是风格问题）：`close="acked"` 给一条 `expects="work"` 的项，
`ack_items` 先把 seen 补记落盘，再在 `_set_item(done)` 里被 `S.Task.validate()`
抛出 `ValueError`；工具层兜住异常后回 `state="unknown"`（"落没落盘不知道"），
而盘上其实已经半笔写好（行停在 `seen`）。
⇒ 半笔事务 + 读数说不知道，正是本仓反复修的那一类。

判据断三件：
  1. 回执是受控拒绝（`state="refused"`、`refusal_codes` 里有 `bad_close`）；
  2. 那一行一个字节没动（`item_state` 还是 `queued`、`seen_by` 还是空）；
  3. 同一批里配对正确的那一条照常成功（不是整批瘫掉）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from agentflow.conductor import Conductor, LocalBackend, calling_as  # noqa: E402
from agentflow.store import Store  # noqa: E402


def _ws(tmp: pathlib.Path) -> tuple[Store, Conductor, str, str, str]:
    st = Store(tmp / "ws")
    st.init()
    cond = Conductor(st, registry={}, backend=LocalBackend({}))
    owner = str(cond.open_top_level_run("M", "ack 配对判据"))
    with calling_as(owner, "M"):
        work = cond.open_item(kind="delegation", role="D", expects="work", action="work",
                              summary="work 类项", called_by="M", parent_task_id=owner, depth=2)
        note = cond.open_item(kind="message", role="D", expects="ack", action="message",
                              summary="ack 类项", called_by="M", parent_task_id=owner, depth=2)
    def _id(x):
        return str(x.get("item_id") or x.get("task_id") or "") if isinstance(x, dict) else str(x)

    return st, cond, owner, _id(work), _id(note)


def _row(cond: Conductor, tid: str) -> dict:
    return next(r for r in cond._tasks() if str(r.get("task_id")) == tid)


def test_a_close_that_does_not_pair_is_refused_before_any_write(tmp_path: pathlib.Path) -> None:
    st, cond, owner, work, note = _ws(tmp_path)
    before_work = dict(_row(cond, work))
    out = cond.ack_items([work], close="acked", by_task_id=owner)
    assert out["state"] == "refused", out
    assert "bad_close" in (out.get("refusal_codes") or []), out
    after_work = _row(cond, work)
    assert after_work.get("item_state") == before_work.get("item_state"), after_work
    assert not str(after_work.get("seen_by") or ""), after_work
    assert after_work.get("item_close") == "", after_work


def test_the_paired_one_in_the_same_batch_still_goes_through(tmp_path: pathlib.Path) -> None:
    st, cond, owner, work, note = _ws(tmp_path)
    good = cond.ack_items([note], close="acked", by_task_id=owner)
    assert good["state"] == "acked", good
    assert _row(cond, note).get("item_state") == "done"
