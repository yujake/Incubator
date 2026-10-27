# -*- coding: utf-8 -*-
"""p210：目的的自动填充要真落盘、缺目的的问询要真进提示词、等任意计时器也算待机。

业主 2026-10-26 逐字（这一批的唯一权威）：

    「这是purpose自动填充没做好，且问询没落地。如果代理没在工作，在挂着
      "等任何一个计时器返回"，那就是待机」

## 真机读数为什么把这三条逼了出来（`projects/mp3-r3`）

    `out/clock/state.json`：timers 20 条，purpose 全为 None（有目的 0 / 无目的 20）
    到点消息却有话可念：「时间到：认领检索请求 r-000004｜等了 2 分钟 27 秒」
    `out/clock/wait_any.json` rows = []（一次都没请求"等任意计时器"）
    三态读数：只有 M 一个会显示 standby，其余子代理多半直接静默

第一条读数的根因在两处取值口径，不在自动填：`purpose` 是 `Timer` 上的一个 `@property`
（读 `reason` 字段），`asdict` 不吐它 ⇒ 盘上那一行只有 `reason`，按行读 `purpose` 的
读者一律拿到 None，而 `fire_due` 用内存里的属性、念得出话。于是"读数与消息不一致"
不是"填没填"的问题，是"两处各取一套"的问题 —— 现在两处都走 `clock.purpose_of`。

## 这一份判据钉的五条（a–e）+ 反真空

| # | 钉什么 | 改前红在哪 |
|---|---|---|
| a | 等子建表 ⇒ 落盘 `purpose` 非空且 `purpose_source="target_task"` | 真机 20/20 是 None（盘上连这个键都没有） |
| b | 等程序建表 ⇒ 落盘 `purpose` 非空且 `purpose_source="program"` | 改前只有 `given`/`unavailable` 两档，程序那一条根本没目的 |
| c | 起表没给目的 ⇒ 受理成功 + 下一拍提示词里有问询（模型真的看见） | 改前 `agent_loop.py` 里 grep `purpose_missing` / `PURPOSE_PROMPT` 命中 0 |
| d | 请求 wait_any 且挂着表 ⇒ `agent_state` 返回 standby 且理由点名"等任意计时器" | 改前 `agent_state` 根本没有 wait_any 这个输入 |
| e | 反真空：把 a/b 的自动填打桩成不填、把 d 的 wait_any 判据打桩成不认 ⇒ 那几条必红 | —— |

另外三条纪律各有一条判据：落盘行与内存里念的目的必须逐字相同（单一来源）、
"要求过等而没可等的"仍按交差但理由点名、等待意图账读不成是 unknown 不是静默。

## 第二批（业主同日追加）：等谁必须指名道姓、而且时钟要真的能收到

    「"等别人"必须要明确到等名册上的谁（父代理或子代理的名册名，且时钟要能真的接收）
      或者等哪条程序」
    「当然他可以起计时器叫"等任意计时器返回"，这个需要存在的计时器数大于等于1」

| # | 钉什么 | 改前红在哪 |
|---|---|---|
| i | `wait_for="别人"` ⇒ 受控拒绝，码 `waiter_not_resolvable`，拒信逐字给两条正路 | 改前只抛一句"等的东西不存在"，不提正路 |
| j | `wait_for=<名册名>` ⇒ 落盘 `waiting_on{kind:roster,name,task_id}`；那人交差 ⇒ 醒、`waiting_on` 清空、只醒一次 | 改前没有 `waiting_on` 这一格；交差不产生时钟事件 |
| k | `wait_for=<绝对编号>` 同上（名册名与编号等价） | 同上 |
| l | `wait_for=<程序句柄>` ⇒ 程序退出 ⇒ 醒 | 改前 `program:` 这个指称根本不存在 |
| m | 等父：父发一条 message ⇒ 醒（父不会交差，它发的是指导意见） | 改前只有交差那条链 |
| n | 0 条表时 `wait_any` ⇒ 拒，码 `no_timers_to_wait`，拒信两条正路 | 改前受理并给 requested/waiting 两格 |
| o | 反真空：打桩掉"唤醒"那一步、打桩掉"数一数现存表"那一步 ⇒ j/k/l/m/n 必红 | —— |

## 边界

全部 tmp 工作区 + 假时钟 + 替身缝照剧本回答，零真实模型调用、零网络。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Callable, Sequence

import pytest

from agentflow import clock as CLK
from agentflow import conductor as COND
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "p210"
TASK = "把引理 L1 的证明写进 out/proof.md"
#: 派活载荷里那句 task 原文（等子那一条的目的应当就是它）。
CHILD_TASK = "把 Sylow 定理的三处证据补齐（含反例扫描与逐字引文回验）"
#: wait_any 那条意图的编号前缀（判据按它认"这一条真的是意图账里的行"）。
WAIT_PREFIX = "wa-"


# ------------------------------------------------------------------ 替身缝与夹具


class _Gate:
    """照剧本回答的替身模型：记下每一次的提示词（模型眼前到底是什么，只有这一份是证据）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: Sequence[str],
                 on_call: Callable[[int, str], None] | None = None) -> None:
        self.replies = list(replies)
        self.on_call = on_call
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(index, prompt)
        text = self.replies[min(index, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


def _tool(name: str, **args: Any) -> str:
    return json.dumps({"tool": name, "args": args}, ensure_ascii=False)


def _stop_now(ws: pathlib.Path, why: str) -> None:
    from agentflow import stopctl

    stopctl.request_stop(ws, reason=why)


@pytest.fixture()
def bench():
    """假时钟 + 清空进程内簿记（时钟簿记是进程级的，串了会污染别的判据）。"""
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    CLK.reset_programs()
    fake = CLK.use(CLK.FakeClock(wall="2026-10-26T09:00:00+00:00", monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()


def _ws(tmp_path: pathlib.Path, name: str, *, secretary: bool = False
        ) -> tuple[Store, Conductor, pathlib.Path]:
    """临时工作区 + 已接上"等谁"读口与时钟工具面的注册表。

    `secretary=True` ⇒ 给 conductor 接上名册写入口（"从名册那条子的 task 填目的"
    那一条判据要它）。
    """
    ws = tmp_path / name
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    if secretary:
        from agentflow.secretary import Secretary

        cond.roster_sink = Secretary("M", root=ws, store=st)
    build_registry(store=st, conductor=cond, workspace_root=ws)
    return st, cond, ws


def _agent(cond: Conductor, parent: str, *, status: str = "done", role: str = "D",
           detail: str = "一个子代理") -> str:
    """造一行代理（`status="done"` = 已经收工；`running` = 在飞）。

    终态行必须带 `ended_at`（`schema.Task.validate`：每次 start 恰有一次 end）。
    """
    ended = None if status in ("pending", "running") else "2026-10-26T09:00:05+08:00"
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"p210@{role}",
        "status": status, "outcome": ("ok" if ended else None),
        "refusal_reason": None, "instance": "",
        "detail": detail, "error": None, "started_at": "2026-10-26T09:00:00+08:00",
        "ended_at": ended, "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, gate: _Gate,
          me: str, *, max_steps: int = 12) -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=max_steps, workspace_root=str(ws))


def _disk_rows(ws: pathlib.Path) -> list[dict[str, Any]]:
    """`out/clock/state.json` 的原始行（落盘那一份事实，不经任何内存对象）。"""
    path = ws / CLK.STATE_REL
    assert path.is_file(), f"没有落盘：{path}"
    return list(json.loads(path.read_text(encoding="utf-8"))["timers"])


def _disk_row(ws: pathlib.Path, timer_id: str) -> dict[str, Any]:
    for row in _disk_rows(ws):
        if str(row.get("timer_id") or "") == str(timer_id):
            return row
    raise AssertionError(
        f"落盘里没有 {timer_id}（有：{[r.get('timer_id') for r in _disk_rows(ws)]}）")


def _three(ws: pathlib.Path, st: Store) -> dict[str, dict[str, Any]]:
    """三态读数（走唯一实现：`clock_waiters` + `agent_states`）。"""
    rows = [dict(r) for r in st.rows("tasks") if not str(r.get("kind") or "")]
    return COND.agent_states(rows, clock=COND.clock_waiters(ws), retired={})


# ================================================================== a 等子：目的落盘


def test_a_a_child_waiter_lands_a_target_task_purpose(tmp_path, bench) -> None:
    """a) 等子建表（`arm_child_waiter`）⇒ 落盘 `purpose` 非空且 `purpose_source="target_task"`。

    改前红：真机 `state.json` 的 20 条表 purpose 全为 None —— 盘上连这个键都没有
    （`Timer.to_dict` 走 `asdict`，而 `purpose` 是属性），于是"填了没有"这件事在
    盘上读不出来，只有内存里的到点消息念得出话。
    """
    st, cond, ws = _ws(tmp_path, "child-waiter", secretary=True)
    parent = cond.open_top_level_run("M", TASK)
    child = _agent(cond, parent, status="running")
    # 名册里那一行（"从名册那条子的 task 填"走的正是这一条读口）。
    got = cond.roster_sink.roster_add(owner=parent, role="D", task_id=child,
                                      brief="", task=CHILD_TASK)
    assert got.get("problem") == "", got

    armed = cond.arm_child_waiter(child, parent_task_id=parent, role="D")
    assert armed["armed"] is True, armed
    timer_id = str(armed["timer_id"])

    row = _disk_row(ws, timer_id)
    assert "purpose" in row, "落盘行里没有 purpose 这一格（读数只能拿 None）"
    assert row["purpose"] == CHILD_TASK, row["purpose"]
    assert row["purpose_source"] == "target_task", row["purpose_source"]
    # 单一来源：`purpose` 是 `reason` 的规范化视图，不许各存一份可漂的副本。
    assert row["purpose"] == row["reason"], (row["purpose"], row["reason"])
    assert row["wait_for_resolved"] == f"task:{child}", row["wait_for_resolved"]


def test_a2_without_the_fill_the_same_row_is_purposeless(
        tmp_path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) 反真空（a 的那一半）：把"从名册那条子填目的"打桩成不填 ⇒ a) 的断言必红。

    打两处，因为填这条路有两段：`clock._probe_read` 的 `task_text`（名册读口）与
    `arm_child_waiter` 的 `task_text` 兜底。两处都空 ⇒ 盘上那条表真的没有目的，
    于是 a) 那三条断言（非空 / target_task / 与 reason 同源）逐条取不到 a) 期望的值。
    """
    _, cond, ws = _ws(tmp_path, "no-fill", secretary=True)
    parent = cond.open_top_level_run("M", TASK)
    child = _agent(cond, parent, status="running")
    cond.roster_sink.roster_add(owner=parent, role="D", task_id=child,
                                brief="", task=CHILD_TASK)
    real_probe = CLK._probe_read

    def hollow_probe(workspace: Any, kind: str, ref: str) -> dict[str, Any]:
        got = dict(real_probe(workspace, kind, ref))
        got["task_text"] = ""      # 名册那一行"还在"，只是没有原文可用
        return got

    monkeypatch.setattr(CLK, "_probe_read", hollow_probe)
    armed = cond.arm_child_waiter(child, parent_task_id=parent, role="D", task_text="")
    assert armed["armed"] is True, armed
    assert armed["purpose_missing"] is True, armed
    row = _disk_row(ws, str(armed["timer_id"]))
    assert row["purpose"] == "", row["purpose"]
    assert row["purpose_source"] == "unavailable", row["purpose_source"]
    assert not (row["purpose"] and row["purpose_source"] == "target_task")


# ================================================================== b 等程序：第四档


def test_b_a_program_waiter_lands_a_program_purpose(tmp_path, bench) -> None:
    """b) 等程序建表（`start_program` 不给 purpose）⇒ 落盘非空且 `purpose_source="program"`。

    改前红：`start_program` 只认 `given`/`unavailable` 两档，程序那一条根本没目的 ——
    到点消息于是只剩「程序跑完了：lean.EXE｜耗时 0 秒｜退出码 0」，读的人看不出
    "等它是为了什么"。
    """
    _, _, ws = _ws(tmp_path, "program")
    timer = CLK.start_program(ws, program=r"D:\_env\lean\lean.EXE",
                              argv=[r"D:\_env\lean\lean.EXE", "--version"],
                              where="p210.lean_version")
    row = _disk_row(ws, timer.timer_id)
    assert "purpose" in row, "落盘行里没有 purpose 这一格"
    assert row["purpose"], row["purpose"]
    assert row["purpose_source"] == "program", row["purpose_source"]
    assert "lean.EXE" in row["purpose"], row["purpose"]
    assert "--version" in row["purpose"], f"目的里没有命令摘要：{row['purpose']!r}"

    CLK.finish_program(ws, timer.timer_id, outcome="exited", exit_code=0, elapsed_sec=0.4)
    done = _disk_row(ws, timer.timer_id)
    assert f"目的：{done['purpose']}" in done["message"], done["message"]
    assert done["purpose"] == row["purpose"], "到点那句念的目的与落盘那一格不一致"


def test_b2_without_the_program_fill_it_is_unavailable(
        tmp_path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) 反真空（b 的那一半）：把程序目的的自动填打桩成不填 ⇒ b) 的三条断言必红。"""
    _, _, ws = _ws(tmp_path, "program-hollow")
    monkeypatch.setattr(CLK, "program_purpose", lambda **kw: "")
    timer = CLK.start_program(ws, program="lean", argv=["lean", "--version"])
    row = _disk_row(ws, timer.timer_id)
    assert row["purpose"] == "", row["purpose"]
    assert row["purpose_source"] == "unavailable", row["purpose_source"]
    assert not (row["purpose"] and row["purpose_source"] == "program")


