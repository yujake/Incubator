# -*- coding: utf-8 -*-
"""彩排（真路径）C13 · 多轮驱动里的唤醒：CLI `--rounds 2` → M 在第二轮逐条审批唤醒被 block 的活。

## 这条链钉的是什么

```text
（盘上先有一条被优雅停止停住的活：真生产者 stopctl.block_remaining_tasks 写的 block 行 + 板项）
第 1 轮：M --conductor.wake_blocked(ids=[项], 不带批准)--> 逐条 skip/not_approved，一个字节不写、一次都不叫
第 2 轮：M --conductor.wake_blocked(ids=[项], approve="yes", dry_run=false)--> 板项 block→queued、
         owner 真被叫起来（`resume_runner` = `Conductor.resume_dispatched`：同一个号接着跑）
         再叫一次 --> not_blocked（幂等：不重复叫人）
```

## 与真机差在哪

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research --rounds 2` | 同一行（`cli.main([...])`） |
| 多轮驱动 | `autonomy.run_autonomous`（每轮之间按停机/待答/唤醒判定） | 同一条：两轮都是真 `autonomy` 开的 |
| 唤醒 | M 调 `conductor.wake_blocked`（逐条审批） | 同一条：判定、审计、直写、叫醒全在 `Conductor.wake_blocked` |
| 叫起来的执行侧 | `host` 接 `cond.resume_runner = cond.resume_dispatched` | 同一条：真 `resume_dispatched` 用同一个台账号把 owner 跑起来 |
| 模型缝 / 记账 / 出网 | 真 `LlmSeam` / `TokenMeter` / `urllib_transport` | 只换出网那一处 |
| block 行 | 优雅停止的 `stopctl.block_remaining_tasks` 写的 | 同一条（夹具直接调这个真生产者；"优雅停"那一步由 C12/停机链覆盖） |

旧版（改写前登记在 `CHAIN_ONLY` 里）直调 `Conductor.wake_blocked` 与
私有 `autonomy._stop_before_round` / `_latest_user_answer`，打桩
`Conductor.wake_on_lifeline` 与 `userio.pending_questions`；这一份一处都不换。

## 终态读数（盘上 / 会话里）

- 三次 `wake_blocked` 的回执：第一次逐条 `skip/not_approved`、`started=False`、`state="refused"`、
  盘上零写入；第二次审计判 `resume`、板项 `item_state` 翻成 `queued`、`inputs` 多一条
  `wake:` 落痕，执行侧真的按同号把 owner 跑起来（`started=True`、owner 行
  `done/ok`、被唤醒的 D 有 `agent_run_start` / `agent_run_end`；板项被 D 读到之后
  推进到 `seen`）；第三次该条 `skip/not_blocked`（板项已经不是 block 了）、
  `wake:` 落痕不翻倍。
- 多轮：`--rounds 2` 的两轮都开了（stdout 的「自主跑完 2 轮」＋ 两条 M 的 `agent_run_start`）。
- 钱账干净、全部 `llm_call` 落在本趟 sid。

## 2026-11-16 已修：研究跑的唤醒只写不叫（CC4 缺陷 1）

改前：`start --mode research` 装配的是 `host.wired_llm_conductor`，它没有把
`cond.resume_runner` 接到 `cond.resume_dispatched`（全仓只有 `host.wired_conductor`
那一处接）。于是研究跑里 M 调 `conductor.wake_blocked`：

```text
板项 block → queued（写了）、wake: 落痕（写了）、审计判 resume
但 started=False、refusal_code="wake_failed"、why="这一趟没有接执行侧（resume_runner 未接线）"
```

现在 `wired_llm_conductor` 在换完 backend 之后按 `wired_conductor` 同形接上执行侧；
`Conductor.resume_dispatched` 调 `LlmBackend.call` 时把主控的取消信号 `token` 一并传下去
（不传 ⇒ 第一次唤醒就落 `TypeError: ... missing 'token'`，owner 行 `failed`）。
本文件因此是正控：`started=True` 且 owner 真的跑完。执行侧没接线的反真空在
`tests/test_rehearsal_c13_wake_chain.py::test_without_the_wiring...`（把接线那一格换成
访问即 AttributeError 的 descriptor，不必在产品里留开关）。

## 反真空（同一个工作区里造红）

1. 没批准不动作：第 1 轮那一趟逐条 `skip/not_approved`、`started=False`、盘上零写入、
   零调用 —— 它证明第 2 轮的"直写 + 叫醒"不是恒真，而是压在那张批准令牌上。
2. 幂等：第 2 轮叫两次，第二次 `not_blocked`、`wake:` 落痕不翻倍、不再叫人。

（"叫错对象"那一档由单点判据覆盖；本条链的正控逐格核过两个号不是同一个：回执里
`task_id` 是 owner 的台账号、`item_id` 才是板项号。）

## Lean 与这条链无关（单档说明）

唤醒链不产出手稿、不碰 `formal.*`、不读 Lean 开关的分支（`wake_blocked` 的判定里没有
Lean 那一格）⇒ 只跑关档（`AGENTFLOW_LEAN_ENABLED=0`）。开档多跑一遍只会把同一条
路径再走一次，多不出任何读数；两档的唯一差别是名册里多一个 L，而 L 不在唤醒对象里。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import time
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import pytest

import rehearsal_contract as RC

from agentflow import cli
from agentflow import leanscope as LS
from agentflow import modelgw as MG
from agentflow import stopctl as SC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

SID = "cc4-c13"
TS = "2026-01-01T00:00:00+00:00"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class _Wire:
    """预置的网络传输层替身（只回答"上游收到了什么、回了什么"）。"""

    def __init__(self, *, item_id: str) -> None:
        self.item_id = item_id
        self.bodies: list[dict[str, str]] = []
        self.steps: dict[str, int] = {}
        self.retired: list[str] = []

    def _roster(self, prompt: str) -> list[str]:
        return [n for n in re.findall(r'"roster_name":\s*"([A-Z]\d*)"', prompt)
                if n not in self.retired]

    def _retire_then(self, prompt: str, nxt: str) -> str:
        names = self._roster(prompt)
        if names:
            self.retired.append(names[0])
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": names[0], "reason": "交完了"}})
        return nxt

    def _m(self, index: int, prompt: str) -> str:
        args = {"ids": [self.item_id]}
        if index == 0:
            # 多轮里的 M 不是只做唤醒：它还有个孩子在盯这条被停住的活（真 summon →
            # 真 `LlmBackend.call` → 子循环在 `calling_as` 里花钱；三格的格②由此有对象）。
            return _json({"summon": {"role": "D",
                                     "task": "看一眼被停住的活还在不在，回来报一声"}})
        if index == 1:
            return _json({"tool": "conductor.wake_blocked",
                          "args": dict(args, dry_run=True)})
        if index == 2:
            return self._retire_then(prompt, _json({"final": "第 1 轮：只看不写，不批准"}))
        if index == 3:
            return _json({"final": "第 1 轮：只看不写，不批准"})
        if index in (4, 5):
            return _json({"tool": "conductor.wake_blocked",
                          "args": dict(args, approve="yes", dry_run=False)})
        return _json({"final": "第 2 轮：唤醒完了", "evidence": [self.item_id]})

    def reply(self, *, system: str, prompt: str) -> str:
        head = system.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["彩排"]})
        m = re.match(r"你是 ([A-Z]) 号角色", head)
        if m:
            role = m.group(1)
            index = self.steps.get(role, 0)
            self.steps[role] = index + 1
            if role == "M":
                return self._m(index, prompt)
            if role == "D":
                return _json({"final": "被唤醒的 D 接着跑完了"})
            return _json({"final": f"{role} 收工", "evidence": []})
        return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["彩排"]})

    def __call__(self, url: str, headers: Any, body: bytes,
                 timeout_sec: float) -> tuple[int, str]:
        payload = json.loads(body.decode("utf-8"))
        messages = payload.get("messages") or []
        system = next((str(x.get("content") or "") for x in messages
                       if x.get("role") == "system"), "")
        prompt = "\n".join(str(x.get("content") or "") for x in messages
                           if x.get("role") == "user")
        text = self.reply(system=system, prompt=prompt)
        self.bodies.append({"system": system, "prompt": prompt, "text": text})
        return 200, json.dumps({"choices": [{"message": {"content": text},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 8, "completion_tokens": 8}},
                               ensure_ascii=False)


# ============================================================ 夹具与读数


def _blocked_workspace(base: pathlib.Path) -> tuple[Store, str, str, str]:
    """一个工作区 ＋ 一条被真生产者停住的活（owner 行 + 板项）。"""
    st = Store(base / "ws")
    st.init()
    cond = Conductor(st, registry={}, backend=LocalBackend({}))
    owner = str(cond.open_top_level_run("D", "夹具：被优雅停止停住的活"))
    item = cond.open_item(kind="delegation", role="F", expects="work",
                          action="write_report", summary="夹具：C13 停下来的活",
                          parent_task_id=owner, depth=3,
                          input_key=f"item:{owner}:c13")
    got = SC.block_remaining_tasks(st, task_id=owner,
                                   why="夹具：budget 到顶，这活停在这里")
    assert got.get("checked") is True, got
    return st, owner, str(item), got


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    base.mkdir(parents=True, exist_ok=True)
    st, owner, item, blocked = _blocked_workspace(base)
    wire = _Wire(item_id=item)
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    # 单档：唤醒链与 Lean 无关（docstring 末节说明理由）。
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "0")
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root), "--sid", SID,
                "--subagents", "--task", "逐条审批唤醒被停住的活",
                "--rounds", "2", "--max-steps", "6",
            ])
    except SystemExit as exc:
        rc = int(exc.code or 0)
    ws = pathlib.Path(st.root)
    # 执行侧接上之后，被唤醒的那一条是后台线程在跑：它的终态、`agent_run_start/end`
    # 与账本行都可能晚于 `cli.main` 返回。若这一趟真的叫起来了（回执 started=True），
    # 等它落定再交读数；没叫起来（反真空/未接线）就照原样立刻返回。
    if any(bool(_cell(w, item).get("started")) for w in _wakes(_events(ws))):
        _wait_terminal(Store(ws), owner, timeout=30.0)
    return {"rc": int(rc), "ws": ws, "store": Store(ws),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "owner": owner, "item": item, "blocked": blocked}


def _wait_terminal(store: Store, task_id: str, *, timeout: float) -> dict:
    """等一条被唤醒的行落终态、并把花销写回（它与主线程并发）。

    只等终态不够：`resume_dispatched` 的顺序是 `_end_from_payload`（写终态）→
    `_set_usage`（把账本累计值抄回 `tasks`）。在两步之间读，owner 行会短暂地
    `done` + `tokens=0`，而"一行账 / 两处相等"那一格就可能读到假的不等。
    `tokenmeter:settled` 是 `_set_usage` 的落痕（`inputs` 里那一格），等到它再交读数；
    写不回来时不无限等（终态之后最多再等 5 秒，超时按实况交，交给判据报）。
    """
    start = time.monotonic()
    deadline = start + float(timeout)
    terminal_at = 0.0
    row = _row(store, task_id)

    def _settled(one: dict) -> bool:
        return any(str(x) == "tokenmeter:settled" for x in (one.get("inputs") or []))

    while time.monotonic() < deadline:
        if str(row.get("status") or "") in ("done", "failed", "cancelled"):
            if _settled(row):
                return row
            if not terminal_at:
                terminal_at = time.monotonic()
            elif time.monotonic() - terminal_at >= 5.0:
                return row
        time.sleep(0.05)
        row = _row(store, task_id)
    return row


def _events(ws: pathlib.Path) -> list[dict]:
    got: list[dict] = []
    for path in sorted((ws / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                got.append(json.loads(line))
            except ValueError:
                continue
    return got


def _wakes(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in events:
        if e.get("kind") != "agent_step" or e.get("role") != "M":
            continue
        if str((e.get("payload") or {}).get("name") or "") != "conductor.wake_blocked":
            continue
        got = e.get("result") or {}
        data = got.get("data")
        if hasattr(data, "to_dict"):
            data = dict(data.to_dict())
        out.append({"ok": bool(got.get("ok")),
                    "data": data if isinstance(data, dict) else {}})
    return out


def _row(store: Store, task_id: str) -> dict:
    return next((dict(r) for r in store.rows("tasks")
                 if str(r.get("task_id")) == task_id), {})


def _chain_reading(got: dict[str, Any]) -> dict[str, Any]:
    events = _events(got["ws"])
    st = got["store"]
    return {
        "store": st, "ws": got["ws"], "events": events,
        "owner": _row(st, got["owner"]), "item": _row(st, got["item"]),
        "wakes": _wakes(events),
        "runs": [e for e in events if e.get("kind") == "agent_run_start"],
        "ends": [e for e in events if e.get("kind") == "agent_run_end"],
        "stdout": got["stdout"],
    }


def _cell(result: dict, item_id: str) -> dict:
    data = dict(result.get("data") or {})
    for one in (data.get("items") or []):
        if isinstance(one, dict) and str(one.get("item_id")) == item_id:
            return dict(one)
    return {}


def _chain_problems(reading: dict[str, Any], item_id: str) -> list[str]:
    problems: list[str] = []
    wakes = reading["wakes"]
    if len(wakes) != 3:
        return [f"M 应恰好调三次 conductor.wake_blocked，实得 {len(wakes)}"]
    # 1. 没批准：逐条 skip/not_approved、一个字节不写、一次都不叫。
    first = dict(wakes[0]["data"])
    cell = _cell(wakes[0], item_id)
    if str(cell.get("verdict") or "") != "skip":
        problems.append(f"未批准那一趟该判 skip：{cell!r}")
    if str(cell.get("refusal_code") or "") != "not_approved":
        problems.append(f"未批准那一趟该点名 not_approved：{cell.get('refusal_code')!r}")
    if cell.get("started") is not False:
        problems.append(f"未批准那一趟 started 该是 False：{cell.get('started')!r}")
    if str(first.get("state") or "") == "woken":
        problems.append(f"未批准那一趟竟然 state=woken：{first!r}")
    # 2. 批准这一趟：审计必须判 resume、直写必须落盘（板项 block→queued + 一条 wake: 落痕）、
    #    执行侧必须真的叫起来（2026-11-16 WF 修好缺陷 1 之后）。
    #
    #    改前（2026-11-15 CC4 实测）：`start --mode research` 走的是
    #    `host.wired_llm_conductor`，它没有把 `cond.resume_runner` 接到
    #    `resume_dispatched`（只有 `host.wired_conductor` 那一条会接）⇒ 研究跑里的
    #    `conductor.wake_blocked` 永远 `wake_failed`：板项翻成 queued 了，人没叫起来。
    #    现在这一格是正控：`started=True`、owner 真的按同号跑完（有它的
    #    `agent_run_start` / `agent_run_end`、结局 ok）。执行侧没接线的反真空在
    #    `tests/test_rehearsal_c13_wake_chain.py::test_without_the_wiring...` 里造。
    second = dict(wakes[1]["data"])
    cell2 = _cell(wakes[1], item_id)
    if str(cell2.get("verdict") or "") != "resume":
        problems.append(f"批准那一趟的审计该判 resume：{cell2!r}")
    item = dict(reading["item"])
    # 板项的状态推进：直写那一刻是 queued；被唤醒的 D 读到它之后是 seen（渲染即收口
    # 的另一档；它仍留在板上，收口要收件人自己 ack）。两档都不是 block。
    if str(item.get("item_state") or "") not in ("queued", "seen", "done"):
        problems.append(f"板项该从 block 推进（queued/seen/done）："
                        f"{item.get('item_state')!r}")
    marks = [str(x) for x in (item.get("inputs") or []) if str(x).startswith("wake:")]
    if len(marks) != 1:
        problems.append(f"wake: 落痕应恰好一条（不准翻倍）：{marks}")
    if cell2.get("started") is not True:
        problems.append(f"批准那一趟必须真的叫起来（started 该是 True）：{cell2!r}")
    if str(second.get("state") or "") != "woken":
        problems.append(f"叫起来了就该 state=woken：{second.get('state')!r}")
    if int(second.get("count") or 0) != 1:
        problems.append(f"叫起来了 count 该是 1：{second.get('count')!r}")
    if str(cell2.get("refusal_code") or ""):
        problems.append(f"叫起来了就不该有 refusal_code：{cell2.get('refusal_code')!r}")
    if str(cell2.get("task_id") or "") != str(reading["owner"].get("task_id") or ""):
        problems.append(f"叫的该是 owner 的台账号：{cell2.get('task_id')!r}")
    owner_id = str(reading["owner"].get("task_id") or "")
    if not [e for e in reading["runs"]
            if str(e.get("task_id") or "") == owner_id
            and str(e.get("role") or "") == "D"]:
        problems.append("被唤醒的 D 没有起跑（没有它的 agent_run_start）")
    if not [e for e in reading["ends"]
            if str(e.get("task_id") or "") == owner_id
            and str(e.get("role") or "") == "D"]:
        problems.append("被唤醒的 D 没有 agent_run_end")
    if str(reading["owner"].get("status") or "") != "done":
        problems.append(f"owner 行没有落终态 done：{reading['owner'].get('status')!r}")
    if str(reading["owner"].get("outcome") or "") != "ok":
        problems.append(f"owner 行的结局不是 ok：{reading['owner'].get('outcome')!r}")
    # 3. 幂等：再叫一遍 ⇒ 板项已不是 block ⇒ not_blocked、不重复叫人。
    cold = _cell(wakes[2], item_id)
    if str(cold.get("refusal_code") or "") != "not_blocked":
        problems.append(f"第二次批准该点名 not_blocked：{cold.get('refusal_code')!r}")
    if cold.get("started") is not False:
        problems.append(f"第二次批准不该再叫人：{cold.get('started')!r}")
    marks_after = [str(x) for x in (dict(reading["item"]).get("inputs") or [])
                   if str(x).startswith("wake:")]
    if len(marks_after) != 1:
        problems.append(f"wake: 落痕翻倍了：{marks_after}")
    # 5. 多轮：两轮都开了。
    m_runs = [e for e in reading["runs"] if str(e.get("role") or "") == "M"]
    if len(m_runs) < 2:
        problems.append(f"多轮驱动只开了 {len(m_runs)} 轮（`--rounds 2`）")
    if "自主跑完" not in reading["stdout"]:
        problems.append("stdout 里没有「自主跑完 N 轮」这一行（走的不是 autonomy 那条路）")
    return problems


# ============================================================ ① 正控


def test_the_wake_happens_inside_the_multi_round_drive(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：两轮驱动 → 未批准不动作 → 批准后审计判 resume、板项翻 queued、执行侧三态如实。"""
    got = _run(tmp_path, monkeypatch)
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」")
    assert [e for e in reading["events"] if e.get("kind") == "llm_call"], (
        "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam")

    problems = _chain_problems(reading, got["item"])
    assert problems == [], problems

    # ---- 钱：账本有行、无主为 0、悬空 0、逐分相等
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(reading["store"])
    assert money["usage_ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ ② 反真空


def test_without_the_token_the_wake_writes_nothing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把三轮里的"批准"换成"不批准" ⇒ 盘上一个字节不动、一次都不叫。

    它证明正控里"叫起来了"不是恒真：没有那张令牌，连"这一条可以唤醒"的结论都不给。
    """
    got = _run(tmp_path, monkeypatch)
    reading = _chain_reading(got)
    item_id = got["item"]
    first = _cell(reading["wakes"][0], item_id)
    approved = _cell(reading["wakes"][1], item_id)
    # 1. 未批准：逐条 not_approved、started=False、没有落痕（一条 wake: 都不写）。
    assert str(first.get("refusal_code") or "") == "not_approved", first
    assert first.get("started") is False, first
    assert str(first.get("mark") or "") == "", first
    assert str(dict(reading["wakes"][0]["data"]).get("state") or "") != "woken", reading["wakes"][0]
    # 2. 盘上那条唯一的 wake: 落痕来自"批准"那一趟（不是未批准那一趟）。
    marks = [str(x) for x in (dict(reading["item"]).get("inputs") or [])
             if str(x).startswith("wake:")]
    assert len(marks) == 1, marks
    assert str(approved.get("mark") or "") == marks[0], (approved.get("mark"), marks)


# ============================================================ 判据①：一行账


def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行。"""
    got = _run(tmp_path, monkeypatch)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = RC.ledger_identity(got["ws"], got["store"])
    print(f"[一行账] c13 真调用={reading['calls']} "
          f"出网={len(got['wire'].bodies)} 账本行={reading['rows']} "
          f"duplicate={len(reading['duplicates'])} 未配对={len(reading['unpaired'])} "
          f"未认领={len(reading['unclaimed'])}")
    assert reading["calls"] == len(got["wire"].bodies), (
        f"真调用与出网次数不等：事件 {reading['calls']} / 出网 {len(got['wire'].bodies)}")
    problems = RC.one_row_per_call_problems(reading)
    assert problems == [], "判据①红：\n- " + "\n- ".join(problems)


# ============================================================ 判据②：会话归口


def test_every_llm_call_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据②：这一趟所有 `llm_call` 事件都落在本趟 `sid`，缺省会话 0 条。"""
    got = _run(tmp_path, monkeypatch)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    split = RC.session_split(got["ws"], SID)
    print(f"[会话归口] c13 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
