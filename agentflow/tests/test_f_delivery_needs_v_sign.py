# -*- coding: utf-8 -*-
"""F 的交差要有 V 签（业主 2026-11-02 逐字：「重点是要F侧拿V签，拿到V签F才能交差」）。

## 这一组守什么

改前：`F -> V` 那条边一直在（`capabilities.ALLOWED_EDGES["F"]` 含 `"V"`），
`agent_skills` 也一直教 F「你产出的证明由你派 V 签」，而 `agent_f` 的实现交完
B 的登记就结束了 —— 没有一处真的送审，也没有一处回读签。于是 F 的 `step`
无论签没签都回 `outcome=progress`，读数里根本没有「签」这一格。
83 的定格现场就是它：F 写的五份证明一份都没签（`out/vsigns/` 只有 000005 一份）。

改后：`agent_f/vsign.py` 提供两件事 —— `submit_proof`（把这一份递给 V）与
`delivery_reading`（回读签，四档）；`F.step` 的返回值与 history 里带这一格，
`delivered` 只在「已签」时为真。

## 四条判据（先红后绿；红的样子写在每一条的 docstring 里）

| # | 造什么 | 期望 |
|---|---|---|
| a | F 写完证明 + 送审 + 三轮干净（一次 `verify_proof` 内） | 签在盘；读数 = 已签 |
| a2 | 命题还没在册时 V 审过（pending 签在盘） | 读数 = 已签（在册 / pending 都算） |
| b | F 写完证明、没送审 | 读数 = 待签；`delivered` 为假 |
| c | F 送了、V 判有毛病 | 读数 = 未通过 |
| d | 反真空：把签删掉（pending 台账 / 在册签文件） | 读数必须回落（不是恒绿） |

零模型调用：V 的审阅缝逐个交出预置回复，秘书缝按 `note` 回预置 JSON
（夹具与 `test_v_reviews_three_times_before_signing.py` 共用同一套替身）。
"""
from __future__ import annotations

import json
import pathlib

import pytest
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.agent_f import vsign as FVS
from agentflow.agent_v import AgentV
from agentflow.store import Store

# 夹具（假缝 + 命题行 + 秘书）与三连判判据共用一份，不抄第二份。
from test_v_reviews_three_times_before_signing import (
    CLEAN_REPLY,
    _axis,
    _ReviewSeam,
    _Seam,
    _secretary,
)

TS = "2026-11-02T09:00:00+08:00"
SID = "000000"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
#: 改一个字（ε → ε/2）的同一份命题的另一版正文。
PROOF_CHANGED = PROOF.replace("δ=ε", "δ=ε/2")
OK = {"verdict": "成立", "why": "逐条核过，没有缺陷", "findings": []}
FAULT = {"verdict": "有毛病", "defect_step": 2,
         "why": "第 2 步直接用了结论", "findings": [
             {"level": "error", "step": 2, "kind": "无依据的步骤",
              "detail": "第 2 步把待证结论当成了依据"}]}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _register(st: Store, *, proof: str = PROOF) -> str:
    """走生产的登记正路把这一条落成在册命题（F 的 `_proof_outlet` 做的就是这一笔）。"""
    got = AgentB(st, extractor=None, extract_text=None).register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=proof,
        kind="conjecture", label="探针命题", origin="own_result",
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="夹具：自产证明，没有第二份文本可比对",
        line_range={"label": "reports/f-proof-plan-0000.md"})
    assert got.get("ok") is True, got
    return str(got.get("stmt_id") or "")


def _v(st: Store, replies: list[str], sec_answers: dict | None = None) -> AgentV:
    """带假缝的 V（不调真模型）：审阅缝按顺序出预置回复，秘书缝出预置 JSON。"""
    seam = _Seam(sec_answers or {
        "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
        "sign_issuance": [_axis(SEC.SIGN_ISSUE)],
    })
    return AgentV(st, workspace_root=st.root, llm=_ReviewSeam(list(replies)),
                  secretary=_secretary(st, seam))


def _f(st: Store, verifier=None) -> AgentF:
    """F 的一个实例：`v_verifier` 是送审的注入点（生产路径不传，就用真的 V）。"""
    cfg: dict = {"workspace_root": str(st.root)}
    if verifier is not None:
        cfg["v_verifier"] = verifier
    return AgentF(st, config=cfg)


