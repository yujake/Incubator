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
                    family: str = "", task_id: str = "", stamp: str = "") -> dict[str, Any]:
    """薄转发 `manuscriptsubmission.mark_ingested`（丙那一笔的唯一实现）。"""
    _ = family  # 族由 `producer_of` 现判；这里收这一格只为调用方读得顺
    return _MS.mark_ingested(store=store, root=root, manuscript=manuscript,
                             out=out, task_id=task_id, stamp=stamp)
