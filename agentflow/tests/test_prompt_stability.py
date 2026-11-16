"""判据：system 提示词的前缀稳定性 + 缓存读数进 run 记录（2026-10-19）。
## 这一组守什么（以及为什么现在才有）
上游的前缀缓存（`usage.prompt_cache_hit_tokens`）只有在前缀逐字节相同时才命中。框架里 system 提示词是每一段对话的前缀，而它每一步都重算：
agent_loop.py:2882（开局一次）→ agent_loop.py:3090（每个步边界再算一次）改前那一步（旧实现，今 `_system_at_step` 的前身）把每步会变的 `budget_left` /
`notebook`重算并写回 system ⇒ 几乎每一步整条 system 都换了 ⇒ 前缀缓存结构性永不命中。
实测（2026-10-19 本机、M 岗、非零价）：
第 0 步 system 54,902 字 / 第 1 步 54,902 字，identical=False从第 35,035 个字符起不同：`剩余预算：5.000000 美元（…已用 0.000000…）`vs
`剩余预算：4.998800 美元（…已用 0.001200…）`
同时，上游的缓存两格从 2026-10-14 起就被读进来了（`llmseam.py:459-460`），计价也按两档算了（`modelcost.py:410-432`），但从没汇总进任何 run 记录
——于是"提示词改完到底省了多少"在真机上一条读数都没有。
## 判据（四条，每条带负控）
1. 稳定性：同一角色 / 同一 task / 同一 registry 下，连续两步的 system 逐字节相同。
负控：把每步会变的东西塞回 system（时间戳 / 步号 / 预算）⇒ 判据红，且报出"从第几个字符起不同 + 前后各 80 字"。
2. 缓存读数：每一步的 `step` 记录里都有 `prompt_cache`（`hit` / `miss` 三态）；
`LoopRun.prompt_cache` 有汇总，`agent_run_end` 带着它，收工那行有一句人话。负控：把那个键从事件里删掉 ⇒ 判据红（`missing_prompt_cache_steps`）。
3. 自洽：上游给了读数时 `hit + miss == tokens_in`。
4. 动态段白名单：变了的 system 段必须登记在 `promptstability.DYNAMIC_SECTION_WHITELIST`
里（初始为空）。负控：白名单外塞一段动态内容 ⇒ 红。
"""
from __future__ import annotations

