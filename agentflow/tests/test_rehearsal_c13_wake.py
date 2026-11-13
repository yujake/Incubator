# -*- coding: utf-8 -*-
"""彩排 C13：唤醒链 —— M 的 block 行 / 逐条审批唤醒 / 待用户答那一条。

## 这一条链的业主口径

「直接读 block 表，并将自动审计工具和 block 表结合起来做自动的逐个审批唤醒工具」
（2026-10-29，逐字）。本文件把这条链整条真跑：

```text
block 写入（真生产者 stopctl.block_remaining_tasks）
  → 唤醒条件检查（逐条审批 approve="yes" / 用户答没答）
  → 满足 ⇒ M 那一行被 wake_on_lifeline 叫醒、板项 block → queued
  → 不满足 ⇒ 一个字节都不写、一次都不叫
```

另有一条「待用户答」的唤醒条件（业主 2026-10-19 的 `ask_user → answer → 续跑`）：
`autonomy._stop_before_round` 是"下一轮开不开"的唯一判据 —— 问题还挂着 ⇒ 停
（不叫醒），答过了 ⇒ 放行（继续）。它今天没有自动"叫醒"线程，只有 `--resume` 那一趟
重新开轮，所以这里钉的是那个判据的读数，不是编一个自动唤醒。

## 终态断言（盘上可查，不看返回值好看）

| 判据 | 盘上/台账上的终态 |
|---|---|
| `test_c13_a_real_block_gate_holds_until_it_is_approved` | 未批准：`tasks.json` 逐字节不变、`calls == []`；批准后：板项 `item_state="queued"`、`status` 仍是 `block`（执行侧翻）、`inputs` 多一条 `wake:` 落痕、`S.Task.validate()` 通过 |
| `test_c13_b_the_same_owner_is_woken_exactly_once` | 第二次调用 ⇒ `nothing` / `not_blocked`，`wake:` 落痕不翻倍、`calls` 不增长 |
| `test_c13_c_a_retired_owner_is_never_woken` | 真销号之后 ⇒ `skip/retired`，`calls == []` |
| `test_c13_d_the_user_answer_is_the_wake_condition` | 问题挂着 ⇒ `_stop_before_round` 返回 `waiting_for_user`；答过 ⇒ 空串（可继续）；回答文本真的被续跑读到 |
| `test_c13_e_the_real_producer_makes_the_row_the_reader_picks_up` | 真 `stopctl.block_remaining_tasks` 造的两根轴都被读到 |

## 反真空（每条都自带负控）

1. 不满足不叫醒：未批准那一趟 `calls == []`、`tasks.json` 前后逐字节一致；
2. 条件打桩成"没满足"：把 `wake_on_lifeline` 打桩成恒 `started=False` ⇒ 板项
   会被直写成 `queued`，但回执必须是 `wake_failed`（不是"已叫起"）—— 这一格钉的是
   "写进去"与"叫起来"是两件事；
3. 用户答打桩：把待答清单打桩成"永远挂着" ⇒ `_stop_before_round` 必须仍返回
   `waiting_for_user`，`test_..._d` 的"答过就放行"断言当场红。

## 零模型

全部 tmp 工作区；`wake_on_lifeline` 下游的 `resume_runner` 是记账替身（生产里由
`host.wired_conductor` 接上），真实产出侧 `stopctl` / `Conductor.wake_blocked` /
`autonomy._stop_before_round` / `userio` 一个都没替。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

import pytest

from agentflow import autonomy as AU
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import stopctl as SC
from agentflow import userio as U
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"

#: 回执顶层键集（与 `Conductor.wake_blocked` 的 docstring 同形同集）。
RECEIPT_KEYS = {"checked", "state", "items", "count", "requested", "reason"}
#: 逐项键集（逐项同形同集）。
ITEM_KEYS = {"item_id", "task_id", "owner", "verdict", "started",
             "refusal_code", "why", "mark"}


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path, name: str) -> dict[str, Any]:
    """一个工作区 ＋ 真 conductor ＋ 真秘书 ＋ 记账式执行侧。"""
    root = tmp_path / name
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = SEC.Secretary("M", root=root, store=store, enable_model=False)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上；销号闸读的 `cond.secretary` 也是它。
    cond.roster_sink = sec
    cond.secretary = sec
    calls: list[str] = []
    plan: dict[str, bool] = {}

    def _runner(tid: str, **_kw: Any) -> dict[str, Any]:
        calls.append(str(tid))
        if plan.get(str(tid), True):
            return {"started": True, "task_id": str(tid), "reason": "夹具：叫起来了"}
        return {"started": False, "task_id": str(tid), "reason": "夹具：执行侧起不来"}

    cond.resume_runner = _runner
    boss = str(cond.open_top_level_run("M", "夹具：C13 唤醒链"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "boss": boss,
            "calls": calls, "plan": plan}


def _agent(cond: Conductor, parent: str, *, role: str = "M",
           status: str = "running") -> str:
    """一条代理行（`kind` 空 = 实例行）。C13 要唤醒的是 M 那一行。"""
    row = {"role": role, "action": "run", "called_by": "M",
           "parent_task_id": parent, "depth": 2,
           "input_key": f"agent:{role}:{status}:c13",
           "status": status, "outcome": None, "refusal_reason": None, "instance": "",
           "detail": "夹具：C13 的 M 行", "error": None, "started_at": TS,
           "ended_at": (TS if status in ("done", "cancelled", "failed", "block") else None),
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return str(cond._write_new_row(row, note="fixture:c13"))


def _rows(env: Mapping[str, Any]) -> dict[str, dict]:
    return {str(r.get("task_id")): r for r in env["store"].rows("tasks")}


def _tasks_bytes(env: Mapping[str, Any]) -> bytes:
    return (pathlib.Path(str(env["root"])) / "data" / "tasks.json").read_bytes()


def _shapes(got: Mapping[str, Any]) -> list[str]:
    """回执的形状问题；空表 = 形状对（逐项同形同集，一份实现）。"""
    problems: list[str] = []
    if set(got) != RECEIPT_KEYS:
        problems.append(f"回执顶层键集不对：多 {sorted(set(got) - RECEIPT_KEYS)}、"
                        f"少 {sorted(RECEIPT_KEYS - set(got))}")
    if got.get("state") not in ("woken", "refused", "nothing", "unknown"):
        problems.append(f"state 落在四档之外：{got.get('state')!r}")
    for i, cell in enumerate(got.get("items") or ()):
        if set(cell) != ITEM_KEYS:
            problems.append(f"第 {i} 项键集不对：多 {sorted(set(cell) - ITEM_KEYS)}、"
                            f"少 {sorted(ITEM_KEYS - set(cell))}")
        if not str(cell.get("why") or "").strip():
            problems.append(f"第 {i} 项没有 why：{cell}")
    return problems


def _one(got: Mapping[str, Any], item: str) -> dict:
    return {str(c.get("item_id")): c for c in (got.get("items") or ())}[item]


def _block_owner_and_item(env: Mapping[str, Any], *, owner_status: str = "running"
                          ) -> tuple[str, str]:
    """真生产者造 block：M 行 ＋ 它名下的板项一起翻成 block（两根轴）。"""
    cond = env["cond"]
    owner = _agent(cond, str(env["boss"]), role="M", status=owner_status)
    item = cond.open_item(kind="delegation", role="D", expects="work",
                          action="write_report", summary="夹具：C13 停下来的活",
                          parent_task_id=owner, depth=3,
                          input_key=f"item:{owner}:c13")
    got = SC.block_remaining_tasks(env["store"], task_id=owner,
                                   why="夹具：budget 到顶，这活停在这里")
    assert got.get("checked") is True, got
    rows = _rows(env)
    assert str((rows.get(owner) or {}).get("status")) == "block", rows.get(owner)
    assert str((rows.get(item) or {}).get("item_state")) == "block", rows.get(item)
    return owner, item


# ====================================================================== a：条件不满足
def test_c13_a_a_real_block_gate_holds_until_it_is_approved(
        tmp_path: pathlib.Path) -> None:
    """block 写入 → 未批准不叫醒 → 批准后 M 被叫醒、板项翻 queued。"""
    env = _workspace(tmp_path, "c13a")
    owner, item = _block_owner_and_item(env)
    before = _tasks_bytes(env)

    preview = env["cond"].wake_blocked(approve="", dry_run=False)
    problems = _shapes(preview)
    cell = _one(preview, item)
    if cell.get("verdict") != "skip" or cell.get("refusal_code") != "not_approved":
        problems.append(f"未批准该判 skip/not_approved，实际 "
                        f"{cell.get('verdict')!r}/{cell.get('refusal_code')!r}")
    if env["calls"]:
        problems.append(f"未批准也叫了人：calls={env['calls']}")
    if _tasks_bytes(env) != before:
        problems.append("未批准动了盘：tasks.json 前后不是逐字节一致")
    if not problems:
        # 批准之后：直写板项 + 叫醒 owner（这里 owner 就是 M 那一行）。
        got = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
        problems += _shapes(got)
        cell = _one(got, item)
        if got.get("state") != "woken" or got.get("count") != 1:
            problems.append(f"批准后该 state=woken/count=1，实际 "
                            f"{got.get('state')!r}/{got.get('count')!r}")
        if cell.get("started") is not True:
            problems.append(f"批准后该叫起来：started={cell.get('started')!r}")
        if env["calls"] != [owner]:
            problems.append(f"叫的该是 owner（M 那一行，不是板项号）：calls={env['calls']}")
        row = _rows(env).get(item) or {}
        if str(row.get("item_state")) != "queued":
            problems.append(f"板项该翻成 queued，实际 {row.get('item_state')!r}")
        if str(row.get("status")) != "block":
            problems.append(f"status 该留给执行侧（仍 block），实际 {row.get('status')!r}")
        marks = [str(x) for x in (row.get("inputs") or [])]
        if not any(x.startswith("wake:") for x in marks):
            problems.append(f"inputs 里没有 wake: 落痕：{marks}")
        try:
            S.Task(**{k: v for k, v in row.items()
                      if k in S.Task.__dataclass_fields__}).validate()
        except ValueError as exc:
            problems.append(f"直写后的行不合法：{exc}")
        owner_row = _rows(env).get(owner) or {}
        if str(owner_row.get("status")) != "block":
            problems.append(f"owner 那一行的 status 不该被本层改：{owner_row.get('status')!r}")
    assert problems == [], problems


# ====================================================================== b：幂等
def test_c13_b_the_same_owner_is_woken_exactly_once(tmp_path: pathlib.Path) -> None:
    """叫醒之后再调两趟 ⇒ `nothing` / `not_blocked`，落痕不翻倍、不再叫人。"""
    env = _workspace(tmp_path, "c13b")
    owner, item = _block_owner_and_item(env)
    first = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    assert first.get("state") == "woken", first
    assert env["calls"] == [owner], env["calls"]
    marks = [str(x) for x in ((_rows(env).get(item) or {}).get("inputs") or [])]
    before_calls = list(env["calls"])

    again = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    problems = _shapes(again)
    cell = _one(again, item)
    if cell.get("verdict") != "skip" or cell.get("refusal_code") != "not_blocked":
        problems.append(f"第二次该判 skip/not_blocked，实际 "
                        f"{cell.get('verdict')!r}/{cell.get('refusal_code')!r}")
    sweep = env["cond"].wake_blocked(approve="yes", dry_run=False)
    problems += _shapes(sweep)
    if sweep.get("state") != "nothing":
        problems.append(f"扫全表那一趟该 state=nothing，实际 {sweep.get('state')!r}")
    if env["calls"] != before_calls:
        problems.append(f"第二次又叫了人：{env['calls']}")
    after_marks = [str(x) for x in ((_rows(env).get(item) or {}).get("inputs") or [])]
    if len(after_marks) != len(marks):
        problems.append(f"wake: 落痕翻倍了：{marks} → {after_marks}")
    assert problems == [], problems


# ====================================================================== c：已销号
def test_c13_c_a_retired_owner_is_never_woken(tmp_path: pathlib.Path) -> None:
    """真销号之后 ⇒ `skip/retired`，`calls == []`（彻底没有了，叫不醒）。"""
    env = _workspace(tmp_path, "c13c")
    owner, item = _block_owner_and_item(env)
    # 真销号：名册登记 → `Secretary.retire`（销号名单由生产者写）。
    added = env["sec"].roster_add(owner=str(env["boss"]), role="M",
                                  task_id=owner, brief="C13 夹具")
    assert not added.get("problem"), added
    retired = env["sec"].retire(owner=str(env["boss"]),
                                name=str(added.get("name") or ""),
                                reason="夹具：M 这一支收口")
    assert retired.get("ok") is True and retired.get("action") == "retired", retired

    got = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    problems = _shapes(got)
    cell = _one(got, item)
    if cell.get("verdict") != "skip" or cell.get("refusal_code") != "retired":
        problems.append(f"已销号的 owner 该判 skip/retired，实际 "
                        f"{cell.get('verdict')!r}/{cell.get('refusal_code')!r}"
                        f"（why={cell.get('why')!r}）")
    if env["calls"]:
        problems.append(f"已销号还被叫起来：calls={env['calls']}")
    assert problems == [], problems


# ====================================================================== 反真空
def test_c13_d_wake_failure_is_reported_as_wake_failed(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空①：把 `wake_on_lifeline` 打桩成恒失败 ⇒ 不许报"已叫起"。

    直写与唤醒是两步：板项会被翻成 `queued`，但回执必须是 `wake_failed` ——
    这一格钉的是"写进去"与"叫起来"是两件事（改前一处写死 `started=True` 就会绿）。
    """
    env = _workspace(tmp_path, "c13d")
    owner, item = _block_owner_and_item(env)
    monkeypatch.setattr(type(env["cond"]), "wake_on_lifeline",
                        lambda self, task_id: {"started": False, "task_id": str(task_id),
                                               "reason": "打桩：执行侧起不来"})
    got = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    problems = _shapes(got)
    cell = _one(got, item)
    if cell.get("started") is not False:
        problems.append(f"打桩失败后 started 该是 False，实际 {cell.get('started')!r}")
    if cell.get("refusal_code") != "wake_failed":
        problems.append(f"打桩失败后该点名 wake_failed，实际 {cell.get('refusal_code')!r}")
    if got.get("state") != "refused":
        problems.append(f"一条都没叫起来时 state 该是 refused，实际 {got.get('state')!r}")
    if str((_rows(env).get(item) or {}).get("item_state")) != "queued":
        problems.append("直写那一步仍应落盘（queued）：失败的是唤醒，不是写")
    assert problems == [], problems


