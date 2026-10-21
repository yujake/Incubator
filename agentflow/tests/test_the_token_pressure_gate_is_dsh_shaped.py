"""判据：token 压力那一道门是 DSH 形状（S-B 第①步 / 裁定 8乙 + 12-H=甲 + 12-I=甲）。

## 这一批做的是哪一半（以及没做哪一半）

做了（policy 层，可以单独判）：
1. 估值器（`tokenestimate`）：搬 DSH `dsh-token-meter/lib/types/estimate.js` 的
三支（`text/reasoning` 走密度、`tool-call` 拆名字与参数、`system` 不含逐块开销）与三个常量（`CHARS_PER_TOKEN`/`BLOCK_OVERHEAD`/`ROLE_OVERHEAD`，
名字原样保留）；"每 token 几个字符"是配置项（12-H=甲），读数里写明用的哪一档。
2. 容量标定与两道门（`compact_by_pressure`）：`thresholdTokens = floor(cw*0.8)`、
`retainTokens = floor(cw*0.16)`；`total < threshold ⇒ 一次也不压`；`retain_tokens = 0 ⇒ 只留最后一个节点`。
3. 三条不变量：节点 0 永不遮蔽 / 配对平衡回退（切点不许落在调用与结果之间）/
摘要必须更小（判据是 `>=`，等于也拒）。
4. 三态：容量读不到 ⇒ 自动路径"警告一次 + 带完整历史继续"，手动路径（`strict=True`）抛。没做（下一批）：把这一步接进循环（步边界上调一次 + 事件三件套 + LLM 摘要器 +用量记
`note="compaction"`），以及剪枝那个"假开"读数的修法。

## 为什么这一批能单独成立

它判的是口径与不变量（纯函数），而接线判的是"循环里真的调了没有"。两批分开之后，"口径对不对"与"接上了没有"是两个独立的红。
"""

from __future__ import annotations

import pytest

from agentflow import tokenestimate as TE
from agentflow.contextbudget import (
    CompactionNotSmallerError,
    ContextBudget,
    TargetPressureConfigError,
    _pairing_cuts,
    compact_by_pressure,
)


def _seq(groups: int, *, body: int = 400) -> list[dict]:
    """造一串"用户话 + 一次调用 + 它的结果"的消息（S-C 之后循环里的形态）。

    为什么按三件一组造：配对平衡那条不变量只有在真的存在"调用/结果"对时才测得到
    （一串纯 user 消息根本切不断任何配对 —— 那会让判据看起来绿、其实什么都没测）。
    """
    out: list[dict] = [{"role": "user", "content": "第0条：任务原文（节点 0）" + "字" * body}]
    for i in range(groups):
        out.append({"role": "user", "content": f"第{i + 1}条：上下文片段" + "字" * body})
        out.append({"role": "assistant", "content": "你说了",
                    "tool_calls": [{"id": f"call-{i + 1}", "type": "function",
                                    "function": {"name": "fs.read", "arguments": "{}"}}]})
        out.append({"role": "tool", "tool_call_id": f"call-{i + 1}", "content": "结果" * 200})
    return out


