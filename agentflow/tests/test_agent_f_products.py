# -*- coding: utf-8 -*-
"""F 的每一轮都要交一件产物（`draft/39` §3.16 + §6.14）—— 真机卡点③ 的机械读数。

## 背景（D15 的真机读数）

p6e/p6f 上 `attack.step` 第 1 轮逐字返回 `no_change`（"本框架尚未接线自动推理"），
于是 `attack_plans.history` 有行而没有任何产物：读起来像"这一轮做了什么"，其实什么都没交。
§3.16 把形态定死：每轮必须以四种产物之一收尾（`reduction` / `proof` /
`counterexample_request` / `dead_end`），确实做不了时也必须落 `dead_end`
（受控理由 + 证据 + `best_partial`）。

## 这一组钉什么（就是真机卡点③ 要读的那一条）

`attack_plans.history` 里每一轮都得有 `product`，且它是合法产物（过 `attackround`
那套判据）；未接线那种收尾必须是 `dead_end`，带受控理由与非空 `best_partial`。
"步级 outcome" 仍然可以是 `no_change`（它说的是"这一轮没有新事实"），
但产物不许缺 —— 这正是"没有产物"与"有产物、产物是 dead_end"的区别。
"""
from __future__ import annotations

import json

from agentflow import attackround as AR
from agentflow.agent_f import AgentF
from agentflow.store import Store


def _f(store: Store, **cfg) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root, **cfg})


def test_every_round_carries_a_valid_product(store: Store):
    """正控：未接线 owner 的那一轮 ⇒ history 里有 `product="dead_end"`，且能过判据。"""
    f = _f(store)
    pid = f.create_plan("难题", "PK-PRODUCT",
                        subgoals=[{"sid": "s1", "text": "让 C 分析结构", "owner": "C"}])["plan_id"]
    out = f.step(pid)
    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec.get("product") == "dead_end", rec
    assert rec.get("strategy") in AR.STRATEGIES, rec
    assert rec.get("dead_end_reason") in AR.DEAD_END_REASONS, rec
    assert rec.get("best_partial"), "§3.19 第 8 条：部分结果必须进台账"
    # 产物是合法的（同一套判据；把 history 里那一份原样喂回去必须能解析）
    again = AR.parse_round(json.dumps({
        "product": rec["product"], "strategy": rec["strategy"],
        "why_strategy": "（回放）", "reason": rec["dead_end_reason"],
        "evidence": rec["detail"][:200], "best_partial": rec["best_partial"]},
        ensure_ascii=False))
    assert again["product"] == "dead_end", again
    # 步级读数照旧（"这一轮没有新事实"），但它现在有产物了
    assert out["outcome"] == "no_change", out
    assert "dead_end" in out["reason"], out["reason"]


def test_no_history_round_is_left_without_a_product(store: Store):
    """反真空（真机卡点③ 的判据形态）：跑几轮之后，没有一轮是"有 outcome 没 product"。"""
    f = _f(store)
    pid = f.create_plan("难题", "PK-SCAN", subgoals=[
        {"sid": "s1", "text": "让 C 分析", "owner": "C"},
        {"sid": "s2", "text": "让 D 综合", "owner": "D"},
        {"sid": "s3", "text": "让 F 自己推", "owner": "F"},
    ])["plan_id"]
    for _ in range(3):
        f.step(pid)
    history = store.rows("attack_plans")[0]["history"]
    assert history, "一轮都没跑起来 ⇒ 这一条判据没有落脚点"
    missing = [h.get("round") for h in history if not h.get("product")]
    assert missing == [], f"这些轮次没有产物：{missing}"


def test_the_product_vocabulary_has_no_no_change(store: Store):
    """反真空：产物词表里没有 `no_change`（它是步级读数，不是产物）。"""
    assert "no_change" not in AR.PRODUCTS, AR.PRODUCTS
    f = _f(store)
    pid = f.create_plan("难题", "PK-VOCAB",
                        subgoals=[{"sid": "s1", "text": "让 C 分析", "owner": "C"}])["plan_id"]
    f.step(pid)
    products = {str(h.get("product") or "") for h in store.rows("attack_plans")[0]["history"]}
    assert products <= set(AR.PRODUCTS), products
    assert "no_change" not in products, products


def test_best_partial_carries_ids_when_the_subgoal_has_evidence(store: Store):
    """§3.19 第 8 条：子目标已经攒下的读数（证据/实验 id）要逐条带 id 进 `best_partial`。"""
    f = _f(store)
    pid = f.create_plan("难题", "PK-PARTIAL", subgoals=[
        {"sid": "s1", "text": "让 C 分析", "owner": "C",
         "evidence_ids": ["exp:0001", "stmt:0007"]},
    ])["plan_id"]
    f.step(pid)
    rec = store.rows("attack_plans")[0]["history"][-1]
    ids = [i for item in (rec.get("best_partial") or []) for i in (item.get("ids") or [])]
    assert sorted(ids) == ["exp:0001", "stmt:0007"], rec
