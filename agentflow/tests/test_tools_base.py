"""工具层基座（`tools/base.py`）与装配器（`tools/__init__.py`）的性质测试。

这些用例锁的是契约，不是实现细节：
- `ToolRegistry.call` 对"调用方写错了"永远返回 `ok=False` 的 `ToolResult`，绝不抛异常
  （这是"不打扰智能体思维链"的核心契约）；
- `validate_params` 必须先看 schema 声明的类型再决定怎么校验
  （历史 bug：把"必须是对象"的检查放在函数开头，于是任何非对象值都被误判）；
- 装配器必须如实报告"哪些模块没装上"，而不是静默少一半工具。
"""

from __future__ import annotations

import sys
import types

import pytest

from agentflow.tools import build_for_role, build_registry
from agentflow.tools.base import (
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
            returns="回显进来的整数",
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
    reg.register(ToolSpec(name="demo.boom", summary="会炸的工具",
                          params={"type": "object", "properties": {}}, handler=boom,
                          returns="（不会返回：handler 抛异常）"))
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
    reg.register(ToolSpec(name="demo.refuse", summary="会拒绝的工具",
                          params={"type": "object", "properties": {}}, handler=refuse,
                          returns="（不会返回：handler 抛 ToolError）"))
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
            summary="返回裸字典",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: {"value": 1},
            returns="{'value'}",
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
        returns="大写后的字符串",
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
        ToolSpec(name="alpha.one", summary="一", params={"type": "object", "properties": {}},
                 handler=lambda: ok(1), roles=("A",), returns="1")
    )
    reg.register(
        ToolSpec(name="beta.two", summary="二", params={"type": "object", "properties": {}},
                 handler=lambda: ok(2), roles=("B",), returns="2")
    )
    assert reg.names() == ["alpha.one", "beta.two"]
    assert [s.name for s in reg.for_role("A")] == ["alpha.one"]
    assert [s["function"]["name"] for s in reg.function_schemas("B")] == ["beta__two"]
    assert "alpha.one" not in reg.text_catalog("B")
    assert "beta.two" in reg.text_catalog()


# ============================================================ ToolSpec


def test_toolspec_rejects_invalid_side_effect():
    """side_effect 是受控词表：非法值必须在构造时就炸，否则审批判断会静默失效。

    判据的顺序是刻意的：`side_effect` 的取值校验排在六件套校验之前。
    否则下面这些"故意写错别的字段"的样本会先以"params 不是 object 根"报错，
    把"side_effect 非法"这条更重要的信息盖掉。
    """
    for bad in ("sideways", "", None, "READ"):
        with pytest.raises(ValueError, match="side_effect"):
            ToolSpec(name="x.y", summary="", params={}, handler=lambda: None, side_effect=bad)


def test_toolspec_needs_approval_tracks_dangerous_side_effects():
    """只有 write_local / network 需要审批；none / read 可以任意调用。"""
    def sp(effect: str) -> ToolSpec:
        return ToolSpec(name="x.y", summary="样本", params={"type": "object", "properties": {}},
                        handler=lambda: None, returns="（样本不返回）", side_effect=effect)

    assert sp("none").needs_approval is False
    assert sp("read").needs_approval is False
    assert sp("write_local").needs_approval is True
    assert sp("network").needs_approval is True


def test_toolspec_name_requires_group_prefix_and_function_schema_replaces_dots():
    """工具名要求"组.动作"；转成 function-calling 时点号要换成 __（部分供应商不接受点号）。"""
    with pytest.raises(ValueError, match="组.动作"):
        ToolSpec(name="nodot", summary="样本", params={"type": "object", "properties": {}},
                 handler=lambda: None, returns="（样本不返回）")


# ============================================================ 第二根轴（external）

def _sample(**over):
    """一个最小的合法 spec；覆盖字段用。"""
    kw = dict(name="sample.one", summary="样本", params={"type": "object", "properties": {}},
              handler=lambda: None, returns="（样本不返回）")
    kw.update(over)
    return ToolSpec(**kw)


