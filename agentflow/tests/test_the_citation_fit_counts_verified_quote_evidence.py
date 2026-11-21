# -*- coding: utf-8 -*-
"""判据：断言与它引的证据对不对口 —— 三条补丁（FITFIX 路）。

## 现场（lp-ball-14，已取证）

`projects/lp-ball-14/data/documents.json` 的 4 条红断言（claim-2 / 10 / 11 / 12）
都是「已回验的引文在正文里，判据却只比题名实词」：

- claim-2 引 `rel:000001`（Ball p.2 逐字命中、`quote_verified=true`、有 span），
  而正文是中文、lit 只是篇名指针 ⇒ 改前 mismatch；
- claim-11 引 `rel:000006`（Ball Theorem 4 的逐字引文），正文是中文转述 ⇒ 改前 mismatch；
- claim-10 / 12 是元陈述（"本库对 lit:000000 有记录 / 覆盖缺口"），lit 是被描述的对象、
  不是证据 ⇒ 改前 mismatch。

三条补丁（缺一不可）：

1. 引 `rel:` 且那条关系的引文已回验到可复核区间（`evidencebits.quote_state` 的
   `verbatim` / `semantic`）⇒ 这条引文算支持，不再漏掉最强的那份证据；
2. 中文正文 + 英文题名 ⇒ `unjudged`（实词代理在这种形态上必然失配），不许记 mismatch；
3. 元陈述（正文出现 `本库` / `本工作区` / `台账` / `记录` / `verifications`）⇒
   被引的 lit 号不参与题名实词判定，不许因为它被判 mismatch；`exp:` 与已回验 `rel:`
   的腿照判，所以元陈述也不会被读成"对上了"。

## 判据（先红后绿 + 反真空）

| # | 造什么 | 期望 |
|---|---|---|
| a | 中文正文引 `rel:`（逐字回验、有 span） | `fit`，`why` 空 |
| a2 | 引 `rel:` 但回验还没落到区间（`quote_verified=True` 无 span） | `unjudged`，不冒充支持 |
| b | 元陈述引 lit 号 | `unjudged`，`why` 点名元陈述 |
| b2 | 中文正文引英文题名 | `unjudged`，`why` 说语言不同 |
| c | 一篇真无关英文文献、无 rel 支撑 | 仍 `mismatch`（正控：判据没被关掉） |
| c2 | 英文断言与题名实词相交 | 仍 `fit`（正控：正常匹配没被误伤） |
| c3 | 英文里的普通名词 `verifications` | 不算记账词，真跑题仍 `mismatch`（正控：元陈述识别没放宽） |
| d | 反真空：把三条改动打桩回去 | a / b 的 fixture 必红成 `mismatch` |
| e | 收工门 `citation_fit` / 验收那一档 | 与单条判据同一读数（rel 腿真的接上了） |
| f | 写稿期 `doc_tools.citation_coverage` | 同一读数（写稿那一刻也看得见 rel 腿） |
"""
from __future__ import annotations

import pytest

from agentflow import closing as CL

TS = "2026-11-21T10:00:00+08:00"
LIT_ID = "000000"
TITLE = "Cube Slicing in R n"
SUMMARY = ("Every (n-1)-dimensional central section of the unit cube in R^n has volume "
           "at most 2*sqrt(2); bound attained by the coordinate-orthogonal section.")

#: 与 cube slicing 无关的英文断言（正控：判据没被关掉）。刻意避开 `every` 这类泛词 ——
#: `_FIT_STOPWORDS` 没把它当停用词，带上它就会「靠一个虚词对上」。
GIRTH = "A graph on n vertices has girth at least three."
#: 真讲 cube slicing 的英文断言（正控：正常匹配不许被误伤）。
CUBE = "Every central section of the unit cube has volume at most sqrt 2."
#: 中文正文 + 两个英文术语（Brunn / Minkowski）：改前靠题名实词比 ⇒ 必然 mismatch。
CHINESE = ("由 Brunn–Minkowski 不等式可知，固定法向的截面函数在 t 上凹，"
           "故非中心截面不超过中心截面。")
