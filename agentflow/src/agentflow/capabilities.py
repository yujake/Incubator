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
  都带符号名证据（见各处注释；`R4-6`：行号易失、几十分钟就漂，改用可核的符号名）。
  为什么写集必须有证据：它是并发安全判据（两张写集相交 ⇒ 串行）。它写错一个表名，
  后果不是报错，而是两个任务真的同时改同一批行，而它们的判重/去重互相看不见 —— 静默的数据损坏。
  已知的一处间接写：`F → A` / `F → D` 的实际写入发生在 A/D 自己的
  `tx(...)` 里（`AgentF._deploy_a`、`AgentF.step` 只提交请求行）。所以 F 的写集
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

    - `declared_external is not None` ⇒ `(spec.external, spec.side_effect)`；
      两根轴各说各的真话（`E.run_experiment` 是 `("exec", "write_local")`：
      它跑调用方给的脚本，同时又写 experiments 表）；
    - 否则 ⇒ `("none", spec.side_effect)`：效果轴照实取 `side_effect`，
      而外部轴在"没声明"时取 `none` —— 这与 `ToolSpec.declared_external`
      的默认值同一口径（"我没说"不等于"我会出网"）。

    B3 收官前这里还有两个遗留分支（`network` 走 `LEGACY_NETWORK_AXES`、
    以及"声明了 external 时效果一栏仍按 `WRITE_SETS` 的事实填
    `write_local`"）。它们随 `network` 那个取值一起删掉了：现在没有哪个取值
    需要"按事实另填一次效果"，两根轴上的值都能从声明直接读出来。
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
    "D": ("research", "search", "trace", "graph", "table", "fs", "conjecture"),
    "E": ("verify", "table", "fs"),
    "F": ("attack", "table", "fs"),
    "G": ("doc", "table", "fs"),
    "H": ("review", "verify", "doc", "table", "fs"),
    # V 的落地工具只有一组：`verify_tools` 里那三件只读的验证台账工具
    # （`verify.verify_proof` / `verify.list_verifications` / `verify.read_proof`）。
    # 刻意**不**照抄 E 的 ("verify","table","fs")：这张表的用途是"名字消歧"，
    # 不是授权矩阵 —— 多写组会让同名工具更容易撞上第二个候选，
    # 而 `ambiguous` 必须为空（`assert_capabilities` 第 [7b] 条）。
    "V": ("verify",),
    # 主控拿的是编排面工具（派活 / 台账 / 停止 / 状态 / 角色规格）：它不产出领域对象，
    # 所以这里只有 conductor 一组，且 CAPABILITIES["M"] 一个字都没变。
    "M": ("conductor",),
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
    """全仓工具名 -> `(side_effect, external, 是否显式写了 external 声明)`。

    不装配工具层，只读源码里的声明。第三个分量是"这条工具的 external
    是人写下来的，还是落到了默认值 `none`"—— 两者的判据强度不同：
    显式声明与能力层矛盾是 error（谁在低估风险），而落到默认值的那个
    只是一个没说的默认，不能拿它去判"能力层低估"。

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
      - `ToolSpec(name="...", side_effect="...", declared_external="...")`
        （关键字或前两个位置参数）；
      - `@tool("...", ..., side_effect="...", external="...")` 装饰器 ——
        装饰器的关键字参数就叫 `external`（`ToolSpec` 的字段叫
        `declared_external`，属性才叫 `external`）。

    注意：两种写法都要认，而且必须认那两个真实的名字。只认 `external=` 时，
    真实树上的 `ToolSpec(..., declared_external="exec")` 会被读成默认的 `none`，
    于是 `declaration_divergences` 会对一个"两层其实说同一句话"的动作报
    `two_layer_external_imprecise`（`verify.run_experiment` 就是这一形态）——
    一条由读错字段名造出来的假报警比漏报更坏：它会训练人忽略告警（P15）。

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
    "conductor_tools",
    # `draft/30` §T3-P3：猜想台账的产出面（T1 只落了数据面与判据）。
    # 这张名单是"两层声明对账"的输入：模块不在名单里，它声明的工具就比对不上，
    # 症状是导入期断言报 `D.register_conjecture` 属于"新的没比对"。
    "conjecture_tools",
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
    B3 收官已把那一处收敛掉（两层现在都说 `read` + `exec`），
    于是真实树上只剩"没有比对"这一类 info；判据本身仍然可红（见
    `tests/test_policy.py` 里那两条把能力层改错的自检）。

    ## 比对口径（三条，逐条都有反例在真实树上）

    两层声明的用途不同，所以不是逐字相等才叫一致（`WRITE_SETS` 的长注释
    逐字登记过这件事：工具层描述"默认调用"的副作用，能力层描述"可能写"的表）：

    1. 能力层在某一根轴上更保守 ⇒ 不报。 那是刻意的（能力表驱动并发与召唤判据，
       宁可多要一次裁决）。
    2. 能力层在某一根轴上更小 ⇒ 报 error。 工具说 `exec`/`egress`、能力说
       `none`，或工具说写、能力说读 —— 那是"能力表以为它更安全"，
       而低估风险比高估贵得多。
    3. 两根轴都非 `none` 但精度不同 ⇒ 报 warning（`two_layer_external_imprecise`）。
       例如工具说 `egress`、能力层说 `exec`：两层都承认"触到了我们不拥有的东西"，
       所以不报 error（那是"低估"那一类，见第 2 条），但"出网"与"起进程"
       是两根不同的风险面（沙箱怎么承接、审计怎么问都不同），
       所以也不许静默 —— 它必须可见。

    ## 为什么它只报告、不在导入期断言

    error 级会在导入期断言（`assert_capabilities` 第 [7] 条）；
    warning/info 只报告。理由：把 warning 也做成导入期 `AssertionError`
    会让 `import agentflow.capabilities` 因为一条"精度不同"而永久失败，
    于是整仓的导入期断言（包括既有的第 1–5 条）全部失效 ——
    那不是"更严"，是把门砸了。要不要付这个代价由 `STRICT_DECLARATIONS` 决定：
    它默认 False（只报告），置 True 时 warning 也进导入期断言
    （`R4-AN-3`：这个开关此前是一句 `pass`，即空转；现在它在 [7] 里真的读 warning）。
    """
    from .tools.base import EFFECT as TOOL_EFFECT

    return _divergences(CAPABILITIES, _tool_side_effects(), TOOL_EFFECT)


