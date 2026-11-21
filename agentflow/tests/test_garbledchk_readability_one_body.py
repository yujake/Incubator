# -*- coding: utf-8 -*-
"""GARBLECHK：可读性判据只有一处真身；判拒理由按槽位/按文件生成。

## 现场（真机 lp-ball-15，2026-11-21，逐字可复算）

种子链 25 份真 PDF，流水线判拒 7 份，判拒理由都是"抽不出可读正文"。同一批文件
`scripts/seed_corpus.py --verify` 却逐份判 usable。两套判据的分歧点不是"哪份文件坏"，
是"乱码"这件事被写成了两份：

* 流水线（`litread.garbled_text`）：NUL 个数 > 0、U+FFFD > 0、控制字符占比 > 2%
  —— 任何一条命中就拒。7 份被拒文件全部是"NUL 个数 > 0"这一条命中，控制字符
  占比都在 2% 以内、U+FFFD 全是 0；
* 种子验证（`seed_corpus._reading_of` / `_judge`）：字数 / 完整词 / 字母占比 /
  U+FFFD，一条都不数 NUL/控制字符。

真读数（`temp/garbledchk/readings.json`）：那 7 份的完整英文词 2609–44163 个、
字母占比 0.62–0.92、U+FFFD 全 0，NUL 占比 0.000008–0.0015。按可读性本体判，
它们是可读的 —— PDF 文字层里少量 NUL 来自没有 ToUnicode 映射的字形，不是错位解码。

## 判据（先红后绿，反真空）

| 格 | 判据 | 改前 | 改后 |
|---|---|---|---|
| a | `seed/.../290c…lp.pdf`（77 个 NUL、正文可读）⇒ `readable`，`text.extract` 真写 `.txt` | `garbled_text` | ok |
| b | 符号汤 PDF / 空白页（扫描件）⇒ 仍判 `garbled` / `no_text_layer` | 符号汤会被旧口径放行 | 仍拒 |
| c | 两槽共用一个点名的 `note` ⇒ 两条 `reject_reason` 不同、各只写自己的文件与读数 | 逐字相同（串号） | 各写各的 |
| d1 | 把 NUL 阈值打桩回 0（旧口径）⇒ a 必红 | — | 红 |
| d2 | 把 `_reject_reason` 打桩回旧写法（note 原样）⇒ c 必红 | — | 红 |

`d` 的两格是反真空：a / c 的绿不是"判据被关掉了"，是同一条判据在被观测。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import extract as E
from agentflow import litavail as AV
from agentflow import litread as LR
from agentflow import litstage as L
from agentflow.store import Store
from agentflow.tools import build_for_role

ROOT = pathlib.Path(__file__).resolve().parents[1]
RID = "r-000001"

#: 真机被拒的 7 份之一：22 页、51416 字符、77 个 NUL、U+FFFD 0、完整词 3168。
#: `seed/literature/files/` 是入库的种子文件（与真机 `library/` 同一份字节）。
NUL_NOISY = ROOT / "seed" / "literature" / "files" / (
    "290c7eb63abe-resilience-of-cube-slicing-in-lp.pdf")
#: 真·乱码：有文本层、抽出来是符号汤（完整词 0 个），且没有 NUL/控制字符
#: —— 旧的流水线口径会把它当可读放行，这一格守住"闸没被关掉"。
SYMBOL_SOUP = ROOT / "tests" / "fixtures" / "garbled-symbol-layer.pdf"


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


@pytest.fixture
def reg(store: Store):
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def _put(store: Store, src: pathlib.Path) -> str:
    """把一份真 PDF 放进工作区 `library/`，返回相对路径（posix 形）。"""
    dest = store.library / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    return f"library/{src.name}"


def _stage_two(reg, urls: list[str]) -> list[str]:
    entries = [{
        "title": f"Per-slot reason sample {i}",
        "doi": f"10.55/{i}",
        "provider": "stub",
        "year": 2020 + i,
        "type_code": "J",
        "summary": "",
        "url": url,
        "relevance": "与本次检索相关（判据夹具）",
    } for i, url in enumerate(urls)]
    res = reg.call("lit.stage_add", request_id=RID, entries=entries)
    assert res.ok, res.error
    return [str(x["slot"]) for x in res.unwrap()["staged"]]


def _row(store: Store, slot: str) -> dict:
    row = next((r for r in store.rows("lit_candidates")
                if str(r.get("slot")) == str(slot)), None)
    assert row is not None, f"盘上没有槽位 {slot}"
    return dict(row)


# ====================================================================== a 少量 NUL 可读


def test_a_a_pdf_with_a_few_nul_bytes_is_still_readable(store: Store, reg) -> None:
    """a. 有少量 NUL 但正文可读的真 PDF ⇒ 判可读，`text.extract` 真写纯文字稿。"""
    doc = E.extract_text(NUL_NOISY)
    reading = LR.assess_text(doc.text)
    assert reading["nul_bytes"] > 0, "夹具应当带 NUL，否则这条判据测的是别的东西"
    assert reading["replacement_chars"] == 0
    assert reading["long_words"] >= LR.READABLE_MIN_LONG_WORDS
    assert reading["state"] == "readable", reading
    assert LR.garbled_text(doc.text)[0] is False, "少量 NUL 又被判成乱码"

    rel = _put(store, NUL_NOISY)
    res = reg.call("text.extract", path=rel)
    assert res.ok, (res.error, dict(res.meta))
    data = res.unwrap()
    assert data["quality"]["nul_bytes"] > 0
    assert data["quality"]["state"] == "readable"
    assert (store.root / data["path"]).is_file(), "判可读却没写下纯文字稿"


# ====================================================================== b 真乱码仍拒


def test_b_a_really_garbled_pdf_and_a_scan_are_still_refused(store: Store, reg) -> None:
    """b. 真乱码（符号汤）仍判 `garbled`；扫描件（空白页）仍判 `no_text_layer`。"""
    doc = E.extract_text(SYMBOL_SOUP)
    reading = LR.assess_text(doc.text)
    assert reading["chars"] >= LR.READABLE_MIN_CHARS
    assert reading["nul_bytes"] == 0 and reading["control_chars"] == 0, (
        "夹具应当是'没有噪声但读不了'的形态，否则测的是 NUL 那条判据")
    assert reading["state"] == "garbled", reading
    assert LR.garbled_text(doc.text)[0] is True

    rel = _put(store, SYMBOL_SOUP)
    res = reg.call("text.extract", path=rel)
    assert not res.ok, "符号汤居然抽读成功"
    assert str(res.meta.get("kind")) == "garbled_text", dict(res.meta)
    assert not (store.library / f"{SYMBOL_SOUP.stem}.txt").is_file(), "乱码被写进了 library/"

    # 扫描件：有字节、没有文本层 ⇒ 仍走 no_text_layer（不是被新判据放行）
    assert LR.fulltext_tier(bytes_on_disk=1024, pages=["", "  "], text="") == \
        LR.FULLTEXT_NO_TEXT_LAYER


# ====================================================================== c 判拒理由逐槽


def test_c_reject_reasons_are_generated_per_slot(store: Store, reg) -> None:
    """c. 两槽共用一个点名三份文件的 `note` ⇒ 理由不同、各自只写自己的文件与读数。"""
    slots = _stage_two(reg, ["library/alpha-paper.pdf", "library/beta-paper.pdf"])
    AV.record_read(store.root, RID, slots[0], LR.FULLTEXT_EXTRACT_FAILED,
                   note="text.extract.garbled_text",
                   quality={"chars": 51416, "control_chars": 792, "nul_bytes": 77,
                            "replacement_chars": 0, "control_ratio": 0.0154})
    shared = (f"text.extract 三次都判 garbled_text（{slots[0]} control_chars=349/nul=16；"
              f"{slots[1]} 全篇 control=16/nul=3）")
    res = reg.call("lit.stage_reject", slots=slots, reason_code="rejected_low_quality",
                   note=shared)
    assert res.ok, res.error

    first = str(_row(store, slots[0])["reject_reason"])
    second = str(_row(store, slots[1])["reject_reason"])
    assert first != second, "两槽的判拒理由逐字相同（串号）"
    for own_file, other, other_file, reason in (
            ("alpha-paper.pdf", slots[1], "beta-paper.pdf", first),
            ("beta-paper.pdf", slots[0], "alpha-paper.pdf", second)):
        assert own_file in reason, reason
        assert other_file not in reason, f"这一行在描述别的文件：{reason}"
        if other in reason:
            raise AssertionError(f"这一行在描述别的槽位：{reason}")
    # 读数也只写自己那份：77 个 NUL 只该出现在第一槽
    assert "nul_bytes=77" in first, first
    assert "nul_bytes=77" not in second, second

    # 第二种串号形态（真机 000003/000004）：一句话用缩写并列两份文件、不写槽位号。
    pair = _stage_two(reg, ["library/gamma-paper.pdf", "library/delta-paper.pdf"])
    abbreviated = ("两份 text.extract 均回 kind=garbled_text、不写盘："
                   "gamm...paper.pdf（control_ratio=0.01528, nul_bytes=77）、"
                   "delt...paper.pdf（0.01061, 58）")
    res = reg.call("lit.stage_reject", slots=pair, reason_code="rejected_low_quality",
                   note=abbreviated)
    assert res.ok, res.error
    gamma = str(_row(store, pair[0])["reject_reason"])
    delta = str(_row(store, pair[1])["reject_reason"])
    assert gamma != delta, "缩写并列也会串号"
    assert "gamma-paper.pdf" in gamma and "delta-paper.pdf" not in gamma, gamma
    assert "delta-paper.pdf" in delta and "gamma-paper.pdf" not in delta, delta


# ====================================================================== d 反真空


def test_d1_zero_tolerance_nul_criterion_makes_a_red(monkeypatch) -> None:
    """d1. 把 NUL 阈值打桩回旧口径（0）⇒ 那份可读 PDF 立刻变回 garbled。"""
    monkeypatch.setattr(LR, "GARBLED_NUL_RATIO_MAX", 0.0)
    reading = LR.assess_text(E.extract_text(NUL_NOISY).text)
    assert reading["state"] == "garbled", (
        "旧口径下仍判可读 —— 说明 a 量的不是 NUL 这条判据")
    assert LR.garbled_text(E.extract_text(NUL_NOISY).text)[0] is True


def test_d2_verbatim_note_write_makes_c_red(store: Store, reg, monkeypatch) -> None:
    """d2. 把理由生成打桩回旧写法（`note` 原样）⇒ 两槽理由重新逐字相同。"""
    monkeypatch.setattr(L, "_reject_reason",
                        lambda row, note, **kwargs: str(note or ""))
    slots = _stage_two(reg, ["library/alpha-paper.pdf", "library/beta-paper.pdf"])
    shared = "一段话同时写了 %s 与 %s 两份文件" % (slots[0], slots[1])
    res = reg.call("lit.stage_reject", slots=slots, reason_code="rejected_low_quality",
                   note=shared)
    assert res.ok, res.error
    first = str(_row(store, slots[0])["reject_reason"])
    second = str(_row(store, slots[1])["reject_reason"])
    assert first == second == shared, (
        "旧写法下两槽理由应当相同 —— 说明 c 的绿来自按槽位生成")
