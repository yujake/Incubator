"""参数接缝 + 导入期交叉断言：能力层与工具层各一条判据（`D-2` / `R2-AN-1` / `N-5`）。

## 这两条判据要抓的是什么
`ActionSpec.params`（能力层声明）与 `Agent<X>.<handler_name>` 的真形参是两件事；`ToolSpec.params`（工具层 schema）
与 `ToolSpec.handler` 的真形参也是两件事。声明里多一个实现收不下的 property，后果是一段静默的错位：① 参数门放行（它读的正是那份声明）⇒ 写一行 `running`；②
执行到handler 时才报"不认这些参数" ⇒ 台账里那一行看起来像"跑失败了"，而这次调用其实从来没被执行过（工具层那半还会被兜成 `kind='unexpected'`，一个"库内部出错"的假 bug 分类）。
所以每层各有一条机器判据：每一层都必须做到"声明的每个 property，要么被实现接受，要么逐条登记进这一层的接缝表并写明理由"——不许留下第三态。
## 落点为什么是"显式审计 / 注册期"而不是"跑一次测试"
判据的价值取决于它会不会被忘记跑。工具层挂在 `ToolRegistry.register`（`tools/base.py`，与既有的 `roles ⊆ schema.ROLES` 判据同一个入口与同一个理由）；
能力层原先挂在导入期，2026-10-27 业主批改成显式（`capabilities.run_capability_audit()`）——
导入期那趟实测给每条 CLI 命令加 1.2 秒，且任何一格登记过期都会让所有命令 exit 1。
摘出来之后，"不会忘记跑"由两处承担：`scripts/release_check.py` 的 imports 项与
`tests/test_capabilities_audit_is_explicit.py`。本文件的用例是这两条判据的读数与自校，
不是它们的存在形式。
## 三条自校（守判据自己，不是守被测对象）
- `test_injected_property_is_reported_and_removing_the_seam_reports_sleep`：在内存里（不动盘上一个字节）注入一个假 property、
再把 `sleep` 那条接缝拿掉 ⇒ 判据必须报出对应的名字；- `test_tools_side_seam_is_the_only_way_through`：同一个坏 spec，没登记时 `register`
必须抛 `ParamError`，登记后必须放行 —— 证明接缝表是唯一的放行路径，而不是"判据其实恒真"；
- `test_capabilities_assertion_still_returns_none`：`assert_capabilities()`
的返回值被一条既有用例（`tests/test_r4_roles_surface.py`）钉住必须是 `None`，覆盖计数走模块级 `PARAM_ASSERT_COVERAGE`；这里把这条契约钉在本窗口的测试里，
免得下一个人"顺手"把它改成返回值。
与既有测试的分工：工具 schema ↔ handler 那条判据另有一份测试面实现（`tests/test_schema_handler_params.py`，它带自己的注入负控）；本文件不重复它，
只在工具侧核"新那条注册期判据"这件事，以及那条判据的覆盖率读数。"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from agentflow import capabilities as C
from agentflow.tools import build_registry
from agentflow.tools import base as B
from agentflow.tools.base import ToolRegistry

#: 注入用的假 property 名。刻意选一个不可能与真实参数撞名的长名字。
FAKE_PROPERTY = "definitely_not_a_handled_param"

#: 接缝表在真实树上的唯一内容（`D-2` 的落点）。集合写死是有意的：
#: 接缝变多意味着"又有一格声明的参数没有实现接住"，那是要人看一眼的事。
EXPECTED_SEAMS = {("E", "run_experiment", "sleep")}


def _properties(spec) -> set[str]:
    return set((spec.params.get("properties") or {}))


# ============================================================ 能力层：正控

def test_capability_audit_covers_every_declared_property():
    """正控：显式跑一趟审计，它真的走遍了能力表的全部 property，且零违反。

    "零违反"必须与"走遍了"一起报：判据解析出空集时无条件通过，是本项目
    P16 的通用形态（空集永远是子集）。

    2026-10-27：审计不再挂在导入期（`run_capability_audit` 是唯一入口），所以这里
    第一件事就是显式跑一趟 —— 判据要守的东西一个字没变，变的是"谁触发它"。
    """
    C.run_capability_audit(print_readings=False)
    cov = C.param_assert_coverage()
    assert cov["declared"] >= 100, f"能力表里只数出 {cov['declared']} 个 property ⇒ 扫描器没接上"
    assert cov["checked"] == cov["declared"], (
        f"参数交叉断言只覆盖了 {cov['checked']} / {cov['declared']} 个 property ⇒ "
        "判据漏看了声明，'零违反'此时不构成证据"
    )
    assert cov["actions"] == sum(len(v) for v in C.CAPABILITIES.values())
    # 模块级读数与就地算出来的必须一致（上一趟审计写过一次）
    assert C.PARAM_ASSERT_COVERAGE == cov, (
        "模块级 PARAM_ASSERT_COVERAGE 与就地复算不一致 ⇒ 上一趟审计写的读数不是这份表"
    )
    assert C.param_seam_violations() == []
    assert C.stale_param_seams() == []
    assert set(C.PARAM_SEAMS) == EXPECTED_SEAMS, (
        f"接缝表变了：{sorted(C.PARAM_SEAMS)}。多出来的每一条都意味着"
        f"『声明了而实现不收』的参数又多了一个，请确认那是刻意的（并写明理由）"
    )
    for key, why in C.PARAM_SEAMS.items():
        assert len(why.strip()) >= 40, f"接缝 {key} 的理由串太短，等于没写：{why!r}"


def test_sleep_stays_declared_and_stays_seamed():
    """反 B 选项：不许为了让断言变绿而删掉 `sleep` 声明。

    删了它，替身夹具就无法按同一份 schema 传参
    （`tests/test_conductor.py` / `tests/test_scheduler.py` 靠 `sleep=` 控制时序），
    被测的就不再是那条真实链路。
    """
    spec = C.find_action("E", "run_experiment")
    assert spec is not None
    assert "sleep" in _properties(spec), "能力表的 E.run_experiment 不再声明 sleep ⇒ 替身夹具那条路断了"
    assert ("E", "run_experiment", "sleep") in C.PARAM_SEAMS, "sleep 的接缝登记被删了"


def test_real_handler_has_no_sleep_and_no_var_keyword():
    """反 C 选项：不许给真实现补一个没人读的 `sleep`（或让它收 VAR_KEYWORD）。

    具名 `sleep` 是没人读的假承诺；收 VAR_KEYWORD 会把"我传了但它没看"
    变成静默成功（`conductor.LocalBackend.call` 的 docstring 逐字拒绝这个形态）。
    """
    sig = inspect.signature(C._agent_class("E").run_experiment)
    assert "sleep" not in sig.parameters, "AgentE.run_experiment 多了一个 sleep 形参"
    assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()), (
        "AgentE.run_experiment 开始收 VAR_KEYWORD ⇒ 任何多传的参数都会被静默吞掉"
    )


def test_the_avoid_name_family_is_gone_from_the_declarations():
    """同族（`name` / `checker_name` / `run_name`）：2026-10-23 晚之后一个都不剩。

    这三个名字来自两个不同的坑：`name` 是"能力表与方法层都正确、而工具层会撞名"
    的那一个（`ToolRegistry.call` 的第一个形参就叫 `name`）；`checker_name` /
    `run_name` 是工具层的避撞名。它们此前只由 `tools/verify_tools.py` 的一段自然语言
    登记着，后来各自的层都有了机器判据。

    裁定把 E 的 Lean 侧整条摘掉之后，这一族的宿主（`E.check_formal` 与它的工具、
    `E.run_experiment` 的两个 formal 参数）全都没了：
    - 能力表里不许再出现这三个名字（出现就意味着方法层得收它）；
    - `E.check_formal` 这条动作不存在了（`find_action` 返回 None）；
    - 工具层剩下的那个避撞名是 `formal.check_formal` 的 `declaration_name`
      （L 的动作名，由 `test_tools_side_names_of_the_same_family_are_accepted_by_their_handlers` 守着）。

    这一条比原来更硬：原来守的是"这三个名字每一处都落在接受或登记上"，
    现在守的是"它们不在任何一处"。
    """
    assert C.find_action("E", "check_formal") is None, (
        "E 的动作表里还有 check_formal ⇒ 这一族又回来了")
    for role, specs in C.CAPABILITIES.items():
        for spec in specs:
            for banned in ("name", "checker_name", "run_name"):
                assert banned not in _properties(spec), (
                    f"{role}.{spec.action} 声明了撞名族里的 {banned!r}")


def test_gate_params_is_the_declaration_intersected_with_the_implementation():
    """参数门的口径：声明 ∩ 实现签名（`D-2` 第 3 条）。

    `gate_params` 是导出的那个公开口径函数（`conductor.py` 本窗口禁改，
    改它的时候只需要把 `_check_params` 换成调 `C.check_params(spec, params)`）。
    """
    spec = C.find_action("E", "run_experiment")
    assert spec is not None
    gate = C.gate_params(spec)
    assert "sleep" not in (gate.get("properties") or {}), "接缝参数必须落在交集之外"
    assert set(gate["properties"]) == _properties(spec) - {"sleep"}
    assert gate["additionalProperties"] is False
    assert set(gate["required"]) == set(spec.params["required"]), (
        "必填项不许被交集过滤掉 —— 那会把『必须给』读成『可以不给』"
    )
    # 口径真的会拦下接缝参数（不是"过滤完就没人看"）
    ok_params = {"claim": "c", "claim_key": "k", "script_path": "s.py"}
    assert C.check_params(spec, ok_params) is None
    bad = C.check_params(spec, {**ok_params, "sleep": 0.1})
    assert bad is not None and "sleep" in bad, f"接缝参数没被拦下：{bad!r}"
    # 实现侧独有的参数同样进不来（交集是双向的）
    #
    # `T0-13`（2026-09-29）把 `imports` / `name` 补进了声明（那时它们是 formal 路径的
    # 参数）。2026-10-23 晚裁定把它们一起撤了：E 不做形式化 ⇒ 那两个参数不在动作面上，
    # 也不在工具 schema 上。所以这里从"它们必须能过闸门"翻成"它们必须被闸门拒"——
    # 判据的规则一个字没改（未声明的参数一律进不来），改的是"什么算未声明"这个事实。
    assert C.check_params(spec, {**ok_params, "nope": 1}) is not None
    assert C.check_params(spec, {**ok_params, "name": "a_theorem", "imports": []}) is not None, (
        "E 不做形式化之后 name / imports 不再声明 ⇒ 闸门必须拒收它们"
    )


def test_injected_property_is_reported_and_removing_the_seam_reports_sleep():
    """判据自己的负控（内存注入，盘上一个字节都不动）。

    两个方向都要红：① 凭空多一个未登记的 property；② 把 `sleep` 那条接缝拿掉。
    再加一条撤掉注入后必须零违反 —— 证明前面的红来自注入，不是判据恒红。
    """
    spec = C.find_action("C", "hottest")
    assert spec is not None
    props = dict(spec.params["properties"])
    props[FAKE_PROPERTY] = {"type": "string"}
    poisoned = dataclasses.replace(
        spec, params={**spec.params, "properties": props}
    )
    fake_table = dict(C.CAPABILITIES)
    fake_table["C"] = tuple(poisoned if s.action == "hottest" else s for s in C.CAPABILITIES["C"])

    armed = C.param_seam_violations(capabilities=fake_table)
    assert armed == [("C", "hottest", [FAKE_PROPERTY])], f"注入的假 property 没被报出来：{armed}"
    # 自校：注入真的生效了吗（不然负控会假绿）
    assert FAKE_PROPERTY in _properties(next(s for s in fake_table["C"] if s.action == "hottest"))
    # 撤掉注入 ⇒ 零违反（证明上面那条红来自注入本身）
    assert C.param_seam_violations() == []

    # 方向二：接缝表被清空 ⇒ sleep 必须作为违反被报出来
    stripped = C.param_seam_violations(seams={})
    assert stripped == [("E", "run_experiment", ["sleep"])], (
        f"删掉 sleep 那条接缝后判据没报出来：{stripped}"
    )
    assert C.stale_param_seams(seams={}) == []
    # 方向三：登记一条已经不需要的接缝 ⇒ stale 必须报出来
    assert C.stale_param_seams(seams={("E", "check_formal", "claim"): "假装需要"}) == [
        ("E", "check_formal", "claim")
    ]


def test_capabilities_assertion_still_returns_none():
    """契约：`assert_capabilities()` 仍然只返回 `None`（覆盖计数走模块级字典）。

    `tests/test_r4_roles_surface.py` 逐字断言 `assert C.assert_capabilities() is None`
    （默认档不许对 warning 级炸）。那条用例不在本窗口的授权改动范围内，
    所以这条契约在这里被钉住：换成"返回计数"会让它变红。
    """
    assert C.assert_capabilities() is None
    assert C.PARAM_ASSERT_COVERAGE["checked"] == C.PARAM_ASSERT_COVERAGE["declared"]


# ============================================================ 工具层：正控

def test_tools_side_assertion_is_wired_and_covers_every_registered_tool(store):
    """正控：装配期那条判据真的走遍了注册表（覆盖率 = 注册工具数），且零违反。"""
    build = build_registry(store=store, workspace_root=store.root)
    assert len(build.registry) >= 50, f"只装出 {len(build.registry)} 个工具 ⇒ 判据没接上工具层"
    assert build.params_checked == len(build.registry), (
        f"参数面判据只走过 {build.params_checked} 个工具，而注册表里有 "
        f"{len(build.registry)} 个 ⇒ 覆盖率读数与注册表脱节"
    )
    assert build.skipped == []
    assert B.PARAM_SEAMS == {}, (
        f"工具侧的接缝表不是空的：{B.PARAM_SEAMS} —— 真实树上工具 schema 与 handler "
        "本来就一致（`tests/test_schema_handler_params.py` 的正控是同一条读数）。"
        "往里加条目会让 falsifiable 的那一格变成'登记了就算过'"
    )
    for name in build.registry.names():
        assert B.tool_param_seam_violations(build.registry.get(name)) == [], (
            f"{name} 的 schema 声明了 handler 收不下的参数"
        )
    assert B.stale_tool_param_seams(build.registry._specs) == []
    assert build.summary()["params_checked"] == len(build.registry)


def test_tools_side_names_of_the_same_family_are_accepted_by_their_handlers(store):
    """同族的工具层半边：`declaration_name` 真的被它的 handler 接受。

    2026-10-23 晚之后这一族只剩 `formal.check_formal` 那一格（L 的 `declaration_name`；
    `verify.check_formal` 的 `checker_name` 与 `verify.run_experiment` 的 `run_name`
    随 E 的 formal 面一起退场）。这一件的 handler 是"转发给 AgentL"的 `**kw` 形态
    （`_formal_check_formal(_store, _root, **kw)`）⇒ "逐形参对齐"那一半在这里是 N/A，
    如实写下来而不是假装它还管得着；能判的是三件：声明里有它、注册期接缝判据为零违反、
    以及 handler 确实是 `**kw` 形态（它一变，这一条就该改回更强的逐形参对齐）。
    """
    reg = build_registry(store=store, workspace_root=store.root).registry
    for tool, prop in (("formal.check_formal", "declaration_name"),):
        spec = reg.get(tool)
        assert prop in _properties(spec), f"{tool} 的 schema 里没有 {prop}"
        assert B.tool_param_seam_violations(spec) == []
        sig = inspect.signature(spec.handler)
        assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()), (
            f"{tool} 的 handler 变成显式列形参了 ⇒ 这一条应当改回逐形参对齐（那是更强的判据）"
        )


# ============================================================ 工具层：负控与自校

def test_tools_side_seam_is_the_only_way_through(store, monkeypatch):
    """负控 + 牙口：坏 spec 没登记就注册不进去，登记后必须放行。

    两个方向合起来才证明"接缝表是唯一的放行路径"：只有前者时，判据可能是恒真的；
    只有后者时，`register` 可能根本没核。
    """
    reg = build_registry(store=store, workspace_root=store.root).registry
    original = reg.get("verify.run_experiment")
    props = dict(original.params["properties"])
    props[FAKE_PROPERTY] = {"type": "string"}
    poisoned = dataclasses.replace(original, params={**original.params, "properties": props})
    # 自校：注入真的生效了吗
    assert FAKE_PROPERTY in _properties(poisoned)

    with pytest.raises(B.ParamError) as exc:
        ToolRegistry().register(poisoned)
    assert FAKE_PROPERTY in str(exc.value), f"报错里没点名那个参数：{exc.value}"
    assert poisoned.name in str(exc.value)

    # 登记那条接缝之后，同一个 spec 必须放行 —— 接缝表是唯一的放行路径
    monkeypatch.setitem(
        B.PARAM_SEAMS, poisoned.name, {FAKE_PROPERTY: "测试注入：证明接缝表是唯一放行路径"}
    )
    fresh = ToolRegistry()
    fresh.register(poisoned)
    assert fresh.get(poisoned.name) is poisoned
    # 撤掉注入 ⇒ 判据重新报违反（同一个 spec，红来自接缝表而不是别处）
    monkeypatch.delitem(B.PARAM_SEAMS, poisoned.name)
    assert B.tool_param_seam_violations(poisoned) == [FAKE_PROPERTY]


def test_public_entry_check_param_seams_is_directly_exercised(store, monkeypatch):
    """公开入口 `B.check_param_seams` 的直接测试（发布门 `coverage` 档要求的那一格）。

    为什么单列一条：`tools/coverage_zero_test.py` 的 `coverage` 档会判"公开函数零直接测试"，
    而这个函数名字含决策词缀（`check`）⇒ 风险等级 ≤2 ⇒ 没有直接测试就会让 `release_all`
    的 `coverage` 档红（本条就是对那次红的处置，不是"为了凑覆盖率"）。
    正控：合规 spec 不抛；负控：声明了 handler 收不下的 property ⇒ 抛 `ParamError` 且逐字点名；
    再补一档"登记进接缝表之后放行"——证明它读的正是与 `register` 期同一个 `PARAM_SEAMS`。
    """
    reg = build_registry(store=store, workspace_root=store.root).registry
    ok = reg.get("verify.run_experiment")
    B.check_param_seams(ok)  # 正控：合规 spec 不抛

    props = dict(ok.params["properties"])
    props[FAKE_PROPERTY] = {"type": "string"}
    poisoned = dataclasses.replace(ok, params={**ok.params, "properties": props})
    assert FAKE_PROPERTY in _properties(poisoned), "自校：注入没有真的落到 params 上"

    with pytest.raises(B.ParamError) as exc:
        B.check_param_seams(poisoned)
    msg = str(exc.value)
    assert FAKE_PROPERTY in msg and poisoned.name in msg, f"报错没逐字点名：{msg}"

    monkeypatch.setitem(
        B.PARAM_SEAMS, poisoned.name, {FAKE_PROPERTY: "测试：证明公开入口读的就是 PARAM_SEAMS"}
    )
    B.check_param_seams(poisoned)  # 登记后必须放行
    monkeypatch.delitem(B.PARAM_SEAMS, poisoned.name)
    with pytest.raises(B.ParamError):
        B.check_param_seams(poisoned)  # 撤回登记 ⇒ 必须重新抛（红来自接缝表，不是别处）


def test_tools_side_seam_table_shape_is_checked_at_import_time():
    """接缝表的形态判据（`tools/__init__.py` 的导入期那一条）有牙。"""
    from agentflow import tools as T

    good = {"verify.run_experiment": {"sleep": "测试"}}
    T._check_param_seams_are_registered(seams=good, groups=T._TOOL_GROUP_PREFIXES)  # 不抛

    with pytest.raises(AssertionError) as typo:
        T._check_param_seams_are_registered(seams={"verfy.run_experiment": {"x": "y"}},
                                           groups=T._TOOL_GROUP_PREFIXES)
    assert "组前缀" in str(typo.value)

    with pytest.raises(AssertionError) as noshape:
        T._check_param_seams_are_registered(seams={"run_experiment": {"x": "y"}},
                                           groups=T._TOOL_GROUP_PREFIXES)
    assert "组.动作" in str(noshape.value)

    with pytest.raises(AssertionError) as noreason:
        T._check_param_seams_are_registered(seams={"verify.run_experiment": {"sleep": "   "}},
                                           groups=T._TOOL_GROUP_PREFIXES)
    assert "理由串" in str(noreason.value)

    assert T.PARAM_SEAMS is B.PARAM_SEAMS, "顶层再导出的必须是同一个对象，不是第二份字面量"
