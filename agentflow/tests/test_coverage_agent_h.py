"""`agent_h.AgentH.verify_fixes` 的直接判据测试（等级 2：决定 `fixed`/`open` 的转发层）。

## 口径（2026-11-15 业主裁定）

逐字：「撤掉这个上限，一切由智能体自行决定，不做读数」。于是本文件测的东西换了方向：

- 旧口径测的是"`max_review_rounds` 有没有从 `AgentH` 的配置传给工具层"（工具层签名里
  那个默认值 2 会让"忘传"静默改小上限）；
- 新口径测的是同一条缝的反面：这条缝上不许再有任何轮次读数 ——
  工具层不再收上限，`AgentH` 也不再持有它；收不收尾只由 H 自己显式给 `close_as`。

这不是删断言，是换对象：旧的三条（转发上限 / `=0` 装配期拒绝 / `0` 不许折成默认值）
守的是"上限配得对不对"；上限机制被撤除之后，"配得对"没有对象了。换成同强度的三条：

1. `close_as` 必须被原样转发（H 的判断要能到达工具层）；
2. 无论 `config` 里还塞着什么 `max_review_rounds`，一次调用里都不许出现它（上限真的没了）；
3. `AgentH` 结构上不再有 `max_review_rounds` 这个属性，`=0` 也不再触发装配期校验
   （机制删除，不是"隐藏起来"）。

为什么用打桩而不是造真实数据：`review.verify_fixes` 要真的跑 `scan_document` 才能判
`fixed`/`open`。本文件要测的只有"参数有没有被传下去 / 有没有被传下去一个上限"，
所以把 `_writer` 打桩、断言它收到的 kwargs —— 造真实数据反而会把"扫描器对不对"混进来。
"""

from __future__ import annotations

import pytest

from agentflow.agent_h import AgentH
from agentflow.store import Store


@pytest.fixture
def h(store: Store) -> AgentH:
    return AgentH(store)


def _stub(monkeypatch: pytest.MonkeyPatch, agent: AgentH) -> dict:
    """把 `_writer` 换成记录 kwargs 的桩；返回那个记录表。"""
    seen: dict = {}

    def fake_writer(tool: str, **kw):
        seen["tool"] = tool
        seen.update(kw)
        return {"verdict": "revise_again", "resolved": [], "still_open": [],
                "unresolved_findings": [], "doc_id": kw["doc_id"], "round": kw["round_no"]}

    monkeypatch.setattr(agent, "_writer", fake_writer)
    return seen


def test_verify_fixes_forwards_h_s_explicit_close_decision(
    h: AgentH, monkeypatch: pytest.MonkeyPatch
):
    """判据：H 自己判的收尾（`close_as`）必须原样到达工具层。

    断言打在收到的 kwargs 上，而不是"返回了 dict"。这条在"转发时把 `close_as` 丢了"
    的实现下会红 —— 于是 H 的判断在工具层变成"什么都不说"（默认不收尾），
    而读数上看起来像 H 没做判断。
    """
    seen = _stub(monkeypatch, h)
    out = h.verify_fixes("0000", round_no=3, close_as="unresolved_review")

    assert seen["tool"] == "review.verify_fixes", seen
    assert seen["doc_id"] == "0000", seen
    assert seen["round_no"] == 3, seen
    assert seen["close_as"] == "unresolved_review", seen
    assert "max_review_rounds" not in seen, (
        f"上限机制已撤除，调用里却还带着它：{seen}")
    assert out["verdict"] == "revise_again", out


def test_verify_fixes_never_forwards_a_round_cap(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """反向判据：即使调用方还在 `config` 里塞 `max_review_rounds`，工具层也不许收到它。

    这条是旧用例 `test_verify_fixes_forwards_the_configured_round_cap` 的反面：
    改前它断言"必须传来 5"，改后断言"不许传来任何东西"。为什么同一条缝要有反面判据：
    上限撤除之后，一个"从 config 读出来再转发"的残留实现不会报任何错 ——
    它只会把 H 的判断又交回给一个计数器，而那正是业主裁定要撤掉的东西。
    """
    agent = AgentH(store, config={"max_review_rounds": 5})
    seen = _stub(monkeypatch, agent)
    agent.verify_fixes("0000", round_no=3)

    assert seen["tool"] == "review.verify_fixes", seen
    assert "max_review_rounds" not in seen, (
        f"上限还在被转发（上限机制应已撤除）：{seen}")
    # 不给 `close_as` 就一个字都不传：转发层不许替 H 决定收尾。
    assert "close_as" not in seen, (
        f"没给收尾判断时不许凭空造一个：{seen}")


def test_the_round_cap_mechanism_is_gone(store: Store):
    """机制删除的结构判据：`AgentH` 不再有 `max_review_rounds` 属性，`=0` 也不再拒绝。

    旧用例断言 `AgentH(store, config={"max_review_rounds": 0})` 在装配期抛
    （0 轮上限会让 `round_no >= max_review_rounds` 恒成立 ⇒ 一切立刻交人复核）。
    上限撤除之后，这个配置项在结构上不该再被读：连"非法值"这一档都没有对象 ——
    所以这里断言的是"它不再是一个机制"，而不是"它被放宽了"：
    构造照常成功，而 `verify_fixes` 的行为由上面两条与
    `tests/test_agent_h.py` 的"没有计数器终态"那两条守着。
    """
    agent = AgentH(store, config={"max_review_rounds": 0})
    assert not hasattr(agent, "max_review_rounds"), (
        "`max_review_rounds` 仍是 AgentH 的属性 ⇒ 上限机制没有被删掉，只是换了读取位置")
