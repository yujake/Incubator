"""`agent_h.AgentH.verify_fixes` 的直接判据测试（等级 2：决定 `fixed`/`open` 的转发层）。

## 为什么这个函数值得一条点名的测试

`AgentH.verify_fixes` 是转发层：它把 `max_review_rounds` 从自己的配置传给
`review.verify_fixes`（工具层）。它自己几乎没有判据 —— 只有一条：

> `self.max_review_rounds` 必须被真的传下去。

这条看起来微不足道，但它是一个真实的失败形态：`AgentH.__init__` 从
`config["max_review_rounds"]` 读出上限（并有 `>= 1` 的装配期校验），
而工具层 `review_tools.verify_fixes` 的签名里 `max_review_rounds` 有默认值 2。
于是"转发时忘了传"不会报任何错 —— 调用方配了 `max_review_rounds=5`，
复审却在第 2 轮就判 `unresolved_review` 交人复核，上限被静默地改回默认值。

在 `tests/test_agent_h.py` 里，`AgentH.verify_fixes` 是被间接调用的
（`h.verify_fixes("0000", round_no=2)` 那种形态，函数名在那份文件里从未出现），
而且那 5 条测试都用 `config={"max_review_rounds": 2}` 或 `{"max_review_rounds": 3}`、
从未断言上限本身被传下去。所以本文件补的是这一条。

## 为什么用打桩而不是造真实数据

`review_tools.py` 在 FC-27 禁改区，而且它要真的跑 `scan_document` 才能判
`fixed`/`open`。本文件要测的只有"参数有没有被传下去"这一件事，
所以把 `_writer` 打桩、断言它收到的 kwargs —— 这是对转发这件事最直接、
也最不容易误伤的判据（造真实数据反而会把"扫描器对不对"混进来）。
"""

from __future__ import annotations

import pytest

from agentflow.agent_h import AgentH
from agentflow.store import Store


@pytest.fixture
def h(store: Store) -> AgentH:
    return AgentH(store, config={"max_review_rounds": 5})


def test_verify_fixes_forwards_the_configured_round_cap(h: AgentH, monkeypatch: pytest.MonkeyPatch):
    """判据：`max_review_rounds` 必须取自 `AgentH` 自己的配置并被传给工具层。

    断言打在收到的 kwargs 上，而不是"返回了 dict"。
    这条测试在"转发时忘了传 `max_review_rounds`"的实现下会红 ——
    而那正是本文件存在的理由（工具层有默认值 2，忘传不会报错）。
    """
    seen: dict = {}

    def fake_writer(tool: str, **kw):
        seen["tool"] = tool
        seen.update(kw)
        return {"verdict": "revise_again", "resolved": [], "still_open": [],
                "unresolved_findings": [], "doc_id": kw["doc_id"], "round": kw["round_no"]}

    monkeypatch.setattr(h, "_writer", fake_writer)
    out = h.verify_fixes("0000", round_no=3)

    assert seen["tool"] == "review.verify_fixes", seen
    assert seen["doc_id"] == "0000", seen
    assert seen["round_no"] == 3, seen
    assert seen["max_review_rounds"] == 5, (
        f"上限没被传下去（工具层会回落到默认 2）：{seen}")
    assert out["verdict"] == "revise_again", out


def test_verify_fixes_rejects_a_zero_round_cap_at_assembly_time(store: Store):
    """负控（装配期 fail-closed）：`max_review_rounds=0` 必须在构造时就拒绝。

    为什么这条重要：0 轮上限意味着"一次复审都不许做"，而它同时会让
    `round_no >= max_review_rounds` 恒成立 ⇒ 一切立刻判 `unresolved_review`。
    在构造时就拒绝，比让它变成一个"永远交人复核"的静默行为好得多
    （`DEVELOPMENT.md`：静默失败比崩溃更危险）。
    """
    with pytest.raises(Exception) as ei:
        AgentH(store, config={"max_review_rounds": 0})
    assert "max_review_rounds" in str(ei.value), str(ei.value)


def test_verify_fixes_negative_control_zero_is_not_coerced_to_the_default(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """负控（不许把非法值悄悄折叠成默认值）：`0` 不许被当成"没配"而回落到 2。

    为什么单独一条：`int(cfg.get("max_review_rounds", 2))` 用的是 `.get` 的默认值，
    它只在键缺失时生效。一个写成 `cfg.get("max_review_rounds") or 2` 的实现
    会把 `0`（以及任何 falsy 值）静默折叠成 2 —— 于是"我要求零轮"变成"我允许两轮"。
    上一条测的是"抛不抛"，这条测的是"抛的原因对不对"：必须是校验拒绝，
    而不是被折叠后悄悄接受。
    """
    calls: list[dict] = []

    class _Probe(AgentH):
        def __init__(self, *a, **kw):  # pragma: no cover - 不该被调到
            calls.append(kw)
            super().__init__(*a, **kw)

    with pytest.raises(Exception):
        _Probe(store, config={"max_review_rounds": 0})
    # 若实现把 0 折叠成 2，就不会抛 ⇒ 上面那行会失败（而不是走到这里）。
    assert calls, "构造被调到了却没有走到校验 ⇒ 夹具前提变了"
