# -*- coding: utf-8 -*-
"""F 的 `attack.create_plan`：子目标缺字段时要**一次说齐**（业主 2026-10-16 亲测口径）。

## 为什么补这个文件

亲测 F 的"立项"时，我按常识写子目标，实测走了**三轮**才凑齐一个子目标的字段：

```
create_plan(subgoals=[{sid, goal, status}])            ⇒ subgoals[0] 缺少 text（子目标必须说清要做什么）
create_plan(subgoals=[{sid, text, status}])            ⇒ subgoals[0] 缺少 owner（owner 是权限面的一部分，不能默认）
create_plan(subgoals=[{sid, text, status, owner}])      ⇒ 落行 ✓
```

业主口径（逐字）：*"凡是你凭感觉第一次运行工具发现红了，都要假想真实智能体也会在这里
困惑并浪费时间和 token。"*

处置与 **B 的 `register_statement`** 同一套写法：只有一条缺时**原文案一字不动**，
多于一条时补一行整份清单。

这一组钉三件事：
1. 同时缺两个 ⇒ 拒信里**两个都点名**（并且仍然**不写库**）；
2. 只缺一个 ⇒ 拒信里**不出现**"还缺"那一行（负控：别把噪声挂上去）；
3. 给齐了 ⇒ **落到 `attack_plans` 一行**（正控：改完不许把正常路径弄坏）。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow.store import Store
from agentflow.tools import build_registry

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}


def _reg(tmp_path: pathlib.Path):
    store = Store(tmp_path / "ws")
    store.init()
    return store, build_registry(store=store, workspace_root=tmp_path / "ws").registry


def _create(reg, subgoals):
    """调一次 `attack.create_plan`；返回 `(ToolResult, 异常消息或空串)`。"""
    try:
        return reg.call("attack.create_plan", role="F", problem="探针难题：某类有限群的结构",
                        problem_key="probe:x", budget=BUDGET, subgoals=subgoals), ""
    except Exception as exc:                                  # noqa: BLE001
        return None, str(exc)


def test_two_missing_fields_are_named_at_once(tmp_path: pathlib.Path) -> None:
    """正控：同时缺 `text` 与 `owner` ⇒ 一次点名两个，而且**不写库**。"""
    store, reg = _reg(tmp_path)
    res, err = _create(reg, [{"sid": "s1"}])
    blob = err or str(getattr(res, "error", "") or "")
    assert "text" in blob and "owner" in blob, f"没有一次说齐：{blob}"
    assert "还缺" in blob, blob
    assert len(store.rows("attack_plans")) == 0, "被拒却写了库"


def test_a_single_missing_field_keeps_the_original_wording(tmp_path: pathlib.Path) -> None:
    """负控：只缺一个 ⇒ **不挂**"还缺"那一行（否则它只是噪声）。"""
    _store, reg = _reg(tmp_path)
    res, err = _create(reg, [{"sid": "s1", "text": "把命题约化到局部情形"}])
    blob = err or str(getattr(res, "error", "") or "")
    assert "owner" in blob, blob
    assert "还缺" not in blob, f"只缺一条也挂了整份清单：{blob}"


def test_a_complete_subgoal_lands_a_plan(tmp_path: pathlib.Path) -> None:
    """正控：给齐了要**真的落一行**（别为了改拒信把正常路径弄坏）。"""
    store, reg = _reg(tmp_path)
    res, err = _create(reg, [{"sid": "s1", "text": "把命题约化到局部情形", "owner": "E"}])
    assert res is not None and res.ok, (err, getattr(res, "error", ""))
    rows = store.rows("attack_plans")
    assert len(rows) == 1, rows
    assert rows[0].get("status") in ("open", "attacking"), rows[0]
