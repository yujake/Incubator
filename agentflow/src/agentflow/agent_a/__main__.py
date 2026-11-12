"""`python -m agentflow.agent_a` 的自检入口。

包形态下 `python -m agentflow.agent_a` 执行的是 `agent_a/__main__.py`，而 `python -m`
退出码 0 这条契约写在 `docs/ROLE-SPECS.md` 与 `scripts/release_check.py` 第 2 项里 ——
没有这个文件，自检块还在但永不被执行。自检本体在 `agent_a/selftest.py`，这个文件只
负责入口。
"""
from __future__ import annotations

from .selftest import _selftest

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块（release_check 第 2 项会跑它）
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 控制台编码重配失败无所谓（重定向到文件时就是这种情况），不影响自检结论
        pass
    raise SystemExit(_selftest())
