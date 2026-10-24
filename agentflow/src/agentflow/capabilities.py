"""角色能力表 + 写集 + 允许的召唤边（主控编队的声明层）。
## 这一层解决什么问题

主控要"按需召唤 A–H"，三个问题都不许靠猜：① 这个角色有哪些动作 —— `CAPABILITIES`；
② 跑这个动作会写哪几张表（于是谁不能和谁并发）—— `WRITE_SETS`；③ 谁允许召唤谁 ——
`ALLOWED_EDGES`。

## 三条纪律（每一条都是"不许另写第二份判据"的形态）

- 动作来自真实代码：`ActionSpec.handler_name` 必须是 `agent_x.py` 里真的存在的公开方法 ——
  不是注释约定，而是 :func:`assert_capabilities` 在导入期用 `importlib` 取类、逐个
  `callable(getattr(cls, name))` 核过的；编造一个不存在的动作名会让模块根本 import 不进来。
- 写集来自 `store.tx(...)` / `alloc_id(...)`：每一行都带符号名证据（`R4-6`：行号易失）。它是
  并发安全判据（两张写集相交 ⇒ 串行），写错一个表名不是报错而是两个任务真的同时改同一批行
  ⇒ 静默的数据损坏。已知的一处间接写（`F → A` / `F → D` 的写入发生在 A/D 自己的 `tx(...)` 里，
  `AgentF._deploy_a` / `AgentF.step` 只提交请求行）本轮刻意不并入 F 的写集，理由见
  `WRITE_SETS["F"]` 的注释 —— 有意的取舍，不是遗漏。
- 只读角色的写集必须为空（或只有它自己的产出表）：见 `READ_ONLY_WRITE_EXCEPTIONS`，与
  `tools.READ_ONLY_ROLES` 交叉断言 —— 工具面没有写工具而能力表有写集 ⇒ 当场炸。
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import schema as S
from . import specs as _specs

#: 声明类型与声明词表住在叶子层 `agentspec`（M3：动作表的真身搬进 `specs/`，
#: 本模块从它派生；搬移理由见 `agentspec.py` 末尾那一段）。
from .agentspec import (  # noqa: F401  （四个词表按原公开名再导出）
    EFFECT,
    EXTERNAL,
    SIDE_EFFECTS,
    UNKNOWN_SIDE_EFFECT,
    ActionSpec,
)



#: 第一根轴的两个名字（`SIDE_EFFECTS` 与 `EFFECT`）之间也要有本文件内的判据，
#: 不能只靠对 `tools.base` 的传递性（`axes-2`，实测）。
#:
#: 为什么必须有这一条：两条既有断言是
#: `set(SIDE_EFFECTS) == set(tools.base.SIDE_EFFECTS)`（第 5 条）与
#: `set(EFFECT) == set(tools.base.EFFECT)`（第 5b 条）。它们是分别对齐的，
#: 于是"把 `EFFECT` 与 `tools.base.EFFECT` 一起加一个取值、而两份 `SIDE_EFFECTS`
#: 都不动"这种改法能让那两条断言全过 —— 而第一根轴在本层就有了两句不一样的话：
#: `ToolSpec.__post_init__` 挡非法取值用的是 `SIDE_EFFECTS`，
#: `_divergences` 比危险度次序用的是 `EFFECT`。分叉本身不会红，这正是要挡的形态。
assert set(EFFECT) == set(SIDE_EFFECTS), (
    f"capabilities.EFFECT={EFFECT} 与 capabilities.SIDE_EFFECTS={SIDE_EFFECTS} "
    "不再是同一份取值 —— 第一根轴的两个名字在这一层分叉了。"
    "第 5 条与第 5b 条只把两者分别与 tools.base 对齐，传递性挡不住这种分叉："
    "构造期校验用 SIDE_EFFECTS、轴比对用 EFFECT，新增取值必须同时改两处"
)



#: 保守判据：哪些副作用等级算"会碰数据"。
#: `unknown` 也算 —— 宁可少并发，不可让一个不确定的东西和别的任务并行改数据。
#: `network` 曾在表里（它把出网与起进程压成一档）；B3 收官删掉那个取值之后，
#: 它在这里也没有对象了。
_WRITE_LIKE = ("write_local", UNKNOWN_SIDE_EFFECT)




def action_axes(spec: ActionSpec) -> tuple[str, str]:
    """一个动作在两根轴上的取值，语义是 `(external, effect)`。

    两个分支，判据是"这根轴有没有被人声明过"（三态：声明了/没声明）：
    - `declared_external is not None` ⇒ `(spec.external, spec.side_effect)`；两根轴各说各的真话
      （`E.run_experiment` 是 `("exec", "write_local")`：跑调用方给的脚本，又写 experiments 表）；
    - 否则 ⇒ `("none", spec.side_effect)`：效果轴照实取 `side_effect`，外部轴取 `none` ——
      与 `ToolSpec.declared_external` 的默认值同一口径（"我没说"不等于"我会出网"）。
    B3 收官前这里还有两个遗留分支（`network` 走 `LEGACY_NETWORK_AXES`、以及"声明了 external 时
    效果一栏仍按 `WRITE_SETS` 的事实填 `write_local`"）。它们随 `network` 那个取值一起删掉了：
    现在没有哪个取值需要"按事实另填一次效果"，两根轴上的值都能从声明直接读出来。
    """
    if spec.external is not None:
        return (spec.external, spec.side_effect)
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

    ## "对上了"的判据是装配面，不是声明面（2026-10-26，第 ④ 条根因）

    `_tool_side_effects()` 读的是**声明**：`tools._MODULES` 加上
    `_TOOL_MODULE_EXTRAS` 里逐条登记的那几件 —— 而后者登记的理由是
    "两层参数对账要看得见这条工具"（见那张表的理由串），不是"它是工具面上的一件"。
    于是 `D.register_conjecture` 曾经被算成"已对上"：名字对上了
    `conjecture.register_conjecture` 的声明，而 `build_registry` 根本装配不到那个模块
    ⇒ 工具面上没有它 ⇒ `agent_loop._own_actions_to_expose` 也不注入 `own.register_conjecture`
    ⇒ 模型按手册喊短名 `register_conjecture`，只拿到"并列候选 0 个"。
    现在对得上 = "那个组由 `tools._MODULES` 里的模块产出"，也就是工具面上真有这件工具
    （过滤发生在 :func:`_candidates`，`_matching_tool_name` 与它共用同一条判据）。
    "读到了、但不注册"这件事仍然是可见的，落点是
    `param_type_coverage()['tools_read_but_not_registered']` —— 两件事分开说，谁也不冒充谁。
    """
    tools = _tool_side_effects()
    unmapped: list[tuple[str, str]] = []
    for role, specs in CAPABILITIES.items():
        for spec in specs:
            if _matching_tool_name(spec, tools) is None:
                unmapped.append((role, spec.action))
    return sorted(unmapped)


#: 角色 -> 它可能借由工具层落地的工具组。为什么必须显式写下来：动作与工具的对应只有一条结构性
#: 约定（工具的最后一个名字段 == 动作的 `handler_name`），而它在短名上必然撞车 —— 实测 `run` 在
#: 能力层有两个动作（`A.run` / `B.run`），工具层有一个工具（`ocr.run`）；不加这张表两条动作会被
#: 同一个工具"对上"，于是报告里出现一条纯属拼写巧合的"不一致"（最反对的那种假报警）。
#: 每组都写理由是因为"这个角色会不会经由这一组工具落地"是设计判断、推不出来：`B`/`ocr`（`AgentB.run`
#: 调 OCR 读 PDF，声明 `network`）· `A`/`D` = `search`/`research` · `E`/`F` = `verify`/`attack` ·
#: `G`/`H` = `doc`/`review` · 通用组（`fs`/`table`/`graph`/`trace`）任何角色都可能用到、只在唯一命中
#: 时才算对上。表里没有的角色组合 ⇒ 报"两层声明没有比对"（info，三态里的 unknown），不猜映射。
_TOOL_GROUPS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "A": ("search", "table", "fs", "research", "trace", "graph"),
    "B": ("ocr", "table", "fs", "trace", "graph"),
    "C": ("graph", "table", "fs", "trace"),
    "D": ("research", "search", "trace", "graph", "table", "fs", "conjecture"),
    "E": ("verify", "table", "fs"),
    "F": ("attack", "table", "fs"),
    "G": ("doc", "table", "fs"),
    "H": ("review", "verify", "doc", "table", "fs"),
    # V 的落地工具只有一组：`verify_tools` 里那三件只读的验证台账工具
    # （`verify.verify_proof` / `verify.list_verifications` / `verify.read_proof`）。
    # 刻意不照抄 E 的 ("verify","table","fs")：这张表的用途是"名字消歧"，
    # 不是授权矩阵 —— 多写组会让同名工具更容易撞上第二个候选，
    # 而 `ambiguous` 必须为空（`assert_capabilities` 第 [7b] 条）。
    "V": ("verify",),
    # 主控拿的是编排面工具（派活 / 台账 / 停止 / 状态 / 角色规格）：它不产出领域对象，
    # 所以这里只有 conductor 一组，且 CAPABILITIES["M"] 一个字都没变。
    "M": ("conductor",),
    # L（Lean 形式化者，2026-10-22 新设）：它自己的两件工具在 `formal` 组
    # （`tools/formal_tools.py`），加上任何角色都可能用到的 `fs`（读写 .lean）。
    # 刻意不写 "verify"：L 不到 `verify.*` 的工具面上去 —— 它由 Agent 层直接调
    # `verify.check_formal` 那个函数（与 `AgentE.check_formal` 同一条路），
    # 这样"自检闸 + 三态形状"这两处差别才是看得见的。
    "L": ("formal", "fs"),
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
    """:func:`matching_tool_name` 的纯函数形态（工具表由调用方给，避免重复解析源码）。

    与 :func:`_candidates` 共用同一份实现（`:func:`_candidates_impl`），但刻意不转调
    `_candidates` 这个名字：后者是负控打桩的接缝（`tests/test_capabilities_two_layer.py`
    把 `_candidates` 打桩成"两个候选 / 一个都没有"来证明对账面会红），而这一条查的是
    "某个动作能不能唯一对上一个工具"，打桩它会让只读例外表（`READONLY_CALL_EXCEPTIONS`）
    的解析跟着变 —— 那会把一条负控变成两条判据互相干扰的假证明。
    """
    hits = _candidates_impl(spec, tools)
    return hits[0] if len(hits) == 1 else None


def _tool_side_effects() -> dict[str, tuple[str, str, bool]]:
    """全仓工具名 -> `(side_effect, external, 是否显式写了 external 声明)`。

    不装配工具层，只读源码里的声明。第三个分量是"这条工具的 external 是人写下来的，还是落到了
    默认值 `none`"—— 两者的判据强度不同：显式声明与能力层矛盾是 error（谁在低估风险），落到默认
    值只是没说的默认，不能拿它去判"能力层低估"。
    ## 为什么读源码而不是装配一次工具层：声明有两种落点，实测都取不到对象：
    1. `reset()/register()` 函数体里现造的 `ToolSpec(...)`（`search_tools` / `ocr_tools` /
       `verify_tools` / `attack_tools` / `doc_tools` / `review_tools`）—— 需要 `store` 与工作区，
       装配一次会在导入期碰文件系统；
    2. 模块级 `@tool(...)` 标记的函数（`fs_tools` / `table_tools` / `research_tools` / `graph_tools` /
       `trace_tools`）。两者都写在源码里、都是字面量，所以用 `ast` 读。
    ## 这是"核对"不是"推断"：本函数读人写下的 `side_effect` 字面量与能力层比，不从 handler 函数体
    推断副作用 —— 那正是 N-4 否决的做法（P-13 §9①：22/55 取不到 handler 源码、9 个转发型假阳性）。
    读不到源码文件（例如装了 wheel）返回空表，于是 :func:`declaration_divergences` 把每条动作报成
    "没有比对"（unknown），不会折叠成"没问题"。
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
    - `ToolSpec(name="...", side_effect="...", declared_external="...")`（关键字或前两个位置参数）；
    - `@tool("...", ..., side_effect="...", external="...")` 装饰器 —— 装饰器的关键字参数就叫
      `external`（`ToolSpec` 的字段叫 `declared_external`，属性才叫 `external`）。
    两种写法都要认，而且必须认那两个真实的名字：只认 `external=` 时，真实树上的
    `ToolSpec(..., declared_external="exec")` 会被读成默认的 `none`，于是 `declaration_divergences`
    会对"两层其实说同一句话"的动作报 `two_layer_external_imprecise`（`verify.run_experiment` 就是
    这一形态）—— 由读错字段名造出来的假报警比漏报更坏：它会训练人忽略告警（P15）。
    只认字面量：名字或取值是变量/表达式时跳过（记不进表），那条动作在报告里是"没有比对"而非"通过"。
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
            elif kw.arg in ("declared_external", "external"):
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


#: 读声明时要多读的模块（`tools._MODULES` 之外的那一个，逐条写理由）。
#:
#: ## 为什么这张表必须存在（审计 D-6 的治本）
#: 本文件原来手抄了一份 14 项模块名单，并写着「与 `tools._MODULES` 同源」—— 那是一句假话：
#: 实测差三个模块（少 `text_tools` / `manuscript_tools`、多 `conjecture_tools`），于是
#: `param_type_coverage()['tools_read']` 只肯说「读到 77 个工具的 schema」，而工具层有 95 件，
#: 读数说不出这 18 件的差从哪来。同一件事（工具模块有哪些）只允许有一个真身：
#: `tools._MODULES`（装配期真正注册工具的那张表）。这里只登记「为什么还要多读一个模块」。
_TOOL_MODULE_EXTRAS: dict[str, str] = {
    "conjecture_tools": (
        "`D.register_conjecture` 的落地工具（`conjecture.register_conjecture`）住在这个文件里，"
        "而它不在 `tools._MODULES` 里 —— `build_registry` 不装配它（D 走 `agent_d._support` "
        "里的直接 import）。两层参数对账要看得见这条工具，所以显式多读一个模块；"
        "但「读进来」不等于「它是工具面的一件」，所以读数把它单列成 "
        "`tools_read_but_not_registered`（读到了、不注册 ≠ 注册了）"
    ),
}


def _tool_modules() -> tuple[str, ...]:
    """读声明用的模块名单 = `tools._MODULES`（真身）＋ 显式登记的额外模块。"""
    from .tools import _MODULES

    return (*_MODULES, *_TOOL_MODULE_EXTRAS)


#: 工具模块名单（只用于「读声明」）。派生自 :func:`_tool_modules`，不是第二份名单。
_TOOL_MODULES: tuple[str, ...] = _tool_modules()
assert len(set(_TOOL_MODULES)) == len(_TOOL_MODULES), (
    f"工具模块名单里出现了重复项：{_TOOL_MODULES} —— `_TOOL_MODULE_EXTRAS` 与 "
    "`tools._MODULES` 撞了，那会让读数里的工具计数重复（计数重复比没有计数更坏：它会看起来对得上）"
)


def _assembled_groups() -> frozenset[str]:
    """工具面上真的装配过的组前缀（`tools._MODULES` 派生的那一份，2026-10-26 加）。

    为什么要与 `_TOOL_MODULES` 分开：「读声明」与「装配」是两件事。`_TOOL_MODULES` 多读一个
    模块，是为了让两层参数对账看得见 `conjecture.register_conjecture` 的约束面；
    而"这件工具在不在工具面上"只能看 `tools._MODULES` —— 装配期真正注册工具的那张表。
    把两者混成一个集合的后果是一次静默的错判：`D.register_conjecture` 被算成"已对上"，
    于是 `agent_loop` 不注入 `own.register_conjecture`，模型在模型驱动模式下喊短名时
    只拿到"并列候选 0 个"。判据 `tests/test_d_can_reach_register_conjecture.py`。
    """
    from .tools import _TOOL_GROUP_PREFIXES

    return frozenset(_TOOL_GROUP_PREFIXES)


#: 装配面上的组前缀（`tools._MODULES` 派生）。`_candidates` 用它把"只读到、不装配"的
#: 那几件工具挡在"对得上"之外 —— 三处读数（`unmapped_actions` / `two_layer_reconciliation`
#: / `declaration_divergences`）共用 `_candidates`，所以这条过滤只有一处落点。
_ASSEMBLED_GROUPS: frozenset[str] = _assembled_groups()


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

    ## 为什么这条判据必须存在：`docs/PROPOSALS.md` 的 P-13 §10 第 3 条实测：`verify.check_formal`
    在工具层声明 `read`、在能力层声明 `network`，而没有任何机器判据看见过它（R006 只看工具层且是
    文件级共现）。本轮（B1/B2）把它变成可判定的：两层各按自己那根轴估值，名字按唯一性约定对上，
    对不上就报。B3 收官已把那一处收敛掉（两层现在都说 `read` + `exec`），于是真实树上只剩
    "没有比对"这类 info；判据本身仍可红（见 `tests/test_policy.py` 里那两条自检）。
    ## 比对口径（三条，逐条都有反例在真实树上）：两层用途不同，不是逐字相等才叫一致
    （`WRITE_SETS` 的长注释登记过：工具层描述"默认调用"的副作用，能力层描述"可能写"的表）：
    1. 能力层在某一根轴上更保守 ⇒ 不报（刻意如此：能力表驱动并发与召唤判据，宁可多要一次裁决）。
    2. 能力层在某一根轴上更小 ⇒ 报 error：工具说 `exec`/`egress`、能力说 `none`，或工具说写、能力
       说读 —— 那是"能力表以为它更安全"，而低估风险比高估贵得多。
    3. 两根轴都非 `none` 但精度不同 ⇒ 报 warning（`two_layer_external_imprecise`）：工具说 `egress`、
       能力层说 `exec`，两层都承认"触到了我们不拥有的东西"（不报 error），但"出网"与"起进程"是两根
       不同的风险面，所以也不许静默 —— 它必须可见。
    ## 为什么只报告、不在导入期断言：error 级在导入期断言（`assert_capabilities` 第 [7] 条），warning/info 只报告 —— 把 warning 也做成 `AssertionError` 会让 `import agentflow.capabilities` 因为一条"精度不同"而永久失败，整仓导入期断言（包括第 1–5 条）全部失效，那不是更严而是砸门。要不要付这个代价由 `STRICT_DECLARATIONS` 决定：默认 False，置 True 时 warning 也进导入期断言（`R4-AN-3`：这个开关此前是一句 `pass`，即空转；现在它在 [7] 里真的读 warning）。
    """
    from .tools.base import EFFECT as TOOL_EFFECT

    return _divergences(CAPABILITIES, _tool_side_effects(), TOOL_EFFECT)


def two_layer_reconciliation() -> dict:
    """两层声明的对账面：每个动作落到三格里恰好一格（分区，不是"有没有分歧"）。

    ## 为什么这个函数必须存在（它补的是一条真的缝）：`declaration_divergences` 答"两层在哪里不一致"，
    而"对账面有没有真的在做"有三个不同答案，必须分开数：`compared`（动作与工具唯一对上了）、
    `unmatched`（`handler_name` 在角色工具组里对应 0 个 ⇒ 没比成，unknown）、`ambiguous`（对应 ≥2 个 ⇒ 按唯一性约定拒绝猜，unknown）。
    实测（2026-10-26 现算）：64 个动作 = 24 compared + 40 unmatched + 0 ambiguous
    （2026-10-15 是 62 个动作 = 23 compared + 39 unmatched + 0 ambiguous；`compared` 从 21 涨到 22 是加了 `A.walk_citations` —— 工具名最后一段正是 `walk_citations`，与 `handler_name` 逐字相同；对照 `search_literature` 落不进（工具名最后一段是 `literature`）⇒ 进 `unmatched`，所以"两层形状一致"对那一对没有判据看着，见 `specs/a.py` 里那段注释）。
    2026-10-26：`D.register_conjecture` 从 compared 挪进 unmatched —— 它对应的
    `conjecture.register_conjecture` 只被"读到"、没有被 `build_registry` 装配（见 `_ASSEMBLED_GROUPS`），
    所以"两层有一个唯一对应的工具"这句话对它不成立（+1 unmatched、−1 compared、动作总数不变）。
    此前各次（数字逐次可复算，每次只增不改）：（2026-10-14）60 = 21 + 39 + 0（退场前：`paper_package` 那一条本来也进 `unmatched`）；（2026-10-06）59 = 21 + 38 + 0（加角色 V 的三条动作 `verify.verify_proof` / `verify.list_verifications` / `verify.read_proof` 全部对上，`_TOOL_GROUPS_BY_ROLE["V"]` 只登记 `verify` 一组）；（2026-10-03）55 = 18 + 37 + 0（加 `G.paper_package`，2026-10-13 退场）；（2026-10-02）53 = 18 + 35 + 0（加 `A.ingest_local` 与 `B.register_statement`）；（2026-09-30）51 = 17 + 34 + 0（加 `A.search_literature`）。
    `C.proof_chain` 与 C 的其余八条同族：`handler_name` 在 `_TOOL_GROUPS_BY_ROLE["C"]` 里对不上工具组 ⇒ 进 `unmatched`，并逐条登记在 `_KNOWN_UNMATCHED_ACTIONS`。
    `assert_capabilities()` 第 [7] 条原来只钉 `unmatched`（`_KNOWN_UNMATCHED_ACTIONS`）—— 于是 `ambiguous` 那一格可以静默长大：它今天恰好是 0，所以那条缝从没被看见。本函数就是给分区断言用的输入，它自己不做判断（判断在第 [7] 条）。
    注意：刻意不把"一致"塞进 `declaration_divergences()`：那个函数的名字就是"分歧"，往里塞一致项会造出"名字与语义不符"的新缺陷（而它正是本仓库最忌讳的那类：判据看起来还在工作，读的人已经理解错了）。
    """
    return _reconcile(CAPABILITIES, _tool_side_effects())


