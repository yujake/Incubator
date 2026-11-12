"""`python -m agentflow` 的入口。

它只做转发：真正的入口是 ``agentflow.cli.main``（``pyproject.toml`` 的
``[project.scripts]`` 指向同一个函数）。两处各写一份实现必然漂移，而漂移的症状是
"两种启动方式行为不一致"却没有任何地方报错。

这个文件本身也不能省：没有它时 `python -m agentflow` 报
``No module named agentflow.__main__`` 并以退出码 1 结束 —— 自动化会把它读成
"检查发现了问题"，而不是"这个包没有这个入口"。
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    # 退出码是接口的一部分，不许吞掉。
    sys.exit(main())
