# -*- coding: utf-8 -*-
"""判据：一个数一个名、一个分母（2026-11-03，153-U-05；业主 2026-11-03 的裁决 4）。

## 背景

"板上还剩几件"今天有三个分母，其中两个都叫 `open_count`：

| 落点 | 分母 | 含合成项 | 范围 |
|---|---|---|---|
| `Conductor.board_view` | 真板项 | 是（并进同一个数） | 全工作区 |
| `patrol` 的 `board` 子格（`conductor_tools._board_cell`） | 真板项 | 否 | 这一个子 |
| `retire_integrity` 的节点格 | 真板项 | 否 | 这一个节点 |

前两个同名不同分母 ⇒ 任何拿它们对照的人都会得出"有一个在说谎"，而两个都对。

## 业主的裁决与这条判据落实的形态

- `board_view` 的真板项数改叫 `board_open_count`，列表改叫 `board_open_items`；
  **合成项分开列**：`pending_attack_items` / `pending_search_items`（+ 原有的两个 count）。
  合成项不落台账（每拍现造），与真板项不同源 —— 合进同一个数里就说不清"板上还剩几件活"。
- `patrol` 的那一个改叫 `child_open_count`（它的分母是"这一个子代理名下"）。
- 三处各带一句"这个名字量的是什么"（写在源串里，见两个返回值旁边的注释）。

## 这条判据钉住什么

1. 同一份工作区上：1 条真板项 + 1 条合成项（登记的猜想没有立项）⇒
   `board_open_count == 1`（只数真板项）而 `pending_attack_count == 1`；
   今天 `open_count == 2`（合成项并进去了）；
2. 名字不再撞：`board_view` 的返回里没有 `open_count` / `open_items`；
   `_board_cell` 的返回里没有 `open_count`，有的是 `child_open_count`。
"""
from __future__ import annotations

import ast
import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.store import Store

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONDUCTOR_TOOLS = ROOT / "src" / "agentflow" / "tools" / "conductor_tools.py"


def _cond(tmp_path: pathlib.Path) -> Conductor:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("conjectures", actor="test") as tx:
        tx.upsert("conjectures", {"conjecture_id": "000000", "statement": "探针猜想",
                                  "question": "q", "form": "universal",
                                  "status": "proposed", "origin": "gap",
                                  "testable": True, "notes": "", "experiment_ids": []})
    return Conductor(st, backend=LocalBackend({}))


def test_the_board_count_counts_only_real_board_items(tmp_path: pathlib.Path) -> None:
    """① 真板项与合成项分开数（今天红：`open_count` 把两件并成一个数）。"""
    cond = _cond(tmp_path)
    cond.open_item(kind="message", role="M", expects="ack", summary="真板项")
    view = cond.board_view(limit=20)
    assert view.get("board_open_count") == 1, (
        f"`board_open_count` 应当是 1（只数真板项），实测 {view.get('board_open_count')!r}；"
        f"今天的 `open_count` 是 {view.get('open_count')!r}（合成项被并进去了）")
    assert [str(r.get("kind") or "") for r in (view.get("board_open_items") or [])] == ["message"], (
        f"`board_open_items` 应当只有那条真板项，实测 {view.get('board_open_items')!r}")
    assert view.get("pending_attack_count") == 1, view
    assert [str(r.get("kind") or "") for r in (view.get("pending_attack_items") or [])] \
        == ["pending_attack"], f"合成项要分开列出来，实测 {view.get('pending_attack_items')!r}"
    assert "open_count" not in view and "open_items" not in view, (
        f"`board_view` 里还留着旧名字（同名不同分母的来源）：{[k for k in view if 'open_count' == k or 'open_items' == k]}")


def _dict_keys_of(path: pathlib.Path, function: str) -> set[str]:
    """某个函数里所有字典字面量的字符串键（现读，不手抄）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            keys: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    for key in sub.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            keys.add(key.value)
            return keys
    raise AssertionError(f"{path.name} 里找不到 {function}() ⇒ 判据的对象没了")


def test_the_two_counts_no_longer_share_a_name() -> None:
    """② 两个分母各一个名（`_board_cell` 是 patrol 的那一个，它只数这一个子）。"""
    board_keys = _dict_keys_of(ROOT / "src" / "agentflow" / "conductor.py", "board_view")
    assert "board_open_count" in board_keys and "board_open_items" in board_keys, (
        f"`board_view` 的返回键里没有新的名字：{sorted(board_keys)}")
    assert "open_count" not in board_keys, "`board_view` 还在返回 `open_count`"
    patrol_keys = _dict_keys_of(CONDUCTOR_TOOLS, "_board_cell")
    assert "child_open_count" in patrol_keys, (
        f"patrol 的 board 子格没有改叫 `child_open_count`：{sorted(patrol_keys)}")
    assert "open_count" not in patrol_keys, "patrol 的 board 子格还在返回 `open_count`"
