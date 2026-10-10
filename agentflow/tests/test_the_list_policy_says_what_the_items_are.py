# -*- coding: utf-8 -*-
"""「清单型交付」那一条政策要说清清单的条目是什么，以及 C 的读数在里面的位置。

## 守的是什么（T4 第 7/8 趟 `t4g`/`t4h` 的真机读数）

题面问"代数几何方向有哪些值得做的开放问题，交付一份清单与说明"，而两趟的交付物
`documents/0000` 逐字在讲我们自己的关系图：`t4g` 的 5 条断言里两条在讲
"只 0007 与 0009 有可读全文"、`t4h` 的 4 条断言全在讲结构洞分析（"得到 10 条值得研究的
关系候选"）、度数中心性热点榜、`C.contradictions` 的 weak 线索、D 的六条问题置信度 low。
⇒ 交付物成了"我们自己的图分析报告"，答的不是题面上那个问题。

同族的对照：`t4d`/`t4e`/`t4f` 答的是对的题（Hodge 猜想、最小模型纲领、Schottky 问题、
Virasoro 猜想…）—— 漂移只出现在后面两趟。

## 为什么是提示词而不是判据

"清单里那几条算不算答了题"是语义判断（机器判不了），而 M 手里两句话都在
（「清单本体是 `documents` 里的行」+「调查型任务要把 C 用起来」），缺的是它们的关系：
C 的读数是依据，不是清单的本体。所以这一批补的是那半句，判据只钉"那半句在不在、
以及它有没有把两头都说清"。

判据：
* 正控：M 的 policy 里那一条要同时出现「清单本体」与「`lit:` 为据」与「不代替清单本体」；
* 负控：`specs/m.py` 与 `agent_prompts.ROLE_BRIEFS["M"]` 两处逐字一致（这条政策不许只改一处）；
* 反真空：那半句要真的写在清单那一条上（不是写在别条上凑数）。
"""
from __future__ import annotations

from agentflow import agent_prompts as AP
from agentflow import capabilities as C


def _list_policy(texts: tuple[str, ...]) -> str:
    """挑出「清单本体」那一条（判据只认这一条，不看别条里有没有那几个词）。"""
    for t in texts:
        if "清单本体" in t:
            return str(t)
    return ""


def test_positive_the_list_policy_says_what_the_items_are() -> None:
    """正控：清单那一条要把两头都说清 —— 条目是「题目问的那个领域里的事」，C 是「依据」。"""
    policy = C._specs.builtin_specs()["M"].brief.policy
    one = _list_policy(policy)
    assert one, "M 的 policy 里找不到「清单本体」那一条 ⇒ 判据没接上（不是没问题）"
    for needle in ("题目问的那个领域", "`lit:` 为据", "依据", "不代替清单本体"):
        assert needle in one, f"清单那一条缺「{needle}」：{one[:200]}"
    # 反真空：这半句必须落在这一条上（别条里出现不算）
    assert "不代替清单本体" in one, one


def test_negative_the_two_copies_of_the_policy_stay_in_step() -> None:
    """负控：`specs/m.py` 与 `agent_prompts.ROLE_BRIEFS["M"]` 的 policy 逐字一致。

    这一条在本次施工里当场红过一次（两处我各写了一遍、中间的空格差一处），
    判据把它抓住了 —— 所以单列一条。
    """
    a = tuple(C._specs.builtin_specs()["M"].brief.policy)
    b = tuple(AP.ROLE_BRIEFS["M"].policy)
    assert len(a) == len(b), (len(a), len(b))
    diff = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
    assert not diff, f"两处 M policy 不一致（第 {[d[0] for d in diff]} 条）"
    assert _list_policy(b), "prompts 那一侧的「清单本体」那一条不见了"


def test_anti_vacuum_the_rule_names_both_ends_not_only_one() -> None:
    """反真空：只写"要有 C 的读数"或只写"清单本体是 documents 行"都不算 —— 要两头都点到。"""
    policy = C._specs.builtin_specs()["M"].brief.policy
    one = _list_policy(policy)
    assert "依据" in one and "不代替清单本体" in one, one
    # 而"把 C 用起来"那一条仍然在（不是把两条合并掉了）
    assert any("要把 C 用起来" in str(t) for t in policy), "M 的 policy 里「要把 C 用起来」那一条不见了"
