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
4. `tests/fixtures/public_dead_baseline.json`：`src/agentflow` 里"生产侧零读者"的公开
   模块级名字（函数 / 类 / 常量），必须逐条落在基线或白名单里；实测集合与两者之并逐条相等。

## 第 5 条为什么必须存在（一条已经漏过的缝）

第 1 条刻意只量私有函数。公开名于是长期没有判据：`identity` 的 `conflict_line`、
`rowscope` 的 `OWNER_FIELDS`、`interactions` 的 `ADJUDICATION_POLICY_CODES`、
`store` 的 `direct_write_backstop`、`schema` 的 `CONJECTURE_QUESTION_WORDS` 这五个
公开名零调用地活到了 2026-11-20，才由人逐条删掉 —— 全程没有任何判据变红。
第 5 条堵的就是这条缝：公开名同样要有一个生产侧读者，或者逐条登记它为什么还在。

## 第 5 条的口径（"什么算引用"写死在这里）

一个公开名"有读者"只有一类：生产代码里真的读了它。生产侧 =
`src/` + `scripts/` + `tools/`。其余的提及各自成类，逐条可查，但都不单独构成"活"：

- `import`：只在 import 行里被 re-export。转发不是读者；下游真用到时那次使用
  会落在 `production` 类里，于是"re-export 且下游有用"自然算活。
- `all_export`：名字被某个 `__all__` 列出。它算一种"公开声明"，但不许拿它掩盖
  死代码：只有 `all_export` 而没有生产读者的名字仍然进基线（或进白名单并写清理由）。
- `dynamic`：名字作为字符串被 `getattr` / `setattr` / `hasattr` / `delattr` 或
  `globals()[...]` / `locals()[...]` / `vars(...)[...]` 取。静态看不见那条边，
  所以它进白名单并写清取它的位置；它不自动算活。
- `prose`：只在生产侧的注释或 docstring 里被提到。叙述不是读者。
- `tests`：只在 `tests/` 的代码里被读。这正是要抓的缝 —— 它不算读者；
  要留就进白名单并写理由。
- `docs`：只在 `*.md` 里被提到。文档不是读者。

判据把"有生产读者"记成 `production` 一类；一个名字 `production` 计数为 0 时，
本判据把它判成待处理，并逐条列出其余哪几类引用存在（报告里那张表就是这个读数）。
白名单只收"确认要留"的名字：每条必须写清它凭哪一类引用留下，且那一类必须实测存在
（塞一个真死的名字进白名单会报"白名单里的名字其实是死的"）。
基线只收"还没处理"的名字：它是棘轮，不是赦免 —— 新出现的死名字会红，
处理掉一个而没从基线删掉那一行也会红。

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

第 5 条另有它自己的盲区，写在这里免得被读成比它实际更强：

- 名字级读数：同名多定义时，一份定义被活的那一份遮住（漏报方向）；与第 1 条同口径。
- "动态取"只认 `getattr` 一族的字符串参数与 `globals()` 一族的字符串下标。
  走注册表字符串（`{"handler": "foo"}`）分发的名字看不见，会落进 `production`
  （字符串里的词也算代码），于是漏报而不是误报。
- import 行被从代码里抹掉后再计数：只被 re-export、没有下游读者的名字会报；
  但"下游用到的"是靠下游那次提及认出来的，认不出的是别名链，方向仍是漏报。
- 基线是一份快照，不是规格：别的路改了 `src/` 之后它可能过期，重跑本判据并
  按失败信息增删那一行即可（判据自己会点名哪一条过期）。
