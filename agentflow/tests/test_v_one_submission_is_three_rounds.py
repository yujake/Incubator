# -*- coding: utf-8 -*-
"""业主 2026-11-02 定稿：一次送审 = 同一次调用内连判三轮；跨调用绝不累计。

口径逐字（本次唯一准绳）：

    「发一次送审，V就会连判三次，三次内任何一次不通过都不签打回，三次过了就签。
      我没听懂什么叫连续三次独立送审成立，难道还是一次审只判一次成立就计数？」

    「不允许跨两次送审累计成功数」

于是四条判据（本文件就是这四条）：

| 编号 | 它要证明的事 | 改前（本文件首次运行） |
|---|---|---|
| a | 一次调用 + 三轮都成立 ⇒ 问 3 次、streak=3、出签 | 绿（连判循环 2026-10-30 已有；这里补"单次调用"的读数与签文件） |
| b | 一次调用 + 第 2 轮有毛病 ⇒ 只问 2 次就停、无签、打回带第 2 轮缺陷 | 绿（既有「立刻停」） |
| c | 一次调用 + 第 1 轮有毛病 ⇒ 只问 1 次就停、无签 | 绿（既有「立刻停」） |
| d | 反累计：旧台账已有 2 行 clean（两次历史送审各 1 轮）+ 本次送审 ⇒ 不许第 1 轮就签，必须问满 3 轮 | 红：`decide_sign_issuance` 读全台账 streak，第 1 轮就发签（只问 1 次） |

d 是本次最关键的判据：它量的是"台账里的历史 clean 行不许凑成这一次的签"。
真机依据：`projects/paper-rewrite-83` 里 000005 是同一趟 `V-20261102-030701-001`
的 p1/p2/p3 三轮 clean（`review_passes` 三格）才签；000004 是三次独立送审、
每次第 1 轮就被秘书判 fault ⇒ 三次都该打回、始终不签。

## 这些替身量的是什么

V 的审阅缝逐个交出预置回复并计数（`asked()`）；秘书缝按 `note` 回预置 JSON。
它们证明"同一次调用里真的问了几次、停在第几轮、签是哪一轮发的"，
不证明模型的判断质量（真模型一路一次都不发）。
"""
from __future__ import annotations

import json

import pytest

from agentflow import agent_loop as AL
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV

# 夹具与三连判判据共用一份（不抄第二份 CLEAN/FAULT 文本与假缝）。
from test_v_reviews_three_times_before_signing import (
    CLEAN_REPLY,
    FAULT_REPLY,
    PROOF,
    REL,
    SID,
    WASHED,
    _axis,
    _put,
    _ReviewSeam,
    _rows,
    _Seam,
    _secretary,
    _stmt_row,
    _ws,
)

#: 历史行（没有 review_call / review_pass 的那一批）用的"成立"账行原料。
OK_VERDICT = {"verdict": "成立", "why": "历史送审的一轮 clean",
              "findings": [], "defect_step": None}
#: 秘书对那一行给出的语义判定：clean（这是"历史 clean 行"要能凑数的前提）。
#: 注意轴取值是 `clean`（`V_REPLY_AXIS` 的两档），不是 `SEC.V_REPLY_CLEAN`（那是决定词）。
CLEAN_JUDGE = {"checked": True, "axis": "clean",
               "decision": SEC.V_REPLY_CLEAN, "reason": "夹具：历史一轮 clean"}


def _agent(st, review, sec_seam):
    return AgentV(st, workspace_root=st.root, llm=review,
                  secretary=_secretary(st, sec_seam))


def _sign_doc(st) -> dict:
    path = VS.sign_path(st.root, VR.proof_sha(PROOF))
    assert path.is_file(), f"没有落签：{path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_legacy_clean(st) -> dict:
    """落一行"历史形态"的 clean 台账（没有 review_call / review_pass）。

    这就是业主说的"两次历史送审各一轮成立"里的那一轮：老代码留下的行。
    新读侧必须把它识别成 `legacy_rows`，且不许拿它凑新送审的 3 轮。
    """
    return VR.record_verification(
        st.root, statement_id=SID, proof_text=PROOF, verdict=OK_VERDICT,
        verifier="agent-V", proof_no=1, store=st, flip=False,
        secretary_judge=CLEAN_JUDGE)


