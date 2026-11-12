# -*- coding: utf-8 -*-
"""`revise` 的三道闸（为了把 `revise` 拉回 200 行软基线而单独成文件）。

机械检查（`DT.normalize_claims`）、引用存在性（`DT.check_citations`）、proof 级断言的
证据锚（`DT.check_proofs`）。搬出来只为体量：这三段的判断、顺序、异常类型与消息串逐字
照旧 —— 不是"两份实现要一致"，而是同一条路上只剩这一份实现。

`tx_rows` 是事务内的读表口（`tx.rows`）：三处检查与随后写 `documents` /
`review_findings` 看到同一份快照。这条约束没有放宽成"事务外先读一次"。
"""
from __future__ import annotations

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
