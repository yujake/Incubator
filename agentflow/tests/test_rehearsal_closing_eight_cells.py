# -*- coding: utf-8 -*-
"""彩排判据（REH8）· 收工闸八格全过：逐格证据 + 机器口径 + 八条反真空。

## 这一份回答什么

业主裁定（逐字）：「除非彩排能做出来收工闸全过，不然不轻易动」。
所以这一份不修门、不改判据语义，只回答一个问题：

> 在一个真账本 + 真表的工作区里，`closing.DEFAULT_CHECKS` 那八格能不能逐格 `pass`？

能，就把它钉成判据（本文件的正控）；不能，就把卡在哪一格哪一条写成读数。
八格的本体是 `closing.DEFAULT_CHECKS`（`closing.py:69`），这一份不复制那张表 ——
`test_the_workspace_covers_every_default_cell` 直接拿它来比。

## 工作区里什么是真的、什么是假模型

| 这一趟用的东西 | 真机 | 这一份彩排 |
|---|---|---|
| 账本 | `data/*.json` + `data/events.jsonl` | 同一套 `store.tx` 写口（每笔事务都追加事件） |
| 产物台账 | `ARTIFACTS.jsonl` | `artifacts.record` 真写口（先核盘上文件再登记 sha256） |
| 任务台账 | `data/tasks.json` | `schema.Task` 真行（M 顶趟 + C 一次关系分析） |
| 表 | `statements` / `conjectures` / `literature` / `lit_candidates` / `experiments` / `documents` / `relations` / `research_questions` / `attack_plans` / `search_requests` | 逐张真表；能走产品写口的都走产品写口（`litstage.clear_delegation` 清表 + 归档、`verifications.record_verification` 落 v-review、`vsigns.issue` 发签、`papermapping.write_package` 落论文对应表三份、`papercompile.compile_paper` 编 PDF） |
| 收工门 | `conductor.closing` → `check_closing(project_dir=".", report_path="out/review/REPORT.md")` | 同一个函数、同一组缺省 `checks=DEFAULT_CHECKS`、同样按"相对工作区"解析 |
| 机器口径 | `retire_integrity` / `programs` 读数 | 由这一趟喂进 `check_closing(retire=…, programs=…)`（`machine_caliber` 的两个喂参） |
| 模型 | 真 `LlmSeam` | 八格本身零模型调用（`closing` 不调模型）—— 所谓"假模型"是这一份夹具替模型做的那几笔决定（登记命题 / 判收 / 跑实验 / 写稿），决定落成的都是真行 |

同一条链的「CLI 入口 + 真 `LlmSeam` + `conductor.closing`」形态不在这里重复：
那是 `tests/test_rehearsal_c12_closing.py`（它复用的正控工作区正是本文件参照的那一种）。
本文件补的是它没有的那一半：逐格证据清单 + 逐格反真空（八条）。

## 为什么这一份不是「同路径彩排」

`rehearsal_contract.CLOSING_CRITERIA_FILES` 里登记了它，与 `WF_CRITERIA_FILES` /
`FLOW_CRITERIA_FILES` 同形：它是判据，不是彩排。两条硬理由：

1. 八条反真空必须逐格把产品里的一处真弄坏（删报告、塞一条 disputed 依赖、清空五张表…）
   —— 这与「打桩只许五类」的静态判据天然冲突；
2. 它不做模型调用，所以 `triplet_probe` 的三格没有对象（那三格量的是"这一趟真的走了一遍
   模型循环"，本文件量的不是那件事）。

真机同路径的证据仍由 C12 那份彩排提供；本文件只回答"那八格在真数据上能不能同时是 pass"。

## 反真空为什么同时断言 `machine_pass` 与 `can_close`

2026-11-19（ROOTGATE-①，业主「要修根因」）之后，"能不能交"只有一份权威结论
（`closing.closing_verdict`）：`can_close` 也读那八格（改前它不读，于是真机
`lp-ball-11` 八格 6/8 仍 `exit 0`）。所以这一份的每条反真空都同时钉三格：

- 弄坏一格 ⇒ 那一格 `fail`、`machine_pass=False`；
- 同一份结论的 `can_close=False`（它不再是"只看 retire/programs"的第二条轴）；
- 退出码 1（`tri_state_exit_code` 也由那一份结论派生）。

另有一条单独的负控证明 `can_close` 的机器那半边也有牙（`retire` 不干净 ⇒ false），
而"没接线"那一档是 `unknown`（退出码 2），不许退回 `m_says_done ∧ machine_pass`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import paperfixture as FX
from conftest import TS, add_concept, add_literature, add_relation, sync_counters
from _credential_fixture import issue_credential

from agentflow import artifacts as AR
from agentflow import closing as CL
from agentflow import litstage as LS
from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow import sessions as SESS
from agentflow import userio as U
from agentflow.store import Store

#: 本趟的会话号。`user_pending` 与"每条账都归得了主"这两件事都要它。
SID = "reh8-e8"

#: M 的顶趟任务行与 C 的那一次关系分析（`c_analysis_runs` 读的就是这张表的 role=C 行）。
TOP_TASK = "t-000001"
C_TASK = "t-000002"

#: 命题 0000 的证明正文（签与 v-review 都钉这一份 —— sha 差一个字节就签不住）。
PROOF_TEXT = "记 G 是 m-正则图。取一条最长路径，逐点比较邻域即得结论。"

#: 只读的那一份"本轮结果"论文（真机 T3 口径：有导言区、有结果章节、参考文献 ≥ 2）。
MAIN_TEX = "\n".join((
    "\\documentclass{article}",
    "\\begin{document}",
    "\\section{结果}",
    "定理 1.5 已由形式化检查器核对（见 stmt:0000、exp:0001）；"
    "n=4 的枚举到界 1000 未见反例（见 exp:0002）。",
    "",
    "\\begin{thebibliography}{9}",
    "\\bibitem{a} Leroy, J. 图论导引. 1930.",
    "\\bibitem{b} Bondy, J. A.; Murty, U. S. R. Graph Theory. 2008.",
    "\\end{thebibliography}",
    "\\end{document}",
    "",
))

#: M 声明的报告体例（R9 之后体例归 M，门只核"你说的和你写的一致"）。
STYLE_SECTIONS: tuple[str, ...] = (
    "一、任务与范围", "二、逐条读数", "三、承重结论", "四、未决问题",
)

#: 验收表的机器可判行 —— 十二行（R1–R12），每一行都现算自本工作区的真台账。
#:
#: 为什么是这十二行：研究链八个环节（`closing.RESEARCH_CHAIN_GROUPS`）各至少一行
#: （R1–R8），外加三条"方向相反"的队列读数（R9–R10）与两条台账厚度读数（R11–R12）。
#: 每一行的 `min`/`max` 都是台账能算出来的数，不是拍的：`retrieval_ok_rows` 的缺省
#: 下限等于 `research_questions` 的行数、`unfinished_request_rows` 的缺省口径是上限 0。
ACCEPTANCE_ROWS: tuple[dict[str, Any], ...] = (
    {"id": "R1", "name": "立题", "kind": "research_question_rows", "min": 1,
     "note": "本趟立起来的研究问题行数"},
    {"id": "R2", "name": "检索（真的取回）", "kind": "retrieval_ok_rows", "min": 1,
     "note": "outcome=ok 的检索次数（一个立起来的问题至少一次成功取回）"},
    {"id": "R3", "name": "算（有结论）", "kind": "numeric_experiment_rows", "min": 1,
     "note": "supports + 界 的数值实验"},
    {"id": "R4", "name": "造（判决性证据）", "kind": "reviewed_proof_rows", "min": 1,
     "note": "我方命题、有证明过程 + 审过（五元位派生出预备定理级）"},
    {"id": "R5", "name": "想（可检验猜想）", "kind": "conjecture_rows", "min": 1,
     "note": "statement 与 testable 都非空的猜想"},
    {"id": "R6", "name": "看（关系分析）", "kind": "c_analysis_runs", "min": 1,
     "note": "tasks 里 role=C 且跑过的行"},
    {"id": "R7", "name": "攻（真推进）", "kind": "plan_progress_rows", "min": 1,
     "note": "至少有一轮 outcome=progress 且该轮有 cites 的计划"},
    {"id": "R8", "name": "交（手稿落盘）", "kind": "document_rows", "min": 1,
     "note": "documents 的行数"},
    {"id": "R9", "name": "闭（请求闭环）", "kind": "unfinished_request_rows", "max": 0,
     "note": "没做完的请求 + pending 重抽取，越少越好"},
    {"id": "R10", "name": "文献消化清零", "kind": "literature_unprocessed_rows", "max": 0,
     "note": "processed 不为真的文献行，越少越好"},
    {"id": "R11", "name": "逐字核验引文", "kind": "quote_verified_rows", "min": 1,
     "note": "带可比对区间的引文行"},
    {"id": "R12", "name": "命题台账", "kind": "statement_rows", "min": 2,
     "note": "我方命题 + 一条文献引文"},
)

#: 四个只读台账文件的相对路径（注册进 `ARTIFACTS.jsonl`；它们之后不许再被改写）。
REGISTERED: tuple[tuple[str, str, str], ...] = (
    ("out/paper/main.tex", "agent-g", "manuscript"),
    ("out/paper/main.pdf", "agent-g", "pdf"),
    ("out/run/evidence.json", "agent-e", "evidence"),
)


# ============================================================ 一 工作区


def _write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _upsert(store: Store, table: str, row: dict[str, Any]) -> dict[str, Any]:
    with store.tx(table, actor="reh8") as tx:
        tx.upsert(table, row)
    return row


def _seed_session(root: pathlib.Path) -> None:
    """一场会话：开场 → 一步 → 一次"问了并答了" → 收尾。

    为什么要有那一次问答：`user_pending` 那格的三态里 `pass` 与"这一段一场都读不到"
    在旧口径下同形；这里让"问过、答了、现在没有待答"是一个真的读出来的 0。
    """
    SESS.append(root, {"kind": "agent_run_start", "role": "M",
                       "task": "REH8 彩排：把这一项研究做到可交付", "ts": TS}, sid=SID)
    SESS.append(root, {"kind": "agent_step", "role": "M", "index": 0,
                       "shape": "conductor.closing", "ts": TS}, sid=SID)
    asked = U.ask_user(root, role="M", question="这一版证据够不够收工？",
                       options=({"label": "够", "description": "按八格读数收工"},),
                       timeout_sec=0, sid=SID, qid="q-1")
    assert asked.state == "pending", asked.to_dict()
    assert U.answer_question(root, qid="q-1", answer="够", sid=SID) == ""
    SESS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final",
                       "steps": 1, "final_chars": 6, "summons": 1, "messages": 1,
                       "elapsed_sec": 2.0, "ts": TS}, sid=SID)


def _seed_tables(store: Store) -> None:
    """把八格要的证据逐格造齐（每一行都从产品写口进盘）。"""
    # ---- 任务台账：M 的顶趟行 + C 的一次关系分析（R6/`c_analysis_runs` 读它）。
    for row in (
        {"task_id": TOP_TASK, "role": "M", "action": "run", "called_by": "user",
         "status": "done", "outcome": "ok", "input_key": "M.run",
         "detail": "REH8 彩排的顶趟", "started_at": TS, "ended_at": TS},
        {"task_id": C_TASK, "role": "C", "action": "relation_paths", "called_by": "M",
         "parent_task_id": TOP_TASK, "status": "done", "outcome": "ok",
         "input_key": "C.relation_paths", "detail": "找出关系图上的热点对",
         "started_at": TS, "ended_at": TS},
    ):
        _upsert(store, "tasks", row)

    # ---- 立题（R1）+ 一次真的取回（R2）：`retrieval_ok_rows` 的下限 = 问题行数。
    q = S.ResearchQuestion(question_id="000000", question="m-正则图的围长下界是多少？",
                           status="answered", priority="high", kind="gap",
                           created_at=TS, updated_at=TS)
    q.validate()
    _upsert(store, "research_questions", q.to_dict())
    req = S.SearchRequest(request_id="r-000001", timestamp=TS, topic="regular graph girth",
                          mode="broad", content_description="查围长下界", done=True,
                          result_lit_ids=["0000"], outcome="ok", providers=["arxiv"])
    req.validate()
    _upsert(store, "search_requests", req.to_dict())

    # ---- 文献（R10 的上限档：这一篇已消化）。
    add_literature(store, "0000", title="Girth of regular graphs", processed=True,
                   source_request_ids=["r-000001"], dedup_key="doi:10.1000/reh8.girth",
                   doi="10.1000/reh8.girth", year=1930,
                   download={"status": "ok", "http_status": 200, "bytes": 42,
                             "sha256": "0" * 64, "error": None})

    # ---- 概念与关系（C 的产物要能被交付面引到：R6 的那条分支靠这条关系）。
    add_concept(store, "0000", "regular graph", definition="每个顶点度数相同的图")
    add_concept(store, "0001", "girth", definition="最短环的长度")
    add_relation(store, "0000", ["0000", "0001"], "0000",
                 quote="The girth of an m-regular graph is at least m.",
                 description="m-正则图围长与度数", page_range=(3, 3),
                 group_key="0000|0001")

    # ---- 命题台账（R12/R11）：一条我方定理（有位记录 + 真签）+ 一条文献引文。
    own = S.Statement(
        stmt_id="0000", origin="own_result", kind="theorem", label="Theorem 1.5",
        statement_text="m-正则图的围长不小于 m", statement_full="设 G 是 m-正则图；则 G 的围长 ≥ m。",
        proof_text=PROOF_TEXT, status="active", created_at=TS, created_by="agent-B",
        # 五元位：第 2 位（有证明过程）+ 第 3 位（审过）⇒ 预备定理级（R4 要的就是它）。
        bits={"proof": True, "reviewed": True,
              "evidence": {"proof_source": "own", "proof_process": PROOF_TEXT,
                           "reviewed_by": {"verification_id": "v-000003",
                                           "round": "V-0001", "verdict": "no_defect"}}},
        # 我方命题没有外部引文要比对 —— 不是 True 就必须说清为什么（三态纪律）。
        quote_reason="我方自产命题，没有外部引文要比对",
    )
    own.validate()
    _upsert(store, "statements", own.to_dict())
    cited = S.Statement(
        stmt_id="0001", origin="external_lit", kind="theorem", label="Lemma 2.1",
        statement_text="正则图的围长至少为 3", statement_full="任何 m ≥ 3 的正则图，围长至少为 3。",
        proof_text="The girth of an m-regular graph is at least m.",
        source_lit_id="0000", quote_verified=True, quote_span="p3:norm[4:52]",
        quote_reason="逐字命中文献第 3 页", status="active", created_at=TS,
        created_by="agent-B",
    )
    cited.validate()
    _upsert(store, "statements", cited.to_dict())

    # ---- 真签：走 `verifications.record_verification` 三票 + `vsigns.issue` 发签。
    # 这一步是「造」那一环的证据：`own_result_manuscript_link` 认的是台账里的签，
    # 不是行上的自报（`closing.py:860`）。
    issue_credential(store.root, proof_text=PROOF_TEXT.strip("\n"), statement_id="0000",
                     manuscript="reports/f-proof-0000.md")

    # ---- 猜想（R5）：statement 与 testable 都非空。
    con = S.Conjecture(conjecture_id="000000", statement="围长下界可以改进到 m+1",
                       form="universal",
                       testable={"params": {"m": 4}, "bounds": {"N": 1000},
                                 "why": "在 m=4 上枚举到界 1000"},
                       origin="rel:0000", status="supported_not_proved",
                       experiment_ids=["0002"], created_at=TS, created_by="agent-E")
    con.validate()
    _upsert(store, "conjectures", con.to_dict())

    # ---- 实验（R3 的结论档 + 承重门要的 T3 档）。
    formal = S.Experiment(
        experiment_id="0001", claim="Theorem 1.5 的证明", claim_key="thm:1.5",
        method="formal", evidence_kind="proof", result="supports",
        negation_kind="not_proved", code_path="code/lean/thm.lean",
        code_hash="deadbeefdeadbeef", exit_code=0,
        verifier_output="'thm_1_5' does not depend on any axioms",
        verifier_subject_key="thm:1.5", created_at=TS)
    formal.validate()
    _upsert(store, "experiments", formal.to_dict())
    numeric = S.Experiment(
        experiment_id="0002", claim="在 n=4 时枚举到界 1000", claim_key="girth:bound",
        method="numeric", evidence_kind="cross_check", result="supports",
        negation_kind="not_proved", code_hash="cafebabecafebabe", exit_code=0,
        search_bound={"N": 1000}, params={"n": 4}, created_at=TS)
    numeric.validate()
    _upsert(store, "experiments", numeric.to_dict())

    # ---- 攻坚计划（R7）：至少一轮 outcome=progress 且该轮有 cites。
    plan = S.AttackPlan(
        plan_id="000000", problem="把围长下界推进一步", problem_key="girth-lower-boost",
        for_question_id="000000", status="open", rounds=1,
        budget={"max_rounds": 4, "max_parallel_subgoals": 2,
                "max_persist_attempts": 3, "max_depth": 1},
        subgoals=[], created_at=TS, updated_at=TS,
        history=[{"round": 1, "sid": "s1", "action": "reduce",
                  "outcome": "progress", "evidence": ["stmt:0000"], "at": TS,
                  # `_round_advanced` 认 `cites`（"有据可依"那一半）：
                  "product_detail": {"steps": [{"cites": ["stmt:0000"]}]}}])
    plan.validate()
    _upsert(store, "attack_plans", plan.to_dict())

    # ---- 稿件（R8）：一节有正文，三条断言分别引 exp/exp/rel（覆盖内容判据的三条分支）。
    doc = S.Document(
        doc_id="0000", kind="paper", title="m-正则图的围长下界",
        status="accepted", content_sha256="a" * 64, created_at=TS, updated_at=TS,
        review_verdict="成立", reviewed_at=TS, reviewed_by="agent-H",
        sections=[{"heading": "结果", "body": "定理 1.5 与数值枚举的结论如下。"}],
        claims=[
            {"claim_id": "c1", "section": "结果", "evidence_kind": "proof",
             "text": "定理 1.5 的数值旁证：n=4 到界 1000", "citations": ["exp:0001"]},
            {"claim_id": "c2", "section": "结果", "evidence_kind": "cross_check",
             "text": "n=4 的枚举到界 1000，未见反例", "citations": ["exp:0002"],
             "disclaimer": "数值交叉验证，不构成证明"},
            {"claim_id": "c3", "section": "结果", "evidence_kind": "heuristic",
             "text": "关系分析的热点对见 rel:0000", "citations": ["rel:0000"]},
        ],
    )
    doc.validate()
    _upsert(store, "documents", doc.to_dict())

    # ---- H 的一条审校发现（`substance` 那五张表之一；已处置，不是 open）。
    # 为什么不给 open：`acceptance` 有一条自动分支（`reviewed_current_rows` 的
    # `open_findings_unreviewed`）会因"有 open findings 而这一版没有复审记录"判红 ——
    # 那是它的正确行为，而这一份彩排要的是"处置完、且有记录"的形态。
    finding = S.ReviewFinding(
        finding_id="000000", doc_id="0000", kind="overclaim", level="warning",
        target="claim-2", evidence="数值断言用了「已证明」的措辞",
        message="把「已证明」改成「数值交叉验证」", status="fixed", round=1,
        suggestion="改词，不改结论", resolution_note="G.revise 已改，H.verify_fixes 复核过",
        created_at=TS, created_by="agent-H")
    finding.validate()
    _upsert(store, "review_findings", finding.to_dict())
    sync_counters(store)


def _seed_literature_queue(store: Store) -> None:
    """待入库文献表（第八格）：两条判过、一条入库一条拒收，然后真的清表。

    走 `litstage.clear_delegation`（清表 + 归档 + 事件）—— 这一格 `pass` 的两个条件是
    「全表没有 pending」与「当前委托的每一行都有 `cleared_at`」，两个都得由这一笔兑现。
    """
    for row in (
        S.LitCandidate(slot="000000", batch=1, status="admitted", title="Girth of regular graphs",
                       request_id="r-000001", doi="10.1000/reh8.girth",
                       relevance="给了 m-正则图围长的下界", lit_id="0000",
                       admitted_at=TS, added_at=TS),
        S.LitCandidate(slot="000001", batch=1, status="rejected", title="A survey of nothing",
                       request_id="r-000001", reason_code="rejected_off_topic",
                       reject_reason="与围长下界无关", added_at=TS),
    ):
        row.validate()
        _upsert(store, "lit_candidates", row.to_dict())
    got = LS.clear_delegation(store, "r-000001", actor="agent-A",
                              reason="本委托收工：入库 1 篇、拒收 1 篇")
    assert got["cleared"] == 2, got


def _write_paper_package(root: pathlib.Path) -> None:
    """正文 + 对应表三份 + 编一遍（回执只认 `main.tex`，所以顺序不能换）。"""
    _write(root / "out" / "paper" / "main.tex", MAIN_TEX)
    PM.write_package(root, [])
    engine = FX.fake_engine(root / "_engine")
    with FX.use_engine(engine):
        got = PC.compile_paper(root)
    assert got.get("ok") is True, got


def _write_report(root: pathlib.Path) -> pathlib.Path:
    """M 的交付说明 + 体例声明（`report_shape` 的附件三件套与声明节名都要兑现）。"""
    lines = ["# 审核报告", ""]
    for name in STYLE_SECTIONS:
        lines += [f"## {name}", f"{name.split('、', 1)[1]}的读数：逐条见台账。", ""]
    lines += ["附件：origin=own_result；依据读数见 §三；版本 sha256=" + "a" * 64 + "。", ""]
    path = _write(root / "out" / "review" / "REPORT.md", "\n".join(lines))
    _write(root / "out" / "review" / "REPORT-STYLE.json",
           json.dumps({"sections": list(STYLE_SECTIONS)}, ensure_ascii=False) + "\n")
    return path


def _write_acceptance(root: pathlib.Path, rows: Any = ACCEPTANCE_ROWS) -> pathlib.Path:
    return _write(root / CL.ACCEPTANCE_CHECKS_NAME,
                  json.dumps({"checks": list(rows)}, ensure_ascii=False, indent=2) + "\n")


def _register_artifacts(root: pathlib.Path) -> None:
    """产物台账：先让文件在盘上，再逐条登记（`artifacts.record` 拒登不存在的路径）。"""
    _write(root / "out" / "run" / "evidence.json",
           json.dumps({"run": "reh8", "claims": 3}, ensure_ascii=False) + "\n")
    for rel, producer, kind in REGISTERED:
        assert (root / rel).is_file(), f"夹具前提：{rel} 还没落盘"
        AR.record(root, path=rel, producer=producer, kind=kind, task_id=TOP_TASK, at=TS)


def build(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    """造那个「八格都造齐」的彩排工作区；返回 `(store, 工作区根)`。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root)
    store.init()
    _seed_session(root)
    _seed_tables(store)
    _seed_literature_queue(store)
    _write_paper_package(root)
    _write_acceptance(root)
    _write_report(root)
    _register_artifacts(root)
    return store, root


