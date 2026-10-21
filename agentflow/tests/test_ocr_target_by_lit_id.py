# -*- coding: utf-8 -*-
"""`ocr.*` 要收下第一猜：给"文献编号"而不是拼路径（业主 2026-10-16 亲测口径）。

## 为什么补这个文件

业主口径（逐字）："凡是你凭感觉第一次运行工具发现红了，都要假想真实智能体也会在这里
困惑并浪费时间和 token。" 我第一次敲 `ocr.detect_text_layer(lit_id="000000")` 就红了：
它只认 `path`，而 B 整个域都按 `lit_id` 说话（`literature` 行、`run_once` 抽的就是它）。

这一组钉四件事（含两个负控）：

1. 给编号 ⇒ 能work（并且 `lit:NNNNNN` 那种带前缀的写法也收）；
2. 给路径 ⇒ 老行为一字不变（负控：别为了新猜把旧路弄坏）；
3. 两者都不给 ⇒ 可读拒绝 `no_target`（"这一格判不了"，不是"文件没问题"）；
4. 编号不认得 ⇒ `unknown_lit_id`，并且把盘上有的编号列出来（有出路）。
"""

from __future__ import annotations

import pathlib
import shutil

import pytest

from agentflow.store import Store
from agentflow.tools import build_registry

_TEST_PDF = pathlib.Path(__file__).resolve().parent.parent / "temp" / "_lit_dl"


def _real_pdf(tmp_path: pathlib.Path) -> bytes:
    """造一份有文本层的真 PDF（`ocr.detect_text_layer` 要的是这个，不是 `%PDF` 头）。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Fermat's Last Theorem probe page.")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def wired(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init()
    name = "probe.pdf"
    store.library_path(name).write_bytes(_real_pdf(tmp_path))
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {
            "lit_id": "000000", "title": "probe", "summary": "s", "year": "2022", "doi": "",
            "type": "J", "path": name, "processed": False, "source_request_ids": [],
            "download": {"status": "ok"},
        })
    reg = build_registry(store=store, workspace_root=ws).registry
    return store, reg, name


def _call(reg, **kw):
    res = reg.call("ocr.detect_text_layer", role="B", **kw)
    payload = {}
    for attr in ("data", "meta"):
        val = getattr(res, attr, None)
        if isinstance(val, dict):
            payload.update(val)
    return res, payload


def test_a_lit_id_is_accepted(wired) -> None:
    """正控（第一猜）：给编号就能跑，不必自己拼路径。"""
    _store, reg, _name = wired
    res, payload = _call(reg, lit_id="000000")
    assert res.ok is True, (res, payload)
    assert payload.get("has_text_layer") is True, payload


def test_a_prefixed_lit_id_is_accepted_too(wired) -> None:
    """边界：`lit:NNNNNN` 这种带前缀的写法也要收（两种写法都自然）。"""
    _store, reg, _name = wired
    res, _payload = _call(reg, lit_id="lit:000000")
    assert res.ok is True, res


def test_a_path_still_works(wired) -> None:
    """负控：给路径的老行为一字不变（别为了新猜把旧路弄坏）。"""
    store, reg, name = wired
    res, payload = _call(reg, path=str(store.library_path(name)))
    assert res.ok is True, (res, payload)
    assert payload.get("has_text_layer") is True, payload


def test_neither_path_nor_lit_id_is_a_readable_refusal(wired) -> None:
    """负控（三态）：两者都不给 ⇒ 可读拒绝，并说清"这一格判不了"。"""
    _store, reg, _name = wired
    res, payload = _call(reg)
    assert res.ok is False, res
    assert payload.get("kind") == "no_target", payload
    assert "判不了" in str(res.error), res.error


def test_an_unknown_lit_id_lists_what_is_on_disk(wired) -> None:
    """有出路：编号不认得时要把盘上有的编号给出来（不是只说一句"找不到"）。"""
    _store, reg, _name = wired
    res, payload = _call(reg, lit_id="999999")
    assert res.ok is False, res
    assert payload.get("kind") == "unknown_lit_id", payload
    assert payload.get("known") == ["000000"], payload
