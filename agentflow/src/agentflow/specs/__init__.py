# -*- coding: utf-8 -*-
"""把九个角色的声明收成表（`goal-7f5116c1` M3）。

`capabilities.py` 从这里的 `action_table()` / `edges()` / `write_sets()` 派生自己的三张表，
`agentspec.builtin_registry()` 从 `builtin_specs()` 取注册表 —— 于是"角色动作表"的真身
只有一份（`specs/<角色>.py`），而不是"声明一处、派生一处、再手抄一处"。

这一包在 `.noai-paths` 里受保护：它现在就是权限面的落点。
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .. import schema as S

if TYPE_CHECKING:  # pragma: no cover - 只为类型
    from ..agentspec import ActionSpec, AgentSpec

#: 收表的顺序 = 角色词表（`schema.ROLES`）后面接主控。
#: 刻意不写死那串字母：lint `R005` 认的就是"角色名单只能有一个来源"，
#: 而 `schema.ROLES` 是那个来源（第一版写死时它当场报了一条 warning，实测）。
_ORDER: tuple[str, ...] = (*S.ROLES, S.CONDUCTOR_ROLE)


def builtin_specs() -> dict[str, "AgentSpec"]:
    """九个角色的声明（按 `_ORDER`；每个角色的模块是叶子，只依赖 `..agentspec`）。"""
    out: dict[str, "AgentSpec"] = {}
    for role in _ORDER:
        mod = importlib.import_module(f".{role.lower()}", __package__)
        out[role] = mod.SPEC
    return out


def action_table() -> dict[str, tuple["ActionSpec", ...]]:
    """角色 ⇒ 动作表（`capabilities.CAPABILITIES` 的真身）。"""
    return {role: spec.actions for role, spec in builtin_specs().items()}


def edges() -> dict[str, frozenset[str]]:
    """角色 ⇒ 它能召唤谁（`capabilities.ALLOWED_EDGES` 的真身）。"""
    return {role: frozenset(spec.edges) for role, spec in builtin_specs().items()}


def write_sets() -> dict[str, frozenset[str]]:
    """角色 ⇒ 它会写的表（`capabilities.WRITE_SETS` 的真身）。"""
    return {role: spec.write_set for role, spec in builtin_specs().items()}


def non_summonable() -> frozenset[str]:
    """不可被召唤的角色（`capabilities.NON_SUMMONABLE` 的真身）。"""
    return frozenset(role for role, spec in builtin_specs().items() if not spec.summonable)
