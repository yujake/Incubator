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
c. 扫全 `tests/`：凡摘掉 `AGENTFLOW_LEAN_ENABLED` 的夹具，收尾必须调用同一个助手；
   助手的定义只许有 `conftest.py` 一处（防止出现第三处"各自的修法"）；另外把这次
   真正漏掉的那条"不挂夹具的用例"单独钉住。
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
