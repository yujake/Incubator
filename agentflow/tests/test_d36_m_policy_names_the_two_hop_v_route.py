# -*- coding: utf-8 -*-
"""判据（施工单 D-36）：M 的提示词必须写明「要 V 的签只能经 B，直呼 V 等于白丢一次」。

## 为什么这一条要进提示词

2026-10-24 的 r34b 现场：主控直呼 V，被 `forbidden_edge` 挡下，而框架对这一类被拒的
请求有一条固定处置 —— 转投回请求方自己（它自己不会去问 V，于是那一次就这么丢了）。
`specs/m.py` 的 policy 里当时只写了「V 不在你的出边里」与「要 V 签字只能走经 B 的
M→B→V」，没有写「直呼 V 会发生什么」。后果是可预期的：模型读到「这条路存在但你别走」，
下一次仍会去试那条直连边 —— 因为它不知道代价是一次白丢。

所以这一条判的是说明，不是能力：`M→V` 那条边本来就不在 `ALLOWED_EDGES` 里
（那一半由 `tests/test_v_signing_belongs_to_f_and_b.py` 与 `tests/test_policy.py` 守），
而"模型知不知道撞上去会白丢一次"没有任何一条判据看得见 —— 它此前只活在代码里。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | `system_prompt("M")` 里读得到这五个意思：V 的签 / 只能经 B / M→B→V 两跳 / forbidden_edge / 转投回你自己 / 白丢一次 | policy 里一句都没有 |
| ② | 反真空：把边表临时放开 M→V、同时把这两句拿掉 ⇒ ① 仍然红 | 证明这条判据钉的是文本，不是边表 |

② 是这道判据的自证：如果 ① 判的是"能力"（断言 V 不在 M 的出边里），那么把边表放开
就该让它变绿；它不会 —— 那条句子是写在 `specs/m.py` 里的字面量，边表放开一个字都没变。
`specs/m.py` 的注释里那些 `M→V`（撤边记录）因此不用被这条判据扫到：这里只读渲染后的
提示词。

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

#: 强调符号与空白：`派 B 去` 与 `派 B 去` 是同一句话（按"读出来的意思"判）。
_EMPHASIS = re.compile(r"[\s*`]+")

#: 这两句必须能被读出来的六个落点（去掉强调与空白之后逐条核）。
#: 拆成六个而不是一整句：语序可以改，意思不许缺 —— 缺哪个都会让模型漏掉一个事实
#: （缺"forbidden_edge"它不知道被拒的名字；缺"白丢一次"它不知道代价）。
_NEEDLES: tuple[str, ...] = (
    "要V的签",              # 有一个"V 的签"这件事
    "只能经B",              # 入口只有 B
    "M→B→V",               # 两跳那条路的名字
    "两跳",                # 它是两跳，不是直连
    "forbidden_edge",      # 直呼 V 被拒的那个理由码
    "转投回你自己",          # 被拒之后请求去哪了
    "白丢一次",              # 代价
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
    return [f"读不到「{needle}」这件事 —— 主控因此不知道要 V 的签该走哪条路、"
            f"也不知道直呼 V 的代价（这一句必须逐字进 policy，见 specs/m.py）"
            for needle in _NEEDLES if _flat(needle) not in flat]


def _render_m() -> str:
    """真的渲染一遍主控的提示词（纯函数，零模型调用）。"""
    return AP.system_prompt("M", registry=build_registry().registry)


# ============================================================ ① 正控


def test_the_m_prompt_says_the_v_signature_goes_through_b_and_costs_a_lost_round() -> None:
    """① 主控的提示词里读得到那六个意思。"""
    text = _render_m()
    bad = _problems(text)
    assert bad == [], "\n".join(bad)
    # 边表那一半的事实照旧成立（它不是这条判据的依据，但两个读数不许互相打架）
    assert "V" not in builtin_specs()["M"].edges


# ============================================================ ② 反真空


def test_anti_vacuum_opening_the_v_edge_does_not_cure_the_criterion(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """② 反真空：边表放开 M→V ＋ 那两句不在 ⇒ ① 仍然红（判的是说明，不是能力）。

    两步都要做，缺一步这条反真空就证明不了它自己：

    - 只放开边表：提示词里的字面量一个字都没变 ⇒ ① 照旧绿（那说明不了什么）；
    - 只拿掉句子：① 红是红，但那可能只是"我删了它"的同义反复。

    两步一起做，问的是那个真正的问题：能力变了之后，这条判据会不会跟着变绿。
    不会 —— 因为那条边本来就不在边表里，而这句话是写进 policy 的一段说明。
    """
    reg = build_registry().registry
    brief = AP.ROLE_BRIEFS["M"]
    stripped = dataclasses.replace(
        brief, policy=tuple(p for p in brief.policy if "白丢一次" not in str(p)))
    assert "白丢一次" not in "\n".join(stripped.policy), (
        "夹具前提：这一条 policy 真的装着那句话（否则下面删的是空）")
    monkeypatch.setitem(AP.ROLE_BRIEFS, "M", stripped)
    # 能力面：把 M→V 临时加进权威边表
    monkeypatch.setitem(C.ALLOWED_EDGES, "M", C.ALLOWED_EDGES["M"] | {"V"})
    assert "V" in C.ALLOWED_EDGES["M"], "打桩没生效：边表里还是没有 M→V"

    text = AP.system_prompt("M", registry=reg)
    bad = _problems(text)
    assert bad, ("边表放开了 M→V、那两句也不在了，判据却绿了 ⇒ 它判的是能力而不是说明"
                 "（这条判据该钉的是提示词里那段话，见 specs/m.py 的 policy）")
    assert any("要V的签" in one for one in bad), bad

    # 负控的负控：把 brief 换回去（边表仍开着）⇒ 判据重新成立
    monkeypatch.setitem(AP.ROLE_BRIEFS, "M", brief)
    assert _problems(AP.system_prompt("M", registry=reg)) == []


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
