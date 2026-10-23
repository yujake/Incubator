"""通用判据：工具 schema 声明的每个 property，必须被 spec.handler 的签名接受。
## 这条判据要抓的是什么（R2-AN-1 / R2b-AN-1-A）
`ToolRegistry.call` 的两步是：
1. `validate_params(spec.params, merged)` —— 按 schema 判参数合法性；2. `spec.handler(**merged)` —— 按关键字把参数交给 handler。
只要 schema 声明了一个 handler 形参表里没有的 property，两步就分家了：第 1 步放行（schema 说它是合法参数），第 2 步抛 `TypeError`，而`tools/base.py` 的兜底把它记成
`ok=False / kind='unexpected'`。`unexpected` 是"库内部出错"那一类，于是调用方拿着 schema 的声明写参数，拿回来一个会让人去查工具注册表的分类 —— 这正是
`R2b-AN-1-A` 实测的假 bug 分类，落点是 `verify.check_formal` 与 `verify.run_experiment` 两处schema 里的旧名 `name`（两个 handler 都不收它）。
2026-10-24：`verify.check_formal` 已随 E 的 Lean 侧清场整条删除（E 的动作 5→4、工具 98→97），
今天这一族量的是 `formal.check_formal`（L 的入口）与 `verify.run_experiment`；通用判据一个字没改，
只有下面那条"旧名不许回来"的专项判据换了载体。
## 为什么判据是"逐条看每个工具"，而不是"盯住那两个名字"
盯名字只能抓住已经被发现的这一处；这条判据抓的是整类形态：任何工具在任何时候多声明一个 handler 收不下的 property，它都会红（`R2-AN-1` 的原始要求，`draft/28` 42.3 已实测"可行、零误伤"）。
所以这里不写任何工具名，只遍历注册表。
## 跳过 `**kwargs` 的 handler
有一批 handler 收 `**kwargs`（`analysis.register_report` / `doc` 的两件 / L 的三件 `formal.*` /
`review` 的四件；判据按 `_accepts_kwargs` 现读，不写死名单 —— 写死的名单会随装配面漂）。
对它们来说，schema 多声明一个 property 不会变成
`kind='unexpected'`（那个键真的进得了 handler），所以它对这条缺陷不适用，判据跳过它。跳过是"按定义不适用"，不是"给它开例外"：这些工具的真实参数契约由它们自己的 schema 与返回声明承担，
本条判据不假装管得着。正因为跳过是按定义发生的，"旧名不许回来"那一条才必须单独存在
（`formal.check_formal` 的 handler 正是 `**kwargs` 适配器，通用判据看不见它）。
## 三条自校（守判据自己，不是守被测对象）
- `armed()`：把一个假 property 真注入注册表 ⇒ 判据必须报出它，且报出的差集恰好只含这个假名字（证明判据不是恒真，也不是恒窄）；- `disarmed()`：同一处注入撤掉 ⇒ 判据必须零违反（证明
`armed()` 的红来自注入本身，不是判据写坏了）；- 正控：`test_every_registered_tool_schema_property_is_accepted_by_its_handler`对整个注册表跑同一条判据
—— 违反数必须为 0。
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools.base import ToolRegistry

#: 注入用的假 property 名。刻意选一个不可能与真实参数撞名的长名字。
FAKE_PROPERTY = "definitely_not_a_handler_param"


def _accepts_kwargs(handler) -> bool:
    """handler 是否收 `**kwargs`（收的话本条判据按定义不适用）。"""
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        for p in inspect.signature(handler).parameters.values()
    )


def _declared_properties(spec) -> set[str]:
    """从 schema 里读出声明的 property 名（不手抄任何工具的参数表）。"""
    props = spec.params.get("properties") or {}
    assert isinstance(props, dict), f"{spec.name} 的 schema properties 不是对象：{props!r}"
    return set(props)


def schema_property_violations(registry: ToolRegistry) -> list[tuple[str, list[str]]]:
    """遍历注册表 ⇒ `[(工具名, schema 声明而 handler 不收的参数名)]`，按名排序。

    唯一的豁免是承 `**kwargs` 的 handler（见模块 docstring）。
    """
    out: list[tuple[str, list[str]]] = []
    for name in registry.names():
        spec = registry.get(name)
        if spec is None:  # pragma: no cover - names() 与 get() 同源，这里只是防御
            continue
        if _accepts_kwargs(spec.handler):
            continue
        accepted = set(inspect.signature(spec.handler).parameters)
        diff = sorted(_declared_properties(spec) - accepted)
        if diff:
            out.append((name, diff))
    return out


def _registry(store: Store) -> ToolRegistry:
    return build_registry(store=store, workspace_root=store.root).registry


# ============================================================ 正控：真注册表零违反


def test_every_registered_tool_schema_property_is_accepted_by_its_handler(
    store: Store,
):
    """正控：真注册表上违反数必须为 0（这条判据就是 `R2-AN-1` 要的那一条）。

    判据接上了没有也要有证据：先断言这次真的遍历到了工具（否则"零违反"
    与"没扫到任何东西"在输出里长得一模一样 —— 本项目的 P16 形态）。
    """
    reg = _registry(store)
    assert len(reg.names()) >= 50, (
        f"只遍历到 {len(reg.names())} 个工具 ⇒ 判据没接上注册表，"
        f"'零违反'此时不构成证据"
    )
    assert schema_property_violations(reg) == []


#: 这条判据量的是"声明名的入口"：schema 里必须没有旧名 `name`（`R2b-AN-1-A` 那一处
#: 假 bug 分类的根），而"今天的入口叫什么"逐件列在这里 —— 这张表本身就是覆盖面，
#: 删一格等于少看一件工具。
#:
#: 2026-10-24：`verify.check_formal` 与 E 的 `check_formal` 已随 E 的 Lean 侧清场删除
#: （E 的动作 5→4、工具 98→97），形式化的工具面现在是 L 的 `formal.formalize` /
#: `formal.check_formal` / `formal.record`。这里跟上真身 —— 改的动机：判据守的纪律
#: 一个字没变（"schema 声明的名字必须是 handler 真收的名字，避撞翻译层留下的旧名不许
#: 回来"），换的只是被指的那一件：`verify.check_formal` -> `formal.check_formal`。
#:
#: 为什么 `verify.run_experiment` 那一格是 `None`：它的声明名入口 `run_name`（连同
#: `imports`）已随 `method='formal'` 在 2026-10-23 晚退场（见 `tools/verify_tools.py`
#: 里 `_verify_run_experiment` 的注释）。E 现在不做形式化，这条工具上不再有"声明名"
#: 这个入口 —— 剩下的纪律只有"那几个名字一个都不许回来"。
_DECLARATION_NAME_ENTRY: dict[str, str | None] = {
    "formal.check_formal": "declaration_name",
    "verify.run_experiment": None,
}

#: `verify.run_experiment` 那一格上"一个都不许回来"的名字。
_RETIRED_DECLARATION_KEYS: frozenset[str] = frozenset(
    {"name", "run_name", "checker_name", "declaration_name"})

#: 反真空用的三件：L 的形式化入口。它们不在注册表里时，上面那几格量的是空气
#: （要么 `reg.get` 直接抛，要么"没有旧名"在 0 个 property 上恒真）。
_FORMAL_ENTRY_TOOLS: tuple[str, ...] = (
    "formal.formalize", "formal.check_formal", "formal.record")


def test_verify_formal_schemas_do_not_declare_the_old_name_property(store: Store):
    """旧名 `name` 不许回来（`R2b-AN-1-A` 的父代理裁定：删掉，不接受登记为残余）。

    这一条与上面的通用判据是两件事：通用判据抓"schema 与 handler 分家"，
    这一条抓"有人把 `name` 又加回 schema" —— 那会同时让通用判据变红
    （handler 不收它），但那时通用判据的报错是"`formal.check_formal` 的
    schema 声明了 handler 收不下的参数"，读的人还需要知道为什么不能
    顺手把它加回去。理由写在这里，免得下一个人"为兼容旧调用方"补回来。
    """
    reg = _registry(store)
    names = set(reg.names())
    missing = sorted(t for t in _FORMAL_ENTRY_TOOLS if t not in names)
    assert not missing, (
        f"L 的形式化入口不在注册表里：缺 {missing} —— 这一条守的是「形式化那几件的"
        " schema 里没有旧名 name」，入口本身不见了就量不到东西（判据套件跑在 Lean"
        " 开着那一档，见 `tests/conftest.py` 的 `AGENTFLOW_LEAN_ENABLED`）")
    for tool, entry in sorted(_DECLARATION_NAME_ENTRY.items()):
        props = _declared_properties(reg.get(tool))
        assert props, f"{tool} 的 schema 里一个 property 都没有 ⇒ 这一格量的是空气"
        assert "name" not in props, (
            f"{tool} 的 schema 又声明了旧名 name：它会经 validate_params 放行、"
            f"再让 handler 抛 TypeError 被兜成 kind='unexpected'（假 bug 分类）"
        )
        if entry is None:
            back = sorted(props & _RETIRED_DECLARATION_KEYS)
            assert not back, (
                f"{tool} 的 schema 里又出现了声明名入口 {back}：`run_name` / `imports`"
                " 是随 `method='formal'` 在 2026-10-23 晚退场的，E 不做形式化之后这条"
                "工具上不该再有「声明名」这个入口 —— 它回来了，就是形式化那一路又从 E"
                " 的实验工具上长了回来")
        else:
            assert entry in props, (
                f"{tool} 的 schema 里没有声明名入口 {entry!r} ⇒ 声明名的入口没了："
                f"{sorted(props)}")


# ============================================================ 判据自己的负控与自校


def test_criterion_negative_control_fake_property_must_be_reported(store: Store):
    """负控：内存里注入一个假 property ⇒ 判据必须报出它，撤掉后必须零违反。

    注入点选在注册表自身（`dataclasses.replace` 造一份多一个 property 的
    spec、换进 `_specs`），跑完立刻还原 —— 盘上的 schema 一个字节都不动。
    `disarmed()` 那半是关键：它证明"红"来自注入那一行，而不是判据恒红。
    """
    reg = _registry(store)
    name = "verify.run_experiment"
    # 2026-10-24：`verify.check_formal` 与 E 的 `check_formal` 已随 E 的 Lean 侧清场删除
    # （E 的动作 5→4、工具 98→97），这里跟上真身 —— 改的动机：判据守的纪律没变（往
    # schema 里注入一个 handler 收不下的 property，通用判据必须报出来），换的只是被指
    # 的那一件。为什么注入点不是 `formal.check_formal`（它在功能上才是 `verify.check_formal`
    # 的继任者）：它的 handler 是 `(**kw) -> Any` 适配器，而通用判据按定义跳过这一族
    # （见模块 docstring），注入进去恒不报 —— 拿它当注入点会让这条负控永远假绿。
    # `verify.run_experiment` 是 `R2b-AN-1-A` 那两处里 handler 形参明确的那一件，
    # 也是 E 手上仍然留着的那一件。
    original = reg.get(name)
    assert not _accepts_kwargs(original.handler), (
        f"{name} 的 handler 改成收 **kwargs 了 ⇒ 这一格按定义不适用，负控必须换到"
        "另一件 handler 不收 **kwargs 的工具上（否则注入恒不报、负控变成假绿）")
    assert _declared_properties(original) == {
        "certificate", "claim", "claim_key", "design", "enumeration", "exhaustive",
        "for_question_id", "method", "params", "script_path", "search_bound",
        "search_space", "timeout",
    }, "这条负控按 verify.run_experiment 当前的 property 集合写的，集合变了要同步改"

    def armed() -> list[tuple[str, list[str]]]:
        props = dict(original.params["properties"])
        props[FAKE_PROPERTY] = {"type": "string"}
        reg._specs[name] = dataclasses.replace(
            original, params={**original.params, "properties": props}
        )
        return schema_property_violations(reg)

    def disarmed() -> list[tuple[str, list[str]]]:
        reg._specs[name] = original
        return schema_property_violations(reg)

    try:
        violations = armed()
        assert violations == [(name, [FAKE_PROPERTY])], (
            f"注入了假 property 而判据没报出它（或报的不是它）：{violations} —— "
            f"判据在这个形态上没有牙"
        )
        # 自校：注入真的生效了吗（不做这一断言，注入被写坏时负控会假绿）
        injected = reg._specs[name]
        assert FAKE_PROPERTY in _declared_properties(injected)
        assert injected.handler is original.handler, "负控只许改 schema，不许换 handler"
    finally:
        assert disarmed() == [], (
            "撤掉注入之后判据仍然报违反 ⇒ 判据恒红，前面的'红'不构成证据"
        )
    assert reg._specs[name] is original, "负控必须把注册表还原成原样"
