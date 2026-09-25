"""工具层基座（`tools/base.py`）与装配器（`tools/__init__.py`）的性质测试。

这些用例锁的是**契约**，不是实现细节：
- `ToolRegistry.call` 对"调用方写错了"永远返回 `ok=False` 的 `ToolResult`，绝不抛异常
  （这是"不打扰智能体思维链"的核心契约）；
- `validate_params` 必须**先看 schema 声明的类型**再决定怎么校验
  （历史 bug：把"必须是对象"的检查放在函数开头，于是任何非对象值都被误判）；
- 装配器必须如实报告"哪些模块没装上"，而不是静默少一半工具。
"""

from __future__ import annotations

import sys
import types

import pytest

from abflow.tools import build_for_role, build_registry
from abflow.tools.base import (
    ParamError,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    ok,
    spec_from_dataclass_fields,
    tool,
    validate_params,
)

# ============================================================ validate_params


def test_validate_params_object_schema_rejects_non_object():
    """object 根 schema 收到非对象时必须报"必须是对象"，这是唯一该做该判断的地方。"""
    with pytest.raises(ParamError, match="必须是对象"):
        validate_params({"type": "object", "properties": {}}, "不是对象")
    with pytest.raises(ParamError, match="必须是对象"):
        validate_params({"type": "object", "properties": {}}, 123)


def test_validate_params_string_subschema_accepts_string():
    """子 schema 声明为 string 时，传字符串必须通过（锁住"开头就判 object"的老 bug）。"""
    validate_params({"type": "string"}, "群")  # 不得抛异常
    nested = {
        "type": "object",
        "properties": {"q": {"type": "string"}, "n": {"type": "integer"}},
        "required": ["q"],
        "additionalProperties": False,
    }
    validate_params(nested, {"q": "群", "n": 3})  # 子值是标量，不得被当成"必须是对象"
    with pytest.raises(ParamError, match="必须是 string"):
        validate_params(nested, {"q": 3})


def test_validate_params_array_items_dispatch_by_item_schema():
    """array 的 items 子 schema 同样按自己的类型分派（字符串数组不该被当成对象数组）。"""
    schema = {"type": "array", "items": {"type": "string"}, "minItems": 1}
    validate_params(schema, ["0000", "0001"])
    with pytest.raises(ParamError, match="必须是 string"):
        validate_params(schema, ["0000", 1])
    with pytest.raises(ParamError, match="必须是数组"):
        validate_params(schema, "0000")


def test_validate_params_bool_is_not_integer():
    """Python 里 isinstance(True, int) 为真，但 bool 不得当作 integer 通过。"""
    with pytest.raises(ParamError, match="必须是 integer"):
        validate_params({"type": "integer"}, True)
    with pytest.raises(ParamError, match="必须是 integer"):
        validate_params({"type": "integer"}, False)
    validate_params({"type": "integer"}, 1)
    validate_params({"type": "boolean"}, True)
    with pytest.raises(ParamError, match="必须是 boolean"):
        validate_params({"type": "boolean"}, 1)


def test_validate_params_enum_rejects_value_outside_vocabulary():
    """enum 是受控词表：表外的值必须被拒绝，否则状态/类型码会悄悄写歪。"""
    schema = {"type": "string", "enum": ["active", "suspect", "rejected"]}
    validate_params(schema, "active")
    with pytest.raises(ParamError, match="必须是"):
        validate_params(schema, "nope")


def test_validate_params_boundaries_are_inclusive():
    """minimum/maximum 是闭区间：越界拒绝，边界值放行。"""
    schema = {"type": "integer", "minimum": 1, "maximum": 5}
    validate_params(schema, 1)
    validate_params(schema, 5)
    with pytest.raises(ParamError, match="不能小于"):
        validate_params(schema, 0)
    with pytest.raises(ParamError, match="不能大于"):
        validate_params(schema, 6)


def test_validate_params_string_length_bounds():
    """minLength/maxLength 必须真的拦住空串与超长串。"""
    schema = {"type": "string", "minLength": 1, "maxLength": 4}
    validate_params(schema, "abc")
    with pytest.raises(ParamError, match="长度至少"):
        validate_params(schema, "")
    with pytest.raises(ParamError, match="长度最多"):
        validate_params(schema, "abcde")


def test_validate_params_array_item_count_bounds():
    """minItems/maxItems 拦住空数组与超量数组。"""
    schema = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2}
    validate_params(schema, ["a"])
    validate_params(schema, ["a", "b"])
    with pytest.raises(ParamError, match="至少 1 项"):
        validate_params(schema, [])
    with pytest.raises(ParamError, match="最多 2 项"):
        validate_params(schema, ["a", "b", "c"])