def gate(store: Store, *, goal_met: bool = True, retire: Any = None,
         programs: Any = None) -> CL.ClosingReport:
    """与真机同形地跑一遍八格（`project_dir="."`、`report_path` 相对工作区）。"""
    return CL.check_closing(
        store, project_dir=".", report_path="out/review/REPORT.md",
        session_root=pathlib.Path(str(store.root)), sid=SID,
        goal="REH8：把这一项研究做到可交付", goal_met=goal_met,
        basis="八格逐格现算的读数（见 readings）",
        task_list=[{"what": "八格逐格读数", "state": "done"},
                   {"what": "证据落台账", "state": "done"}],
        retire=retire if retire is not None
        else {"checked": True, "complete": True, "reason": "彩排：名册树已清"},
        programs=programs if programs is not None
        else {"checked": True, "running_count": 0, "unowned": [],
              "reason": "彩排：没有在跑的程序"},
    )


# ============================================================ 二 读数（打印）


def _print_cells(rep: CL.ClosingReport) -> None:
    """把八格逐格与它们的关键读数打出来（判据红的时候这些数就在报告里）。"""
    for name in CL.DEFAULT_CHECKS:
        print(f"[REH8] {name:20s} status={rep.status.get(name)!r}")
    print(f"[REH8] machine_pass={rep.machine_pass} can_close={rep.can_close} "
          f"m_says_done={rep.m_says_done} exit={CL.tri_state_exit_code(rep)}")
    print(f"[REH8] failed={rep.failed} unknowns={rep.unknowns} "
          f"blockers={[f.code for f in rep.blockers]}")


