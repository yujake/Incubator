# -*- coding: utf-8 -*-
"""收工交付时自动问询"要不要销号它" ＋ 停滞读数（业主 2026-10-26 第二、三条裁定）。

## 业主原话（唯一权威，逐字）

```
「d2 B1 t000006 显示在飞已经很久但显然不是在飞了，它拖着 M 结不了项。且 M 以及其它父代理
  都没有销号无用的静默子代理的意识，这个可以在子代理收工交付时系统自动问询是否销号」
```

同一批裁定的第三条（问询的形状与 `expects`）与第二条（停滞读数）都从这句话来。

## 真机证据（`projects/mp3-r3`）

B1（t-000006）：21:12:46 起、22:34:02 才 done（81 分钟），而这 81 分钟里它只有 4 个 step
（首 21:15:46、末 22:32:49）⇒ 绝大部分时间它既没在跑步、也没交差，状态却一直是 `running`
⇒ 页面显示"在飞" ⇒ M 那一侧"名下还有在飞的子"⇒ 结不了项（`final_refused` / 板项闸），
而实际那个子早就该被处置。

## 这一份钉住的六件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_a_silent_child_handoff_asks_the_parent_whether_to_retire_it` | 子代理交差且已静默 ⇒ 父名下多一条问询板项，正文含"要销号它吗"＋"conductor.retire_child"，`expects="work"` | 改前没有任何问询：交差只落一条交差账与一条留言，盘上没有任何"要不要销号它"这句话，也没有 `retire-ask@` 这一族板项 |
| b) `test_b_a_child_that_still_has_a_timer_is_not_asked`（正控） | 交差时不静默（还挂着计时器）⇒ 不落问询 | 改前不适用（根本没有问询）；改后这条守的是"问询的前提必须是真的"—— 一个还挂着钟的子代理不许收到"已静默"这句话 |
| c) `test_c_the_question_does_not_retire_anything` | 不自动销号：问询落了之后那个子的 `status` 还是原来的，名册上也没有销号行 | 改前不适用（没有问询）；这一条防的是"顺手替父做了"——销号不可逆，必须仍是父的决定 |
| d) `test_d_a_running_task_without_new_steps_reads_stalled` | 造一个 `running` 但 15 分钟没新步的任务 ⇒ `stalled=True`、`stalled_sec>600`、理由含最后一步时间 | 改前没有这一格：`activity_snapshot` / `retire_state_of` / `roster_face` 三处都只有 `state`，一个 81 分钟没动静的行与"正在跑"的行长得一模一样 |
| e) `test_e_a_stalled_task_is_still_flying_and_cannot_be_retired` | 不折平：停滞的任务 `state` 仍是 `flying`（不是 `silent`），且 `conductor.retire_child` 仍按 `target_not_silent` 拒绝 | 改前不适用（没有停滞这一格）；这一条守的是"停滞 ≠ 静默"——折平会让它可以被销号 |
| f) `test_f_stubbing_either_side_makes_a_and_d_red` | 反真空：把 ① 的问询打桩成不落 ⇒ a 必红；把 ② 的停滞判据打桩成恒假 ⇒ d 必红 | 不适用（它守的是 a / d 不是真空的那两条） |

a / d 的判据本体各自只写一份（`_a_problems` / `_d_problems`），反真空那一条调同一份判据：
打桩之后它必须报出问题 —— 否则"打桩 ⇒ 必红"证明的是打桩坏了，而不是判据真的在看那件事。

## 三态纪律在这一份里的落点

`stalled` 恒有值（不是"有这一格才算"）：没读到落痕 ⇒ `False` + 秒数 `None`（"没有证据"
不是"没有停滞"，也不是 0 分钟）。`unknown` 那条路一个字节没改 —— 停滞读不出来不许把
三态也折成"不知道"。

## 为什么问询的 `expects` 是 `"work"`

业主倾向那个选择（"不处理它就会一直拖着结项"）：这条项要父做一个决定（销 / 不销），
不是"读一下就算办完"的通报。所以它不能被"渲染即收口"那一档代收（那条路只对
`expects="ack"` 生效，见 `conductor._settle_if_informational`），会一直留在板上 ——
这正是业主点名的那一件事。
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import clock as CLK
from agentflow import conductor as COND
from agentflow.agent_loop import AgentLoop, LoopRun
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary, retired_path
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry
from agentflow.webui import readers as R

#: 父代理唯一的销号入口（`Secretary.retire` 是它下游的落实那一步）。
TOOL = "conductor.retire_child"

TS = "2026-01-01T00:00:00+00:00"

_REPO = pathlib.Path(__file__).resolve().parents[1]
_ROSTER_TSX = _REPO / "ui" / "src" / "components" / "Roster.tsx"
_TREE_TS = _REPO / "ui" / "src" / "rosterTree.ts"


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 ＋ 一个主控 ＋ 父那一趟的秘书（`roster_sink` 按生产的取法接上）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：静默子与停滞"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, role: str = "D",
           status: str = "running") -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行；`running` 不带终态时间）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"停滞:{role}:{status}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理",
        "error": None, "started_at": TS,
        "ended_at": (TS if status in ("done", "cancelled") else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return cond._write_new_row(row, note="fixture:child")


def _register(env: dict[str, Any], owner: str, task_id: str, *,
              role: str = "D", brief: str = "写研究报告") -> str:
    """登记进 `owner` 那份名册（问询正文要写名册名，销号也用同一个名字）。"""
    got = env["sec"].roster_add(owner=str(owner), role=role, task_id=task_id, brief=brief)
    assert got.get("problem") == "", got
    return str(got["name"])


def _timer(env: dict[str, Any], task_id: str, *, after_sec: float = 600.0,
           role: str = "D") -> Any:
    """给它起一条一次性计时器（"它还会醒过来"的最直接证据）。"""
    return CLK.start_timer(str(env["root"]), reason="夹具：还没到点", after_sec=after_sec,
                           task_id=str(task_id), role=role)


def _handoff(env: dict[str, Any], task_id: str, *, role: str = "D") -> dict[str, Any]:
    """落一条交差账（子代理自己交差时写的就是这一行）。"""
    return CLK.record_handoff(str(env["root"]), task_id=str(task_id),
                              parent_task_id=str(env["owner"]), role=role,
                              reason="夹具：无事可做且没有计时器 ⇒ 交差")


class _Spend:
    usd = 0.0


class _Seam:
    """一条不调模型的缝（这一份判据只跑父侧的两处读数，不该有模型调用）。"""

    usd_budget = None
    spend = _Spend()

    def spent_usd(self) -> tuple[float, str]:
        return 0.0, "fixture"

    def ask_step(self, *a: Any, **k: Any) -> Any:  # pragma: no cover - 不该走到
        raise AssertionError("这一份判据不该真的问模型")


def _loop(env: dict[str, Any]) -> AgentLoop:
    """父代理那一趟的循环（只用到父侧那两处读数，不跑 `run()`）。"""
    return AgentLoop(role="M", session_root=pathlib.Path(env["root"]), registry=object(),
                     seam=_Seam(), conductor=env["cond"], my_task_id=str(env["owner"]),
                     store=env["store"], workspace_root=str(env["root"]), sid="fixture",
                     auto_secretary=False)


def _note(env: dict[str, Any], task_id: str) -> tuple[AgentLoop, LoopRun, str]:
    """走一遍父代理"收到子代理交差"的那条路（`_note_child_handoff`）。"""
    loop = _loop(env)
    run = LoopRun(role="M", task="夹具：父侧收到交差")
    ref = loop._note_child_handoff({"wait_for": f"task:{task_id}"}, run=run)
    return loop, run, ref


def _board(env: dict[str, Any]) -> list[dict]:
    """挂在父名下、还没消的板项（`open_items_of` 是它的唯一读口）。"""
    return [dict(r) for r in env["cond"].open_items_of(str(env["owner"]))]


def _retired_rows(root: Any, owner: str) -> list[dict]:
    """某个父的销号名单（一行 = 一次销号）。"""
    path = retired_path(str(root), str(owner))
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _call(env: dict[str, Any], **kwargs: Any) -> Any:
    """以"父这一趟"的身份调一次销号（`calling_as` 挂台账号，生产里由 `_do_tool` 挂）。"""
    reg = ToolRegistry(name="stall-ask")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(str(env["owner"]), "M"):
        return reg.call(TOOL, dict(kwargs), role="M")


def _stamp_ago(env: dict[str, Any], task_id: str, *, minutes: float,
               step: int = 7) -> str:
    """写一条"最后一步在 N 分钟之前"的落痕（`conductor.stamp_step` 是它的唯一写口）。"""
    at = (datetime.now().astimezone() - timedelta(minutes=minutes)).isoformat(
        timespec="seconds")
    path, problem = COND.stamp_step(str(env["root"]), task_id=str(task_id), role="E",
                                    step=int(step), sid="fixture", at=at)
    assert problem == "", problem
    return at


# ====================================================================== a) 问询
def _a_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个已静默的子代理（running ＋ 交差账上有它那一行、没有计时器、没有活跃子）。"""
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    tid = _child(env["cond"], owner, role="D", status="running")
    env["child"] = {"task_id": tid, "name": _register(env, owner, tid)}
    _handoff(env, tid)
    return env


