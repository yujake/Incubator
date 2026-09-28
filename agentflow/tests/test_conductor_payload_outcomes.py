"""终态映射的判据：两套词表不许折叠（依据 `draft/30` §T0-11）。

实测缺陷（2026-09-29 验收 P1）：`F.step` 返回的 `outcome` 是它的子目标判定词表
（`progress` / `no_change`），而 `Conductor._end_from_payload` 原样把它当任务级结果
透传 ⇒ `schema.Task.validate` 抛 `ValueError` ⇒ 整步落 `failed`，
而活其实已经干完（事务已提交）：20/20 条 `F.step` 台账 `failed`，
而 14 条检索请求已提交、11 条 ok 收尾。

装置说明：派活只接受已声明的角色与动作（`capabilities` 是唯一权威），
所以这里用真实声明的 `E.list_experiments` + 一个返回预设字典的替身，
而不是自造 `X.act`（第一版就是这样写错的）。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from agentflow import schema as S
from agentflow.conductor import Conductor
from agentflow.store import Store


class _FakeE:
    """E 的替身：`list_experiments` 返回预设字典（真实声明的动作）。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def list_experiments(self):
        """无必填参数的 E 动作。"""
        self.calls += 1
        return self.payload


def _wired(tmp_path: Path, payload) -> tuple[Store, _FakeE, Conductor]:
    """工作区 + 替身 + 主控。"""
    st = Store(tmp_path)
    st.init()
    fake = _FakeE(payload)
    c = Conductor(st, registry={"E": ("object", fake)})
    return st, fake, c


def _summon(c: Conductor):
    """派一次 E.list_experiments。"""
    return c.summon(role="E", action="list_experiments", params={}, input_key="judge:outcome")


def _row(st: Store) -> dict:
    """取唯一那条任务行。"""
    rows = st.rows("tasks")
    assert len(rows) == 1, rows
    return rows[0]


def test_foreign_outcome_does_not_crash_the_step_and_stays_visible(tmp_path: Path):
    """正控（回归）：替身返回 `outcome="progress"` ⇒ 任务记 `done/ok`，判定留在 detail 里。"""
    st, fake, c = _wired(tmp_path, {"outcome": "progress", "detail": "子目标推进了一格"})
    res = _summon(c)
    assert fake.calls == 1, "替身应当真的被调到（否则这条判据什么都没测）"
    row = _row(st)
    assert res.status == "done" and res.outcome == "ok", (res.status, res.outcome)
    assert row["status"] == "done" and row["outcome"] == "ok", row
    assert "handler_outcome=progress" in str(row["detail"]), row["detail"]
    assert "子目标推进了一格" in str(row["detail"])


def test_task_outcome_vocabulary_is_not_widened(tmp_path: Path):
    """负控（反真空）：写入的行仍必须过 `Task.validate` —— 词表没被放宽。"""
    st, _fake, c = _wired(tmp_path, {"outcome": "no_change"})
    _summon(c)
    row = _row(st)
    assert row["outcome"] in S.TASK_OUTCOMES, row["outcome"]
    names = {f.name for f in dataclasses.fields(S.Task)}
    S.Task(**{k: v for k, v in row.items() if k in names}).validate()


def test_a_real_task_outcome_is_taken_verbatim(tmp_path: Path):
    """正控（另一支）：替身返回的是任务级词表 ⇒ 原样取用（不做无谓改写）。"""
    st, _fake, c = _wired(tmp_path, {"outcome": "no_result", "detail": "没有产出"})
    _summon(c)
    row = _row(st)
    assert row["outcome"] == "no_result", row
    assert "handler_outcome" not in str(row["detail"]), row["detail"]


def test_failed_status_still_wins(tmp_path: Path):
    """负控：`status="failed"` 的既有 override 仍在（外来判定不许把失败洗成 ok）。"""
    st, _fake, c = _wired(tmp_path, {"status": "failed", "outcome": "progress",
                                     "error": "boom"})
    _summon(c)
    row = _row(st)
    assert row["status"] == "failed" and row["outcome"] == "failed", row
    assert str(row["error"]) == "boom"


def test_refused_outcome_is_not_rewritten(tmp_path: Path):
    """正控：`refused` 是任务级词表里的值（策略拒绝 ≠ 崩溃）⇒ 原样保留。

    注意它必须带受控的 `refusal_reason`（`schema.Task.validate` 逐字要求：
    "拒绝的理由必须是受控词表，不许自由文本"）—— 所以这个替身要像真的拒绝那样写全，
    否则会被 schema 挡住、落成 `failed`，那就不是这条判据要测的东西了。
    """
    st, _fake, c = _wired(tmp_path, {"outcome": "refused", "refusal_reason": "budget_exceeded",
                                     "detail": "闸门拒绝"})
    _summon(c)
    row = _row(st)
    assert row["outcome"] == "refused", row
    assert row["refusal_reason"] == "budget_exceeded", row
    assert "handler_outcome" not in str(row["detail"])
