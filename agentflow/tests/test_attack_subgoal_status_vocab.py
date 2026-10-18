# -*- coding: utf-8 -*-
"""`attack.pick_next_subgoal`：**输入写错**与**确实没有待办**必须分得开。

## 为什么补这个文件

亲测 D 的 `attack.*` 时，我按常识给了 `status="pending"` / `"done"`（词表其实是
`("todo","in_progress","supported_not_proved","closed","blocked","dropped")`），
它回的是：

    {"picked": False, "reason": "没有可推进的子目标（全部 closed/dropped/supported_not_proved 或列表为空）"}

⇒ 这是本仓最在意的**"没查成写成查了没有"**：真正的原因是"**你给的状态不在词表里**"，
而上层读到的结论是"**攻坚已经无事可做**"—— D 会因此不再推进任何子目标。

业主口径（逐字）：*"凡是你凭感觉第一次运行工具发现红了，都要假想真实智能体也会在这里
困惑并浪费时间和 token。"*

这一组钉三件事（含一对**反折平**）：
1. 状态写错 ⇒ `kind='unknown_subgoal_status'`，**点名声 ＋ 列出合法词表**；
2. 合法输入 ⇒ 按确定性次序选中（`in_progress` 优先于 `todo`）；
3. **反折平**：全是终态（`closed`）时**不许**报 `unknown_subgoal_status`
   —— 那是"真的没有待办"，与"你写错了"是两件事。
"""

from __future__ import annotations

import pathlib

from agentflow.store import Store
from agentflow.tools import build_registry

ROLE = "D"


def _call(tmp_path: pathlib.Path, **kw) -> dict:
    store = Store(tmp_path / "ws")
    store.init()
    reg = build_registry(store=store, workspace_root=tmp_path / "ws").registry
    res = reg.call("attack.pick_next_subgoal", role=ROLE, **kw)
    payload: dict = {}
    for attr in ("data", "meta"):
        val = getattr(res, attr, None)
        if isinstance(val, dict):
            payload.update(val)
    return payload


def test_a_wrong_status_is_not_reported_as_nothing_to_do(tmp_path: pathlib.Path) -> None:
    """正控：状态不在词表里 ⇒ 如实说"输入写错了"，并给出合法词表。"""
    got = _call(tmp_path, subgoals=[{"sid": "s1", "status": "done"},
                                    {"sid": "s2", "status": "pending"}])
    assert got.get("picked") is False, got
    assert got.get("kind") == "unknown_subgoal_status", got
    reason = str(got.get("reason") or "")
    assert "pending" in reason and "done" in reason, reason
    assert "todo" in reason and "in_progress" in reason, f"没列出合法词表：{reason}"
    # 判据钉的是**机器的判读入口**（`kind` 与 `picked`），不是文案里有没有某串字：
    # 我第一次把这条写成"reason 里不许出现『没有可推进的子目标』"，而修后的文案**故意**
    # 引用了那句话来说明"这一条没说成…" ⇒ 判据红得有理，是我把断言写机械了。
    assert got.get("picked") is False, got


def test_the_deterministic_order_still_works(tmp_path: pathlib.Path) -> None:
    """正控：合法输入下 `in_progress` 优先于 `todo`（确定性次序不许被这次改动碰坏）。"""
    got = _call(tmp_path, subgoals=[{"sid": "s1", "status": "todo"},
                                    {"sid": "s2", "status": "in_progress"}])
    assert got.get("picked") is True, got
    assert (got.get("subgoal") or {}).get("sid") == "s2", got


def test_an_all_terminal_pool_is_not_the_same_as_a_wrong_status(tmp_path: pathlib.Path) -> None:
    """**反折平**：真的没有可推进的子目标 ⇒ 不许报 `unknown_subgoal_status`。"""
    got = _call(tmp_path, subgoals=[{"sid": "s1", "status": "closed"}])
    assert got.get("picked") is False, got
    assert got.get("kind") != "unknown_subgoal_status", got
    assert "没有可推进的子目标" in str(got.get("reason") or ""), got
