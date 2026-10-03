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


# ------------------------------------------- handler 自己说"没做成"（`draft/37` §88）

def test_a_handler_that_says_ok_false_is_never_recorded_as_ok(tmp_path: Path):
    """负控（T1 第 2 趟的根因）：`{"ok": False, ...}` 不许被记成 `outcome=ok`。

    真机读数：`B.register_statement` 有 8 次返回 `ok=False`（带 `kind` 与 `error`），
    而 `tasks` 台账把它们全记成 `ok`（detail 写着"按有产出处理"）—— 主控据此以为
    命题登记好了，而 `statements` 是 0 行，整条链在这一步静默停住。
    没有受控 `refusal_reason` 时它落 `failed`（"执行了、没成功"），
    但无论哪一档，都不许是 `ok` —— 这是这条判据的底线。
    """
    st, _fake, c = _wired(tmp_path, {"ok": False, "kind": "missing_proof_text",
                                     "error": "自产命题没有证明"})
    res = _summon(c)
    row = _row(st)
    assert res.outcome != "ok", (res.status, res.outcome)
    assert row["outcome"] == "failed" and row["status"] == "failed", row
    assert "handler_ok=False" in str(row["detail"]), row["detail"]
    assert "missing_proof_text" in str(row["detail"]), "细一档的 kind 必须留在台账上"
    assert "自产命题没有证明" in str(row["error"]), row["error"]
    S.Task(**{k: v for k, v in row.items()
              if k in {f.name for f in dataclasses.fields(S.Task)}}).validate()


def test_a_handler_refusal_lands_as_refused_with_a_controlled_reason(tmp_path: Path):
    """正控：handler 声明了受控 `refusal_reason` ⇒ `refused`（不是 `failed`）。

    这一档就是 `agentflow.refusals.refuse` 造出来的形状。为什么要它：
    "我参数给错了，改参数还能重来"与"代码崩了"必须分得开，否则主控只会重试
    或放弃，而不是去改参数。
    """
    from agentflow.refusals import PRECONDITION_REASON, refuse

    st, _fake, c = _wired(tmp_path, refuse("bad_mode", "mode 不认识"))
    res = _summon(c)
    row = _row(st)
    assert res.outcome == "refused" and row["outcome"] == "refused", row
    assert row["status"] == "done", "拒绝是一次成功执行（框架正确地说不）"
    assert row["refusal_reason"] == PRECONDITION_REASON, row
    assert "bad_mode" in str(row["detail"]), row["detail"]


def test_a_self_contradictory_payload_is_not_washed_into_ok(tmp_path: Path):
    """负控（自相矛盾）：一边 `ok=False`、一边声明 `outcome=ok` ⇒ 按没做成分档。

    这一格存在是因为"声明优先"的阶梯可以被一句话绕过：只要在载荷里写上
    `outcome="ok"`，`ok=False` 就被无视了。所以阶梯要显式挡住这一种。
    """
    st, _fake, c = _wired(tmp_path, {"ok": False, "outcome": "ok",
                                     "kind": "nothing_written", "error": "什么都没写成"})
    _summon(c)
    row = _row(st)
    assert row["outcome"] != "ok", row
    assert "自相矛盾" in str(row["detail"]), row["detail"]


def test_a_bare_ok_false_without_error_still_writes_a_valid_row(tmp_path: Path):
    """负控（反真空）：只有 `{"ok": False}` 时也不许把终端态写坏、更不许记成 ok。

    这一条挡的是"修法自身制造崩溃"：`status=failed` 要求 `error` 非空
    （`Task.validate` 逐字要求），所以失败那一档必须合成理由 —— 否则
    handler 少写一个字段就会让整步在写台账时抛异常。
    """
    st, _fake, c = _wired(tmp_path, {"ok": False})
    _summon(c)
    row = _row(st)
    assert row["outcome"] == "failed" and row["status"] == "failed", row
    assert str(row["error"]).strip(), row
    S.Task(**{k: v for k, v in row.items()
              if k in {f.name for f in dataclasses.fields(S.Task)}}).validate()


def test_ok_false_with_a_foreign_outcome_is_not_folded_into_ok_either(tmp_path: Path):
    """负控（同一条纪律的另一半）：`ok=False` + 角色自己的判定词（`progress`）也不许变 ok。

    为什么这条必须单独有：下面还有一条既有规则叫"外来判定折叠成 `ok`"（角色用
    `progress`/`no_change` 时不许让 `Task.validate` 抛），它是为成功的调用准备的。
    两条规则叠在一起时，`{"ok": False, "outcome": "progress"}` 会被那条老规则洗成
    `ok` —— 一条新的漏洞，形状与 §88 要修的那条一模一样。所以分档必须先接住
    `ok=False`。
    """
    st, _fake, c = _wired(tmp_path, {"ok": False, "outcome": "progress",
                                     "detail": "子目标没推进"})
    _summon(c)
    row = _row(st)
    assert row["outcome"] != "ok", row
    assert "handler_ok=False" in str(row["detail"]), row["detail"]
    assert "progress" in str(row["detail"]), row["detail"]
    S.Task(**{k: v for k, v in row.items()
              if k in {f.name for f in dataclasses.fields(S.Task)}}).validate()
