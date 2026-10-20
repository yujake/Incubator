# -*- coding: utf-8 -*-
"""秘书那张"这件活做不做得成"的新一维：**能力面闭包**（业主 2026-10-14）。

业主逐字：「秘书侧……评估派发出的任务能否由**子代理及子代理的出边**共同完成」。
`secretary.surface_fit` 判的是**路径面**（这句话里的文件落不落在它的沙箱里）；
`secretary.reach_fit` 判的是**能力面**：那个动作，被派人自己有没有？没有的话，
它出边上的伙伴（再由伙伴的出边……直到 `policy.Policy().max_depth`）里有谁有？走哪几跳？

这一组守四件事：
1. 四档齐全（`in_self` / `via_edges` / `unreachable` / `unknown`），且 `unknown` 不许折成"做得到"；
2. **真表上的读数**（含本轮新加的 `B → H`：`B` 自己没有语义回验，但一跳够得到 `H`）；
3. 闭包是**真的**按出边走（`A → B → H → G` 三跳那条就是"只看被派人自己"会漏掉的形态）；
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

    这一条同时是**新设计**（2026-10-14 那条 `B→H` 边 + `H.judge_quote_semantics`）的回归守卫：
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


def test_a_branch_without_that_action_is_unreachable(monkeypatch) -> None:
    """被派人那一支闭包里没有谁有这一件 ⇒ `unreachable`（面内做不成，不许折成"做得到"）。

    ## 2026-10-19 业主裁定改了这一条的夹具（判据本身一个字没动）

    裁定逐字：「C 要能把"候选的更短路径"交给 D」⇒ `ALLOWED_EDGES["C"] == {"D"}`
    （注释全文见 `tests/test_policy.py::test_allowed_edges_match_design_table`）。

    改前这一条拿 C 当夹具，理由写的是"C 是只读角色、且它**没有出边**，于是它那一支
    只有它自己，闭包大小恒为 1"。那条边现在有了 ⇒ **实表上再没有一个
    `(角色, 动作)` 对是 unreachable 的**（C 经 D 一跳就够到 A/B/E/F/V/H/G 的动作）。
    所以：

    1. 反真空那半跟着改：断言"实表上 0 个 unreachable"这个**读数**本身，
       并正面钉住 C 的新闭包（`C → D → E` 拿到 `run_experiment`）—— 那是裁定的直接后果；
    2. `unreachable` 这一档改由**注入的边表**来考（把 C 的出边抹掉 = 改前那张表），
       于是"这一档还咬不咬人"仍然被一条真的 `reach_fit` 调用证明，
       而不是因为实表恰好没有反例就静默变成没人守的代码。
    """
    from agentflow import capabilities as C

    # ---- 1. 实表读数：C 现在够得到 run_experiment（C→D→E 两跳）
    assert C.ALLOWED_EDGES["C"] == frozenset({"D"}), C.ALLOWED_EDGES["C"]
    got_c = S.reach_fit("C", "run_experiment")
    assert got_c["verdict"] == "via_edges", got_c
    assert got_c["hops"] == ["C", "D", "E"], got_c

    # 反真空：实表上每一个 (角色, 动作) 对都够得到 ⇒ 下面是"0 个反例"这条读数
    roles = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "M")
    acts = sorted({a.action for r in roles for a in C.CAPABILITIES.get(r, ())})
    live = [(r, a) for r in roles for a in acts
            if S.reach_fit(r, a)["verdict"] == "unreachable"]
    assert live == [], (
        f"实表上出现了 unreachable 的对：{live}（2026-10-19 之后 C→D 让每个角色都够得到"
        "全部动作 —— 这个读数是裁定的后果，不是判据放宽）")

    # ---- 2. 注入改前那张表（C 无出边）⇒ `unreachable` 这一档仍要咬人
    original = C.ALLOWED_EDGES
    weakened = {k: (frozenset() if k == "C" else v) for k, v in original.items()}
    monkeypatch.setattr(C, "ALLOWED_EDGES", weakened)
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
