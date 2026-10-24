# -*- coding: utf-8 -*-
"""判据 ③：路由办成的直写是过程读数，只有"兜底方没接住"才进错误表。

## 改前是什么形态（一个类目装了两件相反的事）

`errorstats` 的 `routed_to_backstop` 这一类同时收：`routed_to_backstop.<兜底方>`
（系统按设计接管、行真的落了盘）与 `*_refused` / `*_unavailable`（这一笔没落成）。
后果与 multi_call 当初一模一样：系统替模型办成了，却照样进"错误动作总数"。

## 判据（按 multi_call 同法拆）

- 办成的 → 过程读数 `direct_write_routed`（不进 `total` / `role_total` / `by_role`）；
- 被兜底方拒 / 兜底方不可达 → 仍留在错误表（类目名还是 `routed_to_backstop`）；
- 反真空：把路由表清空 ⇒ 同一笔写真的被读成 `direct_write`（错误表那一档），
  证明"过程读数那 1 条"不是硬编码出来的。

夹具形状照 `tests/test_direct_write_is_routed_to_the_secretary.py`（同一份合法载荷），
差异只有一处：这里判的是统计口径，不是路由本身。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import errorstats as ES
from agentflow import store as store_mod
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import table_tools as TT
from agentflow.tools.base import ToolRegistry

from conftest import add_literature, add_request

#: 一份合法的命题载荷（与那条路由判据用的是同一份，便于两份读数对拍）。
LEGAL: dict = {
    "origin": "external_lit",
    "kind": "theorem",
    "label": "R(3,4) = 9",
    "statement_full": ("设 R(k, m) 是二色 Ramsey 数：最小的 N0，使得任意 N > N0 个顶点的完全图"
                       "把每条边染成红或蓝之一，都必出现 k 点红团或 m 点蓝团。则 R(3, 4) = 9。"),
    "statement_text": "R(3,4) = 9",
    "proof_text": ("Theorem 2 may now be used to remove the doubt as to the values n(3,4) < 9. "
                   "Since n(2,5) = 5 one readily obtains that n(3,4) = 9."),
    "source_lit_id": "0000",
    "page_range": {"start": 3, "end": 3},
    "quote_verified": None,
    "quote_reason": "还没逐字回验（本判据只核统计口径）",
    "evidence_kind": "heuristic",
}


def _ws(tmp_path: pathlib.Path) -> Store:
    """一个小工作区：一篇在册文献（命题的出处要能核到）。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_request(st, "r-0001", done=True, result_lit_ids=["0000"])
    add_literature(st, "0000", title="Combinatorial Relations and Chromatic Graphs",
                   path=None, processed=True, source_request_ids=["r-0001"],
                   dedup_key="doi:10.4153/CJM-1955-001-4", doi="10.4153/CJM-1955-001-4",
                   year=1955)
    return st


def _reg(st: Store) -> ToolRegistry:
    """通用写口那一张面（直写被它拦下，然后交给兜底方）。"""
    reg = ToolRegistry(name="dw")
    TT.register(reg, store=st)
    return reg


def _as(role: str, fn):
    """在"这一趟是 role 发起的"这个挂点里跑一次（生产里由 `AgentLoop._do_tool` 挂）。"""
    with calling_as("t-000001", role):
        return fn()


def _stats_for(st: Store, *results) -> ES.ErrorStats:
    """同一份工作区 + 同一批工具结果 ⇒ 落成会话记录再读 `error_action_stats`。"""
    records = [{"kind": "agent_step", "role": "B", "index": i, "shape": "tool",
                "payload": {"name": "table.create"},
                "result": {"tool": "table.create", "ok": bool(r.ok), "data": r.data,
                           "error": r.error or "", "meta": dict(r.meta or {})}}
               for i, r in enumerate(results, 1)]
    path = pathlib.Path(str(st.root)) / "sessions" / "s1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records)
                    + "\n", encoding="utf-8")
    return ES.error_action_stats(st)


def test_a_routed_write_is_a_process_reading_and_a_refusal_is_the_error(
        tmp_path: pathlib.Path) -> None:
    """③ 办成的那一笔只进过程读数；被兜底方拒的那一笔才进 total。

    改前红：办成的那一笔会被读成 `routed_to_backstop`（错误表），于是 `total` 至少是 1。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    # ① 办成的：合法载荷 ⇒ 系统转交秘书、行真的落了盘
    ok_res = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                       row=dict(LEGAL)))
    assert ok_res.ok is True, (ok_res.error, ok_res.meta)
    ok_stats = _stats_for(st, ok_res)
    assert ok_stats.checked is True, ok_stats.reason
    assert ok_stats.category_total("routed_to_backstop") == 0, (
        "办成的那一笔进了错误表：", ok_stats.by_role)
    assert ok_stats.total == 0, ok_stats.by_role
    assert ok_stats.process_category_total("direct_write_routed") == 1, ok_stats.process
    # 结局码仍然分开计（过程读数那一栏不吞掉"是哪一种兜底方"这个事实）
    assert ok_stats.sources["hits"]["codes"]["B"]["routed_to_backstop.secretary"] == 1, (
        ok_stats.sources["hits"])

    # ② 被拒的：同一张表、缺必填 ⇒ 兜底方按它自己的判据拒 ⇒ 这一笔进错误表
    bad_res = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                        row=dict(LEGAL, statement_full="")))
    assert bad_res.ok is False, bad_res
    bad_stats = _stats_for(st, bad_res)
    assert bad_stats.category_total("routed_to_backstop") == 1, bad_stats.by_role
    assert bad_stats.total == 1, bad_stats.by_role
    assert bad_stats.process_category_total("direct_write_routed") == 0, bad_stats.process


def test_clearing_the_route_table_reads_the_same_write_as_direct_write(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 反真空：路由表清空 ⇒ 同一笔写真的被读成 `direct_write`。

    没有这一条，"过程读数那 1 条"可能只是把某个常量记了一次 ——
    它证明那条读数确实来自"这一笔真的被转交并办成了"。
    """
    st = _ws(tmp_path)
    reg = _reg(st)
    monkeypatch.setattr(store_mod, "DIRECT_WRITE_ROUTES", ())
    refused = _as("B", lambda: reg.call("table.create", role="B", table="statements",
                                        row=dict(LEGAL)))
    assert refused.ok is False, refused
    stats = _stats_for(st, refused)
    assert stats.total == 1, stats.by_role
    assert stats.count("B", "direct_write") == 1, stats.by_role
    assert stats.process_category_total("direct_write_routed") == 0, stats.process