"""

from __future__ import annotations

import ast
import functools
import io
import json
import pathlib
import re
import subprocess
import tokenize
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
    # 2026-10-27（`R-BE4` 的②-2，业主批准 = 删）：`tools/base.py::_schema_allows_null`
    # 已由人裁掉 —— 零调用点，而"显式 null 一律放行"是 `validate_params` 与
    # `ToolRegistry.call` 刻意的口径（把 null 崩翻成可行动的 `param_error`，见
    # `base.py` 里 `except (TypeError, AttributeError)` 那一支）。函数描述的是一个
    # 不打算落地的判据，留着只会让读的人以为"null 有闸"。
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


# ============================================================ 第 4 条：判据面

#: 第 4 条的台账：`"<rel>::<qual>"` -> "归哪条判据用、为什么不删它"。
#:
#: 这一栏收的是"公开"函数：生产侧没有任何读者（`src` / `scripts` / `tools` 里除了
#: 定义那一处再无提及），但它们是某条判据的靶子。第 1 条收不了这一档 ——
#: 它刻意只量私有名（公开名可能是工具 / argparse 挂点 / 别人 `import` 的 API，
#: 静态看不见那些边）。所以"公开、零生产读者、但有判据读它"必须单列一栏，
#: 否则它要么被当成漏网死代码删掉（判据随即失去对象），要么没人知道它为什么还在。
#:
#: 为什么不删：删掉靶子之后，那条判据只剩两条路 —— 失去对象（不再判任何东西），
#: 或者自己在测试里把那套读账重新算一遍（判据自己证明自己）。后者是本项目点名的
#: 最坏的绿：测试与实现一起漂，而读数照样通过。
DIAGNOSTIC_FACE: dict[str, str] = {
    "conceptrows.py::definition_supply": (
        "定义供给的六桶读数（`concepts` 那套镜像的供给面）。零生产读者，唯一的读者是"
        "`tests/test_the_definition_supply_is_counted.py`（六桶逐格、含一个读不成表的负控）。"
        "为什么不删：它是那条判据的靶子 —— 删了之后测试只能自己再数一遍六桶，于是"
        "'读数错了'与'测试漏了'再也分不开。要是将来接进收工门或 webui 的读数面，"
        "这一条就该从本栏删掉（那时它有生产读者了）。"),
    "conceptrows.py::mirror_gaps": (
        "概念镜像的缺口读数（`statements_only` / `concepts_only` + `transition_over`）。"
        "零生产读者，读者是 `tests/test_the_mirror_is_complete.py` 与"
        "`tests/test_the_concept_view_during_the_merge.py`。为什么不删：同上 —— 它是"
        "'镜像缺哪几条'那条判据的靶子，而且它自己带三态（`transition_over=True` 说的是"
        "'这一格不再适用'，不是'缺口没有了'）；删了这份区分就只剩测试里的复刻。"),
}


def production_word_counts(skip: tuple[pathlib.Path, ...] = ()) -> Counter[str]:
    """生产侧（`src` / `scripts` / `tools`）每个标识符形态的词出现几次。

    与 `word_counts` 的差别只有扫描根：这一栏问的是"生产侧有没有读者"，
    所以测试与文档不算（测试里出现是这条登记的前提，不是反例）。
    """
    skip_set = {p.resolve() for p in skip}
    counts: Counter[str] = Counter()
    for root in (SRC, SCRIPTS, TOOLS):
        for path in _py_files(root):
            if path.resolve() in skip_set:
                continue
            counts.update(_WORD.findall(path.read_text(encoding="utf-8", errors="replace")))
    return counts


def diagnostic_face_problems(defs: list[dict], prod: Counter[str] | dict[str, int],
                             test: Counter[str] | dict[str, int]) -> dict[str, list[str]]:
    """按台账逐条核"它还是不是判据面"，返回 `{键: [问题…]}`（空 dict = 全对）。"""
    by_key = {f"{d['rel']}::{d['qual']}": d for d in defs}
    out: dict[str, list[str]] = {}
    for key in DIAGNOSTIC_FACE:
        d = by_key.get(key)
        if d is None:
            out[key] = [f"定义不见了（{key}）⇒ 登记过期，删掉台账里那一行"]
            continue
        name = d["name"]
        issues: list[str] = []
        if int(prod.get(name, 0)) > 1:
            issues.append(
                f"生产侧现在有读者（{int(prod.get(name, 0)) - 1} 处提及）⇒ 它不再是判据面，"
                "把台账里那一行删掉")
        if int(test.get(name, 0)) < 1:
            issues.append("测试侧一次都不提它 ⇒ 靶子没了，这个函数该删（不许为绿留死代码）")
        if issues:
            out[key] = issues
    return out


def test_every_diagnostic_face_entry_is_still_a_criterion_target() -> None:
    """第 4 条：登记为"判据面"的公开函数，必须仍然只被测试读、且仍有测试读它。

    三向都红（三种"登记过期"）：
    - 那个定义不见了 ⇒ 登记过期（改名 / 删掉了）；
    - 生产侧出现第二处提及 ⇒ 它有读者了，这条登记必须删掉（它不再是判据面）；
    - 测试侧一次都不提 ⇒ 靶子没了，函数该删。

    为什么台账里只有两条：这一栏刻意只收"点过名"的（与第 2 条 `ONE_IMPLEMENTATION`
    同一个取舍）。全仓"公开但只有测试读"的函数远不止两个，逐个登记会烂成噪音；第 1 条
    与 lint R003 已经分担了各自的普查面。这条判据守的是"登记过的每一条都还成立"。
    """
    me = pathlib.Path(__file__)
    defs = collect_defs(SRC)
    measured = diagnostic_face_problems(
        defs, production_word_counts(skip=(me,)), word_counts(skip=(me,)))
    assert not measured, (
        "判据面台账与实测不符：\n  "
        + "\n  ".join(f"{k}：{'；'.join(v)}" for k, v in sorted(measured.items()))
    )


def test_the_diagnostic_face_check_is_two_way() -> None:
    """第 4 条的反真空：三种过期形态各喂一次，必须都报出来。

    "往生产侧接一个读者 ⇒ 登记该删"与"测试不再提它 ⇒ 函数该删"这两条要求，
    本体就是 `diagnostic_face_problems`；下面用合成输入逐条验它。
    """
    defs = [
        {"rel": "probe.py", "line": 1, "name": "supply", "qual": "supply", "decos": []},
        {"rel": "probe.py", "line": 1, "name": "gone_target", "qual": "gone_target", "decos": []},
    ]
    saved = dict(DIAGNOSTIC_FACE)
    DIAGNOSTIC_FACE.clear()
    DIAGNOSTIC_FACE.update({
        "probe.py::supply": "样例：判据靶子",
        "probe.py::gone_target": "样例：判据靶子",
        "probe.py::vanished": "样例：已删",
    })
    try:
        got = diagnostic_face_problems(defs, {"supply": 3}, {"gone_target": 0})
    finally:
        DIAGNOSTIC_FACE.clear()
        DIAGNOSTIC_FACE.update(saved)
    assert "probe.py::vanished" in got, got                  # 定义不见了
    assert any("生产侧现在有读者" in x for x in got.get("probe.py::supply", [])), got
    assert any("靶子没了" in x for x in got.get("probe.py::gone_target", [])), got


# ============================================================ 第 5 条：公开死名字

#: 引用类别的唯一词表。`PRODUCTION` 是唯一让名字"活"的那一类；
#: 其余六类各自可查、可写进白名单，但都不单独构成"有读者"。
REF_PRODUCTION = "production"
REF_IMPORT = "import"
REF_ALL_EXPORT = "all_export"
REF_DYNAMIC = "dynamic"
REF_PROSE = "prose"
REF_TESTS = "tests"
REF_DOCS = "docs"
REF_CATEGORIES = (REF_PRODUCTION, REF_IMPORT, REF_ALL_EXPORT, REF_DYNAMIC,
                  REF_PROSE, REF_TESTS, REF_DOCS)

#: 按名字取值的调用。第二个位置参数是字符串常量时，那个字符串算 `dynamic` 类。
_DYNAMIC_CALLS = frozenset({"getattr", "setattr", "hasattr", "delattr"})
#: `globals()["x"]` / `locals()["x"]` / `vars(obj)["x"]` 这一族的字符串下标。
_DYNAMIC_SUBSCRIPTS = frozenset({"globals", "locals", "vars"})

#: 第 5 条的白名单：名字 -> (凭哪几类引用留下, 为什么）。
#:
#: 白名单只收"确认要留"的名字，不收"还没轮到处理"的名字（后者进基线）。
#: 每一条的两个字段都判据会核：理由空着会红；声称的引用类别实测不存在会红；
#: 一个引用都没有的名字放进白名单，会报"白名单里的名字其实是死的"。
PUBLIC_REFERENCE_WHITELIST: dict[str, tuple[frozenset[str], str]] = {
    "FakeClock": (
        frozenset({REF_ALL_EXPORT, REF_TESTS}),
        "测试用的假时钟（时钟注入点 `use` 的另一半）：生产侧从不实例化它，"
        "`tests/` 里 30+ 处用它把墙钟与单调钟钉死。`__all__` 是它的公开声明，"
        "不是掩盖：删了它，那批判据只能各自造一个私有假钟。"),
    "reset_books": (
        frozenset({REF_ALL_EXPORT, REF_TESTS}),
        "测试隔离面：清时钟账本。生产侧零读者，18 份测试用它保证用例之间不串账；"
        "`__all__` 导出是给测试面用的公开声明。"),
    "reset_observed_events": (
        frozenset({REF_ALL_EXPORT, REF_TESTS}),
        "测试隔离面：清观测定时器。生产侧零读者，22 份测试用它重置挂机读数；"
        "与 `reset_books` 同族，`__all__` 导出。"),
    "reset_waits": (
        frozenset({REF_ALL_EXPORT, REF_TESTS}),
        "测试隔离面：清等待账本。生产侧零读者，19 份测试用它重置等待态；"
        "与 `reset_books` 同族，`__all__` 导出。"),
    "run_gate": (
        frozenset({REF_ALL_EXPORT, REF_TESTS}),
        "逐门入口：生产主路径走 `run_all_gates`，不直接调它；52 处测试逐门拿读数。"
        "它是 gate 判据的靶子（`__all__` 导出是公开声明），删了那批测试就只剩复刻。"),
    # 2026-11-20（LEGACY A5）：`universal_tool_violations` 已接进 `build_registry`
    # 的装配期（违规即报），`stop_closure` 已接进 `dispatch_stop_reading` 与
    # `agentflow stop --status` —— 两者都有了生产读者，白名单里那两行按判据的
    # 失败信息删掉了（白名单只收"生产侧零读者、确认要留"的名字）。
    "PINNED_MATHLIB_TAG": (
        frozenset({REF_DYNAMIC}),
        "被 `toolchain.py` 的 `getattr(FG, \"PINNED_MATHLIB_TAG\", \"\")` 按名字取："
        "动态边，静态看不见；`__all__` 导出是它的公开声明。"),
    "NO_LEAN_REPLACEMENTS": (
        frozenset({REF_DYNAMIC}),
        "B / E / G 三份「关掉 Lean 之后怎么改写」表，被 `agent_prompts._no_lean_tables` "
        "按名字 `getattr` 逐份取（specs/b.py、specs/e.py、specs/g.py 各一份）；"
        "动态边，静态看不见。"),
    "NO_LEAN_DROP_LINE_MARKERS": (
        frozenset({REF_DYNAMIC}),
        "E 的「关掉 Lean 之后哪些行要摘掉」表，被 `agent_prompts._no_lean_tables` "
        "按名字 `getattr` 取；动态边，静态看不见。"),
    "NO_LEAN_DROP_BLOCKS": (
        frozenset({REF_DYNAMIC}),
        "E 的「关掉 Lean 之后哪几段要摘掉」表，被 `agent_prompts._no_lean_tables` "
        "按名字 `getattr` 取；动态边，静态看不见。"),
}


def _char_col(lines: list[str], lineno: int, byte_col: int) -> int:
    """`ast` 的字节列 -> 字符列（源码里有中文时两者不等，混用会抹错区间）。"""
    if not 1 <= lineno <= len(lines):
        return byte_col
    return len(lines[lineno - 1].encode("utf-8")[:byte_col].decode("utf-8", "ignore"))


def mask_python(text: str) -> tuple[str, set[str], set[str], set[str], str]:
    """把一份源码拆成 (代码文本, import 名, `__all__` 名, 动态取名, 注释与 docstring 文本)。

    注释、docstring、import 行、`__all__` 里的字符串、`getattr` 一族的字符串
    都从代码文本里抹掉 —— 判据要数的"生产读者"只认代码里的真实读取。
    抹掉的东西各自记成自己的类别，于是失败信息能说清"哪一类引用是 0"。
    """
    text = text.replace("\r\n", "\n")
    lines = text.splitlines()
    grid = [list(line) for line in lines]
    imported: set[str] = set()
    all_names: set[str] = set()
    dynamic: set[str] = set()
    prose: list[str] = []

    def blank(lineno: int, start: int, end_lineno: int, end: int) -> None:
        for ln in range(lineno, end_lineno + 1):
            if not 1 <= ln <= len(grid):
                continue
            a = start if ln == lineno else 0
            b = end if ln == end_lineno else len(grid[ln - 1])
            for i in range(a, min(b, len(grid[ln - 1]))):
                grid[ln - 1][i] = " "

    def at(node: ast.AST) -> tuple[int, int, int, int]:
        return (node.lineno, _char_col(lines, node.lineno, node.col_offset),
                node.end_lineno, _char_col(lines, node.end_lineno, node.end_col_offset))

    def slice_of(node: ast.AST) -> str:
        a, b, c, d = at(node)
        if a == c:
            return lines[a - 1][b:d]
        return "\n".join([lines[a - 1][b:]] + lines[a:c - 1] + [lines[c - 1][:d]])

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text, imported, all_names, dynamic, ""

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    imported.add(alias.asname or alias.name.split(".")[0])
            blank(*at(node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                value = node.value
                if isinstance(value, (ast.List, ast.Tuple)):
                    for element in value.elts:
                        if isinstance(element, ast.Constant) and isinstance(element.value, str):
                            all_names.add(element.value)
                            blank(*at(element))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _DYNAMIC_CALLS:
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str):
                dynamic.add(node.args[1].value)
                blank(*at(node.args[1]))
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) \
                and node.value.func.id in _DYNAMIC_SUBSCRIPTS:
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                dynamic.add(node.slice.value)
                blank(*at(node.slice))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            prose.append(slice_of(body[0].value))
            blank(*at(body[0].value))

    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                prose.append(token.string)
                blank(token.start[0], token.start[1], token.end[0], token.end[1])
    except tokenize.TokenError:
        pass

    return "\n".join("".join(row) for row in grid), imported, all_names, dynamic, "\n".join(prose)


def public_definitions(root: pathlib.Path) -> list[dict]:
    """一棵树里"模块级公开名"的定义点：函数 / 类 / 常量（跳过下划线名与嵌套定义）。"""
    out: list[dict] = []
    for path in _py_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = _parse(path)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name, kind = node.name, type(node).__name__
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                name, kind = "", "Assign"
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    if isinstance(target, ast.Name):
                        name = target.id
            else:
                continue
            if name and not name.startswith("_"):
                out.append({"rel": rel, "name": name, "kind": kind, "line": node.lineno})
    return out


def _scan_python_corpus(roots: list[pathlib.Path]) -> dict[str, object]:
    """生产侧所有源码按类别收一次：代码词 / import / `__all__` / 动态 / 散文。"""
    words: Counter[str] = Counter()
    prose: Counter[str] = Counter()
    imported: set[str] = set()
    all_names: set[str] = set()
    dynamic: set[str] = set()
    for root in roots:
        for path in _py_files(root):
            try:
                code, imp, alls, dyn, text = mask_python(
                    path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            words.update(_WORD.findall(code))
            prose.update(_WORD.findall(text))
            imported |= imp
            all_names |= alls
            dynamic |= dyn
    return {"words": words, "prose": prose, "imported": imported,
            "all_names": all_names, "dynamic": dynamic}


def _scan_words(roots: list[pathlib.Path]) -> Counter[str]:
    """只数词（不抹注释）：给测试侧与文档侧用。

    测试侧的注释/docstring 里出现的名字最多让它落进 `tests` 类，而 `tests` 类
    本身不构成"活"；所以这里不需要 tokenize，省下的时间用来把源码侧抹干净。
    """
    words: Counter[str] = Counter()
    for root in roots:
        for path in _py_files(root):
            words.update(_WORD.findall(path.read_text(encoding="utf-8", errors="replace")))
    return words


def _scan_md_corpus(paths: list[pathlib.Path]) -> Counter[str]:
    words: Counter[str] = Counter()
    for path in paths:
        words.update(_WORD.findall(path.read_text(encoding="utf-8", errors="replace")))
    return words


def public_doc_files() -> list[pathlib.Path]:
    """第 5 条读的文档面：`docs/` 全部 + 项目根的全部 `.md`（含 DESIGN-*.md）。"""
    out = [p for p in sorted((REPO / "docs").rglob("*.md"))] if (REPO / "docs").is_dir() else []
    out += [p for p in sorted(REPO.glob("*.md"))]
    return out


def classify_public(defs: list[dict], prod: dict[str, object],
                    test_words: Counter[str], docs: Counter[str]) -> dict[str, dict]:
    """逐条公开名算七个引用类别的读数（键 = `rel::name`）。"""
    defined: Counter[str] = Counter(d["name"] for d in defs)
    prod_words = prod["words"]
    prod_prose = prod["prose"]
    out: dict[str, dict] = {}
    for d in defs:
        name = d["name"]
        # 定义行自己也有一处名字：按同名定义数扣掉，剩下的才是"别人读它"。
        production = int(prod_words.get(name, 0)) - defined[name]
        out[f"{d['rel']}::{name}"] = {
            REF_PRODUCTION: max(0, production),
            REF_IMPORT: name in prod["imported"],
            REF_ALL_EXPORT: name in prod["all_names"],
            REF_DYNAMIC: name in prod["dynamic"],
            REF_PROSE: int(prod_prose.get(name, 0)),
            REF_TESTS: int(test_words.get(name, 0)),
            REF_DOCS: int(docs.get(name, 0)),
        }
    return out


def is_public_dead(refs: dict, *, count_tests: bool = False,
                   count_docs: bool = False) -> bool:
    """没有生产读者就是死名。两个开关只给反真空用：打开即"把那一类当读者"。"""
    if int(refs[REF_PRODUCTION]) > 0:
        return False
    if count_tests and int(refs[REF_TESTS]) > 0:
        return False
    if count_docs and int(refs[REF_DOCS]) > 0:
        return False
    return True


def measured_dead_public(defs: list[dict], refs: dict[str, dict], *,
                         count_tests: bool = False,
                         count_docs: bool = False) -> set[str]:
    """实测的"生产侧零读者"公开名集合（键 = 名字）。

    按名字收而不是按 `rel::name` 收：这一条的读数是名字级的（见文件头的盲区），
    文件只是证据。并行开发下模块搬家（`clock.py` -> `clockrun.py` 那一类）很常见，
    按文件收会把一次搬家记成"删一个 + 加一个"，于是棘轮每次搬家都要重冻。
    """
    return {d["name"] for d in defs
            if is_public_dead(refs[f"{d['rel']}::{d['name']}"],
                              count_tests=count_tests, count_docs=count_docs)}


def references_by_name(defs: list[dict], refs: dict[str, dict]) -> dict[str, dict]:
    """同名多定义合并成一条名字级读数（同名定义共享同一份名字级计数）。"""
    out: dict[str, dict] = {}
    for d in defs:
        out.setdefault(d["name"], refs[f"{d['rel']}::{d['name']}"])
    return out


def public_whitelist_problems(refs_by_name: dict[str, dict],
                              whitelist: dict[str, tuple[frozenset[str], str]]
                              ) -> dict[str, list[str]]:
    """白名单逐条核：名字还在、理由非空、声称的引用类别实测存在。

    没有这一条，白名单会退化成"把死名字塞进去就绿"。
    """
    out: dict[str, list[str]] = {}
    for name, (claimed, reason) in whitelist.items():
        refs_one = refs_by_name.get(name)
        if refs_one is None:
            out[name] = ["定义不见了 ⇒ 登记过期，删掉这一行"]
            continue
        issues: list[str] = []
        if not str(reason).strip():
            issues.append("理由空着")
        if int(refs_one[REF_PRODUCTION]) > 0:
            issues.append("生产侧已有读者 ⇒ 它不再是死名，删掉这一行")
        present = {c for c in REF_CATEGORIES if c != REF_PRODUCTION and refs_one[c]}
        claimed = frozenset(claimed)
        if not claimed:
            issues.append("没写它凭哪一类引用留下")
        missing = claimed - present
        if missing:
            issues.append(f"声称有 {sorted(missing)} 类引用，实测没有")
        if claimed and not (claimed & present):
            issues.append("白名单里的名字其实是死的：它连声称的那一类引用都没有")
        if issues:
            out[name] = issues
    return out


def load_public_dead_baseline(path: pathlib.Path) -> dict[str, dict]:
    """读第 5 条的基线：每一行必须写清 name / 处置 / 理由（空着就判据红）。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("rows")
    assert isinstance(rows, list) and rows, f"{path} 没有 rows：基线不许空"
    out: dict[str, dict] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        assert name, f"{path} 有一行没写 name：{row}"
        assert name not in out, f"{path} 里 {name} 重复了"
        assert str(row.get("action") or "").strip(), f"{path} 的 {name} 没写处置"
        assert str(row.get("why") or "").strip(), f"{path} 的 {name} 没写理由"
        out[name] = row
    return out


