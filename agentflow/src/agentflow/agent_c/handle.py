"""角色 C 的动作 `handle`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`tests/test_agent_split_is_verbatim.py`）。
"""
from __future__ import annotations

from ._support import ANALYZERS, AnalysisReport

class _Handle:
    def handle(self, request_text: str) -> AnalysisReport:
        """自然语言需求 → 分派到四个分析器（关键词分派，确定性、可测试）。

        为什么不用 LLM 做分派：分派错了会产出答非所问的报告（例如把
        "研究冷门概念"当成"统计热门"），而报告本身看起来完全正常 —— 这种错误
        最难被发现。关键词分派可以被穷举测试，也可以被人工一眼验证。
        """
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
