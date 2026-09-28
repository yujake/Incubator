"""`locallib` 的判据：把本地书架变成可追溯、幂等、可被证据层接受的来源。

每条判据都配了负控（"改坏了必须红"），负控写在同一条用例里：
`test_ingest_is_idempotent_by_content_hash` 的第二半就是负控
（改了内容 ⇒ 必须新增一行，否则"幂等"会退化成"永远只登记一本"）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import evidence as EV
from agentflow import schema as S
from agentflow.locallib import (
    excerpt_for,
    ingest_directory,
    list_books,
    local_fetch_fn,
    memo_extract_fn,
    search_fn_for_store,
    sha256_file,
)
from agentflow.store import Store


def _make_pdf(path: Path, text: str) -> None:
    """造一页有文本层的 PDF（缺 fitz 就跳过：那是环境问题，不是判据问题）。"""
    fitz = pytest.importorskip("fitz", reason="本机没有 fitz ⇒ 造不出带文本层的 PDF")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


@pytest.fixture()
def books(tmp_path: Path) -> Path:
    root = tmp_path / "books"
    root.mkdir()
    _make_pdf(root / "甲书.pdf", "A group is a set with an operation.")
    (root / "坏书.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    return root


def test_list_books_sorts_and_filters(tmp_path: Path) -> None:
    _make_pdf(tmp_path / "b.pdf", "x")
    _make_pdf(tmp_path / "a.pdf", "y")
    (tmp_path / "notes.txt").write_text("not a book", encoding="utf-8")
    names = [p.name for p in list_books(tmp_path)]
    assert names == ["a.pdf", "b.pdf"], "只认 PDF，且次序必须稳定（否则每次跑的清单都在变）"


def test_ingest_registers_a_traceable_row(tmp_path: Path, books: Path) -> None:
    store = Store(tmp_path / "ws")
    rep = ingest_directory(store, books)

    assert rep.counts()["ingested"] == 1
    assert rep.counts()["unreadable"] == 1, "坏 PDF 必须单独记一档，不许算成登记成功"
    rows = store.rows("literature")
    assert len(rows) == 1
    row = rows[0]
    dl = row["download"]
    assert dl["status"] == "ok"
    assert dl["sha256"] == sha256_file(books / "甲书.pdf")
    assert dl["source_path"].endswith("甲书.pdf")
    assert row["type"] == "M", "专著用 M（LIT_TYPES 里的受控取值）"
    assert row["path"] and not Path(row["path"]).is_absolute()

    # 来源链：本地文件不是 A 检索来的，必须如实登记成一条人给的请求。
    reqs = store.rows("search_requests")
    assert len(reqs) == 1 and reqs[0]["submitted_by"] == "human"
    assert reqs[0]["outcome"] == "ok" and reqs[0]["result_lit_ids"] == [row["lit_id"]]
    assert row["source_request_ids"] == [reqs[0]["request_id"]]

    # 库里的副本必须与源文件同字节（引文回验比的是它）。
    lib = store.library_path(row["path"])
    assert lib is not None and sha256_file(Path(lib)) == dl["sha256"]


def test_ingest_is_idempotent_by_content_hash(tmp_path: Path, books: Path) -> None:
    """同一内容再灌一次不许新增行；内容一改就必须新增（负控）。"""
    store = Store(tmp_path / "ws")
    ingest_directory(store, books)
    again = ingest_directory(store, books)
    assert again.counts()["already_present"] == 1
    assert again.counts()["ingested"] == 0
    assert len(store.rows("literature")) == 1

    # 负控：把内容换掉（同一个文件名）⇒ 必须新增一行，而不是被文件名骗过去。
    _make_pdf(books / "甲书.pdf", "A ring is a set with two operations.")
    third = ingest_directory(store, books)
    assert third.counts()["ingested"] == 1, "内容变了却当成同一本 ⇒ 幂等退化成了永远只认一本"
    assert len(store.rows("literature")) == 2


def test_dry_run_writes_nothing(tmp_path: Path, books: Path) -> None:
    store = Store(tmp_path / "ws")
    rep = ingest_directory(store, books, dry_run=True)
    assert rep.counts()["ingested"] == 1 and rep.dry_run
    assert store.rows("literature") == [], "dry_run 一个字节都不许写"
    assert not Path(store.library).exists() or not list(Path(store.library).iterdir())


def test_limit_gate_reports_rather_than_silently_dropping(tmp_path: Path, books: Path) -> None:
    store = Store(tmp_path / "ws")
    rep = ingest_directory(store, books, limit=1)
    counts = rep.counts()
    assert counts["skipped_limit"] >= 1
    planned = [b for b in rep.books if b.status == "skipped_limit"]
    assert planned and planned[0].note, "被跳过的书必须在清单里写明理由，不许静默消失"


def test_too_large_gate(tmp_path: Path, books: Path) -> None:
    store = Store(tmp_path / "ws")
    rep = ingest_directory(store, books, max_bytes=1)
    assert rep.counts()["skipped_too_large"] == 2
    assert store.rows("literature") == []


def test_excerpt_is_a_contiguous_substring_of_one_page() -> None:
    pages = ["A group is a set with an operation.\nSecond line.", "Another page about rings."]
    page, exc = excerpt_for(pages, "group operation")
    assert page == 1
    assert exc in pages[0], "摘录必须是原文的连续子串，否则模型抄下来的引文必然回验失败"


def test_rare_term_outranks_a_common_one() -> None:
    """负控（2026-09-28 真跑踩出来的）：按出现次数排序会被满篇都是的词带偏。

    真跑现场：主题含 `convex optimization duality and Lagrange multipliers`，
    第一版选中讲"凸集定义"的那一页（`convex` 满页），`duality` 一次都没进窗口，
    模型于是如实回答"材料中没有" —— 看上去像模型不行，其实是选料错了。
    """
    pages = [
        ("common " * 300) + "tail of page one.",
        "middle page without the rare term.",
        ("filler " * 200) + "the rare term appears here: zeta-function." + ("more " * 200),
    ]
    page, exc = excerpt_for(pages, "common zeta-function")
    assert page == 3, "稀有词必须能把选页拉过去"
    assert "zeta-function" in exc, "窗口必须围着命中点取，而不是从页首截"
    assert len(exc) <= 1200


def test_window_does_not_chop_the_first_word() -> None:
    """窗口吸附：页首附近命中时不许把第一个词切成半截（真跑里出现过）。"""
    pages = ["A group is a set with an operation. " + ("filler " * 100)]
    _page, exc = excerpt_for(pages, "group operation")
    assert exc.startswith("A group is a set"), f"窗口起点切进了词里：{exc[:24]!r}"


def test_the_page_that_covers_more_topic_terms_wins() -> None:
    """负控：命中一个稀有词的页不许压过命中三个常见词的页。

    实测代价（2026-09-28）：题目 `cosets and quotient groups` 下，选中页只命中
    `cosets` 一个词（df 小 ⇒ 权重 0.25），而书里明明有同时讲 quotient 与 groups 的页
    （两个常见词，权重和只有 0.05 左右）。打分只看 Σweight 时，前者赢。
    改法：主键改成覆盖率（命中几个不同主题词），稀有度只当次键。
    """
    rare_only = "The word cosets appears here once, plus lots of unrelated filler text."
    covering = "Quotient groups are groups built from cosets; every quotient group is a group."
    filler = "Nothing about the topic at all, just prose to make the book longer. " * 30
    pages = [rare_only, covering, filler, filler, filler]
    page, exc = excerpt_for(pages, "cosets and quotient groups")
    assert page == 2, f"覆盖率更高的那一页应当胜出，实际选第 {page} 页"
    assert "quotient" in exc.lower()


def test_stopwords_are_not_query_tokens() -> None:
    """停用词不许进主题词表：`the`/`and` 每页都有，只会给所有页加同一个常数。

    实测代价（2026-09-28）：题目 `the argument principle and the residue theorem`
    下，一本书的目录页靠这些噪声词多命中一个而胜出。
    """
    from agentflow.locallib import _tokens

    assert set(_tokens("the argument and the residue theorem")) == {
        "argument", "residue", "theorem"}


def test_a_contents_page_does_not_win_over_the_real_page() -> None:
    """负控：目录页天生包含全部主题词，绝不许因为它"命中最多"而被选中。

    没有这一条时（改前）：两页命中数相同 ⇒ 先出现的那一页（目录）胜出，
    交给模型的材料是"目录"，模型只能如实回答"材料中没有"。
    """
    from agentflow.locallib import _looks_like_navigation

    toc = "\n".join([
        "Contents",
        "1. Complex numbers, power series, and exponentials . . . . . . 3",
        "2. Residue calculus, the argument principle . . . . . . . . 197",
        "3. The residue theorem and applications . . . . . . . . . . 211",
        "4. Conformal maps . . . . . . . . . . . . . . . . . . . . . 240",
    ])
    prose = (
        "Proposition 17.1. Suppose the argument principle holds for f. The residue theorem "
        "then gives the number of zeros as a contour integral, and that is exactly why the "
        "argument principle and the residue theorem are proved together."
    )
    assert _looks_like_navigation(toc) is True
    assert _looks_like_navigation(prose) is False
    page, exc = excerpt_for([toc, prose], "the argument principle and the residue theorem")
    assert page == 2, "目录页因为命中全部主题词而胜出 ⇒ 材料里没有答案"
    assert "Proposition 17.1" in exc


def test_search_fn_items_are_accepted_by_the_evidence_layer(tmp_path: Path, books: Path) -> None:
    """真正的判据：证据层的归一函数收不收它（自述"形状对"不算数）。"""
    store = Store(tmp_path / "ws")
    ingest_directory(store, books)
    fn = search_fn_for_store(store)
    items = fn("group operation", limit=5, timeout_sec=5.0)
    assert len(items) == 1 and items[0]["abstract"].strip()

    norm, rejected = EV._sources_from_items(
        items, source_name="localpdf", query="group operation",
        retrieved_at=S.now_iso(),
    )
    assert rejected == [], f"证据层拒收了本地条目：{rejected}"
    src = norm[0]
    assert src["source"] == "localpdf"
    assert src["url"].startswith("file:///")
    assert src["pdf_url"], "本地路径必须走 pdf_url，否则全文那条路会被丢掉"
    assert src["provenance"]["provider"] == "localpdf"


def test_search_fn_rejects_nothing_when_library_is_empty(tmp_path: Path) -> None:
    store = Store(tmp_path / "ws")
    store.init()
    fn = search_fn_for_store(store)
    assert fn("anything", limit=3, timeout_sec=1.0) == []


def test_fetch_fn_reads_in_place_and_never_moves(tmp_path: Path, books: Path) -> None:
    """负控：就地读 ⇒ 源文件必须还在原处（`search.register` 会搬走文件，这条路不许）。"""
    store = Store(tmp_path / "ws")
    ingest_directory(store, books)
    row = store.rows("literature")[0]
    lib = Path(store.library_path(row["path"]))
    before = sorted(p.name for p in books.iterdir())

    f = local_fetch_fn()
    got = f(str(lib), str(tmp_path / "ft"), "hint")
    assert got.ok and got.kind is None
    assert Path(got.path) == lib
    assert got.bytes == lib.stat().st_size
    assert got.sha256 == sha256_file(lib)
    assert sorted(p.name for p in books.iterdir()) == before, "书架不许被搬动"

    missing = f(str(tmp_path / "nope.pdf"), str(tmp_path / "ft"), "hint")
    assert not missing.ok and missing.kind, "失败必须带受控 kind（F-6）"


def test_memo_extract_fn_extracts_once_per_file(tmp_path: Path, books: Path) -> None:
    """同一次运行里同一个文件只抽一遍；文件被换掉必须重新抽（负控）。"""
    calls: list[str] = []

    class _Doc:
        pages = ["p1"]
        text = "p1"

    def _counting(path: str):
        calls.append(path)
        return _Doc()

    target = books / "甲书.pdf"
    memo = memo_extract_fn(_counting)
    first = memo(str(target))
    second = memo(str(target))
    assert first is second, "同一个 (路径, 大小, mtime) 必须复用同一份文本对象"
    assert len(calls) == 1, f"同一个文件不该抽两遍：{calls}"

    # 负控：换掉文件（大小变了）⇒ 缓存必须失效，否则回验会比对一份已经不存在的文本。
    _make_pdf(target, "A ring is a set with two operations and a longer sentence here.")
    memo(str(target))
    assert len(calls) == 2, f"文件换了却还在吃缓存：{calls}"
