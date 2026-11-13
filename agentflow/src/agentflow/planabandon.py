# -*- coding: utf-8 -*-
"""plan 级「放弃理由」的受控词表（唯一真身）。

业主 2026-11-13 裁定（先给一档，后更正为三档）：

> 「`math_error` 和 `difficulty` 是正确的，不再需要是正确的，需要调整是错误的，
>   需要调整在放弃中应该是不再需要放弃掉原 plan 再开一个新 plan。」

- 三档，就是这三个：
  1. `math_error` —— 命题本身有实质数学错误（沿用命题级那一档的语义与判据）；
  2. `difficulty` —— 证明过程中遇到难以逾越的困难（沿用命题级那一档）；
  3. `不再需要` —— plan 没毛病，但它已不是推进目标所必需的那一条。
- 「需要调整」不是一个理由，是一个组合操作：
  `attack.abandon_plan(reason="不再需要")` ＋ 新设一条 plan。词表里没有这一档，
  把它当 `reason` 传进来会受控拒。

## 为什么前两档不在这里写字符串

前两档的标识符就取 `statementabandon` 的那两个常量（`ABANDON_KIND_MATH_ERROR` /
`ABANDON_KIND_DIFFICULTY`）：业主口径是"沿用命题级那一档的语义与判据，别新造"。
两处各写一份 `"math_error"` 就是"同一件事两个名字"，漂了不会有任何东西会响。

## 为什么单独一个模块

写侧（`agent_f/abandon_plan.py`：判据）与工具声明（`tools/attack_tools.py`：参数 enum）
都要读这张表，而 `attack_tools` 被 `agent_f._support` 在模块加载期导入
（`from ..tools import attack_tools as AT`）—— 让工具层反过来 import `agent_f`
会成环。本模块是纯数据、零依赖，两边都依赖它，谁也不欠谁（与 `stop_reasons.py`
同一种放法）。
"""
from __future__ import annotations

from .statementabandon import ABANDON_KIND_DIFFICULTY, ABANDON_KIND_MATH_ERROR

#: 「不再需要」这一档（plan 级自有的一档；命题级没有它）。
PLAN_ABANDON_NOT_NEEDED = "不再需要"

#: plan 级放弃理由：三档，前两档沿用命题级的标识符。
PLAN_ABANDON_REASONS: tuple[str, ...] = (
    ABANDON_KIND_MATH_ERROR,
    ABANDON_KIND_DIFFICULTY,
    PLAN_ABANDON_NOT_NEEDED,
)

#: 哪几档要求"说不出证据就不许放弃"（沿用命题级那两档的证据口径）。
#:
#: - `math_error`：`basis` 要点出错误（哪一步、错的是什么）；
#: - `difficulty`：`basis` 要说清困难，`difficulty` 给一句困难描述，
#:   `salvaged` 把旧证明里可取之处拆成引理写清（形状与命题级同一份
#:   `statementabandon._salvaged_items`）。
PLAN_ABANDON_EVIDENCE_REASONS: tuple[str, ...] = (
    ABANDON_KIND_MATH_ERROR, ABANDON_KIND_DIFFICULTY,
)
