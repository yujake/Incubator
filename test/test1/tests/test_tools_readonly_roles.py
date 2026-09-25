"""只读角色的**权限面**必须由结构保证，不能只靠工具声明。

## 缺陷（子智能体实测发现）

`table.*` / `fs.*` 在注册时把注入的**全部** `ROLES` 写进了每个工具的 `roles`，
于是按角色装配出来的**审校者 H 的工具面**里出现了 `table.update`、`fs.write`、
`verify.run_experiment` —— 也就是说 **H 手里有能改数据/稿件的刀**。

而"H 只读"不是洁癖：若审校者能直接改，它就同时是"发现者"与"修正者"，
于是**"发现问题"与"掩盖问题"在结构上无法区分**。
C 同理：一旦 C 能写，它就成了"绕过 B 引文回验"的写入路径，
而 B 的引文逐字回验是全系统**唯一**能自动发现幻觉引文的地方。

## 修法（两道防线，缺一不可）

1. **声明正确**：写工具的角色集合里不含只读角色（`table_tools` / `fs_tools` /
   `verify_tools` 各自过一遍）。
2. **`ToolRegistry.for_role` 结构性拦截**：对只读角色，无论 spec 怎么声明，
   一律过滤掉有写副作用的工具，并把被剥掉的名字**记进 `role_filter_notes`**
   （静默过滤会让"声明错误"永远暴露不了）。

本文件守的是第 2 道 —— 因为它才是"工具作者无法绕过"的那一道。
"""

from __future__ import annotations

from abflow.tools import READ_ONLY_ROLES, ROLES, SIDE_EFFECTS_WRITE, build_registry
from abflow.tools.base import SIDE_EFFECTS, ToolRegistry, ToolSpec, ok


def _spec(name: str, side_effect: str, roles: tuple[str, ...]) -> ToolSpec:
    return ToolSpec(
        name=name,
        summary="测试用",
        params={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda: ok({}),
        side_effect=side_effect,
        roles=roles,
    )


def test_read_only_roles_are_exactly_c_and_h():
    """只读角色的**单一来源**。改动这里必须同时改设计文档与 C/H 的实现。"""
    assert READ_ONLY_ROLES == ("C", "H")
    assert set(READ_ONLY_ROLES) <= set(ROLES)


def test_for_role_strips_write_tools_from_read_only_roles():
    """**核心负控**：即使 spec 声明 `roles=("C",)` 而 `side_effect="write_local"`，
    `for_role("C")` 也**不得**返回它。

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
    """**防误伤**：声明都正确时，`role_filter_notes` 必须是空的。

    否则那条"留痕"机制会因为到处都是噪音而被忽略。
    """
    reg = ToolRegistry(name="t")
    reg.register(_spec("good.read", "read", ROLES))
    reg.register(_spec("good.write", "write_local", ("A", "B", "D")))
    for role in ROLES:
        reg.for_role(role)
    assert reg.role_filter_notes == {}


def test_real_registry_gives_no_write_tool_to_read_only_roles(store):
    """**端到端**：真实装配出来的工具层里，C 与 H 的工具面 **0 个写工具**。"""
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
    """**负控**：任何写工具都必须至少有一个写角色 —— 否则它谁都拿不到（等于死工具）。"""
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
