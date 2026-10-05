# -*- coding: utf-8 -*-
"""收工门（`draft/37` §16 P3）：五条各自能造红，`unknown` 不算通过。

## 这一组守什么

P3 的收工门是"把纪律变成门"，所以判据的重点不是"门能不能跑"，而是
每一条都能单独造红：把某一条弄坏之后，红的必须正好是它，其余四条仍然绿。
只测"全好 ⇒ 全绿"是不够的 —— 那样的门完全可能是一条恒真的判据。

五条与它们的负控（`draft/37` §16 P3 逐字要求"每一条都能单独造红（五条负控）"）：

| 检查 | 负控（本文件里各一条） |
|---|---|
| `anchor` | 封好锚之后再改一次 `main.tex` ⇒ `drifted` |
| `contradictions` | 挂一条 `status="disputed"` 的依赖 |
| `load_bearing` | 一条 `evidence_kind="proof"` 的正文断言没有 T3 背书 |
| `report_shape` | 报告抽掉一节 + 抽掉分栏标记 |
| `user_pending` | 问了一个还没被回答的问题 |

外加两条反向判据（§10.2 的负控②、"没查成"那一档）：
- 已降档的结论不许因为没上 T3 而判失败（省下来的钱要看得见）；
- 没给项目根 / 没给报告路径 ⇒ `unknown`，而 `unknown` 不许算通过。
"""
from __future__ import annotations

import json
import pathlib

from conftest import TS, sync_counters
from agentflow import closing as CL
from agentflow import renderanchor as RA
from agentflow import schema as S
from agentflow import userio as U
from agentflow.store import Store

# ============================================================ 夹具


def _seal(root: pathlib.Path, st: Store) -> None:
    """写锚 + 回执（必须在最后一次写台账之后，否则锚一出生就是 drifted）。

    这一条本身就是 `doc.paper_state` 的真机教训：锚的 `rows` 维度把 store 的行
    也算在内 ⇒ 封完之后再写一行台账，锚立刻报 `drifted`。
    """
    out = root / "out" / "paper"
    (out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)), encoding="utf-8")
    (out / RA.RECEIPT_NAME).write_text(json.dumps(RA.build_receipt(
        out, tex_sha256=RA.file_digest(out / "main.tex"), pages=21, markers_missing=[],
        pdf_bytes=13, compiler_exit_codes=[0])), encoding="utf-8")


def _project(root: pathlib.Path, *, seed=None) -> Store:
    """造一个论文包项目：先写台账行（seed）再封锚（顺序就是 §PAPER_PACK 要求的那个）。"""
    out = root / "out" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init(force=True)
    (out / "main.tex").write_text("\\date{2026-01-01}\nbody\n", encoding="utf-8")
    (out / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    if seed is not None:
        seed(st)
    _seal(root, st)
    return st


def _write_report(root: pathlib.Path, *, drop_section: str = "",
                  drop_split: bool = False) -> pathlib.Path:
    """写一份九节齐全的报告（可注入两处缺陷）。"""
    p = root / "out" / "review" / "REPORT.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 审核报告", ""]
    for num, name in CL.REPORT_SECTIONS:
        if num == drop_section:
            continue
        lines.append(f"## {num}、{name}")
        lines.append(f"{name}的读数：逐条见台账。")
        lines.append("")
    if not drop_split:
        lines += ["分栏：以下是**我们补的**（不是**原文的**）。", ""]
    lines += ["附件：origin=own_result；依据读数见 §四；版本 sha256=deadbeef。", ""]
    p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return p


def _t3_experiment(store: Store, eid: str = "0001", **kw) -> dict:
    """一条 T3 形态的实验行（formal + proof + 检查器原话）。

 想做"没有 T3 背书"的负控，不能用这条然后把 `verifier_output` 清空 ——
    `schema.Experiment.validate`（FC-22 的机械落地）会当场拒：
    `evidence_kind='proof'` 必须有检查器原话。真实的缺陷形态是
    "数值支持被当成证明"，所以负控走 `_numeric_experiment`（见下）。
    """
    base = dict(experiment_id=eid, claim="Theorem 1.5 的证明", claim_key="thm:1.5",
                method="formal", evidence_kind="proof", result="supports",
                negation_kind="not_proved", code_path="code/lean/thm.lean",
                code_hash="deadbeefdeadbeef", exit_code=0,
                verifier_output="'thm_1_5' does not depend on any axioms",
                verifier_subject_key="thm:1.5", created_at=TS)
    base.update(kw)
    row = S.Experiment(**base)
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _numeric_experiment(store: Store, eid: str = "0001") -> dict:
    """一条只有数值支持的实验行（`cross_check`）：不是 T3。

    这是"承重结论缺 T3"最真实的形态：数值跑出来支持，但没有任何检查器说过话。
    """
    row = S.Experiment(experiment_id=eid, claim="Theorem 1.5 的数值检查", claim_key="thm:1.5",
                       method="numeric", evidence_kind="cross_check", result="supports",
                       negation_kind="not_proved", code_path="code/exp.py",
                       code_hash="deadbeefdeadbeef", exit_code=0, created_at=TS)
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _paper_with_claim(store: Store, *, evidence_kind: str = "proof",
                      citations: list[str] | None = None, doc_id: str = "0001") -> dict:
    """一份带一条断言的稿件（默认 proof 级、引到 T3 实验）。

    `cross_check` 的那一档必须自带 `disclaimer` —— 那是 `schema.Document.validate`
    的结构强制（FC-22："数值交叉验证，不构成证明"这句话不靠人记得写）。
    """
    claim: dict = {"claim_id": "c1", "text": "已证明定理 1.5",
                   "citations": citations if citations is not None else ["exp:0001"],
                   "evidence_kind": evidence_kind, "section": "§2"}
    if evidence_kind == "cross_check":
        claim["disclaimer"] = "数值交叉验证，不构成证明"
    row = S.Document(doc_id=doc_id, kind="paper", title="未发表的论文", status="in_review",
                     claims=[claim], created_at=TS)
    row.validate()
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _good(tmp_path: pathlib.Path):
    """五条全过的那个工作区（正控的底座）：先写台账，再封锚，最后写报告。"""
    def seed(st: Store) -> None:
        """台账里的两条行：一条 T3 实验 + 一条引到它的 proof 级断言。"""
        _t3_experiment(st)
        _paper_with_claim(st)

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    return st, report


def _gate(st: Store, report: pathlib.Path | None, *, project_dir: pathlib.Path | None = None):
    return CL.check_closing(
        st,
        project_dir=str(project_dir if project_dir is not None else st.root),
        report_path=str(report) if report is not None else "",
    )


# ============================================================ 正控

def test_a_ready_workspace_passes_every_check(tmp_path: pathlib.Path):
    """正控：每条都过 ⇒ `can_close` 为真，且没有 blocker。

    这一条本身不足以证明门有效（一条恒真的判据也能过），所以后面每一条
    都配一条"只把它弄坏"的负控 —— 合起来才是这组判据的全部。
    """
    st, report = _good(tmp_path)
    rep = _gate(st, report)
    assert rep.status == {name: "pass" for name in CL.DEFAULT_CHECKS}, rep.to_dict()
    assert rep.can_close and not rep.blockers, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 0
    assert f"{len(CL.DEFAULT_CHECKS)} 条全过" in rep.summary(), rep.summary()


# ============================================================ 各条负控（各自单独红）

def _acceptance_checks(root: pathlib.Path, rows: list[dict], *, st: Store | None = None) -> pathlib.Path:
    """把机器可判的验收行写进项目（`out/paper/ACCEPTANCE-CHECKS.json`）。

    给了 `st` 就顺手重封一次锚：这一格的文件落在 `out/paper` 里，而锚的 `files` 维度
    覆盖那个目录 ⇒ 封锚之后再写它，锚会报 `drifted`（真机上这份文件是建工作区时
    就写好的，所以那个顺序不是问题；判据里要显式重封，免得把锚的红当成这一格的红）。
    """
    path = root / "out" / "paper" / CL.ACCEPTANCE_CHECKS_NAME.split("/", 2)[-1]
    path.write_text(json.dumps({"checks": rows}, ensure_ascii=False), encoding="utf-8")
    if st is not None:
        _seal(root, st)
    return path


