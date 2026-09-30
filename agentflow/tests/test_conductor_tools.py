"""主控工具（T0-9）的判据：M 有手（派活）、有眼（台账/状态）、能停（优雅停止）。

依据 `draft/30` §T0-9。这一组钉住四件事：

1. M 的工具面非空且只有编排面（只读角色一件也拿不到）；
2. 派活过闸门、被拒留痕（越权 / 未接线 / 非法目标都是 refused，不是静默成功）；
3. 优雅停止五条：不再新开任务、无僵尸行、有续跑简报、幂等、不自动重试；
4. 冷/热由 M 决定，四态如实给（别人的目录绝不被当工作区初始化）。

刻意不测计划质量：那由 K 线与人工复核看，工具层只保证"合法且可审计"。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import capabilities as C
from agentflow import projects as P
from agentflow.conductor import Conductor
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT

ORCHESTRATION_TOOLS = {
    "conductor.summon", "conductor.summon_many", "conductor.ledger", "conductor.stop",
    "conductor.resume_brief", "conductor.cancel", "conductor.ensure_project",
    "conductor.state", "conductor.role_spec", "conductor.acceptance",
}


class _FakeE:
    """E 的替身：只实现一个无必填参数的动作，用来验证"派活真的到了角色手里"。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def list_experiments(self) -> dict:
        self.calls.append({})
        return {"experiments": [], "count": 0}


def _wired(tmp_path: Path, *, role_registry=None):
    """造一个工作区 + 一个主控 + 装了主控工具的注册表。"""
    store = Store(tmp_path)
    store.init()
    c = Conductor(store, registry=role_registry if role_registry is not None else {})
    reg = build_registry(store=store, conductor=c).registry
    return store, c, reg


def test_m_tool_surface_is_orchestration_only(tmp_path: Path):
    """M 拿到的正好是那 9 件编排面工具；只读角色一件也拿不到。"""
    _store, _c, reg = _wired(tmp_path)
    assert {s.name for s in reg.for_role("M")} == ORCHESTRATION_TOOLS
    for read_only in ("C", "H"):
        assert not ({s.name for s in reg.for_role(read_only)} & ORCHESTRATION_TOOLS)


def test_summon_runs_the_role_and_lands_a_ledger_row(tmp_path: Path):
    """正控：主控派活 → 角色真的被调用 → 台账里有一行 `by=agent-M` 的终态行。"""
    fake = _FakeE()
    store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", fake)})
    res = reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    assert res.ok, res.error
    assert res.data["status"] == "done" and res.data["outcome"] == "ok"
    assert fake.calls == [{}], "派活必须真的到角色手里"
    rows = store.rows("tasks")
    assert len(rows) == 1
    assert rows[0]["called_by"] == "M" and rows[0]["role"] == "E"
    assert rows[0]["ended_at"], "每个 start 必须恰好有一个 end"


def test_summon_many_fans_out_the_same_role_in_parallel(tmp_path: Path):
    """S-1（§198 的核心判据）：`conductor.summon_many` 让同一角色的多个实例真的并发。

    为什么要有这条：并发引擎（`run_plan` → `scheduler.run_waves` → 线程池 + 探针）
    早就存在，但生产路径上零调用，而 M 的工具面只能一次派一个；
    更硬的一道是分波按"角色级写集"，于是 3 个 B 会被排成 3 波串行（实测峰值真并发 1）。
    用户要的形态是"一次任务要读一大批文献，就并发几个 B 一起干"。

    判据四条一起看：① `count` 恒等于输入长度；② 三个不同 `instance` 落同一波；
    ③ `concurrent_peak == 3`（探针读数，不是墙钟）；④ 三条任务行各自独立、都是 done/ok。
    """
    class _SlowE:
        """替身：睡 0.2s 并记录自己被哪个实例标签调用过。"""

        def __init__(self) -> None:
            self.instances: list[str] = []
            self._lock = __import__("threading").Lock()

        def list_experiments(self) -> dict:
            import threading as _t
            with self._lock:
                self.instances.append(_t.current_thread().name)
            __import__("time").sleep(0.2)
            return {"experiments": [], "count": 0}

    store, _c, reg = _wired(tmp_path, role_registry={
        "E": ("factory", lambda *, store=None, instance="": _SlowE())})
    res = reg.call("conductor.summon_many", role="M", why="探针：三个实例同波",
                   targets=[{"target_role": "E", "action": "list_experiments", "instance": str(i)}
                            for i in (1, 2, 3)])
    assert res.ok, res.error
    data = res.data
    assert data["count"] == 3 and len(data["results"]) == 3
    assert data["waves"] == [3], data["waves"]
    assert data["concurrent_peak"] == 3, data["concurrent_peak"]
    assert [r["instance"] for r in data["results"]] == ["1", "2", "3"]
    assert all(r["status"] == "done" and r["outcome"] == "ok" for r in data["results"])
    assert len({r["task_id"] for r in data["results"]}) == 3
    assert len(store.rows("tasks")) == 3


