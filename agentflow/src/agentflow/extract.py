"""文本抽取层：``extract_text(path) -> DocumentText``。

设计基线：``test/test1/DESIGN.md`` §4.1（接口契约）与 §6.3（引文校验）。

本模块的唯一职责是把一个本地文件变成"逐页可定位的文本"，它不负责
概念/关系抽取（那是 llm.py），也不负责引文校验（那是 agent_b + verify）。

三条贯穿全模块的设计原则（先说明，后面不再重复）：

1. 逐页是硬要求，不是可选优化。
   §1.4 的 ``relations.page_range`` 与 §6.3 的引文校验都要求"这条引文出自
   第几页"。如果只保留全文拼接串，页码就退化成模型/正则的猜测。因此 PDF
   一定保留 ``pages[i] == 第 i+1 页``，``text`` 只是 ``"\\n".join(pages)``
   的派生投影。

2. "无文本层"必须与"文档为空"显式区分（§6.3 的关键）。
   扫描版 PDF 能被成功打开、页数正常，但每页抽出来的都是空白。此时如果
   老老实实返回 ``pages=["", "", ...]``，下游 ``text_at()`` 会返回空串，
   §6.3 的子串匹配就会失败——失败方向恰好是安全的（不会假通过），
   但语义上说不清"校验失败"还是"根本没法校验"。二者对用户的意义完全
   不同：前者是抽取质量问题，后者是"这份文献需要 OCR"。因此本模块约定：
   所有页去空白后皆为空 ⇒ ``pages == []``、``text == ""``。
   调用方（agent_b）只用 ``pages == []`` 判断无文本层，并必须据此把
   ``quote_verified`` 置 ``null``（而不是 ``true``/``false``）。见 §6.3 末段
   "不假装通过"。

3. 超限一律抛异常，绝不静默截断。
   2000 页 / 50 MB 是资源保护，不是业务粒度。静默截断会让"引文在文件里
   存在但没被读到"变成一条看似正常的 ``quote_verified=false``，把资源问题
   伪装成数据问题。所以宁可显式失败，让人去调 ``--max-pages``。

依赖策略：``fitz``/``pdfminer``/``PyPDF2`` 都是重量级 C 扩展或纯 Python 大包，
且要支持"谁在就用谁"的回退链，因此一律函数内惰性 import；模块顶层只依赖
标准库。这样即使某个 PDF 后端没装，``import agentflow.extract`` 也不会炸。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_PAGES",
    "DocumentText",
    "ExtractError",
    "ExtractTooLarge",
    "HtmlNotSupported",
    "UnsupportedFormat",
    "extract_text",
    "page_count",
]


# --------------------------------------------------------------------------- #
# 常量与异常
# --------------------------------------------------------------------------- #

#: 默认页数上限。超大文献多半是扫描件或整本手册，交给 B 逐页抽关系没有意义。
DEFAULT_MAX_PAGES: Final[int] = 2000

#: 默认字节上限 50 MB。超过这个体量的"单篇文献"通常是误抓的整库 PDF。
DEFAULT_MAX_BYTES: Final[int] = 50 * 1024 * 1024

#: 纯文本类文件的编码回退链。顺序是有讲究的：
#: - ``utf-8`` 覆盖绝大多数现代文件；
#: - ``utf-8-sig`` 兜住带 BOM 的文件（严格 utf-8 其实能解出 BOM，但会留下 U+FEFF，
#:   见 ``_decode_text`` 里对 BOM 的显式剥离）；
#: - ``gb18030`` 兜住中文旧文献（它是 GBK/GB2312 的超集，覆盖面最广）；
#: - ``latin-1`` 是永不失败的兜底（1 字节 = 1 码点），保证最后一个分支能收尾。
_ENCODING_CHAIN: Final[tuple[str, ...]] = ("utf-8", "utf-8-sig", "gb18030", "latin-1")

#: 扩展名 → source_kind 的映射。无扩展名走文本分支（离线素材里很常见）。
_TEXT_SUFFIXES: Final[frozenset[str]] = frozenset({".txt", ".md"})
_HTML_SUFFIXES: Final[frozenset[str]] = frozenset({".html", ".htm", ".xhtml"})

#: 魔数/头部嗅探只读文件开头这么多字节。为什么几十字节就够：`%PDF-` 是 5 字节，
#: HTML/XML 的判据是"开头有没有声明或根元素"，两者都不需要读全文。
_SNIFF_BYTES: Final[int] = 512


class ExtractError(RuntimeError):
    """抽取失败的基类。

    继承 ``RuntimeError`` 而不是 ``Exception``：这类失败都是"运行时环境/文件
    内容"问题，不是调用方写错了参数，便于 agent_b 用 ``except ExtractError``
    统一兜住并记入 ``unprocessable``。
    """


class UnsupportedFormat(ExtractError):
    """扩展名不在支持范围内（§4.1 只承诺 pdf/txt/md/html）。"""


class ExtractTooLarge(ExtractError):
    """超过页数或字节上限。抛异常而非截断，理由见模块 docstring 第 3 条。"""


class HtmlNotSupported(ExtractError):
    """内容是按魔数判出来的 HTML/XML，但调用方给的扩展名不在 `_HTML_SUFFIXES` 里。

    为什么它必须是一个独立类型，而不是让 :class:`UnsupportedFormat` 去承担：
    两者对调用方的含义完全不同。扩展名不支持说的是"这个后缀的格式我们不认识"，
    而这里的内容确实是 HTML（正文就在里面，剥标签就能拿到可回验文本）—— 只是
    文件被存成了 `.bin` 这类名字（实测出现过：Crossref 链接落下来的响应是 HTML，
    却被存成 `.bin`）。旧行为会报成"不支持的扩展名"，把一次可处理的内容
    说成"格式不认识"，调用方据此只能放弃；现在的理由直接告诉他怎么处理。
    """


# --------------------------------------------------------------------------- #
# DocumentText：§4.1 契约
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DocumentText:
    """一篇文献的文本视图。

    字段语义（与 §4.1 一致，仅新增一个带默认值的可选字段，位置参数构造不受影响）：

    - ``text``：全文（PDF 情况下即 ``"\\n".join(pages)``）。供不关心页码的
      全文检索 / 交给 LLM 的一次性输入使用。
    - ``pages``：逐页文本，1-based，``pages[i]`` 是第 ``i + 1`` 页。
      ``pages == []`` 表示无文本层（扫描件）或文件确实没有正文，
      调用方必须把它当作"无法校验引文"处理（§6.3）。
    - ``source_kind``：``pdf | txt | md | html``，记录走了哪条抽取路径，
      便于事后审计"这条引文来自 PDF 还是 HTML 快照"。
    - ``encoding``：纯文本类文件实际生效的编码名（PDF/HTML 走字节解析
      时为 ``None``）。记录它是为了可复现：gb18030 与 latin-1 都能"成功"
      解码同一份字节但结果完全不同，不记录就无法解释抽取结果为何如此。

    ``frozen=True`` 的理由：抽取结果会被多个消费者（LLMExtractor、
    verify、报告）共享读取，冻结可避免"某个下游顺手改了 pages 导致页码错位"
    这类极难排查的串扰。
    """

    text: str
    pages: list[str]
    source_kind: str
    encoding: str | None = None
    #: 逐页三态（`F-4`）：`ok` / `empty` / `failed`。它记录的是后端上报的
    #: 真实页数，不保证与 `pages` 等长：`_finish_pdf` 的"无文本层"那一支会
    #: 刻意把 `pages` 置空而保留逐页状态（`R3-2` 的取舍，`R6-AN-2` 把这条写清）。
    #: 要用就用 `page_status` / `failed_pages()`，不要拿 `pages` 的长度去索引它
    #: —— 空 `pages` 会让 `zip(pages, page_status)` 静默变空，越界索引若兜成
    #: `"ok"` 会把"这一页读到了"判给一个没读到的页。
    #:
    #: 为什么需要它：`pages[i] == ""` 有两种完全不同的原因 ——
    #: "这一页本来就是空白"与"这一页抽取时抛异常了"。旧实现把两者都写成 `""`，
    #: 于是下游（`ocr.inspect`、`quoteverify.check_quote`）无法区分，
    #: 结果是真引文被判成幻觉（`not_found`）而 OCR 检查同时告诉人
    #: "有文本层，引文校验可以正常判定"。
    #:
    #: 空元组 = "没有逐页信息"（历史构造点、或整篇只有一个文本单元的文类），
    #: 此时 `page_status_of()` 一律返回 `"ok"` —— 与旧行为逐字一致，
    #: 所以这个字段是纯增量，不会把历史调用方变成"整篇不可读"。
    page_status: tuple[str, ...] = ()

    @property
    def has_text_layer(self) -> bool:
        """是否存在可定位的文本层。

        这是 agent_b 判断 §6.3 分支的唯一依据：``False`` ⇒
        ``quote_verified = None``、``status = "suspect"``，并在报告里计入
        "因无文本层未能校验"的条数。
        """
        return bool(self.pages)

    def failed_pages(self) -> tuple[int, ...]:
        """抽取时抛过异常的页号（1-based）。`F-4` 的消费点都用它。"""
        if not self.page_status:
            return ()
        return tuple(i + 1 for i, s in enumerate(self.page_status) if s == "failed")

    def page_status_of(self, page: int) -> str:
        """第 `page` 页（1-based）的状态；无逐页信息时返回 ``"ok"``。"""
        if not self.page_status or not (1 <= page <= len(self.page_status)):
            return "ok"
        return self.page_status[page - 1]

    def page_unreadable(self, start: int | None, end: int | None) -> bool:
        """`[start, end]`（1-based 闭区间，已收窄）里有任何一页不可读吗。

        引文校验用它来区分"这句话不在这页上"与"这页根本没抽出来"：
        后者必须走 `quote_verified=None`（没法判定），而不是 `False`（判成不存在）。

        `R3-5`：这句话在 2026-09-26 之前是假的 —— 那时生产代码里没有调用点，
        `quoteverify.check_quote` 自己用 `failed_pages()` + 区间过滤重写了同一判据。
        现在 `check_quote` 真的调本方法（判据只有这一份实现），
        所以"引文校验用它"是事实而不是愿望。
        传 `None` 表示"窗口未给" ⇒ 返回 `False`（判不了，而不是"全篇都要查"）。
        """
        if not self.page_status or start is None or end is None:
            return False
        lo = max(1, int(start))
        hi = min(len(self.page_status), int(end))
        if lo > hi:
            return False
        return any(self.page_status_of(p) == "failed" for p in range(lo, hi + 1))

    def text_at(self, start: int | None, end: int | None) -> str:
        """取第 ``start`` 页到第 ``end`` 页的文本（1-based 闭区间）。

        为什么页号是闭区间：§1.4 的 ``page_range = {start, end}`` 和
        §6.2/§6.3 的"±1 页扩大窗口重试"都是按"页"这个人类单位讨论的，
        闭区间与需求原文（"页码范围"）一致，也避免了"end 是开是闭"的经典歧义。

        边界行为与为什么这样定：

        - ``pages == []``（无文本层）⇒ 返回 ``""``。此时没有可校验的对象。
        - ``start`` 或 ``end`` 为 ``None`` ⇒ 返回 ``""``。
          这是刻意的、与"None 视为全文"相反的取舍：``text_at`` 的调用方是
          §6.3 的引文校验，它的语义是"这一页上确实有这句话"。
          若把 ``None`` 当作全文，等于让"引文出现在文档任意位置"冒充
          "引文出现在所声称的页上"——页码字段就失去了约束力，
          ``quote_verified=true`` 会变成一句无法追究的空话。
          取不到页范围就意味着无法定位，而无法定位就不该声称能校验，
          所以返回空串，让校验自然走向"未命中"这一失败方向（fail-closed）。
        - 越界自动收窄到 ``[1, len(pages)]``（例：``text_at(0, 999)`` 在 3 页
          文档上等价于 ``text_at(1, 3)``）。收窄而不是抛异常，是因为 §6.1
          第 5 步明确要求"未命中 → 扩大窗口到 ±1 页重试"：扩窗天然会越界，
          这里若抛异常会把正常的重试流程变成崩溃。
        - 收窄后 ``start > end``（例如 ``text_at(9, 9)`` 在 3 页文档上、
          或 ``text_at(5, 2)``）⇒ 返回 ``""``，不做页码互换。互换会掩盖
          "范围写反了"这个上游 bug，而空串会让校验失败暴露它。
        """
        if not self.pages:
            return ""
        if start is None or end is None:
            return ""
        lo = max(1, int(start))
        hi = min(len(self.pages), int(end))
        if lo > hi:
            return ""
        return "\n".join(self.pages[lo - 1 : hi])

    def page_of(self, needle: str, *, default: int = 1) -> int:
        """定位子串 ``needle`` 首次出现的页号（1-based）。

        RuleExtractor 用它把"原句"映射回页码。若找不到则返回 ``default``
        （默认 1）——注意这不是在伪造定位：RuleExtractor 的句子本来
        就是从某一页的原文里切出来的，走的是同一个规范化路径，找不到只可能
        是调用方传了别处来的串。为了不让调用方悄悄拿到错页码，这里返回
        ``default`` 并在 docstring 里写明它只是兜底值。
        """
        if not needle or not self.pages:
            return default
        for idx, page in enumerate(self.pages):
            if needle in page:
                return idx + 1
        return default


# --------------------------------------------------------------------------- #
# 文本类文件：编码回退
# --------------------------------------------------------------------------- #


def _decode_text(raw: bytes) -> tuple[str, str]:
    """按 ``_ENCODING_CHAIN`` 依次尝试解码，返回 ``(text, 实际编码名)``。

    BOM 的处理：``utf-8`` 严格解码对带 BOM 的文件是成功的（BOM 是一个
    合法码点 U+FEFF），所以链里第二个 ``utf-8-sig`` 几乎永远不会被触发。
    为保证文本干净，这里在解码成功后显式剥掉开头的 U+FEFF。
    （把这些编码全部失败的情况留给调用方是不可能的：``latin-1``
    对任意字节序列都成立，所以本函数不会抛异常。）
    """
    last_error: Exception | None = None
    for enc in _ENCODING_CHAIN:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError) as exc:  # LookupError：编码名不存在
            last_error = exc
            continue
        # utf-8-sig 会把 BOM 吃掉；其它编码路径手动剥一次，保证文本开头干净。
        if text.startswith("\ufeff"):
            text = text[1:]
        return text, enc
    # 理论上不可达（latin-1 全覆盖），保留显式失败分支以备将来改链。
    raise ExtractError(f"无法用任何候选编码解码该文件: {last_error}")


def _check_size(path: Path, max_bytes: int) -> int:
    """检查字节上限，返回文件大小。超限抛 :class:`ExtractTooLarge`。"""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ExtractError(f"无法读取文件元信息: {path}: {exc}") from exc
    if size > max_bytes:
        raise ExtractTooLarge(
            f"文件超过字节上限: {size} > {max_bytes} bytes ({path})"
        )
    return size


def _extract_plain_text(path: Path, *, max_bytes: int) -> tuple[str, str, str]:
    """读取 txt/md（含无扩展名）文件，返回 ``(text, source_kind, encoding)``。"""
    _check_size(path, max_bytes)
    raw = path.read_bytes()
    text, encoding = _decode_text(raw)
    # 统一换行：CRLF/CR → LF。理由：§6.3 的规范化只折叠空白，不处理 \r，
    # 若引文来自 HTML/PDF（无 \r）而正文保留了 \r，子串比较会出现假阴性。
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    suffix = path.suffix.lower()
    kind = "md" if suffix == ".md" else "txt"
    return text, kind, encoding


# --------------------------------------------------------------------------- #
# HTML：标准库剥标签
# --------------------------------------------------------------------------- #


class _HTMLTextExtractor(HTMLParser):
    """极简 HTML → 文本。只用标准库 ``html.parser``（不引入 bs4，见约束）。

    目标不是还原排版，而是拿到正文串，使引文可以在其中做子串匹配。
    两条关键规则：

    - ``script``/``style``/``head``/``noscript``/``template`` 里的内容是
      代码或元数据，不是正文，必须整棵子树跳过（因此用栈记录嵌套深度，
      而不是只判断当前 tag）。
    - 块级标签与 ``<br>`` 处补换行，否则相邻段落的文字会粘成一个句子，
      让"逐字引文"跨段匹配出语义错误的内容。
    """

    #: 需要整棵子树跳过的标签。
    _SKIP_TAGS: Final[frozenset[str]] = frozenset(
        {"script", "style", "head", "noscript", "template", "svg"}
    )
    #: 需要补换行（前后断开）的块级标签。
    _BLOCK_TAGS: Final[frozenset[str]] = frozenset(
        {
            "address", "article", "aside", "blockquote", "br", "dd", "div",
            "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
            "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
            "nav", "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot",
            "th", "thead", "tr", "ul",
        }
    )

    def __init__(self) -> None:
        # convert_charrefs=True：让解析器直接把 &amp;/&#x4e2d; 还原成字符，
        # 否则正文里会残留实体，导致引文与原文对不上。
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_stack.append(tag)
            return
        if tag in self._BLOCK_TAGS and not self._skip_stack:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        # 先处理"跳出被跳过子树"，顺序很重要：若先判断块级标签，
        # </script> 这种收尾会被当成块尾补一个多余换行。
        if self._skip_stack and tag == self._skip_stack[-1]:
            self._skip_stack.pop()
            return
        if tag in self._BLOCK_TAGS and not self._skip_stack:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_stack:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # 行尾空白与 3 个以上连续空行折叠掉：这些差异会干扰 §6.3 之外的
        # 下游启发式（如按空行切段），但不影响子串匹配（匹配前会规范化）。
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _strip_html(raw: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:  # 解析器容错：残缺 HTML 不应让整篇文献失败
        raise ExtractError(f"HTML 解析失败: {exc}") from exc
    return parser.get_text()


# --------------------------------------------------------------------------- #
# PDF：fitz → pdfminer → PyPDF2 回退链
# --------------------------------------------------------------------------- #


def _pdf_pages_fitz(path: Path, max_pages: int) -> tuple[list[str], list[str]]:
    """首选方案：PyMuPDF。抽出的文本层质量最好，且能可靠拿到页数。

    返回 `(pages, status)`（`F-4`）；`status[i]` 是 ``ok`` / ``empty``。
    PyMuPDF 的整篇抽取是原子的一步调用（没有逐页异常可以单独记），
    所以这里只会出现 `ok` / `empty` 两种。
    """
    import fitz  # 惰性：重依赖，且要允许未安装时回退

    with fitz.open(str(path)) as doc:
        total = int(doc.page_count)
        if total > max_pages:
            raise ExtractTooLarge(f"PDF 页数超过上限: {total} > {max_pages} ({path})")
        pages = [doc.load_page(i).get_text("text") or "" for i in range(total)]
    return pages, ["ok" if p.strip() else "empty" for p in pages]


def _pdf_pages_pdfminer(path: Path, max_pages: int) -> tuple[list[str], list[str]]:
    """次选方案：pdfminer.six。纯 Python，对个别 PDF 的排版还原比 fitz 好。

    返回 `(pages, status)`（`F-4`）。pdfminer 是逐页生成器，所以单页解析
    抛异常是可以单独记下来的：那一页记 ``failed`` 而不是插一个空串。
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextContainer

    laparams = LAParams()
    pages: list[str] = []
    status: list[str] = []
    for layout in extract_pages(str(path), laparams=laparams):
        if len(pages) >= max_pages:
            raise ExtractTooLarge(f"PDF 页数超过上限: >{max_pages} ({path})")
        # 只取顶层文本容器：pdfminer 会把文字按行/框组织，逐层递归拼接
        # 会重复计入（父容器已含子容器内容）。
        try:
            got = "".join(
                el.get_text() for el in layout if isinstance(el, LTTextContainer)
            )
        except Exception:
            pages.append("")
            status.append("failed")
            continue
        pages.append(got)
        status.append("ok" if got.strip() else "empty")
    return pages, status


