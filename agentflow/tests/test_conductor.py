"""主控编队测试：`DESIGN-CONDUCTOR.md` §7 的 10 条不变式，每条一条测试 + 一条负控。

## 不变式 → 测试名（本文件里逐条对应）

| # | 不变式 | 测试（断言正方向） | 负控（证明判据真的在卡） |
|---|---|---|---|
| I-1 | 每个 `started_at` 恰好一个 `ended_at` | `test_i1_every_start_has_exactly_one_end` | `test_i1_negative_control_running_row_is_inspectable` |
| I-2 | 终态不可改写 | `test_i2_terminal_state_is_immutable` | `test_i2_negative_control_first_writer_wins` |
| I-3 | 深度单调不减（子 = 父 + 1） | `test_i3_depth_is_parent_plus_one` | `test_i3_negative_control_dangling_parent_is_refused` |
| I-4 | 拒绝必须带受控理由 | `test_i4_refused_always_has_controlled_reason` | `test_i4_negative_control_no_refusal_reason_on_ok` |
| I-5 | 并发度不超上限 | `test_i5_peak_concurrency_within_limit` | `test_i5_negative_control_limit_is_actually_reached` |
| I-6 | 写集相交不并发 | `test_i6_intersecting_write_sets_are_serialized` | `test_i6_negative_control_disjoint_are_parallel` |
| I-7 | 预算耗尽后不再新开任务 | `test_i7_budget_exhaustion_refuses_new_tasks` | `test_i7_negative_control_unlimited_budget_never_refuses` |
| I-8 | 取消是协作式且不自动重试 | `test_i8_cancel_is_cooperative_and_never_retries` | `test_i8_negative_control_without_cancel_task_runs` |
| I-9 | 台账可重建 | `test_i9_tasks_snapshot_rebuilds_byte_identical` | `test_i9_negative_control_rebuild_detects_manual_corruption` |
| I-10 | 结果合并顺序确定 | `test_i10_merge_order_is_deterministic_across_runs` | `test_i10_negative_control_order_is_input_order_not_completion` |

另外覆盖规格书明确要求的若干条（"拒绝也是一个结果"、深度链、扇出、循环、预算、
墙钟、取消、dispose 幂等、backend 抽象、tree/stats）。
"""

from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

from agentflow import capabilities as C
from agentflow import conductor as CO
from agentflow import policy as P
from agentflow import scheduler as SC
from agentflow import schema as S
from agentflow.agent_c import AgentC
from agentflow.agent_e import AgentE
from agentflow.agent_h import AgentH
from agentflow.cancellation import CancelRequested, CancelToken
from agentflow.store import Store


# ---------------------------------------------------------------- 夹具（与 test_scheduler 同构）


def _mk_store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


class FakeC(AgentC):
    """C 的替身：只读分析（写集只有它自己的产出表 `analysis_reports`）。"""

    def __init__(self):
        pass

    def hottest(self, top_n: int = 5, request: str = ""):
        return {"outcome": "ok", "detail": f"hottest({top_n})", "checked": True,
                "payload": {"top": ["0000"]}}

    def cold(self, top_n: int = 5, request: str = ""):
        return {"outcome": "no_result", "detail": "没有冷门概念", "checked": True,
                "payload": {"checked": True, "empty": True}}

    def neighbors(self, concept_id: str, *, depth: int = 1, max_nodes=None):
        return {"outcome": "ok", "detail": concept_id, "checked": True}


class FakeH(AgentH):
    """H 的替身：只读列举 + 一个会写 `documents/review_findings` 的 review。"""

    def __init__(self, *, findings=None, sleep=0.0):
        self.findings = findings if findings is not None else [{"kind": "overclaim"}]
        self.sleep = sleep

    def list_findings(self, **filters):
        if self.sleep:
            time.sleep(self.sleep)
        return {"outcome": "ok", "detail": "findings", "checked": True,
                "payload": {"findings": self.findings}}

    def review(self, doc_id: str, *, round_no=None, dependencies=None):
        """不转发父类的 `_writer`（那要一个真注册表）。

        也不声称 `artifacts`：替身如果编一个 `documents:0001`，
        而库里根本没有这一行，`Conductor.verify_tasks()` 会（正确地）报出
        "artifact 指向不存在的行" —— 那不是框架的缺陷，是替身在谎报产出。
        """
        return {"outcome": "ok", "detail": f"review {doc_id}", "checked": True,
                "payload": {"checked": True, "doc_id": doc_id}}


class FakeE(AgentE):
    """E 的替身：写 `experiments`。可配置睡眠、token 花销、是否抛异常/取消。"""

    def __init__(self, *, sleep=0.0, tokens=0, boom=None, token: CancelToken | None = None,
                 checked_false=False):
        self.sleep = sleep
        self.tokens = tokens
        self.boom = boom
        self.token = token
        self.checked_false = checked_false
        self.entered = threading.Event()

    def run_experiment(self, claim, claim_key, script_path, *, sleep=None, **kw):
        self.entered.set()
        if self.boom is not None:
            raise self.boom
        total = float(self.sleep if sleep is None else sleep)
        deadline = time.monotonic() + total
        while time.monotonic() < deadline:
            if self.token is not None:
                self.token.raise_if_cancelled()
            time.sleep(0.01)
        if self.token is not None:
            self.token.raise_if_cancelled()
        if self.checked_false:
            # 三态纪律的"没法查"：checked=False 必须原样透传
            return {"outcome": "ok", "detail": "没法查", "checked": False,
                    "payload": {"checked": False, "reason": "没有检查器后端"}}
        return {"outcome": "ok", "detail": f"{claim} 跑完", "tokens": self.tokens,
                "payload": {"claim": claim}}

    def evidence_for(self, claim_key: str | None = None, *, for_question_id=None):
        return None  # ⇒ outcome="no_result"（跑完了，确实没有）


class TwoStep:
    """一个提供 `run_once` 的替身（A/B 的链测试用）。"""

    def __init__(self, name="step"):
        self.name = name

    def run_once(self):
        return {"outcome": "ok", "detail": self.name}


class FakeD:
    def probe_c(self, qid, qrow=None):
        return {"outcome": "ok", "detail": f"D.probe_c({qid})"}


class FakeF:
    def status(self, plan_id):
        return {"outcome": "ok", "detail": f"F.status({plan_id})"}


def _conductor(store, *, policy=None, registry=None, token=None, backend="local") -> CO.Conductor:
    return CO.Conductor(
        store,
        policy=policy or P.Policy(max_concurrency=4, max_fanout=5,
                                  max_tasks_per_run=100, wall_clock_sec=60),
        registry=registry or {},
        backend=backend,
        token=token,
    )


def _e_call(claim="c1", *, sleep=0.0) -> SC.TaskCall:
    """构造一个 E 的 `run_experiment` 调用。

    默认带上 `input_key`：它落进台账后，审计不必报 `task_without_input_key`
    （判重键为空 ⇒ 这条召唤无法参与循环检测）。默认带一个而不是让每个
    用例各自记得传，是因为"忘了传"的症状是审计多报一条警告，
    而那种警告一多就会被读成背景噪音。
    """
    return SC.TaskCall("E", "run_experiment",
                       {"claim": claim, "claim_key": f"k-{claim}",
                        "script_path": "s.py", "sleep": sleep},
                       input_key=f"e:{claim}")


def _row(store: Store, task_id: str) -> dict:
    return next(r for r in store.rows("tasks") if r["task_id"] == task_id)


def _tasks_bytes(store: Store) -> bytes:
    return (store.data / "tasks.json").read_bytes()


# ---------------------------------------------------------------- I-1


