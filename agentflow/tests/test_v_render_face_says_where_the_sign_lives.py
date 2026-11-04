# -*- coding: utf-8 -*-
"""判据 P0-2：V 的渲染面对「签在哪」只剩一种说法，且三态措辞退役。

## 现场（`draft/172` §一 R29 / R33 / R34 / R46，§三 P0-2）

同一份 V 可见面上三句话互斥：

- `specs/v.py:153`「签不签由你的秘书判定并落盘」（对）；
- `verifications.py:958`「② 穷举 —— 凭据是 E 写的那份程序 + ②③，签字的人是你」（错）；
- `agent_skills.py:1522`「你签的字落在 `verifications/<命题号>.jsonl` 那一行上」（错）；
- 而 `tools/verify_tools.py:997` 的工具说明仍写「三态结论」（V 从 2026-11-01 起只产两态）。

## 现行设计（三处必须同一口径；2026-11-04 业主裁定 ① 之后的拆分）

- 颁发那一步就写 `out/vsigns/<被审正文的 sha>.json`（一稿一签；正文改一个字，那一签
  就作废）—— 写它的是 `vsigns.issue`，留在 V 这一侧；
- 落签（手稿签块 + 台账位）由收方秘书做（`vsigns.land`，`by=` 只认
  `secretary:F|B|E`）；
- V 的产出是判定（成立 / 有毛病）与逐条缺陷；它只颁发，不落块、不翻第 3 位；
- 三态措辞退役：只剩两态，「看不出错」读成成立。

## 三条判据（每条都带反真空）

| # | 对象 | 改前为什么红 |
|---|---|---|
| s1 | 冷启动提示词（V 每次审阅真正读到的入口） | 写着「签字的人是你」，且一个字都没说签落在哪 |
| s2 | V 的技能手册正文（`skills/V/` 那几份） | 写着「你签的字落在台账那一行上」 |
| s3 | `verify.verify_proof` 的声明面（`summary` ＋ `returns`） | 写着「三态结论」 |

反真空：每条判据都把"改前那一句"塞回同一份文本再喂给同一个判据函数 —— 必须当场报出来
（否则它只是"文本很长"）。零模型调用、零网络。
"""
from __future__ import annotations

from agentflow import agent_skills as AS
from agentflow import verifications as VR
from agentflow.tools import build_registry

PROOF = "1. 由定义直接得到。\n2. 由第 1 步得到结论。"
STATEMENT = "对任意正整数 n，R(3,4)=9。"


def _cold() -> str:
    """V 的真实审阅入口（`verifications.cold_start_prompt`）。"""
    return VR.cold_start_prompt(STATEMENT, PROOF, readonly_facts="- 夹具")


def _v_skills() -> str:
    """V 的手册正文（`skills/V/` 落盘的那几份的正本）。"""
    return "\n".join(s.body for s in AS.skills_for("V"))


def _tool_face() -> str:
    """`verify.verify_proof` 给模型看的那段文字（`summary` ＋ `returns`）。"""
    spec = build_registry().registry.get("verify.verify_proof")
    assert spec is not None, "工具面里没有 verify.verify_proof ⇒ 这条判据失去对象"
    return "\n".join([str(spec.summary or ""), str(spec.returns or "")])


def _sign_home_problems(text: str, *, where: str) -> list[str]:
    """「签在哪」这一条的判据本体（s1/s2 共用）。

    两半：① 改前那两句错话一个字都不许留；② 必须说清签落在 `out/vsigns/`（一稿一签）
    且发签的是秘书 —— `where` 只说读的是哪一份面，进报错串。
    """
    bad: list[str] = []
    for old, why in (("签字的人是你", "改前那句「签字的人是你」还在（签不在 V 手上）"),
                     ("你签的字落在", "改前那句「你签的字落在台账」还在（签是侧文件，不是台账行）")):
        if old in text:
            bad.append(f"{where}：{why}")
    if "out/vsigns" not in text:
        bad.append(f"{where}：没有说清签落在 `out/vsigns/<被审正文的 sha>.json`")
    if "一稿一签" not in text:
        bad.append(f"{where}：没有说清「一稿一签」（正文改一个字那一签就作废）")
    if "秘书" not in text:
        bad.append(f"{where}：没有说清发签的是秘书")
    return bad


def test_s1_the_cold_start_says_the_sign_is_the_secretarys_file(tmp_path) -> None:
    """s1：冷启动不再说「签字的人是你」，并点明签在 `out/vsigns/`、由秘书发。"""
    text = _cold()
    assert len(text) > 500, len(text)          # 反真空①：真的渲染出来的那一份

    bad = _sign_home_problems(text, where="冷启动提示词")
    assert bad == [], "\n".join(bad)

    # 反真空②：把改前那一句塞回去 ⇒ 必须当场报
    probe = text + "\n（补一句改前口径）② 穷举 —— 签字的人是你"
    hit = _sign_home_problems(probe, where="冷启动提示词")
    assert hit and any("签字的人是你" in x for x in hit), hit


def test_s2_the_v_manual_puts_the_sign_in_out_vsigns() -> None:
    """s2：V 的手册里「你签的字落在台账」退役，改成"判定落台账 / 签落 out/vsigns"。"""
    text = _v_skills()
    assert len(text) > 3000, len(text)         # 反真空①：真的那一份手册正文

    bad = _sign_home_problems(text, where="V 的手册")
    assert bad == [], "\n".join(bad)
    assert "vsigns.issue" in text, "手册里那一条「签文件在**颁发**那一步就写」被顺手删掉了"
    assert "收方秘书" in text, "手册里没有说清「落签（手稿块 + 台账位）由收方秘书做」"

    probe = text + "\n（补一句改前口径）你签的字落在 `verifications/<命题号>.jsonl` 那一行上。"
    hit = _sign_home_problems(probe, where="V 的手册")
    assert hit and any("你签的字落在" in x for x in hit), hit


def _two_state_problems(text: str) -> list[str]:
    """「V 的结论只有两态」这一条的判据本体（s3）。

    声明面是按键与用途写的，没有给"第三态"留位置：`三态` 一次都不许有（与
    `test_v_verdict_is_two_states.py` 的 s5 对 `看不出来` 用的是同一把尺子），
    而两态那两个词必须点得到名。
    """
    bad: list[str] = []
    if "三态" in text:
        bad.append("声明面还写着「三态」（V 从 2026-11-01 起只产两态）")
    if "两态" not in text:
        bad.append("声明面没有写「两态」")
    for word in ("成立", "有毛病"):
        if word not in text:
            bad.append(f"声明面没有点名两态里的 {word!r}")
    return bad


def test_s3_the_tool_declaration_says_two_states() -> None:
    """s3：`verify.verify_proof` 的声明面不再写「三态」，写两态（成立 / 有毛病）。"""
    text = _tool_face()
    assert len(text) > 500, len(text)          # 反真空①

    bad = _two_state_problems(text)
    assert bad == [], "\n".join(bad)

    # 反真空②：把「两态」换回「三态」⇒ 必须当场报（且报的是那一条）
    probe = text.replace("两态", "三态")
    assert probe != text, "声明面里没有「两态」那两个字 ⇒ 探针打不中（判据是假绿）"
    hit = _two_state_problems(probe)
    assert hit and any("三态" in x for x in hit), hit
