# -*- coding: utf-8 -*-
"""判据：D3 批 1 的只读读数（`fault_kind_of` / `is_a_vote` / `vote_reading` + `verify-audit`）。

## 这一份守什么

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① 98b 六条 fault 逐条归类 | 2 条 `math` + 4 条 `report_gap`，且 `source` 是 `legacy_*` | 「没记录反例尝试」又被折回 math（签再次不可达），或者反过来把数学缺陷说成 report_gap（静默解锁） |
| ② `is_a_vote` 四条反例 | checked=False / axis=fault / clean 带 kind / row_signable=False 各一条 | 某一条被漏判成一票 ⇒ 票数虚高 |
| ③ 反真空 | 把 4 条 report_gap 判回 math 时，① 必须红 | 判据写成 `kind in (...)` 之类，真空也能过 |

## 为什么用台账夹具复刻 98b，而不是读 `projects/`

`projects/` 是只读的真机材料，而且 98b 的行会被后续批次改写；判据要的是
当年那 7 行的形状（`findings=[]`、`defect_step=null`、`unresolved_errors=0`、
`verdict=成立`，fault 的全部内容在 `secretary_judge.reason` 里）。所以把 7 行逐字
（或逐字到足以判类的程度）抄成夹具，与 `temp/_design_D3.md` 附录 B 对得上。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from agentflow import verifications as VR

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 98b 的 7 行夹具


def _row(
    statement_id: str,
    verification_id: str,
    *,
    verdict: str = "成立",
    axis: str = "fault",
    findings: list[dict[str, Any]] | None = None,
    defect_step: Any = None,
    unresolved_errors: int = 0,
    reason: str = "",
    review_call: str = "",
    review_pass: Any = None,
    proof_sha256: str = "",
    checked: bool = True,
    fault_kind: str | None = None,
    fault_cause: str | None = None,
    report_gap: str | None = None,
) -> dict[str, Any]:
    """造一行台账（形状与 `verifications/<sid>.jsonl` 的落盘行同一套键）。"""
    judge: dict[str, Any] = {
        "axis": axis,
        "checked": checked,
        "decision": "",
        "reason": reason,
    }
    if fault_kind is not None:
        judge["fault_kind"] = fault_kind
    if fault_cause is not None:
        judge["fault_cause"] = fault_cause
    if report_gap is not None:
        judge["report_gap"] = report_gap
    row: dict[str, Any] = {
        "at": "2026-11-09T10:54:45+08:00",
        "citation_checks": [],
        "defect_step": defect_step,
        "findings": list(findings or []),
        "manuscript": f"notes/b-proof-{statement_id}.md",
        "proof_chars": 0,
        "proof_no": 1,
        "proof_sha256": proof_sha256,
        "quote": "",
        "round": 1,
        "secretary_judge": judge,
        "statement_id": statement_id,
        "stmt_id": statement_id,
        "submission_id": "",
        "unresolved_errors": int(unresolved_errors),
        "used_faces": [],
        "verdict": verdict,
        "verification_id": verification_id,
        "verifier": "agent-V",
        "why": "",
    }
    if review_call:
        row["review_call"] = review_call
    if review_pass is not None:
        row["review_pass"] = review_pass
    return row


def _error(step: int, detail: str) -> dict[str, Any]:
    return {"detail": detail, "kind": "无依据的步骤", "level": "error", "step": step}


def _warning(step: int, detail: str) -> dict[str, Any]:
    return {"detail": detail, "kind": "跳步", "level": "warning", "step": step}


def rows_98b() -> list[dict[str, Any]]:
    """98b 的 7 行（与 `temp/_design_D3.md` 附录 B 同一批）。"""
    return [
        # 1. 000000：V 写成立、findings 空；fault 的全部内容 = reason 里那句
        #    「没有记录任何反例构造尝试」。
        _row(
            "000000", "v-000001",
            verdict="成立", axis="fault", findings=[], defect_step=None,
            unresolved_errors=0,
            reason=("它虽逐行核对并称未发现问题，但没有记录任何反例构造尝试，"
                    "按题面标准不能判『没问题』。"),
            review_call="2ad402ded0b8", review_pass=1,
            proof_sha256="05f49cf675fadcd8be69013fab165bdd9428dd0936dee9dd157fe1ec6ec35fae",
        ),
        # 2. 000001 v-000001：两条 error 都指到第 2 步 —— math。
        _row(
            "000001", "v-000001",
            verdict="有毛病", axis="fault",
            findings=[
                _error(2, "步2直接写「逐项求导」，但步1只断言原级数逐点绝对收敛；"
                          "未说明在紧子集上一致收敛，或求导后级数绝对收敛，"
                          "不能由步1直接推出可逐项求导。"),
                _error(2, "命题还断言 Σ_n Λ(n)n^{−σ} 在 σ>1 上绝对收敛；步2只给出等式，"
                          "未证明 Σ_pΣ_k (log p)p^{−kσ}<∞。"),
            ],
            defect_step=2, unresolved_errors=2,
            reason="该回复明确指认步2存在「无依据的逐项求导」和「绝对收敛未证」两处缺陷。",
            review_call="91d8559cbba5", review_pass=1,
            proof_sha256="6f44395f50679c49794648911e33cc490afbb518eace73c9b4bb03abdaeb217d",
        ),
        # 3. 000001 v-000002：唯一一票（clean）。
        _row(
            "000001", "v-000002",
            verdict="成立", axis="clean", findings=[], defect_step=None,
            unresolved_errors=0,
            reason=("回复逐行核对了定理链的三步，并明确记录了在二重级数重排处"
                    "构造反例失败，未指出任何缺陷。"),
            review_call="65ec84580055", review_pass=1,
            proof_sha256="97157c1d0795aef9df40851a7b5b752ad0d02af74f1bf9166a37d08d1df8f740",
        ),
        # 4. 000001 v-000003：同 sha 同 call，只因「未构造出反例」被判 fault。
        _row(
            "000001", "v-000003",
            verdict="成立", axis="fault", findings=[], defect_step=None,
            unresolved_errors=0,
            reason=("它虽声称逐行核对，但对反例仅写“未构造出反例”，没有尝试记录，"
                    "未达到证明没问题的标准。"),
            review_call="65ec84580055", review_pass=2,
            proof_sha256="97157c1d0795aef9df40851a7b5b752ad0d02af74f1bf9166a37d08d1df8f740",
        ),
        # 5. 000002：同一句的变体。
        _row(
            "000002", "v-000001",
            verdict="成立", axis="fault", findings=[], defect_step=None,
            unresolved_errors=0,
            reason=("V 回复虽声称逐行核对并称未发现缺陷，但没有记录任何反例构造尝试，"
                    "只有笼统的“未发现缺陷”，按标准不能判为“没问题”。"),
            review_call="60df812a2495", review_pass=1,
            proof_sha256="2125f47ebdbdbc123accca7794dcaf7a5c111249531995432ddbe55755b63521",
        ),
        # 6. 000003：同一句的变体。
        _row(
            "000003", "v-000001",
            verdict="成立", axis="fault", findings=[], defect_step=None,
            unresolved_errors=0,
            reason=("它只笼统声称逐行复核未发现问题，findings 为空"
                    "且没有记录任何反例构造尝试，未达到「没问题」所需的核查证据。"),
            review_call="4ae02b81970b", review_pass=1,
            proof_sha256="367a3ff23070d88359157e7b3df7b4ec7204997607b31d8cf441a3939e3a1544",
        ),
        # 7. 000004：1 条 error（第 5 步）+ 1 条 warning（第 3 步）—— math。
        _row(
            "000004", "v-000001",
            verdict="有毛病", axis="fault",
            findings=[
                _error(5, "C'=(3A+C)/4、c0=4/(3A+C) 均依赖 A；最后一步需 "
                          "A>2/c0=(3A+C)/2，即 A<−C，与 A>1 矛盾。"),
                _warning(3, "从每项 (σ0−β')/|σ0+2iγ−ρ'|² 到 L4 的 "
                            "1/|σ0+2iγ−ρ'| 缺一句 0 ≤ σ0−β' ≤ |σ0+2iγ−ρ'|。"),
            ],
            defect_step=5, unresolved_errors=1,
            reason="回复明确把主缺陷定位在第 (5) 步，并说明 c0 依赖 A 会使条件矛盾。",
            review_call="7b76bd87d8f7", review_pass=1,
            proof_sha256="9a249dda8e7dceb8e53a072a6ae028e61f089d2f52fe109f66f1a314a2256937",
        ),
    ]


def _fault_rows() -> list[dict[str, Any]]:
    return [row for row in rows_98b() if VR.ledger_axis(row) == "fault"]


def _clean_report_gap_copies() -> list[dict[str, Any]]:
    """把 98b 的 4 条 report_gap 改写成「D3 新口径下的 clean 行」。

    这是反真空的对象：老行本身 axis=fault（批 1 不改既有轴，所以它们本身不算票）；
    新口径下同样这 4 条会写成 clean 行 + `fault_kind=""` + `report_gap` 读数。
    """
    copies: list[dict[str, Any]] = []
    for row in _fault_rows():
        if VR.fault_kind_of(row)["cause"] != "report_gap":
            continue
        copy = json.loads(json.dumps(row, ensure_ascii=False))
        copy["secretary_judge"]["axis"] = "clean"
        copy["secretary_judge"]["fault_kind"] = ""
        copy["secretary_judge"]["report_gap"] = "没有写出反例尝试的位置"
        copy["verdict"] = "成立"
        copy["unresolved_errors"] = 0
        copies.append(copy)
    return copies


# ---------------------------------------------------------------- ① 98b 逐条归类


def test_98b_six_faults_are_two_math_four_report_gap() -> None:
    """98b 的 6 条 fault：2 条 math + 4 条 report_gap（report_gap 在 cause 上）。"""
    faults = _fault_rows()
    assert len(faults) == 6, "98b 的 fault 行应有 6 条（夹具与附录 B 对不上）"

    got = {(str(r["statement_id"]), str(r["verification_id"])): VR.fault_kind_of(r)
           for r in faults}
    expected = {
        ("000000", "v-000001"): ("", "report_gap", "legacy_shape"),
        ("000001", "v-000001"): ("math", "", "legacy_math_evidence"),
        ("000001", "v-000003"): ("", "report_gap", "legacy_shape"),
        ("000002", "v-000001"): ("", "report_gap", "legacy_shape"),
        ("000003", "v-000001"): ("", "report_gap", "legacy_shape"),
        ("000004", "v-000001"): ("math", "", "legacy_math_evidence"),
    }
    assert set(got) == set(expected)
    for key, (kind, cause, source) in expected.items():
        reading = got[key]
        assert reading["kind"] == kind, (key, reading)
        assert reading["cause"] == cause, (key, reading)
        assert reading["source"] == source, (key, reading)
    counts = {kind: sum(1 for one in got.values() if one["kind"] == kind)
              for kind in ("math", "")}
    assert counts == {"math": 2, "": 4}, counts
    # 反过来数 cause：4 条 report_gap（这正是业主裁定 ① 的那一档）。
    assert sum(1 for one in got.values() if one["cause"] == "report_gap") == 4


def test_98b_report_gap_rows_only_say_they_did_not_record_a_counterexample() -> None:
    """4 条 report_gap 的 `cause` 依据：行上没有数学证据，fault 的全内容在秘书的 reason 里。"""
    gaps = [VR.fault_kind_of(r) for r in _fault_rows()
            if VR.fault_kind_of(r)["cause"] == "report_gap"]
    assert len(gaps) == 4
    for reading in gaps:
        assert reading["kind"] == ""
        assert reading["source"] == "legacy_shape"
        assert "反例" in reading["why"]
    # 反方向：两条 math 的 kind 依据是行上的数学证据，不是措辞。
    maths = [r for r in _fault_rows() if VR.fault_kind_of(r)["kind"] == "math"]
    assert len(maths) == 2
    for row in maths:
        assert row.get("defect_step") is not None or any(
            str(f.get("level") or "") == "error" for f in row.get("findings") or [])


def test_the_four_report_gap_rows_are_the_four_measured_in_98b() -> None:
    """反真空（判据本体）：这 4 条的 `cause` 必须逐个是 report_gap，且 `kind` 必须为空。

    如果判据把 report_gap 塞回 kind（哪怕值是 `procedural`），这 4 条就不再是
    "不是缺陷"那一档：这一条当场红。
    """
    gaps = [(str(r["statement_id"]), str(r["verification_id"]))
            for r in _fault_rows() if VR.fault_kind_of(r)["cause"] == "report_gap"]
    assert gaps == [
        ("000000", "v-000001"),
        ("000001", "v-000003"),
        ("000002", "v-000001"),
        ("000003", "v-000001"),
    ], gaps
    for row in _fault_rows():
        reading = VR.fault_kind_of(row)
        if reading["cause"] == "report_gap":
            assert reading["kind"] == "", reading


def test_explicit_fault_kind_wins_and_math_evidence_guards_it() -> None:
    """新行显式带 kind ⇒ `source="row"`；带数学证据的 procedural ⇒ 强制折回 math。"""
    explicit = _row(
        "000010", "v-000001", verdict="有毛病", axis="fault",
        findings=[], defect_step=None, unresolved_errors=0,
        reason="V 自己说没有逐行验证。", fault_kind="procedural")
    reading = VR.fault_kind_of(explicit)
    assert (reading["kind"], reading["source"]) == ("procedural", "row")

    guarded = _row(
        "000010", "v-000002", verdict="有毛病", axis="fault",
        findings=[_error(2, "第 2 步缺依据")], defect_step=2, unresolved_errors=1,
        reason="V 说没有逐行验证。", fault_kind="procedural")
    reading = VR.fault_kind_of(guarded)
    assert reading["kind"] == "math"
    assert reading["source"] == "guard:carries_math_evidence"


def test_explicit_contract_is_read_from_the_row() -> None:
    """contract 只从显式 kind 来（旧行不推定它；见 `fault_kind_of` 的 docstring）。"""
    row = _row(
        "000011", "v-000001", verdict="有毛病", axis="fault",
        findings=[], defect_step=None, unresolved_errors=0,
        reason="稿名解析不出。", fault_kind="contract")
    reading = VR.fault_kind_of(row)
    assert (reading["kind"], reading["source"]) == ("contract", "row")


def test_report_gap_is_a_cause_not_a_kind() -> None:
    """业主裁定 ① 的编码：`report_gap` 不在 kind 里，只在 cause 里。"""
    assert "report_gap" not in VR.FAULT_KINDS
    assert "report_gap" not in VR.FAULT_KIND_VALUES
    assert "report_gap" in VR.FAULT_CAUSES


def test_the_key_presence_distinguishes_new_rows_from_legacy_rows() -> None:
    """键在 + 值为空 = 明确的 clean（source=row）；键不在 = 老行（source 为空）。"""
    new_row = _row("000012", "v-000001", verdict="成立", axis="clean",
                   findings=[], defect_step=None, unresolved_errors=0,
                   reason="", fault_kind="", report_gap="没有写出反例尝试的位置")
    reading = VR.fault_kind_of(new_row)
    assert (reading["kind"], reading["cause"], reading["source"]) == ("", "", "row")
    assert reading["report_gap"] == "没有写出反例尝试的位置"
    assert VR.vote_reading(new_row)["vote"] is True

    old_row = _row("000013", "v-000001", verdict="成立", axis="clean",
                   findings=[], defect_step=None, unresolved_errors=0, reason="")
    assert "fault_kind" not in old_row["secretary_judge"]
    reading = VR.fault_kind_of(old_row)
    assert (reading["kind"], reading["cause"], reading["source"]) == ("", "", "")
    assert VR.vote_reading(old_row)["vote"] is True


def test_report_gap_clean_rows_still_vote() -> None:
    """4 条 report_gap 在 clean 形态下都必须算票（`kind=""`，cause 不参与投票）。"""
    copies = _clean_report_gap_copies()
    assert len(copies) == 4
    for row in copies:
        reading = VR.vote_reading(row)
        assert reading["vote"] is True, reading
        assert reading["kind"] == ""
        assert reading["report_gap"] == "没有写出反例尝试的位置"


def test_misclassifying_report_gap_as_a_kind_stops_the_four_votes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 report_gap 打桩成 kind=procedural，4 条算票的 clean 行当场全变不算票。"""
    copies = _clean_report_gap_copies()
    assert [VR.is_a_vote(row) for row in copies] == [True] * 4
    original = VR.fault_kind_of

    def wrong(row):
        reading = original(row)
        if reading.get("report_gap") or reading.get("cause") == "report_gap":
            return {**reading, "kind": "procedural", "cause": "report_gap"}
        return reading

    monkeypatch.setattr(VR, "fault_kind_of", wrong)
    assert [VR.is_a_vote(row) for row in copies] == [False] * 4