def _pdf_pages_pypdf2(path: Path, max_pages: int) -> tuple[list[str], list[str]]:
    """末选方案：PyPDF2。兜底，抽取质量最弱，但覆盖面广。

    返回 `(pages, status)`：`status[i]` 是 ``ok`` / ``empty`` / ``failed``（`F-4`）。
    单页抛异常记 ``failed`` 而不再是"与空白页同形的空串" —— 两者在返回形态上
    必须能分开，否则引文校验会把"这页没抽出来"读成"这句话不在这页上"。
    """
    from PyPDF2 import PdfReader

    reader = PdfReader(str(path))
    total = len(reader.pages)
    if total > max_pages:
        raise ExtractTooLarge(f"PDF 页数超过上限: {total} > {max_pages} ({path})")
    pages: list[str] = []
    status: list[str] = []
    for page in reader.pages:
        try:
            got = page.extract_text() or ""
        except Exception:
            # 单页失败不该毁掉整篇：记为空串并记 failed，后续"全空 ⇒ 无文本层"
            # 的判断依然成立（fail-closed，不会伪造出内容）。
            pages.append("")
            status.append("failed")
            continue
        pages.append(got)
        status.append("ok" if got.strip() else "empty")
    return pages, status


def _sniff(raw: bytes) -> str:
    """读文件头几十字节判它到底是什么 ⇒ ``"pdf" | "html" | ""``（空串 = 看不出来）。

    为什么必须有它：调用方给的扩展名不是内容的证据。实测（真实数学文献的
    全文获取路径）两次 `extract_failed` 都是同一个形态：Crossref 链接返回的是
    HTML，落盘时被存成 `.bin`，而分派只看扩展名 ⇒ 直接判"格式不支持"。内容是
    完好的，失败的只是"我们按名字猜格式"这一步。

    判据刻意保持最窄的三条，每条都对应一种"内容与扩展名不符"的真实形态：

    - ``b"%PDF"`` ⇒ 走既有 PDF 回退链。放在最前：PDF 的魔数在文件第 0 字节，
      而后面两条判据要看开头，顺序反过来会让一份以声明开头的 PDF 走错路。
    - 开头（跳过 UTF-8 BOM 与空白）是 ``<!DOCTYPE`` / ``<html``，或 ``<?xml``
      且同一次读取里出现 ``<html`` ⇒ HTML。`<?xml` 单独不算：XHTML 是 HTML，
      而真正的 XML（如 JATS 全文）不是本模块承诺的格式，误判会让下游拿到
      "剥完标签什么都没有"的空正文。
    - 其余一律返回空串 ⇒ 调用方保持原有行为（按扩展名分派），所以本函数
      只可能把"原本会失败的分派"救回来，不会改变任何原本成功的路径。
    """
    head = raw[:_SNIFF_BYTES]
    if head.startswith(b"%PDF"):
        return "pdf"
    # 为什么要用 `errors="ignore"` 而不是让解码抛：这是一次嗅探，
    # 二进制垃圾（截断的 PDF、压缩流）必然混在这里，而"解不出字符"与
    # "内容不是 HTML"是同一件事 —— 不 ignore 就会让嗅探本身成为一条崩溃路径。
    text = head.decode("utf-8", "ignore")
    if text.startswith("\ufeff"):
        text = text[1:]
    probe = text.lstrip()
    low = probe.lower()
    if low.startswith("<!doctype") or low.startswith("<html"):
        return "html"
    if low.startswith("<?xml") and "<html" in low:
        return "html"
    return ""


