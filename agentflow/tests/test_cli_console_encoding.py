"""输出编码普查：每个 CLI 入口在 GBK 下都不许把"打印不出来"变成退出码 1。

## 为什么必须是"跑孩子进程"的普查，而不是只修一次

这类缺陷结构性看不见：pytest 的 capture 用 UTF-8 临时文件，进程内的 `cli.*`
打印永远碰不到真实控制台编码。所以用例必须显式把孩子进程放进 GBK 环境里跑，并断言：

1. 输出里没有 `Traceback`；
2. 退出码仍然 ∈ {0, 1, 2}，且语义正确：`1` 只允许出现在"真的报告了问题"的时候。

两个真实事故（都在本文件的覆盖范围里）：
- `scripts/lint_rules.py` 打印含 `⇒` 的行时抛 `UnicodeEncodeError` ⇒ 一棵 0 error 的干净树
  在重定向下也退 1（"有警告/没打印成"与"有错误"同码）；
- `cli run` 无 key 的受控码 2（没跑成） 在 GBK 下被反转成 1（发现问题）（实测）。

负控写在最后：不钉编码时往 GBK 流里写 `⇒` 真的会抛 —— 证明上面的普查不是空话。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: 每个入口一条：`(标签, argv, 子命令前是否补 --root <tmp>)`；argv 里不写解释器，由 `sys.executable` 补。
#: 成本取舍（实测）：`coverage_zero_test.py` 全量跑一次要 68 秒，而它在这个矩阵里只是"又一个入口"，所以用它的
#: `--selftest`（324 毫秒，同一条 `main()` 与打印路径）；代价是"打印含 `⇒` 的发现行"这一格不再由它覆盖 ——
#: 那一格由 `lint_rules` 覆盖（它的 R006/R010/R009 消息里就有 `⇒`，6 秒）。慢的门最后会被跳过，所以必须便宜。
#: 第三列（`needs_root`）为什么必须存在：`cli demo` 的 `run_demo()` 会 `rmtree(root / "demo" / "run")` 再重建；
#: 不给 `--root` 时它按 `DEFAULT_ROOT` 落在仓库内 ⇒ "跑一次这个测试"就等于改写了被跟踪的 `agentflow/demo/run/
#: data/*`，而"仓库冻结、sha256 前后不变"那类断言恰恰以这个仓库为前提（实测：无 `--root` 跑一次，5 个文件的
#: sha256 都变了；负控见 `temp/i1-neg-before.txt` 与 `temp/i1-neg-after.txt`）。给 `--root <tmp_path>` 之后它就 只在临时目录里造数据（顶层的 `--root` 必须写在子命令之前）。
ENTRIES: list[tuple[str, list[str], bool]] = [
    ("lint_rules", ["scripts/lint_rules.py"], False),
    ("noai_consistency", ["scripts/noai_gate.py", "--check-consistency"], False),
    ("noai_git", ["scripts/noai_gate.py", "--git"], False),
    ("coverage_selftest", ["tools/coverage_zero_test.py", "--selftest"], False),
    ("cli_tools", ["-m", "agentflow.cli", "tools", "--role", "A"], False),
    ("cli_demo", ["-m", "agentflow.cli", "demo"], True),
]


def _with_root(argv: list[str], root: Path) -> list[str]:
    """把顶层 `--root` 插到子命令之前。

    `argv` 形如 `["-m", "agentflow.cli", "<子命令>", ...]`：`--root` 是顶层参数，
    argparse 只认子命令之前的位置，所以插在 `-m <模块>` 之后、子命令之前。
    写成显式函数而不是 `argv[:2]` 切片：切片在"某天真加了别的入口"时会静默插错位置。
    """
    assert argv[:2] == ["-m", "agentflow.cli"], f"这个入口不是 cli 子命令：{argv}"
    return [*argv[:2], "--root", str(root), *argv[2:]]


def _run(
    argv: list[str], *, gbk: bool, root: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "PYTHONPATH": "src"}
    if gbk:
        env.pop("PYTHONUTF8", None)
        env["PYTHONIOENCODING"] = "gbk"
        env["PYTHONUTF8"] = "0"
    else:
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
    full = _with_root(argv, root) if root is not None else list(argv)
    return subprocess.run([sys.executable, *full], cwd=str(ROOT), capture_output=True, env=env)


@pytest.mark.parametrize(
    ("label", "argv", "needs_root"), ENTRIES, ids=[e[0] for e in ENTRIES]
)
def test_entry_point_survives_gbk(
    label: str, argv: list[str], needs_root: bool, tmp_path: Path
) -> None:
    """GBK 下：不吐 Traceback、退出码仍在三态里，且 `1` 必须伴随"说清楚问题是什么"。"""
    # `needs_root` 的入口必须在临时工作区里跑：它们会写数据（`cli demo` 甚至会先
    # `rmtree` 再重建），落在仓库里就等于"测试改写了被测仓库"（见 `ENTRIES` 上的注释）。
    p = _run(argv, gbk=True, root=(tmp_path / label) if needs_root else None)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    assert "Traceback" not in out, f"{label} 在 GBK 下崩了：\n{out[-2000:]}"
    assert p.returncode in (0, 1, 2), f"{label} 退出码 {p.returncode} 不在三态里：\n{out[-800:]}"
    if needs_root:
        # 正控：临时工作区真被写进去了。没有这一条，"补了 --root"与"`--root` 被
        # argparse 吃掉、实际仍写仓库"这两种情况在输出上完全一样。
        assert (tmp_path / label).exists(), f"{label} 给了 --root 却没在临时工作区落下任何东西"
    if p.returncode == 1:
        # `1` 是"查过了、发现问题"。判据不是"输出里有某个词"，而是"它张嘴说了话" ——
        # 崩溃换来的 1 往往一个字都没打出来（或只打了 Traceback，上一行已经拦住了）。
        assert p.stdout.strip() != b"", f"{label} 退了 1 却什么都没说 ⇒ 这个 1 多半是崩溃换来的"


def test_cli_run_without_a_key_keeps_its_controlled_exit_code_2_under_gbk() -> None:
    """实测过的反转：`cli run` 无 key 的受控码 2，在 GBK 下曾经变成 1。

    为什么这条单独写：它是"没查成"被读成"发现问题"的方向性错误 —— 比崩溃更危险，
    因为 1 看起来像"跑过了、有问题"，而真相是"根本没跑成"。
    """
    p = _run(["-m", "agentflow.cli", "run", "--topic", "gbk-probe"], gbk=True)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    assert "Traceback" not in out, out[-2000:]
    assert p.returncode == 2, f"无 key 的受控码必须是 2，实测 {p.returncode}：\n{out[-800:]}"


def test_pin_utf8_is_the_single_implementation_the_gates_point_at() -> None:
    """规范实现存在且可调用；三个门脚本的内联副本都在文档里指向它。"""
    from agentflow.console import pin_utf8

    pin_utf8()  # 不抛即可（对真正的 stdout/stderr 生效）
    for rel in ("scripts/lint_rules.py", "scripts/noai_gate.py", "tools/coverage_zero_test.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "agentflow/console.py" in text, f"{rel} 的内联编码兜底没有指向规范实现"
        assert "reconfigure" in text, f"{rel} 少了编码兜底"


# --------------------------------------------------------------------------- 负控


def _gbk_print_probe(tmp_path: Path, *, pin: bool) -> subprocess.CompletedProcess[bytes]:
    """让子进程在 GBK 的 stdout 上打印一个 GBK 编不出的字符（`⇒`）。

    关键：必须打子进程自己的 `sys.stdout`（它由 `PYTHONIOENCODING=gbk` 决定），
    而不是自己造一个 `TextIOWrapper(encoding="gbk")` —— `pin_utf8()` 钉的是
    `sys.stdout/stderr`，手造的流它管不着（第一版就是这么写错的，正控因此变红）。
    """
    body = (
        "import sys\n"
        + ("from agentflow.console import pin_utf8\npin_utf8()\n" if pin else "")
        + "print('\\u21d2')\n"
    )
    env = {**os.environ, "PYTHONPATH": "src", "PYTHONIOENCODING": "gbk"}
    env.pop("PYTHONUTF8", None)
    with open(tmp_path / "out.bin", "wb") as out:
        return subprocess.run(
            [sys.executable, "-c", body],
            cwd=str(ROOT),
            stdout=out,
            stderr=subprocess.PIPE,
            env=env,
        )


def test_without_the_pin_a_gbk_stream_really_raises(tmp_path: Path) -> None:
    """负控：不钉编码 ⇒ `UnicodeEncodeError` 真的发生（证明这条普查不是空话）。"""
    p = _gbk_print_probe(tmp_path, pin=False)
    assert p.returncode != 0
    assert b"UnicodeEncodeError" in p.stderr, p.stderr[:800]


def test_with_the_pin_the_same_write_does_not_raise(tmp_path: Path) -> None:
    """正控：`pin_utf8()` 把流换成 UTF-8 之后，同一个字符写得出去。"""
    p = _gbk_print_probe(tmp_path, pin=True)
    assert p.returncode == 0, p.stderr[:800]