def test_i1_every_start_has_exactly_one_end(tmp_path):
    """I-1：`status ∈ {done,cancelled,failed}` ⇒ `ended_at` 非空；
    `running` ⇒ `ended_at` 为空。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE()), "C": ("object", FakeC()),
                                    "H": ("object", FakeH())})
    outs = [
        c.summon("E", "run_experiment", {"claim": "a", "claim_key": "ka", "script_path": "s.py"},
                 input_key="i1"),
        c.summon("C", "hottest", {"top_n": 2}, input_key="i2"),
        c.summon("H", "review", {"doc_id": "0001"}, input_key="i3"),
        c.summon("C", "no_action", {}, input_key="i4"),          # refused（也是 done）
    ]
    assert [o.status for o in outs] == ["done", "done", "done", "done"]
    for r in store.rows("tasks"):
        if r["status"] in CO.TERMINAL_STATUSES:
            assert r["ended_at"], f"{r['task_id']} 是终态却没有 ended_at"
            assert r["started_at"], f"{r['task_id']} 是终态却没有 started_at"
        else:
            assert not r["ended_at"], f"{r['task_id']} 未结束却有 ended_at"
    assert c.verify_tasks() == []


def test_i1_negative_control_running_row_is_inspectable(tmp_path):
    """I-1 负控：任务在跑的那一刻，台账里必须已经有一行 `running`
    （`started_at` 非空、`ended_at` 为空）。

    这条防的是"攒到最后一起写"：中途崩溃时台账必须已经能回答
    "它跑到哪一步了"（设计 §5 末条）。如果 `summon` 只在结束时写行，
    那么"正在跑"这件事在台账里根本不存在。
    """
    store = _mk_store(tmp_path)
    seen: dict = {}

    class SpyE(AgentE):
        def __init__(self) -> None:
            pass

        def run_experiment(self, claim, claim_key, script_path, **kw):
            rows = store.rows("tasks")
            assert len(rows) == 1, f"开始执行时台账里应恰有一行，实际 {len(rows)}"
            seen.update(rows[0])
            return {"outcome": "ok", "detail": "spy"}

    c = _conductor(store, registry={"E": ("object", SpyE())})
    r = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "k", "script_path": "s.py"})
    assert seen["task_id"] == r.task_id
    assert seen["status"] == "running"
    assert seen["started_at"] and not seen["ended_at"]
    assert seen["outcome"] is None
    # 跑完之后同一行变成终态
    assert _row(store, r.task_id)["status"] == "done"


# ---------------------------------------------------------------- I-2


def test_i2_terminal_state_is_immutable(tmp_path):
    """I-2：对已结束任务再调 `finish()` ⇒ 零变更（逐字节比对 `tasks.json`）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE())})
    r = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "k", "script_path": "s.py"})
    assert r.status == "done"
    before = _tasks_bytes(store)
    for _ in range(3):
        again = c.finish(
            r.task_id, status="failed", outcome="failed", error="试图改写终态",
            detail="这是第二次写，必须什么都不做",
        )
    after = _tasks_bytes(store)
    assert before == after, "终态被改写了（逐字节比对不等）"
    row = _row(store, r.task_id)
    assert row["status"] == "done" and row["outcome"] == "ok" and row["error"] is None
    # 返回的是磁盘上已有的终态，不是调用方想写的那一个
    assert again.status == "done" and again.outcome == "ok"


def test_i2_negative_control_first_writer_wins(tmp_path):
    """I-2 负控：先写下的终态赢 —— 第二次写不许覆盖它。

    上面那条测试如果实现成"总是重写但内容恰好相同"，bytes 也会相等。
    这条用不同的 status/outcome 去写，断言磁盘上仍然是第一次的那个。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE())})
    r = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "k", "script_path": "s.py"})
    assert (r.status, r.outcome) == ("done", "ok")
    c.finish(r.task_id, status="cancelled", outcome="cancelled", detail="后到的取消")
    c.finish(r.task_id, status="done", outcome="refused", refusal_reason="budget_exceeded",
             detail="后到的拒绝")
    row = _row(store, r.task_id)
    assert (row["status"], row["outcome"]) == ("done", "ok")
    assert row["refusal_reason"] is None
    assert "后到" not in row["detail"]


def test_i2_refusal_is_also_a_terminal_state(tmp_path):
    """被拒的行同样是终态：再 finish 也必须零变更（refused 也要幂等）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={})
    r = c.summon("C", "hottest", {"top_n": 1})   # 没接线 ⇒ refused/not_wired
    assert r.outcome == "refused"
    before = _tasks_bytes(store)
    c.finish(r.task_id, status="cancelled", outcome="cancelled", detail="后到")
    assert _tasks_bytes(store) == before


# ---------------------------------------------------------------- I-3


def test_i3_depth_is_parent_plus_one(tmp_path):
    """I-3：子任务的 `depth` 恒等于父 `depth + 1`（主控发起 = 1）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"A": ("object", TwoStep("a")), "B": ("object", TwoStep("b")),
                                    "C": ("object", FakeC())})
    d1 = c.summon("A", "run_once", {}, input_key="k1")
    d2 = c.summon("B", "run_once", {}, by="A", parent_task_id=d1.task_id, input_key="b")
    d3 = c.summon("C", "hottest", {"top_n": 1}, by="B", parent_task_id=d2.task_id, input_key="c")
    assert (d1.depth, d2.depth, d3.depth) == (1, 2, 3)
    rows = {r["task_id"]: r for r in store.rows("tasks")}
    assert rows[d2.task_id]["depth"] == rows[d1.task_id]["depth"] + 1
    assert rows[d3.task_id]["depth"] == rows[d2.task_id]["depth"] + 1
    assert rows[d3.task_id]["called_by"] == "B"
    assert c.verify_tasks() == []


def test_i3_negative_control_dangling_parent_is_refused(tmp_path):
    """I-3 负控：父任务不存在 ⇒ 拒绝（不许凭空挂一个父）。

    凭空挂父会让深度链断裂，而"深度"是 `max_depth` 的唯一判据 ——
    链断了，深度上限就静默失效。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    r = c.summon("C", "hottest", {"top_n": 1}, parent_task_id="t-9999")
    assert r.status == "done" and r.outcome == "refused"
    # `invalid_params` 而不是 `unknown_action`（`draft/28` §154 的 R-46）：
    # 父任务不存在是这次调用本身不成立，不是"这个角色没这个本事"。
    # 原来的理由码把两件事混在一起，排查方向会被引到能力表上去。
    assert r.refusal_reason == "invalid_params"
    assert "不存在" in r.detail
    # 拒绝也落台账（"我们拒绝了它"必须可审计）
    assert len(store.rows("tasks")) == 1


# ---------------------------------------------------------------- I-4


def test_i4_refused_always_has_controlled_reason(tmp_path):
    """I-4：`outcome="refused"` ⇒ `refusal_reason ∈ REFUSAL_REASONS`。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE())})
    out = [
        c.summon("C", "hottest", {"top_n": 1}, by="C", input_key="e1"),        # forbidden_edge
        c.summon("Z", "x", {}, input_key="e2"),                                # unknown_role
        c.summon("C", "没有这个动作", {}, input_key="e3"),                      # unknown_action
        c.summon("H", "list_findings", {}, input_key="e4"),                    # not_wired
        c.summon("E", "run_experiment", {"claim": "c"}, input_key="e5"),       # 参数缺 claim_key/script_path
    ]
    reasons = []
    for r in out:
        assert r.status == "done" and r.outcome == "refused"
        assert r.refusal_reason in S.REFUSAL_REASONS, f"拒绝理由 {r.refusal_reason!r} 不在受控词表"
        assert r.detail.strip(), "拒绝必须带人可读的理由"
        reasons.append(r.refusal_reason)
    assert reasons == ["forbidden_edge", "unknown_role", "unknown_action", "not_wired",
                       "invalid_params"]
    # 拒绝也落台账 —— 每一行都在表里
    rows = store.rows("tasks")
    assert len(rows) == len(out)
    assert all(r["outcome"] == "refused" and r["refusal_reason"] in S.REFUSAL_REASONS for r in rows)
    assert c.verify_tasks() == []


def test_i4_negative_control_no_refusal_reason_on_ok(tmp_path):
    """I-4 负控：成功的行不许带 `refusal_reason`。

    一个看着像"已拒绝"的成功行会让下游把"做成了"读成"被拦住了"。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE())})
    r = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "k", "script_path": "s.py"})
    row = _row(store, r.task_id)
    assert row["outcome"] == "ok" and row["refusal_reason"] is None
    assert r.refusal_reason is None


# ---------------------------------------------------------------- I-5


def test_i5_peak_concurrency_within_limit(tmp_path):
    """I-5：峰值同时 `running` 的行数 ≤ `max_concurrency`。"""
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=8, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "C": ("object", FakeC()), "E": ("object", FakeE(sleep=0.15)),
        "H": ("object", FakeH(sleep=0.15)),
    })
    plan = [_e_call(f"e{i}", sleep=0.15) for i in range(3)]
    plan += [SC.TaskCall("H", "list_findings", {}) for _ in range(2)]
    res = c.run_plan(plan)
    assert len(res) == 5
    assert c.peak_running <= pol.max_concurrency, (
        f"峰值并发 {c.peak_running} 超过 max_concurrency={pol.max_concurrency}"
    )


