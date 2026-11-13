# -*- coding: utf-8 -*-
"""判据：D268 批 1 的签读口（`vsigns.sign_reading` / `credential_reading` + `sign-audit`）。

## 这一份在治什么

"有没有签"在过去有五个门槛（秘书门 1 条 clean / B 门 1 条或块 / 收工门 holding /
`review_standing` 3 条 / `vsigns.issue` 3 条同趟），而签文件与手稿块本身零校验：
文件在就算签、块写 3/3 就算签。批 1 只加一个只读读口，把判据改成：

    signed ⇔ 凭据在 ∧ 文件里那句「连续 need/need」能在台账上逐条点出 need 行
             ∧ 每一行自己签得住（`verifications.row_signable`）∧ 对象对得上

八档各一条（外加 `stale` 与 N5 的 `body_state=absent`）：

| # | 造什么 | 期望 |
|---|---|---|
| a | 3 行同一趟 call、pass 1..3、`issue` 写签 | `signed`、votes/need = 3/3 |
| b | 这一版一票都没有 | `unsigned` |
| c | 2 行 clean（同一趟） | `holding`、2/3 |
| d | 3 行 clean、没有签文件 | `unissued`、3/3（事故档） |
| e | pass1 clean、pass2 判 math | `rejected`、0/3 |
| f | pass1 clean、pass2 是 `report_gap`/程序性 | `retry_report`、1/3（不锁、原样再送） |
| g | 签文件 `passes` 只 1 条（手写） | `unbacked`、`only_1_of_3` |
| h | 签文件是别条命题的 | `borrowed` |
| i | 这一版没有行、同号别的版本审过 | `stale` |
| N5 | 不给正文，台账 6 行 fault | `body_state=absent`、state 不是 `unsigned` |

反真空 4 条（"有文件/有块"的四种假形态，改宽判据任一条都应变红）：

1. 文件在、`passes` 只 1 条 ⇒ 不许读成签；
2. `passes` 3 条、而台账 pass 2 是 fault ⇒ 不许读成签；
3. 签文件 `ledger` 指向稿自己 ⇒ `sign_without_ledger`；
4. 没有签文件、只有手稿块自称 3/3 ⇒ `state != signed`（块只是视图）。

全部 tmp 工作区、零模型调用、不读写 `projects/`（真机正控在 `temp/` 的探针与
`scripts/sign_audit.py` 的读数里，见施工报告）。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any, Mapping

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402

TS = "2026-11-02T00:00:00+08:00"
CALL = "call-1"
PROOF = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
PROOF_NEW = "改过一版：\n1. 先证引理。\n2. 由引理得结论。"


# ---------------------------------------------------------------- 夹具

def _statement_row(sid: str, *, proof_no: int = 1) -> dict[str, Any]:
    return {"stmt_id": sid, "kind": "conjecture", "status": "active",
            "label": f"夹具 {sid}", "statement_full": "夹具命题。"}


def _write_ws(root: pathlib.Path, sids: list[str]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "verifications").mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 2,
           "rows": [_statement_row(sid) for sid in sids]}
    (root / "data" / "statements.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _manuscript(root: pathlib.Path, sid: str, text: str = PROOF) -> tuple[str, str, str]:
    """落一份 `reports/f-proof-<号>.md` ⇒ `(相对路径, 全文, 正文 sha)`。

    稿名只有一种形式（没有 `-pN` 后缀）、稿头不写 `- 证明号：`：路径号由 B 的秘书
    在收录时分配，不进稿（2026-11-11 业主口径）。
    """
    rel = f"reports/f-proof-{sid}.md"
    body = ("# 证明手稿（夹具）\n\n"
            f"## 命题\n\n夹具命题。\n\n## 证明\n\n{text}\n\n"
            "## 依赖\n\n| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |\n"
            "|---|---|---|\n")
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel, body, VS._sign_sha(VS.manuscript_proof_body(body))


def _row(sid: str, sha: str, *, no: int = 1, pass_no: int = 1,
         axis: str = "clean", kind: str | None = None,
         cause: str | None = None, verdict: str = "成立",
         findings: list[dict[str, Any]] | None = None,
         defect_step: int | None = None, unresolved: int = 0,
         vid: str | None = None, call: str = CALL,
         manuscript: str = "") -> dict[str, Any]:
    judge: dict[str, Any] = {"checked": True, "axis": axis}
    if kind is not None:
        judge["fault_kind"] = kind
    if cause:
        judge["fault_cause"] = cause
    return {"verification_id": vid or f"v-{pass_no:06d}", "statement_id": sid,
            "stmt_id": sid, "proof_no": no, "proof_sha256": sha,
            "verdict": verdict, "secretary_judge": judge,
            "findings": findings or [], "defect_step": defect_step,
            "unresolved_errors": unresolved, "at": TS,
            "review_call": call, "review_pass": pass_no,
            "manuscript": manuscript}


def _write_ledger(root: pathlib.Path, sid: str, rows: list[dict[str, Any]]) -> None:
    path = root / "verifications" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def _issue(root: pathlib.Path, sid: str, sha: str, rows: list[dict[str, Any]],
           *, no: int = 1, statement_id: str | None = None) -> dict[str, Any]:
    """按真台账的三行发一份签（`vsigns.issue` 的唯一写口）。"""
    need = VR.SIGN_STREAK_NEED
    assert len(rows) == need
    passes = [{"verification_id": str(r["verification_id"]), "at": str(r["at"]),
               "proof_sha256": sha, "review_call": str(r["review_call"]),
               "review_pass": int(r["review_pass"])} for r in rows]
    got = VS.issue(root, artifact_sha=sha, streak=need, need=need,
                   ledger=f"verifications/{sid}.jsonl#{rows[-1]['verification_id']}",
                   statement_id=str(statement_id if statement_id is not None else sid),
                   proof_no=no, passes=passes, at=TS, by="secretary:B")
    assert got.get("written") is True, got
    return got


def _handwritten_sign(root: pathlib.Path, sha: str, *, passes: list[dict[str, Any]],
                      ledger: str, sid: str = "000001", no: int = 1,
                      need: int = 3) -> pathlib.Path:
    """手写一份签文件（反真空夹具：绕过 `vsigns.issue` 的写前闸）。"""
    doc = {"schema": VS.SIGN_SCHEMA, "artifact_sha": sha, "artifact_path": "",
           "ledger": ledger, "statement_id": sid, "proof_no": no,
           "verdict": "成立", "streak": need, "need": need, "passes": passes,
           "objections": [], "at": TS, "written_by": "handwritten"}
    path = root / "out" / "vsigns" / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------- a–i：八档

def test_state_signed_needs_a_recomputable_credential(tmp_path: pathlib.Path) -> None:
    """a：三票同源 + `issue` 写签 ⇒ `signed`、3/3。"""
    _write_ws(tmp_path, ["000001"])
    rel, text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=n, manuscript=rel) for n in (1, 2, 3)]
    _write_ledger(tmp_path, "000001", rows)
    _issue(tmp_path, "000001", sha, rows)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["checked"] is True
    assert got["state"] == "signed", got
    assert (got["votes"], got["need"]) == (3, 3)
    assert got["votes_source"] == "call"
    assert got["body_state"] == "present"
    assert got["credential"]["recomputable"] is True
    assert got["credential"]["got"] == 3
    assert got["sha"] == sha


def test_state_unsigned_when_this_version_was_never_reviewed(
        tmp_path: pathlib.Path) -> None:
    """b：这一版一票都没有 ⇒ `unsigned`（不是"没查成"）。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, _sha = _manuscript(tmp_path, "000001")
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["checked"] is True
    assert got["state"] == "unsigned", got
    assert got["votes"] == 0
    assert "一次都没送过" in got["why"]


