# -*- coding: utf-8 -*-
"""概念的良定义证明有落点（2026-11-10 业主裁定 甲）。

## 口径（逐字）

「检查需有良定义证明的 concept 具体的注册和录入是否和一般手稿几乎一致（只不过它
几乎是 B 的事）」⇒ 甲：概念的良定义证明与一般手稿同一条链，差别只在"谁产出"：

- 一般命题的稿由 F 产出（`reports/f-proof-<号>.md`）；
- 概念的良定义稿由 B 产出（`reports/b-proof-<号>.md`，复用既有 b-proof 族）；
- V 照常三转签（V 只对手稿负责，不需要知道这是概念）；
- B 收录时把 `## 证明` 写进 concept 行的 `proof_text`（那是"良定义证明"这一格）；
- 概念没有等级轴（`derive_grade` 短路成 `not_applicable`），这一条不改。

## 本文件钉什么

| # | 判据 | 反真空 |
|---|---|---|
| a | `concept_statement`：无签 ⇒ 清空并留读数；有签 ⇒ 保留 | 把"有签"打桩成恒 False ⇒ 保留那条红 |
| b | `well_definedness_reading` 三态 + 来源（稿 / 证号） | 打桩 `sign_reading` 恒 unsigned ⇒ signed 条红 |
| c | `land_manuscript` 对 concept 行落 `reports/b-proof-<号>.md`（b-proof 族） | 把族换成 F ⇒ 判据红（路径不是 b-proof） |
| d | 已签 b-稿 + `ingest_manuscript(apply, ["proof_text"])` ⇒ 成功、读回 == 稿那一节 | 未签 ⇒ 受控拒、零写 |
| e | 删签 ⇒ `well_definedness` 从 signed 变 unsigned、`bits.reviewed` 落回假 | 打桩成恒 signed ⇒ 红 |
| f | F 的 `table.get` 读得出"这条概念有已签的良定义证明"（行上的签读数） | — |

零真实模型调用：`extractor=None`、`extract_text=None`、签由 `_credential_fixture`
的真写口（三票 + `vsigns.issue`）造；工作区全在 `tmp_path`，不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import shutil

import pytest

from agentflow import conceptrows as CR
from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.extract import extract_text
from agentflow.store import Store

import conftest  # noqa: E402
from _credential_fixture import issue_credential  # noqa: E402

PAPER = ("For convenience, a set of vertices K will be said to be a red interconnected "
         "set if all segments joining pairs of vertices in K are colored red.")
DEF = ("定义（红色互连集，red interconnected set）。给定顶点集 V，把完全图的每条边恰好"
       "染成红、蓝两色之一：若顶点子集 K 中任意两点之间的线段全部为红色，则称 K 为"
       "红色互连集。")
WELLDEF = ("良定义性证明：\n"
           "1. 定义里的量词范围是整个顶点集 V，而 V 非空。\n"
           "2. 判定只依赖边的染色；染色给定后 K 的红色性唯一确定 ⇒ 定义是良定义的。")


# ---------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    conftest.write_library_file(st, "000000/a.txt", PAPER + "\n")
    conftest.add_literature(st, "000000", title="Combinatorial", path="000000/a.txt")
    return st, AgentB(st, extractor=None, extract_text=extract_text, config={})


def _register_concept(st: Store, b: AgentB) -> str:
    got = b.register_statement(
        kind="concept", label="红色互连集（red interconnected set）",
        origin="external_lit", source_lit_id="000000",
        page_range={"start": 1, "end": 1}, quote_mode="verbatim", quote_verified=True,
        statement_full=DEF, statement_text="a set of vertices K ...")
    assert got.get("ok") is True, got
    return str(got.get("stmt_id") or "")


def _concept_pipeline(st: Store, b: AgentB) -> tuple[str, str]:
    """登记 concept → 落 b-稿；返回 `(stmt_id, 稿路径)`（此时还没签）。"""
    sid = _register_concept(st, b)
    landed = b.land_manuscript(statement_id=sid, proof_text=WELLDEF)
    assert landed.get("ok") is True, landed
    return sid, str(landed.get("path") or "")


def _sign(st: Store, *, sid: str, rel: str) -> dict:
    issue_credential(st.root, proof_text=WELLDEF, statement_id=sid,
                     manuscript=rel, proof_no=1)
    return dict(VS.sign_reading(st.root, statement_id=sid, proof_text=WELLDEF,
                                proof_no=1, manuscript_path=rel, store=st))


def _row(st: Store, sid: str) -> dict:
    return next((dict(r) for r in st.rows("statements")
                 if str(r.get("stmt_id")) == sid), {})


def _proof_body_on_disk(st: Store, rel: str) -> str:
    return DS.proof_body((pathlib.Path(st.root) / rel).read_text(encoding="utf-8"))


def _concept_issues(report) -> list:
    from agentflow.verify import CONCEPT_PROOF_TEXT_CODE

    return [i for i in report.issues if i.code == CONCEPT_PROOF_TEXT_CODE]


# ================================================================ a 构造口
def test_a_unsigned_body_is_cleared_and_the_reading_says_why() -> None:
    """a：没有 V 签 ⇒ `concept_statement` 清空 `proof_text`，并把它写进 `quote_reason`。"""
    row = CR.concept_statement(stmt_id="000001", label="电导", definition="边上权重的倒数",
                               source_lit_id="0000", proof_text="concept:primitive")
    assert row.proof_text == "", row.proof_text
    assert "没有 V 签" in str(row.quote_reason or ""), row.quote_reason


def test_a_signed_body_is_kept_and_the_anti_vacuum_turns_it_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """a 的正控 + 反真空：有签（`sign.state == "signed"`）⇒ 保留；把"有签"打桩成假 ⇒ 红。"""
    row = CR.concept_statement(stmt_id="000001", label="电导", definition="边上权重的倒数",
                               source_lit_id="0000", proof_text=WELLDEF,
                               sign={"state": "signed", "proof_no": 1,
                                     "credential": {"path": "out/vsigns/x.json"}})
    assert row.proof_text == WELLDEF, row.proof_text

    real = CR.concept_statement

    def _always_unsigned(**kw):
        kw = dict(kw, sign={"state": "unsigned"})
        return real(**kw)

    monkeypatch.setattr(CR, "concept_statement", _always_unsigned)
    red = CR.concept_statement(stmt_id="000001", label="电导", definition="边上权重的倒数",
                               source_lit_id="0000", proof_text=WELLDEF,
                               sign={"state": "signed"})
    assert red.proof_text == "", (
        "把'有签'打桩成假之后正文还在 ⇒ 保留那一半不是由签判据带来的")


# ================================================================ b 三态读数
def test_b_three_states_and_their_source(tmp_path: pathlib.Path) -> None:
    """b：`well_definedness` 三态（signed / unsigned / rejected）+ 来源（哪份稿、哪一签）。"""
    st, b = _ws(tmp_path)
    sid, rel = _concept_pipeline(st, b)

    # unsigned：正文空
    row = _row(st, sid)
    gap = CR.well_definedness_reading(st.root, row, manuscript_path=rel, store=st)
    assert gap["state"] == "unsigned", gap
    assert gap["body_chars"] == 0, gap

    # rejected：V 对同一版正文的最近结论不是「成立」（台账行，没有签文件）
    VR.record_verification(
        str(st.root), statement_id=sid, proof_text=WELLDEF,
        verdict={"verdict": "有毛病", "defect_step": 2,
                 "findings": [{"detail": "第 2 步不成立", "level": "error", "step": 2}]},
        secretary_judge={"axis": "fault", "checked": True, "reason": "夹具：判有毛病"},
        manuscript=rel, flip=False)
    reading = VS.sign_reading(st.root, statement_id=sid, proof_text=WELLDEF,
                              proof_no=1, manuscript_path=rel, store=st)
    assert reading["state"] == "rejected", reading
    gap = CR.well_definedness_reading(st.root, row, manuscript_path=rel, store=st,
                                      sign=reading)
    assert gap["state"] == "rejected", gap
    assert gap["source"]["manuscript"] == rel, gap
    assert "打了回来" in gap["why"], gap["why"]

    # signed：真凭据（三票同源 + vsigns.issue）+ 收录之后正文才在这一行上
    _sign(st, sid=sid, rel=rel)
    ing = b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert ing.get("ok") is True, ing
    row = _row(st, sid)
    gap = CR.well_definedness_reading(st.root, row, manuscript_path=rel, store=st)
    assert gap["state"] == "signed", gap
    assert gap["source"]["manuscript"] == rel, gap
    assert gap["source"]["proof_no"] == 1, gap
    assert gap["source"]["verification_id"], gap
    assert gap["source"]["credential"].startswith("out/vsigns/"), gap
    assert "已由 V 签" in gap["why"], gap["why"]


def test_b_anti_vacuum_the_reading_follows_sign_reading_monkeypatch(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b 的反真空：把 `sign_reading` 打桩成恒 unsigned ⇒ signed 的那条读数红。"""
    st, b = _ws(tmp_path)
    sid, rel = _concept_pipeline(st, b)
    _sign(st, sid=sid, rel=rel)
    ing = b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert ing.get("ok") is True, ing
    row = _row(st, sid)
    assert CR.well_definedness_reading(st.root, row, manuscript_path=rel,
                                       store=st)["state"] == "signed"
    monkeypatch.setattr(VS, "sign_reading", lambda *a, **k: {"checked": True,
                                                             "state": "unsigned"})
    assert CR.well_definedness_reading(st.root, row, manuscript_path=rel,
                                       store=st)["state"] == "unsigned"


