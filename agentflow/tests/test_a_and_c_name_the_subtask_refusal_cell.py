# -*- coding: utf-8 -*-
"""判据：A / C 提示词里"子任务被拒"那一格必须与工具读数同名（2026-11-04，审 F 区）。

## 背景（加这条判据时是红的）

`agenttrace.node_facts` 在 2026-11-03（153-U-09 第二笔）把那一格从 `refusals`
改名成 `subtask_refusals`，为的是把四件同名的东西分开：
`statusreport.action_refusals`（台账里的动作行）、`clock.final_refusals`（收工被拒）、
`secretary.registration_refusals`（名册写口）、`agenttrace.subtask_refusals`（子任务）。

工具面的 `returns=` 跟着改了（`tools/trace_tools.py`），而 p200 那一段政策
（`specs/<角色>.py` 的 policy，十个角色各有一份）还写着
「被拒次数与类目（`refusals`）」—— 模型照它去 `trace.children` 的返回里找一个
不存在的键，只会得出"这一格没有东西"。这正是"提示词说 X、代码做 Y"。

## 这条判据钉什么

1. 反真空：`agenttrace.node_facts` 的返回里今天真的有 `subtask_refusals`、且没有裸
   `refusals`（键集从代码里现读，不手抄）。若哪天改回去，这条判据自己先红 —— 那时
   要改的是它，不是把下面两条放宽。
2. 正控：A 与 C 的提示词里点名 `trace.children` 的那一句必须写 `subtask_refusals`，
   且不许再出现裸 `refusals` 的键写法。
3. 负控：把那一句里的 `subtask_refusals` 换回 `refusals` 再喂给同一个检查 ⇒ 必须点名
   报出来（证明检查函数不是橡皮图章）。

范围只到 A / C（本区的两个角色）：同一条 p200 政策还挂在 B / D / E / F / G / H / L / V
的 policy 里，那几份各有 lane 在动，不在本区改。
"""
from __future__ import annotations

import ast
import pathlib
import re

from agentflow import specs as SP

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"

#: 工具读数里那一格的真名（2026-11-03 之后）。
_SUBTASK = "subtask_refusals"

#: 裸 `refusals` 的键写法（反引号包起来的那个词本身）。
_BARE = re.compile(r"`refusals`")

#: 提示词里点名的另外三格（用来证明读到的键集确实是"子任务读数"那一份）。
_SIBLINGS = ("recent_steps", "products", "last_handoff")


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


# ---------------------------------------------------------------- ② 正控：A / C 的提示词


def test_a_and_c_prompts_name_the_subtask_refusal_cell() -> None:
    """② A / C 的提示词点名 `subtask_refusals`，不写裸 `refusals`。"""
    for role in ("A", "C"):
        lines = _trace_children_lines(role)
        assert lines, f"{role} 的提示词里没有点名 `trace.children` 的那一句 ⇒ 判据失去对象"
        bad = _problems(role, lines)
        assert not bad, (
            "提示词把 `trace.children` 的「被拒次数与类目」那一格指向了一个不存在的键：\n  - "
            + "\n  - ".join(bad))


# ---------------------------------------------------------------- ③ 负控：检查函数不是橡皮图章


def test_the_checker_is_not_a_rubber_stamp() -> None:
    """③ 把 `subtask_refusals` 换回 `refusals` ⇒ 同一个检查必须点名报出来。"""
    lines = _trace_children_lines("A")
    doctored = [line.replace(_SUBTASK, "refusals") for line in lines]
    assert doctored != lines, (
        "夹具前提：A 的那一句里今天写的是 `subtask_refusals`（否则下面这一条在测空气）")
    got = _problems("A", doctored)
    assert got, "换回裸 `refusals` 之后检查函数一声不响 ⇒ 它不是判据"
    assert any("refusals" in item for item in got), got