def _a_problems(env: dict[str, Any]) -> list[str]:
    """(a) 的判据本体：静默交差 ⇒ 父名下多一条问询板项（正文 / expects / 幂等键）。"""
    ctx = dict(env["child"])
    tid = str(ctx["task_id"])
    problems: list[str] = []
    _loop_, run, ref = _note(env, tid)
    if ref != tid:
        problems.append(f"父侧没把这条唤醒认成 {tid} 的交差（拿到 {ref!r}）")
    if str(tid) not in run.silent_children:
        problems.append(f"交差没有被记进 run.silent_children：{run.silent_children}")
    items = _board(env)
    asked = [r for r in items if str(r.get("input_key") or "") == f"retire-ask@{tid}"]
    if len(asked) != 1:
        problems.append(f"父名下该有恰好一条 retire-ask@{tid} 的板项，实际 "
                        f"{[r.get('task_id') for r in items]}")
        return problems
    item = asked[0]
    text = str(item.get("detail") or "")
    if item.get("kind") != "notice":
        problems.append(f"问询项该是 notice，实际 {item.get('kind')!r}")
    if item.get("expects") != "work":
        problems.append(f"问询项的 expects 该是 work（父必须做决定），实际 "
                        f"{item.get('expects')!r}")
    if item.get("item_state") != "queued":
        problems.append(f"问询项该还没被读过（queued），实际 {item.get('item_state')!r}")
    if item.get("parent_task_id") != str(env["owner"]):
        problems.append(f"问询项该挂在父名下 {env['owner']}，实际 "
                        f"{item.get('parent_task_id')!r}")
    if item.get("called_by") != "conductor":
        problems.append(f"问询项该记成框架发起（called_by=conductor），实际 "
                        f"{item.get('called_by')!r}")
    for needle in ("要销号它吗", "conductor.retire_child", "已静默", tid,
                   str(ctx["name"])):
        if needle not in text:
            problems.append(f"问询正文里没有 {needle!r}：{text!r}")
    if "不销也行" not in text:
        problems.append(f"问询正文没说清「不销也行」这一档：{text!r}")
    notes = " ".join(str(n) for n in run.notes)
    if "销号问询已落在名下" not in notes:
        problems.append(f"这一趟的读数里没有「问询已落」那一句：{notes!r}")
    return problems


