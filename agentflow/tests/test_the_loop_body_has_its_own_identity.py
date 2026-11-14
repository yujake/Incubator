# -*- coding: utf-8 -*-
"""判据：模型循环本体（`LlmBackend.call`）里跑的那一段，必须带着这一趟的台账号。

## 现场（`temp/analysis/11-ledger-causes.md` ② B 组，2026-11-14 lp-ball 真机）

11 笔 `scope=reason` 的账无主（$0.002238），全是循环本体发的秘书判定
（`secretary:tool_name` 10 条 + `secretary:dispatch_fit` 1 条）。它们走
`secretary.judge` ⇒ `llmseam.ask_json` ⇒ `_land` 的兜底 `ambient_task_id()`，
而那个 ContextVar 全仓只有两个挂点：`conductor.calling_as`（只包 `registry.call`）
与 `LocalBackend.call`（只包确定性 handler）。模型驱动那一趟是 `LlmBackend.call`，
它一个挂点都没有 —— 循环明明知道自己是谁（`self.my_task_id`），却没把号传下去。

反证（同一份会话）：从工具 handler / 确定性 handler 里发的秘书判定
（`v_reply_defect` 16/16、`proposition_form` 7/7、`statement_keywords` 5/5）28/28 有主；
只有从循环本体发的 11 条全空。差别不在"秘书"这一层，在调用它的是哪一段。

## 这一组钉三件事

1. 正控：`LlmBackend.call` 跑一趟（离线替身模型、0 元）⇒ 循环里每一次模型调用
   看到 `conductor.current_task_id()` 都等于这一趟 `tasks` 行的号；
2. 不泄漏：这一趟返回之后 `current_task_id()` 回到空串（`finally` 复位）；
3. 反真空：把 `calling_as` 打桩成"不挂"（`nullcontext`）⇒ 第 1 条必须红。

改前红：第 1 条（循环里读到的 ambient 全是空串）；第 2、3 条本来就该绿。
"""
from __future__ import annotations

import contextlib
import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest

from agentflow import conductor as CO
from agentflow.agent_loop import LlmBackend
from agentflow.conductor import Conductor, LocalBackend, current_task_id
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

#: 替身模型的花销口径：0 元（这一组判据不许花钱）。
FREE = (0.0, 0.0)


class _AmbientProbeGateway:
    """照剧本回答的替身模型；每次 `complete` 记下那一刻的召唤号。

    接口与真模型一致（`tests/test_run_end_events_carry_the_task_id.py` 那只同形），
    多出来的只有 `ambients` 这一格读数 —— 它就是"循环本体有没有挂点"的探针。
    """

    spec = SimpleNamespace(model="scripted", api_key="fake", base_url="", temperature=0.2)

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.ambients: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        del scope, system, kw
        # 探针就在这一行：生产上秘书的 `judge` 也是在同一种上下文里发出去的。
        self.ambients.append(current_task_id())
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return SimpleNamespace(ok=True, text=text, tokens_in=10, tokens_out=10,
                               scope="reason", attempts=1,
                               error_kind="", error_detail="")


def _one_run(tmp_path: pathlib.Path, *, final: str) -> tuple[Any, str, list[str], Any]:
    """离线真跑一趟 `LlmBackend.call`（替身模型 + 0 元价），返回后端/号/读到的 ambient/store。"""
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    gw = _AmbientProbeGateway([json.dumps({"final": final, "evidence": []},
                                          ensure_ascii=False)])

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=root, gateway=gw, price=FREE, sid="test-hook")

    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=seam_factory, max_steps=2, store=st, sid="test-hook")
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond)
    backend.registry = built.registry
    task_id = cond.open_top_level_run("A", "起一趟（判据：循环本体的身份）")
    return backend, task_id, gw.ambients, st


def _call(backend: Any, task_id: str) -> dict:
    return dict(backend.call("A", "", {"_task_id": task_id}, token=None, task_id=task_id))


# ============================================================ 1 正控：循环里有号
def test_the_loop_body_sees_the_runs_own_task_id(tmp_path: pathlib.Path) -> None:
    """判据 1：`LlmBackend.call` 里每一次模型调用都看得见这一趟的号。

    改前：`ambients` 全是空串 ⇒ 秘书从循环本体发的判定在账上无主（真机 11 笔）。
    """
    backend, task_id, ambients, _st = _one_run(tmp_path, final="这一趟做完了")
    _call(backend, task_id)

    assert ambients, "这一趟一次模型调用都没发生 ⇒ 判据失去对象"
    assert all(a == task_id for a in ambients), (
        "循环本体里的模型调用读不到这一趟的台账号："
        f"读到 {sorted(set(ambients))!r}，应当是 {task_id!r}")


# ============================================================ 2 不泄漏
def test_the_identity_does_not_leak_out_of_the_run(tmp_path: pathlib.Path) -> None:
    """判据 2：这一趟返回之后，调用方的上下文必须回到空串（挂点用 `finally` 复位）。"""
    backend, task_id, _ambients, _st = _one_run(tmp_path, final="这一趟做完了")
    assert current_task_id() == "", "判据开始前就已经有号了 ⇒ 这一条测不到复位"
    _call(backend, task_id)
    assert current_task_id() == "", (
        "`calling_as` 没复位：号漏给了调用方，下一笔无关的花销会挂到这一趟上")


# ============================================================ 3 反真空
def test_stubbing_the_hook_puts_the_orphans_back(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 3（反真空）：把挂点打桩成"不挂" ⇒ 判据 1 必须红。

    没有这一条，判据 1 可能只是"号本来就在别处飘着"。打桩的是
    `conductor.calling_as` 本身（`LlmBackend.call` 现取的那个挂点）。
    """
    monkeypatch.setattr(CO, "calling_as",
                        lambda *a, **k: contextlib.nullcontext(), raising=True)
    backend, task_id, ambients, _st = _one_run(tmp_path, final="这一趟做完了")
    _call(backend, task_id)

    assert ambients, "这一趟一次模型调用都没发生 ⇒ 判据失去对象"
    assert all(a == "" for a in ambients), (
        "挂点被打桩成不挂之后循环里还读得到号 ⇒ 这一条没在测 `LlmBackend.call` 的挂点")
    assert all(a != task_id for a in ambients)