def two_layer_reconciliation() -> dict:
    """两层声明的对账面：每个动作落到三格里恰好一格（分区，不是"有没有分歧"）。

    ## 为什么这个函数必须存在（它补的是一条真的缝）

    :func:`declaration_divergences` 答的是"两层在哪里不一致"。而"对账面有没有
    真的在做"是另一个问题，它有三个不同的答案，必须分开数：

    - `compared`：动作与工具唯一对上了（这一格才叫"比对过"）；
    - `unmatched`：`handler_name` 在角色工具组里对应 0 个工具 ⇒ 没比成（unknown）；
    - `ambiguous`：对应 ≥2 个工具 ⇒ 按唯一性约定拒绝猜（unknown）。

    实测（2026-10-06 加角色 V 的三条动作之后）：
    59 个动作 = 21 compared + 38 unmatched + 0 ambiguous
    （V 的三条动作全部对上：`verify.verify_proof` / `verify.list_verifications` /
    `verify.read_proof` —— 工具名最后一段就是 `handler_name`，
    而 `_TOOL_GROUPS_BY_ROLE["V"]` 只登记了 `verify` 一组。
    此前 2026-10-03 加 `G.paper_package` 之后是 55 = 18 + 37 + 0；
    （2026-10-02 加 `A.ingest_local` 与 `B.register_statement` 之后是 53 = 18 + 35 + 0；
    2026-09-30 加 `A.search_literature` 之后是 51 = 17 + 34 + 0）。
    而 `assert_capabilities()` 第 [7] 条原来只钉 `unmatched`（`_KNOWN_UNMATCHED_ACTIONS`）——
    于是 `ambiguous` 那一格可以静默长大：它今天恰好是 0，所以那条缝从没被看见。
    本函数就是给分区断言用的输入，它自己不做判断（判断在第 [7] 条）。

    注意：刻意不把"一致"塞进 `declaration_divergences()`：那个函数的名字就是
    "分歧"，往里塞一致项会造出"名字与语义不符"的新缺陷（而它正是本仓库最忌讳的
    那类：判据看起来还在工作，读的人已经理解错了）。
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
    """一个动作在它的角色工具组里能对上的工具名（已排序，可能 0 / 1 / 多个）。"""
    groups = _TOOL_GROUPS_BY_ROLE.get(spec.role, ())
    return sorted(
        n for n in tools
        if n.split(".")[-1] == spec.handler_name and n.split(".")[0] in groups
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


# ---------------------------------------------------------------- 两层参数**类型**对账（R-36）
#
# R-36（`draft/28` §150.5）：`_divergences` 只比 property **名**与两根轴，不比**类型**。
# 于是"声明的类型与真交下去的值不是一回事"这一整类缺陷看不见 —— §150 那批里三处
# （`H.review` / `H.verify_fixes` 的 `dependencies` 声明成 `_OBJ`、`H.review_report`
# 声明成 `_ARR_S`，而工具层四条一直是 array-of-objects）就是它漏的：参数门照能力表
# 判，把一条**合法**的派活判成 `dependencies. 必须是对象，收到 array`。
#
# 为什么不是往 `_divergences` 里加一条：那个函数的输入是 `tools: Mapping[str, tuple[str, str, bool]]`
# （只有两根轴），要带类型就得改它的形状；而 `declaration_divergences_for` 是**公开**的
# 纯函数形态，`tests/test_policy.py` 用合成的两层表喂它 —— 改形状会连带改那些用例的
# 语义。判据多一条不等于判据要长在同一个函数里：这里另起一格，两种形态都给
# （读全局的 `param_type_divergences()` + 可喂表的 `param_type_divergences_for()`）。
#
# 为什么类型也要读源码（AST）而不是装配工具层：理由与 `_tool_side_effects` 逐字相同
# （`ToolSpec(...)` 现造于 `reset()/register()` 里，装配一次会在导入期碰文件系统）。
# 差别是这里要读的是**嵌套结构**（`properties.<名>.type` 与 `.items.type`），
# 所以只认字符串字面量的 `type`：读不出来就记成"没有比对"（unknown），不折成通过。


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


def _props_of(params_node: ast.AST | None) -> dict[str, tuple[str | None, str | None]] | None:
    """`params` 字面量里的 `{property: (type, items.type)}`。

    返回 `None` = **读不出来**（`params` 不是字典字面量，例如 `params=spec.params`）；
    返回 `{}` = 读出来了、确认没有 `properties`。两者必须分开 —— 合成一态就会把
    "这条工具的 schema 我看不见"读成"它没有参数，所以没问题"（P16 族的真空通过）。
    """
    if not isinstance(params_node, ast.Dict):
        return None
    props = _dict_value(params_node, "properties")
    if props is None:
        return {}
    if not isinstance(props, ast.Dict):
        return None
    out: dict[str, tuple[str | None, str | None]] = {}
    for k, v in zip(props.keys, props.values):
        name = _str_value(k)
        if name is None:
            continue
        items = _dict_value(v, "items")
        out[name] = (_str_value(_dict_value(v, "type")), _str_value(_dict_value(items, "type")))
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


def _declared_param_schemas(
    tree: ast.AST,
) -> list[tuple[str, dict[str, tuple[str | None, str | None]]]]:
    """从一棵模块 AST 里读出 `(工具名, {property: (type, items.type)})`。

    认三种声明形态（与 `_declared_side_effects` 同一套认名规则，多认一个 `params`）：
      - `ToolSpec(name="a.b", params={...})` / `ToolSpec("a.b", "...", {...})`；
      - `@tool("a.b", "...", params={...})` / `@tool("a.b", "...", {...})`；
      - `params=<模块级常量名>`（解析一层，见 `_module_constants`）。

    `params` 读不出来的工具**不写进表**（调用方按"这条工具没有比对"处理），
    而不是写一条空 schema —— 后者的症状是"零分歧"，与真相无关。
    """
    consts = _module_constants(tree)
    found: list[tuple[str, dict[str, tuple[str | None, str | None]]]] = []

    def resolve(node: ast.AST | None) -> ast.AST | None:
        if isinstance(node, ast.Name):
            return consts.get(node.id, node)
        return node

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
        props = _props_of(resolve(params_node))
        if props is not None:
            found.append((name, props))
    return found


def _tool_param_schemas() -> dict[str, dict[str, tuple[str | None, str | None]]]:
    """全仓工具名 -> `{property: (type, items.type)}`（读源码声明，不装配工具层）。"""
    out: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    base = Path(__file__).resolve().parent / "tools"
    for mod_name in _TOOL_MODULES:
        path = base / f"{mod_name}.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for name, props in _declared_param_schemas(tree):
            out[name] = props
    return out


def _shape(declared: tuple[str | None, str | None]) -> str:
    """把 `(type, items.type)` 渲染成人能读的一小段（只用于报错信息）。"""
    t, it = declared
    if t is None:
        return "（读不出类型）"
    return f"array<{it}>" if t == "array" and it else t


def param_type_divergences_for(
    capabilities: Mapping[str, tuple[ActionSpec, ...]],
    tool_params: Mapping[str, Mapping[str, tuple[str | None, str | None]]],
) -> list[DeclarationDivergence]:
    """判据本体（两张表都由调用方给）：两层对同一个 property 声明的**类型**不一致。

    只在"两层都声明了这个 property、且两层的 `type` 都是字面量"时判 ——
    其余一律不判（那是"没有比对"，不是"比对通过"；缺属性由 `param_seam_violations` 管）。

    `array` 要连 `items.type` 一起比：`_ARR_S`（array<string>）与 `_ARR_OBJ`
    （array<object>）的 `type` 都是 `"array"` —— 只比 `type` 的话，
    §150 那三处缺陷一个都抓不到（`review_report` 那处正是 `_ARR_S` vs array<object>）。

    一处**刻意不判**（写下来免得下一个人以为漏了）：一侧给了 `items.type`、
    另一侧只写了 `{"type": "array"}` ⇒ 不报。理由是 `validate_params` 对没有 `items`
    的 array 不施加形状约束，此时两层并不矛盾，只是其中一层说得更细。
    """
    out: list[DeclarationDivergence] = []
    for role, specs in capabilities.items():
        for spec in specs:
            cands = _candidates(spec, tool_params)
            if len(cands) != 1:
                continue
            tool_name = cands[0]
            tool_props = tool_params.get(tool_name)
            if tool_props is None:
                continue
            cap_props = (spec.params or {}).get("properties") or {}
            for prop, cap_declared in cap_props.items():
                if prop not in tool_props or not isinstance(cap_declared, Mapping):
                    continue
                tool_declared = tool_props[prop]
                cap_type, cap_items = cap_declared.get("type"), (cap_declared.get("items") or {}).get("type")
                tool_type, tool_items = tool_declared
                if cap_type is None or tool_type is None:
                    continue
                if cap_type == tool_type and not (cap_type == "array" and cap_items and tool_items
                                                  and cap_items != tool_items):
                    continue
                out.append(DeclarationDivergence(
                    "two_layer_param_type_divergence", "error",
                    f"{role}.{spec.action} <-> {tool_name}",
                    f"property {prop!r}：能力层声明 {_shape((cap_type, cap_items))}，"
                    f"工具层声明 {_shape((tool_type, tool_items))} —— 两层对"
                    "『这个参数是什么形状』有两个答案。危害不是报错而是**判错**："
                    "参数门（`Conductor._check_params`）读的是能力表，而 `ToolRegistry.call` "
                    "第一步 `validate_params` 读的是工具表 ⇒ 一条合法派活会被能力表判死"
                    "（§150 的 `dependencies` 就是这样：能力层 `_OBJ` vs 工具层 array<object>），"
                    "或者反过来放行一个工具层必然拒收的形状。"
                    "**改哪一层由人定**：工具层是校验的真身，能力层是派活的契约，"
                    "两者对不上时先问『谁在说谎』，不许让判据替你选。",
                ))
    return out


def param_type_divergences() -> list[DeclarationDivergence]:
    """真实树上的类型对账读数（`param_type_divergences_for` 读全局版本）。"""
    return param_type_divergences_for(CAPABILITIES, _tool_param_schemas())


def param_type_coverage() -> dict:
    """类型对账的覆盖率读数：判据**看进去多少**（P16：零分歧必须配上覆盖读数）。

    - `tools_read`：`params` schema 读出来的工具数；
    - `compared`：两层都声明了类型、真的逐对比过的 (动作, property) 对数；
    - `unread`：对上了唯一工具、但那条工具的 `params` 读不出来（三态里的 unknown）。

    刻意不给"应该达到多少"的硬编码下限：工具增删会让它漂。导入期断言用的是
    "`compared` 不许为 0 而 `unread` 一大堆"（见 `assert_capabilities` 第 [9] 条）。
    """
    schemas = _tool_param_schemas()
    compared = 0
    unread: list[str] = []
    for role, specs in CAPABILITIES.items():
        for spec in specs:
            cands = _candidates(spec, schemas)
            if len(cands) != 1:
                continue
            tool_props = schemas.get(cands[0])
            if tool_props is None:
                unread.append(f"{role}.{spec.action} <-> {cands[0]}")
                continue
            for prop, declared in ((spec.params or {}).get("properties") or {}).items():
                if not isinstance(declared, Mapping):
                    continue
                if prop in tool_props and declared.get("type") and tool_props[prop][0]:
                    compared += 1
    return {"tools_read": len(schemas), "compared": compared, "unread": sorted(unread)}


#: 实测的"工具面声明了、动作面没声明"的 property（`two_layer_param_missing_in_action`）。
#:
#: 为什么要有这一格（残项 ㉓；2026-10-07 所有者授权 5b"补反向 + 新计数并入读数"）：
#: 正反两处既有判据都管不到这个方向 —— `param_type_divergences_for` 由**动作面**驱动
#: （动作没声明的 property 它根本看不见），`param_seam_violations` 管的是"动作声明了、
#: 实现不收" ⇒ "工具面加了参数、忘了加动作面"这条裂缝**全树没有读数会报**。
#: 它为什么有代价：编排层（主控）按**动作参数表**派活 ⇒ 工具面新加的入口在派活侧看不见。
#:
#: 形态：按 (角色, 动作) 登记**确切的那几个 property** + 理由（不逐 property 登记，
#: 也不写成"这个动作以后随便缺"）。这样三种变化都会红：
#:   ① 出现新的一对（新动作或新匹配上的工具）· ② 已登记那对又多缺一个 property
#:   · ③ 登记里某个 property 不再缺了（登记过期 ⇒ 必须删掉，否则这张表会烂成噪音）。
#: 判据本体在 `tests/test_capabilities_reverse_param_gaps.py`（**刻意不放进导入期**：
#: 所有者 5b 授权的形态是"补反向 + 新计数并入读数"，把导入期改成硬失败会超出那次授权）。
#: 注意这张表是**可见性**登记，不是"认可"：改哪一层由人定（与 `param_type_divergences_for`
#: 末尾那句处置口径一致）。
_KNOWN_TOOL_ONLY_PARAMS: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    ("B", "run"): (
        frozenset({"backend", "dpi", "languages", "max_pages", "pages", "path"}),
        "`B.run` 的实现是 `ocr.run`（⑫ 的接线）：工具面那六个 OCR 参数是接线时加的，"
        "动作面当时没同步。改它是动 `specs/b.py` 的声明面（禁改区），而"
        "「B 的动作面该不该暴露 OCR 的后端/页数/语言」是设计判断，先让它可见。",
    ),
    ("C", "neighbors"): (
        frozenset({"max_neighbors"}),
        "`graph.neighbors` 有可选上限 `max_neighbors`，动作面只声明了必填。"
        "C 的图上动作今天只走 `neighbors`/`paths` 两个入口，上限是否要暴露给编排层未见裁定。",
    ),
    ("D", "register_conjecture"): (
        frozenset({"force_new"}),
        "`conjecture.register_conjecture` 有 `force_new`（重复登记时是否强建新行），"
        "动作面没声明 ⇒ 主控派活时用不上这个开关。",
    ),
    ("E", "run_experiment"): (
        frozenset({"run_name"}),
        "`verify.run_experiment` 有 `run_name`，动作面没声明。",
    ),
    ("E", "check_formal"): (
        frozenset({"checker_name"}),
        "`verify.check_formal` 有 `checker_name`（指定用哪个证明检查器），动作面没声明 ⇒"
        "编排层选不了检查器（提示词里也没有这一档）。",
    ),
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


def param_missing_in_actions(
    capabilities: Mapping[str, tuple[ActionSpec, ...]] | None = None,
    tool_params: Mapping[str, Mapping[str, tuple[str | None, str | None]]] | None = None,
) -> dict[tuple[str, str], list[str]]:
    """判据本体（**反向**）：工具面声明了、动作面没声明的 property。

    只对"唯一匹配到某个工具、且那条工具的 `params` 读得出来"的 (角色, 动作) 算 ——
    与 `param_type_divergences_for` 同一档口径（多义与读不出来的都不猜）。
    覆盖率读数见 `param_missing_in_action_coverage()`：**空集永远是子集**，
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
# `D-8`（更正，观测时刻 2026-09-26 19:0x）：这里原来是一大片 `文件:行号`
# （形如 `<模块>.py:<行> <方法名>`）。那些行号全部过期了，
# 而且这与 `.noai-paths` 里已经立过的纪律相反 —— 那份清单第 35-45 行逐字论证过
# "理由里刻意写符号名不写行号"，理由是行号易失（实测 `normalize_doi` 在几十分钟内
# 就从 26 行漂到 44 行）。
#
# 所以这里改成只写符号名（`<Class>.<method>`），并由
# `tests/test_capabilities_two_layer.py::test_action_handler_names_exist_as_class_methods`
# 逐个断言"这个名字真的存在于对应模块的那个类里" —— 符号名比行号强：
# 改行号它不响，删了/改了那个方法它必响。
#
#   模块            类            方法
#   agent_a.py      AgentA        run_once / run
#   agent_b.py      AgentB        run_once / reprocess_once / run_reprocess /
#                                 decide_structural_duplicate / resolve_structural_duplicate / run
#   agent_c.py      AgentC        hottest / paths / cold / gaps / neighbors /
#                                 relations_between / contradictions / structural_duplicates / handle
#   agent_d.py      AgentD        probe_c / ingest / ingest_detailed / trace_question / trace_l3 /
#                                 assess / submit_gaps / consider / poll / adjudicate /
#                                 research / run_round / write_report
#   agent_e.py      AgentE        run_experiment / check_formal / evidence_for /
#                                 list_experiments / run_script_experiment
#   agent_f.py      AgentF        create_plan / step / status / list_plans
#   agent_g.py      AgentG        compose_claim / register_dependency / build_document /
#                                 render / refresh_markdown / revise
#   agent_h.py      AgentH        review / verify_fixes / list_findings

