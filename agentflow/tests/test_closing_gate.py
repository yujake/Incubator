# -*- coding: utf-8 -*-
"""收工门（`draft/37` §16 P3）：八格各自能造红，`unknown` 不算通过。

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


#: M 声明的体例（R9 之后体例归 M，门不自带节名清单）。
#:
#: 测试里的"这一趟的 M"声明这些节，写进 `out/review/REPORT-STYLE.json`；
#: 门只核对声明有没有兑现。它与 `closing` 无关 —— 这正是 R9 的判据：
#: 门不再自带一份"报告该有哪几节"（那是 review 线的排版规格）。
STYLE_SECTIONS: tuple[str, ...] = (
    "一、任务与范围", "二、逐条读数", "三、定理与引理清单", "四、形式化覆盖",
    "五、引文核验", "六、体例与表述", "七、我们做的补救", "八、未决问题", "九、诚实边界",
)


def _write_report(root: pathlib.Path, *, drop_section: str = "",
                  drop_attachment: bool = False,
                  declare_style: tuple[str, ...] | None = STYLE_SECTIONS) -> pathlib.Path:
    """按 M 声明的体例写一份报告（可注入两处缺陷：缺一节 / 缺附件三件套）。

    `drop_section` 按声明的节名的首字（如 `"七"`）抽掉一节；
    `declare_style=None` ⇒ 不落体例声明（门就不判体例，只判附件）。
    """
    p = root / "out" / "review" / "REPORT.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    sections = STYLE_SECTIONS if declare_style is None else declare_style
    lines = ["# 审核报告", ""]
    for name in sections:
        num = name.split("、", 1)[0]
        if num == drop_section:
            continue
        lines.append(f"## {name}")
        lines.append(f"{name.split('、', 1)[1]}的读数：逐条见台账。")
        lines.append("")
    if not drop_attachment:
        lines += ["附件：origin=own_result；依据读数见 §四；版本 sha256=deadbeef。", ""]
    p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    style = p.parent / "REPORT-STYLE.json"
    if declare_style is None:
        if style.exists():
            style.unlink()
    else:
        style.write_text(json.dumps({"sections": list(sections)}, ensure_ascii=False),
                         encoding="utf-8", newline="\n")
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


def _numeric_experiment(store: Store, eid: str = "0001", **patch) -> dict:
    """一条只有数值支持的实验行（`cross_check`）：不是 T3。

    这是"承重结论缺 T3"最真实的形态：数值跑出来支持，但没有任何检查器说过话。
    `patch` 用来把这行改成"有界记录的搜索"形态（`claim` / `search_bound` 等），
    D61 的判据要看这些特征。
    """
    base = dict(experiment_id=eid, claim="Theorem 1.5 的数值检查", claim_key="thm:1.5",
                method="numeric", evidence_kind="cross_check", result="supports",
                negation_kind="not_proved", code_path="code/exp.py",
                code_hash="deadbeefdeadbeef", exit_code=0, created_at=TS)
    base.update(patch)
    row = S.Experiment(**base)
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
    """正控：每条都过 ⇒ `machine_pass` 为真、没有 blocker；`can_close` 由 M 判。

    业主 2026-10-09 的两句（逐字）：
    「是否收工不要用机械判据，由 M 制定的目标是否达成为准」＋
    「所有智能体是否能停都是看自己被派的活有没有做完，M 也不例外，只是 M 需要根据用户指令
    给自己设计任务列表」⇒ 八格全过只说明"机器没意见"；能不能停要 M 按它自己列的
    任务列表说一句。所以这一条现在钉两半：
    ① 没有 M 的判据 ⇒ `can_close=false`、退出码 2（"没人判过"，不是"可以交"）；
    ② M 交了判据（任务列表全 done + `goal_met=True`）⇒ `can_close=true`、退出码 0。

    这一条本身不足以证明门有效（一条恒真的判据也能过），所以后面每一条
    都配一条"只把它弄坏"的负控 —— 合起来才是这组判据的全部。
    """
    st, report = _good(tmp_path)
    rep = _gate(st, report)
    assert rep.status == {name: "pass" for name in CL.DEFAULT_CHECKS}, rep.to_dict()
    assert rep.machine_pass and not rep.blockers, rep.to_dict()
    # ① 没人判过 ⇒ 不算能交（三态：unknown 不是 pass）
    assert not rep.can_close, rep.to_dict()
    assert CL.tri_state_exit_code(rep) == 2, rep.to_dict()
    assert "没有提交自己的判据" in rep.summary(), rep.summary()

    # ② M 判了（它按自己列的任务列表说"活做完了"）⇒ 能停
    judged = CL.check_closing(st, project_dir=".", report_path=str(report),
                              goal="把论文包审完并交付修订稿",
                              goal_met=True, basis="P2/P7/P8/P9 全绿",
                              task_list=[{"what": "逐条核引文", "state": "done"},
                                         {"what": "形式化核两条定理", "state": "done"}])
    assert judged.can_close and CL.tri_state_exit_code(judged) == 0, judged.to_dict()
    assert judged.verdict_conflicts == [], judged.to_dict()
    assert "任务列表 2/2 done" in judged.summary(), judged.summary()


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

    # E-05 ③：只差空白不算实质改动（旧口径比 sha ⇒ 一个字节就算改过）
    (tmp_path / "out" / "paper" / "main.tex").write_text(
        "\\date{2026-01-01}\nbody\n\n", encoding="utf-8")
    _acceptance_checks(tmp_path, rows, st=st)
    blank = _gate(st, report)
    assert blank.status["acceptance"] == "fail", blank.to_dict()
    blank_detail = blank.readings["acceptance"]["rows"][0]["detail"]
    assert blank_detail["raw_changed"] is True and blank_detail["substantive"] is False, \
        blank_detail
    assert blank.readings["acceptance"]["rows"][0]["got"] == 0, blank.readings["acceptance"]

    # CC-05：基线不在盘上 ⇒ 该行不适用（不是整格没查成、不是失败）
    (tmp_path / "source" / "main.tex").unlink()
    missing = _gate(st, report)
    assert missing.status["acceptance"] == "pass", missing.to_dict()
    na_row = missing.readings["acceptance"]["rows"][0]
    assert na_row["not_applicable"] is True and na_row["got"] is None, na_row
    assert missing.readings["acceptance"]["rows_not_applicable"] == 1
    assert [f.code for f in missing.findings if f.check == "acceptance"] == [], \
        missing.to_dict()


def test_the_per_citation_leg_counts_against_the_read_only_baseline(
        tmp_path: pathlib.Path):
    """判据（`draft/37` §103 + E-05 ②）：引文那一档的分母取只读基线。

    第 12 趟钻过去的口子：那一档当时只要求"≥1 条带 `quote_verified` 的行"，
    于是做一条就算（它落了一条 `quote_verified=false` 就过了），而任务原文要的是"逐条"。
    现在阈值 = 只读基线 `source/main.tex` 里 `\\bibitem` 的条数 —— 分母不许由
    可改的主稿自己给（旧口径取主稿 ⇒ 删文献就能把门槛一起压低，`draft/43-C` C-05）。

    2026-10-06 的 T1 口径（`draft/39` §6.49 八 第四条）又加了一条：只读基线有
    `\\bibitem`、而台账里 `origin="external_lit"` 的行一条 `quote_verified=True` 都没有
    ⇒ 门自己报「逐字引文一条都没核到」（"哪几条没查到"本身不是交付）。
    所以这份夹具的三条记录里必须留一条真的核到的（`0002`：`quote_verified=True`
    + 逐字理由）：这三行的 `quote_reason` 写的全是文献比对的结论（"与原文不一致" /
    "原文不在盘上 ⇒ 未查"），它们本来就是引文记录 —— 一条核到的都不留，这份夹具就
    不再配叫"引文逐条核过"了。（本夹具按这里的既有写法把三行登记成 `own_result`，
    T1 那条判据只看 `external_lit` ⇒ 它不看这三行；那个口径的正反两面由
    `test_unretrieved_quotes_alone_do_not_satisfy_the_citation_leg` 单列。）
    """
    def seed(s: Store) -> None:
        _t3_experiment(s)
        _paper_with_claim(s)

    ws = tmp_path / "ws-bib"
    ws.mkdir()
    st = _project(ws, seed=seed)
    report = _write_report(ws)
    # 只读基线：3 条 `\bibitem`（分母的真源）
    (ws / "source").mkdir(parents=True, exist_ok=True)
    (ws / "source" / "main.tex").write_text(
        "\\documentclass{article}\n" + "".join(f"\\bibitem{{K{i}}}\nX\n" for i in range(3)),
        encoding="utf-8")
    # 可改的主稿：只有 1 条 —— 旧口径会把它当分母（读成 1 并判过）。
    #
    # 它刻意写成"占位稿"（不带 `\documentclass`）：基线一从盘上拿掉，T3 口径
    # （`draft/39` §6.49 八 第五条）就会把 `out/paper/main.tex` 当成"这一趟从结果写的
    # 论文"来判（参考文献 < 2 条 / 正文没在结果章节引台账）—— 而这一段测的是引文那一档
    # 的分母口径（基线不在 ⇒ 该行 `not_applicable`）。占位稿不触发那一档
    # （`looks_like_article` 为假），而"1 条 `\bibitem`"这个对照读数照样在。
    (ws / "out" / "paper" / "main.tex").write_text(
        "\\bibitem{K0}\nX\n", encoding="utf-8")
    (ws / "out" / "paper" / "ACCEPTANCE-CHECKS.json").write_text(
        json.dumps({"checks": [{"id": "P7", "name": "引文逐条核过",
                                "kind": "citation_records_vs_bibitems"}]}, ensure_ascii=False),
        encoding="utf-8")
    _seal(ws, st)

    empty = _gate(st, report)
    row = empty.readings["acceptance"]["rows"][0]
    assert empty.status["acceptance"] == "fail" and row["min"] == 3, row
    assert row["detail"]["denominator_from"] == "source/main.tex", row["detail"]
    assert row["detail"]["draft_bibitems"] == 1, row["detail"]

    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {
            "stmt_id": "0000", "origin": "own_result", "kind": "claim",
            "statement_full": "一句被核过的断言。", "proof_text": "证明：略。",
            "doc_id": "0000", "quote_verified": False,
            "quote_reason": "与原文不一致（英文转述 vs 中文原文）",
            "evidence_kind": "cross_check", "status": "active",
            "created_at": TS, "created_by": "test"})
    one = _gate(st, report)
    # 3 条 bibitem 的基线，只有 1 条记录 ⇒ 不成立（旧口径会拿主稿的 1 判过）
    assert one.status["acceptance"] == "fail", one.to_dict()
    assert one.readings["acceptance"]["rows"][0]["got"] == 1, one.readings["acceptance"]

    for i in (1, 2):
        row = {
            "stmt_id": f"{i:04d}", "origin": "own_result", "kind": "claim",
            "statement_full": f"第 {i} 条。", "proof_text": "证明：略。",
            "doc_id": "0000", "evidence_kind": "cross_check", "status": "active",
            "created_at": TS, "created_by": "test",
        }
        if i == 2:
            # T1 口径（`draft/39` §6.49 八 第四条）：这一条是核到了的那一条 ——
            # 三条记录要有非空的 `true` 读数，否则这一档在 T1 那条判据下会被整格否掉。
            row["quote_verified"] = True
            row["quote_reason"] = "逐字比对通过（第 1 页）"
        else:
            row["quote_reason"] = "原文不在盘上 ⇒ 未查"
        with st.tx("statements", actor="test") as tx:
            tx.upsert("statements", row)
    full = _gate(st, report)
    assert full.status["acceptance"] == "pass", full.to_dict()   # 3 条记录 ≥ 3 条 bibitem
    assert full.readings["acceptance"]["rows"][0]["detail"]["true"] == 1, \
        full.readings["acceptance"]["rows"][0]["detail"]

    # CC-05：基线不在盘上 ⇒ 该行不适用（不再整格 unknown，也不再读主稿当分母）
    (ws / "source" / "main.tex").unlink()
    gone = _gate(st, report)
    assert gone.status["acceptance"] == "pass", gone.to_dict()
    na_row = gone.readings["acceptance"]["rows"][0]
    assert na_row["not_applicable"] is True, na_row
    assert "source/main.tex" in na_row["reason"].replace("\\", "/"), na_row


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
    codes = [f.code for f in unknown.findings if f.check == "acceptance"]
    # CC-02：词表外 `kind` 只废这一行（`acceptance_unknown_kind`），
    # 整格仍 `unknown`（绝不 `pass`），并附一条汇总 warning。
    assert codes == ["acceptance_unknown_kind", "acceptance_rows_unreadable"], codes
    assert unknown.readings["acceptance"]["rows_unreadable"] == 1, unknown.readings["acceptance"]


def test_the_anchor_check_goes_red_alone(tmp_path: pathlib.Path):
    """负控①（锚）：封好之后改一次正文 ⇒ 锚 `drifted`，其余各条仍然绿。

    按业主 2026-10-09 的口径补后半：这一格红了不阻断 M 停（判据归 M），
    但 M 说"达成"时 `overrode` 必须逐格点名它 —— 判据归 M ≠ 机器读数可以被盖掉。
    """
    st, report = _good(tmp_path)
    (tmp_path / "out" / "paper" / "main.tex").write_text("改过了\n", encoding="utf-8")
    rep = _gate(st, report)
    assert rep.status["anchor"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["anchor_drifted"], rep.to_dict()
    assert {k: v for k, v in rep.status.items() if k != "anchor"} == {
        name: "pass" for name in CL.DEFAULT_CHECKS if name != "anchor"}
    # 没有 M 的判据 ⇒ 不算能交（"没人判过"）；M 判"达成" ⇒ 能停，但那一格被点名
    assert not rep.can_close and CL.tri_state_exit_code(rep) == 2, rep.to_dict()
    judged = CL.check_closing(st, project_dir=str(st.root), report_path=str(report),
                              goal="审完交付", goal_met=True,
                              task_list=[{"what": "审完", "state": "done"}])
    assert judged.can_close and CL.tri_state_exit_code(judged) == 0, judged.to_dict()
    assert [x["check"] for x in judged.overrode] == ["anchor"], judged.overrode


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
    """负控④（报告那一格，已按裁定 9 收窄成读数）：缺附件 ⇒ 逐条进 warning，不再拦门。

    业主 2026-10-09：「T1的5不是已经说过工作内容和交付形式由M决定了吗？不卡机械判据」⇒
    改前这条断言的是 `report_shape == "fail"` 且 `report_incomplete` 进 blockers；
    现在断言的是：那一格仍 `pass`（报告在盘上、读得成）、缺的两件逐条进
    `readings` 与 `findings`（warning 级）、而且没有 blocker。
    """
    st, _ = _good(tmp_path)
    bad = _write_report(tmp_path, drop_attachment=True)
    rep = _gate(st, bad)
    assert rep.status["report_shape"] == "pass", rep.to_dict()
    assert rep.blockers == [], [f.to_dict() for f in rep.blockers]
    rd = rep.readings["report_shape"]
    assert rd["missing_attachment_fields"] == ["origin=own_result", "依据", "sha"], rd
    warns = [f for f in rep.findings if f.code == "attachment_fields_missing"]
    assert warns and warns[0].level == "warning", [f.to_dict() for f in rep.findings]
    # 其余各格照旧（这一格不再把别人带红）
    assert {k: v for k, v in rep.status.items() if k != "report_shape"} == {
        name: "pass" for name in CL.DEFAULT_CHECKS if name != "report_shape"}


def test_a_missing_declared_section_is_a_reading_not_a_blocker(tmp_path: pathlib.Path):
    """负控④′（体例）：M 声明了九节而报告只写了八节 ⇒ 读数点名，不拦门。

    体例本来就是 M 自己声明的（R9），而"你说的和你写的不一致"是一句话，
    不是一条不许收工的理由（业主 2026-10-09 的裁定 9）。
    """
    st, _ = _good(tmp_path)
    bad = _write_report(tmp_path, drop_section="七")
    rep = _gate(st, bad)
    assert rep.status["report_shape"] == "pass", rep.to_dict()
    assert rep.blockers == [], [f.to_dict() for f in rep.blockers]
    rd = rep.readings["report_shape"]
    assert rd["missing_declared_sections"] == ["七、我们做的补救"], rd
    assert rd["missing_attachment_fields"] == [], rd
    warns = [f for f in rep.findings if f.code == "declared_sections_missing"]
    assert warns and warns[0].level == "warning", [f.to_dict() for f in rep.findings]
    assert {k: v for k, v in rep.status.items() if k != "report_shape"} == {
        name: "pass" for name in CL.DEFAULT_CHECKS if name != "report_shape"}


def test_no_declared_style_means_no_format_judgement(tmp_path: pathlib.Path):
    """R9：M 没声明体例 ⇒ 门不判体例（读数 `style_source: "none"`）。

    这不是"通过"，是"这一趟没有体例声明"。附件三件套照判（它不是排版）。
    """
    st, _ = _good(tmp_path)
    report = _write_report(tmp_path, declare_style=None)
    rep = _gate(st, report)
    assert rep.status["report_shape"] == "pass", rep.to_dict()
    rd = rep.readings["report_shape"]
    assert rd["style_source"] == "none" and rd["declared_sections"] == []
    assert rd["attachment_fields"] == ["origin=own_result", "依据", "sha"], rd


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

    # 用户回答之后：三段读数变成 1/1/0，机器那一格放行；
    # 而"能不能停"仍由 M 判（业主 2026-10-09）⇒ 这里把两半分开核。
    assert U.answer_question(st.root, qid=outcome.qid, answer="审") == ""
    rep2 = _gate(st, report)
    assert rep2.status["user_pending"] == "pass", rep2.to_dict()
    assert rep2.readings["user_pending"]["answered"] == 1
    assert rep2.readings["user_pending"]["pending"] == []
    assert rep2.machine_pass and not rep2.can_close, rep2.to_dict()
    assert CL.tri_state_exit_code(rep2) == 2, "没人判过 ⇒ 没查成（不是可以交）"
    judged = CL.check_closing(st, project_dir=str(st.root), report_path=str(report),
                              goal="审完交付", goal_met=True,
                              task_list=[{"what": "审完", "state": "done"}])
    assert judged.can_close and CL.tri_state_exit_code(judged) == 0, judged.to_dict()


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
    # 要项目根的每一格都要在名单里：锚 / 报告形状 / 验收表（第七格）/ 产物台账（第八格）
    assert rep.unknowns == ["acceptance", "anchor", "artifact_ledger", "report_shape"], rep.unknowns
    assert rep.failed == []
    assert CL.tri_state_exit_code(rep) == 2, "没查成 ⇒ 退出码 2（不是 1，也不是 0）"
    codes = sorted(f.code for f in rep.findings)
    assert codes == ["acceptance_not_checked", "anchor_not_checked", "no_project_dir",
                     "report_path_missing"], codes


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

#: 研究链八环节各一行的"全覆盖表"（`min=0`：`0` 也是读数，写清为什么是 0 就合规）。
_FULL_COVER: list[dict] = [
    {"id": "R1", "name": "立题", "kind": "research_question_rows", "min": 0,
     "note": "本轮没立新问题：接着上一轮的问题做"},
    # 「检索（真的取回）」那一环（`draft/39` §6.47 的 D60）：这一档数的是 `outcome=ok` 的
    # 检索条数，缺省阈值 = 研究问题条数 ⇒ 夹具里研究问题 1 行、成功检索 0 条 ⇒ 0 < 1，
    # 这一行特意写成会红的形态（这一组用例要的正是"覆盖面齐了、读数是 0"）。
    {"id": "R2", "name": "检索（真的取回）", "kind": "retrieval_ok_rows", "min": 0,
     "note": "本轮一条检索都没成功取回"},
    {"id": "R3", "name": "算并留下界", "kind": "search_frontier_rows", "min": 0,
     "note": "本轮一条实验都没记下界（脚本没报 bound）"},
    {"id": "R4", "name": "想", "kind": "conjecture_rows", "min": 0,
     "note": "读数不足以提出可检验的猜想"},
    # 「看（关系分析）」那一环节（D52）：要么跑过 C，要么如实标 na 说清为什么不用它。
    {"id": "R5", "name": "看（关系分析）", "kind": "c_analysis_runs", "min": 0,
     "note": "本轮没派 C 的关系分析"},
    # 「攻（攻坚推进）」那一环（D59）：从「交」里分出来的 F 那条腿。
    {"id": "R6", "name": "攻（攻坚推进）", "kind": "plan_progress_rows", "min": 0,
     "note": "本轮没有立过攻坚计划"},
    # 「交（手稿落盘）」那一环（D59）：现在只认"盘上真的有一份交付物"的读数。
    # 夹具里 `documents` 1 行 ⇒ 这一行成立（这一组用例要的不是它红）。
    {"id": "R7", "name": "交（手稿落盘）", "kind": "document_rows", "min": 1,
     "note": "本轮交付了一份稿件"},
    # 「闭（请求闭环）」那一环节（D56）：这一档的缺省判据是
    # 上限 0（队列里没做完的请求应为 0）—— 夹具里一条请求都没有 ⇒ 0 条达标。
    {"id": "R8", "name": "闭（请求闭环）", "kind": "unfinished_request_rows", "min": 0,
     "note": "本轮没有提交过检索/重抽取请求"},
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
    assert chain["researched"] is True and len(chain["missing"]) == 8, chain


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
    assert chain["groups"]["立题"], chain
    assert len(chain["missing"]) == 7, chain
    detail = "；".join(f.detail for f in rep.blockers)
    assert "研究链覆盖面" in detail and "想（猜想或判决性证据）" in detail, detail


def test_a_full_coverage_table_still_judges_each_row_on_its_own_reading(
        tmp_path: pathlib.Path, monkeypatch):
    """三态：六环节各一行、但读数都是 0 ⇒ 覆盖面满足了，红的必须是那些行。

    这一条把两件事分开（这正是本判据存在的意义）：
    - `research_chain.missing == []` ⇒ "六个环节都看过"这件事确实做到了；
    - `acceptance == fail` ⇒ 那几行的读数一个都没成立（0 条 < 该档阈值）。
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

    为什么这条边界必须显式测：T1 的验收表是任务书给的 P1–P11，与"研究链六环节"
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
    assert row["detail"]["authored_rows"] == ["0000", "0001"], row["detail"]
    assert row["detail"]["legacy_md_files"] == ["0009"], row["detail"]
    assert "不计入" in str(row["detail"].get("note") or ""), row["detail"]


