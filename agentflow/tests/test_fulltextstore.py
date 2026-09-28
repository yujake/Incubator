# -*- coding: utf-8 -*-
"""`fulltextstore` 的判据：正控之外，四种坏法各有一条负控。

为什么负控是主角：这个模块的产出会被逐字引文回验当成"依据文本"。一个永远说 ok
的校验器与没有校验器在输出上一模一样，却更坏 —— 它让人以为核过了。所以每一条
"要拒绝"的路径都配一条真的走进去的用例，且断言报错串里点名是哪一层坏。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import fulltextstore as FS


def _ref_for(tmp_path: Path, pages: list[str], pdf_sha: str = "ab" * 32) -> dict:
    """按生产路径造一条引用（`put` 是唯一的产出点，测试不自己拼 JSON）。"""
    return FS.put(pages, store_dir=FS.store_dir_for(tmp_path), pdf_sha256=pdf_sha,
                  pdf_path=str(tmp_path / "x.pdf"), pdf_bytes=11, backend="pdf")


def test_put_then_load_roundtrip(tmp_path: Path) -> None:
    """正控：存了再读，逐页文本一字不差，且体检读数说 ok。"""
    pages = ["第一页 alpha", "第二页 beta gamma", "第三页\n换行 delta"]
    ref = _ref_for(tmp_path, pages)
    got, why = FS.load(ref, allowed_dir=FS.store_dir_for(tmp_path))
    assert why == ""
    assert got == pages
    report = FS.verify_ref(ref, allowed_dir=FS.store_dir_for(tmp_path))
    assert report["ok"] is True
    assert report["pages"] == 3
    assert report["chars"] == sum(len(p) for p in pages)


def test_put_is_idempotent_and_appends_new_extractor_versions(tmp_path: Path) -> None:
    """同一份正文重复 `put` 不重写；同一本书的不同正文各占一个文件（追加式）。

    后半条是这次改动的核心不变量：只按 pdf 哈希命名会让新抽取器覆盖老文件，
    历史产物的引用当场失效。所以文件名里必须带正文哈希。
    """
    pages = ["a", "b"]
    ref1 = _ref_for(tmp_path, pages)
    stamp = Path(ref1["path"]).stat().st_mtime_ns
    ref2 = _ref_for(tmp_path, pages)
    assert ref2["path"] == ref1["path"]
    assert ref2["file_sha256"] == ref1["file_sha256"]
    assert Path(ref1["path"]).stat().st_mtime_ns == stamp, "同一内容不该重写文件"

    ref3 = _ref_for(tmp_path, ["a", "b", "c"])
    assert ref3["path"] != ref1["path"], "不同正文必须各占一个文件"
    for ref in (ref1, ref3):
        pages_got, why = FS.load(ref, allowed_dir=FS.store_dir_for(tmp_path))
        assert why == "" and pages_got


def test_load_refuses_missing_file(tmp_path: Path) -> None:
    """负控：store 文件被删 ⇒ 点名 `store_file_missing`，且不返回任何文本。"""
    ref = _ref_for(tmp_path, ["a"])
    Path(ref["path"]).unlink()
    pages, why = FS.load(ref, allowed_dir=FS.store_dir_for(tmp_path))
    assert pages == []
    assert "store_file_missing" in why


def test_load_refuses_byte_level_tampering(tmp_path: Path) -> None:
    """负控：文件被改一个字节（正文哈希与页数都没变）⇒ 字节哈希层必须抓住。"""
    ref = _ref_for(tmp_path, ["alpha", "beta"])
    target = Path(ref["path"])
    target.write_text(target.read_text(encoding="utf-8").replace('"beta"', '"beta "'),
                      encoding="utf-8", newline="\n")
    pages, why = FS.load(ref, allowed_dir=FS.store_dir_for(tmp_path))
    assert pages == []
    assert "store_file_hash_mismatch" in why


def test_load_refuses_text_hash_mismatch_even_if_file_hash_matches(tmp_path: Path) -> None:
    """负控：把文件换掉并把引用里的 `file_sha256` 一起改成新的 ⇒ 正文哈希层仍要抓住。

    这一条是刻意的"绕过第一层"：只看字节哈希的实现在这里会放行，
    于是被换掉的正文会被当成依据。
    """
    ref = _ref_for(tmp_path, ["alpha", "beta"])
    target = Path(ref["path"])
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["text_pages"] = ["totally", "different"]
    payload["pages"] = 2
    payload["chars"] = 15
    target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
                      encoding="utf-8", newline="\n")
    forged = dict(ref, file_sha256=FS.file_sha256(target))
    pages, why = FS.load(forged, allowed_dir=FS.store_dir_for(tmp_path))
    assert pages == []
    assert "store_text_hash_mismatch" in why


def test_load_refuses_pages_mismatch(tmp_path: Path) -> None:
    """负控：页数对不上 ⇒ `store_pages_mismatch`（把断言页码钉在错页上就是这么来的）。"""
    ref = _ref_for(tmp_path, ["a", "b"])
    forged = dict(ref, pages=99)
    # 页数层在正文哈希层之后；把两条都保持自洽才走得到页数那一层
    forged["file_sha256"] = FS.file_sha256(Path(ref["path"]))
    pages, why = FS.load(forged, allowed_dir=FS.store_dir_for(tmp_path))
    assert pages == []
    assert "store_pages_mismatch" in why


def test_load_refuses_out_of_store_path(tmp_path: Path) -> None:
    """负控：引用指向 store 之外 ⇒ 拒绝。

    这是"引文被凭空验成真"的入口：一份被改过的 evidence.json 可以把 path 指到
    任意文件，于是回验拿一份与文献无关的文本当依据。
    """
    outside = tmp_path / "elsewhere.json"
    outside.write_text(json.dumps({"store_version": FS.STORE_VERSION,
                                   "text_pages": ["forged"],
                                   "text_sha256": FS.pages_text_sha256(["forged"])}),
                       encoding="utf-8", newline="\n")
    pages, why = FS.load({"path": str(outside),
                          "text_sha256": FS.pages_text_sha256(["forged"])})
    assert pages == []
    assert "store_out_of_store" in why


def test_load_refuses_unknown_store_version(tmp_path: Path) -> None:
    """负控：store_version 不认识 ⇒ 拒绝（宁可没查成，也不按猜的格式读证据）。"""
    ref = _ref_for(tmp_path, ["a"])
    target = Path(ref["path"])
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["store_version"] = FS.STORE_VERSION + 1
    target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
                      encoding="utf-8", newline="\n")
    pages, why = FS.load(dict(ref, file_sha256=FS.file_sha256(target)),
                         allowed_dir=FS.store_dir_for(tmp_path))
    assert pages == []
    assert "store_not_a_store_file" in why


def test_put_refuses_empty_text(tmp_path: Path) -> None:
    """空正文不是证据，是噪声：`put` 必须当场拒绝，而不是写出一个空文件。"""
    with pytest.raises(ValueError):
        FS.put([], store_dir=FS.store_dir_for(tmp_path), pdf_sha256="ab" * 32)


def test_inventory_reports_empty_directory_explicitly(tmp_path: Path) -> None:
    """空库与没有库都要能区分开：不存在 ⇒ `[]`（调用方据此说"没有 store"）。"""
    assert FS.inventory(tmp_path / "nope") == []
    rows = FS.inventory(FS.store_dir_for(tmp_path))
    assert rows == []
    _ref_for(tmp_path, ["a"])
    rows = FS.inventory(FS.store_dir_for(tmp_path))
    assert len(rows) == 1 and rows[0]["ok"] is True and rows[0]["pages"] == 1


def test_verify_ref_reports_non_mapping(tmp_path: Path) -> None:
    """`text_ref` 是字符串/None 时给读数而不是抛异常（产物可能是手工改过的）。"""
    for bad in (None, "D:/x.json", 7):
        report = FS.verify_ref(bad)
        assert report["ok"] is False
        assert "store_not_a_mapping" in report["problem"]


def test_selftest_passes() -> None:
    """模块自带的自检入口必须是绿的（它含正控 + 三个负控）。"""
    assert FS.selftest() == 0
