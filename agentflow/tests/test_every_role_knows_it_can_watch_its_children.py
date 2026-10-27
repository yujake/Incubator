# -*- coding: utf-8 -*-
"""判据：每一个可召唤角色都知道「自己能监控直接下级一层」，M 那一侧按实现点名工具。

业主口径（唯一权威，两条都落）：

    ①「注意不只是M侧改，其它所有智能体都要知道有监控一层子代理的能力」
    ②「到时候改M提示词那路要在监控接线后按具体实现明确」

## 这一份守的是什么

接线已经落地（`trace.children` / `conductor.watch` / `conductor.escalate` /
`conductor.guide` 四件都在工具面上），缺的是十个可召唤角色的提示词里一个字都没有
—— 于是模型不知道自己有这一层能力，M 那一侧也还写着"写成一句话指导、沿树传到对应
智能体"这种不点工具名的口径。这一份把两件事都变成可判的：

| 判据 | 守的那件事 | 改前形态 |
|---|---|---|
| 01 | 十个角色逐个：渲染出来的提示词里读得到「`trace.children`」与「向 M 请求」两层意思 | 红：十个角色的 policy 里没有一个字提到它 |
| 02 | 工具面自洽：政策里点名的工具真的在该角色的工具面上；M 没有 `trace.children`、非 M 没有 `conductor.watch` / `conductor.guide` | 绿（护栏：这是防"提示词教它调一件它没有的工具"） |
| 03 | M 的政策里读得到 `conductor.watch` / `conductor.guide` 与「自动通知每一级父」「不必另发 message」 | 红：M 的 policy 里 0 处工具名 |
| 04 | 反真空（逐个参数化）：把某个角色那一条 policy 摘掉 ⇒ 01 对这个角色必红，换回去又绿 | 红：没有可摘的那一条 |

## 为什么 01 要多核几个短语（不只核工具名）

工具目录（按角色工具面渲染的那一段）本来就会印 `trace.children` 的说明，而那段说明
里逐字写着「更深要看请向 M 请求」 —— 只核这两个字样的话，把政策整条摘掉它照样绿
（实测：先按两个字样写，04 这条反真空当场打空）。所以 01 除了那两层意思，还要核三个
只在 policy 里出现的短语（「下级的下级的下级」/「各级父的通知」/「不是原始全树数据」）。
一句话：核的是"政策真的说了这件事"，不是"工具目录里出现过这个词"。

## 零模型调用

提示词是纯函数，工具面是装配读数（`build_registry()`），边表是常量。
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow.tools import ToolRegistry, build_registry

#: 十个可召唤角色（`S.ROLES` 不含 M；M 那一侧由 03 单独判）。
ROLES10: tuple[str, ...] = tuple(S.ROLES)

#: 这一批落地的四件工具（政策里点名的那几件，逐个核它在不在工具面上）。
TRACE_CHILDREN = "trace.children"
WATCH = "conductor.watch"
GUIDE = "conductor.guide"
ESCALATE = "conductor.escalate"

#: 渲染用固定值（与 `test_agent_prompts.py` / `test_g_asks_d_not_b_for_registration.py`
#: 同一套：判据必须确定性，不随机器读数变）。
_TASK = "把这条链路走一遍"
_ROOT = "D:/x"
_FACTS = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
          "- 检查器：（判据夹具，与机器无关）")
_FORMAL = ("你这一岗怎么写形式化（由上面那份读数现算）：\n"
           "- （判据夹具：这一次按自足文件写）")

#: 强调符号与空白：判「读到的意思」，不判排版（与本仓其它提示词判据同一口径）。
_EMPHASIS = re.compile(r"[\s*`]+")

#: 01 要在渲染后的提示词里读到的东西（去掉强调与空白之后逐条核）。
#:
#: 前两条是业主口径里点名的那两层意思；后三条是"这一段真的来自 policy"的判别式
#: （理由见模块 docstring 末节：只核前两条时，04 那条反真空会打空）。
_NEEDLES: tuple[tuple[str, str], ...] = (
    (TRACE_CHILDREN, "看得见自己的直接下级，入口就是这件工具"),
    ("向 M 请求", "更深的分支要向 M 请求（不是自己想办法绕）"),
    ("只看得见一层", "只看一层这条约束写明"),
    ("下级的下级的下级", "「更深」举的例子（说明它看的是第 2 层以下）"),
    ("只有链尾", "M 传下来的东西只到链尾（中间各跳不读内容）"),
    ("中间各跳", "中间各跳只转发、不读内容这句写明"),
    ("不是原始全树数据", "你拿到的是指导，不是全树原始数据"),
)

#: 03 要在 M 的政策里读到的东西。
_M_NEEDLES: tuple[tuple[str, str], ...] = (
    (WATCH, "看全树用哪件工具，点名"),
    (GUIDE, "下发指导用哪件工具，点名"),
    ("只有链尾", "guide 的正文只到链尾（各级父通知已取消）"),
    ("中间各跳", "中间各跳只转发、不读内容这句写明"),
    ("不必再另发 message", "转发是附带的，不用另发一条消息"),
    (ESCALATE, "非 M 角色深看请求走哪件既有通道"),
    ("chain_text", "回执里那条链的写法（下一轮复述用）"),
)

#: 渲染下限（反真空：空串或占位文本不许通过）。
_MIN_CHARS = 3000


def _flat(text: str) -> str:
    """去掉强调符号与所有空白 —— 判「读到的意思」。"""
    return _EMPHASIS.sub("", str(text))


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    """一张不带工作区的注册表（这些用例只渲染提示词、只读工具面）。"""
    return build_registry().registry


def _prompt(role: str, registry: ToolRegistry) -> str:
    """真的渲染一遍这个角色的提示词（纯函数，零模型调用）。"""
    return AP.system_prompt(role, registry=registry, task=_TASK,
                            workspace_root=_ROOT, toolchain_facts=_FACTS,
                            toolchain_formal=_FORMAL)


def _missing(text: str, needles=_NEEDLES) -> list[str]:
    """这段提示词里缺哪几层（空清单 = 都读得到；另带渲染下限的反真空）。"""
    if len(str(text)) < _MIN_CHARS:
        return [f"渲染出来的提示词只有 {len(str(text))} 字（下限 {_MIN_CHARS}）"
                " ⇒ 这一条没有落脚点（它不是在判一份真的提示词）"]
    flat = _flat(text)
    return [f"读不到「{needle}」（{why}）" for needle, why in needles if _flat(needle) not in flat]


def _tool_names(registry: ToolRegistry, role: str) -> set[str]:
    """这个角色此刻的工具面（现算，不抄名单）。"""
    return {spec.name for spec in registry.for_role(role)}


def _policy_text(role: str) -> str:
    """这个角色 policy 的全文（真身是 `specs/<role>.py`，经 `ROLE_BRIEFS` 现读）。"""
    return "\n".join(str(item) for item in AP.ROLE_BRIEFS[role].policy)


# ============================================================ 01 十个角色逐个读得到
@pytest.mark.parametrize("role", ROLES10)
def test_01_each_role_prompt_says_it_can_watch_its_children(
        role: str, registry: ToolRegistry) -> None:
    """01：这个角色的提示词里读得到「看得见直接下级一层 + 更深向 M 请求」这一层意思。"""
    text = _prompt(role, registry)
    problems = _missing(text)
    assert problems == [], "\n".join(problems)
    # 这些字样的真身是 `specs/<role>.py` 的 policy（提示词只是把它渲染出来）：
    # 两处都要有，否则「提示词里有」可能只是别的一段碰巧写着同样的话。
    policy = _policy_text(role)
    absent = [needle for needle, _why in _NEEDLES if _flat(needle) not in _flat(policy)]
    assert absent == [], f"specs/{role.lower()}.py 的 policy 里缺 {absent}"


# ============================================================ 02 工具面自洽
@pytest.mark.parametrize("role", ROLES10)
def test_02_the_tools_the_policy_names_really_are_on_that_roles_surface(
        role: str, registry: ToolRegistry) -> None:
    """02：政策里点名的工具真的在该角色的工具面上（点名一件它没有的 = 教它撞墙）。"""
    policy = _policy_text(role)
    surface = _tool_names(registry, role)
    assert _flat(TRACE_CHILDREN) in _flat(policy), (
        f"{role} 的 policy 里没有 {TRACE_CHILDREN} ⇒ 01 那一层意思没有落点")
    problems: list[str] = []
    for tool in (TRACE_CHILDREN, ESCALATE):
        if _flat(tool) in _flat(policy) and tool not in surface:
            problems.append(f"{role} 的 policy 点名了 {tool}，而它不在这个角色的工具面上")
    # 反向：政策里点名的两件全树工具只归 M —— 非 M 角色连提都不该提（提了就是教它越权）。
    for tool in (WATCH, GUIDE):
        if _flat(tool) in _flat(policy):
            problems.append(f"{role} 的 policy 里出现了 {tool}（只有 M 有这一件）")
        if tool in surface:
            problems.append(f"{role} 的工具面上有 {tool}（只有 M 该有）")
        if _flat(tool) in _flat(_prompt(role, registry)):
            problems.append(f"{role} 的渲染提示词里出现了 {tool}（只有 M 该有）")
    assert problems == [], "\n".join(problems)


def test_02_m_has_the_tree_tools_and_not_the_one_layer_tool(registry: ToolRegistry) -> None:
    """02（M 那一侧）：`watch` / `guide` 在 M 的工具面上，`trace.children` 不在。"""
    surface = _tool_names(registry, S.CONDUCTOR_ROLE)
    assert WATCH in surface, f"M 的工具面上没有 {WATCH} ⇒ 全树那一档没有入口"
    assert GUIDE in surface, f"M 的工具面上没有 {GUIDE} ⇒ 指导下发没有入口"
    assert TRACE_CHILDREN not in surface, (
        f"M 的工具面上有 {TRACE_CHILDREN} ⇒ 业主裁定的「普通代理追一层、M 追全树」两档混了")
    assert _flat(TRACE_CHILDREN) not in _flat(_prompt(S.CONDUCTOR_ROLE, registry)), (
        "M 的渲染提示词里出现了 trace.children（M 看到的是全树，不是一层）")


# ============================================================ 03 M 按实现点名工具
def test_03_m_policy_names_watch_and_guide_and_says_content_stops_at_the_tail(
        registry: ToolRegistry) -> None:
    """03：M 的政策里读到 watch / guide 与「内容只到链尾、中间各跳不读、不必另发 message」。"""
    policy = _policy_text(S.CONDUCTOR_ROLE)
    problems = _missing(policy, _M_NEEDLES)
    assert problems == [], "specs/m.py 的 policy 里：\n  - " + "\n  - ".join(problems)
    # 渲染出来的提示词里也要读得到同样的两件工具名（政策真的进了那一段）。
    flat_prompt = _flat(_prompt(S.CONDUCTOR_ROLE, registry))
    absent = [needle for needle, _why in _M_NEEDLES
              if _flat(needle) not in flat_prompt]
    assert absent == [], f"M 的渲染提示词里读不到 {absent}"


# ============================================================ 04 反真空（逐个参数化）
@pytest.mark.parametrize("role", ROLES10)
def test_04_dropping_that_one_policy_item_turns_this_roles_criterion_red(
        role: str, registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    """04：把某个角色那一条 policy 摘掉 ⇒ 01 对这个角色必红；换回去又绿。"""
    brief = AP.ROLE_BRIEFS[role]
    kept = tuple(item for item in brief.policy if TRACE_CHILDREN not in str(item))
    assert len(kept) == len(brief.policy) - 1, (
        f"夹具前提：{role} 的 policy 里恰好一条装着 {TRACE_CHILDREN}"
        f"（实际 {len(brief.policy) - len(kept)} 条）")
    stripped = dataclasses.replace(brief, policy=kept)
    monkeypatch.setitem(AP.ROLE_BRIEFS, role, stripped)
    problems = _missing(_prompt(role, registry))
    assert problems, (
        f"把 {role} 那一条 policy 摘掉之后 01 还是绿的 ⇒ 它判的不是提示词里那一段话"
        "（读到的也许只是工具目录里的描述）")
    assert any("只看得见一层" in one or "下级的下级的下级" in one for one in problems), problems

    # 负控的负控：换回去 ⇒ 判据重新成立（这一半让本条在改前也红）。
    monkeypatch.setitem(AP.ROLE_BRIEFS, role, brief)
    assert _missing(_prompt(role, registry)) == [], f"{role} 换回去之后 01 仍然红"
