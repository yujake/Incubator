# -*- coding: utf-8 -*-
"""秘书必装（业主 2026-10-08 T14：「秘书是个流程上的东西，不是可要可不要的，是一定要的，
每唤起一个智能体就自带一个秘书帮它忙前忙后」）。

真机读数（`draft/89` §3）：25 个工作区 1562 行手稿全部是框架派生
（`note` 写着「框架据动作结果派生」/「框架据派活派生」），模型自撰 = 0 ——
因为批量召唤那条路造 `AgentLoop` 时没传秘书（D77），于是那些实例的交差文本写不出来。

这一批把"装配"从"每个调用点记得传"改成"构造即派生"（`__post_init__`），
一处改动同时覆盖：`run_role`（生产主路）、`LlmBackend.call`（批量路）、以及任何裸构造。
`auto_secretary=False` 是留给单测造"没有秘书"那一态的唯一入口（生产路径上不可达）。

判据四半：派生（正控）/ 没有 store 时如实说（三态）/ `auto_secretary=False` 时写路径关闭
（负控）/ 派生出来的秘书真的能写出自撰行（这条才是 T14 的收益）。
"""
from __future__ import annotations

import pathlib

from agentflow.agent_loop import AgentLoop
from agentflow.store import Store
from agentflow.tools import build_registry


def _mk(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return st, ws


def _loop(st: Store, ws: pathlib.Path, **kw: object) -> AgentLoop:
    """按批量路那一处的形状构造（`store` / `registry` / `seam` / `sid` 四样都在）。"""
    from agentflow.llmseam import LlmSeam

    return AgentLoop(role="D", session_root=ws, registry=build_registry(store=st).registry,
                     seam=LlmSeam(role="D", session_root=ws, sid="t14",
                                  gateway=type("G", (), {
                                      "complete": lambda self, p, **k: None})()),
                     store=st, sid="t14", **kw)  # type: ignore[arg-type]


def test_a_bare_loop_derives_its_own_secretary(tmp_path: pathlib.Path):
    """正控（T14 的核心）：不传秘书 ⇒ 构造时就派生了（批量路因此自动得益）。"""
    st, ws = _mk(tmp_path)
    loop = _loop(st, ws)
    assert loop.secretary is not None, loop.secretary_problem
    assert loop.secretary_problem == "", loop.secretary_problem


def test_without_a_store_it_says_so_instead_of_pretending(tmp_path: pathlib.Path):
    """三态：没有 store（派生不出）⇒ 如实写一句理由，不许静默当成"不用装配"。"""
    st, ws = _mk(tmp_path)
    loop = AgentLoop(role="D", session_root=ws, registry=None, seam=None, store=None, sid="x")
    assert loop.secretary is None
    assert "没有 store" in loop.secretary_problem, loop.secretary_problem


def test_auto_secretary_false_keeps_the_write_path_closed(tmp_path: pathlib.Path):
    """负控（唯一的"没有秘书"入口）：`auto_secretary=False` ⇒ 手稿写不成，但这一趟照跑。"""
    st, ws = _mk(tmp_path)
    loop = _loop(st, ws, auto_secretary=False)
    assert loop.secretary is None and loop.secretary_problem == ""
    got = loop._do_handoff({"to": "M", "summary": "s", "body": "b"})
    assert got["ok"] is False and "没有装配秘书" in got["error"], got


def test_a_derived_secretary_writes_a_self_authored_row(tmp_path: pathlib.Path):
    """正控（T14 的收益，真机 0/1562 的反面）：派生出来的秘书真能写出自撰行。

    "自撰"怎么判：行的 `note` 是模型/调用方给的那一句，而不是框架那两句模板
    （「框架据动作结果派生」/「框架据派活派生」）；`sender` 是被服务的角色本人。
    """
    st, ws = _mk(tmp_path)
    loop = _loop(st, ws)
    loop.my_task_id = "t-0007"
    got = loop._do_handoff({"to": "M", "summary": "我这一趟的结论",
                            "body": "正文一句。", "note": "模型自己填的"})
    assert got["ok"] is True, got
    from agentflow import manuscripts as MS

    rows, bad = MS.read_rows(ws)
    assert not bad, bad
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["sender"] == "D" and row["note"] == "模型自己填的", row
    assert str(row["task_id"]) == "t-0007", row            # S2 补的那一格
    assert "框架据" not in str(row["note"]), row