def test_the_estimator_matches_the_dsh_arms() -> None:
    """正控（估值器）：三支的算术与 DSH 逐条对齐，读数里写明用的是哪把尺。"""
    assert (TE.CHARS_PER_TOKEN, TE.BLOCK_OVERHEAD, TE.ROLE_OVERHEAD) == (4, 4, 4)
    assert TE.estimate_text_tokens("abcdefgh") == 2 + TE.BLOCK_OVERHEAD
    # system 那条不含逐块开销（适配器把它序列化成一段纯文本）
    assert TE.estimate_message({"role": "system", "content": "abcd"}) == 1 + TE.ROLE_OVERHEAD
    assert TE.estimate_message({"role": "system", "content": ""}) == 0
    # tool-call 那一支把名字与参数分开算（不是按整块 JSON 的字符数）
    call = {"role": "assistant", "content": "",
            "tool_calls": [{"id": "call-1", "type": "function",
                            "function": {"name": "abcd", "arguments": "efgh"}}]}
    # 空 content 也算一个块（`ceil(0/4) + BLOCK_OVERHEAD` = 4）—— 这是 DSH 的口径
    # （`estimateContent` 对每个块都收 BLOCK_OVERHEAD），不是我们的发挥。
    assert TE.estimate_message(call) == (1 + TE.BLOCK_OVERHEAD) * 2 + TE.BLOCK_OVERHEAD \
        + TE.ROLE_OVERHEAD, TE.estimate_message(call)
    # 读数里带尺：同一段文本换个档 ⇒ 数变了、`source` 也变
    est = TE.estimate_messages([{"role": "user", "content": "abcd"}],
                               chars_per_token=2.0, source="config")
    assert est.to_dict()["source"] == "config" and est.chars_per_token == 2.0, est
    assert est.tokens > TE.estimate_messages([{"role": "user", "content": "abcd"}]).tokens
    # 自检那一支（DSH 的算术 + 三态 + 中文偏差）也必须是绿的
    assert TE.selftest() == 0


def test_the_rate_is_a_config_item_with_three_states() -> None:
    """正控 + 三态（12-H=甲 的配置项）：默认档 / 配置档 / 读不到档分得开。"""
    assert TE.chars_per_token_from(None) == (4.0, "default")
    assert TE.chars_per_token_from({"context_budget": {}}) == (4.0, "default")
    assert TE.chars_per_token_from({"context_budget": {"chars_per_token": 2.5}}) == (2.5, "config")
    # 读不到那一档：不许静默回退成默认值（那会让"按 4 估的"与"配置写错了"同形）
    assert TE.chars_per_token_from({"context_budget": {"chars_per_token": "4"}}) == (None, "unknown")
    assert TE.chars_per_token_from({"context_budget": {"chars_per_token": 0}}) == (None, "unknown")
    # 装载期也拒绝（`ContextBudget` 是同一处口径的另一个入口）
    with pytest.raises(ValueError, match="必须是数"):
        ContextBudget.from_mapping({"context_budget": {"chars_per_token": "4"}})
    with pytest.raises(ValueError, match="正的有限数"):
        ContextBudget.from_mapping({"context_budget": {"chars_per_token": 0}})
    # 中文那一档的机器读数：调小 ⇒ 估价抬高（"CJK 会低估"这句话的落点）
    zh = "汉字汉字汉字汉字"
    assert TE.estimate_text_tokens(zh, chars_per_token=1.0) > TE.estimate_text_tokens(zh)


def test_the_capacity_is_calibrated_like_dsh() -> None:
    """正控（容量标定）：`floor(cw*ratio)` 两个数 + 两条自相矛盾的配置当场拒。"""
    b = ContextBudget(context_window=10_000)
    spec, problem = CB_spec(b)
    assert problem == "" and spec is not None, problem
    assert (spec.threshold_tokens, spec.retain_tokens) == (8_000, 1_600), spec
    assert spec.chars_per_token == 4.0 and spec.source == "context_window", spec
    # 直接给保留额 ⇒ 用它（不再乘比值）
    spec2, _ = CB_spec(ContextBudget(context_window=10_000, retain_tokens=200))
    assert spec2 is not None and spec2.retain_tokens == 200, spec2
    # 两条自相矛盾
    with pytest.raises(ValueError, match="retain_ratio"):
        ContextBudget(retain_ratio=0.9, threshold_ratio=0.8).validate()
    with pytest.raises(ValueError, match="同时给了"):
        ContextBudget(retain_tokens=100, retain_ratio=0.3).validate()


def CB_spec(budget: ContextBudget):
    """转发到模块内的容量标定（判据不重写一份判据）。"""
    from agentflow.contextbudget import _spec_of

    return _spec_of(budget)


