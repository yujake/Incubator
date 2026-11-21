# -*- coding: utf-8 -*-
"""
通用小判据（号形 / 数形 / 时刻 / 逐字读数）与「没查成」的受控异常。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class _Unchecked(Exception):
    """这条规则没查成（读不到它要读的东西）。由 `check_kind` 收成 `unchecked`。"""


# ---------------------------------------------------------------- 通用小判据

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID6 = re.compile(r"^\d{6}$")
_ID6_OR_4 = re.compile(r"^(?:\d{6}|\d{4})$")
_TASK_ID = re.compile(r"^t-(?:\d{6}|\d{4})$")


def _is_hex64(value: Any) -> bool:
    """64 位小写十六进制（sha256 的唯一写法）。"""
    return isinstance(value, str) and bool(_HEX64.match(value))


def _is_int(value: Any) -> bool:
    """真整数（`bool` 是 `int` 的子类，阈值与计数都不许收它）。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """有限实数（`NaN` / `inf` 不是账目上的钱）。"""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _is_iso(value: Any) -> bool:
    """可解析的 ISO 时刻（`datetime.fromisoformat` 的口径，不另写一份正则）。"""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _shown(value: Any, limit: int = 120) -> str:
    """逐字读数的短形态（`repr` 保真，过长截断并标出来）。"""
    got = repr(value)
    return got if len(got) <= limit else got[:limit] + f"…（共 {len(got)} 字）"


def _rel(root: Path | None, path: Path) -> str:
    """文件相对工作区的 posix 路径（读数里的"在哪一份文件"）。"""
    if root is None:
        return path.name
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
