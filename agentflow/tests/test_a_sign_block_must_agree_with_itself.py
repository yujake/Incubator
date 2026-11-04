# -*- coding: utf-8 -*-
"""判据：签块自己说「已签=true」而判词是「有毛病」⇒ 它不是签（业主 2026-11-03 甲）。

## 为什么会走到这里

`vsigns.render_manuscript_sign` 的两个格子是分开写的：`已签` 是一个布尔、`判词`
是 V 的结论。生产写口从 2026-11-03 起不再写负判块（`write_manuscript_sign(signed=False)`
那一档只在读侧兼容里存在），但盘上仍然可能有：

- 旧块（`已签=false；判词=有毛病`，正常读成 rejected）；
- 自相矛盾的块（`已签=true；判词=有毛病`）——例如块被手工改过、或别的写者把两个
  格子拼错了。

`manuscript_sign_standing` 改前只读 `已签` 那一格：`已签=true` + `判词=有毛病`
⇒ `state="signed"`。那等于把一条负判读成了签 —— 而业主逐字的口径是
「负判不是签」（`draft/178`，写侧当时修的是"不写块"，读侧这一半没跟上）。

## 判据（每条都两向）

| # | 造什么 | 期望 |
|---|---|---|
| a | `已签=true；判词=成立` | `state=signed`（正控，修法不误伤） |
| b | `已签=true；判词=有毛病` | 不是 `signed`（`rejected`），`why` 点名判词 |
| c | 反真空：把判词闸打桩成"恒放行" | b 的那一块回到 `signed` —— 证明 b 量的是这道闸 |

`manuscript_sign_reading` 仍然如实报两格（`signed=True`、`verdict="有毛病"`）：
本判据改的是结论那一层，不是把块读成"没有块"。
"""
from __future__ import annotations

from agentflow import verifications as VR
from agentflow import vsigns as VS

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


def _block(*, signed: str, verdict: str, streak: str = "3/3") -> str:
    return (f"{VS.SIGN_MARK}已签={signed}；判词={verdict}；连续={streak}；"
            f"正文sha={SHA}；时间=2026-11-04T00:00:00+08:00；签名者=secretary:F；"
            f"台账=reports/{REL}#V签；命题号=未在册；手稿号=000000")


def _manuscript(*, signed: str, verdict: str) -> str:
    return MANUSCRIPT.replace(
        "- 计划：0000 · 子目标：s1\n",
        "- 计划：0000 · 子目标：s1\n" + _block(signed=signed, verdict=verdict) + "\n")


# ====================================================================== a 正控
def test_a_a_positive_block_is_signed() -> None:
    """`已签=true；判词=成立` ⇒ signed（修法不误伤真签）。"""
    standing = VS.manuscript_sign_standing(
        _manuscript(signed="true", verdict="成立"), proof_sha=SHA, manuscript_path=REL)
    assert standing["state"] == "signed", standing


# ====================================================================== b 负判
def test_b_a_block_that_says_both_signed_and_defective_is_not_a_sign() -> None:
    """`已签=true；判词=有毛病` ⇒ rejected：负判不是签（两个格子矛盾时按负判读）。"""
    text = _manuscript(signed="true", verdict="有毛病")
    reading = VS.manuscript_sign_reading(text, manuscript_path=REL)
    # 读侧如实报两格（本判据不是"把块读成没有块"）。
    assert reading["signed"] is True and reading["verdict"] == "有毛病", reading

    standing = VS.manuscript_sign_standing(text, proof_sha=SHA, manuscript_path=REL)
    assert standing["state"] != "signed", standing
    assert standing["state"] == "rejected", standing
    assert "有毛病" in str(standing["why"]), standing


# ====================================================================== c 反真空
def test_c_without_the_verdict_gate_the_contradictory_block_reads_signed(monkeypatch) -> None:
    """反真空：把判词闸打桩成恒放行 ⇒ b 那一块回到 signed（b 量的是这道闸）。"""
    monkeypatch.setattr(VS, "_block_verdict_allows_sign", lambda _reading: True)
    standing = VS.manuscript_sign_standing(
        _manuscript(signed="true", verdict="有毛病"), proof_sha=SHA, manuscript_path=REL)
    assert standing["state"] == "signed", (
        "打桩之后仍然是 rejected ⇒ 拒信不来自判词闸（这一条量错了东西）："
        f"{standing}")


# ====================================================================== d 旧块
def test_d_a_legacy_negative_block_is_still_rejected() -> None:
    """旧写法 `已签=false；判词=有毛病` 照旧 rejected（本修法不改变那一档）。"""
    standing = VS.manuscript_sign_standing(
        _manuscript(signed="false", verdict="有毛病"), proof_sha=SHA, manuscript_path=REL)
    assert standing["state"] == "rejected", standing
