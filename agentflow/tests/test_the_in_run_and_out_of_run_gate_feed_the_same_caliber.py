# -*- coding: utf-8 -*-
"""判据（先红 · 未修）：运行内与运行外必须喂出同一个 `can_close`（2026-11-03，153-U-01/U-02 第 2 笔的收口）。

## 为什么这一条是 K7 的收口点

`can_close` 的机器口径（`m_says_done ∧ retire.complete ∧ programs_ok`）有三个出口：
运行内 `conductor.closing`（主控在循环里调）、运行外 `agentflow closing`（CLI / 发布门）、
以及读数 API `readouts.gates_readout`（`agentflow stats gates` 与将来的网页读它）。
三个出口各喂一份喂参 ⇒ 只要有一边不喂，同一份工作区就会得出不同的结论
（一边 `true`、一边 `null`）—— 而那正是 `draft/37` §63 记过的"两个出口读数必须一致"。

## 这条判据钉住什么

1. 同一现场（有顶趟行、树干净、程序 0 个）：运行内 / CLI / API 的 `can_close` 必须相等，
   且都是 `True`；
2. 同一现场但找不到顶趟行（喂不上）：三边都必须是 `None` + `not_wired`
   —— 不许一边 `None` 一边 `True/False`（那就是"一个说不知道、一个说可以交"）。
3. 不存在的 sid（2026-11-03 第二笔）：API 与 CLI 都必须是受控拒绝
   —— 同一句话、同一个码（2）—— 而不是"读成空会话 ⇒ `user_pending` pass"。
   API 那一份不许是"八格全是 unknown"的空读数（`cells` 为空 + `data.refusal` 非空）。
"""
from __future__ import annotations

import io
import pathlib
from contextlib import redirect_stderr, redirect_stdout

from agentflow import cli
from agentflow import closing as CL
from agentflow import conductor as COND
from agentflow import readouts as RO
from agentflow import sessions as SS
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT

#: 这一趟的会话号（运行内 / API / CLI 三个出口读同一段）。
SID = "probe"


def _ws(tmp_path: pathlib.Path, *, top_level: bool) -> Store:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    if top_level:
        COND.Conductor(st).open_top_level_run("M", "判据：两个出口喂同一份")
    # 会话身份（2026-11-03 第二笔）：三个出口都按这一趟的号读；盘上没有这一段时
    # 它们必须一起受控拒绝（见第三条判据），所以"这一段真的在"是前面两条的前提。
    SS.append(root, {"kind": "agent_run_start", "role": "M"}, sid=SID)
    return st


def _tool(store: Store) -> dict:
    res = CT.conductor_closing(store, session={"root": str(store.root), "sid": SID},
                               goal_met=True, basis="判据")
    assert res.ok, (res.error, res.meta)
    return dict(res.data or {})


def _cli(store: Store, *extra: str) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        code = cli.main(["--plain", "--root", str(store.root), "closing",
                         "--project-dir", str(store.root), "--goal-met", *extra])
    return int(code), buf.getvalue()


def _api(store: Store, *, sid: str | None = SID) -> dict:
    """读数 API 出口（`readouts.gates_readout`）—— 与 `agentflow stats gates` 同一份实现。"""
    return RO.gates_readout(store.root, sid=sid)


def test_both_exits_feed_the_same_caliber(tmp_path: pathlib.Path) -> None:
    """① 同一现场：运行内 / CLI / API 的 `can_close` 相等。"""
    st = _ws(tmp_path, top_level=True)
    # 运行内那一趟先跑：它把 M 的判据落到 `out/review/m-verdicts.jsonl`，
    # API / CLI 没有显式判据时读的就是盘上那一份（同一个落点、同一句话）。
    tool = _tool(st)
    code, out = _cli(st)
    api = _api(st)
    # 2026-11-19（ROOTGATE-①）：空工作区的 `substance` 是 fail ⇒ 权威结论 fail
    # （`can_close=false`）。这一条问的不是"能不能交"，而是"三个出口喂的是不是同一份
    # 机器读数" —— 所以先钉住机器那一格真的被喂进来了，再钉三边逐字相等。
    assert tool["readings"]["machine_caliber"]["checked"] is True, tool.get("readings")
    assert tool.get("can_close") is False, (tool.get("can_close"), tool.get("can_close_reason"))
    assert tool.get("can_close") == CL.check_closing(
        st, sid=SID, goal_met=True,
        retire=CL.machine_feeders(st).get("retire"),
        programs=CL.machine_feeders(st).get("programs")).can_close
    # API 出口也必须是从盘上现算的同一个值（它此前不喂机器口径 ⇒ None）。
    assert api["checked"] is True, api
    assert api["data"]["can_close"] == tool["can_close"], (api["data"], tool["can_close"])
    assert api["data"]["closable"] == tool["closable"], (api["data"], tool["closable"])
    # CLI 出口那一份必须是从盘上现算的同一个值：打出来给读的人看
    assert "can_close" in out, out
    assert "can_close=False" in out, (
        "运行外那一趟没有把 `can_close=False` 打出来：\n" + out)
    assert code == 1, (code, out)


