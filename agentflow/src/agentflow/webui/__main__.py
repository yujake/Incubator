# -*- coding: utf-8 -*-
"""`python -m agentflow.webui` 的入口（只做转发）。

拆包之前 `webui` 是一个模块，所以 `python -B -m agentflow.webui --port 0 --json`
这条命令直接可用（起后台任务拿 URL 用的就是它）。包化之后同名命令会去找
`__main__.py` —— 这个文件就是为那一条命令留的：实现只有
:func:`agentflow.webui.run` 一处，这里不重写第二份（`R003` 要防的正是
"同一个公开名两处各有一份实现"）。
"""

from __future__ import annotations

import sys

from .server import run

if __name__ == "__main__":
    sys.exit(run())
