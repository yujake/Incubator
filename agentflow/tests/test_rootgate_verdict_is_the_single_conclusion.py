# -*- coding: utf-8 -*-
"""ROOTGATE · 一份权威结论：`closing.closing_verdict` 是"能不能交"的唯一判据。

## 这一份回答什么（业主 2026-11-19 裁定：「要修根因」）

根因①：改前有两条互不相干的轴 ——

```text
can_close  = m_says_done ∧ retire.complete ∧ programs_ok   # 不读那八格
machine_pass = 八格全 pass ∧ 没有 blocker                  # 不读机器口径
tri_state_exit_code = 只在两边都说行时给 0
```

于是真机 `projects/lp-ball-11` 的八格 6/8（`acceptance` / `literature_pending` 红）
仍然 `exit 0`，读日志的人把它当成跑成了。根因②：`closing.machine_feeders` 不做
自动收尾，读的是"收尾前"的旧快照，而 `final` 闸在 38 秒后把静默节点销掉 ⇒
最后一次 closing 必写"retire 不干净"，读数与事实错位。

## 钉住的六条

| 判据 | 现场 | 期望 |
|---|---|---|
| a | 彩排 8/8（复用 REH8 的工作区，不重造） | `verdict=pass` · `can_close=True` · exit 0 |
| b | 同一工作区把 `acceptance` + `literature_pending` 弄坏（6/8） | `verdict=fail` · `can_close=False` · exit 1 |
| c | 任一格没查成（打桩抛异常） | `verdict=unknown` · `can_close=None` · exit 2 |
| d | 八格逐格各弄坏一次 | 该格 fail · `verdict=fail` · exit 1 |
| e | 静默且无未消项 / 有未消项 | closing 的 retire 格分别"不报不干净" / "必须报不干净" |
| f | 把 ① 的"读八格"打桩掉 | b 回到旧形态（`can_close=true`）⇒ b 的断言必红 |

## 为什么复用 REH8 而不是另造一份工作区

`tests/test_rehearsal_closing_eight_cells.py` 已经用真 `store.tx` 台账 + 真签 + 真清表
+ 假模型造出了"八格能同时 pass"的现场（业主：「除非彩排能做出来收工闸全过，不然
不轻易动」）。这一份只借它的 `build()` / `gate()` / `BREAKS` / `_break()`，
不复制任何一张表 —— 两份工作区一旦分叉，"6/8 现场"就不再是同一个现场。
"""
from __future__ import annotations

import io
import pathlib
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from typing import Any

import pytest

import test_rehearsal_closing_eight_cells as REH8

from agentflow import agent_loop as AL
from agentflow import cli as CLI
from agentflow import closing as CL
from agentflow import schema as S
from agentflow.store import Store

#: 彩排任务行的固定时刻（与 REH8 同一天；只用于台账行的可读性）。
TS = "2026-11-19T18:00:00+08:00"


# ============================================================ 一 断言助手（f 打桩时复用）


def _six_of_eight_assertions(rep: CL.ClosingReport) -> None:
    """判据 b 的全部断言 —— 单独成函数，判据 f 要拿它证明"打桩掉读八格必红"。"""
    got = CL.closing_verdict(rep)
    assert got["verdict"] == "fail", got
    cells = {c["check"]: c for c in got["cells"]}
    assert set(cells) == set(CL.DEFAULT_CHECKS), sorted(cells)
    assert cells["acceptance"]["status"] == "fail", cells["acceptance"]
    assert cells["literature_pending"]["status"] == "fail", cells["literature_pending"]
    # 红的格必须说得出来为什么（不许只有 status，没有 why）
    assert cells["acceptance"]["why"], cells["acceptance"]
    assert cells["literature_pending"]["why"], cells["literature_pending"]
    # M 说的是"做完了" —— 这正是旧形态 exit 0 的来源；新结论不许被它掩盖
    assert rep.m_says_done is True, rep.to_dict()
    assert got["m_says_done"] is True, got
    assert rep.can_close is False, (rep.can_close, rep.can_close_reason)
    assert rep.machine_pass is False, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 1, CL.tri_state_exit_code(rep)


# ============================================================ 二 判据 a：8/8 ⇒ pass / 0


