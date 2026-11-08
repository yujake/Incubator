# -*- coding: utf-8 -*-
"""块乙：D 只给研究方向，不点命题号（业主 2026-11-08）。

业主原话（逐字）：

> 「那条猜想只是参考意见，D不能直接把自己的猜想登记到命题台账，也不能命令E或F必须把它做出来，
>   这只是研究方向参考」

## 判据（机械可核，不是词表判断）

- 红：从 D 的派活记录（`sessions/*.jsonl` 的 `agent_step`：`role="D"`、
  `shape="summon"` 的 `payload`）里取文本，出现 D 自己登记的 `conjecture_id`
  （`conj:NNNNNN` 或裸 6 位号，且那个号在 `conjectures` 台账里）⇒ `violations` 非空，
  逐条点名「哪一次派活 / 哪条计划、点了哪条猜想」；
- 绿：D 只写研究方向（不提号）⇒ `violations` 空；
- 反真空：把号匹配那一格摘掉（`token_match` 恒返回 `[]`）⇒ 红的那条必须变绿。

`attack_plans` 只在"它的 `problem` 文本能在某一段 D 派活文本里找到"（或 `problem_key`
就是那段派活 `params` 里的值）时才算"这句派活落成的计划"—— F 自主写的计划（问题文本没有
出现在任何 D 派活里）记进 `self_authored_plans`，不算违规：那是 F 自己的选择。

本文件同时钉住题面：`specs/d.py` 的 policy 与 `agent_skills._d_skills()` 不再教 D 拿
`conjecture_id` 当 `problem_key`，并写明猜想只是参考意见。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import dispatchpolicy as DP  # noqa: E402
from agentflow import sessions as SS  # noqa: E402
from agentflow import specs  # noqa: E402
from agentflow.store import Store  # noqa: E402

CONJ = "000007"
OTHER = "000008"


def _workspace(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("conjectures", actor="agent-D") as tx:
        for cid in (CONJ, OTHER):
            tx.upsert("conjectures", {
                "conjecture_id": cid,
                "statement": f"猜想 {cid}：某个计数随 n 增长。",
                "form": "universal", "status": "proposed",
                "testable": {"parameters": {}, "criterion": "枚举到 n=6", "falsified_by": "反例"},
                "origin": "report:r-1", "created_by": "agent-D",
            })
    return st


def _dispatch(st: Store, *, task: str, role: str = "F", index: int = 0,
              params: dict | None = None, why: str = "派 F 攻坚") -> None:
    SS.append(st.root, {
        "kind": "agent_step", "role": "D", "index": index, "shape": "summon",
        "payload": {"role": role, "action": "", "task": task,
                    "params": dict(params or {}), "why": why},
    }, sid="t-test")


def _plan(st: Store, *, problem: str, key: str = "PK-1") -> str:
    with st.tx("attack_plans", actor="agent-F") as tx:
        pid = tx.alloc_id("plan")
        tx.upsert("attack_plans", {
            "plan_id": pid, "problem": problem, "problem_key": key,
            "status": "open", "rounds": 0,
            "budget": {"max_rounds": 6, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 2},
            "subgoals": [], "history": [], "depth": 0, "created_by": "agent-F",
        })
    return pid


# ============================================================ 红：D 派活文本点号
@pytest.mark.parametrize("task, token", [
    (f"证明 conj:{CONJ}（零点检测器 / 两枚饱和见证）", f"conj:{CONJ}"),
    (f"攻坚猜想 {CONJ}（D 登记）：把它的否定也写出来", CONJ),
])
def test_a_d_naming_a_conjecture_id_in_its_dispatch_is_red(
        tmp_path: pathlib.Path, task: str, token: str) -> None:
    """红：派活文本出现 D 自己的猜想号 ⇒ 判据红，逐条点名是哪一次派活、哪条猜想。"""
    st = _workspace(tmp_path)
    _dispatch(st, task=task)
    got = DP.dispatch_text_problems(st.root)
    assert got.get("checked") is True, got
    assert got.get("dispatches") == 1, got
    assert len(got.get("violations") or []) == 1, got
    one = got["violations"][0]
    assert one["kind"] == "dispatch", one
    assert one["conjecture_id"] == CONJ, one
    assert one["token"] == token, one
    assert one["role"] == "F" and one["index"] == 0, one
    assert "conj:" in str(one["task"]) or CONJ in str(one["task"]), one


def test_b_a_plan_that_came_from_the_dispatch_is_named_with_its_plan_id(
        tmp_path: pathlib.Path) -> None:
    """红（计划面）：计划的问题文本就是那句派活 ⇒ 违规里同时点名 plan_id。"""
    st = _workspace(tmp_path)
    problem = f"证明 conjecture {CONJ}：D 让我攻这一条"
    _dispatch(st, task=problem, params={"subgoals": ["先算小情形"]})
    pid = _plan(st, problem=problem)
    got = DP.dispatch_text_problems(st.root)
    kinds = {v["kind"] for v in (got.get("violations") or [])}
    assert "plan" in kinds, got
    plan_rows = [v for v in got["violations"] if v["kind"] == "plan"]
    assert [v["plan_id"] for v in plan_rows] == [pid], plan_rows
    assert plan_rows[0]["conjecture_id"] == CONJ, plan_rows
    assert [x["plan_id"] for x in got.get("named_plans") or []] == [pid], got


# ============================================================ 绿：只写研究方向
def test_c_direction_only_dispatch_is_green_even_if_f_plans_a_d_conjecture(
        tmp_path: pathlib.Path) -> None:
    """绿：D 只写方向（不提号）；F 自主去攻 D 的一条猜想 ⇒ 不算 D 违规。"""
    st = _workspace(tmp_path)
    _dispatch(st, task="沿「计数随 n 的增长阶」这个方向找一条可判定的命题，先算小情形")
    _plan(st, problem=f"证明 conj:{CONJ}（F 自己选的这条猜想）", key="F-self")
    got = DP.dispatch_text_problems(st.root)
    assert got.get("checked") is True, got
    assert got.get("violations") == [], got
    assert int(got.get("self_authored_plans") or 0) == 1, got
    assert "没有点名" in str(got.get("reason") or ""), got


def test_d_a_six_digit_number_that_is_not_a_conjecture_id_is_green(
        tmp_path: pathlib.Path) -> None:
    """绿：派活文本里的 6 位数字不是台账里的猜想号 ⇒ 不判（判据认的是 D 的猜想号）。"""
    st = _workspace(tmp_path)
    _dispatch(st, task="按实验 exp:123456 的读数继续（那不是猜想号）")
    got = DP.dispatch_text_problems(st.root)
    assert got.get("violations") == [], got


# ============================================================ 反真空
def test_e_removing_the_id_matcher_turns_the_red_case_green(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把号匹配打桩成恒空 ⇒ 红那一笔必须变绿（证明红真的来自这条判据）。"""
    st = _workspace(tmp_path)
    _dispatch(st, task=f"证明 conj:{CONJ}：D 的命令")
    red = DP.dispatch_text_problems(st.root)
    assert red.get("violations"), red
    monkeypatch.setattr(DP, "_id_hits", lambda text, ids: [])
    green = DP.dispatch_text_problems(st.root)
    assert green.get("violations") == [], green


# ============================================================ 题面
def test_f_the_policy_and_skills_no_longer_command_the_conjecture() -> None:
    """题面：D 的 policy / skills 写明「参考意见、不点名」，且不再教 `problem_key=猜想号`。"""
    d = specs.builtin_specs()["D"]
    policy = "\n".join(d.brief.policy)
    assert "参考意见" in policy, policy
    assert "不要点名任何 `conjecture_id`" in policy, policy
    assert "dispatchpolicy.dispatch_text_problems" in policy, policy
    assert "`problem_key` 就用猜想的 `conjecture_id`" not in policy, policy
    from agentflow import agent_skills as SK

    text = "\n".join(s.body for s in SK.skills_for("D"))
    assert "problem_key` 用 conjecture_id" not in text, text
    assert "参考意见" in text, text
    assert "不点名 conjecture_id" in text or "不要点名任何 `conjecture_id`" in text, text


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
