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


def _report(root: pathlib.Path, *, empty_section: str = "") -> pathlib.Path:
    """九节报告：默认每节都带读数；`empty_section` 指定哪一节写成空标题。"""
    p = root / "out" / "review" / "REPORT.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 审核报告", ""]
    for i, (num, name) in enumerate(RX_SECTIONS(), 1):
        lines.append(f"## {num}、{name}")
        if num == empty_section:
            lines.append("（本节待补）")
        else:
            # 每一节都要有读数；引用一个「真的存在」的台账行（`draft/37` §70 之后，
            # 报告里的引用会被核 —— 夹具引用不存在的行，红的就是夹具体例而不是被测代码）。
            lines.append(f"读数：{i} 条，见 statements:0001 与 page_range pp. 7-8。")
        lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return p


def RX_SECTIONS() -> tuple[tuple[str, str], ...]:
    """九节（从 `closing.REPORT_SECTIONS` 取 —— 两处各写一份迟早分家）。"""
    from agentflow import closing as CL

    return CL.REPORT_SECTIONS


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

def test_an_empty_report_section_fails_even_though_the_report_exists(tmp_path):
    """负控①：报告在盘上、九节标题都在，但其中一节是空标题 ⇒ 红。

    这一条正对着"报告文件存在"这种容易拿到的信号 —— §17.3 要的是"每栏有读数"。
    """
    st, report = _good(tmp_path)
    _report(tmp_path, empty_section="五")      # 第五节写成空标题
    _seal(tmp_path, st)                        # 改文件后重封锚（锚只作辅助，但别让它噪音）
    acc = _check(st, report)
    assert acc.criteria["report_sections_have_readings"] == "fail", acc.to_dict()
    assert acc.readings["report_sections_without_readings"] == ["五、引文核验"], acc.readings
    assert not acc.passed


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
    assert set(acc.failed) == {"report_sections_have_readings",
                               "statements_have_assumptions_and_source",
                               "triage_branch_recorded"}, acc.failed
    assert "不构成通过" in acc.summary()


def test_missing_inputs_are_unknown_not_pass(tmp_path):
    """三态：没给报告路径 / 没给成本上限 ⇒ `unknown`，而 `unknown` 不算通过。"""
    st, _report_path = _good(tmp_path)
    acc = RX.check_review(st, project_dir="", report_path="", cost_cap_usd=None)
    assert acc.criteria["report_sections_have_readings"] == "unknown", acc.to_dict()
    assert acc.criteria["within_cost_cap"] == "unknown", acc.to_dict()
    assert acc.criteria["attachment_is_honest"] == "unknown", acc.to_dict()
    assert not acc.passed
    assert acc.auxiliary["anchor_verdict"] == "", acc.auxiliary


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