def test_validate_params_required_and_additional_properties():
    """required 缺失与未声明参数都必须被拒绝（拼错的参数不能静默无效）。"""
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    validate_params(schema, {"a": "x"})
    with pytest.raises(ParamError, match="缺少必填参数"):
        validate_params(schema, {})
    with pytest.raises(ParamError, match="未声明的参数"):
        validate_params(schema, {"a": "x", "b": 1})


def test_validate_params_without_declared_type_is_unconstrained():
    """未声明 type 的子 schema 不约束取值（"没声明"不等于"必须是某个类型"）。"""
    validate_params({}, "任意")
    validate_params({"description": "无类型"}, 42)


def test_spec_from_dataclass_fields_builds_strict_object_schema():
    """小工具构造的 schema 必须自带 additionalProperties=False（否则拼错参数不会有反馈）。"""
    schema = spec_from_dataclass_fields("t", {"a": "string", "b": "integer"}, required=("a",))
    assert schema["type"] == "object"
    assert schema["required"] == ["a"]
    assert schema["additionalProperties"] is False
    with pytest.raises(ParamError):
        validate_params(schema, {"a": "x", "c": 1})


# ============================================================ ToolRegistry.call


def test_registry_unknown_tool_returns_failed_result_not_exception():
    """工具名写错必须返回 ok=False 的 ToolResult，绝不抛异常打断智能体循环。"""
    reg = ToolRegistry(name="t")
    res = reg.call("no.such.tool")
    assert isinstance(res, ToolResult)
    assert res.ok is False
    assert res.meta.get("kind") == "unknown_tool"
    assert "no.such.tool" in (res.error or "")


def test_registry_param_errors_return_failed_result_not_exception():
    """参数错误同样返回 ok=False（含"多给了参数""少了必填参数""类型不对"三种）。"""
    reg = ToolRegistry(name="t")
    reg.register(
        ToolSpec(
            name="demo.echo",
            summary="回显整数",
            params={
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
                "additionalProperties": False,
            },
            handler=lambda n: ok(n),
        )
    )
    for label, kwargs in (
        ("类型不对", {"n": "不是整数"}),
        ("缺必填", {}),
        ("多给了参数", {"n": 1, "extra": 2}),
    ):
        res = reg.call("demo.echo", **kwargs)
        assert isinstance(res, ToolResult), label
        assert res.ok is False, label
        assert res.meta.get("kind") == "param_error", label
        assert res.error, label
    assert reg.call("demo.echo", n=7).data == 7


def test_registry_wraps_handler_exception_as_unexpected():
    """handler 抛普通异常要被包成 ok=False 且 kind == "unexpected"，而不是向上冒泡。"""

    def boom() -> ToolResult:
        raise RuntimeError("handler 炸了")

    reg = ToolRegistry(name="t")
    reg.register(ToolSpec(name="demo.boom", summary="", params={"type": "object", "properties": {}}, handler=boom))
    res = reg.call("demo.boom")
    assert res.ok is False
    assert res.meta.get("kind") == "unexpected"
    assert "RuntimeError" in (res.error or "")
    assert "handler 炸了" in (res.error or "")


def test_registry_wraps_tool_error_with_tool_error_kind():
    """handler 抛 ToolError 是"工具自己知道的失败"，kind 要与意外异常区分开。"""

    def refuse() -> ToolResult:
        raise ToolError("拒绝：文件不存在")

    reg = ToolRegistry(name="t")
    reg.register(ToolSpec(name="demo.refuse", summary="", params={"type": "object", "properties": {}}, handler=refuse))
    res = reg.call("demo.refuse")
    assert res.ok is False
    assert res.meta.get("kind") == "tool_error"
    assert "文件不存在" in (res.error or "")


def test_registry_wraps_bare_return_value_into_ok():
    """handler 返回裸值时被自动包成 ok(...)，脚本模式与 LLM 模式共用同一份实现。"""
    reg = ToolRegistry(name="t")
    reg.register(
        ToolSpec(
            name="demo.bare",
            summary="",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: {"value": 1},
        )
    )
    res = reg.call("demo.bare")
    assert res.ok is True
    assert res.data == {"value": 1}
    assert res.error is None


def test_registry_tool_decorator_roundtrip_and_duplicate_name():
    """`@tool` 标记的函数能被 register_function 装上；重名注册必须报错而不是静默覆盖。"""

    @tool(
        "demo.decorated",
        "被装饰的工具",
        {"type": "object", "properties": {"v": {"type": "string"}}, "required": ["v"], "additionalProperties": False},
        side_effect="read",
        roles=("C",),
    )
    def decorated(v: str) -> str:
        return v.upper()

    reg = ToolRegistry(name="t")
    spec = reg.register_function(decorated)
    assert spec.name == "demo.decorated"
    assert reg.call("demo.decorated", v="abc").data == "ABC"
    with pytest.raises(ValueError):
        reg.register(spec)
    with pytest.raises(ValueError):
        reg.register_function(lambda: 1)
    with pytest.raises(ToolError):
        reg.get("demo.nope")


