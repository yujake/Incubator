# -*- coding: utf-8 -*-
"""E-13 的判据（`draft/41` 调查报告-A 的 B9 / B11 / B12）。

三处都在本线的文件里（`conductor.py` / `agent_loop.py` / `scheduler.py`），
不涉及禁改区。每一条都按"改前必红"写：

| 条目 | 窗口 | 这一条钉什么 |
|---|---|---|
| B11 | "先数后写" | 同角色同秒的两个写者不许拿到同一个路径（后写覆盖先写） |
| B9 | 判据与占位之间 | 并发上限恰好等于上限（不许被超） |
| B12 | 事务体内做磁盘 I/O | 摘要文件的写不在持表锁期间（或如实登记为已决定的例外） |

为什么 B11 的负控要 pin 掉 glob：这条缺陷的本质是"数的时候还没看见另一个写者"。
真起两个线程未必能稳定撞上那个交错（真机 0 个 `agent_run_artifact` 事件 ⇒ 这条路径
从未在真机跑过），所以判据注入的是那个交错本身（把计数换成"看不见任何文件"），
而不是去改被测代码。
"""
from __future__ import annotations

import json
import pathlib
import threading

import pytest

from agentflow.agent_loop import RUNS_DIR_NAME, LlmBackend, LoopRun


def _backend(root: pathlib.Path) -> LlmBackend:
    return LlmBackend(inner=None, loops={}, session_root=root)


def _run(role: str = "M", task: str = "t") -> LoopRun:
    return LoopRun(role=role, task=task)


def test_b11_two_writers_never_share_one_artifact_path(tmp_path, monkeypatch):
    """B11 的负控：注入"数的时候看不见对方"的交错 ⇒ 旧实现两个路径相同（红）。

    改前：两次调用都算出 `n=1` ⇒ 第二个覆盖第一个 ⇒ 两个调用返回同一个路径、
    盘上只剩 1 个文件（一份产出凭空消失，而两个调用方都以为自己的在盘上）。
    改后：`O_EXCL` 让第二个写者撞名重试 ⇒ 2 个路径互不相同、盘上 2 个文件。
    """
    root = tmp_path / "ws"
    root.mkdir()
    b = _backend(root)

    real_glob = pathlib.Path.glob

    def _stale_glob(self, pattern):
        # 只对"数序号"这一处注入：让它对任何 pattern 都返回空（= 对方还没写）。
        if "runs" in str(self) or RUNS_DIR_NAME in str(self):
            return iter(())
        return real_glob(self, pattern)

    monkeypatch.setattr(pathlib.Path, "glob", _stale_glob)
    monkeypatch.setattr("agentflow.agent_loop.time.strftime", lambda fmt: "20260101-000000")

    first = b._write_run_artifact("M", _run(task="第一趟"))
    second = b._write_run_artifact("M", _run(task="第二趟"))
    monkeypatch.undo()
    assert first and second, (first, second)
    assert first != second, f"两个写者拿到了同一个路径（后写覆盖先写）：{first}"
    files = sorted(p.name for p in (root / RUNS_DIR_NAME).glob("M-*.json"))
    assert len(files) == 2, files
    # 两份内容都在（"覆盖"与"各写各的"必须分得开）
    tasks = {json.loads((root / RUNS_DIR_NAME / f).read_text(encoding="utf-8"))["task"]
             for f in files}
    assert tasks == {"第一趟", "第二趟"}, tasks


def test_b11_serial_calls_also_get_distinct_names(tmp_path, monkeypatch):
    """正控：顺序调用（正常情形）本来就该各一个名字 —— 不许因修 B11 而退化成同名。"""
    root = tmp_path / "ws"
    root.mkdir()
    b = _backend(root)
    monkeypatch.setattr("agentflow.agent_loop.time.strftime", lambda fmt: "20260101-000000")
    names = [b._write_run_artifact("A", _run(role="A", task=f"t{i}")) for i in range(3)]
    assert len(set(names)) == 3, names
    assert sorted(str(n).split("-")[-1] for n in names) == ["001.json", "002.json", "003.json"], names


