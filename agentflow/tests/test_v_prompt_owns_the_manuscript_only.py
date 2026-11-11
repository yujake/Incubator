# -*- coding: utf-8 -*-
"""V 的冷启动题面只对手稿负责（2026-11-08，业主「V 只对手稿负责」）。

## 改前为什么红

`verifications.cold_start_prompt` 同时教了两句旧口径：

- 「签到位没有，看签文件 `out/vsigns/<sha>.json` 与五元位第 3 位」——V 早就不写
  `statements`（`specs/v.py` 的写集为空），第 3 位由 B 收录时翻；
- 「`verifications/<命题号>.jsonl` 那一行是它的正本」——签的真身是稿上的签块
  （与 `out/vsigns/` 侧文件），台账那一行只是 V 自己的审校记录。

同一份题面还把「等级按通道给」写成"你这一签落地之后、在册那一行现算"——那件事
发生在 B 收录那一刻，不在 V 这一侧。三处与「你只审手稿」互斥。

## 这条判据钉什么（存在性，不是词表阈值）

| # | 题面必须出现 | 反真空（挖掉/塞回就红） |
|---|---|---|
| a | 你只审手稿 / 签落在稿上 / 命题位、等级、第几份由 B 收录时决定 | 把「五元位第 3 位」「是它的正本」塞回同一份文本，判据必须当场报 |
| b | 两格读数、稿上已签、已入台账、`signed_pending_filing`、`signed_stale_in_ledger` | 把这一节删掉，同一个算式必须点名缺哪几个记号 |
| c | 「等级不归你算」且保留「按现行签现算等级」这一句强度（不把该教的一起删） | 删掉「B 收录这份稿」那一句，判据红 |

零模型调用、零网络。
"""
from __future__ import annotations

from agentflow import verifications as VR

PROOF = "1. 取 δ=ε：|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n2. 按定义即一致连续。"
STATEMENT = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"

#: 改前那两句错口径（判据的反真空探针用的就是它们）。
STALE_SIGN_BIT = "五元位第 3 位"
STALE_LEDGER_COPY = "`verifications/<命题号>.jsonl` 那一行是它的正本"

#: 「签落在稿上 / 只审手稿 / 归 B」这一半必须出现的句子（存在性）。
OWNERSHIP_NEEDLES: tuple[str, ...] = (
    "你只审手稿",
    "签落在稿上",
    # 2026-11-11（业主裁定：签跟着正文走）：签的身份是正文 sha + 稿路径；
    # 命题位 / 等级 / 路径号都归 B。改前这一句写的是「这是第几份证明」⇒ 已退役。
    "命题位（第 3 位）、等级、以及这份稿算哪条证明路径（`path_group`），都由 B 收录这份稿时",
    "签的身份是正文 sha + 稿路径",
)

#: 「两格读数与六档」这一半必须出现的记号。
TWO_CELL_NEEDLES: tuple[str, ...] = (
    "两格读数",
    "稿上已签",
    "已入台账",
    "signed_pending_filing",
    "signed_stale_in_ledger",
)


def _cold() -> str:
    return VR.cold_start_prompt(STATEMENT, PROOF, readonly_facts="- 手稿：夹具")


def _problems(text: str) -> list[str]:
    """这一份题面缺了哪些必需句 / 还留着哪些旧口径（空列表 = 全对）。"""
    bad: list[str] = []
    missing = [x for x in OWNERSHIP_NEEDLES if x not in text]
    if missing:
        bad.append(f"没有写清「V 只对手稿负责」：缺 {missing}")
    missing = [x for x in TWO_CELL_NEEDLES if x not in text]
    if missing:
        bad.append(f"没有教两格读数与六档：缺 {missing}")
    if STALE_SIGN_BIT in text:
        bad.append("还教 V 看「五元位第 3 位」（那是 B 收录时的事）")
    if STALE_LEDGER_COPY in text:
        bad.append(f"还把台账那一行叫「签的正本」：{STALE_LEDGER_COPY}（签在稿上）")
    if "等级不归你算" not in text:
        bad.append("没有说清等级不由 V 算")
    if "按现行签**现算等级**" not in text:
        bad.append("把「按现行签现算等级」那一条强度一起删掉了（该教的不许丢）")
    return bad


def test_a_the_cold_start_says_v_owns_the_manuscript_only() -> None:
    """a：只审手稿、签落在稿上、命题位/等级/第几份归 B —— 三样都在。"""
    text = _cold()
    assert len(text) > 500, len(text)          # 反真空：真的是渲染出来的那一份
    bad = _problems(text)
    assert bad == [], "\n".join(bad)


def test_a_putting_the_old_sentences_back_makes_it_red() -> None:
    """a 反真空：把改前那两句旧口径塞回同一份题面 ⇒ 同一个算式必须报出来。"""
    text = _cold()
    for stale in (STALE_SIGN_BIT, STALE_LEDGER_COPY):
        probe = text + "\n（补一句改前口径）" + stale
        hit = _problems(probe)
        assert hit and any(stale in x for x in hit), (stale, hit)
    assert STALE_SIGN_BIT not in text and STALE_LEDGER_COPY not in text


def test_b_two_cell_readings_and_six_states_are_taught() -> None:
    """b：两格读数与六档在题面上读得到，两个中间态各自点名。"""
    text = _cold()
    # 六档：两个中间态 + 其余四档都点名（不是只写一句「六档」）。
    for state in ("signed_pending_filing", "signed_stale_in_ledger", "filed",
                  "unsigned", "abandoned", "unreadable"):
        assert state in text, state
    # 两个中间态的含义要写清（"等 B 收录" / "不是签丢了"）。
    assert "等 B 收录" in text and "签丢了" in text, text


def test_b_removing_the_two_cell_section_makes_it_red() -> None:
    """b 反真空：把两格读数那一节整段挖掉 ⇒ 同一个算式必须点名缺哪几个记号。"""
    text = _cold()
    head = "\n## 你这一签之后：两格读数与六档\n"
    assert head in text, "两格读数那一节的标题不在了 ⇒ 探针打不中（判据是假绿）"
    stripped = text.split(head, 1)[0] + text.split(head, 1)[1].split("\n## ", 1)[0]
    hit = _problems(stripped)
    assert hit and any("两格读数" in x for x in hit), hit


def test_c_the_grade_ownership_moved_to_b_and_the_strength_sentence_survives() -> None:
    """c：等级归 B；「按现行签现算等级」这条强度说法没被顺手删掉。"""
    text = _cold()
    assert "B 收录这份稿" in text and "等级不归你算" in text, text
    assert "按现行签**现算等级**" in text, "V 该知道的等级口径被删掉了"
    assert "只升不降" in text, "等级只升不降这条读数被删掉了"
    # 反真空：把「B 收录这份稿」挖掉 ⇒ 「等级不归你算」这句话就没了主语。
    stripped = text.replace("B 收录这份稿", "")
    assert "B 收录这份稿" not in stripped
    assert _problems(stripped), "挖掉「B 收录这份稿」之后判据仍然全绿 ⇒ 它没在看"
