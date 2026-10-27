# -*- coding: utf-8 -*-
"""通用能力不属于任何角色（业主裁定：「通用能力根本不该出现谁能用这个说法」）。

## 这个文件修的是什么

改前：`clock.timer_start` / `clock.alarm_start` / `clock.timer_cancel` 会写
`tasks` 的 notice 行与 `out/clock` 的状态，却都声明 `side_effect="read"` ——
那是谎报。谎报的目的很具体：`ToolRegistry.for_role` 对只读角色剥掉一切写工具，
而业主 D-53 要求"所有角色都能用"。于是两根轴被压成了一根。

改后：副作用据实（这三件是 `write_local`），可达性交给另一根轴 ——
`tools.UNIVERSAL_TOOLS` 这张受控集合。通用工具不因为副作用等级被剥掉；
硬约束是它写的表只许落在通信/簿记类表上（`BOOKKEEPING_TABLES`），
碰知识表（`statements` / `claims` / `literature` / `relations` / `documents` …）
⇒ 判据直接红，而且运行时也不发给只读角色。

## 判据读法：两根轴各读一处

- 副作用轴：`reg.get(<工具名>).side_effect`（据实声明）；
- 可达性轴：`reg.for_role(<角色>)` 与 `tools.UNIVERSAL_TOOLS`（通用能力的受控集合）。

"一视同仁"这件事不靠例外表：`READONLY_CALL_EXCEPTIONS` 是"这个只读角色可以调这几个
写工具"的逐条登记，它的语义就是"谁能用" —— 通用能力不该进那张表。

## 六条判据（施工单 a–f）

a) 十一个角色都拿得到五件 `clock.*`，且例外表里没有 clock 条目；
b) 通用工具一律不写知识表（登记写集 ⊆ 通信/簿记表，且实现算出的写集 ⊆ 登记写集）；
c) 负控：非通用的写工具（`table.update` / `fs.write` / `doc.build_document`）
   只读角色仍然拿不到 —— 闸没有被整扇打开；
d) 反真空：把"所有工具都是 universal"打桩 ⇒ b 必红；把通用集合清空 ⇒ a 必红；
e) 据实与可达必须同时成立：`clock.timer_start` 是 `write_local`（真话），
   而它对 C / H / V 仍然可用（真事）；
f) 声明面与发出的面双向对得上（Q15，2026-10-26）：`conductor.post_task` 进通用集合 ⇒
   `roles` 声明的十一个角色里，凡没拿到的都必须有一个结构性理由（今天只有"被 Lean
   开关藏起来"这一种），而 C / H / V 必须拿得到 —— 它们同样会收到"要求做事"的消息，
   而"给自己落一条 work 项"是那条口径下唯一合法的落项手。

## 改前红的读数

改前跑本文件：`agentflow.tools` 上既没有 `UNIVERSAL_TOOLS`、也没有本文件读的判据
（`is_universal_tool` / `universal_tool_violations` / `BOOKKEEPING_TABLES`），
于是五条全部以 `AttributeError` 失败（不是跳过、不是空集通过）；
e 另外还会在 `side_effect == "read"` 那一条上红，a/c 会在"只读角色拿不到"上红。

## 为什么 b 用 `capabilities._tool_write_set_from_source`

"它到底写哪几张表"必须从实现读，不能只信登记 —— 否则登记写成空集就能把后门洗白。
仓库里唯一的那个扫描器在 `capabilities`（只读例外的判据 `[5c]` 用的就是它），
本文件直接用它，不复制第二份（FC-03）。方向是"实现 ⊆ 登记 ⊆ 通信/簿记表"：
登记是上界（`clock.timer_start` 的 `tasks` 行由到点那一侧落，扫描器跟不到那里），
而"实现写了登记之外的表"这个方向逐条判红，所以上界不会变成缺口。
"""

from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import ROLES

#: 十一个角色 = 可召唤的十个（A–H / V / L）+ 主控 M。与 `tools.TOOL_ROLES` 同源。
ELEVEN_ROLES: tuple[str, ...] = tuple(ROLES) + (S.CONDUCTOR_ROLE,)

#: D-53 的时钟五件：全都得是"所有人可拿"。
CLOCK_TOOLS: frozenset[str] = frozenset({
    "clock.now",
    "clock.timer_start",
    "clock.alarm_start",
    "clock.timer_list",
    "clock.timer_cancel",
})

