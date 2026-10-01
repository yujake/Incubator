"""角色 H 的动作 `verify_fixes`（`goal-7f5116c1` M6：从 `agent_h.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, _UNSPECIFIED

class _VerifyFixes:
    def verify_fixes(self, doc_id: str, *, round_no: int, dependencies: Any = _UNSPECIFIED) -> dict:
        """复审：重跑检查判 `fixed` / 仍 `open`（转发 `review.verify_fixes`）。

        `error` 级发现一直不修、且已到 `max_review_rounds` ⇒ 文档置
        `unresolved_review`，并且返回值里 `unresolved_findings` 明确列出
        未解决的发现（不许隐藏）。

        `dependencies` 与 :meth:`review` 同一套三态：不传 = 从库里读该稿件的依赖；
        显式 `None` = 没查（复审结论不覆盖依赖闭合这一维）；显式给行序列 = 按给的清单查。

        ## 为什么这个参数必须能传进来（此前缺口）

        下游 `review.verify_fixes` 一直收 `dependencies`，而本方法与
        `capabilities` 的声明都不收 —— 于是复审永远退回"从库里读该稿件的依赖"，
        而 `dependencies_for_doc` 只认 `used_by` 的 `doc:` 前缀。一条挂在
        别的锚点上的依赖（实测：`paper/main.tex#prop:step`）在复审眼里根本不存在，
        于是上一轮如实报出的 `dangling_dep`（`external_unavailable`）
        会被判成 `resolved ⇒ fixed` —— 那是把一个"已知拿不到的前提"
        静默宣告成"已经解决"。修好之后，复审能拿到同一份清单，
        判据与 `review` 逐字一致（实测 2026-09-29：P3 台账的 13 条未刊依赖）。
        """
        params: dict[str, Any] = {
            "doc_id": str(doc_id),
            "round_no": int(round_no),
            "max_review_rounds": self.max_review_rounds,
        }
        if dependencies is not _UNSPECIFIED:
            params["dependencies"] = None if dependencies is None else [dict(d) for d in dependencies]
        data = self._writer("review.verify_fixes", **params)
        self._emit(
            f"复审 doc:{doc_id} round={round_no}：verdict={data.get('verdict')}，"
            f"resolved={len(data.get('resolved') or [])}，still_open={len(data.get('still_open') or [])}，"
            f"未解决(error)={len(data.get('unresolved_findings') or [])}"
        )
        return data
