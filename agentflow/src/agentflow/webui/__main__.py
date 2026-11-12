# -*- coding: utf-8 -*-
"""`python -m agentflow.webui` 的入口（只做转发）。

`python -B -m agentflow.webui --port 0 --json` 是起后台任务拿 URL 用的那一条命令，
包化之后由本文件承接；实现只有 :func:`agentflow.webui.run` 一处，这里不重写第二份
（`R003` 要防的正是"同一个公开名两处各有一份实现"）。
"""

from __future__ import annotations

import sys

from .server import run

if __name__ == "__main__":
    sys.exit(run())