import json
import pathlib
import re
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
    """照剧本回答、并报出缓存读数的替身模型（上游 `usage.prompt_cache_*` 的形状）。

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

    会话记录按这次的 sid 读（`test_agent_loop._events` 钉的是 `test-run`）——
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
    """十个角色各走一遍：静态事实相同时，第二步的 system 与第一步逐字节相同。

    为什么逐角色（而不是只测 M）：某一段是"可调用对象、读外部状态"时，只有那个角色
    的提示词会随步漂移（`Section.text` 允许 lambda）。这里用 `AgentLoop._system_at_step`
    罚真身那条路（它正是每个步边界上跑的那一个），两步之间只让每步会变的两格变
    —— 而它们已经被 `split_facts` 挪出去了。
    """
    st, cond, registry, _gw, root = _wired(tmp_path, _SCRIPTS, max_steps=3)
    facts = dict(task="角色渲染稳定性", summoned_by="user", task_id="t-r", depth=1,
                 parent_task_id="", children="", board="", budget_left="1.000000 美元",
                 inbox="（没有收到留言）", workspace_root=str(root), availability=None,
                 notebook="（草稿本还是空的）", user_replies="", toolchain_facts="",
                 toolchain_formal="", parent_limits="",
                 # 2026-10-22（业主 B-3）：我名下被 V 判「有毛病」的证明明细也登记在
                 # `STEP_VOLATILE_FACTS` 里 ⇒ 这一份探针事实必须给齐它，否则下面
                 # "一格不少、一格不多"那条会读到"登记表里有一格没喂进来"。
                 v_rejections="（名下没有被 V 判「有毛病」的证明）")
    for role in sorted(AP.ROLE_BRIEFS):
        loop = AL.AgentLoop(role=role, session_root=root, registry=registry,
                            conductor=cond,
                            seam=LlmSeam(role=role, session_root=root, gateway=None,
                                         sid="t-role"))
        system_facts, _moved = PS.split_facts(facts)
        first = AP.system_prompt(role, registry=registry, **system_facts)
        # 第二步：每步会变的那两格在原始事实里已经变了（花销涨了 / 笔记多了一条），
        # 但它们不该影响 system —— 这正是静态/动态分离要证明的事。
        later = dict(facts)
        later["budget_left"] = "0.500000 美元（上限 1.000000，已用 0.500000，读数来自 per_seam）"
        later["notebook"] = "- [第 2 步] 记一笔"
        later_system_facts, moved = PS.split_facts(later)
        # 2026-10-21：登记表从"每步会变"扩到"跨 run 也会变"⇒ `moved` 是登记表的全部
        # 键（`facts` 里给齐了）。这里判"一格不少、一格不多"，改动见
        # `promptstability.STEP_VOLATILE_FACTS` 上面那张两轴的说明。
        assert set(moved) == set(PS.STEP_VOLATILE_FACTS), sorted(moved)
        # 值逐格是原值（进 user 消息那一份），不是替身句。
        assert moved == {k: later[k] for k in PS.STEP_VOLATILE_FACTS}, moved
        assert moved["budget_left"] == later["budget_left"]
        assert moved["notebook"] == later["notebook"]
        assert moved["task_id"] == later["task_id"]
        second = loop._system_at_step(later_system_facts, first, step=1)
        assert second == first, (
            f"{role} 的第二步 system 变了（第一步 {len(first)} 字 / 第二步 {len(second)} 字）："
            + PS.stability_problem(first, second))

def test_a_timestamp_in_the_system_makes_the_criterion_red(tmp_path: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（稳定性）：往 system 里塞一个每步会变的东西 ⇒ 判据必红。

    这里塞的是时间戳 + 步号（`time.time()` 的六位小数 + 一个自增计数）：
    它比"预算变了"更硬 —— 预算要花掉钱才变，时间戳不花钱也会变。所以"它红了"
    证明这条判据量的是前缀逐字节相同，而不是"恰好这一趟预算没动"。
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
    #  收工那一步不落 `agent_step`（它在公共尾段之前 `break`，见
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
    # 金额比较用容差，不是改判据强度（2026-10-20 实测复现）：上面 `expected` 走的是
    # "先乘完再 `round(…, 6)`"，而实现是逐次累计后落到微美元那一档 —— 两条路的舍入方向
    # 可以差 1 个微美元（实测 0.000352 vs 0.000353，`< 1e-9` 当场红、复跑仍红）。
    # 差 1 个微美元以内的两个数说的是同一件事；真算错（价格口径用错、单位错、忘了乘步数）
    # 差的是量级，落不进这条容差里。
    #  用整数微美元比较而不是 `abs(a - b) <= 1e-6`：那两个数在二进制浮点里相减是
    # 1.0000000000000243e-06（刚好比 1e-6 大一点点）⇒ 写成 `<= 1e-6` 会留下一条
    # "差值确实是 1 个微美元、却被浮点表示判红"的假红。
    assert abs(round(summary["saved_usd"] * 1_000_000) - round(expected * 1_000_000)) <= 1, (
        summary["saved_usd"], expected)
    assert summary["saved_usd"] > 0, summary

    # 收工那一行：`agent_run_end` 带汇总，`notes` 里有一句人话（60.0%）。
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    assert ends and ends[-1]["prompt_cache"] == summary, ends
    assert "60.0%" in " ".join(ends[-1].get("notes") or []), ends[-1].get("notes")
    assert "可省" in " ".join(ends[-1].get("notes") or []), ends[-1].get("notes")
    # `to_dict()`（`runs/*.json` 的来源）也有这一格。
    assert run.to_dict()["prompt_cache"] == summary, run.to_dict()["prompt_cache"]


def test_a_silent_upstream_stays_unknown_and_is_not_folded_into_zero(tmp_path: pathlib.Path) -> None:
    """负控（三态）：上游没给缓存读数 ⇒ 记 unknown，不许折成 0。

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
    # 事件里只有非收工的那几步（收工那一步不落 `agent_step`）——
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
    """正控：分离之后，没有任何一段随"每步会变的两格"而变。

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

    ① 用未分离的事实（改前的形态）：`TASK_BUDGET` / `TASK_NOTEBOOK` 会随步变，
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


#: `STEP_VOLATILE_FACTS` 的键集账本（事务三 2026-10-21：堵审计射程的边界）。为什么另立一个常量而不是并进
#: `_FROZEN_PROMPT_DIGESTS`：那张冻结表按缺省事实渲染模板 ⇒ 它钉的是"段文本"，而 facts 迁移（把某几格事实
#: 从 system 挪进 user 消息）不改任何一段的文本 ⇒ 十格摘要一个字节都不会变。上一批（2026-10-21 第一批，
#: 2 格 → 12 格）就是这样：判据没红、也没抬版本，而模型读到的落点整个换了一遍 —— 审计射程到此为止，这条账本
#: 补上那一格。口径（`promptstability.facts_migration_problem`）：按顺序记 `(version, count, keys_sha256)`，
#: 判据只认最后一格 —— live 键集必须等于它（否则"迁了而账本没记"）、且它的 `version` 必须等于 `PROMPT_VERSION`（否则"迁了而版本没抬"）；前面的几格是历史、不参与判绿，但它们是"哪一次迁移没抬版本"
#: 在盘上的读数，所以留着。维护：动 `STEP_VOLATILE_FACTS` ⇒ 抬 `PROMPT_VERSION` 一格并在账本末尾追加一格
#: （`count` / `keys_sha256` 用 `PS.volatile_facts_digest()` 现算，不手抄）。
_VOLATILE_FACT_SETS: tuple[dict[str, Any], ...] = (
    # 上一批：`budget_left` / `notebook` + 跨 run 那十格。没抬版本（这就是那条教训）。
    {"version": "p173", "count": 12,
     "keys_sha256": "650a06dca214b4cad3c628887390c3e21fa0b6bf91ef376f86acf6c3c0ae472f",
     "note": "第一批（2026-10-21）：budget_left/notebook + 跨 run 十格；无版本痕迹"},
    # 本批：`availability` / `parent_limits` 从 system 的那两段挪进开场 user 消息。
    # 同样没抬版本（业主口径：本批不许动 `PROMPT_VERSION`）；业主抬格时把这格一起看一眼。
    {"version": "p173", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "第二批（2026-10-21）：availability / parent_limits 也搬进开场消息"},
    {"version": "p174", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p174（2026-10-21）：其它角色减负 + availability/parent_limits 迁移记账；键集未变"},
    {"version": "p175", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p175（2026-10-21）：G 的两条义务补上机械闸后压/删提示词；键集未变"},
    {"version": "p176", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p176（2026-10-21）：A 的「不造概念/不提猜想」由结构性判据接管后删除；键集未变"},
    {"version": "p177", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p177（2026-10-21）：B 的两条 policy 合并去重（三处锚点短语逐字保留）；键集未变"},
    {"version": "p178", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p178（2026-10-21）：D/F/V/M 减负（D 两条合并、V 删重复尾巴）；键集未变"},
    {"version": "p179", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p179（2026-10-21）：修掉提示词里被转义吃掉的 \brief\/\name\/\reuse\（原来渲染成控制字符）；键集未变"},
    {"version": "p180", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p180（2026-10-21）：B/D/G/H 四角色的 stance 各加一条（非平凡性分档写作 / 研究生视角六类困惑 / 入库给素材不判档 / T4 先问缺哪个工具）；键集未变"},
    {"version": "p181", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p181（2026-10-22）：多证明模型与论文对应表落地 —— B 的 register_statement 广告 proofs、V 的 verify_proof 广告 proof_no、G 加 write_mapping 动作与「先出对应表再写正文」政策、H 加「按对应表逐行核」政策；键集未变"},
    {"version": "p182", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p182（2026-10-22）：C 的 skills 多一条「最自然路径」（循序渐进优先 / 绕弯不选 / 唯一且曲折要上报并给构想）；只有 C 那一格的段变了，另九格逐字未动；键集未变"},
    {"version": "p183", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p183（2026-10-22 第二批）：C 的「最自然路径」索引行与正文补上「max_depth 是一批能搜多深、长链一批一批往回搜、前沿是下一批起点、拼起来要交代接缝」；只有 C 那一格的段变了，另九格逐字未动；键集未变"},
    {"version": "p184", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p184（2026-10-22 第三批）：业主施工单「照着 E 的方式新设角色 L（Lean 形式化者）」—— 新增 L 那一格、M 的伙伴表多一行 L、工具面新增 formal.* 两件（只挂给 L）；facts 键集未变（14 格），L 没有边所以另十格逐字未动"},
    {"version": "p185", "count": 14,
     "keys_sha256": "7b586f9861027114136160fccdc954f8b75979405466bfc809a2c42f737f4a37",
     "note": "抬版本 p185（2026-10-22 第四批）：业主口径「所有受 Lean 开关控制的提示词/工具/动作全部指向 L」—— TOOLCHAIN_FORMAL 的受众收成 formal.*（只有 L），那一段正文改成 L 的口径（statement_full/proof_text/逐步/code/formal/三态），facts 开档补一行「形式化由 L 承担」，技能索引那句翻成「开着时形式化见 L、关着时零痕迹」，specs/{e,d,g,h,m}.py 里形式化指向逐条改成 L；facts 键集未变（14 格）"},
    # 本批（业主 B-3「V 的判决必须递到 F」）：键集第一次真正动了（14 → 15）。
    # `count` / `keys_sha256` 是 `PS.volatile_facts_digest()` 的现算值，不手抄。
    {"version": "p186", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p186（2026-10-22 第五批）：业主 B-3「V 的判决必须递到 F（让 F 去修）」—— facts 键集 14 → 15，新增 v_rejections（F 名下被 V 判「有毛病」的证明明细：命题号 / 最近一签 / unresolved_errors / 错在第几步 / 那一签盖的是不是现在这一份；数据源是 verifications.statement_review_reading，念在开场那条 user 消息里）；另 F 的 policy 补一条「按它给的步号补那一步、补完重新送 V、不许绕开」⇒ 段的角色摘要只有 F 那一格变，另十格逐字未动。同一版号里并进来的第二笔（业主 B-1，2026-10-22 晚）：「被指认无可信度 / 待审核的文献不可当引文入库，只可当研究参考」写进 specs/a.py 与 specs/b.py 的 policy ⇒ A / B 两格的摘要也换了值（_FROZEN_PROMPT_DIGESTS 里那两格就是含这一句的现算值）；这一笔不做任何机械闸，lit_candidates / literature 的写入路径一个字没动"},
    # 本批（2026-10-23 收口）：L 的协作面落地。键集未变（15 格仍是那 15 格），
    # `count` / `keys_sha256` 仍是 `PS.volatile_facts_digest()` 的现算值。
    {"version": "p187", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p187（2026-10-23 收口）：L 的协作面落地 —— 入边只有 B（B → L）、出边只有 C（L → C，只派 C 梳理证明链），L 从「不可召唤」变可召唤；形式化那一格从 formal.* 两件长成三件（多出 formal.record），verify.check_formal 的角色面从三格（E/F/G）收成空。事实键集一格未动（15 格还是那 15 格）：这一批换的是「谁拿得到哪些工具」与共用段那句「形式化见 L」的正文，所以这一格记的仍是 21314a39…；那一边的读数在 _FROZEN_PROMPT_DIGESTS（共用段 SKILLS_INDEX 改了 ⇒ 十一格摘要全换），这一格只记 facts 键集，不重复记段的变化"},
    # 本批（2026-10-23 审计收口，业主「其它角色关于 E 的 Lean 侧记忆可以全面清除」最后一刀）：
    # 五元位那一段里 formal 的 owner 从 E 改成 L（`evidencebits.BIT_OWNERS` /
    # `BIT_LEDGERS`）⇒ 共用段换了值、十一格摘要全换（那一侧记在 `_FROZEN_PROMPT_DIGESTS`
    # 的 p188 那一格）。facts 键集一格未动（15 格），`count` / `keys_sha256` 仍是
    # `PS.volatile_facts_digest()` 的现算值、不手抄；这一格与 p187 唯一的区别是版本号。
    {"version": "p188", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p188（2026-10-23 审计收口）：E 的 Lean 侧记忆最后四处残留（① evidencebits 的 formal owner E→L、② 五元位渲染跟着改成「formal：L 签」、③ closing 那条 load_bearing blocker 改指 formal.check_formal/formal.formalize、④ specs/m.py 与 agent_skills.py 里 H 的采信规则那句改指「L 的形式化（formal.record 那一行）」）；另加两条 specs/e.py 的 NO_LEAN_REPLACEMENTS 把关档的 formal 那行改成不点 L 的写法（只在关档生效 ⇒ 开档摘要不受影响，见 test_l_is_isolated_when_lean_is_off 的 0 处 L 判据）。facts 键集一格未动（15 格）：这一批换的是段正文，不涉及任何一格事实的落点"},
        # p188 → p189（2026-10-23 夜）：数值穷举证明链与协作面那批。facts 键集一格未动（仍 15 格）。
        {"version": "p189", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p189（2026-10-23 夜）：T0 档／穷举证明链（E 写②③ → V 七项会审 → B 的第三方签名闸）／E→V 边／G 的数值定理规范／H 认两种 file 落点／F 两类凭据并列／V 唤起者补 E 与 B；另 E 的 Lean 侧原始设计已清干净（动作 5→4、工具 98→97）。facts 键集仍是 15 格，这一批只换段正文"},
        # p189 → p190（2026-10-24）：数值实验定理的索引链（E 上报 D、D 写目录行+索引四格、B 顺索引核签）
        {"version": "p190", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p190（2026-10-24）：D/E/M 三段变 —— E 的穷举协议第⑤步改成上报父代理、D 新增目录行+索引四格与派 B、M 明确派 D；另 agent_prompts 的 FACULTY_LOCAL[(E,敢创新)] 与 specs/e.py 同步。facts 键集仍 15 格"},
        # p190 → p191（2026-10-24）：M 的两跳 V 路线那句 / L 的图论 import 与"五步" / G 技能里那个假函数名改正
        {"version": "p191", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p191（2026-10-24）：M 写明不能直呼 V（要签经 B，M→B→V 两跳）；L 补图论 import（SimpleGraph.Basic）与自检五步；G 技能里的 write_report 改成 land_report/compose_report。facts 键集仍 15 格"},
        # p191 → p192（2026-10-24）：H 的示例路径改成登记过的根（out/paper/proofs/thm.tex）
        {"version": "p192", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p192（2026-10-24）：H 的 policy 示例路径从 proofs/thm.tex 改成 out/paper/proofs/thm.tex（原来的写法不在任何登记过的根下，skills 路径扫描判据会红）。facts 键集仍 15 格"},
        # p192 → p193（2026-10-24）：F 的凭据句去掉 Lean 字样（按 L 的协作面：F 与 L 无关系）
        {"version": "p193", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p193（2026-10-24）：F 的凭据①不再写 Lean 形式化（改成机器核过源码的原话），因为只有 B 能碰 L、F 与 L 之间没有边；另 specs/e.py 关档改写第 9 条右侧去掉 formal.record。facts 键集仍 15 格"},
        # p193 → p194（2026-10-24）：L 协作面全面对齐（授权链：用户指定 → M 派 B → B 派 L → L 报困难 → B 补证重签 → 严重时 B 通知 D）
        {"version": "p194", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p194（2026-10-24）：非 B 角色的提示词不再把 L 当伙伴、不再堆否定句；M 写明用户要形式化时派 B，B 写明六步授权链与派 L 的三样交付。facts 键集仍 15 格"},
        # p194 → p195（2026-10-24）：D-38 —— 成稿四步（正文→对应表→核三格齐→编译）与"对应表缺席即 blocker"
        {"version": "p195", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p195（2026-10-24）：G 的成稿改成四步动作序列（没调 write_mapping 等于没成稿）；M 的验收表与交付物构成加入论文对应表。facts 键集仍 15 格"},
        # p195 → p196（2026-10-24）：D-40（正文结构以 B 台账为准、形式化细节不进正文）＋ D-45（论文语言与正文同语言）＋ D-38 第二步（受控档 paper_mapping_rows）
        {"version": "p196", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p196（2026-10-24）：G 一格（写作参照物 + 论文语言）、M 一格（受控档加入 paper_mapping_rows）。facts 键集仍 15 格"},
        # p196 → p197（2026-10-24）：D-47 —— 正文里的长路径/长哈希必须可断行（\allowbreak 或 \path）
        {"version": "p197", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p197（2026-10-24）：只有 G 一格变（正文长串断行口径）。facts 键集仍 15 格"},
        # p197 → p198（2026-10-24）：业主裁定 —— G 缺命题 / 缺证明时提给 D（D 出研究手稿并登记，
        # B 从 D 侧的手稿收录入库），并写明 G→B 没有这条边（真机 cube2 / r34d 的 forbidden_edge）。
        {"version": "p198", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p198（2026-10-24）：只有 G 一格变（缺命题 → 提给 D、B 从 D 侧手稿收录、G→B 这条边不存在）。facts 键集仍 15 格"},
        # p198 → p199（2026-10-24）：M 的规划能力（业主裁定「我认为现在M侧提示词并不能使M成为一个
        # 好的planner」，四步口径由业主当场给出）。这一批换的是段正文，不涉及任何一格事实的落点。
        {"version": "p199", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p199（2026-10-24）：只有 M 一格变（policy 加七条规划口径 + 一条 M 技能「规划-先了解全貌再定方向」进技能索引；四步：先了解领域全貌 / 定方向、有多种方向分别派遣 / 定期监控全树并调整计划（第三步的射程是整棵树的各智能体行为：handoff 与产出、三类信号、指导下发且各级父知情、配合补派）/ 全部落定才进入成文阶段，外加一句「发散早、收敛晚」）。facts 键集仍 15 格"},
        # p199 → p200（2026-10-24）：监控下级那一层按已落地的实现写进所有角色的提示词
        # （业主逐字两条：「注意不只是M侧改，其它所有智能体都要知道有监控一层子代理的能力」
        # 与「到时候改M提示词那路要在监控接线后按具体实现明确」）。十个可召唤角色各加一条
        # policy（trace.children 一层 + 更深走 conductor.escalate 向 M 请求），M 的 policy
        # 第 05 条改成点名 conductor.watch / conductor.guide 的实现口径。这一批只动段正文，
        # 一格事实的落点都没挪 ⇒ facts 键集仍 15 格。
        {"version": "p200", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p200（2026-10-24）：十一格全换（十个可召唤角色各加一条「能看直接下级一层、更深走 escalate 向 M 请求」的政策；M 那一格另把 policy[05] 从「写成一句话指导」改成点名 conductor.watch / conductor.guide 的实现口径，并补一句非 M 角色会通过 escalate 请求深看）。facts 键集仍 15 格"},
        # p200 → p201（2026-10-25 收口批）：S1 把 system 的 TASK_FRAME 摘掉「你收到的留言」
        # 与「挂在你名下的工作项」两格（六块变四块），S2 把 TOOLCHAIN_FACTS 里「这条路怎么走」
        # 那一族按角色现算地摘掉。这两笔换的都是「同一格事实印在哪儿 / 印给谁」，键集一格没动的
        # 反面 —— 键名与条数仍是那 15 格（inbox / board 仍是 volatile facts，只是落点从 system
        # 挪进开场那条 user 消息，`prompt_facts` 的缺省句仍是它们的唯一来源）。
        # `count` / `keys_sha256` 仍是 `PS.volatile_facts_digest()` 的现算值，不手抄。
        {"version": "p201", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p201（2026-10-25 收口批）：十一格全换（M 的 27 条过时清理 / D·E·F 与 G·H·V·L 两批审计 / S1 摘掉 system 的 inbox·board 两格 / S2 的监控与工具面出口按角色现算 / 共用段那几处）。facts 键集仍 15 格：inbox 与 board 只是换了落点（system 段 → 开场 user 消息），键名与条数一格未动"},
        # p201 → p202（2026-10-26 收口批）：`judge.JUDGE_PROBLEMS` 多一个码 ⇒ 十一格摘要全换；
        # `verify.verify_proof.required` 去掉 `proof_text`；F 的写集去 `statements`；`specs/d.py`
        # 一处文案不再教 `force_new`。这四笔换的都是段正文与工具/写集声明，一格事实的落点都没挪
        # （`STEP_VOLATILE_FACTS` 仍是那 15 格、键名一个没改）⇒ `count` / `keys_sha256` 与上一格
        # 同值。它们仍是 `PS.volatile_facts_digest()` 的现算值，不手抄（这一格现算出来就是
        # 同一个数：事实键集没动，动的是段与声明）。
        {"version": "p202", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p202（2026-10-26 收口批）：十一格摘要全换（唯一根因是 `judge_unknown_tool` 新码进了 `THREE_STATE` 那段）；另 `verify.verify_proof.required` 去掉 `proof_text`、F 的写集去 `statements`、D 的一处文案不再教 `force_new`。facts 键集仍 15 格（键名与条数一格未动）"},
        # p202 → p203（2026-10-26 收口批）：段摘要只有 F 那一格换值（F 的 policy 多一条
        # 「依赖面写在自己的证明手稿里、由 B 读稿登记」），声明面换了 B 的一格可选参数与
        # V 三格 returns。两笔都只动文本与声明，一格事实的落点都没挪 ⇒ `count` /
        # `keys_sha256` 与上一格同值，仍是 `PS.volatile_facts_digest()` 的现算值（不手抄）。
        {"version": "p203", "count": 15,
         "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
         "note": "抬版本 p203（2026-10-26 收口批）：F 的 policy 多一条「依赖面写在证明手稿的 `## 依赖` 四列表里、由 B 读稿登记，缺段而有引用则整笔拒收 dependency_section_missing」（段摘要只有 F 那一格换值）；同批 B 的 register_statement 多一格可选参数 proof_manuscript、verify.verify_proof.returns 多三格（citations / citation_checks / citation_gate）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p203 → p204（2026-10-27 收口批）：五件一起抬版本（时钟八件的形进各角色政策 /
    # 「只到链尾」改口 / `_names` 的手那一档全列 / E 的预算读数那句补回 / M 的链式寻址）。
    # 五件都只动段文本与工具声明，一格事实的落点都没挪 ⇒ `count` / `keys_sha256` 与上一格
    # 同值，仍是 `PS.volatile_facts_digest()` 的现算值（不手抄）。
    {"version": "p204", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p204（2026-10-27 收口批）：① 时钟八件的形写进各角色政策（申请形状二选一 + 目的、目的漏填不报错走 clock.timer_purpose 补同一编号、挂机、周期性巡查的唯一写法、到点消息的例子、wait_for 三种指称、旧计时工具退役）⇒ 十格 policy 各加一条；② 「各级父也会收到通知」改成「按绝对编号链逐级由秘书转发，内容只有链尾看得到，中间各跳不读内容」⇒ 十一份 specs 都动了这一句；③ agent_prompts._names 的手那一档改成全列（M 的写工具不再被省略号吃掉 conductor.summon）⇒ 十一格的次要官能那一行都变；④ attackround.BUDGET_UNREADABLE_NOTE 那句补回 E 的 policy；⑤ M 补一句链式寻址 + 轮查带 chain_text。facts 键集仍 15 格（键名与条数一格未动）"},
    # p204 → p205（2026-10-27 第二批收口）：两件一起抬版本（新工具 `clock.wait_any`
    # 进 tools_lines 那一行 ⇒ 十一格全换；`conductor.retire_child` 的 summary 文案换 ⇒ M
    # 再换一次）。两件都只动段文本与工具声明，一格事实的落点都没挪 ⇒ `count` 与
    # `keys_sha256` 与上一格同值，仍是 `PS.volatile_facts_digest()` 的现算值（不手抄）。
    {"version": "p205", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p205（2026-10-27 第二批收口）：① 新工具 clock.wait_any（业主第三条裁定的后半个动作「直到它认为无事可做时，可启动计时器等待任意计时器返回」）进 tools_lines 那一行（名 + 摘要 + 必填参数 + 副作用），tools_lines 对每个角色都渲染 ⇒ 十一格全换；工具数 110 → 111，登记在 tools/UNIVERSAL_TOOLS（写集空：只写 out/clock/wait_any.json 这份意图账），只读角色 C/H/V 的 clock 件数 8 → 9；② conductor.retire_child 的 summary 文案换了（补「待机」那一档与 refusal_code 走 Conductor.retire_state_of 的三态读数）⇒ M 那一格再换一次；它的 returns= 不进段（只进声明快照，动的是工具面 golden 的 declarations 那一格）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p205 → p206（2026-10-27 第三批收口）：工具面 summary 十一处进 tools_lines（
    # returns 只进声明快照，不进 tools_lines、也不进 function-calling 的 description）、
    # 十一份 specs 的时钟段补 clock.wait_any 的行为口径、specs/m.py 的 delivered_to 改成列表、
    # conductor.retire_child 的 returns/docstring 补早拒支口径、attackround.BUDGET_GUARD_NOTE
    # 去行号并接上读者。五笔都只动段文本与工具声明，一格事实的落点都没挪 ⇒ `count` 与
    # `keys_sha256` 与上一格同值，仍是 `PS.volatile_facts_digest()` 的现算值（不手抄）。
    {"version": "p206", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p206（2026-10-27 第三批收口）：① 工具面 summary 十一处进 tools_lines 那一行（attack.create_plan / clock.alarm_start / clock.timer_cancel / clock.timer_list / clock.wait_any / conductor.guide / fs.edit / fs.write / table.get / table.list / verify.verify_proof —— 实现早就在，这一批才与声明对齐；同批的 returns 只进声明快照）⇒ 十一格全换；② 十一份 specs 的时钟段补 clock.wait_any 的行为口径（要求过等、且没有可等的东西 ⇒ requested=true / waiting=false，它不是「没在等」；这一档无计时而手头也没活就按交差处理）；③ specs/m.py 的 delivered_to 从「链尾那个绝对编号」改成「列表，只有一个元素 = 链尾那一个的绝对编号（不是标量；读它先取 [0]）」⇒ M 那一格再换一次；④ conductor.retire_child 的 returns 与 docstring 补早拒支那两格（target_state 空串 = 三态还没读；refusal_code 的充要条件是静默闸说话了）；⑤ attackround.BUDGET_GUARD_NOTE 去掉两个已漂的 file:line、改成符号名并接上读者（test_p09_the_guard_note_names_live_symbols）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p206 → p207（2026-10-27 第四批收口）：十四段提示词正文 ＋ 一条只读判据
    # （prompt_text_problems），一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值。
    # 它们仍是 PS.volatile_facts_digest() 的现算值，不手抄。
    {"version": "p207", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p207（2026-10-27 第四批收口）：十四段提示词正文一起换（① 形状 2 的 params 改成结构化数据并写明这一形没有 action；② 形状 2B 的 outcome 补成六档受控词表，_LOOP_BLOCK_C 同步；③ 形状 3 补公聊硬拒 public_is_not_a_conversation；④ 形状 8 的名册读数分写 agent_state / active / waiting_only 与 child_count / active_child_count；⑤ 形状 9 的 interrupt 分写 not_mine 与 no_op 两档结局；⑥ 形状 10 的 retire 改成静默闸 target_not_silent，删掉旧路与未消板项两句；⑦ 规则那一条改成每一步只发一条调用；⑧ PARENT_STOP 的原地打转两档措辞与 blocked 的形；⑨ PARENT_ROSTER 补名册读数与退役前置；⑩ COLLAB_SHAPES 补两形只认名册名与静默闸；⑪ COLLAB_NAMES 的台账号拒收收窄成四个入口、message 与 handoff 两种写法都收；⑫ EVIDENCE_RULES 的引文归一补全五类；⑬ PAPER_07_BODY 的 .tex 读数改成 unreadable 加 UnsupportedFormat；⑭ FACULTIES 头的层从两档改成三档），并新增只读判据 prompt_text_problems()（钉原地打转阈值 / 静默闸 / 公聊硬拒 / 六档 outcome / 形状条数 / .tex 读数）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p207 → p208（2026-10-27 第五批收口）：F 的 boundary 新增第 8 条（形式化不是它的活、
    # 不许由它发起）、M 的 policy 改成 proof 双来源（(a) E 的穷举 / 数值论证、(b) 形式化那
    # 一岗），D / G / V 只是伙伴表里 F 那一行的边界条数跟着变。一格事实的落点都没挪 ⇒
    # count / keys_sha256 与上一格同值，仍是 PS.volatile_facts_digest() 的现算值（不手抄）。
    {"version": "p208", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p208（2026-10-27 第五批收口）：本批只换五格摘要（D / F / G / M / V）。① specs/f.py 的 boundary 新增第 8 条「形式化不是你的活，也不许由你发起」—— 形式化只能由用户指定，指定之后由 M 转交 B、由 B 判断成本后逐条派（那条链的唯一真身是 B 的 PROOF_CHANNEL 六步）；F 不发起、不排这条流水线、不立形式化子目标、不把 method=formal 传给任何人 ⇒ F 那一格换值；② 伙伴表连带读数：D / G / V 自己的段一个字没改，但它们伙伴表里 F 那一行印着「（它的边界共 N 条）」，N 从 7 变成 8 ⇒ D / G / V 各换一次（A / B / C / E / H / L 的伙伴表里没有 F，那六格逐字未动）；③ specs/m.py 的 policy 四段改写（回执三样改成三态 + 检查器原话 + 台账里那一行 proof 记录的编号；proof 那一栏写明两个来源、两个都算 proof 级 —— (a) E 的穷举 / 数值论证、(b) 形式化那一岗且只有用户指定过才有；「形式化关闭 ⇒ proof_experiment_rows 必然为 0 ⇒ 换 reviewed_proof_rows」改成那只是 (b) 不适用、不说明 proof 栏没有读数；「挑哪一档」按两来源写，点名 numericproof.exhaustion_problems 与 counterexample_or_proof_rows，并写明不许只认 Lean、不许要求 E 拿 formal 那一支来凑，两样都没有时才写 na）＋ 审校链那一句补「证明这一档的凭据就是 B 的台账那一行 + V 的签 —— 与 Lean 开没开无关」⇒ M 那一格再换一次。同批的 agent_skills.py 手册正文（M 的指派表收件人 L → B、F 的手册第 7 条、V 的引用核实六档、B 的依赖面四列）只落盘、提示词里只有索引行且索引行没动；agent_f/* 的形式化判定（FORMAL_OWNER / FORMAL_EDGE_MISSING_REASON / E_METHODS）也不进段 ⇒ 它们不改任何一格摘要。facts 键集仍 15 格（键名与条数一格未动）"},
    {"version": "p209", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p209（2026-10-26 第六批）：table.create 的 summary 由「自动分配主键（search_requests 用 r-NNNN）」改成「主键由台账分配（这一格整格别写）」（D4 的 hand_filled_id 那一批），该工具只在 A/B/D/E/F/G/L 七格面上 ⇒ 七格提示词变；键集与 p208 相同（15 键）。"},
    {"version": "p210", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p210（2026-10-26/27 收口批）：本批九笔合并抬一格 —— ① 旧的公聊写法与 `ALL` 合成一套（写法本身已废，见 deprecated-forms 台账）（LOOP_PROTOCOL / HANDOFF_PROTOCOL / faculties_text 两格 / COLLAB_NAMES / PARENT_ROSTER，commit 5bd7e58c）；② 提示词里的台账号改成占位形 `t-NNNNNN`（Q25）；③ 程序两件 `program.list` / `program.stop` 进工具面（draft/159 的 G1/G2）；④ `conductor.post_task` 进 `UNIVERSAL_TOOLS`（Q15 裁定 (a)，C/H/V 也拿到）；⑤ `conductor.ack` 加 `close`、`retire_child` 加 `kept` / `cascade_reading`、`conductor.state` 加 `programs`（D12 / Q13 / draft/159）；⑥ `lit.*` 六格改成三态口径（Q16）；⑦ `clock.periodic_start` 的 `returns=` 补 `patrol_checklist`（巡查批）；⑧ `lit.stage_add` / `lit.stage_withdraw` 两句摘要按「补 relevance 用原槽」改写（G9）；⑨ `specs/b.py` 新增两条 policy（入库前逐条判 relevance；定理与证明改写成自然语言、改写过 V 要再签）。facts 键集仍 15 格、键名与条数一格未动（这一格记的是「事实落点没动」，动的是段文本本身）。"},
    # p210 → p211（2026-10-26 K1 收口）：本批只动段文本与工具说明的正文，一格事实的落点
    # 都没挪（`STEP_VOLATILE_FACTS` 仍是那 15 格、键名一个没换）⇒ `count` / `keys_sha256`
    # 与上一格同值，仍是 `PS.volatile_facts_digest()` 的现算值（不手抄）。
    {"version": "p211", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p211（2026-10-26 K1 收口）：本批只动段文本与工具说明，facts 落点一格没动 ⇒ count / keys_sha256 与上一格同值（仍是 PS.volatile_facts_digest() 的现算值，不手抄）。动的是四处正文与一批摘要：① conductor.post_task 的 summary 末句不再点名 conductor.summon（D 面上没有那件工具，判据 G1/G2）；② specs/m.py 的 policy 补回判据要的「只做数值实验不算完成」，并把两种降级都点名；③ PAPER_PACK 第五节去掉「八格」两边的强调标记（判据要 `收工门八格全过`）、第一节把「要改就改」改成「可改、该改」、(七) 第一条补上 `.tex` 那一格真实存在的 `kind=unsupported_format` 读数；④ 30 件工具 summary 按「只压冗余表述、不删语义」重压，压缩批次从 7109（82.37%）落到 6452 字符 = 基线的 74.75%（门槛 75%）。逐件理由见 agent_prompts.PROMPT_VERSION 上方 p211 那一格。"},
    {"version": "p212", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p212（2026-10-27 收尾）：两笔文字口径 —— ① `conductor.closing` 的 summary 补回「收工门（八格）」这一句（判据要点名格数，改写法要同步改本条，不许让它静默变真空）；② PAPER_PACK 的两处实话（摄取那条写明 `kind=unsupported_format`；`source/` 那条改成「可改、该改的是」。）。facts 键集仍 15 格、键名一格未动。"},
    # p212 → p213（2026-10-27 收尾 / L1 巡查）：只动 M 自己的段（policy 多一条 100 字 +
    # 工具面多三件），`STEP_VOLATILE_FACTS` 那 15 格一格没挪、键名一个没换 ⇒ `count` /
    # `keys_sha256` 与上一格同值，仍是 `PS.volatile_facts_digest()` 的现算值（不手抄）。
    {"version": "p213", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p213（2026-10-27 收尾 / L1 巡查）：两笔都落在 M 自己的段上 —— ① specs/m.py 的 policy 多一条轮查规范动作（99 字：到点跑 conductor.patrol 拿全 → 逐个给 conductor.patrol_verdict（过/指导）→ 结完再干别的 → 挂机等时才挂下一个 20 分钟轮查计时器），同处再一条点名 conductor.review_child（要细看某一个时给它绝对编码）；② M 的工具面多三件（conductor.patrol / conductor.review_child / conductor.patrol_verdict，roles 都是 M）⇒ 十一格摘要只有 M 那一格换值。facts 键集仍 15 格、键名一格未动，count / keys_sha256 与上一格同值。计时器与「到点返回 SOP」那一半归 L2，本批不动 clock.py / clock_tools.py / agent_loop.py 的挂机侧。另记一笔已知待办：tests/fixtures/prompt_cache_warm.json 没有重落（重落要花模型钱、业主没批）⇒ 缓存因此 stale。"},
    # p213 → p214（2026-10-27，`R-BE4` 的 D1 Phase A）：只动 D 的工具面（多一件
    # `conjecture.register_conjecture`），`STEP_VOLATILE_FACTS` 那 15 格一格没挪、
    # 键名一个没换 ⇒ `count` / `keys_sha256` 与上一格同值，仍是
    # `PS.volatile_facts_digest()` 的现算值（不手抄）。
    {"version": "p214", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p214（2026-10-27，R-BE4 的 D1 Phase A，业主批准）：把 D 的主力动作接进唯一的注册表 —— tools/__init__.py 的 _MODULES 加 conjecture_tools ⇒ conjecture.register_conjecture 由 build_registry 装配（它的 roles=(D,) ⇒ 十一格里只有 D 的 tools_lines 多一行，其余十格逐字未动，读数见 temp/rbe4_prompt_digests.py）。连带三处登记退场（capabilities 的 _TOOL_MODULE_EXTRAS / _KNOWN_UNMATCHED_ACTIONS / ACTION_ONLY_PARAMS），tool_surface_snapshot.json 的 summary.count 117 → 118（人重冻）。facts 键集仍 15 格、键名一格未动，count / keys_sha256 与上一格同值。已知待办同上一格：prompt_cache_warm.json 没重落 ⇒ 缓存 stale。"},
    {"version": "p215", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p215（2026-10-28，D-06）：提示词示例把名册名写成像编码的 D1/D3 会被当成职责编码，改成 probe-a-1 这种标签，并明写 name 不是职责编码；键集自 p213 起未变（15）"},
    # p215 → p216（2026-10-28，阶段 ③ 2B）：只动 A 的工具面（多一件
    # `search.retry_pending`），`STEP_VOLATILE_FACTS` 那 15 格一格没挪、键名一个没换
    # ⇒ `count` / `keys_sha256` 与上一格同值，仍是 `PS.volatile_facts_digest()`
    # 的现算值（不手抄）。这一格存在的理由不是"键集变了"，而是账本的口径：
    # 版本抬了就记一格 —— 否则"哪一版改了工具面"在盘上没有读数。
    {"version": "p216", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p216（2026-10-28，阶段 ③ 2B）：新增 search.retry_pending（roles 只有 A）⇒ A 的工具面多一行，十一格摘要只有 A 换值（temp/_recompute_digests.py 现算）。facts 键集仍 15 格、键名一格未动，count / keys_sha256 与上一格同值；本批 prompt_cache_warm.json 已重落（业主给了 --cap-usd 0.1 的两条命令），不留 stale 待办"},
    # p216 → p217（2026-10-28，阶段 ③ 2C）：动的是 A 自己的 policy 两段（主动性口径 +
    # broad 的 topic_selfcheck 口径），不是 facts 那一族 —— `STEP_VOLATILE_FACTS` 那 15 格
    # 一格没挪、键名一个没换 ⇒ `count` / `keys_sha256` 与上一格同值，仍是
    # `PS.volatile_facts_digest()` 的现算值（不手抄）。
    {"version": "p217", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p217（2026-10-28，阶段 ③ 2C）：specs/a.py 的 policy 追两段 —— ① 取不到全文 ≠ 这篇不存在（429 等冷却 / 404 换 landing / 400 换 PDF 路由；取不到如实登记；批量再取走 search.retry_pending）② broad 的 topic_selfcheck：off_topic 别花判官调用、unknown 是判不了。机器侧落点 providers.mark_topic_selfcheck（只标不删）+ search.literature 的 candidates[].topic_selfcheck。facts 键集仍 15 格，count / keys_sha256 与上一格同值；prompt_cache_warm.json 本批已重落"},
    # p217 → p218（2026-10-29，V 签门槛）：动的是 V 那一侧（提示词新段 + 手册 + 签名权转交秘书），
    # 以及 M 的工具面多一件 conductor.wake_blocked。`STEP_VOLATILE_FACTS` 那 15 格一格没挪、
    # 键名一个没换 ⇒ `count` / `keys_sha256` 与上一格同值，仍是 `PS.volatile_facts_digest()`
    # 的现算值（不手抄）。这一格存在的理由同上格：版本抬了就记一格，否则"哪一版动了 V 的职责文"
    # 在盘上没有读数。
    {"version": "p218", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p218（2026-10-29）：V 只产审稿意见、签由秘书判定并落盘；M 的编排面多 conductor.wake_blocked（逐条审批唤醒）。"},
    # p218 → p219（2026-10-29 业主批准）：specs/v.py 三句改成"签由秘书"、specs/d.py 与 m.py 的
    # 静默定义按定稿重写；facts 那 15 格一格没挪 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p219", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p219（2026-10-29）：V 的职责文与 D/M 的静默定义改成定稿口径（V 只产意见、签由秘书；静默 = 只挂兜底计时器）。"},
    # p219 → p220（2026-10-30，业主批准动禁改区 · FC-27）：V 的结论收成两态
    # （「不应该有『看不出来』，『看不出来错』就是没毛病」）—— 换的是段正文（V 的
    # policy / 手册 / 技能索引摘要 + `verify.verify_proof` 的动作描述），一格事实的
    # 落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    # 日期更正（2026-10-30，H 那一笔）：这一格原写 2026-11-01 —— 那是一个还没到的
    # 日期（抬这一格的 commit 是 89e784a2，落盘 2026-10-30 22:36；后一格 p221 记的
    # 也是 2026-10-30）。账注里的日子是审计读的一格，不是随手写的标签：写一个未来的
    # 日期会让「哪一版在哪天落地」这条读数自相矛盾，所以统一成 2026-10-30。
    # 只改账注文字：count / keys_sha256 一个字没动（facts 键集仍是那 15 格）。
    {"version": "p220", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p220（2026-10-30 · 业主批准）：V 的结论收成两态（成立 / 有毛病），『看不出错』就是成立、不存在『看不出来』这一档；历史台账行里那一格只作兼容读。facts 键集仍 15 格（键名与条数一格未动）"},
    # p220 → p221（2026-10-30，业主批准动禁改区 · FC-27）：F 读 V 的结论收成两态
    # （`specs/f.py` 的 policy 那一条）—— 换的是段正文，一格事实的落点都没挪 ⇒
    # count / keys_sha256 与上一格同值（现算值，不手抄）。这一格存在的理由同上几格：
    # 版本抬了就记一格，否则"哪一版改了 F 的读法"在盘上没有读数。
    {"version": "p221", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p221（2026-10-30 · 业主批准动禁改区）：F 读 V 的结论收成两态 —— V 只会退回成立（没找到缺陷）/ 有毛病（找到缺陷，指到步号与原句）；读到有毛病就按那条缺陷改稿/补步骤、读到成立就是这一格被审过、不再重交；历史台账行里的那个值只作兼容读、按成立读。facts 键集仍 15 格（键名与条数一格未动）"},
    # p221 → p222（2026-10-30，业主批准动禁改区 · FC-27）：H 的工具面多一件只读工具
    # `review.scan_text_integrity`（业主「需要保证后续写论文不出现异常字符，给 H 加个
    # 工具审」）—— 这一笔一个字都没改手写段文，变的是派生态（H 的 `tools_lines` 多一行）；
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    # 为什么"改的是派生态"也要记一格：`facts_migration_problem` 只认"最后一格的 version
    # 等于 PROMPT_VERSION"，而版本抬了就必须有人在这里认一次账 —— 否则"哪一版多了一件
    # 工具"在盘上没有读数（与 p220 / p221 那两格同一条纪律）。
    {"version": "p222", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p222（2026-10-30 · 业主批准动禁改区）：H 的工具面多一件只读工具 review.scan_text_integrity（CJK / 控制符 / 零宽 / 替换符 / 双向 / 不换行空格六档，只报不写）—— 只落在派生态（H 的 tools_lines 多一行），手写段文一格未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p222 → p223（2026-11-02，业主批准动禁改区 · FC-27）：D / M 的 policy 把
    # 「顺延发号」改成「按序号发下一个未用名」—— 换的是段正文（事实不变、
    # 只统一词面），一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，
    # 不手抄）。这一格存在的理由同 p220–p222：版本抬了就记一格，否则"哪一版改了
    # D / M 的哪一句"在盘上没有读数。
    {"version": "p223", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p223（2026-11-02 · 业主批准动禁改区）：D / M 的 policy 把「顺延发号」改成「按序号发下一个未用名」（事实不变、只统一词面：已废的『撞名 ⇒ 改用顺延名继续登记』删了，仍为真的那句话不再与它共用词面）。只落在 D / M 两段正文，facts 键集仍 15 格（键名与条数一格未动）"},
    # p223 -> p224（2026-11-03，业主批准动禁改区 · FC-27）：M 的交付说明那一段把
    # 「别只看那句 `can_close`」改写成三个名字的分工（`m_says_done` 是 M 的判断 /
    # `can_close` 是机器口径 / `can_close=null` 不是通过），并把 `can_close=true` 的
    # 历史读数改成 `m_says_done=true`。一格事实的落点都没挪 ⇒ count / keys_sha256 与
    # 上一格同值（现算值，不手抄）。这一格存在的理由同 p220-p223：版本抬了就记一格。
    {"version": "p224", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p224（2026-11-03 · 业主批准动禁改区）：`can_close` 拆成两个名字 —— `m_says_done` 是 M 的判断，`can_close` 是机器口径（bool | None，None = 没接线/算不出来，不许读成通过）；M 的交付说明那一段随之改写（三个名字的分工）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p224 -> p225（2026-11-03，业主批准动禁改区 · FC-27）：收工那格改名
    # `child_count` -> `children_unretired`（153-U-13 的另一半）—— M 的名册视图那一段
    # 逐字引着这个键名，所以提示词变了。一格事实的落点都没挪 ⇒ count / keys_sha256
    # 与上一格同值（现算值，不手抄）。
    {"version": "p225", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p225（2026-11-03 · 业主批准动禁改区）：收工读数那格从 child_count 改名 children_unretired（它数的是名册里未销号的子，不是台账子数；台账那一格是网页名册面的 children_in_ledger）。M 的名册视图那一段跟着改，facts 键集仍 15 格（键名与条数一格未动）"},
    # p225 -> p226（2026-11-03，业主批准动禁改区 · FC-27）：`conductor.closing` 的
    # summary 压缩（269→234 字符）—— 那一句进 M 的 `tools_lines`，所以 M 的提示词变了。
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p226", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p226（2026-11-03 · 业主批准动禁改区）：conductor.closing 的 summary 压缩（269→234 字符），保留 m_says_done / can_close / closable 的分工与 can_close=None 不是通过；这一句进 M 的 tools_lines，facts 键集仍 15 格（键名与条数一格未动）"},
    # p226 -> p227（2026-11-01，业主批准动禁改区 · FC-27；`draft/160` 三-4 的丁案）：
    # 循环协议第 2 条（summon 那一形）补三句名册口径 —— 撞名被拒但真跑过的号，收口兜底
    # 会补一个从未用过的新名字（名册行留 requested_name / refusal_code）；没跑过的号
    # 永远不会拿到名字。它是共用段 ⇒ 十一格全换。一格事实的落点都没挪 ⇒ count /
    # keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p227", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p227（2026-11-03 落账；业主 2026-11-01 裁定）：循环协议（summon 那一形）的名册口径改成「没跑过的号不许补名」—— 撞名被拒绝的是那一笔名册登记，但真跑完之后收口兜底会补一个从未用过的新名字（名册行留 requested_name / refusal_code 说明它当初想叫什么、为什么没落），没跑过的号（并发 / 深度 / 扇出这类闸拒掉的）永远不会拿到名字。换的是共用段 ⇒ 十一格提示词全换；facts 键集仍 15 格（键名与条数一格未动）"},
    # p227 -> p228（2026-11-01，业主批准动禁改区 · FC-27；「将 H 的所有机械扫描工具
    # 统一成一个方便 H 使用」）：H 的工具面多一件只读工具 `review.scan`（统一入口，
    # 七类 kinds），它的 summary 进 H 的 `tools_lines` 那一行 ⇒ 十一格里只有 H 换值。
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p228", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p228（2026-11-03 落账；业主 2026-11-01 裁定「将 H 的所有机械扫描工具统一成一个方便 H 使用」）：H 的工具面多一件只读工具 review.scan（统一入口，kinds 七类：text_integrity / cites / inputs / refs / proofs / duplicates / ledger_match）—— 只落在派生态（H 的 tools_lines 多一行），手写段文一格未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p228 -> p229（2026-11-01，业主批准动禁改区 · FC-27）：块 3 改手写段文 ——
    # `specs/h.py` 的审稿清单四条改成"机器读数走 review.scan"（并写清②③没有机器读数）
    # + 新增一条「机械读数走一个入口」（含"这些读数不进 finding 台账"）
    # + `agent_skills._h_skills()` 新增 H 手册（索引行进前置提示词）⇒ 只有 H 那一格换值。
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p229", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p229（2026-11-03 落账；业主 2026-11-01 裁定）：块 3 把 H 的审稿清单改成用 review.scan 取读数（七类一个入口；proof 环境数与台账定理类数的等号不再当判据，改看 statement_surplus），并写清「这些读数不进 finding 台账、要留凭据用 review.report」；另加一份 H 手册。只有 H 那一格换值，facts 键集仍 15 格"},
    # p229 -> p230（两笔文案收口，内容 2026-11-01 定稿；账注日子与上一格同日，
    # 见 `test_no_ledger_note_is_dated_after_the_current_version` 的上界口径 ——
    # 账本里 p223–p229 已记到 2026-11-03，这一格不许写一个更早的日子）：
    # ① 压缩批次回涨那一格压回去（`table.update` 177 → 126，另 `table.get` /
    #    `text.extract` / `conductor.summon_many` 各压一处；85 件总量 6612 → 6468 =
    #    基线 8631 的 74.95%，改前 76.61%）；② B 的说明面不再点名 `proofauthors.py`
    #    （改成「由模块 `proofauthors` 按来源路径推断」）。变化格 = 十一格全换
    #    （`table.update` 只进七格，但同批压的 `table.get` / `text.extract` /
    #    `conductor.summon_many` 也在其余角色的工具面上）。
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p230", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p230（2026-11-03 落账，与上一格同日；两笔文案收口在 2026-11-01 定稿）：① 压缩批次回涨到 76.61% 那一格压回 74.95%（table.update 177→126，table.get / text.extract / conductor.summon_many 各压一处；85 件总量 6612→6468，基线 8631，分母与名单一格未动）；② B 的说明面把 `proofauthors.py` 改成「由模块 proofauthors 按来源路径推断」（提示词不许点名不存在的点号工具名）。变化格 = 十一格全换（三条压缩的 summary 分布在多个角色的工具面上）；facts 键集仍 15 格（键名与条数一格未动）"},
    # p230 → p231（2026-11-02，业主裁定「重点是要F侧拿V签」+「F不是直接能派V吗」+
    # 「V签先放F的手稿里让B录入」）。
    {"version": "p231", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p231（2026-11-03，账本上界口径：本账 p224–p230 记的都是 2026-11-03，而业主这一笔裁定的日子是 2026-11-02 —— 两个日子并列写在这里，别让 `test_no_ledger_note_is_dated_after_the_current_version` 的上界悬空）：① F 的 policy 改成「由你派 V」+ `proof_manuscript` 未在册入口 + `v_sign` 四档（没签不算交差）；② V 的 `verify.verify_proof` 参数面：`statement_id` 不再根级必填、新增可选 `proof_manuscript` —— 这一笔落在动作表上，D / G / M 的伙伴动作段与 V 自己的工具目录跟着换值；③ 变化格 = D / F / G / M / V，其余六格逐字未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p231 → p232（2026-11-02 业主的责任路由：在册缺签找 B / F 产出无签让 F 先拿签）。
    {"version": "p232", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p232（2026-11-03）：① M 的 policy 把「F 产出的证明天生带 V 的签字，缺签就派 D 让 F 补签」与「要 V 的签就经 B 走 M→B→V 两跳」换成业主 2026-11-02 的责任路由：命题在册缺签 ⇒ 让 B 处理（重送 / 补证 / 明确放弃），F 产出无签 ⇒ 经 D 让 F 先拿 V 签；并按同日收口写明 M 没有 V 签的编辑权与获取义务；② B 的 policy 新增「收到没有 V 签的 F 证明 ⇒ 不润色、整笔退回，请 F 先拿 V 签」，并把「册上已有而缺签」分出来（B 自己处理）；③ 变化格 = B / M 两格，其余九格逐字未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p232 → p233（2026-11-03，179 §二之三的逐条交差口径）。
    {"version": "p233", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p233（2026-11-03）：① F 的 `attack.step` / `attack.status` 的 `returns=` 补齐实现的真返回（只加不减：step 多 delivery / delivered / 逐条计数 / unfinished / trail / legal_exits / 覆盖率四格 / self_assessment / delivery_state_plan / delivery_label_plan 共 27 格；status 多 delivery）—— 机器可读的 ToolSpec 声明在 tools/attack_tools.py 同步；② F 的 policy 把「交没交差只看 v_sign / delivered 只有已签时为真」改成 179 的逐条口径（delivery 逐条读、delivered = 有成果且全部成果已签、没成果是合法收工理由）；③ agent_skills 的 F 手册把「实际送审是 F.step 的一步」改成「F 自己派 V 审这一份手稿」（正文只落盘、索引行未动）。变化格 = F 一格，其余十格逐字未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p233 → p234（2026-11-03，业主：「E 在数值证明拿 V 签的时候流程和 F 一模一样，
    # 若未实现请先实现」）：`agent_skills._e_skills()` 多一条「穷举证明-拿签与上报收养」
    # （手稿 → 派 V 三转 → 收方落签 → 上报 D），并把「反例优先」第 5 步里
    # 「让 B.register_statement 登记」改成「交 D（由 D 派 B 登记）」—— 后者与 policy
    # 第 ⑤ 条「不要自己去找 B 的 register_statement」原本是矛盾的。
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p234", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p234（2026-11-03，业主「E 在数值证明拿 V 签的时候流程和 F 一模一样」）：agent_skills 的 E 手册多一条「穷举证明-拿签与上报收养」（手稿 reports/e-proof-<实验号>.md → 派 V 三转 → 收方落签 → 上报 D 收养），并把「反例优先」第 5 步那句「让 B.register_statement 登记」改成「交 D（由 D 派 B 登记）」（与 specs/e.py 的 policy ⑤ 原本矛盾）。变化格 = E 一格，其余十格逐字未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p234 → p235（2026-11-04，收口批）：十一格全换 —— p234 冻结之后提示词 / 工具面一侧
    # 落了 42 笔（子任务被拒格改名 subtask_refusals、doc.mapping_cells 等）。
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p235", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p235（2026-11-04 收口批）：p234 冻结之后提示词 / 工具面一侧落了 42 笔 —— 八份 spec 的「子任务被拒」格改名 subtask_refusals（十一条都有监控下级那一条 ⇒ 十一格全换）、新只读工具 doc.mapping_cells（只进 G 面）、A/B/E/F/G/H/L/M/V 各自的 policy / returns 收口、PAPER_PACK 的 blocker 两类读法。facts 键集仍 15 格（键名与条数一格未动）"},
    # p235 → p236（2026-11-04，6fb014f5 三条已知缝隙）：只有 G / H 两格换值。
    {"version": "p236", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p236（2026-11-04，6fb014f5 三条已知缝隙）：凭据格 lean_file / lean_target 在通道为空时从「可留空」改成「必须留空」（填了受控拒绝），numeric_evidence / exhaustion_note 空通道也不许填；doc.write_mapping 的 lean_state 不再把「关档 / 有产物」当凭据格判据。变化格 = G / H 两格，其余九格逐字未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p236 → p237（2026-11-04，两笔合并抬）：只有 B / G 两格换值，都是文案与判据对齐。
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p237", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p237（2026-11-04，业主批「必要的提示词改动不许静默不改」）：① specs/b.py 的 policy 把「派 V 审手稿（framework_summon 的 verify.verify_proof）」改成 V.verify_proof（B 的工具面上没有那件工具，原文教了做不到的事）；② specs/g.py 的 LEAN_FILE_ROW 把「② formal（形式化）」改成「② formal（形式化，由 L 交出那份 .lean 与声明名）」（受 Lean 开关控制的提示词一律指向 L）。变化格 = B / G 两格，其余九格逐字未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p237 → p238（2026-11-04，`0ed46fb3` 的收口）：只有 G 一格换值 —— 同一行两处措辞，
    # 只改模型可见文本、不改凭据要求，也不挪任何一格事实的落点。
    {"version": "p238", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p238（2026-11-04，0ed46fb3 的收口）：specs/g.py 的 LEAN_FILE_ROW 两处措辞 —— ① numeric 那一半的「数值程序没有 Lean 声明名」改成「没有声明名可填」；② formal 那一半去掉「由 L 交出那份 .lean 与声明名」、只留「formal（形式化）」（这一行同时落在 test_lean_file_is_taught_by_channel / test_l_collab_surface_is_respected_everywhere / test_lean_switch_points_at_l 三把尺子的射程里，唯一同时成立的出口是不提 L、且「形式化」前后 60 字里不放 Lean 族记号）；凭据格该填什么一个字没动。变化格 = G 一格，其余十格逐字未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p238 → p239（2026-11-04，今晚五条 lane 的提示词 / 工具面一次对齐）：十一格全换 ——
    # 共用段 HANDOFF_PROTOCOL 首提改名（347d6267）命中每一格；B / F / G / H / M / V 另有
    # 自己的改动（4e43a81b / 3bb87297 / 7970eacc / b2f39f05）；收口时 verify_proof 的
    # summary 按压缩预算压回 104 字符（aa4231cb）⇒ V 那一格再换一次。一格事实的落点都
    # 没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p239", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p239（2026-11-04，今晚五条 lane 的提示词 / 工具面一次对齐）：变化格 = 全部十一格 —— 共用段 HANDOFF_PROTOCOL 的首提从「交接手稿（交接工作前的标准动作…）」改成「交接手稿（handoff；交接工作前的标准动作…）」（347d6267 的命名裁定），B / F / G / H / M / V 另有各自改动（证明正文的载体改成手稿、G 的 ⓪ 步、V 的在册只经手稿过审 等），收口时 verify_proof 的 summary 又按压缩预算压回 104 字符（aa4231cb，V 那一格再换一次）。facts 键集仍 15 格（键名与条数一格未动，一格事实的落点都没挪）"},
    # p239 → p240（2026-11-04，今晚最后一次冻结：p239 之后三条 lane 的模型可见文本
    # 一次对齐）：变化格 = ['B', 'M'] —— B 是 policy 补回「派 V 审核签字」锚词 + 动作摘要
    # 与参数说明的「证明正文的载体」位置 / 强调（5f29ec24 / 646adcb5）；M 是交接首提改成
    # 「交接工作前先写一份手稿（交接手稿，handoff）」（8d80a398）。V 那一格这次没有换值
    # （p239 的 4daa02d9 仍成立）：6efb3079 改的是 verify.verify_proof 的 returns，而
    # `tools_lines` 只渲染「名字 + 摘要 + 必填参数 + 副作用」，returns 只进声明快照
    # （不进 function-calling 的 description，见 `tools/base.py:674-679`）⇒ 它不进任何
    # 角色的段（p239 提交信息里「V 的摘要会 stale」是预期落空，实测为准）。一格事实的
    # 落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p240", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p240（2026-11-04，今晚最后一次冻结）：变化格 = B / M 两格，其余九格逐字未动。B：policy 把「再派 V 审这一份稿」写回裁定原话「再派 V 审核签字（`V.verify_proof`：`statement_id` + `proof_manuscript=<这份稿>`）」；`register_statement` 的动作摘要把「（证明稿，proof manuscript）」移到「是证明正文的载体」之后、参数说明给这一句加 `**` 强调（5f29ec24 / 646adcb5）。M：policy 首提改成「交接工作前先写一份手稿（交接手稿，handoff）」，旧判据针重新连通（8d80a398）。V 未变：6efb3079 给 verify.verify_proof 的 returns 补了两态词，但 returns 不进 tools_lines、也不进 function-calling 的 description（只进声明快照，见 `tools/base.py:674-679`）⇒ V 的提示词一个字没变，那一笔的模型可见落点在工具面 golden。facts 键集仍 15 格（键名与条数一格未动）"},
    # p240 → p241（2026-11-04，今晚最后一次冻结：p240 之后 D 的可见面一次对齐）：
    # 变化格 = ['D'] —— `specs/d.py` 的 policy 新增「想法 / 落稿与拿签 / 产物」三句并把研究
    # 手稿落点改回 `reports/RESEARCH.md` 七节（035b7365），`agent_skills.py` 的 D 手册新增
    # 「想法 → 派 F → 读回 → 新想法」循环、技能索引那一行的 summary 随之改写。一格事实的
    # 落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p241", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p241（2026-11-04，今晚最后一次冻结）：变化格 = D 一格，其余十格逐字未动。D：`specs/d.py` 的 policy 新增一条三句（业主 2026-11-04 逐字裁定：D 可给证明思路与依赖面参考，最终落稿拿签必须派 F；D 的产物 = 想法 + 收获 + 新想法），同一格的研究手稿落点从「reports/RESEARCH.md 是框架保留面」改回既有七节形式（七节、先读后改、收录 F/E 成果，自写 `## 证明` 节受控拒）；`agent_skills.py` 的 D 手册新增「想法 → 派 F → 读回 → 新想法」循环，技能索引那一行的 summary 随之改写（索引行印在 D 的段上）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p241 → p242（2026-11-05 今晚最后一次冻结）：变化格 = 十一格全变。五笔：① `conductor.post_task`
    # 的 summary 补「有出边就走派活那一形、没有出边时把这件事写进交回结论」（88a203c7），Universal
    # 工具 ⇒ 十一格；② `conductor.escalate` 的 side_effect read → write_local（8aa92286）⇒
    # tools_lines 那行换值（十一格）+「手 / 眼睛」两行件数变；③ 压缩批 510280a3（fs.write / fs.edit /
    # search.download / verify.run_experiment 四条 summary 换文案）；④ table.list 的 `fields` /
    # table.search 的 `select`（068cc9d9）进 tools_lines 的「可选」段；⑤ 角色自己的段（C 的唤起骨架
    # 与手段行、D 的入边去 F、F 的「交给 E 去验」与三句新教法、V 的出边清空 + 只读边界那一族）。
    # 一格事实的落点都没挪 ⇒ count / keys_sha256 与上一格同值（现算值，不手抄）。
    {"version": "p242", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p242（2026-11-05，今晚最后一次冻结）：变化格 = 全部十一格。① `conductor.post_task`（Universal）summary 补「要让别人办一件事，有出边就走派活那一形（`summon`）；没有出边时把这件事写进交回结论」（88a203c7）⇒ tools_lines 对每个角色都渲染；② `conductor.escalate` 的 side_effect `read → write_local`（8aa92286，业主裁定「乙」）⇒ 那行换值 + 「手 / 眼睛」两行件数变；③ 压缩批 510280a3：fs.write / fs.edit / search.download / verify.run_experiment 的 summary 换文案（D 的正文口径句 138→103、fs.edit 不再复制、两句细则挪进 params description），压缩批次 78.86% → 74.60%；④ `table.list.fields` / `table.search.select`（068cc9d9）进「可选 ?…」段；⑤ C 的唤起骨架与手段行（88a203c7）、D 的入边表去 F（50c4a1d2）、F 的「交给 E 去验」与三句新教法（50c4a1d2 / 08b7d2c3 / 05067047 / b26cd7e4）、V 的出边清空 + `verify.verify_proof` 变 write_local + 只读边界那一族（911b9e1f / db83d025 / 100a9074 / 327b617f）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p242 → p243（2026-11-06 等级是唯一的轴 · 提示词/技能/规范文本一次对齐）：只改模型可见
    # 文本（specs 的 policy / 参数说明、agent_prompts 的共用段与 PAPER_PACK、agent_skills 手册、
    # agent_e/_support 的列表句），一格事实都没挪 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p243", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p243（2026-11-06，等级是唯一的轴）：变化格 = 全部十一格（共用段 `STRUCTURE_NOT_PROMPT` 与各角色自己的 policy / 动作说明都改了）。口径：`conjecture` < `strong_conjecture` < `pre_theorem` < `theorem`；可引门槛 = `pre_theorem`；穷举与 Lean 同级都到 `theorem`；`evidence_kind` 只是历史列（由等级反算，判定面不读）；V 不假定有号（没号先落 `verifications/pending/<正文 sha>.jsonl`，B 登记后按正文 sha 认领，三票齐）。判据：`tests/test_agent_prompts.py` 的十一格 + `test_the_prompt_version_moves_with_the_sections`。facts 键集仍 15 格（键名与条数一格未动）"},
    # p243 → p244（2026-11-06 把 V 的判词语义写死：「成立」= 零 finding）：只改模型可见文本
    # （`specs/v.py` 的 policy / deliverable / local_notes、`agent_skills._v_skills()`、
    # `verifications.cold_start_prompt`、`agent_prompts.FACULTY_LOCAL`），一格事实都没挪
    # ⇒ count / keys_sha256 与上一格同值。变化格 B / E / F / M / V（后四者是 V 的 deliverable
    # 进伙伴表那一行，不是它们自己的正文动了）。
    {"version": "p244", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p244（2026-11-06，V 的判词写死）：「成立」= 零 finding —— `findings` 必须为空；只要有一处要改的（含 `level=info` 的措辞建议）⇒ `有毛病` + `defect_step`；`有毛病` 必须给 `defect_step`。why：秘书那一侧按「拿不准、说不清、只挑出一处小记号问题 ⇒ 也算有毛病」判，若 V 继续「成立 + 一条 info」两边题面打架、这条链永远签不出来。变化格 = B / E / F / M / V（V 是自己那一格；B/E/F/M 是 V 的 deliverable 进伙伴表「它交付：」那一行）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p244 → p245（2026-11-06 把 V 那一侧题面的四处口径对齐到秘书那一侧）：只改题面 / 文案
    # 与那几处注释（`verifications.cold_start_prompt` / `agent_skills` 的两份 V 手册 /
    # `specs/v.py` 的 policy），判定代码的机制一个字没动，一格事实也没挪
    # ⇒ count / keys_sha256 与上一格同值。变化格只有 V 一格（没有动 V 的 deliverable，
    # 所以伙伴表那几格不跟）。
    {"version": "p245", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p245（2026-11-06，V 题面四处口径对齐秘书）：四处都是「V 那侧说成立 / 秘书那侧判有毛病」同一个病 —— ① 只写「整体框架没问题 / 思路上没问题」而不带核对记录 ⇒ 判 `有毛病`（没逐行验证，把「核到哪一步、从哪一步起没核」写进 findings + defect_step）；② 依据落在不归 F 的几样（文献真伪/页码/实验数值复现/排版术语）⇒ 也不是成立，判 `有毛病` 并把「理由面错位」写进 findings / defect_step（写 why 不算数）；③ 写「判不了 / 我无法判断」⇒ 没做完审，那一条按 `有毛病` 收并写清卡在哪一步（框架读侧折档保留但只算兜底，不再是 V 的合格答案）；④ 引用核实 `unknown` ⇒ 判「没查成」（不是「没问题」），保持不签发、理由写「引用核不了」。变化格 = V 一格（其余十格逐字未动）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p245 → p247（2026-11-06 第三次收紧：V 的判词只是陈述、轴只由秘书给）：只改题面 /
    # 文案与判定链（`verifications` 去折档、`agent_v.core` 去字面快路、`secretary` 定步号），
    # 一格事实都没挪 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p247", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p247（2026-11-06，第三次收紧：V 的判词只是陈述）：业主逐字「① 结论只有两态；② 不做折档：不许按词面把判不了 / 看不出来 / 拿不准 / 我无法判断折成任何一态；③ V 的判词只是陈述，每一转的轴（clean / fault）一律由 V 秘书做语义分析后给出 + 写清依据；streak / 签发只看秘书给出的轴；判 fault 而 V 没给 defect_step ⇒ 秘书定出那一步」。`parse_verdict` 只做结构解析（不折档、不产轴）；`row_signable` / `_hold_run_lengths` / 签发只看 `secretary_axis`；`agent_v.core` 删掉 `read_verdict != 成立` 的字面快路；秘书题面把「V 的判不了」与「秘书的判不了」分开。变化格 = V 一格（policy 改写；其余十格逐字未动）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p247 → p248（2026-11-06 把「轴 / 发签」两句话的未在册例外补齐）：只改题面 /
    # 文案与两页文档，一格事实都没挪 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p248", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p248（2026-11-06，把「轴 / 发签」的未在册例外补齐）：口径 = 在册档发签由 V 的秘书判定并落盘；未在册档签信封由 V 颁发、收方秘书只落块；轴在在册档与未在册散文支由秘书语义判定，穷举支由机械会审给（`source=exhaustion_report`，不经秘书）。三笔进模型可见面：`agent_skills` 的 V 手册正文（②）、`verifications.cold_start_prompt` 的发签句（④）、`specs/v.py` 的 policy（⑤，唯一换摘要的一格 —— V 30585→30649 字符，`7fb8adfa…`→`5a071356…`；其余十格逐字未动）。另两笔是 A 类、不进提示词也不抬版本：`docs/ROLE-SPECS.md` V.1 与 `agent_v/core.py` 模块 docstring。facts 键集仍 15 格（键名与条数一格未动）"},
    # p248 → p249（2026-11-06「签 / 秘书」这一类口径的最后一次收拾）：只改题面 / 文案与
    # 冻结读数，一格事实都没挪 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p249", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p249（2026-11-06，「签 / 秘书」这一类口径的最后一次收拾）：口径 = 在册档的发签由 V 的秘书判（`decide_sign_issuance`）、写盘由框架侧（`sign_statement` → `_vsigns_write_after_flip` → `vsigns.issue`）；未在册档不经秘书判、由 V 颁发签信封（`vsigns.issue`），收方秘书只落手稿签块（`vsigns.land`）——「判定」与「写盘」在任何一句话里都分开说。五笔进模型可见面：`verifications.cold_start_prompt` 的两类 proof ②条与会审末句、`specs/v.py` 的 `boundary` / `duty` / policy 那一句、`agent_skills` 的 V 技能索引（slug 更名 `…-签分两档` + title + summary）与手册正文第二节。变化格 = V + B/E/F/M（后四格只差伙伴表里 V 的 `duty` 那一行；V 30649→30755 字符，`5a071356…`→`c4a83154…`）。另两笔是 A 类、不进提示词也不抬版本：`verifications.py` 的 S5 注释与 `agent_v/core.py` 模块 docstring（11/11 SAME）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p249 → p250（2026-11-06「过时更正 / 缺补齐 / 压缩」三段）：只改题面 / 文案与两页文档，
    # 一格事实都没挪 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p250", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p250（2026-11-06，六份只读审计报告逐条落地的三段）：① 过时更正（撤销口径 5 处；"
             "`open_count` / `retire_integrity.open_items` / `review_standing` 三个格名；B 的签发轴与打回短接；"
             "F 的 `signs_bit3` 与 `secretary_fault`；cold_start 的等级口径与可观察说法；V 的 duty 人称与 "
             "`write_local` 声明；E 的无稿那一档；A 的 `returns`；SECRETARY_JUDGE_KEY 注释）；"
             "② 缺补齐（a/b/d/e/f/g 六份父 spec 各一句撤销说明、M 的 `revoke` 格与四个 open 读数、"
             "`revoked_recent`、E 手册的 exhaustion 轴来源、F 的 `review_standing=rejected`、"
             "M 的 `fault_unrepaired` / `by_class`）；③ 压缩（10 处：甲 2 / 乙 8，逐条标「谁接住」）。"
             "变化格 = A/B/D/E/F/G/H/L/M/V（C 一字未动）；工具 summary 改动 = conductor.void_items / "
             "retire_child / wake_blocked 三件，外加 void_items 的 `returns`。另两笔是 A 类、不进提示词也"
             "不抬版本：`verifications.py` 的 SECRETARY_JUDGE_KEY 注释与 `agent_skills.py` 的 M/E/F 手册正文。"
             "facts 键集仍 15 格（键名与条数一格未动）"},
    # p250 → p251（2026-11-07「修 9 条红」）：只改题面 / 判据文本，一格事实都没挪
    # ⇒ count / keys_sha256 与上一格同值。
    {"version": "p251", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p251（2026-11-07 修 9 条红）：p250 之后提示词文本又变了两轮却没抬版本 —— "
             "① 72dffab1 把共享的 `conductor.void_items` summary 里 `open_items_of` 改成 "
             "`conductor.board` 四读数（该工具在 A/B/D/E/F/G/L/M 八格面上 ⇒ 这八格已漂）；"
             "② b7a1c721 改 M 的 policy 同一句。本批在 HEAD 2a609a3b 上把 9 条红修完再一次性抬格："
             "甲 = 恢复被 d0987609 压缩掉、判据字面钉着的两句（`secretary.py` 的「两个『判不了』别混」"
             "整段 / `specs/d.py` 的「研究侧由你主导」89 字原条），并把被 b3f0b8fb 顶掉的第一条位置挪回；"
             "乙 = 三组判据按 f507b528 已改准的现状更新（V 的「按现行签**现算等级**」、E 的"
             "「不带稿 ⇒ 只给『看过、没签』/pending 不落一行」、作废板项的 `done` + `expired`），"
             "其中 `done` + `expired` 同步到 b/d/m/agent_skills 五处。"
             "变化格 = A/B/D/E/F/G/L/M（A/E/F/G/L 的上游是 72dffab1 的共享 summary；"
             "B 多一处 `done`+`expired`；D 多恢复原条并挪回第一条；M 多 b7a1c721 的读数名）。"
             "C/H/V 逐字未动。facts 键集仍 15 格（键名与条数一格未动）"},
    # p251 → p252（2026-11-07，业主两笔裁定同批）：facts 键集一格没动（还是 15 格），
    # 两笔都只改段文本 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p252", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p252（2026-11-07，业主两笔裁定同批）：甲「换号需给清理由」两档写进 "
             "`agent_skills` 的 D / F 两本手册（math_error 要指出错在第几步 + `defect_ref`；"
             "difficulty 要说清难在哪 + 把可取之处拆成引理 `salvaged`；理由不齐"
             "受控拒 `abandon_reason_missing`）；乙「命题登记时需过 F 秘书闸」写进 F 交付那一本"
             "（交稿前由 F 自己的秘书按「条件 → 结论」判一次形状，判不过或没判成 ⇒"
             " `proposition_form_refused`，不交给登记）。变化格 = A/B/D/E/F/G/L："
             "D/F 是自己的手册变了，A/B/E/G/L 是 `table.update` 那一行 summary（工具声明，"
             "新增 `abandon_kind` / `abandon_basis` / `defect_ref` / `difficulty` / `salvaged`"
             " 五格）印在这五个角色的工具面上。C/H/M/V 逐字未动。"},
    # p252 → p253（2026-11-07，让提示词与工具面第二次对齐）：facts 键集一格没动（还是 15 格），
    # 只改段文本 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p253", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p253（2026-11-07，提示词与工具面第二次对齐 + 版本冻结）：p252 把 `table.update` 的"
             " summary 改成两档放弃口径，但只改了工具声明与 D/F 的手册 —— 十一格里 A/B/D/E/F/G/L"
             " 从那一刻起就与冻结表对不上，而 D/F/M 的 policy 与 M 正文仍在教旧写法"
             "「`quote_reason=abandoned@<ISO8601>@<理由>`，三样缺一不可」。本笔把四处旧格式逐处改成"
             "两档（`math_error`：错在第几步 + `defect_ref`；`difficulty`：难在哪 + `salvaged` 引理），"
             "B 手册补上五格与「判的是你的秘书」，F 的 policy 正文补上命题形态闸"
             "（`proposition_form_refused`）。变化格 = D/F/M（本笔）＋ A/B/E/G/L（上游 4e5e85ae 的"
             " `table.update` summary，从 p252 起就漂着）；C/H/V 逐字未动。facts 键集仍 15 格。"},
    # p253 → p254（2026-11-07，A4 裁边 + 解耦落地的连带重冻）：facts 键集一格没动（还是 15 格），
    # 只改段文本 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p254", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p254（2026-11-07，A4 裁边 + 解耦落地的连带重冻）：上游是 74e243df「删 F→B、加 F→D」"
             "（`specs/f.py` 的 edges 换一格、F/D/M 的放弃理由落盘形状改成"
             " `quote_reason=abandoned@<ISO8601>@<结构化理由>`、B 手册补「F 不会直接派你；交稿来自 D 的"
             "携带单」与「来自 A 的收录请求照常办」）与本批 B 类的 `fs.write` summary（A/B 写 `reports/` 下"
             "三族证明了也拒、`notes/` 下不算框架产物）。变化格 = B/D/F/M（十一格摘要）；A/E/G/L 只动面快照里"
             "那一行 summary、不进摘要；C/H/V 逐字未动。facts 键集仍 15 格。"},
    # p254 → p255（2026-11-07，A 类压缩收口）：facts 键集一格没动（还是 15 格），
    # 只改工具说明文本 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p255", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p255（2026-11-07，A 类压缩收口）：上游是本批把压缩批次压回预算的那两句工具说明"
             "（`table.update` 的 summary 去掉与 `params` 重复的「只覆盖 patch，不改主键」，"
             "`fs.write` 的 summary 去掉重复的动词与名词）。变化格 = A/B/D/E/F/G/L（`table.update` 的"
             " `roles` 恰是这七格）；`fs.write` 那一行不进摘要（多出的 M 那格 SAME）⇒ 只动面快照；"
             "C/H/M/V 逐字未动。facts 键集仍 15 格。"},
    # p255 → p256（2026-11-07，放弃理由四档）：facts 键集一格没动（还是 15 格），
    # 只改段文本与工具说明 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p256", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p256（2026-11-07，放弃理由四档）：上游两笔 = 8774bb67（五本手册 + M 的正文 + "
             "`specs/d.py` / `specs/f.py` / `specs/m.py` 三条 policy 从「按两档之一」改成四档："
             "math_error + defect_ref / difficulty + salvaged / counterexample + experiment_id / "
             "space_too_large + space；E 手册补「写盘之前先过形态闸」）与 79698677（`table.update` 的 "
             "summary 改四档、`params` 补 `experiment_id` / `space` 两格，同一批在压缩批次内等量回填 "
             "6470/8631 = 74.9623%）。变化格 = A/B/C/D/E/F/G/H/L/M（A/B/D/E/F/G/L 的上游是 "
             "`table.update` 那一行；C/H 没有它，换值来自只读面上那三件说明的等量压缩；M 两处都动）；"
             "V 逐字未动。facts 键集仍 15 格。"},
    # p256 → p257（2026-11-07，玩具例子 `kind=example`）：facts 键集一格没动（还是 15 格），
    # 只改工具说明与 G 的一段 policy ⇒ count / keys_sha256 与上一格同值。
    {"version": "p257", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p257（2026-11-07，玩具例子 `kind=example` 只是标签）：上游三笔 = "
             "8d56c055（`secretary.PROPOSITION_KINDS` 收下 example、B 与 lemma 走同一条签后升档路 —— "
             "不进提示词）、c86e7a2a（`verify.run_experiment` 的工具面多一格 `kind`，它的 roles 是 "
             "E / F / G ⇒ 只这三格的 tools_lines 换值）、adf3402c（`specs/g.py` 的 WRITING_SCOPE 与 "
             "WRITING_SCOPE_NO_LEAN 补「玩具例子用 Example 环境」⇒ G 再换一次）。变化格 = E/F/G；"
             "A/B/C/D/H/L/M/V 逐字未动。facts 键集仍 15 格。"},
    # p257 → p258（2026-11-08，业主三条裁定：E 普通数值手稿 + B 绿色通道 + 穷举档证明栏）：
    # facts 键集一格没动（还是 15 格），只改四份 spec 的段文本 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p258", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p258（2026-11-08，业主三条裁定）：上游四份 spec 的 policy / 动作面描述 = "
             "`specs/e.py`（穷举那一条的 ② 改成「证明栏只写 ③ 穷举论证；程序住 code_path、"
             "设计住 observations」＋新增 ⑤ 普通数值手稿 `e-num-*`）、`specs/b.py`（「两族手稿"
             "读法不同」policy ＋ `origin` 描述补绿色通道的出路）、`specs/d.py`（提交强猜想引用 "
             "`e-num-*`，statements 只读）、`specs/g.py`（落库证明栏只有 ③）。变化格 = B/D/E/G；"
             "A/C/F/H/L/M/V 逐字未动（只差版本行）。facts 键集仍 15 格。"},
    # p258 → p259（2026-11-08，业主三条裁定 · 第 4 笔：D 只递指针 / D 只给研究方向 / 写集对齐 /
    # 穷举标签收紧）：facts 键集一格没动（还是 15 格），只改两份 spec 的段文本 ⇒ count /
    # keys_sha256 与上一格同值。
    {"version": "p259", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p259（2026-11-08，业主三条裁定 · 第 4 笔）：上游两份 spec = "
             "`specs/b.py`（`register_statement.required` 从 (statement_full,) 放开成 ()，"
             "`proof_manuscript` 描述广告「给工作区相对路径 + statement_full 留空 ⇒ 按手稿路径"
             "收录；D 传正文受控拒」）、`specs/d.py`（policy 三处：向 B 登记只递指针 / 立了猜想"
             "之后把研究方向交给 F 而不点名 conjecture_id / 命题台账由 B 写、D 只读，写集三张表）。"
             "变化格 = B/D；A/C/E/F/G/H/L/M/V 逐字未动（只差版本行）。facts 键集仍 15 格。"},
    # p259 → p260（2026-11-08，业主：收录按语义查一圈 + 普通数值一律 conjecture +
    # 数值证据流水）：facts 键集一格没动（还是 15 格），只改 `specs/b.py` 的 policy 段文本
    # ⇒ count / keys_sha256 与上一格同值。
    {"version": "p260", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p260（2026-11-08，业主：收录按语义查一圈 + 普通数值一律 conjecture + "
             "数值证据流水）：上游一份 spec = `specs/b.py` 的 policy 新增「收录先查『是不是在册的"
             "同一条』」（普通数值手稿永远是 conjecture；秘书按关键词检索后认定，查到就不新注册："
             "数值手稿更新数值证据流水 / 证明手稿按既有多证明分支追加 proof_no）。"
             "变化格 = B；A/C/D/E/F/G/H/L/M/V 逐字未动（只差版本行）。facts 键集仍 15 格。"},
    # p260 → p261（2026-11-08，缺陷①「只递指针」在工具层通过）：只改 `specs/b.py` 的
    # `statement_full` 参数格（去 `minLength` + description），`_surface_digest` 不含参数
    # description ⇒ 十一格 SAME；facts 键集一格没动（还是 15 格）。
    {"version": "p261", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p261（2026-11-08，缺陷①）：上游 `specs/b.py` 只去掉 "
             "`register_statement.statement_full` 的 `minLength: 1` 并改那一格的 description"
             "（让只给 `proof_manuscript` 的指针形态过参数门；空正文不能登记仍由动作层 "
             "`empty_statement_text` 拒）。`_surface_digest` 不含参数 description ⇒ 十一格 "
             "SAME（只差版本行）。facts 键集仍 15 格。"},
    # p261 → p262（2026-11-08，提示词-工具面一致性审计 ①–⑦）：facts 键集一格没动
    # （还是 15 格），只改 `specs/b.py` 的 policy 段文本与 `verify.run_experiment` 的 summary
    # ⇒ count / keys_sha256 与上一格同值。
    {"version": "p262", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p262（2026-11-08，提示词-工具面一致性审计 ①–⑦）：上游两笔 —— "
             "`specs/b.py` 的 policy 新增四条（D 只递指针时命题从 `## 命题` 读、证明从 "
             "`## 证明` 读；签的两格读数与六档；概念同一性 / 同种证明判不了 ⇒ 受控拒并给改法；"
             "短证明照样判、不按字数预判死）；`tools/verify_tools.py` 的 `verify.run_experiment` "
             "summary 换成两类 E 手稿（e-proof 穷举要 V 签 / e-num 普通数值不需 V 签），它的 "
             "roles 是 E/F/G ⇒ 这三格的 tools_lines 也跟着换。变化格 = B/E/F/G；"
             "A/C/D/H/L/M/V 逐字未动（只差版本行）。facts 键集仍 15 格。"},
    # p262 → p263（2026-11-09，两把尺统一后的声明面收口）：facts 键集一格没动
    # （还是 15 格），只改 `tools/table_tools.py` 里 `table.search` 的 summary 与两条 params
    # description ⇒ count / keys_sha256 与上一格同值。
    {"version": "p263", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p263（2026-11-09，两把尺统一后的声明面收口）：上游一笔 —— "
             "`table.search` 的 summary 从「默认全部标量字符串字段」改成真口径"
             "（statements 走内容面 label/statement_full，其余表走全部标量字符串字段），"
             "params 的 query / fields description 同步改（后者不进 _surface_digest）。"
             "这件工具的 roles 是 A–H + V + L ⇒ 那十格的 tools_lines 换值，M 逐字未动。"
             "facts 键集仍 15 格。"},
    # p263 → p264（2026-11-10，提示词 × 动作面 × 工具面一致性审计的 11 条收口）：
    # facts 键集一格没动（还是 15 格）—— 本批只改题面正文与工具声明文字，facts 的键名与
    # 条数都没变 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p264", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p264（2026-11-10，一致性审计 11 条收口）：题面侧 —— L1-1 E 的 "
             "`proof_manuscript` 改成回执格（不是入参）、L1-2 V 的签载体只认 "
             "`reports/{f,b,e}-proof-*`、L1-3 B 的指针支只收 `reports/` 规范名；"
             "L2-1 共用段 refs 补 q:/c:、L2-2 PAPER_PACK 的 citations 补 eval:、"
             "L2-3 `## 证明` 三态、L2-4 手稿族五档、L2-6 签块 identity_state 三态。"
             "声明侧 —— `conductor.status_report` side_effect read→write_local（与 "
             "review.report 同类）、`conductor.void_items` 的「系统通知」改成 D13 之后的"
             "真实落法、`table.search` summary 点名 label/statement_full、`fs.write` "
             "summary 点名 A/B 拒写的四族。压缩批次 6473→6343（73.49%）。facts 键集仍 15 格。"},
    # p264 → p265（2026-11-10，D3 批 2：缺陷类别四档 + 程序性/数学缺陷分开记）：
    # facts 键集一格没动（还是 15 格）—— 本批只改 V 的 policy 一句与两处真实入口的题面
    # （冷启动清单 / 秘书那一问），facts 的键名与条数都没变 ⇒ count / keys_sha256 与上一格同值。
    {"version": "p265", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p265（2026-11-10，D3 批 2）：上游 —— `specs/v.py` 的 policy 新增"
             "「没记录反例尝试不是缺陷（只作 report_gap 读数，不挡签）；「我没逐行验证 /"
             " 我判不了」仍是程序性」；同批的 `verifications._cold_start_review_checklist`"
             "（V 的冷启动清单）与 `secretary._judge_system(\"v_reply_defect\")`（秘书那一问）"
             "是真实入口、不进 system prompt ⇒ 十一格里只有 V 换值"
             "（9dce764f…）。facts 键集仍 15 格。"},
    # p265 → p266（2026-11-10，T1：B 的「稿 → 签 → 录入」拆成两个显式动作）：
    # facts 键集一格没动（还是 15 格）—— 本批只改 `specs/b.py` 的 policy 一段
    # （显式落稿 → 派 V → 按位置与格收录）与两个只在被派那一趟现装的 `own.*` 动作。
    {"version": "p266", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p266（2026-11-10，T1）：上游 —— `specs/b.py` 的 policy 把"
             "「改写之后先拿签」从 `own.register_statement`（D1 之后不再落稿）改成"
             "`own.land_manuscript` → 派 V → `own.ingest_manuscript`，并新增"
             "「位置与格由你指定、工具按块回填」（`target_stmt_id` 权威、`cells` 闭集、"
             "派生列不许指定）。`own.*` 只在被派那一趟的循环注册表里现装，不进"
             "`tools_lines` ⇒ 十一格里只有 B 换值（0a45243e…）。facts 键集仍 15 格。"},
    # p266 → p267（2026-11-10，概念的良定义证明有落点；业主裁定 甲）：
    # facts 键集一格没动（还是 15 格）—— 本批只改 `specs/b.py` 的 policy 一段
    # （概念也走 land → 派 V → ingest 这条链，稿由 B 产出）。
    {"version": "p267", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p267（2026-11-10，概念良定义证明）：上游 —— `specs/b.py` 的 policy"
             "新增「概念的良定义证明也走这条链（稿由你产出）」：概念不是没有证明可写，"
             "B 用 `own.land_manuscript` 落 `reports/b-proof-<号>.md`、派 V 三转签、"
             "签回来用 `own.ingest_manuscript(apply, cells=[\"proof_text\"])` 收录；"
             "概念没有等级轴（`derive_grade` 短路成 `not_applicable`，不改）。"
             "十一格里只有 B 换值（65b7ff46…）。facts 键集仍 15 格。"},
    # p267 → p268（2026-11-10，自产概念在 B 的动作面有入口）：
    # facts 键集一格没动（还是 15 格）—— 本批只改 `specs/b.py` 的 policy 一段
    # （自己定义的新概念要显式声明 `self_authored=True`）与动作参数面（不进 system）。
    {"version": "p268", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p268（2026-11-10，自产概念有入口）：上游 —— `specs/b.py` 的 policy"
             "新增「自己定义的新概念要显式声明 `self_authored=True`」（origin=own_result "
             "必须显式声明、不传仍受控拒、与 source_lit_id 同时给是自相矛盾）；"
             "`AgentB.register_statement` 的参数面同时收这一格（参数说明不进 system）。"
             "十一格里只有 B 换值（767b6994…）。facts 键集仍 15 格。"},
    # p268 → p269（2026-11-10，B 不该知道 V 内部审几次；业主 2026-11-04 裁定）：
    # facts 键集一格没动（还是 15 格）—— 本批只改 `specs/b.py` 的 policy 一句
    # （概念良定义证明那条「派 V 照常三转签」→「派 V 照常签」，行数 773 不变）。
    {"version": "p269", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p269（2026-11-10，B 不该知道 V 审几转）：上游 —— `specs/b.py` 的"
             "policy 只说「派 V 照常签」，不再教 V 内部会连续审几次（业主逐字：「就说"
             "拿到 V 签，不需要知道 V 内部会连续三次审」）；「拿到 V 签才算数」这一条"
             "原样保留。十一格里只有 B 换值（7705b3b4…）。facts 键集仍 15 格。"},
    # p269 → p270（2026-11-10，递审只递框架手稿：真机 9 次全拒、签一发未发）：
    # facts 键集一格没动（还是 15 格）—— 本批只改三份 spec 的 policy 教法
    # （F 递审只点 manuscript_path / V 见别的东西先退回 / D 只转 manuscript_path）
    # 与 agent_skills 的 F/V/D 手册正文（手册只落盘、不进 facts）。
    {"version": "p270", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p270（2026-11-10，递审只递框架手稿）：上游 —— 真机 9 次 verify_proof 全拒、"
             "签一发未发，5 次是同一条「只收 F 的证明手稿，收到 reports/P1-MCT.md」——"
             "F 把 fs.write 写的论文章节稿当手稿递给了 V。三处教法（入口闸一个字没改）："
             "① specs/f.py 的 policy 说清「只能点 F.step 返回的 manuscript_path；章节稿不是手稿」；"
             "② specs/v.py 的 policy 说清「被审必须是 reports/f-proof*.md；递来别的东西先退回、"
             "入口闸拒了不许重试同一路径」；③ specs/d.py 的 policy 说清「携带只转 manuscript_path、"
             "不转章节稿」。十一格里 D / F / V 三格换值（a45d95a8… / e66809ec… / cc875eaa…）。"
             "facts 键集仍 15 格。"},
    # p270 → p271（2026-11-10，立项用计划号、入账才建命题行）：
    # facts 键集一格没动（还是 15 格）—— 本批只改 M 的 policy 三句教法（立项不建在台账上 /
    # 决定即立项 / 成果是收录的产物）与 agent_skills 的 M 手册正文（手册只落盘、不进 facts）。
    {"version": "p271", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p271（2026-11-10，立项用计划号、入账才建命题行）：上游 —— 两轮真机都没有谁"
             "把「立项 → 落稿 → 送审 → 收录」当成一条必须走完的链（第一轮 B 建了 4 条号而 V 9 次"
             "送审里 5 次栽在「递的不是框架手稿」、签 0；第二轮 V 真的审了框架手稿，而 B 一次"
             "都没跑 —— 派活被 deadline_exceeded 拒，statements 0 条、签 0 个）。M 的 policy 新增"
             "三句：① 立项不建在命题台账上（拿计划号、F 落 reports/f-proof-plan-<计划号>.md、V 送审"
             "不传 statement_id、判词有落点、B 收录时才建 statements 行 —— 「立项看计划号，入账看"
             "命题号」）；② 决定要证某条命题的那一刻就立项（分命题不分钟）；③ 成果是台账里的条目，"
             "但那是收录的产物、不是立项的产物。十一格里只有 M 换值（6996deb9…）。"
             "facts 键集仍 15 格。"},
    # p271 → p272（2026-11-10 晚，业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号。
    # 停掉错误的口径。」）：
    # facts 键集一格没动（还是 15 格）—— 本批只改 M/F/V/B 四处教法与 agent_skills 的手册正文
    # （手册只落盘、不进 facts）；编号实现（`manuscriptids`）与收录侧也不进 facts。
    {"version": "p272", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p272（2026-11-10，F 自己的稿号源）：上游 —— 业主裁定「F 的稿自己维护一套"
             "号源，不依赖命题号和计划号。停掉错误的口径。」三个号各管一件事：稿号（F 自己发、"
             "签的单位）/ 计划号（继续-放弃-更改的单位）/ 命题号（B 收录时现取）。题面四处"
             "（M/F/V/B）改写：F 的稿叫 reports/f-proof-<稿号>.md、收录不改名、F 的稿可签；"
             "specs/m.py 的 p271 那一段（立项用计划号命名 / 计划稿判成立只看过没签）按新口径"
             "改写。十一格里 B / F / M / V 四格换值（bff2b0ec… / 0a2de44f… / 4d85c06c… / "
             "12872e74…）。facts 键集仍 15 格。"},
    # p272 → p273（2026-11-10 晚，`draft/181` 的 A + B 批 + 题面并入）：
    # facts 键集一格没动（还是 15 格）—— 本批只改 `specs/c.py` 的 policy 那一段
    # （污染面手算多跳 → `ledger.resolve` 选根 / `ledger.expand` 按层展开 / `frontier` 拼接）
    # 与 C 的工具面（`ledger.*` 两件只读工具，进 `tools_lines` 那一行）；facts 的键集与落点
    # 都没有变，所以 count / keys_sha256 与 p272 同值。
    {"version": "p273", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p273（2026-11-10，局部树的按需展开）：上游 —— 业主「C 的建树不是全建，"
             "是选定一个节点后上下按某层数（它自行决定）展开父和子，建立局部树，且可按需"
             "拼接扩张」＋「污染面……这只是一种需求模式，不是一种工具」。代码侧新增只读索引"
             "（ledgerindex.LedgerIndex，本次唤醒缓存一次、不进上下文）与 C 的两件工具"
             "（ledger.resolve 选根 / ledger.expand 层数必填的局部树）；specs/c.py 的 policy 由"
             "「table.list 读 dependencies 反向走多跳」改成「选根 → 按层展开 → 对 frontier 拼接」。"
             "十一格里只有 C 换值（de99ae26…）。facts 键集仍 15 格。"},
    # facts 键集一格没动（还是 15 格）—— 本批只改「F 侧撤按命题号写证明」那几处教法
    # （`specs/f.py` 的送审参数表与两处稿名、共用段 `PAPER_PACK` 与 L 的关档文案各一处
    # `f-proof-<命题号>` → `f-proof-<稿号>`、`agent_skills` 的 F 手册）；没有哪一格事实
    # 换过落点（system ↔ user），所以 count / keys_sha256 与 p273 同值。
    {"version": "p274", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p274（2026-11-10，F 侧撤「按命题号写证明」）：上游 —— 业主逐字"
             "「对于 F 侧，在实现方面彻底通畅（你亲自拿着跑跑通）后，撤去所有有关对某个"
             "给定命题号进行攻坚或写证明的逻辑」。改动全在教法与实现接口：specs/f.py 的"
             "送审参数表删「在册后给号」那一格、两处稿名改成稿号、交稿改走 D；"
             "PAPER_PACK / L 的关档文案各一处旧字面；agent_skills 的 F 手册重写；"
             "agent_f 的 publish/promote 删兼容形参、登记面只递稿号 + 正文、送审提示只点稿。"
             "十一格里只有 F/G/H/M 换值（a62be58c / 6730aa37 / 4e36b38d / 47d3b555）。"
             "facts 键集仍 15 格、落点没动。"},
    # p274 → p275（2026-11-11，真机第三轮的通道断）：facts 键集一格没动（还是 15 格）——
    # 本批只改 F 自己的段（`attack.step` 的参数面 + 动作摘要 + `specs/f.py` 的一条教法），
    # 外加两条实现：`agent_f.step(product=…)` 与 `attackround` 的产物 schema / 逐步判据
    # 抽出一份给两处共用。facts 的键集与落点都没有变，所以 count / keys_sha256 与 p274 同值。
    {"version": "p275", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p275（2026-11-11，真机第三轮的通道断）：上游 —— F 调了 5 次 "
             "`attack.step`、0 次 proof 全部 reduction；收工话逐字「数学内容写出来了，但"
             "没有拿到框架手稿，也没有 V 签」；根因是 `attack.step` 的 schema 只有 "
             "`plan_id` 一格（`additionalProperties=False`）⇒ F 没有把证明正文交进来的入口。"
             "本批给入口：`attack.step` 增加可选 `product`（`proof` / `reduction`），"
             "`agent_f.step(product=…)` 用它跑既有的产物校验、过了照现有路径落 "
             "`reports/f-proof-<稿号>.md`；`specs/f.py` 的动作表同步那一格 + policy 补一条"
             "教法（「写好的证明可以直接交进来；不交也没关系，老路不变」）。"
             "十一格里只有 F 换值（27d85b47…）。facts 键集仍 15 格、落点没动。"},
    # p275 → p276（2026-11-11，一个稿号 = 一份文件 = 一份证明）：facts 键集一格没动
    # （还是 15 格）—— 本批只改 F 的段（多证明政策整条重写：第二份证明另开一份稿，
    # 不再用 `-pN`）与三份手册正文（`agent_skills` 的 F/M/B/V，手册只落盘、不进 facts），
    # 再把 `verify_proof` 的 returns 与 V 顶层读数里的 `proof_no` 撤掉（工具声明不进 facts）。
    # facts 的键集与落点都没有变，所以 count / keys_sha256 与 p275 同值。
    {"version": "p276", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p276（2026-11-11，一个稿号 = 一份文件 = 一份证明）：上游 —— 业主逐字"
             "「一个稿号就相当于是该稿的文件名」「同稿号多个版本是错误的」「拿 V 签冻结后交"
             "哪份是明确的」⇒ F 的「同一份稿的第 N 个证明（-pN）」教法退役，改成「要写第二份"
             "证明就另开一份稿（新稿号）」；`proof_no` 在 F 的送审参数表里不再传（老盘 -pN"
             "只读兼容那句保留）。台账侧（B/D）的 1..N 口径不变：1..N 现在是 N 份稿各一条"
             "路径。十一格里只有 F 换值（4306d8ed…）。facts 键集仍 15 格、落点没动。"},
    # p276 → p277（2026-11-11，P1 七件一致化 + G/H 边集）：facts 键集一格没动
    # （还是 15 格）—— 本批只改题面正文（B/D/F/V 四格的 policy / 动作摘要）与工具面
    # （`manuscripts.submission_reading` 多一件、进 `tools_lines` ⇒ 十一格的工具清单各多
    # 一行），外加两份 golden 的重冻；没有哪一格事实换过落点（system ↔ user），所以
    # count / keys_sha256 与 p276 同值。
    {"version": "p277", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p277（2026-11-11，P1 七件一致化）：上游 —— ① B 的 ACTIONS 补 "
             "`open_polish_copy`（冻结后的补救路径从结构上不可达变成可达），`own.*` 不进 "
             "`tools_lines`；② B 的题面退役 -pN / proof_no 教法（B 的稿号是自己的号段，"
             "第二份证明是另一份稿）；③ D 只递稿路径、路径号由 B 收录时分配；④ V 的签"
             "身份改成正文 sha + 稿路径；⑤ F 题面/手册补「已拿签的稿不许就地改」；"
             "⑥ D→B 生产路（register_statement 指针支）也分配路径号；⑦ "
             "`manuscripts.submission_reading` 暴露成工具（全部角色、只读）、进 "
             "`tools_lines`。另同批 G/H 的边集按业主裁定改（G 出边 C/D/H、H 去掉 G）。"
             "十一格全换：工具清单多一行（十一格都换）+ B/D/F/V 四格的段文本换值。"
             "facts 键集仍 15 格、落点没动。"},
    # p277 → p278（2026-11-11，业主真机三裁定 · 甲 + 丙）：facts 键集一格没动
    # （还是 15 格）—— 本批只改三份题面的 policy 正文（F/E/B 的「送审之后必须挂计时器
    # 等 V 的反馈；签成立即提交；B 另有交稿义务」）与 `review.review_document` 的
    # returns（`open_findings` 一格；returns 不进 `tools_lines`）。没有哪一格事实换过
    # 落点（system ↔ user），所以 count / keys_sha256 与 p277 同值。
    {"version": "p278", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p278（2026-11-11，真机三裁定 · 甲 + 丙）：上游 —— ① 甲：F / E / B "
             "三份题面各补一段「送审之后必须挂计时器等 V 的反馈，不许送完就收工」；"
             "签「成立」那一刻由框架写 `mss:` 记号（`via=sign_issued`），收工再扫一次、"
             "幂等；B 另写「交稿也是你的义务」。② 丙：`review_document` 的 target_status "
             "加闸（有 open findings 不许 accepted），returns 补 `open_findings` 读数"
             "（不进 tools_lines）。变化格 = B / E / F 三格，其余八格逐字未动。"
             "facts 键集仍 15 格、落点没动。"},
    # p278 → p279（2026-11-12，G 的 revise 教法按新轮次口径改）：facts 键集一格没动
    # （还是 15 格）—— 本批只改 `specs/g.py` 的一处动作说明（`revise` 的轮次账口径），
    # 没有哪一格事实换过落点（system ↔ user），所以 count / keys_sha256 与 p278 同值。
    {"version": "p279", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p279（2026-11-12，G 的 revise 轮次教法）：上游 —— `specs/g.py` 的 "
             "`revise` 动作说明还把轮次账教成「review_rounds+1、status=revised」，"
             "而 239e23a7 起轮次账跟着复审走（G.revise 只把轮次托到 max(cur,1)，"
             "此后每次 review.review_document / review.verify_fixes 才 +1）⇒ 改成"
             "「改稿开启/推进这一轮；「复审收过几次」看 review_rounds」。变化格 = G"
             "（e6bcda81… → 4f8dc27e…），其余十格逐字未动（版本行已归一）。"
             "facts 键集仍 15 格、落点没动。"},
    # p279 → p280（2026-11-13，教法对齐）：facts 键集一格没动（还是 15 格）—— 本批只改
    # B/E/F/M 的 policy 正文与三份手册（手册只落盘、不进 facts），没有哪一格事实换过落点
    # （system ↔ user），所以 count / keys_sha256 与 p279 同值。
    {"version": "p280", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p280（2026-11-13，设计对齐最后一项 · 教法）：产出侧只认一套形式，"
             "提示词 / 手册 / 政策正文里的旧写法逐句改成现行为 —— ① 携带单第四格 = 路径号"
             "（由 B 收录时分配；产出侧不写证明号、稿名不带 `-pN`）；② E 的稿头没有"
             "`- 证明号：` 这一行；③ 另一份证明 = 另一个稿号；④ 老盘 `-p2` 不再被认成"
             "手稿（「只读兼容 / 仍能分类 / 读 / 认签」那句删掉）；⑤ 送审之后按签拦收工、"
             "不按计时器拦（`agent_loop._v_wait_gate_reading`：计划号 / `e-proof` / "
             "`b-proof` 有无现行的 V 签、有无被明确放弃）；⑥ `path_id` 的显示名口径写成"
             "`p<路径号>g<组号>`。变化格 = B / E / F / M（其余七格逐字未动，版本行已归一）。"
             "facts 键集仍 15 格、落点没动。"},
    # p280 → p281（2026-11-13，四方合批）：facts 键集一格没动（还是 15 格）—— 本批只改
    # B / D / F 的 policy 与一处 schema 说明（W1 命题字段 / W2 第十条 / X1 派活段），
    # 没有哪一格事实换过落点（system ↔ user），所以 count / keys_sha256 与 p280 同值。
    {"version": "p281", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p281（2026-11-13，业主批准的四方合批）：① W1 —— `specs/f.py` 的交付"
             "示例 JSON 给 proof 档加 `proposition`，形态闸那一段改成三句（`## 命题` 永远是"
             "定理陈述、由 `product.proposition` 逐字渲染；子目标正文不是命题；判不过 / "
             "没判成 ⇒ `proposition_form_refused`、稿一个字节都不写、改的是 `proposition` "
             "那一格）；`attackround.PRODUCT_SPECS['proof']` 要求 `proposition` + `steps`，"
             "`HANDED_PRODUCT_SCHEMA` 的 `proposition` 补 description、`label` 改成"
             "「一句话标签；不是命题」。② W2 —— `INGEST_POLICY` 补第十条（命题节不是定理"
             "陈述 ⇒ 让动作出受控拒、不要写成给 D 的 handoff）。③ X1 —— `specs/d.py` 的"
             "派活段（plan 由 F 定、一个方向一个 F、不按 plan 个数派；D 可查 plan 并发建议；"
             "放弃理由只认「不再需要」；`dispatch_fit` 轴只提醒不拦）。④ secretary 的"
             "`dispatch_fit` 题面在 R2 已落，本批只核口径。变化格 = B / D / F（其余八格逐字"
             "未动，版本行已归一）。facts 键集仍 15 格、落点没动。"},
     # p281 → p282（2026-11-14，业主裁定「是否出 paper 退出收工判定，由 M 自行判断是否到
     # 这个时机」）：facts 键集一格没动（还是 15 格）—— 本批只改 `conductor.closing` 的
     # 工具说明与 `status` 的键名单（`paper` 落 `readings.paper`），没有哪一格事实换过落点
     # （system ↔ user），所以 count / keys_sha256 与 p281 同值。这一格补的是当时漏记的账：
     # `PROMPT_VERSION` 先抬到了 p282，而账本最后一格还停在 p281
     # （`test_facts_migration_must_leave_a_version_trace` 因此一直红）。
     {"version": "p282", "count": 15,
      "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
      "note": "抬版本 p282（2026-11-14，业主裁定「是否出 paper 退出收工判定」）："
              "`conductor.closing` 的说明从「八格」改成「七格」、`status` 的键名单去掉 "
              "`paper` 并注明它落 `readings.paper`（由 M 判断，不是门）。变化格 = D / G / "
              "H / M（这四格读得到 M 的工具说明），其余七格逐字未动。facts 键集仍 15 格、"
              "落点没动。"},
     # p282 → p283（2026-11-15，FC-27 人审批；三批改动合并后的唯一一次抬版）：facts 键集
     # 一格没动（还是 15 格）—— 本批改的是 specs/d.py / f.py / m.py 的 policy 正文、
     # specs/h.py 的 verify_fixes（撤轮数上限、改 `close_as`）、capabilities 的两条过期
     # 登记、PAPER_PACK 的第五 / 六节、table_tools 的 `table.update` 说明，以及
     # agent_prompts 那一格的账注；没有哪一格事实换过落点（system ↔ user），所以
     # count / keys_sha256 与 p282 同值。另：`99f6a08f` 之后 `agent_skills.py` 的 H 段改动没抬版本（账本最后一格停在 p281），这一格同时补齐那次漏账。
     {"version": "p283", "count": 15,
      "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
      "note": "抬版本 p283（2026-11-15，FC-27 人审批；三批改动合并后的唯一一次抬版）。"
              "这一版同时包含三件事：① PAPER_PACK 第五 / 六节的收工门从「八格」改成"
              "「七格」、`paper` 写明落 `readings.paper`（`paper` 退出收工判定，是否出 "
              "paper 由 M 自己判断时机）。② 撤掉审校轮数上限 —— `specs/h.py` 的 "
              "`verify_fixes` 摘要 / 参数面按业主 2026-11-15 裁定重写（`max_review_rounds` "
              "随机制撤除，改声明 H 自己的收尾判断 `close_as`；`capabilities.py` 删掉 "
              "`(\"H\", \"verify_fixes\")` 的过期登记），**收不收尾由 H 判断、不由任何计数器"
              "触发**，也不再提供轮次读数。③ `specs/d.py` 的教法收口（五处「D 自己立猜想」"
              "＋ 一处把 F 的工具 `attack.abandon_plan` 说成 D 的写入口）＋ `specs/m.py` 不再"
              "点名 D 的猜想登记动作、改成产出侧落账 ＋ `capabilities.py` 删掉过期的 "
              "`(\"D\", \"register_conjecture\")` 登记 ＋「difficulty 档 `salvaged` 可不指」"
              "（d / f / m 三份 spec 与 `table_tools`：放弃之后按正常流程注册新命题是主路径，"
              "事后要记成可取之处再给 `salvaged`）。变化格 = A / B / D / E / F / G / H / L / M "
              "九格（A / B / E / L 是 `table.update` 那一行说明改了，它们自己的段没动）；"
              "C / V 逐字未动（版本行已归一）。facts 键集仍 15 格、落点没动。"},
     # p283 → p284（2026-11-16，业主逐字「改」授权的唯一一处；FC-27 区 `specs/d.py`）：
     # facts 键集一格没动（还是 15 格）—— 本批只把 D 的 policy 里 F 的工具名
     # `attack.abandon_plan` 降成动作名 `abandon_plan`（纯词法判据
     # `test_policy_never_names_a_tool_the_role_lacks` 要求 policy 里出现的注册工具名
     # 必须在该角色自己的工具面上），没有哪一格事实换过落点（system ↔ user），所以
     # count / keys_sha256 与 p283 同值。
     {"version": "p284", "count": 15,
      "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
      "note": "抬版本 p284（2026-11-16，业主逐字「改」授权的唯一一处；FC-27 区 "
              "`specs/d.py`）：D 的 policy 把 F 的工具名降成动作名（"
              "`attack.abandon_plan` → 裸动作名 `abandon_plan`，同段已有 "
              "`F.create_plan` / `F.step` 同形），为的是过 "
              "`test_policy_never_names_a_tool_the_role_lacks` 的纯词法判据；语义未变"
              "（那本来就是 F 的动作，D 只被告知「由 F 动手」）。这一版只改了这一处，"
              "变化格 = D 一格，其余十格与 p283 逐字相同（版本行已归一）。"
              "facts 键集仍 15 格、落点没动。"},
     # p284 → p285（2026-11-16，CL2 / 12A）：facts 键集一格没动（还是 15 格）—— 本批只改
     # 了 `conductor.void_items` 的摘要措辞（两处别家工具写明施事），没有哪一格事实换过
     # 落点（system ↔ user），所以 count / keys_sha256 与 p284 同值。
     {"version": "p285", "count": 15,
      "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
      "note": "抬版本 p285（2026-11-16，CL2 / 12A，审计 AU1 表一 A1）："
              "`conductor.void_items` 的摘要里两处别家工具名写明施事 —— "
              "「**主控**用 `conductor.board` 看它们」/「仍是**主控**的 "
              "`conductor.wake_blocked`」。`conductor.board` 的 roles 只有 M，"
              "而 void_items 发给 6 个父角色 ⇒ 原句在教 6 个拿不到它的角色去调。"
              "变化格 = A / B / D / E / F / G / L / M（这八格读得到 void_items 那一行）；"
              "C / H / V 是只读角色、面上没有它，逐字未动。facts 键集仍 15 格、落点没动。"},

)

def test_facts_migration_must_leave_a_version_trace() -> None:
    """判据（事务三）：动 `STEP_VOLATILE_FACTS` 必须在 `PROMPT_VERSION` 上留痕迹。

    ## 这一条守的是"审计射程的边界"（不是"提示词文本"）

    `_FROZEN_PROMPT_DIGESTS`（`test_agent_prompts.py`）按缺省事实渲染模板 ⇒ 它看得见"哪一段的字变了"，看不见"哪几格事实被挪出了 system"。而后者对模型是同一件事：
    落点变了 = 它读到的地方变了。所以"facts 迁移"必须与"改段"同等待遇 —— 抬版本。三处都判：① 正控：live 键集 = 账本最后一格，且那一格的版本 = `PROMPT_VERSION`（今天成立）；②
    反真空：账本至少两格、相邻两格的键集哈希不同（否则"记账"这件事没有内容，一个恒等于 live 的账本什么也守不住）—— 而且它记下了"上一批没抬版本"这个事实；③ 负控（两个方向都打）：
    - 删掉一个键而不抬版本 ⇒ 必红（报"facts 迁移了而账本最后一格没记"）；
    - 键集没动而账本最后一格的版本落后一格 ⇒ 必红（报"版本没抬"）。
    外加一条正控的反面：抬一格版本并在账本里记下新键集 ⇒ 绿（证明它不是"永远红"）。
    """
    version = AP.PROMPT_VERSION
    problem = PS.facts_migration_problem(version, frozen=_VOLATILE_FACT_SETS)
    assert problem == "", problem

    # ---- 反真空 ①：账本真的记过东西（不是一格空表）。
    assert len(_VOLATILE_FACT_SETS) >= 2, _VOLATILE_FACT_SETS
    first, last = dict(_VOLATILE_FACT_SETS[0]), dict(_VOLATILE_FACT_SETS[-1])
    assert first["keys_sha256"] != last["keys_sha256"], (
        "账本里两格的键集哈希相同 ⇒ 这一批 facts 迁移没留下任何读数")
    assert int(last["count"]) == len(PS.STEP_VOLATILE_FACTS), (
        int(last["count"]), len(PS.STEP_VOLATILE_FACTS))
    # 反真空 ②：账本最后一格就是 live 的现算值（不手抄、也不是一个随手写的常数）。
    assert (int(last["count"]), str(last["keys_sha256"])) == PS.volatile_facts_digest(), (
        last, PS.volatile_facts_digest())
    # 反真空 ③：上一批那一格记的是"12 格"（它证明这本账记得住历史，而不是只有一格）。
    assert int(first["count"]) == 12, first

    # ---- 负控 ①：删掉一个键（不改版本）⇒ 必红，且报的是"账本没记"这一档。
    shrunk = {k: v for k, v in PS.STEP_VOLATILE_FACTS.items() if k != "parent_limits"}
    assert len(shrunk) == len(PS.STEP_VOLATILE_FACTS) - 1, "负控没删到东西"
    red = PS.facts_migration_problem(version, frozen=_VOLATILE_FACT_SETS, mapping=shrunk)
    assert red, "删掉一格登记表元素而不抬版本，判据却放过了 ⇒ 这条判据什么也守不住"
    assert "账本最后一格没记" in red, red

    # ---- 负控 ②：键集换了、也记了新账，但版本号没抬（最后一格还写着上一版）⇒ 必红。
    stale_version = dict(last, version="p172")
    red = PS.facts_migration_problem(version, frozen=(*_VOLATILE_FACT_SETS[:-1], stale_version))
    assert red and "PROMPT_VERSION" in red, red

    # ---- 正控（相反的一跳）：抬一格版本 + 账本跟着记 ⇒ 绿（红不是写死的）。
    bumped = f"p{int(version[1:]) + 1}"
    ok = PS.facts_migration_problem(bumped, frozen=(*_VOLATILE_FACT_SETS[:-1],
                                                    dict(last, version=bumped)))
    assert ok == "", ok
    # 抬版本时忘了记账（键集还停在上一格）⇒ 也必红（"版本动了而这一格没跟上"）。
    red = PS.facts_migration_problem(bumped, frozen=(*_VOLATILE_FACT_SETS[:-1],
                                                    dict(first, version=bumped)))
    assert red, "只抬版本、键集账本没跟上，判据却放过了"


def _ledger_date(cell: dict[str, Any]) -> str:
    """账注里第一个 ISO 日子（读不出就是空串）。账注是散文，日子只在开头那一处。"""
    found = re.search(r"\d{4}-\d{2}-\d{2}", str(cell.get("note") or ""))
    return found.group(0) if found else ""


def test_no_ledger_note_is_dated_after_the_current_version() -> None:
    """账注的日子不许晚于账本最后一格（= 当前版本那一格）的日子。

    改前读数（2026-10-31）：p220 那格写 2026-11-01，而账本最后一格 p221 写 2026-10-30
    —— 同一条账里出现「后落地的一版日子更早」，读的人无法判断到底是"p220 还没落地"
    还是"那一格的日子写错了"。而 2026-11-01 那时还没到：抬 p220 的 commit 是
    89e784a2，落盘 2026-10-30 22:36（`git log --format='%h %ad' 89e784a2` 可复核）。

    为什么上界取「最后一格」而不是「今天」：最后一格就是 live 那一版（上一段的正控
    钉着它的版本号 = `PROMPT_VERSION`），它的日子是账本里唯一可当上界的日期 ——
    拿系统时钟判会变成一条"换台机器、换一天跑就红"的判据，那不是判据，那是时钟的读数。

    这一条不判格与格之间的先后：p209 / p210 / p211 记的是 2026-10-26，而 p208 记
    2026-10-27 —— 那几格是"批次日"与"落地日"不同，都是已经过去的日子；改它们要另
    一笔授权（见这一批 H 的处置清单），也不该混进"这一格写了一个还不存在的日子"里。
    """
    dates = [(str(c.get("version") or ""), _ledger_date(c)) for c in _VOLATILE_FACT_SETS]
    top_version, top_date = dates[-1]
    assert top_date, (f"账本最后一格 {top_version} 的账注里读不出日子 ⇒ 这条判据的上界"
                      "没有对象（反真空：它不许在一个没有日期的账本上恒真）")
    late = [f"{v}：{d} 晚于最后一格 {top_version} 的 {top_date}"
            for v, d in dates if d and d > top_date]
    assert late == [], late
    # 反真空：账本里绝大多数格子都真的带着日子（不是只有最后一格有）。
    assert len([1 for _v, d in dates if d]) >= 10, dates


def test_the_volatile_fact_keyset_digest_is_order_independent() -> None:
    """判据的读数本身：键集指纹与插入顺序无关（否则重构一下 dict 就"迁移"了）。"""
    reversed_map = dict(reversed(list(PS.STEP_VOLATILE_FACTS.items())))
    assert PS.volatile_facts_digest(reversed_map) == PS.volatile_facts_digest()
    # 少一格 / 多一格都必须换指纹（判据的牙）。
    fewer = {k: v for k, v in PS.STEP_VOLATILE_FACTS.items() if k != "availability"}
    more = dict(PS.STEP_VOLATILE_FACTS, **{"a_new_fact": "探针"})
    assert PS.volatile_facts_digest(fewer)[1] != PS.volatile_facts_digest()[1]
    assert PS.volatile_facts_digest(more)[1] != PS.volatile_facts_digest()[1]


def test_the_dynamic_section_whitelist_is_registered_and_small() -> None:
    """反真空：登记表是显式的一份，且段白名单初始为空（不是"什么都允许"）。

    "初始为空"是一条判据而不是一种风格：白名单一空，任何一段随步变化都会被点名；
    它一旦被随手填满，前缀缓存就又会悄悄失效，而没有一条测试会因此变红。

    事实登记表（`STEP_VOLATILE_FACTS`）反过来必须是写全的一份：2026-10-21 起它
    除了"每步会变"的两格，还收"跨 run 会变"的十格（否则换一趟活的第一次调用
    永远命中不了），以及"随这一趟的配置变"的两格（`availability` / `parent_limits`
    —— 2026-10-21 第二批；见那一节的三轴表）。这里钉住精确的键集 —— 少一格（有人把
    某格挪回 system）与多一格（有人把静态事实也挪出去、于是模型读不到它）都会红。
    """
    assert isinstance(PS.DYNAMIC_SECTION_WHITELIST, frozenset), PS.DYNAMIC_SECTION_WHITELIST
    assert PS.DYNAMIC_SECTION_WHITELIST == frozenset(), PS.DYNAMIC_SECTION_WHITELIST
    # 每步会变的键也必须登记（登记表本身就是"为什么它不进 system"的出处）。
    assert set(PS.STEP_VOLATILE_FACTS) == {
        # 每步会变（`_prompt` 尾部现读）
        "budget_left", "notebook",
        # 跨 run 会变（开场那条 user 消息里现读）
        "task", "task_id", "depth", "parent_task_id", "summoned_by",
        "children", "board", "inbox", "user_replies", "workspace_root",
        # 随这一趟的配置变（也是开场那条 user 消息里现读，2026-10-21 第二批）
        "availability", "parent_limits",
        # 随 V 的台账与 F 的改稿变（开场那条 user 消息里现读，2026-10-22 业主 B-3）
        "v_rejections",
    }, sorted(PS.STEP_VOLATILE_FACTS)
    # 每一格都必须有静态替身（空串会被 `promptkit` 的严格插值拒掉，
    # 而那正是"挪出去但没留指路语"的形态）。
    assert set(PS.SYSTEM_PLACEHOLDERS) == set(PS.STEP_VOLATILE_FACTS), PS.SYSTEM_PLACEHOLDERS
    for key, text in PS.SYSTEM_PLACEHOLDERS.items():
        assert text.strip(), f"{key} 的替身是空的 ⇒ system 里那一格会渲染失败"
        # 反真空：替身必须指得出真值在哪条消息里（"信息换了位置"而不是"被删了"）。
        assert ("本次对话" in text) or ("每步消息" in text), (key, text)


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
    # 同一趟的检查点：`calls == 0` 的汇总也必须落下去（不是"没人发请求就不写这一格"）。
    ck = _checkpoint_of(root, "t-none")
    assert PS.checkpoint_prompt_cache_problem(ck) == "", PS.checkpoint_prompt_cache_problem(ck)
    assert ck["prompt_cache"]["calls"] == 0 and ck["prompt_cache"]["no_request_calls"] >= 1, ck


# ------------------------------------------------ 5. 两处落点：记录文件与 step 事件
#
# 2026-10-19 真机（`projects/t5-empty`，`sid=t5-1`）那两处读数的落点，逐处一条判据：
#
#   ① `runs/agent-<角色>-<sid>.json`（顶趟在 `runs/` 下唯一那份"跑了什么"的记录）
#      —— 改前它 9 格、只有 `spend`，`prompt_cache` 一格都没有；
#   ② 会话里的 `agent_step` 事件 —— 每一步的两格（`prompt_cache_hit_tokens` /
#      `prompt_cache_miss_tokens`，上游字段名照抄）在 `prompt_cache` 之下。
#
# 为什么 ① 是这份文件而不是产出文件：产出文件 `runs/<角色>-<时间戳>-<序号>.json`
# 只在被召唤那条路上写（`AgentLoop._write_run_artifact` 的调用点在 `_summon` 里），
# `run_role` 收工只写检查点。改前那一趟 M（顶趟）在 `runs/` 下就只有 9 格那一份。
def _checkpoint_of(root: pathlib.Path, sid: str) -> dict[str, Any]:
    """读这一趟的检查点文件（不在盘上就当场红：那是"没写成"，不是"少了某一格"）。"""
    path = AL.run_checkpoint_path(root, "M", sid)
    assert path.is_file(), f"这一趟没有落检查点：{path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_step_checkpoint_carries_the_cache_summary(tmp_path: pathlib.Path) -> None:
    """判据 ①（run 记录文件）：检查点里有 `prompt_cache`，且 `hit + miss == tokens_in`。

    三条一起判，缺一条这条判据就不成立：
    - 这一格在（改前不在：`j.get("prompt_cache") is None`）；
    - `hit + miss == tokens_in`（上游给了读数时的自洽判据，与 `mismatched_calls` 同一口径）；
    - `calls == len(run.steps)`（汇总覆盖了每一步，包括不落事件的收工那一步）。
    """
    sid = "t-ckpt-known"
    run, _gateway, root, _events = _run(tmp_path, hit=600, miss=400, sid=sid)
    assert run.stop_reason == "final", run.to_dict()
    ck = _checkpoint_of(root, sid)

    # ①-a 这一格在，且自洽（键集、三态、自洽三条都在这个判据函数里）。
    assert PS.checkpoint_prompt_cache_problem(ck) == "", PS.checkpoint_prompt_cache_problem(ck)
    cache = ck["prompt_cache"]
    assert set(cache) == set(PS.CACHE_SUMMARY_KEYS), sorted(cache)
    # ①-b 与 `spend` 是同一刻、同一趟的两面：逐格相等（不是"另算一份"）。
    assert cache == run.prompt_cache, (cache, run.prompt_cache)
    ends = [e for e in _events if e.get("kind") == "agent_run_end"]
    assert ends and ends[-1]["prompt_cache"] == cache, ends[-1].get("prompt_cache")
    # ①-c 自洽 + 覆盖面。
    assert cache["calls"] == len(run.steps) == 2, (cache["calls"], len(run.steps))
    assert cache["hit"] == 600 * len(run.steps) and cache["miss"] == 400 * len(run.steps), cache
    assert cache["hit"] + cache["miss"] == cache["tokens_in"], cache
    assert cache["unknown_calls"] == 0 and cache["mismatched_calls"] == 0, cache


def test_a_silent_upstream_leaves_both_places_unknown(tmp_path: pathlib.Path) -> None:
    """判据 ③（三态，两处都判）：上游不给读数 ⇒ 两处都是 unknown，不许折成 0。

    折成 0 的后果与单次调用那一档同源（`test_a_silent_upstream_stays_unknown…`）：
    "这家上游不报这一格"（改读数口径）与"这次真的零命中"（改提示词）会长得一模一样。
    这里逐处点名：事件的 `hit`/`miss` 是 `None`；检查点汇总的 `hit_rate` /
    `saved_usd` 是 `None`，`unknown_calls` 计数不是 0，`why` 说清原因。
    """
    sid = "t-ckpt-unknown"
    run, _gateway, root, events = _run(tmp_path, hit=None, miss=None, sid=sid)
    assert run.stop_reason == "final", run.to_dict()

    # ① 记录文件那一处。
    ck = _checkpoint_of(root, sid)
    assert PS.checkpoint_prompt_cache_problem(ck) == "", PS.checkpoint_prompt_cache_problem(ck)
    cache = ck["prompt_cache"]
    assert cache["unknown_calls"] == len(run.steps) > 0, cache
    assert cache["hit_rate"] is None, ("unknown 不许折成 0%", cache)
    assert cache["saved_usd"] is None, ("算不出来就是算不出来", cache)
    assert cache["mismatched_calls"] == 0, cache
    assert "unknown" in cache["why"], cache

    # ② 事件那一处：每一步的两格都是 `None`（不是 0）。
    steps = [e for e in events if e.get("kind") == "agent_step"]
    assert steps, events
    assert PS.missing_prompt_cache_steps(events) == []
    for event in steps:
        step_cache = event["prompt_cache"]
        assert step_cache["prompt_cache_hit_tokens"] is None, step_cache
        assert step_cache["prompt_cache_miss_tokens"] is None, step_cache
        assert step_cache["known"] is False and step_cache["cache_tri"] == "not_reported"


def test_deleting_the_checkpoint_cache_write_makes_the_criterion_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（① 的写入被删）：把收工那次 `save_run_checkpoint` 换回改前的 9 格写法 ⇒ 必红。

    为什么这样造"删掉写入"：改前的形态不是"先写文件后算汇总"（顺序没错），
    而是 `save_run_checkpoint` 自己拼了一份 9 格的 payload，`prompt_cache` 这条路
    从头到尾没接上（调用点只传了 `spend`）。所以负控就是那一份 payload —— 用它写，
    然后看判据红不红。红的位置也要对：检查点在（`spend` 有值），只少了那一格
    —— 否则这条负控红在"没写成"上，什么也没证明。
    """
    from agentflow import autonomy as AU

    def _legacy_save(session_root: Any, role: str, sid: str | None, *, task: str,
                     step: int, stop_reason: str, waiting_for: str = "",
                     spend: Any = None, prompt_cache: Any = None,
                     # 2026-11-02：写侧补了收口三格，桩的签名跟上（旧实现不写它们，
                     # 所以 payload 仍然只有那 9 格）—— 桩要代表"旧实现"，而旧实现
                     # 的签名是它那个年代被调用的形状；拒收新 kwarg 只会让负控红在
                     # TypeError 上，红的位置就不是"prompt_cache 没落盘"了。
                     started_at: str = "", end_ts: str = "",
                     step_source: str = "run") -> str:
        """改前那一版（`agent_loop.save_run_checkpoint` 的 9 格 payload，逐字照抄）。"""
        path = AL.run_checkpoint_path(session_root, role, sid)
        payload = {"role": role, "sid": str(sid or ""), "task": task,
                   "fingerprint": AU.task_fingerprint(role, task),
                   "step": int(step), "stop_reason": str(stop_reason),
                   "waiting_for": str(waiting_for or ""),
                   "spend": dict(spend or {}),
                   "at": "2026-10-19T00:00:00"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return ""

    monkeypatch.setattr(AL, "save_run_checkpoint", _legacy_save)
    sid = "t-ckpt-red"
    run, _gateway, root, _events = _run(tmp_path, hit=600, miss=400, sid=sid)
    assert run.stop_reason == "final", run.to_dict()
    ck = _checkpoint_of(root, sid)
    assert "prompt_cache" not in ck, sorted(ck)          # 写入真的被删了
    assert ck["spend"], f"检查点本身要写成（否则红在'没写'上）：{ck}"
    problem = PS.checkpoint_prompt_cache_problem(ck)
    assert problem and "prompt_cache" in problem, problem
    # 同一趟的汇总在内存里好好的 ⇒ 红的是"没落盘"，不是"没算出来"。
    assert run.prompt_cache and run.prompt_cache["calls"] == 2, run.prompt_cache


def test_every_step_event_carries_the_two_upstream_fields(tmp_path: pathlib.Path) -> None:
    """判据 ②（step 事件）：每一个 `agent_step` 事件都带着那两个上游字段名。

    计数口径（这一格最容易读错，所以逐条写出来）：
    - 收工那一步不落 `agent_step`（它在公共尾段之前 `break`，见
      `LoopRun.final_payload` 那段说明与 `test_every_step_records_the_upstream…` 的
      `len(run.steps) == 2 and len(steps) == 1`）⇒ 事件数 == 步数 − 1；
    - 收工那一步的读数在 `run.steps[-1].to_dict()`（产出文件/检查点的来源）与
      检查点的汇总里，两处都在 —— 判据逐处点名，不假装事件里有它。
    """
    sid = "t-each-step"
    run, _gateway, root, events = _run(tmp_path, hit=600, miss=400, sid=sid)
    assert run.stop_reason == "final", run.to_dict()
    steps = [e for e in events if e.get("kind") == "agent_step"]
    assert len(steps) == len(run.steps) - 1 == 1, (len(steps), len(run.steps))
    # ②-a 判据本体：一个都不缺（键在、两个字段名也在）。
    assert PS.missing_prompt_cache_steps(events) == [], PS.missing_prompt_cache_steps(events)
    # ②-b "带读数"的事件数 == 事件数（不是"有一部分带了"）。
    carrying = [e for e in steps
                if (e.get("prompt_cache") or {}).get("prompt_cache_hit_tokens") is not None
                and (e.get("prompt_cache") or {}).get("prompt_cache_miss_tokens") is not None]
    assert len(carrying) == len(steps), (len(carrying), len(steps))
    for event in steps:
        cache = event["prompt_cache"]
        assert cache["prompt_cache_hit_tokens"] == 600, cache
        assert cache["prompt_cache_miss_tokens"] == 400, cache
        assert (cache["prompt_cache_hit_tokens"]
                + cache["prompt_cache_miss_tokens"] == cache["tokens_in"]), cache
    # ②-c 收工那一步：事件面没有它（既有设计），记录面有 —— 位置一个字节都不挪。
    closing = run.steps[-1].to_dict()
    assert closing["shape"] == "final", closing
    assert closing["prompt_cache"]["prompt_cache_hit_tokens"] == 600, closing
    # 收工那一步也进了汇总（`calls == 2` = 两步都在），于是"省了多少"不漏最后一步。
    assert _checkpoint_of(root, sid)["prompt_cache"]["calls"] == 2, _checkpoint_of(root, sid)


def test_hollowing_the_two_fields_from_the_step_event_makes_it_red(
        tmp_path: pathlib.Path) -> None:
    """负控（② 的字段被删）：只留一个空 `prompt_cache: {}` ⇒ 判据必红。

    这一刀比"把整个键删掉"细：`{}` 让 `event.get("prompt_cache") is not None` 仍然
    成立（改前那条判据只看键在不在），而两格读数一个字都没落 ——
    那正是"看起来写了、其实没写"的形态。所以判据收在字段名上（见
    `missing_prompt_cache_steps` 的说明）。
    """
    _run_ok, _gateway, _root, events = _run(tmp_path / "ok", hit=600, miss=400, sid="t-hollow")
    assert PS.missing_prompt_cache_steps(events) == []
    hollowed: list[dict[str, Any]] = []
    for event in events:
        copy = dict(event)
        if copy.get("kind") == "agent_step":
            copy["prompt_cache"] = {}          # 键在、两格不在
        hollowed.append(copy)
    missing = PS.missing_prompt_cache_steps(hollowed)
    assert missing == [int(e["index"]) for e in events if e.get("kind") == "agent_step"], missing
    # 中间那一档也要分得清：unknown（两格是 None）不算缺。
    unknown_but_present: list[dict[str, Any]] = []
    for event in events:
        copy = dict(event)
        if copy.get("kind") == "agent_step":
            copy["prompt_cache"] = {"prompt_cache_hit_tokens": None,
                                    "prompt_cache_miss_tokens": None}
        unknown_but_present.append(copy)
    assert PS.missing_prompt_cache_steps(unknown_but_present) == []


def test_a_summary_that_folds_unknown_into_zero_percent_is_red() -> None:
    """负控（三态，汇总层）：把 unknown 折成 0% / 用 0 顶上去 ⇒ `cache_summary_problem` 必红。

    单次调用那一档已有判据（`prompt_cache_record` 的 `None`）；这一条守的是汇总
    这一层：`hit_rate=0.0` 与 `hit_rate=None` 在 JSON 里都"看起来是个数"，而前者会
    让下一次读它的人得出"命中率 0%，提示词还得改"这个错误结论。
    """
    good = PS.summarize_prompt_cache([{"called": True, "tokens_in": 1000,
                                       "prompt_cache_hit_tokens": 600,
                                       "prompt_cache_miss_tokens": 400}])
    assert PS.cache_summary_problem(good) == "", PS.cache_summary_problem(good)

    silent = PS.summarize_prompt_cache([{"called": True, "tokens_in": 1000,
                                         "prompt_cache_hit_tokens": None,
                                         "prompt_cache_miss_tokens": None}])
    assert PS.cache_summary_problem(silent) == "", PS.cache_summary_problem(silent)
    assert silent["hit_rate"] is None and silent["unknown_calls"] == 1, silent

    folded = dict(silent, hit_rate=0.0)
    assert "unknown 不许折成 0%" in PS.cache_summary_problem(folded), folded
    # 静默那一次被算进"零命中"（hit/miss 有值）同样红。
    counted = dict(silent, hit=0, miss=1000)
    assert PS.cache_summary_problem(counted), counted
    # 不自洽：hit+miss ≠ tokens_in（上游读数口径可疑）。
    broken = dict(good, tokens_in=1001)
    assert "≠" in PS.cache_summary_problem(broken), broken
    # 少一格（有人另拼了一份 dict，没走 `summarize_prompt_cache`）。
    half = {k: v for k, v in good.items() if k != "saved_unknown_calls"}
    assert "少了" in PS.cache_summary_problem(half), half
    # 空 `{}`：没算过，与"算过但上游没给"必须分得开。
    assert "没算过" in PS.cache_summary_problem({}), PS.cache_summary_problem({})
