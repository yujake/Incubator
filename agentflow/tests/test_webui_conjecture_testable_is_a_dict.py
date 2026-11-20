# -*- coding: utf-8 -*-
"""判据：猜想的 `testable` 是 dict，不是 `boolean | null`（渲染与类型生成源两处都改）。

## 改前是什么样（`draft/187` P2-1 / A1 的现场读数）

`/api/evidence` 的 13 条 `conjectures[].testable` 真值是对象（本次 13/13 都是 `{}`），
而页面写的是 `String(r.testable)` ⇒ 13 行全是 `[object Object]`。
类型侧同错：`ui/src/types.ts` 声明 `testable: boolean | null`，生成源
`webui/readers.py` 的 `_TS_TYPES` 也写 `("testable", "boolean | null")` —— 所以 `tsc`
不可能报这个错。真身在 `schema.py` 的 `Conjecture.testable: dict`
（`{"params", "bounds", "why"}`）。

## 三条

1. 后端读数：`evidence_chain` 原样带回 dict（这一层只搬运，不许把它折成布尔）；
2. 类型生成源：`readers.type_decls()` 里 `ConjectureRow.testable` 是
   `Record<string, unknown>`，且 `ui/src/types.ts` 是它的最新生成物（逐字节）；
3. 渲染：`Evidence.tsx` 不再 `String(r.testable)`，走 `cell()`（对象 ⇒ JSON）。

反真空：把声明打桩回 `boolean | null` / 把渲染打桩回 `String(...)` ⇒ 检查函数必须报红。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from agentflow.web import emit_types
from agentflow.webui import readers as R

REPO = pathlib.Path(__file__).resolve().parents[1]
TYPES_TS = REPO / "ui" / "src" / "types.ts"
EVIDENCE_TSX = REPO / "ui" / "src" / "pages" / "Evidence.tsx"


def _strip_comments(text: str) -> str:
    """剥掉块注释与整行 `//` 注释（源码里解释「改前是 String(...)」的那几句不算实现）。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _interface_body(text: str, name: str) -> str:
    m = re.search(r"export interface " + name + r" \{(.*?)\n\}", text, re.S)
    return "" if m is None else m.group(1)


def _decl_problems(decl: str) -> list[str]:
    """纯函数（可负控）：生成源里 `testable` 的声明类型对不对。"""
    body = _interface_body(decl, "ConjectureRow")
    if body == "":
        return ["`type_decls()` 里没有 ConjectureRow"]
    m = re.search(r"^\s{2}testable:\s*([^;]+);", body, re.M)
    if m is None:
        return ["ConjectureRow 里没有 `testable` 那一格"]
    got = m.group(1).strip()
    if got == "boolean | null":
        return ["`testable` 仍声明成 `boolean | null` —— 真身是 dict，`tsc` 抓不到 String()"]
    if "Record<string, unknown>" not in got:
        return [f"`testable` 声明是 {got!r}（应为 Record<string, unknown>）"]
    return []


def _render_problems(source: str) -> list[str]:
    """纯函数（可负控）：页面渲染那一格有没有再用 `String(...)`。"""
    code = _strip_comments(source)
    problems: list[str] = []
    if "String(r.testable)" in code:
        problems.append("Evidence.tsx 仍然 `String(r.testable)` ⇒ 对象会印 [object Object]")
    if "cell(t)" not in code and "cell(r.testable)" not in code:
        problems.append("Evidence.tsx 的 testable 那一格没有走 `cell()`（对象 ⇒ JSON）")
    return problems


# ====================================================================== 1 后端读数
def test_the_backend_returns_the_dict_as_a_dict(tmp_path: pathlib.Path) -> None:
    """`evidence_chain` 原样带回 dict（不折成布尔、不折成空串）。"""
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    row = {"conjecture_id": "c0001", "statement": "断定", "status": "testing",
           "form": "universal", "testable": {"params": ["n"], "bounds": "n>=1",
                                             "why": "可枚举"},
           "origin": "statements:000001"}
    (root / "data" / "conjectures.json").write_text(
        json.dumps({"schema_version": 2, "rows": [row]}, ensure_ascii=False), encoding="utf-8")
    rows = R.evidence_chain(root)["conjectures"]
    assert len(rows) == 1, rows
    assert isinstance(rows[0]["testable"], dict), rows[0]["testable"]
    assert rows[0]["testable"]["why"] == "可枚举", rows[0]["testable"]


# ====================================================================== 2 类型生成源
def test_the_type_generator_says_the_truth_and_the_product_is_fresh() -> None:
    """生成源声明 `Record<string, unknown>`；`types.ts` 是它的最新生成物。"""
    decl = R.type_decls()
    assert _decl_problems(decl) == [], _decl_problems(decl)
    assert TYPES_TS.is_file(), f"{TYPES_TS} 不在盘上"
    fresh = emit_types.render_types()
    assert TYPES_TS.read_text(encoding="utf-8") == fresh, (
        "ui/src/types.ts 不是最新的生成物：跑 `python -B -m agentflow.web.emit_types`")
    # 反真空：把声明打桩回改前那一份 ⇒ 检查函数必须报红。
    old = decl.replace("testable: Record<string, unknown>;", "testable: boolean | null;")
    assert old != decl, "负控没改到声明"
    assert _decl_problems(old), "检查函数对旧的 boolean|null 声明没报红"


# ====================================================================== 3 渲染
def test_the_page_renders_an_object_as_json_not_as_string() -> None:
    """页面那一半：不再 `String(r.testable)`；负控能抓住退回旧写法。"""
    source = EVIDENCE_TSX.read_text(encoding="utf-8")
    assert _render_problems(source) == [], _render_problems(source)
    planted = source.replace("cell(t)", "String(t)", 1)
    assert planted != source, "负控没改到源码"
    assert _render_problems(planted + "\nconst bad = String(r.testable);\n"), \
        "检查函数对 `String(r.testable)` 没报红"