def test_summon_many_auto_assigns_instances_for_a_repeated_role(tmp_path: Path):
    """正控（自动实例标签，2026-09-30）：同一角色在一批里出现多次、没给标签 ⇒ 自动补序号。

    为什么要这条：模型写一批 target 时经常不写 `instance`，而"同角色不同实例"
    是并发的唯一开关 —— 不补的话三个 B 会被排成三波串行，而台账看起来是
    "派了三份活、都成功了"（一种不会报错的失败）。判据：`waves == [3]`、
    `concurrent_peak == 3`，且每一项都标了 `auto_instance=True`。
    """
    store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    res = reg.call("conductor.summon_many", role="M",
                   targets=[{"target_role": "E", "action": "list_experiments"} for _ in range(3)])
    assert res.ok, res.error
    assert res.data["waves"] == [3], res.data["waves"]
    assert res.data["concurrent_peak"] == 3, res.data["concurrent_peak"]
    assert [r["instance"] for r in res.data["results"]] == ["E#1", "E#2", "E#3"]
    assert all(r["auto_instance"] is True for r in res.data["results"])
    assert len(store.rows("tasks")) == 3


def test_summon_many_does_not_relax_cross_role_conflicts(tmp_path: Path):
    """负控（自动标签不许顺手放宽跨角色）：A 与 B 都写 `literature` ⇒ 仍必须分波串行。

    自动补标签解决的是"同角色的 N 个实例"，不是"不同角色会不会改同一张表"。
    这条与 `test_scheduler.py::test_instance_axis_only_relaxes_the_same_role` 同族，
    只是换到工具面上再验一遍。
    """

    class _A:
        def run_once(self) -> dict:
            return {"outcome": "ok"}

    class _B:
        def run_once(self) -> dict:
            return {"outcome": "ok"}

    store, _c, reg = _wired(tmp_path, role_registry={"A": ("object", _A()),
                                                     "B": ("object", _B())})
    res = reg.call("conductor.summon_many", role="M",
                   targets=[{"target_role": "A", "action": "run_once"},
                            {"target_role": "B", "action": "run_once"}])
    assert res.ok, res.error
    assert res.data["waves"] == [1, 1], res.data["waves"]
    assert res.data["concurrent_peak"] == 1, res.data["concurrent_peak"]
    assert all(r["auto_instance"] is False for r in res.data["results"]), res.data["results"]


def test_summon_many_refuses_a_bad_target_shape(tmp_path: Path):
    """负控（参数）：targets 里塞一个非对象 ⇒ 当场拒绝（不许静默跳过那一项）。

    工具层把异常转成 `ok=False` 的结果（不抛给调用方）—— 所以判据看 `ok` 与 `error`，
    并且要确认一条任务都没落（"拒绝了"与"跳过那一项、其余照跑"是两回事）。
    """
    store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    res = reg.call("conductor.summon_many", role="M", targets=["E.list_experiments"])
    assert res.ok is False and res.error, res
    assert "targets" in str(res.error) and "对象" in str(res.error), res.error
    assert store.rows("tasks") == []


