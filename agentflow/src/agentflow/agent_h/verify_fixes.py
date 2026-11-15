"""角色 H 的动作 `verify_fixes`。"""
from __future__ import annotations

from ._support import Any, _UNSPECIFIED

class _VerifyFixes:
    def verify_fixes(self, doc_id: str, *, round_no: int, dependencies: Any = _UNSPECIFIED,
                     close_as: str | None = None) -> dict:
        """复审：重跑检查判 `fixed` / 仍 `open`，并把仍 open 的逐条交回（转发 `review.verify_fixes`）。
        ## 收不收尾由你判断（2026-11-15 业主裁定，逐字：「撤掉这个上限，一切由智能体自行决定，不做读数」）
        轮数上限（`max_review_rounds`）已撤除：本方法不再带任何轮次读数，也不会因为"到了
        第几轮"把稿件判成 `unresolved_review`。要收尾就把 `close_as="unresolved_review"`
        显式传进来 —— 那是你的判断，不是计数器；不给 ⇒ 本趟只重审、逐条列出 `still_open`。
        `unresolved_review` 仍是 `documents.status` 的一档（`schema.DOC_STATUSES`），
        只是它的触发从"计数器到点"换成了"H 显式选择"。
        `dependencies` 与 :meth:`review` 同一套三态：不传 = 从库里读该稿件的依赖；显式 `None` = 没查（复审结论不覆盖依赖闭合这一维）；显
        式给行序列 = 按给的清单查。
        ## 为什么这个参数必须能传进来（此前缺口）
        下游 `review.verify_fixes` 一直收 `dependencies`，而本方法与`capabilities` 的声明都不收 —— 于是复审永远退回"从库里
        读该稿件的依赖"，而 `dependencies_for_doc` 只认 `used_by` 的 `doc:` 前缀。一条挂在别的锚点上的依赖（实测：
        `paper/main.tex#prop:step`）在复审眼里根本不存在，于是上一轮如实报出的 `dangling_dep`（`external_unavailable`）
        会被判成 `resolved ⇒ fixed` —— 那是把一个"已知拿不到的前提"静默宣告成"已经解决"。修好之后，复审能拿到同一份清单，判据与 `review` 逐字一
        致（实测 2026-09-29：P3 台账的 13 条未刊依赖）。
        """
        params: dict[str, Any] = {
            "doc_id": str(doc_id),
            "round_no": int(round_no),
        }
        if close_as is not None:
            # 只有 H 真的做了这个判断才传；不传 = 不收尾（转发层不替 H 决定）。
            params["close_as"] = str(close_as)
        if dependencies is not _UNSPECIFIED:
            params["dependencies"] = None if dependencies is None else [dict(d) for d in dependencies]
        data = self._writer("review.verify_fixes", **params)
        self._emit(
            f"复审 doc:{doc_id} round={round_no}：verdict={data.get('verdict')}，"
            f"resolved={len(data.get('resolved') or [])}，still_open={len(data.get('still_open') or [])}，"
            f"未解决(error)={len(data.get('unresolved_findings') or [])}"
        )
        return data