def _pdf_pages(path: Path, max_pages: int) -> tuple[list[str], list[str], str]:
    """按 fitz → pdfminer → PyPDF2 顺序抽取，返回 ``(pages, status, 生效后端名)``。

    为什么每条链都重试而不是只认第一个：这三个库读同一份 PDF 的成功率并不
    一致（fitz 对加密/损坏文件更严格，pdfminer 对老式 Type3 字体更宽容）。
    失败原因会被逐条累积到异常信息里，方便定位是哪一层坏。

    注意：``ExtractTooLarge`` 直接上抛、不参与回退（`R6-AN-6`）：这是策略性拒绝，
    而不是"超限在三条链上都是免费的前置检查"—— 三条链各自判自己的上限
    （fitz 先 `fitz.open`、用 `doc.page_count` 判、判完才 `load_page`；
    pdfminer / PyPDF2 是已经启动解析、抽到上限才抛），所以对"页数被后端误报为
    超限的损坏文件"，回退确实会逐条诚实地失败；这里止住回退是不让一次拒绝在
    三条链上各付一次解析代价。

    `status` 是 `F-4` 的逐页三态（``ok`` / ``empty`` / ``failed``），与它同时
    返回的 `pages` 等长。注意下游 `_finish_pdf` 在"无文本层"那一支会把 `pages`
    置空而保留 `status` ⇒ 到了 `DocumentText` 那一层两者可以不等长（`R6-AN-2`）。
    """
    errors: list[str] = []
    for name, fn in (
        ("fitz", _pdf_pages_fitz),
        ("pdfminer", _pdf_pages_pdfminer),
        ("PyPDF2", _pdf_pages_pypdf2),
    ):
        try:
            pages, status = fn(path, max_pages)
            return pages, status, name
        except ExtractTooLarge:
            raise
        except Exception as exc:  # 记住失败原因后继续回退
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    raise ExtractError(f"所有 PDF 后端均失败 ({path}): " + " | ".join(errors))


