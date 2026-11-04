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
3. 每个符号必须真的在那个文件里（函数改名 / 常量改名 / 搬家都红）；
4. 出处说"这个码在哪产出" ⇒ 收工门那一族（出处点名 `closing.py` 的函数的那些行）
   必须真的在那个函数里产出这个码（①②③只核"符号存在"，不核"这个码在那个符号里"——
   把 `mapping_not_written` 指到根本不产它的 `_check_acceptance` 照样绿）。
"""

from __future__ import annotations

import ast
import pathlib
import re

from agentflow import errorstats as E

REPO = pathlib.Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"(src/agentflow/[\w/]+\.py)::([A-Za-z_][\w.]*)")

#: 出处点名的"产出函数"（只有收工门这一族的出处写的是函数，其余写常量 / 类 / 字段名）。
_CLOSING_FN = re.compile(r"(src/agentflow/closing\.py)::(_check_[a-z_]+|check_closing)")
#: 出处里括注的常量名（码由常量产出时，函数体里出现的是常量而不是字面量）。
_BARE_CONST = re.compile(r"[（(]([A-Z][A-Z0-9_]{2,})[）)]")


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


def _function_node(rel: str, name: str) -> ast.AST | None:
    """`rel` 里函数 `name` 的 AST 节点（找不到返回 None）。"""
    path = REPO / rel
    if not path.is_file():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _emitted_names(node: ast.AST) -> set[str]:
    """函数体里**会被执行到**的名字与字符串字面量。

    刻意走 AST 而不是读源码文本：注释不在 AST 里。改前的错法正是"码只出现在
    `_check_acceptance` 的一句注释里"（真正的产出点在 `_check_mapping`），
    按文本 grep 会把它判绿 —— 那一条假绿是本判据第一版实测踩到的。
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            names.add(child.value)
        elif isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def test_a_closing_code_row_names_the_function_that_emits_it() -> None:
    """第 4 条：出处点名"这个码在哪产出" ⇒ 那个码必须真的在那个函数里产出。

    为什么要有这一条：第 2、3 条只核"文件存在 / 符号存在"这一档。于是把
    `mapping_not_written` 的出处指到 `_check_acceptance`（它根本不产这个码，
    只在注释里提过它）照样绿 —— 而这一列的全部意义就是"人按它去找那一格"。
    改前真身在 `_check_mapping`：`Finding("mapping", MAPPING_NOT_WRITTEN_CODE, …)`。

    口径边界（如实写在这里，免得下一个人把命中数当精确值）：
    - 只核出处**点名函数**的那些行（`closing.py::_check_*` 与 `check_closing`）；
      其余行的出处写的是常量 / 类 / 字段名（如 `RUN_EVIDENCE_UNBACKED_CODE`），
      那几行的"产出点"是常量本身，由第 3 条核存在性；
    - 码由常量产出时，函数体里出现的是常量名而不是字面量 ⇒ 出处括注的那个
      常量名也算命中（`（MAPPING_NOT_WRITTEN_CODE）` 这一档）；
    - 只看 AST（会被执行到的字面量与名字），**注释不算** —— 按文本 grep 会被
      "只在注释里提过这个码"骗过（本判据第一版实测）。
    """
    bad: list[str] = []
    checked = 0
    for code, _cat, where in E.CODE_TABLE:
        hit = _CLOSING_FN.search(str(where))
        if not hit:
            continue
        rel, fn = hit.groups()
        node = _function_node(rel, fn)
        if node is None:
            bad.append(f"{code!r}：{rel} 里找不到函数 {fn}")
            continue
        checked += 1
        consts = _BARE_CONST.findall(str(where))
        emitted = _emitted_names(node)
        if code in emitted or any(c in emitted for c in consts):
            continue
        bad.append(
            f"{code!r}：出处点名 {fn}，而那个函数里既不产 {code!r}、也没有 "
            f"{consts or '（没括注常量）'} —— 按出处去找会走到另一格")
    # 反真空：收工门那一族至少要有三行（今天四行）；扫不到说明选择器坏了，不是"没问题"。
    assert checked >= 3, f"只核到 {checked} 行 ⇒ 这一格没查成（不是没有问题）"
    assert not bad, (
        "这些行的出处点到了不产它的那个函数（出处从'可核的索引'退化成'看起来像索引的一句话'）：\n  "
        + "\n  ".join(bad))
