# -*- coding: utf-8 -*-
"""判据（178 §九 收口）：M 的提示词必须写明「M 没有 V 签的编辑权，也没有获取 V 签的义务」。

## 口径变更（业主 2026-11-02，逐字）

```text
既然B侧不收录F侧产出的异常无签证明，自然不会有无签证明被M看到，
所以M根本上没有V签的编辑权也没有获取V签的义务，无需唤起V
```

这条口径把 2026-10-24 那一版（「要 V 的签只能经 B 走两跳，直呼 V 会白丢一次」）
整条撤掉了：M 既不该去拿 V 签，也就不该知道"怎么绕过去拿"。留着的只有一条事实：
直呼 V 会被判 `forbidden_edge`、请求会转投回你自己 —— 它防的是模型"再试一次"，
不是教它走一条替代路线。

## 判据

| # | 判据 | 反真空 |
|---|---|---|
| ① | 渲染后的 M 提示词里读得到：没有 V 签的编辑权 / 没有获取义务 / 在册缺签让 B 处理 / F 产出无签先让 F 拿签 / `forbidden_edge` / 转投回你自己 | 少任何一条 ⇒ 红 |
| ② | 把边表临时放开 M→V、同时把那段拿掉 ⇒ ① 仍然红 | 证明它钉的是说明，不是能力 |

零模型调用（提示词是纯函数）。
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow.specs import builtin_specs
from agentflow.tools import build_registry

#: 强调符号与空白：`派 **D** 去核` 与 `派 D 去核` 是同一句话（按"读出来的意思"判）。
_EMPHASIS = re.compile(r"[\s*`]+")

#: 这几件事必须能被读出来（去掉强调与空白之后逐条核）：它们合起来才是"M 不该去拿 V 签"
#: 这条口径 —— 只写半句（例如只写"没有编辑权"）会让模型读成"我不能签，但我可以去要"。
_NEEDLES: tuple[str, ...] = (
    "没有V签的编辑权",     # 权限面
    "获取V签的义务",       # 义务面（业主同日收口的那半句）
    "命题已在册而缺V签",    # 在册那一档：B 的问题
    "让B处理",             # M 的动作就是让 B 办
    "经D让F先拿V签",       # F 产出那一档：经 D 让 F 先拿签
    "forbidden_edge",      # 直呼 V 被拒的理由码
    "转投回你自己",        # 被拒之后请求去哪了
)

#: 提示词渲染的下限（反真空：空串或占位文本不许通过）。
_MIN_CHARS = 5000


def _flat(text: str) -> str:
    """去掉强调符号与所有空白 —— 判"读到的意思"，不判排版。"""
    return _EMPHASIS.sub("", str(text))


def _problems(text: str) -> list[str]:
    """① 的正文：渲染后的提示词里缺了哪几个意思（空清单 = 都在）。"""
    if len(str(text)) < _MIN_CHARS:
        return [f"渲染出来的提示词只有 {len(str(text))} 字（下限 {_MIN_CHARS}）⇒ "
                "这一条没有落脚点（它不是在判一份真的提示词）"]
    flat = _flat(text)
    return [f"读不到「{needle}」这件事 —— M 因此不知道自己既没有 V 签的编辑权、也没有获取义务"
            f"（这一句必须逐字进 policy，见 specs/m.py）"
            for needle in _NEEDLES if _flat(needle) not in flat]


def _render_m() -> str:
    """真的渲染一遍主控的提示词（纯函数，零模型调用）。"""
    return AP.system_prompt("M", registry=build_registry().registry)


# ============================================================ ① 正控


def test_the_m_prompt_says_m_has_no_v_sign_duty() -> None:
    """① 主控的提示词里读得到那条口径的七个意思。"""
    text = _render_m()
    bad = _problems(text)
    assert bad == [], "\n".join(bad)
    # 边表那一半的事实照旧成立（它不是这条判据的依据，但两个读数不许互相打架）
    assert "V" not in builtin_specs()["M"].edges


# ============================================================ ② 反真空


def test_anti_vacuum_opening_the_v_edge_does_not_cure_the_criterion(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """② 反真空：边表放开 M→V ＋ 那段说明不在 ⇒ ① 仍然红（判的是说明，不是能力）。

    两步都要做，缺一步这条反真空就证明不了它自己：

    - 只放开边表：提示词里的字面量一个字都没变 ⇒ ① 照旧绿（那说明不了什么）；
    - 只拿掉句子：① 红是红，但那可能只是"我删了它"的同义反复。

    两步一起做，问的是那个真正的问题：能力变了之后，这条判据会不会跟着变绿。
    不会 —— 因为这句话是写进 policy 的一段说明。
    """
    reg = build_registry().registry
    brief = AP.ROLE_BRIEFS["M"]
    stripped = dataclasses.replace(
        brief, policy=tuple(p for p in brief.policy if "获取 V 签的义务" not in str(p)))
    assert "获取 V 签的义务" not in "\n".join(stripped.policy), (
        "夹具前提：这一条 policy 真的装着那句话（否则下面删的是空）")
    monkeypatch.setitem(AP.ROLE_BRIEFS, "M", stripped)
    # 能力面：把 M→V 临时加进权威边表
    monkeypatch.setitem(C.ALLOWED_EDGES, "M", C.ALLOWED_EDGES["M"] | {"V"})
    assert "V" in C.ALLOWED_EDGES["M"], "打桩没生效：边表里还是没有 M→V"

    text = AP.system_prompt("M", registry=reg)
    bad = _problems(text)
    assert bad, ("边表放开了 M→V、那段说明也不在了，判据却绿了 ⇒ 它判的是能力而不是说明"
                 "（这条判据该钉的是提示词里那段话，见 specs/m.py 的 policy）")
    assert any("获取V签的义务" in one for one in bad), bad

    # 负控的负控：把 brief 换回去（边表仍开着）⇒ 判据重新成立
    monkeypatch.setitem(AP.ROLE_BRIEFS, "M", brief)
    assert _problems(AP.system_prompt("M", registry=reg)) == []


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