def test_state_holding_when_the_streak_is_incomplete(tmp_path: pathlib.Path) -> None:
    """c：2 行 clean、同一趟 ⇒ `holding` 2/3（欠签，不是"没审"）。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=n, manuscript=rel) for n in (1, 2)]
    _write_ledger(tmp_path, "000001", rows)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "holding", got
    assert (got["votes"], got["need"]) == (2, 3)
    assert got["votes_source"] == "call"


def test_state_unissued_when_enough_votes_have_no_sign_file(
        tmp_path: pathlib.Path) -> None:
    """d：够票（3/3）却没有签文件 ⇒ `unissued`（事故档；今天读成 signed）。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=n, manuscript=rel) for n in (1, 2, 3)]
    _write_ledger(tmp_path, "000001", rows)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "unissued", got
    assert (got["votes"], got["need"]) == (3, 3)
    assert VS.sign_of(tmp_path, sha)["found"] is False


def test_state_rejected_when_the_stop_kind_is_math(tmp_path: pathlib.Path) -> None:
    """e：pass1 clean、pass2 判 math ⇒ `rejected`（锁 sha、改稿再送）。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=1, manuscript=rel),
            _row("000001", sha, pass_no=2, axis="fault", kind="math",
                 verdict="有毛病", defect_step=2,
                 findings=[{"level": "error", "step": 2, "kind": "无依据的步骤",
                            "detail": "第 2 步直接用了结论"}], manuscript=rel)]
    _write_ledger(tmp_path, "000001", rows)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "rejected", got
    assert got["votes"] == 1  # pass1 那一票保留；后面的 fault 不抹掉它
    assert got["evidence"]["fault_kind"] == "math"


def test_state_retry_report_when_the_stop_kind_is_procedural(
        tmp_path: pathlib.Path) -> None:
    """f：pass1 clean、pass2 是 report_gap ⇒ `retry_report` 1/3（不锁、原样再送）。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=1, manuscript=rel),
            _row("000001", sha, pass_no=2, axis="fault", kind="procedural",
                 cause="report_gap", verdict="有毛病", manuscript=rel)]
    _write_ledger(tmp_path, "000001", rows)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "retry_report", got
    assert got["votes"] == 1
    assert got["evidence"]["fault_kind"] == ""
    assert "原样再送" in got["why"]