def _key_readings(rep: CL.ClosingReport) -> dict[str, Any]:
    """八格各自的"承重读数"（正控里逐格断言它们，而不是只断言 status）。"""
    acc = rep.readings.get("acceptance") or {}
    return {
        "contradictions": {
            "disputed_source": (rep.readings.get("contradictions") or {}).get("disputed_source"),
            "own_hole": (rep.readings.get("contradictions") or {}).get("own_hole"),
            "review_unresolved": (rep.readings.get("contradictions") or {}).get("review_unresolved"),
            "pollution_unreadable": (rep.readings.get("contradictions") or {}).get(
                "pollution_unreadable"),
        },
        "load_bearing": {
            "claims_with_proof": (rep.readings.get("load_bearing") or {}).get(
                "claims_with_proof"),
            "claims_without_t3": (rep.readings.get("load_bearing") or {}).get(
                "claims_without_t3"),
            "state": (rep.readings.get("load_bearing") or {}).get("state"),
        },
        "report_shape": {
            "path": (rep.readings.get("report_shape") or {}).get("path"),
            "missing_declared_sections": (rep.readings.get("report_shape") or {}).get(
                "missing_declared_sections"),
            "missing_attachment_fields": (rep.readings.get("report_shape") or {}).get(
                "missing_attachment_fields"),
        },
        "user_pending": {
            "pending": (rep.readings.get("user_pending") or {}).get("pending"),
            "asked": (rep.readings.get("user_pending") or {}).get("asked"),
            "answered": (rep.readings.get("user_pending") or {}).get("answered"),
        },
        "substance": dict(rep.readings.get("substance") or {}),
        "acceptance": {
            "rows_read": acc.get("rows_read"), "rows_na": acc.get("rows_na"),
            "rows_unreadable": acc.get("rows_unreadable"),
            "rows_unknown": acc.get("rows_unknown"),
            "research_missing": (acc.get("research_chain") or {}).get("missing"),
            "unmet": [f.detail for f in rep.findings
                      if f.check == "acceptance" and f.level == "blocker"],
        },
        "artifact_ledger": {
            "entries": (rep.readings.get("artifact_ledger") or {}).get("entries"),
            "missing": (rep.readings.get("artifact_ledger") or {}).get("missing"),
            "unreadable": (rep.readings.get("artifact_ledger") or {}).get("unreadable"),
            "changed": (rep.readings.get("artifact_ledger") or {}).get("changed"),
        },
        "literature_pending": {
            "pending": (rep.readings.get("literature_pending") or {}).get("pending"),
            "request_id": (rep.readings.get("literature_pending") or {}).get("request_id"),
            "cleared": (rep.readings.get("literature_pending") or {}).get("cleared"),
            "closed_delegations": (rep.readings.get("literature_pending") or {}).get(
                "closed_delegations"),
        },
    }


