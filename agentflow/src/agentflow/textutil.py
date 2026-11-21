"""文本规范化、相似度、slug、页码解析。

这些函数是"判重"与"引文校验"两块核心逻辑的共同基础，因此必须：
1. 确定性（同输入必同输出，不含随机/时间）；
2. 可解释（相似度用集合 Jaccard，能打印出交集/并集让人核对，而不是黑箱分数）；
3. 双语可用（中文无空格，故中文走字符 bigram；英文走词）。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterator
from typing import Any, Iterable

from .schema import PageRange

# ---------------------------------------------------------------- 基础规范化

_PUNCT_RE = re.compile(
    r"[\u2000-\u206f\u2e00-\u2e7f'!\"#$%&()*+,\-./:;<=>?@\[\]^_`{|}~，。、；：？！“”‘’（）《》〈〉【】—…·]"
)
_WS_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
#: 分词用的字符段（CJK 连续段 与 拉丁/数字段），见 :func:`tokens`。
_TOKEN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[a-z0-9]+")
#: slug 折叠用的连续连字符，见 :func:`slugify`。
_DASH_RUN_RE = re.compile(r"-{2,}")

#: 全角 → 半角的逐码点映射（`str.translate` 用的就是这张表，见 :func:`to_halfwidth`）。
_HALFWIDTH_TABLE: dict[int, int | str] = {
    0x3000: " ",
    **{code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)},
}


def to_halfwidth(text: str) -> str:
    """全角转半角（含全角空格）。"""
    return text.translate(_HALFWIDTH_TABLE)


def normalize(text: str | None) -> str:
    """规范化：NFC → 半角 → 小写 → 去标点 → 折叠空白 → 去首尾。

    去标点是故意激进的：判重时 "Let X be a group." 与 "let X be a group"
    应视为同一句；而引文校验另有更保守的版本（见 `normalize_for_quote`）。
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = to_halfwidth(t)
    t = t.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def normalize_for_quote(text: str | None) -> str:
    """引文校验专用的保守规范化（兼容名，等于 :func:`quote_match_text`）。

    与 `normalize` 的区别：这个投影比 `normalize` 保守（不删标点），但比它更擅长
    消化版式噪声：断行、断词连字符、连字（ﬁ/ﬂ）、控制字符、括号内侧的空白
    都是"同一段文字"的不同排版，不是不同的字。判据本身没变 —— 仍然是
    "投影之后逐字是子串"，没有相似度、没有阈值、没有词序容忍。
    """
    return quote_match_text(text)


def is_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


# ------------------------------------------------------------------ 引文投影
#
# 这一段是"引文回验看到的文本"的唯一实现：写侧（`llm._locate_verbatim`，
# 抽取时把模型给的 quote 投影回原文切片）与收工门（`quoteverify.check_quote`，
# 关系落库前的逐字回验）都只调这里。为什么必须只有一份：
#
# 2026-11-21 真机 lp-ball-15 的日志里连续 32 条"剔除引文无法回验的关系"，
# 逐条回原文核过之后 29 条是真引文（PDF 的断行 / 断词连字符 / 连字 /
# 控制字符 / 页码与页眉插行），而两份实现各差一点：写侧用 NFKC 但不做断词，
# 收工门连 NFKC 都不做（NFC）。于是"同一句话"在写侧过、在门里不过（或反过来），
# 而两边都自洽 —— 只有把真引文判成幻觉这一档会说话。
#
# 判据强度：仍然是"同一份文本先做同一化，再要求逐字命中"。没有相似度、
# 没有阈值、没有词序/数字容忍 —— 改词、颠倒语序、换数字照样红（正控见
# `tests/test_quote_projection_feeds_the_gate.py`）。
#
# 归一到"版式"这一层，不做的事：不删标点（"no, X" 仍不等于 "no X"）、
# 不做词干化、不忽略空白以外的字符差异。