#: 元陈述：正文在讲本库的记录（lit 是被描述的对象，不是证据）。
META = "本库对 lit:000000 的两件承重结果有逐行审阅记录：verifications 下有所需 stmt 走查行。"

LITS = {LIT_ID: {"lit_id": LIT_ID, "title": TITLE, "summary": SUMMARY}}
#: 已回验的 relation：逐字通过，且有可复核的区间。
REL_VERIFIED = {LIT_ID: {"relation_id": LIT_ID, "lit_id": LIT_ID, "quote_verified": True,
                         "quote_mode": "verbatim", "quote_span": "p2:norm[100:241]"}}
#: 说了通过、但盘上拿不出区间 ⇒ `quote_state` 读成 no_evidence，不算支持。
REL_NO_SPAN = {LIT_ID: {"relation_id": LIT_ID, "lit_id": LIT_ID, "quote_verified": True,
                        "quote_mode": "", "quote_span": ""}}


def _fit(claim: dict, *, lits: dict | None = None, rels: dict | None = None) -> dict:
    """按生产判据判一条断言（改前 / 改后同一入口）。"""
    return CL.claim_evidence_fit(
        claim, exps={}, lits=LITS if lits is None else lits,
        rels=REL_VERIFIED if rels is None else rels)


# =================================================================== a 引对（rel 凭据）
def test_a_a_verified_quote_is_support_even_when_the_title_words_do_not_meet() -> None:
    """a：中文正文引一条逐字回验、有 span 的 rel ⇒ fit，why 空。

    改前：只比 lit 的题名实词（中文正文 vs 英文题名）⇒ mismatch。
    """
    one = _fit({"text": CHINESE, "citations": [f"rel:{LIT_ID}", f"lit:{LIT_ID}"]})
    assert one["verdict"] == "fit", one
    assert one["why"] == [], one
    # 只引 rel 也是同一读数（不必靠 lit 才判得了）。
    only_rel = _fit({"text": CHINESE, "citations": [f"rel:{LIT_ID}"]})
    assert only_rel["verdict"] == "fit", only_rel


def test_a2_a_relation_without_a_recheckable_span_does_not_count_as_support() -> None:
    """a2：`quote_verified=True` 但拿不出 span ⇒ 不算支持（三态：没核到区间不是通过）。"""
    one = _fit({"text": CHINESE, "citations": [f"rel:{LIT_ID}"]}, rels=REL_NO_SPAN)
    assert one["verdict"] == "unjudged", one
    assert any("可复核的区间" in w for w in one["why"]), one
    assert one["verdict"] != "fit", one


# =================================================================== b 元陈述 / 语言
def test_b_a_record_statement_citing_a_lit_is_unjudged_not_mismatch() -> None:
    """b：元陈述引 lit 号 ⇒ unjudged（lit 是被描述的对象），不许判 mismatch。"""
    one = _fit({"text": META, "citations": [f"lit:{LIT_ID}"]})
    assert one["verdict"] == "unjudged", one
    assert any("元陈述" in w for w in one["why"]), one
    assert one["verdict"] != "mismatch", one
    assert one["verdict"] != "fit", one


def test_b2_a_chinese_body_and_an_english_title_are_unjudged_not_mismatch() -> None:
    """b2：中文正文 + 英文题名 ⇒ unjudged（实词代理不适用），不许判 mismatch。"""
    one = _fit({"text": CHINESE, "citations": [f"lit:{LIT_ID}"]})
    assert one["verdict"] == "unjudged", one
    assert any("语言不同" in w for w in one["why"]), one
    assert one["verdict"] != "mismatch", one


# =================================================================== c 正控
def test_c_a_genuinely_unrelated_paper_still_reads_as_mismatch() -> None:
    """c（正控）：真无关的英文断言引同一篇 ⇒ 仍 mismatch（三条补丁没把判据关掉）。"""
    one = _fit({"text": GIRTH, "citations": [f"lit:{LIT_ID}"]})
    assert one["verdict"] == "mismatch", one
    assert any("没有交集" in w for w in one["why"]), one


