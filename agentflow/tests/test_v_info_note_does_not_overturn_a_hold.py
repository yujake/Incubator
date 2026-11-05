# -*- coding: utf-8 -*-
"""判词由 V 定，findings 只是备注（2026-11-06 真机 `projects/R-mk-infinite-92`）。

## 现场（只读，逐字）

`verifications/000000.jsonl` 的 v-000001 / v-000002 / v-000003 都是
`verdict=成立`、`defect_step=null`、`unresolved_errors=0`；v-000003 的 findings 只有一条
`{"kind":"表述限定语","level":"info","step":2,"detail":"…此句不承重。"}`。
但同一行的 `secretary_judge` 是 `axis=fault`，理由逐字：

    V 虽称未找到承重缺陷并尝试反例，但在 findings 中明确指认第2步表述过强、需要加限定语，
    属于挑出了一处非承重缺陷/记号问题，不能算完全没毛病

于是三连干净成立被判成 2 票（第 3 票清零）。判据在这里收窄：

- `defect_step` 非空，或 findings 里有 `level=error`（承重档）⇒ 才算「有毛病」；
- `verdict=成立` + `defect_step` 空 + findings 全是 `level=info`（备注档）⇒ 不推翻
  「成立」，备注原文留在台账那一行的 findings 里。

## 判据表（每条都带"它能怎么红"）

| 编号 | 它要证明的事 | 它能怎么红 |
|---|---|---|
| a | 现场形状（成立 + 无 defect_step + 仅一条 info）⇒ clean，三连后 streak=3、可签 | 把备注当缺陷 ⇒ v-000003 那一行判 fault、streak 停在 2、位不翻 |
| b | `defect_step` 非空 ⇒ 仍判 fault（不放宽） | 只认 findings 的级别、不看 defect_step ⇒ 有毛病的行被当成 clean |
| c | findings 里有 `level=error`（承重档）⇒ 仍判 fault，且那一行不可签 | 把 error 也当备注 ⇒ 带未解决 error 的行混进连续票 |
| d | 反真空：把 `info` 的备注档摘掉（`NOTE_FINDING_LEVELS` 清空）⇒ a 恢复成 fault | 判据没量到那条收窄（改不改都绿）⇒ 它是装饰 |

全部 tmp 工作区、零真模型调用：V 的秘书那条缝是离线替身，并且故意答
「有缺陷要指出」—— 改前它就是这么答的；a 能绿只能靠代码先按台账读数判掉那一问。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _proof_manuscript_fixture import write_proof_manuscript

from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.store import Store

TS = "2026-10-29T00:00:00+08:00"
SID = "000007"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"

#: 现场那条 finding（逐字形状；`level=info`、`step=2`、"此句不承重"）。
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


def _fault_seam() -> _Seam:
    """改前真机的答案：只要回复里有 finding 就判「有缺陷要指出」。"""
    return _Seam({"checked": True, "decision": SEC.V_REPLY_FAULT,
                  "reason": "夹具：只要有一条 finding 就算有毛病",
                  "basis": ["夹具"]})


def _sec(st: Store, seam: _Seam | None = None) -> SEC.Secretary:
    return SEC.Secretary("V", root=st.root, store=st, seam=seam,
                         enable_model=seam is not None)


def _judge(sec: SEC.Secretary, *, defect_step=None, findings=None) -> dict:
    return sec.judge_v_reply(reply=REPLY, verdict="成立", defect_step=defect_step,
                             findings=INFO_FINDINGS if findings is None else findings,
                             statement_id=SID)


def _sign(store: Store, judge: dict, *, verdict: dict | None = None) -> dict:
    """落一行 V 的审校台账（直调写入口；连续闸那一半由 `consecutive_holds` 现读）。"""
    return VR.record_verification(store.root, statement_id=SID, proof_text=PROOF,
                                  verdict=verdict or {"verdict": "成立", "findings": [],
                                                      "defect_step": None},
                                  verifier="agent-V", store=store, proof_no=1,
                                  secretary_judge=judge)


# ============================================================ a：现场形状

def test_a_info_only_findings_do_not_overturn_a_hold(tmp_path):
    """a：成立 + defect_step=None + 仅一条 level=info ⇒ clean，三连后 streak=3、可签。

    改前（本用例的缝就是改前那个模型的答案）：秘书答「有缺陷要指出」⇒ v-000003 那一行
    `axis=fault` ⇒ `_hold_run_lengths` 清零 ⇒ 三连干净成立只剩 2 票，位不翻。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _fault_seam()          # 故意给"旧判法"的答案：收窄必须先于这一问生效
    sec = _sec(st, seam)

    judges = []
    for i in (1, 2, 3):
        got = _judge(sec)
        assert got["checked"] is True, got
        assert got["axis"] == "clean", (
            f"第 {i} 次：info 备注被当成承重缺陷，秘书推翻了 V 的「成立」：{got}")
        assert got["answer"] == SEC.V_REPLY_CLEAN, got
        assert "info" in got["reason"] and "不推翻" in got["reason"], got["reason"]
        judges.append(got)

    # 收窄是机械判：那一问一次都不该发出去（改前发了、并且答成 fault）。
    assert seam.asked("v_reply_defect") == 0, (
        f"收窄之后仍然问了模型 {seam.asked('v_reply_defect')} 次 ⇒ 现场那一行还会被判 fault")

    rows = [_sign(st, j) for j in judges]
    holds = VR.consecutive_holds(st.root, SID)
    assert holds["checked"] is True and holds["streak"] == 3, (
        f"三连干净成立读成 {holds}（改前是 2：v-000003 那一行 fault 清零）")
    assert holds["streak_ok"] is True and holds["need"] == VR.SIGN_STREAK_NEED, holds
    assert all(VR.row_signable(r) for r in rows), rows
    assert VR.signs_bit3(rows[-1], streak=holds) is True, rows[-1]
    assert _row(st)["bits"]["reviewed"] is True, _row(st)["bits"]