# ============================================================ 三 正控


def test_the_workspace_covers_every_default_cell() -> None:
    """口径自检：本文件钉的八格就是 `closing.DEFAULT_CHECKS` 那一份（不复制第二张表）。

    少了它，"八格全过"可以靠"这一份只跑它自己挑的三格"变绿 —— 那正是这一路要防的形态。
    """
    assert tuple(CL.DEFAULT_CHECKS) == (
        "contradictions", "load_bearing", "report_shape", "user_pending", "substance",
        "acceptance", "artifact_ledger", "literature_pending"), CL.DEFAULT_CHECKS
    assert len(CL.DEFAULT_CHECKS) == 8


def test_the_eight_cells_all_pass_in_the_rehearsal_workspace(tmp_path: pathlib.Path):
    """正控：真账本 + 真表 ⇒ 八格逐格 `pass`，`verdict` 的每一半都为真。

    2026-11-19（ROOTGATE-①）：八格与机器读数合成一份结论
    （`closing.closing_verdict`）。这一条要求那一份的每一半都真：八格全 pass、
    `m_says_done`、`retire.complete`、`programs_ok` ⇒ `verdict=pass`、`can_close=true`。
    """
    store, _root = build(tmp_path)
    rep = gate(store)
    _print_cells(rep)

    assert set(rep.status) == set(CL.DEFAULT_CHECKS), rep.status
    assert {k: v for k, v in rep.status.items() if v != "pass"} == {}, rep.to_dict()
    assert rep.machine_pass is True
    assert rep.blockers == [], [f.to_dict() for f in rep.blockers]
    assert rep.unknowns == [], rep.to_dict()

    # ---- 机器口径那一格：三态必须是"算出来了"，不是 not_wired
    caliber = rep.readings["machine_caliber"]
    assert caliber["checked"] is True, caliber
    assert rep.m_says_done is True
    assert rep.can_close is True, rep.can_close_reason
    assert CL.tri_state_exit_code(rep) == 0

    # ---- 逐格的承重读数（不是只看 status）
    got = _key_readings(rep)
    print(f"[REH8] 逐格读数={json.dumps(got, ensure_ascii=False, default=str)[:2000]}")
    assert got["contradictions"]["disputed_source"] == []
    assert got["contradictions"]["own_hole"] == []
    assert got["load_bearing"]["claims_with_proof"] == 1
    assert got["load_bearing"]["claims_without_t3"] == 0
    assert got["report_shape"]["path"], got["report_shape"]
    assert got["report_shape"]["missing_declared_sections"] == []
    assert got["report_shape"]["missing_attachment_fields"] == []
    assert got["user_pending"]["pending"] == []
    assert got["user_pending"]["answered"] == 1
    assert all(int(got["substance"].get(t) or 0) > 0
               for t in CL.SUBSTANCE_TABLES), got["substance"]
    assert got["acceptance"]["rows_read"] == len(ACCEPTANCE_ROWS), got["acceptance"]
    assert got["acceptance"]["rows_unreadable"] == 0
    assert got["acceptance"]["rows_unknown"] == 0
    assert got["acceptance"]["research_missing"] == []
    assert got["acceptance"]["unmet"] == []
    assert got["artifact_ledger"]["entries"] == len(REGISTERED)
    assert got["artifact_ledger"]["missing"] == 0
    assert got["artifact_ledger"]["unreadable"] == 0
    assert got["literature_pending"]["pending"] == 0
    assert got["literature_pending"]["cleared"] is True
    assert got["literature_pending"]["closed_delegations"] == 1

    # ---- 每一行验收行都是真的按台账算过（`state == "computed"`），没有一行靠 `na` 顶着
    rows = rep.readings["acceptance"]["rows"]
    assert [r["state"] for r in rows] == ["computed"] * len(ACCEPTANCE_ROWS), rows
    assert all(r["ok"] is True for r in rows), rows


