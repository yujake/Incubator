# -*- coding: utf-8 -*-
"""判据 P0-3：B 的 `proof_review` 门槛必须说成 `signed`，不许说成「最近一签成立」。

## 现场（`draft/172` §一 R05 / R67，§三 P0-3）

`specs/b.py:319-321` 教 B：「`proof_text` 非空、且 V 在 `verifications/<命题号>.jsonl` 里
最近那一签是「成立」（`proof_sha256` 与现行正文相符）⇒ 它的 `evidence_kind` 就是
`proof_review`」。而写入期的判据 `verifications.proof_review_gap` 只认 `signed`：

- `review_standing` 的 `signed` 要 `streak >= SIGN_STREAK_NEED`（连续 3 次「成立」）、
  引用核实全 `consistent` / `weaker`、且 findings 里没有未解决的 error；
- `holding`（签过、判成立、盖的也是现行这一版，但连续次数没到）明确不算
  （`verifications.py` 里 `holding` 那一格的定义逐字：「它与 `unsigned`（一次都没签）
  必须分开说」）。

于是 B 照提示词做会被拒（`proof_review_without_evidence`，整笔事务一行不写）——
提示词教的比闸放的宽，模型就会一次次撞同一道闸。

## 三条判据

| # | 它守什么 | 改前为什么红 |
|---|---|---|
| s1 | 渲染后的 B 提示词里，门槛句写的是 `signed`（连续 3 次干净成立 + 引用核实通过） | 只说「最近那一签是成立」，一个门槛都没说 |
| s2 | 同一条必须点名 `holding` / 单次成立不够，并点名 gap 的三个条件 | 一个字都没提 |
| s3 | 行为钉：造 holding（只落 1 次「成立」）⇒ `proof_review_gap` 非空、写入期 gate 拒收；反真空：连落 3 次 ⇒ 同一行收得进去 | —（这一条改前改后都绿；它钉的是"文案说的门槛就是闸用的门槛"） |

s1/s2 自带反真空：把改前那一句喂进同一个判据函数 ⇒ 必须当场报出来（不是恒绿）。
零模型调用、零网络：s3 的签是 `record_verification` 直接落的（不经模型），写入走真事务。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import agent_prompts as AP
from agentflow import verifications as VR
from agentflow.store import Store
from agentflow.tools import build_registry

#: 与 `test_fake_proof_review` 同一套真夹具（同一个门槛的判据不该有两套造行方式）。
from test_fake_proof_review import _PROOF, _row, _sign, _write  # noqa: E402

#: 改前那一句（审计 R05 逐字摘的形态）。
OLD_SENTENCE = ("最近那一签**是「成立」（`proof_sha256` 与现行正文相符）⇒ 它的 "
                "`evidence_kind` **就是** `proof_review`")


def _b_prompt() -> str:
    """渲染后的 B 提示词（policy + 工具面 + 技能索引；`specs/b.py` 是 policy 的唯一真身）。"""
    return AP.system_prompt("B", registry=build_registry().registry)


def _threshold_problems(text: str) -> list[str]:
    """门槛句的判据本体（s1/s2 共用；反真空也喂它）。

    两件事各判一次：
    ① 门槛词：`signed` 必须在、`holding` 必须被点名为"不够"，且要写出连续 3 次
       与引用核实这两道闸 —— 只说「签过」等于把 `holding` 放进门；
    ② 旧话不再：改前那一句（"最近那一签是成立 ⇒ 就是 proof_review"）一个字都不许留。
    """
    bad: list[str] = []
    if OLD_SENTENCE in text:
        bad.append("还留着改前那一句（最近一签成立 ⇒ 就是 proof_review）："
                   f"{OLD_SENTENCE}")
    for needle, why in (
            ("signed", "没有点名 signed（写入期闸只认它）"),
            ("holding", "没有点名 holding（签过但连续次数没到的那一档）"),
            ("连续 3 次", "没有写出「连续 3 次」（SIGN_STREAK_NEED）"),
            ("引用核实", "没有写出引用核实这一道闸"),
            ("`proof_text` 非空", "没有写出 gap 的第 1 个条件（proof_text 非空）"),
            ("proof_sha256", "没有写出 gap 的第 3 个条件（proof_sha256 与现行正文相符）"),
            ("未解决的 error", "没有写出 gap 的第 2 个条件里的「没有未解决的 error」"),
            ("单次", "没有说清单次「成立」不够"),
    ):
        if needle not in text:
            bad.append(f"{why}（缺 {needle!r}）")
    return bad


def test_s1_the_threshold_speaks_of_signed_and_retires_the_old_sentence() -> None:
    """s1+s2：B 的提示词里门槛句写的是 `signed`、点名 holding 不够、并列出 gap 三条件。"""
    text = _b_prompt()
    assert len(text) > 20_000, len(text)       # 反真空①：这是真渲染出来的那一份
    assert "proof_review" in text

    bad = _threshold_problems(text)
    assert bad == [], "B 的 proof_review 门槛还没说成 signed：\n" + "\n".join(bad)

    # 反真空②：把改前那一句塞回去 ⇒ 必须当场报（判据不是恒绿）
    probe = text + "\n（补一句改前口径）" + OLD_SENTENCE
    hit = _threshold_problems(probe)
    assert hit and any("改前那一句" in x for x in hit), hit


def test_s3_holding_is_not_enough_and_the_gate_says_so(tmp_path: pathlib.Path) -> None:
    """s3 行为钉：holding（1 次成立）⇒ gap 非空、写入期 gate 不升档；3 次才收。

    这一条把"文案"与"闸"钉在同一件事上：提示词说"holding 不算"，闸就必须也不收 ——
    两边有一条松了，这条都会红。
    """
    ws = Store(tmp_path / "ws")
    ws.init()
    _sign(ws, "000000", times=1)               # holding：签过、判成立、连续次数没到

    holding = VR.proof_review_gap(ws.root, _row())
    assert holding["checked"] is True, holding          # 查过了（不是"没查成"）
    assert holding["ok"] is False, holding
    assert holding["state"] == "holding", holding
    assert "连续" in str(holding.get("why") or "") or "次数" in str(
        holding.get("why") or ""), holding

    gaps = VR.proof_review_gaps(ws.root, [_row()])
    assert [g["state"] for g in gaps] == ["holding"], gaps

    with pytest.raises(ValueError) as exc:
        _write(ws, _row())
    assert "proof_review_without_evidence" in str(exc.value), str(exc.value)
    assert ws.rows("statements") == [], "gate 说拒收，却还是写了一行"

    # 反真空：补齐到连续 3 次 ⇒ 同一行收得进去（"拒"只能来自连续次数，不是别的原因）
    _sign(ws, "000000", times=VR.SIGN_STREAK_NEED - 1)
    signed = VR.proof_review_gap(ws.root, _row())
    assert signed["ok"] is True and signed["state"] == "signed", signed
    _write(ws, _row())
    assert [str(r.get("stmt_id")) for r in ws.rows("statements")] == ["000000"]
    assert VR.proof_review_gap(ws.root, ws.rows("statements")[0])["verification_id"] == str(
        signed["verification_id"])