def public_dead_baseline_path() -> pathlib.Path:
    return REPO / "tests" / "fixtures" / "public_dead_baseline.json"


@functools.lru_cache(maxsize=1)
def _real_public_scan() -> tuple[list[dict], dict[str, dict]]:
    """现盘扫一次（缓存）：公开名定义 + 七类引用读数。"""
    defs = public_definitions(SRC)
    refs = classify_public(
        defs,
        _scan_python_corpus([SRC, SCRIPTS, TOOLS]),
        _scan_words([TESTS]),
        _scan_md_corpus(public_doc_files()),
    )
    return defs, refs


def effective_public_whitelist() -> dict[str, tuple[frozenset[str], str]]:
    """第 5 条的白名单 = 本文件登记的 + `DIAGNOSTIC_FACE`（那份台账已有理由，不重复抄）。

    `DIAGNOSTIC_FACE` 只把模块级名字并进来：它收的是"公开函数/方法"，
    而第 5 条只扫模块级公开名（类方法不在它的面上）。
    """
    out = dict(PUBLIC_REFERENCE_WHITELIST)
    for key, reason in DIAGNOSTIC_FACE.items():
        qual = key.split("::", 1)[1]
        if "." in qual:
            continue
        out.setdefault(qual, (frozenset({REF_TESTS}), reason))
    return out


