# -*- coding: utf-8 -*-
"""判据：能力的三个源码读取器，在一个进程里每个工具模块只解析一次（2026-10-27）。

## 为什么要这条判据（它是"性能静默回退"的哨兵）

`import agentflow.capabilities` 原先会在导入期跑 `assert_capabilities()`；那一趟会问三个
"读工具源码"的读取器（`_tool_side_effects` / `_tool_param_faces` / `_tool_declared_names`），
而它们各自 `ast.parse` 每个工具模块。实测（`temp/r_be2_cap_profile.py`）：改前
`_tool_side_effects()` 被问 32 次、`_tool_param_faces()` 8 次，`ast.walk` 走 5,050,209 个
节点 ⇒ `import agentflow.capabilities` 16.9 s/进程。每一个 CLI 进程、网页进程、
每条子进程判据都要付一次。

2026-10-27 加了三个进程内缓存（AST 一份、两张结果表各一份）之后是 1.36 s/进程；
同一天业主批的 item 1 又把审计整体摘出了导入期（`run_capability_audit()` 显式调用），
所以今天导入是 ~0.1 s、显式跑一趟是 ~1.4 s。判据与结论一个字符都没改 —— 缓存的只是
"从源码字节读出来的那两张表"，摘掉的只是"谁触发"。

风险形态：这层缓存如果被谁顺手去掉，性能会静默回到 16.9 s，而没有任何判据会红
（结论一模一样）。所以这里把"解析次数"钉成判据：

1. 热跑 `assert_capabilities()` ⇒ 解析次数增量为 0（缓存还在），且命中数确实在涨
   （反真空：命中数不动说明读取器根本没被调用，那这条判据什么都没测）；
2. 负控：把 AST 缓存打桩成"永远不命中" + 清掉两张结果表 ⇒ 一趟的解析次数暴涨到
   模块数的数倍 ⇒ 上一条那种"等于 0"的断言必然红（证明哨兵有牙）；
3. 读数面：导入期那三行里带着 `AST 解析 N 次 / 缓存命中 M 次`（不新增门，只是可见）。

判据不改变任何权限面取值：`ALLOWED_EDGES` / `CAPABILITIES` / `WRITE_SETS` /
`NON_SUMMONABLE` 一个都没动。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agentflow import capabilities as C


def _tool_module_files() -> list[pathlib.Path]:
    """`_TOOL_MODULES` 里那些盘上真有的工具模块（读不到的模块本来就不解析）。"""
    base = pathlib.Path(C.__file__).resolve().parent / "tools"
    return [base / f"{name}.py" for name in C._TOOL_MODULES
            if (base / f"{name}.py").is_file()]


def _parses() -> int:
    return int(C._READER_TALLY.get("ast_parses") or 0)


def _hits() -> int:
    return int(C._READER_TALLY.get("ast_hits") or 0)


@pytest.fixture(autouse=True)
def _ensure_one_cold_run() -> None:
    """每个用例之前保证"至少跑过一趟审计"（缓存与计数才处在热态）。

    2026-10-27（item 1）：审计不再在导入期跑，这个前置条件必须显式建立 ——
    否则 `test_a_warm_rerun_parses_nothing` 会把"第一趟的解析"读成"热跑又解析了"。
    """
    if _parses() == 0:
        C.run_capability_audit(print_readings=False)


def test_the_tally_is_wired_when_the_audit_runs() -> None:
    """反真空：审计显式跑一趟时必须真的解析过东西（0 说明哨兵没接上，不是"很省"）。

    2026-10-27（item 1）：审计不再在导入期跑，所以这条判据改成"先显式跑一趟、再数"。
    它守的东西没变 —— 那个哨兵仍然必须接在 `_tool_module_ast` 上。
    """
    files = _tool_module_files()
    assert files, "一个工具模块都没找到 ⇒ 这条判据没有比对对象（不是通过）"
    C.run_capability_audit(print_readings=False)
    assert _parses() > 0, (
        "显式跑了一趟审计却一次 AST 解析都没记到 ⇒ `_READER_TALLY` 没接上 "
        "`_tool_module_ast`，这条判据现在是真空通过")
    assert _parses() <= len(files) + 2, (
        f"这一趟解析了 {_parses()} 次，而盘上只有 {len(files)} 个工具模块 ⇒ "
        "每个模块被解析了不止一次（缓存没生效或读取器绕过了 `_tool_module_ast`）")


def test_a_warm_rerun_parses_nothing() -> None:
    """主判据：热跑一趟 `assert_capabilities()` 不许再解析任何一个模块。"""
    before_parses, before_hits = _parses(), _hits()
    C.assert_capabilities()
    after_parses, after_hits = _parses(), _hits()
    assert after_parses == before_parses, (
        f"热跑又解析了 {after_parses - before_parses} 次（改前那种形态）⇒ "
        "每个 CLI 进程会多等十几秒，而判据结论一模一样")
    assert after_hits > before_hits, (
        "热跑一次缓存命中都没有 ⇒ 三个读取器这次根本没被调用，"
        "上一条的'等于 0'是真空通过（不是缓存生效）")


def test_removing_the_cache_makes_this_criterion_red(monkeypatch) -> None:
    """负控：AST 缓存永远不命中 + 两张结果表清空 ⇒ 一趟的解析次数暴涨（≥ 模块数的 2 倍）。

    这正是改前的形态：解析次数不再与"模块数"同阶，而是与"读取器被问了几次 × 模块数"
    同阶。上面那条"热跑增量为 0"在这种形态下必然红。
    """
    files = _tool_module_files()
    assert files
    real = C._tool_module_ast

    def _always_parse(path: pathlib.Path) -> ast.AST:
        """绕过缓存的那个版本（负控专用）：每次都真解析。"""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        C._READER_TALLY["ast_parses"] = _parses() + 1
        return tree

    monkeypatch.setattr(C, "_TOOL_SIDE_EFFECTS_CACHE", None)
    monkeypatch.setattr(C, "_TOOL_PARAM_FACES_CACHE", {})
    monkeypatch.setattr(C, "_tool_module_ast", _always_parse)
    before = _parses()
    try:
        C.assert_capabilities()
        delta = _parses() - before
    finally:
        # 缓存本身没问题，是打桩造成的：把真身放回去，并让它在下一趟重新读一遍源码。
        monkeypatch.setattr(C, "_tool_module_ast", real)
        monkeypatch.setattr(C, "_TOOL_SIDE_EFFECTS_CACHE", None)
        monkeypatch.setattr(C, "_TOOL_PARAM_FACES_CACHE", {})
        C.assert_capabilities()
    assert delta >= 2 * len(files), (
        f"打桩之后一趟只解析了 {delta} 次（模块 {len(files)} 个）⇒ 哨兵没有牙："
        "把缓存整个去掉，这条判据也不会红")
    # 负控跑完之后世界必须恢复成"缓存生效"那一档（否则后面的用例会看到假读数）：
    # 一趟热跑必须是 0 次新解析。
    settled = _parses()
    C.assert_capabilities()
    assert _parses() == settled, (
        f"负控恢复之后热跑又解析了 {_parses() - settled} 次 ⇒ 缓存没真的装回去")


def test_the_reading_is_printed_next_to_the_other_audit_lines() -> None:
    """读数面：审计那两行里带着解析次数与命中次数（可见、不新增门）。"""
    text = str(C._PRINT_TYPE_COVERAGE)
    assert "AST 解析" in text and "缓存命中" in text, (
        f"审计读数里没有解析次数这一格 ⇒ 静默回退看不见：{text[:120]}")
