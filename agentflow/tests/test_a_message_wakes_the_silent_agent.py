# -*- coding: utf-8 -*-
"""判据（D-a）：给"静默未销号"的代理发一条消息 ⇒ 它按同一个号跑起来、把那封信读掉。

链路（真机就这两步，模型那一步归后端；替身只顶"角色循环干什么"，
不顶被测的两段：叫醒判定与同号继续）：

```
open_item(kind="message")            ← 发信人（或计时器到点）落一条板项
  ⇒ _ensure_consumer：终态 + 未销号 ⇒ 交执行侧
  ⇒ resume_dispatched：status 由 done 改回 running（同号、不新建行）
  ⇒ backend.call(role, "", {}, task_id=同号)   ← 角色循环（替身：把收件箱读掉、写一步）
  ⇒ 跑完写回终态
```

同时钉住 (D-d)：tasks 行数与名册行数都不增，号还是原来那个号。
"""
from __future__ import annotations

import pathlib
import time

from agentflow.conductor import Conductor
from agentflow.secretary import Secretary
from agentflow.store import Store

BR = "2026-10-29T17:00:00+08:00"


class _Loop:
    """角色循环替身：被叫起来之后把收件箱里那几条读掉（mark_seen + ack），然后回 payload。"""

    def __init__(self, cond: Conductor | None = None) -> None:
        self.cond = cond
        self.calls: list[dict] = []
        self.drained: list[str] = []

    def call(self, role, action, params, *, token=None, instance="", task_id=""):
        self.calls.append({"role": role, "action": action, "task_id": task_id})
        try:
            items = [str(x.get("task_id") or "") for x in self.cond.open_items_of(task_id)
                     if str(x.get("item_state") or "") == "queued"]
        except Exception:  # noqa: BLE001
            items = []
        for item_id in items:
            try:
                self.cond.mark_item_seen(item_id, by_task_id=task_id, step=1)
                self.cond.close_item(item_id, close="acked", by_task_id=task_id)
                self.drained.append(item_id)
            except Exception:  # noqa: BLE001
                pass
        return {"status": "done", "outcome": "ok",
                "detail": "被一条来信叫起来，读掉了收件箱里那几条", "payload": None,
                "artifacts": [], "tokens": 0, "usd": 0.0}


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str, str, _Loop]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    be = _Loop()
    cond = Conductor(st, policy=None, backend=be)
    be.cond = cond
    cond.secretary = Secretary("M", root=ws, store=st)
    cond.roster_sink = cond.secretary
    parent = str(cond.open_top_level_run("M", "顶趟这一趟"))
    child = cond._write_new_row({
        "task_id": "", "role": "D", "action": "", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": "@x", "status": "done",
        "outcome": "ok", "refusal_reason": None, "instance": "D#1",
        "detail": "研究包已交回", "error": None, "started_at": BR, "ended_at": BR,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": ["conductor:admitted"],
    }, note="probe:child")
    cond.resume_runner = cond.resume_dispatched      # 真实装配也是这么接的
    return cond, parent, child, be


def test_a_message_wakes_the_silent_agent_on_the_same_number(tmp_path: pathlib.Path) -> None:
    cond, parent, child, be = _env(tmp_path)
    before_roster = [str(r.get("task_id")) for r in cond.secretary.roster_rows(parent)[0]]

    item = cond.open_item(kind="message", role="D", expects="ack", action="message",
                          summary="来自 M 的一条留言", called_by="M",
                          parent_task_id=child, depth=3)
    # 板项自己也是一条 tasks 行（它是"挂在收件人名下的工作项"）——所以基线要在这之后再量，
    # 这一条钉的是"叫醒不额外建行"。
    after_delivery = len(cond._tasks())
    for _ in range(400):
        if be.calls and str((cond._task(child) or {}).get("status")) != "running":
            break
        time.sleep(0.02)

    assert be.calls, "执行侧一次都没被调（叫醒没接上）"
    assert be.calls[0]["task_id"] == child, be.calls
    assert be.drained == [item], (be.drained, item)      # 那封信真的被读掉（ack 掉了）
    assert str((cond._task(child) or {}).get("status")) == "done", cond._task(child)
    assert len(cond._tasks()) == after_delivery, "叫醒不许额外建行（同号继续）"
    assert [str(r.get("task_id")) for r in cond._tasks()].count(child) == 1, "同一个号只许一行"
    assert [str(r.get("task_id")) for r in cond.secretary.roster_rows(parent)[0]] == \
        before_roster, "名册一行都不许多"
