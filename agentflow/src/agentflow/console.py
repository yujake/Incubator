"""把 CLI 的输出编码钉在 UTF-8 上 —— 这一件事只有一份实现。

## 为什么必须有这个模块（实测，不是推理）

本项目的产物几乎全是中文，而 Windows 控制台与重定向的默认编码是 cp936(GBK)。
GBK 编不出 `⇒`(U+21D2) 这类符号，于是 `print()` 自己抛 `UnicodeEncodeError`，
进程以 1 结束 —— 而在本项目的三态里 1 是"查过了、发现问题"。后果有两个方向，
都坏：

1. 一次投递层面的问题（打印不出来）被读成代码层面的问题；
2. 更坏：`cli run` 在无 key 时受控退出码是 2（没跑成），一旦摘要里出现 GBK 编不出的
   符号，进程就以 1 结束 —— "没查成"被反转成"发现问题"（实测复现：
   `cli run` 无 key 在 GBK 下 exit=1，加 `PYTHONUTF8=1` 后 exit=2）。

而且这类缺陷在套件里结构性看不见：pytest 的 capture 用 UTF-8 临时文件，
进程内的 `cli.*` 打印永远碰不到真实控制台编码。

## 取舍（显式写清）

宁可在输出里出现替换字符（`errors="replace"`），也不让"打印不出来"改写退出码。
本函数只负责钉编码；"输出失败 ⇒ 退出码 2"这一条属于调用方。
"""

from __future__ import annotations

import sys
from typing import Iterable, TextIO


def pin_utf8(extra: Iterable[TextIO] = ()) -> None:
    """把 `stdout` / `stderr`（以及 `extra`）的编码钉在 UTF-8 上。

    被重定向或被测试替换过的流可能没有 `reconfigure`（或已关闭）⇒ 吞掉这两种情况：
    门本身不许因为"改不了输出编码"而崩。
    """
    for stream in (sys.stdout, sys.stderr, *extra):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            # 可以忽略：被重定向/被测试替换过的流可能没有 reconfigure（或已关闭），
            # 而"改不了输出编码"不该让门本身崩掉。
            pass
