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
        return {**data, "citation_coverage": self._citation_coverage(data, kind=kind)}

    def _citation_coverage(self, data: Mapping[str, Any], *, kind: str) -> dict:
        """这份稿子引了几条台账凭据 / 库里还有多少可引的（T2 第 25 趟抓出来的缺口）。

        ## 为什么单开一个方法（这条缺口值得记）

        `doc.build_document` 的工具层在 `meta.citation_coverage` 里给了这份读数
        （`tools/doc_tools.py`），但 `AgentG._call` 只把 `res.data` 交出来 ——
        meta 被丢在门里。M 手里那条路（`conductor.summon` → `G.build_document`）
        因此一个字都看不到：真机读数（T2 第 25 趟 `t2t`，`sessions/t2t.jsonl`）
        全文件搜 `citation_coverage` 0 命中，而这一趟恰好引了一条 `lit:` ——
        也就是说"引了文献"这件事与这条读数无关。
        与 `revise` 那条路同形（`check_citations` / `check_proofs` 各在这条路上
        补过一次），也与 d1 那次"两个入口分家"同形：改一处入口不算改。

        读数只报数、不拦：`check_citations` 在工具层已经判过"引用存不存在"。
        """
        from ..tools import doc_tools as DT

        try:
            return DT.citation_coverage(
                self.store.rows, list(data.get("claims") or []), citing_kind=str(kind or "")
            )
        except Exception as exc:  # noqa: BLE001 —— 读数算不出不许影响这笔写入
            return {"readable": False, "reason": f"{type(exc).__name__}: {exc}"}