# ============================================================ a：送审 + 三轮干净

def test_a_submitting_three_clean_rounds_puts_a_sign_on_disk(tmp_path):
    """a 造「F 写完证明 + 送审 + 三轮干净」⇒ 签在盘；F 的交差读数 = 已签。

    改前红：`AgentF._submit_and_read_sign` 不存在（F 这一侧没有送审这一步），
    签文件也不会出现 —— 这个用例在改前直接 AttributeError。
    """
    st = _ws(tmp_path)
    sid = _register(st)
    assert sid == SID, sid
    v = _v(st, [CLEAN_REPLY])
    f = _f(st, verifier=v)

    got = f._submit_and_read_sign(statement_id=sid, proof_text=PROOF)
    reading = dict(got.get("reading") or {})

    # 真的送出去了：V 那一次调用自己连判三轮（不是 F 交三次）。
    assert got.get("submitted") is True, got
    assert got["verification"]["asked"] == 3, got["verification"]
    # 签在盘：out/vsigns/<正文 sha>.json，连续 3/3。
    sign_path = VS.sign_path(st.root, VR.proof_sha(PROOF))
    assert sign_path.is_file(), f"没有落签：{sign_path}"
    doc = json.loads(sign_path.read_text(encoding="utf-8"))
    assert (doc["streak"], doc["need"]) == (3, 3), doc
    # F 的交差读数：已签、delivered 为真。
    assert reading["state"] == FVS.STATE_SIGNED, reading
    assert reading["label"] == "已签", reading
    assert reading["delivered"] is True, reading
    assert reading["channel"] in (FVS.CHANNEL_ON_SHELF, FVS.CHANNEL_LEDGER), reading


def test_a2_a_pending_sign_also_counts_as_signed(tmp_path):
    """a2：「先签后登记」的那一签（pending 台账）同样算已签 —— 在册或 pending 都可以。

    这一档就是 `verifications.record_pending_sign` 的落点（V 在命题还没在册时审的那一签）：
    B 登记时按正文 sha 认领它（`vsigns._claim_pending_sign`），F 的交差读数必须与
    同一把尺说同一句话。
    """
    st = _ws(tmp_path)
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict=dict(OK))

    reading = FVS.delivery_reading(st.root, statement_id="", proof_text=PROOF)
    assert reading["state"] == FVS.STATE_SIGNED, reading
    assert reading["channel"] == FVS.CHANNEL_PENDING, reading
    assert reading["delivered"] is True, reading
    # 反真空：改一个字 ⇒ 同一把尺立刻回落（sha 不符，认不到那一签）。
    changed = FVS.delivery_reading(st.root, statement_id="", proof_text=PROOF_CHANGED)
    assert changed["state"] != FVS.STATE_SIGNED, changed


# ============================================================ b：没送审 = 待签

def test_b_a_proof_that_was_never_submitted_reads_as_waiting(tmp_path):
    """b 造「F 写完证明但没送审」⇒ 交差读数 = 待签，不许算交差。

    改前红：`step` 的返回值里没有 `v_sign` / `delivered` 这一格 ——
    「没送审」与「已签」在读数上根本分不开。
    """
    st = _ws(tmp_path)
    sid = _register(st)

    reading = FVS.delivery_reading(st.root, statement_id=sid, proof_text=PROOF)
    assert reading["state"] == FVS.STATE_WAITING, reading
    assert reading["label"] == "待签", reading
    assert reading["delivered"] is False, reading
    assert "没有签" in reading["why"] or "没送审" in reading["why"], reading

    # 送审那一步也知道「还没送」：它没有跳过（skipped 为假），因为确实没有过审的结论。
    got = FVS.submit_proof(store=st, root=st.root, statement_id=sid,
                           proof_text=PROOF, verifier=_v(st, [CLEAN_REPLY]))
    assert got["submitted"] is True, got


# ============================================================ c：V 判有毛病

