# -*- coding: utf-8 -*-
"""判据：优化侧的「未优化清单」是候选面，「等洗」是作业面 —— 两个问题、两把尺子。

## 业主口径（2026-11-14，逐字）

> 「这不是针对哪个类型的特殊规定，是一般性规定，是一般性的针对优化侧的规定，
>  毕竟录入侧可能找不到素材。对于优化侧，系统取未优化的命题号及相关信息、
>  命题类型、原证明稿，自动注册 B 侧稿号并给出初始稿（就是原证明稿的复制版）……」

⇒ 候选面按"有没有原稿"划，不按 kind 划；概念只是 `prompt_class == "well_defined"`
那一档。

## 这一份钉什么（每条都能单独红）

| # | 判据 | 反真空 |
|---|---|---|
| a | 1 条 own_result 概念 + 1 条 external_lit 概念 ⇒ 候选面 `checked=True`、两支行各 1 条，`next_step` 逐支不同 | 把 `_statement_rows` 打桩成空账本 ⇒ 同一把尺子必红 |
| b | 签与位不许分家：`well_definedness=="signed"` ⇔ `bits.reviewed is True`（只调两个既有唯一读口） | 把 `bits_from_row` 打桩成丢掉 reviewed ⇒ 同一把尺子必红 |
| c | 「等洗」的排除面是没有可优化的正文，不是 kind：无稿概念恒 0（负控）+ 有稿概念必进（正控） | 把 `proof_text` 清空 ⇒ 它从等洗里消失（证明量的是正文） |
| d | `prompt_class` 三档的判定输入：`statements.kind`（权威）+ 证明栏是否穷举 | 穷举证明栏摘掉 ⇒ 退回 `theorem` |

全部 tmp 工作区、零模型调用，不读写 `projects/` 与 `temp/realrun-*`。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import conftest  # noqa: E402
from _credential_fixture import issue_credential  # noqa: E402

from agentflow import closing as CL  # noqa: E402
from agentflow import conceptrows as CR  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

P1 = "1. 由定义直接得到。\n2. 由 1 得结论。"
EXHAUSTIVE_PROOF = (
    "程序：temp/probe.py\n\n"
    "程序设计：枚举全部 3 个顶点的染色，剪掉对称重复。\n\n"
    "穷举论证：搜索空间共 8 种染色，穷尽了所有情形，边界 0/3 逐条处理，不漏。")


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    conftest.add_literature(st, "000004", title="夹具文献")
    return st


def _put_concept(st: Store, *, sid: str, origin: str, proof_text: str = "") -> dict:
    extra: dict = {}
    if origin == "external_lit":
        extra["source_lit_id"] = "000004"
    return conftest.seed_statement_row(
        st, stmt_id=sid, kind="concept", origin=origin,
        statement_full=f"定义（{sid}）：夹具概念的定义正文。", proof_text=proof_text,
        **extra)


def _put_theorem(st: Store, *, sid: str, proof_text: str, kind: str = "theorem") -> dict:
    return conftest.seed_statement_row(
        st, stmt_id=sid, kind=kind, origin="own_result",
        statement_full=f"命题（{sid}）：夹具命题。", proof_text=proof_text)


def _states(st: Store, sid: str, table: dict[str, bool]) -> None:
    """把 `optimized_by_proof` 那一格按证明号铺上（只动这一格）。"""
    row = next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)
    bits = dict(row.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    ev[EB.OPTIMIZED_BY_PROOF_KEY] = {str(k): bool(v) for k, v in table.items()}
    bits["evidence"] = ev
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", dict(row, bits=EB.normalize_raw(
            bits, origin=str(row.get("origin") or ""), kind=str(row.get("kind") or ""))))


# ================================================================ a 候选面

def _candidate_problems(reading: dict) -> list[str]:
    """候选面那三条读数（绿 = 空列表）。两个用例调同一份判据。"""
    problems: list[str] = []
    if reading.get("checked") is not True:
        problems.append(f"checked 不是 True：{reading.get('reason')!r}")
    by_origin = dict(reading.get("by_origin") or {})
    if by_origin.get("own_result") != 1:
        problems.append(f"own_result 那一支不是 1 条：{by_origin!r}")
    if by_origin.get("external_lit") != 1:
        problems.append(f"external_lit 那一支不是 1 条：{by_origin!r}")
    rows = {str(r.get("stmt_id")): r for r in (reading.get("rows") or [])}
    if len(rows) != 2:
        problems.append(f"逐条数不是 2：{sorted(rows)}")
        return problems
    for sid, row in rows.items():
        if row.get("prompt_class") != "well_defined":
            problems.append(f"{sid} 的 prompt_class 不是 well_defined：{row.get('prompt_class')!r}")
        if (row.get("draft") or {}).get("available") is not False:
            problems.append(f"{sid} 没有原稿却读成有：{row.get('draft')!r}")
        if not str(row.get("next_step") or "").strip():
            problems.append(f"{sid} 没有 next_step")
    own = next(r for r in rows.values() if r.get("origin") == "own_result")
    lit = next(r for r in rows.values() if r.get("origin") == "external_lit")
    if "b-稿" not in str(own.get("next_step") or ""):
        problems.append(f"own_result 支的 next_step 不指向落 b-稿：{own.get('next_step')!r}")
    if "quote_span" not in str(lit.get("next_step") or ""):
        problems.append(f"external_lit 支的 next_step 不指向补 quote_span：{lit.get('next_step')!r}")
    if own["next_step"] == lit["next_step"]:
        problems.append("两支的 next_step 是同一句话（等于没分支）")
    return problems


def test_a_the_candidate_face_names_both_origin_branches(tmp_path) -> None:
    """a：两条概念（own_result / external_lit）⇒ 候选面两支行各 1 条，next_step 分得开。"""
    st = _ws(tmp_path)
    _put_concept(st, sid="000001", origin="own_result")
    _put_concept(st, sid="000002", origin="external_lit")
    got = CL.statements_optimization_candidates(st)
    assert _candidate_problems(got) == [], "\n".join(_candidate_problems(got))
    assert got["by_prompt_class"] == {"well_defined": 2}, got["by_prompt_class"]
    assert got["problems"] == [], got["problems"]


def test_a_stubbing_the_ledger_empty_turns_the_candidate_face_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a 反真空：把命题台账打桩成空账本 ⇒ 同一把尺子必红（绿不是"读了个空集"）。"""
    st = _ws(tmp_path)
    _put_concept(st, sid="000001", origin="own_result")
    _put_concept(st, sid="000002", origin="external_lit")
    monkeypatch.setattr(CL, "_statement_rows", lambda store: ({}, ""))
    empty = CL.statements_optimization_candidates(st)
    assert empty.get("checked") is True, empty
    assert _candidate_problems(empty), "空账本竟然通过了候选面判据 ⇒ 这条反真空失效"