# ================================================================ B9：并发上限的检查点与更新点


class _BlockingBackend:
    """一个会在 handler 里等所有线程都进来的后端（把窗口撑开成可观测的）。

    为什么要它：B9 的窗口只有几微秒（读计数 → 判 → 写行），不起眼地起线程是撞不上的。
    这里让每个"已经被放行"的调用都停在 handler 里等齐 —— 于是"到底放行了几个"
    变成一个确定性的读数（`admitted` 的峰值），而不是碰运气。
    """

    def __init__(self, n: int) -> None:
        self.barrier = threading.Barrier(n, timeout=5.0)
        self.enter = threading.Semaphore(0)
        self.peak = 0
        self._lock = threading.Lock()
        self._now = 0

    def call(self, role, action, params, *, token, instance="", task_id=""):
        with self._lock:
            self._now += 1
            self.peak = max(self.peak, self._now)
        try:
            self.barrier.wait()          # 等齐 n 个（改前：n 个全放行 ⇒ 一个都不超时）
        except threading.BrokenBarrierError:
            pass                          # 改后：被拒的那些根本没进来 ⇒ 屏障会破，正常
        with self._lock:
            self._now -= 1
        return {"outcome": "ok", "detail": "done", "checked": True}


def _conductor_with(tmp_path, backend, *, max_concurrency: int):
    from agentflow import conductor as CO
    from agentflow import policy as P
    from agentflow.store import Store

    st = Store(tmp_path / "ws")
    st.init()
    return CO.Conductor(st, policy=P.Policy(max_concurrency=max_concurrency), backend=backend)


def test_b9_concurrency_cap_holds_when_all_callers_enter_together(tmp_path, monkeypatch):
    """B9 的负控：把"读计数 → 判"这一段用屏障撑开 ⇒ 旧实现会超过上限（红）。

    注入的是那个交错本身（所有调用者都在 `P.check` 处等齐），不是去改被测代码：
    改前每个线程读到的 `running` 都是同一个数（写行还没发生）⇒ 全部放行；
    改后线程 k 读到的是"已接受 k-1 条"（预留可见）⇒ 第 `cap+1` 个被拒。
    """
    from agentflow import policy as P

    cap = 2
    n = 5
    backend = _BlockingBackend(n)
    cond = _conductor_with(tmp_path, backend, max_concurrency=cap)

    real_check = P.check
    barrier = threading.Barrier(n, timeout=5.0)

    def _check(policy, d, *, registry=None):
        try:
            barrier.wait()               # 撑开"已经读过计数、还没判"的那个窗口
        except threading.BrokenBarrierError:
            pass
        return real_check(policy, d, registry=registry)

    monkeypatch.setattr(P, "check", _check)

    out: list[Any] = [None] * n
    threads = []

    def _one(i: int) -> None:
        out[i] = cond.summon("C", "hottest", {"top_n": 5}, by="M", input_key=f"k{i}")

    for i in range(n):
        t = threading.Thread(target=_one, args=(i,))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    denied = [r for r in out if r is not None and r.refusal_reason == "concurrency_exceeded"]
    admitted = [r for r in out if r is not None and r.refusal_reason != "concurrency_exceeded"]
    assert len(denied) == n - cap, [getattr(r, "refusal_reason", None) for r in out]
    assert len(admitted) == cap, [getattr(r, "refusal_reason", None) for r in out]
    assert backend.peak <= cap, f"并发峰值 {backend.peak} 超过了上限 {cap}（B9 的窗口）"


