"""角色 D 的动作 `trace_l3`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import Sequence

class _TraceL3:
    def trace_l3(self, evidence: dict, lit_ids: Sequence[str] | None = None) -> dict:
        """按需 L3：下钻到文献（元数据 + 本地文件 + 正文是否可得）。

        刻意只取"事实"（文件是否存在、是否 processed），不在这里做 OCR 或
        正文抽取：那是 B/K 的职责，D 下钻正文的目的是"核对引文语境"，
        必须由专门的工具返回带页码的片段。工具缺失时如实写 ``found=False``,
        而不是假装读过 —— "没做"和"做了但没结果"是两件事。
        """
        want = list(lit_ids or [])
        if not want:
            want = [str(c.get("lit_id")) for c in evidence.get("claims") or [] if c.get("lit_id")]
        want = sorted(set(want))[: self.max_l3_lits]
        out: list[dict] = []
        for lid in want:
            data = self._trace_one("trace.literature", lit_id=lid)
            source = "external"
            if data is None:
                data = self._local_literature(lid)
                source = "fallback"
            if not data:
                data = {"found": False, "lit_id": lid}
            entry = dict(data)
            entry["lit_id"] = lid
            entry.setdefault("source", source)
            out.append(entry)
            evidence.setdefault("traces", []).append(
                {"level": "L3", "tool": "trace.literature", "lit_id": lid, "found": bool(data.get("found"))}
            )
        evidence["l3"] = out
        return evidence
