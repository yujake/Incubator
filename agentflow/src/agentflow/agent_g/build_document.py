"""角色 G 的动作 `build_document`：写一行 `documents` 并渲染 markdown。"""
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

        ## 写之前先过「难以自证」那一关（业主 2026-11-13 裁定）

        `hard_to_prove.settle_claims` 是唯一实现（`revise` 那条路调的是同一个函数）：

        - 引到了「难以自证」命题的辅助断言 ⇒ 改写成保守形态（不写成已证定理）；
        - 承重断言 ⇒ 摘出正文（原因进开放问题区）、并发一条 message 给召唤者。

        读数挂在返回值的 `hard_to_prove` 那一格；承重被摘掉时**上报的成没成**也在里面
        （`report` 子格），"没报成"不许被读成"报过了"。上报在写库之前发生：一份稿若
        被摘得一条不剩（承重的那条就是它的全部），写库会以"claims 不能为空"拒掉，
        而"这条承重、需仔细研究"不许跟着那一笔一起失败。
        """
        from .hard_to_prove import report_held_back, settle_claims

        settled = settle_claims(self.store.rows, [dict(c) for c in claims])
        problems = [str(x) for x in (open_problems or [])]
        problems.extend(settled["open_problems"])
        # 上报放在写库之前：承重条目被摘光时（一份稿只剩它一条）`doc.build_document`
        # 会以"claims 不能为空"拒掉这一笔 —— 而"这条承重、需仔细研究"这件事
        # 与"这一笔写不写得进去"是两件事，上报不许跟着写库一起失败。
        report = report_held_back(self.store, settled, kind=kind)
        data = self._call(
            "doc.build_document",
            kind=kind,
            title=title,
            claims=[dict(c) for c in settled["claims"]],
            sections=[dict(s) for s in (sections or [])] or None,
            open_problems=problems or None,
            out_path=str(out_path) if out_path is not None else None,
        )
        readings = dict(settled["readings"])
        readings["report"] = report
        for row in readings["rows"]:
            self._emit(
                f"「难以自证」{row['claim_id']}：引 "
                + "、".join(f"stmt:{x}" for x in row["statement_ids"])
                + f" ⇒ {'不进正文（承重）' if row['action'] == 'held_back' else '保守形态'}"
            )
        if report.get("sent"):
            self._emit(f"已把承重的那几条上报召唤者 {report.get('to')}（msg_id={report.get('msg_id')}）")
        self._emit(f"写出稿件 doc:{data.get('doc_id')} → {data.get('markdown_path')}")
        return {
            **data,
            "citation_coverage": self._citation_coverage(data, kind=kind),
            "hard_to_prove": readings,
        }

    def _citation_coverage(self, data: Mapping[str, Any], *, kind: str) -> dict:
        """这份稿子引了几条台账凭据 / 库里还有多少可引的。

        为什么单开一个方法：`doc.build_document` 的工具层在 `meta.citation_coverage` 里
        给了这份读数（`tools/doc_tools.py`），但 `AgentG._call` 只把 `res.data` 交出来
        —— meta 被丢在门里。M 手里那条路（`conductor.summon` → `G.build_document`）
        因此一个字都看不到：真机读数里全文件搜 `citation_coverage` 0 命中，而那一趟
        恰好引了一条 `lit:`。与 `revise` 那条路同形（`check_citations` / `check_proofs`
        各在这条路上补过一次）：改一处入口不算改。

        读数只报数、不拦：`check_citations` 在工具层已经判过"引用存不存在"。
        """
        from ..tools import doc_tools as DT

        try:
            return DT.citation_coverage(
                self.store.rows, list(data.get("claims") or []), citing_kind=str(kind or ""),
                # 与工具层同一个接法：判"真有全文"要看盘上 `library/`。
                library_root=(self.workspace_root / "library"),
            )
        except Exception as exc:  # noqa: BLE001 —— 读数算不出不许影响这笔写入
            return {"readable": False, "reason": f"{type(exc).__name__}: {exc}"}
