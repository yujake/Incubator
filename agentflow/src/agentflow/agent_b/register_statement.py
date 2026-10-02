"""角色 B 的动作 `register_statement`（`draft/37` §46）：把一条命题登记进命题台账。

## 为什么需要这个动作

§44.4 的真机读数把"审阅并 polish 一篇外部论文"这条链的堵点定在动作表上：
主控只能 `conductor.summon` 动作，而"把论文里的定理登记成 `statements` 行"原先只有
工具（`table.create`，A–D 都能调）—— `agent_b/` 里 `statements` 一个字都没有，
所以即使 A 把文集登记好了（§46 的另一个动作），命题台账仍然建不起来，
G 就没有可引的 `lit:`/命题依据，H 也没有可审的对象。

B 的边界里本来就写着"命题台账三件套缺一不可"（完整假设的正文 / 逐字证明摘录 / 出处），
这个动作就是那句话的执行面。

## 三个"必填"与它们各自防的是什么

1. `statement_full`（含完整假设的命题正文）：省掉假设的命题会被下游当成无条件成立
   —— 那是 FC-23 在命题级的同一种病；
2. `proof_text`（逐字摘录）：`quote_verified` 的比对对象就是它，没有它"引文回验"无从做起；
3. `source_lit_id`（`origin="external_lit"` 时）：出处必须真的存在 —— 本动作在写库前
 核一次 `literature` 表，引用一个不存在的 `lit_id` 直接拒（`kind="unknown_lit_id"`），
   与 `doc.build_document` 的 `check_citations` 同一条纪律：坏引用不许进库。

`quote_verified` 是三态：`True` 逐字通过 / `False` 比对不一致 / `None` 还没查。
只要不是 `True` 就必须给 `quote_reason`（包括"还没查"），这条由 `Statement.validate()`
与这里的预检双保险 —— 预检存在的理由是把 `kind` 说清楚（调用方要能分辨"参数不对"
与"还没查"）。
"""
from __future__ import annotations

from ._support import S

class _RegisterStatement:
    def register_statement(
        self,
        *,
        statement_full: str,
        source_lit_id: str = "",
        proof_text: str = "",
        kind: str = "theorem",
        label: str = "",
        statement_text: str = "",
        origin: str = "external_lit",
        page_range: dict | None = None,
        evidence_kind: str = "cross_check",
        quote_verified: bool | None = None,
        quote_reason: str = "",
        derived_from: list | None = None,
        doc_id: str = "",
        line_range: dict | None = None,
    ) -> dict:
        """登记一条命题，返回 `{"ok": True, "stmt_id": ..., "row": {...}}`；不合规就零写入。"""
        full = str(statement_full or "").strip()
        if not full:
            return {"ok": False, "kind": "bad_statement",
                    "error": "statement_full 不能为空 —— 只有短版（statement_text）不算数："
                             "省掉假设的命题会被下游当成无条件成立"}
        origin = str(origin or "external_lit")
        if origin not in S.STATEMENT_ORIGINS:
            return {"ok": False, "kind": "bad_origin",
                    "error": f"origin 必须是 {S.STATEMENT_ORIGINS} 之一，收到 {origin!r}"}
        evidence_kind = str(evidence_kind or "heuristic")
        if evidence_kind not in S.EVIDENCE_KINDS:
            return {"ok": False, "kind": "bad_evidence_kind",
                    "error": f"evidence_kind 必须是 {S.EVIDENCE_KINDS} 之一，收到 {evidence_kind!r}"
                             "（它是证据**强度**，不是来源；来源走 source_lit_id）"}
        lit_id = str(source_lit_id or "").strip()
        if origin == "external_lit" and not lit_id:
            return {"ok": False, "kind": "missing_source",
                    "error": "origin='external_lit' 时必须给 source_lit_id —— "
                             "从文献摘的命题必须有出处（没有出处的摘录就是二手结论）"}
        if quote_verified is not True and not str(quote_reason or "").strip():
            return {"ok": False, "kind": "missing_quote_reason",
                    "error": "quote_verified 不是 True 时必须给 quote_reason —— "
                             "三态纪律：没通过要说为什么没通过，**还没查**也要说出来（不许留白）"}

        with self.store.tx("literature", "statements", actor=self.actor,
                           note="register_statement") as tx:
            if lit_id and tx.find("literature", lit_id=lit_id) is None:
                # 坏引用不许进库（与 `doc.build_document` 的 check_citations 同一条纪律）
                return {"ok": False, "kind": "unknown_lit_id", "source_lit_id": lit_id,
                        "error": f"literature 表里没有 lit_id={lit_id!r} ⇒ 这条命题的出处不存在，"
                                 "整笔不写库"}

            stmt_id = tx.alloc_id("stmt")
            row = S.Statement(
                stmt_id=stmt_id,
                origin=origin,
                kind=str(kind or "theorem"),
                label=str(label or ""),
                statement_text=str(statement_text or ""),
                statement_full=full,
                proof_text=str(proof_text or ""),
                source_lit_id=lit_id or None,
                page_range=S.PageRange.from_dict(page_range),
                quote_verified=quote_verified,
                quote_reason=str(quote_reason or ""),
                evidence_kind=evidence_kind,
                status="active",
                derived_from=S.sorted_unique(list(derived_from or [])),
                doc_id=str(doc_id or "") or None,
                line_range=S.PageRange.from_dict(line_range),
                created_at=S.now_iso(),
                created_by=self.actor,
            )
            row.validate()
            data = row.to_dict()
            tx.upsert("statements", data, note="register_statement")
            return {"ok": True, "stmt_id": stmt_id, "source_lit_id": lit_id or None,
                    "quote_verified": quote_verified, "origin": origin,
                    "evidence_kind": evidence_kind, "row": data,
                    "note": ("登记 ≠ 核对：quote_verified 是三态（True/False/None），"
                             "它不是 True 时下游必须按 `quote_reason` 读，不许当成通过。")}
