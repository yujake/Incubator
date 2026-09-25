"""`gates`（H 的 G1–G15）的门测试：每道门一正一反，外加四条结构纪律。

对应规格：`draft/17-正式文稿体例（参考投影度量论）.md` §8.4（第 1054–1074 行）。

## 这个文件要证明的四件事（§8.4 最值得抄的四条制度）

1. 每道门都能返回"没做"：缺输入 ⇒ `unknown` + reason，不是 `pass`。
   参考体例的教训逐字是"多数脚本不设退出码，于是『未报错』被误读为『无问题』"
   （`draft/17-…md:675-676`）。
2. 零发现必须自证（G13）：结构强制 —— 缺自证的 `GateResult` 构造不出来。
3. 报告必须钉住被审版本 hash（G11），且报告里必须有"我这一轮犯的错"（G15）。
4. 15 个门号齐全，每个门号都能单独查询到它的结论（不许合并掉门号）。
"""

from __future__ import annotations

import json

import pytest

from agentflow import claimanatomy as CA
from agentflow import gates as G
from agentflow.agent_h import AgentH
from agentflow.store import Store
from agentflow.tools import doc_tools as DT
from agentflow.tools import review_tools as RV

from conftest import TS


# ============================================================ 夹具


def claim(**over: object) -> dict:
    """一条 12 字段齐全、且在每个轴上都自洽的断言。"""
    base = {
        "claim_id": "claim-1",
        "kind": "定理",
        "statement": "谱落在区间内。",
        "status": "证",
        "proof_location": "code/p1.py:12",
        "numeric_evidence": {
            "script": "code/p1.py", "range": "d<=33", "n_cases": 256, "n_counterexamples": 0,
        },
        "counterexamples": [],
        "frozen": False,
        "freeze_reason": "",
        "allowed_use": "主结果",
        "scope_caveat": "",
        "revision_hash": "deadbeefdeadbeef",
        "errata_ids": [],
        "evidence_kind": "proof",
        "citations": ["rel:0000"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
        "section": "主要结果",
    }
    base.update(over)
    return base


def doc(claims: list[dict] | None = None, **over: object) -> dict:
    base = {
        "doc_id": "0000",
        "kind": "paper",
        "title": "门测试稿件",
        "markdown_path": "documents/0000.md",
        "claims": claims if claims is not None else [claim()],
        "open_problems": [],
        "status": "draft",
        "review_rounds": 0,
        "created_at": TS,
        "updated_at": TS,
    }
    base.update(over)
    return base


@pytest.fixture
def ws(tmp_path):
    """一个带 `code/p1.py` 与 `documents/0000.md` 的最小工作区。"""
    root = tmp_path / "ws"
    (root / "code").mkdir(parents=True)
    (root / "documents").mkdir(parents=True)
    (root / "code" / "p1.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "documents" / "0000.md").write_text("# 稿件\n", encoding="utf-8")
    return root


def full_ctx(ws, **over):
    """一个所有输入都齐的上下文（于是能验证"全绿"这一侧）。"""
    kw = {
        "dependencies": [],
        "files": ["code/p1.py"],
        "workspace_root": ws,
        "run_evidence": {
            "checked": True,
            "commands": [{"claim_id": "claim-1", "command": "python code/p1.py", "output_tail": "ALL CHECKS PASS"}],
        },
        "findings": [
            {
                "finding_id": "0000", "kind": "overclaim", "level": "error", "target": "claim-1",
                "line": 12, "verbatim_quote": "已证明", "minimal_fix": "改成『交叉验证』",
                "maths": "yes", "axis": "证据", "message": "m", "evidence": "e",
            }
        ],
        "claim_counts": {"declared_claim_count": 1, "declared_counterexample_count": 0, "declared_script_count": 1},
        "banned_words": ["显然"],
        "own_errors": [],
    }
    kw.update(over)
    return G.GateContext.build(doc(), **kw)


# ============================================================ 1. 15 道门都在


def test_gates_declares_all_fifteen_ids():
    """声明表里 G1–G15 一个都不许少（删门会让"15 道门都在跑"变成假话）。"""
    assert G.GATE_IDS == tuple(f"G{i}" for i in range(1, 16))
    assert G.known_gate_ids() == G.GATE_IDS
    assert set(G.GATES) == set(G.GATE_IDS)
    assert len(G.GATES) == 15


def test_every_gate_can_be_queried_on_its_own(ws):
    """每个门号都能单独查询到结论（而不是只能拿一整张报告）。"""
    ctx = full_ctx(ws)
    for gid in G.GATE_IDS:
        r = G.run_gate(gid, ctx)
        assert isinstance(r, G.GateResult), gid
        assert r.gate_id == gid
        assert r.verdict in ("pass", "fail", "unknown", "not_applicable")
        assert r.criterion.strip() and r.axis in G.AXES
        assert isinstance(r.findings, tuple)
        for f in r.findings:
            assert f.get("evidence", "").strip(), f"{gid} 的发现没带证据"


def test_every_gate_has_a_known_name_axis_criterion_and_script():
    """每道门都要有名字、轴、判据、"照搬哪个脚本"与失败处置。"""
    for gid, spec in G.GATES.items():
        assert spec["name"].strip(), gid
        assert spec["axis"] in G.AXES, gid
        assert spec["criterion"].strip(), gid
        assert spec["script"].strip(), gid
        assert spec["on_failure"].strip(), gid
        assert callable(spec["checker"]), gid
        assert gid in G.GATE_CRITERIA_REVISION, f"{gid} 没有登记判据修订状态"


def test_unknown_gate_id_is_rejected():
    """负控：不许自造门号（G16 之类）——门号清单是规格，不是实现细节。"""
    with pytest.raises(ValueError, match="未知门号"):
        G.run_gate("G16", G.GateContext.build(doc()))


def test_gate_result_rejects_an_unknown_verdict():
    """负控：`verdict` 只许四态；"没查成"不许被写成第五种含糊值。"""
    with pytest.raises(ValueError, match="verdict"):
        G.GateResult(
            gate_id="G1", name="n", axis="工程", criterion="c", verdict="maybe", reason="r",
        )


def test_unknown_and_fail_must_carry_a_reason():
    """负控：判 `unknown`/`fail`/`not_applicable` 却不说理由 ⇒ 构造不出来。"""
    for verdict in ("fail", "unknown", "not_applicable"):
        with pytest.raises(ValueError, match="没说理由"):
            G.GateResult(
                gate_id="G1", name="n", axis="工程", criterion="c", verdict=verdict, reason="  ",
            )


# ============================================================ 2. 零发现自证（G13，结构强制）


def test_zero_findings_without_attestation_cannot_be_constructed():
    """G13 的结构强制：`pass` + 零发现 + 无自证 ⇒ 对象根本构造不出来。

    这条是"缺一个就是 H 自己的格式违规"的机器形态 —— 它不是靠 G13 事后发现，
    而是让不合规的报告对象无法存在。
    """
    with pytest.raises(ValueError, match="零发现"):
        G.GateResult(
            gate_id="G2", name="引用解析门", axis="证据", criterion="c",
            verdict="pass", reason="没有坏引用", findings=(),
        )
    # 有过程但没有数字 ⇒ 同样不合规
    with pytest.raises(ValueError, match="数字"):
        G.GateResult(
            gate_id="G2", name="引用解析门", axis="证据", criterion="c",
            verdict="pass", reason="没有坏引用", findings=(),
            self_attestation="我扫了一遍", counts={},
        )


def test_attest_requires_both_process_and_numbers():
    """负控：自证块缺过程或缺数字 ⇒ 抛。"""
    with pytest.raises(G.GatesReportError, match="过程"):
        G.attest("", {"扫描的引用数": 3})
    with pytest.raises(G.GatesReportError, match="数字"):
        G.attest("扫了一遍", {})


def test_every_zero_finding_gate_carries_numbers(ws):
    """正控：全绿上下文里，凡报零发现的门都带自证数字（G13 通过）。"""
    ctx = full_ctx(ws, findings=[], banned_words=["显然"])
    results = G.run_all_gates(ctx)
    zero = [gid for gid, r in results.items() if r.verdict == "pass" and not r.findings and gid != "G13"]
    assert zero, "夹具应当至少让一道门报零发现（否则本用例测不到东西）"
    for gid in zero:
        assert results[gid].self_attestation.strip(), gid
        assert results[gid].counts, gid
    assert results["G13"].verdict == "pass"


def test_g13_rejects_a_gate_that_claims_zero_findings_without_numbers(ws):
    """负控：伪造一个"零发现但没自证"的门结果 ⇒ G13 必须报 error。"""
    ctx = full_ctx(ws)
    results = G.run_all_gates(ctx)
    forged = G.GateResult(
        gate_id="G2", name="引用解析门", axis="证据", criterion="c",
        verdict="pass", reason="没有坏引用",
        # 绕过构造期校验的办法：先构造一个合法的，再替换字段（模拟"从别处塞进来"）
        self_attestation="x", counts={"a": 1},
    )
    object.__setattr__(forged, "self_attestation", "")
    object.__setattr__(forged, "counts", {})
    results["G2"] = forged
    g13 = G.gate_g13(ctx, results)
    assert g13.verdict == "fail"
    assert any("零发现" in f["message"] for f in g13.findings)
    assert any(f["target"] == "G2" for f in g13.findings)


def test_findings_without_evidence_cannot_be_constructed():
    """负控：发现不带 `evidence` ⇒ 构造不出来（审校者的判断也要有证据）。"""
    with pytest.raises(ValueError, match="evidence"):
        G.GateResult(
            gate_id="G2", name="引用解析门", axis="证据", criterion="c",
            verdict="fail", reason="有坏引用",
            findings=({"gate": "G2", "severity": "error", "target": "claim-1", "message": "m"},),
        )


# ============================================================ 3. 三态：缺输入 = unknown


def test_g8_reports_unknown_when_there_is_no_run_evidence(ws):
    """G8 的标本用例："本轮实跑过"这件事门自己查不出来 ⇒ 必须 unknown。

    库里没有实跑输出时判 `pass`，就是把"没报错"读成了"没问题"——
    参考体例逐字记录了那个坑（`draft/17-…md:675-676`）。
    """
    ctx = G.GateContext.build(doc(), workspace_root=ws, dependencies=[])
    r = G.run_gate("G8", ctx)
    assert r.verdict == "unknown"
    assert "无法判定" in r.reason
    assert "未提供" in r.counts["本轮实跑记录"] or r.counts["本轮实跑记录"] == "未提供"
    # 显式声明"本轮没跑"也必须是 unknown（不是 fail：没做 ≠ 做失败）
    ctx2 = full_ctx(ws, run_evidence={"checked": False, "reason": "本轮只审格式，没跑数值"})
    r2 = G.run_gate("G8", ctx2)
    assert r2.verdict == "unknown"
    assert "没查" in r2.reason
    # 真跑了且覆盖了 ⇒ 才可能 pass
    r3 = G.run_gate("G8", full_ctx(ws))
    assert r3.verdict == "pass"


def test_g8_fails_when_a_numeric_claim_has_no_command(ws):
    """负控：有数值断言但本轮实跑记录没覆盖它 ⇒ error（阻断）。"""
    ctx = full_ctx(ws, run_evidence={"checked": True, "commands": []})
    r = G.run_gate("G8", ctx)
    assert r.verdict == "fail"
    assert r.findings and r.findings[0]["target"] == "claim-1"


def test_g9_reports_unknown_without_declared_counts(ws):
    """G9：没有"另一个文件"可对账 ⇒ 判不了一致性（单看一处数字永远不能说一致）。"""
    ctx = full_ctx(ws, claim_counts=None)
    r = G.run_gate("G9", ctx)
    assert r.verdict == "unknown"
    assert "判不了一致性" in r.reason


def test_g9_rejects_a_count_drift(ws):
    """负控：声明的计数与实际不一致 ⇒ error（§1.4 的十处漂移同族）。"""
    ctx = full_ctx(ws, claim_counts={"declared_claim_count": 3})
    r = G.run_gate("G9", ctx)
    assert r.verdict == "fail"
    assert any("计数" in f["message"] for f in r.findings)


def test_g11_reports_unknown_without_the_previous_hash(ws):
    """G11："钉住 hash" ≠ "验证审校期间没被改过" —— 两者必须分开。"""
    ctx = full_ctx(ws, observed_hash=None)
    r = G.run_gate("G11", ctx)
    assert r.verdict == "unknown"
    assert r.counts["被审版本 hash"]
    assert "判不了" in r.reason


def test_g11_rejects_a_changed_revision(ws):
    """负控：审校期间稿件被改（hash 不匹配）⇒ error，本次审校结论作废。"""
    ctx = full_ctx(ws, observed_hash="0000000000000000")
    r = G.run_gate("G11", ctx)
    assert r.verdict == "fail"
    assert "在审校期间被改过" in r.reason


def test_g11_passes_when_the_hash_still_matches(ws):
    """正控：上一轮的 hash 与本轮重算一致 ⇒ pass（冻结成立）。"""
    ctx0 = full_ctx(ws)
    ctx = full_ctx(ws, observed_hash=ctx0.revision_hash)
    r = G.run_gate("G11", ctx)
    assert r.verdict == "pass"
    assert r.counts["是否冻结"] is True


def test_g1_reports_unknown_without_a_workspace():
    """G1：没有工作区 ⇒ 判不了"在不在包内"（没查，不是"都在包内"）。"""
    ctx = G.GateContext.build(doc(), dependencies=[])
    r = G.run_gate("G1", ctx)
    assert r.verdict == "unknown"
    assert "workspace_root" in r.reason


def test_g6_reports_not_applicable_when_nothing_is_numeric(ws):
    """G6：一条数值证据都没点名 ⇒ 没有对象可判 ⇒ not_applicable（不是 pass）。"""
    plain = claim()
    plain.pop("numeric_evidence")
    ctx = G.GateContext.build(doc([plain]), workspace_root=ws, dependencies=[])
    r = G.run_gate("G6", ctx)
    assert r.verdict == "not_applicable"
    assert "没有可判定的对象" in r.reason


def test_g5_is_not_applicable_without_a_word_list(ws):
    """G5：本项目故意不在代码里写死禁词表 ⇒ 缺词表判 not_applicable + 说清原委。"""
    ctx = full_ctx(ws, banned_words=None)
    r = G.run_gate("G5", ctx)
    assert r.verdict == "not_applicable"
    assert "banned_words" in r.reason


def test_g5_flags_a_banned_word_with_context(ws):
    """负控：命中禁词必须带上下文（供人工裁），不是一句"有问题"。"""
    ctx = full_ctx(ws, banned_words=["谱"])
    r = G.run_gate("G5", ctx)
    assert r.verdict == "fail"
    assert "谱" in r.findings[0]["evidence"]


def test_no_doc_gates_report_unknown():
    """负控：连稿件都没给 ⇒ 每道依赖稿件的门都必须是 unknown（不许 pass）。

    上下文里显式给了 `own_errors=[]`，否则 G15 会（正确地）判 fail
    —— 那样总体结论会是 `rejected`，就测不到"缺对象 ⇒ unknown"这条了。
    """
    ctx = G.GateContext.build(None, own_errors=[])
    results = G.run_all_gates(ctx)
    for gid in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G11", "G12", "G14"):
        assert results[gid].verdict == "unknown", gid
    assert G.gate_verdict(results)["verdict"] == "unverified"


# ============================================================ 4. 逐门正/负


def test_g1_accepts_paths_inside_and_rejects_paths_outside(ws):
    """G1：工作区内的路径通过；工作区外的路径阻断交付。"""
    inside = full_ctx(ws, files=["code/p1.py"])
    assert G.run_gate("G1", inside).verdict == "pass"

    outside = full_ctx(ws, files=["../outside/secret.py"])
    r = G.run_gate("G1", outside)
    assert r.verdict == "fail"
    assert any("工作区" in f["message"] for f in r.findings)


def test_g2_accepts_resolvable_citations_and_rejects_broken_ones(ws):
    """G2：前缀可解析 ⇒ pass；空前缀/空代号 ⇒ fail（阻断交付）。"""
    ok = full_ctx(ws)
    assert G.run_gate("G2", ok).verdict == "pass"

    broken = full_ctx(ws)
    broken.doc = doc([claim(citations=[":0007"])])
    r = G.run_gate("G2", broken)
    assert r.verdict == "fail"
    assert r.counts["扫描的引用数"] == 1


def test_g2_warns_but_does_not_block_on_an_unknown_prefix(ws):
    """G2 的"假阳性须逐条留痕"档：未知前缀报 warning（不阻断），但留痕。"""
    ctx = full_ctx(ws)
    ctx.doc = doc([claim(citations=["bib:0007"])])
    r = G.run_gate("G2", ctx)
    assert r.verdict == "pass"
    assert r.findings and r.findings[0]["severity"] == "warning"


def test_g3_accepts_self_reference_and_rejects_a_dangling_proof_location(ws):
    """G3：`proof_location` 指向本文档内的 claim_id（允许自指）⇒ pass；否则 fail。"""
    ctx = full_ctx(ws)
    ctx.doc = doc([claim(claim_id="claim-1", proof_location="claim-1")])
    assert G.run_gate("G3", ctx).verdict == "pass"

    ctx2 = full_ctx(ws)
    ctx2.doc = doc([claim(proof_location="«见某处»")])
    r = G.run_gate("G3", ctx2)
    assert r.verdict == "fail"
    assert "cross-references" not in r.reason  # 中文理由
    assert "无法解析" in r.reason


def test_g4_rejects_a_missing_markdown_file_and_a_count_drift(ws):
    """G4：账本点名的文件必须存在；声明的断言数必须对得上。"""
    ok = full_ctx(ws)
    assert G.run_gate("G4", ok).verdict == "pass"

    missing = full_ctx(ws)
    missing.doc = doc(markdown_path="documents/nope.md")
    r = G.run_gate("G4", missing)
    assert r.verdict == "fail"
    assert any("不存在" in f["message"] for f in r.findings)

    drift = full_ctx(ws, claim_counts={"declared_claim_count": 5})
    r2 = G.run_gate("G4", drift)
    assert r2.verdict == "fail"


def test_g6_rejects_a_missing_script_and_accepts_an_existing_one(ws):
    """G6（虚证门）：点名的脚本必须存在；通配符必须至少命中一个文件。"""
    ok = full_ctx(ws)
    assert G.run_gate("G6", ok).verdict == "pass"

    fake = full_ctx(ws)
    fake.doc = doc([claim(numeric_evidence={"script": "code/ghost.py", "range": "d<=3", "n_cases": 1, "n_counterexamples": 0})])
    r = G.run_gate("G6", fake)
    assert r.verdict == "fail"
    assert any("虚证" in f["message"] for f in r.findings)

    wildcard = full_ctx(ws)
    wildcard.doc = doc([claim(numeric_evidence={"script": "code/*.py", "range": "d<=3", "n_cases": 1, "n_counterexamples": 0})])
    assert G.run_gate("G6", wildcard).verdict == "pass"

    no_hit = full_ctx(ws)
    no_hit.doc = doc([claim(numeric_evidence={"script": "code/*.lean", "range": "d<=3", "n_cases": 1, "n_counterexamples": 0})])
    assert G.run_gate("G6", no_hit).verdict == "fail"


def test_g7_rejects_a_numeric_claim_without_a_ledger_row(ws):
    """G7（台账完整门）：正文像数值断言却没有 `numeric_evidence` ⇒ "仅泛证型" ⇒ 阻断。"""
    ok = full_ctx(ws)
    assert G.run_gate("G7", ok).verdict == "pass"

    bare = claim()
    bare.pop("numeric_evidence")
    bare["status"] = "验"
    ctx = full_ctx(ws)
    ctx.doc = doc([bare])
    r = G.run_gate("G7", ctx)
    assert r.verdict == "fail"
    assert any("仅泛证" in f["message"] for f in r.findings)


def test_g10_reports_unknown_when_findings_lack_the_reference_columns(ws):
    """G10 的实测缺口：`schema.ReviewFinding` 没有 line/verbatim_quote/minimal_fix/maths。

    处置是保留门 + 如实报 unknown（不是删门，也不是判 pass）——
    删门会让"15 道门都在跑"变成假话。
    """
    ctx = full_ctx(ws, findings=[{"finding_id": "0000", "kind": "overclaim", "level": "error", "target": "c", "evidence": "e"}])
    r = G.run_gate("G10", ctx)
    assert r.verdict == "unknown"
    assert "不可判定" in r.reason
    assert r.findings, "缺哪些字段必须逐条列出来（不是一句『不合格』）"


def test_g10_passes_when_the_findings_have_all_six_columns(ws):
    """正控：发现字段齐全时，G10 才可能 pass（闸门不是永远关着的）。"""
    ctx = full_ctx(ws)
    assert G.run_gate("G10", ctx).verdict == "pass"


def test_g10_rejects_a_quote_longer_than_twenty_words(ws):
    """负控：逐字引文超过 20 词 ⇒ 打回（参考体例的格式判据）。"""
    long_quote = " ".join(f"w{i}" for i in range(21))
    ctx = full_ctx(ws, findings=[{
        "finding_id": "0000", "kind": "overclaim", "level": "error", "target": "c",
        "line": 1, "verbatim_quote": long_quote, "minimal_fix": "f", "maths": "yes", "evidence": "e",
    }])
    r = G.run_gate("G10", ctx)
    assert r.verdict == "fail"
    assert any("20 词" in f["message"] for f in r.findings)


def test_g12_requires_a_counterexample_search_for_proved_claims(ws):
    """G12（反方门）：标了"证"却没有反例搜索痕迹 ⇒ warning（"没搜过"≠"没有反例"）。"""
    ctx = full_ctx(ws)
    bare = claim()
    bare.pop("numeric_evidence")
    bare.pop("counterexamples")
    ctx.doc = doc([bare])
    r = G.run_gate("G12", ctx)
    assert r.verdict == "pass"
    assert any("反例搜索的痕迹" in f["message"] for f in r.findings)
    assert r.counts["有反例搜索痕迹"] == 0

def test_g12_rejects_a_proved_claim_that_has_counterexamples(ws):
    """负控：有反例却标"证" ⇒ 自相矛盾 ⇒ error（阻断）。"""
    ctx = full_ctx(ws)
    ctx.doc = doc([claim(counterexamples=["n=3 时不等"])])
    r = G.run_gate("G12", ctx)
    assert r.verdict == "fail"
    assert any("自相矛盾" in f["message"] for f in r.findings)


def test_g12_is_not_applicable_when_nothing_is_marked_proved(ws):
    """G12：没有任何 `status='证'` 的断言 ⇒ 没有对象可判（不是"反例都搜过了"）。"""
    ctx = full_ctx(ws)
    ctx.doc = doc([claim(status="待精化")])
    r = G.run_gate("G12", ctx)
    assert r.verdict == "not_applicable"


def test_g14_rejects_a_retracted_claim_in_the_main_body(ws):
    """G14（降级合规门）：`status='作废'` 的断言出现在正文 ⇒ 阻断。"""
    ok = full_ctx(ws)
    assert G.run_gate("G14", ok).verdict == "pass"

    ctx = full_ctx(ws)
    ctx.doc = doc([claim(status="作废", errata_ids=["E-01"])])
    r = G.run_gate("G14", ctx)
    assert r.verdict == "fail"
    assert any("正文主结果区" in f["message"] for f in r.findings)
    assert r.counts["作废却在正文"] == 1


def test_g14_rejects_cross_check_marked_as_main_result(ws):
    """负控：`cross_check` 的断言标 `allowed_use='主结果'` ⇒ 违反硬性降级规则。"""
    ctx = full_ctx(ws)
    c = claim(evidence_kind="cross_check", allowed_use="主结果", disclaimer=DT.CROSS_CHECK_DISCLAIMER)
    ctx.doc = doc([c])
    r = G.run_gate("G14", ctx)
    assert r.verdict == "fail"
    assert any("降为" in f["message"] for f in r.findings)


def test_g15_fails_when_the_own_errors_section_is_missing(ws):
    """G15：报告里没有"我这一轮犯的错" ⇒ 退回（fail，不是 warning）。"""
    ctx = full_ctx(ws, own_errors=None)
    r = G.run_gate("G15", ctx)
    assert r.verdict == "fail"
    assert "退回" in r.reason


def test_g15_accepts_an_explicit_empty_list(ws):
    """防误伤：`own_errors=[]`（显式声明零错误）合法，且与"没写"严格区分。"""
    ctx = full_ctx(ws, own_errors=[])
    r = G.run_gate("G15", ctx)
    assert r.verdict == "pass"
    assert r.counts["显式声明零错误"] is True
    assert "显式声明" in r.reason


# ============================================================ 5. 汇总与报告


def test_gate_verdict_keeps_unknown_separate_from_accepted():
    """汇总：有 unknown 时不许判 accepted（"没查"与"查过没问题"必须分开）。"""
    def mk(gid, verdict):
        return G.GateResult(
            gate_id=gid, name="n", axis="工程", criterion="c", verdict=verdict,
            reason="r", findings=(),
            self_attestation="我扫了 1 个对象", counts={"对象数": 1},
        )

    assert G.gate_verdict({g: mk(g, "pass") for g in G.GATE_IDS})["verdict"] == "accepted"
    mixed = {g: mk(g, "pass") for g in G.GATE_IDS}
    mixed["G8"] = mk("G8", "unknown")
    out = G.gate_verdict(mixed)
    assert out["verdict"] == "unverified"
    assert out["unknown_gates"] == ["G8"]
    mixed["G2"] = mk("G2", "fail")
    assert G.gate_verdict(mixed)["verdict"] == "rejected"


def test_gate_verdict_reports_accepted_with_gaps_when_a_gate_has_no_object():
    """`not_applicable` 不是失败，但也不等于"全绿" —— 单占一档。"""
    def mk(gid):
        return G.GateResult(
            gate_id=gid, name="n", axis="工程", criterion="c", verdict="pass",
            reason="r", findings=(), self_attestation="扫了 1 个", counts={"n": 1},
        )
    results = {g: mk(g) for g in G.GATE_IDS}
    results["G5"] = G.GateResult(
        gate_id="G5", name="禁词门", axis="体例", criterion="c", verdict="not_applicable",
        reason="没有词表", counts={"提供的禁词数": 0}, self_attestation="查了词表",
    )
    out = G.gate_verdict(results)
    assert out["verdict"] == "accepted_with_gaps"
    assert out["not_applicable_gates"] == ["G5"]


def test_gate_report_requires_the_own_errors_section(ws):
    """`gate_report` 把 G15 做成必填参数：不写就抛（不是默默生成）。"""
    ctx = full_ctx(ws)
    with pytest.raises(G.GatesReportError, match="我这一轮犯的错"):
        G.gate_report(ctx, own_errors=None)


def test_gate_report_refuses_to_run_without_a_revision_hash():
    """报告必须钉住被审版本 hash（G11）：算不出 hash ⇒ 不许出报告。

    这里显式把 hash 打桩成空串（`monkeypatch`）—— 因为对真实的 doc
    `revision_hash()` 恒非空，于是"算不出 hash"这条分支在真数据上不可达；
    而它必须可达且可测，否则那句 `if not ctx.revision_hash: raise` 就是死代码。
    """
    ctx = G.GateContext.build(None)
    assert ctx.revision_hash == "", "夹具前提：没有 doc ⇒ 没有 hash"
    with pytest.raises(G.GatesReportError, match="hash"):
        G.gate_report(ctx, own_errors=[])

    real = G.GateContext.build(doc())
    assert real.revision_hash, "有 doc 时 hash 必须非空"
    # 直接改这份新造的上下文实例的字段（它就是"算不出 hash"的形态），
    # 于是那条 `if not ctx.revision_hash: raise` 的守卫可测而不是死代码。
    real.revision_hash = ""
    with pytest.raises(G.GatesReportError, match="hash"):
        G.gate_report(real, own_errors=[])


def test_every_non_empty_report_carries_a_sixteen_hex_hash(ws):
    """G11 的不变量：报告头那份 hash 必须非空、且是 16 位十六进制。

    这条比"某条分支可达"更强：它对每一份报告都成立，
    所以任何"顺手把 hash 从报告里去掉/改成常量"的改动都会当场变红。
    """
    for ctx in (
        full_ctx(ws),
        G.GateContext.build(doc(), workspace_root=ws, dependencies=[], own_errors=[]),
        G.GateContext.build(doc([claim(claim_id="c2", statement="另一句。")]), dependencies=[], own_errors=[]),
    ):
        report = G.gate_report(ctx, own_errors=[])
        h = report["revision_hash"]
        assert h and len(h) == 16, f"报告头 hash 不合规：{h!r}"
        assert all(ch in "0123456789abcdef" for ch in h), h
        assert h in G.render_review_report(report), "markdown 报告里必须看得见这个 hash"


def test_gate_report_contains_all_fifteen_gates_and_a_hash(ws):
    """报告的结构：15 门齐全 + 头部 hash + 自身错误一节 + 自证数字。"""
    ctx = full_ctx(ws, own_errors=["我把 G8 的 unknown 一度读成了 pass"])
    report = G.gate_report(ctx, own_errors=["我把 G8 的 unknown 一度读成了 pass"])
    assert report["gates_total"] == 15
    assert set(report["gates"]) == set(G.GATE_IDS)
    assert report["revision_hash"] and len(report["revision_hash"]) == 16
    assert report["own_errors"] == ["我把 G8 的 unknown 一度读成了 pass"]
    assert report["counts"]["断言数"] == 1
    assert report["counts"]["引用数"] == 1
    md = G.render_review_report(report)
    assert "被审版本 hash" in md and report["revision_hash"] in md
    assert "我这一轮犯的错" in md
    assert "G15" in md and "G1" in md
    for gid in G.GATE_IDS:
        assert gid in md, f"报告里缺 {gid}"


def test_report_json_matches_the_markdown_report(ws):
    """报告可以落成 JSON（机读）——与 markdown 是同一份数据。"""
    ctx = full_ctx(ws)
    report = G.gate_report(ctx, own_errors=[])
    blob = G.report_as_json(report)
    back = json.loads(blob)
    assert back["revision_hash"] == report["revision_hash"]
    assert set(back["gates"]) == set(G.GATE_IDS)


# ============================================================ 6. 端到端：H 产报告


def test_agent_h_produces_a_hash_pinned_report_on_disk(tmp_path):
    """端到端：H 的 `review_report` 落一份 markdown，且不改任何数据行。

    三件被结构强制的事都要在真文件里看得见：版本 hash、自证数字、自身错误一节。
    """
    st = Store(tmp_path / "ws")
    st.init()
    st_row = CA.to_storage_claim(claim())
    row = {
        "doc_id": "0000", "kind": "paper", "title": "端到端", "markdown_path": "documents/0000.md",
        "sections": [], "claims": [st_row], "open_problems": [], "status": "draft",
        "review_rounds": 0, "created_at": TS, "updated_at": TS, "created_by": "agent-G",
    }
    with st.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row)
    claims_before = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))

    h = AgentH(st)
    out = h.review_report("0000", own_errors=["第一轮我把未查的 G8 当成了通过"])
    assert out["gates_total"] == 15
    assert out["report_path"] == "reports/0000-review.md"
    body = (st.root / out["report_path"]).read_text(encoding="utf-8")
    assert out["revision_hash"] in body
    assert "我这一轮犯的错" in body
    assert "第一轮我把未查的 G8 当成了通过" in body
    assert "自证" in body

    # ---- H 只读：跑完报告后 documents.json 逐字节不变
    claims_after = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))
    assert claims_after == claims_before, "review_report 改动了数据表 —— 它只该写一个报告文件"