def test_a_a_silent_child_handoff_asks_the_parent_whether_to_retire_it(
        tmp_path: pathlib.Path) -> None:
    """a) 子代理交差且已静默 ⇒ 父名下多一条问询板项，正文含那两句、`expects="work"`。

    改前红：改前交差只落一条交差账（`out/clock/handoffs.json`）与一条留言，
    盘上没有任何"要不要销号它"这句话 —— `retire-ask@` 这一族 `input_key` 一条都没有。
    """
    env = _a_env(tmp_path)
    problems = _a_problems(env)
    assert problems == [], problems


# ====================================================================== b) 正控
def _b_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个交差了、但还挂着计时器的子代理（= 待机，不是静默）。"""
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    tid = _child(env["cond"], owner, role="E", status="running")
    env["child"] = {"task_id": tid, "name": _register(env, owner, tid, role="E")}
    _handoff(env, tid, role="E")
    _timer(env, tid, role="E")
    return env


def _b_problems(env: dict[str, Any]) -> list[str]:
    """(b) 的判据本体：交差时还不静默 ⇒ 被记为静默的是"交差"这件事本身，但不问。"""
    tid = str(dict(env["child"])["task_id"])
    problems: list[str] = []
    _loop_, run, ref = _note(env, tid)
    if ref != tid or str(tid) not in run.silent_children:
        problems.append(f"交差账那一步该照旧记下来（ref={ref!r}，"
                        f"silent_children={run.silent_children}）")
    items = _board(env)
    if items:
        problems.append(f"它还挂着计时器（待机，不是静默）⇒ 不该问，实际落了 "
                        f"{[r.get('task_id') for r in items]}")
    state = str(env["cond"].retire_state_of(tid).get("state") or "")
    if state != COND.AGENT_STATE_STANDBY:
        problems.append(f"夹具该让它落在待机，实际 {state!r}")
    return problems


def test_b_a_child_that_still_has_a_timer_is_not_asked(tmp_path: pathlib.Path) -> None:
    """b) 正控：交差时不静默（还有计时器）⇒ 不落问询。"""
    env = _b_env(tmp_path)
    problems = _b_problems(env)
    assert problems == [], problems


# ====================================================================== c) 不自动销号
def test_c_the_question_does_not_retire_anything(tmp_path: pathlib.Path) -> None:
    """c) 不自动销号：问询落了之后那个子的 `status` 还是原来的（没有 retired）。

    改前不适用（没有问询）；这一条防的是"顺手替父做了"：销号不可逆
    （名字永久不复用），所以框架只问、不代做 —— `conductor.retire_child` 仍是唯一入口。
    """
    env = _a_env(tmp_path)
    ctx = dict(env["child"])
    tid = str(ctx["task_id"])
    assert _a_problems(env) == [], _a_problems(env)
    assert _board(env), "前提：问询项已经落下来了"
    row = env["cond"]._task(tid) or {}
    assert row.get("status") == "running", (
        f"问询落了之后那个子的 status 不许被改（实际 {row.get('status')!r}）")
    assert _retired_rows(env["root"], str(env["owner"])) == [], (
        "问询不许代销：销号名单该是空的")
    roster = env["sec"].roster_view(owner=str(env["owner"]))
    rows = [r for r in (roster.get("rows") or []) if str(r.get("task_id") or "") == tid]
    assert rows, roster
    # 名册上它还占着一位（销号会把它从"子代理数"里减掉，`child_counts` 是那个读数的
    # 唯一口径）：问询落了之后这个数不许动。
    counts = env["sec"].child_counts(owner=str(env["owner"]))
    assert counts.get("child_count") == 1, counts


# ====================================================================== d) 停滞读数
def _d_env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个 `running`、可最近一步在 15 分钟之前的子代理（不交差、没有计时器）。"""
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    tid = _child(env["cond"], owner, role="E", status="running")
    env["child"] = {"task_id": tid, "name": _register(env, owner, tid, role="E"),
                    "at": _stamp_ago(env, tid, minutes=15, step=7)}
    return env


