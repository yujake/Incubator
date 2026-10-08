# -*- coding: utf-8 -*-
"""投递的两个集合只有一个来源（`draft/83` §11 的 D75 / `draft/86` §4.1 的 S4 前半）。

真机读数（`draft/89` §2）：128 个会话里 `agent_message` 579 条，而 `agent_inbox`
（"这批已投递"）只有 12 次、涉及 8 条消息。旧形态的病根是一句话：

    渲染 `messages[-8:]`  ←→  标记 `fresh`（全部未投递）

两个集合不一样大 ⇒ 第 9 条及更早的留言既不进提示词、也不再是 fresh ⇒ 永久静默丢失。
这份文件钉三件事：

1. 渲染集合 == 标记集合（现在 `inbox_digest` 的第二个返回值就是"渲染过的"；
   调用方标它，两个集合只有一个来源）；
2. 未投递优先、老的先读（否则新留言不断到来会把老的永远挤在窗口外）；
3. 积压要看得见（窗口装不下时提示词里写"还有 K 条没渲染"）。
"""
from __future__ import annotations

import pathlib

from agentflow import agent_loop as AL
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return ws


def _send(ws: pathlib.Path, n: int, *, prefix: str = "m") -> list[str]:
    ids: list[str] = []
    for i in range(n):
        mid, problem = AL.send_message(ws, sender="M", to="D",
                                       subject=f"{prefix}{i:02d}", body=f"正文 {i}")
        assert not problem, problem
        ids.append(mid)
    return ids


def test_the_rendered_set_is_exactly_what_gets_marked(tmp_path: pathlib.Path):
    """正控（D75 的核心）：12 条未投递 ⇒ 开场窗口渲染 8 条，标记的恰好是这 8 条。

    改前必红：旧实现标记的是全部 12 条，于是第 9-12 条下次再也不出现。
    """
    ws = _ws(tmp_path)
    ids = _send(ws, 12)
    text, rendered, problems = AL.inbox_digest(ws, "D", sid=None)
    assert not problems, problems
    assert len(rendered) == 8, rendered
    assert rendered == ids[:8], (rendered, ids)          # 老的先读（时间升序）
    assert "还有 4 条留言没渲染" in text, text            # 积压是看得见的事实
    assert text.splitlines()[0].startswith("- （新）[m0001]"), text
    assert AL.mark_delivered(ws, "D", rendered, sid=None) == ""
    # 剩下的 4 条仍然是 fresh ⇒ 下一步会读到它们（这正是"不再丢"的机器形态）
    text2, rendered2, _ = AL.inbox_digest(ws, "D", sid=None)
    assert rendered2 == ids[8:], (rendered2, ids[8:])
    assert "（新）" in text2, text2


def test_the_other_window_renders_everything_it_hears(tmp_path: pathlib.Path):
    """负控/口径对照：`window=None`（`_hear` 那条路）把新到的一次性全渲染、全标记。

    这一步的结果会把 `heard` 里每一条都并进上下文 ⇒ "渲染多少标多少"在那里等价于
    "标全部新到的"；两处窗口不同、纪律同一条。
    """
    ws = _ws(tmp_path)
    ids = _send(ws, 12)
    _text, rendered, _ = AL.inbox_digest(ws, "D", sid=None, window=None)
    assert rendered == ids, (rendered, ids)


def test_delivered_messages_are_background_not_priority(tmp_path: pathlib.Path):
    """正控（优先级的另一半）：窗口先给未投递的，已投递的只当背景。"""
    ws = _ws(tmp_path)
    ids = _send(ws, 3)
    AL.mark_delivered(ws, "D", ids, sid=None)
    new_ids = _send(ws, 2, prefix="n")
    text, rendered, _ = AL.inbox_digest(ws, "D", sid=None)
    # 两条新的必须都在（窗口 8 > 2 条新的 ⇒ 余量给已投递的背景）
    assert set(new_ids) <= set(rendered), (new_ids, rendered)
    first_line = text.splitlines()[0]
    assert first_line.startswith("- （新）[m0004]") and "n00" in first_line, text


def test_an_empty_inbox_is_not_a_problem(tmp_path: pathlib.Path):
    """反真空：空收件箱是"读成了、没有留言"，不是"没读成"（三态不许折平）。"""
    ws = _ws(tmp_path)
    text, rendered, problems = AL.inbox_digest(ws, "D", sid=None)
    assert text == "（没有收到留言）" and rendered == [] and problems == [], (text, rendered, problems)
