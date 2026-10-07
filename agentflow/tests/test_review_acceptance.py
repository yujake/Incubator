# -*- coding: utf-8 -*-
"""审稿场景的内容级验收（`draft/37` §17.3 的 ①②③④⑤）+ 一条最重要的反真空。

## 这一组守什么

§17.3 把验收写成两半：该验的五条内容级判据，以及逐字禁止拿来当"通过"的五种读数
（`sha 变了` / `页数对得上` / `锚 consistent` 单项 / `任务数增加` / `台账行数增加`）。
判据文件里最容易漏的是第二半 —— 那些信号跑一次就变，很容易拿到，
于是"验收"会不知不觉退化成"看它们变了没有"。

所以这里最要紧的一条是 `test_pretty_auxiliary_signals_cannot_fake_a_pass`：
把五种辅助读数全部造得漂亮（正文改过、PDF 页数对得上、锚 `consistent`、任务行与台账行都增加），
而内容级判据不合格 ⇒ `passed` 必须仍为假。
"""
from __future__ import annotations

import json
import pathlib

from conftest import TS, sync_counters
from agentflow import renderanchor as RA
from agentflow import reviewaccept as RX
from agentflow import schema as S
from agentflow import userio as U
from agentflow.store import Store


# ============================================================ 夹具

def _stmt(store: Store, sid: str, **kw) -> dict:
    base = dict(stmt_id=sid, origin="external_lit", kind="theorem", label=f"Theorem {sid}",
                statement_text="短版", statement_full="若假设 A 成立，则结论 B 成立",
                proof_text="Proof. 逐字摘录……", source_lit_id="0000",
                page_range=S.PageRange(start=7, end=8, label="pp. 7-8"),
                quote_verified=True, quote_reason="逐字比对通过", evidence_kind="cross_check",
                status="active", created_at=TS)
    base.update(kw)
    row = S.Statement(**base)
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sync_counters(store)
    return row.to_dict()


#: M 声明的体例（R9 之后体例归 M，门不自带任何节名清单）。
#:
#: 这份清单是测试里的 M 声明的：写进 `out/review/REPORT-STYLE.json`，
#: 由 `closing._check_report_shape` 逐节核它有没有兑现。它与 `closing` 不再有任何关系
#: —— 这正是 R9 要的：门不许自带一份"报告该有哪几节"（那是 review 线的排版规格）。
STYLE_SECTIONS: tuple[str, ...] = (
    "一、任务与范围", "二、逐条读数", "三、定理与引理清单", "四、形式化覆盖",
    "五、引文核验", "六、体例与表述", "七、我们做的补救", "八、未决问题", "九、诚实边界",
)


def _report(root: pathlib.Path, *, empty_section: str = "") -> pathlib.Path:
    """M 声明体例 + 照它写一份九节报告（`empty_section` 指定哪一节写成空标题）。

    报告的形状只由 M 的声明决定：这里同时落下 `REPORT-STYLE.json`
    （声明）与报告本体（兑现），门核的是两者是否一致。
    """
    p = root / "out" / "review" / "REPORT.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 审核报告", ""]
    for i, name in enumerate(STYLE_SECTIONS, 1):
        num = name.split("、", 1)[0]
        lines.append(f"## {num}、{name.split('、', 1)[1]}")
        if num == empty_section:
            lines.append("（本节待补）")
        else:
            # 每一节都要有读数；引用一个「真的存在」的台账行（`draft/37` §70 之后，
            # 报告里的引用会被核 —— 夹具引用不存在的行，红的就是夹具体例而不是被测代码）。
            lines.append(f"读数：{i} 条，见 statements:0001 与 page_range pp. 7-8。")
        lines.append("")
    # 附件三件套（`closing.report_shape` 判实：来源 / 依据 / 版本 sha）——
    # 它不是排版，是"这条结论是不是我们自己做的、依据在哪、文件有没有被换过"。
    lines += ["附件：origin=own_result；依据读数见 §四；版本 sha256=deadbeef。", ""]
    p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    (p.parent / "REPORT-STYLE.json").write_text(
        json.dumps({"sections": list(STYLE_SECTIONS)}, ensure_ascii=False),
        encoding="utf-8", newline="\n")
    return p


