# -*- coding: utf-8 -*-
"""清洁不变量：死代码 / 重复实现 / 仓根残留，三件都变成会红的读数。

## 这份判据为什么必须存在

清洁这件事的失败形态不是"清得不干净"，而是"清完之后没人知道该守什么"：
下一批改动再把一个没人调的私有函数写进 `src/`、把同一段渲染代码抄第二遍、
或者让一个临时审计目录散在仓根 —— 这三件都不会让任何既有判据变红。
单测永远是绿的（用例自己塞调用方），lint 的 R003 只管公开名，
而"仓根多了一个未跟踪目录"根本不在任何既有判据的字段里。

所以这里把三件事各做成一条两向相等的判据（多一个红、少一个也红）：

1. `DEAD_PRIVATE_LEDGER`：`src/agentflow` 里"全仓只有它自己那一次出现"的私有函数，
   必须逐条登记；实测集合与台账必须逐条相等。
2. `ONE_IMPLEMENTATION`：点名的那几个概念，真实现必须恰好一处
   （转发不算实现）。
3. git 顶层不许有未跟踪目录。

## 口径（写死在这里，否则下一个人无法判断这条判据量的是什么）

第 1 条只量「私有」函数（名字以 `_` 开头、不是 dunder、且不嵌套在函数体内）：

- 公开名可能是工具（模型按名字从注册表取）、CLI 命令（argparse 挂点）、别人
  `import` 的 API —— 静态看不见那些边，混进来只会让台账烂成噪音；
- 私有名的接线面只可能是代码本身，所以"没人提它"对它们是真话；
- 嵌套定式不收：它的调用点一定在同一个函数体里，按名字收边会把外层那个大函数里
  的同名局部当成它的活边（更漏报的方向）；它真死的时候外层那一条会报。

"提"按整词出现计（代码 / 注释 / docstring / 字符串 / `.md` 都算）：
留痕是正当的 —— 一个退场实现的旧名字被注释引着（"这里原有它、为什么摘掉"），
读者找得到它、也知道它为什么还在。只判调用点会把那一类正确留痕判成缺陷。
"全仓只有定义那一次出现"才是"没人知道它存在"。

## 已知盲区（写清，否则这条判据会被读成比它实际更强）

- 名字级读数（与 `tests/test_wiring_edges.py` 的按文件记账不同）：同名多定义时，
  两份定义共用一个计数 ⇒ 死的那一份会被活的那一份遮住（漏报方向）。
  同名多定义这件事由 `test_wiring_edges.py::test_every_ledger_name_is_resolved_by_
  file_not_by_name` 与 lint R003 管，本文件不重复它；这里只负责"名字本身没人提"。
- 经 `getattr(名字字符串)` / 反射拿到的调用看不见（同 `test_wiring_edges.py` 的
  已知盲区）。方向上只会多报、不会漏报；多报的逐条登记进台账并写清差哪一根线。
- 第 2 条只守那几个「点过名」的概念，不是"全仓零重复"。全仓同名多实现由
  `scripts/lint_rules.py` 的 R003 报（清洁那一轮 20 条 → 17 条，逐条判定见报告）。
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
from collections import Counter

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "agentflow"
TESTS = REPO / "tests"
SCRIPTS = REPO / "scripts"
TOOLS = REPO / "tools"

#: 第 1 条的台账：`"<rel>::<限定名>"` -> 为什么它还在（以及差哪一根线）。
#:
#: 空表本身也是有内容的读数（"今天没有孤儿"）；非空时每一条都必须是
#: "看得见理由的例外"，而不是"还没轮到的欠账"。
DEAD_PRIVATE_LEDGER: dict[str, str] = {
    "conductor.py::Conductor._write_completion_manuscript": (
        "交差手稿的代写（`draft/39` §6.6 F1）。零调用点已 20 天（孤儿于 e3fd3bf 那次"
        "手稿账本去噪），全仓没有一处提它。不敢删的理由：它与今晚这一批的"
        "交差/手稿面同族 —— 可能是接线缺口（实现好了没接上去），而删它会连那半截设计"
        "一起丢。需人裁：接上它，或由人删。`docs/WIRING-AUDIT-2026-10-27.md` 的台账"
        "只收今晚点过名的那些，没有它。"),
    "tools/base.py::_schema_allows_null": (
        "`validate_params` 的 null 放行判据。零调用点、零提及，但 `tools/base.py` 是"
        "FC-27 禁改区（`[category: auth-audit]`：只读角色的权限面由它三处共同决定）"
        "⇒ 清洁这一轮不许动它。需人裁：或并进 `validate_params`（那儿有同一段理由），"
        "或由人删除。"),
}

#: 结构上不算"孤儿"的（按形态排除，不按名字登记 —— 名单越短越不会被借用）：
#: 这些是按名字被取走的（框架 / 人 / 注册表），静态看不见边。
_NOT_ORPHAN_NAMES = frozenset({"selftest", "register", "install", "main", "tool_specs"})

#: 装饰器里出现这些字样 ⇒ 它按名字被取（工具注册表 / 属性 / 协议 / 缓存）。
_NOT_ORPHAN_DECOS = ("tool", "property", "staticmethod", "classmethod", "overload",
                     "setter", "cache")

#: 第 2 条：概念 ->（唯一实现所在的文件（相对 `src/agentflow`）, 函数名）。
#:
#: 为什么是这几条：它们都是这一批改动点过名、且最容易长成第二份的东西
#: （三态判定会长出"另一处的三态折平"、销号闸会长出"另一处的放行"、
#: 计时登记会长出"另一处 start_timer"、渲染会长出"再抄一遍排版"）。
ONE_IMPLEMENTATION: dict[str, tuple[str, str]] = {
    "三态判定（在飞 / 待机 / 静默 / 未读到）": ("conductor.py", "agent_state"),
    "三态取最活跃那一档": ("conductor.py", "most_active_state"),
    "销号闸（谁可以销号）": ("conductor.py", "retire_blocking"),
    "计时登记（挂机登记）": ("clock.py", "_register_parked"),
    "TS 声明渲染（三条零交线共用）": ("webui/state.py", "type_decls"),
}

#: 第 3 条的台账：允许的未跟踪目录（今天为空 —— 仓根一个都不许有）。
UNTRACKED_DIRS_ALLOWED: dict[str, str] = {}

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# ============================================================ 第 1 条：死代码

def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _py_files(root: pathlib.Path) -> list[pathlib.Path]:
    if not root.is_dir():
        return []
    return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]


def _md_files() -> list[pathlib.Path]:
    out = [p for p in sorted((REPO / "docs").rglob("*.md"))] if (REPO / "docs").is_dir() else []
    for extra in (REPO / "AGENTS.md", REPO / "DEVELOPMENT.md", REPO / "DESIGN.md"):
        if extra.is_file():
            out.append(extra)
    return out


class _Defs(ast.NodeVisitor):
    """收"模块级函数 + 类方法"的定义点，跳过嵌套在函数体内的定义。"""

    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.stack: list[str] = []
        self.in_function = 0
        self.defs: list[dict] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not self.in_function:
            self.defs.append({
                "rel": self.rel, "line": node.lineno, "name": node.name,
                "qual": ".".join(self.stack + [node.name]),
                "decos": [ast.unparse(d) for d in node.decorator_list],
            })
        self.stack.append(node.name)
        self.in_function += 1
        self.generic_visit(node)
        self.in_function -= 1
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def collect_defs(root: pathlib.Path) -> list[dict]:
    """一棵树里"模块级函数 + 类方法"的全部定义点。"""
    out: list[dict] = []
    for path in _py_files(root):
        rel = path.relative_to(root).as_posix()
        got = _Defs(rel)
        got.visit(_parse(path))
        out.extend(got.defs)
    return out


def word_counts(skip: tuple[pathlib.Path, ...] = ()) -> Counter[str]:
    """整仓（源码 / 测试 / 脚本 / 工具 / 文档）每个标识符形态的词出现几次。

    `skip` 里那几份不算 —— 判据自己必须排除在外：台账里那几行写着名字
    （`"conductor.py::Conductor._write_completion_manuscript"`），算进来的话
    台账会自己把自己判定成"有人提过它"，于是每一个登记项自动通过。
    那是一条只有本文件能给出的假边，属于最坏的绿。
    """
    skip_set = {p.resolve() for p in skip}
    counts: Counter[str] = Counter()
    for root in (SRC, TESTS, SCRIPTS, TOOLS):
        for path in _py_files(root):
            if path.resolve() in skip_set:
                continue
            counts.update(_WORD.findall(path.read_text(encoding="utf-8", errors="replace")))
    for path in _md_files():
        if path.resolve() in skip_set:
            continue
        counts.update(_WORD.findall(path.read_text(encoding="utf-8", errors="replace")))
    return counts


def _exempt(d: dict) -> bool:
    name = d["name"]
    if name in _NOT_ORPHAN_NAMES:
        return True
    if name.startswith("__") and name.endswith("__"):
        return True
    if d["rel"] == "host.py":                              # 装配线本身是入口
        return True
    if d["rel"] == "cli.py" and name.startswith("cmd_"):    # argparse 挂点
        return True
    return any(mark in deco for deco in d["decos"] for mark in _NOT_ORPHAN_DECOS)


def found_orphans(defs: list[dict], counts: Counter[str] | dict[str, int]) -> set[str]:
    """实测的"私有、全仓除定义外零提及"集合（键 = `rel::qual`）。"""
    out: set[str] = set()
    for d in defs:
        name = d["name"]
        if not name.startswith("_") or name.startswith("__"):
            continue
        if _exempt(d):
            continue
        if int(counts.get(name, 0)) > 1:     # 定义处那一次之外的任何一处提及都算
            continue
        out.add(f"{d['rel']}::{d['qual']}")
    return out


def test_no_dead_private_function_without_a_ledger_entry() -> None:
    """第 1 条：实测的"没人知道它存在"的私有函数集合，必须与台账逐条相等。

    两向都红：
    - 实测有、台账没写 ⇒ 树里多了一个零提及的私有函数（接上它、删掉它，
      或写清它为什么还在）；
    - 台账写了、实测没有 ⇒ 登记过期（那会训练人忽略整张表）。
    """
    measured = found_orphans(collect_defs(SRC), word_counts(skip=(pathlib.Path(__file__),)))
    listed = set(DEAD_PRIVATE_LEDGER)
    assert measured == listed, (
        "零提及的私有函数与台账不符。\n"
        f"  实测有、台账没写：{sorted(measured - listed)}（接上它、删掉它，或登记理由）\n"
        f"  台账写了、实测没有：{sorted(listed - measured)}（登记过期，删掉那一行）\n"
        f"  台账 {len(listed)} 条 / 实测 {len(measured)} 条 ⇒ 净额 {len(measured - listed)}"
    )


def test_the_orphan_scan_sees_a_function_nobody_calls() -> None:
    """第 1 条的反真空：同一套扫描，喂"有人提的"和"没人提的"必须读出不同结论。

    "往 `src/` 塞一个没人调的函数 ⇒ 该判据红"这条要求的本体就是这里：
    判据跑的是 `found_orphans`，下面给它语义相反的两组输入。

    为什么用合成输入而不是真的往 `src/` 写一个文件：判据自己往被扫的树里写东西，
    会让"跑判据"变成"改仓库"（`tests/test_demo_selftest_leaves_the_repo_clean.py`
    记的正是这类事故）。喂的是同一份实现，被量的那一步真跑一遍。
    """
    lone = [{"rel": "probe.py", "line": 1, "name": "_nobody_calls_me",
             "qual": "_nobody_calls_me", "decos": []}]
    assert found_orphans(lone, {"_nobody_calls_me": 1}) == {"probe.py::_nobody_calls_me"}, (
        "没人提的私有函数没被扫出来 ⇒ 这条判据没有牙")
    assert found_orphans(lone, {"_nobody_calls_me": 2}) == set(), (
        "被提及的私有函数仍被判成孤儿 ⇒ 会把正确留痕一起判红")

    for exempt in (
        {"rel": "probe.py", "line": 1, "name": "__enter__", "qual": "__enter__", "decos": []},
        {"rel": "probe.py", "line": 1, "name": "_selftest", "qual": "_selftest", "decos": ["tool"]},
        {"rel": "host.py", "line": 1, "name": "_assemble", "qual": "_assemble", "decos": []},
        {"rel": "cli.py", "line": 1, "name": "cmd_probe", "qual": "cmd_probe", "decos": []},
    ):
        assert found_orphans([exempt], {exempt["name"]: 1}) == set(), exempt


def test_a_nested_function_is_not_a_module_level_definition() -> None:
    """嵌套定式不算孤儿：它的调用点一定在同一个函数体里，外层那一条才该报。"""
    got = _Defs("probe.py")
    got.visit(ast.parse("def outer():\n    def _inner():\n        return 1\n    return _inner()\n"))
    assert {d["name"] for d in got.defs} == {"outer"}, got.defs


# ============================================================ 第 2 条：重复实现

def _is_forwarder(path: pathlib.Path, name: str) -> bool:
    """`name` 在这份文件里是不是一条转发（与 `scripts/lint_rules.py` 的 R003 同口径）。

    刻意抄一份极小实现而不是 import 那一份：`scripts/lint_rules.py` 是 FC-27
    禁改区，本文件 import 它会把"判据的判据"接成一条线 —— 改 lint 的口径就等于
    悄悄改了这里的口径。两条口径的一致性由
    `test_the_forwarder_recogniser_matches_the_two_shapes` 自己承重。
    """
    try:
        tree = _parse(path)
    except (SyntaxError, OSError):
        return False
    for node in tree.body:
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name):
            continue
        body = [s for s in node.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        aliases: dict[str, str] = {}
        while body and isinstance(body[0], (ast.Import, ast.ImportFrom)):
            for al in body.pop(0).names:
                aliases[al.asname or al.name.split(".")[0]] = al.name
        if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
            return False
        value = body[0].value
        if isinstance(value, ast.Call):
            value = value.func
        if isinstance(value, ast.Attribute):
            return value.attr == name
        if isinstance(value, ast.Name):
            return value.id == name or aliases.get(value.id) == name
        return False
    return False


def implementations_of(name: str) -> set[str]:
    """全 `src` 里这个名字的「真实现」所在文件（转发的那些不算）。"""
    got: set[str] = set()
    for path in _py_files(SRC):
        try:
            tree = _parse(path)
        except SyntaxError:
            continue
        if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                   and n.name == name for n in tree.body):
            continue
        if _is_forwarder(path, name):
            continue
        got.add(path.relative_to(SRC).as_posix())
    return got


def test_each_watched_concept_has_exactly_one_implementation() -> None:
    """第 2 条：点名的那几个概念，真实现必须恰好一处。

    "恰好一处"是双向的：长出第二份红，该在的那一份不见了也红
    （后者会让这条判据在被删空之后继续绿 —— 那是最贵的一种绿）。
    """
    problems: list[str] = []
    for concept, (owner, name) in sorted(ONE_IMPLEMENTATION.items()):
        got = implementations_of(name)
        if got != {owner}:
            problems.append(f"{concept}：`{name}` 的实现在 {sorted(got) or '（一处都没有）'}，"
                            f"台账写的是 {owner}")
    assert not problems, (
        "这些概念长出了第二份实现（或者该在的那一份不见了）：\n  " + "\n  ".join(problems)
        + "\n留一份、删另一份，并让删掉的那份转发过去（转发不算实现）。")


def test_the_forwarder_recogniser_matches_the_two_shapes(tmp_path: pathlib.Path) -> None:
    """第 2 条的反真空：转发与真实现必须被读成两回事。

    没有这一条，`implementations_of` 可以因为"永远把一切当转发"而恒返回空集 ——
    那时上面的相等判据仍然是红的，但红的原因不是它想守的那件事；反过来写成
    "永远不算转发"，三处真实现则会全绿。
    """
    real = tmp_path / "real.py"
    real.write_text("def target():\n    return 1\n", encoding="utf-8")
    fwd = tmp_path / "fwd.py"
    fwd.write_text("from . import impl as _impl\n\n\n"
                   "def target():\n    \"\"\"转发。\"\"\"\n    return _impl.target(1)\n",
                   encoding="utf-8")
    assert _is_forwarder(real, "target") is False, "真实现被读成了转发"
    assert _is_forwarder(fwd, "target") is True, "转发没被读出来"


# ============================================================ 第 3 条：仓根

def untracked_dirs(porcelain: str) -> list[str]:
    """`git ls-files --others --directory` 的输出 -> 未跟踪目录（纯函数，便于一正一反）。"""
    return [line.strip() for line in str(porcelain).splitlines() if line.strip().endswith("/")]


def test_the_untracked_dir_parser_separates_dirs_from_files() -> None:
    """第 3 条的反真空：解析器必须把目录与散文件分开，否则"零目录"可以恒真。"""
    got = untracked_dirs("_audit_tmp/\nagentflow/tests/test_x.py\ndraft/\n")
    assert got == ["_audit_tmp/", "draft/"], got
    assert untracked_dirs("") == []
    assert untracked_dirs("agentflow/scripts/golden_diff.py\n") == []


def test_the_repo_root_has_no_untracked_directory() -> None:
    """第 3 条：git 顶层不许有未跟踪目录（临时的审计/探针目录一律不许散在仓根）。

    为什么量的是"目录"而不是"文件"：一次性的审计产物总是以目录形态出现
    （`_audit_tmp/sections/`、`_audit_tmp/unique/` 那种），而「长期有用的脚本」
    有它该去的地方 —— `scripts/`（并在文件头写清用途），不是仓根。
    散在仓根的单个文件 `git status` 自己可见，不在这里重复判。
    """
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(REPO),
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:      # git 不在这台机器上
        raise AssertionError(
            f"没查成：起不了 git（{type(exc).__name__}: {exc}）⇒ 这一条判据今天没有读数。"
            "三态纪律：没查成不算通过") from exc
    assert top.returncode == 0, f"没查成：`git rev-parse` 退出码 {top.returncode}：{top.stderr[-300:]}"
    root = pathlib.Path(top.stdout.strip())
    proc = subprocess.run(["git", "ls-files", "--others", "--directory", "--exclude-standard"],
                          cwd=str(root), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300)
    assert proc.returncode == 0, f"没查成：`git ls-files` 退出码 {proc.returncode}：{proc.stderr[-300:]}"
    # 只量顶层：`agentflow/data/` 那种是"某个未跟踪文件的父目录"，不是"仓根残留"。
    dirs = [d for d in untracked_dirs(proc.stdout) if d.rstrip("/").count("/") == 0]
    assert dirs == sorted(UNTRACKED_DIRS_ALLOWED), (
        f"git 顶层有未跟踪目录：{dirs}（允许清单：{sorted(UNTRACKED_DIRS_ALLOWED)}）\n"
        "  一次性的审计/探针目录：删掉；长期有用的脚本：移到 `scripts/` 并写清用途。")
