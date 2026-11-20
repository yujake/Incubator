# -*- coding: utf-8 -*-
"""temp/ 是工作台，不是仓库：三条判据钉住「临时目录能清、干净东西不活在 temp」。

## 为什么有这三条（2026-11-20 业主指令）

业主原话：「temp目录清理是需要的，请派人做。别把有用的东西做在temp里」。
`AGENTS.md` R2 只说了「一次性脚本 / 取证探针 / 读数导出放 `temp/`」，没说反面：
长期有用的东西不许只活在 `temp/` —— 它不入库、别人看不见、下一个人不会用。
两条合起来才是判据：一次性可以留 temp、可以清；长期有用的必须进 `scripts/` 一类的地方。

现场读数（TEMPTIDY 路，2026-11-20）：`%TEMP%` 里 `role-specs-face-*` 积了 3103 个 ——
`tools/verify_role_specs.py::live_tool_face()` 每装配一次注册表就 `mkdtemp` 一个工作区、
从不删。所以光「这次清掉」不够，得有一条判据看着它不再积。

## 三条

1. `src/` 与 `tests/` 不许 import `temp/` 下的模块（AST 扫描）。temp 不入库、不进分发，
   从它 import 等于把判据/实现挂在一份随时会被清的目录上 —— 清垃圾那天就断。
   反真空：造一份 `from temp.helper import x` 的假样本，扫描器必须报红；
   再造一份 `spec_from_file_location(..., "temp/x.py")` 的假样本，同样必须报红。
2. 会 `mkdtemp` 的判据跑完之后，临时根里不许留下新目录。反真空：故意不清理的负控
   必须在同一个装置下留下 1 个目录 —— 否则「0 个」可能只是装置没接上（判据真空）。
3. `scripts/` 下这几个从 temp 提升上来的长期工具必须 `--help` 跑得起来（退出码 0）。
   反真空：一个 `--help` 直接退 3 的假脚本必须被判红。

三态纪律：扫描器读不出/解析不了不是通过 —— 第 1 条把解析失败记成违规并给出路径。
"""
from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys
import warnings

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 从 `temp/` 提升进 `scripts/` 的长期工具（各自 README 有一行用法）。
#: 新增长期工具时把它加进这张表 —— 否则它会从判据面上消失（这正是 R2 的反面）。
SCRIPTS_TOOLS = (
    "safe_comment_fix.py",
    "recompute_prompt_digests.py",
    "refreeze_goldens.py",
    "recompute_map_headline.py",
)

_DYNAMIC_LOADERS = {"spec_from_file_location", "import_module", "SourceFileLoader"}


def _path_mentions_temp(value: str) -> bool:
    """字符串是不是指向 `temp/` 下的一个文件（按路径分段判，不按子串）。"""
    parts = pathlib.PurePath(value.replace("\\", "/")).parts
    return "temp" in parts


def scan_temp_imports(root: pathlib.Path) -> list[str]:
    """扫一棵树：返回 `["路径:行: 理由", ...]`；空列表 = 查过、干净。

    判据面（AST，不是 grep）：
    - `import temp.x` / `from temp.x import y`（模块名首段恰好是 `temp`）；
    - `importlib.util.spec_from_file_location(...)` / `import_module(...)` 的字符串实参
      落在 `temp/` 下（路径分段含 `temp`）；
    - `sys.path.insert(...)` 塞进一个 `temp/` 路径。
    解析失败（`SyntaxError`）记成违规，不跳过 —— 解析不了的那份文件没有被检查过。
    """
    found: list[str] = []
    scanned = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in {"__pycache__", ".pytest_cache", ".pytest-tmp"} for part in path.parts):
            continue
        scanned += 1
        try:
            src = path.read_text(encoding="utf-8")
            with warnings.catch_warnings():
                # 只取 AST：被扫文件里的非法转义（`\/`、`\`` 一类）会发
                # DeprecationWarning，但那不是本判据要管的事，别把它灌进跑测输出。
                warnings.simplefilter("ignore", DeprecationWarning)
                tree = ast.parse(src)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            found.append(f"{path}:0: 解析不了，没检查过（{type(exc).__name__}: {exc}）")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "temp":
                        found.append(f"{path}:{node.lineno}: import {alias.name}（temp 不入库、随时会被清）")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[0] == "temp":
                    found.append(f"{path}:{node.lineno}: from {mod} import …（temp 不入库、随时会被清）")
            elif isinstance(node, ast.Call):
                name = ""
                func = node.func
                if isinstance(func, ast.Attribute):
                    name = func.attr
                elif isinstance(func, ast.Name):
                    name = func.id
                if name in _DYNAMIC_LOADERS:
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                                and _path_mentions_temp(arg.value):
                            found.append(
                                f"{path}:{node.lineno}: {name}({arg.value!r})（按路径加载 temp 下的模块）")
                if name == "insert" and isinstance(func, ast.Attribute) \
                        and isinstance(func.value, ast.Attribute) \
                        and func.value.attr == "path":
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                                and _path_mentions_temp(arg.value):
                            found.append(
                                f"{path}:{node.lineno}: sys.path.insert(… {arg.value!r})（把 temp 塞进 import 路径）")
    # 反真空：一个源文件都没扫到的扫描器与一棵真的干净的树在输出上完全一样。
    if scanned == 0:
        found.append(f"{root}:0: 一个 .py 都没扫到 ⇒ 扫描器没接上（不是干净）")
    return found


