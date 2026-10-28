# -*- coding: utf-8 -*-
"""判据：`conductor.void_items` 必须真的调到 `Conductor.void_items`（改前每次都抛 AttributeError）。

## 真机（2026-10-28 `projects/paper-rewrite-78c` 收工，M 的第 94 / 104 步）

```
{"tool": "conductor.void_items", "args": {"item_ids": ["t-000006", "t-000143"], "why": "…"}}
→ {"checked": false, "ok": false, "state": "unknown",
   "reason": "作废时抛了（AttributeError: 'function' object has no attribute 'void_items'）⇒ 落没落盘不知道"}
```

根因在 `tools/conductor_tools.py::register`：它把工厂函数 `_conductor()` 绑给了
`_conductor` 这个位置：

```python
_bound['_conductor'] = _conductor        # 绑的是工厂，不是它的结果
```

其余每一件 `conductor.*` 的 handler 都写 `_conductor().summon(...)`（先调用再取属性），
只有 `conductor_void_items` 写成 `_conductor.void_items(...)` —— 于是在一个函数对象上
取属性，永远抛 `AttributeError`。

后果不是"这一件工具不好用"：它是唯一设计来解「销号闸 ↔ 收工闸」互锁的出口
（收件人已静默、名下还挂着 `expects=ack` 的通知）。它一炸，那一趟只能以 `final_refused`
收尾 —— 真机这一趟就是这样（3 次 final 被拒，交付物齐全但收不了工）。

## 这一组守什么

1. 正题：走真注册表调 `conductor.void_items`，返回里不许出现 "has no attribute"；
2. 到达约定的读数：`checked=True`、`state ∈ {voided, refused, nothing}`（真走到了
   `Conductor.void_items` 的判据，而不是被异常兜住）；
3. 反真空：拿一个别人的 `expects=ack` 项去作废 ⇒ `state="refused"` 且理由点名
   （证明它真的在做那个判断，不是把什么都算成功）。
"""
from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry


def _ws(tmp_path: pathlib.Path) -> tuple[Store, Conductor, pathlib.Path]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return st, cond, ws


def _row(cond: Conductor, parent: str, *, role: str = "A", expects: str = "ack",
         status: str = "done") -> str:
    """一条"到点通知"板项（`kind` 非空 + 六格板状态齐全，见 `schema.Task.validate`）。"""
    ended = None if status in ("pending", "running") else "2026-10-28T09:00:05+08:00"
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "notice", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"void@{role}",
        "status": status, "outcome": ("no_result" if ended else None),
        "refusal_reason": None, "instance": "", "detail": "到点通知",
        "error": None, "started_at": "2026-10-28T09:00:00+08:00", "ended_at": ended,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        # 板项那六格：`kind`（项类）+ `expects`（要不要回执）+ `item_state`（状态机）
        "kind": "notice", "expects": expects, "item_state": "queued",
        "item_close": None, "keep_alive": False, "seen_by": "", "seen_step": None,
    }, note=f"start:{role}.notice")


def test_the_tool_reaches_the_conductor_instead_of_exploding(tmp_path: pathlib.Path):
    """正题：真注册表里调它 ⇒ 不许 "has no attribute"，且落到约定的读数。"""
    st, cond, ws = _ws(tmp_path)
    parent = cond.open_top_level_run("M", "收工时作废到点通知")
    item = _row(cond, parent)
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    reg.bound_role = "M"          # 这一件工具的角色面是父 + M（真机上就是 M 在调）
    with calling_as(parent):
        res = reg.call("conductor.void_items", item_ids=[item], why="收件人已静默，父代作废")
    data = dict(res.data or {})
    reason = str(data.get("reason") or "")
    assert "has no attribute" not in reason, reason
    assert data.get("checked") is True, data
    assert str(data.get("state")) in ("voided", "refused", "nothing"), data


def test_an_item_that_belongs_to_someone_else_is_refused(tmp_path: pathlib.Path):
    """反真空：作废"别人的"项 ⇒ `state="refused"` 且理由点名（真在做判断）。"""
    st, cond, ws = _ws(tmp_path)
    parent = cond.open_top_level_run("M", "收工时作废到点通知")
    other_parent = cond.open_top_level_run("M", "另一个父")
    foreign = _row(cond, other_parent, role="A")
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    reg.bound_role = "M"
    with calling_as(parent):
        res = reg.call("conductor.void_items", item_ids=[foreign], why="随手试试")
    data = dict(res.data or {})
    assert "has no attribute" not in str(data.get("reason") or ""), data
    assert str(data.get("state")) == "refused" or data.get("refused"), data
