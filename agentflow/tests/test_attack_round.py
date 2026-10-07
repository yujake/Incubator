# -*- coding: utf-8 -*-
"""F 的"一轮真推理"（`draft/39` §3.16 + §3.19 已批准项）—— E11 / E12 / E13 的离线演练。

用户口径（逐字，`draft/39` §3.16 那一节的来源）：

> D15 暴露真问题，看 draft 里关于 danus 智能体的调查报告想方法。
> 批准 3、6、8；5 的表述是 F 禁止写的，其它有待商榷
> ……我们后续详细讨论怎么用这种方式给 F 加强。

三条判据（`draft/39` §6 表 E11–E13）：

- E11 一轮四产物：给一个可判定子目标跑一轮 ⇒ 产物必须是四种之一（不许 `no_change`）；
- E12 缺陷继承（I11）：让证明引一条已作废的命题 ⇒ 该步必须记继承缺陷；
- E13 超预算阻塞（I16）：造一个超预算轮次 ⇒ 显式阻塞、不许截断。

模拟真机那一条 D15 读数（`attack.step` 第 1 轮逐字 `no_change`）也在这里当负控钉住。
"""
from __future__ import annotations

import json

import pytest

from agentflow import attackround as AR


# ============================================================ E11：四种产物

def test_e11_reduction_is_a_product(tmp_path=None):
    """E11①：`reduction` ⇒ 1–3 条可判定的新子目标 + 归约理由。"""
    got = AR.parse_round(json.dumps({
        "product": "reduction", "strategy": "归约", "why_strategy": "先缩小到单参数族",
        "new_subgoals": [{"goal": "证 m=3, k=6 的存在性", "testable": "枚举 n≤12"},
                         {"goal": "排除 k≥7", "testable": "构造反例或给出上界"}],
        "reason": "原命题含两个自由参数"}))
    assert got["product"] == "reduction" and len(got["new_subgoals"]) == 2, got
    assert all(s["testable"] for s in got["new_subgoals"]), got
    # 超过三条就是没归约（那不是"更细"，那是把子目标摊开）
    with pytest.raises(AR.RoundError):
        AR.parse_round(json.dumps({
            "product": "reduction", "strategy": "归约", "why_strategy": "x",
            "new_subgoals": [{"goal": str(i), "testable": "t"} for i in range(4)]}))
    # 给不出可检验形式 ⇒ 不是一条归约（该落 dead_end 并写清缺什么）
    with pytest.raises(AR.RoundError):
        AR.parse_round(json.dumps({
            "product": "reduction", "strategy": "归约", "why_strategy": "x",
            "new_subgoals": [{"goal": "把问题想清楚"}]}))


def test_e11_proof_is_a_product_and_the_proof_goes_somewhere():
    """E11②：`proof` ⇒ 逐步论证（每步引 id 或声明成前提）—— 它就是要置第 2 位的那件东西。"""
    got = AR.parse_round(json.dumps({
        "product": "proof", "strategy": "反证", "why_strategy": "假设不存在族导出矛盾",
        "steps": [{"text": "假设对所有 n 都不存在", "assumption": True},
                  {"text": "由 stmt:0004 的界得到 girth ≤ 6", "cites": ["stmt:0004"]}]},
        ensure_ascii=False))
    assert [s["n"] for s in got["steps"]] == [1, 2], got
    assert got["steps"][0]["assumption"] is True and got["steps"][1]["cites"] == ["stmt:0004"]


def test_e11_counterexample_request_is_a_product():
    """E11③：`counterexample_request` ⇒ 具体可判的脚本规格 + "凭什么能判"。"""
    got = AR.parse_round(json.dumps({
        "product": "counterexample_request", "strategy": "小情形搜索找模式",
        "why_strategy": "先便宜地证伪",
        "script_spec": {"criterion": "存在 m-正则、围长 k 且每边在两个 k-圈里",
                        "params": "m∈{3,4}, k∈{3..8}, n≤14", "expected_bound": "界推到 n=14"},
        "why_it_decides": "找不到就是这条命题在 n≤14 上的反例候选"}))
    assert got["script_spec"]["expected_bound"].endswith("n=14"), got
    with pytest.raises(AR.RoundError):
        AR.parse_round(json.dumps({
            "product": "counterexample_request", "strategy": "反证", "why_strategy": "x",
            "script_spec": {"criterion": "c"}, "why_it_decides": "y"}))


def test_e11_dead_end_is_a_product_and_best_partial_is_mandatory():
    """E11④ + §3.19 第 8 条：`dead_end` 要有受控理由、证据，且 `best_partial` 必填。"""
    got = AR.parse_round(json.dumps({
        "product": "dead_end", "strategy": "编码为 SAT/ILP", "why_strategy": "试试编码",
        "reason": "方法不适用", "evidence": "约束数随 n 指数增长，n=10 就写不进内存",
        "best_partial": [{"what": "证了 m=3 的一族", "ids": ["stmt:0004"],
                          "why_partial": "只覆盖 m=3"}]}))
    assert got["reason"] == "方法不适用" and got["best_partial"][0]["ids"] == ["stmt:0004"], got
    with pytest.raises(AR.RoundError):
        AR.parse_round(json.dumps({
            "product": "dead_end", "strategy": "反证", "why_strategy": "x",
            "reason": "方法不适用", "evidence": "不行"}))
    with pytest.raises(AR.RoundError):
        AR.parse_round(json.dumps({
            "product": "dead_end", "strategy": "反证", "why_strategy": "x",
            "reason": "随便一个理由", "evidence": "不行", "best_partial": [{"what": "w"}]}))


