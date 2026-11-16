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

from agentflow import conductor as CND
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import obligations as OBL
from agentflow.agent_v import AgentV
from agentflow.agent_v import core as AG

#: 与 `test_v_reviews_three_times_before_signing.py` 同一套夹具（V 的审阅缝 + 秘书缝）：
#: 它们证明的是"每一问落在哪个分支、每一类拿到哪一套后果"，真模型一次都不调。
#: 用模块名取 `T3.SID` / `T3.PROOF` / `T3.REL`：本文件自己那组纯函数夹具叫 `SID` / `PROOF`
#: （两者是不同的命题号，混用会让"台账落在哪个工作区"变得看不出来）。
import test_v_reviews_three_times_before_signing as T3  # noqa: E402

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


def _write_ledger(root: Path, rows: list[dict[str, Any]]) -> None:
    """把夹具行按命题号落成 `<root>/verifications/<sid>.jsonl`（只用于 tmp_path）。"""
    ledger = root / "verifications"
    ledger.mkdir(parents=True, exist_ok=True)
    by_statement: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_statement.setdefault(str(row["statement_id"]), []).append(row)
    for statement_id, group in by_statement.items():
        text = "\n".join(json.dumps(row, ensure_ascii=False) for row in group) + "\n"
        (ledger / f"{statement_id}.jsonl").write_text(text, encoding="utf-8")


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


# ============================================================ ② 后果分叉（16 格矩阵）

#: V 的回复：逐行核对、没写反例尝试的位置（98b 那 4 条的形状）。
GAP_CLEAN_REPLY = json.dumps(
    {"verdict": "成立", "why": "逐行核对了假设关与定理链，未发现缺陷。", "findings": []},
    ensure_ascii=False)

WASHED = {"text": "第 2 步的记号没有定义：请补上记号说明之后再送 V 重签。", "step": 2,
          "findings": [{"quote": "第 2 步的记号没有定义", "why": "记号没定义就没法核这一步"}]}


def _conductor(st: Any) -> Any:
    """已经装配的主控（与生产同一个取口；判据不自己造第二个）。"""
    from agentflow.tools.conductor_tools import conductor_for

    return conductor_for(st)


