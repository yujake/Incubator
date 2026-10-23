"""引文回验的「证据叶子」：三态结论必须带上可以复核的那几栏（D1 的落点）。

## 为什么单独成模块

真机读数（`saxl-ws/data/statements.json`，2026-10-22 修复前）：8 条命题写着
`quote_verified=true` / `quote_mode=verbatim`，而 `quote_span` / `quote_reason` /
`quote_call_sha256` 三栏全是空串。于是"逐字回验通过"这句话在盘上没有任何读数：
核了哪一段、在第几页、是逐字命中还是归一化后命中、有没有花模型钱，一条都读不出来。

追下去是三个洞，一个都不在 `quoteverify.py`（那是禁改区，且它本身判得没错 ——
它会把 `matched_page` / `window` / `reason` 如实回报）：

1. 对命题（`statements`）而言，根本没有回验这一步：`quote_verified` 是模型自报的入参；
2. `schema._normalize_quote_mode` 会把"只说通过、没说方式"的行记实成 `verbatim`
   —— 它的前提是"那时 `True` 只可能来自逐字那一档"，而自报把那个前提弄假了；
3. 秘书那一层（`Secretary._statement_from`）只搬了 `quote_verified` / `quote_reason`，
   `quote_mode` / `quote_span` / `quote_call_sha256` 被白名单收下又被静默丢掉 ⇒
   即使 H 的语义判定给出了 span 与调用指纹，也到不了盘上。

本模块补的是"调动方"那一半：

- :func:`verify_quote_evidence` 用禁改区那一个 `quoteverify.check_quote` 判，再把判决
  翻成落盘需要的四栏（区间、方式、理由、调用指纹）；
- :func:`enforce_quote_evidence` 是写侧断言：说"逐字通过"就必须在这一次写里定位出
  区间，否则降成 unknown 档（不是 false、也不是 true）；"有理由、没区间"同样降档 ——
  理由不是证据（D1 的第二版口径，见该函数 docstring 的"为什么理由不够"一节）；
- :func:`scan_quote_evidence` 是读侧判据：扫盘上所有行，把"说通过而拿不出区间"的行
  逐条点名（历史脏数据因此不会被当成通过放过）。

## 区间口径（`quote_span`）

`p{页号}:norm[{起}:{止}]`：页号从 1 起；起止是该页文本经
`textutil.normalize_for_quote` 归一化之后的字符偏移，含头不含尾。为什么用归一化后的
偏移而不是原文字符偏移：判据本身就是在归一化后的文本上做的（`check_quote` 的
`q in normalize_for_quote(page)`），偏移落在同一个坐标系里才复现得出来 —— 复核的人
拿同一个函数把那一页归一化一次，切片就应当逐字等于归一化后的引文。写原文字符偏移
反而要再造一份"归一化 ⇒ 原位置"的映射，那是同一件事的第二份实现。

`quote_call_sha256` 只有语义那一档（模型判过）才有值。逐字档是纯文本比对，
没有模型调用（不是"忘了记"），这一栏留空；:func:`enforce_quote_evidence` 会把
"确实没有调用"写进 `quote_reason` —— 空栏不加说明时，读的人分不清"没调用"与"忘了记"。

## 「无来源可核」那一档（业主 2026-10-22 裁定 B-4）

`quote_reason` 里出现 `no_source` / `无来源` 这一类记号，说的是"这条引文没有外部原文
可核"。裁定原文：「所谓"无来源可核"却仍然写上去了，一定有我方研究手稿当背书 ⇒
no_source 这一档必须指向"我方手稿里的哪一处"」。于是这一档从一句理由变成一条判据：

- 写侧（:func:`enforce_quote_evidence`）：出现这一档却没给背书位置 ⇒ 受控拒绝
  `no_source_without_backing`，整笔不写；
- 读侧（:func:`no_source_state` / :func:`no_source_reading`）：四态分开数 ——
  `no_source_backed`（有背书）/ `no_source_unbacked`（写了这一档却没背书）/
  `no_source_absent`（该写理由而一个字没写）/ `not_applicable`（概念行）。

四态分立的理由与三态同一条：把这四件事折成"假"或"未查"两个词，读的人会去追一条
根本不存在的欠账（概念行本来就不该有引文），或者放过一条真的没有来路的断言。
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from . import quoteverify as _QV
from .schema import PageRange
from .textutil import normalize_for_quote

#: 归一口径的名字（写进 reason，读的人据此复现区间）。
SPAN_SCHEME = "p{page}:norm[{start}:{end}]"

#: 逐字档的 `quote_call_sha256` 为什么可以是空的（写进 reason）。
NO_CALL_NOTE = "没有模型调用（逐字档是纯文本比对）⇒ quote_call_sha256 留空"

#: 三态里"没查成"那一档的理由前缀（读侧/写侧都用它，免得两处措辞分家）。
UNKNOWN_NOTE = "unknown：没查成 ≠ 查过不存在"

#: 「无来源可核」那一档在 `quote_reason` 里的记号（业主 2026-10-22 裁定 B-4）。
#:
#: 这一档说的是"这条引文拿不到外部原文可核"（原文不在盘上 / 只有元数据 / 来源被指认
#: 不可信）。裁定原文：「所谓"无来源可核"却仍然写上去了，一定有我方研究手稿当背书
#: ⇒ no_source 这一档必须指向"我方手稿里的哪一处"」。所以它不是一个可以单独成立的
#: 理由：出现它就同时要有背书位置，否则由 :func:`enforce_quote_evidence` 受控拒绝
#: （`no_source_without_backing`）。
NO_SOURCE_MARKERS: tuple[str, ...] = (
    "no_source", "无来源可核", "无来源", "没有来源可核", "没有来源",
    "无出处可核", "查无来源",
)

#: 背书位置的第一种写法（裁定给的例子）：`manuscripts/handoffs.jsonl#NNNN`。
BACKING_HANDOFF = re.compile(r"manuscripts/handoffs\.jsonl\s*#\s*\d+")

#: 背书位置的第二种写法：`out/paper/main.tex` 的某一节（文件 + 定位标记两件都要）。
BACKING_PAPER = re.compile(r"out/paper/main\.tex")
_PAPER_LOCATOR = re.compile(
    r"(§\s*\d|第\s*[0-9一二三四五六七八九十]+\s*节|sec:|section|#L?\d+|\\section)")

#: 背书位置的第三种写法：`stmt:` 编号（台账里那一行就是"我们说过什么"的落点）。
BACKING_STMT = re.compile(r"stmt:\s*\d{4,}")

#: 四态的受控取值（`no_source` 那一族 + 概念行的"不适用"）。
#:
#: 为什么单独给它们四个名字：改前概念行与"无来源可核"的行在读数里都被折成
#: `mismatch`（假）或 `unchecked`（未查）—— 而"这一行不该有引文"与"这一行没查"
#: 是两件事，把它们印成同一个词，读的人会去追一条根本不存在的欠账。
NO_SOURCE_BACKED = "no_source_backed"
NO_SOURCE_UNBACKED = "no_source_unbacked"
NO_SOURCE_ABSENT = "no_source_absent"
NOT_APPLICABLE = "not_applicable"

#: 概念行的 kind（这一档的引文"不适用"：概念不参与引文回验，见 `specs/b.py`）。
_CONCEPT_KIND = "concept"


def declares_no_source(text: Any) -> bool:
    """这段理由有没有走「无来源可核」那一档。"""
    body = str(text or "")
    return any(marker in body for marker in NO_SOURCE_MARKERS)


def manuscript_backing(text: Any) -> str:
    """这段文字里指出的"我方手稿里的哪一处"（原样返回命中的那一段）；没有则空串。

    只认三种写法（业主裁定逐字给的那三条路线，不多认一种）：

    - `manuscripts/handoffs.jsonl#NNNN`：交接手稿账本的第几行；
    - `out/paper/main.tex` + 一处定位（`§3` / `第 2 节` / `sec:` / `#L12`）：正文的哪一节；
    - `stmt:` + 编号：命题台账里那一行。

    为什么"文件在场"不算：`out/paper/main.tex` 有几百行，只写文件名指不到"哪一处"，
    与"没有背书"在复核时是一样的（读的人仍然要在整篇里找）。
    """
    body = str(text or "")
    for pattern in (BACKING_HANDOFF, BACKING_STMT):
        found = pattern.search(body)
        if found:
            return found.group(0)
    if BACKING_PAPER.search(body) and _PAPER_LOCATOR.search(body):
        locator = _PAPER_LOCATOR.search(body)
        return f"out/paper/main.tex{locator.group(0) if locator else ''}"
    return ""


def no_source_state(row: Mapping[str, Any]) -> str:
    """这一行的「无来源/不适用」四态读数（空串 = 不属于这四态，走三态那一套）。

    四态（业主 2026-10-22 裁定 B-4 的三档 + 概念行那一档）：

    - `not_applicable`：概念行（`kind="concept"`）—— 概念不参与引文回验，
      既不是"假"也不是"未查"；
    - `no_source_backed`：理由走了「无来源可核」那一档，且给了我方手稿的位置；
    - `no_source_unbacked`：理由走了那一档，却没有给位置（写入期已被拒，
      盘上这一档只可能是历史行）；
    - `no_source_absent`：`quote_verified` 不是 True，而理由一个字都没写
      （说不出是哪一档 ⇒ 这一格"没写理由"就是它的读数）。

    概念行先判：概念行的 `quote_verified` 恒为 None，若不先摘出去，它会永远落在
    `no_source_absent` 那一格里，把"不适用"印成"没写理由"。
    """
    if str(row.get("kind") or "") == _CONCEPT_KIND:
        return NOT_APPLICABLE
    if row.get("quote_verified") is True:
        return ""
    reason = str(row.get("quote_reason") or "").strip()
    if not reason:
        return NO_SOURCE_ABSENT
    if not declares_no_source(reason):
        return ""
    return NO_SOURCE_BACKED if manuscript_backing(reason) else NO_SOURCE_UNBACKED


def no_source_reading(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """四态各自的行数（`no_source` 那一族 + 概念行），读数用。

    `no_source_absent` 是"该说说不出"的那一档（见 :func:`no_source_state`）——
    它与 `no_source_unbacked` 分开数：前者是"没写理由"，后者是"写了理由但指不到
    我方手稿的哪一处"。两种欠账的处置不同（补理由 / 补背书），混成一个数就看不出来。
    """
    counts = {NO_SOURCE_BACKED: 0, NO_SOURCE_UNBACKED: 0, NO_SOURCE_ABSENT: 0,
              NOT_APPLICABLE: 0}
    for row in rows:
        state = no_source_state(row)
        if state in counts:
            counts[state] += 1
    return counts



def span_text(page: int, start: int, end: int) -> str:
    """拼一个区间串（`SPAN_SCHEME` 的格式）。"""
    return SPAN_SCHEME.format(page=int(page), start=int(start), end=int(end))


def locate_span(doc: Any, quote: str, *, page: int | None = None) -> str:
    """在文档里定位引文，返回区间串；定位不到返回空串。

    判据与 `quoteverify.check_quote` 逐字相同（同一个 `normalize_for_quote`、同样的
    "归一化后是不是子串"），只是把命中的位置也留下来。`page` 是 `check_quote` 已经
    回报的命中页：先试它，再按页序找（调用方给不出命中页时说"不知道在哪一页"）。
    定位不到就返回空串，不猜一个页码 —— 猜出来的区间比没有区间更坏。
    """
    q = normalize_for_quote(str(quote or ""))
    if not q:
        return ""
    pages = list(getattr(doc, "pages", None) or [])
    if not pages:
        return ""
    hint = int(page or 0)
    order = ([hint] if hint > 0 else []) + [p for p in range(1, len(pages) + 1) if p != hint]
    for p in order:
        if p < 1 or p > len(pages):
            continue
        norm = normalize_for_quote(pages[p - 1])
        at = norm.find(q)
        if at >= 0:
            return span_text(p, at, at + len(q))
    return ""


#: 区间串的解析式（:func:`span_text` 的逆）。格式只由 :data:`SPAN_SCHEME` 定义一次，
#: 解析也只在这里定义一次 —— 两处各写一份正则会造出"能写不能读"的区间。
_SPAN_RE = re.compile(r"^p(\d+):norm\[(\d+):(\d+)\]$")


def parse_span(span: Any) -> tuple[int, int, int] | None:
    """解析区间串 ⇒ `(页号, 起, 止)`；认不出就返回 `None`（绝不猜一个位置）。"""
    found = _SPAN_RE.match(str(span or "").strip())
    if not found:
        return None
    page, start, end = (int(x) for x in found.groups())
    if page < 1 or start < 0 or end < start:
        return None
    return page, start, end


def span_of(row: Mapping[str, Any]) -> str:
    """一行里的区间（去首尾空白）。读侧判"这一行有没有可复核的位置"只认这一处。"""
    return str(row.get("quote_span") or "").strip()


def call_of(row: Mapping[str, Any]) -> str:
    """一行里的调用指纹（去首尾空白）。语义档的第二件证据。"""
    return str(row.get("quote_call_sha256") or "").strip()


def span_slice(doc: Any, span: Any) -> tuple[str, int]:
    """按区间串去文档里切那一段 ⇒ `(片段, 页号)`；切不出来返回 `("", 0)`。

    越界就是切不出来，不做收窄：`p9:norm[0:10]` 出现在一份三页的文档上，说明写这个
    区间的人看的不是这一份 —— 收窄之后切出来的那十个字会看起来像"核过了"。

    为什么要有这一层：入参里的 `quote_span` 可能是调用方自报的定位（或 H 判时对着的
    那一段原文）。真要比对就得拿它去文档里取一次；取不到就说明这个区间不成立，
    这件事必须在写侧变现成降档，而不是原样落盘。
    """
    parsed = parse_span(span)
    if parsed is None:
        return "", 0
    page, start, end = parsed
    pages = list(getattr(doc, "pages", None) or [])
    if page > len(pages):
        return "", 0
    norm = normalize_for_quote(pages[page - 1])
    if end > len(norm):
        return "", 0
    return norm[start:end], page


def _page_range(raw: Any) -> Any:
    """把调用方可能给的页码形状归一成 `PageRange`（dict 也收，读侧不许因类型炸）。"""
    if isinstance(raw, Mapping):
        return PageRange.from_dict(raw)
    return raw


def _declared_label(page_range: Any) -> str:
    """声明窗口的人话（写在 reason 里，读的人一眼看到"查的是哪几页"）。"""
    pr = _page_range(page_range)
    known = bool(getattr(pr, "known", False))
    if not known:
        return "页码未声明"
    start = getattr(pr, "start", None)
    end = getattr(pr, "end", None)
    if end is None:
        return f"第 {start} 页"
    return f"第 {start}-{end} 页"


def _unknown_reason(check: Any, page_range: Any, field: str) -> str:
    """`check_quote` 判"没法判"的那几档 ⇒ 一句可读的理由（不许折成"不存在"）。"""
    code = str(getattr(check, "reason", "") or "")
    where = _declared_label(page_range)
    base = f"{UNKNOWN_NOTE}（{code}）："
    if code == "no_text_layer":
        return (base + "这一篇没有可读文本（抽取失败 / 扫描版没有文本层 / 还没抽）⇒ "
                f"没法拿 {field or '引文'} 逐字比对，按 unknown 记 —— 不是 false："
                "没读到不等于原文里没有")
    if code == "page_unreadable":
        return (base + f"{where}里有抽取失败的页（读不到那几页的文本）⇒ 不判 not_found；"
                "要 OCR 或换一份可读的全文再查")
    if code == "page_status_unknown":
        return (base + "逐页状态取不到（读页状态的那一步抛了异常）⇒ 连'那一页能不能读'"
                "都不知道，按 unknown 记")
    if code == "empty_quote":
        return base + "引文本身是空的（归一化后没有字）⇒ 没有可比的字符串"
    if code == "empty_page_range":
        return (base + f"声明的窗口是空的（{where}，start > end）⇒ 区间里不可能有页，"
                "'在这段里没找到'没有信息量")
    return base + f"理由码 {code or '空'}（这一档没有对应的可读解释）"


def _miss_reason(check: Any, page_range: Any, field: str) -> str:
    """判"没命中"的那一档 ⇒ 可操作的理由（点名查过哪几页）。"""
    where = _declared_label(page_range)
    tried = "/".join(str(t) for t in (getattr(check, "tried", ()) or ()))
    return (f"逐字没命中（{str(getattr(check, 'reason', '') or 'not_found')}）：引文不在声明的"
            f"{where}，归一化之后也不匹配（试过的窗口：{tried or '无'}）⇒ 要么页码错、"
            f"要么引文被改写或编造；{field or '引文'} 要改哪一边由人判。{NO_CALL_NOTE}")


def _no_hit_reason(*, reason: str, page_range: Any = None, field: str = "",
                   note: str = "", pages: int = 0) -> str:
    """整份全文里都定位不到那一段 ⇒ 判"查过了、不一致"的理由（不是 unknown）。

    这一档与 :func:`_no_span_reason` 是两件不同的事，措辞必须分得开：这里读到了全文，
    所以"找不到"是一条有信息量的结论（引文被改写 / 页码或来源给错），落 `False`；
    那边一次比对都没发生（没有全文 / 没有可读的页 / 没有要比对的那一段），落 `None`。
    把前者写成 unknown 会丢掉一条已经查实的读数；把后者写成 false 会指控一条真引文
    （本仓库最贵的方向）。
    """
    where = _declared_label(page_range)
    said = ""
    if str(reason or "").strip():
        said += (f"；这一笔交来的 quote_reason 是 {str(reason)[:120]!r}"
                 "（它说通过，而这一次重核在全文里找不到那一段）")
    if str(note or "").strip():
        said += f"；这一笔核的是{note}"
    return (f"逐字没命中（not_found）：这一份全文共 {pages} 页，逐页归一化之后都没有出现"
            f"要比对的那一段（声明窗口：{where}；比对对象：{field or '引文'}）{said} ⇒ 要么"
            "它指的不是这一份来源（页码或 source_lit_id 给错了），要么这一句被改写过"
            "（改写要按语义档走：H 判 + quote_call_sha256）。"
            f"按 quote_verified=False 记 —— 不是 unknown：这份全文我读到了。{NO_CALL_NOTE}")


def _no_span_reason(*, reason: str, has_doc: bool, doc_problem: str, quote: str,
                    page_range: Any = None, field: str = "", note: str = "",
                    pages: int = 0) -> str:
    """说"逐字通过"而这一次写产不出区间 ⇒ 一句可操作的理由（unknown 档）。

    两种现场分开写，因为补法不同：有全文而定位不到（两侧有一侧要改：页码/引文，或
    那一份全文没覆盖到）与根本没有可比全文（一次比对都没发生）。折成同一句话，
    读的人会把"没全文"当成"引文错了"，于是去改一条其实没问题的引文。

    交来的 `quote_reason` 一并留在这里：它是这一笔的来路（很有用），但它不是区间 ——
    保留它不等于承认它。不保留又会让"模型当时说了什么"从盘上消失。
    """
    where = _declared_label(page_range)
    if has_doc:
        head = (f"{UNKNOWN_NOTE}：这一次写没有真的比对起来（文档在手，但"
                + ("里头一页可读文本都没有" if not pages else "没有要比对的那一段")
                + f"；{field or '引文'}）")
        if not str(quote or "").strip():
            head += "（要比对的那一段是空的：quote_span 与 proof_text 都没给）"
        tail = ("没有可比的那一段就谈不上命中或没命中，所以按 unknown 记（不是 false）。"
                "补齐：给 quote_span（p{页}:norm[起:止]）或 proof_text（要核的那一段），"
                "或者把这一行写成 quote_verified=None 并说明还没核")
    else:
        head = (f"{UNKNOWN_NOTE}：这一笔没有可比的全文"
                f"（{doc_problem or '没有给文档可查'}），一次比对都没有发生")
        tail = ("没有全文就没有『逐字通过』这句话：它既不是 true（没人核过），"
                "也不是 false（没读到的不能说原文里没有）。补齐：① 给 source_lit_id、"
                "且那一篇的全文在库（B 会拿它真比对并把区间写实）；"
                "② 或者把 quote_verified 写成 None 并说明还没核")
    said = ""
    if str(reason or "").strip():
        said = (f"；这一笔交来的 quote_reason 是 {str(reason)[:120]!r} —— 理由不是区间，"
                "复现不出核的是哪一段，它留着但不改变结论")
    if str(note or "").strip():
        said += f"；这一笔核的是{str(note)}"
    return f"{head}（声明窗口：{where}）{said}。{tail}"


def enforce_quote_evidence(fields: Mapping[str, Any], *, quote: str = "",
                           doc: Any = None, page_range: Any = None,
                           field: str = "", doc_problem: str = "",
                           hint_page: int = 0, note: str = "",
                           ) -> tuple[dict[str, Any], dict[str, Any]]:
    """写侧断言：返回 `(摆好的四栏, 读数)`，读数里 `action` 有四档。

    这是"必须落 span"的唯一实现（`quote_span` 的产出点就是这里），判据 1 依赖它 ——
    把它 monkeypatch 掉之后，`verify_quote_evidence` 给出的 span 必然是空的。

    四档（与 `quote_verified` 的三态对齐，不许折平）：

    - `keep`：`True` 且当场算得出区间（`semantic` 还要求调用指纹）⇒ 四栏写实；
    - `mismatch`：有全文、有要比对的那一段，而整份全文里都没有它 ⇒ 改判 `False`
      （查过了、不一致）。这一档不是降级：它是这一趟真查出来的结论；
    - `downgrade`：说"逐字通过"而这一趟根本没有可比对的全文（或没有要比对的那一段）
      ⇒ 降成 `None` + 原因（"没查成"是 unknown 档，既不是 false 也不是 true）。
      真机那 13 条命题落到这一档：`quote_verified=true` 而没有区间；
    - `refuse`：说"语义相同"却缺 span 或调用指纹 ⇒ 调用方应当整笔不写（说不出
      对着哪一段、哪一次判的，就不是语义通过）；理由走了「无来源可核」那一档却
      指不出我方手稿的哪一处也是这一档（`no_source_without_backing`）。

    `quote_verified` 不是 `True` 的行不改判决，只把方式归一成空串、并保证理由非空：
    三态纪律要求"没通过 / 还没查"都说得出为什么。

    ## 区间从哪来：只从 :func:`locate_span` 来

    `doc` 与 `quote` 都给齐时，本函数当场在文档里定位引文，把命中的区间写进 `quote_span`
    （`locate_span` 搜的是整份文档，所以"页码写错"不会被误判成"引文不存在"——命中页与
    声明窗口不符时如实写进理由，判决仍是 `True`）。入参里的 `quote_span` 不是结论，
    只是"该去哪一段核"的线索（调用方给的可能是自报的定位，也可能是 H 判时对着的那一段
    原文）；能不能落成区间要重算一遍。

    ## 为什么理由不够（第二版口径，2026-10-22）

    第一版留下过一档"有理由、没区间 ⇒ 保留 `True`、把缺口写进理由"，当时的理由是
    "B 的动作面没有 `quote_span` 参数，一律降档会把所有合规登记都降成 unknown"。
    那一档已经把病治反了：`quote_reason` 是一句人话，复现不出核的是哪一段——
    真机那 13 行里就有写着"逐字比对通过"而 span 为空的，读的人照样无从复核。
    参数面补齐之后（`specs/b.py` 的 `quote_span` / `quote_call_sha256`），
    "说不出位置就不算通过"这条才真正可执行，所以那一档并入 `downgrade`。

    降档不是"指控它造假"：`None` 的语义是"没查成"，而"这一趟没有可比对的全文"正是
    "没查成"的一种；它既不是 false（我们没证明原文里没有），也不是 true。
    """
    out = dict(fields)
    verified = out.get("quote_verified")
    mode = str(out.get("quote_mode") or "")
    span = str(out.get("quote_span") or "").strip()
    call = str(out.get("quote_call_sha256") or "").strip()
    reason = str(out.get("quote_reason") or "").strip()
    reading: dict[str, Any] = {"ok": True, "action": "keep", "why": "", "where": field}

    # ---- B-4（业主 2026-10-22）：走「无来源可核」那一档，就必须指到我方手稿的哪一处。
    #
    # 为什么这是一条拒收（而不是像 `downgrade` 那样改判决）：这一档说的不是"没查成"，
    # 是"我们明明没有外部原文可核，却仍然把它写上去了" —— 它唯一的正当性来自
    # 我方手稿里的一处背书。背书指不出来时，这一行在盘上就是一句没有来路的断言，
    # 而"没有来路"与"来路是我方手稿"在读数上会完全一样（都只是 `quote_verified=None`
    # 加一句理由）。所以位置缺了就不许进库，理由码单独命名（`no_source_without_backing`），
    # 与"漏字段"那一档分开。
    no_source_declared = declares_no_source(reason)
    no_source_backing = manuscript_backing(reason) if no_source_declared else ""
    if no_source_declared:
        reading["no_source"] = {
            "declared": True,
            "backing": no_source_backing,
            "state": NO_SOURCE_BACKED if no_source_backing else NO_SOURCE_UNBACKED,
        }
    if no_source_declared and not no_source_backing:
        reading.update(
            ok=False, action="refuse", code="no_source_without_backing",
            why=("quote_reason 走了「无来源可核」那一档，却没有指出我方手稿里的哪一处 ⇒ "
                 "整笔不写。这一档不是「查不到所以算了」：说得出无来源还写上去，"
                 "凭的只能是我方手稿的背书 —— 欠了它就等于把一句没有来路的断言放进了台账。"
                 "三条正路（给一处就够）：① `manuscripts/handoffs.jsonl#NNNN`；"
                 "② `out/paper/main.tex` 的某一节（如 `out/paper/main.tex§3`）；"
                 "③ `stmt:` + 编号。给不出背书就别写这一档：把 quote_verified 说成"
                 "「还没查」并写清为什么，或者干脆不登记这一行"))
        return out, reading

    if verified is not True:
        # `False` 原样留着（它是"查过、不一致"），`None` 也原样留着（"还没查"）。
        out["quote_verified"] = None if verified is None else False
        out["quote_mode"] = ""
        out["quote_span"] = ""
        if verified is not False:
            out["quote_call_sha256"] = ""
        if not reason:
            out["quote_reason"] = (
                f"{UNKNOWN_NOTE}：这一行的 quote_verified={verified!r}，"
                "但没有任何理由 —— 没查 / 查不成 / 查过不一致，三种都要说出是哪一种")
            reading["why"] = "理由原来是空的，已按 unknown 口径写实"
        return out, reading

    if mode == "semantic":
        if not span or not call:
            missing = "quote_span" if not span else "quote_call_sha256"
            reading.update(
                ok=False, action="refuse",
                why=(f"标了 quote_mode='semantic' 但缺 {missing} ⇒ 说不出对着哪一段原文、"
                     "哪一次调用的判定就不算语义通过（指令：要么补上这两栏，"
                     "要么这一行写 quote_verified=None 并说明还没核）"))
            return out, reading
        out.update(quote_mode="semantic", quote_span=span, quote_call_sha256=call,
                   quote_reason=reason or f"语义相同（H 判）：对着原文 {span} 判的，"
                                          f"调用指纹 {call[:16]}…")
        return out, reading

    # ---- 逐字档：区间必须由这一次写算出来 -----------------------------------------
    #
    # 判据只有一句：说"逐字通过"就必须当场指得出核的是哪一段。三态在这一档上的分工：
    #
    # - 有全文、整份全文里定位到 ⇒ `True` + 区间（`keep`）；
    # - 有全文、整份全文里都没有这一段 ⇒ `False`（`mismatch`）——这是"查过了、不一致"：
    #   全文我读到了，归一化之后一段都不含这句（`locate_span` 搜的是整份文档，不是声明的
    #   那几页，所以"页码写错"不会被误判成"引文不存在"）；
    # - 没有全文 / 全文没有可读的页 / 没有可比的那一段 ⇒ `None`（`downgrade`）：
    #   一次比对都没发生，既不能判 true 也不能判 false（三态纪律）。
    #
    # 入参里的 `quote_span` 只是线索，不是结论：它有值时也只用来指"该去核哪一段"，
    # 落盘的那个区间一律由 `locate_span` 在这一份全文上重算 —— 接受自报的区间等于
    # 把"证据"换回"声明"，而那正是 D1 要堵的东西。
    claimed = span
    hint = int(hint_page or 0) or int(getattr(_page_range(page_range), "start", 0) or 0)
    quote_now = str(quote or "").strip()
    pages = list(getattr(doc, "pages", None) or []) if doc is not None else []
    span = locate_span(doc, quote_now, page=hint) if (pages and quote_now) else ""
    if not span:
        if pages and quote_now:
            # 有全文、有要比对的那一段，而整份全文里都没有它 ⇒ 查过了、不一致。
            out.update(
                quote_verified=False, quote_mode="", quote_span="", quote_call_sha256="",
                quote_reason=_no_hit_reason(reason=reason, page_range=page_range,
                                            field=field, note=note, pages=len(pages)))
            reading.update(
                action="mismatch",
                why=(f"整份全文（{len(pages)} 页）里都没有这一段 ⇒ 判 false"
                     "（查过了、不一致；不是 unknown：这份全文读到了）"))
            return out, reading
        out.update(
            quote_verified=None, quote_mode="", quote_span="", quote_call_sha256="",
            quote_reason=_no_span_reason(reason=reason, has_doc=doc is not None,
                                         doc_problem=doc_problem, quote=quote_now,
                                         page_range=page_range, field=field,
                                         note=note, pages=len(pages)))
        reading.update(
            action="downgrade",
            why=("说逐字通过，而这一次写没有可比对的全文（或没有要比对的那一段）"
                 " ⇒ 降为 unknown（D1 的写侧断言：理由不是区间，区间只能算出来）"))
        return out, reading

    moved = ""
    if claimed and claimed != span:
        moved = (f"交来的 quote_span 是 {claimed}，拿这一份全文重算得到 {span} —— "
                 "落盘的是算出来的那一个")
    # 页码标注错 ≠ 引文不存在（与 `verify.py` 的 `page_range_mismatch` 同一条口径）：
    # 命中页落在声明窗口之外时如实写进理由，判决仍是 True（逐字确实存在）。
    off_page = ""
    parsed = parse_span(span)
    if parsed:
        lo = getattr(_page_range(page_range), "start", None)
        hi = getattr(_page_range(page_range), "end", None) or lo
        actual = parsed[0]
        if isinstance(lo, int) and (actual < lo or (isinstance(hi, int) and actual > hi)):
            off_page = (f"声明的页码是{_declared_label(page_range)}，实际命中第 {actual} 页 —— "
                        "引文逐字存在，错的是页码标注（不是引文不存在）")
    out.update(
        quote_verified=True, quote_mode="verbatim", quote_span=span,
        quote_call_sha256="",
        quote_reason="；".join(x for x in (
            str(note or ""), reason, moved, off_page,
            f"命中区间 {span}（页号从 1 起；起止是该页归一化文本的字符偏移，含头不含尾，"
            f"归一化函数 textutil.normalize_for_quote）", NO_CALL_NOTE) if x))
    reading["why"] = f"落了区间 {span}"
    return out, reading


def evidence_fields(check: Any, *, doc: Any = None, quote: str = "",
                    page_range: Any = None, field: str = "",
                    note: str = "", doc_problem: str = "") -> dict[str, Any]:
    """把一次 `QuoteCheck` 翻成落盘的四栏（三态原样透传，不折平）。

    `note` 是调用方自己的来路说明（"命中的是 `out/paper/main.tex`，不是 PDF"）——
    两种证据不许混成一种，所以它排在 reason 最前面。`doc_problem` 只在"没有文档可比"
    时才进理由（调用方用来说明为什么没有全文）。
    """
    verified = getattr(check, "verified", None)
    if verified is True:
        reason = (str(note or "") + "；" if note else "") + (
            f"逐字命中（{str(getattr(check, 'reason', '') or 'substring_match')}，"
            f"窗口 {str(getattr(check, 'window', '') or '未记')}，"
            f"试过 {'/'.join(str(t) for t in (getattr(check, 'tried', ()) or ())) or '未记'}）")
        mode = "verbatim"
    elif verified is False:
        reason = _miss_reason(check, page_range, field)
        mode = ""
    else:
        reason = _unknown_reason(check, page_range, field)
        mode = ""
    fields = {"quote_verified": verified, "quote_mode": mode, "quote_span": "",
              "quote_call_sha256": "", "quote_reason": reason}
    fixed, reading = enforce_quote_evidence(
        fields, quote=quote, doc=doc if verified is True else None,
        page_range=page_range, field=field, doc_problem=doc_problem)
    fixed["reading"] = reading
    fixed["check"] = (check.to_dict() if hasattr(check, "to_dict") else {})
    return fixed


def verify_quote_evidence(*, doc: Any, quote: str, page_range: Any = None,
                          field: str = "quote", widen: int = 1,
                          allow_fulltext_fallback: bool = False,
                          note: str = "", doc_problem: str = "",
                          ) -> dict[str, Any]:
    """验一条引文，返回 `{quote_verified, quote_mode, quote_span, quote_call_sha256,
    quote_reason, reading, check}`（可以直接摊进载荷）。

    判据只有一份实现：仍然交给禁改区那一个 `quoteverify.check_quote` —— 本函数不做
    第二种"像不像"的判断，只负责把它的三态判决翻译成盘上读得出来的四栏。
    `quote_call_sha256` 恒为空串：这条路是纯文本比对，一次模型调用都没有（理由写进
    `quote_reason`，不是留一个空栏让人猜）。
    """
    pr = _page_range(page_range)
    check = _QV.check_quote(doc, quote, pr, widen=widen,
                            allow_fulltext_fallback=allow_fulltext_fallback)
    return evidence_fields(check, doc=doc, quote=quote, page_range=pr, field=field,
                           note=note, doc_problem=doc_problem)


def scan_quote_evidence(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """读侧判据：扫盘上所有行，点名"说通过而拿不出可复核证据"的行。

    `checked` 是扫了几行（反真空：它若是 0，说明扫描器没读到东西，"没有命中"不等于
    "没有问题"）。`verified_rows` 是多少行自称通过（这一栏是分母），`dirty` 逐条给
    `{id, why, class}`，三类：

    - `no_span_no_reason`：`quote_verified=true` 而 `quote_span` 与 `quote_reason`
      都空 —— 真机那 13 行就是这一档，盘上连"为什么算通过"都读不到；
    - `no_span`：说通过、也写了理由，但没有区间 —— 仍然不可复核（理由本身不是证据，
      复现不出核的是哪一段）；
    - `no_call`：`quote_mode=semantic` 而 `quote_call_sha256` 空 —— 说不出是哪一次
      模型调用判的（语义档的第二件证据缺了）。

    `quote_verified` 不是 `True` 的行不进这一档：没通过 / 没查成的行本来就没有区间。

    这一栏与 `evidencebits.quote_state` 是同一件事的两面：那边给一行的状态（其中
    `no_evidence` 就是这里点名的那些行），这边逐条点名并给出可操作的话。
    """
    dirty: list[dict[str, Any]] = []
    rows = list(rows or ())
    for row in rows:
        if row.get("quote_verified") is not True:
            continue
        span = span_of(row)
        mode = str(row.get("quote_mode") or "")
        reason = str(row.get("quote_reason") or "").strip()
        missing: list[str] = []
        if not span:
            missing.append("quote_span")
        if mode == "semantic" and not call_of(row):
            missing.append("quote_call_sha256")
        if not missing:
            continue
        rid = str(row.get("stmt_id") or row.get("relation_id") or row.get("id") or "")
        if "quote_span" in missing:
            why = ("quote_verified=true 而 quote_span 为空 ⇒ 盘上没有'核了哪一段、在第几页'"
                   "的读数")
            if not reason:
                why += "；quote_reason 也是空的 ⇒ 连为什么算通过都读不到"
            else:
                why += f"；理由只说 {reason[:60]!r}，没有位置"
            if "quote_call_sha256" in missing:
                why += "；另外 quote_call_sha256 也是空的（语义档说不出哪一次判的）"
            cls = "no_span_no_reason" if not reason else "no_span"
        else:
            why = ("quote_mode=semantic 而 quote_call_sha256 为空 ⇒ 盘上读不出'哪一次模型"
                   "调用判的'，这一档唯一能复核的凭据就是它")
            cls = "no_call"
        dirty.append({"id": rid, "class": cls, "why": why,
                      "missing": missing})
    return {
        "checked": len(rows),
        "dirty": dirty,
        "verified_rows": sum(1 for r in rows if r.get("quote_verified") is True),
        "clean": not dirty,
    }