def test_e11_no_change_is_not_a_product(tmp_path=None):
    """E11 的负控（真机那一条读数）：`attack.step` 第 1 轮逐字 `no_change` ⇒ 打回。

    "确实什么都做不了"要落成 `dead_end`（受控理由 + 证据 + 缺什么），那是三态（null + 理由），
    不是 `no_change` —— 这个区别就是 D15 的要害。
    """
    with pytest.raises(AR.RoundError) as exc:
        AR.parse_round(json.dumps({"product": "no_change", "strategy": "归约",
                                   "why_strategy": "还没接线自动推理"}))
    assert "dead_end" in str(exc.value), str(exc.value)
    with pytest.raises(AR.RoundError):
        AR.parse_round(json.dumps({"product": "proof", "why_strategy": "x", "steps": []}))
    with pytest.raises(AR.RoundError):
        AR.parse_round(json.dumps({"product": "proof", "strategy": "随便", "why_strategy": "x",
                                   "steps": [{"text": "a"}]}))


# ============================================================ #5 禁止项（两条合法出口）

def test_the_banned_phrase_needs_one_of_the_two_legal_exits():
    """#5：出现"易证/显然"这类缝 ⇒ 打回，并逐字给出两条合法出口。"""
    with pytest.raises(AR.RoundError) as exc:
        AR.parse_round(json.dumps({
            "product": "proof", "strategy": "归约", "why_strategy": "x",
            "steps": [{"text": "易证该族非空"}]}))
    msg = str(exc.value)
    assert "合法出口" in msg and "assumption" in msg, msg
    # 出口 ①：把这一步写出来（给出依据）
    ok1 = AR.parse_round(json.dumps({
        "product": "proof", "strategy": "构造参数族", "why_strategy": "显式构造",
        "steps": [{"text": "取 G=C_n：2-正则、围长 n", "cites": ["stmt:0001"]}]}))
    assert ok1["steps"][0]["cites"] == ["stmt:0001"]
    # 出口 ②：显式声明成前提
    ok2 = AR.parse_round(json.dumps({
        "product": "proof", "strategy": "归约", "why_strategy": "先接受这条前提",
        "steps": [{"text": "设该族非空（本文的前提）", "assumption": True}]}))
    assert ok2["steps"][0]["assumption"] is True
    # 既没引据也没声明 ⇒ 打回（"每一步都要指出依据"是 I10 的最小形态）
    with pytest.raises(AR.RoundError):
        AR.parse_round(json.dumps({
            "product": "proof", "strategy": "归约", "why_strategy": "x",
            "steps": [{"text": "由上面的讨论得到结论"}]}))


# ============================================================ E12：缺陷继承（I11）

def test_e12_a_proof_citing_a_refuted_statement_inherits_the_defect():
    """E12：证明引了一条已作废的命题 ⇒ 那一步记继承缺陷（I11），并且指到步号。"""
    row = AR.parse_round(json.dumps({
        "product": "proof", "strategy": "套用已知定理", "why_strategy": "直接用它",
        "steps": [{"text": "由 stmt:0007 的界得到结论", "cites": ["stmt:0007"]},
                  {"text": "由 stmt:0004 得到 girth ≤ 6", "cites": ["stmt:0004"]}]}))
    defects = AR.inherit_defects(row, clean_ids=["stmt:0004"])
    assert len(defects) == 1, defects
    assert defects[0]["step"] == 1 and defects[0]["ref"] == "stmt:0007", defects[0]
    assert "继承" in defects[0]["detail"], defects[0]
    # 干净集合覆盖全部引用 ⇒ 无缺陷（反真空）
    assert AR.inherit_defects(row, clean_ids=["stmt:0004", "stmt:0007"]) == []


def test_e12_a_declared_assumption_does_not_inherit_a_defect():
    """I11 的边界：显式声明成前提的那一步引用"不干净"的东西是已知的，不算继承缺陷。"""
    row = AR.parse_round(json.dumps({
        "product": "proof", "strategy": "归约", "why_strategy": "先接受它",
        "steps": [{"text": "设 stmt:0007 成立（本轮前提）", "cites": ["stmt:0007"],
                   "assumption": True}]}))
    assert AR.inherit_defects(row, clean_ids=[]) == [], AR.inherit_defects(row, clean_ids=[])


# ============================================================ E13：超预算阻塞（I16）+ I9

