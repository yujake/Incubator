# -*- coding: utf-8 -*-
"""判据：活档状态表只有一个真身（2026-10-27）。

## 为什么要这条判据

"还没终态"那两档（`pending` / `running`）此前在 `conductor` 与 `secretary` 各写一份
`("pending", "running")` 字面量，外加 11 处内联（`in ("pending", "running")`）。它们今天
相等纯属巧合：那条判据没有任何一条测试钉住，而它决定的是
"这一行还算不算在跑" —— 扇出名额、活跃读数、三态、销号门全都从它派生。

分家的后果不是崩溃，是两个读数各说一件事（父看到"在跑 3 个"而销号门看到"都停了"），
而没有任何东西会报错。

## 钉住三件事

1. 两个名字取到的是同一个元组（`conductor.UNFINISHED_STATUSES` 是
   `secretary.LIVE_TASK_STATUSES` 的转发，不是第二份）；
2. 这两个文件里除真身那一行之外没有第二处字面量（含内联 `in (...)` 写法）；
3. 反真空：真身本身必须是非空的、且确实是 `schema.TASK_STATUSES` 的子集
   （否则"两个空元组相等"也能过）。

## 已知的第三处（不改，点名）

`schema.py` 的 `Task.validate` 里也有一处 `in ("pending", "running")` —— 它属 FC-27
禁改区（schema 迁移），本轮不动，也不许把它算成"通过"：本判据只声明"上面两个模块里
不再有第二处"，schema 那一处由人审。
"""
from __future__ import annotations

import pathlib

from agentflow import conductor as C
from agentflow import schema as S
from agentflow import secretary as SEC

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
LITERAL = '("pending", "running")'


def test_the_two_names_are_the_same_tuple() -> None:
    assert tuple(C.UNFINISHED_STATUSES) == tuple(SEC.LIVE_TASK_STATUSES), (
        "两个活档常量分家了："
        f"conductor={C.UNFINISHED_STATUSES} / secretary={SEC.LIVE_TASK_STATUSES}")
    assert len(SEC.LIVE_TASK_STATUSES) == 2, SEC.LIVE_TASK_STATUSES


def test_the_truth_is_not_vacuous() -> None:
    """反真空：两个空元组也"相等"，所以真身必须非空、且是 schema 词表的子集。"""
    assert SEC.LIVE_TASK_STATUSES, "活档状态表是空的 ⇒ 上一条判据在真空通过"
    assert set(SEC.LIVE_TASK_STATUSES) <= set(S.TASK_STATUSES), (
        f"{SEC.LIVE_TASK_STATUSES} 里有不在 schema.TASK_STATUSES 里的取值")
    assert set(SEC.LIVE_TASK_STATUSES) < set(S.TASK_STATUSES), (
        "活档表等于整张状态表 ⇒ 终态也算'还在跑'，这条判据失去意义")


def _literal_lines(path: pathlib.Path) -> list[int]:
    """`("pending", "running")` 作为代码出现在哪几行（注释与 docstring 不算）。

    为什么用 tokenize 而不是"行里含这个子串"：注释与 docstring 里点名这个字面量
    恰恰是解释这件事的写法（本文件自己就要写它），按子串判会把说明文字也判成违规。
    这里只认 token 序列：`(` `"pending"` `,` `"running"` `)` —— 与空白、引号种类无关。
    """
    import io
    import tokenize

    toks = [t for t in tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
            if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                              tokenize.INDENT, tokenize.DEDENT)]
    hits: list[int] = []
    for i in range(len(toks) - 4):
        a, b, c, d, e = toks[i:i + 5]
        if (a.type == tokenize.OP and a.string == "("
                and b.type == tokenize.STRING and b.string.strip("\"'") == "pending"
                and c.type == tokenize.OP and c.string == ","
                and d.type == tokenize.STRING and d.string.strip("\"'") == "running"
                and e.type == tokenize.OP and e.string == ")"):
            hits.append(a.start[0])
    return hits


def test_no_second_literal_in_the_two_modules() -> None:
    """这两个文件里，`("pending", "running")` 作为代码只许出现在真身那一行。"""
    found: list[str] = []
    for name in ("conductor.py", "secretary.py"):
        src = _SRC / name
        lines = src.read_text(encoding="utf-8").splitlines()
        for lineno in _literal_lines(src):
            line = lines[lineno - 1]
            if name == "secretary.py" and line.startswith("LIVE_TASK_STATUSES"):
                continue          # 真身那一行
            found.append(f"{name}:{lineno}: {line.strip()[:100]}")
    assert not found, (
        "又出现了第二处活档字面量（分家的起点）—— 请改成引用常量：\n" + "\n".join(found))