def _task(store: Store, tid: str, **kw) -> dict:
    base = dict(task_id=tid, role="B", action="run_once", called_by="M", depth=2,
                input_key="阿贝尔群", status="done", outcome="ok", detail="消化了一条定理",
                started_at=TS, ended_at=TS, created_at=TS)
    base.update(kw)
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", base)
    return base


def _usage(store: Store, uid: str, usd: float | None) -> None:
    """一行花销账（`at` 必填 —— 没有时间戳的账目无法按时间对账）。"""
    with store.tx("usage_ledger", actor="test") as tx:
        tx.upsert("usage_ledger", {"usage_id": uid, "scope": "reason", "role": "B",
                                   "task_id": "t-0001", "tokens_in": 10, "tokens_out": 10,
                                   "tokens_total": 20, "usd": usd, "attempts": 1,
                                   "at": TS, "note": "test", "prompt_version": "p24"})


def _seal(root: pathlib.Path, st: Store) -> None:
    out = root / "out" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    (out / "main.tex").write_text("\\date{2026-01-01}\nbody\n", encoding="utf-8")
    (out / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    (out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)), encoding="utf-8")
    (out / RA.RECEIPT_NAME).write_text(json.dumps(RA.build_receipt(
        out, tex_sha256=RA.file_digest(out / "main.tex"), pages=21, markers_missing=[],
        pdf_bytes=13, compiler_exit_codes=[0])), encoding="utf-8")


def _good(tmp_path: pathlib.Path):
    """五条全过的那个工作区。

    工作区根 = 项目根（`data/` 与 `out/paper/` 在同一个根下，与真项目一致）：
    早先把 store 放在子目录里，`_auxiliary` 就读不到 `out/paper/main.tex` 与锚了。
    """
    st = Store(tmp_path)
    st.init()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0000", title="Brown 1971", type="J",
                                             summary="室图", path=None, added_at=TS).to_dict())
    _stmt(st, "0001")
    _task(st, "t-0001")
    _usage(st, "0001", 0.25)
    sync_counters(st)
    q = U.ask_user(st.root, role="M", question="「审」还是「研」？", timeout_sec=0.0, qid="q0001")
    assert q.problem == "user_no_answer", q
    assert U.answer_question(st.root, qid="q0001", answer="审") == ""
    report = _report(tmp_path)
    _seal(tmp_path, st)
    return st, report


def _check(st, report, **kw):
    return RX.check_review(st, project_dir=str(st.root), report_path=str(report),
                           cost_cap_usd=kw.pop("cap", 1.0), **kw)


# ============================================================ 正控

def test_a_content_complete_review_passes(tmp_path):
    """正控：内容齐（台账有假设与出处、报告九节都有读数、问过并答过、在成本内、每跳有输入）。"""
    st, report = _good(tmp_path)
    acc = _check(st, report)
    assert acc.passed and not acc.failed, acc.to_dict()
    assert "五条内容级判据全过" in acc.summary()


# ============================================================ 五条负控（各自单独红）

def test_the_report_shape_criterion_lives_in_exactly_one_module(tmp_path):
    """R9（`draft/52` 裁决 1 = C''）：报告形状判据只住一个模块，而且不再自带节名。

    三件事一起判（这条是 R9 的负控，改前必红）：

    ① `reviewaccept` 里不许再有 `report_sections_have_readings` 这条判据
       （它连同 `closing.REPORT_SECTIONS` / `SPLIT_MARKERS` 一起废除）；
    ② `closing` 里不许再有自带节名清单（`REPORT_SECTIONS` / `SPLIT_MARKERS` 都没了）；
    ③ 门对报告形状说话的落点是M 声明的体例（`REPORT-STYLE.json`）。
    """
    import pathlib

    from agentflow import closing as CL
    from agentflow import reviewaccept as RX

    assert not hasattr(CL, "REPORT_SECTIONS"), "九节清单还在 closing 里（R9 要求废除）"
    assert not hasattr(CL, "SPLIT_MARKERS"), "分栏标记还在 closing 里（R9 要求废除）"
    assert not hasattr(RX, "_c_report"), "九节判据的实现还在 reviewaccept 里（R9 要求连同删掉）"
    assert "report_sections_have_readings" not in {k for k, _ in RX.CRITERIA}
    assert "report_sections_have_readings" not in RX.ReviewAcceptance().criteria
    assert CL.REPORT_STYLE_NAME.endswith("REPORT-STYLE.json")

    # 反真空：体例声明真的被门读、且只读声明的那几节
    st, report = _good(tmp_path)
    (report.parent / "REPORT-STYLE.json").write_text(
        json.dumps({"sections": ["一、任务与范围", "二、逐条读数"]}, ensure_ascii=False),
        encoding="utf-8", newline="\n")
    rep = CL.check_closing(st, project_dir=str(st.root),
                           report_path=str(report), checks=("report_shape",))
    assert rep.status["report_shape"] == "pass", rep.to_dict()
    assert rep.readings["report_shape"]["declared_sections"] == ["一、任务与范围", "二、逐条读数"]
    assert rep.readings["report_shape"]["missing_declared_sections"] == []


