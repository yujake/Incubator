# -*- coding: utf-8 -*-
"""判据：M 的顶趟（`run_role` 起的那一趟）里发出去的模型调用也要带台账号。

## 现场（AH3，2026-11-17，真机 `projects/lp-ball-2`）

`usage_ledger` 里 3 行 `task_id=""`、`role=M`、`$0.000458`，note 是
「调用方没给 task_id，且不在任何 ambient 里」。它们不是本体循环的调用（那些由
循环显式传 `task_id=self.my_task_id`，同一份账里 26/26 有主），而是循环体里发出去的
秘书判定（`secretary:tool_name`）：`Secretary.judge` 不传 `task_id`，归口只能靠
`ambient_task_id()`。

全仓的 ambient 挂点只有两个：`_do_tool`（只包 `registry.call`）与
`LlmBackend.call`（模型驱动的子代理那一趟）。M 的顶趟走的是
`agent_loop.run_role` —— 它在 `14587` 已经拿到了 `top_tid`，可 `loop.run(...)` 那
两处都没有 `calling_as` 包住 ⇒ 循环体里的秘书判定读到的 ambient 是空串。

## 这一组钉四件事

1. 正控：真跑一趟 M 顶趟（离线替身模型、0 元），触发一次 `secretary:tool_name`
   判定 ⇒ 那条 `llm_call` 事件的 `task_id` 等于顶趟台账行的号，账本里它那一行
   也归到同一个号；
2. 账目：`reconcile_usage(store)["unattributed"]["count"] == 0`（这条路径上没有
   无主花销）；
3. 收行：顶趟自己那一行 `task_end` 也落本趟会话（真机 48 条里就有它；收行发生在
   `loop.run` 返回之后，只有把 `_close_top` 一起包住才落得对）；
4. 反真空：把 `calling_as` 打桩成"不挂"（`nullcontext`）⇒ 第 1、3 条必须红
   （判定那一行的 `task_id` 回到空串，无主计数 ≥ 1，顶趟 `task_end` 回到缺省会话）。

改前红：第 1、2、3 条（顶趟循环体里的每一次模型调用读到的 ambient 都是空串，
顶趟收行也没有会话身份）。
"""
from __future__ import annotations

import contextlib
import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest

from agentflow import conductor as CO
from agentflow import modelcost as MC
from agentflow import sessions as SS
from agentflow.agent_loop import run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam, ambient_task_id
from agentflow.secretary import for_role as secretary_for_role
from agentflow.store import Store
from agentflow.tokenmeter import TokenMeter
from agentflow.tools import build_registry

#: 替身模型的花销口径：0 元（这一组判据不许花钱）。
FREE = (0.0, 0.0)
SID = "top-ambient"
#: 缺省会话的固定名（`AGENTFLOW_SESSION`）：真机两文件形态里的那份"缺省文件"。
FALLBACK_SID = "top-fallback"
ROLE = "M"
TASK = "夹具：M 顶趟派一件活（判据：循环体里的秘书判定带号）"
JUDGE_NOTE = "secretary:tool_name"


class _ProbeGateway:
    """照剧本回答的替身模型；每次 `complete` 记下那一刻的 ambient 台账号。

    接口与真模型一致。判定的那一次调用（`system` 是 `_judge_system` 的短题面，
    75k 的角色提示词不会走这里）回一个 `tool_name` 词表里的结论；循环本体第一步
    回一条带 `name` 的 `summon`（`name` 不是注册表里的真名 ⇒ 预筛报警 ⇒ 秘书判
    `tool_name`），之后回 `final`。
    """

    spec = SimpleNamespace(model="scripted", api_key="fake", base_url="", temperature=0.2)

    def __init__(self) -> None:
        self.ambients: list[str] = []
        self.prompts: list[str] = []
        self.loop_calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        del scope, kw
        self.ambients.append(ambient_task_id())
        self.prompts.append(prompt)
        short_system = len(str(system or "")) < 4000
        if short_system:
            text = json.dumps({"decision": "建议改派", "reason": "判据夹具",
                               "basis": ["判据夹具"]}, ensure_ascii=False)
        else:
            self.loop_calls += 1
            if self.loop_calls == 1:
                text = json.dumps({"summon": {"role": "B", "action": "", "name": "B",
                                              "task": "判据夹具：给 B 一件活"}},
                                  ensure_ascii=False)
            else:
                text = json.dumps({"final": "判据夹具做完了", "evidence": []},
                                  ensure_ascii=False)
        return SimpleNamespace(ok=True, text=text, tokens_in=10, tokens_out=10,
                               scope="reason", attempts=1, kind="", error_kind="",
                               error_detail="")