def page_count(path: Path | str) -> int | None:
    """只数页数，不抽全文（供报告/预览用，成本远低于 ``extract_text``）。

    - 非 PDF（txt/md/html）⇒ ``None``：文本类文件没有"页"这个概念，
      返回 ``1`` 会诱导调用方以为页码可定位。
    - 读取失败 ⇒ ``None``：这是诊断性函数，失败不该让调用方崩溃；
      真要失败详情请调 ``extract_text``（它会抛出带原因链的异常）。
    """
    p = Path(path)
    if p.suffix.lower() != ".pdf":
        return None
    try:
        import fitz

        with fitz.open(str(p)) as doc:
            return int(doc.page_count)
    except Exception:  # fitz 缺失或读不了这份 PDF ⇒ 回退下一个后端（全都失败则返回 None）
        pass
    try:
        from PyPDF2 import PdfReader

        return len(PdfReader(str(p)).pages)
    except Exception:  # PyPDF2 也不成 ⇒ 再试 pdfminer；这是诊断性函数，失败即 None
        pass
    try:
        from pdfminer.pdfpage import PDFPage

        with p.open("rb") as fh:
            return sum(1 for _ in PDFPage.get_pages(fh))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def _page_status_of(pages: Sequence[str], status: Sequence[str] | None,
                    *, expected: int | None = None,
                    backend: str = "?") -> tuple[str, ...]:
    """逐页三态。后端给了（且长度对得上）就用它的；否则按内容推。

    抽出来是为了让 `_finish_pdf` 的两支共用同一条长度校验规则：旧版只在"有文本层"
    那一支用它，无文本层那一支硬写空元组 —— 那正是 `R3-2`（整篇抽取失败被
    报成"疑似扫描件"）的成因。`R6-AN-5` 补一句：两支传的 `expected` 不同
    （无文本支要给，正常支不传，见下一段），相同的只是"长度校验"这一步，
    不是"两支走完全相同的路径"。

    `expected` 用来处理一个故意留下的小错位：无文本层时 `pages` 被置空（§6.3 契约），
    而后端给的 `status` 仍然与**真实页数**等长。此时不能因为"长度与 `pages` 不等"
    就把整份状态丢掉 —— 那正是被修掉的那个缺陷。给了 `expected` 就按它比长度。

    `R3-8`：长度确实对不上时**不许静默降级**。旧版在这里无声地改按内容推，
    于是后端上报的 `failed` 凭空消失、回到"真引文被判成幻觉"的那条路径，
    而没有任何信号（重审实测：`_finish_pdf(['第一页','','第三页'], 'PyPDF2', ['ok'])`
    ⇒ `page_status=('ok','empty','ok')`、`failed_pages=()`）。
    现在留一条 warning（带 backend 与两个长度）—— 按内容推仍然是结论
    （抛异常会让"后端少报一页状态"变成整篇抽取失败，代价更大），
    但它是"被记录过的降级"，可以被断言、也可以被人看见。
    """
    materialized = [str(page) for page in pages]
    if status is not None:
        n_want = len(materialized) if expected is None else int(expected)
        if len(status) == n_want:
            return tuple(str(s) for s in status)
        logger.warning(
            "后端 %s 给的逐页状态与页数不符（status=%d 项，期望 %d 项，pages=%d 页）"
            "⇒ 本次按内容推逐页状态（ok/empty）：后端上报的 failed 会因此丢失，"
            "`R3-8` 记的就是这个形态（`failed_pages` 这一层可能被判成『没有失败页』）",
            backend, len(status), n_want, len(materialized),
        )
    # 后端没给状态（或给的长度确实对不上）⇒ 按内容推：这与旧行为一致，
    # 不会凭空制造"这一页不可读"。
    return tuple("ok" if p.strip() else "empty" for p in materialized)


