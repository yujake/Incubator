# -*- coding: utf-8 -*-
"""判据（D-09）：子代理这一趟到底干成没有，必须写进 `tasks.outcome`。

## 真机（2026-10-28，`projects/paper-rewrite-78-backup`，逐条从盘上抄下来）

```
t-000008 G  run.stop_reason=model_unreachable → tasks.outcome=ok
t-000012 G  run.stop_reason=stop_file         → tasks.outcome=ok
t-000015 G  run.stop_reason=stop_file         → tasks.outcome=ok
三条的 detail 逐字都是：「执行完成（handler 未声明 outcome，按有产出处理）」
```

同一份台账里，顶趟是对的（M 两次都是 `no_result`）—— 因为
`Conductor.finish_top_level_run` 看了 `stop_reason`（`final` 才算 ok）。子行那条路没看：
`LlmBackend.call` 回的结果里既没有 `status` 也没有 `outcome`，收行时落进
`conductor.py` 的"`status=done` 且没声明 outcome ⇒ 按有产出处理 ⇒ ok"。

后果不是漂亮话：父代理读 `conductor.board` / `ledger` 时，被用户叫停的、被断网打断的
子代理，与真正交了差的子代理长得一模一样。这正是本项目在引文、OCR、D 溯源、C 预算
四处反复踩的同一个坑：把"没做成"读成"做成了"。

## 这一组守什么

1. 只有 `final` 算 ok：`STOP_REASONS` 里每一个登记过的理由都要有一档，且不许多出第二个 ok；
2. 三档各归各：被叫停 ⇒ `cancelled`；没连上/没接线 ⇒ `failed`（必须带原因）；
   跑完了没结论 ⇒ `no_result`；
3. 端到端：真跑一条子循环（走 `LlmBackend` + `Conductor.summon`），看任务行上的那两格，
   而不是只看那个纯函数；
4. 反真空：没登记的新理由不许落到 ok；正控（`final` 仍然 ok）也在，免得"修过头"。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import schema as S
from agentflow.agent_loop import LlmBackend, task_outcome_of_loop_stop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.stop_reasons import STOP_REASONS
from agentflow.store import Store
from agentflow.tools import build_registry


# ---------------------------------------------------------------- 替身模型


class _Scripted:
    """按脚本回话的替身（与 `tests/test_stop_switch_is_consumed_once.py` 同形）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.calls += 1
        text = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