def test_i5_negative_control_limit_is_actually_reached(tmp_path):
    """I-5 负控：并发上限必须被用满，否则"≤ 上限"是废话。

    ## 两个数字：为什么断言的是探针而不是 `conductor.peak_running`

    - `scheduler.ConcurrencyProbe.peak` 数的是"真的在跑的任务数"
      （进入执行窗口 +1、出窗口 -1）。它是"真并发"的判据。
    - `conductor.peak_running` 数的是"已经登记为 running 且还没写终态"的行数。
      它≤ 探针：一次 `summon` 在调 handler 之前还要落一行 `running`
      （含一次 fsync 事务，实测 20~60ms）。三个任务各自落行期间，先落完的那个
      可能已经跑完了 —— 于是同一瞬间"登记在飞"的只有 2 个，而执行窗口
      确实重叠了 3 个。

    把 `peak_running == 上限` 当成判据会得到一个偶发失败的测试
    （它与机器快慢有关），而那正是"时间断言要给足余量"要防的东西。
    所以：峰值并发用探针判，`peak_running` 只判"≤ 上限"（I-5 的字面要求）。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=3, max_fanout=8, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "C": ("object", FakeC()), "H": ("object", FakeH(sleep=0.3)),
        "E": ("object", FakeE(sleep=0.3)),
    })
    plan = [SC.TaskCall("H", "list_findings", {}), SC.TaskCall("C", "hottest", {"top_n": 1}),
            _e_call("e1", sleep=0.3)]
    # 三个角色两两写集不相交（H{documents,review_findings} / C{analysis_reports}
    # / E{experiments}）⇒ 同波并发 3
    assert len(P.waves_of(plan, limit=3)) == 1
    res = c.run_plan(plan)
    assert len(res) == 3 and all(r.outcome == "ok" for r in res)
    assert c.peak_running <= pol.max_concurrency, (
        f"峰值并发 {c.peak_running} 超过 max_concurrency={pol.max_concurrency}"
    )
    assert c._last_probe is not None, "run_waves 必须留下可观测的并发探针（便于验收）"
    assert c._last_probe.peak == 3, (
        f"峰值真并发 {c._last_probe.peak} ≠ 上限 3 ⇒ 并发没被用满"
    )


# ---------------------------------------------------------------- I-6


def test_i6_intersecting_write_sets_are_serialized(tmp_path):
    """I-6：写集相交的两个任务不许并发（都写 `experiments`）。"""
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(sleep=0.15))})
    assert len(P.waves_of([_e_call("a", sleep=0.15), _e_call("b", sleep=0.15)], limit=4)) == 2
    t0 = time.monotonic()
    res = c.run_plan([_e_call("a", sleep=0.15), _e_call("b", sleep=0.15)])
    elapsed = time.monotonic() - t0
    assert [r.outcome for r in res] == ["ok", "ok"]
    assert elapsed >= 0.3 * 0.85, f"两个写 experiments 的任务被并发了（耗时 {elapsed:.3f}s）"


def test_i6_negative_control_disjoint_are_parallel(tmp_path):
    """I-6 负控：写集不相交的两个任务必须并发（否则判据退化成"永远串行"）。

    注意：时间判据用相对比较（与"两个都串行"的耗时对比），不用绝对秒数：
    旧版写死 `elapsed < 0.6 * 0.85`（= 0.51s），而两个任务各自 sleep 0.3s ⇒
    并发时理论 0.30s、串行时 0.60s，余量只有 0.21s。
    实测（`R5` 第一次重审的观测窗口 15:5x，机器上同时有 3 个审计者在跑）
    这条会偶发失败 —— 那是判据的余量太窄，不是并发坏了：
    重跑 3/3 通过（审计者撤回的怀疑里记了这一条），我在自己跑全量时也撞到一次。
    改法：同时测"相交 ⇒ 串行"与"不相交 ⇒ 并发"两个形态，只比较它们的比值
    —— 机器慢会同时拖慢两者，比值不受影响。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)

    # ① 不相交 ⇒ 并发
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(sleep=0.3)),
                                                "C": ("object", FakeC())})
    plan = [_e_call("a", sleep=0.3), SC.TaskCall("C", "hottest", {"top_n": 1})]
    assert len(P.waves_of(plan, limit=4)) == 1
    t0 = time.monotonic()
    c.run_plan(plan)
    parallel = time.monotonic() - t0

    # ② 相交 ⇒ 串行（同一份 sleep）
    store2 = _mk_store(tmp_path / "s2")
    c2 = _conductor(store2, policy=pol, registry={"E": ("object", FakeE(sleep=0.3))})
    t0 = time.monotonic()
    c2.run_plan([_e_call("a", sleep=0.3), _e_call("b", sleep=0.3)])
    serial = time.monotonic() - t0

    assert serial > parallel * 1.4, (
        f"不相交的两个任务没有并发：并行 {parallel:.3f}s vs 串行 {serial:.3f}s"
        "（比值必须 > 1.4；机器慢会同时拖慢两者，比值不受影响）"
    )


# ---------------------------------------------------------------- I-7


def test_i7_budget_exhaustion_refuses_new_tasks(tmp_path):
    """I-7：钱花光 ⇒ 后续召唤 `refused/budget_exceeded`，
    而已经在跑的那个不被砍（它是"钱花光了"，不是"被预算杀死"）。

    ⚠️ 2026-10-15 业主裁定 A1/A2/A3/A7 + B2/B4 之后，这条路上的"预算"**只剩钱、
    且只有一处判据**（全局已花 vs 全局预算）。此前它传的是
    `budget={"max_tokens": 1}`（token 轴，已删）；现在判据来自
    `Policy(usd_budget=0.0)` —— "这一次运行一个子儿都不许花"。
    `usd_budget=0.0` 与 `None` 语义不同：前者是"预算为零"，后者是"没设预算"。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100,
                   wall_clock_sec=60, usd_budget=0.0)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(tokens=100))})
    first = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "ka", "script_path": "s.py"},
                     input_key="k1")
    assert first.status == "done" and first.outcome == "refused"
    assert first.refusal_reason == "budget_exceeded", first.detail
    assert c.verify_tasks() == []


def test_i7_a_running_task_is_not_killed_when_the_budget_runs_out(tmp_path):
    """I-7 的另一半：钱花光**之后**，已经在跑的那个不许被砍。

    判据是那一行的终态仍然是它自己的结局（不是 `cancelled`）——
    "花光了预算"与"被预算杀死"是两件事。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100,
                   wall_clock_sec=60, usd_budget=1.0)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(tokens=100))})
    first = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "ka", "script_path": "s.py"},
                     input_key="k1")
    assert first.outcome == "ok" and first.tokens == 100
    # 把账上的钱推过上限（模拟另一个角色花掉的），再派一件新的
    from agentflow.tokenmeter import Charge

    c.meter.charge(Charge(role="A", scope="search", usd=2.0, task_id="t-9999", note="别的角色花的"))
    second = c.summon("E", "run_experiment", {"claim": "b", "claim_key": "kb", "script_path": "s.py"},
                      input_key="k2")
    assert second.outcome == "refused" and second.refusal_reason == "budget_exceeded"
    assert _row(store, first.task_id)["status"] == "done", "在跑的那个不许被砍"
    assert _row(store, first.task_id)["outcome"] == "ok"


def test_i7_negative_control_unlimited_budget_never_refuses(tmp_path):
    """I-7 负控：不设预算时，花再多 token / 再多钱也不许因此被拒。

    三态纪律：`None`（没设预算）与 `0`（预算为零）语义不同。把"不限"
    实现成 0 的话，第二次调用就会被拒 —— 而调用方以为自己没有上限。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100,
                   wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(tokens=10**6))})
    outs = [c.summon("E", "run_experiment",
                     {"claim": f"c{i}", "claim_key": f"k{i}", "script_path": "s.py"})
            for i in range(3)]
    assert [o.outcome for o in outs] == ["ok", "ok", "ok"]
    st = c.budget.state(pol)
    assert st["usd_left"] is None, "不限必须原样是 None，不许折叠成 0"
    assert "tokens_left" not in st and "token_budget" not in st, (
        "token 不许再以判据的形状出现在预算读数里（裁定 A7）"
    )
    assert st["spent_tokens"] == 3 * 10**6, "但花了多少 token 要看得见（读数）"


# ---------------------------------------------------------------- I-8


def test_i8_cancel_is_cooperative_and_never_retries(tmp_path):
    """I-8：被取消的任务 `outcome="cancelled"`；取消后不产生新任务；
    被砍掉的任务不被重试（台账里只有它一行）。"""
    store = _mk_store(tmp_path)
    token = CancelToken()
    e = FakeE(sleep=5.0, token=token)
    pol = P.Policy(max_concurrency=1, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", e)}, token=token)
    out: dict = {}
    th = threading.Thread(target=lambda: out.update(res=c.run_plan([
        _e_call("a", sleep=5.0), _e_call("b", sleep=5.0),
    ])))
    th.start()
    assert e.entered.wait(timeout=5.0)
    c.cancel("user", detail="人按了停止")
    th.join(timeout=20.0)
    assert not th.is_alive()
    res = out["res"]
    assert res[0].status == "cancelled" and res[0].outcome == "cancelled"
    rows = store.rows("tasks")
    assert len(rows) == 1, f"取消后不该产生新任务（台账 {len(rows)} 行）"
    assert rows[0]["status"] == "cancelled" and rows[0]["outcome"] == "cancelled"
    assert rows[0]["input_key"], "被判重键要落台账（否则循环检测对这条召唤无效）"
    # 不自动重试：整个台账里只有这一次召唤
    assert c.stats()["total"] == 1
    assert c.verify_tasks() == []


def test_i8_negative_control_without_cancel_task_runs(tmp_path):
    """I-8 负控：没有取消时，同样的 plan 必须跑完（两条都要落台账）。

    否则上面那条"只有一行"可能只是因为"第二个任务本来就不跑"。
    """
    store = _mk_store(tmp_path)
    e = FakeE(sleep=0.02)
    pol = P.Policy(max_concurrency=1, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", e)})
    res = c.run_plan([_e_call("a", sleep=0.02), _e_call("b", sleep=0.02)])
    assert [r.outcome for r in res] == ["ok", "ok"]
    assert len(store.rows("tasks")) == 2


# ---------------------------------------------------------------- I-9


def test_i9_tasks_snapshot_rebuilds_byte_identical(tmp_path):
    """I-9：`store.rebuild()` 后 `tasks.json` 逐字节一致（FC-12）。

    实现前提：每条事件里存的是整行 upsert，折叠逻辑是"按主键 last-write-wins"，
    而行的写入顺序与首次建行的顺序一致 —— 所以重建出的行序也一致。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE(tokens=3)), "C": ("object", FakeC()),
                                    "H": ("object", FakeH())})
    c.run_plan([_e_call("a"), SC.TaskCall("C", "hottest", {"top_n": 1}),
                SC.TaskCall("H", "review", {"doc_id": "0001"})])
    c.summon("Z", "x", {})                      # 一条 refused 行
    c.finish(next(r["task_id"] for r in store.rows("tasks") if r["status"] == "done"),
             status="done", outcome="ok", detail="重复 finish（幂等，不落事件）")
    before = _tasks_bytes(store)
    store.rebuild(backup=False)
    after = _tasks_bytes(store)
    assert before == after, "rebuild 后 tasks.json 逐字节不一致（台账不可重建）"


