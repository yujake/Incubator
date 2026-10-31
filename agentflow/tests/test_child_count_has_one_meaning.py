# -*- coding: utf-8 -*-
"""判据：`child_count` 不许同时指两件东西（2026-11-03，153-U-13；业主 2026-11-03 的裁决 4）。

## 背景

同一个键名 `child_count` 落在两个分母与范围都不同的问题上：

| 落点 | 数的是什么 | 范围 |
|---|---|---|
| `webui.readers.roster_face` 的节点格（`readers.py:3837`） | 这个节点在台账里挂了几个子（含没落名册的） | 这个节点 |
| `Secretary.child_counts` 的 `child_count`（`secretary.py:7912`） | 名册里还有几个没销号的项 | 全工作区 / 按 owner |

两个都对，但拿两处 `child_count` 对照的人只会得出"有一个在说谎"。

## 业主的裁决与这条判据落实的形态

- 网页那一格改叫 `children_in_ledger`（"台账里挂了几个子"），名册项数那格照旧是
  `roster_child_count`；
- 收工那一格（`child_counts` 的 `child_count`）的改名要动 `CHILD_COUNT_KEY` 的值 ⇒
  会改到 M 的提示词正文（`agent_prompts.py:3060` 逐字引着这个键名）⇒ 命中 FC-27
  （`tests/golden/agent_surface_snapshot.json:254` 有渲染副本）。那半笔不在本文件里，
  见提交信息与报告。

## 这条判据钉住什么

1. 名册面节点格叫 `children_in_ledger`，且同一个节点上不再有 `child_count`；
2. 收工读数那一个仍然是"名册里未销号项数"（1 个名册项 / 2 个台账子）⇒ 两个数不同值，
   证明它们是两个量（也就说明为什么必须两个名）；
3. 前端两处（`rosterTree.ts` 的类型映射、`Roster.tsx` 的「子 N」）读的都是新名字 ——
   只改后端的话页面读不到那个数。
"""
from __future__ import annotations

import pathlib

from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

REPO = pathlib.Path(__file__).resolve().parents[1]
ROSTER_TSX = REPO / "ui" / "src" / "components" / "Roster.tsx"
ROSTER_TREE_TS = REPO / "ui" / "src" / "rosterTree.ts"

#: 夹具时间戳（`schema.Task` 要求"每个 start 有且仅有一个 end"对得上）。
AT = "2026-10-24T23:30:00+08:00"


def _row(task_id: str, *, role: str, parent: str | None, depth: int) -> dict:
    return {"task_id": task_id, "role": role, "action": "", "called_by": "parent",
            "parent_task_id": parent, "depth": depth, "input_key": f"k@{task_id}",
            "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
            "detail": "夹具：153-U-13（两个 child 计数不许同名）", "error": None,
            "started_at": AT, "ended_at": AT, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [], "kind": "", "expects": "",
            "item_state": "", "item_close": "", "seen_by": "", "seen_step": None,
            "keep_alive": False}


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """台账 2 个子、名册 1 项 —— 两个数不同值，是这条判据要的形状。"""
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    store = Store(root)
    sec = Secretary("M", root=root, store=store)
    got = sec.roster_add(owner="t-000001", role="D", task_id="t-000002", brief="落了名册的那个")
    assert got.get("problem") == "", got
    with store.tx("tasks", actor="test", note="153-u13 fixture") as tx:
        tx.upsert("tasks", _row("t-000001", role="M", parent=None, depth=1), note="顶趟")
        tx.upsert("tasks", _row("t-000002", role="D", parent="t-000001", depth=2), note="子 1")
        tx.upsert("tasks", _row("t-000003", role="D", parent="t-000001", depth=2), note="子 2")
    return root


def _m_node(face: dict) -> dict:
    got = [n for n in face.get("nodes") or [] if str(n.get("task_id")) == "t-000001"]
    assert len(got) == 1, [n.get("task_id") for n in face.get("nodes") or []]
    return got[0]


def test_the_roster_face_counts_children_in_the_ledger_under_its_own_name(
        tmp_path: pathlib.Path) -> None:
    """① 网页那一格叫 `children_in_ledger`，且同一节点上不再有 `child_count`（今天红）。"""
    root = _workspace(tmp_path)
    face = R.roster_face(root)
    node = _m_node(face)
    assert node.get("children_in_ledger") == 2, (
        f"台账里这个节点挂了 2 个子，`children_in_ledger` 实测 {node.get('children_in_ledger')!r}"
        f"（今天它还叫 `child_count`：{node.get('child_count')!r}）")
    assert node.get("roster_child_count") == 1, node
    assert "child_count" not in node, (
        "名册面节点上还留着 `child_count` ⇒ 它和收工读数里那个 `child_count`（名册未销号项数）"
        "仍然同名不同义")


def test_the_two_numbers_are_two_quantities(tmp_path: pathlib.Path) -> None:
    """② 两个数确实不同值（所以必须两个名）：台账 2 子 vs 名册 1 项。"""
    root = _workspace(tmp_path)
    node = _m_node(R.roster_face(root))
    counts = Secretary("M", root=root, store=Store(root)).child_counts(owner="t-000001")
    ledger_side = node.get("children_in_ledger")
    roster_side = counts.get("child_count")
    assert ledger_side == 2 and roster_side == 1, (ledger_side, roster_side)
    assert ledger_side != roster_side, (
        "两个数今天相等 ⇒ 这条判据失去了'同名不同义'的对象，请重新裁这两个名字")


def test_the_frontend_reads_the_new_name() -> None:
    """③ 前端两处读的都是新名字（只改后端 ⇒ 页面读不到那个数）。"""
    tree = ROSTER_TREE_TS.read_text(encoding="utf-8")
    assert "children_in_ledger" in tree, (
        "`ui/src/rosterTree.ts` 没有把 `children_in_ledger` 映射进来（页面拿不到这一格）")
    tsx = ROSTER_TSX.read_text(encoding="utf-8")
    assert "node.children_in_ledger" in tsx, "`Roster.tsx` 的「子 N」没有读 `children_in_ledger`"