# ================================================================== 单一来源（落盘 = 内存）


def test_b3_the_disk_row_and_the_memory_message_say_the_same_purpose(tmp_path, bench) -> None:
    """目的只有一个来源：落盘那一行喂回读侧念出来的，必须与到点消息逐字相同。

    这一条是业主"两处口径不一致"那句话的机器判据：喂进去的是 `state.json` 的原始行
    （不经任何内存对象），一边用 `purpose_of(row)` + `due_message` 重念一遍，
    另一边是 `fire_due` 真的写进那一行 `message` 的那句。两边不同 ⇒ 红。
    """
    _, cond, ws = _ws(tmp_path, "single-source")
    me = cond.open_top_level_run("M", TASK)
    timer = CLK.start_timer(ws, after_sec=60.0, reason="等一小时+外审回信",
                            task_id=me, to=me)
    in_memory = timer.purpose
    row = _disk_row(ws, timer.timer_id)
    assert row["purpose"] == in_memory, (row["purpose"], in_memory)
    loaded = CLK.Timer.from_dict(row)
    assert loaded.purpose == in_memory, (loaded.purpose, in_memory)
    assert CLK.purpose_of(row) == CLK.purpose_of(timer), (
        CLK.purpose_of(row), CLK.purpose_of(timer))

    bench.advance(61.0)          # advance 自己会跑一次 fire_due（到点即写那一行）
    fired = _disk_row(ws, timer.timer_id)
    assert fired["state"] == "fired", fired["state"]
    assert fired["message"].startswith("时间到：等一小时+外审回信"), fired["message"]
    replayed = CLK.due_message(
        purpose=CLK.purpose_of(fired), waited_sec=timer.waited_seconds(),
        created_at=fired["created_at"], fired_at=fired["fired_at"])
    assert fired["message"].startswith(replayed), (
        "落盘行念出来的目的与内存里念的那句不一致", fired["message"], replayed)


