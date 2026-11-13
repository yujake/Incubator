# -*- coding: utf-8 -*-
"""判据：难以自证的命题在论文里不许写成已证定理；承重的要上报、不落成文（业主 2026-11-13）。

## 业主原话（逐字）

「G 侧写论文时要读得懂：已优化 + 引文占位 V 签代表着难以自证，对这类命题需在论文中持保守态度。
若该命题承重，需报告要仔细研究，不敢落成文。」

## 这条判据读的是哪一个标记

不是"已优化 + 引文占位签"这个组合（业主同日更正：那个组合是刚被否决的形态），而是命题行上
那个显式的第四档标记：`bits.evidence.hard_to_prove_by_proof`（读口
`evidencebits.hard_to_prove_by_proof` 与 `optimized_state` 的 `hard_to_prove` 那一档）。
反真空①直接把那个标记打桩成空表：保守逻辑必须整条消失 —— 这比打桩 `optimized` 更能证明
它读的是直读，而不是"看起来像优化过又没真签"的组合推断。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 辅助断言引到难以自证的命题 ⇒ 正文不出现"已证明"形态，改成「引文所述，未经独立复核」，且读数点名它 | 改前照抄 `evidence_kind="proof"`、正文原样留着"已证明" |
| b | 承重断言引到难以自证的命题 ⇒ 不进正文；收件箱里有一条 message，正文含"需仔细研究" | 改前它照常写进正文、一条上报也没有 |
| c | 正控：真 V 签的命题照常写成定理（保守逻辑不许泛化到所有命题） | 泛化会让这一条红 |
| d | 反真空①：把 `hard_to_prove_by_proof` 打桩成空表 ⇒ a/b 的绿必须消失 | 打桩之后还绿 ⇒ 它读的不是那个标记 |
| e | 反真空②：把承重判定打桩成恒 False ⇒ b 的绿必须消失 | 承重那一条不是那条判据给的（那条断言是真空的） |
| f | 同一个实现也接在 `revise` 那个入口上（写稿与改稿是两个入口） | 只接 `build_document` ⇒ 改稿是后门 |

## 夹具里的角色

命题台账两条：`HARD_STMT`（记着难以自证）/ `CLEAN_STMT`（真 V 签）。一条 formal 实验行给
`evidence_kind="proof"` 的断言当证据锚（`doc_tools.check_proofs` 要它），证据落点是一份盘上
真有的 `.lean` 文件（与 `agent_g._selftest` 同一种最小夹具）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow.agent_g import AgentG
from agentflow.agent_g import hard_to_prove as HP
from agentflow.agent_loop import read_messages
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import doc_tools as DT

TS = "2026-11-13T00:00:00+08:00"
SID = "t"

#: 业主原话的体裁化写法（与 `hard_to_prove.HARD_TO_PROVE_CLAUSE` 逐字相同：
#: 判据这一边钉字面量、实现那一边钉常量，两边一起漂才会红）。
CLAUSE = "引文所述，未经独立复核"
RESEARCH_NEEDED = "需仔细研究"

LIT = S.format_id(0)
EXP = S.format_id(0)
HARD_STMT = S.format_id(1)
CLEAN_STMT = S.format_id(2)
PROOF_FILE = "proofs/note.lean"


# ============================================================ 夹具


def _statement(*, stmt_id: str, hard: bool, label: str) -> dict:
    """一条在册命题：`hard=True` 时带着「难以自证」的显式标记，否则是拿到真 V 签的那一条。"""
    if hard:
        bits = EB.with_hard_to_prove(
            EB.bits_of(proof=True, source_lit_id=LIT, origin="external_lit", quote_verified=True),
            1, basis="引文只给了结论，没有给出证明", at=TS,
        )
        row = S.Statement(
            stmt_id=stmt_id, origin="external_lit", kind="theorem", label=label,
            statement_text="X 对一切 n 成立", statement_full="X 对一切 n 成立（完整假设见引文）",
            proof_text="（引文没给证明）", source_lit_id=LIT,
            quote_verified=True, quote_reason="逐字比对通过", evidence_kind="cross_check",
            status="active", created_at=TS, bits=bits,
        )
        row.validate()
        return row.to_dict()
    bits = EB.bits_of(proof=True, reviewed=True, reviewed_by={"evidence": "v-000001"},
                      proof_process="逐步论证……")
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem", label=label,
        statement_text="Y 对一切 n 成立", statement_full="Y 对一切 n 成立（自有证明）",
        proof_text="Proof. 逐步论证……", quote_reason="自产：证明在 proof_text",
        status="active", created_at=TS, bits=bits,
    )
    row.validate()
    return row.to_dict()


def _store(tmp_path: pathlib.Path) -> Store:
    """最小工作区：1 篇文献 + 1 条 formal 实验 + 2 条命题（一条难以自证、一条真 V 签）。"""
    st = Store(tmp_path / "ws")
    st.init()
    (st.root / "proofs").mkdir(parents=True, exist_ok=True)
    (st.root / PROOF_FILE).write_text("theorem note : True := trivial\n", encoding="utf-8")
    with st.tx("literature", "experiments", "statements", actor="test", note="夹具") as tx:
        tx.upsert("literature", S.Literature(
            lit_id=LIT, title="一篇外部论文", type="J", summary="s", path=None, added_at=TS,
        ).to_dict())
        exp = S.Experiment(
            experiment_id=EXP, claim="X 对一切 n 成立", claim_key="Xforalln",
            method="formal", evidence_kind="proof", result="supports",
            negation_kind="not_proved",
            verifier_output="'Xforalln' does not depend on any axioms",
            verifier_subject_key="Xforalln", created_at=TS,
        )
        exp.validate()
        tx.upsert("experiments", exp.to_dict())
        tx.upsert("statements", _statement(
            stmt_id=HARD_STMT, hard=True, label="Theorem A（引文占位签）"))
        tx.upsert("statements", _statement(
            stmt_id=CLEAN_STMT, hard=False, label="Theorem B（真 V 签）"))
    return st


def _agent(st: Store) -> AgentG:
    return AgentG(st, config={"docs_subdir": "documents"})


def _main_claim(g: AgentG) -> dict:
    """承重断言：类型是定理、正文声张"已证明"、引那条难以自证的命题。"""
    return g.compose_claim(
        "本文主结果：X 对一切 n 成立，已证明。",
        citations=[f"exp:{EXP}", f"stmt:{HARD_STMT}"],
        evidence_kind="proof", section="主要结果", kind="定理",
        proof_location=f"{PROOF_FILE}:1",
    )


def _aux_claim(g: AgentG) -> dict:
    """辅助断言：类型是注、引同一条难以自证的命题。"""
    return g.compose_claim(
        "已证明：由该命题可得推论（这一条只是备注）。",
        citations=[f"exp:{EXP}", f"stmt:{HARD_STMT}"],
        evidence_kind="proof", section="备注", kind="注",
        proof_location=f"{PROOF_FILE}:1",
    )


def _clean_claim(g: AgentG) -> dict:
    """真 V 签那一条：正控 —— 它必须照常可以被写成定理。"""
    return g.compose_claim(
        "Y 对一切 n 成立，已证明。",
        citations=[f"exp:{EXP}", f"stmt:{CLEAN_STMT}"],
        evidence_kind="proof", section="主要结果", kind="定理",
        proof_location=f"{PROOF_FILE}:1",
    )


def _body(doc: dict, st: Store) -> str:
    """稿件 markdown 的正文（`markdown_path` 是工作区相对路径，落在 `store.root` 下）。"""
    return (pathlib.Path(str(st.root)) / str(doc["markdown_path"])).read_text(encoding="utf-8")


def _stored_claims(st: Store) -> list[dict]:
    rows = st.rows("documents")
    assert len(rows) == 1, rows
    return list(rows[0].get("claims") or [])


def _cites(claim: dict, stmt_id: str) -> bool:
    return f"stmt:{stmt_id}" in [str(x) for x in (claim.get("citations") or [])]


def _inbox(st: Store, role: str = "M") -> list[dict]:
    msgs, problems = read_messages(st.root, role, sid=SID)
    assert not problems, problems
    return msgs


# ============================================================ a) 保守表述


def assert_a_holds(st: Store, doc: dict) -> None:
    """判据 a 的全部断言（正控 a 与反真空①共用这一段：打桩之后它还绿 ⇒ 那条绿是真空的）。

    内容：证据档位降下来（于是「定理 / 已证明」写不进去）、不再声称"证"、正文带保守形态、
    没有过度声称措辞、读数点名了那条命题与依据、没有承重条目就不发上报。
    """
    claim = _stored_claims(st)[0]
    body = _body(doc, st)
    # 结构：证据档位被降下来（于是「定理 / 已证明」这类措辞再也写不进去）、不再声称"证"
    assert claim["evidence_kind"] == "heuristic", claim["evidence_kind"]
    assert "status" not in claim, "这一条不许留着 status='证'"
    assert claim["our_check"] == "只读了陈述" and claim["source_kind"] == "文献", claim
    # 正文：保守形态在、过度声称不在
    assert CLAUSE in claim["text"], claim["text"]
    assert "已证明" not in claim["text"], claim["text"]
    assert CLAUSE in body, body
    assert "已证明" not in body, "保守形态落下来之后，正文里不许再出现'已证明'"
    # 更宽的那一半：受控的过度声称措辞（`doc_tools.OVERCLAIM_MARKERS`）在这条断言的正文里
    # 一个都不许剩（正文整体不这么查：否定分类那张表里有 `disproved` / `not_proved` 两个
    # 受控取值，它们是词表本身，不是过度声称）
    hits = [m for m in DT.OVERCLAIM_MARKERS if m in claim["text"]]
    assert hits == [], f"这条断言里还有过度声称措辞 {hits}"
    # 读数点名它（命题 + 路径 + 依据）
    reading = doc["hard_to_prove"]
    assert reading["checked"] is True, reading
    row = next(r for r in reading["rows"] if f"stmt:{HARD_STMT}" in
               [f"stmt:{x}" for x in r["statement_ids"]])
    assert row["action"] == "attributed", row
    assert row["paths"] and "引文只给了结论" in row["paths"][0]["basis"], row
    # 这一份没有承重条目 ⇒ 不许发一条空上报
    assert reading["report"]["sent"] is False and _inbox(st) == [], reading["report"]


def test_a_hard_to_prove_proposition_is_not_written_as_a_proved_theorem(tmp_path: pathlib.Path):
    """a) 辅助断言引到难以自证 ⇒ 不出现"已证明"形态、改成「引文所述，未经独立复核」、读数点名。"""
    st = _store(tmp_path)
    g = _agent(st)
    doc = g.build_document("paper", "保守表述那一稿", claims=[_aux_claim(g)])
    assert_a_holds(st, doc)
    # 读数也进了这一趟的日志（"点名"在盘上看得到）
    assert any(HARD_STMT in line for line in g.logs), g.logs


# ============================================================ b) 承重 ⇒ 不落成文 + 上报


def assert_b_holds(st: Store, doc: dict) -> None:
    """判据 b 的全部断言（正控 b 与反真空①②共用这一段）。"""
    claims = _stored_claims(st)
    held = [c for c in claims if _cites(c, HARD_STMT)]
    assert held == [], f"承重那一条不许落进正文：{held}"
    assert [c for c in claims if _cites(c, CLEAN_STMT)], "其余断言照常写进正文"
    held_rows = [r for r in doc["hard_to_prove"]["rows"] if r["action"] == "held_back"]
    assert held_rows and HARD_STMT in held_rows[0]["statement_ids"], doc["hard_to_prove"]

    # 读者看得见"它为什么不在正文"（开放问题区那一句）
    body = _body(doc, st)
    assert RESEARCH_NEEDED in body, body
    assert "难以自证" in body, body
    assert "本文主结果" not in body, "承重那一条的正文不许出现在稿里（这是'不落成文'那一半）"
    # 上报：同一条收件箱通道、不停这一趟（`message`）
    report = doc["hard_to_prove"]["report"]
    assert report["sent"] is True, report
    msgs = _inbox(st)
    assert len(msgs) == 1, ("承重的那一条必须有一条 message 上报", msgs)
    message = msgs[0]
    assert message["to"] == "M" and message["from"] == "G", message
    assert RESEARCH_NEEDED in message["body"], message["body"]
    assert f"stmt:{HARD_STMT}" in message["body"], message["body"]
    assert "承重" in message["body"], message["body"]


def test_a_load_bearing_hard_to_prove_claim_is_held_back_and_reported(tmp_path: pathlib.Path):
    """b) 承重 ⇒ 不进正文（原因进开放问题区）+ 收件箱里一条 message，正文含"需仔细研究"。"""
    st = _store(tmp_path)
    g = _agent(st)
    with calling_as(S.format_id(2), "G", parent_task_id=S.format_id(1), parent_role="M",
                    session_root=str(st.root), sid=SID):
        doc = g.build_document("paper", "承重那一条不落成文",
                               claims=[_main_claim(g), _clean_claim(g)])
    assert_b_holds(st, doc)


def test_a_revision_holds_back_the_same_load_bearing_claim(tmp_path: pathlib.Path):
    """f) 同一个实现也接在 `revise` 那个入口上：改稿不是后门。"""
    st = _store(tmp_path)
    g = _agent(st)
    doc = g.build_document("paper", "先有一稿", claims=[_clean_claim(g)])
    with calling_as(S.format_id(2), "G", parent_task_id=S.format_id(1), parent_role="M",
                    session_root=str(st.root), sid=SID):
        out = g.revise(str(doc["doc_id"]), new_claims=[_main_claim(g)], note="按审校意见加一条主结果")
    claims = _stored_claims(st)
    assert [c for c in claims if _cites(c, HARD_STMT)] == [], claims
    assert [c for c in claims if _cites(c, CLEAN_STMT)], claims
    assert out["hard_to_prove"]["held_back"], out["hard_to_prove"]
    assert out["hard_to_prove"]["report"]["sent"] is True, out["hard_to_prove"]["report"]
    assert RESEARCH_NEEDED in _inbox(st)[0]["body"]


# ============================================================ c) 正控：真 V 签照常写定理


def test_a_real_v_sign_still_buys_a_theorem(tmp_path: pathlib.Path):
    """c) 正控：真 V 签的命题 ⇒ 照常写成定理（保守逻辑不许泛化到所有命题）。"""
    st = _store(tmp_path)
    g = _agent(st)
    doc = g.build_document("paper", "真签那一稿", claims=[_clean_claim(g)])
    claim = _stored_claims(st)[0]
    assert claim["evidence_kind"] == "proof", claim
    assert "status" not in claim or claim["status"] == "证", claim
    assert CLAUSE not in claim["text"], claim["text"]
    assert "已证明" in claim["text"], claim["text"]
    assert doc["hard_to_prove"]["rows"] == [], doc["hard_to_prove"]
    assert _inbox(st) == []


# ============================================================ d) 反真空①：打桩那个标记


def test_stubbing_the_marker_brings_the_overclaim_back(tmp_path: pathlib.Path, monkeypatch):
    """d) 把 `hard_to_prove_by_proof` 打桩成空表 ⇒ a/b 必红（它读的就是那个标记）。

    这里直接拿 a/b 那两段断言（`assert_a_holds` / `assert_b_holds`）在打桩后的盘上跑：
    两段都必须抛 AssertionError。若它们仍是绿的，说明那两条绿根本没读这个标记
    （而是"看起来像优化过又没真签"的组合推断，或者别的什么）。
    """
    st = _store(tmp_path)
    g = _agent(st)
    monkeypatch.setattr(EB, "hard_to_prove_by_proof", lambda row: {})
    with calling_as(S.format_id(2), "G", parent_task_id=S.format_id(1), parent_role="M",
                    session_root=str(st.root), sid=SID):
        doc = g.build_document("paper", "打桩之后", claims=[_aux_claim(g), _main_claim(g)])

    with pytest.raises(AssertionError):
        assert_a_holds(st, doc)
    with pytest.raises(AssertionError):
        assert_b_holds(st, doc)

    # 红在哪：保守形态整条消失 —— 正文回到"已证明"、承重那一条照常写进正文、一条上报都没有
    claims = _stored_claims(st)
    aux = next(c for c in claims if c.get("kind") == "注")
    assert aux["evidence_kind"] == "proof", aux
    assert "已证明" in aux["text"] and CLAUSE not in aux["text"], aux["text"]
    assert "已证明" in _body(doc, st)
    assert [c for c in claims if _cites(c, HARD_STMT)], "打桩之后它又落回正文了"
    assert doc["hard_to_prove"]["rows"] == [], doc["hard_to_prove"]
    assert _inbox(st) == []


# ============================================================ e) 反真空②：打桩承重判定


def test_stubbing_load_bearing_drops_the_report(tmp_path: pathlib.Path, monkeypatch):
    """e) 把承重判定打桩成恒 False ⇒ b 必红（承重的处置是那条判据给的）。"""
    st = _store(tmp_path)
    g = _agent(st)
    monkeypatch.setattr(HP, "is_load_bearing", lambda claim: False)
    with calling_as(S.format_id(2), "G", parent_task_id=S.format_id(1), parent_role="M",
                    session_root=str(st.root), sid=SID):
        doc = g.build_document("paper", "打桩承重之后", claims=[_main_claim(g), _clean_claim(g)])

    with pytest.raises(AssertionError):
        assert_b_holds(st, doc)

    # 红在哪：它被当成辅助件 ⇒ 落回正文（保守形态）、没有上报、开放问题区也没有那句
    claims = _stored_claims(st)
    kept = [c for c in claims if _cites(c, HARD_STMT)]
    assert kept, "承重判定被摘掉之后它又落回正文了"
    assert kept[0]["evidence_kind"] == "heuristic" and CLAUSE in kept[0]["text"], kept[0]
    assert doc["hard_to_prove"]["held_back"] == [], doc["hard_to_prove"]
    assert doc["hard_to_prove"]["report"]["sent"] is False, doc["hard_to_prove"]["report"]
    assert _inbox(st) == [], "没有承重条目就不许发上报"
    assert RESEARCH_NEEDED not in _body(doc, st), "它不在承重那一档时，开放问题区不许写那句"
