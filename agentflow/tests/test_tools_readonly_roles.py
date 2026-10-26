"""只读角色的权限面必须由结构保证，不能只靠工具声明。

## 缺陷（子智能体实测发现）

`table.*` / `fs.*` 在注册时把注入的全部 `ROLES` 写进了每个工具的 `roles`，于是按角色装配出来的审校者 H 的工具面里出现了
`table.update`、`fs.write`、`verify.run_experiment` —— 也就是说 H 手里有能改数据/稿件的刀。

而"H 只读"不是洁癖：若审校者能直接改，它就同时是"发现者"与"修正者"，于是"发现问题"与"掩盖问题"在结构上无法区分。C 同理：一旦 C 能写，它就成了"绕过 B 引文回验"的写入路径，而 B
的引文逐字回验是全系统唯一能自动发现幻觉引文的地方。

## 修法（两道防线，缺一不可）

1. 声明正确：写工具的角色集合里不含只读角色（`table_tools` / `fs_tools` /
`verify_tools` 各自过一遍）。
2. `ToolRegistry.for_role` 结构性拦截：对只读角色，无论 spec 怎么声明，
一律过滤掉有写副作用的工具，并把被剥掉的名字记进 `role_filter_notes`（静默过滤会让"声明错误"永远暴露不了）。

本文件守的是第 2 道 —— 因为它才是"工具作者无法绕过"的那一道。
"""

from __future__ import annotations

from typing import Iterable, Mapping

import pytest

from agentflow.tools import (BOOKKEEPING_TABLES, READ_ONLY_ROLES, ROLES,
                             SIDE_EFFECTS_WRITE, UNIVERSAL_TOOLS, UniversalTool,
                             build_registry, is_universal_tool,
                             universal_tool_is_bookkeeping_only, universal_tool_tables)
from agentflow.tools.base import SIDE_EFFECTS, ToolRegistry, ToolSpec, ok


