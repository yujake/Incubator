# -*- coding: utf-8 -*-
"""判据（D / 并发 P0）：同一正文 sha 已有 issued 签 ⇒ 送审判定入口短路，不调模型。

现场（`temp/analysis/10-concurrency-budget.md` §3/§4）：同一份 `f-proof-000001.md`
（正文 sha `0ac4b14c…`）被两条送审路径各判一遍 —— 2 趟 V × 每趟连判 3 转 = 6 条
「成立」，签只有 1 个；第二趟 $0.030761 白花。

改前短接只认"稿上那块签"（`manuscript_sign_standing`），而正式颁发的证据是
`out/vsigns/<正文 sha>.json` —— 稿上的块没读到（旧盘没落块、或落块失败）时，同一份
正文会被整趟重新买一遍。这一条钉的就是那个洞：

1. 签文件在、稿上块读不到 ⇒ 二次送审短路：0 次模型调用、0 行台账、读数
   `already_signed` + `issued_sign` 指回签文件那一行；
2. 负控：正文 sha 变了（签文件不在）⇒ 照常判（不许把"改过稿"也短路）；
3. 反真空（旧盘）：签文件缺失 ⇒ 不短路，照常判（fail-open，不许当已签）；
4. 反真空（打桩）：把短路函数打成恒 `found=False` ⇒ 第 1 条必红。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import verifications as VR
from agentflow import vsigns as VS

import test_v_reviews_three_times_before_signing as T3
from test_a_signed_statement_is_not_reviewed_again import _signed_agent
from _proof_manuscript_fixture import write_proof_manuscript


def _sign_files(st) -> list[pathlib.Path]:
    folder = pathlib.Path(st.root) / "out" / "vsigns"
    return sorted(p for p in folder.glob("*.json") if p.name != "issued.json")


def _strip_the_sign_block(st) -> None:
    """把稿重写成同一份正文、但没有签块（模拟旧盘 / 落块失败那一档）。

    正文逐字不变 ⇒ `## 证明` 那一节的 sha 不变（签文件仍盖得住它）。
    """
    write_proof_manuscript(st.root, T3.SID, T3.PROOF, statement_full=T3.FULL)
    raw = (pathlib.Path(st.root) / T3.REL).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(raw, manuscript_path=T3.REL)
    assert block["found"] is False, ("夹具前提：稿上不该再有签块", block)


def _sign_once(tmp_path: pathlib.Path):
    st = T3._ws(tmp_path)
    T3._put(st)
    agent, review, sec_seam = _signed_agent(st)
    with T3._as_submitter():
        first = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)
    assert first["review_write"].get("manuscript_signed") is True, first["review_write"]
    files = _sign_files(st)
    assert len(files) == 1, ("夹具前提：正式颁发的签应当只有一份", files)
    return st, agent, review, sec_seam, files[0]


def test_a_signed_sha_is_not_judged_twice_even_without_the_manuscript_block(
        tmp_path: pathlib.Path) -> None:
    """签文件在、稿上块读不到 ⇒ 二次送审 0 次模型调用，读数 already_signed。"""
    st, agent, review, sec_seam, sign_file = _sign_once(tmp_path)
    sha = json.loads(sign_file.read_text(encoding="utf-8"))["artifact_sha"]
    _strip_the_sign_block(st)
    review.prompts.clear()
    sec_seam.seen.clear()
    rows_before = len(T3._rows(st))

    with T3._as_submitter():
        again = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)

    assert again["checked"] is True, again
    assert again["reason"] == "already_signed", again
    assert again["review_passes"] == [], again["review_passes"]
    assert again["proof_sha256"] == sha, again
    issued = dict(again.get("issued_sign") or {})
    assert issued.get("found") is True, issued
    assert issued.get("block_covers") is False, issued
    assert str(issued.get("sha")) == sha, issued
    # 指针与签文件同源：返回值那一格就是 `out/vsigns/<sha>.json` 里记的那一行。
    assert str(again["ledger"]) == str(issued.get("ledger")), again["ledger"]
    assert str(again["ledger"]).endswith("#" + str(issued.get("verification_id"))), again
    assert again["review_write"].get("manuscript_signed") is False, again["review_write"]
    assert again["review_write"].get("already_signed") is True, again["review_write"]

    assert review.asked() == 0, (
        f"同一份正文被买了第二遍：又问了 {review.asked()} 次模型", review.prompts)
    assert sec_seam.seen == [], sec_seam.seen
    assert len(T3._rows(st)) == rows_before, (
        "短接这一趟仍然落了台账行：", [r.get("verification_id") for r in T3._rows(st)])


def test_a_different_sha_is_still_judged(tmp_path: pathlib.Path) -> None:
    """负控：正文 sha 变了（签文件盖不住它）⇒ 照常判满三转。"""
    st, agent, review, sec_seam, _sign_file = _sign_once(tmp_path)
    changed = T3.PROOF + "\n3. 补上边界情形。"
    T3._put(st, proof_text=changed)
    write_proof_manuscript(st.root, T3.SID, changed, statement_full=T3.FULL)
    review.prompts.clear()
    sec_seam.seen.clear()
    rows_before = len(T3._rows(st))

    with T3._as_submitter():
        again = agent.verify_proof(T3.SID, proof_text=changed, proof_manuscript=T3.REL)

    assert again["reason"] != "already_signed", again
    assert review.asked() == VR.SIGN_STREAK_NEED, (
        f"改过稿之后只问了 {review.asked()} 次模型 ⇒ 短路做宽了")
    assert len(T3._rows(st)) == rows_before + VR.SIGN_STREAK_NEED, T3._rows(st)


def test_a_missing_sign_file_does_not_short_circuit(tmp_path: pathlib.Path) -> None:
    """反真空（旧盘）：签文件缺失 ⇒ fail-open 到照常判，不许把「没签文件」当已签。"""
    st, agent, review, sec_seam, sign_file = _sign_once(tmp_path)
    _strip_the_sign_block(st)
    sign_file.unlink()
    review.prompts.clear()
    sec_seam.seen.clear()

    with T3._as_submitter():
        again = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)

    assert again["reason"] != "already_signed", again
    assert review.asked() == VR.SIGN_STREAK_NEED, (
        f"签文件不在盘上却短路了（把「没查成」当成了「已签」）：asked={review.asked()}")


def test_anti_vacuum_stubbing_the_short_circuit_off_buys_it_again(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把短路打成恒 `found=False` ⇒ 第 1 条必红（又买一遍判定）。"""
    st, agent, review, sec_seam, _sign_file = _sign_once(tmp_path)
    _strip_the_sign_block(st)
    monkeypatch.setattr(VR, "issued_sign_short_circuit",
                        lambda *a, **kw: {"checked": True, "found": False})
    review.prompts.clear()
    sec_seam.seen.clear()

    with T3._as_submitter():
        again = agent.verify_proof(T3.SID, proof_text=T3.PROOF, proof_manuscript=T3.REL)

    assert again["reason"] != "already_signed", (
        "打桩之后仍然短路 —— 打桩没生效，反真空不成立")
    assert review.asked() == VR.SIGN_STREAK_NEED, (
        f"打桩之后应当又买一遍（{VR.SIGN_STREAK_NEED} 次），实得 {review.asked()}")
