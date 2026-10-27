"""`errorstats.CODE_TABLE` 的"出处"必须真的指得到东西（`R-BE4`，2026-10-27 业主批准）。

## 这条判据守什么

`CODE_TABLE` 的第三列说"这个码在哪定义 / 在哪产出"。改前它写的是 `文件:行号`，
而没有任何判据看行号 —— `tests/test_error_action_stats.py` 的第 6 条只断言
"这个码在 `src/agentflow/` 的某个文件里出现过"。于是行号漂走之后："出处"那一列
从"可核的索引"退化成"看起来像索引的一句话"：实测 80 行里只有 16 行还指在码上
（`temp/rbe4_codetable_provenance.py` 的读数），另外 64 行指到的是与这个码无关的代码。

现在出处写符号名（`src/agentflow/x.py::函数或常量`），于是可以机械核：
那个文件存在、那个符号真的在那个文件里（顶层 def/class，或 `Class.method`，
或模块级赋值名）。行号会漂，符号名不会 —— 改了函数名这条判据当场红，那正是要的。

## 三条

1. 每一行都必须给出处，且出处里至少有一个 `file::symbol`；
2. 每个 `file::symbol` 的文件必须真的存在（拼错路径 / 文件被删都红）；
3. 每个符号必须真的在那个文件里（函数改名 / 常量改名 / 搬家都红）。
"""

from __future__ import annotations

import ast
import pathlib
import re

from agentflow import errorstats as E

REPO = pathlib.Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"(src/agentflow/[\w/]+\.py)::([A-Za-z_][\w.]*)")


def _defined_names(path: pathlib.Path) -> set[str]:
    """文件里"有名字的东西"：顶层/嵌套 def、class，以及模块级赋值目标（含 `Class.方法`）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()

    def walk(node, prefix: str) -> None:
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                names.add(name)
                walk(child, name + ".")
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        names.add(f"{prefix}{target.id}")
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                names.add(f"{prefix}{child.target.id}")

    walk(tree, "")
    return names


def test_every_code_has_a_symbol_provenance() -> None:
    """第 1 条：80 行每一行都要给出处，且出处里至少有一个 `file::symbol`。"""
    missing: list[str] = []
    for code, _cat, where in E.CODE_TABLE:
        if not str(where or "").strip():
            missing.append(f"{code!r}：出处是空的")
        elif not TOKEN.search(str(where)):
            missing.append(f"{code!r}：出处里没有 `file::symbol` —— {str(where)[:60]}")
    assert not missing, (
        "这些行的出处不是一个可核的符号名（行号不算）：\n  " + "\n  ".join(missing))


def test_every_provenance_symbol_exists_in_its_file() -> None:
    """第 2、3 条：文件存在，且符号真的在那个文件里（函数改名 / 搬家都会红）。"""
    cache: dict[str, set[str]] = {}
    bad: list[str] = []
    for code, _cat, where in E.CODE_TABLE:
        for rel, symbol in TOKEN.findall(str(where)):
            path = REPO / rel
            if not path.is_file():
                bad.append(f"{code!r}：{rel} 不存在")
                continue
            if rel not in cache:
                cache[rel] = _defined_names(path)
            if symbol not in cache[rel]:
                bad.append(f"{code!r}：{rel} 里没有 {symbol}")
    assert not bad, (
        "`CODE_TABLE` 的出处指向了不存在的东西（符号名是新的口径：行号会漂，符号名不许漂）：\n  "
        + "\n  ".join(bad))


def test_the_old_line_number_form_is_gone() -> None:
    """反真空：出处里不许再出现 `文件.py:123` 这种行号形态。

    没有这一条，"改回行号"不会被任何地方发现 —— 上一条判据只认 `::` 形态，
    混写一个行号它照样绿。
    """
    line_form = re.compile(r"src/agentflow/[\w/]+\.py:\d")
    offenders = [code for code, _c, where in E.CODE_TABLE if line_form.search(str(where))]
    assert not offenders, (
        f"这些行的出处还在用行号（会漂，且没有任何判据能核）：{offenders}")
