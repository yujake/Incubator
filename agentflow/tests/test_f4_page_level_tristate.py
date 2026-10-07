"""`F-4` 的回归判据：逐页三态 —— "这页没抽出来"不许与"这句话不在这页上"同形。

## 缺陷（2026-09-26 全面体检 · 子代理 F 发现，`temp/auditF-probe3.txt` [K]）

`DocumentText` 只有 `text/pages/source_kind/encoding` 四个字段，
PyPDF2 后端单页失败时 `pages.append("")`。于是 `_finish_pdf(['有','空','有'])`
给出 `has_text_layer=True`、`pages=['page one text','','page three text']`，
与"第 2 页本来就是空白页"在返回形态上完全同形。下游客观后果：

- `ocr.detect_text_layer` 判 `has_layer=bool(doc.pages)` 后逐字打印
  「有文本层：N 页可定位文本……引文校验可以正常判定 true/false」；
- `quoteverify.check_quote` 只在 `pages == []` 时给 `verified=None`，
  部分页失败时给 `QuoteCheck(False, reason='not_found')` ——
  真引文被判成幻觉（B 的唯一自动幻觉防线给出假阳性）。

修法是给 `DocumentText` 加一个纯增量字段 `page_status`（默认空元组 =
没有逐页信息 = 与旧行为逐字一致），并让两个消费点各判一次。

## 本文件守什么

1. 字段与辅助方法本身（`failed_pages` / `page_status_of` / `page_unreadable`）；
2. `check_quote` 的三态：声明窗口里有失败页且没命中 ⇒ `None`，
   而不是旧行为的 `False`；
3. `check_quote` 的方向：命中优先于失败（引文真在可读页上 ⇒ `True`，
   哪怕同一次声明的窗口里还有别的失败页）；
4. `ocr.detect_text_layer` 的 reason 必须点名失败页；
5. 负控：`page_status` 为空的旧形态仍然给出旧答案（`False`/`not_found`）——
   证明这一层是"新增信息"而不是"把一切都变严"。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import schema as S
from agentflow.extract import DocumentText, _finish_pdf, extract_text
from agentflow.quoteverify import check_quote

LONG = "第 1 页：谱落在区间内。"


def _doc(pages: list[str], status: tuple[str, ...] = ()) -> DocumentText:
    return DocumentText(text="\n".join(pages), pages=list(pages), source_kind="pdf",
                        encoding=None, page_status=status)


# ============================================================ 字段与辅助方法


def test_page_status_defaults_to_no_information() -> None:
    """纯增量：不给 `page_status` ⇒ 与旧行为一致（没有"失败页"这个概念）。"""
    d = _doc(["有", "", "有"])
    assert d.page_status == ()
    assert d.failed_pages() == ()
    assert d.page_status_of(2) == "ok"
    assert d.page_unreadable(1, 3) is False


def test_failed_pages_and_page_unreadable_are_one_based() -> None:
    d = _doc(["有", "", "有"], ("ok", "failed", "ok"))
    assert d.failed_pages() == (2,)
    assert d.page_status_of(1) == "ok" and d.page_status_of(2) == "failed"
    assert d.page_unreadable(1, 1) is False
    assert d.page_unreadable(1, 3) is True
    assert d.page_unreadable(2, 2) is True
    # 越界/反向区间不许抛，也不许误报
    assert d.page_unreadable(2, 1) is False
    assert d.page_unreadable(9, 9) is False


def test_finish_pdf_keeps_the_old_shape_when_no_status_is_given() -> None:
    """`_finish_pdf` 不给状态时按内容推（`ok` / `empty`）——旧行为不变。"""
    d = _finish_pdf(["page one text", "", "page three text"], "PyPDF2")
    assert d.pages == ["page one text", "", "page three text"]
    assert d.page_status == ("ok", "empty", "ok")
    assert d.failed_pages() == ()
    assert d.has_text_layer is True


def test_finish_pdf_propagates_an_explicit_failure() -> None:
    d = _finish_pdf(["有", "", "有"], "PyPDF2", ["ok", "failed", "ok"])
    assert d.page_status == ("ok", "failed", "ok")
    assert d.failed_pages() == (2,)


def test_extract_text_propagates_a_backend_failure(tmp_path: pathlib.Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：后端报"第 2 页失败" ⇒ `extract_text` 的返回值里必须看得见。

    用 monkeypatch 换掉后端函数（不是换掉 `extract_text` 本身）：
    被测对象是"后端的状态能不能传到 `DocumentText`"这一整条链。
    """
    from agentflow import extract as E

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    def fake(path, max_pages):
        return ["有", "", "有"], ["ok", "failed", "ok"]

    monkeypatch.setattr(E, "_pdf_pages_fitz", fake)
    monkeypatch.setattr(E, "_pdf_pages_pdfminer", fake)
    monkeypatch.setattr(E, "_pdf_pages_pypdf2", fake)
    d = extract_text(pdf)
    assert d.failed_pages() == (2,), d.page_status
    assert d.source_kind == "pdf" and d.has_text_layer is True