def test_the_acceptance_cell_goes_red_alone_when_a_named_leg_has_no_ledger_row(
        tmp_path: pathlib.Path):
    """负控（`draft/37` §94 的真机读数）：任务点名的腿在台账里没凭据 ⇒ 这一格单独红。

    T1 第 7、8 趟：逐字核验引文与形式化验证都没落台账（`statements`/`literature` 0 行），
    而收工门六格全过、`can_close=true` —— `substance` 只问"五张表里有没有非空的"，
    于是"缺了两条腿"被读成"可交付"。这一条判据就是那次假绿的反面。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P7", "name": "引文逐条核过", "kind": "quote_verified_rows", "min": 1},
        {"id": "P8", "name": "形式化", "kind": "proof_experiment_rows", "min": 1},
    ], st=st)
    rep = _gate(st, report)
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["acceptance_unmet"], rep.to_dict()
    assert rep.status["anchor"] == "pass" and rep.status["substance"] == "pass", rep.to_dict()
    detail = rep.blockers[0].detail
    # 夹具里本来就有一条 formal+proof 实验（`_t3_experiment`）⇒ P8 满足、只有 P7 缺。
    # 这一格必须逐行判（不许一票通吃），所以缺的那一行要点名、满足的那一行不进 detail。
    assert "P7" in detail and "P8" not in detail, detail
    rows = rep.readings["acceptance"]["rows"]
    assert [r["id"] for r in rows] == ["P7", "P8"], rows
    assert [r["ok"] for r in rows] == [False, True], rows
    assert rows[0]["got"] == 0 and rows[1]["got"] >= 1, rows


def test_the_acceptance_cell_passes_once_each_leg_has_a_ledger_row(tmp_path: pathlib.Path):
    """正控（反真空）：把凭据真的落进台账 ⇒ 这一格转 `pass`。

    三条腿各造一条：`quote_verified` 非 null 的命题、`method=formal` + `evidence_kind=proof`
    的实验、`review_rounds >= 1` 的稿件。判据不是"文件在不在"，而是台账里真的有没有。
    """
    def seed(s: Store) -> None:
        _t3_experiment(s, "0002", method="formal", evidence_kind="proof")
        _paper_with_claim(s, doc_id="0002")
        with s.tx("documents", actor="test") as tx:
            row = dict(tx.rows("documents")[0])
            row["review_rounds"] = 1
            tx.upsert("documents", row)
        with s.tx("statements", actor="test") as tx:
            tx.upsert("statements", {
                "stmt_id": "0000", "origin": "external_lit", "kind": "theorem",
                "statement_full": "设 G 是任意有限群；则 c(G) ≤ 1。",
                "proof_text": "Proof. 见第 3 节（逐字摘录）。",
                "source_lit_id": "0000", "page_range": {"start": 1, "end": 2},
                "quote_verified": True, "quote_reason": "逐字比对通过（第 1 页）",
                "evidence_kind": "cross_check", "status": "active",
                "created_at": TS, "created_by": "test"})

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P7", "name": "引文逐条核过", "kind": "quote_verified_rows", "min": 1},
        {"id": "P8", "name": "形式化", "kind": "proof_experiment_rows", "min": 1},
        {"id": "P9", "name": "审校", "kind": "reviewed_documents", "min": 1},
    ], st=st)
    rep = _gate(st, report)
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    assert all(r["ok"] for r in rep.readings["acceptance"]["rows"]), rep.readings["acceptance"]


def test_the_acceptance_cell_only_excuses_the_row_that_is_really_met(tmp_path: pathlib.Path):
    """负控（阈值逐行、不许一票通吃）：只满足 P7/P8 时，缺的 P9 必须被点名。"""
    def seed(s: Store) -> None:
        _t3_experiment(s, "0003", method="formal", evidence_kind="proof")
        with s.tx("statements", actor="test") as tx:
            tx.upsert("statements", {
                "stmt_id": "0000", "origin": "external_lit", "kind": "theorem",
                "statement_full": "设 G 是任意有限群；则 c(G) ≤ 1。",
                "proof_text": "Proof. 见第 3 节（逐字摘录）。",
                "source_lit_id": "0000", "page_range": {"start": 1, "end": 2},
                "quote_verified": True, "quote_reason": "逐字比对通过（第 1 页）",
                "evidence_kind": "cross_check", "status": "active",
                "created_at": TS, "created_by": "test"})

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P7", "name": "引文逐条核过", "kind": "quote_verified_rows", "min": 1},
        {"id": "P8", "name": "形式化", "kind": "proof_experiment_rows", "min": 1},
        {"id": "P9", "name": "审校", "kind": "reviewed_documents", "min": 1},
    ], st=st)
    rep = _gate(st, report)
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    rows = rep.readings["acceptance"]["rows"]
    assert [r["id"] for r in rows if r["ok"]] == ["P7", "P8"], rows
    assert [r["id"] for r in rows if not r["ok"]] == ["P9"], rows


def test_the_reviewed_documents_leg_counts_hs_verdict_not_only_revision_rounds(
        tmp_path: pathlib.Path):
    """判据（`draft/37` §95 的真机读数）：`status=accepted` 而 `review_rounds=0` 必须算"审过"。

    第 9 趟实测：`documents/0000` 是 `status=accepted`、`review_rounds=0`（H 审过并给了裁决，
    而"轮次"只在真的改过稿时才加）。按 `review_rounds >= 1` 判会把它读成"没审过" ——
    判据恒红，于是没人再信它（这比没有判据更坏）。所以这一档要认 H 的裁决本身。
    """
    def seed(s: Store) -> None:
        _paper_with_claim(s, doc_id="0009")
        with s.tx("documents", actor="test") as tx:
            row = dict(tx.rows("documents")[0])
            row["status"] = "accepted"          # H 的裁决
            row["review_rounds"] = 0            # 没有改过稿 ⇒ 轮次是 0
            # 审批必须钉住"审的是哪一版"（`schema.Document.validate` 的结构强制）
            from agentflow import signatures as SIG

            row["content_sha256"] = SIG.content_sha256_of(row)
            tx.upsert("documents", row)

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P9", "name": "我方稿件被审过", "kind": "reviewed_documents", "min": 1},
    ], st=st)
    rep = _gate(st, report)
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    detail = rep.readings["acceptance"]["rows"][0]["detail"]
    assert detail["documents"][0]["status"] == "accepted", detail


def test_the_manuscript_edited_leg_compares_the_draft_with_the_read_only_baseline(
        tmp_path: pathlib.Path):
    """判据（`draft/37` §96）：任务第一句（"改掉正文里的问题"）的机器可判形式。

    第 9 趟真机：三条腿的凭据全齐、收工门七格全过，而主稿一个字节都没改 ——
    "引文核过、形式化验过"与"把正文里的问题改掉"是三件事，前两件当时有判据、第三件没有。

    三条读数一起钉：主稿 = 基线 ⇒ `fail`；主稿 ≠ 基线 ⇒ `pass`；
    基线不在盘上 ⇒ `unknown`（比不出"改没改"，不许算成"没改"）。
    """
    (tmp_path / "source").mkdir(parents=True, exist_ok=True)
    (tmp_path / "source" / "main.tex").write_text("\\date{2026-01-01}\nbody\n", encoding="utf-8")

    def seed(s: Store) -> None:
        # 这一格测的不是 substance：给它一点实质产出，免得两格一起红
        _t3_experiment(s)
        _paper_with_claim(s)

    st = _project(tmp_path, seed=seed)           # out/paper/main.tex 与基线逐字相同
    report = _write_report(tmp_path)
    rows = [{"id": "P2", "name": "正文实质改动", "kind": "manuscript_edited", "min": 1}]

    def _acc_finding(rep) -> str:
        hits = [f.detail for f in rep.blockers if f.check == "acceptance"]
        assert len(hits) == 1, [f.code for f in rep.blockers]
        return hits[0]

    _acceptance_checks(tmp_path, rows, st=st)
    same = _gate(st, report)
    assert same.status["acceptance"] == "fail", same.to_dict()
    assert "P2" in _acc_finding(same), _acc_finding(same)
    assert same.readings["acceptance"]["rows"][0]["detail"]["edited"] is False, \
        same.readings["acceptance"]

    (tmp_path / "out" / "paper" / "main.tex").write_text(
        "\\date{2026-01-01}\nbody 改过了\n", encoding="utf-8")
    _acceptance_checks(tmp_path, rows, st=st)    # 改主稿会让锚漂 ⇒ 重封（这一格测的不是锚）
    changed = _gate(st, report)
    assert changed.status["acceptance"] == "pass", changed.to_dict()
    assert changed.readings["acceptance"]["rows"][0]["detail"]["edited"] is True, \
        changed.readings["acceptance"]

    (tmp_path / "source" / "main.tex").unlink()
    missing = _gate(st, report)
    assert missing.status["acceptance"] == "unknown", missing.to_dict()
    assert [f.code for f in missing.findings
            if f.check == "acceptance"] == ["acceptance_leg_unreadable"], missing.to_dict()


def test_the_per_citation_leg_counts_against_the_number_of_bibitems(tmp_path: pathlib.Path):
    """判据（`draft/37` §103）：引文那一档要"每条 `\\bibitem` 一条记录"，阈值由主稿自己定。

    第 12 趟钻过去的口子：那一档当时只要求"≥1 条带 `quote_verified` 的行"，
    于是做一条就算（它落了一条 `quote_verified=false` 就过了），而任务原文要的是"逐条"。
    这一档现在按主稿里 `\\bibitem` 的条数当阈值（调用方不写 `min` 时用它自己算的那个）。
    """
    def seed(s: Store) -> None:
        _t3_experiment(s)
        _paper_with_claim(s)

    ws = tmp_path / "ws-bib"
    ws.mkdir()
    st = _project(ws, seed=seed)
    report = _write_report(ws)
    (ws / "out" / "paper" / "main.tex").write_text(
        "\\documentclass{article}\n" + "".join(f"\\bibitem{{K{i}}}\nX\n" for i in range(3)),
        encoding="utf-8")
    (ws / "out" / "paper" / "ACCEPTANCE-CHECKS.json").write_text(
        json.dumps({"checks": [{"id": "P7", "name": "引文逐条核过",
                                "kind": "citation_records_vs_bibitems"}]}, ensure_ascii=False),
        encoding="utf-8")
    _seal(ws, st)

    empty = _gate(st, report)
    row = empty.readings["acceptance"]["rows"][0]
    assert empty.status["acceptance"] == "fail" and row["min"] == 3, row

    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {
            "stmt_id": "0000", "origin": "own_result", "kind": "claim",
            "statement_full": "一句被核过的断言。", "proof_text": "证明：略。",
            "doc_id": "0000", "quote_verified": False,
            "quote_reason": "与原文不一致（英文转述 vs 中文原文）",
            "evidence_kind": "cross_check", "status": "active",
            "created_at": TS, "created_by": "test"})
    one = _gate(st, report)
    assert one.status["acceptance"] == "fail", one.to_dict()   # 3 条 bibitem、只有 1 条记录
    assert one.readings["acceptance"]["rows"][0]["got"] == 1, one.readings["acceptance"]

    for i in (1, 2):
        with st.tx("statements", actor="test") as tx:
            tx.upsert("statements", {
                "stmt_id": f"{i:04d}", "origin": "own_result", "kind": "claim",
                "statement_full": f"第 {i} 条。", "proof_text": "证明：略。",
                "doc_id": "0000", "quote_reason": "原文不在盘上 ⇒ 未查",
                "evidence_kind": "cross_check", "status": "active",
                "created_at": TS, "created_by": "test"})
    full = _gate(st, report)
    assert full.status["acceptance"] == "pass", full.to_dict()   # 3 条记录 ≥ 3 条 bibitem


def test_the_retrieval_leg_requires_a_search_that_actually_ran(
        tmp_path: pathlib.Path, monkeypatch):
    """判据（`draft/37` §105）：「盘外引文先检索」这一档要的是"真的查过"。

    用户一句话点破了此前口径的漏洞："盘上没有就 false？A 不会去查吗"。
    实测（离线探针）：`A.search_literature("An overview of periodic elliptic operators")`
    一次就登记了 9 行文献、含 Kuchment 那篇（DOI `10.1090/bull/1528`），
    而 A 的工具面里还有 `search.download` —— 所以"原文不在工作区"只是"还没去取"。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P7b", "name": "盘外引文先检索", "kind": "retrieval_attempts", "min": 1},
    ], st=st)
    none = _gate(st, report)
    assert none.status["acceptance"] == "fail", none.to_dict()
    assert none.readings["acceptance"]["rows"][0]["got"] == 0, none.readings["acceptance"]

    # 用替身喂一行"查过的检索请求"：这一档判的是读法（真跑过的检索请求数），
    # 不必为它造一行过 schema 的完整行（那会把判据变成 schema 的复制品）。
    real_rows = st.rows
    monkeypatch.setattr(st, "rows", lambda table: (
        [{"request_id": "r-0001", "topic": "An overview of periodic operators",
          "done": True, "outcome": "ok"}] if table == "search_requests" else real_rows(table)))
    some = _gate(st, report)
    assert some.status["acceptance"] == "pass", some.to_dict()
    detail = some.readings["acceptance"]["rows"][0]["detail"]
    assert detail["done"] == 1 and "overview" in detail["topics"][0], detail