def test_registry_text_catalog_and_function_schemas_are_scoped_by_role():
    """目录/function schema 必须按角色过滤，且列出全部工具时不漏。"""
    reg = ToolRegistry(name="t")
    reg.register(
        ToolSpec(name="alpha.one", summary="一", params={"type": "object", "properties": {}}, handler=lambda: ok(1), roles=("A",))
    )
    reg.register(
        ToolSpec(name="beta.two", summary="二", params={"type": "object", "properties": {}}, handler=lambda: ok(2), roles=("B",))
    )
    assert reg.names() == ["alpha.one", "beta.two"]
    assert [s.name for s in reg.for_role("A")] == ["alpha.one"]
    assert [s["function"]["name"] for s in reg.function_schemas("B")] == ["beta__two"]
    assert "alpha.one" not in reg.text_catalog("B")
    assert "beta.two" in reg.text_catalog()


# ============================================================ ToolSpec


def test_toolspec_rejects_invalid_side_effect():
    """side_effect 是受控词表：非法值必须在构造时就炸，否则审批判断会静默失效。"""
    for bad in ("sideways", "", None, "READ"):
        with pytest.raises(ValueError, match="side_effect"):
            ToolSpec(name="x.y", summary="", params={}, handler=lambda: None, side_effect=bad)


def test_toolspec_needs_approval_tracks_dangerous_side_effects():
    """只有 write_local / network 需要审批；none / read 可以任意调用。"""
    def sp(effect: str) -> ToolSpec:
        return ToolSpec(name="x.y", summary="", params={}, handler=lambda: None, side_effect=effect)

    assert sp("none").needs_approval is False
    assert sp("read").needs_approval is False
    assert sp("write_local").needs_approval is True
    assert sp("network").needs_approval is True


def test_toolspec_name_requires_group_prefix_and_function_schema_replaces_dots():
    """工具名要求"组.动作"；转成 function-calling 时点号要换成 __（部分供应商不接受点号）。"""
    with pytest.raises(ValueError, match="组.动作"):
        ToolSpec(name="nodot", summary="", params={}, handler=lambda: None)

    spec = ToolSpec(
        name="table.create",
        summary="建行",
        params={"type": "object", "properties": {}},
        handler=lambda: None,
        returns="新主键",
    )
    fs = spec.to_function_schema()
    assert fs["type"] == "function"
    assert fs["function"]["name"] == "table__create"
    assert "." not in fs["function"]["name"]
    assert "新主键" in fs["function"]["description"]
    assert spec.to_dict()["needs_approval"] is False


# ============================================================ 装配器


@pytest.fixture
def _assembled(store):
    """在临时工作区上装配一次完整工具层（不联网、不调用任何工具）。"""
    return build_registry(store=store, workspace_root=store.root)


def test_assembly_loads_all_modules(_assembled):
    """全部工具模块必须装上、skipped 为空，且工具总数不少于 30。

    ⚠️ 这份清单与 `abflow.tools._MODULES` **必须逐项一致**。新增模块时若只改了
    一边，这里会以"多出/缺少模块"的形式报错 —— 这是我们想要的：让"新模块没接线"
    或"接线了但没被验证"都在**装配期**暴露，而不是等到某个角色的工具静默少几个。
    """
    assert _assembled.skipped == [], f"有模块被跳过：{_assembled.skipped}"
    from abflow.tools import _MODULES

    assert _assembled.loaded == list(_MODULES)
    assert len(_assembled.registry) >= 30
    assert _assembled.ok is True
    assert _assembled.summary()["count"] == len(_assembled.registry)
    # 每个模块都真的贡献了工具，而不是"register 跑通但一个没加"
    for prefix in ("table.", "fs.", "search.", "ocr.", "graph.", "trace.", "research.",
                   "verify.", "attack.", "doc.", "review."):
        assert any(n.startswith(prefix) for n in _assembled.registry.names()), prefix


def test_assembly_is_strict_about_skipped_modules(store, monkeypatch):
    """strict=True 时任何模块被跳过都要抛错，防止"少了一半工具还以为装好了"。"""
    import abflow.tools as tools_pkg

    monkeypatch.setattr(tools_pkg, "_MODULES", ("table_tools", "definitely_missing_module"))
    build = build_registry(store=store, workspace_root=store.root)
    assert [s["module"] for s in build.skipped] == ["definitely_missing_module"]
    assert build.skipped[0]["stage"] == "import"
    assert build.ok is False
    with pytest.raises(ToolError, match="严格模式"):
        build_registry(store=store, workspace_root=store.root, strict=True)


