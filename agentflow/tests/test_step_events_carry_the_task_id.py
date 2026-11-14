# -*- coding: utf-8 -*-
"""判据：步级记录（`agent_step`，及 `runs/*.json` 的 steps）必须带这一趟的台账号。

## 现场（`temp/analysis/11-ledger-causes.md` ①，2026-11-14 lp-ball 真机）

拒信的两个载体**都没有台账号**：`runs/*.json` 的 `steps[]` **0/551**、
`sessions` 的 `agent_step` **0/564**。后果是"哪条 task 被拒了几次"在盘上答不了 ——
本次 B 的 19 条拒落在 t-000017 / t-000050 / t-000058 / t-000076 哪几行，只能靠时间窗猜；
而本次 F 有**两个并发实例**（t-000008 / t-000009，同秒起跑），按 `(role, index)` 配对直接撞键。

号**本来就在循环手上**：`agent_run_start` 已经带它（29/29）、`tasks` 那行的号也是它
（`self.my_task_id`）。缺的是"每一份作业都把这一格插进去"—— 同一个号，三条载体，
只有一条带了。这一组钉的就是另外两条。

## 判据三件事

1. 正控：离线真跑一趟（替身模型、0 元）⇒ **每一条** `agent_step` 都带 `task_id`，
   且号等于这一趟 `tasks` 行的号、也等于 `agent_run_start` 那一条的号（三处同一份）；
2. run 步：同一趟落下的 `runs/<角色>-<时间戳>-<序号>.json` 里，顶层与 `steps[]`
   每一格都带同一个号；
3. 反真空：把注入打桩成"不写"（`_step_task_id` 恒返回空串）⇒ 第 1 条必须红。

改前红：第 1、2 条（`agent_step` / run 步的键集里根本没有 `task_id`）。
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import sessions as SS
from agentflow.agent_loop import RUNS_DIR_NAME, LlmBackend
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

#: 替身模型的花销口径：0 元（这一组判据不许花钱）。
FREE = (0.0, 0.0)


class _ScriptedGateway:
    """照剧本回答的替身模型（接口与真模型一致；本判据只看事件，不看模型。"""

    spec = SimpleNamespace(model="scripted", api_key="fake", base_url="", temperature=0.2)

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        del scope, system, kw
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return SimpleNamespace(ok=True, text=text, tokens_in=10, tokens_out=10,
                               scope="reason", attempts=1,
                               error_kind="", error_detail="")


def _replies() -> list[str]:
    """三步：一条正常步、一条解析不了的坏 JSON（步级拒信的同族形态）、收工。

    为什么要那一坏步：它的落点与正常步**不是同一个写入口**（`run()` 里的收尾段 vs
    `_land_unusable`），只钉正常步会让"另一个写口忘了插号"永远看不见。
    """
    return [json.dumps({"note": "先记一句进度"}, ensure_ascii=False),
            "这不是 JSON",
            json.dumps({"final": "这一趟做完了", "evidence": []}, ensure_ascii=False)]


def _one_run(tmp_path: pathlib.Path) -> tuple[Any, str, pathlib.Path]:
    """离线真跑一趟 `LlmBackend.call`，返回 `(run, 这一趟的号, 工作区根)`。"""
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    gw = _ScriptedGateway(_replies())

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=root, gateway=gw, price=FREE, sid="test-step")

    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=seam_factory, max_steps=4, store=st, sid="test-step")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond)
    backend.registry = built.registry
    task_id = cond.open_top_level_run("A", "起一趟（判据：步级记录带号）")
    backend.call("A", "", {"_task_id": task_id}, token=None, task_id=task_id)
    return st, task_id, root


def _events(root: pathlib.Path) -> list[dict]:
    events, problems = SS.read_session(root, sid="test-step")
    assert not problems, problems
    return events


def _steps(events: list[dict]) -> list[dict]:
    return [e for e in events if str(e.get("kind")) == "agent_step"]


def _task_rows(st: Store, task_id: str) -> list[dict]:
    return [dict(r) for r in st.rows("tasks") if str(r.get("task_id")) == task_id]


# ============================================================ 1 正控：每条步都带号
def test_every_step_event_carries_the_runs_own_task_id(tmp_path: pathlib.Path) -> None:
    """判据 1：`agent_step` **全带号**，且与 `agent_run_start` / 台账行三处同一份。

    改前：`agent_step` 的键集里根本没有 `task_id`（真机 0/564）⇒ "这条步是哪条 task 的"
    只能按角色 + 时间窗猜；并发同角色的两个实例连猜都猜不开。
    """
    st, task_id, root = _one_run(tmp_path)
    events = _events(root)
    steps = _steps(events)
    assert len(steps) >= 2, f"这一趟至少该有两步（正常步 + 坏 JSON 步）：{[e.get('kind') for e in events]}"

    ids = [str(s.get("task_id") or "") for s in steps]
    assert all(ids), f"有步没带号（改前形态）：{ids}；键集={sorted(steps[0])}"
    assert set(ids) == {task_id}, f"步上的号不是这一趟的号：{sorted(set(ids))} vs {task_id!r}"

    starts = [e for e in events if str(e.get("kind")) == "agent_run_start"]
    assert starts and str(starts[-1].get("task_id") or "") == task_id, starts

    rows = _task_rows(st, task_id)
    assert rows, "台账里没有这一趟的行 ⇒ 判据失去对照"

    # 步号不许被这次改动带走：坏的那一步照旧在，且形状如实是 invalid。
    assert "invalid" in [str(s.get("shape") or "") for s in steps], (
        f"坏 JSON 那一步没落成 invalid：{[s.get('shape') for s in steps]}")


# ============================================================ 2 run 步也带号
def test_the_run_artifact_steps_carry_the_same_task_id(tmp_path: pathlib.Path) -> None:
    """判据 2：`runs/<角色>-<时间戳>-<序号>.json` 的顶层与每一步都带同一个号。

    这一条是"两份载体互有缺口"的另一半：`runs/*.json` 的 `steps[]` 真机 0/551，
    于是 10 条只落在 runs 的 `notify_problem` 连"属于哪条 task"都答不了。
    """
    _st, task_id, root = _one_run(tmp_path)
    files = sorted((root / RUNS_DIR_NAME).glob("A-*.json"))
    assert len(files) == 1, [p.name for p in files]
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert str(payload.get("task_id") or "") == task_id, (
        f"run 文件顶层没带这一趟的号：{payload.get('task_id')!r}")
    steps = list(payload.get("steps") or [])
    assert steps, "这一趟的 run 文件里没有 steps ⇒ 判据失去对象"
    assert [str(s.get("task_id") or "") for s in steps] == [task_id] * len(steps), (
        f"run 文件里有步没带号：{[s.get('task_id') for s in steps]}")


# ============================================================ 3 反真空
def test_stubbing_the_injection_writes_no_id(tmp_path: pathlib.Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 3（反真空）：把注入打桩成"不写" ⇒ 判据 1 必须红。

    没有这一条，判据 1 可能只是"键碰巧存在"（例如某个空串被当成了号）。
    打桩的是 `agent_loop._step_task_id` —— `agent_step` 取号的唯一一处。
    """
    monkeypatch.setattr(AL, "_step_task_id", lambda loop: "", raising=False)
    _st, _task_id, root = _one_run(tmp_path)
    steps = _steps(_events(root))
    assert steps, "这一趟一步都没走 ⇒ 判据失去对象"
    ids = [str(s.get("task_id") or "") for s in steps]
    assert not any(ids), (
        f"注入被打桩成不写之后步上还有号 ⇒ 这一条没在测注入：{ids}")
    assert all("task_id" in s for s in steps), "键还在、只是空 —— '没写'与'没这一格'要分得开"
