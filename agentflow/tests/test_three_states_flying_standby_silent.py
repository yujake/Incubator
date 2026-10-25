# -*- coding: utf-8 -*-
"""三态（在飞 / 待机 / 静默）＋「活跃子代理 = 非静默」的判据（业主 2026-10-26 裁定）。

## 业主原话（唯一权威，逐字）

```
「关于"在飞"的读数要随着时钟式待机进行适配，分三种：
 1.在工作叫"在飞"，2.在等待（计时器）为"待机"，3.已收工，无任务，无计时器，叫"静默"。
 更新"活跃子代理"的定义为非静默子代理。」
```

同一批裁定的前一句（「有"等"这个动作还是算活跃的」）仍然成立 ⇒ 待机也算活跃。

## 这一份钉住的九件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_a_running_agent_reads_flying` | 有 running 的任务 ⇒ `flying`（正控） | 改前没有 `state` 这一格（`activity_snapshot` 只有 `active` / `waiting_only`）⇒ 读到的是 KeyError |
| b) `test_b_a_finished_agent_with_a_pending_timer_reads_standby` | `status=done` 但有未到期的 timer ⇒ `standby` | 改前它一律算"收工"：`active=False`、`active_child_count` 少一个 —— 它其实正挂在时钟上等 |
| c) `test_c_a_finished_agent_with_a_running_periodic_reads_standby` | `status=done` 且有 running 的 periodic ⇒ `standby`（正控） | 同上：改前 periodic 在活跃读数里一个字都没有 |
| d) `test_d_a_finished_agent_without_timers_reads_silent` | 已收工、无任务、无计时器 ⇒ `silent` | 改前被算成活跃的那一支：只要名下有活跃下级就活跃，而"真的收工了"没有单独一档 |
| e) `test_e_a_retired_agent_reads_silent_even_with_a_timer` | 已销号 ⇒ `silent`（负控：它挂着钟也还是静默 —— 销号即退场） | 改前名册面只有"已退役"那个中文档，三态里没有"退场 ⇒ 不在活跃集合"这一条 |
| f) `test_f_active_child_count_is_the_non_silent_count` | 1 飞 1 待 1 静默 ⇒ `active_child_count = 2` | 改前读 3（把静默的也算活跃）或 1（只数自己在跑） |
| g) `test_g_an_unreadable_clock_is_unknown_not_silent` | 时钟 / 名册读不到 ⇒ `unknown`，且不许被算成静默（反 fail-open） | 改前没有这一档：读不到时钟就等于"没有计时器" ⇒ 静默 |
| h) `test_h_stubbing_the_standby_judgement_makes_b_c_f_red` | 反真空：把"有待机计时器"的判定打桩成恒假 ⇒ b / c / f 必红 | 不适用（它守的是 b/c/f 不是真空的那几条） |
| i) `test_i_the_frontend_reads_the_non_silent_count` | 前端三档文案都在、且「活 N」读的是非静默数（不是 `children.length`） | 改前 `Roster.tsx` 那一格读 `children.length` 与 `in_flight`，三档文案一个都没有 |

b / c / f 的判据本体各自只写一份（`_b_problems` / `_c_problems` / `_f_problems`），
反真空那一条调同一份判据：打桩之后它必须报出问题 —— 否则"打桩 ⇒ 必红"证明的是
打桩坏了，而不是判据真的在看那件事。

## 三态纪律在这一份里的落点

`unknown` 是第四档，不是静默的别名：静默说的是"查过了、它收工了"，而 `unknown`
说的是"这一格没查成"。折平它们的代价很具体 —— 一个还挂在时钟上的代理会被判成收工，
而"能不能销号"正好读这一格。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import clock as CLK
from agentflow import conductor as COND
from agentflow.conductor import Conductor, LocalBackend, agent_state, clock_waiters
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

TS = "2026-01-01T00:00:00+00:00"

_REPO = pathlib.Path(__file__).resolve().parents[1]
_ROSTER_TSX = _REPO / "ui" / "src" / "components" / "Roster.tsx"
_TREE_TS = _REPO / "ui" / "src" / "rosterTree.ts"


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, object]:
    """一个工作区 + 一个主控 + 父那一趟的秘书（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：三态"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, role: str = "D",
           status: str = "done") -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行；`done` 带 outcome 与 ended_at）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"三态:{role}:{status}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理",
        "error": None, "started_at": TS,
        "ended_at": (TS if status in ("done", "cancelled") else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return cond._write_new_row(row, note="fixture:child")


def _register(env: dict[str, object], owner: str, task_id: str, *,
              role: str = "D", brief: str = "夹具的活") -> str:
    """登记进 `owner` 那份名册（名册项的身份是 owner + name，销号也要它）。"""
    got = env["sec"].roster_add(owner=str(owner), role=role, task_id=task_id, brief=brief)
    assert got.get("problem") == "", got
    return str(got["name"])


def _timer(env: dict[str, object], task_id: str, *, after_sec: float = 600.0,
           role: str = "D") -> object:
    """给它起一条一次性计时器（"还在等"的最直接证据）。"""
    return CLK.start_timer(str(env["root"]), reason="夹具：还没到点",
                           after_sec=after_sec, task_id=str(task_id), role=role)


def _periodic(env: dict[str, object], task_id: str, *,
              every_sec: float = 60.0, role: str = "D") -> object:
    """给它起一条周期性巡查（到点不消耗 ⇒ 一直"挂着"）。"""
    return CLK.start_periodic(str(env["root"]), every_sec=every_sec,
                              purpose="夹具：周期性巡查", task_id=str(task_id),
                              role=role)


def _state(env: dict[str, object], task_id: str) -> str:
    """一个代理此刻的三态（`Conductor.active_reading` 是它的读数面）。"""
    got = env["cond"].active_reading(str(task_id))
    assert got.get("checked") is True, got
    return str(got.get("state") or "")


def _states_of_counts(counts: dict) -> dict[str, object]:
    """`child_counts()["states"]` 里那四个数（缺格就是夹具坏了）。"""
    got = dict(counts.get("states") or {})
    for key in ("flying", "standby", "silent", "unknown", "active", "total"):
        assert key in got, f"child_counts()['states'] 缺 {key!r}：{got}"
    return got


# ====================================================================== a) 在飞
def test_a_a_running_agent_reads_flying(tmp_path: pathlib.Path) -> None:
    """a) 有 running 的任务 ⇒ `flying`（正控）。

    ## 改前红在哪
    `activity_snapshot()` 改前每一格只有 `self_busy` / `active` / `waiting_only`，
    没有任何一格叫 `state`；"在飞 / 待机 / 静默"这三个词在读数面上一个都没有
    （`active_children` 给的是中文两档"活跃 / 在等待"，那是另一件事）。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    running = _child(env["cond"], owner, status="running")
    _register(env, owner, running)
    assert _state(env, running) == COND.AGENT_STATE_FLYING, _state(env, running)
    got = env["cond"].active_reading(running)
    assert got["state_label"] == "在飞", got
    assert "在跑" in str(got.get("state_reason") or ""), got
    counts = env["sec"].child_counts(owner=owner)
    assert _states_of_counts(counts)["flying"] == 1, counts


# ====================================================================== b) done + timer
def _b_problems(env: dict[str, object]) -> list[str]:
    """(b) 的判据本体：`status=done` 但有一条没到点的 timer ⇒ `standby` 且算活跃。"""
    ctx = dict(env["three"])          # type: ignore[arg-type]
    tid = str(ctx["standby"])
    problems: list[str] = []
    got = env["cond"].active_reading(tid)
    if not got.get("checked"):
        return [f"活跃读数没读成：{got.get('reason')}"]
    if got.get("state") != COND.AGENT_STATE_STANDBY:
        problems.append(f"已收工但挂着计时器 ⇒ 该是待机，实际 {got.get('state')!r}"
                        f"（reason={got.get('state_reason')!r}）")
    if not got.get("waiters"):
        problems.append("待机那一格没有点名它挂在时钟上的哪一条（waiters 是空的）")
    counts = env["sec"].child_counts(owner=str(ctx["owner"]))
    states = _states_of_counts(counts)
    if states["standby"] != 1:
        problems.append(f"父的读数里待机该是 1，实际 {states['standby']}")
    if not counts.get("active_child_count"):
        problems.append("待机也算活跃（业主：有『等』这个动作还是算活跃的），"
                        f"而 active_child_count={counts.get('active_child_count')!r}")
    return problems


def _b_env(tmp_path: pathlib.Path) -> dict[str, object]:
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    standby = _child(env["cond"], owner, status="done")
    _register(env, owner, standby)
    _timer(env, standby)
    env["three"] = {"owner": owner, "standby": standby}
    return env


def test_b_a_finished_agent_with_a_pending_timer_reads_standby(
        tmp_path: pathlib.Path) -> None:
    """b) `status=done` 但有未到期的 timer ⇒ standby（不是静默、也不是在飞）。

    ## 改前红在哪
    改前的活跃口径只有一条：`active(node) = 自身有未收口的任务 or 任一直接子 active`。
    这一行已经是 `done`、也没有下级 ⇒ 改前读成 `active=False` —— 也就是"收工了"。
    而它其实正挂在时钟上等（`out/clock/state.json` 里那一条 `pending` 就是证据），
    所以改前 `active_child_count` 会少一个，三态里也没有"待机"这一档。
    """
    env = _b_env(tmp_path)
    assert _b_problems(env) == [], _b_problems(env)
    assert _state(env, str(dict(env["three"])["standby"])) == COND.AGENT_STATE_STANDBY


# ====================================================================== c) done + periodic
def _c_problems(env: dict[str, object]) -> list[str]:
    """(c) 的判据本体：`status=done` 但有一条 running 的 periodic ⇒ `standby`。"""
    ctx = dict(env["three"])          # type: ignore[arg-type]
    tid = str(ctx["periodic"])
    problems: list[str] = []
    got = env["cond"].active_reading(tid)
    if not got.get("checked"):
        return [f"活跃读数没读成：{got.get('reason')}"]
    if got.get("state") != COND.AGENT_STATE_STANDBY:
        problems.append(f"已收工但有一条 running 的周期性巡查 ⇒ 该是待机，"
                        f"实际 {got.get('state')!r}")
    kinds = sorted({str(w.get("kind") or "") for w in (got.get("waiters") or [])})
    if "periodic" not in kinds:
        problems.append(f"挂在时钟上的那一条没被认成 periodic：{kinds}")
    counts = env["sec"].child_counts(owner=str(ctx["owner"]))
    if _states_of_counts(counts)["standby"] != 1:
        problems.append(f"待机该是 1，实际 {_states_of_counts(counts)['standby']}")
    return problems


def _c_env(tmp_path: pathlib.Path) -> dict[str, object]:
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    periodic = _child(env["cond"], owner, status="done")
    _register(env, owner, periodic)
    _periodic(env, periodic)
    env["three"] = {"owner": owner, "periodic": periodic}
    return env


def test_c_a_finished_agent_with_a_running_periodic_reads_standby(
        tmp_path: pathlib.Path) -> None:
    """c) `status=done` 且有 running 的 periodic ⇒ standby（正控）。

    ## 改前红在哪
    periodic 在改前的活跃读数里一个字都没有：它既不是"未收口的任务"，
    也不是"活跃的下级" ⇒ 一条还在跳的周期性巡查对活跃读数完全透明。
    """
    env = _c_env(tmp_path)
    assert _c_problems(env) == [], _c_problems(env)


# ====================================================================== d) 静默
def test_d_a_finished_agent_without_timers_reads_silent(tmp_path: pathlib.Path) -> None:
    """d) 已收工、无任务、无计时器 ⇒ `silent`。

    ## 改前红在哪
    改前没有"静默"这一档：一个交完差、名字还挂在名册上的代理，在活跃读数里与
    "还在干活"共用同一格 `active=False` —— 读的人分不出"它收工了"与"它没被判到"。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    done = _child(env["cond"], owner, status="done")
    _register(env, owner, done)
    assert _state(env, done) == COND.AGENT_STATE_SILENT, _state(env, done)
    got = env["cond"].active_reading(done)
    assert got["state_label"] == "静默", got
    counts = env["sec"].child_counts(owner=owner)
    assert _states_of_counts(counts)["silent"] == 1, counts
    assert counts["active_child_count"] == 0, counts


