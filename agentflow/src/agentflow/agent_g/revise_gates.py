# -*- coding: utf-8 -*-
"""`revise` 的闸（为了把 `revise` 拉回 200 行软基线而单独成文件）。

前三道是机械检查（`DT.normalize_claims`）、引用存在性（`DT.check_citations`）、proof
级断言的证据锚（`DT.check_proofs`）——搬出来只为体量，判断、顺序、异常类型与消息串
逐字照旧。后两道是业主 2026-11-14 裁定的两条缺口（本文件只放判据，调用点在 `revise`）：

- ① 给了 `claim_id` 而本稿没有 ⇒ 受控拒 `unknown_claim_id`（旧行为：静默追加，且
  `normalize_claims` 按位置把它改成另一个号 —— 请求 claim-99、盘上 claim-26）；
- ② `fixed_findings` 的 `target` 解析成本稿某条断言 ⇒ 这一笔必须同号替换了它、且内容
  真的有变化，否则拒 `finding_target_not_revised`（旧行为：claim-11 一个字没改也收）。

`tx_rows` 是事务内的读表口（`tx.rows`）：检查与随后写 `documents` / `review_findings`
看到同一份快照。这条约束没有放宽成"事务外先读一次"。
"""
from __future__ import annotations

import json
from collections.abc import Collection

from ._support import Any, DT, DocumentError, Mapping, Sequence


def checked_claims(
    tx_rows: Any,
    merged: Sequence[Mapping[str, Any]],
    *,
    doc_id: str,
    kind: str,
    workspace_root: Any,
) -> list[dict]:
    """修订后的整份断言表过三道闸，返回规范化后的断言（不合规就抛 `DocumentError`）。"""
    # 合规闸门：修订后的整份稿子要重过一遍机械检查。
    # 只查"新加的那几条"是不够的 —— 替换语义下，旧的错话可能被换掉，
    # 也可能被换坏，只有全量重查才说得清现在的稿子是否合规。
    try:
        normalized = DT.normalize_claims(merged)
    except ValueError as exc:
        # `normalize_claims` 是「纯函数校验」，抛裸 `ValueError` ⇒ 绕过工具层的包装
        # 穿出动作，被记成 `failed/执行中异常`，模型拿不到"哪一条断言、缺什么字段"。
        # 翻成 `DocumentError`（在 `_BUSINESS_ERROR_NAMES` 里）⇒ 落
        # `refused/invalid_params`，可自救。
        raise DocumentError(f"修订未通过机械检查：{exc}") from exc

    # 第二道闸：引用存在性。与 `doc.build_document` 复用同一个判据，
    # 理由见 `revise` 的 docstring —— 少了它，"修订"就是绕过引用检查的后门。
    # `citing_kind` 必须传（两阶段口径）：正式论文（`kind="paper"`）里不许直接引
    # 我方手稿，手稿内容要在正文里重建。
    cites = DT.check_citations(tx_rows, normalized, citing_kind=kind)
    if not cites["checked"]:
        # 理论上不可达（这里必然有 tx）。留着是为了让"没法查"这条状态
        # 有出口，而不是在某次重构里悄悄退化成"当作查过了"。
        raise DocumentError(
            f"修订 doc:{doc_id} 时无法核对引用是否存在：{cites['reason']} ⇒ 整笔不写库"
        )
    if cites["missing"]:
        bad = "；".join(
            f"[{m['claim_id']}] {m['citation']!r}：{m['why']}" for m in cites["missing"]
        )
        raise DocumentError(
            f"修订 doc:{doc_id} 被拒：{len(cites['missing'])} 条引用指向**不存在**的对象，"
            f"整笔不写库（documents/review_findings 都不动）：{bad}。"
            "引用一个不存在的代号，等于把外部结论当成自己的结论（FC-02）——"
            "`normalize_claims` 只看 citations 非空，查不出这一点"
        )

    # 第三道闸：proof 级断言的证据锚（`D-1`）。与 `doc.build_document`
    # 复用同一个 `DT.check_proofs`，理由与上面那条相同 —— 少一道，"修订"就是绕过
    # 它的后门。这不是推演：把 `revise` 的新断言换成一条只引 `lit:`、没有
    # `proof_location` 的 proof 断言，它能成功写库。
    proofs = DT.check_proofs(tx_rows, normalized, workspace_root=workspace_root)
    if not proofs["checked"]:
        raise DocumentError(
            f"修订 doc:{doc_id} 时无法核对 proof 级断言的证据：{proofs['reason']} ⇒ 整笔不写库"
        )
    if proofs["problems"]:
        bad = "；".join(f"[{p['claim_id']}] {p['detail']}" for p in proofs["problems"])
        raise DocumentError(
            f"修订 doc:{doc_id} 被拒：{len(proofs['problems'])} 条 proof 级断言的证据"
            f"不成立，整笔不写库（documents/review_findings 都不动）：{bad}。"
            "`evidence_kind='proof'` 享受最高一档的证据待遇，所以改写这条路"
            "也必须指向一条真的跑过检查器的实验行、并给出盘上真的存在的落点"
        )

    return normalized


