"""`F-4` 的消费点 2 判据：`ocr.detect_text_layer` 必须点名失败页。

为什么要单独一个文件：`ocr_tools` 的 handler 是通过 `register()` 装进注册表的
（`_h_detect_text_layer(ctx, path)` 收一个 `_Ctx`），所以它没法像纯函数那样直接调。
这里走真实注册表装配一次（与 `cli tools` 同一条路径），
只把 `extract_text` 换成返回"第 2 页失败"的替身 —— 被测对象是
"后端状态 → 工具输出"这一整条链，不是 `extract_text` 本身。

改前的输出逐字包含「有文本层：3 页可定位文本……引文校验可以正常判定 true/false」，
而第 2 页其实没抽出来 —— 那句话在部分页失败时是假话。
"""
from __future__ import annotations

import pathlib

from agentflow import extract
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import ocr_tools as OT


class _PartialDoc:
    """第 2 页抽取失败的文档替身（字段与 `DocumentText` 同形）。"""

    pages = ["第一页文字", "", "第三页文字"]
    text = "第一页文字\n\n第三页文字"
    source_kind = "pdf"
    encoding = None

    @staticmethod
    def failed_pages() -> tuple[int, ...]:
        return (2,)


def _call_detect(tmp_path: pathlib.Path, doc: object, *, page_count: int | None = None) -> dict:
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    pdf = root / "library" / "partial.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    reg = build_registry(store=st, workspace_root=root, strict=True).registry
    # `ocr.detect_text_layer` 声明的 roles 是 `("B",)`（见 `ocr_tools.register`）：
    # 探测"这份文献有没有文本层"是 B 抽取阶段的动作，H 只读审校拿不到它。
    # 这里必须按声明绑定角色 —— 写成 H 会得到 `role_denied`，
    # 而那是"我的夹具与实现不一致"，不是判据在说话。
    reg.bound_role = "B"
    real_extract, real_count = OT.extract_text, OT.page_count
    OT.extract_text = lambda *_a, **_kw: doc  # type: ignore[assignment]
    if page_count is not None:
        OT.page_count = _StubPageCount(page_count)  # type: ignore[assignment]
    try:
        res = reg.call("ocr.detect_text_layer", path="library/partial.pdf")
    finally:
        OT.extract_text = real_extract  # type: ignore[assignment]
        OT.page_count = real_count  # type: ignore[assignment]
    assert res.ok, (res.error, res.meta)
    # `ToolResult` 的负载字段名是 `data`（`ok(...)` 包出来的那个 dict）。
    return dict(res.data)


def test_detect_text_layer_names_the_failed_pages(tmp_path: pathlib.Path) -> None:
    """负控（核心）：部分页失败时，reason 必须说清"哪几页没抽出来"。

    改前这一格的 reason 逐字是「有文本层：3 页可定位文本……
    引文校验可以正常判定 true/false」——它把"第 2 页没抽出来"读成了"可以正常判定"。
    """
    data = _call_detect(tmp_path, _PartialDoc())
    reason = str(data["reason"])
    assert "部分页抽取失败" in reason, reason
    assert "第 2 页" in reason, reason
    assert "quote_verified=null" in reason, reason
    assert data["failed_pages"] == [2], data
    assert data["has_text_layer"] is True, data


def test_detect_text_layer_without_failures_still_says_ok(tmp_path: pathlib.Path) -> None:
    """正控：没有失败页时，那句话必须照旧说"可以正常判定"。

    没有这一条，"一律说部分页失败"也能让上一条通过 —— 那会让这条判据变成噪音，
    而噪音比不报更糟（它会训练人忽略这一行）。
    """

    class _Clean:
        pages = ["a", "b", "c"]
        text = "a\nb\nc"
        source_kind = "pdf"
        encoding = None

        @staticmethod
        def failed_pages() -> tuple[int, ...]:
            return ()

    data = _call_detect(tmp_path, _Clean())
    reason = str(data["reason"])
    assert "可以正常判定" in reason, reason
    assert "部分页抽取失败" not in reason, reason
    assert data["failed_pages"] == [], data


class _AllFailedDoc:
    """每一页都抽取失败的文档替身：`pages=[]`（§6.3 契约）但逐页状态是 `failed`。

    这一档正是 `R3-2` 报的形态：`extract._finish_pdf` 旧版在"无文本层"那一支
    无条件写 `page_status=()`（空元组 = "没有逐页信息"），于是
    `failed_pages()` 返回 `()`，`ocr_tools` 里专为"抽取失败"写的那一支成了死代码，
    工具把"我们的后端在这份文件上全崩了"报成"疑似扫描件（本来就是空白页）"。

    这里刻意不走替身：直接用真 `_finish_pdf` 造文档，
    免得夹具自己把"失败页"编出来而掩盖了被测的那一行。
    """

    def __init__(self) -> None:
        self._doc = extract._finish_pdf([], "fitz", ["failed", "failed", "failed"])

    @property
    def pages(self) -> list[str]:
        return self._doc.pages

    @property
    def text(self) -> str:
        return self._doc.text

    @property
    def source_kind(self) -> str:
        return self._doc.source_kind

    @property
    def encoding(self) -> str | None:
        return self._doc.encoding

    @property
    def failed_pages(self) -> tuple[int, ...]:
        return self._doc.failed_pages


