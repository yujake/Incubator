"""判据：system 提示词的前缀稳定性 + 缓存读数进 run 记录（2026-10-19）。

## 这一组守什么（以及为什么现在才有）

上游的前缀缓存（`usage.prompt_cache_hit_tokens`）只有在**前缀逐字节相同**时才命中。
框架里 system 提示词是每一段对话的前缀，而它每一步都重算：

    agent_loop.py:2882（开局一次）→ agent_loop.py:3090（每个步边界再算一次）
    改前那一步（旧实现，今 `_system_at_step` 的前身）把每步会变的 `budget_left` / `notebook`
    **重算并写回 system** ⇒ 几乎每一步整条 system 都换了 ⇒ 前缀缓存结构性永不命中。

实测（2026-10-19 本机、M 岗、非零价）：

    第 0 步 system 54,902 字 / 第 1 步 54,902 字，identical=False
    从第 35,035 个字符起不同：`剩余预算：5.000000 美元（…已用 0.000000…）`
                          vs  `剩余预算：4.998800 美元（…已用 0.001200…）`

同时，上游的缓存两格从 2026-10-14 起就被读进来了（`llmseam.py:459-460`），
计价也按两档算了（`modelcost.py:410-432`），但**从没汇总进任何 run 记录** ——
于是"提示词改完到底省了多少"在真机上一条读数都没有。

## 判据（四条，每条带负控）

1. 稳定性：同一角色 / 同一 task / 同一 registry 下，连续两步的 system 逐字节相同。
   负控：把每步会变的东西塞回 system（时间戳 / 步号 / 预算）⇒ 判据红，且报出
   "从第几个字符起不同 + 前后各 80 字"。
2. 缓存读数：每一步的 `step` 记录里都有 `prompt_cache`（`hit` / `miss` 三态）；
   `LoopRun.prompt_cache` 有汇总，`agent_run_end` 带着它，收工那行有一句人话。
   负控：把那个键从事件里删掉 ⇒ 判据红（`missing_prompt_cache_steps`）。
3. 自洽：上游给了读数时 `hit + miss == tokens_in`。
4. 动态段白名单：变了的 system 段必须登记在 `promptstability.DYNAMIC_SECTION_WHITELIST`
   里（初始为空）。负控：白名单外塞一段动态内容 ⇒ 红。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import agent_prompts as AP
from agentflow import promptkit as PK
from agentflow import promptstability as PS
from agentflow import sessions as SS
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam

from test_agent_loop import _wired

#: 纯工具步骤 + 收工（两步足够看"连续两步的 system"）。
_SCRIPTS = {"M": [json.dumps({"tool": "conductor.role_spec", "args": {"role_name": "C"},
                              "why": "先看一眼 C 的规格"}, ensure_ascii=False),
                  json.dumps({"final": "收工"}, ensure_ascii=False)]}


class _CacheGateway:
    """照剧本回答、并**报出缓存读数**的替身模型（上游 `usage.prompt_cache_*` 的形状）。

    `hit=None` / `miss=None` 就是"上游没给这两格"那一档（三态里的 unknown）——
    它与 `0`（明说零命中）必须在读数上分得开，所以用两个不同的替身跑两趟。
    """

    spec = type("Spec", (), {"vendor": "deepseek", "model": "deepseek-flash",
                             "api_key": "fake"})()

    def __init__(self, replies: list[str], *, hit: int | None, miss: int | None,
                 tokens_in: int = 1000, tokens_out: int = 100) -> None:
        self.replies = list(replies)
        self.hit, self.miss = hit, miss
        self.tokens_in, self.tokens_out = tokens_in, tokens_out
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        self.systems.append(system or "")
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {
            "ok": True, "text": text, "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out, "cache_hit_tokens": self.hit,
            "cache_miss_tokens": self.miss, "error_detail": "", "error_kind": "",
            "reasoning": "", "tool_calls": (), "attempts": 1,
        })()


def _run(tmp_path: pathlib.Path, *, hit: int | None, miss: int | None,
         sid: str = "t-cache"):
    """跑一趟两步的 M（替身模型报缓存读数）；返回 `(run, gateway, root, events)`。

    会话记录按**这次的 sid** 读（`test_agent_loop._events` 钉的是 `test-run`）——
    读错 sid 会得到一份空会话，而"空"与"没有 agent_step 事件"在断言里长得一样。
    """
    st, cond, registry, _gw, root = _wired(tmp_path, _SCRIPTS, max_steps=3)
    gateway = _CacheGateway(_SCRIPTS["M"], hit=hit, miss=miss)
    run = run_role("M", "两步之间 system 应该一个字节都不变", store=st, registry=registry,
                   conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gateway,
                                usd_budget=5.0, sid=sid),
                   workspace_root=str(root), sid=sid, from_env=False)
    events, problems = SS.read_session(root, sid=sid)
    assert not problems, problems
    return run, gateway, root, events


# ---------------------------------------------------------------- 1. 稳定性判据
def test_two_consecutive_steps_send_a_byte_identical_system(tmp_path: pathlib.Path) -> None:
    """正控（主判据）：连续两步的 system 逐字节相同 —— 前缀缓存命中得起来的前提。

    真读数一起断言：字符数、前 80 字、sha256。只断言"相等"而不断言"它不是空串/
    不是同一份脚本"的话，一个把 system 渲染成空的实现也能过（反真空）。
    """
    run, gateway, _root, events = _run(tmp_path, hit=600, miss=400)
    assert run.stop_reason == "final", run.to_dict()
    systems = gateway.systems
    assert len(systems) >= 2, systems

    reading = PS.step_stability(systems[0], systems[1])
    assert reading["stable"] is True, reading["reason"]
    assert reading["first_diff"] is None, reading
    assert reading["prev_chars"] == reading["cur_chars"] == len(systems[1]), reading
    # 反真空：这不是"两边都空"或"两边都差不多短"那种假相等。
    assert reading["prev_chars"] > 20_000, reading
    assert systems[0][:80] == systems[1][:80], (systems[0][:80], systems[1][:80])
    assert systems[0][:20].startswith("你是 M 号角色"), systems[0][:20]

    # 会话记录里也一条"system 变了"的红灯都不该有。
    red = [e for e in events if e.get("kind") == "agent_note"
           and "system 在步边界上变了" in str(e.get("note"))]
    assert not red, red


def test_every_role_renders_a_stable_system_across_steps(tmp_path: pathlib.Path) -> None:
    """十个角色各走一遍：**静态事实相同**时，第二步的 system 与第一步逐字节相同。

    为什么逐角色（而不是只测 M）：某一段是"可调用对象、读外部状态"时，只有那个角色
    的提示词会随步漂移（`Section.text` 允许 lambda）。这里用 `AgentLoop._system_at_step`
    罚真身那条路（它正是每个步边界上跑的那一个），两步之间只让**每步会变的两格**变
    —— 而它们已经被 `split_facts` 挪出去了。
    """
    st, cond, registry, _gw, root = _wired(tmp_path, _SCRIPTS, max_steps=3)
    facts = dict(task="角色渲染稳定性", summoned_by="user", task_id="t-r", depth=1,
                 parent_task_id="", children="", board="", budget_left="1.000000 美元",
                 inbox="（没有收到留言）", workspace_root=str(root), availability=None,
                 notebook="（草稿本还是空的）", user_replies="", toolchain_facts="",
                 toolchain_formal="", parent_limits="")
    for role in sorted(AP.ROLE_BRIEFS):
        loop = AL.AgentLoop(role=role, session_root=root, registry=registry,
                            conductor=cond,
                            seam=LlmSeam(role=role, session_root=root, gateway=None,
                                         sid="t-role"))
        system_facts, _moved = PS.split_facts(facts)
        first = AP.system_prompt(role, registry=registry, **system_facts)
        # 第二步：每步会变的那两格在**原始事实**里已经变了（花销涨了 / 笔记多了一条），
        # 但它们不该影响 system —— 这正是静态/动态分离要证明的事。
        later = dict(facts)
        later["budget_left"] = "0.500000 美元（上限 1.000000，已用 0.500000，读数来自 per_seam）"
        later["notebook"] = "- [第 2 步] 记一笔"
        later_system_facts, moved = PS.split_facts(later)
        assert moved == {"budget_left": later["budget_left"], "notebook": later["notebook"]}, moved
        second = loop._system_at_step(later_system_facts, first, step=1)
        assert second == first, (
            f"{role} 的第二步 system 变了（第一步 {len(first)} 字 / 第二步 {len(second)} 字）："
            + PS.stability_problem(first, second))


def test_a_timestamp_in_the_system_makes_the_criterion_red(tmp_path: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（稳定性）：往 system 里塞一个**每步会变**的东西 ⇒ 判据必红。

    这里塞的是**时间戳 + 步号**（`time.time()` 的六位小数 + 一个自增计数）：
    它比"预算变了"更硬 —— 预算要花掉钱才变，时间戳不花钱也会变。所以"它红了"
    证明这条判据量的是**前缀逐字节相同**，而不是"恰好这一趟预算没动"。
    """
    import time

    original = AP.system_prompt
    renders = {"n": 0}

    def leaky_system_prompt(role: str, **kw: Any) -> str:
        text = original(role, **kw)
        renders["n"] += 1
        # 这就是那个"每步都会变的一格"：改前是 `TASK_BUDGET` 里的余额，现在塞什么都一样。
        return text + (f"\n现在时刻：{time.time():.6f}（第 {renders['n']} 次渲染；"
                       "这一段是每步都会变的探针）")

    monkeypatch.setattr(AP, "system_prompt", leaky_system_prompt)

    run, gateway, _root, events = _run(tmp_path, hit=600, miss=400, sid="t-red")
    assert run.stop_reason == "final", run.to_dict()
    systems = gateway.systems
    assert len(systems) >= 2, systems

    # ① 判据红：两步的 system 不同，且能点名"从第几个字符起不同"。
    reading = PS.step_stability(systems[0], systems[1])
    assert reading["stable"] is False, "塞了时间戳还判绿 ⇒ 这条判据什么也没测"
    diff = reading["first_diff"]
    assert diff and diff["index"] >= 0 and diff["position"] == diff["index"] + 1, diff
    assert "从第" in reading["reason"] and "个字符起不同" in reading["reason"], reading["reason"]
    # 前后各 80 字真的端上来了（不是只有一句"变了"）。
    assert "现在时刻" in diff["prev_context"] and "现在时刻" in diff["cur_context"], diff
    # 位置也对：注入的那一段在 system 尾部 ⇒ 差异点必然落在最后 200 个字符里。
    assert diff["index"] > len(systems[0]) - 200, diff

    # ② 红灯读数落进会话记录（带同一份 diff），于是"第几步开始不重合"事后可查。
    notes = [e for e in events if e.get("kind") == "agent_note"
             and "system 在步边界上变了" in str(e.get("note"))]
    assert notes, "system 变了却没留读数 ⇒ 事后答不出'从第几步起前缀不重合'"
    assert notes[0]["system_stability"]["stable"] is False, notes[0]
    # 落档的那一份 diff 与"发给模型的两步"落在同一处尾巴上（不是两个人都说"变了"
    # 而指的不是同一段 —— 那种"都红"读不出该改哪儿）。
    assert abs(notes[0]["system_stability"]["first_diff"]["index"] - diff["index"]) <= 200, notes[0]