def test_no_public_dead_name_outside_the_baseline_or_whitelist() -> None:
    """第 5 条：实测的公开死名字集合，必须与"基线 + 白名单"逐条相等。

    四向都红：
    - 实测有、两者都没写 ⇒ 新出现一个生产侧零读者的公开名；
    - 基线写了、实测没有 ⇒ 已经处理掉了（接线或删了），基线该收一行；
    - 白名单写了、实测没有 ⇒ 同上；
    - 基线写了、实测也还在，但白名单也写了 ⇒ 同一件事两处记账。
    """
    defs, refs = _real_public_scan()
    measured = measured_dead_public(defs, refs)
    baseline = load_public_dead_baseline(public_dead_baseline_path())
    whitelist = effective_public_whitelist()

    both = sorted(set(baseline) & set(whitelist))
    assert not both, f"这些名字同时进了基线与白名单（同一件事只许记一处）：{both}"

    listed = set(baseline) | set(whitelist)
    refs_by_name = references_by_name(defs, refs)
    fresh = sorted(measured - listed)
    detail = "\n    ".join(
        f"{name}：生产读者 0；还有 "
        + (", ".join(c for c in REF_CATEGORIES
                     if c != REF_PRODUCTION and refs_by_name[name][c]) or "（一类都没有）")
        for name in fresh)
    assert measured == listed, (
        "公开死名字与基线/白名单不符。\n"
        f"  实测有、两处都没写：{fresh}"
        "（接线、删掉，或写进基线并写清处置）\n"
        + (f"  新出现的每一条的引用类别：\n    {detail}\n" if fresh else "")
        + f"  写了、实测已经没有：{sorted(listed - measured)}"
        "（处理掉了，把那一行删掉）\n"
        f"  基线 {len(baseline)} 条 / 白名单 {len(whitelist)} 条 / "
        f"实测 {len(measured)} 条 ⇒ 净额 {len(measured - listed)}"
    )

    problems = public_whitelist_problems(refs_by_name, whitelist)
    assert not problems, (
        "白名单与实测不符：\n  "
        + "\n  ".join(f"{k}：{'；'.join(v)}" for k, v in sorted(problems.items()))
    )


