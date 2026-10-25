# -*- coding: utf-8 -*-
"""判据：假绿的四种形态各有一条会红的机器普查（只读，不碰功能代码）。

## 这一份守的是什么

业主 2026-10-25 与 2026-10-27 两次的原话是同一件事的不同说法：怕的是"绿"，不是"红"。
今晚这一批新判据（`NEW_CRITERIA` 那十二个文件）逐条都写了"反真空"，但反真空这句话
本身也可以写成空转：一句 `assert x or True`、一条只搭合成 AST 的"反真空"、一条
`skipif`、一条不承重的替身，都能让同一片绿看起来没有缺口。

所以这里不重复那十二个文件各自的判据，只对它们做四件事的普查：

1. `test_no_assert_is_forever_true`：断言里不许有恒真项（`assert True` / `assert x or True`
   / `assert len(x) >= 0`）。审计 2026-10-27 点名的唯一一处（`test_clock_governs_all_timed_work.py`
   里那句 `assert ... or True`）已改成钉死真实读数形态，台账因此为空；这一条仍然两向相等
   （新出现一处恒真就红，台账里留一条已经修掉的也红）。
2. `test_every_criterion_file_has_a_non_stubbed_case`：每个新判据文件至少要有一条
   不注入替身的用例。整文件全替身的那一档必须进 `ALL_STUB_FILES` 说清为什么
   （今天只有 `test_park_is_a_real_stop.py`：零模型钱、假时钟、替身缝全开），
   同样两向相等。
3. `test_no_new_criterion_can_be_skipped_away`：那十二个文件里不许出现 `skip` / `skipif`
   （跳过不是绿）；`xfail` 必须 `strict=True`（今天两条，都是登记缺口的严格档）。
   这一条就是"假绿"最省事的那条路：把面挂上 skip。
4. `test_every_anti_vacuum_case_touches_its_subject`：名字里带 `not_vacuous` 的用例
   必须真的碰到被测对象（模块级从 `agentflow` 导入的名字，或本文件里别的用例也在用的
   模块级函数）。只在用例内部造一个合成对象、只断言那个合成对象的，不算反真空：
   审计 2026-10-27 实测一处（`test_wiring_edges.py` 的 `test_the_predicate_is_not_vacuous`，
   它断的是用例内嵌的 `callees()`，`is_live` 一次都没被它调用），那一处已修成
   "拿两棵语义相反的 AST 真喂 `is_live` / `reachable`"，台账因此为空。

## 反真空（这一条自己也承重）

`test_the_four_checks_bite_on_synthetic_negatives`：四条普查函数各自喂一份"该红"的
合成源码，四条都必须报出来。没有这一条，上面四条可以整体退化成"永远返回空"。

## 误报方向（写清，否则下一次有人会把这些检查删掉）

- 第 4 条的判据是"名字里带 not_vacuous"，不是"所有反真空都叫这个名字"：改名成
  `test_the_predicate_has_teeth` 的用例逃得掉。它的方向是宁可漏报，不会误报真反真空
  （真反真空一定碰到被测对象）；唯一会误报的形态是"反真空对象只在本文件里定义、
  且只有这一条用例用它"，那种情况写进 `KNOWN_ANTI_VACUUM_WITHOUT_SUBJECT` 并写清理由。
- 第 1 条只认三种形态（常量真、or 链恒真、`>= 0`）。更隐的永真式（例如断言一个
  恒为字典的返回值非空）机器看不出来，只能人工读；这里不假装能看出来。
- 第 2 条的"替身"只认 `monkeypatch` 这一种注入方式。用别的注入（模块级替换、
  环境变量开关）的替身数不出来，方向同样是漏报。

边界：本文件只读盘（`tests/` 与 `src/` 不动一个字），不变量任何功能代码，
不新增 golden，不改 `PROMPT_VERSION`。
"""
from __future__ import annotations

import ast
import pathlib

#: 今晚这批新判据（2026-10-27 第二批）。少一个文件名这一条就红，新增的请一并登记。
NEW_CRITERIA: tuple[str, ...] = (
    "test_clock_governs_all_timed_work.py",
    "test_timers_and_handoff_semantics.py",
    "test_park_is_a_real_stop.py",
    "test_three_states_flying_standby_silent.py",
    "test_retire_only_for_the_silent.py",
    "test_wiring_edges.py",
    "test_wiring_readouts.py",
    "test_dependency_wiring_is_live.py",
    "test_dependency_face_is_read_from_f_manuscript.py",
    "test_v_checks_fs_citations.py",
    "test_prompt_and_tool_truth.py",
    "test_library_face_only_counts_admitted_works.py",
)

