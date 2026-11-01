# -*- coding: utf-8 -*-
"""`/api/package` 的纯函数判据（块 2：不建路由也能测）。

## 这一份守什么

`package_face()` 一次给三块（A 证明 / B 结构 / C 收工）。它最容易退化的形态不是
"抛异常"，而是把读不到折成 0：没有正文写成 0 行、没有台账写成 0 条、没有回执
写成 0 打回。所以这里的正控都带一条"同一现场的另一档"：

- 没有正文 ⇒ `structure.tri="not_applicable"`（不是 `computed` + 0 行）；
- 台账读不出来 ⇒ `proofs.review_states == {}`、`signed is None`（不是 0）；
- 八格的四态与 `readouts.gates_readout` 逐格一致（两处不许各算一套）；
- `failed`（真 fail）与 `unchecked`（没查成）不重不漏。

真机数字（81 副本的 52 行 / 8 判 4 送 / 5.728771）不写进这里 —— 82 还在跑，
冻结任何真机数字都会让这条判据在下一秒变成谎言（父代理 2026-11-01 的纪律）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from agentflow import readouts
from agentflow.store import Store
from agentflow.webui import readers as R


def _add_paper(root: pathlib.Path) -> pathlib.Path:
    """给夹具工作区补一份可查的论文包（`main.tex` / `main.pdf` / 编译回执）。"""
    fitz = pytest.importorskip("fitz")
    pkg = root / "out" / "paper"
    pkg.mkdir(parents=True, exist_ok=True)
    tex = pkg / "main.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\section{夹具}\n"
        "\\begin{theorem}夹具定理。\\end{theorem}\n"
        "\\begin{proof}夹具证明。\\end{proof}\n"
        "\\end{document}\n", encoding="utf-8")
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pkg / "main.pdf"))
    doc.close()
    (pkg / "COMPILE-RECEIPT.json").write_text(
        json.dumps({"tex_sha256": hashlib.sha256(tex.read_bytes()).hexdigest(),
                    "pages": 1, "engine": "fixture", "exit_codes": [0, 0]}),
        encoding="utf-8")
    return root


def _keys(block: dict) -> set[str]:
    return set(block)


# ====================================================================== 1 没有正文
def test_no_paper_is_not_applicable_not_zero(artifacts_ws: pathlib.Path) -> None:
    """没有 `main.tex` ⇒ `structure.tri=not_applicable`，不是「0 行、0 个定理」。"""
    pkg = R.package_face(artifacts_ws, project_dir=str(artifacts_ws))
    assert _keys(pkg) == {"tri", "reason", "generated_at", "proofs", "structure", "closing"}
    assert _keys(pkg["proofs"]) == {
        "tri", "reason", "source", "paper_theorem_envs", "propositions_with_proof",
        "ledger_theorem_kinds", "signed", "coverage_note", "review_states",
        "rows", "vsign", "receipt", "c3"}
    assert _keys(pkg["structure"]) == {"tri", "reason", "source", "paper", "checks",
                                       "ledger", "findings"}
    assert _keys(pkg["closing"]) == {"tri", "reason", "source", "gates", "machine",
                                     "undelivered", "cost", "runtime", "content"}
    assert pkg["structure"]["tri"] == "not_applicable"
    assert pkg["structure"]["paper"]["exists"] is False
    assert pkg["structure"]["paper"]["lines"] is None, "没有正文不许写成 0 行"
    assert pkg["structure"]["findings"] == []
    # 三块各自的三态，不互相顶替
    assert pkg["proofs"]["tri"] in ("computed", "unreadable")
    assert pkg["closing"]["tri"] in ("computed", "unreadable")


# ====================================================================== 2 有正文
def test_a_real_paper_fills_the_structure_block(artifacts_ws: pathlib.Path) -> None:
    """有 `main.tex` / `main.pdf` ⇒ B 块真的读出行数、页数、proof 配对。"""
    root = _add_paper(artifacts_ws)
    pkg = R.package_face(root, project_dir=str(root))
    structure = pkg["structure"]
    assert structure["tri"] == "computed", structure["reason"]
    paper = structure["paper"]
    assert paper["exists"] is True
    assert paper["lines"] and paper["lines"] > 0
    assert paper["pdf_pages"] == 1
    assert paper["receipt_verdict"] == "consistent"
    assert structure["ledger"]["statement_envs"] == 1
    assert structure["checks"]["proofs"]["checked"] is True
    # 每一条 finding 都带原文出处（没有出处的 finding 不许上屏）
    for finding in structure["findings"]:
        assert finding["source"]["path"], finding
        assert finding["source"]["line"] > 0, finding


# ====================================================================== 3 八格同一口径
def test_the_gate_table_agrees_with_the_cli_readout(artifacts_ws: pathlib.Path) -> None:
    """`package_face().closing.gates` 与 `readouts.gates_readout` 逐格一致。

    两处都从 `closing.check_closing` 现算；这一条是"同一件事不许有两个口径"的
    文件级落点。不一致时先看是谁改了四态映射，而不是把这条判据改宽。
    """
    pkg = R.package_face(artifacts_ws, project_dir=str(artifacts_ws),
                         report_path="out/review/REPORT.md")
    cli = readouts.gates_readout(artifacts_ws, project_dir=str(artifacts_ws),
                                 report_path="out/review/REPORT.md")
    gates = pkg["closing"]["gates"]
    assert gates["counts"] == cli["data"]["counts"], (gates["counts"], cli["data"]["counts"])
    assert gates["machine_pass"] == cli["data"]["machine_pass"]
    assert gates["can_close"] == cli["data"]["can_close"]
    assert gates["closable"] == cli["data"]["closable"]
    got = [(c["name"], c["status"]) for c in gates["cells"]]
    want = [(c["name"], c["status"]) for c in cli["data"]["cells"]]
    assert got == want
    # 每一格都能点开原文
    for cell in gates["cells"]:
        assert cell["source"]["path"], cell


# ====================================================================== 4 failed / unchecked
def test_failed_and_unchecked_are_two_different_diagrams(
        artifacts_ws: pathlib.Path) -> None:
    """`failed` 只收真 fail，`unchecked` 只收 unknown；两档不重不漏。"""
    pkg = R.package_face(artifacts_ws, project_dir=str(artifacts_ws),
                         report_path="out/review/REPORT.md")
    content = pkg["closing"]["content"]
    criteria = content["criteria"]
    assert set(content["failed"]) == {k for k, v in criteria.items() if v == "fail"}
    assert set(content["unchecked"]) == {k for k, v in criteria.items()
                                         if v == "unknown"}
    assert not (set(content["failed"]) & set(content["unchecked"]))
    # 三档词表之外不许出现别的值
    assert set(criteria.values()) <= {"pass", "fail", "unknown"}
    assert content["passed"] == (all(v == "pass" for v in criteria.values())
                                 if criteria else False)
    assert content["note"], "内容级验收必须写明「不进机器门」"


# ====================================================================== 5 读不成不折 0
def test_unreadable_ledger_is_not_zero(artifacts_ws: pathlib.Path) -> None:
    """`data/statements.json` 坏掉 ⇒ A 块 `unreadable` + `signed is None`（不是 0）。"""
    (artifacts_ws / "data" / "statements.json").write_text("{ 这不是 JSON\n",
                                                           encoding="utf-8")
    pkg = R.package_face(artifacts_ws, project_dir=str(artifacts_ws))
    proofs = pkg["proofs"]
    assert proofs["tri"] == "unreadable", proofs
    assert proofs["review_states"] == {}
    assert proofs["signed"] is None, "没查成不许写成「0 条已签」"
    assert proofs["rows"] == []
    assert proofs["reason"], "没查成必须给原因"


# ====================================================================== 6 source 形状
def test_every_row_carries_a_source_ref(artifacts_ws: pathlib.Path) -> None:
    """`source` 的四格恒定（path / line / match / label）；空出处也要四格俱全。"""
    pkg = R.package_face(artifacts_ws, project_dir=str(artifacts_ws))
    refs = [pkg["proofs"]["source"], pkg["proofs"]["c3"]["source"],
            pkg["proofs"]["vsign"]["source"], pkg["proofs"]["receipt"]["source"],
            pkg["structure"]["source"], pkg["closing"]["source"],
            pkg["closing"]["cost"]["source"],
            pkg["closing"]["runtime"]["source"],
            pkg["closing"]["machine"]["source"]]
    refs += [cell["source"] for cell in pkg["closing"]["gates"]["cells"]]
    refs += list(pkg["closing"]["content"]["sources"].values())
    for ref in refs:
        assert set(ref) == {"path", "line", "match", "label"}, ref
        assert isinstance(ref["line"], int)