def test_the_research_kinds_count_their_own_tables(tmp_path: pathlib.Path, monkeypatch):
    """判据（`draft/38` 的 T2）：研究类那四档各数自己那张表（不是互相替代）。

    从零做一轮研究要看的四件事各有落点：立起问题（`research_questions`）、
    检索取回（`search_requests`）、算一遍（`experiments` 的 numeric 行）、
    分析报告与攻坚计划（D 与 F 的交付物）。四档要是混着数，一门绿就会掩盖另一门空。
    """
    st, report = _good(tmp_path)
    fake = {
        "research_questions": [{"question_id": "q-0001", "status": "open"}],
        "analysis_reports": [{"report_id": "ar-0001", "status": "done"}],
        "attack_plans": [{"plan_id": "ap-0001", "status": "active"}],
    }
    real_rows = st.rows

    def rows(table):
        return fake[table] if table in fake else real_rows(table)

    monkeypatch.setattr(st, "rows", rows)
    _acceptance_checks(tmp_path, [
        {"id": "R1", "name": "立起研究问题", "kind": "research_question_rows", "min": 1},
        {"id": "R5", "name": "分析报告", "kind": "analysis_report_rows", "min": 1},
        {"id": "R6", "name": "攻坚计划", "kind": "attack_plan_rows", "min": 1},
        {"id": "R3", "name": "数值实验", "kind": "numeric_experiment_rows", "min": 1},
    ], st=st)
    rep = _gate(st, report)
    rows_read = rep.readings["acceptance"]["rows"]
    got = {r["id"]: (r["got"], r["ok"]) for r in rows_read}
    assert got["R1"] == (1, True) and got["R5"] == (1, True) and got["R6"] == (1, True), got
    # 夹具里的那条 T3 实验是 formal ⇒ numeric 那一档必须是 0（各数各的表）
    assert got["R3"] == (0, False), got
    assert rep.status["acceptance"] == "fail", rep.to_dict()


