# -*- coding: utf-8 -*-
"""判据：M 的收工/收录手册要教三处 2026-11-04 的读数与一条被写错的送审路。

## 为什么是这三处（都是"机器有、提示词没有"）

| # | 那一格 | 真身 | 改前 M 面读得到什么 |
|---|---|---|---|
| 1 | `statements_unoptimized`（哪些证明还没洗过，按来源三档） | `closing.statements_unoptimized_reading`（进 `conductor.closing` 的 `readings`） | 0 处 —— M 只被教了 `statements_unsigned`，会把"未优化"读成"未签"或当成没有 |
| 2 | `deps_missing`（依赖面的三态） | `secretary._deps_missing_reading` → `agent_b/register_statement.py` 的返回值；拒收码 `dependency_section_missing` | 0 处 —— M 读不懂 B 的拒收，只会让 B "再试一次" |
| 3 | F / E 的稿到 B 的**第一来源**（D 的 `## 携带的证明手稿` → B 寻址） | `depsection.carried_manuscripts` / `SOURCE_CARRIED="carried_by_D"`（178 §五之二、2026-11-04「E 的穷举论证和 V 签也是委托入库」） | 手册的链在 `V` 之后直接写「B 收录证明」，没写 D 那一跳 |

第 4 条是同一节里一句**做不到的动作**：改前写「让 D / F 把那一份重新送 V 审」，
而 `D` 没有到 `V` 的边（`ALLOWED_EDGES["D"]` 不含 `V`）—— 照它派 D，只拿得到
`forbidden_edge`。

## 判据（正控 / 负控）

1. 三处读数的**名字与三档取值**都能在 M 的手册正文里读到；
2. 第 3 条另外要读到"兜底读盘只是降级 / 读不到清单是受控拒绝"这层语义；
3. 第 4 条：旧写法不在、新写法在；
4. 负控：把每一组针喂给一段缺它们的文本 ⇒ 同一个读法必须报缺（判据不是橡皮图章）。
"""
from __future__ import annotations

import re

from agentflow import agent_skills as AS
from agentflow import capabilities as C

#: 强调符号与空白：`**F 与 E**` 与 `F 与 E` 是同一句话（按"读出来的意思"判）。
_EMPHASIS = re.compile(r"[\s*`]+")

#: 手册里「收工」那一条。
_CLOSING_SLUG = "收工-门是读数不是判决"
#: 手册里「研究攻坚链」那一条。
_CHAIN_SLUG = "研究攻坚链-文献到收录证明"


def _flat(text: str) -> str:
    return _EMPHASIS.sub("", str(text))


def _body(slug: str) -> str:
    return next(s for s in AS.CATALOG["M"] if s.slug == slug).body


def _missing(text: str, needles: tuple[str, ...]) -> list[str]:
    flat = _flat(text)
    return [needle for needle in needles if _flat(needle) not in flat]


#: 收工手册必须读到的那一组（第 1 条）。
_UNOPTIMIZED: tuple[str, ...] = (
    "readings.statements_unoptimized",
    "unoptimized_from_f",
    "unoptimized_from_lit",
    "unoptimized_source_not_recorded",
    "不许折成 from_f",
    "checked=false",
    "读数、不拦门",
    "optimized[proof_no]",
)

#: 研究攻坚链必须读到的那一组（第 2、3 条 + 穷举那一路的档位）。
_CHAIN: tuple[str, ...] = (
    "deps_missing",
    "present",
    "missing",
    "not_applicable",
    "dependency_section_missing",
    "携带的证明手稿",
    "carried_by_D",
    "兜底读盘",
    "不许自己猜一个路径",
    # 2026-11-04「穷举程序 + V 签 ⇒ proof」：表里改前把收录档写死成 proof_review。
    "穷举程序 + V 签 ⇒ `proof`",
)

#: 第 4 条：改前那句（做不到的动作）与改后那句。
_OLD_SEND_BACK = "让 D / F 把那一份重新送 V 审"
_NEW_SEND_BACK = "由 D 让 F 把那一份重新送 V 审"