def test_framework_derived_template_rows_do_not_count_as_handoffs(tmp_path: pathlib.Path):
    """判据（`draft/39` §6.49 的 D64，用户 2026-10-06 裁）：模板行不算交接。

    真机读数：T1–T5 五趟的账本 92 / 96 / 118 / 62 / 94 行里 100% 是框架派生的模板
    （`note` 写着「框架据动作结果派生」/「框架据派活派生」），`refs` 逐行全空 ——
    用户原话「handoffs 里面没有几条有效信息全在强调纪律」。读数不许再替噪声背书：
    自写的才计入，派生的另列一栏，而且一份自写的都没有时门要自己报。
    """
    from agentflow import manuscripts as MS

    st, report = _good(tmp_path)
    MS.write(tmp_path, sender="E", recipient="M", summary="list_experiments：ok",
             body="从 E 到 M 的模板行。\n",
             note="留痕来源：框架据动作结果派生（动作驱动的一趟没有 final 可填）")
    MS.write(tmp_path, sender="M", recipient="F", summary="派活留痕",
             body="从 M 到 F 的模板行。\n", note="留痕来源：框架据派活派生（模型这一句没填 notify）")
    # ①验收表里没写这一档 ⇒ 门自己报（这是"一份自写的都没有"的兜底读数）
    _acceptance_checks(tmp_path, [{"id": "P1", "name": "有稿件", "kind": "document_rows",
                                   "min": 1}], st=st)
    rep_auto = _gate(st, report)
    auto_detail = "；".join(f.detail for f in rep_auto.blockers if f.check == "acceptance")
    assert "全是框架派生的模板" in auto_detail and "refs" in auto_detail, auto_detail

    # ②写进验收表时由它自己那一行判：0 条 ⇒ 红，明细里派生的另列一栏
    _acceptance_checks(tmp_path, [{"id": "M1", "name": "交接手稿", "kind": "manuscript_rows",
                                   "min": 1}], st=st)
    rep = _gate(st, report)
    row = rep.readings["acceptance"]["rows"][0]
    assert row["got"] == 0 and row["ok"] is False, row
    assert row["detail"]["derived_rows"] == 2, row["detail"]

    # ③一份自写的（带编号）就够把这一档立起来
    MS.write(tmp_path, sender="D", recipient="F", summary="族证据在 exp:0001",
             body="实验 0001 的族证据在 out/experiments/0001.log。\n", refs=["exp:0001"])
    rep2 = _gate(st, report)
    row2 = rep2.readings["acceptance"]["rows"][0]
    assert row2["got"] == 1 and row2["ok"] is True, row2
    assert row2["detail"]["refs_ok"] == ["0002"], row2["detail"]


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

    声明了这一档（`reviewed_proof_rows`）之后，`draft/39` §6.49 八 第二条（D66 造半边）
    也跟着生效：`origin="own_result"` 的行要说清派生于什么（`derived_from` /
    `source_lit_id` 至少一个非空），否则门会报「「造」那一环没有我方派生的命题」——
    而那会把这一条要测的读数（`counted == 1`）盖掉。所以夹具里被计入的那条
    （`0001`）要 `derived_from=["0000"]`：`0000` 是同夹具里已登记的命题号，
    `Statement.validate` 只要求它是合法四位号、去重、不含自身。
    """
    def seed(s: Store) -> None:
        # ① 只有证明过程、没审过 ⇒ 还是"猜想"（第 2 位真、第 3 位空）
        _statement(s, "0000", proof_text="（逐步论证）",
                   bits={"proof": True, "evidence": {"proof_source": "own",
                                                     "proof_process": "（逐步论证）"}})
        # ② 有证明过程 + 审过 ⇒ 预备定理级 ⇒ 算一档；`derived_from` 指回①
        _statement(s, "0001", derived_from=["0000"],
                   bits={"proof": True, "reviewed": True,
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


def test_the_grade_reading_comes_from_bits_from_row(tmp_path: pathlib.Path):
    """R3 读侧（`draft/57` 组 9）：等级只许来自 `bits_from_row` / `derive_grade`。

    判据（AST）：`closing.py` 里读 `bits.get("grade")` 的那个 `bits` 必须由
    `EB.bits_from_row(...)`（或 `derive_grade(...)`）赋值 —— 也就是说盘上那份
    `bits["grade"]` 只当缓存，读侧现算。今天已经如此；这条把它固化成"以后改坏会红"。

    负控（两份，缺一不可）：
    1. 「合成」：把一段"直接读盘上 dict 的 grade"的源码喂给同一个判据 ⇒ 必须报违规
       （这段判据自己也要能被证伪，不能只对真文件恒真）；
    2. 「真文件注入」（另做、见交付说明）：把 `closing.py` 那一行临时换成
       `str((r.get("bits") or {}).get("grade") or "")` ⇒ 本用例红，然后还原。
    """
    import ast
    import inspect

    src = inspect.getsource(CL)

    def _grade_reads(text: str) -> tuple[list[int], list[int]]:
        tree = ast.parse(text)
        ok_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn = node.value.func
                fname = (fn.attr if isinstance(fn, ast.Attribute)
                         else (fn.id if isinstance(fn, ast.Name) else ""))
                if fname in ("bits_from_row", "derive_grade"):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            ok_names.add(t.id)
        good: list[int] = []
        bad: list[int] = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "grade"):
                recv = node.func.value
                if isinstance(recv, ast.Name) and recv.id in ok_names:
                    good.append(node.lineno)
                else:
                    bad.append(node.lineno)
            if (isinstance(node, ast.Subscript)
                    and isinstance(getattr(node, "slice", None), ast.Constant)
                    and node.slice.value == "grade"):
                bad.append(node.lineno)
        return good, bad

    good, bad = _grade_reads(src)
    assert good, "没找到任何来自 bits_from_row 的 grade 读取 —— 判据自己接错了（不是通过）"
    assert bad == [], (
        f"closing.py 里有 {len(bad)} 处 grade 读取不是来自 bits_from_row/derive_grade："
        f"第 {bad} 行 —— 盘上存的等级只当缓存，读侧必须现算"
    )

    # 负控（合成）：直接读盘上 dict 的 grade ⇒ 判据必须报违规
    _good2, bad2 = _grade_reads(
        'def f(r):\n    grade = str((r.get("bits") or {}).get("grade") or "")\n    return grade\n')
    assert bad2, "判据对『直接读盘上的 grade』不报 —— 它是一条恒真判据"
    _good3, bad3 = _grade_reads('def f(r):\n    g = r["bits"]["grade"]\n    return g\n')
    assert bad3, "判据对下标式读 grade 不报 —— 漏了另一条入口"


def test_the_reviewed_proof_leg_separates_never_computed_from_low_grade(
        tmp_path: pathlib.Path):
    """R3 三态：`没有位记录`与`算了、只到 conjecture`必须分得开（都要有读数）。

    旧读数的病：两件事同形（都表现为"没被计入 `counted`"），于是"这一趟根本没算过
    五位"会被读成"算了、就是低档"。这一条要求逐档分母并列：
    `statements_without_bits` / `grades_with_bits` / `counted`。
    """
    def seed(s: Store) -> None:
        # ① 没有任何位记录（老数据 / 产出方这一趟没走过）
        _statement(s, "0000", bits=None)
        # ② 有位记录，但只到 conjecture（算了、就是低档）
        _statement(s, "0001", bits={"proof": True,
                                    "evidence": {"proof_source": "own",
                                                 "proof_process": "（逐步论证）"}})
        # ③ 有位记录，且我方到预备定理级（这一档要数的）
        _statement(s, "0002", bits={"proof": True, "reviewed": True,
                                    "evidence": {"proof_source": "own",
                                                 "proof_process": "（逐步论证）",
                                                 "reviewed_by": {"round": "V-0001",
                                                                 "verdict": "no_defect"}}})

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _acceptance_checks(tmp_path, [{"id": "B2", "name": "造判决性证据",
                                   "kind": "reviewed_proof_rows", "min": 1}], st=st)
    rep = _gate(st, report)

    d = rep.readings["acceptance"]["rows"][0]["detail"]
    assert d["statements"] == 3, d
    assert d["statements_without_bits"] == 1 and d["without_bits_ids"] == ["0000"], d
    assert d["statements_with_bits"] == 2, d
    # 负控：没有位记录的那一行「不许」被算进"算了之后落在哪一档"
    assert d["grades_with_bits"] == {"conjecture": 1, "pre_theorem": 1}, d
    # 兼容读数（全行，按"五位全空 ⇒ conjecture"）：无记录那一行确实落在 conjecture 里 ——
    # 这正是它必须与 `grades_with_bits` 并列给出的原因
    assert d["grades"] == {"conjecture": 2, "pre_theorem": 1}, d
    assert d["counted"] and d["counted"][0]["stmt_id"] == "0002", d
    note = str(d["note"])
    assert "没有位记录" in note and "算了、不够档" in note, note
    assert rep.readings["acceptance"]["rows"][0]["got"] == 1


def test_the_external_lit_grade_carries_a_readable_reason(tmp_path: pathlib.Path):
    """R3 第三条：`external_lit` 被跳过时要有「可读理由串」（不只是计数）。

    口径确认：这一档数的是"我方造出的判决性证据"；引用外部文献得来的高档
    「不算」（否则"引一篇别人的定理"就满足了"我们自己造"）。引用命题的承重
    归 `load_bearing` 那一格 —— 理由串必须把这两件事说清。
    """
    def seed(s: Store) -> None:
        _statement(s, "0000", origin="external_lit", source_lit_id="0042",
                   quote_verified=True, proof_text="")
        _statement(s, "0001", bits={"proof": True, "reviewed": True,
                                    "evidence": {"proof_source": "own",
                                                 "proof_process": "（逐步论证）",
                                                 "reviewed_by": {"round": "V-0001",
                                                                 "verdict": "no_defect"}}})

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _acceptance_checks(tmp_path, [{"id": "B2", "name": "造判决性证据",
                                   "kind": "reviewed_proof_rows", "min": 1}], st=st)
    rep = _gate(st, report)

    d = rep.readings["acceptance"]["rows"][0]["detail"]
    assert d["cited_skipped"] == 1, d
    assert [r["stmt_id"] for r in d["cited_skipped_rows"]] == ["0000"], d
    reason = str(d["cited_skipped_reason"])
    assert "external_lit" in reason and "load_bearing" in reason, reason
    assert "我们自己造" in reason or "我方" in reason, reason
    # 被跳过的那一条「不许」进 `counted`（它进了 counted 就等于把别人的定理算成我们的）
    assert [c["stmt_id"] for c in d["counted"]] == ["0001"], d


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
        # 「检索（真的取回）」那一环（D60）：这一趟的结论来自证明过程，不依赖新检索。
        {"id": "R9", "name": "检索（真的取回）", "kind": "retrieval_ok_rows", "min": 1,
         "na": True, "note": "这一趟的结论由证明过程给出，不依赖新检索"},
        {"id": "R2", "name": "算或造", "kind": "reviewed_proof_rows", "min": 1},
        {"id": "R3", "name": "想", "kind": "conjecture_rows", "min": 0},
        {"id": "R4", "name": "交", "kind": "document_literature_citations", "min": 0},
        # 「看（关系分析）」那一环（D53）：这一趟走的是"造"那条腿，明说不用关系分析。
        {"id": "R5", "name": "看（关系分析）", "kind": "c_analysis_runs", "min": 1,
         "na": True, "note": "这一趟用证明过程收尾，不需要关系分析"},
        # 「攻（攻坚推进）」那一环（D59）：这一趟没有攻坚计划 ⇒ na + 理由。
        {"id": "R6", "name": "攻（攻坚推进）", "kind": "plan_progress_rows", "min": 1,
         "na": True, "note": "这一趟没有立过攻坚计划（结论由形式化给出）"},
        # 「交（手稿落盘）」那一环（D59）：夹具里 `documents` 1 行 ⇒ 真读数。
        {"id": "R7", "name": "交（手稿落盘）", "kind": "document_rows", "min": 1,
         "note": "夹具里有一份稿件"},
        # 「闭（请求闭环）」那一环（D56）：这一趟没提交过请求 ⇒ 上限 0 达标。
        {"id": "R8", "name": "闭（请求闭环）", "kind": "unfinished_request_rows", "min": 0,
         "note": "这一趟没有提交过检索请求"},
    ], st=st)
    rep = _gate(st, report)

    chain = rep.readings["acceptance"]["research_chain"]
    assert chain["groups"]["算或造"] == ["reviewed_proof_rows"], chain
    assert chain["missing"] == [], chain


def test_a_leg_that_needs_the_baseline_is_not_applicable_not_the_whole_cell(
        tmp_path: pathlib.Path):
    """CC-05（`draft/44` J-21：与 E-05 同批）：缺只读基线 ⇒ 该行不适用，不是整格没查成。

    真机读数（T2 第 7 趟 `projects/p6i-research-from-zero`）：验收表 P1 用了
    `manuscript_edited`，而从零工作区没有只读基线 `source/`。旧口径下那一行抛
    `ValueError` ⇒ 整格 `unknown`、`rows=0` —— 表里另外 10 行本来算得出数，
    却连读数都没留下（改前实测：`acceptance=unknown`、`code=acceptance_leg_unreadable`、
    `rows=0`）。

    现在分成两件事：
    - 缺只读基线 ⇒ 该行 `not_applicable`（既不是通过也不是失败），其余行照常判；
    - 台账读不到 / JSON 坏 / 词表外 ⇒ 仍然是"没查成"（整格 `unknown`，见下一条）。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "正文改动", "kind": "manuscript_edited", "min": 1},
        {"id": "P2", "name": "交付物在不在", "kind": "document_rows", "min": 1},
    ], st=st)
    rep = _gate(st, report)

    reading = rep.readings["acceptance"]
    assert isinstance(reading, dict) and reading.get("rows"), reading
    assert [r["id"] for r in reading["rows"]] == ["P1", "P2"], reading["rows"]
    na_row = reading["rows"][0]
    assert na_row["not_applicable"] is True and na_row["ok"] is None, na_row
    assert "source/main.tex" in na_row["reason"].replace("\\", "/"), na_row
    assert reading["rows_not_applicable"] == 1 and reading["rows_read"] == 1, reading
    assert reading["not_applicable_rows"] == ["P1"], reading
    # 其余行照常判 ⇒ 这一格由它们决定（不再因为一行算不出来就整格没查成）
    assert rep.status["acceptance"] == "pass", rep.to_dict()