# ====================================================================== e：用户答
def test_c13_e_the_user_answer_is_the_wake_condition(tmp_path: pathlib.Path) -> None:
    """「待用户答」那一条：问题挂着 ⇒ 不叫醒；答过 ⇒ 放行、回答真的进续跑。

    真入口：`userio.ask_user` / `userio.answer_question`（CLI 的两个写口）＋
    `autonomy._stop_before_round`（下一轮开不开的唯一判据）＋
    `autonomy._latest_user_answer`（--resume 读回答的唯一读口）。
    """
    root = tmp_path / "c13e"
    root.mkdir()
    asked = U.ask_user(root, role="M", question="「审」还是「研」？", timeout_sec=0.0,
                       qid="q0001")
    problems: list[str] = []
    if asked.qid != "q0001" or asked.problem != "user_no_answer":
        problems.append(f"问题没落成待答：qid={asked.qid!r} problem={asked.problem!r}")
    pending = U.pending_questions(root, sid=None)
    if [q.qid for q in pending] != ["q0001"]:
        problems.append(f"待答清单该有 q0001，实际 {[q.qid for q in pending]}")

    blocked = AU._stop_before_round(
        1, rounds=9, spent_usd=0.0, usd_budget=None, stop_path=None,
        user_answer="", last_stop_reason="waiting_for_user",
        pending_qids=("q0001",))
    if blocked != "waiting_for_user":
        problems.append(f"问题还挂着时下一轮该停（waiting_for_user），实际 {blocked!r}")
    no_answer, _notes = AU._latest_user_answer(root, "M", sid=None)
    if no_answer != "":
        problems.append(f"没答却读出了回答：{no_answer!r}（三态被折平）")

    wrote = U.answer_question(root, qid="q0001", answer="研")
    if wrote != "":
        problems.append(f"回答没写成：{wrote!r}")
    answer, _notes = AU._latest_user_answer(root, "M", sid=None)
    if answer != "研":
        problems.append(f"续跑该读到「研」，实际 {answer!r}")
    allowed = AU._stop_before_round(
        1, rounds=9, spent_usd=0.0, usd_budget=None, stop_path=None,
        user_answer=answer, last_stop_reason="waiting_for_user",
        pending_qids=())
    if allowed != "":
        problems.append(f"答过之后下一轮该放行（空串），实际 {allowed!r}")
    if [q.qid for q in U.pending_questions(root, sid=None)]:
        problems.append("答过之后待答清单该清空")
    assert problems == [], problems