def test_the_report_shape_is_not_judged_when_m_declares_nothing(tmp_path):
    """R9 的另一半：M 没声明体例 ⇒ 门不判体例（读数里如实写 `none`）。

    这不是"通过"，是"这一趟没有体例声明"：读数 `style_source: "none"` 说得清。
    """
    from agentflow import closing as CL

    st, report = _good(tmp_path)
    (report.parent / "REPORT-STYLE.json").unlink()
    rep = CL.check_closing(st, project_dir=str(st.root),
                           report_path=str(report), checks=("report_shape",))
    assert rep.status["report_shape"] == "pass", rep.to_dict()
    rd = rep.readings["report_shape"]
    assert rd["style_source"] == "none" and rd["declared_sections"] == []
    # 附件三件套仍然判实（它不是排版）
    assert rd["missing_attachment_fields"] == []


def test_m_s_declared_style_is_judged_section_by_section(tmp_path):
    """R9：M 声明了体例 ⇒ 逐节核它有没有兑现（缺一节就是这一条红）。"""
    from agentflow import closing as CL

    st, report = _good(tmp_path)
    (report.parent / "REPORT-STYLE.json").write_text(
        json.dumps({"sections": list(STYLE_SECTIONS) + ["十、M 自己加的一节"]},
                   ensure_ascii=False),
        encoding="utf-8", newline="\n")
    rep = CL.check_closing(st, project_dir=str(st.root),
                           report_path=str(report), checks=("report_shape",))
    assert rep.status["report_shape"] == "fail", rep.to_dict()
    assert rep.readings["report_shape"]["missing_declared_sections"] == ["十、M 自己加的一节"]
    assert [f.code for f in rep.blockers] == ["report_incomplete"]


def test_a_statement_without_a_page_range_fails(tmp_path):
    """负控②：命题有假设、有出处，但没有页码 ⇒ 红（§14.4 第三条要"出处页码"）。"""
    st, report = _good(tmp_path)
    _stmt(st, "0002", page_range=S.PageRange())
    _seal(tmp_path, st)
    acc = _check(st, report)
    assert acc.criteria["statements_have_assumptions_and_source"] == "fail", acc.to_dict()
    assert any("page_range" in b for b in acc.readings["statements_missing_fields"]), acc.readings


def test_an_empty_ledger_is_not_compliance(tmp_path):
    """负控②′：台账一条 active 命题都没有 ⇒ 红（空台账不是合规，是没做）。"""
    st = Store(tmp_path / "ws")
    st.init()
    _task(st, "t-0001")
    _usage(st, "0001", 0.1)
    report = _report(tmp_path)
    _seal(tmp_path, st)
    acc = _check(st, report)
    assert acc.criteria["statements_have_assumptions_and_source"] == "fail", acc.to_dict()
    assert "没有交出内容" in acc.details["statements_have_assumptions_and_source"]


def test_an_unanswered_question_blocks_the_triage_branch(tmp_path):
    """负控③：问题落盘了但没人回答 ⇒ 红（正确分支是停在"等待用户"）。"""
    st, report = _good(tmp_path)
    U.ask_user(st.root, role="M", question="这条要不要换一篇来源？", timeout_sec=0.0, qid="q0002")
    acc = _check(st, report)
    assert acc.criteria["triage_branch_recorded"] == "fail", acc.to_dict()
    assert "等待用户" in acc.details["triage_branch_recorded"]


