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

本模块补的是"调动方"那一半（禁改区里那两条的最小改法见交付说明）：

- :func:`verify_quote_evidence` 用禁改区那一个 `quoteverify.check_quote` 判，再把判决
  翻成落盘需要的四栏（区间、方式、理由、调用指纹）；
- :func:`enforce_quote_evidence` 是写侧断言：说"通过"却既没有区间也没有理由就降成
  unknown 档（不是 false、也不是 true）；有理由而没有区间时保留判决，但把缺口写进
  理由（为什么这一档不能一律降档，见该函数 docstring 的"边界"一节）；
- :func:`scan_quote_evidence` 是读侧判据：扫盘上所有行，把"说通过而没有任何证据"的
  行逐条点名（历史脏数据因此不会被当成通过放过）。

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
"""
from __future__ import annotations

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


def enforce_quote_evidence(fields: Mapping[str, Any], *, quote: str = "",
                           doc: Any = None, page_range: Any = None,
                           field: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    """写侧断言：返回 `(摆好的四栏, 读数)`，读数里 `action` 只有三档。

    这是"必须落 span"的唯一实现（`quote_span` 的产出点就是这里），判据 1 依赖它 ——
    把它 monkeypatch 掉之后，`verify_quote_evidence` 给出的 span 必然是空的。

    三档（与 `quote_verified` 的三态对齐，不许折平）：

    - `keep`：`True` 且拿得出区间（`semantic` 还要求调用指纹）⇒ 四栏写实；
      拿不出区间但有理由时也走这一档，并把"没有区间 ⇒ 这一行不可复核"写进理由
      （缺口必须在盘上看得见，见下面那段边界）；
    - `downgrade`：说"逐字通过了"却既没有区间、也没有任何理由 ⇒ 降成 `None` +
      原因（"没查成"是 unknown 档，既不是 false 也不是 true）。真机那 8 条命题就是
      这一档：`quote_verified=true` 而 span 与 reason 全空；
    - `refuse`：说"语义相同"却缺 span 或调用指纹 ⇒ 调用方应当整笔不写（说不出
      对着哪一段、哪一次判的，就不是语义通过）。

    `quote_verified` 不是 `True` 的行不改判决，只把方式归一成空串、并保证理由非空：
    三态纪律要求"没通过 / 还没查"都说得出为什么。

    ## 边界：为什么"有理由、没区间"这一档不降档

    它照样是不可复核的，但它与"连理由都没有"不是同一件事：前者至少说清了凭什么
    算通过（人在读的时候能追），后者在盘上什么都没说。所以这一档保留 `True`、
    把缺口写进 `quote_reason`，并交由读侧判据 :func:`scan_quote_evidence` 逐条点名
    （class=`no_span`）—— 三态纪律要的是"缺口可见"，不是"一律判不知道"。

    另一个现实约束：B 的动作面（`specs/b.py` 是禁改区）今天没有 `quote_span` /
    `quote_call_sha256` 这两个参数，所以经 `register_statement` 进来的外部命题
    结构上给不出区间 —— 这一档因此必须留着，否则所有合规登记都会被降成 unknown。
    要让它真的可复核，需要人改 `specs/b.py` 的动作参数面（最小改法见交付说明）。
    """
    out = dict(fields)
    verified = out.get("quote_verified")
    mode = str(out.get("quote_mode") or "")
    span = str(out.get("quote_span") or "").strip()
    call = str(out.get("quote_call_sha256") or "").strip()
    reason = str(out.get("quote_reason") or "").strip()
    reading: dict[str, Any] = {"ok": True, "action": "keep", "why": "", "where": field}

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

    if not span and doc is not None and str(quote or "").strip():
        # 有文档就把区间当场定位出来：这是"证据"而不是"让调用方补一句话"。
        span = locate_span(doc, quote, page=int(getattr(_page_range(page_range), "start", 0) or 0))
    if not span and not reason:
        out.update(
            quote_verified=None, quote_mode="", quote_span="",
            quote_reason=(
                f"{UNKNOWN_NOTE}：这一行写着 quote_verified=true，但 quote_span 与"
                "quote_reason 都是空的 ⇒ 盘上没有任何可复核的证据（核了哪一段、在第几页、"
                "为什么算命中，一条都读不到），也没有理由 ⇒ 降成 unknown（不是 false："
                "我们没有查成；也不是 true：说不出凭什么）。补齐的办法：给 quote_span"
                "（p{页}:norm[起:止]）与 reason，或把 quote_verified 改成 None/False 并写明原因"))
        reading.update(action="downgrade",
                       why="说通过但 span 与 reason 全空 ⇒ 降为 unknown（D1 的写侧断言）")
        return out, reading
    if not span:
        out.update(
            quote_verified=True, quote_mode="verbatim", quote_span="",
            quote_call_sha256="",
            quote_reason=reason + (
                "；写侧读数：这一行没有 quote_span ⇒ 不可复核（说不出在第几页的哪一段）；"
                "动作面的参数里今天没有这一栏，补齐要人改 `specs/b.py`。"+NO_CALL_NOTE))
        reading.update(why="有理由、没有区间 ⇒ 缺口写进 reason，读侧判据会点名")
        return out, reading

    out.update(
        quote_verified=True, quote_mode="verbatim", quote_span=span,
        quote_call_sha256="",
        quote_reason=(reason + "；" if reason else "") + (
            f"命中区间 {span}（页号从 1 起；起止是该页归一化文本的字符偏移，含头不含尾，"
            f"归一化函数 textutil.normalize_for_quote）；{NO_CALL_NOTE}"))
    reading["why"] = f"落了区间 {span}"
    return out, reading


def evidence_fields(check: Any, *, doc: Any = None, quote: str = "",
                    page_range: Any = None, field: str = "",
                    note: str = "") -> dict[str, Any]:
    """把一次 `QuoteCheck` 翻成落盘的四栏（三态原样透传，不折平）。

    `note` 是调用方自己的来路说明（"命中的是 `out/paper/main.tex`，不是 PDF"）——
    两种证据不许混成一种，所以它排在 reason 最前面。
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
        page_range=page_range, field=field)
    fixed["reading"] = reading
    fixed["check"] = (check.to_dict() if hasattr(check, "to_dict") else {})
    return fixed


