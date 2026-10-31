# -*- coding: utf-8 -*-
"""判据：这份判据文件自己抄的工具数必须等于盘上现读（2026-11-03，153-U-14）。

## 背景

`tests/test_tools_returns_declaration.py` 是"防过期计数"的那一份判据：它把工具面规模写死在
`TOOL_COUNT` 里，新增/删除工具时那条断言会红，而不是让新工具悄悄从门下面溜过去。
可是它自己的散文里还挂着五个更早的读数：55 / 79 / 80 / 110 / 107 —— 而盘上现读是 122。
同一仓里 `docs/ROLE-SPECS-APPENDIX.md:32` 写的"122 个工具"是对的 ⇒ 两份"现读"读数
差 12–17 件，读的人没法知道该信哪一个。

## 这条判据钉住什么

1. `TOOL_COUNT` 常量 == 现读（这一条今天绿：它一直是那个对的数）；
2. 文件里每一处 `N 个工具` / `N 件`：同一行带日期（`YYYY-MM-DD`）的认作历史读数、放行；
   不带日期的必须等于现读。今天红 5 处（55 / 79 / 80 / 110 / 107）。
3. 反真空：扫到的数量必须够（>= 6 处）—— 正则失效或文件被换掉时，"零命中"不许被读成
   "没有过期计数"。

规则 2 的日期豁免不是退让：本项目对"会过期的数"的既有纪律就是"读数带日期"
（`AGENTS.md` 的禁改区理由串里那句"数字是读数不是规格"、`tests/test_skill_staleness.py`
的 `no-frozen-counts` 同族）。要写历史就写日期，要写现状就写现算。
"""
from __future__ import annotations

import pathlib
import re

TARGET = pathlib.Path(__file__).resolve().parent / "test_tools_returns_declaration.py"

#: 会过期的两种写法：`N 个工具` 与 `N 件`（后者是这个文件里"件数"的口径）。
_COUNT_CLAIM = re.compile(r"(?P<n>\d+)\s*(?:个工具|件)")

#: 带日期的读数 = 历史读数（允许与现读不同）。
_DATED = re.compile(r"20\d\d-\d\d-\d\d")


def _live_tool_count(tmp_path: pathlib.Path) -> int:
    """盘上现读：Lean 开（`tests/conftest.py` 钉的这一档）+ 真 store + 工作区根。"""
    from agentflow.store import Store
    from agentflow.tools import build_registry

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    store = Store(str(ws))
    built = build_registry(store=store, workspace_root=str(ws))
    return len(built.registry.names())


def _claims():
    """(行号, 数字, 是否带日期, 那一行) 逐条产出。"""
    for lineno, line in enumerate(TARGET.read_text(encoding="utf-8").splitlines(), 1):
        for hit in _COUNT_CLAIM.finditer(line):
            yield lineno, int(hit.group("n")), bool(_DATED.search(line)), line.strip()


def test_the_constant_equals_the_disk(tmp_path: pathlib.Path) -> None:
    """① `TOOL_COUNT` == 现读（今天绿：它是这个文件里唯一一直对的那个数）。"""
    live = _live_tool_count(tmp_path)
    text = TARGET.read_text(encoding="utf-8")
    found = re.search(r"^TOOL_COUNT = (\d+)$", text, re.M)
    assert found, "`TOOL_COUNT` 不见了 ⇒ 这份判据失去对象"
    assert int(found.group(1)) == live, (
        f"`TOOL_COUNT = {found.group(1)}` 而盘上现读 {live} ⇒ "
        "改了工具面却没改这个常量（这正是它要红的情形）")


def test_no_undated_tool_count_claim_is_stale(tmp_path: pathlib.Path) -> None:
    """② 不带日期的 `N 个工具` / `N 件` 必须等于现读（今天红 5 处）。"""
    live = _live_tool_count(tmp_path)
    claims = list(_claims())
    assert len(claims) >= 6, (
        f"只扫到 {len(claims)} 处 `N 个工具` / `N 件` ⇒ 判据在扫空集（零命中不等于没有过期计数）")
    stale = [(lineno, n, line) for lineno, n, dated, line in claims
             if not dated and n != live]
    assert not stale, (
        "这份判据文件里还有不带日期的过期读数（现读 %d 件）：\n  - "
        % live
        + "\n  - ".join(f"第 {lineno} 行写着 {n}，现读 {live}：{line[:100]}"
                        for lineno, n, line in stale)
        + "\n要么改成现算（与 `TOOL_COUNT` 同源），要么写成「YYYY-MM-DD 的读数：……」")
