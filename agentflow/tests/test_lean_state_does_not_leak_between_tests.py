# -*- coding: utf-8 -*-
"""判据：Lean 开关的读数不许从上一条用例漏到下一条（第二处泄漏的收口）。

## 第二处泄漏是什么（2026-11-05 实测）

`settings` 自己不缓存读数，会留在进程里的是 `agent_prompts` 的那几个 `lru_cache`
（`_lean_switch` / `_toolchain_readings` / `toolchain_facts_text`）。关档夹具把开关设成关、
并在关档下渲染过一次提示词之后，收尾若只 `importlib.reload(settings)`，缓存里仍是关档
那一次算出来的结论；而 `monkeypatch` 的 undo 在夹具之后才跑 —— 于是"环境已经回到
基线、读数还停在关档"这一档会一直活到后面每一条渲染提示词的用例。

实测读数（修前）：先跑 `tests/test_lean_modes_matrix.py` 里那条没收回基线的用例、再跑
`tests/test_lean_file_is_taught_by_channel.py`（同一进程），G 的渲染缺五条只在开档才
出现的锚点（`numeric（数值证明` / `formal（形式化）` / `` `lean_target` 必填 `` /
`无依据的声称` / `自称有数值证据`）；单独跑后者是 10 passed。

## 三条判据

a. 先跑真的"关档夹具"（`test_no_proof_without_lean.py::lean_off` 当夹具用），再在它的
   收尾之后渲染 G 的提示词 ⇒ 五条开档锚点必须都在；
b. 反真空：共用助手 :func:`conftest.restore_lean_baseline` 必须在 monkeypatch 的 undo
   之前就把环境扳回基线 —— 摘掉那一句 `setenv("1")`，同一个读法必须当场红；
c. 扫全 `tests/`，三档写法一起量（凡"关档 + 渲染过提示词"都必须把读数收回基线）：
   ① 夹具里的 `delenv` / `setenv(假值)`；② 本地包装的实参绑定（`_lean_env(monkeypatch,
   False)` 里那句 `"1" if on else "0"`）；③ 直接赋值 `os.environ[SWITCH] = 假值`。
   收尾只认两档：调用共用助手，或在豁免表里且能自证收干净（finally 里有重载口 /
   写回真值之后重载）。另有一条更窄的：凡 `delenv` 开关的夹具（哪怕它不渲染提示词）
   也必须调同一个助手 —— 助手的定义只许 `conftest.py` 一处；最后把这次真正漏掉的
   那条"不挂夹具的用例"单独钉住。
"""
from __future__ import annotations

import ast
import importlib
import warnings
from functools import lru_cache
from pathlib import Path

from agentflow import agent_prompts as AP
from agentflow import settings as SET

#: 真的"关档夹具"（a 要跑的就是它 —— 不在这里再抄一份夹具逻辑）。
from test_no_proof_without_lean import lean_off  # noqa: F401

#: 只在开档那一段才出现的五条锚点（第二处泄漏的机器读数就是这五条一起消失）。
LEAN_ON_ANCHORS: tuple[str, ...] = (
    "numeric（数值证明",
    "formal（形式化）",
    "`lean_target` 必填",
    "无依据的声称",
    "自称有数值证据",
)

#: `tests/` 落点（扫描面的根）。
TESTS_DIR = Path(__file__).resolve().parent

#: 开关的环境变量名（取唯一来源，不在这里抄第二份字面量）。
SWITCH_ENV = SET.ENV_LEAN_ENABLED

#: 共用助手的名字（判据 c 与"只有一处定义"都按它找）。
HELPER = "restore_lean_baseline"

#: 第二处泄漏真正漏掉的那条用例（不是夹具，c 的扫描面按定义扫不到它）。
UNREADABLE_CASE = ("test_lean_modes_matrix.py", "test_an_unreadable_switch_falls_back_to_off")