def test_toolspec_rejects_invalid_external():
    """`external` 是受控词表：非法值必须在构造时就炸。

    它直接决定"要不要进沙箱、要不要人工签字"，静默接受一个拼错的值
    等于把两根轴的判据一起废掉（与 `side_effect` 同族的理由）。
    """
    for bad in ("network", "EXEC", "", None, "egress "):
        with pytest.raises(ValueError, match="external"):
            _sample(declared_external=bad)


def test_effect_axis_is_derived_from_side_effect_not_a_second_declaration():
    """`effect` 与 `side_effect` 对非遗留取值同值：它是取下来的，不是第二份声明。"""
    for value in ("none", "read", "write_local"):
        spec = _sample(side_effect=value)
        assert spec.effect == value, value
    assert _sample().effect == "none"


def test_legacy_network_is_translated_explicitly_per_tool():
    """遗留取值 `network` 走逐工具翻译表：两根轴上的值都由人写下来。

    实测的两个方向都在这里钉住：`search.download` 会写工作区（`write_local`），
    `ocr.run` 首次构造 Reader 会下模型（同口径）。不许静默重新解释：
    没登记的遗留工具在构造期就被拒。
    """
    from agentflow.tools.base import LEGACY_EFFECTS_BY_TOOL

    assert LEGACY_EFFECTS_BY_TOOL["search.download"] == ("egress", "write_local")
    assert LEGACY_EFFECTS_BY_TOOL["ocr.run"] == ("egress", "write_local")
    assert LEGACY_EFFECTS_BY_TOOL["search.providers"] == ("egress", "read")

    # 负控：遗留工具上"翻译表说 egress、声明说 exec"这种两个说法不许同时存在。
    # （装配期还有一条：声明了 network 却忘了登记原意的工具会让 build_registry
    # 报 `<legacy>` —— 那条由 tests 里的 `test_unregistered_legacy_tool_is_reported_at_assembly` 守。）
    with pytest.raises(ValueError, match="external"):
        _sample(name="sample.conflict", side_effect="network", declared_external="exec")


def test_unregistered_legacy_tool_is_reported_at_assembly(store):
    """装配期可见：新加的遗留工具若忘了登记原意 ⇒ 报告里必须出现它。

    这是"不许静默重新解释"的装配期形态：`effect` 会退回翻译表的默认值，
    而默认值恰好是 `network` 这个取值字面上说过的话（"不改我们的东西"）——
    "它其实会写我们的东西"这个事实会被丢掉，且没有任何地方报错。
    判据走的是 `build_registry` 用的同一个函数（不是测试里重写一遍）。
    """
    from agentflow.tools import LEGACY_EFFECTS_BY_TOOL, untranslated_legacy_tools

    reg = build_registry(store=store, workspace_root=store.root).registry
    assert untranslated_legacy_tools(reg) == [], "真实树上四个遗留工具都登记过原意"

    reg.register(ToolSpec(name="sample.unregistered", summary="遗留样本",
                          params={"type": "object", "properties": {}}, handler=lambda: None,
                          returns="（样本不返回）", side_effect="network"))
    assert untranslated_legacy_tools(reg) == ["sample.unregistered"]
    assert "sample.unregistered" not in LEGACY_EFFECTS_BY_TOOL


def test_real_tree_legacy_tools_translate_to_the_documented_axes(store):
    """真实树上的四个遗留工具，翻译结果必须与 P-13 §4.2/§4.3 逐条一致。"""
    build = build_registry(store=store, workspace_root=store.root)
    expected = {
        "search.providers": ("egress", "read"),
        "search.literature": ("egress", "read"),
        "search.download": ("egress", "write_local"),
        "ocr.run": ("egress", "write_local"),
    }
    for name, (ext, eff) in expected.items():
        spec = build.registry.get(name)
        assert (spec.external, spec.effect) == (ext, eff), name
        # 行为不变：遗留取值继续需要审批（P-13 §5 的审批面表）
        assert spec.needs_approval is True, name
        assert spec.sandbox_required is True, name


