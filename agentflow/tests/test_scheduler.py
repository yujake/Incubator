"""调度测试：波浪、真并发、确定性合并顺序、四类上限。

## 时间断言的阈值与理由（报告要求的"说明阈值与理由"）

所有"真并发"的判据都用两个数一起说：

- `T_serial = n × sleep`：串行执行会花多少（下界，只多不少 ——
  串行还要加上每次落台账的开销）。
- 阈值取 `T_serial × 0.85`：留 15% 余量给"机器慢、CI 抖动"。

为什么不用 `0.5` 这种"看起来更安全"的阈值：3 个任务里只要有两个
真的同时跑，总额就会掉到 `2 × sleep`（= `T_serial × 0.667`）。
取 0.85 意味着"三个都并发"才过 —— 这正是要判的东西
（"写集不相交的 calls 必须真的同时跑"）。余量 15% 对应
`0.3s × 3 = 0.9s` 上的 `0.135s`，而实测单次调用开销约 20~60ms
（两次 `store.tx` + fsync），所以余量足够。

实测参考（本机，3 个各睡 0.3s 的不相交任务）：0.44s（= `T_serial × 0.49`）。
反方向（2 个写集相交、各睡 0.3s）：0.66s ≥ `T_serial × 0.85 = 0.51s`，
即相交的一对确实没有并发。

除了时间还有一条结构性判据：运行窗口 `[start, end)` 是否重叠
（`scheduler.ConcurrencyProbe.overlapped`）。时间会因机器负载失真，
窗口重叠不会 —— 所以"真并发"以窗口为准，时间作为粗筛（防"窗口记错了但其实是串行"）。

## 假角色为什么继承真实类

本文件里的 `FakeC/FakeH/FakeE` 都继承 `AgentC/AgentH/AgentE` 并只覆写
`__init__`（不建工具面、不连 store）与要用的那个方法。
为什么不用 `type("Y", (), {...})` 这种随手捏的替身：能力表的 `params` schema
会拒绝未声明的参数，而"替身方法签名与真实方法差一个参数"是最容易被忽略的
漂移（真实类上有 `**kw` 会吞掉它，于是测试过得去、生产里参数没了）。
继承真实类让"替身必须提供真实方法名"由 Python 自己保证。
"""

from __future__ import annotations

import threading
import time

import pytest

from agentflow import capabilities as C
from agentflow import conductor as CO
from agentflow import policy as P
from agentflow import scheduler as SC
from agentflow.agent_c import AgentC
from agentflow.agent_e import AgentE
from agentflow.agent_h import AgentH
from agentflow.cancellation import CancelToken
from agentflow.store import Store


# ---------------------------------------------------------------- 测试用的假角色


