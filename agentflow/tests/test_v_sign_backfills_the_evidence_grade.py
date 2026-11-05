# -*- coding: utf-8 -*-
"""等级现算：V 的签落位之后，那一行的等级按五元位现算（2026-11-05 改口径）。

## 业主原话（唯一权威，逐字）

2026-11-04：「有证明 + V 签就该是审过的档；只有数值实验才是 strong_conjecture」；
2026-11-05：「cross_check 等价于强猜想等价于有普通数值实验支撑的猜想……不妨就用等级制
平替掉」＋「穷举证书相当于 lean 形式化，表示绝对正确」。

## 改了什么（这一份的第二次生命）

改前这一份钉的是"V 落签 ⇒ 把 `statements.evidence_kind` 回填成 `proof_review`"。
2026-11-05 之后等级是唯一的轴：`bits.reviewed` 一翻真，`derive_grade` 现算就是
`pre_theorem` —— 等级不需要任何回填，回填那一格只剩"凭什么"的读数
（`verifications._grade_recomputed_from_signature` 只算等级、不写档位）。

## 判据与各自的"改前红"

| 判据 | 它钉住的事 | 红在哪 |
|---|---|---|
| a | 三转「成立」⇒ 现算等级 `pre_theorem`；回执 `to`/`to_kind`/`basis` 指向那一签；`evidence_kind` 一个字节没动 | 位没翻 / 等级没现算 / 有人偷偷写了档位 |
| b | 反真空：把"翻第 3 位"那一格打桩掉 ⇒ 等级停在 `conjecture`（等级是位给的，不是回执给的） | 若等级来自别处，打桩不会让它掉 |
| c | 幂等：同一份签再签一次 ⇒ 不产生第二次回执（时间戳与依据一起没变） | 粗做的回执会每次重写 |
| d | negative：没签 / 判「有毛病」的行一个字节都不许被这一格升 | 粗做的回执会把"没签"也报成"升了" |
| d2 | 机器可核的行（穷举证书）⇒ `theorem`，不许被"V 签"压回 `pre_theorem` | 回填若按通道写档会把它降档 |

全部 tmp 工作区、零模型调用；不读写 `projects/`（真机工作区只读）。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.store import Store  # noqa: E402

from conftest import seed_statement_row  # noqa: E402

FULL = "对任意整数 n≥0：1^3 + 2^3 + … + n^3 = (n(n+1)/2)^2。"
PROOF = ("对 n 作归纳。基例 n = 0 两边都是 0；归纳步把 (n+1)^3 加进去，"
         "整理得 ((n+1)(n+2)/2)^2。")

_OK = {"verdict": "成立", "findings": []}
_FAULT = {"verdict": "有毛病", "defect_step": 2,
          "findings": [{"level": "error", "step": 2, "detail": "第 2 步的代数整理不成立"}]}


# ------------------------------------------------------------------ 夹具

def _seed(store: Store, *, evidence_kind: str = "heuristic", kind: str = "conjecture",
          bits: dict | None = None) -> str:
    """一条在册命题（真机那一行的同形：有证明正文、V 还没签）。

    为什么直接铺行而不是走 `register_statement`：2026-11-02 的准入闸 strict 之后，
    "无签的证明正文"经登记写不进去 —— 而这几条要的正是"登记那一刻还没有签"这个状态。
    行号一律以盘上 `stmt_id` 为准（D2 那条 lane 会把稿头号当候选号，不假设它由计数器给）。
    """
    seeded = seed_statement_row(
        store, proof_text=PROOF, statement_full=FULL, statement_text="立方和闭式",
        kind=kind, label="sum-of-cubes-closed-form", origin="own_result",
        evidence_kind=evidence_kind, doc_id=S.format_id(0),
        quote_reason="本判据夹具：自产命题，没有外部引文要比对",
        derived_from=[], aliases=[],
        bits=dict(bits or EB.bits_of(origin="own_result", proof=True,
                                     proof_process=PROOF, kind=kind)))
    return str(seeded["stmt_id"])


def _row(store: Store, sid: str) -> dict:
    return next(dict(r) for r in store.rows("statements")
                if str(r.get("stmt_id") or "") == str(sid))


def _grade(row: dict) -> str:
    """这一行现在按五元位现算的等级（唯一入口 `derive_grade`）。"""
    return EB.derive_grade(EB.bits_from_row(dict(row)), kind=str(row.get("kind") or ""))


def _sign(store: Store, sid: str, *, verdict: dict | None = None,
          text: str = PROOF) -> dict:
    return VR.record_verification(
        str(store.root), statement_id=sid, proof_text=text,
        verdict=dict(verdict or _OK), verifier="agent-V", store=store, proof_no=1)


def _sign_three(store: Store, sid: str, *, verdict: dict | None = None) -> dict:
    """连签 `SIGN_STREAK_NEED` 次（2026-10-29 口径：第 1、2 次只落台账）。"""
    need = int(VR.SIGN_STREAK_NEED)
    last: dict = {}
    for i in range(1, need + 1):
        last = _sign(store, sid, verdict=verdict)
        wrote = bool((last.get("statement_writeback") or {}).get("written"))
        assert wrote is (i == need), (
            f"第 {i} 次「成立」的翻位读数是 written={wrote!r} —— 连续 {need} 次才发签；"
            f"理由：{(last.get('statement_writeback') or {}).get('reason') or '（没有理由）'}")
    return last


# ------------------------------------------------------------------ a

def test_a_after_the_third_clean_sign_the_grade_is_pre_theorem(store: Store) -> None:
    """a：登记时 `heuristic` + V 三转「成立」⇒ 现算等级 `pre_theorem`（回执点在那一签上）。"""
    sid = _seed(store)
    assert _row(store, sid)["evidence_kind"] == "heuristic", _row(store, sid)
    assert _grade(_row(store, sid)) == "conjecture", _row(store, sid)

    signed = _sign_three(store, sid)
    assert signed.get("checked") is True and signed.get("verdict") == "成立", signed

    row = _row(store, sid)
    assert _grade(row) == "pre_theorem", row
    # 名字与等级是同一笔里一起到位的（D-69 抬 kind，等级由位现算）。
    assert row["kind"] == "theorem", row
    trace = dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert trace.get("to") == "pre_theorem", trace
    assert trace.get("to_kind") == "proof_review", trace
    assert trace.get("checked") is True, trace
    sign_row = f"verifications/{sid}.jsonl#{signed['verification_id']}"
    assert sign_row in str(trace.get("basis") or ""), (sign_row, trace)
    assert int(trace.get("proof_no") or 0) == 1, trace
    # 「只算等级，不写档位」：历史列一个字节没动（它只是历史，判定面读等级）。
    assert row["evidence_kind"] == "heuristic", row
    # 读数面：签名那一笔自己把它带回来（不是"事后才补"的一句话）。
    writeback = dict(signed.get("statement_writeback") or {})
    assert (writeback.get("grade_recomputed") or {}).get("to") == "pre_theorem", writeback
    assert sign_row in str((writeback.get("grade_recomputed") or {}).get("basis") or ""), writeback


# ------------------------------------------------------------------ b（反真空）

def test_b_without_the_bit_flip_the_grade_stays_conjecture(store: Store,
                                                           monkeypatch) -> None:
    """b：把"翻第 3 位"那一格打桩成"什么都不做" ⇒ 等级必须停在 `conjecture`。

    这条钉的是"等级是五元位给的"：签照旧落台账、回执照旧产出，但位不翻 ⇒
    `derive_grade` 看不到 V 签。改前若等级来自回填函数（而不是位），打桩不会让它掉。
    """
    real = VR._reviewed_statement_row

    def _no_flip(found, row, *, proof_text="", proof_no=1, streak=None):
        return dict(found)          # 位不翻（reviewed_by_proof 不写、reviewed 不翻）

    monkeypatch.setattr(VR, "_reviewed_statement_row", _no_flip)
    try:
        sid = _seed(store)
        signed = _sign_three(store, sid)
        assert signed.get("checked") is True, signed
        row = _row(store, sid)
        assert _grade(row) == "conjecture", (
            "位没翻，等级却上去了 ⇒ 等级不是从五元位现算的", row)
        assert VR.GRADE_RECOMPUTED_KEY not in row, row
    finally:
        monkeypatch.setattr(VR, "_reviewed_statement_row", real)


# ------------------------------------------------------------------ c（幂等）

def test_c_signing_again_does_not_write_a_second_trace(store: Store) -> None:
    """c：同一份签再签一次 ⇒ 不产生第二次回执（那一格的时间戳与依据一起没变）。"""
    sid = _seed(store)
    _sign_three(store, sid)
    first = dict(_row(store, sid).get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert first.get("to") == "pre_theorem", first

    again = _sign(store, sid)
    writeback = dict(again.get("statement_writeback") or {})
    assert writeback.get("grade_recomputed") == {}, writeback
    assert dict(_row(store, sid).get(VR.GRADE_RECOMPUTED_KEY) or {}) == first, _row(store, sid)


# ------------------------------------------------------------------ d（negative）

def test_d_an_unsigned_or_faulted_row_is_never_reported_as_upgraded(store: Store) -> None:
    """d：没签 / 判「有毛病」的行一个字节都不许被这一格报成"升了"。"""
    # ① 只签了 1 次（连续次数不够 ⇒ 位没翻）⇒ 没有回执，等级还是 conjecture。
    pending = _seed(store, evidence_kind="cross_check")
    one = _sign(store, pending)
    assert (one.get("statement_writeback") or {}).get("written") is False, one
    assert _grade(_row(store, pending)) == "conjecture", _row(store, pending)
    assert VR.GRADE_RECOMPUTED_KEY not in _row(store, pending), _row(store, pending)

    # ② 三转都判「有毛病」⇒ 一次「成立」都没有 ⇒ 同上。
    faulted = _seed(store, evidence_kind="heuristic")
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        fault = _sign(store, faulted, verdict=_FAULT)
        assert (fault.get("statement_writeback") or {}).get("written") is False, fault
    row = _row(store, faulted)
    assert _grade(row) == "conjecture", row
    assert VR.GRADE_RECOMPUTED_KEY not in row, row


def test_d2_a_machine_checked_row_is_not_downgraded(store: Store) -> None:
    """d 的第二格：穷举证书（numeric=verified）已经在位 ⇒ 等级 `theorem`，不许被压回
    `pre_theorem`（2026-11-05：穷举证书与 Lean 同级）。

    行号以盘上 `stmt_id` 为准（不假设新行号由计数器给）。
    """
    bits = EB.bits_of(origin="own_result", numeric="verified",
                      numeric_evidence={"experiment_id": "000009",
                                        "script": "code/scan.py", "sha": "aa11"},
                      proof=True, proof_process=PROOF, kind="conjecture")
    sid = _seed(store, evidence_kind="heuristic", bits=bits)
    _sign_three(store, sid)
    row = _row(store, sid)
    assert _grade(row) == "theorem", row
    trace = dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert trace.get("to") == "theorem", trace
    assert trace.get("to_kind") == "proof", trace
    # 只算等级、不写档位：历史列仍是登记时那一档（它不影响判定）。
    assert row["evidence_kind"] == "heuristic", row