def _help_ok(script: pathlib.Path) -> bool:
    """`--help` 跑得起来就是 True（退出码 0 且打印了用法）。"""
    try:
        done = subprocess.run([sys.executable, str(script), "--help"],
                              cwd=str(REPO), capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    # 子进程输出是 UTF-8（PYTHONUTF8 / 本仓的编码约定）；Windows 的 locale 是 GBK，
    # 用 text=True 会在 reader 线程里 UnicodeDecodeError —— 那个线程异常会变成
    # 一条 PytestUnhandledThreadExceptionWarning，把"退出码"这条真读数淹掉。
    out = (done.stdout or b"").decode("utf-8", "replace") + \
        (done.stderr or b"").decode("utf-8", "replace")
    return done.returncode == 0 and "usage" in out.lower()


# ------------------------------------------------------------------ 判据 1


def test_src_and_tests_never_import_from_temp():
    """`src/` 与 `tests/` 都不许从 `temp/` import（temp 不入库、随时会被清）。"""
    for part in ("src", "tests"):
        found = scan_temp_imports(REPO / part)
        assert not found, "从 temp/ import 的违规：\n" + "\n".join(found)


def test_the_scan_catches_a_fake_temp_import():
    """反真空：人造样本里 `from temp.helper import x` 与 `spec_from_file_location(..., "temp/x.py")` 必红。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="temp-scan-sample-") as td:
        root = pathlib.Path(td)
        (root / "bad_import.py").write_text(
            "from temp.helper import x\n\n\ndef f():\n    return x\n", encoding="utf-8")
        (root / "bad_dynamic.py").write_text(
            "import importlib.util\n\n"
            "importlib.util.spec_from_file_location('m', 'temp/helper.py')\n", encoding="utf-8")
        (root / "ok.py").write_text(
            "import tempfile\n\n\ndef f():\n    return tempfile.gettempdir()\n", encoding="utf-8")
        found = scan_temp_imports(root)
        text = "\n".join(found)
        assert "bad_import.py" in text, f"假样本没被认出来：{found}"
        assert "bad_dynamic.py" in text, f"按路径加载 temp 的假样本没被认出来：{found}"
        assert "ok.py" not in text, f"干净的样本被误报：{found}"


# ------------------------------------------------------------------ 判据 2


def _run_with_private_temp(root: pathlib.Path, argv: list[str]) -> int:
    """在一个私有临时根下跑一条命令（TEMP/TMP/TMPDIR 三档全钉到它）。"""
    env = dict(os.environ)
    env.update({"TEMP": str(root), "TMP": str(root), "TMPDIR": str(root),
                "PYTHONUTF8": "1"})
    done = subprocess.run(argv, cwd=str(REPO), env=env,
                          capture_output=True, timeout=300)
    return done.returncode


def test_a_mkdtemp_gate_leaves_no_new_temp_dir():
    """跑一次会 `mkdtemp` 的判据（角色规格门）之后，私有临时根里新目录数必须是 0。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="temp-hygiene-gate-") as td:
        root = pathlib.Path(td)
        # 反真空：故意不清理的负控必须留下 1 个目录 —— 证明装置真的接上了。
        leak = "import tempfile, pathlib\n" \
               "pathlib.Path(tempfile.mkdtemp(prefix='leak-proof-'))\n"
        _run_with_private_temp(root, [sys.executable, "-c", leak])
        leaked = list(root.glob("leak-proof-*"))
        assert len(leaked) == 1, (
            "负控没在私有临时根下造出目录 ⇒ 这条判据的装置没接上（0 个新目录可能只是没测到）"
            f"；实际 {[p.name for p in root.iterdir()]}")

        # 正题：角色规格门每跑一次都会装配一份注册表（旧版在这里 mkdtemp 且不删）。
        code = _run_with_private_temp(
            root, [sys.executable, str(REPO / "tools" / "verify_role_specs.py"),
                   "--root", str(REPO), "--json"])
        assert code in (0, 1), f"角色规格门跑了但没给出结论（退出码 {code}）—— 没查成不是干净"
        left = [p.name for p in root.glob("role-specs-face-*")]
        assert not left, (
            f"跑一次角色规格门之后临时根里还留着 {len(left)} 个 role-specs-face-* 目录：{left[:5]}…"
            "（产出它的代码必须用 try/finally 或 tempfile.TemporaryDirectory 收尾）")


# ------------------------------------------------------------------ 判据 3


def test_scripts_tools_answer_help():
    """`scripts/` 下这几个长期工具必须 `--help` 跑得起来（退出码 0，打印 usage）。"""
    assert SCRIPTS_TOOLS, "工具清单空了 ⇒ 这条判据在测一个空集合（判据真空）"
    broken = [name for name in SCRIPTS_TOOLS
              if not (REPO / "scripts" / name).is_file()
              or not _help_ok(REPO / "scripts" / name)]
    assert not broken, f"这些 scripts/ 工具 `--help` 跑不起来：{broken}"


def test_the_help_smoke_can_go_red():
    """反真空：一个 `--help` 直接退 3 的假脚本必须被判红。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="temp-help-sample-") as td:
        bad = pathlib.Path(td) / "broken.py"
        bad.write_text("import sys\n\nsys.exit(3)\n", encoding="utf-8")
        assert _help_ok(bad) is False, "假脚本 `--help` 退 3 却被判绿 ⇒ 冒烟判据没接上"