class _Recorder:
    """记录进入/离开，用来独立于 conductor 的探针再算一次峰值并发。

    为什么要有第二份观测：`scheduler.ConcurrencyProbe` 是产品代码的一部分，
    用它自己验证它自己的正确性是循环论证。两个来源的数字一致，
    才说明"并发确实是那么回事"。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.entered: list[str] = []

    def enter(self, tag: str) -> None:
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
            self.entered.append(tag)

    def leave(self, tag: str) -> None:
        with self._lock:
            self.current -= 1


class FakeC(AgentC):
    """C 的替身：只读，写集 `{analysis_reports}`。"""

    def __init__(self, recorder: _Recorder, sleep: float = 0.0) -> None:  # noqa: D107
        self.r = recorder
        self.sleep = sleep

    def hottest(self, top_n: int = 5, request: str = ""):
        self.r.enter(request or "hottest")
        try:
            if self.sleep:
                time.sleep(self.sleep)
            return {"outcome": "ok", "detail": request or "hottest", "checked": True}
        finally:
            self.r.leave(request or "hottest")

    def cold(self, top_n: int = 5, request: str = ""):
        self.r.enter(request or "cold")
        try:
            if self.sleep:
                time.sleep(self.sleep)
            return {"outcome": "ok", "detail": request or "cold", "checked": True}
        finally:
            self.r.leave(request or "cold")


class FakeH(AgentH):
    """H 的替身：只读工具箱（写集 `{review_findings, documents}`），与 C 不相交。"""

    def __init__(self, recorder: _Recorder, sleep: float = 0.0) -> None:  # noqa: D107
        self.r = recorder
        self.sleep = sleep

    def list_findings(self, **filters):
        tag = str(filters.get("doc_id") or "list_findings")
        self.r.enter(tag)
        try:
            if self.sleep:
                time.sleep(self.sleep)
            return {"outcome": "ok", "detail": tag, "checked": True}
        finally:
            self.r.leave(tag)

    def review(self, doc_id: str, *, round_no=None, dependencies=None):
        """不转发父类的 `_writer`（那要一个真注册表）：直接给出与 production
        同形的结果 —— 替身要可独立构造，否则它会静默依赖未被初始化的属性。"""
        self.r.enter(f"review:{doc_id}")
        try:
            return {"outcome": "ok", "detail": f"review {doc_id}", "checked": True,
                    "artifacts": ["documents:0001"]}
        finally:
            self.r.leave(f"review:{doc_id}")


class FakeE(AgentE):
    """E 的替身：写 `experiments`（与 C/H 都不相交）。"""

    def __init__(self, recorder: _Recorder | None = None, sleep: float = 0.0) -> None:  # noqa: D107
        self.r = recorder
        self.sleep = sleep

    def run_experiment(self, claim, claim_key, script_path, *, sleep=None, **kw):
        if self.r is not None:
            self.r.enter(claim)
        try:
            time.sleep(float(self.sleep if sleep is None else sleep))
            return {"outcome": "ok", "detail": f"{claim} 跑完", "checked": True,
                    "payload": {"claim": claim}}
        finally:
            if self.r is not None:
                self.r.leave(claim)


class FakeG(AgentE):
    """G 的替身：写 `documents`（用于 H→G 的扇出链）。

    它继承 `AgentE` 只是为了让 `__init__` 不碰真实依赖；它假装成 G，
    而 `LocalBackend` 按角色名取实例 —— 能力表的自检只核真实类，
    所以替身只需提供被调用的那个同名方法（鸭子类型）。
    """

    def __init__(self, recorder: _Recorder | None = None, sleep: float = 0.0) -> None:  # noqa: D107
        self.r = recorder
        self.sleep = sleep

    def revise(self, doc_id, **kw):
        if self.r is not None:
            self.r.enter(f"revise:{doc_id}")
        try:
            if self.sleep:
                time.sleep(self.sleep)
            return {"outcome": "ok", "detail": f"revised {doc_id}"}
        finally:
            if self.r is not None:
                self.r.leave(f"revise:{doc_id}")


class TwoStep(AgentE):
    """M → A → B 链的替身：提供被用到的动作名，签名与真实类一致。

    为什么不用 `type("Y", (), {...})` 随手捏的替身：能力表的 `params` schema
    会拒绝未声明的参数，而"替身方法签名与真实方法差一个参数"是最容易被忽略的
    漂移（真实类上的 `**kw` 会吞掉它，于是测试过得去、生产里参数没了）。
    """

    def __init__(self) -> None:  # 不建工具面：这条链测的是深度，不是抽取质量
        pass

    def run_once(self):  # type: ignore[override]
        return {"outcome": "ok", "detail": "step"}

    def probe_c(self, qid, qrow=None):
        return {"outcome": "ok", "detail": f"probe_c({qid})"}

    def status(self, plan_id):
        return {"outcome": "ok", "detail": f"status({plan_id})"}


class Boom:
    """一个固定的失败替身（E 的名字，写集与真实 E 同）。"""

    def run_experiment(self, claim, claim_key, script_path, **kw):
        raise RuntimeError("实验炸了")


class Spendy:
    """花掉固定 token 的替身（用来测预算）。"""

    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def run_experiment(self, claim, claim_key, script_path, **kw):
        return {"outcome": "ok", "detail": "花钱", "tokens": self.tokens}


class TokenAware:
    """会检查取消的替身 —— 协作式取消的唯一正确形态。"""

    def __init__(self, token: CancelToken, sleep: float) -> None:
        self.token = token
        self.sleep = sleep
        self.started = threading.Event()

    def run_experiment(self, claim, claim_key, script_path, **kw):
        self.started.set()
        deadline = time.monotonic() + self.sleep
        while time.monotonic() < deadline:
            self.token.raise_if_cancelled()
            time.sleep(0.01)
        self.token.raise_if_cancelled()
        return {"outcome": "ok", "detail": "跑完了"}


# ---------------------------------------------------------------- fixtures


def _mk_store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _conductor(store, *, policy=None, registry=None, token=None,
               fanout_wait_sec: float = 0.0) -> CO.Conductor:
    # `fanout_wait_sec=0`：这些用例要的是"触顶就拒"的即时读数。等（所有者 2026-10-08
    # 的"只可等待"）由 `tools/conductor_tools.conductor_for` 在真跑批那一处显式打开，
    # 它的判据在 `tests/test_fanout_admission.py`。
    return CO.Conductor(
        store,
        policy=policy or P.Policy(max_concurrency=4, max_fanout=5,
                                  max_tasks_per_run=100, wall_clock_sec=60),
        registry=registry or {},
        token=token,
        fanout_wait_sec=fanout_wait_sec,
    )


def _e_task(claim="c1", *, sleep=0.3) -> SC.TaskCall:
    return SC.TaskCall("E", "run_experiment",
                       {"claim": claim, "claim_key": f"k-{claim}",
                        "script_path": "s.py", "sleep": sleep})


# ---------------------------------------------------------------- 真并发（§4 的耗时判据）


def test_disjoint_calls_really_run_concurrently(tmp_path):
    """真并发正控：3 个写集不相交的 call，各睡 0.3s。

    判据：总耗时 < `T_serial × 0.85`（= 0.765s），且两个独立来源的
    峰值并发都等于 3。串行会是 0.9s+（还要加落台账的开销），
    所以这条断言能真的区分两者。
    """
    sleep = 0.3
    rec = _Recorder()
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "C": ("object", FakeC(rec, sleep=sleep)),
        "H": ("object", FakeH(rec, sleep=sleep)),
        "E": ("object", FakeE(rec, sleep=sleep)),
    })
    plan = [
        _e_task("e1", sleep=sleep),
        SC.TaskCall("C", "hottest", {"top_n": 2, "request": "c-tag"}),
        SC.TaskCall("H", "list_findings", {"doc_id": "h-tag"}),
    ]
    waves = P.waves_of(plan, limit=pol.max_concurrency)
    assert len(waves) == 1, f"三个不相交的 call 必须在同一波（实际 {waves}）"

    t0 = time.monotonic()
    res = c.run_plan(plan)
    elapsed = time.monotonic() - t0
    t_serial = sleep * 3
    assert elapsed < t_serial * 0.85, (
        f"3 个不相交的 call 耗时 {elapsed:.3f}s，接近串行的 {t_serial:.3f}s ⇒ 没有真的并发"
    )
    assert [r.outcome for r in res] == ["ok", "ok", "ok"]
    assert c.peak_running == 3, f"conductor 侧的峰值并发应为 3，实际 {c.peak_running}"
    assert rec.peak == 3, f"测试侧独立观测的峰值并发应为 3，实际 {rec.peak}"


def test_intersecting_calls_do_not_overlap(tmp_path):
    """负控（真并发）：2 个写集相交的 call（都写 experiments）必须串行。

    判据：总耗时 ≥ `T_serial × 0.85`（= 0.51s）。如果调度退化成
    "什么都并发"，这条会失败 —— 而"什么都并发"是本项目最危险的缺陷形态
    （数据被改坏且不报错）。
    """
    sleep = 0.3
    rec = _Recorder()
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(rec, sleep=sleep))})
    plan = [_e_task("e1", sleep=sleep), _e_task("e2", sleep=sleep)]
    waves = P.waves_of(plan, limit=pol.max_concurrency)
    assert len(waves) == 2, f"两个都写 experiments 的 call 必须分波（实际 {waves}）"

    t0 = time.monotonic()
    res = c.run_plan(plan)
    elapsed = time.monotonic() - t0
    assert elapsed >= sleep * 2 * 0.85, (
        f"2 个相交的 call 只花了 {elapsed:.3f}s ⇒ 它们被错误地并发了"
    )
    assert [r.outcome for r in res] == ["ok", "ok"]


def test_same_role_two_instances_really_run_concurrently(tmp_path):
    """实例轴正控（2026-09-30）：同一角色的两个不同实例必须能同波并发。

    为什么需要这条判据：分波此前只看"角色级写集"，而 B 的两个调用必然都写
    `literature` ⇒ 3 个 B 被排成 3 波串行（实测 `[[0],[1],[2]]`，峰值真并发 1）。
    后果不是"慢"，是"再多 B 也没用" —— 而用户要的正是"并发几个 B 一起读一批文献"。
    数据面本来就支持（B 的写入按行领取 + 租约），卡住的是编排面把角色当成了实例键。

    判据：两个 `instance` 不同的 E ⇒ 同一波、真并发（耗时 < 串行的 0.85 倍、
    峰值 = 2）；同时断言台账里两条任务各自独立。
    """
    sleep = 0.4
    rec = _Recorder()
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(rec, sleep=sleep))})
    plan = [SC.TaskCall("E", "run_experiment",
                        {"claim": f"c{i}", "claim_key": f"k{i}", "script_path": "s.py"},
                        instance=str(i))
            for i in (1, 2)]
    waves = P.waves_of(plan, limit=pol.max_concurrency)
    assert len(waves) == 1, f"同角色不同实例必须能同波（实际 {waves}）"

    t0 = time.monotonic()
    res = c.run_plan(plan)
    elapsed = time.monotonic() - t0
    assert [r.outcome for r in res] == ["ok", "ok"]
    assert elapsed < sleep * 2 * 0.85, f"两个不同实例花了 {elapsed:.3f}s ⇒ 没有真的并发"
    assert c.peak_running == 2, f"峰值并发 {c.peak_running} ≠ 2"
    assert len({r.task_id for r in res}) == 2, "两个实例必须各自一条任务行"


def test_same_role_without_instance_is_still_serialized(tmp_path):
    """实例轴负控：不给实例的两个同角色调用，默认行为一个字不许变松。

    这条是上一轮"同角色串行"判据的守门人：如果实例轴被写成"默认打开并发"，
    那么既有的 `test_intersecting_calls_do_not_overlap` 会静默失效，
    而"数据被改坏且不报错"正是本项目最危险的形态。
    """
    sleep = 0.3
    rec = _Recorder()
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(rec, sleep=sleep))})
    plan = [_e_task("e1", sleep=sleep), _e_task("e2", sleep=sleep)]
    assert len(P.waves_of(plan, limit=pol.max_concurrency)) == 2
    t0 = time.monotonic()
    c.run_plan(plan)
    assert time.monotonic() - t0 >= sleep * 2 * 0.85
    # 同标签（两边都叫 "s1"）同样算冲突 —— 只有"两边都给了且不同"才豁免。
    same = [SC.TaskCall("E", "run_experiment",
                        {"claim": "c", "claim_key": "k", "script_path": "s.py"}, instance="s1"),
            SC.TaskCall("E", "run_experiment",
                        {"claim": "c", "claim_key": "k", "script_path": "s.py"}, instance="s1")]
    assert len(P.waves_of(same, limit=pol.max_concurrency)) == 2


def test_instance_axis_only_relaxes_the_same_role(tmp_path):
    """实例轴负控 2：不同角色的写集相交仍然必须分波（实例轴不许顺手放宽跨角色）。

    A 写 `literature`、B 也写 `literature`：给它们各自的实例标签也没用 ——
    跨角色的冲突判据回答的是"两张表会不会被两个角色同时改"。
    """
    st = _mk_store(tmp_path)
    plan = [SC.TaskCall("A", "run", {}, instance="1"),
            SC.TaskCall("B", "run_once", {}, instance="1")]
    assert len(P.waves_of(plan, limit=4)) == 2, "A 与 B 都写 literature ⇒ 必须分波"
    assert st is not None


def test_concurrency_never_exceeds_policy_limit(tmp_path):
    """I-5：峰值同时运行的任务数 ≤ max_concurrency。

    5 个互不相交的只读 call（C 与 H 交替），上限压到 2：
    断言峰值 ≤ 2（不超）且 == 2（上限被用满 ⇒ 真的在并发，不是退化成串行）。
    """
    rec = _Recorder()
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "C": ("object", FakeC(rec, sleep=0.2)),
        "H": ("object", FakeH(rec, sleep=0.2)),
    })
    plan = [SC.TaskCall("C", "hottest", {"top_n": 2, "request": f"C{i}"}) for i in range(3)]
    plan += [SC.TaskCall("H", "list_findings", {"doc_id": f"H{i}"}) for i in range(2)]
    res = c.run_plan(plan)
    assert len(res) == 5 and all(r.outcome == "ok" for r in res)
    assert c.peak_running <= 2, f"峰值并发 {c.peak_running} 超过 max_concurrency=2"
    assert c.peak_running == 2, "上限没被用满说明并发退化成了串行"
    assert rec.peak <= 2


def test_write_sets_inside_a_wave_never_intersect():
    """I-6：任一波浪内不存在两个任务写集相交。

    直接扫 `waves_of` 的输出 —— 这是判据本身，不依赖"跑起来看时间"。
    """
    calls = [_e_task(f"c{i}", sleep=0.0) for i in range(3)]
    calls += [
        SC.TaskCall("C", "hottest", {"top_n": 1}),
        SC.TaskCall("H", "list_findings", {}),
        SC.TaskCall("A", "run_once", {}),
        SC.TaskCall("G", "render", {"doc": {}}),
    ]
    waves = P.waves_of(calls, limit=8)
    assert sum(len(w) for w in waves) == len(calls)
    for w in waves:
        for i in w:
            for j in w:
                if i != j:
                    assert not P.estimate_write_conflict(calls[i].role, calls[j].role), (
                        f"波内 {calls[i].role} 与 {calls[j].role} 的写集相交"
                    )


def test_wave_count_is_deterministic_across_runs():
    """分波必须确定性：同一输入两次得到同一划分。

    依赖 dict 迭代顺序或线程完成顺序的划分会让"可复现"失效 ——
    而可复现是本项目对"离线实验"的全部承诺。
    """
    calls = [SC.TaskCall(r, a, {}) for r, a in
             (("E", "run_experiment"), ("C", "hottest"), ("H", "list_findings"),
              ("E", "run_experiment"), ("A", "run_once"), ("C", "cold"))]
    first = P.waves_of(calls, limit=4)
    for _ in range(20):
        assert P.waves_of(calls, limit=4) == first


# ---------------------------------------------------------------- 确定性（I-10）


def test_merge_order_follows_input_order(tmp_path):
    """I-10：同一 plan 跑两次，返回列表顺序相同，且等于输入顺序。

    两个任务的耗时差异很大（0.25 / 0.05）：按完成顺序合并会得到
    `[fast, slow]`；按输入顺序则恒为 `[slow, fast]`。
    """
    rec = _Recorder()
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "C": ("object", FakeC(rec, sleep=0.25)),
        "H": ("object", FakeH(rec, sleep=0.05)),
    })
    plan = [
        SC.TaskCall("C", "hottest", {"top_n": 1, "request": "slow"}),
        SC.TaskCall("H", "list_findings", {"doc_id": "fast"}),
    ]
    res1 = c.run_plan(plan)
    assert [r.detail for r in res1] == ["slow", "fast"], "fast 先结束，但它必须排在第二"
    # 同一份 plan 再跑一次：顺序必须一模一样（任务 id 会变，但顺序不变）
    res2 = c.run_plan([
        SC.TaskCall("C", "hottest", {"top_n": 1, "request": "slow"}),
        SC.TaskCall("H", "list_findings", {"doc_id": "fast"}),
    ])
    assert [r.detail for r in res2] == ["slow", "fast"]
    assert [r.role for r in res1] == [r.role for r in res2] == ["C", "H"]
    # 反复跑也必须稳定（并发度不改变结果顺序）
    for _ in range(3):
        res = c.run_plan([
            SC.TaskCall("C", "hottest", {"top_n": 1, "request": "slow"}),
            SC.TaskCall("H", "list_findings", {"doc_id": "fast"}),
        ])
        assert [r.detail for r in res] == ["slow", "fast"]


def test_result_list_length_always_equals_plan_length(tmp_path):
    """负控：即使有 call 失败/被拒，返回列表也不许变短。

    变短的列表会让调用方把"第 3 个失败了"静默读成"只有 2 个任务"。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC(_Recorder())),
                                    "E": ("object", Boom())})
    plan = [
        SC.TaskCall("C", "hottest", {"top_n": 1}),
        SC.TaskCall("Z", "nope", {}),             # unknown_role ⇒ refused
        SC.TaskCall("C", "no_such_action", {}),   # unknown_action ⇒ refused
    ]
    res = c.run_plan(plan)
    assert len(res) == 3
    assert res[0].status == "done" and res[0].outcome == "ok"
    assert res[1].outcome == "refused" and res[1].refusal_reason == "unknown_role"
    assert res[2].outcome == "refused" and res[2].refusal_reason == "unknown_action"


