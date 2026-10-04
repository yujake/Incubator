# -*- coding: utf-8 -*-
"""判据（`draft/37` §133）：「判数学的进度，不判台账的厚度」。

用户口径（逐字）：

> 数值实验时间长是正常的，我们团队之前做那篇论文时也做了不少数值实验，
> 但后面逐渐发现模式优化枚举策略才把时间压下去的

它推翻了我第一版的想法（给实验设硬上限、连续超时就不让跑）。正确的做法是：
「慢可以，但每次实验都要留下可比较的读数」（搜到哪儿 / 花了多少 / 用什么策略），
而"进展"的定义是「界往前推」或「同一界更快」——外加「把模式写成可检验的猜想」。

这一组钉四件事：
1. 超时/崩溃的实验也留下"搜到哪儿"（`PROGRESS:` 行 → `observations.progress`）；
2. 结构化结论里的 `bound`/`strategy`/`scaling` 落进 `observations`，`bound` 同时落
   `experiments.search_bound`；
3. E 会「逐条比给上一次看」：同 claim 的历史（界/耗时/策略/脚本），同形就明说"没有推进"；
4. 两条新验收档读得出来：`search_frontier_rows`（有界记录的 claim 数）与
   `enumeration_optimization_rows`（界更大而耗时不多，或界相同而耗时降到 80% 以下）。
"""
from __future__ import annotations

import pathlib

from agentflow import closing as CL
from agentflow.agent_e import AgentE
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store]:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    (ws / "scripts").mkdir()
    st = Store(ws)
    st.init()
    return ws, st


def test_a_timed_out_experiment_still_records_where_it_got_to(tmp_path: pathlib.Path):
    """超时不等于没有读数：`PROGRESS:` 行留下"最后完成到哪儿"。"""
    ws, st = _ws(tmp_path)
    (ws / "scripts" / "slow.py").write_text(
        "import json, time\n"
        "for n in (8, 9, 10):\n"
        "    print('PROGRESS: ' + json.dumps({'n': n, 'sec': 0.1 * n}), flush=True)\n"
        "time.sleep(30)\n", encoding="utf-8")
    out = AgentE(st, workspace_root=ws).run_experiment(
        "慢枚举", "K1", "scripts/slow.py", method="numeric", timeout=1)
    assert out["result"] == "inconclusive", out
    row = st.rows("experiments")[0]
    progress = (row.get("observations") or {}).get("progress")
    assert progress and progress[-1]["n"] == 10, row.get("observations")
    assert "进度读数" in str(row.get("notes")), row.get("notes")


def test_the_structured_search_readings_land_on_the_row(tmp_path: pathlib.Path):
    """`bound`/`strategy`/`scaling` 从结构化结论落进 observations，`bound` 同时落 search_bound。"""
    ws, st = _ws(tmp_path)
    (ws / "scripts" / "fast.py").write_text(
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result': 'supports',\n"
        "    'strategy': 'canonical form + iso rejection', 'bound': {'n': 12},\n"
        "    'scaling': [{'n': 10, 'sec': 3.0}, {'n': 12, 'sec': 40.0}]}))\n", encoding="utf-8")
    AgentE(st, workspace_root=ws).run_experiment(
        "快枚举", "K2", "scripts/fast.py", method="numeric", timeout=60)
    row = st.rows("experiments")[0]
    obs = row.get("observations") or {}
    assert obs.get("strategy") == "canonical form + iso rejection", obs
    assert obs.get("scaling") and obs["scaling"][-1]["n"] == 12, obs
    assert row.get("search_bound") == {"n": 12}, row.get("search_bound")


def test_the_engineer_tells_the_model_when_an_attempt_did_not_advance(tmp_path: pathlib.Path):
    """E 逐条比给上一次看：同形就说"没有推进"，换了脚本/界/策略就说"有推进"。"""
    ws, st = _ws(tmp_path)
    (ws / "scripts" / "same.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    (ws / "scripts" / "better.py").write_text(
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result': 'supports', 'strategy': 'canonical form',\n"
        "                                     'bound': {'n': 12}}))\n", encoding="utf-8")
    e = AgentE(st, workspace_root=ws)
    e.run_experiment("同一 claim", "K3", "scripts/same.py", method="numeric", timeout=1)
    again = e.run_experiment("同一 claim", "K3", "scripts/same.py", method="numeric", timeout=1)
    line = next(l for l in str(again["notes"]).splitlines() if l.startswith("[progress]"))
    assert "同形" in line, line

    moved = e.run_experiment("同一 claim", "K3", "scripts/better.py", method="numeric", timeout=30)
    line2 = next(l for l in str(moved["notes"]).splitlines() if l.startswith("[progress]"))
    assert "不同形" in line2 and "脚本换了" in line2, line2


def test_the_two_search_progress_legs_are_readable(tmp_path: pathlib.Path):
    """新验收档：`search_frontier_rows` 与 `enumeration_optimization_rows`。"""
    ws, st = _ws(tmp_path)
    (ws / "scripts" / "one.py").write_text(
        "import json, time\n"
        "print('REPRO_RESULT: ' + json.dumps({'result': 'supports', 'bound': {'n': 10}}))\n"
        "time.sleep(0.1)\n", encoding="utf-8")
    (ws / "scripts" / "two.py").write_text(
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result': 'supports', 'strategy': 'canonical form',\n"
        "                                     'bound': {'n': 12}}))\n", encoding="utf-8")
    e = AgentE(st, workspace_root=ws)
    assert CL._leg_reading(st, "search_frontier_rows", ws)[0] == 0
    e.run_experiment("界", "K4", "scripts/one.py", method="numeric", timeout=30)
    got1, detail1 = CL._leg_reading(st, "search_frontier_rows", ws)
    assert got1 == 1 and detail1["claim_keys"] == ["K4"], detail1
    # 更大界、耗时不多 ⇒ 算一次"枚举策略优化"
    e.run_experiment("界", "K4", "scripts/two.py", method="numeric", timeout=30)
    got2, detail2 = CL._leg_reading(st, "enumeration_optimization_rows", ws)
    assert got2 == 1, detail2
    assert detail2["optimized"][0]["kind"] == "bigger_in_no_more_time", detail2
