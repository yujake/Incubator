# -*- coding: utf-8 -*-
"""判据：B 的 `evidence_kind` 说明只教「可观察状态」，不教 V 的内部连判机制（业主 2026-11-04 裁定 D）。

## 业主裁定（逐字）

    D 改，但不要按建议改：
       "就说拿到 V 签，不需要知道 V 内部会连续三次审"
       ⇒ 提示词只教可观察状态（拿到签 = 有签块/台账那一行 ⇒ 视为审过），
         不许写"连续三次干净成立才够"，也不许写"一次成立就够"；V 的内部连判机制不进提示词

## 改前是什么形态

`specs/b.py` 的 `evidence_kind` 说明教的是「有一次『成立』就该写 `proof_review`」，
而策略段（同一份提示词的 policy）教的是「连续 3 次干净成立才够」—— 两种相反的说法
同时摆在模型面前。两条都不可观察：模型既拿不到「第 3 转」，也不该被要求推断
V 内部还有几转。可观察的只有一件事：签到位了没有（`bits.reviewed` / 签块 /
台账那一行）。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | `evidence_kind` 说明里不再有「一次成立」与「连续三次 / 连续 3 次」两种说法 | 改前有「一次成立」那一句 |
| b | 同一段里有「V 签到位」这类可观察表述（并有「可观察状态」） | 改前没有 |
| c | 反真空：把「V 签到位」删掉 ⇒ 校验函数必须红 | 证明 b 的绿来自那句话，不是来自别的字 |
"""
from __future__ import annotations

import pathlib

SPEC_B = (pathlib.Path(__file__).resolve().parents[1]
          / "src" / "agentflow" / "specs" / "b.py")

#: 只圈 `evidence_kind` 这一格的说明（到下一格 `quote_verified` 之前）。
_START = '"evidence_kind": {"type": "string", "enum": list(S.EVIDENCE_KINDS),'
_END = '"quote_verified":'

OBSERVABLE = "V 签到位"
STATE_WORD = "可观察状态"

#: 不许出现的两套说法（V 内部机制）。
FORBIDDEN: tuple[str, ...] = ("一次成立", "连续三次", "连续 3 次", "连续3次")


def _cell(text: str) -> str:
    start = text.find(_START)
    assert start >= 0, "specs/b.py 里找不到 evidence_kind 那一格的声明"
    end = text.find(_END, start)
    assert end > start, "evidence_kind 之后找不到 quote_verified（这一格的边界读不出来）"
    return text[start:end]


def _problems(cell: str) -> list[str]:
    out: list[str] = []
    if OBSERVABLE not in cell:
        out.append(f"没有可观察表述「{OBSERVABLE}」")
    if STATE_WORD not in cell:
        out.append(f"没有点明「{STATE_WORD}」")
    for bad in FORBIDDEN:
        if bad in cell:
            out.append(f"仍在教 V 的内部机制：{bad!r}")
    if "内部过程" not in cell:
        out.append("没有写明「具体怎么给由框架判，你不必也不该推断内部过程」")
    return out


# ============================================================ a + b 同一段
def test_a_the_evidence_kind_note_teaches_the_observable_sign_only() -> None:
    """a+b：只有可观察说法；「一次成立」与「连续三次」两种都不在。"""
    cell = _cell(SPEC_B.read_text(encoding="utf-8"))
    problems = _problems(cell)
    assert problems == [], "evidence_kind 那一格还不合格：\n  - " + "\n  - ".join(problems)


# ============================================================ c 反真空
def test_b_removing_the_observable_sentence_turns_it_red() -> None:
    """c：把「V 签到位」删掉 ⇒ 校验函数必须红。"""
    cell = _cell(SPEC_B.read_text(encoding="utf-8"))
    assert _problems(cell) == []
    broken = cell.replace(OBSERVABLE, "")
    assert _problems(broken) != [], (
        "删掉「V 签到位」之后校验仍然绿 —— a/b 量的不是这句话")