def _spec(name: str, side_effect: str, roles: tuple[str, ...], *, external: str = "none") -> ToolSpec:
    return ToolSpec(
        name=name,
        summary="测试用",
        params={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda: ok({}),
        side_effect=side_effect,
        roles=roles,
        returns="（测试样本不返回）",
        declared_external=external,
    )


def test_read_only_roles_are_exactly_c_h_v():
    """只读角色的单一来源。改动这里必须同时改设计文档与 C/H/V 的实现。

    V（验证者，F-02 起）在这里的理由：它不写任何表（`capabilities.WRITE_SETS["V"]`
    是空集），唯一的产物是 `verifications/<命题号>.jsonl` 这个文件。
    """
    assert READ_ONLY_ROLES == ("C", "H", "V")
    assert set(READ_ONLY_ROLES) <= set(ROLES)


def test_for_role_strips_write_tools_from_read_only_roles():
    """核心负控：即使 spec 声明 `roles=("C",)` 而 `side_effect="write_local"`，
    `for_role("C")` 也不得返回它。

    这一条正是"工具作者无法绕过"的证明：声明写错也不会真的把刀交出去。
    """
    reg = ToolRegistry(name="t")
    reg.register(_spec("bad.write", "write_local", ("C", "H")))
    reg.register(_spec("fine.read", "read", ("C", "H")))
    reg.register(_spec("fine.none", "none", ("C", "H")))

    got = sorted(s.name for s in reg.for_role("C"))
    assert got == ["fine.none", "fine.read"], f"C 的工具面里不该有写工具：{got}"
    got_h = sorted(s.name for s in reg.for_role("H"))
    assert got_h == ["fine.none", "fine.read"], f"H 的工具面里不该有写工具：{got_h}"

    # 留痕：被剥掉的名字必须可见（静默过滤 = 声明错误永远发现不了）
    assert "C" in reg.role_filter_notes and "H" in reg.role_filter_notes
    assert "bad.write" in reg.role_filter_notes["C"][0]


def test_for_role_keeps_write_tools_for_writing_roles():
    """防误伤：写角色（A/B/D/E/F/G）必须照常拿到写工具。"""
    reg = ToolRegistry(name="t")
    reg.register(_spec("good.write", "write_local", ("A", "B", "D", "E", "F", "G")))
    for role in ("A", "B", "D", "E", "F", "G"):
        names = [s.name for s in reg.for_role(role)]
        assert names == ["good.write"], (role, names)


def test_no_role_filter_notes_when_declarations_are_correct():
    """防误伤：声明都正确时，`role_filter_notes` 必须是空的。

    否则那条"留痕"机制会因为到处都是噪音而被忽略。
    """
    reg = ToolRegistry(name="t")
    reg.register(_spec("good.read", "read", ROLES))
    reg.register(_spec("good.write", "write_local", ("A", "B", "D")))
    for role in ROLES:
        reg.for_role(role)
    # 2026-10-17（业主裁定「方案 1」）：H 的落库代理是登记过的放行 ⇒ 那一条留痕不是声明错误

    # ---- 差分（`G-22`）：同一个夹具，只把"写工具声明的 roles"换成含只读角色，
    # 留痕必须非空。为什么必须成对写：上面那条 `== {}` 单看是不可能失败的断言
    # —— 就算 `for_role` 完全停止剥离，它也照样绿。把正反两侧放进同一个用例，
    # 任何一侧被抹平都会红。
    leaky = ToolRegistry(name="t-leaky")
    leaky.register(_spec("good.read", "read", ROLES))
    leaky.register(_spec("leaky.write", "write_local", ("A", "H")))
    leaky.for_role("H")
    assert leaky.role_filter_notes != {}, (
        "写工具被放行给只读角色却没留痕 ⇒ 留痕机制本身失效（这正是上一条断言看不见的那种坏法）"
    )
    assert "leaky.write" in leaky.role_filter_notes["H"][0], leaky.role_filter_notes


def test_real_registry_gives_no_write_tool_to_read_only_roles(store):
    """端到端：真实装配出来的工具层里，C 与 H 的工具面里没有未登记的写工具。

    "未登记"有两档，且都要显式登记过（不是"看着像就行"）：
    1. `READONLY_CALL_EXCEPTIONS`：只读角色自己的落库代理（2026-10-17 业主裁定「方案 1」）；
    2. `UNIVERSAL_TOOLS`：通用能力（2026-10-24 业主裁定「通用能力根本不该出现谁能用这个说法」）——
       `clock.timer_start` 据实是 `write_local`，而它对所有角色都可用，所以它必须能出现在
       C/H/V 的工具面上。这不是"闸开了"：通用能力的硬约束写在工具层
       （只许写通信/簿记类表），判据见 `tests/test_universal_tools_are_for_everyone.py`。
    """
    build = build_registry(store=store, workspace_root=store.root)
    assert build.skipped == [], build.skipped
    from agentflow.tools import UNIVERSAL_TOOLS

    _uni = set(UNIVERSAL_TOOLS)
    for role in READ_ONLY_ROLES:
        specs = build.registry.for_role(role)
        leaks = [s.name for s in specs if s.side_effect in SIDE_EFFECTS_WRITE]
        # 2026-10-17（业主裁定「方案 1」）：只读角色自己的落库代理是允许的
        from agentflow.tools.base import READONLY_CALL_EXCEPTIONS as _EXC
        _ex = {n for n, _w in _EXC.get(role, ())}
        universal_write = [n for n in leaks if n not in _ex and n in _uni]
        leaks = [n for n in leaks if n not in _ex and n not in _uni]
        assert leaks == [], f"{role} 的工具面里有**未登记**的写工具：{leaks}"
        # 正向：被剔掉的那几件确实是登记在案的通用能力，而且真的在面上 ——
        # 没有这一半，上面那条断言就算被一张空名单掏空也照样绿。
        assert universal_write, (
            f"{role} 的面上一件通用写工具都没有 ⇒ 要么通用集合空了，要么这条排除规则"
            "把判据掏空了（通用能力里今天有 `clock.timer_start` 这类 write_local）"
        )
        assert set(universal_write) <= {n for n in _uni if n in {s.name for s in specs}}, (
            f"{role} 的工具面与通用集合对不上：{universal_write}"
        )
        assert specs, f"{role} 一个工具都没有 —— 那不是只读，那是没接线"
    # 声明侧也应当已经干净（`for_role` 的留痕为空），否则说明有人又写错了 roles
    # 2026-10-17（业主裁定「方案 1」）：H 的落库代理是登记过的放行，不是"声明错误"。
    # 2026-10-24：通用能力也是登记过的放行（它们不进例外表，理由见 `UNIVERSAL_TOOLS`）。
    _markers = ("方案 1」放行了", "方案 1」放行", "按通用能力放行了")
    _notes = {k: [m for m in v if not any(mark in m for mark in _markers)]
              for k, v in build.registry.role_filter_notes.items()}
    _notes = {k: v for k, v in _notes.items() if v}
    assert _notes == {}, (
        "有工具的 roles 声明把写工具给了只读角色（行为已被拦下，但声明要改）："
        f"{_notes}"
    )


def test_every_write_tool_declares_at_least_one_writing_role(store):
    """负控：任何写工具都必须至少有一个写角色 —— 否则它谁都拿不到（等于死工具）。"""
    build = build_registry(store=store, workspace_root=store.root)
    orphan = [
        s.name for s in build.registry._specs.values()
        if s.side_effect in SIDE_EFFECTS_WRITE and not (set(s.roles) - set(READ_ONLY_ROLES))
    ]
    # 2026-10-17（业主裁定「方案 1」）：例外表里登记的落库代理不算漏
    from agentflow.tools.base import READONLY_CALL_EXCEPTIONS as _EXC
    _ex = {n for _ns in _EXC.values() for n, _w in _ns}
    orphan = [n for n in orphan if n not in _ex]
    assert orphan == [], f"这些写工具没有任何写角色能拿到：{orphan}"


def test_side_effect_vocabulary_is_the_single_source():
    """`SIDE_EFFECTS_WRITE` 必须是 `SIDE_EFFECTS` 的尾部子集（不是另写一份词表）。

    B3 收官之后它只剩 `write_local`：遗留取值 `network` 已从两处词表里删掉，
    于是"哪些算写"这个问题在只读角色的剥离判据上只有一个答案。
    """
    assert set(SIDE_EFFECTS_WRITE) <= set(SIDE_EFFECTS)
    assert set(SIDE_EFFECTS_WRITE) == {"write_local"}
    # 负控：`network` 已经不是合法取值 ⇒ 想用旧的"写副作用"集合绕过剥离是不可能的，
    # 那个取值在构造 `ToolSpec` 时就会被拒（见 test_tools_base.py 的负控）。
    assert "network" not in SIDE_EFFECTS


# ============================================================ 第二道：external == "exec"

def test_for_role_strips_exec_tools_from_read_only_roles():
    """只读角色再剥一类：`external == "exec"`（P-13 §3.3 的剥离规则）。

    理由与剥离写工具同族：只读角色的语义是"它在结构上不能改世界"，
    而执行一个由调用方决定内容的程序改变了世界（它能写工作区、能出网、
    能起更多进程）。所以即使 `side_effect="none"`（不写我们的表），
    只读角色也拿不到它。
    """
    reg = ToolRegistry(name="t")
    reg.register(_spec("bad.exec", "none", ("C", "H"), external="exec"))
    reg.register(_spec("fine.read", "read", ("C", "H")))

    got = sorted(s.name for s in reg.for_role("C"))
    assert got == ["fine.read"], f"C 的工具面里不该有 exec 工具：{got}"
    got_h = sorted(s.name for s in reg.for_role("H"))
    assert got_h == ["fine.read"], f"H 的工具面里不该有 exec 工具：{got_h}"
    assert "C" in reg.role_filter_notes and "bad.exec" in reg.role_filter_notes["C"][0]


def test_for_role_releases_exec_when_sandbox_is_declared_available(monkeypatch):
    """唯一的放行条件：沙箱被声明为可用（且放行也要留痕）。

    放行的判据是"沙箱承接了这次执行"，不是"这个工具变安全了" ——
    所以留痕必须说清是哪一条理由放行的，否则"为什么 H 拿到了一个 exec 工具"
    在报告里不可见。
    """
    from agentflow.tools import base as B

    reg = ToolRegistry(name="t")
    reg.register(_spec("tool.exec", "none", ("C",), external="exec"))

    monkeypatch.setattr(B, "SANDBOX_AVAILABLE", True)
    assert [s.name for s in reg.for_role("C")] == ["tool.exec"]
    notes = reg.role_filter_notes.get("C", [])
    assert any("沙箱已声明可用" in n and "tool.exec" in n for n in notes), notes


#: 真实树上"外部动作 = `exec`"的工具清单。为什么钉成常量而不是只断言"只读角色拿不到 exec 工具"：后者在
#: "任何" exec 工具存在时都成立，于是每多一个 exec 工具都不会被任何人注意到 —— 而 `for_role` 的剥离规则意味着
#: "多一个 exec 工具"就等于"C/H 的工具面少一个"（P-13 §8.2 的受影响清单）；钉住清单 ⇒ 每次迁移都必须显式改这一行。
#: 现状 5 条：`verify.run_experiment`（B3 第 0 步）、L 的 `formal.formalize` / `formal.check_formal` /
#: `formal.record`（2026-10-23 形式化搬到 L；`verify.check_formal` 这一件已删）、`doc.paper_compile`
#: （框架自己起 LaTeX 引擎那一档）。前者同时是写工具 ⇒ 就算 exec 轴不存在 C/H 也拿不到它；L 那三件
#: 是 `read` + `exec` ⇒ 只有 exec 轴能把它剥掉（`roles` 也已从 `_ROLES` 改成 `_ROLES_WRITE`，不靠过滤兜底），
#: 所以它是"第二根轴的剥离规则真的在干活"的证据。2026-10-13（业主裁定「paper_package 里那些都是古早废案了，
#: 我们要智能体写文章」，退场面见 `draft/117`）：旧路那四条 exec 工具（渲染 / 重编 / 查锚 / 读锚）整条退场， 编译那一格由 `doc.paper_compile` 一件接手 ⇒ 这份清单从 6 条收回到 3 条。
KNOWN_EXEC_TOOLS = frozenset({"verify.run_experiment",
    "formal.formalize",
    "formal.check_formal",
    "formal.record", 
                              "doc.paper_compile"})


def _exec_inventory_delta(registry, expected: frozenset[str]) -> dict[str, list[str]]:
    """`registry` 里 `external == "exec"` 的工具名集合与 `expected` 的双向差集。"""
    got = {s.name for s in registry._specs.values() if s.external == "exec"}
    return {"unexpected": sorted(got - expected), "missing": sorted(expected - got)}


def test_real_registry_exec_inventory_is_pinned_and_read_only_roles_stay_clean(store):
    """真实树上的现状：exec 清单是 3 条，且只读角色仍 0 条。

    这条断言原来写的是"一个 exec 工具都没有"，它的职责从来不是"现状如此"，
    而是"exec 清单变化必须被人看见"。B3 落地后按设计变红，于是它改为"钉住清单"：
    形状不变（谁动了清单谁就得改这一行），强度更高（多了/少了都报）。
    """
    build = build_registry(store=store, workspace_root=store.root)
    assert build.skipped == [], build.skipped

    delta = _exec_inventory_delta(build.registry, KNOWN_EXEC_TOOLS)
    assert delta == {"unexpected": [], "missing": []}, (
        f"真实树的 exec 清单与 `KNOWN_EXEC_TOOLS` 不一致：{delta}。"
        "多了 ⇒ 有工具被标成 exec（C/H 的工具面会因此少一个，见 P-13 §8.2）；"
        "少了 ⇒ 迁移被回退。两种都要连带更新本常量与 `P-13` 的受影响清单。"
    )

    # ---- 差分（`G-22`）：把同一个判据函数用在两个夹具上，两个方向都必须报出差异。
    # 没有这一半，上面那条 `== {"unexpected": [], "missing": []}` 就是不可能失败
    # 的断言：哪怕 `_exec_inventory_delta` 里那个 `== "exec"` 被写成恒假，
    # 它也照样绿 —— 而恒假恰好就是"这条清单没人再看"的那种坏法。
    extra = ToolRegistry(name="t-extra-exec")
    for _name, _se, _roles in (("verify.run_experiment", "write_local", ("E", "F", "G")),
                               ("formal.formalize", "write_local", ("L",)),
                                   ("formal.check_formal", "read", ("L",)),
                                   ("formal.record", "write_local", ("L",)),
                               ("doc.paper_compile", "write_local", ("G",))):
        extra.register(_spec(_name, _se, _roles, external="exec"))
    extra.register(_spec("bogus.exec", "none", ("E",), external="exec"))
    assert _exec_inventory_delta(extra, KNOWN_EXEC_TOOLS) == {
        "unexpected": ["bogus.exec"], "missing": [],
    }, _exec_inventory_delta(extra, KNOWN_EXEC_TOOLS)

    absent = ToolRegistry(name="t-absent-exec")
    absent.register(_spec("formal.check_formal", "read", ("L",), external="exec"))
    assert _exec_inventory_delta(absent, KNOWN_EXEC_TOOLS) == {
        "unexpected": [],
        "missing": ["doc.paper_compile", "formal.formalize", "formal.record",
                       "verify.run_experiment"],
    }, _exec_inventory_delta(absent, KNOWN_EXEC_TOOLS)
    none_at_all = ToolRegistry(name="t-no-exec")
    assert _exec_inventory_delta(none_at_all, KNOWN_EXEC_TOOLS) == {
        "unexpected": [],
        "missing": ["doc.paper_compile", "formal.check_formal", "formal.formalize",
                    "formal.record", "verify.run_experiment"],
    }, _exec_inventory_delta(none_at_all, KNOWN_EXEC_TOOLS)

    # 只读角色侧：真实树上 exec 工具一条都进不去，且留痕为空（= 声明侧也干净）。
    for role in READ_ONLY_ROLES:
        specs = build.registry.for_role(role)
        assert [s.name for s in specs if s.external == "exec"] == [], (
            f"{role} 的工具面里出现了 exec 工具："
            f"{[s.name for s in specs if s.external == 'exec']}"
        )
    # 2026-10-17（业主裁定「方案 1」）：H 的落库代理是登记过的放行 ⇒ 那一条留痕不是声明错误
    _notes = {k: [m for m in v if '放行了' not in m] for k, v in build.registry.role_filter_notes.items()}
    _notes = {k: v for k, v in _notes.items() if v}
    assert _notes == {}, f"未登记的写工具声明：{_notes}"
    # 原断言（`role_filter_notes == {}`）在「方案 1」之后不再成立：H 的三个落库代理是
    # 登记过的放行，会在留痕里各留一条。上面那条已把这一条剔掉再判空 ——
    # 保留的语义不变：未登记的写工具声明仍然一个都不许有。


# ============================================================ 第三道：写面分解（通用轴 / 声明写工具）
#
# 2026-10-27 的读数：`clock.*` 七件加 `conductor.ack` 升进 `UNIVERSAL_TOOLS`（写集只落在
# `tasks` 这一张簿记表上），于是只读角色的写工具从 C 的 1 件、H 的 4 件、V 的 0 件
# 长成 9 / 12 / 8 件。判据如果只数数量，这一次正当的扩容会把它判红；如果只拿
# `READONLY_CALL_EXCEPTIONS` 当期望值，同一个名字既可以是"通用能力"又可以是
# "越权写知识表的落库代理"，两侧一起变而没有人看得见。
#
# 所以下面把两档在读数上分开，三段各自承重：
#   ① 减掉通用轴之后，剩下的写工具必须逐一等于本文件里人写下（并逐条审过）的那张台账；
#   ② 通用轴那几件必须都登记在案、都发到该角色面上，且登记写集只落在通信/簿记类表上；
#   ③ 负控：往该角色的声明里塞一件写知识表的工具（`table.create`）⇒ ① 必红。

#: 只读角色「声明写工具」的台账。人逐条写下，不由实现反推。
#:
#: 为什么不直接读 `READONLY_CALL_EXCEPTIONS` 当期望值：那张表是「实现允许谁调什么」。
#: 拿它当期望值时，往它里面塞一件 `table.create` 会让比较的两侧一起变、判据照旧绿
#: （`test_injecting_a_knowledge_table_writer_into_the_declaration_goes_red` 量的就是这件事）。
#: 所以这里写的是审过的落点清单：改它必须是人逐条看过的一改。
DECLARED_READONLY_WRITE_TOOLS: dict[str, frozenset[str]] = {
    "C": frozenset({"analysis.register_report"}),
    "H": frozenset({
        "review.record_finding",
        "review.report",
        "review.review_document",
        "review.verify_fixes",
    }),
    "V": frozenset(),
}


def role_write_tools(registry, role: str) -> set[str]:
    """该角色从 `for_role` 真正拿到的写工具（副作用据实是写，不是"名字像写"）。"""
    return {s.name for s in registry.for_role(role) if s.side_effect in SIDE_EFFECTS_WRITE}


def universal_write_tools(registry) -> set[str]:
    """树上登记在案、且据实会写东西的通用能力（今天八件：clock 七件加 `conductor.ack`）。"""
    names = set(registry.names())
    return {n for n in UNIVERSAL_TOOLS
            if n in names and registry.get(n).side_effect in SIDE_EFFECTS_WRITE}


def assert_declared_write_tools(
    role: str,
    surface: Iterable[str],
    *,
    tree=None,
    declared: Mapping[str, frozenset[str]] | None = None,
) -> set[str]:
    """判据本体（① + ②）：把一个只读角色的写面拆成「通用轴」与「声明写工具」两档。

    `surface` 是该角色的写工具名集合（`role_write_tools` 的结果，或它的并集）；
    `tree` 是整棵工具层（给了才核"通用轴一件都不许漏发"这一半）；
    `declared` 只为让负控能喂一张改造过的台账，真正跑的那一次读的是本文件的常量。

    返回值是被放行的通用写工具集合，调用方可以接着做差分（三个角色应当拿到同一批）。
    """
    table = DECLARED_READONLY_WRITE_TOOLS if declared is None else declared
    got = set(surface)
    universal = {n for n in got if is_universal_tool(n)}
    rest = got - universal
    # ① 逐一点名：减掉通用轴之后剩下的必须与审过的台账相等（多一件、少一件都红）。
    assert rest == set(table[role]), (
        f"{role} 的写面分解对不上。\n"
        f"  减掉通用轴之后剩下的：{sorted(rest)}\n"
        f"  逐条审过的声明写工具：{sorted(table[role])}\n"
        f"  多出来的（越权写，例如一件写知识表的工具）：{sorted(rest - set(table[role]))}\n"
        f"  少掉的（声明了却没拿到）：{sorted(set(table[role]) - rest)}"
    )
    # ② 通用轴这一档：登记在案、只写簿记表、而且真的发到了这个角色面上。
    assert universal, (
        f"{role} 的写面上一件通用能力都没有 —— 那不是「这个角色不需要」，"
        "而是通用轴被结构性剥掉了（业主裁定：通用能力不该出现谁能用这个说法）"
    )
    for name in sorted(universal):
        assert universal_tool_is_bookkeeping_only(name), (
            f"通用能力 {name} 的登记写集 {sorted(universal_tool_tables(name) or ())} 越出了"
            f"通信/簿记类表 {sorted(BOOKKEEPING_TABLES)} —— 通用能力写知识表，"
            "就是把「谁都能用」变成「谁都能改知识表」的后门"
        )
    writing = {n for n in universal if universal_tool_tables(n)}
    assert writing, (
        "通用轴上没有一件登记的写集非空 —— ② 的「只许写簿记表」今天没有可核的写集"
    )
    for name in sorted(writing):
        assert set(universal_tool_tables(name) or ()) <= set(BOOKKEEPING_TABLES), name
    if tree is not None:
        expected = universal_write_tools(tree)
        assert expected <= got, (
            f"通用轴上据实会写东西的这几件没有全部发给 {role}：{sorted(expected - got)}"
            "（通用能力漏发就是「谁都能用」这句话在实现上不成立）"
        )
    return universal


def test_declared_write_tools_are_exactly_the_non_universal_write_tools(store):
    """① + ②：C / H / V 三个只读角色逐个把写面拆成通用轴与声明写工具。

    三个角色必须给出三份不同的声明读数（C 一件、H 四件、V 零件），否则"逐个核"
    只是把同一条断言跑三遍；而通用轴那一档三个角色必须完全一样（八件），
    否则"通用能力谁都能拿"就有角色被漏掉。
    """
    build = build_registry(store=store, workspace_root=store.root)
    assert build.skipped == [], build.skipped
    reg = build.registry

    assert set(DECLARED_READONLY_WRITE_TOOLS) == set(READ_ONLY_ROLES), (
        f"台账的角色 {sorted(DECLARED_READONLY_WRITE_TOOLS)} 与只读角色名单 "
        f"{sorted(READ_ONLY_ROLES)} 不一致"
    )
    assert any(DECLARED_READONLY_WRITE_TOOLS.values()), (
        "三个角色的声明写工具全是空集 —— ① 今天没有可核的东西"
    )

    universal_by_role: dict[str, set[str]] = {}
    for role in READ_ONLY_ROLES:
        universal_by_role[role] = assert_declared_write_tools(
            role, role_write_tools(reg, role), tree=reg
        )

    # 差分一：声明那一档三个角色互不相同（H 四件 / C 一件 / V 零件），
    # 所以"逐个核"真的核了三份不同的东西。
    declared_reading = {r: sorted(DECLARED_READONLY_WRITE_TOOLS[r]) for r in READ_ONLY_ROLES}
    assert declared_reading == {
        "C": ["analysis.register_report"],
        "H": ["review.record_finding", "review.report", "review.review_document",
              "review.verify_fixes"],
        "V": [],
    }, declared_reading
    # 差分二：通用轴那一档三个角色完全一样 —— 同一个集合，不按角色分配。
    expected_universal = universal_write_tools(reg)
    assert expected_universal, "树上没有一件据实会写东西的通用能力 ⇒ ② 没有可核的对象"
    for role, got in universal_by_role.items():
        assert got == expected_universal, (
            f"{role} 拿到的通用写工具与通用的定义不一致：{sorted(got)} ≠ "
            f"{sorted(expected_universal)}（通用能力按判据分配，不按角色分配）"
        )


def test_the_universal_axis_may_not_write_a_knowledge_table():
    """② 的负控那一半：登记写集碰知识表 ⇒ `universal_tool_is_bookkeeping_only` 必假。

    正控是 `assert_declared_write_tools` 里那句逐件断言；这里造一件形状正确、
    只是"写的是 `statements`"的通用登记，证明那句断言真的会咬。
    """
    probe = {"probe.knowledge": UniversalTool("判据探针：写 statements", frozenset({"statements"}))}
    assert not universal_tool_is_bookkeeping_only("probe.knowledge", universal=probe), (
        "一件登记自己会写 statements 的通用能力被读成了「只写簿记表」⇒ ② 是空转"
    )
    # 同一件探针把登记写集换成 `tasks` 就必须过 —— 否则上一条只是"恒假"。
    assert universal_tool_is_bookkeeping_only(
        "probe.knowledge",
        universal={"probe.knowledge": UniversalTool("判据探针：只写 tasks", frozenset({"tasks"}))},
    ), "只写 tasks 的通用登记被读成了越界 ⇒ 这条判据的方向反了"


def test_injecting_a_knowledge_table_writer_into_the_declaration_goes_red(store, monkeypatch):
    """③ 负控：往 H 的声明里塞一件写知识表的工具（`table.create`）⇒ ① 必红。

    "声明"在这条负控里是实打实的两处声明，缺一处都塞不进去：工具的 `roles`（谁拿得到）
    与 `READONLY_CALL_EXCEPTIONS["H"]`（只读角色的写落点）。两处都改完，`for_role("H")`
    就会真的把 `table.create` 发出去 —— 那是一把能改知识表的刀。判据必须当场红，
    而不是跟着声明一起变绿：这就是 ① 拿本文件那张人审过的台账当期望值的理由。
    """
    import dataclasses

    from agentflow.tools.base import READONLY_CALL_EXCEPTIONS as EXC

    build = build_registry(store=store, workspace_root=store.root)
    assert build.skipped == [], build.skipped
    reg = build.registry
    assert "table.create" in reg.names(), "夹具前提崩了：树上没有 table.create"
    assert "table.create" not in role_write_tools(reg, "H"), (
        "夹具前提崩了：H 本来就不该拿到 table.create"
    )
    spec = reg._specs["table.create"]
    assert "H" not in spec.roles, f"夹具前提崩了：table.create 已经声明给 H 了：{spec.roles}"
    monkeypatch.setitem(
        reg._specs, "table.create", dataclasses.replace(spec, roles=(*spec.roles, "H")),
    )
    monkeypatch.setitem(
        EXC, "H", (*EXC["H"], ("table.create", "判据负控：往声明里塞一件写知识表的工具")),
    )
    poisoned = role_write_tools(reg, "H")
    assert "table.create" in poisoned, "注入没生效：H 的写面上没多出 table.create"
    with pytest.raises(AssertionError, match="table.create"):
        assert_declared_write_tools("H", poisoned, tree=reg)
    # 负控的负控：把注入撤掉，同一份判据必须照旧绿（红不是从别处来的）。
    monkeypatch.undo()
    assert_declared_write_tools("H", role_write_tools(reg, "H"), tree=reg)