# ---------------------------------------------------------------- ② is_a_vote 四条反例


def test_is_a_vote_false_when_checked_is_false() -> None:
    """反例 ①：checked=False（问过、没判成）不是一票。"""
    row = _row("000020", "v-000001", verdict="成立", axis="",
               findings=[], defect_step=None, unresolved_errors=0,
               reason="", checked=False)
    reading = VR.vote_reading(row)
    assert reading["vote"] is False
    assert reading["why"] == "no_judgement"


def test_is_a_vote_false_when_axis_is_fault() -> None:
    """反例 ②：axis=fault 不是一票（哪怕 verdict 写「成立」）。"""
    row = _row("000021", "v-000001", verdict="成立", axis="fault",
               findings=[], defect_step=None, unresolved_errors=0,
               reason="没有记录任何反例构造尝试。")
    reading = VR.vote_reading(row)
    assert reading["vote"] is False
    assert reading["why"] == "axis_fault:report_gap"


def test_is_a_vote_false_when_a_clean_row_carries_a_fault_kind() -> None:
    """反例 ③：clean 行带 fault_kind = 自相矛盾行，fail-closed。"""
    row = _row("000022", "v-000001", verdict="成立", axis="clean",
               findings=[], defect_step=None, unresolved_errors=0,
               reason="", fault_kind="math")
    reading = VR.vote_reading(row)
    assert reading["vote"] is False
    assert reading["why"] == "clean_row_carries_fault_kind"