def test_c_a_rejected_proof_reads_as_not_passed(tmp_path):
    """c 造「F 送了、V 判有毛病」⇒ 交差读数 = 未通过（不是待签，也不是已签）。

    两态纪律：V 只产「成立 / 有毛病」；这里造的是结论「有毛病」+ 步号。
    读数必须把它与「还没送审」分开（处置不同：一个改稿、一个去送审）。
    """
    st = _ws(tmp_path)
    sid = _register(st)
    v = _v(st, [json.dumps(FAULT, ensure_ascii=False)], {
        "v_reply_defect": [_axis(SEC.V_REPLY_FAULT)],
        "wash_v_reply": [{"text": "第 2 步把待证结论当成了依据：请补上依据。", "step": 2,
                          "findings": [{"quote": "按定义即一致连续",
                                        "why": "这一步直接用了结论"}]}],
        "sign_issuance": [_axis(SEC.SIGN_ISSUE)],
    })
    f = _f(st, verifier=v)

    got = f._submit_and_read_sign(statement_id=sid, proof_text=PROOF)
    reading = dict(got.get("reading") or {})
    assert got.get("submitted") is True, got
    assert reading["state"] == FVS.STATE_REJECTED, reading
    assert reading["label"] == "未通过", reading
    assert reading["delivered"] is False, reading
    # 没有签：out/vsigns 里这一份的签文件不存在。
    assert not VS.sign_path(st.root, VR.proof_sha(PROOF)).is_file()


# ============================================================ d：反真空

def test_d1_deleting_the_pending_sign_falls_back_to_waiting(tmp_path):
    """d1 反真空：pending 签在盘 ⇒ 已签；把那一份台账删掉 ⇒ 必须回落成待签。

    它证明读数是真的在读签，不是一个恒绿的字面量。
    """
    st = _ws(tmp_path)
    path = VR.pending_ledger_path(st.root, VR.proof_sha(PROOF))
    VR.record_pending_sign(st.root, proof_text=PROOF, verdict=dict(OK))
    assert path.is_file(), path
    assert FVS.delivery_reading(st.root, proof_text=PROOF)["state"] == FVS.STATE_SIGNED

    path.unlink()
    after = FVS.delivery_reading(st.root, proof_text=PROOF)
    assert after["state"] == FVS.STATE_WAITING, after
    assert after["delivered"] is False, after


def test_d2_the_shelf_sign_is_read_from_disk_not_a_constant(tmp_path):
    """d2 反真空（在册那一支）：签有两个落点（`out/vsigns/<sha>.json` 与台账那三行
    clean），只有两处都不在了读数才回落 —— 它证明这一格真的从盘上读，不是恒绿。

    为什么不删一处就必须回落：同一件事在盘上有两个落点（秘书发的签文件 / 它判过的
    三行台账），`verifications.review_standing` 读的就是后者（收工门 R10 也用那一把尺）。
    删掉签文件而台账还在时读数仍是已签 —— 那不是"恒绿"，是第二处证据还在；
    两处都删掉之后必须回落，这一条量的就是这件事。
    """
    st = _ws(tmp_path)
    sid = _register(st)
    f = _f(st, verifier=_v(st, [CLEAN_REPLY]))
    f._submit_and_read_sign(statement_id=sid, proof_text=PROOF)
    sign_path = VS.sign_path(st.root, VR.proof_sha(PROOF))
    ledger_path = VR.verification_ledger_path(st.root, sid)
    assert sign_path.is_file() and ledger_path.is_file(), (sign_path, ledger_path)
    assert FVS.delivery_reading(st.root, statement_id=sid,
                                proof_text=PROOF)["state"] == FVS.STATE_SIGNED

    # 只删签文件：台账那三行 clean 还在 ⇒ 仍是已签（第二处证据）。
    sign_path.unlink()
    assert FVS.delivery_reading(st.root, statement_id=sid,
                                proof_text=PROOF)["state"] == FVS.STATE_SIGNED

    # 两处都删掉 ⇒ 必须回落成待签（不是恒绿）。
    ledger_path.unlink()
    after = FVS.delivery_reading(st.root, statement_id=sid, proof_text=PROOF)
    assert after["state"] == FVS.STATE_WAITING, after
    assert after["delivered"] is False, after


# ============================================================ F.step 的那一格

class _FSecretary:
    """F 的秘书替身：洗稿照过（`_apply_round` 的 proof 分支要求它这一遍核得过）。"""
    actor = "fake-F-secretary"
    seam = object()

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": self.actor,
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


