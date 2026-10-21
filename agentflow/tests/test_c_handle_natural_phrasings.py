# -*- coding: utf-8 -*-
"""C 的 `handle` 要认得出最自然的那几种说法（业主 2026-10-16 亲测口径）。

## 为什么补这个文件

第一次亲测 C 时，我按最普通的一句话问它："看看这张图里什么最热" ⇒ 它答
`ok=False kind='unknown' error='关键词未命中'` —— 而 `C.hottest` 明明就在它的动作表里。
查词表：`_HOT_HINTS` 里只有 "最热门"，没有 "最热"（更短、更自然），
也没有"热度/中心性/hottest/核心概念"。

业主口径（逐字）："凡是你凭感觉第一次运行工具发现红了，都要假想真实智能体也会在这里
困惑并浪费时间和 token。" —— 这一格尤其要紧：它是智能体对 C 说的第一句话。

这一组钉两件事：
1. 常见说法都要路由对（不许把"什么最热"判成 unknown）；
2. 负控：真的不相干的说法仍必须是 `unknown`（不许为了让它"都能过"而把词表放宽到乱命中）。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow.agent_c import AgentC
from agentflow.store import Store


@pytest.fixture()
def c(tmp_path: pathlib.Path) -> AgentC:
    store = Store(tmp_path / "ws")
    store.init()
    return AgentC(store)


@pytest.mark.parametrize(("text", "kind"), [
    ("看看这张图里什么最热", "hottest"),
    ("最热的概念", "hottest"),
    ("hottest", "hottest"),
    ("统计最热门的 3 个概念", "hottest"),
    ("哪个概念度数最高", "hottest"),
    ("研究冷门概念", "cold"),
    ("哪些概念是孤立的", "cold"),
    ("找结构缺口", "gaps"),
    ("完善关系图", "gaps"),
    ("群与阿贝尔群之间的关系", "paths"),
])
def test_natural_phrasings_reach_the_right_analyzer(c: AgentC, text: str, kind: str) -> None:
    """正控：常见说法要落到对的那个分析器上（不是恰好"没报错"）。"""
    out = c.handle(text)
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("kind") == kind, (text, got)


def test_a_request_that_really_matches_nothing_stays_unknown(c: AgentC) -> None:
    """负控：真不相干的说法仍必须是 `unknown`，而且拒绝里要给出路。"""
    out = c.handle("给我讲个笑话")
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("ok") is False, got
    assert got.get("kind") == "unknown", got
    payload = got.get("payload") or {}
    assert payload.get("available"), "拒绝里没列出可用的分析器（那就没有出路）"