def test_a_eight_of_eight_is_one_pass_conclusion(tmp_path: pathlib.Path) -> None:
    """彩排 8/8 现场 ⇒ 三个名字读出同一份结论（verdict=pass、can_close=true、exit 0）。"""
    store, _root = REH8.build(tmp_path)
    rep = REH8.gate(store)
    got = CL.closing_verdict(rep)

    assert got["verdict"] == "pass", got
    assert got["m_says_done"] is True, got
    assert got["retire"]["checked"] is True and got["retire"]["complete"] is True, got["retire"]
    assert got["programs"]["checked"] is True and got["programs"]["ok"] is True, got["programs"]
    assert got["blockers"] == [], got["blockers"]
    assert [c["check"] for c in got["cells"]] == list(CL.DEFAULT_CHECKS), got["cells"]
    assert {c["status"] for c in got["cells"]} == {"pass"}, got["cells"]
    assert rep.can_close is True, rep.can_close_reason
    assert rep.machine_pass is True, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 0, CL.tri_state_exit_code(rep)


# ============================================================ 三 判据 b：6/8 ⇒ fail / 非 0


def test_b_six_of_eight_is_a_failure_not_an_exit_zero(tmp_path: pathlib.Path) -> None:
    """真机 lp-ball-11 的形态：`acceptance` + `literature_pending` 红，M 仍说达成。

    改前：`can_close=true`（它不读八格）、`machine_pass=false`、退出码 1 —— 但真机那一趟
    的 exit 0 来自运行收工（`stop_reason=final`），所以这一条同时钉住"八格进结论"。
    """
    store, root = REH8.build(tmp_path)
    REH8._break(root, store, "acceptance")
    REH8._break(root, store, "literature_pending")
    rep = REH8.gate(store)
    _six_of_eight_assertions(rep)


# ============================================================ 四 判据 c：unknown ≠ pass