def test_a_broken_ledger_still_makes_the_whole_cell_unknown(tmp_path: pathlib.Path):
    """三态分界（CC-05 的另一半）：读不到台账 ⇒ 整格 `unknown`（"没查成"）。

    "缺基线 ⇒ 不适用"与"读不到 ⇒ 没查成"必须分得开：把后者也折成 `not_applicable`
    等于把"我们没读到"读成"这一档用不上"（最贵的方向）。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "引文逐条核过", "kind": "citation_records_vs_bibitems", "min": 1},
    ], st=st)
    # 基线在盘上（走不到 not_applicable），但台账读不到：把 statements 表读坏
    src = tmp_path / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.tex").write_text("\\bibitem{a}\n", encoding="utf-8")

    class _Boom:
        root = st.root

        def rows(self, name):
            if name == "research_questions":       # 覆盖面那一格照常读（它不参与本条判据）
                return []
            raise OSError("表读不到（注入）")

    rep = CL.check_closing(_Boom(), project_dir=str(tmp_path), report_path=str(report),
                           checks=("acceptance",))
    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    reading = rep.readings["acceptance"]
    # CC-02：这一行落 `unreadable`（好行的读数照留），整格仍 `unknown`
    # （"读不到台账"不许折成 `not_applicable`，也不许折成 `pass`）。
    assert reading["rows_unreadable"] == 1, reading
    assert reading["unreadable_rows"][0]["code"] == "acceptance_leg_unreadable", reading
    detail = reading["unreadable_rows"][0]["reason"]
    assert "OSError" in detail, detail
    codes = [f.code for f in rep.findings if f.code.startswith("acceptance")]
    assert codes == ["acceptance_leg_unreadable", "acceptance_rows_unreadable"], codes
    # 反真空：它不是 `not_applicable`（那是"缺只读基线"那一档）
    assert reading["rows_not_applicable"] == 0, reading
    assert reading["rows"][0]["state"] == "unreadable", reading["rows"][0]


def test_the_row_state_judge_has_exactly_one_definition():
    """CC-02：行状态判据只有一处定义，四种状态各自可判，老读数行也读得对。

    为什么单列（主控裁定边界 5："一处定义、两处用，改一次两处同时正确"）：
    行循环产出 `state`，四条自动分支的守卫（E-04a）与覆盖率消费它 ——
    分别写两份就是"各修一半"。这条测试既钉住四种状态的语义，也把这两个入口
    直接调一次。
    """
    rows = [
        {"kind": "a", "state": "computed", "got": 1, "ok": True},
        {"kind": "b", "na": True, "state": "na", "got": None, "ok": True},
        {"kind": "c", "state": "unreadable", "ok": None},
        {"kind": "d", "state": "not_applicable", "ok": None},
        {"kind": "a", "na": True, "state": "na", "got": None, "ok": True},
    ]
    assert CL.acceptance_row_state(rows[0]) == "computed"
    assert CL.acceptance_row_state(rows[1]) == "na"
    assert CL.acceptance_row_state(rows[2]) == "unreadable"
    assert CL.acceptance_row_state(rows[3]) == "not_applicable"
    # 老读数行（没有 `state` 键）按旧语义推 —— 204 行历史读数与手写的行对象都读得对
    assert CL.acceptance_row_state({"kind": "x", "got": 1, "ok": True}) == "computed"
    assert CL.acceptance_row_state({"kind": "x", "na": True}) == "na"
    assert CL.acceptance_row_state({"kind": "x", "not_applicable": True}) == "not_applicable"
    # 只有 `computed` 算"这一档被算过"（`na`/`not_applicable`/`unreadable` 都不算）
    assert CL.acceptance_kinds_with_state(rows, "computed") == {"a"}
    assert CL.acceptance_kinds_with_state(rows, "na") == {"a", "b"}
    assert CL.acceptance_kinds_with_state(rows, "unreadable") == {"c"}
    assert CL.acceptance_kinds_with_state(rows, "not_applicable") == {"d"}
    # 一处定义：定义点各只有一个（分叉会让守卫与行循环各读一套）
    import inspect

    src = inspect.getsource(CL)
    assert src.count("def acceptance_row_state(") == 1, "行状态判据被定义了不止一处"
    assert src.count("def acceptance_kinds_with_state(") == 1, "状态到 kind 的取值被定义了不止一处"


def test_a_row_level_defect_does_not_take_the_whole_table_down(tmp_path: pathlib.Path):
    """CC-02（`draft/52` 裁定 (a)）：行级读不懂只废那一行，好行的读数照留。

    三种形态一起钉（都是"顶层读得出来、行里坏了"）：

    - 一行不是对象；② 词表外 `kind`；③ `na` 无理由。
    改前它们都让整格 `unknown` 且 `rows=0`（好行的读数一起丢 —— 那正是 CC-05
    刚修掉的反向错误）。改后：好行 `state="computed"` 且 `got/ok` 真实、
    坏行 `state="unreadable"`、整格 `unknown`（绝不 `pass`）。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "交付物在不在", "kind": "document_rows", "min": 1},
        {"id": "P2", "name": "我编的档", "kind": "render_anchor_consistent", "min": 1},
    ], st=st)
    rep = _gate(st, report)
    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    acc = rep.readings["acceptance"]
    assert [r["state"] for r in acc["rows"]] == ["computed", "unreadable"], acc["rows"]
    good = acc["rows"][0]
    assert good["got"] == 1 and good["ok"] is True, good
    # 好行的读数与"表里只有它"时逐字相同（坏行不许影响它）
    only_good = CL.check_closing(Store(tmp_path), project_dir=str(tmp_path),
                                 checks=("acceptance",))
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "交付物在不在", "kind": "document_rows", "min": 1},
    ], st=st)
    rep2 = _gate(st, report)
    assert rep2.status["acceptance"] == "pass", rep2.to_dict()
    row_only = rep2.readings["acceptance"]["rows"][0]
    assert {k: good[k] for k in ("id", "kind", "got", "ok", "min", "max")} == \
        {k: row_only[k] for k in ("id", "kind", "got", "ok", "min", "max")}, (good, row_only)
    assert good["detail"] == row_only["detail"], (good["detail"], row_only["detail"])
    assert only_good is not None


def test_a_bad_threshold_type_does_not_crash_the_gate(tmp_path: pathlib.Path):
    """CC-02：`min`/`max` 不是整数 ⇒ 那一行 `unreadable`，门不许崩。

    改前必红（门崩）：`int(row.get("min") or 0)` 对 `"abc"` 抛 `ValueError`、
    对 `{}` 抛 `TypeError`，异常直接穿出 `check_closing` —— 整个收工门报不出来。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "交付物在不在", "kind": "document_rows", "min": 1},
        {"id": "P2", "name": "坏阈值", "kind": "document_rows", "min": "abc"},
    ], st=st)
    rep = _gate(st, report)                      # 不抛就是这一条的一半
    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    acc = rep.readings["acceptance"]
    assert acc["rows_unreadable"] == 1, acc
    assert "不是整数" in acc["unreadable_rows"][0]["reason"], acc["unreadable_rows"]
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "交付物在不在", "kind": "document_rows", "min": 1},
        {"id": "P2", "name": "坏上限", "kind": "document_rows", "min": 1, "max": {}},
    ], st=st)
    rep2 = _gate(st, report)
    assert rep2.status["acceptance"] == "unknown", rep2.to_dict()
    assert rep2.readings["acceptance"]["rows_unreadable"] == 1, rep2.readings["acceptance"]


def test_a_non_boolean_na_is_not_silently_judged_as_a_normal_row(tmp_path: pathlib.Path):
    """CC-02：`"na": "true"`（非布尔）⇒ 该行 `unreadable`、整格 `unknown`。

    改前必红（假绿方向，最值钱的一条）：旧口径只认 `is True`，于是
    `"na": "true"` 被当普通行判 —— `na` 的语义被静默丢掉（既不生效也不报错），
    整格还能读成 `pass`。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "交付物在不在", "kind": "document_rows", "min": 1},
        {"id": "P2", "name": "想写 na 但写错了类型", "kind": "document_rows", "na": "true"},
    ], st=st)
    rep = _gate(st, report)
    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    acc = rep.readings["acceptance"]
    assert acc["rows_unreadable"] == 1, acc
    assert "na" in acc["unreadable_rows"][0]["reason"], acc["unreadable_rows"]
    assert "布尔" in acc["unreadable_rows"][0]["reason"], acc["unreadable_rows"]


