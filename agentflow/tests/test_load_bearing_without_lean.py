# -*- coding: utf-8 -*-
"""收工门 `load_bearing`：Lean 关也判，`na` 消失（业主 2026-11-14 拍板）。

## 改前是什么（这一份要钉住的那个缺陷）

`_check_load_bearing` 在 Lean 关（产品缺省，`settings.DEFAULT_LEAN_ENABLED = False`）
时直接写 `status="na"` 并 return：正文/命题扫描一步没跑，`claims_with_proof` 硬编码 0
⇒ 这一格度量的是"Lean 开关"，不是"承重结论有没有背书"。而 `na` 又不是 `pass`
⇒ `machine_pass` 在产品缺省的工作区上永远为假（2026-11-14 真机：0/107）。

## 改后（替代口径，不是放宽）

每条 `grade=theorem` 的正文断言都要有背书：① T3 / V 真签过的穷举（`_has_t3`）；
② Lean 关时，它引用的命题「现行版」有 V 签（`_statement_reviewed`）；③ 已降档
（不在 `theorem` 档就不进这一问）。零承重断言 ⇒ `pass` + 读数 `state="not_applicable"`。

## 判据（每条都能造红，也有反真空）

| # | 判据 | 造的是什么现场 |
|---|---|---|
| a | 缺背书 ⇒ `fail` + blocker，且点名那条断言 | 一条 proof 级断言只引到数值实验 |
| b | 引用的命题现行版有 V 签 ⇒ `pass` | 命题签够票并颁发真凭据（`vsigns.issue`） |
| c | 零承重断言 ⇒ `pass` + `state="not_applicable"`（不是 `na`） | 有命题、没有 theorem 档断言 |
| d | 反真空：把 `_statement_reviewed` 打桩成恒真 ⇒ a 必红 | 同 a，`monkeypatch.setattr` |
| e | Lean 关且有证据的工作区上 `machine_pass` 能变真 | 七格全 pass、零 blocker |
| f | 负控：Lean 开着时"V 签"不算背书（那一档只给 Lean 关） | 同一份 V 签命题，开关打开 |

夹具与 `tests/test_closing_gate.py` 同一份（`_project` / `_paper_with_claim` /
`_numeric_experiment` / `_t3_experiment` / `_write_report`）；`_credential_fixture.issue_credential` 是
仓库里"造一份可复算的 V 签"的唯一写法（只写三行台账不够：`statements_unsigned` 会把
"够票却没有签文件"读成 `unissued`，`machine_pass` 因此永远真不了）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import closing as CL
from agentflow import settings as SET
from agentflow.store import Store

from _credential_fixture import issue_credential
from test_closing_gate import (
    _numeric_experiment, _paper_with_claim, _project, _seed_gate_subjects,
    _t3_experiment, _write_report,
)

#: 一条有证明过程、可以送 V 审的命题正文（与 `tests/test_lean_switch.py` 同形）。
PROOF_TEXT = "证明：一行"


def _statement(store: Store, *, sid: str = "0000") -> None:
    """落一条非概念命题（`cross_check` 档：还没送 V，所以不写 `proof_review`）。"""
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", {
            "stmt_id": sid, "status": "active", "evidence_kind": "cross_check",
            "statement_full": "命题", "proof_text": PROOF_TEXT,
            "quote_reason": "夹具：这一行只为承重那一格的读数而造，不涉及外部原文",
            "origin": "own_result"})


def _v_sign(root: pathlib.Path, *, sid: str = "0000") -> None:
    """按 `tests/_credential_fixture.issue_credential` 的口径签出一份真凭据。"""
    issue_credential(root, proof_text=PROOF_TEXT, statement_id=sid)


def _gate(store: Store, report: pathlib.Path | None = None):
    return CL.check_closing(
        store, project_dir=str(store.root),
        report_path=str(report) if report is not None else "")


# ============================================================ a) 缺背书 ⇒ fail + 点名

def test_a_load_bearing_claim_without_any_backing_fails_and_is_named(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a) Lean 关 + 一条承重断言无 T3 / 无现行 V 签 / 未降档 ⇒ `fail` 且点名该断言。

    改前的读数是 `na` + "T3 判据不适用"：`claims_with_proof` 恒 0、正文一条没扫。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _project(tmp_path)
    _numeric_experiment(st)                 # 只有数值支持，不是 T3
    _paper_with_claim(st)                   # proof 档断言，引到那条数值实验
    # 2026-11-16：`d30f5c49` 起 G8 直接从 `experiments` 台账现算（回执那条路已删）⇒
    # 上面那条 `_numeric_experiment`（带 `code_hash` + `exit_code`）已经让 G8 有落点，
    # 原先那句 `_run_evidence(tmp_path)`（写 RUN-EVIDENCE 回执）不再需要、也不再存在。
    rep = _gate(st)

    assert rep.status["load_bearing"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["load_bearing_without_backing"], \
        [f.to_dict() for f in rep.blockers]
    detail = rep.blockers[0].detail
    assert "0001#c1" in detail, "这一格红了却没点名是哪条断言：" + detail
    assert "V 签" in detail and "降档" in detail, (
        "Lean 关时 blocker 的处置必须指向替代口径（V 签 / 降档），"
        "不许把 M 派去做这一趟做不了的 formal 活：" + detail)

    readings = rep.readings["load_bearing"]
    assert readings["state"] == "fail", readings
    assert readings["lean"] == "off", readings
    assert readings["claims_with_proof"] == 1, readings
    assert readings["claims_without_t3"] == 1, readings
    # 逐条给理由：那一条断言在 `claims` 里、`backed_by` 是空的、`why` 说清缺什么
    assert readings["claims"] == [{
        "doc_id": "0001", "claim_id": "c1", "evidence_kind": "proof",
        "text": "已证明定理 1.5", "backed_by": "", "v_signed": [],
        "why": readings["claims"][0]["why"],
    }], readings["claims"]
    assert "不是 T3 形态" in readings["claims"][0]["why"], readings["claims"]
    assert "一条命题都没引" in readings["claims"][0]["why"], readings["claims"]


# ============================================================ b) 现行 V 签 ⇒ pass

def test_a_claim_backed_by_the_current_v_sign_passes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b) Lean 关 + 承重断言引用的命题现行版有 V 签 ⇒ `pass`（没有 blocker）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _project(tmp_path)
    _statement(st)
    _v_sign(tmp_path)
    _paper_with_claim(st, citations=["stmt:0000"])
    rep = _gate(st)

    assert rep.status["load_bearing"] == "pass", rep.to_dict()
    assert [f for f in rep.blockers if f.check == "load_bearing"] == [], \
        [f.to_dict() for f in rep.blockers]
    readings = rep.readings["load_bearing"]
    assert readings["state"] == "pass", readings
    assert readings["v_sign_backed_claims"] == 1, readings
    assert readings["claims"][0]["backed_by"] == "v_sign", readings["claims"]
    assert readings["claims"][0]["v_signed"] == ["0000"], readings["claims"]


def test_the_t3_entry_is_still_recognised_when_lean_is_off(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """替代口径多开一个入口，不是把 T3 那一条换掉：盘上真有 T3 行 ⇒ 照旧算背书。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _project(tmp_path)
    _t3_experiment(st)                      # formal + proof + 检查器原话
    _paper_with_claim(st)                   # 引到 exp:0001
    rep = _gate(st)

    assert rep.status["load_bearing"] == "pass", rep.to_dict()
    assert rep.readings["load_bearing"]["claims"][0]["backed_by"] == "t3", \
        rep.readings["load_bearing"]["claims"]