# ============================================================ 四 反真空（八条）

#: 每一格"弄坏哪一处"（一句话进判据红时的报错；与 `_break` 的 if 分支一一对应）。
BREAKS: dict[str, str] = {
    "contradictions": "在 dependencies 里加一行 status=disputed（一条来源争议）",
    "load_bearing": "把承重断言的引文从 T3 实验 exp:0001 改成数值实验 exp:0002",
    "report_shape": "删掉 out/review/REPORT.md（给了 report_path 而盘上没这份文件）",
    "user_pending": "再登记一个没人回答的问题（q-2）",
    "substance": "清空 substance 认的五张表（documents/relations/experiments/review_findings/statements）",
    "acceptance": "把验收行 R12 的 min 抬到台账给不出的条数（99）",
    "artifact_ledger": "删掉一条已登记的产物 out/run/evidence.json",
    "literature_pending": "往待入库文献表里塞回一条 pending 行（slot 000002）",
}


def _break(root: pathlib.Path, store: Store, which: str) -> None:
    """把一个必要条件弄坏（只动一处；每一处的对象都是产品自己读的那张表/那份文件）。"""
    if which == "contradictions":
        _upsert(store, "dependencies", {
            "dep_id": "000000", "label": "两篇文献对同一条命题两说",
            "used_by": "0000", "status": "disputed", "kind": "theorem",
            "status_reason": "两篇文献对同一条命题给出相反说法，还没裁",
            "created_at": TS})
        return
    if which == "load_bearing":
        rows = [dict(r) for r in store.rows("documents")]
        doc = next(r for r in rows if str(r.get("doc_id")) == "0000")
        doc["claims"] = [dict(c) for c in doc["claims"]]
        for claim in doc["claims"]:
            if claim["claim_id"] == "c1":
                claim["citations"] = ["exp:0002"]      # 数值行不是 T3
        _upsert(store, "documents", doc)
        return
    if which == "report_shape":
        (root / "out" / "review" / "REPORT.md").unlink()
        return
    if which == "user_pending":
        got = U.ask_user(root, role="M", question="要不要再加一轮枚举？",
                         options=({"label": "加", "description": "再跑到界 2000"},),
                         timeout_sec=0, sid=SID, qid="q-2")
        assert got.state == "pending", got.to_dict()
        return
    if which == "substance":
        for table in CL.SUBSTANCE_TABLES:
            with store.tx(table, actor="reh8") as tx:
                key = S.TABLES[table]["id_field"]
                for row in [dict(r) for r in tx.rows(table)]:
                    tx.delete(table, row.get(key))
        return
    if which == "acceptance":
        rows = [dict(r) for r in ACCEPTANCE_ROWS]
        for row in rows:
            if row["id"] == "R12":
                row["min"] = 99
        _write_acceptance(root, rows)
        return
    if which == "artifact_ledger":
        (root / "out" / "run" / "evidence.json").unlink()
        return
    if which == "literature_pending":
        _upsert(store, "lit_candidates", {
            "slot": "000002", "batch": 1, "status": "pending",
            "title": "还没人判的一篇", "request_id": "r-000001", "added_at": TS})
        return
    raise AssertionError(f"没有这一格：{which!r}")


