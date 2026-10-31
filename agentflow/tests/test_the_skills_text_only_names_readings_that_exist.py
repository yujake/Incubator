# -*- coding: utf-8 -*-
"""判据：手册不许把「stats 的读数」说成收工那一步能拿到的（2026-11-03，153-U-11）。

## 背景

`agent_skills.py` 里 M 那一岗的 skill 正文（模型现做现读的那一份）曾写：

    ## 收尾还有一格：未闭环提醒是你秘书列的

    收工那一步（`conductor.closing`）与 `conductor.ledger(view="stats")` 的
    `stats.closure_reminders` 不是统计，是点名：……

而 `closure_reminders` 全仓只有一个产出点：`Conductor.stats()`
（`conductor.py:9371`，值来自 `_closure_reading`）。`conductor.closing` 的返回
（`ClosingReport.to_dict()`，12 个键）里没有它 —— 所以这句话教模型去一个不存在的面上
找一个不存在的格。模型照着找不到，只会得出"这一格没有东西"。

## 这条判据钉住什么

1. 点名 `conductor.closing` 的那一行里，不许出现 `stats.<键>` —— 那是在把 stats 的读数
   挂到 closing 名下（今天红）。要提 stats 的读数，单独起一句，别和 closing 写在同一行。
2. 两个面的键集必须真的不同（反真空：若哪天 closing 真的补上了 `closure_reminders`，
   第 1 条就变成在禁止一句真话 ⇒ 那时应当删掉这条判据，而不是把它放宽）。
3. 那句提醒本身不许被删掉（只删话不改指向 = 把"未闭环提醒"这一格从手册里抹掉）：
   正文里必须仍有一行同时点名 `conductor.ledger` 与 `stats.closure_reminders`。

键集从代码里现读（AST 取 `ClosingReport.to_dict()` 与 `Conductor.stats()` 的字典字面量），
不手抄 —— 手抄的键集就是下一条不一致。
"""
from __future__ import annotations

import ast
import pathlib
import re

from agentflow import agent_skills as AS

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
CLOSING = _SRC / "closing.py"
CONDUCTOR = _SRC / "conductor.py"

#: 正文里"某个面上的一格"的写法：`stats.<键>`。
_STATS_REF = re.compile(r"stats\.([A-Za-z_][A-Za-z0-9_]*)")


def _dict_keys(path: pathlib.Path, class_name: str, method_name: str) -> set[str]:
    """类里某个方法返回的那个字典字面量的键集（现读，不手抄）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for cls in ast.walk(tree):
        if not (isinstance(cls, ast.ClassDef) and cls.name == class_name):
            continue
        for fn in cls.body:
            if not (isinstance(fn, ast.FunctionDef) and fn.name == method_name):
                continue
            keys: set[str] = set()
            for node in ast.walk(fn):
                if isinstance(node, ast.Dict):
                    for key in node.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            keys.add(key.value)
            return keys
    raise AssertionError(f"{path.name} 里找不到 {class_name}.{method_name}（判据的对象没了）")


CLOSING_KEYS = _dict_keys(CLOSING, "ClosingReport", "to_dict")
STATS_KEYS = _dict_keys(CONDUCTOR, "Conductor", "stats")

#: 只在 stats 里有、closing 的返回里没有的那些格 —— "挂错面"说的就是它们。
STATS_ONLY = STATS_KEYS - CLOSING_KEYS


def _body_lines():
    """(角色, skill, 行号, 正文行) —— 逐条 skill 正文（不是源码行）。"""
    for owner, skills in AS.CATALOG.items():
        for skill in skills:
            for lineno, line in enumerate(skill.body.splitlines(), 1):
                yield owner, skill.slug, lineno, line


def test_the_two_faces_really_have_different_keys() -> None:
    """反真空：这条判据的前提今天必须成立（closing 没有 `closure_reminders`）。"""
    assert len(CLOSING_KEYS) >= 8, f"closing 的返回只剩 {len(CLOSING_KEYS)} 格 ⇒ 判据在扫空集"
    assert len(STATS_KEYS) >= 8, f"stats 只有 {len(STATS_KEYS)} 格 ⇒ 判据在扫空集"
    assert "closure_reminders" in STATS_KEYS, "stats 里没有 closure_reminders ⇒ 判据前提过期"
    assert "closure_reminders" not in CLOSING_KEYS, (
        "`closing` 现在真的有 `closure_reminders` 了 ⇒ 第 1 条会开始禁止一句真话："
        "请删掉这条判据（并同步手册），不是把它放宽")


def test_no_skill_line_hands_a_stats_reading_to_the_closing_call() -> None:
    """① 点名 `conductor.closing` 的那一行里不许出现 stats 独有的格（今天红）。"""
    offenders = []
    for owner, slug, lineno, line in _body_lines():
        if "conductor.closing" not in line:
            continue
        for hit in _STATS_REF.finditer(line):
            if hit.group(1) in STATS_ONLY:
                offenders.append(f"{owner}/{slug} 正文第 {lineno} 行：`{hit.group(0)}`"
                                 f" 只在 `Conductor.stats()` 里，`conductor.closing` 没有这一格"
                                 f"\n    {line.strip()}")
    assert not offenders, (
        "手册把 stats 的读数挂到收工那一步名下了 —— 模型会去一个不存在的面上找它：\n  - "
        + "\n  - ".join(offenders))


def test_the_closure_reminder_is_still_told_in_the_manual() -> None:
    """② 只删话不改指向 = 把"未闭环提醒"这一格从手册里抹掉（不许这样"修"）。"""
    lines = [line for _owner, _slug, _lineno, line in _body_lines()
             if "conductor.ledger" in line and "stats.closure_reminders" in line]
    assert lines, (
        "M 的手册里已经没有一句同时点名 `conductor.ledger(view=\"stats\")` 与 "
        "`stats.closure_reminders` 了 ⇒ 未闭环提醒这一格丢了（改法是删掉 closing 那半句，"
        "不是删掉整句）")
