# -*- coding: utf-8 -*-
"""plan 级「放弃理由」的受控词表（唯一真身）。

业主 2026-11-13 裁定 Q2：

> 「F 应该有新的放弃理由为不再需要」

- **只有一档**：`不再需要`。业主点名"plan 级没有「失败 / 冲突」的对应物，不许自己编"，
  所以这里不搬 `statementabandon.ABANDON_KINDS` 那四档命题级换号理由 ——
  它们各自要缺陷引用 / 拆出的引理 / 实验号 / 空间读数，而一条 plan 没有这些证据面。
- 自由文本在这里没有位置：词表外的 `reason` 由 `agent_f.abandon_plan` 受控拒。

## 为什么单独一个模块

写侧（`agent_f/abandon_plan.py`：判据）与工具声明（`tools/attack_tools.py`：参数 enum）
都要读这张表，而 `attack_tools` 被 `agent_f._support` 在模块加载期导入
（`from ..tools import attack_tools as AT`）—— 让工具层反过来 import `agent_f`
会成环。本模块是纯数据、零依赖，两边都依赖它，谁也不欠谁（与 `stop_reasons.py`
同一种放法）。
"""
from __future__ import annotations

#: plan 级放弃理由：**只有这一档**。
PLAN_ABANDON_REASONS: tuple[str, ...] = ("不再需要",)
