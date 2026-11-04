# -*- coding: utf-8 -*-
"""判据：一条「已经签过」的命题不再被送审（2026-10-31 真机冒烟抓到的那个读数）。

## 现场（工作区 `D:\\Incubator\\projects\\abelian-smoke-20261030c`，只读）

`verifications/000001.jsonl` 12 行、全部同一个 `proof_sha256=67c95e88…`：

```text
v1        有毛病 fault / v2–v5 成立 fault（4 趟各自第一转被打回）
v6–v8     成立 clean ×3  ⇒ 连判三转 ⇒ 发签（statements[000001].bits.reviewed = True）
v9        成立 clean
v10       成立 fault     ← 签完之后仍在被送审，而且这一转被判成「有毛病」
v11–v12   成立 clean
```

问题不在"v10 那一转判得对不对"，在"这条命题还该不该被审"：第 3 位已经翻真
（`bits.reviewed=True`）之后，同一份证明（同一个 sha）「又被打回了一趟」——读侧
（`agent_loop.v_rejections_digest` → `deliver_v_verdicts`）把 v10 那一转当成"有毛病要打回"，
于是 F 会被叫去改一份「已经签过」的证明。真机证据在 `draft/142` §四。

## 三条判据

| 编号 | 它要证明的事 | 改前怎么红 | 什么改动会让它红回去 |
|---|---|---|---|
| r1 | 第 3 位已真 ⇒ 短接：`checked=True`、`signed_bit3=True`、`review_passes=[]`、`reason` 说"已经签过了"，「不落新台账行、不问模型、不问秘书」 | 同一趟调用又连判三转（多 3 行、多 3 次模型调用）⇒ 读侧照样读得出"有毛病" | 短接被摘掉 / 只短接一半（照落行、照问秘书）/ 短接时把 `signed_bit3` 说成假 |
| r2 | 负控：把 `bits.reviewed` 清成假 ⇒ 同一趟调用照常审、照常落行 | （改前本来就绿：这段代码还不认识那个位） | 短接量的不是那个位（读台账 / 读逐条表 / 恒短接）⇒ 清位之后仍然不审不落行 |
| r3 | 历史行为不变：未签的命题照旧一次判满三转（3 行、3 次模型调用、发签） | （改前本来就绿） | 短接做宽了（未签也短接）⇒ 3 行变 0 行 / 一次都不问模型 |

r2 的负控为什么必须留：r1 的三条断言（不落行 / 不问模型 / 不问秘书）可以靠「恒短接」
轻松变绿 —— 那样未签的命题再也不会被审，而 r1 一个字都不会报。r3 是同一件事的另一半：
短接必须窄到"只拦已经签过的那一条"。

## 这些替身各自量的是什么（别把它们当成"真模型跑过"）

审阅缝（`_ReviewSeam`）与秘书缝（`_Seam`）都是离线替身，夹具取自
`test_v_reviews_three_times_before_signing.py`（同一份夹具，不抄第二份）：它们证明的是
"这条链还会不会自己再问一次、每一问落在哪个分支"，不证明模型的判断质量。真模型那一路
在本文件里一次都不发。全部 tmp 工作区、零模型调用、不读写 `projects/`。
"""
from __future__ import annotations

import copy

from agentflow import agent_loop as AL
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_v import AgentV

import test_v_reviews_three_times_before_signing as T3
from _proof_manuscript_fixture import write_proof_manuscript


