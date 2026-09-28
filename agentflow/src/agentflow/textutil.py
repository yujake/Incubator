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
from typing import Any, Iterable

from .schema import PageRange

# ---------------------------------------------------------------- 基础规范化

_PUNCT_RE = re.compile(
    r"[\u2000-\u206f\u2e00-\u2e7f'!\"#$%&()*+,\-./:;<=>?@\[\]^_`{|}~，。、；：？！“”‘’（）《》〈〉【】—…·]"
)
_WS_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def to_halfwidth(text: str) -> str:
    """全角转半角（含全角空格）。"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


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
    """引文校验专用的保守规范化。

    与 `normalize` 的区别（DESIGN.md §6.3）：只允许空白折叠、大小写、连字符与
    引号归一化、全半角转换；不删标点（因为删标点会让 "no, X" 与 "no X" 等价，
    从而放过错误的引文）。
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = to_halfwidth(t)
    t = t.lower()
    # 统一各种连字符与引号
    t = re.sub(r"[\u2010-\u2015\u2212]", "-", t)
    t = re.sub(r"[\u2018\u2019\u201b]", "'", t)
    t = re.sub(r"[\u201c\u201d\u201f]", '"', t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def is_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


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
    for m in re.finditer(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[a-z0-9]+", norm):
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
        "score": round(similarity(a, b), 4),
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

    合并前后的两套契约（见 ``INVENTORY.md`` §4.7②）：
    ``fetch.slugify`` 原先把 CJK 一并当分隔符剥掉、空结果回退 ``"download"``；
    本函数保留 CJK、空结果回退 ``"untitled"``。``fetch.slugify`` 现已改为
    转发到本函数（唯一判据），参数名与默认值由调用点显式表达。

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
    t = re.sub(r"-{2,}", "-", t)
    slug = t[:limit].strip("-")
    if slug:
        return slug
    # 回退值本身也过同一套规则：调用点若传了 `"a/b"` 这类东西，也不会漏出去。
    safe = _SLUG_STRIP.sub("-", to_halfwidth(unicodedata.normalize("NFKC", fallback or ""))).strip("-")
    return re.sub(r"-{2,}", "-", safe) or "untitled"


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

    关系判重的前置条件（DESIGN.md §3.3）：不同概念组之间文本再像也是不同知识点。
    """
    return "|".join(sorted(set(concept_ids)))


# ---------------------------------------------------------------- 引用解析（P-5 的唯一实现）


def citation_ref_parts(citation: Any) -> tuple[str, str]:
    """把一条 citation 拆成 `(前缀, 代号)`：按第一个 `:` 切、再去掉 `#` 之后的部分。

    ## 为什么它是唯一实现、以及为什么放在 `textutil`（`P-5`）

    这条口径此前有两份实现：`verify.py` 的 `dangling_citation` 检查里内联着
    一份，工具层 `doc_tools.citation_ref_parts()` 又抄了一份。两份必须逐字一致 ——
    否则"G 认为合法的引用"与"verify 认为悬空的引用"会给出不同答案，而
    两边各自都自洽（FC-03 禁止的形态）。

    落点选 `textutil` 而不是 `verify.py`，理由是依赖图（改前实测）：

    - `tools/table_tools.py:1135` 有 `from ..verify import verify_all`
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
