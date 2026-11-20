# -*- coding: utf-8 -*-
"""判据：B 的职责面是「登记快录 ＋ 二阶段逐个优化」，且 M 的派活时机接得上。

## 真源（`draft/179-证明优化两阶段录入口径（2026-11-02）.md`；`draft/191` §5）

- 第一阶段 = 机械录入：F / E 的证明原文 + 那一份已有的 V 签，几乎自动录入 —— 快录。
  只有「自己分析引文落稿」那一档要花力气。
- 第二阶段 = 逐个优化：洗稿 → 重拿 V 签 → 精准替换（旧正文进 `proof_history`）
  → 置逐份的 `optimized` 为 true。
- 业主 2026-11-02 逐字：「总之都要洗一遍。洗过的肯定能保证 V 签。所以二阶段只用看是否优化过」。
  ⇒ 第二阶段只看这一份优化过没有（逐份的 `optimized` 格），不再判签：
  `optimized=true` 就是「签已到手」的充分标记（写侧那条核仍是
  `evidencebits.optimized_signature`，本路一字不动）。
- 优化的对象是证明正文，不是命题措辞 —— 所以这里不写「润色 / 统一术语 / 与相邻命题去重」。

## 真身（三处，各只有一处）

- 职责档：`specs/b.py::SPEC.brief.duty` —— 它渲染成提示词第一行
  「你是 B 号角色，职责是：…」（`agent_prompts` 的 `AGENT_IDENTITY` 段）。
  「二阶段（逐个优化）」写在这里才算职责；只写在 policy 里是一句时机，不是一岗的活。
- 时机的另一面：`specs/m.py` 的 policy —— 「B 交回机械录入的回执 ⇒ 下一步派二阶段」。
  没有人接这一棒时，登记完的那一批会一直停在「机械录入」态。
- 语义链：`evidencebits.optimized_signature` —— `optimized=true` 仍然只认
  「这一份正文有签、且那一签盖的就是它」。本路只重写职责与时机，不动这条链。

## 现场（改前，真机 lp-ball-13）

13 条命题（7 概念 ＋ 6 猜想）：`bits.evidence.optimized_by_proof` 里一条 true 都没有
（6 条 `{"1": false}`、7 条缺格）；`tasks` 里 B 只跑过 1 趟（`t-000016`，done）。
登记有人做，二阶段一次都没发生 —— 而全文没有任何一处写「什么时候做二阶段」，
所以这不是某一次疏忽，是职责面缺了一档。

## 判据（a / a2 / a3 / b / c ＋ 反真空）

| 格 | 判据 |
|---|---|
| a | 渲染产物的「职责是：」那一行里读到「快录」与「二阶段（逐个优化）」两个锚点 |
| a2 | 同一个短语也在 `ROLE_BRIEFS["B"].duty` 里（是职责档，不是 policy 里那句时机） |
| a3 | 二阶段的形状写在 B 的可见面上：洗稿 / 重拿 V 签 / 精准替换 / `proof_history` / 逐份 `optimized_by_proof` |
| b | 渲染后的 M 提示词里有同一行把「B 交回登记」与「二阶段（逐个优化）」连起来的时机 |
| c | `optimized_signature` 语义链未动：没签 ⇒ 打不上 true（`no_sign`）；签盖的不是这一版 ⇒ `sha_mismatch`；签真盖住 ⇒ `true` |
| d | 反真空：把 a 那一段从渲染产物里抠掉 ⇒ 同一个检查器必红；把 b 那一句抠掉 ⇒ 同样必红 |

## 这一组不测什么

- 不测 `open_polish_copy` 本身能不能复制（那是 `tests/test_b_open_polish_copy.py`）；
- 不测 `optimized=true` 的写侧闸（那是 `tests/test_optimized_requires_a_sign.py`）——
  这里只用公开函数 `optimized_signature` 量「语义链还在」；
- 不测文案措辞好坏，只测那几个锚点落没落在职责档与时机会合处。
"""
from __future__ import annotations

import re

from agentflow import agent_prompts as AP
from agentflow import evidencebits as EB
from agentflow.tools import build_registry

#: 职责档里必须读到的两个锚点（业主口径：「登记是快录」「二阶段逐个优化」）。
DUTY_NEEDLES: tuple[str, ...] = ("快录", "二阶段（逐个优化）")

