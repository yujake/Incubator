"""`P-1`：R004 已退休 —— 而且"退休"这件事本身必须是可断言的。

为什么需要这一节：退休一条规则最容易的坏法是悄悄不报。那样规则数不变、
输出也看不出异常，读者会以为判据面没变，而实际上少了一条。
所以这里钉五件事：退休有登记、退休后不产生 findings、编号仍在注册表里（不悬空）、
接替者（注册期校验，`ToolRegistry.register*` 的 `roles ⊆ schema.ROLES`）真的在，
以及那张豁免表与它的两个 warning 一起收掉了（`ROLE_VALIDATOR_CALLS` /
`R004_ALLOWED_SITES` 不再存在 —— 留着它们就成了"永不生效的豁免"）。

形态与 `tests/test_lint_rules_r006_retired.py` 逐条同族（同一件事不该有两种写法）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("_lint_rules_under_test_r004", ROOT / "scripts" / "lint_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()


def test_r004_is_retired_with_a_reason() -> None:
    """退休必须显式登记并带理由，且理由点明"判据移到注册期"。"""
    assert "R004" in L.RETIRED_RULES, "退休没登记 ⇒ 规则数会假装没变"
    why = L.RETIRED_RULES["R004"]
    assert why.strip(), "退休必须写清理由，否则下一个人只会把它改回来"
    assert "注册期" in why or "注册" in why, f"退休理由必须点明判据去了哪里：{why!r}"


def test_retired_rule_produces_no_findings() -> None:
    """退休后不再产生 findings（判据面已由注册期校验承担）。

    负控形态：这里刻意用一个"经典正样本"（工具层之外构造 `ToolRegistry`）——
    它在退休前会报 warning，退休后必须一条都不报。
    """
    assert L.rule_R004_registry_outside_tools(ROOT) == []


def test_retired_rule_keeps_its_number_in_the_registry() -> None:
    """编号保留：删号会让历史报告与 `DEVELOPMENT.md` §6 里的 "R004" 变成悬空引用。"""
    assert any("R004" in str(entry) for entry in L.RULES), "R004 从注册表里消失了"


def test_the_replacement_judgement_really_exists() -> None:
    """接替者必须真的在：`ToolRegistry.register*` 各核一次 `roles ⊆ schema.ROLES`。

    为什么断言在工具层而不是 linter 里：`P-1` 把判据从"lint 探测器"换成
    "构造期的门" —— 如果那个门被移走，R004 就是白退的（判据面凭空消失）。
    """
    import importlib

    base = importlib.import_module("agentflow.tools.base")
    reg_cls = base.ToolRegistry
    for name in ("register", "register_function", "register_spec"):
        assert hasattr(reg_cls, name), f"注册入口 {name} 不见了"
    assert hasattr(reg_cls, "_reject_unknown_roles"), "注册期的 roles 判据不见了"
    # 负控：非法角色在注册那一刻抛（而不是只在 build_registry 的装配期）。
    from agentflow.tools.base import ToolSpec

    reg = reg_cls(name="probe")
    try:
        reg.register(ToolSpec(
            name="probe.bad", summary="非法角色样本",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: base.ok({}), roles=("agent-X",), returns="（无）",
        ))
    except base.ToolError as exc:
        assert "ROLES" in str(exc), str(exc)
    else:
        raise AssertionError("非法角色在注册期没有被拒 ⇒ P-1 没接上，R004 是白退的")


def test_the_exemption_tables_are_gone() -> None:
    """豁免表连同它的两条 warning 一起收掉了。

    留着 `ROLE_VALIDATOR_CALLS` / `R004_ALLOWED_SITES` 会变成"永不生效的豁免"：
    判据已经不跑了，而两张表还在告诉读者"这些点被豁免了"。
    """
    for name in ("ROLE_VALIDATOR_CALLS", "R004_ALLOWED_SITES", "REGISTRY_BUILDERS"):
        assert not hasattr(L, name), f"{name} 应当随 R004 退休一起收掉"