#: 角色 -> 该角色的动作元组。不在表里的角色没有任何动作（`M` 就是如此：
#: 主控的"动作"是 `summon()` 本身，它由 `Conductor` 实现，不是一个 Agent 方法）。
#: 真身是 `src/agentflow/specs/<角色>.py`（M3 起）。这一行只做派生 —— 
#: 也就是说改权限面要改 `specs/`，而 `specs/` 在 `.noai-paths` 里受保护。
CAPABILITIES: dict[str, tuple[ActionSpec, ...]] = _specs.action_table()

#: `M` 没有任何动作，但它必须在键集合里（与 `schema.ROLES` 不同的一套名单会漂移）。
#: 为什么空而不是省掉：`CAPABILITIES["M"] == ()` 让"主控不产出领域对象"这条约束
#: 变成可断言的事实，而不是"表里没写所以大概是吧"。


# ---------------------------------------------------------------- 参数接缝（声明 ↔ 实现签名）
#
# ## 这一段补的是哪一个洞（`D-2` / `R2-AN-1` 的 capabilities 半边）
#
# `ActionSpec.params` 是**声明**，handler 的 `inspect.signature` 是**实现**。
# 两者此前没有任何机器判据相连：`Conductor._check_params` 只看声明
# （`tools.base.validate_params(spec.params, …)`），而声明里多一个 property
# 不会有任何地方报出来 —— 主控放行 ⇒ 写 `running` 行 ⇒ 执行期才发现这个参数
# 没人接（`E.run_experiment` 的 `sleep` 就是这一格）。诊断台账里那一行看起来像
# "实验跑失败了"，其实这次调用从来没被执行过。
#
# 判据的形态（三态，缺一条就会退化成真空断言）：
#   ① 每个 property 要么被 handler 的签名接受（具名形参，或 handler 收
#      `inspect.Parameter.VAR_KEYWORD` —— 后者按定义真的收得下这个键），
#      要么逐条登记在下面这张接缝表里；
#   ② 不满足 ⇒ **导入即失败**（`assert_capabilities` 第 [8] 条），
#      错误信息逐字给出 角色 / 能力 / property，并说清两条出路
#      （改实现，或登记 + 写理由）；
#   ③ 登记表不许烂成噪音：接缝表里"现在已经不需要了"的条目也要报出来
#      （形态照抄 `_KNOWN_UNMATCHED_ACTIONS` 的 stale 那一条）。
#
# ## 为什么这张表存在，而不是"直接把 sleep 删了"
#
# 删声明（被否掉的 B 选项）会让替身/夹具无法按同一份 schema 声明参数：
# `tests/test_conductor.py` / `tests/test_scheduler.py` 的 `FakeE.run_experiment`
# 靠 `sleep=` 控制"这次实验跑多久"，那些用例测的正是并发/取消/串行的时序。
# 给 `AgentE.run_experiment` 加一个没人读的具名 `sleep` 或让它收
# `inspect.Parameter.VAR_KEYWORD`（被否掉的 C 选项）是更坏的一种：
# 它把"我传了但它没看"变成静默成功 —— 那正是 `LocalBackend.call` 的
# docstring 逐字拒绝的形态。所以接缝留在声明这一层，并且必须**登记 + 写理由**。