def _signed_agent(st):
    """一台"审阅缝只记调用、秘书缝照规则判"的 V（r1/r2 共用同一套装配）。"""
    review = T3._ReviewSeam([T3.CLEAN_REPLY])
    sec_seam = T3._Seam({"v_reply_defect": [T3._axis(SEC.V_REPLY_CLEAN)],
                         "sign_issuance": [T3._axis(SEC.SIGN_ISSUE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=T3._secretary(st, sec_seam))
    return agent, review, sec_seam


# ============================================================ r1：签过的不再送审

def test_r1_a_signed_statement_is_not_reviewed_again(tmp_path):
    """签完之后的同一趟调用必须短接：不落新行、不问模型、不问秘书、读数说得出来。

    夹具走真路：一次 `verify_proof` 自己连判三转 clean ⇒ 秘书发签 ⇒ 命题行第 3 位翻真
    （这正是真机 v6–v8 那三行的来路）。之后的调用必须一眼停下 —— 改前它又连判三转
    （真机 v9–v12 就是这么来的，其中 v10 还被判成 fault，读侧把它当"要打回"）。
    """
    st = T3._ws(tmp_path)
    T3._put(st)
    agent, review, sec_seam = _signed_agent(st)

    first = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    assert first["signed_bit3"] is True, first["sign_issuance"]
    assert T3._stmt_row(st)["bits"]["reviewed"] is True, T3._stmt_row(st)["bits"]
    signed_rows = T3._rows(st)
    assert len(signed_rows) == VR.SIGN_STREAK_NEED, signed_rows
    # 只量"签完之后"那几趟：把这一趟的调用读数清掉。
    review.prompts.clear()
    sec_seam.seen.clear()

    again = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    assert again["checked"] is True, again
    assert again["signed_bit3"] is True, again
    assert again["review_passes"] == [], (
        f"签过的命题又被连判了 {len(again['review_passes'])} 转：{again['review_passes']}")
    assert again["reason"] == "already_signed", again["reason"]
    assert again["proof_no"] == 1, again
    assert again["proof_sha256"] == VR.proof_sha(T3.PROOF), again
    assert again["bits"]["reviewed"] is True, again["bits"]

    # 不给正文那一趟（读盘上那一份）也必须同样短接：M 派 V 时常走这一支。
    without_text = agent.verify_proof(T3.SID, proof_manuscript=T3.REL)
    assert without_text["checked"] is True, without_text
    assert without_text["review_passes"] == [], without_text["review_passes"]
    assert without_text["reason"] == "already_signed", without_text["reason"]

    # 两趟都没有问模型、没有问秘书，也没有落新台账行。
    assert review.asked() == 0, (
        f"签过之后又问了 {review.asked()} 次模型："
        + "\n".join(p[-200:] for p in review.prompts))
    assert sec_seam.seen == [], f"签过之后又问了秘书：{sec_seam.seen}"
    assert len(T3._rows(st)) == len(signed_rows), (
        f"签过之后又落了台账行：{len(signed_rows)} → {len(T3._rows(st))}")

    # 读侧：这一趟一条要打回 F 的明细都没有（真机 v10 那一档正是从这儿漏出去的）。
    _text, details, problems = AL.v_rejections_digest(st.root, [T3._stmt_row(st)])
    assert problems == [], problems
    assert details == [], f"签过的命题仍然读出了要打回 F 的明细：{details}"


# ============================================================ r2：负控（量的就是那个位）

def test_r2_clearing_the_bit_lets_the_same_call_review_again(tmp_path):
    """把 `bits.reviewed` 清成假 ⇒ 同一个调用照常审、照常落行（r1 量的就是那个位）。

    负控的靶子是"恒短接"：若短接条件写成"这条命题有台账行就停"（或干脆恒停），
    这一条会红 —— 位清掉了却仍然一行不落、一次不问。
    """
    st = T3._ws(tmp_path)
    T3._put(st)
    agent, review, sec_seam = _signed_agent(st)

    first = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    assert first["signed_bit3"] is True, first["sign_issuance"]
    rows_before = len(T3._rows(st))
    assert rows_before == VR.SIGN_STREAK_NEED, T3._rows(st)
    review.prompts.clear()
    sec_seam.seen.clear()

    # 直接把 statements 那一行的第 3 位清成假（走真事务；不改台账 —— 负控要量的就是这一位）。
    # 等级按五元位现算（`normalize_raw`）：盘上的 `grade` 只是缓存，清位之后必须跟着现算值，
    # 否则写入期闸会以"自报等级与现算不符"拒收 —— 那是另一条判据，不是这条负控要量的东西。
    cleared = copy.deepcopy(T3._stmt_row(st))
    cleared["bits"]["reviewed"] = False
    cleared["bits"] = EB.normalize_raw(cleared["bits"],
                                       origin=str(cleared.get("origin") or "own_result"),
                                       kind=str(cleared.get("kind") or ""))
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", cleared)
    assert T3._stmt_row(st)["bits"]["reviewed"] is False, T3._stmt_row(st)["bits"]

    again = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)

    passes = again["review_passes"] or []
    assert again["reason"] != "already_signed", (
        "第 3 位已经是假，这一趟却仍然短接 ⇒ 短接量的不是那个位")
    assert review.asked() >= 1, "位清成假之后一次模型都没问 ⇒ 这一条命题再也审不了了"
    assert review.asked() == len(passes), (review.asked(), passes)
    assert len(T3._rows(st)) == rows_before + len(passes), (
        f"位清成假之后审了 {len(passes)} 转，台账却从 {rows_before} 变成"
        f" {len(T3._rows(st))} 行")
    assert again["checked"] is True, again
    # 这一趟审完又签上了（台账里前三次 clean 的票还在）⇒ 位回到真。
    assert T3._stmt_row(st)["bits"]["reviewed"] is True, T3._stmt_row(st)["bits"]


# ============================================================ r3：历史行为不变
def test_r3_an_unsigned_statement_still_reviews_three_times(tmp_path):
    """未签的命题照旧一次判满三转（3 行、3 次模型调用、发签）—— 短接不许做宽。"""
    st = T3._ws(tmp_path)
    T3._put(st)
    assert T3._stmt_row(st)["bits"]["reviewed"] is False, "夹具前提：这一行一次都没签过"
    agent, review, sec_seam = _signed_agent(st)

    got = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)

    assert review.asked() == VR.SIGN_STREAK_NEED, (
        f"未签的命题只问了 {review.asked()} 次模型 ⇒ 短接做宽了（历史行为变了）")
    assert len(got["review_passes"] or []) == VR.SIGN_STREAK_NEED, got["review_passes"]
    assert len(T3._rows(st)) == VR.SIGN_STREAK_NEED, f"台账应当 3 行，实得 {len(T3._rows(st))}"
    assert got["reason"] != "already_signed", got["reason"]
    assert got["signed_bit3"] is True, got["sign_issuance"]
    assert (got["review_passes"] or [])[-1]["terminal"] == "signed", got["review_passes"]
    assert T3._stmt_row(st)["bits"]["reviewed"] is True, T3._stmt_row(st)["bits"]


# ============================================================ r4：另一份证明不许借光

def _put_two_proofs(st):
    """一条命题两份证明：`#p1` 是行上的 `proof_text`，`#p2` 在 `proofs` 清单里。"""
    proof_2 = T3.PROOF + "\n3. 补上第三步。"
    row = {
        "stmt_id": T3.SID, "origin": "own_result", "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": T3.FULL,
        "statement_text": "弦长函数不是常值", "proof_text": T3.PROOF,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题，没有外部引文要比对",
        "created_at": T3.TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=T3.PROOF, kind="theorem"),
        "proofs": [{"proof_no": 2, "proof_text": proof_2}],
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    write_proof_manuscript(st.root, T3.SID, T3.PROOF, statement_full=T3.FULL)
    write_proof_manuscript(st.root, T3.SID, proof_2, statement_full=T3.FULL, proof_no=2)
    return proof_2


def test_r4_another_proof_of_the_same_statement_is_still_reviewed(tmp_path):
    """`#p1` 签过之后，`#p2` 不许短接（逐条表里 `#p2` 还是假）。

    这一条量的是"短接做宽"的第二种形态：按命题级汇总位（`bits.reviewed` 是
    "任一份成立即为真"）短接，会替 `#p2` 借 `#p1` 的光 —— 一份一次都没审过的证明
    被读成"已经签过"，那是比原缺陷更坏的一种假话（`evidencebits.reviewed_by_proof`
    存在的理由就是这一条）。
    """
    st = T3._ws(tmp_path)
    proof_2 = _put_two_proofs(st)
    agent, review, sec_seam = _signed_agent(st)

    first = agent.verify_proof(T3.SID, proof_no=1, proof_manuscript=T3.REL)
    assert first["signed_bit3"] is True, first["sign_issuance"]
    assert EB.reviewed_by_proof(T3._stmt_row(st)) == {1: True, 2: False}, (
        EB.reviewed_by_proof(T3._stmt_row(st)))
    review.prompts.clear()
    sec_seam.seen.clear()

    second = agent.verify_proof(T3.SID, proof_no=2, proof_manuscript=f"reports/f-proof-{T3.SID}-p2.md")

    assert second["reason"] != "already_signed", (
        "#p2 一次都没审过，这一趟却短接了 ⇒ 短接读的是命题级汇总位（借了 #p1 的光）")
    assert review.asked() == VR.SIGN_STREAK_NEED, (
        f"#p2 只问了 {review.asked()} 次模型 ⇒ 它没被真的审过")
    assert len(second["review_passes"] or []) == VR.SIGN_STREAK_NEED, second["review_passes"]
    assert second["proof_no"] == 2, second
    assert second["proof_sha256"] == VR.proof_sha(proof_2), second
    assert second["signed_bit3"] is True, second["sign_issuance"]
    assert EB.reviewed_by_proof(T3._stmt_row(st)) == {1: True, 2: True}, (
        EB.reviewed_by_proof(T3._stmt_row(st)))
    rows = T3._rows(st)
    assert len(rows) == 2 * VR.SIGN_STREAK_NEED, f"台账应当 6 行，实得 {len(rows)}"

    # 两份都签了之后，再问 #p2 才该短接。
    review.prompts.clear()
    third = agent.verify_proof(T3.SID, proof_no=2, proof_manuscript=f"reports/f-proof-{T3.SID}-p2.md")
    assert third["reason"] == "already_signed", third["reason"]
    assert third["review_passes"] == [], third["review_passes"]
    assert review.asked() == 0, review.asked()