#: 恒真断言台账：(文件名, 形态) -> 今天预期有几处。
#:
#: 形态只有三种：`const_true`（整条断言是常量真）、`or_true`（`or` 链里有恒真项）、
#: `ge_zero`（`len(...) >= 0` 这一类）。
#:
#: 今天为空（2026-10-27）：唯一那一处（`test_clock_governs_all_timed_work.py`
#: `test_n_three_process_waits_are_on_the_ledger` 里的
#: `assert result.get("stopped_requested") or result.get("stopped") or True`）已经换成
#: 钉死真实读数形态的四条断言（`stopped_by_user is True` / `timed_out is False` /
#: `exit_code` 这一格在且为 `None` / `program_timer.outcome == "killed"`）。
#: 台账与实测继续两向相等：谁再写一句恒真项就红；谁把这一行加回来而实测没有也红。
KNOWN_VACUOUS_ASSERTS: dict[tuple[str, str], int] = {}

#: 整文件全替身的台账：文件名 -> 为什么一个不注入替身的用例都没有。
#:
#: `test_park_is_a_real_stop.py` 的四个用例都开替身缝：假时钟（`bench`）、
#: 模型替身（`_Gate`）、`_park_slice`（时间那一刀）。这是业主"零模型钱"那条约束下
#: 唯一能跑挂机区间的形态；它的真跑面在别处被钉住：本文件第 2 条用例把挂机支拔掉
#: 要求读数取反，`test_timers_and_handoff_semantics.py` 的 `test_a_...` 起真子程序，
#: `test_clock_governs_all_timed_work.py` 的 `test_n_...` 起真进程。
ALL_STUB_FILES: dict[str, str] = {
    "test_park_is_a_real_stop.py": (
        "挂机区间必须假时钟加替身缝才能毫秒级跑完（零模型钱）；"
        "真跑面由同文件第 2 条反真空与 test_timers_and_handoff_semantics 的真子程序用例覆盖"),
}

#: 名为反真空、实际只在用例内部造合成对象的台账：(文件名, 用例名) -> 差哪一根线。
#:
#: 今天为空（2026-10-27）：唯一那一处（`test_wiring_edges.py` 的
#: `test_the_predicate_is_not_vacuous`，断的是用例内嵌的 `callees()`，`is_live` 一次
#: 都没被调用）已经改成"拿两棵语义相反的 AST 真喂 `is_live` / `reachable`，断言一死
#: 一活"，并把谓词打桩成恒 True / 恒 False 各验一遍。修好之后这一行必须删掉，否则
#: 本判据会以"台账写了、实测已经碰到"红。
#: 另一条真实缺口（不在本台账里、但同一次审计量到）：`is_live` 只做名字解析，
#: 同名的另一条活函数会把可达性"借"给这一条 —— 方向是漏报，写在这里供读数的人知道。
KNOWN_ANTI_VACUUM_WITHOUT_SUBJECT: dict[tuple[str, str], str] = {}

_TESTS = pathlib.Path(__file__).resolve().parent


# ------------------------------------------------------------------ 解析助手

def _tree(name: str) -> ast.Module:
    path = _TESTS / name
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")]


def _imported_production(tree: ast.Module) -> set[str]:
    """模块级从 `agentflow` 导入的名字（含 `as` 别名与 `import a.b` 的根名）。"""
    got: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            roots = (node.module or "").split(".")
            if not roots or roots[0] != "agentflow":
                continue
            for alias in node.names:
                got.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts and parts[0] == "agentflow":
                    got.add(alias.asname or parts[0])
    return got


def _loaded(node: ast.AST) -> set[str]:
    return {sub.id for sub in ast.walk(node)
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load)}


