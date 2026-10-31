# -*- coding: utf-8 -*-
"""判据（先红 · 未修）：运行内与运行外必须喂出同一个 `can_close`（2026-11-03，153-U-01/U-02 第 2 笔的收口）。

## 为什么这一条是 K7 的收口点

`can_close` 的机器口径（`m_says_done ∧ retire.complete ∧ programs_ok`）有两个出口：
运行内 `conductor.closing`（主控在循环里调）与运行外 `agentflow closing`（CLI / 发布门）。
两个出口各喂一份喂参 ⇒ 只要有一边不喂，同一份工作区就会得出两个结论
（一边 `true`、一边 `null`）—— 而那正是 `draft/37` §63 记过的"两个出口读数必须一致"。

## 这条判据钉住什么

1. 同一现场（有顶趟行、树干净、程序 0 个）：运行内与运行外的 `can_close` 必须相等，
   且都是 `True`；两边的 `can_close_reason` 都是空串；
2. 同一现场但找不到顶趟行（喂不上）：两边都必须是 `None` + `not_wired`
   —— 不许一边 `None` 一边 `True/False`（那就是"一个说不知道、一个说可以交"）。
"""
from __future__ import annotations

import io
import pathlib
from contextlib import redirect_stderr, redirect_stdout

from agentflow import cli
from agentflow import closing as CL
from agentflow import conductor as COND
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT


def _ws(tmp_path: pathlib.Path, *, top_level: bool) -> Store:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    if top_level:
        COND.Conductor(st).open_top_level_run("M", "判据：两个出口喂同一份")
    return st


def _tool(store: Store) -> dict:
    res = CT.conductor_closing(store, session={"root": str(store.root), "sid": "probe"},
                               goal_met=True, basis="判据")
    assert res.ok, (res.error, res.meta)
    return dict(res.data or {})


def _cli(store: Store) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        code = cli.main(["--plain", "--root", str(store.root), "closing",
                         "--project-dir", str(store.root), "--goal-met"])
    return int(code), buf.getvalue()


def test_both_exits_feed_the_same_caliber(tmp_path: pathlib.Path) -> None:
    """① 同一现场：运行内与运行外的 `can_close` 相等（今天红：CLI 那边没喂 ⇒ None）。"""
    st = _ws(tmp_path, top_level=True)
    tool = _tool(st)
    code, out = _cli(st)
    assert tool.get("can_close") is True, (tool.get("can_close"), tool.get("can_close_reason"))
    assert tool.get("can_close") == CL.check_closing(
        st, checks=("substance",), goal_met=True,
        retire=CL.machine_feeders(st).get("retire"),
        programs=CL.machine_feeders(st).get("programs")).can_close
    # CLI 出口那一份必须是从盘上现算的同一个值：打出来给读的人看
    assert "can_close" in out, out
    assert ("can_close=True" in out or "can_close=true" in out), (
        "运行外那一趟没有把 `can_close=True` 打出来（它没喂机器口径 ⇒ None）：\n" + out)
    assert code in (0, 1), (code, out)


def test_both_exits_say_unknown_when_the_caliber_cannot_be_fed(
        tmp_path: pathlib.Path) -> None:
    """② 喂不上（没有顶趟行）：两边都 None + `not_wired`，不许一边说可以交。"""
    st = _ws(tmp_path, top_level=False)
    tool = _tool(st)
    code, out = _cli(st)
    assert tool.get("can_close") is None, tool.get("can_close")
    assert "not_wired" in str(tool.get("can_close_reason") or ""), tool.get("can_close_reason")
    assert ("can_close=None" in out or "can_close=null" in out
            or "can_close 算不出来" in out), (
        "运行外那一趟没有如实打出『算不出来』（`can_close` 三态里 None 不许被折成 False）：\n" + out)
    assert "not_wired" in out, out