def test_no_capacity_warns_and_continues_but_strict_raises() -> None:
    """三态（读不到容量）：自动路径带完整历史继续，手动路径当场抛（照 DSH）。"""
    items = _seq(6)
    soft = compact_by_pressure(items, budget=ContextBudget(context_window=0))
    assert soft.compacted is False and soft.summarizer == "none", soft
    assert "读不到容量" in soft.reason and "带完整历史继续" in soft.reason, soft.reason
    assert soft.dropped_count == 0 and soft.kept_count == len(items), soft
    assert all(str(m.get("content") or "") in soft.text for m in items), \
        "读不到容量时不许改动历史（要带完整历史继续）"
    with pytest.raises(TargetPressureConfigError, match="context_window"):
        compact_by_pressure(items, budget=ContextBudget(context_window=0), strict=True)


def test_below_the_threshold_nothing_happens() -> None:
    """负控（第一道门）：没到阈值 ⇒ 一次也不压（"没压"与"压了没效果"分得开）。"""
    items = _seq(2)
    big = ContextBudget(context_window=10_000_000)
    r = compact_by_pressure(items, budget=big)
    assert r.compacted is False and r.summarizer == "none", r
    assert "未到阈值" in r.reason and "一次也不压" in r.reason, r.reason
    assert r.shadowed_tokens == 0 and r.framed_tokens == 0, r
    assert r.dropped_count == 0 and r.kept_count == len(items), r
    assert all(str(m.get("content") or "") in r.text for m in items)


def test_the_pressure_path_compacts_and_keeps_node_zero() -> None:
    """正控 + 反真空：真的压了一次，而节点 0（任务原文）仍在（不许被折进摘要）。"""
    items = _seq(12)
    b = ContextBudget(context_window=4_000, chars_per_token=1.0)
    r = compact_by_pressure(items, budget=b)
    assert r.compacted is True and r.summarizer == "mechanical", r
    assert r.dropped_count > 0 and r.kept_count > 0, r
    assert r.shadowed_tokens > r.framed_tokens > 0, r
    assert (r.threshold_tokens, r.retain_tokens) == (3_200, 640), r
    assert r.shadowed_range[0] >= 1, f"被遮蔽的区间从 {r.shadowed_range} 起 —— 节点 0 被压了"
    assert "第0条：任务原文" in r.text, "任务原文那一节不在压缩后的历史里（节点 0 不变量破了）"
    assert "早期" in r.text and "已压缩" in r.text, r.text[:80]


def test_the_tail_never_splits_a_call_from_its_result() -> None:
    """正控（配对平衡）：切点不许落在"一次调用"与"它的结果"之间。

    正控：压完保留的那一段里，每一条 tool 都有它上面那条 assistant 给的 id。
    负控：把切点故意挪到"调用与结果之间" ⇒ 配对表在那一刀上必须是 False
    （判据自己有分辨力，而不是恒真）。
    """
    items = _seq(12)
    b = ContextBudget(context_window=4_000, chars_per_token=1.0)
    r = compact_by_pressure(items, budget=b)
    kept: list[dict] = []
    for m in items:
        if str(m.get("content") or "") in r.text:
            kept.append(m)
    # 保留下来的 tool 必须与它上面那条 assistant 配对（同进同出）
    for i, m in enumerate(kept):
        if m["role"] == "tool":
            prev = kept[i - 1] if i else {}
            ids = {c["id"] for c in (prev.get("tool_calls") or [])}
            assert m["tool_call_id"] in ids, (prev, m)
    # 负控：配对表在"调用/结果之间"那一刀上是 False（分辨力）
    cuts = _pairing_cuts(items)
    # `_seq` 的排布是 0=节点0 / 1=user / 2=assistant / 3=tool ⇒ 那一刀在 3 上。
    assert cuts[3] is False, "第 2 条与第 3 条之间正是'调用与结果之间'，配对表该说 False"
    assert cuts[1] is True and cuts[2] is True and cuts[4] is True, cuts[:6]