# ============================================================ c) 零承重 ⇒ not_applicable

def test_zero_load_bearing_claims_are_a_pass_with_not_applicable_as_a_reading(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c) 零承重断言 ⇒ `pass` + 读数 `state="not_applicable"`（不是 `na`，也不是 fail）。

    这一档与 `paper` 那一格同一个口径：没有对象要判 ≠ 判不了 ≠ 没查成。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _project(tmp_path)
    _statement(st)                          # 有命题，没有 theorem 档断言
    _v_sign(tmp_path)
    rep = _gate(st)

    assert rep.status["load_bearing"] == "pass", rep.to_dict()
    assert rep.status["load_bearing"] != "na", "`na` 已经从这个状态位里消失"
    readings = rep.readings["load_bearing"]
    assert readings["state"] == "not_applicable", readings
    assert readings["claims_with_proof"] == 0 and readings["claims_without_t3"] == 0, readings
    assert all(f.level != "blocker" for f in rep.findings), \
        [f.to_dict() for f in rep.findings]
    # 反真空：这不是"空台账把没做读成没问题"——命题台账里真的有一行
    assert rep.readings["substance"]["statements"] == 1, rep.readings["substance"]


# ============================================================ d) 反真空

def test_stubbing_the_v_sign_criterion_turns_the_red_green(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：把「现行 V 签」那条判据打桩成恒真 ⇒ a 那条断言不再 fail。

    两半一起读才说明红真的压在那条判据上（夹具里有一条命题、一次都没送过 V）：
    不打桩 ⇒ `fail`；打桩 ⇒ `pass`。若有人把 `_statement_reviewed` 换成恒真，
    a 那一条会当场变绿 —— 那正是这一条要报的"判据没有接线"。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _project(tmp_path)
    _statement(st)
    _paper_with_claim(st, citations=["stmt:0000"])
    plain = _gate(st)
    assert plain.status["load_bearing"] == "fail", plain.to_dict()

    monkeypatch.setattr(CL, "_statement_reviewed", lambda *a, **k: True)
    stubbed = _gate(st)
    assert stubbed.status["load_bearing"] == "pass", (
        "把「现行 V 签」打桩成恒真之后 a 仍然红 ⇒ a 红的不是这条判据", stubbed.to_dict())
    assert stubbed.readings["load_bearing"]["claims"][0]["backed_by"] == "v_sign", \
        stubbed.readings["load_bearing"]["claims"]


# ============================================================ e) machine_pass 能变真

def test_machine_pass_can_become_true_on_a_lean_off_workspace_with_evidence(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) Lean 关 + 有证据（一条 V 签住的命题）⇒ 没有 fail / unknown 格 ⇒ `machine_pass` 真。

    这是改前"永远真不了"的反面：那一版把 `load_bearing` 记成 `na`，而 `na` 不是 `pass`
    ⇒ 同一份工作区 `machine_pass` 恒为 false（真机 0/107）。工作区里没有任何
    formal 实验行（`method="formal"` 一条都没跑），所以这不是靠 T3 那条路过的。

    2026-11-20（EMPTYCELL）：四态落地后"没有可判对象"的格记 `na`，而 `machine_pass`
    仍是"八格全 pass"的旧口径 ⇒ 要让这一条继续有意义，夹具必须让八格都真的判过。
    `_seed_gate_subjects` 补的正是那三样（会话记录 / 验收表两行 / 文献归档）—— 它们
    不是为了让读数变绿：没有它们，`user_pending` / `acceptance` / `literature_pending`
    三格是 `na`（不适用），`machine_pass` 当然为假。补完之后八格全 pass 才是这条要证的
    "Lean 关 + 有证据 ⇒ 机器口径能成立"。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    st = _project(tmp_path)
    _statement(st)
    _v_sign(tmp_path)
    _paper_with_claim(st, citations=["stmt:0000"])
    _seed_gate_subjects(tmp_path)
    report = _write_report(tmp_path)
    rep = _gate(st, report)

    assert dict(rep.status) == {name: "pass" for name in CL.DEFAULT_CHECKS}, rep.to_dict()
    assert rep.verdict["counts"] == {"pass": 8, "fail": 0, "unknown": 0, "na": 0}, \
        rep.verdict["counts"]
    assert rep.blockers == [], [f.to_dict() for f in rep.blockers]
    assert rep.machine_pass is True, rep.to_dict()
    # 反真空：不是空工作区（没有实质产出时 `substance` 自己会红）
    assert rep.readings["substance_total"] > 0, rep.readings.get("substance")
    assert st.rows("experiments") == [], "这一条要的是「没有 formal 行也能过」"


# ============================================================ f) 负控（Lean 开）

def test_the_v_sign_substitute_does_not_loosen_the_lean_on_criterion(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：Lean 开着时，引到 V 签命题的 proof 断言仍不算背书（那一档只给 Lean 关）。

    替代口径是"形式化那条路这一趟走不了"时的替代，不是把 T3 判据整体改软：
    开关打开时判据逐字不变（`load_bearing_without_t3`）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    st = _project(tmp_path)
    _statement(st)
    _v_sign(tmp_path)
    _paper_with_claim(st, citations=["stmt:0000"])
    rep = _gate(st)

    assert rep.status["load_bearing"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["load_bearing_without_t3"], \
        [f.to_dict() for f in rep.blockers]
    assert rep.readings["load_bearing"]["lean"] == "on", rep.readings["load_bearing"]
    assert "disabled" not in rep.readings["load_bearing"], rep.readings["load_bearing"]
