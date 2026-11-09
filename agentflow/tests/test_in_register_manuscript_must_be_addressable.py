# -*- coding: utf-8 -*-
"""判据：在册命题的 `proof_manuscript` 必须按号命名（业主 2026-11-04 裁定 · 乙-2）。

## 这一条堵的是什么

V 的在册读稿口（`_registered_manuscript_body`）改前接受任意工作区相对路径。于是
`notes/proof.md` 也能签：`vsigns.manuscript_id_of` 认不出裸稿号 ⇒ 签块第 9 格
`手稿号` 是空串 ⇒ B 的 `manuscript_sign_gate` 一律判 `manuscript_id_missing` ——
V 签了、没人能认，等于白签；而且"按号命名"从硬条件退成了命名口味。

业主口径（乙-2）：V 的在册/未在册读稿口只收 `manuscript_id_of` 认得出号的名字
（`reports/f-proof-*` / `e-proof-*` / `b-proof-*`）；`notes/` 稿必须先走转正
（`fd9a5e33` 的那一步），转正后再签。

## 判据（每条都两向）

| # | 造什么 | 期望 |
|---|---|---|
| a | 在册 + `notes/proof.md`（内容三节齐全） | `checked=False`、`kind=bad_manuscript_name`、detail 指路转正；不问模型、不落签 |
| b | 同一份内容落到 `reports/f-proof-000000.md` | 可签；稿上有 `已签=true` 块；B 的 `manuscript_sign_gate` 认（`resolved`） |
| c | 反真空：把 `manuscript_id_of` 打桩成恒有号 | a 的 `notes/` 稿被放行并签上 —— a 量的是这道闸 |

零模型钱：V 的审阅缝是预置 clean，不联网。
"""
from __future__ import annotations

import contextlib
import json
import pathlib

from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV
from agentflow.store import Store

from test_agent_v_exhaustion_review import _v_secretary

CLEAN = json.dumps({"verdict": "成立", "findings": []}, ensure_ascii=False)
PROOF = "1. 由定义直接得到。\n2. 于是结论成立。"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
NOTES = "notes/proof.md"
NUMBERED = "reports/f-proof-000000.md"


