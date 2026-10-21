"""判据（修法 4）：`literature.unprocessed > 0` 不许让「请求闭环」那一行记 `pass`。

现场读数（三份验收表，逐字）：`projects/mp2` R10：`literature.unprocessed` = 32 未清零却记 `pass`；
`projects/mp3` P8：20 记 `pass`；`projects/t3d` ⑧：12 记「成立」。三份都把那个读数如实写出来了 ——
红的原因不是"没写"，而是没有任何一行判它：`unfinished_request_rows` 数的是检索/重抽取两条队列，
而"登记进 `literature` 但没被 B 消化"是第三条队列，收工门此前一行都没读。

修法（业主裁定：`unprocessed > 0` ⇒ 该项记 `unknown`，不是 `pass`）：① 新增受控档
`literature_unprocessed_rows`（`closing._leg_reading`，缺省上限 0），让第三条队列有一条可复算的读数；
② 行循环里给「请求闭环」那一行加降级判据（`kind == "unfinished_request_rows"`）：`unprocessed == 0`
⇒ 照常判；`> 0` 且那一行写了 `unprocessed_reason` ⇒ 这一行 `state="unknown"`、整格 `unknown`；
`> 0` 而没写理由 ⇒ `unmet`（blocker），不许静默带着队列收工；`literature` 读不到 ⇒ `unknown`
（读不到 ≠ 清零）。
负控（每条都钉在"修好之前会绿"的那一格）：`test_a_clear_queue_still_passes`：正控（反真空）——
队列清零时这一行照常 `pass`、整格 `pass`（证明新判据不是"恒 unknown"）；
`test_a_dirty_queue_without_a_reason_is_a_blocker`：32 条未消化且没写理由 ⇒ 整格 `fail` + 点名
`acceptance_unprocessed_without_reason`（修法前这里是 `pass`）；
`test_a_dirty_queue_with_a_reason_downgrades_to_unknown`：写了理由 ⇒ 行 `unknown`、整格 `unknown`
（不是 `pass`），读数 `got` 仍在；`test_the_third_queue_has_its_own_leg`：`literature_unprocessed_rows` 自己算得出 32，且它的上限是
0（写进验收表时它自己会红）。"""
from __future__ import annotations

import json
import pathlib

from agentflow import closing as CL
from agentflow import schema as S
from agentflow.store import Store

from conftest import TS, sync_counters
from test_closing_gate import (
    _acceptance_checks,
    _gate,
    _paper_with_claim,
    _project,
    _t3_experiment,
    _write_report,
)


def _legs(**over: object) -> list[dict]:
    """四条腿的验收表：P7/P8/P9 与「请求闭环」（`unfinished_request_rows`，上限 0）。

    这套行在 `tests/test_closing_gate.py::test_the_acceptance_cell_passes_once_each_leg_has_a_ledger_row`
    里是"全绿"的形态；本文件只动第四条腿的语境（文献消化队列）。
    """
    close_row: dict = {"id": "P10", "name": "请求闭环", "kind": "unfinished_request_rows",
                       "max": 0}
    close_row.update(over)
    return [
        {"id": "P7", "name": "引文逐条核过", "kind": "quote_verified_rows", "min": 1},
        {"id": "P8", "name": "形式化", "kind": "proof_experiment_rows", "min": 1},
        {"id": "P9", "name": "审校", "kind": "reviewed_documents", "min": 1},
        close_row,
    ]


def _seed_legs(s: Store) -> None:
    """三条腿各一条凭据（与 `test_closing_gate` 的正控同一形态）。"""
    _t3_experiment(s, "0002", method="formal", evidence_kind="proof")
    _paper_with_claim(s, doc_id="0002")
    with s.tx("documents", actor="test") as tx:
        row = dict(tx.rows("documents")[0])
        row["review_rounds"] = 1
        row["review_verdict"] = "成立"
        row["reviewed_at"] = TS
        row["reviewed_by"] = "agent-H"
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


def _seed_literature(s: Store, *, unprocessed: int, processed: int = 0) -> None:
    """登记 `unprocessed + processed` 条文献（`processed` 决定第三条队列的长度）。"""
    with s.tx("literature", actor="test", note="seed literature") as tx:
        n = 0
        for i in range(processed):
            tx.upsert("literature", {
                "lit_id": f"{n:06d}", "title": f"已消化 {n}", "type": "J",
                "summary": f"已消化的第 {n} 条", "path": None,
                "processed": True, "added_at": TS})
            n += 1
        for _ in range(unprocessed):
            tx.upsert("literature", {
                "lit_id": f"{n:06d}", "title": f"未消化 {n}", "type": "J",
                # metadata-only 的那一类（现场口径：`projects/mp2` 的 32 条就是这一档）
                "summary": f"未消化的第 {n} 条（无本地全文）", "path": None,
                "processed": False, "added_at": TS})
            n += 1
    sync_counters(s)


