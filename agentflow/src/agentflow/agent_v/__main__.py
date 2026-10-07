# -*- coding: utf-8 -*-
"""`python -m agentflow.agent_v` 的自检入口。

包形态下 `python -m agentflow.agent_v` 执行的是本文件（与 A–H 八个包同一形态：
`tests/test_agent_split_is_one_action_one_file.py` 的 `main_entry_problems` 守的就是
"这个 `if __name__ == '__main__':` 块在不在"）。退出码 0 = 自检全过。
"""
from __future__ import annotations

from .core import selftest

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(selftest())
