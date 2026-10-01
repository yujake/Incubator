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
class BuilderDeps:
    """装配期能交给工厂的东西（`host._Builder` 的公开面）。

    工厂（`AgentSpec.build`）**只吃这个对象**，不碰 `_Builder`：这样"一个角色要什么依赖"
    写在它自己的声明里（`needs` / `peers`），而"这些依赖怎么造"留在接线层（`host`）——
    两件事分开之后，"新建一个 agent"不需要在 `host` 里加分支（`goal-7f5116c1` M4）。
    """

    role: str
    store: Any
    instance: str = ""
    #: 该角色用的模型缝（`_llm_for(role)` 已算好）
    llm: Any = None
    #: 该角色的配置段（G/H 的那一份**已经带 `actor`**，与今天逐字一致）
    config: Mapping[str, Any] = field(default_factory=dict)
    #: 检索后端（声明里 `needs=("providers",)` 时才给）
    providers: tuple[Any, ...] = ()
    #: 抽取器（B 用；`needs=("extractor",)` 时才给）
    extractor: Any = None
    #: 工作区根（E/G 用；`needs=("workspace_root",)` 时才给）
    workspace_root: Any = None
    #: actor 名（实例标签已折进它）
    actor: str = ""
    #: 下载器（A 用；`needs=("downloader",)` 时才给）
    downloader: Any = None
    #: 构造期要拿到的邻居实例（D→C、F→E）
    peers: Mapping[str, Any] = field(default_factory=dict)


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
    #: 本角色的动作表（M3 起由 `specs/<角色>.py` 拥有；`capabilities.CAPABILITIES`
    #: 从它派生）。`M` 是空元组：主控的"动作"是 `summon()` 本身，不是 Agent 方法。
    actions: tuple[ActionSpec, ...] = ()
    class_path: str = ""
    #: 构造期依赖工厂（M4）：`(BuilderDeps) -> 实例`。写在角色自己的声明里，
    #: 于是"新建一个 agent"不需要在 `host` 里加分支。
    build: Callable[[BuilderDeps], Any] | None = None
    #: 工厂需要哪些装配期资源（`providers` / `downloader` / `extractor` / `workspace_root`）。
    #: 空元组 = 只要 `store` / `config` / `llm` / `actor`。
    needs: tuple[str, ...] = ()
    #: 构造期要拿到的邻居实例（D 要 C、F 要 E）——"谁能叫谁"之外的另一件事：
    #: 这是"谁在构造期就握着谁"，今天由 `host._Builder.get()` 的同单例保证。
    peers: tuple[str, ...] = ()

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


def builtin_registry() -> AgentRegistry:
    """把内置角色的声明收成一张注册表（读 `specs/` 这个叶子包）。

    为什么读 `specs/` 而不是九个角色模块：角色模块是**实现**（`agent_d` 4000+ 行，
    连带 store/capabilities/…），而注册表是给装配面与判据用的薄层 ——
    M2 时只能这么取是因为声明写在角色模块里；M3 把声明搬进 `specs/<角色>.py`（叶子）之后，
    取声明不再需要拉起任何实现。这一层保持"叶子"这条性质因此是**结构性**的，
    不再只是注释里的一句承诺。
    """
    from . import specs as _specs

    reg = AgentRegistry()
    for role, spec in _specs.builtin_specs().items():
        assert spec.role == role, f"specs/{role.lower()}.py 里的 SPEC.role 是 {spec.role!r}"
        reg.add(spec)
    return reg


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


# ---------------------------------------------------------------- 从 capabilities.py 搬来的
#
# 下面这四块原本在 `capabilities.py`（禁改区）。M3 把"角色动作表"的真身搬进
# `specs/<角色>.py` 之后，`capabilities` 变成**从它派生** —— 于是"声明类型"与
# "声明词表"必须待在更低的一层（叶子），否则 `specs` 反过来 import `capabilities` 会成环。
#
# 搬移方式：逐字（含注释），判据见 `tests/test_agent_spec_reconciliation.py` 与
# `tests/test_capabilities_two_layer.py`；`capabilities` 侧改成 `from .agentspec import …`，
# 公开名与取值一个都没变。

