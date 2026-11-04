# -*- coding: utf-8 -*-
"""判据：十份角色提示词里"子任务被拒"那一格必须与工具读数同名（2026-11-04，审 F 区）。

> 文件名保留 2026-11-04 第一版的范围（当时只钉 A / C），正文已扩到十份。**不改名**
> 是因为 `specs/a.py` / `specs/c.py` 的注释还指着这个路径（改名要再动一次禁改区），
> 不是"名字还准"。

## 背景（扩到十份时是红的）

`agenttrace.node_facts` 在 2026-11-03（153-U-09 第二笔）把那一格从 `refusals`
改名成 `subtask_refusals`，为的是把四件同名的东西分开：
`statusreport.action_refusals`（台账里的动作行）、`clock.final_refusals`（收工被拒）、
`secretary.registration_refusals`（名册写口）、`agenttrace.subtask_refusals`（子任务）。

工具面的 `returns=` 跟着改了（`tools/trace_tools.py` / `tools/conductor_tools.py` 的
`trace.children` 与 `conductor.watch`），而 p200 那一段政策（`specs/<角色>.py` 的
policy，十个角色各有一份）还写着「被拒次数与类目（`refusals`）」—— 模型照它去
`trace.children` 的返回里找一个不存在的键，只会得出"这一格没有东西"。
这正是"提示词说 X、代码做 Y"。

p200 那一段是十份共用的同一段文案，所以判据也必须十份一起看：只钉 A / C 时，
另外八份改了没人知道、也没人拦（这一版扩范围时实测：8 failed / 2 passed）。

## 这条判据钉什么

1. 反真空：`agenttrace.node_facts` 的返回里今天真的有 `subtask_refusals`、且没有裸
   `refusals`（键集从代码里现读，不手抄）。若哪天改回去，这条判据自己先红 —— 那时
   要改的是它，不是把下面的正控放宽。
2. 正控（十份，逐角色）：每个角色的提示词里点名 `trace.children` 的那一句必须写
   `subtask_refusals`，且不许再出现裸 `refusals` 的键写法。
3. 覆盖面：没有第十一个角色带着这一句却没进 `_ROLES`（否则"十份全绿"可能只是
   "该看的没看"）。
4. 负控：把 B 的那一句里的 `subtask_refusals` 换回 `refusals` 再喂给同一个检查 ⇒
   必须点名报出来（证明检查函数不是橡皮图章）。

范围是 A / B / C / D / E / F / G / H / L / V 十份（M 没有这一句：它看全树走
`conductor.watch`，不是 `trace.children`）。
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from agentflow import specs as SP

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"

#: 工具读数里那一格的真名（2026-11-03 之后）。
_SUBTASK = "subtask_refusals"

#: 裸 `refusals` 的键写法（反引号包起来的那个词本身）。
_BARE = re.compile(r"`refusals`")

#: 提示词里点名的另外三格（用来证明读到的键集确实是"子任务读数"那一份）。
_SIBLINGS = ("recent_steps", "products", "last_handoff")

#: 带 p200 那段政策、因而必须点名这一格的角色（十个；M 不在里面）。
_ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "L", "V")


def _node_fact_keys() -> set[str]:
    """`agenttrace.node_facts` 那个返回字典字面量的键集（现读，不手抄）。"""
    tree = ast.parse((_SRC / "agenttrace.py").read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "node_facts"):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                return {k.value for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise AssertionError("agenttrace.py 里找不到 node_facts 的返回字典（判据的对象没了）")


def _trace_children_lines(role: str) -> list[str]:
    """该角色提示词里点名 `trace.children` 的那几句（boundary / policy / stance 逐条拆行）。"""
    brief = SP.builtin_specs()[role].brief
    lines: list[str] = []
    for text in (*brief.boundary, *brief.policy, *brief.stance):
        for line in str(text).splitlines():
            if "trace.children" in line or "被拒次数与类目" in line:
                lines.append(line)
    return lines


def _problems(role: str, lines: list[str]) -> list[str]:
    """这一批句子里与工具读数对不上的地方（空列表 = 对得上）。"""
    bad: list[str] = []
    for line in lines:
        if _BARE.search(line):
            bad.append(f"{role}：`trace.children` 那一句里仍有裸 `refusals`"
                       f"（工具读数叫 `{_SUBTASK}`）")
        if _SUBTASK not in line:
            bad.append(f"{role}：`trace.children` 那一句没写 `{_SUBTASK}` "
                       f"⇒ 模型照它找不到那一格")
    return bad


# ---------------------------------------------------------------- ① 反真空：键集本身


def test_the_subtask_cell_is_named_subtask_refusals_in_the_code() -> None:
    """① 工具读数今天真叫 `subtask_refusals`、且没有裸 `refusals`（判据的前提）。"""
    keys = _node_fact_keys()
    assert _SUBTASK in keys, (
        f"`agenttrace.node_facts` 的返回里没有 `{_SUBTASK}`（键集：{sorted(keys)}）"
        " ⇒ 这条判据的前提过期：请先看它是不是又改名了")
    assert "refusals" not in keys, (
        f"`agenttrace.node_facts` 的返回里又有裸 `refusals` 了（键集：{sorted(keys)}）"
        " ⇒ 三义又共用一个名字；那时要改的是这条判据，不是把正控放宽")
    for key in _SIBLINGS:
        assert key in keys, (
            f"`agenttrace.node_facts` 的返回里没有 `{key}` ⇒ 读到的这份键集不是"
            "「子任务读数」那一份，下面的正控会拿错对象")


# ---------------------------------------------------------------- ② 正控：十份提示词


@pytest.mark.parametrize("role", _ROLES)
def test_each_spec_prompt_names_the_subtask_refusal_cell(role: str) -> None:
    """② 十份提示词各自点名 `subtask_refusals`，不写裸 `refusals`。"""
    lines = _trace_children_lines(role)
    assert lines, f"{role} 的提示词里没有点名 `trace.children` 的那一句 ⇒ 判据失去对象"
    bad = _problems(role, lines)
    assert not bad, (
        "提示词把 `trace.children` 的「被拒次数与类目」那一格指向了一个不存在的键：\n  - "
        + "\n  - ".join(bad))


# ---------------------------------------------------------------- ③ 覆盖面：没有第十一份漏网


def test_no_role_outside_the_ten_carries_that_sentence() -> None:
    """③ 带着这一句的角色恰好是那十份 —— 多出来的必须进 `_ROLES`，否则是"没看"。"""
    extra = sorted(role for role in SP.builtin_specs()
                   if role not in _ROLES and _trace_children_lines(role))
    assert not extra, (
        f"这些角色也带着「子任务被拒」那一句、却不在判据的十份里：{extra} ⇒ "
        "要么把它们加进 `_ROLES`，要么说明它们指的不是 `agenttrace.subtask_refusals`")


# ---------------------------------------------------------------- ④ 负控：检查函数不是橡皮图章


def test_the_checker_is_not_a_rubber_stamp() -> None:
    """④ 把 B 的 `subtask_refusals` 换回 `refusals` ⇒ 同一个检查必须点名报出来。"""
    role = "B"
    lines = _trace_children_lines(role)
    doctored = [line.replace(_SUBTASK, "refusals") for line in lines]
    assert doctored != lines, (
        f"夹具前提：{role} 的那一句里今天写的是 `{_SUBTASK}`（否则下面这一条在测空气）")
    got = _problems(role, doctored)
    assert got, "换回裸 `refusals` 之后检查函数一声不响 ⇒ 它不是判据"
    assert any("refusals" in item for item in got), got