# ================================================================ b 签与位

def _split_problems(*, well_definedness: dict, bits: dict, sign_state: str) -> list[str]:
    """「签」与「位」不许分家的判据（绿 = 空列表；两个方向都查）。"""
    problems: list[str] = []
    signed = str(well_definedness.get("state") or "") == "signed"
    reviewed = bits.get("reviewed") is True
    if signed and not reviewed:
        problems.append(
            f"签与位分家：well_definedness=signed 而 bits.reviewed 不是 True（{bits.get('reviewed')!r}）")
    if reviewed and sign_state != "signed":
        problems.append(
            f"签与位分家：bits.reviewed=True 而 sign_reading.state != signed（{sign_state!r}）")
    return problems


def _signed_concept(tmp_path: pathlib.Path) -> tuple[Store, AgentB, str, str]:
    """一条概念：登记 → 落 b-稿 → V 签 → 收录（`proof_text` 与第 3 位都到位）。"""
    st = Store(tmp_path / "ws")
    st.init()
    conftest.write_library_file(st, "000000/a.txt", "red set 定义原文。\n")
    conftest.add_literature(st, "000000", title="Combinatorial", path="000000/a.txt")
    b = conftest.b_form_gate_ok(AgentB(st, extractor=None, extract_text=None, config={}))
    reg = b.register_statement(
        kind="concept", label="红色互连集", origin="external_lit", source_lit_id="000000",
        page_range={"start": 1, "end": 1}, quote_mode="verbatim", quote_verified=True,
        statement_full="定义（红色互连集）：若 K 中任意两点之间的线段全为红色，则称 K 为红色互连集。",
        statement_text="a set of vertices K ...")
    assert reg.get("ok") is True, reg
    sid = str(reg["stmt_id"])
    welldef = ("良定义性证明：\n1. 量词范围是整个顶点集 V，而 V 非空。\n"
               "2. 判定只依赖边的染色；染色给定后 K 的红色性唯一确定。")
    landed = b.land_manuscript(statement_id=sid, proof_text=welldef)
    assert landed.get("ok") is True, landed
    rel = str(landed["path"])
    issue_credential(st.root, proof_text=welldef, statement_id=sid, manuscript=rel,
                     proof_no=1)
    ing = b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert ing.get("ok") is True, ing
    return st, b, sid, rel


