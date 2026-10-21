# -*- coding: utf-8 -*-
"""优雅停止把剩余任务与委托翻成 `block`（业主 2026-10-13，批 R74）。

业主三句原话（逐字）：

1. 「优雅停止时要向父代理汇报未完成的任务，最终由M整理汇报用户」
2. 「优雅停止就是主控用这个操作或预算耗尽自动触发主控用这个操作」
3. 「接收到停的时候，剩余任务委托状态自动变成block」

判据分四组：词表（`block` 这一档存在、且必须有来路）· 搬运（谁被翻、谁不许被翻）·
两条通路（预算耗尽与主控的操作都接上了）· 回报（它随子结果与事件回给父，M 汇总）。

为什么这一档必须由框架翻而不是"让模型汇报"：预算耗尽那一支根本没有模型回合
（循环在步边界直接 break）—— 想让它汇报只能等下一次模型调用，而那时钱已经没了。
"""
from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow import stopctl as SC
from agentflow.store import Store

TS = "2026-10-13T12:00:00+08:00"


def _task(task_id: str, *, status: str = "pending", parent: str = "", role: str = "B",
          kind: str = "", item_state: str = "", detail: str = "") -> dict:
    row = S.Task(task_id=task_id, role=role, action="run_once", status=status,
                 parent_task_id=(parent or None), kind=kind, item_state=item_state,
                 expects=("work" if kind else ""),
                 detail=detail or ("夹具：早做完了" if status == "done" else
                                   "夹具：人叫停了" if status == "cancelled" else ""),
                 started_at=TS,
                 ended_at=(TS if status in ("done", "cancelled", "failed") else None),
                 outcome=("ok" if status == "done" else
                          "cancelled" if status == "cancelled" else
                          "failed" if status == "failed" else None))
    return row.to_dict()


# ============================================================ 一、词表


def test_the_block_state_exists_and_has_only_one_meaning():
    """`block` 在任务状态词表里 —— 它说的是"停了、没做完"，与 cancelled / failed 都不同。"""
    assert "block" in S.TASK_STATUSES, S.TASK_STATUSES
    assert len(set(S.TASK_STATUSES)) == len(S.TASK_STATUSES), "词表里有重名"


def test_a_blocked_row_must_carry_why_it_stopped():
    """`block` 行必须有 `detail`（为什么停）：三态纪律 —— 不许让"没做完"没有来路。"""
    row = S.Task(task_id="t-0001", role="B", action="run_once", status="block")
    with pytest.raises(ValueError, match="detail"):
        row.validate()


def test_a_blocked_row_may_not_claim_success():
    """`block` 的 `outcome` 只能是 `None` / `no_result` —— 没做完就不是 ok。"""
    row = S.Task(task_id="t-0001", role="B", action="run_once", status="block",
                 detail="优雅停止（budget）", outcome="ok")
    with pytest.raises(ValueError, match="no_result"):
        row.validate()


# ============================================================ 二、搬运


def test_the_helper_flips_the_agents_own_row_and_its_delegations(tmp_path: pathlib.Path):
    """正控：自己那一行 + 它派出去的都翻 `block`，理由与时间由框架写。"""
    st = Store(tmp_path)
    st.init(force=True)
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", _task("t-0001", status="running"))
        tx.upsert("tasks", _task("t-0002", parent="t-0001", status="running",
                                 kind="delegation", item_state="claimed"))
        tx.upsert("tasks", _task("t-0003", parent="t-0009", status="running"))  # 别人的
    got = SC.block_remaining_tasks(st, task_id="t-0001", why="budget")
    assert got["checked"] is True and sorted(got["blocked"]) == ["t-0001", "t-0002"], got
    assert got["blocked_items"] == ["t-0002"], got
    rows = {r["task_id"]: r for r in st.rows("tasks")}
    assert rows["t-0001"]["status"] == "block" and rows["t-0002"]["status"] == "block", rows
    assert "budget" in rows["t-0001"]["detail"], rows["t-0001"]
    assert rows["t-0001"]["ended_at"], "翻 block 要落时间"
    assert rows["t-0002"]["item_state"] == "block", "被停掉的委托不许在板上永远挂着待办"
    assert rows["t-0003"]["status"] == "running", "不属于这一趟的行一个字都不许动"


