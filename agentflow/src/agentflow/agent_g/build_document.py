"""角色 G 的动作 `build_document`（`goal-7f5116c1` M6：从 `agent_g.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, Mapping, Path, Sequence

class _BuildDocument:
    def build_document(
        self,
        kind: str,
        title: str,
        *,
        claims: Sequence[Mapping[str, Any]],
        sections: Sequence[Mapping[str, Any]] | None = None,
        open_problems: Sequence[str] | None = None,
        out_path: str | Path | None = None,
    ) -> dict:
        """写一行 `documents` 并把 markdown 渲染到工作区内（转发 `doc.build_document`）。

        `out_path=None` 时用 `<workspace_root>/<docs_subdir>/<doc_id>.md`。
        给了 `out_path` 就必须落在工作区内：越界一律 `ValueError`，
        不许"写到外面再警告" —— 允许一次越界就等于承认沙箱边界可以被绕开。

        渲染是无条件的（不是"给了 out_path 才渲染"）：`markdown_path` 是
        FC-02 追溯链的一环，稿件必须有一个能被人打开的落点，否则
        "H 审的是哪个版本"无法回答。
        """
        data = self._call(
            "doc.build_document",
            kind=kind,
            title=title,
            claims=[dict(c) for c in claims],
            sections=[dict(s) for s in (sections or [])] or None,
            open_problems=[str(x) for x in (open_problems or [])] or None,
            out_path=str(out_path) if out_path is not None else None,
        )
        self._emit(f"写出稿件 doc:{data.get('doc_id')} → {data.get('markdown_path')}")
        return data
