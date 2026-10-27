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
     "note": "抬版本 p205（2026-10-27 第二批收口）：① 新工具 clock.wait_any（业主第三条裁定的后半个动作「直到它认为无事可做时，可启动计时器等待任意计时器返回」）进 tools_lines 那一行（名 + 摘要 + 必填参数 + 副作用），tools_lines 对每个角色都渲染 ⇒ 十一格全换；工具数 110 → 111，登记在 tools/UNIVERSAL_TOOLS（写集空：只写 out/clock/wait_any.json 这份意图账），只读角色 C/H/V 的 clock 件数 8 → 9；② conductor.retire_child 的 summary 文案换了（补「待机」那一档与 refusal_code 走 Conductor.retire_state_of 的三态读数）⇒ M 那一格再换一次；它的 returns= 不进段（只进 function-calling 的 description，动的是工具面 golden 的 declarations 那一格）。facts 键集仍 15 格（键名与条数一格未动）"},
    # p205 → p206（2026-10-27 第三批收口）：工具面 returns / summary 十一处进 tools_lines、
    # 十一份 specs 的时钟段补 clock.wait_any 的行为口径、specs/m.py 的 delivered_to 改成列表、
    # conductor.retire_child 的 returns/docstring 补早拒支口径、attackround.BUDGET_GUARD_NOTE
    # 去行号并接上读者。五笔都只动段文本与工具声明，一格事实的落点都没挪 ⇒ `count` 与
    # `keys_sha256` 与上一格同值，仍是 `PS.volatile_facts_digest()` 的现算值（不手抄）。
    {"version": "p206", "count": 15,
     "keys_sha256": "21314a392c60f8559e101f0c59759d3cd1726a861954c7bfb7d3a0459ab2ffe3",
     "note": "抬版本 p206（2026-10-27 第三批收口）：① 工具面 returns / summary 十一处进 tools_lines 那一行（attack.create_plan / clock.alarm_start / clock.timer_cancel / clock.timer_list / clock.wait_any / conductor.guide / fs.edit / fs.write / table.get / table.list / verify.verify_proof —— 实现早就在，这一批才与声明对齐）⇒ 十一格全换；② 十一份 specs 的时钟段补 clock.wait_any 的行为口径（要求过等、且没有可等的东西 ⇒ requested=true / waiting=false，它不是「没在等」；这一档无计时而手头也没活就按交差处理）；③ specs/m.py 的 delivered_to 从「链尾那个绝对编号」改成「列表，只有一个元素 = 链尾那一个的绝对编号（不是标量；读它先取 [0]）」⇒ M 那一格再换一次；④ conductor.retire_child 的 returns 与 docstring 补早拒支那两格（target_state 空串 = 三态还没读；refusal_code 的充要条件是静默闸说话了）；⑤ attackround.BUDGET_GUARD_NOTE 去掉两个已漂的 file:line、改成符号名并接上读者（test_p09_the_guard_note_names_live_symbols）。facts 键集仍 15 格（键名与条数一格未动）"},
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
                     spend: Any = None, prompt_cache: Any = None) -> str:
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
