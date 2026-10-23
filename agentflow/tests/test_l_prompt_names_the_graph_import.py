# -*- coding: utf-8 -*-
"""判据（施工单 b）：L 的提示词必须写出「图论走哪条 import、可用性看哪条读数」。

## 为什么这一句必须进 L 的提示词

2026-10-24 的现场：盘上那份 Mathlib 的图论库已经编好了（`lake exe cache get` 加
`SimpleGraph` 编译通过），而 L 的提示词里一个字都没提它 —— 于是 L 只有两条路可走：
写一个不 import 任何库的自足文件，或者瞎猜一行 import。两条都不算错，但都没用上
那台机器上真实存在的库。

这一句同时钉两件事：

- 走哪条 import：`Mathlib.Combinatorics.SimpleGraph.Basic`（不是 umbrella
  `import Mathlib`：那一句能过但更重，而且它会把"库可用"这个结论的粒度抹平）；
- 信哪条读数：自检第 ⑤ 步那一条（`leantoolchain.mathlib_reading`）—— 不是记忆、
  不是"上次好像能编过"。读数说 absent / unusable 时如实回 unknown。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | `system_prompt("L")` 里读得到那条 import 与那两条名字（第 ⑤ 步 / `leantoolchain.mathlib_reading`） | policy 里一句都没有 |
| ② | 数据面：那条 import 与那个函数真的存在（`leantoolchain.MATHLIB_GRAPH_MODULE` / `mathlib_reading`） | 免得提示词点着一个不存在的东西 |
| ③ | 反真空：把那一条 policy 拿掉 ⇒ ① 必须红 | 判据不许是恒绿的 |

零模型调用（提示词是纯函数）。
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import leantoolchain as LT
from agentflow.tools import build_registry

#: 那条 import 的模块（与 `leantoolchain.MATHLIB_GRAPH_MODULE` 是同一个东西，
#: 但这里写死一份：实现把常量改坏了，这条判据要跟着红，而不是跟着一起变）。
GRAPH_MODULE = "Mathlib.Combinatorics.SimpleGraph.Basic"

#: 必须读得到的四段（按"读到的意思"判：去掉强调符号与空白之后逐条核）。
_NEEDLES = (
    f"import {GRAPH_MODULE}",
    "第 ⑤ 步",
    "leantoolchain.mathlib_reading",
)

#: 提示词渲染的下限（反真空：空串或占位文本不许通过）。
_MIN_CHARS = 5000

_EMPHASIS = re.compile(r"[\s*`]+")


def _flat(text: str) -> str:
    return _EMPHASIS.sub("", str(text))


def _problems(text: str) -> list[str]:
    """① 的正文：渲染后的提示词里缺了哪一段（空清单 = 都在）。"""
    if len(str(text)) < _MIN_CHARS:
        return [f"渲染出来的提示词只有 {len(str(text))} 字（下限 {_MIN_CHARS}）⇒ "
                "这一条没有落脚点"]
    flat = _flat(text)
    return [f"读不到「{needle}」—— L 因此不知道图论该写哪条 import、"
            "也不知道可用性该信哪条读数（这一句必须进 specs/l.py 的 policy）"
            for needle in _NEEDLES if _flat(needle) not in flat]


def _render_l() -> str:
    return AP.system_prompt("L", registry=build_registry().registry)


# ============================================================ ① 正控


def test_the_l_prompt_names_the_graph_import_and_the_reading() -> None:
    """① L 的提示词里读得到那条 import 与那两条名字。"""
    text = _render_l()
    bad = _problems(text)
    assert bad == [], "\n".join(bad)


# ============================================================ ② 数据面


def test_the_named_import_and_function_really_exist() -> None:
    """② 提示词点的东西是真的：常量等于那条 import，读数函数真的在。"""
    assert LT.MATHLIB_GRAPH_MODULE == GRAPH_MODULE, (
        f"第 ⑤ 步探的模块是 {LT.MATHLIB_GRAPH_MODULE!r}，而提示词写的是 {GRAPH_MODULE!r} "
        "⇒ 两处说的不是同一条 import")
    assert callable(getattr(LT, "mathlib_reading", None)), (
        "`leantoolchain.mathlib_reading` 不存在 ⇒ 提示词把 L 指向一个不存在的读数")


# ============================================================ ③ 反真空


def test_anti_vacuum_removing_the_sentence_makes_it_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 反真空：把那一条 policy 拿掉 ⇒ ① 必红（判据压的正是那段话）。"""
    reg = build_registry().registry
    brief = AP.ROLE_BRIEFS["L"]
    kept = tuple(p for p in brief.policy if "SimpleGraph.Basic" not in str(p))
    assert kept != tuple(brief.policy), "夹具前提：policy 里真有一条写着那条 import"
    monkeypatch.setitem(AP.ROLE_BRIEFS, "L", dataclasses.replace(brief, policy=kept))
    bad = _problems(AP.system_prompt("L", registry=reg))
    assert bad, ("拿掉那一条之后判据仍然绿 ⇒ 它没有压在提示词上")
    assert any(GRAPH_MODULE in one for one in bad), bad
    # 负控的负控：放回去 ⇒ 重新成立
    monkeypatch.setitem(AP.ROLE_BRIEFS, "L", brief)
    assert _problems(AP.system_prompt("L", registry=reg)) == []


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