#: 参数接缝表：`(角色, 动作, property 名)` -> 一行理由串。
#:
#: 一行 = 一个"声明里有、实现侧不收"的参数。写入这张表就是承认
#: "这一格参数门放行时实现会拒"，因此理由必须写清它**只服务谁**。
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

#: 两层参数**类型**对账上一次的覆盖计数（由 :func:`assert_capabilities` 第 [9] 条就地写）。
#: 键：`tools_read` / `compared` / `unread`（`unread` 是列表，另存一份计数时用 `len`）。
#: 与 `PARAM_ASSERT_COVERAGE` 分开放：两条断言的覆盖率不是一回事
#: （那条数 property 名与实现签名，这条数"两层都给了类型的 (动作, property) 对"）。
PARAM_TYPE_COVERAGE: dict[str, Any] = {}

#: 反向那一格（工具面有、动作面没有）的覆盖读数：与 `PARAM_TYPE_COVERAGE` 同一条理由 ——
#: 只在失败时说话的判据，成功时与"没跑"同形。读它：
#: `python -c "import agentflow.capabilities as c; print(c.PARAM_MISSING_IN_ACTION_COVERAGE)"`。
#: 这里刻意**不放导入期断言**（所有者 5b 授权的形态是"补反向 + 新计数并入读数"）；
#: 判据本体与登记表对账在 `tests/test_capabilities_reverse_param_gaps.py`。
PARAM_MISSING_IN_ACTION_COVERAGE: dict[str, Any] = {}


