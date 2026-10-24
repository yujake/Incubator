"""角色 G 的动作 `refresh_markdown`（`goal-7f5116c1` M6：从 `agent_g.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import DT, DocumentError

class _RefreshMarkdown:
    def refresh_markdown(self, doc_id: str) -> str | None:
        """把稿件的 markdown 文件按库里当前的数据重画一遍（不改任何数据行）。

        为什么需要它：依赖是稿件写完之后才登记的（`used_by="doc:0001#claim-1"`
        必须等 doc_id 存在），而渲染层要把依赖表画出来。没有这一步，
        盘上的 markdown 会永远显示"0 条依赖"——一份与库不一致的稿件。
        """
        doc = next(
            (r for r in self.store.rows("documents") if str(r.get("doc_id")) == str(doc_id)), None
        )
        if doc is None:
            raise DocumentError(f"稿件 {doc_id} 不存在")
        rel = doc.get("markdown_path")
        if not rel:
            return None
        target = self._resolve_inside(rel)
        deps = DT.dependencies_for_doc(self.store.rows("dependencies"), str(doc_id))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DT.render_markdown(doc, dependencies=deps), encoding="utf-8")
        # `D-44`：重画就是换了一份中间产物 ⇒ 把它的新 sha 记下来（否则读侧会把每一次
        # 正常的重画都报成"内容已变"）。这一步只追加一条 info 事件，不改任何数据行
        # —— 事务开在 `DT.note_markdown_artifact` 内部，本函数一个字都不写表。
        DT.note_markdown_artifact(self.store, doc_id, rel, target)
        self._emit(f"重渲染 doc:{doc_id} → {rel}")
        return str(target)
