# -*- coding: utf-8 -*-
"""`agentflow demo` 的实现真身（移植期工具，从 `cli.py` 原样搬来）。

离线端到端演示：不联网、不花钱，第一次接触这套框架时看它跑一遍最快。
为什么算移植期工具：它是一次性的"看个样子"，不是日常命令；真身（`agentflow.demo.run_demo`）
本来就在库里，命令行这一层只是把 `--root` / `--keep` 翻成两个入参。

`main(args)` 的入参就是 argparse 出来的那个 namespace（读 `root` 与 `keep`）。
"""
from __future__ import annotations

from pathlib import Path


def main(args) -> int:
    """跑一遍离线演示（`reset=not keep`：缺省把上次的演示数据清掉重来）。"""
    from agentflow.cli import DEFAULT_ROOT
    from agentflow.demo import run_demo

    return run_demo(Path(args.root or DEFAULT_ROOT).resolve(), reset=not args.keep)