# ================================================================== c 问询进提示词


def test_c_the_next_prompt_asks_for_the_missing_purpose(tmp_path, bench) -> None:
    """c) 起表没给目的 ⇒ 受理成功 + 下一拍提示词里有问询，且模型真的看见。

    走真路径：模型自己调 `clock.timer_start(after_sec=…)`（不给目的）⇒ 受理；
    下一拍的提示词（`AgentLoop._prompt` 是唯一拼它的地方）里必须有缺目的那一节、
    那条表的编号、以及唯一一份追问句 `clock.PURPOSE_PROMPT`。

    改前红：`agent_loop.py` 里 grep `purpose_missing` / `PURPOSE_PROMPT` 命中 0 ——
    追问只活在工具读数与到点消息里，模型的提示词里一次都没出现过（"问询没落地"）。
    """
    st, cond, ws = _ws(tmp_path, "ask")
    me = cond.open_top_level_run("M", TASK)
    # 手上有活（一条未消的委托型板项）⇒ `_park_gate` 不挂机，下一拍照常问模型。
    cond.open_item(kind="delegation", role="M", expects="work", action="run_once",
                   parent_task_id=me, summary="把 L1 的证明写完")
    gate = _Gate([_tool("clock.timer_start", after_sec=60.0),
                  _tool("clock.now")])

    def on_call(index: int, _prompt: str) -> None:
        if index >= 1:
            _stop_now(ws, "判据：下一拍已经问过模型了")

    gate.on_call = on_call
    loop = _loop(st, cond, ws, gate, me)
    loop.run(TASK, summoned_by="user", my_task_id=me, depth=1)

    assert len(gate.prompts) >= 2, (
        f"循环只问了 {len(gate.prompts)} 次模型 ⇒ 没法证明'下一拍有问询'")
    purposeless = [t for t in CLK.timers(ws) if not t.purpose]
    assert purposeless, "模型那条 timer_start(after_sec) 没有被受理（缺目的应当受理）"
    timer_id = purposeless[0].timer_id

    first, second = gate.prompts[0], gate.prompts[1]
    assert "【缺目的】" not in first, "起表之前就该没有这一节（否则不是'起表之后才问'）"
    assert "【缺目的】" in second, "下一拍的提示词里没有缺目的那一节 —— 问询没落地"
    assert CLK.PURPOSE_PROMPT in second, "提示词里没有唯一那份追问句"
    assert "clock.timer_purpose(" in second, second[-600:]
    assert timer_id in second, f"提示词里没点名是哪一条表（{timer_id}）"


