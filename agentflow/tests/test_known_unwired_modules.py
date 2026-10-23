# -*- coding: utf-8 -*-
"""判据（施工单 e）：没装配的工具模块必须点名在一份可机核的清单里。

## 这一条防的是什么

`tools/__init__.py` 的 `_MODULES` 是"哪些工具模块会被装配"的唯一真身。一个
`*_tools.py` 写了、却不在那张表里，是静默的：导入不报错、判据不变红，只是那件工具
在任何一个角色的工具面上都不存在 —— 而"不存在"与"这个角色不需要它"在读数上一模一样。

施工单给的两条路是（i）挂上它（工具数 97 到 99，两份冻结快照重冻）或（ii）不挂、但把
"没接线"这件事写成可机核的清单。业主此前裁定「本轮不挂」，所以取（ii）——
本判据就是（ii）里"做成判据"那一半：清单存在、点名 `cache_tools`、且与盘上的集合相等。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | `docs/KNOWN-UNWIRED.md` 里那个机器可读区块 == 盘上没装配的 `*_tools.py` 集合 | 没有这份清单（`cache_tools` 与 `conjecture_tools` 都没点名） |
| ② | 清单里必须点名 `cache_tools`，并且它的两件工具（`cache.status` / `cache.warm`）在正文里写清 | 一句话都没有 |
| ③ | 反真空：扫描面真的扫到了模块文件；负控：清单漏一项 / 多一项都要红 | 空清单会让 ① 恒绿（真空通过） |

判据读的是清单的机器可读区块，不解析正文 —— 正文是给人读的，格式可以改。
"""
from __future__ import annotations

import pathlib
import re

import pytest

#: 仓库根（`tests/` 的上一级）。
ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 清单文件。
MANIFEST = ROOT / "docs" / "KNOWN-UNWIRED.md"

#: 机器可读区块的边界（逐行一个模块名，不带反引号、不带说明）。
BEGIN = "<!-- KNOWN-UNWIRED:BEGIN -->"
END = "<!-- KNOWN-UNWIRED:END -->"

#: 这一批必须被点名的那一个（施工单 e 的正题）。
MUST_NAME = "cache_tools"

#: 它带的工具（施工单 e 要求"点名它"，具体到能做哪两件事）。
MUST_NAME_TOOLS = ("cache.status", "cache.warm")


def _manifest_block(text: str) -> list[str]:
    """区块里逐行的模块名（区块缺失或为空 ⇒ 空清单，判据会因此红）。"""
    if BEGIN not in str(text) or END not in str(text):
        return []
    body = str(text).split(BEGIN, 1)[1].split(END, 1)[0]
    return [line.strip() for line in body.splitlines() if line.strip()]


def _tool_modules_on_disk(root: pathlib.Path = ROOT) -> set[str]:
    """盘上真的有 `*_tools.py` 的那些模块名。"""
    return {p.stem for p in (root / "src" / "agentflow" / "tools").glob("*_tools.py")}


def _wired_modules() -> set[str]:
    """装配表里的模块名（`tools._MODULES` 是唯一真身）。"""
    from agentflow.tools import _MODULES

    return set(_MODULES)


def _problems(listed: list[str], on_disk: set[str], wired: set[str]) -> list[str]:
    """① 的正文：清单与"盘上没装配的模块"两个集合对不对得上。"""
    bad: list[str] = []
    named = set(listed)
    if len(listed) != len(named):
        dupes = sorted({x for x in listed if listed.count(x) > 1})
        bad.append(f"清单里有重复项：{dupes} —— 一个模块只该占一行")
    missing = sorted((on_disk - wired) - named)
    if missing:
        bad.append(f"这些工具模块盘上有、没装配、也没在清单里点名：{missing} "
                   "（静默缺席：没有任何东西会报错）")
    stale = sorted(named - (on_disk - wired))
    if stale:
        bad.append(f"清单点了这些名字，而它们不该在这份清单里：{stale} "
                   "（要么文件不存在，要么它已经装配了 —— 过期条目会让真缺口被噪音埋掉）")
    return bad


