"""角色 C 的动作 `handle`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来）。

## L-03（`draft/52` / `44 J-02`）：`handle` 是 C 的产出登记口

`capabilities.py` 把 `analysis_reports` 归给 `AgentC.handle`（写集 `WRITE_SETS["C"]` 逐字含
`analysis_reports`）⇒ "报告由 C 的动作产出"这件事的落点就是这里：`handle` 在分派完之后
（`ok=True` 时）收口一次 `persist()`，把报告的 `report_id` 带在返回值上。

三条边界（改这一处时必须同时守住）：

1. 每个分析动作产出即登记（业主 2026-10-12 裁定 CS-10 ②：「直接调分析器也落库」）——
   落点在 `AgentC._report`：`ok=True` 且 `kind` 在受控词表里时收口一次 `persist()`。
   `handle` 这里再收口一次也无害（`report_id` 已有就跳过），于是"谁产出了这份报告"
   在台账上仍是 `role=C` 的那一行；`pipeline` 照旧只从返回值里读 `report_id`。
   （改前那一版把登记只收口在 `handle`：`tests/test_agent_c.py:485` 走的是
   `hottest(...) + rep.persist()` 并断言 1 行、`tests/test_agent_c_service.py:656` 钉的是
   "直接调 `gaps` 不落报告表" —— 那两条判据随裁定一起改成新口径：分析器自己落一条，
   显式再 `persist()` 就是第二条。）
2. `ok=False` 不落盘：失败报告（概念解析不到、关键词未命中、关系表为空）不是"一份分析产物"，
   登记它会让 `analysis_reports` 里混进答非所问的行。
3. 落盘失败不许静默：`persist()` 抛什么就让它穿出去（conductor 会把这一步记成
   `failed` 并留下原话）—— 一条"看起来产出了报告、其实没登记"的路径比报错更坏。
"""
from __future__ import annotations

from ._support import ANALYZERS, AnalysisReport


class _Handle:
    def handle(self, request_text: str) -> AnalysisReport:
        """自然语言需求 → 分派到四个分析器（关键词分派，确定性、可测试）；并登记报告。

        为什么不用 LLM 做分派：分派错了会产出答非所问的报告（例如把
        "研究冷门概念"当成"统计热门"），而报告本身看起来完全正常 —— 这种错误
        最难被发现。关键词分派可以被穷举测试，也可以被人工一眼验证。

        `ok=True` 时这一层调一次 `persist()`（幂等：已有 `report_id` 就不再落），
        于是"谁产出了这份报告"在台账上是 `role=C` 的那一行 —— 这也是 `pipeline`
        不再自己直写报告表的原因（它只从这一步的返回值里读 `report_id`）。
        """
        report = self._dispatch_request(request_text)
        if bool(getattr(report, "ok", True)) and not getattr(report, "report_id", None):
            out = report.persist()
            report.report_id = str(out.get("report_id") or "") or None
            report.markdown_path = str(out.get("markdown_path") or "") or report.markdown_path
        return report

    def _dispatch_request(self, request_text: str) -> AnalysisReport:
        """按需求原文分派（原 `handle` 的分派体，逐字未改；由 :meth:`handle` 收口）。"""
        text = (request_text or "").strip()
        if not text:
            return self._report(
                "unknown",
                "",
                {},
                summary="空请求：无法分派。请说明是统计最热门、查询两概念间关系、研究冷门，还是完善关系图。",
                payload={"available": list(ANALYZERS)},
                ok_=False,
                error="空请求",
            )
        if any(k in text for k in self._PATH_HINTS):
            return self._handle_paths(text)
        if any(k in text for k in self._HOT_HINTS):
            return self.hottest(top_n=self._parse_int(text, 5, 1, 100), request=text)
        if any(k in text for k in self._COLD_HINTS):
            return self.cold(top_n=self._parse_int(text, 5, 1, 100), request=text)
        if any(k in text for k in self._GAP_HINTS):
            return self.gaps(limit=self._parse_int(text, 10, 1, 100), request=text)
        return self._report(
            "unknown",
            text,
            {},
            summary=(
                "无法分派这条需求（关键词未命中）。可用说法示例：'统计最热门的 5 个概念'、"
                "'查询 群 与 域 之间的关系'、'研究冷门概念'、'完善关系图/找结构洞'。"
            ),
            payload={"available": list(ANALYZERS), "request": text},
            ok_=False,
            error="关键词未命中",
        )