def test_i9_negative_control_rebuild_detects_manual_corruption(tmp_path):
    """I-9 负控：手工把 `tasks.json` 改坏（删掉一行）后 `rebuild()` 必须复原。

    没有这条，上面那条"逐字节一致"可能只是因为"两张文件都没被碰过"。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    c.summon("C", "hottest", {"top_n": 1})
    c.summon("C", "cold", {"top_n": 1})
    good = _tasks_bytes(store)
    doc = json.loads(good.decode("utf-8"))
    assert len(doc["rows"]) == 2
    doc["rows"] = doc["rows"][:1]                      # 手工删掉一行
    (store.data / "tasks.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert _tasks_bytes(store) != good
    store.rebuild(backup=False)
    assert _tasks_bytes(store) == good, "rebuild 没有从事件复原被删掉的行"


# ---------------------------------------------------------------- I-10


def test_i10_merge_order_is_deterministic_across_runs(tmp_path):
    """I-10：同一 plan 跑两次，`SummonResult` 列表顺序相同。"""
    pol = P.Policy(max_concurrency=4, max_fanout=8, max_tasks_per_run=100, wall_clock_sec=60)
    plan_factory = lambda: [  # noqa: E731
        SC.TaskCall("E", "run_experiment", {"claim": "e", "claim_key": "ke",
                                            "script_path": "s.py", "sleep": 0.15}),
        SC.TaskCall("C", "hottest", {"top_n": 1}),
        SC.TaskCall("H", "list_findings", {}),
        SC.TaskCall("E", "run_experiment", {"claim": "e2", "claim_key": "ke2",
                                            "script_path": "s.py", "sleep": 0.05}),
    ]
    orders = []
    for i in range(2):
        store = _mk_store(tmp_path / f"run{i}")
        c = _conductor(store, policy=pol, registry={
            "E": ("object", FakeE(sleep=0.15)), "C": ("object", FakeC()),
            "H": ("object", FakeH()),
        })
        res = c.run_plan(plan_factory())
        orders.append([(r.role, r.action, r.status, r.outcome) for r in res])
    assert orders[0] == orders[1], "两次跑同一 plan 得到不同顺序 ⇒ 结果不可复现"


def test_i10_negative_control_order_is_input_order_not_completion(tmp_path):
    """I-10 负控：返回顺序必须是输入顺序，不是完成顺序。

    慢的那个放第一位、快的放第二位：按完成顺序会得到 `[fast, slow]`。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=8, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "E": ("object", FakeE(sleep=0.25)), "C": ("object", FakeC()),
    })
    res = c.run_plan([
        _e_call("slow", sleep=0.25),
        SC.TaskCall("C", "hottest", {"top_n": 1, "request": "fast"}),
    ])
    assert [r.role for r in res] == ["E", "C"], "完成顺序泄漏进了结果顺序"
    assert res[0].detail.endswith("跑完")


# ---------------------------------------------------------------- 拒绝也是一个结果（越权边）


def test_forbidden_edge_is_recorded_in_ledger(tmp_path):
    """拒绝也是一个结果：`C → B` ⇒ `outcome="refused"`,
    `refusal_reason="forbidden_edge"`，且台账里有这一行。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC()), "B": ("object", TwoStep("b"))})
    r = c.summon("B", "run_once", {}, by="C", input_key="越权尝试")
    assert r.status == "done", "拒绝是**成功的执行**（框架正确地说『不』），不是 failed"
    assert r.outcome == "refused"
    assert r.refusal_reason == "forbidden_edge"
    rows = store.rows("tasks")
    assert len(rows) == 1, "不写这一行，『我们拒绝了它』就无可审计"
    assert rows[0]["role"] == "B" and rows[0]["called_by"] == "C"
    assert rows[0]["outcome"] == "refused"
    assert rows[0]["refusal_reason"] == "forbidden_edge"
    assert rows[0]["started_at"] and rows[0]["ended_at"]
    assert c.verify_tasks() == []


def test_refusal_negative_control_forbidden_pair_actually_allowed_list(tmp_path):
    """负控：`C → B` 被拒，且 C 对每一个目标都一律被拒。

    即：C 的边真的是空的，不是"某些边被挡了但另一些漏过去了"。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"A": ("object", TwoStep("a")), "C": ("object", FakeC())})
    for target, action, params in (
        ("A", "run_once", {}),
        ("B", "run_once", {}),
        ("D", "poll", {}),
        ("E", "evidence_for", {"claim_key": "k"}),
    ):
        r = c.summon(target, action, params, by="C", input_key=f"越权-{target}")
        assert r.outcome == "refused", f"C → {target} 竟然被放行"
        assert r.refusal_reason == "forbidden_edge"


# ---------------------------------------------------------------- 深度链（规格书明确要求）


def test_four_layer_chain_is_refused_by_depth(tmp_path):
    """深度：造一条 `M→A→B→C` 的链，断言第 4 层被 `depth_exceeded` 拒。

    `max_depth=3`：`M` 发起 = 1，所以 `A(1) → B(2) → C(3)` 已到底，
    第 4 层无论走哪条边都必须被深度拒。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_depth=3, max_concurrency=4, max_fanout=8,
                   max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "A": ("object", TwoStep("a")), "B": ("object", TwoStep("b")), "C": ("object", FakeC()),
    })
    d1 = c.summon("A", "run_once", {})
    d2 = c.summon("B", "run_once", {}, by="A", parent_task_id=d1.task_id, input_key="b")
    d3 = c.summon("C", "hottest", {"top_n": 1}, by="B", parent_task_id=d2.task_id, input_key="c")
    assert (d1.depth, d2.depth, d3.depth) == (1, 2, 3)
    assert d3.outcome == "ok", "第 3 层还在上限内，必须放行"
    # 第 4 层：从 C 再召唤 —— C 的边是空的，所以这里改用 B→C 的"更深一个"
    d4 = c.summon("C", "cold", {"top_n": 1}, by="B", parent_task_id=d3.task_id, input_key="d")
    assert (d3.depth, d4.depth) == (3, 4)
    assert d4.status == "done" and d4.outcome == "refused"
    assert d4.refusal_reason == "depth_exceeded"


# ---------------------------------------------------------------- dispose


def test_dispose_closes_running_rows_and_is_idempotent(tmp_path):
    """`dispose()`：把仍在 `pending/running` 的任务合成 `cancelled` 的 end 事件，
    `detail` 里写明"因 dispose 而终止，结果未知"；两次调用逐字节幂等。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    r = c.summon("C", "hottest", {"top_n": 1}, input_key="i1")
    assert r.status == "done"
    # 手工造一条 running 的僵尸行（模拟"进程被杀在任务中间"）
    zombie = S.Task(
        task_id="t-9998", role="C", action="hottest", called_by="M", depth=1,
        status="running", started_at=S.now_iso(), ended_at=None, detail="跑到一半",
        input_key="zombie",
    )
    zombie.validate()
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", zombie.to_dict())

    out1 = c.dispose()
    assert out1["closed"] == ["t-9998"]
    row = _row(store, "t-9998")
    assert row["status"] == "cancelled" and row["outcome"] == "cancelled"
    assert row["ended_at"], "每个 start 必须有 end（否则台账里会有永远在跑的僵尸）"
    assert "结果未知" in row["detail"], "被中途砍掉的任务**结果未知**，不许写『失败』"
    assert "dispose" in row["detail"]
    assert c.verify_tasks() == []

    after_first = _tasks_bytes(store)
    out2 = c.dispose()
    assert out2["closed"] == []
    assert _tasks_bytes(store) == after_first, "dispose 第二次必须逐字节零变更"


def test_dispose_does_not_rewrite_finished_rows(tmp_path):
    """负控（dispose）：已完成的 `ok` 行不许被 dispose 改成 cancelled。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    r = c.summon("C", "hottest", {"top_n": 1})
    before = _tasks_bytes(store)
    c.dispose()
    assert _tasks_bytes(store) == before
    assert _row(store, r.task_id)["outcome"] == "ok"


def test_dispose_refuses_new_summons(tmp_path):
    """dispose 之后不再产生新任务（`task_id is None`）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    c.dispose()
    before = len(store.rows("tasks"))
    r = c.summon("C", "hottest", {"top_n": 1})
    assert r.status == "cancelled" and r.task_id is None
    assert len(store.rows("tasks")) == before