# ---------------------------------------------------------------- 2. 缓存读数进记录
def test_every_step_records_the_upstream_cache_readings(tmp_path: pathlib.Path) -> None:
    """正控：上游给了读数 ⇒ 每一步的 step 记录都带着它，且 `hit + miss == tokens_in`。

    `run.prompt_cache` 的汇总与"收工那一行"的人话一起判：
    没有那行字，命中率就只活在 JSON 里，而"收工时看一眼"是这一格的全部用途。
    """
    run, gateway, _root, events = _run(tmp_path, hit=600, miss=400, sid="t-known")
    assert run.stop_reason == "final", run.to_dict()
    steps = [e for e in events if e.get("kind") == "agent_step"]
    assert steps, events
    # ⚠️ 收工那一步**不落 `agent_step`**（它在公共尾段之前 `break`，见
    # `LoopRun.final_payload` 那段说明）⇒ 它的 step 记录只在 `run.steps` 里。
    # 所以"每步都有读数"要在两处各判一次，只判事件会漏掉收工那一步。
    assert len(run.steps) == 2 and len(steps) == 1, (len(run.steps), len(steps))

    for event in steps:
        cache = event.get("prompt_cache")
        assert cache is not None, f"第 {event.get('index')} 步没有 prompt_cache：{event}"
        assert cache["prompt_cache_hit_tokens"] == 600, cache
        assert cache["prompt_cache_miss_tokens"] == 400, cache
        assert cache["tokens_in"] == 1000, cache
        # 自洽判据：上游给了这两格时，它们相加必须等于 prompt_tokens。
        assert (cache["prompt_cache_hit_tokens"]
                + cache["prompt_cache_miss_tokens"] == cache["tokens_in"]), cache
        assert cache["known"] is True and cache["called"] is True, cache

    # 每步记录的另一份（`LoopStep.to_dict()`）也要有 —— 它是 `runs/*.json` 的来源。
    for step in run.steps:
        assert "prompt_cache" in step.to_dict(), step.to_dict()
        assert step.to_dict()["prompt_cache"]["prompt_cache_hit_tokens"] == 600, step.to_dict()
        assert step.to_dict()["prompt_cache"]["known"] is True, step.to_dict()

    summary = run.prompt_cache
    assert summary["calls"] == len(run.steps) == 2, summary
    assert summary["hit"] == 600 * len(run.steps) and summary["miss"] == 400 * len(run.steps), summary
    assert summary["unknown_calls"] == 0, summary
    assert summary["mismatched_calls"] == 0, summary
    assert abs(summary["hit_rate"] - 0.6) < 1e-9, summary

    # 可省金额：按 `modelcost` 的口径（命中部分 in_hit 价、其余 in 价）直接算一遍。
    prices = steps[0]["prompt_cache"]
    expected = round(600 * (prices["usd_per_m_in"] - prices["usd_per_m_in_hit"])
                     / 1_000_000.0 * len(run.steps), 6)
    assert summary["saved_usd"] is not None, summary
    assert abs(summary["saved_usd"] - expected) < 1e-9, (summary["saved_usd"], expected)
    assert summary["saved_usd"] > 0, summary

    # 收工那一行：`agent_run_end` 带汇总，`notes` 里有一句人话（60.0%）。
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    assert ends and ends[-1]["prompt_cache"] == summary, ends
    assert "60.0%" in " ".join(ends[-1].get("notes") or []), ends[-1].get("notes")
    assert "可省" in " ".join(ends[-1].get("notes") or []), ends[-1].get("notes")
    # `to_dict()`（`runs/*.json` 的来源）也有这一格。
    assert run.to_dict()["prompt_cache"] == summary, run.to_dict()["prompt_cache"]


