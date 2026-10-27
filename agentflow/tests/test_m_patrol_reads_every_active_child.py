# -*- coding: utf-8 -*-
"""M 的自动审阅工具（L1）：一次拿全每个活跃子代理的状态，M 只负责说「过」或给指导意见。

业主原话（唯一权威，2026-10-27 逐字）：

    「给M设计自动审阅工具，要求能遍历每个活跃子代理（在飞/待机）且按名册深度优先遍历，
      返回绝对编码、按名册的绝对编码链、在执行的任务、任务看板（未做完的，并标记现在在
      做哪项）、计时器列表（等谁或等待时长+purpose+已等待时间）。M要做的只是根据这些
      信息对逐个活跃子代理给出"过"、指导意见（行为干预），且M有更细化的单独审阅工具
      （审阅工具提供名册树，M输入合法的绝对编码，工具返回上述全部信息，M给出"过"或
      指导意见（行为干预））」

以及业主给的病根：「M 不起巡查是因为太繁琐」。所以这一组判据量的不是"能不能查到"，
而是"一次调用是否把 M 要的每一格都备齐了"：

| 判据 | 守的那件事 | 改前形态 |
|---|---|---|
| a | 次序按名册深度优先（先钻进第一支，再第二支） | 三件工具都不存在（`unknown_tool`） |
| b | 在飞与待机都在同一份列表里（不是两档各查一次） | 同上 |
| c | `unknown` 不折成在飞、也不折成待机（三态） | 同上 |
| d | 板项里"现在在做哪一项"有显式标记（`in_progress_id`） | 同上 |
| e | 计时器三格（purpose / 等谁 / 已等待）都读得到 | 同上 |
| f | 读不成 ⇒ `checked=false` 加原因，绝不折成"没有活跃子代理" | 同上 |
| g | `review_child`：合法编码给全信息、非法编码受控拒绝并点名合法号 | 同上 |
| h | `patrol_verdict` 的 `pass` 有落痕（`out/secretary/relay.jsonl` 一行） | 同上 |
| i | `patrol_verdict` 的 `guide` 真的沿秘书链逐级走到链尾（不是第二条投递路） | 同上 |
| j | 每一项带 `last_guidance`（这一支最近一次收到的指导） | 同上 |
| k | 对不活跃的号：受控拒绝并点名它现在在哪一档 | 同上 |

每一条都有一个反真空：把那条判据赖以成立的那个内部实现换成"另一种做法"，同一条断言必须
变红（证明它真的在看那一件事，而不是在空转）。

零模型：全部读数来自台账 / 名册 / 时钟 / 转发台账，一次模型调用都没有。
边界：只用 `tmp_path` 里的工作区，不碰 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import clock as CLK
from agentflow import conductor as COND
from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT

#: 台账里的时间戳一律写死（与 `tests/conftest.py` 同一条纪律）。
TS = "2026-10-27T00:00:00+08:00"
SID = "m-patrol"

#: 业主点名的那个场景逐字（指导正文）。
BODY = "别再做穷举了：把已经跑完的 64 阶群写成证明，穷举交给另一支"


# ---------------------------------------------------------------- 夹具


def _ws(root: pathlib.Path, name: str = "ws") -> tuple[pathlib.Path, Store, Conductor, Any]:
    """一个空工作区 + 主控 + 工具面（与生产同一条装配路径）。"""
    ws = root / name
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    return ws, st, cond, reg


def _child(cond: Conductor, parent: str, role: str, *, status: str = "running",
           detail: str = "", ended_at: str | None = None) -> str:
    """建一条子代理实例行（与 `summon` 建的那种同形；实例行的唯一建行点）。"""
    prow = cond._task(parent) or {}
    terminal = status in ("done", "cancelled", "failed")
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": f"patrol:{role}:{detail[:16]}", "status": status,
        "outcome": "ok" if terminal else None, "refusal_reason": None,
        "instance": "", "detail": detail or f"{role} 这一趟的活", "error": None,
        "started_at": TS, "ended_at": ended_at,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:patrol")


def _roster(ws: pathlib.Path, st: Store, owner: str, role: str, task_id: str) -> str:
    """把这一条登记进名册（指导要按名册逐跳校验，名字是那一跳的指称）。"""
    writer = SEC.for_role("M", root=ws, store=st)
    got = writer.roster_add(owner=owner, role=role, task_id=task_id, brief="巡查夹具的名册项")
    assert got.get("problem") == "", got
    return str(got.get("name") or "")


def _env(root: pathlib.Path, name: str = "ws") -> dict[str, Any]:
    """一棵四节点的树（两条兄弟支，第一条支深三层）。

        顶趟 M
        ├── D1（在等 E1：父等子的那条不变量起的钟）   ⇒ 待机
        │   └── E1（在等 F1 + 一条 600 秒的表）        ⇒ 待机
        │       └── F1（自己在跑，没有钟）              ⇒ 在飞
        └── D2（自己在跑，父刻意没给它起等它的钟）      ⇒ 在飞

    `D2` 刻意不 arm 等待器：那一档正是 `child_wait_invariant` 要点名的异常
    （"在飞却没有等它的计时器"）。
    """
    ws, st, cond, reg = _ws(root, name)
    top = cond.open_top_level_run("M", "巡查的顶趟")
    d1 = _child(cond, top, "D", detail="查 Sylow 猜想的第一条路线")
    # D2 刻意在建 E1 / F1 之前建：于是"按编号平铺"与"深度优先"给出不同的次序
    # （t-000002 / t-000003 / t-000004 / t-000005 对 002 / 004 / 005 / 003）——
    # 没有这一点，判据 a 的反真空会假绿（两种次序恰好一样）。
    d2 = _child(cond, top, "D", detail="查第二条路线")
    e1 = _child(cond, d1, "E", detail="跑 64 阶群的穷举")
    f1 = _child(cond, e1, "F", detail="把穷举结果写成证明")
    names = {
        d1: _roster(ws, st, top, "D", d1),
        e1: _roster(ws, st, d1, "E", e1),
        f1: _roster(ws, st, e1, "F", f1),
        d2: _roster(ws, st, top, "D", d2),
    }
    # 父等子的不变量（生产路径 `arm_child_waiter`）：D1 / E1 / F1 各有一条等它的钟。
    for pid, cid, role in ((top, d1, "D"), (d1, e1, "E"), (e1, f1, "F")):
        armed = cond.arm_child_waiter(cid, parent_task_id=pid, role=role)
        assert armed.get("armed") is True, armed
    # E1 自己：一条等 F1 的钟（"等谁"那一格），一条纯计时的表（"还剩多久"那一格）。
    park = CLK.start_timer(ws, wait_for=f"task:{f1}", reason="等 F 交回证明",
                           task_id=e1, role="E")
    tick = CLK.start_timer(ws, reason="自查一遍穷举脚本", after_sec=600.0,
                           task_id=e1, role="E")
    # D1 名下两条未消板项：一条 claimed（= 现在在做这一项），一条还 queued。
    doing = cond.open_item(kind="message", role="D", expects="ack", action="message",
                           summary="先核 Sylow 定理里的阶数那一步",
                           parent_task_id=d1, depth=2)
    cond.claim_item(doing, by_task_id=d1)
    todo = cond.open_item(kind="delegation", role="D", expects="work", action="run",
                          summary="再核一遍共轭类的那条引理",
                          parent_task_id=d1, depth=2)
    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "top": top,
            "d1": d1, "e1": e1, "f1": f1, "d2": d2, "names": names,
            "park": park.timer_id, "tick": tick.timer_id,
            "doing": doing, "todo": todo}


def _call(env: dict[str, Any], name: str, **params: Any) -> Any:
    """以顶趟那一行（M）的身份调一件工具（生产路径由 `_do_tool` 挂同一个身份）。"""
    with calling_as(env["top"], "M", session_root=str(env["ws"]), sid=SID):
        return env["reg"].call(name, role="M", **params)


def _patrol(env: dict[str, Any]) -> dict[str, Any]:
    res = _call(env, "conductor.patrol")
    assert res.ok, res.to_dict()
    return dict(res.data)


def _by_code(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("code") or ""): item for item in data.get("items") or ()}


def _stable(value: Any) -> Any:
    """把"时间在走"的那几格抹平（两次调用之间秒数必然不同，那不叫两套实现）。"""
    if isinstance(value, dict):
        return {k: (None if k in ("waited_sec", "due_in_sec", "stalled_sec") else _stable(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def _relay_rows(ws: pathlib.Path) -> list[dict[str, Any]]:
    """转发台账的行（`out/secretary/relay.jsonl`）。读不到 ⇒ 空列表（断言会红）。"""
    path = SEC.relay_path(ws)
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _hop_rows(ws: pathlib.Path) -> list[dict[str, Any]]:
    """只要"转发那一跳"的行（`kind=relay_hop`）：巡查的落痕与转发共用一本台账。"""
    return [r for r in _relay_rows(ws) if str(r.get("kind") or "") == "relay_hop"]


def _verdict_rows(ws: pathlib.Path) -> list[dict[str, Any]]:
    return [r for r in _relay_rows(ws) if str(r.get("kind") or "") == CT.PATROL_TRACE_KIND]


def _items_of(cond: Conductor, tid: str) -> list[dict[str, Any]]:
    return [dict(r) for r in cond.open_items_of(tid)]


def _chain(env: dict[str, Any]) -> list[str]:
    return [env["top"], env["d1"], env["e1"], env["f1"]]


# ---------------------------------------------------------------- a) 深度优先


def _assert_depth_first(data: dict[str, Any], expect: list[str]) -> None:
    """`order` 逐字是深度优先的次序，且每一条的绝对编码链与台账的父子关系一致。"""
    assert data["order"] == expect, (
        "巡查次序不是按名册深度优先：\n"
        f"  期望 {expect}\n  实得 {data['order']}")
    assert [i["code"] for i in data["items"]] == expect, data["items"]
    for item in data["items"]:
        assert item["chain"][-1] == item["code"], item
        assert item["chain"][0] == data["root"], item


def test_a_patrol_orders_children_by_roster_depth_first(tmp_path: pathlib.Path) -> None:
    """判据 a：先钻进 D1 那一支（D1 → E1 → F1），再回来走 D2。"""
    env = _env(tmp_path)
    data = _patrol(env)
    _assert_depth_first(data, [env["d1"], env["e1"], env["f1"], env["d2"]])
    # 逐条把链也对一遍（深层节点不许只给"父是谁"让 M 自己拼）。
    by = _by_code(data)
    assert by[env["f1"]]["chain"] == _chain(env), by[env["f1"]]
    assert by[env["d2"]]["chain"] == [env["top"], env["d2"]]
    assert by[env["e1"]]["chain_text"] == Conductor.chain_text(
        [env["top"], env["d1"], env["e1"]]), by[env["e1"]]
    # 名册名也在（M 认人按名册名，认号按绝对编码）
    assert by[env["e1"]]["name"] == env["names"][env["e1"]], by[env["e1"]]


def test_a_reverse_vacuum_a_flat_order_breaks_the_depth_first_criterion(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 a：把次序换成"按编号平铺"⇒ 同一条断言必须变红（证明它真的在看次序）。"""
    env = _env(tmp_path)
    monkeypatch.setattr(CT, "_dfs_codes", lambda children, tops: sorted(
        set(tops) | {k for v in children.values() for k in v}))
    data = _patrol(env)
    with pytest.raises(AssertionError):
        _assert_depth_first(data, [env["d1"], env["e1"], env["f1"], env["d2"]])


