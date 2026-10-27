# -*- coding: utf-8 -*-
"""Q18：板项行不是"在跑的子代理"（业主 2026-10-26）。

## 真机读数（`projects/mp3-r3`，已核）

48 行 tasks = 18 代理行（全 `done`，17×ok + 1×no_result）+ 30 板项行（28 `notice` + 2 `message`，
`status` 恒为 `pending`）。代理行最后一条 `ended_at=22:36:37`，比顶趟收行（22:37:50）早 73 秒
⇒ 那一局退出时台账里一个在跑的子都没有。而顶趟行的 `detail` 逐字写着
「顶趟收工：final_refused；闭环提醒 5 条（running 5 条…）」—— 那 5 条是板项行
（`MAX_REMINDERS=5` 截断），读数在说谎。

本机复现（同一份 48 行、零模型调用）：`inbox_todos()` 给出 `count=20`（30 条被 `limit=20`
再截一次）、`states=['running']`、`by_state={'running': 5}`，收工 detail 逐字
「；闭环提醒 5 条（running 5 条；unclaimed=没人接手，pending/running=没有终态）」。

## 这一份钉住的 4+1 件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a | 30 条板项 + 0 在跑代理 ⇒ `running=0 / items=30`，收工 detail 不含 `running` 字样、两栏各自出现 | 改前 `running=30`（截到 5），detail 写 `running 5 条` |
| b | 2 条真在跑的代理 + 3 条板项 ⇒ `2/3`，两栏都点名编号 | 改前两轴混成一句，5 条里分不出谁是子、谁是板项 |
| c | 正控：板项被收口（`done`）之后 `items` 减 1、`running` 不变 | 改前板项永远算 `running`，"收口"对读数没有任何影响 |
| d | 反真空：把"只数代理行"那一步打桩成旧行为 ⇒ a 必红 | 不适用（它守的是 a 不是真空形态） |
| e | 截断只作用于待办项：7 条板项 + 2 代理 ⇒ 代理全列、板项点名 5 条 + `还有 2 条没点名` | 改前两栏一起被 `MAX_REMINDERS` 截到 5，且没有"还有几条"的读数 |

判据本体写成 `_x_problems()` 返回问题清单（同 `test_information_items_are_acked_when_read.py`
的形态）：改前红的输出就是那份清单的逐字内容，而不是一个断言下标。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

import agentflow.secretary as SEC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

TS = "2026-10-26T00:00:00+08:00"


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """真 Store + 真 Conductor + 真 Secretary + 一条顶趟行（不手写脏盘）。"""
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    sec = SEC.Secretary("M", root=root, store=st)
    cond.secretary = sec                       # 生产里由 agent_loop 接上；这里显式接
    owner = str(cond.open_top_level_run("M", "Q18：板项不是在跑的子"))
    return {"store": st, "cond": cond, "sec": sec, "owner": owner}


def _board(env: dict[str, Any], n: int) -> list[str]:
    """`n` 条挂在顶趟行名下的板项（`notice` / `message` 交替：两种都要被覆盖）。

    形态与生产一致：`open_item` 写死 `status="pending"`，`expects="ack"`（信息型）。
    """
    out: list[str] = []
    for i in range(n):
        kind = ("notice", "message")[i % 2]
        out.append(str(env["cond"].open_item(
            kind=kind, role="M", expects="ack", action=kind,
            summary=f"{i} 号板项", called_by="M",
            parent_task_id=env["owner"], depth=2, input_key=f"q18:{kind}:{i}")))
    return out


def _agent(env: dict[str, Any], role: str = "A") -> str:
    """一条真在跑的代理行（`kind` 为空、`status="running"`、有父）。"""
    return str(env["cond"]._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": env["owner"], "depth": 2, "input_key": f"q18:agent:{role}",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "", "detail": "真在跑的子", "error": None,
        "started_at": TS, "ended_at": None, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="start:A.run_once"))


def _row(env: dict[str, Any], tid: str) -> dict:
    return next(r for r in env["store"].rows("tasks") if str(r.get("task_id")) == tid)


def _finish(env: dict[str, Any]) -> str:
    """收掉顶趟行，返回它的 `detail`（收工那一句唯一的落点）。"""
    env["cond"].finish_top_level_run(env["owner"], stop_reason="final")
    return str(_row(env, env["owner"]).get("detail") or "")


def _columns(got: dict, problems: list[str], *, where: str) -> tuple[dict, dict]:
    """取出两栏；缺栏本身就是问题（改前没有这两栏）。"""
    for key in ("running_agents", "pending_items"):
        if key not in got:
            problems.append(f"{where} 的读数里没有 {key} 这一栏（两栏是 Q18 的交付形态）："
                            f"{sorted(got)}")
    return (dict(got.get("running_agents") or {}),
            dict(got.get("pending_items") or {}))


# ====================================================================== a) 30 条板项
def _a_problems(tmp_path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    env = _env(tmp_path)
    _board(env, 30)
    got = env["sec"].inbox_todos()
    run_col, item_col = _columns(got, problems, where="30 条板项")
    if int(run_col.get("count") or 0) != 0:
        problems.append(f"30 条板项 + 0 在跑代理，在跑的子代理数却是 "
                        f"{run_col.get('count')!r}（改前读数：30 条板项全部被算成 running）")
    if [str(x) for x in (run_col.get("ids") or ())]:
        problems.append(f"在跑的子代理编号不该有东西：{run_col.get('ids')}")
    if int(item_col.get("count") or 0) != 30:
        problems.append(f"待办项应为 30 条，收到 {item_col.get('count')!r}：{item_col}")
    if len([str(x) for x in (item_col.get("ids") or ())]) != 30:
        problems.append(f"待办项要点名 30 个编号（数量 + 编号两样都要）：{item_col}")
    truncated = dict(got.get("truncated") or {})
    if int(truncated.get("total") or 0) != 30 or int(truncated.get("shown") or 0) != 20:
        problems.append(f"`limit=20` 的截断必须显式（shown=20 / total=30）：{truncated}")
    if int(truncated.get("more") or 0) != 10:
        problems.append(f"截断量要写成 more=10：{truncated}")

    detail = _finish(env)
    if "running" in detail:
        problems.append(f"收工 detail 里还有 running 字样（改前逐字：「；闭环提醒 5 条"
                        f"（running 5 条；unclaimed=没人接手，pending/running=没有终态）」）：{detail}")
    if "在跑的子代理 0 个" not in detail:
        problems.append(f"detail 没写「在跑的子代理 0 个」这一栏：{detail}")
    if "待办项 30 条" not in detail:
        problems.append(f"detail 没写「待办项 30 条」这一栏：{detail}")
    if "还有 25 条没点名" not in detail:
        problems.append(f"detail 里 30 条只点名 5 条，必须写「还有 25 条没点名」：{detail}")
    stats_col = dict(env["cond"].stats().get("closure_reminders") or {})
    if int(dict(stats_col.get("running_agents") or {}).get("count") or 0) != 0:
        problems.append(f"`stats.closure_reminders` 的在跑栏也要是 0：{stats_col}")
    return problems


def test_a_thirty_board_items_are_not_running_children(tmp_path: pathlib.Path) -> None:
    """a) 30 条板项 + 0 在跑代理 ⇒ running=0 / items=30（改前红：running=30 截到 5）。"""
    problems = _a_problems(tmp_path)
    assert problems == [], problems


# ====================================================================== b) 两栏各自点名
def _b_problems(tmp_path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    env = _env(tmp_path)
    agents = [_agent(env, "A"), _agent(env, "B")]
    items = _board(env, 3)
    got = env["sec"].inbox_todos()
    run_col, item_col = _columns(got, problems, where="2 代理 + 3 板项")
    if int(run_col.get("count") or 0) != 2:
        problems.append(f"在跑的子代理应为 2 个，收到 {run_col.get('count')!r}：{run_col}")
    if [str(x) for x in (run_col.get("ids") or ())] != agents:
        problems.append(f"在跑栏要点名这两条代理行的编号 {agents}：{run_col}")
    if int(item_col.get("count") or 0) != 3:
        problems.append(f"待办项应为 3 条，收到 {item_col.get('count')!r}：{item_col}")
    if [str(x) for x in (item_col.get("ids") or ())] != items:
        problems.append(f"待办栏要点名这三条板项的编号 {items}：{item_col}")

    detail = _finish(env)
    for want in agents:
        if want not in detail:
            problems.append(f"detail 没点名在跑的子代理 {want}：{detail}")
    for want in items:
        if want not in detail:
            problems.append(f"detail 没点名待办项 {want}：{detail}")
    for want in ("在跑的子代理 2 个", "待办项 3 条"):
        if want not in detail:
            problems.append(f"detail 缺「{want}」：{detail}")
    if "running" in detail:
        problems.append(f"detail 里还有 running 字样：{detail}")

    stats = dict(env["cond"].stats().get("closure_reminders") or {})
    reminded = [dict(x) for x in (stats.get("reminded") or ())]
    axes: dict[str, int] = {}
    for one in reminded:
        axes[str(one.get("axis") or "")] = axes.get(str(one.get("axis") or ""), 0) + 1
    if axes.get("agent") != 2 or axes.get("item_open") != 3:
        problems.append(f"每条提醒要带轴（2 条代理 + 3 条待办），收到 {axes}：{reminded}")
    if dict(stats.get("by_state") or {}) != {"pending": 3}:
        problems.append(f"by_state 只统计待办项（在跑的子代理是另一栏）："
                        f"{stats.get('by_state')}")
    return problems


def test_b_the_two_columns_name_their_own_rows(tmp_path: pathlib.Path) -> None:
    """b) 2 条真在跑的代理 + 3 条板项 ⇒ 2/3，且两栏各自点名编号。"""
    problems = _b_problems(tmp_path)
    assert problems == [], problems


# ====================================================================== c) 收口正控
def _c_problems(tmp_path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    env = _env(tmp_path)
    _agent(env)
    keep, close = _board(env, 2)
    before_run, before_item = _columns(env["sec"].inbox_todos(), problems, where="收口前")
    state, why = env["cond"].mark_item_seen(close, by_task_id=env["owner"], step=1)
    if not state:
        problems.append(f"板项 {close} 渲染那一拍没收口：{why}")
    row = _row(env, close)
    if (str(row.get("item_state")), str(row.get("item_close"))) != ("done", "acked"):
        problems.append(f"信息型板项渲染即收口，收到 "
                        f"{row.get('item_state')!r}/{row.get('item_close')!r}")
    after_run, after_item = _columns(env["sec"].inbox_todos(), problems, where="收口后")
    if int(before_item.get("count") or 0) != 2 or int(after_item.get("count") or 0) != 1:
        problems.append(f"收口一条之后待办项应当 2→1，收到 "
                        f"{before_item.get('count')!r}→{after_item.get('count')!r}")
    if close in [str(x) for x in (after_item.get("ids") or ())]:
        problems.append(f"已收口的板项 {close} 不许还挂在待办栏里：{after_item.get('ids')}")
    if str(keep) not in [str(x) for x in (after_item.get("ids") or ())]:
        problems.append(f"没动过的板项 {keep} 还应当在待办栏里：{after_item.get('ids')}")
    if int(before_run.get("count") or 0) != 1 or int(after_run.get("count") or 0) != 1:
        problems.append(f"收口一条板项不许动在跑栏（应当恒 1）："
                        f"{before_run.get('count')!r}→{after_run.get('count')!r}")
    got = env["sec"].inbox_todos()
    if int(got.get("excluded_item_closed") or 0) != 1:
        problems.append(f"已收口的板项要落进显式读数 excluded_item_closed=1：{got}")
    return problems


def test_c_closing_a_board_item_only_moves_the_pending_column(
        tmp_path: pathlib.Path) -> None:
    """c) 正控：板项收口之后 items 减 1、running 不变（改前：收口对读数毫无影响）。"""
    problems = _c_problems(tmp_path)
    assert problems == [], problems


# ====================================================================== e) 截断只作用于待办项
def _e_problems(tmp_path: pathlib.Path) -> list[str]:
    problems: list[str] = []
    env = _env(tmp_path)
    agents = [_agent(env, "A"), _agent(env, "B")]
    _board(env, 7)
    got = env["sec"].inbox_todos()
    run_col, item_col = _columns(got, problems, where="2 代理 + 7 板项")
    if [str(x) for x in (run_col.get("ids") or ())] != agents:
        problems.append(f"在跑栏永不截断（2 条必须全列）：{run_col}")
    if len([str(x) for x in (item_col.get("ids") or ())]) != 7:
        problems.append(f"待办栏的编号要给真数 7 个（点名另算）：{item_col}")
    # `limit=20` 这一档：9 行没触顶，截断读数要明说 more=0（不许没有这一格）。
    flat = dict(got.get("truncated") or {})
    if (int(flat.get("shown") or 0), int(flat.get("total") or 0),
            int(flat.get("more") or 0)) != (9, 9, 0):
        problems.append(f"`limit=20` 的截断读数要显式 shown=9 / total=9 / more=0：{flat}")
    # `MAX_REMINDERS=5` 这一档：只截待办栏的对点名单。
    reading = env["sec"].closure_reading()
    truncated = dict((reading.get("truncated") or {}).get("pending_items") or {})
    if (int(truncated.get("shown") or 0), int(truncated.get("total") or 0),
            int(truncated.get("more") or 0)) != (5, 7, 2):
        problems.append(f"待办栏点名截断要显式 shown=5 / total=7 / more=2：{truncated}")
    if int(dict((reading.get("truncated") or {}).get("running_agents") or {})
           .get("more") or 0) != 0:
        problems.append(f"在跑栏的 more 必须是 0（它不截）：{reading.get('truncated')}")

    detail = _finish(env)
    for want in agents:
        if want not in detail:
            problems.append(f"detail 没点名在跑的 {want}：{detail}")
    if "还有 2 条没点名" not in detail:
        problems.append(f"待办栏 7 条只点名 5 条，必须写「还有 2 条没点名」：{detail}")
    stats = dict(env["cond"].stats().get("closure_reminders") or {})
    reminded = [dict(x) for x in (stats.get("reminded") or ())]
    agent_hits = [x for x in reminded if str(x.get("axis")) == "agent"]
    item_hits = [x for x in reminded if str(x.get("axis")) == "item_open"]
    if len(agent_hits) != 2:
        problems.append(f"在跑的子代理要全列（2 条），收到 {len(agent_hits)}：{reminded}")
    if len(item_hits) != 5:
        problems.append(f"待办项点名上限是 MAX_REMINDERS=5，收到 {len(item_hits)}：{reminded}")
    return problems


def test_e_the_reminder_cap_only_truncates_the_pending_column(
        tmp_path: pathlib.Path) -> None:
    """e) 截断只作用于待办项；在跑的子代理全列（改前：两栏一起被截到 5）。"""
    problems = _e_problems(tmp_path)
    assert problems == [], problems


# ====================================================================== d) 反真空
def _old_axis(row: dict) -> str:
    """"只数代理行"那一步的旧行为（2026-10-08 之前的形态）：不看 kind，只看 status。

    取值用字面量（`"agent"` / `"other"`）而不是模块常量：这一条要能在改前的树上
    也构造得出来，否则它的"红"证明不了判据在看分轴这件事。
    """
    if str(row.get("action") or "") == "run":
        return "other"
    if str(row.get("status") or "") in ("pending", "running"):
        return "agent"
    return "other"


def test_d_stubbing_the_axis_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：把分轴判据打桩成旧行为 ⇒ a 必红，且红在"板项被数成在跑的子"上。

    打桩的落点 2026-10-26 Q27 起是 `secretary.is_live_agent`（那一问才判"在不在跑"；
    `row_axis` 只管轴）—— 旧桩打在 `task_row_axis` 上，拆分之后它不再被收件箱读。
    """
    # 基线：同一份判据在不打桩时必须绿（否则下面的红证明不了任何事）
    baseline = _a_problems(tmp_path / "a0")
    assert baseline == [], baseline

    monkeypatch.setattr(SEC, "is_live_agent", lambda row: _old_axis(row) == "agent")
    a = _a_problems(tmp_path / "a1")
    assert a, "把分轴判据打桩成旧行为，(a) 却仍然绿 ⇒ 这条判据没在看分轴这件事"
    assert any("在跑的子代理" in x and "30" in x for x in a), a
    assert any("待办项应为 30 条" in x for x in a), a