class _StubPageCount:
    """把 `page_count` 换成"就是 3 页"。

    判据只关心"页数已知且每页都抽取失败"这一档；让 `page_count` 去解析夹具里那个
    假 PDF 会把用例的成败挂在 PDF 解析器上（夹具的字节不是真 PDF），
    而那不是被测对象。替换掉之后这一条仍然能红：改前 `failed_pages` 是空的，
    分支会落到"疑似扫描件"那一句。
    """

    def __init__(self, n: int) -> None:
        self._n = n

    def __call__(self, *_a: object, **_kw: object) -> int:
        return self._n


def test_detect_text_layer_says_extraction_failed_when_every_page_failed(tmp_path: pathlib.Path) -> None:
    """`R3-2` 负控：整篇抽取失败 ⇒ 必须报"失败原因是抽取失败"，不许报成"疑似扫描件"。

    这一条在改前必红：`_finish_pdf` 把逐页状态丢掉之后，
    `failed_pages()` 是空的，于是走的是"每页抽出的文本去空白后都为空（疑似扫描件）"。
    """
    assert extract._finish_pdf([], "fitz", ["failed", "failed", "failed"]).failed_pages() == (1, 2, 3)
    data = _call_detect(tmp_path, _AllFailedDoc(), page_count=3)
    reason = str(data["reason"])
    assert "原因是抽取失败" in reason, reason
    assert "疑似扫描件" not in reason, reason
    assert data["failed_pages"] == [1, 2, 3], data
    assert data["has_text_layer"] is False, data
    assert data["pages"] == 0, data


def test_finish_pdf_still_reports_no_page_info_when_backend_gives_none() -> None:
    """正控（不许扩大化）：后端没给状态时，`_finish_pdf` 不能凭空造出"失败页"。

    `pages=[]`（后端一页都没返回）+ 没有状态 ⇒ 仍然只能是"没有逐页信息"：
    `failed_pages()` 空、`page_status_of()` 一律 `ok`（与历史行为逐字一致）。
    """
    doc = extract._finish_pdf([], "fitz", None)
    assert doc.pages == []
    assert doc.failed_pages() == ()
    assert doc.page_status_of(1) == "ok"
    # 内容推出来的状态仍然要保留：这是 `F-4` 原本就有的行为。
    blank = extract._finish_pdf(["", "文字"], "fitz", None)
    assert blank.page_status == ("empty", "ok")
    assert blank.failed_pages() == ()


def test_finish_pdf_logs_the_failed_case_differently_from_the_blank_case() -> None:
    """`R3B-2` 负控：日志面必须和工具面一样把"抽取失败"与"真空白"分开。

    改前两支打同一句「PDF 无文本层（疑似扫描件）」⇒ 日志里
    "我们的抽取链在这份文件上全崩了"（该换后端重试）与"它本来就是扫描件"
    （该走 OCR）长得一模一样，而处置完全不同。
    """
    import logging as _logging

    def capture(produce: object) -> list[dict]:
        recs: list[dict] = []

        class _H(_logging.Handler):
            def emit(self, record: _logging.LogRecord) -> None:
                recs.append({"level": record.levelname, "msg": record.getMessage()})

        logger = _logging.getLogger("agentflow.extract")
        old_level, old_prop = logger.level, logger.propagate
        h = _H()
        logger.addHandler(h)
        logger.setLevel(_logging.DEBUG)
        logger.propagate = False
        try:
            produce()  # type: ignore[operator]
        finally:
            logger.removeHandler(h)
            logger.setLevel(old_level)
            logger.propagate = old_prop
        return recs

    failed = capture(lambda: extract._finish_pdf([], "fitz", ["failed"] * 3))
    blank = capture(lambda: extract._finish_pdf([""], "fitz", None))
    t_failed = " ".join(r["msg"] for r in failed)
    t_blank = " ".join(r["msg"] for r in blank)

    assert "WARNING" in [r["level"] for r in failed], failed
    assert "抽取失败" in t_failed and "疑似扫描件" not in t_failed, failed
    assert "INFO" in [r["level"] for r in blank], blank
    assert "疑似扫描件" in t_blank and "抽取失败" not in t_blank, blank
    assert t_failed != t_blank, "两种形态的日志文本必须不同（这就是 `R3B-2` 的判据）"
