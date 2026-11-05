# -*- coding: utf-8 -*-
"""判据：`table.list` / `table.search` 的声明要写出「给了投影时 meta 多一格」。

## 现场（2026-11-05 审查 D1 / D2）

投影（`table.list` 的 `fields` / `table.search` 的 `select`）已经实现，但两件的
`returns=` 仍只写 data 的键与旧的 meta 读数：调用方按声明读返回值时看不到
「这一页是按哪几个键投影的」这格读数。实现里那两格是条件出现的：

- `table.list`：返回的 meta 里按条件展开 `fields` 那一格；
- `table.search`：返回的 meta 里按条件展开 `select` 那一格；

于是「不给投影」时 meta 里根本没有这一格 —— 不是空串、不是 `None`。

## 判据

a. 声明读到「给了 `fields`（/`select`）时 meta 多一格」，实测：给投影 ⇒ meta 有那一格
   且等于请求的字段名；不给 ⇒ 那一格不在 meta 里（不是 `""`）；
b. 反真空：把实现里的那一格摘掉而声明不动 ⇒ a 必红（声明与实测分家必须被看见）。
"""
from __future__ import annotations

import copy
import dataclasses
from typing import Any, Mapping

import pytest

from agentflow.store import Store
from agentflow.tools import build_registry

import test_table_list_projects_fields as BASE

#: 两件工具各自的「投影参数名」与「meta 读数格名」（同一件事，名字不同）。
CASES: tuple[tuple[str, str], ...] = (
    ("table.list", "fields"),
    ("table.search", "select"),
)

#: 声明里必须逐字出现的那句（`returns=` 是给人读的契约；实现是另一侧）。
NEEDLE = "meta 多一格 `{cell}`"


@pytest.fixture()
def reg(tmp_path):
    ws = BASE._ws(tmp_path / "ws")
    return build_registry(store=Store(ws), workspace_root=ws).registry


def _call(reg, tool: str, *, projected: bool) -> Any:
    """走真的工具面：`projected=True` 给投影，`False` 与改前的默认路径逐字相同。"""
    if tool == "table.list":
        kwargs = {"table": "statements", "fields": BASE.FIELDS} if projected else {
            "table": "statements"}
    else:
        kwargs = {"table": "statements", "query": "引理"}
        if projected:
            kwargs["select"] = BASE.FIELDS
    got = reg.call(tool, role="B", **kwargs)
    assert got.ok, (tool, got.error, got.meta)
    return got


def _problems(reg) -> dict[str, list[str]]:
    """两件工具各一条：声明那一句 + 实测那两档（给 / 不给）。"""
    out: dict[str, list[str]] = {tool: [] for tool, _ in CASES}
    for tool, cell in CASES:
        needle = NEEDLE.format(cell=cell)
        returns = getattr(reg.get(tool), "returns", "") or ""
        if needle not in returns:
            out[tool].append(f"{tool} 的 returns 没写 {needle!r}")
        with_projection = _call(reg, tool, projected=True)
        if list(with_projection.meta.get(cell) or []) != list(BASE.FIELDS):
            out[tool].append(
                f"{tool} 给了投影，meta[{cell!r}] = {with_projection.meta.get(cell)!r}"
                f"，不是请求的 {list(BASE.FIELDS)!r}")
        without = _call(reg, tool, projected=False)
        if cell in without.meta:
            out[tool].append(
                f"{tool} 没给投影，meta 里仍有 {cell!r}={without.meta.get(cell)!r}"
                " —— 「没有这一格」不许写成空串")
        if without.meta.get(cell) == "":
            out[tool].append(f"{tool} 没给投影，meta[{cell!r}] 是空串（那是冒充）")
    return out


def test_a_the_declaration_says_the_projection_meta_cell_and_the_tool_does_it(reg) -> None:
    """a：声明读到那一句，实测给投影有、不给就没有（不是空串）。"""
    bad = {tool: items for tool, items in _problems(reg).items() if items}
    assert not bad, "\n".join(f"[{tool}] {one}"
                              for tool, items in bad.items() for one in items)


@pytest.mark.parametrize("tool,cell", CASES)
def test_b_dropping_the_meta_cell_from_the_implementation_turns_it_red(
        reg, tool: str, cell: str) -> None:
    """b（反真空）：实现里摘掉那一格、声明不动 ⇒ 判据红；放回 ⇒ 又绿。

    打桩只摘 meta 那一格（不碰 data / 声明），红的必须就是「声明说有、实测没有」。
    """
    assert _problems(reg)[tool] == []

    real = reg.get(tool)
    handler = real.handler

    def stripped(**kwargs):
        result = handler(**kwargs)
        result.meta.pop(cell, None)
        return result

    doctored = copy.copy(reg)
    doctored._specs = dict(reg._specs)  # noqa: SLF001 —— 判据只替换这一件，不动别的
    doctored._specs[tool] = dataclasses.replace(real, handler=stripped)
    assert _problems(doctored)[tool], (
        f"把 {tool} 的 meta[{cell!r}] 摘掉后判据仍全绿 ⇒ 它没有真的在读实现")
