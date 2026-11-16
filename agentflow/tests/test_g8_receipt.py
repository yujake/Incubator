"""G8 只从 `experiments` 台账取证，不再接受任何"回执"自述。

## 改前（旧口径）

`gates.gate_g8` 读 `GateContext.run_evidence` —— 一份由调用方（H 的 `review.report`）
传进来的 dict，形状 `{checked, commands:[{claim_id, command, exit_code, output_tail}]}`。
它与收工门读的 `out/review/RUN-EVIDENCE.json` 是同一套"回执"载体的两个落位，而
全仓没有任何步骤被要求写它们（`specs/m.py` 只教"凑成 dict 交给 H"，H 从未被召唤）。
回执里那句 `checked: true` 因此是声明，不是证据。

## 这一组钉什么

台账是唯一的证据来源：每一条数值断言都要在 `experiments` 里对得上一行
（`code_path` / `script_path` 与断言的 `numeric_evidence.script` 相同），
且那一行有 `code_hash` 与整数 `exit_code`。回执不再参与判定（传了也视而不见）。

| # | 判据 |
|---|---|
| ① | H 仍没有 exec 面（结构事实不变），G8 从台账取证的修法不靠放权 |
| ② | 台账行齐（脚本 + `code_hash` + `exit_code=0`）⇒ `pass` |
| ③ | 台账行 `exit_code != 0` ⇒ `fail`（跑过但红了） |
| ④ | 台账行缺 `exit_code` ⇒ `unknown`（分不出绿与红） |
| ⑤ | 台账里没有这条断言的脚本 ⇒ `fail` |
| ⑥ | 台账没接上（`experiments=None`）⇒ `unknown`（没查成，不是通过） |
| ⑦ | 稿件没有数值断言 ⇒ `not_applicable`（不是空回执的 unknown） |
| ⑧ | 反真空：一份 `checked: true` 的"全绿回执"在空台账上必须不能让 G8 变绿 |
| ⑨ | 成稿引到台账里没有的 `exp:` 号 ⇒ `fail` |
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import gates as G
from agentflow.tools import build_registry

from conftest import TS


def _claim(**over: object) -> dict:
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


def _doc(claims: list[dict] | None = None) -> dict:
    return {
        "doc_id": "0000", "kind": "paper", "title": "G8 台账测试稿件",
        "markdown_path": "documents/0000.md",
        "claims": claims if claims is not None else [_claim()],
        "open_problems": [], "status": "draft", "review_rounds": 0,
        "created_at": TS, "updated_at": TS,
    }


def _doc_with_no_numeric_claims() -> dict:
    """没有任何 `numeric_evidence.script`、也不引任何实验的稿件（G8 的"真空"那一格）。"""
    return _doc([_claim(numeric_evidence={}, status="猜想", evidence_kind="heuristic",
                        citations=["lit:0000"])])


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "code").mkdir(parents=True)
    (root / "documents").mkdir(parents=True)
    (root / "code" / "p1.py").write_text("print('REPRO_RESULT: {}\\n')\n", encoding="utf-8")
    (root / "documents" / "0000.md").write_text("# 稿件\n", encoding="utf-8")
    return root


def _row(**over: object) -> dict:
    """一行 `experiments` 台账（默认就是 `code/p1.py` 那一次绿跑）。"""
    base = {
        "experiment_id": "000000", "claim": "谱落在区间内", "claim_key": "stmt:000007",
        "method": "numeric", "evidence_kind": "cross_check", "result": "supports",
        "code_path": "code/p1.py", "code_hash": "4f6ea689cbfacb7a",
        "exit_code": 0, "status": "active", "created_at": TS, "created_by": "test",
    }
    base.update(over)
    return base


_DEFAULT = object()


def _ctx(ws: Path, *, experiments: object = _DEFAULT, doc: dict | None = None,
         run_evidence: object = None) -> G.GateContext:
    rows: object
    if experiments is _DEFAULT:
        rows = [_row()]
    elif isinstance(experiments, dict):
        rows = [experiments]
    else:
        rows = experiments
    return G.GateContext.build(
        doc if doc is not None else _doc(), dependencies=[], files=["code/p1.py"],
        workspace_root=ws, experiments=rows, run_evidence=run_evidence,
        findings=[], claim_counts=None, banned_words=[], own_errors=[],
    )


# ============================================================ ① 结构：H 没有执行面
def test_h_structurally_has_no_exec_surface(tmp_path: Path) -> None:
    """正控（结构事实）：H 的工具面里没有任何 `exec` 入口 —— 这是"只读"的定义。

    G8 改成从台账取证之后，这条事实不需要放松：台账由 E 的 `verify.run_experiment`
    写、由 H 只读地判。放松它等于给审校者一把能跑任意程序的刀。
    """
    root = tmp_path / "ws"
    root.mkdir()
    reg = build_registry(workspace_root=root).registry
    h = [s for s in reg.for_role("H")]
    exec_like = [s.name for s in h if getattr(s, "external", "none") == "exec"]
    assert exec_like == [], f"H 的工具面里出现了 exec 入口：{exec_like}"
    e_exec = [s.name for s in reg.for_role("E") if getattr(s, "external", "none") == "exec"]
    assert e_exec, "E 的工具面里没有任何 exec —— 这条判据退化成真空"
    # 兼容面：`review.report` 仍收 `run_evidence` 参数（旧调用方不会因为参数消失而炸），
    # 但这一组下面钉着"它不再影响判定"。
    assert "review.report" in {s.name for s in h}
    props = next(s for s in h if s.name == "review.report").params["properties"]
    assert "run_evidence" in props, props


# ============================================================ ②–⑤ 台账四态
def test_g8_passes_on_a_green_ledger_row(ws: Path) -> None:
    """② 台账行齐（脚本 + `code_hash` + `exit_code=0`）⇒ `pass`。"""
    r = G.gate_g8(_ctx(ws))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["退出码非零"] == 0, r.counts
    assert r.counts["本轮实跑记录"] == 1, r.counts


def test_g8_fails_on_a_red_ledger_row(ws: Path) -> None:
    """③ 台账行 `exit_code=2` ⇒ `fail`（跑过但红了）。"""
    r = G.gate_g8(_ctx(ws, experiments=_row(exit_code=2)))
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["退出码非零"] == 1, r.counts
    assert any("exit_code" in str(f.get("message") or "") for f in r.findings), r.findings


def test_g8_is_unknown_when_the_ledger_row_has_no_exit_code(ws: Path) -> None:
    """④ 台账行缺 `exit_code` ⇒ `unknown`（分不出绿与红就等于没判）。"""
    row = _row()
    row.pop("exit_code")
    r = G.gate_g8(_ctx(ws, experiments=row))
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "exit_code" in r.reason, r.reason


def test_g8_fails_when_the_ledger_has_no_row_for_the_script(ws: Path) -> None:
    """⑤ 台账里没有这条断言的脚本 ⇒ `fail`（"没跑过"不是"跑绿了"）。"""
    r = G.gate_g8(_ctx(ws, experiments=_row(code_path="code/other.py")))
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["缺命令"] == 1, r.counts
    assert r.findings and r.findings[0]["target"] == "claim-1", r.findings


# ============================================================ ⑥–⑦ 三态
def test_g8_is_unknown_when_the_ledger_is_not_wired(ws: Path) -> None:
    """⑥ `experiments=None`（台账没接上/读不到）⇒ `unknown`，绝不是 `pass`。"""
    r = G.gate_g8(_ctx(ws, experiments=None))
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "台账" in r.reason and "没查成" in r.reason, r.reason
    assert r.counts["本轮实跑记录"] == "未提供", r.counts


def test_g8_is_not_applicable_without_numeric_claims(ws: Path) -> None:
    """⑦ 稿件没有数值断言 ⇒ `not_applicable`（有理由，不是真空 pass）。"""
    r = G.gate_g8(_ctx(ws, experiments=[], doc=_doc_with_no_numeric_claims()))
    assert r.verdict == "not_applicable", (r.verdict, r.reason)
    assert r.reason.strip(), "not_applicable 必须给理由"


# ============================================================ ⑧ 反真空
def test_a_green_receipt_cannot_turn_g8_green_on_an_empty_ledger(ws: Path) -> None:
    """⑧ 反真空：一份"全绿回执"在空台账上必须不能让 G8 变绿。

    改前：`run_evidence={checked: true, commands:[...]}` ⇒ `pass`。
    改后：回执不是输入 ⇒ 台账里没有那行就 `fail`、读不到就 `unknown`。
    """
    receipt = {"checked": True, "commands": [
        {"claim_id": "claim-1", "command": "python code/p1.py",
         "exit_code": 0, "output_tail": "ALL CHECKS PASS"}]}
    empty = G.gate_g8(_ctx(ws, experiments=[], run_evidence=receipt))
    assert empty.verdict == "fail", empty
    no_ledger = G.gate_g8(_ctx(ws, experiments=None, run_evidence=receipt))
    assert no_ledger.verdict == "unknown", no_ledger


def test_a_declared_non_run_receipt_cannot_turn_a_green_ledger_red(ws: Path) -> None:
    """⑧ 的反向：回执说"没跑"、而台账齐全 ⇒ 仍然 `pass`（回执不再参与判定）。"""
    r = G.gate_g8(_ctx(ws, run_evidence={"checked": False, "reason": "本轮只改措辞"}))
    assert r.verdict == "pass", (r.verdict, r.reason)


# ============================================================ ⑨ 引到不存在的 exp
def test_g8_fails_when_a_citation_points_at_an_experiment_missing_from_the_ledger(
        ws: Path) -> None:
    """⑨ 成稿引 `exp:999999`，台账里没有 ⇒ `fail`（一条指不到台账的引用不是证据）。"""
    claim = _claim(citations=["exp:999999"], numeric_evidence={})
    r = G.gate_g8(_ctx(ws, experiments=[_row()], doc=_doc([claim])))
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["缺命令"] == 1, r.counts
    assert r.findings and "999999" in str(r.findings[0].get("evidence") or ""), r.findings
