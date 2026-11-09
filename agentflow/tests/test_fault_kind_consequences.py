# -*- coding: utf-8 -*-
"""判据：D3 批 2 —— 四类缺陷 × 四条后果（写侧分类 · 后果分叉 · 回执与义务）。

## 这一份守什么（按批 2 的三块）

| 块 | 判据 | 改坏之后的样子 |
|---|---|---|
| ① 写侧分类 | `secretary.v_reply_fault_reading` 把秘书那一问的答案读成 `(axis, kind, cause, report_gap)`；`verifications.record_verification` 把三个类别格原样落进 `secretary_judge`；没给就不写（老行读法不变） | 「没记录反例尝试」又被折回 fault（签再次不可达），或者 clean 行带着 kind（`is_a_vote` 的 ③ 把一条真 clean 判成矛盾行） |
| ② 后果分叉 | 四类 × 四格：算不算票 / 锁不锁 sha / 当趟终局 / 签不签；`report_gap` 算票（业主裁定 ①）、程序性不锁 sha（同 sha 可再送）、math 锁 sha（同 sha 拒） | 某一类被折回另一类（例如把程序性锁成 math，或把 math 解锁） |
| ③ 回执与义务 | 程序性不开 `v-resubmit@…`（那是"改稿"的义务）、改发"本轮无有效判定、可原样再送"的回执、进 `report_fix_list`（`attempts` / `last_at`，不设上限） | 程序性又开出一条"改稿"义务（把报告措辞变成改稿命令），或者反复重送不可见 |

## 反真空（三条，见文件末尾）

把 `report_gap` 判回 math / 把程序性判成锁 / 把 math 判成不锁 —— 三条都必须变红。
没有它们，「矩阵绿」只证明"夹具恰好走了我写的那一支"。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentflow import secretary as SEC
from agentflow import verifications as VR

SID = "000030"
PROOF = "1. 设 x>0。\n2. 由定义直接得到结论。"


# ---------------------------------------------------------------- 夹具


def _reason_98b_gap() -> str:
    """98b 那 4 条 fault 的 `reason` 变体之一（逐字，D3 §2.1）。"""
    return "它虽逐行核对并称未发现问题，但没有记录任何反例构造尝试，按题面标准不能判『没问题』。"


def _reason_math() -> str:
    return "该回复明确指认步2存在「无依据的逐项求导」和「绝对收敛未证」两处缺陷。"


def _row(*, axis: str = "fault", kind: str | None = "procedural",
         cause: str | None = "", report_gap: str | None = None,
         verdict: str = "成立", findings: list[dict[str, Any]] | None = None,
         defect_step: Any = None, unresolved_errors: int = 0,
         reason: str = "", review_call: str = "", review_pass: Any = None,
         proof_sha256: str = "", checked: bool = True) -> dict[str, Any]:
    """一行台账夹具（键与落盘行同一套；`fault_kind=None` = 老行没有那一格）。"""
    judge: dict[str, Any] = {"axis": axis, "checked": checked, "decision": "",
                             "reason": reason}
    if kind is not None:
        judge["fault_kind"] = kind
    if cause is not None and kind is not None:
        judge["fault_cause"] = cause
    if report_gap is not None:
        judge["report_gap"] = report_gap
    row: dict[str, Any] = {
        "at": "2026-11-09T10:54:45+08:00",
        "defect_step": defect_step,
        "findings": list(findings or []),
        "proof_no": 1,
        "proof_sha256": proof_sha256,
        "secretary_judge": judge,
        "statement_id": SID,
        "stmt_id": SID,
        "unresolved_errors": int(unresolved_errors),
        "verdict": verdict,
        "verification_id": "v-000001",
        "why": "",
    }
    if review_call:
        row["review_call"] = review_call
    if review_pass is not None:
        row["review_pass"] = review_pass
    return row


def _error(step: int) -> dict[str, Any]:
    return {"detail": "第 %d 步缺依据" % step, "level": "error", "step": step}


# ============================================================ ① 写侧分类


def test_the_clean_reading_carries_the_report_gap_as_a_cause() -> None:
    """`decision=没问题` + `report_gap` 文本 ⇒ clean、kind 空、cause=report_gap（可投票）。"""
    reading = SEC.v_reply_fault_reading(
        decision=SEC.V_REPLY_CLEAN,
        report_gap="没有写出反例尝试的位置")
    assert reading["axis"] == "clean"
    assert reading["fault_kind"] == ""
    assert reading["fault_cause"] == "report_gap"
    assert reading["report_gap"] == "没有写出反例尝试的位置"


def test_a_clean_decision_never_carries_a_fault_kind() -> None:
    """模型同时答「没问题」与 `defect_kind=math` ⇒ kind 不采信（写侧归一是硬要求）。"""
    reading = SEC.v_reply_fault_reading(decision=SEC.V_REPLY_CLEAN,
                                        defect_kind="math")
    assert reading["axis"] == "clean"
    assert reading["fault_kind"] == ""
    assert reading["fault_cause"] == ""


def test_the_four_kinds_are_read_verbatim_and_procedural_gets_self_declared() -> None:
    """判 fault ⇒ 四类原样读；procedural 的 cause 是 self_declared（V 自己说没验证）。"""
    for kind in VR.FAULT_KINDS:
        reading = SEC.v_reply_fault_reading(decision=SEC.V_REPLY_FAULT,
                                            defect_kind=kind)
        assert reading["axis"] == "fault", (kind, reading)
        assert reading["fault_kind"] == kind, (kind, reading)
        assert reading["fault_cause"] == ("self_declared" if kind == "procedural" else "")


def test_a_report_gap_written_as_a_kind_becomes_a_cause_not_a_fault() -> None:
    """业主裁定 ①：模型把"只缺反例尝试记录"写进 kind ⇒ kind 空、cause=report_gap。"""
    reading = SEC.v_reply_fault_reading(decision=SEC.V_REPLY_FAULT,
                                        defect_kind="report_gap")
    assert (reading["axis"], reading["fault_kind"], reading["fault_cause"]) == (
        "fault", "", "report_gap")


def test_an_unknown_kind_is_left_empty_so_the_write_side_defaults_to_math() -> None:
    """拼错的类别不许静默解锁：这里留空，写行处按 math 兜底（下一节）。"""
    reading = SEC.v_reply_fault_reading(decision=SEC.V_REPLY_FAULT,
                                        defect_kind="banana")
    assert reading["axis"] == "fault"
    assert reading["fault_kind"] == ""


def test_an_out_of_vocabulary_decision_has_no_axis_and_no_kind() -> None:
    """`判不了` / 空串不是一种结论：没有轴、四个类别格全空（p247 + 业主 2026-10-30）。"""
    for decision in ("判不了", "", "看不出来"):
        reading = SEC.v_reply_fault_reading(decision=decision, defect_kind="math")
        assert reading == {"axis": "", "fault_kind": "", "fault_cause": "",
                           "report_gap": ""}, decision


def test_the_report_gap_text_predicate_is_the_one_reading_side_predicate() -> None:
    """`says_only_a_report_gap` 与读侧同一张措辞表（98b 的 4 条逐字命中）。"""
    assert VR.says_only_a_report_gap(_reason_98b_gap()) is True
    assert VR.says_only_a_report_gap("对反例仅写“未构造出反例”，没有尝试记录") is True
    assert VR.says_only_a_report_gap(_reason_math()) is False
    assert VR.says_only_a_report_gap("") is False


def test_the_ledger_writer_lands_the_three_classification_cells(tmp_path: Path) -> None:
    """写口把三个类别格落进 `secretary_judge`（不新增磁盘字段），没给就不写。"""
    judge = {"checked": True, "axis": "fault", "decision": "有缺陷要指出",
             "reason": "V 自己说没有逐行验证。",
             "fault_kind": "procedural", "fault_cause": "self_declared",
             "report_gap": ""}
    row = VR.record_verification(tmp_path, statement_id=SID, proof_text=PROOF,
                                 verdict={"verdict": "成立", "findings": []},
                                 proof_no=1, secretary_judge=judge)
    cell = dict(row[VR.SECRETARY_JUDGE_KEY])
    assert (cell.get("fault_kind"), cell.get("fault_cause"), cell.get("report_gap")) == (
        "procedural", "self_declared", ""), cell
    reading = VR.fault_kind_of(row)
    assert (reading["kind"], reading["cause"], reading["source"]) == (
        "procedural", "self_declared", "row"), reading

    # 没给类别格（老测试夹具 / 非 V 写口）⇒ 一个字节都不写，读法回到 legacy_*。
    old = VR.record_verification(tmp_path, statement_id=SID, proof_text=PROOF,
                                 verdict={"verdict": "成立", "findings": []},
                                 proof_no=1,
                                 secretary_judge={"checked": True, "axis": "fault",
                                                  "decision": "有缺陷要指出",
                                                  "reason": _reason_98b_gap()})
    assert "fault_kind" not in old[VR.SECRETARY_JUDGE_KEY]
    assert VR.fault_kind_of(old)["source"] == "legacy_shape"
