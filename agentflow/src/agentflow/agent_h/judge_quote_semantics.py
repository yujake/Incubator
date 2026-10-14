"""角色 H 的动作 `judge_quote_semantics`（业主 2026-10-14：「回验不应该是十分呆板的
逐字验证，而是保持语义相同即可」，落点是 **B 唤起 H**）。

## 这一件只判、不写

H 是只读角色，而它的落库代理被钉死在 `review_findings` / `documents.status` 上
（**不碰任何知识表**，见 `agent_h/__init__.py` 的"为什么 H 必须是只读的"）。
所以这一件**不写** `relations` / `statements`：它把判定与证据交回**唤起它的那一方**（B），
由 B 用它自己的写面回填 `quote_verified` / `quote_mode` / `quote_reason`。
"判"与"落"分居两处，正是这条链能被信任的前提（与"发现者不许同时是修正者"同一条纪律）。

## 两档与三态

- 逐字那一档**不在这里**：它归 `quoteverify.check_quote`（禁改区里那份不花钱的实现），
  由 B 先走；这一件只处理"逐字不中、但语义相同"那一档。
- 语义判定要模型缝（`self.llm`）：**没有缝（没有 key）⇒ 如实回"没查"**，
  既不是通过也不是不通过（`judge_not_wired`）。缝只在
  `run-agent --semantic-review` 时才接到 H 手上（默认确定性）——
  所以默认路径下这一件回的是"没查成"，而那句话本身就是如实读数。
- 判定词表与"判定 ⇒ 三栏"的映射都只有一处：`judges.quote_semantics_judge_for` /
  `judges.quote_fields_from_verdict`（本文件不抄第二份口径）。
"""
from __future__ import annotations

from ._support import Any, ReviewError, _UNSPECIFIED  # noqa: F401  - 与同目录其余动作同源

#: 「这条引文喂给语义判据」的四栏（调用方给；H 不自己去猜）：
#: `quote`（待核引文）· `span`（来源里那一段，逐字取来）· `statement`（它要支撑的断言，
#: 可空）· `where`（落点：文件/页码，给人看的）。
_MATERIAL_KEYS = ("quote", "span", "statement", "where")


class _JudgeQuoteSemantics:
    def judge_quote_semantics(self, *, quote: str = "", span: str = "",
                              statement: str = "", where: str = "",
                              relation_id: str = "", stmt_id: str = "") -> dict:
        """判一条引文与来源**是不是说同一件事**（只读；判完把结论交回调用方）。

        `relation_id` / `stmt_id` 是"这条判定属于哪一行"的记账栏：本件不读表
        （H 的工具面只读，但读表这件事该由唤起方连材料一起给 —— 免得 H 与 B
        对"哪一行"各读一份、读成两样）。返回值里原样带回，B 据此回填。
        """
        if not str(quote or "").strip() or not str(span or "").strip():
            return {"tri": "unreadable", "verdict": "unknown", "same_meaning": None,
                    "relation_id": str(relation_id or ""), "stmt_id": str(stmt_id or ""),
                    "reason": ("材料不全：`quote`（待核引文）与 `span`（来源里那一段）"
                               "都必须给 —— 少了任何一条，这一档无从判起（没查，不是通过）")}
        from .. import judges as JG

        seam = getattr(self, "llm", None)
        judge = JG.quote_semantics_judge_for(seam)
        got = judge({"quote": quote, "span": span, "statement": statement,
                     "where": where})
        verified, mode, reason = JG.quote_fields_from_verdict(got["verdict"], got["why"])
        self.tool_calls.append({"tool": "judge:quote.same_meaning",
                                "ok": bool(got.get("verdict") == "same_meaning"),
                                "error": "" if verified is not None else got["why"]})
        return {
            "tri": "computed" if verified is not None else "unreadable",
            "verdict": str(got["verdict"]),
            "same_meaning": verified,
            "quote_mode": mode,
            "quote_reason": reason,
            "judge": "H",
            "call": dict(got.get("call") or {}),
            "span": str(span),
            "where": str(where or ""),
            "relation_id": str(relation_id or ""),
            "stmt_id": str(stmt_id or ""),
            "reason": "" if verified is not None else str(got["why"]),
        }


__all__ = ["_JudgeQuoteSemantics"]