# ============================================================ b：defect_step 不放宽

def test_b_a_defect_step_still_counts_as_a_defect(tmp_path):
    """b：`defect_step` 非空 ⇒ 仍算「有毛病」（不放宽）。

    现场那条 info 原样带着，只把 `defect_step` 改成 2：这一档 V 自己指到了那一步，
    秘书必须判 fault，而且不问模型（判词已经在台账上）。
    """
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"checked": True, "decision": SEC.V_REPLY_CLEAN,
                  "reason": "夹具：反方向的答案（这一条不该被采信）"})
    got = _judge(_sec(st, seam), defect_step=2)
    assert got["checked"] is True, got
    assert got["axis"] == "fault", got
    assert "defect_step" in got["reason"], got["reason"]
    assert seam.asked("v_reply_defect") == 0, "defect_step 已经是台账读数，不该再问模型"
    _sign(st, got)
    assert VR.consecutive_holds(st.root, SID)["streak"] == 0, "fault 被计入了连续票"


# ============================================================ c：error 不放宽

def test_c_a_load_bearing_finding_still_counts_as_a_defect(tmp_path):
    """c：findings 里那条是 `level=error`（承重档）⇒ 仍算「有毛病」，那一行不可签。

    与 a 只差一个 `level`：`info` → `error`。这就是"哪一档算承重"的全部区别。
    """
    st = _ws(tmp_path)
    _put(st)
    error_findings = [{**INFO_FINDINGS[0], "level": "error"}]
    seam = _Seam({"checked": True, "decision": SEC.V_REPLY_CLEAN,
                  "reason": "夹具：反方向的答案（这一条不该被采信）"})
    got = _judge(_sec(st, seam), findings=error_findings)
    assert got["checked"] is True, got
    assert got["axis"] == "fault", got
    assert "error" in got["reason"], got["reason"]
    assert seam.asked("v_reply_defect") == 0, "承重档已经是台账读数，不该再问模型"
    row = _sign(st, got, verdict={"verdict": "成立", "defect_step": None,
                                  "findings": error_findings})
    assert int(row.get("unresolved_errors") or 0) == 1, row
    assert VR.row_signable(row) is False, "带未解决 error 的行被判成可签"
    assert VR.consecutive_holds(st.root, SID)["streak"] == 0
    assert _row(st)["bits"]["reviewed"] is False, _row(st)["bits"]


# ============================================================ e0：词表来源

def test_e0_the_two_grades_come_from_the_controlled_vocabulary():
    """e0：两个档的取值必须都在 `FINDING_LEVELS` 里（不许新造字符串）。

    收窄的判据是"哪一档算承重"，这一档只能从受控词表里挑（`schema.FINDING_LEVELS`
    → `verifications.FINDING_LEVELS`），不许在秘书那一侧另立一个新词。
    """
    known = set(VR.FINDING_LEVELS)
    assert VR.NOTE_FINDING_LEVELS <= known, (VR.NOTE_FINDING_LEVELS, known)
    assert VR.LOAD_BEARING_FINDING_LEVELS <= known, (VR.LOAD_BEARING_FINDING_LEVELS, known)
    assert VR.NOTE_FINDING_LEVELS.isdisjoint(VR.LOAD_BEARING_FINDING_LEVELS)
    assert "info" in VR.NOTE_FINDING_LEVELS
    assert "error" in VR.LOAD_BEARING_FINDING_LEVELS


# ============================================================ d：反真空

def test_d_removing_the_note_grade_turns_a_back_to_fault(tmp_path, monkeypatch):
    """d：把 `info` 的备注档摘掉 ⇒ a 恢复成改前的读数（fault）。

    只改判定用的那份词表（`verifications.NOTE_FINDING_LEVELS`），不改被测代码路径：
    摘掉之后 `load_bearing_reading` 判不出"备注档"，那一问回到模型 ⇒ 缝答 fault。
    这一步必须能让 a 红，否则 a 量的不是"收窄"，而是别的东西。
    """
    st = _ws(tmp_path)
    _put(st)
    monkeypatch.setattr(VR, "NOTE_FINDING_LEVELS", frozenset())
    seam = _fault_seam()
    got = _judge(_sec(st, seam))
    assert seam.asked("v_reply_defect") == 1, "收窄摘掉之后没有回到模型那一问"
    assert got["axis"] == "fault", (
        "摘掉 info 备注档之后仍然判 clean ⇒ a 的绿与那条收窄无关（判据是装饰）")
    _sign(st, got)
    assert VR.consecutive_holds(st.root, SID)["streak"] == 0
