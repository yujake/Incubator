# -*- coding: utf-8 -*-
"""判据：名册补名那条口径的两处承诺，必须与实现说的是同一句话（`draft/160` 三-4）。

## 为什么要有这一条（两处 docstring 曾经与实现相反）

`draft/160` 一-e 查出来的：d9ebb7fe / 1cdacbf6 之后，两处 docstring 还写着"收口时必须
给得出名字"，而实现已经把补名关掉了 —— 于是 81 的 `t-000106`（真跑、`done/ok`、有产物）
永久无名，而读代码的人会以为它会被补上。文字的漂移没有判据看得见，直到业主
2026-11-01 裁定（丁案）把口径改成"没跑过的号不许补名、真跑过的补新名"，两处才对齐。

这一条把这个对齐钉住：两处（`Conductor._register_roster` 与 `Secretary.retire`）都必须
说清三件事 —— ① 没跑过的号永远没有名字；② 真跑过的号会在自愈时补一个从未用过的新名；
③ 那三格留痕（`named_after_run` / `requested_name` / `refusal_code`），且被拒的名字不复用。
同时钉住旧说法必须消失（"暂时没有名字" / "被拒的名字最终仍会出现一个新名字"）——
那句话回到源码里，就等于承诺又漂回去了。

## 判据与反真空

| 判据 | 它钉的是 | 负控 |
|---|---|---|
| ① `test_both_places_state_the_same_contract` | 两处源码都含那三件事的关键词、且不含旧说法 | 把两处换成旧文案的替身 ⇒ 同一个检查函数必报 |
| ② `test_the_contract_check_is_not_vacuous` | 空串 / 只有一半的文案必须被报出来 | — |
"""
from __future__ import annotations

import inspect
from typing import Iterable

import pytest

from agentflow.conductor import Conductor
from agentflow.secretary import Secretary

#: 两处都必须出现的词：没跑过 / 永远没有名字 / 真跑过 / 从未用过的新名 / 三格留痕 / 不复用。
_REQUIRED = ("没跑过", "永远没有名字", "真跑", "从未", "named_after_run",
             "requested_name", "refusal_code", "不复用")

#: 旧文案（与实现相反的那两句）：回到源码里就是漂回去了。
_FORBIDDEN = ("暂时没有名字", "被拒的名字最终仍会出现一个新名字")


def _problems(*, blocks: Iterable[str]) -> list[str]:
    """两处源码里的承诺文案与实现对不对得上（空列表 = 对得上）。"""
    text = "\n".join(blocks)
    bad: list[str] = []
    for need in _REQUIRED:
        if need not in text:
            bad.append(f"两处承诺里缺了「{need}」⇒ 读者读不出这条口径")
    for old in _FORBIDDEN:
        if old in text:
            bad.append(f"旧文案「{old}」还在 ⇒ 承诺与实现相反（d9ebb7fe / 1cdacbf6 之后它已不成立）")
    if "没跑过" in text and "真跑" in text and text.index("没跑过") > text.index("真跑"):
        bad.append("「真跑过」写在「没跑过」之前 ⇒ 读者会先读到补名、后读到例外，"
                   "口径的主次反了")
    return bad


def test_both_places_state_the_same_contract() -> None:
    """① 两处源码（`_register_roster` 与 `Secretary.retire`）都含那三件事、且无旧说法。"""
    conductor_src = inspect.getsource(Conductor._register_roster)
    secretary_src = inspect.getsource(Secretary.retire)
    # 前提：这两段确实是"那两处"（否则等于对空字符串做断言）
    assert "名册" in conductor_src and "roster_repair" in conductor_src, conductor_src[:200]
    assert "roster_repair" in secretary_src and "retire" in secretary_src, secretary_src[:200]
    bad = _problems(blocks=[conductor_src, secretary_src])
    assert bad == [], "\n".join(bad)


def test_the_contract_check_is_not_vacuous() -> None:
    """② 反真空：空串、只有一半的文案、旧文案，都必须被同一个检查函数报出来。"""
    assert _problems(blocks=["", ""]), "空串竟然通过了 ⇒ 这条判据恒真"
    half = "没跑过的号永远没有名字"
    assert _problems(blocks=[half, half]), "只有前半句也通过了 ⇒ 三格留痕没被要求"
    old = ("没跑过的号永远没有名字；真跑过的号会补一个从未用过的新名字；"
           "named_after_run / requested_name / refusal_code；被拒的那个不复用。" + _FORBIDDEN[0])
    assert _problems(blocks=[old]), "旧文案没有被报出来 ⇒ 判据抓不住漂回去"
    good = ("没跑过的号永远没有名字；真跑过的号会补一个从未用过的新名字；"
            "add 行带 named_after_run / requested_name / refusal_code；被拒的那个不复用。")
    assert _problems(blocks=[good, good]) == []