class _CleanSeam:
    """只记调用次数、永远回 clean。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        return SimpleNamespace(text=CLEAN, problem="")


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store) -> dict:
    row = {
        "stmt_id": "000000", "origin": "own_result", "kind": "theorem",
        "label": "一致连续", "statement_full": FULL, "statement_text": "一致连续",
        "proof_text": PROOF, "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题",
        "created_at": "2026-11-04T00:00:00+08:00", "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=PROOF, kind="theorem"),
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _manuscript() -> str:
    return ("# F 的证明手稿：一致连续\n\n- 命题号：stmt:000000\n- 计划：0000\n\n"
            "## 命题\n\n" + FULL + "\n\n## 证明\n\n" + PROOF + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _write(st: Store, rel: str) -> None:
    p = pathlib.Path(st.root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_manuscript(), encoding="utf-8")


@contextlib.contextmanager
def _submitted_by_f():
    with CND.calling_as("t-v-000000", "V", parent_task_id="t-f-000000",
                        parent_role="F"):
        yield


def _agent(st: Store, seam: _CleanSeam) -> AgentV:
    return AgentV(st, workspace_root=st.root, llm=seam, secretary=_v_secretary(st))


def _snapshot(st: Store) -> dict:
    rows = [dict(r) for r in st.rows("statements")]
    bits = dict((rows[0].get("bits") if rows else {}) or {})
    signs = pathlib.Path(st.root) / VS.SIGNS_DIR
    return {
        "reviewed": bool(bits.get("reviewed")),
        "ledger": len(VR.list_verifications(st.root, statement_id="000000")[0]),
        "sign_files": len(list(signs.glob("*.json"))) if signs.is_dir() else 0,
    }


# ====================================================================== a notes
def test_a_a_notes_manuscript_is_refused_with_a_pointer_to_promotion(
        tmp_path: pathlib.Path) -> None:
    """`notes/proof.md` 送审 ⇒ `bad_manuscript_name`；不问模型、不落签，detail 指路转正。"""
    st = _ws(tmp_path)
    _put(st)
    _write(st, NOTES)
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f():
        got = v.verify_proof("000000", proof_manuscript=NOTES)
    assert got.get("checked") is False, got
    assert got.get("kind") == "bad_manuscript_name", got
    assert got.get("reason") == "bad_manuscript_name", got
    detail = str(got.get("detail") or "")
    assert "转正" in detail and "reports/f-proof-" in detail, detail
    assert seam.prompts == [], f"被拒之后还问了 {len(seam.prompts)} 次模型"
    assert _snapshot(st) == {"reviewed": False, "ledger": 0, "sign_files": 0}, _snapshot(st)


# ====================================================================== b 按号稿
def test_b_the_same_body_on_a_numbered_manuscript_is_signed(
        tmp_path: pathlib.Path) -> None:
    """同一份内容落到 `reports/f-proof-000000.md` ⇒ 可签；B 的签块闸认（resolved）。"""
    st = _ws(tmp_path)
    _put(st)
    _write(st, NUMBERED)
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f():
        got = v.verify_proof("000000", proof_manuscript=NUMBERED)
    assert got.get("checked") is True, got
    assert got.get("signed_bit3") is False, got.get("sign_issuance")
    assert got.get("review_write", {}).get("manuscript_signed") is True, got["review_write"]
    assert len(seam.prompts) == VR.SIGN_STREAK_NEED, len(seam.prompts)
    text = (pathlib.Path(st.root) / NUMBERED).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(text, manuscript_path=NUMBERED)
    assert block["found"] is True and block["signed"] is True, block
    assert block["identity_state"] == "resolved", block
    standing = VS.manuscript_sign_standing(
        text, proof_sha=VR.text_sha(PROOF), manuscript_path=NUMBERED)
    assert standing["state"] == "signed", standing
    gate = VS.manuscript_sign_gate(standing, statement_id="000000",
                                   registered=("000000",))
    assert gate["admitted"] is True, gate


# ====================================================================== c 反真空
def test_c_without_the_two_name_gates_the_notes_manuscript_is_signed(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把两道名字闸都打桩 ⇒ a 的 notes 稿被放行并签上。

    2026-11-09（T2 收编）：`sign_carrier_reading` 现在只认表里的四族（`notes/` 与
    `-v2` 都不可签），所以 a 的拒信有两条来源 —— 按号命名闸（`manuscript_id_of`）
    与载体闸（`sign_carrier_reading`）。两道都打桩，a 才应该被放行；只打一道仍有
    另一道在拒，那是判据变强，不是 a 量错了东西。
    """
    monkeypatch.setattr(VS, "manuscript_id_of", lambda _path: "000000")
    monkeypatch.setattr(VS, "sign_carrier_reading", lambda _path: {
        "ok": True, "code": "", "reason": "夹具：把载体闸也打桩", "name": ""})
    st = _ws(tmp_path)
    _put(st)
    _write(st, NOTES)
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f():
        got = v.verify_proof("000000", proof_manuscript=NOTES)
    assert got.get("checked") is True, (
        "打桩之后仍然被拒 ⇒ a 的拒信不来自按号命名闸（这一条量错了东西）：" + str(got))
    assert len(seam.prompts) >= 1, "打桩放行之后一次模型都没问"


# ====================================================================== d 两把尺
def test_d_a_whole_manuscript_as_proof_text_is_refused_not_normalized(
        tmp_path: pathlib.Path) -> None:
    """反真空：`proof_text` 给整份手稿 ⇒ `given != body` 必须拒。

    2026-11-09 T2 收口时曾把 `verifications.proof_sha` 合并成"手稿取小节"的签
    对拍尺，于是这里两边都归一到同一小节，整份手稿被静默读成"与稿里正文同一份"，
    这道闸（问的是"V 拿到的这一段，是不是稿里那一段"）就空了。现在 `given` 走
    `verifications.text_sha`（原样 sha）、`body` 走小节正文 —— 两者必须不同。
    """
    st = _ws(tmp_path)
    _put(st)
    _write(st, NUMBERED)
    manuscript = (pathlib.Path(st.root) / NUMBERED).read_text(encoding="utf-8")
    seam = _CleanSeam()
    v = _agent(st, seam)
    with _submitted_by_f():
        got = v.verify_proof("000000", proof_text=manuscript,
                             proof_manuscript=NUMBERED)
    assert got.get("checked") is False, got
    assert got.get("reason") == "proof_text_mismatch", got
    assert seam.prompts == [], f"被拒之后还问了 {len(seam.prompts)} 次模型"


def test_e_text_sha_and_sign_sha_are_two_rulers() -> None:
    """反真空：两把尺对整份手稿不同、对一段正文相同（T2 收口的定义）。"""
    from agentflow import proofregistry as PR

    manuscript = _manuscript()
    assert VR.text_sha(manuscript) != PR.proof_sha(manuscript), (
        "整份手稿上两把尺同值 ⇒ 它们又合并成了一把")
    assert VR.text_sha(PROOF) == PR.proof_sha(PROOF), (
        "一段证明正文上两把尺不同值 ⇒ 签的对拍尺把正文改写了")
