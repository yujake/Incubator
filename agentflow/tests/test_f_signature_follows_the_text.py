# -*- coding: utf-8 -*-
"""R07 的两端：F 的证明天生带签（原样入库存认签）＋ 签跟着正文走（改一字要重送）。

## 业主 2026-11-01 的澄清（逐字）

> 「一句说"F 的证明天生带签"，一句说"改一字签就作废"。这两句都是我的口径。若 B 想完善
> F 提交的证明再入库，重写后需重新获得 V 签」

所以这不是两句互相否认的话，而是一条时间线的两端：

- F 送审时拿到的那一签，盖在**F 那一版正文**上 ⇒ B **原样入库**时认它，不要重复要求签；
- 签跟着正文走（一稿一签）：B 若完善 / 重写 / 改动正文任何一个字，**改后的正文必须重新
  送审拿新签**；原来那份签对改后的正文**对不上**（不是"被撤销"）；
- 落地判据是现成的那条 sha 比对：`verifications.proof_review_gap` 的
  `sha_matches` / `state`（一致 ⇒ 认签；不一致 ⇒ `state="stale"` ⇒ `proof_review` 不成立、待复核）。

## 三条判据

| # | 它守什么 | 改前为什么红 |
|---|---|---|
| r1 | B 的提示词里两句都在：`天生带 V 签字` + `重新送审` / `签跟着正文走` | 改前只有前半句，读起来像"F 的证明永远不用签" |
| r2 | 现场㈠：签盖在现行正文上（连续 3 次成立）⇒ 原样入库**认得签**（写入不拒、gap.ok 为真） | 改前改后都该绿（护栏：认签这一端不许被改坏） |
| r3 | 现场㈡：正文改过一个字 ⇒ **不认原签**：`gap.ok=False`、`state="stale"`、`sha_matches=False`、理由说"对不上/待复核"（不许说成"签无效"）；同时钉住 2026-10-22 的口径 —— **"正文改过了"本身不是拒收理由** | 改前改后都该绿（它钉的是行为；r1 钉文案） |
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP     # noqa: E402
from agentflow import verifications as VR     # noqa: E402
from agentflow.store import Store             # noqa: E402
from agentflow.tools import build_registry    # noqa: E402

from test_fake_proof_review import _PROOF, _row, _sign, _write  # noqa: E402


def test_b_prompt_has_both_ends_of_the_timeline() -> None:
    text = AP.system_prompt("B", registry=build_registry().registry)
    assert "天生带 V 签字" in text, (
        "B 的提示词里没有「F 产的证明天生带 V 签字」那一句 —— 原样入库时它会白要求一次签")
    assert "签跟着正文走" in text or "重新送审" in text, (
        "B 的提示词里没有「签跟着正文走 / 改过的正文要重新送审」那一半")
    assert "对不上" in text, (
        "改过正文那一档要说成「对不上」（不是「被撤销」）：签没被撤，只是不盖这一版")


def test_a_signature_on_the_current_text_is_honoured(tmp_path: pathlib.Path) -> None:
    """现场㈠：签盖在现行正文上 ⇒ 原样入库认签（写入不拒）。"""
    store = Store(tmp_path / "ws")
    store.init()
    _sign(store, "000000", _PROOF)
    row = _row("000000", proof_text=_PROOF)
    _write(store, row)  # 不抛 = 闸放行
    gap = VR.proof_review_gap(store.root, row)
    assert gap["ok"] is True and gap["sha_matches"] is True, gap


def test_editing_one_character_makes_the_old_signature_not_match(tmp_path: pathlib.Path) -> None:
    """现场㈡：改一个字 ⇒ 原签对不上（stale），但"改过了"本身不是拒收理由。"""
    store = Store(tmp_path / "ws")
    store.init()
    _sign(store, "000000", _PROOF)
    edited = _PROOF.replace("直接", "几乎直接")
    assert edited != _PROOF
    row = _row("000000", proof_text=edited)
    gap = VR.proof_review_gap(store.root, row)
    assert gap["ok"] is False, gap
    assert gap["state"] == "stale", gap
    assert gap["sha_matches"] is False, gap
    assert "对不上" in str(gap["why"]) or "待复核" in str(gap["why"]), gap["why"]
    assert "无效" not in str(gap["why"]), gap["why"]
    # 2026-10-22 的口径：写入期闸只拒 rejected / 一次都没签；stale 不是拒收理由。
    _write(store, row)
