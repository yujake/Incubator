# -*- coding: utf-8 -*-
"""判据：收工门的说明书（模块 docstring 那张表）与门的实现（`DEFAULT_CHECKS`）逐条一致。

## 这一份守什么（R-BE1 的 ③-8，2026-10-27）

`closing.py` 的模块 docstring 用一张表说"八格各判什么"（2026-11-14：`paper` 退出收工判定）。改前那张表只有七行 —— 少了
`acceptance` 一格，而没有任何判据会红：门的实现与门的说明书各说八格里的七格。
这一条从 docstring 里现扫表行（反引号里的那一格名字），与 `DEFAULT_CHECKS` 对拍。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① 逐条同序 | 表里的格名序列 == `DEFAULT_CHECKS` | 加一格只改实现、说明书留在七格 |
| ② 反真空 | 表至少扫出 `len(DEFAULT_CHECKS)` 行（扫不到就红，不是"空表也一致"） | 表格被换成散文 ⇒ 判据静默通过 |
| ③ 那一行说的判据 | `artifact_ledger` 那一行的结局词与 D9 的收窄一致（只有 `changed` ⇒ `pass` + warning） | 格名对得上、而那一行说的是 `unknown` —— 改前就是这一形态 |
"""
from __future__ import annotations

import re

from agentflow import closing as CL

#: 表行形如 `| \`paper\` | … |`（第一列是被反引号包住的格名）。
_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|", re.M)

#: `artifact_ledger` 那一行的正文（第一列之后的全部）。
_ARTIFACT_ROW = re.compile(r"^\|\s*`artifact_ledger`\s*\|(.*)\|\s*$", re.M)


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
    assert len(_documented_cells()) == len(CL.DEFAULT_CHECKS) == 8, (
        len(_documented_cells()), len(CL.DEFAULT_CHECKS))


def test_the_artifact_ledger_row_does_not_contradict_d9() -> None:
    """③ 说明书那一行的结局词必须与 D9 的收窄一致：只有 `changed` ⇒ `pass` + warning。

    为什么这一条要单独钉：①② 只核"有没有这一行、顺序对不对"，不核那一行说的判据。
    改前 `artifact_ledger` 那一行写的是「只有 `changed` ⇒ `unknown`」，而实现
    （`_check_artifact_ledger`，D9 业主 2026-10-09 裁"收窄"）与读数自己的 note
    （`artifact_ledger_reading`）都说 `pass` + warning —— 同一份判据两个口径。
    这一格的方向是"unknown 会让任何有派活的跑批都收不了工"（真机 t1u 的 23 条
    `changed` 全是框架自己幂等重写的 `out/tasks/*.json`）。行为那一半已有判据
    （`test_closing_gate.py` 的那条 `artifact_ledger` 测试），这里把说明书那一半
    钉在同一处口径上 —— 两处分家的形态是"判据绿、说明书写反"，没有任何一格会红。
    """
    rows = _ARTIFACT_ROW.findall(CL.__doc__ or "")
    assert len(rows) == 1, f"`artifact_ledger` 那一行扫到 {len(rows)} 次 ⇒ 这一格没查成"
    row = rows[0]
    assert "`pass`" in row, f"说明书没写这一档的结局是 `pass`：{row}"
    assert "`unknown`" not in row, (
        "说明书还在说 `changed` ⇒ `unknown`，而实现与 `artifact_ledger_reading` 的 note "
        f"都说 `pass` + warning（D9 的收窄）：{row}")