def test_both_exits_say_not_wired_when_the_caliber_cannot_be_fed(
        tmp_path: pathlib.Path) -> None:
    """② 喂不上（没有顶趟行）：三边都记 `not_wired`，没有一边把它读成"可以交"。

    2026-11-19（ROOTGATE-①）之后 `can_close` 还读八格：这一份空工作区的 `substance`
    是 fail ⇒ 权威结论 fail（不是 None）。所以这一条钉的是机器那一格没接线
    （`machine_caliber.checked=False` + `not_wired` 出现在三个出口），而不是
    "can_close 一定是 None" —— 后者只在八格全 pass 时才成立。

    2026-11-19 业主口径：台账里**没有树**是查过的干净（干净工作区必须 pass/0），
    所以"喂不上"要造一支**断头的树**（有父行、没有顶趟行）—— 那才是"根判不了"。
    """
    st = _ws(tmp_path, top_level=False)
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {"task_id": "t-000002", "role": "C", "action": "run_once",
                            "called_by": "M", "parent_task_id": "t-000099",
                            "status": "done", "outcome": "ok",
                            "detail": "断头树里的子行（没有顶趟行）",
                            "started_at": "2026-11-19T18:00:00+08:00",
                            "ended_at": "2026-11-19T18:01:00+08:00"})
    tool = _tool(st)
    code, out = _cli(st)
    api = _api(st)
    caliber = dict((tool.get("readings") or {}).get("machine_caliber") or {})
    assert caliber.get("checked") is False, caliber
    assert "not_wired" in str(caliber.get("reason") or ""), caliber
    assert tool.get("can_close") is False, tool.get("can_close")
    assert "not_wired" in str(tool.get("can_close_reason") or ""), tool.get("can_close_reason")
    assert api["data"]["can_close"] == tool["can_close"], (api["data"], tool["can_close"])
    assert "not_wired" in out, (
        "运行外那一趟没有如实打出『机器读数没接线』：\n" + out)
    assert code == 1, (code, out)


def test_the_api_refuses_a_session_that_is_not_on_disk(tmp_path: pathlib.Path) -> None:
    """③ 不存在的 sid：API 与 CLI 是同一个受控拒绝（同一句话、同一个码 2）。

    改前：API 直接调 `check_closing(sid=…)`，`sessions.read_session` 把"文件不存在"
    读成空会话 ⇒ `user_pending` 是 `pass`；而 CLI 侧已经拒绝（e4e5efff）。
    同一件事两个出口，一个拒绝一个放行。
    """
    st = _ws(tmp_path, top_level=True)
    api = _api(st, sid="no-such-session")
    assert api["checked"] is False, api
    assert api["state"] == "unknown", api["state"]
    refused = api["data"]["refusal"]
    assert refused, api["data"]
    assert refused["code"] == "no_such_session", refused
    assert refused["exit_code"] == 2, refused
    assert "没有会话 'no-such-session'" in api["reason"], api["reason"]
    # 不是"八格全是没查成"的空读数：门根本没跑，cells 为空。
    assert api["data"]["cells"] == [], api["data"]["cells"]
    assert api["data"]["can_close"] is None, api["data"]

    code, out = _cli(st, "--sid", "no-such-session")
    assert code == 2, (code, out)
    # 同一句话：API 的 detail 必须逐字出现在 CLI 的输出里（两处共用一个身份判据）。
    assert refused["detail"] in out, (refused["detail"], out)
    assert "不跑收工门" in out, out


def test_the_in_run_tool_refuses_the_same_way_and_writes_nothing(
        tmp_path: pathlib.Path) -> None:
    """③b 运行内那个出口同样受控拒绝，而且"拒绝 = 一行都不写"（判据不许先落盘）。

    `conductor.closing` 拿到 `goal_met=True` 时会先把 M 的判据落到
    `out/review/m-verdicts.jsonl`；会话号不存在时这个落盘必须不发生
    —— 否则一次被拒绝的调用仍然改了盘。
    """
    st = _ws(tmp_path, top_level=True)
    res = CT.conductor_closing(st, session={"root": str(st.root), "sid": "no-such-session"},
                               goal_met=True, basis="判据")
    assert res.ok is False, (res.error, res.meta)
    assert res.meta.get("refused") is True, res.meta
    assert res.meta.get("exit_code") == 2, res.meta
    assert "没有会话 'no-such-session'" in str(res.error), res.error
    assert not (st.root / "out" / "review" / "m-verdicts.jsonl").is_file(), (
        "受控拒绝的调用把 M 的判据写进盘了（拒绝必须一行都不写）")