#: 二阶段的形状（真源那三步 + 两个落点；都要在 B 的可见面上）。
STAGE_TWO_SHAPE: tuple[str, ...] = ("洗稿", "重拿 V 签", "精准替换",
                                    "proof_history", "optimized_by_proof")

#: M 的派活时机：同一行里这两个锚点必须同时出现（「B 交回」在前、「二阶段」在后）。
M_CROSS_NEEDLE = "B 交回"
M_DUTY_NEEDLE = "二阶段（逐个优化）"

#: 「职责是：」那一行（它在 `AGENT_IDENTITY` 段，是渲染产物的第一行）。
_DUTY_LINE = re.compile(r"^你是 B 号角色，职责是：(.+)$", re.M)


def duty_line(text: str) -> str:
    """从渲染产物里取「职责是：」那一行（取不到给空串）。"""
    found = _DUTY_LINE.search(str(text))
    return found.group(1) if found else ""


def b_problems(text: str) -> list[str]:
    """a：B 的职责档里两个锚点齐不齐（空 = 齐）。"""
    line = duty_line(text)
    if not line:
        return ["渲染产物里读不到「你是 B 号角色，职责是：…」那一行 —— 职责档不在可见面上"]
    return [f"职责那一行缺 {needle!r}：{line}" for needle in DUTY_NEEDLES
            if needle not in line]


def shape_problems(text: str) -> list[str]:
    """a3：二阶段的形状齐不齐（空 = 齐）。"""
    return [f"B 的可见面上读不到二阶段的 {needle!r}" for needle in STAGE_TWO_SHAPE
            if needle not in str(text)]


def m_problems(text: str) -> list[str]:
    """b：M 的提示词里有没有「B 交回登记 ⇒ 下一步派二阶段」那一条时机（空 = 有）。"""
    hit = [line for line in str(text).splitlines()
           if M_CROSS_NEEDLE in line and M_DUTY_NEEDLE in line]
    if hit:
        return []
    loose = [line for line in str(text).splitlines() if M_DUTY_NEEDLE in line]
    if loose:
        return ["M 的提示词里提了二阶段，但没有一条把「B 交回登记」与它连成"
                f"同一步派活（读到 {len(loose)} 行、都不含 {M_CROSS_NEEDLE!r}）"]
    return [f"M 的提示词里没有派二阶段的时机（两个锚点 {M_CROSS_NEEDLE!r} / "
            f"{M_DUTY_NEEDLE!r} 一个都读不到）"]


def _prompt(role: str) -> str:
    registry = build_registry().registry
    return AP.system_prompt(role, registry=registry, task="把这一批登记完再洗一遍",
                            workspace_root="D:/x")


# ============================================================ a（渲染产物・职责档）
def test_a_the_rendered_duty_line_says_fast_intake_and_second_stage() -> None:
    """a：渲染产物「职责是：」那一行同时写着「快录」与「二阶段（逐个优化）」。"""
    text = _prompt("B")
    assert text, "B 的提示词渲染成空串 ⇒ 这一条没有落脚点"
    problems = b_problems(text)
    assert problems == [], "\n".join(problems)


# ============================================================ a2（是职责档，不是一句时机）
def test_a2_the_same_phrase_lives_in_the_duty_field() -> None:
    """a2：那两个锚点也在 `ROLE_BRIEFS["B"].duty` 里，不是只在 policy 里说一句时机。"""
    duty = str(AP.ROLE_BRIEFS["B"].duty)
    missing = [needle for needle in DUTY_NEEDLES if needle not in duty]
    assert missing == [], f"B 的 duty 字段缺 {missing}：{duty!r}"
    # 反面对照：duty 那一句不许被抄进 policy（第二份真身）。
    policy = "\n".join(str(x) for x in AP.ROLE_BRIEFS["B"].policy)
    assert duty not in policy, "duty 那一句被抄进了 policy（第二份真身）"


# ============================================================ a3（二阶段的形状）
def test_a3_the_shape_of_stage_two_is_on_b_visible_face() -> None:
    """a3：洗稿 / 重拿 V 签 / 精准替换 / `proof_history` / 逐份 optimized 都在 B 的面上。"""
    text = _prompt("B")
    problems = shape_problems(text)
    assert problems == [], "\n".join(problems)