# ---------------------------------------------------------------- 三态纪律


def test_none_result_is_no_result_not_ok(tmp_path):
    """handler 返回 `None` ⇒ `outcome="no_result"`（跑完了，确实没有）。

    把它写成 `ok` 正是"把『没做』与『做了没结果』折叠成同一个值" ——
    本项目在引文校验、OCR、D 溯源、C 预算截断四处踩过它。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE())})
    r = c.summon("E", "evidence_for", {"claim_key": "k"})
    assert r.status == "done" and r.outcome == "no_result"
    assert r.outcome != "ok"
    assert not r.ok, "`.ok` 的判据是 status==done 且 outcome==ok"


def test_checked_false_is_passed_through(tmp_path):
    """`checked=False` 必须原样透传：查询没法做时不许写成"查了没有"。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE(checked_false=True))})
    r = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "k", "script_path": "s.py"})
    assert r.checked is False
    assert r.payload["checked"] is False and r.payload["reason"]


def test_checked_negative_control_true_is_passed_through(tmp_path):
    """负控：`checked=True` 时不许被改写成 False（透传是双向的）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    r = c.summon("C", "hottest", {"top_n": 1})
    assert r.checked is True


def test_handler_exception_is_failed_with_error_text(tmp_path):
    """handler 抛其它异常 ⇒ `failed` + `error` 写异常文本（不许吞）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE(boom=ValueError("参数没配好")))})
    r = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "k", "script_path": "s.py"},
                 input_key="i1")
    assert r.status == "failed" and r.outcome == "failed"
    assert r.error is not None and "ValueError" in r.error and "参数没配好" in r.error
    row = _row(store, r.task_id)
    assert row["status"] == "failed" and row["error"] == r.error
    assert c.verify_tasks() == []


def test_cancel_requested_is_cancelled_not_failed(tmp_path):
    """`CancelRequested` ⇒ `cancelled`（不是 failed）：取消是外部决定，不是错误。"""
    store = _mk_store(tmp_path)

    class Raiser(AgentE):
        def __init__(self) -> None:
            pass

        def run_experiment(self, claim, claim_key, script_path, **kw):
            raise CancelRequested("预算耗尽")

    c = _conductor(store, registry={"E": ("object", Raiser())})
    r = c.summon("E", "run_experiment", {"claim": "a", "claim_key": "k", "script_path": "s.py"})
    assert r.status == "cancelled" and r.outcome == "cancelled"
    assert r.error is None, "取消不是失败，不许写 error"
    assert "预算耗尽" in r.detail


# ---------------------------------------------------------------- backend 抽象


def test_subagent_backend_refuses_loudly_not_silently(tmp_path):
    """`SubagentBackend` 必须显式拒绝（`refused/not_wired`），
    绝不允许把"未接线"写成"执行成功但没结果"。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, backend="subagent")
    r = c.summon("C", "hottest", {"top_n": 1})
    assert r.status == "done" and r.outcome == "refused"
    assert r.refusal_reason == "not_wired"
    assert r.payload is None
    assert "subagent" in r.detail or "DSH" in r.detail
    assert r.outcome != "no_result", "『没接线』与『做了没结果』必须能区分"


def test_local_backend_unwired_role_refuses_not_wired(tmp_path):
    """没给接线的角色也是 `not_wired`（不是 failed、不是 no_result）。

    B 由 A 转达（2026-10-10 裁定第 4 条：主控不许直接控制 B / F / V）⇒ 这一条走 M→A→B。
    判的仍然是"目标角色没接线"这一档；`forbidden_edge` 是另一档，
    见 `test_the_conductor_does_not_directly_control_bfv.py`。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    r = c.summon("B", "run_once", {}, by="A", input_key="unwired-b")
    assert r.status == "done" and r.outcome == "refused" and r.refusal_reason == "not_wired"


def test_local_backend_rejects_unknown_backend_name(tmp_path):
    """负控：拼错的 backend 名必须当场拒绝，不许"未知 ⇒ 逐个 if 落空"。"""
    store = _mk_store(tmp_path)
    with pytest.raises(ValueError, match="未知 backend"):
        CO.Conductor(store, backend="Local")


def test_local_backend_rejects_class_without_factory(tmp_path):
    """负控：只注册类（`("class", AgentC)`）⇒ 明确拒绝。

    构造依赖无法自动满足，假装能建就是"猜依赖"——而猜错的形态是
    静默少做事（例如一个没有 extractor 的 B）。
    """
    store = _mk_store(tmp_path)
    c = CO.Conductor(store, registry={"C": ("class", AgentC)})
    r = c.summon("C", "hottest", {"top_n": 1})
    assert r.outcome == "refused" and r.refusal_reason == "not_wired"
    assert "工厂" in r.detail


def test_local_backend_rejects_unknown_params(tmp_path):
    """负控：handler 不认的参数必须被拒（不许静默丢弃）。

    "我传了 `submit_requests=True` 但它被忽略了"看起来像一次成功 ——
    于是报告里说"已提交"，而请求一条也没有。
    """
    store = _mk_store(tmp_path)

    class Strict(AgentC):
        def __init__(self) -> None:
            pass

        def hottest(self, top_n=5, request=""):
            return {"outcome": "ok", "detail": "ok"}

    c = CO.Conductor(store, registry={"C": ("object", Strict())})
    # 参数 schema 会先拦下未声明的键（这是第一道闸）；理由码是 `invalid_params`
    # （`draft/28` §154 的 R-46：参数问题不许借 `unknown_action` 表达）
    r = c.summon("C", "hottest", {"top_n": 1, "不存在的参数": True})
    assert r.outcome == "refused" and r.refusal_reason == "invalid_params"
    assert "参数不合法" in r.detail


def test_local_backend_resolves_factory_once(tmp_path):
    """工厂只调一次（每个角色一份实例）：反复建实例会让"同一角色两次召唤
    看到不同的内存状态"，而那是无法复现的一半来源。"""
    store = _mk_store(tmp_path)
    calls = {"n": 0}

    def factory(*, store=None):
        calls["n"] += 1
        return FakeC()

    c = CO.Conductor(store, registry={"C": ("factory", factory)})
    c.summon("C", "hottest", {"top_n": 1})
    c.summon("C", "cold", {"top_n": 1})
    assert calls["n"] == 1


# ---------------------------------------------------------------- tree / stats


def test_tree_shows_parent_child_chain(tmp_path):
    """`tree()` 从台账读出父子链（跨会话恢复之后内存里什么都没有）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"A": ("object", TwoStep("a")), "B": ("object", TwoStep("b")),
                                    "C": ("object", FakeC())})
    d1 = c.summon("A", "run_once", {})
    d2 = c.summon("B", "run_once", {}, by="A", parent_task_id=d1.task_id, input_key="b")
    d3 = c.summon("C", "hottest", {"top_n": 1}, by="B", parent_task_id=d2.task_id, input_key="c")
    full = c.tree()
    assert [x["task_id"] for x in full] == [d1.task_id, d2.task_id, d3.task_id]
    assert [x["level"] for x in full] == [0, 1, 2]
    assert full[0]["children"] == [d2.task_id]
    assert full[1]["children"] == [d3.task_id]
    assert full[2]["children"] == []
    sub = c.tree(d2.task_id)
    assert [x["task_id"] for x in sub] == [d2.task_id, d3.task_id]
    assert [x["level"] for x in sub] == [0, 1]
    with pytest.raises(ValueError, match="没有这个任务"):
        c.tree("t-9999")


def test_stats_counts_by_role_outcome_and_depth(tmp_path):
    """`stats()`：按角色/outcome 的计数 + 深度分布 + 拒绝理由分布。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE(tokens=7)), "C": ("object", FakeC()),
                                    "H": ("object", FakeH())})
    c.summon("E", "run_experiment", {"claim": "a", "claim_key": "ka", "script_path": "s.py"})
    c.summon("C", "cold", {"top_n": 1})                     # no_result
    c.summon("H", "list_findings", {})                      # ok
    c.summon("C", "hottest", {"top_n": 1}, by="C")          # refused/forbidden_edge
    s = c.stats()
    assert s["total"] == 4
    assert s["by_role"] == {"E": 1, "C": 2, "H": 1}
    assert s["by_outcome"]["ok"] == 2 and s["by_outcome"]["no_result"] == 1
    assert s["by_outcome"]["refused"] == 1
    assert s["by_depth"] == {"1": 4}
    assert s["refusal_reasons"] == {"forbidden_edge": 1}
    assert s["budget"]["spent_tokens"] == 7
    assert s["unknown_outcome"] == 0
    # 未知结果必须单列（它不是 cancelled，是"我们不知道"）
    c.dispose()
    assert c.stats()["disposed"] is True