def _agent_row(st: Any, *, role: str = "F", parent: str = "t-root",
               depth: int = 2) -> str:
    """落一条代理行（`kind` 空）：义务负责人 / 送审者都用它。"""
    return CND.Conductor._write_new_row(_conductor(st), {
        "task_id": "", "role": role, "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": depth,
        "input_key": f"@t:{role}:{T3.SID}", "status": "done", "outcome": "ok",
        "refusal_reason": None, "instance": f"{role}#1", "detail": "夹具",
        "error": None, "started_at": "2026-11-16T21:00:00+08:00",
        "ended_at": "2026-11-16T21:00:00+08:00", "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="probe:agent")


def _run_fault(tmp_path: Path, kind: str, *, st: Any = None,
               parent: str = "") -> dict[str, Any]:
    """同一份夹具、同一条回复，只把秘书给的 `defect_kind` 换掉 —— 三套后果逐格对拍。

    `parent` 给了（一条 `tasks` 里存在的送审者）⇒ 用真实送审挂点，义务有负责人；
    不给 ⇒ 用 `T3._as_submitter()`（挂点没有台账行 ⇒ 重送义务记 `unowned`，不开项）。
    """
    st = st or T3._ws(tmp_path)
    T3._put(st)
    review = T3._ReviewSeam([T3.CLEAN_REPLY, T3.FAULT_REPLY])
    seam = T3._Seam({
        "v_reply_defect": [T3._axis(SEC.V_REPLY_CLEAN),
                           T3._axis(SEC.V_REPLY_FAULT, defect_kind=kind)],
        "wash_v_reply": [WASHED]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=T3._secretary(st, seam))
    ctx = (CND.calling_as("t-v-receipt", "V", parent_task_id=parent, parent_role="F")
           if parent else T3._as_submitter())
    with ctx:
        got = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    rows, bad = VR.list_verifications(st.root, statement_id=T3.SID, limit=None)
    assert not bad, bad
    standing = VR.review_standing(st.root, statement_id=T3.SID,
                                  proof_text=T3.PROOF, proof_no=1)
    last = dict(rows[-1])
    kind_read = VR.fault_kind_of(last)
    return {
        "st": st, "got": got, "rows": [dict(r) for r in rows], "row": last,
        "standing": standing, "review": review, "seam": seam,
        "vote": VR.is_a_vote(last), "reading": VR.vote_reading(last),
        "kind": str(kind_read.get("kind") or ""),
        "source": str(kind_read.get("source") or ""),
        "lock_kind": AG._rejection_fault_kind(st.root, standing),
        "locked": AG._rejection_stands(standing,
                                       fault_kind=AG._rejection_fault_kind(st.root, standing)),
        "terminal": str((got.get("review_passes") or [{}])[-1].get("terminal") or ""),
        "issued": bool(got.get("sign_issuance", {}).get("issued")),
    }


def test_the_matrix_math_counts_no_vote_locks_the_sha_and_rejects(tmp_path: Path) -> None:
    """`math` 那一条：不算票（axis=fault）· 锁 sha（同 sha 拒）· 当趟 rejected · 不发签。"""
    got = _run_fault(tmp_path, "math")
    assert got["kind"] == "math" and got["source"] == "row", got["row"]
    assert got["reading"]["vote"] is False, got["reading"]
    assert got["reading"]["why"] == "axis_fault:math", got["reading"]
    assert got["standing"]["state"] == "rejected", got["standing"]
    assert got["lock_kind"] == "math", got["lock_kind"]
    assert got["locked"] is True, "math 的同一份正文没有锁住（同 sha 可以重掷）"
    assert got["terminal"] == "rejected", got["got"].get("review_passes")
    assert got["issued"] is False, got["got"].get("sign_issuance")


def test_the_matrix_procedural_counts_no_vote_but_does_not_lock(tmp_path: Path) -> None:
    """`procedural` 那一条：不算票 · 不锁 sha · 当趟 report（不是 rejected）· 不发签。"""
    got = _run_fault(tmp_path, "procedural")
    assert got["kind"] == "procedural" and got["source"] == "row", got["row"]
    assert got["reading"]["vote"] is False, got["reading"]
    assert got["reading"]["why"] == "axis_fault:procedural", got["reading"]
    # 台账读数仍是 rejected（`_hold_runs` 本批不碰）—— 但"锁不锁"由类别分叉：
    assert got["standing"]["state"] == "rejected", got["standing"]
    assert got["lock_kind"] == "procedural", got["lock_kind"]
    assert got["locked"] is False, "程序性仍然锁 sha（同一份正文不能原样再送）"
    assert got["terminal"] == "report", got["got"].get("review_passes")
    assert got["issued"] is False, got["got"].get("sign_issuance")
    # 不洗稿：那一格一个字都不写（不是"洗了但没落"）。
    assert "washed_relay" not in got["row"], got["row"]
    assert got["seam"].asked("wash_v_reply") == 0, got["seam"].seen


def test_the_matrix_style_counts_no_vote_but_does_not_lock(tmp_path: Path) -> None:
    """`style` 那一条：与 procedural 同一套后果（不算票、不锁、report、不发签）。"""
    got = _run_fault(tmp_path, "style")
    assert got["kind"] == "style" and got["source"] == "row", got["row"]
    assert got["reading"]["vote"] is False, got["reading"]
    assert got["locked"] is False, "文风类仍然锁 sha"
    assert got["terminal"] == "report", got["got"].get("review_passes")
    assert got["issued"] is False, got["got"].get("sign_issuance")
    assert "washed_relay" not in got["row"], got["row"]


def test_the_matrix_report_gap_counts_as_a_clean_vote(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """`report_gap` 那一条（业主裁定 ①）：算 clean 的一票 · 不锁 · 不终止 · 照常签发。"""
    monkeypatch.setattr(VR, "SIGN_STREAK_NEED", 1)
    st = T3._ws(tmp_path)
    T3._put(st)
    review = T3._ReviewSeam([GAP_CLEAN_REPLY])
    seam = T3._Seam({
        "v_reply_defect": [T3._axis(SEC.V_REPLY_CLEAN,
                                    report_gap="没有写出反例尝试的位置")],
        "sign_issuance": [T3._axis(SEC.SIGN_ISSUE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=T3._secretary(st, seam))
    with T3._as_submitter():
        got = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    rows, bad = VR.list_verifications(st.root, statement_id=T3.SID, limit=None)
    assert not bad, bad
    row = dict(rows[-1])
    reading = VR.vote_reading(row)
    assert reading["vote"] is True, reading
    assert reading["why"] == "clean", reading
    assert (reading["kind"], reading["cause"]) == ("", "report_gap"), reading
    assert reading["report_gap"] == "没有写出反例尝试的位置", reading
    assert "fault_kind" in row[VR.SECRETARY_JUDGE_KEY], row[VR.SECRETARY_JUDGE_KEY]
    assert row[VR.SECRETARY_JUDGE_KEY]["fault_kind"] == "", row
    standing = VR.review_standing(st.root, statement_id=T3.SID,
                                  proof_text=T3.PROOF, proof_no=1)
    assert standing["state"] == "signed", standing
    assert AG._rejection_fault_kind(st.root, standing) == "", standing
    assert AG._rejection_stands(standing, fault_kind="") is False, standing
    assert str((got.get("review_passes") or [{}])[-1].get("terminal") or "") == "signed", \
        got.get("review_passes")
    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]


def test_the_same_sha_can_be_resubmitted_after_a_procedural_fault(tmp_path: Path) -> None:
    """程序性之后同一份正文（同一个 sha）再送 ⇒ 真的再判，三转 clean 照发签。"""
    st = T3._ws(tmp_path)
    T3._put(st)
    review = T3._ReviewSeam([T3.CLEAN_REPLY, T3.FAULT_REPLY,
                             T3.CLEAN_REPLY, T3.CLEAN_REPLY, T3.CLEAN_REPLY])
    seam = T3._Seam({
        "v_reply_defect": [T3._axis(SEC.V_REPLY_CLEAN),
                           T3._axis(SEC.V_REPLY_FAULT, defect_kind="procedural"),
                           T3._axis(SEC.V_REPLY_CLEAN),
                           T3._axis(SEC.V_REPLY_CLEAN),
                           T3._axis(SEC.V_REPLY_CLEAN)],
        "sign_issuance": [T3._axis(SEC.SIGN_ISSUE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=T3._secretary(st, seam))
    with T3._as_submitter():
        first = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    assert review.asked() == 2, review.asked()
    assert str((first.get("review_passes") or [{}])[-1].get("terminal") or "") == "report", \
        first.get("review_passes")
    with T3._as_submitter():
        second = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    assert review.asked() == 5, (
        f"程序性之后同一份正文再送只问了 {review.asked()} 次模型 ⇒ 被当成打回站住了")
    assert [p["streak"] for p in (second.get("review_passes") or [])] == [1, 2, 3], \
        second.get("review_passes")
    assert second["sign_issuance"]["issued"] is True, second["sign_issuance"]
    assert second["review_write"].get("manuscript_signed") is True, second["review_write"]


def test_the_same_sha_is_refused_after_a_math_fault(tmp_path: Path) -> None:
    """math 之后同一份正文再送 ⇒ 打回站住：不问模型、不落新行、不签发。"""
    st = T3._ws(tmp_path)
    T3._put(st)
    review = T3._ReviewSeam([T3.CLEAN_REPLY, T3.FAULT_REPLY,
                             T3.CLEAN_REPLY, T3.CLEAN_REPLY, T3.CLEAN_REPLY])
    seam = T3._Seam({
        "v_reply_defect": [T3._axis(SEC.V_REPLY_CLEAN),
                           T3._axis(SEC.V_REPLY_FAULT, defect_kind="math")],
        "sign_issuance": [T3._axis(SEC.SIGN_ISSUE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=T3._secretary(st, seam))
    with T3._as_submitter():
        first = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    assert review.asked() == 2, review.asked()
    with T3._as_submitter():
        second = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    assert review.asked() == 2, (
        f"math 打回之后同一份正文再送又问了一次模型（累计 {review.asked()} 次）")
    assert second["review_passes"] == [], second["review_passes"]
    assert "打回站住" in str(second["reason"]), second["reason"]
    assert len(VR.list_verifications(st.root, statement_id=T3.SID, limit=None)[0]) == 2


# ============================================================ 反真空（三条）


def test_antivacuum_report_gap_judged_back_as_math_loses_the_vote(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 ①：把 `report_gap` 判回 math ⇒ 那条 clean 票当场不算票。

    对应正控：`test_the_matrix_report_gap_counts_as_a_clean_vote`。
    """
    copy = _row(verdict="成立", axis="clean",
                kind="", cause="report_gap",
                report_gap="没有写出反例尝试的位置")
    assert VR.is_a_vote(copy) is True
    original = VR.fault_kind_of

    def wrong(row):
        reading = original(row)
        if reading.get("cause") == "report_gap" or reading.get("report_gap"):
            return {**reading, "kind": "math"}
        return reading

    monkeypatch.setattr(VR, "fault_kind_of", wrong)
    assert VR.is_a_vote(copy) is False, (
        "把 report_gap 判回 math 之后它仍然算票 ⇒ 正控不依赖 kind，那一条是真空")


def test_antivacuum_procedural_judged_as_locked_breaks_the_resubmit(
        tmp_path: Path) -> None:
    """反真空 ②：程序性那一行按"空类别"读 ⇒ `_rejection_stands` 立刻变回锁住。

    对应正控：`test_the_same_sha_can_be_resubmitted_after_a_procedural_fault`。
    """
    got = _run_fault(tmp_path, "procedural")
    assert AG._rejection_stands(got["standing"], fault_kind="procedural") is False
    # 摘掉类别（等于旧行 / 缺分类）⇒ 同一份台账读数必须变回"站住"。
    assert AG._rejection_stands(got["standing"], fault_kind="") is True


def test_antivacuum_a_math_defect_labelled_procedural_is_folded_back(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空 ③：护栏被摘掉时，带数学证据的行会被说成 procedural ⇒ 不锁 sha。

    对应正控：`_write_fault_cell` 把"procedural + 数学证据"强制折回 math（只往更严折）。
    """
    judgment = {"checked": True, "axis": "fault", "fault_kind": "procedural",
                "fault_cause": "", "report_gap": "", "reason": "V 说没有逐行验证。",
                "basis": []}
    verdict = {"verdict": "成立", "findings": [_error(2)], "defect_step": 2}
    cell = AG._write_fault_cell(judgment, verdict)
    assert cell["fault_kind"] == "math", cell
    assert cell["kind_override"] == "guard:carries_math_evidence", cell

    monkeypatch.setattr(AG, "_verdict_has_math_evidence", lambda _v: False)
    wrong = AG._write_fault_cell(judgment, verdict)
    assert wrong["fault_kind"] == "procedural", wrong
    assert AG._rejection_stands({"state": "rejected"},
                                fault_kind=wrong["fault_kind"]) is False


# ============================================================ ③ 回执与义务


def _task_keys(st: Any, prefix: str) -> list[dict[str, Any]]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(prefix)]


def test_a_procedural_fault_opens_no_resubmit_obligation(tmp_path: Path) -> None:
    """程序性：不开 `v-resubmit@…`（改稿义务）；判词仍作为 V 稿 notice 送到送审者。

    2026-11-16「V 回执投递层退场」之后，"可原样再送"那句话不再由这一层拼一条回执
    正文（回执正文随投递层一起删了）；留下的是两条语义：
    ① 程序性 / 文风不是打回 ⇒ 没有改稿义务；② 这一签的类别仍可在 `report_fix_list`
    里读到（`requires_rewrite=False`），所以"不用改稿"这件事没有丢。
    """
    st = T3._ws(tmp_path)
    _conductor(st)
    recipient = _agent_row(st, role="F")
    got = _run_fault(tmp_path, "procedural", st=st, parent=recipient)
    # 义务：一条都不开（那一档不是打回）。
    assert _task_keys(st, OBL.RESUBMIT_PREFIX) == [], [
        r.get("input_key") for r in st.rows("tasks")]
    # 送达：V 稿 notice 在送审者名下（判词送到 ≠ 开一条改稿义务）。
    notices = _task_keys(st, "v-review@")
    assert len(notices) == 1, [r.get("input_key") for r in st.rows("tasks")]
    assert str(notices[0].get("parent_task_id") or "") == recipient, notices[0]
    # "可原样再送"这句话在退场后由这份 notice 承担（原先在回执正文里）。
    assert "原样再送" in str(notices[0].get("detail") or ""), notices[0].get("detail")
    # "不用改稿"的类别读数仍在（`report_fix_list` 是它的唯一读口）。
    fix = VR.report_fix_list(st.root, statement_id=T3.SID)
    assert fix["checked"] is True, fix
    assert any(one["requires_rewrite"] is False for one in fix["items"]), fix
    assert got.get("kind"), got


def test_report_fix_list_counts_attempts_without_a_cap(tmp_path: Path) -> None:
    """`report_fix_list`：同一 sha 上两趟程序性 ⇒ attempts 1、2；最后一条 `last_at` 同值。"""
    st = T3._ws(tmp_path)
    T3._put(st)
    review = T3._ReviewSeam([T3.CLEAN_REPLY, T3.FAULT_REPLY,
                             T3.CLEAN_REPLY, T3.FAULT_REPLY])
    seam = T3._Seam({
        "v_reply_defect": [T3._axis(SEC.V_REPLY_CLEAN),
                           T3._axis(SEC.V_REPLY_FAULT, defect_kind="procedural"),
                           T3._axis(SEC.V_REPLY_CLEAN),
                           T3._axis(SEC.V_REPLY_FAULT, defect_kind="procedural")]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=T3._secretary(st, seam))
    with T3._as_submitter():
        agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    with T3._as_submitter():
        agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    fix = VR.report_fix_list(st.root, statement_id=T3.SID)
    assert fix["checked"] is True, fix
    assert len(fix["items"]) == 2, fix
    assert [one["attempts"] for one in fix["items"]] == [1, 2], fix
    assert len({one["sha"] for one in fix["items"]}) == 1, fix
    assert fix["items"][0]["last_at"] == fix["items"][1]["last_at"], fix
    for one in fix["items"]:
        assert one["kind"] == "procedural", one
        assert one["requires_rewrite"] is False, one
        assert one["addressee"] == "V", one
        assert one["quote"], one


def test_report_fix_list_excludes_math_and_report_gap(tmp_path: Path) -> None:
    """math / contract 不进这张表（那是缺陷清单）；report_gap 是 clean 的质量读数，也不进。"""
    st = T3._ws(tmp_path)
    T3._put(st)
    review = T3._ReviewSeam([T3.CLEAN_REPLY, T3.FAULT_REPLY])
    seam = T3._Seam({"v_reply_defect": [T3._axis(SEC.V_REPLY_CLEAN),
                                        T3._axis(SEC.V_REPLY_FAULT,
                                                 defect_kind="math")]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=T3._secretary(st, seam))
    with T3._as_submitter():
        agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    fix = VR.report_fix_list(st.root, statement_id=T3.SID)
    assert fix["checked"] is True and fix["items"] == [], fix

    # report_gap 那一档（clean 行）同样不进：它不是缺陷，只是报告质量读数。
    gap = _row(verdict="成立", axis="clean", kind="", cause="report_gap",
               report_gap="没有写出反例尝试的位置")
    gap_path = tmp_path / "gap-ws"
    _write_ledger(gap_path, [gap])
    fix2 = VR.report_fix_list(gap_path, statement_id=SID)
    assert fix2["checked"] is True and fix2["items"] == [], fix2


def test_report_fix_list_says_not_checked_when_the_ledger_is_unreadable(
        tmp_path: Path) -> None:
    """读不成是"没查成"（checked=False + why），不是"没有待改项"。"""
    ledger = tmp_path / "verifications"
    ledger.mkdir(parents=True)
    (ledger / f"{SID}.jsonl").write_text("{not json}\n", encoding="utf-8")
    fix = VR.report_fix_list(tmp_path, statement_id=SID)
    assert fix["checked"] is False, fix
    assert "没查成" in fix["why"], fix


