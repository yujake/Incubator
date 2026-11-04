# -*- coding: utf-8 -*-
"""判据：判决词「成立 / 有毛病」只有一个真身，另三处必须与它逐字一致。

## 这一份在治什么（2026-10-27，R-EVID 分块审查 ③；2026-11-01 按两态裁定改口径）

同一个词表在四个模块里各有一份落点：

| 落点 | 它管的是 | 词表 | 与真身的关系 |
|---|---|---|---|
| `verifications.VERDICTS` | V 的台账结论（`parse_verdict` 校验的就是它） | 两档（有毛病 / 成立），按"站不住→站得住"排 | 真身 |
| `verifications.LEGACY_VERDICTS` | 已经取消的那一档的历史值（2026-11-02：连历史兼容读也不留） | `看不出来` | 真身的历史值（读得出、按成立读并计票、写不出） |
| `numericproof.THIRD_PARTY_VERDICT_OK` | 第三方签字那一档"签住了"的取值 | `"成立"` | 真身的最后一档（按位置引用，不抄字面量） |
| `exhaustionreport.VERDICT_OK` / `VERDICT_BAD` / `VERDICT_UNKNOWN` | 穷举型证据的会审机器读数 | 三个词 | 前两个与真身逐字相同；`VERDICT_UNKNOWN` 是兼容读值（V 不再产出它，见下） |
| `schema.REVIEW_VERDICTS` | `documents.review_verdict`（另一根轴：文档审校结论） | 两态 + 一个空串 | 与真身逐字相同；空串表示"还没审"。2026-10-30 之后这一轴也不再收「看不出来」 |

## 2026-11-01：V 的结论收成两态，这一份跟着改口径（不是放宽）

业主逐字：「不应该有『看不出来』，『看不出来错』就是没毛病，没有『看不出来对』」。
于是真身只剩两格，`看不出来` 降到"已经取消的那一档的历史值"（`LEGACY_VERDICTS`）：
写不出；读侧按 :func:`verifications.read_verdict` 读成 `成立` 并计一票（2026-11-02 追加
裁定：那一档连历史兼容读也不留 —— 改前是"不算票、也不清零"）。而另外三处里：
- `numericproof` 按位置引用最后一格（`[-1]`）—— 仍是 `成立`，一个字没动；
- `exhaustionreport` 的三格是机械会审自己的读数（`review()` 的返回值），V 会在
  缺材料时把它读成"没查成"，所以那一格仍是 `看不出来` 这个词：它是另一份读数的
  兼容值，不是 V 的结论。这一条判据因此钉"它与历史值逐字相同"，而不是"它等于真身"；
- `schema.REVIEW_VERDICTS` 是 H 的文档审校轴（另一根轴、另一份台账）。它此前等于
  "两态 + 历史值"，因为 2026-11-01 那一批只裁 V 的结论词；2026-10-30 的业主裁定
  在 2026-11-04 落到这一轴上（施工单：「H 的『看不出来』不是第三态，必须从数据层
  删掉」）：于是它也只剩两态，旧值降到 `schema.REVIEW_LEGACY_VERDICTS`。
  这一轴与 V 轴的读法不同（这不是漂移，是两份读数）：V 的旧值按「成立（没找到
  缺陷）」读；H 的旧值按「没查成」（`checked=False`）读 —— H 的「看不出来」记的是
  "这一轮没查成"，不是"查了没找到缺陷"。判据在这里钉两件事：词表逐字相同、
  旧值是同一个词，但读侧各按各的口径。

## 为什么钉"顺序"而不只钉集合

`numericproof` 与 `exhaustionreport` 是按位置引用真身的（`[-1]` / `[0]` / `[1]`）。
集合相等但顺序变了，`[-1]` 就会指到另一个词 —— 那是一种"看起来一致、实际指错"的
漂移，比字面量分家更难发现。

## 这一份不改任何代码行为

它只读常量。要加第三档判决词时，这一份会先红，提醒把四处一起改（并想清"这一档
是 V 的结论，还是另一份读数"）。
"""
from __future__ import annotations

import ast
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402


def test_the_authority_is_the_two_verdict_words_in_order() -> None:
    """真身：两档、顺序 = 从"站不住"到"站得住"（另两处是按位置引用它的）。"""
    assert VR.VERDICTS == ("有毛病", "成立")
    assert VR.VERDICTS[-1] == "成立", "最后一档是'签住了'那一档，numericproof 按 -1 引用它"
    assert VR.VERDICTS[0] == "有毛病"
    assert len(VR.VERDICTS) == 2
    # 那一档已经取消：它只剩"历史值"这一个身份（读得出、按成立读并计票、写不出）
    assert "看不出来" not in VR.VERDICTS, VR.VERDICTS
    assert VR.LEGACY_VERDICTS == ("看不出来",), VR.LEGACY_VERDICTS
    assert VR.read_verdict({"verdict": VR.LEGACY_VERDICTS[0]}) == VR.VERDICTS[-1], (
        "历史值没有被读成真身的最后一格（成立）⇒ 那一档还在读侧冒充一格")