def test_a_summary_that_is_not_smaller_is_a_failure() -> None:
    """负控（摘要必须更小，判据是 `>=`）：更大 ⇒ 判失败；错误文本里必须写明"等于也拒"。"""
    items = _seq(12)
    b = ContextBudget(context_window=4_000, chars_per_token=1.0)
    with pytest.raises(CompactionNotSmallerError) as bad:
        compact_by_pressure(items, budget=b, summarize=lambda _early: "啰嗦" * 5_000)
    assert ">=" in str(bad.value) and "等于也拒" in str(bad.value), str(bad.value)
    # 正控对照：一个真的更小的摘要（LLM 那一档的读数也叫 `llm`）
    ok = compact_by_pressure(items, budget=b, summarize=lambda _early: "一句话摘要。")
    assert ok.compacted is True and ok.summarizer == "llm", ok
    assert ok.framed_tokens < ok.shadowed_tokens, ok


def test_the_usage_anchor_can_trigger_the_gate() -> None:
    """正控（压力基线）：上一轮的真实 usage 更大时以它为准（读数写明取自哪一半）。"""
    items = _seq(12)
    b = ContextBudget(context_window=10_000)          # 阈值 8000
    # 先把它压到"估算低于阈值"那一档：把小尺调回去（默认 4）时 12 组还不到 8000
    guess = compact_by_pressure(items, budget=b)
    assert guess.compacted is False and guess.baseline_source == "heuristic", guess
    anchored = compact_by_pressure(items, budget=b, usage_tokens=9_000,
                                   summarize=lambda _e: "一句话摘要。")
    assert anchored.baseline_source == "usage_anchor", anchored
    assert anchored.compacted is True, "锚更大却没有触发压力门 ⇒ 那一格没接上"
    assert anchored.threshold_tokens == 8_000, anchored


def test_every_step_node_carries_its_own_price(tmp_path) -> None:
    """正控（节点计价）：每一步的 `agent_step` 事件带 `heuristic_tokens`，且它按未截断那份算。

    为什么这一格重要（施工单 §2 逐字）：压力门的输入是"历史值多少 token"。
    若计价用的是 `_for_record` 的截断副本，那个数会系统性偏小 ⇒ 门永远晚一步才响，
    而"晚一步"这件事在任何读数上都看不见（门响之前没有别的症状）。
    """
    import json as _json

    from agentflow import agent_loop as AL
    import test_agent_loop as TAL
    from agentflow.agent_loop import run_role
    from agentflow.llmseam import LlmSeam

    def _reply(obj):
        return _json.dumps(obj, ensure_ascii=False)

    big = "长" * 3000                      # 大于 RECORD_CHARS(2000)：截断副本一定更小
    st, cond, registry, gw, root = TAL._wired(
        tmp_path, {"M": [_reply({"tool": "conductor.role_spec", "args": {"role_name": "C"},
                                 "why": "看一眼"}), _reply({"final": "收工"})]}, max_steps=3)
    run = run_role("M", "给节点计价", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                price=(0.0, 0.0), sid="t-price"),
                   workspace_root=str(root), sid="t-price", from_env=False)
    assert run.stop_reason == "final", run.to_dict()
    with open(root / "sessions" / "t-price.jsonl", encoding="utf-8") as fh:
        steps = [_json.loads(ln) for ln in fh if ln.strip()
                 and _json.loads(ln).get("kind") == "agent_step"]
    assert steps, "没有 `agent_step` 事件 ⇒ 夹具没跑到那一步"
    for e in steps:
        assert int(e.get("heuristic_tokens") or 0) > 0, e
    # "按未截断那份算"的机器读数：拿一份大结果比 —— 截断副本的价一定更小。
    from agentflow import tokenestimate as TE

    raw = {"ok": True, "data": big}
    live = AL.step_node_tokens(0, {"tool": "fs.read", "args": {"path": "a"}}, raw)
    clipped = AL.step_node_tokens(0, {"tool": "fs.read", "args": {"path": "a"}},
                                  AL._for_record(raw))
    assert live > clipped, (live, clipped)
    # 与估值器本身对得上（不是另算了一套）
    pair = [AL.assistant_message(0, {"tool": "fs.read", "args": {"path": "a"}}, name="step",
                                 content=AL._spoken_half(0, {"tool": "fs.read",
                                                             "args": {"path": "a"}})),
            AL.tool_message(0, AL._result_half(raw), name="step")]
    assert live == TE.estimate_messages(pair).tokens, (live, TE.estimate_messages(pair).tokens)