def test_b9_a_refusal_does_not_leak_a_reservation(tmp_path, monkeypatch):
    """正控（回滚）：被策略拒的召唤必须把预留还回去 —— 否则上限会一次比一次紧。"""
    from agentflow import policy as P

    cap = 1
    cond = _conductor_with(tmp_path, _BlockingBackend(1), max_concurrency=cap)
    monkeypatch.setattr(P, "check", lambda policy, d, *, registry=None: P.Refusal(
        "concurrency_exceeded", "测试注入：一律拒", "max_concurrency"))
    for i in range(3):
        got = cond.summon("C", "hottest", {"top_n": 5}, by="M", input_key=f"k{i}")
        assert got.refusal_reason == "concurrency_exceeded", got
    # 预留没泄漏：`peak_running` 与"已接受"的计数都不该留下占位
    assert cond.peak_running <= 1, cond.stats()
    assert cond.stats()["started_total"] == 0, cond.stats()


# ================================================================ B12：`finish` 持表锁写摘要


def test_b12_the_digest_write_stays_inside_the_winner_transaction(tmp_path):
    """B12 的读数（"为什么它挪不出事务"）：输掉终态竞争的那一次不许改写摘要。

    `finish` 在 `store.tx("tasks")` 体内调 `_write_task_digest`（写 `out/tasks/<id>.json`）。主控给的思路是"摘要内容进事务前就已知 ⇒ 可以挪到事务外"，但挪出去会丢掉一件事：现在这次写是被事务内的读-判结果门住的（`if row.get("status") in TERMINAL_STATUSES: return` —— 只有抢到终态的那一次才走到写摘要那一行）。挪到事务外之后，幂等分支（后到的写者）也会写一遍，于是输家可以覆盖赢家的摘要（同一个 task_id、两份不同的 payload）。

    这一条钉的就是那个性质：对已结束的任务再调一次 `finish`（带不同 payload）⇒ 盘上那份摘要逐字不变。它同时是"已决定的例外"的依据 —— 这条 I/O 不是"与台账无关的文件 I/O"，它的内容取决于事务内的那个判定。

    顺带核实（主控要求）：`closing` 第八格 `artifact_ledger` 只数台账行（`missing` / `unreadable` / `changed` 都相对"登记过的产物"算），不扫盘上多出来的文件 ⇒ 这条例外不会在那一格里造出 `missing` / `changed` 读数。"""
    cond = _conductor_with(tmp_path, _BlockingBackend(1), max_concurrency=2)
    # 造一条还在 running 的行（走 `summon` 的话它当场就落终态了，测不到 `finish`）
    from agentflow import schema as S

    started = S.now_iso()
    tid = cond._write_new_row({
        "task_id": "", "role": "C", "action": "hottest", "called_by": "M",
        "parent_task_id": None, "depth": 1, "input_key": "k1", "status": "running",
        "outcome": None, "refusal_reason": None, "instance": "", "detail": "",
        "error": None, "started_at": started, "ended_at": None, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="b12")
    got = type("R", (), {"task_id": tid})()
    cond.finish(got.task_id, status="done", outcome="ok", detail="赢家",
                payload={"who": "winner"})
    path = pathlib.Path(cond.store.root) / "out" / "tasks" / f"{got.task_id}.json"
    assert path.is_file(), path
    before = path.read_text(encoding="utf-8")
    assert "winner" in before, before

    # 后到的那个写者：同样的 task_id、不同的 payload —— 幂等分支必须让它一个字节都不改
    again = cond.finish(got.task_id, status="done", outcome="ok", detail="输家",
                        payload={"who": "loser"})
    assert again.payload is None, "幂等分支不该声称自己产出了 payload"
    assert path.read_text(encoding="utf-8") == before, "输家改写了赢家的摘要（B12 的反面）"

    # 而 `_write_task_digest` 本身没有门禁（这正是不能把它挪到事务外的原因）：
    # 直接调它，盘上那份就被改掉了 ⇒ 谁都可以覆盖谁。
    cond._write_task_digest({"task_id": got.task_id, "role": "C", "action": "hottest"},
                            payload={"who": "anyone"}, status="done", outcome="ok",
                            detail="任何人")
    assert path.read_text(encoding="utf-8") != before, "直接调用竟然改不动 ⇒ 这一条读数失去对象"

