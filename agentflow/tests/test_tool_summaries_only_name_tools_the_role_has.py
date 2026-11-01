# -*- coding: utf-8 -*-
"""工具摘要不许点名「该角色拿不到的工具」；提示词不许把模块函数写成工具（审计 174 §1.3/§1.4）。

两件事是同一个后果的两面：模型照着提示词去调，拿到 `unknown_tool`（幻名）或
`role_denied`（别人面上的工具）——而这两类写法在提示词里看起来与真工具一模一样。

判据一（跨面）：把每一格的 `tools_lines()` 逐行扫一遍，凡行内出现真工具名、而该角色
面上没有它 ⇒ 那一行必须写明这是别人的工具（同一行里有「主控」或「父」这类转述词）；
否则红。改前实测 31 对，其中硬缺口 2 类：`program.list` 叫人「先 program.stop」（C/H/V
没有它）、`text.extract` 叫人「走 ocr.run」（A 的 ocr.* 为 0 件）。

判据二（幻名）：`STRUCTURE_NOT_PROMPT` 那段是「框架用结构保证的事」，里面 4 条被写成
工具形（`policy.check` / `quoteverify.check_quote` / `userio.ask_user` /
`autonomy.run_autonomous`），而 123 件工具里一件都没有；`conductor.summon_many` 的摘要
另点了一个 `policy.waves_of`。这 5 个 token 在十一格渲染提示词里必须为 0。

反真空：判据一先断言扫描器真的抓得住一条人造的跨面提及（否则"没有命中"可能只是没扫）。
"""
from __future__ import annotations

import pathlib
import re
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow.agent_prompts import STRUCTURE_NOT_PROMPT, tools_lines  # noqa: E402
from agentflow.tools import ROLES, TOOL_ROLES, build_registry          # noqa: E402

_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
#: 转述词：出现这些词就说明"这不是你自己的工具"（审计 174 把这一类判成"软"）。
_TRANSCRIBED = ("主控", "你的父", "父代理", "召唤者")

#: 工具形幻名（`agent_prompts.py` 的 STRUCTURE_NOT_PROMPT + summon_many 摘要）。
PHANTOMS = (
    "policy.check",
    "quoteverify.check_quote",
    "userio.ask_user",
    "autonomy.run_autonomous",
    "policy.waves_of",
)


def _reg():
    return build_registry().registry


def _bad_mentions(lines: list[str], names: set[str], have: set[str]) -> list[str]:
    """行内点名的真工具、而该角色没有 ⇒ 返回 `owner -> token` 清单（纯函数）。"""
    out: list[str] = []
    for line in lines:
        owner = line.split("：", 1)[0].lstrip("- ").strip()
        for tok in sorted(set(_TOOL_NAME.findall(line))):
            if tok in names and tok not in have:
                if any(word in line for word in _TRANSCRIBED):
                    continue
                out.append(f"{owner} -> {tok}")
    return out


def test_no_tool_line_names_a_tool_the_role_lacks_without_saying_whose() -> None:
    reg = _reg()
    names = set(reg.names())
    assert len(names) >= 100, f"注册表只有 {len(names)} 件工具 ⇒ 这条判据没有对象"
    bad: list[str] = []
    checked = 0
    for role in (*ROLES, "M"):
        have = {s.name for s in reg.for_role(role)}
        lines = tools_lines(role, reg)
        checked += len(lines)
        for one in _bad_mentions(lines, names, have):
            bad.append(f"{role}: {one}")
    assert checked >= 400, f"只扫了 {checked} 行 ⇒ 扫描面不对"
    assert not bad, (
        "工具摘要点名了该角色拿不到的工具（模型会照着调，然后拿 role_denied）：\n  "
        + "\n  ".join(bad[:12]))


def test_the_cross_mention_scanner_catches_a_synthetic_one() -> None:
    """负控：人造一条「A 的 program.list 叫人用 program.stop」⇒ 扫描器必须报。"""
    names = {"program.list", "program.stop"}
    got = _bad_mentions(["- program.list：列出程序（先 program.stop 停掉）"],
                        names, {"program.list"})
    assert got == ["program.list -> program.stop"], got
    # 转述不算：同一句里点名"主控"就放行
    assert _bad_mentions(["- program.list：列出程序（由主控 program.stop 停掉）"],
                         names, {"program.list"}) == []


def test_the_prompt_never_names_a_module_function_as_a_tool() -> None:
    from agentflow.agent_prompts import system_prompt

    reg = _reg()
    bad: list[str] = []
    for role in (*TOOL_ROLES, "M"):
        text = system_prompt(role, registry=reg)
        for token in PHANTOMS:
            if token in text:
                bad.append(f"{role}: {token}")
    assert not bad, (
        "提示词里仍有工具形幻名（它们不是工具，照字面调会拿 unknown_tool）：\n  "
        + "\n  ".join(bad))


def test_the_structure_section_still_describes_the_mechanisms() -> None:
    """反真空：删词不等于删事 —— 五条机制的中文描述必须还在（换成描述，不是删行）。"""
    text = "\n".join(f"{name}：{body}" for name, body in STRUCTURE_NOT_PROMPT)
    for needle in ("谁能唤起谁", "引文是否逐字可达", "只有用户能定的取舍",
                   "放手后的自主轮与汇报"):
        assert needle in text, f"STRUCTURE_NOT_PROMPT 里没有「{needle}」这一条"
    for needle in ("边/深度/扇出/并发/预算", "逐字回验", "用户频道", "自主轮"):
        assert needle in text, f"机制那一句的中文描述丢了：「{needle}」"
