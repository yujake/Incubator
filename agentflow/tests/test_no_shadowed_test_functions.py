# -*- coding: utf-8 -*-
"""R7-⑳ 模块级重名测试函数：后者遮蔽前者，而被遮蔽的那个永远不跑。

形态（`draft/58` §2 ⑳）：同一文件里两个同名 `def test_*` ⇒ pytest 按名字收，
同名定义里只有最后一个成为模块属性 ⇒ 前一个永远不执行，而全量门照样全绿、
条数也不变（收的是"名字"，不是"定义"）。这是"读数看不出来"的那一类缺陷：
删掉被遮蔽的那块，测试条数与结论一个字都不变。

`R0` 修过两处真事故（判据用它们当形态样本）：
1. `tests/test_autonomy_resume.py`：两块完全相同（删掉重复那块，188→164 行，7 passed）；
2. `tests/test_release_check_noai.py`：两块不同（保留强的那块：它断言得更细；
   删掉死的那块。27 passed）。

三态：判据自己给读数（扫了几个文件 / 几个模块级 test 函数 / 几处重名），
别让"0 个文件"与"0 处重名"同形。
"""
from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 被遮蔽的定义长什么样：模块级（`mod.body` 直接成员）的 `def test_*` / `async def test_*`。
#: 刻意不扫类里的方法：同一个类里两个同名方法同样是遮蔽，但那是另一族
#: （pytest 收的是 `类::方法`，遮蔽发生在类体内），本批只治模块级那一族。
_TEST_PREFIX = "test"


def _module_test_defs(src: str) -> list[tuple[str, int]]:
    """模块级 `def test_*` 的 (名字, 行号) 清单（按源码顺序）。

    读不出来（`SyntaxError`）⇒ 抛：一份正在被写的半截文件不该被读成"没有重名"
    （三态纪律：读不到不是通过）。调用方按文件捕获并把它当读数报出来。

    名字刻意不带 `test_` 前缀：`pytest` 会把模块里任何 `test*` 可调用当用例收，
    这个 helper 会被当成一条缺参数的用例（本文件第一次跑就是这么红的）。
    """
    tree = ast.parse(src)
    got: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith(_TEST_PREFIX):
            got.append((node.name, node.lineno))
    return got


def shadowed_names(src: str) -> list[str]:
    """模块级重名的测试函数 ⇒ 逐条问题（空表 = 没有重名）。"""
    seen: dict[str, list[int]] = {}
    for name, lineno in _module_test_defs(src):
        seen.setdefault(name, []).append(lineno)
    return [f"`{name}` 在这个文件里定义了 {len(lines)} 次（行 {lines}）—— "
            "pytest 只收最后一个（按名字收），前面那些定义永远不会执行，"
            "而全量门的条数与结论一个字都不变"
            for name, lines in sorted(seen.items()) if len(lines) > 1]


def _scan_shadowed(files: list[pathlib.Path]) -> tuple[list[str], list[str], int]:
    """扫这批文件 ⇒ (重名问题, 读不出来的文件, 模块级测试函数总数)。

    读不出来的单列一档（不许并进"没问题"）：一份正在被写的半截文件既不是
    "没有重名"，也不该让整条判据崩掉。
    """
    problems: list[str] = []
    unreadable: list[str] = []
    total = 0
    for path in files:
        rel = path.relative_to(REPO).as_posix() if REPO in path.parents else path.name
        try:
            src = path.read_text(encoding="utf-8")
            defs = _module_test_defs(src)
        except SyntaxError as exc:
            unreadable.append(f"{rel}: 读不出来（{exc.msg}）⇒ 这一份没查成，不是没问题")
            continue
        total += len(defs)
        problems += [f"{rel}:{p}" for p in shadowed_names(src)]
    return problems, unreadable, total