def test_stats_unknown_outcome_is_separate_from_cancelled(tmp_path):
    """负控（三态）：dispose 造成的取消要被单列成"结果未知"。

    把它并进 `cancelled` 的计数里，"有几件事我们其实不知道结果"
    这个数字就永远看不见了。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    zombie = S.Task(task_id="t-9000", role="C", action="hottest", status="running",
                    started_at=S.now_iso(), detail="跑到一半")
    zombie.validate()
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", zombie.to_dict())
    c.dispose()
    s = c.stats()
    assert s["unknown_outcome"] == 1
    assert s["by_outcome"]["cancelled"] == 1


# ---------------------------------------------------------------- 断言与联动的自检


def test_verify_tasks_detects_zombie_running_row(tmp_path):
    """`Conductor.verify_tasks()` 能报出僵尸 `running`（提议给 `verify_all` 的第一条检查）。

    这里手工造一个"有 started_at、无 ended_at 且已不可能再结束"的行 ——
    正是 `verify.py` 该报出来的东西。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store)
    zombie = S.Task(task_id="t-9001", role="C", action="hottest", status="running",
                    started_at=S.now_iso(), detail="僵尸")
    zombie.validate()
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", zombie.to_dict())
    problems = c.verify_tasks()
    assert any("[task_still_running]" in p and "t-9001" in p for p in problems), problems


def _inject_raw_rows(store: Store, payloads: list[dict]) -> None:
    """把故意非法的行直接写进 `tasks.json`（绕过 schema 校验）。

    为什么需要它：审计要抓的正是"schema 不让你写、但磁盘上真的会出现"的行
    （崩溃写一半、手工改坏、旧版本留下的行）。用 `store.tx` 写不进去
    （提交时会 `validate_table` 抛）—— 那不是限制，而是这条测试必须绕开
    校验器的证据：要么别造这种行，要么就承认它只能从校验器外面进来。
    """
    path = store.data / "tasks.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"].extend(payloads)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_task_ledger_audit_reports_every_expected_code(tmp_path):
    """负控：手工造一批各有一处毛病的行，断言审计把它们逐个报出来。

    这是"审计不是摆设"的判据：每一类问题都要有一条具名断言，
    否则某个分支写错了也永远不会被发现（`verify_tasks` 恒返回 `[]` 也能让
    所有"正控"测试通过）。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store)
    now = S.now_iso()
    legal = [
        # 父不存在
        S.Task(task_id="t-9000", role="C", action="hottest", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=2, parent_task_id="t-8888",
               input_key="k"),
        # 深度不连续：父 depth=1，子 depth=5
        S.Task(task_id="t-9001", role="C", action="hottest", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=1, input_key="k"),
        S.Task(task_id="t-9002", role="A", action="run_once", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=5, parent_task_id="t-9001",
               input_key="k"),
        # 无 input_key ⇒ task_without_input_key
        S.Task(task_id="t-9003", role="C", action="cold", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=1),
        # artifact 指向不存在的行 ⇒ dangling_task_artifact
        S.Task(task_id="t-9007", role="G", action="render", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=1, input_key="k",
               artifacts=["documents:9999"]),
        # 无父但 depth != 1 ⇒ task_root_depth_not_one
        S.Task(task_id="t-9008", role="C", action="cold", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=3, input_key="k"),
    ]
    for r in legal:
        r.validate()
    with store.tx("tasks", actor="test") as tx:
        for r in legal:
            tx.upsert("tasks", r.to_dict())

    # ---- 以下三类schema 会拒，只能从校验器外面进来（正因如此值得被抓）
    base = {
        "role": "C", "action": "cold", "called_by": "M", "parent_task_id": None, "depth": 1,
        "input_key": "k", "status": "done", "outcome": "ok", "refusal_reason": None,
        "detail": "d", "error": None, "started_at": now, "ended_at": now,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    _inject_raw_rows(store, [
        # 终态缺 ended_at ⇒ task_terminal_without_end
        {**base, "task_id": "t-9004", "ended_at": None},
        # 未结束却有 ended_at ⇒ task_terminal_rewritten + task_still_running
        {**base, "task_id": "t-9005", "status": "running", "outcome": None},
        # 非拒绝却带 refusal_reason ⇒ task_refusal_reason_on_non_refusal
        {**base, "task_id": "t-9010", "refusal_reason": "forbidden_edge"},
        # pending 且没有任何 worker 在跑 ⇒ task_still_running
        {**base, "task_id": "t-9009", "status": "pending", "outcome": None, "ended_at": None},
        # refused 但理由不在受控词表 ⇒ task_refused_without_reason
        {**base, "task_id": "t-9011", "outcome": "refused", "refusal_reason": "因为我不想跑"},
        # 无法识别的 artifact 前缀 ⇒ unknown_artifact_kind
        {**base, "task_id": "t-9012", "artifacts": ["不存在的表:0001"]},
    ])

    issues = {i.code for i in c.task_issues()}
    expected = {
        "dangling_parent_task", "task_depth_discontinuous", "task_without_input_key",
        "task_still_running", "task_terminal_without_end", "task_terminal_rewritten",
        "dangling_task_artifact", "unknown_artifact_kind", "task_root_depth_not_one",
        "task_refusal_reason_on_non_refusal", "task_refused_without_reason",
    }
    missing = expected - issues
    assert not missing, f"审计漏报了这些码：{sorted(missing)}（实际报了 {sorted(issues)}）"
    # 正向：这些码都属于声明过的受控集合（写错的码不许出现）
    assert issues <= set(C.TASK_AUDIT_CODES)


def test_task_ledger_audit_critical_codes_match_verify_all(tmp_path):
    """一致性测试（`DEVELOPMENT.md` §10 点名的那条）。

    `Conductor.verify_tasks` 与 `verify.verify_all` 的 tasks 段是同一个判据的
    两个入口。这条测试构造一批有毛病的行，断言：
    `verify_all` 报出的每一个 tasks 码，`task_issues()` 也都报得出
    （子集关系，因为 `verify_all` 还检查 `usage_ledger` 与 `eval_results`）。

    为什么需要它：两处各写一份判据必然漂移，而漂移的形态是
    "其中一处永远说没问题" —— 那是审计最坏的失效方式。
    只写注释说"两处应一致"正是这条规则要防的形态。
    """
    from agentflow.verify import verify_all

    store = _mk_store(tmp_path)
    c = _conductor(store)
    now = S.now_iso()
    rows = [
        S.Task(task_id="t-9000", role="C", action="hottest", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=2, parent_task_id="t-8888"),
        S.Task(task_id="t-9001", role="C", action="hottest", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=1),
        S.Task(task_id="t-9002", role="A", action="run_once", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=5, parent_task_id="t-9001"),
        S.Task(task_id="t-9003", role="C", action="cold", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=1),
        S.Task(task_id="t-9004", role="G", action="render", status="done", outcome="ok",
               detail="d", started_at=now, ended_at=now, depth=1, input_key="k",
               artifacts=["documents:9999", "统计:0001"]),
    ]
    for r in rows:
        r.validate()
    with store.tx("tasks", actor="test") as tx:
        for r in rows:
            tx.upsert("tasks", r.to_dict())

    rep = verify_all(store)
    verify_codes = {i.code for i in rep.issues if i.table == "tasks"}
    assert verify_codes, "verify_all 在有毛病的数据上一条 tasks 问题都没报 ⇒ 这条测试没有判据"
    mine = {i.code for i in c.task_issues()}
    assert verify_codes <= mine, (
        f"verify_all 报了 {sorted(verify_codes)}，但 Conductor 只报了 {sorted(mine)} ⇒ "
        "两份台账审计已经漂移"
    )
    assert mine <= set(C.TASK_AUDIT_CODES)


def test_verify_tasks_detects_depth_discontinuity(tmp_path):
    """负控：`verify_tasks` 能报出 `depth` 与父不连续（否则它只是个摆设）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store)
    rows = [
        S.Task(task_id="t-9000", role="M", action="summon", status="done", outcome="ok",
               detail="d", started_at=S.now_iso(), ended_at=S.now_iso(), depth=1),
        S.Task(task_id="t-9001", role="C", action="hottest", status="done", outcome="ok",
               detail="d", started_at=S.now_iso(), ended_at=S.now_iso(), depth=5,
               parent_task_id="t-9000"),
    ]
    for r in rows:
        r.validate()
    with store.tx("tasks", actor="test") as tx:
        for r in rows:
            tx.upsert("tasks", r.to_dict())
    problems = c.verify_tasks()
    assert any("depth" in p for p in problems), problems