#: 会写东西的那三件（据实是 `write_local`）。它们正是改前被谎报成 `read` 的三件。
CLOCK_WRITE_TOOLS: frozenset[str] = frozenset({
    "clock.timer_start",
    "clock.alarm_start",
    "clock.timer_cancel",
})


def _tools():
    """惰性导入被测模块。

    惰性导入是刻意的：改前红要逐条看见原因（五条各自的 `AttributeError`），
    而不是整个文件在 collection 阶段就停住、看起来像"一条都没写"。
    """
    from agentflow import tools as T

    return T


def _registry(tmp_path):
    """一份真实的工具层（临时工作区，离线；`strict=True` 不许任何模块被跳过）。"""
    T = _tools()
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root)
    store.init()
    build = T.build_registry(store=store, workspace_root=root, strict=True)
    assert build.skipped == [], f"有模块被跳过（这一份面不完整）：{build.skipped}"
    return build.registry


def _assert_everyone_gets_the_clock(reg) -> None:
    """判据 a 的本体：十一个角色都拿得到五件 `clock.*`，且不靠例外表。"""
    T = _tools()
    assert len(ELEVEN_ROLES) == 11, f"角色词汇不是十一个：{ELEVEN_ROLES}"
    missing: dict[str, list[str]] = {}
    for role in ELEVEN_ROLES:
        got = {s.name for s in reg.for_role(role)}
        lack = CLOCK_TOOLS - got
        if lack:
            missing[role] = sorted(lack)
    assert not missing, f"这些角色拿不到时钟（通用能力不该有谁能用这回事）：{missing}"
    # 不靠例外表：通用能力一旦进例外表，"它为什么可用"就有两个互相独立的来源。
    exempt = {name for entries in T.READONLY_CALL_EXCEPTIONS.values() for name, _w in entries}
    assert not (CLOCK_TOOLS & exempt), (
        f"`READONLY_CALL_EXCEPTIONS` 里出现了 clock 条目：{sorted(CLOCK_TOOLS & exempt)} —— "
        "那是一张'谁能用'的例外表，通用能力不许走它"
    )
    # 也不许"在例外表里没有、但也没登记成通用"这种半吊子状态。
    not_universal = sorted(n for n in CLOCK_TOOLS if not T.is_universal_tool(n))
    assert not not_universal, f"这些 clock 工具没有登记成通用能力：{not_universal}"


def _assert_call_time_reachability(reg) -> None:
    """判据 a 的另一半：只读角色在调用期也放行（`P-14`：工具面只是第一道）。

    这里不要求调用成功 —— 没有台账号时的受控失败（`not_found`）正说明它走到了工具体。
    要的是"不是 `role_denied`"。
    """
    for role in ("C", "H", "V"):
        res = reg.call("clock.timer_start", role=role, after_sec=5,
                       reason="判据：通用能力的调用期可达性", to="self")
        assert res.meta.get("kind") != "role_denied", (
            f"{role} 在调用期被拒了（可达性只在工具面上成立，`P-14` 那道闸没跟上）："
            f"{res.to_dict()}"
        )


def _assert_no_universal_tool_writes_knowledge_tables(*, universal=None) -> None:
    """判据 b 的本体：通用工具的写集只落在通信/簿记类表上（含实现侧比对）。"""
    T = _tools()
    from agentflow.capabilities import _tool_write_set_from_source

    table = dict(T.UNIVERSAL_TOOLS if universal is None else universal)
    write_sets = {name: _tool_write_set_from_source(name) for name in table}
    bad = T.universal_tool_violations(write_sets, universal=table)
    assert not bad, (
        "这些通用工具的写集越界（通用能力只许写通信/簿记类表，不许写知识表）："
        f"{bad}"
    )
    # 反向：知识表一个都不许出现在登记里（`universal_tool_violations` 已经判了，
    # 这里再按名字列一遍，让失败信息能直接读出来是哪张表）。
    knowledge = set(T.KNOWLEDGE_TABLES)
    hits = {
        name: sorted(set(entry.tables) & knowledge)
        for name, entry in table.items()
        if set(entry.tables) & knowledge
    }
    assert not hits, f"通用工具的登记写集里出现了知识表：{hits}"