def test_a_silent_upstream_stays_unknown_and_is_not_folded_into_zero(tmp_path: pathlib.Path) -> None:
    """负控（三态）：上游没给缓存读数 ⇒ 记 unknown，**不许折成 0**。

    折成 0 的后果不是"少一个数"，是把两件处置方向相反的事混成一件：
    "这家上游不报这一格"（改读数口径）与"这次真的零命中"（改提示词）。
    """
    run, _gateway, _root, events = _run(tmp_path, hit=None, miss=None, sid="t-unknown")
    assert run.stop_reason == "final", run.to_dict()
    steps = [e for e in events if e.get("kind") == "agent_step"]
    assert steps, events
    for event in steps:
        cache = event["prompt_cache"]
        assert cache["prompt_cache_hit_tokens"] is None, cache
        assert cache["prompt_cache_miss_tokens"] is None, cache
        assert cache["known"] is False, cache
        assert cache["cache_tri"] == "not_reported", cache
    summary = run.prompt_cache
    assert summary["unknown_calls"] == len(run.steps), summary
    assert summary["hit"] == 0 and summary["miss"] == 0, summary
    assert summary["hit_rate"] is None, ("unknown 不许折成 0%", summary)
    assert summary["saved_usd"] is None, ("算不出来就是算不出来", summary)
    assert "unknown" in summary["why"], summary