# ---------------------------------------------------------------- b) 在飞 + 待机


def _assert_both_states(env: dict[str, Any], data: dict[str, Any]) -> None:
    """在飞与待机都在同一份列表里，`by_state` 四档各几个。"""
    states = {i["code"]: i["state"] for i in data["items"]}
    assert states[env["d1"]] == COND.AGENT_STATE_STANDBY, states
    assert states[env["e1"]] == COND.AGENT_STATE_STANDBY, states
    assert states[env["f1"]] == COND.AGENT_STATE_FLYING, states
    assert states[env["d2"]] == COND.AGENT_STATE_FLYING, states
    assert data["by_state"][COND.AGENT_STATE_FLYING] == 2, data["by_state"]
    assert data["by_state"][COND.AGENT_STATE_STANDBY] == 2, data["by_state"]
    assert data["by_state"][COND.AGENT_STATE_UNKNOWN] == 0, data["by_state"]
    assert data["by_state"]["total"] == data["count"] == 4, data["by_state"]
    assert data["checked"] is True and data["reason"] == ""
    # 状态词只用既有的那四个常量（不新造词），标签也来自那一份词表。
    assert {i["state"] for i in data["items"]} <= set(COND.AGENT_STATES)
    labels = {i["state"]: i["state_label"] for i in data["items"]}
    assert labels[COND.AGENT_STATE_FLYING] == COND.AGENT_STATE_LABELS[
        COND.AGENT_STATE_FLYING]


