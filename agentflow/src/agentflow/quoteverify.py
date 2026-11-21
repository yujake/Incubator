"""引文校验：把"关系描述需完全引用参考文献"变成一道可执行的质量门。

为什么单独成模块：这是整个系统里唯一能自动发现"模型编造引文"的地方，
而幻觉引文是 LLM 做文献整理时最典型、也最危险的失败模式 —— 它看起来完全合理。
所以这里的判定必须严格、且必须能被复核（因此返回匹配到的页码窗口，而不是一个布尔值）。

判定原则：
- 用保守规范化后的子串匹配，不用相似度。相似度会放过"改了几个词"的引文，
  而需求要求的是"完全引用"。
- 那份"保守规范化"只有一处实现：`textutil.quote_match_text`（写侧的
  `llm._locate_verbatim` 与这里的 `check_quote` 共用同一个投影）。它消化的是
  版式噪声 —— 断行、断词连字符、连字（ﬁ/ﬂ）、控制字符、括号内侧空白；它不删
  标点、不做词干化、不容忍词序或数字差异。所以"同一段文字换了个排版"会命中，
  "同一句话换了几个词"照样不命中（正控见
  `tests/test_quote_projection_feeds_the_gate.py`）。为什么必须共用：2026-11-21
  真机 lp-ball-15 里 32 条被剔除的引文有 29 条是真引文，而写侧用 NFKC、这一侧
  用 NFC，两边各差一点，于是同一句话在一边过、在另一边不过。
- 定位不到就不要声称校验过。页码未知时不做"全文搜索后就算通过"的默认放宽 ——
  那等于把"页码错了"这个真实缺陷掩盖掉。这里的选择是：先按声明的页码查，
  再按 ±widen 页查，最后只在显式允许时查全文，并且把用的是哪种窗口如实回报。
- 无文本层（扫描版）时返回 `None` 而不是 `False`：
  "没校验"和"校验失败"是两件不同的事，前者需要 OCR，后者需要改引文。

## 边界：本模块只判「逐字不在」，不判「被改写/拼接」

`reason` 的取值面刻意只有匹配成功那三档与"没找到 / 没法判"那几档 ——
没有一档叫"找到了但不一样"。于是：

- 把一条真引文改一个词（`the` → `a`）与整句编造，在本模块里给出逐字相同的判决
  （`verified=False` / `reason="not_found"`）；
- 想区分这两者，需要一档近似匹配（例如 token 覆盖率高于某个阈值），
  而那个阈值今天没有标定方案 ⇒ 本模块不实现它。

为什么不做那半件事（而不是"顺手加上"）：近似匹配会把一次编造软化成一档更轻的
指控（"改写"），而两者的处置方向相反（改写 ⇒ 去改引文；编造 ⇒ 去查幻觉）。
证据链上"往轻判"是最危险的方向。所以这里的取舍是如实划边界：
"逐字不在"是这里能给的唯一失败判决，读者不要把它读成"这篇文献里一定有/没有这句话"
以外的任何结论。

相应地，`schema.FINDING_KINDS` 里刻意没有"引文与原文不符"这一档发现类型：
它没有任何生产路径能产出 —— 词表不许承诺这里办不到的事。
"""

from __future__ import annotations

from collections.abc import Mapping

import logging
from dataclasses import dataclass

from .schema import PageRange
from .textutil import quote_match_text

logger = logging.getLogger(__name__)


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


