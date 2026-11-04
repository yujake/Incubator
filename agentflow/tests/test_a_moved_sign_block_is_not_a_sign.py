# -*- coding: utf-8 -*-
"""判据：签块被搬到另一份稿上 ⇒ 它不给那份稿作证（第 9 格 `手稿号` 的读侧一半）。

## 为什么会有这一条

第 9 格 `手稿号` 是 2026-11-02 加的，`manuscript_sign_reading` 也如实给出三态
（`resolved` / `unmatched` / `legacy`），`test_sign_block_ninth_cell_is_the_manuscript_id`
逐字写着 `unmatched` **不许**读成"签过了"。但 `manuscript_sign_standing`（F 的交付读数、
B 的收录认签、V 的"已经签过"短接、秘书的升档依据都走它）当时**不看**这一格：
只认正文 sha 与连续次数。于是"同一份正文的签块从 000000 的稿搬进 000001 的稿"照样
读成 signed —— 第 9 格写了、读了，却没有一处拿它拦。

## 判据（每条都两向）

| # | 造什么 | 期望 |
|---|---|---|
| a | 块与所在稿同号（`f-proof-000000.md`） | `signed`（正控） |
| b | 同一块搬到 `f-proof-000001.md` | **不是** `signed`；`why` 点名手稿号对不上 |
| c | 不给稿路径 | 仍 `signed`（三态：判不了就不判，旧调用点行为逐字不变） |
| d | 旧 8 格块搬到别的稿 | 仍 `signed`（`legacy` 是当时真的签过，不许读成没签） |
| e | 反真空：把搬块闸打桩成恒放行 | b 的那一块回到 `signed` —— b 量的是这道闸 |
| f | F 的交付读数（`agent_f.vsign`）拿搬过的块 | 不是「已签」——调用点真的把稿路径递进去了 |

判据只读块与路径，不写盘、不起模型。
"""
from __future__ import annotations

import pathlib

from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import vsign as FVS

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n2. 按定义即一致连续。"
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              f"{PROOF}\n\n"
              "## 依赖\n\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
SHA = VR.proof_sha(PROOF)
REL = "reports/f-proof-000000.md"
OTHER = "reports/f-proof-000001.md"


def _block(*, manuscript_id: str = "000000", legacy: bool = False) -> str:
    head = (f"{VS.SIGN_MARK}已签=true；判词=成立；连续=3/3；正文sha={SHA}；"
            "时间=2026-11-04T00:00:00+08:00；签名者=secretary:F；"
            f"台账=reports/f-proof-000000.md#V签；命题号=未在册")
    if legacy:
        return head
    return f"{head}；手稿号={manuscript_id}"


def _text(*, manuscript_id: str = "000000", legacy: bool = False) -> str:
    return MANUSCRIPT.replace(
        "- 计划：0000 · 子目标：s1\n",
        "- 计划：0000 · 子目标：s1\n"
        + _block(manuscript_id=manuscript_id, legacy=legacy) + "\n")


def _write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ====================================================================== a 正控
def test_a_the_block_of_this_manuscript_is_signed() -> None:
    """块与所在稿同号 ⇒ signed（修法不误伤同一份稿上的真签）。"""
    standing = VS.manuscript_sign_standing(_text(), proof_sha=SHA, manuscript_path=REL)
    assert standing["identity_state"] == "resolved", standing
    assert standing["state"] == "signed", standing


# ====================================================================== b 搬块
def test_b_a_block_moved_to_another_manuscript_is_not_a_sign() -> None:
    """同一块搬到 `f-proof-000001.md` ⇒ 不是 signed；why 点名手稿号。"""
    text = _text()  # 块里的手稿号是 000000
    standing = VS.manuscript_sign_standing(text, proof_sha=SHA, manuscript_path=OTHER)
    assert standing["identity_state"] == "unmatched", standing
    assert standing["state"] != "signed", standing
    assert "手稿号" in str(standing["why"]), standing


# ====================================================================== c 三态
def test_c_without_the_path_the_old_callers_are_unchanged() -> None:
    """不给稿路径 ⇒ 判不了，仍 signed（旧调用点逐字不变；不拿"判不了"当"搬过"）。"""
    standing = VS.manuscript_sign_standing(_text(), proof_sha=SHA)
    assert standing["identity_state"] == "unmatched", standing
    assert standing["state"] == "signed", standing


# ====================================================================== d legacy
def test_d_a_legacy_eight_cell_block_still_counts_on_any_manuscript() -> None:
    """旧 8 格块没有手稿号可比 ⇒ `legacy` 仍 signed（不许读成没签）。"""
    standing = VS.manuscript_sign_standing(
        _text(legacy=True), proof_sha=SHA, manuscript_path=OTHER)
    assert standing["identity_state"] == "legacy", standing
    assert standing["state"] == "signed", standing


# ====================================================================== e 反真空
def test_e_without_the_identity_gate_the_moved_block_reads_signed(monkeypatch) -> None:
    """反真空：把搬块闸打桩成恒放行 ⇒ b 那一块回到 signed（b 量的是这道闸）。"""
    monkeypatch.setattr(VS, "_block_identity_conflicts", lambda _reading: False)
    standing = VS.manuscript_sign_standing(_text(), proof_sha=SHA, manuscript_path=OTHER)
    assert standing["state"] == "signed", (
        "打桩之后仍然是 unsigned ⇒ 拒信不来自搬块闸（这一条量错了东西）："
        f"{standing}")


# ====================================================================== f 调用点
def test_f_f_delivery_reading_passes_the_path_and_refuses_a_moved_block(tmp_path) -> None:
    """F 的交付读数把稿路径递给 standing：搬过的块不给「已签」。"""
    _write(tmp_path, OTHER, _text())
    moved = FVS.delivery_reading(tmp_path, proof_text=PROOF, manuscript_paths=(OTHER,))
    assert moved["state"] != FVS.STATE_SIGNED, moved
    assert moved["delivered"] is False, moved

    _write(tmp_path, REL, _text())
    ok = FVS.delivery_reading(tmp_path, proof_text=PROOF, manuscript_paths=(REL,))
    assert ok["state"] == FVS.STATE_SIGNED, ok
    assert ok["channel"] == FVS.CHANNEL_MANUSCRIPT, ok
