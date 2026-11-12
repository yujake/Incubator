"""`python -m agentflow.agent_f` 的自检入口。

包形态下 `python -m agentflow.agent_f` 执行的是 `agent_f/__main__.py`；没有
这个文件，自检块还在但永不被执行 —— 而 `python -m` 退出码 0 这条契约写在
`docs/ROLE-SPECS.md` 与 `scripts/release_check.py` 第 2 项里。自检本体在
`agent_f/selftest.py`，这个文件只负责入口。
"""
from __future__ import annotations

from .core import selftest

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(selftest())
