# -*- coding: utf-8 -*-
"""判据：B 的 `proof_manuscript` 收路径；号已在册时，交稿那一笔先把攻坚稿转正再认签。

## 真机形态（`projects/paper-rewrite-big`）

① 先按猜想登记拿到号（签另算）；② V 在那份 `notes/F-conj000000-proof.md` 上签过；
③ F 把签过的稿交回 B（`proof_manuscript=notes/…`，与 V 的召唤参数同一格）。

第 ③ 笔必须在认签之前把它转成 `reports/f-proof-<号>.md`：签块的第 9 格 `手稿号`
按稿路径现算，`notes/…` 算不出号（`vsigns.manuscript_id_of` 返回空）⇒ B 的签块闸
判 `manuscript_id_missing`，那一签永远认不上。改前还有更前面的一刀：这一格只当
正文，路径字符串被当成一份 20 字节的"稿"，`## 依赖` 一个字都读不出。

判据本体只有一处（`agentflow.agent_f.manuscript.promote_manuscript`）；这一份钉的是
"B 在什么时刻调它、调完从哪读正文"。模块本身另有一份判据
（`tests/test_notes_manuscript_is_promoted_to_f_proof.py`）。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

NOTES_REL = "notes/F-conj000000-proof.md"
FULL = "设 d = 1、σ 有界 Borel 可测、两端极限存在且不等；则 N_σ ∩ L^p(R) 在 L^p(R) 中稠密。"
PROOF = ("1. 对 c < d、λ > 0 取 f_λ := [σ(λ(x−c)) − σ(λ(x−d))]/(L+ − L−) ∈ N_σ。\n"
         "2. f_λ 逐点收敛到 1_{(c,d)}，三个区域分别估计 ⇒ L^p 收敛。\n"
         "3. 紧支阶梯函数在 L^p(R) 稠密 ⇒ 闭包是 L^p(R)。")
DEP_TABLE = (
    "## 依赖\n\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n"
)


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _draft() -> str:
    text = (
        "# F 的证明手稿：conj:000000 攻坚（P1）\n\n"
        "- 命题号：stmt:（还没落号）\n"
        "- 计划：000000 · 子目标：s1\n\n"
        "## 命题\n\n"
        f"{FULL}\n\n"
        "## 证明\n\n"
        f"{PROOF}\n\n"
        + DEP_TABLE
    )
    return DS.mark_washed(text, actor="secretary-F")


def _sign(st: Store, rel: str) -> None:
    """V 在 notes 草稿上签过：三转「成立」落 pending 台账，再把签块盖上。

    2026-11-05 晚：签块必须有一个盘上读得出来的独立台账背书（`sign_ledger_backing`），
    手写一个 `#v-…` 的假锚点现在不算签。所以这里先走真写口 `record_pending_sign`
    （未在册那一档的落点），再用它给出的 ledger 盖块。
    """
    path = pathlib.Path(st.root) / rel
    text = path.read_text(encoding="utf-8")
    body = VS.manuscript_proof_body(text)
    row: dict = {}
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        row = VR.record_pending_sign(
            st.root, proof_text=body,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", object_path=rel)
    ledger = (f"verifications/pending/{row['proof_sha256']}.jsonl"
              f"#{row['verification_id']}")
    stamped = VS.stamp_manuscript_sign(
        text, proof_sha=VR.proof_sha(body),
        streak=VR.SIGN_STREAK_NEED, need=VR.SIGN_STREAK_NEED,
        verdict="成立", at="2026-11-04T15:00:00+08:00",
        ledger=ledger, statement_id="",
        manuscript_id=VS.manuscript_id_of(rel))
    path.write_text(stamped, encoding="utf-8")


def _block(st: Store, rel: str) -> dict:
    return VS.manuscript_sign_reading((pathlib.Path(st.root) / rel).read_text(encoding="utf-8"),
                                      manuscript_path=rel)


def test_b_b_registration_with_a_notes_path_promotes_at_the_same_time(tmp_path):
    """b：号已在册 ⇒ 交稿那一笔先转正（签块跟着搬、第 9 格按号重算），再认签。"""
    st = _ws(tmp_path)
    b = AgentB(st, extractor=None, extract_text=None)
    first = b.register_statement(
        statement_full=FULL, statement_text=FULL, kind="conjecture",
        label="探针命题", origin="own_result", evidence_kind="heuristic",
        quote_verified=None, quote_reason="夹具：自产命题，先拿号",
        line_range={"label": NOTES_REL})
    assert first.get("ok") is True, first
    sid = str(first.get("stmt_id") or "")
    assert sid, first

    path = pathlib.Path(st.root) / NOTES_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_draft(), encoding="utf-8")
    _sign(st, NOTES_REL)

    got = b.register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=PROOF,
        # 与真机同一格：F 的召唤参数里写的是 `proof_manuscript=notes/…`（路径，不是正文）。
        proof_manuscript=NOTES_REL, kind="conjecture", label="探针命题",
        origin="own_result", evidence_kind="heuristic",
        quote_verified=None, quote_reason="夹具：自产证明，没有第二份文本可比对",
        line_range={"label": NOTES_REL})

    assert got.get("ok") is True, got
    assert str(got.get("stmt_id") or "") == sid, got
    promotion = dict(got.get("promoted_manuscript") or {})
    assert promotion.get("promoted") is True, got
    assert promotion.get("path") == f"reports/f-proof-{sid}.md", promotion

    final_rel = f"reports/f-proof-{sid}.md"
    assert (pathlib.Path(st.root) / final_rel).is_file(), "登记成功却没有正式稿"
    block = _block(st, final_rel)
    assert block.get("signed") is True, block
    assert block.get("manuscript_id") == sid, block
    assert dict(got.get("v_sign") or {}).get("applied") is True, got.get("v_sign")