# ============================================================ a) 十一个角色都拿得到
def test_a_all_eleven_roles_get_the_five_clock_tools_without_the_exception_table(tmp_path) -> None:
    """通用能力：A–H / V / L 与主控 M 都拿得到五件 `clock.*`，且靠的是通用集合不是例外表。"""
    reg = _registry(tmp_path)
    _assert_everyone_gets_the_clock(reg)
    _assert_call_time_reachability(reg)
    # 逐角色点名一遍只读角色：这一档是改前唯一被剥的地方，最值得单独留痕。
    for role in ("C", "H", "V"):
        got = {s.name for s in reg.for_role(role)}
        assert CLOCK_TOOLS <= got, f"只读角色 {role} 拿不到时钟：{sorted(CLOCK_TOOLS - got)}"


def test_a2_h_free_toolbox_keeps_universal_and_still_refuses_real_write_tools(tmp_path) -> None:
    """H 的装配路径（第二道闸）也必须收下通用能力，且仍然拒掉真正的写工具。

    为什么这条要在本文件里：`for_role` 放行只是第一道；`install_h_tools` 还会用
    `agent_h.h_free_toolbox_accepts` 再裁一次。两道判据不同步的话，"所有角色都能用"
    在 H 这里就是空话，而工具层的判据照样绿。
    """
    T = _tools()
    from agentflow.agent_h import filter_readonly_h_surface

    reg = _registry(tmp_path)
    kept, refused = filter_readonly_h_surface(reg.for_role("H"))
    kept_names = {s.name for s in kept}
    refused_names = {r["name"] for r in refused}
    assert CLOCK_TOOLS <= kept_names, (
        f"H 的自由工具箱把通用能力当写工具拒了：{sorted(CLOCK_TOOLS - kept_names)}"
    )
    assert "conductor.escalate" in kept_names and "trace.children" in kept_names
    assert not ({name for name in T.UNIVERSAL_TOOLS} & refused_names), (
        f"H 的自由工具箱拒掉了通用能力：{sorted({n for n in T.UNIVERSAL_TOOLS} & refused_names)}"
    )
    # 闸没整扇开：真正的写工具仍然被拒，而且理由被记下来（不是静默丢弃）。
    probe_refused = filter_readonly_h_surface([
        T.ToolSpec(
            name="table.update",
            summary="判据用探针：真正的写工具",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda **_: T.ok({}),
            side_effect="write_local",
            roles=("H",),
            returns="{'ok'}",
        )
    ])[1]
    assert [r["name"] for r in probe_refused] == ["table.update"], probe_refused


# ============================================================ b) 通用工具不写知识表
def test_b_no_universal_tool_writes_a_knowledge_table(tmp_path) -> None:
    """通用工具一律不写知识表：登记 ⊆ 通信/簿记表，实现 ⊆ 登记。"""
    T = _tools()
    _assert_no_universal_tool_writes_knowledge_tables()
    # 反真空：这条判据今天必须真的核到了东西。
    # 1) 至少一件通用工具的登记写集非空（否则"只写通信/簿记"什么也没核到）；
    non_empty = sorted(n for n, e in T.UNIVERSAL_TOOLS.items() if e.tables)
    assert non_empty, "所有通用工具的登记写集都是空集 ⇒ 这条判据今天没有可核的写集"
    assert "clock.timer_start" in non_empty, (
        "`clock.timer_start` 据实会写 `tasks` 的 notice 行 ⇒ 它的登记写集不该是空集"
    )
    # 2) 登记的写集恰好是通信/簿记表（不许多登记一张）。
    for name in non_empty:
        assert set(T.UNIVERSAL_TOOLS[name].tables) <= set(T.BOOKKEEPING_TABLES), name
    # 3) 知识表与通信/簿记表必须是不相交的两栏：交集非空会让"只许写簿记"这句话无意义。
    assert not (set(T.KNOWLEDGE_TABLES) & set(T.BOOKKEEPING_TABLES)), (
        f"知识表与通信/簿记表有交集：{sorted(set(T.KNOWLEDGE_TABLES) & set(T.BOOKKEEPING_TABLES))}"
    )


