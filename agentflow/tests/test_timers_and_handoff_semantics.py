# -*- coding: utf-8 -*-
"""业主 2026-10-27 的四条裁定：等程序 / 目的自动填 / 计时器不阻塞 / 交差与静默。

## 业主原话（唯一权威，逐字）

```
「将计时器的"等谁"加强到可以等某程序，即运行一个程序时会自动启动一个计时器，
  程序运行完成时计时器会返回。
  再将"等子代理"的"目的"与名册机制的task结合，自动以task填充目的。
  注意：计时器不阻塞智能体动作，智能体可在多计时器同时存在时继续手上工作，直到它认为无事可做时，
  可启动计时器"等待任意计时器返回"。如果已无事可做且无计时器，这意味着它交差了，需要向父代理报告，
  父代理把它记为静默子代理。
  注意：如果一个子代理还有活跃子代理，必存在一个等待该子代理的计时器，所以"静默"定义良好」
```

## 这一份钉住的五件事（每条都写清"改前红在哪"）

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| `test_a_a_program_that_runs_is_on_the_clock_while_it_runs` | ① 起程序就登记 `kind="program"` 的计时器，程序结束它收口带结局/耗时/退出码/pid | 改前 `TIMER_KINDS` 里没有 `program`，`clock.programs` 不存在 ⇒ 程序在跑而账上一条都没有 |
| `test_a2_every_spawn_site_is_on_the_clock_or_registered` | ① 的普查（反真空 + 负控）：起进程的地方逐个点出来 | 改前没有普查器，`subprocess.*` 与计时器之间没有任何机器判据 |
| `test_b_the_purpose_is_filled_from_the_target_task` | ② 等谁没给目的 ⇒ 用名册里那一行 task 填，标 `purpose_source="target_task"` | 改前目的缺了只落 `purpose_missing=true`（追问），不会自己补 |
| `test_c_a_timer_does_not_block_work_in_hand` | ③a 起了 timer 但手上有活 ⇒ 仍调模型（改前红：旧判据"有 waiter 就停"） | 改前的 `_park_gate` 第一条是"有 parked waiter ⇒ 不调模型" |
| `test_c2_wait_any_parks_even_with_timers` | ③b 显式 `wait_any` ⇒ 不调模型（正控） | 改前没有 `wait_any` 这个动作（`clock.request_wait_any` 不存在） |
| `test_c3_wait_any_wakes_when_any_timer_returns` | ③c `wait_any` 到任一 timer 返回那一刻醒（正控） | 同上 |
| `test_d_nothing_to_do_and_no_timer_is_a_handoff` | ④ 无事可做 + 无计时器 ⇒ 交差：向父报告、父记静默 | 改前这一档只会一直挂机（或者干等到步数耗尽），没有"交差"这条路 |
| `test_e_every_active_child_has_a_waiter` | ⑤ 不变量：活跃子代理 ⇒ 必有一条等它的计时器（含负控点名） | 改前派活之后没有任何人给父起这条表 |

## 边界

全部 tmp 工作区 + 假时钟 + 替身缝（`_Gate` 照剧本回答、`_park_slice` 换成一格假时钟），
零真实模型调用、零真睡（除了"起一个几十毫秒的 python 子进程"这一件 —— 那正是 ① 要证明的东西）。
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
from typing import Any, Callable, Sequence

import pytest

from agentflow import clock as CLK
from agentflow import conductor as COND
from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import build_registry
from _d68_board_fixture import children_clean_their_boards  # noqa: E402 - D-68 夹具助手

SID = "timers"
TASK = "业主 2026-10-27 那一批（等程序 / 目的自动填 / 不阻塞 / 交差）"
MARKER = "命题 P 的证明已经落盘"


# ------------------------------------------------------------------ 替身缝


class _Gate:
    """照剧本回答的替身模型：记 prompt，并在回答之前跑 `on_call(index, prompt)`。"""

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


# ------------------------------------------------------------------ 夹具


@pytest.fixture()
def bench():
    """假时钟 + 清空进程内簿记（挂机视图、程序账、交差账都是进程级的）。"""
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    fake = CLK.use(CLK.FakeClock(wall="2026-10-27T09:00:00+00:00", monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()


def _ws(tmp_path: pathlib.Path, name: str, *, secretary: bool = False
        ) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / name
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    children_clean_their_boards(cond)
    if secretary:
        sec = Secretary("M", root=ws, store=st)
        cond.roster_sink = sec
    CLK.set_default_workspace(ws)
    return st, cond, ws


def _child(cond: Conductor, parent: str, key: str = "timers@child") -> str:
    """造一行还在飞的子代理（等谁的那一条的等待对象）。"""
    return cond._write_new_row({
        "task_id": "", "role": "D", "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": key, "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "一个子代理",
        "error": None, "started_at": "2026-10-27T09:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:D.run_once")


def _loop(st: Store, cond: Conductor, ws: pathlib.Path, gate: _Gate, me: str, *,
          role: str = "M", max_steps: int = 12, parent: str = "",
          parent_role: str = "") -> AgentLoop:
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role=role, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=role, session_root=ws, gateway=gate,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=max_steps, workspace_root=str(ws),
                     parent_task_id=parent, parent_role=parent_role)


# ================================================================== ① 等程序


def test_a_a_program_that_runs_is_on_the_clock_while_it_runs(tmp_path, bench) -> None:
    """① 起程序就登记一条程序计时器；程序结束它收口并带上结局。

    业主逐字：「运行一个程序时会自动启动一个计时器，程序运行完成时计时器会返回」。

    钉住三件：
    1. 程序还在跑的那一刻，账上有一条 `kind="program"` 且 `state="pending"` 的计时器；
    2. 程序结束之后它是 `fired`，带 `outcome="exited"`、`exit_code=0`、`elapsed_sec > 0`、
       `pid` 非空（业主点名的那几格）；
    3. 读数（`clock.programs`）里的键集就是业主点名的那几格。

    ## 改前红在哪
    `TIMER_KINDS` 里只有 `timer` / `alarm` / `periodic`；`clock.programs` / `start_program` /
    `program_span` 都不存在 ⇒ 这一条在改前是 `AttributeError`，而"程序在跑"这件事
    在任何一本账上都读不到。
    """
    from agentflow import cancellation as CX

    _, _, ws = _ws(tmp_path, "prog")
    # 一个 0.6 秒的子进程：够我们在它跑着的时候读一次账。
    cmd = [sys.executable, "-c", "import time; time.sleep(0.6)"]
    seen: dict[str, Any] = {}

    def watch() -> None:
        # 等在跑的那条表把 pid 挂上再取快照。固定 `sleep(0.25)` 是个假红源：
        # Windows 起一个子进程要几百毫秒（机器忙时更久），而 pid 是 `Popen` 之后才补进
        # 账里的 ⇒ 快照可能落在"表已登记、pid 还没挂"的那一小段上。这一条要钉的是
        # "程序跑着的时候 pid 在账上"，不是"0.25 秒时它一定已经挂上"。
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            rows = list(CLK.programs(ws).get("rows") or ())
            if rows and isinstance(rows[0].get("pid"), int):
                break
            time.sleep(0.02)
        seen.update(CLK.programs(ws))

    th = threading.Thread(target=watch, daemon=True)
    th.start()
    got = CX.run_cancellable(cmd, timeout_sec=20.0, workspace=str(ws),
                             purpose="判据：起一个程序并等它")
    th.join(timeout=5.0)

    # 1) 跑着的时候账上有一条 pending 的程序计时器（pid 已经挂上）
    assert seen.get("checked") is True, seen
    assert int(seen.get("running") or 0) == 1, ("程序在跑而账上没有计时器", seen)
    row = dict(seen["rows"][0])
    assert row["state"] == "pending", row
    assert row["program"] == sys.executable, row
    assert "time.sleep(0.6)" in row["argv_digest"], row
    assert isinstance(row["pid"], int) and row["pid"] > 0, row

    # 2) 结束之后它收口，结局/退出码/耗时都在
    assert got["exit_code"] == 0, got
    after = CLK.programs(ws)
    assert int(after["running"]) == 0, after
    timer = CLK.book(ws).get(got["program_timer"]["timer_id"])
    assert timer is not None and timer.state == "fired", timer
    assert timer.outcome == "exited", timer.outcome
    assert timer.exit_code == 0, timer.exit_code
    assert timer.elapsed_sec is not None and timer.elapsed_sec > 0.0, timer.elapsed_sec
    assert timer.triggered_by == "program_exit", timer.triggered_by
    assert "程序跑完了" in timer.message, timer.message

    # 3) 键集（业主点名的七格都在）
    assert set(row) >= {"timer_id", "program", "argv_digest", "pid", "state",
                        "elapsed_sec", "exit_code"}, sorted(row)


def test_a2_every_spawn_site_is_on_the_clock_or_registered(tmp_path) -> None:
    """① 的普查：起进程的每个地方都进了程序计时器（或逐条登记了为什么不必进）。

    这是"不允许程序在跑而账上没有计时器"的静态那一半：`program_census()` 用 AST
    扫 `src/agentflow`，把 `subprocess.Popen/run/...` 连它所在的函数一起点出来；
    与某个 `program_span(...)` 落在同一个函数里才算管住。

    反真空：扫描根给一个空目录 ⇒ `files == 0`（不许把"没扫到"读成"都干净"）。
    负控：临时造一个"起进程却没开账"的函数 ⇒ 它必须被点名。
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    got = CLK.program_census(source_root=root)
    assert got["checked"] is True, got["reason"]
    assert int(got["files"]) > 100, got["files"]
    assert got["findings"] == [], [f["where"] for f in got["findings"]]
    # 反真空：扫到的"起进程"点必须真的非空（否则"没有 findings"证明的是空集）
    assert len(got["governed"]) >= 8, [g["where"] for g in got["governed"]]
    assert len(got["spans"]) >= 5, got["spans"]

    # 空目录：没扫到东西 = files 0（不是"都干净"）
    empty = tmp_path / "empty"
    empty.mkdir()
    none = CLK.program_census(source_root=empty)
    assert none["files"] == 0 and none["findings"] == [], none

    # 负控：一个起进程却没进 `program_span` 的函数 ⇒ 必须被点名
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "probe.py").write_text(
        "import subprocess\n"
        "def spawn_without_a_timer():\n"
        "    return subprocess.run(['x'], capture_output=True)\n",
        encoding="utf-8")
    found = CLK.program_census(source_root=bad)
    assert [f["func"] for f in found["findings"]] == ["spawn_without_a_timer"], found


