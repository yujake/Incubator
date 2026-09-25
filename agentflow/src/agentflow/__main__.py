"""`python -m agentflow` 的入口。

## 为什么必须有这个文件

`agentflow` 的对外入口一直是 `python -m agentflow <动词>`（实现是
``agentflow.cli.main``，见模块 docstring）。而在本文件出现之前，`python -m agentflow`
会以退出码 1 结束并报 ``No module named agentflow.__main__`` —— 那不是"命令跑失败了"，
而是"这个包根本没有这个入口"。两者的区别在自动化里很要命：退出码 1 被读成
"检查发现问题"，于是一条正确的用法被判成一次失败。

## 为什么是转发而不是把 `cli` 的代码搬过来

同一份入口写在两处必然漂移，而漂移的症状是"`python -m agentflow` 与
`agentflow`（console script）行为不一致"，且没有任何地方会报错。
所以这里只有一句转发：`pyproject.toml` 的 `[project.scripts]` 指的也是
同一个 `cli.main`。
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    # 与 `cli.py` 的 `__main__` 块逐字同形：退出码是接口的一部分，不能吞掉。
    sys.exit(main())