# ============================================================ c) 负控：闸没整扇开
def test_c_non_universal_write_tools_are_still_refused_to_read_only_roles(tmp_path) -> None:
    """负控：`table.update` / `fs.write` / `doc.build_document` 这些非通用写工具照旧拿不到。"""
    T = _tools()
    reg = _registry(tmp_path)
    for name in ("table.update", "fs.write", "doc.build_document"):
        assert not T.is_universal_tool(name), f"{name} 不该被登记成通用能力"
    for role in ("C", "H", "V"):
        got = {s.name for s in reg.for_role(role)}
        for name in ("table.update", "fs.write", "doc.build_document"):
            assert name not in got, f"{role} 的工具面里出现了非通用的写工具 {name}（闸被整扇打开了）"
    # 调用期同样拦（`for_role` 只是第一道；`P-14` 要求在 `call` 里再判一次）。
    #
    # 这里的理由串是"它不在这个角色的可调用面里"，而不是"结构性过滤把它剥掉了"：
    # `table.update` 的 `roles` 里本来就没有 C（声明侧也干净），所以它压根不在 C 的
    # 声明面上。那一句"被只读约束剥掉"只会出现在"声明里有 C、但它是写工具"的形态上
    # —— 真实树上今天没有这种工具（有的话 `for_role` 的留痕会点名），
    # 合成的那种形态由 d3 的探针覆盖。
    denied = reg.call("table.update", role="C")
    assert denied.ok is False and denied.meta.get("kind") == "role_denied", denied.to_dict()
    assert "拿不到工具" in str(denied.error), denied.error


# ============================================================ d) 反真空
def test_d1_the_write_set_judgement_goes_red_if_every_tool_is_declared_universal(tmp_path) -> None:
    """反真空（b 的方向）：把"所有工具都是 universal"打桩 ⇒ b 的判据必红。"""
    T = _tools()
    reg = _registry(tmp_path)
    stubbed = {
        name: T.UniversalTool("桩：把所有工具都当成通用能力（只为证明判据不是真空的）", frozenset())
        for name in reg.names()
    }
    assert len(stubbed) > 50, "桩太少了，这条证明不了判据在真树上会咬"
    with pytest.raises(AssertionError, match="写集越界"):
        _assert_no_universal_tool_writes_knowledge_tables(universal=stubbed)
    # 并且它是因为"知识表"才红的，不是随便什么理由：
    from agentflow.capabilities import _tool_write_set_from_source

    bad = T.universal_tool_violations(
        {name: _tool_write_set_from_source(name) for name in stubbed}, universal=stubbed
    )
    flat = " ".join(reason for reasons in bad.values() for reason in reasons)
    assert "documents" in flat or "literature" in flat or "知识表" in flat, (
        f"把所有工具都当通用能力之后，判据没有点出知识表：{bad}"
    )


def test_d2_the_reachability_judgement_goes_red_if_the_universal_set_is_emptied(tmp_path, monkeypatch) -> None:
    """反真空（a 的方向）：把通用集合清空 ⇒ a 的判据必红（三件写工具会被剥掉）。"""
    T = _tools()
    reg = _registry(tmp_path)
    # 基线：清空之前 a 是绿的（否则下面的"红"证明不了任何事）。
    _assert_everyone_gets_the_clock(reg)
    monkeypatch.setattr(T, "UNIVERSAL_TOOLS", {}, raising=True)
    with pytest.raises(AssertionError, match="拿不到时钟"):
        _assert_everyone_gets_the_clock(reg)
    # 差分：被剥掉的恰好是会写东西的那三件，只读的两件不受影响
    # （否则"红"可能只是把所有 clock 工具都弄没了）。
    got = {s.name for s in reg.for_role("C")}
    assert not (CLOCK_WRITE_TOOLS & got), sorted(CLOCK_WRITE_TOOLS & got)
    assert {"clock.now", "clock.timer_list"} <= got, sorted(got)


def test_d3_a_universal_entry_that_writes_knowledge_tables_is_refused_at_runtime(monkeypatch) -> None:
    """硬约束的运行时那一半：登记写集越界的通用工具不发给只读角色（fail-closed + 留痕）。

    同一张合成注册表里放两件形状相同的探针，只有"登记写的是哪张表"不同：
    `probe.bookkeeping` 写 `tasks`（通信/簿记）⇒ 发给 C；
    `probe.knowledge` 写 `statements`（知识表）⇒ 不发给 C，并留一条痕。
    """
    T = _tools()
    from agentflow.tools.base import ToolRegistry

    monkeypatch.setattr(
        T,
        "UNIVERSAL_TOOLS",
        {
            "probe.bookkeeping": T.UniversalTool("判据探针：只写 tasks", frozenset({"tasks"})),
            "probe.knowledge": T.UniversalTool("判据探针：写 statements", frozenset({"statements"})),
        },
        raising=True,
    )
    reg = ToolRegistry(name="universal-hard-constraint")
    for name in ("probe.bookkeeping", "probe.knowledge"):
        reg.register(T.ToolSpec(
            name=name,
            summary="判据探针",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda **_: T.ok({}),
            side_effect="write_local",
            roles=("C",),
            returns="{'ok'}",
        ))
    got = {s.name for s in reg.for_role("C")}
    assert "probe.bookkeeping" in got, "登记只写 tasks 的通用工具被误伤了"
    assert "probe.knowledge" not in got, "登记写知识表的工具仍然发给了只读角色（后门）"
    notes = " ".join(reg.role_filter_notes.get("C", []))
    assert "probe.knowledge" in notes and "通信/簿记" in notes, reg.role_filter_notes
    # 调用期也拦，而且理由串点名"结构性过滤把它剥掉了"（这里才是那一句该出现的地方：
    # 探针的 `roles` 声明里有 C，它不是"压根不在面上"）。
    denied = reg.call("probe.knowledge", role="C")
    assert denied.ok is False and denied.meta.get("kind") == "role_denied", denied.to_dict()
    assert "结构性过滤" in str(denied.error), denied.error