def _finish_pdf(pages: Sequence[str], backend: str,
                status: Sequence[str] | None = None) -> DocumentText:
    """统一的收尾：判断无文本层 + 拼接全文。

    "无文本层"的判据是所有页去空白后都为空，而不是"某一页为空"：
    正常 PDF 里插图页/章节扉页常常没有文字，把它误判成扫描件会让整篇文献
    的引文全部落到 ``quote_verified=null``，代价过大。

    `status` 是逐页三态（`F-4`）；不给时按"空 ⇒ empty、非空 ⇒ ok"推出来 ——
    这与旧行为逐字一致（"没有 failed 这个概念"），所以调用方不传它不会变严。
    """
    if not pages or all(not page.strip() for page in pages):
        # 无文本层：pages=[] 是给 agent_b 的信号（§6.3），
        # source_kind 仍保持 "pdf"，好让报告能区分"扫描版 PDF"与"非 PDF"。
        #
        # `R3-2`（重审实测的修法）：逐页状态**必须带出去**。
        # 旧版在这里无条件写 `page_status=()`，于是"整篇每一页都抽取失败"这一档
        # 在 `failed_pages()` 眼里是"没有失败的页" ⇒ `ocr_tools` 里专为
        # "抽取失败"写的那一支（`失败原因是抽取失败`）成了**死代码**，
        # 工具把"我们的后端在这份文件上全崩了"报成"疑似扫描件（本来就是空白页）"，
        # 而这两种情况的处置完全不同（换后端重试 vs 走 OCR）。
        #
        # 为什么仍然置 `pages=()`：那是 §6.3 的契约（`agent_b` 据此把
        # `quote_verified` 置 null），改它会把下游整片改掉；而"哪些页不可读"
        # 本来就由 `page_status` 承载。注意这里两者是刻意不等长的（`R6-AN-2`：
        # `page_status` 记的是后端上报的真实页数，`pages` 是空元组），所以要读
        # 就用 `page_status` / `failed_pages()`，不要拿 `pages` 的长度去索引它
        # —— 空 `pages` 会让按它兜底的读者静默读空。两者分开正是 `F-4` 的用意。
        # `R3B-2`（第二轮复审实测）：日志行必须和工具面一样**分开这两件事**。
        # 旧版无论哪一种都打同一句「PDF 无文本层（疑似扫描件）」——
        # 于是"我们的抽取链在这份文件上全崩了"与"它本来就是扫描件"
        # 在日志里长得一模一样（`ocr_tools` 那边已经分开，日志这边还没有）。
        status_now = _page_status_of(pages, status, backend=backend,
                                     expected=len(pages) or (len(status) if status else 0))
        n_failed = sum(1 for s in status_now if s == "failed")
        if n_failed:
            logger.warning(
                "PDF 无文本层，且原因是**抽取失败**（不是扫描件）：后端=%s，"
                "%d/%d 页在抽取时抛了异常 ⇒ pages 置空、逐页状态保留为 %d 个 failed",
                backend, n_failed, len(status_now), n_failed,
            )
        else:
            logger.info("PDF 无文本层（疑似扫描件：每页去空白后都为空），后端=%s：pages 置空",
                        backend)
        # `expected`：`pages` 为空但 `status` 非空时（"后端一页都没返回、但逐页状态还在"），
        # 长度按状态自己算 —— 不能因为"与空的 pages 不等长"就把状态丢掉。
        return DocumentText(text="", pages=[], source_kind="pdf", encoding=None,
                            page_status=status_now)
    logger.debug("PDF 抽取成功：后端=%s 页数=%d", backend, len(pages))
    materialized = [str(page) for page in pages]
    return DocumentText(
        text="\n".join(materialized),
        pages=materialized,
        source_kind="pdf",
        encoding=None,
        page_status=_page_status_of(materialized, status, backend=backend),
    )