def test_c_any_unknown_cell_makes_the_whole_verdict_unknown(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """任一格没查成 ⇒ `verdict=unknown`、`can_close=None`、exit 2（三态不许折平）。"""

    def _boom(*_a: Any, _k: Any) -> None:
        raise RuntimeError("ROOTGATE 彩排：这一格没查成")

    monkeypatch.setattr(CL, "_check_acceptance", _boom)
    store, _root = REH8.build(tmp_path)
    rep = REH8.gate(store)
    got = CL.closing_verdict(rep)

    assert got["verdict"] == "unknown", got
    assert "acceptance" in [c["check"] for c in got["cells"] if c["status"] == "unknown"], got
    assert rep.status["acceptance"] == "unknown", rep.status
    assert rep.m_says_done is True, "夹具前提：M 说达成（unknown 不许被它折成 pass）"
    assert rep.can_close is None, (rep.can_close, rep.can_close_reason)
    assert rep.closable is False, "unknown 不是'能停'"
    assert CL.tri_state_exit_code(rep) == 2, CL.tri_state_exit_code(rep)


# ============================================================ 五 判据 d：八格逐格有牙


def test_d_every_cell_has_a_tooth_in_the_one_verdict(tmp_path: pathlib.Path) -> None:
    """八格逐条各弄坏一次 ⇒ 该格 fail、`verdict=fail`、`can_close=false`、exit 1。"""
    for cell in CL.DEFAULT_CHECKS:
        case = tmp_path / cell
        case.mkdir()
        store, root = REH8.build(case)
        REH8._break(root, store, cell)
        rep = REH8.gate(store)
        got = CL.closing_verdict(rep)
        one = {c["check"]: c for c in got["cells"]}[cell]
        assert one["status"] == "fail", (cell, one, got)
        assert one["why"], (cell, one)
        assert got["verdict"] == "fail", (cell, got)
        assert rep.can_close is False, (cell, rep.can_close, rep.can_close_reason)
        assert CL.tri_state_exit_code(rep) == 1, (cell, CL.tri_state_exit_code(rep))


# ============================================================ 六 判据 e：retire 快照不错位


def _retire_workspace(tmp_path: pathlib.Path, *, with_open_item: bool) -> Store:
    """一个最小的真台账：M 顶趟 + 一个已完工的静默子代理（可选：它名下一条未消项）。"""
    root = tmp_path / "retire-ws"
    root.mkdir()
    store = Store(root)
    store.init()
    rows = [
        {"task_id": "t-000001", "role": "M", "action": "run", "called_by": "user",
         "status": "running", "started_at": TS},
        {"task_id": "t-000002", "role": "C", "action": "relation_paths", "called_by": "M",
         "parent_task_id": "t-000001", "status": "done", "outcome": "ok",
         "detail": "跑了一次关系分析", "started_at": TS, "ended_at": TS},
    ]
    if with_open_item:
        rows.append({
            "task_id": "t-000003", "role": "M", "action": "notice", "called_by": "M",
            "parent_task_id": "t-000002", "status": "pending", "kind": "notice",
            "expects": "ack", "item_state": "queued", "started_at": TS})
    with store.tx("tasks", actor="rootgate") as tx:
        for row in rows:
            tx.upsert("tasks", row)
    return store


def test_e_a_silent_node_with_no_open_items_is_not_reported_dirty(
        tmp_path: pathlib.Path) -> None:
    """静默且无未消项 ⇒ closing 的 retire 格不报"不干净"（收尾前自动收尾会销它）。"""
    store = _retire_workspace(tmp_path, with_open_item=False)
    feed = CL.machine_feeders(store, root_task_id="t-000001")
    retire = dict(feed["retire"])
    assert retire.get("checked") is True, retire
    assert retire.get("complete") is True, retire
    assert retire.get("projected") is True, retire
    assert "t-000002" in (retire.get("auto_retire") or {}).get("would_retire", []), retire
    assert "不干净" not in str(retire.get("reason") or ""), retire
    # 同一份读数喂进机器口径 ⇒ can_close 能成立（不是靠"没检查"通过）
    caliber = CL.machine_caliber(m_says_done=True, retire=retire, programs=feed["programs"])
    assert caliber["value"] is True, caliber


def test_e_a_node_with_open_items_still_reports_dirty(tmp_path: pathlib.Path) -> None:
    """反真空：名下有未消项 ⇒ 必须报不干净（自动收尾不会碰它）。"""
    store = _retire_workspace(tmp_path, with_open_item=True)
    feed = CL.machine_feeders(store, root_task_id="t-000001")
    retire = dict(feed["retire"])
    assert retire.get("checked") is True, retire
    assert retire.get("complete") is False, retire
    assert retire.get("projected") is False, retire
    assert "t-000002" not in (retire.get("auto_retire") or {}).get("would_retire", []), retire
    kept = (retire.get("auto_retire") or {}).get("kept") or []
    assert any(str(k.get("task_id") or "") == "t-000002" for k in kept), retire
    caliber = CL.machine_caliber(m_says_done=True, retire=retire, programs=feed["programs"])
    assert caliber["value"] is False, caliber


# ============================================================ 七 判据 f：打桩掉"读八格"必红


def test_f_stubbing_out_the_cells_turns_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 ① 的"读八格"打桩掉 ⇒ b 回到旧形态（`can_close=true`）⇒ b 的断言必红。

    这个桩就是 2026-11-03 裁决 ①=乙 的旧形态：只看 `machine_caliber.value`，不读八格。
    它证明 b 不是恒绿：真的有人在结论里读八格，b 才有牙。
    """
    store, root = REH8.build(tmp_path)
    REH8._break(root, store, "acceptance")
    REH8._break(root, store, "literature_pending")
    rep = REH8.gate(store)

    def _old_two_axis(one: CL.ClosingReport) -> dict[str, Any]:
        caliber = dict((one.readings or {}).get("machine_caliber") or {})
        value = caliber.get("value")
        verdict = "pass" if value is True else ("fail" if value is False else "unknown")
        return {"verdict": verdict, "value": value,
                "cells": [{"check": n, "status": one.status.get(n, "unknown"), "why": ""}
                          for n in CL.DEFAULT_CHECKS],
                "m_says_done": one.m_says_done, "blockers": [],
                "machine_pass": all(v == "pass" for v in one.status.values())
                                 and not one.blockers,
                "can_close": True if value is True else (False if value is False else None),
                "exit_code": 0 if value is True else (1 if value is False else 2),
                "retire": {}, "programs": {}}

    monkeypatch.setattr(CL, "closing_verdict", _old_two_axis)
    assert rep.can_close is True, "旧形态下 can_close 不读八格 ⇒ 6/8 仍是 true"
    with pytest.raises(AssertionError):
        _six_of_eight_assertions(rep)


# ============================================================ 八 运行收工：6/8 不许 exit 0


def _closing_loop(tmp_path: pathlib.Path, state: str) -> SimpleNamespace:
    """一个"研究型项目"的最小循环壳：收工门跑过、结论是 `state`。"""
    root = tmp_path / f"loop-{state}"
    root.mkdir()
    store = Store(root)
    store.init()
    q = S.ResearchQuestion(question_id="000000", question="m-正则图的围长下界是多少？",
                           status="answered", priority="high", kind="gap",
                           created_at=TS, updated_at=TS)
    q.validate()
    with store.tx("research_questions", actor="rootgate") as tx:
        tx.upsert("research_questions", q.to_dict())
    return SimpleNamespace(
        store=store, workspace_root=str(root), role="M",
        _closing_gate_readings=[{"verdict": {"verdict": state, "authoritative": True,
                                             "reason": "夹具有意"}}])


def test_g_a_six_of_eight_run_does_not_stop_with_exit_zero(tmp_path: pathlib.Path) -> None:
    """运行收工也读同一份结论：verdict=fail ⇒ `closing_failed` ⇒ 退出码 1（不是 0）。

    这一条钉的正是真机 `lp-ball-11` 的那一步：八格 6/8、模型交 final，而
    `stop_reason=final` 让命令以 0 结束。三态各一档（fail=1 / unknown=2 / pass=0），
    unknown 与 fail 不许挤进同一个码。
    """
    for state, stop, code in (("fail", AL.CLOSING_FAILED_STOP, 1),
                              ("unknown", AL.CLOSING_UNKNOWN_STOP, 2),
                              ("pass", "final", 0)):
        loop = _closing_loop(tmp_path, state)
        run = SimpleNamespace(notes=[])
        assert AL.final_stop_reason(loop, run) == stop, (state, AL.final_stop_reason(loop, run))
        assert CLI._run_agent_exit_code(SimpleNamespace(stop_reason=stop)) == code, state
        if state == "pass":
            assert run.notes == [], run.notes
        else:
            assert any("收工结论" in n for n in run.notes), run.notes


# ============================================================ 九 CLI 必须把两个喂参喂进去


def _cli_closing(root: pathlib.Path) -> tuple[int, str]:
    """跑一次真的 `agentflow closing`（与运维/CI 同一条入口）。"""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        code = CLI.main(["--plain", "--root", str(root), "closing",
                         "--project-dir", str(root),
                         "--report", "out/review/REPORT.md",
                         "--sid", REH8.SID, "--goal-met"])
    return int(code), buf.getvalue()


def test_h_cli_closing_feeds_retire_and_programs_and_is_not_not_wired(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """干净工作区上 `agentflow closing` ⇒ verdict=pass / exit 0（不是 not_wired/2）。

    反真空：把两个喂参的注入各拿掉一个 ⇒ 回到 `unknown` / exit 2（三态不许折平）。
    这一条钉的是 CLI 这条路，不是 `check_closing` 的函数签名 —— 业主 2026-11-19
    点名的正是"CLI closing 必须把 retire 与 programs 喂进 closing_verdict"。
    """
    store, root = REH8.build(tmp_path)
    code, out = _cli_closing(root)
    assert code == 0, out
    assert "收工结论：pass" in out, out
    feed = CL.machine_feeders(store)
    assert feed["retire"]["checked"] is True, feed["retire"]
    assert feed["retire"]["complete"] is True, feed["retire"]
    assert feed["programs"]["checked"] is True, feed["programs"]

    real = CL.machine_feeders

    def _drop(key: str):
        def _feed(*args: Any, **kwargs: Any) -> dict[str, Any]:
            got = dict(real(*args, **kwargs))
            got[key] = None
            return got
        return _feed

    for key in ("retire", "programs"):
        monkeypatch.setattr(CL, "machine_feeders", _drop(key))
        bad_code, bad_out = _cli_closing(root)
        monkeypatch.setattr(CL, "machine_feeders", real)
        assert bad_code == 2, (key, bad_code, bad_out)
        assert "收工结论：unknown" in bad_out, (key, bad_out)
        assert "not_wired" in bad_out, (key, bad_out)