# ============================================================ check_quote 的三态


def test_a_quote_on_a_failed_page_is_undecidable_not_false() -> None:
    """负控（核心）：声明窗口里有失败页且没命中 ⇒ `None` / `page_unreadable`。

    改前这一条给出 `QuoteCheck(False, reason='not_found')` —— 真引文被判成幻觉。
    """
    d = _doc(["第一页有别的句子", "", "第三页也有别的句子"], ("ok", "failed", "ok"))
    out = check_quote(d, "这句话其实在第二页上，但我们没抽出来", S.PageRange(2, 2), widen=0)
    assert out.verified is None, f"必须判『无法校验』，实际 {out}"
    assert out.reason == "page_unreadable"


def test_a_quote_on_a_readable_page_is_still_false_when_absent() -> None:
    """正控：可读页上确实没有这句话 ⇒ 仍然如实判 `False` / `not_found`。

    没有这一条，"凡是有失败页就一律 None"也能让上面那条通过 ——
    那会让"引文不在文档里"这件事永远报不出来。
    """
    d = _doc(["第一页有别的句子", "", "第三页也有别的句子"], ("ok", "failed", "ok"))
    out = check_quote(d, "这句话在哪一页都不存在", S.PageRange(1, 1), widen=0)
    assert out.verified is False, out
    assert out.reason == "not_found"


def test_a_hit_beats_a_failure_in_the_same_window() -> None:
    """方向：命中优先于失败。

    声明窗口 `1..3` 里第 2 页失败，而引文真在第 1 页上 ⇒ 必须 `True`。
    把顺序写反（先判失败）会把一条能验的引文降级成"无法校验"，
    那是"为了保守而丢掉可得证据"，与本项目"证据等级不能凭空降"的口径冲突。
    """
    d = _doc([LONG, "", "第三页"], ("ok", "failed", "ok"))
    out = check_quote(d, LONG, S.PageRange(1, 3), widen=0)
    assert out.verified is True, out
    assert out.matched_page == 1


def test_the_old_shape_without_page_status_still_says_not_found() -> None:
    """负控 2（纯增量）：`page_status` 为空（历史替身/文类）⇒ 仍然给出旧答案 `False`。

    这一条保证"加字段"没有把历史调用方变成"整篇不可读"。
    """
    d = _doc(["第一页有别的句子", "", "第三页也有别的句子"])
    out = check_quote(d, "不在任何一页上的一句话", S.PageRange(2, 2), widen=0)
    assert out.verified is False and out.reason == "not_found", out


def test_a_quote_found_only_in_the_widened_window_still_reports_outside_range() -> None:
    """边界：扩窗命中仍然报 `substring_match_outside_declared_range`（失败页不干扰）。"""
    d = _doc(["目标句子在这里", "", "第三页"], ("ok", "failed", "ok"))
    out = check_quote(d, "目标句子", S.PageRange(2, 2), widen=1)
    assert out.verified is True, out
    assert out.reason == "substring_match_outside_declared_range"
    assert out.matched_page == 1


# ============================================ `R3-5`：判据只有一份实现