class _DeadV:
    """没接线的 V（`judge_not_wired`）：证明「送审没成」那一档也带得出读数。"""

    def verify_proof(self, **kw) -> dict:
        return {"checked": False, "reason": "judge_not_wired",
                "detail": "夹具：V 没有审阅缝 ⇒ 这一份没审成", "review_passes": []}


def _apply_one_proof_round(st: Store, *, verifier=None) -> dict:
    """走 `_apply_round` 的 proof 分支（不调模型：产物是直接给的）。"""
    f = _f(st, verifier=verifier)
    f.f_secretary = _FSecretary()
    plan = {"plan_id": "0000", "rounds": 0, "history": [], "subgoals": [],
            "budget": {"max_rounds": 9}, "status": "open"}
    sg = {"sid": "s1", "text": FULL, "owner": "F", "status": "in_progress"}
    product = {"product": "proof", "strategy": "direct",
               "steps": [{"n": 1, "text": "取 δ=ε，逐点验证。", "cites": [],
                          "assumption": False},
                         {"n": 2, "text": "δ 只依赖 ε ⇒ 一致连续。", "cites": []}],
               "best_partial": [], "why_strategy": "直接按定义"}
    return f._apply_round(product, sg, plan=plan, owner="F")


def test_the_step_cell_says_signed_only_when_the_sign_is_on_disk(tmp_path):
    """F 的这一趟带「签」这一格：签在盘 ⇒ 已签 / 没送成 ⇒ 没交差。

    改前红：`_apply_round` 的返回值里没有 `v_sign` / `delivered` 这两格
    （KeyError）—— 「这一趟交没交差」在读数上根本不存在。
    """
    st = _ws(tmp_path)
    signed = _apply_one_proof_round(st, verifier=_v(st, [CLEAN_REPLY]))
    v_sign = dict(signed.get("v_sign") or {})
    reading = dict(v_sign.get("reading") or {})
    assert signed.get("delivered") is True, signed
    assert signed.get("delivery_state") == FVS.STATE_SIGNED, signed
    assert reading.get("label") == "已签", reading
    assert "V 签：已签" in str(signed.get("detail") or ""), signed.get("detail")
    sid = str(signed.get("statement_id") or "")
    assert sid, signed

    # 反真空：换一条命题、V 没签（这一趟没送成 / 没签）⇒ 同一格必须说没交差。
    st2 = _ws(tmp_path / "ws2")
    _register(st2)
    unsent = _apply_one_proof_round(st2, verifier=_DeadV())
    assert unsent.get("delivered") is False, unsent
    assert unsent.get("delivery_state") != FVS.STATE_SIGNED, unsent
    assert "没签 ⇒ 这一趟不算交差" in str(unsent.get("detail") or ""), unsent.get("detail")


def test_the_reading_is_not_a_constant_even_for_a_registered_proof(tmp_path):
    """反真空（三态合看）：同一份在册证明，随盘上状态在 待签 / 未通过 / 已签 之间真的变。

    这一条钉的是「读数从盘上读」：三个状态用的是同一份正文、同一条命题。
    """
    st = _ws(tmp_path)
    sid = _register(st)
    assert FVS.delivery_reading(st.root, statement_id=sid,
                                proof_text=PROOF)["state"] == FVS.STATE_WAITING

    _v(st, [json.dumps(FAULT, ensure_ascii=False)], {
        "v_reply_defect": [_axis(SEC.V_REPLY_FAULT)],
        "wash_v_reply": [{"text": "请补第 2 步的依据。", "step": 2,
                          "findings": [{"quote": "按定义即一致连续",
                                        "why": "这一步直接用了结论"}]}],
        "sign_issuance": [_axis(SEC.SIGN_ISSUE)],
    }).verify_proof(sid, proof_text=PROOF)
    assert FVS.delivery_reading(st.root, statement_id=sid,
                                proof_text=PROOF)["state"] == FVS.STATE_REJECTED

    _v(st, [CLEAN_REPLY]).verify_proof(sid, proof_text=PROOF)
    assert FVS.delivery_reading(st.root, statement_id=sid,
                                proof_text=PROOF)["state"] == FVS.STATE_SIGNED
