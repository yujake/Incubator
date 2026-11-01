# -*- coding: utf-8 -*-
"""护栏（162 ①）：趟次读数有「两个」读口，它们必须说同一套话。

## 为什么这条判据必须存在（2026-11-01 实测）

`/api/state` 的 `runs` 走 `webui.state._scan`（A 线手抄的那一份），
`/api/run/{sid}` 的 `runs` 走 `sessions.runs_in_session`（真身）。两份实现是
`state.py:252` 自己承认的"两处同形实现（只改一处等于再造一次『两个读口各说一套』）"。

而「今天没有一条判据抓得住它们分家」：

- 契约 C（`tests/test_webui_contracts.py::_backend_keys`）比的是 `types.ts` 的键
  vs 后端读出来的键的「并集」（`_rows_union`）—— 一路多一格、另一路没有，C 照样全绿；
- `tests/test_webui_readers.py::test_the_run_row_keys_match_what_sessions_computes`
  只测 `run_view` 那一路（它走真身），A 线那一份没有任何键集断言。

于是"只改一路"这种改法在今天的判据网里是「静默」的：同一格在 `/api/state` 上看得见、
在 `/api/run/{sid}` 上看不见，而两个端点都"成功"返回 200。这正是本仓库反复出现的
那一族缺陷（`state.py:252`、`sessions.py:318`）——所以它要有一条判据，而不是一句注释。

## 这条判据钉三件事

1. 「键集合相同」：左右相等，「不是并集」 —— 并集会把"只有一路有"读成"两边都有"；
2. 「逐格值相同」：`runs_in_session` 与 `_scan` 对同一份事件、同一批趟给出同一批数；
3. 「对比器本身不真空」：喂它一个"只改一路"的现场，它必须点名报出来（负控）。

## 豁免哪几格（以及为什么这不是一张白名单）

`_scan` 的产物比"趟次读数"多几格：`orphans` / `orphan_kinds` / `pending` /
`events_seen` / `last_kind` / `last_seq` —— 它们描述的是"这一场会话里「轮次之外」
还有什么"，改前就不属于趟次读数。它们「不在 run 行里」（第 4 条用例钉住这件事），
所以它们是「结构上」落在对比面之外，不是逐格豁免表里的条目。对比面上今天「一格都不豁免」
—— 包括 `usd` / `unknown_usd` / `events_span` / `events_owned` / `task_id`。

## 反真空

第 3 条用例同时守两件事：①正控真的读到了趟（否则"没有问题"只是"没有东西可比"）；
②对比器对三种畸形（一边多一个键 / 一边少一个键 / 一格值不同）都点名。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import sessions as SS
from agentflow.webui import readers as R
from agentflow.webui import state as W

SID = "s-two-paths"
TS = "2026-11-01T00:00:00+08:00"

#: 逐格对比面上今天「不豁免」任何一格（见模块 docstring 最后一段）。
EXEMPT: frozenset[str] = frozenset()

#: run 行里「不许」出现的"会话状态特有"几格（它们属于 `_scan` 的另外半边）。
STATE_ONLY = ("orphans", "orphan_kinds", "pending", "events_seen", "last_kind", "last_seq")


def two_path_problems(left, right, *, exempt: frozenset[str] = EXEMPT) -> list[str]:
    """两份趟次读数的问题清单（空列表 = 同一套话）。

    为什么把对比抽成一个函数：判据要能对「它自己」做负控（喂畸形输入，看它报不报）。
    一条只能"断言相等"的判据，在两边都读空的时候也是绿的 —— 那不叫一致，叫没比。
    """
    problems: list[str] = []
    if len(left) != len(right):
        problems.append(f"趟数不同：左 {len(left)} 趟 vs 右 {len(right)} 趟")
        return problems
    for i, (a, b) in enumerate(zip(left, right)):
        ka = {str(k) for k in a} - set(exempt)
        kb = {str(k) for k in b} - set(exempt)
        if ka != kb:
            problems.append(
                f"趟#{i + 1}：键集合不同 —— 只在左 {sorted(ka - kb)}，只在右 {sorted(kb - ka)}")
            # 键集不同就不再逐格比：缺的那一格会以"值不同"的样子报第二遍，
            # 让"是形状漂了"与"是数变了"混成一条。
            continue
        for key in sorted(ka):
            if a.get(key) != b.get(key):
                problems.append(f"趟#{i + 1}.{key}：左 {a.get(key)!r} vs 右 {b.get(key)!r}")
    return problems


def _append(root: pathlib.Path, **event) -> None:
    """落一条事件（走 `sessions.append`，不手拼 JSON 行）。"""
    event.setdefault("ts", TS)
    SS.append(root, event, sid=SID)


def _interleaved(root: pathlib.Path, *, with_pending: bool = False) -> pathlib.Path:
    """造一场「多代理共写」的会话：同角色两趟同时开着、空编号调用、没闭合的趟。

    这份夹具是判据的"现场"：改前两处实现都对它给出同一批读数（我实测 78 个真机
    工作区 722 趟零分歧），但它把每一种归属路径都摆了一遍 ——
    `by_tid` / `by_role`（空编号）/ 同角色两趟同时开 / 无收工行 / `usd=None`。
    """
    root.mkdir(parents=True, exist_ok=True)
    # 轮次之前的一条提问（后来被答）——它不是任何一趟的事件
    _append(root, kind="user_question", role="M", qid="q1", text="先问一句")
    _append(root, kind="agent_run_start", role="M", task="父", task_id="t-000001")
    _append(root, kind="agent_step", role="M", shape="fs.write")
    _append(root, kind="llm_call", role="M", task_id="t-000001", usd=0.1, ok=True)
    # 同一个角色两趟同时开着 —— 空编号调用该归谁，两处必须给同一个答案
    _append(root, kind="agent_run_start", role="D", task="子一", task_id="t-000002")
    _append(root, kind="agent_run_start", role="D", task="子二", task_id="t-000003")
    _append(root, kind="llm_call", role="D", task_id="t-000002", usd=0.2, ok=True)
    _append(root, kind="llm_call", role="D", usd=0.3, ok=True)          # 空编号 ⇒ by_role
    _append(root, kind="agent_step", role="D", shape="tool")
    _append(root, kind="llm_call", role="D", task_id="t-000003", usd=0.4, ok=True)
    _append(root, kind="agent_run_end", role="D", task_id="t-000002", stop_reason="final",
            steps=1, spend={"calls": 1, "usd": 0.2, "unknown_usd_calls": 0})
    _append(root, kind="llm_call", role="D", task_id="t-000003", usd=None, ok=False)
    _append(root, kind="agent_run_end", role="D", task_id="t-000003", stop_reason="final",
            steps=1, spend={"calls": 2, "usd": 0.7, "unknown_usd_calls": 1})
    if with_pending:
        # 落在 M 那一趟的区间里，且没人答 ⇒ M 的 stop_reason 空着就成了「停在等用户」
        _append(root, kind="user_question", role="M", qid="q2", text="还等一句")
    _append(root, kind="agent_run_end", role="M", task_id="t-000001",
            stop_reason="" if with_pending else "final", steps=1,
            spend={"calls": 1, "usd": 0.1, "unknown_usd_calls": 0})
    # 没闭合的一趟：end_index=None ⇒ 那一趟按文件尾算，且没有收工行可自报
    _append(root, kind="agent_run_start", role="E", task="没写完", task_id="t-000004")
    _append(root, kind="llm_call", role="E", task_id="t-000004", usd=0.5, ok=True)
    _append(root, kind="user_answer", role="M", qid="q1", text="答了")
    return root


def _two_readings(root: pathlib.Path) -> tuple[list[dict], list[dict]]:
    """同一份盘上事实的两次读：左 = `/api/state` 那一份，右 = `/api/run/{sid}` 那一份。"""
    snap = W.snapshot(root)
    left = [row for row in snap["runs"] if str(row.get("sid") or "") == SID]
    right = R.run_view(root, SID)["runs"]
    return left, right


# ====================================================================== 正控
def test_the_two_readers_of_a_run_row_say_the_same_thing(tmp_path: pathlib.Path) -> None:
    """正控（核心）：同一份事件，两条读口给出同一批键、同一批值。

    这是本轮的护栏：块②③④ 加格/改名都必须「两处一起动」，否则这条会点名说
    "哪一格只在一边"。
    """
    root = _interleaved(tmp_path / "ws")
    left, right = _two_readings(root)
    # 反真空：真的读到了趟（4 趟：M / D / D / E），且两条读口都不是空的
    assert len(left) == 4, left
    assert len(right) == 4, right
    assert two_path_problems(left, right) == [], two_path_problems(left, right)
    # 两趟同角色的归属在这份夹具里真的是"空编号被按 role 塞给最新那趟"：
    # 不钉住这件事，"两边一致"可能只是"两边都没算到"
    d_rows = [row for row in right if row.get("role") == "D"]
    assert sorted(row["llm_calls"] for row in d_rows) == [1, 2], d_rows


def test_the_two_readers_agree_about_a_pending_question_too(tmp_path: pathlib.Path) -> None:
    """正控（待答那一档）：两处对"哪一趟在等哪个问题"也必须同一套。

    这一档的来路改前就不同：`_scan` 吃 `userio.workspace_pending_view`，
    `runs_in_session` 自己扫 `user_question` / `user_answer`。来路不同、读数必须相同。
    """
    root = _interleaved(tmp_path / "ws", with_pending=True)
    left, right = _two_readings(root)
    assert two_path_problems(left, right) == [], two_path_problems(left, right)
    awaiting = [row for row in right if row.get("waiting")]
    assert len(awaiting) == 1 and awaiting[0]["role"] == "M", awaiting
    assert awaiting[0]["waiting_on"] == ["q2"], awaiting[0]["waiting_on"]
    assert awaiting[0]["stop_reason"] == "waiting_for_user", awaiting[0]["stop_reason"]


def test_the_run_row_does_not_carry_the_state_only_columns(tmp_path: pathlib.Path) -> None:
    """结构性豁免：`orphans` / `pending` 那几格「不在」 run 行里（不是白名单豁免掉的）。"""
    root = _interleaved(tmp_path / "ws")
    left, right = _two_readings(root)
    for rows, name in ((left, "state._scan"), (right, "sessions.runs_in_session")):
        for row in rows:
            assert set(STATE_ONLY) & set(row) == set(), (name, sorted(row))


# ====================================================================== 负控
def test_the_comparison_is_not_vacuous(tmp_path: pathlib.Path) -> None:
    """负控（对比器）：三种畸形必须点名，其中"一边多一个键"专打「并集」那一档。

    `_rows_union` 那套判据对"只在一路出现的键"是绿的 —— 那正是今天抓不住
    "只改一路"的原因。这里逐条证明本对比器不是那种判据。
    """
    root = _interleaved(tmp_path / "ws")
    left, right = _two_readings(root)
    assert two_path_problems(left, right) == []

    # ① 一边多一个键（并集判据会绿的现场）
    doctored = [dict(row) for row in right]
    doctored[0] = dict(doctored[0], probe_only=1)
    problems = two_path_problems(left, doctored)
    assert problems and "只在右 ['probe_only']" in problems[0], problems

    # ② 一边少一个键
    doctored = [dict(row) for row in right]
    doctored[1] = {k: v for k, v in doctored[1].items() if k != "usd"}
    problems = two_path_problems(left, doctored)
    assert problems and "只在左 ['usd']" in problems[0], problems

    # ③ 一格值不同（形状一样、数不一样）
    doctored = [dict(row) for row in right]
    doctored[2] = dict(doctored[2], steps=doctored[2]["steps"] + 1)
    problems = two_path_problems(left, doctored)
    assert problems and problems[0].startswith("趟#3.steps"), problems

    # ④ 趟数不同（少一趟 / 多一趟都要报，不是"前 N 趟一样就算过"）
    assert two_path_problems(left, right[:-1]), "少一趟没报"
    assert two_path_problems(left[:-1], right), "少一趟没报（左右对调）"
