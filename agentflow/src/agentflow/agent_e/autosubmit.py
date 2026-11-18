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
    """收工那一趟：把 E 这个实例名下已签、尚未提交的稿写进 E 自己那一行的 `artifacts`。

    实例标签从 `identity.resolve_identity` 现读（名册名 > 召唤标签 > `tasks.instance`；
    台账号不算实例标签 —— 那是 K9 记的病）。读不到实例标签时按角色级读，与改前同一
    口径（并在读数里留 `instance=""`，不是静默）。
    """
    identity: dict[str, Any] = {}
    try:
        from .. import identity as _ID

        identity = dict(_ID.resolve_identity(store, "E", task_id=str(task_id or "")))
    except Exception:  # noqa: BLE001 —— 读不成按角色级读（下面 instance=""）
        identity = {}
    instance = "" if str(identity.get("source") or "") == "task_id" else str(
        identity.get("instance") or "")
    return _MC.auto_submit_for(
        store=store, root=root, role="E", families=FAMILIES_E,
        task_id=str(task_id or ""), instance=instance,
        stamp=str(stamp or ""))