def test_check_quote_asks_the_document_for_the_unreadable_verdict() -> None:
    """`R3-5` 负控（核心）：`check_quote` 必须真的去调 `doc.page_unreadable`。

    改前 `quoteverify` 自己有一个 `unreadable()` 闭包（`failed_pages()` + 区间
    过滤），与 `DocumentText.page_unreadable` 是同一件事的两份实现 —— 而那一份
    在生产代码里 0 个调用点，它的 docstring 却写着"引文校验用它来区分…"
    （假话），两份实现之间也没有任何断言相连。

    这条判据是行为级的：用一个记录调用的文档子类跑一次 `check_quote`，
    断言"文档被问过"。把实现改回闭包 ⇒ 调用列表为空 ⇒ 这条红。
    （不是"源码里搜 `page_unreadable` 这个串"——那种判据一行注释就能满足。）
    """
    class _Recording(DocumentText):
        def __init__(self) -> None:
            super().__init__(text="", pages=["第一页有别的句子", "", "第三页也有别的句子"],
                             source_kind="pdf", encoding=None,
                             page_status=("ok", "failed", "ok"))
            object.__setattr__(self, "asked", [])

        def page_unreadable(self, start: int | None, end: int | None) -> bool:
            self.asked.append((start, end))
            return super().page_unreadable(start, end)

    d = _Recording()
    out = check_quote(d, "这句话其实在第二页上，但我们没抽出来", S.PageRange(2, 2), widen=0)
    assert d.asked, (
        "`check_quote` 没有问文档要逐页状态 ⇒ 判据又成了两份实现（`R3-5` 的形态）"
    )
    assert d.asked == [(2, 2)], d.asked
    assert out.verified is None and out.reason == "page_unreadable", out


@pytest.mark.parametrize("start,end,widen", [
    (1, 1, 0), (2, 2, 0), (3, 3, 0), (1, 3, 0),
    (3, 3, 1), (1, 1, 1), (9, 9, 0), (3, 9, 0), (1, 2, 0), (2, 3, 0),
    (None, None, 0), (None, None, 1),
])
def test_check_quote_and_page_unreadable_agree_on_every_window(
        start: int | None, end: int | None, widen: int) -> None:
    """`R3-5` 交叉断言：同一组窗口下，两条路径的结论必须一致。

    左边是 `DocumentText.page_unreadable` 的窗口判据，右边是 `check_quote` 的
    最终三态。改前它们是两份独立实现，"今天恰好一致"没有任何断言守着 ——
    漂移的形态就是"其中一份永远说没问题"。
    这里把参数化矩阵打在两边的连接点上（页码未知 ⇒ 全篇、越界收窄、
    反向区间、widen 进出失败页）。
    """
    d = _doc(["第一页有别的句子", "", "第三页也有别的句子"], ("ok", "failed", "ok"))
    if start is None:
        eff_lo, eff_hi = 1, len(d.pages)
    else:
        eff_lo, eff_hi = start - max(0, widen), end + max(0, widen)
    expect_unreadable = d.page_unreadable(eff_lo, eff_hi)

    out = check_quote(d, "这句话在哪一页都不存在", S.PageRange(start, end, ""), widen=widen)
    if expect_unreadable:
        assert out.verified is None, (start, end, widen, out)
        assert out.reason == "page_unreadable", (start, end, widen, out)
    else:
        assert out.verified is False, (start, end, widen, out)
        assert out.reason in ("not_found", "not_found_page_unknown"), out


# ============================================ `R3-6`：诊断取不到 ≠ 没有失败页


def test_a_doc_whose_failed_pages_raises_is_not_reported_as_not_found(caplog) -> None:
    """`R3-6` 负控（核心）：`failed_pages()` 抛异常 ⇒ 不许折成"没有失败页"。

    改前那一支是 `except Exception: return ()`，于是"文档诊断坏掉了"与
    "文档真的可读、这句话确实不在"逐字同形（`verified=False / not_found`）——
    而那正是 `F-4` 要防的最贵方向（把真引文记成幻觉），且没有任何日志。
    现在方向倒过来：判"无法判定"，并留一条可观察的 warning。
    """
    import logging

    class _Broken:
        pages = ["第一页有别的句子", "", "第三页也有别的句子"]
        text = "第一页有别的句子\n\n第三页也有别的句子"
        source_kind = "pdf"
        encoding = None

        def failed_pages(self) -> tuple[int, ...]:
            raise RuntimeError("注入：这份历史替身的诊断坏掉了")

    with caplog.at_level(logging.WARNING, logger="agentflow.quoteverify"):
        out = check_quote(_Broken(), "这句话其实在第二页上，但我们没抽出来",
                          S.PageRange(2, 2), widen=0)
    assert out.verified is None, f"必须判『无法判定』，实际 {out}"
    assert out.reason == "page_status_unknown", out
    assert any("R3-6" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]


