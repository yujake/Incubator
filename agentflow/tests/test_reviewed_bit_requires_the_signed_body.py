# -*- coding: utf-8 -*-
"""第 3 位逐份表只许在"这一份正文存在、且就是签覆盖的那一份"时翻真（2026-11-03 件二）。

## 现场（86）

`projects/paper-rewrite-86` 的 `stmt:000013`：

```text
kind=conjecture origin=own_result 有正文=False
bits.evidence.reviewed_by_proof={"1": true}
bits.evidence.reviewed_sha_by_proof={"1": "ed35a73f…"}
```

B 先按"不带正文"拿号（`quote_reason` 里写着「本步先按写入期闸给的出路②拿 stmt 号
（不带 proof_text）」），V 的秘书随后拿 `ed35a73f…` 那一份正文的审校行调
`verifications.sign_statement`。改前 `sign_statement` 只对 `proof_no > 1` 检查
"证明清单里有没有 #pN"，对 `#p1` 不检查命题行有没有正文 —— 于是
`_reviewed_statement_row`（`verifications.py:2362` 一带）无条件把
`reviewed_by_proof["1"]` 写成 `true`：没有正文（也就没有正文 sha）却读成"第 1 份已签"。

## 修法

翻位前加一道正文闸（`sign_statement`，`verifications.py:2854` 一带）：

- 这一份正文读不到（`proof_text` / `proofs` 清单都没有）⇒ `body_gate=missing_body`，不翻位；
- 正文 sha 与这一签的 `proof_sha256` 不符 ⇒ `body_gate=sha_mismatch`，不翻位；
- 两条都过 ⇒ `body_gate=matched`，照原样翻位。

台账那一行照旧落（它是签的正本）；只是命题行上的位不翻，理由串点名缺哪一条。

## 判据（先红后绿）

| # | 造什么 | 期望 |
|---|---|---|
| a | 命题行无正文 + 有一份签（`proof_sha256=ed35…`）指向它 | `written=False`、`body_gate=missing_body`；`reviewed_by_proof` 不含该份 / 该份为假 |
| b | 命题行有正文且 sha 与签相符 | `written=True`、`body_gate=matched`；`reviewed_by_proof[1] is True` |
| b2 | 有正文但 sha 与签不符 | 不翻位（`sha_mismatch`）——证明闸不是只看"有没有正文" |
| c | 86 定格重放（`tests/fixtures/paper_rewrite_86_reviewed_bit.json`） | `000013` 重放后未签；`000000` 重放后已签 |

c 的"定格"：夹具从 `projects/paper-rewrite-86` 只读抓取（2026-11-03），保留两条命题行
与各自用来重放的那一行台账（`000000` 的 `v-000003`：正文 sha 与现行正文一致；
`000013` 的 `v-000003`：签的是 `ed35…`，而命题行没有正文）。重放从"签之前"的位开始
（清掉逐份表），只把冻结的正文与台账行喂回 `sign_statement` —— 改前 000013 会被翻真
（红），改后不翻；000000 两条都过（绿，反真空）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import evidencebits as EB
from agentflow import verifications as VR
from agentflow.store import Store

PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
SHA = VR.proof_sha(PROOF)
SID = "000013"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
TS = "2026-11-03T05:07:53+08:00"
FIXTURE = (pathlib.Path(__file__).resolve().parent / "fixtures"
           / "paper_rewrite_86_reviewed_bit.json")


def _statement(proof_text: str) -> dict:
    return {
        "stmt_id": SID, "origin": "own_result", "kind": "conjecture",
        "label": "紧支撑有限符号测度上的卷积零条件引理",
        "statement_full": FULL, "statement_text": FULL,
        "proof_text": proof_text, "evidence_kind": "cross_check",
        "status": "active", "quote_verified": None,
        "quote_reason": "夹具：自产结果，没有外部引文", "created_at": TS,
        "created_by": "test",
        "bits": EB.bits_of(proof=bool(proof_text), proof_process=proof_text,
                           kind="conjecture"),
    }


def _vrow(*, sha: str = SHA, verdict: str = "成立", unresolved: int = 0) -> dict:
    return {
        "verification_id": "v-000003", "stmt_id": SID, "statement_id": SID,
        "verdict": verdict, "defect_step": None, "findings": [],
        "unresolved_errors": unresolved, "proof_sha256": sha,
        "proof_chars": len(PROOF), "proof_no": 1, "at": TS,
        "verifier": "agent-V", "review_call": "call-1", "review_pass": 3,
        "secretary_judge": {"checked": True, "axis": "clean", "decision": "没问题"},
    }


def _issuance() -> dict:
    return {"checked": True, "issue": True, "issued": True, "need": 3,
            "within_call": 3, "streak": 3, "streak_ok": True,
            "review_call": "call-1", "decision": "签发"}


def _ws(tmp_path: pathlib.Path, row: dict) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return st


def _write_ledger(st: Store, row: dict, sid: str = SID) -> pathlib.Path:
    """落一整趟送审的三转（`review_pass` 1..3、同一 `review_call`）。

    2026-11-05：签的必填闸要求 `passes` 逐转带读数且最后一转正是 `ledger` 指的那一行
    —— 只写第 3 转会让 `_vsign_payload` 只捞到一条票（那是"三格全空的占位"的同族，
    只是缺的那两格更长）。夹具因此按真台账的形状落三行；`row` 仍是第 3 转那一行。
    """
    path = VR.verification_ledger_path(st.root, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    last_id = str(row.get("verification_id") or "v-000003")
    call = "call-1"   # `_issuance()` 点名的是这一趟送审
    for n in (1, 2, 3):
        one = dict(row)
        one["verification_id"] = last_id if n == 3 else f"v-{n:06d}"
        one["review_pass"] = n
        one["review_call"] = call
        lines.append(json.dumps(one, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _latest(st: Store, sid: str = SID) -> dict:
    return dict(next(r for r in st.rows("statements")
                     if str(r.get("stmt_id") or "") == sid))


def _sign(st: Store, row: dict, *, proof_text: str, by: str = "secretary:B") -> dict:
    return VR.sign_statement(
        st, row=row, proof_text=proof_text, proof_no=1, append_ledger=False,
        sign_issuance=_issuance(), by=by)


# ====================================================================== a 无正文
def test_a_a_statements_row_without_a_body_is_not_flipped(tmp_path: pathlib.Path) -> None:
    """命题行无正文 + 有一份签指向它 ⇒ 只落台账，`reviewed_by_proof` 不含这一份。

    改前红：`sign_statement` 不看 `#p1` 有没有正文，直接把
    `reviewed_by_proof["1"]` 写成 true。
    """
    st = _ws(tmp_path, _statement(""))
    row = _vrow()
    _write_ledger(st, row)

    got = _sign(st, row, proof_text=PROOF)

    assert got["written"] is False, got
    assert got["body_gate"] == "missing_body", got
    assert "没有正文" in str(got.get("reason") or ""), got["reason"]
    latest = _latest(st)
    per = EB.reviewed_by_proof(latest)
    assert per.get(1) is not True, per
    assert EB.bits_from_row(latest)["reviewed"] is False, latest.get("bits")
    # 台账那三行是签的正本（一整趟送审的三转）：它们不许被这道闸带走。
    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not bad and len(rows) == 3, (rows, bad)


# ====================================================================== b 相符
def test_b_a_matching_body_is_flipped(tmp_path: pathlib.Path) -> None:
    """有正文且 sha 与签相符 ⇒ 必须翻 true（证明判据不是"永远不翻"）。"""
    st = _ws(tmp_path, _statement(PROOF))
    row = _vrow()
    _write_ledger(st, row)

    got = _sign(st, row, proof_text=PROOF)

    assert got["written"] is True, got
    assert got["body_gate"] == "matched", got
    latest = _latest(st)
    assert EB.reviewed_by_proof(latest).get(1) is True, latest.get("bits")
    assert EB.bits_from_row(latest)["reviewed"] is True, latest.get("bits")


# ====================================================================== b2 不符
def test_b2_a_different_body_is_not_flipped(tmp_path: pathlib.Path) -> None:
    """有正文但 sha 与签不符 ⇒ 不翻位（闸不是只看"有没有正文"）。"""
    other = PROOF + "\n3. 这一行是改稿之后加的。"
    st = _ws(tmp_path, _statement(other))
    row = _vrow()          # 签覆盖的是 PROOF 的 sha，不是 other 的
    _write_ledger(st, row)

    got = _sign(st, row, proof_text=PROOF)

    assert got["written"] is False, got
    assert got["body_gate"] == "sha_mismatch", got
    assert "不符" in str(got.get("reason") or ""), got["reason"]
    latest = _latest(st)
    assert EB.reviewed_by_proof(latest).get(1) is not True, latest.get("bits")
    assert EB.bits_from_row(latest)["reviewed"] is False, latest.get("bits")


# ====================================================================== c 86 定格
def _clean_bits(row: dict) -> dict:
    """签之前的那一位：清掉逐份表与凭据（保留正文与位本身）。"""
    bits = dict(row.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    for key in (EB.REVIEWED_BY_PROOF_KEY, EB.REVIEWED_SHA_BY_PROOF_KEY):
        ev.pop(key, None)
    ev["reviewed_by"] = {}
    bits["reviewed"] = False
    bits["evidence"] = ev
    return EB.normalize_raw(bits, origin=str(row.get("origin") or "own_result"),
                            kind=str(row.get("kind") or ""))


def _load_fixture() -> dict:
    assert FIXTURE.is_file(), f"86 定格夹具不在盘上：{FIXTURE}"
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_c_the_frozen_86_replay_reads_000013_unsigned_and_000000_signed(
        tmp_path: pathlib.Path) -> None:
    """86 定格重放：000013 重放后未签；000000 重放后已签。

    重放从"签之前"的位开始：把冻结的命题行清掉逐份表，再把冻结的那一行台账喂回
    `sign_statement`。改前 000013 会被翻真（红）；改后 000000 仍翻真（反真空）。
    """
    frozen = _load_fixture()
    rows = {str(r["stmt_id"]): r for r in frozen["statements"]}

    # ---- 000013：命题行没有正文（`proof_text` 空），签覆盖 ed35… ----
    row13 = dict(rows["000013"])
    assert not str(row13.get("proof_text") or "").strip(), "定格夹具里的 000013 必须有号无正文"
    row13["bits"] = _clean_bits(row13)
    st13 = _ws(tmp_path / "p13", row13)
    vrow13 = dict(frozen["verifications"]["000013"][0])
    _write_ledger(st13, vrow13, sid="000013")
    got13 = VR.sign_statement(
        st13, row=vrow13, proof_text="", proof_no=1, append_ledger=False,
        sign_issuance=_issuance(), by="secretary:B")
    assert got13["written"] is False, got13
    assert got13["body_gate"] == "missing_body", got13
    latest13 = _latest(st13, "000013")
    assert EB.reviewed_by_proof(latest13).get(1) is not True, latest13.get("bits")
    assert EB.bits_from_row(latest13)["reviewed"] is False, latest13.get("bits")

    # ---- 000000：正文存在且 sha 与冻结的那一签相符 ----
    row00 = dict(rows["000000"])
    body00 = str(row00.get("proof_text") or "")
    assert body00.strip(), "定格夹具里的 000000 必须有正文"
    row00["bits"] = _clean_bits(row00)
    st00 = _ws(tmp_path / "p00", row00)
    vrow00 = dict(frozen["verifications"]["000000"][0])
    assert vrow00["proof_sha256"] == VR.proof_sha(body00), (
        "定格夹具对不上：000000 的那一签盖的不是现行正文")
    _write_ledger(st00, vrow00, sid="000000")
    got00 = VR.sign_statement(
        st00, row=vrow00, proof_text=body00, proof_no=1, append_ledger=False,
        sign_issuance=_issuance(), by="secretary:B")
    assert got00["written"] is True, got00
    assert got00["body_gate"] == "matched", got00
    latest00 = _latest(st00, "000000")
    assert EB.reviewed_by_proof(latest00).get(1) is True, latest00.get("bits")
    assert EB.bits_from_row(latest00)["reviewed"] is True, latest00.get("bits")
