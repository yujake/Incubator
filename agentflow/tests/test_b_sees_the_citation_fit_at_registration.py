# -*- coding: utf-8 -*-
"""判据：B 登记命题时，回执上要能看见「这条命题的正文与它的出处对不对得上」（BQUOTE 路）。

## 现场（lp-ball-14，已取证）

`projects/lp-ball-14/data/documents.json` 的 4 条断言（claim-2 / 10 / 11 / 12）都把
`lit:000000`（Ball 1986《Cube Slicing in R n》）列进 `citations`，而收工门的
`closing.claim_evidence_fit` 判它们「断言的实词与被引文献的题名 / 摘要没有交集」。
四条的实际落点（`rel:000001` / `rel:000004` / `rel:000006` / `rel:000008`）逐字回验
是通过的：引文没有跑题，是命题 / 断言的写法与文献题名不在同一套术语里。

那一条判据只在 `closing`（收工门）与 `doc_tools.citation_coverage`（写稿那一刻）上
现算，B 登记命题那一刻看不到 —— 于是「一批命题都挂同一篇泛论」这件事要到收工门才现形，
那时上游已经改不动。本文件守的就是这一格：登记回执带 `citation_fit`。

## 判据（红 → 绿）

| # | 造什么 | 期望 | 改前为什么红 |
|---|---|---|---|
| a | 断言讲 cube / section / volume，引《Cube Slicing in R n》 | 回执 `citation_fit.verdict == fit`、`why` 空 | 改前回执上没有 `citation_fit` 这一格 |
| b | 断言讲图的围长，引《Cube Slicing in R n》 | `verdict == mismatch`，`why` 点名 `lit:000000` 与「没有交集」，`note` 说「跑题」 | 同上（改前没有这一格） |
| c | 中文断言的实词太少 | `verdict == unjudged` + `why` 说「实词特征」；`note` 写「判不了」 | 同上 |
| d | 自产命题（没有 `source_lit_id`） | `verdict == not_applicable`、`lit_id` 空 | 同上；这一条防「没出处也判成对上了」 |
| e | 反真空①：把 `claim_evidence_fit` 打桩成恒 fit | b 的 fixture 变成 `fit`（所以 b 的红是那条判据给的） | — |
| e2 | 反真空②：把它打桩成恒 mismatch | a 的 fixture 变成 `mismatch`（所以 a 的绿也是它给的） | — |

判据本体只有一处：`closing.claim_evidence_fit`（收工门 / 写稿期 / 登记回执三处共用，
`R003`）。本文件不另写一份交集，只量「登记那一刻有没有把它喂给回执」。
"""
from __future__ import annotations

import pytest

from conftest import b_form_gate_ok, sign_before_registration

from agentflow import closing as CL
from agentflow.agent_b import AgentB
from agentflow.store import Store

TS = "2026-11-21T10:00:00+08:00"
LIT = "000000"
TITLE = "Cube Slicing in R n"
SUMMARY = ("Every (n-1)-dimensional central section of the unit cube in R^n has volume "
           "at most 2*sqrt(2); bound attained by the coordinate-orthogonal section.")

#: 一篇与 cube slicing 无关的断言（图论围长）。英文实词与文献题名 / 摘要零交集。
#: 措辞刻意避开 `every` / `volume` 这类泛词：`_FIT_STOPWORDS` 没把 `every` 当停用词，
#: 而摘要有它 —— 带上它就会「靠一个虚词对上」，那就不是在造「无关」的现场。
GIRTH = "A graph on n vertices has girth at least three."

#: 一篇真讲 cube slicing 的断言（与题名 / 摘要共有 cube / section / volume 等实词）。
CUBE = "Every central section of the unit cube has volume at most sqrt 2."

#: 中文转述：一条中文断言的英文实词不足两个 ⇒ 判据记 unjudged（不是 fit）。
CHINESE = ("设 Q_n 为中心单位立方体，H 为 R^n 的一个 (n-1) 维子空间，"
           "则 H ∩ Q_n 的 (n-1) 维体积至少为 1。")

PROOF = ("证明（逐字摘录）：The central section area is at most 2*sqrt(2); equality holds "
         "when the section contains an (n-2)-dimensional face.")


def _lit(store: Store, *, title: str = TITLE, summary: str = SUMMARY) -> None:
    """播种一条文献行（题录 + 摘要；判据读的就是这两格）。"""
    with store.tx("literature", actor="test", note="seed") as tx:
        tx.upsert("literature", {"lit_id": LIT, "title": title, "type": "J",
                                 "summary": summary, "path": None, "processed": True,
                                 "added_at": TS}, note="seed")


def _b(store: Store) -> AgentB:
    """真 B 与真秘书；只把命题形态那一问钉成已过（与本仓既有登记判据同一取舍）。"""
    return b_form_gate_ok(AgentB(store, extractor=None, extract_text=None))


def _cited(statement: str) -> dict:
    """一条文献侧命题的登记参数（`origin=external_lit` + 逐字引文）。"""
    return dict(statement_full=statement, origin="external_lit", kind="theorem",
                label="文献定理", proof_text=PROOF, source_lit_id=LIT,
                page_range={"start": 2, "end": 2}, quote_verified=True,
                quote_reason="逐字比对通过（page 2）", evidence_kind="cross_check")