def test_e13_an_over_budget_round_is_blocked_not_truncated():
    """E13：超上限的一轮 ⇒ `too_large` 显式阻塞；不截断，且指出拆解是编排方的活。"""
    got = AR.budget_decision(cost_usd=3.5, cap_usd=3.0, spent_usd=0.4)
    assert got["status"] == "too_large", got
    assert "不截断" in got["note"] and "拆子目标" in got["note"], got["note"]
    assert got["projected_usd"] == pytest.approx(3.9), got
    assert AR.budget_decision(cost_usd=1.0, cap_usd=3.0, spent_usd=0.4)["status"] == "ok"
    assert AR.budget_decision(cost_usd=1.0, cap_usd=None)["status"] == "unbounded"


def test_i9_the_deterministic_gate_runs_before_any_money_is_spent():
    """已批准的第 3 条 + I9：先做便宜的证伪 —— 四条事实各自挡住，且不花一分钱。

    P-09（`draft/44:60`）之后这四条是全部的否决面：它们是事实（目标空 /
    没有可检验形式 / 引到已作废的命题 / 预算耗尽），不是"该模型抉择的事"。
    原来还有第五条"九招试完了就不许花钱"—— 那一条已改成读数（见下一条用例）。
    """
    assert AR.pre_spend_gate(goal="", testable="x")["spend"] is False
    assert AR.pre_spend_gate(goal="证 n=3", testable="")["spend"] is False
    refuted = AR.pre_spend_gate(goal="证 n=3", testable="枚举", deps_refuted=["stmt:0007"])
    assert refuted["spend"] is False and "作废" in refuted["reasons"][0], refuted
    broke = AR.pre_spend_gate(goal="证 n=3", testable="枚举", budget_left_usd=0.0)
    assert broke["spend"] is False and "预算" in broke["reasons"][0], broke
    ok = AR.pre_spend_gate(goal="证 n=3", testable="枚举", budget_left_usd=2.5,
                           tried_strategies=["归约"])
    assert ok["spend"] is True and ok["checks"]["budget_ok"], ok


def test_p09_tried_strategies_is_a_reading_not_a_veto():
    """P-09：计数不否决花钱 —— 九招试完给的是"代价可读"，裁量权回到 F 手里。

    改前：`len(set(tried)) >= len(STRATEGIES)` 直接 `spend=False`（死旋钮）。
    改后：`checks["strategies_tried"]` 如实报 `tried / remaining / exhausted` 与一句
    代价读数，`spend` 仍为真（该不该再花一轮是 F 按代价做的判断，不是闸门替它定的）。
    反负控（同一用例里）：上面那四条事实仍然必须否决 —— 证明这次改的是"计数否决"，
    没有把整条 I9 闸门拆掉。
    """
    all_tried = AR.pre_spend_gate(goal="证 n=3", testable="枚举",
                                  tried_strategies=list(AR.STRATEGIES))
    assert all_tried["spend"] is True, all_tried
    assert all_tried["reasons"] == [], all_tried
    info = all_tried["checks"]["strategies_tried"]
    assert info["exhausted"] is True and info["remaining"] == [], info
    assert len(info["tried"]) == len(AR.STRATEGIES), info
    assert "已穷尽" in info["note"] and str(len(AR.STRATEGIES)) in info["note"], info["note"]

    partial = AR.pre_spend_gate(goal="证 n=3", testable="枚举",
                                tried_strategies=[AR.STRATEGIES[0]])
    assert partial["spend"] is True
    assert partial["checks"]["strategies_tried"]["exhausted"] is False
    assert AR.STRATEGIES[0] not in partial["checks"]["strategies_tried"]["remaining"]

    # 反负控：四条事实一条都不许被这次改动放过。
    assert AR.pre_spend_gate(goal="", testable="枚举")["spend"] is False
    assert AR.pre_spend_gate(goal="证 n=3", testable="")["spend"] is False
    assert AR.pre_spend_gate(goal="证 n=3", testable="枚举",
                             deps_refuted=["stmt:0007"])["spend"] is False
    assert AR.pre_spend_gate(goal="证 n=3", testable="枚举",
                             budget_left_usd=0.0)["spend"] is False


def test_rule_6_parallel_routes_are_distinct_strategies():
    """已批准的第 6 条：多路并行要不同策略（否则"三路"其实是同一招跑三遍）。"""
    fresh = AR.pick_parallel_routes(3)
    assert len(fresh) == 3 and len(set(fresh)) == 3, fresh
    after_tried = AR.pick_parallel_routes(2, tried=["归约", "反证"])
    assert "归约" not in after_tried and "反证" not in after_tried, after_tried
    assert AR.pick_parallel_routes(0) == []


def test_the_round_form_is_documented_as_the_four_products():
    """反真空：四种产物与策略工具箱是受控表（少一档 ⇒ 上面那些判据就有洞）。"""
    assert AR.PRODUCTS == ("reduction", "proof", "counterexample_request", "dead_end")
    assert "no_change" not in AR.PRODUCTS
    assert len(AR.STRATEGIES) == 9, AR.STRATEGIES
    assert AR.DEAD_END_REASONS and AR.F_BANNED_MARKERS
