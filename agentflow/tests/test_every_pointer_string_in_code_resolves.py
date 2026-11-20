"""代码里的 `文件.py::符号` 指针必须指得到真身（2026-11-20 通用判据）。

## 这条判据守什么

2026-11-20 那一轮拆文件（`secretary.py` 16,341 → 788 拆出 31 个 `secretary_*.py`；
`verifications.py` 7,166 → 356 拆出 18 个 `v_*.py`；`clock.py` 6,777 → 698 拆出 12 个
`clock*.py` …）之后，"按（文件, 符号）登记的读数面"成批失去对象：`errorstats.CODE_TABLE`
的出处列 9 行指着 `secretary.py` 里已经搬走的符号；三张收口登记表（`MIGRATED_BY_ID` /
`MIGRATED_TEXT` / `MIGRATED_POOL`）还写着 `secretary.py::…`；`deprecated` 台账里那句
`secretary.<旧名>` 的旧名也全指空。每一处都是"看起来像索引的一句话"。

这条判据只守一件事实：代码里写下的指针，目标文件在、符号也在。它不判断那句指针
写得对不对（那是人读的事），也不替任何一条判据决定它该读哪个符号。

## 为什么只扫"代码字符串"，不扫注释与 docstring

注释 / docstring 里的指针是散文：`tests/test_deprecated_forms_are_gone.py` 已经有一条
按 `module.symbol` 扫注释/docstring 的判据（`DANGLING_ALLOWED`，两向等额）。文档里的
`文件.py::symbol` 按本仓口径（`R-BE4`：行号易失）只报不改，那是另一条路。

字符串常量不一样：它是机器读的数据（`CODE_TABLE` 的一格、登记表的一个调用点、
夹具值）。它错了没有第二个读者会替它发现 —— 所以必须由判据守。这也正是这次事故的形态：
拆文件的人改了实现，没有任何一条判据去核"登记表那一格还指得到吗"。

## 三条

1. 目标文件必须存在（按六个根解析：包目录 / `tests/` / `tools/` / `scripts/` / 交付树根 /
   仓库根 —— 指针的写法有 `agent_f/manuscript.py::…` 与 `agentflow/src/…` 两种）；
2. 目标 `.py` 里必须有那个符号：顶层 `def` / `class` / 赋值，或 `Class.method`，或
   import 进来的名字（再导出的门面页也算"在这个文件里"——指针回答的是"去哪一格看"，
   门面页是真的能看的那一格）；
3. 指向"夹具里造出来的文件/行"的指针（`probe.py::…`、`tests/test_a.py::…`、喂给
   "坏文档必须被拒"那类判据的假行）逐条登记在 `_FIXTURE_ONLY` 并写清为什么它是夹具；
   登记过期（那句话没了）也是红 —— 与 `CODE_TABLE` 那条判据同一纪律。

## 反真空

`test_the_scanner_reports_a_bogus_pointer` 用夹具树证明：好指针不报、坏指针必报。
没有它，`_pointer_problems` 可以因为"永远返回空"而恒绿 —— 那是这条判据最贵的绿。

## 与设计对齐（`draft/191`）

判据是设计的派生物：本条钉的不变式是"登记面是索引，不是一句话"。拆文件没有推翻它，
所以修法是把指针改到新真身，不是把判据放宽成"文件存在就行"或跳过分类。
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "agentflow"

#: 指针的形态：`相对路径.py::符号`。符号只收 `A-Za-z_` 开头（行号形态不是指针，另行判）。
TOKEN = re.compile(r"((?:[\w./-]+/)?[\w-]+\.py)::([A-Za-z_][\w.]*)")

#: 扫哪些文件里的字符串常量。
SCAN_ROOTS: tuple[pathlib.Path, ...] = (
    PKG,
    REPO / "tests",
    REPO / "scripts",
    REPO / "tools",
)

#: 指针里的相对路径按这些根解析（顺序 = 先近后远；同一个路径只会在一个根下）。
RESOLVE_ROOTS: tuple[pathlib.Path, ...] = (
    PKG,
    REPO / "tests",
    REPO / "tools",
    REPO / "scripts",
    REPO,
    REPO.parent,
)

#: 夹具里造出来的指针：只有这些不是真指针。键 =（写它的文件, 指针），值 = 为什么是夹具。
#: 多数是"临时树里造一个同名文件，再断言某条判据认得出它"；`agent_d.py::install_d_tools`
#: 那一条是喂给"坏文档必须被拒"的假行（`tools_problems` 的正控），不是盘上的真引用。
_FIXTURE_ONLY: dict[tuple[str, str], str] = {
    ("tests/test_clean_invariant.py", "probe.py::_nobody_calls_me"):
        "夹具：临时树里造 `probe.py` 的一个零提及私有函数，判据该把它读成死代码",
    ("tests/test_clean_invariant.py", "probe.py::supply"):
        "夹具：临时树里的'唯一定义'，正向控制",
    ("tests/test_clean_invariant.py", "probe.py::gone_target"):
        "夹具：临时树里的'目标已经不见了'那一格",
    ("tests/test_clean_invariant.py", "probe.py::vanished"):
        "夹具：临时树里被删掉的定义，负向控制",
    ("tests/test_sysclean_design_side_is_current.py", "agent_d.py::install_d_tools"):
        "夹具文档：`old_tools` 是喂给 `tools_problems` 的假行（正控要求它必须被判红），"
        "不是盘上真引用",
    ("tests/test_the_full_suite_runner_splits_deterministically.py", "tests/test_a.py::test_1"):
        "夹具：分文件跑批时造出来的假测试文件名（只用于拼 argv）",
    ("tests/test_the_full_suite_runner_splits_deterministically.py", "tests/test_a.py::test_2"):
        "夹具：同上",
    ("tests/test_the_full_suite_runner_splits_deterministically.py", "tests/test_b.py::test_3"):
        "夹具：同上",
    ("tests/test_tools_branch_key_sets.py", "search_tools.py::_h_register"):
        "扫描器自己的键形态：`scan(TOOLS)` 产出的键就是 `<模块名>.py::<handler>`，"
        "断言拿它比对产出，不是文件指针",
    ("tests/test_tools_branch_key_sets.py", "research_tools.py::research_submit_gap"):
        "同上",
}


def _defined_names(path: pathlib.Path) -> tuple[set[str], set[str]]:
    """（文件里"有名字的东西", 其中哪些是类）。

    名字含嵌套 def / class、模块级赋值、import 进来的名字；`Class.方法` 带前缀。
    返回类名集合是为了区分两件事：`Class.方法` 必须逐段存在（类里真有那个方法），
    而 `SPEC.write_set` 这种"表/字典的二级键"只核持有者（字典是数据，不是符号表）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    classes: set[str] = set()

    def walk(node: ast.AST, prefix: str) -> None:
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                names.add(name)
                if isinstance(child, ast.ClassDef):
                    classes.add(name)
                walk(child, name + ".")
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        names.add(f"{prefix}{target.id}")
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                names.add(f"{prefix}{child.target.id}")
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    names.add(alias.asname or alias.name.split(".")[-1])

    walk(tree, "")
    return names, classes