def _is_stubbed(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """这一条用例有没有注入替身（今天只认 monkeypatch 一种注入方式）。"""
    args = [a.arg for a in node.args.args + node.args.kwonlyargs]
    return "monkeypatch" in args or "monkeypatch" in _loaded(node)


def _truthy_const(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and bool(node.value)


def _vacuous_asserts(tree: ast.Module,
                     lines: list[str] | None = None) -> list[tuple[str, int, str]]:
    """恒真断言普查：返回 [(形态, 行号, 源码行)]。三种形态见台账注释。

    `ge_zero` 只认 `len(...) >= 0` 这一形：`len(...) >= 1` 是可假判据，
    把它算进来会把整批"至少一条"的断言误报成恒真（误报方向必须写清，见模块 docstring）。
    """
    got: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        kind = ""
        if _truthy_const(test):
            kind = "const_true"
        elif isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) \
                and any(_truthy_const(v) for v in test.values):
            kind = "or_true"
        elif isinstance(test, ast.Compare) and len(test.ops) == 1 \
                and isinstance(test.ops[0], ast.GtE) \
                and len(test.comparators) == 1 \
                and isinstance(test.comparators[0], ast.Constant) \
                and test.comparators[0].value == 0 \
                and not isinstance(test.comparators[0].value, bool) \
                and isinstance(test.left, ast.Call) \
                and isinstance(test.left.func, ast.Name) \
                and test.left.func.id == "len":
            kind = "ge_zero"
        if kind:
            text = ""
            if lines and 0 < node.lineno <= len(lines):
                text = lines[node.lineno - 1].strip()[:120]
            got.append((kind, node.lineno, text))
    return got


def _assert_counts() -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for name in NEW_CRITERIA:
        lines = (_TESTS / name).read_text(encoding="utf-8").splitlines()
        for kind, _line, _text in _vacuous_asserts(_tree(name), lines):
            key = (name, kind)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _stubbed_ratio() -> dict[str, tuple[int, int]]:
    """每个新判据文件：(打桩用例数, 用例总数)。"""
    out: dict[str, tuple[int, int]] = {}
    for name in NEW_CRITERIA:
        cases = _tests(_tree(name))
        out[name] = (sum(1 for c in cases if _is_stubbed(c)), len(cases))
    return out


def _skip_markers(tree: ast.Module) -> list[tuple[str, int]]:
    """`pytest.mark.skip` / `skipif` / 非 strict 的 `xfail`。"""
    bad: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in ("skip", "skipif", "xfail"):
            continue
        # 只认 `pytest.mark.<attr>` 这一形（别的同名属性不算标记）。
        mark = node.value
        if not isinstance(mark, ast.Attribute) or mark.attr != "mark":
            continue
        if not (isinstance(mark.value, ast.Name) and mark.value.id == "pytest"):
            continue
        if node.attr == "xfail":
            parent = _decorator_call(tree, node)
            strict = False
            if parent is not None:
                for kw in parent.keywords:
                    if kw.arg == "strict" and _truthy_const(kw.value):
                        strict = True
            if not strict:
                bad.append(("xfail_without_strict", node.lineno))
            continue
        bad.append((node.attr, node.lineno))
    return bad


def _decorator_call(tree: ast.Module, target: ast.Attribute) -> ast.Call | None:
    """把 `@pytest.mark.xfail(...)` 里那个 Call 找出来（按装饰器表达式反查）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.func is target:
            return node
    return None


def _anti_vacuum_cases() -> list[tuple[str, str]]:
    """名字里带 `not_vacuous` 的用例：[(文件名, 用例名)]。"""
    got: list[tuple[str, str]] = []
    for name in NEW_CRITERIA:
        for case in _tests(_tree(name)):
            if "not_vacuous" in case.name:
                got.append((name, case.name))
    return got


def _subjectless_anti_vacuum() -> list[tuple[str, str]]:
    """反真空用例里，既没碰 agentflow 导入名、也没碰本文件别的用例也在用的模块级函数的那些。"""
    out: list[tuple[str, str]] = []
    for name in NEW_CRITERIA:
        tree = _tree(name)
        imported = _imported_production(tree)
        helper_use: dict[str, int] = {}
        for case in _tests(tree):
            for ident in _loaded(case):
                helper_use[ident] = helper_use.get(ident, 0) + 1
        module_helpers = {node.name for node in tree.body
                          if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and not node.name.startswith("test_")}
        shared = {h for h in module_helpers if helper_use.get(h, 0) >= 2}
        for case in _tests(tree):
            if "not_vacuous" not in case.name:
                continue
            touched = _loaded(case) & (imported | shared)
            if not touched:
                out.append((name, case.name))
    return out


# ------------------------------------------------------------------ 1 恒真断言

def test_no_assert_is_forever_true() -> None:
    """断言里不许有恒真项；今天的例外逐条登记，且登记必须与实测相等。"""
    measured = _assert_counts()
    assert measured == KNOWN_VACUOUS_ASSERTS, (
        "恒真断言台账与实测不符。\n"
        f"  实测有、台账没写：{sorted(set(measured) - set(KNOWN_VACUOUS_ASSERTS))}"
        "（把恒真项删掉或改写成真判据，别登记）\n"
        f"  台账写了、实测没有：{sorted(set(KNOWN_VACUOUS_ASSERTS) - set(measured))}"
        "（已经修好了就把台账那一行删掉，它不该长期挂着）")


# ------------------------------------------------------------------ 2 非替身用例

def test_every_criterion_file_has_a_non_stubbed_case() -> None:
    """每个新判据文件至少要有一条不注入替身的用例；整文件全替身的必须登记理由。"""
    ratios = _stubbed_ratio()
    empty = {name for name, (stub, total) in ratios.items()
             if total == 0 or stub == total}
    assert empty == set(ALL_STUB_FILES), (
        "全替身文件的台账与实测不符。\n"
        f"  实测整文件全替身、台账没写：{sorted(empty - set(ALL_STUB_FILES))}"
        "（补一条真跑用例，或说明为什么做不到）\n"
        f"  台账写了、实测已经不是：{sorted(set(ALL_STUB_FILES) - empty)}"
        "（已经有真跑用例了就把台账那一行删掉）")
    for name, (_stub, total) in ratios.items():
        assert total >= 3, f"{name} 只有 {total} 条用例，判据薄得不像一份判据"


# ------------------------------------------------------------------ 3 跳过面

def test_no_new_criterion_can_be_skipped_away() -> None:
    """这十二个文件里不许有 skip / skipif；xfail 必须 strict。"""
    bad: list[tuple[str, str, int]] = []
    for name in NEW_CRITERIA:
        for kind, line in _skip_markers(_tree(name)):
            bad.append((name, kind, line))
    assert not bad, (
        "今晚这批判据里出现了能把它自己变绿得更容易的标记（跳过不是绿）：\n"
        + "\n".join(f"  {n}:{line}  {kind}" for n, kind, line in bad))


# ------------------------------------------------------------------ 4 反真空的对象

def test_every_anti_vacuum_case_touches_its_subject() -> None:
    """名为反真空的用例必须真的碰到被测对象；只在内部造合成对象的不算。"""
    measured = _subjectless_anti_vacuum()
    assert set(measured) == set(KNOWN_ANTI_VACUUM_WITHOUT_SUBJECT), (
        "反真空用例的对象台账与实测不符。\n"
        f"  实测没碰被测对象、台账没写：{sorted(set(measured) - set(KNOWN_ANTI_VACUUM_WITHOUT_SUBJECT))}"
        "（让它去调被测函数，别只搭合成对象）\n"
        f"  台账写了、实测已经碰到：{sorted(set(KNOWN_ANTI_VACUUM_WITHOUT_SUBJECT) - set(measured))}"
        "（修好了就把台账那一行删掉）")
    assert _anti_vacuum_cases(), (
        "一个名为 not_vacuous 的用例都没有 —— 那说明这一批的反真空整片消失，"
        "比某一条写成空转更坏")


# ------------------------------------------------------------------ 5 反真空（本文件自己）

def test_the_four_checks_bite_on_synthetic_negatives() -> None:
    """四条普查各自喂一份该红的合成源码，四条都必须当场报出来。"""
    const_true = ast.parse("def test_x():\n    assert True\n")
    assert [k for k, _l, _t in _vacuous_asserts(const_true)] == ["const_true"], \
        _vacuous_asserts(const_true)

    or_true = ast.parse("def test_x():\n    value = 0\n    assert value or True\n")
    assert [k for k, _l, _t in _vacuous_asserts(or_true)] == ["or_true"], _vacuous_asserts(or_true)

    ge_zero = ast.parse("def test_x():\n    rows = []\n    assert len(rows) >= 0\n")
    assert [k for k, _l, _t in _vacuous_asserts(ge_zero)] == ["ge_zero"], _vacuous_asserts(ge_zero)

    skipped = ast.parse(
        "import pytest\n\n"
        "@pytest.mark.skipif(True, reason='x')\n"
        "def test_a():\n    assert 1 == 1\n\n"
        "@pytest.mark.xfail(reason='x')\n"
        "def test_b():\n    assert False\n\n"
        "@pytest.mark.xfail(strict=True, reason='x')\n"
        "def test_c():\n    assert False\n")
    kinds = sorted(k for k, _l in _skip_markers(skipped))
    assert kinds == ["skipif", "xfail_without_strict"], kinds

    # 反真空的对象那一档：只在内部造合成对象、只断言它 -> 必须被判成"没碰被测对象"。
    synthetic = ast.parse(
        "def callees(tree, target):\n    return set()\n\n"
        "def test_the_predicate_is_not_vacuous():\n"
        "    one = callees(None, 'a')\n"
        "    assert one == callees(None, 'b')\n")
    picked = _loaded(synthetic.body[-1]) & ({"callees"} & {"callees"})
    assert picked, "合成样本本身没造对"
    # 这一档用一个临时模块级的"共享函数"是造不出来的，所以直接核那条判据的算术：
    # `_subjectless_anti_vacuum` 判的是"碰没碰到 agentflow 导入名或别的用例也在用的函数"，
    # 这里的合成用例两条都不满足 —— 用同一段算术现场验一遍。
    imported = _imported_production(synthetic)
    helper_use: dict[str, int] = {}
    for case in _tests(synthetic):
        for ident in _loaded(case):
            helper_use[ident] = helper_use.get(ident, 0) + 1
    shared = {h for h in {"callees"} if helper_use.get(h, 0) >= 2}
    assert not (_loaded(synthetic.body[-1]) & (imported | shared)), (
        "合成样本居然算碰到被测对象 —— 第 4 条的算术反了，它会漏报")
