# -*- coding: utf-8 -*-
"""判据：`lit.stage_list` 的 note 把 `metadata_only` 的真口径说对（业主 2026-11-16 裁定 AR1）。

## 改前那一句是反的

`litstage.list_candidates` 的 note 写着「盘上没有字节的才报 `metadata_only`」——
真口径是：`metadata_only` 不是"零读可入"，它必须有一次"试过、拿不到可读文本"的
`extract_failed` 回执；零回执（`no_extract`）由 `litstage._read_evidence_gate` 按
`no_read_evidence` 整批拒、逐槽点名（口径真身见 `litavail.py` 模块头与
`litstage._read_evidence_gate` 的 docstring）。A 在真机上读到的就是这一句 note。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| d | note 含「必须先试一次抽取」这一件事（留 `extract_failed` 回执才允许按仅题录入库），点名零回执的后果（`no_read_evidence` 整批拒），且不再含旧句「盘上没有字节的才报」 | 改前 note 把 `metadata_only` 说成"盘上没有字节才报"，与读证据闸相反 |
| e | 反真空：把旧句写回 note ⇒ d 必红 | 证明 d 的绿来自"新口径在、旧口径不在"，不是来自别的字 |
"""
from __future__ import annotations

import pytest

from agentflow import litstage as L
from agentflow.store import Store

#: d 必须出现的那一句（业主裁定 AR1 的语义）。
ATTEMPT_NEEDLE = "必须先试一次抽取"
#: 改前那句反口径（d 的另一半：必须不在）。
OLD_CLAUSE = "盘上没有字节的才报 `metadata_only`"
#: 新口径那段可替换的字面（e 用它把旧句写回去）。
NEW_CLAUSE = (
    "报 `metadata_only` 也一样：**必须先试一次抽取**（留下 `extract_failed` 回执）"
    "才允许按仅题录入库，零回执的仅题录会被同一道闸按零读取尝试整批拒掉"
    "（要指得出处）。"
)
#: 改前那一句原话（写回时用它整段替换）。
OLD_CLAUSE_TEXT = "盘上没有字节的才报 `metadata_only`（要指得出处）。"


def _note(store: Store) -> str:
    """走真调用面拿 note（`lit.stage_list` 交给 A 的就是这一个字段）。"""
    return str(L.list_candidates(store)["note"] or "")


def _note_problems(note: str) -> list[str]:
    """这一条 note 离真口径还差什么（空列表 = 合格）。"""
    out: list[str] = []
    if ATTEMPT_NEEDLE not in note:
        out.append(f"note 没写 `metadata_only` 必须先试一次抽取：缺 {ATTEMPT_NEEDLE!r}")
    if "extract_failed" not in note:
        out.append("note 没点名要留 `extract_failed` 回执 —— 只说「试一次」"
                   "不够，A 不知道要留哪一条")
    if "no_read_evidence" not in note:
        out.append("note 没点名零回执的后果（`no_read_evidence` 整批拒）")
    if OLD_CLAUSE in note:
        out.append(f"note 还留着旧口径（盘上没有字节才报仅题录）：{OLD_CLAUSE!r}")
    return out


@pytest.fixture
def store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def test_d_the_stage_list_note_says_metadata_only_needs_an_attempt(store: Store) -> None:
    """d：note 说的是真口径（先试一次抽取、留回执），不是旧那句「盘上没有字节才报」。"""
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
        "把旧句写回 note 之后校验仍然绿 —— d 量的不是「先试一次抽取」这件事")