def test_never_asking_is_unknown_not_pass(tmp_path):
    """反真空（三态）：一次都没问过用户 ⇒ `unknown`，不是通过。

    这一条挡的是本判据最容易退化的方向：把"没有问题"当成"该问的都问了"。
    """
    st, report = _good(tmp_path)
    # 把那条问答从会话记录里"抹掉"：换一个干净的会话根
    fresh = tmp_path / "ws2"
    fresh.mkdir()
    acc = RX.check_review(st, project_dir=str(st.root), report_path=str(report),
                          session_root=fresh, cost_cap_usd=1.0)
    assert acc.criteria["triage_branch_recorded"] == "unknown", acc.to_dict()
    assert not acc.passed


def test_costing_over_the_cap_fails_and_the_blind_spot_is_declared(tmp_path):
    """负控④：超上限 ⇒ 红。外加一条盲区证据：账本表达不了"花销算不出来"。

    `tokenmeter._row_for` 永远写一个 float `usd` ⇒ schema 会拒 `usd=None`。
    于是"这次调用算不出价钱"在账本上看起来就是零元。
    这一条把这个盲区钉成可执行的证据（而不是一句注释）：它写不进去，
    所以判据只能说"账本上的合计没超"，说不出"这一轮没有漏记的花销"。
    """
    st, report = _good(tmp_path)
    acc = _check(st, report, cap=0.10)
    assert acc.criteria["within_cost_cap"] == "fail", acc.to_dict()
    assert "超过" in acc.details["within_cost_cap"] or ">" in acc.details["within_cost_cap"]

    # 盲区：一行"算不出花销"的账写不进 schema —— 而且它不是一句校验异常，
    # 是 `UsageEntry.validate` 里 `self.usd < 0` 撞上 None 的 TypeError
    # （`schema.py` 是禁改区 ⇒ 这条只登记、由人裁；判据只把形态钉住）。
    import pytest as _pytest

    with _pytest.raises(TypeError):
        _usage(st, "0002", None)
    # 而 `_c_cost` 的读数里必须明说这个盲区
    assert "看不见" in acc.readings["cost"]["blind_spot"], acc.readings["cost"]


def test_a_hop_without_an_input_key_fails(tmp_path):
    """负控⑤：成功的召唤没有 `input_key` ⇒ 红（说不清"派下去的是什么"）。"""
    st, report = _good(tmp_path)
    _task(st, "t-0002", input_key="")
    acc = _check(st, report)
    assert acc.criteria["hops_have_readable_prompts"] == "fail", acc.to_dict()
    assert acc.readings["hops"]["without_input_key"] == ["t-0002"], acc.readings["hops"]


def test_a_report_citing_a_row_that_does_not_exist_fails(tmp_path):
    """负控⑥（`draft/37` §70 的真机形态）：报告点名一条盘上没有的台账行 ⇒ 红。

    第十四趟真机：六条判据全绿、`closing.can_close=True`，而交付说明里写着
    "4 条登记进 `statements`（0000–0003）"、表格里逐行给 `statements 0001/0002/0003`
    —— 台账里只有 0000。这一条钉住"引用悬空"这一格。
    """
    st, report = _good(tmp_path)
    with report.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n| Theorem 1.2 | 三个族的 exactness | 第 107–131 行 | statements 0042 |\n")
    acc = _check(st, report)
    assert acc.criteria["attachment_is_honest"] == "fail", acc.to_dict()
    assert acc.readings["attachment"]["dangling_refs"] == ["statements 0042"], acc.readings
    assert "引用的台账行不存在" in acc.details["attachment_is_honest"], acc.details
    assert not acc.passed


def test_dangling_reference_check_does_not_fire_on_page_numbers(tmp_path):
    """负控（不许变成噪音）：页码、行号区间、年份这些「裸数字」不许被当成台账引用。

    报告里到处都是 "第 88–105 行"、"pp. 7-8"、"P1–P6"、"split 2026" 这样的数字；
    判据只认「带前缀」的 4 位号（`statements 0001` / `lit:0000` / `doc 0000`），
    否则它每天都会红，而红成常态的判据等于没有判据。
    """
    st, report = _good(tmp_path)
    with report.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n第 88–105 行、pp. 7-8、P1–P6、split 2026、0007 与 9999 都是裸数字。\n")
    acc = _check(st, report)
    assert acc.readings["attachment"]["dangling_refs"] == [], acc.readings["attachment"]
    assert acc.criteria["attachment_is_honest"] != "fail", acc.details


