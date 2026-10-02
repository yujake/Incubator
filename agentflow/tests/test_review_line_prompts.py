# -*- coding: utf-8 -*-
"""论文审阅线的六条提示词口径（`draft/37` §16 P2）——两面判据。

## 这一组守什么

P2 的改动全在提示词里（三条总原则的第①条：提示词优先，动作表尽量不动）。
提示词的判据天生容易写成"喊口号"（"提示词里要有 X"），所以这份文件的判据是两面的：

- 正面：这六条口径里每一条的可判定关键词必须真的出现在该角色的系统提示词里；
- 反面（反真空）：把同一个检查函数喂给一份被抽掉那句话的提示词，
  它必须点名报出来；喂给空串时，它必须把全部事实都报成缺失。

没有反面那两条，"提示词里有 X"与"检查函数永远返回空"长得一模一样 ——
而后者是本项目最忌的形态（假绿）。同样地，`PROMPT_VERSION` 必须随段一起前进：
段变了而版本没动，事后就分不清"这句话是哪个版本的提示词说的"。

## 为什么关键词取这些

取的是能被下游判定的那句话，不是整段原文：例如 A 的 `mismatch`（文献行的命中校验
第三态，§2 R1b）、`exact / partial / none`（文内定位三态，§2 R14）、
`none 不许交给 B`（R14 负控①的处置）；B 的 `statement_full` / `proof_text` /
`quote_reason` / `origin=own_result`（P1 那张表的四件套）；C 的 `submit_requests=true`
（缺口→检索请求的闭环）；D 的 `初步数学审阅` + `可挽救性评估`；H 的 `逐字一致` +
`evidence_kind=proof`（采信规则的两条）；M 的 `每一跳都要写清提示词` + `ask_user`。
"""
from __future__ import annotations

import pytest

from agentflow import agent_prompts as AP
from agentflow.tools import build_registry

#: `(角色, 必须出现的关键词, 它是哪一条口径 / 为什么这个词能判定它)`。
FACTS: tuple[tuple[str, str, str], ...] = (
    # ---- A：命中校验（§2 R1b，文献身份）+ 定位确认（§2 R14，文内存在）
    ("A", "命中校验", "R1b 这条口径本身被写进提示词（否则它只是登记册里的一句话）"),
    ("A", "mismatch", "R1b 的第三态：不是这一篇 ⇒ 落文献行的 matched，不许静默登记"),
    ("A", "exact / partial / none", "R14 文内定位的三态值域（与 R1b 的 mismatch 是两回事）"),
    ("A", "none 不许交给 B", "R14 负控①的处置：没定位到就不算找到"),
    ("A", "最接近的三段", "R14 负控②：partial/none 要列出可复核的候选"),
    ("A", "反证检索", "§9.4：被问「有没有人说它不成立」时的动作"),
    # ---- B：命题台账三件套（P1 的表 + 本轮的提示词）
    ("B", "statement_full", "含完整假设的正文 —— 缺了它 active 会被 schema 拒"),
    ("B", "proof_text", "逐字证明摘录 —— quote_verified 的比对对象"),
    ("B", "quote_reason", "三态纪律：不是 true 就必须写原因"),
    ("B", "origin=own_result", "改写必须显式标注为我们的重构，不许像原文"),
    # ---- C：缺口 → 检索请求（闭环）+ 依赖链读数
    ("C", "submit_requests=true", "缺口落成检索请求的开关（默认 false）"),
    ("C", "最短依赖链", "被问「这条结论靠什么站着」时的第一样读数"),
    ("C", "污染面", "第二样读数：它被推翻会连累哪些后代"),
    # ---- D：两条新职责
    ("D", "初步数学审阅", "职责①（对 B 的文字版证明）"),
    ("D", "可挽救性评估", "职责②：差什么 / 要多少预算 / 连累谁"),
    ("D", "真正承重的那一步", "审阅要给依据，而不是「我觉得不对」"),
    # ---- H：采信规则（不判数学那句话本来就在）
    ("H", "逐字一致", "采信规则的第一条（正文与 B 台账逐字一致）"),
    ("H", "evidence_kind=proof", "采信规则的第二条（E 的背书）"),
    ("H", "采信不了", "两条都不在时的唯一允许结论"),
    # ---- M：每跳写清提示词 + 目标变更必须问用户
    ("M", "每一跳都要写清提示词", "§15.3 的第一条判据（四样：谁/要什么/依据哪条验收/落到哪）"),
    ("M", "ask_user", "§15.3 的第二条：目标变更必须问用户"),
)


def _prompts() -> dict[str, str]:
    """六个角色这一次的系统提示词（同一个注册表 ⇒ 与真跑时同一份）。"""
    reg = build_registry().registry
    return {role: AP.system_prompt(role, registry=reg)
            for role in sorted({r for r, _n, _w in FACTS})}


def _missing(prompt: str, facts: tuple[tuple[str, str, str], ...]) -> list[str]:
    """这份提示词里缺了哪些关键词（空列表 = 全在）。"""
    return [f"{role}：缺「{needle}」（{why}）" for role, needle, why in facts
            if needle not in prompt]


