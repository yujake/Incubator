# -*- coding: utf-8 -*-
"""判据：`agentflow --version` 是一个真出口，且与打包元数据同一个数（2026-10-27，item 8）。

## 为什么要这条判据

改前 CLI 里没有任何命令读得到版本号：`agentflow/__init__.py` 的 `__version__` 与
`pyproject.toml` 的 `version` 是两个各自写死的字面量，而使用者只能靠
`pip show agentflow` 查 —— 从源码树跑、或装成脚本时连那条都没有。item 8 加了
`--version` 之后，这两处字面量第一次有了一个共同的、可执行的读数。

判据钉两件事，缺一条这个出口就还是"看着有、其实没说"：

1. `main(["--version"])` 打印的就是 `agentflow.__version__`，且以 0 结束
   （argparse 的 `version` action 会把输出打到 stdout 再 `SystemExit(0)`）；
2. `pyproject.toml` 的 `version` 与 `__version__` 相等 —— 两个字面量必须同一个数，
   否则"发布出去的版本号"与"CLI 报的版本号"各说一套，而这种漂移没有任何地方会响。
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import tomllib

import pytest

import agentflow
from agentflow import cli

PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_flag_prints_the_package_version_and_exits_zero() -> None:
    """① `--version` 打 `agentflow <__version__>`，退出码 0（stdout，不是 stderr）。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as ei:
            cli.main(["--version"])
    assert ei.value.code == 0, f"--version 的退出码必须是 0（收到 {ei.value.code!r}）"
    printed = out.getvalue().strip()
    assert printed == f"agentflow {agentflow.__version__}", (
        f"`--version` 打的是 {printed!r}，而 `agentflow.__version__` 是 "
        f"{agentflow.__version__!r}")
    assert agentflow.__version__ not in err.getvalue(), "版本号不许走 stderr"


def test_pyproject_version_matches_the_package() -> None:
    """② 打包元数据的 `version` 必须与 `__version__` 是同一个数（两处字面量不许漂）。"""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    packaged = str(data["project"]["version"])
    assert packaged == agentflow.__version__, (
        f"pyproject.toml 的 version={packaged!r} 与 agentflow.__version__="
        f"{agentflow.__version__!r} 不一致 ⇒ 发出去的版本号与 CLI 报的版本号各说一套")