def handler_accepted(role: str, action: str) -> tuple[frozenset[str], bool]:
    """取 `(角色, 动作)` 的**实现侧**参数面：`(具名参数集, 是否收 VAR_KEYWORD)`。

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
    """参数门的口径：**声明 ∩ 实现签名**（`D-2` 第 3 条）。

    返回一份可以交给 `tools.base.validate_params` 的 schema：

    - `properties` = 声明里的 property ∩ handler 按名收得下的那些。
      收 `inspect.Parameter.VAR_KEYWORD` 时交集就是声明本身（实现真的收得下任何键）；
    - `required` = 声明里的必填 ∩ 剩下的 property。**必填项落在交集之外是错误，
      不是"过滤掉"** —— 静默丢掉一个必填项会把"必须给 claim"读成"可以不给"；
    - `additionalProperties` 原样保留（声明里是 `False` 时，实现侧独有的参数
      仍然进不来：交集是双向的）。

    两个关键字形参是接缝表的入口：替身夹具的实现面由调用方给（`accepted` /
    `accepts_kw`），不给时按 `spec` 的角色与动作从真实现读（`None` 与"空集"是
    两件事，所以默认值是 `None` 而不是 `frozenset()`）。

    它今天**没有**被 `Conductor._check_params` 调用 —— `conductor.py` 在本窗口
    禁改，而它的 `_check_params` 读的是 `spec.params`。这一格为什么可以不改，
    逐字写在 :func:`check_params` 的 docstring 里。
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

    形态与 `Conductor._check_params` 逐字同形（同一个判据、同一句话），
    好让那一处**一行就能改成调它**：`return C.check_params(spec, dict(params))`。

    ## 为什么这一版没有直接接进 `Conductor._check_params`

    判据要能区分"产品实现"与"替身夹具"的收参数面，而那个信息只存在于
    **调用点**（`_check_params(spec, params)` 只有这两个入参，看不到
    `self.backend` / `self.registry` 里挂着的是谁）。本窗口 `conductor.py` 是禁改
    文件，所以：

    - 产品路径的正确性今天由**两个已有的落点**共同保证，都不需要改 conductor：
      ① 本模块第 [8] 条导入期断言保证"声明里的每个 property 要么被真实现接受、
      要么逐条登记"；② `LocalBackend.call` 在调 handler 之前已经用
      `inspect.signature` 核过"实现不认这些参数"，不认就抛 `ParamError`
      （所以接缝参数在产品路径上**不会**静默进 handler）；
    - 参数门**提前**拒绝（把 `failed` 变成 `refused`，不写 `running` 行）需要调用点
      把实现面传进来，那是一次 conductor 改动 ⇒ 已作为交接项写进交付，
      函数在这里备好（`gate_params` / `check_params`），改的时候只有一个调用点。
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
#: 真身是 `src/agentflow/specs/<角色>.py`（M3 起）。这一行只做派生 —— 
#: 也就是说改权限面要改 `specs/`，而 `specs/` 在 `.noai-paths` 里受保护。
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
#:
#: ## 为什么需要它（以及它为什么不是"第二份名单"）
#:
#: `WRITE_SETS` 是角色级的，`READ_ONLY_WRITE_EXCEPTIONS` 是表级的，
#: 而 `READONLY_CALL_EXCEPTIONS` 是工具级的 —— 三者之间原本没有任何机器判据相连：
#: 往工具级表加一个能写 `claims` 的工具，工具层会放行、表级例外不认，什么都不红。
#:
#: 第一版修法我试过"角色级写集 ∩ 该工具源码里字面出现过的表名"，实测接近真空：
#: 对 `review.verify_fixes` 只算出 `{review_findings}`（`documents` 是它调用的下层写的，
#: 它的函数体里没有那个字面量）⇒ 永远算不出 `documents` ⇒ 永远报不出"越权写 documents"。
#: 一个永远不报的判据与没有判据在证据上是一回事。
#:
#: 现在是显式逐工具登记 + 三条机器判据（全部在 `assert_capabilities` 的 `[5c]` 里）：
#:   ① 本表覆盖 `READONLY_CALL_EXCEPTIONS` 里的每个工具（漏一个 ⇒ 导入期红）；
#:   ② 本表[tool] 必须等于 `_tool_write_set_from_source(tool)` 从工具实现里
#:      算出来的写集（写多/写少都红）—— 这一条是 `R4-5` 补的：
#:      此前 ② 只保证"能解析到一个动作"，登记值写错没有任何判据看得见；
#:   ③ 本表[tool] ⊆ `READ_ONLY_WRITE_EXCEPTIONS[role]`（写越界 ⇒ 导入期红）；
#:      外加"本表里没有已经不存在的工具"（登记表要自我清理）。
#: 四条一起把"漏登记 / 多登记 / 登记值与实现不符 / 写越界"四个方向都堵住。
#:
#: 证据栏用符号名（与 `WRITE_SETS` 同一个口径）：写不出证据的行不许留在这里。
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
}


# ---------------------------------------------------------------- 允许的召唤边

#: 谁能召唤谁（DESIGN-CONDUCTOR.md §3.1，逐字实现）。
#:
#: 两条刻意设计的边：
#: - `C` 的边是空的：C 一旦能发起动作，它就成了"绕过 B 引文回验"的写入路径。
#:   C 的 `candidate_gaps` / `structural_duplicates` 是产出，由 D 或编排层
#:   决定要不要变成请求。
#: - `H` 能召唤 `A` / `E` / `G`（**不是只有 `G`**）：`H → A` 与 `H → E` 两条边
#:   2026-09-30 由人批准加入（`draft/28` §199），用途是"引文对不上就找 A 核实原文、
#:   断言能不能形式化就找 E"。审校者**依然不能改数据**，但那条约束的真身是
#:   "H 的工具面 0 个写工具"（schema.H 的装配期断言），**不是**"H 没有向外的边"——
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
    于是"临时角色能不能被闸门认出来"只取决于**有没有把注册表传下去**这一件事。
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

    只认写方法，不认读方法 —— 这是本函数与那个被删掉的第一版
    `_tables_written_by_action` 的第一处区别（`R4-3` / `R4-5`）：

    - 写：`upsert` / `append` / `insert_unique` / `mark_dirty`
      （`mark_dirty` 是"就地改过"的显式声明，它一定导致这张表被写回）；
    - 不写：`rows` / `find` / `store.tx(...)` 本身 / `store.rows(...)`。

    把 `store.tx("documents", ...)` 也算成写，会把"为了读快照而声明的表"
    算进来（`WRITE_SETS["D"]` 的注释记的正是这个形态：D 的 `relations` 是读）。

    接收者必须叫 `tx`（`store.tx(...)` 返回的那个事务对象）。这一条是必须的：
    `tool_tools` 里满地是 `found.append("…")` / `reasons.append("…")` 这类
    列表 append，只看方法名会把一大段中文提示语当成表名（实测：
    `verify_fixes` 第一次跑就"算出"了 `documents`、`review_findings`
    加两条中文消息）。
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

    ## 为什么需要它（`R4-5`：判据 ② 原先只保证"解析到一个动作"）

    ② 原来的判据止步于"这个只读例外工具能在能力表里解析到一个 `ActionSpec`"，
    而"它到底写哪几张表"没有任何机器判据比对 ⇒ 实测把
    `TOOL_WRITE_SETS['review.review_document']` 改成空集，`assert_capabilities()`
    照样通过。本函数把那一半接上：从工具自己的实现里算出写集，再与登记值逐个比。

    ## 与第一版那个零调用点的 `_tables_written_by_action` 的区别（`R4-3`）

    第一版扫的是 `ActionSpec.handler_name` 那一层函数体里字面出现过的表名
    （不分读写、不跟调用），实测接近真空：`review.verify_fixes` 只算出
    `{review_findings}`，而 `documents` 是它调用的 `_set_doc_status` 写的
    ⇒ 算不出 `documents` ⇒ 永远报不出"越权写 documents"。一个永远不报的判据
    与没有判据在证据上是一回事。三处不同，三处都是为了"真的会红"：

    1. 只认写方法字面量（`_write_calls_in`），读不算；
    2. 沿同一文件里的顶层函数调用做闭包（`_set_doc_status` 这类下层写入点会被
       走到），而不是只看一层；
    3. 它真的被调用（见 `assert_capabilities` 的 ②），而且算不出来时返回 `None`
       —— 调用方必须显式登记到 `_NO_WRITE_SET_SOURCE`，不许静默跳过。

    返回值：`frozenset` = 算出来的写集；`None` = 算不出（`<前缀>_tools.py`
    不在盘上、函数名找不到、或文件读不了）。`None` 绝不是空集：
    前者是"没查成"，后者是"查过了、不写表"。
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
_NO_WRITE_SET_SOURCE: dict[str, str] = {}


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