def test_one_failure_does_not_stop_others(tmp_path):
    """部分失败语义：一个 call 失败不中断其它 call（子任务可降级，
    整体绝不谎报成功）。"""
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"E": ("object", Boom())})
    # Boom 只提供 run_experiment；用两个不同的 claim 无法区分"成功"，
    # 所以这里混入一个只读 C 来证明"别的 call 照常跑"。
    c.backend.registry["C"] = ("object", FakeC(_Recorder()))
    res = c.run_plan([
        SC.TaskCall("C", "hottest", {"top_n": 1, "request": "c-ok"}),
        _e_task("bad", sleep=0.0),
        SC.TaskCall("C", "cold", {"top_n": 1, "request": "c-ok2"}),
    ])
    assert [r.outcome for r in res] == ["ok", "failed", "ok"]
    assert res[1].error is not None and "实验炸了" in res[1].error


# ---------------------------------------------------------------- 四类上限的负控


def test_fanout_limit_refuses_extra_children(tmp_path):
    """扇出上限：一个任务同时在飞的子代理超过 `max_fanout` ⇒ 拒（`fanout_exceeded`）。

    链用 `H → G`（`ALLOWED_EDGES["H"] == {"G"}`）—— 为什么不用 `C → H`：
    C 的边是空的，从 C 派任何子任务都会先被判 `forbidden_edge`，
    于是这条测试就测不到扇出了。

    口径（所有者 2026-10-08）：扇出 = 此刻还没返回的子代理数，不是累计派过几次。
    所以这里先把两行写成"在飞"（`status="running"` + `started_at`），第 3 件才该被拒；
    再把其中一行标成返回 ⇒ 名额立刻腾出来（正控的下半段，与 `fanout_wait_sec=0`
    的"不等"口径一致：等的那一半另有判据）。
    """
    store = _mk_store(tmp_path)
    rec = _Recorder()
    pol = P.Policy(max_concurrency=4, max_fanout=2, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "H": ("object", FakeH(rec)), "G": ("object", FakeG(rec)),
    })
    parent = c.summon("H", "review", {"doc_id": "0001"})
    assert parent.outcome == "ok"

    def _seed_in_flight(n: int) -> None:
        with store.tx("tasks", actor="test") as tx:
            for i in range(n):
                tx.upsert("tasks", {
                    "task_id": f"t-8{i:03d}", "role": "G", "action": "revise",
                    "called_by": "H", "status": "running", "parent_task_id": parent.task_id,
                    "input_key": f"s{i}", "started_at": "2026-01-01T00:00:00+00:00",
                    "ended_at": None, "outcome": None, "tokens": 0, "usd": 0.0,
                    "artifacts": [], "inputs": [],
                })

    _seed_in_flight(2)
    over = c.summon("G", "revise", {"doc_id": "0009"}, by="H",
                    parent_task_id=parent.task_id, input_key="k-over")
    assert over.outcome == "refused" and over.refusal_reason == "fanout_exceeded", over
    assert "在飞 2" in over.detail and "上限 2" in over.detail, over.detail

    # 正控：一行返回 ⇒ 名额腾出，同一件活立刻派得进去（"智能体返回后腾出空间"）
    with store.tx("tasks", actor="test") as tx:
        row = dict(next(r for r in tx.rows("tasks")
                        if r.get("parent_task_id") == parent.task_id
                        and r.get("status") == "running"))
        row.update({"status": "done", "ended_at": "2026-01-01T00:01:00+00:00",
                    "outcome": "ok", "detail": "替身：这一件跑完了"})
        tx.upsert("tasks", row)
    ok = c.summon("G", "revise", {"doc_id": "0009"}, by="H",
                  parent_task_id=parent.task_id, input_key="k-over")
    assert ok.outcome == "ok", f"返回之后名额该腾出来，拿到 {ok.outcome}/{ok.refusal_reason}"


