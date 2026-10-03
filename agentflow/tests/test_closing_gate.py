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

