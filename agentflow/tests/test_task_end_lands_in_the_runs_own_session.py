# -*- coding: utf-8 -*-
"""判据：`task_end` 必须落进这一趟的会话文件，不许全落进缺省会话。

## 现场（AH4，2026-11-17，真机 `projects/lp-ball-2`）

`sessions/` 下并排两个文件：

| 文件 | 行数 | 里面是什么 |
|---|---:|---|
| `2026-11-16.jsonl` | 2903 | 真跑：`agent_step` / `llm_call` / 对话…… |
| `20261116.jsonl` | 48 | 只有 `task_end` |

旁证：两文件的 `task_id` 交集 47、双向差集空、时刻逐条相等 —— 同一批收口，
一份进了真会话、一份进了 `sessions.session_id()` 的缺省日期名。

根因不是"谁传错了号"：`Conductor` 类没有 `sid` 字段，而 `task_end` 的两个
写点（`Conductor.finish` 与 `Conductor._refuse`）写会话时一个 `sid=` 都没给。
号本来就在上下文里（`calling_as` 的 `sid=` 那一格），缺的只是写这一笔时现取一次。

## 这一组钉四件事

1. 正控：`finish` 在 `calling_as(sid=...)` 里收一行 ⇒ `task_end` 落在带横线的那份
   会话里，缺省文件里 0 条（夹具就是真机那两文件形态：`AGENTFLOW_SESSION` 顶上
   缺省名，真跑给一个不同的 sid）；
2. 正控：`_refuse` 的 `task_end` 同一条口径（拒绝也是这一趟的收口，不许掉进缺省）；
3. 退路：取不到 sid ⇒ 落缺省文件并写明 why（行上带 `sid_problem`，不是静默）；
4. 反真空：把 `current_session` 打桩成"这一层不知道" ⇒ 第 1 条必须红（`task_end`
   回到缺省文件）—— 证明第 1 条真的在测"写这一笔时现取 sid"。

改前红：第 1、2 条（两个写点的 `_SESS.append(...)` 都没有 `sid=`，`task_end` 全落缺省）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import conductor as CO
from agentflow import sessions as SS
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.policy import Policy
from agentflow.store import Store

#: 真跑用的会话号（真机形态：带横线的日期）。
SID_REAL = "2026-11-16"
#: 缺省会话语义（真机形态：`%Y%m%d`，由 `sessions.session_id()` 在没给 sid 时取）。
SID_DEFAULT = "20261116"


def _env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> tuple[pathlib.Path, Store, Conductor]:
    """真机两文件形态的夹具：缺省名由环境变量顶上，真跑显式给另一个 sid。

    为什么要设 `AGENTFLOW_SESSION` 而不是靠"当天日期"：日期类断言跨午夜会变成
    flaky 的另一种来源；而 `session_id()` 的口径本来就是"环境变量优先，否则当天日期"，
    把环境变量钉住测的是同一条口径，且两个文件名与真机逐字同形。
    """
    monkeypatch.setenv(SS.ENV_SESSION, SID_DEFAULT)
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=Policy(), backend=LocalBackend({}))
    return ws, st, cond


def _task_ends(ws: pathlib.Path, sid: str) -> list[dict]:
    """读某一份会话里的 `task_end`（文件不存在 = 一条都没有，不是错误）。"""
    if not SS.session_path(ws, sid).is_file():
        return []
    events, problems = SS.read_session(ws, sid=sid)
    assert not problems, problems
    return [e for e in events if str(e.get("kind") or "") == "task_end"]


# ============================================================ 1 finish
def test_a_finished_task_end_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 1：`finish` 收的那一行，`task_end` 必须落在本趟 sid 的文件里。

    改前：`_SESS.append` 没给 `sid=` ⇒ 落 `sessions/<当天日期>.jsonl`，与本趟
    真会话分成两个文件（真机 48 行全在缺省文件里）。
    """
    ws, _st, cond = _env(tmp_path, monkeypatch)
    with calling_as("", "M", session_root=str(ws), sid=SID_REAL):
        tid = cond.open_top_level_run("M", "夹具：收一趟（判据：task_end 落本趟会话）")
        cond.finish_top_level_run(tid, stop_reason="final", detail="这一趟做完了")

    real = _task_ends(ws, SID_REAL)
    assert [str(e.get("task_id") or "") for e in real] == [tid], (
        f"本趟会话里没有这一条 task_end：{[e.get('task_id') for e in real]}")
    assert "sid_problem" not in real[0], (
        f"有 sid 的那条不该带 `sid_problem`：{real[0]}")
    assert _task_ends(ws, SID_DEFAULT) == [], (
        "task_end 仍落进了缺省会话（改前形态）")