def test_a_historical_double_without_the_new_api_still_says_not_found() -> None:
    """对照（`R3-6` 别扩大化）：只有 `failed_pages`、且它正常返回空 ⇒ 仍然是旧答案。

    `_pages_unreadable` 的历史替身分支只在"任何一页失败"时保守；
    读得出空集时行为与旧版逐字一致（不许把"没有逐页信息的替身"一律变成未知）。
    """
    class _Old:
        pages = ["有", "", "有"]
        text = "有\n\n有"
        source_kind = "pdf"
        encoding = None

        def failed_pages(self) -> tuple[int, ...]:
            return ()

    out = check_quote(_Old(), "不在任何一页上的一句话", S.PageRange(2, 2), widen=0)
    assert out.verified is False and out.reason == "not_found", out


def test_a_historical_double_reporting_a_failure_is_conservative_without_narrowing() -> None:
    """边界（`R3-6` 的保守分支）：历史替身报了失败页 ⇒ 判未知，且不做第二份收窄。

    `R3-5` 删掉了 quoteverify 里的区间过滤闭包（收窄只许有一份实现）。
    历史替身没有 `page_unreadable`，所以这里不按窗口过滤：任何一页失败
    都按"不可读"处理。方向是更保守（宁判未知，不判不存在），这是刻意的取舍 ——
    少收窄只会多判"无法判定"，不会把真引文判成幻觉。
    """
    class _Old:
        pages = ["有", "", "有"]
        text = "有\n\n有"
        source_kind = "pdf"
        encoding = None

        def failed_pages(self) -> tuple[int, ...]:
            return (2,)

    # 窗口是第 1 页（可读），失败页在第 2 页 —— 没有收窄 ⇒ 仍然判未知
    out = check_quote(_Old(), "不在第一页上的一句话", S.PageRange(1, 1), widen=0)
    assert out.verified is None and out.reason == "page_unreadable", out


# ============================================ `R3-8`：status 长度不符不许静默


def test_a_status_length_mismatch_is_logged_instead_of_silently_inferred(caplog) -> None:
    """`R3-8` 负控：后端给的 `status` 长度与页数不符 ⇒ 必须留下一条 warning。

    改前这一支无声降级（按内容推 ok/empty）：后端上报的 `failed` 凭空消失，
    回到"真引文被判成幻觉"的那条路径，而没有任何信号。
    按内容推仍然是结论（抛异常会让"后端少报一页状态"变成整篇抽取失败，
    代价更大），但它是"被记录过的降级"。
    """
    import logging

    from agentflow import extract as E

    with caplog.at_level(logging.WARNING, logger="agentflow.extract"):
        d = _finish_pdf(["第一页", "", "第三页"], "PyPDF2", ["ok"])
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "R3-8" in msgs, [r.getMessage() for r in caplog.records]
    assert "PyPDF2" in msgs and "3" in msgs, msgs
    # 行为不变：仍然是"按内容推"（不抛错、不把整份状态丢掉）
    assert d.page_status == ("ok", "empty", "ok"), d.page_status
    assert d.failed_pages() == ()
    # 直接调 `_page_status_of` 也守同一条（两支共用一个实现）
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="agentflow.extract"):
        E._page_status_of(["a", "b"], ["failed"], backend="fitz")
    assert "R3-8" in " ".join(r.getMessage() for r in caplog.records)