def _d_problems(env: dict[str, Any]) -> list[str]:
    """(d) 的判据本体：running 但 15 分钟没新步 ⇒ `stalled=True` + 秒数 + 那一句理由。"""
    ctx = dict(env["child"])
    tid = str(ctx["task_id"])
    problems: list[str] = []
    snap = env["cond"].activity_snapshot()
    assert snap.get("checked") is True, snap
    cell = dict(dict(snap.get("by_task") or {}).get(tid) or {})
    if cell.get("state") != COND.AGENT_STATE_FLYING:
        problems.append(f"停滞不改三态：state 该仍是 flying，实际 {cell.get('state')!r}")
    if cell.get("stalled") is not True:
        problems.append(f"15 分钟没新步的任务该标成停滞，实际 {cell.get('stalled')!r}")
    sec = cell.get("stalled_sec")
    if not isinstance(sec, (int, float)) or float(sec) <= 600:
        problems.append(f"`stalled_sec` 该大于 600（15 分钟），实际 {sec!r}")
    reason = str(cell.get("stalled_reason") or "")
    if "最近一步在" not in reason:
        problems.append(f"理由里要点名最后一步的时刻：{reason!r}")
    if "分钟没有新步" not in reason:
        problems.append(f"理由里要写清「已经多少分钟没有新步」：{reason!r}")
    # 同一个读数在销号门那一份里也要在（`retire_state_of` 是它的唯一读口）
    gate = env["cond"].retire_state_of(tid)
    if gate.get("stalled") is not True or gate.get("stalled_sec") != sec:
        problems.append(f"`retire_state_of` 那一份读数没跟上：{gate!r}")
    # 网页那一面（`readers.roster_face`）逐节点也要有这三格
    face = R.roster_face(str(env["root"]))
    nodes = [n for n in (face.get("nodes") or []) if str(n.get("task_id") or "") == tid]
    if not nodes:
        problems.append(f"名册面里没有 {tid} 这个节点（判据测不到那一格）："
                        f"{[n.get('task_id') for n in face.get('nodes') or []]}")
    else:
        node = dict(nodes[0])
        if node.get("stalled") is not True or not isinstance(node.get("stalled_sec"),
                                                            (int, float)):
            problems.append(f"名册面那个节点没带停滞读数：stalled="
                            f"{node.get('stalled')!r}，"
                            f"stalled_sec={node.get('stalled_sec')!r}")
        if "最近一步在" not in str(node.get("stalled_reason") or ""):
            problems.append(f"名册面那个节点的理由格是空的：{node.get('stalled_reason')!r}")
    return problems