#: 投影里统一的字符（连字符族 → "-"，引号族 → 直引号）。
_QUOTE_CHAR_MAP = {
    **{code: "-" for code in range(0x2010, 0x2016)},
    0x2212: "-",
    0x2018: "'", 0x2019: "'", 0x201B: "'",
    0x201C: '"', 0x201D: '"', 0x201F: '"',
}
#: 括号内侧的空白不算字：`) ] } >` 之前的、`( [ { <` 之后的空白都删掉。
_QUOTE_OPENERS = "([{<"
_QUOTE_CLOSERS = ")]}>,.;:!?"
#: 断词连字符只接在这几种字符后面才算断词（字母另判），见 `_quote_layout`。
_QUOTE_HYPHEN_AFTER = ")]}>"


def _nfkc_clusters(text: str) -> Iterator[tuple[str, int, int]]:
    """把 ``text`` 切成"必须一起做 NFKC 的簇"，逐簇产出 ``(规范化片段, 起, 止)``。

    为什么不能逐字符做 NFKC：NFKC 是上下文相关的，而逐字符规范化会
    把"规范化后等价"的两串判成不同。最典型的失败是组合记号：

        text  = "Spe\\u0301ctrum"（s p e + 组合尖音符 …，PDF/LaTeX 常见的分解形）
        quote = "Sp\\u00e9ctrum" （预组合的 é）
        unicodedata.normalize("NFKC", text) == unicodedata.normalize("NFKC", quote)  # True！

    但逐字符规范化后前者里的 ``e``+``´`` 仍是两个字符，后者是一个 ``é``，
    于是一句真的引文会被判成幻觉、被剔除。

    簇的边界用 ``NFC`` 探测"相邻两字符会不会合成"（合成后串变短/变不同），
    这比列举 Unicode 组合类更通用：组合记号、Hangul Jamo 都能被它覆盖。
    """
    i = 0
    n = len(text)
    while i < n:
        j = i + 1
        # 只要"前一字符 + 当前字符"还能合成出别的东西，就必须留在同一个簇里。
        while j < n and unicodedata.normalize("NFC", text[j - 1:j + 1]) != text[j - 1:j + 1]:
            j += 1
        yield unicodedata.normalize("NFKC", text[i:j]), i, j
        i = j


def _quote_layout(chars: list[str], spans: list[tuple[int, int]]
                  ) -> tuple[str, list[tuple[int, int]]]:
    """版式层的三条规则（都在字符流上做，删字符时同步删它们的区间）。

    输入 ``chars`` 已经过统一映射（连字符族 → "-"、引号族 → 直引号）。

    1. 断词连字符：`-` + 可选空白 + 字母 ⇒ 连字符与空白一起删。按同一个规则处理
       引用侧与原文侧，于是 "Gen- \\neralized" ≡ "Generalized"，而 ")- rectifiable"
       ≡ ")-rectifiable"（两边的连字符都按同一条规则处理，不会一边留一边不留）。
       投影必须先映射再跑这条规则，否则"第二轮"会把上一轮由破折号映射来的 "-"
       当成断词连字符再删一次 —— 那样投影就不幂等，写侧与门里各投影一次会得到
       两个不同的串（`p{页}:norm` 的区间也会跟着错位）。
    2. 括号内侧空白：右括号/收尾标点前的空白、左括号/开括号后的空白都删
       （PDF 换行会凭空造出 `p\\n)`、`( deﬁned` 这种形态）。
    3. 空白折叠与去首尾（"空格"是这条投影里唯一保留的分隔符）。
    """
    out_c: list[str] = []
    out_s: list[tuple[int, int]] = []
    i, n = 0, len(chars)
    while i < n:
        ch = chars[i]
        # 断词连字符：两种情况才按"断词"处理 ——
        #   ① 前面是字母且后面跟着空白（PDF 的行末断词："Gen- \neralized"）；
        #   ② 前面是右括号且后面是字母（"…, m)-\nrectifiable" 这类术语里的连字符，
        #      模型抄回来时会把换行拼掉、连字符留着："(Hm, m)-rectifiable"）。
        # 不满足这两条的连字符原样保留，所以：公式里的减号（"2 −g2"，前面是空格）
        # 不会被吃掉；"A—B" 这类破折号仍归一成 "a-b" 而不是被粘成 "ab"；
        # 复合词里的真连字符（"well-known"）也留着。投影必须幂等，见 `_quote_layout`。
        if ch == "-" and out_c:
            prev = out_c[-1]
            j = i + 1
            while j < n and chars[j] == " ":
                j += 1
            spaced = j > i + 1
            if (j < n and chars[j].isalpha()
                    and ((prev.isalpha() and spaced) or prev in _QUOTE_HYPHEN_AFTER)):
                i = j          # 连字符与中间的空白一起删；下一个字母留给下一轮
                continue
        if ch == " ":
            nxt = chars[i + 1] if i + 1 < n else ""
            prev = out_c[-1] if out_c else ""
            # 首部空白 / 括号内侧空白 / 连续空白：都不进投影
            if not out_c or nxt in _QUOTE_CLOSERS or prev in _QUOTE_OPENERS or prev == " ":
                i += 1
                continue
        out_c.append(ch)
        out_s.append(spans[i])
        i += 1
    # 尾部空白在循环里不会被写出来（只有"后面还有字"时才落一个空格），无需再截。
    return "".join(out_c), out_s