# ============================================================ a：一次调用三轮 clean

def test_a_one_call_asks_three_rounds_and_signs(tmp_path):
    """一次调用 + 三轮都成立 ⇒ 问 3 次、每轮 streak 是"这一次送审内的第几轮"、出签。"""
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    got = _agent(st, review, sec_seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    assert review.asked() == 3, f"一次送审只问了 {review.asked()} 次 ⇒ 不是连判三轮"
    passes = got.get("review_passes") or []
    assert [p["pass"] for p in passes] == [1, 2, 3], passes
    assert [p["streak"] for p in passes] == [1, 2, 3], passes
    assert [p["streak_ok"] for p in passes] == [False, False, True], passes
    assert [p["issue"] for p in passes] == [False, False, True], passes
    assert passes[-1]["terminal"] == "signed", passes

    assert got["signed_bit3"] is True, got
    assert got["sign_issuance"]["streak"] == 3, got["sign_issuance"]
    assert got["sign_issuance"]["need"] == 3, got["sign_issuance"]

    rows = _rows(st)
    assert len(rows) == 3, rows
    assert [r.get("review_pass") for r in rows] == [1, 2, 3], rows
    calls = {str(r.get("review_call") or "") for r in rows}
    assert len(calls) == 1 and "" not in calls, (
        f"三行不是同一次送审（review_call 应只有一个且非空）：{calls}")

    doc = _sign_doc(st)
    assert (doc["streak"], doc["need"]) == (3, 3), doc
    assert [p["verification_id"] for p in doc["passes"]] == \
        [r["verification_id"] for r in rows], doc["passes"]
    assert [p.get("review_pass") for p in doc["passes"]] == [1, 2, 3], doc["passes"]
    assert {p.get("review_call") for p in doc["passes"]} == calls, doc["passes"]


# ============================================================ b：第 2 轮 fault

def test_b_fault_on_round_two_stops_after_two_and_rejects(tmp_path):
    """一次调用 + 第 2 轮 fault ⇒ 只问 2 次、无签、打回带第 2 轮的缺陷（第 2 步）。"""
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([CLEAN_REPLY, FAULT_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN),
                                         _axis(SEC.V_REPLY_FAULT)],
                      "wash_v_reply": [{"text": WASHED, "step": 2,
                                        "findings": [{"quote": "第 2 步的记号没有定义",
                                                      "why": "记号没有定义就没法核这一步"}]}],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    got = _agent(st, review, sec_seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    assert review.asked() == 2, (
        f"第 2 轮已经判 fault，却又问了 {review.asked()} 次 ⇒ 「立刻停」没做到")
    passes = got.get("review_passes") or []
    assert [p["axis"] for p in passes] == ["clean", "fault"], passes
    assert [p["streak"] for p in passes] == [1, 0], passes
    assert passes[-1]["terminal"] == "fault", passes
    assert got["signed_bit3"] is False and got["sign_issuance"]["issued"] is False, got
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]
    assert len(_rows(st)) == 2, _rows(st)
    assert _rows(st)[-1]["washed_relay"]["text"] == WASHED, _rows(st)[-1]

    _text, details, _problems = AL.v_rejections_digest(st.root, [_stmt_row(st)])
    faults = [d for d in details if d.get("via") == "secretary_fault"]
    assert len(faults) == 1, details
    assert faults[0]["steps"] == [2], faults[0]
    assert faults[0]["washed"] == WASHED, faults[0]


# ============================================================ c：第 1 轮 fault

def test_c_fault_on_round_one_stops_after_one_and_rejects(tmp_path):
    """一次调用 + 第 1 轮 fault ⇒ 只问 1 次就停、无签。"""
    st = _ws(tmp_path)
    _put(st)
    review = _ReviewSeam([FAULT_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_FAULT)],
                      "wash_v_reply": [{"text": WASHED, "step": 2,
                                        "findings": [{"quote": "第 2 步的记号没有定义",
                                                      "why": "记号没有定义就没法核这一步"}]}],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    got = _agent(st, review, sec_seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    assert review.asked() == 1, (
        f"第 1 轮已经判 fault，却又问了 {review.asked()} 次 ⇒ 不是「立刻停」")
    passes = got.get("review_passes") or []
    assert len(passes) == 1, passes
    assert passes[0]["axis"] == "fault" and passes[0]["streak"] == 0, passes
    assert passes[0]["terminal"] == "fault", passes
    assert got["signed_bit3"] is False, got
    assert got["sign_issuance"]["issued"] is False, got["sign_issuance"]
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]
    assert len(_rows(st)) == 1, _rows(st)

    _text, details, _problems = AL.v_rejections_digest(st.root, [_stmt_row(st)])
    faults = [d for d in details if d.get("via") == "secretary_fault"]
    assert len(faults) == 1, details
    assert faults[0]["steps"] == [2], faults[0]


# ============================================================ d：反累计（本次核心）

def test_d_two_legacy_clean_rounds_cannot_add_up_to_this_submission(tmp_path):
    """旧台账已有 2 行 clean，本次第一轮 clean 不许出签：跨送审绝不累计。

    业主逐字：「不允许跨两次送审累计成功数」。

    改前红：`secretary.decide_sign_issuance` 读的是全台账尾部 streak（2+1=3）⇒
    第一轮就发签，`review.asked()` 只有 1；签文件的 `passes` 还会把两行历史行
    与本次第一轮拼成"三票"。
    改后绿：地板只看本次送审内的轮数 ⇒ 第 1、2 轮只有 `streak=1/2` 且不签，
    第 3 轮才问秘书、才出签；历史两行仍是 `legacy_rows=2`，不参与判定。
    """
    st = _ws(tmp_path)
    _put(st)
    first = _seed_legacy_clean(st)
    second = _seed_legacy_clean(st)
    assert [r.get("review_call") for r in (first, second)] == ["", ""], (first, second)
    standing = VR.review_standing(st.root, statement_id=SID, proof_text=PROOF,
                                  proof_no=1)
    assert standing["streak"] == 2, standing
    assert standing["legacy_rows"] == 2, standing

    review = _ReviewSeam([CLEAN_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    got = _agent(st, review, sec_seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    assert review.asked() == 3, (
        f"旧台账 2 行 clean + 本次第 1 轮 clean 就出签 ⇒ 跨送审累计（只问了 "
        f"{review.asked()} 次）。业主原话：「不允许跨两次送审累计成功数」")
    passes = got.get("review_passes") or []
    assert [p["streak"] for p in passes] == [1, 2, 3], passes
    assert [p["streak_ok"] for p in passes] == [False, False, True], passes
    assert [p["issue"] for p in passes] == [False, False, True], passes
    assert passes[-1]["terminal"] == "signed", passes
    assert got["sign_issuance"]["streak"] == 3, got["sign_issuance"]
    assert got["signed_bit3"] is True, got

    rows = _rows(st)
    assert len(rows) == 5, rows
    new_rows = [r for r in rows if str(r.get("review_call") or "")]
    assert len(new_rows) == 3, new_rows
    assert [r.get("review_pass") for r in new_rows] == [1, 2, 3], new_rows
    assert all(str(r.get("review_call") or "") for r in new_rows), new_rows

    after = VR.review_standing(st.root, statement_id=SID, proof_text=PROOF, proof_no=1)
    assert after["legacy_rows"] == 2, (
        "新行落盘之后历史行数变了 ⇒ legacy 识别不是按行自身的标记算的")

    doc = _sign_doc(st)
    assert (doc["streak"], doc["need"]) == (3, 3), doc
    # 签的 `passes` 必须只有本次送审的三轮 —— 不许把两行历史 clean 拼进来。
    assert [p["verification_id"] for p in doc["passes"]] == \
        [r["verification_id"] for r in new_rows], doc["passes"]
    assert [p.get("review_pass") for p in doc["passes"]] == [1, 2, 3], doc["passes"]
    assert {p.get("review_call") for p in doc["passes"]} == \
        {r.get("review_call") for r in new_rows}, doc["passes"]


def test_d2_a_second_submission_does_not_inherit_the_first_calls_two_rounds(tmp_path):
    """两次送审各判一轮 clean，不得凑成 streak=2/3：第 2 次送审仍须问满 3 轮。

    第一趟送审：第 1 轮 clean、第 2 轮模型调用失败 ⇒ 整笔返回（台账只留 1 行 clean）。
    第二趟送审：第 1 轮 clean ⇒ 改前台账尾部 1+1=2 还不够，但第 2 轮 clean 就凑到 3
    ⇒ 第 2 趟只问 2 次就签（跨调用累计）。改后必须问满 3 轮。
    """
    st = _ws(tmp_path)
    _put(st)
    # 第一趟：第一轮 clean，第二轮拿不到合法回复 ⇒ `_review_pass` 返回 ok=False，
    # 整笔 `verify_proof` 返回、台账留 1 行 clean（不落第二轮）。
    class _BrokenAfterOne(_ReviewSeam):
        def ask(self, prompt: str = "", **_kw):
            if self.asked() >= 1:
                call = super().ask(prompt, **_kw)
                call.ok = False
                call.text = ""
                call.problem = "fixture: 第二轮没拿到回复"
                return call
            return super().ask(prompt, **_kw)

    first_review = _BrokenAfterOne([CLEAN_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    _agent(st, first_review, sec_seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert first_review.asked() == 2, "夹具前提：第一趟第二轮失败（第一轮 clean 已落一行）"
    rows = _rows(st)
    assert len(rows) == 1 and str(rows[0].get("review_call") or ""), rows
    assert VR.review_standing(st.root, statement_id=SID, proof_text=PROOF,
                              proof_no=1)["streak"] == 1

    # 第二趟：三轮 clean。改前第 2 轮就会凑到 3（1+2），只问 2 次；改后问满 3。
    second_review = _ReviewSeam([CLEAN_REPLY])
    got = _agent(st, second_review, sec_seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert second_review.asked() == 3, (
        f"第二趟送审只问了 {second_review.asked()} 次就签 ⇒ 把第一趟的 1 轮 clean "
        "累计进来了（跨送审累计）")
    assert [p["streak"] for p in got["review_passes"]] == [1, 2, 3], got["review_passes"]
    assert got["signed_bit3"] is True, got
    new_rows = [r for r in _rows(st) if str(r.get("review_call") or "")]
    assert len(new_rows) == 4, _rows(st)
    calls = {str(r.get("review_call") or "") for r in new_rows}
    assert len(calls) == 2, calls  # 两趟送审各自的 call id，绝不合并
    doc = _sign_doc(st)
    assert len(doc["passes"]) == 3, doc["passes"]
    assert {p.get("review_call") for p in doc["passes"]} == \
        {str(r.get("review_call") or "") for r in new_rows[-3:]}, doc["passes"]


# ============================================================ 反真空：签文件不是空的

def test_e_the_sign_file_is_not_a_vacuous_pass(tmp_path):
    """反真空：改前的 `passes` 若把历史行拼进来，d 的断言会红；这里单独把"三票同源"钉住。"""
    st = _ws(tmp_path)
    _put(st)
    _seed_legacy_clean(st)
    _seed_legacy_clean(st)
    review = _ReviewSeam([CLEAN_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    got = _agent(st, review, sec_seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert got["signed_bit3"] is True, got

    doc = _sign_doc(st)
    passes = doc["passes"]
    assert len(passes) == 3, f"签里只有 {len(passes)} 票（三票不同源）"
    assert len({p.get("review_call") for p in passes}) == 1, passes
    assert [p.get("review_pass") for p in passes] == [1, 2, 3], passes
    assert all(p.get("proof_sha256") == VR.proof_sha(PROOF) for p in passes), passes