def test_a_missing_or_duplicate_id_is_reported(tmp_path: pathlib.Path):
    """CC-02：`id` 缺失 / 重复 ⇒ 该行 `unreadable` + 读数 `duplicate_ids`。

    为什么这条重要：`id` 是人与表对上那一行的唯一把手。改前 `id` 缺失的读数在
    报告里显示成空串、重复 id 一个字都不报 —— 读数与人对不上，而门照样绿。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"name": "没有 id", "kind": "document_rows", "min": 1},
        {"id": "P1", "name": "交付物在不在", "kind": "document_rows", "min": 1},
        {"id": "P1", "name": "重复 id", "kind": "document_rows", "min": 1},
    ], st=st)
    rep = _gate(st, report)
    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    acc = rep.readings["acceptance"]
    assert acc["rows_unreadable"] == 2, acc
    assert acc["duplicate_ids"] == ["P1"], acc
    assert [r["state"] for r in acc["rows"]] == ["unreadable", "computed", "unreadable"], \
        acc["rows"]


def test_a_leg_unreadable_row_does_not_silence_an_automatic_branch(tmp_path: pathlib.Path):
    """CC-02 × E-04a（一处定义，两处用）：`unreadable` 行不算 `computed_kinds`。

    形态：表里给 `reviewed_current_rows` 写一行坏行（非布尔 `na`），
    而那一档的自动分支（"现行版没有被审校记录钉住"）必须照旧报出来 ——
    如果守卫用"表里有没有这个 kind"或把 `unreadable` 也算 `computed`，
    一行坏行就能关掉分支（那正是 E-04a 治的洞换了入口）。
    """
    st, report = _good(tmp_path)
    _accepted_doc(st)
    _revise_after_signoff(st)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "稿件有裁决", "kind": "reviewed_documents", "min": 1},
        {"id": "P2", "name": "坏行", "kind": "reviewed_current_rows", "na": "true"},
    ], st=st)
    rep = _gate(st, report)
    acc = rep.readings["acceptance"]
    assert acc["na_only_branch_kinds"] == [], acc
    detail = "；".join(f.detail for f in rep.blockers if f.check == "acceptance")
    assert "现行版本没有被审校记录钉住的稿件" in detail, detail
    assert rep.status["acceptance"] == "fail", rep.to_dict()

    # 同一份表里把坏行改成合法的 `na` + 理由 ⇒ 分支仍然报（E-04a 的语义不变）
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "稿件有裁决", "kind": "reviewed_documents", "min": 1},
        {"id": "P2", "name": "现行版复核", "kind": "reviewed_current_rows",
         "na": True, "note": "同事说这一版不用复核"},
    ], st=st)
    rep2 = _gate(st, report)
    assert rep2.readings["acceptance"]["na_only_branch_kinds"] == ["reviewed_current_rows"], \
        rep2.readings["acceptance"]
    detail2 = "；".join(f.detail for f in rep2.blockers if f.check == "acceptance")
    assert "现行版本没有被审校记录钉住的稿件" in detail2, detail2


def test_a_self_invented_kind_says_it_takes_the_whole_table_down(tmp_path: pathlib.Path):
    """判据（D35 的另一半 + CC-02）：自造 `kind` 让整格不通过，但读数逐行留下。

    口径沿革：旧措辞是"一个 kind 不认识 ⇒ 整张表都判没查成"（读数一起没了）。
    CC-02（`draft/52` 裁定 (a)）之后：这一行 `unreadable`、其余行照常判、
    整格 `unknown`（绝不 `pass`）—— 威慑不变（门照样过不去），连坐去掉。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "我编的档", "kind": "render_anchor_consistent", "min": 1},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    acc = rep.readings["acceptance"]
    assert acc["rows_unreadable"] == 1, acc
    assert "受控词表" in acc["unreadable_rows"][0]["reason"], acc["unreadable_rows"]
    assert "整张表" not in "".join(f.detail for f in rep.findings), \
        "读数里不该再出现『整张表都没查成』那句旧措辞（口径已改成行级）"


# ============================================================ `na` 行（D49）