#: 本次修掉的那一批"关档下渲染过提示词、收尾不收回"的用例（扫描面的反真空锚点）。
KNOWN_OFF_RENDER_FIXED: tuple[tuple[str, str], ...] = (
    ("test_l_is_isolated_when_lean_is_off.py", "test_off_no_role_prompt_mentions_l"),
    ("test_l_is_isolated_when_lean_is_off.py", "test_off_l_has_no_prompt_of_its_own"),
    ("test_l_is_isolated_when_lean_is_off.py", "test_off_the_readouts_do_not_list_l"),
    ("test_l_is_isolated_when_lean_is_off.py", "test_off_the_whole_isolation_holds"),
    ("test_l_is_isolated_when_lean_is_off.py", "test_never_isolating_turns_criterion_one_red"),
    # 两条"同进程 关→开→再关"的用例：以前以"再关"收尾，缓存停在关档。
    ("test_l_is_isolated_when_lean_is_off.py", "test_the_same_process_follows_the_switch"),
    ("test_l_wiring_and_isolation_matrix.py", "test_e14_the_same_process_follows_off_on_off"),
    # 两条经 `_lean_env(monkeypatch, False)` 关档的用例：包装的实参代入后才是"关"。
    ("test_l_wiring_and_isolation_matrix.py", "test_e12_when_off_every_face_has_zero_l_and_zero_formal"),
    ("test_l_wiring_and_isolation_matrix.py", "test_e15_never_hiding_turns_e12_red"),
    ("test_l_collab_surface_is_exactly_this.py",
     "test_two_lean_off_hides_all_four_edges_and_the_role_itself"),
    # 三条直接 `os.environ[...] = ...` 关档的用例（第三档扫描面加进来之后才看见）。
    ("test_lean_switch_points_at_l.py", "test_off_leaves_no_trace_of_l"),
    ("test_lean_switch_points_at_l.py", "test_the_same_process_follows_the_switch"),
    ("test_lean_switch_points_at_l.py", "test_never_hiding_turns_the_zero_trace_criterion_red"),
)

#: "渲染过提示词层"的调用面：它们都会读 `agent_prompts` 的那几个 `lru_cache`。
#: 本地包装（`_prompt` / `_isolation_violations` …）由模块内的调用图传递解析，不在这里列。
RENDER_PRIMITIVES: frozenset[str] = frozenset({
    "system_prompt", "prompt_audit", "profiles_markdown",
    "toolchain_facts_text", "toolchain_formal_text",
    "cold_start_prompt", "index_block", "write_profiles",
})

#: "关掉"的假值写法（与 `settings._FALSE_WORDS` 同族；这里只认字面量）。
FALSE_WORDS: frozenset[str] = frozenset({"0", "false", "no", "off", "n", "f"})

#: 重载口（清 `agent_prompts` 那几个 `lru_cache` 的两个公开/本地写法）。
RELOADERS: frozenset[str] = frozenset({"reset_toolchain_readings", "_reload_switch"})

#: 豁免面（2026-11-05 显式登记）：这些函数摘了开关、也渲染过提示词，但它们自己把
#: 读数清干净了 —— 与共用助手做的是同一件事，只是没经过那一个函数。每一条都必须
#: 通过 :func:`_ends_clean_by_itself`，否则豁免无效（见 c 扩面那条判据）。
EXEMPT_TAIL_RESET: frozenset[tuple[str, str]] = frozenset({
    # finally 里 `AP.reset_toolchain_readings()`：缓存清掉之后用例就退出，下一次读
    # 发生在 monkeypatch 的 undo 之后（环境已是基线）⇒ 从基线重新算，不留关档读数。
    ("test_lean_file_is_taught_by_channel.py",
     "test_the_closed_tier_still_requires_lean_file_for_the_numeric_channel"),
    # 下面三条自己把开关写回 "1" 再清缓存（finally 里，或最后两句），收尾那一刻
    # 缓存是按基线算的 —— 同样不会把关档读数留给后面的用例。
    ("test_lean_switch.py", "test_the_prompt_blocks_follow_the_switch"),
    ("test_lean_switch.py", "test_the_no_lean_variant_rewrites_every_role_face"),
    ("test_lean_switch.py", "test_a_corrupted_entry_in_the_rewrite_table_is_reported_by_name"),
    # 直接写 `os.environ[...] = "0"` 的两处（第三档扫描面见到的）：都在 finally 里
    # 按原值放回环境变量并 `AP.reset_toolchain_readings()` —— 与另外三处同一种收法。
    ("test_g_h_v_l_prompt_has_no_stale_design.py", "corpus"),
    ("test_g_h_v_l_prompt_has_no_stale_design.py",
     "test_the_g_no_lean_table_rewrites_every_left"),
})


# --------------------------------------------------------------------------- 读法


def _g_text() -> str:
    """G 的可见面（与 `test_lean_file_is_taught_by_channel._prompt("G")` 同形）。"""
    from agentflow.tools import build_registry

    return AP.system_prompt("G", registry=build_registry().registry)


