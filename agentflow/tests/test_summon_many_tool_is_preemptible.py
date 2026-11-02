# -*- coding: utf-8 -*-
"""2026-11-02（83 · M 零回合 113 分钟）：`conductor.summon_many` 的工具入口也必须可抢占。

## 这一份钉的是什么

83 的真机读数（只读复算）：M 第 11 步调的是原生工具 `conductor.summon_many`
（`agent_step.payload.name` 就是那个名字），这一个调用阻塞 6 778 秒
（llm_call 04:51:18 → agent_step 06:44:19），父代理 113 分钟零回合，顶趟行一直 `running`，
直到人工写 `.agentflow-stop` 才落 `done/no_result`。

根因不是"没有可抢占"——形状路径 `_do_summon_many` 自 2026-10-24（D-64）起就是可抢占的
（≤ `CHILD_STEP_WAIT_SEC` 返场）。根因是「同一件事有两条拼法、只修了一条」：

```
工具入口：conductor_tools.conductor_summon_many → Conductor.run_plan(calls)   # 默认 preemptible=False
                                                         └→ WaveHandle.results() → wait_all()  # 无 timeout
形状入口：agent_loop._do_summon_many            → run_plan(calls, preemptible=True)
                                                         └→ 句柄进挂账 + 返场投递
```

| 条 | 判据 | 改前红在哪 |
|---|---|---|
| a | 走工具入口派 3 个长活 ⇒ 第二次模型调用时 3 条子行还在跑，且 elapsed < 5s | 改前工具阻塞到最后一个孩子跑完，第二次调用只可能在「0 条在跑」之后 |
| b | 句柄进了本循环的挂账，返场点能把结果投回来（含孩子的结论与记录路径） | 改前句柄被丢在工具里，返场没有对象 |
| c | 返回里有 `preempted` / `dispatched` / `running`，且工具原来声明的老键（`max_wave` / `elapsed_sec` / `why`）一个不少 | 改前只有终局那一份（`preempted` 不存在） |
| d | 反真空：`PREEMPTIBLE_DISPATCH=False` ⇒ 退回阻塞形态（`running_count == 0`、没有挂账） | 这一条是「a/b/c 真的在测抢占」的机器证明 |

## 夹具为什么不睡觉

「跑很久」由 `threading.Event` 造（与 `test_summon_is_preemptible.py` 同一手法）：
孩子的 handler 卡在等放行上，判据自己决定什么时候放行。`_BlockingBackend` 的等待上限
故意压到 2 秒：改前那一趟会阻塞在「等全部落定」上，2 秒后以一句可读的话失败，
而不是把整份判据挂成 60 秒的假死。
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
from typing import Any, Mapping

import pytest

from agentflow import agent_loop as AL
from agentflow.agent_loop import AgentLoop, run_role
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.policy import Policy
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "smt"
#: 父必须是 M：`conductor.summon_many` 的工具声明里 `roles=("M",)`（调用期角色判据在
#: `tools/base.py`），用别的角色会先被 `role_denied` 拒掉，这条判据就没有对象。
ROLE = "M"
KID = "C"           # C 没有出边 ⇒ 不会有孙辈搅进读数
TASK = "2026-11-02 判据夹具：工具入口派出去几个跑很久的活"

LOOK = json.dumps({"tool": "fs.list", "args": {"path": "."}}, ensure_ascii=False)
#: 问用户、零超时 ⇒ 停在等。它是这一档唯一干净的出口：`final` 会被"孩子在跑"拒掉，
#: `stop`/预算会把直接子翻成 block（见 `test_a_child_cut_off_at_parent_exit_is_its_own_tier.py`
#: 的判据 d），两者都会把"孩子还在跑"这一格提前抹掉。
ASK = json.dumps({"ask_user": {"question": "口径用哪个？", "timeout_sec": 0}},
                 ensure_ascii=False)

TARGETS = [{"target_role": KID, "task": f"第 {i} 件长活", "instance": str(i)}
           for i in (1, 2, 3)]
TOOL_MANY = json.dumps({"tool": "conductor.summon_many",
                        "args": {"targets": TARGETS, "why": "判据：三个长活"}},
                       ensure_ascii=False)


class _BlockingBackend:
    """派出去就卡住的后端：它只保证子代理真的还在跑。"""

    name = "blocks"

    def __init__(self, wait_timeout: float = 2.0) -> None:
        self.gate = threading.Event()
        self.wait_timeout = float(wait_timeout)
        self._lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []

    # ---- Conductor 只用到这三样
    def known_roles(self) -> list[str]:
        return [KID]

    def resolve(self, role: str, instance: str = "") -> Any:  # pragma: no cover - 接口需要
        return self

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        with self._lock:
            self.calls.append({"role": str(role), "instance": str(instance),
                               "task_id": str(task_id)})
        if not self.gate.wait(timeout=self.wait_timeout):
            return {"outcome": "no_result",
                    "detail": "判据：等放行超时（说明有谁没有在等孩子）"}
        return {"outcome": "ok", "detail": f"{role} 的活跑完了",
                "payload": {"llm_run_path": f"out/tasks/{task_id or 'x'}.json",
                            "final": f"{role}#{instance or '-'} 的结论"}}

    def entered(self) -> int:
        with self._lock:
            return len(self.calls)

    def release(self) -> None:
        self.gate.set()


class _Gate:
    """照剧本回答的替身模型：记下每一次提示词，`on_call(i)` 在第 i 次调用返回之前跑。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str], on_call: Any = None) -> None:
        self.replies = list(replies)
        self.on_call = on_call
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(index)
        text = self.replies[min(index, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


@pytest.fixture()
def fast_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """三个等待压到毫秒，并把挂机那一支隔离掉（理由同上一个判据文件）。"""
    original = AL.AgentLoop.__init__

    def patched(self: Any, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        self.child_step_wait_sec = 0.05
        self.child_return_wait_sec = 0.05
        self.child_exit_drain_sec = 0.05

    monkeypatch.setattr(AL.AgentLoop, "__init__", patched)
    monkeypatch.setattr(
        AL.AgentLoop, "_park_gate",
        lambda self, **kw: {"skip_model": False, "decision": "run",
                            "checked": True, "reason": "判据：照常问模型"})


def _env(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, Conductor, _BlockingBackend]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    backend = _BlockingBackend()
    cond = Conductor(st, policy=Policy(), backend=backend)
    return ws, st, cond, backend


def _registry(st: Store, cond: Conductor, ws: pathlib.Path) -> Any:
    return build_registry(store=st, conductor=cond, workspace_root=ws).registry


def _top_row(st: Store) -> dict:
    rows = [dict(r) for r in st.rows("tasks") if str(r.get("action") or "") == "run"]
    assert rows, "台账里没有顶趟那一行"
    return rows[-1]


def _kids(st: Store, parent: str) -> dict[str, dict]:
    return {str(r["task_id"]): dict(r) for r in st.rows("tasks")
            if str(r.get("parent_task_id") or "") == parent
            and not str(r.get("kind") or "")}


def _in_flight(st: Store, parent: str) -> list[str]:
    return [tid for tid, row in _kids(st, parent).items()
            if str(row.get("status") or "") == "running"]


def _step_of(run: Any, shape: str) -> dict[str, Any]:
    got = [s.result for s in run.steps if s.shape == shape]
    assert got, f"这一趟没有 {shape} 那一步：{[s.shape for s in run.steps]}"
    return got[0]


# ============================================================ a + b：父拿得到回合
def test_the_tool_entry_returns_before_the_children_finish(
        tmp_path: pathlib.Path, fast_loop: None) -> None:
    """判据 a + b：走工具入口派 3 个长活 ⇒ 第二次模型调用时孩子还在跑，result 照常回来。

    改前红：工具入口是阻塞档（`run_plan()` → `results()`），第二次模型调用只可能发生在
    "三个都跑完"之后 —— 真机形态就是 83 的 M：113 分钟零回合。
    """
    ws, st, cond, backend = _env(tmp_path)
    seen: dict[str, Any] = {"began": time.monotonic()}

    def on_call(index: int) -> None:
        if index == 1:
            seen["elapsed"] = time.monotonic() - seen["began"]
            seen["in_flight"] = _in_flight(st, _top_row(st)["task_id"])
            seen["entered"] = backend.entered()
            backend.release()

    gate = _Gate([TOOL_MANY, LOOK, ASK, ASK], on_call=on_call)
    run = run_role(ROLE, TASK, store=st, registry=_registry(st, cond, ws),
                   conductor=cond, session_root=ws, sid=SID, from_env=False,
                   seam=LlmSeam(role=ROLE, session_root=ws, gateway=gate,
                                price=(0.0, 0.0), sid=SID),
                   max_steps=20)

    """一、父代理第二次被问到时，三个孩子真的还在跑。"""
    assert len(gate.prompts) >= 2, gate.prompts
    assert seen.get("entered") == 3, ("三个孩子的 handler 没有都进去过：",
                                     seen.get("entered"), backend.calls)
    assert len(seen.get("in_flight") or []) == 3, (
        "父代理第二次被问到时名下只剩 "
        f"{len(seen.get('in_flight') or [])} 个在跑（要求 3）⇒ 工具入口仍然阻塞", seen)
    assert seen.get("elapsed", 99.0) < 5.0, (
        f"第二次模型调用花了 {seen.get('elapsed'):.2f}s —— 父代理又被工具入口阻塞住了", seen)

    """二、那一步的返回是「已派出 / 还在跑」，不是终局。"""
    payload = _step_of(run, "tool")
    data = payload.get("data") or {}
    assert data.get("preempted") is True, data
    assert len(data.get("dispatched") or []) == 3, data
    assert len(data.get("running") or []) == 3, data
    assert data.get("running_count") == 3, data
    assert {i["status"] for i in data["results"]} == {"running"}, data["results"]

    """三、句柄进了本循环的挂账（返场点从它取结果），孩子最后都落终态。"""
    assert any("返场" in str(n) for n in run.notes), run.notes
    kids = _kids(st, _top_row(st)["task_id"])
    assert len(kids) == 3, kids
    assert all(str(r["status"]) == "done" for r in kids.values()), kids


def test_the_folding_point_delivers_the_tool_children(tmp_path: pathlib.Path,
                                                      fast_loop: None) -> None:
    """判据 b（直接测那个点）：句柄挂上 ⇒ 放行后 `_children_round_trip` 能投回结果。

    改前红：工具入口把句柄丢在工具里，`_child_handles` 是空的 —— 这一段没有对象。
    """
    ws, st, cond, backend = _env(tmp_path)
    me = cond.open_top_level_run(ROLE, TASK)
    loop = AgentLoop(role=ROLE, session_root=ws, registry=_registry(st, cond, ws),
                     conductor=cond,
                     seam=LlmSeam(role=ROLE, session_root=ws, gateway=_Gate([ASK]),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=4, workspace_root=str(ws))
    loop.my_task_id = me
    loop.child_step_wait_sec = 0.05
    loop.child_return_wait_sec = 2.0
    loop.child_exit_drain_sec = 0.05

    out = loop._do_tool({"name": "conductor.summon_many",
                         "args": {"targets": TARGETS}})
    assert out.get("ok") is True, out
    data = out.get("data") or {}
    assert data.get("preempted") is True, data
    assert len(loop._children_running()) == 3, loop._child_handles

    backend.release()
    got: dict[str, Any] = {}
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        got = loop._children_round_trip(step=1, run=AL.LoopRun(role=ROLE, task=TASK),
                                        wait=True)
        if got.get("settled") and loop._children_running() == []:
            break
    assert got.get("settled"), ("工具入口派出去的孩子没有返场投递", got)
    text = str(got.get("text") or "")
    assert "的结论" in text, text            # 孩子的结论
    assert "out/tasks/" in text, text        # 孩子的完整记录路径
    assert loop._children_running() == [], loop._child_handles


# ============================================================ c：老键一个不少
def test_the_tool_payload_keeps_every_declared_key(tmp_path: pathlib.Path,
                                                   fast_loop: None) -> None:
    """判据 c：可抢占那一路只「加」键，工具原来声明的那几个一个不少。

    为什么单列一条：`conductor.summon_many` 的 `returns=` 是对模型与调用方的契约
    （`count` / `ok_count` / `refused_count` / `failed_count` / `waves` / `max_wave` /
    `concurrent_peak` / `elapsed_sec` / `why` / `results`）。把工具入口改成共用形状路径
    时，`_do_summon_many` 的那套键（`summoned` / `running_count` / `preempted` …）是新增，
    老键必须留着 —— 否则"修了一条拼法"变成"改了另一条契约"。
    """
    ws, st, cond, backend = _env(tmp_path)
    me = cond.open_top_level_run(ROLE, TASK)
    loop = AgentLoop(role=ROLE, session_root=ws, registry=_registry(st, cond, ws),
                     conductor=cond,
                     seam=LlmSeam(role=ROLE, session_root=ws, gateway=_Gate([ASK]),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=4, workspace_root=str(ws))
    loop.my_task_id = me
    loop.child_step_wait_sec = 0.05
    loop.child_exit_drain_sec = 0.05

    out = loop._do_tool({"name": "conductor.summon_many",
                         "args": {"targets": TARGETS, "why": "老键的判据"}})
    data = out.get("data") or {}
    for key in ("count", "ok_count", "refused_count", "failed_count", "waves",
                "max_wave", "concurrent_peak", "elapsed_sec", "why", "results"):
        assert key in data, (f"工具声明的 `{key}` 不见了", sorted(data))
    assert data.get("why") == "老键的判据", data
    assert len(data.get("results") or []) == len(TARGETS), data["results"]
    # 新增的那几格也在（"只加不减"的另一半：加了没接上等于没加）。
    assert data.get("preempted") is True, data
    assert data.get("running_count") == 3, data
    backend.release()


# ============================================================ d：反真空
def test_without_preemption_the_tool_entry_falls_back_to_blocking(
        tmp_path: pathlib.Path, fast_loop: None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 d（反真空）：把抢占打桩成不抢占 ⇒ 工具入口必退回阻塞形态。

    这一条是「a/b/c 真的在测抢占」的机器证明：没有它，`preempted=True` 有可能只是被
    别的东西（别的形状、别的投递通道）满足的，那样的判据什么都没钉住。
    """
    monkeypatch.setattr(AL, "PREEMPTIBLE_DISPATCH", False)
    ws, st, cond, backend = _env(tmp_path)
    backend.release()          # 阻塞档会一直等到孩子跑完 ⇒ 必须先放行，否则自己锁死自己
    me = cond.open_top_level_run(ROLE, TASK)
    loop = AgentLoop(role=ROLE, session_root=ws, registry=_registry(st, cond, ws),
                     conductor=cond,
                     seam=LlmSeam(role=ROLE, session_root=ws, gateway=_Gate([ASK]),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=4, workspace_root=str(ws))
    loop.my_task_id = me
    loop.child_step_wait_sec = 0.05
    loop.child_exit_drain_sec = 0.05

    out = loop._do_tool({"name": "conductor.summon_many", "args": {"targets": TARGETS}})
    data = out.get("data") or {}
    assert not data.get("preempted"), data
    assert data.get("running_count", 0) == 0, data
    assert loop._child_handles == [], loop._child_handles
    assert sorted(i["status"] for i in data["results"]) == ["done"] * 3, data["results"]
    # 老键在不抢占那一档也照旧（两条路只差"抢不抢"，不差契约）。
    assert data.get("max_wave", 0) >= 1 and "elapsed_sec" in data, sorted(data)