# ============================================================ 2 _refuse
def test_a_refused_task_end_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 2：`_refuse` 收的那一行同一条口径（拒绝也是这一趟的收口）。

    为什么单独钉：`_refuse` 走的是"还没有 running 行"的另一条路（它自己建行），
    与 `finish` 是两个写点 —— 只修一个，另一半仍然静默落缺省。
    """
    ws, _st, cond = _env(tmp_path, monkeypatch)
    with calling_as("", "M", session_root=str(ws), sid=SID_REAL):
        res = cond.summon("A", "run_once", {}, by="C")     # C 没有出边 ⇒ 受控拒绝
    assert str(res.outcome) == "refused", res
    assert str(res.refusal_reason) == "forbidden_edge", res

    real = _task_ends(ws, SID_REAL)
    assert [str(e.get("task_id") or "") for e in real] == [str(res.task_id)], (
        f"拒绝那一行没落进本趟会话：{[e.get('task_id') for e in real]}")
    assert _task_ends(ws, SID_DEFAULT) == [], (
        "拒绝的 task_end 仍落进了缺省会话（改前形态）")


# ============================================================ 3 退路 + why
def test_missing_sid_falls_back_and_says_why(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 3：取不到 sid ⇒ 落缺省文件，但那一行必须写明为什么（不许静默）。

    退缺省是合法的（`sessions.session_id()` 是既有的缺省落点），不合法的是
    "落在缺省文件里而看的人不知道为什么"—— 那正是 AH4 在盘上长成两个文件之后
    仍然没人发现的原因。
    """
    ws, _st, cond = _env(tmp_path, monkeypatch)
    tid = cond.open_top_level_run("M", "夹具：没有会话上下文的一次收口")
    cond.finish_top_level_run(tid, stop_reason="final")

    fallback = _task_ends(ws, SID_DEFAULT)
    assert [str(e.get("task_id") or "") for e in fallback] == [tid], (
        f"没有 sid 时应当退缺省会话：{[e.get('task_id') for e in fallback]}")
    why = str(fallback[0].get("sid_problem") or "")
    assert why, f"落在缺省会话却没写 why（静默）：{fallback[0]}"
    assert "sid" in why and "calling_as" in why, (
        f"why 没有说清「为什么取不到 / 该怎么补」：{why!r}")
    assert _task_ends(ws, SID_REAL) == [], "没有 sid 的一笔不该出现在真会话里"


# ============================================================ 4 反真空
def test_without_the_ambient_read_the_task_end_goes_back_to_the_default(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 4（反真空）：把 `current_session` 打桩成"这一层不知道" ⇒ 判据 1 必红。

    打桩的是取 sid 的那一处（`Conductor._session_for_task_end` 读的
    `current_session()`），不是把判据换掉：换掉判据证明不了"判据会在真实现上红"。
    桩生效时 `task_end` 必须回到缺省文件（且带 why）—— 于是判据 1 那两条断言
    （真会话里有一条 / 缺省里 0 条）会同时不成立。
    """
    ws, _st, cond = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(CO, "current_session", lambda: ("", ""), raising=True)

    with calling_as("", "M", session_root=str(ws), sid=SID_REAL):
        tid = cond.open_top_level_run("M", "夹具：反真空（取 sid 的那一处被打桩）")
        cond.finish_top_level_run(tid, stop_reason="final")

    assert _task_ends(ws, SID_REAL) == [], (
        "打桩之后 task_end 还在真会话里 ⇒ 这一条没在测「写这一笔时现取 sid」")
    fallback = _task_ends(ws, SID_DEFAULT)
    assert [str(e.get("task_id") or "") for e in fallback] == [tid], (
        f"打桩之后 task_end 没有回到缺省会话：{[e.get('task_id') for e in fallback]}")
    assert str(fallback[0].get("sid_problem") or ""), fallback[0]
