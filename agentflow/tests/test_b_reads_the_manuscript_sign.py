# -*- coding: utf-8 -*-
"""B 收录时从手稿里读到 V 签（业主 2026-11-01 逐字，2026-11-02 再确认）。

    业主原话：「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或命题
    收录时读到。」「不是说好了 V 签先放在 F 的手稿里让 B 录入吗」

改前：B 这一侧认签只认两处 —— `out/vsigns/<正文 sha>.json` 与
`verifications/pending/<sha>.jsonl`（`register_statement.py` 的认领那一段）；
手稿里那一行签块它一个字都不读。于是「签先进手稿、B 收录时读到」这条业主要的路
在 B 那一侧是断的：手稿里有签，登记照样按"没有签"办。

改后：B 的两处读口都先看手稿块（`vsigns.manuscript_sign_standing`：
sha 相符 + 连续次数够 ⇒ signed），再看 pending / 侧文件。写路径一个字节没动。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| ① | 手稿带签块（sha 相符、3/3 成立），登记一条自产 theorem | 收下；`bits.reviewed` 真 |
| ② | 同一份稿不带签块 | 退回（自产 theorem 没有 V 签 = `self_authored_proof_needs_v` 那一档） |
| ③ | 签块盖的是另一版正文（改过一个字） | 退回（不许借旧版的签） |
| ④ | 签块写 `已签=false；判词=有毛病` | 退回（审过、没过） |
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
              "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。\n\n"
              "## 依赖\n\n"
              "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
              "|---|---|---|---|\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
PROOF = _DS.proof_body(MANUSCRIPT).strip("\n")
REL = "reports/f-proof-plan-0000.md"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _manuscript(st: Store, *, block: bool = True, signed: bool = True,
                verdict: str = "成立", sha: str = "", body: str = PROOF) -> str:
    text = MANUSCRIPT
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    want = sha or VR.proof_sha(body)
    # 2026-11-05 晚（业主）：签块必须有独立台账背书 —— 稿头自述（`reports/… #V签`）
    # 是假签。夹具在这里先落一行 pending 台账，再把它的锚点写进块里（真签的形状）。
    row = VR.record_pending_sign(
        st.root, proof_text=body,
        verdict=({"verdict": verdict} if verdict == "成立" else {
            "verdict": verdict, "defect_step": 2,
            "quote": "夹具：第 1 步直接取 δ=ε", "why": "夹具：对一般连续函数不成立"}),
        verifier="agent-V", object_path=REL, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    ledger = (f"verifications/pending/"
              f"{str(row.get('object_sha256') or row.get('proof_sha256'))}.jsonl"
              f"#{row.get('verification_id')}")
    if block and want != VR.proof_sha(PROOF):
        # ③ 号那一档要的是"盖着另一版正文的块"：`write_manuscript_sign` 自 2026-11-02
        # 起会核「这份稿的正文 == 被签的那一份」并拒掉这一笔（body_mismatch），
        # 所以夹具在这里直接拼块（纯字符串），才量得到"B 不借旧版的签"这件事。
        path.write_text(VS.stamp_manuscript_sign(
            text, proof_sha=want, streak=3, need=3, verdict=verdict, signer="V",
            at="2026-11-02T10:00:00+08:00", ledger=ledger, statement_id="",
            manuscript_id=VS.manuscript_id_of(REL),
            signed=(verdict == "成立")), encoding="utf-8")
    elif block:
        VS.write_manuscript_sign(
            st.root, REL, proof_sha=want, streak=3,
            need=3, verdict=verdict, signer="V", at="2026-11-02T10:00:00+08:00",
            ledger=ledger, statement_id="", signed=(verdict == "成立"))
    return path.read_text(encoding="utf-8")


def _register(st: Store, manuscript_text: str) -> dict:
    b = AgentB(st, extractor=None, extract_text=None)
    return b.register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=PROOF,
        proof_manuscript=manuscript_text, kind="theorem", label="探针命题",
        origin="own_result", evidence_kind="heuristic",
        quote_verified=None,
        quote_reason="夹具：自产证明，没有第二份文本可比对",
        line_range={"label": REL})


def _row(st: Store) -> dict:
    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1, rows
    return rows[0]


# ============================================================ ① 读到签
def test_a_the_manuscript_block_is_read_at_registration(tmp_path):
    """① 手稿带签块 ⇒ B 收下，第 3 位按签写。"""
    st = _ws(tmp_path)
    text = _manuscript(st)
    got = _register(st, text)

    assert got.get("ok") is True, got
    v_sign = dict(got.get("v_sign") or {})
    assert v_sign.get("applied") is True, v_sign
    assert "手稿" in str(v_sign.get("why") or ""), v_sign
    bits = dict(_row(st).get("bits") or {})
    assert bits.get("reviewed") is True, bits


# ============================================================ ② 没有签块
def test_b_without_the_block_a_self_authored_theorem_is_refused(tmp_path):
    """② 没有签块 ⇒ 自产 theorem 退回（同一条闸，只是这次它看得见手稿里没有签）。"""
    st = _ws(tmp_path)
    text = _manuscript(st, block=False)
    got = _register(st, text)
    assert got.get("ok") is not True, got
    # 没有签时 B 退在"自产 theorem 先按猜想注册"这一档（`must_start_as_conjecture`）——
    # 与"有签时收下"是同一条闸的两面；这里只钉"退掉了、一行都没写"。
    assert str(got.get("error") or "").strip(), got
    assert len(st.rows("statements")) == 0, st.rows("statements")


# ============================================================ ③ 签的是旧版
def test_c_a_block_for_another_body_is_not_accepted(tmp_path):
    """③ 签块盖的是另一版 ⇒ 不许借（sha 不符 = stale，不是签过）。"""
    st = _ws(tmp_path)
    text = _manuscript(st, body=PROOF + "改一个字")
    got = _register(st, text)
    assert got.get("ok") is not True, got
    assert len(st.rows("statements")) == 0, st.rows("statements")


# ============================================================ ④ 审过、没过
def test_d_a_rejected_block_is_not_a_signature(tmp_path):
    """④ 块写 `已签=false；判词=有毛病` ⇒ 不算签（审过、没过）。"""
    st = _ws(tmp_path)
    text = _manuscript(st, signed=False, verdict="有毛病")
    got = _register(st, text)
    assert got.get("ok") is not True, got
    assert len(st.rows("statements")) == 0, st.rows("statements")