# ====================================================================== e) 已销号
def test_e_a_retired_agent_reads_silent_even_with_a_timer(
        tmp_path: pathlib.Path) -> None:
    """e) 已销号 ⇒ `silent`（负控：它挂着钟也还是静默）。

    「销号即退场，不在活跃集合里」：一条留在销号名字上的钟不许把它重新拉进活跃集合 ——
    否则 `active_child_count` 会被一个早就退场的名字撑大，而"这一支还有几个人"就再也
    说不准了。名字永久不复用那一条（业主 B1）与这里不冲突：销号名单只记事、不复活。

    次序是刻意的：先趁它静默时销号（销号门上"只给静默"那一道闸要的就是这一档），
    再往这个名字上补一条钟 —— 模拟"销号之后那条 periodic / timer 才被发现还挂着"。
    闸门与判定是两件事：闸门不许销一个还在等的名字，而判定说"已经退了的那一格，
    钟也不许把它拉回来"。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    done = _child(env["cond"], owner, status="done")
    name = _register(env, owner, done)
    got = env["sec"].retire(owner=owner, name=name, reason="夹具：交完差就销号")
    assert got.get("action") == "retired", got
    view = env["sec"].roster_view(owner=owner)
    assert view["checked"] is True, view
    row = next(r for r in view["rows"] if str(r.get("task_id") or "") == done)
    # `state` 是给人读的五档中文（它已经是"已退役"），三态在 `agent_state` 那一格。
    assert row["state"] == "已退役", row
    assert row["agent_state"] == COND.AGENT_STATE_SILENT, row

    # 销号之后才发现它还挂着一条钟：名册那一层仍然是静默（退场优先于"等"）。
    stray = _timer(env, done)
    assert getattr(stray, "state", "") == "pending", stray
    view2 = env["sec"].roster_view(owner=owner)
    row2 = next(r for r in view2["rows"] if str(r.get("task_id") or "") == done)
    assert row2["agent_state"] == COND.AGENT_STATE_SILENT, row2
    face = R.roster_face(str(env["root"]))
    node = next(n for n in face["nodes"] if str(n.get("task_id") or "") == done)
    assert node["state"] == COND.AGENT_STATE_SILENT, node
    # 它不在活跃集合里：子代理数只数未销号项，活跃数里没有它。
    counts = env["sec"].child_counts(owner=owner)
    assert counts["child_count"] == 0, counts
    assert counts["active_child_count"] == 0, counts

    # 台账那一层（`activity_snapshot`）不知道"销号"这件事 —— 它只有台账行，
    # 名册名与退役都在秘书那一侧（`conductor` 的既有分层）。所以同一时刻这里读到
    # standby 而不是 silent：这不是折叠，而是"这一层缺那条事实"。谁要给三态就必须
    # 把名册项一起给它（下面纯函数那一行就是那件事）。
    snap = env["cond"].activity_snapshot()
    assert snap["by_task"][done]["state"] == COND.AGENT_STATE_STANDBY, snap["by_task"][done]
    pure = agent_state(row={"task_id": done, "status": "done"},
                       item={"retired": True},
                       wait={"checked": True, "rows": [
                           {"id": "tm-1", "kind": "timer", "park_state": ""}]})
    assert pure["state"] == COND.AGENT_STATE_SILENT, pure
    assert pure["retired"] is True, pure


# ====================================================================== f) 活跃 = 非静默
def _f_problems(env: dict[str, object]) -> list[str]:
    """(f) 的判据本体：1 飞 1 待 1 静默 ⇒ `child_count=3`、`active_child_count=2`。"""
    ctx = dict(env["three"])          # type: ignore[arg-type]
    owner = str(ctx["owner"])
    problems: list[str] = []
    counts = env["sec"].child_counts(owner=owner)
    if counts.get("checked") is not True:
        return [f"两个读数没读成：{counts.get('reason')}"]
    if counts.get("child_count") != 3:
        problems.append(f"子代理数该是 3，实际 {counts.get('child_count')!r}")
    if counts.get("active_child_count") != 2:
        problems.append(f"活跃子代理数 = 非静默 = 在飞 + 待机 = 2，"
                        f"实际 {counts.get('active_child_count')!r}")
    states = _states_of_counts(counts)
    for key, want in (("flying", 1), ("standby", 1), ("silent", 1), ("unknown", 0),
                      ("active", 2), ("total", 3)):
        if states[key] != want:
            problems.append(f"states[{key!r}] 该是 {want}，实际 {states[key]!r}")
    if int(states["flying"]) + int(states["standby"]) != int(counts["active_child_count"] or 0):
        problems.append("active_child_count 与『在飞 + 待机』对不上（两个口径各算了一遍）")
    # 同一份读数在名册面与网页名册面上也得是同一批数字
    view = env["sec"].roster_view(owner=owner)
    if view.get("active_child_count") != 2:
        problems.append(f"名册面 active_child_count 该是 2，实际 {view.get('active_child_count')!r}")
    face = R.roster_face(str(env["root"]))
    if face.get("answer") != "ok":
        problems.append(f"网页名册面没读成：{face.get('reason')!r}")
    else:
        # 纯函数的那一格：三个子各是飞 / 待 / 静默（名册名 → 三态）
        by_name = {str(n.get("name") or ""): str(n.get("state") or "")
                   for n in face.get("nodes") or []}
        want = {"D1": "flying", "F1": "standby", "B1": "silent"}
        for name, state in want.items():
            if by_name.get(name) != state:
                problems.append(f"网页名册面上 {name} 该是 {state}，实际 {by_name.get(name)!r}")
        # 顶部合计含树根那一行（它是父这一趟自己的台账行，跑着 ⇒ 也算一个在飞）
        face_states = dict(face.get("states") or {})
        if (face_states.get("flying"), face_states.get("standby"),
                face_states.get("silent"), face_states.get("unknown")) != (2, 1, 1, 0):
            problems.append(f"网页名册面四档该是 2/1/1/0（含树根），实际 {face_states}")
        if int(face_states.get("active") or 0) != int(face_states.get("flying") or 0) + \
                int(face_states.get("standby") or 0):
            problems.append(f"网页名册面 active 不等于『在飞 + 待机』：{face_states}")
    return problems


def _f_env(tmp_path: pathlib.Path) -> dict[str, object]:
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    flying = _child(env["cond"], owner, role="D", status="running")
    standby = _child(env["cond"], owner, role="F", status="done")
    silent = _child(env["cond"], owner, role="B", status="done")
    for tid, role in ((flying, "D"), (standby, "F"), (silent, "B")):
        _register(env, owner, tid, role=role)
    _timer(env, standby)
    env["three"] = {"owner": owner, "flying": flying, "standby": standby, "silent": silent}
    return env


def test_f_active_child_count_is_the_non_silent_count(tmp_path: pathlib.Path) -> None:
    """f) `active_child_count` = 非静默（= 在飞 + 待机）：1 飞 1 待 1 静默 ⇒ 读 2。

    ## 改前红在哪
    改前的 `active_child_count` 数的是"未收口的任务 + 活跃的下级"：
    - 静默那一个（done、无钟、无下级）不算 ⇒ 这一条改前读 1（少了待机那一个）；
    - 若把口径改成"名册项数"（业主点名要拆开的那两个数折成一个）⇒ 读 3。
    两个数都必须不相等且各自出现：`child_count=3`、`active_child_count=2`。
    """
    env = _f_env(tmp_path)
    assert _f_problems(env) == [], _f_problems(env)
    counts = env["sec"].child_counts(owner=str(dict(env["three"])["owner"]))
    assert counts["child_count"] != counts["active_child_count"], counts


# ====================================================================== g) unknown
def test_g_an_unreadable_clock_is_unknown_not_silent(tmp_path: pathlib.Path) -> None:
    """g) 时钟 / 名册读不到 ⇒ `unknown`，且不许被算成静默（反 fail-open）。

    三处一起钉：
    1. 纯函数那一层：`wait={"checked": False}` ⇒ `unknown`；`roster_checked=False` ⇒ `unknown`；
    2. 端到端：`out/clock/state.json` 坏掉 ⇒ 每一格 `state` 都是 `unknown`，
       `states["silent"]` 是 0（不许把"没读到"折成"收工了"），`complete=False`；
    3. 反 fail-open：`unknown` 不进 `active_child_count`，也不进 `silent` ——
       两个方向都不许折平（折进静默会让销号门把一整支误判成可以销）。

    ## 改前红在哪
    改前没有 `unknown` 这一档：时钟簿记在活跃读数里根本不被读，于是"时钟读不成"
    与"没有任何计时器"是同一件事 ⇒ 一律算收工。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    done = _child(env["cond"], owner, status="done")
    _register(env, owner, done)

    # ① 纯函数那一层（两处读不成各一档）
    no_clock = agent_state(row={"task_id": done, "status": "done"},
                           wait={"checked": False, "rows": [], "reason": "夹具：时钟坏了"})
    assert no_clock["state"] == COND.AGENT_STATE_UNKNOWN, no_clock
    assert "时钟读不成" in str(no_clock["reason"]), no_clock
    no_roster = agent_state(row={"task_id": done, "status": "done"},
                            wait={"checked": True, "rows": []},
                            roster_checked=False)
    assert no_roster["state"] == COND.AGENT_STATE_UNKNOWN, no_roster

    # ② 端到端：把时钟簿记写坏（`CLK.book` 读它时 load_error 非空 ⇒ 抛 ⇒ checked=False）
    clock_dir = pathlib.Path(str(env["root"])) / "out" / "clock"
    clock_dir.mkdir(parents=True, exist_ok=True)
    (clock_dir / "state.json").write_text("{ 这不是 JSON", encoding="utf-8")
    CLK.reset_books()                 # 让下一次读盘真的去读那份坏文件
    reading = clock_waiters(str(env["root"]))
    assert reading["checked"] is False, reading
    assert "时钟读不成" in str(reading["reason"]), reading

    got = env["cond"].active_reading(done)
    assert got["checked"] is True, got
    assert got["state"] == COND.AGENT_STATE_UNKNOWN, got
    assert "时钟读不成" in str(got.get("state_reason") or ""), got

    counts = env["sec"].child_counts(owner=owner)
    states = _states_of_counts(counts)
    assert states["unknown"] == 1, counts
    assert states["silent"] == 0, ("时钟读不成被折成了静默（fail-open）", counts)
    assert states["flying"] == 0 and states["standby"] == 0, counts
    assert counts["complete"] is False, counts
    assert [str(u.get("state") or "") for u in counts["unjudged"]] == [], counts["unjudged"]
    snap = env["cond"].activity_snapshot()
    assert snap["clock"]["checked"] is False, snap["clock"]
    assert snap["states"]["unknown"] >= 1, snap["states"]