def declaration_divergences_for(
    capabilities: Mapping[str, tuple[ActionSpec, ...]],
    tools: Mapping[str, tuple[str, str, bool]],
) -> list[DeclarationDivergence]:
    """:func:`declaration_divergences` 的纯函数形态（两张表都由调用方给）。

    为什么必须能单独喂表：真实树现在"两层一致"，于是判据的正确性只能靠
    合成的两层来证（`tests/test_policy.py` 里那几条把两层各改错的自检）。
    只留一个读全局的实现，那些用例就只能去 monkeypatch 模块级函数 ——
    而 monkeypatch 一个函数名不等于被测判据接在了正确的位置上。
    """
    from .tools.base import EFFECT as TOOL_EFFECT

    return _divergences(capabilities, tools, TOOL_EFFECT)


def _candidates(
    spec: ActionSpec, tools: Mapping[str, tuple[str, str, bool]]
) -> list[str]:
    """一个动作在它的角色工具组里能对上的工具名（负控打桩的接缝；实现见 `_candidates_impl`）。

    为什么留这一层同名包装：本仓的负控靠"把这一格打桩掉、看判据会不会红"来证明判据真的
    在比对（`tests/test_capabilities_two_layer.py` 的两条负控）。实现放在
    `_candidates_impl` 里，于是"打桩 `_candidates`"只影响对账面，不波及
    `_matching_tool_name`（后者查的是同一件事的另一个消费者）。
    """
    return _candidates_impl(spec, tools)


def _candidates_impl(
    spec: ActionSpec, tools: Mapping[str, tuple[str, str, bool]]
) -> list[str]:
    """`_candidates` 的实现：名字最后一段 + 角色工具组 + 装配面，三条一起判。

    前两条是名字消歧（`handler_name` 逐字相同、组在 `_TOOL_GROUPS_BY_ROLE` 里登记过）；
    第三条（`_ASSEMBLED_GROUPS`）是 2026-10-26 补的：那个组必须由 `tools._MODULES` 里的
    模块产出。少了它，"只读到、不装配"的工具（`conjecture.register_conjecture`，
    见 `_TOOL_MODULE_EXTRAS` 的理由串）会被算成"对上了"，而它在工具面上根本不存在。
    """
    groups = _TOOL_GROUPS_BY_ROLE.get(spec.role, ())
    return sorted(
        n for n in tools
        if n.split(".")[-1] == spec.handler_name
        and n.split(".")[0] in groups
        and n.split(".")[0] in _ASSEMBLED_GROUPS
    )


def _reconcile(
    capabilities: Mapping[str, tuple[ActionSpec, ...]],
    tools: Mapping[str, tuple[str, str, bool]],
) -> dict:
    """分区判据本体：把每个动作分进 compared / unmatched / ambiguous 三格之一。"""
    compared: list[tuple[str, str]] = []
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for role, specs in capabilities.items():
        for spec in specs:
            cands = _candidates(spec, tools)
            where = f"{role}.{spec.action}"
            if len(cands) == 1:
                compared.append((where, cands[0]))
            elif cands:
                ambiguous.append(where)
            else:
                unmatched.append(where)
    total = sum(len(v) for v in capabilities.values())
    return {
        "total": total,
        "compared": compared,
        "unmatched": sorted(unmatched),
        "ambiguous": sorted(ambiguous),
    }


def _divergences(
    capabilities: Mapping[str, tuple[ActionSpec, ...]],
    tools: Mapping[str, tuple[str, str, bool]],
    tool_effect_order: tuple[str, ...],
) -> list[DeclarationDivergence]:
    """判据本体：两层声明逐条对账。`tool_effect_order` 是效果轴的危险度次序。"""
    out: list[DeclarationDivergence] = []
    for role, specs in capabilities.items():
        for spec in specs:
            cands = _candidates(spec, tools)
            groups = _TOOL_GROUPS_BY_ROLE.get(spec.role, ())
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
            tool_ext, tool_eff, precise = _tool_axes(tools[tool_name])
            cap_ext, cap_eff = action_axes(spec)

            # 只有"精确声明"才算"能力层低估了风险轴"：第三分量说的是这一条工具的
            # `external` 是不是人写下来的（默认 `none` 与"我声明成 `none`"不是一回事）。
            # 能力层低估 ⇒ error（见下面的 docstring 第 2 条）。
            if precise and tool_ext != "none" and cap_ext == "none":
                out.append(DeclarationDivergence(
                    "two_layer_external_divergence", "error", f"{role}.{spec.action} <-> {tool_name}",
                    f"工具层声明 external={tool_ext!r}，能力层声明 {cap_ext!r}"
                    "（能力层**低估**了这根轴）—— 两层对同一个动作"
                    "能不能触到我们不拥有的事有两个估值，而能力表是并发与召唤判据的输入",
                ))
            elif tool_ext != "none" and cap_ext != "none" and tool_ext != cap_ext:
                # 两层都非 `none`、但精度不同（例如工具说 egress、能力层说 exec）。
                # 不报 error：两层都承认"会触到我们不拥有的事"，风险面没有被低估。
                # 但也不能静默 —— `egress` 与 `exec` 是两根不同的风险面
                # （沙箱怎么承接、审计怎么问都不同），静默会让"精度不同"
                # 变成一件没人看得见的事（P15：判据要么可见，要么没有信息量）。
                out.append(DeclarationDivergence(
                    "two_layer_external_imprecise", "warning", f"{role}.{spec.action} <-> {tool_name}",
                    f"工具层声明 external={tool_ext!r}，能力层声明 {cap_ext!r} —— "
                    "两层都承认这个动作会触到我们不拥有的事，所以不是低估；"
                    "但出网与起进程是两根不同的风险面，两个估值必须同时可见",
                ))
            if tool_effect_order.index(tool_eff) > tool_effect_order.index(cap_eff):
                out.append(DeclarationDivergence(
                    "two_layer_effect_divergence", "error", f"{role}.{spec.action} <-> {tool_name}",
                    f"工具层声明 effect={tool_eff!r}，能力层声明 {cap_eff!r}"
                    "（能力层**低估**了这根轴）—— 与写集/并发判据直接相关",
                ))
    return out


# ---------------------------------------------------------------- 两层参数类型对账（R-36）
# R-36（`draft/28` §150.5）：`_divergences` 只比 property 名与两根轴、不比类型，于是"声明的类型与真
# 交下去的值不是一回事"这一整类缺陷看不见（实测形态：合法派活被参数门判成"dependencies. 必须是对象，收到 array"）。
# 为什么不并进 `_divergences`：它的输入只有两根轴，带类型就得改形状，而 `declaration_divergences_for`
# 是公开纯函数、`tests/test_policy.py` 用合成表喂它 ⇒ 另起一格，两种形态都给（读全局的
# `param_type_divergences()` + 可喂表的 `param_type_divergences_for()`）。
# 类型读源码 AST（同 `_tool_side_effects`：装配一次会在导入期碰文件系统），只认字符串字面量的
# `type`（`properties.<名>.type` / `.items.type`），读不出就记 unknown、不折成通过。


#: 两层参数对账里真的逐个比过的约束键（`R-36` 起只有 `type` / `items.type`，2026-10-22 扩表）。
#:
#: 为什么是这十格：每一格都是「派活面（能力表）」与「校验面（工具表）」必须说同一句话的口径。
#: 判错的后果不是崩溃而是判错：`Conductor._check_params` 读能力表、`validate_params` 读工具表，
#: 一处更松就放行一次必然被拒的派活，一处更紧就把一次合法派活判死（§150 的 `dependencies` 形态）。
#: 不在表里的键（`enum` / `description` / `default` / `additionalProperties` / `pattern` /
#: `items.properties.*` 的逐格约束）今天没有比对 —— 那是三态里的 unknown，读数在
#: `param_type_coverage()['keys_not_compared']` 里（不写的键不会自己变红）。
_PARAM_CONSTRAINT_KEYS: tuple[str, ...] = (
    "type",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "required",
    "items.type",
    "items.required",
)

#: 上面那十个键里"不参与比对"的对立面（只为让读数能把 unknown 说出来，不是第二份真身）。
_PARAM_KEYS_NOT_COMPARED: tuple[str, ...] = (
    "enum",
    "description",
    "default",
    "additionalProperties",
    "pattern",
    "items.properties.*",
)

#: 根级 `required` 在差值报告里的伪 property 名（它不是某个参数，而是 `params.required` 本身）。
_ROOT_REQUIRED = "<root>"

#: 读不出来的取值。与 `None` 必须分开：`None` = 读出来了、确认没有这个键；
#: `_UNRESOLVED` = 这个键写了、但写的是变量/表达式，读不出来（三态里的 unknown）。
_UNRESOLVED: Any = object()


def _dict_value(node: ast.AST | None, key: str) -> ast.AST | None:
    """从一棵 `ast.Dict` 里取某个字符串字面量键对应的值节点；不是字典就返回 `None`。"""
    if not isinstance(node, ast.Dict):
        return None
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _str_value(node: ast.AST | None) -> str | None:
    """字符串字面量取值；变量/表达式一律 `None`（"读不出来"，不是"没有"）。"""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _resolve_const(node: ast.AST | None, consts: Mapping[str, ast.AST]) -> ast.AST | None:
    """沿模块级常量名往下解析，直到拿到一个不是"已知常量名"的节点。

    审计 D-1 的另一半：原来只有一个 `resolve()` 作用在 `params=` 那一层，于是
    `"items": _MAPPING_ROW_PARAMS`（`doc_tools` 里 `rows` 那一行恰恰这么写）永远解析不出来 ——
    症状是 `items.type` 两侧都读成 `None`，那条 array 的比对就被"一侧只写 `{type:array}`"的
    豁免吞掉了。「嵌套位置上的 Name 与顶层是同一件事」，必须在同一个解析器里走到。
    """
    seen = 0
    while isinstance(node, ast.Name) and node.id in consts and seen < 10:
        node = consts[node.id]
        seen += 1
    return node


def _module_aliases(tree: ast.AST) -> dict[str, str]:
    """模块里 `from .. import schema as S` 这类别名 -> 绝对模块名（`S` -> `agentflow.schema`）。

    为什么需要它：工具源码里的边界常写成 `S.ID_DIGITS`（而不是字面量 6）。比的必须是
    "两层说的数是不是同一个"，不是"两层写的表达式是不是同一个" —— 只认字面量会把
    `S.ID_DIGITS` 与 `6` 判成分歧（假报警），而假报警会训练人忽略告警（P15）。
    """
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        package = "agentflow" if node.level >= 2 else "agentflow.tools"
        if node.module:
            base = f"{package}.{node.module}"
            for alias in node.names:
                out[alias.asname or alias.name] = f"{base}.{alias.name}"
        else:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{package}.{alias.name}"
    return out


#: `<模块>.<属性>` 常量名 -> 取值（含 `_UNRESOLVED` 的缓存）。
_ALIAS_CONSTANTS: dict[tuple[str, str], Any] = {}


def _attr_constant(module: str, attr: str) -> Any:
    """`<module>.<attr>` 的取值。读不到（没有这个模块/属性）⇒ `_UNRESOLVED`。"""
    key = (module, attr)
    if key not in _ALIAS_CONSTANTS:
        try:
            value = getattr(importlib.import_module(module), attr)
        except (ImportError, AttributeError):
            value = _UNRESOLVED
        _ALIAS_CONSTANTS[key] = value
    return _ALIAS_CONSTANTS[key]


def _literal(
    node: ast.AST | None,
    consts: Mapping[str, ast.AST],
    aliases: Mapping[str, str],
    depth: int = 0,
) -> Any:
    """把一棵表达式节点解析成 Python 值；解析不了 ⇒ `_UNRESOLVED`（不是 `None`）。

    认四种形态：字面量、模块级常量名（任意深度，见 :func:`_resolve_const`）、
    `<别名>.<常量>`（见 :func:`_module_aliases`）、以及字典/列表的递归。
    刻意不认函数调用：`list(PM.ENV_KINDS)` 这类写法落在 `_UNRESOLVED` 上 ——
    它没有"读错了"的风险，只有"没读出来"这一档。
    """
    if node is None or depth > 8:
        return _UNRESOLVED
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        resolved = _resolve_const(node, consts)
        if resolved is node:
            return _UNRESOLVED
        return _literal(resolved, consts, aliases, depth + 1)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        module = aliases.get(node.value.id)
        return _attr_constant(module, node.attr) if module else _UNRESOLVED
    if isinstance(node, ast.Dict):
        out: dict[str, Any] = {}
        for k, v in zip(node.keys, node.values):
            key = _literal(k, consts, aliases, depth + 1)
            if not isinstance(key, str):
                return _UNRESOLVED
            out[key] = _literal(v, consts, aliases, depth + 1)
        return out
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(x, consts, aliases, depth + 1) for x in node.elts]
    return _UNRESOLVED