def test_supported_claims_needs_an_experiment_that_actually_supports(tmp_path: pathlib.Path):
    """判据（`draft/37` §126）：手稿里有多少条断言「真被实验支持」（`result=supports`）。

    为什么与"断言不许夸大"是一对：第 4 趟真机为了满足那一档，把「正面断言也标成」
    `is_negative`（「K4 每条边恰在两个三角形里」被标成「没得出结论」）—— 那一档过了，
    而稿子里一条有实验支持的断言都没有。这一档逼的是"本轮真的跑出了结论"。
    """
    from agentflow.tools.doc_tools import build_document

    st, _report = _good(tmp_path)                      # 夹具里那条 T3 实验 result=supports
    got, detail = CL._leg_reading(st, "supported_claims", tmp_path)
    assert got == 1, detail                             # 夹具那份稿子引的正是它
    assert detail["experiments_with_result_supports"] == ["0001"], detail

    # 把那条实验改成 inconclusive ⇒ 同一条断言不再算"被支持"
    exp = dict(st.rows("experiments")[0])
    exp["result"] = "inconclusive"
    exp["negation_kind"] = "no_local_evidence"
    exp["evidence_kind"] = "heuristic"
    with st.tx("experiments", actor="test", note="supported_claims probe") as tx:
        tx.upsert("experiments", exp, note="supported_claims probe")
    got2, detail2 = CL._leg_reading(st, "supported_claims", tmp_path)
    assert got2 == 0, detail2
    assert detail2["experiments_with_result_supports"] == [], detail2

    # 再换回来 ⇒ 又算一条；另写一份引它的稿件 ⇒ 两条
    exp["result"] = "supports"
    exp["negation_kind"] = "not_proved"
    exp["evidence_kind"] = "cross_check"
    with st.tx("experiments", actor="test", note="supported_claims probe") as tx:
        tx.upsert("experiments", exp, note="supported_claims probe")
    build_document(store=st, kind="paper", title="有实验支持的稿",
                   claims=[{"claim_id": "c1", "section": "§1", "text": "数值支持该断言",
                            "evidence_kind": "cross_check",
                            "disclaimer": "数值交叉验证，不构成证明",
                            "citations": ["exp:0001"]}],
                   workspace_root=str(tmp_path), actor="test")
    got3, detail3 = CL._leg_reading(st, "supported_claims", tmp_path)
    assert got3 == 2, detail3                           # 夹具那份 + 新写这份


def test_a_claim_may_not_outstate_the_experiment_it_cites(tmp_path: pathlib.Path):
    """判据（`draft/37` §122）：断言与它所引实验的 `result` 必须一致。

    真机读数（T2 第 3 趟）：稿子写着「Heawood 图围长 6」，而它引的那条实验行 stdout 逐字是
    `"girth": 4` 且 `result=inconclusive` —— 三条断言全是这种形态，门却全绿。

    三态都钉住：① 引 `supports` 的实验 ⇒ 这份稿子算「有据」；② 引 `inconclusive` 的实验、
    但断言本身标成「没得出结论」（`is_negative` + `negation_kind`）⇒ 也算有据（那是诚实的形态）；
    ③ 引 `inconclusive` 却写成正面结论 ⇒ 这份稿子「不算」，读数里点名是哪条断言、哪个实验、什么 result。
    """
    st, report = _good(tmp_path)                      # 夹具里有一条 supports 的 T3 实验 exp:0001
    _acceptance_checks(tmp_path, [
        {"id": "R7", "name": "断言与证据一致", "kind": "claims_supported_by_their_evidence", "min": 1},
    ], st=st)

    exp = st.rows("experiments")[0]
    assert exp["result"] == "supports", exp          # 前提：夹具那条实验是支持的
    got, detail = CL._leg_reading(st, "claims_supported_by_their_evidence", tmp_path)
    assert got == 1, detail                          # 夹具那份稿子引的正是它 ⇒ 有据

    # ② 换一条 inconclusive 的实验 + 一条标成「没得出结论」的断言 ⇒ 仍然有据
    incon = S.Experiment(experiment_id="0002", claim_key="rmk", claim="Heawood 图的逐边圈数核验",
                         method="numeric", evidence_kind="heuristic", result="inconclusive",
                         negation_kind="no_local_evidence", code_path="scripts/heawood_check.py",
                         code_hash="deadbeefdeadbeef", exit_code=0, created_at=TS)
    incon.validate()
    with st.tx("experiments", actor="test", note="overstate probe") as tx:
        tx.upsert("experiments", incon.to_dict(), note="overstate probe")
    sync_counters(st)
    lit = st.rows("documents")
    assert lit, "夹具里应当有稿件"
    with st.tx("documents", actor="test", note="overstate probe") as tx:
        row = dict(lit[0])
        row["claims"] = [{"claim_id": "c9", "section": "§1", "text": "没得出结论：搜索超时",
                          "citations": ["exp:0002"], "evidence_kind": "heuristic",
                          "is_negative": True, "negation_kind": "no_local_evidence"}]
        tx.upsert("documents", row, note="overstate probe")
    got2, detail2 = CL._leg_reading(st, "claims_supported_by_their_evidence", tmp_path)
    assert got2 == 1, detail2                        # 诚实标注 ⇒ 仍然算有据

    # ③ 同一份稿子改成正面语气（去掉 is_negative）⇒ 掉出「有据」
    with st.tx("documents", actor="test", note="overstate probe") as tx:
        row = dict(lit[0])
        row["claims"] = [{"claim_id": "c9", "section": "§1", "text": "搜索表明不存在这样的图",
                          "citations": ["exp:0002"], "evidence_kind": "heuristic"}]
        tx.upsert("documents", row, note="overstate probe")
    got3, detail3 = CL._leg_reading(st, "claims_supported_by_their_evidence", tmp_path)
    assert got3 == 0, detail3
    bad = detail3["documents_with_overstated_claims"]
    assert "0001" in bad and bad["0001"][0]["experiment"] == "exp:0002", bad
    assert bad["0001"][0]["result"] == "inconclusive", bad

    rep = _gate(st, report)
    row7 = next(r for r in rep.readings["acceptance"]["rows"] if r["id"] == "R7")
    assert row7["got"] == 0 and row7["ok"] is False, row7
    assert rep.status["acceptance"] == "fail", rep.to_dict()


def test_the_workspace_relative_resolution_rule_is_pinned(tmp_path: pathlib.Path, monkeypatch):
    """直接判 `closing.resolve_under_workspace`（工具层的「相对谁解析」那条规则）。

    为什么单列（`tools/coverage_zero_test.py` 的等级 2 判据 + 它的来历）：这条规则是
    `draft/37` §96 那次真机读数的修法 —— 主控报「报告不在盘上」「锚文件读不到」，
    而两个文件都在盘上，病因是 `Path(given)` 按进程当前目录解析、工具的契约却是
    「相对工作区」。三个口径：① 相对 → 按 `store.root` 解析成绝对；② 绝对 → 原样放过
    （调用方给的是绝对路径就不再改它）；③ 空串/纯空白 → 空串（「没给」不许被解析成
    工作区根，那会让「没查成」看起来像「查了、目录就在那儿」）。
    """
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    st = Store(ws)
    st.init()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)          # 进程 cwd 故意不是工作区

    assert CL.resolve_under_workspace(st, "out/review/REPORT.md") == \
        str((ws / "out" / "review" / "REPORT.md").resolve())
    ab = str(elsewhere / "abs.md")
    assert CL.resolve_under_workspace(st, ab) == ab
    assert CL.resolve_under_workspace(st, "") == ""
    assert CL.resolve_under_workspace(st, "   ") == ""