# ============================================================ e) 据实与可达同时成立
def test_e_clock_timer_start_is_truthfully_write_local_and_still_available_to_read_only(tmp_path) -> None:
    """`clock.timer_start` 的副作用据实是 `write_local`，而它仍然对 C / H / V 可用。

    这一对必须同时成立：只留前一半 ⇒ 通用能力被剥掉（改前的病）；
    只留后一半（谎报成 `read`）⇒ 声明在说谎（改前的病灶）。
    """
    T = _tools()
    reg = _registry(tmp_path)
    spec = reg.get("clock.timer_start")
    assert spec.side_effect == "write_local", (
        "`clock.timer_start` 会写 `out/clock` 的状态、到点还会落一条 `tasks` notice 行 —— "
        f"据实必须是 write_local，收到 {spec.side_effect!r}（改成 read 就是谎报）"
    )
    assert spec.needs_approval is True, "write_local 的审批判据是推导出来的，这里也该跟上"
    # 只读的两件仍然是 read，写的那三件都据实
    assert reg.get("clock.now").side_effect == "read"
    assert reg.get("clock.timer_list").side_effect == "read"
    for name in ("clock.alarm_start", "clock.timer_cancel"):
        assert reg.get(name).side_effect == "write_local", name
    # 同一件事的另一半：仍然可用（而且不靠例外表 —— 见 a）。
    for role in ("C", "H", "V"):
        got = {s.name for s in reg.for_role(role)}
        assert "clock.timer_start" in got, f"{role} 拿不到据实为 write_local 的通用工具"
    # 差分：把它从通用集合里撤掉，同一件工具立刻被剥掉 —— 证明"可用"来自通用集合，
    # 不是来自某个恰好没被拦住的漏洞。
    with pytest.MonkeyPatch.context() as m:
        m.setattr(T, "UNIVERSAL_TOOLS", {}, raising=True)
        assert "clock.timer_start" not in {s.name for s in reg.for_role("C")}


# ================================================ f) 声明面 = 发出的面（Q15）
#: Q15 的那一件：`conductor.post_task` 的 `roles` 声明是十一个角色，而改前只有七个拿到
#: （C/H/V 被只读约束剥掉、L 被 Lean 开关藏起来）。改前的注释逐字写着"由
#: `UNIVERSAL_TOOLS` 那条判据放行"，而那一句是事实错误 —— 那张表里没有它。
#: 2026-10-26 的裁定是走 (a)：把 `conductor.post_task` 登记成通用能力（它只写 `tasks`，
#: 在 `BOOKKEEPING_TABLES` 之内，构造上合法），于是声明与行为重新对齐。
POST_TASK = "conductor.post_task"

#: 三档"会收到要办的事"的只读角色：它们必须拿得到落项的手（(a) 的全部理由）。
READ_ONLY_HANDS: tuple[str, ...] = ("C", "H", "V")