def test_b_the_signed_concept_keeps_the_sign_and_the_bit_together(tmp_path) -> None:
    """b：已签的良定义证明 ⇒ 两个既有读口同时为真（signed ⇔ reviewed），且 `next_step` 为空。"""
    st, _b, sid, rel = _signed_concept(tmp_path)
    row = next(dict(r) for r in st.rows("statements") if str(r["stmt_id"]) == sid)
    gap = CR.well_definedness_reading(st.root, row, manuscript_path=rel, store=st)
    bits = EB.bits_from_row(row)
    sign = VS.sign_reading(st.root, statement_id=sid,
                           proof_text=str(row.get("proof_text") or ""),
                           proof_no=1, manuscript_path=rel, store=st)
    assert gap["state"] == "signed", gap
    assert bits.get("reviewed") is True, bits
    assert str(sign.get("state") or "") == "signed", sign
    assert _split_problems(well_definedness=gap, bits=bits,
                           sign_state=str(sign.get("state") or "")) == []
    assert gap.get("next_step") == "", gap


def test_b_stubbing_the_bit_dropped_turns_the_split_judgement_red(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b 反真空：把 `bits_from_row` 打桩成丢掉 reviewed ⇒ 同一把尺子必红。"""
    st, _b, sid, rel = _signed_concept(tmp_path)
    row = next(dict(r) for r in st.rows("statements") if str(r["stmt_id"]) == sid)
    monkeypatch.setattr(EB, "bits_from_row", lambda r: {"reviewed": False})
    gap = CR.well_definedness_reading(st.root, row, manuscript_path=rel, store=st)
    bits = EB.bits_from_row(row)
    problems = _split_problems(well_definedness=gap, bits=bits, sign_state="signed")
    assert problems, "位掉了、读数没红 ⇒ 这条反真空失效"
    assert "签与位分家" in problems[0], problems


def test_b_the_reverse_direction_is_a_problem() -> None:
    """b 的反向：位为真而签读数不是 signed ⇒ 判据当场报红（不是只查一个方向）。"""
    gap = {"state": "unsigned"}
    problems = _split_problems(well_definedness=gap, bits={"reviewed": True},
                               sign_state="unsigned")
    assert problems and "签与位分家" in problems[0], problems


# ================================================================ c 等洗的排除面

def _wash_kinds(reading: dict) -> set[str]:
    return {str(r.get("kind")) for r in (reading.get("rows") or [])}


def test_c_a_concept_without_a_draft_is_not_in_the_wash_scope(tmp_path) -> None:
    """c 负控：无稿概念不进「等洗」（count 只数那条有正文的定理；scanned 两条都数）。"""
    st = _ws(tmp_path)
    _put_concept(st, sid="000001", origin="own_result")
    _put_theorem(st, sid="000002", proof_text=P1)
    _states(st, "000002", {"1": False})
    got = CL.statements_unoptimized_reading(st)
    assert got["checked"] is True, got
    assert int(got["count"]) == 1, got
    assert int(got["scanned"]) == 2, got
    assert _wash_kinds(got) == {"theorem"}, got["rows"]
    assert {str(r["stmt_id"]) for r in got["rows"]} == {"000002"}, got["rows"]


def test_c_a_concept_with_a_draft_is_in_the_wash_scope(tmp_path) -> None:
    """c 正控：概念有良定义论证正文 ⇒ 它必须进「等洗」—— 排除的是"没有原稿"，不是 kind。"""
    st = _ws(tmp_path)
    _put_concept(st, sid="000001", origin="own_result", proof_text="良定义论证正文。")
    got = CL.statements_unoptimized_reading(st)
    assert got["checked"] is True, got
    assert int(got["count"]) == 1, got
    assert _wash_kinds(got) == {"concept"}, got["rows"]


def test_c_clearing_the_body_removes_it_from_the_wash_scope(tmp_path) -> None:
    """c 反真空：把同一条概念的正文清空 ⇒ 它从等洗里消失（量的是正文，不是那条 continue）。"""
    st = _ws(tmp_path)
    _put_concept(st, sid="000001", origin="own_result", proof_text="良定义论证正文。")
    assert int(CL.statements_unoptimized_reading(st)["count"]) == 1
    row = next(dict(r) for r in st.rows("statements") if str(r["stmt_id"]) == "000001")
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", dict(row, proof_text=""))
    got = CL.statements_unoptimized_reading(st)
    assert int(got["count"]) == 0, got
    assert int(got["scanned"]) == 1, got


# ================================================================ d prompt_class

def test_d_prompt_class_uses_kind_and_the_proof_column(tmp_path) -> None:
    """d：概念 ⇒ well_defined；定理 ⇒ theorem；证明栏带穷举论证 ⇒ exhaustive。"""
    st = _ws(tmp_path)
    _put_concept(st, sid="000001", origin="own_result")
    _put_theorem(st, sid="000002", proof_text=P1)
    _put_theorem(st, sid="000003", proof_text=EXHAUSTIVE_PROOF)
    got = CL.statements_optimization_candidates(st)
    by = {str(r["stmt_id"]): r["prompt_class"] for r in got["rows"]}
    assert by.get("000001") == "well_defined", by
    assert by.get("000002") == "theorem", by
    assert by.get("000003") == "exhaustive", by
    assert got["by_prompt_class"] == {"well_defined": 1, "theorem": 1, "exhaustive": 1}, (
        got["by_prompt_class"])


def test_d_without_the_exhaustion_column_it_falls_back_to_theorem(tmp_path) -> None:
    """d 反真空：把穷举论证那一段摘掉 ⇒ 同一条命题退回 theorem（分档量的是证明栏）。"""
    st = _ws(tmp_path)
    _put_theorem(st, sid="000003", proof_text="程序：temp/probe.py\n\n穷举论证：穷尽了所有情形。")
    before = CL.statements_optimization_candidates(st)
    assert next(r["prompt_class"] for r in before["rows"]
                if r["stmt_id"] == "000003") == "exhaustive", before["rows"]
    _put_theorem(st, sid="000003", proof_text=P1)
    after = CL.statements_optimization_candidates(st)
    assert next(r["prompt_class"] for r in after["rows"]
                if r["stmt_id"] == "000003") == "theorem", after["rows"]
