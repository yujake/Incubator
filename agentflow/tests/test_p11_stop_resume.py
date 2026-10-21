"""P11 的两条缺判据（依据 `draft/30` §T3-P11）。

`tests/test_conductor_tools.py` 已经守住了 P11 的五条里的四条（停后不新开任务、无僵尸行、
有续跑简报、第二次 stop 不改理由）。这里守剩下那一半：

1. 在飞任务被停（第③条：记"unknown outcome"且不自动重试）—— 既有的那条用例停下来时
   其实没有在飞任务，所以这条纪律从来没被测到；
2. "停 → 热启动 → 接着做"的链路 —— 既有用例分别测了 stop 与 ensure，没测"停过之后接得上"。

关于"unknown outcome"到底是什么：`TASK_OUTCOMES` 里没有 `unknown` 这个取值，
设计对它的定义在 `cancellation.py:24-27` 逐字 —— `outcome="cancelled"` +
`detail` 写明"结果未知" + 不自动重试。本文件按那个定义判，不发明新取值。
"""

from __future__ import annotations

import threading
from pathlib import Path

from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT


class _BlockingE:
    """E 的替身：进去就等一个 Event（用来制造"在飞"状态），放行后正常返回。"""

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release
        self.calls = 0
        self.returned = False

    def list_experiments(self) -> dict:
        """无必填参数的 E 动作（与 `capabilities` 里的声明一致）。"""
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=10.0)
        self.returned = True
        return {"experiments": [], "count": 0}


def _wired(tmp_path: Path, *, registry=None):
    """工作区 + 主控 + 装了主控工具的注册表（与既有判据同一形态）。"""
    store = Store(tmp_path)
    store.init()
    c = Conductor(store, registry=registry if registry is not None else {})
    reg = build_registry(store=store, conductor=c).registry
    return store, c, reg


def _row(c: Conductor, task_id: str) -> dict:
    """按 task_id 从台账里取那一行。"""
    hits = [r for r in c.tree() if str(r.get("task_id")) == task_id]
    assert len(hits) == 1, f"台账里 {task_id!r} 应恰好一行，实得 {len(hits)}"
    return hits[0]


# ---------------------------------------------------------------- ① 在飞被停（P11 第③条）

def test_inflight_task_caught_by_stop_is_recorded_as_unknown_and_not_retried(tmp_path: Path):
    """在飞任务被 stop 抓到 ⇒ cancelled + "结果未知" + 不自动重试 + 后来的终态不许覆盖。"""
    started, release = threading.Event(), threading.Event()
    blocker = _BlockingE(started, release)
    _store, c, reg = _wired(tmp_path, registry={"E": ("object", blocker)})

    holder: dict = {}

    def worker() -> None:
        # 2026-10-16（口径 S2）：这条判据考"确定性实现被 stop 抓到" ⇒ 走内部 API
        # （工具层那条路现在一律走角色自己的循环，不进确定性实现）。
        holder["res"] = c.summon("E", "list_experiments", {}, by="M",
                                 input_key="P11:inflight")

    th = threading.Thread(target=worker)
    th.start()
    assert started.wait(timeout=10.0), "worker 没进到角色动作里 ⇒ 这条判据的前提不成立"

    stop = reg.call("conductor.stop", role="M", reason="user", drain_sec=0.0)
    assert stop.ok, stop.error
    inflight = list(stop.data["inflight_at_stop"])
    assert inflight, ("停止时台账里应当有在飞任务 —— 没有就说明这条判据什么都没测到"
                      "（这是 P11 第③条的前提，不许静默通过）")

    # (b) 那一行的三件事同时成立
    row = _row(c, inflight[0])
    assert row["status"] == "cancelled", row
    assert row["outcome"] == "cancelled", row
    assert "结果未知" in str(row["detail"]), row

    # (d) 没有僵尸行
    assert c.verify_tasks() == [], c.verify_tasks()

    # (c) 放行阻塞之后：worker 自己写的终态不许覆盖已写的终态（终态先到先得），
    #     并且台账不许因为"重试"而长出新行
    before = len(c.tree())
    release.set()
    th.join(timeout=10.0)
    assert blocker.returned, "放行后 worker 应当正常返回（这条判据不能靠线程泄漏通过）"
    after = c.tree()
    assert len(after) == before, f"停止之后不许自动重试：台账从 {before} 行长到 {len(after)} 行"
    row2 = _row(c, inflight[0])
    assert row2["status"] == "cancelled" and "结果未知" in str(row2["detail"]), row2
    assert c.verify_tasks() == [], c.verify_tasks()


