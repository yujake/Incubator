# -*- coding: utf-8 -*-
"""判据：`lit.stage_list` 的 note 把「没有正文不许判收」说对（业主 2026-11-20 裁定）。

## 这一句为什么必须对

A 每一趟判收前都会读 `lit.stage_list` 的返回；note 是它逐趟读到的口径。改前那一句
（AR1 之后）写的是「`metadata_only` 必须先试一次抽取（留 `extract_failed` 回执）才
允许按仅题录入库」—— 业主 2026-11-20 的裁定把这条路封了：

> 「读内容才能判东西，这样的话保证通过的肯定有内容，且能保证质量」

没有正文（未下载 / 抽取失败 / 只有题录或只有摘要）⇒ 不许判收。note 必须写这件事，
否则 A 会照着旧句子去凑一条"试过"的回执、然后理直气壮地把没有正文的候选判收。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| d | note 写「没有正文就不许判收」，逐档点名 `metadata_only` / `extract_failed` / 只有摘要一律不许入库，且不再含旧句「盘上没有字节的才报」 | 改前 note 教的是"拿 `extract_failed` 回执照仅题录入库" |
| e | 反真空：把旧句写回 note ⇒ d 必红 | 证明 d 的绿来自"新口径在、旧口径不在"，不是来自别的字 |
"""
from __future__ import annotations

import pytest

from agentflow import litstage as L
from agentflow.store import Store

#: d 必须出现的那一句（业主 2026-11-20 的语义）。
NO_CONTENT_NEEDLE = "没有正文就不许判收"
#: 改前那句反口径（d 的另一半：必须不在）。
OLD_CLAUSE = "盘上没有字节的才报 `metadata_only`"
#: 新口径那段可替换的字面（e 用它把旧句写回去）。
NEW_CLAUSE = (
    "仅题录（`metadata_only`）、抽取失败（`extract_failed`）、没下载 / 只有摘要的候选："
    "**不许判收、不许入库** —— 只能把题录留在候选记录里并写清为什么没读到"
    "（`lit.stage_reject` + 受控理由码：没下到 / 抽不出 / 只有题录或摘要）。"
)
#: 改前那一句原话（写回时用它整段替换）。
OLD_CLAUSE_TEXT = "盘上没有字节的才报 `metadata_only`（要指得出处）。"


def _note(store: Store) -> str:
    """走真调用面拿 note（`lit.stage_list` 交给 A 的就是这一个字段）。"""
    return str(L.list_candidates(store)["note"] or "")


def _note_problems(note: str) -> list[str]:
    """这一条 note 离真口径还差什么（空列表 = 合格）。"""
    out: list[str] = []
    if NO_CONTENT_NEEDLE not in note:
        out.append(f"note 没写「没有正文就不许判收」：缺 {NO_CONTENT_NEEDLE!r}")
    for tier in ("metadata_only", "extract_failed"):
        if tier not in note:
            out.append(f"note 没点名 {tier!r} 这一档不许判收")
    if "摘要" not in note:
        out.append("note 没写「摘要不算正文」那一半")
    if OLD_CLAUSE in note:
        out.append(f"note 还留着旧口径（盘上没有字节才报仅题录）：{OLD_CLAUSE!r}")
    return out


@pytest.fixture
def store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def test_d_the_stage_list_note_says_no_content_means_no_admission(store: Store) -> None:
    """d：note 说的是真口径（没有正文不许判收），不是旧那句「盘上没有字节才报」。"""
    problems = _note_problems(_note(store))
    assert problems == [], "lit.stage_list 的 note：\n  - " + "\n  - ".join(problems)


def test_e_writing_the_old_clause_back_turns_it_red(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把旧句写回 note ⇒ d 必红（d 不是空转）。"""
    live = L._stage_list_note(0)
    assert _note_problems(live) == []
    old = live.replace(NEW_CLAUSE, OLD_CLAUSE_TEXT)
    assert old != live, "盘上找不到新口径那一段 ⇒ 反真空打不中（d 量的不是它）"
    monkeypatch.setattr(L, "_stage_list_note", lambda waiting_count: old)
    replay = _note(store)
    assert _note_problems(replay) != [], (
        "把旧句写回 note 之后校验仍然绿 —— d 量的不是「没有正文不许判收」这件事")