def _own(statement: str) -> dict:
    """一条自产命题（没有 `source_lit_id`）—— citation_fit 对它是 not_applicable。"""
    return dict(statement_full=statement, origin="own_result", kind="conjecture",
                label="自产猜想", proof_text="", doc_id="000000",
                line_range={"label": "manuscripts/handoffs.jsonl#0042"},
                quote_verified=None, quote_reason="own_result：我方还没证，留着当猜想",
                evidence_kind="heuristic")


def _register(store: Store, payload: dict) -> dict:
    sign_before_registration(store.root, proof_text=PROOF)
    out = _b(store).register_statement(**payload)
    assert out.get("ok") is True, out
    return out


def _fit(out: dict) -> dict:
    got = out.get("citation_fit")
    assert isinstance(got, dict), (
        f"登记回执上没有 citation_fit 这一格（改前就是这一形态）：{sorted(out)}")
    return dict(got)


# =================================================================== a 引对了
def test_a_a_statement_that_matches_its_source_is_not_named(store) -> None:
    """a：断言与出处共有实词 ⇒ `fit`，`why` 空（对上了就不点名）。"""
    _lit(store)
    out = _register(store, _cited(CUBE))
    fit = _fit(out)
    assert fit.get("verdict") == "fit", fit
    assert fit.get("lit_id") == LIT, fit
    assert fit.get("why") == [], fit
    assert "跑题" not in str(fit.get("note") or ""), fit
    assert fit.get("checked") is True, fit


# =================================================================== b 引错了
def test_b_a_statement_about_girth_citing_cube_slicing_is_named(store) -> None:
    """b：断言讲图的围长、引的是 cube slicing ⇒ `mismatch`，回执逐字点名。"""
    _lit(store)
    out = _register(store, _cited(GIRTH))
    fit = _fit(out)
    assert fit.get("verdict") == "mismatch", fit
    why = " ".join(str(x) for x in (fit.get("why") or []))
    assert f"lit:{LIT}" in why, why
    assert TITLE in why, why
    assert "没有交集" in why, why
    assert "跑题" in str(fit.get("note") or ""), fit
    # 反向：这一条不许被读成 fit。
    assert fit.get("verdict") != "fit", fit


# =================================================================== c 判不了
def test_c_a_chinese_statement_is_unjudged_not_fit(store) -> None:
    """c：中文断言没有可判的英文实词 ⇒ `unjudged`（判不了，不是对上了）。"""
    _lit(store)
    out = _register(store, _cited(CHINESE))
    fit = _fit(out)
    assert fit.get("verdict") == "unjudged", fit
    why = " ".join(str(x) for x in (fit.get("why") or []))
    assert "实词特征" in why, why
    assert "判不了" in str(fit.get("note") or ""), fit
    assert fit.get("verdict") != "fit", fit


# =================================================================== d 没出处
def test_d_a_statement_without_a_literature_source_is_not_applicable(store) -> None:
    """d：自产命题没有 `source_lit_id` ⇒ `not_applicable`（这一格不适用，不是对上了）。"""
    out = _register(store, _own("设 n>=3，则 n^2+n 是偶数。"))
    fit = _fit(out)
    assert fit.get("verdict") == "not_applicable", fit
    assert fit.get("lit_id") == "", fit
    assert "不适用" in str(fit.get("note") or ""), fit


# =================================================================== e 反真空
def test_e_anti_vacuum_stubbing_the_judge_to_fit_hides_the_mismatch(
        monkeypatch: pytest.MonkeyPatch, store) -> None:
    """e（反真空①）：把 `claim_evidence_fit` 打桩成恒 fit ⇒ b 的 fixture 不再被点名。"""
    _lit(store)

    def _always_fit(*_a, **_kw):  # noqa: ANN001 - 与真身同用途的替身
        return {"verdict": "fit", "why": [], "numbers_in_claim": [], "words_in_claim": []}

    monkeypatch.setattr(CL, "claim_evidence_fit", _always_fit)
    out = _register(store, _cited(GIRTH))
    fit = _fit(out)
    assert fit.get("verdict") == "fit", (
        f"把判据打桩成恒 fit 之后这一条还是 {fit.get('verdict')!r} ⇒ "
        "b 量的不是那条判据（判据没有承重）")


def test_e2_anti_vacuum_stubbing_the_judge_to_mismatch_reds_the_match(
        monkeypatch: pytest.MonkeyPatch, store) -> None:
    """e2（反真空②）：把同一个判据打桩成恒 mismatch ⇒ a 的 fixture 变成「跑题」。"""
    _lit(store)

    def _always_mismatch(*_a, **_kw):  # noqa: ANN001 - 同上
        return {"verdict": "mismatch", "why": ["夹具：恒判跑题"],
                "numbers_in_claim": [], "words_in_claim": []}

    monkeypatch.setattr(CL, "claim_evidence_fit", _always_mismatch)
    out = _register(store, _cited(CUBE))
    fit = _fit(out)
    assert fit.get("verdict") == "mismatch", (
        f"把判据打桩成恒 mismatch 之后这一条还是 {fit.get('verdict')!r} ⇒ "
        "a 的绿不是那条判据给的（判据没有承重）")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
