# -*- coding: utf-8 -*-
"""彩排 C9：概念图链 —— C 的读数 → D 用缺口立题／B 做结构重复裁决。

## 这一条链的两条出口

```text
C.hottest / C.paths / C.gaps / C.proof_chain / C.contradictions
  → 每条读数里的概念号 / 关系号都能在 concepts / relations / statements 里查到
  → 读数登记进 analysis_reports（只读角色的唯一写入口）

出口一（D）：C.gaps 的 candidate_gaps → D.ingest 立出 research_questions 一行
  → D.consider 走状态机（证据不足 ⇒ 提交缺口请求；证据够 ⇒ 推进 researching）

出口二（B）：C.structural_duplicates 的候选 → B.decide_structural_duplicate
  → B.resolve_structural_duplicate 真合并：concepts 留墓碑（merged_into / merge_reason），
    relations 的被合并方改写成 survivor
```

## 终态断言（盘上/台账上可查）

| 判据 | 终态 |
|---|---|
| `test_c9_a_every_c_reading_is_anchored_in_the_ledger` | 五条读数的每个概念号/关系号都在 concepts/relations/statements 里；五份报告在 `analysis_reports` 里各一行 |
| `test_c9_b_the_gap_becomes_a_question_and_enters_the_state_machine` | `research_questions` 新增一行，`origin` 带 `C:gaps:<报告号>:`、`related_concept_ids` 是缺口那两个；`consider` 之后它不再停在"什么都没发生" |
| `test_c9_c_b_merges_the_structural_duplicate` | 被合并命题 `status=superseded` + 墓碑点名 survivor；relations 里不再出现它；`applied=True` |
| `test_c9_d_b_rejects_structural_equivalence_that_is_not_synonymy` | 名字不同的候选 ⇒ `verdict=reject`、`applied=False`、概念表一个字节不动 |

## 反真空

把 C 的读数打桩成空：`AgentC.gaps` 恒回一份空报告 ⇒ `AgentD.ingest` 必须以空题
收场（返回 `[]`，`last_ingest["skipped"]` 点名"没有可识别的结构化发现"，
`research_questions` 一行都不多）—— `test_..._e`。若 D 在"没有候选"时仍然凭空
立题，这一条当场红。

`test_..._d` 是 B 那一侧的负控：邻域相同但名字不同的一对（0008/0009）必须被拒，
且概念表一个字节不动 —— 结构等价 ≠ 同义，合并决定权在 B 且必须给出可反驳的理由。

## 零模型

全部 tmp 工作区；C 的 LLM 钩子不接线（`llm=None`）；不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
from typing import Any, Mapping

import pytest

from agentflow import schema as S
from agentflow import conceptrows as CR
from agentflow.agent_c import AgentC
from agentflow.agent_c._support import AnalysisReport
from agentflow.agent_d import AgentD
from agentflow.store import Store

from conftest import (add_concept, add_literature, add_relation, add_request,
                      sync_counters)

TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path, name: str = "ws") -> Store:
    """一张小图：一对结构重复（0000/0001 邻域相同、名字相同）＋一条对立关系。

    刻意不使用 0000/0001 之间任何直接关系：结构重复的第 2 条判据要求"两者之间
    没有直接关系"（有就直接拒）。
    """
    st = Store(tmp_path / name)
    st.init()
    add_concept(st, "0000", "群", definition="一个带有二元运算的集合，满足结合律、单位元与逆元。",
                sync=False)
    add_concept(st, "0001", "群", definition="带有二元运算的集合。", sync=False)
    add_concept(st, "0002", "子群", definition="群的非空子集，对运算封闭。", sync=False)
    add_concept(st, "0003", "正规子群", definition="对共轭作用封闭的子群。", sync=False)
    add_concept(st, "0006", "交换环", definition="乘法交换的环。", sync=False)
    add_concept(st, "0007", "整环", definition="无零因子的交换环。", sync=False)
    # 另一对「邻域相同但名字不同」：B 的负控用它（结构等价 ≠ 同义）。
    add_concept(st, "0008", "甲概念", definition="夹具概念甲。", sync=False)
    add_concept(st, "0009", "乙概念", definition="夹具概念乙。", sync=False)
    add_literature(st, "0000", title="夹具文献甲", processed=True, sync=False)
    add_literature(st, "0001", title="夹具文献乙", processed=True, sync=False)
    for rid, cids, lit in (("0000", ["0000", "0002"], "0000"),
                           ("0001", ["0000", "0003"], "0000"),
                           ("0002", ["0001", "0002"], "0001"),
                           ("0003", ["0001", "0003"], "0001"),
                           ("0006", ["0002", "0008"], "0000"),
                           ("0007", ["0003", "0008"], "0001"),
                           ("0008", ["0002", "0009"], "0000"),
                           ("0009", ["0003", "0009"], "0001")):
        add_relation(st, rid, cids, lit, description="子群是群的结构，正规子群是子群。",
                     quote="子群是群的结构。", quote_verified=True, sync=False)
    # 明确对立的一对：同一概念组、一方肯定一方否定（`interactions` 的 strong 档）。
    add_relation(st, "0004", ["0006", "0007"], "0000",
                 description="交换环是整环", quote="交换环是整环", quote_verified=True,
                 sync=False)
    add_relation(st, "0005", ["0006", "0007"], "0001",
                 description="交换环不是整环", quote="交换环不是整环", quote_verified=True,
                 sync=False)
    sync_counters(st)
    return st


def _c(st: Store) -> AgentC:
    return AgentC(st, config={"hot_top_n": 3, "gap_group_min_count": 2})


def _d(st: Store) -> AgentD:
    # `c=None`：不让 D 在 ingest 时顺带调用 C 的服务面 —— 这一条链要钉的是
    # "C 已经交来的报告如何变成问题"，不是 C 的实时查询。
    return AgentD(st, c=None)


def _stmt(st: Store, sid: str, *, proof: str = "", evidence: str = "cross_check") -> None:
    row = S.Statement(stmt_id=sid, origin="own_result", kind="theorem",
                      label=f"定理 {sid}", statement_text="短版",
                      statement_full="若假设 A 成立，则结论 B 成立",
                      proof_text=proof, source_lit_id=None, quote_verified=None,
                      quote_reason="夹具", evidence_kind=evidence, status="active",
                      created_at=TS)
    row.validate()
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())


def _dep(st: Store, did: str, used_by: str, *, lit: str) -> None:
    row = S.Dependency(dep_id=did, used_by=used_by, kind="prior_art", label="前提",
                       status="closed", source_lit_id=lit, path_group=1,
                       created_at=TS)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict())


# ====================================================================== a：锚定
def test_c9_a_every_c_reading_is_anchored_in_the_ledger(
        tmp_path: pathlib.Path) -> None:
    """C 的五条读数都落在台账上：概念号/关系号查得到，报告也真的登记了。"""
    st = _env(tmp_path, "c9a")
    _stmt(st, "0100")
    _dep(st, "0100", "stmt:0100", lit="0000")
    c = _c(st)
    reports = {
        "hottest": c.hottest(top_n=3, request="C9 热点"),
        "paths": c.paths("0000", "0002", request="C9 路径"),
        "gaps": c.gaps(limit=5, request="C9 缺口"),
        "proof_chain": c.proof_chain("0100"),
        "contradictions": c.contradictions(),
    }
    concept_rows = CR.view(st, shape="legacy")["rows"]
    concept_ids = {str(r.get("concept_id")) for r in concept_rows}
    relation_ids = {str(r.get("relation_id")) for r in st.rows("relations")}
    stmt_ids = {str(r.get("stmt_id")) for r in st.rows("statements")}
    problems: list[str] = []
    # 三份"分析报告"（`hottest` / `paths` / `gaps`）登记进 analysis_reports ——
    # 只读角色的唯一写入口。`proof_chain` / `contradictions` 是角色级读数，
    # 不在 `schema.REPORT_KINDS` 里（它们不冒充可登记的报告）。
    for name in ("hottest", "paths", "gaps"):
        rep = reports[name]
        if not rep.ok:
            problems.append(f"C.{name} 没查成：{rep.error!r}")
            continue
        # `AgentC` 的报告一生成就已经登记过（`report_id` 非空）—— 这正是
        # 「只读角色的产出能进台账」那条通道；这里不再重复 persist（会多出一行）。
        if not rep.report_id:
            problems.append(f"C.{name} 的报告没有登记号（分析没进台账）：{rep!r}")
    kinds = sorted(str(r.get("kind")) for r in st.rows("analysis_reports"))
    if kinds != ["gaps", "hottest", "paths"]:
        problems.append(f"analysis_reports 的 kind 集合不对：{kinds}")
    for name in ("proof_chain",):
        if not reports[name].ok:
            problems.append(f"C.{name} 没查成：{reports[name].error!r}")
    if reports["contradictions"].get("checked") is not True:
        problems.append(f"C.contradictions 没查成：{reports['contradictions'].get('reason')!r}")

    hot = reports["hottest"].payload
    for entry in hot.get("entries") or ():
        if str(entry.get("concept_id")) not in concept_ids:
            problems.append(f"hottest 凭空造了概念号：{entry!r}")
    paths = reports["paths"].payload
    for item in paths.get("paths") or ():
        for cid in item.get("concept_path") or ():
            if str(cid) not in concept_ids:
                problems.append(f"paths 的概念号不在 concepts 里：{cid!r}")
        for rid in item.get("relation_chain") or ():
            if str(rid) not in relation_ids:
                problems.append(f"paths 的关系号不在 relations 里：{rid!r}")
    gaps = reports["gaps"].payload
    if gaps.get("verdict") not in ("有", "无"):
        problems.append(f"gaps 的 verdict 不在二值里：{gaps.get('verdict')!r}")
    for cand in gaps.get("candidate_gaps") or ():
        for cid in cand.get("concept_ids") or ():
            if str(cid) not in concept_ids:
                problems.append(f"gaps 的候选概念号不在 concepts 里：{cid!r}")
        for rid in cand.get("related_relation_ids") or ():
            if str(rid) not in relation_ids:
                problems.append(f"gaps 的关系号不在 relations 里：{rid!r}")
    chain = reports["proof_chain"].payload
    if chain.get("target") not in (None, "", "0100"):
        problems.append(f"proof_chain 的目标不对：{chain.get('target')!r}")
    for group in chain.get("groups") or ():
        for hop in group.get("hops") or ():
            node = str(hop.get("node") or "")
            if node.startswith("lit:") and node[4:] not in {"0000"}:
                problems.append(f"proof_chain 的文献根不在 literature 里：{node!r}")
    con = reports["contradictions"]
    for row in con.get("contradictions") or ():
        for rid in row.get("relation_ids") or ():
            if str(rid) not in relation_ids:
                problems.append(f"contradictions 的关系号不在 relations 里：{rid!r}")
    if "0100" not in stmt_ids:
        problems.append("proof_chain 的目标 0100 不在 statements 里")
    assert problems == [], problems


# ====================================================================== b：D 立题
def test_c9_b_the_gap_becomes_a_question_and_enters_the_state_machine(
        tmp_path: pathlib.Path) -> None:
    """C 的缺口 → D 立出一行问题 → `consider` 真的推进/交缺口。"""
    st = _env(tmp_path, "c9b")
    gaps = _c(st).gaps(limit=5, request="C9 缺口立题")
    rid = str(gaps.report_id)
    created = _d(st).ingest(gaps)
    problems: list[str] = []
    if not created:
        problems.append(f"D 没有从 C 的缺口立出题：last_ingest={_d(st).last_ingest!r}")
    rows = [dict(r) for r in st.rows("research_questions")]
    if len(rows) != len(created):
        problems.append(f"research_questions 行数与 ingest 返回不一致："
                        f"{len(rows)} vs {len(created)}")
    if not rows:
        problems.append("research_questions 一行都没有")
    else:
        q = rows[0]
        origin = str(q.get("origin") or "")
        if not origin.startswith(f"C:gaps:{rid}:"):
            problems.append(f"问题的 origin 没有指回 C 的报告：{origin!r}")
        related = [str(x) for x in (q.get("related_concept_ids") or ())]
        if len(related) < 2:
            problems.append(f"问题没有带上缺口的那两个概念：{q!r}")
        if not set(related) <= {str(r.get("concept_id"))
                                for r in CR.view(st, shape="legacy")["rows"]}:
            problems.append(f"问题的概念号不在 concepts 里：{related!r}")
        if str(q.get("status")) != "open":
            problems.append(f"新立的问题该是 open，实际 {q.get('status')!r}")

    # `consider` 是状态机的 [3] 评估 → 分支：要么推进 researching，要么交缺口。
    studied = _d(st).consider(str(rows[0]["question_id"])) if rows else {}
    if studied:
        if str(studied.get("question_id")) != str(rows[0]["question_id"]):
            problems.append(f"consider 回执的号不对：{studied!r}")
        if not (studied.get("promoted") or studied.get("submitted")):
            problems.append(f"consider 之后什么都没发生（既没推进也没交缺口）：{studied!r}")
        after = next(dict(r) for r in st.rows("research_questions")
                     if str(r.get("question_id")) == str(rows[0]["question_id"]))
        if str(after.get("status")) == "open" and not studied.get("submitted"):
            problems.append(f"问题还停在 open 且没有缺口请求：{after!r}")
    assert problems == [], problems


# ====================================================================== c：B 合并
def test_c9_c_b_merges_the_structural_duplicate(tmp_path: pathlib.Path) -> None:
    """C 提候选 → B 判 merge → B 真合并：墓碑 + 关系改写都落在台账上。"""
    st = _env(tmp_path, "c9c")
    cands = _c(st).structural_duplicates()
    problems: list[str] = []
    if cands.get("checked") is not True:
        problems.append(f"C 的结构重复没查成：{cands.get('reason')!r}")
    merge_cands = [c for c in (cands.get("candidates") or ())
                   if c.get("proposal") == "merge"
                   and sorted(c.get("concept_ids") or ()) == ["0000", "0001"]]
    if not merge_cands:
        problems.append(f"夹具没造出 proposal=merge 的候选：{cands!r}")
    if merge_cands:
        candidate = merge_cands[0]
        from agentflow.agent_b import AgentB

        b = AgentB(st, extractor=None, extract_text=None)
        decision = b.decide_structural_duplicate(candidate)
        if str(decision.get("verdict")) != "merge":
            problems.append(f"B 没判 merge：{decision!r}")
        resolved = b.resolve_structural_duplicate(candidate)
        if resolved.get("applied") is not True:
            problems.append(f"B 的合并没执行：{resolved!r}")
        merged_id = str(decision.get("merged_id") or "")
        survivor_id = str(decision.get("survivor_id") or "")
        # 新标准那一行（statements 里的概念行）是墓碑：status=superseded +
        # quote_reason 点名并入的是哪一条（新标准没有 merged_into 这一列）。
        stmt_row = next((dict(r) for r in st.rows("statements")
                         if str(r.get("stmt_id")) == merged_id), {})
        if str(stmt_row.get("status")) != "superseded":
            problems.append(f"被合并命题没有 superseded 墓碑：{stmt_row!r}")
        if survivor_id not in str(stmt_row.get("quote_reason") or ""):
            problems.append(f"墓碑没有点名并入哪一条（{survivor_id}）：{stmt_row!r}")
        legacy = {str(r.get("concept_id")): dict(r)
                  for r in CR.view(st, shape="legacy")["rows"]}
        if not str((legacy.get(merged_id) or {}).get("merged_into") or ""):
            problems.append(f"老表视图没有墓碑读数：{legacy.get(merged_id)!r}")
        for rel in st.rows("relations"):
            if merged_id in {str(x) for x in (rel.get("concept_ids") or ())}:
                problems.append(f"关系 {rel.get('relation_id')} 仍指着被合并方：{rel!r}")
        # 被合并方的边要么被改写（换成 survivor），要么被判重（同一概念组里重复）——
        # 两者都是"这一笔真动了关系表"的读数。
        if not (resolved.get("rewritten_relation_ids")
                or resolved.get("rejected_relation_ids")):
            problems.append(f"合并没有动任何关系：{resolved!r}")
    assert problems == [], problems


# ====================================================================== d：B 拒
def test_c9_d_b_rejects_structural_equivalence_that_is_not_synonymy(
        tmp_path: pathlib.Path) -> None:
    """反控：邻域相同但名字不同（0008/0009）⇒ 只有一路证据，B 必须 reject、一行不写。"""
    st = _env(tmp_path, "c9d")
    cands = [c for c in (_c(st).structural_duplicates().get("candidates") or ())
             if sorted(c.get("concept_ids") or ()) == ["0008", "0009"]]
    problems: list[str] = []
    if not cands:
        problems.append("夹具没造出 0008/0009 的结构重复候选")
    else:
        from agentflow.agent_b import AgentB

        b = AgentB(st, extractor=None, extract_text=None)
        before = {str(r.get("concept_id")): dict(r)
                  for r in CR.view(st, shape="legacy")["rows"]}
        decision = b.decide_structural_duplicate(cands[0])
        if str(decision.get("verdict")) != "reject":
            problems.append(f"名字不同却判了 {decision.get('verdict')!r}")
        resolved = b.resolve_structural_duplicate(cands[0])
        if resolved.get("applied") is not False:
            problems.append(f"reject 却执行了合并：{resolved!r}")
        after = {str(r.get("concept_id")): dict(r)
                 for r in CR.view(st, shape="legacy")["rows"]}
        if before != after:
            problems.append("reject 那一档动了概念表（连墓碑都不许落）")
    assert problems == [], problems



# ====================================================================== e：反真空空读
def test_c9_e_an_empty_c_reading_yields_no_questions(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空①：把 C 的读数打桩成空 ⇒ D 必须以受控拒/空题收场。

    桩只改 C 的那一格（返回一份空报告），不改 D；若 D 在"没有候选"时仍然凭空
    立题，这一条当场红。
    """

    def _empty(self: AgentC, *a: Any, **kw: Any) -> AnalysisReport:
        return AnalysisReport(kind="gaps", request="打桩：空读数", summary="空",
                              payload={"verdict": "无", "candidate_gaps": []},
                              markdown="打桩：空读数\n")

    monkeypatch.setattr(AgentC, "gaps", _empty)
    st = _env(tmp_path, "c9e")
    empty = AgentC(st).gaps(limit=5)
    empty.persist(st)
    d = _d(st)
    created = d.ingest(empty)
    problems: list[str] = []
    if created:
        problems.append(f"空读数却立出了题：{created!r}")
    if st.rows("research_questions"):
        problems.append(f"空读数却写了 research_questions：{st.rows('research_questions')!r}")
    skipped = " ".join(str(x) for x in (d.last_ingest.get("skipped") or ()))
    if "没有可识别的结构化发现" not in skipped:
        problems.append(f"空读数的 skipped 没点名原因：{d.last_ingest!r}")
    assert problems == [], problems

