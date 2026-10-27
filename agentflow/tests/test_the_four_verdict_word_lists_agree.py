# -*- coding: utf-8 -*-
"""判据：判决词「成立 / 有毛病 / 看不出来」只有一个真身，另三处必须与它逐字一致。

## 这一份在治什么（2026-10-27，R-EVID 分块审查 ③）

同一个词表在四个模块里各有一份落点：

| 落点 | 它管的是 | 词表 | 与真身的关系 |
|---|---|---|---|
| `verifications.VERDICTS` | V 的台账结论（`parse_verdict` 校验的就是它） | 三档，按"站不住→站得住"排 | 真身 |
| `numericproof.THIRD_PARTY_VERDICT_OK` | 第三方签字那一档"签住了"的取值 | `"成立"` | 真身的最后一档（按位置引用，不抄字面量） |
| `exhaustionreport.VERDICT_OK` / `VERDICT_BAD` / `VERDICT_UNKNOWN` | 穷举型证据的会审三态 | 三个词 | 与真身逐字相同 |
| `schema.REVIEW_VERDICTS` | `documents.review_verdict`（另一根轴：文档审校结论） | 三个词 + 一个空串 | 三个词逐字相同；空串表示"还没审" |

前三处是同一根轴（一次证明审校的结论），第四处是另一根轴但共用同一批词。
改前它们各是一份字面量，没有任何东西钉住"加一档时四处一起改" ⇒ 判决词加一档，
下游四处里只有一处会认。这一份把那件事变成可机械判的：逐字一致（`==`，
顺序也判），词表本身的形状（几档、谁在最后）单独钉一次。

## 为什么钉"顺序"而不只钉集合

`numericproof` 与 `exhaustionreport` 是按位置引用真身的（`[-1]` / `[0]` / `[1]`）。
集合相等但顺序变了，`[-1]` 就会指到另一个词 —— 那是一种"看起来一致、实际指错"的
漂移，比字面量分家更难发现。

## 这一份不改任何代码行为

它只读常量。要加第四档判决词时，这一份会先红，提醒把四处一起改。
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


def test_the_authority_is_the_three_verdict_words_in_order() -> None:
    """真身：三档、顺序 = 从"站不住"到"站得住"（另两处是按位置引用它的）。"""
    assert VR.VERDICTS == ("有毛病", "看不出来", "成立")
    assert VR.VERDICTS[-1] == "成立", "最后一档是'签住了'那一档，numericproof 按 -1 引用它"
    assert VR.VERDICTS[0] == "有毛病"
    assert VR.VERDICTS[1] == "看不出来"
    assert len(VR.VERDICTS) == 3


def test_the_same_axis_copies_are_word_for_word_identical() -> None:
    """同一根轴（一次证明审校的结论）：另两处必须与真身逐字一致。"""
    assert NP.THIRD_PARTY_VERDICT_OK == VR.VERDICTS[-1], (
        "numericproof 的'签住了'取值与真身不一致 —— 索引里那一行会被读成没签住")
    assert (ER.VERDICT_BAD, ER.VERDICT_UNKNOWN, ER.VERDICT_OK) == VR.VERDICTS, (
        "exhaustionreport 的会审三态与真身不一致（顺序也要一致：它是按位置读的）")


def test_schema_review_verdicts_is_another_axis_and_therefore_has_one_extra_cell() -> None:
    """`schema.REVIEW_VERDICTS` 是另一根轴：三个词逐字相同，多一个空串。

    空串不是第四档判决，是"这份文档还没有审校结论"（`documents.review_verdict` 的
    缺省）。所以这里只判"去掉空串之后与真身逐字相同 + 恰好多一格"，
    不判"两者相等" —— 那会把另一根轴折成本轴。
    """
    assert set(S.REVIEW_VERDICTS) - {""} == set(VR.VERDICTS), (
        f"文档审校结论的词表与真身分家了：{S.REVIEW_VERDICTS}")
    assert "" in S.REVIEW_VERDICTS, "空串是'还没审'这一档，删掉它会把'没审'折成一档判决"
    assert len(S.REVIEW_VERDICTS) == len(VR.VERDICTS) + 1


def test_parse_verdict_accepts_exactly_the_authority() -> None:
    """行为面：`parse_verdict` 认的判决词必须恰好是真身那三档。"""
    for word in VR.VERDICTS:
        # `有毛病` 必须指到那一步（`parse_verdict` 的另一条纪律），其余两档不需要。
        payload = {"verdict": word,
                   "defect_step": 1 if word == "有毛病" else None, "findings": []}
        got = VR.parse_verdict(__import__("json").dumps(payload, ensure_ascii=False))
        assert got["verdict"] == word
    # 词表之外的词一个都不许认（首尾空白是 `parse_verdict` 刻意容忍的，不算"之外的词"）。
    for bad in ("proved", "已完成", "", "成立。"):
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