def test_ledger_relays_view_reports_pending_and_fulfilled(tmp_path: Path):
    """代唤申请的可判定视图（§199）：留言是给人看的，这个视图是给主控看的。

    判据：一条 `agent_summon_request` 算"已受理"，当且仅当台账里存在一条同
    (角色, 动作) 且 `started_at >= 申请时刻` 的任务行。三态：读不到会话目录时
    `relay_pending` 必须是 `None`（没查成），不是 `0`（没有申请）。
    """
    from agentflow import schema as S
    from agentflow import sessions as SS

    store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    root = Path(store.root)
    SS.append(root, {"kind": "agent_summon_request", "role": "H", "wants_role": "A",
                     "wants_action": "run_once", "refusal_reason": "forbidden_edge",
                     "ts": "2026-01-01T00:00:00+00:00"}, sid="probe")

    # ① 还没有人派 A ⇒ 待受理 1 条
    got = reg.call("conductor.ledger", role="M", view="relays")
    assert got.ok, got.error
    assert got.data["relay_pending"] == 1, got.data
    assert got.data["relays"][0]["fulfilled"] is False, got.data["relays"]

    # ② 台账里出现一条之后的 A.run_once ⇒ 视为已受理（判据是台账事实，不是承诺）
    with store.tx("tasks", actor="probe") as tx:
        row = S.Task(task_id="t-9001", role="A", action="run_once", called_by="M",
                     status="done", outcome="ok", input_key="A.run_once",
                     detail="探针：模拟主控替 H 派了 A",
                     started_at="2026-01-01T00:00:01+00:00",
                     ended_at="2026-01-01T00:00:02+00:00").to_dict()
        tx.upsert("tasks", row)
    got2 = reg.call("conductor.ledger", role="M", view="relays")
    assert got2.data["relay_pending"] == 0, got2.data
    assert got2.data["relays"][0]["fulfilled"] is True, got2.data["relays"]
    assert got2.data["relays"][0]["fulfilled_by_task"] == "t-9001"

    # ③ 负控（三态）：会话目录不在 ⇒ `None`（没查成），不是 0
    import shutil

    shutil.rmtree(root / "sessions")
    got3 = reg.call("conductor.ledger", role="M", view="relays")
    assert got3.data["relay_pending"] is None, got3.data
    assert got3.data["relay_note"], got3.data


def test_summon_without_wiring_refuses_and_still_writes_the_row(tmp_path: Path):
    """负控：角色没接线 ⇒ refused/not_wired，而且拒绝也落台账（不许静默）。"""
    store, _c, reg = _wired(tmp_path)
    res = reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    assert res.ok, res.error
    assert res.data["outcome"] == "refused" and res.data["refusal_reason"]
    rows = store.rows("tasks")
    assert len(rows) == 1, "拒绝也是一次召唤，必须留痕"
    assert rows[0]["outcome"] == "refused"


def test_summon_refuses_illegal_targets(tmp_path: Path):
    """负控：派给不可召唤的角色（主控自己）与不存在的动作 ⇒ 都被拒。"""
    _store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    to_m = reg.call("conductor.summon", role="M", target_role="M", action="list_experiments", input_key="E.list_experiments")
    assert to_m.data["outcome"] == "refused", to_m.data
    bad_action = reg.call("conductor.summon", role="M", target_role="E", action="没有这个动作", input_key="x")
    assert bad_action.data["outcome"] == "refused"
    assert "unknown_action" in str(bad_action.data["refusal_reason"])


def test_stop_is_graceful_and_idempotent(tmp_path: Path):
    """优雅停止：停后再派活不产生新任务、无僵尸行、有续跑简报、第二次不改理由。"""
    _store, c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")

    first = reg.call("conductor.stop", role="M", reason="user")
    assert first.ok, first.error
    assert first.data["verify"] == [], "停止后不许留 running/pending 的僵尸行"
    brief_path = Path(first.data["resume_brief"]["path"])
    assert brief_path.is_file(), "优雅停止必须留下续跑简报（否则就是粗暴 kill）"

    # ① 停后不再新开任务：再派一次，台账不许多一行
    before = len(c.tree())
    again = reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    assert again.data["outcome"] in ("cancelled", "refused")
    assert len(c.tree()) == before, "停止之后不许再产生新任务"

    # ⑤ 幂等：第二次 stop 不改第一次的理由
    second = reg.call("conductor.stop", role="M", reason="budget")
    assert second.data["detail"] == first.data["detail"]
    assert second.data["reason"] == "user"


