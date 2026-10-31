# -*- coding: utf-8 -*-
"""E10：`tsc` 的盲区 —— 后端真的会给出的键，`types.ts` 必须声明（反向也不许凭空多）。

## 这一份守什么

E10 点名两格：`RosterNode.registered`（台账兜底档的节点才有：名册档的节点不带它，
= 它在名册上）与 `CacheActive.key`（`GET /api/cache` 的 `active` 那一格，起跑读数
与换 key 提醒都靠它）。它们的形状真身不在 `types.ts`，在
`webui.readers._roster_from_tasks` / `webui.readers.roster_face` 与
`cachectl.active_reading`；`_TS_TYPES` 只是向它们对齐。

## 为什么取键必须扫所有行（E4 的教训）

E4 那次漏 `AcceptanceCheck.max` 的直接原因是契约判据的取键只看第一行：夹具第一行
是 `min` 档，于是"真机 60/99 份工作区里那些 max-only 行"在判据的世界里不存在 ——
`types.ts` 把 `min` 写成必填、把 `max` 漏掉，`tsc` 全绿，页面 `String(undefined)`。
所以这里的取键一律是「所有行的并集」：名册档与台账兜底档的节点都要并进来（两档的
键集不同正是 `registered` 只在一档出现的原因），并有一条负控（③）钉住"第二行才
出现的键也会被看见"。

| 判据 | 它钉的是 | 改前红在哪 |
|---|---|---|
| ① `test_every_key_the_backend_really_gives_is_declared` | 后端（名册档 ∪ 兜底档 ∪ `/api/cache`）给出的每个键都在 `_TS_TYPES` 里 | `RosterNode` 缺 `registered`、`CacheActive` 缺 `key` |
| ② `test_no_declared_key_is_missing_from_the_readings` | 声明成必填的每个键，后端一定给得出（反向） | 改前不红（两格都不是"多声明"）；它守的是下一步不许把 `key` 写成别的形状 |
| ③ `test_the_key_census_takes_the_union_of_every_row` | 取键是并集（负控：第二行才有的键必须被看见） | 改前不红（并集已随 E4 落地，这一条钉住它不许退回去） |
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import cachectl
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
ROSTER_TSX = UI_SRC / "components" / "Roster.tsx"
PROMPT_CACHE_TSX = UI_SRC / "components" / "PromptCache.tsx"

#: 夹具里的时间戳（`schema.Task` 的"每个 start 有且仅有一个 end"要求它对得上）。
_AT = "2026-10-21T00:00:00+08:00"


# ====================================================================== 夹具
def _row(task_id: str, *, role: str, parent: str | None, depth: int,
         status: str) -> dict[str, Any]:
    """一条实例行（`kind == ""`：一个 agent 一行，与 `schema.Task` 同形）。"""
    ended = None if status in ("pending", "running") else _AT
    outcome = None if status in ("pending", "running") else "ok"
    return {"task_id": task_id, "role": role, "action": "", "called_by": "parent",
            "parent_task_id": parent, "depth": depth, "input_key": f"k@{task_id}",
            "status": status, "outcome": outcome, "refusal_reason": None,
            "instance": "", "detail": "E10 夹具：台账里的一行", "error": None,
            "started_at": _AT, "ended_at": ended, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [], "kind": "", "expects": "",
            "item_state": "", "item_close": "", "seen_by": "", "seen_step": None,
            "keep_alive": False}


def _roster_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """有名册的工作区（`Secretary.roster_add` 是名册写侧的唯一实现）。"""
    root = tmp / "ws"
    root.mkdir()
    Store(root).init()
    store = Store(root)
    sec = Secretary("M", root=root, store=store)
    assert sec.roster_add(owner="t-000001", role="D", task_id="t-000002",
                          brief="E10 夹具：名册上的一项")["problem"] == ""
    with store.tx("tasks", actor="test", note="E10 roster fixture") as tx:
        tx.upsert("tasks", _row("t-000001", role="M", parent=None, depth=1,
                                status="done"), note="顶趟")
        tx.upsert("tasks", _row("t-000002", role="D", parent="t-000001", depth=2,
                                status="running"), note="在飞")
    return root


def _fallback_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """没有名册、但有带父代理行的工作区 ⇒ `roster_face` 走台账兜底那一档。

    这一档是 `RosterNode.registered` 唯一的落点：名册档的节点不带那一格
    （`test_roster_registration_covers_every_path.py` 逐字写着这一点）。
    """
    root = tmp / "bare"
    root.mkdir()
    Store(root).init()
    store = Store(root)
    with store.tx("tasks", actor="test", note="E10 fallback fixture") as tx:
        tx.upsert("tasks", _row("t-000001", role="M", parent=None, depth=1,
                                status="done"), note="顶趟")
        tx.upsert("tasks", _row("t-000002", role="D", parent="t-000001", depth=2,
                                status="running"), note="子")
    return root


# ====================================================================== 声明那一侧
def _declared(interface: str) -> tuple[set[str], set[str]]:
    """`_TS_TYPES` 里某个接口的 `(必填键, 可选键)`。"""
    fields = next((fields for name, _why, fields in R._TS_TYPES if name == interface),
                  None)
    assert fields is not None, f"`_TS_TYPES` 里没有 {interface}（判据失去对象）"
    required: set[str] = set()
    optional: set[str] = set()
    for field, _type in fields:
        if field.endswith("?"):
            optional.add(field[:-1])
        else:
            required.add(field)
    return required, optional


def _union(rows: Any) -> set[str]:
    """一栏里所有行的键的并集（空栏 ⇒ 空集）。

    取键口径与 `tests/test_webui_contracts.py` 的 `_rows_union` 逐字相同：
    不许只看第一行 —— E4 的 `max` 就是那么漏掉的。
    """
    if not isinstance(rows, list):
        return set()
    return {str(key) for row in rows if isinstance(row, dict) for key in row}


# ====================================================================== ① 后端 → 声明
def test_every_key_the_backend_really_gives_is_declared(tmp_path: pathlib.Path) -> None:
    """①：后端真给出的键，`_TS_TYPES` 每一个都声明了（两档名册 + 缓存 active）。"""
    roster_root = _roster_workspace(tmp_path)
    roster_face = R.roster_face(roster_root)
    assert roster_face["answer"] == "ok", (roster_face["answer"], roster_face["reason"])
    roster_nodes = roster_face["nodes"]
    assert roster_nodes, "名册档一个节点都没读出来 ⇒ 这一档没有落脚点"

    fallback_face = R.roster_face(_fallback_workspace(tmp_path))
    assert fallback_face["answer"] == "unknown", fallback_face["reason"]
    fallback_nodes = fallback_face["nodes"]
    assert fallback_nodes, "台账兜底档一个节点都没读出来 ⇒ `registered` 没有落脚点"

    # 两档的节点形状不同，而 `RosterNode` 是同一个接口 ⇒ 键集取两者的并集。
    node_keys = _union(list(roster_nodes) + list(fallback_nodes))
    required, optional = _declared("RosterNode")
    problems: list[str] = []
    missing = sorted(node_keys - required - optional)
    if missing:
        problems.append(
            f"RosterNode：后端给得出这些键，types.ts 没有声明 {missing}"
            f"（名册档 {sorted(_union(roster_nodes))}；"
            f"兜底档 {sorted(_union(fallback_nodes))}）")

    # `registered` 只出现在兜底档：这一格是 E10 那一条的落点，单独点名。
    for node in fallback_nodes:
        if "registered" not in node:
            problems.append(
                f"台账兜底档的节点 {node.get('task_id')} 没带 `registered`"
                "（这一档每一行都要有它，不是只有第一行）")

    # `/api/cache` 的 `active` 那一格（`cacheface.handle_cache_status` 的 data.active）。
    cache = cachectl.status(root=roster_root)
    active = cache.get("active")
    assert isinstance(active, dict) and active, "`cachectl.status()` 没给 active 读数"
    cache_required, cache_optional = _declared("CacheActive")
    cache_missing = sorted(set(active) - cache_required - cache_optional)
    if cache_missing:
        problems.append(
            f"CacheActive：后端给得出这些键，types.ts 没有声明 {cache_missing}"
            f"（active 的全部键 {sorted(active)}）")
    assert not problems, "\n".join(problems)


# ====================================================================== ② 声明 → 后端
def test_no_declared_key_is_missing_from_the_readings(tmp_path: pathlib.Path) -> None:
    """②：声明成必填的键，后端一定给得出（反向漂移：types.ts 凭空多一格）。"""
    roster_nodes = R.roster_face(_roster_workspace(tmp_path))["nodes"]
    node_keys = _union(list(roster_nodes))
    required, optional = _declared("RosterNode")
    absent = sorted(required - node_keys)
    assert not absent, (
        f"RosterNode：types.ts 声明成必填、而名册档的节点上读不出 {absent}"
        f"（可选的那几格可以缺席：{sorted(optional)}）")

    cache = cachectl.status(root=tmp_path / "ws")
    active = cache.get("active") or {}
    cache_required, cache_optional = _declared("CacheActive")
    cache_absent = sorted(cache_required - set(active))
    assert not cache_absent, (
        f"CacheActive：types.ts 声明成必填、而 `/api/cache` 的 active 读不出 "
        f"{cache_absent}（可选的那几格可以缺席：{sorted(cache_optional)}）")


# ====================================================================== ③ 并集负控
def test_the_key_census_takes_the_union_of_every_row() -> None:
    """③ 负控：第二行才出现的键必须被看见（只看第一行就会漏掉它）。

    这条不碰盘：它证明的是"取键是并集"这件事本身。改前 E4 的形态是
    `set(rows[0])` —— 同一个函数、同一批夹具，只是少看了后面的行。
    """
    from tests.test_webui_contracts import _rows_union

    rows = [{"id": "C1", "kind": "k", "min": 0},
            {"id": "C3", "kind": "k", "max": 0}]
    assert _rows_union(rows) == {"id", "kind", "min", "max"}, _rows_union(rows)
    # 反负控（正控的镜像）：只看第一行的那份实现必须漏掉 `max`。
    first_row_only = {str(key) for key in rows[0]}
    assert "max" not in first_row_only, "夹具坏了：第一行不该有 max"
    assert "max" in _rows_union(rows), "取键不是并集 ⇒ 第二行才出现的键被漏掉了"


# ====================================================================== 页面那一半
def test_the_page_really_reads_the_two_new_cells() -> None:
    """前端那一半：两格至少要让页面能显示（或明确标注"暂不显示"，见各自的注释）。"""
    roster = ROSTER_TSX.read_text(encoding="utf-8")
    assert "node.registered" in roster, (
        "Roster.tsx 没读 `node.registered` ⇒ 台账兜底档与名册档在页面上仍然长得一样")
    cache = PROMPT_CACHE_TSX.read_text(encoding="utf-8")
    assert "active.key" in cache or "active.key" in cache.replace(" ", ""), (
        "PromptCache.tsx 没读 `active.key` ⇒ 换 key 的读数在页面上仍然看不见")
