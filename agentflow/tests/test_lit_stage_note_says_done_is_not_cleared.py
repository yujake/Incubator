# -*- coding: utf-8 -*-
"""判据：`lit.stage_list` 的 note 让 A 自己看见「`done=True` ≠ 清表，收工闸数全表」。

## 这一句原来只在收工门的 docstring 里

`closing.py` 的 `_check_literature_pending` docstring 里有一句是这一整件事的关键事实：

> 「A 的 `done=True` 只表示"这一条检索请求跑完了"（真机 r-000008 就是带着 15 条
> pending 收了 done=true）。收工是这一道。」

但它落在收工门自己的 docstring 里 —— 那是收工那一刻才跑到、而且模型读不到的
地方。A 能读到的只有两处：它自己的提示词（`specs/a.py`，禁改区，要人审）与
`lit.stage_list` 的返回文案（`litstage._stage_list_note`）。

真机 `lp-ball-11` 的读数（`temp/reconA/REPORT.md` §1.2）：`search_requests` 七条
全部 `done=true`，而 `lit_candidates` 还有 60 条 pending、`lit.stage_reject`
事件 0 条。A 在 final 里把"累计 45 / 60 条待裁"当成"这一档已经收过工"来收尾。

所以这一条判据守的是：那句话必须出现在 A 每一趟都读得到的那一格（`lit.stage_list`
的 `note`），而不是只活在收工门的 docstring 里。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| d | `lit.stage_list` 的 `note` 里说清两件事：① `done=True` 只是「这一条检索请求跑完了」；② 收工闸数的是全表（不是当前委托 / 不是那一条请求） | 改前 note 只说"本委托还有 N 条没判"与"全表还有 N 条待裁"，没有一个字解释 `done=True` 与清表是两件事 |
| e | 反真空：把这一句从 note 里拿掉（`_stage_list_note` 打桩成旧文案）⇒ d 必红 | 证明 d 的绿来自"这句在"，不是来自别的字 |

「改 closing.py」这条路不走：`closing.py` 这一趟有别的路未提交的改动，而且
`_check_literature_pending` 的 docstring 本来就不是模型面。事实不变，只换落点。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import litstage as L
from agentflow.store import Store

#: d 要求两件事同时在（逐字取自 `closing.py` 那句事实的等价说法）。
DONE_IS_NOT_CLEARED = "`done=True` 只表示「这一条检索请求跑完了」"
GATE_COUNTS_THE_WHOLE_TABLE = "收工闸数的是**全表**"


def _note(store: Store) -> str:
    """走真调用面拿 note（`lit.stage_list` 交给 A 的就是这一个字段）。"""
    return str(L.list_candidates(store)["note"] or "")


def _note_problems(note: str) -> list[str]:
    """这一条 note 离那句话还差什么（空列表 = 合格）。"""
    out: list[str] = []
    if DONE_IS_NOT_CLEARED not in note:
        out.append(f"note 没说清 `done=True` 只是那一条请求跑完了：缺 {DONE_IS_NOT_CLEARED!r}")
    if GATE_COUNTS_THE_WHOLE_TABLE not in note:
        out.append(f"note 没说清收工闸看的是全表：缺 {GATE_COUNTS_THE_WHOLE_TABLE!r}")
    # 反真空的另一半：只写一句口号不算（"清表"那件事必须点名，且要有"不是"的关系）。
    if "清表" not in note:
        out.append("note 没提「清表」—— 只写 done=True 与收工，A 读不出两者的关系")
    return out


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def test_d_the_stage_list_note_says_done_is_not_cleared(store: Store) -> None:
    """d：note 里同时有「`done=True` 只表示那一条跑完了」与「收工闸数的是全表」。"""
    problems = _note_problems(_note(store))
    assert problems == [], "lit.stage_list 的 note：\n  - " + "\n  - ".join(problems)


def test_e_dropping_the_clause_turns_it_red(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把这一句从 note 里拿掉（打桩成旧文案）⇒ d 必红。"""
    live = L._stage_list_note(0)
    assert _note_problems(live) == []
    patched = live.replace(
        "A 的 `done=True` 只表示「这一条检索请求跑完了」，不等于「清表」；"
        "收工闸数的是**全表**，不是当前委托、也不是那一条检索请求。", "")
    assert patched != live, "盘上找不到那一句 ⇒ 反真空打不中（d 量的不是它）"
    monkeypatch.setattr(L, "_stage_list_note", lambda waiting_count: patched)
    assert _note_problems(_note(store)) != [], (
        "把那句话拿掉之后校验仍然绿 —— d 量的不是「done=True ≠ 清表」这件事")