def _one_run(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, _ProbeGateway]:
    """离线真跑一趟 M 顶趟，返回 `(工作区根, store, 替身模型)`。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    gw = _ProbeGateway()
    seam = LlmSeam(role=ROLE, session_root=ws, gateway=gw, price=FREE, sid=SID,
                   meter=TokenMeter(st))
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    built = build_registry(store=st, conductor=cond, workspace_root=ws)
    secretary = secretary_for_role(ROLE, root=ws, store=st, registry=built.registry,
                                   seam=seam, enable_model=True, sid=SID)
    run_role(ROLE, TASK, store=st, registry=built.registry, conductor=cond, seam=seam,
             session_root=ws, workspace_root=str(ws), sid=SID, max_steps=2,
             from_env=False, secretary=secretary)
    return ws, st, gw


def _top_tid(st: Store) -> str:
    """这一趟顶层的绝对编号（`open_top_level_run` 落的那一行）。"""
    rows = [r for r in st.rows("tasks")
            if str(r.get("action") or "") == "run"
            and str(r.get("called_by") or "") == "user"]
    assert len(rows) == 1, f"顶趟行应当恰好一条：{rows}"
    return str(rows[0].get("task_id") or "")


def _judge_events(ws: pathlib.Path) -> list[dict]:
    """会话里那一次 `secretary:tool_name` 判定（`llm_call` 事件）。"""
    events, problems = SS.read_session(ws, sid=SID)
    assert not problems, problems
    return [e for e in events
            if str(e.get("kind") or "") == "llm_call"
            and str(e.get("note") or "") == JUDGE_NOTE]


def _usage_row(st: Store, usage_id: str) -> dict:
    rows = [dict(r) for r in st.rows("usage_ledger")
            if str(r.get("usage_id") or "") == usage_id]
    assert len(rows) == 1, f"账本里找不到 {usage_id!r}：{rows}"
    return rows[0]


def _task_ends(ws: pathlib.Path, sid: str) -> list[dict]:
    """读某一份会话里的 `task_end`（文件不存在 = 一条都没有，不是错误）。"""
    if not SS.session_path(ws, sid).is_file():
        return []
    events, problems = SS.read_session(ws, sid=sid)
    assert not problems, problems
    return [e for e in events if str(e.get("kind") or "") == "task_end"]


# ============================================================ 1 正控：判定带号
def test_the_top_runs_secretary_judgement_carries_the_task_id(
        tmp_path: pathlib.Path) -> None:
    """判据 1：M 顶趟里发出去的秘书判定，`llm_call` 与账本两处都归到顶趟的号。

    改前：`llm_call.task_id=""`、账本行 `task_id=None`（真机 3 笔、$0.000458）。
    """
    ws, st, gw = _one_run(tmp_path)
    top = _top_tid(st)
    judges = _judge_events(ws)
    assert len(judges) == 1, (
        f"这一趟该恰好触发一次 {JUDGE_NOTE} 判定："
        f"{[e.get('note') for e in judges]}")
    event = judges[0]
    assert str(event.get("task_id") or "") == top, (
        f"秘书判定那一行的 task_id 不是顶趟的号：{event.get('task_id')!r} vs {top!r}")

    ledger = event.get("ledger") if isinstance(event.get("ledger"), dict) else {}
    usage_id = str(ledger.get("usage_id") or "")
    assert usage_id, f"判定那一次没有账本行可核：{event.get('ledger')}"
    row = _usage_row(st, usage_id)
    assert str(row.get("task_id") or "") == top, (
        f"账本那一行没归到顶趟的号：{row.get('task_id')!r} vs {top!r}")

    # 反真空的正面：循环体里每一次模型调用都读得到同一个号（不只判定那一次）。
    assert gw.ambients, "这一趟一次模型调用都没发生 ⇒ 判据失去对象"
    assert set(gw.ambients) == {top}, (
        f"循环体里的模型调用读到的 ambient 不是顶趟的号：{sorted(set(gw.ambients))!r}")


# ============================================================ 2 账目：无主 0
def test_no_unattributed_usage_on_the_top_run_path(tmp_path: pathlib.Path) -> None:
    """判据 2：M 顶趟这条路径上，`unattributed.count` 必须是 0。"""
    _ws, st, _gw = _one_run(tmp_path)
    reading = MC.reconcile_usage(st)
    unattributed = reading.get("unattributed") or {}
    assert int(unattributed.get("count") or 0) == 0, (
        f"这条路径上仍有无主花销：{unattributed}")


# ============================================================ 3 顶趟的 task_end
def test_the_top_rows_task_end_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 3：顶趟自己那一行 `task_end` 也落本趟会话（真机 48 条里就有它）。

    为什么这一条必须在：`finish_top_level_run` 发生在 `loop.run` 返回之后/异常兜底
    里，调用方的上下文已经不在了。只在 `loop.run` 外面包 `calling_as` 而不包收行
    那一处，M 自己那一行仍会落进缺省会话（真机 `lp-ball-2` 的 48 条 `task_end`
    里恰好有一条 `role=M`）。
    """
    monkeypatch.setenv(SS.ENV_SESSION, FALLBACK_SID)
    ws, st, _gw = _one_run(tmp_path)
    top = _top_tid(st)
    real = _task_ends(ws, SID)
    mine = [e for e in real if str(e.get("task_id") or "") == top]
    assert len(mine) == 1, (
        f"顶趟自己的 task_end 没落本趟会话：{[(e.get('task_id'), e.get('role')) for e in real]}")
    assert "sid_problem" not in mine[0], mine[0]
    assert _task_ends(ws, FALLBACK_SID) == [], (
        "顶趟的 task_end 仍落进了缺省会话（AH4 的真机形态）")


