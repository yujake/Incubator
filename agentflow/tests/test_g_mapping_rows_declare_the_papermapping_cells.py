# -*- coding: utf-8 -*-
"""`G.write_mapping` 的 `rows` 声明面必须盖住 `papermapping` 判据要求的每一格。

## 这一条守什么

`specs/g.py` 的 `ACTIONS` 是 M 的派活面（`capabilities.CAPABILITIES` 由它派生），
而 `papermapping` / `numericproof` 的判据在写表时逐格核。两边一旦不同步，形态不是
报错而是"侥幸能跑"：JSON-Schema 的 `additionalProperties` 默认放行没声明的那几格，
于是**派活面看不见它们，判据却要求它们** —— M 会派出一张必然被工具层拒收的表。

## 判据的来源（现读，不手抄清单）

| 来源 | 贡献的格 |
|---|---|
| `papermapping.ROW_FIELDS` | 每行无条件必填的六格 |
| `papermapping.NUMERIC_ROW_FIELDS`（= `numerictheorem.NUMERIC_ROW_FIELDS`） | 数值实验定理那两格 |
| `papermapping.LEAN_ROW_FIELDS` | 机器核验凭据那两格 |
| `numericproof.INDEX_*_FIELD` | 索引四格（列义只有这一份，没有元组可读） |

`papermapping` 以后加一格（或改它的必填口径），这里不用改断言就跟着变 —— 判据读的是
它的判据来源，不是一份抄过来的名单。

## `required` 的取舍

无条件必填的只有 `ROW_FIELDS` 那六格（与工具层 `_MAPPING_ROW_PARAMS["required"]`
同一份口径）；凭据两格按证明通道、数值两格与索引四格按行的种类条件必填 —— 这些由
读侧判，**不进 `required`**（一律 required 会把"不适用"读成"没填"）。

## 反向（反真空）

摘掉 `lean_file` 这一格声明 ⇒ 第一条判据必须红。只写"覆盖"不写这一条，
一份把 `criteria` 读成空集的实现也能永远绿。
"""
from __future__ import annotations

import copy
import dataclasses
from typing import Mapping

import pytest

from agentflow import capabilities as C
from agentflow import numericproof as NP
from agentflow import papermapping as PM

#: 本判据补进声明的那几格（描述文字要逐格写清；判据来源那一张表在 `_criteria_cells()`）。
_NEW_CELLS: tuple[str, ...] = (
    "file", "lean_file", "lean_target",
    "evidence_kind", "evidence_path", "evidence_sha256", "v_signature",
)

#: `file` 的两种落点、`lean_file` 的两类凭据、`lean_target` 只属于 formal ——
#: 这几句必须写在描述里（派活面只读 schema，不读 `specs/g.py` 的注释）。
_DESCRIPTION_NEEDLES: dict[str, tuple[str, ...]] = {
    "file": ("论文包内", "仓库根"),
    "lean_file": (".py", ".lean"),
    "lean_target": ("formal",),
}


def _write_mapping_spec(table: Mapping[str, tuple] | None = None):
    """`G.write_mapping` 的动作声明（从派活面现读）。"""
    specs = C.CAPABILITIES if table is None else table
    for spec in specs.get("G", ()):
        if spec.action == "write_mapping":
            return spec
    raise AssertionError("动作表里没有 `G.write_mapping` —— 判据自己接错了，不是通过")


def _row_item(params: Mapping | None) -> dict:
    """`rows` 的 `items` 声明（读不出来 ⇒ 判据自己接错了，不是通过）。"""
    rows = (params or {}).get("properties", {}).get("rows")
    assert isinstance(rows, dict), f"`rows` 读不出来：{rows!r}"
    item = rows.get("items")
    assert isinstance(item, dict), f"`rows.items` 读不出来：{item!r}"
    return item


def _declared_cells(params: Mapping | None) -> set[str]:
    """动作面声明了的格：`properties` 里写出来的 ∪ `required` 里点名的。

    为什么 `required` 也算：JSON Schema 里 `required` 点了名的键，派活面读得到那个名字
    （只是没有类型）；本判据要防的是"一格名字都不出现"的格子。
    """
    item = _row_item(params)
    props = item.get("properties") or {}
    required = item.get("required") or ()
    return set(props) | set(required)


def _criteria_cells() -> set[str]:
    """判据要求的格 —— 从 `papermapping` / `numericproof` 的判据来源现读。"""
    return (
        set(PM.ROW_FIELDS)
        | set(PM.NUMERIC_ROW_FIELDS)
        | set(PM.LEAN_ROW_FIELDS)
        | {
            NP.INDEX_KIND_FIELD,
            NP.INDEX_PATH_FIELD,
            NP.INDEX_SHA_FIELD,
            NP.INDEX_SIGN_FIELD,
        }
    )