def project_quotes(text: str | None) -> tuple[str, list[tuple[int, int]]]:
    """把一段文本投影成"引文比对用的那一串字"，并保留每个字的原文区间。

    返回 ``(projected, spans)``，``spans[i] = (start, end)`` 是 ``projected[i]``
    在 ``text`` 里对应的原始区间 ``text[start:end]``。插入的分隔空格是零宽区间
    ``(start, start)``（它不对应原文任何字符，也不可能成为匹配的首字符）。

    这两样一起返回，是为了让"定位"与"比对"用同一个投影：收工门只取第一项
    （只看"在不在"），写侧还要第二项（把命中的那一段原文切片存进 quote）。
    """
    if not text:
        return "", []
    chars: list[str] = []
    spans: list[tuple[int, int]] = []
    pending_space = False
    for piece, start, end in _nfkc_clusters(text):
        for ch in piece.casefold():
            # 软连字符是零宽格式字符：视觉上不存在，只标记"这里可断行"。
            # 当空白处理会凭空插入一个空格（"abel\\u00adian" → "abel ian"），
            # 于是 PDF 断词处的真引文永远匹配不上。
            if ch == "\u00ad":
                continue
            if ch.isspace():
                pending_space = True
                continue
            if unicodedata.category(ch) in ("Cc", "Cf"):
                # 控制字符 / 格式字符：PDF 的符号字体常把它们当字形写进文本层
                # （真机 lp-ball-15 的第 26 条里，公式的 ">" 被抽成了 U+0015）。
                continue
            if pending_space and chars:
                chars.append(" ")
                spans.append((start, start))
            pending_space = False
            # 统一映射放在这里（而不是版式层）：投影必须幂等，见 `_quote_layout`。
            chars.append(_QUOTE_CHAR_MAP.get(ord(ch), ch))
            spans.append((start, end))
    return _quote_layout(chars, spans)


def quote_match_text(text: str | None) -> str:
    """引文比对用的投影（唯一判据的那一半）：只保留"同一段文字"的字面。

    逐条规则见 :func:`project_quotes` 的 `_quote_layout` 一节。调用方拿它把
    引文与原文投影到同一个坐标系里，然后做子串比较。
    """
    return project_quotes(text)[0]


