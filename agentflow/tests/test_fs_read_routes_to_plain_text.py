# -*- coding: utf-8 -*-
"""消费论文的请求要自动路由到同名纯文字稿（业主 2026-10-17 口径）。

原话：*"把其它智能体要消费论文的请求自动路由到同名纯文字稿，其它智能体不必再做 OCR 等操作。"*

背景（T5 真机读数，`draft/136`）：四个角色里没有一个做得到"把 PDF 变成正文"；
`fs.read(library/*.pdf)` 一律 `binary` 拒收 ⇒ B 只能去调 `ocr.run`（后端不可用）、
最后靠 M 写脚本才解开。现在改成：A 用 `text.extract` 转好的那份同名 `.txt` 就在同一层，
读 PDF 的请求直接路由过去 —— 而且必须说清"这是自动改读的"（`routed_from`），
不许静默替换来源。

这一组钉三态（含一条反折平）：
1. 有同名纯文字稿 ⇒ 路由（`routed_from` 指回 PDF、正文是稿子）；
2. 没有 ⇒ 仍是 `binary` 且出路指向 A 的 `text.extract`；
3. 反折平：非 PDF 的二进制（例如图片）不许被路由（没有"同名稿"这回事）。
"""

from __future__ import annotations

import pathlib

from agentflow.store import Store
from agentflow.tools import build_registry

PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\n%%EOF\n\x00\x00"
TEXT = "===== page 1 =====\n探针：这份纯文字稿就是下游该读的东西。\n"


def _reg(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init()
    (ws / "library").mkdir(parents=True, exist_ok=True)
    (ws / "library" / "paper.pdf").write_bytes(PDF_BYTES)
    (ws / "library" / "photo.png").write_bytes(PDF_BYTES)      # 非 PDF 的二进制（第三条用）
    return ws, build_registry(store=store, workspace_root=ws).registry


def _call(reg, path: str) -> tuple[bool, dict]:
    """`fs.read` 的 `data` 是标量文本（不是字典）⇒ 正文单独取，其余读 `meta`。"""
    res = reg.call("fs.read", role="B", path=path)
    payload: dict = {}
    val = getattr(res, "meta", None)
    if isinstance(val, dict):
        payload.update(val)
    data = getattr(res, "data", None)
    if isinstance(data, str):
        payload["text"] = data
    elif isinstance(data, dict):
        payload.update(data)
    return bool(getattr(res, "ok", False)), {**payload, "error": str(getattr(res, "error", "") or "")}


def test_a_pdf_with_a_sibling_text_is_routed(tmp_path: pathlib.Path) -> None:
    """正控：有同名纯文字稿 ⇒ 路由过去，并把"原本要读的是哪一份"说清楚。"""
    ws, reg = _reg(tmp_path)
    (ws / "library" / "paper.txt").write_text(TEXT, encoding="utf-8")
    ok, got = _call(reg, "library/paper.pdf")
    assert ok is True, got
    assert got.get("path") == "library/paper.txt", got
    assert got.get("routed_from") == "library/paper.pdf", got
    assert "探针" in str(got.get("text") or ""), got


def test_a_pdf_without_a_text_still_refuses_and_points_at_a(tmp_path: pathlib.Path) -> None:
    """负控：还没有纯文字稿 ⇒ 仍拒，而且出路必须指向 A 的 `text.extract`。"""
    _ws, reg = _reg(tmp_path)
    ok, got = _call(reg, "library/paper.pdf")
    assert ok is False, got
    assert got.get("kind") == "binary", got
    assert "text.extract" in str(got.get("error") or ""), got


def test_a_non_pdf_binary_is_not_routed(tmp_path: pathlib.Path) -> None:
    """反折平：图片这类二进制不许被路由（它旁边没有"同名稿"这回事）。"""
    ws, reg = _reg(tmp_path)
    (ws / "library" / "photo.txt").write_text(TEXT, encoding="utf-8")   # 故意放一份同名稿
    ok, got = _call(reg, "library/photo.png")
    assert ok is False, got
    assert got.get("kind") == "binary", got
