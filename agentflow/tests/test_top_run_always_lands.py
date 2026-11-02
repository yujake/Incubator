# -*- coding: utf-8 -*-
"""2026-11-02（83）：顶趟那一行必须落终态，而且三档要分得开。

## 这一份钉的是什么

83 的真机读数（只读复算）：M 的顶趟行 `t-000001` 从 02:01:31 一直到 06:44:22 都是
`status=running`；04:50:44 之后 M 已经 113 分钟没有新步（`out/steps/t-000001.json`
停在 04:50:45），而台账上它「还在跑」。只有人工写 `.agentflow-stop` 才收场。

根因不是「没有收行代码」——`run_role` 里有，但它在 `loop.run()` 返回之后
（`agent_loop.py` 的收尾那几行），而且是顺序语句：`run()` 一抛异常、或者一阻塞，
那一行就永远 `running`。同一条路上还有一处：`--resume` 被拒的五个提前返回
（`no_checkpoint` / `checkpoint_mismatch` / `already_finished` / `still_waiting` /
`resume_no_transcript`）在开行之后、收行之前 return —— 它们同样漏行。

| 条 | 判据 | 改前红在哪 |
|---|---|---|
| a | 循环里抛异常 ⇒ 顶趟行落 `done`（不是 running）、`detail` 含「收工没做成」、`runs/agent-<角色>-<会话>.json` 有 `end_ts` | 改前异常直接穿过 `run_role`，那一行永远 running |
| b | 三档映射：`final→ok` / `USER_STOP_REASONS→cancelled` / 其余 `→no_result + 「收工没做成：…」` | 改前后两档折在同一个 `no_result` 里（第三次三态折平） |
| c | 正常收工也带 `end_ts`（`LoopRun.to_dict()` 与步检查点两处） | 改前 71 份 `runs/*.json` 里 0 份有 `end_ts` |
| d | `--resume` 被拒（开出顶趟行之后 return）也不许漏行 | 改前那五条提前返回都不收行 |
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

import pytest

from agentflow import agent_loop as AL
from agentflow.agent_loop import run_role
from agentflow.conductor import Conductor
from agentflow.llmseam import LlmSeam
from agentflow.policy import Policy
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "lands"
ROLE = "M"
TASK = "2026-11-02 判据夹具：顶趟那一行必须落终态"

FINAL = json.dumps({"final": "都做完了，收工", "evidence": []}, ensure_ascii=False)


class _Gate:
    """照剧本回答的替身模型（不联网、不花钱）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        text = self.replies[min(index, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


def _env(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store, Conductor]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return ws, st, Conductor(st, policy=Policy())


def _registry(st: Store, cond: Conductor, ws: pathlib.Path) -> Any:
    return build_registry(store=st, conductor=cond, workspace_root=ws).registry


def _run(ws: pathlib.Path, st: Store, cond: Conductor, replies: list[str], *,
         resume: bool = False) -> Any:
    return run_role(ROLE, TASK, store=st, registry=_registry(st, cond, ws),
                    conductor=cond, session_root=ws, sid=SID, from_env=False,
                    seam=LlmSeam(role=ROLE, session_root=ws, gateway=_Gate(replies),
                                 price=(0.0, 0.0), sid=SID),
                    max_steps=6, resume=resume)


def _top_rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("action") or "") == "run"
            and str(r.get("called_by") or "") == "user"]


