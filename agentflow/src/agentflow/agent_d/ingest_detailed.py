"""角色 D 的动作 `ingest_detailed`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import Any, Mapping

class _IngestDetailed:
    def ingest_detailed(self, report: Any, *, c_contradictions: Mapping[str, Any] | None = None) -> dict:
        """``ingest`` 的详细返回形态：每个候选的处置都在这一个 dict 里（§3.1）。

        §3.1 要求"命中等价问题所以没新建"与"新建了"在返回值里体现。
        但 ``ingest`` 的既有契约（以及依赖它的既有测试）是"返回新建的
        question_id 列表" —— 把它改成 dict 会把所有"我只想知道新建了哪些"的调用方
        弄坏。所以保留 ``ingest`` 的窄返回，另给这个宽的：
        一次调用同时能看到 ``created`` / ``merged_by_equivalence`` /
        ``merged_by_content_key`` / ``skipped`` 与每个候选的 ``decisions``。
        """
        created = self.ingest(report, c_contradictions=c_contradictions)
        info = dict(getattr(self, "last_ingest", {}) or {})
        return {
            "created": list(created),
            "created_count": len(created),
            "merged_by_content_key": list(info.get("merged") or []),
            "merged_by_equivalence": list(info.get("equivalent_matched") or []),
            "skipped": list(info.get("skipped") or []),
            "decisions": list(info.get("decisions") or []),
            "contradictions": dict(info.get("contradictions") or {}),
            "weak_clues_noted": list(info.get("weak_clues_noted") or []),
        }
