# -*- coding: utf-8 -*-
"""E 的收工自动提交：收工时自动提交名下所有未提交稿并更新状态。

与 F 那套逐条同形：

- 选谁：E 名下（`e-proof` / `e-num` 两族）、已签（签 sha == 当前正文 sha）、尚未提交；
- 记号：`tasks.artifacts` 里的一枚 `mss:`（格式与解析复用 `agent_f/submission.py`）；
- 幂等 / 未签不提交 / 签后改正文不提交三条与 F 一致。

实现只有一处：`manuscriptsubmission.auto_submit_for`（F 自己那份在
`agent_f/autosubmit.py`，本模块不复制它的选人逻辑，只给它 `role="E"` 与两族）。
"""
from __future__ import annotations

from typing import Any

from .. import manuscriptclosing as _MC

#: E 的两族（`manuscriptfamily.FAMILY_ORDER` 里的名字；不在这里另写前缀）。
FAMILIES_E: tuple[str, ...] = ("e-proof", "e-num")


def auto_submit_at_close(*, store: Any, root: Any, task_id: str = "",
                         stamp: str = "") -> dict[str, Any]:
    """收工那一趟：把 E 名下已签、尚未提交的稿写进 E 自己那一行的 `artifacts`。"""
    return _MC.auto_submit_for(
        store=store, root=root, role="E", families=FAMILIES_E,
        task_id=str(task_id or ""), stamp=str(stamp or ""))