def test_the_public_scan_sees_a_resurrected_name(tmp_path: pathlib.Path) -> None:
    """改前红：5 个已经删掉的公开名"复活"之后，第 5 条必须逐条点出来。

    这五个正是 2026-11-20 从第 1 条下面漏过、由人删掉的样本。判据不许依赖
    "它们今天不在盘上" —— 所以这里在副本里把它们造回来，走同一条扫描。
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "identity.py").write_text(
        "def conflict_line(reading):\n    return reading\n", encoding="utf-8")
    (src / "rowscope.py").write_text(
        "OWNER_FIELDS = ('task_id', 'instance')\n", encoding="utf-8")
    (src / "interactions.py").write_text(
        "ADJUDICATION_POLICY_CODES = {'a': 'b'}\n", encoding="utf-8")
    (src / "store.py").write_text(
        "def direct_write_backstop(table):\n    return table\n", encoding="utf-8")
    (src / "schema.py").write_text(
        "CONJECTURE_QUESTION_WORDS = ('which', 'what')\n", encoding="utf-8")

    defs = public_definitions(src)
    refs = classify_public(defs, _scan_python_corpus([src]),
                           _scan_words([]), Counter())
    got = measured_dead_public(defs, refs)
    expected = {
        "conflict_line",
        "OWNER_FIELDS",
        "ADJUDICATION_POLICY_CODES",
        "direct_write_backstop",
        "CONJECTURE_QUESTION_WORDS",
    }
    assert expected <= got, f"复活版里这些没被点出来：{sorted(expected - got)}"
    assert got == expected, f"副本里还有不该报的：{sorted(got - expected)}"


#: 正控样本：这些公开名在现盘上真的被 `src/` 读。它们一个都不许被第 5 条误报。
#: 20 个是下限（"不误报"必须在一批真名字上成立，不能在空集上成立）。
LIVE_PUBLIC_SAMPLES = frozenset({
    "actor_for",
    "resolve_identity",
    "split_actor",
    "from_actor",
    "OWNER_TASK",
    "TABLES",
    "LOCK_ORDER",
    "agent_state",
    "most_active_state",
    "retire_blocking",
    "check_conflict",
    "ALLOWED_EDGES",
    "CAPABILITIES",
    "AgentSpec",
    "Policy",
    "build_role_registry",
    "type_decls",
    "decide_relation",
    "EXIT_CODE_BY_STOP",
    "ToolRegistry",
    "normalize_doi",
})


def test_the_public_scan_does_not_flag_names_production_reads() -> None:
    """正控：真被 `src/` 读的公开名不许误报（至少 20 个样本，且样本必须还在盘上）。"""
    defs, refs = _real_public_scan()
    names = {d["name"] for d in defs}
    missing = sorted(LIVE_PUBLIC_SAMPLES - names)
    assert not missing, f"正控样本的定义找不到（判据与现盘脱节）：{missing}"
    dead = measured_dead_public(defs, refs)
    false_positives = sorted(LIVE_PUBLIC_SAMPLES & dead)
    assert not false_positives, (
        f"这些公开名确实被生产侧读者读着，却被第 5 条判成死的：{false_positives}")
    assert len(LIVE_PUBLIC_SAMPLES) >= 20, "正控样本少于 20 个，不足以证明不误报"


def _probe_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """负控用的小树：一个只被测试读、一个只被文档提、一个真死、一个生产真读。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "probe.py").write_text(
        "def only_in_tests():\n    return 1\n\n\n"
        "def only_in_docs():\n    return 2\n\n\n"
        "def dead_everywhere():\n    return 3\n\n\n"
        "def live_one():\n    return 4\n",
        encoding="utf-8")
    (src / "consumer.py").write_text(
        "from .probe import live_one\n\n\ndef use():\n    return live_one()\n",
        encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_probe.py").write_text(
        "from .probe import only_in_tests\n\n\ndef test_x():\n    only_in_tests()\n",
        encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "note.md").write_text("只在文档里提到的名字：only_in_docs。\n", encoding="utf-8")
    return tmp_path