def test_a_finished_row_is_never_flipped(tmp_path: pathlib.Path):
    """负控：已经收终态的行（done/cancelled/failed）不许被这次停机改写。"""
    st = Store(tmp_path)
    st.init(force=True)
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", _task("t-0001", status="done", detail="做完了"))
        tx.upsert("tasks", _task("t-0002", parent="t-0001", status="cancelled", detail="人叫停"))
    got = SC.block_remaining_tasks(st, task_id="t-0001", why="budget")
    assert got["checked"] is True and got["blocked"] == [], got
    rows = {r["task_id"]: r["status"] for r in st.rows("tasks")}
    assert rows == {"t-0001": "done", "t-0002": "cancelled"}, rows


def test_all_runs_blocks_the_whole_turn(tmp_path: pathlib.Path):
    """主控那条操作要停的是整趟：`all_runs=True` 时整棵树里未终态的行都翻。"""
    st = Store(tmp_path)
    st.init(force=True)
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", _task("t-0001", status="running"))
        tx.upsert("tasks", _task("t-0002", parent="t-0001", status="running"))
        tx.upsert("tasks", _task("t-0003", parent="t-0002", status="pending"))
        tx.upsert("tasks", _task("t-0004", status="done", detail="早做完了"))
    got = SC.block_remaining_tasks(st, why="user_stop", all_runs=True)
    assert sorted(got["blocked"]) == ["t-0001", "t-0002", "t-0003"], got
    rows = {r["task_id"]: r["status"] for r in st.rows("tasks")}
    assert rows["t-0004"] == "done", rows


def test_no_store_is_unknown_not_nothing_left(tmp_path: pathlib.Path):
    """三态：没接线 ⇒ `checked=False` + 理由 —— 不许折成"没有剩余"。"""
    got = SC.block_remaining_tasks(None, task_id="t-0001", why="budget")
    assert got["checked"] is False and got["blocked"] == [], got
    assert "没查成" in got["reason"] or "翻不了" in got["reason"], got


# ============================================================ 三、两条通路接上了没有


def test_the_two_stop_paths_call_the_helper():
    """判据（接线）：预算耗尽那一支与"接收到停"那一支都真的调了 `_block_remaining`。

    为什么按源码读而不是跑一遍循环：这两支分别在"钱花完"与"收到停"那一刻触发，
    跑真循环要造出那两个状态；而这一条要守的是"接线没有掉"——接了没有，
    读调用点就够，跑一遍反而更脆（预算那条要伪造账本）。行为那一半由上面几条判据钉。
    """
    from agentflow import agent_loop as AL

    src = pathlib.Path(inspect.getsourcefile(AL)).read_text(encoding="utf-8")
    assert src.count("self._block_remaining(run, ") >= 2, (
        "两条停机通路（接收到停 / 预算耗尽）里至少各要有一处 `_block_remaining`")
    assert '"blocked_remaining": dict(run.blocked_remaining)' in src, \
        "子结果里没有把剩余项带给父代理"
    assert '"blocked_remaining": dict(run.blocked_remaining),' in src, \
        "`agent_run_end` 事件里没落这一栏（观测面读不到）"


def test_the_conductors_stop_operation_blocks_the_whole_turn():
    """判据（M 的操作）：`conductor.stop` 的返回里有 `blocked_remaining`，且按整趟翻。"""
    from agentflow.tools import conductor_tools as CT

    src = pathlib.Path(inspect.getsourcefile(CT)).read_text(encoding="utf-8")
    assert "block_remaining_tasks(" in src and "all_runs=True" in src, \
        "主控的优雅停止操作没有接上整趟翻 block"
    assert '"blocked_remaining": blocked_remaining' in src, \
        "翻完的结果没有随返回值回去（M 就没法汇总进交付说明）"


def test_the_flip_leaves_no_nonterminal_rows(tmp_path: pathlib.Path):
    """翻完之后"未终态的行"是空的 —— 续跑简报那一栏读的就是这个口径（不是被 block 顶掉）。

    这里刻意不断言简报内部复用哪个函数：判的是台账那一栏本身（`pending`/`running` 的行数），
    那是"还剩什么活"的唯一权威来源。
    """
    st = Store(tmp_path)
    st.init(force=True)
    with st.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", _task("t-0001", status="running"))
        tx.upsert("tasks", _task("t-0002", parent="t-0001", status="pending"))
    before = [r["task_id"] for r in st.rows("tasks")
              if r["status"] in ("pending", "running")]
    assert sorted(before) == ["t-0001", "t-0002"], before
    SC.block_remaining_tasks(st, why="user_stop", all_runs=True)
    after = [r["task_id"] for r in st.rows("tasks")
             if r["status"] in ("pending", "running")]
    assert after == [], after
    blocked = [r for r in st.rows("tasks") if r["status"] == "block"]
    assert len(blocked) == 2 and all("user_stop" in r["detail"] for r in blocked), blocked
