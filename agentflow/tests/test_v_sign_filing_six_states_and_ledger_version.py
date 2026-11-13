# -*- coding: utf-8 -*-
"""判据②：两格四态实为六档，且「册里没有证明行」与「册里是旧版」必须分开。

## 改前的两处错（2026-11-08，业主让核的 file:line）

- `vsigns.py` 的状态表写着六档，但实现里 `matched_no == 0` 一律归
  `signed_stale_in_ledger` ⇒ 真实新命题（B 收录前，`statements` 行上
  `proof_text=""`）永远读不到 `signed_pending_filing`（它被误报成"册里是旧版"）；
- stale 档只说"册里没有盖住这一份正文的证明行"，不给出册里现行是哪一版 ——
  读的人分不清"旧到哪一版"。

## 这一份钉的六档 + 两条反真空

| 档 | 造什么 | 期望 |
|---|---|---|
| `filed` | 稿上签 + 册里同 sha 且第 3 位为真 | `filed=True` |
| `signed_pending_filing`(无证明行) | 新命题（`proof_text=""`）+ 稿上签 | `pending`、`proof_rows==0` |
| `signed_pending_filing`(位没翻) | 册里有这一份正文的行、第 3 位为假 | `pending`、`proof_no==1` |
| `signed_stale_in_ledger` | 册里 #p1 是旧版、稿上签的是新版 | `stale` + 册里现行 `proof_no/sha` |
| `unsigned` | 稿上没签、册里也没位 | `unsigned` |
| `abandoned` | 明确放弃标记 | `abandoned` |
| `unreadable` | 没给 store（这一格没查成） | `unreadable`，`filed=None` |

反真空 ①：新命题那一档若退回"`matched_no==0` ⇒ stale"，`pending` 那两条立刻红。
反真空 ②：册里现行那一版必须真是最新带正文的那一份（多份证明那一格）。

零模型调用、全部 tmp 工作区、不读写 `projects/`。
"""
from __future__ import annotations

import pathlib

from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import statementabandon as SA
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.store import Store

from conftest import seed_statement_row

PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
SID = "000000"
REL = f"reports/f-proof-{SID}.md"
SHA = VS._sign_sha(PROOF)
TS = "2026-11-08T00:00:00+08:00"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _manuscript(st: Store, proof: str = PROOF, *, full: str = FULL) -> str:
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (f"# 证明手稿\n\n\n"
            f"## 命题\n\n{full}\n\n"
            f"## 证明\n\n{proof}\n\n" + DS.render_dependency_section([]))
    path.write_text(text, encoding="utf-8")
    return text


def _issue(st: Store, *, proof: str = PROOF) -> dict:
    """三票同源 + `vsigns.issue` 写签（D268 批 2 的正控形状）。"""
    sha = VS._sign_sha(proof)
    call = "call-1"
    rows = []
    for n in (1, 2, 3):
        rows.append(VR.record_verification(
            st.root, statement_id=SID, proof_text=proof,
            verdict={"verdict": "成立", "findings": []},
            secretary_judge={"axis": "clean", "checked": True,
                             "reason": "夹具：秘书判 clean"},
            flip=False, review_call=call, review_pass=n, manuscript=REL))
    passes = [{"verification_id": str(r["verification_id"]), "at": str(r.get("at") or ""),
               "proof_sha256": sha, "review_call": call, "review_pass": n}
              for n, r in zip((1, 2, 3), rows)]
    got = VS.issue(st.root, artifact_sha=sha, streak=3, need=3,
                   ledger=f"verifications/{SID}.jsonl#{rows[-1]['verification_id']}",
                   statement_id=SID, proof_no=1, passes=passes, at=TS,
                   by="secretary:B")
    assert got.get("written") is True or got.get("idempotent") is True, got
    return got


def _signed_text(text: str, *, sha: str = SHA) -> str:
    return VS.stamp_manuscript_sign(
        text, proof_sha=sha, streak=3, need=3, verdict="成立",
        signer="secretary:B", at=TS,
        ledger=f"verifications/{SID}.jsonl#v-000003",
        statement_id=SID, manuscript_id=SID)


def _row(st: Store, *, proof: str = PROOF, reviewed: bool = False,
         proofs: list | None = None, status: str = "active",
         quote_reason: str = "夹具：直接铺行") -> dict:
    bits = EB.bits_of(
        proof=True, proof_process=(proof or PROOF), reviewed=reviewed,
        reviewed_by=({"verification_id": "v-000001", "evidence":
                      f"verifications/{SID}.jsonl#v-000001"} if reviewed else None),
        kind="theorem")
    if reviewed:
        ev = dict(bits.get("evidence") or {})
        ev[EB.REVIEWED_BY_PROOF_KEY] = {str(1): True}
        bits["evidence"] = ev
        bits["grade"] = EB.derive_grade(bits, kind="theorem")
    extra: dict = {"bits": bits}
    if proofs is not None:
        extra["proofs"] = proofs
    return seed_statement_row(
        st, proof_text=proof, statement_full=FULL, statement_text="一致连续",
        kind="theorem", label="uniform-continuity", origin="own_result",
        evidence_kind="heuristic", status=status, quote_reason=quote_reason,
        stmt_id=SID, **extra)


def _read(st: Store, text: str, *, store: Store | None = None) -> dict:
    return VS.sign_filing_reading(st.root, manuscript_path=REL, proof_text=text,
                                  statement_id=SID,
                                  store=st if store is None else store)


# ============================================================ 六档逐档

def test_1_filed(tmp_path: pathlib.Path) -> None:
    st = _ws(tmp_path)
    _row(st, reviewed=True)
    _issue(st)
    got = _read(st, _signed_text(_manuscript(st)))
    assert got["state"] == "filed", got
    assert got["filed"] is True, got
    assert int(got["statement"]["proof_no"]) == 1, got["statement"]