def test_is_a_vote_false_when_the_row_is_not_signable() -> None:
    """反例 ④：row_signable=False（未解决 error）不是一票。"""
    row = _row("000023", "v-000001", verdict="成立", axis="clean",
               findings=[], defect_step=None, unresolved_errors=1,
               reason="")
    reading = VR.vote_reading(row)
    assert reading["vote"] is False
    assert reading["why"] == "mechanical_gate:unresolved_errors"


def test_is_a_vote_true_for_a_clean_signable_row() -> None:
    """正控：clean + checked + 无 kind + signable ⇒ 一票（98b 的 v-000002）。"""
    row = next(r for r in rows_98b() if r["verification_id"] == "v-000002")
    reading = VR.vote_reading(row)
    assert reading["vote"] is True
    assert reading["why"] == "clean"
    assert (reading["axis"], reading["kind"], reading["checked"]) == ("clean", "", True)
    # 98b 的行有 review_call ⇒ `_is_legacy_row` 为 False；它的"legacy"是 kind_source。
    assert reading["legacy"] is False
    assert reading["kind_source"] == ""


# ---------------------------------------------------------------- ③ 只读 CLI


@pytest.fixture(scope="module")
def audit_cli():
    """按路径加载 `scripts/verify_audit.py`（它不在 `tests/` 下、不是包成员）。"""
    path = ROOT / "scripts" / "verify_audit.py"
    spec = importlib.util.spec_from_file_location("verify_audit", path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_workspace(root: Path, rows: list[dict[str, Any]]) -> None:
    """把夹具行按命题号落成 `<root>/verifications/<sid>.jsonl`（只用于 tmp_path）。"""
    ledger = root / "verifications"
    ledger.mkdir(parents=True, exist_ok=True)
    by_statement: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_statement.setdefault(str(row["statement_id"]), []).append(row)
    for statement_id, group in by_statement.items():
        text = "\n".join(json.dumps(row, ensure_ascii=False) for row in group) + "\n"
        (ledger / f"{statement_id}.jsonl").write_text(text, encoding="utf-8")


def test_verify_audit_reads_the_four_tables(tmp_path: Path, audit_cli) -> None:
    """CLI 读数口：四张表的数字与 98b 的真机读数逐格相等。"""
    _write_workspace(tmp_path, rows_98b())
    reading = audit_cli.audit(tmp_path)
    assert reading["checked"] is True, reading
    assert reading["rows"] == 7

    statements = {(one["statement_id"], one["proof_no"]): one
                  for one in reading["statements"]}
    assert statements[("000000", 1)]["votes"] == 0
    assert statements[("000000", 1)]["stop_kind"] == ""
    assert statements[("000000", 1)]["stop_cause"] == "report_gap"
    assert statements[("000001", 1)]["votes"] == 1
    assert statements[("000001", 1)]["stop_kind"] == ""
    assert statements[("000001", 1)]["stop_cause"] == "report_gap"
    assert statements[("000001", 1)]["need"] == VR.SIGN_STREAK_NEED
    assert statements[("000004", 1)]["stop_kind"] == "math"
    assert statements[("000004", 1)]["stop_cause"] == ""

    assert len(reading["report_gaps"]) == 4
    assert reading["legacy_counts"]["legacy_math_evidence"] == 2
    assert reading["legacy_counts"]["legacy_shape"] == 4
    assert reading["legacy_counts"]["legacy_default"] == 0
    assert reading["legacy_counts"]["row"] == 0

    assert len(reading["flips"]) == 1
    flip = reading["flips"][0]
    assert (flip["clean_verification_id"], flip["clean_review_pass"]) == ("v-000002", 1)
    assert (flip["fault_verification_id"], flip["fault_review_pass"]) == ("v-000003", 2)
    assert flip["fault_kind"] == ""
    assert flip["fault_cause"] == "report_gap"


def test_verify_audit_writes_nothing(tmp_path: Path, audit_cli) -> None:
    """`verify-audit` 不写任何工作区：跑前跑后每个文件的 (mtime, size) 都不变。"""
    _write_workspace(tmp_path, rows_98b())

    def snapshot() -> dict[str, tuple[int, int]]:
        return {str(path.relative_to(tmp_path)): (path.stat().st_mtime_ns, path.stat().st_size)
                for path in tmp_path.rglob("*") if path.is_file()}

    before = snapshot()
    audit_cli.audit(tmp_path)
    assert snapshot() == before


def test_verify_audit_main_prints_four_tables(tmp_path: Path, audit_cli,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    """`main` 的退出码与四张表的抬头（人读形态）。"""
    _write_workspace(tmp_path, rows_98b())
    code = audit_cli.main(["--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "per-statement" in out
    assert "report_gap 清单" in out
    assert "legacy_* 三类计数" in out
    assert "clean → fault" in out
    assert "000001#p1  votes=1/3" in out


def test_verify_audit_main_json_is_the_same_reading(tmp_path: Path, audit_cli,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    """`--json` 与 `audit()` 是同一份读数（不是第二次实现）。"""
    _write_workspace(tmp_path, rows_98b())
    code = audit_cli.main(["--root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["rows"] == 7
    assert payload["legacy_counts"]["legacy_shape"] == 4


def test_verify_audit_unknown_root_exits_two(tmp_path: Path, audit_cli,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    """`2` = 没查成（工作区不在盘上），不是"没有问题"。"""
    code = audit_cli.main(["--root", str(tmp_path / "does-not-exist")])
    err = capsys.readouterr().err
    assert code == 2
    assert "没查成" in err
