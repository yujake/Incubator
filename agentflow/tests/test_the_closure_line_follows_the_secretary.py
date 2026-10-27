# -*- coding: utf-8 -*-
"""判据：收工那句话的点名上限跟着秘书那一档走（2026-10-27）。

## 为什么要有这条判据

`conductor._CLOSURE_IDS_IN_LINE` 决定"收工那句 `detail` 里每一栏点名几个编号"，
`secretary.MAX_REMINDERS` 决定"待办栏一次最多点名几条"。这两个数是同一件事（同一屏
上的同一档），而改前 conductor 里写死 `5`，只附了一句注释"与 `secretary.MAX_REMINDERS`
对齐"—— 一句注释挡不住漂移。同一个文件里 `_roster_brief_fits` 走的是转发
`SEC.BRIEF_MAX` 的正路，两种写法并存本身就是那个隐患。

分家的形态：待办栏改到 6 条、收工那句话仍点名 5 条 —— 没有东西会报，而读的人会以为
"就这 5 条"。

## 钉住两件事

1. 两个数今天相等（`conductor._CLOSURE_IDS_IN_LINE == secretary.MAX_REMINDERS`）；
2. 它是转发而不是巧合：把 `secretary.MAX_REMINDERS` 改成一个别的值、重新求值
   conductor 那一行，必须跟着变（只执行那一行赋值，不重载真模块）。
"""
from __future__ import annotations

import pathlib

from agentflow import conductor as C
from agentflow import secretary as SEC


def test_the_two_limits_are_the_same_number() -> None:
    assert int(C._CLOSURE_IDS_IN_LINE) == int(SEC.MAX_REMINDERS), (
        f"收工那句的点名上限 {C._CLOSURE_IDS_IN_LINE} 与秘书待办栏上限 "
        f"{SEC.MAX_REMINDERS} 分家了 —— 请让 conductor 转发 `SEC.MAX_REMINDERS`")


def test_it_is_a_forward_not_a_coincidence() -> None:
    """转发判据：那一行是表达式（`int(SEC.MAX_REMINDERS)`），不是一个写死的数。

    做法：把 conductor 里那一行赋值语句单独取出来，在一个只有假 `SEC`（`MAX_REMINDERS=9`）
    的命名空间里执行 —— 转发 ⇒ 求值得 9；写成字面量 ⇒ 求值仍是 5 ⇒ 红。
    为什么不 `importlib.reload(conductor)`：重载会把模块里的类对象重新造一遍，
    同进程后续用例手里的旧引用就与模块里的新对象分家了（那是一场与本判据无关的事故）。
    """
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "conductor.py"
    line = next((ln for ln in src.read_text(encoding="utf-8").splitlines()
                 if ln.startswith("_CLOSURE_IDS_IN_LINE")), "")
    assert line, "conductor 里找不到 `_CLOSURE_IDS_IN_LINE` 这一行"

    class _FakeSec:
        MAX_REMINDERS = 9

    ns: dict[str, object] = {"SEC": _FakeSec}
    exec(compile(line, "conductor.py", "exec"), ns)   # noqa: S102 —— 只执行那一行赋值
    assert int(ns["_CLOSURE_IDS_IN_LINE"]) == 9, (        # type: ignore[arg-type]
        "把秘书那一格改成 9 之后这一行仍求值出 "
        f"{ns['_CLOSURE_IDS_IN_LINE']} ⇒ 它不是转发（是第二份写死的数）：{line!r}")
