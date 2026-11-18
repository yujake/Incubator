# -*- coding: utf-8 -*-
"""K10 判据：凭据面与输入面按「我这条链 + 活跃集」读（不再读工作区全局）。

## 缺口（清单 K10 两条 P + 真机现场）

- `GD-03`：G 的成文门读工作区全局读数 —— 只要工作区里有任意一份别人的签，
  或任意一条带证明正文的命题，门就放行（真机 G1 的拒信逐字引用全局读数
  「签 0 份、待签稿 2 份」，而那两份稿与它要写的 kind=note 总结稿没有引用关系）。
- `GD-04`：门里的「待签稿」清单也是全局列表 ⇒ 门只会说"要等全工作区清零"。
- `HR-02`：H 的 `selftest` 取 `documents` 第一行去跑一次真复审 —— 拿别人的稿当输入。

## 这一组守什么

d) 成文门按这份成文的 claims 所引的命题读凭据：别的实例有签不算我有签（改前红：
   全局签数放行）；我自己这条链上有签才放行（正控）；一条命题都没引 ⇒ 受控拒；
   待签清单只列我这条链上的稿（改前红：列全工作区的稿）；
e) M 的巡查用 `lifecycle.state_of_manuscript` 的活跃集判「待签」：已完工（拿到签）
   的稿不进 `manuscript_unsigned`（哪怕签字表那一格读成"没签"）；
f) H 的自检不审任何一份稿：`documents` / `review_findings` 一个字节不变
   （改前红：`selftest` 在 `documents[0]` 上落发现并改 status）；
g) 反真空：把范围读数打桩成"全局"（`signs_reading` 忽略 `statements`）⇒ d 必红。

边界：全部 tmp 工作区、假时钟，零真实模型调用、不碰 `projects/`。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import lifecycle as LC
from agentflow import researchbase as RB
from agentflow import researchpending as RP
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools.conductor_tools import conductor_for

TS = "2026-11-18T10:00:00+08:00"
MINE = "000000"
OTHER = "000001"
PROOF = "1. 取 ε>0，按定义逐点验证。\n2. 第 1 步只依赖 ε ⇒ 一致连续。"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    conductor_for(st)
    build_registry(store=st, workspace_root=pathlib.Path(st.root))
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    return st


def _statement(st: Store, sid: str, *, proof: str = "", status: str = "active",
               quote_reason: str = "", manuscripts: dict | None = None) -> None:
    row = {"stmt_id": sid, "origin": "own_result", "kind": "theorem",
           "label": f"夹具命题 {sid}", "statement_full": "夹具命题",
           "statement_text": "夹具命题", "proof_text": proof,
           "evidence_kind": "proof" if proof else "heuristic", "status": status,
           "quote_verified": None,
           "quote_reason": quote_reason or "夹具：这一条没有可比的全文 ⇒ 还没校验",
           "created_at": TS, "created_by": "secretary-B",
           "manuscripts": dict(manuscripts or {})}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def _manuscript(st: Store, mid: str) -> str:
    rel = f"reports/f-proof-{mid}.md"
    (pathlib.Path(st.root) / rel).write_text("# 稿\n\n## 证明\n\n推导……\n",
                                             encoding="utf-8")
    return rel


def _sign(st: Store, rel: str, *, statement_id: str = "", sha: str = "a" * 64) -> str:
    d = pathlib.Path(st.root) / "out" / "vsigns"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "vsign/1", "artifact_sha": sha, "artifact_path": rel,
           "statement_id": statement_id, "at": TS, "verdict": "成立",
           "streak": 3, "need": 3, "ledger": "", "written_by": "secretary:F"}
    (d / f"{sha}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return sha


def _claims(*sids: str) -> list[dict]:
    return [{"text": "夹具断言", "citations": [f"stmt:{sid}" for sid in sids],
             "evidence_kind": "cross_check", "section": "1",
             "disclaimer": "夹具"}]


# ============================================================ d：成文门按我的链读
def test_d_another_instances_sign_does_not_let_me_write(tmp_path):
    """d1 别人的稿有签、我这条链没有 ⇒ 受控拒（改前红：全局签数放行）。"""
    st = _ws(tmp_path)
    _statement(st, MINE)                       # 我的命题：只有标题
    _statement(st, OTHER)
    _manuscript(st, MINE)                      # 我这条链上有一份待签稿
    _sign(st, _manuscript(st, OTHER), statement_id=OTHER)
    # 全局读数确实有 1 份签（这一条防止"拒是因为签目录没读到"）。
    assert (RB.signs_reading(st) or {}).get("signs") == 1
    gate = RB.writing_gate(st, claims=_claims(MINE))
    assert gate["refuse"] is True, gate
    assert gate["kind"] == "no_evidence_chain", gate
    signing = dict(gate["signing"] or {})
    assert int(signing.get("signs") or 0) == 0, signing
    assert int(signing.get("signs_total") or 0) == 1, signing
    # 待签清单只列我这条链上的稿（改前：全工作区的稿都列）。
    assert signing.get("pending_manuscripts") == [f"reports/f-proof-{MINE}.md"], signing


def test_d_my_own_sign_lets_the_gate_through(tmp_path):
    """d2 正控：我自己这条链上有签 ⇒ 放行（不许一刀切）。"""
    st = _ws(tmp_path)
    _statement(st, MINE)
    _sign(st, _manuscript(st, MINE), statement_id=MINE)
    gate = RB.writing_gate(st, claims=_claims(MINE))
    assert gate["refuse"] is False, gate
    assert gate["base"]["state"] == "ready", gate["base"]


def test_d_without_any_cited_statement_the_gate_is_a_floor_not_a_credential(tmp_path):
    """d3 只引文献、不引命题 ⇒ 凭据门没有对象：退到「工作区里有没有研究产出」的下限。

    这一档刻意与 d1 分开：d1 是凭据（"我这条链有没有签"），d3 是下限
    （"工作区里有没有任何可依赖的产出"，旧 DOCGATE1 口径）。读数里逐字记
    `credential_scope="none"`，读的人不会把它读成"我有签"。
    """
    st = _ws(tmp_path)
    _statement(st, OTHER, proof=PROOF)          # 工作区里确有研究产出
    _sign(st, _manuscript(st, OTHER), statement_id=OTHER)
    gate = RB.writing_gate(st, claims=[{"text": "夹具", "citations": ["lit:0001"],
                                       "evidence_kind": "cross_check"}])
    assert gate["refuse"] is False, gate
    assert (gate["details"] or {}).get("credential_scope") == "none", gate
    # 反方向：工作区里一条产出都没有 ⇒ 下限照样拒。
    st2 = _ws(tmp_path / "empty")
    gate2 = RB.writing_gate(st2, claims=[{"text": "夹具", "citations": ["lit:0001"],
                                         "evidence_kind": "cross_check"}])
    assert gate2["refuse"] is True, gate2
    assert gate2["kind"] == "no_evidence_chain", gate2


def test_d_a_completed_manuscript_is_not_pending(tmp_path):
    """d4 已完工（拿到签）的稿不进「待签」：生命周期是唯一判据。"""
    st = _ws(tmp_path)
    rel = _manuscript(st, MINE)
    _statement(st, MINE)
    _sign(st, rel, statement_id=MINE)
    reading = RB.signs_reading(st, statements=(MINE,))
    assert reading["pending"] == 0, reading
    assert LC.state_of_manuscript(st, rel)["state"] == LC.COMPLETED


def test_d_an_abandoned_statement_is_not_pending(tmp_path):
    """d5 命题被明确放弃 ⇒ 稿不在活跃集 ⇒ 不算「待签」。"""
    st = _ws(tmp_path)
    rel = _manuscript(st, MINE)
    _statement(st, MINE, status="abandoned",
               quote_reason=f"abandoned@{TS}@夹具：明确放弃",
               manuscripts={"1": rel})
    reading = RB.signs_reading(st, statements=(MINE,))
    assert reading["pending"] == 0, reading
    assert LC.state_of_manuscript(st, rel)["state"] == LC.ABANDONED


# ============================================================ e：M 的巡查按活跃集
def test_e_patrol_does_not_count_a_completed_manuscript_as_unsigned(tmp_path, monkeypatch):
    """e 签字表读成"没签"也没用：生命周期说完工 ⇒ `manuscript_unsigned` 是 0。"""
    st = _ws(tmp_path)
    rel = _manuscript(st, MINE)
    _statement(st, MINE)
    _sign(st, rel, statement_id=MINE)
    assert RP.pending_reading(st)["counts"]["manuscript_unsigned"] == 0

    from agentflow.agent_f import vsign as FV

    def _unsigned(*_a, **_k):
        return {"state": FV.STATE_WAITING, "label": "等签", "delivered": False,
                "checked": True, "why": "反真空：签字表这一格读成没签", "sha": ""}

    monkeypatch.setattr(FV, "delivery_reading", _unsigned)
    reading = RP.pending_reading(st)
    assert int(reading["counts"]["manuscript_unsigned"]) == 0, reading["counts"]


# ============================================================ f：H 的自检不审别人的稿
def test_f_h_selftest_never_reviews_a_foreign_document(tmp_path):
    """f `selftest` 不再取 `documents[0]` 审：两份稿、账一个字节不变。"""
    from agentflow.agent_h import AgentH
    from agentflow.agent_h._support import _seed_document

    st = _ws(tmp_path)
    _seed_document(st, doc_id="0000", claims=[{
        "claim_id": "claim-0", "text": "夹具断言", "citations": ["stmt:000000"],
        "evidence_kind": "cross_check", "section": "1", "disclaimer": "夹具"}])
    _seed_document(st, doc_id="0001", claims=[{
        "claim_id": "claim-0", "text": "另一份夹具断言", "citations": ["stmt:000001"],
        "evidence_kind": "cross_check", "section": "1", "disclaimer": "夹具"}])
    before_docs = [dict(r) for r in st.rows("documents")]
    before_findings = [dict(r) for r in st.rows("review_findings")]
    h = AgentH(st)
    rc = h.selftest()
    assert rc in (0, 1), rc
    # 自检连"读过一份稿"都不该发生：落库代理一次都没被调用（改前这里会 review
    # documents[0]，tool_calls 里留下 review.review_document）。
    assert [str(x.get("tool")) for x in (h.tool_calls or ())] == [], h.tool_calls
    after_docs = [dict(r) for r in st.rows("documents")]
    after_findings = [dict(r) for r in st.rows("review_findings")]
    assert [(r["doc_id"], r.get("status"), r.get("review_rounds")) for r in after_docs] == \
        [(r["doc_id"], r.get("status"), r.get("review_rounds")) for r in before_docs]
    assert after_findings == before_findings, "自检在别人的稿上落了发现"


# ============================================================ g：反真空
def test_g_a_global_signs_reading_turns_d1_green(tmp_path, monkeypatch):
    """g 把范围读数打桩成"全局"（`signs_reading` 忽略 statements）⇒ d1 必红。"""
    st = _ws(tmp_path)
    _statement(st, MINE)
    _statement(st, OTHER)
    _sign(st, _manuscript(st, OTHER), statement_id=OTHER)
    real = RB.signs_reading

    def _global(store, *, root=None, statements=None):
        return real(store, root=root, statements=None)   # 打桩：范围整格摘掉（改前口径）

    monkeypatch.setattr(RB, "signs_reading", _global)
    gate = RB.writing_gate(st, claims=_claims(MINE))
    assert gate["refuse"] is False, gate     # d1 的"受控拒"在这一档必红
    with pytest.raises(AssertionError):
        assert gate["refuse"] is True, gate