def test_c2_the_ask_disappears_once_the_purpose_is_written(tmp_path, bench) -> None:
    """c) 的负控：补上目的之后不许再问（否则每一拍都在问同一件事）。"""
    st, cond, ws = _ws(tmp_path, "ask-gone")
    me = cond.open_top_level_run("M", TASK)
    timer = CLK.start_timer(ws, after_sec=60.0, task_id=me, to=me)
    loop = _loop(st, cond, ws, _Gate([_tool("clock.now")]), me)
    loop.my_task_id = me          # `run()` 里才设这一格；这里直接拼提示词，先补上
    assert "【缺目的】" in loop._prompt([], step=0), loop._prompt([], step=0)[-600:]
    CLK.set_purpose(ws, timer.timer_id, "等一分钟+看着子代理")
    assert "【缺目的】" not in loop._prompt([], step=0), "补上目的之后还在问"


def test_c3_another_agents_purposeless_timer_does_not_shout_at_me(tmp_path, bench) -> None:
    """c) 的负控：按台账号筛 —— 别人的缺目的不许刷到我这一拍的提示词里。"""
    st, cond, ws = _ws(tmp_path, "ask-scope")
    me = cond.open_top_level_run("M", TASK)
    other = _agent(cond, me, status="running", role="E")
    CLK.start_timer(ws, after_sec=60.0, task_id=other, to=other)
    loop = _loop(st, cond, ws, _Gate([_tool("clock.now")]), me)
    loop.my_task_id = me          # 同上：这一格在 `run()` 里才设
    prompt = loop._prompt([], step=0)
    assert "【缺目的】" not in prompt, prompt[-600:]
    assert len(CLK.timers_missing_purpose(ws)) == 1, "读数那一侧仍要看得见它（只是不刷给 M）"


# ================================================================== d 等任意计时器 = 待机


def test_d_wait_any_with_a_timer_reads_standby(tmp_path, bench) -> None:
    """d) 没在工作、请求过 wait_any、且时钟上确实还有东西没回来 ⇒ standby，理由点名。

    这一条刻意让那条计时器只写了收件人（`to=<那个台账号>`）而 `task_id` 是空串：
    `clock_waiters.by_task` 只按 `task_id` 归组，于是"这个名字下挂着钟"那一档
    结构上看不见它（那是既有的一处窄口），只有 wait_any 那一条认得出来。
    `request_wait_any` 的"名下现存计时器"判据按 `task_id` 或 `to` 认，所以它照样受理。

    改前红：`agent_state` 根本没有 wait_any 这个输入 ⇒ 这一行读成 `silent`
    （"它已收工：没有任务、也没有任何计时器"）。
    """
    st, cond, ws = _ws(tmp_path, "wait-any")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")
    CLK.start_timer(ws, after_sec=120.0, reason="等 Lean 那一趟跑完", to=child)
    asked = CLK.request_wait_any(ws, task_id=child, role="D",
                                 purpose="等任意计时器返回")
    assert str(asked["wait_id"]).startswith(WAIT_PREFIX), asked

    cell = dict(_three(ws, st)[child])
    assert cell["state"] == COND.AGENT_STATE_STANDBY, cell
    assert cell["state_label"] == "待机", cell
    assert "等任意计时器" in cell["reason"], cell["reason"]
    assert cell["wait_any"]["requested"] is True, cell["wait_any"]
    assert cell["waiting_only"] is True, cell


