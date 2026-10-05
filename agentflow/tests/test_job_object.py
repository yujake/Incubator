# -*- coding: utf-8 -*-
"""进程树治理（`draft/39` §3.21 五 I13）+ E14 树杀演练。

D03 的真机读数：强制停止那条路上 `taskkill /T /F` 与 `os.kill` 在受限环境里都会被拒
（`Access denied` / `WinError 5`），而在更早的一次实测里"包装进程被杀之后 python 子进程
又跑了 12 分钟"。I13 的立场是"最后一个句柄一关，OS 收掉整棵传递树" —— 于是这一组钉四件事：

1. 作业对象可用时，`assign` + `close` 真的把子孙一起收掉（正控）；
2. 负控：不用作业对象、只杀父进程 ⇒ 孙进程还活着（那正是 D03 那个 bug 的形态）；
3. `grace_then_kill`：宽限期内自己走掉 ⇒ 不杀；宽限期到 ⇒ `TerminateJobObject`；
4. `stopctl` 的强制停止优先走作业对象（真机上不再依赖 `taskkill` 能不能成功），
   并把"通过哪条路杀的"记进结果（`via="job"`）。

平台用不了时整组 `skip`（并打印原因）—— 那不是通过，而是"这台机器上测不了"。
"""
from __future__ import annotations

import subprocess
import sys
import time
import pathlib

import pytest

from agentflow import jobobject as JB
from agentflow import stopctl

pytestmark = pytest.mark.skipif(not JB.available(),
                                reason=f"作业对象用不了：{JB.unavailable_reason()}")

#: 孙进程由它自己把 pid 写进文件（而不是靠 `wmic` 查父子关系）：
#: 新版 Windows 已经不带 `wmic`，靠它查父子关系会让夹具在好机器上失败 ——
#: 而"读不到父子关系"与"没有孙进程"是两件事（三态纪律不该在夹具里被折平）。
_GRANDCHILD = ("import pathlib, subprocess, sys, time;"
               "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
               "pathlib.Path(sys.argv[1]).write_text(str(p.pid), encoding='utf-8');"
               "time.sleep(60)")
_CHILD = "import time; time.sleep(60)"


def _spawn_tree(tmp_path: pathlib.Path):
    """起一棵两层树：child（包一层）→ grandchild。返回 `(child_proc, [孙的 pid])`。"""
    pid_file = pathlib.Path(tmp_path) / "grandchild.pid"
    child = subprocess.Popen([sys.executable, "-c", _GRANDCHILD, str(pid_file)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if pid_file.is_file() and pid_file.read_text(encoding="utf-8").strip().isdigit():
            return child, [int(pid_file.read_text(encoding="utf-8").strip())]
        time.sleep(0.2)
    return child, []


# ============================================================ E14①②

def test_e14_closing_the_job_handle_kills_the_whole_tree(tmp_path: pathlib.Path):
    """E14① 正控：把根进程放进作业 ⇒ 关句柄之后子与孙都没了（不依赖 taskkill）。"""
    job = JB.create_job("agentflow-e14")
    child, grandkids = _spawn_tree(tmp_path)
    assert grandkids, "夹具失败：没造出孙进程（那这一条就测不到树）"
    try:
        # 根 + 现有后代都要放进去（作业归属不向前追溯 —— 见下面那条边界判据）
        placed = JB.assign_tree(job, child.pid)
        assert child.pid in placed["assigned"] and grandkids[0] in placed["assigned"], placed
        assert set(grandkids) <= set(JB.assigned_pids(job).get("pids") or []), JB.assigned_pids(job)
        JB.close(job)                      # ← 唯一的终止动作
        for _ in range(30):
            if not JB._alive(child.pid) and not any(JB._alive(g) for g in grandkids):
                break
            time.sleep(0.2)
        assert not JB._alive(child.pid), f"根进程 {child.pid} 还活着"
        assert not [g for g in grandkids if JB._alive(g)], \
            f"子孙还活着：{[g for g in grandkids if JB._alive(g)]}"
    finally:
        if not child.poll():
            child.kill()


def test_e14_without_a_job_the_grandchild_survives(tmp_path: pathlib.Path):
    """E14② 负控（D03 的形态）：不用作业对象、只杀父进程 ⇒ 孙进程还活着。

    这一条比正控更重要：它证明上面那条通过不是因为"这个环境本来就杀得干净"。
    """
    child, grandkids = _spawn_tree(tmp_path)
    assert grandkids, "夹具失败：没造出孙进程"
    try:
        child.kill()
        child.wait(timeout=20)
        time.sleep(0.5)
        assert any(JB._alive(g) for g in grandkids), \
            "孙进程也死了 ⇒ 这条负控失效（它在别的机器上可能因为平台差异而失败）"
    finally:
        for g in grandkids:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(g)], capture_output=True,
                               timeout=20)
            except Exception:  # noqa: BLE001 —— 清理失败不影响判据结论
                pass


