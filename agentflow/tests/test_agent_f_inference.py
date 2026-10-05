# -*- coding: utf-8 -*-
"""F 自己推理那一支（`draft/39` §6.31 的 D42）：插座接上之后，`step` 真的推一轮。

## 背景（真机读数）

`agent_f/core.py` 的 `llm` 形参从 `draft/30` §T0-8 起就在，注释逐字写着
"默认 None = 不接线 ⇒ 本角色一个 LLM 调用都不发"，但 `_deploy` 里那一条
`owner in UNWIRED_OWNERS`（C/D/F）无论有没有缝都落 `dead_end(缺工具)` ——
于是 T2 第 11 趟（`projects/p6m-research-from-zero`）`F.step` 回的是
`no_change`，M 据此写下"F 的自动推理未接线，攻坚这条路走不通"。
这一组钉的就是"接上缝之后它真的推一轮"，以及四种受控产物各自的落法。

## 判据的形状

离线（假模型返回写死的 JSON）——不由真模型决定判据；
每一档都有一条正控（接线的 F 交得出那一档产物）与一条负控
（没接线时仍是 `dead_end`；闸门说不许花钱时一次模型调用都不发）。
"""
from __future__ import annotations

import json

from agentflow import attackround as AR
from agentflow.agent_f import AgentF
from agentflow.store import Store