def test_b_flying_and_standby_are_in_the_same_list(tmp_path: pathlib.Path) -> None:
    """判据 b：在飞与待机都在同一份列表里（不是两档各查一次）。"""
    env = _env(tmp_path)
    _assert_both_states(env, _patrol(env))


def test_b_reverse_vacuum_folding_standby_into_flying_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 b：把待机折成在飞 ⇒ 同一条断言必须变红（证明两档真的分得开）。"""
    env = _env(tmp_path)
    real = CT._state_cells

    def folded(cond_: Any, rows: Any, clock: Any, **kw: Any) -> dict[str, Any]:
        out = real(cond_, rows, clock, **kw)
        for cell in out.values():
            if str(cell.get("state") or "") == COND.AGENT_STATE_STANDBY:
                cell["state"] = COND.AGENT_STATE_FLYING
        return out

    monkeypatch.setattr(CT, "_state_cells", folded)
    with pytest.raises(AssertionError):
        _assert_both_states(env, _patrol(env))


# ---------------------------------------------------------------- c) unknown 不折


def _break_clock(env: dict[str, Any]) -> pathlib.Path:
    """把这个工作区的时钟簿记写坏，并清掉进程内缓存（否则读到的是缓存里那一份）。"""
    path = env["ws"] / "out" / "clock" / "state.json"
    assert path.is_file(), path
    path.write_text("{ 这不是 JSON", encoding="utf-8", newline="")
    CLK.reset_books()
    return path


def _assert_unknown_not_folded(data: dict[str, Any], expect: int = 4) -> None:
    """时钟读不成 ⇒ 每一条都是 unknown，而活跃子代理一条都不少。"""
    assert data["checked"] is False, data
    assert data["clock"]["checked"] is False and data["clock"]["reason"], data["clock"]
    assert data["count"] == expect, ("读不成被折成了『没有活跃子代理』", data["count"])
    assert {i["state"] for i in data["items"]} == {COND.AGENT_STATE_UNKNOWN}, data["items"]
    assert data["by_state"][COND.AGENT_STATE_UNKNOWN] == expect, data["by_state"]
    assert data["by_state"][COND.AGENT_STATE_FLYING] == 0, data["by_state"]
    assert data["by_state"][COND.AGENT_STATE_STANDBY] == 0, data["by_state"]
    assert data["reason"], data


def test_c_unknown_is_not_folded_into_any_active_bucket(tmp_path: pathlib.Path) -> None:
    """判据 c：时钟读不成 ⇒ 每一条都是 `unknown`（不折成在飞、也不折成待机）。"""
    env = _env(tmp_path)
    _break_clock(env)
    _assert_unknown_not_folded(_patrol(env))


def test_c_reverse_vacuum_folding_unknown_into_silent_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 c：把 unknown 折成静默 ⇒ 同一条断言必须变红。"""
    env = _env(tmp_path)
    _break_clock(env)
    real = CT._state_cells

    def folded(cond_: Any, rows: Any, clock: Any, **kw: Any) -> dict[str, Any]:
        out = real(cond_, rows, clock, **kw)
        for cell in out.values():
            if str(cell.get("state") or "") == COND.AGENT_STATE_UNKNOWN:
                cell["state"] = COND.AGENT_STATE_SILENT
        return out

    monkeypatch.setattr(CT, "_state_cells", folded)
    with pytest.raises(AssertionError):
        _assert_unknown_not_folded(_patrol(env))