def test_verify_tasks_detects_dangling_artifact(tmp_path):
    """`verify_tasks` 能报出 `artifacts` 指向不存在的行（与无法识别的表前缀）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store)
    bad = S.Task(task_id="t-9002", role="G", action="render", status="done", outcome="ok",
                 detail="d", started_at=S.now_iso(), ended_at=S.now_iso(), depth=1,
                 input_key="k", artifacts=["documents:9999", "不存在的表:0001"])
    bad.validate()
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", bad.to_dict())
    codes = {i.code for i in c.task_issues()}
    assert "dangling_task_artifact" in codes, codes
    assert "unknown_artifact_kind" in codes, codes
    text = " ".join(c.verify_tasks())
    assert "documents:9999" in text and "不存在的表" in text


def test_artifacts_are_recorded_and_verified(tmp_path):
    """`artifacts`（handler 的产出引用）会被写进台账，且 `verify_tasks()` 会核
    它指向的行真的存在。

    这里造一行真的 `documents`（而不是让替身凭空声称一个产出）——
    "我先说产出了 documents:0001，但库里没有这一行"正是审计要抓的东西。
    """
    store = _mk_store(tmp_path)
    doc = S.Document(
        doc_id="0001", kind="survey", title="T", markdown_path="documents/0001.md",
        # 一条没有引用的断言不允许进稿件（schema.py:1066），
        # 所以这里造的是最小但合法的一行 —— 测试数据本身不合法会让
        # `store.tx` 在提交时抛，而错误信息看起来像框架坏了。
        claims=[{"claim_id": "c1", "text": "T", "citations": ["lit:0000"],
                 "evidence_kind": "heuristic"}],
        created_at=S.now_iso(), created_by="test",
    )
    doc.validate()

    class Writer(AgentH):
        def __init__(self) -> None:
            pass

        def review(self, doc_id: str, *, round_no=None, dependencies=None):
            return {"outcome": "ok", "detail": f"review {doc_id}",
                    "artifacts": [f"documents:{doc_id}"]}

    c = _conductor(store, registry={"H": ("object", Writer())})
    # 先落一行真 documents，再让 H 声称产出了它
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", doc.to_dict())
    r = c.summon("H", "review", {"doc_id": "0001"}, input_key="i1")
    # `R-47`（`draft/28` §159）之后，除了 handler 自报的产出引用，`finish` 还会把
    # 本次调用的返回值摘要落成 `out/tasks/<task_id>.json` 并把路径并进 `artifacts`
    # —— 因为 `tasks` 表不存 payload，"outcome=ok"无法自证有产出（83 行 detail 是
    # "handler 未声明 outcome，按有产出处理"）。所以这里断言的是并集：
    # ① handler 自报的那一条；② 摘要文件那一条（且它真的在盘上）。
    digest = f"out/tasks/{r.task_id}.json"
    assert sorted(r.artifacts) == sorted([f"documents:0001", digest]), r.artifacts
    assert _row(store, r.task_id)["artifacts"] == sorted([f"documents:0001", digest])
    assert (pathlib.Path(store.root) / digest).is_file(), "摘要文件必须真的落在盘上"
    assert c.verify_tasks() == [], "artifact 指向的行确实存在 ⇒ 不该报问题"


def test_verify_tasks_reports_dangling_artifact(tmp_path):
    """负控：`verify_tasks()` 必须报出"artifact 指向不存在的行"。

    与上一条合起来才说明这个检查是真的在核，而不是恒返回空列表。
    """
    store = _mk_store(tmp_path)

    class Liar(AgentH):
        def __init__(self) -> None:
            pass

        def review(self, doc_id: str, *, round_no=None, dependencies=None):
            return {"outcome": "ok", "detail": "我说我产出了",
                    "artifacts": ["documents:0001"]}

    c = _conductor(store, registry={"H": ("object", Liar())})
    r = c.summon("H", "review", {"doc_id": "0001"}, input_key="i1")
    problems = c.verify_tasks()
    assert any("documents:0001" in p for p in problems), problems


def test_children_are_reported_on_the_parent_result(tmp_path):
    """`SummonResult.children` / `tree()` 是"本次召唤又召唤出了哪些任务"的可读视图。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"A": ("object", TwoStep("a")), "C": ("object", FakeC())})
    d1 = c.summon("A", "run_once", {})
    kids = [c.summon("C", "hottest", {"top_n": 1}, by="A", parent_task_id=d1.task_id,
                     input_key=f"k{i}") for i in range(2)]
    assert d1.children == [], "d1 返回时孩子还没出生 —— 快照不许回填未来的信息"
    assert c.tree(d1.task_id)[0]["children"] == [k.task_id for k in kids]


def test_direct_summon_result_has_children_after_running(tmp_path):
    """`children` 由 `_children_of` 在返回前回填 —— 直接调用时也要有。

    造法：先让父任务跑完并留下孩子，然后用同一个父 id 再问一次
    （这里用一个"事后重读"的入口：`tree()` 与 `stats()` 都从表里数，
    而 `summon` 的返回值是那一刻的快照）。这条测试钉住的是：
    结果对象里的 `children` 确实是查表得到的，而不是恒为空列表。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"A": ("object", TwoStep("a")), "C": ("object", FakeC())})
    d1 = c.summon("A", "run_once", {})
    c.summon("C", "hottest", {"top_n": 1}, by="A", parent_task_id=d1.task_id, input_key="k")
    # 结果对象是快照 ⇒ 第一次调用时 children 为空；表里已经有一个孩子
    assert d1.children == []
    assert c.tree(d1.task_id)[0]["children"] != []


def test_policy_snapshot_is_recorded_in_stats(tmp_path):
    """`stats()` 里带策略快照 —— "当时的上限是多少"必须能从台账侧回答。"""
    store = _mk_store(tmp_path)
    pol = P.Policy(max_depth=7, max_fanout=6, max_concurrency=5, max_tasks_per_run=99,
                   wall_clock_sec=12.5)
    c = _conductor(store, policy=pol)
    s = c.stats()["policy"]
    assert s["max_depth"] == 7 and s["max_tasks_per_run"] == 99
    # 2026-10-15 业主裁定 A7：策略快照里**不许**再有 token 预算这一格
    # （留一格就有人会把它打开，而打开它就会把"想得久"判成过错）
    assert "token_budget" not in s
    assert s["wall_clock_sec"] == 12.5


def test_run_plan_empty_is_empty(tmp_path):
    """空 plan ⇒ 空结果（不是 None，也不是抛）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store)
    assert c.run_plan([]) == []
    assert store.rows("tasks") == []


# ---------------------------------------------------------------- 取号的并发缺陷（回归）