def test_fanout_negative_control_under_limit(tmp_path):
    """负控（扇出）：不超过上限时必须放行。

    与上一条合起来才能排除"扇出检查恒为真"。
    """
    store = _mk_store(tmp_path)
    rec = _Recorder()
    pol = P.Policy(max_concurrency=4, max_fanout=3, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "H": ("object", FakeH(rec)), "G": ("object", FakeG(rec)),
    })
    parent = c.summon("H", "review", {"doc_id": "0001"})
    kids = [
        c.summon("G", "revise", {"doc_id": f"000{i}"}, by="H",
                 parent_task_id=parent.task_id, input_key=f"k{i}")
        for i in range(3)
    ]
    assert [k.outcome for k in kids] == ["ok", "ok", "ok"], "上限 3 ⇒ 三个都该过"


def test_total_tasks_budget_refuses_extra(tmp_path):
    """总量上限：`max_tasks_per_run` 用尽 ⇒ 后续一律被拒。"""
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=2, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"C": ("object", FakeC(_Recorder()))})
    outs = [c.summon("C", "hottest", {"top_n": 1}) for _ in range(3)]
    assert [o.outcome for o in outs] == ["ok", "ok", "refused"]
    assert outs[2].refusal_reason == "budget_exceeded"
    assert outs[2].detail and "max_tasks_per_run" in outs[2].detail


