# -*- coding: utf-8 -*-
"""D13：`register_conjecture` 按规范化 `statement` 判重（`draft/39` §3.9/§3.12）。

## 真机读数（p6e，25 次派活）

5 次成功落了 5 行，其中 `0001/0003/0004` 的规范化 `statement` sha 完全相同、
`0002` 只差标点 —— 原因是"重试即新建" + "想更新却没带 id" 两件事叠加，
而工具当时不判重。修法（用户裁"甲+乙"）：

1. 没给 `conjecture_id` ⇒ 先按规范化 `statement` 找同一条 ⇒ 命中就返回既有行
   并把本次给的状态/证据合并进去（结果里记 `duplicate=true` 与 `duplicate_of`）；
2. 真要新建 ⇒ 显式 `force_new=true`（调用方的决定，不是默认行为）。

规范化只做"空格与标点"（中英文都去）—— 不做全角/半角映射：那要一张映射表，
换一个环境就漂，而它换来的判重收益远小于"判据自己漂了"的代价。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow.store import Store
from agentflow.tools import conjecture_tools as CT

_TESTABLE = {"parameters": "n", "criterion": "该族非空", "falsified_by": "n=3 时为空"}


def _store(tmp_path: pathlib.Path) -> Store:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return st


def test_the_same_sentence_does_not_create_a_second_row(tmp_path):
    """正控（D13 的要害）：同一句话（连标点都一样）登记两次 ⇒ 只有一行。"""
    st = _store(tmp_path)
    a = CT.register_conjecture(st, statement="n≥3 时该族非空。", origin="gap",
                               testable=_TESTABLE)
    b = CT.register_conjecture(st, statement="n≥3 时该族非空。", origin="gap",
                               testable=_TESTABLE)
    assert a["duplicate"] is False and a["conjecture_id"] == "0000", a
    assert b["duplicate"] is True and b["duplicate_of"] == "0000", b
    assert len(st.rows("conjectures")) == 1, st.rows("conjectures")


def test_punctuation_and_whitespace_do_not_hide_a_duplicate(tmp_path):
    """判重的口径：只差标点/空格 ⇒ 仍然算同一条（`0002` 当年就是只差逗号）。"""
    st = _store(tmp_path)
    CT.register_conjecture(st, statement="n≥3 时，该族非空。", origin="gap",
                           testable=_TESTABLE)
    again = CT.register_conjecture(st, statement=" n≥3 时 该族非空 ", origin="gap",
                                   testable=_TESTABLE)
    assert again["duplicate"] is True and again["conjecture_id"] == "0000", again
    assert len(st.rows("conjectures")) == 1


def test_force_new_is_the_only_way_to_add_a_lookalike(tmp_path):
    """`force_new=true` 是显式的新建（调用方的决定）；两条并存且各自有 id。"""
    st = _store(tmp_path)
    CT.register_conjecture(st, statement="n≥3 时该族非空。", origin="gap",
                           testable=_TESTABLE)
    forced = CT.register_conjecture(st, statement="n≥3 时该族非空。", origin="gap",
                                    testable=_TESTABLE, force_new=True)
    assert forced["duplicate"] is False and forced["conjecture_id"] == "0001", forced
    assert len(st.rows("conjectures")) == 2


def test_a_different_sentence_still_creates_a_new_row(tmp_path):
    """反真空：不同的话照旧新建（判重不许变成"什么都命中"）。"""
    st = _store(tmp_path)
    CT.register_conjecture(st, statement="n≥3 时该族非空。", origin="gap",
                           testable=_TESTABLE)
    other = CT.register_conjecture(st, statement="n≥4 时该族非空。", origin="gap",
                                   testable=_TESTABLE)
    assert other["duplicate"] is False and other["conjecture_id"] == "0001", other
    assert len(st.rows("conjectures")) == 2


def test_hitting_an_existing_row_still_merges_the_new_state(tmp_path):
    """命中既有行 ≠ 什么都不做：本次给的状态要合并进去（D13 的另一半"更新"）。"""
    st = _store(tmp_path)
    CT.register_conjecture(st, statement="n≥3 时该族非空。", origin="gap",
                           testable=_TESTABLE)
    merged = CT.register_conjecture(st, statement="n≥3 时该族非空。", origin="gap",
                                    status="testing", notes="本轮开始枚举")
    row = st.rows("conjectures")[0]
    assert merged["duplicate"] is True, merged
    assert row["status"] == "testing" and row["notes"] == "本轮开始枚举", row


def test_giving_an_id_still_means_update(tmp_path):
    """给了 `conjecture_id` ⇒ 照旧是更新（判重只在"没给 id"时才介入）。"""
    st = _store(tmp_path)
    CT.register_conjecture(st, statement="n≥3 时该族非空。", origin="gap",
                           testable=_TESTABLE)
    upd = CT.register_conjecture(st, statement="n≥3 时该族非空（改写）", origin="gap",
                                 conjecture_id="0000", notes="按 id 更新")
    assert upd["duplicate"] is False and upd["conjecture_id"] == "0000", upd
    assert len(st.rows("conjectures")) == 1
    assert st.rows("conjectures")[0]["notes"] == "按 id 更新"


def test_the_normalisation_key_is_stable_and_hides_only_punctuation():
    """判重键本身：同一句话 ⇒ 同键；加一个实词 ⇒ 不同键（它只抹标点与空白）。"""
    assert CT._norm_statement("n≥3 时该族非空。") == CT._norm_statement(" n≥3 时该族非空 ")
    assert CT._norm_statement("n≥3 时该族非空。") != CT._norm_statement("n≥3 时该族为空。")