def test_d_a_running_task_without_new_steps_reads_stalled(tmp_path: pathlib.Path) -> None:
    """d) 停滞读数：造一个 `running` 但 15 分钟没新步的任务 ⇒ 三个读数都看得见。

    改前红：改前三处（`activity_snapshot` / `retire_state_of` / `roster_face`）只有
    `state` —— 一个 81 分钟没动静的行与"正在跑"的行长得一模一样，页面只能照着
    `running` 说"在飞"，而父那一侧的结项闸也只能说"名下还有活跃子"。
    """
    env = _d_env(tmp_path)
    problems = _d_problems(env)
    assert problems == [], problems


# ====================================================================== e) 不折平
def test_e_a_stalled_task_is_still_flying_and_cannot_be_retired(
        tmp_path: pathlib.Path) -> None:
    """e) 不折平：停滞的任务 `state` 仍是 `flying`，且不许被 `retire_child` 当静默销掉。

    为什么这一条比 d 更重要：把"停滞"折成"静默"会让一个活没做完的子代理变成可销
    （销号不可逆、名字永久不复用）。所以停滞只加一格读数，三态的判定次序一个字没改。
    """
    env = _d_env(tmp_path)
    ctx = dict(env["child"])
    tid = str(ctx["task_id"])
    gate = env["cond"].retire_state_of(tid)
    assert gate.get("state") == COND.AGENT_STATE_FLYING, gate
    assert gate.get("stalled") is True, gate
    assert gate.get("silent") is False, f"停滞不许读成静默：{gate!r}"
    res = _call(env, child_name=str(ctx["name"]))
    assert getattr(res, "ok", False), getattr(res, "error", res)
    data = dict(res.data or {})
    assert data.get("state") == "refused", data
    assert data.get("refusal_code") == "target_not_silent", data
    assert data.get("target_state") == "flying", data
    reason = str(data.get("reason") or "")
    assert "它还在干活" in reason, reason
    assert "停滞" in reason, f"拒信要点名它是停滞（而不是静默）：{reason!r}"
    assert "停滞不等于静默" in reason, reason
    assert _retired_rows(env["root"], str(env["owner"])) == [], "停滞的子一个都不许销"