def _missing(text: str) -> list[str]:
    """这一段文本缺哪几条开档锚点（顺序按 :data:`LEAN_ON_ANCHORS`）。"""
    return [anchor for anchor in LEAN_ON_ANCHORS if anchor not in text]


def _enter_closed_tier(tmp_path: Path, monkeypatch) -> None:
    """关档夹具的开头（与 `test_no_proof_without_lean.py::lean_off` 逐句同形）。

    刻意不在这里调共用助手：这一句是"夹具在开头做的那几步"，收尾那一步由 a/b
    两条分别量（经过夹具、与不经过夹具各一次）。
    """
    empty = tmp_path / "settings.json"
    empty.write_text('{"toolchain": {"lean_enabled": false, "lean_bin": ""}}',
                     encoding="utf-8")
    monkeypatch.setenv(SET.ENV_SETTINGS, str(empty))
    monkeypatch.delenv(SWITCH_ENV, raising=False)
    monkeypatch.delenv("AGENTFLOW_LEAN_BIN", raising=False)
    importlib.reload(SET)


# --------------------------------------------------------------------------- a


def test_the_closed_fixture_primes_the_off_readings(lean_off) -> None:
    """a 的前半：先跑真的关档夹具，并在关档下把 G 渲染一次。

    为什么这里要 `importlib.reload(AP)`：全套判据跑在开档，模块缓存多半已经算过开档
    读数，而关档夹具只重载 settings。这一句与 `test_lean_modes_matrix._prompts()` 同形，
    也是"关档下渲染过一次"这个载体的最小复现 —— 少了它，下一条量到的可能是别的用例
    留下的开档读数，判据就成了"看谁先跑"。
    """
    assert bool(lean_off.lean_enabled()[0]) is False, "关档夹具没有真的把开关关掉"
    importlib.reload(AP)
    missing = _missing(_g_text())
    assert missing == list(LEAN_ON_ANCHORS), (
        f"关档那一档仍带着这些开档锚点：{missing} ⇒ 这一条判据没有落脚点")


def test_g_after_the_closed_fixture_speaks_lean_again() -> None:
    """a：上一条的夹具收尾之后，G 的五条开档锚点必须都在（修前这里红的正是这五条）。

    刻意不挂夹具：要量的就是"上一条收尾之后"的读数 —— 挂上它又会把关档重新装回来。
    """
    text = _g_text()
    missing = _missing(text)
    assert missing == [], (
        "关档夹具的收尾把关档读数漏到了下一条用例：G 缺 " + repr(missing))


# --------------------------------------------------------------------------- b


def test_the_helper_returns_to_the_baseline_before_the_undo(tmp_path, monkeypatch) -> None:
    """b（反真空）：助手必须在 monkeypatch 的 undo 之前就把环境扳回基线。

    这里刻意不经过夹具：`monkeypatch` 的 undo 在本用例收尾才跑，所以调用助手之后
    立刻渲染读到的就是助手自己设的那一档。把助手里那句 `setenv("1")` 摘掉 ⇒
    这一条立刻红（2026-11-05 实测：1 failed）。
    """
    _enter_closed_tier(tmp_path, monkeypatch)
    importlib.reload(AP)
    assert _missing(_g_text()) == list(LEAN_ON_ANCHORS), "关档这一档没有量到（b 没有落脚点）"

    from conftest import restore_lean_baseline

    restore_lean_baseline(monkeypatch)
    missing = _missing(_g_text())
    assert missing == [], (
        "助手调用之后（monkeypatch 还没 undo）读到的仍是关档那一份：缺 " + repr(missing))


# --------------------------------------------------------------------------- c


def _call_name(func: ast.AST) -> str:
    """一个调用点的名字（`f(...)` 取 `f`，`m.f(...)` 取 `f`）。"""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _names_the_switch(node: ast.AST) -> bool:
    """这个实参是不是 Lean 开关的环境变量名（字面量或 `SET.ENV_LEAN_ENABLED`）。"""
    if isinstance(node, ast.Constant) and node.value == SWITCH_ENV:
        return True
    return isinstance(node, ast.Attribute) and node.attr == "ENV_LEAN_ENABLED"