def test_state_unbacked_when_the_file_has_only_one_pass(
        tmp_path: pathlib.Path) -> None:
    """g：手写签文件 `passes` 只 1 条 ⇒ `unbacked`、`only_1_of_3`（文件在不算签）。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=1, manuscript=rel)]
    _write_ledger(tmp_path, "000001", rows)
    _handwritten_sign(tmp_path, sha, ledger="verifications/000001.jsonl#v-000001",
                      passes=[{"verification_id": "v-000001", "at": TS,
                               "proof_sha256": sha, "review_call": CALL,
                               "review_pass": 1}])
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "unbacked", got
    assert got["credential"]["problem"] == "only_1_of_3"
    assert VS.sign_of(tmp_path, sha)["found"] is True


def test_state_borrowed_when_the_sign_is_for_another_statement(
        tmp_path: pathlib.Path) -> None:
    """h：凭据复算通过但它是别条命题的 ⇒ `borrowed`。"""
    _write_ws(tmp_path, ["000001", "000002"])
    rel, _text, sha = _manuscript(tmp_path, "000002")
    rows = [_row("000002", sha, pass_no=n, manuscript=rel) for n in (1, 2, 3)]
    _write_ledger(tmp_path, "000002", rows)
    _issue(tmp_path, "000002", sha, rows)
    rel1, _t1, _s1 = _manuscript(tmp_path, "000001", PROOF_NEW)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel1)
    # 000001 这一版没有行、也没有签 ⇒ 不是"借光"；用同一份正文问才算借光。
    assert got["state"] == "unsigned", got
    got2 = VS.sign_reading(tmp_path, statement_id="000001", proof_text=PROOF)
    assert got2["state"] != "signed"
    # 同一 sha、问成 000001：凭据复算通过、对象不符 ⇒ borrowed。
    got3 = VS.sign_reading(tmp_path, statement_id="000001", proof_text=PROOF, proof_no=1)
    # 000001 没有台账行，但凭据这一支先判 ⇒ borrowed（不因没有行而折成 stale）。
    assert got3["state"] == "borrowed", got3
    assert "借光" in got3["why"]


def test_state_stale_when_the_reviewed_version_is_older(
        tmp_path: pathlib.Path) -> None:
    """i：这一版没有行、同号旧版审过 ⇒ `stale`（签的是旧版 / 待重送）。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha_new = _manuscript(tmp_path, "000001", PROOF_NEW)
    sha_old = VS._sign_sha(PROOF)
    rows = [_row("000001", sha_old, pass_no=1, manuscript=rel)]
    _write_ledger(tmp_path, "000001", rows)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "stale", got
    assert got["sha"] == sha_new
    assert got["evidence"]["covering"] == 0