# ============================================================ ① 清单 == 盘上集合


def test_the_known_unwired_list_matches_the_unwired_modules_on_disk() -> None:
    """① 清单与盘上的集合相等。"""
    text = MANIFEST.read_text(encoding="utf-8") if MANIFEST.is_file() else ""
    listed = _manifest_block(text)
    on_disk = _tool_modules_on_disk()
    wired = _wired_modules()
    assert len(on_disk) >= 15, (
        f"盘上只找到 {len(on_disk)} 个工具模块（下限 15）⇒ 扫描面坏了，"
        "这条判据会把「没扫到」读成「没有未接线的模块」")
    assert len(wired) >= 15, f"装配表只读到 {len(wired)} 个模块 ⇒ 读数不可信"
    bad = _problems(listed, on_disk, wired)
    assert bad == [], "\n".join(bad)


# ============================================================ ② 点名它


def test_the_list_names_cache_tools_and_its_two_tools() -> None:
    """② `cache_tools` 被点名，且正文写清它带的 `cache.status` / `cache.warm`。"""
    text = MANIFEST.read_text(encoding="utf-8") if MANIFEST.is_file() else ""
    assert text, f"清单文件读不到：{MANIFEST}"
    assert MUST_NAME in _manifest_block(text), (
        f"机器可读区块里没有 {MUST_NAME} ⇒ 施工单 e 要的那一条没有被点名")
    for tool in MUST_NAME_TOOLS:
        assert tool in text, f"清单正文里没有写 {tool} ⇒ 读的人不知道缺的是哪两件"
    # 它真的没被装配（这一条是"未接线"这个判断本身）
    assert MUST_NAME not in _wired_modules(), (
        f"{MUST_NAME} 已经挂进 `_MODULES` 了 ⇒ 清单该把它删掉，"
        "并且按施工单那一步重冻两份冻结快照（工具数 97 到 99）")
    # 模块自己的 docstring 也说了这件事（READING-MAP 指着它）
    module = __import__("agentflow.tools.cache_tools", fromlist=["_"])
    doc = str(getattr(module, "__doc__", "") or "")
    assert "KNOWN-UNWIRED" in doc, (
        "`cache_tools` 的 docstring 没提这份清单 ⇒ `docs/READING-MAP.md` 里"
        "「见该文件 docstring」那句话是假的")


# ============================================================ ③ 反真空与负控


def test_negative_control_a_missing_or_stale_entry_is_caught() -> None:
    """③ 负控：删一项 / 加一项过期条目 / 重复一项，都要红。"""
    on_disk = _tool_modules_on_disk()
    wired = _wired_modules()
    real = sorted(on_disk - wired)
    assert real, "夹具前提：盘上真的存在没装配的模块"

    # (a) 漏一项（改前的形态：什么都没有）
    bad = _problems(real[1:], on_disk, wired)
    assert bad and real[0] in bad[0], bad

    # (b) 过期条目：把一个已装配的模块写进清单
    bad = _problems([*real, sorted(wired)[0]], on_disk, wired)
    assert bad and sorted(wired)[0] in bad[0], bad

    # (c) 重复
    bad = _problems([*real, real[0]], on_disk, wired)
    assert any("重复" in one for one in bad), bad

    # 收尾：真的清单照旧全对
    assert _problems(real, on_disk, wired) == []


def test_the_manifest_bounds_are_machine_readable() -> None:
    """③ 的另一半：区块边界在位，且区块里没有多余的行（它是判据唯一的输入面）。"""
    text = MANIFEST.read_text(encoding="utf-8")
    listed = _manifest_block(text)
    assert listed, "机器可读区块是空的 ⇒ 上面那条判据是真空的"
    for name in listed:
        assert re.fullmatch(r"[a-z][a-z0-9_]*_tools", name), (
            f"区块里这一行不是模块名：{name!r}（区块只放模块名，说明写在正文里）")


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
