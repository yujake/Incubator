# -*- coding: utf-8 -*-
"""判据（乙-15）：B 的提前闸 `_v_signature_for` 也必须把稿路径递进签块读数。

搬块（`reports/f-proof-000001.md` 里放着 `手稿号=000000` 的块）在最终 `bits_after_sign`
会被拒；但 B 的提前闸如果不递 `manuscript_path`，它会先把这一块读成 `signed`，于是
拒信码/读数说错。这里钉住：
| # | 造什么 | 期望 |
|---|---|---|
| a | 搬块 + 给了所在稿路径 | 不是 signed |
| b | 反真空：同一块、不给路径 | 回到 signed（证明 a 量的是 `manuscript_path=` 这一格） |
"""
from __future__ import annotations

import pathlib

from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n2. 按定义即一致连续。"
REL = "reports/f-proof-000001.md"


def _text() -> str:
    sha = VR.text_sha(PROOF)
    block = (f"{VS.SIGN_MARK}已签=true；判词=成立；连续=3/3；正文sha={sha}；"
             "时间=2026-11-04T00:00:00+08:00；签名者=secretary:F；"
             f"台账={REL}#V签；命题号=未在册；手稿号=000000")
    return ("# F 的证明手稿（被搬过的块）\n\n"
            f"{block}\n\n"
            f"## 命题\n\n{FULL}\n\n## 证明\n\n{PROOF}\n\n## 依赖\n\n"
            "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")


def _agent(tmp_path: pathlib.Path) -> AgentB:
    st = Store(tmp_path / "ws")
    st.init()
    return AgentB(st, extractor=None, extract_text=None)


def test_a_moved_block_is_not_signed_through_the_early_gate(tmp_path):
    b = _agent(tmp_path)
    got = b._v_signature_for(statement_full=FULL, proof_text=PROOF,
                             manuscript_text=_text(), manuscript_path=REL)
    assert got.get("signed") is False, got


def test_b_without_the_path_it_falls_back_to_signed(tmp_path):
    b = _agent(tmp_path)
    got = b._v_signature_for(statement_full=FULL, proof_text=PROOF,
                             manuscript_text=_text(), manuscript_path="")
    assert got.get("signed") is True, got