def test_depth_limit_refuses_deeper_chain(tmp_path):
    """深度正控：`max_depth=3` 时能跑到第 3 层，第 4 层被拒。

    链：`M → A(1) → B(2) → C(3)`，然后从 B 再派生必须仍是 3（深度不是"第几个孩子"）。
    """
    store = _mk_store(tmp_path)
    rec = _Recorder()
    pol = P.Policy(max_concurrency=4, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "A": ("object", TwoStep()), "B": ("object", TwoStep()),
        "C": ("object", FakeC(rec)),
    })
    d1 = c.summon("A", "run_once", {})
    d2 = c.summon("B", "run_once", {}, by="A", parent_task_id=d1.task_id, input_key="b1")
    d3 = c.summon("C", "hottest", {"top_n": 1, "request": "d3"}, by="B",
                  parent_task_id=d2.task_id, input_key="c1")
    d3b = c.summon("C", "cold", {"top_n": 1, "request": "d3b"}, by="B",
                   parent_task_id=d2.task_id, input_key="c2")
    assert (d1.depth, d2.depth, d3.depth, d3b.depth) == (1, 2, 3, 3)
    assert [d1.outcome, d2.outcome, d3.outcome, d3b.outcome] == ["ok"] * 4


def test_depth_limit_is_hard_at_the_boundary(tmp_path):
    """负控（深度）：把 `max_depth` 收到 2，第 3 层必须被拒
    （`refused/depth_exceeded`）。"""
    store = _mk_store(tmp_path)
    rec = _Recorder()
    pol = P.Policy(max_depth=2, max_concurrency=4, max_fanout=5,
                   max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "A": ("object", TwoStep()), "B": ("object", TwoStep()),
        "C": ("object", FakeC(rec)),
    })
    d1 = c.summon("A", "run_once", {})
    d2 = c.summon("B", "run_once", {}, by="A", parent_task_id=d1.task_id, input_key="b")
    assert d2.depth == 2 and d2.outcome == "ok"
    d3 = c.summon("C", "hottest", {"top_n": 1}, by="B", parent_task_id=d2.task_id, input_key="c")
    assert d3.status == "done" and d3.outcome == "refused"
    assert d3.refusal_reason == "depth_exceeded"
    assert d3.depth == 3