def verify_quote_evidence(*, doc: Any, quote: str, page_range: Any = None,
                          field: str = "quote", widen: int = 1,
                          allow_fulltext_fallback: bool = False) -> dict[str, Any]:
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
    return evidence_fields(check, doc=doc, quote=quote, page_range=pr, field=field)


def scan_quote_evidence(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """读侧判据：扫盘上所有行，点名"说通过而没有任何可复核证据"的行。

    `checked` 是扫了几行（反真空：它若是 0，说明扫描器没读到东西，"没有命中"不等于
    "没有问题"）。`dirty` 逐条给 `{id, why, class}`，两类：

    - `no_span_no_reason`：`quote_verified=true` 而 `quote_span` 与 `quote_reason`
      都空 —— 真机那 8 行就是这一档，盘上连"为什么算通过"都读不到；
    - `no_span`：说通过、也写了理由，但没有区间 —— 仍然不可复核（理由本身不是证据）。

    `quote_verified` 不是 `True` 的行不进这一档：没通过 / 没查成的行本来就没有区间。
    """
    dirty: list[dict[str, Any]] = []
    rows = list(rows or ())
    for row in rows:
        if row.get("quote_verified") is not True:
            continue
        span = str(row.get("quote_span") or "").strip()
        if span:
            continue
        reason = str(row.get("quote_reason") or "").strip()
        rid = str(row.get("stmt_id") or row.get("relation_id") or row.get("id") or "")
        why = ("quote_verified=true 而 quote_span 为空 ⇒ 盘上没有'核了哪一段、在第几页'"
               "的读数")
        if not reason:
            dirty.append({"id": rid, "class": "no_span_no_reason",
                          "why": why + "；quote_reason 也是空的 ⇒ 连为什么算通过都读不到"})
        else:
            dirty.append({"id": rid, "class": "no_span",
                          "why": why + f"；理由只说 {reason[:60]!r}，没有位置"})
    return {
        "checked": len(rows),
        "dirty": dirty,
        "verified_rows": sum(1 for r in rows if r.get("quote_verified") is True),
        "clean": not dirty,
    }
