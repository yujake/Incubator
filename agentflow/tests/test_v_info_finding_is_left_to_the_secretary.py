# -*- coding: utf-8 -*-
"""成立 + 一条 `info` 级 finding ⇒ 仍然交给秘书按题面语义判（2026-11-06 业主裁定）。

## 为什么要留这一条

`9c5df7fc` 曾经把「findings 里只有 `level=info`」机械地判成"不是缺陷"
（`verifications.load_bearing_reading`：`defect_step` 空 + 只有 info ⇒ clean，不问模型）。
业主 2026-11-06 的裁定是：「判定要回给秘书的语义判断」 ——「info 级 finding 也确实会让
这一转不算干净」这句话是秘书判出来的结论，不是代码数 finding 条数数出来的。

这一份只钉两件事（不钉"同一形状必须两次同结论"——判定是语义的，那由题面与模型定）：

- a 成立 + 一条 info：秘书答「有缺陷要指出」⇒ 这一转不算干净：streak 不增、不签发。
  这一条证明的是"允许它这么判"（不是"要求它必须这么判"）。
- b 成立 + findings 空：秘书答「没问题」⇒ 干净：streak +1、这一行可签。

两半都断言秘书真的被问过一次 —— `9c5df7fc` 的机械支一次都不问，那正是被撤回的形状。

全部 tmp 工作区、零真模型调用：秘书那条缝是离线替身，答什么由夹具给。
"""
from __future__ import annotations

import pathlib

from _proof_manuscript_fixture import write_proof_manuscript

from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.store import Store

TS = "2026-10-29T00:00:00+08:00"
SID = "000007"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"

#: 真机现场那条 finding 的形状：`level=info`、`step=2`、"此句不承重"。
INFO_FINDINGS = [{"level": "info", "step": 2, "kind": "表述限定语",
                  "detail": ("第2步末句『含e的k-圈只能是C_k本身』宜读作『在C_k内』；"
                             "作为任意扩图的断言偏强，但第6步另有独立论据，此句不承重。")}]

#: V 的回复正文（秘书那一问的对象；它不是证明正文，可以给）。
REPLY = ("我试了几种反例构造都失败，未发现问题。第2步末句宜读作『在C_k内』，"
         "此句不承重。")


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(store: Store) -> dict:
    """落一条在册命题（走真事务；夹具只造这一行）。"""
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": FULL,
        "statement_text": "弦长函数不是常值", "proof_text": PROOF,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=PROOF, kind="theorem"),
    }
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    write_proof_manuscript(store.root, SID, PROOF, statement_full=FULL)
    return row


def _row(store: Store) -> dict:
    return dict(store.rows("statements")[0])


class _Call:
    """`llmseam.SeamCall` 的替身：`judge()` 只读 ok / problem / detail。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _Seam:
    """离线替身缝：把秘书那一问答成预置的结论，并记住问过几次。"""

    wired = True

    def __init__(self, answer: dict) -> None:
        self.answer = dict(answer)
        self.seen: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict | None, _Call]:
        self.seen.append(note)
        return dict(self.answer), _Call()

    def asked(self, kind: str) -> int:
        return sum(1 for note in self.seen if note.endswith(f":{kind}"))


def _sec(st: Store, seam: _Seam) -> SEC.Secretary:
    return SEC.Secretary("V", root=st.root, store=st, seam=seam, enable_model=True)


def _judge(sec: SEC.Secretary, *, defect_step=None) -> dict:
    """问秘书：这条 V 的回复有没有指出缺陷（与改前一样，只给回复与台账读数）。"""
    return sec.judge_v_reply(reply=REPLY, verdict="成立", defect_step=defect_step,
                             statement_id=SID)


def _sign(store: Store, judge: dict, *, verdict: dict) -> dict:
    """落一行 V 的审校台账（直调写入口；连续闸那一半由 `consecutive_holds` 现读）。"""
    return VR.record_verification(store.root, statement_id=SID, proof_text=PROOF,
                                  verdict=verdict, verifier="agent-V", store=store,
                                  proof_no=1, secretary_judge=judge)


# ============================================================ a：成立 + info 可以判不干净

def test_a_an_info_finding_may_still_make_the_turn_not_clean(tmp_path):
    """a：成立 + `defect_step` 空 + 一条 `level=info` ⇒ 秘书可以判「有缺陷要指出」。

    这一条不是"要求模型必须这么判"：它钉的是"判定权在秘书的语义判断" ——
    夹具让缝答 fault，代码必须采信它，而不是按 finding 的级别把它机械折成 clean。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"checked": True, "decision": SEC.V_REPLY_FAULT,
                  "reason": "夹具：按题面『只挑出一处小记号问题也算有毛病』判",
                  "basis": ["夹具"]})
    got = _judge(_sec(st, seam))
    assert seam.asked("v_reply_defect") == 1, (
        "秘书没有被问过 ⇒ 判定又回到了数 finding 条数（9c5df7fc 的机械支）")
    assert got["checked"] is True, got
    assert got["axis"] == "fault", got
    assert got["answer"] == SEC.V_REPLY_FAULT, got
    assert "夹具" in got["reason"], got["reason"]

    row = _sign(st, got, verdict={"verdict": "成立", "defect_step": None,
                                  "findings": INFO_FINDINGS})
    # info 不进 `unresolved_errors`：这一行自己不是"带未解决 error"的形状，
    # 挡签的是秘书判出来的 fault（连续票清零），不是 error 计数。
    assert int(row.get("unresolved_errors") or 0) == 0, row
    assert VR.consecutive_holds(st.root, SID)["streak"] == 0, "fault 被计入了连续票"
    assert VR.signs_bit3(row, streak=VR.consecutive_holds(st.root, SID)) is False, row
    assert _row(st)["bits"]["reviewed"] is False, _row(st)["bits"]


# ============================================================ b：零 finding 可以判干净

def test_b_zero_findings_lets_the_secretary_call_it_clean(tmp_path):
    """b：成立 + findings 空 ⇒ 秘书答「没问题」⇒ 干净：每转 +1，三转后可签。

    同样证明秘书真的被问过（三转三次）：改前 9c5df7fc 的机械支在这一形状上一次都不问
    （它自己按"findings 空"判了 clean）。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"checked": True, "decision": SEC.V_REPLY_CLEAN,
                  "reason": "夹具：未发现问题", "basis": ["夹具"]})
    sec = _sec(st, seam)
    rows = []
    for i in (1, 2, 3):
        got = _judge(sec)
        assert got["checked"] is True and got["axis"] == "clean", (i, got)
        assert got["answer"] == SEC.V_REPLY_CLEAN, (i, got)
        rows.append(_sign(st, got, verdict={"verdict": "成立", "defect_step": None,
                                            "findings": []}))
    assert seam.asked("v_reply_defect") == 3, "三转里秘书没有被问过三次 ⇒ 判定又不是语义判断了"
    assert all(VR.row_signable(r) for r in rows), rows
    holds = VR.consecutive_holds(st.root, SID)
    assert holds["checked"] is True and holds["streak"] == 3, holds
    assert VR.signs_bit3(rows[-1], streak=holds) is True, rows[-1]
    assert _row(st)["bits"]["reviewed"] is True, _row(st)["bits"]
