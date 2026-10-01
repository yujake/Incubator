"""角色 H 的动作 `review`（`goal-7f5116c1` M6：从 `agent_h.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, _UNSPECIFIED

class _Review:
    def review(
        self,
        doc_id: str,
        *,
        round_no: int | None = None,
        dependencies: Any = _UNSPECIFIED,
    ) -> dict:
        """审一份稿件：落发现 + 更新文档状态（转发 `review.review_document`）。

        返回 ``{"doc_id","checked","round","new_findings","duplicate_skipped",
        "reopened","error_count","warning_count","info_count","dep_check","status",
        "status_updated","status_error","verdict","reason"}``。

        `dependencies` 三态：不传 = 从库里读该稿件的依赖；显式 `None` = 没查
        （此时 `dep_check["checked"] is False`，verdict 是 `"unverified"` ——
        「依赖都闭合」这句话在没有查过的情况下不许说出口）。
        """
        params: dict[str, Any] = {"doc_id": str(doc_id)}
        if round_no is not None:
            params["round_no"] = int(round_no)
        if dependencies is not _UNSPECIFIED:
            params["dependencies"] = None if dependencies is None else [dict(d) for d in dependencies]
        data = self._writer("review.review_document", **params)
        self._emit(
            f"审校 doc:{doc_id} round={data.get('round')}：verdict={data.get('verdict')}，"
            f"新增 {len(data.get('new_findings') or [])} 条、跳过重复 "
            f"{data.get('duplicate_skipped')} 条，error={data.get('error_count')}，"
            f"status={data.get('status')}"
            + ("" if data.get("status_updated") else f"（状态未更新：{data.get('status_error')}）")
        )
        return data