# ============================================================ 1 收工：未优化那一格
def test_the_closing_manual_teaches_the_unoptimized_reading() -> None:
    """M 的收工手册读得到 `statements_unoptimized` 的名字、三档与三条读法。"""
    bad = _missing(_body(_CLOSING_SLUG), _UNOPTIMIZED)
    assert bad == [], (
        "M 的收工手册读不到这几处（业主 2026-11-02 两阶段录入那一格："
        "`conductor.closing` 的 `readings.statements_unoptimized`）：\n  - " + "\n  - ".join(bad))


def test_the_unoptimized_reading_is_not_folded_into_signed() -> None:
    """它回答的不是"签了没有" —— 手册必须把两个问题分开写（否则又回到一个 0 两种读法）。"""
    body = _body(_CLOSING_SLUG)
    flat = _flat(body)
    assert "不是\"签了没有\"" in flat or "不是「签了没有」" in flat, (
        "手册没把 statements_unoptimized 与 statements_unsigned 分开 —— "
        "两个问题混成一个 0，M 就会把「还有证明要洗」读成「还有命题没签」")
    assert "statements_unsigned" in flat


# ============================================================ 2、3 收录：依赖面与携带单
def test_the_chain_manual_teaches_deps_missing_and_the_carried_sheet() -> None:
    """M 的研究攻坚链手册读得到依赖面三态与 D 的携带单那一跳。"""
    bad = _missing(_body(_CHAIN_SLUG), _CHAIN)
    assert bad == [], (
        "M 的研究攻坚链手册读不到这几处（依赖面三态 / D 的携带单是第一来源）：\n  - "
        + "\n  - ".join(bad))


def test_the_carried_sheet_is_not_written_as_a_direct_handoff() -> None:
    """兜底读盘只是降级：手册必须写明"清单读不到 ⇒ 受控拒绝、不许自己猜路径"。"""
    flat = _flat(_body(_CHAIN_SLUG))
    assert "受控拒绝" in flat, "手册没写清单地址读不到时的出路（受控拒绝）"
    assert "降级" in flat, "手册没写兜底读盘只是清单缺失时的降级"


def test_the_chain_manual_does_not_hardcode_proof_review_for_every_proof() -> None:
    """穷举程序 + V 签 ⇒ `proof`（2026-11-04 口径）：表里改前把收录档写死成 `proof_review`。"""
    body = _body(_CHAIN_SLUG)
    assert "`evidence_kind=proof_review`、`proof_text`" not in body, (
        "研究攻坚链的 B 收录行还把 evidence_kind 写死成 proof_review —— "
        "穷举题停在 proof_review 是错的终态（`verifications._exhaustion_proof_channel`）")
    assert "穷举程序 + V 签 ⇒ `proof`" in body, "手册读不到「穷举程序 + V 签 ⇒ proof」这一档"
    assert "proof_review" in body, "手册读不到文字证明那一档（proof_review）"


# ============================================================ 4 送审：D 没有到 V 的边
def test_the_resend_sentence_does_not_ask_d_to_send_to_v() -> None:
    """改前那句「让 D / F …重新送 V 审」把 D 写成了送审方 —— 而 D 没有到 V 的边。"""
    assert "V" not in C.ALLOWED_EDGES["D"], (
        "结构变了：D 现在有到 V 的边 ⇒ 这一条前提过期（改前那句就不再是做不到的动作）")
    body = _body(_CLOSING_SLUG)
    assert _OLD_SEND_BACK not in body, (
        f"手册里还写着「{_OLD_SEND_BACK}」—— D 没有到 V 的边，照它派 D 只会拿 forbidden_edge")
    assert _NEW_SEND_BACK in body, f"手册里读不到改后的写法「{_NEW_SEND_BACK}」"


# ============================================================ 负控
def test_the_criterion_bites_on_a_manual_without_them() -> None:
    """负控：缺这几处的文本喂进同一个读法 ⇒ 必须报缺（证明上面两条不是橡皮图章）。"""
    bare = "收工门看 conductor.closing 的读数；B 收完给一份回执。"
    assert _missing(bare, _UNOPTIMIZED), "缺 statements_unoptimized 的文本没被读出来"
    assert _missing(bare, _CHAIN), "缺 deps_missing / 携带单的文本没被读出来"
    assert _OLD_SEND_BACK not in bare, "负控前提：这段裸文本里没有旧句"