# ================================================================ c 落稿族
def test_c_land_manuscript_puts_a_concept_on_the_b_proof_family(
        tmp_path: pathlib.Path) -> None:
    """c：concept 行的良定义稿落在 `reports/b-proof-<号>.md`（复用 b-proof，不新开族）。"""
    st, b = _ws(tmp_path)
    sid, rel = _concept_pipeline(st, b)
    assert rel == f"reports/b-proof-{sid}.md", rel
    path = pathlib.Path(st.root) / rel
    assert path.is_file(), rel
    text = path.read_text(encoding="utf-8")
    assert f"- 命题号：stmt:{sid}" in text, text[:400]
    assert "## 命题" in text and DEF in text, text[:600]
    assert "## 证明" in text and WELLDEF in text, text[:800]
    assert "## 依赖" in text, text[:400]
    # 落稿只写文件、不写台账
    assert _row(st, sid)["proof_text"] == "", _row(st, sid)


# ================================================================ d 收录 + 读回
def test_d_signed_manuscript_is_ingested_and_read_back(tmp_path: pathlib.Path) -> None:
    """d：已签 b-稿 ⇒ `ingest_manuscript(apply, ["proof_text"])` 成功，读回逐格对得上。"""
    st, b = _ws(tmp_path)
    sid, rel = _concept_pipeline(st, b)
    _sign(st, sid=sid, rel=rel)
    body = _proof_body_on_disk(st, rel)

    ing = b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert ing.get("ok") is True, ing
    assert ing.get("refused") in ("", None), ing
    assert ing.get("diff") == {"requested_not_filled": [],
                               "filled_not_requested": []}, ing.get("diff")
    assert ing["cells"]["proof_text"]["outcome"] == "filled", ing["cells"]["proof_text"]
    assert ing.get("well_definedness", {}).get("state") == "signed", ing.get(
        "well_definedness")

    row = _row(st, sid)
    bits = EB.bits_from_row(row)
    assert str(row.get("proof_text") or "").strip() == body.strip(), row.get("proof_text")
    assert row.get("evidence_kind") == "heuristic", row.get("evidence_kind")
    assert bits.get("reviewed") is True, bits
    assert EB.derive_grade(bits, kind=str(row.get("kind") or "")) == "not_applicable", bits
    assert bits.get("grade") == "not_applicable", bits
    # 等级轴 / 可引门一个字不动：概念仍不可被引
    assert sid not in DS.citable_pool([dict(r) for r in st.rows("statements")]), (
        "概念进了可引池 —— 可引门不该被这一笔改")
    assert CR.well_definedness_reading(st.root, row, manuscript_path=rel,
                                       store=st)["state"] == "signed"
    gap = VR.proof_review_gap(st.root, row)
    assert gap["ok"] is True and gap["state"] == "signed", gap
    assert "良定义证明" in gap["why"], gap["why"]