def test_a_report_citing_existing_rows_is_not_flagged(tmp_path):
    """正控：引用真的存在的行（含 `lit:0000` 写法）⇒ 不报悬空。

    注意上面那句"documents 0000 未建"「不能」写成 `documents 0000` —— 这一格对
    `documents` 一样生效（夹具里没有 documents 行，写了就会被判悬空；
    第一版这条判据就是这么红了一次，红得对）。
    """
    st, report = _good(tmp_path)
    with report.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n来源：lit:0000 第 7–8 页（statements 0001；我方稿件本轮没建 documents 行）。\n")
    acc = _check(st, report)
    assert acc.readings["attachment"]["dangling_refs"] == [], acc.readings["attachment"]


# ============================================================ 最重要的反真空

def test_pretty_auxiliary_signals_cannot_fake_a_pass(tmp_path):
    """§17.3 逐字禁止的那五种读数一起变漂亮，也不许把不合格说成通过。

    做法：内容级判据全部弄坏（报告有一节空标题 + 一条命题缺页码 + 有未答问题），
    同时把那五种辅助信号全部造得"漂亮"：正文改过（sha 变了）、PDF 在盘上（页数读得到）、
    锚 `consistent`、任务行与台账行数都增加。
    判据：`passed` 必须仍为假，且辅助读数确实是漂亮的
    —— 两者同时成立才说明"分栏"是真的分了。
    """
    st, report = _good(tmp_path)
    _report(tmp_path, empty_section="七")
    _stmt(st, "0002", page_range=S.PageRange())
    U.ask_user(st.root, role="M", question="要不要重取?", timeout_sec=0.0, qid="q0009")
    _task(st, "t-0003")
    _task(st, "t-0004")
    with st.tx("concepts", actor="test") as tx:
        tx.upsert("concepts", S.Concept(concept_id="0000", name="室图", definition="d",
                                        created_at=TS).to_dict())
    (tmp_path / "out" / "paper" / "main.tex").write_text("改过了\n", encoding="utf-8")
    _seal(tmp_path, st)                         # 重封锚 ⇒ 锚 consistent（漂亮）

    acc = _check(st, report, cap=10.0)
    # 辅助读数确实漂亮
    assert acc.auxiliary["anchor_verdict"] == "consistent", acc.auxiliary
    assert acc.auxiliary["tex_sha256"], acc.auxiliary
    assert acc.auxiliary["task_rows"] >= 3 and acc.auxiliary["ledger_rows"] >= 1, acc.auxiliary
    # 页数是辅助读数里最脆的一个：夹具的 PDF 是假的（`%PDF-1.4 fake`，没有真页）
    # ⇒ `page_count` 如实返回 None，不编一个数。这恰好演示了辅助读数的性质：
    # 它可读可不读，而无论读得到读不到，都不该参与"通过"。
    assert acc.auxiliary["pdf_pages"] is None, acc.auxiliary
    # 而内容级判据仍然不合格 ⇒ 不许通过
    assert not acc.passed, acc.to_dict()
    assert set(acc.failed) == {"statements_have_assumptions_and_source",
                               "triage_branch_recorded"}, acc.failed
    assert "不构成通过" in acc.summary()


def test_missing_inputs_are_unknown_not_pass(tmp_path):
    """三态：没给报告路径 / 没给成本上限 ⇒ `unknown`，而 `unknown` 不算通过。"""
    st, _report_path = _good(tmp_path)
    acc = RX.check_review(st, project_dir="", report_path="", cost_cap_usd=None)
    assert acc.criteria["within_cost_cap"] == "unknown", acc.to_dict()
    assert acc.criteria["attachment_is_honest"] == "unknown", acc.to_dict()
    assert not acc.passed
    assert acc.auxiliary["anchor_verdict"] == "", acc.auxiliary
    # R9：报告形状这条判据已废除 ⇒ 它不该再出现在 `criteria` 里（连 `unknown` 都不许）
    assert "report_sections_have_readings" not in acc.criteria


# ============================================================ R25：附件诚实（两条负控）

def test_an_attachment_claiming_a_literature_source_fails(tmp_path):
    """R25 负控①（来源造假）：把我们补的手稿写成"文献补充" ⇒ 红。

    这一条与下一条必须分开报：来源造假的处置是改正标注，过度声称的处置是
    降档或补 T3 —— 两件事的接手人不同。
    """
    st, report = _good(tmp_path)
    with report.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n七、我们做的补救：文献补充——定理 1.5 取自 Brown 1971。\n")
    acc = _check(st, report)
    assert acc.criteria["attachment_is_honest"] == "fail", acc.to_dict()
    assert "文献补充" in acc.readings["attachment"]["forgery_markers"], acc.readings
    assert "来源造假" in acc.details["attachment_is_honest"]