def locate_verbatim(text: str, quote: str) -> str | None:
    """在 ``text`` 里定位 ``quote``，返回原文里的确切切片；定位不到返回 ``None``。

    命中判据只有一条：两边经 :func:`project_quotes` 投影之后，``quote`` 的投影是
    ``text`` 投影的子串。返回的是原文切片（用区间映射还原），所以调用方拿去
    落盘的东西天然是 ``text`` 的子串 —— 不需要再相信谁。

    先试原样子串（零成本且能保住"模型抄的就是原文里连续的这一片"），再走投影。
    """
    if not quote:
        return None
    if quote in text:
        return quote
    projected, spans = project_quotes(text)
    quote_projected, _ = project_quotes(quote)
    if not quote_projected:
        return None
    pos = projected.find(quote_projected)
    if pos < 0:
        return None
    start = spans[pos][0]
    # 末尾用区间右端而不是"起始下标 + 1"：一个投影字符可能来自多个原文字符，
    # 用 +1 会把 "é"（来自 "e"+组合记号）或 "fi"（来自连字 ﬁ）切掉一半。
    end = spans[pos + len(quote_projected) - 1][1]
    return text[start:end]

# ---------------------------------------------------------------- 关键词命中（唯一判据）
#
# 这一段是"怎么算包含"的唯一实现：命题台账查口（`statementledger.by_keywords`）与
# 通用表工具（`tools/table_tools.table_search` 在 `statements` 表上）都调它。
#
# 为什么必须只有一处：两处各写一份时，同一个查询会给出两个结论
# —— 工具层用 `casefold` 裸子串，查口用 `normalize`（全半角 / 大小写 / 标点 / 空白都折叠）。
# 例如 `noether，环` 在查口命中 `Noether 环`、在工具层 0 命中；全角 `Ｐ 阶元` 同样分家。
# 两边各自都自洽 ⇒ 没有任何判据会报错，只有人对着读数才看得出来。


def normalized_keywords(keywords: str | Iterable[Any]) -> list[tuple[str, str]]:
    """关键词 → `[(原样, 归一后)]`；归一后为空的词丢掉。

    三态：空词不是"空命中"——它连一问都构成不了（`by_keywords` 据此给
    `checked=False`）。丢在这里而不是让调用方各判一次：那正是两份实现开始分家的地方。
    """
    raw_words = [keywords] if isinstance(keywords, str) else list(keywords or ())
    out: list[tuple[str, str]] = []
    for raw in raw_words:
        text = str(raw)
        norm = normalize(text)
        if norm:
            out.append((text, norm))
    return out


def matched_keywords(texts: Iterable[str | None],
                     wanted: Iterable[tuple[str, str]]) -> list[str]:
    """在多段文本里找命中的关键词，按给定次序返回原样的词。

    - 判据只有一句：`normalize(文本)` 里包含 `归一后的关键词`（子串）。全半角 / 大小写 /
      标点 / 空白都由 `normalize` 折叠，所以"同一个词的不同写法"是同一个词；
    - 多段文本任一命中即算命中（`label` 与 `statement_full` 就是两段）；
    - `texts` 只收 `str | None`：非字符串由调用方先决定怎么处理（工具层跳过、查口 `str()`），
      本函数不替它猜一个字面量出来。
    """
    hay = [normalize(text) for text in texts]
    return [raw for raw, norm in wanted if any(norm in chunk for chunk in hay)]


# ---------------------------------------------------------------- 分词与相似度


def tokens(text: str) -> set[str]:
    """切成 token 集合。

    - 含 CJK 的串：CJK 段取字符 bigram（单字兜底），拉丁段仍按词。
      这样"阿贝尔群"与"阿贝尔 群"能产生稳定重叠，且中文无须分词器。
    - 纯拉丁串：按词。
    """
    norm = normalize(text)
    if not norm:
        return set()
    out: set[str] = set()
    # 先把 CJK 连续段与拉丁段分开
    for m in _TOKEN_RE.finditer(norm):
        chunk = m.group(0)
        if is_cjk(chunk):
            if len(chunk) == 1:
                out.add(chunk)
            else:
                out.update(chunk[i : i + 2] for i in range(len(chunk) - 1))
        else:
            out.add(chunk)
    return out