def test_d_unsigned_manuscript_is_still_refused_with_zero_writes(
        tmp_path: pathlib.Path) -> None:
    """d 的反真空：未签的稿 ⇒ 受控拒，`proof_text` 仍是空、零写。"""
    st, b = _ws(tmp_path)
    sid, rel = _concept_pipeline(st, b)
    before = _row(st, sid)
    ing = b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert ing.get("ok") is False, ing
    assert ing.get("refused") == "proof_without_v_sign", ing
    assert _row(st, sid) == before, "未签那一笔改了台账"
    assert str(_row(st, sid).get("proof_text") or "") == ""


# ================================================================ e 删签降档
def test_e_deleting_the_sign_drops_signed_to_unsigned(
        tmp_path: pathlib.Path) -> None:
    """e：删签 ⇒ `well_definedness` 从 signed 变 unsigned，`bits.reviewed` 落回假。"""
    st, b = _ws(tmp_path)
    sid, rel = _concept_pipeline(st, b)
    _sign(st, sid=sid, rel=rel)
    first = b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                                cells=["proof_text"], mode="apply")
    assert first.get("ok") is True, first
    assert CR.well_definedness_reading(st.root, _row(st, sid), manuscript_path=rel,
                                       store=st)["state"] == "signed"
    assert EB.bits_from_row(_row(st, sid)).get("reviewed") is True

    # 删掉签文件（保留 issued.json 索引）
    for path in (pathlib.Path(st.root) / "out" / "vsigns").glob("*.json"):
        if path.name != "issued.json":
            path.unlink()
    replay = b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                                 cells=["proof_text"], mode="apply")
    assert replay.get("ok") is True, replay
    row = _row(st, sid)
    bits = EB.bits_from_row(row)
    assert bits.get("reviewed") is False, bits
    assert CR.well_definedness_reading(st.root, row, manuscript_path=rel,
                                       store=st)["state"] == "unsigned"
    gap = VR.proof_review_gap(st.root, row)
    assert gap["ok"] is False and "概念行不该带证明文本" in gap["why"], gap
    from agentflow.verify import verify_all

    report = verify_all(st)
    assert len(_concept_issues(report)) == 1, [i.to_dict() for i in _concept_issues(report)]