#: 动作的副作用等级。与 `tools/base.SIDE_EFFECTS` 逐字一致（FC-07：副作用是一等公民）。
#: 为什么不从 `tools.base` import 过来：`capabilities` 是更底层的声明层，
#: 它要能被 `verify`、能被 CLI 单独读，而不该拖上整个工具层。两处字面量由
#: :func:`assert_capabilities` 交叉断言（`assert set(SIDE_EFFECTS) == set(TOOL_SIDE_EFFECTS)`），
#: 于是"两套说法"不可能悄悄分叉。
#:
#: B3 收官时 `network` 从这里与 `tools/base.py` 一起删掉（同一个原子改动）。
SIDE_EFFECTS: tuple[str, ...] = ("none", "read", "write_local")


#: 第一根轴（改不改我们拥有的东西）的取值。与 `tools.base.EFFECT` 逐字一致，
#: 同样由 :func:`assert_capabilities` 交叉断言 —— 形态照抄既有第 5 条，
#: 不发明第二套机制（P-13 §3.4）。
EFFECT: tuple[str, ...] = ("none", "read", "write_local")


#: 第二根轴（能不能触到我们不拥有的东西）的取值。与 `tools.base.EXTERNAL` 逐字一致。
#:
#: 能力层逐动作声明 `external`（`ActionSpec.external`），取值就是这里的三个。
#: 词表仍必须在本层有一份，因为两份字面量的比对（第 5 条的同族断言）是
#: "两套说法不可能悄悄分叉"的唯一机器判据。
EXTERNAL: tuple[str, ...] = ("none", "egress", "exec")


#: `side_effect="unknown"` 单独存在，且不在 `SIDE_EFFECTS` 里。
#:
#: 为什么需要它：本轮的能力表是从真实代码推导的，有几个方法我读不出它到底写不写
#: （例如 `AgentC.register_tools` 只改自己进程内的注册表，`AgentF.e` 只是惰性建 E）。
#: 把它们硬填成 `"read"` 是编造；填 `"none"` 也一样。按三态纪律，这里必须有一个
#: "我不知道"的值，并且它必须让并发判据保守（未知 ⇒ 当写者处理 ⇒ 串行）。
UNKNOWN_SIDE_EFFECT = "unknown"


@dataclass(frozen=True)
class ActionSpec:
    """一个角色动作的声明。参数 schema 用 JSON Schema 子集（与 `tools` 同风格）。

    `params` 的根必须是 object 且给出 `properties`/`required`：主控与
    `SubagentBackend` 都按它构造调用，"参数是什么"必须是机器可读的，
    而不是只写在 docstring 里。
    """

    role: str
    action: str
    summary: str
    #: JSON Schema 子集（object 根）。空参数动作也要写 `properties: {}`，
    #: 而不是留 None —— None 与"无参数"在下游会被当成两件事。
    params: Mapping[str, Any] = field(default_factory=dict)
    #: 该动作产出什么（人可读的一句话；机器可读的部分由 backend 决定）。
    returns: str = ""
    side_effect: str = "read"
    #: `agent_<role>.py` 里 真实存在的公开方法名（装配期逐个 `getattr` 核过）。
    handler_name: str = ""
    #: 逐动作的 `external` 声明（`none` / `egress` / `exec`）；`None` = 还没迁移。
    #:
    #: 为什么这个字段现在才出现（B3 第 0 步，只读勘察结论）：在此之前
    #: `action_axes` 只能从 `side_effect` 派生 external（`network` 走遗留翻译表、
    #: 其余一律 `"none"`）⇒ 能力层结构上表达不了 `external="exec"`。
    #: 于是"只改工具层"必然是半迁移，而 `declaration_divergences()` 会判成
    #: "能力层低估了风险轴"、`assert_capabilities()` 第 [7] 条在导入期就炸
    #: （实测：`pytest tests/test_policy.py` 收集期 ERROR）。
    #:
    #: 注意：`None` 默认值在 B3 收官后仍然保留，它是"未迁移"的显式标记，
    #: 而三态纪律要求"没声明"与"声明成 `none`"是两件事 ——
    #: 本轮把剩下的动作全部迁移了，判据里也不再有遗留分支，
    #: 但字段本身不删（删了它，"未迁移"这件事就无法被表达，
    #: 于是 `action_axes` 会把"没声明"静默读成 `("none", …)`）。
    external: str | None = None

    def __post_init__(self) -> None:
        if self.side_effect not in (*SIDE_EFFECTS, UNKNOWN_SIDE_EFFECT):
            raise ValueError(
                f"side_effect 必须是 {(*SIDE_EFFECTS, UNKNOWN_SIDE_EFFECT)} 之一，收到 {self.side_effect!r}"
            )
        if not str(self.handler_name or "").strip():
            raise ValueError(
                f"{self.role}.{self.action} 没有 handler_name —— "
                "没有实现落点的动作只是一个愿望，主控召唤它时只能失败"
            )
        schema = dict(self.params or {})
        if schema.get("type") != "object":
            raise ValueError(
                f"{self.role}.{self.action} 的 params 根必须是 object，收到 {schema.get('type')!r}"
            )
        if not isinstance(schema.get("properties"), Mapping):
            raise ValueError(f"{self.role}.{self.action} 的 params 必须给出 properties")

    def to_dict(self) -> dict:
        """这条动作声明的可序列化形状（`external` 不在其中：它是派生轴，见 `action_axes`）。"""
        return {
            "role": self.role,
            "action": self.action,
            "summary": self.summary,
            "params": dict(self.params),
            "returns": self.returns,
            "side_effect": self.side_effect,
            "handler_name": self.handler_name,
        }


