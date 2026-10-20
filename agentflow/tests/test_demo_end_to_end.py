"""离线端到端：A → B → verify 整条链路（DESIGN.md §7 的 `agentflow demo`）。

产物一律落在 ``tmp_path``（``run_demo`` 会在其中新建 demo/ ），
绝不写 ``test/test1/demo/run/``。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.demo import run_demo
from agentflow.extract import extract_text
from agentflow.llm import OfflineFixtureExtractor
from agentflow.store import Store
from agentflow.verify import verify_all


@pytest.fixture(scope="module")
def demo_root(tmp_path_factory) -> Path:
    """在临时目录里跑一次 demo（reset=True），返回工作区根。"""
    root = tmp_path_factory.mktemp("demo-e2e")
    run_demo(root, reset=True, verbose=False)
    return root


@pytest.fixture(scope="module")
def demo_store(demo_root: Path) -> Store:
    return Store(demo_root / "demo" / "run")


def test_run_demo_returns_zero(tmp_path: Path) -> None:
    """demo 的全部内置判定必须通过（返回 0），否则说明整条链路有回归。"""
    assert run_demo(tmp_path, reset=True, verbose=False) == 0


def test_demo_requests_and_literature_products(demo_store: Store) -> None:
    """产物：3 条请求全 done、6 个候选去重成 5 行文献、全部 processed。"""
    requests = demo_store.rows("search_requests")
    assert len(requests) == 3
    assert all(r["done"] for r in requests), "所有请求必须标记完成"
    assert all(r["result_lit_ids"] for r in requests)
    assert all(r.get("last_error") is None for r in requests)

    literature = demo_store.rows("literature")
    assert len(literature) == 5, "6 个候选里有 1 个与已登记文献同 DOI/标题，必须去重"
    assert all(l["processed"] for l in literature)
    assert all(l["path"] for l in literature), "demo 的下载应当全部成功"

    # 被去重的那条候选必须把来源记到既有文献行上（否则无法追溯）
    multi_source = [l for l in literature if len(l["source_request_ids"]) >= 2]
    assert multi_source, "同一文献被多个请求命中时必须累积 source_request_ids"


def test_demo_relations_and_concepts(demo_store: Store) -> None:
    """≥2 条 active 关系、概念已建立、引文全部通过逐字校验、related_concepts 互相连通。"""
    from agentflow import conceptrows as CR
    from agentflow import dedup as D

    relations = demo_store.rows("relations")
    active = [r for r in relations if r["status"] == "active"]
    assert len(active) >= 2, "阿贝尔群↔群、域↔环两条关系应当 active"
    assert all(r["quote_verified"] is True for r in relations), "demo 素材的引文应当全部可校验"
    assert all(r["quote"] and r["dedup_key"] for r in relations)

    # 概念行并表之后住 `statements`（`kind="concept"`）⇒ 老字段名走过渡层投影。
    concepts = {c["concept_id"]: c for c in CR.view(demo_store, shape="legacy")["rows"]}
    assert len(concepts) >= 4
    # "相关"这一格并表之后没有落点：它由关系表现算（`dedup.derive_related_concepts`
    # 是唯一实现，`demo.py` 的判定与 `verify` 都读它）。所以这条判据改成盯派生结果
    # —— 判的仍是"概念之间真的连通了、且形状合法"，而不是某个字段非空。
    derived = {cid: D.derive_related_concepts(cid, relations, include_suspect=True)
               for cid in concepts}
    for cid, rel in derived.items():
        assert rel == sorted(set(rel)), f"{cid} 的派生相关集未升序去重：{rel}"
        assert cid not in rel, f"{cid} 的派生相关集含自身"
    assert any(derived.values()), "related_concepts 必须由关系派生出来"


def test_demo_deep_verify_has_no_issues(demo_store: Store) -> None:
    """端到端数据必须通过 deep 校验（含重开文献复核引文）：0 error / 0 warning。"""
    # 反真空（2026-10-21）：`warnings == []` 不许靠"demo 里根本没有那一类行"通过 ——
    # 4 条概念行（`external_lit` + `active` + `quote_verified=None`）必须**还在**。
    # 它们是"概念行不适用逐字回验"那条口径的素材：判据本体与依据写在
    # `verify.active_stmt_needs_quote_check` 上面（`source_lit_id` 不是"逐字抄自"、
    # `proof_text` 概念行结构上不许带、读侧早已跳过），反真空由
    # `tests/test_verify.py::test_an_unsourced_non_concept_statement_still_warns` 钉住。
    concept_rows = [r for r in demo_store.rows("statements")
                    if str(r.get("kind") or "") == "concept"
                    and str(r.get("origin") or "") == "external_lit"
                    and str(r.get("status") or "") == "active"
                    and r.get("quote_verified") is not True]
    assert len(concept_rows) == 4, [r.get("stmt_id") for r in concept_rows]
    rep = verify_all(demo_store, deep=True, extract_text=extract_text)
    assert rep.ok is True, [i.to_dict() for i in rep.errors]
    assert rep.warnings == [], [i.to_dict() for i in rep.warnings]


def test_demo_duplicate_relation_is_rejected_on_rerun(tmp_path: Path) -> None:
    """重新处理"重印文献"（正文与已有文献逐字相同）时，同一关系必须被判重拒绝写入。"""
    assert run_demo(tmp_path, reset=True, verbose=False) == 0
    st = Store(tmp_path / "demo" / "run")
    before = len(st.rows("relations"))

    # 把重印文献重新放回队列（0004 = 与 0001 正文逐字相同的那篇）
    with st.tx("literature", actor="test") as tx:
        row = tx.find("literature", lit_id=S.format_id(4))
        assert row is not None
        row["processed"] = False
        row["claimed_by"] = None
        row["lease_until"] = None
        tx.upsert("literature", row)

    out = AgentB(
        st,
        extractor=OfflineFixtureExtractor(),
        extract_text=extract_text,
        config={"dup_strong": 0.92, "dup_review": 0.72, "quote_widen_pages": 1},
    ).run_once()

    assert out.relations_duplicate >= 1, "同一概念组 + 同一引文必须判 duplicate"
    assert out.relations_added == 0
    assert len(st.rows("relations")) == before, "被判重的关系不得写入快照"
    dup_details = [d for d in out.details if d.get("skipped") == "duplicate"]
    assert dup_details and dup_details[0]["duplicate_of"], "必须记录 duplicate_of 以便审计"
    assert not [r for r in st.rows("relations") if r["status"] == "rejected"], (
        "§3.3 的判重是「拒绝写入」而不是写一行 rejected，因此不应残留 rejected 行；"
        "证据是 duplicate_of 与 relations_duplicate 计数"
    )


def test_demo_is_idempotent_on_second_run(demo_root: Path) -> None:
    """A/B 都没有待办时重跑：不新增任何行（幂等，§2.4）。"""
    st = Store(demo_root / "demo" / "run")
    from agentflow import conceptrows as CR
    from agentflow.agent_a import AgentA
    from agentflow.providers import FixtureProvider

    before_lit = len(st.rows("literature"))
    before_rel = len(st.rows("relations"))
    before_con = len(CR.view(st, shape="legacy")["rows"])   # 概念行住 `statements`

    agent_a = AgentA(st, providers=[FixtureProvider(demo_root / "demo" / "fixtures" / "candidates.json")], downloader=None)
    out = agent_a.run()
    assert out["skipped_reason"] == "no_pending_request"
    agent_b = AgentB(st, extractor=OfflineFixtureExtractor(), extract_text=extract_text, config={})
    assert agent_b.run_once().skipped_reason == "no_unprocessed_literature"

    assert len(st.rows("literature")) == before_lit
    assert len(st.rows("relations")) == before_rel
    assert len(CR.view(st, shape="legacy")["rows"]) == before_con