def _assert_declares_every_criteria_cell(table: Mapping[str, tuple] | None = None) -> None:
    """判据本体：动作面声明的 rows 格 ⊇ 判据要求的格（空集不算通过）。"""
    criteria = _criteria_cells()
    assert criteria, "判据来源读成空集 ⇒ 这一条是真空通过（不是通过）"
    assert set(PM.ROW_FIELDS) <= criteria, (
        f"判据来源自己的口径变了：ROW_FIELDS {sorted(PM.ROW_FIELDS)} 不在 {sorted(criteria)} 里"
    )
    assert len(criteria) > len(PM.ROW_FIELDS), (
        "判据来源里只剩无条件必填那六格 ⇒ 条件必填那几格的来源读漏了（不是通过）"
    )
    spec = _write_mapping_spec(table)
    declared = _declared_cells(spec.params)
    missing = sorted(criteria - declared)
    assert not missing, (
        f"`G.write_mapping` 的 `rows` 声明漏了判据要求的格：{missing}。\n"
        f"  判据要求：{sorted(criteria)}\n"
        f"  动作面声明：{sorted(declared)}\n"
        "这些格现在靠 JSON-Schema 的 `additionalProperties` 默认放行 —— 能跑，"
        "但 M 的派活面看不见它们，派活与判据脱节。"
    )


def _capability_table_without(spec, cell: str) -> dict[str, tuple]:
    """把某一格从动作声明里摘掉的那张表（不动真身：深拷贝 + 只换这一条 spec）。"""
    params = copy.deepcopy(dict(spec.params))
    props = _row_item(params)["properties"]
    assert cell in props, f"负控前提不成立：`{cell}` 本来就不在 properties 里"
    props.pop(cell)
    doctored = dataclasses.replace(spec, params=params)
    table = dict(C.CAPABILITIES)
    table["G"] = tuple(doctored if s is spec else s for s in table["G"])
    return table


# ============================================================ a 覆盖（红 → 绿）


def test_the_rows_declaration_covers_every_cell_the_mapping_criteria_require() -> None:
    """① 动作面声明的行格 ⊇ 判据要求的行格（来源现读，见模块 docstring）。"""
    _assert_declares_every_criteria_cell()


def test_the_new_cells_carry_descriptions_the_dispatch_surface_can_read() -> None:
    """①的附带：新补的格必须带描述 —— 类型名说不清"两种落点 / 两类凭据"。"""
    props = _row_item(_write_mapping_spec().params).get("properties") or {}
    for cell in _NEW_CELLS:
        face = props.get(cell)
        assert isinstance(face, dict), f"`{cell}` 没有声明（`properties` 里读不到）"
        text = str(face.get("description") or "").strip()
        assert text, f"`{cell}` 没有描述 ⇒ 派活面只看到类型名，看不到这一格该填什么"
    for cell, needles in _DESCRIPTION_NEEDLES.items():
        text = str((props.get(cell) or {}).get("description") or "")
        for needle in needles:
            assert needle in text, (
                f"`{cell}` 的描述里缺 {needle!r} —— 这一格有两种落点/两类凭据，"
                f"写漏一种就会把合规的那一行判成错。描述原文：{text!r}"
            )


# ============================================================ b 反向（摘掉 lean_file ⇒ 红）


def test_removing_the_lean_file_declaration_turns_the_criterion_red() -> None:
    """② 反真空：从 ACTIONS 里摘掉 `lean_file` 这一格 ⇒ ① 必红；放回 ⇒ 又绿。

    只写 ① 不写这一条，"判据读成空集"与"动作面真的覆盖了"分不开。
    """
    live = _write_mapping_spec()
    doctored = _capability_table_without(live, "lean_file")
    with pytest.raises(AssertionError) as excinfo:
        _assert_declares_every_criteria_cell(doctored)
    assert "lean_file" in str(excinfo.value), str(excinfo.value)
    # 放回现场那一份 ⇒ 又绿：红只能是那一格造成的，不是负控把表弄坏了。
    _assert_declares_every_criteria_cell()


# ============================================================ d required 的取舍


def test_only_the_unconditional_cells_are_required() -> None:
    """③ `required` 只放无条件必填那六格；按通道/按落点条件必填的格不许一律 required。

    一律 required 会把"这一格不适用"读成"这一格没填"（凭据两格在空通道就是这一档），
    所以条件必填的那几格只进 `properties`，由读侧按证明通道与行的种类判。
    """
    spec = _write_mapping_spec()
    required = set(_row_item(spec.params).get("required") or ())
    criteria = _criteria_cells()
    conditional = criteria - set(PM.ROW_FIELDS)
    assert conditional, "反真空：条件必填格读成空集 ⇒ 这一条没在核东西"
    assert required == set(PM.ROW_FIELDS), (
        f"`rows.items.required` 应为无条件必填六格 {sorted(PM.ROW_FIELDS)}，"
        f"实际 {sorted(required)}（条件必填格 {sorted(conditional)} 不许写进 required）"
    )
    assert not (required & conditional), sorted(required & conditional)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
