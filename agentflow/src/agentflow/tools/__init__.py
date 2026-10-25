"""工具层装配：把各工具模块按角色组装成一个 `ToolRegistry`。

## 为什么要按角色组装，而不是给所有智能体同一套工具

工具不只是能力，也是权限面。A 不该能调 `research.submit_gap`（那是 D 的决策），
B 不该能调 `search.download`（下载是 A 的职责，且它是网络副作用）。
把"谁能用什么"固化在这里，比写在提示词里可靠得多 —— 提示词可以被绕过，注册表不能。

## 唯一的例外：通用能力没有"谁能用"这回事

业主裁定（`UNIVERSAL_TOOLS` 一节逐字引了原话）：通用能力不该出现"谁能用"这个说法。
于是本文件多了一张受控集合 `UNIVERSAL_TOOLS`，它的判据不是"谁被允许用"，
而是"它写不写知识表" —— 只写通信与簿记（`tasks` 的 notice 行 / 板项、事件流、
`out/clock` 的状态与唤醒标记）的工具对全部角色开放，包括只读角色 C/H/V。
这条例外刻意的形状：进集合要写下理由，写知识表则判据直接红且不发给只读角色。

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

# `EFFECT` / `EXTERNAL` / `SANDBOX_AVAILABLE` 曾经也在这里被 import（`axes-5`）：本文件对这三个名字的使用
# 次数各 0 次、也都不在 `__all__` 里，但"本文件没用"与"没有消费者"是两件事：
# - `EFFECT` / `EXTERNAL` 删掉 —— 全仓库没有地方从 `agentflow.tools` 顶层取它们；词表的落位是
#   `tools/base.py` 与 `capabilities.py`，留着会被读成"词表单一来源就在本文件"（`axes-5` 的影响面）。
# - `SANDBOX_AVAILABLE` 保留：`tests/test_r4_roles_surface.py` 用
#   `monkeypatch.setattr(T, "SANDBOX_AVAILABLE", True)` 取它。它唯一的设置点就是测试里的 monkeypatch（装配层
#   不设它，本文件也没有 `sandbox_available=` 入口），不要读成"沙箱可用性在装配层设置"（`axes-3` 要防的正是
#   这个错误结论）。
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
#: A/B/C/D 是最初的文献流水线；E/F/G/H 是面向"数学研究"补上的四个角色（E 数值实验与形式化验证 / F 多轮
#: 难题攻坚 / G 论文撰写 / H 审校），它们与 A–D 一样遵循"角色即权限面"：H 只读、C 只读，是为了让"改稿的
#: 人"与"审稿的人"在结构上不能是同一个人。单一来源：角色名单定义在 `schema.ROLES`，这里只是把它引过来。
#: 为什么不能各写一份：`schema` 需要"role 是否合法"的判据（`Task.validate`），而 `tools` 需要"按角色过滤工具
#: 面"；两处各写一份就会出现"schema 认为合法的角色，工具层不认"这种没有报错的分裂 —— 这正是 FC-03（跨模块
#: 字符串约定必须集中定义）要防的事。`schema` 不 import `tools`（依赖方向是 tools -> schema），所以没有循环。
from ..schema import ROLES, CONDUCTOR_ROLE  # noqa: E402  (放在这里是为了让上面的说明紧贴定义)

#: 角色可见性的唯一判定入口（业主 2026-10-22：「在Lean开关没开时隔绝L」）。
#: 本文件读它两次：`TOOL_ROLES` 与装配期"Lean 专属模块要不要装"。两次都不自己再判
#: 一遍开关 —— 判定真身在 `leanscope.lean_reading()`，改开关立刻跟着变（没有缓存）。
from .. import leanscope as _LEANSCOPE  # noqa: E402

#: 能持有工具的角色名 = 可被召唤的 A–H + 主控 M。
#:
#: 为什么主控也要在工具词汇里：`schema.ROLES` 回答的是"谁可以被召唤"（主控不在里面，
#: `NON_SUMMONABLE` 明写），而工具层回答的是"谁能拿工具"。这两件事必须分开：
#: 实测（2026-09-28）`registry.for_role("M") == []` —— 主控此前一件工具都没有，
#: 于是"派活"这件事在它手上没有动作可用（一句需求要落地只能靠调用方替它拼 plan）。
#: 把主控加进工具词汇不会让它变得可被召唤：可召唤性只由
#: `capabilities.ALLOWED_EDGES` / `NON_SUMMONABLE` 决定。
#:
#: 业主 2026-10-22（「在Lean开关没开时隔绝L」）：这份名单刻意仍然完整（含 L）。
#: 理由是它有两个不同的用途，而混成一个是会松掉一道真门：
#:   - 它是声明词表：`ToolSpec.roles` 里能出现哪些角色名由它判（`P-1` 的
#:     "拼错了名字"闸门）。把 L 从这里删掉，等于让 `roles=tuple(S.ROLES)` 这种
#:     "全体角色"的写法变成拼写错误 ⇒ `table_tools` / `conductor_tools` /
#:     `manuscript_tools` 会整模块装不上（实测），而那与业主的要求毫无关系；
#:   - 它是读数来源：`cli tools` 的逐角色计数与 skills 的工具面普查都从它派生。
#:     这些读数是面向人的，所以它们逐个过 `leanscope.visible_roles`（见那两处）。
#: "L 在开关关着时不存在"这件事落在更下面一层：`ToolRegistry._role_surface` 对
#: `leanscope.is_hidden` 的角色直接返回空面（工具面与可调用面都是空）。
TOOL_ROLES: tuple[str, ...] = tuple(ROLES) + (CONDUCTOR_ROLE,)

#: 只读角色：它们的工具面里不允许出现任何写工具，无论 `ToolSpec.roles` 怎么声明。
#: - C（只读图分析）：一旦 C 能写，它就成了"绕过 B 引文回验"的写入路径，而 B 的引文逐字回验是全系统唯一
#:   能自动发现幻觉引文的地方。
#: - H（审校）：若审校者能直接改稿，它就同时是"发现者"与"修正者"，于是"发现问题"与"掩盖问题"在结构上
#:   无法区分。
#: 实现不在这个常量本身，而在 `ToolRegistry.for_role`（结构性过滤）—— 常量只是这条约束的单一来源（FC-03）。
#: V（验证者）同理但落点不同：它不写任何「表」（`capabilities.WRITE_SETS["V"]` 是空集），唯一的产物是
#: `verifications/<命题号>.jsonl`；只靠"约定只读"的话 `for_role("V")` 会照旧把写工具发给它。
READ_ONLY_ROLES = ("C", "H", "V")

#: 有写副作用的等级 —— 第一根轴词表里"写"的那一半（另一半是下面的 `_NON_WRITE_EFFECTS`）。单列一份是为了
#: 让 `READ_ONLY_ROLES` 的判据在一个地方可读（FC-07：`side_effect` 是一等公民）。
#: `X-91.5-5` 更正：此前写的"与 `base.SIDE_EFFECTS` 的尾部一致"是一句按位置说的话（"尾巴"既没点明是哪一半，
#: 也会在词表末尾追加一个非写等级时当场变成假话，而那种假话不会报错）。准确的说法是一个二分，而且已被机器
#: 钉住：`_check_write_levels_are_registered()` 在 `agentflow.tools` 被导入时断言"词表 = 写等级 ∪ 非写等级、
#: 两栏不相交、两栏都取自词表"。
#: B3 收官之后这里只剩 `write_local`，于是 `external == "exec"` 的剥离判据（`ToolRegistry.for_role`）是只读角
#: 色在"写"之外唯一还要看的那根轴；两处词表不能分批删（`capabilities.assert_capabilities` 第 5 条要求两处逐字
#: 相等，只删一处会导入期就炸）。`R4-AN-4` / `N-5`：光有两处相等还不够 —— 加了写等级却忘了登记进这张表，
#: `for_role` 就不把它算写工具、只读角色 C/H 会静默拿到它（`R4` 用副本注入实测），那正是 `.noai-paths` 第七类
#: 的原文"测试全绿、上线即越权"；判据是下面那条模块级断言。
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
#: `P-14` 之后工具面与可调用面是两个集合：`ToolRegistry.call` 要求调用方声明角色（`role=`，或装配期用
#: `ToolRegistry.scoped_to(role)` 绑定），判据与 `for_role` 共用同一份私有谓词 `_role_surface`。两个面刻意分开
#: 命名：工具面（`ToolRegistry.for_role`）＝ 这个角色声明能拿到什么（只读角色在这里被结构性剥离写工具与
#: `external="exec"`，`role_filter_notes` 留痕）；可调用面（`ToolRegistry.call_surface`）＝ 工具面 + 逐条登记的
#: 落库代理（`base.READONLY_CALL_EXCEPTIONS`，今天只有 `H` 的三个 `review.*`）。第二个集合只允许由那张显式
#: 登记表产生 —— 没有第二条产生路径；`H` 的落库代理是它的第一个用户（`agent_h.AgentH.writers`）。
_MODULES: tuple[str, ...] = (
    "table_tools",
    # 2026-10-24（D-53 业主裁定「把时钟做成系统原生工具」）：五件 `clock.*`
    # （clock.now / clock.timer_start / clock.alarm_start / clock.timer_list /
    # clock.timer_cancel）。它是通用工具 —— 挂给全部角色 + 主控，不写任何知识表，
    # 只落"到点"这一条通信（tasks 的 notice 板项 + out/clock 的唤醒标记）。
    # 工具体在 `tools/clock_tools.py`，时钟与计时器簿记在顶层 `clock.py`。
    "clock_tools",
    "fs_tools",
    "search_tools",
    "ocr_tools",
    "text_tools",
    "graph_tools",
    "trace_tools",
    "research_tools",
    "verify_tools",
    "attack_tools",
    "doc_tools",
    "review_tools",
    "conductor_tools",
    "manuscript_tools",
    # 2026-10-18（业主裁定「只读角色的产出要能进台账」）：C 的产出登记通道
    # （`analysis.register_report`）。组前缀 `analysis` 由模块名机械派生
    # （`_TOOL_GROUP_PREFIXES`），所以这一行也等于给那件工具一个可核的组前缀。
    "analysis_tools",
    # 2026-10-22（业主施工单：新设 L 这个 Lean 形式化者）：L 的两件工具
    # （`formal.formalize` / `formal.check_formal`）。组前缀 `formal` 由模块名
    # 机械派生；工具只挂给 L（`roles=("L",)`），所以 E 的工具面一个字都没变。
    "formal_tools",
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
    1. 键必须是 `组.动作` 形态，且组前缀由 `_MODULES` 里某个模块产出—— 拼错的键会让那条接缝永远不命中（"登记了"与"生效了"是两件事）； 2. 理由串必
    须非空 —— 缺理由的登记与没登记在证据上一样（"写不出理由的，就该改代码而不是加例外"，与 `READONLY_CALL_EXCEPTIONS` 的纪律同族）； 3. 一
    个键下的 property 名必须非空字符串。
    为什么落点在导入期而不是等 `ToolRegistry.register`：`register` 只知道"某个工具注册了"，看不见"接缝表里有没有指着空气的键"（工具模块是
    `build_registry` 惰性 import 的，导入本模块时树上一个 `ToolSpec` 都还没有）。参数「面」的判据在注册期（`base.check_param_seams`），
    接缝「表」的判据在这里。
    两个形参只为让判据能被单独喂表（负控与单元测试用）；真正跑的那一次在下面用默认值调用，读的就是真表。
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


# ---------------------------------------------------------------- 通用能力（第二条轴：可达性）
#
# 业主裁定（逐字，唯一权威）：「通用能力根本不该出现谁能用这个说法」。
#
# 这条裁定把两件此前压在一起的事分开：
#   - 副作用轴（`side_effect`）：它改不改我们拥有的东西。据实声明 —— `clock.timer_start`
#     会写 `tasks` 的 notice 行与 `out/clock` 的状态，所以它是 `write_local`，不许写成 `read`；
#   - 可达性轴（本节这张受控集合）：它是不是通用能力。通用能力对全部角色都可拿
#     （含只读角色 C/H/V 与主控 M），不因为副作用等级被剥掉。
#
# 改前把两根轴压成一根的代价（实测）：为了让只读角色拿得到 `clock.timer_start`，
# 它的声明被写成 `side_effect="read"` —— 而它真的会写表。「谎报换可达性」使
# 「只读角色的工具面里没有写工具」这条判据在声明层面先成了假话，而没有任何东西会红。
# 改法不是「往只读例外表里再加三条」（那是"谁能用"的另一种说法，且通用能力一旦
# 走例外表，下一个通用工具就得再加一条），而是本表：进集合要写下理由。
#
# 硬约束（不许通用集合变成后门）：通用工具写的表只许是 `BOOKKEEPING_TABLES`；
# 碰知识表（`KNOWLEDGE_TABLES`）⇒ 判据直接红，且 `for_role` 对它 fail-closed（不发给只读角色）。
# 三道判据各守一处：
#   ① 导入期 `_check_universal_tools_are_registered()`：登记形态、写集在允许面内、
#      不许与 `READONLY_CALL_EXCEPTIONS` 重复登记（通用能力不是例外）；
#   ② 装配期 `build_registry` 的孤儿判据 `stale_universal_tools()`：登记的名字必须真的在树上；
#   ③ `base.ToolRegistry._role_surface`：只读角色不剥通用工具，但写集越界的通用工具不发给它。
# 登记写集与实现的一致性由 `tests/test_universal_tools_are_for_everyone.py` 用
# `capabilities._tool_write_set_from_source` 读 —— 那是工具层之外的一份实现，
# 本文件不复制它的扫描器（FC-03：同一件事不许两份实现）。

#: 通信/簿记类表：通用工具唯一允许写的表。
#:
#: 板项就是 `tasks` 里 `kind="notice"` 的行（`Conductor.open_item`），所以"tasks / 板项"
#: 是同一张表；事件流（`events/`）、`out/clock` 的状态与唤醒标记、`notes` 都是文件，
#: 不在表里 —— 于是它们不需要在这里出现。
#:
#: 为什么是"允许面"而不是"禁写名单"：禁写名单会漏（新加一张表就默认放行），
#: 而通用工具是"所有角色都能拿"的能力面，它只该有"确实不需要写"这一档。
BOOKKEEPING_TABLES: frozenset[str] = frozenset({"tasks"})

#: 知识表：通用工具一个字都不许写（命中即红）。
#:
#: `claims` 不是一张表（它是 `documents` 行里的一格），所以"写 claims"这条约束由
#: `documents` 代表 —— 写 `documents` 就等于改断言本体。
KNOWLEDGE_TABLES: frozenset[str] = frozenset({
    "statements",
    "literature",
    "relations",
    "documents",
    "conjectures",
    "research_questions",
    "experiments",
    "dependencies",
    "attack_plans",
})


@dataclass(frozen=True)
class UniversalTool:
    """一条通用能力的登记：为什么它是通用能力，以及它最多写哪几张表。

    `tables` 是「它可能写到的表」的一个上界，不是"它每次都会写"的清单：
    方向必须是 `实现算出的写集 ⊆ 本字段 ⊆ BOOKKEEPING_TABLES`。
    为什么是上界而不是相等：有一类通用工具的写发生在到点/异步那一侧
    （`clock.timer_start` 的 `tasks` 行由 `_deliver_due` 落，而它由 `clock.fire_due`
    触发，不在工具入口的调用链上），AST 扫描器跟不到那里。把方向定成上界，
    这一类就能如实登记；下界方向（"实现写了登记之外的表"）仍然逐条判红，
    所以上界不会变成"什么都能写"的缺口。

    写不出理由的登记与没登记在证据上是一回事（与 `PARAM_SEAMS` /
    `READONLY_CALL_EXCEPTIONS` 的纪律同族）：`why` 非空由导入期判据强制。
    """

    why: str
    tables: frozenset[str] = frozenset()


#: 通用能力的受控集合：工具名 -> 登记。首批是 D-53 的时钟五件、父子追踪一件、
#: 上行通道一件。为什么把它们放在一起：它们的可达性判据是同一条
#: （"它写不写知识表"），而不是"谁被允许用它"。
UNIVERSAL_TOOLS: dict[str, UniversalTool] = {
    "clock.now": UniversalTool(
        "读系统时钟与等我的唤醒标记（纯读）。业主 D-53：「其它人要看表也可以用」",
        frozenset(),
    ),
    "clock.timer_start": UniversalTool(
        "起一次性计时器：写 `out/clock` 的状态与到期后的唤醒标记，到点落一条 "
        "`tasks` notice 行（板项）。业主 D-53：「所有角色都能用」",
        frozenset({"tasks"}),
    ),
    "clock.alarm_start": UniversalTool(
        "定一次性闹钟：与 `clock.timer_start` 同一套落点（`out/clock` 的状态 + "
        "到点的 `tasks` notice 行），差别只在时间怎么给",
        frozenset({"tasks"}),
    ),
    "clock.timer_list": UniversalTool(
        "列计时器与唤醒标记读数（纯读）；与 `clock.now` 同一口径",
        frozenset(),
    ),
    "clock.timer_cancel": UniversalTool(
        "取消一条待发的计时器：只改 `out/clock` 的状态，不写任何表"
        "（取消之后就不该再有 notice 行）",
        frozenset(),
    ),
    # 2026-10-25 业主裁定（「M 的巡视叫等待20分钟+周期性巡查」＋「忘填目的不报错，
    # 只是让它追加目的」＋「挂机是将进程挂在时钟上」）：时钟从五件长到八件。
    # 这三件的可达性判据与那五件逐字同一条（"它写不写知识表"），所以一起登记在
    # 通用集合里 —— 不登记的话只读角色 C/H/V 的工具面上会少这三件，而"通用能力
    # 不该出现谁能用这个说法"那条裁定就被这三件悄悄破了。写集仍只落在
    # `BOOKKEEPING_TABLES`（今天只有 `tasks`）之内，导入期判据照旧核这一点。
    "clock.periodic_start": UniversalTool(
        "起周期性巡查（M 的巡视就是这一类：`every_sec=1200` + `purpose=周期性巡查`）："
        "写 `out/clock` 的状态，每一拍到点落一条 `tasks` notice 行（簿记板项）",
        frozenset({"tasks"}),
    ),
    "clock.periodic_stop": UniversalTool(
        "停一条周期性巡查：只改 `out/clock` 的状态（停之后就不该再有这条巡查的 notice 行）",
        frozenset(),
    ),
    "clock.timer_purpose": UniversalTool(
        "给一条已受理的等待补上目的（同一个编号，不是新建一条）：只改 `out/clock` 的状态",
        frozenset(),
    ),
    # 2026-10-27 业主第三条裁定（「直到它认为无事可做时，可启动计时器等待任意计时器返回」）：
    # 时钟从八件长到九件。这一件的可达性判据与前八件逐字同一条（"它写不写知识表"）：
    # 它只写 `out/clock/wait_any.json`（一份意图账，是文件不是表）⇒ 登记写集是空集。
    # 为什么必须进这一张表：它是"通用能力"，不是"谁能用"—— 只读角色 C/H/V 也会有无事可做
    # 的时候，把它们排除在外等于让那三个角色只能空转或提前收工。
    "clock.wait_any": UniversalTool(
        "手上没事了：记一条「等待任意计时器返回」的意图（同一个台账号只留最新一条），"
        "并把这一格的读数交回去。只写 `out/clock/wait_any.json` 这份意图账，不写任何表；"
        "挂机与否的判定在 `agent_loop._park_gate`，工具本身不做控制流。"
        "业主 2026-10-27 原话：「可启动计时器等待任意计时器返回」",
        frozenset(),
    ),
    "trace.children": UniversalTool(
        "读任务树里我这一层的直接下级：只读 `tasks` 的可见行，不写任何东西。"
        "父子追踪对所有角色开放 —— 否则只读角色连自己在等谁都不知道",
        frozenset(),
    ),
    "conductor.escalate": UniversalTool(
        "上行通道：孩子把需求写进召唤者的收件箱（一条 `agent_message` 事件，不写任何表）。"
        "业主 2026-10-19 裁定「父子天然双向」，含只读角色",
        frozenset(),
    ),
    "conductor.ack": UniversalTool(
        "消项：收件人把自己名下已经读过/办完的板项推到 done，只改 `tasks` 的 "
        "`item_state` / `item_close` 两格并追加一条事件（簿记，不写知识表）。"
        "业主 D-68 逐字「就做手，不兜底」：凡是会收到板项的角色都得拿得到这只手 —— "
        "板项按 `parent_task_id` 投给任何一行，只读角色 C/H/V 同样收交接通报、"
        "指导与停止通知，所以它不是某个角色的活，是通用能力",
        frozenset({"tasks"}),
    ),
}


def is_universal_tool(
    name: str, *, universal: Mapping[str, "UniversalTool"] | None = None
) -> bool:
    """这个名字是不是登记在案的通用能力（`universal=None` ⇒ 读本文件的受控集合）。

    形参只为让判据能被单独喂表（负控与单元测试用）；真正跑的那一次读的就是真表。
    """
    table = UNIVERSAL_TOOLS if universal is None else universal
    return str(name) in table


def universal_tool_tables(
    name: str, *, universal: Mapping[str, "UniversalTool"] | None = None
) -> frozenset[str] | None:
    """这件通用工具登记自己能写的表（没登记 ⇒ `None`，不是空集）。

    三态：`None` = 它不是通用工具（"没登记"）；空集 = 登记了、且不写任何表。
    把两者折叠成空集，会让"没登记"被读成"查过了、不写"。
    """
    table = UNIVERSAL_TOOLS if universal is None else universal
    entry = table.get(str(name))
    return None if entry is None else frozenset(entry.tables)


def universal_tool_is_bookkeeping_only(
    name: str,
    *,
    universal: Mapping[str, "UniversalTool"] | None = None,
    bookkeeping: Iterable[str] | frozenset[str] | None = None,
) -> bool:
    """这件通用工具的登记写集是否只落在通信/簿记类表上（硬约束的判据本体）。

    没登记的名字返回假（不是通用工具就谈不上"通用工具的写集"）；`base._role_surface`
    只在 `is_universal_tool()` 为真时才问这一句，所以这里的"没登记 ⇒ 假"不会把
    普通工具误判成越界。
    """
    tables = universal_tool_tables(name, universal=universal)
    if tables is None:
        return False
    allow = set(BOOKKEEPING_TABLES if bookkeeping is None else bookkeeping)
    return not (set(tables) - allow)


def universal_tool_violations(
    write_sets: Mapping[str, frozenset[str] | None],
    *,
    universal: Mapping[str, "UniversalTool"] | None = None,
    bookkeeping: Iterable[str] | None = None,
    knowledge: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    """逐个通用工具核「它的写集只落在通信/簿记类表上」，返回 `{工具名: [违规理由]}`。

    `write_sets` 是「工具名 -> 从实现算出来的写集」；`None` 表示算不出来。
    它是必填形参，没有默认值 —— 少给一张写集表这件事必须当场报错，
    而不是让判据在空表上返回"零违反"（那是真空通过：`P16` 的形态）。
    缺键与 `None` 都记违规：前者是"没查"，后者是"没查成"，两者都不是"没有写"。

    两条判据的方向刻意不同：
      - 登记写集必须是允许面的子集（登记本身不许越界）；
      - 实现写集必须是登记写集的子集（实现不许写登记之外的表）。
    合起来是 `实现 ⊆ 登记 ⊆ 通信/簿记表`。反方向（登记多于实现）是上界语义，
    见 `UniversalTool.tables` 的注释。
    """
    table = UNIVERSAL_TOOLS if universal is None else universal
    allow = set(BOOKKEEPING_TABLES if bookkeeping is None else bookkeeping)
    know = set(KNOWLEDGE_TABLES if knowledge is None else knowledge)
    out: dict[str, list[str]] = {}
    for name in sorted(table):
        reasons: list[str] = []
        declared = set(table[name].tables)
        bad_declared = sorted(declared - allow)
        if bad_declared:
            reasons.append(
                f"登记的写集 {sorted(declared)} 里 {bad_declared} 不在通信/簿记表 "
                f"{sorted(allow)} 里"
            )
        declared_knowledge = sorted(declared & know)
        if declared_knowledge:
            reasons.append(f"登记的写集碰了知识表 {declared_knowledge}（通用工具一个字都不许写）")
        if name not in write_sets:
            reasons.append("没有给出它的写集（没查不等于没有写）")
        else:
            actual = write_sets[name]
            if actual is None:
                reasons.append(
                    "它的写集算不出来（没查成）：要么让实现函数与工具名对得上，"
                    "要么把它从通用集合里撤掉"
                )
            else:
                undeclared = sorted(set(actual) - declared)
                if undeclared:
                    reasons.append(
                        f"实现写了登记之外的表 {undeclared}（登记的是 {sorted(declared)}）"
                    )
                hits = sorted(set(actual) & know)
                if hits:
                    reasons.append(f"实现写了知识表 {hits}")
                outside = sorted(set(actual) - allow)
                if outside:
                    reasons.append(f"实现写了通信/簿记表以外的表 {outside}")
        if reasons:
            out[name] = reasons
    return out


def stale_universal_tools(
    specs: Mapping[str, Any], *, universal: Mapping[str, Any] | None = None
) -> list[str]:
    """`UNIVERSAL_TOOLS` 里已经不在树上的名字（拼错 / 工具改名后留下的孤儿）。

    与 `stale_tool_param_seams` 同一条纪律：登记表不许烂成噪音，而"登记了"与
    "生效了"是两件事 —— 一个拼错的名字会让那条通用能力静默地不存在。
    """
    table = UNIVERSAL_TOOLS if universal is None else universal
    return sorted(set(table) - set(specs))


def _check_universal_tools_are_registered(
    universal: Mapping[str, UniversalTool] | None = None,
    bookkeeping: Iterable[str] | None = None,
    knowledge: Iterable[str] | None = None,
    groups: tuple[str, ...] = _TOOL_GROUP_PREFIXES,
    exceptions: Mapping[str, Any] | None = None,
) -> None:
    """导入期交叉断言：通用能力的受控集合形态与允许面（本条判据的五条）。

    1. 键必须是 `组.动作` 形态，且组前缀由 `_MODULES` 里某个模块产出 —— 拼错的名字
       不会命中任何工具，那条通用能力静默地不存在；
    2. 理由串必须非空 —— 写不出理由就该改代码而不是登记；
    3. 登记写集必须是 `BOOKKEEPING_TABLES` 的子集；
    4. 登记写集不许碰 `KNOWLEDGE_TABLES`；
    5. 通用工具不许同时出现在 `READONLY_CALL_EXCEPTIONS` 里 —— 通用能力不是例外，
       两者混记会让"它为什么能拿"有两个互相独立的来源（改一处、另一处不动）。
       业主口径是"通用能力不该有谁能用这回事"，例外表回答的正是"谁能用"。

    外加一条反真空：集合为空时本判据会静默通过，而那时所有通用能力都退回
    "按副作用等级剥掉"的旧世界 —— 所以空集合本身就是红。
    形参只为让判据能被单独喂表（负控与单元测试用）；真正跑的那一次在下面用默认值调用。
    """
    table = UNIVERSAL_TOOLS if universal is None else universal
    allow = set(BOOKKEEPING_TABLES if bookkeeping is None else bookkeeping)
    know = set(KNOWLEDGE_TABLES if knowledge is None else knowledge)
    exempt = READONLY_CALL_EXCEPTIONS if exceptions is None else exceptions

    assert table, (
        "UNIVERSAL_TOOLS 是空的 —— 通用能力集合清空之后，所有通用工具都会退回"
        "『按副作用等级被只读角色剥掉』的旧口径，而本判据会静默通过"
    )
    bad_shape = sorted(k for k in table if not isinstance(k, str) or "." not in k)
    assert not bad_shape, (
        f"UNIVERSAL_TOOLS 的键 {bad_shape} 不是 `组.动作` 形态 —— 工具名只有这一种形态，"
        "拼错的键不会命中任何工具，于是那条通用能力静默失效"
    )
    unknown_group = sorted({k.split(".")[0] for k in table} - set(groups))
    assert not unknown_group, (
        f"UNIVERSAL_TOOLS 里的组前缀 {unknown_group} 不由任何工具模块产出"
        f"（_MODULES 派生出的是 {sorted(groups)}）⇒ 这些登记永远不会命中任何工具"
    )
    for name, entry in sorted(table.items()):
        assert str(entry.why or "").strip(), (
            f"UNIVERSAL_TOOLS[{name!r}] 没有理由串 —— 登记而不写理由，"
            "与没登记在证据上是一回事（写不出理由就该改代码）"
        )
        stray = sorted(set(entry.tables) - allow)
        assert not stray, (
            f"UNIVERSAL_TOOLS[{name!r}] 登记自己会写 {stray}，而通用工具只许写通信/簿记表 "
            f"{sorted(allow)} —— 写别的表说明它是某个角色的活，不是通用能力"
        )
        hits = sorted(set(entry.tables) & know)
        assert not hits, (
            f"UNIVERSAL_TOOLS[{name!r}] 登记自己会写知识表 {hits} ⇒ 它会把"
            "『只读角色拿得到』变成『只读角色能改知识表』的后门"
        )
    overlaps = sorted(
        {name for name, _why in (n for ns in exempt.values() for n in ns)} & set(table)
    )
    assert not overlaps, (
        f"这些工具既是通用能力、又在只读例外表 READONLY_CALL_EXCEPTIONS 里：{overlaps} ⇒ "
        "『它为什么对只读角色可用』有了两个互相独立的来源。业主口径：通用能力不进例外表 —— "
        "请把例外表里的那条删掉（通用能力由 UNIVERSAL_TOOLS 一条判据负责）"
    )


_check_universal_tools_are_registered()


@dataclass
class RegistryBuild:
    """装配结果。`skipped` 让"某个模块没装上"变成可见的事实，而不是静默少几个工具。"""

    registry: ToolRegistry
    loaded: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    #: 这一趟「按下开关」没有装配的 Lean 专属模块（`leanscope.LEAN_ONLY_TOOL_MODULES`）。
    #:
    #: 为什么单列一格、而不是塞进 `skipped`：`skipped` 的语义是"该装上却没装上"
    #: （装配缺陷，`ok` 为假、`strict=True` 时直接抛），而这里是"按用户设的开关
    #: 本来就不该装"—— 折进 `skipped` 会让"关掉 Lean"变成"装配出错"，
    #: 而且 `strict=True` 的验收会因此炸，逼人把一个正确的行为当成故障去关掉。
    lean_off: list[str] = field(default_factory=list)
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
            # 按开关不装的模块（不是缺陷：见 `lean_off` 字段的注释）。
            "lean_off_modules": list(self.lean_off),
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
        # 2026-10-17（业主裁定「方案 1」）：H 的写入口长在它自己身上。
        # review_tools 的写件自带 roles=("H",)，装进主表只对 H 可见；
        # 不装则 H 永远够不到自己的落库口（真机 t5e：M 派 8 次、H 跑 4 趟，review_findings 恒 0）。
        if (str(getattr(mod, "__name__", "")).endswith("review_tools")
                and "include_writers" not in kwargs):
            kwargs["include_writers"] = True
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
    
    参数----store : Store | None 数据表工具必需；为 None 时相关模块会被跳过（并记录原因）。
    workspace_root : Path | None 文件工具的工作区根（沙箱边界）。为 None 时用 `<store.root>`。
    graph : RelationGraph | None C 的图对象；为 None 时 `graph_tools` 的只读查询类工具仍可注册（它们可自行构建）。
    strict : bool 为 True 时，任何模块跳过都抛异常 —— 供验收脚本使用，防止"少了一半工具还以为装好了"。 session_root, sid : 会话身
    份（`draft/37` §63，修法 B）这一趟运行「是谁」：会话记录的根与这一趟的会话号。装配期注入，工具层不替它猜。为什么必须是装配期输入：真机实测第 11 趟（`sessions/real11.jsonl`）
    主控在运行内调 `conductor.closing` 得到 `can_close: true`，而同一次运行外部带 `sid=real11`的读数报 
    `failed: ['user_pending']` —— 工具体当时按 `sid=None` 读到了缺省会话`sessions/<今天>.jsonl`，于是"问了还没答"
    被读成"没问过"。「假绿」，且它只在运行内出现，外面怎么看都是对的。`sid` 不给 ⇒ 传下去的是 `closing.NO_SESSION` ⇒ 那一格记 
    `unknown`（不是 pass，也不回落成"读今天那份"：三态纪律）。
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
    # 必须放在 `root` 算出来之后 —— 先写的版本把它放在 `root = ...` 之前，
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
    lean_off: list[str] = []
    for mod_name in _MODULES:
        # 业主 2026-10-22（「在Lean开关没开时隔绝L」）：Lean 专属模块在开关关着时
        # 一件都不装配 —— 谁的工具面里都没有 `formal.*`，连 L 自己的也没有。
        # 判定读 `leanscope`（唯一入口），这里只做"跳过并如实记一笔"。
        if mod_name in _LEANSCOPE.LEAN_ONLY_TOOL_MODULES and not _LEANSCOPE.lean_on():
            lean_off.append(mod_name)
            continue
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

    # 断言所有工具声明的角色都在 ROLES 里。
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

    # 遗留取值 `network` 的装配期翻译检查已随 B3 收官删除。
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

    # ---- 通用能力集合的孤儿判据（与参数接缝那条同一处置口径）
    #
    # `_check_universal_tools_are_registered()` 只能核"这张表自己的形态"（导入期树上一个
    # 工具都没有）；"登记的名字到底有没有人产出"只能在这里核。拼错的名字不会报错，
    # 它只会让那条通用工具按普通工具的判据被只读角色剥掉 —— 静默的能力缺失。
    stale_universal = stale_universal_tools(reg._specs)
    if stale_universal:
        msg = (
            f"UNIVERSAL_TOOLS 里这些名字在装配出来的树上不存在：{stale_universal}。"
            "要么工具名改了而登记没跟着改，要么那条登记本来就写错了 —— "
            "两种都会让『通用能力对所有人可用』静默失效（登记表不许烂成噪音）"
        )
        # 只记进 `skipped`，不在这里单独抛：`strict=True` 的唯一出口是下面那道
        # 「严格模式下不允许模块被跳过」—— 两个退出点会让"严格档到底为什么失败"
        # 取决于哪一条先跑到，而那种先后关系没有人维护。
        skipped.append({"module": "<universal-tools>", "stage": "validate", "error": msg})

    if strict and skipped:
        raise ToolError(f"严格模式下不允许模块被跳过：{skipped}")
    return RegistryBuild(registry=reg, loaded=loaded, skipped=skipped, params_checked=params_checked,
                         lean_off=lean_off)


def build_for_role(role: str, **kwargs: Any) -> RegistryBuild:
    """只装某个角色的工具子集。"""
    build = build_registry(**kwargs)
    filtered = ToolRegistry(name=f"{kwargs.get('name', 'agentflow')}:{role}")
    for spec in build.registry.for_role(role):
        filtered.register(spec)
    return RegistryBuild(registry=filtered, loaded=build.loaded, skipped=build.skipped,
                         params_checked=build.params_checked, lean_off=build.lean_off)


__all__ = [
    "ROLES",
    "READ_ONLY_ROLES",
    "READONLY_CALL_EXCEPTIONS",
    "PARAM_SEAMS",
    "SIDE_EFFECTS_WRITE",
    "BOOKKEEPING_TABLES",
    "KNOWLEDGE_TABLES",
    "UNIVERSAL_TOOLS",
    "UniversalTool",
    "is_universal_tool",
    "stale_universal_tools",
    "universal_tool_is_bookkeeping_only",
    "universal_tool_tables",
    "universal_tool_violations",
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
