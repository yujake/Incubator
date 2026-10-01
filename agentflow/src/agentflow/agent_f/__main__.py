"""`python -m agentflow.agent_f` 的自检入口（`goal-7f5116c1` M6/M7）。

为什么需要这个文件：包形态下 `python -m agentflow.agent_f` 执行的是
`agent_f/__main__.py`。拆包时自检块被搬进了 `_support.py`，于是它还在但永不被执行
—— 而 `python -m` 退出码 0 这条契约写在 `docs/ROLE-SPECS.md` 与
`scripts/release_check.py` 第 2 项里。这个文件把那一段块逐字搬回来。
"""
from __future__ import annotations

from .core import selftest

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(selftest())