def test_cycle_detected_on_repeated_key(tmp_path):
    """循环：同一 `(role, action, input_key)` 出现在祖先链上 ⇒ `cycle_detected`。

    链：`M →D(probe_c, same-key)→ F(status)→ D(probe_c, same-key)`。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_depth=6, max_concurrency=4, max_fanout=5,
                   max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "D": ("object", TwoStep()), "F": ("object", TwoStep()),
    })
    d1 = c.summon("D", "probe_c", {"qid": "0000"}, input_key="same-key")
    f1 = c.summon("F", "status", {"plan_id": "0000"}, by="D",
                  parent_task_id=d1.task_id, input_key="f-key")
    assert (d1.outcome, f1.outcome) == ("ok", "ok")
    d2 = c.summon("D", "probe_c", {"qid": "0000"}, by="F",
                  parent_task_id=f1.task_id, input_key="same-key")
    assert d2.status == "done" and d2.outcome == "refused"
    assert d2.refusal_reason == "cycle_detected"
    assert "same-key" in d2.detail


def test_cycle_negative_control_different_key_passes(tmp_path):
    """负控（循环）：同样的 (role, action)、不同 input_key ⇒ 放行。

    否则"对第二个问题问同一个角色"会被误判成活锁 —— 而那是正常进展。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_depth=6, max_concurrency=4, max_fanout=5,
                   max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={
        "D": ("object", TwoStep()), "F": ("object", TwoStep()),
    })
    d1 = c.summon("D", "probe_c", {"qid": "0000"}, input_key="key-1")
    f1 = c.summon("F", "status", {"plan_id": "0000"}, by="D",
                  parent_task_id=d1.task_id, input_key="f")
    d2 = c.summon("D", "probe_c", {"qid": "0001"}, by="F",
                  parent_task_id=f1.task_id, input_key="key-2")
    assert d2.outcome == "ok", "不同 input_key 是进展，不是循环"
    assert d2.depth == 3


