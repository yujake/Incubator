"""引文校验：把"关系描述需完全引用参考文献"变成一道**可执行的质量门**。

为什么单独成模块：这是整个系统里唯一能自动发现"模型编造引文"的地方，
而幻觉引文是 LLM 做文献整理时最典型、也最危险的失败模式 —— 它**看起来完全合理**。
所以这里的判定必须严格、且必须**能被复核**（因此返回匹配到的页码窗口，而不是一个布尔值）。

判定原则（DESIGN.md §6.3）：
- 用**保守规范化后的子串匹配**，不用相似度。相似度会放过"改了几个词"的引文，
  而需求要求的是"完全引用"。
- **定位不到就不要声称校验过**。页码未知时不做"全文搜索后就算通过"的默认放宽 ——
  那等于把"页码错了"这个真实缺陷掩盖掉。这里的选择是：先按声明的页码查，
  再按 ±widen 页查，最后**只在显式允许时**查全文，并且把用的是哪种窗口如实回报。
- 无文本层（扫描版）时返回 `None` 而不是 `False`：
  "没校验"和"校验失败"是两件不同的事，前者需要 OCR，后者需要改引文。
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import PageRange
from .textutil import normalize_for_quote


@dataclass(frozen=True)
class QuoteCheck:
    """校验结果。`verified` 为三态：True 通过 / False 失败 / None 无法校验。"""

    verified: bool | None
    matched_page: int | None = None
    window: str = ""
    reason: str = ""
    tried: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "matched_page": self.matched_page,
            "window": self.window,
            "reason": self.reason,
            "tried": list(self.tried),
        }


def check_quote(
    doc,
    quote: str,
    page_range: PageRange | None,
    *,
    widen: int = 1,
    allow_fulltext_fallback: bool = False,
) -> QuoteCheck:
    """在文档中定位引文。

    参数
    ----
    doc : DocumentText
        必须提供 `pages: list[str]`（逐页文本）。
    page_range : PageRange | None
        关系声明的页码范围；`start/end` 为 None 时视为"未知页码"。
    widen : int
        声明窗口失败后向两侧扩展的页数。
    allow_fulltext_fallback : bool
        是否允许退化为全文搜索。**默认 False** —— 见模块 docstring 的说明。
    """
    pages = list(getattr(doc, "pages", []) or [])
    if not pages:
        return QuoteCheck(None, reason="no_text_layer", tried=())

    q = normalize_for_quote(quote)
    if not q:
        return QuoteCheck(None, reason="empty_quote", tried=())

    def scan(start: int, end: int, label: str) -> QuoteCheck | None:
        lo = max(1, start)
        hi = min(len(pages), end)
        if lo > hi:
            return None
        for p in range(lo, hi + 1):
            if q in normalize_for_quote(pages[p - 1]):
                return QuoteCheck(True, matched_page=p, window=label, reason="substring_match")
        return None

    tried: list[str] = []
    pr = page_range or PageRange(None, None, "")
    if pr.known:
        label = f"declared:{pr.start}-{pr.end}"
        tried.append(label)
        hit = scan(pr.start, pr.end, label)
        if hit:
            return hit
        if widen > 0:
            label_w = f"widened:{max(1, pr.start - widen)}-{min(len(pages), pr.end + widen)}"
            tried.append(label_w)
            hit = scan(pr.start - widen, pr.end + widen, label_w)
            if hit:
                # 找到了，但**不在声明的页码里** —— 这是页码错误，必须显式标记出来
                return QuoteCheck(
                    True,
                    matched_page=hit.matched_page,
                    window=hit.window,
                    reason="substring_match_outside_declared_range",
                    tried=tuple(tried),
                )

    if allow_fulltext_fallback:
        tried.append("fulltext")
        hit = scan(1, len(pages), "fulltext")
        if hit:
            return QuoteCheck(True, matched_page=hit.matched_page, window="fulltext",
                              reason="substring_match_fulltext", tried=tuple(tried))

    return QuoteCheck(
        False,
        reason="not_found" if pr.known else "not_found_page_unknown",
        tried=tuple(tried) or ("no_window",),
    )