# ====================================================================== 反真空②
def test_c13_f_a_pending_question_still_blocks_the_next_round(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空②：把"待答还在不在"打桩成恒挂着 ⇒ "答过就放行"必须红。

    桩只改一个读数（`pending_questions` 恒非空），不改 `_stop_before_round`；
    若后者不读待答清单、或把"答过"当成默认放行，这一条当场红。
    """
    root = tmp_path / "c13f"
    root.mkdir()
    U.ask_user(root, role="M", question="要不要换来源？", timeout_sec=0.0, qid="q0002")
    U.answer_question(root, qid="q0002", answer="换")
    monkeypatch.setattr(U, "pending_questions",
                        lambda *a, **kw: [object()])
    stop = AU._stop_before_round(
        1, rounds=9, spent_usd=0.0, usd_budget=None, stop_path=None,
        user_answer="换", last_stop_reason="waiting_for_user",
        pending_qids=("q0002",))
    assert stop == "waiting_for_user", (
        "把待答清单打桩成永远挂着之后，下一轮仍然放行 ⇒ "
        f"「答过才放行」不来自那个读数：{stop!r}")


# ====================================================================== 终态读数
def test_c13_g_the_end_state_is_readable_on_disk(tmp_path: pathlib.Path) -> None:
    """终态读数：盘上的那一行能逐格复读（不是靠返回值好看）。"""
    env = _workspace(tmp_path, "c13g")
    owner, item = _block_owner_and_item(env)
    got = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    assert got.get("state") == "woken", got
    raw = json.loads((pathlib.Path(str(env["root"])) / "data" / "tasks.json")
                     .read_text(encoding="utf-8"))
    row = next(r for r in raw["rows"] if str(r.get("task_id")) == item)
    assert str(row.get("item_state")) == "queued", row
    assert str(row.get("item_close")) == "", row
    assert row.get("seen_by") == "" and row.get("seen_step") is None, row
    assert row.get("ended_at") is None and row.get("outcome") is None, row
    assert any(str(x).startswith("wake:") for x in (row.get("inputs") or [])), row
    # 回执与盘上一致：回执里那枚 mark 就是 inputs 里那一行。
    cell = _one(got, item)
    assert cell.get("mark") and cell["mark"] in (row.get("inputs") or []), (
        cell.get("mark"), row.get("inputs"))
    assert cell.get("task_id") == owner, (cell.get("task_id"), owner)