def _assert_one_cell_red(rep: CL.ClosingReport, cell: str) -> None:
    """弄坏一处的读数：那格 `fail`、门被拦（`machine_pass=False`、`can_close=False`、退出码 1）。

    2026-11-19（ROOTGATE-①）：`can_close` 现在也读那八格 —— 它必须一起变 false；
    只断言 `machine_pass` 会让"结论不读八格"这个根因重新长回来。
    """
    assert rep.status.get(cell) == "fail", (cell, rep.status, rep.to_dict())
    assert rep.machine_pass is False, rep.to_dict()
    assert rep.can_close is False, (cell, rep.can_close, rep.can_close_reason)
    assert CL.tri_state_exit_code(rep) == 1, rep.to_dict()
    assert [f for f in rep.blockers], "拦门了，却没有一条 blocker —— 读的人不知道为什么红"


def _run_broken(tmp_path: pathlib.Path, cell: str) -> CL.ClosingReport:
    store, root = build(tmp_path)
    _break(root, store, cell)
    rep = gate(store)
    _print_cells(rep)
    return rep


def test_breaking_contradictions_turns_that_cell_red(tmp_path: pathlib.Path):
    rep = _run_broken(tmp_path, "contradictions")
    _assert_one_cell_red(rep, "contradictions")
    assert rep.readings["contradictions"]["disputed_source"], rep.readings["contradictions"]
    assert rep.failed == ["contradictions"], rep.failed


