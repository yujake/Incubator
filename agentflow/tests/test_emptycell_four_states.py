# -*- coding: utf-8 -*-
"""EMPTYCELL 判据：收工八格四态 —— "没有可判对象"记 `na`，不许真空通过。

## 现场（两份独立取证，同一读数）

- `temp/webclean/REPORT.md` P1-6；
- `temp/webcap/REPORT.md` B8（同一读数被两次独立发现）。

空工作区跑收工八格（`/api/package` 的 `closing.gates`）::

    counts = {pass: 6, fail: 2}、can_close = null

六格 `pass` 是"没有东西可判"，不是"判过且合格" —— 真空通过。改前 `closing.py` 的
`contradictions` / `load_bearing` / `user_pending` / `acceptance` / `artifact_ledger` /
`literature_pending` 六格在"表不在 / 目录空 / 没有可判对象"时都落 `pass`。

## 四态（后端跟上 web，不另造计数）

| 状态 | 含义 | 进不进分母 |
|---|---|---|
| `pass` / `fail` | 这一格依赖的东西存在、而且判过 | 进 |
| `unknown` | 存在但读不成（没查成） | 进 |
| `na` | 依赖的东西整个不存在（表不在 / 表在零行 / 没有会话记录）⇒ 没有可判对象 | 不进 |

网页与 CLI 都只读 `readouts.gate_cells`（唯一实现），所以后端把 `na` 写进
`rep.status` 就够了 —— 这一份不碰 webui/ui，也不另写一套计数。

## 五条判据

| # | 判据 | 反真空 / 负控 |
|---|---|---|
| a | 空工作区 ⇒ 六格 `na`（带 why）、真 fail 仍 fail、真 unknown 仍 unknown | 改前六格是 `pass` ⇒ 这一条必红 |
| b | 非空工作区（`test_closing_gate._good` 的正控）⇒ 该 pass 的八格仍 pass | 证明 a 不是"把 pass 也改成 na" |
| c | 表在盘上但读不成 ⇒ `unknown`（不折成 `na` / `pass`） | 坏 JSON 落在盘上 |
| d | 反真空：把 `_record_not_applicable` 打桩回"记 pass" ⇒ a 的检查必红 | 复现改前的 `counts={pass:6, fail:2}` |
| e | `na` 不进 `pass` 计数、不进 `fail` 计数、不进分母；八格全 na ⇒ `unknown` | 甲 规则（至少一格 pass）的逐档读数 |

`closing_verdict` 对 `na` 的规则选「甲」（没有 fail / unknown 且至少一格 pass ⇒ pass），
理由钉在 e2：`乙`（na 视为满足）会让八格全 na 的空工作区给出"可以交"—— 那正是这一路
要拆掉的真空通过。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import closing as CL
from agentflow.store import Store

from test_closing_gate import _gate, _good

#: 网页 `/api/package` 同形的那两个入参（`_closing_block` 就是这么调的）。
PROJECT = "."
REPORT = "out/review/REPORT.md"

#: 空工作区上原来那六格真空 `pass`（WEBCAP B8 逐字点名的那六格）。
VACUOUS: tuple[str, ...] = (
    "contradictions", "load_bearing", "user_pending", "acceptance",
    "artifact_ledger", "literature_pending",
)


# ============================================================ 夹具


def _empty_gate(ws: pathlib.Path, *, m_says_done: bool = False) -> CL.ClosingReport:
    """空工作区上跑一次门（与网页同形入参：`project_dir="."`、报告路径给了但文件不在）。

    `m_says_done=True` 时把机器读数两个喂参也喂齐（`retire` 干净 / 程序已停），于是
    `closing_verdict` 走到"八格那一半"—— 用来证明 `na` 藏不住真正的 `fail`。
    """
    extra: dict = {}
    if m_says_done:
        extra = dict(goal="把这一趟做完并交付", goal_met=True, basis="夹具：M 说做完了",
                     task_list=[{"what": "交付", "state": "done"}],
                     retire={"checked": True, "complete": True, "reason": "夹具：名册已清"},
                     programs={"checked": True, "running_count": 0,
                               "reason": "夹具：没有在跑的程序"})
    return CL.check_closing(Store(ws), project_dir=PROJECT, report_path=REPORT,
                            sid=None, **extra)


def _a_problems(rep: CL.ClosingReport) -> list[str]:
    """判据 a 的检查本体（d 要拿它证明"打桩回 pass ⇒ 必红"）。

    返回空表 = a 成立；非空 = 逐条说哪一格不对。
    """
    problems: list[str] = []
    for name in VACUOUS:
        got = rep.status.get(name)
        if got != "na":
            problems.append(f"{name} 记的是 {got!r}，要 na（没有可判对象）")
    cells = {c["check"]: c for c in CL.closing_verdict(rep)["cells"]}
    for name in VACUOUS:
        cell = cells.get(name) or {}
        if not str(cell.get("why") or ""):
            problems.append(f"{name} 是 na 却没有 why（na 不是一个没有理由的空状态）")
        elif "没有可判对象" not in str(cell["why"]):
            problems.append(f"{name} 的 why 没说清为什么没有可判对象：{cell['why']}")
        reading = rep.readings.get(name) or {}
        if "没有可判对象" not in str(reading.get("reason") or ""):
            problems.append(f"{name} 的 readings.reason 没留下 why：{reading.get('reason')!r}")
    if rep.status.get("substance") != "fail":
        problems.append(f"substance 记的是 {rep.status.get('substance')!r}，真 fail 要仍 fail")
    counts = CL.closing_verdict(rep)["counts"]
    if counts.get("na") != len(VACUOUS):
        problems.append(f"counts.na 是 {counts.get('na')!r}，要 {len(VACUOUS)}")
    if counts.get("pass") != 0:
        problems.append(f"counts.pass 是 {counts.get('pass')!r}，六格都改成 na 之后要 0")
    return problems


def _statuses(pass_n: int, fail_n: int, unknown_n: int, na_n: int) -> dict[str, str]:
    """按 `DEFAULT_CHECKS` 的顺序造一份状态表（四档各取几格）。"""
    names = list(CL.DEFAULT_CHECKS)
    out: dict[str, str] = {}
    at = 0
    for state, count in (("pass", pass_n), ("fail", fail_n),
                         ("unknown", unknown_n), ("na", na_n)):
        for name in names[at:at + count]:
            out[name] = state
        at += count
    assert at == len(names), (at, len(names))
    return out


def _report(status: dict[str, str]) -> CL.ClosingReport:
    """一份"完整八格 + M 判达成 + 机器读数齐"的报告（只造读数，不跑门）。"""
    rep = CL.ClosingReport()
    rep.status = dict(status)
    rep.full_gate = True
    rep.authoritative = True
    rep.m_verdict = {"goal": "夹具目标", "met": True, "basis": "夹具",
                     "at": "2026-11-20T00:00:00+08:00",
                     "tasks": [{"what": "交付", "state": "done", "why": ""}]}
    rep.readings["machine_caliber"] = {
        "checked": True, "value": True,
        "retire": {"checked": True, "complete": True, "projected": False,
                   "state": "干净", "reason": ""},
        "programs": {"checked": True, "ok": True, "running_count": 0,
                     "unowned_count": 0, "state": "已停", "reason": ""},
    }
    return rep


# ============================================================ a) 空工作区 ⇒ 六格 na


def test_a_empty_workspace_turns_the_six_vacuous_passes_into_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """a) 空工作区 ⇒ 六格 `na`；真 fail 仍 fail；真 unknown 仍 unknown。

    改前这六格是 `pass`（`counts={pass:6, fail:2}`）⇒ 这一条在改前的代码上必红。
    """
    ws = tmp_path / "ws"
    Store(ws).init()
    rep = _empty_gate(ws)

    assert _a_problems(rep) == [], _a_problems(rep)
    # 真 fail 仍 fail：substance（五张表全空）与 report_shape（给了报告路径、文件不在）
    assert rep.status["substance"] == "fail", rep.status
    assert rep.status["report_shape"] == "fail", rep.status
    verdict = CL.closing_verdict(rep)
    assert verdict["counts"] == {"pass": 0, "fail": 2, "unknown": 0, "na": 6}, verdict["counts"]
    # 没有一格判过 ⇒ machine_pass 是假（na 不是 pass）
    assert rep.machine_pass is False, rep.to_dict()
    # 没人判过 ⇒ 结论仍是 unknown（真空通过拆掉之后也不许变成"可以交"）
    assert verdict["verdict"] == "unknown" and verdict["exit_code"] == 2, verdict


def test_a2_not_applicable_does_not_hide_a_real_fail(tmp_path: pathlib.Path) -> None:
    """a) 的第二半：M 说做完了，而 `na` 旁边有真 fail ⇒ 结论仍是 fail（不会被 na 洗绿）。

    改前六格 pass 时这一份会走到 `unknown`（没人判过那半已给）；现在 M 判了、机器读数
    也齐，八格里那两格 `fail` 必须照旧拦住 —— `na` 不许把真红藏起来。
    """
    ws = tmp_path / "ws"
    Store(ws).init()
    rep = _empty_gate(ws, m_says_done=True)
    verdict = CL.closing_verdict(rep)

    assert verdict["verdict"] == "fail", verdict
    assert verdict["exit_code"] == 1, verdict
    assert verdict["can_close"] is False, verdict
    assert "格 fail" in verdict["reason"], verdict["reason"]
    assert "substance" in verdict["reason"] or "report_shape" in verdict["reason"], \
        verdict["reason"]


# ============================================================ b) 正控：pass 没被改坏


def test_b_a_non_empty_workspace_still_passes_every_cell(tmp_path: pathlib.Path) -> None:
    """b) 正控：非空工作区（八格都真有对象可判）⇒ 八格仍全 `pass`。

    `_good` 是 `test_closing_gate.py` 的正控底座（本轮补了会话记录 / 验收表 / 文献归档，
    见 `_seed_gate_subjects`）。这一条证明 a 不是"把 pass 也一起改成 na"。
    """
    st, report = _good(tmp_path)
    rep = _gate(st, report)
    assert dict(rep.status) == {name: "pass" for name in CL.DEFAULT_CHECKS}, rep.to_dict()
    assert rep.verdict["counts"] == {"pass": 8, "fail": 0, "unknown": 0, "na": 0}, \
        rep.verdict["counts"]
    assert rep.machine_pass is True, rep.to_dict()


# ============================================================ c) 存在但读不成 ⇒ unknown


def test_c_a_table_that_exists_but_cannot_be_read_is_unknown(tmp_path: pathlib.Path) -> None:
    """c) 表在盘上、但读不成 ⇒ `unknown`（不是 `na`，也不是 `pass`）。

    三态纪律：`na` 说"没有可判对象"，`unknown` 说"有对象、但我们没查成"。把坏表折成
    `na` 等于把缺陷说成不适用 —— 那比原来的真空通过更难查（它不再刷红）。
    """
    ws = tmp_path / "ws"
    Store(ws).init()
    bad = "{这不是 JSON"
    (ws / "data" / "statements.json").write_text(bad, encoding="utf-8")
    (ws / "data" / "lit_candidates.json").write_text(bad, encoding="utf-8")
    paper = ws / "out" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "ACCEPTANCE-CHECKS.json").write_text(bad, encoding="utf-8")

    rep = _empty_gate(ws)
    for name in ("contradictions", "load_bearing", "substance",
                 "literature_pending", "acceptance"):
        assert rep.status.get(name) == "unknown", (name, rep.status)
    # 反真空：同一格里"文件根本不在"才是 na（a 已经钉住）；这里坏掉的三张表都是"在"。
    assert (ws / "data" / "statements.json").is_file()
    assert (ws / "data" / "lit_candidates.json").is_file()
    assert (paper / "ACCEPTANCE-CHECKS.json").is_file()


# ============================================================ d) 反真空


def test_d_stubbing_not_applicable_back_to_pass_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：把 `na` 那个落点打桩回"记 pass"（改前的行为）⇒ a 的检查必红。

    打的是唯一落点 `_record_not_applicable`，不是把整格函数换掉 —— 换掉的话证明的是
    "夹具能红"，不是"这一行改动是拦住真空通过的那一行"。
    """
    ws = tmp_path / "ws"
    Store(ws).init()
    plain = _empty_gate(ws)
    assert _a_problems(plain) == [], _a_problems(plain)      # 先证明没打桩时 a 是绿的

    def _old_pass(rep: CL.ClosingReport, name: str, why: str,
                  reading: object = None) -> None:
        """改前：表不在 ⇒ `pass`（why 也不落读数）。"""
        rep.status[name] = "pass"
        rep.readings[name] = dict(reading or {})

    monkeypatch.setattr(CL, "_record_not_applicable", _old_pass)
    stubbed = _empty_gate(ws)
    assert {n: stubbed.status[n] for n in VACUOUS} == {n: "pass" for n in VACUOUS}, \
        stubbed.status
    problems = _a_problems(stubbed)
    assert problems, "打桩回 pass 之后 a 的检查居然还是绿的 ⇒ a 没有接线到 na 这个落点"
    assert any("要 na" in p for p in problems), problems
    # 打桩之后复现的就是改前那份读数：六格 pass、两格 fail、机器说不过。
    assert stubbed.verdict["counts"] == {"pass": 6, "fail": 2, "unknown": 0, "na": 0}, \
        stubbed.verdict["counts"]