def _is_os_environ(node: ast.AST) -> bool:
    """这个表达式是不是 `os.environ`（直接赋值那一档的落点）。"""
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _literal_value(node: ast.AST, bindings: dict[str, object]):
    """一个字面量实参在 `bindings` 下的取值（`"1" if on else "0"` 这种写法也解）。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.IfExp):
        test = node.test
        if isinstance(test, ast.Name) and test.id in bindings:
            return _literal_value(node.body if bindings[test.id] else node.orelse, bindings)
        return None
    if isinstance(node, ast.Name) and node.id in bindings:
        return bindings[node.id]
    return None


def _turns_switch_off(node: ast.AST, defs: dict[str, ast.AST],
                      bindings: dict[str, object] | None = None,
                      seen: set[tuple] | None = None) -> bool:
    """这个函数会不会把 Lean 开关摘掉 / 写成假值（三档写法一起认）。

    三档：
    ① `monkeypatch.delenv` / `setenv(SWITCH, 假值)`；
    ② 本地包装的实参绑定（`_lean_env(monkeypatch, False)` 里的
       `"1" if on else "0"` 只有把实参代进去才知道这一档是关）；
    ③ 直接赋值 `os.environ[SWITCH] = 假值`（2026-11-05 补的一档：先做过全树普查，
       当时 0 处"关档 + 渲染 + 不收回"，所以加进扫描面没有可修对象；加它是防将来
       有人用这种写法泄漏、而判据看不见）。
    """
    bindings = {} if bindings is None else bindings
    seen = set() if seen is None else seen
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign) and len(sub.targets) == 1:
            target = sub.targets[0]
            if isinstance(target, ast.Subscript) and _is_os_environ(target.value) \
                    and _names_the_switch(target.slice):
                value = _literal_value(sub.value, bindings)
                if value is not None and str(value).strip().lower() in FALSE_WORDS:
                    return True
            continue
        if not isinstance(sub, ast.Call):
            continue
        callee = _call_name(sub.func)
        if callee == "delenv" and sub.args and _names_the_switch(sub.args[0]):
            return True
        if callee == "setenv" and len(sub.args) >= 2 and _names_the_switch(sub.args[0]):
            value = _literal_value(sub.args[1], bindings)
            if value is not None and str(value).strip().lower() in FALSE_WORDS:
                return True
        target = defs.get(callee)
        if target is None:
            continue
        params = [a.arg for a in getattr(target.args, "args", [])]
        inner: dict[str, object] = {}
        for param, arg in zip(params, sub.args):
            value = _literal_value(arg, bindings)
            if value is not None:
                inner[param] = value
        key = (callee, tuple(sorted((k, repr(v)) for k, v in inner.items())))
        if key in seen:
            continue
        seen.add(key)
        if _turns_switch_off(target, defs, inner, seen):
            return True
    return False


def _local_call_graph(tree: ast.Module) -> dict[str, set[str]]:
    """模块内的调用图（模块顶层的函数 → 它们直接调到的名字）。"""
    graph: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            graph[node.name] = {_call_name(sub.func) for sub in ast.walk(node)
                                if isinstance(sub, ast.Call)}
    return graph


def _renders_prompts(name: str, graph: dict[str, set[str]],
                     seen: set[str] | None = None) -> bool:
    """这个函数（顺着模块内调用图）会不会读到提示词层。

    本地包装也要算：`_prompt` / `_l_prompt_problem` / `_isolation_violations` 这些
    函数自己就是"渲染一次提示词"的载体（它们最后都落到 `system_prompt` /
    `profiles_markdown` 上），只按名字里有没有 `prompt` 判会漏掉后两者。
    """
    seen = set() if seen is None else seen
    if name in seen:
        return False
    seen.add(name)
    callees = graph.get(name, set())
    if callees & RENDER_PRIMITIVES:
        return True
    return any(_renders_prompts(callee, graph, seen)
               for callee in callees if callee in graph)


def _off_tier_render_sites() -> list[tuple[str, str, bool, int]]:
    """摘开关 + 渲染过提示词层：`(文件, 函数名, 调了共用助手?, 行号)`。"""
    out: list[tuple[str, str, bool, int]] = []
    for file_name, tree in _parse_test_files():
        graph = _local_call_graph(tree)
        defs = {node.name: node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _turns_switch_off(node, defs) or not _renders_prompts(node.name, graph):
                continue
            calls = {_call_name(sub.func) for sub in ast.walk(node)
                     if isinstance(sub, ast.Call)}
            out.append((file_name, node.name, HELPER in calls, node.lineno))
    return out


def _ends_clean_by_itself(fn: ast.AST) -> bool:
    """这个函数自己把读数收回去了吗（豁免面的结构判据，两档都认）。

    ① `try/finally` 的 finally 里调了重载口；
    ② 它把开关写回真值，并在那之后调过重载口（`test_the_prompt_blocks_follow_the_switch`
       就是"最后两句把 1 写回去再清缓存"那种写法）。

    只认这两档，是因为它们与共用助手等价：缓存被清掉之后，下一次读发生在
    monkeypatch 的 undo 之后（环境已是基线），算出来的一定是基线那一档。
    """
    for sub in ast.walk(fn):
        if not isinstance(sub, ast.Try):
            continue
        tail = [n for stmt in sub.finalbody for n in ast.walk(stmt)]
        if any(isinstance(n, ast.Call) and _call_name(n.func) in RELOADERS for n in tail):
            return True
    set_true: list[int] = []
    reset_lines: list[int] = []
    for sub in ast.walk(fn):
        if not isinstance(sub, ast.Call):
            continue
        callee = _call_name(sub.func)
        if callee == "setenv" and len(sub.args) >= 2 and _names_the_switch(sub.args[0]):
            value = sub.args[1]
            if isinstance(value, ast.Constant) \
                    and str(value.value).strip().lower() not in FALSE_WORDS:
                set_true.append(sub.lineno)
        if callee in RELOADERS:
            reset_lines.append(sub.lineno)
    return any(line < reset for line in set_true for reset in reset_lines)


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """这个函数有没有挂 `@pytest.fixture`（含带参写法）。"""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
    return False


@lru_cache(maxsize=1)
def _parsed_trees() -> tuple[tuple[str, ast.Module], ...]:
    """`tests/*.py` 全部解析一次（只读；扫描面是整份测试目录，解析结果按会话缓存）。

    解析别人的文件会把它 docstring 里那些"无效转义"的编译期告警带进本文件的告警面；
    本判据只读语法树、从不执行那些文件，所以那一档告警在这里就地关掉（它们不是
    这条判据的读数，也不该在报告里冒充它）。
    """
    out: list[tuple[str, ast.Module]] = []
    for path in sorted(TESTS_DIR.glob("*.py")):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        out.append((path.name, tree))
    return tuple(out)


def _parse_test_files() -> list[tuple[str, ast.Module]]:
    """只看 `test_*.py`（判据面；`conftest.py` 用 `_functions_defining` 的读数单独看）。"""
    return [(name, tree) for name, tree in _parsed_trees() if name.startswith("test_")]


def _sites_that_remove_the_switch() -> list[tuple[str, str, bool, bool, int]]:
    """扫到的全部"摘开关"函数：`(文件, 函数名, 是夹具?, 收尾调了助手?, 行号)`。

    只看模块顶层的函数定义（夹具与用例都在那一层）：嵌在函数里的局部定义不是
    夹具面，把它算进来会把"别人的局部状态"记成"这里漏了"。
    """
    out: list[tuple[str, str, bool, bool, int]] = []
    for name, tree in _parse_test_files():
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            removes = False
            restores = False
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                if isinstance(sub.func, ast.Attribute) and sub.func.attr == "delenv":
                    if sub.args and _names_the_switch(sub.args[0]):
                        removes = True
                if _call_name(sub.func) == HELPER:
                    restores = True
            if removes:
                out.append((name, node.name, _is_fixture(node), restores, node.lineno))
    return out


def _functions_defining(name: str) -> list[str]:
    """哪些文件在模块顶层定义了同名函数（"只有一处定义"的机器读数）。"""
    found: list[str] = []
    for file_name, tree in _parsed_trees():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                found.append(file_name)
    return found


def _function_node(file_name: str, func_name: str):
    """按文件名 + 函数名取一个顶层函数节点（找不到 ⇒ None）。"""
    for name, tree in _parse_test_files():
        if name != file_name:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == func_name:
                return node
    return None


def test_every_fixture_that_removes_the_switch_restores_the_baseline() -> None:
    """c：凡摘掉 `AGENTFLOW_LEAN_ENABLED` 的夹具，收尾必须调用同一个助手。

    扫描面刻意是全 `tests/` 而不是这两个文件：这条判据上一次漏掉的正是一种"第三处"
    —— 同一份文件里还有一条用例不挂夹具、自己重载提示词层，收尾什么都不做
    （见下一条判据）。扫描自己也要能自证不空转：至少两条夹具、且这两个文件都在名单里。
    """
    sites = _sites_that_remove_the_switch()
    fixtures = [one for one in sites if one[2]]
    assert len(fixtures) >= 2, f"扫描没读到夹具（不空转的底线）：{sites}"
    files = {one[0] for one in fixtures}
    assert {"test_no_proof_without_lean.py", "test_lean_modes_matrix.py"} <= files, files
    missing = [(name, func, line) for name, func, _fx, restores, line in fixtures
               if not restores]
    assert missing == [], f"这些夹具摘了开关却没有把基线收回来：{missing}"

    defined_in = _functions_defining(HELPER)
    assert defined_in == ["conftest.py"], (
        f"共用助手只许有 {HELPER} 一处定义（conftest.py），实际：{defined_in} —— "
        "两处定义就是两份'各自的修法'")


def test_every_off_tier_render_restores_the_baseline() -> None:
    """c（扩面）：摘了开关又渲染过提示词的函数，收尾必须回到基线。

    为什么扩这一面：泄漏的载体是"关档下渲染过一次"，光看夹具抓不到那些不挂夹具、
    自己在用例里关档渲染的写法 —— 2026-11-05 按 node-id 抽跑时 G 缺五条锚点，
    漏的就是 `test_l_is_isolated_when_lean_is_off.py` 里那 5 条（见
    :data:`KNOWN_OFF_RENDER_FIXED`）。

    三档写法一起量（见 :func:`_turns_switch_off`）：`monkeypatch.delenv/setenv`、
    本地包装的实参绑定、直接赋值 `os.environ[SWITCH] = 假值`。第三档是 2026-11-05
    补进来的：先做过全树普查（当时没有"关档 + 渲染 + 不收回"的对象），加它是防将来
    有人用这种写法泄漏而判据看不见；加进来之后按同一把尺子又看见 5 处 —— 3 条用例
    收尾改调助手，2 处（一个 module 夹具 + 一条用例）本来就在 finally 里按原值放回
    环境并重载，进豁免面。

    豁免面见 :data:`EXEMPT_TAIL_RESET`：每条都必须能自证"自己把读数清干净了"
    （:func:`_ends_clean_by_itself`），而且豁免表不许留永不生效的条目 ——
    把一条真漏的放进来，第一条断言就会红。
    """
    sites = _off_tier_render_sites()
    found = {(file_name, func) for file_name, func, _restored, _line in sites}
    assert set(KNOWN_OFF_RENDER_FIXED) <= found, (
        "扫描面没读到已知的那批关档渲染函数（扩面判据没有落脚点）："
        f"{sorted(found)}")
    assert not (set(KNOWN_OFF_RENDER_FIXED) & EXEMPT_TAIL_RESET), (
        "本次修掉的那批不许再挂在豁免面上（那等于把真漏的当免检）")

    missing = [(file_name, func, line) for file_name, func, restored, line in sites
               if not restored and (file_name, func) not in EXEMPT_TAIL_RESET]
    assert missing == [], (
        "这些函数摘了开关、渲染过提示词，却没有把基线收回来"
        f"（收尾调用 {HELPER}）：{missing}")

    stale = sorted(EXEMPT_TAIL_RESET - found)
    assert stale == [], (
        "豁免表里这些条目已经不再摘开关/渲染提示词了（一张永不生效的表要收）："
        f"{stale}")
    for file_name, func in sorted(EXEMPT_TAIL_RESET):
        node = _function_node(file_name, func)
        assert node is not None, f"豁免条目找不到落脚点：{file_name}::{func}"
        assert _ends_clean_by_itself(node), (
            f"豁免不成立：{file_name}::{func} 既没有 finally 里的重载口，"
            "也没有在写回真值之后重载 —— 它和真漏的那几条是同一种写法")


def test_the_unreadable_switch_case_restores_the_baseline() -> None:
    """c（第二处）：真正漏掉的那条用例不是夹具，单独钉住它。

    `test_an_unreadable_switch_falls_back_to_off` 自己 `delenv` 开关、把设置文件指到
    一份读不懂的配置、重载 settings 与提示词层，然后什么都不收回 —— 同一进程里它跑在
    前面时，G 的五条开档锚点就消失（2026-11-05 实测：那条命令 1 failed / 10 passed）。
    """
    node = _function_node(*UNREADABLE_CASE)
    assert node is not None, f"找不到 {UNREADABLE_CASE} —— 它改名/搬走了？这条守卫没有落脚点"
    calls = {_call_name(sub.func) for sub in ast.walk(node) if isinstance(sub, ast.Call)}
    assert HELPER in calls, (
        f"{UNREADABLE_CASE[1]} 没有调用 {HELPER} —— 第三处又长出来了")


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
