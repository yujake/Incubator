# -*- coding: utf-8 -*-
"""判据：收录那一笔必须把第 2 位（有证明）翻上去（真机 R-mk-infinite-92）。

## 现场（只读，2026-11-06）

`projects/R-mk-infinite-92` 的 `statements:000000`：`proof_text` 1325 字在行上、
`reports/f-proof-000000.md` 上有连续 3/3 成立的 V 签块、`verifications/000000.jsonl`
里三行「成立」，而那一行是

    bits.proof = false · bits.reviewed = true · bits.grade = "conjecture"
    reviewed_by_proof = {"1": true} · _grade_recomputed = null

板上 `b-register@000000@58cf…` 那条「必须收录」义务确实被 B 接了、走完了 —— 收口
读数（`obligations.registration_gap`）只要求"正文 + reviewed"，于是"见过签"就够了。

## 根因（两条路，只有一条写全）

| 路 | 入口 | 写了哪些 bits 子格 |
|---|---|---|
| A 新建 / 升档 | 秘书 `record_statement` → B `_attach_proofs` | 第 2 位 + 第 3 位（`reviewed_by_proof` / sha 表）+ `_grade_recomputed` |
| B 并进在册命题 | 秘书 `_merge_into_proposition`（canonical 从空补上 / 第 N 份证明） | 一个字节都没写（正文写进去了，这一笔交来的 `bits` 整份丢掉）；此后只有 V 落签那一笔会翻第 3 位 |

现场走的是 B 路（秘书判同一条 ⇒ `merged=True`），于是"正文在行上"与"这一行有证明"
分家；而能翻位的只有 `verifications._reviewed_statement_row`（只动第 3 位）⇒ 自相矛盾。

## 修法

B 路的那个分支（`register_statement` 的 `merged` 支）也调 `_attach_proofs`（与 A 路
同一个写者）；`_attach_proofs` 在"这一行已有正文而第 2 位还没翻"时调
`evidencebits.bits_after_proof_recorded`（唯一实现：第 2 位翻真 + 第 3 位带过这一笔
认到的签，整份走 `normalize_raw` / `derive_grade`），并同一笔写顶层收录回执
（`proof_no` / `proof_sha256`）与 `_grade_recomputed`。穷举那一档不受影响：
`_grade_recomputed_from_signature` 的 exhaustion 通道照样把等级判成 `theorem`。

## 判据（先红后绿）

| # | 造什么 | 期望 |
|---|---|---|
| a | 在册猜想行（正文空）+ 稿上 3/3 成立的签块 ⇒ B 收录 | `proof=true ∧ reviewed=true ∧ grade=pre_theorem`；`proof_no=1`、`proof_sha256` == 签块那一份；`_grade_recomputed` 的 `to=pre_theorem`、`basis=verifications/000000.jsonl#v-…`、`proof_no=1`；且这一笔真调到了 `_attach_proofs` 与 `_grade_recomputed_from_signature`（打桩计数） |
| b | 反真空：把"翻第 2 位"那一步摘掉（打桩 `bits_after_proof_recorded` 只带第 3 位） | a 必须红：回到现场形状（`proof=false ∧ reviewed=true`、等级 `conjecture`、`_grade_recomputed` 为空、没有收录回执） |
| c | a 的同一行上 `numeric` 仍是 `pending` | 等级只能是 `pre_theorem`（不许顺手到 `theorem`）—— 定理要第 1/4 位真 verified |
| d | 穷举现场（E 的 `reports/e-proof-*.md` + V 签 ⇒ 收录进在册行） | 等级 `theorem`（`bits.numeric=verified`、`_grade_recomputed.channel=exhaustion`）—— e8ca6ccc 的通道不许被压回 `pre_theorem` |
| e | 已经在场的自相矛盾行（正文在、`reviewed=true`、`proof=false`）再收录一次同一份正文 | 补翻第 2 位 + 写回收据/`_grade_recomputed`（现场那一行不必手改：下一笔收录就会追平） |

零真实模型调用：V 与本文件里的秘书缝都是打桩（`_Seam` / `_ReviewSeam` 复用
`tests/test_b_signed_proof_must_be_registered.py` 里那两份，判据是同一组）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import conductor as CND  # noqa: E402
from agentflow import depsection as _DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_b.register_statement import _RegisterStatement  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools.conductor_tools import conductor_for  # noqa: E402

from conftest import seed_statement_row  # noqa: E402
from test_b_signed_proof_must_be_registered import (  # noqa: E402
    CLEAN_REPLY, _ReviewSeam, _Seam, _axis,
)

TS = "2026-11-06T03:19:40+08:00"
SID = "000000"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
#: 在册那一行的 `statement_full` 与这一笔交来的不是逐字相同（现场 000000：
#: 在册的是"写出主定理的完整证明稿…"那一长串，B 交来的是"命题（主定理 T）…"）。
#: 逐字相同会先撞 `record_statement` 的 exact-duplicate 分支 ⇒ 走不到"并进在册命题"。
FULL_ROW = ("写出主定理的完整证明稿。设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
            "证明按定义走：取 δ=ε 即得。格式要求：本证明自足。")
PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")


class _IdentitySeam:
    """B 的秘书缝：只回一个"同一条命题"的判词（现场那一笔走的是秘书判 same）。

    它不看数学，只看候选表第一条 —— 本文件量的是"并进在册那一行之后五元位写了
    什么"，不是同一性判定的智能（那一格的判据在
    `tests/test_one_theorem_many_proofs_is_not_three_theorems.py`）。
    """

    wired = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict, object]:
        from test_b_signed_proof_must_be_registered import _Call

        self.calls.append(str(note or ""))
        if str(note or "").endswith("statement_keywords"):
            # 2026-11-08（主动查询）：秘书先挑词、再检索；这几个词命中在册那一行
            # （它的 label / 正文里都有「一致连续」）。
            return ({"keywords": ["一致连续"],
                     "why": "打桩：这个数学词能把在册那一条捞出来"}, _Call())
        if str(note or "").endswith("statement_same"):
            # 2026-11-10（T1 后）：按手稿路径收录时，B 先问秘书「这一条是不是在册的
            # 同一条」。这一问的产物是 `decision=same` + `same_as=<号>`（与
            # `Secretary.adjudicate_proposition` 读的两个键一致）；这里点回在册那一行，
            # 于是这一笔走"在册"分支、按该行的号读签。
            return ({"decision": "same", "same_as": SID, "checked": True,
                     "canonical_name": "", "route": "",
                     "why": "打桩：判同一条", "basis": ["打桩：判同一条"]}, _Call())
        if not str(note or "").endswith("proposition_identity"):
            return {}, _Call()
        text = str(prompt or "")
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
        except ValueError:
            data = {}
        candidates = [c for c in (data.get("candidates") or ()) if isinstance(c, dict)]
        return {"decision": "same",
                "same_as": str(candidates[0].get("stmt_id") or "") if candidates else "",
                "canonical_name": str(data.get("label") or ""), "route": "",
                "condition": "打桩：条件一致", "conclusion": "打桩：结论一致",
                "reason": "打桩：判同一条", "basis": ["打桩：判同一条"]}, _Call()


def _env(tmp_path: pathlib.Path) -> dict:
    """现场那一行：在册、`kind=conjecture`、正文空；稿与 V 的签都真造。"""
    st = Store(tmp_path / "ws")
    st.init()
    conductor_for(st)
    row = {"stmt_id": SID, "origin": "own_result", "kind": "conjecture",
           "label": "一致连续", "statement_full": FULL_ROW, "statement_text": FULL,
           "proof_text": "", "evidence_kind": "heuristic", "status": "active",
           "quote_verified": None, "quote_reason": "这一条还没有命题号 ⇒ 按最弱一档登记",
           "created_at": TS, "created_by": "secretary-B",
           "bits": EB.bits_of(kind="conjecture"), "proof_authors": ["F"]}
    with st.tx("statements", actor="secretary-B") as tx:
        tx.upsert("statements", row)
    rel = f"reports/f-proof-{SID}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# F 的证明手稿\n\n"
                    f"- 计划：{SID} · 子目标：S3\n\n"
                    f"## 命题\n\n{FULL}\n\n## 证明\n\n{PROOF}\n\n"
                    + _DS.render_dependency_section([]), encoding="utf-8")
    sec_v = SEC.Secretary("V", root=st.root, store=st,
                          seam=_Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]}),
                          enable_model=True)
    v = AgentV(st, workspace_root=st.root, llm=_ReviewSeam(CLEAN_REPLY), secretary=sec_v)
    b = AgentB(st, extractor=None, extract_text=None,
               secretary=SEC.Secretary("B", root=st.root, store=st,
                                       seam=_IdentitySeam(), enable_model=True))
    return {"store": st, "v": v, "b": b, "rel": rel}


def _sign(env: dict) -> dict:
    """V 的未在册形态那一签：正文先签进稿（连续 3/3 成立），B 再来收录。

    与现场同形：签落位时命题行还没有正文 ⇒ 第 3 位当时翻不了（`body_gate` 那一闸），
    签仍在稿与 `verifications/<号>.jsonl` 里（现场 v-000006 那一笔）。
    """
    with CND.calling_as("t-v1", "V", parent_task_id="t-f1", parent_role="F"):
        got = env["v"].verify_proof(SID, proof_text=PROOF, proof_manuscript=env["rel"])
    text = (pathlib.Path(env["store"].root) / env["rel"]).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(text, manuscript_path=env["rel"])
    assert block["signed"] is True and block["streak"] == block["need"] == 3, block
    return got


def _row(env: dict) -> dict:
    return next(dict(r) for r in env["store"].rows("statements") if r["stmt_id"] == SID)


def _register(env: dict) -> dict:
    """B 的收录那一笔（`evidence_kind` 不比在册强 ⇒ 秘书走"并进在册命题"那一支）。

    2026-11-10（T1 之后）：稿以路径寻址，不再把正文抄进参数。这不是换被测对象：
    这一条量的仍然是"并进在册那一行之后五元位写了什么"；改的只是稿的递法（D 只递
    指针、B 从稿里读，是 T1 的入口形状）。路径那一格还让 B 先问一句"这是不是在册的
    同一条命题"——`_IdentitySeam` 现在把那一问也答成 `same`，于是这一笔按在册行的号
    读签（签是 D268 批 2 的可复算凭据，见 `_sign`）。
    """
    return env["b"].register_statement(
        origin="own_result", kind="theorem", label="一致连续",
        statement_full=FULL, statement_text="一致连续", proof_text=PROOF,
        proof_manuscript=env["rel"], evidence_kind="cross_check",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")


def _trace(row: dict) -> dict:
    return dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {})


# ============================================================ a 收录 ⇒ 第 2 位翻真
def test_a_collecting_a_signed_proof_flips_bit2_bit3_and_the_grade(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：签块 + 三条成立台账 ⇒ 收录之后行上 `proof ∧ reviewed ⇒ pre_theorem`。"""
    env = _env(tmp_path)
    before = _row(env)
    assert not str(before.get("proof_text") or "").strip(), before
    assert (before.get("bits") or {}).get("proof") is False, before
    _sign(env)

    calls: list[str] = []
    real_attach = _RegisterStatement._attach_proofs
    real_grade = VR._grade_recomputed_from_signature

    def spy_attach(self, *a, **kw):
        calls.append("_attach_proofs")
        return real_attach(self, *a, **kw)

    def spy_grade(row, **kw):
        calls.append("_grade_recomputed_from_signature")
        return real_grade(row, **kw)

    monkeypatch.setattr(_RegisterStatement, "_attach_proofs", spy_attach)
    monkeypatch.setattr(VR, "_grade_recomputed_from_signature", spy_grade)
    filed = _register(env)
    monkeypatch.undo()

    assert filed.get("ok") is True, filed
    assert filed.get("merged") is True, filed
    # ② 诊断：这条收录路上"写全"那两个判据函数必须真的被调到（改前一个都没调）。
    assert calls == ["_attach_proofs", "_grade_recomputed_from_signature"], calls

    row = _row(env)
    bits = dict(row.get("bits") or {})
    assert len(str(row.get("proof_text") or "")) == len(PROOF), row
    assert bits.get("proof") is True, bits
    assert bits.get("reviewed") is True, bits
    assert bits.get("grade") == "pre_theorem", bits
    ev = dict(bits.get("evidence") or {})
    assert ev.get("reviewed_by_proof") == {"1": True}, ev
    assert ev.get("reviewed_sha_by_proof") == {"1": VR.text_sha(PROOF)}, ev
    assert len(str(ev.get("proof_process") or "")) == len(PROOF), ev
    # 顶层收录回执：号与指纹都由行上那一份正文现算，与签块钉的 sha 同一份。
    assert row.get("proof_no") == 1, row
    assert row.get("proof_sha256") == VR.text_sha(PROOF), row
    # `_grade_recomputed`：判据是盘上那一签，不是自报。
    trace = _trace(row)
    assert trace.get("checked") is True, trace
    assert trace.get("from") == "conjecture" and trace.get("to") == "pre_theorem", trace
    assert trace.get("proof_no") == 1, trace
    rows, problems = VR.list_verifications(env["store"].root, statement_id=SID, limit=None)
    assert not problems, problems
    assert trace.get("basis") == (f"verifications/{SID}.jsonl#"
                                 f"{rows[-1]['verification_id']}"), (trace, rows)
    # 收口读数：这一行现在是"正文 + 已经收录"（板的义务据此才关得上）。
    assert bool(filed.get("proof_collected")) is True, filed


