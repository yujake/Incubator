"""角色能力表 + 写集 + 允许的召唤边（主控编队的声明层）。

## 这一层解决什么问题

主控要"按需召唤 A–H"，它必须能回答三个问题，而这三个问题都不许靠猜：

1. 这个角色有哪些动作？ —— `CAPABILITIES`
2. 跑这个动作会写哪几张表（于是谁不能和谁并发）？ —— `WRITE_SETS`
3. 谁允许召唤谁？ —— `ALLOWED_EDGES`

## 三条纪律（每一条都是"不许另写第二份判据"的形态）

- 动作来自真实代码：`ActionSpec.handler_name` 必须是 `agent_x.py` 里真的存在
  的公开方法。这不是注释约定，而是 :func:`assert_capabilities` 在导入期用
  `importlib` 把类取出来、逐个 `callable(getattr(cls, name))` 核过的。
  编造一个不存在的动作名会让模块根本 import 不进来 —— 这是刻意的：
  能力表一旦与实现漂移，"主控能召唤什么"就成了一句没有依据的话。
- 写集来自真实代码的 `store.tx(...)` / `alloc_id(...)`：`WRITE_SETS` 里每一行
  都带 `文件:行号` 证据（见各处注释）。为什么必须这样：写集是并发安全判据
  （两张写集相交 ⇒ 串行）。它写错一个表名，后果不是报错，而是两个任务真的同时
  改同一批行，而它们的判重/去重互相看不见 —— 静默的数据损坏。
  已知的一处间接写：`F → A` / `F → D` 的实际写入发生在 A/D 自己的
  `tx(...)` 里（`agent_f.py:852`、`agent_f.py:938` 只提交请求行）。所以 F 的写集
  必须并上 A 与 D 的写集吗？本轮不并，理由见 `WRITE_SETS["F"]` 的注释：
  并集会让 F 与 A/D 永远不能并发，而 F 提交请求与 A 消费请求本来就是
  流水线的正常形态（`search_requests` 上已有租约机制处理这件事）。
  这是一条有意的取舍，不是遗漏。
- 只读角色的写集必须为空（或只有它自己的产出表）：见 `READ_ONLY_WRITE_EXCEPTIONS`。
  这一条与 `tools.READ_ONLY_ROLES` 交叉断言 —— 工具面里没有写工具，而能力表里
  却有写集，那就说明两个模块对同一个角色有两套说法，交叉断言让它当场炸。
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import schema as S

#: 动作的副作用等级。与 `tools/base.SIDE_EFFECTS` 逐字一致（FC-07：副作用是一等公民）。
#: 为什么不从 `tools.base` import 过来：`capabilities` 是更底层的声明层，
#: 它要能被 `verify`、能被 CLI 单独读，而不该拖上整个工具层。两处字面量由
#: :func:`assert_capabilities` 交叉断言（`assert set(SIDE_EFFECTS) == set(TOOL_SIDE_EFFECTS)`），
#: 于是"两套说法"不可能悄悄分叉。
SIDE_EFFECTS: tuple[str, ...] = ("none", "read", "write_local", "network")

#: 第一根轴（改不改我们拥有的东西）的取值。与 `tools.base.EFFECT` 逐字一致，
#: 同样由 :func:`assert_capabilities` 交叉断言 —— 形态照抄既有第 5 条，
#: 不发明第二套机制（P-13 §3.4）。
EFFECT: tuple[str, ...] = ("none", "read", "write_local")

#: 第二根轴（能不能触到我们不拥有的东西）的取值。与 `tools.base.EXTERNAL` 逐字一致。
#:
#: 能力层本轮不逐动作声明 `external`（那是 B3 的迁移清单），而是用
#: :func:`external_axis_of` 从行动作的 `side_effect` 按同一张遗留翻译表算出来。
#: 词表仍必须在本层有一份，因为两份字面量的比对（第 5 条的同族断言）是
#: "两套说法不可能悄悄分叉"的唯一机器判据。
EXTERNAL: tuple[str, ...] = ("none", "egress", "exec")

#: 遗留取值 -> 两根轴上的翻译（与 `tools.base.LEGACY_SIDE_EFFECTS` 逐字一致）。
#:
#: 能力层只用到 `network` 这一条：它丢掉了"是出网还是起进程"。A 的两个动作与
#: H 的 `review` 都声明了它，而它们都同时写我们的表（`WRITE_SETS`），
#: 所以效果一栏在这里取 `write_local` —— 与工具层逐工具表（`search.download` /
#: `ocr.run`）同一条口径：效果按事实填，不按遗留取值字面填。
LEGACY_NETWORK_AXES: tuple[str, str] = ("egress", "write_local")

#: `side_effect="unknown"` 单独存在，且不在 `SIDE_EFFECTS` 里。
#:
#: 为什么需要它：本轮的能力表是从真实代码推导的，有几个方法我读不出它到底写不写
#: （例如 `AgentC.register_tools` 只改自己进程内的注册表，`AgentF.e` 只是惰性建 E）。
#: 把它们硬填成 `"read"` 是编造；填 `"none"` 也一样。按三态纪律，这里必须有一个
#: "我不知道"的值，并且它必须让并发判据保守（未知 ⇒ 当写者处理 ⇒ 串行）。
UNKNOWN_SIDE_EFFECT = "unknown"

#: 保守判据：哪些副作用等级算"会碰数据"。
#: `unknown` 也算 —— 宁可少并发，不可让一个不确定的东西和别的任务并行改数据。
_WRITE_LIKE = ("write_local", "network", UNKNOWN_SIDE_EFFECT)


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
        return {
            "role": self.role,
            "action": self.action,
            "summary": self.summary,
            "params": dict(self.params),
            "returns": self.returns,
            "side_effect": self.side_effect,
            "handler_name": self.handler_name,
        }


def action_axes(spec: ActionSpec) -> tuple[str, str]:
    """一个动作在两根轴上的取值，语义是 `(external, effect)`。

    ## 为什么能力层不逐动作声明 `external`

    能力层本轮（B1/B2）只迁移词表与派生策略，逐动作的 `external` 声明是
    B3 的迁移清单（P-13 §3.6 的 B3：`A.run_once` / `A.run` / `E.check_formal` …）。
    在那之前，这里用同一张遗留翻译表把 `side_effect` 折成两根轴 ——
    于是两层说的是同一种语言，可以逐条比对（:func:`declaration_divergences`）。

    ## 为什么 `network` 的效果一栏是 `write_local` 而不是默认的 `none`

    工具层的默认值 `none` 是"这个取值字面上说过的话"；能力层这三个动作
    （`A.run_once` / `A.run` / `H.review`）都由 `WRITE_SETS` 逐条登记了写入面，
    所以按事实填 `write_local`。这与工具层逐工具表
    （`search.download` / `ocr.run` 的效果一栏是 `write_local`）是同一条口径：
    效果按事实填，不按遗留取值的字面填。
    """
    if spec.side_effect == "network":
        return LEGACY_NETWORK_AXES
    return ("none", spec.side_effect)


def effect_axis_of(spec: ActionSpec) -> str:
    """一个动作在"改不改我们拥有的东西"这根轴上的取值。"""
    return action_axes(spec)[1]


def external_axis_of(spec: ActionSpec) -> str:
    """一个动作在"能不能触到我们不拥有的事"这根轴上的取值。"""
    return action_axes(spec)[0]


def unmapped_actions() -> list[tuple[str, str]]:
    """找不到对应工具的动作（`(role, action)`）。

    ## 这条判据要回答的问题

    P-13 §10 第 3 条实测的形态是：同一个动作在两层有两个估值
    （工具层 `verify.check_formal` 声明 `read`、能力层 `E.check_formal`
    声明 `network`），而"没有任何机器判据看见过"。

    看见它的前提是先把"能力层的动作"与"工具层的 spec"按名字对上；
    对不上的动作就必须如实报出来，而不是当成"一致"（那是 P16 的
    "判据真空通过"：空集永远是子集）。
    """
    tools = _tool_side_effects()
    unmapped: list[tuple[str, str]] = []
    for role, specs in CAPABILITIES.items():
        for spec in specs:
            if _matching_tool_name(spec, tools) is None:
                unmapped.append((role, spec.action))
    return sorted(unmapped)


#: 角色 -> 它可能借由工具层落地的工具组。
#:
#: 为什么必须显式写下来：动作与工具的对应关系只有一条结构性约定
#: （工具的最后一个名字段 == 动作的 `handler_name`），而这条约定在短名上必然
#: 撞车 —— 实测 `run` 在能力层有两个动作（`A.run` / `B.run`），在工具层有一个
#: 工具（`ocr.run`）。不加这张表，两条动作会被同一个工具"对上"，
#: 于是报告里出现一条纯属拼写巧合的"不一致"（这是本项目最反对的假报警：
#: 它会让整条判据失去可信度）。
#:
#: 表里的每一组都写上了理由，因为"这个角色会不会经由这一组工具落地"
#: 是一条设计判断，不是可以从名字推出来的事实：
#:   - `B` 有 `ocr`：`AgentB.run` 会调 OCR 读 PDF（`ocr.run` 声明 `network`），
#:     所以"B 的动作可能与 ocr 工具同名"是真实存在的对应，不是巧合；
#:   - `A` / `D` 有 `search` / `research`：检索与研究的落地工具；
#:   - `E` / `F` 有 `verify` / `attack`：实验与攻坚的落地工具；
#:   - `G` / `H` 有 `doc` / `review`：撰写与审校的落地工具；
#:   - 通用组（`fs` / `table` / `graph` / `trace`）任何角色都可能用到，
#:     但只在唯一命中时才认为对上了。
#:
#: 表里没有的角色组合 ⇒ 报成"两层声明没有比对"（info，三态里的 unknown），
#: 不猜映射。
_TOOL_GROUPS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "A": ("search", "table", "fs", "research", "trace", "graph"),
    "B": ("ocr", "table", "fs", "trace", "graph"),
    "C": ("graph", "table", "fs", "trace"),
    "D": ("research", "search", "trace", "graph", "table", "fs"),
    "E": ("verify", "table", "fs"),
    "F": ("attack", "table", "fs"),
    "G": ("doc", "table", "fs"),
    "H": ("review", "verify", "doc", "table", "fs"),
}


def matching_tool_name(spec: ActionSpec) -> str | None:
    """按唯一性约定找该动作对应的工具名；不唯一或找不到时返回 `None`。

    约定只有一条、且是结构性的：工具的最后一个名字段 == 动作的
    `handler_name`，且工具组必须在 :data:`_TOOL_GROUPS_BY_ROLE` 里登记过。
    同名多义（`run` 在能力层有两个动作）不算对上 —— 猜一个映射会让报告出错，
    而"没查成"必须与"查过了没问题"分开（三态纪律）。
    """
    return _matching_tool_name(spec, _tool_side_effects())


def _matching_tool_name(spec: ActionSpec, tools: Mapping[str, Any]) -> str | None:
    """:func:`matching_tool_name` 的纯函数形态（工具表由调用方给，避免重复解析源码）。"""
    groups = _TOOL_GROUPS_BY_ROLE.get(spec.role, ())
    hits = sorted(
        name for name in tools
        if name.split(".")[-1] == spec.handler_name and name.split(".")[0] in groups
    )
    return hits[0] if len(hits) == 1 else None


def _tool_side_effects() -> dict[str, tuple[str, str, bool]]:
    """全仓工具名 -> `(side_effect, external, 是否显式写了 external=)`。

    不装配工具层，只读源码里的声明。第三个分量是"这条工具的 external
    是人写下来的精确声明，还是从遗留取值 `network` 翻译来的"——
    两者的判据强度不同：精确声明与能力层矛盾是 error（谁在低估风险），
    而遗留工具的两根轴本来就带着一层不确定，只能报 warning。

    ## 为什么是"读源码"而不是"装配一次工具层"

    工具的声明有两种落点，实测都取不到对象：

    1. `reset()/register()` 函数体里现造的 `ToolSpec(...)`（`search_tools` /
       `ocr_tools` / `verify_tools` / `attack_tools` / `doc_tools` / `review_tools`）——
       它们需要 `store` 与工作区，装配一次会在导入期碰文件系统，
       而"能不能 import 能力表"不该依赖于当前目录里有什么；
    2. 模块级 `@tool(...)` 标记的函数（`fs_tools` / `table_tools` /
       `research_tools` / `graph_tools` / `trace_tools`）。

    两者都写在源码里、都是字面量（名字与 `side_effect`），所以本函数用
    `ast` 把它们读出来。

    ## 这是"核对"，不是"推断"（两者必须分清）

    本函数读的是已经由人写下的 `side_effect` 字面量，用来与能力层的声明比。
    它不从 handler 的函数体推断副作用 —— 那正是 N-4 已经否决的做法
    （P-13 §9①：22/55 取不到 handler 源码、9 个转发型 handler 是假阳性）。
    读不到源码文件时（例如装了 wheel）返回空表，于是
    :func:`declaration_divergences` 会把每条动作报成"没有比对"（unknown），
    不会折叠成"没问题"。
    """
    out: dict[str, tuple[str, str, bool]] = {}
    base = Path(__file__).resolve().parent / "tools"
    for mod_name in _TOOL_MODULES:
        path = base / f"{mod_name}.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for name, side, declared, explicit in _declared_side_effects(tree):
            out[name] = (side, declared, explicit)
    return out


def _declared_side_effects(tree: ast.AST) -> list[tuple[str, str, str, bool]]:
    """从一棵模块 AST 里读出 `(工具名, side_effect, external, 是否显式声明 external)`。

    覆盖两种声明形态：
      - `ToolSpec(name="...", side_effect="...", external="...")`（关键字或前两个位置参数）；
      - `@tool("...", ..., side_effect="...", external="...")` 装饰器。

    只认字面量：名字或取值是变量/表达式时跳过（记不进表），
    于是那条动作在报告里是"没有比对"而不是"比对通过"。
    """
    found: list[tuple[str, str, str, bool]] = []

    def literal(node: ast.AST | None) -> str | None:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    def from_call(node: ast.Call, *, positional_name: bool) -> None:
        name: str | None = None
        side = "none"
        declared = "none"
        explicit = False
        if positional_name and node.args:
            name = literal(node.args[0])
        elif not positional_name and node.args:
            name = literal(node.args[1]) if len(node.args) > 1 else None
        for kw in node.keywords:
            if kw.arg == "name":
                name = literal(kw.value)
            elif kw.arg == "side_effect":
                side = literal(kw.value) or "none"
            elif kw.arg == "external":
                declared = literal(kw.value) or "none"
                explicit = True
        if name:
            found.append((name, side, declared, explicit))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if fname == "ToolSpec":
                from_call(node, positional_name=False)
            elif fname == "tool":
                from_call(node, positional_name=True)
    return found


#: 工具模块名单（与 `tools._MODULES` 同源，这里只用于"读声明"）。
_TOOL_MODULES: tuple[str, ...] = (
    "table_tools",
    "fs_tools",
    "search_tools",
    "ocr_tools",
    "graph_tools",
    "trace_tools",
    "research_tools",
    "verify_tools",
    "attack_tools",
    "doc_tools",
    "review_tools",
)


@dataclass(frozen=True)
class DeclarationDivergence:
    """两层声明不一致的一条记录。带机器可读的码。"""

    code: str
    level: str  # error | warning | info
    where: str
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "level": self.level, "where": self.where, "message": self.message}


def declaration_divergences() -> list[DeclarationDivergence]:
    """两层声明（工具层 `ToolSpec` vs 能力层 `ActionSpec`）里可判定的不一致。

    ## 为什么这条判据必须存在

    `docs/PROPOSALS.md` 的 P-13 §10 第 3 条实测：`verify.check_formal` 在工具层
    声明 `read`、在能力层声明 `network`，而没有任何机器判据看见过它 ——
    R006 只看工具层，且是文件级共现。本轮（B1/B2）就把这条不一致变成
    可判定的：两层各自按自己那根轴估值，名字按唯一性约定对上，对不上就报。

    ## 比对口径（三条，逐条都有反例在真实树上）

    两层声明的用途不同，所以不是逐字相等才叫一致（`WRITE_SETS` 的长注释
    逐字登记过这件事：工具层描述"默认调用"的副作用，能力层描述"可能写"的表）：

    1. 能力层在某一根轴上更保守 ⇒ 不报。 那是刻意的（能力表驱动并发与召唤判据，
       宁可多要一次裁决）。`A.run_once`（工具层 `search.*` 是 `read`，能力层
       `network`）就是这一类。
    2. 能力层在某一根轴上更小 ⇒ 报 error。 工具说 `exec`/`egress`、能力说
       `none`，或工具说写、能力说读 —— 那是"能力表以为它更安全"，
       而低估风险比高估贵得多。
    3. 能力层用遗留取值 `network` 时，它对两根轴各有一个满足条件。
       这一条是本函数能看见 §10 第 3 条那个形态的关键：`network` 是一个
       把两根轴压在一起的取值，它说"会做本框架管不住的事"。于是：
       - 工具层的 `external != "none"` 满足它（真的会触到我们不拥有的事）；
       - 反过来，工具层 `external == "none"` 与它矛盾 —— 能力表把一个
         什么外部调用都没有的动作报成了 `network`，而开发文档 P7 的原始形态
         就是"声明撒谎 ⇒ 权限面在说假话"（只不过这次撒谎的是保守那一侧：
         审计问"哪些动作会出网"时会把一个纯本地的内核检查器列进去，
         P-13 §2.3 逐字写了这一点）。这一类的级别是 `warning`：它不改审批面，
         只让审计口径失真。

    ## 为什么它只报告、不在导入期断言

    实测（快照）：真实树上存在这类不一致，其中 `E.check_formal`
    （工具层 `read` / 能力层 `network`）是提案自己登记的、要由 B3 收敛的一条。
    把它做成导入期 `AssertionError` 会让 `import agentflow.capabilities`
    永久失败，于是整仓的导入期断言（包括既有的第 1–5 条）全部失效 ——
    那不是"更严"，是把门砸了。所以：报告可判定、可复现、可测试；
    升级为 error 由 `STRICT_DECLARATIONS` 开关在 B3 收口时翻。
    """
    from .tools.base import EFFECT as TOOL_EFFECT
    from .tools.base import EXTERNAL as TOOL_EXTERNAL

    tools = _tool_side_effects()
    by_handler: dict[str, list[str]] = {}
    for name in tools:
        by_handler.setdefault(name.split(".")[-1], []).append(name)

    out: list[DeclarationDivergence] = []
    for role, specs in CAPABILITIES.items():
        for spec in specs:
            groups = _TOOL_GROUPS_BY_ROLE.get(spec.role, ())
            cands = sorted(
                n for n in by_handler.get(spec.handler_name, []) if n.split(".")[0] in groups
            )
            if len(cands) != 1:
                out.append(DeclarationDivergence(
                    "two_layer_name_ambiguous" if cands else "two_layer_name_unmatched",
                    "info", f"{role}.{spec.action}",
                    f"handler_name={spec.handler_name!r} 在角色 {role} 的工具组 "
                    f"{list(groups)} 里对应 {len(cands)} 个工具 {cands} —— "
                    "两层声明**没有比对**（不猜映射；三态里这是 unknown，不是通过）",
                ))
                continue
            tool_name = cands[0]
            tool_ext, tool_eff, precise = _tool_axes(tool_name, tools[tool_name])
            cap_ext, cap_eff = action_axes(spec)
            if spec.side_effect == "network" and tool_ext == "none":
                out.append(DeclarationDivergence(
                    "two_layer_legacy_overclaims", "warning", f"{role}.{spec.action} <-> {tool_name}",
                    "能力层用遗留取值 network（它把出网与起进程压成一个取值），"
                    f"但工具层的两根轴是 external={tool_ext!r} / effect={tool_eff!r} —— "
                    "这个动作**不触到我们不拥有的事**。保守的假话仍然是假话："
                    "审计问哪些动作会出网时，会把一个纯本地的动作列进去",
                ))
                continue

            # 只有精确声明才算"能力层低估了风险轴"：遗留工具的两根轴由翻译表
            # 推出来（`network` 这个取值本身说不出是出网还是起进程），拿它去判能力层
            # 会把"能力层保守高估"也判成 error —— 那一类走
            # `two_layer_legacy_overclaims`（warning）。
            if precise and tool_ext != "none" and cap_ext == "none" and spec.side_effect != "network":
                out.append(DeclarationDivergence(
                    "two_layer_external_divergence", "error", f"{role}.{spec.action} <-> {tool_name}",
                    f"工具层声明 external={tool_ext!r}，能力层声明 {cap_ext!r}"
                    "（能力层**低估**了这根轴，且不是遗留取值的保守高估）—— 两层对同一个动作"
                    "能不能触到我们不拥有的事有两个估值，而能力表是并发与召唤判据的输入",
                ))
            elif tool_ext == "exec" and spec.side_effect == "network":
                # 能力层用遗留取值时它只能说"network"（出网与起进程压在一起）。
                # 工具层说 exec 时两层不矛盾（都说"会触到我们不拥有的事"），
                # 所以不报 error；这里记一条 info 让人看到"这一处的两层精度不同"。
                out.append(DeclarationDivergence(
                    "two_layer_legacy_imprecise", "info", f"{role}.{spec.action} <-> {tool_name}",
                    "工具层声明 external='exec'，能力层只能说到遗留取值 network（它把"
                    "出网与起进程压在一起）—— 两层不矛盾，但精度不同；"
                    "B3 把能力层改成两根轴上的确定值之后这一条会消失",
                ))
            if TOOL_EFFECT.index(tool_eff) > TOOL_EFFECT.index(cap_eff):
                out.append(DeclarationDivergence(
                    "two_layer_effect_divergence", "error", f"{role}.{spec.action} <-> {tool_name}",
                    f"工具层声明 effect={tool_eff!r}，能力层声明 {cap_eff!r}"
                    "（能力层**低估**了这根轴）—— 与写集/并发判据直接相关",
                ))
    return out


def _tool_axes(tool_name: str, declared: tuple[str, str, bool]) -> tuple[str, str, bool]:
    """工具层一个声明在两根轴上的取值，以及"external 是不是精确声明"。

    `declared` 是源码里读出来的 `(side_effect, external, 是否显式声明 external)`：
      - 非遗留工具：`(external, side_effect, 是否为精确声明)` —— 第二根轴是
        人写的声明，第一根轴与 `side_effect` 同值（与 `ToolSpec.effect` 逐字一致）；
      - 遗留工具（`network`）：两根轴都走翻译表（`LEGACY_EFFECTS_BY_TOOL`），
        第三个分量是 `False`（它不是精确声明）。
    """
    from .tools.base import LEGACY_EFFECTS_BY_TOOL, LEGACY_SIDE_EFFECTS

    side_effect, declared_external, explicit = declared
    if side_effect == "network":
        entry = LEGACY_EFFECTS_BY_TOOL.get(tool_name)
        if entry is None:
            entry = LEGACY_SIDE_EFFECTS["network"]
        return (entry[0], entry[1], False)
    return (declared_external, side_effect, explicit)


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
_OBJ = {"type": "object"}


# ---------------------------------------------------------------- 动作表
#
# 每个动作的 handler_name 都能在对应文件里找到 `def <name>(`：
#   agent_a.py:306 run_once / agent_a.py:484 run
#   agent_b.py:229 run_once / 496 reprocess_once / 534 run_reprocess /
#              1035 decide_structural_duplicate / 1155 resolve_structural_duplicate / 1316 run
#   agent_c.py:469 hottest / 677 paths / 1051 cold / 1347 gaps / 1694 neighbors /
#              1813 relations_between / 1887 contradictions / 2014 structural_duplicates /
#              2349 handle
#   agent_d.py:1200 ingest / 1406 ingest_detailed / 1738 trace_question / 1968 trace_l3 /
#              2024 assess / 2133 submit_gaps / 2198 consider / 2262 poll / 2514 adjudicate /
#              2941 research / 3198 run_round / 3341 write_report / 920 probe_c
#   agent_e.py:518 run_experiment / 619 check_formal / 640 evidence_for /
#              646 list_experiments / 652 run_script_experiment
#   agent_f.py:269 create_plan / 423 step / 1055 status / 1094 list_plans
#   agent_g.py:161 compose_claim / 193 register_dependency / 229 build_document /
#              263 render / 278 refresh_markdown / 315 revise
#   agent_h.py:188 review / 220 verify_fixes / 240 list_findings

#: 角色 -> 该角色的动作元组。不在表里的角色没有任何动作（`M` 就是如此：
#: 主控的"动作"是 `summon()` 本身，它由 `Conductor` 实现，不是一个 Agent 方法）。
CAPABILITIES: dict[str, tuple[ActionSpec, ...]] = {
    # ---------------- A：文献检索（唯一带网络副作用的角色）
    "A": (
        ActionSpec(
            "A", "run_once",
            "领取一条待办检索请求并跑完（搜索 + 登记文献 + 下载）",
            _obj({}),
            "ARunResult（含 claimed / outstanding / registered ）",
            side_effect="network", handler_name="run_once",
        ),
        ActionSpec(
            "A", "run",
            "连续领跑到没有可领的请求为止（有界：max_requests）",
            _obj({"max_requests": {**_I, "minimum": 1}}),
            "汇总 dict（processed / registered / …）",
            side_effect="network", handler_name="run",
        ),
    ),
    # ---------------- B：文献整理
    "B": (
        ActionSpec(
            "B", "run_once",
            "抽取一篇待处理文献的概念与关系（含引文逐字回验）",
            _obj({}), "BRunResult",
            side_effect="write_local", handler_name="run_once",
        ),
        ActionSpec(
            "B", "reprocess_once",
            "处理一条定向重抽取请求（I4）",
            _obj({}), "dict（status/result/touched_relation_ids）",
            side_effect="write_local", handler_name="reprocess_once",
        ),
        ActionSpec(
            "B", "run_reprocess",
            "连续处理重抽取请求（有界：max_requests）",
            _obj({"max_requests": {**_I, "minimum": 1}}),
            "汇总 dict", side_effect="write_local", handler_name="run_reprocess",
        ),
        ActionSpec(
            "B", "decide_structural_duplicate",
            "判定一组结构重复候选该不该合并（I5，纯判定，不写库）",
            _obj({"candidate": _OBJ, "concepts": {"type": "array", "items": _OBJ},
                  "relations": {"type": "array", "items": _OBJ}},
                 ("candidate",)),
            "判定 dict（merge / survivor / reason）",
            side_effect="read", handler_name="decide_structural_duplicate",
        ),
        ActionSpec(
            "B", "resolve_structural_duplicate",
            "执行合并判定（写 concepts 的 merged_into + relations 的 status）",
            _obj({"candidate": _OBJ}, ("candidate",)),
            "合并结果 dict", side_effect="write_local", handler_name="resolve_structural_duplicate",
        ),
        ActionSpec(
            "B", "run",
            "连续抽取（有界：max_docs）",
            _obj({"max_docs": {**_I, "minimum": 1}}),
            "汇总 dict", side_effect="write_local", handler_name="run",
        ),
    ),
    # ---------------- C：只读关系分析（唯一"只读但会写自己产出表"的角色）
    "C": (
        ActionSpec(
            "C", "hottest",
            "最热概念榜（度数中心性）",
            _obj({"top_n": {**_I, "minimum": 1}, "request": _S}),
            "AnalysisReport（内存对象；要落库需显式 persist）",
            side_effect="read", handler_name="hottest",
        ),
        ActionSpec(
            "C", "paths",
            "两个概念之间的关系路径",
            _obj({"a": _S, "b": _S, "max_paths": _I, "max_len": _I,
                  "max_overlap": _N, "request": _S}, ("a", "b")),
            "AnalysisReport", side_effect="read", handler_name="paths",
        ),
        ActionSpec(
            "C", "cold",
            "冷门/完全孤立概念",
            _obj({"top_n": {**_I, "minimum": 1}, "request": _S}),
            "AnalysisReport", side_effect="read", handler_name="cold",
        ),
        ActionSpec(
            "C", "gaps",
            "结构缺口候选（可显式选择是否提交检索请求）",
            _obj({"limit": {**_I, "minimum": 1}, "request": _S, "submit_requests": _B}),
            "AnalysisReport", side_effect="read", handler_name="gaps",
        ),
        ActionSpec(
            "C", "neighbors",
            "某概念的邻居（可指定深度）",
            _obj({"concept_id": _S, "depth": {**_I, "minimum": 1}, "max_nodes": _I},
                 ("concept_id",)),
            "dict", side_effect="read", handler_name="neighbors",
        ),
        ActionSpec(
            "C", "relations_between",
            "两个概念之间的全部关系",
            _obj({"a": _S, "b": _S, "include_inactive": _B}, ("a", "b")),
            "dict", side_effect="read", handler_name="relations_between",
        ),
        ActionSpec(
            "C", "contradictions",
            "检测互相矛盾的关系对",
            _obj({"relation_ids": _ARR_S, "limit": _I}),
            "dict", side_effect="read", handler_name="contradictions",
        ),
        ActionSpec(
            "C", "structural_duplicates",
            "结构重复候选（I5 的输入）",
            _obj({"limit": _I}),
            "dict", side_effect="read", handler_name="structural_duplicates",
        ),
        ActionSpec(
            "C", "handle",
            "自然语言需求 -> 分派到上面某个分析器",
            _obj({"request_text": _S}, ("request_text",)),
            "AnalysisReport（kind 可能是 'unknown'，不可落库）",
            side_effect="read", handler_name="handle",
        ),
    ),
    # ---------------- D：研究（状态机）
    "D": (
        ActionSpec(
            "D", "probe_c",
            "按问题向 C 点菜并记录问答（只读 C + 写回本问题行）",
            _obj({"qid": _S, "qrow": _OBJ}, ("qid",)),
            "list[dict]（本轮问到的条目）", side_effect="write_local", handler_name="probe_c",
        ),
        ActionSpec(
            "D", "ingest",
            "把一份 C 报告消化成研究问题",
            _obj({"report": _OBJ, "c_contradictions": _OBJ}, ("report",)),
            "新建的 question_id 列表", side_effect="write_local", handler_name="ingest",
        ),
        ActionSpec(
            "D", "ingest_detailed",
            "同 ingest，但返回逐条明细（含被跳过者及原因）",
            _obj({"report": _OBJ, "c_contradictions": _OBJ}, ("report",)),
            "dict", side_effect="write_local", handler_name="ingest_detailed",
        ),
        ActionSpec(
            "D", "trace_question",
            "把一个研究问题溯源到它依赖的 L1/L2/L3 证据（只读）",
            _obj({"qid": _S}, ("qid",)),
            "dict", side_effect="read", handler_name="trace_question",
        ),
        ActionSpec(
            "D", "trace_l3",
            "L3 下钻：读文献正文里该关系所在段落",
            _obj({"evidence": _OBJ, "lit_ids": _ARR_S}, ("evidence",)),
            "dict", side_effect="read", handler_name="trace_l3",
        ),
        ActionSpec(
            "D", "assess",
            "判定证据是否就绪（决定要不要向 A 要检索）",
            _obj({"qid": _S, "evidence": _OBJ}, ("qid",)),
            "verdict dict", side_effect="read", handler_name="assess",
        ),
        ActionSpec(
            "D", "submit_gaps",
            "把缺口提交为检索请求（受配额与已提交集约束）",
            _obj({"qid": _S}, ("qid",)),
            "新建的 request_id 列表", side_effect="write_local", handler_name="submit_gaps",
        ),
        ActionSpec(
            "D", "consider",
            "重新考虑一个问题（可能提到 researching）",
            _obj({"qid": _S}, ("qid",)),
            "dict", side_effect="write_local", handler_name="consider",
        ),
        ActionSpec(
            "D", "poll",
            "看新到的文献是否答上了在等的问题",
            _obj({"relations": _OBJ}),
            "dict", side_effect="write_local", handler_name="poll",
        ),
        ActionSpec(
            "D", "adjudicate",
            "裁决一条矛盾问题（I2 的闭环）",
            _obj({"qid": _S}, ("qid",)),
            "裁决 dict", side_effect="write_local", handler_name="adjudicate",
        ),
        ActionSpec(
            "D", "research",
            "回答一个证据就绪的问题",
            _obj({"qid": _S}, ("qid",)),
            "dict（含结论与证据代号）", side_effect="write_local", handler_name="research",
        ),
        ActionSpec(
            "D", "run_round",
            "把 ingest ->…-> research 串成一轮（有界：limit）",
            _obj({"report": _OBJ, "submit": _B, "limit": _I}, ("report",)),
            "本轮汇总 dict", side_effect="write_local", handler_name="run_round",
        ),
        ActionSpec(
            "D", "write_report",
            "把研究结果渲染成 markdown 报告",
            _obj({"out_path": _S}),
            "写出文件的路径", side_effect="write_local", handler_name="write_report",
        ),
    ),
    # ---------------- E：实验与形式化验证
    "E": (
        ActionSpec(
            "E", "run_experiment",
            "跑一个实验脚本并登记一行 experiments（证据等级由 schema 机械约束）",
            _obj({"claim": _S, "claim_key": _S, "script_path": _S, "params": _OBJ,
                  "method": {"type": "string", "enum": list(S.EXPERIMENT_METHODS)},
                  "for_question_id": _S, "timeout": _I,
                  # `sleep` 不在真实 `AgentE.run_experiment` 的具名形参里，
                  # 但它在 `**kw` 的接收范围内（agent_e.py:518）。显式登记它有两个理由：
                  # (1) 它是编排层真实需要的东西（"给这一次实验一个更短的时限"）；
                  # (2) 替身/夹具按同一份 schema 声明参数时，"多传一个 sleep 就被拒"
                  #     会逼测试去绕过参数校验 —— 而绕过校验的测试就不再测那条链路了。
                  "sleep": _N},
                 ("claim", "claim_key", "script_path")),
            "dict（experiment_id / result / evidence_kind / …）",
            side_effect="write_local", handler_name="run_experiment",
        ),
        ActionSpec(
            "E", "check_formal",
            "转发到形式化检查器；没有后端时如实回答『没做』",
            _obj({"claim": _S, "script_path": _S, "source": _S, "name": _S,
                  "imports": _ARR_S, "timeout_sec": _N}, ("claim",)),
            "dict（checked=False + reason 表示『没法做』）",
            # 本条此前是 `side_effect="unknown"`（"我读不出它写不写"）。现在读得出来了，
            # 于是必须改成确定值 —— `unknown` 是"我不知道"，留着它就是一句已经不准的话。
            #
            # 判据（逐条从代码读出，不是推测）：
            # (1) 无后端时它只读：`verify_tools.check_formal` 在 `detect_verifier()`
            #     探不到检查器时立刻返回 `no_backend`，不起进程、不写盘（见该函数开头）；
            # (2) 有后端时它起外部进程：桥接层 `formalgw.check_lean` 真的执行
            #     `lean`/`coqc`/`isabelle`（`formalgw._default_run` 是 `subprocess.run`），
            #     而那个子进程继承本进程的环境与工作目录 ⇒ 它的读写面不由本框架决定；
            # (3) 它不写工作区：源码走内存时 `formalgw._materialize` 建的是
            #     `tempfile.TemporaryDirectory`（`workdir=None` ⇒ 临时目录），跑完即删。
            #     所以它不是 `write_local`（工作区字节不变）；代价是它也不是纯内存计算。
            #
            # 因此在"既起子进程、又可能触碰工作区之外"这三条里，唯一不撒谎的值是
            # `network`：它是本词表里"会做本框架管不住的事"的那一档，也正是
            # `DEVELOPMENT.md` P7 对同类形态（`verify.detect_verifier` 的
            # `none` 却 `subprocess.run`）给出的处置 ——"声明成 network（或新增'执行进程'档）"。
            # 没有选 `read`：`read` 的既有含义是"执行本地只读命令、不需要审批"，
            # 而本动作起的是由调用方决定跑什么的检查器，把它说成"只读且免审批"
            # 就是 P7 那句"声明撒谎 ⇒ 权限面在说假话"。工具层（`verify.check_formal`）
            # 自己声明的是 `read`，本条比它更保守，这是刻意的：能力表驱动并发与
            # 召唤判据，宁可在这里多要一次裁决，也不要在那里少要一次。
            #
            # 代价（如实登记）：E 的这个动作从此需要审批、并与其它角色串行。
            # 这条取舍站得住的前提是"起进程取证"本来就该有人签字。
            side_effect="network", handler_name="check_formal",
        ),
        ActionSpec(
            "E", "evidence_for",
            "三态查询：没查 / 查了没有 / 查到了什么",
            _obj({"claim_key": _S, "for_question_id": _S}),
            "dict（必须带 checked 位）", side_effect="read", handler_name="evidence_for",
        ),
        ActionSpec(
            "E", "list_experiments",
            "只读列举实验",
            _obj({"claim_key": _S, "limit": _I}),
            "dict", side_effect="read", handler_name="list_experiments",
        ),
        ActionSpec(
            "E", "run_script_experiment",
            "`run_experiment` 的便捷封装（脚本路径必填）",
            _obj({"claim": _S, "claim_key": _S, "script_path": _S},
                 ("claim", "claim_key", "script_path")),
            "dict", side_effect="write_local", handler_name="run_script_experiment",
        ),
    ),
    # ---------------- F：难题攻坚
    "F": (
        ActionSpec(
            "F", "create_plan",
            "立项（预算不完整即拒绝，不写库）",
            _obj({"problem": _S, "problem_key": _S, "for_question_id": _S,
                  "subgoals": {"type": "array", "items": _OBJ}, "budget": _OBJ,
                  "depth": _I, "parent_plan_id": _S},
                 ("problem", "problem_key")),
            "dict（plan_id）", side_effect="write_local", handler_name="create_plan",
        ),
        ActionSpec(
            "F", "step",
            "推进一轮（唯一会改计划的方法）",
            _obj({"plan_id": _S}, ("plan_id",)),
            "dict（本轮做了什么 / 新状态）", side_effect="write_local", handler_name="step",
        ),
        ActionSpec(
            "F", "status",
            "只读看一个攻坚计划的当前状态",
            _obj({"plan_id": _S}, ("plan_id",)),
            "dict", side_effect="read", handler_name="status",
        ),
        ActionSpec(
            "F", "list_plans",
            "只读列举攻坚计划",
            _obj({"problem_key": _S, "include_terminal": _B}),
            "dict", side_effect="read", handler_name="list_plans",
        ),
    ),
    # ---------------- G：撰写（自己不改稿，只产出稿件与依赖）
    "G": (
        ActionSpec(
            "G", "compose_claim",
            "构造一条合规断言（转发工具层，判据只有一份）",
            _obj({"text": _S, "citations": _ARR_S, "evidence_kind": _S, "section": _S,
                  "is_negative": _B, "negation_kind": _S, "claim_id": _S},
                 ("text", "citations", "evidence_kind", "section")),
            "claim dict", side_effect="none", handler_name="compose_claim",
        ),
        ActionSpec(
            "G", "register_dependency",
            "登记外部依赖（`closed` 时必须核到已入库的来源，FC-23）",
            _obj({"used_by": _S, "kind": _S, "label": _S, "source_lit_id": _S,
                  "source_experiment_id": _S, "page_range": _ARR_S, "quote": _S,
                  "status": {"type": "string", "enum": list(S.DEP_STATUSES)},
                  "status_reason": _S},
                 ("used_by", "kind", "label")),
            "dependency dict", side_effect="write_local", handler_name="register_dependency",
        ),
        ActionSpec(
            "G", "build_document",
            "写一行 documents 并渲染 markdown（无条件渲染）",
            _obj({"kind": {"type": "string", "enum": list(S.DOC_KINDS)}, "title": _S,
                  "claims": {"type": "array", "items": _OBJ},
                  "sections": {"type": "array", "items": _OBJ},
                  "open_problems": _ARR_S, "out_path": _S},
                 ("kind", "title", "claims")),
            "dict（doc_id / markdown_path）", side_effect="write_local", handler_name="build_document",
        ),
        ActionSpec(
            "G", "render",
            "把稿件渲染成 markdown 文本（不写库、不落盘）",
            _obj({"doc": _OBJ, "dependencies": _OBJ}, ("doc",)),
            "markdown 文本", side_effect="read", handler_name="render",
        ),
        ActionSpec(
            "G", "refresh_markdown",
            "按库里当前数据重画稿件 markdown（不改数据行，只改文件）",
            _obj({"doc_id": _S}, ("doc_id",)),
            "文件绝对路径（None = 该稿件没有 markdown_path）",
            side_effect="write_local", handler_name="refresh_markdown",
        ),
        ActionSpec(
            "G", "revise",
            "按 H 的发现修订稿件（review_rounds+1、status=revised）",
            _obj({"doc_id": _S, "fixed_findings": _ARR_S,
                  "new_claims": {"type": "array", "items": _OBJ}, "note": _S},
                 ("doc_id",)),
            "dict", side_effect="write_local", handler_name="revise",
        ),
    ),
    # ---------------- H：审校（只读工具箱 + 一个被钉死的落库代理）
    "H": (
        ActionSpec(
            "H", "review",
            "审一份稿件：落发现 + 更新文档状态",
            _obj({"doc_id": _S, "round_no": _I, "dependencies": _OBJ}, ("doc_id",)),
            "dict（含 checked / verdict / new_findings / error_count）",
            side_effect="write_local", handler_name="review",
        ),
        ActionSpec(
            "H", "verify_fixes",
            "复审：重跑检查判 fixed / 仍 open；到轮数上限则 unresolved_review",
            _obj({"doc_id": _S, "round_no": _I}, ("doc_id", "round_no")),
            "dict", side_effect="write_local", handler_name="verify_fixes",
        ),
        ActionSpec(
            "H", "list_findings",
            "只读列举审校发现",
            _obj({"doc_id": _S, "level": _S, "status": _S, "kind": _S}),
            "dict（必须带 checked 位）", side_effect="read", handler_name="list_findings",
        ),
    ),
}

#: `M` 没有任何动作，但它必须在键集合里（与 `schema.ROLES` 不同的一套名单会漂移）。
#: 为什么空而不是省掉：`CAPABILITIES["M"] == ()` 让"主控不产出领域对象"这条约束
#: 变成可断言的事实，而不是"表里没写所以大概是吧"。
CAPABILITIES[S.CONDUCTOR_ROLE] = ()


# ---------------------------------------------------------------- 写集（表级）
#
# 证据栏里的每一行都是 `grep '\.tx\(|alloc_id\('` 的真实输出。
#    只登记写的表面（`tx("A","B")` ⇒ A 与 B），读的表不进写集。

#: 角色 -> 它可能写的表（表级粒度；见 DESIGN-CONDUCTOR.md §8 待决问题 3）。
#:
#: ## 两条口径说的是两件事（主控裁决 3）
#:
#: - 工具层的 `ToolSpec.side_effect` 描述"默认调用"的副作用
#:   （`agent_c.gaps` 的 `submit_requests` 默认 `False` ⇒ 默认是纯读，
#:   所以 `graph_tools` 里那条声明是对的）；
#: - 能力层的 `WRITE_SETS` 描述"可能写"的表 —— 条件性写也算可能写。
#:
#: 这解释了为什么 `WRITE_SETS["C"]` 必须包含 `search_requests`，而
#: `graph.gaps` 的 `side_effect` 不该被改成 `write_local`：后者会让
#: `ToolRegistry.for_role` 把这个工具从 C 的工具面里过滤掉（只读角色拿不到
#: 写工具）—— 于是"修一个措辞"会砍掉 C 的核心能力。这是"照字面修反而更坏"
#: 的情形，所以修的是登记（`READ_ONLY_WRITE_EXCEPTIONS`），不是声明。
#:
#: ## 关于"第二个只读角色照抄这个模式"的隐患：它已经被结构挡住了
#:
#: 失效点不在 `for_role` 的过滤（那里只按 `side_effect` 过滤工具面），
#: 而在 `READ_ONLY_WRITE_EXCEPTIONS` —— 新角色若照抄 I3 这个模式却不登记，
#: `assert_capabilities()` 会当场抛（"只读角色的写集里出现了未登记的 …"）。
#: 所以这条隐患不需要额外机制：登记表 + 装配期断言就是它的闸门。
WRITE_SETS: dict[str, frozenset[str]] = {
    # agent_a.py:189 search_requests / :360 search_requests+literature / :377 alloc_id("lit")
    "A": frozenset({"search_requests", "literature"}),
    # agent_b.py:165,252,271 literature / :300 literature+concepts+relations
    # / :318 alloc_id("concept") / :383 alloc_id("relation")
    # / :630,939,964 reprocess_requests(+relations) / :1173 concepts+relations
    "B": frozenset({"literature", "concepts", "relations", "reprocess_requests"}),
    # 受控例外：C 是只读角色（`tools.READ_ONLY_ROLES`），但它有两个
    # 写入面，且两者都已在 `READ_ONLY_WRITE_EXCEPTIONS` 里登记：
    #
    # 1. `analysis_reports` —— 它自己的产出登记行
    #    （agent_c.py:319 `with st.tx("analysis_reports")` / :320 `tx.alloc_id("report")`）。
    # 2. `search_requests` —— I3 缺口直连 A（主控裁决为受控例外，不是越界）：
    #    `agent_c.py:2299` `with self.store.tx("search_requests", actor=SUBMITTER, …)`，
    #    由 `_submit_gap_requests()`（agent_c.py:2217）在
    #    `gaps(submit_requests=True)` 时调用，默认关闭。
    #
    # 为什么它不算破坏"C 只读"：
    #   - C 的工具面仍然全量只读 —— `graph.gaps` 刻意不暴露 `submit_requests`
    #     （agent_c.py:2752 的注释原话），所以"推理链不能写"没被破；
    #   - 它写的是过程记录（"请 A 去查一查"），不是知识：
    #     `literature` / `concepts` / `relations` 三张知识表零写入点；
    #   - 把它移到编排层会多一跳、多一份失真，而 I3 的设计意图就是"直连"。
    "C": frozenset({"analysis_reports", "search_requests"}),
    # agent_d.py:1297,1438,2246,2975 research_questions / :1366 alloc_id("question")
    # / :2306 research_questions+relations / :2686 search_requests+research_questions
    # / :2738,2752 alloc_id("question")
    "D": frozenset({"research_questions", "search_requests", "relations"}),
    # agent_e.py:582 experiments / :583 alloc_id("experiment")
    "E": frozenset({"experiments"}),
    # agent_f.py:338 attack_plans / :339 alloc_id("plan") / :852 search_requests
    # / :938 reprocess_requests / :1050 attack_plans
    #
    # F 的写集是"F 自己写的那几张"，不含 A/D/B 在消费请求时写的表。
    # 为什么不做传递闭包：`_deploy_a` 只是提交一条请求（agent_f.py:852），
    # 真正写 literature 的是 A 之后自己去领。把 A/B/D 的写集并进来会让
    # "F 扩张检索面"与"A 检索"永远不能并发 —— 而它们本来就是流水线的两端
    # （`search_requests` 上的 `claimed_by`/`lease_until` 正是为这种并发设计的，
    # interactions.admit_search_request 也按它判配额）。
    # 这是有意的取舍：写集判据回答的是"两个任务会不会同时改同一批行"，
    # 而不是"数据依赖上谁先谁后"（后者是依赖图，本轮明确不做，见设计 §5）。
    "F": frozenset({"attack_plans", "search_requests", "reprocess_requests"}),
    # agent_g.py:337 documents+dependencies+review_findings（revise 一个事务改三张）
    # 间接：tools/doc_tools.py:666 documents / :750 dependencies+literature+experiments
    #      （register_dependency 的 tx 声明了三张，但只写 dependencies；
    #       另两张是它为了核"closed 的来源真的存在"而读的 —— 读不进写集）
    "G": frozenset({"documents", "dependencies", "review_findings"}),
    # 间接：tools/review_tools.py:274 documents（只改 status）/ :296,375 review_findings
    # agent_h.py:150-165 把这两条路钉死成"唯一允许的写面"。
    "H": frozenset({"review_findings", "documents"}),
    # 主控不写任何领域表。它只写 `tasks`（运行记录层）—— 而 `tasks` 是
    # 编排器的台账，不是任何一个角色的产出，所以它不在这里，而在
    # `CONDUCTOR_WRITE_SET`。把它塞进 `WRITE_SETS["M"]` 会掩盖一个事实：
    # 主控的写面是全体共享的（每个召唤都写一行 tasks），因此 M 的召唤
    # 永远与任何角色并发时都可能碰同一张表 —— 见 `write_set_of()`。
    "M": frozenset(),
}

#: 编排器自己写的表。与角色写集分开，因为它的语义不同：
#: 角色的写集是"可能被两个并发任务同时改"的判据；`tasks` 由主控在
#: 每个任务的 start/end 各写一次，且有 `_id_lock` 与事务保护
#: （`task_id` 由 `interactions.next_prefixed_id` 在锁内取号）。
CONDUCTOR_WRITE_SET: frozenset[str] = frozenset({"tasks"})

#: 只读角色的写集例外（必须显式登记，不许靠"看代码猜"）。
#:
#: `tools.READ_ONLY_ROLES` 说的是"它们的工具面里不许出现写工具"。
#: 能力表的写集说的是"它们的 Python 实现可能 `store.tx()` 哪些表"。
#: 两者不是同一件事：一个只读角色的实现当然可以写自己的产出登记行。
#: 显式登记例外的价值在于：新增一个只读角色、或给已有只读角色加一个写入面时，
#: 若它的写集非空而这里没登记，:func:`assert_capabilities` 会当场抛，
#: 逼人写下理由。
#:
#: 这张表不是"删掉那条断言"的替代品：断言仍然在（"只读角色的写集
#: 必须只含已登记的受控例外"）。删掉它，这些例外就再也不会被复核 ——
#: 于是"未登记的写入"会静默通过，而那正是 R003 / FC-03 家族要防的形态。
READ_ONLY_WRITE_EXCEPTIONS: dict[str, frozenset[str]] = {
    # C：两个写入面，都是登记在案的受控例外。
    #   - `analysis_reports`（agent_c.py:319）：它自己的产出登记行 ——
    #     这是"产出"，不是改世界。
    #   - `search_requests`（agent_c.py:2299，I3 缺口直连 A）：主控裁决的受控例外。
    #     判据三条：(1) 工具面仍然全量只读（`graph.gaps` 刻意不暴露该开关）；
    #     (2) 写的是过程记录（请求 A 去查），三张知识表零写入点；
    #     (3) 默认关闭，只能由编排层显式开启。移到编排层会多一跳、多一份失真。
    "C": frozenset({"analysis_reports", "search_requests"}),
    # H：写"审校发现"（review_findings）+ 只改 documents.status（review_tools.py:274/296）。
    # 为什么 H 可以写这两张而不是"违反只读"：H 的工具箱是纯只读的
    # （agent_h.py:154-161 装配期断言），写只发生在一个被钉死的 `writers` 注册表里，
    # 而它的落点只有这两个 —— 于是"发现问题"与"改稿内容"在结构上仍然分得开：
    # H 能改的只有状态与自己的发现，改不了任何一句断言。
    "H": frozenset({"review_findings", "documents"}),
}


# ---------------------------------------------------------------- 允许的召唤边

#: 谁能召唤谁（DESIGN-CONDUCTOR.md §3.1，逐字实现）。
#:
#: 两条刻意设计的边：
#: - `C` 的边是空的：C 一旦能发起动作，它就成了"绕过 B 引文回验"的写入路径。
#:   C 的 `candidate_gaps` / `structural_duplicates` 是产出，由 D 或编排层
#:   决定要不要变成请求。
#: - `H` 只能召唤 `G`：审校者若能让别人改数据，它就同时是发现者与修正者。
#:   这条与"H 的工具面 0 个写工具"（schema.H 的装配期断言）是同一约束的两个面。
ALLOWED_EDGES: dict[str, frozenset[str]] = {
    # ---- `M` 的边是"它能召唤所有角色" ⇒ 必须引用名单，而不是复述名单。
    #
    # 复述的后果是实测过的（linter R005 的判据来源）：`cli.cmd_tools` 曾写死
    # `("A","B","C","D")`，于是命令一边说"工具总数 55"、一边只列 4 个角色 ——
    # 新增 E–H 时没有任何地方报错。枚举全部角色的第二份副本一旦漏掉新角色
    # 就会静默漂移，而"主控能不能召唤新角色"漂移的后果是新角色永远没被召唤过。
    #
    # `S.ROLES` 不含 `S.CONDUCTOR_ROLE`（主控不在自己的召唤名单里，
    # 见 `NON_SUMMONABLE`）—— 这正是我们要的语义，不是遗漏。
    "M": frozenset(S.ROLES),
    "A": frozenset({"B"}),                 # 检索完请 B 整理（A 不自己抽概念）
    "B": frozenset({"C"}),                 # 整理完请 C 看图的形状
    "C": frozenset(),                      # 只读角色，连"请求"都不直接发
    "D": frozenset({"A", "B", "C", "E", "F"}),
    "E": frozenset({"B", "D"}),            # 引文不可核实→B；发现反例→回 D
    "F": frozenset({"A", "B", "C", "D", "E"}),
    "G": frozenset({"D", "E", "F"}),       # 写稿时发现缺证据 → 回去要
    "H": frozenset({"G"}),                 # 审校发现问题 → 请 G 修订
}

#: 没人能召唤主控（没有"召唤 M"这件事）。用一张显式的集合表达，
#: 而不是靠"ALLOWED_EDGES 里没人把 M 写进值里"这个偶然事实 ——
#: 后者会在有人给别的角色加一条 `→ M` 的边时静默失效（那条边会合法化）。
NON_SUMMONABLE: frozenset[str] = frozenset({S.CONDUCTOR_ROLE})


def actions_for(role: str) -> tuple[ActionSpec, ...]:
    """某角色的动作表。未知角色返回空元组（由 policy 判 unknown_role，这里不抛）。"""
    return CAPABILITIES.get(role, ())


def find_action(role: str, action: str) -> ActionSpec | None:
    """查一个动作。找不到返回 `None` —— 三态纪律：调用方必须区分
    "角色不存在"（`role not in CAPABILITIES`）与"角色存在但没这个动作"，
    这两者对应 `unknown_role` / `unknown_action` 两个不同的拒绝理由。"""
    for spec in actions_for(role):
        if spec.action == action:
            return spec
    return None


def write_set_of(role: str) -> frozenset[str]:
    """某角色的写集。

    未知角色返回"整张表"而不是空集：空集意味着"它什么都不写，可以和任何人并发"，
    那是最危险的方向（一个不认识的执行单元被当成了只读）。三态纪律在这里的形态是
    "不知道 ⇒ 保守"，而保守 = 与所有人串行。
    """
    ws = WRITE_SETS.get(role)
    if ws is None:
        return _ALL_TABLES
    if not ws:
        # 没有写集的角色（M）在并发判据上必须与任何角色串行 —— 因为它的
        # 召唤本身会写 tasks，而且它派生的子任务可能写任何东西。
        return _ALL_TABLES
    return ws


_ALL_TABLES: frozenset[str] = frozenset(
    (S.TABLES.keys() if hasattr(S, "TABLES") else ())  # type: ignore[attr-defined]
) | CONDUCTOR_WRITE_SET


def write_sets_intersect(a: str, b: str) -> bool:
    """两个角色的写集是否相交 ⇒ 它们不该并发。"""
    return bool(write_set_of(a) & write_set_of(b))


# ---------------------------------------------------------------- 台账审计（唯一实现）


@dataclass(frozen=True)
class TaskIssue:
    """一条台账问题。带机器可读的码，与 `verify.Issue` 的码逐字一致。"""

    code: str
    level: str  # error | warning
    task_id: str
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "level": self.level,
                "task_id": self.task_id, "message": self.message}


#: 台账审计里用到的码。与 `verify.py:653-697` 里 tasks 那段逐字一致（见
#: `tests/test_conductor.py::test_task_ledger_audit_critical_codes_match_verify_all`），
#: 加四个本模块特有的码（`task_terminal_without_end` / `task_running_without_start`
#: / `task_terminal_rewritten` / `task_refused_without_reason` /
#: `task_refusal_reason_on_non_refusal` / `task_root_depth_not_one` —— 见下面的清单）。
#:
#: ## 为什么这份实现放在这里（而不是各写一份）
#
#: `verify_all`（全库离线审计，CLI 跑）与 `Conductor.verify_tasks`（刚跑完
#: 一次 run 的即时自检）问的是同一个问题："这批 tasks 行自洽吗？"
#: 两处各写一份判据必然漂移，而漂移的形态是"其中一处永远说没问题"——
#: 那是审计最坏的失效方式。
#:
#: 处置（`DEVELOPMENT.md` §10 点名的那条，本轮选方案 (b)，理由见报告）：
#: `Conductor.verify_tasks` 改成调用这一份（`Conductor.task_issues()`），
#: 而 `verify.py` 是禁改区（`AGENTS.md` 的 auth-audit 清单），保留它自己的
#: `Issue` 包装；由一致性测试钉住两者的码集合相等 —— 这正是方案 (b) 的
#: 要求（"不许只写注释说两处应一致"：注释不会变红，测试会）。
TASK_AUDIT_CODES: tuple[str, ...] = (
    "dangling_parent_task",
    "task_depth_discontinuous",
    "task_without_input_key",
    "task_still_running",
    "unknown_artifact_kind",
    "dangling_task_artifact",
    "task_terminal_without_end",
    "task_running_without_start",
    "task_terminal_rewritten",
    "task_refused_without_reason",
    "task_refusal_reason_on_non_refusal",
    "task_root_depth_not_one",
)


def audit_task_ledger(
    tasks: Sequence[Mapping[str, Any]],
    *,
    store: Any,
    in_flight: frozenset[str] | set[str] | None = None,
) -> list[TaskIssue]:
    """审一批 `tasks` 行。这是台账审计的唯一实现（见 `TASK_AUDIT_CODES`）。

    参数
    ----
    in_flight : 本进程确实在跑的任务 id 集合。`None` = 离线审计
        （等价于空集）：此时任何 `running`/`pending` 行都是"没有 end 的 start"，
        因为离线时没有任何 worker 在跑它 —— 这正是 `verify_all` 的语义
        （`verify.py:678` 的原话："verify 是离线跑的，所以任何仍在 running
        的行都是『没有 end 的 start』"）。
    """
    live = frozenset(in_flight or ())
    rows = list(tasks)
    by_id = {str(r.get("task_id")): r for r in rows}
    out: list[TaskIssue] = []

    for r in rows:
        tid = str(r.get("task_id") or "")
        pid = r.get("parent_task_id")
        st = str(r.get("status") or "")

        # ---- I-3：深度链（父必须存在，且子 depth 恒为父+1）
        if pid is not None and str(pid) not in by_id:
            out.append(TaskIssue(
                "dangling_parent_task", "error", tid,
                f"parent_task_id={pid} 不在 tasks 表里 ⇒ 召唤链断了（深度/循环判据都依赖这条链）",
            ))
        elif pid is not None:
            p = by_id[str(pid)]
            if int(r.get("depth") or 0) != int(p.get("depth") or 0) + 1:
                out.append(TaskIssue(
                    "task_depth_discontinuous", "error", tid,
                    f"depth={r.get('depth')} 但父任务 {pid} 的 depth={p.get('depth')} "
                    "⇒ 子任务深度必须恰为父+1（FC-18 ③）",
                ))
        elif int(r.get("depth") or 0) != 1:
            out.append(TaskIssue(
                "task_root_depth_not_one", "warning", tid,
                f"无父任务但 depth={r.get('depth')} ⇒ 主控发起必须 = 1（`schema.Task` 也这么要求）",
            ))

        # ---- 判重键为空 ⇒ 循环检测对它无效
        if not str(r.get("input_key") or "").strip():
            out.append(TaskIssue(
                "task_without_input_key", "warning", tid,
                "input_key 为空 ⇒ 这条召唤无法参与循环检测"
                "（同一 (role, action, input_key) 出现在祖先链上才算循环）",
            ))

        # ---- I-1：start/end 配对（不只是"僵尸 running"）
        if st == "running" and not str(r.get("started_at") or "").strip():
            out.append(TaskIssue("task_running_without_start", "error", tid,
                                 "status=running 但没有 started_at ⇒ 无法回答『跑了多久』"))
        if st in ("done", "cancelled", "failed") and not str(r.get("ended_at") or "").strip():
            out.append(TaskIssue("task_terminal_without_end", "error", tid,
                                 f"status={st} 却没有 ended_at ⇒ 每个 start 必须有且仅有一个 end"))
        if st in ("pending", "running") and str(r.get("ended_at") or "").strip():
            out.append(TaskIssue("task_terminal_rewritten", "error", tid,
                                 f"status={st} 却已有 ended_at ⇒ 终态先到先得，结束时间不许再被改写"))
        if st in ("pending", "running") and tid not in live:
            out.append(TaskIssue(
                "task_still_running", "warning", tid,
                f"status={st}（started_at={r.get('started_at')}）—— "
                "没有任何在跑的 worker 对应它，是一条没有 end 的 start。"
                "可能是崩溃/会话中断残留；本项目不自动续跑（重跑一个可能已经"
                "写了半张表的任务更危险），由人决定是弃掉还是重发",
            ))

        # ---- I-4：拒绝必须带受控理由（且非拒绝不许带理由）
        outcome = r.get("outcome")
        rr = r.get("refusal_reason")
        if outcome == "refused" and rr not in S.REFUSAL_REASONS:
            out.append(TaskIssue(
                "task_refused_without_reason", "error", tid,
                f"outcome=refused 但 refusal_reason={rr!r} 不在受控词表 "
                f"{S.REFUSAL_REASONS} 里 ⇒ 拒绝的理由必须可枚举、可统计",
            ))
        if outcome != "refused" and rr is not None:
            out.append(TaskIssue(
                "task_refusal_reason_on_non_refusal", "error", tid,
                f"outcome={outcome!r} 却带了 refusal_reason={rr!r} ⇒ 看着像『已拒绝』的成功行",
            ))

        # ---- artifacts 形如 "table:id"，必须真的存在
        for a in r.get("artifacts") or []:
            kind, _, ref = str(a).partition(":")
            if kind not in S.TABLES:
                out.append(TaskIssue("unknown_artifact_kind", "warning", tid,
                                     f"artifacts 里的 {a!r} 前缀无法识别（不在 schema.TABLES 里）"))
                continue
            idf = S.TABLES[kind]["id_field"]
            if not any(str(x.get(idf)) == ref for x in store.rows(kind)):
                out.append(TaskIssue("dangling_task_artifact", "error", tid,
                                     f"artifacts 指向不存在的行：{a!r}"))
    return out


# ---------------------------------------------------------------- 装配期自检


def _agent_class(role: str) -> type:
    """按 `schema.ROLES` 的命名约定取角色类。

    为什么用 importlib 而不是在模块顶部 `from .agent_a import AgentA`：
    那会让"读一张声明表"变成"import 全项目"（llm / providers / fetch / extract
    全在 `agent_*` 的 import 图里），于是能力表无法被离线、轻量地读。
    这里的代价是"命名约定"成了一条隐含契约，所以 :func:`assert_capabilities`
    必须真的把类取出来核一遍 —— 命名对不上时它当场炸，而不是留到运行时。
    """
    mod = importlib.import_module(f".agent_{role.lower()}", package=__package__)
    cls = getattr(mod, f"Agent{role}", None)
    if cls is None:
        raise AssertionError(
            f"找不到 agent_{role.lower()}.Agent{role} —— 能力表按 naming convention 取实现类，"
            "约定对不上时这里必须炸（否则主控会以为某个角色『已接线』）"
        )
    return cls


def assert_capabilities() -> None:
    """装配期自检（fail-closed）。任何一条不成立就抛 `AssertionError`。

    七条断言，每一条都对应一次本项目真实踩过的坑族：

    1. 键集合 == `schema.ROLES`。两个模块各写一份角色名单 ⇒
       "schema 认为合法、编排层不认"这种没有任何报错的分裂（FC-03）。
    2. `handler_name` 真的存在且可调用。编造动作名的后果不是报错，而是
       主控一路上把任务派给一个不存在的落点，直到运行时才发现（或者更糟：
       被 `getattr(obj, name, None)` 静默吞掉）。
    3. `(role, action)` 不重复。同一角色两个同名动作 ⇒
       `find_action` 返回哪一个取决于元组顺序 —— 一个"取决于声明顺序"的行为。
    4. 只读角色的写集例外必须显式登记。见 `READ_ONLY_WRITE_EXCEPTIONS`。
    5. 副作用词表只有一份（`set(SIDE_EFFECTS) == set(tools.base.SIDE_EFFECTS)`），
       外加两根轴各自的同一形态断言。两处字面量分叉会让"有副作用"这件事在
       两套口径下不同，而它不会报错。
    6. 写集非空 ⇒ 该角色的效果轴里必须有 `_WRITE_LIKE` 的动作（P-13 §3.4 断言一）。
    7. 两层声明的不一致可判定（见 `declaration_divergences`）；
       默认只报告，`STRICT_DECLARATIONS=True` 时才升级为导入期断言。
    """
    # ---- [1] 角色名单只有一份
    missing = set(S.ROLES) - set(CAPABILITIES)
    extra = set(CAPABILITIES) - set(S.ROLES) - {S.CONDUCTOR_ROLE}
    assert not missing, f"CAPABILITIES 缺少角色 {sorted(missing)}（判据是 schema.ROLES，不许另写名单）"
    assert not extra, f"CAPABILITIES 含 schema.ROLES 之外的角色 {sorted(extra)}"
    assert set(WRITE_SETS) == set(S.ROLES) | {S.CONDUCTOR_ROLE}, (
        f"WRITE_SETS 的键必须与 schema.ROLES + CONDUCTOR_ROLE 一致，"
        f"多 {sorted(set(WRITE_SETS) - set(S.ROLES) - {S.CONDUCTOR_ROLE})}，"
        f"少 {sorted(set(S.ROLES) | {S.CONDUCTOR_ROLE} - set(WRITE_SETS))}"
    )
    assert set(ALLOWED_EDGES) >= set(S.ROLES), f"ALLOWED_EDGES 缺少角色 {sorted(set(S.ROLES) - set(ALLOWED_EDGES))}"
    # 边表里的目标也必须是合法角色名：写成 "agent-A" 这类拼法会让
    # 每一次 `M → A` 都被判 forbidden_edge，而"策略拒绝了"看起来像正常工作。
    for frm, tos in ALLOWED_EDGES.items():
        bad_targets = sorted(set(tos) - set(S.ROLES))
        assert not bad_targets, f"ALLOWED_EDGES[{frm!r}] 含非角色目标 {bad_targets}（拼法必须与 schema.ROLES 一致）"
        assert not (set(tos) & NON_SUMMONABLE), (
            f"ALLOWED_EDGES[{frm!r}] 允许召唤主控 {sorted(set(tos) & NON_SUMMONABLE)} —— "
            "没有『召唤主控』这件事，它只能由用户/调用方驱动"
        )

    # ---- [2] handler 真的存在
    for role in S.ROLES:
        cls = _agent_class(role)
        for spec in CAPABILITIES[role]:
            assert spec.role == role, f"{spec.action} 声明在 {role} 名下，但 ActionSpec.role={spec.role!r}"
            fn = getattr(cls, spec.handler_name, None)
            assert callable(fn), (
                f"Agent{role} 上没有可调用的 {spec.handler_name!r}（动作 {spec.action}）—— "
                "能力表里的动作必须是真实代码里存在的公开方法，不许编造"
            )

    # ---- [3] 同角色同动作不许重复
    for role, specs in CAPABILITIES.items():
        seen: set[str] = set()
        for spec in specs:
            assert spec.action not in seen, f"{role} 声明了重复动作 {spec.action!r}"
            seen.add(spec.action)

    # ---- [4] 只读角色的写集例外必须显式登记
    from .tools import READ_ONLY_ROLES  # 局部导入：避免能力表被工具层的 import 图拖慢

    for role in READ_ONLY_ROLES:
        ws = WRITE_SETS.get(role, frozenset())
        allowed = READ_ONLY_WRITE_EXCEPTIONS.get(role, frozenset())
        bad = set(ws) - set(allowed)
        assert not bad, (
            f"只读角色 {role} 的写集里出现了未登记的 {sorted(bad)}。"
            f"只读角色的工具面里没有写工具（tools.READ_ONLY_ROLES={READ_ONLY_ROLES}），"
            "所以它的写集必须为空，或只有它自己的产出表 —— 后者必须在 "
            "READ_ONLY_WRITE_EXCEPTIONS 里写下理由"
        )

    # ---- [5] 副作用词表只有一份
    from .tools.base import EFFECT as TOOL_EFFECT
    from .tools.base import EXTERNAL as TOOL_EXTERNAL
    from .tools.base import SIDE_EFFECTS as TOOL_SIDE_EFFECTS

    assert set(SIDE_EFFECTS) == set(TOOL_SIDE_EFFECTS), (
        f"capabilities.SIDE_EFFECTS={SIDE_EFFECTS} 与 tools.base.SIDE_EFFECTS="
        f"{TOOL_SIDE_EFFECTS} 不一致 —— 副作用是跨模块约定，两套词表必然漂移"
    )

    # ---- [5b] 两根轴的词表各只有一份（形态照抄第 5 条，不发明第二套机制）
    assert set(EFFECT) == set(TOOL_EFFECT), (
        f"capabilities.EFFECT={EFFECT} 与 tools.base.EFFECT={TOOL_EFFECT} 不一致 —— "
        "轴上的取值是跨模块字符串约定（FC-03），分叉的症状不是崩溃而是"
        "'两套说法都自洽'"
    )
    assert set(EXTERNAL) == set(TOOL_EXTERNAL), (
        f"capabilities.EXTERNAL={EXTERNAL} 与 tools.base.EXTERNAL={TOOL_EXTERNAL} 不一致 —— "
        "同上；这一根轴决定'谁要进沙箱、谁要人工签字'"
    )

    # ---- [6] 写集与效果轴必须一致（P-13 §3.4 断言一）
    #
    # `WRITE_SETS[role] != ∅` ⇒ 该角色至少有一个"会改我们拥有的东西"的动作。
    # 为什么必须有这一条：写集是并发判据（两张写集相交 ⇒ 串行），
    # 而效果轴是审批与沙箱的输入。两者分叉的形态是"在轨道上会写，在声明上说只读" ——
    # 谁都不会报错，直到两个任务真的并发了。
    #
    # 判据里必须先减掉 `READ_ONLY_WRITE_EXCEPTIONS`。只读角色 C 的写集
    # （`analysis_reports` + I3 直连的 `search_requests`）是已登记的受控例外，
    # 而它的动作轴应当是 `read`（第 4 条与 `WRITE_SETS["C"]` 的长注释一起
    # 解释了为什么这两件事可以同时成立）。不减掉例外，这条断言会把一个
    # 已经写下理由的设计判成违规 —— 而"照字面修反而更坏"。
    for role, ws in WRITE_SETS.items():
        unexplained = set(ws) - set(READ_ONLY_WRITE_EXCEPTIONS.get(role, frozenset()))
        if not unexplained:
            continue
        axes = [effect_axis_of(s) for s in actions_for(role)]
        assert any(a in _WRITE_LIKE for a in axes), (
            f"WRITE_SETS[{role!r}]={sorted(unexplained)} 非空（已减掉已登记的只读例外），"
            f"但该角色没有任何效果轴为 {_WRITE_LIKE} 的动作（实测轴值：{sorted(set(axes)) or '（无动作）'}）"
            "—— 写集说它会写表，效果轴说它不写：这两个判据不许分叉"
        )

    # ---- [7] 两层声明的不一致必须可判定
    #
    # P-13 §10 第 3 条实测：`verify.check_formal` 工具层 `read` / 能力层 `network`，
    # 而没有任何机器判据看见过。本轮的处置是"先让它可见"（:func:`declaration_divergences`），
    # 不是"导入期炸" —— 真实树上现在就有两条，做成 AssertionError 会让
    # `import agentflow.capabilities` 永久失败，把既有第 1–5 条断言一起废掉。
    # 升级为 error 的开关在这里：B3 把两处声明同批改完之后把它翻成 True。
    if STRICT_DECLARATIONS:
        hard = [d for d in declaration_divergences() if d.level == "error"]
        assert not hard, (
            "两层声明不一致（能力层低估了风险轴）："
            + "；".join(f"{d.where}: {d.message}" for d in hard)
        )


#: 两层声明不一致要不要在导入期炸。默认 False，理由见 :func:`assert_capabilities`
#: 第 7 条：真实树上现有的不一致（`E.check_formal` 与 `H.review` 一类）是
#: B3 的迁移对象，现在炸等于把整仓的导入期断言一次性废掉。
STRICT_DECLARATIONS: bool = False


#: 导入期自检。为什么放在导入期：能力表是策略判据的输入（写集相交 ⇒ 串行、
#: 边表 ⇒ 越权拒绝）。它一旦与实现漂移，症状不是崩溃而是静默的越权/并发损坏。
#: 让它 import 时就炸，是唯一"不可能忘记跑"的校验点。
#:
#: ## 代价与"为什么仍然值得"（主控裁决 2）
#:
#: 代价是实测的：`import agentflow.capabilities` 会拉起全部 `agent_*` 与它们的
#: import 图（约 167ms、约 159 个模块）。这与 `agentflow/__init__.py` 刻意不
#: import 子模块的取向有张力，但保留，理由是那句话本身：
#: "一个没人运行的校验"与"没有校验"在结果上不可区分 —— 而能力表漂移的
#: 症状是静默的越权/并发损坏，不是崩溃。167ms 换"不可能忘记跑"是划算的。
#:
#: 但不许只靠导入期：`agentflow/__init__.py` 不 import 子模块，所以
#: 只有"真的 import 到本模块"的人才会触发它。待办（给主控）：
#: `scripts/release_check.py` 里应显式跑一次 `import agentflow.capabilities`
#: 并断言退出码 0，让这个自检有一个明确的触发者，而不是靠"总会有人 import 到"。
#: （`release_check.py` 是禁改区，本模块不自行改动它。）
assert_capabilities()