def test_deleting_the_cache_write_makes_the_criterion_red(tmp_path: pathlib.Path) -> None:
    """负控（写入被删）：把 `prompt_cache` 从 step 事件里删掉 ⇒ 判据当场红。

    这正是"改前"的形态：改前 `agent_step` 事件里没有这一格（上游的读数只到
    `SeamCall` 为止）。判据是 `promptstability.missing_prompt_cache_steps`：
    它认的是"键不存在"，不是"值是 unknown" —— 后者是合法的第三态。
    """
    _run_ok, _gateway, _root, events = _run(tmp_path / "ok", hit=600, miss=400, sid="t-keep")
    assert PS.missing_prompt_cache_steps(events) == [], PS.missing_prompt_cache_steps(events)

    stripped: list[dict[str, Any]] = []
    for event in events:
        copy = dict(event)
        if copy.get("kind") == "agent_step":
            copy.pop("prompt_cache", None)
        stripped.append(copy)
    missing = PS.missing_prompt_cache_steps(stripped)
    assert missing, "删掉了写入还判绿 ⇒ 这条判据什么也没测"
    # 事件里**只有**非收工的那几步（收工那一步不落 `agent_step`）——
    # 这条判据只能看事件面，`run.steps` 那一半由上面那条 `LoopStep.to_dict()` 判。
    assert missing == [int(e["index"]) for e in events if e.get("kind") == "agent_step"], missing