# ============================================================ E14③ 宽限与收割

def test_e14_grace_then_kill_leaves_a_self_finished_round_alone():
    """宽限期里自己走掉的 ⇒ 不杀（优雅停优先），读数里 `killed=False`。"""
    job = JB.create_job("agentflow-grace")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.6)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert JB.assign(job, child.pid) is True
        got = JB.grace_then_kill(job, grace_sec=6.0, poll_sec=0.2)
        assert got["killed"] is False, got
        assert "自己走完" in got["note"], got
    finally:
        JB.close(job)


def test_e14_grace_then_kill_terminates_the_stragglers(tmp_path: pathlib.Path):
    """宽限期到了还不走 ⇒ `TerminateJobObject` 收掉整棵树，并报出 `stragglers`。"""
    job = JB.create_job("agentflow-straggler")
    child, grandkids = _spawn_tree(tmp_path)
    try:
        assert JB.assign_tree(job, child.pid)["assigned"], "没放进作业"
        got = JB.grace_then_kill(job, grace_sec=1.0, poll_sec=0.2)
        assert got["killed"] is True, got
        assert child.pid in (got["stragglers"] or []), got
        for _ in range(30):
            if not JB._alive(child.pid) and not any(JB._alive(g) for g in grandkids):
                break
            time.sleep(0.2)
        assert not JB._alive(child.pid), "根进程还活着"
        assert not [g for g in grandkids if JB._alive(g) or g in (got.get("left") or [])], got
    finally:
        JB.close(job)


def test_reap_reports_what_is_still_assigned_and_three_states():
    """`reap()` 只报不杀；"查不成"与"没有进程"分得开（三态）。"""
    job = JB.create_job("agentflow-reap")
    child = subprocess.Popen([sys.executable, "-c", _CHILD],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert JB.assign(job, child.pid) is True
        got = JB.reap(job)
        assert got["checked"] is True and child.pid in got["pids"], got
        assert JB._alive(child.pid), "reap 不许杀进程"
    finally:
        JB.terminate(job)
        JB.close(job)
        if child.poll() is None:
            child.kill()
    closed = JB.reap(job)
    assert closed["checked"] is True and closed["pids"] == [], closed
    assert "已关闭" in closed["reason"], closed


# ============================================================ E14④ 接进 stopctl

def test_e14_stopctl_force_prefers_the_job_object(tmp_path: pathlib.Path):
    """D03 的根因修法：`stopctl` 的强制停止优先走作业对象，并把 `via` 记下来。"""
    root = tmp_path / "ws"
    root.mkdir()
    child, grandkids = _spawn_tree(tmp_path)
    assert grandkids, "夹具失败：没造出孙进程"
    try:
        stopctl.register_pid(root, "E", "round1", pid=child.pid)
        got = stopctl.kill_registered(root, prefer_job=True)
        assert got["requested"] == [child.pid], got
        assert got["killed"] >= 1, got
        assert any(r.get("via") == "job" for r in got["results"]), got["results"]
        for _ in range(30):
            if not JB._alive(child.pid) and not any(JB._alive(g) for g in grandkids):
                break
            time.sleep(0.2)
        assert not [g for g in grandkids if JB._alive(g)], \
            f"走作业对象那一路也必须收掉子孙：{[g for g in grandkids if JB._alive(g)]}"
    finally:
        if not child.poll():
            child.kill()


def test_assigning_only_the_root_does_not_pull_in_existing_descendants(tmp_path: pathlib.Path):
    """边界（E14 实测，2026-10-05）：作业归属不向前追溯。

    把一个已经在跑的进程 assign 进作业，不会把它此前已经生出来的子进程带进来 ——
    于是"停一棵已经在跑的树"必须用 `assign_tree`（根 + 现有后代逐个放进去），
    而"起进程时就 assign"（新生的子进程自动继承）才只需要放根。
    这一条钉的就是这个区别：只放根 ⇒ 关句柄后孙进程还活着。
    """
    job = JB.create_job("agentflow-root-only")
    child, grandkids = _spawn_tree(tmp_path)
    try:
        assert JB.assign(job, child.pid) is True          # 只放根
        JB.close(job)
        for _ in range(20):
            if not JB._alive(child.pid):
                break
            time.sleep(0.2)
        assert not JB._alive(child.pid), "根进程应当被收掉"
        alive_grandkids = [g for g in grandkids if JB._alive(g)]
        assert alive_grandkids, (
            "孙进程也死了 ⇒ 这条边界判据失效（说明这个平台上作业归属会向前追溯，"
            "那 `assign_tree` 的存在理由就要重新论证）")
    finally:
        for g in grandkids:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(g)], capture_output=True, timeout=20)
            except Exception:  # noqa: BLE001 —— 清理失败不影响结论
                pass
        if not child.poll():
            child.kill()
