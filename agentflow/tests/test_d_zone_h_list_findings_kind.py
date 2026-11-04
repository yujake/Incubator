# -*- coding: utf-8 -*-
"""D 区：`H.list_findings` 的 `kind` 过滤 —— 动作面承诺了，工具面做不到。

动作面（`src/agentflow/specs/h.py` 里 `H.list_findings` 的 `params`）写着四格：
`doc_id` / `level` / `status` / `kind`；而真正执行的那件工具
`review.list_findings` 只收 `doc_id` / `level` / `status`（`additionalProperties=False`）。
于是照动作面派活 —— `conductor.summon("H", "list_findings", {"kind": …})` ——
会被工具层拒成 `invalid_params`：动作面承诺的那一格，工具面做不到，
而"照能力表派活、再被拒"正是最贵的一种失败（那一步的预算白花，
读数上还像是 H 不肯干活）。

判据三条：

① 动作面承诺的 `kind` 真的过滤（走 `conductor.summon` 这条派活路）；
② 同一个过滤在直调 `AgentH.list_findings(kind=…)` 时也成立（两个入口不分家）；
③ 反真空：工具面本身没有因此变宽 —— `review.list_findings` 的参数表仍然只有
   `doc_id` / `level` / `status`。这一条盯着修法：`kind` 的过滤属于动作面那一侧
   （H 的实现按 `kind` 现筛），不是把工具的参数表偷偷加一格。
"""

from __future__ import annotations

import pathlib
import sys

from agentflow import schema as S
from agentflow.agent_h import AgentH
from agentflow.host import wired_conductor
from agentflow.store import Store
from agentflow.tools import review_tools as RV

#: 夹具里的两条发现：一条 `overclaim`、一条 `garbled`（两个不同的受控 kind）。
KINDS = ("overclaim", "garbled")


def _seed(store: Store) -> None:
    """直接写两行 schema 合法的 `review_findings`（不经过 review 动作，夹具自足）。"""
    with store.tx("review_findings", actor="seed", note="test:H.list_findings kind") as tx:
        for i, kind in enumerate(KINDS, start=1):
            tx.upsert("review_findings", S.ReviewFinding(
                finding_id=S.format_id(i), doc_id=S.format_id(0), kind=kind,
                level="error", target=f"claim-{i}", evidence="夹具证据（一条可复核的读数）",
                message=f"夹具发现 {i}").to_dict())


def _store(tmp_path: pathlib.Path) -> Store:
    store = Store(tmp_path / "ws")
    store.init()
    _seed(store)
    return store


def _kinds(payload: dict) -> list[str]:
    return [str(r.get("kind")) for r in payload.get("findings") or ()]


def test_the_declared_kind_filter_works_through_the_action_face(
        tmp_path: pathlib.Path) -> None:
    """① 照动作面派活（`kind=`）真的过滤 —— 改前这一步是 `refused/invalid_params`。"""
    store = _store(tmp_path)
    cond = wired_conductor(store, workspace_root=str(store.root))

    # 前提：不给 kind 时两条都出来（过滤器不是"永远只给一条"的桩）
    every = cond.summon("H", "list_findings", {}, by="M")
    assert str(every.outcome) == "ok", every
    assert every.payload["count"] == len(KINDS), every.payload

    got = cond.summon("H", "list_findings", {"kind": "overclaim"}, by="M")
    assert str(got.outcome) == "ok", (
        f"动作面写着 `kind`、派活却被拒：{got.outcome} {got.refusal_reason} {got.detail}")
    assert _kinds(got.payload) == ["overclaim"], got.payload
    assert got.payload["count"] == 1, got.payload


def test_the_declared_kind_filter_works_when_called_directly(
        tmp_path: pathlib.Path) -> None:
    """② 直调 `AgentH.list_findings(kind=…)` 与派活那条路同一口径（两个入口不分家）。"""
    store = _store(tmp_path)
    agent = AgentH(store)

    assert agent.list_findings()["count"] == len(KINDS)
    got = agent.list_findings(kind="garbled")
    assert _kinds(got) == ["garbled"], got
    assert got["count"] == 1, got
    # 不认识的 kind ⇒ 空表（一次纯列举：没有"没查成"这一档，也不假装有）
    assert agent.list_findings(kind="not_a_finding_kind") == {"count": 0, "findings": []}


def test_the_tool_face_is_not_widened_by_the_kind_filter() -> None:
    """③ 反真空：工具 `review.list_findings` 的参数表仍然没有 `kind`。

    为什么这也要判：`kind` 的承诺在动作面（`H.list_findings`）。若修法是把工具面
    加一格，就会改变工具面（`tools/golden` 的冻结面、以及"哪一层负责过滤"这件事）；
    而这条缺陷的正确落点是 H 的实现按 `kind` 现筛 —— 工具面一个字都不动。
    """
    props = set((RV._review_list_findings_tool.__tool_spec__.params.get("properties") or {}))
    assert props == {"doc_id", "level", "status"}, (
        f"`review.list_findings` 的参数表变了（收到 {sorted(props)}）："
        "`kind` 的过滤属于动作面那一侧，不该在这里加")