# ============================================================ b 反真空（摘掉翻位）
def test_b_without_the_bit2_step_the_field_shape_comes_back(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：把"翻第 2 位"摘掉 ⇒ 回到现场那个自相矛盾形状（a 的判据必须红）。"""
    def _review_only(bits, *, delivered=None, proof_process="", kind=""):
        """只把这一笔认到的签（第 3 位）带过来，第 2 位保持原样。"""
        raw = dict(bits or {})
        fresh = dict(delivered or {})
        ev = dict(raw.get("evidence") or {})
        fresh_ev = dict(fresh.get("evidence") or {})
        for key in (EB.REVIEWED_BY_PROOF_KEY, EB.REVIEWED_SHA_BY_PROOF_KEY,
                    "reviewed_by", "reviewed_source"):
            if key in fresh_ev:
                ev[key] = fresh_ev[key]
        if bool(fresh.get("reviewed")):
            raw["reviewed"] = True
        raw["evidence"] = ev
        return EB.normalize_raw(raw, origin=str(raw.get("origin") or "own_result"),
                                kind=kind)

    env = _env(tmp_path)
    _sign(env)
    monkeypatch.setattr(EB, "bits_after_proof_recorded", _review_only)
    filed = _register(env)
    monkeypatch.undo()

    assert filed.get("ok") is True, filed
    row = _row(env)
    bits = dict(row.get("bits") or {})
    # 现场形状：正文在行上、第 3 位说"见过签"，而第 2 位是空的 ⇒ 等级停在猜想。
    assert len(str(row.get("proof_text") or "")) == len(PROOF), row
    assert bits.get("reviewed") is True, bits
    assert bits.get("proof") is False, bits
    assert bits.get("grade") == "conjecture", bits
    assert row.get(VR.GRADE_RECOMPUTED_KEY) is None, row
    # 2026-11-08（缺陷③）：回执与"第 2 位这次翻没翻"解耦 —— 正文在行上，回执照写
    # （号 / sha 是"这一行现在有哪一份正文"的事实）；承重的是上面 `bits.proof=false`
    # 那条判据。改前这一行断言的是"回执也没有"，而回执缺席本身并不是第 2 位的读数。
    assert int(row.get("proof_no") or 0) == 1, row
    assert str(row.get("proof_sha256") or "") == VR.text_sha(PROOF), row


# ============================================================ c 不许顺手到 theorem
def test_c_a_pending_numeric_bit_still_stops_at_pre_theorem(tmp_path: pathlib.Path) -> None:
    """c：`numeric` 仍是 `pending` ⇒ 只能是 `pre_theorem`（不许把文字证明当定理）。"""
    env = _env(tmp_path)
    _sign(env)
    assert _register(env).get("ok") is True
    row = _row(env)
    bits = dict(row.get("bits") or {})
    assert bits.get("numeric") == "pending", bits
    assert bits.get("formal") == "pending", bits
    assert EB.derive_grade(EB.bits_from_row(row),
                           kind=str(row.get("kind") or "")) == "pre_theorem", bits
    assert _trace(row).get("to") == "pre_theorem", _trace(row)


# ============================================================ d 穷举通道不被压回
def test_d_an_exhaustive_proof_collected_later_is_still_a_theorem(
        tmp_path: pathlib.Path) -> None:
    """d：穷举现场（E 的稿 + V 签）走同一条收录路 ⇒ 等级 `theorem`（e8ca6ccc 的通道）。"""
    import test_e_gets_its_v_sign_like_f as E

    env = E._env(tmp_path / "exhaustive")
    rel, text = E._manuscript(env)
    column = E._column(env)
    seeded = seed_statement_row(
        env["store"], proof_text="", statement_full=FULL_ROW,
        statement_text="R(3,4)=9", kind="conjecture", label="R(3,4)=9",
        origin="own_result", evidence_kind="cross_check", bits={})
    sid = str(seeded["stmt_id"])
    with E._submitted_by_e():
        signed = env["v"].verify_proof(proof_manuscript=rel)
    assert signed.get("checked") is True, signed
    b = AgentB(env["store"], extractor=None, extract_text=None,
               secretary=SEC.Secretary("B", root=env["store"].root,
                                       store=env["store"],
                                       seam=_IdentitySeam(), enable_model=True))
    filed = b.register_statement(
        origin="own_result", kind="theorem", label="R(3,4)=9",
        statement_full=E.FULL, statement_text="R(3,4)=9", proof_text=column,
        proof_manuscript=text, evidence_kind="cross_check",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="我方推导")
    assert filed.get("ok") is True, filed
    assert filed.get("merged") is True, filed
    row = next(dict(r) for r in env["store"].rows("statements")
               if str(r.get("stmt_id") or "") == sid)
    bits = dict(row.get("bits") or {})
    assert bits.get("proof") is True and bits.get("reviewed") is True, bits
    assert bits.get("numeric") == "verified", bits
    assert bits.get("grade") == "theorem", bits
    trace = _trace(row)
    assert trace.get("to") == "theorem", trace
    assert trace.get("channel") == "exhaustion", trace
    assert row.get("proof_no") == 1, row
    assert row.get("proof_sha256") == VR.text_sha(column), row


# ============================================================ e 现场那一行可追平
def test_e_a_redelivery_repairs_the_live_contradiction(tmp_path: pathlib.Path) -> None:
    """e：已经在场的那种矛盾行，同一份正文再收录一次就追平（不必手改盘）。

    现场 `statements:000000` 就是这一种形态：`proof_text` 在、`reviewed=true`、
    `proof=false`。修好之后，B 再走一次收录（同一条命题、同一份正文）会命中
    `duplicate_statement` 那一支，而那一支也调 `_attach_proofs` —— 第 2 位按行上的
    正文补翻、回执与 `_grade_recomputed` 同一笔补上。这一条钉的是"存量不必手改"。
    """
    env = _env(tmp_path)
    _sign(env)
    assert _register(env).get("ok") is True
    row = _row(env)
    # 把行退回到现场的形态（正文在、第 3 位说见过签、第 2 位空、没有回执/回填）。
    bits = dict(row.get("bits") or {})
    bits["proof"] = False
    row["bits"] = EB.normalize_raw(bits, origin="own_result",
                                   kind=str(row.get("kind") or ""))
    row.pop(VR.GRADE_RECOMPUTED_KEY, None)
    row.pop("proof_no", None)
    row.pop("proof_sha256", None)
    with env["store"].tx("statements", actor="probe") as tx:
        tx.upsert("statements", row)
    live = _row(env)
    assert (live.get("bits") or {}).get("proof") is False, live
    assert (live.get("bits") or {}).get("reviewed") is True, live

    filed = _register(env)
    assert filed.get("ok") is True, filed
    repaired = _row(env)
    bits = dict(repaired.get("bits") or {})
    assert bits.get("proof") is True and bits.get("reviewed") is True, bits
    assert bits.get("grade") == "pre_theorem", bits
    assert repaired.get("proof_no") == 1, repaired
    assert repaired.get("proof_sha256") == VR.text_sha(PROOF), repaired
    assert _trace(repaired).get("to") == "pre_theorem", _trace(repaired)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))