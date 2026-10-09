# -*- coding: utf-8 -*-
"""S1o：《业主说"和父代理交流即可"》—— "请代唤"改发直接父，不再越级直达 M。

业主 2026-10-09 逐字：

> 「最常见的定义不明极可能是A查论文要B消化时遇到生僻定义，这时和父代理A交流即可」

现场（本 session 现算 `ALLOWED_EDGES`）：能唤起 B 的是 A / D / E / F（+ 顶层 M），
而 B 的出边只有 C ⇒ B 下派不了 A；最常见的场景里 B 的父就是 A（原文在它手里，
就地能给出定义）。而这一档此前写死 `to="M"`（越级：中间那一层看不见、
M 被当路由器）。

判据（正控 2 / 负控 1 / 反真空 2）：

- 正控①：有直接父（父角色 = A）⇒ 申请发给 A（不是 M），读数里写出"为什么是它"；
- 正控②：顶层（没有父 / 父那一行就是我自己）⇒ 发给 M（老行为，只在这一档）；
- 负控：父那一行读不到（未知台账号）⇒ 落回 M，并把原因写进读数（不静默改主、不丢申请）；
- 反真空①：两种收件人下都要留下结构化事件 `agent_summon_request`（可审计）；
- 反真空②：`relay_to` / `relay_why` 两个读数都在（"发给谁、为什么"要能一眼看出来）。
"""
from __future__ import annotations

import pathlib

from agentflow import schema as S
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store


def _loop(tmp_path: pathlib.Path, *, parent_task_id: str, my_task_id: str):
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    # 夹具只需要"能调 `_request_relay`"这一件事：缝给一个空替身即可（本判据不跑循环）
    seam = LlmSeam(role="B", session_root=ws, gateway=None, price=(0.0, 0.0), sid="relay")
    loop = AgentLoop(role="B", session_root=ws, registry=None, conductor=cond,
                     seam=seam, store=st, sid="relay")
    loop.parent_task_id = parent_task_id          # noqa: SLF001 —— 夹具直接摆好父子关系
    loop.my_task_id = my_task_id                  # noqa: SLF001
    return loop, st, cond


def _row(cond: Conductor, role: str) -> str:
    return cond._write_new_row({          # noqa: SLF001 —— 造一行父（与真机同一处建行口）
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": None, "depth": 1, "input_key": f"relay@{role}",
        "status": "running", "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": "父那一趟", "error": None, "started_at": "2026-10-09T00:00:00+08:00",
        "ended_at": None, "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def test_the_relay_goes_to_the_direct_parent(tmp_path: pathlib.Path):
    """正控①：父是 A ⇒ 申请发给 A（最常见的场景：A 查论文、B 消化时撞到生僻定义）。"""
    loop, st, cond = _loop(tmp_path, parent_task_id="", my_task_id="")
    pid = _row(cond, "A")
    loop.parent_task_id = pid                                  # noqa: SLF001
    loop.my_task_id = "t-9999"                                 # noqa: SLF001
    got = loop._request_relay("A", "run_once", {"request": "给个定义"},  # noqa: SLF001
                              "forbidden_edge", "B 没有到 A 的边")
    assert got["to"] == "A", got
    assert "直接父 A" in got["note"], got["note"]
    events = [e for e in st.rows("tasks") if True]              # 事件落在会话里
    assert events, "台账读不成（夹具问题）"
    session = (st.root / "sessions").glob("*.jsonl")
    text = "".join(p.read_text(encoding="utf-8") for p in session)
    assert "agent_summon_request" in text and '"relay_to": "A"' in text, text[-400:]


def test_the_relay_still_goes_to_m_for_a_top_level_agent(tmp_path: pathlib.Path):
    """正控②：顶层（没有父）⇒ 发给 M（老行为只保留在这一档）。"""
    loop, _st, _cond = _loop(tmp_path, parent_task_id="", my_task_id="t-0001")
    got = loop._request_relay("A", "run_once", {}, "forbidden_edge", "x")  # noqa: SLF001
    assert got["to"] == S.CONDUCTOR_ROLE, got
    assert "顶层" in got["note"], got["note"]


def test_a_self_referential_parent_row_is_not_a_parent(tmp_path: pathlib.Path):
    """正控②′：父那一行就是我自己（顶层跑批的行）⇒ 也算顶层 ⇒ 发给 M。"""
    loop, _st, _cond = _loop(tmp_path, parent_task_id="t-0001", my_task_id="t-0001")
    got = loop._request_relay("A", "run_once", {}, "forbidden_edge", "x")  # noqa: SLF001
    assert got["to"] == S.CONDUCTOR_ROLE, got


def test_an_unreadable_parent_falls_back_to_m_with_a_reason(tmp_path: pathlib.Path):
    """负控：父那一行读不到 ⇒ 落回 M，并把原因写进读数（不静默改主、不丢申请）。"""
    loop, _st, _cond = _loop(tmp_path, parent_task_id="t-8888", my_task_id="t-0001")
    got = loop._request_relay("A", "run_once", {}, "forbidden_edge", "x")  # noqa: SLF001
    assert got["to"] == S.CONDUCTOR_ROLE, got
    assert "读不到" in got["note"] and "落回 M" in got["note"], got["note"]
