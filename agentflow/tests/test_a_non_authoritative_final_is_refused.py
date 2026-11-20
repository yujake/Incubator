# -*- coding: utf-8 -*-
"""FINALAUTH：漏传 `project_dir` / `report_path`，交 final 还会不会静默 rc=0。

## 现场（2026-11-19 已取证；`temp/_rehfix_evidence.md`）

```text
① `conductor.closing` 中途调用只传 goal / goal_met / basis / task_list（不传两个路径参数）
   ⇒ `ClosingReport.authoritative=False`（closing.py:8914）
   ⇒ `final_stop_reason` 直接回 "final"（agent_loop.py 的 authoritative 分支）
   ⇒ 结论是 rc=0 而判据 verdict=fail
② 这条口径「authoritative=False ⇒ 不改退出码」此前没有任何判据钉着：
   ROOTGATE 的判据只喂 authoritative=True
   （tests/test_rootgate_verdict_is_the_single_conclusion.py）
③ 真机提示词要求 M 两个参数都传（agent_prompts.py:4003-4005），但"漏传"没有受控读数
④ 31 条彩排当时靠这条口径变绿
```

## 业主裁定（2026-11-19）→ 本文件钉的东西

```text
① 运行中途的 closing（只取读数）= 非权威，允许，不参与退出码   —— 保留设计（判据 a）
② 但交 final 的那一刻必须有一份权威结论：
   若 final 时拿到的是 non-authoritative ⇒ 受控拒（closing_not_authoritative），
   让 M 带上 project_dir / report_path 重交；不许 rc=0                  （判据 b）
③ 彩排按权威门写：full 文献链 ⇒ verdict=pass + rc==0 + 八格逐格 pass    （判据 c）
④ 反真空：把 ② 的判据打桩掉 ⇒ b 必红；把彩排的两个参数去掉 ⇒ c 必红    （判据 d）
```

## 两处分工（同一份裁定的两半，别在任一处把另一半重算一遍）

| 决策点 | 函数 | 非权威时 |
|---|---|---|
| 运行收工的 `stop_reason` | `agent_loop.final_stop_reason` | 仍读作 `"final"` —— ①「不参与退出码」 |
| 交 final 那一刻要不要收 | `agent_loop.closing_final_authority` | 受控拒 —— ②「不许 rc=0」 |

受控拒走的是既有的收尾路：`_final_gate_reading` → `final_refused`（补救拍，
`AgentLoop.max_final_refused` 拍之后 `stop_reason=final_refused` ⇒ 退出码 5）。
拒信里的 `code` 是 `closing_not_authoritative`，`how_to_fix` 逐字点名两个参数。

## 判据与反真空

| 判据 | 读什么 | 反真空（同一判据必红） |
|---|---|---|
| a | 非权威读数 ⇒ `final_stop_reason` 仍是 `final`；没有门对象时 `closing_final_authority` 不拒；端到端 rc=0 | —— （这是正控：它守的是"别把①改坏"） |
| b | 有门对象 + final 时非权威 ⇒ `closing_not_authoritative` + `rc=5` + `how_to_fix` 点名两参数 | d1：打桩 `closing_final_authority` ⇒ 拒信与 rc≠0 一起消失 |
| c | full 文献链走权威门 ⇒ `verdict=pass` / `authoritative=True` / `rc==0` / 八格逐格 pass | d2：把彩排 M 的两个参数去掉 ⇒ 退回非权威，c 的读数必红 |
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest

import rehearsal_contract as RC

from agentflow import agent_loop as AL
from agentflow import closing as CL

import test_rehearsal_a_literature_flow as LIT

#: 非权威的那一份读数（与真工具回执同形：`readings.verdict` 的五格）。
NON_AUTHORITATIVE: dict[str, Any] = {
    "verdict": "fail", "exit_code": 1, "authoritative": False,
    "cells": [{"check": "substance", "status": "fail", "why": "五张实质表全 0"},
              {"check": "report_shape", "status": "unknown", "why": "没给报告路径"},
              {"check": "acceptance", "status": "unknown", "why": "没给项目根"},
              {"check": "artifact_ledger", "status": "unknown", "why": "没给项目根"}],
    "blockers": [{"check": "substance", "code": "no_substantive_output", "why": "五张表全 0"}],
    "reason": "格 fail：substance",
}


# ============================================================ 夹具


def _loop(readings: list[dict[str, Any]]) -> Any:
    """只带收工闸要读的那一格（`final_stop_reason` / `closing_final_authority` 都是纯读）。"""
    return SimpleNamespace(_closing_gate_readings=list(readings), store=None,
                           workspace_root="", role="M")


def _consulted(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"consulted": True, "calls": 1, "last": {"verdict": dict(verdict)}}


def _strip_the_two_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    """把彩排 M 那一次 `conductor.closing` 的两个参数摘掉（= 改前的真机形态）。"""
    original = LIT._Wire._m_script

    def patched(self: Any, prompt: str) -> str:
        spec = json.loads(original(self, prompt))
        if spec.get("tool") == "conductor.closing":
            spec["args"] = {k: v for k, v in (spec.get("args") or {}).items()
                            if k not in ("project_dir", "report_path")}
        return json.dumps(spec, ensure_ascii=False)

    monkeypatch.setattr(LIT._Wire, "_m_script", patched)


def _gate_the_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """让这一趟成为"有门的项目"（盘上有验收表 ⇒ `closing_gate_requirement.required`）。

    用的是空表（`{"checks": []}`）：这一格要的只是"有门对象"这个事实，验收行的读数
    在别的判据里（`tests/test_rehearsal_closing_eight_cells.py` 的十二行）。
    """
    original = LIT._workspace

    def patched(base: pathlib.Path) -> Any:
        store = original(base)
        path = pathlib.Path(store.root) / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checks": []}), encoding="utf-8", newline="\n")
        return store

    monkeypatch.setattr(LIT, "_workspace", patched)


# ============================================================ 读数（判据本体）


def _final_gate_refusals(got: dict[str, Any]) -> list[dict[str, Any]]:
    """M 每一次被收工闸拒的读数（`{"final_refused": …, "why": …}`）。"""
    out: list[dict[str, Any]] = []
    for event in got["events"]:
        if event.get("kind") != "agent_step" or event.get("role") != "M":
            continue
        result = event.get("result") or {}
        if isinstance(result, dict) and result.get("final_refused"):
            out.append(dict(result))
    return out


def _refusal_problems(got: dict[str, Any]) -> list[str]:
    """判据 b：final 时非权威 ⇒ 受控拒 + rc≠0 + 拒信点名两个参数（空 = 绿）。"""
    problems: list[str] = []
    verdict = RC.closing_verdict(got["ws"])
    if verdict.get("authoritative") is not False:
        problems.append(f"这一趟的收工读数本该是**非权威**的（漏传两参数），"
                        f"实得 authoritative={verdict.get('authoritative')!r}")
    refusals = _final_gate_refusals(got)
    if not refusals:
        problems.append("交 final 时没有被收工闸拒过（漏传两参数 + 有门项目 ⇒ 必须受控拒）")
        return problems
    last = dict(refusals[-1].get("final_refused") or {})
    if str(last.get("code") or "") != AL.CLOSING_NOT_AUTHORITATIVE_CODE:
        problems.append(f"受拒码应为 `{AL.CLOSING_NOT_AUTHORITATIVE_CODE}`，"
                        f"实得 {last.get('code')!r}")
    fix = str(last.get("how_to_fix") or "")
    for name in ("project_dir", "report_path"):
        if name not in fix:
            problems.append(f"`how_to_fix` 没有点名 `{name}`：{fix!r}")
    why = str(last.get("why") or "")
    if "权威" not in why:
        problems.append(f"拒信没说清「交 final 需要权威结论」：{why!r}")
    ends = [e for e in got["events"]
            if e.get("kind") == "agent_run_end" and e.get("role") == "M"]
    if not ends or str(ends[-1].get("stop_reason") or "") != "final_refused":
        problems.append(f"M 那一趟的 stop_reason 应为 final_refused，"
                        f"实得 {[e.get('stop_reason') for e in ends]}")
    if int(got.get("rc", 0)) == 0:
        problems.append("rc==0：非权威的 final 被静默放过了（业主裁定 ②「不许 rc=0」）")
    if int(got.get("rc", -1)) != 5:
        problems.append(f"退出码应为 5（`final_refused`），实得 {got.get('rc')!r}")
    return problems


def _run_without_parameters(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """full 文献链，M 交 final 时不带那两个参数（改前的真机/彩排形态）。"""
    _strip_the_two_parameters(monkeypatch)
    return LIT._run(base, monkeypatch)


# ============================================================ a 保留设计（正控）


def test_a_a_non_authoritative_reading_does_not_change_the_stop_reason() -> None:
    """a：非权威读数在 `final_stop_reason` 里仍读作 `final`（裁定 ①，保留设计）。

    这一条守的是别把 ① 改坏：业主说"运行中途的 closing（只取读数）= 非权威，
    允许，不参与退出码"。所以 `final_stop_reason` 见到非权威不许改停止理由 ——
    "交 final 的那一刻"由 :func:`agent_loop.closing_final_authority` 负责（判据 b）。
    """
    loop = _loop([{"verdict": NON_AUTHORITATIVE}])
    assert AL.final_stop_reason(loop) == "final", (
        "非权威读数把 stop_reason 改了 ⇒ 那是把裁定 ① 改坏（中途读数要允许）")

    # 没有门对象 ⇒ 这一格没有对象，不拒（同一份非权威读数）。
    no_gate = AL.closing_final_authority(
        loop, gate_req={"required": False, "checked": True, "why": "非研究型"},
        consulted=_consulted(NON_AUTHORITATIVE), exemption={"declared": False})
    assert no_gate["refuse"] is False, no_gate
    assert no_gate["checked"] is False, no_gate

    # 有门对象 ⇒ 同一份读数才拒（b 的行级对照：差别只在"这一趟要不要过门"）。
    gated = AL.closing_final_authority(
        loop, gate_req={"required": True, "checked": True, "why": "有验收表"},
        consulted=_consulted(NON_AUTHORITATIVE), exemption={"declared": False})
    assert gated["refuse"] is True, gated
    assert gated["code"] == AL.CLOSING_NOT_AUTHORITATIVE_CODE, gated
    assert gated["authoritative"] is False, gated

    # 权威的那一份 ⇒ 不拒（正控的第三档）。
    authoritative = dict(NON_AUTHORITATIVE, verdict="pass", authoritative=True,
                         exit_code=0, cells=[], blockers=[])
    ok = AL.closing_final_authority(
        loop, gate_req={"required": True}, consulted=_consulted(authoritative),
        exemption={"declared": False})
    assert ok["refuse"] is False and ok["authoritative"] is True, ok

    # 没跑过门 / 最后一次没回 verdict ⇒ 这一格"没查成"（不折成非权威，也不折成权威）。
    never = AL.closing_final_authority(
        loop, gate_req={"required": True}, consulted={"consulted": False},
        exemption={"declared": False})
    assert never["refuse"] is False and never["checked"] is False, never
    empty = AL.closing_final_authority(
        loop, gate_req={"required": True}, consulted={"consulted": True, "last": {}},
        exemption={"declared": False})
    assert empty["refuse"] is False and empty["checked"] is False, empty


def test_a_end_to_end_a_non_authoritative_final_still_ends_at_final_without_gate(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a 的端到端：没有门对象的项目，M 漏传两参数 ⇒ `stop_reason=final`、rc=0。

    这是裁定 ①「允许」的那一侧：链条彩排（文献链没有研究问题 / 验收表 / 论文包）
    拿一份非权威读数收工，退出码不受影响 —— 改前改后都该是 0，所以它是正控
    （它反过来证明 b 的红不是"所有非权威 final 都被拒"）。
    """
    got = _run_without_parameters(tmp_path, monkeypatch)
    verdict = RC.closing_verdict(got["ws"])
    assert verdict.get("authoritative") is False, verdict.get("authoritative")
    assert got["rc"] == 0, (got["rc"], got["stdout"][-1500:], got["stderr"][-1500:])
    ends = [e for e in got["events"]
            if e.get("kind") == "agent_run_end" and e.get("role") == "M"]
    assert ends and ends[-1].get("stop_reason") == "final", ends[-1:]
    assert not _final_gate_refusals(got), "没有门对象的项目不该被收工闸拒"