def _run(tmp_path: pathlib.Path, *, unprocessed: int, processed: int = 0,
         close_row_extra: dict | None = None):
    def seed(s: Store) -> None:
        _seed_legs(s)
        _seed_literature(s, unprocessed=unprocessed, processed=processed)

    st = _project(tmp_path, seed=seed)
    report = _write_report(tmp_path)
    _acceptance_checks(tmp_path, _legs(**(close_row_extra or {})), st=st)
    return _gate(st, report)


# ============================================================ 正控（反真空）

def test_a_clear_queue_still_passes(tmp_path: pathlib.Path) -> None:
    """正控：`unprocessed = 0` 时「请求闭环」照常 `pass`、整格 `pass`。

    这一条是反真空：新判据若无条件把那一行降成 `unknown`，它就废了这一档。
    """
    rep = _run(tmp_path, unprocessed=0, processed=5)
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    row = next(r for r in rep.readings["acceptance"]["rows"] if r["id"] == "P10")
    assert row["state"] == "computed" and row["ok"] is True, row
    assert row["detail"]["literature_unprocessed"] == 0, row["detail"]


# ============================================================ 负控：没有理由 ⇒ blocker

def test_a_dirty_queue_without_a_reason_is_a_blocker(tmp_path: pathlib.Path) -> None:
    """负控（核心）：32 条未消化、而那一行没写 `unprocessed_reason` ⇒ 整格 `fail`。

    修法前这一格是 `pass`（`projects/mp2` R10 的现场：读数写着 32 未清零、结论 pass）。
    """
    rep = _run(tmp_path, unprocessed=32, processed=3)
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    codes = [f.code for f in rep.findings if f.check == "acceptance"]
    assert "acceptance_unprocessed_without_reason" in codes or "acceptance_unmet" in codes, codes
    detail = "；".join(str(f.detail) for f in rep.findings if f.check == "acceptance")
    assert "literature.unprocessed" in detail and "32" in detail, detail
    assert "unprocessed_reason" in detail, detail


# ============================================================ 负控：有理由 ⇒ unknown（不是 pass）

def test_a_dirty_queue_with_a_reason_downgrades_to_unknown(tmp_path: pathlib.Path) -> None:
    """业主口径：`unprocessed > 0` ⇒ 该项记 `unknown`，且写清为什么可以带着它收工。

    这一条钉三件事：
    ① 行 `state == "unknown"`、`ok is False`（不是 pass）；
    ② 整格 `unknown`（"行记 unknown、格记 pass"等于什么都没改）；
    ③ 读数没丢：`got` 与 `detail.literature_unprocessed` 仍在（不是把行删掉）。
    """
    rep = _run(tmp_path, unprocessed=32, processed=3,
               close_row_extra={"unprocessed_reason":
                                "剩下 32 条是 metadata-only（无本地全文），processed 永远为假"})
    assert rep.status["acceptance"] == "unknown", rep.to_dict()
    acc = rep.readings["acceptance"]
    row = next(r for r in acc["rows"] if r["id"] == "P10")
    assert row["state"] == "unknown" and row["ok"] is False, row
    assert row["got"] == 0, row          # 读数留着：闭环队列本身是 0
    assert row["detail"]["literature_unprocessed"] == 32, row["detail"]
    assert acc["rows_unknown"] == 1 and acc["unknown_rows"][0]["id"] == "P10", acc["unknown_rows"]
    codes = [f.code for f in rep.findings if f.check == "acceptance"]
    assert "acceptance_unprocessed_carried" in codes, codes
    # 本文件不是要禁掉"带着队列收工"：它要的是这件事必须说得出来
    assert "metadata-only" in "；".join(str(f.detail) for f in rep.findings), \
        [f.detail for f in rep.findings]


# ============================================================ 第三条队列自己有读数

def test_the_third_queue_has_its_own_leg(tmp_path: pathlib.Path) -> None:
    """`literature_unprocessed_rows` 这一档算得出 32，且它的上限是 0（自己会红）。"""
    rep = _run(tmp_path, unprocessed=32, processed=3,
               close_row_extra=None)
    st = Store(tmp_path)
    got, detail = CL._leg_reading(st, "literature_unprocessed_rows", tmp_path)
    assert got == 32, (got, detail)
    assert detail["literature"] == 35 and detail["unprocessed"] == 32, detail
    assert detail["implicit_max"] == 0, detail
    assert "literature_unprocessed_rows" in CL.LEG_CHECK_KINDS

    # 把它自己写进验收表：上限 0 ⇒ 这一行自己红（不靠降级那一条兜着）
    _acceptance_checks(tmp_path, [
        {"id": "LIT", "name": "文献消化队列", "kind": "literature_unprocessed_rows",
         "max": 0},
    ])
    rep2 = _gate(st, next(p for p in (tmp_path / "out" / "review").glob("REPORT.md")))
    row = next(r for r in rep2.readings["acceptance"]["rows"] if r["id"] == "LIT")
    assert row["got"] == 32 and row["ok"] is False, row
