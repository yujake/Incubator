# -*- coding: utf-8 -*-
"""一个 agent 的声明（`goal-7f5116c1` 的 M2）：它"是什么"，写在一个地方。

## 为什么要有这个模块

今天"一个 agent 由什么定义"散在六处、且每一处都是手抄的：

| 处 | 内容 |
|---|---|
| `schema.py::ROLES` | 角色词表（禁改区） |
| `tools/__init__.py` | `ROLES` / `TOOL_ROLES` / `READ_ONLY_ROLES`（禁改区） |
| `capabilities.py` | 动作表 `CAPABILITIES`、召唤边 `ALLOWED_EDGES`、写集 `WRITE_SETS`（禁改区） |
| `agent_prompts.py` | `ROLE_BRIEFS`（职责/边界/政策/招牌错误/交付物/姿态）、`FACULTY_EMPHASIS`、`FACULTY_LOCAL` |
| `host.py` | 每个角色的构造器 `agent_x()` |
| `docs/ROLE-SPECS.md` | 每角色一节 + 手抄的动作表 |

于是"新建一个 agent"要同时改六处（三处在禁改区），而"调整某个 agent 的行为"要在一个
4000 行的模块里找落点。`AgentSpec` 的落点是：每个角色自己的模块里写一份 SPEC，
装配面（M3/M4）改成从这里读。

## 这一版（M2）接管了什么、没接管什么

接管（每一格都有对账判据，见 `tests/test_agent_spec_reconciliation.py`）：

- `brief`：职责 / 边界 / 政策 / 招牌错误 / 交付物 / 姿态（今天在 `agent_prompts.ROLE_BRIEFS`）；
- `emphasis` + `local_notes`：十项官能在这一岗上的轻重与自己那几句话
  （今天在 `agent_prompts.FACULTY_EMPHASIS` / `FACULTY_LOCAL`）；
- `read_only` / `summonable`：权限面上的两个布尔（今天在 `tools.READ_ONLY_ROLES` / `NON_SUMMONABLE`）；
- `edges` / `write_set`：它能召唤谁、会写哪些表（今天在 `capabilities`）；
- `class_path`：它的实现类（今天只在 `host.py` 的构造器里隐含）。

没接管（写清楚，免得被读成"已经做完了"）：动作表 `ActionSpec` 还在 `capabilities.py`，
构造工厂还在 `host.py`。M3 搬动作表、M4 搬构造工厂，两处都按同一套对账判据走；
在那之前本模块不复制那两份数据（复制一份假的真相比手抄更坏）。
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class AgentBrief:
    """一个角色的手写部分（与 `agent_prompts.RoleBrief` 逐字对应；M3 之后由本模块拥有）。"""

    duty: str
    boundary: tuple[str, ...]
    policy: tuple[str, ...] = ()
    signature_error: str = ""
    deliverable: str = ""
    stance: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    """一个 agent 的声明。`class_path` 形如 `agentflow.agent_a:AgentA`。"""

    role: str
    brief: AgentBrief
    emphasis: Mapping[str, str] = field(default_factory=dict)
    local_notes: Mapping[str, str] = field(default_factory=dict)
    read_only: bool = False
    summonable: bool = True
    edges: tuple[str, ...] = ()
    write_set: frozenset[str] = frozenset()
    class_path: str = ""

    @property
    def module(self) -> str:
        """实现类所在模块（`agentflow.agent_a`）。"""
        return self.class_path.split(":", 1)[0]

    @property
    def class_name(self) -> str:
        """实现类名（`AgentA`）。"""
        return self.class_path.split(":", 1)[1]

    def cls(self) -> type:
        """实现类（延迟 import：`agentspec` 不许在导入期拉进任何一个 agent 模块）。"""
        return getattr(importlib.import_module(self.module), self.class_name)


class AgentRegistry:
    """角色 ⇒ 声明。装配面（M3/M4）从这里读，而不是各自手抄。

    刻意不用模块级单例：`goal-7f5116c1` 的判据之一是"在测试里造一个临时角色"——
    那要求"多一个角色"是给某个注册表加一条，而不是去改一个全局常量
    （全局常量会被 import 序与缓存绑住，测试之间互相污染）。
    """

    def __init__(self, specs: Iterable[AgentSpec] = ()) -> None:
        self._specs: dict[str, AgentSpec] = {}
        for spec in specs:
            self.add(spec)

    def add(self, spec: AgentSpec) -> AgentSpec:
        """登记一个角色；重复登记直接抛（"哪一份是真的"不许变成运气）。"""
        if spec.role in self._specs:
            raise ValueError(f"角色 {spec.role!r} 已经登记过（重复登记会让'哪一份是真的'变成运气）")
        self._specs[spec.role] = spec
        return spec

    def get(self, role: str) -> AgentSpec:
        """取某个角色的声明；没有就抛（不返回 None：那会把"没登记"与"登记成空"混起来）。"""
        try:
            return self._specs[role]
        except KeyError:
            raise KeyError(f"没有登记角色 {role!r}；已登记：{sorted(self._specs)}") from None

    def roles(self) -> tuple[str, ...]:
        """已登记的角色（按登记顺序）。"""
        return tuple(self._specs)

    def read_only_roles(self) -> tuple[str, ...]:
        """只读角色（它们拿不到写工具，见 `tools/base._role_surface`）。"""
        return tuple(r for r, s in self._specs.items() if s.read_only)

    def summonable_roles(self) -> tuple[str, ...]:
        """可被召唤的角色（主控 M 不在其中）。"""
        return tuple(r for r, s in self._specs.items() if s.summonable)

    def edges(self) -> dict[str, tuple[str, ...]]:
        """角色 ⇒ 它能召唤谁（对账 `capabilities.ALLOWED_EDGES`）。"""
        return {r: s.edges for r, s in self._specs.items()}

    def write_sets(self) -> dict[str, frozenset[str]]:
        """角色 ⇒ 它会写的表（对账 `capabilities.WRITE_SETS`）。"""
        return {r: s.write_set for r, s in self._specs.items()}

    def briefs(self) -> dict[str, AgentBrief]:
        """角色 ⇒ 它的手写部分（职责/边界/政策/招牌错误/交付物/姿态）。"""
        return {r: s.brief for r, s in self._specs.items()}

    def local_notes(self) -> dict[tuple[str, str], str]:
        """`(角色, 官能)` ⇒ 该角色自己那几句话（对账 `agent_prompts.FACULTY_LOCAL`）。"""
        return {(r, f): t for r, s in self._specs.items() for f, t in s.local_notes.items()}

    def emphasis(self) -> dict[str, Mapping[str, str]]:
        """角色 ⇒ 十项官能在它这一岗上的轻重（对账 `agent_prompts.FACULTY_EMPHASIS`）。"""
        return {r: s.emphasis for r, s in self._specs.items()}


#: `builtin_registry()` 收集 SPEC 的模块（一个角色一个模块；M5 会把它们变成包）。
_SPEC_MODULES: tuple[str, ...] = (
    "agent_a", "agent_b", "agent_c", "agent_d", "agent_e", "agent_f", "agent_g", "agent_h",
    "conductor",
)


def builtin_registry() -> AgentRegistry:
    """把内置角色的 SPEC 收成一张注册表（延迟 import：本模块保持"叶子"）。

    为什么是函数而不是模块级常量：模块级常量会在 `import agentflow.agentspec` 的那一刻
    就把 8 个角色模块全拉进来（`agent_d` 4188 行、连带 store/capabilities/…），
    而 `agentspec` 是给装配面与判据用的薄层 —— 它不该有这种副作用。
    """
    reg = AgentRegistry()
    for name in _SPEC_MODULES:
        mod = importlib.import_module(f".{name}", __package__)
        spec = getattr(mod, "SPEC", None)
        if spec is None:
            raise ValueError(f"{name} 里没有 SPEC —— 角色模块必须自带声明（M2 的对账判据会点名）")
        reg.add(spec)
    return reg
