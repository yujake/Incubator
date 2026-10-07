# -*- coding: utf-8 -*-
"""S-07 的判据：D 的 `write_report`"有调用、但台账里没有落点"这件事必须看得见。

裁定（`44 J-01` + `draft/52:112` 逐字）：只加读数，不新增 kind / 不新增表。
理由：D 的研究报告落不进 `analysis_reports`（`schema.REPORT_KINDS` 只收
`hottest/paths/cold/gaps` 四档，那是 C 的报告种类；`WRITE_SETS["D"]` 里也没有那张表）
—— 要给它找落点，要么扩 `REPORT_KINDS`（禁改区字段）、要么新开一张表（要人裁）。

真机读数（`44 S-07`）：45 次 `write_report` 只落磁盘、表 0 行，而这件事在读数面上
没有任何地方会说 ⇒ 下游把"有产物无台账"读成"D 没产报告"。这条读数就是让它看得见。
"""
from __future__ import annotations

import pathlib

from agentflow.agent_d._support import report_landing_reading
from agentflow.store import Store


def _store(tmp_path: pathlib.Path, *, d_calls: int = 0, broken: bool = False) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    if broken:
        return st
    for i in range(d_calls):
        with st.tx("tasks", actor="test", note="s07") as tx:
            tx.upsert("tasks", {
                "task_id": f"t-{i + 1:04d}", "role": "D", "action": "write_report",
                "called_by": "M", "parent_task_id": None, "depth": 2, "input_key": f"k{i}",
                "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
                "detail": "写了报告", "error": None,
                "started_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-01T00:00:01+00:00", "tokens": 0, "usd": 0.0,
                "artifacts": ["reports/t-0001.md"], "inputs": [],
            }, note="s07")
    return st


def test_s07_a_call_without_a_landing_is_visible(tmp_path: pathlib.Path):
    """判据（改前红：`report_landing_reading` 不存在 ⇒ AttributeError）：

    45 次那样的调用必须在读数里数得出来，而"台账里没有落点"必须是结构性的
    （不是"这次没写"）—— 所以 `landed == 0` 且 `landing_tables == []` 且
    `kind_writable is False` 三件同时给出来。
    """
    st = _store(tmp_path, d_calls=3)
    got = report_landing_reading(st)
    assert got["checked"] is True, got
    assert got["calls"] == 3, got
    assert got["landed"] == 0, "落点数不许凭空声称（今天没有一张表能收 D 的报告）"
    assert got["landing_tables"] == [] and got["kind_writable"] is False, got
    assert got["task_ids"] == ["t-0001", "t-0002", "t-0003"], got
    assert "只落磁盘" in got["note"] and "没有它的落点" in got["note"], got["note"]
    # 没有落点不是"没写报告"：调用数 > 0 而落点 0，两件事分得开
    assert got["calls"] > got["landed"], got


def test_s07_the_reading_is_quiet_when_nothing_was_called(tmp_path: pathlib.Path):
    """反负控（别把噪音当读数）：一次 `write_report` 都没调过 ⇒ `calls == 0`，但仍要
    如实给出"落点结构性为 0"这件事（它是结构读数，不是"这次没有"）。"""
    st = _store(tmp_path)
    got = report_landing_reading(st)
    assert got["checked"] is True and got["calls"] == 0, got
    assert got["landed"] == 0 and got["landing_tables"] == [], got


def test_s07_the_reading_admits_when_it_could_not_be_taken(tmp_path: pathlib.Path):
    """三态：表读不出来 ⇒ `checked=False` + 理由（"没查成"不许折成"没有调用"）。"""
    class _Broken:
        def rows(self, table):
            raise OSError("表读不出来")

    got = report_landing_reading(_Broken())
    assert got["checked"] is False and "读不出来" in got["reason"], got
    assert got["calls"] == 0 and got["landed"] == 0, got


def test_s07_the_reading_carries_its_own_caliber(tmp_path: pathlib.Path):
    """口径必须印在读数里（2026-10-02 主控现场更正）。

    这条读数数的是 `tasks` 台账的落盘行，而权威读数是 `sessions/*.jsonl` 的
    `events` 重放 —— 两个口径的数差得很远（实测某工作区 `tasks.json` 2 行、
    同目录 `events.jsonl` 1161 行）。没有口径的数字必然被拿去互相比，那是错的用法。
    """
    got = report_landing_reading(_store(tmp_path, d_calls=1))
    assert "caliber" in got, "读数没带口径 ⇒ 读的人只能猜它数的是什么"
    caliber = got["caliber"]
    assert "tasks" in caliber and "events" in caliber, caliber
    assert "重放" in caliber and "不许互相比" in caliber, caliber

    class _Broken:
        def rows(self, table):
            raise OSError("表读不出来")

    assert "caliber" in report_landing_reading(_Broken()), "读不成的那一格也要带口径"