def similarity(a: str, b: str) -> float:
    """token 集合的 Jaccard 相似度，值域 [0, 1]。

    两边都空 → 0.0（而不是 1.0）："两个空串"不构成"相同表述"，判重时应走向
    "不相似"分支，避免空值互相判重。
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def similarity_detail(a: str, b: str) -> dict:
    """给人类看的相似度明细 —— 判重结果必须能被复核，所以保留证据。"""
    ta, tb = tokens(a), tokens(b)
    inter, union = ta & tb, ta | tb
    return {
        # 与 `similarity(a, b)` 同一个商：这里两组 token 已经在手上，
        # 再调一次会把两边各重新切一遍（首次命中相同，只是白算）。
        "score": round(len(inter) / len(union), 4) if union else 0.0,
        "shared": sorted(inter)[:40],
        "only_a": sorted(ta - tb)[:20],
        "only_b": sorted(tb - ta)[:20],
        "n_a": len(ta),
        "n_b": len(tb),
    }


# ---------------------------------------------------------------- 摘要 / 哈希


def short_hash(text: str, n: int = 16) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:n]


def clip(text: str | None, limit: int = 1200) -> str:
    """按字符截断并加省略标记。用于摘要等展示字段，不用于判重。"""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- slug / 文件名


#: 白名单：ASCII 字母数字 + CJK 统一汉字基本区（U+4E00–U+9FFF）。
#:
#: 为什么白名单而不是黑名单（"只去危险字符"）：黑名单永远列不全。
#: Windows 的保留设备名（``CON``/``NUL``/``LPT1``）、结尾的 ``.`` 与空格、
#: Unicode 里的方向覆盖字符（U+202E 可以把 ``gpj.exe`` 显示成 ``exe.jpg``）
#: 都是"看起来无害但会出事"的形态。白名单把判据的反面变成默认值：
#: 没被显式允许的字符通通不许进文件名，因此不可能漏掉某个危险形态。
_SLUG_STRIP = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def slugify(text: str, limit: int = 60, fallback: str = "untitled") -> str:
    """把任意文本变成安全的文件名片段 —— 全项目唯一的一份 slug 规则。

    ``fetch.slugify`` 转发到本函数（唯一判据），参数名与默认值由调用点显式表达。
    与 ``fetch`` 那份的差别只在两处：本函数保留 CJK（那一份把 CJK 一并当分隔符剥掉），
    空结果回退 ``"untitled"``（那一份回退 ``"download"``）。

    ## 规则与理由

    1. NFC → NFKC → 全角转半角 → 小写：NFKC 会把兼容字符折成它们的
       规范形态（``ﬁle`` → ``file``、``①②`` → ``12``），避免了"字符被当成
       标点整块删光"这种静默信息损失；``to_halfwidth`` 再兜住全角空格
       （U+3000，NFKC 已覆盖）与全角字母数字。
    2. 非 ASCII / 非字母数字一律替换为 ``-``，再折叠连续 ``-``。
       这不是"删字符"而是"替换成分隔符"：``a/b`` → ``a-b`` 保留了
       "这里是两个词"的信息，也让 ``..``/``//`` 这类路径片段结构上不可能
       留下 ``/`` ``\\`` ``.``。
    3. 保留 CJK 基本区（中文标题不必音译 —— 这是本项目的既定设计，
       ``agent_a`` 用它造下载提示名）。与之配套的三条真实约束是：
       - *文件系统*：白名单保证了不含路径分隔符、不以 ``.`` 开头或结尾、
         不含控制/方向字符，因此 Windows 的保留名与穿越形态天然不可达；
         CJK 文件名在 NTFS/ext4 上都是合法的 UTF-8 名称（本仓库的
         ``library/`` 也已经在存中文标题的文献文件）。
       - *可读性*：音译/删除 CJK 会让"群论基础"与"环论基础"退化成同一个
         slug（都空 ⇒ 都回退成占位名），比中文名更危险 —— 那才是真正的碰撞。
       - *唯一性*：文件名不靠本函数保证唯一。真正的唯一性由
         ``fetch._target_path`` 的短哈希后缀负责，本函数只提供可读前缀。
    4. 空结果回退 ``fallback``，绝不返回空串：空串会让 ``dest / ""``
       变成目录本身、让 ``Path("")`` 在别的调用点变成 ``.``。
       ``fallback`` 只允许由调用点给出"非空且本身能通过本函数"的常量；
       它同样会过一遍本规则，因此它自己也不是绕过白名单的后门。
    5. ``limit`` 按字符截断（不是字节）。UTF-8 下中文一字 3 字节，
       60 字符 ≈ 180 字节，远低于各平台的单段上限（255 字节），故不会
       在文件系统层被静默截断。截断后再 ``strip("-")``，防止留下尾随 ``-``。
    """
    t = to_halfwidth(unicodedata.normalize("NFKC", text or "")).lower()
    t = _SLUG_STRIP.sub("-", t).strip("-")
    t = _DASH_RUN_RE.sub("-", t)
    slug = t[:limit].strip("-")
    if slug:
        return slug
    # 回退值本身也过同一套规则：调用点若传了 `"a/b"` 这类东西，也不会漏出去。
    safe = _SLUG_STRIP.sub("-", to_halfwidth(unicodedata.normalize("NFKC", fallback or ""))).strip("-")
    return _DASH_RUN_RE.sub("-", safe) or "untitled"


# ---------------------------------------------------------------- 页码解析

_PAGE_PATTERNS = [
    # pp. 45-67 / p. 45 / pp.45–67
    re.compile(r"\bpp?\.?\s*(\d{1,5})\s*[-–—~]\s*(\d{1,5})", re.I),
    re.compile(r"\b(\d{1,5})\s*[-–—~]\s*(\d{1,5})\b"),
    re.compile(r"\bpp?\.?\s*(\d{1,5})\b", re.I),
    re.compile(r"\bp\.?\s*(\d{1,5})\b", re.I),
]


def parse_page_range(text: str | None) -> PageRange:
    """从自由文本里解析页码范围。

    解析不出来时返回 `PageRange(None, None, 原文本)` —— 显式表达未知。
    这一点很重要：B 的引文校验依赖页码窗口，若把未知页码当成 1-1，
    就会去错误的页里找引文，然后报告"引文不存在"，产生假阴性。
    """
    if not text:
        return PageRange(None, None, "")
    raw = text.strip()
    for pat in _PAGE_PATTERNS:
        m = pat.search(raw)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 2:
            try:
                return PageRange(int(groups[0]), int(groups[1]), raw)
            except ValueError:
                continue
        elif len(groups) == 1:
            try:
                n = int(groups[0])
                return PageRange(n, n, raw)
            except ValueError:
                continue
    return PageRange(None, None, raw)


def concept_group_key(concept_ids: Iterable[str]) -> str:
    """概念组的稳定键：升序去重后用 `|` 连接。

    关系判重的前置条件：不同概念组之间文本再像也是不同知识点。
    """
    return "|".join(sorted(set(concept_ids)))


# ---------------------------------------------------------------- 引用解析（唯一实现）


def citation_ref_parts(citation: Any) -> tuple[str, str]:
    """把一条 citation 拆成 `(前缀, 代号)`：按第一个 `:` 切、再去掉 `#` 之后的部分。

    ## 为什么它是唯一实现、以及为什么放在 `textutil`

    这条口径只许有一份：`verify.py` 的 `dangling_citation` 检查与工具层
    `doc_tools.citation_ref_parts()` 如果各写一份，两份必须逐字一致 —— 否则"G 认为
    合法的引用"与"verify 认为悬空的引用"会给出不同答案，而两边各自都自洽
    （FC-03 禁止的形态）。

    落点选 `textutil` 而不是 `verify.py`，理由是依赖图：

    - `tools/table_tools.py` 有 `from ..verify import verify_all`
      ⇒ 工具层依赖 `verify`。所以"`verify` 去 import 工具层"是把依赖方向
      反过来引一条新边，会把工具包的装配（`tools/__init__`）拉进审计模块的
      import 图里；`verify` 与 `tools/doc_tools` 之间没有任何现有边。
    - `textutil` 是一个叶子：它只 import `schema`。而 `verify.py` 与
      `tools/doc_tools.py` 本来就都 import 它（`from . import textutil as T` /
      `from .. import textutil as T`）。
    - 于是把实现放在 `textutil` 是零新边、结构上不可能成环的那个方向。

    ## 语义（必须逐字保住，改之前先看这条）

    `partition(":")` 而不是 `split(":")`：只切第一个冒号，代号里再出现 `:` 就留在
    代号里。`split("#")[0]`：`#` 之后是断言内的锚点（`rel:0001#claim-1`），
    不参与"这个代号存不存在"的判定。

    边界（有对拍用例守着）：无冒号 ⇒ `("整串", "")`；冒号在开头 ⇒ `("", "代号")`；
    多个 `#` ⇒ 只取第一段；非字符串 ⇒ 先 `str()` 再切。
    """
    kind, _, ref = str(citation).partition(":")
    return kind, ref.split("#")[0]


#: 自由文本里的引用记号：`<前缀>:<代号>`（代号里允许数字、字母、`-`、`_`，允许 `#锚点`）。
#: 前缀不在这里写死 —— 认不认由 `schema.CITATION_PREFIXES`（唯一声明面）说了算，
#: 这条正则只负责"把长得像引用的那一小段切出来"。
_TEXT_CITATION = re.compile(r"(?<![\w:/])([A-Za-z][A-Za-z0-9_]*):([A-Za-z0-9][A-Za-z0-9_\-]*)(#[^\s，。；、）)\]】\"']*)?")


def find_citations(text: Any, *, prefixes: Iterable[str] | None = None) -> list[dict[str, str]]:
    """从自由文本里扫出引用记号，按出现次序返回（同一个记号只出现一次）。

    口径：「B 只交定理内容 + 证明过程」，而「依赖 = 证明过程里引用到的那些号」
    ⇒ 秘书要从证明文本里逐条扫出引用。这一格就是那件事的唯一实现（`citation_ref_parts`
    只解析一条已经切好的 citation，没有"从一段话里找出来"的那一半）。

    返回 `[{"raw", "prefix", "code", "table"}]`：

    - `raw` 是原文里那一段（含 `#锚点`，便于读数里回指）；
    - `prefix` / `code` 由 `citation_ref_parts` 切出来（同一套口径，不在这里抄第二份）；
    - `table` 由 `schema.CITATION_PREFIXES` 给（不认识的前缀不进结果 ——
      "认不认"只有那一处说了算）。`prefixes` 给了就只认那几个（调用方想收窄时的显式口）。

    为什么"不认识的记号"不返回、也不报错：这一格只回答"这里有哪些在册的引用"。
    "文本里出现了不成形态的东西"是另一件事（`doc.scan_claim` / `verify` 的
    `dangling_citation` 那一档管），两件事折平会让调用方分不清"没有引用"与"引用写坏了"。
    """
    from . import schema as S   # 惰性：前缀表是 schema 的声明面

    wanted = None if prefixes is None else {str(p) for p in prefixes}
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in _TEXT_CITATION.finditer(str(text or "")):
        raw = m.group(0)
        prefix, code = citation_ref_parts(raw)
        if wanted is not None and prefix not in wanted:
            continue
        table = S.citation_prefix_table(prefix)
        if table is None or not code:
            continue
        # 去重的键是 `(前缀, 代号)` 而不是原文那一段：`lit:0003#p.4` 与 `lit:0003`
        # 指向同一条（`citation_ref_parts` 的语义：`#` 之后是锚点，不参与身份），
        # 于是它们必须落成一条依赖边而不是两条 —— 落两条会让"依赖面"凭空多一环。
        if (prefix, code) in seen:
            continue
        seen.add((prefix, code))
        out.append({"raw": raw, "prefix": prefix, "code": code, "table": table})
    return out