def test_claiming_resolved_while_t3_is_missing_fails(tmp_path):
    """R25 负控②（过度声称）：写了"已解决"，而收工门仍说承重结论缺 T3 ⇒ 红。

    这一条演示的是"两条判据互相咬"：措辞的诚实由证据状态裁定，不由措辞自己裁定。
    """
    st, report = _good(tmp_path)
    # 把那条承重断言设成 proof 级，而台账里没有任何 T3 形态的实验行
    with st.tx("documents", actor="test") as tx:
        doc = S.Document(doc_id="0001", kind="paper", title="未发表的论文", status="in_review",
                         claims=[{"claim_id": "c1", "text": "已证明定理 1.5",
                                  "citations": ["lit:0000"], "evidence_kind": "proof",
                                  "section": "§2"}], created_at=TS)
        doc.validate()
        tx.upsert("documents", doc.to_dict())
    sync_counters(st)
    with report.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n八、未决问题：形式化覆盖缺口已解决。\n")
    acc = _check(st, report)
    assert acc.readings["attachment"]["load_bearing"] == "fail", acc.to_dict()
    assert acc.criteria["attachment_is_honest"] == "fail", acc.to_dict()
    assert "过度声称" in acc.details["attachment_is_honest"]

    # 反真空：把那条断言如实降档之后，"已解决"这句话就不再是过度声称
    with st.tx("documents", actor="test") as tx:
        row = dict(st.rows("documents")[0])
        row["claims"][0]["evidence_kind"] = "cross_check"
        row["claims"][0]["disclaimer"] = "数值交叉验证，不构成证明"
        tx.upsert("documents", row)
    acc2 = _check(st, report)
    assert acc2.readings["attachment"]["load_bearing"] == "pass", acc2.to_dict()
    assert acc2.criteria["attachment_is_honest"] == "pass", acc2.to_dict()


def test_the_top_run_row_is_not_counted_as_a_hop(tmp_path):
    """判据（A 线 F1 + 主控 2026-10-06 裁定）：顶趟行不算一次召唤。

    顶趟行 = 用户发起的那一趟（`role=M` / `action="run"` / `called_by="user"` /
    `depth=1` / `input_key="top:…"`）。`hops`/`ok_tasks` 数的是委托，
    把它算进去会让"派了几跳 / 成了几跳"凭空 +1。

    改前必红：旧判据只按 `status=="done" and outcome=="ok"` 过滤 ⇒ 造一条顶趟行
    之后 `ok_tasks` 从 N 变 N+1。改后：`ok_tasks` 不变，且读数里留下
    `excluded_top_run_rows == 1`（排除本身可见，不许静默滤掉）。
    """
    st, report = _good(tmp_path)
    before = _check(st, report)
    hops_before = before.readings["hops"]
    assert hops_before["excluded_top_run_rows"] == 0, hops_before

    _task(st, "t-0009", role="M", action="run", called_by="user", depth=1,
          input_key="top:用户发起的那一趟")
    after = _check(st, report)
    hops_after = after.readings["hops"]
    assert hops_after["ok_tasks"] == hops_before["ok_tasks"], (hops_before, hops_after)
    assert hops_after["excluded_top_run_rows"] == 1, hops_after
    assert "顶趟行" in hops_after["note"], hops_after
    assert after.criteria["hops_have_readable_prompts"] == "pass", after.to_dict()


def test_a_top_run_row_without_an_input_key_does_not_fail_the_hop_criterion(tmp_path):
    """反真空：顶趟行缺 `input_key` 也不许把这一格判红（它根本不是一次召唤）。

    没有这一条，"排除顶趟行"很容易写成"只在算数时减一、判据仍然看全表"。
    """
    st, report = _good(tmp_path)
    _task(st, "t-0010", role="M", action="run", called_by="user", depth=1, input_key="")
    acc = _check(st, report)
    assert acc.criteria["hops_have_readable_prompts"] == "pass", acc.to_dict()
    assert acc.readings["hops"]["excluded_top_run_rows"] == 1, acc.readings["hops"]
