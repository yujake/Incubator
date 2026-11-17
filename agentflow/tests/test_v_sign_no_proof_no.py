# -*- coding: utf-8 -*-
"""V 签侧退役 `proof_no`：正控 / 老文件兼容 / B 接住 / 反真空（业主 2026-11-11）。

业主逐字（这一批的总口径）：

```text
「proof_no 确实该退役，因为已经让 B 秘书收录时现看了，手稿产出侧和 V 签侧甚至呈递侧可退役，
  台账不能退役，还要确认 B 秘书确实能接住（也要彩排）。」
```

所以本批判据只钉 V 签侧的写：新签文件 / `issued.json` 派生项 / 新 verifications 行
不再产生 `proof_no`；读侧对老文件里已有的那一格照旧读（不删能力）。身份靠三样：

1. 正文 sha（签文件 `artifact_sha` / 台账行 `proof_sha256`）；
2. 手稿路径（`artifact_path`，稿号由 `signed_table` 从路径现读成 `manuscript_id`）；
3. `statement_id`（收录之后；未在册那一档是空串，合法的）。

## 判据（每条都带"它能怎么红"）

| # | 造什么 | 期望 | 它能怎么红 |
|---|---|---|---|
| a | 新发一张 canonical 签（三转成立） | 签文件 / `issued.json` / verifications 新行都没有 `proof_no`；sha / 稿号 / 命题号 / verdict 都在 | 写侧回潮（谁再写一格）⇒ 红 |
| b | 手工造一份老签文件（带 `proof_no=2`）+ 老台账行 | 读口照旧读出（`proof_no`、sha、`statement_id`）；认签 / 冻结 / 拿签稿表都不受影响 | 读侧把老格删掉 ⇒ 红 |
| c | F 交卷 → V 未在册签 → B 收录（预演） | B 认签 `applied=True`；行上 `manuscript_id` / `reviewed` / `grade` 都对 | B 依赖签文件里的 `proof_no` 才接得住 ⇒ 红 |
| d | 反真空：把 `proof_no` 加回 a 的签文件 | a 的读数当场红 | a 的"没有这一格"只是恒真 ⇒ 红 |

零模型调用（V 的审阅缝是预置回复）；不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import evidencebits as EB
from agentflow import manuscriptfreeze as MF
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_v import AgentV
from agentflow.store import Store

from _proof_manuscript_fixture import write_proof_manuscript
from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam
from test_unregistered_sign_is_the_main_path import _clean_secretary
from conftest import ensure_basis_lit, ensure_basis_stmt

TS = "2026-11-11T00:00:00+08:00"
SID = "000081"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
PROOF = ("1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n"
         "2. 由第 1 步直接得到结论。")
REL = f"reports/f-proof-{SID}.md"
_CLEAN = {"checked": True, "axis": "clean", "decision": "没问题", "reason": "判据：clean"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store) -> dict:
    """落一条在册命题（只造这一行；正文/五元位从真实现算）。"""
    row = {
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
        "stmt_id": SID, "origin": "own_result", "source_lit_id": ensure_basis_lit(st), "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": FULL,
        "statement_text": "弦长函数不是常值", "proof_text": PROOF,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=PROOF, kind="theorem"),
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _sign_once(st: Store) -> str:
    """三转「成立」⇒ 一张 canonical 签。返回正文 sha。"""
    _put(st)
    rel = write_proof_manuscript(st.root, SID, PROOF, statement_full=FULL)
    assert rel == REL, rel
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            st.root, statement_id=SID, proof_text=PROOF,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", store=st, proof_no=1,
            manuscript=REL,
            object_sha256=VR.text_sha(PROOF), object_path=REL,
            secretary_judge=dict(_CLEAN))
    return VR.text_sha(PROOF)


def _a_problems(st: Store, sha: str) -> list[str]:
    """a 的机器判据（正控与反真空共用同一份读数，避免两处各说各的）。"""
    problems: list[str] = []
    sign = json.loads(VS.sign_path(st.root, sha).read_text(encoding="utf-8"))
    if "proof_no" in sign:
        problems.append(f"签文件仍写着 proof_no={sign.get('proof_no')!r}")
    for key in ("artifact_sha", "artifact_path", "statement_id", "verdict"):
        if key not in sign:
            problems.append(f"签文件缺身份格 {key}")
    if str(sign.get("artifact_sha") or "") != sha:
        problems.append("签文件的 artifact_sha 不是这一份正文的 sha")
    if str(sign.get("verdict") or "") != "成立":
        problems.append("签文件的 verdict 不是「成立」")

    issued = VS.load_index(st.root)[0] or {}
    for entry in (issued.get("signs") or []):
        if "proof_no" in entry:
            problems.append(f"issued.json 的派生项仍写着 proof_no={entry.get('proof_no')!r}")
        for key in ("artifact_sha", "statement_id", "verdict"):
            if key not in entry:
                problems.append(f"issued.json 的派生项缺 {key}")

    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    if bad:
        problems.append(f"台账有坏行：{bad[:2]}")
    for row in rows:
        if "proof_no" in row:
            problems.append(f"verifications 新行仍写着 proof_no={row.get('proof_no')!r}")
        for key in ("proof_sha256", "stmt_id", "statement_id", "verdict"):
            if key not in row:
                problems.append(f"verifications 新行缺 {key}: {sorted(row)}")
    if not rows:
        problems.append("三转成立却没有 verifications 行")

    table = VS.signed_table(st.root)
    entries = [dict(e) for e in (table.get("entries") or [])]
    if len(entries) != 1:
        problems.append(f"拿签稿表不是恰好 1 行：{len(entries)}")
    else:
        one = entries[0]
        if str(one.get("artifact_sha") or "") != sha:
            problems.append("拿签稿表的 artifact_sha 不是这一份正文的 sha")
        if str(one.get("manuscript_id") or "") != SID:
            problems.append(f"拿签稿表的 manuscript_id 不是稿号 {SID}：{one.get('manuscript_id')!r}")
        if str(one.get("statement_id") or "") != SID:
            problems.append("拿签稿表的 statement_id 不是这一条命题")
        if str(one.get("verdict") or "") != "成立":
            problems.append("拿签稿表的 verdict 不是「成立」")
    return problems


# ============================================================ a 正控：新写不再产生
def test_a_a_new_sign_writes_no_proof_no_but_keeps_the_three_identities(tmp_path):
    """a：新签 ⇒ 签文件 / issued.json / verifications 新行都没有 `proof_no`。

    而三样身份一格不少：正文 sha（`artifact_sha` / `proof_sha256`）、稿号
    （`artifact_path` ⇒ `signed_table.manuscript_id`）、`statement_id`，外加 verdict。
    """
    st = _ws(tmp_path)
    sha = _sign_once(st)

    sign = json.loads(VS.sign_path(st.root, sha).read_text(encoding="utf-8"))
    assert "proof_no" not in sign, sign
    assert sign["artifact_sha"] == sha and sign["artifact_path"] == REL, sign
    assert sign["statement_id"] == SID and sign["verdict"] == "成立", sign
    # 逐转读数照旧：三票的 sha 都在（不许为省事把 sha / streak 一起删）。
    assert int(sign["streak"]) == int(VR.SIGN_STREAK_NEED) == int(sign["need"]), sign
    assert {str(p.get("proof_sha256") or "") for p in sign["passes"]} == {sha}, sign["passes"]

    issued = VS.load_index(st.root)[0] or {}
    assert [e.get("artifact_sha") for e in issued.get("signs") or []] == [sha], issued
    for entry in issued.get("signs") or []:
        assert "proof_no" not in entry, entry
        assert set(entry) == set(VS.ENTRY_KEYS), (sorted(entry), sorted(VS.ENTRY_KEYS))

    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not bad and len(rows) == int(VR.SIGN_STREAK_NEED), (bad, rows)
    for row in rows:
        assert "proof_no" not in row, row
        assert row["proof_sha256"] == sha and row["stmt_id"] == SID, row
        assert row["statement_id"] == SID and row["verdict"] == "成立", row
        assert row["object_sha256"] == sha and row["object_path"] == REL, row

    assert _a_problems(st, sha) == []


# ============================================================ b 老文件兼容
def _old_sign(st: Store, sha: str) -> dict:
    """手工造一份 2026-11-11 之前的签：`proof_no=2` + 老形态 passes（无 review_call）。"""
    rows, _bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    doc = {
        "schema": VS.SIGN_SCHEMA,
        "artifact_sha": sha,
        "artifact_path": REL,
        "artifact_sha_rule": VS.ARTIFACT_SHA_RULE,
        "ledger": f"verifications/{SID}.jsonl#{rows[-1]['verification_id']}",
        "statement_id": SID,
        "proof_no": 2,
        "verdict": "成立",
        "streak": int(VR.SIGN_STREAK_NEED),
        "need": int(VR.SIGN_STREAK_NEED),
        "passes": [{"verification_id": str(r["verification_id"]),
                    "at": str(r["at"] or TS),
                    "proof_sha256": sha} for r in rows],
        "objections": [],
        "source_note": VS.PASSES_SOURCE_NOTE,
        "at": TS,
        "written_by": "secretary:F",
        "envelope": {"kind": VS.ENVELOPE_KIND, "to": "secretary:F",
                     "at": TS, "issued_by": "V"},
    }
    path = VS.sign_path(st.root, sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    VS.rebuild_index(st.root)
    return doc


def _old_ledger(st: Store) -> None:
    """把三行新台账改写成老形态：每行补 `proof_no=2`（模拟老盘文件）。"""
    path = VR.verification_ledger_path(st.root, SID)
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        row["proof_no"] = 2
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                            for r in rows), encoding="utf-8")


def test_b_an_old_sign_with_proof_no_still_reads_and_freezes(tmp_path):
    """b：老签文件（带 `proof_no`）读得出；认签 / 冻结 / 拿签稿表都不受影响。"""
    st = _ws(tmp_path)
    _put(st)
    write_proof_manuscript(st.root, SID, PROOF, statement_full=FULL)
    # 先按老口径落三行（只追加、不翻位，避免 canonical 签文件抢先落盘）。
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            st.root, statement_id=SID, proof_text=PROOF,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", store=None, proof_no=2, manuscript=REL,
            secretary_judge=dict(_CLEAN))
    _old_ledger(st)
    sha = VR.text_sha(PROOF)
    old = _old_sign(st, sha)

    got = VS.sign_of(st.root, sha)
    assert got["checked"] and got["found"], got
    assert int(got["sign"]["proof_no"]) == 2, got["sign"]
    assert got["sign"]["artifact_sha"] == sha, got["sign"]

    cred = VS.credential_reading(st.root, sha)
    assert cred["found"] and cred["recomputable"] is True, cred
    assert cred["tier"] == "legacy" and int(cred["got"]) == int(VR.SIGN_STREAK_NEED), cred

    reading = VS.sign_reading(st.root, statement_id=SID, proof_text=PROOF, proof_no=2)
    assert reading["state"] == "signed", reading
    assert int(reading["proof_no"]) == 2, reading

    table = VS.signed_table(st.root)
    assert table["checked"] and table["count"] == 1, table
    row = dict(table["entries"][0])
    assert row["artifact_sha"] == sha and row["manuscript_id"] == SID, row
    assert row["statement_id"] == SID and row["verdict"] == "成立", row

    frozen = MF.freeze_reading(st.root, REL)
    assert frozen["state"] == "signed" and frozen["frozen"] is True, frozen
    assert frozen["sign_sha"] == sha, frozen

    # 老行的 `proof_no` 读得出（读侧不许把这一格删掉）。
    rows, _bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert [int(VR.proof_no_of(r)) for r in rows] == [2, 2, 2], rows
    assert old["proof_no"] == 2


# ============================================================ c B 接住（预演）
def test_c_b_catches_an_unregistered_sign_without_proof_no(tmp_path):
    """c：F 交卷 → V 未在册签 → B 收录；B 认签仍 `applied=True`，行人三格都对。

    这一条量的是「B 不靠 proof_no 也能接住」：签文件里没有任何 `proof_no`，
    B 只按正文 sha 从 pending 台账认领。
    """
    st = _ws(tmp_path)
    # ---- F 交卷：一份未在册的三节手稿（`reports/f-proof-000000.md`）----
    bman = ("# F 的证明手稿：一致连续\n\n"
            "## 命题\n\n"
            f"{FULL}\n\n"
            "## 证明\n\n"
            f"{PROOF}\n\n"
            + _DS.render_dependency_section([]))
    rel = "reports/f-proof-000000.md"
    target = pathlib.Path(st.root) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(bman, encoding="utf-8")
    body = str(_DS.proof_body(bman)).strip("\n")
    sha = VR.text_sha(body)

    # ---- V 未在册签：三转干净 + 收方秘书落块 ----
    v = AgentV(st, workspace_root=st.root, llm=_ReviewSeam([CLEAN_REPLY]),
               secretary=_clean_secretary(st))
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        signed = v.verify_proof(proof_manuscript=rel)
    assert signed.get("kind") == "proof_unregistered_signed", signed
    assert signed.get("verdict") == "成立", signed

    sign = json.loads(VS.sign_path(st.root, sha).read_text(encoding="utf-8"))
    assert "proof_no" not in sign, sign
    assert sign["artifact_sha"] == sha and sign["artifact_path"] == rel, sign
    pending_base = pathlib.Path(st.root) / "verifications" / "pending"
    pending = [json.loads(line) for p in sorted(pending_base.glob("*.jsonl"))
               for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(pending) == int(VR.SIGN_STREAK_NEED), pending
    for row in pending:
        assert "proof_no" not in row, row
        assert row["proof_sha256"] == sha and row["object_path"] == rel, row

    # ---- B 收录：从稿拿签 ----
    b = AgentB(st, extractor=None, extract_text=None)
    # `proof_manuscript` 给工作区相对路径（B 认路径、从盘上读，并据此记下稿号）；
    # 正文三格仍逐字给，避免这一步变成"指针收录"而绕过本判据要量的认签。
    got = b.register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=body,
        proof_manuscript=rel, kind="theorem",
        label="探针命题", origin="own_result", source_lit_id=ensure_basis_lit(st), evidence_kind="heuristic",
        quote_verified=None,
        quote_reason="判据：自产证明，没有第二份文本可比对",
        line_range={"label": rel})
    assert got.get("ok") is True, got
    v_sign = dict(got.get("v_sign") or {})
    assert v_sign.get("applied") is True, v_sign

    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1, rows
    row = rows[0]
    assert str(row.get("manuscript_id") or "") == VS.manuscript_id_of(rel), row
    assert dict(row.get("bits") or {}).get("reviewed") is True, row.get("bits")
    assert str(dict(row.get("bits") or {}).get("grade") or "") == "pre_theorem", row.get("bits")
    # 台账不能退役：B 的 statements 行仍可记它自己的证明号（本判据不要求它消失）。
    assert int(VR.proof_no_of(row) or 0) in (0, 1), row.get("proof_no")


# ============================================================ d 反真空
def test_d_putting_proof_no_back_into_the_sign_file_turns_a_red(tmp_path):
    """d：把 `proof_no` 加回签文件 ⇒ a 的读数当场红（"没有这一格"不是恒真）。"""
    st = _ws(tmp_path)
    sha = _sign_once(st)
    assert _a_problems(st, sha) == []

    path = VS.sign_path(st.root, sha)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["proof_no"] = 1
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")

    problems = _a_problems(st, sha)
    assert problems, "把 proof_no 加回签文件之后 a 仍然全绿 ⇒ 「没有这一格」是恒真"
    assert any("签文件" in p and "proof_no" in p for p in problems), problems