def test_an_na_row_counts_as_marked_and_leaves_a_reading(tmp_path: pathlib.Path, monkeypatch):
    """判据（`draft/39` §6.39 的 D49）：某一档对这个项目天然不适用时，`na` 要能写成读数。

    真机读数（T4 第 1 趟 `projects/p7-open-questions`）：那是一趟调查任务
    （"调查…开放问题，交付一份清单"），它天然没有"算或造"那一步 —— M 按纪律如实写了 0
    （红得精确），可那份诚实没有出口：政策里提过 `na` 这个词，实现里只认 `got >= min`，
    于是"这一档不适用"只能被读成"没做"。
    三态：`na` ≠ 通过 ≠ 失败 —— 读数里要能看见这一行是 `na`、理由是什么。
    """
    st, report = _good(tmp_path)
    _as_research(st, monkeypatch)
    _acceptance_checks(tmp_path, [
        {"id": "A1", "name": "立题与检索", "kind": "research_question_rows", "min": 1},
        {"id": "A2", "name": "算或造", "kind": "numeric_experiment_rows", "min": 1,
         "na": True, "note": "这是调查型任务（交付清单），没有数值/构造那一步"},
        {"id": "A3", "name": "想", "kind": "conjecture_rows", "min": 1,
         "na": True, "note": "同上：调查不产出猜想"},
        # 「检索（真的取回）」与「攻（攻坚推进）」两环（D59/D60）在这一趟不适用 ⇒ na + 理由。
        {"id": "A7", "name": "检索（真的取回）", "kind": "retrieval_ok_rows", "min": 1,
         "na": True, "note": "这一趟的结论由夹具给出，不依赖新检索"},
        {"id": "A8", "name": "攻（攻坚推进）", "kind": "plan_progress_rows", "min": 1,
         "na": True, "note": "这一趟没有立过攻坚计划"},
        # 「交」那一档要有真读数（覆盖面要求八环节各有其行；`na` 只用来标不适用，
        # 不许把整张表都变成 na）
        {"id": "A4", "name": "交（有证据支撑的断言）", "kind": "supported_claims", "min": 1},
        {"id": "A5", "name": "看（关系分析）", "kind": "c_analysis_runs", "min": 1,
         "na": True, "note": "这条腿用证明过程收尾，不需要关系分析"},
        # 「闭（请求闭环）」（D56）：这一趟没提交过请求 ⇒ 上限 0 达标（真读数，不是 na）。
        {"id": "A6", "name": "闭（请求闭环）", "kind": "unfinished_request_rows", "min": 0,
         "note": "这一趟没有提交过检索请求"},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "pass", rep.to_dict()
    rows = {r["id"]: r for r in rep.readings["acceptance"]["rows"]}
    assert rows["A2"]["na"] is True and rows["A2"]["got"] is None, rows["A2"]
    assert "调查型任务" in rows["A2"]["note"], rows["A2"]
    chain = rep.readings["acceptance"]["research_chain"]
    assert chain["na_groups"]["算或造"], chain
    assert chain["missing"] == [], chain


def test_an_na_row_without_a_reason_is_not_checked(tmp_path: pathlib.Path):
    """负控：`na` 不写理由 ⇒ 这一行读不懂（`na` 不是"跳过"的快捷键）。

    CC-02 之后它是行级的：该行 `unreadable`、整格 `unknown`（绝不 `pass`）。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "某档", "kind": "numeric_experiment_rows", "min": 1, "na": True},
        {"id": "P2", "name": "交付物在不在", "kind": "document_rows", "min": 1},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    acc = rep.readings["acceptance"]
    assert acc["rows_unreadable"] == 1, acc
    row = acc["unreadable_rows"][0]
    assert row["code"] == "acceptance_na_without_reason", row
    assert "理由" in row["reason"], row
    # 好行的读数照留（不是整格没读数）
    assert [r["state"] for r in acc["rows"]] == ["unreadable", "computed"], acc["rows"]


def test_a_table_of_nothing_but_na_is_refused(tmp_path: pathlib.Path):
    """负控：整张表全是 `na` ⇒ 红（一张全 na 的验收表等于没有验收表）。"""
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "某档", "kind": "numeric_experiment_rows", "min": 1,
         "na": True, "note": "不适用"},
        {"id": "P2", "name": "另一档", "kind": "conjecture_rows", "min": 1,
         "na": True, "note": "也不适用"},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "fail", rep.to_dict()
    assert [f.code for f in rep.blockers] == ["acceptance_all_na"], rep.to_dict()


def test_the_c_analysis_kind_counts_role_c_task_rows(tmp_path: pathlib.Path, monkeypatch):
    """判据（`draft/39` §6.41 的 D52）：`c_analysis_runs` 数的是 `tasks` 里 role=C 的任务行。

    为什么单列这一档（真机读数 T5 第 1 趟 `p8-fermat-shorter-proof`）：用户点名
    "重点考察 C"，而那一趟 `tasks` 里 role=C 的行是 0、七格全绿、无人察觉 ——
    因为 C 的八个动作产物就是返回值本身、不落台账，没有任何一格能回答"用没用 C"。
    这一档把那个问题变成可复算的读数（任务行是 C 唯一会留下的痕迹）。
    """
    from agentflow import closing as CL

    st, report = _good(tmp_path)
    real_rows = st.rows
    tasks = [
        {"task_id": "t-1", "role": "C", "action": "hottest", "status": "done"},
        {"task_id": "t-2", "role": "C", "action": "gaps", "status": "failed"},
        {"task_id": "t-3", "role": "D", "action": "propose_question", "status": "done"},
    ]
    monkeypatch.setattr(st, "rows", lambda table: (tasks if table == "tasks" else real_rows(table)))
    got, detail = CL._leg_reading(st, "c_analysis_runs", tmp_path)
    assert got == 2, detail
    assert [t["action"] for t in detail["c_tasks"]] == ["hottest", "gaps"], detail

    # 负控：一次都没派过 C ⇒ 0（这一档的读数就是"用没用它"）
    monkeypatch.setattr(st, "rows", lambda table: ([] if table == "tasks" else real_rows(table)))
    got2, detail2 = CL._leg_reading(st, "c_analysis_runs", tmp_path)
    assert got2 == 0, detail2
    assert "一次都没用过 C" in detail2["note"], detail2


# ============================================================ 手稿成体与引文对得上（D61/D62/D63）


def _doc_with(store: Store, *, doc_id: str, claims: list[dict],
              sections: list[dict] | None):
    """落一份稿件（`sections` 给了就带上；`None` = 清单型交付，不带 sections）。"""
    row: dict = {"doc_id": doc_id, "kind": "survey", "title": "稿", "status": "draft",
                 "claims": claims, "created_at": TS}
    if sections is not None:
        row["sections"] = sections
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", row)
    sync_counters(store)
    return row


def test_the_citation_fit_check_catches_swapped_and_irrelevant_citations(tmp_path: pathlib.Path):
    """判据（`draft/39` §6.48 的 D61/D62）：断言与它引的证据说的是不是同一件事（确定性）。

    真机读数（T5 第 7 趟 `p8g-fermat-shorter-proof`）——三条断言，三处都躲过了旧读数：
    claim-2（n=3，界 2000）引 `exp:0000`（n=4，界 1000）、claim-3（n=4，界 1000）引
    `exp:0001`（n=3，界 2000）两条互换；claim-1（Wiles 证明的三条承重腿）引的
    `lit:0000` 是「PRIMES is in P」（AKS 素性检验）。
    """
    from agentflow import closing as CL

    st, _report = _good(tmp_path)
    # 两条实验：exp:0000 = n=4/界 1000、exp:0001 = n=3/界 2000（与真机同形的穷举行）
    _numeric_experiment(st, eid="0000",
                        claim="No solution to a^4+b^4=c^4 with a,b,c <= 1000",
                        search_bound={"exponents": [4], "n": 1000})
    _numeric_experiment(st, eid="0001",
                        claim="No solution to a^3+b^3=c^3 with a,b,c <= 2000",
                        search_bound={"exponents": [3], "n": 2000})
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0000", title="PRIMES is in P", type="J",
                                             path="library/0000/a.pdf",
                                             summary="AKS primality test.").to_dict())
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(
            lit_id="0001", title="Fermat's Last Theorem for regular primes", type="J",
            path="library/0001/b.pdf",
            summary="Kummer's approach via regular primes.").to_dict())
    _doc_with(st, doc_id="0009", sections=None, claims=[
        {"claim_id": "c1", "evidence_kind": "heuristic", "section": "s",
         "text": "The Wiles-Taylor proof of Fermat's Last Theorem proceeds through the Frey "
                 "curve construction and Ribet's level-lowering theorem.",
         "citations": ["lit:0000"]},                    # 跑题：AKS 素性检验
        {"claim_id": "c2", "evidence_kind": "cross_check", "section": "s",
         "disclaimer": "数值交叉验证，不构成证明",
         "text": "No solution to a^3+b^3=c^3 with a,b,c <= 2000.",
         "citations": ["exp:0000"]},                    # 互换：0000 是 n=4/界 1000
        {"claim_id": "c3", "evidence_kind": "cross_check", "section": "s",
         "disclaimer": "数值交叉验证，不构成证明",
         "text": "No solution to a^3+b^3=c^3 with a,b,c <= 2000.",
         "citations": ["exp:0001"]},                    # 这一条对得上
    ])

    fit = CL.citation_fit(st)
    verdicts = {(c["doc_id"], c["claim_id"]): c["verdict"] for c in fit["claims"]}
    assert verdicts[("0009", "c2")] == "mismatch", fit
    assert verdicts[("0009", "c3")] == "fit", fit
    assert verdicts[("0009", "c1")] == "mismatch", fit
    # 三态：判不了的那一条记 unjudged（不冒充通过）
    got, detail = CL._leg_reading(st, "claim_evidence_fit_rows", tmp_path)
    assert detail["implicit_min"] == fit["judged"], detail
    assert got == fit["fit"], detail


def test_a_hollow_manuscript_is_not_a_manuscript(tmp_path: pathlib.Path):
    """判据（`draft/39` §6.48 的 D63）：有 sections 却每节都空的稿件是骨架，不是手稿。

    真机读数（T5 第 7 趟 `p8g`）：那份 survey 的三节 body 全是空串，
    而 `document_rows` 与 `document_literature_citations` 都绿。
    """
    from agentflow import closing as CL

    st, report = _good(tmp_path)
    _doc_with(st, doc_id="0009", claims=[
        {"claim_id": "c1", "evidence_kind": "heuristic", "section": "s",
         "text": "一份只有标题的稿子", "citations": ["exp:0001"]}],
        sections=[{"heading": "1. Intro", "body": ""}, {"heading": "2. Open", "body": "   "}])
    got, detail = CL._leg_reading(st, "document_body_rows", tmp_path)
    assert got == 0, detail
    assert detail["empty_section_docs"], detail
    assert detail["implicit_min"] == 1, detail

    # 有正文之后这一档成立
    with st.tx("documents", actor="test") as tx:
        row = dict(tx.rows("documents")[-1])
        row["sections"] = [{"heading": "1. Intro", "body": "这一段是正文。"}]
        tx.upsert("documents", row)
    got2, _ = CL._leg_reading(st, "document_body_rows", tmp_path)
    assert got2 == 1, "每节都有正文 ⇒ 这一档成立"

    # 门在自己报：验收表里没写这一档时，空壳稿件让 acceptance 红
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "有稿件", "kind": "document_rows", "min": 1},
    ], st=st)
    with st.tx("documents", actor="test") as tx:
        row = dict(tx.rows("documents")[-1])
        row["sections"] = [{"heading": "1. Intro", "body": ""}]
        tx.upsert("documents", row)
    rep = _gate(st, report)
    detail_txt = "；".join(f.detail for f in rep.blockers if f.check == "acceptance")
    assert "只有骨架、没有正文" in detail_txt, detail_txt


def test_the_document_claim_kind_needs_one_claim_per_question(tmp_path: pathlib.Path,
                                                              monkeypatch):
    """判据（D63）：手稿里带引文的断言条数不少于研究问题条数（阈值随台账走）。

    `document_rows` 问"那份东西在不在"，这一档问"它有没有把立起来的问题说进去"。
    """
    from agentflow import closing as CL

    st, _report = _good(tmp_path)
    _as_research(st, monkeypatch)          # 1 条研究问题
    got, detail = CL._leg_reading(st, "document_claim_rows", tmp_path)
    assert got == 1 and detail["implicit_min"] == 1, detail

    real_rows = st.rows
    questions = [{"question_id": f"q-{i}", "question": "why?", "status": "open"}
                 for i in range(3)]
    monkeypatch.setattr(st, "rows", lambda table: (
        questions if table == "research_questions" else real_rows(table)))
    got2, detail2 = CL._leg_reading(st, "document_claim_rows", tmp_path)
    assert got2 == 1 and detail2["implicit_min"] == 3, detail2


# ============================================================ 交付物与检索那一腿（D59/D60）


def test_the_document_rows_kind_counts_the_deliverable_itself(tmp_path: pathlib.Path):
    """判据（`draft/39` §6.47 的 D59）：这一档数的是"任务说要交的那份东西在不在"。

    真机读数（T5 第 6 趟 `p8f-fermat-shorter-proof`）：任务原话是「交付进展手稿与说明」，
    而盘上 `documents` 0 行；`substance` 那一格照样绿（它只看五张表里有没有非空的，
    `relations` 47 行就够），于是"没有稿子"这件事只有这一档能说。
    """
    from agentflow import closing as CL

    st, _report = _good(tmp_path)
    got, detail = CL._leg_reading(st, "document_rows", tmp_path)
    assert got == 1 and detail["with_claims"] == 1, detail
    assert detail["ids"] == ["0001"], detail

    # 负控：一份稿件都没有 ⇒ 0（这一档就是"交付物本身在不在"）
    real_rows = st.rows
    st.rows = lambda table: ([] if table == "documents" else real_rows(table))  # type: ignore[method-assign]
    got2, detail2 = CL._leg_reading(st, "document_rows", tmp_path)
    assert got2 == 0, detail2
    assert "交付物本身在不在" in detail2["note"], detail2


def test_the_retrieval_ok_kind_needs_one_success_per_question(
        tmp_path: pathlib.Path, monkeypatch):
    """判据（`draft/39` §6.47 的 D60）：这一档数的是真的取回的次数，阈值由问题数算出来。

    真机读数（T5 第 6 趟 `p8f`）：4 次检索 2 次 `no_results`（题面式说法、没换规范术语重查），
    `literature` 8 行；M 自己在报告的「未决问题」第 6 条里写着「未按纪律用规范术语再查一轮」。
    「查过」与「查到了」必须分开：`retrieval_attempts` 把 `no_results` 也算进去。
    """
    from agentflow import closing as CL

    st, _report = _good(tmp_path)
    real_rows = st.rows
    reqs = [
        {"request_id": "r-1", "topic": "short proof of Fermat's Last Theorem",
         "done": True, "outcome": "no_results"},
        {"request_id": "r-2", "topic": "Kummer regular primes Fermat", "done": True,
         "outcome": "ok", "result_lit_ids": ["0000"]},
    ]
    questions = [{"question_id": f"q-{i}", "question": "why?", "status": "open"}
                 for i in range(3)]
    monkeypatch.setattr(st, "rows", lambda table: (
        reqs if table == "search_requests"
        else questions if table == "research_questions" else real_rows(table)))
    got, detail = CL._leg_reading(st, "retrieval_ok_rows", tmp_path)
    assert got == 1, detail
    # 3 个问题 ⇒ 至少 3 次成功取回；`no_results` 的那条进明细、不进这一档的分子
    assert detail["implicit_min"] == 3, detail
    assert detail["no_results"] == 1 and detail["no_result_topics"], detail

    # 负控：把问题减到 1 条 ⇒ 同一个读数就成立了（阈值随台账长，不是我拍的数）
    monkeypatch.setattr(st, "rows", lambda table: (
        reqs if table == "search_requests"
        else questions[:1] if table == "research_questions" else real_rows(table)))
    got2, detail2 = CL._leg_reading(st, "retrieval_ok_rows", tmp_path)
    assert got2 == 1 and detail2["implicit_min"] == 1, detail2


def test_a_stage_cannot_be_covered_by_a_reading_about_something_else(
        tmp_path: pathlib.Path, monkeypatch):
    """判据（D59 的核心）：用 `plan_progress_rows`（F 的计划推进）顶不了「交」那一环。

    改前「交」那一环的成员里有 `plan_progress_rows` ⇒ 一份稿子都没有的交付照样"覆盖"了
    「交」，而任务原文说的正是"交付进展手稿"。现在 F 的推进归「攻」，「交」只认
    必须在稿件里才成立的档。
    """
    from agentflow import closing as CL

    st, report = _good(tmp_path)
    _as_research(st, monkeypatch)
    _acceptance_checks(tmp_path, [
        {"id": "R1", "name": "立题", "kind": "research_question_rows", "min": 1},
        {"id": "R2", "name": "检索", "kind": "retrieval_ok_rows", "na": True,
         "note": "这一趟的结论不依赖新检索（探针用夹具）"},
        {"id": "R3", "name": "算或造", "kind": "search_frontier_rows", "min": 1},
        {"id": "R4", "name": "想", "kind": "conjecture_rows", "na": True,
         "note": "夹具不产出猜想"},
        {"id": "R5", "name": "看", "kind": "c_analysis_runs", "na": True,
         "note": "夹具不跑关系分析"},
        # 就是这一行：M 在真机上把 F 的计划推进填进了「交」。
        {"id": "R6", "name": "交（计划推进）", "kind": "plan_progress_rows", "min": 1},
        {"id": "R8", "name": "闭", "kind": "unfinished_request_rows", "max": 0},
    ], st=st)
    rep = _gate(st, report)

    chain = rep.readings["acceptance"]["research_chain"]
    assert any("交（手稿落盘）" in m for m in chain["missing"]), chain
    assert chain["groups"]["攻（攻坚推进）"] == ["plan_progress_rows"], chain
    detail = "；".join(f.detail for f in rep.blockers if f.check == "acceptance")
    assert "交（手稿落盘）" in detail, detail


# ============================================================ 「闭（请求闭环）」那一档（D56）
def test_the_unfinished_request_kind_counts_queued_but_undone_requests(
        tmp_path: pathlib.Path, monkeypatch):
    """判据（`draft/39` §6.45 的 D56）：这一档数的是「提交了、没人做」的请求。

    真机读数（T5 第 5 趟 `projects/p8e-fermat-shorter-proof`）：F 的攻坚子目标用
    `submit_search_request` 提了 `r-0004`（`done=false` / `claimed_by=null` /
    `attempts=0`），计划那一行写着「等 A 完成检索请求 r-0004」，而七格全绿、
    `can_close=true` —— 一件被提交的活整趟没发生，收工门上一个读数都没有。
    这一档就是那件事的读数：它数没做的（`retrieval_attempts` 数的是做过的）。
    """
    from agentflow import closing as CL

    st, _report = _good(tmp_path)
    real_rows = st.rows
    rows = [
        {"request_id": "r-0001", "topic": "a", "done": True, "outcome": "ok",
         "submitted_by": "agent-A", "attempts": 1},
        {"request_id": "r-0004", "topic": "核验 1995 年后是否有初等证明", "done": False,
         "outcome": None, "submitted_by": "agent-F", "claimed_by": None, "attempts": 0},
    ]
    monkeypatch.setattr(st, "rows", lambda table: (
        rows if table == "search_requests" else real_rows(table)))
    got, detail = CL._leg_reading(st, "unfinished_request_rows", tmp_path)
    assert got == 1, detail
    assert [r["id"] for r in detail["unfinished"]] == ["r-0004"], detail
    assert detail["unfinished"][0]["submitted_by"] == "agent-F", detail
    # 这一档的方向是「上限」：0 才是达标，别让调用方把它读成 `got >= min`
    assert detail["implicit_max"] == 0 and detail["implicit_min"] == 0, detail
    # 负控：都做完了 ⇒ 0
    rows[1]["done"] = True
    got2, _ = CL._leg_reading(st, "unfinished_request_rows", tmp_path)
    assert got2 == 0, "全部 done=true 时这一档必须是 0"


def test_a_queued_request_that_nobody_did_fails_its_row(tmp_path: pathlib.Path,
                                                        monkeypatch):
    """负控（D56 的核心）：队列里躺着一条没人做的请求 ⇒ 第六环那一行不成立（上限 0）。

    这是"请求提交了没人做"在收工门上的读数。改前它是静默的：T5 第 5 趟七格全绿。
    """
    st, report = _good(tmp_path)
    real_rows = st.rows
    rows = [{"request_id": "r-0004", "topic": "FLT 短证明文献", "done": False,
             "submitted_by": "agent-F", "claimed_by": None, "attempts": 0}]
    monkeypatch.setattr(st, "rows", lambda table: (
        rows if table == "search_requests" else real_rows(table)))
    _as_research(st, monkeypatch)
    _acceptance_checks(tmp_path, list(_FULL_COVER), st=st)
    rep = _gate(st, report)

    row = next(r for r in rep.readings["acceptance"]["rows"] if r["id"] == "R8")
    assert row["got"] == 1 and row["ok"] is False, row
    assert row["max"] == 0 and row["min"] == 0, row
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    detail = "；".join(f.detail for f in rep.blockers)
    assert "上限 0 条" in detail and "r-0004" in detail, detail    # 点名那条请求

    # 派 A 认领跑完之后（`done=true`）这一行就成立 —— 这一档不是"永远红"
    rows[0]["done"] = True
    rows[0]["outcome"] = "ok"
    rep2 = _gate(st, report)
    row2 = next(r for r in rep2.readings["acceptance"]["rows"] if r["id"] == "R8")
    assert row2["got"] == 0 and row2["ok"] is True, row2
    assert "R8" not in "；".join(f.detail for f in rep2.blockers), rep2.to_dict()


def test_an_na_row_is_the_way_to_leave_a_request_open_on_purpose(
        tmp_path: pathlib.Path, monkeypatch):
    """三态：确实要把某条请求留着（预算用尽 / 优先级更低）⇒ 标 `na` + 理由也算数。

    与其它五环同一条口径：`na` ≠ 通过 ≠ 失败。这一档存在的意义不是"一条都不许剩"，
    而是"剩了几条"这件事必须被看见、被写下来。
    """
    st, report = _good(tmp_path)
    real_rows = st.rows
    rows = [{"request_id": "r-0009", "topic": "低优先级的旁支检索", "done": False,
             "submitted_by": "agent-F", "attempts": 0}]
    monkeypatch.setattr(st, "rows", lambda table: (
        rows if table == "search_requests" else real_rows(table)))
    _as_research(st, monkeypatch)
    cover = [dict(r) for r in _FULL_COVER]
    cover[-1] = {"id": "R8", "name": "闭（请求闭环）", "kind": "unfinished_request_rows",
                 "na": True, "note": "预算用尽，r-0009 这条旁支检索留着不做了（如实记账）"}
    _acceptance_checks(tmp_path, cover, st=st)
    rep = _gate(st, report)

    row = next(r for r in rep.readings["acceptance"]["rows"] if r["id"] == "R8")
    assert row["na"] is True and row["got"] is None, row
    assert "预算用尽" in row["note"], row
    assert "R8" not in "；".join(f.detail for f in rep.blockers), rep.to_dict()


def test_a_reprocess_request_that_is_still_pending_counts_too(tmp_path: pathlib.Path,
                                                              monkeypatch):
    """两条队列一起数：`reprocess_requests` 里 `status=pending` 的行也算没做完。

    为什么必须一起数（`draft/39` §6.45 的 D56）：请求队列有两条 —— A 的检索与 B 的
    重抽取；两条的"没做完"字段名还不一样（`done` 是布尔、另一张是 `status`）。
    判据写在同一个地方，免得调用方各判一套（那正是"D 与 C 各持一套判据"的同一种病）。
    """
    from agentflow import closing as CL

    st, _report = _good(tmp_path)
    real_rows = st.rows
    rows = [{"reprocess_id": "p-0001", "reason": "need_context", "status": "pending",
             "submitted_by": "agent-D", "attempts": 0}]
    monkeypatch.setattr(st, "rows", lambda table: (
        rows if table == "reprocess_requests" else real_rows(table)))
    got, detail = CL._leg_reading(st, "unfinished_request_rows", tmp_path)
    assert got == 1 and detail["reprocess_unfinished"] == 1, detail
    rows[0]["status"] = "done"
    got2, _ = CL._leg_reading(st, "unfinished_request_rows", tmp_path)
    assert got2 == 0, "status=done 不该还算没做完"


# ============================================================ 「改完之后有没有再复核」（D57）


def _sign_doc(st: Store, doc_row: dict, **patch) -> dict:
    """给一行稿件签一条合法签名（照 `test_doc_signatures._sign` 的口径）。"""
    from agentflow import signatures as SIG

    cur = SIG.content_sha256_of(doc_row)
    rec = {"doc_id": str(doc_row["doc_id"]), "content_sha256": cur, "name": SIG.SIGNER_NAME,
           "at": "2026-10-06T00:00:00+08:00", "scope": "document", "verdict": "accepted",
           "instance_id": "test", "inputs": {"doc_sha256": cur, "evidence_hashes": []},
           "basis": {"codes_checked": [], "finding_ids": [], "rounds": 1, "dimensions": []}}
    rec.update(patch)
    return SIG.append_signature(st.root, rec)


def _accepted_doc(st: Store) -> dict:
    """把夹具里那份稿件推成"H 审过"的形态，并给它签一条钉在现行版的签名。"""
    from agentflow import signatures as SIG

    with st.tx("documents", actor="test") as tx:
        row = dict(tx.rows("documents")[0])
        row["status"] = "accepted"
        row["content_sha256"] = SIG.content_sha256_of(row)
        tx.upsert("documents", row)
    _sign_doc(st, row)
    return row


def _revise_after_signoff(st: Store) -> dict:
    """模拟 `G.revise`：追加一条断言并把状态推成 `revised` —— 签名仍钉着改之前那一版。"""
    from agentflow import signatures as SIG

    with st.tx("documents", actor="test") as tx:
        row = dict(tx.rows("documents")[0])
        row["claims"] = list(row.get("claims") or []) + [{
            "claim_id": "claim-4", "text": "检索到的 7 篇文献（含 Wiles 模形式路线）构成立论依据。",
            "citations": ["lit:0000"], "evidence_kind": "heuristic", "section": "Open routes"}]
        row["status"] = "revised"
        row["review_rounds"] = 1
        row["revision"] = int(row.get("revision") or 1) + 1
        row["content_sha256"] = SIG.content_sha256_of(row)
        tx.upsert("documents", row)
    return row


def test_the_reviewed_current_kind_reads_whether_the_signature_covers_this_version(
        tmp_path: pathlib.Path):
    """判据（`draft/39` §6.46 的 D57）：这一档数的是"现行版有没有被审校记录钉住"。

    真机读数（T5 第 5 趟 `p8e-fermat-shorter-proof`）：H 判的是三条断言的旧版
    （签名钉 `e7346eb7…`），随后 G.revise 追加了第 4 条断言（现行版 `68bfc4c7…`）——
    收工门读的是 `status=revised`，于是那一条断言从未被任何一次审校看过，
    而七格全绿、`review_findings` 0 条。
    """
    from agentflow import closing as CL

    st, _report = _good(tmp_path)
    _accepted_doc(st)
    got, detail = CL._leg_reading(st, "reviewed_current_rows", tmp_path)
    assert got == 1, detail
    assert detail["claimed_reviewed"] == 1 and not detail["stale_signoffs"], detail
    assert detail["implicit_min"] == 1, detail

    _revise_after_signoff(st)
    got2, detail2 = CL._leg_reading(st, "reviewed_current_rows", tmp_path)
    assert got2 == 0, detail2
    assert detail2["stale_signoffs"], detail2
    stale = detail2["stale_signoffs"][0]
    assert stale["status"] == "revised" and stale["revision"] == 2, stale
    assert stale["current"] != (stale["signed"] or [""])[0], stale


def test_a_revision_after_the_signoff_turns_the_gate_red(tmp_path: pathlib.Path):
    """负控（D57 的核心）：改完之后没复核 ⇒ 收工门红，并点名两份哈希。

    改前这是静默的：状态是 `revised` ⇒ `reviewed_documents` 算"审过"、
    `verify_all` 的签名判据只对 `accepted` 成立（`SIGNABLE_STATUS`）⇒ 两处都看不见。
    """
    st, report = _good(tmp_path)
    _accepted_doc(st)
    _revise_after_signoff(st)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "稿件有裁决", "kind": "reviewed_documents", "min": 1},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "fail", rep.to_dict()
    detail = "；".join(f.detail for f in rep.blockers if f.check == "acceptance")
    assert "现行版本没有被审校记录钉住的稿件" in detail, detail
    assert "改完之后没再复核" in detail, detail
    assert "H.verify_fixes" in detail, detail
    # 那一行 `reviewed_documents` 自己是满的（status=revised）—— 红的是新这一档
    row = rep.readings["acceptance"]["rows"][0]
    assert row["id"] == "P1" and row["ok"] is True, row

    # 复核之后（签名钉到现行版上）门放行
    from agentflow import signatures as SIG

    with st.tx("documents", actor="test") as tx:
        row = dict(tx.rows("documents")[0])
    _sign_doc(st, row, verdict="accepted_with_warnings")
    rep2 = _gate(st, report)
    assert rep2.status["acceptance"] == "pass", rep2.to_dict()


def test_an_na_row_cannot_silence_an_automatic_branch(tmp_path: pathlib.Path):
    """E-04a（`draft/44` J-17）：给那四档写一行 `na` 不许关掉门的自动分支。

    真机形态（`draft/46-04` §2.1 的内存复算）：`p7b` +6 行、`p5-review-t17`/`p8g`
    各 +3 行 `na` ⇒ 旧门从 `fail` 读成 `pass`。

    这一条守的是"`na` 的语义边界"：`na` 是"这一行对这个项目天然不适用"（D49），
    不是"门不许问这件事"。所以本用例给 `reviewed_current_rows` 写一行 `na`，
    而那一档的自动分支（"现行版没有被审校记录钉住"）必须照旧报出来。
    """
    st, report = _good(tmp_path)
    _accepted_doc(st)
    _revise_after_signoff(st)          # 改完之后没复核 —— 缺陷是真的
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "稿件有裁决", "kind": "reviewed_documents", "min": 1},
        {"id": "P2", "name": "现行版复核", "kind": "reviewed_current_rows",
         "na": True, "note": "同事说这一版不用复核"},
    ], st=st)
    rep = _gate(st, report)

    assert rep.status["acceptance"] == "fail", rep.to_dict()
    detail = "；".join(f.detail for f in rep.blockers if f.check == "acceptance")
    assert "现行版本没有被审校记录钉住的稿件" in detail, detail
    assert "改完之后没再复核" in detail, detail
    # 那一行 `na` 自己仍然是"不适用"（三态没被改），读数里也如实留痕
    rows = {r["id"]: r for r in rep.readings["acceptance"]["rows"]}
    assert rows["P2"]["na"] is True and rows["P2"]["got"] is None, rows["P2"]
    assert rep.readings["acceptance"]["na_only_branch_kinds"] == ["reviewed_current_rows"], \
        rep.readings["acceptance"]


def test_the_four_auto_branches_read_the_ledger_not_the_table(tmp_path: pathlib.Path):
    """E-04a（`draft/46-04` §6.2 负控二）：四条自动分支统一从台账读，键名固定。

    四条分支各自认一个"键"：`stale_signoffs`（改完没复核）/ `empty_section_docs`（骨架稿）
    / `mismatches`（引文对不上）/ `derived_rows`（账本被模板灌满）。表里不写这四档时，
    门必须自己把它们从台账读出来（旧实现只在"表里没有该 kind"时跑，没有统一的四键）。
    """
    st, report = _good(tmp_path)
    _accepted_doc(st)
    _revise_after_signoff(st)
    _acceptance_checks(tmp_path, [
        {"id": "P1", "name": "稿件有裁决", "kind": "reviewed_documents", "min": 1},
    ], st=st)
    rep = _gate(st, report)

    detail = "；".join(f.detail for f in rep.blockers if f.check == "acceptance")
    # 门的自动分支真的从台账读到了缺陷（而不是只看"表里有没有这个 kind"）
    got, cur = CL._leg_reading(st, "reviewed_current_rows", tmp_path)
    assert cur["stale_signoffs"], cur
    assert got == 0, cur
    assert "现行版本没有被审校记录钉住的稿件" in detail, detail
    assert rep.readings["acceptance"]["na_only_branch_kinds"] == [], rep.readings["acceptance"]
    # 另三条分支的键由各自的档提供（同一份台账读法）：门对每一档都能说出"读到了什么"
    _g, body = CL._leg_reading(st, "document_body_rows", tmp_path)
    assert "empty_section_docs" in body, body
    fit = CL.citation_fit(st)
    assert "mismatches" in fit, fit
    _g2, ms = CL._leg_reading(st, "manuscript_rows", tmp_path)
    assert "derived_rows" in ms, ms


# ============================================================ E-04b / E-05 / EE-05 / EE-10 / C6


def test_a_group_covered_only_by_na_rows_is_reported_not_judged(tmp_path: pathlib.Path):
    """E-04b（`draft/52` C1）：整环只有 `na` 行 ⇒ 机器如实报出来，判断归 M/秘书。

    真机形态（`draft/49-03` 决策 1 逐格）：`p7b` 的 `B1`（`numeric_experiment_rows` + `na`）
    把「算或造」整个环节撑起来了 —— 那一环的成员一行都不在别处出现。

    判据有三条，缺一不可：
    1. 这一环不在 `missing` 里（读数级，不改覆盖面算法）；
    2. 它出现在 `na_only_groups` 里（看得见）；
    3. 门不因此判 `unknown`/`fail`（"算不算覆盖"是语义判断，归 M/秘书）。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "R1", "name": "立题", "kind": "research_question_rows", "min": 0,
         "note": "夹具里没有研究问题行，如实记 0"},
        {"id": "R2", "name": "算或造", "kind": "numeric_experiment_rows", "min": 0,
         "na": True, "note": "调查型任务，不做数值实验（如实标注）"},
    ], st=st)
    # 让覆盖面判据真的开火：这个项目要"是研究型"（有 research_questions 行）
    with st.tx("research_questions", actor="test") as tx:
        tx.upsert("research_questions", {"question_id": "0000", "question": "问题",
                                         "status": "open", "created_at": TS,
                                         "created_by": "test"})
    rep = _gate(st, report)

    chain = rep.readings["acceptance"]["research_chain"]
    assert chain["researched"] is True, chain
    assert "算或造" in chain["na_only_groups"], chain
    assert not any("算或造" in m for m in chain["missing"]), chain
    # 判断归 M/秘书：机器不因为"整环只有 na"就把这一格判成 unknown/fail
    assert rep.status["acceptance"] in ("pass", "fail"), rep.to_dict()
    assert "acceptance_chain_unreadable" not in [f.code for f in rep.findings]