def test_breaking_load_bearing_turns_that_cell_red(tmp_path: pathlib.Path):
    rep = _run_broken(tmp_path, "load_bearing")
    _assert_one_cell_red(rep, "load_bearing")
    got = rep.readings["load_bearing"]
    assert got["claims_with_proof"] == 1 and got["claims_without_t3"] == 1, got
    assert got["claims"][0]["backed_by"] == "", got["claims"]
    assert rep.failed == ["load_bearing"], rep.failed


def test_breaking_report_shape_turns_that_cell_red(tmp_path: pathlib.Path):
    rep = _run_broken(tmp_path, "report_shape")
    _assert_one_cell_red(rep, "report_shape")
    assert rep.readings["report_shape"]["exists"] is False, rep.readings["report_shape"]
    assert rep.failed == ["report_shape"], rep.failed


def test_breaking_user_pending_turns_that_cell_red(tmp_path: pathlib.Path):
    rep = _run_broken(tmp_path, "user_pending")
    _assert_one_cell_red(rep, "user_pending")
    assert [q["qid"] for q in rep.readings["user_pending"]["pending"]] == ["q-2"]
    assert rep.failed == ["user_pending"], rep.failed


def test_breaking_substance_turns_that_cell_red(tmp_path: pathlib.Path):
    """`substance` 的必要条件是"五张表里至少一张非空"—— 弄坏它只能把五张都清空。

    为什么这一条的 `failed` 不是单格：`acceptance` 的行（R8/R12）读的正是
    `documents` / `statements` 这两张被清空的表 ⇒ 它必然一起红。这不是判据互相矛盾，
    而是 `substance` 是全局前置条件（"这一趟什么都没产出"时下游读数本来就没有对象）。
    所以这一条只钉方向：`substance` 必须 `fail`、门必须被拦。
    """
    rep = _run_broken(tmp_path, "substance")
    _assert_one_cell_red(rep, "substance")
    assert all(int(v or 0) == 0 for v in rep.readings["substance"].values()), \
        rep.readings["substance"]
    assert "acceptance" in rep.failed, rep.failed
    assert set(rep.failed) == {"substance", "acceptance"}, rep.failed