def test_the_manuscript_must_cite_the_literature_it_retrieved(tmp_path: pathlib.Path, monkeypatch):
    """判据（`draft/37` §120）：手稿引用了多少「文献来源」（`lit:` / `rel:` 代号）。

    为什么单列这一档（T2 第 2 趟真机）：那一趟 A 取回 35 条文献、B 整理出 32 条关系，
    而手稿的三条断言「全部只引 `exp:`」 —— 一条文献都没引，门却全绿（没有一行问过它）。
    研究手稿的第一条要求就是"知道别人做过什么"。

    口径逐条钉住：只算 `lit:` / `rel:`（`exp:` 是自家实验）；`lit:0003#p.4` 按同一篇算一次；
    多份稿件取并集去重；读数里同时给出"库里有几条可引"（让"引了 0 条"与"库里本来就没有"分得开）。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "R6", "name": "手稿引用文献", "kind": "document_literature_citations", "min": 2},
    ], st=st)

    # 先往库里放一条可引的文献（三态纪律：读数要能区分"引了 0 条"与"库里本来没有"）
    lit = S.Literature(lit_id="0000", title="一篇外部论文", type="J",
                       summary="外部文献的一句话摘要", path="library/0000/x.pdf")
    lit.validate()
    with st.tx("literature", actor="test", note="lit-cite probe") as tx:
        tx.upsert("literature", lit.to_dict(), note="lit-cite probe")

    # 夹具里那份稿件（`_good` 造的 documents 行）先看基线读数：它只引 `exp:` ⇒ 0
    got, detail = CL._leg_reading(st, "document_literature_citations", tmp_path)
    assert got == 0 and detail["available"]["literature"] == 1, detail

    # 再放一行稿件：claims 引同一篇文献的两种写法 + 一条自家实验。
    # 走「真实写入口」（`doc.build_document`）而不是手拼一行：手拼那一路会绕开
    # `content_sha256`/`citations` 存在性之类的结构判据（实测被 `schema` 与
    # `check_citations` 当场拒），而"这一档够得着"必须由真实写入路径来证明。
    from agentflow.tools.doc_tools import build_document

    build_document(
        store=st, kind="paper", title="引用文献的稿",
        claims=[{"claim_id": "c1", "section": "Related", "text": "甲（引自文献）",
                 "evidence_kind": "heuristic",
                 "citations": ["lit:0000", "lit:0000#p.4", "exp:0001"]}],
        workspace_root=str(tmp_path), actor="test")
    got2, detail2 = CL._leg_reading(st, "document_literature_citations", tmp_path)
    assert detail2["lit_ids"] == ["lit:0000"], detail2       # 两种写法算一篇
    assert got2 == got + 1, (got, got2, detail2)

    # `rel:` 那一半单独判（`documents` 行里的 claim 引到关系代号）：这一档只解析
    # 代号、不核存在性（存在性由 `build_document` 的 `check_citations` 管），
    # 所以这里用一份替身 reads 把口径钉住，而不必先造一条完整的 relations 行。
    real_docs = st.rows("documents")

    def fake_rows(table):
        if table != "documents":
            return []
        return [*real_docs, {"doc_id": "0009", "claims": [
            {"claim_id": "c9", "citations": ["rel:0007", "rel:0007", "lit:0000"]}]}]

    monkeypatch.setattr(st, "rows", fake_rows)
    got3, detail3 = CL._leg_reading(st, "document_literature_citations", tmp_path)
    assert detail3["rel_ids"] == ["rel:0007"], detail3
    assert got3 == got2 + 1, (got2, got3, detail3)           # 多了一条关系、文献不重算
    monkeypatch.undo()

    rep = _gate(st, report)
    row = next(r for r in rep.readings["acceptance"]["rows"] if r["id"] == "R6")
    assert row["got"] == got2 and row["ok"] is (got2 >= 2), row


def test_a_project_without_a_paper_package_has_no_anchor_to_check(tmp_path: pathlib.Path):
    """判据（`draft/37` §115 + §117）：没有论文包的项目里，锚这一格是「不适用」，不是「没查成」。

    为什么必须单列（T2 第 1 趟的真机读数）：从零研究的工作区里没有论文包，
    而 `_check_anchor` 只会报 `unknown`（锚文件读不到）—— `can_close` 要求七格全 pass
    ⇒ 那类测试永远关不上门，而它们本来就不该有论文包。

    §117 把"论文包在不在"的判据从「`out/paper/` 目录在不在」改成「盘上有没有论文包的实物」：
    人给的验收表按 `ACCEPTANCE_CHECKS_NAME` 的定义就住在 `out/paper/` 里，于是
    "目录在"是个恒真信号（本轮预检实测：空白 T2 工作区 `anchor=unknown`、门永远关不上）。
    反面那一半照旧守住：「有正文」而没有锚 ⇒ 仍然是 `unknown`（那是真出了问题，不许被吞掉）。
    """
    ws = tmp_path / "ws-no-paper"
    (ws / "data").mkdir(parents=True)
    st = Store(ws)
    st.init()
    rep = CL.check_closing(st, project_dir=".", report_path="")
    assert rep.status["anchor"] == "pass", rep.to_dict()
    assert rep.readings["anchor"]["verdict"] == "not_applicable", rep.readings["anchor"]

    # ① 只有验收表（人给的记账）⇒ 还不是论文包 ⇒ 仍然「不适用」
    (ws / "out" / "paper").mkdir(parents=True)
    (ws / "out" / "paper" / "ACCEPTANCE.md").write_text("验收表\n", encoding="utf-8")
    rep2 = CL.check_closing(st, project_dir=".", report_path="")
    assert rep2.status["anchor"] == "pass", rep2.to_dict()
    assert rep2.readings["anchor"]["verdict"] == "not_applicable", rep2.readings["anchor"]

    # ② 有正文、没有锚 ⇒ 真有问题 ⇒ 回到那条可操作的 `unknown`
    (ws / "out" / "paper" / "main.tex").write_text("\\documentclass{article}\n",
                                                   encoding="utf-8")
    rep3 = CL.check_closing(st, project_dir=".", report_path="")
    assert rep3.status["anchor"] == "unknown", rep3.to_dict()
    assert [f.code for f in rep3.findings if f.check == "anchor"] == ["anchor_unknown"]


def test_the_acceptance_cell_separates_no_rows_from_not_checked(tmp_path: pathlib.Path):
    """三态（这一格最容易做错的地方）：没有这一栏 ⇒ `pass`；读不懂 ⇒ `unknown`。

    "这个项目没有机器可判的验收行"与"有、但我没查成"必须分得开 ——
    把后者读成 `pass` 就是本项目最忌的形态（把"没查"折成"没问题"）。
    """
    st, report = _good(tmp_path)
    rep = _gate(st, report)
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    assert "没有" in rep.readings["acceptance"]["note"], rep.readings["acceptance"]

    (tmp_path / "out" / "paper" / "ACCEPTANCE-CHECKS.json").write_text("{坏 JSON", encoding="utf-8")
    bad = _gate(st, report)
    assert bad.status["acceptance"] == "unknown", bad.to_dict()
    assert [f.code for f in bad.findings if f.check == "acceptance"] == ["acceptance_unreadable"]

    _acceptance_checks(tmp_path, [{"id": "P7", "kind": "no_such_leg_kind", "min": 1}])
    unknown = _gate(st, report)
    assert unknown.status["acceptance"] == "unknown", unknown.to_dict()
    assert [f.code for f in unknown.findings
            if f.check == "acceptance"] == ["acceptance_unknown_kind"]


def test_the_anchor_check_goes_red_alone(tmp_path: pathlib.Path):
    """负控①（锚）：封好之后改一次正文 ⇒ 锚 `drifted`，其余各条仍然绿。"""
    st, report = _good(tmp_path)
    (tmp_path / "out" / "paper" / "main.tex").write_text("改过了\n", encoding="utf-8")
    rep = _gate(st, report)
    assert rep.status["anchor"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["anchor_drifted"], rep.to_dict()
    assert {k: v for k, v in rep.status.items() if k != "anchor"} == {
        name: "pass" for name in CL.DEFAULT_CHECKS if name != "anchor"}
    assert CL.tri_state_exit_code(rep) == 1


def test_the_contradiction_check_goes_red_alone(tmp_path: pathlib.Path):
    """负控②（未裁决矛盾）：挂一条 disputed 依赖 ⇒ 只这一条红。"""
    st, report = _good(tmp_path)
    row = S.Dependency(dep_id="0001", used_by="doc:0001#c1", kind="theorem",
                       label="有争议的定理", status="disputed",
                       status_reason="两篇文献给出不同常数", created_at=TS)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict())
    sync_counters(st)
    _seal(tmp_path, st)          # 写完台账要重新封锚（否则红的是锚，不是矛盾那一条）
    rep = _gate(st, report)
    assert rep.status["contradictions"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["contradiction_disputed_source"], \
        [f.code for f in rep.blockers]
    assert {k: v for k, v in rep.status.items() if k != "contradictions"} == {
        name: "pass" for name in CL.DEFAULT_CHECKS if name != "contradictions"}


def test_the_load_bearing_check_goes_red_alone(tmp_path: pathlib.Path):
    """负控③（承重结论）：proof 级正文断言没有 T3 背书 ⇒ 只这一条红。"""
    st, report = _good(tmp_path)
    # 把那条 T3 实验换成只有数值支持的一条（同一实验号，形态不再是 T3）
    _numeric_experiment(st, eid="0001")
    _seal(tmp_path, st)          # 台账变了 ⇒ 重新封锚，让红的那一条只剩 load_bearing
    rep = _gate(st, report)
    assert rep.status["load_bearing"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["load_bearing_without_t3"]
    assert rep.readings["load_bearing"]["claims_without_t3"] == 1
    assert {k: v for k, v in rep.status.items() if k != "load_bearing"} == {
        name: "pass" for name in CL.DEFAULT_CHECKS if name != "load_bearing"}


def test_a_downgraded_claim_does_not_fail_the_gate(tmp_path: pathlib.Path):
    """反真空（§10.2 负控②）：已降档的断言不许因为没有 T3 而判失败。

    这一条与上一条是一对：上一条证明"缺 T3 会红"，这一条证明"降档是允许的出路"。
    只有上一条时，门会把"如实降档"与"过度声称"报成同一件事 —— 那是本末倒置。
    """
    st, report = _good(tmp_path)
    _numeric_experiment(st, eid="0001")
    _paper_with_claim(st, evidence_kind="cross_check")
    _seal(tmp_path, st)
    rep = _gate(st, report)
    assert rep.status["load_bearing"] == "pass", rep.to_dict()
    assert rep.readings["load_bearing"]["claims_with_proof"] == 0, rep.readings


def test_the_report_shape_check_goes_red_alone(tmp_path: pathlib.Path):
    """负控④（报告形状）：抽掉一节与分栏标记 ⇒ 只这一条红。"""
    st, _ = _good(tmp_path)
    bad = _write_report(tmp_path, drop_section="七", drop_split=True)
    rep = _gate(st, bad)
    assert rep.status["report_shape"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["report_incomplete"]
    rd = rep.readings["report_shape"]
    assert any("我们做的补救" in m for m in rd["missing_sections"]), rd
    assert rd["missing_split_markers"] == ["我们补的", "原文的"], rd
    assert {k: v for k, v in rep.status.items() if k != "report_shape"} == {
        name: "pass" for name in CL.DEFAULT_CHECKS if name != "report_shape"}


def test_the_user_pending_check_goes_red_alone(tmp_path: pathlib.Path):
    """负控⑤（等用户）：问了一个没被回答的问题 ⇒ 必须停在"等待用户"。

    三段读数（R26 的形态）：问过 1 个 → 答过 0 个 → 待答 1 个 ⇒ 门红；
    用户答完之后（`agentflow answer` 走的就是 `U.answer_question`）⇒ 门绿。
    """
    st, report = _good(tmp_path)
    outcome = U.ask_user(st.root, role="M", question="「审」还是「研」？", timeout_sec=0.0)
    assert not outcome.answered and outcome.problem == "user_no_answer", outcome
    rep = _gate(st, report)
    assert rep.status["user_pending"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["waiting_for_user"]
    assert rep.readings["user_pending"]["asked"] == 1
    assert rep.readings["user_pending"]["answered"] == 0
    assert "等待用户" in rep.blockers[0].detail
    assert {k: v for k, v in rep.status.items() if k != "user_pending"} == {
        name: "pass" for name in CL.DEFAULT_CHECKS if name != "user_pending"}

    # 用户回答之后：三段读数变成 1/1/0，门放行
    assert U.answer_question(st.root, qid=outcome.qid, answer="审") == ""
    rep2 = _gate(st, report)
    assert rep2.status["user_pending"] == "pass", rep2.to_dict()
    assert rep2.readings["user_pending"]["answered"] == 1
    assert rep2.readings["user_pending"]["pending"] == []
    assert rep2.can_close and CL.tri_state_exit_code(rep2) == 0


# ============================================================ 三态：没查成 ≠ 通过

def test_missing_readings_are_unknown_and_unknown_is_not_a_pass(tmp_path: pathlib.Path):
    """反真空（三态）：不给项目根 / 不给报告路径 ⇒ `unknown`，而 `unknown` 不算通过。

    这一条守的是这门最容易退化的形态：把"我没查成"悄悄算成"可以交"。
    """
    st, _report = _good(tmp_path)
    rep = CL.check_closing(st, project_dir="", report_path="")
    assert rep.status["anchor"] == "unknown", rep.to_dict()
    assert rep.status["report_shape"] == "unknown", rep.to_dict()
    assert not rep.can_close, "没查成却报告可交付 —— 这正是这门要防的形态"
    # 三格都要项目根：锚 / 报告形状 / 验收表的机器可判行（加了第七格之后）
    assert rep.unknowns == ["acceptance", "anchor", "report_shape"], rep.unknowns
    assert rep.failed == []
    assert CL.tri_state_exit_code(rep) == 2, "两格没查成 ⇒ 退出码 2（不是 1，也不是 0）"
    codes = sorted(f.code for f in rep.findings)
    assert codes == ["acceptance_not_checked", "anchor_not_checked", "report_path_missing"], codes


def test_a_missing_report_file_is_unknown_not_a_failure(tmp_path: pathlib.Path):
    """报告还没写与"报告写坏了"是两件事：前者 `unknown`，后者 `fail`。"""
    st, _ = _good(tmp_path)
    gone = tmp_path / "out" / "review" / "NOPE.md"
    rep = _gate(st, gone)
    assert rep.status["report_shape"] == "unknown", rep.to_dict()
    assert [f.code for f in rep.findings if f.check == "report_shape"] == ["report_not_written"]
    assert CL.tri_state_exit_code(rep) == 2


def test_the_wrong_directory_gets_an_actionable_message(tmp_path: pathlib.Path):
    """正控 + 可行动性（`draft/37` §44.5 / §45）：传错目录时，错误必须说清该传哪一个。

    `project_dir` 要的是项目根，`renderanchor.check_package` 自己会拼 `out/paper`。
    2026-10-02 那趟真机上，主控照着工具描述（原话"论文包所在目录"）传了 `out/paper`，
    结果工具去找 `out/paper/out/paper/RENDER-ANCHOR.json`，锚那一格变成 `unknown`，
    白花一步 —— 而那句错误当时只说"读不到 <双拼路径>"，没有一个字提示路径多了一层。

    所以这条判据守两件事：
    1. 传项目根 ⇒ `pass`（正确姿势能过）；
    2. 传论文包目录 ⇒ `unknown`（不改判据口径，仍然不许当"一致"），
       但 finding 里必须点名期望的路径形状与"改传项目根"这个动作。
    """
    st, report = _good(tmp_path)
    right = _gate(st, report, project_dir=tmp_path)
    assert right.status["anchor"] == "pass", right.to_dict()

    wrong = _gate(st, report, project_dir=tmp_path / "out" / "paper")
    assert wrong.status["anchor"] == "unknown", wrong.to_dict()
    msg = next(f.detail for f in wrong.findings if f.code == "anchor_unknown")
    # 消息里点出了"被拼了两次的那一段"（平台分隔符），以及该改传什么。
    doubled = str(pathlib.Path("out") / "paper" / "out" / "paper")
    assert doubled in msg, msg
    assert "项目根" in msg and "out/paper" in msg, msg


def test_the_substance_check_goes_red_alone(tmp_path: pathlib.Path):
    """负控⑥（实质产出，`draft/37` §86）：台账全空 ⇒ 只有这一条红。

    这一条挡的正是 T1 那一趟的形态：退出码 0、报告九节齐全、锚一致、没有矛盾、
    没有待答问题 —— 而 `documents`/`statements`/`relations`/`experiments`/
    `review_findings` 全是 0，报告写着"可交付"。
    """
    report = _write_report(tmp_path)
    st = _project(tmp_path)          # 不写任何台账行（seed 不给）
    rep = _gate(st, report)
    assert rep.status["substance"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["no_substantive_output"], rep.to_dict()
    assert "实质产出" in rep.findings[0].detail, rep.findings[0].detail
    # 其余各条不被这一条带红（除了锚：没有台账就没有渲染锚 ⇒ 那是另一条自己的红）
    assert rep.status["contradictions"] == "pass", rep.to_dict()
    assert rep.status["report_shape"] == "pass", rep.to_dict()


# ============================================================ 研究链覆盖面（§137）

#: 研究链四环节各一行的"全覆盖表"（`min=0`：`0` 也是读数，写清为什么是 0 就合规）。
_FULL_COVER: list[dict] = [
    {"id": "R1", "name": "立题与检索", "kind": "research_question_rows", "min": 0,
     "note": "本轮没立新问题：接着上一轮的问题做"},
    {"id": "R2", "name": "算并留下界", "kind": "search_frontier_rows", "min": 0,
     "note": "本轮一条实验都没记下界（脚本没报 bound）"},
    {"id": "R3", "name": "想", "kind": "conjecture_rows", "min": 0,
     "note": "读数不足以提出可检验的猜想"},
    {"id": "R4", "name": "交", "kind": "document_literature_citations", "min": 0,
     "note": "手稿还没引文献"},
]


def _as_research(st: Store, monkeypatch) -> None:
    """把工作区伪装成"研究型项目"（`research_questions` 有一行）。"""
    real_rows = st.rows
    monkeypatch.setattr(st, "rows", lambda table: (
        [{"question_id": "q-0001", "question": "为什么？", "status": "open"}]
        if table == "research_questions" else real_rows(table)))


def test_a_research_project_must_leave_an_acceptance_checks_file(
        tmp_path: pathlib.Path, monkeypatch):
    """负控（`draft/37` §137）：研究型项目没有那份机器可判的验收表 ⇒ 这一格红。

    改前这里是 `pass` + 一句"这个项目没有 `ACCEPTANCE-CHECKS.json`" ——
    于是"没写验收表"与"写了且全过"在收工门上长得一模一样（三态被折平的那种形态）。
    """
    st, report = _good(tmp_path)
    _as_research(st, monkeypatch)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "fail", rep.to_dict()
    codes = [f.code for f in rep.blockers]
    assert "acceptance_missing_for_research" in codes, rep.to_dict()
    chain = rep.readings["acceptance"]["research_chain"]
    assert chain["researched"] is True and len(chain["missing"]) == 4, chain


def test_a_thin_acceptance_table_is_named_by_the_missing_stage(
        tmp_path: pathlib.Path, monkeypatch):
    """负控（这一条判据的正面用例）：只写"最容易满足的那几行" ⇒ 点名缺哪个环节。

    T2 四趟的验收表就是这个形态：立题、检索、数值、报告都有行，而猜想 / 计划推进 /
    文献进稿 / 留下界一行都没有 —— 七格全绿、`can_close=true`，而研究链一步没走。
    """
    st, report = _good(tmp_path)
    _as_research(st, monkeypatch)
    _acceptance_checks(tmp_path, [
        {"id": "R1", "name": "立起研究问题", "kind": "research_question_rows", "min": 0},
        {"id": "R2", "name": "检索过", "kind": "retrieval_attempts", "min": 0},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "fail", rep.to_dict()
    chain = rep.readings["acceptance"]["research_chain"]
    assert chain["groups"]["立题与检索"], chain
    assert len(chain["missing"]) == 3, chain
    detail = "；".join(f.detail for f in rep.blockers)
    assert "研究链覆盖面" in detail and "想（猜想或判决性证据）" in detail, detail


def test_a_full_coverage_table_still_judges_each_row_on_its_own_reading(
        tmp_path: pathlib.Path, monkeypatch):
    """三态：四环节各一行、但读数都是 0 ⇒ 覆盖面满足了，红的必须是那些行。

    这一条把两件事分开（这正是本判据存在的意义）：
    - `research_chain.missing == []` ⇒ "四个环节都看过"这件事确实做到了；
    - `acceptance == fail` ⇒ 那四行的读数一个都没成立（0 条 < 该档阈值）。
    两者都如实报出来：只报"红"会让 M 不知道是"表薄"还是"活没干"。
    """
    st, report = _good(tmp_path)
    _as_research(st, monkeypatch)
    _acceptance_checks(tmp_path, list(_FULL_COVER), st=st)
    rep = _gate(st, report)

    chain = rep.readings["acceptance"]["research_chain"]
    assert chain["missing"] == [], chain
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    detail = "；".join(f.detail for f in rep.blockers)
    assert "研究链覆盖面" not in detail, detail
    assert "0 条，要求 ≥ 1 条" in detail, detail


def test_a_review_project_is_not_touched_by_the_coverage_rule(tmp_path: pathlib.Path):
    """边界：没有 `research_questions` 行的项目（T1 那种 review）不受这一条约束。

    为什么这条边界必须显式测：T1 的验收表是任务书给的 P1–P11，与"研究链四环节"
    无关 —— 把这条判据撒到它头上会让 T1 那一线当场变红（而它已经通过了 15 趟）。
    改前"没有验收表 ⇒ pass + 一句读数"，那一条对 review 项目保持不变。
    """
    st, report = _good(tmp_path)                     # 不给 research_questions、不给验收表
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "pass", rep.to_dict()
    assert rep.readings["acceptance"]["research_chain"]["researched"] is False, \
        rep.readings["acceptance"]["research_chain"]
    assert "没有" in rep.readings["acceptance"]["note"], rep.readings["acceptance"]


# ============================================================ 交接手稿那一档（§140）

def test_the_manuscript_leg_counts_rows_in_the_ledger_not_files(tmp_path: pathlib.Path):
    """判据（`draft/39` §C1）：`manuscript_rows` 数账本行（一行一份交接）。

    为什么单列这一档：用户点名"传信息就传手稿编号"，而 T2 第 5 趟这一类一次也没用
    （M 写了 26 条 `note`，只活在会话里）。为什么从"数文件"改成"数行"（用户 2026-10-05 裁）：
    旧口径要求文件名能被 `<编号>-<谁>to<谁>.md` 认出来 ⇒ 改个名、少个字段就读成 0，
    读数被文件名的形状绑住。旧格式文件不计入，但在明细里另列一栏（不假装没有）。
    """
    from agentflow import manuscripts as MS

    st, report = _good(tmp_path)
    assert "manuscript_rows" in CL.LEG_CHECK_KINDS, sorted(CL.LEG_CHECK_KINDS)
    _acceptance_checks(tmp_path, [{"id": "M1", "name": "交接手稿", "kind": "manuscript_rows",
                                   "min": 2}], st=st)
    before = _gate(st, report)
    assert before.readings["acceptance"]["rows"][0]["got"] == 0, before.readings["acceptance"]

    MS.write(tmp_path, sender="D", recipient="F", summary="族证据",
             body="实验 0002 的族证据在 out/experiments/0002.log。\n")
    MS.write(tmp_path, sender="M", recipient="ALL", summary="本轮结论", body="见报告。\n")
    # 旧格式文件：读得回来，但不计入这一档（明细里点名）
    (tmp_path / "manuscripts" / "0009-DtoF.md").write_text(
        "# 0009｜D → F\n\n- 标题：旧的\n\n## 正文\n\n旧格式。\n", encoding="utf-8")

    after = _gate(st, report)
    row = after.readings["acceptance"]["rows"][0]
    assert row["got"] == 2, row
    assert after.status["acceptance"] == "pass", after.to_dict()
    assert row["detail"]["complete_rows"] == ["0000", "0001"], row["detail"]
    assert row["detail"]["legacy_md_files"] == ["0009"], row["detail"]
    assert "不计入" in str(row["detail"].get("note") or ""), row["detail"]


def test_a_row_missing_a_required_field_does_not_count(tmp_path: pathlib.Path):
    """负控（三态）：账本里有一行、但缺 `summary`（那一句话要进留言）⇒ 不算数并点名。"""
    import json as _json

    from agentflow import manuscripts as MS

    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [{"id": "M1", "name": "交接手稿", "kind": "manuscript_rows",
                                   "min": 1}], st=st)
    MS.write(tmp_path, sender="D", recipient="F", summary="完整的一份", body="正文。\n")
    # 手工追加一行"缺字段"的（模拟旧账本 / 手改过的账本）
    with MS.handoffs_path(tmp_path).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(_json.dumps({"id": "0001", "sender": "D", "to": "F", "body": "没有一句话"},
                             ensure_ascii=False) + "\n")

    rep = _gate(st, report)
    row = rep.readings["acceptance"]["rows"][0]
    assert row["got"] == 1 and row["ok"] is True, row
    assert row["detail"]["rows"] == 2, row["detail"]
    assert row["detail"]["rows_missing_fields"] == [{"id": "0001", "missing": ["summary"]}], \
        row["detail"]


def test_a_broken_ledger_line_makes_the_reading_low_and_says_so(tmp_path: pathlib.Path):
    """负控（三态）：账本里有读不出来的行 ⇒ 读数偏低且明细里报出来（读不出不等于没有）。"""
    from agentflow import manuscripts as MS

    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [{"id": "M1", "name": "交接手稿", "kind": "manuscript_rows",
                                   "min": 1}], st=st)
    MS.write(tmp_path, sender="D", recipient="F", summary="好的一份", body="正文。\n")
    with MS.handoffs_path(tmp_path).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{这行不是 JSON\n")

    rep = _gate(st, report)
    row = rep.readings["acceptance"]["rows"][0]
    assert row["got"] == 1, row
    assert row["detail"]["unparsable_lines"], row["detail"]
    assert "读不出" in str(row["detail"].get("note") or ""), row["detail"]


# ============================================================ 「算或造」那一档（draft/39 §3.17）

def _statement(store: Store, stmt_id: str, **kw) -> None:
    """往 `statements` 里写一行（`bits` 是五元位记录，见 `draft/39` §3.14）。"""
    row = {"stmt_id": stmt_id, "origin": "own_result", "kind": "theorem",
           "statement_full": "设 G 是 m-正则图；则……", "created_at": TS, "created_by": "test",
           # `quote_verified=None` 时必须写 `quote_reason`（`Statement.validate` 的硬约束：
           # "没查"也要说清为什么还没查）—— 我方自产命题就是"没有外部引文要比对"。
           "quote_reason": "我方自产命题，没有外部引文要比对",
           # `origin=own_result` 必须有 `proof_text`（`Statement.validate`：自产命题没证明就入库
           # 等于把猜测抬成事实）—— 注意：它只是"这一行写了证明文字"这条老约束，
           # 五位里的第 2 位不看它（看 `bits.proof` + 证明过程的凭据）。
           "proof_text": "（逐步论证）"}
    row.update(kw)
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    sync_counters(store)


def test_the_reviewed_proof_leg_counts_our_own_proved_and_reviewed_statements(
        tmp_path: pathlib.Path):
    """`reviewed_proof_rows`：五位派生出「预备定理级 / 正式定理」的我方命题才算。

    非数值方向（分析/拓扑）的项目永远不会有数值实验那一行，`draft/39` §3.17 A5 把
    第二环节从「算并留下界」扩成「算或造」—— 这一档就是"造"那条腿的读数。
    """
    def seed(s: Store) -> None:
        # ① 只有证明过程、没审过 ⇒ 还是"猜想"（第 2 位真、第 3 位空）
        _statement(s, "0000", proof_text="（逐步论证）",
                   bits={"proof": True, "evidence": {"proof_source": "own",
                                                     "proof_process": "（逐步论证）"}})
        # ② 有证明过程 + 审过 ⇒ 预备定理级 ⇒ 算一档
        _statement(s, "0001", bits={"proof": True, "reviewed": True,
                                    "evidence": {"proof_source": "own",
                                                 "proof_process": "（逐步论证）",
                                                 "reviewed_by": {"round": "V-0001",
                                                                 "verdict": "no_defect"}}})
        # ③ 引用命题：凭文献代号进第 2+3 位 ⇒ 等级一样是预备定理级，但不算我方产出
        _statement(s, "0002", origin="external_lit", source_lit_id="0042",
                   quote_verified=True)
        # ④ 只有老字段（`evidence_kind=proof` + `proof_text`，schema 本来就逼着 `own_result`
        #    写证明文字），没有位记录 ⇒ 按五位全空算（自报不算凭据）—— 这正是这个模型
        #    要防的那一类假绿
        _statement(s, "0003", evidence_kind="proof")

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _acceptance_checks(tmp_path, [{"id": "B2", "name": "造判决性证据",
                                   "kind": "reviewed_proof_rows", "min": 1}], st=st)
    rep = _gate(st, report)

    row = rep.readings["acceptance"]["rows"][0]
    assert row["got"] == 1, row
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    assert row["detail"]["counted"][0]["stmt_id"] == "0001", row["detail"]
    assert row["detail"]["cited_skipped"] == 1, row["detail"]
    # 0000（只有证明过程、没审过）与 0003（只有老字段）都停在"猜想"；
    # 0001（我方，算一档）与 0002（引用，`cited_skipped`）都是"预备定理级"。
    assert row["detail"]["grades"] == {"conjecture": 2, "pre_theorem": 2}, row["detail"]


def test_the_reviewed_proof_leg_goes_red_on_self_declared_proofs_alone(tmp_path: pathlib.Path):
    """负控：只有老字段（`evidence_kind=proof` + `proof_text`）而五位全空 ⇒ 这一档 0 条。

    没有这一条，`reviewed_proof_rows` 就退化成"台账里有没有写着 `evidence_kind=proof` 的行" ——
    而历史上正是那些老字段把"数值支持"读成了"已证明"。
    """
    def seed(s: Store) -> None:
        _statement(s, "0000", evidence_kind="proof")
        _statement(s, "0001", evidence_kind="cross_check")

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _acceptance_checks(tmp_path, [{"id": "B2", "name": "造判决性证据",
                                   "kind": "reviewed_proof_rows", "min": 1}], st=st)
    rep = _gate(st, report)

    row = rep.readings["acceptance"]["rows"][0]
    assert row["got"] == 0 and row["ok"] is False, row
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    assert "自报" in row["detail"]["note"], row["detail"]


def test_the_non_numeric_leg_satisfies_the_calculate_or_construct_stage(
        tmp_path: pathlib.Path, monkeypatch):
    """覆盖面：只写 `reviewed_proof_rows` 一行 ⇒ 「算或造」这一环节满足（非数值方向不被卡死）。

    改前那一组的成员只有数值/界三档 ⇒ 分析方向的项目那一格结构性恒空，
    无论做得多好都收不了工 —— 那是拿数值口径去卡一个不该用数值的方向（`draft/39` §3.17）。
    """
    def seed(s: Store) -> None:
        _statement(s, "0000", bits={"proof": True, "reviewed": True,
                                    "evidence": {"proof_source": "own",
                                                 "proof_process": "（逐步论证）",
                                                 "reviewed_by": {"round": "V-0001"}}})

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _as_research(st, monkeypatch)
    _acceptance_checks(tmp_path, [
        {"id": "R1", "name": "立题与检索", "kind": "research_question_rows", "min": 0},
        {"id": "R2", "name": "算或造", "kind": "reviewed_proof_rows", "min": 1},
        {"id": "R3", "name": "想", "kind": "conjecture_rows", "min": 0},
        {"id": "R4", "name": "交", "kind": "document_literature_citations", "min": 0},
    ], st=st)
    rep = _gate(st, report)

    chain = rep.readings["acceptance"]["research_chain"]
    assert chain["groups"]["算或造"] == ["reviewed_proof_rows"], chain
    assert chain["missing"] == [], chain


def test_an_unreadable_leg_leaves_a_reason_in_the_reading_not_a_null(tmp_path: pathlib.Path):
    """判据（`draft/39` §6.25 的 D35）：一档读不出来时，读数里必须带上"为什么"。

    真机读数（T2 第 7 趟 `projects/p6i-research-from-zero`）：验收表 P1 用了
    `manuscript_edited`，而从零工作区没有只读基线 `source/` ⇒ 那一行的读数算不出来
    ⇒ 整格 `unknown`；而这一格当时只 push 了一条 `Finding`，`readings["acceptance"]`
    留在 `None` 上 —— 交付面（报告、离线复算脚本、状态报告）看到的就是一个没有理由的空格。
    三态纪律要的是"没查成"本身可读：哪一行、哪一档、为什么、该换什么。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "正文改动", "kind": "manuscript_edited", "min": 1},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    reading = rep.readings["acceptance"]
    assert isinstance(reading, dict), reading
    assert reading["code"] == "acceptance_leg_unreadable", reading
    assert reading["detail"], reading
    assert "source" in reading["detail"], reading
    assert [f.code for f in rep.findings if f.code.startswith("acceptance")] == \
        ["acceptance_leg_unreadable"], rep.to_dict()


def test_a_self_invented_kind_says_it_takes_the_whole_table_down(tmp_path: pathlib.Path):
    """判据（D35 的另一半）：自造 `kind` 不只废那一行 —— 读数要说清"整张表都没查成"。"""
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "我编的档", "kind": "render_anchor_consistent", "min": 1},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    reading = rep.readings["acceptance"]
    assert reading["code"] == "acceptance_unknown_kind", reading
    assert "整张表" in reading["detail"], reading

