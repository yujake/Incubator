# -*- coding: utf-8 -*-
"""档位回填：V 的签落位之后，那一行的 `evidence_kind` 按现行签重算（业主 2026-11-04）。

## 业主原话（唯一权威，逐字）

    「有证明 + V 签就该是审过的档；只有数值实验才是 strong_conjecture」

## 断在哪（真机读数，只读）

`evidence_kind` 原先只有一条升档路：同一份内容再登记一次时由
`Secretary._upgrade_evidence_kind` 改。于是"V 签了、之后再没有人登记"的行永远停在旧档：

| 工作区 | 命题 | kind | bits.reviewed | bits.grade | evidence_kind |
|---|---|---|---|---|---|
| `projects/paper-rewrite-84` | 000000 | theorem | true | pre_theorem | heuristic（旧档） |
| `projects/paper-rewrite-85` | 000004 | theorem | true | pre_theorem | heuristic（旧档） |
| `projects/paper-rewrite-85` | 000005 | theorem | true | pre_theorem | heuristic（旧档） |

后果不在报告里，在 F 那一侧：F 的"可引用在册命题"清单只收 `proof_review` 及以上
（`agent_f/manuscript.py::citable_statements`），这些行一条都进不去 ⇒ F 每一轮都被告知
"没有可引的 id" ⇒ 证明里零 `cites` ⇒ 手稿的 `## 依赖` 恒空表 ⇒ `dependencies` 0 行。
这就是"依赖面几乎没用过"的上游（87 的六份稿 52 步全「前提」）。

## 判据与各自的"改前红"

| 判据 | 它钉住的事 | 改前红在哪 |
|---|---|---|
| a | 登记时 `heuristic` + V 三转「成立」⇒ 回填到 `proof_review`，依据指向签发的那一签 | 改前签完仍是 `heuristic`（要再登记一次才动） |
| b | 反真空：把回填那一格打桩成"什么都不做"⇒ a 必红 | 判据若没接在那根线上，打桩不会让它变 |
| c | 幂等：同一份签再签一次 ⇒ 不产生第二次回填（不写第二个时间戳） | 改前没有回填，这条判据无从绿；粗做的回填会每次重写 |
| d | negative：没签 / 判「有毛病」/ 已经是 `proof` 的行，一个字节都不许被这一格升（或降） | 粗做的回填会把"没签"也抬上去、把 `proof` 降成 `proof_review` |

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

def _seed(store: Store, *, evidence_kind: str = "heuristic", kind: str = "conjecture") -> str:
    """一条在册命题（真机那一行的同形：有证明正文、V 还没签）。

    为什么直接铺行而不是走 `register_statement`：2026-11-02 的准入闸 strict 之后，
    "无签的证明正文"经登记写不进去 —— 而这几条要的正是"登记那一刻还没有签"这个状态。
    """
    seeded = seed_statement_row(
        store, proof_text=PROOF, statement_full=FULL, statement_text="立方和闭式",
        kind=kind, label="sum-of-cubes-closed-form", origin="own_result",
        evidence_kind=evidence_kind, doc_id=S.format_id(0),
        quote_reason="本判据夹具：自产命题，没有外部引文要比对",
        derived_from=[], aliases=[],
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=PROOF, kind=kind))
    return str(seeded["stmt_id"])


def _row(store: Store, sid: str) -> dict:
    return next(dict(r) for r in store.rows("statements")
                if str(r.get("stmt_id") or "") == str(sid))


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

def test_a_after_the_third_clean_sign_the_grade_is_backfilled(store: Store) -> None:
    """a：登记时 `heuristic` + V 三转「成立」⇒ `evidence_kind=proof_review`（依据点在那一签上）。"""
    sid = _seed(store)
    assert _row(store, sid)["evidence_kind"] == "heuristic", _row(store, sid)

    signed = _sign_three(store, sid)
    assert signed.get("checked") is True and signed.get("verdict") == "成立", signed

    row = _row(store, sid)
    assert row["evidence_kind"] == "proof_review", row
    # 名字与档位是同一笔里一起到位的（D-69 + 本批）。
    assert row["kind"] == "theorem", row
    trace = dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert trace.get("from") == "heuristic" and trace.get("to") == "proof_review", trace
    assert trace.get("checked") is True, trace
    sign_row = f"verifications/{sid}.jsonl#{signed['verification_id']}"
    assert sign_row in str(trace.get("basis") or ""), (sign_row, trace)
    assert int(trace.get("proof_no") or 0) == 1, trace
    # 读数面：签名那一笔自己把它带回来（不是"事后才补"的一句话）。
    writeback = dict(signed.get("statement_writeback") or {})
    assert (writeback.get("grade_recomputed") or {}).get("to") == "proof_review", writeback
    assert sign_row in str((writeback.get("grade_recomputed") or {}).get("basis") or ""), writeback


# ------------------------------------------------------------------ b（反真空）

def test_b_unplugging_the_backfill_turns_a_red(store: Store, monkeypatch) -> None:
    """b：把回填那一格打桩成"什么都不做" ⇒ a 必须回到 `heuristic`。"""
    def _noop(row, *, root, proof_no=None):
        return {"row": dict(row), "reading": {}}

    monkeypatch.setattr(VR, "_grade_recomputed_from_signature", _noop)

    sid = _seed(store)
    signed = _sign_three(store, sid)
    assert signed.get("checked") is True, signed
    row = _row(store, sid)
    assert row["evidence_kind"] == "heuristic", (
        "回填被摘掉之后档位仍然上去了 ⇒ 上面那条 a 的绿不是这条接线给的", row)
    assert VR.GRADE_RECOMPUTED_KEY not in row, row
    # 名字那一半不受影响（两格各有各的接线，摘掉一条不许把另一条也读成"没接"）。
    assert row["kind"] == "theorem", row


# ------------------------------------------------------------------ c（幂等）

def test_c_signing_again_does_not_backfill_a_second_time(store: Store) -> None:
    """c：同一份签再签一次 ⇒ 不产生第二次回填（那一格的时间戳与依据一起没变）。"""
    sid = _seed(store)
    _sign_three(store, sid)
    first = dict(_row(store, sid).get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert first.get("to") == "proof_review", first

    again = _sign(store, sid)
    writeback = dict(again.get("statement_writeback") or {})
    assert writeback.get("grade_recomputed") == {}, writeback
    assert dict(_row(store, sid).get(VR.GRADE_RECOMPUTED_KEY) or {}) == first, _row(store, sid)


# ------------------------------------------------------------------ d（negative）

def test_d_an_unsigned_or_faulted_row_is_never_backfilled(store: Store) -> None:
    """d：没签 / 判「有毛病」的行一个字节都不许被这一格升上去。"""
    # ① 只签了 1 次（连续次数不够 ⇒ 位没翻）⇒ 不回填。
    pending = _seed(store, evidence_kind="cross_check")
    one = _sign(store, pending)
    assert (one.get("statement_writeback") or {}).get("written") is False, one
    assert _row(store, pending)["evidence_kind"] == "cross_check", _row(store, pending)
    assert VR.GRADE_RECOMPUTED_KEY not in _row(store, pending), _row(store, pending)

    # ② 三转都判「有毛病」⇒ 一次「成立」都没有 ⇒ 不回填。
    faulted = _seed(store, evidence_kind="heuristic")
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        fault = _sign(store, faulted, verdict=_FAULT)
        assert (fault.get("statement_writeback") or {}).get("written") is False, fault
    row = _row(store, faulted)
    assert row["evidence_kind"] == "heuristic", row
    assert VR.GRADE_RECOMPUTED_KEY not in row, row


def test_d2_a_machine_checked_row_is_never_downgraded(store: Store) -> None:
    """d 的第二格：已经是 `proof`（机器核过那档）⇒ 回填不许把它改成 `proof_review`。"""
    sid = _seed(store, evidence_kind="proof")
    _sign_three(store, sid)
    row = _row(store, sid)
    assert row["evidence_kind"] == "proof", row
    assert VR.GRADE_RECOMPUTED_KEY not in row, row
