# -*- coding: utf-8 -*-
"""收录回执那一格：把这一份正文的号与指纹写到 `statements` 顶层。

只做一件事：这一行真有一份正文时，把它的号（`proof_no`）与现算的正文 sha 写到
`statements` 顶层，并把 F 的稿号（`manuscript_id`）一并记上。

为什么回执与"第 2 位这次翻没翻"解耦：一条新建的「命题 + 证明」（`bits.proof` 一开始
就为真）走不到"翻位"那一支，不解耦就永远拿不到回执 —— 返回值说第 1 份，而盘上
`proof_no` / `proof_sha256` 一个字节都没写。号只从这一笔的落点读，不猜。
"""
from __future__ import annotations

from .. import proofregistry as _PR


def write_proof_receipt(
    row: dict,
    out: dict,
    *,
    body_now: str,
    proof_no: int,
    manuscript_id: str,
) -> None:
    """把这一行现在这一份证明的号 / 正文指纹 / 稿号写到顶层（就地改 `row` 与 `out`）。

    只在"这一行真有一份正文"时由调用方进来（e-num 那一档没有正文 ⇒ 顶层不写 ——
    没有证明就不许读出"第 1 份证明"）。
    """
    want_sha = _PR.proof_sha(body_now)
    mid = str(manuscript_id or row.get("manuscript_id") or "")
    # 这一格要写四处（比较一次、写 row 两格、写回执一格）：转换只做一次。
    no = int(proof_no)
    if (str(row.get("proof_sha256") or "") != want_sha
            or int(row.get("proof_no") or 0) != no
            or (bool(mid) and str(row.get("manuscript_id") or "") != mid)):
        row["proof_no"] = no
        row["proof_sha256"] = want_sha
        out["proof_receipt"] = {"proof_no": no,
                                "proof_sha256": want_sha}
        # ---- 行上记 `manuscript_id`（F 自己的稿号）
        #
        # 稿名与命题号不再绑定 ⇒ "这一行是哪一份稿"只能由这一格回答。
        # F 的稿号与命题号不同形（前者是 F 自己发的六位号），D 的携带单、
        # F 的交差读数、B 的签块闸都按它回找那份稿。
        if mid:
            row["manuscript_id"] = mid
            out["proof_receipt"]["manuscript_id"] = mid