def test_resume_brief_reads_back_what_stop_wrote(tmp_path: Path):
    """续跑简报读得回来，且带"做了什么"的事实（不是建议）。"""
    _store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    reg.call("conductor.stop", role="M", reason="user")
    got = reg.call("conductor.resume_brief", role="M")
    assert got.ok and got.data["present"] is True
    brief = got.data["brief"]
    assert brief["tasks_total"] == 1
    assert brief["outcome_counts"].get("ok") == 1
    assert "how_to_continue" in brief


def test_ensure_project_decides_cold_then_warm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """冷/热由 M 决定：第一次冷启动建目录，第二次热启动复用；四态如实给。"""
    monkeypatch.setenv("AGENTFLOW_PROJECTS_DIR", str(tmp_path / "projects"))
    _store, _c, reg = _wired(tmp_path)
    cold = reg.call("conductor.ensure_project", role="M", project_name="project1", start="cold")
    assert cold.ok, cold.error
    assert cold.data["mode"] == "cold" and cold.data["created"] is True
    assert cold.data["state"] == "workspace"

    warm = reg.call("conductor.ensure_project", role="M", project_name="project1", start="auto")
    assert warm.data["mode"] == "warm" and warm.data["created"] is False
    assert warm.data["state"] == "workspace"


def test_ensure_project_refuses_foreign_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """负控：目录不空且不是本框架的工作区 ⇒ 明确失败，绝不被当工作区初始化。"""
    root = tmp_path / "projects"
    foreign = root / "manual-notes"
    foreign.mkdir(parents=True)
    (foreign / "notes.txt").write_text("别人的东西", encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_PROJECTS_DIR", str(root))
    _store, _c, reg = _wired(tmp_path)

    res = reg.call("conductor.ensure_project", role="M", project_name="manual-notes", start="auto")
    assert res.ok is False, "存在但不是工作区时必须失败"
    assert "manual-notes" in str(res.error)
    assert sorted(p.name for p in foreign.iterdir()) == ["notes.txt"], "绝不往别人的目录里写东西"


def test_state_and_role_spec_are_read_only_views(tmp_path: Path):
    """状态视图与角色规格：都与既有单一来源同源，且不写任何字节。"""
    store, _c, reg = _wired(tmp_path)
    st = reg.call("conductor.state", role="M")
    assert st.ok and st.data["tables"].get("tasks") == 0
    spec = reg.call("conductor.role_spec", role="M", role_name="C")
    actions = {a["action"] for a in spec.data["actions"]}
    assert "hottest" in actions, "角色规格必须来自 capabilities"
    assert spec.data["summonable"] is True
    assert reg.call("conductor.role_spec", role="M", role_name="M").data["summonable"] is False
    assert len(store.rows("tasks")) == 0, "只读视图不许写台账"


def test_ledger_views(tmp_path: Path):
    """台账四个视图都能出读数（tree/stats/issues/verify）。"""
    _store, _c, reg = _wired(tmp_path, role_registry={"E": ("object", _FakeE())})
    reg.call("conductor.summon", role="M", target_role="E", action="list_experiments", input_key="E.list_experiments")
    for view in ("tree", "stats", "issues", "verify"):
        got = reg.call("conductor.ledger", role="M", view=view)
        assert got.ok, (view, got.error)
        assert got.data["task_count"] == 1


def test_capabilities_unchanged_for_the_conductor(tmp_path: Path):
    """红线：主控拿到工具没有改变"它不产出领域对象"这条约束。"""
    assert C.CAPABILITIES["M"] == ()
    assert not C.WRITE_SETS["M"], "主控的领域写集必须仍为空"
    assert C.CONDUCTOR_WRITE_SET == frozenset({"tasks"})
    assert "M" in C.NON_SUMMONABLE, "主控仍不可被召唤"


def test_resume_brief_absent_is_reported_honestly(tmp_path: Path):
    """没有停止过就没有简报：如实说"没有"，不许编一份空的当有。"""
    _store, _c, reg = _wired(tmp_path)
    got = reg.call("conductor.resume_brief", role="M")
    assert got.ok and got.data["present"] is False
    assert got.data["brief"] == {}
    assert json.dumps(got.data, ensure_ascii=False)

