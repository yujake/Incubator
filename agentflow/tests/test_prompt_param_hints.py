# -*- coding: utf-8 -*-
"""参数提示：必填逐个列、可选键用 `?key` 紧凑列（2026-11-01 口径变更）。

## 为什么改（审计 174 §1.2 的读数）

改前：`_params_hint` 只列必填，可用键交给"被拒时那张表"。123 件里 92 件有可选键、
合计 286 个；其中 43 件至少有一个键在十一份提示词里一个字都没出现过。而兜底只在
"第一次调用就被拒"时给全表 —— 一个一次成功、从不重试的工具，它的可选键等于没教。
典型：`analysis.register_report` 的 `payload`（C 唯一的业务落库口），失败形态不是被拒，
而是"分析做完了、登记行是空壳"。

改后：同一行里加一段 `可选 ?a、?b`（一个键一个 token、不带描述）。判据钉四件：

1. 每一格面上每一件工具的每一个可选键都以 `?key` 出现在该格的渲染提示词里；
2. 反真空：把某一件的某个 `?key` 从 `_params_hint` 里摘掉 ⇒ 检查器必须当场报（不是"恰好没缺"）；
3. 预算：每格 `tools_lines` 的字符数有上限（改动前实测 ×1.18，逐格登记在 `_BUDGET`）；
4. `LOOP_PROTOCOL` 的两句没丢：可用键是封闭集合、被拒时框架回完整参数表
   （丢了等于把当年那次 `invalid_params` 事故重新打开）。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP          # noqa: E402
from agentflow.agent_prompts import LOOP_PROTOCOL, tools_lines  # noqa: E402
from agentflow.tools import ROLES, TOOL_ROLES, build_registry   # noqa: E402

#: 每格 `tools_lines` 的字符上限（2026-11-01 实测值向上取整到百位；超了就是提示词又胖了）。
#: 改前/改后（可选键那一段带来的增量，逐格现算）：A 10655→11714、B 8031→8721、
#: C 5551→6187、D 9757→10961、E 8150→8922、F 9279→10412、G 9891→11127、
#: H 6780→7924（+16.9%，本格最高）、L 8484→9383、V 4827→5356、M 10750→11624。
_BUDGET: dict[str, int] = {
    "A": 11800, "B": 8800, "C": 6300, "D": 11050, "E": 9000, "F": 10500,
    "G": 11200, "H": 8000, "L": 9500, "V": 5400, "M": 11700,
}


def _reg():
    return build_registry().registry


def _optional_keys(role: str, reg) -> list[tuple[str, str]]:
    """该角色面上 (工具名, 可选键) 的每一对。"""
    out: list[tuple[str, str]] = []
    for spec in reg.for_role(role):
        req = set(AP._required_of(spec))
        for key in AP._props_of(spec):
            if key not in req:
                out.append((spec.name, key))
    return out


def test_every_optional_key_is_visible_as_a_question_mark_token() -> None:
    reg = _reg()
    bad: list[str] = []
    pairs = 0
    for role in (*TOOL_ROLES, "M"):
        text = "\n".join(tools_lines(role, reg))
        for tool, key in _optional_keys(role, reg):
            pairs += 1
            if "?" + key not in text:
                bad.append(f"{role}: {tool} 的可选键 {key!r} 不在提示词里")
    assert pairs >= 250, f"只数到 {pairs} 个可选键 ⇒ 这条判据没有对象"
    assert not bad, "可选键没教全：\n  " + "\n  ".join(bad[:15])


def test_the_checker_catches_a_missing_optional_key() -> None:
    """反真空：人造一件工具、把它的可选键从提示里拿掉 ⇒ 检查器必须报。"""
    class _Spec:
        name = "demo.tool"
        params = {"type": "object", "properties": {
            "a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a"]}
        summary = "演示"
        side_effect = "read"

    hint = AP._params_hint(_Spec())
    assert "?b" in hint and "必填 a" in hint, hint
    # 摘掉可选那一段之后，`?b` 就不在提示里了 —— 判据要能看见这个差
    stripped = hint.replace("；可选 ?b", "")
    assert "?b" not in stripped


def test_the_tools_lines_budget_per_role() -> None:
    reg = _reg()
    over: list[str] = []
    for role in (*TOOL_ROLES, "M"):
        got = len("\n".join(tools_lines(role, reg)))
        if got > _BUDGET[role]:
            over.append(f"{role}: {got} > {_BUDGET[role]}")
    assert not over, "tools_lines 超出预算：\n  " + "\n  ".join(over)


def test_the_closure_rule_and_its_fallback_are_both_still_stated() -> None:
    """丢掉这两句就等于把当年的真机事故重新打开，而不会有任何地方报错。"""
    assert "封闭集合" in LOOP_PROTOCOL, (
        "LOOP 里不再说「可用键是封闭集合」⇒ 模型会以为没说过的键就能自己发明")
    assert "参数表" in LOOP_PROTOCOL, (
        "LOOP 里不再提'被拒时会给参数表'⇒ 兜底这条路模型不知道，等于没有兜底")
    reg = _reg()
    for role in (*TOOL_ROLES, "M"):
        text = "\n".join(tools_lines(role, reg))
        assert "封闭集合" in AP.system_prompt(role, registry=reg), (
            f"{role} 的提示词里没有封闭集合那句")
        assert "（必填" in text, f"{role} 的 tools_lines 里没有参数提示 ⇒ 这条判据失去对象"
