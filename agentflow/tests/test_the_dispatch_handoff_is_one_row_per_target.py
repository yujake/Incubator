# -*- coding: utf-8 -*-
"""判据：`summon_many` 的派活留痕按目标拆条（不再是一条 `to=ALL` 的通报）。

## 真机（2026-10-28，`projects/paper-rewrite-78c` 16:11:53）

M 第 13 步一次 `summon_many` 派了 A、D、D 三个目标，而它没填 `notify` ⇒ 框架代笔。
代笔出来的是一条 `to="ALL"` 的手稿（`m000004`，6147 字节），正文把三条派活拼在一起。
两头都不对：

- 留痕与派活不一一对应：三条互不相同的活共用一条通报，按任务号查不到自己那一张；
- `ALL` 在公共频道的可见面是"发信人的直接子"（`public_visibility` 的 `instance` 档）
  ⇒ 三个孩子各自读到的是另外两路的派活全文（A 是只读检索者，读到"方向A 的攻坚任务"）；
- 页面把 `to` 直译成 "ALL"，读起来像"发给所有人"。

## 这一组守什么

1. 正题：派生支在多目标时 ⇒ N 条，`to` 各是各的目标角色，正文只含它自己那一条；
2. 单目标 ⇒ 仍是一条、`to` 是那个角色（老行为逐字不变）；
3. 模型自己写了 `notify` 的那一支不动：多目标仍是一条、缺省 `to="ALL"`
   （判据 `tests/test_forced_notify.py` 那条，与这里并存）；
4. 反真空：拆条的条数必须等于目标数，且不许多写一个 `to="ALL"`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Sequence

from agentflow import manuscripts as MS
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "probe-notify-split"


class _Gate:
    """按剧本回话的替身缝（每回合取一条）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: Sequence[Any]) -> None:
        self.replies = list(replies)
        self.seen: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.seen.append(prompt)
        text = self.replies[min(len(self.seen) - 1, len(self.replies) - 1)]
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "", "error_kind": ""})()


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    build_registry(store=st, conductor=cond, workspace_root=ws)
    return st, cond, ws


def _run(tmp_path: pathlib.Path, replies: list[Any], *, role: str = "M"):
    from agentflow.agent_loop import run_role
    from agentflow.llmseam import LlmSeam

    st, cond, ws = _ws(tmp_path)
    gate = _Gate(replies)
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    run = run_role(role, "派活并收工", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role=role, session_root=ws, gateway=gate, price=(0.0, 0.0),
                                sid=SID),
                   session_root=ws, workspace_root=str(ws), sid=SID, max_steps=6,
                   from_env=False)
    return ws, run, gate


TWO = {"summon_many": {"targets": [
    {"role": "D", "task": "派活：把这条猜想立起来并登记", "params": {"statement": "甲"}},
    {"role": "E", "task": "派活：跑一次实验", "params": {"claim": "乙"}}],
    "why": "两条并行"}}
FINISH = {"final": "派完了"}


def test_the_derived_notify_is_one_row_per_target(tmp_path: pathlib.Path):
    """正题：两个目标（模型没填 notify）⇒ 两条留痕、各投各的、正文不串。"""
    ws, run, _gate = _run(tmp_path, [TWO, {"tool": "conductor.retire_child",
                                           "args": {"child_name": "D1"}},
                                     {"tool": "conductor.retire_child",
                                      "args": {"child_name": "E1"}},
                                     FINISH])
    rows = [r for r in MS.rows(ws)]
    tos = sorted(str(r.get("to")) for r in rows)
    assert len(rows) == 2, rows
    assert tos == ["D", "E"], tos
    assert "ALL" not in tos, tos
    # 每条只含它自己那一条派活（不串）
    by_to = {str(r.get("to")): json.dumps(r, ensure_ascii=False) for r in rows}
    assert "甲" in by_to["D"] or "猜想" in by_to["D"], by_to["D"][:200]
    assert "乙" not in by_to["D"], "D 那条里串进了 E 的派活"
    assert "乙" in by_to["E"] or "实验" in by_to["E"], by_to["E"][:200]
    assert "甲" not in by_to["E"], "E 那条里串进了 D 的派活"


def test_a_single_target_keeps_one_row_addressed_to_it(tmp_path: pathlib.Path):
    """单目标 ⇒ 仍是一条、`to` 是那个角色（老行为逐字不变）。"""
    one = {"summon": {"role": "D", "task": "派活：把这条猜想立起来", "params": {"statement": "甲"}}}
    ws, _run_obj, _gate = _run(tmp_path, [one, {"tool": "conductor.retire_child",
                                                "args": {"child_name": "D1"}}, FINISH])
    rows = MS.rows(ws)
    assert len(rows) == 1, rows
    assert rows[0]["to"] == "D", rows[0]


def test_the_model_written_notify_still_goes_out_as_one_public_note(tmp_path: pathlib.Path):
    """模型自己写了 `notify`（没写 to）⇒ 仍是一条 `to="ALL"`：它写的是一段共同的话。"""
    payload = {**TWO, "summon_many": {**TWO["summon_many"],
                                      "notify": {"summary": "派两条活",
                                                 "body": "## 派什么活\n甲 + 乙。\n"}}}
    ws, _run_obj, _gate = _run(tmp_path, [payload,
                                          {"tool": "conductor.retire_child",
                                           "args": {"child_name": "D1"}},
                                          {"tool": "conductor.retire_child",
                                           "args": {"child_name": "E1"}}, FINISH])
    rows = MS.rows(ws)
    assert len(rows) == 1, rows
    assert rows[0]["to"] == "ALL", rows[0]


def test_the_step_result_says_how_many_rows_were_written(tmp_path: pathlib.Path):
    """这一步的结果里能读出写了几条（拆条之后"一条"与"两条"必须分得开）。"""
    ws, run, _gate = _run(tmp_path, [TWO, {"tool": "conductor.retire_child",
                                           "args": {"child_name": "D1"}},
                                     {"tool": "conductor.retire_child",
                                      "args": {"child_name": "E1"}}, FINISH])
    hand = run.steps[0].result.get("dispatch_handoff") or {}
    assert hand.get("count") == 2 and hand.get("ok") is True, hand
    assert isinstance(hand.get("items"), list) and len(hand["items"]) == 2, hand