def test_assembly_records_register_exception_without_crashing(store, monkeypatch):
    """某个模块的 register() 抛异常时，装配器记进 skipped 而不是整体崩掉。"""
    import abflow.tools as tools_pkg

    bogus = types.ModuleType("abflow.tools.bogus_tools")

    def _register(registry, **kwargs):  # noqa: ARG001
        raise RuntimeError("坏模块故意炸")

    bogus.register = _register  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "abflow.tools.bogus_tools", bogus)
    monkeypatch.setattr(tools_pkg, "_MODULES", ("table_tools", "bogus_tools"))

    build = build_registry(store=store, workspace_root=store.root)
    rows = {s["module"]: s for s in build.skipped}
    assert "bogus_tools" in rows
    assert rows["bogus_tools"]["stage"] == "register"
    assert "坏模块故意炸" in rows["bogus_tools"]["error"]
    # 其它模块照常装上：一个坏模块不该让整个工具层不可用
    assert "table_tools" in build.loaded
    assert any(n.startswith("table.") for n in build.registry.names())


def test_assembly_records_module_that_registers_nothing(store, monkeypatch):
    """register() 跑通却没加任何工具，几乎总是 bug —— 必须被记为 skipped。"""
    import abflow.tools as tools_pkg

    empty = types.ModuleType("abflow.tools.empty_tools")
    empty.register = lambda registry, **kwargs: []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "abflow.tools.empty_tools", empty)
    monkeypatch.setattr(tools_pkg, "_MODULES", ("empty_tools",))

    build = build_registry(store=store, workspace_root=store.root)
    assert build.skipped[0]["module"] == "empty_tools"
    assert "未注册任何工具" in build.skipped[0]["error"]


def test_role_surface_A_has_search_but_no_research(store):
    """A 的权限面：有检索（search.*），但拿不到 D 的研究决策工具（research.*）。"""
    reg = build_for_role("A", store=store, workspace_root=store.root).registry
    names = reg.names()
    assert any(n.startswith("search.") for n in names)
    assert not any(n.startswith("research.") for n in names)
    assert not any(n.startswith("ocr.") for n in names)
    assert not any(n.startswith(("graph.", "trace.")) for n in names)


def test_role_surface_B_has_ocr_but_no_search(store):
    """B 的权限面：有 OCR（ocr.*），但拿不到下载/检索（那是 A 的网络副作用）。"""
    reg = build_for_role("B", store=store, workspace_root=store.root).registry
    names = reg.names()
    assert any(n.startswith("ocr.") for n in names)
    assert not any(n.startswith("search.") for n in names)
    assert not any(n.startswith(("graph.", "trace.", "research.")) for n in names)


def test_role_surface_C_and_D_analysis_tools_are_pure_reads(store):
    """C/D 的分析与溯源工具全部 side_effect=read —— C 必须能任意组合反复查询而不写盘、不审批。"""
    build = build_registry(store=store, workspace_root=store.root)
    for role in ("C", "D"):
        own = [
            s
            for s in build.registry.for_role(role)
            if s.name.startswith(("graph.", "trace."))
        ]
        assert own, f"{role} 没有任何 graph./trace. 工具"
        for spec in own:
            assert spec.side_effect == "read", f"{spec.name} 不是纯读"
            assert spec.needs_approval is False, f"{spec.name} 不该需要审批"


def test_research_tools_declare_their_write_side_effects_honestly(store):
    """D 的 research.* 里"会写盘的"必须如实声明 write_local（§1.1：write_local / network）。

    与上一条并不矛盾：`graph.*` / `trace.*` 是纯读（C 的分析要能任意反复查询），
    而 `research.submit_gap` / `write_note` / `set_status` 确实要落盘，不能假装只读。
    """
    build = build_registry(store=store, workspace_root=store.root)
    reads = {"research.list_gaps", "research.poll_waiting"}
    writes = {"research.submit_gap", "research.write_note", "research.set_status"}
    for name in reads | writes:
        spec = build.registry.get(name)
        expected = "read" if name in reads else "write_local"
        assert spec.side_effect == expected, f"{name} 的副作用声明应为 {expected}"
    assert build.registry.get("research.submit_gap").needs_approval is True
    assert build.registry.get("research.list_gaps").needs_approval is False


def test_research_tools_are_reachable_through_the_D_role_filter(store):
    """DESIGN-TOOLS §1.1 把 research.* 的角色写作 D；`build_for_role("D")` 必须能拿到它们。

    （当前实现把角色写成 `"agent-D"`，而装配器的 `ROLES` 是 `"D"`，于是按角色过滤时
    这些工具会凭空消失 —— `for_role("D")` 拿不到 D 自己的工具。）
    """
    reg = build_for_role("D", store=store, workspace_root=store.root).registry
    names = set(reg.names())
    missing = {"research.submit_gap", "research.list_gaps", "research.write_note"} - names
    assert not missing, f"for_role('D') 拿不到这些 D 专属工具：{sorted(missing)}"