# ====================================================================== f) 反真空
def test_f_stubbing_either_side_makes_a_and_d_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 反真空：把 ① 的问询打桩成不落 ⇒ a 必红；把 ② 的停滞判据打桩成恒假 ⇒ d 必红。

    两个打桩点各是那一侧的唯一入口：
    - ①：`Conductor.open_retire_question`（问询的判定与落盘都在它里面）；
    - ②：`conductor.step_beats`（停滞读数的唯一读口）。
    打桩之后判据必须当场报出问题 —— 否则"打桩 ⇒ 必红"证明的是打桩坏了。
    """
    real_ask = COND.Conductor.open_retire_question
    real_beats = COND.step_beats

    # 先证明两份判据在真读数上是安静的（否则下面的"必红"可能只是夹具坏了）
    a_env, d_env = _a_env(tmp_path / "a"), _d_env(tmp_path / "d")
    assert _a_problems(a_env) == [], _a_problems(a_env)
    assert _d_problems(d_env) == [], _d_problems(d_env)

    def stubbed_ask(self, **_kwargs):  # noqa: ANN001, ANN202 - 打桩
        return {"checked": True, "opened": False, "item_id": "", "silent": True,
                "state": COND.AGENT_STATE_SILENT, "state_label": "静默",
                "text": "", "duplicate": False, "why": "", "reason": ""}

    monkeypatch.setattr(COND.Conductor, "open_retire_question", stubbed_ask)
    assert _a_problems(_a_env(tmp_path / "a2")), (
        "把问询打桩成不落，a 却一声不吭（说明它没在看那张板）")

    def stubbed_beats(workspace, **_kwargs):  # noqa: ANN001, ANN202 - 打桩
        return {"checked": True, "by_task": {}, "rows": [], "count": 0,
                "dir": "", "threshold_sec": COND.STALLED_AFTER_SEC, "now": "",
                "problems": [], "reason": ""}

    monkeypatch.setattr(COND, "step_beats", stubbed_beats)
    assert _d_problems(_d_env(tmp_path / "d2")), (
        "把停滞判据打桩成真空，d 却一声不吭（说明它没在看步进落痕）")

    # 两条打桩都不许把三态弄坏：真实现仍读得回来（打桩只影响这一格）
    monkeypatch.undo()
    assert COND.step_beats and COND.Conductor.open_retire_question is real_ask
    back = _d_env(tmp_path / "d3")
    assert _d_problems(back) == [], _d_problems(back)
    assert real_beats is not None


# ====================================================================== 前端那一格
def test_the_stalled_mark_is_wired_and_data_driven() -> None:
    """前端那一格：`stalledTag` 是真函数（数据驱动），面板把它画在三态徽标旁边。

    为什么只判源码形态而不跑 TS：这一格的行为（"stalled 才画、秒数照抄"）由
    `rosterTree.stalledTag` 的一组早退实现，跑它要 node + typescript；而"面板有没有
    用它"是纯粹的接线问题，源码级就能钉住（数据面由 d 那一条从后端钉到节点上）。
    """
    tree_ts = _TREE_TS.read_text(encoding="utf-8")
    roster_tsx = _ROSTER_TSX.read_text(encoding="utf-8")
    problems: list[str] = []
    if "export function stalledTag(" not in tree_ts:
        problems.append("rosterTree.ts 里没有 stalledTag（那一格的唯一实现）")
    if "stalledBadge(" not in roster_tsx:
        problems.append("Roster.tsx 没有画停滞那一枚标记（stalledBadge）")
    if "stalledTag(" not in roster_tsx:
        problems.append("Roster.tsx 没有走 stalledTag（自己拼了第二份文案）")
    if "roster-stalled" not in roster_tsx:
        problems.append("Roster.tsx 的停滞标记没挂 roster-stalled 那个类")
    start = tree_ts.find("export function stalledTag(")
    if start >= 0:
        body = tree_ts[start:tree_ts.find("\n}", start)]
        if "node.stalled !== true" not in body:
            problems.append("stalledTag 没先判 node.stalled（「不成立就不画」没有了）")
        if "node.stalled_sec" not in body:
            problems.append("stalledTag 没读 node.stalled_sec（悬停拿不到秒数）")
    assert problems == [], problems

    # 负控①：拿掉那一枚标记 ⇒ 必红
    assert _stall_ui_problems(roster_tsx.replace("stalledBadge(", "_dropped("),
                              tree_ts), "拿掉停滞标记，判据却一声不吭"
    # 负控②：把函数改成恒不画 ⇒ 必红
    assert _stall_ui_problems(roster_tsx,
                              tree_ts.replace("node.stalled !== true", "false", 1)
                              ), "把 stalledTag 改成恒真，判据却一声不吭"


def _stall_ui_problems(roster_tsx: str, tree_ts: str) -> list[str]:
    """上面那一条的判据本体（抽出来是为了让两条负控调同一份判据）。"""
    problems: list[str] = []
    if "export function stalledTag(" not in tree_ts:
        problems.append("rosterTree.ts 里没有 stalledTag")
    if "stalledBadge(" not in roster_tsx:
        problems.append("Roster.tsx 没有画停滞那一枚标记")
    if "stalledTag(" not in roster_tsx:
        problems.append("Roster.tsx 没有走 stalledTag")
    if "roster-stalled" not in roster_tsx:
        problems.append("Roster.tsx 的停滞标记没挂 roster-stalled 那个类")
    start = tree_ts.find("export function stalledTag(")
    if start >= 0:
        body = tree_ts[start:tree_ts.find("\n}", start)]
        if "node.stalled !== true" not in body:
            problems.append("stalledTag 没先判 node.stalled")
        if "node.stalled_sec" not in body:
            problems.append("stalledTag 没读 node.stalled_sec")
    return problems
