# -*- coding: utf-8 -*-
"""判据：`reviewed=True` 但凭据不可定位 ⇒ 不算「已经签过」，V 不许短接（乙-11）。

## 为什么这一条必要

`bit3_already_signed` 是 V 的短接判据：它说「这一份已经签过」⇒ `verify_proof` 不读、
不问模型、直接返回 `signed_bit3=True`。改前它只读 `bits.reviewed` 这一个布尔：
旧行 / repair / 手改行里可能只剩一个裸布尔（`reviewed_by` 空、也没有逐条表的 sha），
于是 V 会把一份没被这一版正文签过的稿当成"已经签过"。

业主 2026-11-04 裁定（乙-11）：在 `signed=True` 之前要求
`reviewed_by.verification_id` / `proof_sha256`（或逐条表里至少一条「为真且有 sha」）
之一；都没有 ⇒ `signed=False`，短接不再发生、照常重审。只收紧这一格，不动
`bits_from_row`（不动全库旧行的档位）。

## 判据（每条都两向）

| # | 造什么 | 期望 |
|---|---|---|
| a | `reviewed=True` + `reviewed_by={"round": 1}`（无 locator） | `signed=False`、`why` 点名"可定位" |
| b | `reviewed_by={"verification_id": …}` | 照旧 `signed=True`（正控） |
| c | `reviewed_by={"proof_sha256": …}` | 照旧 `signed=True`（正控） |
| d | 逐条表「为真且有 sha」、`reviewed_by` 空 | 照旧 `signed=True`（正控） |
| e | 反真空（读口）：把 locator 判据打桩成恒真 | a 的裸布尔回到 `signed=True` |
| f | 集成：裸布尔 + 有效手稿 ⇒ `verify_proof` | 不短接（`reason != already_signed`、问了模型） |
| g | 反真空（集成）：打桩 locator ⇒ 同一调用 | 短接（`already_signed`、零模型调用） |

零模型钱：f/g 用 `_ScriptedSeam`（预置回复、计数），不联网。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import verifications as VR
from agentflow.agent_v import AgentV
from agentflow.agent_v.core import _NoSecretary, _ScriptedSeam
from agentflow.store import Store

PROOF = "1. 由定义直接得到。\n2. 于是结论成立。"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
REL = "reports/f-proof-000000.md"
CLEAN = json.dumps({"verdict": "成立", "findings": []}, ensure_ascii=False)


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _bits(*, reviewed_by: dict, per_sha: str = "") -> dict:
    """一条已审的 bits；`per_sha` 非空时再补一张「逐条表里为真且有 sha」。"""
    bits = EB.bits_of(proof=True, proof_process=PROOF, reviewed=True,
                      reviewed_by=dict(reviewed_by or {}), kind="theorem")
    if per_sha:
        ev = dict(bits.get("evidence") or {})
        ev[EB.REVIEWED_BY_PROOF_KEY] = {"1": True}
        ev[EB.REVIEWED_SHA_BY_PROOF_KEY] = {"1": per_sha}
        bits["evidence"] = ev
        bits = EB.normalize_raw(bits, origin="own_result", kind="theorem")
    return bits


def _put(st: Store, *, reviewed_by: dict, per_sha: str = "") -> dict:
    row = {
        "stmt_id": "000000", "origin": "own_result", "kind": "theorem",
        "label": "一致连续", "statement_full": FULL, "statement_text": "一致连续",
        "proof_text": PROOF, "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题", "created_at": "2026-11-04T00:00:00+08:00",
        "created_by": "test", "bits": _bits(reviewed_by=reviewed_by, per_sha=per_sha),
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _manuscript() -> str:
    return ("# F 的证明手稿：一致连续\n\n- 命题号：stmt:000000\n- 计划：0000\n\n"
            "## 命题\n\n" + FULL + "\n\n## 证明\n\n" + PROOF + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _write_ms(st: Store) -> str:
    p = pathlib.Path(st.root) / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_manuscript(), encoding="utf-8")
    return REL


def _agent(st: Store) -> tuple[AgentV, _ScriptedSeam]:
    seam = _ScriptedSeam([CLEAN])
    return AgentV(st, workspace_root=st.root, llm=seam, secretary=_NoSecretary()), seam


# ====================================================================== a 裸布尔
def test_a_a_review_bit_without_a_locator_is_not_signed(tmp_path: pathlib.Path) -> None:
    """`reviewed=True` + 无 locator 的凭据 ⇒ 不算已签；why 点名"可定位"。"""
    st = _ws(tmp_path)
    row = _put(st, reviewed_by={"round": 1})
    got = VR.bit3_already_signed(row, proof_no=1, proof_text=PROOF)
    assert got["signed"] is False, got
    assert "可定位" in str(got["why"]), got


# ====================================================================== b 正控
def test_b_a_verification_id_locator_still_short_circuits(tmp_path: pathlib.Path) -> None:
    """`reviewed_by.verification_id` 在 ⇒ 照旧已签（修法不误伤真签）。"""
    st = _ws(tmp_path)
    row = _put(st, reviewed_by={"verification_id": "v-000001"})
    got = VR.bit3_already_signed(row, proof_no=1, proof_text=PROOF)
    assert got["signed"] is True, got


# ====================================================================== c 正控
def test_c_a_body_sha_locator_still_short_circuits(tmp_path: pathlib.Path) -> None:
    """`reviewed_by.proof_sha256` 在 ⇒ 照旧已签。"""
    st = _ws(tmp_path)
    row = _put(st, reviewed_by={"proof_sha256": VR.proof_sha(PROOF)})
    got = VR.bit3_already_signed(row, proof_no=1, proof_text=PROOF)
    assert got["signed"] is True, got


# ====================================================================== d 正控
def test_d_a_per_proof_sha_is_a_locator(tmp_path: pathlib.Path) -> None:
    """`reviewed_by` 没有 locator、但逐条表「为真且有 sha」⇒ 照旧已签。"""
    st = _ws(tmp_path)
    row = _put(st, reviewed_by={"round": 1}, per_sha=VR.proof_sha(PROOF))
    got = VR.bit3_already_signed(row, proof_no=1, proof_text=PROOF)
    assert got["signed"] is True, got


# ====================================================================== e 反真空（读口）
def test_e_without_the_locator_gate_the_bare_bit_reads_signed(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把 locator 判据打桩成恒真 ⇒ a 的裸布尔回到 signed（a 量的是这道闸）。"""
    monkeypatch.setattr(VR, "_already_signed_locator", lambda *_a, **_kw: "stub")
    st = _ws(tmp_path)
    row = _put(st, reviewed_by={"round": 1})
    got = VR.bit3_already_signed(row, proof_no=1, proof_text=PROOF)
    assert got["signed"] is True, (
        "打桩之后仍然是 not signed ⇒ a 的拒信不来自 locator 闸（这一条量错了东西）")


