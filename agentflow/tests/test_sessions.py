"""`sessions` 的判据（`R-63`）：按项目存放的会话记录。

## 为什么补这一组

`src/agentflow/sessions.py` 是 `draft/28` §155 那一批新增的模块（`Conductor.finish`
在每次终态后往 `<项目根>/sessions/<会话号>.jsonl` 追加一条叙事行），
它自带 `selftest()`，但没有 `tests/test_sessions.py` ——
与 `artifacts.py` 遇到的是同一个缺口（新增模块零回归），
`draft/28` §166 把 `artifacts.py` 那一半补掉了，这一半留作 `R-63`。

## 这一组守什么

1. 落点就是 `<项目根>/sessions/<会话号>.jsonl`（按项目分：换项目就是另一段历史）；
2. 追加写、一行一事件；`ts` 自动补；
3. 坏行逐条报出，不许静默跳过（三态：坏行 ≠ 没有坏行）；
4. 写不进去要返回问题，而不是抛异常（叙事不是判据本身 ⇒ 调用方据此"不改终态"）；
5. 会话号可由 `AGENTFLOW_SESSION` 覆盖；
6. `summarize` 的计数与 `list_sessions` 的逐项读数。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import sessions as SESS


def test_append_and_read_back_one_line_per_event(tmp_path: pathlib.Path):
    """正控：追加两条 ⇒ 落点是 `<root>/sessions/<sid>.jsonl`，读回两条、`ts` 自动补上。"""
    root = tmp_path / "proj"
    sid = "20260101"
    path, problem = SESS.append(root, {"kind": "task_end", "role": "E", "action": "run_experiment",
                                       "outcome": "ok"}, sid=sid)
    assert problem == "" and path is not None
    assert path == SESS.sessions_dir(root) / f"{sid}.jsonl"
    assert path.is_file()
    SESS.append(root, {"kind": "task_end", "role": "H", "action": "review",
                       "outcome": "refused"}, sid=sid)
    events, problems = SESS.read_session(root, sid)
    assert problems == []
    assert [e["role"] for e in events] == ["E", "H"]
    assert all(e.get("ts") for e in events), "每条事件都必须有时间戳（叙事要有时刻）"


def test_sessions_are_isolated_per_project(tmp_path: pathlib.Path):
    """正控（学 harness 的那条）：一个项目一个目录 ⇒ 两个项目互不污染。"""
    a, b = tmp_path / "projA", tmp_path / "projB"
    SESS.append(a, {"kind": "task_end", "role": "A"}, sid="s1")
    # 读的时候要给同一个 `sid`：不给就按"今天"那个会话号找（那是另一段历史）。
    assert SESS.read_session(a, "s1")[0]
    assert SESS.read_session(b) == ([], []), "B 里没有会话（合法初态，不是错误）"
    assert SESS.list_sessions(b) == [], "另一个项目里不该看见 A 的会话"
    assert [s["sid"] for s in SESS.list_sessions(a)] == ["s1"]


def test_a_corrupt_line_is_reported_not_swallowed(tmp_path: pathlib.Path):
    """负控（三态）：坏行必须逐条报出，且不许把好行也吞掉。"""
    root = tmp_path / "proj"
    SESS.append(root, {"kind": "task_end", "role": "E"}, sid="s1")
    with SESS.session_path(root, "s1").open("a", encoding="utf-8") as fh:
        fh.write("{这不是 JSON\n")
        fh.write("[1, 2, 3]\n")          # 合法 JSON，但不是对象
    events, problems = SESS.read_session(root, "s1")
    assert len(events) == 1, events
    assert len(problems) == 2, problems
    assert any("读不出来" in p for p in problems) and any("不是对象" in p for p in problems)
    listed = SESS.list_sessions(root)[0]
    assert listed["events"] == 1 and listed["bad_lines"] == 2


def test_append_failure_returns_a_problem_instead_of_raising(tmp_path: pathlib.Path):
    """负控（fail-soft）：写不进去 ⇒ 返回问题串，不抛 —— 叙事不是判据本身。

    注入方式：把 `sessions` 这个目录位置先占成一个文件 ⇒ `mkdir`/`open` 必然失败。
    """
    root = tmp_path / "proj"
    root.mkdir()
    (root / SESS.SESSIONS_DIR_NAME).write_text("我不是目录\n", encoding="utf-8")
    path, problem = SESS.append(root, {"kind": "task_end"}, sid="s1")
    assert path is None and problem, "写不进去必须返回问题（调用方据此决定不改终态）"
    assert "OSError" in problem or "NotADirectory" in problem or "FileExistsError" in problem, problem


def test_session_id_follows_the_environment_variable(tmp_path: pathlib.Path, monkeypatch):
    """口径：会话号优先取 `AGENTFLOW_SESSION`，否则取当天日期。"""
    monkeypatch.setenv(SESS.ENV_SESSION, "my-session-1")
    assert SESS.session_id() == "my-session-1"
    path, _ = SESS.append(tmp_path, {"kind": "task_end"})
    assert path is not None and path.name == "my-session-1.jsonl"
    monkeypatch.delenv(SESS.ENV_SESSION, raising=False)
    assert SESS.session_id().isdigit() and len(SESS.session_id()) == 8, "默认应当形如 YYYYMMDD"


def test_summarize_counts_roles_outcomes_and_kinds(tmp_path: pathlib.Path):
    """读数：`summarize` 按角色/动作/结局/类别计数（报告要用它）。"""
    events = [
        {"kind": "task_end", "role": "E", "action": "run_experiment", "outcome": "ok"},
        {"kind": "task_end", "role": "H", "action": "review", "outcome": "refused"},
        {"kind": "task_end", "role": "H", "action": "review", "outcome": "ok"},
        {"kind": "note"},
    ]
    s = SESS.summarize(events)
    assert s["roles"] == {"E": 1, "H": 2}
    assert s["actions"] == {"run_experiment": 1, "review": 2}
    assert s["outcomes"] == {"ok": 2, "refused": 1}
    assert s["kinds"] == {"task_end": 3, "note": 1}


def test_selftest_passes():
    """模块自带的自检必须过（它覆盖追加/读回/隔离/坏行四格）。"""
    assert SESS.selftest() == 0