# ============================================================ e) na 的计数与分母


def test_e_na_is_not_pass_not_fail_and_not_in_the_denominator() -> None:
    """e) `na` 四档各数各的：不进 pass、不进 fail、不进分母；八格全 na 不是 pass。

    规则选「甲」：没有 fail / unknown 且「至少一格 pass」⇒ pass。于是：
    - 一格 pass + 七格 na ⇒ `verdict=pass`（na 不拦）；但 `machine_pass` 仍是假 ——
      那个旧口径是"八格全 pass"，而 `na` 不是 pass（两栏并列，句子里点名 na 格）；
    - 八格全 na ⇒ unknown（没有一格判过 —— `乙` 会在这里给出"可以交"）；
    - na 旁边有 fail / unknown ⇒ 照旧 fail / unknown（na 藏不住真红）。
    """
    # na 不进 pass 计数：三格 pass、五格 na ⇒ counts 分开各数
    ok = CL.closing_verdict(_report(_statuses(3, 0, 0, 5)))
    assert ok["counts"] == {"pass": 3, "fail": 0, "unknown": 0, "na": 5}, ok["counts"]
    assert ok["verdict"] == "pass" and ok["exit_code"] == 0, ok
    # na 不进分母：可判的格数就是 pass + fail + unknown = 3（na 那五格不算）
    counted = {k: v for k, v in ok["counts"].items() if k != "na"}
    assert sum(counted.values()) == 3, ok["counts"]
    # na 不是 pass：旧口径 machine_pass（八格全 pass）因此在有 na 时为假（webui 那条判据）
    assert ok["machine_pass"] is False, ok
    # 而权威结论仍然是通过的，且句子里点名了那些 na 格（na 不拦、也不许藏）
    assert "na 格" in ok["reason"], ok["reason"]

    # na 旁边有真 fail ⇒ fail（na 不进 fail 计数，也不替 fail 说情）
    bad = CL.closing_verdict(_report(_statuses(2, 1, 0, 5)))
    assert bad["counts"] == {"pass": 2, "fail": 1, "unknown": 0, "na": 5}, bad["counts"]
    assert bad["verdict"] == "fail" and bad["exit_code"] == 1, bad
    assert bad["can_close"] is False, bad

    # na 旁边有没查成 ⇒ unknown（不是 na 覆盖它）
    unchecked = CL.closing_verdict(_report(_statuses(2, 0, 1, 5)))
    assert unchecked["verdict"] == "unknown" and unchecked["exit_code"] == 2, unchecked

    # 八格全 na ⇒ 一格都没判过 ⇒ unknown（甲 的"至少一格 pass"不成立；乙 会在这里给 pass）
    all_na = CL.closing_verdict(_report(_statuses(0, 0, 0, 8)))
    assert all_na["counts"] == {"pass": 0, "fail": 0, "unknown": 0, "na": 8}, all_na["counts"]
    assert all_na["verdict"] == "unknown" and all_na["exit_code"] == 2, all_na
    assert all_na["can_close"] is None, all_na
    assert "全是 na" in all_na["reason"], all_na["reason"]

    # 一格 pass + 七格 na ⇒ pass：na 不进分母，也不拦真正的通过
    one = CL.closing_verdict(_report(_statuses(1, 0, 0, 7)))
    assert one["counts"]["pass"] == 1 and one["counts"]["na"] == 7, one["counts"]
    assert one["verdict"] == "pass" and one["exit_code"] == 0, one


def test_e2_the_na_rule_is_pinned_in_the_verdict_docstring() -> None:
    """e) 的判据面：`closing_verdict` 的 docstring 必须写明选哪条规则、为什么。

    这条判据防的是"口径只活在代码里"：下一个人读 docstring 看不到 `na` 怎么进结论，
    就会把它折成 pass（真空通过）或折成 unknown（把不适用说成没查成）。
    """
    doc = CL.closing_verdict.__doc__ or ""
    for needle in ("甲", "乙", "至少一格 pass", "不进 `pass` 计数",
                   "不进 `fail` 计数", "不进分母", "八格全 `na`"):
        assert needle in doc, (f"closing_verdict 的 docstring 缺这一句：{needle!r}", doc[:300])