#: 台账审计里用到的码。与 `verify.verify_all` 里 tasks 那段逐字一致（见
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
        #   ② **文件型产物** `file:<工作区相对路径>`，或直接给一个工作区内存在的相对路径。
        # 第二种是 R-47/R-52 逼出来的：产出摘要落成文件后，`artifacts` 里出现的是**路径**，
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

    ## 两个注入形参为什么存在（与 `WRITE_SETS` 无关的那个理由）

    第 `[5c]` 条（`roles-2`）是导入期判据，而导入只发生一次 ⇒ 在进程内
    没法用"改掉表再重跑"的方式给它做负控（实测：先撞上第 `[4]`/`[6]` 条，
    那两条比它更早看到同一张表）。没有注入，这条断言就永远无法被负控验证，
    而"无法验证的断言"与"没有断言"在证据上是一回事。

    所以这两个形参让调用方（只有测试）换掉那两张表。生产路径不传 ⇒ 与加形参之前
    逐字相同。这不是"给门开后门"：默认值 `None` 意味着"用模块里那一份"，
    而模块里那一份仍然是导入期被核过的。形态照抄 `_matching_tool_name(spec, tools)`
    （同一个文件里既有的"工具表由调用方给"的做法）。

    三态纪律（`R4-4` 实测的修法）：`write_sets` 形参曾经是"空转入口" ——
    `_ws = dict(write_sets) …` 那一行赋值之后从未被读，第 [1]/[4]/[6] 条读的
    仍是模块全局 `WRITE_SETS`，于是 `assert_capabilities(write_sets={…})` 这个
    调用看起来在拿替身跑判据、实际什么都没换（把 `C.WRITE_SETS` 整个清空后
    断言照样通过）。现在 `_ws` / `_rowe` 在函数最前面解析一次，第 [1]/[4]/[6]
    与 `[5c]` 全部读它们 —— 要么形参真的生效，要么它不存在，不许"看起来生效"。

    八条断言，每一条都对应一次本项目真实踩过的坑族：

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
       error 级任何时候都在导入期断言，warning 级只在
       `STRICT_DECLARATIONS=True` 时升级为导入期断言（默认只报告）。
       外加第 [7b] 条：对账面必须是一个分区（`compared` / `unmatched` /
       `ambiguous` 三格互斥且穷尽，且 `compared` 非空、`ambiguous` 为空）。
       为什么第 [7] 条不够：它只钉 `unmatched`，`ambiguous` 那一格今天恰好是 0
       却不在任何登记表里 ⇒ 它可以静默长大（`G-19` 的同族形态）。
    8. 参数门的口径是"声明 ∩ 实现签名"：能力表里每个 property 要么被对应
       handler 的签名接受（具名形参，或 handler 收
       `inspect.Parameter.VAR_KEYWORD`），要么逐条登记在 `PARAM_SEAMS` 里。
       第 [2] 条只核"这个动作名真的存在"，管不到"这个动作收不收这些参数" ——
       `E.run_experiment` 的 `sleep` 就是这一格：声明在、实现不收、
       `Conductor._check_params` 放行、执行期才炸。这一条与 `tools` 侧
       注册期的同族断言（`tools.base` 的接缝表 + `ToolRegistry.register`）
       是同一机制在两层的两个落点。
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
    # `FINAL-R4-01`：上面那一条只核**键集**（"每个角色都有出边条目"），
    # 不核**值**。于是把 M 的边写成 7 元字面量（漏掉 H）之后，新角色永远不会被
    # 主控召唤，而这条断言照样过 —— 今天守住它的用例在 `tests/test_policy.py`
    # （`assert C.ALLOWED_EDGES["M"] == frozenset(S.ROLES)`），落点不在能力层自家
    # 判据里。这里补上同一条：主控的出边必须**恰好**是全部角色。
    #
    # 位置刻意放在下面那个逐条循环**之后**：先让"含非角色目标"那条判据对
    # `{"agent-A"}` 这类拼错说话（`test_unknown_edge_target_is_rejected` 逐字匹配
    # 那句消息），本条只在"目标都是合法角色名、但漏了一个"时才承担判据。
    # 边表里的目标也必须是合法角色名：写成 "agent-A" 这类拼法会让
    # 每一次 `M → A` 都被判 forbidden_edge，而"策略拒绝了"看起来像正常工作。
    for frm, tos in ALLOWED_EDGES.items():
        bad_targets = sorted(set(tos) - set(S.ROLES))
        assert not bad_targets, f"ALLOWED_EDGES[{frm!r}] 含非角色目标 {bad_targets}（拼法必须与 schema.ROLES 一致）"
        # `FINAL-R4-05`：下面这一条在今天的 schema 下**不可达** —— `NON_SUMMONABLE`
        # 只含 `CONDUCTOR_ROLE`，而它不在 `S.ROLES` 里，所以任何指向 M 的边都会先被
        # 上面那条"含非角色目标"命中。保留它是为了"将来 NON_SUMMONABLE 里放进一个
        # 合法角色"时仍有人守着（实测：把 NON_SUMMONABLE 换成合法角色后这条会红），
        # 但顺序必须写在这里，免得读的人以为它今天在承重。
        assert not (set(tos) & NON_SUMMONABLE), (
            f"ALLOWED_EDGES[{frm!r}] 允许召唤这些不可召唤的角色 {sorted(set(tos) & NON_SUMMONABLE)} —— "
            "没有『召唤主控』这件事，它只能由用户/调用方驱动"
        )
    assert set(ALLOWED_EDGES.get(S.CONDUCTOR_ROLE) or ()) == set(S.ROLES), (
        f"ALLOWED_EDGES[{S.CONDUCTOR_ROLE!r}] 必须恰好等于 schema.ROLES："
        f"多 {sorted(set(ALLOWED_EDGES.get(S.CONDUCTOR_ROLE) or ()) - set(S.ROLES))}，"
        f"少 {sorted(set(S.ROLES) - set(ALLOWED_EDGES.get(S.CONDUCTOR_ROLE) or ()))}"
        "（少的那些角色永远不会被主控召唤，而键集判据看不见这件事）"
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
    #
    # 缺陷（2026-09-26 全面体检 · 子代理 A，实测）：只读角色能写哪些表这件事有两个
    # 互相独立、可以各自漂移的落点 —— 工具级 `tools.base.READONLY_CALL_EXCEPTIONS`
    # （H 到 3 个 `review.*`）与表级本模块的 `READ_ONLY_WRITE_EXCEPTIONS`
    # （H 到 `documents` 与 `review_findings`）。`capabilities.py` 全文不出现
    # `READONLY_CALL_EXCEPTIONS`，两者的对应关系只写在自然语言理由里。
    # ⇒ 往工具级表加一个能写 `claims` 的工具不会触发任何断言：
    # 工具层会放行、表级例外不认，没有任何东西会红。
    #
    # 这正是 `.noai-paths` 给 FC-27 第七类写的那句"测试全绿、上线即越权"的破口形态。
    #
    # 判据（三条，缺一条就会退化成真空断言）：
    #   ① 两个例外表的键集必须相同（有工具级例外却没人登记表级 ⇒ 直接红）；
    #   ② 每个例外工具必须能在能力表里解析到一个动作（`matching_tool_name`），
    #      否则"比不了"这件事必须显式登记 —— 不许静默跳过（`P16`：真空通过 = 缺陷）；
    #   ③ 解析到的动作能写哪些表，必须是表级例外的子集。
    #
    #  已知边界（如实登记，不许读成"已完全闭合"）：`review.review_document`
    # 今天在能力表里没有对应的 `ActionSpec`（H 的 action 只有 `review` / `verify_fixes`
    # / `list_findings`），所以它比不了，走 ② 的显式登记那一支。
    # 也就是说："review_document 只写这两张表"这件事今天仍然只由人写的理由保证。
    # 把它变成机器判据需要给 `ActionSpec` 加逐动作写集（今天 `WRITE_SETS` 是角色级），
    # 那是另一条改动，登记在 `draft/28` 的 `roles-2`。
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

    # 实测的窟窿（`D-9` 更正，观测时刻 2026-09-26 18:5x）：33 条不一致，全部是"没有比对"
    # （`two_layer_name_unmatched`，两个层的名字对不上 ⇒ 三态里的 unknown），
    # warning 0、error 0。于是上面那道 error 断言今天是真空的 ——
    # 门看起来接上了，实际上只比对了 1 个动作。这不是"再严一点"能解决的：
    # 那些动作本来就不是工具调用（`C.hottest` / `D.ingest` 是角色级方法），
    # 两层没有可比对的对象。
    #
    # 这个数字怎么来的（不许手抄）：`collections.Counter((x.level, x.code)
    # for x in capabilities.declaration_divergences())` ⇒ 今天全部落在
    # `('info', 'two_layer_name_unmatched')` 这一格，总条数等于
    # `len(two_layer_reconciliation()['unmatched'])`，也等于 `_KNOWN_UNMATCHED_ACTIONS`
    # 的条数 —— 下面第 [7] 条的两条断言（new_unmatched 与 stale 都为空）
    # 钉着这个相等，所以这里不再写死具体数字。
    # 它此前写的是 32，而 `D-5` 给 `CAPABILITIES['H']` 加了一个动作之后就漂了
    # （第 6 轮重审 `R4-AN-2` 实测到 33）：手抄的数字会过期，等式不会。
    # 旧版这里写"33 条里 32 条 + 1 条 warning"，而那条 warning
    # （`two_layer_external_imprecise`）在 B3 收官后已经不存在了。
    #
    # 所以这里钉的是对账面不许静默缩小（P16 族：真空通过 = 缺陷）：
    #   ① 新出现的"没比对"必须显式登记（否则导入失败）；
    #   ② 登记表里"已经对上了"的必须删掉（否则登记表变成噪音，慢慢就没人看）。
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
    # 上面那条只钉 `unmatched`。实测（2026-10-03 加 `G.paper_package` 之后）：
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
    #
    # 我原本在这里加了一条"反方向"断言：只读例外表里的每个工具，要么在能力表里
    # 解析到一个动作，要么在 `_NO_ACTION_YET` 里登记。写完自己负控时发现它是
    # 真空的 —— 上面第 [5c] 条的 ② 已经在同一个循环、同一张表上做了同一件事    # （`if not _matched: assert _tool in _NO_ACTION_YET`），而且它先跑。
    # 于是 [7c] 的 `_excepted = {...} - set(_NO_ACTION_YET)` 里剩下的那一格
    # 永远满足断言前提：能走到这里的工具必然"解析不到但不在登记表里"，
    # 而那正是 [5c] 已经判红的形态 —— 我再也构造不出一个只有 [7c] 能抓的输入
    # （实测：把例外表里一个工具改名成解析不到的写工具，[5c] 先炸；
    # 把它登记进 `_NO_ACTION_YET`，[7c] 就看不见它了）。
    #
    # 一条抓不到任何东西的断言比没有断言更坏：它会让读的人以为这一格被守住了。
    # 所以撤掉它，不留"看起来在工作"的门。
    #
    # `D-5` 的根除靠的是另外两件真的会红的事，两处都有负控（`temp/batchM-verify.py`）：
    #   ① `H.review_report` 补进 `CAPABILITIES['H']` + `_KNOWN_UNMATCHED_ACTIONS`
    #      ⇒ `check_action('H','review_report')` 不再是 `unknown_action`；
    #   ② 第 [7] 条的 `new_unmatched` 断言：将来加一个动作而忘了同步登记，
    #      `import agentflow.capabilities` 当场炸（负控实测：删掉
    #      `_KNOWN_UNMATCHED_ACTIONS` 里那行 ⇒ `AssertionError: 出现了新的
    #      『两层没有比对』的动作 ... ['H.review_report']`）。
    #      这就是 `D-5` 当初漏掉的那一步（那时它悄悄多了一条 info，
    #      对账面静默缩小）。

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

    # ---- [9] 两层参数**类型**对账（`R-36`）
    #
    # R-36（`draft/28` §150.5）：上面的 [8] 只比 property **名**与实现签名，不比类型；
    # [7] 只比两根轴。于是"两层对同一个参数声明的**类型**不一致"这一整类缺陷
    # 没有任何机器判据 —— §150 那三处（`H.review` / `H.verify_fixes` 的
    # `dependencies` 声明成 `_OBJ`、`H.review_report` 声明成 `_ARR_S`，工具层四条
    # 一直是 array-of-objects）就是它漏的。当时的判据是**一条注释 + 一条单测**；
    # 本批把它变成导入期断言，并当场咬出第四处（`G.register_dependency.page_range`）。
    #
    # 为什么类型不一致是 error 而不是 warning：参数门读能力表、工具层校验读工具表，
    # 两层不一致的后果不是崩溃而是**判错**（合法派活被判死，或必然被拒的形状被放行），
    # 与 [7] 的"能力层低估风险轴"同一档：错了不吵，静默地错。
    #
    # 三条断言的顺序与 [8] 逐条同形，理由也同形：先报"表里有问题"，再报"判据自己没走遍"。
    type_coverage = param_type_coverage()
    PARAM_TYPE_COVERAGE.clear()
    PARAM_TYPE_COVERAGE.update(type_coverage)
    type_divergences = param_type_divergences()
    assert not type_divergences, (
        "两层对同一个参数声明的类型不一致："
        + "；".join(f"[{d.code}] {d.where}: {d.message}" for d in type_divergences)
    )
    assert not type_coverage["unread"], (
        "这些动作的唯一匹配工具，其 `params` schema **读不出来**（不是字面量，例如 "
        f"`params=some_variable`）：{type_coverage['unread']}。"
        "读不出来的工具在这条判据里是 unknown，而 unknown 多了以后『零分歧』"
        "就不再是证据（P16 真空通过）。两条出路：① 把 `params` 写成字面量 "
        "（这是判据能看见它的唯一形态，与 `_declared_side_effects` 同一套读源码口径）；"
        "② 若确实做不到，请把这条动作登记进一张显式表并写明理由 —— "
        "不许让它静默地落在判据外。"
    )
    assert type_coverage["compared"] > 0, (
        "两层参数类型对账**一对都没比过**（compared=0）—— 这不可能来自'两层都没声明类型'"
        "（能力表声明了 "
        f"{PARAM_ASSERT_COVERAGE.get('declared', 0)} 个 property，工具表也有各自的 schema），"
        "只可能来自判据自身失效（例如 `_tool_param_schemas()` 读不到任何工具模块）。"
        "零分歧此时不构成证据"
    )

    # [10] 反向那一格的读数（工具面有、动作面没有）。**只读数、不断言** —— 所有者 5b 授权的
    # 就是这一形状；牙在那条测试里（`_KNOWN_TOOL_ONLY_PARAMS` 与实测逐条对账 + 过期检测）。
    reverse_coverage = param_missing_in_action_coverage()
    PARAM_MISSING_IN_ACTION_COVERAGE.clear()
    PARAM_MISSING_IN_ACTION_COVERAGE.update(reverse_coverage)


#: 实测的"两层没有可比对对象"的动作（`two_layer_name_unmatched`）。
#:
#: 注意：这张表只管 `unmatched` 这一格（`handler_name` 在角色工具组里对应 0 个工具）。
#: 另一格 `ambiguous`（对应 ≥2 个工具 ⇒ 拒绝猜）不由它管，而由
#: `assert_capabilities` 第 [7b] 条的分区断言管：那一格今天实测是 0，
#: 但正因为它不在任何登记表里，"它悄悄长大"就没有任何地方会报 —— 分区断言
#: （三格互斥且穷尽 + `ambiguous` 必须为空）才是它的闸门。
#:
#: 为什么必须显式登记而不是"允许 info 级不管"：不加这张表时，`assert_capabilities`
#: 第 [7] 条只过滤 `level == "error"`，而真实树上 error 数为 0
#: ⇒ 那道断言恒真（`G-19`：门接上了，但只比对了 1 个动作）。
#: 有了这张表，对账面就不能静默缩小：新加一个对不上的动作会让
#: `import agentflow.capabilities` 失败，而不是悄悄多一条 info。
#:
#: 这些动作绝大多数是角色级方法（`C.hottest` / `D.ingest` / `H.review`），
#: 不是工具调用，因此两层本来就无可比对 —— 这一栏记录的是"没查成"，不是"查过了没问题"。
_KNOWN_UNMATCHED_ACTIONS: frozenset[str] = frozenset({
    "A.run_once", "A.run",
    "B.run_once", "B.reprocess_once", "B.run_reprocess",
    "B.decide_structural_duplicate", "B.resolve_structural_duplicate",
    "C.hottest", "C.paths", "C.cold", "C.gaps", "C.contradictions",
    "C.structural_duplicates", "C.handle",
    "D.probe_c", "D.ingest", "D.ingest_detailed", "D.trace_question", "D.trace_l3",
    "D.assess", "D.submit_gaps", "D.consider", "D.poll", "D.adjudicate",
    "D.research", "D.run_round", "D.write_report",
    # `draft/37` §115：从零做研究时"立起第一行问题"的通路 —— 它只写
    # `research_questions` 一行，工具层没有同名工具（不是转发，也没有对应的 tool 调用）。
    "D.propose_question",
    "E.run_script_experiment",
    "G.render", "G.refresh_markdown", "G.revise",
    "H.review",
    # `D-5`：`review_report` 转发 `review.report`，而工具名的最后一段是 `report`、
    # 本动作的 `handler_name` 是 `review_report` ⇒ `_matching_tool_name` 对不上
    # （唯一性约定要求逐字同名），于是它诚实地落进 `unmatched` 这一格。
    # 它不是工具调用（是 H 自己的方法），所以登记在这里而不是改工具名：
    # 改工具名会同时动 `READONLY_CALL_EXCEPTIONS` / `TOOL_WRITE_SETS` /
    # `agent_h` 的 writer 名单，而那是权限面的改动。
    "H.review_report",
    # `A.search_literature`（2026-09-30）：A 的**角色级**动作，不是工具调用。工具组里
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
    # `B.register_statement`（2026-10-02，`draft/37` §46）：B 的**角色级**动作，
    # 不是工具调用。它写的是通用表工具 `table.create(table="statements")` ——
    # 工具名的最后一段是 `create`，与 `handler_name` 对不上（唯一性约定要求逐字同名）。
    # 为什么不给它凑一个同名工具：`table.create` 是**通用**表操作（A–D 都能调、
    # 任何表都能建），而本动作是"命题台账那一行的三件套预检 + 出处核验 + 取号"——
    # 把两者配成一对会让两层类型对账去比两件不同的事（比 `table.create` 的
    # `table`/`row` 与本动作的 `statement_full`），那种"比上了"比诚实的"没比对"更坏。
    # 与 `A.search_literature` / `H.review_report` 两条同族。
    "B.register_statement",
    # `G.paper_package`（2026-10-03，`draft/37` §59）：G 的**角色级**动作，不是工具调用。
    # 它一次做三件工具的事（`doc.paper_render` / `doc.paper_compile` / `doc.paper_state`），
    # 所以没有哪一个工具名的最后一段等于 `paper_package`（唯一性约定要求逐字同名）。
    # 为什么不拆成三个动作：它们**必须连着做**（先渲染再编译，最后核锚才有意义 ——
    # 核锚放在最前面会让读数关于旧包），拆开就把"顺序"这件事留在调用方的记忆里，
    # 而真机实测主控连派三次都没能把包更新掉。与 `A.search_literature` /
    # `B.register_statement` / `H.review_report` 三条同族：诚实地登记"这一格没比对上"。
    "G.paper_package",
    # `A.shelf_search`（2026-10-06，J-53 / 裁决 2 族 1）：A 的**角色级**动作，不是工具调用。
    # 它调的是 `search.shelf` / `search.local`，两件工具名的最后一段是 `shelf` / `local`
    # ⇒ 与 `handler_name`（`shelf_search`）对不上（唯一性约定要求逐字同名）。
    # 为什么不给它凑一个同名工具：那两件是**通用只读检索**（A/C/H 都能调），而本动作是
    # "先列书架清单、再按需取逐字摘录"的一次编排 —— 配成一对会让两层类型对账去比
    # 两件不同的事。与 `A.search_literature` / `B.register_statement` / `G.paper_package`
    # / `H.review_report` 五条同族：诚实地登记"这一格没比对上"。
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
_PRINT_TYPE_COVERAGE = (
    f"[capabilities] 两层参数类型对账：比较 {PARAM_TYPE_COVERAGE.get('compared', 0)} 对"
    f"（动作, property），读到 {PARAM_TYPE_COVERAGE.get('tools_read', 0)} 个工具的 schema，"
    f"没比对 {len(PARAM_TYPE_COVERAGE.get('unread', []))} 个；"
    f"反向（工具面有/动作面没有）：比过 {PARAM_MISSING_IN_ACTION_COVERAGE.get('pairs', 0)} 个动作，"
    f"缺口 {PARAM_MISSING_IN_ACTION_COVERAGE.get('gaps', 0)} 处"
    f"（已登记 {len(_KNOWN_TOOL_ONLY_PARAMS)} 个动作）"
)
print(_PRINT_TYPE_COVERAGE, file=sys.stderr)
