# -*- coding: utf-8 -*-
"""B 的「把严重的证明难点升级给 D 开展研究」这一格（业主 2026-10-22 晚裁定第四句）。

## 裁定原文（逐字）

> 「若缺陷严重，B 应通知 D 开展研究处理证明难点。」

三条落点，缺一条这一句就还是口号：

1. 边：`specs/b.py` 的 `edges` 里有 `D` —— B 本来就够不到 D（那之前 B 的出边是
   `C / H / V`），这一条是为这句话单独加的边，没有顺带放宽别的边；
2. 落点：D 的收件箱（`agent_loop.send_message`，标题前缀 `研究请求`）——
   与 L 的汇报同一条通道、同一套准入（`agent_loop.message_admission`）；
3. 判据：只有 `severity="research"` 才写。普通缺陷（`normal`）什么都不写 ——
   "打扰 D"本身是一条要被守住的边界（否则 D 的收件箱会退化成一张杂事清单，
   而"哪一件真的需要研究"就没人读得出来）。

## 谁判严重

B。这一格收的是 B 给的 `severity`，它替 B 判 —— "路线本身不成立"这种判断是从证明
内容来的，不由框架猜。`proofreport.SEVERITIES` 把它钉成两档受控值，
于是"没有 severity"与"severity 普通"分得开。
"""
from __future__ import annotations

from typing import Any

from .. import proofreport as PR


class _ProofResearch:
    """B 的升级入口（`AgentB` 的一个混入，见 `agent_b/core.py` 的类声明）。"""

    def escalate_proof_research(self, *, statement_id: str, failure_type: str,
                                step: Any = 0, detail: str = "",
                                severity: str = "normal", statement_label: str = "",
                                suggestion: str = "", proof_chars: Any = 0,
                                dependency_steps: Any = 0, session_root: Any = "",
                                sid: Any = "") -> dict[str, Any]:
        """按 `severity` 决定要不要把这条证明难点交给 D 开展研究。

        返回值与 :func:`proofreport.deliver` 同形：`state` 三档，只有 `escalated`
        表示"D 真的收到了"。`severity` 不是 `research` ⇒ `state="skipped"`、
        `reason="not_research"`、一行都不写（负控：普通缺陷不打扰 D）。

        `proof_chars` / `dependency_steps` 是 L 的汇报里那两格读数：B 转达时原样带上，
        D 不必回头去问"这条证明有多大"（缺省 0 = 这一趟没有读数，不是"证明是空的"）。
        """
        item = PR.payload(
            statement_id=statement_id, failure_type=failure_type, step=step,
            statement_label=statement_label, suggestion=suggestion,
            severity=severity, detail=detail, proof_chars=proof_chars,
            dependency_steps=dependency_steps)
        if not str(suggestion or "").strip():
            item["suggestion"] = PR.suggestion_for(str(failure_type or ""),
                                                   int(item.get("step") or 0))
        bad = PR.violations(item)
        if bad:
            return {"attempted": True, "state": "refused", "reason": "invalid_params",
                    "why": "；".join(bad), "msg_id": "", "to": "D",
                    "session_root": "", "sid": "", "payload": item}
        if str(item.get("severity") or "normal") != "research":
            return {"attempted": False, "state": "skipped", "reason": "not_research",
                    "why": (f"severity={item.get('severity')!r} ⇒ B 判断这一条补上就够，"
                            "不去打扰 D（D 只处理「路线本身不成立」那一档）"),
                    "msg_id": "", "to": "D", "session_root": "", "sid": "",
                    "payload": item}
        out = PR.deliver(
            sender="B", to="D", item=item, subject=PR.research_subject(item),
            body=PR.research_body(item), extra_key="research_request",
            session_root=session_root or self.cfg.get("session_root"),
            sid=sid or self.cfg.get("sid"),
            fallback_root=getattr(self.store, "root", ""))
        if str(out.get("state") or "") == "reported":
            # 同一件事的两个名字：这条通道叫"升级"，返回值里就叫 `escalated`
            # （`Conductor.escalate` 的既有口径；`reported` 是投递层的那个词）。
            out["state"] = "escalated"
        return out


__all__ = ["_ProofResearch"]