def test_n5_no_body_still_reads_the_ledger_instead_of_unsigned(
        tmp_path: pathlib.Path) -> None:
    """N5：`proof_text=""`、台账 6 行 fault ⇒ `body_state=absent` 且 state 不是 unsigned。"""
    _write_ws(tmp_path, ["000001"])
    _rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=n, axis="fault", kind="math",
                 verdict="有毛病", defect_step=1, manuscript="")
            for n in range(1, 7)]
    _write_ledger(tmp_path, "000001", rows)
    got = VS.sign_reading(tmp_path, statement_id="000001", proof_text="", proof_no=1)
    assert got["body_state"] == "absent", got
    assert got["state"] != "unsigned", got
    assert got["state"] == "rejected", got
    assert got["sha"] == sha
    assert "台账最后一行" in got["body_why"]


# ---------------------------------------------------------------- 反真空 4 条

def test_anti_vacuum_a_one_pass_file_is_not_a_sign(tmp_path: pathlib.Path) -> None:
    """反真空 1：文件在、`passes` 只 1 条 ⇒ 不许读成签。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=1, manuscript=rel)]
    _write_ledger(tmp_path, "000001", rows)
    _handwritten_sign(tmp_path, sha, ledger="verifications/000001.jsonl#v-000001",
                      passes=[{"verification_id": "v-000001", "at": TS,
                               "proof_sha256": sha, "review_call": CALL,
                               "review_pass": 1}])
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "unbacked", got
    assert got["credential"]["problem"].startswith("only_1_of_3")


def test_anti_vacuum_a_fault_pass_inside_the_three_is_not_a_sign(
        tmp_path: pathlib.Path) -> None:
    """反真空 2：`passes` 3 条、而台账 pass 2 是 fault ⇒ 不许读成签。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=1, manuscript=rel),
            _row("000001", sha, pass_no=2, axis="fault", kind="math",
                 verdict="有毛病", defect_step=3, manuscript=rel),
            _row("000001", sha, pass_no=3, manuscript=rel)]
    _write_ledger(tmp_path, "000001", rows)
    # 写前闸只看最后一转的背书 ⇒ 这一份"三票"能被 `issue` 写出来（真机同族）。
    _issue(tmp_path, "000001", sha, rows)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "unbacked", got
    assert got["credential"]["problem"].startswith("row_not_signable")