def test_every_criterion_is_actually_in_the_prompt() -> None:
    """正面：六条口径的可判定关键词都真的进了对应角色的系统提示词。"""
    prompts = _prompts()
    assert set(prompts) == {"A", "B", "C", "D", "H", "M"}, sorted(prompts)
    bad: list[str] = []
    for role, prompt in sorted(prompts.items()):
        bad += _missing(prompt, tuple(f for f in FACTS if f[0] == role))
    assert not bad, "P2 的提示词口径没有全部落到提示词里：\n" + "\n".join(bad)


def test_the_criterion_judge_is_not_vacuous() -> None:
    """反面（反真空）：抽掉一句话必须被点名；空提示词必须把事实全部报缺。

    两条缺一不可：只做第一条，检查函数可能"在别的角色串里命中"而显得有效；
    只做第二条，它可能对任何非空串都返回空。
    """
    prompts = _prompts()
    a = prompts["A"]
    doctored = a.replace("命中校验", "")
    assert doctored != a, "夹具前提：A 的提示词里有「命中校验」可抽"
    hit = _missing(doctored, tuple(f for f in FACTS if f[0] == "A"))
    assert len(hit) == 1 and "命中校验" in hit[0], hit

    everything = _missing("", FACTS)
    assert len(everything) == len(FACTS), (len(everything), len(FACTS))


def test_the_prompt_version_moved_with_the_sections() -> None:
    """版本随段前进：段变了而版本没动，事后分不清这句话是哪个版本的提示词说的。

    判据取的是"必须 ≥ p24"而不是"必须 == p24"：版本还会再前进（P3/P4 会再改段），
    而这条判据要守的是"P2 这批口径属于 p24 及以后"，不是把版本钉死在今天。
    （2026-10-02：`== "p24"` 那半句与这段意图相反 —— 任何一次正当的段改动都会让它红，
    而红了之后人会去改数字而不是去看段。现在两处都只判下界；`p25` 是 §42 那一刀。）
    """
    num = int(AP.PROMPT_VERSION[1:])
    assert num >= 24, f"P2 的这批口径属于 p24 及以后，收到 {AP.PROMPT_VERSION!r}"


def test_the_facts_table_covers_exactly_the_six_roles_of_this_phase() -> None:
    """反真空：事实表必须刚好覆盖 P2 点名的六个角色（多一个少一个都要有人看见）。

    为什么值得单列一条：这张表是"P2 做了什么"的机器可读形态。少一个角色
    ⇒ 那个角色的口径没人守；多一个角色 ⇒ 有人顺手加了本阶段没要求的约束。
    """
    assert sorted({r for r, _n, _w in FACTS}) == ["A", "B", "C", "D", "H", "M"]
    assert len(FACTS) >= 20, f"事实只有 {len(FACTS)} 条 —— P2 的六条口径不止这些"
    dup = [n for n in {needle for _r, needle, _w in FACTS}
           if sum(1 for _r2, n2, _w2 in FACTS if n2 == n) > 1]
    assert not dup, f"事实表里有重复关键词（重复登记会让'都检查过了'虚高）：{dup}"


@pytest.mark.parametrize("role", ["A", "B", "C", "D", "H", "M"])
def test_the_role_brief_and_the_spec_are_the_same_object(role: str) -> None:
    """提示词的真身是 `ROLE_BRIEFS`；`specs/<角色>.py` 是它逐字镜像。

    这一条与 `tests/test_agent_spec_reconciliation.py` 的关系：那条判据比"六格全等"，
    这条只比本次改过的六个角色，并额外守一条结构性的要求 ——
    P2 的这批口径必须落在 `boundary` 或 `policy` 这两格里，
 不许只落在 `stance` 里：`stance` 受官能轻重（`FACULTY_EMPHASIS`）影响，
    某一档被改成 `denied` 时它就不再渲染，于是"口径还在"与"口径进不了提示词"会分家
    —— 而分家时上面那条"关键词必须出现"的判据才会红，红得比病因晚一步。
    （H 的 `policy` 本来就是空的：只读角色的政策写在边界里。这条判据不要求每格都非空。）
    """
    from agentflow.agentspec import builtin_registry

    brief = AP.ROLE_BRIEFS[role]
    spec_brief = builtin_registry().get(role).brief
    assert tuple(spec_brief.boundary) == tuple(brief.boundary)
    assert tuple(spec_brief.policy) == tuple(brief.policy)
    always_rendered = "\n".join(brief.boundary) + "\n" + "\n".join(brief.policy)
    loose = [f"{role}：「{needle}」只落在 stance 里（官能轻重一改就可能不再渲染）"
             for r, needle, _w in FACTS if r == role and needle not in always_rendered]
    assert not loose, "\n".join(loose)
    assert len(brief.boundary) >= 4, f"{role} 的 boundary 只有 {len(brief.boundary)} 条"