def test_stop_with_nothing_inflight_is_still_idempotent(tmp_path: Path):
    """负控（反真空）：没有在飞任务时，`inflight_at_stop` 必须为空 —— 否则上面的判据是假的。"""
    _store, _c, reg = _wired(tmp_path, registry={"E": ("object", _BlockingE(
        threading.Event(), threading.Event()))})
    stop = reg.call("conductor.stop", role="M", reason="user", drain_sec=0.0)
    assert stop.ok and stop.data["inflight_at_stop"] == [], stop.data
    again = reg.call("conductor.stop", role="M", reason="budget", drain_sec=0.0)
    assert again.data["reason"] == "user", "第二次 stop 不许改写第一次的理由"


# ---------------------------------------------------------------- ② 停 → 热启动 → 接着做

def test_stop_then_warm_start_then_continue_from_the_brief(tmp_path: Path,
                                                           monkeypatch) -> None:
    """停得下、接得上：热启动判据 + 简报 + 新会话能把两次运行的台账拼成一条链。"""
    monkeypatch.setenv("AGENTFLOW_PROJECTS_DIR", str(tmp_path / "projects"))
    store, c, reg = _wired(tmp_path / "ws", registry={"E": ("object", _BlockingE(
        threading.Event(), threading.Event()))})

    cold = reg.call("conductor.ensure_project", role="M", project_name="p1", start="cold")
    assert cold.ok and cold.data["mode"] == "cold", cold.data
    first = c.summon("E", "list_experiments", {}, by="M", input_key="P11:first")
    assert first.outcome == "ok", first

    stop = reg.call("conductor.stop", role="M", reason="user")
    assert stop.ok and stop.data["verify"] == []
    brief_path = Path(stop.data["resume_brief"]["path"])
    assert brief_path.is_file()

    # (a) 停过之后 start="auto" 必得热启动（文件夹还在）
    warm = reg.call("conductor.ensure_project", role="M", project_name="p1", start="auto")
    assert warm.data["mode"] == "warm" and warm.data["created"] is False, warm.data

    # (b) 简报读得回，且带"从哪继续"
    got = reg.call("conductor.resume_brief", role="M")
    assert got.ok and got.data["present"] is True
    assert got.data["brief"].get("how_to_continue"), got.data["brief"]

    # (c) 新会话：新主控（内存状态全空）+ 同一个库 ⇒ 台账重建得出上一次的全部行，
    #     并且还能继续派活（resume 不是"锁死状态"）
    fresh = Conductor(store, registry={"E": ("object", _BlockingE(
        threading.Event(), threading.Event()))})
    fresh_reg = build_registry(store=store, conductor=fresh).registry
    tree = fresh.tree()
    assert [str(r["task_id"]) for r in tree] == [str(r["task_id"]) for r in c.tree()], \
        "新会话应当能重建出同一条台账（两次运行的台账拼成一条链）"
    again = fresh.summon("E", "list_experiments", {}, by="M", input_key="P11:second")
    assert again.outcome == "ok", again
    assert len(fresh.tree()) == len(tree) + 1, "续跑应当能再落一行（不是被上一次的 stop 锁死）"
    assert fresh.verify_tasks() == []


def test_resume_brief_before_any_stop_says_so(tmp_path: Path):
    """反真空：没停过时简报不存在，必须如实说"还没有"，不许编一份空的。"""
    _store, _c, reg = _wired(tmp_path)
    got = reg.call("conductor.resume_brief", role="M")
    assert got.data["present"] is False, got.data


def test_reset_cache_does_not_erase_the_ledger(tmp_path: Path):
    """`CT.reset_cache()`（换会话）之后，磁盘上的台账与简报仍在（会话状态 ≠ 权威）。"""
    monkeypatch_projects = tmp_path / "projects"
    store, c, reg = _wired(tmp_path / "ws", registry={"E": ("object", _BlockingE(
        threading.Event(), threading.Event()))})
    reg.call("conductor.summon", role="M", target_role="E", task="派活：列一遍实验",
             input_key="P11:only")
    reg.call("conductor.stop", role="M", reason="user")
    CT.reset_cache()
    fresh = Conductor(store, registry={})
    assert len(fresh.tree()) == 1, "台账在磁盘上，换会话不许把它清掉"
    assert (Path(store.root) / "resume-brief.json").is_file(), monkeypatch_projects
