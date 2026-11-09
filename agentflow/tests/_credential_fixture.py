# -*- coding: utf-8 -*-
"""夹具：造一份可复算的 V 签（D268 批 2 的正控形状）。

三票同源（同一 `review_call`、`review_pass` 1..3）+ `vsigns.issue` 写
`out/vsigns/<正文 sha>.json`。批 2 起"块在/文件在"不再算签，所有"已签"夹具都必须
先过这一步，再（可选地）把块盖上去当视图。

只写 `root` 下的工作区（tmp）；不碰 `projects/`。
"""
from __future__ import annotations

from typing import Any

from agentflow import verifications as VR
from agentflow import vsigns as VS

AT = "2026-11-02T10:00:00+08:00"


def issue_credential(root: Any, *, proof_text: str, statement_id: str = "",
                     manuscript: str = "", call: str = "call-1",
                     at: str = AT, proof_no: int = 1) -> dict[str, Any]:
    """写三行台账并颁发一份签；返回 `vsigns.issue` 的读数。"""
    sid = str(statement_id or "").strip()
    ledger_sid = sid or "000000"
    rows = []
    for n in (1, 2, 3):
        rows.append(VR.record_verification(
            str(root), statement_id=ledger_sid, proof_text=proof_text,
            verdict={"verdict": "成立", "findings": []},
            secretary_judge={"axis": "clean", "checked": True,
                             "reason": "夹具：秘书判 clean"},
            flip=False, review_call=call, review_pass=n,
            manuscript=str(manuscript or ""), proof_no=proof_no))
    sha = VS._sign_sha(proof_text)
    passes = [{"verification_id": str(r["verification_id"]),
               "at": str(r.get("at") or at), "proof_sha256": sha,
               "review_call": call, "review_pass": n}
              for n, r in zip((1, 2, 3), rows)]
    got = VS.issue(
        str(root), artifact_sha=sha, streak=3, need=3,
        ledger=f"verifications/{ledger_sid}.jsonl#{rows[-1]['verification_id']}",
        statement_id=sid, proof_no=int(proof_no), passes=passes, at=at,
        by="secretary:B")
    assert got.get("written") is True or got.get("idempotent") is True, got
    return got