# ============================================================ b 受控拒（新）


def test_b_a_non_authoritative_final_is_refused_with_a_named_code(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：有门对象 + final 时非权威 ⇒ 受控拒 `closing_not_authoritative`、rc≠0。

    这就是业主裁定 ② 的正控：漏传两个参数不再能静默 rc=0。拒信要点名两个参数
    （`how_to_fix`），并且这一趟以 `final_refused` 收尾（退出码 5）—— 不许"记了 final
    又提醒"。
    """
    _gate_the_workspace(monkeypatch)
    got = _run_without_parameters(tmp_path, monkeypatch)
    problems = _refusal_problems(got)
    assert not problems, "受控拒的读数不对：\n- " + "\n- ".join(problems)
    # 补救拍真的给过（M 有机会带上两个参数重交），且拒信进了会话事件。
    assert len(_final_gate_refusals(got)) >= 1, "拒信没有落进会话事件"


# ============================================================ c full 彩排走权威门


def test_c_the_full_rehearsal_passes_the_authoritative_gate(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：full 文献链（带全两个参数）⇒ `verdict=pass`、`rc==0`、八格逐格 pass。"""
    got = LIT._run(tmp_path, monkeypatch)
    verdict = RC.closing_verdict(got["ws"])
    assert verdict.get("verdict") == "pass", (verdict.get("verdict"),
                                              str(verdict.get("reason"))[:300])
    assert verdict.get("authoritative") is True, verdict.get("authoritative")
    assert int(verdict.get("exit_code", -1)) == 0, verdict.get("exit_code")
    assert int(got["rc"]) == 0, (got["rc"], got["stdout"][-1500:], got["stderr"][-1500:])
    cells = {str(c.get("check")): str(c.get("status")) for c in (verdict.get("cells") or [])}
    assert sorted(cells) == sorted(CL.DEFAULT_CHECKS), sorted(cells)
    # 2026-11-20（EMPTYCELL）：`acceptance` 在"没有验收表、`research_questions` 也一行
    # 没有"的项目上是 `na`（没有可判对象），不是 pass。这一趟只写文献表，正是那种项目；
    # 除它之外每一格都必须 pass。
    assert cells.get("acceptance") == "na", cells
    assert all(v == "pass" for k, v in cells.items() if k != "acceptance"), cells
    assert verdict.get("blockers") == [], verdict.get("blockers")
    ends = [e for e in got["events"]
            if e.get("kind") == "agent_run_end" and e.get("role") == "M"]
    assert ends and ends[-1].get("stop_reason") == "final", ends[-1:]
    gate_problems = RC.authoritative_problems(verdict, allow_na=("acceptance",))
    assert not gate_problems, gate_problems


# ============================================================ d 反真空


def test_d1_stubbing_the_authority_criterion_turns_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d1：把 ② 的判据打桩成"永不拒" ⇒ b 的读数必红（同一份工作区、同一条链）。

    打的是 `agent_loop.closing_final_authority`（唯一判据，见它的 docstring）：
    打桩之后漏传两参数的 final 又被静默放过（rc=0、没有拒信）—— 这正是改前的形态，
    于是 b 的 `_refusal_problems` 非空。"判据不在=红"证明它承重。
    """
    _gate_the_workspace(monkeypatch)
    monkeypatch.setattr(AL, "closing_final_authority",
                        lambda *a, **k: {"refuse": False, "code": "", "checked": False,
                                         "authoritative": None, "why": "", "how_to_fix": "",
                                         "last": {}})
    got = _run_without_parameters(tmp_path, monkeypatch)
    problems = _refusal_problems(got)
    assert problems, "把 ② 的判据打桩掉之后 b 仍然读成绿 ⇒ 判据是橡皮图章"
    assert int(got["rc"]) == 0, (
        f"打桩之后这一趟应当又回到静默 rc=0（改前形态），实得 rc={got['rc']!r}")


def test_d2_stripping_the_two_parameters_turns_c_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d2：把彩排 M 的两个参数去掉 ⇒ 退回非权威，c 的读数必红。

    同一份工作区、同一条链，只摘 `project_dir` / `report_path`：权威门那三格
    （`report_shape` / `acceptance` / `artifact_ledger`）只能记 unknown ⇒
    `authoritative=False`、`verdict` 不再是 pass ⇒ c 的两条判据（pass / 权威）都红。
    （rc 仍可能是 0：没有门对象的项目按裁定 ① 允许 —— 所以 c 的 rc 那条在这一档
    不是红点，红的是"权威"与"pass"。）
    """
    got = _run_without_parameters(tmp_path, monkeypatch)
    verdict = RC.closing_verdict(got["ws"])
    problems = RC.authoritative_problems(verdict)
    assert problems, "把两个参数去掉之后 c 的读数仍然全绿 ⇒ c 是橡皮图章"
    assert verdict.get("authoritative") is False, verdict.get("authoritative")
    assert verdict.get("verdict") != "pass", verdict.get("verdict")


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