# ---------------------------------------------------------------- d) 现在在做哪一项


def _assert_in_progress(env: dict[str, Any], data: dict[str, Any]) -> None:
    """未做完的板项逐条给；`claimed` 那一条是"现在在做这一项"。"""
    board = _by_code(data)[env["d1"]]["board"]
    assert board["checked"] is True, board
    assert board["open_count"] == 2, board
    ids = [r["id"] for r in board["items"]]
    assert sorted(ids) == sorted([env["doing"], env["todo"]]), ids
    assert board["in_progress_id"] == env["doing"], board
    row = next(r for r in board["items"] if r["id"] == env["doing"])
    assert row["item_state"] == "claimed", row
    assert row["kind"] == "message" and row["expects"] == "ack", row
    assert row["subject"] == "先核 Sylow 定理里的阶数那一步", row
    assert row["age_reason"], ("板项行没有创建时刻 ⇒ 年龄要写清为什么读不了", row)
    # 没有 claimed 项的那一支：空串 + 一句为什么（不是"随便挑一条当在做"）。
    quiet = _by_code(data)[env["f1"]]["board"]
    assert quiet["in_progress_id"] == "", quiet
    assert quiet["in_progress_reason"], quiet
    assert quiet["open_count"] == 0, quiet


def test_d_board_marks_the_item_being_done_right_now(tmp_path: pathlib.Path) -> None:
    """判据 d：`in_progress_id` 是 `claimed` 那一条（接手 = 现在在做）。"""
    env = _env(tmp_path)
    _assert_in_progress(env, _patrol(env))