def _obj(props: Mapping[str, Any], required: tuple[str, ...] = ()) -> dict:
    """构造 object 根 schema 的小工具（与 `tools.base` 的 `obj_schema` 同风格）。"""
    return {
        "type": "object",
        "properties": dict(props),
        "required": list(required),
        "additionalProperties": False,
    }


_S = {"type": "string"}
_I = {"type": "integer"}
_N = {"type": "number"}
_B = {"type": "boolean"}
_ARR_S = {"type": "array", "items": {"type": "string"}}
#: `array<integer>`。R-36（`draft/28` §164）为 `G.register_dependency.page_range` 新增。
#:
#: 为什么必须新列一个：这里原来写的是 `_ARR_S`，而工具层
#: （`doc_tools` 的 `doc.register_dependency`）写的是
#: `{"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2}` ——
#: 于是**没有任何一种取值能同时过两道门**（实测 2026-09-29）：
#: `[45, 46]` 能力层拒（"必须是 string"）工具层放行；`["45", "46"]` 能力层放行
#: 工具层拒（"必须是 integer"）。实现本体 `doc_tools._coerce_page_range` 两种都收，
#: 但"两层各自判死一半"意味着这条链路上**没有**合法形状。
#: 取 `array<integer>` 而不是 `array<string>`：工具层的校验是真身，
#: 而 `_coerce_page_range` 的规范形态就是 `[start, end]`（`minItems/maxItems` 也对得上）。
_ARR_I = {"type": "array", "items": {"type": "integer"}}
_OBJ = {"type": "object"}
#: 一行行记录的序列（依赖行、发现行…）。刻意与 `_OBJ` 分开。
#:
#: 为什么要单列一个常量：`H.review` / `G.render` 的 `dependencies` 先前都声明成
#: `_OBJ`，而实现侧（`AgentH.review` → `review.review_document`、
#: `AgentG.render` → `doc_tools.render_markdown`）交下去的是序列 ——
#: 于是任何一次"把依赖逐条交给审校/渲染"的派活，都在参数门被判
#: `H.review 的参数不合法：dependencies. 必须是对象，收到 array`，
#: 而理由码被记成 `unknown_action`（"这个角色没这个本事"），与真相不符。
#: 实测 2026-09-29（P3 派 H 审台账）：`summon(role="H", action="review",
#: params={"doc_id": "0000", "dependencies": [ …13 行 external_unavailable… ]})`
#: 被参数门拒。导入期的交叉断言（`param_seam_violations`）只比 property 名
#: 与实现签名，不比类型，所以它照旧全绿 —— 这条注释与
#: `tests/test_capability_seams.py` 的正控一起，是这一格唯一的机器判据。
_ARR_OBJ = {"type": "array", "items": {"type": "object"}}
