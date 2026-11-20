# -*- coding: utf-8 -*-
"""B 的「收录即提交」：收录成功写行之后把这一份稿记成已提交。

落点与 F / E 同一套：`tasks.artifacts` 里的一枚 `mss:` 记号（格式与解析都在
`agent_f/submission.py`，本模块不新造字符串）。区别只在时机：

- F / E：收工那一趟由框架扫「已签、尚未提交」的稿（`closing_auto_submit`）；
- B：收录成功写行之后这一刻（`ingested_to_ledger`）—— B 的稿不靠收工自动提交。

受控拒（`out["ok"] is False`）⇒ 一个字节都不写；没有 task 行 ⇒ 把「没有 task 行可
写」写进返回读数，不静默。
"""
from __future__ import annotations

from typing import Any

from .. import manuscriptsubmission as _MS


def mark_b_ingested(store: Any, root: Any, *, manuscript: Any, out: dict[str, Any],
                    task_id: str = "", stamp: str = "") -> dict[str, Any]:
    """薄转发 `manuscriptsubmission.mark_ingested`（丙那一笔的唯一实现）。

    不收 `family`：族由 `manuscriptsubmission.producer_of` 从稿路径现判。改前这里收一个
    `family` 形参、函数体第一行 `_ = family` 把它吞掉 —— 调用方以为自己传了「这一份稿属于
    哪一族」，而它一个字节都没被读；那种形参是"接口看着收得下、实现其实不认"的假面。
    """
    return _MS.mark_ingested(store=store, root=root, manuscript=manuscript,
                             out=out, task_id=task_id, stamp=stamp)
