# -*- coding: utf-8 -*-
"""审 C 区（V / E / L 核验链）的缺教判据 ③：L 的登记那一格（`record` → 第 4 位）没教。

## 缺的是什么（2026-11-04 审 C 区）

L 落 `experiments`（`method="formal"`）之后，是 **B 把它读成第 4 位**的：
`agent_b/register_statement.py` 的 `_bits_with_formal`（:545）调
`evidencebits.formal_ledger_reading`（:534 的注释逐字：「只认绑到这条命题的
`method="formal"` 行」），写出 `bits.formal`（二维 `{证明号: 状态}`）与
`bits.evidence.formal_by_proof`。所以「我这一行会被谁读、读成哪一位」是 L 的登记
动作的全部意义。

而 L 的手册（`skills/L/形式化-忠实复述B的证明链路.md`）只教了 `formalize` 与
`check_formal` 两件：`record` 这个名字在手册正文里 0 次，`method="formal"`、第 4 位、
`proof_no` 与「它不动 `statements`」也一个都没有。specs 的动作摘要里有（
`specs/l.py:187-194`），但手册才是"什么时候用它、它落到哪"的那一份。

## 判据怎么判

只钉"这几句话在不在 L 的手册正文里"，每条都带反真空（挖掉 ⇒ 同一个算式当场看见）。
"""
from __future__ import annotations

from agentflow import agent_skills as AS

#: 登记那一段必须点到的记号：动作名、它落的那张表/那个 method、它到的那一位、以及
#: "不动 statements"与证明号这半句（多证明时第 4 位是二维的）。
NEEDLES: tuple[str, ...] = ("L.record", 'method="formal"', "第 4 位", "不动",
                            "statements", "proof_no")


def _l_manual() -> str:
    """L 的手册正文（`skills/L/` 落盘的那几份的正本）。"""
    return "\n".join(s.body for s in AS.skills_for("L"))


def _problems(text: str) -> list[str]:
    bad: list[str] = []
    missing = [n for n in NEEDLES if n not in text]
    if missing:
        bad.append(f"L 的手册里缺 {missing}")
    return bad


def test_l_manual_teaches_the_record_row_and_the_fourth_bit() -> None:
    """正控：L 的手册写清「跑完 verified 之后用 record 落一行 method=\"formal\"」。"""
    text = _l_manual()
    assert len(text) > 2000, len(text)      # 反真空①：真的是那一份手册
    bad = _problems(text)
    assert bad == [], "\n".join(bad)


def test_removing_the_sentence_makes_it_red() -> None:
    """反真空②：把 `L.record` 那一段挖掉 ⇒ 同一个算式当场报出来。"""
    text = _l_manual()
    stripped = text.replace("L.record", "")
    assert stripped != text, "L 的手册里没有 `L.record` ⇒ 探针打不中（判据是假绿）"
    hit = _problems(stripped)
    assert hit and any("L.record" in x for x in hit), hit