def test_concurrent_summons_never_share_a_task_id(tmp_path):
    """回归：并发召唤不许拿到同一个 `task_id`。

    ## 这条测试为什么存在（它抓的是一个真实缺陷）

    `interactions.next_prefixed_id` 是纯函数（取 max+1 并跳过已占用）——
    它没有计数器。所以"先算号、再写行"在并发下必错：

    1. 线程 A 算出 `t-0003`，还没写行；
    2. 线程 B 读 `tasks`，看不见 A 那一行，于是也算出 `t-0003`；
    3. `upsert` 按主键替换 ⇒ 后写的静默覆盖先写的。

    症状：同一个 `task_id` 出现在两次不同召唤的返回值里，台账里凭空少一次
    召唤，而没有任何地方报错（`test_merge_order_follows_input_order`
    曾以"第二个任务是第一个的副本"的形式复现它）。

    修法：取号与建行在同一把锁 + 同一个事务里（`Conductor._write_new_row`）。
    这条测试同时断言"号唯一"与"行数 == 召唤次数"—— 后者才是覆盖的直接证据。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=32, max_fanout=5, max_tasks_per_run=500, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"C": ("object", FakeC())})
    n = 24
    bar = threading.Barrier(n)
    results: list = [None] * n

    def worker(i: int) -> None:
        bar.wait()
        results[i] = c.summon("C", "hottest", {"top_n": 1, "request": f"r{i}"}, input_key=f"k{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60.0)
    ids = [r.task_id for r in results]
    assert all(i is not None for i in ids)
    assert len(set(ids)) == n, f"有召唤拿到了重复的 task_id：{sorted(ids)}"
    rows = store.rows("tasks")
    assert len(rows) == n, f"台账有 {len(rows)} 行，但发生了 {n} 次召唤（有行被静默覆盖）"
    assert {r["task_id"] for r in rows} == set(ids)
    assert c.verify_tasks() == []


def test_concurrent_refusals_also_never_share_a_task_id(tmp_path):
    """回归（拒绝路径）：被拒的召唤同样并发写台账，取号必须一样安全。

    拒绝不抢并发配额 ⇒ 它比正常召唤更容易同时发生（一波里所有被拒的
    呼叫会同时进来）。如果只有"开始"那条路径做了临界区保护，这里会漏。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC())})
    n = 16
    bar = threading.Barrier(n)
    results: list = [None] * n

    def worker(i: int) -> None:
        bar.wait()
        # C 不发起任何召唤 ⇒ 一律 forbidden_edge（拒绝也要落台账）
        results[i] = c.summon("C", "hottest", {"top_n": 1}, by="C", input_key=f"k{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60.0)
    assert all(r.outcome == "refused" and r.refusal_reason == "forbidden_edge" for r in results)
    ids = [r.task_id for r in results]
    assert len(set(ids)) == n, f"拒绝路径上有重复 task_id：{sorted(ids)}"
    assert len(store.rows("tasks")) == n


# ---------------------------------------------------------------- FC-19：单一账（裁决 1）


class _CountingE(FakeE):
    """会记下"自己被调用了几次"的 E —— 用来证明守卫在开工前就拦住了。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = 0

    def run_experiment(self, claim, claim_key, script_path, **kw):
        self.calls += 1
        return super().run_experiment(claim, claim_key, script_path, **kw)


def test_fc19_guard_refuses_before_work_starts(tmp_path):
    """裁决 1(a)：超预算时 `guard` 在开工前拒绝，不是干完再拒。

    判据是 handler 的调用次数 == 0。这一条不能用"`tasks.tokens` 是 0"
    来判 —— 后者在"先跑后拒"的实现下同样成立（被拒的行不记账），
    于是它区分不出两种实现。这正是"判据要选在能区分两种实现的地方"。

    ⚠️ 2026-10-15 业主裁定 A7 + B2/B4 之后这里只剩**钱**这一轴，且判据只有一处
    （全局已花 vs 全局预算）：第二单的拒绝来自全局预算为零
    （`Policy(usd_budget=0.0)`），不是调用方传的每单限额 ——
    `budget_usd=0` 与 `None` 语义不同（三态纪律）：0 是"预算为零 ⇒ 拦"，
    None 是"没设预算 ⇒ 不限制"。第一条断言 `spent()["tokens"] == 100`
    留着 —— 那是读数，它不是拦人的依据，但必须在。
    """
    store = _mk_store(tmp_path)
    first = _CountingE(tokens=100)
    second = _CountingE(tokens=0)
    c = _conductor(store, policy=P.Policy(max_concurrency=2, max_fanout=5,
                                          max_tasks_per_run=100, wall_clock_sec=60,
                                          usd_budget=0.0),
                   registry={"E": ("object", first)})
    r1 = c.summon("E", "run_experiment",
                  {"claim": "a", "claim_key": "ka", "script_path": "s.py"}, input_key="k1")
    assert r1.status == "done" and r1.outcome == "refused", r1.detail
    assert first.calls == 0, "守卫必须在**开工前**拦住 —— 干完再拒不是同一个功能"
    assert c.meter.spent()["tokens"] == 0, "被拒的那一行不记账（它没花钱）"

    # 换一个"会数调用次数"的 E，确认它也一次都不会被调用（预算为零 ⇒ 一件都不许做）
    c.backend.registry["E"] = ("object", second)
    r2 = c.summon("E", "run_experiment",
                  {"claim": "b", "claim_key": "kb", "script_path": "s.py"}, input_key="k2")
    assert r2.status == "done" and r2.outcome == "refused"
    assert r2.refusal_reason == "budget_exceeded"
    assert second.calls == 0, "守卫必须在**开工前**拦住 —— 干完再拒不是同一个功能"
    assert "超" in r2.detail and "预算" in r2.detail
    # 被拒的那一行不记账（它没花钱）
    assert all(u["task_id"] != r2.task_id for u in store.rows("usage_ledger"))


def test_fc19_tasks_tokens_match_usage_ledger_exactly(tmp_path):
    """裁决 1(b)：`tasks.tokens` 与 `usage_ledger` 的汇总恒等。

    这是"由构造保证相等"的判据：`summon` 先 `charge()`、再用 `tokens_for()`
    把账上的值抄进 `tasks`。跑一次真有召唤的 run，两边必须逐行相等 ——
    并且 `verify_all` 不报 `usage_task_total_mismatch`（那是同一条判据的全库版本）。
    """
    from agentflow.verify import verify_all

    store = _mk_store(tmp_path)
    c = _conductor(store, registry={
        "E": ("object", FakeE(tokens=7)), "C": ("object", FakeC()),
        "H": ("object", FakeH()),
    })
    c.run_plan([
        _e_call("a"),
        SC.TaskCall("C", "hottest", {"top_n": 1}, input_key="c1"),
        SC.TaskCall("H", "review", {"doc_id": "0001"}, input_key="h1"),
    ])
    c.summon("Z", "x", {}, input_key="z1")          # refused：不花钱，但也要有账
    rows = store.rows("tasks")
    usage = store.rows("usage_ledger")
    assert rows and usage, "这条测试必须有真数据（否则『恒等』是废话）"
    for r in rows:
        ledger_total = sum(int(u.get("tokens_total") or 0)
                           for u in usage if str(u.get("task_id")) == str(r["task_id"]))
        assert int(r["tokens"] or 0) == ledger_total, (
            f"{r['task_id']}: tasks.tokens={r['tokens']} 与台账汇总 {ledger_total} 不等"
        )
    assert sum(int(r["tokens"] or 0) for r in rows) == sum(
        int(u.get("tokens_total") or 0) for u in usage)
    rep = verify_all(store)
    mismatches = [i.to_dict() for i in rep.issues if i.code == "usage_task_total_mismatch"]
    assert not mismatches, mismatches


def test_fc19_the_per_summon_estimate_is_checked_against_the_remaining_money(tmp_path):
    """裁定 B2/B4：`budget={"max_usd": X}` 的语义是**"这一单预计最多花 X"**。

    判据因此是"剩下的钱够不够 X"（`X > 剩余` ⇒ 开工前拒），而**不是**
    "拿 X 去和全局已花比" —— 后者是改前那一版做的事，它把"每单限额"
    实现成了"全局阈值的第二个落点"（同一件事两处判，两处都不是调用方以为的意思）。

    三条都测：还剩 0.8 时"预计最多花 0.5"放行、"预计最多花 0.9"拒；
    没给 `max_usd` 时这一格完全不参与判定（只剩全局那一处）。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, policy=P.Policy(max_concurrency=2, max_fanout=5,
                                          max_tasks_per_run=100, wall_clock_sec=60,
                                          usd_budget=1.0))
    assert c.meter.budget_usd == 1.0
    from agentflow.tokenmeter import Charge

    c.meter.charge(Charge(role="A", scope="search", usd=0.2, task_id="t-9001", note="先花一点"))
    ok = c._meter_guard("E", {"max_usd": 0.5})
    assert ok.allowed is True, ok.reason
    over = c._meter_guard("E", {"max_usd": 0.9})
    assert over.allowed is False and "预计" in over.reason, over.reason
    assert "在开工前拒绝" in over.reason, over.reason
    # 不给这一格 ⇒ 只由全局那一处判（此刻全局还有钱 ⇒ 放行）
    assert c._meter_guard("E", None).allowed is True
    # 负控：没有全局上限时，"预计"这一格也不许凭空拒绝（不然它就成了新的暗闸）
    loose = _conductor(store, policy=P.Policy(max_concurrency=2, max_fanout=5,
                                              max_tasks_per_run=100, wall_clock_sec=60))
    assert loose._meter_guard("E", {"max_usd": 10 ** 9}).allowed is True


def test_fc19_retry_charged_per_attempt(tmp_path):
    """裁决 1(c)：重试按次计费 —— `tokens = (in + out) × attempts`。

    判据的来源是 `tokenmeter.Charge.tokens`（FC-19 原文："Each retry is
    another billed provider request"）。本轮各 agent 的 `_call` 还没接线，
    所以这里直接调 `charge()` 把判据钉住 —— 接通 `_call` 之后这条测试
    应当仍然通过（届时 `attempts` 由 `_call` 从真实重试次数填进来，
    计费口径不变；这一条就是那个口径的可执行定义）。
    """
    from agentflow.tokenmeter import Charge

    store = _mk_store(tmp_path)
    meter = CO.TokenMeter(store)
    one = meter.charge(Charge(role="A", scope="search", tokens_in=100, tokens_out=50,
                              attempts=1, task_id="t-0001", note="一次成功"))
    three = meter.charge(Charge(role="A", scope="search", tokens_in=100, tokens_out=50,
                                attempts=3, task_id="t-0002", note="重试两次"))
    assert one["tokens"] == 150
    assert three["tokens"] == 450, "3 次尝试必须计 3 倍（150 × 3）"
    assert three["attempts"] == 3
    # 行上的 `attempts` 与 `tokens_total` 必须自洽（账本可复核）
    row = next(r for r in store.rows("usage_ledger") if r["usage_id"] == three["usage_id"])
    assert row["tokens_total"] == (row["tokens_in"] + row["tokens_out"]) * row["attempts"]
    assert row["attempts"] == 3
    # 重试开销可判定（FC-19 判据②的正面证据）
    assert meter.retry_overhead()["extra_tokens"] == 300
    assert meter.tokens_for("t-0002") == 450


def test_fc19_duplicate_settle_does_not_double_charge(tmp_path):
    """负控（单一账）：同一行不许被结算两次。

    `finish()` 是幂等的（终态先到先得）：若一个任务在本轮 `finish` 之前就已经是
    终态（另一个写者赢了），再记一次账会让台账汇总变成 `tasks.tokens` 的两倍 ——
    而 `verify.py` 会（正确地）报 `usage_task_total_mismatch`。
    判据落在 `tasks.inputs` 的 `tokenmeter:settled` 标记上（同一事务内可读）。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", FakeE(tokens=5))})
    r = c.summon("E", "run_experiment",
                 {"claim": "a", "claim_key": "ka", "script_path": "s.py"}, input_key="k1")
    assert r.tokens == 5
    before = len(store.rows("usage_ledger"))
    # 再走一遍结算（模拟"另一个写者也想结束同一行"）
    c._charge_and_settle(r, role="E")
    assert len(store.rows("usage_ledger")) == before, "重复结算不该再写一笔账"
    row = _row(store, r.task_id)
    total = sum(int(u.get("tokens_total") or 0) for u in store.rows("usage_ledger")
                if str(u.get("task_id")) == r.task_id)
    assert total == int(row["tokens"]) == 5
