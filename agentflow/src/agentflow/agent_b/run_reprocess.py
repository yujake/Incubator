"""角色 B 的动作 `run_reprocess`（`goal-7f5116c1` M6：从 `agent_b.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations


class _RunReprocess:
    def run_reprocess(self, max_requests: int | None = None) -> dict:
        """把 pending 的重抽取请求处理干净（有界，不会无限循环）。

        两道刹车，都很必要：

        - ``max_reprocess_per_run``：单次调用最多处理多少条（默认 10）；
        - ``seen``：同一条请求在一次调用里只处理一次。失败路径会释放租约让请求
          立刻可被再领，若没有这道刹车，"失败 → 释放 → 再领 → 再失败"就是一个
          不会停的循环 —— 而且是静默的：它不报错，只是把时间烧完。
        """
        cap = self.max_reprocess_per_run if max_requests is None else int(max_requests)
        summary: dict = {
            "handled": 0,
            "by_result": {},
            "rejected": [],
            "errors": [],
            "notes": [],
            "skipped_reason": None,
            "stopped": None,
        }
        seen: set[str] = set()
        n = 0
        while n < cap:
            out = self.reprocess_once()
            n += 1
            summary["rejected"].extend(out.get("rejected") or [])
            rid = str(out.get("reprocess_id") or "")
            if rid and rid in seen:
                summary["stopped"] = "same_request_repeated"
                break
            if rid:
                seen.add(rid)
            if out.get("error"):
                summary["errors"].append({"reprocess_id": rid, "error": out["error"]})
                continue
            if not out.get("handled"):
                summary["skipped_reason"] = out.get("skipped_reason")
                break
            summary["handled"] += 1
            word = str(out.get("result") or "")
            summary["by_result"][word] = summary["by_result"].get(word, 0) + 1
            summary["notes"].append(
                {
                    "reprocess_id": rid,
                    "result": word,
                    "touched_relation_ids": out.get("touched_relation_ids") or [],
                }
            )
        if summary["stopped"] is None and cap > 0 and n >= cap:
            summary["stopped"] = "max_requests_reached"
        return summary