# ====================================================================== h) 反真空
def test_h_stubbing_the_standby_judgement_makes_b_c_f_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h) 反真空：把"有待机计时器"的判定打桩成恒假 ⇒ b / c / f 必红。

    打桩点是 `conductor.clock_waiters`（唯一读时钟的那一处）—— 让它永远回
    "读到了、一条等待也没有"。这不是"读不成"（那一档会得 `unknown`，见 g），
    而是"查过了、没有计时器"：于是待机那两格被读成静默，f 的活跃数少一个。
    三条判据必须当场报出问题 —— 否则它们证明的不是"判定在看计时器"。
    """
    real = COND.clock_waiters

    def stubbed(workspace):  # noqa: ANN001, ANN202 - 打桩
        out = dict(real(workspace))
        out.update({"checked": True, "by_task": {}, "rows": [], "count": 0, "reason": ""})
        return out

    # 先证明三条判据在真读数上是安静的（否则下面的"必红"可能只是夹具坏了）
    b_env, c_env, f_env = (_b_env(tmp_path / "b"), _c_env(tmp_path / "c"),
                           _f_env(tmp_path / "f"))
    assert _b_problems(b_env) == [], _b_problems(b_env)
    assert _c_problems(c_env) == [], _c_problems(c_env)
    assert _f_problems(f_env) == [], _f_problems(f_env)

    monkeypatch.setattr(COND, "clock_waiters", stubbed)
    assert _b_problems(b_env), "把待机判定打桩成恒假，b 却一声不吭（说明它没在看计时器）"
    assert _c_problems(c_env), "把待机判定打桩成恒假，c 却一声不吭"
    assert _f_problems(f_env), "把待机判定打桩成恒假，f 却一声不吭"
    # 打桩之后那两格必须是"静默"（而不是 unknown）—— 这才是打桩该造成的错法。
    assert _state(b_env, str(dict(b_env["three"])["standby"])) == COND.AGENT_STATE_SILENT
    assert _state(c_env, str(dict(c_env["three"])["periodic"])) == COND.AGENT_STATE_SILENT


# ====================================================================== i) 前端
def _frontend_problems(roster_tsx: str, tree_ts: str) -> list[str]:
    """(i) 的判据本体：三档文案都在、且「活 N」读的是非静默数（不是 `children.length`）。

    四条（缺一条就等于"界面还在用旧口径"）：
    1. 三档文案在词表里（`STATE_TEXT` 的 flying / standby / silent 各对应 在飞 / 待机 / 静默）；
    2. `Roster.tsx` 真的用那个词表画徽标（`stateBadge` 调 `STATE_TEXT`）；
    3. 行尾那一格「活 N」走的是 `kidsStateText`（它数的是非静默），
       而 `kidsStateText` 的实现用的是 `tallyKids` / `tallyStates`，不是 `children.length`；
    4. 顶部合计走的是 `stateSummary`（读不到就说"未读到"，不显示 0）。
    """
    problems: list[str] = []
    for word in ('flying: "在飞"', 'standby: "待机"', 'silent: "静默"'):
        if word not in tree_ts:
            problems.append(f"rosterTree.ts 的三档词表里没有 {word}")
    for needle in ("STATE_TEXT", "stateBadge("):
        if needle not in roster_tsx:
            problems.append(f"Roster.tsx 没有用 {needle}（三态徽标没画出来）")
    if "kidsStateText(" not in roster_tsx:
        problems.append("Roster.tsx 没有画「活 N（飞 a · 待 b）」那一格（kidsStateText）")
    if "stateSummary(" not in roster_tsx:
        problems.append("Roster.tsx 没有画顶部合计（stateSummary）")
    # 「活 N」那一格的实现：数的是非静默，不是 children.length
    start = tree_ts.find("export function kidsStateText")
    if start < 0:
        problems.append("rosterTree.ts 里没有 kidsStateText（「活 N」那一格的唯一实现）")
    else:
        body = tree_ts[start:tree_ts.find("\n}", start)]
        if "children.length" in body:
            problems.append("kidsStateText 读了 children.length ⇒ 静默的子也会被算进「活 N」")
        if "tallyKids" not in body:
            problems.append("kidsStateText 没有走 tallyKids（非静默那一份合计）")
    return problems


def test_i_the_frontend_reads_the_non_silent_count() -> None:
    """i) 前端源码判据：三档文案都在、且「活 N」读的是非静默数（不是 `children.length`）。

    ## 改前红在哪
    改前 `Roster.tsx` 那一格读的是 `node.children.length`（「子 N」）与 `in_flight`
    （「在飞」），三档文案（在飞 / 待机 / 静默）在源码里一个都没有；
    顶部也没有任何三态合计。
    """
    roster_tsx = _ROSTER_TSX.read_text(encoding="utf-8")
    tree_ts = _TREE_TS.read_text(encoding="utf-8")
    assert _frontend_problems(roster_tsx, tree_ts) == [], _frontend_problems(roster_tsx, tree_ts)

    # 负控①：把「活 N」换回 children.length ⇒ 必红
    doctored = tree_ts.replace("tallyKids(kids)", "kids.length", 1)
    assert _frontend_problems(roster_tsx, doctored), (
        "把「活 N」改回 children.length，判据却一声不吭")
    # 负控②：把三档文案删掉一档 ⇒ 必红
    assert _frontend_problems(roster_tsx, tree_ts.replace('standby: "待机"', 'standby: ""')), (
        "把「待机」那一档文案删掉，判据却一声不吭")
    # 负控③：面板不再用那个词表 ⇒ 必红
    assert _frontend_problems(roster_tsx.replace("STATE_TEXT", "_dropped"), tree_ts), (
        "面板不画三态徽标，判据却一声不吭")


# ====================================================================== 改前读数
def test_the_old_active_flag_and_the_new_state_diverge_where_the_owner_said(
        tmp_path: pathlib.Path) -> None:
    """改前红在哪（机器证据）：同一份夹具里 `active`（改前那一个读数）与 `state`（这一批）
    在业主点名的那两处必须不一样 —— 否则这一批改的是措辞，不是读数。

    `activity_snapshot()["by_task"][tid]["active"]` 是改前唯一那个活跃口径
    （`自身有未收口的任务 or 任一直接子 active`），它今天仍在（销号门读它）；
    三态是新加的那一轴。两轴在下面三处对齐方式由业主原话决定：

    | 夹具 | 改前 `active` | 现在 `state` | 为什么 |
    |---|---|---|---|
    | 在跑 | True | `flying` | 两轴一致（正控） |
    | 已收工 + 挂着钟 | False | `standby` | 改前把它读成"收工了"，而它是在等 |
    | 已收工 + 无钟 | False | `silent` | 两轴一致（正控） |
    """
    env = _f_env(tmp_path)
    ids = dict(env["three"])          # type: ignore[arg-type]
    snap = env["cond"].activity_snapshot()
    by_task = dict(snap["by_task"])

    def cell(key: str) -> dict:
        return dict(by_task[str(ids[key])])

    assert (cell("flying")["active"], cell("flying")["state"]) == (True, "flying"), cell("flying")
    standby = cell("standby")
    assert (standby["active"], standby["state"]) == (False, "standby"), (
        "待机那一格在改前的口径里必须是 False（否则这条判据证明不了'改前读错了'）", standby)
    assert (cell("silent")["active"], cell("silent")["state"]) == (False, "silent"), cell("silent")

    # 旧口径下这两格都算"不活跃" ⇒ 改前 active_child_count 只会数到 1（在跑那一个）；
    # 新口径数到 2（在飞 + 待机）。这就是 f) 的改前红。
    assert sum(1 for key in ("flying", "standby", "silent") if cell(key)["active"]) == 1
    counts = env["sec"].child_counts(owner=str(ids["owner"]))
    assert counts["active_child_count"] == 2, counts


# ====================================================================== 合计
def test_the_four_state_words_are_one_vocabulary() -> None:
    """三态词表只有一份（机器值 + 中文名同源）：`AGENT_STATES` / `ACTIVE_AGENT_STATES`。

    这一条守的是"同一个读数三处措辞"：词表一漂，"活跃"到底含不含待机就再也没人说得清。
    """
    assert COND.AGENT_STATES == ("flying", "standby", "silent", "unknown"), COND.AGENT_STATES
    assert COND.ACTIVE_AGENT_STATES == ("flying", "standby"), COND.ACTIVE_AGENT_STATES
    assert COND.AGENT_STATE_LABELS == {"flying": "在飞", "standby": "待机",
                                       "silent": "静默", "unknown": "未读到"}
    counts = COND.state_counts(["flying", "standby", "silent", "unknown", "词表外"])
    assert counts == {"flying": 1, "standby": 1, "silent": 1, "unknown": 2,
                      "active": 2, "total": 5}, counts
    assert COND.most_active_state(["silent", "unknown"]) == "unknown"
    assert COND.most_active_state(["silent", "standby"]) == "standby"
    assert COND.most_active_state([]) == "unknown"


def test_the_json_shapes_are_stable_under_both_faces(tmp_path: pathlib.Path) -> None:
    """读数形状：`child_counts` / `roster_view` / `roster_face` 三处都有同一批格。

    三处少一格的表现是"前端读 undefined ⇒ 那一行静默不显示"，没有任何地方会报错。
    """
    env = _f_env(tmp_path)
    owner = str(dict(env["three"])["owner"])
    counts = env["sec"].child_counts(owner=owner)
    assert set(env["sec"].child_counts().keys()) >= {
        "checked", "child_count", "active_child_count", "states", "state_labels",
        "by_owner", "waiting_only", "unjudged", "complete", "note"}, sorted(counts)
    assert counts["state_labels"]["standby"] == "待机", counts["state_labels"]
    view = env["sec"].roster_view(owner=owner)
    assert "states" in view and "agent_state" in view["rows"][0], view["rows"][0]
    face = R.roster_face(str(env["root"]))
    node_keys = {k for node in face["nodes"] for k in node}
    assert "state" in node_keys and "state_reason" in node_keys, sorted(node_keys)
    assert set(face["states"]) >= {"checked", "flying", "standby", "silent", "unknown",
                                   "active", "total", "labels", "reason"}, face["states"]
    # 三处说的是同一件事：1 飞 1 待 1 静默（网页那一面还含树根那一行 —— 它是父这一趟
    # 自己的台账行，跑着，所以它也是"在飞"；两个面的口径在 docstring 里各自写清）。
    assert view["states"]["active"] == 2, view["states"]
    assert face["states"]["active"] == 3, face["states"]
    assert (face["states"]["flying"], face["states"]["standby"],
            face["states"]["silent"], face["states"]["unknown"]) == (2, 1, 1, 0), face["states"]
    assert json.dumps(face["states"], ensure_ascii=False)  # 可序列化（HTTP 面要它）