def test_a_smaller_min_cannot_lower_the_kinds_own_threshold(tmp_path: pathlib.Path):
    """E-05 ①：阈值取大 —— 表里写 `min: 1` 而这一档自己算出来 3 ⇒ 生效的是 3。

    改前是"显式优先"（`closing.py:1213` 的注释逐字 `0 = 让这一档自己定阈值`）⇒
    写表的人可以把门槛压低（`draft/43-C` C-05）。真机 33 份表里
    `min` 与 `implicit_min` 不一致的行 = 0 ⇒ 这一改 0 处翻转。
    """
    st, report = _good(tmp_path)
    # `retrieval_ok_rows` 的缺省阈值 = `research_questions` 的行数
    with st.tx("research_questions", actor="test") as tx:
        for i in range(3):
            tx.upsert("research_questions", {"question_id": f"{i:04d}", "question": f"问题{i}",
                                             "status": "open", "created_at": TS,
                                             "created_by": "test"})
    with st.tx("search_requests", actor="test") as tx:
        tx.upsert("search_requests", {"request_id": "r-0001", "topic": "q", "mode": "broad",
                                      "timestamp": TS, "done": True,
                                      "outcome": "ok", "attempts": 1,
                                      "result_lit_ids": ["0000"],
                                      "submitted_by": "test"})
    _acceptance_checks(tmp_path, [
        {"id": "C2", "name": "检索真的取回", "kind": "retrieval_ok_rows", "min": 1},
    ], st=st)
    rep = _gate(st, report)

    row = rep.readings["acceptance"]["rows"][0]
    assert row["min"] == 3, row
    assert row["ok"] is False, row
    assert row["detail"]["min_overridden"] == {"declared": 1, "kind_min": 3, "effective": 3}, \
        row["detail"]
    assert rep.status["acceptance"] == "fail", rep.to_dict()


def test_the_acceptance_readings_carry_a_reading_version(tmp_path: pathlib.Path):
    """C6（`draft/52`）：口径必须可追溯 —— 读数里要有 `reading_version`。

    为什么（`draft/46-04` §6.4 第 1 条）：33 份表 / 204 行今天读出的 `got` 是
    旧口径下的数。每改一次口径（E-05 的分母、CC-05 的第四态、E-04a 的守卫）
    都必须说清"从哪一趟起口径变了" —— 没有版本号，两趟读数不同时无从判断差异
    来自"研究对象变了"还是"门的口径变了"。
    """
    st, report = _good(tmp_path)
    _acceptance_checks(tmp_path, [
        {"id": "P2", "name": "交付物在不在", "kind": "document_rows", "min": 1},
    ], st=st)
    rep = _gate(st, report)
    acc = rep.readings["acceptance"]
    assert acc["reading_version"] == CL.ACCEPTANCE_READING_VERSION, acc
    assert acc["reading_version"], "口径版本号不许是空串"
    assert acc["rows_read"] == 1 and acc["rows_na"] == 0 and acc["rows_not_applicable"] == 0, acc


def test_the_two_ledgers_share_one_reader(tmp_path: pathlib.Path):
    """EE-10（`draft/44` J-24）：两条台账只合并读法 —— `reviewed_current_rows` 如实标出它读哪一条。

    两条台账钉的是不同哈希空间（真机：`ARTIFACTS.jsonl` 的 `49404e4d…` vs
    `DOC-SIGNATURES.jsonl` 的 `dc8a062c…`）⇒ 本体不许合并；合并的是"怎么读 JSONL"
    那一层（`jsonlfile.read_jsonl`，`draft/36` T-6）。
    """
    from agentflow import artifacts as A
    from agentflow import jsonlfile as JF
    from agentflow import signatures as SIG

    assert SIG.read_jsonl is JF.read_jsonl and A.read_ledger.__module__ == "agentflow.artifacts"
    st, report = _good(tmp_path)
    _accepted_doc(st)
    _g, detail = CL._leg_reading(st, "reviewed_current_rows", tmp_path)
    assert detail["ledger_module"] == "signatures", detail
    assert detail["signature_ledger"].endswith(SIG.LEDGER_NAME), detail


