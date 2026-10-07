# -*- coding: utf-8 -*-
"""L-05a：两处记账的已决定的分工（用判据把"理由"钉在源码里）。

## 分工是什么（A 的 L-05a 核查 + 主控裁定 (b)）

`llmseam._charge_ledger` 刻意不走 `modelcost.charge_reply`，理由逐字写在它的
docstring 里：`charge_reply` 拿 `reply` 自己重算 `usd_for(...)`（价与重试次数都从
`reply` 上取），而 `llmseam` 手上是 `SeamCall`（没有 `attempts` 字段）⇒ 走它会让
"网关重试过的调用"只按一次计价，与 `llm_call` 事件里的 `usd` 不等 —— 即
「同一笔钱两处两个数」。两处写的是同一本账（唯一写入口
`TokenMeter.charge_once` → `_row_for`），分歧只在"行构造"那一层。

主控裁定 (b)：保留这处分工 + 用判据钉住"理由必须在源码里"
（理由一丢，这处就从"已决定的分工"退化成静默分叉）。
裁定 (a)（把 `charge_reply` 的入参抽象成 `(usd_total, attempts, tokens…)`、
让两处共用一份行构造）记为将来若要统一行构造时的设计项，本轮不做。

## 判据的形状

两半：① 落点必须是同一个唯一写入口 `TokenMeter.charge_once`（"同一本账"）；
② 那段理由必须在 `_charge_ledger` 的源码里逐字存在（四段各查一次）。
反负控：把理由里的一段挖掉再喂给同一个判据，它必须被认出来（否则"理由还在"这句话
是真空的 —— 判据看不见缺失，等于没有判据）。
"""
from __future__ import annotations

import inspect

#: 理由必须逐字在源码里的四段（少一段 ⇒ 这处分工就成了静默分叉）。
REASON_SEGMENTS: tuple[str, ...] = (
    "为什么不用 `modelcost.charge_reply`",
    "它没有 `attempts` 字段",
    "同一笔钱两处两个数",
    "入账本身仍走同一条实现",
)

#: 账本的唯一写入口（两处记账都必须落在这里）。
SINGLE_WRITE_ENTRY = "TokenMeter.charge_once"


def _missing_reason(source: str) -> list[str]:
    """返回源码里缺了哪几段理由（空列表 = 四段都在）。"""
    return [seg for seg in REASON_SEGMENTS if seg not in source]


def _code_only(source: str) -> str:
    """去掉函数 docstring，只留代码体（用于"没调 charge_reply"这一类断言）。"""
    parts = source.split('"""')
    return parts[2] if len(parts) >= 3 else source


def test_charge_ledger_lands_on_the_single_write_entry_and_keeps_its_reason() -> None:
    """① 落点是同一个唯一写入口；② 那段理由逐字在源码里（缺一段就红）。"""
    from agentflow import llmseam as LS

    src = inspect.getsource(LS.LlmSeam._charge_ledger)
    assert "self.meter.charge_once(charge, idem_key=key)" in _code_only(src), (
        "`_charge_ledger` 的落点不再是同一个唯一写入口（`charge_once`）⇒ 两处记账分家了")
    assert "charge_reply" not in _code_only(src), (
        "`_charge_ledger` 直接调上了 `charge_reply` —— 那正是它刻意避开的那条路"
        "（会让重试过的调用只按一次计价）")
    assert _missing_reason(src) == [], (
        f"理由不见了：{_missing_reason(src)} ⇒ 这处分工从「已决定」退化成静默分叉；"
        "要改分工就同时改这条判据，别把理由删了了事")


def test_the_reason_check_actually_sees_a_missing_reason() -> None:
    """反负控：把理由里的一段挖掉 ⇒ 同一个判据必须认出来（否则它是空壳）。"""
    from agentflow import llmseam as LS

    src = inspect.getsource(LS.LlmSeam._charge_ledger)
    assert _missing_reason(src) == [], "基线本身就不全 ⇒ 上面那条判据没有分辨力"
    broken = src.replace(REASON_SEGMENTS[2], "（被挖掉的一段）")
    assert _missing_reason(broken) == [REASON_SEGMENTS[2]], _missing_reason(broken)


def test_both_charging_paths_land_on_the_same_single_write_entry() -> None:
    """两处写的是同一本账：`modelcost.charge_reply` 与 `llmseam._charge_ledger` 都落 `charge_once`。"""
    from agentflow import llmseam as LS
    from agentflow import modelcost as MC

    seam_src = _code_only(inspect.getsource(LS.LlmSeam._charge_ledger))
    reply_src = _code_only(inspect.getsource(MC.charge_reply))
    assert "charge_once" in seam_src, "llmseam 那条路的落点变了"
    assert "charge_once" in reply_src, (
        "`modelcost.charge_reply` 不再落 `charge_once` ⇒ 两处不再是同一本账，"
        "那条「已决定的分工」的前提（分歧只在行构造）不成立了")
    assert SINGLE_WRITE_ENTRY in inspect.getsource(MC), MC.__name__