class FakeLLM:
    """最小模型缝：`complete(prompt) -> str`（`judge.judge_json` 的调用约定）。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("模型被调用的次数比剧本多")
        return self.replies.pop(0)


class BrokenLLM:
    """每次调用都炸（走 `judge_failed:<类名>` 那一档）。"""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("网关炸了")


def _f(store: Store, llm=None, **cfg) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root, **cfg}, llm=llm)


def _new_plan(f: AgentF, *, owner: str = "F", testable: str = "存在反例或有限界",
              key: str = "PK-INF") -> str:
    return f.create_plan("难题：证明或否证某个族的存在性", key, subgoals=[
        {"sid": "s1", "text": "判定这条难题", "owner": owner, "testable": testable},
    ])["plan_id"]


def _round(**fields) -> str:
    """造一份成形产物的 JSON 文本（缺省补上公共字段）。"""
    base = {"strategy": "小情形搜索找模式", "why_strategy": "先看小情形有没有模式"}
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


# ============================================================ 正控：四档产物都能交出来


def test_a_wired_f_really_advances_one_round(store: Store):
    """正控（D42 的核心）：接上缝的 F 交 `reduction` ⇒ 子目标真被归约、history 长一条。"""
    llm = FakeLLM(_round(product="reduction", reason="把存在性归约成两个更小的判定",
                         new_subgoals=[{"goal": "判定小情形 n<=12",
                                        "testable": "枚举 n<=12 全部候选"},
                                       {"goal": "判定构造族是否无限",
                                        "testable": "给出参数族与它的 girth 公式"}]))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    assert out["action"] == "reduction", out
    assert out["outcome"] == "progress", out
    row = store.rows("attack_plans")[0]
    sids = [s["sid"] for s in row["subgoals"]]
    assert sids == ["s1", "s2", "s3"], sids
    assert row["subgoals"][1]["owner"] == "F" and row["subgoals"][1]["status"] == "todo"
    rec = row["history"][-1]
    assert rec["product"] == "reduction" and rec["strategy"] in AR.STRATEGIES, rec
    # 整份产物进 history（D42）：归约出来的子目标不许只活在模型那一句回复里
    assert [g["goal"] for g in rec["product_detail"]["new_subgoals"]], rec
    # 提示词里必须带着受控值（四档 + 九招 + #5 的禁用词 + 这一条子目标的可检验形式）
    assert llm.prompts and "reduction" in llm.prompts[0] and "dead_end" in llm.prompts[0]
    for word in AR.F_BANNED_MARKERS:
        assert word in llm.prompts[0], f"提示词没把禁用词 {word} 告诉模型"


def test_a_proof_round_is_progress_but_never_closes_the_subgoal(store: Store):
    """`proof`：论证进 history 的 `product_detail`；子目标不因此关闭（FC-22）。

    步的形状是 `attackround._clean_step` 定的 `{text, cites, assumption}` ——
    提示词里也必须逐字给这三个键（写错键名 ⇒ 模型照提示词写、判据照样拒，
    那正是"提示词与判据分家"）。
    """
    llm = FakeLLM(_round(product="proof", steps=[
        {"text": "对于 n=14 的具名图，每条边落在 4 个 k-圈里", "cites": ["exp:0004"]},
    ]))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    row = store.rows("attack_plans")[0]
    assert out["outcome"] == "progress", out
    assert row["subgoals"][0]["status"] != "closed", "FC-22：没有 proof 级实验就不许关闭"
    rec = row["history"][-1]
    assert rec["product"] == "proof"
    assert len(rec["product_detail"]["steps"]) == 1, rec
    assert "assumption" in llm.prompts[0], "提示词没给步的真实形状（text/cites/assumption）"


def test_a_counterexample_request_becomes_an_e_owned_subgoal(store: Store):
    """`counterexample_request`：判据变成一条 owner=E 的新子目标（下一轮派给它跑）。"""
    llm = FakeLLM(_round(product="counterexample_request",
                         script_spec={"criterion": "每条边的 k-圈数 >= 2",
                                      "params": "m=3, k=6, n<=18",
                                      "expected_bound": "n_max=18"},
                         why_it_decides="这条判据直接把 R(3,6) 判死或判活"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    row = store.rows("attack_plans")[0]
    assert out["action"] == "counterexample_request", out
    owners = {s["sid"]: s["owner"] for s in row["subgoals"]}
    assert owners == {"s1": "F", "s2": "E"}, owners
    assert "每条边的 k-圈数 >= 2" in row["subgoals"][1]["text"], row["subgoals"][1]


def test_a_dead_end_round_is_blocked_with_a_controlled_reason(store: Store):
    """`dead_end`：如实 `blocked`（受控理由 + `in_flight`），不许自动重试同一条。"""
    llm = FakeLLM(_round(product="dead_end", reason="方法不适用",
                         evidence="这条子目标里没有可判定的有限形式",
                         best_partial=[{"what": "已把难题缩到 k=6 这一支", "ids": [],
                                        "why_partial": "不是进展，是范围"}],
                         why_strategy="九招里没有一招能落在没有有限形式的命题上"))
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    row = store.rows("attack_plans")[0]
    assert out["outcome"] == "no_change", out
    assert row["subgoals"][0]["status"] == "blocked"
    assert row["subgoals"][0]["blocked_reason"], "blocked 必须说清被什么卡住"
    assert row["subgoals"][0].get("in_flight") is True
    rec = row["history"][-1]
    assert rec["product"] == "dead_end" and rec["dead_end_reason"] == "方法不适用", rec
    assert rec["best_partial"], rec


# ============================================================ 负控：三种"没推成"分得开


def test_an_unwired_f_still_says_it_is_not_wired(store: Store):
    """负控（D42 的反面）：没接缝时仍是 `dead_end(缺工具)`，不许假装推了一轮。"""
    f = _f(store)                      # llm=None
    pid = _new_plan(f)
    f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec["product"] == "dead_end", rec
    assert rec["dead_end_reason"] == "缺工具", rec
    assert "尚未接线自动推理" in rec["detail"], rec["detail"]


def test_a_broken_seam_is_recorded_as_not_checked_not_as_a_dead_end(store: Store):
    """三态：缝炸了 ⇒ `no_change` + `judge_failed:…`，不落产物（不是"这条路死了"）。"""
    llm = BrokenLLM()
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert llm.calls == 1, "炸了的那一次该只调一次"
    assert out["outcome"] == "no_change", out
    assert rec.get("product_detail") is None, "没查成不许落产物（那会把'没查'写成'查了'）"
    assert "judge_failed:RuntimeError" in rec["detail"], rec["detail"]
    assert store.rows("attack_plans")[0]["subgoals"][0]["blocked_reason"].startswith("LLM 判定没查成")


def test_a_malformed_round_comes_back_with_the_original_reason(store: Store):
    """不成形 ⇒ 原话带回去（而不是只说"没进展"）：调用方要能据它改提示词。"""
    llm = FakeLLM(_round(product="reduction", new_subgoals=[]))   # reduction 必须给 1–3 条
    f = _f(store, llm=llm)
    pid = _new_plan(f)
    out = f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert out["outcome"] == "no_change", out
    assert rec.get("product_detail") is None, rec
    assert "不成形" in rec["detail"] and "1–3" in rec["detail"], rec["detail"]


def test_the_pre_spend_gate_stops_the_call_before_any_money_is_spent(store: Store):
    """I9：子目标没有可检验形式 ⇒ 一轮的钱都不花（模型一次都没被调用）。"""
    llm = FakeLLM()                    # 一次都不该被调用（调了就 AssertionError）
    f = _f(store, llm=llm)
    pid = _new_plan(f, testable="")
    out = f.step(pid)

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert llm.prompts == [], "闸门没过却发了模型调用"
    assert rec["product"] == "dead_end" and rec["dead_end_reason"] == "缺定义", rec
    assert "可检验形式" in rec["detail"], rec["detail"]
    assert out["outcome"] == "no_change", out