def test_the_artifact_ledger_must_match_the_disk(tmp_path: pathlib.Path):
    """EE-05 第八格（`draft/52` C4）：产物台账与盘上不一致 ⇒ 这一格说得出是哪一种不一致。

    三档分开、强度不同（这是 C4 的核心，避免把正常产物读成坏）：

    - `missing`（登记过、盘上没了）/ `unreadable` ⇒ `fail`；
    - 只有 `changed`（登记之后又被正常改写）⇒ `unknown`（真机根 B 589 条 ≈18.75%）；
    - 全 `ok` ⇒ `pass`；台账不在盘上 ⇒ `pass` + 读数 `absent: true`（"没有这一栏"）。
    """
    from agentflow import artifacts as A

    st, report = _good(tmp_path)

    def _ledger(path: str, sha: str) -> None:
        with open(tmp_path / "ARTIFACTS.jsonl", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"path": path, "sha256": sha, "producer": "test",
                                 "at": TS}, ensure_ascii=False) + "\n")

    # ① 登记一条真的产物（sha 与盘上一致）⇒ pass
    good = tmp_path / "out" / "paper" / "main.tex"
    _ledger("out/paper/main.tex", A.sha256_of(good))
    rep = CL.check_closing(st, project_dir=str(tmp_path), report_path=str(report),
                           checks=("artifact_ledger",))
    assert rep.status["artifact_ledger"] == "pass", rep.to_dict()
    assert rep.readings["artifact_ledger"]["entries"] == 1, rep.readings

    # ② 同一条被改写（sha 变了）⇒ changed ⇒ pass + warning（D9，2026-10-09 裁"收窄"）
    #
    # 改前这一条断言的是 `unknown`（旧口径）——而真机 t1u 的 23 条 changed 全是框架自己
    # 幂等重写的 `out/tasks/*.json` ⇒ 任何有派活的跑批都收不了工。裁定之后：
    # 比对改成按路径取最后一条登记，而"最后一次登记之后又被改写"这一格记 pass，
    # 但这件事仍然以 warning + 阅读数可见（可见性一格不减）。
    good.write_text("改过了\n", encoding="utf-8")
    rep = CL.check_closing(st, project_dir=str(tmp_path), report_path=str(report),
                           checks=("artifact_ledger",))
    assert rep.status["artifact_ledger"] == "pass", rep.to_dict()
    assert rep.readings["artifact_ledger"]["changed"] == 1, rep.readings
    assert rep.blockers == [], [f.to_dict() for f in rep.blockers]
    assert [f.code for f in rep.findings] == ["artifact_ledger_changed_only"], rep.to_dict()
    assert rep.findings[0].level == "warning", rep.findings[0]

    # ③ 登记过、盘上没了 ⇒ missing ⇒ fail（同一个格，强度不同）
    _ledger("out/paper/NOPE.tex", "deadbeef")
    rep = CL.check_closing(st, project_dir=str(tmp_path), report_path=str(report),
                           checks=("artifact_ledger",))
    assert rep.status["artifact_ledger"] == "fail", rep.to_dict()
    assert rep.readings["artifact_ledger"]["missing"] == 1, rep.readings
    assert [f.code for f in rep.findings] == ["artifact_ledger_bad_rows"], rep.to_dict()

    # ④ 台账不在盘上 ⇒ pass + 读数写明"没有这一栏"（与 acceptance 对非研究型项目同口径）
    (tmp_path / "ARTIFACTS.jsonl").unlink()
    rep = CL.check_closing(st, project_dir=str(tmp_path), report_path=str(report),
                           checks=("artifact_ledger",))
    assert rep.status["artifact_ledger"] == "pass", rep.to_dict()
    assert rep.readings["artifact_ledger"]["absent"] is True, rep.readings


def test_the_ledger_compares_against_the_last_registration_per_path(tmp_path: pathlib.Path):
    """D9 正控（真机 t1u 的形态）：同一个路径登记两次（框架幂等重写 ⇒ 再登记一次）⇒
    按最后一条登记比 ⇒ `pass`，且不是 `changed`。

    改前的口径是"逐行比"：同一条 append-only 历史里的旧行永远对不上，
    于是 t1u 那 23 条框架自己重写的 `out/tasks/*.json` 把这一格读成 `unknown`
    （八格全 pass 因此不可能，任何有派活的跑批都收不了工）。
    """
    st, report = _good(tmp_path)
    p = tmp_path / "out" / "tasks" / "t-0002.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"n": 1}', encoding="utf-8")
    A = __import__("agentflow.artifacts", fromlist=["x"])
    led = tmp_path / "ARTIFACTS.jsonl"
    for body in ('{"n": 1}', '{"n": 2}'):
        p.write_text(body, encoding="utf-8")
        with led.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"path": "out/tasks/t-0002.json",
                                 "sha256": A.sha256_of(p), "producer": "framework",
                                 "at": TS}, ensure_ascii=False) + "\n")
    rep = CL.check_closing(st, project_dir=str(tmp_path), report_path=str(report),
                           checks=("artifact_ledger",))
    assert rep.status["artifact_ledger"] == "pass", rep.to_dict()
    rd = rep.readings["artifact_ledger"]
    assert rd["changed"] == 0 and rd["missing"] == 0, rd
    # 反真空：台账里确实是两行（append-only 历史还在），只是比对取最后一条
    assert sum(1 for _ in led.read_text(encoding="utf-8").splitlines()) == 2, rd


# ============================================================ 内容判据（D66 / D67 / T1 / T3）
#
# `draft/39` §6.49 八（用户 2026-10-06 裁「产出太保守」，行 3134-3140）之后，门多了五条
# 内容判据（`closing.content_leg_unmet`）：①「算」那一环要结论（D66 算半边）；
# ②「造」那一环要我方派生的命题（D66 造半边）；③ C 的产物要进交付面（D67）；
# ④ 逐字引文一条都没核到不算交付（T1 口径）；⑤ 论文要承载本轮结果（T3 口径）。
# 读数统一落在 `rep.readings["acceptance"]["content_branches"]`，句子落在 blocker 正文里。
#
# 下面六条与本文件开头那五条负控同一套纪律：每条都能单独造红，而且红绿两侧都测 ——
# 只测一侧的判据可能是一条恒真的判据。底座见 `_research_ready`。


def _acc_row(rep, row_id: str) -> dict:
    """验收读数里点名的那一行（找不到 ⇒ 判据自己接错了，不是"通过"）。"""
    return next(r for r in rep.readings["acceptance"]["rows"] if r["id"] == row_id)


def _acc_detail(rep) -> str:
    """`acceptance` 那一格的 blocker 正文（五条内容判据的句子都落在这里）。"""
    return "；".join(f.detail for f in rep.blockers if f.check == "acceptance")


def _valid_statement(store: Store, stmt_id: str, **kw) -> dict:
    """一条先过 `schema.Statement.validate` 再落库的命题行（内容判据的夹具用它）。

    为什么单列（而不是直接用 `_statement`）：内容判据读的正是 `origin` / `derived_from` /
    `quote_verified` 这几个字段，而"字段写在盘上"与"这一行合法"是两件事 ——
    先 validate 再落库，夹具就不会拿一行 schema 本来就拒收的形态去测判据。
    """
    row = {"stmt_id": stmt_id, "origin": "own_result", "kind": "theorem",
           "statement_full": "设 G 是 m-正则图；则……", "proof_text": "（逐步论证）",
           # `quote_verified is not True` 时 `Statement.validate` 要求非空理由。
           "quote_reason": "我方自产命题，没有外部引文要比对",
           "evidence_kind": "heuristic", "status": "active",
           "created_at": TS, "created_by": "test"}
    row.update(kw)
    S.Statement(**row).validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    sync_counters(store)
    return row


def _write_article(root: pathlib.Path, *, bibitems: int, cite_in: str) -> pathlib.Path:
    """写一份"像论文"的 `out/paper/main.tex`（T3 口径的判据对象）。

    `looks_like_article` 的口径是"含 `\\documentclass` 或 `\\begin{document}`"，
    所以这里必须真的像一篇论文（不是占位稿）：
    `cite_in="result"` ⇒ `exp:0001` 落在 `Results` 节（正控那一侧）；
    `cite_in="check"` ⇒ 只落在 `Evidence and status` 节（真机 T5 第 7 趟 `p6r` 的形态）。
    """
    lines = ["\\documentclass{article}", "\\begin{document}",
             "\\section{Introduction}", "本轮研究周期算子的谱隙与围长的关系。"]
    if cite_in == "result":
        lines += ["\\section{Results}", "本轮数值结果 exp:0001 给出了界 B 内的结论。"]
    else:
        lines += ["\\section{Evidence and status}", "核查读数：exp:0001 已登记，逐条见台账。"]
    lines.append("\\begin{thebibliography}{9}")
    lines += [f"\\bibitem{{K{i}}} 文献 {i}。" for i in range(bibitems)]
    lines += ["\\end{thebibliography}", "\\end{document}"]
    p = root / "out" / "paper" / "main.tex"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


#: 研究型项目"五条内容判据全过"的那份验收表：八环节各一行，而且读数都成立。
#:
#: 为什么不复用 `_FULL_COVER`：那一份是"覆盖面齐了、读数都是 0"（守的是"0 也是读数"）；
#: 这一份要的是一片本来就合规的工作区 —— 内容判据的负控只有在"别的都过"的底座上
#: 才能证明"红的是这一条"（与文件开头那五条负控同一条纪律）。
_RESEARCH_COVER: list[dict] = [
    {"id": "R1", "name": "立题", "kind": "research_question_rows", "min": 1,
     "note": "本轮立起了一个研究问题"},
    {"id": "R2", "name": "检索（真的取回）", "kind": "retrieval_ok_rows", "min": 1,
     "note": "一次检索成功取回了文献"},
    {"id": "R3", "name": "算（数值结论）", "kind": "numeric_experiment_rows", "min": 1,
     "note": "数值实验给出了带界的结论（D66：跑出结论才算）"},
    {"id": "R4", "name": "想", "kind": "conjecture_rows", "min": 1,
     "note": "登记了一条可检验的猜想"},
    {"id": "R5", "name": "看（关系分析）", "kind": "c_analysis_runs", "min": 1,
     "note": "派过 C 的关系分析"},
    {"id": "R6", "name": "攻（攻坚推进）", "kind": "attack_plan_rows", "min": 1,
     "note": "立了一份攻坚计划"},
    {"id": "R7", "name": "交（手稿落盘）", "kind": "document_rows", "min": 1,
     "note": "交付了一份稿件"},
    {"id": "R8", "name": "闭（请求闭环）", "kind": "unfinished_request_rows", "min": 0,
     "note": "队列里没有没做完的请求"},
]


def _research_ready(root: pathlib.Path, *, cover: list[dict] | None = None,
                    c_delivery: bool = True):
    """研究型工作区：`draft/39` §6.49 八 的五条内容判据本来就全过的底座。

    返回 `(store, report, root)`。底座里每一件东西都在回答"五条里有一条为什么需要它"
    （逐条写在 `seed` 的注释里）。`cover` 换掉 R3 那一档（构造腿那一组用
    `reviewed_proof_rows` 顶「算或造」）；`c_delivery=False` 抽掉 C 的产物（D67 的负控）。
    """
    def seed(s: Store) -> None:
        # ---- ①②：算那一环要结论 + 造那一环的派生目标。
        # `_t3_experiment` 是 formal + proof + 检查器原话 ⇒ `experiment_concludes` 为真
        # （它同时是 `load_bearing` 那一格要的 T3 背书）；`0002` 是被测的数值那一档：
        # `supports` + `search_bound` 才算"跑出结论"。
        _t3_experiment(s)
        _numeric_experiment(s, "0002", result="supports", search_bound={"n": 20})
        _valid_statement(s, "0000")
        # 交（手稿落盘）：一份带 proof 级断言的稿件，它引 exp:0001（那一条有 T3 背书）。
        _paper_with_claim(s)
        # ---- 研究链其余几环各一行的读数（覆盖面要八环节各一行、且每一行的读数都成立）。
        # 这几行都按 `schema` 那一行的形状写（`store.tx` 退出时 `validate_table` 会当场校验，
        # 写一行 schema 本来就拒收的形态是写不进去的）。
        with s.tx("research_questions", actor="test") as tx:
            tx.upsert("research_questions", {
                "question_id": "0000", "question": "这一族在界 B 内有没有反例？",
                "kind": "gap", "priority": "medium", "status": "open",
                "created_at": TS, "created_by": "test"})
        with s.tx("search_requests", actor="test") as tx:
            tx.upsert("search_requests", {
                "request_id": "r-0001", "topic": "上界族的最新进展", "mode": "broad",
                "timestamp": TS, "done": True, "outcome": "ok", "attempts": 1,
                "result_lit_ids": ["0000"], "submitted_by": "test"})
        with s.tx("conjectures", actor="test") as tx:
            tx.upsert("conjectures", {
                "conjecture_id": "0000", "statement": "对每个 n≥3 都有 c(G) ≤ 1。",
                "form": "universal", "testable": {"bounds": {"n": 20}},
                "status": "proposed", "origin": "gap",
                "created_at": TS, "created_by": "test"})
        with s.tx("attack_plans", actor="test") as tx:
            tx.upsert("attack_plans", {
                "plan_id": "0000", "problem": "把界推到 n ≤ 20 需要新的构造",
                "problem_key": "bound-n20", "status": "open",
                "budget": {"max_rounds": 2, "max_parallel_subgoals": 2,
                           "max_persist_attempts": 2, "max_depth": 1},
                "subgoals": [], "history": [], "created_at": TS, "created_by": "test"})
        # ---- ③ 看（关系分析）：C 跑过一次（`tasks` 里 role=C 且跑过的行）。
        # 这一行同时会让 D67 那条判据生效 ⇒ 底座默认把产物也送进交付面。
        with s.tx("tasks", actor="test") as tx:
            tx.upsert("tasks", {
                "task_id": "t-0001", "role": "C", "action": "hottest", "called_by": "M",
                "status": "done", "outcome": "ok", "detail": "跑了一次最热关系分析",
                "started_at": TS, "ended_at": TS})
        with s.tx("relations", actor="test") as tx:
            tx.upsert("relations", {
                "relation_id": "0000", "concept_ids": ["0000", "0001"],
                "description": "c(G) 与谱隙同向", "lit_id": "0000",
                "page_range": {"start": 1, "end": 2}, "created_at": TS})
        if c_delivery:
            # ---- ③（续）C 的产物进交付面：手稿引一条 `rel:` 编号（D67 的两条出口之一）。
            from agentflow import manuscripts as MS

            MS.write(root, sender="M", recipient="ALL", summary="C 的关系读数进交付面",
                     body="本轮 C 跑出 rel:0000（hottest 关系），据此交接。",
                     refs=["rel:0000"])

    st = _project(root, seed=seed)
    _acceptance_checks(root, list(cover or _RESEARCH_COVER), st=st)
    report = _write_report(root)
    return st, report, root