def test_2_pending_filing_when_the_ledger_has_no_proof_row(tmp_path: pathlib.Path) -> None:
    """新命题（B 收录前 `proof_text=""`）+ 稿上已签 ⇒ pending，不是 stale。"""
    st = _ws(tmp_path)
    _row(st, proof="", reviewed=False)
    _issue(st)
    got = _read(st, _signed_text(_manuscript(st)))
    assert got["manuscript_signed"] is True, got
    assert got["state"] == "signed_pending_filing", got
    assert int(got["statement"]["proof_rows"]) == 0, got["statement"]
    assert "没有任何证明行" in got["why"], got["why"]


def test_3_pending_filing_when_the_bit_is_not_flipped(tmp_path: pathlib.Path) -> None:
    """册里有这一份正文的证明行、第 3 位没翻 ⇒ 仍是 pending（等 B 收录）。"""
    st = _ws(tmp_path)
    _row(st, reviewed=False)
    _issue(st)
    got = _read(st, _signed_text(_manuscript(st)))
    assert got["state"] == "signed_pending_filing", got
    assert int(got["statement"]["proof_no"]) == 1, got["statement"]
    assert got["statement"]["reviewed"] is False, got["statement"]


def test_4_stale_names_the_current_version_in_the_ledger(tmp_path: pathlib.Path) -> None:
    """册里是旧版 ⇒ stale，且给出册里现行 proof_no / proof_sha256。"""
    st = _ws(tmp_path)
    _row(st, reviewed=True)
    new_proof = PROOF + "\n3. 补上边界情形。"
    _issue(st, proof=new_proof)
    got = _read(st, _signed_text(_manuscript(st, new_proof),
                                 sha=VS._sign_sha(new_proof)))
    assert got["state"] == "signed_stale_in_ledger", got
    stmt = dict(got["statement"])
    assert int(stmt["proof_no"]) == 0, stmt          # 没有一条盖住新版
    assert int(stmt["current_proof_no"]) == 1, stmt  # 册里现行 #p1
    assert stmt["current_proof_sha256"] == SHA, stmt
    assert int(stmt["proof_rows"]) == 1, stmt
    assert "#p1" in got["why"] and SHA[:12] in got["why"], got["why"]


def test_5_unsigned(tmp_path: pathlib.Path) -> None:
    st = _ws(tmp_path)
    _row(st, reviewed=False)
    got = _read(st, _manuscript(st))
    assert got["manuscript_signed"] is False, got
    assert got["state"] == "unsigned", got


def test_6_abandoned(tmp_path: pathlib.Path) -> None:
    st = _ws(tmp_path)
    _row(st, reviewed=False, status="abandoned",
         quote_reason=SA.abandon_marker(at=TS, reason="夹具：明确放弃"))
    _issue(st)
    got = _read(st, _signed_text(_manuscript(st)))
    assert got["state"] == "abandoned", got
    assert got["abandoned"] is True, got
    assert got["filed"] is False, got


def test_7_unreadable_without_store(tmp_path: pathlib.Path) -> None:
    st = _ws(tmp_path)
    _row(st, reviewed=True)
    _issue(st)
    got = VS.sign_filing_reading(st.root, manuscript_path=REL,
                                 proof_text=_signed_text(_manuscript(st)),
                                 statement_id=SID, store=None)
    assert got["filed"] is None, got
    assert got["state"] == "unreadable", got


# ============================================================ 反真空

def test_8_anti_vacuum_new_proposition_must_not_be_stale(tmp_path: pathlib.Path) -> None:
    """反真空 ①：把「`matched_no==0` ⇒ stale」改回去，这一条立刻红。

    同一份签、只改册里有没有带正文的证明行：没有 ⇒ pending；有旧版 ⇒ stale。
    两个读数必须不同 —— 这就是"分开两档"的判据本身。
    """
    st = _ws(tmp_path)
    _row(st, proof="", reviewed=False)
    _issue(st)
    text = _signed_text(_manuscript(st))
    no_rows = _read(st, text)
    assert no_rows["state"] == "signed_pending_filing", no_rows
    # 同一份稿/签，给册里补一条旧版正文 ⇒ 立刻落到 stale（证明分档真的在看册）。
    st2 = _ws(tmp_path / "old-version")
    _row(st2, proof=PROOF + "\n3. 更旧的一版。", reviewed=True)
    _issue(st2)
    stale = _read(st2, text)
    assert stale["state"] == "signed_stale_in_ledger", stale
    assert no_rows["state"] != stale["state"], (no_rows, stale)


def test_9_anti_vacuum_current_version_is_the_latest_with_text(tmp_path: pathlib.Path) -> None:
    """反真空 ②：册里有 #p1/#p2 两份，签的是新版 ⇒ `current_proof_*` 指 #p2。

    若把"现行"读成"随便一条 / 第一条"，这一条红 —— 那两格不是摆设。
    """
    st = _ws(tmp_path)
    old1, old2 = PROOF, PROOF + "\n3. 旧的第二版。"
    _row(st, proof=old1, reviewed=True,
         proofs=[{"proof_no": 2, "proof_text": old2}])
    new_proof = PROOF + "\n4. 全新的一版。"
    _issue(st, proof=new_proof)
    got = _read(st, _signed_text(_manuscript(st, new_proof),
                                 sha=VS._sign_sha(new_proof)))
    assert got["state"] == "signed_stale_in_ledger", got
    stmt = dict(got["statement"])
    assert int(stmt["proof_rows"]) == 2, stmt
    assert int(stmt["current_proof_no"]) == 2, stmt
    assert stmt["current_proof_sha256"] == VS._sign_sha(old2), stmt
    assert "p2" in got["why"], got["why"]