def _checkpoint(ws: pathlib.Path) -> dict:
    path = AL.run_checkpoint_path(ws, ROLE, SID)
    assert path.is_file(), f"步检查点不在盘上：{path}"
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================ a：抛异常也落终态
def test_a_crashing_loop_still_lands_the_top_row(tmp_path: pathlib.Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 a：循环里抛异常 ⇒ 顶趟行落 done（含「收工没做成」），且 runs 有 end_ts。

    改前红：异常穿过 `run_role`（收行那几行在它后面），那一行永远 running ——
    83 上就是这一档（只不过那一次是阻塞而不是抛异常）。
    """

    def boom(self: Any, *a: Any, **kw: Any) -> Any:
        raise RuntimeError("判据：循环里炸了")

    monkeypatch.setattr(AL.AgentLoop, "run", boom)
    ws, st, cond = _env(tmp_path)
    with pytest.raises(RuntimeError, match="循环里炸了"):
        _run(ws, st, cond, [FINAL])

    rows = _top_rows(st)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["status"] == "done", ("异常之后那一行仍是 running", row)
    assert row["outcome"] == "no_result", row
    assert row.get("ended_at"), row
    assert "收工没做成" in str(row.get("detail") or ""), row
    # runs/*.json 的 end_ts：崩溃那一趟也要有一份"收在这一刻"的记录（不是没有文件）。
    ck = _checkpoint(ws)
    assert str(ck.get("end_ts") or ""), ("崩溃那一趟的步检查点没有 end_ts", ck)
    assert str(ck.get("stop_reason") or "") == "crashed", ck


# ============================================================ b：三档映射
def test_the_three_ways_to_end_are_three_different_readings(tmp_path: pathlib.Path) -> None:
    """判据 b：收工成功 / 收工被叫停 / 收工没做成 —— 台账上必须是三行不同的读数。

    改前红：后两档都落 `done/no_result`（`finish_top_level_run` 只有
    `stop_reason == "final"` 一个判据），于是"被用户叫停"与"自己没做成"在台账上
    长得一模一样 —— 这是第三次三态折平。
    """
    ws, st, cond = _env(tmp_path)
    # 三个角色各开一趟：`open_top_level_run` 会顺手把同角色遗留的 running 顶趟
    # 扫成 failed（`_sweep_stale_top_running`），同一个角色连开三行会把前一行扫掉 ——
    # 那是另一条判据的对象（僵尸清扫），这里要的是三档读数本身。
    cases = {
        "final": ("done", "ok", "顶趟收工：final"),
        "stop_file": ("done", "cancelled", "顶趟收工被叫停：stop_file"),
        "no_progress_limit": ("done", "no_result", "收工没做成：no_progress_limit"),
    }
    roles = {"final": "M", "stop_file": "D", "no_progress_limit": "G"}
    ids = {reason: cond.open_top_level_run(roles[reason], TASK) for reason in cases}
    res = {reason: cond.finish_top_level_run(tid, stop_reason=reason)
           for reason, tid in ids.items()}
    rows = {str(r["task_id"]): r for r in _top_rows(st)}
    for reason, (status, outcome, head) in cases.items():
        row = rows[ids[reason]]
        assert (row["status"], row["outcome"]) == (status, outcome), (reason, row)
        assert str(row.get("detail") or "").startswith(head), (reason, row.get("detail"))
        assert (res[reason].status, res[reason].outcome) == (status, outcome), res[reason]
    # 三行必须互不相同（"折平"的机器形态就是这三行里有任意两行同读数）。
    seen = {(rows[ids[r]]["status"], rows[ids[r]]["outcome"]) for r in cases}
    assert len(seen) == 3, seen


# ============================================================ c：正常收工也带 end_ts
def test_a_normal_run_stamps_end_ts_in_both_places(tmp_path: pathlib.Path) -> None:
    """判据 c：正常收工 ⇒ `LoopRun.to_dict()["end_ts"]` 与步检查点的 `end_ts` 都有值。

    改前红（读数对照）：83 的 `runs/` 下 71 份 json 里 0 份有 `end_ts` ——
    `LoopRun.to_dict()` 没有这一格，步检查点也没有（只有写入时刻的 `at`）。
    """
    ws, st, cond = _env(tmp_path)
    run = _run(ws, st, cond, [FINAL])

    assert run.stop_reason == "final", run.to_dict()
    dumped = run.to_dict()
    assert str(dumped.get("end_ts") or ""), ("to_dict 里没有 end_ts", sorted(dumped))
    assert dumped["end_ts"] >= run.started_at, (dumped["end_ts"], run.started_at)
    ck = _checkpoint(ws)
    assert str(ck.get("end_ts") or ""), ("步检查点里没有 end_ts", ck)
    assert ck.get("stop_reason") == "final", ck
    row = _top_rows(st)[0]
    assert (row["status"], row["outcome"]) == ("done", "ok"), row


# ============================================================ d：提前返回不漏行
def test_a_refused_resume_still_lands_the_row(tmp_path: pathlib.Path) -> None:
    """判据 d：`--resume` 被拒（开行之后、跑之前 return）也不许把顶趟行留在 running。

    改前红：`no_checkpoint` 那一条在 `open_top_level_run` 之后直接 `return LoopRun(...)`,
    收行那几行在它后面 ⇒ 台账上多一条永远 running 的顶趟行。
    """
    ws, st, cond = _env(tmp_path)
    run = _run(ws, st, cond, [FINAL], resume=True)
    assert run.stop_reason == "no_checkpoint", run.to_dict()

    rows = _top_rows(st)
    assert len(rows) == 1, rows
    assert rows[0]["status"] == "done", ("被拒的续跑也把行留在 running", rows[0])
    assert rows[0]["outcome"] == "no_result", rows[0]
    assert "收工没做成" in str(rows[0].get("detail") or ""), rows[0]
