# -*- coding: utf-8 -*-
"""审 C 区（V / E / L 核验链）的缺教判据 ①：E 的两档分野、签块读法、证明号。

## 缺的是什么（2026-11-04 审 C 区，逐条给代码真身）

实现里那两档是**分开**的，界在 `agent_e/run_experiment.py` 的 `wants_numeric_proof`
（:421 那一行）：

- **一般数值实验**：不写 `out/experiments/<号>/exhaustion.md`、不落
  `reports/e-proof-<号>.md`（:463-471 那一支把 report / manuscript 都留成空壳）、不派 V、
  没有签；`evidence_kind` 最多 `cross_check`（`numericproof.SUPPORTED_ONLY_KIND`）
  ⇒ 命题行的等级最多 `strong_conjecture`（`evidencebits.derive_grade` 只在
  `numeric` 位 verified 时给这一档）。
- **穷举证明**：三件套齐 + ②③ 落盘 + 手稿，V 三转「成立」之后由收方秘书落块；
  `evidence_kind` 按**通道**给 `proof`（**不是** `proof_review` —— V 不能逐行走查一份
  程序），真身是 `verifications._grade_recomputed_from_signature` 与
  `secretary._upgrade_evidence_kind` 两条落点共用的那条判据。

而 E 的可见面（`specs/e.py` 的 policy 第四段 + `skills/E/穷举证明-拿签与上报收养.md`）
只教了"穷举 → 派 V → 上报 D"这一条路，**三件事一个字都没有**：

1. 一般数值实验到不了 proof、最多 `strong_conjecture`（于是"我跑了实验"与"我有证明"
   在 E 眼里可能是一档）；
2. 稿上那一行签块是**九格**、`签名者` 是收方秘书（不是 V）、第 9 格 `手稿号` 与读侧的
   `identity_state` 三态（`vsigns.MANUSCRIPT_ID_STATES`：`resolved` / `unmatched` / `legacy`）；
3. 稿头 `- 证明号：` 省略即 `#p1`（`depsection.manuscript_proof_no` 读成 0 ⇒ canonical），
   **不许猜**一个号（`exhaustionreport.compose_manuscript` 的注释逐字：「不知道就省略 —
   — 不知道等于第 1 份，不许猜成别的号」）。

## 判据怎么判

只钉"这些话在不在 E 的手册正文里"（`agent_skills.skills_for("E")` 的 `body`）——
它不是文笔判据，所以每个 needle 都是实现里真存在的一个名字/一个数，改实现时它们会
跟着变红。每条都带反真空（挖掉一句 ⇒ 同一个算式必须当场看见）。
"""
from __future__ import annotations

from agentflow import agent_skills as AS

#: 两档分野那一段必须点到的名字（前两个是实现里的受控取值，后两个是"不派 / 不拿"这条边界）。
TIER_NEEDLES: tuple[str, ...] = ("strong_conjecture", "cross_check", "不派 V", "不拿签")
#: 穷举那一档必须写清"落 proof，不是 proof_review"。
PROOF_CHANNEL_NEEDLES: tuple[str, ...] = ("proof_review", "穷举", "按通道")
#: 签块的读法：九格的名字 + 第 9 格 + 三态。
SIGN_BLOCK_NEEDLES: tuple[str, ...] = ("签名者=secretary:E", "手稿号", "identity_state",
                                      "resolved", "legacy")
#: 证明号那一格。
PROOF_NO_NEEDLES: tuple[str, ...] = ("- 证明号：", "#p1", "省略")


def _e_manual() -> str:
    """E 的手册正文（`skills/E/` 落盘的那几份的正本）。"""
    return "\n".join(s.body for s in AS.skills_for("E"))


def _problems(text: str) -> list[str]:
    """缺哪几条（空清单 = 教齐了）。"""
    bad: list[str] = []
    for group, needles in (("两档分野", TIER_NEEDLES),
                           ("穷举那一档的落档", PROOF_CHANNEL_NEEDLES),
                           ("签块九格的读法", SIGN_BLOCK_NEEDLES),
                           ("稿头的证明号", PROOF_NO_NEEDLES)):
        missing = [n for n in needles if n not in text]
        if missing:
            bad.append(f"{group}：E 的手册里缺 {missing}")
    # 负控那一半：签块的署名不许写成 V（真身是收方秘书，`vsigns.land` 的 `by=`）
    if "签名者=V" in text or "签名者是 V" in text:
        bad.append("签块的署名写成了 V（真身是收方秘书 `secretary:E`）")
    return bad


def test_e_manual_teaches_the_two_tiers_and_how_to_read_the_sign_block() -> None:
    """正控：E 的手册正文教齐了四组句子。"""
    text = _e_manual()
    assert len(text) > 3000, len(text)          # 反真空①：真的是那一份手册
    bad = _problems(text)
    assert bad == [], "\n".join(bad)


def test_removing_one_sentence_makes_it_red() -> None:
    """反真空②：挖掉"两档分野"那一句 ⇒ 同一个算式当场报出来。"""
    text = _e_manual()
    stripped = text.replace("strong_conjecture", "")
    assert stripped != text, "手册里没有 `strong_conjecture` ⇒ 探针打不中（判据是假绿）"
    hit = _problems(stripped)
    assert hit and any("strong_conjecture" in x for x in hit), hit
