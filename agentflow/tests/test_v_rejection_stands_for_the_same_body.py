# -*- coding: utf-8 -*-
"""业主 2026-11-06（裁定 3）的准确含义：一次判有毛病 ⇒ 立刻打回，同一份正文不再起转。

口径逐字（本次唯一准绳）：

    「3 的形状有问题，一次判有毛病时应该立即打回，不再起转，等下一次提交时重新从 0 转计数」

拆成三句可执行的：

1. 同一次送审里，某一转判「有毛病」⇒ 立刻打回、这次送审结束，不再起第 4、5 转；
2. 打回站住：同一份正文（同一个 `proof_sha256`）在改稿之前重送，不构成一次新的送审
   —— 不许把"打回之后又起转"的那一趟当成"另一次送审攒够了三转"；
3. 下一次真正的提交（F 改过字 ⇒ sha 变了）从 0 起数，三转 clean 才发签。

## 现场（只读取证：`projects/R-mk-infinite-94/verifications/000034.jsonl`）

| 行 | 轮 | `review_call` | `review_pass` | 秘书轴 |
|---|---|---|---|---|
| v-000001 | 1 | `841d6720449b` | 1 | clean |
| v-000002 | 2 | `841d6720449b` | 2 | Fault（打回） |
| v-000003 | 3 | `ffc98d2bb6e0` | 1 | clean |
| v-000004 | 4 | `ffc98d2bb6e0` | 2 | clean |
| v-000005 | 5 | `ffc98d2bb6e0` | 3 | clean |

稿上签块写「连续=3/3」。按业主口径这个形状本来就不该出现：v2 判 fault 时就该打回，
v3–v5 是同一份正文（同一个 sha `82af883c7935…`）重开的一趟，三转 clean 之后签上了 ——
于是"被打回过"的那一份正文靠重掷拿到了签，而台账里"打回"只是被降成一条历史读数。

## 判据（先红后绿 + 反真空）

| 编号 | 它要证明的事 | 改前（本文件首次运行） |
|---|---|---|
| a | 现场复刻（同一份正文、两次送审、5 个回复）⇒ 只问 2 次模型、`terminal=rejected`、`streak=0`、台账 2 行、不签发 | 红：问 5 次、v3–v5 三转 clean ⇒ 签上（`signed_bit3=True`） |
| b | 打回之后改稿再送 ⇒ 从 0 起数：1 / 2 / 3，第三转才签 | 绿（连判循环既有） |
| c | 一次送审三转全 clean ⇒ 正常签发（既有行为不许坏） | 绿 |
| d | 反真空：摘掉"打回站住"那一格 ⇒ a 变回"问 5 次并且签了"；摘掉 fault 的 `break` ⇒ 同一趟会接着问第 3 转 | 那是被修掉的那个形状 |
| e | 现场那 5 行按新口径复算 ⇒ `[1, 0, 0, 0, 0]`、`streak=0`、`state=rejected`、`signs_bit3=False`；老行（没有 `review_call`）仍按旧口径读 | 红：`[1, 0, 1, 2, 3]`、`state=signed`、连签 3/3 |
| f | 重送义务：现场那种 sha（1 行 fault + 3 行 clean-after-reject）⇒ `obligations.resubmit_cleared` 的 `cleared=False`（作废行不许把义务清掉）；负控：改稿之后拿到干净的「成立」⇒ `cleared=True` | 红：作废行被当成"更干净的成立" ⇒ `cleared=True`、「要你重送」消失 |
| g | 不传 `within_call` 的历史兼容门（在册穷举支走的就是它）也站住：`sign_statement` 数出 `streak=0`、不翻位 | 红：`streak=3`、位翻上去 |

## 这些替身量的是什么

V 的审阅缝（`_ReviewSeam`）逐个交出预置回复并按次数计数（`asked()`），秘书缝（`_Seam`）
按 `note` 回预置 JSON —— 与 `test_v_reviews_three_times_before_signing.py` 同一套夹具。
它们证明的是"这条链会不会自己再问一次、停在第几转、签是哪一转发的"，不证明模型的
判断质量（真模型一次都不调）。
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import obligations as OBL
from agentflow.agent_v import AgentV, core as AV_CORE

from _proof_manuscript_fixture import write_proof_manuscript
import test_v_reviews_three_times_before_signing as T3
from test_v_reviews_three_times_before_signing import (
    CLEAN_REPLY,
    FAULT_REPLY,
    FULL,
    PROOF,
    REL,
    SID,
    WASHED,
    _axis,
    _put,
    _rows,
    _ReviewSeam,
    _Seam,
    _secretary,
    _stmt_row,
    _ws,
)

#: 改稿之后的那一份正文（sha 必须变 —— 这正是"下一次提交"的判据）。
PROOF_B = PROOF + "\n3. 补一条：n ≥ 3 时 C_n 的弦长集合非空。"

#: 现场那 5 行的形状（两个 `review_call`、第二行是 fault）。
FIELD_ROWS = (
    ("v-1", "841d6720449b", 1, "clean"),
    ("v-2", "841d6720449b", 2, "fault"),
    ("v-3", "ffc98d2bb6e0", 1, "clean"),
    ("v-4", "ffc98d2bb6e0", 2, "clean"),
    ("v-5", "ffc98d2bb6e0", 3, "clean"),
)


def _agent(st, replies, axes, *, sign_axes=None):
    """一套 V（审阅缝按 `replies` 计数）+ 一套秘书缝（按 `axes` 判轴）。"""
    review = _ReviewSeam(list(replies))
    seam = _Seam({"v_reply_defect": [_axis(a) for a in axes],
                  "wash_v_reply": [{"text": WASHED, "step": 2,
                                    "findings": [{"quote": "第 2 步的记号没有定义",
                                                  "why": "记号没有定义就没法核这一步"}]}]
                  * max(1, len(axes)),
                  "sign_issuance": [_axis(a) for a in (sign_axes or [SEC.SIGN_ISSUE])]
                  * max(1, len(axes))})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=_secretary(st, seam))
    return agent, review


def _revise(st) -> str:
    """F 改稿：命题行与按号稿一起换成 `PROOF_B`（两处一起换才是真的"下一次提交"）。"""
    row = _stmt_row(st)
    row["proof_text"] = PROOF_B
    row["bits"] = EB.bits_of(proof=True, proof_process=PROOF_B, kind="theorem")
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    write_proof_manuscript(st.root, SID, PROOF_B, statement_full=FULL)
    return PROOF_B


# ============================================================ a：现场复刻（同一份正文两次送审）

def test_a_the_field_shape_asks_two_times_and_never_signs(tmp_path):
    """5 个回复、同一份正文送两趟 ⇒ 只问 2 次、第二转就是终局、不签发。

    这一条量的就是现场（`R-mk-infinite-94` 的 000034）：改前第一趟判 fault 之后，
    同一份正文又起了一趟，v3–v5 三转 clean ⇒ 签上（`signed_bit3=True`，模型一共问 5 次）。
    """
    st = _ws(tmp_path)
    _put(st)
    agent, review = _agent(st, [CLEAN_REPLY, FAULT_REPLY, CLEAN_REPLY, CLEAN_REPLY, CLEAN_REPLY],
                           [SEC.V_REPLY_CLEAN, SEC.V_REPLY_FAULT, SEC.V_REPLY_CLEAN,
                            SEC.V_REPLY_CLEAN, SEC.V_REPLY_CLEAN])

    first = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    # ① 同一次送审：第 2 转判 fault ⇒ 立刻打回，不再起第 3 转。
    assert review.asked() == 2, (
        f"第 2 转已经判 fault，却又问了 {review.asked()} 次模型 ⇒ 「立刻打回」没做到")
    passes = first.get("review_passes") or []
    assert [p["axis"] for p in passes] == ["clean", "fault"], passes
    assert [p["streak"] for p in passes] == [1, 0], passes
    assert passes[-1]["terminal"] == "rejected", passes
    assert first["signed_bit3"] is False and first["sign_issuance"]["issued"] is False, first
    assert len(_rows(st)) == 2, _rows(st)

    # ② 同一份正文（同一个 sha）再送 ⇒ 打回站住：不问模型、不落行、不签发。
    second = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert review.asked() == 2, (
        f"同一份正文再送又问了一次模型（累计 {review.asked()} 次）⇒ 打回没有站住")
    assert second["review_passes"] == [], second["review_passes"]
    assert second["checked"] is True, second
    assert "打回站住" in str(second["reason"]), second["reason"]
    assert second["signed_bit3"] is False, second
    assert second["sign_issuance"]["issue"] is False, second["sign_issuance"]
    assert second["sign_issuance"]["streak"] == 0, second["sign_issuance"]
    assert len(_rows(st)) == 2, f"打回站住那一趟不许落台账行：{_rows(st)}"

    # 读侧同一份读数：这一份正文是打回状态、连续 0。
    standing = VR.review_standing(st.root, statement_id=SID, proof_text=PROOF, proof_no=1)
    assert standing["state"] == "rejected", standing
    assert standing["streak"] == 0 and standing["streak_ok"] is False, standing
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]


# ============================================================ b：改稿之后从 0 起数

def test_b_the_next_submission_counts_from_zero_after_the_revision(tmp_path):
    """打回之后改稿再送 ⇒ 0 → 1 → 2 → 3，第三转才发签（不是接着上一次的数攒）。"""
    st = _ws(tmp_path)
    _put(st)
    agent, review = _agent(st, [CLEAN_REPLY, FAULT_REPLY],
                           [SEC.V_REPLY_CLEAN, SEC.V_REPLY_FAULT])
    agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert review.asked() == 2
    before = VR.review_standing(st.root, statement_id=SID, proof_text=PROOF, proof_no=1)
    assert before["streak"] == 0, before  # 打回之后：0

    proof_b = _revise(st)
    after_revision = VR.review_standing(st.root, statement_id=SID, proof_text=proof_b,
                                        proof_no=1)
    assert after_revision["streak"] == 0, (
        f"改稿之后起始连续数不是 0：{after_revision}")

    review.replies = [CLEAN_REPLY] * 3
    agent2, review2 = _agent(st, [CLEAN_REPLY] * 3, [SEC.V_REPLY_CLEAN] * 3)
    with T3._as_submitter():
        got = agent2.verify_proof(SID, proof_text=proof_b, proof_manuscript=REL)
    assert review2.asked() == 3, (
        f"改稿之后问了 {review2.asked()} 次（应当是三转 clean ⇒ 3 次）")
    assert review.asked() == 2, review.asked()
    passes = got.get("review_passes") or []
    assert [p["axis"] for p in passes] == ["clean"] * 3, passes
    assert [p["streak"] for p in passes] == [1, 2, 3], passes
    assert passes[-1]["terminal"] == "signed", passes
    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]
    assert got["sign_issuance"]["streak"] == 3, got["sign_issuance"]
    assert got["review_write"].get("manuscript_signed") is True, got["review_write"]
    assert got["signed_bit3"] is False, got
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]


# ============================================================ c：三转 clean 照旧发签

def test_c_three_clean_rounds_in_one_submission_still_sign(tmp_path):
    """既有行为不许坏：一次送审三转全 clean ⇒ 问 3 次、streak 1/2/3、发签。"""
    st = _ws(tmp_path)
    _put(st)
    agent, review = _agent(st, [CLEAN_REPLY], [SEC.V_REPLY_CLEAN])
    with T3._as_submitter():
        got = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert review.asked() == 3, review.asked()
    passes = got.get("review_passes") or []
    assert [p["streak"] for p in passes] == [1, 2, 3], passes
    assert passes[-1]["terminal"] == "signed", passes
    assert got["signed_bit3"] is False, got
    assert got["review_write"].get("manuscript_signed") is True, got["review_write"]
    assert got["sign_issuance"]["issued"] is True, got["sign_issuance"]
    assert len(_rows(st)) == 3, _rows(st)


# ============================================================ d：反真空

def test_d_removing_the_rejection_stop_brings_the_field_shape_back(tmp_path, monkeypatch):
    """反真空：把「打回站住」那一格摘掉 ⇒ a 变回现场那个形状（问 5 次、并且签了）。

    这一条是 a 的反真空：它量的是"a 的绿真的是那一格干的"，不是"别处恰好也走不通"。
    """
    # D3 批 2：`_rejection_stands` 多了按类别分叉的那个关键字（`fault_kind`）——
    # 这一格打桩成恒 False 仍然表达"摘掉打回站住"，关键字跟着签名走即可。
    monkeypatch.setattr(AV_CORE, "_rejection_stands",
                        lambda _standing, **_kw: False)
    st = _ws(tmp_path)
    _put(st)
    agent, review = _agent(st, [CLEAN_REPLY, FAULT_REPLY, CLEAN_REPLY, CLEAN_REPLY, CLEAN_REPLY],
                           [SEC.V_REPLY_CLEAN, SEC.V_REPLY_FAULT, SEC.V_REPLY_CLEAN,
                            SEC.V_REPLY_CLEAN, SEC.V_REPLY_CLEAN])
    with T3._as_submitter():
        first = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    assert review.asked() == 2, review.asked()
    with T3._as_submitter():
        second = agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)
    # 摘掉那一格 ⇒ 同一份正文又起了一趟：一共问 5 次、而且签真的落在这份稿上（= 现场）。
    assert review.asked() == 5, f"摘掉那一格之后只问了 {review.asked()} 次（不是现场形状）"
    assert len(second.get("review_passes") or []) == 3, second.get("review_passes")
    assert [p["streak"] for p in second["review_passes"]] == [1, 2, 3], second["review_passes"]
    assert second["sign_issuance"]["issued"] is True, second["sign_issuance"]
    assert second["review_write"].get("manuscript_signed") is True, second["review_write"]
    # 两件独立的事实：稿上签了（上面那格），而 V 的台账仍把这一份正文读成「打回站住」
    # （`signed_bit3` 因此仍是 False —— V 不翻命题位，这一步归 B 收录）。
    assert second["signed_bit3"] is False, second
    assert first["signed_bit3"] is False, first
    assert VR.review_standing(st.root, statement_id=SID, proof_text=PROOF,
                              proof_no=1)["state"] == "rejected"


def test_d2_the_fault_branch_breaks_and_the_streak_is_a_real_counter():
    """反真空（结构）：fault 那一支必须当场 `break`；连续数必须是真计数、不是轮号。

    两条都用 AST 读源码（不看注释、不靠"别处恰好停住"）：

    ① 连判循环里 `axis == "fault"` 那一支的末句是 `break`（摘掉它 ⇒ 同一趟会接着问）；
    ② `streak` 的赋值不是 `pass_no`（拿轮号当连续数就是"清零后接着攒"的形状）。
    """
    src = (pathlib.Path(AV_CORE.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "verify_proof")
    loop = next(n for n in ast.walk(fn)
                if isinstance(n, ast.For) and "need" in ast.dump(n.iter))
    fault_branch = None
    for stmt in loop.body:
        if (isinstance(stmt, ast.If) and isinstance(stmt.test, ast.Compare)
                and ast.dump(stmt.test).count("'fault'") == 1
                and isinstance(stmt.test.left, ast.Name) and stmt.test.left.id == "axis"):
            fault_branch = stmt
    assert fault_branch is not None, "连判循环里找不到 `if axis == \"fault\"` 那一支"
    assert isinstance(fault_branch.body[-1], ast.Break), (
        "fault 那一支的末句不是 break ⇒ 同一趟送审会接着起第 3 转（业主裁定 3 否掉的就是它）")
    assigns = [n for n in loop.body
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "streak" for t in n.targets)]
    assert assigns, "连判循环里找不到 streak 的赋值"
    for node in assigns:
        dump = ast.dump(node.value)
        assert "pass_no" not in dump, (
            "streak 又按轮号算了（`pass_no`）⇒ 「清零后接着攒」的形状："
            f"{ast.unparse(node) if hasattr(ast, 'unparse') else dump}")


# ============================================================ e：现场那 5 行按新口径复算

def _seed_field_rows(st) -> list[dict]:
    """把现场那 5 行的形状原样落进台账（同一个 sha、两个 `review_call`）。"""
    out: list[dict] = []
    for _vid, call, pass_no, axis in FIELD_ROWS:
        out.append(VR.record_verification(
            st.root, statement_id=SID, proof_text=PROOF,
            verdict={"verdict": "成立", "why": f"夹具：现场第 {pass_no} 转",
                     "findings": [], "defect_step": None},
            verifier="agent-V", proof_no=1, store=st, flip=False,
            secretary_judge={"checked": True, "axis": axis,
                             "decision": (SEC.V_REPLY_CLEAN if axis == "clean"
                                          else SEC.V_REPLY_FAULT),
                             "reason": "夹具：现场那一转的秘书轴"},
            review_pass=pass_no, review_call=call))
    return out


def test_e_the_field_rows_are_not_one_submissions_three_rounds(tmp_path):
    """现场那 5 行按新口径复算 ⇒ 不算"一次送审攒够 3 转"：连续 0、状态 rejected、不签。"""
    st = _ws(tmp_path)
    _put(st)
    rows = _seed_field_rows(st)
    assert len(rows) == 5, rows

    runs = VR._hold_run_lengths([dict(r) for r in rows])
    assert runs == [1, 0, 0, 0, 0], (
        f"读侧把「打回之后又起转」的那三行算成了票：{runs}（改前是 [1, 0, 1, 2, 3]）")

    holds = VR.consecutive_holds(st.root, SID, proof_no=1)
    assert holds["checked"] is True, holds
    assert holds["streak"] == 0 and holds["streak_ok"] is False, holds

    standing = VR.review_standing(st.root, statement_id=SID, proof_text=PROOF, proof_no=1)
    assert standing["state"] == "rejected", standing
    assert standing["streak"] == 0, standing
    assert standing["verification_id"] == "v-000002", (
        f"打回的读数必须指回那一条 fault：{standing}")
    assert VR.signs_bit3(dict(rows[-1]),
                         streak={"streak": 0, "need": VR.SIGN_STREAK_NEED,
                                 "checked": True}) is False

    # 签块的"连续=N/N"取的是这一趟送审内的连续数：这一份正文现在是 0/need，不是 3/3。
    assert standing["streak"] != VR.SIGN_STREAK_NEED, standing


def test_e2_legacy_rows_keep_the_old_reading(tmp_path):
    """老行（2026-11-02 之前没有 `review_call` 的形态）按旧口径读：清零之后还能再攒。

    这一条是 e 的反真空：新规矩只吃"新形态的送审行"，不许顺手把历史工作区的读数
    整体翻掉（`tests/test_v_sign_gate_streak.py::test_a2` 钉着同一件事）。
    """
    st = _ws(tmp_path)
    _put(st)
    clean = {"verdict": "成立", "why": "老行一签", "findings": [], "defect_step": None}
    for _ in range(2):
        VR.record_verification(st.root, statement_id=SID, proof_text=PROOF, verdict=clean,
                               verifier="agent-V", proof_no=1, store=st, flip=False,
                               secretary_judge={"checked": True, "axis": "clean",
                                                "decision": SEC.V_REPLY_CLEAN,
                                                "reason": "夹具：老行 clean"})
    VR.record_verification(st.root, statement_id=SID, proof_text=PROOF,
                           verdict={"verdict": "有毛病", "why": "老行一条缺陷",
                                    "findings": [], "defect_step": 2},
                           verifier="agent-V", proof_no=1, store=st, flip=False,
                           secretary_judge={"checked": True, "axis": "fault",
                                            "decision": SEC.V_REPLY_FAULT,
                                            "reason": "夹具：老行 fault"})
    for _ in range(2):
        VR.record_verification(st.root, statement_id=SID, proof_text=PROOF, verdict=clean,
                               verifier="agent-V", proof_no=1, store=st, flip=False,
                               secretary_judge={"checked": True, "axis": "clean",
                                                "decision": SEC.V_REPLY_CLEAN,
                                                "reason": "夹具：老行 clean"})
    runs = VR._hold_run_lengths([dict(r) for r in _rows(st)])
    assert runs == [1, 2, 0, 1, 2], (
        f"老行被新规矩牵连了：{runs}（老行应当仍是「fault 清零之后还能再攒」）")

# ============================================================ f：重送义务不许被作废行清掉

def test_f_the_resubmit_obligation_is_not_cleared_by_a_void_row(tmp_path):
    """现场那种 sha（1 行 fault + 3 行 clean-after-reject）⇒ `resubmit_cleared` = False。

    这是"打回即站住"的另一半：作废行既不算票（e），也不许把"要你重送"的义务清掉。
    两处必须同一把尺 —— 一边不算票、一边却把义务清掉，于是一份被重掷签上的正文
    既不欠票、也不再有人要求它重送。

    读数（本机，三条都贴）：
    - 现场 5 行（同一个 sha）⇒ `checked=True, cleared=False, why="…义务还在"`。
      注意：这一档不是作废行救回来的 —— `resubmit_cleared` 本来只找"在这个 sha 的
      所有行之后"的干净成立，同 sha 的行永远不在扫描范围里。所以这里量的是不再回归。
    - 真正的漏算在混 sha（台账里两份正文的行交错出现）：
      `A clean / B fault / A clean / B 的作废 clean` —— 作废行若被当成"更干净的成立"
      就会把 A 的义务清掉。改前 `cleared=True`（清错），改后 `False`（义务还在）。
    - 负控（反真空）：改稿之后（新 sha）落一条真正干净的「成立」⇒ `cleared=True`，
      说明这个 False 不是"恒 False"。
    """
    st = _ws(tmp_path)
    _put(st)
    _seed_field_rows(st)
    sha = VR.text_sha(PROOF)
    got = OBL.resubmit_cleared(root=st.root, label=f"{SID}#p1", proof_sha=sha)
    assert got["checked"] is True, got
    assert got["cleared"] is False, got
    assert "义务还在" in got["why"], got

    proof_b = _revise(st)
    VR.record_verification(st.root, statement_id=SID, proof_text=proof_b,
                           verdict={"verdict": "成立", "why": "改稿之后的一转 clean",
                                    "findings": [], "defect_step": None},
                           verifier="agent-V", proof_no=1, store=st, flip=False,
                           secretary_judge={"checked": True, "axis": "clean",
                                            "decision": SEC.V_REPLY_CLEAN,
                                            "reason": "夹具：改稿之后的 clean"},
                           review_pass=1, review_call="c0ffee000001")
    cleared = OBL.resubmit_cleared(root=st.root, label=f"{SID}#p1", proof_sha=sha)
    assert cleared["cleared"] is True, cleared
    assert "义务已清" in cleared["why"], cleared

    # ---- 混 sha（这才是作废行会咬人的那一档）----------------------------------
    #
    # `A clean / B fault / A clean / B 打回之后又起转的 clean`：最后那一行按新口径是
    # 作废行；它若被当成"更干净的成立"，A 的"要你重送"义务就被清掉了（改前 True）。
    st2 = _ws(tmp_path / "mixed")
    _put(st2)
    sha_a, sha_b = VR.text_sha(PROOF), VR.text_sha(PROOF_B)

    def _rec(text: str, axis: str, call: str, pass_no: int) -> dict:
        return VR.record_verification(
            st2.root, statement_id=SID, proof_text=text,
            verdict={"verdict": "成立", "why": "夹具：混 sha 现场",
                     "findings": [], "defect_step": None},
            verifier="agent-V", proof_no=1, store=st2, flip=False,
            secretary_judge={"checked": True, "axis": axis,
                             "decision": (SEC.V_REPLY_CLEAN if axis == "clean"
                                          else SEC.V_REPLY_FAULT),
                             "reason": "夹具：混 sha 现场"},
            review_call=call, review_pass=pass_no)

    _rec(PROOF, "clean", "m1", 1)
    _rec(PROOF_B, "fault", "m2", 1)
    _rec(PROOF, "clean", "m3", 1)
    _rec(PROOF_B, "clean", "m4", 2)          # B 打回之后又起转 ⇒ 作废行
    mixed = OBL.resubmit_cleared(root=st2.root, label=f"{SID}#p1", proof_sha=sha_a)
    assert mixed["checked"] is True, mixed
    assert mixed["cleared"] is False, (
        "作废行把另一份正文的「要你重送」义务清掉了：" + str(mixed))
    assert "义务还在" in mixed["why"], mixed
    assert sha_a and sha_b  # 两份正文都在盘上（夹具前提）


# ============================================================ g：历史兼容门也站住（#7）

def test_g_the_historical_gate_holds_the_same_line(tmp_path):
    """不传 `sign_issuance.within_call` 的那道门（在册穷举支走的就是它）也站住。

    `agent_v/core.py` 的穷举在册支调 `_decide_sign_issuance` 时不给 `within_call`
    （它自己的注释写明"签发仍走历史台账门"）⇒ `verifications.sign_statement` 现数台账
    尾部连续数（`consecutive_holds`）。这一条实测那道门：同一份 sha 上先打回、再起三转
    clean 之后，历史门数出来的连续次数是 0，位不翻。
    """
    st = _ws(tmp_path)
    _put(st)
    rows = _seed_field_rows(st)
    got = VR.sign_statement(st, row=dict(rows[-1]), proof_text=PROOF, proof_no=1,
                            append_ledger=False)
    assert got["append_state"] == "appended_by_caller", got
    assert got["streak"] == 0 and got["streak_ok"] is False, got
    assert got["written"] is False, got
    # 这一句在 `3892242d`（PA4，业主 2026-11-04 口径）由「还差次数 …（连续 3 次没问题
    # 才发签）」改成「门槛还没到 …（门槛由框架按这一趟送审自己数；跨趟不累计）」
    # —— 旧措辞正是在教模型 V 内部有几轮，按裁定清零。判据跟着换面，不是放宽：
    # 仍旧逐字咬住"这一签没成、第 3 位不翻"这两件事，另加"跨趟不累计"这一句。
    assert "门槛还没到" in str(got["reason"]), got
    assert "第 3 位不翻" in str(got["reason"]), got
    assert "跨趟不累计" in str(got["reason"]), got
    assert _stmt_row(st)["bits"]["reviewed"] is False, _stmt_row(st)["bits"]