def test_a_matching_status_length_is_not_warned_about(caplog) -> None:
    """正控（`R3-8` 别扩大化）：长度对得上时不许打那条 warning。

    没有这一条，"一律 warning"也能让上面那条通过 —— 而噪音比不报更糟    （它会训练人忽略这一行）。
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="agentflow.extract"):
        d = _finish_pdf(["有", "", "有"], "PyPDF2", ["ok", "failed", "ok"])
    assert d.page_status == ("ok", "failed", "ok")
    assert d.failed_pages() == (2,)
    assert "R3-8" not in " ".join(r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]


# ============================================ `R-08`（B1 候选 C）：空窗口判"没法判"

class _DuckRange:
    """`PageRange` 的替身：能表示反向区间。

    为什么要替身：`schema.PageRange.__post_init__` 显式拒绝 `start > end`
    （`start(4) 不能大于 end(3)`）。所以"反向区间"只能从别的来源进来
    （历史行、外部拼出来的范围对象、将来放宽校验的那一天）—— 而 `check_quote`
    是那道桥：桥上的行为必须被钉住，不能假设上游永远不给反向区间。
    """

    def __init__(self, start: int | None, end: int | None) -> None:
        self.start = start
        self.end = end
        self.label = ""

    @property
    def known(self) -> bool:
        return self.start is not None and self.end is not None


def test_an_empty_page_window_is_unjudgeable_not_not_found() -> None:
    """`R-08` = B1 候选 C（`draft/52`）：空窗口（`start > end`）⇒ `None` + 新档。

    改前必红（这是修正编码错误行为，`draft/52` 逐字要求同批写明）：
    旧实现让 `scan` 因 `lo > hi` 返回 `None`，随后 `widen` 把窗口撑到 3-4 页，
    若那句话在那几页上就返回 `True/…outside_declared_range`（"页码错了"）——
    于是"声明的区间是空的"这个编码错误变成了一句"引文可靠"（`True`）；
    什么都不命中时又落 `False/not_found`（"这句话不在"），同样不是这句话能有的结论。

    新行为：`None` + `reason="empty_page_range"`（"没法判"）。
    """
    d = _doc(["第一页上有一句话", "第二页上有另一句话", "第三页上还有一句"],
             ("ok", "ok", "ok"))
    # 那句话真的在第 2 页上：旧实现会经由 widen 判 `True`（最贵的假绿方向）
    out = check_quote(d, "第二页上有另一句话", _DuckRange(4, 3), widen=1)
    assert out.verified is None, out
    assert out.reason == "empty_page_range", out
    assert out.window == "", out
    assert out.tried == ("empty:4-3",), out
    # 命不中也一样：空区间里"没找到"没有信息量，不许判 `not_found`
    out2 = check_quote(d, "这句话哪一页都没有", _DuckRange(4, 3), widen=1)
    assert out2.verified is None and out2.reason == "empty_page_range", out2


def test_page_unknown_still_takes_its_own_branch() -> None:
    """反真空（B1 的守卫）：页码未知（`start=end=None`）走的是 `not_found_page_unknown`。

    没有 `pr.known` 守卫时，新分支会把它一起吃掉 —— 而"页码未知 ⇒ 全篇找过、没找到"
    与"声明的窗口是空的"是两件完全不同的事（前者是合法结论，后者是没法判）。
    """
    d = _doc(["第一页上有一句话"], ("ok",))
    out = check_quote(d, "这句话哪一页都没有", _DuckRange(None, None), widen=1)
    assert out.verified is False and out.reason == "not_found_page_unknown", out


def test_the_widened_label_never_shows_an_inverted_range() -> None:
    """T（`R-08` 同批）：`widened:` 标签必须与真的扫过的窗口一致（不许反向）。

    越界把窗口收窄到空集时，标签写 `widened:empty` —— 旧实现会写出
    `widened:4-3` 这种反向区间，读的人会以为"从第 4 页往第 3 页扫过"。
    """
    d = _doc(["第一页上有一句话"], ("ok",))
    out = check_quote(d, "这句话哪一页都没有", _DuckRange(2, 2), widen=0)
    assert out.reason == "not_found", out
    assert out.tried == ("declared:2-2",), out
    out2 = check_quote(d, "这句话哪一页都没有", _DuckRange(4, 4), widen=2)
    assert out2.verified is False and out2.reason == "not_found", out2
    for t in out2.tried:
        span = t.split(":", 1)[1]
        if span == "empty":
            continue
        lo, _, hi = span.partition("-")
        assert int(lo) <= int(hi), (t, out2.tried)