# ============================================================ b（M 的派活时机）
def test_b_the_m_prompt_hands_the_batch_back_into_stage_two() -> None:
    """b：渲染后的 M 提示词里，有一条把「B 交回登记」与二阶段连起来的时机。"""
    text = _prompt("M")
    assert text, "M 的提示词渲染成空串 ⇒ 这一条没有落脚点"
    problems = m_problems(text)
    assert problems == [], "\n".join(problems)


# ============================================================ c（语义链没被改坏）
def test_c_optimized_true_still_needs_a_sign_covering_this_version() -> None:
    """c：`optimized_signature` 判据照旧 —— 没有签（或签的不是这一版）就打不上 true。"""
    text = "设 ℓ 是弦长函数，则椭圆不存在等弦点。"
    unsigned = EB.optimized_signature({}, 1, proof_text=text)
    assert unsigned["optimized"] is False, unsigned
    assert unsigned["optimized_blocked"] == EB.OPTIMIZED_BLOCKED_NO_SIGN, unsigned

    want = str(unsigned["proof_sha256"])
    assert want, "连这一版正文的 sha 都算不出来 ⇒ 这条判据量不到签与正文的对应关系"

    stale = EB.optimized_signature(
        {"bits": {"evidence": {"reviewed_by_proof": {"1": True},
                              "reviewed_sha_by_proof": {"1": "0" * 64}}}},
        1, proof_text=text)
    assert stale["optimized"] is False, stale
    assert stale["optimized_blocked"] == EB.OPTIMIZED_BLOCKED_SHA_MISMATCH, stale

    signed = EB.optimized_signature(
        {"bits": {"evidence": {"reviewed_by_proof": {"1": True},
                              "reviewed_sha_by_proof": {"1": want}}}},
        1, proof_text=text)
    assert signed["optimized"] is True, signed


# ============================================================ d（反真空）
def test_d_stubbing_the_duty_line_out_turns_a_red() -> None:
    """d-1：把「职责是：」那一行从渲染产物里抠掉 ⇒ a 的检查器必红。"""
    text = _prompt("B")
    stubbed = _DUTY_LINE.sub("你是 B 号角色。", text)
    assert stubbed != text, "夹具前提不成立：渲染产物里没有可打桩的「职责是：」那一行"
    assert duty_line(stubbed) == "", "打桩之后仍读得到职责那一行 ⇒ 打桩点没落在真身上"
    assert b_problems(stubbed), "把职责档整行抠掉之后检查器仍判绿 ⇒ a 是橡皮图章"


def test_d2_removing_the_phrase_alone_turns_a_red() -> None:
    """d-2：只把「二阶段（逐个优化）」从职责那一行里换掉 ⇒ a 必红（不是整行删才红）。"""
    text = _prompt("B")
    line = duty_line(text)
    assert line, "夹具前提不成立：读不到职责那一行"
    weakened = line.replace("二阶段（逐个优化）", "继续工作")
    assert weakened != line, "夹具前提不成立：职责那一行里没有可替换的锚点"
    stubbed = _DUTY_LINE.sub(lambda m: "你是 B 号角色，职责是：" + weakened, text)
    problems = b_problems(stubbed)
    assert any("二阶段（逐个优化）" in one for one in problems), problems


def test_d3_removing_the_dispatch_sentence_turns_b_red() -> None:
    """d-3：把 M 那一句时机从渲染产物里抠掉 ⇒ b 必红。"""
    text = _prompt("M")
    kept = [line for line in text.splitlines()
            if not (M_CROSS_NEEDLE in line and M_DUTY_NEEDLE in line)]
    stubbed = "\n".join(kept)
    assert stubbed != text, "夹具前提不存在：M 的提示词里没有可抠的那一条时机"
    assert m_problems(stubbed), "抠掉那一条时机之后检查器仍判绿 ⇒ b 是橡皮图章"


def test_d4_dropping_the_stage_two_shape_turns_a3_red() -> None:
    """d-4：把「精准替换」那一格抠掉 ⇒ a3 必红（形状不是靠一句"洗一遍"顶上的）。"""
    text = _prompt("B")
    stubbed = text.replace("精准替换", "换个说法")
    assert stubbed != text, "夹具前提不成立：B 的可见面上没有「精准替换」这个锚点"
    assert shape_problems(stubbed), "抠掉「精准替换」之后 a3 仍判绿 ⇒ 它没盯住那一步"