def test_budget_exhaustion_refuses_later_summons(tmp_path):
    """预算：钱用尽 ⇒ 后续 `refused/budget_exceeded`，且在跑的那个不被砍。

    ⚠️ 2026-10-15 业主裁定 A1/A2/A3/A7 + B2/B4：这里的"预算"**只剩钱**，
    而且判据只有一处（全局已花 vs 全局预算）。
    此前它走的是 `token_budget=100` + `budget={"max_tokens": 10}`。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100,
                   wall_clock_sec=60, usd_budget=1.0)
    c = _conductor(store, policy=pol, registry={"E": ("object", Spendy(100))})
    first = c.summon("E", "run_experiment",
                     {"claim": "c1", "claim_key": "k1", "script_path": "s.py"})
    assert first.outcome == "ok" and first.tokens == 100
    assert c.budget.state(pol)["spent_tokens"] == 100, "花销照记（读数）"
    # 把全局账推过上限（模拟别的角色花的钱），再派新的 ⇒ 拒
    from agentflow.tokenmeter import Charge

    c.meter.charge(Charge(role="A", scope="search", usd=2.0, task_id="t-9999",
                          note="别的角色花的钱"))
    second = c.summon("E", "run_experiment",
                      {"claim": "c2", "claim_key": "k2", "script_path": "s.py"})
    assert second.status == "done" and second.outcome == "refused"
    assert second.refusal_reason == "budget_exceeded"
    assert first.status == "done", "在跑的那个不许被预算砍掉"


def test_budget_negative_control_no_task_is_mutated(tmp_path):
    """负控（预算）：预算耗尽不许改写已经完成的行。

    这条防的是"预算检查跑到 finish 的路径上，把一条 ok 改成 refused"
    —— 那会让台账与真实发生的事矛盾（终态先到先得，见 I-2）。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100,
                   wall_clock_sec=60, usd_budget=1.0)
    c = _conductor(store, policy=pol, registry={"E": ("object", Spendy(50))})
    r = c.summon("E", "run_experiment",
                 {"claim": "c", "claim_key": "k", "script_path": "s.py"})
    row = next(x for x in store.rows("tasks") if x["task_id"] == r.task_id)
    assert row["status"] == "done" and row["outcome"] == "ok"
    assert row["ended_at"] and row["refusal_reason"] is None
    # 推过上限之后再派一次：会被拒，且不改前面那一行
    from agentflow.tokenmeter import Charge

    c.meter.charge(Charge(role="A", scope="search", usd=2.0, task_id="t-9999",
                          note="别的角色花的钱"))
    r2 = c.summon("E", "run_experiment",
                  {"claim": "c2", "claim_key": "k2", "script_path": "s.py"})
    assert r2.outcome == "refused"
    row_again = next(x for x in store.rows("tasks") if x["task_id"] == r.task_id)
    assert row_again == row, "被拒的新召唤不许改动已完成的旧行"


# ---------------------------------------------------------------- 墙钟 + 协作式取消


