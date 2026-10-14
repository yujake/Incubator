# -*- coding: utf-8 -*-
"""写稿那一刻的读数：这份稿子引了几条台账凭据、库里还有多少可引的。

## 守的是什么（T2 第 24 趟 `t2s` 的真机形态）

那一趟：检索 2 条全 `ok`、17 篇文献全部消化、`relations` 73 条、C 跑了 3 次、
2 条实验 —— 而三份稿件的 9 条断言全引 `exp:0001`：`lit:` 0 条、`rel:` 0 条，
交付面上"文献"与"C 的产物"一条都没进（T2 的四号判据因此红）。
收工门那一档读得出这个 0，但它只在 M 把那一行写进验收表时才进报告；
写稿那一刻没有任何数字。这一格把读数放进 `doc.build_document` 的
`meta.citation_coverage`（`agent_loop` 把 `meta` 一并给模型看）。

## 红/绿成对 + 反真空

* 正控：稿子只引 `exp:` 而库里有已消化文献 + 关系 ⇒ `gaps` 两句都非空、
  `suggest_lit` / `suggest_rel` 点名到号，且读数在 meta 里、不在 data（落库那一行）里；
* 负控：稿子引了 `lit:` 与 `rel:` ⇒ `gaps` 空（做对了不许再念叨）；
* 反真空①：库里一篇已消化文献都没有 ⇒ `gaps` 里不出现"你没引文献"那一句
  （"没东西可引"与"你没引"是两件事）；
* 反真空②：库读不到 ⇒ `readable=False`、`available` 是 -1（三态，不编 0）；
* 负控③：`check_citations` 拦下那笔写入时（悬空引用）⇒ 没有 `citation_coverage`
  （失败语义一个字不变）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry

TS = "2026-10-10T00:00:00+08:00"


def _literature(tx, lit_id: str, title: str, *, processed: bool) -> None:
    tx.upsert("literature", {"lit_id": lit_id, "title": title, "type": "J", "summary": "s",
                             "path": None, "processed": processed, "added_at": TS}, note="seed")


def _relation(tx, rel_id: str, a: str, b: str) -> None:
    tx.upsert("relations", {"relation_id": rel_id, "concept_ids": [a, b],
                            "description": f"{a} 与 {b} 同向", "lit_id": "0000",
                            "page_range": {"start": 1, "end": 2}, "created_at": TS}, note="seed")


def _seed_library(root: Path, *, processed: bool = True) -> Store:
    store = Store(root)
    store.init()
    # `lit:0000` 给一份真有全文的行（`download.status="ok"` + 盘上真有那个文件）——
    # 「登记了几篇」与「真有全文几篇」是两件事（T4 第 7 趟 `t4g` 的读数），
    # 健康夹具必须是真健康的，否则那条"引了文献却不喊"的负控会被这一格叫住（实测）。
    lib = root / "library" / "0000"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "paper.pdf").write_bytes(b"%PDF-1.4\n% fixture\n")
    with store.tx("literature", "relations", "statements", actor="test", note="seed") as tx:
        _literature(tx, "0000", "Edge-girth-regular graphs", processed=processed)
        _literature(tx, "0001", "Constructions for cubic graphs with large girth", processed=processed)
        tx.upsert("literature", {"lit_id": "0000", "title": "Edge-girth-regular graphs",
                                 "type": "J", "summary": "s", "path": "0000/paper.pdf",
                                 "processed": processed,
                                 "download": {"status": "ok", "http_status": 200,
                                              "bytes": 18},
                                 "added_at": TS}, note="seed")
        tx.upsert("statements", {"stmt_id": "0000", "origin": "external_lit", "kind": "concept",
                                 "label": "girth", "statement_full": "围长",
                                 "source_lit_id": "0000",
                                 "quote_reason": "夹具：尚未逐字校验", "created_at": TS}, note="seed")
        tx.upsert("statements", {"stmt_id": "0001", "origin": "external_lit", "kind": "concept",
                                 "label": "cage", "statement_full": "笼",
                                 "source_lit_id": "0001",
                                 "quote_reason": "夹具：尚未逐字校验", "created_at": TS}, note="seed")
        _relation(tx, "0000", "0000", "0001")
    with store.tx("experiments", actor="test", note="seed") as tx:
        tx.upsert("experiments", {"experiment_id": "0000", "claim": "c", "claim_key": "c",
                                  "method": "numeric", "evidence_kind": "cross_check",
                                  "result": "supports", "negation_kind": "not_proved",
                                  "created_at": TS}, note="seed")
    return store


def _build(root: Path, store: Store, claims: list[dict]):
    reg = build_registry(store=store, workspace_root=root).registry
    return reg.call("doc.build_document", role="G", kind="note", title="t", claims=claims)


def _claim(citations: list[str], cid: str = "claim-1", text: str = "") -> dict:
    """一条合规的 claim（用唯一的构造入口 `compose_claim`，不手拼必填字段）。"""
    from agentflow.tools import doc_tools as DT

    return DT.compose_claim(text or "围长恰为 k 的图里每条边至少落在两个 k-圈里。",
                            citations=list(citations), evidence_kind="cross_check",
                            section="主结果", claim_id=cid)


def test_positive_the_reading_names_what_is_missing_and_what_is_available(tmp_path: Path) -> None:
    """正控：只引 `exp:` ⇒ 两句 `gaps` 都点名，库里可引的样例也列出来。"""
    store = _seed_library(tmp_path)

    res = _build(tmp_path, store, [_claim(["exp:0000"])])

    assert res.ok is True, res
    cov = res.meta.get("citation_coverage")
    assert isinstance(cov, dict) and cov.get("readable") is True, res.meta
    assert cov["counts"]["exp"] == 1 and cov["counts"]["lit"] == 0 and cov["counts"]["rel"] == 0
    assert cov["available"]["literature_processed"] == 2, cov["available"]
    assert cov["available"]["relations"] == 1, cov["available"]
    assert len(cov["gaps"]) == 2, cov["gaps"]
    assert "lit:" in cov["gaps"][0] and "2 篇已消化" in cov["gaps"][0], cov["gaps"][0]
    assert "rel:" in cov["gaps"][1], cov["gaps"][1]
    assert [x["lit_id"] for x in cov["suggest_lit"]] == ["0000", "0001"], cov["suggest_lit"]
    assert cov["suggest_lit"][0]["title"].startswith("Edge-girth-regular"), cov["suggest_lit"]
    assert [x["relation_id"] for x in cov["suggest_rel"]] == ["0000"], cov["suggest_rel"]
    # 读数在 meta 里；`data`（落库的那一行）一个键都不许多 —— 它要算内容哈希。
    assert "citation_coverage" not in res.data, sorted(res.data)
    stored = list(store.rows("documents"))[0]
    assert "citation_coverage" not in dict(stored), sorted(stored)


def test_negative_no_nagging_when_the_manuscript_cites_the_library(tmp_path: Path) -> None:
    """负控：稿子引了 `lit:` 与 `rel:` ⇒ `gaps` 空（做对了不许再念叨）。"""
    store = _seed_library(tmp_path)

    res = _build(tmp_path, store, [_claim(["lit:0000", "rel:0000"])])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["counts"]["lit"] == 1 and cov["counts"]["rel"] == 1, cov["counts"]
    assert cov["gaps"] == [], cov["gaps"]


def test_anti_vacuum_empty_library_does_not_blame_the_writer(tmp_path: Path) -> None:
    """反真空①：库里没有已消化的文献 ⇒ 不出现"你没引文献"那一句。"""
    store = _seed_library(tmp_path, processed=False)

    res = _build(tmp_path, store, [_claim(["exp:0000"])])

    assert res.ok is True, res  # 悬空 `exp:` 由 `check_citations` 拦，这一次不引 exp
    cov = res.meta["citation_coverage"]
    assert cov["available"]["literature_processed"] == 0, cov["available"]
    assert all("已消化的文献" not in g for g in cov["gaps"]), cov["gaps"]
    assert cov["suggest_lit"] == [], cov["suggest_lit"]


def test_anti_vacuum_unreadable_library_is_minus_one_not_zero() -> None:
    """反真空②：库读不到 ⇒ -1 + `readable=False`（"没查成" ≠ "库里没有"）。"""
    from agentflow.tools import doc_tools as DT

    def _blind(table: str):
        raise RuntimeError("表读不到")

    cov = DT.citation_coverage(_blind, [_claim(["exp:0000"])])
    assert cov["readable"] is False, cov
    assert cov["available"]["literature_processed"] == -1, cov["available"]
    assert cov["available"]["relations"] == -1, cov["available"]
    # 引了几条仍然给得出（那一半只读 claims，不看库）
    assert cov["counts"]["exp"] == 1, cov["counts"]
    assert "没查成" in cov["note"], cov["note"]


def test_negative_dangling_citation_still_fails_without_the_reading(tmp_path: Path) -> None:
    """负控③：悬空引用被拦下 ⇒ 那笔写入失败，且不挂 `citation_coverage`。"""
    store = _seed_library(tmp_path)

    res = _build(tmp_path, store, [_claim(["lit:9999"])])

    assert res.ok is False, res
    assert res.meta.get("kind") == "dangling_citation", res.meta
    assert "citation_coverage" not in res.meta, res.meta
    assert len(list(store.rows("documents"))) == 0


def test_revise_returns_the_same_reading(tmp_path: Path) -> None:
    """`G.revise` 那条路也要给同一份读数（否则"改写"是绕开它的后门）。

    与 `check_citations` / `check_proofs` 在同一条路上各被补过一次的那两处同形。
    """
    from agentflow.agent_g import AgentG

    store = _seed_library(tmp_path)
    g = AgentG(store, config={"docs_subdir": "documents"})
    doc_id = g.build_document("note", "初稿", claims=[_claim(["exp:0000"])])["doc_id"]

    out = g.revise(doc_id, new_claims=[_claim(["exp:0000"])])

    cov = out["citation_coverage"]
    assert cov["readable"] is True, cov
    assert cov["counts"]["lit"] == 0 and cov["counts"]["rel"] == 0, cov["counts"]
    assert len(cov["gaps"]) == 2, cov["gaps"]
    assert [x["lit_id"] for x in cov["suggest_lit"]] == ["0000", "0001"], cov["suggest_lit"]


def test_negative_the_g_role_path_must_carry_the_reading_too(tmp_path: Path) -> None:
    """负控（T2 第 25 趟抓出来的真缺口）：`G.build_document` 那条路必须带着读数回。

    为什么单列一条：工具层把读数放在 `meta` 里，而 `AgentG._call` 只交出 `res.data`
    —— meta 丢在门里 ⇒ M 手里那条路（`conductor.summon` → `G.build_document`）
    一个字都看不到。真机读数：T2 第 25 趟 `t2t` 的 `sessions/t2t.jsonl` 全文件搜
    `citation_coverage` 0 命中。这一条钉住"两个入口都要给"。
    """
    from agentflow.agent_g import AgentG

    store = _seed_library(tmp_path)
    g = AgentG(store, config={"docs_subdir": "documents"})

    out = g.build_document("note", "初稿", claims=[_claim(["exp:0000"])])

    assert out["doc_id"] == S.format_id(0), out          # 稿件那一行的字段一个不少
    assert out["claims"], out                    # 也不许多少
    cov = out["citation_coverage"]               # 读数就在同一个返回值里
    assert cov["readable"] is True, cov
    assert cov["counts"]["lit"] == 0 and cov["counts"]["rel"] == 0, cov["counts"]
    assert len(cov["gaps"]) == 2, cov["gaps"]
    # 落库的那一行不许带上读数（它要算内容哈希、要被 schema 校验）
    stored = dict(list(store.rows("documents"))[0])
    assert "citation_coverage" not in stored, sorted(stored)


# ---- 「引文对不对口」那一半（T4 第 3 趟 `t4c` 的整改）----
#
# 真机读数：`t4c` 的清单里 2 条断言把数学教育论文当出处，收工门的 `citation_fit`
# 点名了，M 调了 5 次 `closing` 看到 blocker 之后仍按 `met=true` 收工。写稿那一刻
# 那条读数原先只说"引了几条" ⇒ 这一半补上"对不对口"（判据与 `citation_fit` 共用一份实现）。


def _off_topic_library(root: Path) -> Store:
    """库里混进一篇数学教育论文（`t4c` 的真实形态）。"""
    store = _seed_library(root)
    with store.tx("literature", actor="test", note="seed") as tx:
        tx.upsert("literature", {
            "lit_id": "0002",
            "title": "Promoting Problem Solving across Geometry and Algebra by Using Technology",
            "type": "J", "summary": "classroom study on problem solving with technology",
            "path": None, "processed": True, "added_at": TS}, note="seed")
    return store


def test_positive_an_off_topic_citation_is_reported_as_misfit(tmp_path: Path) -> None:
    """正控：断言的实词与被引文献没有交集 ⇒ 进 `misfit`，并且 `gaps` 里有一句。"""
    store = _off_topic_library(tmp_path)

    res = _build(tmp_path, store, [_claim(
        ["lit:0002"],
        text="Termination of flips for klt singularities in dimension four remains open.")])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["fit"]["mismatch"] == 1, cov["fit"]
    assert [m["claim_id"] for m in cov["misfit"]] == ["claim-1"], cov["misfit"]
    assert "跑题" in cov["misfit"][0]["why"][0], cov["misfit"][0]
    assert any("引文与原文对不上" in g for g in cov["gaps"]), cov["gaps"]


def test_negative_an_on_topic_citation_is_not_flagged(tmp_path: Path) -> None:
    """负控：引对了不许误报（不然这条读数会退化成"每次都喊"）。"""
    store = _off_topic_library(tmp_path)

    res = _build(tmp_path, store, [_claim(
        ["lit:0000"], text="Edge-girth-regular graphs are the setting of this note.")])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["fit"]["fit"] == 1 and cov["misfit"] == [], cov["fit"]


def test_anti_vacuum_no_features_on_one_side_is_unjudged_not_mismatch(tmp_path: Path) -> None:
    """反真空：一侧抽不出可判特征 ⇒ `unjudged`（"没查成"绝不读成"对不上"）。"""
    store = _off_topic_library(tmp_path)

    res = _build(tmp_path, store, [_claim(["lit:0002"], text="Open.")])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["fit"]["unjudged"] == 1 and cov["misfit"] == [], cov["fit"]
    assert cov["gaps"] == [] or all("引文与原文对不上" not in g for g in cov["gaps"]), cov["gaps"]


# ---- 「立了几条研究问题 vs 稿件几条带引文断言」那一格（T4 第 4/5 趟的整改）----
#
# 两趟连着的 blocker 是同一个形状：`t4d` 的 `retrieval_ok_rows` 5 < 6、
# `t4e` 的 `document_claim_rows` 12 < 16 —— 两档的隐式门槛都是"研究问题条数"，
# 而 M 在写稿那一刻多半没回头数自己立了几条问题。


def _with_questions(root: Path, n: int) -> Store:
    store = _seed_library(root)
    with store.tx("research_questions", actor="test", note="seed") as tx:
        for i in range(n):
            tx.upsert("research_questions", {"question_id": f"{i:04d}",
                                             "question": f"problem {i}",
                                             "status": "open",
                                             "created_at": TS}, note="seed")
    return store


def test_positive_the_gap_between_questions_and_claims_is_named(tmp_path: Path) -> None:
    """正控：立的比写的多 ⇒ 报出差几条，并给出两条出路。"""
    store = _with_questions(tmp_path, 4)

    res = _build(tmp_path, store, [_claim(["lit:0000"])])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["questions_vs_claims"]["research_questions"] == 4, cov["questions_vs_claims"]
    assert cov["questions_vs_claims"]["claims_with_citations"] == 1, cov["questions_vs_claims"]
    assert cov["questions_vs_claims"]["short"] == 3, cov["questions_vs_claims"]
    assert any("4 条研究问题" in g for g in cov["gaps"]), cov["gaps"]


def test_negative_no_questions_no_nagging(tmp_path: Path) -> None:
    """负控（反真空）：一条研究问题都没立 ⇒ 不喊（"没立题"与"写得少"是两件事）。"""
    store = _seed_library(tmp_path)

    res = _build(tmp_path, store, [_claim(["lit:0000"])])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["questions_vs_claims"]["research_questions"] == 0, cov["questions_vs_claims"]
    assert cov["questions_vs_claims"]["short"] == 0, cov["questions_vs_claims"]
    assert all("条研究问题" not in g for g in cov["gaps"]), cov["gaps"]


# ---- 「真有全文几篇」那一格（T4 第 7 趟 `t4g` 的整改）----
#
# 真机读数：`t4g` 的 `literature` 15 篇里 5 条 `download.status=skipped`（后端只给元数据）、
# 4 条 `content_mismatch`（HTML 壳）、2 条 `ok`、4 条 `failed`（404/403/429）⇒ 真能逐字回验的
# 只有 2 篇，而交付物退化成了"证据不足的报告"。「登记了几篇」与「真有全文几篇」是两件事，
# 写稿那一刻要把后者摆出来（元数据级出处可以引，但正文要写明它只有元数据支撑）。


def _no_fulltext_library(root: Path) -> Store:
    """把 `lit:0000` 的全文拿掉（状态不是 ok），只留元数据。"""
    store = _seed_library(root)
    with store.tx("literature", actor="test", note="seed") as tx:
        tx.upsert("literature", {"lit_id": "0000", "title": "Edge-girth-regular graphs",
                                 "type": "J", "summary": "s", "path": None,
                                 "processed": True,
                                 "download": {"status": "skipped", "http_status": None},
                                 "added_at": TS}, note="seed")
    return store


def test_positive_no_full_text_is_named_as_a_gap(tmp_path: Path) -> None:
    """正控：引了 `lit:` 而库里一篇可用全文都没有 ⇒ 那一句要点出来。"""
    store = _no_fulltext_library(tmp_path)

    res = _build(tmp_path, store, [_claim(["lit:0000"])])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["available"]["literature_with_fulltext"] == 0, cov["available"]
    assert any("一篇有可用全文的都没有" in g for g in cov["gaps"]), cov["gaps"]


def test_negative_a_real_full_text_is_counted_and_not_nagged(tmp_path: Path) -> None:
    """负控：盘上有全文且状态 ok ⇒ 计进 `literature_with_fulltext`，且不喊那一句。"""
    store = _seed_library(tmp_path)

    res = _build(tmp_path, store, [_claim(["lit:0000"])])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["available"]["literature_with_fulltext"] == 1, cov["available"]
    assert all("一篇有可用全文的都没有" not in g for g in cov["gaps"]), cov["gaps"]


def test_anti_vacuum_status_ok_but_the_file_is_gone_does_not_count(tmp_path: Path) -> None:
    """反真空：状态说 `ok` 而盘上文件没了 ⇒ 不算有全文（"没查成"不许读成"有"）。"""
    store = _seed_library(tmp_path)
    (tmp_path / "library" / "0000" / "paper.pdf").unlink()

    res = _build(tmp_path, store, [_claim(["lit:0000"])])

    assert res.ok is True, res
    cov = res.meta["citation_coverage"]
    assert cov["available"]["literature_with_fulltext"] == 0, cov["available"]
    assert any("一篇有可用全文的都没有" in g for g in cov["gaps"]), cov["gaps"]

