# -*- coding: utf-8 -*-
"""判据：收工门的说明书（模块 docstring 那张表）与门的实现（`DEFAULT_CHECKS`）逐条一致。

## 这一份守什么（R-BE1 的 ③-8，2026-10-27）

`closing.py` 的模块 docstring 用一张表说"八格各判什么"。改前那张表只有七行 —— 少了
`acceptance` 一格，而没有任何判据会红：门的实现与门的说明书各说八格里的七格。
这一条从 docstring 里现扫表行（反引号里的那一格名字），与 `DEFAULT_CHECKS` 对拍。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① 逐条同序 | 表里的格名序列 == `DEFAULT_CHECKS` | 加一格只改实现、说明书留在七格 |
| ② 反真空 | 表至少扫出 `len(DEFAULT_CHECKS)` 行（扫不到就红，不是"空表也一致"） | 表格被换成散文 ⇒ 判据静默通过 |
"""
from __future__ import annotations

import re

from agentflow import closing as CL

#: 表行形如 `| \`paper\` | … |`（第一列是被反引号包住的格名）。
_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|", re.M)


def _documented_cells() -> list[str]:
    return _ROW.findall(CL.__doc__ or "")


def test_the_docstring_table_lists_every_cell_in_order() -> None:
    """说明书那张表的格名序列必须与 `DEFAULT_CHECKS` 逐条相同（同序）。"""
    documented = _documented_cells()
    assert documented, "模块 docstring 里一格都没扫到（表格被删/被改成散文了）"
    assert documented == list(CL.DEFAULT_CHECKS), (
        "说明书与实现分家了：docstring 表里是 "
        f"{documented}，`DEFAULT_CHECKS` 是 {list(CL.DEFAULT_CHECKS)}")


def test_the_table_is_not_vacuous() -> None:
    """反真空：扫出来的行数必须等于八格的数量（扫不到 ≠ 一致）。"""
    assert len(_documented_cells()) == len(CL.DEFAULT_CHECKS) >= 8, (
        len(_documented_cells()), len(CL.DEFAULT_CHECKS))