# ====================================================================== f 集成
def test_f_verify_proof_re_reviews_a_bare_bit(tmp_path: pathlib.Path) -> None:
    """裸布尔 + 有效手稿 ⇒ 不短接：V 真的问了模型、落了 `review_passes`。"""
    st = _ws(tmp_path)
    _put(st, reviewed_by={"round": 1})
    v, seam = _agent(st)
    got = v.verify_proof("000000", proof_manuscript=_write_ms(st))
    assert got.get("reason") != "already_signed", got
    assert len(got.get("review_passes") or []) >= 1, got
    assert len(seam.prompts) >= 1, "不短接之后一次模型都没问 ⇒ 这一份还是审不了"


# ====================================================================== g 反真空（集成）
def test_g_the_short_circuit_comes_from_the_manuscript_sign(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空（集成）：短接的判据是稿上签块盖住这一份正文（2026-11-08）。

    2026-11-08 之前这一条打桩的是 `bit3_already_signed` 的 locator；V 只对手稿负责
    之后，短接改读 `vsigns.manuscript_sign_standing` —— 所以这里真的盖一块签，看
    同一调用是否零模型短接；再把稿的正文改一个字（sha 变了），看它是否重开审。
    """
    from agentflow import vsigns as VS

    st = _ws(tmp_path)
    _put(st, reviewed_by={"round": 1})
    rel = _write_ms(st)
    raw = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    stamped = VS.stamp_manuscript_sign(
        raw, proof_sha=VR.proof_sha(PROOF), streak=VR.SIGN_STREAK_NEED,
        need=VR.SIGN_STREAK_NEED, verdict="成立", signer="secretary:F",
        at="2026-11-08T00:00:00+08:00",
        ledger="verifications/000000.jsonl#v-000001",
        statement_id="000000", manuscript_id="000000")
    (pathlib.Path(st.root) / rel).write_text(stamped, encoding="utf-8")

    v, seam = _agent(st)
    got = v.verify_proof("000000", proof_manuscript=rel)
    assert got.get("reason") == "already_signed", got
    assert got.get("review_passes") == [], got
    assert len(seam.prompts) == 0, f"短接那一趟还问了 {len(seam.prompts)} 次模型"

    # 反真空：改一个字（正文 sha 变了）⇒ 签块不再盖住这一份 ⇒ 必须重开审。
    changed = stamped.replace(PROOF, PROOF + "\n3. 补上边界情形。")
    assert changed != stamped
    (pathlib.Path(st.root) / rel).write_text(changed, encoding="utf-8")
    v2, seam2 = _agent(st)
    again = v2.verify_proof("000000", proof_manuscript=rel)
    assert again.get("reason") != "already_signed", again
    assert len(seam2.prompts) >= 1, "改稿之后一次模型都没问 ⇒ 短接做宽了"
