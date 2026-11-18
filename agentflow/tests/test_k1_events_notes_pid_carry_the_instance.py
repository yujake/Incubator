# -*- coding: utf-8 -*-
"""K1 收尾①：会话事件 / 草稿本 / 进程登记 / 形态台账都带实例身份。

## 为什么有这一批（业主口径，逐字）

> 每个 F 自己管自己的计划与稿，名册名就是实例身份。

K1 的根因是「实例身份只到角色」：装配期拿得到 instance，落盘面却只写角色字面量。
BATCH1–6 已经把计划 / 稿 / claims / ARTIFACTS / 事件 actor 这几格接上 `identity`，本批
收的是运行期那几件「每支笔一份」的东西：会话事件、草稿本、进程登记、形态台账。

## 判据

| # | 判据 | 条目 |
|---|---|---|
| a | 事件带 `instance`；读不到的那一笔不写这个键（三态：没读到 ≠ 没有实例） | SH-24 |
| b | 草稿本按 `(角色, 实例)` 分文件、`ARTIFACTS.producer` 是实例级；读不到实例 ⇒ 与改前同名同值 | SH-01 |
| c | 进程登记按 `(角色, 实例, 会话)` 分文件：两支笔同会话各有自己那一份，注销一份不动另一份 | SH-03 |
| d | E 的形态台账行带本趟台账号（改前调用点从不给 ⇒ `task_id=''`） | SH-04 |

反真空都在同一个用例里：把实例标签摘掉，读数退回改前形态（同名文件 / 角色名 /
空台账号）—— 绿不是「什么都没写」给的。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import conductor as C  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import sessions as SS  # noqa: E402
from agentflow import stopctl as SC  # noqa: E402
from agentflow.agent_loop import note_path, notebook_digest, write_note  # noqa: E402
from agentflow.identity import current_instance  # noqa: E402
from agentflow.store import Store  # noqa: E402

from test_e_side_proposition_form_gate import (  # noqa: E402
    WELL_FORMED, _e as _e_agent, _run as _run_experiment, _well_formed_seam, _write,
)


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


def _events(root: pathlib.Path, sid: str) -> list[dict]:
    rows, _problems = SS.read_session(root, sid)
    return rows


def _artifacts(root: pathlib.Path) -> list[dict]:
    path = root / "ARTIFACTS.jsonl"
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            out.append(json.loads(text))
    return out


# ------------------------------------------------------------------ a 事件
def test_a_events_carry_the_instance_and_say_so_when_they_cannot(
        tmp_path: pathlib.Path) -> None:
    """a：`conductor.calling_as(instance=…)` 里写的每一条事件都带实例标签。"""
    root = _root(tmp_path)
    with C.calling_as("t-000001", role="V", instance="v2"):
        assert current_instance() == "v2"
        _p, problem = SS.append(root, {"kind": "agent_step", "role": "V"}, sid="s1")
    assert problem == ""
    rows = _events(root, "s1")
    assert [r.get("instance") for r in rows] == ["v2"], rows

    # 反真空 + 三态：没有实例的那一笔不写这个键（写空串会把「没读到」折成「没有实例」）。
    SS.append(root, {"kind": "agent_note", "role": "M"}, sid="s1")
    last = _events(root, "s1")[-1]
    assert "instance" not in last, last
    # 写者显式给的那一格优先于挂点（审计面要的是「这一笔是谁」，不是「谁正挂着」）。
    with C.calling_as("t-000002", role="V", instance="v3"):
        SS.append(root, {"kind": "agent_step", "role": "V", "instance": "v-explicit"},
                  sid="s1")
    assert _events(root, "s1")[-1]["instance"] == "v-explicit"


# ------------------------------------------------------------------ b 草稿本
def test_b_the_notebook_is_per_instance(tmp_path: pathlib.Path) -> None:
    """b：两支 E 的草稿本不是同一份文件；`producer` 是实例级。"""
    root = _root(tmp_path)
    assert note_path(root, "E", "e1").name == "E-e1.md"
    assert note_path(root, "E", "e2").name == "E-e2.md"
    # 反真空：读不到实例 ⇒ 与改前同名（`notes/E.md`）、producer 也和改前一样是角色名。
    assert note_path(root, "E", "").name == "E.md"

    p1, prob1 = write_note(root, "E", "第一支笔想到的", instance="e1")
    p2, prob2 = write_note(root, "E", "第二支笔想到的", instance="e2")
    assert (prob1, prob2) == ("", ""), (prob1, prob2)
    assert pathlib.Path(p1) != pathlib.Path(p2), (p1, p2)
    assert "第一支笔" in pathlib.Path(p1).read_text(encoding="utf-8")
    assert "第二支笔" not in pathlib.Path(p1).read_text(encoding="utf-8")
    assert notebook_digest(root, "E", instance="e2").endswith("第二支笔想到的")
    assert "第一支笔" not in notebook_digest(root, "E", instance="e2")

    producers = {row["path"]: row["producer"] for row in _artifacts(root)
                 if str(row.get("kind") or "") == "note"}
    assert producers.get("notes/E-e1.md") == "agent-E-e1", producers
    assert producers.get("notes/E-e2.md") == "agent-E-e2", producers

    # 反真空：摘掉实例 ⇒ 落回 `notes/E.md`，producer 退回角色名（改前读数）。
    p0, _ = write_note(root, "E", "没有实例的那一支")
    assert pathlib.Path(p0).name == "E.md"
    assert {row["producer"] for row in _artifacts(root)
            if str(row.get("path") or "") == "notes/E.md"} == {"E"}, _artifacts(root)


# ------------------------------------------------------------------ c 进程登记
def test_c_pid_registrations_are_per_instance(tmp_path: pathlib.Path) -> None:
    """c：同一会话里的两支笔各有自己那份 pid 登记，注销一份不动另一份。"""
    root = _root(tmp_path)
    one = SC.register_pid(root, "E", "s1", pid=os.getpid(), instance="e1")
    two = SC.register_pid(root, "E", "s1", pid=os.getpid(), instance="e2")
    assert one != two, (one, two)
    assert one.is_file() and two.is_file()
    body = json.loads(two.read_text(encoding="utf-8"))
    assert body["instance"] == "e2" and body["role"] == "E", body
    assert SC.unregister_pid(root, "E", "s1", instance="e1") is True
    assert not one.is_file() and two.is_file(), (one, two)

    # 反真空：不传实例 ⇒ 与改前同一个文件名 `runs/E-s1.pid`（覆盖写的老形态）。
    old = SC.register_pid(root, "E", "s1", pid=os.getpid())
    assert old.name == "E-s1.pid"
    assert SC.register_pid(root, "E", "s1", pid=os.getpid()) == old


# ------------------------------------------------------------------ d 形态台账
def test_d_the_form_ledger_row_carries_the_task_id(tmp_path: pathlib.Path) -> None:
    """d：E 走数值证明路线时，形态台账那一行答得出「这是哪一趟」。"""
    st = Store(tmp_path / "ws")
    st.init()
    _write(st)
    agent = _e_agent(st, _well_formed_seam())
    with C.calling_as("t-000123", role="E", instance="e1"):
        out = _run_experiment(agent, WELL_FORMED)
        assert out["recorded"] is True, out
    rows = SEC.proposition_form_rows(st.root)
    assert rows, "形态台账一行都没有（判据自己没走到那一格）"
    assert str(rows[-1].get("task_id")) == "t-000123", rows[-1]
    assert str(rows[-1].get("role")) == "E", rows[-1]

    # 反真空：不在召唤上下文里跑 ⇒ 台账号是空串（改前的读数），可见那一格是挂点给的。
    st2 = Store(tmp_path / "ws2")
    st2.init()
    _write(st2)
    agent2 = _e_agent(st2, _well_formed_seam())
    out2 = _run_experiment(agent2, WELL_FORMED)
    assert out2["recorded"] is True, out2
    rows2 = SEC.proposition_form_rows(st2.root)
    assert rows2 and str(rows2[-1].get("task_id")) == "", rows2[-1:]
