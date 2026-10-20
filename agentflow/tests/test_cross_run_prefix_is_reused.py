# -*- coding: utf-8 -*-
"""判据：**跨 run** 也能命中同一段前缀（2026-10-21，事务二）。

## 这一组守什么

上一批（`tests/test_prompt_stability.py`）把"每步会变"的两格（`budget_left` /
`notebook`）从 system 挪进了 user 消息，换来的是"同一趟的第 2..N 步"能命中缓存。
但它买到的**只是"同一份前缀的第二次"**：`AGENT_IDENTITY`（段序 0）里带着
`task_id` / `depth` / `children` / `parent_task_id` / `summoned_by`，`TASK_FRAME`
（段序 4200）里带着 `task` 正文 / `inbox` / `board` / `user_replies`，
`WORKSPACE_FACTS`（段序 10000）里带着 `workspace_root` —— 换一趟活，这条前缀
从第 **95** 个字符起就不同（改前实测，见 `tests/fixtures/prompt_cache_warm.json`
的 `cross_run_prefix_chars`）⇒ 换一趟活的第一次调用 `hit=0`。

## 三条判据（每条带负控）

1. **两趟不同的活 ⇒ 同一份 system**（十个角色各一遍，逐字节）。
   负控：把 `task_id` 放回 system（即绕过 `split_facts`）⇒ 必红，且报出
   "从第 N 个字符起不同"（N 落在 `AGENT_IDENTITY` 那一段里，不是"反正不同"）。
2. **同一角色同一趟两次渲染逐字节相同**（`step_stability` 的 `stable=True`；
   `test_prompt_stability.py` 已有那一条，这里再钉一次"跨趟也相同"的那一半）。
3. **被挪走的事实还在 user 消息里**（判据断言"还在，只是换了位置"）：
   跑一趟真的循环，从 `agent_run_start.opening_facts` 读回十格原值，
   逐格断言它①在 user 消息里、②不在 system 里。
   负控：把某一格整段删掉（喂空串 ⇒ 只剩缺省句）⇒ 必红。

## 读数面（真机）

`cross_run_hit`（`scripts/warm_prompt_cache.py --probe-cross-run`）的两行是
"另一趟活"的**同一份 system** 连发两次：改前 = `0 / 满`，改后 = **两次都该 ≥90%**。
`tests/test_prompt_cache_warm.py` 与这里各判一次（那边判读数自洽，这里判比例）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from typing import Any, Mapping

import pytest

from agentflow import agent_prompts as AP
from agentflow import promptstability as PS
from agentflow.agent_loop import OPENING_FACT_KEYS, _opening_transcript, run_role
from agentflow.llmseam import LlmSeam

from test_agent_loop import _wired

_REPO = pathlib.Path(__file__).resolve().parents[1]
_READINGS = _REPO / "tests" / "fixtures" / "prompt_cache_warm.json"

#: "第一趟活"的十格事实（**全部**是跨 run 会变的那几格，一格不少）。
_JOB_A: dict[str, Any] = {
    "task": "把第一件活做完：核一条 1900 年前的引文是否逐字存在",
    "summoned_by": "user",
    "task_id": "t-job-a",
    "depth": 1,
    "parent_task_id": "",
    "children": "",
    "board": "",
    "budget_left": "1.000000 美元",
    "notebook": "（草稿本还是空的）",
    "inbox": "（没有收到留言）",
    "user_replies": "",
    "workspace_root": "D:/ws-a",
}

#: "第二趟活"：同一个角色、另一件完全不同的活（十格逐格不同）。
_JOB_B: dict[str, Any] = {
    "task": "另一件活：把这份手稿的证据位补齐（与前一件毫无关系）",
    "summoned_by": "M",
    "task_id": "t-job-b",
    "depth": 3,
    "parent_task_id": "t-parent-9",
    "children": "- B1（working）",
    "board": "- [i-0007] 一条待消的板项",
    "budget_left": "0.400000 美元",
    "notebook": "- [第 2 步] 记一笔",
    "inbox": "- [m-0003] 一条新留言",
    "user_replies": "- [q-0002] 问：… → 用户答（user）：…",
    "workspace_root": "D:/ws-b",
}

#: 十格"跨 run 会变"的事实（`budget_left` / `notebook` 是每步会变的那两格，
#: 它们也算"会变"，但判据分开：它们的载体是每步的尾部消息）。
_CROSS_RUN_KEYS: tuple[str, ...] = tuple(k for k in _JOB_A
                                        if k not in ("budget_left", "notebook"))


@pytest.fixture(scope="module")
def registry() -> Any:
    """生产同形的工具注册表（`build_registry()`；不需要 store）。"""
    from agentflow.tools import build_registry

    return build_registry().registry


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 1. 两趟不同的活

def test_two_different_jobs_render_a_byte_identical_system(registry: Any) -> None:
    """正控（主判据）：同一个角色、**两趟完全不同的活** ⇒ system 逐字节相同。

    十个角色各判一遍（不是只判 M）：某一段若只在某个角色的模板里插值（例如 M 才有
    的那几块），只判一个角色会漏掉它。反真空也一起判：system 必须有几万字
    （"两边都是空串"那种假相等不许过）。
    """
    checked: list[str] = []
    for role in sorted(AP.ROLE_BRIEFS):
        facts_a, moved_a = PS.split_facts(_JOB_A)
        facts_b, moved_b = PS.split_facts(_JOB_B)
        a = AP.system_prompt(role, registry=registry, **facts_a)
        b = AP.system_prompt(role, registry=registry, **facts_b)
        assert len(a) > 20_000, f"{role} 的 system 只有 {len(a)} 字 ⇒ 反真空"
        reading = PS.step_stability(a, b)
        assert reading["stable"] is True, f"{role}：两趟不同的活 system 不同\n{reading['reason']}"
        assert _sha(a) == _sha(b), role
        # 反真空（另一半）：这两份事实**真的**不同 —— 否则上面的"相同"什么也没证明。
        assert moved_a["task"] != moved_b["task"], moved_a
        assert moved_a["task_id"] != moved_b["task_id"], moved_a
        checked.append(role)
    assert len(checked) == len(AP.ROLE_BRIEFS) == 10, checked


def test_putting_task_id_back_into_the_system_makes_it_red(registry: Any) -> None:
    """负控（① 的牙）：把 `task_id` 放回 system ⇒ 两趟的 system 必红，且报出位置。

    怎么造"改前那个形态"：**不过** `split_facts`，把这份事实直接喂给
    `system_prompt` —— 那正是改前 `agent_loop` 的做法（它那时也过一遍渲染，
    只是登记的格子里没有 `task_id`）。红的位置也要对：差异必须落在
    `AGENT_IDENTITY`（段序 0）那一段里，也就是**很靠前**的地方 ——
    报一个"反正不同"而位置在 5 万字之后，说明红的原因不是这一格。
    """
    victim = "task_id"
    for role in ("M", "A", "D"):
        raw_a = dict(_JOB_A)
        raw_b = dict(_JOB_B)
        a = AP.system_prompt(role, registry=registry, **raw_a)
        b = AP.system_prompt(role, registry=registry, **raw_b)
        reading = PS.step_stability(a, b)
        assert reading["stable"] is False, (
            f"{role}：把 `{victim}` 放回 system 之后两趟仍然逐字节相同 ⇒ 这条负控是空转")
        problem = reading["reason"]
        assert "从第" in problem and "个字符起不同" in problem, problem
        diff = reading["first_diff"]
        assert diff is not None, reading
        # 位置：`AGENT_IDENTITY` 是第一条段（段序 0）⇒ 差异在头 400 个字符里。
        # （改前实测第 95 个字符；这里放宽到 400，是因为"号"与"深度"谁先变会移动它。）
        assert diff["index"] < 400, (
            f"{role}：差异落在第 {diff['index']} 个字符（改前读数约 95）⇒ "
            f"红的原因可能不是 task_id 这一格：{problem}")
        # 报出来的上下文里真的能看到那一格的值（不然定位不到该改哪儿）。
        assert _JOB_A["task_id"] in diff["prev_context"] or _JOB_B["task_id"] in diff["cur_context"], (
            f"{role}：差异前后 80 字里没有那两个台账号 ⇒ 报的不是这一格：{diff}")


def test_the_same_job_rendered_twice_is_byte_identical(registry: Any) -> None:
    """判据 ②：**同一趟**的两次独立渲染逐字节相同（跨 run 相同的另一半）。

    与上面那条分工：上面换的是"哪一趟"，这一条换的是"渲染了几次"（同一个角色、
    同一份事实）。两次都过 `split_facts`、各自造一份注册表 —— 只共享静态事实。
    """
    for role in sorted(AP.ROLE_BRIEFS):
        first = AP.system_prompt(role, registry=registry, **PS.split_facts(_JOB_A)[0])
        second = AP.system_prompt(role, registry=registry, **PS.split_facts(_JOB_A)[0])
        assert first == second, f"{role}：同一份事实渲染两次不同（{PS.stability_problem(first, second)}）"


# ---------------------------------------------------------------- 3. 事实还在，只是换了位置

def test_every_cross_run_fact_is_registered_and_moved_out_of_the_system(registry: Any) -> None:
    """判据 ③（其一）：十格**一个不少**地登记着，且 `split_facts` 真的把它们挪走了。

    两半都要判：
    - "登记了" —— 名字在 `STEP_VOLATILE_FACTS` 里（否则 `split_facts` 不会动它）；
    - "挪走了" —— 进 system 那一份里它被换成了替身（不是原值）。
    """
    system_facts, moved = PS.split_facts(_JOB_A)
    for key in _CROSS_RUN_KEYS:
        assert key in PS.STEP_VOLATILE_FACTS, (key, sorted(PS.STEP_VOLATILE_FACTS))
        assert key in moved, (key, sorted(moved))
        assert moved[key] == _JOB_A[key], (key, moved[key])
        assert system_facts[key] == PS.SYSTEM_PLACEHOLDERS[key], (key, system_facts[key])
        assert system_facts[key] != _JOB_A[key], (key, system_facts[key])


def test_the_opening_user_message_still_carries_every_moved_fact(tmp_path: pathlib.Path) -> None:
    """判据 ③（其二，**最重要的一条**）：事实还在，只是换了位置。

    不靠"读源码觉得它在那儿"，而是**跑一趟真的循环**，从两个地方取读数：
    - user 消息：`gateway.prompts[0]`（真正发给模型的第一条 user）；
    - 事实原值：`agent_run_start.opening_facts`（这一趟开始那一刻的快照）；
    - system：`gateway.systems[0]`。

    逐格断言：原值在 user 里、不在 system 里。**没有这一条**，"为了命中率把信息删掉"
    也能让上面那些判据全绿 —— 那正是这一批最危险的走法。
    """
    st, cond, reg, _gw, root = _wired(tmp_path, {"M": [
        json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)]}, max_steps=2)
    gateway = _BytesGateway(gateway_replies=[
        json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)])
    sid = "t-cross-facts"
    run = run_role("M", "核一条引文是否逐字存在", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gateway, sid=sid),
                   workspace_root=str(root), sid=sid, from_env=False)
    assert run.stop_reason == "final", run.to_dict()
    assert gateway.systems and gateway.prompts, (gateway.systems, gateway.prompts)
    system, prompt = gateway.systems[0], gateway.prompts[0]

    from agentflow import sessions as SS

    events, problems = SS.read_session(root, sid=sid)
    assert not problems, problems
    starts = [e for e in events if e.get("kind") == "agent_run_start"]
    assert starts, "这一趟没有 agent_run_start ⇒ 事实的原值没处读"
    facts = dict(starts[-1].get("opening_facts") or {})
    assert set(facts) == set(OPENING_FACT_KEYS), (sorted(facts), sorted(OPENING_FACT_KEYS))

    # 每一格：user 消息里有它（按它在对面那句话里的**原话**找），system 里没有。
    checks = {
        "task": (f"你的任务：{facts['task']}", f"这一次的任务：\n{facts['task']}"),
        "inbox": (f"你的收件箱：{facts['inbox']}", f"你收到的留言（可能为空）：\n{facts['inbox']}"),
        "board": (f"挂在你名下的工作项（板；可能为空）：{facts['board']}",
                  f"挂在你名下的工作项（板；可能为空）：\n{facts['board']}"),
        "children": (f"这是这一趟开始那一刻的快照）：{facts['children']}",
                     f"要看活的用 `{{\"roster\": {{\"of\": \"self\"}}}}`）：{facts['children']}"),
        "user_replies": (f"用户回答过的问题（含迟到送达的回答）：{facts['user_replies']}",
                         f"用户回答过的问题（含迟到送达的回答）：\n{facts['user_replies']}"),
        "summoned_by": (f"由 {facts['summoned_by']} 发起",
                        f"你这次是被 {facts['summoned_by']} 唤起"),
        "task_id": (f"台账号 {facts['task_id']}", f"台账号为 {facts['task_id']}"),
        "depth": (f"召唤链深度 {facts['depth']}", f"在召唤链上的深度是 {facts['depth']}"),
        "parent_task_id": (f"父代理台账号：{facts['parent_task_id']}",
                           f"你的父代理台账号：{facts['parent_task_id']}"),
        "workspace_root": (f"工作区根目录：{facts['workspace_root']}",
                           f"- 工作区根目录：{facts['workspace_root']}"),
    }
    assert set(checks) == set(_CROSS_RUN_KEYS), (sorted(checks), sorted(_CROSS_RUN_KEYS))
    missing: list[str] = []
    leaked: list[str] = []
    for key, (in_user, in_system) in checks.items():
        if in_user not in prompt:
            missing.append(f"{key}（在 user 消息里找不到 {in_user!r}）")
        if in_system in system:
            leaked.append(f"{key}（还在 system 里：{in_system!r}）")
    assert not missing, "这些事实从 system 挪走之后**没有**出现在 user 消息里（信息被删）：" + "；".join(missing)
    assert not leaked, "这些事实**还在** system 里 ⇒ 前缀仍然跨不过 run：" + "；".join(leaked)
    # 反真空：system 里确实有替身指路语（不是"整段被删光了"）。
    assert "见本次对话第一条消息" in system, system[:400]


def test_deleting_one_fact_from_the_user_message_makes_the_criterion_red(
        tmp_path: pathlib.Path) -> None:
    """负控（③ 的牙）：把某一格**整段删掉** ⇒ 同一个读法必红。

    怎么造"删掉"：把那一格喂成空串 —— `prompt_facts` 会把它换成缺省句，于是
    原值不再出现在 user 消息里（这正是"挪走之后又悄悄删掉"的形态）。
    这条负控必须比"信息还在"那条更强：它证明后者读的是**原值**，不是"有一句人话"。
    """
    facts = {
        "task": "把这一件活做完", "inbox": "（没有收到留言）", "board": "- [i-1] 一条板项",
        "children": "- B1（working）", "user_replies": "- [q-1] 问：… → 答：…",
        "summoned_by": "M", "task_id": "t-0009", "depth": 2,
        "parent_task_id": "t-0008", "workspace_root": "D:/ws",
    }
    opening = _opening_transcript(**facts)
    assert facts["board"] in opening      # 正控：先确认它在
    poisoned = dict(facts, board="")      # 负控：整段删掉
    assert facts["board"] not in _opening_transcript(**poisoned), (
        "把 board 清空之后 user 消息里还读得到它 ⇒ 这条负控没删到东西")


# ---------------------------------------------------------------- 读数面（真机）

def _load_warm() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_warm_prompt_cache_cross_run", _REPO / "scripts" / "warm_prompt_cache.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cross_run_problem(cross: list[Mapping[str, Any]], *, floor: float = 0.90) -> str:
    """`cross_run_hit` 那两行合不合格（空串 = 合格）。判据本体只这一处。

    口径：两行都是"**另一趟活**的 system"（不同 `task` / `task_id` / `depth` /
    `workspace_root`）—— 第一行是它第一次见，第二行是同一份再发一次。
    改前：`0 / 满`；改后：两行都该 ≥ `floor`。
    """
    if not cross or len(cross) != 2:
        return f"跨 run 探针该有 2 行（第一次见 / 第二次见），实得 {cross!r}"
    first, second = cross[0], cross[1]
    for tag, got in (("第一次见", first), ("第二次见", second)):
        tokens = int(got.get("tokens_in") or 0)
        hit = int(got.get("hit") or 0)
        if not tokens:
            return f"{tag}：tokens_in=0 ⇒ 这一格没量到"
        rate = hit / tokens
        if hit <= 0:
            return f"{tag}：hit=0（miss={got.get('miss')}）⇒ 换一趟活的前缀没命中"
        if rate < floor:
            return (f"{tag}：命中率 {rate * 100:.1f}% < {floor * 100:.0f}%"
                    f"（hit {hit} / tokens_in {tokens}）⇒ 前缀里还有跨 run 会变的东西")
    return ""


def test_the_recorded_cross_run_probe_reuses_the_prefix() -> None:
    """判据 ①（读数面）：真机上"另一趟活"的 system **两次都 ≥90% 命中**。

    读数由 `scripts/warm_prompt_cache.py --probe-cross-run <角色>` 产出（它把另一份
    事实的 system 连发两次）。这一条**只读读数**，不联网、不花钱 —— 与
    `tests/test_prompt_cache_warm.py` 的分工：那边判"读数自洽/新鲜"，
    这里判"换一趟活到底命中多少"。
    """
    if not _READINGS.is_file():
        pytest.skip(f"读数不在盘上：{_READINGS}")
    runs = _load_warm().load_readings(_READINGS)
    probes = [r for r in runs if r.get("cross_run_hit")]
    assert probes, "读数里一次跨 run 探针都没有 ⇒ 这一格没量（不是'合格'）"
    cross = list(probes[-1]["cross_run_hit"])
    problem = _cross_run_problem(cross)
    assert problem == "", problem
    # 计数器口径也要自洽：hit + miss == tokens_in（上游两格与 prompt_tokens 该相等）。
    for got in cross:
        assert int(got["hit"]) + int(got["miss"]) == int(got["tokens_in"]), got
    # 落盘的那一格 `cross_run_prefix_chars` 必须等于整份 system 的长度（离线读数）。
    rows = [r for r in probes[-1]["rows"] if int(r.get("pass") or 1) in (4, 5)]
    assert rows, probes[-1].get("rows")
    for row in rows:
        assert int(row["cross_run_prefix_chars"]) == int(row["system_chars"]), (
            f"跨 run 可复用前缀只有 {row['cross_run_prefix_chars']} / 整份 "
            f"{row['system_chars']} 字符 ⇒ system 里还有跨 run 会变的东西")


def test_setting_the_recorded_cross_run_hit_to_zero_makes_the_criterion_red() -> None:
    """负控（① 的读法）：把读数里的 `hit` 改成 0 ⇒ 同一个判据必须红。

    守的是"这个数字真的在被读"：判据若把 `hit` 折掉（或只判 `tokens_in` 非零），
    改成 0 也照样绿 —— 而"换一趟活的第一次调用命中 0"正是这一批要修掉的那个数。
    """
    if not _READINGS.is_file():
        pytest.skip(f"读数不在盘上：{_READINGS}")
    runs = _load_warm().load_readings(_READINGS)
    probes = [r for r in runs if r.get("cross_run_hit")]
    assert probes, "读数里没有跨 run 探针 ⇒ 这条负控没有素材"
    cross = [dict(got) for got in probes[-1]["cross_run_hit"]]
    assert _cross_run_problem(cross) == "", _cross_run_problem(cross)
    poisoned = [dict(cross[0], hit=0), dict(cross[1])]
    assert _cross_run_problem(poisoned), "把第一次见的 hit 改成 0 之后仍判合格 ⇒ 判据没在读那个数"
    poisoned_both = [dict(cross[0], hit=0), dict(cross[1], hit=0)]
    assert "hit=0" in _cross_run_problem(poisoned_both), poisoned_both


# ---------------------------------------------------------------- 夹具：记 system/user 的替身

class _BytesGateway:
    """照剧本回答、并把**两条消息**分别记下来的替身模型（不联网）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, *, gateway_replies: list[str]) -> None:
        self.replies = list(gateway_replies)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        self.systems.append(system or "")
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "cache_hit_tokens": None, "cache_miss_tokens": None,
                                  "error_detail": "", "error_kind": "", "reasoning": "",
                                  "tool_calls": (), "attempts": 1})()