def test_e_wiping_the_body_makes_the_readback_red(tmp_path: pathlib.Path) -> None:
    """e 的第二半：概念行的 `proof_text` 又被清空 ⇒ 与稿那一节不再相等（b 红）。"""
    st, b = _ws(tmp_path)
    sid, rel = _concept_pipeline(st, b)
    _sign(st, sid=sid, rel=rel)
    body = _proof_body_on_disk(st, rel)
    b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                        cells=["proof_text"], mode="apply")
    assert str(_row(st, sid).get("proof_text") or "").strip() == body.strip()
    with st.tx("statements", actor="test") as tx:
        for r in tx.rows("statements"):
            if str(r.get("stmt_id") or "") == sid:
                r = dict(r)
                r["proof_text"] = ""
                tx.upsert("statements", r)
    assert str(_row(st, sid).get("proof_text") or "").strip() != body.strip(), (
        "清空之后仍相等 ⇒ 这一条判据量错了东西")
    assert CR.well_definedness_reading(st.root, _row(st, sid), manuscript_path=rel,
                                       store=st)["state"] == "unsigned"


# ================================================================ f F 的读法
def test_f_f_reads_the_signed_well_definedness_from_the_row(tmp_path: pathlib.Path) -> None:
    """f：F 的 `table.get` 读得出"这条概念有已签的良定义证明"，且那是行上的签读数。

    F 看到的是 `proof_text` 非空 + `bits.reviewed=true` + `bits.evidence.
    reviewed_by_proof={"1": true}`（不是 V 的直接产物：F 没有 V 的三件工具）。
    """
    st, b = _ws(tmp_path)
    sid, rel = _concept_pipeline(st, b)
    _sign(st, sid=sid, rel=rel)
    b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                        cells=["proof_text"], mode="apply")

    from agentflow.tools import build_registry

    freg = build_registry(store=st, workspace_root=str(st.root)).registry.scoped_to("F")
    res = freg.call("table.get", table="statements", id=sid)
    assert res.ok is True, res.error
    row = dict(res.data or {})
    bits = dict(row.get("bits") or {})
    assert str(row.get("proof_text") or "").strip(), row
    assert bits.get("reviewed") is True, bits
    assert bits.get("grade") == "not_applicable", bits
    assert EB.reviewed_by_proof(bits).get(1) is True, bits
    verdict = dict((bits.get("evidence") or {}).get("reviewed_by") or {})
    assert verdict.get("verdict") == "成立", verdict
    # 概念仍不在可引池：F 读得到它，但不能引它（另一条裁定，不动）。
    assert sid not in DS.citable_pool([dict(r) for r in st.rows("statements")])