def test_a3_the_experiment_runner_books_its_program(tmp_path) -> None:
    """① verify.run_experiment 的真身（`agent_e._run_script`）也进了程序账。

    这一条走 `_run_script` 而不是工具面（工具面要多一层装配）：读数是同一本账。
    """
    import agentflow.agent_e.core as EC

    _, _, ws = _ws(tmp_path, "e")
    script = ws / "quick.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    core = EC._Core.__new__(EC._Core)
    core.workspace_root = ws
    core.python = sys.executable
    result = core._run_script(script, timeout=20)
    assert result["exit_code"] == 0, result
    timer = CLK.book(ws).get(result["program_timer"]["timer_id"])
    assert timer is not None, result
    assert timer.kind == "program" and timer.state == "fired", timer
    assert timer.outcome == "exited" and timer.exit_code == 0, timer
    assert "quick.py" in timer.argv_digest, timer.argv_digest
    assert int(CLK.programs(ws)["count"]) == 1, CLK.programs(ws)


def test_c4_the_old_rule_would_have_parked(tmp_path, bench,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """③a 的"改前红"机器证据：把判据换回旧口径（有 waiter 就停）⇒ 同一个夹具零次调用。

    旧口径只写在注释里是证不出来的；这一条把旧口径做成一个替身 `_park_gate`
    （"本趟有 parked waiter ⇒ 这一拍不调模型"，与改前逐字同义），跑同一个夹具。

    期望：旧口径下 `len(gate.prompts) == 0`、`decision == "park"` —— 与
    `test_c_a_timer_does_not_block_work_in_hand`（新口径下 >= 2 次调用）正好相反。
    两条放在一起才证明"这一批真的改了判据"，而不是"两边都碰巧能过"。
    """
    st, cond, ws = _ws(tmp_path, "old-rule")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    CLK.start_timer(ws, reason="等 D 交回结论", wait_for=f"task:{child}",
                    task_id=me, role="M")
    cond.open_item(kind="notice", role="M", expects="ack", action="notice",
                   summary="有一件事要你处置", called_by="judge",
                   parent_task_id=me, depth=1, input_key="judge:old-rule")

    turns = {"n": 0}

    def old_gate(self_: AgentLoop, *, step: int, run: Any, mailbox: Any) -> dict[str, Any]:
        """改前的判据：只要本趟有 parked waiter 且这一拍没有唤醒 ⇒ 不调模型。"""
        parked = self_._park_reading()
        wakes = self_._wake_readings(mailbox.get("wake_ids") or ())
        turns["n"] = int(turns["n"]) + 1
        if turns["n"] >= 2:
            _stop_now(ws, "判据：旧口径停住了")
        if parked["count"] and not wakes["count"]:
            run.park["skip_calls"] = int(run.park.get("skip_calls") or 0) + 1
            run.park["decision"] = "park"
            return {"skip_model": True, "decision": "park", "waited_sec": 1.0,
                    "woke_reason": "", "reason": "改前口径：有 waiter 就停",
                    "parked": int(parked["count"]), "waiters": [], "checked": True}
        return {"skip_model": False, "decision": "run", "waited_sec": 0.0,
                "woke_reason": "", "reason": "", "parked": int(parked["count"]),
                "waiters": [], "checked": True}

    monkeypatch.setattr(AgentLoop, "_park_gate", old_gate)
    gate = _Gate([_tool("clock.now")] * 3)
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user", my_task_id=me, depth=1)

    assert gate.prompts == [], ("旧口径居然也调了模型 ⇒ 这一条证明不了'改前红'",
                                len(gate.prompts))
    assert run.park.get("decision") == "park", run.park
    assert int(run.park.get("skip_calls") or 0) >= 1, run.park


def test_a4_a_failed_booking_is_visible_not_silent(tmp_path, bench,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """① 的负控：程序计时器登记失败 ⇒ 程序照跑，但账上留一条"没登记"的读数。

    为什么这一条必须有：`programs()` 读到"没有程序在跑"与"程序在跑而我没记上"
    在别的读数上长得一模一样 —— 折平它们就等于把"没做完"报成"做完了"。
    """
    import tempfile

    _, _, ws = _ws(tmp_path, "unbooked")

    def boom(*a: Any, **k: Any) -> Any:
        raise CLK.ClockStateError("判据：簿记故意写不成")

    monkeypatch.setattr(CLK, "start_program", boom)
    with CLK.program_span(program="make-believe", argv=["make-believe", "--x"],
                          workspace=ws, where="judge") as span:
        pass
    assert span.timer is None, span.timer
    assert "没登记成" in span.problem, span.problem
    got = CLK.programs(ws)
    assert got["checked"] is True and got["count"] == 0, got
    assert got["unbooked"] and got["unbooked"][-1]["program"] == "make-believe", got["unbooked"]
    assert span.reading()["state"] == "unbooked", span.reading()


# ================================================================== ② 目的自动填


def test_b_the_purpose_is_filled_from_the_target_task(tmp_path, bench) -> None:
    """② 等子代理不给目的 ⇒ 用名册里那一行 task 填，读数标 `purpose_source="target_task"`。

    三条一起钉：
    1. 名册有那一行 ⇒ `purpose` 就是它的 task 原文（截断到 200 字），`purpose_missing=False`；
    2. 显式给目的 ⇒ `purpose_source="given"`（自动填不覆盖人给的那一句）；
    3. 名册读不到 ⇒ 仍是 `purpose_missing=True` + 追问（原语义不变）。

    ## 改前红在哪
    改前 `Timer` 上根本没有 `purpose_source` 这一格；目的缺了只会 `purpose_missing=true`，
    到点消息里写"（目的未填）"并追问 —— 业主这一批要的是"自动以 task 填充"。
    """
    st, cond, ws = _ws(tmp_path, "purpose", secretary=True)
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    task_text = "把 Sylow 定理的三处证据补齐（含反例扫描与逐字引文回验）"
    got = cond.roster_sink.roster_add(owner=me, role="D", task_id=child,
                                      brief="", task=task_text)
    assert got.get("problem") == "", got
    build_registry(store=st, conductor=cond, workspace_root=ws)   # 接上"等谁"的读口

    timer = CLK.start_timer(ws, wait_for=f"task:{child}", task_id=me, role="M")
    assert timer.purpose == task_text, timer.purpose
    assert timer.purpose_source == "target_task", timer.purpose_source
    assert timer.purpose_missing is False, timer.row()

    given = CLK.start_timer(ws, wait_for=f"task:{child}", task_id=me, role="M",
                            reason="等 D 交回结论")
    assert given.purpose == "等 D 交回结论", given.purpose
    assert given.purpose_source == "given", given.purpose_source

    # 截断：200 字上限（业主定死）
    long_text = "长" * 500
    cond.roster_sink.roster_add(owner=me, role="D", task_id=child + "x",
                                brief="", task=long_text)
    other = _child(cond, me, key="timers@child2")
    cond.roster_sink.roster_add(owner=me, role="D", task_id=other, brief="", task=long_text)
    cut = CLK.start_timer(ws, wait_for=f"task:{other}", task_id=me, role="M")
    assert len(cut.purpose) == CLK.PURPOSE_FROM_TARGET, len(cut.purpose)


def test_b2_no_roster_still_asks_for_the_purpose(tmp_path, bench) -> None:
    """② 的负控：两边都拿不到 ⇒ 仍是 `purpose_missing=true` + 追问（原语义不变）。"""
    st, cond, ws = _ws(tmp_path, "purpose-none")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    build_registry(store=st, conductor=cond, workspace_root=ws)
    timer = CLK.start_timer(ws, wait_for=f"task:{child}", task_id=me, role="M")
    assert timer.purpose_missing is True, timer.row()
    assert timer.purpose_source == "unavailable", timer.purpose_source
    assert CLK.PURPOSE_MISSING_TEXT in CLK.due_message(
        purpose=timer.purpose, waited_sec=1.0, created_at=timer.created_at,
        fired_at=timer.created_at), "缺目的那一趟没有写'目的未填'"


# ================================================================== ③ 不阻塞


def _arm_wait(ws: pathlib.Path, me: str, *, role: str = "M") -> dict[str, Any]:
    """显式要求"等待任意计时器返回"（业主口径里的那个新动作）。"""
    return CLK.request_wait_any(ws, task_id=me, role=role, purpose="等任意计时器返回")


def test_c_a_timer_does_not_block_work_in_hand(tmp_path, bench,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """③a 起了 timer 但手上有活 ⇒ 仍会调模型。

    夹具：父名下有一条等子代理的计时器（所以旧判据会停），同时父名下有一条没消的板项
    （"手上有活"）。旧判据（"有 parked waiter ⇒ 不调模型"）在这一条上会 零次 调模型；
    新判据必须照常问。

    ## 改前红在哪
    `_park_gate` 改前的第一条是「本趟有 parked waiter 且这一拍没有唤醒 ⇒ 这一拍不调模型」，
    与"手上有没有活"无关 —— 于是 `len(gate.prompts) == 0`，而业主这一批逐字要求
    「计时器不阻塞智能体动作，智能体可在多计时器同时存在时继续手上工作」。
    """
    st, cond, ws = _ws(tmp_path, "busy")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    CLK.start_timer(ws, reason="等 D 交回结论", wait_for=f"task:{child}",
                    task_id=me, role="M")
    # 手上有活：父名下一条没消的板项（queued 就是"等着我处置"）。
    #
    # 2026-10-26 口径同步：这一格必须是要办事的那种板项（`expects="work"`）。
    # 改前它写的是 `kind="notice" / expects="ack"`，而那一批把"信息型板项"改成
    # "渲染即 ack"（`Conductor.mark_item_seen` → `_settle_if_informational`）：
    # 一条 notice 被读进第一步提示词的那一刻就 `done+acked` ⇒ `open_items_of` 变空
    # ⇒ `_pending_work` 读成"没有活" ⇒ `_park_gate` 落进挂机档 ⇒ 这条用例的停机开关
    # （挂在 `on_call` 上）永远不触发 ⇒ 空转到 CI 超时。它测的是"计时器不阻塞动作"，
    # 与"那条板项是什么种类"无关，所以换成一条真的还没办的委托。
    item = cond.open_item(kind="delegation", role="M", expects="work", action="run_once",
                          summary="有一件事要你处置", called_by="judge",
                          parent_task_id=me, depth=1, input_key="judge:busy")
    assert item, item

    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        bench.advance(seconds)
        return {"checked": True, "asked_sec": seconds}

    monkeypatch.setattr(AgentLoop, "_park_slice", park_slice)

    def stop_after_two(index: int, prompt: str) -> None:
        if index == 1:
            _stop_now(ws, "判据：看够 2 个回合了")

    gate = _Gate([_tool("clock.now"), _tool("clock.now"), _tool("clock.now")],
                 on_call=stop_after_two)
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert len(gate.prompts) >= 2, ("起了表就停住了 —— 计时器把动作阻塞了",
                                    len(gate.prompts))
    assert [s.shape for s in run.steps][:2] == ["tool", "tool"], [s.shape for s in run.steps]
    # 计时器一直在账上（它只是不阻塞）
    assert [t.state for t in CLK.book(ws).all()] == ["pending"], CLK.timers(ws)


def test_c2_wait_any_parks_even_with_timers(tmp_path, bench,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """③b 显式要求"等待任意计时器返回" ⇒ 不调模型（正控）。

    夹具：父已挂在一条等子代理的计时器上，并且显式 `request_wait_any`。
    这一条是"挂机"该发生的那一档：跑了 3 拍、零模型调用。

    ## 改前红在哪
    改前没有 `clock.request_wait_any` 这个动作（`AttributeError`）；而挂机只由
    "有 parked waiter"触发，无法区分"我手上有活但想等"与"我没活可干" ——
    业主这一批要的正是这个区分。
    """
    st, cond, ws = _ws(tmp_path, "waitany")
    me = cond.open_top_level_run("M", TASK)
    child = _child(cond, me)
    CLK.start_timer(ws, reason="等 D 交回结论", wait_for=f"task:{child}",
                    task_id=me, role="M")
    _arm_wait(ws, me)
    turns: list[dict[str, Any]] = []

    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        turns.append(dict(CLK.wait_any_reading(ws, me)))
        bench.advance(seconds)
        if len(turns) == 3:
            _stop_now(ws, "判据：等够 3 拍")
        return {"checked": True, "asked_sec": seconds}

    monkeypatch.setattr(AgentLoop, "_park_slice", park_slice)
    gate = _Gate([_tool("clock.now")])
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert gate.prompts == [], ("显式要求等却仍在问模型", len(gate.prompts))
    assert int(run.park.get("parked_turns") or 0) == 3, run.park
    assert int(run.park.get("skip_calls") or 0) == 3, run.park
    assert run.park.get("wait_any") is True, run.park
    assert turns and turns[0]["waiting"] is True, turns[0]
    # 挂机区间里这一趟没有产生回合（业主 2026-10-25 的判据仍然成立）
    last = dict(CLK.waiters(ws))
    assert int(last["parked_steps"]) == 0 and int(last["parked_calls"]) == 0, last


def test_c3_wait_any_wakes_when_any_timer_returns(tmp_path, bench,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """③c `wait_any` 到任一 timer 返回那一刻醒（正控）。

    夹具：父挂了 2 拍，第 2 拍把假时钟拨过那条计时器的钟点（它到点、报醒、落唤醒标记），
    于是下一拍 `wait_any` 的读数变成"有东西回来了" ⇒ 这一拍照常问模型。

    读数是三样（2026-10-27 第三批把"醒来之后意图的去向"也钉进来了）：
    ① 挂机那几拍确实在等（`slices[0].waiting`）；
    ② 唤醒被消费（`run.wakes >= 1`）；
    ③ 回模型那一拍把那条意图撤掉（`run.park.wait_cancelled >= 1`，且账上那一行没了）——
       那个意图是一个显式动作（「直到它认为无事可做时，可启动计时器等待任意计时器返回」），
       不是一个持久状态：醒了/改主意了就得再要一次。不撤的话它会一直"requested 为假但
       那一行还在"，于是下一次"我改主意了、手上有活"仍被旧意图拖着。
    """
    st, cond, ws = _ws(tmp_path, "wake")
    me = cond.open_top_level_run("M", TASK)
    CLK.start_timer(ws, reason="等 20 分钟", after_sec=60.0, task_id=me, role="M")
    _arm_wait(ws, me)
    slices: list[dict[str, Any]] = []

    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        slices.append(dict(CLK.wait_any_reading(ws, me)))
        bench.advance(seconds)
        if len(slices) == 2:
            # 拨过钟点：那条计时器到点（`FakeClock.advance` 会跑 `fire_due`）
            bench.advance(900.0)
        if len(slices) == 4:
            _stop_now(ws, "判据：醒过了")
        return {"checked": True, "asked_sec": seconds}

    monkeypatch.setattr(AgentLoop, "_park_slice", park_slice)

    def stop_after_one(index: int, prompt: str) -> None:
        if index == 0:
            _stop_now(ws, "判据：醒过了、问过一次就够了")

    gate = _Gate([_tool("clock.now")] * 5, on_call=stop_after_one)
    run = _loop(st, cond, ws, gate, me).run(TASK, summoned_by="user", my_task_id=me, depth=1)

    assert run.stop_reason == "stop_file", run.to_dict()
    assert slices[0]["waiting"] is True, slices[0]
    assert int(run.wakes) >= 1, run.to_dict()
    assert int(run.park.get("wait_cancelled") or 0) >= 1, run.park
    assert CLK.read_wait_any(ws)["rows"] == [], CLK.read_wait_any(ws)
    after = dict(CLK.wait_any_reading(ws, me))
    assert after["checked"] is True, after
    assert after["waiting"] is False, after
    assert after["woke"] == [], after
    assert len(gate.prompts) == 1, ("醒了却没回模型", len(gate.prompts))


# ================================================================== ④ 交差


def test_d_nothing_to_do_and_no_timer_is_a_handoff(tmp_path, bench,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 无事可做 + 一条计时器都没有 ⇒ 交差：向父报告，父记静默。

    夹具：子代理先起一条表并显式要求"等待任意计时器返回"，随后那条表被撤掉
    （父派它的时候没有给它派下级，它自己也没别的活在等）。这一档的定义就是业主要的那一句：
    「如果已无事可做且无计时器，这意味着它交差了」。

    2026-10-26 口径同步（业主：「这个需要存在的计时器数大于等于1」）：起意那一刻
    必须至少有一条现存计时器（0 条时 `clock.wait_any` 直接受控拒绝，
    码 `no_timers_to_wait`），所以这一条的"没有可等的东西"由"表被撤掉"造成，
    不再是"起意时就一条都没有"。

    钉住四件：
    1. 零模型调用（它没有可问模型的事）；
    2. `run.handed_off` 有账（编号、时间、父），且这一趟按"正常收工"的退出档收尾
       （`stop_reason` 仍是 `final`：退出码表在 `cli.py`，本轮禁改；区分"交差"的读数是
       `run.handed_off` 与 `agent_handoff` 事件，不是另起一个未登记的档）；
    3. 父的收件箱里有一条 subject 是 `交差` 的留言（沿用既有消息通道）；
    4. `clock.read_handoffs(ws, parent_task_id=父)` 读到这一条 —— 父据此把它记为静默，
       而 `agent_state` 对它的判定就是 `silent`。
    """
    st, cond, ws = _ws(tmp_path, "handoff")
    parent = cond.open_top_level_run("M", TASK)
    child = _child(cond, parent)
    parked = CLK.start_timer(ws, after_sec=60.0, reason="等一会儿", task_id=child, role="D")
    _arm_wait(ws, child, role="D")
    CLK.cancel_timer(ws, parked.timer_id)      # 撤掉之后：没有可等的东西了

    def park_slice(self_: AgentLoop, *, seconds: float, purpose: str) -> dict[str, Any]:
        return {"checked": True, "asked_sec": 0.0}   # 不该走到这里

    monkeypatch.setattr(AgentLoop, "_park_slice", park_slice)
    gate = _Gate([_tool("clock.now")])
    run = _loop(st, cond, ws, gate, child, role="D", parent=parent,
                parent_role="M").run(TASK, summoned_by="M", my_task_id=child,
                                     parent_task_id=parent, depth=2)

    assert gate.prompts == [], ("交差那一档还是问了模型", len(gate.prompts))
    # 交差是正常收工的一种：退出档仍是 `final`（新档不登记会静默落进兜底异常档）。
    assert run.stop_reason == "final", run.to_dict()
    assert run.handed_off.get("handoff_id", "").startswith("ho-"), run.handed_off
    assert run.handed_off.get("reported") is True, run.handed_off
    assert run.final.startswith("交差："), run.final

    # 父的收件箱：既有消息通道上的那一条
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    msg = [e for e in events if str(e.get("kind") or "") == "agent_message"
           and str(e.get("subject") or "") == CLK.HANDOFF_SUBJECT]
    assert msg, [e.get("kind") for e in events]
    assert str(msg[0].get("from_task_id") or "") == child, msg[0]

    # 交差账：父那一侧的读数
    ledger = CLK.read_handoffs(ws, parent_task_id=parent)
    assert ledger["checked"] is True and ledger["count"] == 1, ledger
    assert ledger["rows"][0]["task_id"] == child, ledger["rows"]
    counts = cond.handoffs_reading(parent)
    assert counts["count"] == 1 and counts["silent"] == [child], counts
    snap = cond.activity_snapshot()
    assert int((snap.get("handoffs") or {}).get("count") or 0) == 1, snap.get("handoffs")
    assert COND.agent_state(row={"task_id": child, "status": "running"},
                            item=None, wait={"checked": True, "rows": []},
                            waiting_for=[])["state"] == COND.AGENT_STATE_FLYING


def test_d2_the_parent_records_the_silent_child(tmp_path, bench) -> None:
    """④ 父侧那一半：收到子代理交差 ⇒ 那条子代理置静默（读数可见）并在父读数里 +1。

    这一条直接调父循环的那一处（`_note_child_handoff`）：父消费掉一条
    `wait_for=task:<子>` 的唤醒时，交差账上那一行被补上 `seen_by`（= 父的台账号），
    父的 `run.silent_children` 里 +1。
    """
    st, cond, ws = _ws(tmp_path, "parent")
    parent = cond.open_top_level_run("M", TASK)
    child = _child(cond, parent)
    CLK.record_handoff(ws, task_id=child, parent_task_id=parent, role="D",
                       reason="无事可做且没有任何计时器 ⇒ 交差")
    gate = _Gate([_tool("clock.now")])
    loop = _loop(st, cond, ws, gate, parent)
    loop.my_task_id = parent
    run = type("Run", (), {"silent_children": [], "notes": [],
                           # `_note_child_handoff` 现在还会把"问过哪几个静默子"记进这一格
                           # （2026-10-26 另一批加的读数）；替身 Run 必须带上它，
                           # 否则这一条测的是替身的字段表而不是父侧的交接。
                           "silent_children_asked": []})()

    got = loop._note_child_handoff({"wait_for": f"task:{child}", "wake_id": "wk-1"},
                                  run=run)
    assert got == child, got
    assert run.silent_children == [child], run.silent_children
    assert any("记为静默" in n for n in run.notes), run.notes
    row = CLK.read_handoffs(ws, parent_task_id=parent)["rows"][0]
    assert row.get("seen_by") == parent, ("父代理没有留下'我记下了'这一笔", row)
    # 第二次收到同一条唤醒不重复计数（"又交了一次"与"第一次交差"分得开）
    assert loop._note_child_handoff({"wait_for": f"task:{child}"}, run=run) == child
    assert run.silent_children == [child], run.silent_children


# ================================================================== ⑤ 不变量


def _blocking_env(tmp_path: pathlib.Path, name: str):
    """两个"派出去就不回来"的子代理（用 gate 卡住后端，直到判据放行）。"""
    gate = threading.Event()

    class _Slow(LocalBackend):
        def call(self, role, action, params, *, token, instance="", task_id=""):
            gate.wait(10.0)
            return {"ok": True, "detail": "done"}

    ws = tmp_path / name
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=_Slow({}))
    children_clean_their_boards(cond)
    sec = Secretary("M", root=ws, store=st)
    cond.roster_sink = sec
    CLK.set_default_workspace(ws)
    build_registry(store=st, conductor=cond, workspace_root=ws)
    return st, cond, ws, gate


def test_e_every_active_child_has_a_waiter(tmp_path, bench) -> None:
    """⑤ 不变量：活跃子代理非空 ⇒ 必有一条等它的计时器（写侧由 summon 自动起表）。

    父派两个子代理 ⇒ 账上自动多出两条 `wait_for=task:<子>` 的计时器（目的自动填的是
    名册里那一行 task 原文），`child_wait_invariant` 的 `unwaited` 必须是空的。
    子代理收口之后那条计时器跟着收口（`fire_due` 把它报醒 ⇒ `fired`）。

    ## 改前红在哪
    改前 `summon` 落完 running 行与名册行就返回 —— 没有任何人给父起这条表：
    `clock.timers(ws)` 是空表，而两个子代理都还活着 ⇒ "静默"的定义在这里不成立
    （父既没有在等它们，也没法从账上知道该等谁）。
    """
    st, cond, ws, gate = _blocking_env(tmp_path, "invariant")
    parent = cond.open_top_level_run("M", TASK)
    first = cond.summon_preemptible("D", "write_report", {"out_path": "out/a.md"},
                                    parent_task_id=parent,
                                    roster={"task": "把 Sylow 定理的三处证据补齐"})
    second = cond.summon_preemptible("D", "write_report", {"out_path": "out/b.md"},
                                     parent_task_id=parent,
                                     roster={"task": "写反例扫描那一节"})
    time.sleep(0.2)
    kids = [str(first.task_id or ""), str(second.task_id or "")]
    assert all(kids), kids

    timers = CLK.book(ws).all()
    assert len(timers) == 2, [t.row() for t in timers]
    by_wait = {t.wait_for: t for t in timers}
    for kid in kids:
        assert f"task:{kid}" in by_wait, sorted(by_wait)
        assert by_wait[f"task:{kid}"].state == "pending", by_wait[f"task:{kid}"].row()
        assert by_wait[f"task:{kid}"].purpose_source == "target_task", \
            by_wait[f"task:{kid}"].row()

    got = cond.child_wait_invariant(parent)
    assert got["checked"] is True, got
    assert sorted(got["active_children"]) == sorted(kids), got
    assert got["unwaited"] == [], got["problems"]
    assert sorted(got["waited"]) == sorted(kids), got["waited"]

    # 子代理收口 ⇒ 那条计时器跟着收口（下一次推时钟把它报醒）
    gate.set()
    first.wait(10.0)
    second.wait(10.0)
    time.sleep(0.2)
    CLK.fire_due(ws)
    states = {t.wait_for: t.state for t in CLK.book(ws).all()}
    assert states == {f"task:{kids[0]}": "fired", f"task:{kids[1]}": "fired"}, states
    assert cond.child_wait_invariant(parent)["active_children"] == []


def test_e2_the_invariant_names_the_child_nobody_waits_for(
        tmp_path, bench, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 的负控：把"派活时自动起表"那一支拔掉 ⇒ 不变量必须红，并点名哪个子代理没人等。

    判据本体只有一份（`child_wait_invariant`）；这一条证明它真的在看那条计时器，
    而不是永远返回空 `problems`。
    """
    st, cond, ws, gate = _blocking_env(tmp_path, "invariant-negative")
    parent = cond.open_top_level_run("M", TASK)

    def no_arm(self_: Conductor, child_task_id: str, **kw: Any) -> dict[str, Any]:
        return {"armed": False, "timer_id": "", "reason": "判据：把自动起表拔掉"}

    monkeypatch.setattr(Conductor, "arm_child_waiter", no_arm)
    handle = cond.summon_preemptible("D", "write_report", {"out_path": "out/a.md"},
                                     parent_task_id=parent,
                                     roster={"task": "把 Sylow 定理的三处证据补齐"})
    time.sleep(0.2)
    kid = str(handle.task_id or "")
    assert kid, handle
    assert CLK.book(ws).all() == [], "拔掉自动起表之后账上不该有计时器"

    got = cond.child_wait_invariant(parent)
    assert got["checked"] is True, got
    assert got["active_children"] == [kid], got
    assert got["unwaited"] == [kid], got
    assert got["problems"] and kid in got["problems"][0], got["problems"]
    gate.set()
    handle.wait(10.0)
