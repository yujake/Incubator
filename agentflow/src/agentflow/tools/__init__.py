"""工具层装配：把各工具模块按角色组装成一个 `ToolRegistry`。

## 为什么要按角色组装，而不是给所有智能体同一套工具

工具不只是能力，也是权限面。A 不该能调 `research.submit_gap`（那是 D 的决策），
B 不该能调 `search.download`（下载是 A 的职责，且它是网络副作用）。
把"谁能用什么"固化在这里，比写在提示词里可靠得多 —— 提示词可以被绕过，注册表不能。

## 为什么用签名反射而不是写死参数

各工具模块的 `register()` 需要的依赖不同（`table_tools` 要 `store`，`fs_tools` 要 `root`，
`graph_tools` 可能只要一个已建好的 `graph`）。这里按 `inspect.signature` 只传它声明要的
关键字参数，于是模块之间可以各自演进而不用改这里 —— 少一个必须同步维护的耦合点。

模块缺失时不报错，只记录：这些模块是并行开发的，任何一个还没落地都不该让整个工具层不可用。
缺失项会出现在 `build_registry()` 返回的 `skipped` 里，便于诊断。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

# `EFFECT` / `EXTERNAL` / `SANDBOX_AVAILABLE` 曾经也在这里被 import（`axes-5`）。
# 先核实：本文件对这三个名字的使用次数各 0 次，且三个都不在 `__all__` 里。
# 核实后的处置分两种 —— "本文件没用"与"没有消费者"是两件事：
#
#   - `EFFECT` / `EXTERNAL` 删掉。全仓库没有任何地方从 `agentflow.tools` 顶层取它们；
#     词表的落位是 `tools/base.py`（定义）与 `capabilities.py`（本层自己那一份字面量
#     加导入期交叉断言），本文件不参与，要用请直接 `from .base import`。
#     留着它们会被读成"词表单一来源就在本文件"（`axes-5` 的影响面）。
#   - `SANDBOX_AVAILABLE` 保留，因为有一个消费者从本层取它：
#     `tests/test_r4_roles_surface.py` 里的 `monkeypatch.setattr(T, "SANDBOX_AVAILABLE", True)`。
#     删掉它会让那个用例以 AttributeError 变红，而 `tests/` 不在本轮授权改动范围内。
#     它保留时，下面这句必须写在眼前，否则它正是 `axes-5` 说的那个误导性极强的死导入：
#     SANDBOX_AVAILABLE 的唯一设置点是测试里的 monkeypatch（`tests/*` 对
#     `tools.base.SANDBOX_AVAILABLE` 的 setattr）；装配层不设它，本文件也没有任何
#     `sandbox_available=` 参数入口。它在这里只是一个名字，不要读成
#     "沙箱可用性在装配层设置"（`axes-3` 要防的正是这个错误结论）。
from .base import (
    READONLY_CALL_EXCEPTIONS,
    SANDBOX_AVAILABLE,  # noqa: F401  - 只为顶层再导出，理由见上；唯一的消费者在 tests/ 里
    PARAM_SEAMS,
    ParamError,
    stale_tool_param_seams,
    tool_param_seam_violations,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    fail,
    ok,
    tool,
)

# `R4-AN-4` / `N-5`：`SIDE_EFFECTS` 在这里 import 进来，只为一件事 ——
# 把下面的写等级登记表与第一根轴的词表钉成一个二分，且这条判据必须在
# `agentflow.tools` 被导入时就已经跑过（落点只能在装配层，`base.py` 先于
# 本文件的 `SIDE_EFFECTS_WRITE` 执行，它自己看不见这张表）。
# 它不是"本文件又声明了一份词表"：词表的定义落位仍然是 `tools/base.py`，
# 这里拿的是同一个对象的引用，别名加 `_BASE_` 前缀是为了让读源码的人第一眼
# 看出"这是外来的那一份"，而不是本文件的第二份字面量。
from .base import SIDE_EFFECTS as _BASE_SIDE_EFFECTS

#: 智能体角色。顺序无关，但保持稳定便于日志可比。
#:
#: A/B/C/D 是最初的文献流水线；E/F/G/H 是面向"数学研究"补上的四个角色：
#:   E —— 数值实验与形式化验证（产出证据，且必须标注证据等级）
#:   F —— 多轮难题攻坚（产出过程，且必须有三维预算与终止条件）
#:   G —— 论文撰写（产出稿件，每条断言必须带引用）
#:   H —— 审校（产出发现，且发现本身必须有证据）
#: 它们与 A–D 一样遵循"角色即权限面"：H 只读、C 只读，是为了让
#: "改稿的人"与"审稿的人"在结构上不能是同一个人。
#: ⚠️ 单一来源：角色名单定义在 `schema.ROLES`，这里只是把它引过来。
#:
#: 为什么不能各写一份：`schema` 需要"role 是否合法"的判据（`Task.validate`），
#: 而 `tools` 需要"按角色过滤工具面"。两处各写一份名单，就会出现
#: "schema 认为合法的角色，工具层不认"这种没有任何报错的分裂 ——
#: 这正是 FC-03（跨模块字符串约定必须集中定义）要防的事。
#: `schema` 不 import `tools`（依赖方向是 tools -> schema），所以放 schema 里没有循环。
from ..schema import ROLES, CONDUCTOR_ROLE  # noqa: E402  (放在这里是为了让上面的说明紧贴定义)

#: 能持有工具的角色名 = 可被召唤的 A–H + 主控 M。
#:
#: 为什么主控也要在工具词汇里：`schema.ROLES` 回答的是"谁可以被召唤"（主控不在里面，
#: `NON_SUMMONABLE` 明写），而工具层回答的是"谁能拿工具"。这两件事必须分开：
#: 实测（2026-09-28）`registry.for_role("M") == []` —— 主控此前一件工具都没有，
#: 于是"派活"这件事在它手上没有动作可用（一句需求要落地只能靠调用方替它拼 plan）。
#: 把主控加进工具词汇不会让它变得可被召唤：可召唤性只由
#: `capabilities.ALLOWED_EDGES` / `NON_SUMMONABLE` 决定。
TOOL_ROLES: tuple[str, ...] = tuple(ROLES) + (CONDUCTOR_ROLE,)

#: 只读角色：它们的工具面里不允许出现任何写工具，无论 `ToolSpec.roles` 怎么声明。
#:
#: - C（只读图分析）：一旦 C 能写，它就成了"绕过 B 引文回验"的写入路径，
#:   而 B 的引文逐字回验是全系统唯一能自动发现幻觉引文的地方。
#: - H（审校）：若审校者能直接改稿，它就同时是"发现者"与"修正者"，
#:   于是"发现问题"与"掩盖问题"在结构上无法区分。
#:
#: 实现不在这个常量本身，而在 `ToolRegistry.for_role`（结构性过滤）——
#: 常量只是这条约束的单一来源（FC-03）。
READ_ONLY_ROLES = ("C", "H")

#: 有写副作用的等级 —— 第一根轴词表里"写"的那一半（另一半是下面的 `_NON_WRITE_EFFECTS`）。
#: 单列一份是为了让
#: `READ_ONLY_ROLES` 的判据在一个地方可读（FC-07：`side_effect` 是一等公民）。
#:
#: `X-91.5-5` 更正：这两行此前写的是"与 `base.SIDE_EFFECTS` 的尾部一致"——
#: 那是一句按位置说的话：词表是元组，"尾巴"既没点明是哪一半，
#: 也会在有人往词表末尾追加一个非写等级时当场变成假话，而那种假话不会报错。
#: 准确的说法是一个二分，而且它已经被机器钉住：下面的
#: `_check_write_levels_are_registered()` 在 `agentflow.tools` 被导入时断言
#: "词表 = 写等级 ∪ 非写等级、两栏不相交、两栏都取自词表"。
#: 措辞自此与判据是同一件事（审计者判这一处为非 finding，本轮只做精确化，不改取值）。
#:
#: B3 收官之后这里只剩 `write_local`：遗留取值 `network` 已从两处词表里删掉
#: （它曾是"迁移期行为不变"的一半 —— 声明了它的工具继续被只读角色剥离），
#: 于是 `external == "exec"` 的剥离判据（`ToolRegistry.for_role`）是只读角色
#: 在"写"之外唯一还要看的那一根轴。
#:
#: 两处词表不能分批删：`capabilities.assert_capabilities` 第 5 条断言
#: `set(capabilities.SIDE_EFFECTS) == set(base.SIDE_EFFECTS)`，只删一处会
#: 导入期就炸。这是好事（"删一半"不可能静默），但排期上必须知道它们是
#: 一个原子改动。
#:
#: ## `R4-AN-4` / `N-5`：光有两处词表的相等还不够，写等级这一份也要被钉住
#:
#: 上面那句只管词表自己的两份字面量。它管不住另一种改法：往第一根轴加一个写等级、
#: 却忘了把它登记进这张写等级表。`for_role` 的剥离判据是
#: `s.side_effect in SIDE_EFFECTS_WRITE`，新取值不在表里就不算写工具，
#: 于是只读角色 C/H 会静默拿到它（`R4` 用副本注入实测：两处词表同步加
#: `write_remote` 之后导入成功、`for_role('C')` / `for_role('H')` 都拿到那个工具、
#: `call(..., role='C')` 返回 ok=True）。这正是 `.noai-paths` 第七类的原文
#: "测试全绿、上线即越权"，而且两处落点都在 FC-27 禁改区里。
#:
#: 判据是下面那条模块级断言（`agentflow.tools` 一被导入就跑）：第一根轴的词表
#: 必须恰好被"非写等级"与"写等级"两栏穷举划分，两栏不相交、都由这里登记。
SIDE_EFFECTS_WRITE = ("write_local",)

#: 第一根轴上"不是写"的那些等级。它与 `SIDE_EFFECTS_WRITE` 一起构成词表的二分。
#:
#: 为什么把"非写"也写成一份显式名单：只写"写等级 ⊆ 词表"挡不住漏登记
#: （新加一个写等级、只改词表不改这张表时那个方向的判据仍然是绿的）。
#: 把两栏都写下来，"词表 = 非写 ∪ 写"这条等式才有分辨力 —— 新取值落在哪一栏
#: 都必须由人显式决定，而不是默认落进"不算写"那一栏。
_NON_WRITE_EFFECTS = ("none", "read")


def _check_write_levels_are_registered(
    side_effects: tuple[str, ...] = _BASE_SIDE_EFFECTS,
    write_levels: tuple[str, ...] = SIDE_EFFECTS_WRITE,
    non_write: tuple[str, ...] = _NON_WRITE_EFFECTS,
) -> None:
    """导入期交叉断言：写等级登记表与第一根轴的词表必须互为补充（`R4-AN-4` / `N-5`）。

    四条合起来是一个二分：两栏都取自词表、互不相交、并集恰好是词表。
    只留其中一条都会留下一个方向的静默漂移（漏登记 / 登记了不存在的等级 /
    同一个等级同时被登记成写与非写 / 词表里有谁都没认领的等级）。

    两个形参只为让判据能被单独喂表（负控与单元测试用）：真正跑的那一次
    在模块末尾用默认值调用，读的就是真表。形参不许成为第二条产生路径。
    """
    stray = sorted(set(write_levels) - set(side_effects))
    assert not stray, (
        f"SIDE_EFFECTS_WRITE 里的 {stray} 不在 SIDE_EFFECTS{tuple(side_effects)} 里 —— "
        "写等级登记表引用了不存在的等级，`for_role` 的剥离判据会拿一个词表外的字符串去比"
    )
    unclaimed_non_write = sorted(set(non_write) - set(side_effects))
    assert not unclaimed_non_write, (
        f"_NON_WRITE_EFFECTS 里的 {unclaimed_non_write} 不在 SIDE_EFFECTS{tuple(side_effects)} 里 —— "
        "非写等级名单同样必须取自第一根轴的词表"
    )
    both = sorted(set(write_levels) & set(non_write))
    assert not both, (
        f"{both} 同时被登记成写等级与非写等级 —— 只读角色的剥离判据读的是写等级这一栏，"
        "同一个等级落在两栏里等于这条判据今天算不算数取决于读取顺序"
    )
    unregistered = sorted(set(side_effects) - set(write_levels) - set(non_write))
    assert not unregistered, (
        f"SIDE_EFFECTS 里的 {unregistered} 既不在 SIDE_EFFECTS_WRITE{tuple(write_levels)} 里、"
        f"也不在 _NON_WRITE_EFFECTS{tuple(non_write)} 里 —— 新加的等级必须显式落进一栏。"
        "落进写等级那一栏才会被只读角色的结构性剥离看见；默认当成"
        "『不是写』会让只读角色静默拿到一个写工具（`R4-AN-4` / 台账 `N-5`）"
    )


_check_write_levels_are_registered()

#: 模块名 -> 它需要的依赖键（值从 build_registry 的 kwargs 里按名取）。
#:
#: ## `P-14` 之后：工具面与可调用面是两个集合
#:
#: `ToolRegistry.call` 现在要求调用方声明角色（`role=`，或装配期用
#: `ToolRegistry.scoped_to(role)` 绑定），判据与 `for_role` 共用同一份私有谓词。
#: 两个面刻意分开命名：
#:
#: - 工具面（`ToolRegistry.for_role`）：这个角色声明能拿到什么。
#:   只读角色在这里被结构性剥离写工具与 `external="exec"`，`role_filter_notes` 留痕。
#: - 可调用面（`ToolRegistry.call_surface`）：工具面 + 逐条登记的落库代理
#:   （`base.READONLY_CALL_EXCEPTIONS`，今天只有 `H` 的三个 `review.*`）。
#:
#: 第二个集合只允许由那张显式登记表产生 —— 没有第二条产生路径。`H` 的落库代理
#: 是它的第一个用户（`agent_h.AgentH.writers`）。
_MODULES: tuple[str, ...] = (
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
    "manuscript_tools",
)

#: `_MODULES` 里每个模块产出的工具名组前缀（`verify_tools` ⇒ `verify`）。
#:
#: 从模块名机械派生，不另写一份名单：接缝报表（`base.PARAM_SEAMS`）的键是
#: 工具名，而"这个名字的组前缀有没有人产出"是导入期唯一能核的事实 ——
#: 一个拼错的键（`verfy.run_experiment`）在接缝表里看起来完全正常，
#: 而它永远不会命中任何工具，于是那条接缝静默失效：既不生效、也没人报。
_TOOL_GROUP_PREFIXES: tuple[str, ...] = tuple(m[: -len("_tools")] for m in _MODULES)
assert all(p and not p.endswith("_") for p in _TOOL_GROUP_PREFIXES), (
    f"_TOOL_GROUP_PREFIXES 从 _MODULES 派生失败：{_TOOL_GROUP_PREFIXES} —— "
    "模块名的命名约定变了，派生这一步必须跟着改（否则下面那条接缝判据会变成空转）"
)


def _check_param_seams_are_registered(
    seams: Mapping[str, Mapping[str, str]] = PARAM_SEAMS,
    groups: tuple[str, ...] = _TOOL_GROUP_PREFIXES,
) -> None:
    """导入期交叉断言：参数接缝表的键与理由必须是可用的（台账 `N-5` 的工具侧）。

    三条，缺一条就留下一个静默方向：

    1. 键必须是 `组.动作` 形态，且组前缀由 `_MODULES` 里某个模块产出
       —— 拼错的键会让那条接缝永远不命中（"登记了"与"生效了"是两件事）；
    2. 理由串必须非空 —— 缺理由的登记与没登记在证据上一样（"写不出理由的，
       就该改代码而不是加例外"，与 `READONLY_CALL_EXCEPTIONS` 的纪律同族）；
    3. 一个键下的 property 名必须非空字符串。

    为什么落点在导入期而不是等 `ToolRegistry.register`：`register` 只知道
    "某个工具注册了"，看不见"接缝表里有没有指着空气的键"（工具模块是
    `build_registry` 惰性 import 的，导入本模块时树上一个 `ToolSpec` 都还没有）。
    参数「面」的判据在注册期（`base.check_param_seams`），接缝「表」的判据在这里。

    两个形参只为让判据能被单独喂表（负控与单元测试用）；真正跑的那一次
    在下面用默认值调用，读的就是真表。
    """
    bad_shape = sorted(k for k in seams if not isinstance(k, str) or "." not in k)
    assert not bad_shape, (
        f"PARAM_SEAMS 的键 {bad_shape} 不是 `组.动作` 形态 —— 工具名只有这一种形态，"
        "拼错的键不会命中任何工具，于是那条接缝静默失效"
    )
    unknown_group = sorted({k.split(".")[0] for k in seams} - set(groups))
    assert not unknown_group, (
        f"PARAM_SEAMS 里的组前缀 {unknown_group} 不由任何工具模块产出"
        f"（_MODULES 派生出的是 {sorted(groups)}）⇒ 这些接缝永远不会命中任何工具。"
        "要么改工具名，要么改 `_MODULES`，要么删掉这条登记"
    )
    for tool, props in sorted(seams.items()):
        assert props, f"PARAM_SEAMS[{tool!r}] 是空的 —— 空条目既没理由也没内容，删掉它"
        for prop, why in sorted(props.items()):
            assert str(prop).strip(), f"PARAM_SEAMS[{tool!r}] 里有一个空的 property 名"
            assert str(why or "").strip(), (
                f"PARAM_SEAMS[{tool!r}][{prop!r}] 没有理由串 —— "
                "登记而不写理由，与没登记在证据上是一回事（写不出理由就该改 handler）"
            )


_check_param_seams_are_registered()


@dataclass
class RegistryBuild:
    """装配结果。`skipped` 让"某个模块没装上"变成可见的事实，而不是静默少几个工具。"""

    registry: ToolRegistry
    loaded: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    #: 装配期"参数面"判据真的走过了几个工具（`N-5` 的工具侧覆盖率读数）。
    #:
    #: 为什么要有这个数字：`register` 里那条判据的结论是"零违反"，而
    #: "零违反"与"一个工具都没核到"在输出上完全一样（P16 的真空通过）。
    #: 真值由 `build_registry` 在装配末尾数出来，测试断言它等于注册的工具数。
    params_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.skipped

    def summary(self) -> dict:
        return {
            "tools": self.registry.names(),
            "count": len(self.registry),
            "loaded_modules": self.loaded,
            "skipped_modules": self.skipped,
            # `N-5` 的覆盖率读数：参数面判据走过了几个工具（见字段注释）。
            "params_checked": self.params_checked,
            # FC-17 的接线状态：可打印的事实，不是"去看源码猜"。
            # `None` = 没启用；一个对象 = 已启用（其 `threshold_chars` 等值可见）。
            "context_budget": (
                None
                if getattr(self.registry, "default_budget", None) is None
                else {
                    "enabled": True,
                    "threshold_chars": getattr(self.registry.default_budget, "threshold_chars", None),
                    "head_chars": getattr(self.registry.default_budget, "head_chars", None),
                    "tail_chars": getattr(self.registry.default_budget, "tail_chars", None),
                    "max_inline_bytes": getattr(self.registry.default_budget, "max_inline_bytes", None),
                    "spill_dir": getattr(self.registry.default_budget, "spill_dir", None),
                }
            ),
        }


def _call_register(mod: Any, registry: ToolRegistry, deps: dict[str, Any]) -> int:
    """把模块的工具装进注册表。返回新增的工具数。

    容忍三种约定 —— 这些模块是并行开发的，为"用哪种入口"去返工不值得，
    但必须只有这三条路，否则就成了"随便怎么写都能装上"的糊涂账：
      1. `register(registry, **deps)`   —— 首选
      2. `install(registry, ...)`        —— 等价别名
      3. 模块级 `ALL_TOOLS: list[ToolSpec]`  —— 纯声明式
    """
    before = len(registry)

    fn = getattr(mod, "register", None) or getattr(mod, "install", None)
    if fn is not None:
        sig = inspect.signature(fn)
        kwargs = {}
        for pname, p in sig.parameters.items():
            if pname == "registry":
                continue
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            if pname in deps:
                kwargs[pname] = deps[pname]
            elif p.default is inspect.Parameter.empty:
                # 模块要求一个我们没提供的依赖 —— 明确报出来，而不是传 None 让它后面炸
                raise ToolError(f"{mod.__name__}.{fn.__name__}() 需要依赖 {pname!r}，但装配时未提供")
        fn(registry, **kwargs)
        return len(registry) - before

    specs = getattr(mod, "ALL_TOOLS", None)
    if specs:
        for s in specs:
            if isinstance(s, ToolSpec):
                registry.register(s)
            else:
                raise ToolError(f"{mod.__name__}.ALL_TOOLS 里含非 ToolSpec 元素：{type(s).__name__}")
        return len(registry) - before

    raise ToolError(f"{mod.__name__} 既没有 register()/install()，也没有 ALL_TOOLS")


def build_registry(
    *,
    store: Any = None,
    workspace_root: str | Path | None = None,
    graph: Any = None,
    roles: Iterable[str] = ROLES,
    name: str = "agentflow",
    strict: bool = False,
    context_budget: Any = None,
    config: Any = None,
    conductor: Any = None,
    role_registry: Any = None,
    session_root: str | Path | None = None,
    sid: str | None = None,
) -> RegistryBuild:
    """组装工具层。

    参数
    ----
    store : Store | None
        数据表工具必需；为 None 时相关模块会被跳过（并记录原因）。
    workspace_root : Path | None
        文件工具的工作区根（沙箱边界）。为 None 时用 `<store.root>`。
    graph : RelationGraph | None
        C 的图对象；为 None 时 `graph_tools` 的只读查询类工具仍可注册（它们可自行构建）。
    strict : bool
        为 True 时，任何模块跳过都抛异常 —— 供验收脚本使用，防止"少了一半工具还以为装好了"。
    session_root, sid : 会话身份（`draft/37` §63，修法 B）
        这一趟运行「是谁」：会话记录的根与这一趟的会话号。装配期注入，工具层不替它猜。
        为什么必须是装配期输入：真机实测第 11 趟（`sessions/real11.jsonl`）主控在运行内
        调 `conductor.closing` 得到 `can_close: true`，而同一次运行外部带 `sid=real11`
        的读数报 `failed: ['user_pending']` —— 工具体当时按 `sid=None` 读到了缺省会话
        `sessions/<今天>.jsonl`，于是"问了还没答"被读成"没问过"。「假绿」，
        且它只在运行内出现，外面怎么看都是对的。
        `sid` 不给 ⇒ 传下去的是 `closing.NO_SESSION` ⇒ 那一格记 `unknown`
        （不是 pass，也不回落成"读今天那份"：三态纪律）。
    """
    reg = ToolRegistry(name=name)

    # ---- FC-17：把上下文预算装到注册表上（装配期决定，而不是靠每个调用点记得传）
    #
    # `config` 给整份配置时，从它的 `context_budget` 块取；没有该块 ⇒ 不启用
    # （三态：没配 ≠ 用默认值，见 `contextbudget.load_budget`）。
    # 显式传 `context_budget=` 优先于 `config=`。
    if context_budget is None and config is not None:
        from ..contextbudget import load_budget

        context_budget = load_budget(config)
    if context_budget is not None:
        # 装配期就把类型错了的关掉 —— 否则它会一路活到第一次 `call()` 才炸，
        # 而那时错误信息里已经没有"是装配时配错的"这个线索了。
        try:
            context_budget.validate()
        except AttributeError as e:
            raise ToolError(
                f"context_budget 必须是一个 ContextBudget 对象（收到 {type(context_budget).__name__}）：{e}"
            ) from None
    reg.default_budget = context_budget
    root = Path(workspace_root) if workspace_root else (Path(store.root) if store is not None else None)
    # spill 要有地方落：默认落在工作区根下的 `spill/`。没有这一句，
    # `default_budget` 生效时剪枝后的内容想落盘却没有 root（spill 那一件套走不到）。
    # ⚠️ 必须放在 `root` 算出来之后 —— 先写的版本把它放在 `root = ...` 之前，
    # 于是 `UnboundLocalError`。好在那是装配期就暴露的失败，不是潜伏到某次调用。
    reg.default_spill_root = root
    deps: dict[str, Any] = {
        "store": store,
        "root": root,
        "workspace_root": root,
        "graph": graph,
        "roles": tuple(roles),
        # 主控工具（`conductor_tools`）要的是"这一会话的主控实例"或"角色接线"：
        # 由调用方注入，工具层不替它猜（猜错的形态是派出去的活没人接，而台账照样绿）。
        "conductor": conductor,
        "role_registry": role_registry,
        # 会话身份（`draft/37` §63，修法 B）：同样是装配期注入，工具层不替它猜。
        # `sid` 为空 ⇒ 这一趟「没有」会话身份，`conductor.closing` 的 `user_pending`
        # 记 `unknown`。刻意不在这里回落到 `sessions.session_id()`：
        # 那个缺省值是"今天那段会话"，与"这一趟是哪一段"是两件事，
        # 而把它俩折叠起来正是第 11 趟那次运行内假绿的病因。
        "session": {"root": str(session_root or root or ""), "sid": str(sid or "")},
    }

    loaded: list[str] = []
    skipped: list[dict] = []
    for mod_name in _MODULES:
        try:
            mod = __import__(f"{__name__}.{mod_name}", fromlist=[mod_name])
        except Exception as e:  # noqa: BLE001
            skipped.append({"module": mod_name, "stage": "import", "error": f"{type(e).__name__}: {e}"})
            continue
        try:
            added = _call_register(mod, reg, deps)
        except Exception as e:  # noqa: BLE001
            skipped.append({"module": mod_name, "stage": "register", "error": f"{type(e).__name__}: {e}"})
            continue
        if added == 0:
            # register() 跑通了但一个工具都没加 —— 这几乎总是 bug（比如 roles 不匹配被全过滤）
            skipped.append({"module": mod_name, "stage": "register", "error": "register() 未注册任何工具"})
        else:
            loaded.append(mod_name)

    # ⚠️ 断言所有工具声明的角色都在 ROLES 里。
    #
    # 为什么必须有这一句：`roles` 是跨模块的字符串约定。曾经 `research_tools` 写的是
    # `roles=("agent-D",)` 而全项目其余地方按 `"D"` 过滤 —— 结果是
    # `build_for_role('D')` 静默少 5 个工具，没有任何地方报错，直到测试才被抓到。
    # 这类"字符串拼法不同导致静默失配"的 bug，唯一的通用解法就是在校验点上炸出来。
    bad_roles: dict[str, list[str]] = {}
    for spec in reg._specs.values():
        # 与注册期那处（`base.ToolRegistry._reject_unknown_roles`）同一条判据、同一个词表：
        # `TOOL_ROLES` = 可被召唤的 A–H + 主控 M。两处分开写会让"注册期放行、装配期拒绝"
        # 这种自相矛盾的行为出现（实测撞过：只改了一处，strict=True 的装配就炸）。
        unknown = [r for r in spec.roles if r not in TOOL_ROLES]
        if unknown:
            bad_roles[spec.name] = unknown
    if bad_roles:
        msg = (
            f"以下工具声明了不在 TOOL_ROLES{TOOL_ROLES} 里的角色：{bad_roles}。"
            "角色名是跨模块约定，拼法不一致会让 build_for_role() 静默漏掉这些工具。"
        )
        if strict:
            raise ToolError(msg)
        skipped.append({"module": "<roles>", "stage": "validate", "error": msg})

    # ⚠️ 遗留取值 `network` 的装配期翻译检查已随 B3 收官删除。
    #
    # 它曾经在这里做什么：`side_effect="network"` 的逐工具原意（它到底写不写
    # 我们的东西）写在 `base.LEGACY_EFFECTS_BY_TOOL` 里，而新加一个声明了
    # `network` 的工具却忘了登记时，`ToolSpec.effect` 会退回翻译表的默认值 ——
    # 于是"写盘的事实被丢掉"会重演，且没有任何地方报错。
    #
    # 为什么现在可以不查：那个取值本身已从 `base.SIDE_EFFECTS` 里删掉，
    # 任何声明 `network` 的 `ToolSpec` 在 `__post_init__` 就被 `ValueError` 拒了
    # （负控见 `tests/test_tools_base.py`）。判据从"装配期查表"前移成
    # "构造期拒绝"：更强的形态，且少了一张必须与真实树同步维护的表。

    # ---- `N-5`（工具侧）：参数接缝表的「整体」判据（逐条工具那条在 `register` 里）
    #
    # `register` 里的 `check_param_seams` 是逐工具 fail-closed 的；它看不见
    # 两种"整体"事实，而这两种都只能在这里核（装配完才知道树上有哪些工具）：
    #   ① 接缝表里有指向不存在工具的键（拼错 / 工具改名后留下的孤儿）；
    #   ② 接缝表里的条目现在「已经不需要了」（handler 开始收得下它了）——
    #      只增不减的登记表会烂成噪音，噪音里的真违约就没人看了。
    # 覆盖率（`params_checked`）单独计数：判据的结论是"零违反"，而
    # "零违反"与"一个工具都没核到"在输出上一模一样（P16）。
    #
    # 处置口径与上面那条 `roles` 判据逐字一致：非严格档记进 `skipped`（可见），
    # 严格档直接抛。「不改」成无条件抛：`build_registry` 允许部分模块缺席
    # （那是它的既定契约），在这里无条件抛会把"某个并行开发的模块还没落地"
    # 升级成"整个工具层不可用"。
    params_checked = sum(1 for _ in reg._specs.values())
    stale_seams = stale_tool_param_seams(reg._specs)
    if stale_seams:
        msg = (
            f"PARAM_SEAMS 里这些条目已经不需要了或指向不存在的工具：{stale_seams}。"
            "那个 property 要么已被 handler 接受，要么工具名已经不是注册表里的名字 —— "
            "请删掉这些登记（登记表不许烂成噪音，同 `capabilities.stale_param_seams`）"
        )
        if strict:
            raise ToolError(msg)
        skipped.append({"module": "<param-seams>", "stage": "validate", "error": msg})

    if strict and skipped:
        raise ToolError(f"严格模式下不允许模块被跳过：{skipped}")
    return RegistryBuild(registry=reg, loaded=loaded, skipped=skipped, params_checked=params_checked)


def build_for_role(role: str, **kwargs: Any) -> RegistryBuild:
    """只装某个角色的工具子集。"""
    build = build_registry(**kwargs)
    filtered = ToolRegistry(name=f"{kwargs.get('name', 'agentflow')}:{role}")
    for spec in build.registry.for_role(role):
        filtered.register(spec)
    return RegistryBuild(registry=filtered, loaded=build.loaded, skipped=build.skipped,
                         params_checked=build.params_checked)


__all__ = [
    "ROLES",
    "READ_ONLY_ROLES",
    "READONLY_CALL_EXCEPTIONS",
    "PARAM_SEAMS",
    "SIDE_EFFECTS_WRITE",
    "RegistryBuild",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ParamError",
    "build_for_role",
    "build_registry",
    "fail",
    "ok",
    "tool",
]
