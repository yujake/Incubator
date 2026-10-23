# -*- coding: utf-8 -*-
"""判据（D20）：会话概览的「待答」与面板的「待答」数是同一份清单。

## 改前是什么样

同一页上有两处「待答」：

1. 会话概览那张表里的一列（`SessionRow.pending`，每段会话一个数）；
2. 「说一句」那张卡上真正列出来的待答问题（`snapshot.pending_questions`，全局一份）。

两处都从 `userio.workspace_pending_view` 派生，但各算一遍：`snapshot()` 把每段
会话的那一片交给 `_scan()`，会话行取 `len(...)`，全局清单再把各片拼起来。结构上
`sum(sessions[].pending) <= len(pending_questions)`（前者是"按会话切过的"），而且
没有任何判据把它们钉在一起 —— 于是"概览说 3 条、面板只列出 2 条"这种口径漂移
可以一直存在而测试全绿。

## 这一份守什么

| 判据 | 落点 |
|---|---|
| ① 三数相等 | 夹具（1 段会话 / 2 问 / 1 答）⇒ `sessions[0].pending == sum(sessions[].pending) == len(pending_questions) == 1` |
| ② 同一份清单 | 把 `userio.workspace_pending_view` 换成一份"会话事件里没有对应提问"的两条 ⇒ 两个数一起变成 2（证明两处都不是各自扫事件算的） |
| ③ 列标题写清来源 | `Home.tsx` 的两处「待答」都带上同一个来源词（`全局待答清单`），且负控：删掉任一处 ⇒ 红 |

## 改前红在哪

①在改前是绿的（两处恰好相等，这也是这条缺陷一直没被发现的原因）；
③是红的那一半：会话概览那一列只写「待答」，`0 条待回答` 也只写个数，没有一处说
"这个数取自哪一份清单"。所以「改前红」以③为准，①是这一批要新加的钉子。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import userio as U
from agentflow import webui as W
from agentflow.store import Store

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
HOME_TSX = REPO / "ui" / "src" / "pages" / "Home.tsx"

#: 两处「待答」共用的来源词（列标题与面板副标题都要有它）。
PENDING_SOURCE = "全局待答清单"

#: 夹具里的会话号。
SID = "d20"


def _workspace_with_two_questions_and_one_answer(tmp_path: pathlib.Path) -> pathlib.Path:
    """夹具：1 段会话、2 个问题、答掉 1 个 ⇒ 待答 1 条（走真写路径，不手写事件）。"""
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    for text in ("先审哪一章？", "要不要顺手改公式？"):
        U.ask_user(root, role="M", question=text, timeout_sec=0, sid=SID)
    asked = U.pending_questions(root, sid=SID)
    assert len(asked) == 2, [q.text for q in asked]
    problem = U.answer_question(root, qid=asked[0].qid, answer="第二章", sid=SID)
    assert problem == "", problem
    return root


# ====================================================================== ① 三数相等
def test_the_session_row_pending_is_the_global_list_counted_once(tmp_path: pathlib.Path) -> None:
    """判据 ①：1 段会话 / 2 问 / 1 答 ⇒ 三个数都是 1（不是 2，也不是 3）。"""
    root = _workspace_with_two_questions_and_one_answer(tmp_path)
    snap = W.snapshot(root)

    per_session = [row["pending"] for row in snap["sessions"]]
    assert per_session == [1], per_session
    assert sum(per_session) == len(snap["pending_questions"]) == 1, (
        f"两处口径没对齐：会话概览 {per_session} / 面板 {len(snap['pending_questions'])}"
        f"（{snap['pending_questions']}）")
    # 剩下那一条确实是没被回答的那一条（"数对了、数的是另一个东西"也要挡）。
    assert [q["text"] for q in snap["pending_questions"]] == ["要不要顺手改公式？"], (
        snap["pending_questions"])


# ====================================================================== ② 同一份清单
def test_both_numbers_move_together_when_the_shared_list_changes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 ②：两处读的是同一份清单，不是"各自扫一遍事件"。

    做法：把 `userio.workspace_pending_view` 换成一份 2 条的清单，而这 2 条的 qid
    在会话事件里根本不存在（它们不是扫事件能得到的）。两个数必须一起变成 2 ——
    任何一处改成"自己扫事件数一遍"都会在这里掉到 0。
    """
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    U.ask_user(root, role="M", question="真问题", timeout_sec=0, sid=SID)

    fake = [
        {"qid": "injected-1", "sid": SID, "role": "M", "ts": "", "timeout_sec": None,
         "text": "注入的一", "options": [], "multi": False, "index": 100},
        {"qid": "injected-2", "sid": SID, "role": "M", "ts": "", "timeout_sec": None,
         "text": "注入的二", "options": [], "multi": False, "index": 101},
    ]
    monkeypatch.setattr(U, "workspace_pending_view", lambda _root: [dict(q) for q in fake])

    snap = W.snapshot(root)
    assert len(snap["pending_questions"]) == 2, snap["pending_questions"]
    assert sum(row["pending"] for row in snap["sessions"]) == 2, snap["sessions"]
    assert [row["pending"] for row in snap["sessions"]] == [2], snap["sessions"]


# ====================================================================== ③ 列标题写清来源
def _source_note_problems(source: str) -> list[str]:
    """两处「待答」各自的来源词（纯函数：给负控喂人造源码用）。"""
    problems: list[str] = []
    column = [ln for ln in source.splitlines() if 'key: "pending"' in ln]
    subtitle = [ln for ln in source.splitlines() if "条待回答" in ln]
    if not column:
        problems.append("`Home.tsx` 里找不到会话概览的「待答」那一列（key: \"pending\"）")
    elif PENDING_SOURCE not in column[0]:
        problems.append(
            f"会话概览的「待答」列标题没写来源（应含「{PENDING_SOURCE}」）：{column[0].strip()}")
    if not subtitle:
        problems.append("`Home.tsx` 里找不到面板那句『N 条待回答』")
    elif PENDING_SOURCE not in subtitle[0]:
        problems.append(
            f"面板的『N 条待回答』没写来源（应含「{PENDING_SOURCE}」）：{subtitle[0].strip()}")
    if source.count(PENDING_SOURCE) < 2:
        problems.append(f"来源词「{PENDING_SOURCE}」只出现 {source.count(PENDING_SOURCE)} 次"
                        "（两处都写才叫同一份清单）")
    return problems


def test_the_two_pending_places_name_their_shared_source() -> None:
    """判据 ③：会话概览那一列与面板那一句都写明"取自全局待答清单"。"""
    source = HOME_TSX.read_text(encoding="utf-8")
    problems = _source_note_problems(source)
    assert problems == [], "\n".join(problems)


def test_negative_control_dropping_the_source_word_is_reported() -> None:
    """判据 ③ 的反真空：把任一处的来源词删掉 ⇒ 检查函数必须报出来。"""
    source = HOME_TSX.read_text(encoding="utf-8")
    assert _source_note_problems(source) == [], "前提：真源码本身是绿的"

    # ① 把列标题退回旧文案
    old_column = source.replace(f'title: "待答（{PENDING_SOURCE}）"', 'title: "待答"')
    assert old_column != source, "找不到会话概览那一列的标题（判据与源码对不上）"
    problems = _source_note_problems(old_column)
    assert problems and any("列标题" in p for p in problems), problems

    # ② 把面板那句里的来源删掉
    old_subtitle = source.replace(f"（{PENDING_SOURCE}）", "")
    problems = _source_note_problems(old_subtitle)
    assert problems, "把两处来源词都删掉之后判据没响"
