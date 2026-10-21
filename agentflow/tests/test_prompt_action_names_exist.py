# -*- coding: utf-8 -*-
"""判据：提示词里点名的 `角色.动作` 必须真的存在于能力表里（`P1-2`）。

## 为什么要有这一条（真机读数）

`specs/d.py:210` 与 `specs/m.py:91` 两处（D 与 M 的 policy，逐字进提示词）点名了`F.attack.step`。而
`capabilities.find_action('F', 'attack.step')` 是 `None` ——F 的四个动作是 `create_plan` / `step` / `status` / `list_plans`，
没有 `attack.step`（`attack.step` 是工具的名字，`F.step` 是动作的名字：同一实现的两种命名空间）。后果是安静的那种：D 与 M 被教着去派一件不存在的东西，
派出去只会落`unknown_action`；而"提示词里写的动作名到底能不能派"没有任何读数会红（`test_agent_prompts.py` 那一组守的是工具名、伙伴表、三态词表，没有守这一轴）。

## 判据的形状

- 正控：把所有角色的提示词（`agent_prompts.system_prompt` 现渲染的那一份）扫一遍，
里面每一处 `角色.名字` 都必须 `find_action(角色, 名字)` 得到（F 是这一批改的对象，但同一条判据对任何角色都成立 —— 只盯 F 会让"下次点错的是 C.xxx"漏掉）；
- 负控①（证明它会红）：把 `F.attack.step` 塞进一段真的提示词文本 ⇒ 扫描器当场吐出来；
- 负控②（证明它不是靠白名单过的）：一个不存在的 `F.frobnicate` 同样被抓到；
- 豁免面只有一条：路径里的同名片段（`notes/M.md` 的 `M.md`）不算动作引用 ——
豁免的依据是"前面是路径分隔符"，不是"这几个字我见过"。
"""
from __future__ import annotations

import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow import schema as S
from agentflow.tools import ToolRegistry, build_registry

#: 要扫的角色：可被召唤的 A-H 加主控（与 `test_agent_prompts.ALL_ROLES` 同一份口径）。
ALL_ROLES: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: `角色.动作`（动作名可带一段点号，例如 `F.attack.step`）。
_ROLE_REF = re.compile(r"\b([A-HMV])\.([a-z][a-z_]*(?:\.[a-z][a-z_]*)?)\b")

#: 路径分隔符：`notes/M.md` 里的 `M.md` 是文件名，不是"角色 M 的动作 md"。
_PATH_SEP = ("/", "\\")


def action_refs(text: str) -> list[tuple[str, str]]:
    """这段文本里每一处「角色.名字」⇒ `[(角色, 名字)]`（去掉路径里的同名片段）。

    为什么把"路径"这一档写成一条显式豁免而不是靠正则绕：`notes/M.md` 这种写法会
    随着交付物形态变化，绕法一变就漏；豁免面写清楚才能被负控钉住。
    """
    out: list[tuple[str, str]] = []
    for m in _ROLE_REF.finditer(text):
        before = text[max(0, m.start() - 1):m.start()]
        if before in _PATH_SEP:
            continue
        out.append((m.group(1), m.group(2)))
    return out


def unknown_actions(text: str) -> list[tuple[str, str]]:
    """这段文本里点名了、而 `find_action` 查不到的那些」（空列表 = 全都在册）。"""
    return sorted({(role, name) for role, name in action_refs(text)
                   if C.find_action(role, name) is None})


def unknown_f_actions(text: str) -> list[str]:
    """只取 F 那一半（负控用：改前那两处点的正是 `F.attack.step`）。"""
    return sorted({name for role, name in unknown_actions(text) if role == "F"})


@pytest.fixture()
def registry() -> ToolRegistry:
    """一张不带工作区的注册表（与 `test_agent_prompts.py` 同一份口径：没有 fs 工具）。"""
    return build_registry().registry


def _prompt(role: str, registry: ToolRegistry) -> str:
    return AP.system_prompt(role, registry=registry, task="把这条链路走一遍",
                            workspace_root="D:/x")


def test_every_action_named_in_a_prompt_really_exists(registry: ToolRegistry):
    """正控：任何角色提示词里点名的 `角色.动作` 都必须查得到 —— 今天的读数应当是空表。"""
    problems = {role: unknown_actions(_prompt(role, registry)) for role in ALL_ROLES}
    bad = {role: names for role, names in problems.items() if names}
    assert bad == {}, (
        "这些提示词里点名了能力表里没有的动作（模型会照着派，然后拿到 "
        f"`unknown_action`）：{bad}；F 的动作是 {[a.action for a in C.actions_for('F')]}")

    # 反真空：D 与 M 两份提示词里确实有 F 的动作名（否则"全都在册"是空转）
    for role in ("D", "M"):
        names = [name for r, name in action_refs(_prompt(role, registry)) if r == "F"]
        assert "step" in names, (
            f"{role} 的提示词里一个 `F.step` 都没有 ⇒ 这条判据在这一格是空转"
            f"（读到的是 {names}）")


def test_the_scanner_catches_the_name_that_was_there_before_the_fix(registry: ToolRegistry):
    """负控①：`F.attack.step` 这种名字必须被扫出来（改前 d.py/m.py 逐字就是它）。"""
    poisoned = _prompt("M", registry) + "\n并至少推进一步 `F.attack.step`。\n"
    assert unknown_f_actions(poisoned) == ["attack.step"], unknown_f_actions(poisoned)
    # 负控②：一个谁也没见过的名字同样被抓到（不是靠"这几个字见过"过的）
    assert unknown_f_actions("派 `F.frobnicate` 去做") == ["frobnicate"]
    # 反负控③：真的在册的名字不许被误伤（否则判据会变成"凡 角色.x 都红"）
    assert unknown_actions("派 `F.step` 推进、用 `F.create_plan` 立项") == []


def test_a_path_segment_that_looks_like_an_action_is_not_judged(registry: ToolRegistry):
    """豁免面只有一条：路径里的 `M.md` 不算"角色 M 的动作 md"。"""
    assert unknown_actions("写在盘上（`notes/M.md`）但只记给自己看") == []
    # 反负控：豁免只对"前面是路径分隔符"生效 —— 同一个词不在路径里就必须判
    assert unknown_actions("派 `M.md` 去做") == [("M", "md")]