def test_d_reverse_vacuum_marking_the_first_item_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 d：把"现在在做"改成"列表第一条"⇒ 同一条断言必须变红。"""
    env = _env(tmp_path)
    monkeypatch.setattr(CT, "_in_progress_of",
                        lambda rows: (str(rows[0].get("task_id") or "") if rows else "", ""))
    with pytest.raises(AssertionError):
        _assert_in_progress(env, _patrol(env))


# ---------------------------------------------------------------- e) 计时器三格


def _assert_timer_cells(env: dict[str, Any], data: dict[str, Any]) -> None:
    """每条计时器给 purpose / 等谁 / 已等待（外加还剩多久与状态）。"""
    timers = _by_code(data)[env["e1"]]["timers"]
    assert timers["checked"] is True, timers
    rows = {str(r["timer_id"]): r for r in timers["rows"]}
    assert env["park"] in rows and env["tick"] in rows, sorted(rows)
    park = rows[env["park"]]
    assert park["purpose"] == "等 F 交回证明", park
    assert park["waiting_on_text"].startswith("在等"), park
    assert env["f1"] in park["waiting_on_text"], park
    assert isinstance(park["waited_sec"], float) and park["waited_sec"] >= 0.0, park
    assert park["due_in_sec"] is None, ("等谁且没设上限 ⇒ 没有钟点，不许编一个 0", park)
    assert park["state"] == "pending", park
    tick = rows[env["tick"]]
    assert tick["purpose"] == "自查一遍穷举脚本", tick
    assert tick["waiting_on_text"] == "", ("等的是时间 ⇒ 这一格是空串，不是『在等 None』", tick)
    assert isinstance(tick["waited_sec"], float) and tick["waited_sec"] >= 0.0, tick
    assert isinstance(tick["due_in_sec"], float) and tick["due_in_sec"] > 500.0, tick
    assert timers["count"] == len(timers["rows"]), timers


def test_e_timer_rows_carry_purpose_waiter_and_waited_seconds(
        tmp_path: pathlib.Path) -> None:
    """判据 e：三格都读得到（purpose / 等谁 / 已等待）。"""
    env = _env(tmp_path)
    _assert_timer_cells(env, _patrol(env))


def test_e_reverse_vacuum_dropping_the_waiter_text_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 e：把三格抹掉（purpose 空、等谁空、已等待 null）⇒ 同一条断言必须变红。"""
    env = _env(tmp_path)
    monkeypatch.setattr(CT, "_timer_cell", lambda row, entry, reading: {
        "timer_id": str((row or {}).get("id") or ""),
        "kind": str((row or {}).get("kind") or ""),
        "purpose": "", "purpose_missing": False, "waiting_on_text": "", "wait_for": "",
        "waited_sec": None, "due_in_sec": None, "state": "pending",
        "park_state": "", "to": ""})
    with pytest.raises(AssertionError):
        _assert_timer_cells(env, _patrol(env))


# ---------------------------------------------------------------- f) 三态（读不成）


def _assert_unreadable(data: dict[str, Any]) -> None:
    """台账读不成 ⇒ checked=false 加原因；与"查过了、一条活跃子代理都没有"分得开。"""
    assert data["checked"] is False, data
    assert data["count"] == 0 and data["items"] == [], data
    assert data["reason"], data


