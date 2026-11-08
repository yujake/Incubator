# -*- coding: utf-8 -*-
"""B 的题面：从手稿读命题 / 两格读数与六档 / 判不了受控拒 / 短证明照样判。

## 这一组补的是什么（提示词-工具面一致性审计 ③④⑤⑥）

- ③ B 的可见面此前 0 处提到「两格读数（稿上已签 / 已入台账）」与
  `signed_pending_filing` / `signed_stale_in_ledger` 两个中间态；
- ④ D 只递指针时，B 的 policy 没有教「命题从 `## 命题` 读、证明从 `## 证明` 读」；
- ⑤ 概念同一性 / 同种证明两根轴的「判不了 ⇒ 受控拒」（`concept_identity_unjudged` /
  `proof_kind_unjudged`）在题面与说明里 0 处；
- ⑥「短证明不按字数预判死」此前只活在一条触发不到的拒信里，B 的题面没有正面表述。

## 判据（存在性 + 反真空）

| # | 题面必须出现 | 反真空 |
|---|---|---|
| a | 从手稿读：`## 命题` / `## 证明` / 只递指针 / D | 挖掉「## 命题」⇒ 红 |
| b | 两格读数 / 稿上已签 / 已入台账 / 两个中间态 / 六档 | 删掉那一句 ⇒ 红 |
| c | 两个受控拒码 + 「受控拒」+「改法」 | 挖掉任一码 ⇒ 红 |
| d | 短证明照样判 / 不按字数预判死 / 没有可比的文本 | 换成旧口径 ⇒ 红 |
| e | 拒信相关说明（`register_statement.statement_full`）也带两个码 + 改法 | 挖掉码 ⇒ 红 |

零模型调用、零网络。
"""
from __future__ import annotations

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow.tools import build_registry

#: ④ 从手稿读的两节与「只递指针」。
MANUSCRIPT_READING: tuple[str, ...] = (
    "## 命题", "## 证明", "只递指针", "D 只递手稿路径",
)
#: ③ 两格读数与六档。
TWO_CELL_NEEDLES: tuple[str, ...] = (
    "两格读数", "稿上已签", "已入台账", "signed_pending_filing",
    "signed_stale_in_ledger", "六档",
)
#: ⑤ 两根轴的受控拒与改法。
UNJUDGED_NEEDLES: tuple[str, ...] = (
    "concept_identity_unjudged", "proof_kind_unjudged", "受控拒", "改法",
)
#: ⑥ 短证明的正面表述。
SHORT_PROOF_NEEDLES: tuple[str, ...] = (
    "短证明照样判", "不按字数预判死", "没有可比的文本",
)


def _b_prompt() -> str:
    return AP.system_prompt("B", registry=build_registry().registry)


def _missing(text: str, needles: tuple[str, ...]) -> list[str]:
    return [n for n in needles if n not in text]


def _statement_full_desc() -> str:
    """`register_statement` 的拒信相关说明（收录那一刻模型看得到的那一格）。"""
    spec = next((a for a in C.CAPABILITIES.get("B", ())
                 if a.action == "register_statement"), None)
    assert spec is not None, "B 的动作表里没有 register_statement"
    props = ((spec.params or {}).get("properties") or {})
    return str((props.get("statement_full") or {}).get("description") or "")


def test_a_b_prompt_reads_the_proposition_and_proof_from_the_manuscript() -> None:
    """a：D 只递手稿路径时，命题与证明都从稿里读（两节都点名）。"""
    text = _b_prompt()
    assert len(text) > 5000, len(text)          # 反真空：真的是渲染出来的那一份
    missing = _missing(text, MANUSCRIPT_READING)
    assert not missing, f"B 的题面没有教从手稿读：缺 {missing}"


def test_a_removing_the_proposition_section_makes_it_red() -> None:
    """a 反真空：挖掉「## 命题」⇒ 同一个算式必须看见。"""
    text = _b_prompt()
    stripped = text.replace("## 命题", "")
    assert stripped != text, "B 的题面里没有 `## 命题` ⇒ 探针打不中（判据是假绿）"
    assert _missing(stripped, MANUSCRIPT_READING), "挖掉之后仍然全绿 ⇒ 判据没在看"


def test_b_b_prompt_teaches_the_two_cells_and_six_states() -> None:
    """b：两格读数 + 两个中间态 + 六档，都在 B 的可见面上。"""
    text = _b_prompt()
    missing = _missing(text, TWO_CELL_NEEDLES)
    assert not missing, f"B 的题面没有教两格读数/六档：缺 {missing}"
    for state in ("signed_pending_filing", "signed_stale_in_ledger"):
        assert state in text, state
    assert "等 B 收录" in text or "收录时认领" in text, "两个中间态没有写「等收录/认领」"


def test_b_removing_the_two_cell_sentence_makes_it_red() -> None:
    """b 反真空：删掉「两格读数」那一段 ⇒ 红。"""
    text = _b_prompt()
    head = "**签的两格读数（稿上已签 / 已入台账）与六档各有名字**"
    assert head in text, "两格读数那一条不在 ⇒ 探针打不中"
    start = text.find(head)
    end = text.find("\n", text.find("没查成」", start))
    stripped = text[:start] + text[end + 1:]
    assert _missing(stripped, TWO_CELL_NEEDLES), "删掉之后仍然全绿 ⇒ 判据没在看"


def test_c_b_prompt_says_unjudged_axes_are_controlled_refusals_with_a_fix() -> None:
    """c：两根轴判不了 ⇒ 受控拒，且给「改法」。"""
    text = _b_prompt()
    missing = _missing(text, UNJUDGED_NEEDLES)
    assert not missing, f"B 的题面没有教两根轴的受控拒与改法：缺 {missing}"


def test_c_removing_one_refusal_code_makes_it_red() -> None:
    """c 反真空：挖掉 `proof_kind_unjudged` ⇒ 红。"""
    text = _b_prompt()
    stripped = text.replace("proof_kind_unjudged", "")
    assert stripped != text, "B 的题面里没有 `proof_kind_unjudged` ⇒ 探针打不中"
    assert _missing(stripped, UNJUDGED_NEEDLES), "挖掉之后仍然全绿 ⇒ 判据没在看"


def test_d_b_prompt_says_a_short_proof_is_still_judged() -> None:
    """d：短证明照样判（正面表述），只有「没有可比的文本」才算判不了。"""
    text = _b_prompt()
    missing = _missing(text, SHORT_PROOF_NEEDLES)
    assert not missing, f"B 的题面没有正面写短证明：缺 {missing}"


def test_d_replacing_it_with_the_old_word_count_wording_makes_it_red() -> None:
    """d 反真空：换成旧的「按字数」口径 ⇒ 红。"""
    text = _b_prompt()
    old = text.replace("短证明照样判", "短证明先按字数判")
    assert old != text
    assert _missing(old, SHORT_PROOF_NEEDLES), "换了旧口径仍然全绿 ⇒ 判据没在看"


def test_e_the_refusal_description_carries_both_codes_and_the_fix() -> None:
    """e：拒信相关说明（收录那一格）也带两个码与改法。"""
    desc = _statement_full_desc()
    assert desc, "register_statement.statement_full 的说明是空的"
    missing = _missing(desc, ("concept_identity_unjudged", "proof_kind_unjudged", "改法"))
    assert not missing, f"拒信相关说明缺：{missing}（{desc}）"
    stripped = desc.replace("concept_identity_unjudged", "")
    assert _missing(stripped, ("concept_identity_unjudged",))
