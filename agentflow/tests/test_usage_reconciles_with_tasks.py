# -*- coding: utf-8 -*-
"""判据 a / b / d(a)：`Σ tasks.usd` 与 `Σ usage_ledger.usd` 逐分相等，差值只允许被点名。

## 这条判据钉的是哪一处缺陷

`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md` ① / §A-5 的现场读数：

- `tasks` 389 行里只有 9 行有 `tokens/usd`（合计 $0.5427），而 `usage_ledger` 416 行
  合计 $0.8573；
- V 的 61 笔账散在 35 个 `task_id` 上，可 `tasks` 里 V 只有 `t-000054` 一行有 token
  （1.68M 全塞它一家）；
- 差 $0.3146 = 17 条 running（$0.2825）+ 18 条 `task_id=None`（$0.0322）。

两个根因，各钉一条：

| 根因 | file:line（修复前） | 症状 | 这里的判据 |
|---|---|---|---|
| 幂等键按"这条缝的第 i 次调用"造（`f"{sid}:{role}"` + 缝自己的计数器），而缝是每次召唤现造的 ⇒ 第一次召唤把键全占满，后面每一次召唤的同号调用被判 `duplicate`、静默不记 | `llmseam.py` 的 `_charge_ledger`（`key = MC.idempotency_key(f"{self.sid}:{self.role}", idx)`） | 钱只落在"角色第一次召唤"那几行上 | `test_two_summons_of_the_same_role_each_carry_their_own_call` + 它的反真空 |
| 回写只发生在召唤收尾（`conductor._charge_and_settle` ⇒ `_set_usage`）⇒ 没走到收尾的行永远是 0 | `tokenmeter.TokenMeter.charge/charge_once`（改前不碰 `tasks`） | 17 条 running 行 `usd=0`，而账本上它们有 $0.2825 | `test_a_running_task_carries_its_spend_before_it_settles` |

## 三态纪律落在哪

`task_id=None` 的账不是"忘了填"，而是一个「要说得出为什么」的档：不在任何一次召唤的
上下文里、调用方也没给号。修复后这种行一律在 `note` 里带 `unattributed` 字样，并由
`tokenmeter.reconcile_usage` 单列一栏（判据 b：要么 0 笔，要么全部点名）。
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from agentflow import conductor as CO
from agentflow import schema as S
from agentflow import tokenmeter as TM
from agentflow.llmseam import LlmSeam
from agentflow.store import Store


# --------------------------------------------------------------------- 夹具


class _Gateway:
    """打桩网关：只回固定 usage，不碰网络（判据不花一分真钱）。"""

    def __init__(self, tokens_in: int = 10_000, tokens_out: int = 1_000) -> None:
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 tools: object = None, **_kw: object) -> object:
        self.calls += 1
        return SimpleNamespace(
            ok=True, text='{"ok": 1}', tokens_in=self.tokens_in,
            tokens_out=self.tokens_out, scope=scope, attempts=1,
            error_kind="", error_detail="",
            cache_hit_tokens=None, cache_miss_tokens=None,
        )


def _seam(store: Store, *, role: str = "E") -> LlmSeam:
    """一条接了账本的缝（价表显式给：判据不许依赖供应商价目表）。"""
    return LlmSeam(role=role, session_root=store.root, gateway=_Gateway(),
                   price=(1.0, 2.0), sid="judge-a", meter=TM.TokenMeter(store))


def _world(store: Store, calls: int = 1) -> tuple[CO.Conductor, LlmSeam, list[int]]:
    """最小工作区：一个角色、一条召唤 handler，handler 里真发 N 次模型调用。

    调用不带 `task_id`（与 V 的审阅工具、抽取那一路同形）—— 归口只由召唤上下文
    决定，这正是要钉的那一半。
    """
    seam = _seam(store)
    seen: list[int] = []

    class _E:
        def run_experiment(self, claim: str, claim_key: str, script_path: str,
                           **_kw: object) -> dict:
            seen.append(len(seen) + 1)
            for _ in range(calls):
                seam.ask("这一步要问一次模型")
            return {"outcome": "ok", "detail": "跑完", "tokens": 0, "payload": {}}

    conductor = CO.Conductor(store, registry={"E": ("object", _E())}, backend="local")
    return conductor, seam, seen


def _ledger_usd_of(store: Store, task_id: str) -> float:
    rows = [u for u in store.rows("usage_ledger") if str(u.get("task_id") or "") == task_id]
    return round(sum(float(u.get("usd") or 0.0) for u in rows), 6)


def _task_row(store: Store, task_id: str) -> dict:
    for row in store.rows("tasks"):
        if str(row.get("task_id")) == task_id:
            return dict(row)
    raise AssertionError(f"tasks 里没有 {task_id}：{store.rows('tasks')}")


# ===================================================================== a：相等


def test_two_summons_of_the_same_role_each_carry_their_own_call(store: Store):
    """判据 a 的正控：同一角色连着两次召唤 ⇒ 两笔账各落自己那一行，两处逐分相等。

    ## 改前红在哪（这条判据的证明力）

    改前的幂等键是 `(sid:role, 这条缝的第 i 次调用)`，而 `_seam` 每召唤现造一次 ⇒
    第二次召唤的 `call_index=0` 与第一次撞键，被 `charge_once` 判成 `duplicate`、
    静默不记账。于是 `tasks` 上第二行 `usd=0`，账本上没有那笔钱 —— 现场就是
    "V 的 61 笔账只有 27 笔真的落账，其余 34 笔撞键被吞"。
    """
    conductor, _seam_obj, seen = _world(store)
    first = conductor.summon("E", "run_experiment",
                             {"claim": "a", "claim_key": "ka", "script_path": "s.py"},
                             input_key="first")
    second = conductor.summon("E", "run_experiment",
                              {"claim": "b", "claim_key": "kb", "script_path": "s.py"},
                              input_key="second")
    assert seen == [1, 2]
    assert first.task_id and second.task_id and first.task_id != second.task_id

    model_rows = [u for u in store.rows("usage_ledger") if str(u.get("scope")) == "reason"]
    by_task: dict[str, int] = {}
    for row in model_rows:
        by_task[str(row.get("task_id"))] = by_task.get(str(row.get("task_id")), 0) + 1
    assert by_task == {first.task_id: 1, second.task_id: 1}, (
        "每一次 `llm_call` 的账必须落在「当时那一次召唤」的号上（不是角色第一行）："
        f"{by_task}；账本：{[(u['task_id'], u['scope']) for u in store.rows('usage_ledger')]}")

    for task_id in (first.task_id, second.task_id):
        row = _task_row(store, task_id)
        assert int(row["tokens"]) > 0 and float(row["usd"]) > 0, (
            f"{task_id} 的花销两格必须非零（它真的调过模型）：{row}")
        assert float(row["usd"]) == _ledger_usd_of(store, task_id), (
            f"{task_id}：tasks.usd 与账本上该号的汇总必须逐分相等")

    reading = TM.reconcile_usage(store)
    assert reading["equal"] is True, reading
    assert reading["diff_usd"] == 0.0, reading
    assert reading["named_residual"] == [] and reading["unattributed"]["count"] == 0, reading
    assert reading["tasks_usd"] == reading["ledger_usd"] > 0, reading


def test_negative_control_shared_call_index_reopens_the_role_first_row(store: Store,
                                                                      monkeypatch):
    """判据 a 的反真空：把"按召唤计号"摘掉（退回一条缝一个计数器）⇒ 上面那条必红。

    注入的是「旧口径本身」：`_next_call_index` 恒返回 0，且 `idempotency_key` 不再看
    命名空间（两个召唤都算出一个键）—— 这正是改前"第一次召唤把键全占满"的行为。
    它必须让第二笔账被判 `duplicate`：第二行 `tasks.usd=0`、
    `reconcile_usage()["equal"]` 为假。若这一条不红，上面那条正控就只是
    "两个数碰巧相等"，而不是"按召唤归口的构造"。
    """
    from agentflow import llmseam as LS
    from agentflow import modelcost as MC

    conductor, _seam_obj, seen = _world(store)
    monkeypatch.setattr(LS, "_next_call_index", lambda *a, **k: 0, raising=True)
    monkeypatch.setattr(MC, "idempotency_key", lambda *a, **k: "idem-same-for-every-summon",
                        raising=True)

    first = conductor.summon("E", "run_experiment",
                             {"claim": "a", "claim_key": "ka", "script_path": "s.py"},
                             input_key="neg-1")
    second = conductor.summon("E", "run_experiment",
                              {"claim": "b", "claim_key": "kb", "script_path": "s.py"},
                              input_key="neg-2")
    assert seen == [1, 2], "两次召唤都真的调了模型 —— 这一点在注入下不许变"
    # 旧口径的读数：两次真调用只落下一笔 `reason` 账（第二笔被判 duplicate、静默吞掉），
    # 于是第二次召唤那一行 `usd=0`。这正是"钱落在角色第一行"的形态：
    # 账本少记了一笔、而 `tasks` 上那一行也看不见它花过钱。
    reason_rows = [u for u in store.rows("usage_ledger") if str(u.get("scope")) == "reason"]
    assert len(reason_rows) == 1, (
        f"旧口径下第二次召唤的账应当撞键被吞（只该剩一笔真账）：{reason_rows}")
    assert str(reason_rows[0].get("task_id")) == first.task_id, reason_rows
    assert _ledger_usd_of(store, second.task_id) == 0.0, (
        "旧口径下第二次召唤那一行没有任何花销读数")
    assert float(_task_row(store, second.task_id)["usd"]) == 0.0, (
        "反真空不成立：摘掉按召唤计号之后，第二次召唤那一行仍然有花销 ⇒ "
        "正控测的不是这一格")
    assert float(_task_row(store, first.task_id)["usd"]) == _ledger_usd_of(store, first.task_id), (
        "那一笔真账仍然落在第一次召唤的行上（这就是'角色第一行'的字面形态）")


# ===================================================================== a：running


def test_a_running_task_carries_its_spend_before_it_settles(store: Store):
    """判据 a 的第二半：「还在跑、永远不会结算」的行也必须带着自己的花销。

    现场：17 条 `running` 行在 `tasks` 上 `usd=0`，而账本上它们有 $0.2825 ——
    因为回写只发生在召唤收尾。这里造一条 `running` 行，在召唤上下文里发两次调用，
    全程不写终态，然后要求 `tasks.usd` 已经等于账本汇总。
    """
    seam = _seam(store)
    with store.tx("tasks", actor="judge", note="running 行") as tx:
        tx.upsert("tasks", S.Task(
            task_id="t-000001", role="E", action="run_experiment", called_by="judge",
            parent_task_id=None, depth=1, input_key="running", status="running",
            outcome=None, refusal_reason=None, instance="", detail="还没跑完",
            error=None, started_at=S.now_iso(), ended_at=None, tokens=0, usd=0.0,
            artifacts=[], inputs=[]).to_dict(), note="running 行")

    with CO.calling_as("t-000001", role="E"):
        seam.ask("第一问")
        seam.ask("第二问")

    row = _task_row(store, "t-000001")
    assert row["status"] == "running" and row["ended_at"] is None, row
    assert int(row["tokens"]) > 0, f"running 行也必须带着已花 token：{row}"
    assert float(row["usd"]) == _ledger_usd_of(store, "t-000001") > 0, (
        f"running 行的 usd 必须等于账本上该号的汇总：{row}")
    reading = TM.reconcile_usage(store)
    assert reading["equal"] is True, reading
    assert reading["named_residual"] == [], reading


# ===================================================================== b：点名


def test_a_call_outside_any_summon_is_named_unattributed(store: Store):
    """判据 b：`task_id=None` 的账要么 0 笔，要么「全部点名」为 `unattributed`。

    不在任何一次召唤里（`current_task_id()` 为空）、调用方也没给号 ⇒ 这一笔没有
    可回写的行。它不是"忘了填"：`note` 里必须写明 `unattributed` 与为什么，
    `reconcile_usage()` 也必须把它单列一栏 —— 否则"差 $0.03 差在哪"永远答不出来。
    """
    seam = _seam(store)
    seam.ask("没有台账号的一问")

    rows = [u for u in store.rows("usage_ledger") if u.get("task_id") is None]
    assert len(rows) == 1, store.rows("usage_ledger")
    note = str(rows[0].get("note") or "")
    assert "unattributed" in note, f"没有台账号的账必须自行点名：{note!r}"
    assert "任务上下文" in note or "召唤" in note, note

    reading = TM.reconcile_usage(store)
    assert reading["unattributed"]["count"] == 1, reading
    assert reading["unattributed"]["usage_ids"] == [rows[0]["usage_id"]], reading
    assert reading["equal"] is False, (
        "没有台账号的那一笔进不了任何一行 tasks ⇒ 两处总额不可能相等；这里要求它被点名，"
        f"而不是被悄悄算平：{reading}")


def test_a_task_id_with_no_task_row_is_named_dangling_not_silently_dropped(store: Store):
    """判据 b 的边界：挂着一个不在 `tasks` 里的号 ⇒ 如实点名 `dangling`（不抛、不吞）。

    钱已经花了：回写失败不许把账吞掉（那是比"对不上"更坏的方向）。这一格由
    `verify.dangling_usage_task` 报 error；`reconcile_usage` 只负责让它可被点名。
    """
    meter = TM.TokenMeter(store)
    meter.charge(TM.Charge(role="E", scope="reason", tokens_in=10, tokens_out=1, usd=0.5,
                           task_id="t-9999", note="挂不上任何一行"))
    reading = TM.reconcile_usage(store)
    assert reading["dangling"] == [{"task_id": "t-9999", "ledger_usd": 0.5}], reading
    assert reading["equal"] is False and reading["diff_usd"] == 0.5, reading
    assert store.rows("usage_ledger"), "回写失败不许把账吞掉"


# ============================================================== 反真空：回写那一步


def test_negative_control_without_the_writeback_the_running_row_stays_zero(store: Store,
                                                                          monkeypatch):
    """判据 a 的反真空②：把"记账即回写"摘掉 ⇒ running 行退回 `usd=0`（上面那条必红）。

    注入的是 `_sync_task_usage` 的 no-op（改前它根本不存在）。这一条证明
    `test_a_running_task_carries_its_spend_before_it_settles` 的绿来自回写那一步，
    不是来自"账本本来就会写"。
    """
    monkeypatch.setattr(TM.TokenMeter, "_sync_task_usage",
                        lambda self, tx, task_id: {"written": False, "reason": "injected"},
                        raising=True)
    seam = _seam(store)
    with store.tx("tasks", actor="judge", note="running 行") as tx:
        tx.upsert("tasks", S.Task(
            task_id="t-000001", role="E", action="run_experiment", called_by="judge",
            parent_task_id=None, depth=1, input_key="running", status="running",
            outcome=None, refusal_reason=None, instance="", detail="还没跑完",
            error=None, started_at=S.now_iso(), ended_at=None, tokens=0, usd=0.0,
            artifacts=[], inputs=[]).to_dict(), note="running 行")
    with CO.calling_as("t-000001", role="E"):
        seam.ask("这一问的钱回写不了")

    row = _task_row(store, "t-000001")
    assert float(row["usd"]) == 0.0 and _ledger_usd_of(store, "t-000001") > 0, row
    assert TM.reconcile_usage(store)["equal"] is False, (
        "反真空不成立：摘掉回写之后两处仍然相等 ⇒ 正控测的不是回写那一步")
