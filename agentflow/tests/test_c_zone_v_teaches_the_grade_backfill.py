# -*- coding: utf-8 -*-
"""审 C 区（V / E / L 核验链）的缺教判据 ②：V 落签后「档位按通道重算」没教。

## 缺的是什么（2026-11-04 审 C 区）

`verifications._grade_recomputed_from_signature`（:2516）在**签落位的那一刻**按现行签把
`evidence_kind` 重算一遍，目标档**按通道**给（同文件 :2575-2583）：

- 通道是穷举程序（三段式证明栏 + 实验台账里那条 `is_signed_exhaustion` 的行）+ V 签
  ⇒ `proof`（`proof_review` 的定义是"V 逐行审过文字证明"，V 不能逐行走查一份程序）；
- 通道是文字证明 + V 签 ⇒ `proof_review`。

判据只有一处：`numericproof.find_signed_exhaustion_for_column`（审计期
`proof_stmt_without_formal_backing` 认的穷举背书也是它）。

而 V 的真实入口（`verifications.cold_start_prompt`，V 每次审阅读到的就是它）只写了
"你这一次的「成立」本身不构成 `proof`"，**没有**写这一签落地之后档位会怎么变 ——
于是"穷举那一篇落签就是 `proof`"这条 2026-11-04 的裁定在 V 的可见面上一个字节都没有
（`proof_review` / `按现行签重算` / `只升不降` 三个记号在冷启动提示词里 0 次）。

## 判据怎么判

只钉"这几句话在不在冷启动提示词里"，每条都带反真空（挖掉 ⇒ 同一个算式当场看见）。
"""
from __future__ import annotations

from agentflow import verifications as VR

PROOF = "程序：code/enum.py\n程序设计：按 4-子集编码枚举\n穷举论证：全部 2^36 个染色，无一遗漏"
STATEMENT = "对任意正整数 n，R(3,4)=9。"

#: 这一段必须点到的四个记号（前两个是受控取值，后两个是这条重算的性质）。
NEEDLES: tuple[str, ...] = ("按现行签重算", "proof_review", "通道", "只升不降")


def _cold() -> str:
    return VR.cold_start_prompt(STATEMENT, PROOF, readonly_facts="- 夹具")


def _problems(text: str) -> list[str]:
    bad: list[str] = []
    missing = [n for n in NEEDLES if n not in text]
    if missing:
        bad.append(f"V 的冷启动提示词里缺 {missing}")
    # 反方向那一半：这一段的强度说法还在（`test_lean_modes_matrix` 的 S3 钉的就是它），
    # 补教不许把"你这一签本身不构成 proof"顺手删掉 —— 两句说的是两件事：
    # 判断的强度 vs 命题行那一格的档位。
    if "不构成 `proof`" not in text:
        bad.append("「你这一次的『成立』本身不构成 `proof`」那一句被删掉了")
    return bad


def test_v_cold_start_teaches_the_grade_backfill_by_channel() -> None:
    """正控：V 的入口写清"落签后按现行签重算、穷举 ⇒ proof、文字 ⇒ proof_review"。"""
    text = _cold()
    assert len(text) > 500, len(text)      # 反真空①：真的是渲染出来的那一份
    bad = _problems(text)
    assert bad == [], "\n".join(bad)


def test_removing_the_sentence_makes_it_red() -> None:
    """反真空②：把"按现行签重算"挖掉 ⇒ 同一个算式当场报出来。"""
    text = _cold()
    stripped = text.replace("按现行签重算", "")
    assert stripped != text, "冷启动提示词里没有「按现行签重算」⇒ 探针打不中（判据是假绿）"
    hit = _problems(stripped)
    assert hit and any("按现行签重算" in x for x in hit), hit
