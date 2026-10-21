"""角色 D 的动作 `run_round`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import Any, _as_report_dict

class _RunRound:
    def run_round(self, report: Any, *, submit: bool = True, limit: int | None = None) -> dict:
        """一轮完整流程（§4.1 + I1/I2）：
        ``ingest → 矛盾裁决 → (逐问题) trace → assess → 不足则 submit_gaps → poll → research``
        ``submit=False`` 表示"只评估不提问"（干跑模式），用于先看看会触发哪些判据而不动 A 的队列。``poll`` 放在最后：这样上一轮提交的请求（A、B 已
        经跑完）会在这一轮被拉回 researching，形成闭环。
        ## 为什么矛盾裁决排在缺口流程之前
        §1 I2 的顺序是设计的一部分：矛盾比缺口更强（它说明现有知识里有东西可能是错的，而不是"还不够"）。先裁决矛盾，才能保证它的 high 优先级请求在这一轮更早进入 A 
        的队列，而不是排在若干 medium 缺口之后。裁决结果写进 ``summary["adjudications"]``，让人看得到本轮裁了什么。
        ``submit=False``（干跑）时不裁决：裁决的落点就是"提交下一轮追问"，干跑模式下不做任何状态迁移是它存在的全部意义。
        """
        info = _as_report_dict(report)
        summary: dict[str, Any] = {
            "report_id": info.get("report_id"),
            "kind": info.get("kind"),
            "request": info.get("request"),
            "summary": info.get("summary"),
            "ingested": [],
            "adjudications": [],
            "traced": [],
            "assessed": [],
            "submitted": [],
            "researched": [],
            "confidence": {},
        }
        created = self.ingest(report)
        summary["ingested"] = created

        # ---- I2：先裁决"可裁决"的矛盾问题（含本次 ingest 刚建出来的新矛盾）
        summary["adjudications"] = self._adjudicate_ready_contradictions() if submit else []
        for adj in summary["adjudications"]:
            for rid in adj.get("request_ids") or []:
                summary["submitted"].append(rid)

        # ---- 本轮新提取的问题：溯源 + 评估 + 分支（足够→researching / 不足→提问）
        targets = created[: (limit if limit is not None else self.max_questions)]
        for qid in targets:
            ev = self.trace_question(qid)
            summary["traced"].append(
                {"question_id": qid, "claims": len(ev.get("claims") or []), "trace_mode": ev.get("trace_mode"),
                 "l3": len(ev.get("l3") or []), "path_chains": len(ev.get("path_chains") or [])}
            )
            verdict = self.assess(qid, ev)
            summary["confidence"][qid] = verdict["confidence"]
            if submit:
                decision = self.consider(qid)  # 足够 -> researching；不足 -> 提交请求
            else:
                # 干跑模式（submit=False）：只评估、不改状态、不提问
                decision = {
                    "question_id": qid,
                    "sufficient": verdict["sufficient"],
                    "criteria": [c["id"] for c in verdict["criteria"]],
                    "promoted": False,
                    "submitted": [],
                }
            summary["assessed"].append(
                {
                    "question_id": qid,
                    "sufficient": verdict["sufficient"],
                    "criteria": [c["id"] for c in verdict["criteria"]],
                    "priority": verdict["priority"],
                    "confidence": verdict["confidence"],
                    "hits": verdict["hits"]["distinct_hit_keywords"],
                    "degree": verdict["degree"],
                    "promoted": decision["promoted"],
                }
            )
            summary["submitted"].extend(decision["submitted"])

        # ---- [6] 复查等待集（上一轮的请求可能已经回来）
        summary["poll"] = self.poll()

        # ---- [5] 对"已就绪"的问题做初步研究（状态为 researching 的）
        #
        # 跳过 ``kind="contradiction"``：矛盾问题的推进权在 :meth:`adjudicate`
        # （它的收敛判据是裁决：resolved / persistent），而不是"写一段分析"。
        # 让 research() 也去动它，会把 needs_evidence → researching 的迁移
        # 绕过裁决做掉，于是"我还在等证据"和"我正在研究"就分不出来了。
        rows = self.store.rows("research_questions")
        for row in sorted(rows, key=lambda r: str(r.get("question_id"))):
            if row.get("status") != "researching":
                continue
            if str(row.get("kind") or "gap") == "contradiction":
                continue
            res = self.research(str(row.get("question_id")))
            summary["researched"].append(
                {
                    "question_id": res["question_id"],
                    "confidence": res["confidence"],
                    "criteria": res["criteria"],
                    "llm_used": res["llm_used"],
                    # 三态读数随本轮汇总一起出去（`R1-A1`）：`llm_used=False` 的那两种
                    # 情形（没接线 / 接了但失败）在这一格里分得开。
                    "llm_reading": dict(res.get("llm_reading") or {}),
                }
            )
            summary["confidence"][res["question_id"]] = res["confidence"]
        return summary
