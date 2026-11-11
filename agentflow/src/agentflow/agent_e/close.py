# -*- coding: utf-8 -*-
"""E 的「收工读数」（业主 2026-11-11 裁定 ②）。

F 的收工读数在 `agent_f/step.py::_close_reading`；E 没有 `step` 动作（它的活是
`run_experiment`，收口在循环那一趟的退出），所以这里给 E 一个同形的
`close_reading()`：三格 `auto_submitted` / `auto_submitted_count` /
`still_unsubmitted`，外加候选级理由（`why` / `problems`）。

`agent_loop` 在 E 这一趟退场时调 `agent_e.autosubmit.auto_submit_at_close`，把同样三格
落进 `agent_run_end`（那一行才是盘上的收工读数）。本方法给直调 / 判据用，两处读的
是同一个实现（`manuscriptsubmission.auto_submit_for`），不各算一份。
"""
from __future__ import annotations

from typing import Any

from .. import schema as S


class _CloseReading:
    def close_reading(self, *, task_id: str = "", stamp: str = "") -> dict[str, Any]:
        """E 这一趟的收工自动提交读数（没查成时 `checked=False`，不折成 0 份）。"""
        from . import autosubmit as _AS

        if not task_id:
            try:
                from .. import conductor as _CND

                task_id = str(_CND.current_task_id() or "")
            except Exception:  # noqa: BLE001 —— 读不到就是没有召唤号
                task_id = ""
        root = (self.cfg.get("workspace_root")
                or getattr(self.store, "root", "") or ".")
        return _AS.auto_submit_at_close(
            store=self.store, root=root, task_id=str(task_id or ""),
            stamp=str(stamp or S.now_iso()))