def _surface_gap(reg) -> tuple[list[str], dict[str, str]]:
    """声明与行为之间的差：`(没有理由的漂移, {角色: 结构性理由})`（Q15 的判据本体）。

    两个方向各判一次：
      - `行为 ⊆ 声明`：拿得到却没声明 ⇒ 权限面漏出去一格；
      - `声明 ⊆ 行为 ∪ 结构性理由`：声明了却拿不到 ⇒ 要么它是通用能力却没登记，
        要么声明本身就是空话。

    结构性理由只认一种：角色被 Lean 开关藏起来（`leanscope.is_hidden`；声明没变，
    两个面都是空的）。"只读角色 + 写工具"在这里不算理由 —— 裁定既然是"进通用集合"，
    那 C/H/V 拿不到它就不是"结构性剥离"，而是行为面掉了。
    """
    T = _tools()
    from agentflow import leanscope as LEANSCOPE

    spec = reg.get(POST_TASK)
    declared = set(spec.roles)
    surface = {role: {s.name for s in reg.for_role(role)} for role in ELEVEN_ROLES}
    drift: list[str] = []
    for role in sorted(ELEVEN_ROLES):
        if POST_TASK in surface[role] and role not in declared:
            drift.append(f"{role} 拿得到 {POST_TASK}，而它的 `roles` 声明里没有这个角色")
    explained: dict[str, str] = {}
    for role in sorted(declared):
        if POST_TASK in surface[role]:
            continue
        if LEANSCOPE.is_hidden(role):
            explained[role] = "被 Lean 开关藏起来（两个面都是空的，与声明无关）"
        else:
            drift.append(
                f"{role} 在 `roles` 声明里，却拿不到 {POST_TASK}"
                "（没有任何结构性理由 —— 要么登记成通用能力，要么把声明收掉）")
    return drift, explained


def test_f_post_task_is_a_universal_tool_so_the_declaration_matches_the_surface(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 f（Q15，改前红）：`conductor.post_task` 进通用集合 ⇒ 声明与行为双向对得上。

    改前读数（同一份装配）：`roles` 声明 11 个，`for_role` 只发给
    `['A', 'B', 'D', 'E', 'F', 'G', 'M']` 7 个 —— 差的是 C / H / V / L，
    而那条注释还写着"由 `UNIVERSAL_TOOLS` 那条判据放行"（它不在那张表里）。
    """
    T = _tools()
    reg = _registry(tmp_path)
    spec = reg.get(POST_TASK)
    # ① 它确实是一件通用能力，且登记的写集只落在簿记表上（否则"对十一个角色都发"是后门）。
    assert T.is_universal_tool(POST_TASK), (
        f"{POST_TASK} 没有登记成通用能力 —— 它的 `roles` 声明是十一个角色，"
        "而只读角色 C/H/V 会被结构性剥掉（声明与行为分家，判定见 ②）")
    assert T.universal_tool_tables(POST_TASK) == frozenset({"tasks"}), (
        f"{POST_TASK} 登记写的表是 {T.universal_tool_tables(POST_TASK)!r}，"
        f"而它只该写 `tasks` 的一行板项")
    assert T.universal_tool_is_bookkeeping_only(POST_TASK)
    exempt = {name for entries in T.READONLY_CALL_EXCEPTIONS.values() for name, _w in entries}
    assert POST_TASK not in exempt, (
        f"{POST_TASK} 出现在只读例外表里 —— 通用能力不许走例外表（两条独立的来源）")
    # ② 双向：行为 ⊆ 声明，且声明 ⊆ 行为 ∪ 结构性理由。
    drift, explained = _surface_gap(reg)
    assert drift == [], (
        f"{POST_TASK} 的声明面与发出的面对不上：\n  - " + "\n  - ".join(drift)
        + f"\n（有结构性理由的缺席：{explained}；声明 {sorted(spec.roles)}）")
    # ③ (a) 的落点：C / H / V 收到"要求做事"的消息时，也有落项的合法手。
    for role in READ_ONLY_HANDS:
        got = {s.name for s in reg.for_role(role)}
        assert POST_TASK in got, (
            f"只读角色 {role} 拿不到 {POST_TASK} —— 它同样会收到"
            "「这条消息要求做事」的那一条，而那正是唯一合法的落项手")
    # ④ 反真空：把它从通用集合里撤掉 ⇒ 同一双判据立刻说 C/H/V 漂移。
    with monkeypatch.context() as m:
        m.setattr(T, "UNIVERSAL_TOOLS",
                  {k: v for k, v in T.UNIVERSAL_TOOLS.items() if k != POST_TASK},
                  raising=True)
        drift2, _explained2 = _surface_gap(reg)
        assert drift2, (
            f"把 {POST_TASK} 从 UNIVERSAL_TOOLS 撤掉，双向判据居然还是绿的 —— 它是橡皮图章")
        flat = " ".join(drift2)
        for role in READ_ONLY_HANDS:
            assert role in flat, (
                f"撤掉之后判据没有点名 {role}（它正是被剥掉的那一档）：{drift2}")

