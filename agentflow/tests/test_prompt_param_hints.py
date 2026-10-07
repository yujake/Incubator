"""参数提示只列必填，可用键交给"被拒时那张表"（R6 `draft/63 §2-①②` 的判据化）。

改前的形态：每条工具 / 动作 / 伙伴动作后面都挂一串"（必填 X；可选 Y、Z、…）"，
十角色合计的可选枚举是 10,458 字符（实测：M 1691 · G 1679 · F 1667 · D 1488 · H 1109 ·
E 983 · A 629 · B 557 · C 378 · V 277）。而它当年被加进来是有真机事故依据的 ——
`agent_prompts.py::_params_hint` 的 docstring 记着：第一次真机跑，模型给一个无参动作传了
两个键、拿到 `invalid_params`，"它不是不听话，而是提示词只说了必填、没说键是封闭集合"。

本轮（2026-10-07）把接住方换成兜底，而不是继续把枚举挂在每一步的提示词里（那是每次运行
每一步都要付的钱）：

* 可用键是封闭集合 —— LOOP 规则①明说；
* 写错时框架把完整参数表回给模型（`agent_loop._param_table`，三条形状都覆盖），
  它的判据在 `tests/test_param_table_on_refusal.py`（"被参数拒了却没给参数表" 必红）。

这一族判据钉两件事：可选枚举不许回到提示词里；封闭集合与那张兜底表这两句话不许丢
（丢了就等于把当年的真机事故重新打开，而没有任何地方会报错）。
"""

from __future__ import annotations

import pathlib
import re
import tempfile

from agentflow.agent_prompts import LOOP_PROTOCOL
from agentflow.store import Store
from agentflow.tools import ROLES, TOOL_ROLES, build_registry
from agentflow.agent_prompts import system_prompt

#: 参数提示里的"可选"枚举形态。
_OPTIONAL_RE = re.compile(r"可选\s")


def hints_with_optional(text: str) -> list[str]:
    """返回文本里带"可选"枚举的行。纯函数：正控与负控都调它。"""
    return [ln for ln in text.splitlines() if _OPTIONAL_RE.search(ln)]


def _rendered_prompts() -> dict[str, str]:
    """十角色的生产提示词（与 golden 同一口径）。"""
    ws = pathlib.Path(tempfile.mkdtemp(prefix="param-hints-")) / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    reg = build_registry(store=st, workspace_root=ws, roles=tuple(ROLES), strict=True).registry
    return {role: system_prompt(role, registry=reg) for role in (*TOOL_ROLES, "M")}


def test_no_role_prompt_enumerates_optional_parameter_keys() -> None:
    """正控：十角色提示词里都不许再有"可选"枚举。"""
    prompts = _rendered_prompts()
    # 反真空：得先证明提示词里真的还挂着参数提示，否则"没有可选"可能只是因为没有参数提示。
    hints = sum(p.count("（必填") for p in prompts.values())
    assert hints >= 100, (
        f"十角色合计只有 {hints} 处参数提示 ⇒ 这条判据可能失去对象："
        "不是「没有可选枚举」，而是「根本没有参数提示」"
    )
    bad: list[str] = []
    for role, text in prompts.items():
        for ln in hints_with_optional(text):
            bad.append(f"{role}: {ln.strip()[:120]}")
    assert not bad, (
        "提示词里又出现了可选键枚举（本轮已把可用键交给'被拒时那张表'，见本文件 docstring）"
        f"，共 {len(bad)} 行：\n  " + "\n  ".join(bad[:8])
    )


def test_the_optional_key_checker_actually_catches_an_enumeration() -> None:
    """负控（改前红）：喂一行带可选枚举的提示词，检查器必须报出来。"""
    fake = "  - t.a：做某件事（必填 无；可选 filter、limit、offset）；副作用 read"
    assert hints_with_optional(fake), "带可选枚举的行没有被报出来 ⇒ 上面那条正控是真空的"
    assert not hints_with_optional("  - t.a：做某件事（必填 无）；副作用 read"), "干净的参数提示被误报"


def test_the_closure_rule_and_its_fallback_are_both_still_stated() -> None:
    """丢掉这两句就等于把当年的真机事故重新打开，而不会有任何地方报错。"""
    assert "封闭集合" in LOOP_PROTOCOL, (
        "LOOP 里不再说「可用键是封闭集合」⇒ 模型会以为没说过的键就能自己发明"
    )
    assert "参数表" in LOOP_PROTOCOL, (
        "LOOP 里不再提'被拒时会给参数表' ⇒ 兜底这条路模型不知道，等于没有兜底"
    )
    prompts = _rendered_prompts()
    for role, text in prompts.items():
        assert "封闭集合" in text, f"{role} 的提示词里没有封闭集合那句"
