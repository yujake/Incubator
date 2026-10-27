# -*- coding: utf-8 -*-
"""Q29：`_ack_stop_notice` 不再自己判"是不是已经 done"，改为照状态机的判词。

## 这一件修的是什么

`agent_loop._ack_stop_notice` 里有一句 `if row["item_state"] == "done": return ""`：
它是"同一终态重复设置"在状态机外面的第四份实现。Q24 已经把这条判断收进
`Conductor._set_item` + `Conductor.ITEM_MOVES`（`done → done` 判 `same` ⇒ `changed=False`、
零写入），并删掉了另外三份（`_settle_if_informational` 的两行、`ack_items` 的
`already_done` 入口支）。剩下这一份同样该删：幂等命中不归循环这一层判。

改后：这一层只把现态交给状态机的判词读数（`Conductor.item_move` —— 它就是
`_set_item` 内部唯一的判决来源），拿到 `same` 就什么都不做（不写落痕、不追加事件、
不报错）；不在 `same` 上才推 `close_item` 并落 `stop-acked:<子代号>@<时间>`。

为什么消费的是 `item_move` 而不是 `_set_item` 的第三格 `changed`：`close_item` 只回
`(state, why)`（第三格在 conductor 里被丢掉），而 `ack_items` / `_set_item` 直接出现在
`agent_loop.py` 里会撞上 `test_ack_is_the_hand_and_retire_needs_a_clean_board.py` 的
落点白名单（`_WRITE_SITES`：循环这一层只许 `close_item` / `mark_item_seen`）。
`item_move` 是那张迁移图的公开读数，`same` 与 `changed=False` 是同一件事（Q24 的
`_set_item` 第 3 条：`same` ⇒ 零写入、返回 `(state, "", False)`）。

## 这一份钉住的判据

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) 第一次 ack ⇒ 落痕一条 + 真迁移 | 正控：`seen → done` 走真迁移，`acked_at` 有值 | 不适用（改前就绿） |
| b) 再 ack ⇒ 不报错、落痕仍一条、判决来自状态机 | 幂等命中由 `item_move` 的 `same` 判出来，不是循环自己读 `item_state` 短路 | 改前：自己读 `item_state` 短路，状态机一次都没被问到 ⇒ ④⑤ 两格红 |
| b2) `same` 与 `changed=False` 对拍 | 图判词与写入是同一件事（业主 2026-10-26 附加）：图一改，这一条先红 | 不适用（守的是不变式，不是那一句） |
| c) 反真空：把判决打桩回"自己读 item_state" | "不报错 / 落痕只一条 / 零写入"三条会被老实现骗过（红被隐藏）；④⑤ 两格不该被骗 | 不适用（桩就是改前那一句） |
| d) 读数：`stop_edge_readings.acked_at` | 落痕语义不变：读的就是父那一行的 `stop-acked:` 落痕，且不重复写 | 不适用 |

三条口径：空串 ＝ 这一拍没话说（幂等命中也在这一档）；非空 ＝ 真的 ack 了一次；
`same` ⇔ `_set_item` 的 `changed=False`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

SID = "q29"
ACKED_PREFIX = "stop-acked:"


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """工作区 + 主控 + 一个在飞的子 + 一条沿边下发的停止通知。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    top = cond.open_top_level_run("M", "顶趟")
    child = cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": top, "depth": 2, "input_key": "q29@d", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "",
        "detail": "一个子代理", "error": None, "started_at": "2026-10-26T00:00:00+08:00",
        "ended_at": None, "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")
    got = cond.notify_children_of_stop(top, reason="user", by="M")
    assert got["checked"] is True and len(got["notified"]) == 1, got
    item = str(got["notified"][0]["item_id"])
    loop = _loop(ws, cond, task_id=child, parent=top)
    return {"st": st, "cond": cond, "ws": ws, "top": top, "child": child,
            "item": item, "loop": loop}


def _loop(ws: pathlib.Path, cond: Conductor, *, task_id: str, parent: str) -> AgentLoop:
    loop = AgentLoop(role="D", session_root=ws, registry=None, seam=None, conductor=cond,
                     sid=SID, store=None, max_steps=1, auto_secretary=False)
    loop.my_task_id = task_id
    loop.parent_task_id = parent
    return loop