def test_agent_h_reports_unregistered_own_errors_loudly(tmp_path):
    """`own_errors` 缺省时不许假装"零错误"：返回值与日志都要留痕。"""
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", {
            "doc_id": "0000", "kind": "paper", "title": "t", "markdown_path": None,
            "sections": [], "claims": [CA.to_storage_claim(claim())], "open_problems": [],
            "status": "draft", "review_rounds": 0, "created_at": TS, "updated_at": TS,
            "created_by": "agent-G",
        })
    h = AgentH(st)
    out = h.review_report("0000")  # own_errors 没传
    assert out["own_errors_registered"] is False
    assert out["own_error_count"] == 0
    assert any("未登记" in line for line in h.logs), "『自身错误没登记』必须在日志里可见"


def test_review_report_tool_rejects_an_out_of_workspace_path(tmp_path):
    """负控：报告的 `out_path` 越界 ⇒ 拒绝（沙箱边界不是建议）。"""
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", {
            "doc_id": "0000", "kind": "paper", "title": "t", "markdown_path": None,
            "sections": [], "claims": [CA.to_storage_claim(claim())], "open_problems": [],
            "status": "draft", "review_rounds": 0, "created_at": TS, "updated_at": TS,
            "created_by": "agent-G",
        })
    with pytest.raises(ValueError, match="越界"):
        RV.review_report(st, "0000", own_errors=[], out_path="../escape.md")


def test_review_report_requires_the_own_errors_section(tmp_path):
    """负控：函数层也强制 G15（不许只在门那一层拦）。"""
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", {
            "doc_id": "0000", "kind": "paper", "title": "t", "markdown_path": None,
            "sections": [], "claims": [CA.to_storage_claim(claim())], "open_problems": [],
            "status": "draft", "review_rounds": 0, "created_at": TS, "updated_at": TS,
            "created_by": "agent-G",
        })
    with pytest.raises(ValueError, match="我这一轮犯的错"):
        RV.review_report(st, "0000", own_errors=None)


def test_review_report_tool_is_registered_only_on_the_writer_surface(tmp_path):
    """报告工具只出现在 H 的落库代理里（`include_writers=True`），默认面仍然全只读。"""
    from agentflow.tools.base import ToolRegistry

    st = Store(tmp_path / "ws")
    st.init()
    default_reg = ToolRegistry(name="review-default")
    RV.register(default_reg, store=st)
    assert default_reg.names() == ["review.list_findings", "review.scan_document"]
    writers = ToolRegistry(name="review-writers")
    RV.register(writers, store=st, include_writers=True)
    assert writers.get("review.report").side_effect == "write_local"
    assert writers.get("review.report").roles == ("H",)