def test_no_module_level_test_function_is_shadowed() -> None:
    """仓级：`tests/` 下每个文件里，模块级测试函数名不许重复。"""
    _assert_shadow_negative_controls()
    files = sorted((REPO / "tests").rglob("*.py"))
    assert len(files) >= 100, f"`tests/` 下只读到 {len(files)} 个文件 ⇒ 枚举面坏了"
    problems, unreadable, total = _scan_shadowed(files)

    reading = {"files_scanned": len(files), "module_test_defs": total,
               "unreadable_files": len(unreadable), "shadowed": len(problems)}
    assert not unreadable, ("有文件读不出来 ⇒ 那几份没进扫描面（读数里不许把它读成干净）："
                            + "；".join(unreadable))
    assert reading["module_test_defs"] >= 1000, (
        f"模块级测试函数只数到 {reading['module_test_defs']} 个 ⇒ 扫描器多半没接上"
        f"（不是没问题）：{reading}")
    assert not problems, (
        f"模块级重名 `def test_*` ⇒ 被遮蔽的那个永远不会执行（读数 {reading}）："
        + "；".join(problems))


def test_a_duplicate_in_a_fixture_directory_is_reported(tmp_path: pathlib.Path) -> None:
    """负控（夹具注入）：真的造一份带重名的文件 ⇒ 仓级那条扫描必须报出来。

    为什么不往真仓的某个测试文件里插一行再还原：那会让受审源码在盘上带一段假定义
    （硬杀 pytest 就留在那儿），同树并发的另一个 pytest 还会读到瞬时注入 ——
    `test_r5_orchestration_cost.py` 的 `_probe_tree_copy` 上面逐字记着这个教训。
    所以注入落在 `tmp_path`，扫的还是同一个函数 `_scan_shadowed`。
    """
    dup = ("def test_repeated():\n    assert True\n\n\n"
           "def test_repeated():\n    assert True\n")
    fixture = tmp_path / "test_shadow_fixture_case.py"
    fixture.write_text(dup, encoding="utf-8")
    problems, unreadable, total = _scan_shadowed([fixture])
    assert not unreadable, unreadable
    assert total == 2, f"夹具里应当数到 2 处模块级定义，实得 {total}"
    assert len(problems) == 1 and "定义了 2 次" in problems[0], (
        f"夹具里的重名必须被仓级扫描报出来（否则这条判据是橡皮图章）：{problems}")


def _assert_shadow_negative_controls() -> None:
    """负控：夹具里造一对同名函数 ⇒ 必须报；并证明后一个才是被收集的那个。

    行为面的证据用 `exec` 一份内存模块：两个定义都在 `ast` 里看得见（2 处），
    而模块名字空间里只剩一个函数对象、且它的 `co_firstlineno` 指向第二次定义
    ⇒ 前一个在 pytest 眼里从来不存在。这就是"条数不变而那个测试永远不跑"的机制。
    """
    dup = ("def test_same():\n    assert True\n\n\n"
           "def test_same():\n    assert False  # 后一个才是被收的\n")
    got = shadowed_names(dup)
    assert got and "定义了 2 次" in got[0], f"夹具里的重名没被报出来：{got}"
    assert len(_module_test_defs(dup)) == 2, "ast 面应当看得见两处定义"

    namespace: dict = {}
    exec(compile(dup, "<shadow-fixture>", "exec"), namespace)  # noqa: S102 —— 注入自己写的字节
    collected = {k: v for k, v in namespace.items() if k.startswith("test")}
    assert len(collected) == 1, (
        f"夹具不成立：模块名字空间里应当只剩一个测试函数，实得 {sorted(collected)}")
    assert collected["test_same"].__code__.co_firstlineno == 5, (
        "被收集的不是最后一个定义 ⇒ 这条负控的机制说明不成立"
        f"（co_firstlineno={collected['test_same'].__code__.co_firstlineno}）")
    assert shadowed_names("def test_a():\n    assert True\n") == [], \
        "不重复的模块被报成重名 ⇒ 判据会乱叫"