def _row(st: Store, task_id: str) -> dict:
    return next(r for r in st.rows("tasks") if str(r.get("task_id")) == str(task_id))


def _row_bytes(st: Store, task_id: str) -> str:
    """一行的字节（键序归一）：比"改了没有"比比字段逐个比更严。"""
    return json.dumps(_row(st, task_id), ensure_ascii=False, sort_keys=True, default=str)


def _events(st: Store) -> list[dict]:
    return list(st.read_events())


def _done_events(st: Store, item: str) -> list[dict]:
    """这一条板项"推到 done"的那几条事件（一条真迁移 = 一条，幂等命中 = 零条）。"""
    return [e for e in _events(st)
            if str((e.get("row") or {}).get("task_id") or "") == str(item)
            and str((e.get("row") or {}).get("item_state") or "") == "done"]


def _traces(st: Store, top: str) -> list[str]:
    """父那一行上的 `stop-acked:<子代号>@<时间>` 落痕（`acked_at` 读的就是它）。"""
    return [str(x) for x in (_row(st, top).get("inputs") or [])
            if str(x).startswith(ACKED_PREFIX)]


def _first_ack(env: dict[str, Any]) -> str:
    """按生产的次序把通知项读到 `seen`，再替这一趟 ack 一次（返回那句读数）。"""
    cond, item, child, loop = env["cond"], env["item"], env["child"], env["loop"]
    state, why = cond.mark_item_seen(item, by_task_id=child, step=1)
    assert (state, why) == ("seen", ""), (state, why)
    return loop._ack_stop_notice(item, 1)


# ====================================================================== a) 正控
def test_a_the_first_ack_writes_the_trace_once(tmp_path: pathlib.Path) -> None:
    """a) 正控：第一次 ack ⇒ 真迁移一条（`changed=True`）、落痕一条、`acked_at` 有值。"""
    env = _env(tmp_path)
    cond, st, item, top = env["cond"], env["st"], env["item"], env["top"]
    assert _traces(st, top) == [], "夹具前提：下发那一步不该先写 ack 落痕"
    assert _done_events(st, item) == [], "夹具前提：通知项还没被 ack"

    note = _first_ack(env)

    assert note != "", "第一次 ack 没留下读数（框架替它 ack 这条手没生效）"
    assert len(_traces(st, top)) == 1, _traces(st, top)
    # changed=True：`seen → done` 在迁移图里是 forward，`_set_item` 第 4 条会真写一行 + 记一笔。
    assert Conductor.item_move("seen", "done") == Conductor.ITEM_MOVE_FORWARD
    assert len(_done_events(st, item)) == 1, (
        f"真迁移该恰好记一条 done 事件（changed=True），"
        f"实际 {len(_done_events(st, item))} 条")
    row = _row(st, item)
    assert (str(row.get("item_state") or ""), str(row.get("item_close") or "")) == (
        "done", "acked"), row
    edges = cond.stop_edge_readings(top)["edges"]
    assert edges and edges[0]["acked_at"], edges


