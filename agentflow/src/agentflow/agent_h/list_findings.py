"""角色 H 的动作 `list_findings`：只读列举审校发现（`kind` 由本层现筛）。

`kind` 这一格归本文件筛：动作面（`specs/h.py` 的 `H.list_findings.params`）承诺了
`doc_id` / `level` / `status` / `kind` 四格，而底下的工具 `review.list_findings`
只收前三格（`additionalProperties=False`）。照动作面派活带 `kind` 时，工具层会拒成
`invalid_params` —— 动作面承诺的那一格，工具面做不到。所以这一层把 `kind` 接下来、
在返回的清单上现筛（工具面一个字都不动：它仍然是"一次纯列举"，没有"没查成"这一档）。
"""
from __future__ import annotations

from ._support import Any, ReviewError

class _ListFindings:
    def list_findings(self, **filters: Any) -> dict:
        """只读列举发现（走 H 的自由工具箱；`kind` 由本层按返回清单现筛）。"""
        kind = filters.pop("kind", None)
        res = self.tools.call("review.list_findings", **filters)
        self.tool_calls.append({"tool": "review.list_findings", "ok": res.ok, "error": res.error})
        if not res.ok:
            raise ReviewError(f"review.list_findings 调用失败：{res.error}")
        data = dict(res.data or {})
        if kind is not None:
            # `kind` 是受控词表里的那一格（`schema.FINDING_KINDS`）：这里只做等值筛，
            # 不认识的值给出空表 —— 一次纯列举没有"这个值判不了"的第三档。
            rows = [row for row in (data.get("findings") or ())
                    if str(row.get("kind")) == str(kind)]
            data = {**data, "count": len(rows), "findings": rows}
        return data