def test_needs_approval_and_sandbox_required_are_derived(monkeypatch):
    """两根轴推导审批与沙箱，且沙箱可用性是一个显式三态。

    判据（P-13 §3.3）：
      - 写我们的东西 ⇒ 需要审批（与沙箱无关）；
      - 未声明沙箱时，出网/起进程都需要审批；
      - 沙箱声明可用时，只出网的工具不再需要审批（沙箱承接了它），
        而起进程的工具同样由沙箱承接。
    """
    from agentflow.tools import base as B

    egress = _sample(declared_external="egress")
    runner = _sample(declared_external="exec")
    writer = _sample(side_effect="write_local")
    plain = _sample()

    # 三态之一：未声明（默认）与"声明不可用"同样保守
    for value in (None, False):
        monkeypatch.setattr(B, "SANDBOX_AVAILABLE", value)
        assert egress.needs_approval is True
        assert runner.needs_approval is True
        assert writer.needs_approval is True
        assert plain.needs_approval is False

    # 沙箱声明可用：egress 被沙箱承接 ⇒ 免人工审批；写盘仍要审批
    monkeypatch.setattr(B, "SANDBOX_AVAILABLE", True)
    assert egress.needs_approval is False
    assert runner.needs_approval is False
    assert writer.needs_approval is True
    assert plain.needs_approval is False

    # 沙箱必要性是纯推导、无例外
    assert egress.sandbox_required is True
    assert runner.sandbox_required is True
    assert plain.sandbox_required is False


def test_to_dict_carries_both_axes_so_audit_can_see_them():
    """`to_dict` 看不见的事实等于不存在：两根轴与派生结果都必须在里面。"""
    d = _sample(declared_external="egress").to_dict()
    assert d["external"] == "egress" and d["effect"] == "none"
    assert d["sandbox_required"] is True and d["needs_approval"] is True


def test_six_piece_validation_really_runs_in_post_init():
    """§4.3 第 1 项承诺的"六件套由 `__post_init__` 校验"必须真的接上。

    这是本轮修掉的那处"文档承诺了不存在的门"的证据：每一条都单独触发一次。
    """
    with pytest.raises(ValueError, match="summary"):
        _sample(summary="   ")
    with pytest.raises(ValueError, match="params"):
        _sample(params={})
    with pytest.raises(ValueError, match="params"):
        _sample(params=[])
    with pytest.raises(ValueError, match="returns"):
        _sample(returns=None)

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

    这份清单与 `agentflow.tools._MODULES` 必须逐项一致。新增模块时若只改了
    一边，这里会以"多出/缺少模块"的形式报错 —— 这是我们想要的：让"新模块没接线"
    或"接线了但没被验证"都在装配期暴露，而不是等到某个角色的工具静默少几个。
    """
    assert _assembled.skipped == [], f"有模块被跳过：{_assembled.skipped}"
    from agentflow.tools import _MODULES

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
    import agentflow.tools as tools_pkg

    monkeypatch.setattr(tools_pkg, "_MODULES", ("table_tools", "definitely_missing_module"))
    build = build_registry(store=store, workspace_root=store.root)
    assert [s["module"] for s in build.skipped] == ["definitely_missing_module"]
    assert build.skipped[0]["stage"] == "import"
    assert build.ok is False
    with pytest.raises(ToolError, match="严格模式"):
        build_registry(store=store, workspace_root=store.root, strict=True)


def test_assembly_records_register_exception_without_crashing(store, monkeypatch):
    """某个模块的 register() 抛异常时，装配器记进 skipped 而不是整体崩掉。"""
    import agentflow.tools as tools_pkg

    bogus = types.ModuleType("agentflow.tools.bogus_tools")

    def _register(registry, **kwargs):  # noqa: ARG001
        raise RuntimeError("坏模块故意炸")

    bogus.register = _register  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agentflow.tools.bogus_tools", bogus)
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
    import agentflow.tools as tools_pkg

    empty = types.ModuleType("agentflow.tools.empty_tools")
    empty.register = lambda registry, **kwargs: []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agentflow.tools.empty_tools", empty)
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
