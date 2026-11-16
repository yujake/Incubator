# -*- coding: utf-8 -*-
"""判据：判决词「成立 / 有毛病」只有一个真身，另三处必须与它逐字一致。

## 这一份在治什么（2026-10-27，R-EVID 分块审查 ③；2026-11-16 按两态裁定改口径）

同一个词表在四个模块里各有一份落点：

| 落点 | 它管的是 | 词表 | 与真身的关系 |
|---|---|---|---|
| `verifications.VERDICTS` | V 的台账结论（`parse_verdict` 校验的就是它） | 两档（有毛病 / 成立），按"站不住→站得住"排 | 真身 |
| `verifications` 的历史值 | 已经取消的那一档（2026-11-16 裁定 ④：不立词表） | 无 | 不立常量；老台账里那四个字原样读、不产生轴 |
| `numericproof.THIRD_PARTY_VERDICT_OK` | 第三方签字那一档"签住了"的取值 | `"成立"` | 真身的最后一档（按位置引用，不抄字面量） |
| `exhaustionreport.VERDICT_OK` / `VERDICT_BAD` | 穷举型证据的会审机器读数 | 两个词 | 与真身逐字相同；缺材料走 `checked=False`（没有第三档） |
| `schema.REVIEW_VERDICTS` | `documents.review_verdict`（另一根轴：文档审校结论） | 两态 + 一个空串 | 与真身逐字相同；空串表示"还没审"。旧值另住 `REVIEW_LEGACY_VERDICTS` |

## 2026-11-01 / 2026-11-16：V 的结论收成两态，这一份跟着改口径（不是放宽）

业主逐字：「不应该有『看不出来』，『看不出来错』就是没毛病，没有『看不出来对』」。
2026-11-16 的裁定 ④ 进一步要求「把看不出来这档删干净」：于是
`exhaustionreport` 的 `VERDICT_UNKNOWN` 与 `verifications` 的 `LEGACY_VERDICTS`
这两个历史值词表都删掉了 —— 会审缺材料改由 `checked=False` 说，老台账行里的那四个字
只是一句历史陈述（读得出、不产生轴、不算票、不签）。这不是放宽：删掉的是"一种结论"，
没查成仍然是一个可见的、与两态分开的读数。

`schema.REVIEW_VERDICTS` 是 H 的文档审校轴（另一根轴、另一份台账），它的旧值仍按
「没查成」（`checked=False`）读 —— 那一格不改，因为它在 FC-27 禁改区里，且它本来就
不是 V 的结论。

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
    # 历史值只剩"可读的陈述"这一个身份（p247：不折档、不算票、不签）；
    # 2026-11-16 裁定 ④：它连词表常数也不立了（删干净，不是换个地方放着）。
    assert "看不出来" not in VR.VERDICTS, VR.VERDICTS
    assert not hasattr(VR, "LEGACY_VERDICTS"), (
        "`LEGACY_VERDICTS` 还在：那一档的词表必须删掉")
    historical = "看不出来"
    assert VR.read_verdict({"verdict": historical}) == historical, (
        "历史值被折成了某一态 ⇒ 判词又变成判据了（p247 要求原样读出）")
    assert VR.signs_bit3({"verdict": historical}, streak=3) is False, (
        "历史值没有秘书轴却签住了 ⇒ 字面又当成了 clean")


def test_the_same_axis_copies_are_word_for_word_identical() -> None:
    """同一根轴：（可产出的）两格逐字一致；会审不再有第三格。"""
    assert NP.THIRD_PARTY_VERDICT_OK == VR.VERDICTS[-1], (
        "numericproof 的'签住了'取值与真身不一致 —— 索引里那一行会被读成没签住")
    assert (ER.VERDICT_BAD, ER.VERDICT_OK) == VR.VERDICTS, (
        "exhaustionreport 的会审两态与真身不一致（顺序也要一致：它是按位置读的）")
    assert not hasattr(ER, "VERDICT_UNKNOWN"), (
        "会审的第三态常数还在：2026-11-16 裁定 ④ 要求把这一档删干净")


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
    assert S.REVIEW_LEGACY_VERDICTS == ("看不出来",), (
        "H 那一轴的历史值仍在读侧（它在 FC-27 禁改区里，本批只删 V 那一轴的词表）")
    assert "" in S.REVIEW_VERDICTS, "空串是'还没审'这一档，删掉它会把'没审'折成一档判决"
    assert len(S.REVIEW_VERDICTS) == len(VR.VERDICTS) + 1
    legacy = S.read_review_verdict({"review_verdict": S.REVIEW_LEGACY_VERDICTS[0]})
    assert legacy["verdict"] == "" and legacy["checked"] is False, legacy
    assert legacy["legacy"] is True, legacy


def test_parse_verdict_accepts_exactly_the_authority() -> None:
    """行为面（p247）：两态逐字认；历史值与「判不了」那一族原样认作陈述；不折档。"""
    import json as _json

    for word in VR.VERDICTS:
        payload = {"verdict": word, "defect_step": 1 if word == "有毛病" else None,
                   "findings": []}
        got = VR.parse_verdict(_json.dumps(payload, ensure_ascii=False))
        assert got["verdict"] == word
    # 历史值（2026-11-01 之前写下的）与「判不了」那一族：原样是陈述，不折成任何一态
    for word in ("看不出来", "判不了", "我无法判断", "拿不准", "大概成立"):
        got = VR.parse_verdict(_json.dumps({"verdict": word, "findings": []},
                                           ensure_ascii=False))
        assert got["verdict"] == word, got
        assert VR.secretary_axis(got) == "", "parse_verdict 自己产出了轴 ⇒ 字面又成判据了"
    # 结构不合法才是"没查成"（不是 JSON / 缺 verdict 字段）
    for bad in ("proved", "", "成立。"):
        with pytest.raises(VR.VerificationError):
            VR.parse_verdict("not-json-" + bad)


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
