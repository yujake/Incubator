"""只读角色的权限面必须由结构保证，不能只靠工具声明。

## 缺陷（子智能体实测发现）

`table.*` / `fs.*` 在注册时把注入的全部 `ROLES` 写进了每个工具的 `roles`，
于是按角色装配出来的审校者 H 的工具面里出现了 `table.update`、`fs.write`、
`verify.run_experiment` —— 也就是说 H 手里有能改数据/稿件的刀。

而"H 只读"不是洁癖：若审校者能直接改，它就同时是"发现者"与"修正者"，
于是"发现问题"与"掩盖问题"在结构上无法区分。
C 同理：一旦 C 能写，它就成了"绕过 B 引文回验"的写入路径，
而 B 的引文逐字回验是全系统唯一能自动发现幻觉引文的地方。

## 修法（两道防线，缺一不可）

1. 声明正确：写工具的角色集合里不含只读角色（`table_tools` / `fs_tools` /
   `verify_tools` 各自过一遍）。
2. `ToolRegistry.for_role` 结构性拦截：对只读角色，无论 spec 怎么声明，
   一律过滤掉有写副作用的工具，并把被剥掉的名字记进 `role_filter_notes`
   （静默过滤会让"声明错误"永远暴露不了）。

本文件守的是第 2 道 —— 因为它才是"工具作者无法绕过"的那一道。
"""

from __future__ import annotations

from agentflow.tools import READ_ONLY_ROLES, ROLES, SIDE_EFFECTS_WRITE, build_registry
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


def test_read_only_roles_are_exactly_c_and_h():
    """只读角色的单一来源。改动这里必须同时改设计文档与 C/H 的实现。"""
    assert READ_ONLY_ROLES == ("C", "H")
    assert set(READ_ONLY_ROLES) <= set(ROLES)


def test_for_role_strips_write_tools_from_read_only_roles():
    """核心负控：即使 spec 声明 `roles=("C",)` 而 `side_effect="write_local"`，
    `for_role("C")` 也不得返回它。

    这一条正是"工具作者无法绕过"的证明：声明写错也不会真的把刀交出去。
    """
    reg = ToolRegistry(name="t")
    reg.register(_spec("bad.write", "write_local", ("C", "H")))
    reg.register(_spec("bad.net", "network", ("C",)))
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
    assert reg.role_filter_notes == {}


def test_real_registry_gives_no_write_tool_to_read_only_roles(store):
    """端到端：真实装配出来的工具层里，C 与 H 的工具面 0 个写工具。"""
    build = build_registry(store=store, workspace_root=store.root)
    assert build.skipped == [], build.skipped
    for role in READ_ONLY_ROLES:
        specs = build.registry.for_role(role)
        leaks = [s.name for s in specs if s.side_effect in SIDE_EFFECTS_WRITE]
        assert leaks == [], f"{role} 的工具面里有写工具：{leaks}"
        assert specs, f"{role} 一个工具都没有 —— 那不是只读，那是没接线"
    # 声明侧也应当已经干净（`for_role` 的留痕为空），否则说明有人又写错了 roles
    assert build.registry.role_filter_notes == {}, (
        "有工具的 roles 声明把写工具给了只读角色（行为已被拦下，但声明要改）："
        f"{build.registry.role_filter_notes}"
    )


def test_every_write_tool_declares_at_least_one_writing_role(store):
    """负控：任何写工具都必须至少有一个写角色 —— 否则它谁都拿不到（等于死工具）。"""
    build = build_registry(store=store, workspace_root=store.root)
    orphan = [
        s.name for s in build.registry._specs.values()
        if s.side_effect in SIDE_EFFECTS_WRITE and not (set(s.roles) - set(READ_ONLY_ROLES))
    ]
    assert orphan == [], f"这些写工具没有任何写角色能拿到：{orphan}"


def test_side_effect_vocabulary_is_the_single_source():
    """`SIDE_EFFECTS_WRITE` 必须是 `SIDE_EFFECTS` 的尾部子集（不是另写一份词表）。"""
    assert set(SIDE_EFFECTS_WRITE) <= set(SIDE_EFFECTS)
    assert set(SIDE_EFFECTS_WRITE) == {"write_local", "network"}


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


def test_real_registry_has_no_exec_tool_and_filter_notes_stay_empty(store):
    """真实树上的现状：55 个工具里没有一个声明 `external="exec"`。

    这条断言是"本轮不改变行为"的直接证据：`external` 是本轮新加的轴，
    默认 `none` ⇒ `for_role` 的新剥离条件对既有工具一次都不触发
    （`role_filter_notes` 仍然为空）。B3 迁移 `verify.run_experiment` 等工具时，
    这条断言会变红 —— 那时它正是"受影响清单"的触发器。
    """
    build = build_registry(store=store, workspace_root=store.root)
    execs = sorted(s.name for s in build.registry._specs.values() if s.external == "exec")
    assert execs == [], f"出现了声明 exec 的工具：{execs}（H/C 会因此少掉它们，见 P-13 §8.2）"
    for role in READ_ONLY_ROLES:
        build.registry.for_role(role)
    assert build.registry.role_filter_notes == {}, build.registry.role_filter_notes