def test_f_unreadable_ledger_is_checked_false_not_zero(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 f：台账读不成 ⇒ `checked=false`；而"读成了、没有活跃子代理"是 `checked=true`。"""
    env = _env(tmp_path)
    real = env["st"].rows

    def broken(name: str, *a: Any, **kw: Any):
        if name == "tasks":
            raise RuntimeError("判据：台账读不成")
        return real(name, *a, **kw)

    monkeypatch.setattr(env["st"], "rows", broken)
    _assert_unreadable(_patrol(env))
    # 反真空：同一件工具在"读成了、一条活跃子代理都没有"时是 checked=True + 0 条。
    env2 = _ws(tmp_path, "empty")
    clean = dict(env2[3].call("conductor.patrol", role="M").data)
    assert clean["checked"] is True and clean["count"] == 0, clean
    assert clean["reason"] == "", clean


def test_f_reverse_vacuum_collapsing_unreadable_into_empty_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 f：把"读不成"折成"查过了、没有活跃子代理"⇒ 同一条断言必须变红。"""
    env = _env(tmp_path)
    monkeypatch.setattr(CT, "_patrol_reading", lambda cond, **kw: {
        "checked": True, "root": "", "reason": "", "items": [], "order": [],
        "by_state": COND.state_counts([]), "anomalies": [], "clock": {"checked": True},
        "states": {}, "legal_codes": [], "legal_total": 0, "tree": []})
    with pytest.raises(AssertionError):
        _assert_unreadable(_patrol(env))


# ---------------------------------------------------------------- g) review_child


def _assert_illegal_refused(env: dict[str, Any], data: dict[str, Any]) -> None:
    """非法号 ⇒ 受控拒绝（不抛），并点名哪些号是合法的。"""
    assert data["checked"] is True, data
    assert data["legal"] is False and data["item"] == {}, data
    assert data["refused"] == "not_in_roster", data
    assert data["legal_total"] == 4, data
    assert data["legal_codes"] == [env["d1"], env["e1"], env["f1"], env["d2"]], data
    assert "t-999999" in str(data["reason"]), data
    assert len(data["legal_codes"]) <= CT.LEGAL_CODES_LIMIT, data


def test_g_review_child_legal_code_gives_the_same_item_as_patrol(
        tmp_path: pathlib.Path) -> None:
    """判据 g 的正控：合法号 ⇒ 与 `conductor.patrol` 那一项逐键相同（同一份实现）。"""
    env = _env(tmp_path)
    patrol = _by_code(_patrol(env))
    res = _call(env, "conductor.review_child", code=env["e1"])
    assert res.ok, res.to_dict()
    data = dict(res.data)
    assert data["checked"] is True and data["legal"] is True, data
    assert data["item"]["code"] == env["e1"], data["item"]
    assert _stable(data["item"]) == _stable(patrol[env["e1"]]), (
        "两件工具给的同一项不一致 ⇒ 那是第二套实现")
    assert [n["code"] for n in data["tree"]] == [env["top"]], data["tree"]
    assert [n["code"] for n in data["tree"][0]["children"]] == [env["d1"], env["d2"]]
    assert [n["code"] for n in data["tree"][0]["children"][0]["children"]] == [env["e1"]]
    assert [n["code"] for n in data["tree"][0]["children"][0]["children"][0]["children"]] \
        == [env["f1"]]
    assert data["legal_total"] == 4, data
    assert data["legal_codes"] == [env["d1"], env["e1"], env["f1"], env["d2"]], data


def test_g_review_child_illegal_code_is_a_controlled_refusal(
        tmp_path: pathlib.Path) -> None:
    """判据 g 的负控：非法号 ⇒ 受控拒绝（不抛），并点名合法号。"""
    env = _env(tmp_path)
    res = _call(env, "conductor.review_child", code="t-999999")
    assert res.ok, ("受控拒绝不是工具故障", res.to_dict())
    _assert_illegal_refused(env, dict(res.data))


def test_g_reverse_vacuum_accepting_any_code_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 g：把"合法"改成"我把它当成活跃的那一个"⇒ 负控那一条必须变红。"""
    env = _env(tmp_path)
    real = CT._patrol_reading

    def loose(cond_: Any, **kw: Any) -> dict[str, Any]:
        got = real(cond_, **kw)
        got["items"] = list(got["items"]) + [{
            "code": "t-999999", "chain": [env["top"], "t-999999"], "chain_text": "",
            "name": "", "role": "D", "state": COND.AGENT_STATE_FLYING,
            "state_label": "", "state_reason": "", "status": "running", "doing": {},
            "board": {"checked": True, "in_progress_id": "", "in_progress_reason": "",
                      "open_count": 0, "items": []},
            "timers": {"checked": True, "count": 0, "rows": [], "reason": ""},
            "last_guidance": {"checked": True, "relay_id": "", "reason": ""},
            "notes": [], "legal": True}]
        return got

    monkeypatch.setattr(CT, "_patrol_reading", loose)
    with pytest.raises(AssertionError):
        _assert_illegal_refused(env, dict(_call(env, "conductor.review_child",
                                                code="t-999999").data))


# ---------------------------------------------------------------- h) pass 有落痕


def _assert_trace_written(env: dict[str, Any], *, verdict: str, code: str) -> dict[str, Any]:
    """`out/secretary/relay.jsonl` 里多了一行巡查结论（与转发同一本账）。"""
    rows = _verdict_rows(env["ws"])
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["verdict"] == verdict and row["code"] == code, row
    assert str(row.get("at") or ""), row
    assert row["chain"] == [env["top"], env["d1"], env["e1"], env["f1"]] or verdict == "pass", row
    return row


def test_h_pass_leaves_a_line_in_the_secretary_ledger(tmp_path: pathlib.Path) -> None:
    """判据 h：`pass` 记一条落痕，且一步投递都不发生。"""
    env = _env(tmp_path)
    assert _verdict_rows(env["ws"]) == [], "起手不该有落痕"
    res = _call(env, "conductor.patrol_verdict", code=env["f1"], verdict="pass")
    assert res.ok, res.to_dict()
    data = dict(res.data)
    assert data["checked"] is True and data["verdict"] == "pass", data
    assert data["status"] == "passed", data
    assert data["trace"] is True and data["trace_problem"] == "", data
    row = _assert_trace_written(env, verdict="pass", code=env["f1"])
    assert row["chain"] == _chain(env), row
    assert _hop_rows(env["ws"]) == [], ("pass 不该投递任何东西", _hop_rows(env["ws"]))
    for tid in (env["d1"], env["e1"], env["f1"], env["d2"]):
        assert all(BODY not in str(r.get("detail") or "")
                   for r in _items_of(env["cond"], tid)), tid


def test_h_reverse_vacuum_skipping_the_trace_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 h：把落痕那一步换成空操作 ⇒ "有账"与"没巡"就分不开了。"""
    env = _env(tmp_path)
    monkeypatch.setattr(CT, "_write_verdict_trace", lambda *a, **kw: (True, ""))
    res = _call(env, "conductor.patrol_verdict", code=env["f1"], verdict="pass")
    assert dict(res.data)["trace"] is True, ("工具照样自称落了痕", res.data)
    with pytest.raises(AssertionError):
        _assert_trace_written(env, verdict="pass", code=env["f1"])


# ---------------------------------------------------------------- i) guide 走秘书链


def _assert_guide_went_through_the_chain(env: dict[str, Any], data: dict[str, Any],
                                         *, hops: int = 4) -> None:
    """指导沿秘书链逐级转发：台账多一笔转发、中间各跳不拿正文、只有链尾有正文。"""
    assert data["checked"] is True, data
    assert data["status"] == "delivered", data
    assert data["delivered_to"] == [env["f1"]], data
    assert data["relay_id"], data
    chain = _chain(env)
    assert data["chain"] == chain, data["chain"]
    routed = _hop_rows(env["ws"])
    assert len(routed) == hops, routed
    assert [r["secretary_task_id"] for r in routed] == chain, routed
    assert [r["mode"] for r in routed] == ["forward"] * (hops - 1) + ["deliver"], routed
    assert [r["content_read"] for r in routed] == [False] * (hops - 1) + [True], routed
    assert len({r["relay_id"] for r in routed}) == 1, routed
    # 中间各跳的代理本人一条正文都没有；链尾那一个收到正文。
    for tid in chain[:-1]:
        assert all(BODY not in str(r.get("detail") or "")
                   for r in _items_of(env["cond"], tid)), (
            "中间各跳不许拿到正文", tid, _items_of(env["cond"], tid))
    tail = [r for r in _items_of(env["cond"], env["f1"]) if BODY in str(r.get("detail") or "")]
    assert len(tail) == 1, ("链尾必须收到正文", _items_of(env["cond"], env["f1"]))


def test_i_guide_travels_down_the_secretary_chain(tmp_path: pathlib.Path) -> None:
    """判据 i：`patrol_verdict(guide)` 走的就是 `conductor.guide` 那条秘书链。"""
    env = _env(tmp_path)
    res = _call(env, "conductor.patrol_verdict", code=env["f1"], verdict="guide",
                text=BODY)
    assert res.ok, res.to_dict()
    data = dict(res.data)
    assert data["verdict"] == "guide" and data["status"] == "delivered", data
    _assert_guide_went_through_the_chain(env, data)
    assert [h["hop"] for h in data["hops"]] == [1, 2, 3, 4], data["hops"]
    assert data["item_id"], data
    # 同一本账上多了一行巡查结论（结论与"指导走到哪一跳"对着一张台账读）。
    row = _assert_trace_written(env, verdict="guide", code=env["f1"])
    assert row["relay_id"] == data["relay_id"], row
    assert row["hops"] == 4, row


def test_i_reverse_vacuum_delivering_directly_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 i：把指导改成"直接给目标开一条板项"（第二条投递路）⇒ 判据 i 必红。"""
    env = _env(tmp_path)

    def direct(_conductor: Any, store: Any, *, to: str, text: str) -> Any:
        from agentflow.tools import ok as _ok

        cond = _conductor()
        item = cond.open_item(kind="notice", role="F", expects="ack", action="notice",
                              summary=text, parent_task_id=to, depth=2)
        return _ok({"checked": True, "ok": True, "status": "delivered", "to": to,
                    "chain": _chain(env), "chain_text": "", "names": [], "roles": ["F"],
                    "to_role": "F", "delivered_to": [to], "hops": [],
                    "item_id": str(item), "relay_id": "", "refused": "", "error": "",
                    "skipped": [], "text": text, "note": "判据：第二条投递路"})

    monkeypatch.setattr(CT, "_guide_handler", direct)
    data = dict(_call(env, "conductor.patrol_verdict", code=env["f1"], verdict="guide",
                      text=BODY).data)
    with pytest.raises(AssertionError):
        _assert_guide_went_through_the_chain(env, data)


def test_i_illegal_code_is_refused_and_nothing_is_delivered(tmp_path: pathlib.Path) -> None:
    """判据 i 的邻格：非法编码在 `patrol_verdict` 上也是受控拒绝（不抛）。"""
    env = _env(tmp_path)
    res = _call(env, "conductor.patrol_verdict", code="t-999999", verdict="guide",
                text=BODY)
    assert res.ok, res.to_dict()
    data = dict(res.data)
    assert data["checked"] is True and data["status"] == "refused", data
    assert data["refused"] == "not_in_roster", data
    assert data["legal_codes"] == [env["d1"], env["e1"], env["f1"], env["d2"]], data
    assert _hop_rows(env["ws"]) == [], ("被拒的指导一步都不许动", _hop_rows(env["ws"]))
    assert _verdict_rows(env["ws"]) == [], ("被拒的结论不许落成『巡过了』", _verdict_rows(env["ws"]))


# ---------------------------------------------------------------- j) last_guidance


def _assert_last_guidance(env: dict[str, Any], data: dict[str, Any]) -> None:
    """`last_guidance` 读得到（谁在第几跳收到了什么），没收到过的是空表 + 原因。"""
    got = _by_code(data)[env["f1"]]["last_guidance"]
    assert got["checked"] is True and got["relay_id"], got
    assert got["hops"] == 4, got
    assert BODY[:10] in got["text"], got
    assert str(got.get("at") or ""), got
    quiet = _by_code(data)[env["d2"]]["last_guidance"]
    assert quiet["checked"] is True and quiet["relay_id"] == "", quiet
    assert quiet["reason"], ("没收到过要写清为什么，不是空表了事", quiet)
    for tid in (env["d1"], env["e1"]):
        assert _by_code(data)[tid]["last_guidance"]["relay_id"] == "", (
            "中间各跳不算收到 M 的指导（正文只到链尾）", tid)


def test_j_each_item_carries_the_latest_guidance(tmp_path: pathlib.Path) -> None:
    """判据 j：M 不必每轮重发同一句 —— 这一支最近一次收到的指导就在这一格。"""
    env = _env(tmp_path)
    _call(env, "conductor.patrol_verdict", code=env["f1"], verdict="guide", text=BODY)
    _assert_last_guidance(env, _patrol(env))


def test_j_reverse_vacuum_counting_intermediate_hops_as_received_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 j：把"链上任何一跳"都算成收到指导 ⇒ 同一条断言必须变红。"""
    env = _env(tmp_path)
    _call(env, "conductor.patrol_verdict", code=env["f1"], verdict="guide", text=BODY)

    def loose(rows: Any, code: str) -> dict[str, Any]:
        for row in rows:
            if code in (row.get("chain") or ()) and str(row.get("kind") or "") == "relay_hop":
                return {"checked": True, "relay_id": str(row.get("relay_id") or ""),
                        "at": str(row.get("at") or ""), "text": BODY, "hops": 1,
                        "delivered_to": [], "item_id": "", "reason": ""}
        return {"checked": True, "relay_id": "", "at": "", "text": "", "hops": 0,
                "delivered_to": [], "item_id": "", "reason": "没收到过"}

    monkeypatch.setattr(CT, "_last_guidance", loose)
    with pytest.raises(AssertionError):
        _assert_last_guidance(env, _patrol(env))


# ---------------------------------------------------------------- k) 不活跃的号


def _assert_inactive_refused(env: dict[str, Any], data: dict[str, Any]) -> None:
    """对不活跃的号（已收工的静默子代理）受控拒绝，并点名它现在在哪一档。

    两档拒绝码都算数，含义不同：`not_active` = 它不在活跃列表里（台账里那一行已收工）；
    `target_not_active` = 它在列表里、但三态已经是静默（交完差还占着 running 那一行）。
    """
    assert data["checked"] is True and data["status"] == "refused", data
    assert data["refused"] in ("not_active", "target_not_active"), data
    assert data["target_state"] == COND.AGENT_STATE_SILENT, data
    assert data["target_state_label"] == COND.AGENT_STATE_LABELS[
        COND.AGENT_STATE_SILENT], data


def test_k_inactive_code_is_refused_with_its_state(tmp_path: pathlib.Path) -> None:
    """判据 k：一个已经交完差的子代理没有「过」可言（拒绝并点名它在静默那一档）。"""
    env = _env(tmp_path)
    quiet = _child(env["cond"], env["top"], "G", status="done",
                   detail="已经交完的那一件活", ended_at=TS)
    res = _call(env, "conductor.patrol_verdict", code=quiet, verdict="pass")
    assert res.ok, res.to_dict()
    _assert_inactive_refused(env, dict(res.data))
    assert quiet not in [i["code"] for i in _patrol(env)["items"]], (
        "台账已落终态的行不在活跃列表里", quiet)
    assert _verdict_rows(env["ws"]) == [], ("被拒的结论不许落成『巡过了』", _verdict_rows(env["ws"]))


def test_k_reverse_vacuum_accepting_an_inactive_child_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 k：把"活跃"放宽（任何号都算活跃）⇒ 对静默子代理的拒绝会消失。"""
    env = _env(tmp_path)
    quiet = _child(env["cond"], env["top"], "G", status="done",
                   detail="已经交完的那一件活", ended_at=TS)
    monkeypatch.setattr(CT, "_legal_code", lambda reading, code: True)
    data = dict(_call(env, "conductor.patrol_verdict", code=quiet, verdict="pass").data)
    with pytest.raises(AssertionError):
        _assert_inactive_refused(env, data)