def test_deadline_refuses_new_and_signals_running(tmp_path):
    """墙钟到点 ⇒ 新召唤被拒（`deadline_exceeded`）+ 在跑的收到取消信号。

    这里刻意用一个不检查 token 的 handler：它会跑完
    （协作式取消不是强杀），于是这条测试同时证明了两件事：
    (a) 共享 token 已经被置位（`c.token.cancelled is True`），
    (b) 已开始的任务不会因为到点而丢结果。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=0.25)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(None, sleep=0.45))})
    plan = [_e_task("a", sleep=0.45), _e_task("b", sleep=0.45)]
    res = c.run_plan(plan)
    assert res[0].status == "done" and res[0].outcome == "ok", "在跑的那个不许被强杀"
    assert res[1].status == "done" and res[1].outcome == "refused"
    assert res[1].refusal_reason == "deadline_exceeded"
    assert c.token.cancelled is True, "到点必须发出**共享**取消信号（覆盖在飞与待启动）"
    assert c.token.reason is not None and c.token.reason.code == "deadline"


def test_deadline_cooperative_handler_is_cancelled(tmp_path):
    """协作式取消正控：会检查 token 的 handler 收到 `CancelRequested`
    ⇒ `status="cancelled", outcome="cancelled"`。"""
    store = _mk_store(tmp_path)
    token = CancelToken()
    aware = TokenAware(token, sleep=5.0)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", aware)}, token=token)
    out: dict = {}
    th = threading.Thread(target=lambda: out.update(res=c.run_plan([_e_task("a", sleep=1.0)])))
    th.start()
    assert aware.started.wait(timeout=5.0), "handler 没起来"
    c.cancel("user", detail="人按了停止")
    th.join(timeout=15.0)
    assert not th.is_alive()
    res = out["res"][0]
    assert res.status == "cancelled" and res.outcome == "cancelled"
    assert "取消" in res.detail


def test_cancel_does_not_create_new_tasks(tmp_path):
    """取消后不产生新任务：`task_id is None`，台账行数不变。"""
    store = _mk_store(tmp_path)
    token = CancelToken()
    c = _conductor(store, registry={"C": ("object", FakeC(_Recorder()))}, token=token)
    before = len(store.rows("tasks"))
    token.cancel("user", detail="先取消")
    r = c.summon("C", "hottest", {"top_n": 1})
    assert r.status == "cancelled" and r.outcome == "cancelled"
    assert r.task_id is None, "没有 start 就没有 end；编一个 id 会让调用方去查不存在的行"
    assert len(store.rows("tasks")) == before
    assert "未启动" in r.detail


def test_cancel_negative_control_without_cancel_task_is_created(tmp_path):
    """负控：没有取消时，同样的召唤必须产生一行台账。

    否则上面那条"行数不变"可能只是因为"这个动作根本不落台账"。
    """
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"C": ("object", FakeC(_Recorder()))})
    before = len(store.rows("tasks"))
    r = c.summon("C", "hottest", {"top_n": 1})
    assert r.task_id is not None and r.outcome == "ok"
    assert len(store.rows("tasks")) == before + 1


def test_cancel_stops_the_queue_mid_plan(tmp_path):
    """取消覆盖待启动的任务（FC-20 第 1 条的直接测试）。

    一波跑完后，后续的 call 一律不启动 ⇒ 只有第一个真的留下台账行。
    逐个取消的实现会漏掉"还在队列里"的那些。
    """
    store = _mk_store(tmp_path)
    token = CancelToken()
    aware = TokenAware(token, sleep=2.0)
    pol = P.Policy(max_concurrency=1, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", aware)}, token=token)
    plan = [_e_task(f"c{i}", sleep=1.0) for i in range(3)]
    out: dict = {}
    th = threading.Thread(target=lambda: out.update(res=c.run_plan(plan)))
    th.start()
    assert aware.started.wait(timeout=5.0)
    c.cancel("user", detail="队列也停")
    th.join(timeout=20.0)
    assert not th.is_alive()
    res = out["res"]
    assert len(res) == 3
    assert res[0].status == "cancelled"
    assert res[1].task_id is None and res[2].task_id is None, "待启动的任务不许被启动"
    assert all(r.outcome == "cancelled" for r in res)
    rows = store.rows("tasks")
    assert len(rows) == 1, f"只有第一个真的 start 过；台账行数 {len(rows)}"


def test_deadline_negative_control_generous_wall_clock(tmp_path):
    """负控（墙钟）：给足时间时，同样的 plan 必须全部成功。

    没有这条，`deadline_exceeded` 可能只是因为"实现永远判到点"。
    """
    store = _mk_store(tmp_path)
    pol = P.Policy(max_concurrency=2, max_fanout=5, max_tasks_per_run=100, wall_clock_sec=60)
    c = _conductor(store, policy=pol, registry={"E": ("object", FakeE(None, sleep=0.05))})
    res = c.run_plan([_e_task("a", sleep=0.05), _e_task("b", sleep=0.05)])
    assert [r.outcome for r in res] == ["ok", "ok"]
    assert c.token.cancelled is False


# ---------------------------------------------------------------- 与 capabilities 的联动


def test_scheduler_uses_capability_write_sets():
    """调度的分波判据只来自 `capabilities.WRITE_SETS`（不是另写一份表）。

    通过改 `WRITE_SETS` 观察分波变化来证明这一点（改完立刻还原）。
    """
    calls = [SC.TaskCall("C", "hottest", {}), SC.TaskCall("H", "list_findings", {})]
    assert len(P.waves_of(calls, limit=4)) == 1
    original = C.WRITE_SETS["H"]
    C.WRITE_SETS["H"] = frozenset({"analysis_reports"})  # 人为制造相交
    try:
        assert len(P.waves_of(calls, limit=4)) == 2, "写集改了但分波没变 ⇒ 判据不是同一份"
    finally:
        C.WRITE_SETS["H"] = original
    assert len(P.waves_of(calls, limit=4)) == 1