def _pages_unreadable(doc, start: int | None, end: int | None) -> bool | None:
    """`[start, end]`（1-based 闭区间，已收窄）里有没有"抽取失败"的页。

    三态返回值：`True` = 有不可读的页；`False` = 没有（或这份文档没有逐页信息）；
    `None` = 诊断取不到（`page_unreadable` / `failed_pages` 抛了异常）。

    ## 窗口收窄只有一份实现

    收窄逻辑不许有第二份实现，也不许留一个与 `DocumentText.page_unreadable`
    （`extract.py`）并行的闭包：两份实现没有任何断言把它们钉在一起，越界 / None /
    反向区间上迟早会分叉。所以这里直接问文档对象。

    历史替身（只有 `failed_pages`、没有 `page_unreadable`）走保守分支：
    只要能读出任何一页失败，就按"不可读"处理。这一支不看 `[start, end]`
    —— 它不是"窗口仍在起作用、只是没收窄到声明窗口"，而是任何一页失败都算。
    两条理由：收窄逻辑不许有第二份实现；而且这个方向更保守
    （宁可判"无法判定"，也不判"不存在"）。

    ## 诊断取不到时不许折成"没有失败页"

    在 `except Exception` 里 `return ()` 会把"`failed_pages()` 抛异常"折成
    "文档真的可读、这句话确实不在"（`verified=False / not_found`）—— 逐字同形，
    而那是把真引文记成幻觉的最贵方向。这一支返回 `None`，调用方据此判"无法判定"
    并留一条 warning。
    """
    fn = getattr(doc, "page_unreadable", None)
    if callable(fn):
        try:
            return bool(fn(start, end))
        except Exception:  # noqa: BLE001 - 诊断取不到要说出来，不该让校验崩
            return None
    fp = getattr(doc, "failed_pages", None)
    if not callable(fp):
        # 既没有 `page_unreadable` 也没有 `failed_pages`：这是"没有逐页信息"
        # （历史替身一律当可读），不是"取不到诊断"。
        return False
    try:
        failed = tuple(int(x) for x in fp())
    except Exception:  # noqa: BLE001 - 同上：抛异常是"取不到"，不是"没有"
        return None
    return bool(failed)


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
        是否允许退化为全文搜索。默认 False —— 见模块 docstring 的说明。

    三态与 `reason` 的边界：

    * `True`  + `substring_match` / `substring_match_outside_declared_range` /
      `substring_match_fulltext` —— 逐字命中（后两档把"窗口不对"如实标出来）；
    * `False` + `not_found` / `not_found_page_unknown` —— 逐字没找到。
      这一档不区分"引文被改写"与"整句编造"：本函数没有近似匹配那一档，
      所以两者在这里同形。要判"被改写"必须先有阈值标定方案 —— 那是新能力，
      不是本函数的补丁（见模块 docstring 的"边界"一节）；
    * `None` + `no_text_layer` / `empty_quote` / `empty_page_range` /
      `page_unreadable` / `page_status_unknown` —— 没法判（"没校验"不是"校验失败"）。
      `empty_page_range` 是"声明的窗口是空的（`start > end`）"：
      空区间里不可能有页 ⇒ "在这段里没找到"没有信息量，不许据此判 `not_found`。
    """
    pages = list(getattr(doc, "pages", []) or [])
    if not pages:
        return QuoteCheck(None, reason="no_text_layer", tried=())

    q = quote_match_text(quote)
    if not q:
        return QuoteCheck(None, reason="empty_quote", tried=())

    # 每页的投影只算一次：声明窗口 / ±widen / 全文三趟扫的是同一批页，
    # 而 `quote_match_text` 是纯函数、`pages` 是一份浅拷贝里的不可变字符串
    # ⇒ 三趟共用一个按页号缓存的字典（原来的实现每趟都把同一页重新投影一遍）。
    norm_pages: dict[int, str] = {}

    def scan(start: int, end: int, label: str) -> QuoteCheck | None:
        lo = max(1, start)
        hi = min(len(pages), end)
        if lo > hi:
            return None
        for p in range(lo, hi + 1):
            page = norm_pages.get(p)
            if page is None:
                page = quote_match_text(pages[p - 1])
                norm_pages[p] = page
            if q in page:
                return QuoteCheck(True, matched_page=p, window=label, reason="substring_match")
        return None

    tried: list[str] = []
    pr = page_range or PageRange(None, None, "")
    # ---- 空窗口（`start > end`）判"没法判"。
    #
    # 为什么这不是"没找到"：声明的是一个空区间 —— 它里面不可能有任何一页，
    # 于是"在这段里没找到"这句话没有信息量（分母是 0）。若让 `scan` 直接返回
    # `None`（`lo > hi`），再靠 `widen` 把窗口撑开去数页外命中，会得出
    # `substring_match_outside_declared_range`（"页码错了"）—— 那是拿一个编码错误
    # 去指控引文/页码错了（`True` 会被下游读成"引文可靠"）。
    #
    # 守卫必须带 `pr.known`：页码未知（`start=end=None`）走的是另一档
    # （`not_found_page_unknown`）—— 没有这个守卫会把它一起吃掉。
    # 调用方可能把台账里的 dict 直接传进来（`page_range` 是
    # `{"start":…,"end":…}`）：直接 `pr.known` ⇒ AttributeError，所以这里改成可读
    # 拒信（类型契约是 `schema.PageRange`，静默接受 dict 会让 `known` 的语义在半路丢）。
    if isinstance(pr, Mapping):
        raise ValueError(
            "check_quote 的 page_range 必须是 `schema.PageRange`（收到 dict）—— "
            "调用方请先 `S.PageRange.from_dict(row[\"page_range\"])` 再传")
    if pr.known and int(pr.start) > int(pr.end):
        return QuoteCheck(None, reason="empty_page_range",
                          tried=(f"empty:{pr.start}-{pr.end}",))
    if pr.known:
        label = f"declared:{pr.start}-{pr.end}"
        tried.append(label)
        hit = scan(pr.start, pr.end, label)
        if hit:
            return hit
        if widen > 0:
            # `widened` 的标签必须与真的扫过的窗口一致：越界被收窄到空集时说
            # `empty`，不写出 `widened:4-3` 这种反向区间（反向标签会让人以为
            # "从第 4 页往第 3 页扫过"）。
            w_lo = max(1, pr.start - widen)
            w_hi = min(len(pages), pr.end + widen)
            label_w = f"widened:{w_lo}-{w_hi}" if w_lo <= w_hi else "widened:empty"
            tried.append(label_w)
            hit = scan(pr.start - widen, pr.end + widen, label_w)
            if hit:
                # 找到了，但不在声明的页码里 —— 这是页码错误，必须显式标记出来
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

    # ---- 没命中且声明窗口里有无可读页 ⇒ 不判 `not_found`
    #
    # 这一步必须在全部分支之后、返回 `not_found` 之前：命中过的都在上面返回了，
    # 走到这里说明"在所有试过的窗口里都没找到"。此时若其中任何一页是抽取失败
    # 的页，那"没找到"就有一部分是"我们根本没读到那一页"造成的 ——
    # 那是 `None`（没法判定），不是 `False`（判成不存在）。
    # 方向很重要：把 `False` 判给一条真引文，等于把真引文记成幻觉（FC-02 最贵的那一档）。
    if pr.known:
        lo: int | None = pr.start - max(0, widen)
        hi: int | None = pr.end + max(0, widen)
    else:
        # 页码未知 ⇒ 考虑范围就是全篇。不许写成 `(None, None)`：
        # `DocumentText.page_unreadable` 对 None 一律返回 False（"窗口未给 ⇒
        # 判不了"），那会把这一支变成"凡页码未知就一律判 not_found" —— 那是把
        # 保守方向反过来（最容易踩的一处，见 tests/test_f4_page_level_tristate.py
        # 的交叉断言）。
        lo, hi = 1, len(pages)
    bad = _pages_unreadable(doc, lo, hi)
    if bad is None:
        # 诊断取不到 ⇒ 不许折成"没有失败页"。
        # 折过去的话，一个坏掉的历史替身会让 quoteverify 静默退回旧行为，
        # 把"我们没读到"报成"这句话不存在"（真引文判成幻觉，且没有日志）。
        logger.warning(
            "逐页状态取不到（`failed_pages()` / `page_unreadable()` 抛了异常）⇒ "
            "本次引文校验判『无法判定』而不是 `not_found`（`R3-6`）：窗口 %s",
            (lo, hi),
        )
        return QuoteCheck(
            None,
            reason="page_status_unknown",
            tried=tuple(tried) or ("no_window",),
        )
    if bad:
        return QuoteCheck(
            None,
            reason="page_unreadable",
            tried=tuple(tried) or ("no_window",),
        )

    return QuoteCheck(
        False,
        reason="not_found" if pr.known else "not_found_page_unknown",
        tried=tuple(tried) or ("no_window",),
    )
