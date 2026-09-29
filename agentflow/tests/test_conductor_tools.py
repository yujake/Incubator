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
    "conductor.summon", "conductor.ledger", "conductor.stop", "conductor.resume_brief",
    "conductor.cancel", "conductor.ensure_project", "conductor.state", "conductor.role_spec",
    "conductor.acceptance",
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

