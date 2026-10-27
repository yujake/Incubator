"""`python -m agentflow.agent_a` 的自检入口（`goal-7f5116c1` M6/M7）。

为什么需要这个文件：包形态下 `python -m agentflow.agent_a` 执行的是
`agent_a/__main__.py`。拆包时自检块被搬进了 `_support.py`，于是它还在但永不被执行
—— 而 `python -m` 退出码 0 这条契约写在 `docs/ROLE-SPECS.md` 与
`scripts/release_check.py` 第 2 项里。这个文件把那一段块逐字搬回来。

自检本体在 `agent_a/selftest.py`（2026-10-26 从 `core.py` 搬出来：那一块把 core 撑过了
`src_files_gt800_lines` 的基线，而自检既不是动作也不是装配）。这个文件只负责入口。
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