def _probe_dead(root: pathlib.Path, *, count_tests: bool = False,
                count_docs: bool = False) -> set[str]:
    src = root / "src"
    defs = public_definitions(src)
    refs = classify_public(defs, _scan_python_corpus([src]),
                           _scan_words([root / "tests"]),
                           _scan_md_corpus([root / "docs" / "note.md"]))
    return measured_dead_public(defs, refs, count_tests=count_tests, count_docs=count_docs)


def test_the_public_scan_sees_test_only_and_doc_only_names(tmp_path: pathlib.Path) -> None:
    """负控：只被测试用、只被文档提到，都必须报；生产真读的那个不许报。

    没有这一条，"生产侧零读者"可以退化成"谁都不算读者"，而判据照样绿。
    """
    dead = _probe_dead(_probe_tree(tmp_path))
    assert "only_in_tests" in dead, "只被测试用的公开名没被报出来"
    assert "only_in_docs" in dead, "只被文档提到的公开名没被报出来"
    assert "dead_everywhere" in dead, "全仓零提及的公开名没被报出来"
    assert "live_one" not in dead, "生产侧真读着的公开名被误报了"


def test_counting_tests_or_docs_as_readers_would_hide_the_gap(tmp_path: pathlib.Path) -> None:
    """反真空：把"只被测试用不算引用"打桩成"算引用" ⇒ 负控必红。

    `is_public_dead` 的 `count_tests` / `count_docs` 就是这个桩。打开之后，
    负控里那两个名字不能再被判死 —— 否则说明判据根本没按这两类口径分档，
    上面那条负控是碰巧绿的。
    """
    root = _probe_tree(tmp_path)
    assert "only_in_tests" not in _probe_dead(root, count_tests=True), (
        "打桩成'测试算引用'之后，只被测试用的名字仍然被判死 ⇒ 口径没有真的分档")
    assert "only_in_docs" not in _probe_dead(root, count_docs=True), (
        "打桩成'文档算引用'之后，只被文档提到的名字仍然被判死 ⇒ 口径没有真的分档")
    # 真死的那个不受两个桩影响：它连测试/文档读者都没有。
    assert "dead_everywhere" in _probe_dead(root, count_tests=True,
                                            count_docs=True)


def test_a_dead_name_in_the_whitelist_is_reported() -> None:
    """白名单反真空：塞一个真死的名字进白名单 ⇒ 必报"其实是死的"。

    两向都验：真死的名字放进去要红；有测试读者的名字放进去不红。
    """
    zero = {c: 0 for c in REF_CATEGORIES}
    refs_by_name = {
        "ghost": dict(zero),
        "target": {**zero, REF_TESTS: 3},
    }
    problems = public_whitelist_problems(
        refs_by_name, {"ghost": (frozenset({REF_TESTS}), "样例：声称测试读它")})
    assert any("其实是死的" in msg for msg in problems.get("ghost", [])), problems
    ok = public_whitelist_problems(
        refs_by_name, {"target": (frozenset({REF_TESTS}), "样例：判据靶子")})
    assert not ok, f"有测试读者的白名单条目被误报：{ok}"


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
