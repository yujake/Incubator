# -*- coding: utf-8 -*-
"""判据：没给运行号的收工门读数不许把「待答问题」读成 pass（2026-11-14 真机假绿）。

## 现场（G1 报告与 `temp/g1_probe_user_pending.py`）

`sessions.session_path(root, sid=None)` 回落到 `session_id()` = `"%Y%m%d"`（`sessions.py:79-88`），
而真机上真会话的名字是 ISO 日期（`2026-11-14.jsonl`，1771 条）：

```text
107 个工作区里，sessions/<YYYYMMDD>.jsonl 只有 1 个存在（lp-ball，而且是另一段 79 条）
真会话 sessions/2026-11-14.jsonl 1771 条
⇒ 106/107 的 `agentflow stats gates` 读的是一个不存在的文件 ⇒ 0 待答 ⇒ user_pending: pass
```

假绿只落在读数出口：`agentflow stats gates` → `_stats_readout` → `gates_readout(sid=None)`。
判据层本身是诚实的（`check_closing(sid=None)` = 读缺省会话，那是运维口径；
`agentflow closing` 缺省是 `NO_SESSION`）。

## 修法（业主裁定：改调用方，不改判据层）

`gates_readout` 不给 `sid` ⇒ 与 `closing.NO_SESSION` 同值（这次调用没有运行号）。
于是「待答问题」那一格记 `unknown`（不是 pass），并在 `problems` 里点名"没给运行号"。
要读某一趟就显式给那个号；显式给 `None` 才是运维口径的「读缺省会话」。

## 五条判据

| # | 判据 | 反真空 / 负控 |
|---|---|---|
| a | 不给 `sid` ⇒ `user_pending` 是 `unknown`，且读数点名"没给运行号" | 同一份工作区显式给号 ⇒ `fail`（那个问题真的在盘上，不是"文件里没东西"） |
| b | 给真实 sid 且会话里有未答问题 ⇒ `fail` + blocker 点名 qid | —— |
| c | 给真实 sid 且无未答 ⇒ `pass` | 与 b 同一副夹具，只差那一行提问 |
| d | 把缺省值打桩回改前的 `None` ⇒ a 仍不是 `unknown` | 证明 a 不是恒绿：旧缺省在同一个工作区上给的是 `na`（2026-11-20 四态；改前是假绿 `pass`） |
| e | `gates_readout` 的缺省值逐字等于 `closing.NO_SESSION` | 两处字面量漂开时这条红（`session_path` 的缺省回落会重新生效） |

e 是这一组的"词表钉"：`closing.NO_SESSION == ""` 由
`test_session_context_wiring.py::test_the_judge_itself_has_the_third_input` 钉着；
这里再钉读数层的缺省与它是同一个值，免得有人把缺省改成另一个看着像空的东西。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import closing as CL
from agentflow import readouts as R
from agentflow import sessions as SS
from agentflow.store import Store

#: 这一趟真正的会话号（真机上的形态：ISO 日期）。
SID = "2026-11-14"

#: `sessions.session_path` 在 `sid=None` 时回落到的那一个号（`"%Y%m%d"`）。
DEFAULT_SID = SS.session_id()


def _ws(tmp_path: pathlib.Path, *, ask: bool) -> pathlib.Path:
    """造一个工作区：真会话 `sessions/2026-11-14.jsonl` 在，缺省会话文件不在。

    `ask=True` 时那一段里有一个没人回答的 `user_question`；`False` 时只有一条开场行
    （两档都能让门跑到「待答问题」那一格，差别只有那一个问题）。
    """
    ws = tmp_path / "ws"
    Store(ws).init()
    SS.append(ws, {"kind": "agent_run_start", "role": "M"}, sid=SID)
    if ask:
        SS.append(ws, {"kind": "user_question", "role": "M", "qid": "q0001",
                       "text": "这一版要不要交？", "options": ["交", "再改"],
                       "timeout_sec": 60.0}, sid=SID)
    return ws


def _cell(got: dict, name: str) -> dict:
    """读数里点名的那一格（八格改七格、顺序变化都不影响这条判据）。"""
    cells = {str(c.get("name")): c for c in (got.get("data", {}).get("cells") or [])}
    assert name in cells, f"读数里没有 {name} 这一格：{sorted(cells)}"
    return cells[name]


def _no_sid_problem(got: dict) -> str:
    """读数里那句"没给运行号"（`problems` 的口径见 `readouts._envelope`）。"""
    return "；".join(str(p.get("detail") or "") for p in (got.get("problems") or ())
                     if str(p.get("code") or "") == "no_session")


def test_the_fixture_really_has_the_two_session_files_apart() -> None:
    """夹具前提：缺省号与这一趟的号不是一个（否则 a 与 b 会指到同一个文件）。"""
    assert DEFAULT_SID != SID, (
        f"缺省会话号与这一趟的号撞了（都是 {SID!r}）⇒ 假绿在这副夹具上看不出来")
    # 反真空：`sessions.session_path(sid=None)` 真的会回落到缺省号（那是假绿的来路）
    assert SS.session_path(".", sid=None).name == f"{DEFAULT_SID}.jsonl"
    assert SS.session_path(".", sid=SID).name == f"{SID}.jsonl"


def test_a_without_a_run_number_the_cell_is_unknown_and_says_so(
        tmp_path: pathlib.Path) -> None:
    """a：不给运行号 ⇒ `unknown` + 点名，不是 pass。"""
    ws = _ws(tmp_path, ask=True)
    assert not (ws / "sessions" / f"{DEFAULT_SID}.jsonl").is_file(), (
        "夹具不成立：缺省会话文件居然在盘上（假绿会被它自己遮住）")

    got = R.gates_readout(ws)  # 不给 sid —— 与 `agentflow stats gates` 同一条路
    assert got["checked"] is True, got["reason"]
    assert _cell(got, "user_pending")["status"] == "unknown", _cell(got, "user_pending")
    assert _no_sid_problem(got), (
        "读数说 unknown 却没说为什么：读的人会把它读成『没拦住』。"
        f"problems={got.get('problems')}")

    # 反真空：同一份工作区、同一段会话，显式给号 ⇒ 那个问题真的看得见（fail）。
    named = R.gates_readout(ws, sid=SID)
    assert _cell(named, "user_pending")["status"] == "fail", _cell(named, "user_pending")
    assert "q0001" in str(_cell(named, "user_pending")["detail"]), _cell(named, "user_pending")


def test_b_a_real_run_number_with_an_unanswered_question_is_fail(
        tmp_path: pathlib.Path) -> None:
    """b：显式给真实 sid、会话里有未答问题 ⇒ `fail`（唯一出口口径）。"""
    ws = _ws(tmp_path, ask=True)
    got = R.gates_readout(ws, sid=SID)
    cell = _cell(got, "user_pending")
    assert cell["status"] == "fail", cell
    assert "q0001" in str(cell["detail"]), cell
    assert any("waiting_for_user" in str(p.get("code") or "") for p in got["problems"]), (
        got["problems"])


def test_c_a_real_run_number_without_questions_is_pass(tmp_path: pathlib.Path) -> None:
    """c：显式给真实 sid、没有未答 ⇒ `pass`（与 b 只差那一行提问）。"""
    ws = _ws(tmp_path, ask=False)
    got = R.gates_readout(ws, sid=SID)
    assert _cell(got, "user_pending")["status"] == "pass", _cell(got, "user_pending")
    assert not _no_sid_problem(got), (
        "给了号却还报『没给运行号』：那句话成了恒挂的噪声")


def test_d_stubbing_the_default_back_to_none_brings_the_false_green_back(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d（负控）：把缺省值打桩回改前的 `None` ⇒ 同一个工作区上 a 仍不是 unknown。

    打的是「缺省值本身」（`__kwdefaults__`），不是把 `gates_readout` 整个换掉 ——
    换掉的话证明的是"夹具能红"，不是"这一行改动是拦住假绿的那一行"。

    2026-11-20（EMPTYCELL）：旧的缺省（`sid=None` 去读缺省会话）在这副夹具上曾经给出
    `pass` —— 那是这一条最初要复现的假绿。四态落地之后，那个文件不在盘上会让这一格
    记 `na`（没有提问可判），于是旧缺省现在给 `na` 而不是 `pass`：假绿被两层同时挡住
    （调用方不给号 ⇒ unknown；判据层没有会话记录 ⇒ na），a 的分辨力仍在
    （`unknown` 与 `na` 不是同一个词）。
    """
    ws = _ws(tmp_path, ask=True)
    assert _cell(R.gates_readout(ws), "user_pending")["status"] == "unknown", (
        "先证明没打桩时是 unknown（否则下面那条红是假红）")

    monkeypatch.setitem(R.gates_readout.__kwdefaults__, "sid", None)  # ← 改前的缺省
    old = R.gates_readout(ws)
    assert _cell(old, "user_pending")["status"] == "na", (
        "改前的缺省（sid=None）在这副夹具上读缺省会话文件；那个文件不在盘上 ⇒ 这一格"
        f"记 na（没有提问可判），不是 pass 也不是 unknown：{_cell(old, 'user_pending')}")
    assert not _no_sid_problem(old), old["problems"]


def test_e_the_readout_default_is_the_judges_no_session_sentinel() -> None:
    """e：读数层的缺省会话身份与 `closing.NO_SESSION` 是同一个值。"""
    default = R.gates_readout.__kwdefaults__["sid"]
    assert default == CL.NO_SESSION, (default, CL.NO_SESSION)
    assert default is not None, "缺省又变回 None 了 ⇒ `session_path` 的缺省回落会重新生效"
