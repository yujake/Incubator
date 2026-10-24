"""父节点的「子 N」按台账数，未落名册的子挂在父节点下（2026-10-25 业主截图的读数面）。

## 事故（真机 sylow4，截图与只读盘上读数）

```
台账：M（t-000001）名下实际 6 个子（D1/D2/D3 + A t-000047 + A t-000048 + G t-000051）
名册面：M 显示「子 4」；t-000048 进 unplaced；t-000051 压根没出现
```

根因是"数的东西不是同一个量"：页面上的「子 N」取的是名册项数（`node.children.length`），
而名册项只管"落了名册"的那些。名册漏写一个（写侧的缺口见
`tests/test_summon_without_a_name_still_registers.py`），父的子树读数就比台账低一个，
而少的那一个既不在这棵树里、也没有任何一处说"它是谁的儿子" —— 只剩页面底部那个
`unplaced` 列表。

## 修法（只加，不动既有键的语义）

- `roster_face` 每个节点补三格：`child_count`（台账里的子数；台账读不到 ⇒ null）、
  `roster_child_count`（名册项数）、`unrostered_children`（有父、没落名册的那些：
  编号 + 角色 + 状态 + 为什么）；
- 前端「子 N」改成读 `child_count`，并在名册项数比它少时同一格后面写
  「其中 M 个未落名册」；未落名册的那些挂在父节点下面一行（编号 + 角色 + 状态），
  同时仍进页面底部的 `unplaced`（两处同一处判据的两个落位）。

## 判据

| 条 | 这条问什么 | 改前红在哪 |
|---|---|---|
| f | 台账 6 子 / 名册 4 项 ⇒ 父节点读数是 6，带 2 个未落名册；`unplaced` 里恰好是那 2 个 | 改前节点上没有 `child_count` 这一格，页面读的是 `children.length` = 4 |
| g | 反真空：把"未落名册"的计数打桩成 0 ⇒ f 必红 | 这一条证明 f 真的在测"按台账数"，不是被空数组顺手带绿 |

另加一条源码判据（前端那一半）：`Roster.tsx` 必须真的用 `child_count` 与
`unrostered_children` 渲染，且同一格带「其中 M 个未落名册」那句话 —— 只改后端
的话，页面上那个"4"一个字都不会变。

## 纪律

纯夹具（`Secretary.roster_add` 是写侧唯一实现），零模型调用、不碰真工作区。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

REPO = pathlib.Path(__file__).resolve().parents[1]
ROSTER_TSX = REPO / "ui" / "src" / "components" / "Roster.tsx"

#: 夹具里的时间戳（`schema.Task` 的"每个 start 有且仅有一个 end"要求它对得上）。
AT = "2026-10-24T23:30:00+08:00"


def _row(task_id: str, *, role: str, parent: str | None, depth: int,
         status: str = "done") -> dict[str, Any]:
    """一条实例行（`kind == ""`：一个 agent 一行，与 `schema.Task` 同形）。"""
    ended = None if status in ("pending", "running") else AT
    return {"task_id": task_id, "role": role, "action": "", "called_by": "parent",
            "parent_task_id": parent, "depth": depth, "input_key": f"k@{task_id}",
            "status": status, "outcome": None if ended is None else "ok",
            "refusal_reason": None, "instance": "",
            "detail": "夹具：这一行是「子 N 按台账数」判据用的台账行", "error": None,
            "started_at": AT, "ended_at": ended, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [], "kind": "", "expects": "",
            "item_state": "", "item_close": "", "seen_by": "", "seen_step": None,
            "keep_alive": False}


#: 台账里 M 名下的 6 个子；前 4 个落名册，后 2 个（t-000048 / t-000051）没落。
CHILDREN = (("t-000002", "D"), ("t-000003", "D"), ("t-000004", "D"),
            ("t-000047", "A"), ("t-000048", "A"), ("t-000051", "G"))
REGISTERED = CHILDREN[:4]
UNROSTERED = CHILDREN[4:]


def _ws_with_six_children_and_four_roster_items(tmp: pathlib.Path) -> pathlib.Path:
    """造 sylow4 那个形状：台账 6 个子、名册只有 4 项。

    写侧仍然是 `Secretary.roster_add`（盘上格式的唯一实现），台账行走 `store.tx`
    （与真机落行的形状同一条）。
    """
    root = tmp / "ws"
    root.mkdir()
    Store(root).init()
    store = Store(root)
    sec = Secretary("M", root=root, store=store)
    for tid, role in REGISTERED:
        got = sec.roster_add(owner="t-000001", role=role, task_id=tid,
                             brief=f"{role} {tid} 这一件活")
        assert got.get("problem") == "", got
        assert got.get("name"), got
    with store.tx("tasks", actor="test", note="child-count fixture") as tx:
        tx.upsert("tasks", _row("t-000001", role="M", parent=None, depth=1), note="顶趟")
        for tid, role in CHILDREN:
            tx.upsert("tasks", _row(tid, role=role, parent="t-000001", depth=2),
                      note=f"子 {tid}")
    return root


def _m_node(face: dict[str, Any]) -> dict[str, Any]:
    got = [n for n in face.get("nodes") or [] if str(n.get("task_id")) == "t-000001"]
    assert len(got) == 1, [n.get("task_id") for n in face.get("nodes") or []]
    return got[0]


# ---------------------------------------------------------------- 判据 f（正控）


def _f_the_child_count_is_the_ledger_count(face: dict[str, Any]) -> None:
    """判据 f 的正控内容（判据 g 复用同一份断言来做反真空）。"""
    node = _m_node(face)
    # 改前红：这一格不存在（页面读的是 children.length = 4）。
    assert node.get("child_count") == 6, ("「子 N」必须按台账数", node.get("child_count"), node)
    assert node.get("roster_child_count") == 4, node
    missing = [str(u.get("task_id")) for u in node.get("unrostered_children") or []]
    assert missing == [str(t) for t, _r in UNROSTERED], missing
    for cell in node.get("unrostered_children") or []:
        assert str(cell.get("role") or ""), ("未落名册的子要带角色", cell)
        assert str(cell.get("status") or ""), ("未落名册的子要带状态", cell)
    # 两处口径一致：它们同时仍进页面底部那个 unplaced（不是二选一）。
    unplaced = sorted(str(u.get("task_id")) for u in face.get("unplaced") or [])
    assert unplaced == sorted(str(t) for t, _r in UNROSTERED), unplaced
    assert all(str(u.get("parent_task_id")) == "t-000001"
               for u in face.get("unplaced") or []), face.get("unplaced")
    # 名册项那 4 个照旧在 children 里（这一改不许把名册本来就有的子挤掉）。
    roster_kids = sorted(str(c.get("task_id")) for c in node.get("children") or [])
    assert roster_kids == sorted(str(t) for t, _r in REGISTERED), roster_kids


def test_f_the_child_count_is_the_ledger_count(tmp_path: pathlib.Path) -> None:
    """判据 f：台账 6 子 / 名册 4 项 ⇒ 父节点读数是 6，带 2 个未落名册。"""
    root = _ws_with_six_children_and_four_roster_items(tmp_path)
    face = R.roster_face(root)
    assert face["answer"] == "ok", (face["answer"], face["reason"])
    _f_the_child_count_is_the_ledger_count(face)


def test_f_the_ledger_fallback_carries_the_same_three_cells(tmp_path: pathlib.Path) -> None:
    """判据 f 的兜底档：名册读不到 ⇒ 台账兜底那棵树也要带这三格（键集不许两档不一样）。"""
    root = tmp_path / "bare"
    root.mkdir()
    Store(root).init()
    store = Store(root)
    with store.tx("tasks", actor="test", note="fallback fixture") as tx:
        tx.upsert("tasks", _row("t-000001", role="M", parent=None, depth=1), note="顶趟")
        tx.upsert("tasks", _row("t-000002", role="D", parent="t-000001", depth=2), note="子")
    face = R.roster_face(root)
    assert face["answer"] == "unknown", face["reason"]
    node = _m_node(face)
    assert node["child_count"] == 1, node
    assert node["roster_child_count"] == 0, node
    assert [u["task_id"] for u in node["unrostered_children"]] == ["t-000002"], node
    assert node["registered"] is False, node


# ---------------------------------------------------------------- 判据 g（反真空）


def test_g_negctl_zeroing_the_unrostered_count_makes_f_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 g：把"未落名册"的计数打桩成 0 ⇒ f 必红（反真空）。"""
    root = _ws_with_six_children_and_four_roster_items(tmp_path)
    monkeypatch.setattr(R, "_roster_unrostered_children", lambda *a, **k: [])
    face = R.roster_face(root)
    assert face["answer"] == "ok", face["reason"]
    # 打桩之后父节点读数是 6、未落名册 0 ⇒ f 的"带 2 个"那一条必须红
    with pytest.raises(AssertionError):
        _f_the_child_count_is_the_ledger_count(face)


# ---------------------------------------------------------------- 前端那一半


def test_the_page_shows_the_ledger_count_and_the_unrostered_children() -> None:
    """前端源码判据：「子 N」读 `child_count`，未落名册的子挂在父节点下并带那两格。

    为什么这一条是源码判据：页面读的是 `/api/roster` 的同一份 payload，但"显示哪一格"
    只活在前端（本仓对前端事实的既有口径，见 `test_roster_renders_as_a_tree.py` 判据③）。
    只改后端的话，页面上那个"4"一个字都不会变。
    """
    text = ROSTER_TSX.read_text(encoding="utf-8")
    assert "childCountText" in text, "前端没有把「子 N」抽成一个可读的式子"
    assert "node.child_count" in text, "「子 N」没有读 child_count（改前读的是 children.length）"
    assert "未落名册" in text, "名册项数比台账少时没有显式写「其中 M 个未落名册」"
    assert "unrosteredOf" in text and "UnrosteredLine" in text, \
        "未落名册的子没有挂在父节点下（不许只躺在页面底部的 unplaced 里）"
    assert "u.role" in text and "u.status" in text, "未落名册的子要显示编号 + 角色 + 状态"