def _constraint_face(prop: Any) -> dict[str, Any]:
    """一个 property 的约束面：只留 :data:`_PARAM_CONSTRAINT_KEYS` 里读得出来的那些键。

    返回 `{}` 不是错误：一个只写 `{"type": "string"}` 的 property 约束面就是"只有 type"。
    """
    if not isinstance(prop, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key in ("type", "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum"):
        value = prop.get(key, _UNRESOLVED)
        if value is not _UNRESOLVED and value is not None:
            out[key] = value
    required = prop.get("required", _UNRESOLVED)
    if isinstance(required, (list, tuple)):
        out["required"] = sorted(str(x) for x in required)
    items = prop.get("items", _UNRESOLVED)
    if isinstance(items, Mapping):
        item_type = items.get("type", _UNRESOLVED)
        if item_type is not _UNRESOLVED and item_type is not None:
            out["items.type"] = item_type
        item_required = items.get("required", _UNRESOLVED)
        if isinstance(item_required, (list, tuple)):
            out["items.required"] = sorted(str(x) for x in item_required)
    return out


def _module_constants(tree: ast.AST) -> dict[str, ast.AST]:
    """模块级 `NAME = <字面量>` 的取值节点表，用来解析 `params=EMPTY_PARAMS` 这种写法。"""
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node.value
    return out


def _declared_param_faces(tree: ast.AST) -> list[tuple[str, dict[str, Any] | None]]:
    """从一棵模块 AST 里读出 `(工具名, 约束面)`；约束面是 `{property: 约束键}`。

    约束面的形状是 `{"properties": {名: {...}}, "required": [根级必填]}`。
    `None` = 这条工具的 `params` 读不出来（不是"没有参数"）：两者合成一态就会把
    "这条工具的 schema 我看不见"读成"它没有参数，所以没问题"（P16 族的真空通过）。

    认三种声明形态（与 `_declared_side_effects` 同一套认名规则，多认一个 `params`）：
      - `ToolSpec(name="a.b", params={...})` / `ToolSpec("a.b", "...", {...})`；
      - `@tool("a.b", "...", params={...})` / `@tool("a.b", "...", {...})`；
      - `params=<模块级常量名>`（任意深度解析，见 `_resolve_const`）。
    """
    consts = _module_constants(tree)
    aliases = _module_aliases(tree)
    found: list[tuple[str, dict[str, Any] | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        if fname not in ("ToolSpec", "tool"):
            continue
        # 工具名：`tool` 的第 1 个位置参数、`ToolSpec` 的第 2 个，或关键字 `name=`。
        name: str | None = None
        if fname == "tool":
            name = _str_value(node.args[0]) if node.args else None
        elif len(node.args) > 1:
            name = _str_value(node.args[1])
        params_node: ast.AST | None = node.args[2] if len(node.args) > 2 else None
        for kw in node.keywords:
            if kw.arg == "name":
                name = _str_value(kw.value)
            elif kw.arg == "params":
                params_node = kw.value
        if not name:
            continue
        resolved = _resolve_const(params_node, consts)
        if not isinstance(resolved, ast.Dict):
            found.append((name, None))
            continue
        props_node = _resolve_const(_dict_value(resolved, "properties"), consts)
        if props_node is None:
            found.append((name, {"properties": {}, "required": []}))
            continue
        props_literal = _literal(props_node, consts, aliases)
        if not isinstance(props_literal, Mapping):
            found.append((name, None))
            continue
        props = {str(k): _constraint_face(v) for k, v in props_literal.items()}
        required_literal = _literal(_dict_value(resolved, "required"), consts, aliases)
        required = (sorted(str(x) for x in required_literal)
                    if isinstance(required_literal, (list, tuple)) else [])
        found.append((name, {"properties": props, "required": required}))
    return found


def _tool_declared_names(modules: tuple[str, ...] | None = None) -> list[str]:
    """这些模块里声明的工具名（不管 `params` 读不读得出来）。

    为什么它必须与 `_tool_param_faces` 分开数：读数要能回答"工具层有 N 件，其中几件
    读不出约束面" —— 只数读得出来的那些，`tools_read` 会把"读不出"悄悄折成"不存在"。
    """
    base = Path(__file__).resolve().parent / "tools"
    names: list[str] = []
    for mod_name in (_TOOL_MODULES if modules is None else modules):
        path = base / f"{mod_name}.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        names.extend(name for name, _face in _declared_param_faces(tree))
    return names


def _tool_param_faces(
    modules: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """全仓工具名 -> 约束面（读源码声明，不装配工具层）。

    `params` 读不出来的工具不写进表：调用方按"这条工具没有比对"处理（unknown），
    而不是给它一条空 schema —— 后者的症状是"零分歧"，与真相无关。
    """
    base = Path(__file__).resolve().parent / "tools"
    out: dict[str, dict[str, Any]] = {}
    for mod_name in (_TOOL_MODULES if modules is None else modules):
        path = base / f"{mod_name}.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for name, face in _declared_param_faces(tree):
            if face is not None:
                out[name] = face
    return out


def _face_text(face: Mapping[str, Any]) -> str:
    """把约束面渲染成人能读的一小段（只用于报错信息）。"""
    type_text = face.get("type")
    item_type = face.get("items.type")
    if type_text is None:
        parts = ["（读不出类型）"]
    elif type_text == "array" and item_type:
        parts = [f"array<{item_type}>"]
    else:
        parts = [str(type_text)]
    for key in ("minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum"):
        if key in face:
            parts.append(f"{key}={face[key]}")
    if "required" in face:
        parts.append(f"required={list(face['required'])}")
    if "items.required" in face:
        parts.append(f"items.required={list(face['items.required'])}")
    return "，".join(parts)


def _norm_constraint(value: Any) -> Any:
    """约束值归一：列表按排序比（`required` 的顺序不是语义），其余原样。"""
    if isinstance(value, (list, tuple)):
        return sorted(str(x) for x in value)
    return value


def _face_diff(
    cap_face: Mapping[str, Any],
    tool_face: Mapping[str, Any],
) -> dict[str, list[str]]:
    """两层约束面的差：`{property: [取值不同的约束键]}`。

    根级 `required` 用 :data:`_ROOT_REQUIRED` 当伪 property 名。
    只比"两层都声明了这个 property"的那些（缺 property 由 `param_missing_in_actions` /
    `param_missing_in_tools` 管，两件事不混）。一侧没声明某个键、另一侧声明了 ⇒ 也是差：
    "未声明"是第三种取值，不是"相等"。
    """
    out: dict[str, list[str]] = {}
    cap_props = cap_face.get("properties") or {}
    tool_props = tool_face.get("properties") or {}
    for prop in sorted(set(cap_props) & set(tool_props)):
        cap_declared, tool_declared = cap_props[prop], tool_props[prop]
        keys = [
            key for key in _PARAM_CONSTRAINT_KEYS
            if _norm_constraint(cap_declared.get(key)) != _norm_constraint(tool_declared.get(key))
            and (key in cap_declared or key in tool_declared)
        ]
        if keys:
            out[prop] = keys
    if _norm_constraint(cap_face.get("required")) != _norm_constraint(tool_face.get("required")):
        out[_ROOT_REQUIRED] = ["required"]
    return out


def _action_face(spec: ActionSpec) -> dict[str, Any]:
    """动作声明的约束面（形状与读工具源码得到的约束面逐字相同，见 :func:`_face_diff`）。"""
    params = spec.params or {}
    props = {
        str(name): _constraint_face(declared)
        for name, declared in (params.get("properties") or {}).items()
    }
    required = sorted(str(x) for x in (params.get("required") or []))
    return {"properties": props, "required": required}


def tool_only_constraints(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[tuple[str, str], frozenset[str]]:
    """工具面声明了、动作面没声明的约束键（`"<property>.<键>"` 形态）。

    ## 为什么它与 `param_missing_in_actions` 是两件事
    那一格管的是"工具面有、动作面没有这个 property"；这一格管的是"两层都有这个 property，
    而工具面给它加了边界（`minLength` / `minimum` / `minItems` / 根级 `required`…），动作面只写了类型"。
    审计 D-1 / D-2 / D-3 的真实形态全在这一格里：`doc.write_mapping` 的 `project` 有
    `minLength=1/maxLength=300`、`rows` 有 `minItems=1` 与每行必填六格，动作面只写了
    `_S` / `_ARR_OBJ` ⇒ 派活面比校验面松，而三层对账当时返回 `[]`。

    只对"唯一匹配到工具、且那条工具的约束面读得出来"的对算（与类型对账同一档口径）。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    faces = _tool_param_faces() if tool_faces is None else tool_faces
    out: dict[tuple[str, str], frozenset[str]] = {}
    for role, specs in table.items():
        for spec in specs:
            cands = _candidates(spec, faces)
            if len(cands) != 1:
                continue
            tool_face = faces.get(cands[0])
            if tool_face is None:
                continue
            cap_face = _action_face(spec)
            keys: set[str] = set()
            tool_props = tool_face.get("properties") or {}
            cap_props = cap_face.get("properties") or {}
            for prop in sorted(set(cap_props) & set(tool_props)):
                cap_declared, tool_declared = cap_props[prop], tool_props[prop]
                for key in _PARAM_CONSTRAINT_KEYS:
                    if key in tool_declared and key not in cap_declared:
                        keys.add(f"{prop}.{key}")
            missing_root = set(tool_face.get("required") or []) - set(cap_face.get("required") or [])
            if missing_root:
                keys.add(f"{_ROOT_REQUIRED}.required")
            if keys:
                out[(role, spec.action)] = frozenset(keys)
    return out


#: 已登记的"工具面独有约束"：`(角色, 动作)` -> (确定的那几个 `<property>.<键>`, 理由)。
#:
#: 为什么需要这一格：扩表之后（2026-10-22）对账一次性咬出 13 对、21 个键的不对称 ——
#: 其中 `specs/g.py` / `specs/v.py` 里的六对本次直接补齐（工具层是校验的真身），
#: 剩下七对落在 `specs/c.py` / `e.py` / `f.py` / `h.py`（本轮授权的改动面不含它们）。
#: 处置与 `_KNOWN_UNMATCHED_ACTIONS` 同一条纪律：登记 = 让它可见，不是认可；
#: 两个方向都由判据钉住（`unregistered_tool_only_constraints` 管"新长出来的"，
#: `stale_tool_only_constraint_entries` 管"补齐了却没删的"），所以这张表只增不减会红。
_KNOWN_TOOL_ONLY_CONSTRAINTS: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    ("C", "neighbors"): (
        frozenset({"concept_id.minLength", "concept_id.maxLength"}),
        "`graph.neighbors` 的 `concept_id` 写了 `minLength=4` 与 `maxLength=S.ID_DIGITS`"
        "（与 `C.relations_between` 的 `a`/`b` 同一套编号口径），动作面只写了 `_S`。"
        "补齐它要改 `specs/c.py` —— 不在本轮授权的改动面里。"
        "危害方向：派活面放行一个工具层必然拒收的编号，或反过来把一次合法派活判死。",
    ),
    ("C", "relations_between"): (
        frozenset({"a.minLength", "a.maxLength", "b.minLength", "b.maxLength"}),
        "`graph.relations_between` 的两个端点 `a` / `b` 同样带编号长度上下界，动作面只写了 `_S`。"
        "与上一条同一处修法（`specs/c.py`），同一批人审一起改。",
    ),
    # 2026-10-23 晚：`("E", "check_formal")` 那一对已删 —— 动作整条摘掉之后这一对
    # 不再存在（`unregistered_tool_only_constraints` 也会因"登记过期"报红）。
    ("E", "list_experiments"): (
        frozenset({"limit.minimum"}),
        "`verify.list_experiments` 的 `limit` 有 `minimum=0`，动作面只写了 `_I`。改它在 `specs/e.py`。",
    ),
    ("E", "run_experiment"): (
        frozenset({"timeout.minimum"}),
        "`verify.run_experiment` 的 `timeout` 有 `minimum=1`，动作面只写了 `_N`。改它在 `specs/e.py`。",
    ),
    ("F", "create_plan"): (
        frozenset({"depth.minimum"}),
        "`attack.create_plan` 的 `depth` 有 `minimum=0`，动作面只写了 `_I`。改它在 `specs/f.py`。",
    ),
    ("H", "verify_fixes"): (
        frozenset({"round_no.minimum"}),
        "`review.verify_fixes` 的 `round_no` 有 `minimum=1`（轮次从 1 起），动作面只写了 `_I`。"
        "改它在 `specs/h.py`。",
    ),
}


def unregistered_tool_only_constraints(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """没登记的工具面独有约束（新的一对、或已登记那对又多出一个键）⇒ 判据报这个。"""
    found = tool_only_constraints(capabilities, tool_faces)
    bad: list[str] = []
    for key, keys in sorted(found.items()):
        known = _KNOWN_TOOL_ONLY_CONSTRAINTS.get(key)
        if known is None:
            bad.append(f"{key[0]}.{key[1]}：未登记的工具面独有约束 {sorted(keys)}")
            continue
        extra = sorted(set(keys) - set(known[0]))
        if extra:
            bad.append(f"{key[0]}.{key[1]}：已登记之外又多出 {extra}")
    return bad


def stale_tool_only_constraint_entries(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """登记过期的条目（那个约束键不再独有了 / 那一对不再匹配）⇒ 判据也报这个。

    与 `stale_missing_in_action_entries` 同一条道理：只增不减的登记表会烂成噪音，
    而噪音里的真缺口就没人看了。
    """
    found = tool_only_constraints(capabilities, tool_faces)
    stale: list[str] = []
    for (role, action), (keys, _why) in sorted(_KNOWN_TOOL_ONLY_CONSTRAINTS.items()):
        live = set(found.get((role, action), frozenset()))
        gone = sorted(set(keys) - live)
        if gone:
            stale.append(
                f"{role}.{action}：登记里的 {gone} 已经不再独有（动作面补齐了 / 工具面删了 / 那一对不匹配了）"
                " ⇒ 删掉这几条登记"
            )
    return stale


def param_type_divergences_for(
    capabilities: Mapping[str, tuple[ActionSpec, ...]],
    tool_faces: Mapping[str, Mapping[str, Any]],
) -> list[DeclarationDivergence]:
    """判据本体（两张表都由调用方给）：两层对同一个 property 的约束面不一致。

    比的是 :data:`_PARAM_CONSTRAINT_KEYS` 里那十格，不是只有 `type`。三层口径：

    1. 只比"两层都声明了这个 property"的那些（缺 property 由 `param_missing_in_actions`
       / `param_missing_in_tools` 管）—— 两件事不混；
    2. 一侧声明了某个键、另一侧没声明 ⇒ 也算差："未声明"是第三种取值，不是"相等"；
       原来那条"一侧只写 `{type: array}` 就不报"的豁免已经删掉 —— 它正是把
       `doc.write_mapping.rows` 吞掉的那一条（`items` 写成模块常量名时两侧都读成 `None`，
       于是"一侧有 items.type"这个前提根本不成立，豁免连判都没判就放过了）；
    3. `_KNOWN_TOOL_ONLY_CONSTRAINTS` 里登记的"工具面独有约束"不在本函数里报（它们在
       `tool_only_constraints()` 的读数与第 [9b] 条的两个方向断言里），所以本函数返回 `[]`
       的含义是"没有未登记的约束不对称"，不是"两层逐字相同"。

    `tool_faces` 的形状是 `{工具名: {"properties": {property: {约束键: 值}}, "required": [...]}}`
    （见 :func:`_tool_param_faces`）；`_PARAMS_DERIVED_FROM_TOOL` 里登记的那几对，"真身"
    就是它的来源 —— 判据消费的是派生结果，不是自己另比一遍。
    """
    out: list[DeclarationDivergence] = []
    for role, specs in capabilities.items():
        for spec in specs:
            cands = _candidates(spec, tool_faces)
            if len(cands) != 1:
                continue
            tool_name = cands[0]
            tool_face = tool_faces.get(tool_name)
            if tool_face is None:
                continue
            cap_face = _action_face(spec)
            known = _KNOWN_TOOL_ONLY_CONSTRAINTS.get((role, spec.action), (frozenset(), ""))[0]
            cap_props = cap_face.get("properties") or {}
            tool_props = tool_face.get("properties") or {}
            for prop, keys in sorted(_face_diff(cap_face, tool_face).items()):
                kept: list[str] = []
                for key in keys:
                    cap_declared = cap_props.get(prop, {})
                    tool_declared = tool_props.get(prop, {})
                    tool_only = key in tool_declared and key not in cap_declared
                    if tool_only and f"{prop}.{key}" in known:
                        continue
                    kept.append(key)
                if not kept:
                    continue
                if prop == _ROOT_REQUIRED:
                    detail = (
                        f"根级 required：能力层 {list(cap_face.get('required') or [])}，"
                        f"工具层 {list(tool_face.get('required') or [])}"
                    )
                else:
                    detail = (
                        f"property {prop!r} 的约束键 {kept}：能力层声明 "
                        f"{_face_text(cap_props.get(prop, {}))}，工具层声明 "
                        f"{_face_text(tool_props.get(prop, {}))}"
                    )
                out.append(DeclarationDivergence(
                    "two_layer_param_type_divergence", "error",
                    f"{role}.{spec.action} <-> {tool_name}",
                    detail
                    + " —— 两层对『这个参数的边界』有两个答案。危害不是报错而是判错："
                    "参数门（`Conductor._check_params`）读的是能力表，而 `ToolRegistry.call` "
                    "第一步 `validate_params` 读的是工具表 ⇒ 一条合法派活会被能力表判死"
                    "（§150 的 `dependencies` 就是这样：能力层 `_OBJ` vs 工具层 array<object>），"
                    "或者反过来放行一个工具层必然拒收的形状。"
                    "改哪一层由人定：工具层是校验的真身，能力层是派活的契约，"
                    "两者对不上时先问『谁在说谎』，不许让判据替你选。",
                ))
    return out


def param_type_divergences() -> list[DeclarationDivergence]:
    """真实树上的参数对账读数（`param_type_divergences_for` 读全局版本）。"""
    return param_type_divergences_for(CAPABILITIES, _tool_param_faces())


def param_type_coverage() -> dict:
    """参数对账的覆盖率读数：判据看进去多少（P16：零分歧必须配上覆盖读数）。

    键与它们的用途：
    - `tools_read`：读出了约束面的工具数；
    - `tools_in_registry_modules`：`tools._MODULES`（工具面的真身）声明的工具数；
    - `tools_unread`：那些工具里 `params` 读不出来的（`table_tools` / `fs_tools` 把
      `params` 写成 `_obj(...)` 调用，不是字典字面量 ⇒ unknown，不是"没有参数"）；
    - `tools_read_but_not_registered`：读到了、但不在 `tools._MODULES` 里的（今天只有
      `conjecture.register_conjecture`，理由见 `_TOOL_MODULE_EXTRAS`）；
    - `modules_missing`：名单里有、盘上没有的模块（unknown）；
    - `compared` / `keys_compared`：逐对看过的 (动作, property) 对数与 (动作, property, 键) 个数；
    - `unread`：对上了唯一工具、但那条工具的约束面读不出来（unknown）；
    - `tool_only_constraints` / `registered_tool_only_constraints`：工具面独有约束的实测数与登记数；
    - `keys_not_compared`：扩表时刻意没比的键（`enum` 等）—— 不写的键不会自己变红。

    为什么要 `tools_in_registry_modules` + `tools_unread` + `tools_read_but_not_registered` 三个数：
    只报一个 `tools_read` 时，"77" 与 "95" 之间的 18 件没有出处，读的人只能猜（审计 D-6）。
    三个数一起写，等式是 `tools_in_registry_modules = tools_read + len(tools_unread)
    - len(tools_read_but_not_registered)`，导入期打在 stderr 上。
    """
    from .tools import _MODULES as REGISTRY_MODULES

    faces = _tool_param_faces()
    registry_faces = _tool_param_faces(REGISTRY_MODULES)
    registry_names = _tool_declared_names(REGISTRY_MODULES)
    base = Path(__file__).resolve().parent / "tools"
    compared = 0
    keys_compared = 0
    unread: list[str] = []
    for role, specs in CAPABILITIES.items():
        for spec in specs:
            cands = _candidates(spec, faces)
            if len(cands) != 1:
                continue
            tool_face = faces.get(cands[0])
            if tool_face is None:
                unread.append(f"{role}.{spec.action} <-> {cands[0]}")
                continue
            cap_props = _action_face(spec).get("properties") or {}
            tool_props = tool_face.get("properties") or {}
            for prop in sorted(set(cap_props) & set(tool_props)):
                compared += 1
                keys_compared += len(set(cap_props[prop]) | set(tool_props[prop]))
    return {
        "tools_read": len(faces),
        "tools_in_registry_modules": len(registry_names),
        "tools_unread": sorted(set(registry_names) - set(registry_faces)),
        "tools_read_but_not_registered": sorted(set(faces) - set(registry_names)),
        "modules_missing": sorted(
            m for m in _TOOL_MODULES if not (base / f"{m}.py").is_file()
        ),
        "compared": compared,
        "keys_compared": keys_compared,
        "unread": sorted(unread),
        "tool_only_constraints": len(tool_only_constraints(tool_faces=faces)),
        "registered_tool_only_constraints": len(_KNOWN_TOOL_ONLY_CONSTRAINTS),
        "keys_not_compared": list(_PARAM_KEYS_NOT_COMPARED),
    }


#: "动作面参数的真身在工具层"的对：`(角色, 动作)` -> 理由。
#:
#: 2026-10-22 业主裁定（治本口径）：同一件事只有一个真身，另一层必须派生自它 ——
#: `G.write_mapping` 的 `project` / `rows` 与 `V.verify_proof` 的 `proof_no` 就是被点名的三处。
#: 真身是工具层（`tools/doc_tools.py` / `tools/verify_tools.py` 里 `validate_params` 真正读的那一份），
#: 动作面只镜像它的约束键；漂移由第 [9c] 条逐键对拍（`param_derivation_violations()`）。
#: 为什么不直接把动作面写成 `action_params_from_tool(...)` 的调用：`specs/` 是声明层，
#: 让它 import `capabilities` 会造出 `capabilities -> specs -> capabilities` 的循环导入；
#: 所以"派生"落在断言上（改工具层 ⇒ 导入期当场红），而不是落在运行期取值上。
_PARAMS_DERIVED_FROM_TOOL: dict[tuple[str, str], str] = {
    ("G", "write_mapping"): (
        "审计 D-2：动作面原来只有 `project: _S` 与 `rows: _ARR_OBJ`，而工具面"
        "（`doc.write_mapping`）有 `project.minLength=1/maxLength=300`、"
        "`rows.minItems=1` 与每行必填六格（kind/label/env_no/ledger_id/proof_no/file）"
        " ⇒ 动作门 PASS、工具门 REJECT，而三层对账返回 `[]`。"
        "真身是工具层：它是 `papermapping.parse_rows` 之前真正校验的那一份。"
    ),
    ("V", "verify_proof"): (
        "审计 D-3：动作面的 `proof_no` 只有 `_I`，工具面有 `minimum=1`"
        "（第几条证明，1 = canonical）。真身是工具层 —— 给工具面放宽不算修，"
        "把动作面补到与工具面同界才算。"
    ),
}


def action_params_from_tool(
    role: str,
    action: str,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """一条动作的参数真身：它唯一匹配到的工具的约束面（`{property: {约束键: 值}}`）。

    `None` = 没有唯一匹配的工具 / 那条工具的 `params` 读不出来 / 动作不存在 ——
    三态里的 unknown，不是"两层一致"（`B.register_statement` 就是这一档：它没有同名工具）。
    """
    faces = _tool_param_faces() if tool_faces is None else tool_faces
    spec = find_action(role, action)
    if spec is None:
        return None
    cands = _candidates(spec, faces)
    if len(cands) != 1:
        return None
    return faces.get(cands[0])


def param_derivation_violations(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """`_PARAMS_DERIVED_FROM_TOOL` 里那几对的逐键对拍（导入期第 [9c] 条读它）。

    它比 :func:`param_type_divergences` 窄（只看登记的那几对），但更强：派生面读不出来
    （unknown）在这里也是红 —— 而在 `param_type_divergences` 里那只是"没比对"。
    返回人话列表（空 = 通过）；每一条都点名 (角色, 动作) 与差异的 property/键。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    faces = _tool_param_faces() if tool_faces is None else tool_faces
    out: list[str] = []
    for (role, action), why in sorted(_PARAMS_DERIVED_FROM_TOOL.items()):
        spec = next((s for s in table.get(role, ()) if s.action == action), None)
        if spec is None:
            out.append(f"{role}.{action}：登记说它的参数真身在工具层，而动作面里没有这条动作（登记过期）")
            continue
        derived = action_params_from_tool(role, action, faces)
        if derived is None:
            out.append(
                f"{role}.{action}：派生面读不出来（没有唯一匹配的工具 / 那条工具的 `params` 不是字面量）"
                f" ⇒ 这一格是 unknown，不是一致。登记的理由：{why}"
            )
            continue
        for prop, keys in sorted(_face_diff(_action_face(spec), derived).items()):
            cap_props = _action_face(spec).get("properties") or {}
            out.append(
                f"{role}.{action}：{prop} 的 {keys} 与工具层（真身）不一致 —— 动作面声明 "
                f"{_face_text(cap_props.get(prop, {}))}，工具层声明 "
                f"{_face_text((derived.get('properties') or {}).get(prop, {}))}"
            )
    return out


#: 实测的"工具面声明了、动作面没声明"的 property（`two_layer_param_missing_in_action`）。
#: 为什么要有这一格（残项 ㉓；2026-10-07 所有者授权 5b"补反向 + 新计数并入读数"）：正反两处既有
#: 判据都管不到这个方向 —— `param_type_divergences_for` 由动作面驱动（动作没声明的 property 它根本
#: 看不见），`param_seam_violations` 管的是"动作声明了、实现不收" ⇒ "工具面加了参数、忘了加动作面"
#: 这条裂缝全树没有读数会报。形态：按 (角色, 动作) 登记确切的那几个 property + 理由。三种变化都会红：① 出现新的一对 ·
#: ② 已登记那对又多缺一个 · ③ 登记里某个不再缺了（登记过期 ⇒ 必须删掉，否则会烂成噪音）。
#: 判据本体在 `tests/test_capabilities_reverse_param_gaps.py`（刻意不进导入期）；这是可见性登记、
#: 不是"认可"：改哪一层由人定。
_KNOWN_TOOL_ONLY_PARAMS: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    ("B", "run"): (
        frozenset({"backend", "dpi", "languages", "max_pages", "pages", "path", "lit_id"}),
        "`B.run` 的实现是 `ocr.run`（⑫ 的接线）：工具面那六个 OCR 参数是接线时加的，"
        "动作面当时没同步。改它是动 `specs/b.py` 的声明面（禁改区），而"
        "「B 的动作面该不该暴露 OCR 的后端/页数/语言」是设计判断，先让它可见。"
        "2026-10-16 再加 `lit_id`（亲测 B 时：这一件原本只认 `path`，而 B 整个域都按"
        "文献编号说话 ⇒ 给编号要能work；编号→路径的解析在 `ocr_tools._target_path`，"
        "三态齐全：两者都不给 ⇒ `no_target`、编号不认得 ⇒ `unknown_lit_id` 并列出盘上有的编号）。"
        "**这一条落在禁改区（本文件），已登记待 2 名 reviewer 批准**。",
    ),
    ("C", "neighbors"): (
        frozenset({"max_neighbors"}),
        "`graph.neighbors` 有可选上限 `max_neighbors`，动作面只声明了必填。"
        "C 的图上动作今天只走 `neighbors`/`paths` 两个入口，上限是否要暴露给编排层未见裁定。",
    ),
    # 2026-10-26：`("D", "register_conjecture")` 那一对已删（登记过期）。它登记的是
    # "`conjecture.register_conjecture` 有 `force_new`，动作面没声明"；而那条工具不在
    # `tools._MODULES` 里（`build_registry` 不装配它）⇒ 这一对现在落进"没有工具层"那一格
    # （见 `_KNOWN_UNMATCHED_ACTIONS` 与 `_KNOWN_ACTION_ONLY_PARAMS` 的同名条目）。
    # 反向缺口只对"唯一匹配到工具"的对算，所以这条登记留着就会变成噪音；
    # "那条工具上有 force_new" 这个事实仍在它自己的 schema 里，工具的注册状态由
    # `param_type_coverage()['tools_read_but_not_registered']` 报。
    #
    # 2026-10-23 晚：`("E", "run_experiment")` 的 `run_name` 与
    # `("E", "check_formal")` 的 `checker_name` 两对已删 —— 前者随工具 schema 一起
    # 退场（那两个参数只服务 formal，而 E 不做形式化），后者随动作整条摘掉。
    ("G", "compose_claim"): (
        frozenset({"allowed_use", "counterexamples", "errata_ids", "freeze_reason", "frozen",
                   "kind", "numeric_evidence", "proof_location", "revision_hash",
                   "scope_caveat", "status"}),
        "`doc.compose_claim` 是**通用写入口**（十一个可选字段覆盖冻结/勘误/数值证据等），"
        "而 `G.compose_claim` 这个动作用的是它的一小部分契约 ⇒ 这个方向的不对称"
        "很可能是**刻意的**（动作面就是比工具面窄）。登记它是因为"
        "「刻意」必须被写下来才算刻意 —— 不写下来，它与前面六处的形态完全一样。",
    ),
    ("H", "verify_fixes"): (
        frozenset({"max_review_rounds"}),
        "`review.verify_fixes` 有 `max_review_rounds`，动作面没声明。",
    ),
}


def _tool_param_schemas() -> dict[str, dict[str, tuple[str | None, str | None]]]:
    """工具名 -> `{property: (type, items.type)}` 的旧视图（从约束面派生，不是第二次读源码）。

    为什么留着它：`param_missing_in_actions` 那一族（工具面有、动作面没有的 property）只需要
    property 名与类型，而 `tests/test_capabilities_reverse_param_gaps.py` 是拿这个形状喂替身表的
    （`{p: (None, None)}`）。让两处各有各的形状而读源码只有一处（`_tool_param_faces`），
    比为了统一形状去改一张已登记的替身表安全。
    """
    return {
        name: {
            prop: (face.get("type"), face.get("items.type"))
            for prop, face in (face_of_tool.get("properties") or {}).items()
        }
        for name, face_of_tool in _tool_param_faces().items()
    }


def param_missing_in_actions(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_params: Mapping[str, Mapping[str, tuple[str | None, str | None]]] | None = None,
) -> dict[tuple[str, str], list[str]]:
    """判据本体（反向）：工具面声明了、动作面没声明的 property。

    只对"唯一匹配到某个工具、且那条工具的 `params` 读得出来"的 (角色, 动作) 算 ——
    与 `param_type_divergences_for` 同一档口径（多义与读不出来的都不猜）。
    覆盖率读数见 `param_missing_in_action_coverage()`：空集永远是子集，
    所以"没有反向缺口"这句话必须配上"比过多少对"才作数。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    schemas = _tool_param_schemas() if tool_params is None else tool_params
    out: dict[tuple[str, str], list[str]] = {}
    for role, specs in table.items():
        for spec in specs:
            cands = _candidates(spec, schemas)
            if len(cands) != 1:
                continue
            tool_props = schemas.get(cands[0])
            if tool_props is None:
                continue
            cap_props = set((spec.params or {}).get("properties") or {})
            missing = sorted(set(tool_props) - cap_props)
            if missing:
                out[(role, spec.action)] = missing
    return out


def param_missing_in_action_coverage(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_params: Mapping[str, Mapping[str, tuple[str | None, str | None]]] | None = None,
) -> dict:
    """反向那一格的覆盖读数：`pairs`（真的逐对比过的动作数）与 `gaps`（缺口数）。"""
    table = CAPABILITIES if capabilities is None else capabilities
    schemas = _tool_param_schemas() if tool_params is None else tool_params
    pairs = 0
    for _role, specs in table.items():
        for spec in specs:
            cands = _candidates(spec, schemas)
            if len(cands) != 1 or schemas.get(cands[0]) is None:
                continue
            pairs += 1
    return {"pairs": pairs, "gaps": len(param_missing_in_actions(table, schemas))}


def unregistered_missing_in_actions(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_params: Mapping[str, Mapping[str, tuple[str | None, str | None]]] | None = None,
) -> list[str]:
    """没登记的缺口（新的一对、或已登记那对又多缺了一个）⇒ 判据报这个。"""
    found = param_missing_in_actions(capabilities, tool_params)
    bad: list[str] = []
    for key, missing in sorted(found.items()):
        known = _KNOWN_TOOL_ONLY_PARAMS.get(key)
        if known is None:
            bad.append(f"{key[0]}.{key[1]}：未登记的工具面独有参数 {missing}")
            continue
        extra = sorted(set(missing) - set(known[0]))
        if extra:
            bad.append(f"{key[0]}.{key[1]}：已登记之外又多缺了 {extra}")
    return bad


def stale_missing_in_action_entries(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_params: Mapping[str, Mapping[str, tuple[str | None, str | None]]] | None = None,
) -> list[str]:
    """登记过期的条目（那个 property 不再缺了、或那一对根本不再匹配）⇒ 判据也报这个。

    与 `stale_param_seams` 同一条道理：只增不减的登记表会烂成噪音，
    而噪音里的真缺口就没人看了。
    """
    found = param_missing_in_actions(capabilities, tool_params)
    stale: list[str] = []
    for (role, action), (props, _why) in sorted(_KNOWN_TOOL_ONLY_PARAMS.items()):
        live = set(found.get((role, action), []))
        gone = sorted(set(props) - live)
        if gone:
            stale.append(f"{role}.{action}：登记里的 {gone} 已经不再缺了 ⇒ 删掉这几条登记")
    return stale


# ------------------------------------------------- 动作面独有参数（反向的另一半，审计 D-4）
#
# 上面那一族管"工具面有、动作面没有"；这一族管"动作面有、工具面没有"。两者的计算范围不同，
# 口径必须写死（2026-10-22 业主裁定，甲方案）：
#
# - 有工具面的动作（唯一匹配到某件工具）⇒ 逐 property 算：动作面声明了、工具面没有的那些就是
#   动作面独有参数。今天 23 对里 6 对有缺口（9 个 property）。
# - 没有工具面的动作（`B.register_statement` 这类：整条动作没有同名工具）⇒ 不逐 property 算。
#   把"没有工具层"一律当成"每个 property 都独有"，实测会得到 42 对、111 个 property 的清单，
#   而那与 `_KNOWN_UNMATCHED_ACTIONS`（同样那 39 条动作）是同一个事实的第二份登记 ——
#   同一个事实记在两处必然漂。这一档进下面那张表的第二栏：按 (角色, 动作) 登记，
#   且登记的 property 集合必须等于动作面声明的集合（多一个少一个都红）。
#
# 判据本体在 `tests/test_two_layer_constraints_really_match.py`（与 `_KNOWN_TOOL_ONLY_PARAMS`
# 同一条纪律：登记是可见性，不是认可；改哪一层由人定）。

#: 动作面独有参数登记：`(角色, 动作)` -> (那一对的全部动作面独有 property, 理由)。
#:
#: 第一栏（有工具面）：值就是"工具面没有的那些 property"。
#: 第二栏（没有工具面）：值是动作面声明的全部 property —— 因为那时"工具面"是空集，
#: 动作面的每一个 property 都只活在动作面。第二栏的意义正是"这条动作没有工具层"这件事，
#: 而不是逐格挑刺：所以判据要求"登记集合 == 动作面声明的集合"，删掉任何一个都红。
_KNOWN_ACTION_ONLY_PARAMS: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    ("B", "run"): (
        frozenset({"max_docs"}),
        "`B.run` 的落地工具是 `ocr.run`（⑫ 的接线），而 `ocr.run` 一次只读一份 PDF；"
        "`max_docs` 是 `B.run` 自己的有界连续抽取上限（循环在角色级实现里）⇒ 工具面没有它。"
        "补一个同名工具会把两件事压成一件（一次 OCR 与一轮有界抽取），所以登记。",
    ),
    ("C", "neighbors"): (
        frozenset({"depth", "max_nodes"}),
        "`graph.neighbors` 的图上参数叫 `max_neighbors`；`depth` / `max_nodes` 是 C 角色级"
        "遍历的上限（BFS 深度与节点数），工具面没有这两个名字 ⇒ 动作面独有。"
        "要不要把它们暴露成工具参数是 C 的算法口径问题，未见裁定。",
    ),
    ("C", "relations_between"): (
        frozenset({"include_inactive"}),
        "`graph.relations_between` 只列现行关系；`include_inactive` 是动作面多出来的"
        "「算不算已失效关系」开关 ⇒ 工具面没有（它今天恒按现行算）。",
    ),
    ("E", "run_experiment"): (
        frozenset({"sleep"}),
        "`sleep` 只服务替身夹具、实现侧刻意不收（逐条理由在 `PARAM_SEAMS`）⇒ 工具面没有"
        "同名工具参数。2026-10-23 晚：`name` 从这一格里退场 —— 动作面不再声明它"
        "（它只服务 formal，而 E 不做形式化，工具 schema 的 `run_name` 也一起删了）。",
    ),
    # 2026-10-23 晚：`("E", "check_formal")` 那一对已删（动作整条摘掉）。
    ("D", "register_conjecture"): (
        frozenset({
            "conjecture_id", "counterexample_experiment_id", "experiment_ids", "form",
            "known_lit_id", "negation_statement", "notes", "origin", "promoted_to",
            "proof_experiment_id", "statement", "status", "testable", "withdraw_reason",
        }),
        "这条动作没有工具层（2026-10-26 起）：落地工具 `conjecture.register_conjecture` "
        "住在 `tools/conjecture_tools.py`，而那个模块不在 `tools._MODULES` 里 ⇒ "
        "`build_registry` 不装配它。「读到、但不注册」这件事仍由 "
        "`param_type_coverage()['tools_read_but_not_registered']` 如实报出（那条工具上有 "
        "`force_new`，本动作面不声明它 —— 同一条事实的另一半）。这里的 14 格是动作面"
        "声明的全部 property：没有工具面时它们只活在动作面，不登记就等于在读数里不存在。",
    ),
    ("H", "list_findings"): (
        frozenset({"kind"}),
        "`review.list_findings` 按 `level` / `status` 过滤，而动作面按 `kind` 过滤 ⇒"
        "动作面独有；`kind` 是 H 的发现分类，工具面今天不认这个名字。",
    ),
    ("B", "register_statement"): (
        frozenset({
            "statement_full", "source_lit_id", "proof_text", "proofs", "kind", "label",
            "statement_text", "origin", "page_range", "evidence_kind", "quote_verified",
            "quote_mode", "quote_reason", "quote_span", "quote_call_sha256", "doc_id",
            "line_range", "derived_from",
        }),
        "这条动作没有同名工具：`proofs`（以及其余十七格）由 `AgentB.register_statement(proofs=...)`"
        "直接收 —— 整条动作的 schema 就是动作声明本身（`table.create` 那条通用写口被"
        "`store.direct_write_refusal` 挡住，拒信里指的 `own.register_statement` 路由没有"
        "独立的工具 schema，它取的就是这份动作声明）。所以这里的 property 不是"
        "「工具面漏了」，而是「唯一落点」；登记它是为了让"
        "「B 的 proofs 没有工具层」这件事实可见 —— 不登记时它落在 unknown，"
        "而 unknown 与「两层一致」在读数上长得一样（审计 D-4）。"
        "2026-10-22（D1）：`quote_span` / `quote_call_sha256` 两格同日加进动作面"
        "（引文回验的证据栏，此前 `additionalProperties=false` 让模型连参数名都传不进来），"
        "它们同样只活在动作面 ⇒ 一并登记（登记集合必须等于动作面集合，缺一个就红）。"
        "判据：登记集合必须等于动作面声明的集合（`unregistered_missing_in_tools` 第 ③ 条）。",
    ),
    # 2026-10-22 第二班曾在这里登记 `("L", "formalize"): {"statement_id"}`
    # （动作面有、工具面没有）。第三班把 `statement_id` 补进工具面
    # `formal.formalize` 的 params 与 handler 之后，这一对不再有缺口 ——
    # 按 `stale_action_only_entries` 的纪律（登记表不许留过期名字）删掉这一条，
    # 否则读的人会以为"显式编号走不通"，而它已经通了。
}


def _action_props(spec: ActionSpec) -> frozenset[str]:
    """一条动作声明的 property 名集合。"""
    return frozenset(str(p) for p in ((spec.params or {}).get("properties") or {}))


def param_missing_in_tools(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[tuple[str, str], list[str]]:
    """动作面声明了、它唯一匹配到的工具面没有的 property（第一栏）。

    只对"唯一匹配到工具、且那条工具的约束面读得出来"的对算 —— 与 `param_missing_in_actions`
    同一档口径（多义与读不出来的都不猜）。没有工具面的对（`B.register_statement` 这类）
    不在这里，它们进 `_KNOWN_ACTION_ONLY_PARAMS` 的第二栏，由
    :func:`unregistered_missing_in_tools` 的第 ③ 条判。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    faces = _tool_param_faces() if tool_faces is None else tool_faces
    out: dict[tuple[str, str], list[str]] = {}
    for role, specs in table.items():
        for spec in specs:
            cands = _candidates(spec, faces)
            if len(cands) != 1:
                continue
            tool_face = faces.get(cands[0])
            if tool_face is None:
                continue
            tool_props = set(tool_face.get("properties") or {})
            missing = sorted(_action_props(spec) - tool_props)
            if missing:
                out[(role, spec.action)] = missing
    return out


def param_missing_in_tools_coverage(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict:
    """动作面独有参数的覆盖读数（P16：空集永远是子集，所以必须配"比过多少对"）。

    三格分开数，因为它们的"没有缺口"说的不是同一句话：`pairs_with_tool`（真的逐 property
    比过）、`unmatched`（动作对应 0 个工具 ⇒ 整条动作没有工具层）、`unreadable`
    （对应唯一工具但它的 `params` 读不出来 ⇒ unknown）。把后两格并进第一格，
    "6 对没有缺口"就会被读成"两层都对齐了"。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    faces = _tool_param_faces() if tool_faces is None else tool_faces
    pairs_with_tool = 0
    unmatched: list[str] = []
    unreadable: list[str] = []
    ambiguous: list[str] = []
    for role, specs in table.items():
        for spec in specs:
            cands = _candidates(spec, faces)
            where = f"{role}.{spec.action}"
            if not cands:
                unmatched.append(where)
                continue
            if len(cands) > 1:
                ambiguous.append(where)
                continue
            if faces.get(cands[0]) is None:
                unreadable.append(where)
                continue
            pairs_with_tool += 1
    return {
        "pairs_with_tool": pairs_with_tool,
        "unmatched": sorted(unmatched),
        "ambiguous": sorted(ambiguous),
        "unreadable": sorted(unreadable),
        "gaps": len(param_missing_in_tools(table, faces)),
        "registered": len(_KNOWN_ACTION_ONLY_PARAMS),
    }


def unregistered_missing_in_tools(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """未登记 / 登记不全的动作面独有参数（三条判据，缺一条就有一种坏法看不见）。

    ① 有工具面的对：计算出来的缺口必须在登记表里，且不许比登记的多；
    ② 第二栏（没有工具面的对）：登记的 property 集合必须等于动作面声明的集合 ——
       动作面新加一格而没登记 ⇒ 这里红（这是本判据的牙：删掉登记里的 `proofs` 也走这一条）；
    ③ 登记过期由 :func:`stale_action_only_entries` 管（两个方向分开报，修法不同）。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    faces = _tool_param_faces() if tool_faces is None else tool_faces
    found = param_missing_in_tools(table, faces)
    bad: list[str] = []
    for key, missing in sorted(found.items()):
        known = _KNOWN_ACTION_ONLY_PARAMS.get(key)
        if known is None:
            bad.append(f"{key[0]}.{key[1]}：未登记的动作面独有参数 {missing}")
            continue
        extra = sorted(set(missing) - set(known[0]))
        if extra:
            bad.append(f"{key[0]}.{key[1]}：已登记之外又多出 {extra}")
    for (role, action), (props, _why) in sorted(_KNOWN_ACTION_ONLY_PARAMS.items()):
        spec = next((s for s in table.get(role, ()) if s.action == action), None)
        if spec is None:
            continue  # 由 stale 管（动作已经不在了）
        cands = _candidates(spec, faces)
        if len(cands) == 1 and faces.get(cands[0]) is not None:
            continue  # 有工具面 ⇒ 由上面的 ① 与 stale 管
        unregistered = sorted(_action_props(spec) - set(props))
        if unregistered:
            bad.append(
                f"{role}.{action}：动作面声明了 {unregistered}，而登记表里没有它们 ——"
                "这条动作没有工具层，所以它的每个 property 都只活在动作面；"
                "没登记的那几格在读数里等于不存在（unknown 被读成「一致」）"
            )
    return bad


def stale_action_only_entries(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_faces: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """登记过期：登记的 property 不再独有、或那一对的"没有工具层"前提已经变了。

    与 `stale_missing_in_action_entries` 同一条道理：只增不减的登记表会烂成噪音。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    faces = _tool_param_faces() if tool_faces is None else tool_faces
    found = param_missing_in_tools(table, faces)
    stale: list[str] = []
    for (role, action), (props, _why) in sorted(_KNOWN_ACTION_ONLY_PARAMS.items()):
        spec = next((s for s in table.get(role, ()) if s.action == action), None)
        if spec is None:
            stale.append(f"{role}.{action}：能力表里已经没有这条动作 ⇒ 删掉这条登记")
            continue
        cands = _candidates(spec, faces)
        if len(cands) == 1 and faces.get(cands[0]) is not None:
            live = set(found.get((role, action), []))
            gone = sorted(set(props) - live)
            if gone:
                stale.append(
                    f"{role}.{action}：这条动作现在有工具面了，而登记里的 {gone} 工具面已经有了 ⇒"
                    " 删掉这几条登记（它不再是「动作面独有」）"
                )
            continue
        gone = sorted(set(props) - _action_props(spec))
        if gone:
            stale.append(f"{role}.{action}：动作面已经没有 {gone} ⇒ 删掉这几条登记")
    return stale


def _tool_axes(declared: tuple[str, str, bool]) -> tuple[str, str, bool]:
    """工具层一个声明在两根轴上的取值，以及"external 是不是精确声明"。

    `declared` 是源码里读出来的 `(side_effect, external, 是否显式声明 external)`：
    两根轴都直接取那两个声明（`external` 那根轴就是人写的 `declared_external=`
    或 `@tool(external=…)`），第三个分量原样透传 —— 它是
    "`external` 是人写下来的，还是落到了默认值 `none`"。

    B3 收官前这个函数还要为 `side_effect == "network"` 查逐工具翻译表
    （所以参数里有工具名），并因此把第三分量强制成 `False`
    （翻译出来的值当然不是精确声明）。`network` 从词表里删掉之后，
    那条分支连同工具名这个参数一起消失：这个函数现在是一次恒等读取。
    """
    side_effect, declared_external, explicit = declared
    return (declared_external, side_effect, explicit)




# ---------------------------------------------------------------- 动作表
#
# `D-8`（更正，观测时刻 2026-09-26 19:0x）：这里原来是一大片 `文件:行号`，那些行号全部过期了，
# 而且与 `.noai-paths` 第 35-45 行逐字论证过的纪律相反（"理由里刻意写符号名不写行号"：行号易失，
# 实测 `normalize_doi` 在几十分钟内就从 26 行漂到 44 行）。所以这里只写符号名（`<Class>.<method>`），
# 由 `tests/test_capabilities_two_layer.py::test_action_handler_names_exist_as_class_methods` 逐个
# 断言"这个名字真的存在于对应模块的那个类里"（符号名比行号强：改行号它不响，删了那个方法它必响）。
# 动作声明的真身是 `specs/<角色>.py` 的 `ACTIONS`（M3 起），本表只做派生。

#: 角色 -> 该角色的动作元组。不在表里的角色没有任何动作（`M` 就是如此：
#: 主控的"动作"是 `summon()` 本身，它由 `Conductor` 实现，不是一个 Agent 方法）。
#: 真身是 `src/agentflow/specs/<角色>.py`（M3 起）。这一行只做派生 —— 
#: 也就是说改权限面要改 `specs/`，而 `specs/` 在 `.noai-paths` 里受保护。
CAPABILITIES: dict[str, tuple[ActionSpec, ...]] = _specs.action_table()

#: `M` 没有任何动作，但它必须在键集合里（与 `schema.ROLES` 不同的一套名单会漂移）。
#: 为什么空而不是省掉：`CAPABILITIES["M"] == ()` 让"主控不产出领域对象"这条约束
#: 变成可断言的事实，而不是"表里没写所以大概是吧"。


# ---------------------------------------------------------------- 参数接缝（声明 ↔ 实现签名）
# `ActionSpec.params` 是声明，handler 的 `inspect.signature` 是实现；此前两者没有任何机器判据相连
# （`Conductor._check_params` 只看声明）⇒ 声明里多一个 property 不会有地方报（`E.run_experiment` 的
# `sleep` 就是这一格：主控放行、写 `running` 行、执行期才发现没人接）。判据（缺一条就退化成真空断言）：① 每个 property 要么被 handler 签名接受（具名形参或
# `inspect.Parameter.VAR_KEYWORD`），要么逐条登记在下面的接缝表里；② 不满足 ⇒ 导入即失败
# （`assert_capabilities` 第 [8] 条）；③ 接缝表里"现在不需要了"的条目也要报（同 `_KNOWN_UNMATCHED_ACTIONS` 的 stale）。
# 不删 `sleep`：删声明会让 `FakeE.run_experiment` 无法按同一份 schema 声明（`tests/test_conductor.py` /
# `tests/test_scheduler.py` 靠它控时序）；加没人读的具名 `sleep` 更坏 —— 把"传了但没看"变成静默成功。

#: 参数接缝表：`(角色, 动作, property 名)` -> 一行理由串。
#:
#: 一行 = 一个"声明里有、实现侧不收"的参数。写入这张表就是承认
#: "这一格参数门放行时实现会拒"，因此理由必须写清它只服务谁。
#: 键用三元组而不是动作名：同一个 property 名在不同动作上的性质可以完全不同
#: （`name` 在 `E.check_formal` 上是被实现接受的具名形参，在工具层却是会吞参数的
#: 撞名 —— `verify_tools.py` 里 `R2b-AN-1-C` 那一节逐字登记过这三层）。
PARAM_SEAMS: dict[tuple[str, str, str], str] = {
    ("E", "run_experiment", "sleep"): (
        "只服务替身/夹具，产品实现侧刻意不收。"
        "替身：`tests/test_conductor.py` 与 `tests/test_scheduler.py` 的 `FakeE.run_experiment` "
        "逐字声明了具名形参 `sleep`（用它控制'这次实验跑多久'，那些用例测的是并发/取消/串行时序），"
        "而它们经由 `Conductor.run_plan` → `summon` → 参数门，参数门读的就是本表的 `spec.params`。"
        "实现：`AgentE.run_experiment` 的签名里没有 `sleep`、也不收 "
        "`inspect.Parameter.VAR_KEYWORD`（实测，见 `tools/verify_tools.py` 的 `R2b-AN-1-C` 一节）。"
        "为什么不删声明：删了替身就得多传一个不在 schema 里的键，被测的就不再是那条真实链路"
        "（被否掉的 B 选项）。为什么不给实现加一个假形参：没人读它，等于把'我传了但它没看'"
        "变成静默成功（被否掉的 C 选项）。"
    ),
}


#: 参数交叉断言上一次的覆盖计数（由 :func:`assert_capabilities` 就地写）。
#:
#: 为什么是模块级字典而不是函数返回值：`assert_capabilities()` 的返回值被一条
#: 既有用例钉住必须是 `None`（`tests/test_r4_roles_surface.py`：默认档不许对
#: warning 级炸）。计数是读数，不是判据的输出 —— 判据仍然只返回 `None`。
#: 键：`roles` / `actions` / `declared` / `checked` / `seams`。
PARAM_ASSERT_COVERAGE: dict[str, int] = {}

#: 两层参数约束面对账上一次的覆盖计数（由 :func:`assert_capabilities` 第 [9] 条就地写）。
#: 键：`tools_read` / `tools_in_registry_modules` / `tools_unread` / `tools_read_but_not_registered` /
#: `modules_missing` / `compared` / `keys_compared` / `unread` / `tool_only_constraints` /
#: `registered_tool_only_constraints` / `keys_not_compared`。读它：
#: `python -c "import agentflow.capabilities as c; print(c.PARAM_TYPE_COVERAGE)"`。
#: 与 `PARAM_ASSERT_COVERAGE` 分开放：两条断言的覆盖率不是一回事
#: （那条数 property 名与实现签名，这条数"两层都给了约束的 (动作, property, 键) 三元组"）。
PARAM_TYPE_COVERAGE: dict[str, Any] = {}

#: 反向那一格（工具面有、动作面没有）的覆盖读数：与 `PARAM_TYPE_COVERAGE` 同一条理由 ——
#: 只在失败时说话的判据，成功时与"没跑"同形。读它：
#: `python -c "import agentflow.capabilities as c; print(c.PARAM_MISSING_IN_ACTION_COVERAGE)"`。
#: 这里刻意不放导入期断言（所有者 5b 授权的形态是"补反向 + 新计数并入读数"）；
#: 判据本体与登记表对账在 `tests/test_capabilities_reverse_param_gaps.py`。
PARAM_MISSING_IN_ACTION_COVERAGE: dict[str, Any] = {}

#: 反向的另一半（动作面有、工具面没有）的覆盖读数，由第 [10] 条就地写。
#: 键：`pairs_with_tool` / `unmatched` / `ambiguous` / `unreadable` / `gaps` / `registered`。
#: 三格分开数：只有 `pairs_with_tool` 那一格真的逐 property 比过；`unmatched`（整条动作
#: 没有工具层）与 `unreadable`（工具面读不出来）是 unknown，不许并进第一格。
PARAM_ACTION_ONLY_COVERAGE: dict[str, Any] = {}


def handler_accepted(role: str, action: str) -> tuple[frozenset[str], bool]:
    """取 `(角色, 动作)` 的实现侧参数面：`(具名参数集, 是否收 VAR_KEYWORD)`。

    具名参数集只算 `POSITIONAL_OR_KEYWORD` / `KEYWORD_ONLY` 两类 —— 它们是"按名
    传得进去"的全部形态。`VAR_POSITIONAL`（星号那一个）与 `POSITIONAL_ONLY` 都
    按名传不进去，所以不计入。第二个返回值是 `VAR_KEYWORD`（两个星号那一档）：
    收了它就等于"任何键都收得下"，此时交集判据按定义不适用（不是给它开例外）。

    实现类按 `schema.ROLES` 的命名约定取（:func:`_agent_class`），取不到时直接炸 ——
    "读不出实现"绝不允许折叠成"这一格没问题"（三态纪律）。
    """
    cls = _agent_class(role)
    spec = find_action(role, action)
    assert spec is not None, f"{role} 没有动作 {action} —— 参数面取自能力表，表里没有它就没有实现面可比"
    fn = getattr(cls, spec.handler_name)
    sig = inspect.signature(fn)
    named = frozenset(
        name for name, p in sig.parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    )
    accepts_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    return named, accepts_kw


def _param_seams(seams: Mapping[tuple[str, str, str], str] | None) -> dict[tuple[str, str, str], str]:
    """解析接缝表：`None` ⇒ 模块里那一份（与 `WRITE_SETS` 的注入形参同一形态）。"""
    return dict(PARAM_SEAMS if seams is None else seams)


def param_seam_violations(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    seams: Mapping[tuple[str, str, str], str] | None = None,
) -> list[tuple[str, str, list[str]]]:
    """声明了、实现不收、又没登记的 property ⇒ `[(角色, 动作, [property…])]`。

    这是 `D-2` 的判据本体（`assert_capabilities` 第 [8] 条读它）。返回空列表
    才是"查过了、干净"；判据是否真的遍历到了东西由 :func:`param_assert_coverage`
    的 `checked` 计数负责（P16：空集永远是子集，所以覆盖率必须另有读数）。

    两个形参只为让判据能被单独喂表（负控与单元测试用）：默认值 `None` 表示
    "读模块里那一份"，而模块里那一份仍然是导入期被核过的 —— 形参不构成第二条
    产生路径（`R4-4` 的教训：注入形参必须真的被读，不许是空转入口）。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    seam_table = _param_seams(seams)
    out: list[tuple[str, str, list[str]]] = []
    for role, specs in sorted(table.items()):
        for spec in specs:
            declared = set((spec.params.get("properties") or {}))
            if not declared:
                continue
            named, accepts_kw = handler_accepted(role, spec.action)
            if accepts_kw:
                continue
            missing = sorted(
                p for p in declared - named
                if (role, spec.action, p) not in seam_table
            )
            if missing:
                out.append((role, spec.action, missing))
    return out


def stale_param_seams(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    seams: Mapping[tuple[str, str, str], str] | None = None,
) -> list[tuple[str, str, str]]:
    """接缝表里"已经不需要了"的条目 ⇒ `[(角色, 动作, property)]`。

    两种"不需要"：动作或 property 在能力表里已经不存在（登记指向空气），
    或者那个 property 现在真的被实现接受了（接缝已闭合）。
    理由与 `_KNOWN_UNMATCHED_ACTIONS` 的 stale 那条一样：一张只增不减的登记表
    会烂成噪音，而噪音里的真违约就没人看了。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    seam_table = _param_seams(seams)
    stale: list[tuple[str, str, str]] = []
    for (role, action, prop) in sorted(seam_table):
        spec = next((s for s in table.get(role, ()) if s.action == action), None)
        if spec is None:
            stale.append((role, action, prop))
            continue
        declared = set((spec.params.get("properties") or {}))
        if prop not in declared:
            stale.append((role, action, prop))
            continue
        named, accepts_kw = handler_accepted(role, action)
        if accepts_kw or prop in named:
            stale.append((role, action, prop))
    return stale


def param_assert_coverage(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    seams: Mapping[tuple[str, str, str], str] | None = None,
) -> dict[str, int]:
    """参数交叉断言的覆盖读数（P16 的"判据接上了没有"那一栏）。

    `declared` = 能力表里声明的 property 总数；`checked` = 上面那条判据真的
    逐个看过的个数。两者必须相等 —— 断言里钉的是 `checked >= declared`：
    判据漏看任何一个 property，"零违反"就不构成证据。
    """
    table = CAPABILITIES if capabilities is None else capabilities
    seam_table = _param_seams(seams)
    roles = 0
    actions = 0
    declared = 0
    checked = 0
    for role, specs in sorted(table.items()):
        if not specs:
            continue
        roles += 1
        for spec in specs:
            actions += 1
            props = set((spec.params.get("properties") or {}))
            declared += len(props)
            named, accepts_kw = handler_accepted(role, spec.action)
            if accepts_kw:
                checked += len(props)
                continue
            checked += sum(
                1 for p in props
                if p in named or (role, spec.action, p) in seam_table
            )
    return {
        "roles": roles,
        "actions": actions,
        "declared": declared,
        "checked": checked,
        "seams": len(seam_table),
    }


def gate_params(
    spec: ActionSpec,
    *,
    accepted: frozenset[str] | None = None,
    accepts_kw: bool | None = None,
) -> dict:
    """参数门的口径：声明 ∩ 实现签名（`D-2` 第 3 条）。

    返回一份可以交给 `tools.base.validate_params` 的 schema：
    - `properties` = 声明里的 property ∩ handler 按名收得下的那些（收 `inspect.Parameter.VAR_KEYWORD`
      时交集就是声明本身）；
    - `required` = 声明里的必填 ∩ 剩下的 property。必填项落在交集之外是错误，不是"过滤掉"——
      静默丢掉一个必填项会把"必须给 claim"读成"可以不给"；
    - `additionalProperties` 原样保留（声明里是 `False` 时，实现侧独有的参数仍然进不来）。
    两个关键字形参是接缝表的入口：替身夹具的实现面由调用方给（`accepted` / `accepts_kw`），不给时按
    `spec` 的角色与动作从真实现读（`None` 与"空集"是两件事，默认值是 `None` 而不是 `frozenset()`）。
    它今天没有被 `Conductor._check_params` 调用（`conductor.py` 在本窗口禁改，而它的 `_check_params` 读的是 `spec.params`）；为什么可以不改，逐字写在 :func:`check_params` 的 docstring 里。
    """
    if accepted is None or accepts_kw is None:
        named, kw = handler_accepted(spec.role, spec.action)
        accepted = named if accepted is None else accepted
        accepts_kw = kw if accepts_kw is None else accepts_kw
    schema = dict(spec.params or {})
    props = dict(schema.get("properties") or {})
    required = list(schema.get("required") or [])
    if accepts_kw:
        return schema
    kept = {name: sub for name, sub in props.items() if name in accepted}
    dropped_required = sorted(set(required) - set(kept))
    assert not dropped_required, (
        f"{spec.role}.{spec.action} 的必填 property {dropped_required} 不在实现签名 "
        f"{sorted(accepted)} 里 —— 参数门不许把必填项静默过滤掉（那会把'必须给'读成'可以不给'）。"
        "要么改实现去接受它，要么把它从 required 里去掉并写明理由"
    )
    out = dict(schema)
    out["properties"] = kept
    out["required"] = [name for name in required if name in kept]
    return out


def check_params(spec: ActionSpec, params: Mapping[str, Any]) -> str | None:
    """按"声明 ∩ 实现签名"校验一次调用；返回错误说明或 `None`。

    形态与 `Conductor._check_params` 逐字同形（同一个判据、同一句话），好让那一处一行就能改成调它：
    `return C.check_params(spec, dict(params))`。
    ## 为什么这一版没有直接接进 `Conductor._check_params`：判据要区分"产品实现"与"替身夹具"的收参数面，而那个信息只存在于调用点（`_check_params(spec, params)` 只有两个入参，看不到 `self.backend` / `self.registry` 里挂着的是谁）。本窗口 `conductor.py` 是禁改文件，所以：
    - 产品路径的正确性今天由两个已有落点共同保证：① 本模块第 [8] 条导入期断言保证"声明里的每个
      property 要么被真实现接受、要么逐条登记"；② `LocalBackend.call` 在调 handler 之前已用
      `inspect.signature` 核过"实现不认这些参数"，不认就抛 `ParamError`（不会静默进 handler）；
    - 参数门提前拒绝（把 `failed` 变成 `refused`，不写 `running` 行）需要调用点把实现面传进来，
      那是一次 conductor 改动 ⇒ 已作为交接项写进交付，函数在这里备好（`gate_params` / `check_params`）。
    """
    try:
        from .tools.base import validate_params

        validate_params(gate_params(spec), dict(params))
    except Exception as e:  # noqa: BLE001 - ParamError 及子 schema 的错误都归为"这次没这么调"
        return f"{spec.role}.{spec.action} 的参数不合法：{e}"
    return None


# ---------------------------------------------------------------- 写集（表级）
#
# 证据栏里的每一行都是 `grep '\.tx\(|alloc_id\('` 的真实输出。
#    只登记写的表面（`tx("A","B")` ⇒ A 与 B），读的表不进写集。

#: 角色 -> 它可能写的表（表级粒度；见 DESIGN-CONDUCTOR.md §8 待决问题 3）。
#: 两条口径说的是两件事（主控裁决 3）：工具层的 `ToolSpec.side_effect` 描述"默认调用"的副作用
#: （`agent_c.gaps` 的 `submit_requests` 默认 `False` ⇒ 默认是纯读）；能力层的 `WRITE_SETS` 描述
#: "可能写"—— 条件性写也算可能写。所以 `WRITE_SETS["C"]` 必须包含 `search_requests`，而
#: `graph.gaps` 的 `side_effect` 不该改成 `write_local`（那会让 `ToolRegistry.for_role` 把这个工具
#: 从只读角色 C 的工具面里过滤掉）：修的是登记（`READ_ONLY_WRITE_EXCEPTIONS`），不是声明。
#: "第二个只读角色照抄这个模式"的隐患已被结构挡住：不登记 ⇒ `assert_capabilities()` 当场抛。
#: 真身是 `src/agentflow/specs/<角色>.py`（M3 起），这一行只做派生；`specs/` 在 `.noai-paths` 里受保护。
WRITE_SETS: dict[str, frozenset[str]] = _specs.write_sets()

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
    #   - `analysis_reports`（`AgentC.handle`）：它自己的产出登记行 ——
    #     这是"产出"，不是改世界。
    #   - `search_requests`（`AgentC.handle`，I3 缺口直连 A）：主控裁决的受控例外。
    #     判据三条：(1) 工具面仍然全量只读（`graph.gaps` 刻意不暴露该开关）；
    #     (2) 写的是过程记录（请求 A 去查），三张知识表零写入点；
    #     (3) 默认关闭，只能由编排层显式开启。移到编排层会多一跳、多一份失真。
    "C": frozenset({"analysis_reports", "search_requests"}),
    # H：写"审校发现"（review_findings）+ 只改 documents.status（`tools.review_tools` 的 writers）。
    # 为什么 H 可以写这两张而不是"违反只读"：H 的工具箱是纯只读的
    # （`AgentH.install_h_tools` 的装配期断言），写只发生在一个被钉死的 `writers` 注册表里，
    # 而它的落点只有这两个 —— 于是"发现问题"与"改稿内容"在结构上仍然分得开：
    # H 能改的只有状态与自己的发现，改不了任何一句断言。
    "H": frozenset({"review_findings", "documents"}),
}

#: 逐工具写集：只读例外里每个工具会写哪几张表（`roles-2` 判据 ② / ③ 的输入）。
#: 为什么需要它（以及为什么它不是"第二份名单"）：`WRITE_SETS` 是角色级、`READ_ONLY_WRITE_EXCEPTIONS`
#: 是表级、`READONLY_CALL_EXCEPTIONS` 是工具级，三者原本没有任何机器判据相连 ⇒ 往工具级表加一个
#: 能写 `claims` 的工具，工具层会放行、表级例外不认，什么都不红。
#: 现在是显式逐工具登记 + 三条机器判据（全部在 `assert_capabilities` 的 `[5c]` 里）：① 本表覆盖
#: `READONLY_CALL_EXCEPTIONS` 里的每个工具 · ② 本表[tool] == `_tool_write_set_from_source(tool)`
#: （`R4-5` 补：登记值写错必须看得见）· ③ 本表[tool] ⊆ `READ_ONLY_WRITE_EXCEPTIONS[role]`；外加
#: "本表里没有已经不存在的工具"。四个方向（漏登记/多登记/值与实现不符/写越界）都堵住；证据栏用符号名，写不出证据的行不许留。
TOOL_WRITE_SETS: dict[str, frozenset[str]] = {
    "review.review_document": frozenset({"review_findings", "documents"}),
    #   ↑ `review_tools.review_document`：`tx.upsert("review_findings", …)` 落 finding，
    #     并调 `_set_doc_status`（`store.tx("documents")` + `tx.upsert("documents", …)`）
    #     把 documents.status 置 in_review/accepted。`R4-6`：此处原先用
    #     `review_tools.py` 的 274 / 296 两个行号当证据，实测那两行是无关代码
    #     （274 是一条 finding 的字典字面量、296 是 `seen_ids[cid] = text`）。
    "review.verify_fixes": frozenset({"review_findings", "documents"}),
    #   ↑ `review_tools.verify_fixes`：`_apply_finding_status` 改 finding 的
    #     status/resolution_note，`_set_doc_status` 把文档置 unresolved_review
    "review.report": frozenset(),
    #   ↑ `review_tools.review_report`：只写一个 markdown 报告文件（`draft/17` §8.4），
    #     它对 `review_findings` 只读（`store.rows(...)`），`store.tx` 一次都没出现
    "review.record_finding": frozenset({"review_findings"}),
    #   ↑ `review_tools.record_finding`（业主 2026-10-18）：H 自己读出来的发现在这里落库。
    #     只写 `review_findings`（`tx.upsert("review_findings", …)`），不碰
    #     `documents` —— 改状态是裁决那一档（`review_document` / `verify_fixes`）的事。
    #     这一条是可以被 AST 算出来的（`tools/review_tools.py` 里有同名顶层函数），
    #     所以它走的是 ②′ 的逐格相等判据，而不是 `_NO_WRITE_SET_SOURCE` 那一档。
    "analysis.register_report": frozenset({"analysis_reports"}),
    #   ↑ `analysis_tools` 的产出登记通道（C 的）：写发生在
    #     `agent_c._support.AnalysisReport.persist()`（`st.tx("analysis_reports")` +
    #     `tx.upsert`），工具层只是把那条路暴露给 C 自己 ⇒ 跨模块调用，扫描器
    #     （只跟同文件顶层函数）算不出来，已登记进 `_NO_WRITE_SET_SOURCE`。
    #     登记值 `{analysis_reports}` 同时受两条判据守着：③ 的子集检查（越界即红）
    #     与 `tests/test_readonly_output_channel.py` 的行为读数（调用一次，除
    #     `analysis_reports` 外所有表的行数不变）。
}


# ---------------------------------------------------------------- 允许的召唤边

#: 谁能召唤谁（DESIGN-CONDUCTOR.md §3.1，逐字实现）。
#:
#: 两条刻意设计的边：
#: - `C` 的边是空的：C 一旦能发起动作，它就成了"绕过 B 引文回验"的写入路径。
#:   C 的 `candidate_gaps` / `structural_duplicates` 是产出，由 D 或编排层
#:   决定要不要变成请求。
#: - `H` 能召唤 `A` / `E` / `G`（不是只有 `G`）：`H → A` 与 `H → E` 两条边
#:   2026-09-30 由人批准加入（`draft/28` §199），用途是"引文对不上就找 A 核实原文、
#:   断言能不能形式化就找 E"。审校者依然不能改数据，但那条约束的真身是
#:   "H 的工具面 0 个写工具"（schema.H 的装配期断言），不是"H 没有向外的边"——
#:   把这两件事混成一句会让人以为 `H → A`/`H → E` 不存在（本行 2026-10-06 更正）。
#: 真身是 `src/agentflow/specs/<角色>.py`（M3 起）。这一行只做派生 —— 
#: 也就是说改权限面要改 `specs/`，而 `specs/` 在 `.noai-paths` 里受保护。
ALLOWED_EDGES: dict[str, frozenset[str]] = _specs.edges()

#: 没人能召唤主控（没有"召唤 M"这件事）。用一张显式的集合表达，
#: 而不是靠"ALLOWED_EDGES 里没人把 M 写进值里"这个偶然事实 ——
#: 后者会在有人给别的角色加一条 `→ M` 的边时静默失效（那条边会合法化）。
#: 真身是 `src/agentflow/specs/<角色>.py`（M3 起）。这一行只做派生 —— 
#: 也就是说改权限面要改 `specs/`，而 `specs/` 在 `.noai-paths` 里受保护。
NON_SUMMONABLE: frozenset[str] = _specs.non_summonable()


def registry():
    """内置角色的声明注册表（`specs/` 是它的真身；懒取一次）。

    为什么放在 `capabilities` 而不是让每个调用方自己 `builtin_registry()`：
    这一层是"权限面的读法"——查动作、查边、查写集都从这里出发，
    于是"临时角色能不能被闸门认出来"只取决于有没有把注册表传下去这一件事。
    """
    global _REGISTRY
    if _REGISTRY is None:
        from .agentspec import builtin_registry

        _REGISTRY = builtin_registry()
    return _REGISTRY


#: `registry()` 的缓存（`goal-7f5116c1` M5）。`None` = 还没取过。
_REGISTRY: Any = None


def actions_for(role: str, *, registry: Any = None) -> tuple[ActionSpec, ...]:
    """某角色的动作表。未知角色返回空元组（由 policy 判 unknown_role，这里不抛）。

    给了 `registry` 就从它读（`M5`：临时角色走这条）；否则读内置那份。
    """
    if registry is not None:
        try:
            return tuple(registry.get(role).actions)
        except KeyError:
            return ()
    return CAPABILITIES.get(role, ())


def find_action(role: str, action: str, *, registry: Any = None) -> ActionSpec | None:
    """查一个动作。找不到返回 `None` —— 三态纪律：调用方必须区分
    "角色不存在"（`role not in CAPABILITIES`）与"角色存在但没这个动作"，
    这两者对应 `unknown_role` / `unknown_action` 两个不同的拒绝理由。"""
    for spec in actions_for(role, registry=registry):
        if spec.action == action:
            return spec
    return None


def roles_in(registry: Any = None) -> tuple[str, ...]:
    """角色名单（`None` ⇒ 内置那份；`M5` 起闸门用这个，而不是写死 `schema.ROLES`）。"""
    if registry is not None:
        return tuple(registry.roles())
    return (*S.ROLES, S.CONDUCTOR_ROLE)


def edges_for(role: str, *, registry: Any = None) -> frozenset[str]:
    """某角色能召唤谁（`None` ⇒ 内置那份）。"""
    if registry is not None:
        try:
            return frozenset(registry.get(role).edges)
        except KeyError:
            return frozenset()
    return ALLOWED_EDGES.get(role, frozenset())


def _write_calls_in(node: ast.AST) -> set[str]:
    """一个函数体里"写入某张表"的字面量（`tx.upsert(...)` 这一族）。

    只认写方法，不认读方法 —— 这是它与被删掉的第一版 `_tables_written_by_action` 的第一处区别（`R4-3` / `R4-5`）：
    - 写：`upsert` / `append` / `insert_unique` / `mark_dirty`（`mark_dirty` 是"就地改过"的显式
      声明，它一定导致这张表被写回）；
    - 不写：`rows` / `find` / `store.tx(...)` 本身 / `store.rows(...)`。
    把 `store.tx("documents", ...)` 也算成写，会把"为了读快照而声明的表"算进来（`WRITE_SETS["D"]`
    的注释记的正是这个形态：D 的 `relations` 是读）。
    接收者必须叫 `tx`（`store.tx(...)` 返回的事务对象）：`tool_tools` 里满地是 `found.append("…")` /
    `reasons.append("…")` 这类列表 append，只看方法名会把中文提示语当成表名（实测：`verify_fixes`
    第一次跑就"算出"了 `documents`、`review_findings` 加两条中文消息）。
    """
    write_methods = {"upsert", "append", "insert_unique", "mark_dirty"}
    found: set[str] = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        fn = sub.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in write_methods:
            continue
        if not (isinstance(fn.value, ast.Name) and fn.value.id == "tx"):
            continue
        if not sub.args:
            continue
        first = sub.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
    return found


def _tool_write_set_from_source(tool: str) -> frozenset[str] | None:
    """工具名 → 它的 handler 链真正写入的表名（AST 实证，第 `[5c]` 条 ② 的输入）。

    ## 为什么需要它（`R4-5`：判据 ② 原先只保证"解析到一个动作"）：② 原来止步于"这个只读例外工具
    能在能力表里解析到一个 `ActionSpec`"，而"它到底写哪几张表"没有机器判据比对 ⇒ 实测把
    `TOOL_WRITE_SETS['review.review_document']` 改成空集，`assert_capabilities()` 照样通过。
    本函数把那一半接上：从工具自己的实现里算出写集，再与登记值逐个比。
    ## 与第一版那个零调用点的 `_tables_written_by_action` 的区别（`R4-3`）：第一版扫的是
    `ActionSpec.handler_name` 那一层函数体里字面出现过的表名（不分读写、不跟调用），实测接近真空：
    `review.verify_fixes` 只算出 `{review_findings}`，而 `documents` 是它调用的 `_set_doc_status`
    写的 ⇒ 永远报不出"越权写 documents"。三处不同，都是为了"真的会红"：
    1. 只认写方法字面量（`_write_calls_in`），读不算；
    2. 沿同一文件里的顶层函数调用做闭包（`_set_doc_status` 这类下层写入点会被走到），不只一层；
    3. 它真的被调用（见 `assert_capabilities` 的 ②），算不出来时返回 `None` —— 调用方必须显式登记到
       `_NO_WRITE_SET_SOURCE`，不许静默跳过。
    返回值：`frozenset` = 算出来的写集；`None` = 算不出（`<前缀>_tools.py` 不在盘上、函数名找不到、
    或文件读不了）。`None` 绝不是空集：前者是"没查成"，后者是"查过了、不写表"。
    """
    prefix, _, func = str(tool).rpartition(".")
    if not prefix or not func:
        return None
    p = Path(__file__).resolve().parent / "tools" / f"{prefix}_tools.py"
    if not p.is_file():
        return None
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    funcs = {n.name: n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    # 工具名 -> 函数名：先找同名的，再退一步找以 `_<末段>` 结尾的
    # （`review.report` 的实现函数叫 `review_report`，不是 `report` ——
    #  这一条是实测出来的：只按同名找会让 review.report 直接算不出）。
    # 候选不唯一时返回 None（交给 _NO_WRITE_SET_SOURCE 显式登记），
    # 不猜、不取并集：猜出来的写集拿去比对只会制造假红或假绿。
    if func in funcs:
        entry = func
    else:
        cands = [n for n in funcs if n.endswith("_" + func)]
        if len(cands) != 1:
            return None
        entry = cands[0]
    seen: set[str] = set()
    stack = [entry]
    tables: set[str] = set()
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        node = funcs.get(name)
        if node is None:
            continue
        tables |= _write_calls_in(node)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id in funcs:
                stack.append(sub.id)
    return frozenset(tables)


#: 算不出写集的例外工具（工具名 -> 为什么算不出）。
#: 今天是空的：`TOOL_WRITE_SETS` 里的三个工具都在 `tools/review_tools.py` 里
#: 有同名顶层函数，`_tool_write_set_from_source` 三个都算得出来。
#: 留着这张表是因为"算不出"必须是显式登记的一格，而不是静默跳过 ——
#: 静默跳过会让将来新加的工具全部落在判据之外，而门照样绿（`P16`）。
_NO_WRITE_SET_SOURCE: dict[str, str] = {
    "analysis.register_report": (
        "写发生在 `agent_c._support.AnalysisReport.persist()`（C 落盘的**唯一**实现："
        "`st.tx(\"analysis_reports\")` + `tx.alloc_id` + `tx.upsert`），工具层只负责把"
        "那条路暴露给 C 自己 —— 跨模块调用，而扫描器只跟**同文件**的顶层函数调用链，"
        "所以算不出来。为什么不去 `tools/analysis_tools.py` 里重写一遍落盘：那会立刻产生"
        "第二份'怎么存一份报告'的口径（文件名 / 号段 / 文件与登记行的先后顺序），"
        "而两份口径漂开的那一天，`reports/<rid>-<kind>.md` 与表里的 `markdown_path` 就"
        "对不上了（FC-03 的同族）。登记值 `{'analysis_reports'}` 由 ③ 的子集检查与"
        "`tests/test_readonly_output_channel.py` 的行为读数（调用一次后除 "
        "`analysis_reports` 外所有表行数不变）共同守着"
    ),
}


def _h_writable_tools_is_derived() -> bool:
    """`agent_h._H_WRITABLE_TOOLS` 是否从只读例外表派生（`G-45` 那一类）。

    用 AST 而不是字符串匹配：一条 `_H_WRITABLE_TOOLS = (...)` 的字面量元组与一条
    从 `READONLY_CALL_EXCEPTIONS["H"]` 派生的切片，在源码里长得很像，
    而只有后者会随表变化。判据是右侧不是字面量容器（`ast.Tuple`/`ast.List`/
    `ast.Set`），且模块里出现了 `READONLY_CALL_EXCEPTIONS` 这个名字。
    """
    p = Path(__file__).resolve().parent / "agent_h" / "_support.py"
    if not p.is_file():  # pragma: no cover - 未拆包时的落点（`goal-7f5116c1` M7 之前）
        p = Path(__file__).resolve().parent / "agent_h.py"
    if not p.is_file():  # pragma: no cover - 文件不在就说明装配方式变了
        return False
    text = p.read_text(encoding="utf-8")
    if "READONLY_CALL_EXCEPTIONS" not in text:
        return False
    tree = ast.parse(text)
    for node in ast.walk(tree):
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            #  实测形态是带注解的：`_H_WRITABLE_TOOLS: tuple[str, ...] = tuple(...)`。
            # 第一版只认 `ast.Assign`，于是这条断言在真树上永远返回 False
            # （一个恒假的判据比没有判据更糟：它看起来在守着，其实什么都没守）。
            targets, value = [node.target], node.value
        if any(isinstance(t, ast.Name) and t.id == "_H_WRITABLE_TOOLS" for t in targets):
            # 派生的形态：右侧是 `READONLY_CALL_EXCEPTIONS[...]`（Subscript）或对它的
            # 推导/拼接 —— 一律不是裸的字面量容器。
            return not isinstance(value, (ast.Tuple, ast.List, ast.Set))
    return False


@dataclass(frozen=True)
class EmptyWriteSet:
    """一个"空写集"角色在并发轴上的含义（`:data:`EMPTY_WRITE_SETS` 的值类型）。

    `concurrent=True` = 真·空集：它不写任何表，因此与任何角色的表写集都不冲突
    （V 的台账是文件）。`concurrent=False` = 空写集只是"没有逐表声明"，并发上必须
    当它可能写任何表（M 的召唤会写 `tasks`，派生的子任务可能写任何东西）。

    为什么用一个具名类型而不是 `tuple[bool, str]`：调用点要能读成
    `entry.concurrent` / `entry.why`，而不是 `entry[0]` —— 后者在半年后没人能读。
    """

    concurrent: bool
    why: str


#: 空写集的两种含义（CS-14：这一格此前是折平的）。`WRITE_SETS[role] == frozenset()` 有两个完全不同的来源：M（它的召唤本身会写 `tasks`，而且派生的
#: 子任务可能写任何东西 ⇒ 并发上必须与任何人串行，理由逐字写在 `specs/m.py` 的写集声明里）；V（它的
#: 台账是一个文件 `verifications/<4 位>.jsonl`、也没有子代理 ⇒ 与任何人的表写集都不冲突，是真·空集）。
#: 折平的后果（本批现算）：`write_set_of("V")` 返回全部 16 张表 —— 与"完全不认识的执行单元"
#: （`write_set_of("Z")`）和 M 一模一样 ⇒ V 真跑起来，写集轴（`write_sets_intersect` / `policy` 的波次 /
#: `scheduler` 的 `write_set` 读数）把它当成"能写全部表"的角色。
#: 为什么在这里而不在各角色 spec 里：写集轴的口径只有一处（`write_set_of`），含义表必须与它同址；
#: 反真空由 `assert_capabilities` 的 [6b] 段守着：空写集角色必须登记、且不许留下过期名字。
EMPTY_WRITE_SETS: dict[str, "EmptyWriteSet"] = {
    "M": EmptyWriteSet(
        concurrent=False,
        why="召唤本身会写 tasks，且它派生的子任务可能写任何东西 ⇒ 并发上与任何人串行",
    ),
    "V": EmptyWriteSet(
        concurrent=True,
        why="台账是文件（verifications/<4 位>.jsonl）、没有子代理 ⇒ 真·空集，"
            "与任何人的表写集都不冲突",
    ),
    # 2026-10-22 第二批：L 从这张表里删除（它此前在这里，理由是"一张表都不写"）。
    # 业主第二句施工单给了它一格写集（`experiments`：`formal.record` 落一行形式化
    # 实验行）⇒ 它的写集不再是空集，本表里的那一行按 [6b] 的"登记不许留过期名字"
    # 必须同时删掉（否则 `import agentflow.capabilities` 当场炸，而那正是 [6b] 想挡的：
    # 读的人会以为 L 仍是真空集）。并发含义随之由 `WRITE_SETS["L"]` 现算：
    # 只与同样写 `experiments` 的角色（E）相交 ⇒ 与 E 串行，与其余角色可并发。
}


def write_set_of(role: str) -> frozenset[str]:
    """某角色的写集。

    ## 三态（这一格此前只有两态，CS-14）
    1. 有写集 ⇒ 用它；
    2. 空写集且在这里登记过并发含义 ⇒ 按 `EMPTY_WRITE_SETS` 走（M 串行 / V 真·空集）；
    3. 空写集但没登记，或者角色根本不在 `WRITE_SETS` 里 ⇒ 全部表。
    第 3 档是原有语义，一字未改：空集意味着"它什么都不写，可以和任何人并发"，那是最危险的方向
    （一个不认识的执行单元被当成了只读）⇒ "不知道 ⇒ 保守"，而保守 = 与所有人串行。
    新增的是第 2 档：同一个空集不许再折平两种含义。"没有表写集"（V：写的是文件）与"不写任何表"
    （M：因为可能写任何表，所以按全表算）不是一件事 —— 折成同一个返回值，读的人就再也分不开了。
    """
    ws = WRITE_SETS.get(role)
    if ws:
        return ws
    entry = EMPTY_WRITE_SETS.get(role) if ws is not None else None
    if entry is None:
        return _ALL_TABLES
    return frozenset() if entry.concurrent else _ALL_TABLES


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


#: 台账审计里用到的码。与 `verify.verify_all` 里 tasks 那段逐字一致（判据
#: `tests/test_conductor.py::test_task_ledger_audit_critical_codes_match_verify_all`），外加本模块
#: 特有的码：`task_terminal_without_end` / `task_running_without_start` / `task_terminal_rewritten` /
#: `task_refused_without_reason` / `task_refusal_reason_on_non_refusal` / `task_root_depth_not_one`。
#: 实现放在这里是因为 `verify_all`（全库离线审计）与 `Conductor.verify_tasks`（即时自检）问的是同一个
#: 问题"这批 tasks 行自洽吗"，各写一份必然漂移，而漂移的形态是"其中一处永远说没问题"—— 审计最坏
#: 的失效方式。`verify_tasks` 调这一份（`Conductor.task_issues()`）；`verify.py` 是禁改区、保留自己的
#: `Issue` 包装，码集合相等由一致性测试钉住（"不许只写注释说两处应一致"：注释不会变红，测试会）。
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
        （`verify.verify_all` 里 `task_still_running` 那条的原话："verify 是离线跑的，所以任何仍在 running
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

        # ---- artifacts：两种形态都要认（`draft/28` §161 的 R-58）
        #   ① 行引用 `table:id`（本表原来的口径）；
        #   ② 文件型产物 `file:<工作区相对路径>`，或直接给一个工作区内存在的相对路径。
        # 第二种是 R-47/R-52 逼出来的：产出摘要落成文件后，`artifacts` 里出现的是路径，
        # 而这条判据原来只认表名 ⇒ 每一次有产出的召唤都报一条 `unknown_artifact_kind`
        # （实测 p2-review 上 61 条，而 `verify.py` 里那份副本改成认路径之后，
        # 这里仍在报 —— 同一判据两份实现的典型形态）。
        # 三态：显式 `file:` 却找不到 ⇒ error（登记了产出却不在）；裸路径找不到 ⇒
        # 仍报 `unknown_artifact_kind`（可能只是形态写错，不该判成"文件被删"）。
        root = Path(getattr(store, "root", ".") or ".")
        for a in r.get("artifacts") or []:
            kind, _, ref = str(a).partition(":")
            if kind in S.TABLES:
                idf = S.TABLES[kind]["id_field"]
                if not any(str(x.get(idf)) == ref for x in store.rows(kind)):
                    out.append(TaskIssue("dangling_task_artifact", "error", tid,
                                         f"artifacts 指向不存在的行：{a!r}"))
                continue
            rel = ref if kind == "file" else str(a)
            candidate = root / rel
            try:
                inside = candidate.resolve().is_relative_to(root.resolve())
            except (OSError, ValueError):
                inside = False
            if inside and candidate.is_file():
                continue
            if kind == "file":
                out.append(TaskIssue("dangling_task_artifact", "error", tid,
                                     f"artifacts 里的文件型产物不存在：{a!r}"))
            else:
                out.append(TaskIssue("unknown_artifact_kind", "warning", tid,
                                     f"artifacts 里的 {a!r} 既不是表名，"
                                     "也不是工作区内存在的相对路径"))
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


def assert_capabilities(
    *,
    write_sets: Mapping[str, frozenset[str]] | None = None,
    read_only_write_exceptions: Mapping[str, frozenset[str]] | None = None,
) -> None:
    """装配期自检（fail-closed）。任何一条不成立就抛 `AssertionError`。

    八条断言各对应一次真实踩过的坑族（两个注入形参只为让第 `[5c]` 条 `roles-2` 能在进程内做负控 —— 实测先撞上第 `[4]`/`[6]` 条，那两条比它更早看到同一张表）：
    1. 键集合 == `schema.ROLES`：两个模块各写一份角色名单 ⇒ "schema 认为合法、编排层不认"（FC-03）。
    2. `handler_name` 真的存在且可调用：编造动作名会让主控把任务派给不存在的落点，直到运行时才发现（或被 `getattr(obj, name, None)` 静默吞掉）。
    3. `(role, action)` 不重复：同名动作下 `find_action` 返回哪一个取决于元组顺序 —— "取决于声明顺序"的行为。
    4. 只读角色的写集例外必须显式登记，见 `READ_ONLY_WRITE_EXCEPTIONS`。
    5. 副作用词表只有一份（`set(SIDE_EFFECTS) == set(tools.base.SIDE_EFFECTS)`），外加两根轴各自的同一形态断言；两处字面量分叉会让"有副作用"在两套口径下不同，而它不会报错。
    6. 写集非空 ⇒ 该角色的效果轴里必须有 `_WRITE_LIKE` 的动作（P-13 §3.4 断言一）。
    7. 两层声明的不一致可判定（见 `declaration_divergences`）：error 级任何时候都在导入期断言，warning 级只在 `STRICT_DECLARATIONS=True` 时升级；外加第 [7b] 条 —— 对账面必须是一个分区（`compared` / `unmatched` / `ambiguous` 三格互斥且穷尽，`compared` 非空、`ambiguous` 为空）。
    8. 参数门是"声明 ∩ 实现签名"：每个 property 要么被对应 handler 的签名接受（具名形参，或收 `inspect.Parameter.VAR_KEYWORD`），要么逐条登记在 `PARAM_SEAMS` 里 —— `Conductor._check_params` 那处放行、执行期才炸（`E.run_experiment` 的 `sleep` 就是这一格），与 `tools` 侧注册期的同族断言（`tools.base` 的接缝表 + `ToolRegistry.register`）是同一机制在两层的落点。
    第 [7] 条只钉 `unmatched`（`_KNOWN_UNMATCHED_ACTIONS`），`ambiguous` 那一格今天恰好是 0 却不在任何登记表 ⇒ 可以静默长大（`G-19` 的同族形态）。
    三态纪律（`R4-4` 实测的修法）：`write_sets` 形参曾空转 —— `_ws = dict(write_sets) …` 之后从未被读，第 [1]/[4]/[6] 条仍读模块全局 `WRITE_SETS`，于是 `assert_capabilities(write_sets={…})` 看起来在拿替身跑判据、实际什么都没换（把 `C.WRITE_SETS` 整个清空后断言照样通过）；现在 `_ws` / `_rowe` 在函数最前解析一次，第 [1]/[4]/[6] 与 `[5c]` 全读它们 —— 要么形参真的生效，要么它不存在，不许"看起来生效"。
    两个注入形参让调用方（只有测试）换掉那两张表；生产路径不传 ⇒ 与加形参之前逐字相同。默认值 `None` 意味着"用模块里那一份"（模块那份仍是导入期被核过的），形态照抄 `_matching_tool_name(spec, tools)`。
    """
    # ---- [1] 角色名单只有一份
    #
    # `R4-4`：两张可注入的表在这里就解析出来，之后每一条断言都读 `_ws` / `_rowe`。
    # 解析放在最前面（而不是原来的第 `[5c]` 之前）的理由：第 [1] 条自己就读写集，
    # 而注入形参若在那里读不到、只有 `[5c]` 读得到，那这条注入仍然是半空转的。
    _ws = dict(write_sets) if write_sets is not None else dict(WRITE_SETS)
    _rowe = (dict(read_only_write_exceptions) if read_only_write_exceptions is not None
             else dict(READ_ONLY_WRITE_EXCEPTIONS))
    missing = set(S.ROLES) - set(CAPABILITIES)
    extra = set(CAPABILITIES) - set(S.ROLES) - {S.CONDUCTOR_ROLE}
    assert not missing, f"CAPABILITIES 缺少角色 {sorted(missing)}（判据是 schema.ROLES，不许另写名单）"
    assert not extra, f"CAPABILITIES 含 schema.ROLES 之外的角色 {sorted(extra)}"
    assert set(_ws) == set(S.ROLES) | {S.CONDUCTOR_ROLE}, (
        f"WRITE_SETS 的键必须与 schema.ROLES + CONDUCTOR_ROLE 一致，"
        f"多 {sorted(set(_ws) - set(S.ROLES) - {S.CONDUCTOR_ROLE})}，"
        f"少 {sorted(set(S.ROLES) | {S.CONDUCTOR_ROLE} - set(_ws))}"
    )
    assert set(ALLOWED_EDGES) >= set(S.ROLES), f"ALLOWED_EDGES 缺少角色 {sorted(set(S.ROLES) - set(ALLOWED_EDGES))}"
    # `FINAL-R4-01`：上面那一条只核键集（"每个角色都有出边条目"），不核值 —— 漏掉一个角色时它照样过。
    # 这里守住"主控到底能不能够到每一个角色"。判据形态在 2026-10-10（第 146 轮第 4 条裁定）换过一次：
    # 改前是 `ALLOWED_EDGES["M"] == frozenset(S.ROLES)`；改后按业主裁定「M 的出边设限（不许直接控制
    # B、F、V，只可间接由父代理转达）」⇒ 那条等式按定义不再成立，换成下面 `_INDIRECT_FROM_M` 那段的三条判据。
    # 为什么不是"把等式右边改成 `set(S.ROLES) - {B,F,V}`"：那等于把裁定抄成第二份字面量，声明层
    # （`specs/m.py`）一改它就跟着漂，而它自己说不出"少了哪条链就不对"。
    # 位置刻意放在下面那个逐条循环之后：先让"含非角色目标"那条判据对 `{"agent-A"}` 这类拼错说话
    # （`test_unknown_edge_target_is_rejected` 逐字匹配那句消息），本条只在"目标都是合法角色名、但漏了一个"时承担判据。
    for frm, tos in ALLOWED_EDGES.items():
        bad_targets = sorted(set(tos) - set(S.ROLES))
        assert not bad_targets, f"ALLOWED_EDGES[{frm!r}] 含非角色目标 {bad_targets}（拼法必须与 schema.ROLES 一致）"
        # `FINAL-R4-05`：下面这一条在今天的 schema 下不可达 —— `NON_SUMMONABLE`
        # 只含 `CONDUCTOR_ROLE`，而它不在 `S.ROLES` 里，所以任何指向 M 的边都会先被
        # 上面那条"含非角色目标"命中。保留它是为了"将来 NON_SUMMONABLE 里放进一个
        # 合法角色"时仍有人守着（实测：把 NON_SUMMONABLE 换成合法角色后这条会红），
        # 但顺序必须写在这里，免得读的人以为它今天在承重。
        assert not (set(tos) & NON_SUMMONABLE), (
            f"ALLOWED_EDGES[{frm!r}] 允许召唤这些不可召唤的角色 {sorted(set(tos) & NON_SUMMONABLE)} —— "
            "没有『召唤主控』这件事，它只能由用户/调用方驱动"
        )
    # ---- [1b] 主控的出边：三条判据（2026-10-10 第 146 轮第 4 条裁定）
    # 裁定的内容是一条"间接"要求：主控不许直接控制的角色只可间接由父代理转达。三处可判，缺一条就有
    # 一种坏法看不见：① 直接边不许含受限集合（`_INDIRECT_FROM_M`）⇒ 裁定本身；② 这些角色各自要有别的
    # 进路 ⇒ 否则成孤儿（键集判据与 ① 都看不见）；③ 从主控出发在边图上可达每一个角色 ⇒ 换掉旧等式
    # （`ALLOWED_EDGES["M"] == frozenset(S.ROLES)`）之后"够不到某个角色"仍有人守。
    # 角色名在这里是判据的一部分（判据必须能独立说出"哪一条不对"），它们不是边表的第二份定义 —— 边表
    # 真身是 `specs/m.py` 的 `edges`。历次业主裁定：2026-10-13「补 M 到 B」· 2026-10-18「给 M 开 V 出边」·
    # 2026-10-20「撤掉 M→V」⇒ 今天的受限集合是 {F, V}（V 走 `M→B→V` 两跳）。
    _INDIRECT_FROM_M = frozenset({"F", "V"})
    _m_edges = frozenset(ALLOWED_EDGES.get(S.CONDUCTOR_ROLE) or ())
    assert not (_m_edges & _INDIRECT_FROM_M), (
        f"ALLOWED_EDGES[{S.CONDUCTOR_ROLE!r}] 含 {sorted(_m_edges & _INDIRECT_FROM_M)}："
        "F 按 2026-10-10 的裁定只能间接由父代理转达（F 走 D）——"
        "主控直接派它仍是被明确设限的那一件事"
        "（B 已于 2026-10-13、V 已于 2026-10-18 由业主加回，见 `specs/m.py`）"
    )
    for _role in sorted(_INDIRECT_FROM_M):
        _inbound = sorted(frm for frm, tos in ALLOWED_EDGES.items()
                          if _role in tos and frm != S.CONDUCTOR_ROLE)
        assert _inbound, (
            f"{_role} 既不能被主控直接召唤、又没有别的父代理进路 ⇒ 这个角色成了孤儿"
            "（裁定要的是『间接转达』，不是『谁都派不动』）"
        )
    # 2026-10-22（业主施工单：新设 L，且明确要求"协作面不搭"）：可召唤性在这里
    # 第一次与可达性分开。`NON_SUMMONABLE` 里的角色按定义就不该被召唤 ——
    # 要求它从主控出发可达，等价于要求"每一个不可召唤的角色都必须有一条进路"，
    # 而那是一个自相矛盾的要求；L 正是第一个合法地"不可召唤且没有边"的角色
    # （它只能由用户直接用 `run-agent L` 起，与主控 M 的处境相同）。
    # 判据强度不放：可召唤的角色仍然必须全部可达（`_unreachable` 那一行原样保留）。
    _reachable = set(_m_edges)
    while True:
        _grew = {t for frm in _reachable for t in ALLOWED_EDGES.get(frm, ())} - _reachable
        if not _grew:
            break
        _reachable |= _grew
    _unreachable = sorted((set(S.ROLES) - set(NON_SUMMONABLE)) - _reachable)
    assert not _unreachable, (
        f"从 {S.CONDUCTOR_ROLE} 出发在边图上到不了这些角色（可召唤的那一批）：{_unreachable} —— "
        "它们永远不会被召唤（改前那条『出边恰好等于 schema.ROLES』守的就是这件事）。"
        f"不可召唤的 {sorted(set(NON_SUMMONABLE))} 不在这条判据的射程里："
        "它们按定义就不该被召唤，要求它们可达是自相矛盾的"
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
        ws = _ws.get(role, frozenset())
        allowed = _rowe.get(role, frozenset())
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

    # ---- [5c] 只读例外的两张表必须由机器判据相连（`roles-2`）
    # 缺陷：只读角色能写哪些表有两个可各自漂移的落点 —— 工具级 `tools.base.READONLY_CALL_EXCEPTIONS` 与
    # 表级本模块的 `READ_ONLY_WRITE_EXCEPTIONS`；`capabilities.py` 全文不出现前者，对应关系只写在自然
    # 语言理由里 ⇒ 往工具级表加一个能写 `claims` 的工具不会触发任何断言（这正是 `.noai-paths` 给 FC-27
    # 第七类写的"测试全绿、上线即越权"的破口形态）。判据（三条）：① 两个例外表的键集必须相同；② 每个例外工具必须能在能力表里解析到一个动作
    # （`matching_tool_name`），否则"比不了"必须显式登记 —— 不许静默跳过（`P16`：真空通过 = 缺陷）；
    # ③ 解析到的动作能写哪些表必须是表级例外的子集。已知边界：`review.review_document` 无对应
    # `ActionSpec`，走 ② 的登记支 ⇒ "它只写这两张表"仍只由人写的理由保证（`draft/28` 的 `roles-2`）。
    from .tools import READ_ONLY_ROLES
    from .tools.base import READONLY_CALL_EXCEPTIONS

    assert set(READONLY_CALL_EXCEPTIONS) <= set(_rowe), (
        f"工具级例外表里的角色 {sorted(set(READONLY_CALL_EXCEPTIONS) - set(_rowe))} "
        "在表级例外表 `READ_ONLY_WRITE_EXCEPTIONS` 里没有登记 —— 只读角色能写哪些表"
        "有两个落点，两处必须成对出现"
    )
    assert set(READONLY_CALL_EXCEPTIONS) <= set(READ_ONLY_ROLES), (
        f"`READONLY_CALL_EXCEPTIONS` 的键 {sorted(set(READONLY_CALL_EXCEPTIONS))} 不在只读角色 "
        f"{sorted(READ_ONLY_ROLES)} 里 —— 例外表只对只读角色有意义"
    )
    _NO_ACTION_YET = {
        # 工具名 -> 为什么今天解析不到动作（写不出理由的，就应该去补 ActionSpec）
        "review.review_document": (
            "能力表里 H 的 action 只有 review / verify_fixes / list_findings，"
            "没有 `review_document`；它的写集今天只由 `READ_ONLY_WRITE_EXCEPTIONS` 的理由保证"
        ),
        "review.record_finding": (
            "业主 2026-10-18 新增的产出登记通道：能力表里 H 的动作仍只有 "
            "review / verify_fixes / list_findings / review_report（工具名最后一段 "
            "`record_finding` 与任何 `handler_name` 都不相同）⇒ 唯一性约定对不上。"
            "它的写集（`{review_findings}`）仍然由 ③ 的子集检查与 ②′ 的 AST 比对守着 "
            "—— `tools/review_tools.py` 里有同名顶层函数 `record_finding`。"
            "要不要把它升成 H 的一个动作，是「H 的动作面该不该多一格」的设计判断，"
            "留给下一次人审（这一改已经动了权限面）"
        ),
        "analysis.register_report": (
            "业主 2026-10-18 新增的产出登记通道：能力表里 C 的动作是 "
            "hottest/paths/cold/gaps/handle/… —— 没有哪一个的 `handler_name` 叫 `register_report`"
            "⇒ 唯一性约定对不上。它的写集登记值（`{analysis_reports}`）由 ③ 的子集检查"
            "（C 的表级例外含 `analysis_reports`）与行为读数守着；"
            "要不要把它写成 C 的 `ActionSpec`（从而被编排层按动作派活）是设计判断，"
            "留给下一次人审"
        ),
        "review.report": (
            "H.review_report 的 handler_name 与工具名最后一段不同名（工具名 `review.report` "
            "的最后一段是 `report`）⇒ 唯一性约定对不上，它今天仍然落在 unmatched 这一格，"
            "已登记进 `_KNOWN_UNMATCHED_ACTIONS`。实测 "
            "`matching_tool_name(find_action('H', 'review_report'))` 返回 None "
            "⇒ 下面 ② 那一步走的是本登记这一支：这个工具的两层口径今天没有被机器比过。"
            "另：它只写一个 markdown 报告文件、不碰任何数据表（`READONLY_CALL_EXCEPTIONS` 里的"
            "理由逐字写了这一点），所以 `TOOL_WRITE_SETS['review.report'] == frozenset()`、"
            "没有表要比对。第 [7c] 条那条反方向断言已被撤回（见本文件"
            "『[7c] 撤回的判据』一节），今天守『例外表里的工具必须有动作』的是"
            "第 [5c] 条 ② 与第 [7] 条的 `new_unmatched` 断言。"
        ),
    }
    _covered: set[str] = set()
    for _role, _entries in READONLY_CALL_EXCEPTIONS.items():
        _allowed = set(_rowe.get(_role, frozenset()))
        for _tool, _why in _entries:
            # ③ 逐工具写集：先要求"有登记"，再比子集 —— 缺登记 ⇒ 这条例外是空头支票
            assert _tool in TOOL_WRITE_SETS, (
                f"只读例外 {_role}.{_tool} 在 `TOOL_WRITE_SETS` 里没有逐工具写集登记 ⇒ "
                "「它会写哪几张表」没有被任何判据比对。请登记它（带 `文件:行号` 证据）"
            )
            _covered.add(_tool)
            _writes = set(TOOL_WRITE_SETS[_tool])
            _over = _writes - _allowed
            assert not _over, (
                f"只读例外 {_role}.{_tool} 的写集是 {sorted(_writes)}，其中 "
                f"{sorted(_over)} 不在 `READ_ONLY_WRITE_EXCEPTIONS[{_role!r}]`"
                f"（= {sorted(_allowed)}）里 ⇒ **只读角色越权写表**。"
                "要么把这张表登记进表级例外（并写清为什么只读角色能写它），"
                "要么这个工具不该进 `READONLY_CALL_EXCEPTIONS`"
            )
            # ② 能力动作这一格：能解析就解析，解析不到必须显式登记（不许静默跳过）
            _matched = [s for s in actions_for(_role) if matching_tool_name(s) == _tool]
            if not _matched:
                assert _tool in _NO_ACTION_YET, (
                    f"只读例外 {_role}.{_tool} 在能力表里解析不到动作 ⇒ 这一格"
                    "**没被任何判据比对**。要么给它补一个 `ActionSpec`，要么把它登记进 "
                    "`_NO_ACTION_YET` 并写明为什么今天比不了（不许静默跳过）"
                )
            # ②′ 写集比对（`R4-5` 的修法）：登记值必须等于从工具实现里算出来的写集。
            #
            # 为什么必须有这一条：② 原来止步于"能解析到一个动作"，而
            # "那个动作到底写哪几张表"没有任何机器判据 ⇒ 实测把
            # `TOOL_WRITE_SETS['review.review_document']` 改成空集（真实写集非空）
            # 仍能通过。③ 只能挡住"多写一张不在表级例外里的表"，挡不住
            # "把真实写集改成空集/少写一张"这类"漏报"方向。
            #
            # 三态：算得出 ⇒ 必须逐个相等；算不出 ⇒ 必须显式登记在
            # `_NO_WRITE_SET_SOURCE` 里并写明为什么（今天它是空的）。
            _from_src = _tool_write_set_from_source(_tool)
            if _from_src is None:
                assert _tool in _NO_WRITE_SET_SOURCE, (
                    f"只读例外 {_role}.{_tool} 的写集**算不出来**（`tools/{_tool.split('.')[0]}_tools.py` "
                    f"里找不到名为 {_tool.split('.')[-1]!r} 的顶层函数，或文件读不了）⇒ 这一格"
                    "没被任何判据比对。要么让工具名与实现文件名/函数名对上，要么把它登记进 "
                    "`_NO_WRITE_SET_SOURCE` 并写明为什么算不出（不许静默跳过）"
                )
            else:
                _declared = set(TOOL_WRITE_SETS[_tool])
                assert _declared == set(_from_src), (
                    f"只读例外 {_role}.{_tool} 的逐工具写集登记与实现不符："
                    f"`TOOL_WRITE_SETS` 写的是 {sorted(_declared)}，而 "
                    f"`_tool_write_set_from_source({_tool!r})` 从 "
                    f"`tools/{_tool.split('.')[0]}_tools.py` 的 "
                    f"{_tool.split('.')[-1]!r} 及其同文件调用链里算出来的是 "
                    f"{sorted(_from_src)}（只认 tx.upsert / tx.append / "
                    "tx.insert_unique / tx.mark_dirty 的写调用）。"
                    "差集：多登记 "
                    f"{sorted(_declared - set(_from_src))}、漏登记 "
                    f"{sorted(set(_from_src) - _declared)}。登记值与实现必须一起改 —— "
                    "写多了会让只读角色看起来能改它其实碰不到的表，"
                    "写少了则是**漏报**方向：越权写表再也不会有判据看得见（`R4-5`）"
                )
    # ③ 的另一半：`TOOL_WRITE_SETS` 不许留下已经不存在的工具（登记表要自我清理）
    _stale = sorted(set(TOOL_WRITE_SETS) - _covered)
    assert not _stale, (
        f"`TOOL_WRITE_SETS` 里这些工具已经不在 `READONLY_CALL_EXCEPTIONS` 里了：{_stale} ⇒ "
        "请删掉它们，否则这张表会烂成噪音（而噪音比没有判据更糟：它会训练人忽略告警）"
    )
    # 反向守卫：例外工具的名字不许在别的文件里被复述成第二份字面量（`G-45` 那一类）。
    # `agent_h._H_WRITABLE_TOOLS` 曾经是同一件事的第二份名字，现在从本表派生；
    # 这里用 AST 钉住它是派生而不是字面量（写在别处的一份名单不会触发任何断言）。
    assert _h_writable_tools_is_derived(), (
        "`src/agentflow/agent_h.py` 的 `_H_WRITABLE_TOOLS` 不再是**从只读例外表派生**的 —— "
        "它成了同一件事的第二份名字（改一处、另一处不动的形态）。"
        "请让它继续写成 `READONLY_CALL_EXCEPTIONS[...]` 的派生式"
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
    for role, ws in _ws.items():
        unexplained = set(ws) - set(_rowe.get(role, frozenset()))
        if not unexplained:
            continue
        axes = [effect_axis_of(s) for s in actions_for(role)]
        assert any(a in _WRITE_LIKE for a in axes), (
            f"WRITE_SETS[{role!r}]={sorted(unexplained)} 非空（已减掉已登记的只读例外），"
            f"但该角色没有任何效果轴为 {_WRITE_LIKE} 的动作（实测轴值：{sorted(set(axes)) or '（无动作）'}）"
            "—— 写集说它会写表，效果轴说它不写：这两个判据不许分叉"
        )

    # ---- [6b] 空写集角色的并发含义必须登记（CS-14 的反真空，两个方向都查）
    #
    # 为什么必须有这一条：`write_set_of` 的第 2 档只在"这个空写集角色登记过"时才生效，
    # 没登记就退回第 3 档（全部表 ⇒ 与所有人串行）。那个退回是保守的，所以不会有
    # 数据被改坏 —— 但它会把"新加了一个空写集角色、忘了写它的并发含义"这件事静默吃掉，
    # 而返回值看不出来（还是全部表）。两个方向都要红：漏登记、以及登记表里留下
    # 已经不是空写集的名字（后者会让读的人以为那个角色仍是空写集）。
    _empty_roles = sorted(r for r, ws in _ws.items() if not ws)
    _unregistered = [r for r in _empty_roles if r not in EMPTY_WRITE_SETS]
    assert not _unregistered, (
        f"这些角色的写集是空集，却没有在 `EMPTY_WRITE_SETS` 里登记并发含义：{_unregistered} ⇒ "
        "`write_set_of` 会把它们当成'可能写任何表'（保守，但没有读数能说明这是有意的）。"
        "补一行：`concurrent=True`（真·空集：它不写表，与任何人可并发）或 "
        "`concurrent=False`（空写集只是'没有逐表声明'，并发上当它写任何表）。"
    )
    _stale_empty = sorted(set(EMPTY_WRITE_SETS) - set(_empty_roles))
    assert not _stale_empty, (
        f"`EMPTY_WRITE_SETS` 里这些名字的写集已经不是空集了：{_stale_empty} ⇒ "
        "登记表要自我清理，否则读的人会以为那个角色仍是空写集"
    )

    # ---- [7] 两层声明的对账：不许静默地少比对
    #
    # P-13 §10 第 3 条实测：`verify.check_formal` 工具层 `read` / 能力层 `network`，
    # 而没有任何机器判据看见过。本轮的处置是"先让它可见"（:func:`declaration_divergences`），
    # 不是"导入期炸" —— 真实树上现在就有两条，做成 AssertionError 会让
    # `import agentflow.capabilities` 永久失败，把既有第 1–5 条断言一起废掉。
    #
    # 所以这一档分两级（口径同 :func:`declaration_divergences` 的说明）：
    #   - error 级在这里无条件断言（"能力层低估了风险轴"是缺陷，没有商量余地）；
    #   - warning 级默认只报告，`STRICT_DECLARATIONS=True` 时才由下面那一支断言
    #     （`R4-AN-3`：那一支此前是 `pass`，这个开关是空转的）。
    divergences = declaration_divergences()
    hard = [d for d in divergences if d.level == "error"]
    assert not hard, (
        "两层声明不一致（能力层低估了风险轴）："
        + "；".join(f"{d.where}: {d.message}" for d in hard)
    )
    if STRICT_DECLARATIONS:
        # `R4-AN-3`：这一支此前是 `pass` —— 一个空转开关。docstring 承诺"True 时把
        # warning 也升成导入期断言"，而实现什么都不做；照文档打开它的人以为多了一道门。
        # 现在真做：warning 级不一致在 True 档按导入期断言处理（默认档仍然只报告）。
        # 今天真实树的 warning 数是 0，所以打开它不会让 `import agentflow.capabilities` 失败。
        soft = [d for d in divergences if d.level == "warning"]
        assert not soft, (
            "STRICT_DECLARATIONS=True：两层声明的 warning 级不一致也按导入期断言处理"
            "（默认只报告，理由见本函数第 [7] 条与模块末尾 STRICT_DECLARATIONS 的说明）："
            + "；".join(f"{d.where}: {d.message}" for d in soft)
        )

    # 实测的窟窿（`D-9` 更正，观测时刻 2026-09-26 18:5x）：33 条不一致全部是"没有比对"
    # （`two_layer_name_unmatched`，两个层的名字对不上 ⇒ 三态里的 unknown），warning 0、error 0 ⇒ 上面
    # 那道 error 断言今天是真空的，门看起来接上了、实际只比对了 1 个动作。这不是"再严一点"能解决的：
    # 那些动作本来就不是工具调用（`C.hottest` / `D.ingest` 是角色级方法），两层没有可比对的对象。
    # 这个数字怎么来的（不许手抄）：`len(two_layer_reconciliation()['unmatched'])` 等于
    # `_KNOWN_UNMATCHED_ACTIONS` 的条数，第 [7] 条的两条断言（new_unmatched 与 stale 都为空）钉着这个
    # 相等 —— 手抄的数字会过期（此前写 32，`D-5` 加一个动作后漂到 33），等式不会。
    # 所以这里钉的是对账面不许静默缩小（P16 族）：① 新出现的"没比对"必须显式登记（否则导入失败）；② 登记表里"已经对上了"的必须删掉（否则登记表变成噪音，慢慢就没人看）。
    unmatched = {d.where for d in divergences if d.code == "two_layer_name_unmatched"}
    new_unmatched = sorted(unmatched - _KNOWN_UNMATCHED_ACTIONS)
    assert not new_unmatched, (
        "出现了新的『两层没有比对』的动作 ⇒ 对账面在缩小，而它是 P7/FC-03 的判据面："
        f"{new_unmatched}。若它确实不是工具调用，请登记进 `_KNOWN_UNMATCHED_ACTIONS` 并写明理由。"
    )
    stale = sorted(_KNOWN_UNMATCHED_ACTIONS - unmatched)
    assert not stale, (
        "这些动作以前『没比对』、现在对上了 —— 是好事，但请把它们从 "
        f"`_KNOWN_UNMATCHED_ACTIONS` 里删掉，否则登记表会烂成噪音：{stale}"
    )

    # ---- [7b] 对账面必须是一个分区（D-3）
    #
    # 上面那条只钉 `unmatched`。实测（2026-10-03 加 `G.paper_package` 之后；该动作 2026-10-13 退场）：
    # 55 个动作 = 18 compared + 37 unmatched + 0 ambiguous
    # （2026-10-02 是 53 = 18 + 35 + 0；2026-09-30 加 `A.search_literature` 之后是 51 = 17 + 34 + 0）。
    # 于是 `ambiguous` 那一格今天恰好是 0，
    # 而没有任何判据看着它 —— 若将来一个动作的 handler_name 在角色工具组里
    # 撞上两个工具，`declaration_divergences()` 只会多一条 info，导入照样成功，
    # 对账面就此静默缩小。这正是 G-19（门接上了但只比对了 1 个动作）的同族形态，
    # 所以这里钉的不再是"某个数字"，而是三格互斥且穷尽这个结构本身：
    # 它自我维护（不钉 48 / 16 / 32），任何一格变了都必然在某处报出来。
    recon = two_layer_reconciliation()
    compared, amb, un = recon["compared"], recon["ambiguous"], recon["unmatched"]
    assert len(compared) + len(amb) + len(un) == recon["total"], (
        f"两层对账面不是分区：{len(compared)} compared + {len(amb)} ambiguous + "
        f"{len(un)} unmatched != {recon['total']} 个动作 ⇒ 判据本身漏了动作"
    )
    assert not (set(x for x, _ in compared) & set(un)) and not (set(x for x, _ in compared) & set(amb)) \
        and not (set(un) & set(amb)), (
        "两层对账面三格相交 ⇒ 同一个动作被数进两格（分区判据的前提被破坏）"
    )
    assert compared, (
        "两层比对一条都没做成 ⇒ 对账面是空的，而门会显示为通过（G-19）"
    )
    assert not amb, (
        "出现了『两层名字对不上唯一一个工具』的动作（歧义）⇒ 那一条**没有比对**，"
        "而对账面正在静默缩小。`_KNOWN_UNMATCHED_ACTIONS` 只管 unmatched，管不住这一格："
        f"{amb}。要么修 `_TOOL_GROUPS_BY_ROLE` / 工具名，要么显式登记它并写明理由。"
    )

    # ---- [7c] 撤回的判据（记在这里，免得下一个人再写一遍）
    # 原本这里有一条"反方向"断言：只读例外表里的每个工具，要么在能力表里解析到一个动作，要么在
    # `_NO_ACTION_YET` 里登记。负控证明它是真空的 —— 第 [5c] 条的 ② 已经在同一个循环、同一张表上做了
    # 同一件事而且先跑 ⇒ 能走到这里的工具必然"解析不到但不在登记表里"，而那正是 [5c] 已判红的形态，
    # 构造不出只有 [7c] 能抓的输入。一条抓不到任何东西的断言比没有断言更坏：它会让读的人以为这一格被守住了。
    # `D-5` 的根除靠两件真的会红的事：① `H.review_report` 补进 `CAPABILITIES['H']` +
    # `_KNOWN_UNMATCHED_ACTIONS`；② 第 [7] 条的 `new_unmatched` 断言 —— 加了动作却忘了同步登记 ⇒
    # `import agentflow.capabilities` 当场炸（负控 `temp/batchM-verify.py`）。

    # ---- [8] 参数门：声明 ∩ 实现签名（`D-2` / `R2-AN-1` 的 capabilities 半边）
    #
    # 这一条补的是"参数门被绕过"那一格：声明里多一个 property 而实现不收，
    # 此前没有任何判据看得见 —— 主控放行、写 `running` 行、执行期才发现没人接。
    # 判据的三态见 `PARAM_SEAMS` 上面那一段；这里落三件事，顺序即优先级：
    #   ① 违反（声明了、实现不收、又没登记）⇒ 出错信息逐字给出 角色/能力/property；
    #   ② 接缝表里已经不需要的条目 ⇒ 也报（登记表不许烂成噪音）；
    #   ③ 覆盖读数 ⇒ `checked >= declared`（判据漏看任何一个 property，
    #      "零违反"就不构成证据 —— P16 的真空通过）。
    # ①② 必须先跑：它们的失败信息里带着具体的 property 名，而 ③ 的信息只说
    # "漏看了几个"；反过来报的话，一次真实的表内违约会被读成"扫描器坏了"。
    bad_params = param_seam_violations()
    coverage = param_assert_coverage()
    PARAM_ASSERT_COVERAGE.clear()
    PARAM_ASSERT_COVERAGE.update(coverage)
    assert not bad_params, (
        "以下 property 声明在能力表里、而对应实现（inspect.signature）不收，"
        "又没有登记进 PARAM_SEAMS："
        + "；".join(f"{role}.{action} 的 {props}" for role, action, props in bad_params)
        + "。危害是静默的：参数门（Conductor._check_params）读的就是这张表，"
        "它会放行 ⇒ 写一行 running ⇒ 执行期才报『不认这些参数』，"
        "台账里那一行看起来像跑失败了，其实这次调用从来没被执行过。"
        "两条出路（二选一，不许留第三态）：① 改实现去接受它；"
        "② 登记进 PARAM_SEAMS 并逐字写明理由（它只服务谁 / 为什么实现侧刻意不收）。"
    )
    stale_seams = stale_param_seams()
    assert not stale_seams, (
        f"这些接缝登记现在已经不需要了：{stale_seams} —— 那个 property 要么已被实现接受，"
        "要么在能力表里已经不存在。请把它们从 PARAM_SEAMS 里删掉，"
        "否则登记表会烂成噪音，噪音里的真违约就没人看了（`_KNOWN_UNMATCHED_ACTIONS` 的同族纪律）"
    )
    assert coverage["checked"] >= coverage["declared"], (
        f"参数交叉断言只覆盖了 {coverage['checked']} 个 property，而能力表里声明了 "
        f"{coverage['declared']} 个 ⇒ 判据没走遍全部声明，'零违反'此时不构成证据。"
        "这一条排在前面两条之后：前两条是『表里有问题』，这一条是『判据自己没走遍』，"
        "两条的修法完全不同，报出来要能一眼分开"
    )

    # ---- [9] 两层参数对账（`R-36`；2026-10-22 扩表：比的是约束面，不是只有 type）
    #
    # R-36（`draft/28` §150.5）：上面的 [8] 只比 property 名与实现签名，不比类型；
    # [7] 只比两根轴。于是"两层对同一个参数声明的边界不一致"这一整类缺陷
    # 没有任何机器判据 —— §150 那三处（`H.review` / `H.verify_fixes` 的
    # `dependencies` 声明成 `_OBJ`、`H.review_report` 声明成 `_ARR_S`，工具层四条
    # 一直是 array-of-objects）就是它漏的。
    # 2026-10-22（审计 D-1/2/3/6/7）：只比 `type` / `items.type` 仍然漏一整族 ——
    # `G.write_mapping` 的 `rows`（工具面 `minItems=1` ＋ 每行必填六格）、`project`
    # （`minLength=1/maxLength=300`）、`V.verify_proof` 的 `proof_no`（`minimum=1`）
    # 三处真实分歧，`param_type_divergences()` 当时返回 `[]`。现在比
    # `_PARAM_CONSTRAINT_KEYS` 那十格，并且 `_module_constants` 会解析嵌套 `items` 里的
    # 常量名（`doc_tools._MAPPING_ROW_PARAMS`）—— 那条 array 以前连"两侧都有 items.type"
    # 这个前提都不成立，于是被"一侧只写 `{type:array}`"的豁免连判都没判就放过。
    #
    # 为什么不一致是 error 而不是 warning：参数门读能力表、工具层校验读工具表，
    # 两层不一致的后果不是崩溃而是判错（合法派活被判死，或必然被拒的形状被放行），
    # 与 [7] 的"能力层低估风险轴"同一档：错了不吵，静默地错。
    type_coverage = param_type_coverage()
    PARAM_TYPE_COVERAGE.clear()
    PARAM_TYPE_COVERAGE.update(type_coverage)
    type_divergences = param_type_divergences()
    assert not type_divergences, (
        "两层对同一个参数声明的边界不一致（能力层是派活的契约、工具层是校验的真身）："
        + "；".join(f"[{d.code}] {d.where}: {d.message}" for d in type_divergences)
    )
    assert not type_coverage["unread"], (
        "这些动作的唯一匹配工具，其 `params` 约束面读不出来（不是字面量，例如 "
        f"`params=some_variable`）：{type_coverage['unread']}。"
        "读不出来的工具在这条判据里是 unknown，而 unknown 多了以后『零分歧』"
        "就不再是证据（P16 真空通过）。两条出路：① 把 `params` 写成字面量 "
        "（这是判据能看见它的唯一形态，与 `_declared_side_effects` 同一套读源码口径）；"
        "② 若确实做不到，请把这条动作登记进一张显式表并写明理由 —— "
        "不许让它静默地落在判据外。"
    )
    assert type_coverage["compared"] > 0 and type_coverage["keys_compared"] > 0, (
        "两层参数对账一对都没比过（compared / keys_compared 至少一个为 0）——"
        "这不可能来自'两层都没声明约束'"
        "（能力表声明了 "
        f"{PARAM_ASSERT_COVERAGE.get('declared', 0)} 个 property，工具表也有各自的 schema），"
        "只可能来自判据自身失效（例如 `_tool_param_faces()` 读不到任何工具模块）。"
        "零分歧此时不构成证据"
    )
    # [9b] 工具面独有约束的两向对拍（`_KNOWN_TOOL_ONLY_CONSTRAINTS`）。
    #
    # 扩表之后一次咬出 13 对 21 个键：`specs/g.py` / `specs/v.py` 里的六对本次直接补齐
    # （工具层是真身），剩下七对落在 `specs/c.py` / `e.py` / `f.py` / `h.py`，逐条登记。
    # 两个方向都要断言：新长出来的不对称 ⇒ 红（否则登记表会变成万能豁免）；
    # 补齐了却没删登记 ⇒ 也红（否则登记表会烂成噪音，而噪音里的真缺口没人看）。
    unregistered_constraints = unregistered_tool_only_constraints()
    assert not unregistered_constraints, (
        "出现了没登记的工具面独有约束（工具面给了边界、动作面只写了类型）⇒ 派活面比校验面松："
        + "；".join(unregistered_constraints)
        + "。两条出路：① 把动作面补齐到与工具面同界（`specs/*.py`，禁改区、要人审）；"
        "② 登记进 `_KNOWN_TOOL_ONLY_CONSTRAINTS` 并写明为什么不改"
    )
    stale_constraints = stale_tool_only_constraint_entries()
    assert not stale_constraints, (
        f"这些约束不对称已经不在了，登记却没有删：{stale_constraints} —— 登记表必须自我清理，"
        "否则它会烂成噪音，而噪音里的真缺口就没人看了"
    )
    # [9c] "参数真身在工具层"的那几对：逐键对拍（`_PARAMS_DERIVED_FROM_TOOL`）。
    #
    # 为什么它必须与 [9] 分开： [9] 只看"未登记的约束不对称"，而这一条管的是
    # "这几对的真身被点名写在工具层" —— 派生面读不出来（unknown）在这里也是红，
    # 而在 [9] 里那只是"没比对"。2026-10-22 业主裁定：这三处的真身在工具层，
    # 改工具层的 `minItems` / `minimum` 而不改动作面 ⇒ 这里当场红（不是两份手抄碰巧相同）。
    derivation_violations = param_derivation_violations()
    assert not derivation_violations, (
        "登记为『参数真身在工具层』的那几对，动作面与工具层不再逐键相等："
        + "；".join(derivation_violations)
        + "。处置：改动作面去跟工具层（真身），不许反过来把工具面放宽 ——"
        "工具面是 `validate_params` 真正读的那一份"
    )

    # [10] 反向那一格的读数（工具面有、动作面没有）。只读数、不断言 —— 所有者 5b 授权的
    # 就是这一形状；牙在那条测试里（`_KNOWN_TOOL_ONLY_PARAMS` 与实测逐条对账 + 过期检测）。
    # `_KNOWN_ACTION_ONLY_PARAMS`（动作面独有参数）同样只在这里留读数，牙在
    # `tests/test_two_layer_constraints_really_match.py`：它的第 ③ 条要求
    # "没有工具层的那一对，登记集合 == 动作面声明的集合"，那是这一族唯一的牙。
    reverse_coverage = param_missing_in_action_coverage()
    PARAM_MISSING_IN_ACTION_COVERAGE.clear()
    PARAM_MISSING_IN_ACTION_COVERAGE.update(reverse_coverage)
    action_only_coverage = param_missing_in_tools_coverage()
    PARAM_ACTION_ONLY_COVERAGE.clear()
    PARAM_ACTION_ONLY_COVERAGE.update(action_only_coverage)


#: 实测的"两层没有可比对对象"的动作（`two_layer_name_unmatched`）。这张表只管 `unmatched` 这一格
#: （`handler_name` 在角色工具组里对应 0 个工具）；另一格 `ambiguous`（对应 ≥2 个工具 ⇒ 拒绝猜）不由
#: 它管，而由第 [7b] 条的分区断言管（三格互斥且穷尽 + `ambiguous` 必须为空）—— 那一格今天实测是 0，正因为它不在任何登记表里，"它悄悄长大"就没有任何地方会报。
#: 为什么必须显式登记：不加这张表时第 [7] 条只过滤 `level == "error"`，而真实树上 error 数为 0 ⇒
#: 那道断言恒真（`G-19`：门接上了，但只比对了 1 个动作）。有了它，新加一个对不上的动作会让
#: `import agentflow.capabilities` 失败，而不是悄悄多一条 info。
#: 这些动作绝大多数是角色级方法（`C.hottest` / `D.ingest` / `H.review`），不是工具调用 ⇒ 两层本来
#: 就无可比对 —— 这一栏记录的是"没查成"，不是"查过了没问题"。
_KNOWN_UNMATCHED_ACTIONS: frozenset[str] = frozenset({
    "A.run_once", "A.run",
    "B.run_once", "B.reprocess_once", "B.run_reprocess",
    "B.decide_structural_duplicate", "B.resolve_structural_duplicate",
    "C.hottest", "C.paths", "C.cold", "C.gaps", "C.contradictions",
    "C.structural_duplicates", "C.handle",
    # 2026-10-09（业主：「想想C怎么找最短依赖链？……B走乙。由于B这边出了多依赖写法，
    # C的分析需要做适配」）：`proof_chain` 是角色级只读方法（读 `statements` +
    # `dependencies` 现算，零模型调用、不落库），工具层没有同名工具 ⇒ 两层无可比对。
    "C.proof_chain",
    "D.probe_c", "D.ingest", "D.ingest_detailed", "D.trace_question", "D.trace_l3",
    "D.assess", "D.submit_gaps", "D.consider", "D.poll", "D.adjudicate",
    "D.research", "D.run_round", "D.write_report",
    # `draft/37` §115：从零做研究时"立起第一行问题"的通路 —— 它只写
    # `research_questions` 一行，工具层没有同名工具（不是转发，也没有对应的 tool 调用）。
    "D.propose_question",
    # 2026-10-26（第 ④ 条根因）：`register_conjecture` 此前被算成"已对上"，
    # 而它对应的 `conjecture.register_conjecture` 不在 `tools._MODULES` 里
    # （`build_registry` 装配不到那个模块，D 走 `agent_d._support` 的直接 import）
    # ⇒ 工具面上没有它，模型驱动模式下 D 喊短名只会拿到"并列候选 0 个"。
    # 现在"对得上"的判据改成装配面（`_candidates` 的 `_ASSEMBLED_GROUPS` 过滤），
    # 于是它诚实地落进"没有工具层"这一格 —— `agent_loop._own_actions_to_expose`
    # 据此把 `own.register_conjecture` 注入这一趟的工具面。
    # 为什么不选另一条路（把 `conjecture_tools` 加进 `tools._MODULES`）：那会改变
    # 广告出去的整份工具面（`tests/golden/tool_surface_snapshot.json` 里每个角色的
    # 工具清单都会多一件），而"不重冻 golden"是本批的硬边界；而且那件工具的
    # `roles` / 依赖装配也都要一起接进来，改动的面比这条判据大。
    "D.register_conjecture",
    "E.run_script_experiment",
    "G.render", "G.refresh_markdown", "G.revise",
    "H.review",
    # 2026-10-14（业主：「允许 B 和 H 协作，B 唤起 H」+「回验……保持语义相同即可」）：
    # `judge_quote_semantics` 是 H 的角色级只读方法（`agent_h/judge_quote_semantics.py`：
    # 把材料喂给 `judges.quote_semantics_judge_for` 的缝，判完把结论交回调用方，
    # 不碰任何表 —— H 的落库代理仍钉死在 review_findings/documents 上）。
    # 工具层没有同名工具（它不是转发，也不该是：塞进 `quoteverify.check_quote`
    # 会让"引文级证据"的口径取决于模型），所以它诚实地落进 unmatched 这一格。
    "H.judge_quote_semantics",
    # `D-5`：`review_report` 转发 `review.report`，而工具名的最后一段是 `report`、
    # 本动作的 `handler_name` 是 `review_report` ⇒ `_matching_tool_name` 对不上
    # （唯一性约定要求逐字同名），于是它诚实地落进 `unmatched` 这一格。
    # 它不是工具调用（是 H 自己的方法），所以登记在这里而不是改工具名：
    # 改工具名会同时动 `READONLY_CALL_EXCEPTIONS` / `TOOL_WRITE_SETS` /
    # `agent_h` 的 writer 名单，而那是权限面的改动。
    "H.review_report",
    # `A.search_literature`（2026-09-30）：A 的角色级动作，不是工具调用。工具组里
    # A 的那几条名字是 `search.providers` / `search.literature` / `search.download` /
    # `search.dedup_check` / `search.ingest_local` / `search.register` ——
    # 没有一条的最后一段是 `search_literature`，所以按唯一性约定它诚实地落进 `unmatched`。
    # （为什么不叫 `search`：那样会与 `fs.search` / `table.search` 撞成 `ambiguous`，
    # 而导入期第 [7b] 条要求 `ambiguous` 为空 —— 实测过。）
    # 为什么不给它凑一个同名工具：`search.literature` 只做"查一次"，而本动作是
    # "入队（过 I7 准入闸门）→ 领跑（领取/租约/退避/判重/下载/落库）→ 交回来源"，
    # 把两者配成一对会让两层类型对账去比两件不同的事（比 `search.literature` 的
    # `limit` 与本动作的参数），那种"比上了"比诚实的"没比对"更坏。
    "A.search_literature",
    # `B.register_statement`（2026-10-02，`draft/37` §46）：B 的角色级动作，
    # 不是工具调用。它写的是通用表工具 `table.create(table="statements")` ——
    # 工具名的最后一段是 `create`，与 `handler_name` 对不上（唯一性约定要求逐字同名）。
    # 为什么不给它凑一个同名工具：`table.create` 是通用表操作（A–D 都能调、
    # 任何表都能建），而本动作是"命题台账那一行的三件套预检 + 出处核验 + 取号"——
    # 把两者配成一对会让两层类型对账去比两件不同的事（比 `table.create` 的
    # `table`/`row` 与本动作的 `statement_full`），那种"比上了"比诚实的"没比对"更坏。
    # 与 `A.search_literature` / `H.review_report` 两条同族。
    "B.register_statement",
    # 2026-10-13：`G.paper_package` 已从这里拿掉（业主裁定「paper_package 里那些东西都是
    # 古早废案了，我们要智能体写文章」）—— 动作本身、它的三个工具与渲染锚那一格一起退场，
    # 所以"这一格没比对上"的登记也不再需要它。退场面与理由见 `draft/117`。
    # `A.shelf_search`（2026-10-06，J-53 / 裁决 2 族 1）：A 的角色级动作，不是工具调用。
    # 它调的是 `search.shelf` / `search.local`，两件工具名的最后一段是 `shelf` / `local`
    # ⇒ 与 `handler_name`（`shelf_search`）对不上（唯一性约定要求逐字同名）。
    # 为什么不给它凑一个同名工具：那两件是通用只读检索（A/C/H 都能调），而本动作是
    # "先列书架清单、再按需取逐字摘录"的一次编排 —— 配成一对会让两层类型对账去比
    # 两件不同的事。与 `A.search_literature` / `B.register_statement` / `G.paper_package`
    # / `H.review_report` 四条同族：诚实地登记"这一格没比对上"。
    "A.shelf_search",
})


#: 两层声明不一致要不要在导入期炸。默认 False，理由见 :func:`assert_capabilities`
#: 第 7 条：真实树上现有的不一致（`E.check_formal` 与 `H.review` 一类）是
#: B3 的迁移对象，现在炸等于把整仓的导入期断言一次性废掉。
#:
#: `R4-AN-3` 更正：它此前只被一句 `if STRICT_DECLARATIONS: pass` 读着 —— 一个
#: 空转开关（docstring 承诺"True 时把 warning 升成导入期断言"，实现什么都不做）。
#: 现在 [7] 里这一档真的断言 warning；error 级则与开关无关，任何时候都在导入期断言。
#: 今天真实树的 warning 数是 0，所以把它翻成 True 不会让导入失败。
STRICT_DECLARATIONS: bool = False


#: 导入期自检。为什么放在导入期：能力表是策略判据的输入（写集相交 ⇒ 串行、边表 ⇒ 越权拒绝），
#: 它一旦与实现漂移，症状不是崩溃而是静默的越权/并发损坏 ⇒ 让它 import 时就炸，是唯一"不可能
#: 忘记跑"的校验点。
#: 代价（主控裁决 2）：`import agentflow.capabilities` 会拉起全部 `agent_*` 与它们的 import 图
#: （约 167ms、约 159 个模块），与 `agentflow/__init__.py` 刻意不 import 子模块的取向有张力 ——
#: 保留的理由是"一个没人运行的校验"与"没有校验"在结果上不可区分，167ms 换"不可能忘记跑"划算。
#: 但不许只靠导入期：`__init__.py` 不 import 子模块 ⇒ 只有真的 import 到本模块的人才触发它。
#: 待办（给主控）：`scripts/release_check.py` 应显式跑一次 `import agentflow.capabilities` 并断言退出码 0。
assert_capabilities()

#: 导入期的覆盖读数。为什么要有这一行：第 [8] 条那种"零违反"的断言，
#: 在成功路径上必须留下"判据真的走遍了全部声明"的可见证据 ——
#: 一条只在失败时才说话的断言，与"根本没跑"在成功输出里长得一模一样（P16）。
#:
#: 为什么打在 stderr 而不是 stdout：stdout 是本仓若干脚本的机器可读出口
#: （`tests/test_noai_gate.py` 里有把整段 stdout 当 JSON 解析的用例），
#: 导入期的诊断行不许污染它。读数所以这样取：
#: `python -c "import agentflow.capabilities"`（exit 0，计数在 stderr）
#: 或 `python -c "import agentflow.capabilities as c; print(c.PARAM_ASSERT_COVERAGE)"`。
_PRINT_COVERAGE = (
    f"[capabilities] 导入期参数交叉断言：覆盖 "
    f"{PARAM_ASSERT_COVERAGE.get('checked', 0)} / 声明 "
    f"{PARAM_ASSERT_COVERAGE.get('declared', 0)} 个 property，"
    f"{PARAM_ASSERT_COVERAGE.get('actions', 0)} 个动作，接缝 {len(PARAM_SEAMS)} 条"
)
print(_PRINT_COVERAGE, file=sys.stderr)

#: `R-36` 的覆盖读数（与上行同一个理由：只在失败时说话的断言，成功时与"没跑"同形）。
#: 读它：`python -c "import agentflow.capabilities as c; print(c.PARAM_TYPE_COVERAGE)"`。
#:
#: 为什么这一行要写出 `80 + 16 − 1 = 95` 这条等式（审计 D-6）：只报一个 `tools_read` 时，
#: "77" 与工具层的 "95" 之间的 18 件没有出处，读的人只能猜。三个数一起写，等式自己会说话：
#: - `tools_in_registry_modules` = `tools._MODULES`（工具面真身）里声明的工具数；
#: - `tools_unread` = 那些工具里 `params` 不是字典字面量的（`table_tools` / `fs_tools` 用
#:   `_obj(...)` 调用装配 schema ⇒ 读不出，unknown）；
#: - `tools_read_but_not_registered` = 读得到、但不在 `tools._MODULES` 里的（今天只有
#:   `conjecture.register_conjecture`，理由见 `_TOOL_MODULE_EXTRAS`）。
_PRINT_TYPE_COVERAGE = (
    f"[capabilities] 两层参数对账：比较 {PARAM_TYPE_COVERAGE.get('compared', 0)} 对"
    f"（动作, property）/ {PARAM_TYPE_COVERAGE.get('keys_compared', 0)} 个约束键三元组；"
    "工具面读数 "
    f"{PARAM_TYPE_COVERAGE.get('tools_read', 0)} 个工具的约束面 = "
    f"{PARAM_TYPE_COVERAGE.get('tools_in_registry_modules', 0)} 件（`tools._MODULES`）"
    f" − {len(PARAM_TYPE_COVERAGE.get('tools_unread', []))} 件读不出"
    "（`params` 是 `_obj(...)` 调用而不是字典字面量："
    f"{PARAM_TYPE_COVERAGE.get('tools_unread', [])}）"
    f" + {len(PARAM_TYPE_COVERAGE.get('tools_read_but_not_registered', []))} 件读到但不注册"
    f"（{PARAM_TYPE_COVERAGE.get('tools_read_but_not_registered', [])}）；"
    f"没比对 {len(PARAM_TYPE_COVERAGE.get('unread', []))} 个动作；"
    f"工具面独有约束 {PARAM_TYPE_COVERAGE.get('tool_only_constraints', 0)} 对"
    f"（已登记 {PARAM_TYPE_COVERAGE.get('registered_tool_only_constraints', 0)} 对）；"
    f"反向（工具面有/动作面没有）：比过 {PARAM_MISSING_IN_ACTION_COVERAGE.get('pairs', 0)} 个动作，"
    f"缺口 {PARAM_MISSING_IN_ACTION_COVERAGE.get('gaps', 0)} 处"
    f"（已登记 {len(_KNOWN_TOOL_ONLY_PARAMS)} 个动作）；"
    f"动作面独有参数：逐 property 比过 {PARAM_ACTION_ONLY_COVERAGE.get('pairs_with_tool', 0)} 个动作，"
    f"缺口 {PARAM_ACTION_ONLY_COVERAGE.get('gaps', 0)} 处"
    f"（已登记 {PARAM_ACTION_ONLY_COVERAGE.get('registered', 0)} 个动作），"
    f"没有工具层的动作 {len(PARAM_ACTION_ONLY_COVERAGE.get('unmatched', []))} 个"
)
print(_PRINT_TYPE_COVERAGE, file=sys.stderr)