# ---------------------------------------------------------------- ① 未知号


def ensure_known_claim_id(
    *, doc_id: str, claim: Mapping[str, Any], given: str, known_ids: Sequence[str],
) -> None:
    """`new_claims` 里给了 `claim_id`，它就必须是本稿现行号（否则受控拒）。

    旧行为（`projects/lp-ball`，2026-11-14）：传 `claim-99` 被当成"新增"，随后
    `normalize_claims` 按位置重编号（盘上第 26 条）⇒ 调用方以为"替换了 99"，
    盘上是"多了一条 26"，而回执报的又是请求号。三态折成一态，且没有一条读数
    会告诉人"号根本没对上"。

    一个例外：`compose_claim` 给出的内容派生别名（`claim-<sha1 前 8>`，
    `doc_tools._claim_id_of`）不是"替某条断言占号"，它是构造函数给对象起的稳定
    别名 —— `normalize_claims` 落库时本来就会按位置重编号。按追加处理；真正要
    堵的是"看起来像本稿号"（`claim-N`）的未知号。

    拒信逐个列出本稿现行号：下一次照着交，而不是再猜一个。
    """
    if given in known_ids:
        return
    derived = DT._claim_id_of(str(claim.get("text") or ""), claim.get("citations") or [])
    if given == derived:
        return
    listing = "、".join(str(x) for x in known_ids) or "（本稿一条断言都没有）"
    raise DocumentError(
        f"修订 doc:{doc_id} 被拒：new_claims 里给的 claim_id={given!r} 不在本稿现行号里"
        f"（拒因码 unknown_claim_id）。本稿现行号（{len(known_ids)} 条）：{listing}。"
        "要改哪一条就把那一条的号**原样**交回 —— 号从 "
        f"`documents/{doc_id}.md` 正文里的 `**claim-N**` 读（或读 "
        "`documents.claims[*].claim_id`）。要新增一条就别给 claim_id，脚本会分配；"
        "回执里的 `appended_claim_ids` 报的是归一化之后的号，不是请求号。"
    )


# ---------------------------------------------------------------- ③ 回执报归一化号


def claim_content_signature(claim: Mapping[str, Any]) -> str:
    """一条断言的"内容"指纹（不含 `claim_id`：代号由脚本按位置分配）。

    为什么按整条断言比、而不是只比 `text`：正文不是断言的全部 —— 补上 `disclaimer`、
    改 `numeric_evidence`、换 `proof_location` 都是真的改到了那一条（真机 G7 的
    8 条里就有只补四元组的）。但同号交回一份逐字相同的对象不算改 —— 那是
    "我把状态标成 fixed"的另一种写法。
    """
    body = {str(k): v for k, v in dict(claim).items() if str(k) != "claim_id"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)


def finding_target_claim_id(target: str, claim_ids: Collection[str]) -> str:
    """把 finding 的 `target` 解析成本稿现行号（解析不出 ⇒ 空串）。

    只认两种形态：`claim-N` 与 `claim-N:行号`。`section:2` / `dep:0004` /
    `claims[3]` 不是断言号，原样不认 —— 判断"这条发现是不是针对某条断言"时，
    不拿"看起来像"去猜。
    """
    text = str(target or "").strip()
    if not text:
        return ""
    if text in claim_ids:
        return text
    base = text.partition(":")[0].strip()
    return base if base != text and base in claim_ids else ""


def ensure_finding_target_revised(
    *,
    doc_id: str,
    finding_id: str,
    target: str,
    claim_id: str,
    replaced_ids: Collection[str],
    changed_ids: Collection[str],
) -> None:
    """标 fixed 的发现若指到本稿某条断言，这一笔必须真的同号改了它。

    旧行为（真机三次）：`target=claim-11` 的发现被标 fixed 三次，claim-11 一个字
    没改 —— 写口照收。`fixed_findings` 原来只写 finding 的 `status` /
    `resolution_note`，于是"我说修好了"与"真改了"在台账上同形。

    `claim_id` 是已经被解析、归一化之后的那一条（解析不出 ⇒ 空串 ⇒ 这条判据不管）。
    """
    if not claim_id:
        return
    if claim_id in replaced_ids and claim_id in changed_ids:
        return
    why = ("没有同号交回（不在这一笔的 replaced 里）" if claim_id not in replaced_ids
           else "同号交回了但断言内容一个字没改")
    raise DocumentError(
        f"修订 doc:{doc_id} 被拒：发现 {finding_id} 的 target={target!r} 指向断言 "
        f"{claim_id}，但这一笔 revise {why}（拒因码 finding_target_not_revised）。"
        f"要标 fixed 就先把 {claim_id} 同号交回 new_claims、并真的改掉它；"
        "只把 finding 的状态标成 fixed、断言原样不动，不算修好。"
    )