def test_the_same_axis_copies_are_word_for_word_identical() -> None:
    """同一根轴：（可产出的）两格逐字一致；会审那一格的历史值对得上 `LEGACY_VERDICTS`。"""
    assert NP.THIRD_PARTY_VERDICT_OK == VR.VERDICTS[-1], (
        "numericproof 的'签住了'取值与真身不一致 —— 索引里那一行会被读成没签住")
    assert (ER.VERDICT_BAD, ER.VERDICT_OK) == VR.VERDICTS, (
        "exhaustionreport 的会审两态与真身不一致（顺序也要一致：它是按位置读的）")
    assert ER.VERDICT_UNKNOWN == VR.LEGACY_VERDICTS[0], (
        "会审那一格的历史值必须与本模块的 `LEGACY_VERDICTS` 逐字相同 —— 那是另一份读数"
        "（机械会审的「缺材料」）：V 读到它就把这一格记成「没查成」，V 自己不产出这个词")
    assert all(word not in VR.VERDICTS for word in (ER.VERDICT_UNKNOWN,))


def test_schema_review_verdicts_is_another_axis_without_a_third_state() -> None:
    """`schema.REVIEW_VERDICTS` 是另一根轴：与真身逐字一致，另加一个空串。

    空串不是又一动判决，是"这份文档还没有审校结论"（`documents.review_verdict` 的
    缺省）。「看不出来」在 2026-10-30 的业主裁定之后不再是这一轴的取值，旧行里的
    那四个字降到 `schema.REVIEW_LEGACY_VERDICTS`，读侧按「没查成」读（`checked=False`）
    —— 不许折成「成立」，也不许折成「有毛病」。
    """
    assert set(S.REVIEW_VERDICTS) - {""} == set(VR.VERDICTS), (
        f"文档审校结论的词表与真身分家了：{S.REVIEW_VERDICTS}")
    assert "看不出来" not in S.REVIEW_VERDICTS, S.REVIEW_VERDICTS
    assert S.REVIEW_LEGACY_VERDICTS == VR.LEGACY_VERDICTS, (
        "两根轴的历史值必须是同一个词（V 的旧值按成立读、H 的旧值按没查成读，"
        f"但词本身要对得上）：{S.REVIEW_LEGACY_VERDICTS} vs {VR.LEGACY_VERDICTS}")
    assert "" in S.REVIEW_VERDICTS, "空串是'还没审'这一档，删掉它会把'没审'折成一档判决"
    assert len(S.REVIEW_VERDICTS) == len(VR.VERDICTS) + 1
    legacy = S.read_review_verdict({"review_verdict": S.REVIEW_LEGACY_VERDICTS[0]})
    assert legacy["verdict"] == "" and legacy["checked"] is False, legacy
    assert legacy["legacy"] is True, legacy


def test_parse_verdict_accepts_exactly_the_authority() -> None:
    """行为面：两态逐字认；历史那一格与"判不了"那一族折成 `成立`；其余一个都不认。"""
    for word in VR.VERDICTS:
        # `有毛病` 必须指到那一步（`parse_verdict` 的另一条纪律），另一档不需要。
        payload = {"verdict": word,
                   "defect_step": 1 if word == "有毛病" else None, "findings": []}
        got = VR.parse_verdict(__import__("json").dumps(payload, ensure_ascii=False))
        assert got["verdict"] == word
    # 历史那一格（2026-11-01 之前写下的）：折成 `成立`，原话进 `verdict_raw`
    folded = VR.parse_verdict('{"verdict": "看不出来", "why": "信息不足", "findings": []}')
    assert folded["verdict"] == "成立", folded
    assert folded["verdict_raw"] == "看不出来", folded
    assert "没有找到缺陷" in folded["why"], folded["why"]
    # 词表之外的词一个都不许认（首尾空白是 `parse_verdict` 刻意容忍的，不算"之外的词"）。
    for bad in ("proved", "已完成", "", "成立。", "大概成立"):
        with pytest.raises(VR.VerificationError):
            VR.parse_verdict('{"verdict": %s, "findings": []}'
                             % __import__("json").dumps(bad, ensure_ascii=False))


def test_no_fifth_module_defines_the_word_as_its_own_literal() -> None:
    """反真空（漂移探测）：`"成立"` 作为模块级字面量赋值只许出现在那两处。

    这一条抓的是"第五份副本"：判决词加一档、或有人在新模块里写一个
    `VERDICT_OK = "成立"`，这里会立刻红。它不读 `src/` 之外，也不算 `==` 之外的
    间接定义（例如在元组里包含它 —— 那种形态由上面那条逐字判据管）。
    """
    got: set[tuple[str, str]] = set()
    for path in sorted((_SRC / "agentflow").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if not isinstance(target, ast.Name):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            if value == VR.VERDICTS[-1]:
                got.add((path.name, target.id))
    assert got == {("numericproof.py", "THIRD_PARTY_VERDICT_OK"),
                   ("exhaustionreport.py", "VERDICT_OK")}, (
        f"判决词的真身之外多出/少了模块级字面量：{sorted(got)} —— "
        "新加的那一处必须改成按位置引用 `verifications.VERDICTS`")
