# -*- coding: utf-8 -*-
"""秘书那张"这件活做不做得成"的新一维：能力面闭包（业主 2026-10-14）。

业主逐字：「秘书侧……评估派发出的任务能否由子代理及子代理的出边共同完成」。
`secretary.surface_fit` 判的是路径面（这句话里的文件落不落在它的沙箱里）；
`secretary.reach_fit` 判的是能力面：那个动作，被派人自己有没有？没有的话，
它出边上的伙伴（再由伙伴的出边……直到 `policy.Policy().max_depth`）里有谁有？走哪几跳？

这一组守四件事：
1. 四档齐全（`in_self` / `via_edges` / `unreachable` / `unknown`），且 `unknown` 不许折成"做得到"；
2. 真表上的读数（含本轮新加的 `B → H`：`B` 自己没有语义回验，但一跳够得到 `H`）；
3. 闭包是真的按出边走（`A → B → H → G` 三跳那条就是"只看被派人自己"会漏掉的形态）；
4. 判不了时说得出为什么（角色/动作名认不出各有一条理由）。
"""
from __future__ import annotations

from agentflow import capabilities as C
from agentflow import secretary as S


def test_an_action_the_sub_agent_has_itself_is_in_self() -> None:
    """被派人自己的动作表里就有 ⇒ `in_self`（一跳都不用）。"""
    got = S.reach_fit("H", "judge_quote_semantics")
    assert got["checked"] is True and got["verdict"] == "in_self", got
    assert got["hops"] == ["H"], got


def test_an_action_reachable_through_one_edge_is_via_edges() -> None:
    """B 自己没有语义回验，但出边上的 H 有 ⇒ `via_edges`，链是 `B → H`。

    这一条同时是新设计（2026-10-14 那条 `B→H` 边 + `H.judge_quote_semantics`）的回归守卫：
    边或动作哪一条没了，这里当场红 —— 而"B 要把引文交给 H 判"正是这一维要看见的事。
    """
    got = S.reach_fit("B", "judge_quote_semantics")
    assert got["verdict"] == "via_edges", got
    assert got["hops"] == ["B", "H"], got
    assert "1 跳" in got["reason"], got


def test_the_closure_really_walks_more_than_one_hop() -> None:
    """闭包按出边一层层走：`A` 自己不会写稿，但 `A → B → H → G` 够得到 `build_document`。

    "只看被派人自己的动作表"会把这一件读成"面内做不成"，而它其实三跳就够得到。
    """
    got = S.reach_fit("A", "build_document")
    assert got["verdict"] == "via_edges", got
    assert got["hops"][0] == "A" and got["hops"][-1] == "G", got
    assert len(got["hops"]) - 1 >= 2, got


def test_a_branch_without_that_action_is_unreachable() -> None:
    """被派人那一支闭包里没有谁有这一件 ⇒ `unreachable`（面内做不成，不许折成"做得到"）。

    `C` 是只读角色、且它没有出边（`ALLOWED_EDGES["C"] == frozenset()`）——
    于是它那一支只有它自己，闭包大小恒为 1。

    2026-10-20 业主裁定：改回 C 无出边、由 D 唤起 C ⇒ 这一条按原形态恢复
    （2026-10-19 那一版曾为 C→D 把夹具换成"注入边表"，夹具回到实表本来的那一档）。
    """
    assert C.ALLOWED_EDGES["C"] == frozenset(), C.ALLOWED_EDGES["C"]
    got = S.reach_fit("C", "run_experiment")
    assert got["verdict"] == "unreachable", got
    assert got["hops"] == ["C"], got
    assert "面内做不成" in got["reason"], got


def test_names_that_cannot_be_read_say_so_instead_of_passing() -> None:
    """角色名 / 动作名认不出 ⇒ `unknown` + 一句为什么（判不了不等于做得到）。"""
    bad_role = S.reach_fit("谁", "judge_quote_semantics")
    assert bad_role["checked"] is True and bad_role["verdict"] == "unknown", bad_role
    assert "不在能力表里" in bad_role["reason"], bad_role
    bad_action = S.reach_fit("B", "没这个动作")
    assert bad_action["verdict"] == "unknown", bad_action
    assert "不在任何角色的动作表里" in bad_action["reason"], bad_action
    empty = S.reach_fit("B", "")
    assert empty["verdict"] == "unknown" and "没给动作名" in empty["reason"], empty
