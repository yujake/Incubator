# -*- coding: utf-8 -*-
"""丙 + 边集 + D 的向上汇报（2026-11-11 业主裁定）。

## 裁定的三句（逐字）

```
「出边形状错误。更改 G 的出边集为 C,D,H，H 为 G 的下级不召唤 G」
「G 想补内容都走 D」
「D 不能指向 G，G 是 D 的父，是向上汇报完成任务」
```

## 落成结构

- `specs/g.py` 的 `edges`：`('C','D','H')`（去掉 A/E/F）；
- `specs/h.py` 的 `edges`：`('A','E')`（去掉 G）；
- `specs/d.py` **不动**（D 的出边保持 `{A,B,C,E,F}`；D 是子，汇报是"向上"，不是召唤）；
- 补内容的链：G 派 D → D 调 A/E/F 补 → D 交台账、B 收录 → **D 向上汇报只带指针**
  （`send_message` + 收件箱，不是 summon 一条新边）→ G 去台账读。

## 判据

- a/d 边集：`ALLOWED_EDGES['G'] == {'C','D','H'}`、`'G' not in ALLOWED_EDGES['H']`、
  `ALLOWED_EDGES['D']` 仍含 `{'A','E','F'}` 且**不含 G**；
- b/f 端到端：G 派 H ⇒ 通；H 派 G ⇒ 受控拒；反真空：把边改回 A/D/E/F（并给 H 加回 G）⇒ 两条都放行；
- e 题面：G 的 policy 有「补内容走 D」、没有旧说法「你能召唤的只有 A / D / E / F」；
  H 的 policy 没有「请 G 修订」；
- g 链：G 派 D ⇒ D 补 ⇒ B 收录成功 ⇒ 向上汇报点名指针（无正文）⇒ G 从台账读到；
- h 反控：B 受控拒 ⇒ 汇报明写「没进台账」，不许出现"已完成/已入库"；
- i 反真空：D 的边表若被加上 G ⇒ 结构判据红；
- 丙 g/i：`revise` 的返回值与收工读数都有 `next_step` 指向 `H.verify_fixes`；摘掉它 ⇒ g 红。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import capabilities as C
from agentflow import conductor as CO
from agentflow import policy as P
from agentflow import schema as S
from agentflow import statementledger as SL
from agentflow.agent_d import AgentD
from agentflow.agent_g import AgentG
from agentflow.store import Store

from test_p1a_revise_records_body_sha import _workspace
from test_scheduler import FakeG, FakeH, _Recorder, _conductor, _mk_store


# ============================================================ a/d 边集


def test_a_the_edges_are_c_d_h_and_h_has_no_g() -> None:
    assert C.ALLOWED_EDGES["G"] == frozenset({"C", "D", "H"}), sorted(C.ALLOWED_EDGES["G"])
    assert "G" not in C.ALLOWED_EDGES["H"], sorted(C.ALLOWED_EDGES["H"])
    assert C.ALLOWED_EDGES["H"] == frozenset({"A", "E"}), sorted(C.ALLOWED_EDGES["H"])
    # 转交链没断：D 仍然能调 A/E/F（G 补内容只能经 D）
    assert {"A", "E", "F"} <= C.ALLOWED_EDGES["D"], sorted(C.ALLOWED_EDGES["D"])
    # 「D 不能指向 G，G 是 D 的父」⇒ D 的出边不含 G（汇报不是召唤）
    assert "G" not in C.ALLOWED_EDGES["D"], sorted(C.ALLOWED_EDGES["D"])


# ============================================================ b/f 端到端


def test_b_g_may_summon_h_and_h_may_not_summon_g(tmp_path: pathlib.Path):
    store = _mk_store(tmp_path)
    c = _conductor(store, registry={"G": ("object", FakeG()),
                                    "H": ("object", FakeH(_Recorder()))})
    g_task = c.summon("G", "revise", {"doc_id": "0001"})
    assert g_task.outcome == "ok", g_task

    h_task = c.summon("H", "review", {"doc_id": "0001"}, by="G",
                      parent_task_id=g_task.task_id, input_key="g-to-h")
    assert h_task.outcome == "ok", h_task

    back = c.summon("G", "revise", {"doc_id": "0001"}, by="H",
                    parent_task_id=h_task.task_id, input_key="h-to-g")
    assert back.outcome == "refused", back
    assert back.refusal_reason == "forbidden_edge", back
    assert back.detail and "边" in back.detail, back.detail


def test_f_putting_the_old_edges_back_would_allow_h_to_summon_g(monkeypatch) -> None:
    """反真空：边集改回旧值（并给 H 加回 G）⇒ G→A 与 H→G 都放行（a/b 都会红）。"""
    monkeypatch.setitem(C.ALLOWED_EDGES, "G", frozenset({"A", "D", "E", "F"}))
    monkeypatch.setitem(C.ALLOWED_EDGES, "H", frozenset({"A", "E", "G"}))
    # 不给 registry：`edges_for` 走派生层（给了 registry 它读声明层，打桩就失效）
    assert P.check(P.Policy(), _d("G", "A", "run_once")) is None
    assert P.check(P.Policy(), _d("H", "G", "revise")) is None


def _d(frm: str, to: str, action: str):
    return P.Decision(frm=frm, to=to, action=action)


# ============================================================ e 题面


def test_e_g_policy_routes_content_through_d_and_h_never_summons_g() -> None:
    from agentflow.specs.g import SPEC as G_SPEC
    from agentflow.specs.h import SPEC as H_SPEC

    g_text = "\n".join(G_SPEC.brief.policy) + "\n" + "\n".join(G_SPEC.brief.boundary)
    h_text = "\n".join(H_SPEC.brief.policy) + "\n" + "\n".join(H_SPEC.brief.boundary)
    h_text += "\n" + "\n".join(str(v) for v in H_SPEC.local_notes.values())

    assert "补内容都走 D" in g_text, "G 的 policy 没写「补内容走 D」"
    assert "把缺口提给 D" in g_text, "G 的 policy 没写「把缺口提给 D」"
    assert "你只能召唤 C / D / H" in g_text, "G 的 policy 没点名新的可召唤面"
    assert "你能召唤的只有 A / D / E / F" not in g_text, "G 的 policy 还留着旧的可召唤面"
    # 丙 h：改完必须送回 H 复审
    assert "改完稿必须送回 H 复审" in g_text and "未复审不许交差" in g_text, g_text
    # H 侧：不许暗示"可以找 G"
    assert "请 G 修订" not in h_text, "H 的题面还在暗示它可以找 G"
    assert "不许召唤 G" in h_text, "H 的题面没写「不许召唤 G」"


# ============================================================ 丙 g/i：revise 的 next_step


def test_g_revise_returns_next_step_pointing_at_verify_fixes(store: Store):
    g, doc_id, _tex = _workspace(store)
    rv = g.revise(doc_id, note="丙：改完送回 H")
    assert "next_step" in rv, rv
    assert "H.verify_fixes" in rv["next_step"], rv["next_step"]
    assert "改完" in rv["next_step"] and "复核" in rv["next_step"], rv["next_step"]


def test_i_removing_next_step_makes_g_red(store: Store, monkeypatch):
    """反真空：把 `next_step` 摘掉 ⇒ g 的断言红。"""
    import agentflow.agent_g.revise as RV_MOD

    monkeypatch.setattr(RV_MOD, "REVISE_NEXT_STEP", "")
    g, doc_id, _tex = _workspace(store)
    rv = g.revise(doc_id, note="反真空")
    assert rv["next_step"] == ""


# ============================================================ D 的向上汇报（g/h）


class _FakeB:
    def __init__(self, *, ok: bool, error: str = "") -> None:
        self.ok = ok
        self.error = error
        self.calls: list[dict] = []

    def register_statement(self, **kw):
        self.calls.append(dict(kw))
        return {"ok": self.ok, "stmt_id": "000001" if self.ok else "", "deps_written": 2,
                "manuscript_source": "carried_by_D", "error": self.error}


_STMT_TEXT = "命题 000001：谱落在闭区间内（台账里的正文，不在汇报里）。"
_MANUSCRIPT = "reports/f-proof-000001.md"


def _d_store(tmp_path: pathlib.Path) -> tuple[Store, str]:
    store = Store(tmp_path / "ws")
    store.init()
    row = S.Statement(
        stmt_id="000001", origin="own_result", kind="theorem", label="在册命题 000001",
        statement_text="谱落在闭区间内", statement_full=_STMT_TEXT,
        proof_text="证明：由定义直接得到。", evidence_kind="heuristic", status="active",
        quote_verified=None, quote_reason="夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B",
    )
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    (store.root / _MANUSCRIPT).parent.mkdir(parents=True, exist_ok=True)
    (store.root / _MANUSCRIPT).write_text(
        "## 命题\n\n谱落在闭区间内。\n\n## 证明\n\n由定义直接得到。\n", encoding="utf-8")
    return store, "000001"


def _write_report_as_child_d(store: Store, b: _FakeB, *, task_id: str = "t-000101"):
    """在 `calling_as` 里跑 D 的交付（父 = G）⇒ 汇报走收件箱。"""
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {
            "task_id": task_id, "role": "D", "action": "write_report", "called_by": "G",
            "status": "running", "input_key": "chain", "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": None, "outcome": None, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        })
    d = AgentD(store, b=b)
    d._carried_manuscripts = lambda: ([{
        "statement_id": "000001", "path": _MANUSCRIPT, "manuscript_id": "", "sha256": "",
    }], "夹具：F 的稿")
    with CO.calling_as(task_id, "D", parent_role="G",
                       session_root=str(store.root), sid="testsid"):
        d.write_report()
    return d


def test_g_the_chain_reports_pointers_and_g_reads_the_ledger(tmp_path: pathlib.Path):
    """G 派 D ⇒ B 收录成功 ⇒ D 的向上汇报只带指针 ⇒ G 从台账读到（不是从汇报正文）。"""
    from agentflow.agent_loop import inbox_digest

    store, stmt_id = _d_store(tmp_path)
    b = _FakeB(ok=True)
    d = _write_report_as_child_d(store, b)

    report = d.last_delivery["parent_report"]
    assert report["checked"] is True and report["sent"] is True, report
    assert report["to"] == "G", report

    digest, fresh, problems = inbox_digest(store.root, "G", sid="testsid", window=None)
    assert not problems, problems
    assert fresh, "汇报没有落进 G 的收件箱"
    text = digest
    assert "D 交付汇报" in text, text
    assert f"stmt:{stmt_id}" in text, text
    # 指针，不是正文：台账里的命题正文一个字都不在汇报里
    assert _STMT_TEXT not in text, text
    assert "不属于" not in text

    # G 拿东西一律去台账读
    got = SL.by_id(store, stmt_id=stmt_id)
    assert got["checked"] and got["found"], got
    assert got["row"]["statement_full"] == _STMT_TEXT, got
    # 反证：G 读到的那一句不是从汇报正文里取的
    assert _STMT_TEXT not in text


def test_h_a_refused_ingest_is_reported_as_not_in_the_ledger(tmp_path: pathlib.Path):
    """反控：B 收录被受控拒 ⇒ 汇报明写「没进台账、原因是…」，不许写成办成了。"""
    from agentflow.agent_loop import inbox_digest

    store, _stmt_id = _d_store(tmp_path)
    b = _FakeB(ok=False, error="受控拒绝：稿上没有 V 签（no_sign）")
    d = _write_report_as_child_d(store, b)

    report = d.last_delivery["parent_report"]
    assert report["sent"] is True and report["failed"], report
    digest, _fresh, _problems = inbox_digest(store.root, "G", sid="testsid", window=None)
    assert "没进台账" in digest, digest
    assert "受控拒" in digest, digest
    assert "no_sign" in digest, digest
    assert "收录成功" not in digest, digest
    assert "已完成" not in digest and "已入库" not in digest, digest


def test_i_adding_a_g_edge_to_d_is_caught(monkeypatch) -> None:
    """反真空：给 D 加上 G 的边 ⇒ 结构判据红（汇报是向上，不是召唤）。"""
    tampered = {role: frozenset(t) for role, t in C.ALLOWED_EDGES.items()}
    tampered["D"] = frozenset(set(tampered["D"]) | {"G"})
    monkeypatch.setattr(C, "ALLOWED_EDGES", tampered)
    assert "G" in C.ALLOWED_EDGES["D"]
    assert C.ALLOWED_EDGES["D"] != frozenset({"A", "B", "C", "E", "F"})


# ============================================================ j/k/l：成文前先派 C 拿依赖链


def _stmt(store: Store, sid: str) -> None:
    row = S.Statement(
        stmt_id=sid, origin="own_result", kind="theorem", label=f"在册命题 {sid}",
        statement_text=f"命题 {sid}", statement_full=f"命题 {sid} 的完整正文。",
        proof_text=f"证明 {sid}：由定义直接得到。", evidence_kind="heuristic",
        status="active", quote_verified=None,
        quote_reason="夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B",
    )
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())


class _FakeC:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def proof_chain(self, target, **kw):
        self.calls.append({"target": target, **kw})
        return {"checked": True, "target": str(target),
                # 根 → 叶（C 的 proof_chain 返回的 chain 就是这个顺序）
                "chain": ["000001", "000002"], "summary": "夹具：两条的依赖链"}


def _c_chain_via_summon(tmp_path: pathlib.Path):
    store = _mk_store(tmp_path)
    _stmt(store, "000001")
    _stmt(store, "000002")
    fake_c = _FakeC()
    c = _conductor(store, registry={"G": ("object", FakeG()), "C": ("object", fake_c)})
    parent = c.summon("G", "revise", {"doc_id": "0001"})
    assert parent.outcome == "ok", parent
    got = c.summon("C", "proof_chain", {"target": "000002"}, by="G",
                   parent_task_id=parent.task_id, input_key="g-to-c")
    assert got.outcome == "ok", got
    return store, got, fake_c


def _doc_follows_chain(claims: list[dict], chain: list[str]) -> list[str]:
    """稿子那一段是否「先根后叶、每一步点得到被依赖那条」。"""
    problems: list[str] = []
    if len(claims) != len(chain):
        problems.append(f"断言数 {len(claims)} != 链长 {len(chain)}")
        return problems
    for i in range(1, len(chain)):
        need = f"stmt:{chain[i - 1]}"
        if need not in (claims[i].get("citations") or []):
            problems.append(f"第 {i} 条（{chain[i]}）没有点它的依赖 {need}")
    return problems


def test_j_g_policy_says_ask_c_for_the_dependency_chain_before_writing() -> None:
    from agentflow.specs.g import SPEC as G_SPEC

    text = "\n".join(G_SPEC.brief.policy)
    assert "派 C" in text and "依赖链" in text, text
    assert "proof_chain" in text, "G 的 policy 没点名 C 的 proof_chain"
    assert "paths" in text, "G 的 policy 没点名 C 的 paths"
    assert "先根后叶" in text, "G 的 policy 没写「先根后叶」"
    assert "不许自己猜依赖" in text, "G 的 policy 没写「不许自己猜依赖」"


def test_k_chain_from_c_is_really_used_by_the_document(tmp_path: pathlib.Path):
    """G 派 C（带 stmt:<号>）⇒ C 返回链 ⇒ 稿子的顺序/凭据与链一致（先根后叶）。"""
    store, got, fake_c = _c_chain_via_summon(tmp_path)
    payload = got.payload
    assert payload["checked"] is True and payload["chain"] == ["000001", "000002"], payload
    assert fake_c.calls and fake_c.calls[0]["target"] == "000002", fake_c.calls

    from agentflow.agent_g import AgentG
    from agentflow.tools import doc_tools as DT
    from conftest import add_literature

    add_literature(store, "0000", title="根文献", processed=True)
    g = AgentG(store, workspace_root=store.root)
    claims = [
        {"claim_id": "c-root", "section": "主要结果", "text": "根命题。",
         "evidence_kind": "heuristic", "citations": ["lit:0000"],
         "is_negative": False, "negation_kind": None},
        {"claim_id": "c-leaf", "section": "主要结果", "text": "叶命题（依赖根）。",
         "evidence_kind": "heuristic", "citations": ["stmt:000001"],
         "is_negative": False, "negation_kind": None},
    ]
    built = g.build_document("paper", "丙 k 探针稿", claims=claims,
                             sections=[{"heading": "主要结果", "body": "根 → 叶。"}])
    doc = next(dict(r) for r in store.rows("documents")
               if str(r["doc_id"]) == str(built["doc_id"]))
    assert _doc_follows_chain(list(doc["claims"]), payload["chain"]) == [], doc["claims"]

    # 反控（l 的后半）：跳过 C 的链、按"叶 → 根"直接写 ⇒ 同一条判据红
    reversed_claims = [list(doc["claims"])[1], list(doc["claims"])[0]]
    assert _doc_follows_chain(reversed_claims, payload["chain"]), reversed_claims


def test_l_removing_the_c_paragraph_makes_j_red() -> None:
    """反真空：把「成文前派 C 拿依赖链」这一段摘掉 ⇒ j 的字面扫描红。"""
    from agentflow.specs.g import SPEC as G_SPEC

    kept = tuple(p for p in G_SPEC.brief.policy
                 if "成文之前，先派 C 把每一条要用到的成果的依赖链拿来" not in str(p))
    assert len(kept) == len(G_SPEC.brief.policy) - 1, "夹具前提：那一段真的在 policy 里"
    text = "\n".join(kept)
    assert "proof_chain" not in text or "先根后叶" not in text, "摘掉之后仍像 j 一样通过"
