# -*- coding: utf-8 -*-
"""判据：命题的两个新终态（「标记为错误」与「优化栏=难以自证」）与「稿一并作废」。

## 业主 2026-11-13 裁定（本文件钉的就是它）

> 「一个命题通过规范性审查后拿到一个稿号……放弃命题时就是这个稿也一并作废。」
> 「数学错误应该将命题标记为错误」「就是优化栏写难以自证，其它栏保留引文侧录入的
>   样子，如 V 签还是占位」「若父代理认为这个命题重要，则应上报作为一个研究任务」。

## 一句话结论（也是本文件 a/b 两组守的）

「标记为错误」的机器实现早就有了（`evidencebits.VOID_CONDITIONS` / `void_refusal` /
`void` / `cascade_void` / `apply_cascade` + 读侧 `derive_grade` 的清零），只缺一个把
它写上命题行的写入口 —— 本批补的就是那一笔（`statementrefute.refute_statement`）。

## 判据表

| # | 钉的是 | 正控 / 反真空 |
|---|---|---|
| a | 三件证据各能写成 `status=refuted` + `bits.voided_by`（构造 / 反例实验 / 判词） | 正控 |
| b | 「难以自证」只动优化栏：status、占位签、`reviewed` 一个都不动 | 正控 |
| c | 命题退休 ⇒ 那份稿一并作废（不可 edit、收工门不要它、不算依据），文件留着 | 正控 |
| d | 三处「假红」不再红：`statements_unsigned` / `statements_unoptimized` / E、B 的签门 | 正控 |
| e | 原子性：写失败 ⇒ 一行都没改（status 与 voided_by 原样） | 正控 |
| f | 反真空：把退休判据摘掉 ⇒ 写面放行（c 的绿来自那条核） | 反真空 |
| g | 反真空：把占位签掰成真签 ⇒ b 的断言必红 | 反真空 |
| h | 反真空：把写口改成「先落盘再报拒」⇒ e 的原子性断言必红 | 反真空 |
| i | 「哪几份稿属于这条命题」= 三源并集（`manuscript_id` / `manuscripts` / 签行） | 正控 |
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import seed_statement_row  # noqa: E402

from agentflow import agent_loop as AL  # noqa: E402
from agentflow import closing as CL  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscriptids as MID  # noqa: E402
from agentflow import manuscriptopen as MO  # noqa: E402
from agentflow import manuscriptretire as MR  # noqa: E402
from agentflow import papermapping as PM  # noqa: E402
from agentflow import statementrefute as SR  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-11-13T09:00:00+08:00"
SID = "000001"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
F_REL = "reports/f-proof-000000.md"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _issue_manuscript(st: Store, family: str = "f-proof") -> tuple[str, str]:
    """发一个真号并落一份真文件（写面要「号已发 + 在盘上」两样都成立）。"""
    mid = MID.next_manuscript_id(st.root, family=family)
    rel = MID.canonical_rel(mid, family=family)
    path = pathlib.Path(str(st.root)) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 探针稿\n\n## 命题\n\nX\n\n## 证明\n\nY\n", encoding="utf-8")
    return mid, rel


def _put(st: Store, sid: str = SID, *, origin: str = "own_result",
         bits: dict | None = None, status: str = "active", **extra) -> dict:
    if origin == "external_lit":
        extra.setdefault("source_lit_id", "000000")
    extra.setdefault("quote_reason", "夹具：探针")
    return seed_statement_row(
        st, stmt_id=sid, kind="theorem", label="探针命题", statement_full=FULL,
        proof_text=PROOF, origin=origin,
        quote_verified=(True if origin == "external_lit" else None),
        status=status, bits=bits if bits is not None else {}, **extra)


def _citation_bits(*, reviewed: bool = False) -> dict:
    """引文侧那五元位：第 2 位凭据是文献代号、第 3 位不翻（占位签）。"""
    bits = EB.bits_of(origin="external_lit", source_lit_id="000000",
                      quote_verified=True, proof=True, reviewed=reviewed,
                      reviewed_by={"evidence": "lit:000000"}, kind="theorem")
    bits["evidence"]["reviewed_source"] = EB.REVIEWED_SOURCE_CITATION
    return EB.with_optimized_defaults(bits, [1])


def _fault_row(st: Store, sid: str = SID, *, step: int = 5) -> str:
    """落一行判词「有毛病」（`defect_ref` 那一档的正控现场）。"""
    VR.record_verification(
        st.root, statement_id=sid, proof_text=PROOF,
        verdict={"verdict": "有毛病", "defect_step": step,
                 "findings": [{"detail": "夹具：第 5 步断言不成立", "level": "error",
                               "step": step}]},
        secretary_judge={"axis": "fault", "checked": True, "reason": "夹具：秘书判 fault"},
        flip=False)
    return f"verifications/{sid}.jsonl#v-000001"


def _cands(rel: str) -> dict:
    return {"000000": {"manuscript": rel, "signed": False, "state": "unsigned"}}


# ============================================================ a：三件证据都能写成 refuted

def test_a1_each_evidence_shape_writes_refuted_with_a_payload(tmp_path):
    """a：构造 / 反例实验 / 判词 三条证据路各自把命题标成 refuted 并留下载荷。"""
    st = _ws(tmp_path)
    _put(st, "000001")
    got = SR.refute_statement(st, statement_id="000001", reason="引文第 3 步推不出来",
                              construction="取 G = 完全图 K3，则假设不成立")
    assert got["checked"] is True and got["amended"] is True, got
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == "000001")
    assert row["status"] == "refuted"
    payload = (row.get("bits") or {}).get("voided_by") or {}
    assert payload.get("kind") == "construction", payload
    assert payload.get("at") == got["at"] and payload.get("reason"), payload

    # 反例实验那一档：§3.18 四条由既有 `void_refusal` 判（这里只替掉「那一行从哪来」）
    _put(st, "000002")
    fake = {"experiment_id": "000007", "exit_code": 0, "result": "refutes",
            "counterexample": {"point": "(0,0)"}, "code_path": "scripts/x.py",
            "code_hash": "a" * 64, "claim_key": "探针命题"}
    real = SR._experiment_row
    SR._experiment_row = lambda store, eid: (dict(fake), "")
    try:
        got2 = SR.refute_statement(st, statement_id="000002", reason="反例命中",
                                   experiment_id="000007", counterexample_valid=True)
    finally:
        SR._experiment_row = real
    assert got2["checked"] is True, got2
    row2 = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == "000002")
    assert row2["status"] == "refuted"
    assert (row2["bits"].get("voided_by") or {}).get("kind") == "numeric_counterexample"

    # 判词那一档：`defect_ref` 必须真的指到一行「有毛病」、且审的是现行正文
    _put(st, "000003")
    ref = _fault_row(st, "000003")
    got3 = SR.refute_statement(st, statement_id="000003",
                               reason="第 5 步直接用了结论", defect_ref=ref)
    assert got3["checked"] is True, got3
    row3 = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == "000003")
    assert (row3["bits"].get("voided_by") or {}).get("kind") == "defect_ref"
    assert (row3["bits"].get("voided_by") or {}).get("defect_ref") == ref


def test_a2_refute_needs_exactly_one_evidence_and_a_reason(tmp_path):
    """a 的负控：没证据 / 两件证据 / 没理由 都是受控拒，且一行不改。"""
    st = _ws(tmp_path)
    _put(st)
    none = SR.refute_statement(st, statement_id=SID, reason="我觉得错了")
    assert none["refused"] == "refute_evidence_required", none
    two = SR.refute_statement(st, statement_id=SID, reason="两句都说了",
                              construction="x", experiment_id="000007")
    assert two["refused"] == "refute_evidence_ambiguous", two
    noreason = SR.refute_statement(st, statement_id=SID, construction="x")
    assert noreason["refused"] == "refute_reason_missing", noreason
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    assert row["status"] == "active" and not (row.get("bits") or {}).get("voided_by")


def test_a3_refuted_is_terminal_not_idempotent_rewrite(tmp_path):
    """a 的终态纪律：已 refuted 重放 ⇒ already；已 abandoned ⇒ 拒（两个终态不能换档）。"""
    st = _ws(tmp_path)
    _put(st)
    first = SR.refute_statement(st, statement_id=SID, reason="错", construction="x")
    assert first["checked"] is True
    again = SR.refute_statement(st, statement_id=SID, reason="再来", construction="y")
    assert again["checked"] is True and again["already"] is True, again
    from agentflow import statementabandon as SA

    ab = SA.apply_abandonment(st, statement_id=SID, reason="先放弃",
                              abandon_kind="difficulty", abandon_basis="难",
                              difficulty="难在哪", salvaged=[],
                              difficulty_judge=lambda **k: {
                                  "checked": True, "genuine": True,
                                  "salvaged_from_proof": True, "problems": []})
    assert ab["checked"] is False  # abandoned 是另一档，不在这一条上再判
    _put(st, "000002", status="abandoned",
         quote_reason="abandoned@2026-11-13T09:00:00+08:00@先放下了")
    refused = SR.refute_statement(st, statement_id="000002", reason="错", construction="x")
    assert refused["refused"] == "refute_on_abandoned", refused


# ============================================================ b：难以自证只动优化栏

def test_b_hard_to_prove_touches_only_the_optimization_column(tmp_path):
    """b：「难以自证」写进优化栏，status / 占位签 / `reviewed` 一个都不动。"""
    st = _ws(tmp_path)
    _put(st, origin="external_lit", bits=_citation_bits(reviewed=False))
    got = SR.mark_hard_to_prove(st, statement_id=SID, basis="引文没给完整严密证明",
                                at=TS)
    assert got["checked"] is True and got["amended"] is True, got
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    bits = row.get("bits") or {}
    ev = bits.get("evidence") or {}
    assert row["status"] == "active", row["status"]
    assert bits.get("reviewed") is False, bits.get("reviewed")
    assert ev.get("reviewed_source") == EB.REVIEWED_SOURCE_CITATION, ev
    assert ev.get("proof_source") == "citation", ev
    assert EB.optimized_state(row, 1) == "hard_to_prove"
    assert PM.optimized_cell(row, 1) == PM.OPTIMIZED_HARD_TO_PROVE
    assert EB.hard_to_prove_entry(row, 1)["basis"] == "引文没给完整严密证明"
    # 幂等：同一句理由重放 ⇒ 一个字节不写
    again = SR.mark_hard_to_prove(st, statement_id=SID, basis="引文没给完整严密证明")
    assert again["checked"] is True and again["already"] is True, again


def test_b2_hard_to_prove_refuses_when_the_row_already_claims_optimized(tmp_path):
    """b 的负控：「已优化」与「难以自证」不能并存（两个结论同时成立=自相矛盾）。"""
    st = _ws(tmp_path)
    bits = _citation_bits(reviewed=False)
    bits = EB.with_optimized_flag(bits, 1, True)
    _put(st, origin="external_lit", bits=bits)
    got = SR.mark_hard_to_prove(st, statement_id=SID, basis="证不出来")
    assert got["checked"] is False
    assert got["refused"] == "hard_to_prove_after_optimized", got
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    assert not EB.hard_to_prove_by_proof(row)


# ============================================================ c：稿一并作废

def test_c_the_manuscript_is_voided_with_the_statement_but_the_file_stays(tmp_path):
    """c：命题退休 ⇒ 那份稿不可 edit；稿文件留着（删/移不是这一档的处置）。"""
    st = _ws(tmp_path)
    mid, rel = _issue_manuscript(st)
    _put(st, manuscript_id=rel)
    before = MO.write_allowed(rel=rel, role="F", root=str(st.root), store=st)
    assert before["allowed"] is True, before
    SR.refute_statement(st, statement_id=SID, reason="引文错了", construction="x")
    assert MR.retire_reading(st, rel)["retired"] is True
    after = MO.write_allowed(rel=rel, role="F", root=str(st.root), store=st)
    assert after["allowed"] is False and after["code"] == MO.MANUSCRIPT_RETIRED, after
    assert (pathlib.Path(str(st.root)) / rel).is_file(), "稿文件必须留着"
    # 反方向：没有 store 的调用点读不到这一格（不折成「没退休」）
    blind = MO.write_allowed(rel=rel, role="F", root=str(st.root))
    assert blind["allowed"] is True and blind["retirement"]["checked"] is False


def test_c2_union_of_three_sources_finds_every_role_manuscript(tmp_path):
    """c 的读侧：`manuscript_id` / `manuscripts` / 签行 三源并集都要读到。"""
    st = _ws(tmp_path)
    mid_f, rel_f = _issue_manuscript(st, "f-proof")
    mid_b, rel_b = _issue_manuscript(st, "b-proof")
    _put(st, manuscript_id=rel_b, manuscripts={"1": rel_f})
    got = MR.manuscripts_of_statement(st, SID)
    assert set(got["manuscripts"]) == {rel_f, rel_b}, got
    assert "manuscripts" in got["sources"][rel_f]
    assert "manuscript_id" in got["sources"][rel_b]
    # 第三源独有：行上两格都被覆写成 b-稿，f-稿只剩签行里那一份
    _put(st, "000002", manuscript_id=rel_b, manuscripts={"1": rel_b})
    VR.record_verification(
        st.root, statement_id="000002", proof_text=PROOF,
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
        manuscript=rel_f, secretary_judge={"axis": "clean", "checked": True,
                                           "reason": "夹具"},
        flip=False)
    got2 = MR.manuscripts_of_statement(st, "000002")
    assert rel_f in got2["manuscripts"], got2
    assert "verifications" in got2["sources"][rel_f]


# ============================================================ d：三处假红

def test_d_the_three_false_reds_are_gone(tmp_path):
    """d：refuted / hard_to_prove 的行不再被读成「欠签」或「等洗」。"""
    st = _ws(tmp_path)
    _put(st, "000001", manuscript_id=F_REL)
    _put(st, "000002", origin="external_lit", bits=_citation_bits(reviewed=False))
    SR.refute_statement(st, statement_id="000001", reason="错了", construction="x")
    SR.mark_hard_to_prove(st, statement_id="000002", basis="证不出来")

    unsigned = CL.statements_unsigned_reading(st)
    assert unsigned["checked"] is True
    assert unsigned["count"] == 0, unsigned["rows"]
    assert unsigned["hard_to_prove_count"] == 1, unsigned
    assert unsigned["by_class"] == {}, unsigned["by_class"]

    unopt = CL.statements_unoptimized_reading(st)
    assert unopt["checked"] is True
    assert unopt["count"] == 0, unopt["rows"]
    assert unopt["hard_to_prove_count"] == 1, unopt
    assert sum(unopt["by_class"].values()) == unopt["count"]

    # 两个终态在「放弃/错误」那一格里都要看得见（静默是另一种谎）
    retired = CL.statements_abandoned_reading(st)
    assert retired["error_count"] == 1, retired["error"]
    assert retired["error"][0]["voided_kind"] == "construction"
    assert retired["error"][0]["grade"] == EB.GRADE_ERROR
    assert retired["error"][0]["error_by_sign"] is False

    # B / E 两道签门都不再要签
    out_b: dict = {"problems": []}
    AL._sign_gate_b(st, str(st.root), _cands(F_REL), out_b)
    assert out_b.get("problems") == [], out_b
    out_e: dict = {"problems": []}
    AL._sign_gate_e(st, str(st.root), _cands(F_REL), out_e)
    assert out_e.get("problems") == [], out_e


# ============================================================ e：原子性

def test_e_a_failed_write_leaves_the_row_untouched(tmp_path):
    """e：写不进去 ⇒ status 与 voided_by 都没动（受控拒不是一个字节都没写就当成功）。"""

    class _Broken:
        root = ""

        def rows(self, table):
            return st.rows(table)

        def tx(self, *a, **k):
            raise RuntimeError("模拟落盘失败")

    st = _ws(tmp_path)
    _put(st)
    broken = _Broken()
    broken.root = st.root
    got = SR.refute_statement(broken, statement_id=SID, reason="错", construction="x")
    assert got["checked"] is False and got["refused"] == "refute_write_failed", got
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    assert row["status"] == "active"
    assert not (row.get("bits") or {}).get("voided_by")


# ============================================================ f/g/h：反真空

def test_f_without_the_retire_reading_the_write_face_lets_it_through(tmp_path, monkeypatch):
    """f（反真空）：摘掉退休判据 ⇒ 写面放行 —— c 的绿必须来自那条核。"""
    st = _ws(tmp_path)
    mid, rel = _issue_manuscript(st)
    _put(st, manuscript_id=rel)
    SR.refute_statement(st, statement_id=SID, reason="错", construction="x")
    monkeypatch.setattr(MR, "retire_reading",
                        lambda *a, **k: {"checked": True, "retired": False,
                                         "stmt_id": "", "status": "", "why": "打桩"})
    got = MO.write_allowed(rel=rel, role="F", root=str(st.root), store=st)
    assert got["allowed"] is True, "打桩之后没放行 ⇒ c 量的不是这条核"


def test_g_a_real_sign_stub_breaks_the_placeholder_reading(tmp_path, monkeypatch):
    """g（反真空）：把占位签掰成真签 ⇒ b 的断言必红。"""
    st = _ws(tmp_path)
    _put(st, origin="external_lit", bits=_citation_bits(reviewed=False))
    real = EB.with_hard_to_prove

    def _stub(bits, proof_no, *, basis, at=""):
        out = real(bits, proof_no, basis=basis, at=at)
        # 打桩：把占位签掰成真签。等级是现算的（`bits.grade` 与五位必须自洽），
        # 所以掰完要一起重算 —— 否则写入期会在 `bits.grade` 那一格先拒掉，
        # 这一条就量不到"真签与占位签在读侧不是一回事"。
        out["reviewed"] = True
        out["grade"] = EB.derive_grade(out, kind="theorem")
        return out

    monkeypatch.setattr(EB, "with_hard_to_prove", _stub)
    got = SR.mark_hard_to_prove(st, statement_id=SID, basis="证不出来")
    assert got["checked"] is True, got
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    # b 那一组断言是 `bits.reviewed is False`；打桩之后它必红 —— 这里证明打桩确实生效。
    assert row["bits"]["reviewed"] is True, "打桩没生效 ⇒ g 量不到东西"


def test_h_a_half_write_turns_the_atomicity_assertion_red(tmp_path, monkeypatch):
    """h（反真空）：把写口改成「先落盘再报拒」⇒ e 的原子性断言必红。"""
    st = _ws(tmp_path)
    _put(st)
    real = SR._write_row

    def _half(store, *, before, merged, note, actor, **kw):
        real(store, before=before, merged=merged, note=note, actor=actor, **kw)
        return None, "refute_write_failed", "打桩：写成了却报拒"

    monkeypatch.setattr(SR, "_write_row", _half)
    got = SR.refute_statement(st, statement_id=SID, reason="错", construction="x")
    assert got["checked"] is False
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    # e 的断言是 `status == "active"`；半途之后它必红 —— 证明 e 量的就是这一条。
    from agentflow import errorstate as ES
    assert row["status"] == ES.ERROR_WORD, "打桩没生效 ⇒ e 量不到原子性"


# ============================================================ k：生产写口（table.update）

def _registry(st: Store):
    from agentflow import conductor as CND
    from agentflow.tools import table_tools
    from agentflow.tools.base import ToolRegistry

    reg = ToolRegistry(name="tables")
    reg.bound_role = "B"
    table_tools.register(reg, store=st)
    return reg, CND


def test_k_the_production_write_face_routes_both_new_terminals(tmp_path):
    """k：B 真会走的 `table.update` 那条路也要能写这两档（不只是直调模块）。"""
    st = _ws(tmp_path)
    _put(st, "000001")
    _put(st, "000002", origin="external_lit", bits=_citation_bits(reviewed=False))
    reg, CND = _registry(st)
    with CND.calling_as("t-b1", "B"):
        refuted = reg.call("table.update", table="statements", id="000001",
                           patch={"status": "refuted",
                                  "abandon_basis": "引文第 3 步推不出来",
                                  "construction": "取 G = 完全图 K3"})
        hard = reg.call("table.update", table="statements", id="000002",
                        patch={"hard_to_prove": "引文没给完整严密证明"})
    assert refuted.ok is True, (refuted.error, refuted.meta)
    assert hard.ok is True, (hard.error, hard.meta)
    row1 = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == "000001")
    row2 = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == "000002")
    assert row1["status"] == "refuted"
    assert (row1["bits"].get("voided_by") or {}).get("kind") == "construction"
    assert row2["status"] == "active"
    assert EB.optimized_state(row2, 1) == "hard_to_prove"


def test_k2_the_write_face_refuses_the_three_shape_errors(tmp_path):
    """k 的负控：两个终态一笔交 / refuted 还带 abandon_kind / 未知键 —— 都受控拒。"""
    st = _ws(tmp_path)
    _put(st)
    reg, CND = _registry(st)
    with CND.calling_as("t-b1", "B"):
        both = reg.call("table.update", table="statements", id=SID,
                        patch={"status": "refuted", "hard_to_prove": "x",
                               "abandon_basis": "理由", "construction": "y"})
        kind = reg.call("table.update", table="statements", id=SID,
                        patch={"status": "refuted", "abandon_kind": "math_error",
                               "abandon_basis": "理由", "construction": "y"})
        unknown = reg.call("table.update", table="statements", id=SID,
                           patch={"hard_to_prove": "x", "bogus_key": 1})
    assert both.ok is False and dict(both.meta or {}).get("kind") == "retire_two_in_one_patch"
    assert kind.ok is False and dict(kind.meta or {}).get("kind") == "refute_kind_not_needed"
    assert unknown.ok is False
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    assert row["status"] == "active" and not (row.get("bits") or {}).get("voided_by")
    assert not EB.hard_to_prove_by_proof(row)