def test_d2_without_the_wait_any_rule_the_same_agent_reads_silent(
        tmp_path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) 反真空（d 的那一半）：把 wait_any 那条判据打桩成不认 ⇒ d) 必红。

    打的是唯一那条通路（`conductor.waiters_of` 把意图账挂进每格 `wait`）：
    打掉之后同一个夹具读成 `silent` —— 证明 d) 真的是"新判据"在起作用。
    """
    st, cond, ws = _ws(tmp_path, "wait-any-hollow")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")
    CLK.start_timer(ws, after_sec=120.0, reason="等 Lean 那一趟跑完", to=child)
    CLK.request_wait_any(ws, task_id=child, role="D", purpose="等任意计时器返回")

    real = COND.waiters_of

    def blind_waiters_of(clock: Any, task_ids: Any) -> dict[str, Any]:
        got = dict(real(clock, task_ids))
        got.pop("wait_any", None)
        return got

    monkeypatch.setattr(COND, "waiters_of", blind_waiters_of)
    cell = dict(_three(ws, st)[child])
    assert cell["state"] == COND.AGENT_STATE_SILENT, cell
    assert "等任意计时器" not in cell["reason"], cell["reason"]


def test_e_wait_any_with_nothing_left_to_wait_is_still_a_handoff(tmp_path, bench) -> None:
    """d/e) 意图还在、而可等的东西已经没了 ⇒ 仍按既有口径（交差/静默），理由点名这一档。

    起意时有一条表（所以 `request_wait_any` 受理），随后那条表到点了 —— 这一档
    不许读成待机（它已经没有可等的东西了），也不许和"从来没要求过等"折平。
    """
    st, cond, ws = _ws(tmp_path, "wait-any-empty")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")
    CLK.start_timer(ws, after_sec=60.0, reason="等 Lean 那一趟跑完",
                    task_id=child, to=child)
    CLK.request_wait_any(ws, task_id=child, role="D", purpose="等任意计时器返回")
    bench.advance(120.0)          # 那条表到点
    assert CLK.timers_missing_purpose(ws) == [], "夹具前提：目的都在，这里只看等待意图"
    cell = dict(_three(ws, st)[child])
    assert cell["state"] == COND.AGENT_STATE_SILENT, cell
    assert "等任意计时器" in cell["reason"], cell["reason"]
    assert "交差" in cell["reason"] or "没有可等" in cell["reason"], cell["reason"]


def test_f_an_unreadable_wait_any_book_is_unknown_not_silent(tmp_path, bench) -> None:
    """三态不许折平：等待意图账读不成 ⇒ `unknown`（不是"它没要求过等"）。"""
    st, cond, ws = _ws(tmp_path, "wait-any-broken")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")
    path = ws / CLK.WAIT_ANY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ 这不是 JSON", encoding="utf-8")
    cell = dict(_three(ws, st)[child])
    assert cell["state"] == COND.AGENT_STATE_UNKNOWN, cell
    assert "等待意图账读不成" in cell["reason"], cell["reason"]


def test_g_the_three_states_are_not_flattened(tmp_path, bench) -> None:
    """三个不许折平的读数在同一份夹具里各不相同：在飞 / 待机（挂表 + 等任意表）/ 静默。

    折平任意两档，"父代理能不能销号"就跟着错：销号只对静默
    （`RETIRE_REFUSAL_TARGET_NOT_SILENT`）。
    """
    st, cond, ws = _ws(tmp_path, "three-states")
    me = cond.open_top_level_run("M", TASK)
    flying = _agent(cond, me, status="running", role="D")
    standby_any = _agent(cond, me, status="done", role="E")
    standby_timer = _agent(cond, me, status="done", role="F")
    silent = _agent(cond, me, status="done", role="G")
    CLK.start_timer(ws, wait_for=f"task:{flying}", task_id=me, to=me)
    CLK.start_timer(ws, after_sec=90.0, reason="等 Lean", to=standby_any)
    CLK.start_timer(ws, after_sec=90.0, task_id=standby_timer, to=standby_timer)
    CLK.request_wait_any(ws, task_id=standby_any, role="E", purpose="等任意计时器返回")

    three = _three(ws, st)
    assert three[flying]["state"] == COND.AGENT_STATE_FLYING, three[flying]
    assert three[standby_any]["state"] == COND.AGENT_STATE_STANDBY, three[standby_any]
    assert "等任意计时器" in three[standby_any]["reason"], three[standby_any]["reason"]
    assert three[standby_timer]["state"] == COND.AGENT_STATE_STANDBY, three[standby_timer]
    assert three[silent]["state"] == COND.AGENT_STATE_SILENT, three[silent]
    got = {three[tid]["state"] for tid in (flying, standby_any, standby_timer, silent)}
    assert got == {COND.AGENT_STATE_FLYING, COND.AGENT_STATE_STANDBY,
                   COND.AGENT_STATE_SILENT}, got
    counts = COND.state_counts(
        [three[tid]["state"] for tid in (flying, standby_any, standby_timer, silent)])
    assert counts[COND.AGENT_STATE_FLYING] == 1, counts
    assert counts[COND.AGENT_STATE_STANDBY] == 2, counts
    assert counts[COND.AGENT_STATE_SILENT] == 1, counts
    assert counts["active"] == 3, counts


def test_h_a_wait_any_standby_cannot_be_retired(tmp_path, bench) -> None:
    """待机（挂着等任意计时器）在销号闸上必须有话说 —— 否则"销号只对静默"是句空话。

    它名下可能一条钟都没有（程序计时器不挂名字），所以销号闸不能只读 `waiters`。
    """
    st, cond, ws = _ws(tmp_path, "retire-block")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")
    CLK.start_timer(ws, after_sec=120.0, reason="等 Lean", to=child)
    CLK.request_wait_any(ws, task_id=child, role="D", purpose="等任意计时器返回")
    cell = dict(_three(ws, st)[child])
    blocking = COND.retire_blocking(cell)
    assert blocking, "一个挂着等任意计时器的待机代理在销号闸上一条理由都没有"
    assert any("等任意计时器" in str(b.get("detail") or "") for b in blocking), blocking
    assert all(str(b.get("kind") or "") == "waiting" for b in blocking), blocking


# ================================================================== i 等谁必须指名道姓


def test_i_a_prose_wait_for_is_refused_with_the_two_ways_out(tmp_path, bench) -> None:
    """i) `wait_for="别人"` ⇒ 受控拒绝：码 `waiter_not_resolvable` + 拒信逐字两条正路。

    改前红：改前抛的是一句"等的东西不存在……先确认它的名字或编号"，既没有码，
    也没提"等程序"那条路 —— 模型下一次重写仍然只能猜。

    两条正路是业主原话的两半：名册上的谁（名册名/绝对编号）与某条程序
    （`clock.start_program` 的句柄）。
    """
    _, cond, ws = _ws(tmp_path, "prose")
    me = cond.open_top_level_run("M", TASK)
    with pytest.raises(CLK.ClockError) as excinfo:
        CLK.start_timer(ws, wait_for="别人", task_id=me, to=me)
    text = str(excinfo.value)
    assert isinstance(excinfo.value, CLK.ClockWaiterNotResolvable), type(excinfo.value)
    assert CLK.WAITER_NOT_RESOLVABLE in text, text
    assert "名册名或绝对编号" in text, text
    assert "start_program" in text, text
    assert CLK.timers(ws) == [], "受控拒绝不许留下半条表"


def test_i2_the_same_refusal_comes_back_through_the_tool(tmp_path, bench) -> None:
    """i) 走工具面也一样：`clock.timer_start(wait_for="外部")` 失败且带那个码。"""
    st, cond, ws = _ws(tmp_path, "prose-tool")
    me = cond.open_top_level_run("M", TASK)
    from agentflow.conductor import calling_as
    from agentflow.tools import ToolRegistry
    from agentflow.tools import clock_tools as CT

    reg = ToolRegistry(name="p210-prose")
    reg.bound_role = "M"
    CT.register(reg, store=st, root=ws)
    with calling_as(me, "M"):
        got = reg.call("clock.timer_start", wait_for="外部", reason="等外部结果")
    assert got.ok is False, got.to_dict()
    assert CLK.WAITER_NOT_RESOLVABLE in str(got.error), got.error
    assert "start_program" in str(got.error), got.error
    assert CLK.timers(ws) == []


# ================================================================== j/k 等名册上的人


def _roster_name_for(cond: Conductor, parent: str, child: str, *,
                     name: str = "A1") -> str:
    """在名册里给这个子代理起一个名字（"等名册名"要的那一条读口从这里来）。"""
    got = cond.roster_sink.roster_add(owner=parent, role="D", task_id=child,
                                      brief="", task=CHILD_TASK, want_name=name)
    assert got.get("problem") == "", got
    return str(got.get("name") or name)


def test_j_waiting_on_a_roster_name_lands_and_wakes_on_handoff(tmp_path, bench) -> None:
    """j) `wait_for=<名册名>` ⇒ 落盘 `waiting_on`；那人交差 ⇒ 醒、`waiting_on` 清空、只醒一次。

    改前红两处：`state.json` 里没有 `waiting_on` 这一格（读侧回答不了"在等谁"），
    而 `record_handoff` 不产生时钟事件 ⇒ 等他的那条表只能等超时。
    """
    _, cond, ws = _ws(tmp_path, "roster-name", secretary=True)
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="running")
    name = _roster_name_for(cond, me, child)
    timer = CLK.start_timer(ws, wait_for=name, task_id=me, to=me)

    row = _disk_row(ws, timer.timer_id)
    assert row["waiting_on"]["kind"] == "roster", row["waiting_on"]
    assert row["waiting_on"]["name"] == name, row["waiting_on"]
    assert row["waiting_on"]["task_id"] == child, row["waiting_on"]
    assert CLK.waiting_on_text(row["waiting_on"]) == f"在等 {name}（{child}）", row
    assert row["purpose"], "等名册上的人也该有目的（名册那条 task 原文）"

    handed = CLK.record_handoff(ws, task_id=child, parent_task_id=me, role="D",
                                reason="无事可做且没有计时器")
    assert handed["checked"] is True, handed
    fired = CLK.fire_due(ws)["fired"]
    assert [f["timer_id"] for f in fired] == [timer.timer_id], fired
    assert fired[0]["woke_from"]["name"] == name, fired[0]
    after = _disk_row(ws, timer.timer_id)
    assert after["state"] == "fired", after["state"]
    assert after["waiting_on"] == {}, "醒了之后 waiting_on 必须清空"
    assert after["wait_for_resolved"] == f"task:{child}", "等过谁要留档"
    # 只醒一次：再推一遍不许又"醒"一条。
    assert CLK.fire_due(ws)["fired"] == [], "同一条表醒了两次"


def test_k_waiting_on_the_absolute_id_is_the_same_thing(tmp_path, bench) -> None:
    """k) `wait_for=<绝对编号>` 与名册名等价（业主口径里两种写法是同一件事）。"""
    _, cond, ws = _ws(tmp_path, "absolute", secretary=True)
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="running")
    timer = CLK.start_timer(ws, wait_for=child, task_id=me, to=me)
    row = _disk_row(ws, timer.timer_id)
    assert row["wait_for_resolved"] == f"task:{child}", row["wait_for_resolved"]
    assert row["waiting_on"]["kind"] == "roster", row["waiting_on"]
    assert row["waiting_on"]["task_id"] == child, row["waiting_on"]

    CLK.record_handoff(ws, task_id=child, parent_task_id=me, role="D", reason="交差")
    assert [f["timer_id"] for f in CLK.fire_due(ws)["fired"]] == [timer.timer_id]
    assert _disk_row(ws, timer.timer_id)["waiting_on"] == {}


# ================================================================== l 等某条程序


def test_l_waiting_on_a_program_handle_wakes_when_the_program_exits(tmp_path, bench) -> None:
    """l) `wait_for=<program:<句柄>>` ⇒ 程序退出 ⇒ 醒（`finish_program` 那条链）。

    改前红：`program` 这个指称不存在（`WAIT_FOR_KINDS` 只有 agent/task），
    等程序只能靠"猜一个名字"，而程序根本不是名册上的人。
    """
    _, cond, ws = _ws(tmp_path, "program-wait")
    me = cond.open_top_level_run("M", TASK)
    prog = CLK.start_program(ws, program="lean", argv=["lean", "--run", "L1.lean"],
                             where="p210")
    timer = CLK.start_timer(ws, wait_for=f"program:{prog.timer_id}",
                            task_id=me, to=me)
    row = _disk_row(ws, timer.timer_id)
    assert row["waiting_on"]["kind"] == "program", row["waiting_on"]
    assert row["waiting_on"]["program_id"] == prog.timer_id, row["waiting_on"]
    assert "lean" in row["waiting_on"]["name"], row["waiting_on"]
    assert row["purpose"], "等程序也该有目的"

    assert CLK.fire_due(ws)["fired"] == [], "程序还在跑，不该醒"
    CLK.finish_program(ws, prog.timer_id, outcome="exited", exit_code=0, elapsed_sec=1.5)
    fired = CLK.fire_due(ws)["fired"]
    assert [f["timer_id"] for f in fired] == [timer.timer_id], fired
    assert fired[0]["woke_reason"] == "closed", fired[0]
    assert _disk_row(ws, timer.timer_id)["waiting_on"] == {}


def test_l2_a_program_that_does_not_exist_is_refused(tmp_path, bench) -> None:
    """l) 负控：`program:` 后面跟一个不存在的句柄 ⇒ 受控拒绝（不是"等一条永不到点的表"）。"""
    _, cond, ws = _ws(tmp_path, "program-missing")
    me = cond.open_top_level_run("M", TASK)
    with pytest.raises(CLK.ClockWaiterNotResolvable) as excinfo:
        CLK.start_timer(ws, wait_for="program:tm-000099", task_id=me, to=me)
    text = str(excinfo.value)
    assert "start_program" in text, text
    assert "现有" in text or "一条程序计时器都没有" in text, text
    assert CLK.timers(ws) == []


# ================================================================== m 等父：投递那一侧


def test_m_waiting_on_the_parent_wakes_when_the_parent_speaks(tmp_path, bench) -> None:
    """m) 等父：父发一条 message ⇒ 等待者醒（父不交差，它发的是指导意见）。

    改前红：唤醒的端只有"交差"那条链（`record_handoff`），而父代理永远不交差 ⇒
    子代理"等父回话"只能等超时。
    """
    st, cond, ws = _ws(tmp_path, "parent-speaks", secretary=True)
    grand = cond.open_top_level_run("M", TASK)
    parent = _agent(cond, grand, status="running", role="M", detail="父代理这一趟")
    child = _agent(cond, parent, status="done", role="D")
    # 父在祖父的名册上有一个名字（"父的名册名"就是这么来的）。
    got = cond.roster_sink.roster_add(owner=grand, role="M", task_id=parent,
                                      brief="", task="父代理这一趟", want_name="M1")
    assert got.get("problem") == "", got
    timer = CLK.start_timer(ws, wait_for="M1", task_id=child, to=child)
    row = _disk_row(ws, timer.timer_id)
    assert row["waiting_on"]["name"] == "M1", row["waiting_on"]
    assert row["waiting_on"]["task_id"] == parent, row["waiting_on"]

    from agentflow.agent_loop import send_message

    msg_id, problem = send_message(ws, sender="M", to="D1", subject="指导意见",
                                   body="先证 J 的幂零性，再取反例", from_task_id=parent)
    assert problem == "", problem
    assert CLK.observed_events()["counts"].get("delivery", 0) >= 1, (
        "投递那一侧没有记时钟事件 ⇒ 等父这一档没有落脚点")
    fired = CLK.fire_due(ws)["fired"]
    assert [f["timer_id"] for f in fired] == [timer.timer_id], fired
    assert "先证 J 的幂零性" in fired[0]["message"], fired[0]["message"]
    assert _disk_row(ws, timer.timer_id)["waiting_on"] == {}
    assert CLK.fire_due(ws)["fired"] == [], "第二次投递不许再叫醒同一条表"


# ================================================================== n 等任意表要 >=1 条表


def test_n_wait_any_needs_at_least_one_live_timer(tmp_path, bench) -> None:
    """n) 0 条表时 `wait_any` ⇒ 拒（码 `no_timers_to_wait` + 两条正路）。

    改前红：改前受理并给出 `requested=true / waiting=false` 两格 —— 那种"要求过等、
    而没有可等的东西"的结局与"交差"是两句话，读侧只好再分第三档。
    """
    st, cond, ws = _ws(tmp_path, "wait-any-gate")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")
    with pytest.raises(CLK.ClockNoTimersToWait) as excinfo:
        CLK.request_wait_any(ws, task_id=child, role="D")
    text = str(excinfo.value)
    assert CLK.NO_TIMERS_TO_WAIT in text, text
    assert "wait_for=<名册名或绝对编号>" in text or "名册名" in text, text
    assert "start_program" in text, text
    assert "交差" in text, text
    assert CLK.read_wait_any(ws)["rows"] == [], "受控拒绝不许留下半条意图"


def test_n2_one_live_timer_accepts_it_and_reads_standby(tmp_path, bench) -> None:
    """n) 有 1 条表 ⇒ 受理、`waiting=true`、`agent_state == standby`（正控）。"""
    st, cond, ws = _ws(tmp_path, "wait-any-ok")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")
    CLK.start_timer(ws, after_sec=300.0, reason="等 Lean", to=child)
    row = CLK.request_wait_any(ws, task_id=child, role="D", purpose="等任意计时器返回")
    assert row["wait_id"].startswith(WAIT_PREFIX), row
    reading = CLK.wait_any_reading(ws, child)
    assert reading["requested"] is True and reading["waiting"] is True, reading
    cell = dict(_three(ws, st)[child])
    assert cell["state"] == COND.AGENT_STATE_STANDBY, cell


def test_n3_after_the_timers_are_gone_it_is_refused_again(tmp_path, bench) -> None:
    """n) 正控：表全到点之后又变成拒（不是"一旦受理就永久允许"）。"""
    _, cond, ws = _ws(tmp_path, "wait-any-again")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")
    CLK.start_timer(ws, after_sec=60.0, reason="等 Lean", task_id=child, to=child)
    CLK.request_wait_any(ws, task_id=child, role="D")
    bench.advance(120.0)                       # 那条表到点
    with pytest.raises(CLK.ClockNoTimersToWait):
        CLK.request_wait_any(ws, task_id=child, role="D")


# ================================================================== o 反真空（第二批）


def test_o_without_the_wake_step_the_handoff_judges_go_red(
        tmp_path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """o) 反真空：把"交差要产生时钟事件"那一步打桩掉 ⇒ j/k 的唤醒断言必红。"""
    _, cond, ws = _ws(tmp_path, "hollow-wake", secretary=True)
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="running")
    timer = CLK.start_timer(ws, wait_for=child, task_id=me, to=me)
    real = CLK.observe_event

    def silent_observe(kind: str, **kw: Any) -> Any:
        if kind in ("handoff", "delivery"):
            return None
        return real(kind, **kw)

    monkeypatch.setattr(CLK, "observe_event", silent_observe)
    CLK.record_handoff(ws, task_id=child, parent_task_id=me, role="D", reason="交差")
    assert CLK.fire_due(ws)["fired"] == [], (
        "唤醒那一步被打桩掉了，这条表居然还是醒了 ⇒ 判据没有真的依赖那一步")
    assert _disk_row(ws, timer.timer_id)["waiting_on"], "没醒就该还挂着"


def test_o2_without_the_program_close_the_program_judge_goes_red(
        tmp_path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """o) 反真空：把程序"收口"那一步打桩掉 ⇒ l 的唤醒断言必红。"""
    _, cond, ws = _ws(tmp_path, "hollow-program")
    me = cond.open_top_level_run("M", TASK)
    prog = CLK.start_program(ws, program="lean", argv=["lean", "--run", "L1.lean"])
    timer = CLK.start_timer(ws, wait_for=f"program:{prog.timer_id}", task_id=me, to=me)
    monkeypatch.setattr(CLK, "finish_program",
                        lambda *a, **kw: (prog, "already_fired"))
    assert CLK.fire_due(ws)["fired"] == []
    assert _disk_row(ws, timer.timer_id)["waiting_on"]


def test_o3_without_counting_the_live_timers_the_gate_goes_green(
        tmp_path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """o) 反真空：把"数一数现存表"那一步打桩成恒 >=1 ⇒ 0 条表时的拒不再发生。"""
    _, cond, ws = _ws(tmp_path, "hollow-count")
    me = cond.open_top_level_run("M", TASK)
    child = _agent(cond, me, status="done")

    class _PretendLive:
        def all(self) -> list[Any]:
            return [type("T", (), {"state": "pending", "task_id": child,
                                   "to": child, "kind": "program"})()]

        def all_periodics(self) -> list[Any]:
            return []

    monkeypatch.setattr(CLK, "book", lambda _ws: _PretendLive())
    row = CLK.request_wait_any(ws, task_id=child, role="D")   # 改前会拒，这里不拒
    assert row["wait_id"].startswith(WAIT_PREFIX), (
        "数表那一步被打桩成恒 >=1，却还是拒了 ⇒ 判据 n 没有真的依赖那一步")
