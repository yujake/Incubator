# -*- coding: utf-8 -*-
"""block 表 × 自动审计：逐个审批唤醒（业主 2026-10-29）。

业主原话（唯一权威，逐字）：

```
「直接读 block 表，并将自动审计工具和 block 表结合起来做自动的逐个审批唤醒工具」
```

## 为什么需要它（`draft/119` §一/§三 的调查读数，逐条有出处）

```text
· 没有"block 表"：真身是 `tasks` 里两类行的并集 —— `status == "block"` 与
  `item_state == "block"`（`stopctl.block_remaining_tasks` 一次写两根轴）。
· block 既不在 UNFINISHED_STATUSES 也不在 TERMINAL_STATUSES ⇒ 三态把它读成 silent、
  wakeable=true ⇒ 销号门放行（看起来可销），而它其实是"停了、活没做完"。
· block 在状态机里没有出边（ITEM_MOVES 四条全 back）⇒ 醒不过来只能靠直写；
  retire_child 让父去 ack，而 ack 对 block 必被状态机拒 ⇒ 死结。
```

所以这一层是"读 block 行 → 逐条审计 → 批准了才逐条直写并唤醒"。

## 这一份钉住的八件事

| 判据 | 守的是 |
|---|---|
| w1 `test_w1_a_dry_run_writes_nothing_and_wakes_nobody` | `dry_run=True` 只读：`tasks` 前后逐字节一致、wake 一次都没被调（审计照跑） |
| w2 `test_w2_without_the_approval_every_row_is_skipped` | 未批准不动：`approve` 为空 ⇒ 全部 skip，理由点名"没批准"，一个字节都不写 |
| w3 `test_w3_the_three_verdicts_are_not_folded_together` | 三档不许折平：已销号 ⇒ skip；读数没查成 ⇒ review；静默未销号 ＋ 板项未终态 ⇒ resume |
| w4 `test_w4_the_direct_write_leaves_a_legal_row` | 直写后的行仍然合法：两根轴一起翻、`item_close` 仍 ""、`seen_*` 已清、`inputs` 有 `wake:` 落痕、`S.Task.validate()` 通过 |
| w5 `test_w5_one_failed_wake_does_not_swallow_the_other` | 逐条隔离：两条 resume，第一条的唤醒失败 ⇒ 第二条照常被叫，回执分别 `started=True`/`False` |
| w6 `test_w6_an_in_flight_owner_is_skipped_not_started_twice` | 在飞不另起：owner 在飞 ⇒ skip（`refusal_code="in_flight"`），不产生第二个同号循环 |
| w7 `test_w7_waking_the_same_row_twice_is_a_no_op` | 幂等：叫醒之后再调两趟（不给 ids / 给 ids）⇒ `nothing` 与 `skip`/`not_blocked`，一个字节都没写、没再叫人、`wake:` 落痕不翻倍 |
| w8 `test_w8_the_real_producer_makes_rows_the_reader_picks_up` | 读侧与真实生产者的口径：`stopctl.block_remaining_tasks` 造的 block 行（两根轴一起翻）必须被本层读到并唤醒 —— 手搓夹具与真实生产者不许分家 |

w7 / w8 是 2026-10-29 那趟可用性探针（temp 里的脚本，走真 `Store` / 真
`open_item` / 真 `block_remaining_tasks`）的读数补出来的：探针五档 a–e 全绿，但 d
（再调一次）与"真实生产者"这两档此前没有任何判据守着 —— 那种缺口不会让现有 12 条
变红，它只是在实现漂了之后继续绿。

## 反真空（每条判据都自带负控）

w1 的"一个字节都没写"用 `tasks.json` 的字节比；w2 的"没批准"用逐条理由串；w5 把
失败的那一条放在前面（若实现一遇失败就中断，后一条根本不会被叫）；w6 断言
`calls == []`（若实现绕过 `wake_on_lifeline` 自己起循环，这条必红）。三档那一条用
三份夹具分别读出三个不同结论 —— 任何"折平成一档"的实现都会让其中至少一格变红。

## 唤醒只能走 `wake_on_lifeline`

它是唯一带"已销号 / 在飞"双闸的那一层（`wake_on_lifeline` 自己的 docstring 逐字）。
本方法绝不直接调 `resume_dispatched`：那条路没有闸，绕过它就等于允许同号起第二个循环
（业主 2026-10-29 的自我唤醒事故，见 `test_the_wake_does_not_resume_a_running_agent.py`）。
w6 就是这条纪律的判据：owner 在飞时 `calls` 必须是空的。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import clock as CLK
from agentflow import schema as S
from agentflow import stopctl as SC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"

#: 回执顶层要有的那一套键（与 `Conductor.ack_items` 同形：`checked` / `state` /
#: `count` / `requested` / `reason`，外加逐条的那一张 `items`）。
RECEIPT_KEYS = {"checked", "state", "items", "count", "requested", "reason"}

#: 一条回执项要有的那一套键（逐项同形同集：少一个键，读的人就要在两种形状之间猜）。
ITEM_KEYS = {"item_id", "task_id", "owner", "verdict", "started",
             "refusal_code", "why", "mark"}


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path, name: str = "ws") -> dict[str, Any]:
    """一个工作区 ＋ 一个主控 ＋ 一个记着"谁被叫过"的执行侧。

    `resume_runner` 是 `wake_on_lifeline` 下游那一层（生产里由 `host.wired_conductor`
    接上）。这里接一个记账替身，好让判据回答"到底有没有叫、叫的是谁"。
    """
    root = tmp_path / name
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    calls: list[str] = []
    plan: dict[str, bool] = {}

    def _runner(tid: str, **_kw: Any) -> dict[str, Any]:
        calls.append(str(tid))
        if plan.get(str(tid), True):
            return {"started": True, "task_id": str(tid), "reason": "夹具：叫起来了"}
        return {"started": False, "task_id": str(tid), "reason": "夹具：执行侧起不来"}

    cond.resume_runner = _runner
    boss = str(cond.open_top_level_run("M", "夹具：block 表逐个审批唤醒"))
    return {"root": root, "store": store, "cond": cond, "boss": boss,
            "calls": calls, "plan": plan}


def _agent(cond: Conductor, parent: str, *, status: str = "block",
           role: str = "D", what: str = "") -> str:
    """一个代理行（`kind` 空 = 实例行）。

    `status="block"` 就是 `stopctl.block_remaining_tasks` 停下来的那个样子：停在这里、
    没做完，`detail` 必填、`ended_at` 已写。
    """
    row = {"role": role, "action": "write_report", "called_by": "M",
           "parent_task_id": parent, "depth": 2,
           "input_key": f"agent:{role}:{status}:{what or role}",
           "status": status, "outcome": None, "refusal_reason": None, "instance": "",
           "detail": f"夹具代理（{status}{'，' + what if what else ''}）",
           "error": None, "started_at": TS,
           "ended_at": (TS if status in ("done", "cancelled", "failed", "block") else None),
           "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": []}
    return str(cond._write_new_row(row, note="fixture:wake_blocked"))


def _blocked_item(cond: Conductor, owner: str, *, role: str = "D",
                  kind: str = "delegation", expects: str = "work",
                  seen: bool = True, inputs: list[str] | None = None) -> str:
    """一条 block 板项（`status="block"` ＋ `item_state="block"`，两根轴同时停）。

    `seen_by` / `seen_step` 刻意都填上：它们必须被直写清掉，而"要么都在、要么都不在"
    这条配对（`schema.py` 的 `seen_by`/`seen_step` 判据）正是清理时要守住的东西。
    真实历史里 block 行可能带上它们（被渲染过之后才被停掉）。
    """
    row = {"role": role, "action": "write_report", "called_by": owner,
           "parent_task_id": owner, "depth": 3,
           "input_key": f"item:{owner}:{kind}",
           "status": "block", "outcome": None, "refusal_reason": None, "instance": "",
           "detail": "优雅停止（budget）：这活停在这里、没做完",
           "error": None, "started_at": TS, "ended_at": TS,
           "tokens": 0, "usd": 0.0, "artifacts": [],
           "inputs": list(inputs if inputs is not None else ["blocked:fixture@x|夹具"]),
           "kind": kind, "expects": expects, "item_state": "block", "item_close": "",
           "seen_by": (owner if seen else ""), "seen_step": (3 if seen else None),
           "keep_alive": False}
    return str(cond._write_new_row(row, note="fixture:wake_blocked"))


def _retire(cond: Conductor, task_id: str) -> None:
    """把某个号记成"已销号"（秘书那一侧的权威读数，`_is_retired_task` 只读这一格）。"""
    cond.secretary = type("S", (), {"retired_names": {str(task_id): "夹具：已销号"}})()


def _tasks_bytes(env: dict[str, Any]) -> bytes:
    """`tasks.json` 的字节（"一个字节都没写"的唯一硬判据）。"""
    return (pathlib.Path(str(env["root"])) / "data" / "tasks.json").read_bytes()


def _rows(env: dict[str, Any]) -> dict[str, dict]:
    return {str(r.get("task_id")): r for r in env["store"].rows("tasks")}


def _shapes(got: mapping) -> list[str]:
    """回执的形状问题（顶层键集 ＋ 逐项同形同集）。空表 = 形状对。"""
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
        if cell.get("verdict") not in ("resume", "review", "skip"):
            problems.append(f"第 {i} 项的 verdict 落在三档之外：{cell.get('verdict')!r}")
        if not isinstance(cell.get("started"), bool):
            problems.append(f"第 {i} 项的 started 不是布尔：{cell.get('started')!r}")
        if not str(cell.get("why") or "").strip():
            problems.append(f"第 {i} 项没有 why（每一档都要能回答'凭什么'）：{cell}")
    return problems


def _verdicts(got: mapping) -> dict[str, dict]:
    return {str(c.get("item_id")): dict(c) for c in (got.get("items") or ())}


# ====================================================================== w1 只读
def _w1_problems(env: dict[str, Any]) -> list[str]:
    """(w1) 的判据本体：`dry_run=True` 只读不写。"""
    problems: list[str] = []
    owner = _agent(env["cond"], str(env["boss"]))
    item = _blocked_item(env["cond"], owner)
    before = _tasks_bytes(env)
    got = env["cond"].wake_blocked(approve="yes", dry_run=True)
    problems += _shapes(got)
    after = _tasks_bytes(env)
    if before != after:
        problems.append("dry_run=True 写了盘：`tasks.json` 前后不是逐字节一致")
    if env["calls"]:
        problems.append(f"dry_run=True 也叫了人：calls={env['calls']}")
    if int(got.get("count") or 0) != 0:
        problems.append(f"一条都没动，count 该是 0，实际 {got.get('count')!r}")
    if got.get("state") == "woken":
        problems.append("dry_run=True 却报 state='woken'（什么都没写，不许说 woke）")
    cells = _verdicts(got)
    if item not in cells:
        problems.append(f"回执里没有 {item} 这一项：{sorted(cells)}")
    else:
        cell = cells[item]
        if cell.get("verdict") != "resume":
            problems.append(f"dry_run 也要照跑审计：{item} 该判 resume，"
                            f"实际 {cell.get('verdict')!r}（why={cell.get('why')!r}）")
        if cell.get("started") is not False:
            problems.append(f"dry_run 下 started 必须是 False，实际 {cell.get('started')!r}")
        if cell.get("mark"):
            problems.append(f"dry_run 下不许有落痕（mark），实际 {cell.get('mark')!r}")
        if "预览" not in str(cell.get("why") or ""):
            problems.append(f"dry_run 的 why 要写明这是预览：{cell.get('why')!r}")
    row = _rows(env).get(item) or {}
    if str(row.get("status")) != "block" or str(row.get("item_state")) != "block":
        problems.append(f"dry_run 动了那一行：status={row.get('status')!r}、"
                        f"item_state={row.get('item_state')!r}")
    return problems


def test_w1_a_dry_run_writes_nothing_and_wakes_nobody(tmp_path: pathlib.Path) -> None:
    """w1) `dry_run=True` 只读不写：`tasks` 前后逐字节一致、wake 一次都没被调。

    为什么"逐字节"而不是"读出来的行相等"：后者对键序、字段补齐、落痕清空全都无感
    —— 而这一层唯一的危险正是"顺手写了一点"。
    """
    problems = _w1_problems(_workspace(tmp_path, "w1"))
    assert problems == [], problems


# ====================================================================== w2 未批准
def _w2_problems(env: dict[str, Any]) -> list[str]:
    """(w2) 的判据本体：`approve` 为空 ⇒ 全部 skip，理由点名"没批准"。"""
    problems: list[str] = []
    owner = _agent(env["cond"], str(env["boss"]))
    item = _blocked_item(env["cond"], owner)
    for dry in (False, True):
        before = _tasks_bytes(env)
        got = env["cond"].wake_blocked(dry_run=dry)       # approve 缺省 ""
        problems += _shapes(got)
        if before != _tasks_bytes(env):
            problems.append(f"approve 为空（dry_run={dry}）却写了盘")
        if env["calls"]:
            problems.append(f"approve 为空（dry_run={dry}）却叫了人：{env['calls']}")
        if got.get("state") != "refused":
            problems.append(f"approve 为空 ⇒ 一条都没成，state 该是 refused，"
                            f"实际 {got.get('state')!r}")
        cell = _verdicts(got).get(item) or {}
        if cell.get("verdict") != "skip":
            problems.append(f"没批准的那一条该判 skip，实际 {cell.get('verdict')!r}")
        if cell.get("refusal_code") != "not_approved":
            problems.append(f"理由码该是 not_approved，实际 {cell.get('refusal_code')!r}")
        if "没批准" not in str(cell.get("why") or ""):
            problems.append(f"理由没有点名「没批准」：{cell.get('why')!r}")
    row = _rows(env).get(item) or {}
    if str(row.get("status")) != "block" or str(row.get("item_state")) != "block":
        problems.append(f"没批准也动了那一行：status={row.get('status')!r}、"
                        f"item_state={row.get('item_state')!r}")
    return problems


def test_w2_without_the_approval_every_row_is_skipped(tmp_path: pathlib.Path) -> None:
    """w2) 未批准不动：`approve` 为空 ⇒ 全部 skip，理由点名"没批准"。

    两趟都判（`dry_run=False` 与 `True`）：批准是"允不允许按审计结论动作"的令牌，
    不是"要不要真写"的开关 —— 没有令牌的那一趟连"它能唤醒"这个结论都不给，
    因为一张"没批准但可唤醒"的清单等于把绕开批准的路递到调用方手里。
    """
    problems = _w2_problems(_workspace(tmp_path, "w2"))
    assert problems == [], problems


# ====================================================================== w3 三档
def _w3_skip_and_review_problems(env: dict[str, Any]) -> list[str]:
    """(w3 前半) 同一趟里两档同时出现：已销号 ⇒ skip，读数没查成 ⇒ review。

    读数没查成用的是真夹具（把 `out/clock/state.json` 写成半份 JSON，
    与 `test_retire_only_for_the_silent.py` 的 d) 同一手法），不是给判定打桩：
    打桩能证明"这段代码被调用过"，证明不了"盘上读不到时它不会猜"。
    """
    problems: list[str] = []
    dead = _agent(env["cond"], str(env["boss"]))
    _retire(env["cond"], dead)
    gone = _blocked_item(env["cond"], dead)
    live = _agent(env["cond"], str(env["boss"]))
    blind = _blocked_item(env["cond"], live)
    clock_dir = pathlib.Path(str(env["root"])) / "out" / "clock"
    clock_dir.mkdir(parents=True, exist_ok=True)
    (clock_dir / "state.json").write_text("{ 这不是 JSON", encoding="utf-8")
    CLK.reset_books()                      # 让下一次读盘真的去读那份坏文件
    got = env["cond"].wake_blocked(approve="yes", dry_run=True)
    problems += _shapes(got)
    cells = _verdicts(got)
    if dead and str((_rows(env).get(dead) or {}).get("status")) != "block":
        problems.append("已销号那一档不该动行")
    one = cells.get(gone) or {}
    if one.get("verdict") != "skip":
        problems.append(f"已销号 ⇒ skip，实际 {one.get('verdict')!r}（why={one.get('why')!r}）")
    if one.get("refusal_code") != "retired":
        problems.append(f"已销号的理由码该是 retired，实际 {one.get('refusal_code')!r}")
    if "销号" not in str(one.get("why") or ""):
        problems.append(f"已销号的 why 要说明「彻底没有了」：{one.get('why')!r}")
    two = cells.get(blind) or {}
    if two.get("verdict") != "review":
        problems.append(f"读数没查成 ⇒ review（不许猜成 resume / skip），"
                        f"实际 {two.get('verdict')!r}（why={two.get('why')!r}）")
    if two.get("refusal_code") != "unknown_reading":
        problems.append(f"没查成的理由码该是 unknown_reading，实际 {two.get('refusal_code')!r}")
    if "没查成" not in str(two.get("why") or "") and "读不成" not in str(two.get("why") or ""):
        problems.append(f"没查成的 why 要说明「没查成」：{two.get('why')!r}")
    return problems


def _w3_resume_problems(env: dict[str, Any]) -> list[str]:
    """(w3 后半) 静默 ∧ 未销号 ∧ 板项未终态 ⇒ resume（正控）。"""
    problems: list[str] = []
    owner = _agent(env["cond"], str(env["boss"]))
    item = _blocked_item(env["cond"], owner)
    got = env["cond"].wake_blocked(approve="yes", dry_run=True)
    problems += _shapes(got)
    cell = _verdicts(got).get(item) or {}
    if cell.get("verdict") != "resume":
        problems.append(f"静默＋未销号＋板项未终态 ⇒ resume，"
                        f"实际 {cell.get('verdict')!r}（why={cell.get('why')!r}）")
    if cell.get("refusal_code"):
        problems.append(f"resume 那一条不该带理由码：{cell.get('refusal_code')!r}")
    if cell.get("task_id") != owner:
        problems.append(f"要唤醒的那个号该是 {owner}（这一行的 parent），"
                        f"实际 {cell.get('task_id')!r}")
    return problems


def test_w3_the_three_verdicts_are_not_folded_together(tmp_path: pathlib.Path) -> None:
    """w3) 三档不许折平：已销号 ⇒ skip；读数没查成 ⇒ review；静默未销号 ⇒ resume。

    三档在同一份判据里各读一格：任何"折成一档"的实现（全 skip / 全 review / 全 resume）
    都会让其中至少一格变红。这是本仓最贵的一类折叠 —— 把"没查成"折成"可以唤醒"，
    唤醒的是不可逆的第二个同号循环；折成"已销号"，一条真的活就永远没人做了。
    """
    problems = _w3_skip_and_review_problems(_workspace(tmp_path, "w3a"))
    problems += _w3_resume_problems(_workspace(tmp_path, "w3b"))
    assert problems == [], problems


# ====================================================================== w4 直写
def _w4_problems(env: dict[str, Any]) -> list[str]:
    """(w4) 的判据本体：直写之后那一行仍然合法（两根轴一起翻 ＋ 自校）。"""
    problems: list[str] = []
    owner = _agent(env["cond"], str(env["boss"]))
    item = _blocked_item(env["cond"], owner)
    got = env["cond"].wake_blocked(approve="yes", dry_run=False)
    problems += _shapes(got)
    cell = _verdicts(got).get(item) or {}
    if cell.get("started") is not True:
        problems.append(f"批准之后要真的叫起来：started={cell.get('started')!r}、"
                        f"why={cell.get('why')!r}")
    if env["calls"] != [owner]:
        problems.append(f"叫的必须是「要唤醒的那个号」（{owner}），不是板项号："
                        f"calls={env['calls']}")
    row = _rows(env).get(item) or {}
    if str(row.get("status")) != "block":
        problems.append(f"status 这一幕不许动（业主自查实测：先写 running 会让唤醒闸门判 in_flight，"
                        f"一条都叫不起来）实际 {row.get('status')!r}")
    if str(row.get("item_state")) != "queued":
        problems.append(f"item_state 该由 block 翻成 queued（渲染只认 queued），"
                        f"实际 {row.get('item_state')!r}")
    if row.get("item_close") != "":
        problems.append(f"block / queued 行的 item_close 必须是空串，实际 {row.get('item_close')!r}"
                        "（schema：item_close 只在 item_state='done' 时有意义）")
    if row.get("seen_by") != "" or row.get("seen_step") is not None:
        problems.append(f"seen_by / seen_step 要一并清空（要么都在、要么都不在），"
                        f"实际 {row.get('seen_by')!r} / {row.get('seen_step')!r}")
    if row.get("ended_at") is not None:
        problems.append(f"翻回 running 必须清掉 ended_at（终态先到先得的反方向），"
                        f"实际 {row.get('ended_at')!r}")
    if not str(row.get("started_at") or "").strip():
        problems.append("running 行必须有 started_at")
    marks = [str(x) for x in (row.get("inputs") or ())]
    wake_marks = [m for m in marks if m.startswith("wake:")]
    if len(wake_marks) != 1:
        problems.append(f"inputs 里该恰好有一条 wake: 落痕，实际 {wake_marks!r}（全部：{marks}）")
    else:
        mark = wake_marks[0]
        body = mark[len("wake:"):]
        if "@" not in body:
            problems.append(f"落痕缺 @<iso>：{mark!r}")
        else:
            who, _, rest = body.partition("@")
            if not who.strip():
                problems.append(f"落痕缺 <by>（谁批的）：{mark!r}")
            if "|" not in rest:
                problems.append(f"落痕缺 |<why>：{mark!r}")
        if cell.get("mark") != mark:
            problems.append(f"回执里的 mark 要等于写进 inputs 的那一条："
                            f"{cell.get('mark')!r} != {mark!r}")
    if "blocked:fixture@x|夹具" not in marks:
        problems.append(f"旧的 inputs 元素被覆盖掉了（只许追加）：{marks}")
    try:
        S.Task(**row).validate()
    except ValueError as exc:  # pragma: no cover - 红了就是这条判据要说的话
        problems.append(f"直写之后那一行过不了 S.Task.validate()：{exc}")
    return problems


def test_w4_the_direct_write_leaves_a_legal_row(tmp_path: pathlib.Path) -> None:
    """w4) 直写后的行仍然合法：两根轴一起翻、`item_close` 仍 ""、`seen_*` 已清、有落痕。

    为什么两根轴都必须翻：只翻 status，板项仍不渲染（它还是 block）；只翻 item_state，
    "已收口"那份读数仍说它 done。为什么必须自己复校一遍：这一层绕开了状态机
    （block 在 ITEM_MOVES 里没有出边），`S.Task.validate()` 是剩下的唯一一道闸。
    """
    problems = _w4_problems(_workspace(tmp_path, "w4"))
    assert problems == [], problems


# ====================================================================== w5 逐条隔离
def _w5_problems(env: dict[str, Any]) -> list[str]:
    """(w5) 的判据本体：第一条的唤醒失败，第二条照常被叫。"""
    problems: list[str] = []
    first_owner = _agent(env["cond"], str(env["boss"]), what="first")
    second_owner = _agent(env["cond"], str(env["boss"]), what="second")
    first = _blocked_item(env["cond"], first_owner)
    second = _blocked_item(env["cond"], second_owner)
    env["plan"][first_owner] = False        # 第一条的唤醒失败
    got = env["cond"].wake_blocked(approve="yes", dry_run=False)
    problems += _shapes(got)
    cells = _verdicts(got)
    order = [str(c.get("item_id")) for c in (got.get("items") or ())]
    if order != sorted([first, second]):
        problems.append(f"回执要逐条给、次序确定（按板项号升序）：{order}")
    one = cells.get(first) or {}
    two = cells.get(second) or {}
    if one.get("started") is not False:
        problems.append(f"唤醒失败的那一条 started 该是 False，实际 {one.get('started')!r}")
    if one.get("refusal_code") != "wake_failed":
        problems.append(f"失败那一条的理由码该是 wake_failed，实际 {one.get('refusal_code')!r}")
    if one.get("verdict") != "resume":
        problems.append(f"审计结论仍是 resume（它确实可唤醒，是执行侧没起来），"
                        f"实际 {one.get('verdict')!r}")
    if two.get("started") is not True:
        problems.append(f"另一条必须照常被叫（失败只影响它自己）：started={two.get('started')!r}、"
                        f"why={two.get('why')!r}")
    if str(two.get("refusal_code") or ""):
        problems.append(f"成功的那一条不该带理由码：{two.get('refusal_code')!r}")
    if sorted(env["calls"]) != sorted([first_owner, second_owner]):
        problems.append(f"两条都得被叫（一条失败不许吞掉另一条）：calls={env['calls']}")
    if int(got.get("count") or 0) != 1:
        problems.append(f"count 数的是真被叫起来的条数，该是 1，实际 {got.get('count')!r}")
    if got.get("state") != "woken":
        problems.append(f"有一条叫起来了 ⇒ state 该是 woken，实际 {got.get('state')!r}")
    rows = _rows(env)
    for iid in (first, second):
        row = rows.get(iid) or {}
        if str(row.get("status")) != "block" or str(row.get("item_state")) != "queued":
            problems.append(f"{iid} 的直写与唤醒是两步：直写只翻 item_state（status 留给执行侧），"
                            f"实际 status={row.get('status')!r}、item_state={row.get('item_state')!r}")
    return problems


def test_w5_one_failed_wake_does_not_swallow_the_other(tmp_path: pathlib.Path) -> None:
    """w5) 逐条隔离：一条唤醒失败 ⇒ 另一条照常被叫，回执分别 `started=True`/`False`。

    失败的那一条刻意排在前面（板项号更小）：若实现"一遇失败就中断整趟"，
    第二条根本不会被叫，`calls` 就只有一条 ⇒ 这条判据当场红。
    """
    problems = _w5_problems(_workspace(tmp_path, "w5"))
    assert problems == [], problems


# ====================================================================== w6 在飞不另起
def _w6_problems(env: dict[str, Any]) -> list[str]:
    """(w6) 的判据本体：owner 在飞 ⇒ skip / in_flight，且一次都不许叫。"""
    problems: list[str] = []
    owner = _agent(env["cond"], str(env["boss"]), status="running")
    item = _blocked_item(env["cond"], owner)
    got = env["cond"].wake_blocked(approve="yes", dry_run=False)
    problems += _shapes(got)
    cell = _verdicts(got).get(item) or {}
    if cell.get("verdict") != "skip":
        problems.append(f"owner 在飞 ⇒ skip，实际 {cell.get('verdict')!r}"
                        f"（why={cell.get('why')!r}）")
    if cell.get("refusal_code") != "in_flight":
        problems.append(f"理由码该是 in_flight，实际 {cell.get('refusal_code')!r}")
    if "在跑" not in str(cell.get("why") or "") and "在飞" not in str(cell.get("why") or ""):
        problems.append(f"why 要点明「它自己在跑」：{cell.get('why')!r}")
    if cell.get("started") is not False:
        problems.append(f"在飞那一档不许 started=True：{cell.get('started')!r}")
    if env["calls"]:
        problems.append(f"owner 在飞 ⇒ 一次都不许叫（那会起第二个同号循环）："
                        f"calls={env['calls']}")
    if (env["cond"].wake_on_lifeline(owner) or {}).get("started") is not False:
        problems.append("负控：`wake_on_lifeline` 在飞那一档本来就该拒 —— 这一格没拒说明"
                        "本判据测的不是那道闸")
    row = _rows(env).get(item) or {}
    if str(row.get("status")) != "block" or str(row.get("item_state")) != "block":
        problems.append(f"在飞那一档一个字节都不许写：status={row.get('status')!r}、"
                        f"item_state={row.get('item_state')!r}")
    if got.get("state") != "refused":
        problems.append(f"一条都没叫起来 ⇒ state 该是 refused，实际 {got.get('state')!r}")
    return problems


def test_w6_an_in_flight_owner_is_skipped_not_started_twice(tmp_path: pathlib.Path) -> None:
    """w6) 在飞不另起：owner 在飞 ⇒ skip（`refusal_code="in_flight"`），不产生第二个循环。

    这条与 `test_the_wake_does_not_resume_a_running_agent.py::s1` 守的是同一件事，
    但对象不同：那条守 `wake_on_lifeline` 自己的闸，这条守"本方法只能经过那道闸"——
    实现若顺手直接调 `resume_dispatched`，`calls` 就不会是空的。
    """
    problems = _w6_problems(_workspace(tmp_path, "w6"))
    assert problems == [], problems


# ====================================================================== 回执形状
def test_the_receipt_is_one_shape_for_every_item(tmp_path: pathlib.Path) -> None:
    """跨档形状一致：同一份回执里 skip / review / resume 三种项必须同一个键集。

    `draft/119` §二逐字：「每项同形同集」—— 键多一个少一个，读的人就要在几种形状
    之间猜，而模型会照着猜出来的形状写下游逻辑。
    """
    env = _workspace(tmp_path, "shape")
    dead = _agent(env["cond"], str(env["boss"]))
    _retire(env["cond"], dead)
    _blocked_item(env["cond"], dead)
    live = _agent(env["cond"], str(env["boss"]))
    _blocked_item(env["cond"], live)
    got = env["cond"].wake_blocked(approve="yes", dry_run=True)
    problems = _shapes(got)
    kinds = {str(c.get("verdict")) for c in (got.get("items") or ())}
    if kinds != {"skip", "resume"}:
        problems.append(f"夹具该读出 skip ＋ resume 两档，实际 {sorted(kinds)}")
    assert problems == [], problems


def test_a_call_with_no_block_rows_says_nothing_not_unknown(tmp_path: pathlib.Path) -> None:
    """负控：板上一条 block 行都没有 ⇒ `state="nothing"` + `checked=True`。

    三态纪律：`nothing`（查过了、没有）与 `unknown`（没查成）不许折平 ——
    折平的代价是"没查成"被读成"板上没事，所以休眠就好"。
    """
    env = _workspace(tmp_path, "empty")
    got = env["cond"].wake_blocked(approve="yes", dry_run=True)
    problems = _shapes(got)
    if got.get("checked") is not True:
        problems.append(f"台账读得成 ⇒ checked 该是 True，实际 {got.get('checked')!r}")
    if got.get("state") != "nothing":
        problems.append(f"没有 block 行 ⇒ state 该是 nothing，实际 {got.get('state')!r}")
    if got.get("items"):
        problems.append(f"没有 block 行 ⇒ 逐条清单该是空的，实际 {got.get('items')!r}")
    if int(got.get("requested") or 0) != 0:
        problems.append(f"没给 ids ⇒ requested 该是 0，实际 {got.get('requested')!r}")
    assert problems == [], problems


def test_the_reader_filters_by_item_state_not_by_status(tmp_path: pathlib.Path) -> None:
    """读侧按 `item_state` 筛，不按 `status`。

    为什么这一条必须有（`draft/119` §二）：`status` 会被单向翻（`done` 之后不再回
    `block`），于是"item_state 早已 done、status 还停着 block"的老板项会混进来 ——
    读它们等于去唤醒一件早就做完了的活。反过来"status=block 但 item_state=queued"
    不是 block 板项（它没被停掉），也不该进这一层。
    """
    env = _workspace(tmp_path, "axis")
    owner = _agent(env["cond"], str(env["boss"]))
    done_item = _blocked_item(env["cond"], owner)
    queued_item = _blocked_item(env["cond"], owner)
    with env["store"].tx("tasks", actor="test") as tx:
        row = dict(tx.find("tasks", task_id=done_item) or {})
        row.update(item_state="done", item_close="completed")
        tx.upsert("tasks", S.Task(**row).to_dict())
        row = dict(tx.find("tasks", task_id=queued_item) or {})
        row.update(item_state="queued")
        tx.upsert("tasks", S.Task(**row).to_dict())
    got = env["cond"].wake_blocked(approve="yes", dry_run=True)
    problems = _shapes(got)
    ids = {str(c.get("item_id")) for c in (got.get("items") or ())}
    if ids:
        problems.append(f"item_state≠block 的行一条都不许进这一层：{sorted(ids)}")
    if got.get("state") != "nothing":
        problems.append(f"没有 block 板项 ⇒ state 该是 nothing，实际 {got.get('state')!r}")
    assert problems == [], problems


def test_the_ids_argument_lands_on_the_named_rows_only(tmp_path: pathlib.Path) -> None:
    """`ids` 点了谁就只审谁：没点到的 block 行一个字节都不动。"""
    env = _workspace(tmp_path, "ids")
    first_owner = _agent(env["cond"], str(env["boss"]), what="named")
    second_owner = _agent(env["cond"], str(env["boss"]), what="unnamed")
    named = _blocked_item(env["cond"], first_owner)
    unnamed = _blocked_item(env["cond"], second_owner)
    got = env["cond"].wake_blocked([named], approve="yes", dry_run=False)
    problems = _shapes(got)
    cells = _verdicts(got)
    if sorted(cells) != [named]:
        problems.append(f"ids 只点了 {named} ⇒ 回执只该有它，实际 {sorted(cells)}")
    if int(got.get("requested") or 0) != 1:
        problems.append(f"requested 该是 1，实际 {got.get('requested')!r}")
    if (cells.get(named) or {}).get("started") is not True:
        problems.append(f"{named} 该被叫起来：{cells.get(named)!r}")
    if env["calls"] != [first_owner]:
        problems.append(f"只许叫点到的那个号：calls={env['calls']}")
    row = _rows(env).get(unnamed) or {}
    if str(row.get("status")) != "block" or str(row.get("item_state")) != "block":
        problems.append(f"没点到的 {unnamed} 一个字节都不许动："
                        f"status (留给执行侧翻) ={row.get('status')!r}、item_state={row.get('item_state')!r}")
    assert problems == [], problems


def test_the_ledger_being_unreadable_is_unknown_not_nothing(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """三态：台账读不成 ⇒ `checked=False` + `state="unknown"`，一个字节都不写。

    这是本仓最贵的一类折叠（把"没查成"折成"没有 block 行"）：折平之后，一次读盘
    失败会让调用方以为"板上没事"，而盘上其实停着一整排没做完的活。
    """
    env = _workspace(tmp_path, "blind")
    owner = _agent(env["cond"], str(env["boss"]))
    _blocked_item(env["cond"], owner)
    before = _tasks_bytes(env)

    def _boom() -> list:
        raise OSError("夹具：台账读不成")

    monkeypatch.setattr(env["cond"], "_tasks", _boom)
    got = env["cond"].wake_blocked(approve="yes", dry_run=False)
    problems: list[str] = []
    if set(got) != RECEIPT_KEYS:
        problems.append(f"回执顶层键集不对：{sorted(got)}")
    if got.get("checked") is not False:
        problems.append(f"读不成 ⇒ checked 该是 False，实际 {got.get('checked')!r}")
    if got.get("state") != "unknown":
        problems.append(f"读不成 ⇒ state 该是 unknown，实际 {got.get('state')!r}")
    if "没查成" not in str(got.get("reason") or ""):
        problems.append(f"reason 要写明「没查成」：{got.get('reason')!r}")
    if got.get("items"):
        problems.append(f"没查成时不许给逐条清单（那是猜）：{got.get('items')!r}")
    if before != _tasks_bytes(env):
        problems.append("没查成时一个字节都不许写")
    if env["calls"]:
        problems.append(f"没查成时不许叫人：calls={env['calls']}")
    assert problems == [], problems


def test_the_json_receipt_survives_a_round_trip(tmp_path: pathlib.Path) -> None:
    """回执要能被序列化出去（工具层第二段会把它当返回值给模型）。

    这一条不测工具壳，只测"这份读数里没有不能出门的对象"（`S.Task` 实例、
    `Path`、异常对象都会在那一层炸掉，而它们是这里最容易顺手塞进去的东西）。
    """
    env = _workspace(tmp_path, "json")
    owner = _agent(env["cond"], str(env["boss"]))
    _blocked_item(env["cond"], owner)
    got = env["cond"].wake_blocked(approve="yes", dry_run=True)
    blob = json.dumps(got, ensure_ascii=False)
    back = json.loads(blob)
    assert set(back) == RECEIPT_KEYS, sorted(back)
    assert isinstance(back["items"], list) and back["items"], back
    for cell in back["items"]:
        assert set(cell) == ITEM_KEYS, sorted(cell)


# ====================================================================== w7 幂等
def _wake_marks(row: mapping) -> list[str]:
    """那一行 `inputs` 里的 `wake:` 落痕（重复写就会多一条）。"""
    return [str(m) for m in (row.get("inputs") or ()) if str(m).startswith("wake:")]


def _w7_problems(env: dict[str, Any]) -> list[str]:
    """(w7) 的判据本体：同一行叫醒两次的第二次必须是空动作。"""
    problems: list[str] = []
    owner = _agent(env["cond"], str(env["boss"]))
    item = _blocked_item(env["cond"], owner)
    first = env["cond"].wake_blocked(approve="yes", dry_run=False)
    problems += _shapes(first)
    first_cell = _verdicts(first).get(item) or {}
    if first_cell.get("started") is not True:
        problems.append(f"正控：第一次该真的叫起来，实际 {first_cell.get('started')!r}"
                        f"（why={first_cell.get('why')!r}）")
    row = _rows(env).get(item) or {}
    if len(_wake_marks(row)) != 1:
        problems.append(f"正控：第一次之后该恰好一条 wake: 落痕，实际 {_wake_marks(row)}")
    calls_after_first = list(env["calls"])
    before = _tasks_bytes(env)
    # 第二趟：不给 ids —— 板上一条 block 行都不剩了
    again = env["cond"].wake_blocked(approve="yes", dry_run=False)
    problems += _shapes(again)
    if again.get("state") != "nothing":
        problems.append(f"叫醒之后再调（不给 ids）该说 nothing（查过了、没有），"
                        f"实际 {again.get('state')!r}（reason={again.get('reason')!r}）")
    if again.get("items"):
        problems.append(f"叫醒之后不该再有逐条清单：{again.get('items')}")
    if int(again.get("count") or 0) != 0:
        problems.append(f"第二趟 count 该是 0，实际 {again.get('count')!r}")
    # 第三趟：点了那条已经叫醒的行 —— 它不是 block 了，逐条该是 skip / not_blocked
    named = env["cond"].wake_blocked([item], approve="yes", dry_run=False)
    problems += _shapes(named)
    cell = _verdicts(named).get(item) or {}
    if cell.get("verdict") != "skip":
        problems.append(f"该行已不是 block 板项 ⇒ 该判 skip，实际 {cell.get('verdict')!r}"
                        f"（why={cell.get('why')!r}）")
    if cell.get("refusal_code") != "not_blocked":
        problems.append(f"理由码该是 not_blocked，实际 {cell.get('refusal_code')!r}")
    if cell.get("started") is not False:
        problems.append(f"不是 block 的那一行不许再叫一次：started={cell.get('started')!r}")
    if cell.get("mark"):
        problems.append(f"不是 block 的那一行不许再落痕：{cell.get('mark')!r}")
    # 三件硬读数：一个字节都没写、没再叫人、落痕不翻倍
    if before != _tasks_bytes(env):
        problems.append("第二、三趟写了盘：`tasks.json` 前后不是逐字节一致")
    if env["calls"] != calls_after_first:
        problems.append(f"第二、三趟又叫了人：{env['calls']}（第一次之后是 {calls_after_first}）")
    row = _rows(env).get(item) or {}
    if len(_wake_marks(row)) != 1:
        problems.append(f"wake: 落痕被重复写了：{_wake_marks(row)}")
    return problems


def test_w7_waking_the_same_row_twice_is_a_no_op(tmp_path: pathlib.Path) -> None:
    """w7) 幂等：叫醒之后再调两趟，第二趟与第三趟都是空动作。

    为什么必须有这一条（2026-10-29 可用性探针 d 档的读数）：回执里的 `state` 说的是
    这一笔有没有叫醒，不是"板上还有没有 block 行"。再调那一趟的实现若把"已经叫醒过"
    读成"还能再叫"，代价是同一行多一条 `wake:` 落痕、再起一个同号循环，而既有 12 条
    判据一条都不会红（它们都只跑一趟）。两档都要判：不给 `ids`（走读侧筛选 ⇒ `nothing`）
    与给 `ids`（走逐条判定 ⇒ `skip`/`not_blocked`）是两条不同的分支。
    """
    problems = _w7_problems(_workspace(tmp_path, "w7"))
    assert problems == [], problems


# ====================================================================== w8 真生产者
def _w8_problems(env: dict[str, Any]) -> list[str]:
    """(w8) 的判据本体：block 行由真实生产者造，本层必须读得到并唤醒。"""
    problems: list[str] = []
    owner = _agent(env["cond"], str(env["boss"]), status="running")
    item = env["cond"].open_item(kind="delegation", role="D", expects="work",
                                 action="write_report", summary="夹具：优雅停止停下来的活",
                                 parent_task_id=owner, depth=3,
                                 input_key=f"item:{owner}:w8")
    # 真实生产者：`stopctl.block_remaining_tasks` 一次写两根轴（status + item_state）
    got = SC.block_remaining_tasks(env["store"], task_id=owner, why="夹具：budget")
    if not got.get("checked"):
        problems.append(f"夹具自己没成立：block_remaining_tasks 没查成（{got.get('reason')!r}）")
    rows = _rows(env)
    if str((rows.get(owner) or {}).get("status")) != "block":
        problems.append(f"夹具自己没成立：owner 那一行该被翻成 block，"
                        f"实际 {(rows.get(owner) or {}).get('status')!r}")
    if str((rows.get(item) or {}).get("item_state")) != "block":
        problems.append(f"夹具自己没成立：板项该被翻成 block，"
                        f"实际 {(rows.get(item) or {}).get('item_state')!r}"
                        f"（blocked_items={got.get('blocked_items')!r}）")
    went = env["cond"].wake_blocked(approve="yes", dry_run=False)
    problems += _shapes(went)
    cell = _verdicts(went).get(item) or {}
    if cell.get("verdict") != "resume":
        problems.append(f"真实生产者造的 block 行必须被读成 resume，实际 "
                        f"{cell.get('verdict')!r}（why={cell.get('why')!r}）")
    if cell.get("started") is not True:
        problems.append(f"它该被叫起来：started={cell.get('started')!r}")
    if env["calls"] != [owner]:
        problems.append(f"叫的该是 owner（不是板项号）：calls={env['calls']}")
    row = _rows(env).get(item) or {}
    if str(row.get("status")) != "block" or str(row.get("item_state")) != "queued":
        problems.append(f"item_state 该翻成 queued、status 留给执行侧："
                        f"{row.get('status')!r}/{row.get('item_state')!r}")
    return problems


def test_w8_the_real_producer_makes_rows_the_reader_picks_up(tmp_path: pathlib.Path) -> None:
    """w8) 读侧与真实生产者同口径：`stopctl.block_remaining_tasks` 造的行必须被读到。

    为什么必须有这一条（2026-10-29 可用性探针的口径）：本文件其余判据的 block 行都是
    手搓的（`_blocked_item` 直接写两根轴）。手搓夹具与真实生产者一旦分家 ——
    比如生产者改了只翻 `status`、不翻 `item_state` —— 本层就静默地一条也读不到，
    而所有手搓夹具的判据照样全绿（它们造的行仍然两根轴都是 block）。这一条把"生产者的
    读数"接进判据：夹具自己先断言 producer 真的造出了 block 行，再断言本层读得到它。
    """
    problems = _w8_problems(_workspace(tmp_path, "w8"))
    assert problems == [], problems

