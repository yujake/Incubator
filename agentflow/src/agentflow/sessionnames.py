# -*- coding: utf-8 -*-
"""会话号的写法与落点（`sessions/` 目录、`<sid>.jsonl` 文件名）。

## 为什么单独一个模块

2026-11-22 业主裁定「旧工作区不必兼容」之后，会话号的写法从两种收成一种
（ISO `2026-11-21`），而"哪种写法算旧、旧文件怎么点名"这件事需要一个可判定的名字。
它与会话的读写（事件、索引、锁）是两件事，所以分开：
:mod:`agentflow.sessions` 只往这里取"号长什么样、文件在哪"。

## 三态纪律

- 新写法：`YYYY-MM-DD`（写侧唯一一种）；
- 旧写法：`YYYYMMDD`（`is_legacy_sid` 认得出，`legacy_session_files` 逐个点名）——
  不读，但也不折成"盘上没有这个文件"；
- 别的号（`real11` / `r34c` / `s1`）：不是日期，原样当文件名。
"""

from __future__ import annotations

import os
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

#: 会话记录目录名（工作区根下）。
SESSIONS_DIR_NAME = "sessions"
#: 缺省会话号的环境变量。
ENV_SESSION = "AGENTFLOW_SESSION"

#: 旧的紧凑日期写法（`20261030`）：只用于"报旧布局"，不用于读。
_LEGACY_SID = re.compile(r"^\d{8}$")


def sessions_dir(root: Any) -> pathlib.Path:
    """`<项目根>/sessions/`（只算路径，不建目录）。"""
    return pathlib.Path(str(root)) / SESSIONS_DIR_NAME


def session_id() -> str:
    """本次会话号：环境变量优先，否则当天日期（ISO 写法 `YYYY-MM-DD`）。

    2026-11-22（业主裁定「旧工作区不必兼容」）：缺省写法从紧凑 `%Y%m%d` 收成 ISO ——
    读侧只认带连字符的写法；紧凑名（`20261030.jsonl` 这类）不再被读。
    """
    env = str(os.environ.get(ENV_SESSION) or "").strip()
    if env:
        return env
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def session_path(root: Any, sid: str | None = None) -> pathlib.Path:
    return sessions_dir(root) / f"{sid or session_id()}.jsonl"


def is_legacy_sid(sid: Any) -> bool:
    """这个会话号是不是旧紧凑写法（`20261030`）—— 只用于"报旧布局"，不用于读。"""
    return bool(_LEGACY_SID.match(str(sid or "").strip()))


def legacy_session_files(root: Any) -> list[str]:
    """盘上那些不再读的旧写法会话文件名（读侧只认 ISO；这里只报，不读）。"""
    d = sessions_dir(root)
    if not d.is_dir():
        return []
    try:
        return sorted(p.name for p in d.glob("*.jsonl") if is_legacy_sid(p.stem))
    except OSError:
        return []