def extract_text(
    path: Path | str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> DocumentText:
    """按内容（魔数/头部嗅探）与扩展名分派抽取，返回逐页 :class:`DocumentText`。

    - 内容以 ``%PDF`` 开头：fitz → pdfminer → PyPDF2 回退链，保留逐页文本。
    - 内容以 ``<!DOCTYPE`` / ``<html``（或带 ``<html`` 的 ``<?xml``）开头：
      把字节按 ``_ENCODING_CHAIN`` 解码后走 HTML 剥标签路径；`source_kind` 为
      ``"html"``（无扩展名的快照只在这里被识别出来）。扩展名不在
      `_HTML_SUFFIXES` 里（例如 `.bin`）⇒ 抛 :class:`HtmlNotSupported`，
      理由里写清"内容确实是 HTML"以及怎么处理。
    - ``.pdf``：仍走 PDF 回退链（内容嗅探也认过的，两条路等价）。
    - ``.txt`` / ``.md`` / 无扩展名：按 ``_ENCODING_CHAIN`` 解码，``pages=[全文]``。
    - ``.html`` / ``.htm`` / ``.xhtml``：标准库剥标签，``pages=[全文]``。
    - 其余：抛 :class:`UnsupportedFormat`（§4.1 只承诺这四类）。

    文本类文件同样保留 ``pages=[全文]``：让"有文本层"这一判断在所有格式上
    都退化成同一个表达式（``bool(pages)``），而不是每个调用点各写一套
    ``if kind == "pdf"`` 分支——分支越多，§6.3 漏判的可能性越大。

    超限抛 :class:`ExtractTooLarge`，不截断（理由见模块 docstring 第 3 条）。
    内容嗅探只读文件头的 :data:`_SNIFF_BYTES` 字节：它**只影响原本会被判成
    "不支持的扩展名"的那些文件**，已经能成功的路径一字未动。
    """
    p = Path(path)
    if not p.exists():
        raise ExtractError(f"文件不存在: {p}")
    if not p.is_file():
        raise ExtractError(f"不是普通文件: {p}")

    suffix = p.suffix.lower()
    _check_size(p, max_bytes)

    # ---- 内容嗅探（扩展名不是内容的证据，见 `_sniff`）
    with open(p, "rb") as fh:
        head = fh.read(_SNIFF_BYTES)
    sniffed = _sniff(head)
    if sniffed == "html":
        text, kind, encoding = _extract_plain_text(p, max_bytes=max_bytes)
        body = _strip_html(text)
        if suffix in _HTML_SUFFIXES:
            if not body.strip():
                return DocumentText(text="", pages=[], source_kind="html", encoding=encoding)
            return DocumentText(text=body, pages=[body], source_kind="html", encoding=encoding)
        raise HtmlNotSupported(
            f"内容按魔数判定为 HTML（开头是 {head[:64]!r}），但扩展名是 {suffix!r}（{p}）。"
            "这不是'格式不认识'：正文就在文件里，把它按 .html/.htm 落盘即可走 HTML 抽取路径"
            "（扩展名是这里唯一的判据，本模块不改写调用方的文件名）。"
        )
    if sniffed == "pdf" or suffix == ".pdf":
        pages, status, _backend = _pdf_pages(p, max_pages)
        return _finish_pdf(pages, _backend, status)

    if suffix in _TEXT_SUFFIXES or suffix == "":
        text, kind, encoding = _extract_plain_text(p, max_bytes=max_bytes)
        if not text.strip():
            return DocumentText(text="", pages=[], source_kind=kind, encoding=encoding)
        return DocumentText(
            text=text, pages=[text], source_kind=kind, encoding=encoding
        )

    raise UnsupportedFormat(f"不支持的扩展名: {suffix!r} ({p})")


# --------------------------------------------------------------------------- #
# 自检：cd <test1>/src && python -m agentflow.extract
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    # 本文件即 __main__，因此上面定义的名字（extract_text / page_count / …）
    # 直接可用，不要再 `from .extract import ...`，否则会加载出第二份模块实例。
    import json
    import sys
    from dataclasses import asdict, is_dataclass

    try:  # Windows 控制台/管道下强制 utf-8，避免中文输出报编码错
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    DEMO = Path(__file__).resolve().parents[2] / "demo" / "selftest"
    DEMO.mkdir(parents=True, exist_ok=True)
    pdf_path = DEMO / "sample.pdf"
    blank_path = DEMO / "blank.pdf"

    print("=" * 72)
    print("[1] 用 fitz 现造 3 页 PDF（每页一句，第 2 页含定义句）")
    import fitz

    pdf = fitz.open()
    lines = [
        "Group theory studies algebraic structures.",
        "An abelian group is a group in which the commutative law holds.",
        "The identity element is unique in every group.",
    ]
    for line in lines:
        page = pdf.new_page()
        page.insert_text((72, 96), line, fontsize=12)
    pdf.save(str(pdf_path))
    pdf.close()
    print(f"    saved: {pdf_path}")

    print("[2] extract_text(sample.pdf)")
    dt = extract_text(pdf_path)
    print(
        f"    source_kind={dt.source_kind}  pages={len(dt.pages)}"
        f"  has_text_layer={dt.has_text_layer}  page_count()={page_count(pdf_path)}"
    )
    for i, page in enumerate(dt.pages):
        print(f"    p{i + 1} 前60字符: {page.strip()[:60]!r}")

    print("[3] RuleExtractor 抽取 + quote 逐条回验")
    seed = [
        {"name": "group", "definition": "a set with a binary operation", "aliases": ["groups"]},
        {"name": "commutative law", "definition": "", "aliases": []},
    ]
    from .llm import RuleExtractor  # type: ignore[import-not-found]

    concepts, relations = RuleExtractor().extract(dt, "0000", {"seed_concepts": seed})
    print(f"    concepts={len(concepts)} relations={len(relations)}")
    for c in concepts:
        print(f"    C: {c.name!r} | def={c.definition[:44]!r} | aliases={c.aliases}")
    all_ok = True
    for r in relations:
        ok = r.quote in dt.text
        all_ok = all_ok and ok
        pr = asdict(r.page_range) if is_dataclass(r.page_range) else r.page_range
        print(
            f"    R: names={r.concept_names} page_range={pr}"
            f" quote_in_text={ok} quote={r.quote[:64]!r}"
        )
    print(f"    >>> 所有 quote 均为原文子串: {all_ok}")

    print("[4] 空白 PDF（模拟扫描版无文本层）")
    blank = fitz.open()
    blank.new_page()
    blank.new_page()
    blank.save(str(blank_path))
    blank.close()
    bdt = extract_text(blank_path)
    print(f"    source_kind={bdt.source_kind} pages={bdt.pages!r} text={bdt.text!r}")
    print(f"    >>> pages == [] : {bdt.pages == []}   has_text_layer={bdt.has_text_layer}")
    b_concepts, b_relations = RuleExtractor().extract(bdt, "0001", {"seed_concepts": seed})
    print(
        f"    RuleExtractor on blank: concepts={len(b_concepts)}"
        f" relations={len(b_relations)}  (期望 2/0：种子概念照给、关系 0 条)"
    )

    print("[5] text_at 边界语义 + 异常路径")
    print(f"    text_at(2,2) 第2页: {dt.text_at(2, 2).strip()[:50]!r}")
    print(f"    text_at(0,999) 收窄到全部页 长度={len(dt.text_at(0, 999))} 全文长度={len(dt.text)}")
    print(f"    text_at(9,9) 越界 => {dt.text_at(9, 9)!r}")
    print(f"    text_at(5,2) 反向 => {dt.text_at(5, 2)!r}")
    print(f"    text_at(None,None) => {dt.text_at(None, None)!r}  (刻意返回空串，见 docstring)")
    print(f"    blank.text_at(1,1) => {bdt.text_at(1, 1)!r}")
    try:
        # 先落一个真实文件：extract_text 先查存在性再查格式（存在性是更根本的错误）
        (DEMO / "nope.docx").write_bytes(b"PK\x03\x04 fake docx")
        extract_text(DEMO / "nope.docx")
    except UnsupportedFormat as exc:
        print(f"    >>> 不支持的扩展名抛 UnsupportedFormat: {exc}")
    try:
        extract_text(pdf_path, max_pages=1)
    except ExtractTooLarge as exc:
        print(f"    >>> 超限抛 ExtractTooLarge: {exc}")
    try:
        extract_text(DEMO / "missing.pdf")
    except ExtractError as exc:
        print(f"    >>> 文件不存在抛 ExtractError: {exc}")

    print("[6] 文本类文件：编码回退与 HTML 剥标签")
    txt_path = DEMO / "sample_zh.txt"
    txt_path.write_bytes("一个群是一个带有二元运算的集合。".encode("gb18030"))
    tdt = extract_text(txt_path)
    print(f"    gb18030 txt: encoding={tdt.encoding} pages={len(tdt.pages)} text={tdt.text!r}")
    html_path = DEMO / "sample.html"
    html_path.write_text(
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>An abelian group is a group in which the commutative law holds.</p>"
        "<script>var x = 1;</script></body></html>",
        encoding="utf-8",
    )
    hdt = extract_text(html_path)
    print(f"    html: source_kind={hdt.source_kind} text={hdt.text!r}")
    print(f"    >>> 脚本/样式已剔除: {'var x' not in hdt.text and 'color:red' not in hdt.text}")

    print("[7] LLMExtractor 回验：用会编引文的假 client 验证 fail-closed")
    from .llm import ExtractionError, LLMExtractor, NullExtractor, parse_llm_json

    class _FakeClient:
        """模拟两类模型行为：一条真引文（换行被抄成空格）+ 一条凭空捏造的引文。"""

        def complete(self, prompt: str) -> str:
            assert "{DOCUMENT_TEXT}" not in prompt and "<<<PAGE 1>>>" in prompt
            return (
                "好的，结果如下：\n```json\n"
                + json.dumps(
                    {
                        "concepts": [
                            {
                                "name": "abelian group",
                                "definition": "a group with commutative law",
                                "aliases": [],
                            }
                        ],
                        "relations": [
                            {
                                "concept_names": ["abelian group", "group"],
                                "description": "定义阿贝尔群",
                                "quote": "An abelian group is a group in which the\ncommutative law holds.",
                                "page_range": {"start": 2, "end": 2},
                            },
                            {
                                "concept_names": ["abelian group", "magic"],
                                "description": "编造的关系",
                                "quote": "An abelian group is always finite and cyclic.",
                                "page_range": {"start": 2, "end": 2},
                            },
                            {
                                "concept_names": ["only one"],
                                "description": "概念数不足",
                                "quote": "Group theory studies algebraic structures.",
                                "page_range": {"start": 1, "end": 1},
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n```\n希望有帮助！"
            )

    le = LLMExtractor(_FakeClient())
    c2, r2 = le.extract(dt, "0000", {})
    print(f"    concepts={len(c2)} relations={len(r2)} report={le.last_report}")
    for r in r2:
        print(f"    R kept: 字面子串={r.quote in dt.text} quote={r.quote!r}")
    print(f"    >>> 2 条问题引文被剔除且计数正确: {le.last_report['relations_dropped'] == 2}")
    print(f"    >>> 剔除原因: {le.last_report['drop_reasons']}")
    print(
        "    >>> 无文本层时 LLMExtractor 直接返回空（不调用模型）: "
        f"{LLMExtractor(_FakeClient()).extract(bdt, '0001', {}) == ([], [])}"
    )
    print(f"    >>> NullExtractor: {NullExtractor().extract(dt, '0000', {})}")
    _messy = '前言\n```json\n{"a": 1,}\n```\n后记'
    print(f"    >>> 围栏/寒暄容忍: {list(parse_llm_json(_messy))}")
    try:
        parse_llm_json("这不是 JSON")
    except ExtractionError as exc:
        print(f"    >>> 解析失败抛 ExtractionError: {type(exc).__name__}")

    print("=" * 72)
    print("SELF-CHECK DONE")
