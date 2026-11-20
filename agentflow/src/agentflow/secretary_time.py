# -*- coding: utf-8 -*-
"""秘书台账的时间戳口径（从 secretary.py 的 U29 单元逐字搬出）。

我保证哪条不变式：同一次落盘里的 "at" 只有一个口径 —— `_now_iso()` 是秘书所有 JSONL
台账的时间戳唯一来源（本地时区 + 秒级 ISO8601）；`_older_than()` 只拿它读回来的串比，
不另造一种格式。

为什么单独成一个模块：它是刀1（台账底座）与后面每一刀的公共叶子 —— 台账、名册、判据、
档位、签、转发都要写 "at"。留在 secretary.py 里会让每一个新模块都要从 secretary.py
反向 import（组装层 -> 模块 -> 组装层的环）；搬成一个只依赖标准库的叶子，依赖方向就是
单向的 `secretary -> secretary_time`，而各模块之间不必互相 import。

对外名字：`_now_iso` / `_older_than` / `_as_mapping`（再导出仍在 secretary.py 里，外部
调用点一个字不改）。
"""

from __future__ import annotations

from typing import Any

from typing import Mapping
import datetime as _dt

def _as_mapping(value: Any) -> dict[str, Any]:
    """把一个"看起来像声明"的对象读成 dict（`RoleBrief` 是 dataclass，不是 Mapping）。

    读不出来（`None` / 别的类型）就返回空表，且只在最后一个分支返回它 ——
    调用方必须把"空表"读成"这一格判不了"，不是"没有定位"。
    """
    import dataclasses

    if isinstance(value, Mapping):
        return dict(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    return {}


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _older_than(stamp: Any, now: str, window_sec: int) -> bool:
    """`stamp` 比 `now` 早了超过 `window_sec` 秒吗（"够久了还没核"的判据）。

    三个"不知道"都回 `False`（不列，而不是"列成待核"）：没有时间戳 / 解析不了 /
    时钟反了。理由：待核队列一旦把"判不了"也列进去，它就会变成"什么都往里塞"的
    假阳性来源（主控点名的那条负控）。
    """
    raw = str(stamp or "").strip()
    if not raw:
        return False
    try:
        then = _dt.datetime.fromisoformat(raw)
        reference = _dt.datetime.fromisoformat(str(now))
    except ValueError:
        return False
    try:
        return (reference - then).total_seconds() > float(window_sec)
    except (TypeError, ValueError):
        return False