# ============================================================ 4 反真空
def test_stubbing_the_ambient_hook_puts_the_orphans_back(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 4（反真空）：把 `calling_as` 打桩成"不挂" ⇒ 判据 1 必红。

    打桩的是 `run_role` 现取的那个挂点（`from .conductor import calling_as`），
    不是把 `_one_run` 换掉 —— 换掉实现证明不了"判据会在真实现上红"。
    同一次打桩也把顶趟的 `task_end` 打回缺省会话（判据 3 的另一半）。
    """
    monkeypatch.setenv(SS.ENV_SESSION, FALLBACK_SID)
    monkeypatch.setattr(CO, "calling_as",
                        lambda *a, **k: contextlib.nullcontext(), raising=True)
    ws, st, gw = _one_run(tmp_path)
    top = _top_tid(st)
    judges = _judge_events(ws)
    assert len(judges) == 1, f"这一趟该恰好触发一次判定：{[e.get('note') for e in judges]}"
    event = judges[0]
    assert str(event.get("task_id") or "") == "", (
        f"挂点被打桩成不挂之后判定还带号 ⇒ 这一条没在测挂点：{event.get('task_id')!r}")

    ledger = event.get("ledger") if isinstance(event.get("ledger"), dict) else {}
    usage_id = str(ledger.get("usage_id") or "")
    assert usage_id, event.get("ledger")
    row = _usage_row(st, usage_id)
    assert str(row.get("task_id") or "") == "", (
        f"挂点被打桩之后账本行还有号：{row.get('task_id')!r}")
    reading = MC.reconcile_usage(st)
    assert int((reading.get("unattributed") or {}).get("count") or 0) >= 1, reading
    assert gw.ambients and set(gw.ambients) == {""}, (
        f"挂点被打桩之后还读得到号 ⇒ 这一条没在测挂点：{sorted(set(gw.ambients))!r}")
    # 判据 3 的另一半：收行那一处也被同一个桩打回缺省（并在行上说明 why）。
    fallback = _task_ends(ws, FALLBACK_SID)
    mine = [e for e in fallback if str(e.get("task_id") or "") == top]
    assert len(mine) == 1, fallback
    assert str(mine[0].get("sid_problem") or ""), mine[0]
    assert not [e for e in _task_ends(ws, SID)
                if str(e.get("task_id") or "") == top], (
        "挂点被打桩成不挂之后顶趟的 task_end 还在本趟会话里")
    assert top, "顶趟号是空的 ⇒ 判据失去对照"