# ---------------------------------------------------------------- 3. 动态段白名单
def _facts(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(task="白名单判据", summoned_by="user", task_id="t-w", depth=1,
                                parent_task_id="", children="", board="",
                                budget_left="1.000000 美元", inbox="（没有收到留言）",
                                workspace_root="D:/ws", availability=None,
                                notebook="（草稿本还是空的）", user_replies="",
                                toolchain_facts="", toolchain_formal="", parent_limits="")
    base.update(over)
    return base


def _assemblies(role: str, registry: Any, prev: dict[str, Any], cur: dict[str, Any]
                ) -> tuple[PK.Assembly, PK.Assembly]:
    a = AP.role_prompt_registry(role, registry=registry, **prev).assemble(AP.Scope(role=role))
    b = AP.role_prompt_registry(role, registry=registry, **cur).assemble(AP.Scope(role=role))
    return a, b


def test_no_system_section_changes_between_steps_after_the_split(tmp_path: pathlib.Path) -> None:
    """正控：分离之后，**没有任何一段**随"每步会变的两格"而变。

    这是"白名单为空"能成立的机械前提：不是"我们没发现变化"，而是
    `dynamic_sections()` 给出空列表。十个角色各扫一遍。
    """
    _st, _cond, registry, _gw, _root = _wired(tmp_path, _SCRIPTS, max_steps=3)
    prev, cur = _facts(), _facts(budget_left="0.400000 美元", notebook="- [第 2 步] 记一笔")
    prev_system, _ = PS.split_facts(prev)
    cur_system, _ = PS.split_facts(cur)
    for role in sorted(AP.ROLE_BRIEFS):
        a, b = _assemblies(role, registry, prev_system, cur_system)
        changed = PS.dynamic_sections(a, b)
        assert changed == [], f"{role}：分离之后还有段在变：{changed}"
        assert PS.unregistered_dynamic_sections(a, b) == [], role


def test_a_dynamic_section_that_is_not_registered_is_red(tmp_path: pathlib.Path) -> None:
    """负控（白名单）：两跳 —— 没登记的动态段必红，登记了就绿。

    ① 用**未分离**的事实（改前的形态）：`TASK_BUDGET` / `TASK_NOTEBOOK` 会随步变，
       而登记表是空的 ⇒ 判据点名这两段（红）。
    ② 白名单里塞一段"每步都在变的段"（步号/时钟）：它不在登记表里 ⇒ 红；
       `task_checksum` 那样显式登记它 ⇒ 绿。这一跳证明"红"不是写死的。
    """
    _st, _cond, registry, _gw, _root = _wired(tmp_path, _SCRIPTS, max_steps=3)
    raw_prev = _facts()
    raw_cur = _facts(budget_left="0.400000 美元", notebook="- [第 2 步] 记一笔")
    a, b = _assemblies("M", registry, raw_prev, raw_cur)
    flagged = PS.unregistered_dynamic_sections(a, b)
    assert "TASK_BUDGET" in flagged and "TASK_NOTEBOOK" in flagged, flagged
    # 显式登记这两段 ⇒ 同一份对比不再红（证明判据是"与登记表比"，不是"永远红"）。
    assert PS.unregistered_dynamic_sections(
        a, b, whitelist={"TASK_BUDGET", "TASK_NOTEBOOK"}) == []

    # ② 往白名单外塞一段动态内容：加一段引用"每步会变的值"的段。
    def build(facts: dict[str, Any]) -> PK.Assembly:
        reg = AP.role_prompt_registry("M", registry=registry, **facts)
        reg.section(PK.Section("PROBE_STEP_CLOCK", 9_999,
                               "现在是第 {{budget_left}} 个时刻（这一段是每步会变的探针）"))
        return reg.assemble(AP.Scope(role="M"))

    probe_a, probe_b = build(raw_prev), build(raw_cur)
    assert "PROBE_STEP_CLOCK" in PS.dynamic_sections(probe_a, probe_b), PS.dynamic_sections(
        probe_a, probe_b)
    assert "PROBE_STEP_CLOCK" in PS.unregistered_dynamic_sections(probe_a, probe_b)
    assert "PROBE_STEP_CLOCK" not in PS.unregistered_dynamic_sections(
        probe_a, probe_b, whitelist={"PROBE_STEP_CLOCK", "TASK_BUDGET", "TASK_NOTEBOOK"})


def test_the_dynamic_section_whitelist_is_registered_and_small() -> None:
    """反真空：登记表是**显式的一份**，且初始为空（不是"什么都允许"）。

    "初始为空"是一条判据而不是一种风格：登记表一空，任何一段随步变化都会被点名；
    它一旦被随手填满，前缀缓存就又会悄悄失效，而没有一条测试会因此变红。
    """
    assert isinstance(PS.DYNAMIC_SECTION_WHITELIST, frozenset), PS.DYNAMIC_SECTION_WHITELIST
    assert PS.DYNAMIC_SECTION_WHITELIST == frozenset(), PS.DYNAMIC_SECTION_WHITELIST
    # 每步会变的键也必须登记（登记表本身就是"为什么它不进 system"的出处）。
    assert set(PS.STEP_VOLATILE_FACTS) == {"budget_left", "notebook"}, PS.STEP_VOLATILE_FACTS
    assert set(PS.SYSTEM_PLACEHOLDERS) == set(PS.STEP_VOLATILE_FACTS), PS.SYSTEM_PLACEHOLDERS


def test_first_difference_reports_the_exact_position() -> None:
    """判据的读数本身：位置、前后各 80 字、长度 —— 这三个缺一个都定位不到。"""
    left = "A" * 100 + "预算 0.5" + "B" * 50
    right = "A" * 100 + "预算 0.4" + "B" * 50
    diff = PS.first_difference(left, right)
    assert diff is not None, diff
    # "A"*100 之后是 "预算 0.5"：那一位 '5' 在 0 基 105（"预算"两字 + 空格 + "0." + "5"）。
    assert diff["index"] == 105 and diff["position"] == 106, diff
    assert diff["prev_char"] == "5" and diff["cur_char"] == "4", diff
    assert diff["prev_context"].endswith("预算 0.5" + "B" * 50), diff["prev_context"][-100:]
    assert "从第 106 个字符起不同" in PS.stability_problem(left, right)
    # 逐字节相同 ⇒ None（"没变"与"变了"必须分得开）。
    assert PS.first_difference(left, left) is None
    # 一边是另一边的前缀（追加）⇒ 位置在短的那一边的末尾。
    assert PS.first_difference("abc", "abcdef")["index"] == 3


def test_the_run_record_carries_a_cache_field_even_with_no_calls(tmp_path: pathlib.Path) -> None:
    """三态之外的第零态：一步都没真发请求（没接线）⇒ 字段仍在、`calls=0`。

    为什么也要判：字段"有、但恒为零"与"字段根本没有"在 `runs/*.json` 里长得不一样，
    而"这一趟没发请求"恰恰是最常见的形态之一（没接线 / 预算已尽）。
    更关键的是它不许被折进 `unknown_calls` —— 那会把"上游不报这一格"与
    "一个请求都没发"混成同一档，而两者的处置方向相反（改读数口径 vs 去接线）。
    """
    st, cond, registry, _gw, root = _wired(tmp_path, {"M": ["{}"]}, max_steps=2)
    run = run_role("M", "没接线的一趟", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=None, sid="t-none"),
                   workspace_root=str(root), sid="t-none", from_env=False)
    assert run.stop_reason == "not_wired", run.to_dict()
    summary = run.prompt_cache
    assert summary and summary["calls"] == 0, summary
    assert summary["no_request_calls"] >= 1, summary
    assert summary["unknown_calls"] == 0, summary
    assert summary["hit_rate"] is None and summary["saved_usd"] is None, summary
    events, _problems = SS.read_session(root, sid="t-none")
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    assert ends and "prompt_cache" in ends[-1], ends
    assert "没有模型调用" in " ".join(ends[-1].get("notes") or []), ends[-1].get("notes")