def test_anti_vacuum_a_self_referential_ledger_is_not_a_sign(
        tmp_path: pathlib.Path) -> None:
    """反真空 3：签文件 `ledger` 指向稿自己 ⇒ `sign_without_ledger`（今天 10 份的形态）。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    _handwritten_sign(
        tmp_path, sha, ledger=f"{rel}#V签",
        passes=[{"verification_id": f"v-{n:06d}", "at": TS, "proof_sha256": sha,
                 "review_call": CALL, "review_pass": n} for n in (1, 2, 3)])
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "unbacked", got
    assert got["credential"]["problem"] == "sign_without_ledger"


def test_anti_vacuum_a_block_without_a_file_is_not_a_sign(
        tmp_path: pathlib.Path) -> None:
    """反真空 4：没有签文件、只有手稿块自称 3/3 ⇒ `state != signed`。"""
    _write_ws(tmp_path, ["000001"])
    rel, text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=1, manuscript=rel)]
    _write_ledger(tmp_path, "000001", rows)
    stamped = VS.stamp_manuscript_sign(
        text, proof_sha=sha, streak=3, need=3, verdict="成立",
        signer="secretary:B", at=TS,
        ledger="verifications/000001.jsonl#v-000001",
        statement_id="000001", manuscript_id="000001")
    (tmp_path / rel).write_text(stamped, encoding="utf-8")
    assert VS.manuscript_sign_standing(
        stamped, proof_sha=sha, manuscript_path=rel)["state"] == "signed"
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "holding", got
    assert (got["votes"], got["need"]) == (1, 3)
    assert VS.sign_of(tmp_path, sha)["found"] is False


def test_a_legacy_sign_file_recomputes_by_counting_back(
        tmp_path: pathlib.Path) -> None:
    """正控 2（老形态）：`passes` 不带号 ⇒ 锚点往前数 3 行、同 sha、每行签得住 ⇒ signed。"""
    _write_ws(tmp_path, ["000001"])
    rel, _text, sha = _manuscript(tmp_path, "000001")
    rows = [_row("000001", sha, pass_no=0, vid=f"v-{n:06d}", manuscript=rel)
            for n in (1, 2, 3)]
    for row in rows:
        row["review_call"] = ""
        row["review_pass"] = None
    _write_ledger(tmp_path, "000001", rows)
    _handwritten_sign(
        tmp_path, sha, ledger="verifications/000001.jsonl#v-000003",
        passes=[{"verification_id": f"v-{n:06d}", "at": TS, "proof_sha256": sha}
                for n in (1, 2, 3)], need=3)
    got = VS.sign_reading(tmp_path, statement_id="000001", manuscript_path=rel)
    assert got["state"] == "signed", got
    assert got["votes_source"] == "legacy"
    assert (got["votes"], got["need"]) == (3, 3)


def test_the_state_word_list_covers_every_branch() -> None:
    """反真空：八档 + `retry_report` + `stale` + `unreadable` 都必须在词表里。"""
    assert set(VS.SIGN_READING_WORDS) == {
        "signed", "unissued", "holding", "rejected", "retry_report", "stale",
        "unbacked", "borrowed", "unsigned", "unreadable"}
    assert tuple(VS.BODY_STATE_WORDS) == ("present", "absent", "unreadable")


def test_filed_and_abandoned_are_read_from_the_statement_row(
        tmp_path: pathlib.Path) -> None:
    """`filed` / `abandoned` 两格（批 2 接 store）：签是事实、放弃是另一根轴。"""
    from agentflow import evidencebits as EB
    from agentflow import statementabandon as SA
    from agentflow.store import Store

    from conftest import seed_statement_row

    st = Store(tmp_path / "ws")
    st.init()
    rel, _text, sha = _manuscript(st.root, "000001")
    bits = EB.bits_of(proof=True, proof_process=PROOF, kind="theorem")
    ev = dict(bits.get("evidence") or {})
    ev[EB.REVIEWED_BY_PROOF_KEY] = {str(1): True}
    bits["evidence"] = ev
    seed_statement_row(
        st, proof_text=PROOF, statement_full="夹具命题。", statement_text="夹具命题",
        kind="theorem", label="filed-abandoned", origin="own_result",
        evidence_kind="heuristic", status="abandoned",
        quote_reason=SA.abandon_marker(at=TS, reason="夹具：明确放弃"),
        bits=bits, stmt_id="000001")
    rows = [_row("000001", sha, pass_no=n, manuscript=rel) for n in (1, 2, 3)]
    _write_ledger(st.root, "000001", rows)
    _issue(st.root, "000001", sha, rows)
    got = VS.sign_reading(st.root, statement_id="000001", manuscript_path=rel, store=st)
    assert got["state"] == "signed", got
    assert got["filed"] is True, got["filed_why"]
    assert got["abandoned"] is True, got["filed_why"]
    # 没有 store ⇒ 两格都是 None（没查成，不是「没收录 / 没放弃」）
    bare = VS.sign_reading(st.root, statement_id="000001", manuscript_path=rel)
    assert bare["filed"] is None and bare["abandoned"] is None, bare


# ---------------------------------------------------------------- 只读 CLI

@pytest.fixture(scope="module")
def audit_cli():
    """按路径加载 `scripts/sign_audit.py`（它不在 `tests/` 下、不是包成员）。"""
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "sign_audit.py"
    spec = importlib.util.spec_from_file_location("sign_audit", path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cli_workspace(root: pathlib.Path) -> None:
    """一个工区，七张表各至少一条（v. 上面的八档）。

    每条命题的正文互不相同：签是按正文 sha 命名的，五条共用一段正文会让
    「一条命题的签」被另一条看到（那是 `borrowed` 的形态，不是这里要测的）。
    """
    _write_ws(root, ["000001", "000002", "000003", "000004", "000005", "000006"])

    def text_for(sid: str) -> str:
        return f"证明 {sid}：\n1. 由定义直接得到。\n2. 由 1 得结论。"

    # 000001：signed
    rel1, _t1, sha1 = _manuscript(root, "000001", text_for("000001"))
    rows1 = [_row("000001", sha1, pass_no=n, manuscript=rel1) for n in (1, 2, 3)]
    _write_ledger(root, "000001", rows1)
    _issue(root, "000001", sha1, rows1)
    # 000002：holding ⇒ legacy_clean_only
    rel2, _t2, sha2 = _manuscript(root, "000002", text_for("000002"))
    _write_ledger(root, "000002", [_row("000002", sha2, pass_no=1, manuscript=rel2)])
    # 000003：unbacked（手写文件 passes 只 1 条）
    rel3, _t3, sha3 = _manuscript(root, "000003", text_for("000003"))
    _write_ledger(root, "000003", [_row("000003", sha3, pass_no=1, manuscript=rel3)])
    _handwritten_sign(root, sha3, sid="000003",
                      ledger="verifications/000003.jsonl#v-000001",
                      passes=[{"verification_id": "v-000001", "at": TS,
                               "proof_sha256": sha3, "review_call": CALL,
                               "review_pass": 1}])
    # 000004：块自称 3/3、没有签文件 ⇒ view_conflict（台账那一转判 fault，不进 legacy_clean_only）
    rel4, text4, sha4 = _manuscript(root, "000004", text_for("000004"))
    _write_ledger(root, "000004", [_row("000004", sha4, pass_no=1, axis="fault",
                                        kind="math", verdict="有毛病", defect_step=1,
                                        manuscript=rel4)])
    stamped = VS.stamp_manuscript_sign(
        text4, proof_sha=sha4, streak=3, need=3, verdict="成立",
        signer="secretary:B", at=TS, ledger="verifications/000004.jsonl#v-000001",
        statement_id="000004", manuscript_id="000004")
    (root / rel4).write_text(stamped, encoding="utf-8")
    # 000005：unissued
    rel5, _t5, sha5 = _manuscript(root, "000005", text_for("000005"))
    _write_ledger(root, "000005",
                  [_row("000005", sha5, pass_no=n, manuscript=rel5) for n in (1, 2, 3)])
    # 000006：正文与 000001 同一段（拿 000001 的签来问）⇒ borrowed
    _manuscript(root, "000006", text_for("000001"))


def test_sign_audit_reads_the_seven_tables(tmp_path: pathlib.Path, audit_cli) -> None:
    _cli_workspace(tmp_path)
    reading = audit_cli.audit(tmp_path)
    assert reading["checked"] is True, reading
    assert reading["summary"]["workspaces"] == 1
    assert reading["summary"]["signed"] == 1
    assert reading["summary"]["unissued"] == 1
    assert reading["summary"]["unbacked"] == 1
    assert reading["summary"]["borrowed"] == 1
    assert reading["summary"]["view_conflict"] == 1
    assert reading["summary"]["legacy_clean_only"] == 1
    assert reading["summary"]["unverifiable_sign_files"] == 1
    assert [one["statement_id"] for one in reading["signed"]] == ["000001"]
    assert reading["borrowed"][0]["statement_id"] == "000006"
    assert reading["unverifiable_sign_files"][0]["code"].startswith("only_1_of_3")
    conflict = reading["view_conflict"][0]
    assert conflict["statement_id"] == "000004"
    assert (conflict["block_streak"], conflict["block_need"]) == (3, 3)


def test_sign_audit_writes_nothing(tmp_path: pathlib.Path, audit_cli) -> None:
    """只读判据：跑前跑后每个文件的 (mtime_ns, size) 都不变。"""
    _cli_workspace(tmp_path)

    def snapshot() -> dict[str, tuple[int, int]]:
        return {str(path.relative_to(tmp_path)): (path.stat().st_mtime_ns,
                                                  path.stat().st_size)
                for path in tmp_path.rglob("*") if path.is_file()}

    before = snapshot()
    audit_cli.audit(tmp_path)
    assert snapshot() == before


def test_sign_audit_main_prints_the_tables(tmp_path: pathlib.Path, audit_cli,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    _cli_workspace(tmp_path)
    code = audit_cli.main(["--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "== 1. signed" in out
    assert "== 5. view_conflict" in out
    assert "== 7. unverifiable_sign_files" in out
    assert "statement_id=000001" in out


def test_sign_audit_main_json_is_the_same_reading(
        tmp_path: pathlib.Path, audit_cli,
        capsys: pytest.CaptureFixture[str]) -> None:
    _cli_workspace(tmp_path)
    code = audit_cli.main(["--root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["summary"]["signed"] == 1
    assert len(payload["readings"]) >= 6
    states = {one["state"] for one in payload["readings"]}
    assert {"signed", "holding", "unissued", "borrowed", "unbacked"} <= states


def test_sign_audit_unknown_root_exits_two(tmp_path: pathlib.Path, audit_cli,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    code = audit_cli.main(["--root", str(tmp_path / "does-not-exist")])
    err = capsys.readouterr().err
    assert code == 2
    assert "没查成" in err
