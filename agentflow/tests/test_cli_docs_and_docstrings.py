# -*- coding: utf-8 -*-
"""判据：命令有 docstring，文档写的命令真的存在（业主特别点的那一条：注释与文档）。

## 这一份守什么

三条都是"文档与实现同源"这件事的可执行形态：

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① | parser 里每个子命令的 handler 都有 docstring，且那三段话齐（干什么 / 读写什么 / 实现方式） | 半年后没人说得清 `stats gates` 到底读不读台账 |
| ② | `docs/USER-GUIDE.md` 里出现的每个命令名都能在 parser（或四个入口）里找到 | 文档写了一条敲不通的命令（`draft/35` 把角色写成 `--role` 那次） |
| ③ | USER-GUIDE 的新老对照表每一行都真的能 `--help` 通过 | 对照表里躺着一条早就不存在的路径 |
| ④ | `docs/CLI-CONTRACT.md` 与 `docs/USER-GUIDE.md` 都在 `docs/INDEX.md` 里被点名 | 新写的文档没人找得到 |

## 为什么 ① 要"三段话"而不是"有 docstring 就行"

有 docstring 与"读完知道它读写哪张表"是两件事。这一轮的 docstring 规格是三条：
这条命令干什么 / 它读写了哪些表或文件 / 实现方式一句话。所以判据查的是里面有没有
`读写` 与 `实现` 这两个词 —— 那是三段话里的两段的记号（第三段由第一句承担）。
"有 docstring 就算过"只会让一句空的 TODO 也过。
"""
from __future__ import annotations

import argparse
import inspect
import io
import pathlib
import re
import shlex
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentflow import cli

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"
USER_GUIDE = DOCS / "USER-GUIDE.md"
CONTRACT = DOCS / "CLI-CONTRACT.md"

#: 在 USER-GUIDE 里出现、但它不是一个命令的词（逐条给理由）。
#:
#: 目前只有一条：`agentflow workspace` 是工作区标记文件（`.agentflow-workspace`）
#: 的内容样本，不是一条能敲的命令。
NOT_A_COMMAND: frozenset[str] = frozenset({"workspace"})


def _handlers() -> dict[str, object]:
    """26 个级联命令 + 二级子命令的 handler（键是"命令 [子命令]"）。"""
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    out: dict[str, object] = {}
    for name, child in sub.choices.items():
        out[name] = child.get_default("func")
        nested = next((a for a in child._actions
                       if isinstance(a, argparse._SubParsersAction)), None)
        for inner, grand in (nested.choices.items() if nested is not None else ()):
            out[f"{name} {inner}"] = grand.get_default("func")
    return out


# ---------------------------------------------------------------- ① handler docstring


def test_every_subcommand_handler_has_a_three_part_docstring() -> None:
    """① 每个 handler 都有 docstring，且里面写着"读写"与"实现"两段。"""
    handlers = _handlers()
    assert len(handlers) >= 30, sorted(handlers)  # 反真空：扫描面真的读到子命令
    missing: list[str] = []
    thin: list[str] = []
    for path, func in sorted(handlers.items()):
        doc = inspect.getdoc(func) if func is not None else None
        if not doc:
            missing.append(path)
            continue
        if "读写" not in doc or "实现" not in doc:
            thin.append(path)
    assert not missing, f"这些子命令的 handler 没有 docstring：{missing}"
    assert not thin, f"这些 handler 的 docstring 缺『读写』或『实现』那一段：{thin}"


def test_every_subcommand_handler_is_a_named_function() -> None:
    """① 的反面：handler 不许是 lambda / 匿名可调用（否则它没有可写的 docstring）。

    为什么要有这一条：`set_defaults(func=lambda args: 0)` 也能跑，但它没法带注释 ——
    而"这条命令读写哪张表"正是靠注释活下来的。
    """
    for path, func in sorted(_handlers().items()):
        assert callable(func), path
        assert getattr(func, "__name__", "") not in ("", "<lambda>"), path


# ---------------------------------------------------------------- ② 文档里的命令名都真实存在


def _known_names() -> set[str]:
    names = set(cli.LEGACY_COMMANDS) | set(cli.GROUP_NAMES)
    return names


def test_every_command_named_in_the_user_guide_really_exists() -> None:
    """② USER-GUIDE 里出现的每个 `agentflow <词>` 都必须是真的命令或入口组。"""
    text = USER_GUIDE.read_text(encoding="utf-8")
    found = [(m.group(1), m.start()) for m in re.finditer(r"agentflow\s+([a-z][a-z0-9-]*)", text)]
    assert len(found) >= 20, f"扫描面只读到 {len(found)} 处命令名（判据失去对象）"
    known = _known_names()
    bad = sorted({word for word, _pos in found
                  if word not in known and word not in NOT_A_COMMAND})
    assert not bad, f"USER-GUIDE 里写了不存在的命令：{bad}"


# ---------------------------------------------------------------- ③ 对照表逐行可执行


def _table_rows() -> list[tuple[str, str]]:
    """USER-GUIDE 7.2 那张表里的 (旧名, 新路径)（从表格里现读，不抄第二份）。"""
    text = USER_GUIDE.read_text(encoding="utf-8")
    start = text.index("### 7.2")
    end = text.index("### 7.3")
    rows: list[tuple[str, str]] = []
    for line in text[start:end].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not line.strip().startswith("|"):
            continue
        for left, right in ((cells[0], cells[1]), (cells[2], cells[3])):
            old = left.strip("` ")
            new = right.strip("` ")
            if old.startswith("`") or new.startswith("agentflow "):
                if old and new.startswith("agentflow "):
                    rows.append((old, new))
    return rows


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return int(code or 0), out.getvalue(), err.getvalue()


def test_every_row_of_the_mapping_table_is_executable() -> None:
    """③ 对照表每一行的新路径都能 `--help` 通过，且旧名与新路径折回同一个 argv。"""
    rows = _table_rows()
    assert len(rows) == len(cli.command_paths()) == 29, (len(rows), len(cli.command_paths()))
    for old, new in rows:
        path = new.split()[1:]  # 去掉开头的 `agentflow`
        code, out, err = _run([*path, "--help"])
        assert code == 0, (new, code, err)
        assert cli.canonical_argv(path)[:1] == [old], (new, old, cli.canonical_argv(path))
    # 表里的旧名必须与代码里那张表逐字一致（顺序可以不同，集合不许不同）
    assert {old for old, _new in rows} == set(cli.LEGACY_COMMANDS), (
        {old for old, _new in rows} ^ set(cli.LEGACY_COMMANDS))


def test_the_mapping_table_matches_the_help_legacy_page() -> None:
    """③ 的另一半：文档那张表与 `--help-legacy` 打出来的是同一批行。"""
    code, out, err = _run(["--help-legacy"])
    assert code == 0, (code, err)
    for _old, new in _table_rows():
        assert new in out, f"`--help-legacy` 里没有这一行：{new}"


# ---------------------------------------------------------------- ④ 文档索引


def test_the_new_and_updated_docs_are_indexed() -> None:
    """④ `docs/INDEX.md` 点名了 USER-GUIDE 与 CLI-CONTRACT（否则没人找得到它们）。"""
    index = (DOCS / "INDEX.md").read_text(encoding="utf-8")
    assert "USER-GUIDE.md" in index, "INDEX.md 里没有 USER-GUIDE.md"
    assert "CLI-CONTRACT.md" in index, (
        "INDEX.md 里没有 CLI-CONTRACT.md —— 新增的契约文档要在索引里有一行")