# ====================================================================== b) 幂等命中
def _second_ack_problems(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """b 的判据本体：第二拍 ack 必须"静默 + 零写入 + 判决来自状态机"。

    返回问题清单（空 ＝ 通过）。抽成函数是为了让 c 能把它打桩之后复用同一套断言 ——
    否则 c 会变成"另写一份更松的判据"。
    """
    cond, st, item, top, loop = (env["cond"], env["st"], env["item"], env["top"],
                                 env["loop"])
    problems: list[str] = []
    traces_before = _traces(st, top)
    row_before = _row_bytes(st, item)
    events_before = len(_events(st))

    # 判词读数：第二拍有没有真的走进状态机（这是"消费了状态机"的直接证据 ——
    # 改前那一句短路会让这张表一条都没有）。
    calls: list[tuple[str, str, str]] = []
    real_move = Conductor.item_move

    def _recording(cur: str, state: str) -> str:
        verdict = real_move(cur, state)
        calls.append((cur, state, verdict))
        return verdict

    monkeypatch.setattr(Conductor, "item_move", staticmethod(_recording))

    # ① 不报错：幂等命中在这一层就是"这一拍没话说"。
    note = loop._ack_stop_notice(item, 2)
    if note != "":
        problems.append(f"第二拍 ack 报了话（幂等命中应静默）：{note!r}")
    # ② 落痕不重复写。
    if _traces(st, top) != traces_before:
        problems.append(f"落痕被重复写了：{traces_before} → {_traces(st, top)}")
    # ③ 零写入：行、事件数都不许变（`changed=False` 的机器形态）。
    if _row_bytes(st, item) != row_before:
        problems.append("幂等命中却改写了那一行")
    if len(_events(st)) != events_before:
        problems.append(f"幂等命中却多了 {len(_events(st)) - events_before} 条事件")
    # ④ 判词读数：第二拍问过状态机，而且它答的是 `done → done = same`。
    asked = [c for c in calls if (c[0], c[1]) == ("done", "done")]
    if not asked:
        problems.append("第二拍没有问状态机（`item_move` 没被调用一次）⇒ 这一拍的静默"
                        "不是状态机的判词，是自己读 item_state 短路")
    elif asked[0][2] != Conductor.ITEM_MOVE_SAME:
        problems.append(f"状态机对 done→done 的判词不是 same（拿到 {asked[0][2]!r}）")

    # ⑤ 判别：这一拍的静默确实是状态机判出来的，不是自己读了 item_state 短路。
    #    桩是谎话（图说 done→done 还能往前），测的是"谁在判"：循环若照图走，就会去推
    #    close_item 并报一句话；若仍然静默，说明它压根没问状态机。
    def _forward_on_done(cur: str, state: str) -> str:
        if (cur, state) == ("done", "done"):
            return Conductor.ITEM_MOVE_FORWARD
        return real_move(cur, state)

    monkeypatch.setattr(Conductor, "item_move", staticmethod(_forward_on_done))
    followed = loop._ack_stop_notice(item, 3)
    if followed == "":
        problems.append("把 done→done 的判词打桩成 forward 之后这一拍仍然静默 ⇒ "
                        "它不是照状态机的判词，而是自己读 item_state 短路")
    return problems


def test_b_the_second_ack_comes_from_the_state_machine(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b) 第二拍 ack：不报错、落痕仍一条、零写入，且判决来自状态机（改前红）。"""
    env = _env(tmp_path)
    assert _first_ack(env) != ""
    # 调用点契约（`agent_loop.py`：`ack_note = self._ack_stop_notice(item_id, step)`，
    # 紧接着 `if ack_note: run.notes.append(ack_note)`）：空串 ⇒ 这一拍不往 run.notes
    # 里塞一句假的"已 ack"。这是删掉短路之后最容易漏出来的那一条。
    run_notes: list[str] = []
    second = env["loop"]._ack_stop_notice(env["item"], 2)
    if second:
        run_notes.append(second)
    assert run_notes == [], f"第二拍往 run.notes 里塞了一句假的收口读数：{run_notes}"
    problems = _second_ack_problems(env, monkeypatch)
    assert problems == [], problems


def test_b2_the_verdict_same_and_the_write_agree(tmp_path: pathlib.Path) -> None:
    """b 的接续判据：在同一夹具上把 `same` 与 `changed=False` 对拍（业主 2026-10-26）。

    三格必须同时成立：`item_move("done", "done") == same`、`close_item` 对同一项回
    `("done", "")`、而那一笔零写入（行、done 事件、板上计数一个字节都不动）。
    于是"same ⇔ changed=False"不是谁在注释里说的一句话，而是判据：将来谁把迁移图改了
    而 `_ack_stop_notice` 那一句没跟上，这条先红（它照图判，图一变它就静默走偏）。
    """
    env = _env(tmp_path)
    assert _first_ack(env) != ""
    cond, st, item, child = env["cond"], env["st"], env["item"], env["child"]

    assert Conductor.item_move("done", "done") == Conductor.ITEM_MOVE_SAME, (
        "迁移图里 done→done 不是 same ⇒ `_ack_stop_notice` 照图判的那一句会误走 forward")
    row_before = _row_bytes(st, item)
    done_before = len(_done_events(st, item))
    reads_before = dict(cond.board_readings().get("by_state") or {})

    state, why = cond.close_item(item, close="acked", by_task_id=child)
    assert (state, why) == ("done", ""), (state, why)
    assert _row_bytes(st, item) == row_before, "`same` 那一支却写了行"
    assert len(_done_events(st, item)) == done_before, "`same` 那一支却记了事件"
    assert dict(cond.board_readings().get("by_state") or {}) == reads_before, (
        "`same` 那一支却动了板上计数")

    # `changed=False` 的字面读数：同一格由状态机自己给（Q24 的 `_set_item` 第 3 条）。
    _state, _why, changed = cond._set_item(item, state="done", close="acked",
                                           by_task_id=child)
    assert changed is False, f"同一终态重复设置报了 changed={changed!r}"


# ====================================================================== c) 反真空
def test_c_stubbing_the_verdict_back_to_a_self_read_hides_the_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c) 反真空：把判决打桩回"自己读 item_state" ⇒ b 的静默三条照样绿（红被隐藏）。

    也就是说：只看"不报错 / 落痕只一条 / 零写入"这三条，改前那一句
    `if item_state == "done": return ""` 与改后的"照状态机判词"分不开。所以 b 必须
    带判别那两格（④ 判词读数、⑤ 照图走的因果）；这一条证明它们不是摆设 —— 桩一打
    回去，两格当场红。
    """
    env = _env(tmp_path)
    assert _first_ack(env) != ""
    cond, st, item, top = env["cond"], env["st"], env["item"], env["top"]

    real_ack = AgentLoop._ack_stop_notice

    def _self_read(self: AgentLoop, item_id: str, step: int) -> str:
        """改前那一份形状：自己读 item_state，命中就直接短路（不问状态机）。"""
        row = self.conductor._task(item_id) or {}
        if str(row.get("item_state") or "") == "done":
            return ""
        return real_ack(self, item_id, step)

    monkeypatch.setattr(AgentLoop, "_ack_stop_notice", _self_read)

    # ① 老实现打得过的三条：静默、落痕只一条、零写入 —— 红被隐藏。
    traces_before = _traces(st, top)
    row_before = _row_bytes(st, item)
    events_before = len(_events(st))
    assert env["loop"]._ack_stop_notice(item, 2) == ""
    assert _traces(st, top) == traces_before, "桩不该写落痕"
    assert _row_bytes(st, item) == row_before, "桩不该改行"
    assert len(_events(st)) == events_before, "桩不该记事件"
    assert cond.stop_edge_readings(top)["edges"][0]["acked_at"], "读数仍该是那条落痕"

    # ② 判别那两格必红：同一个桩下，b 的判据本体必须报出问题。
    problems = _second_ack_problems(env, monkeypatch)
    assert problems, ("把判决打桩回自己读 item_state，b 却仍然绿 ⇒ b 分不出"
                      "『幂等命中』与『自己短路』")
    assert any("没有问状态机" in p for p in problems), problems
    assert any("打桩成 forward" in p for p in problems), problems


# ====================================================================== d) 读数
def test_d_the_reading_is_the_trace_and_stays_one(tmp_path: pathlib.Path) -> None:
    """d) 读数：`stop_edge_readings.acked_at` 读的就是那条落痕，且再 ack 不改动它。"""
    env = _env(tmp_path)
    assert _first_ack(env) != ""
    cond, st, item, top, loop = (env["cond"], env["st"], env["item"], env["top"],
                                 env["loop"])
    readings = cond.stop_edge_readings(top)
    assert readings["checked"] is True, readings
    edge = readings["edges"][0]
    assert edge["acked_at"], edge
    assert edge["item_state"] == "done", edge
    assert _traces(st, top)[0].startswith(f"{ACKED_PREFIX}{env['child']}@"), _traces(st, top)

    # 幂等：再 ack 一次，边读数逐字不变（落痕的时间戳也不许被重写）。
    before = dict(edge)
    assert loop._ack_stop_notice(item, 2) == ""
    assert cond.stop_edge_readings(top)["edges"][0] == before, (
        "再 ack 一次改了边读数 —— 落痕被重写或被弄丢了")