def test_numeric_experiment_rows_needs_a_conclusion_not_just_a_run(tmp_path: pathlib.Path):
    """D66 算半边（`draft/39` §6.49 八 第一条）：这一档数「跑出结论」而不是「跑过」。

    旧口径只数 `method="numeric"` 的行 —— 真机 T2 `p6q` 是 10 条实验全 `inconclusive`，
    读数照样是 10 ⇒「算」那一环变绿。新口径 = `experiment_concludes`：`result` 是
    `supports` / `refutes`，且（`search_bound` 或 `certificate` 非空；
    形式化那一支看 `verifier_output`）。

    两侧（先红后绿，改的是同一行）：
    - 红：那条数值实验改成 `inconclusive`（跑过、没结论）⇒ 这一档 `got == 0`、该行不成立；
    - 绿：改回 `supports` + `search_bound` ⇒ `got == 1`，整格 `pass`。
    """
    st, report, ws = _research_ready(tmp_path)
    green = _gate(st, report)
    assert green.status["acceptance"] == "pass", green.to_dict()
    assert _acc_row(green, "R3")["got"] == 1, _acc_row(green, "R3")

    _numeric_experiment(st, "0002", result="inconclusive")   # 跑过、没结论
    _seal(ws, st)
    red = _gate(st, report)
    row = _acc_row(red, "R3")
    assert red.status["acceptance"] == "fail", red.to_dict()
    assert row["got"] == 0 and row["ok"] is False, row
    assert row["detail"]["numeric_rows"] == 1 and row["detail"]["conclusive"] == 0, row["detail"]
    assert row["detail"]["inconclusive_ids"] == ["0002"], row["detail"]
    # 这一格不是"没查成"：读数在（分母 `numeric_rows` 照留），只是结论没了
    assert "R3" in _acc_detail(red), _acc_detail(red)

    _numeric_experiment(st, "0002", result="supports", search_bound={"n": 20})
    _seal(ws, st)
    back = _gate(st, report)
    assert back.status["acceptance"] == "pass", back.to_dict()
    assert _acc_row(back, "R3")["got"] == 1, _acc_row(back, "R3")


def test_the_calculate_stage_reports_when_no_experiment_concludes(tmp_path: pathlib.Path):
    """D66 算半边：整环没有结论时，门自己把话说出来（不是等着人写进验收表）。

    与上一条的分工：上一条测 `numeric_experiment_rows` 这一档的读数换口径；
    这一条测 `content_leg_unmet` 的第 ① 条判据本身。触发条件三条同时成立：项目是研究型
    （有 `research_questions` 行）+ 验收表里真的声明了「算或造」那一组的档 + `experiments`
    有行 —— 缺任何一条都不判（调查型项目 T4 的清单不声明算/造，`na` 也关不掉它）。

    两侧：
    - 红：两条实验都改成 `inconclusive` ⇒ blocker 正文含「「算」那一环没有结论」；
    - 绿：让其中一条带界地支持 ⇒ 那句话消失，整格回到 `pass`。
    """
    st, report, ws = _research_ready(tmp_path)
    _t3_experiment(st, "0001", result="inconclusive")
    _numeric_experiment(st, "0002", result="inconclusive")
    _seal(ws, st)
    red = _gate(st, report)

    detail = _acc_detail(red)
    assert red.status["acceptance"] == "fail", red.to_dict()
    assert "「算」那一环没有结论" in detail, detail
    leg = red.readings["acceptance"]["content_branches"]["compute_leg"]
    assert leg["experiments"] == 2 and leg["conclusive"] == 0, leg
    assert leg["inconclusive"] == 2 and sorted(leg["inconclusive_ids"]) == ["0001", "0002"], leg
    assert leg["researched"] is True and leg["declared"] is True, leg

    # 绿：补一条"界内的支持" ⇒ 这一环有结论（两条实验都回到 base 的形态）
    _t3_experiment(st, "0001")
    _numeric_experiment(st, "0002", result="supports", search_bound={"n": 20})
    _seal(ws, st)
    green = _gate(st, report)
    assert green.status["acceptance"] == "pass", green.to_dict()
    assert "「算」那一环没有结论" not in _acc_detail(green), _acc_detail(green)
    leg2 = green.readings["acceptance"]["content_branches"]["compute_leg"]
    assert leg2["conclusive"] == 2 and leg2["inconclusive"] == 0, leg2


def test_the_construct_stage_needs_an_own_derived_statement(tmp_path: pathlib.Path):
    """D66 造半边（`draft/39` §6.49 八 第二条）：声明了「造」那一环的项目要有我方派生产物。

    只在 `computed_kinds` 含 `reviewed_proof_rows` / `counterexample_or_proof_rows` 时判
    （只走数值那一腿的项目不受这一条约束）：`statements` 里 `origin="own_result"` 的行，
    至少要有一行写清它派生于什么（`derived_from` 或 `source_lit_id` 非空）——
    「造」= 我方自己提出并证明的命题，而且来路要能被复核。

    两侧：
    - 红：我方命题 `0003`（有证明过程 + 审过）没有 `derived_from` ⇒ blocker 含
      「「造」那一环没有我方派生的命题」，读数 `construct_leg.with_basis == 0`；
      而 R3（`reviewed_proof_rows`）照样成立 ⇒ 红的是内容判据这一条，不是那一行的读数；
    - 绿：给它 `derived_from=["0000"]`（`0000` 是同夹具里已登记的命题号）⇒ 那句话消失、
      `with_basis == 1`，整格 `pass`。
    """
    cover = [dict(r) for r in _RESEARCH_COVER]
    cover[2] = {"id": "R3", "name": "造（我方判决性证据）", "kind": "reviewed_proof_rows",
                "min": 1, "note": "我方命题走到了预备定理级"}
    st, report, ws = _research_ready(tmp_path, cover=cover)
    bits = {"proof": True, "reviewed": True,
            "evidence": {"proof_source": "own", "proof_process": "（逐步论证）",
                         "reviewed_by": {"round": "V-0001", "verdict": "no_defect"}}}
    _valid_statement(st, "0003", bits=bits)
    _seal(ws, st)
    red = _gate(st, report)

    detail = _acc_detail(red)
    assert red.status["acceptance"] == "fail", red.to_dict()
    assert "「造」那一环没有我方派生的命题" in detail, detail
    assert _acc_row(red, "R3")["got"] == 1, _acc_row(red, "R3")
    leg = red.readings["acceptance"]["content_branches"]["construct_leg"]
    assert leg["own_result"] == 2 and leg["with_basis"] == 0, leg

    # 绿：把"派生于什么"写上去（`0000` 已登记）
    _valid_statement(st, "0003", bits=bits, derived_from=["0000"])
    _seal(ws, st)
    green = _gate(st, report)
    assert green.status["acceptance"] == "pass", green.to_dict()
    assert "「造」那一环没有我方派生的命题" not in _acc_detail(green), _acc_detail(green)
    leg2 = green.readings["acceptance"]["content_branches"]["construct_leg"]
    assert leg2["own_result"] == 2 and leg2["with_basis"] == 1, leg2


def test_a_rel_ref_carries_c_analysis_into_the_delivery(tmp_path: pathlib.Path):
    """D67（`draft/39` §6.49 八 第三条）：C 的关系分析跑过 ⇒ 产物至少要能被交付物引到。

    真机读数（T5 第 7 趟 `p8g-fermat-shorter-proof`）：`tasks` 里 role=C 四行 `done`
    （`hottest` / `contradictions` / `gaps` / `cold`）、`relations` 107 行，而
    `analysis_reports` 0 行、手稿 `refs` 里一条 `rel:` 都没有 —— C 是那几趟里唯一产出真
    知识的角色，产物却被扔掉了。两条出口（任一成立就算进交付面）：手稿/文档断言里引一条
    `rel:`，或 `analysis_reports` 有行。

    两侧：
    - 红：C 跑过而交付面一条 `rel:` 都没有 ⇒ blocker 含「产物一条都没进交付面」，
      读数 `c_delivery.c_analysis_runs == 1` / `manuscript_rel_refs == []` /
      `analysis_reports == 0`；
    - 绿：手稿引一条 `rel:0000`（那条关系行在册）⇒ 那句话消失，整格 `pass`。
    """
    st, report, ws = _research_ready(tmp_path, c_delivery=False)
    red = _gate(st, report)

    detail = _acc_detail(red)
    assert red.status["acceptance"] == "fail", red.to_dict()
    assert "产物一条都没进交付面" in detail, detail
    face = red.readings["acceptance"]["content_branches"]["c_delivery"]
    assert face["c_analysis_runs"] == 1, face
    assert face["manuscript_rel_refs"] == [] and face["document_rel_refs"] == [], face
    assert face["analysis_reports"] == 0, face

    from agentflow import manuscripts as MS

    MS.write(ws, sender="M", recipient="ALL", summary="C 的关系读数进交付面",
             body="本轮 C 跑出 rel:0000（hottest 关系），据此交接。", refs=["rel:0000"])
    _seal(ws, st)
    green = _gate(st, report)
    assert green.status["acceptance"] == "pass", green.to_dict()
    assert "产物一条都没进交付面" not in _acc_detail(green), _acc_detail(green)
    face2 = green.readings["acceptance"]["content_branches"]["c_delivery"]
    assert any(str(r).endswith(":rel:0000") for r in face2["manuscript_rel_refs"]), face2


def test_unretrieved_quotes_alone_do_not_satisfy_the_citation_leg(tmp_path: pathlib.Path):
    """T1 口径（`draft/39` §6.49 八 第四条）：「哪几条没查到」本身不是交付。

    触发条件三条同时成立：只读基线 `source/main.tex` 存在且含 `\\bibitem`、
    台账里 `origin="external_lit"` 的行数 > 0、而这些行里一条 `quote_verified=True`
    都没有。只看 `external_lit`：我方自产命题（`own_result`）本来就没有外部原文可比对，
    把它算进来会把"自己证的定理"读成"没核到的引文"。

    两侧：
    - 红：三条 `external_lit` 记录全停在"未查 / 不一致" ⇒ blocker 含「逐字引文一条都没
      核到」，读数 `quote_verification.citation_rows == 3` / `verified == 0` /
      `baseline_bibitems == 3`；
    - 绿：其中一条改成 `quote_verified=True` + 逐字理由 ⇒ 那句话消失、`verified == 1`，
      整格 `pass`。
    """
    st, report, ws = _research_ready(tmp_path)
    (ws / "source").mkdir(parents=True, exist_ok=True)
    (ws / "source" / "main.tex").write_text(
        "\\documentclass{article}\n" + "".join(f"\\bibitem{{K{i}}}\nX\n" for i in range(3)),
        encoding="utf-8")
    _valid_statement(st, "0001", origin="external_lit", source_lit_id="0000",
                     quote_verified=False,
                     quote_reason="与原文不一致（英文转述 vs 中文原文）")
    for i in (2, 3):
        _valid_statement(st, f"{i:04d}", origin="external_lit", source_lit_id="0000",
                         quote_reason="原文不在盘上 ⇒ 未查")
    _seal(ws, st)
    red = _gate(st, report)

    detail = _acc_detail(red)
    assert red.status["acceptance"] == "fail", red.to_dict()
    assert "逐字引文一条都没核到" in detail, detail
    quote = red.readings["acceptance"]["content_branches"]["quote_verification"]
    assert quote["baseline_bibitems"] == 3, quote
    assert quote["citation_rows"] == 3 and quote["verified"] == 0, quote
    assert quote["unverified_ids"] == ["0001", "0002", "0003"], quote
    # 有只读基线 ⇒ T3 口径那一条不判它（那一档只在"从结果写论文"的工作区上说话）
    assert "paper_leg" not in red.readings["acceptance"]["content_branches"], \
        red.readings["acceptance"]["content_branches"]

    # 绿：留一条真的核到的（逐字比对通过）
    _valid_statement(st, "0003", origin="external_lit", source_lit_id="0000",
                     quote_verified=True, quote_reason="逐字比对通过（第 1 页）")
    _seal(ws, st)
    green = _gate(st, report)
    assert green.status["acceptance"] == "pass", green.to_dict()
    assert "逐字引文一条都没核到" not in _acc_detail(green), _acc_detail(green)
    quote2 = green.readings["acceptance"]["content_branches"]["quote_verification"]
    assert quote2["verified"] == 1 and quote2["citation_rows"] == 3, quote2


def test_the_paper_must_carry_this_rounds_results(tmp_path: pathlib.Path):
    """T3 口径（`draft/39` §6.49 八 第五条）：论文要承载本轮结果。

    只在"从结果写论文"的形态上判（没有只读基线 `source/main.tex`），且只判真的像论文的稿子
    （`looks_like_article`：含 `\\documentclass` / `\\begin{document}`）—— T1 那一类审阅项目
    的 `out/paper/main.tex` 是被审的稿件本身，它的参考文献与引用形态由原稿决定。
    两条判据：① `\\bibitem` ≥ 2；② 正文里 `stmt:` / `exp:` / `rel:` 引用不能只出现在
    核查章节里（真机 `p6r`：那一篇 5 节里 `exp:0008` 只出现在 `Evidence and status` 节）。

    两侧：
    - 红：1 条 `\\bibitem` + `exp:0001` 只写在 `Evidence and status` 节 ⇒ blocker 同时含
      「论文的参考文献只有」与「核查章节」；
    - 绿：2 条 `\\bibitem` + `exp:0001` 写在 `Results` 节 ⇒ 两句话都消失，整格 `pass`。
    """
    st, report, ws = _research_ready(tmp_path)
    _write_article(ws, bibitems=1, cite_in="check")
    _seal(ws, st)
    red = _gate(st, report)

    detail = _acc_detail(red)
    assert red.status["acceptance"] == "fail", red.to_dict()
    assert "参考文献只有" in detail and "核查章节" in detail, detail
    paper = red.readings["acceptance"]["content_branches"]["paper_leg"]
    assert paper["looks_like_article"] is True and paper["bibitems"] == 1, paper
    assert paper["result_sections"] == [], paper
    assert paper["check_citations"] == ["exp:0001"], paper

    _write_article(ws, bibitems=2, cite_in="result")
    _seal(ws, st)
    green = _gate(st, report)
    assert green.status["acceptance"] == "pass", green.to_dict()
    detail2 = _acc_detail(green)
    assert "参考文献只有" not in detail2 and "核查章节" not in detail2, detail2
    paper2 = green.readings["acceptance"]["content_branches"]["paper_leg"]
    assert paper2["bibitems"] == 2 and paper2["result_citations"] == ["exp:0001"], paper2