def test_c2_an_english_statement_that_matches_still_reads_as_fit() -> None:
    """c2（正控）：英文断言与题名 / 摘要共有实词 ⇒ 仍 fit（正常匹配没被误伤）。"""
    one = _fit({"text": CUBE, "citations": [f"lit:{LIT_ID}"]})
    assert one["verdict"] == "fit", one


def test_c3_a_plain_english_verifications_noun_is_not_a_record_marker() -> None:
    """c3（正控）：英文里的普通名词 "verifications" 不是记账词，真跑题仍 mismatch。

    元陈述识别只认 `verifications` 当表 / 目录引用的形态（`verifications/` /
    `verifications 下`）。否则 "numerical verifications of ..." 这种普通英文句子
    会把一条真跑题的引用降成 `unjudged` —— 那就是放宽。
    """
    text = "We report numerical verifications of the girth problem."
    one = _fit({"text": text, "citations": [f"lit:{LIT_ID}"]})
    assert one["verdict"] == "mismatch", one
    assert CL._is_record_statement(text) is False, text


# =================================================================== d 反真空
def test_d_anti_vacuum_reverting_the_three_reads_reds_a_and_b(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """d：把三条改动打桩回去 ⇒ a / b 的 fixture 必红成 mismatch。

    打桩的是三条改动的入口，不是判据本身：只要哪一条没承重，对应的 fixture 就会
    退回改前读数（a / b 都是 mismatch）。
    """
    monkeypatch.setattr(CL, "_is_record_statement", lambda _text: False)
    monkeypatch.setattr(CL, "_cjk_dominant", lambda _text: False)
    monkeypatch.setattr(CL.EB, "quote_state", lambda _row: "unchecked")

    a = _fit({"text": CHINESE, "citations": [f"rel:{LIT_ID}", f"lit:{LIT_ID}"]})
    assert a["verdict"] == "mismatch", a
    b = _fit({"text": META, "citations": [f"lit:{LIT_ID}"]})
    assert b["verdict"] == "mismatch", b


# =================================================================== e 收工门那一档
class _RowsOnly:
    """只实现 `rows` 的假库（`citation_fit` 只读这四张表）。"""

    def __init__(self, rows: dict) -> None:
        self._rows = rows

    def rows(self, table: str) -> list:
        return list(self._rows.get(table, []))


def test_e_the_closing_readings_use_the_relation_leg(tmp_path) -> None:
    """e：`citation_fit` 与验收那一档读的是同一份判据（rel 腿真的接上了）。"""
    claim = {"claim_id": "claim-1", "evidence_kind": "heuristic", "section": "s",
             "text": CHINESE, "citations": [f"rel:{LIT_ID}", f"lit:{LIT_ID}"]}
    store = _RowsOnly({
        "documents": [{"doc_id": "000000", "claims": [claim]}],
        "literature": [LITS[LIT_ID]],
        "experiments": [],
        "relations": [REL_VERIFIED[LIT_ID]],
    })
    fit = CL.citation_fit(store)
    assert fit["fit"] == 1 and fit["mismatch"] == 0 and fit["judged"] == 1, fit
    got, detail = CL._leg_reading(store, "claim_evidence_fit_rows", tmp_path)
    assert got == 1, detail
    assert detail["implicit_min"] == 1, detail


# =================================================================== f 写稿期那一档
def test_f_the_write_time_coverage_uses_the_relation_leg() -> None:
    """f：`doc_tools.citation_coverage` 与收工门同一读数（写稿那一刻也看得见 rel 腿）。"""
    from agentflow.tools import doc_tools

    rows = {
        "literature": [dict(LITS[LIT_ID], processed=True, type="J", path=None, added_at=TS)],
        "relations": [REL_VERIFIED[LIT_ID]],
        "experiments": [], "statements": [], "eval_results": [],
    }
    cov = doc_tools.citation_coverage(
        lambda table: list(rows.get(table, [])),
        [{"claim_id": "claim-1", "text": CHINESE,
          "citations": [f"rel:{LIT_ID}", f"lit:{LIT_ID}"]}])
    assert cov["fit"]["fit"] == 1, cov["fit"]
    assert cov["misfit"] == [], cov["misfit"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