def _docstring_values(tree: ast.AST) -> set[int]:
    """docstring 那些常量节点的 `id()`（散文里的指针不归本条判据管）。"""
    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def _resolve(rel: str) -> pathlib.Path | None:
    for base in RESOLVE_ROOTS:
        path = base / rel
        if path.is_file():
            return path
    return None


def _rel(path: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:                      # 反真空用的 `tmp_path`
        return path.name


def _code_pointers(paths: list[pathlib.Path]) -> dict[tuple[str, str], list[int]]:
    """（写它的文件, 指针）-> 出现的行号。只收代码字符串；docstring 不算。"""
    me = pathlib.Path(__file__).resolve()
    got: dict[tuple[str, str], list[int]] = {}
    for path in paths:
        if path.resolve() == me:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prose = _docstring_values(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in prose:
                continue
            for rel, symbol in TOKEN.findall(node.value):
                got.setdefault((_rel(path), f"{rel}::{symbol}"), []).append(node.lineno)
    return got


def _scanned_paths() -> list[pathlib.Path]:
    """候选文件：正文里真的出现 `.py::` 的那些（先文本筛，只解析筛出来的 —— 全量 AST
    解析一千多个文件要十几秒，而 99% 的文件里一个指针都没有）。"""
    out: list[pathlib.Path] = []
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if ".py::" in text:
                out.append(path)
    return out


def _pointer_problems(measured: dict[tuple[str, str], list[int]],
                      resolver=_resolve) -> list[str]:
    """逐条核：文件在、符号在；夹具登记过期也报。返回问题清单（空 = 全对）。"""
    problems: list[str] = []
    cache: dict[pathlib.Path, tuple[set[str], set[str]]] = {}
    for (src, pointer), lines in sorted(measured.items()):
        if (src, pointer) in _FIXTURE_ONLY:
            continue
        rel, symbol = pointer.split("::", 1)
        target = resolver(rel)
        where = f"{src}:{lines[0]}  {pointer}"
        if target is None:
            problems.append(f"{where} ⇒ 目标文件不存在")
            continue
        if target.suffix != ".py":
            continue                        # 指针指向非 .py（如 `fixtures/x.json`）只核存在
        try:
            if target not in cache:
                cache[target] = _defined_names(target)
            have, classes = cache[target]
        except SyntaxError:
            problems.append(f"{where} ⇒ 目标文件此刻不可解析（本判据没查成，不是通过）")
            continue
        if symbol in have:
            continue
        head = symbol.split(".")[0]
        if "." in symbol and head not in classes and head in have:
            # 表 / 字典 / 函数的二级键（`SPEC.write_set` 这种）：只核持有者 ——
            # 键是数据不是符号，硬核它会把"表里有哪些键"抄成第二份真源。
            continue
        problems.append(f"{where} ⇒ {target.name} 里没有这个符号")
    stale = sorted(
        f"{src}  {pointer}（{_FIXTURE_ONLY[(src, pointer)]}）"
        for (src, pointer) in _FIXTURE_ONLY if (src, pointer) not in measured)
    if stale:
        problems.append("夹具登记过期（那处指针已经不在盘上了，删掉这一行）：\n  "
                        + "\n  ".join(stale))
    return problems


def test_every_pointer_string_in_code_resolves() -> None:
    """第 1–3 条：代码字符串里的每个 `文件.py::符号` 都必须指得到真身。"""
    paths = _scanned_paths()
    assert len(paths) > 50, (
        f"只筛到 {len(paths)} 个含 `.py::` 的 .py ⇒ 这一格没查成"
        "（根被搬走 / 路径写错都不是「没问题」）")
    measured = _code_pointers(paths)
    # 反真空：盘上真有多少指针要按它数（今天 111 对 / src 里 81 对；一个都扫不到说明扫描器坏了）。
    assert len(measured) > 80, (
        f"只扫到 {len(measured)} 个代码字符串指针 ⇒ 扫描器没接上（不是「没有指针」）")
    in_src = [k for k in measured if k[0].startswith("src/")]
    assert len(in_src) > 50, (
        f"产品源码里只扫到 {len(in_src)} 个指针 ⇒ 产品面没接上"
        "（不是「产品里没有指针」）")
    problems = _pointer_problems(measured)
    assert not problems, (
        "代码字符串里的指针指到了不存在的东西（改到真身；夹具造出来的逐条登记进 "
        "`_FIXTURE_ONLY`）：\n  " + "\n  ".join(problems))


def test_the_scanner_reports_a_bogus_pointer(tmp_path: pathlib.Path) -> None:
    """反真空：好指针不报、坏指针必报；夹具登记过期也报。

    没有这一条，`_pointer_problems` 返回空列表可以是因为"它什么也没核"。
    """
    good = tmp_path / "mod.py"
    good.write_text("def hello() -> int:\n    return 1\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text(
        '"""模块 docstring 是散文，不算：mod.py::also_never_defined"""\n'
        'OK = "mod.py::hello"\n'
        'GONE = "mod.py::never_defined"\n'
        'MISSING = "nowhere.py::hello"\n',
        encoding="utf-8")

    measured = _code_pointers([bad])
    assert ("bad.py", "mod.py::never_defined") in measured, measured
    assert ("bad.py", "mod.py::hello") in measured, measured
    assert not any("also_never_defined" in ptr for _src, ptr in measured), (
        "docstring 里的指针不该被收进来（散文归另一条判据）")

    def resolver(rel: str) -> pathlib.Path | None:
        return {"mod.py": good}.get(rel)

    problems = _pointer_problems(measured, resolver=resolver)
    text = "\n".join(problems)
    assert "never_defined" in text, f"坏符号没被报出来：{problems}"
    assert "nowhere.py" in text, f"不存在的文件没被报出来：{problems}"
    assert "mod.py::hello" not in text.replace("never_defined", ""), (
        f"好指针被误报了：{problems}")