def test_breaking_acceptance_turns_that_cell_red(tmp_path: pathlib.Path):
    rep = _run_broken(tmp_path, "acceptance")
    _assert_one_cell_red(rep, "acceptance")
    row = next(r for r in rep.readings["acceptance"]["rows"] if r["id"] == "R12")
    assert row["ok"] is False and row["got"] == 2 and row["min"] == 99, row
    assert rep.failed == ["acceptance"], rep.failed


def test_breaking_artifact_ledger_turns_that_cell_red(tmp_path: pathlib.Path):
    rep = _run_broken(tmp_path, "artifact_ledger")
    _assert_one_cell_red(rep, "artifact_ledger")
    assert rep.readings["artifact_ledger"]["missing"] == 1, rep.readings["artifact_ledger"]
    assert rep.failed == ["artifact_ledger"], rep.failed


def test_breaking_literature_pending_turns_that_cell_red(tmp_path: pathlib.Path):
    rep = _run_broken(tmp_path, "literature_pending")
    _assert_one_cell_red(rep, "literature_pending")
    assert rep.readings["literature_pending"]["pending"] == 1
    assert rep.failed == ["literature_pending"], rep.failed


def test_every_cell_has_a_break(tmp_path: pathlib.Path):
    """口径自检：`BREAKS` 的键集必须恰好是八格（少一格 = 那一格没有反真空）。"""
    assert set(BREAKS) == set(CL.DEFAULT_CHECKS), (set(BREAKS), set(CL.DEFAULT_CHECKS))


# ============================================================ 五 一份结论的两半


def test_only_the_machine_caliber_can_turn_can_close_off(tmp_path: pathlib.Path):
    """`can_close` 的机器那半边也有牙：八格全 pass 而 `retire` 不干净 ⇒ false。

    这一条与上面八条是成对的：上面八条证明"格子有牙"，这一条证明"机器读数那一格
    也有牙"（业主 2026-11-03 的裁决 ①=乙：`retire.complete` 与 `programs_ok` 仍进结论）。
    2026-11-19（ROOTGATE-①）之后两半合成一份：八格全 pass 也救不了不干净的 retire。
    """
    store, _root = build(tmp_path)
    rep = gate(store, retire={"checked": True, "complete": False,
                              "reason": "彩排：名下还有在册节点"})
    _print_cells(rep)
    assert {k: v for k, v in rep.status.items() if v != "pass"} == {}, rep.status
    assert rep.machine_pass is True and rep.m_says_done is True
    assert rep.can_close is False, rep.can_close_reason
    assert "retire 不干净" in rep.can_close_reason, rep.can_close_reason
    assert CL.tri_state_exit_code(rep) == 1


def test_an_unwired_machine_caliber_is_not_a_pass(tmp_path: pathlib.Path):
    """三态：`retire` / `programs` 没喂进来 ⇒ `can_close is None`、退出码 2（不是 0）。

    "没接线"是 `unknown`，不是"可以交"：改前 `closable` 会退回到
    `m_says_done ∧ machine_pass` 并给出退出码 0 —— 那正是"没查成被读成通过"。
    现在 `verdict=unknown` ⇒ `closable=False`、退出码 2（ROOTGATE-①）。
    """
    store, _root = build(tmp_path)
    rep = CL.check_closing(
        store, project_dir=".", report_path="out/review/REPORT.md",
        session_root=pathlib.Path(str(store.root)), sid=SID,
        goal="REH8：把这一项研究做到可交付", goal_met=True, basis="八格读数",
        task_list=[{"what": "八格逐格读数", "state": "done"}])
    assert rep.machine_pass is True
    assert rep.can_close is None, rep.can_close_reason
    assert rep.readings["machine_caliber"]["checked"] is False
    assert rep.can_close_reason.startswith("not_wired:"), rep.can_close_reason
    assert rep.closable is False, "没查成不是'能停'"
    assert CL.tri_state_exit_code(rep) == 2