class _NoReply:
    """"从不返回可用回复"的替身：`ok=False` + `error_kind="network"`（断网那一档）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.calls += 1
        return type("Reply", (), {"ok": False, "text": "", "tokens_in": 0, "tokens_out": 0,
                                  "error_kind": "network",
                                  "error_detail": "gaierror: [Errno 11001] getaddrinfo failed"})()


FINISH = json.dumps({"final": "交差"}, ensure_ascii=False)


# ---------------------------------------------------------------- 装配


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    Store(ws).init()
    return ws


def _conductor(ws: pathlib.Path, gw: Any, *, max_steps: int = 6,
               stop_file: str = "") -> tuple[Store, Conductor]:
    st = Store(ws)
    backend = LlmBackend(
        inner=LocalBackend({}),
        # 空动作也走循环（S2「只派活」）：登记 ("E", "") 这一格即可。
        loops={("E", ""): {"max_steps": max_steps}},
        session_root=ws,
        seam_factory=lambda role: LlmSeam(role=role, session_root=ws, gateway=gw,
                                          price=(0.0, 0.0), sid="s"),
        max_steps=max_steps, store=st, sid="s", stop_file=stop_file)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    backend.registry = build_registry(store=st, conductor=cond).registry
    return st, cond


def _row(st: Store, task_id: str) -> dict:
    for r in st.rows("tasks"):
        if str(r.get("task_id")) == str(task_id):
            return r
    raise AssertionError(f"tasks 里没有 {task_id}")


def _summon_e(cond: Conductor) -> Any:
    return cond.summon("E", "", {"task": "跑一趟，看看结局怎么写进台账"}, by="M")


# ---------------------------------------------------------------- 1) 纯口径


def test_only_the_final_stop_reason_counts_as_ok():
    """`STOP_REASONS` 里每一档都要有任务级结局，且只有 `final` 算 ok。

    反真空两半：① 表要点名到每一档（新加一个 stop_reason 而没人归类 ⇒ 这里红，
    而不是静默落进缺省）；② "只有一档是 ok"这句话本身由 `== ["final"]` 说出来。
    """
    bad: list[str] = []
    ok_reasons: list[str] = []
    for reason in STOP_REASONS:
        status, outcome = task_outcome_of_loop_stop(reason)
        if outcome not in S.TASK_OUTCOMES:
            bad.append(f"{reason}: outcome={outcome!r} 不在 TASK_OUTCOMES")
        if status not in ("done", "failed"):
            bad.append(f"{reason}: status={status!r} 只允许 done/failed")
        if (status == "failed") != (outcome == "failed"):
            bad.append(f"{reason}: status={status!r} 与 outcome={outcome!r} 不自洽")
        if outcome == "ok":
            ok_reasons.append(reason)
    assert not bad, "停止理由 → 任务结局 的映射有毛病：\n  " + "\n  ".join(bad)
    assert ok_reasons == ["final"], (
        f"算作 ok 的停止理由只能有 `final` 一个，实际 {ok_reasons} —— "
        "多一个就等于把「没干成」写成「干成了」")


def test_an_unregistered_stop_reason_is_never_ok():
    """反真空：没登记过的新理由 ⇒ `no_result`（缺省不许是 ok）。

    这条是"下一次有人加一档 stop_reason 又忘了归类"的护栏：那时台账会落 `no_result`
    （跑完了、没结论），而不是凭空多一条"成功"。
    """
    assert task_outcome_of_loop_stop("some_brand_new_reason") == ("done", "no_result")
    assert task_outcome_of_loop_stop("") == ("done", "no_result")


def test_the_three_dispositions_are_told_apart():
    """三档各归各：叫停 ⇒ cancelled；断网 ⇒ failed；跑完没结论 ⇒ no_result。"""
    assert task_outcome_of_loop_stop("stop_file") == ("done", "cancelled")
    assert task_outcome_of_loop_stop("budget") == ("done", "cancelled")
    assert task_outcome_of_loop_stop("interrupted_by_parent") == ("done", "cancelled")
    assert task_outcome_of_loop_stop("model_unreachable") == ("failed", "failed")
    assert task_outcome_of_loop_stop("max_steps") == ("done", "no_result")
    assert task_outcome_of_loop_stop("final_refused") == ("done", "no_result")


# ---------------------------------------------------------------- 2) 端到端（任务行）


def test_a_child_that_finishes_is_still_ok(tmp_path: pathlib.Path):
    """正控（不许修过头）：子循环正常收工 ⇒ 任务行 `done / ok`。"""
    ws = _ws(tmp_path)
    st, cond = _conductor(ws, _Scripted([FINISH]))
    res = _summon_e(cond)
    assert res.status == "done" and res.outcome == "ok", (res.status, res.outcome)
    row = _row(st, res.task_id)
    assert row["status"] == "done" and row["outcome"] == "ok", row


def test_a_child_that_lost_the_model_is_failed_with_a_reason(tmp_path: pathlib.Path):
    """D-09 的正题：子循环以 `model_unreachable` 收场 ⇒ 任务行必须是 `failed` ＋ 原因。

    真机形态：G 跑 826 秒后断网，台账上却是 `ok`，`final` 里躺着框架那句停止通告。
    """
    ws = _ws(tmp_path)
    st, cond = _conductor(ws, _NoReply())
    res = _summon_e(cond)
    assert res.status == "failed" and res.outcome == "failed", (res.status, res.outcome)
    row = _row(st, res.task_id)
    assert row["status"] == "failed" and row["outcome"] == "failed", row
    assert str(row.get("error") or "").strip(), f"失败的行必须写原因：{row}"
    assert "没拿到可用的回复" in str(row.get("error")), row["error"]
    # 停止理由本身仍然要在载荷里（修复不许把这一格吃掉）
    assert str((res.payload or {}).get("stop_reason")) == "model_unreachable", res.payload


def test_a_child_stopped_by_the_switch_is_cancelled(tmp_path: pathlib.Path):
    """被用户叫停的子代理 ⇒ `done / cancelled`（不是 ok，也不是 failed）。"""
    ws = _ws(tmp_path)
    switch = ws / ".agentflow-stop"
    switch.write_text('{"reason": "user", "by": "test"}', encoding="utf-8")
    st, cond = _conductor(ws, _Scripted([FINISH]), stop_file=str(switch))
    res = _summon_e(cond)
    assert res.status == "done" and res.outcome == "cancelled", (res.status, res.outcome)
    row = _row(st, res.task_id)
    assert row["status"] == "done" and row["outcome"] == "cancelled", row
    assert str((res.payload or {}).get("stop_reason")) == "stop_file", res.payload
