# -*- coding: utf-8 -*-
"""判据 ⑥–⑧：V 的两份提示词指向"穷举型证据会审"这一档，唤起者是 F / E / B。

## 改前的方向错在哪（业主 2026-10-23 晚）

`verifications.cold_start_prompt` 的"第 3 位强度"那一段写着：

    evidence_kind="proof" 只由 verify.check_formal 的检查器输出产生；
    要 proof 级证据，得请 M 派 E 走 method="formal" 那条路。

两句话都是假话（穷举证据也能拿 proof，而签字的人正是 V），而且它给 V 一个明确的错误
方向：把 E 交来的穷举证明读成"不归我审"，或者反过来去要一份自然语言证明。真身是
`exhaustionreport.review` 的七项机械会审（不进模型）。

职责行与技能 when 也只写"F 唤起"：E 派 V 会审穷举证据这条边（`E -> V`）已经落了，
B 在登记 proof 之前也要 V 那一签，所以唤起者是 F / E / B。

| # | 判据 | 改前为什么红 |
|---|---|---|
| ⑥ | `system_prompt("V")` 与 `cold_start_prompt` 都含穷举会审那一档，且不再含"只由 check_formal" | 两处都没有那一档；cold 里那句是假话 |
| ⑦ | 唤起者写成 F / E / B（三条断言：职责行 / 技能 when / 渲染后的提示词） | 两处只写 F |
| ⑧ | 反真空：把 cold_start 那段删掉 ⇒ ⑥ 必红 | 判据自身要能红 |

一个模型调用都不发（提示词是纯函数）。
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow import agent_skills as SK  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.specs import v as V_SPEC  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

#: 这一档的名字（两处提示词里必须逐字出现）。
SECTION = "穷举型证据会审"
#: 七项机械检查里两处都该点到的六项（第 ⑦ 项在 system 那一份里写作「证明栏末尾那一格」：
#: 那一岗的提示词刻意不写「形式化」这三个字 —— 讲形式化就必须点着 L，而开关关着时
#: L 与 `formal.` 在别人的提示词里必须 0 次，判据见 `tests/test_lean_switch_points_at_l.py`）。
CHECKS: tuple[str, ...] = ("程序地址", "报告", "搜索空间", "对称性", "边界", "穷尽")
#: 冷启动那一份要额外点到的（它才是 V 的真实入口，形式化那一类在这里交代）。
CHECKS_COLD: tuple[str, ...] = CHECKS + ("形式化那一格",)
#: 改前那句假话的两个片段（"不再含"钉的就是它们）。
STALE_SENTENCES: tuple[str, ...] = (
    '`evidence_kind="proof"` 只由 `verify.check_formal`',
    "只由 `verify.check_formal` 的检查器输出产生",
)
#: 唤起者（职责行 / 技能 when / 渲染后的提示词三处都要这一串）。
SUMMONERS = "F / E / B"


def _prompt_problems(system_text: str, cold_text: str) -> list[str]:
    """⑥ 的正文：两处提示词各自的读数（空清单 = 两处都指对了）。"""
    bad: list[str] = []
    for name, text, checks in (('system_prompt("V")', system_text, CHECKS),
                               ("cold_start_prompt", cold_text, CHECKS_COLD)):
        if SECTION not in text:
            bad.append(f"{name} 里没有『{SECTION}』那一档（V 会把穷举证据读成不归它审）")
        missing = [word for word in checks if word not in text]
        if missing:
            bad.append(f"{name} 的会审那一档缺这几项：{missing}")
        for sentence in STALE_SENTENCES:
            if sentence in text:
                bad.append(f"{name} 里还留着改前那句假话：{sentence!r}（proof 不只由它产生）")
        if "两类" not in text:
            bad.append(f"{name} 里没有「两类 proof 并列」这件事（穷举那一类会被漏掉）")
    # 「看不出来 = 缺材料」与三格落点只要求在冷启动那一份（那才是 V 的真实入口）
    if "缺材料" not in cold_text:
        bad.append("cold_start_prompt 没有写清这一档的『看不出来』是缺材料，不是没查成")
    for cell in ("exhaustion_review", "checks", "missing"):
        if cell not in cold_text:
            bad.append(f"cold_start_prompt 没有写清结论落点 `{cell}`")
    return bad


def _system_prompt_v() -> str:
    return AP.system_prompt("V", registry=build_registry().registry)


def _cold_start() -> str:
    return VR.cold_start_prompt("对任意正整数 n，R(3,4)=9。",
                                "程序：code/enum.py\n程序设计：按 4-子集编码枚举\n"
                                "穷举论证：全部 2^36 个染色，无一遗漏")


# ------------------------------------------------------------------ ⑥ 两处提示词

def test_6_both_prompts_point_at_the_exhaustion_review() -> None:
    """⑥ 渲染后的两处提示词都含穷举会审那一档，且不再含"只由 check_formal"。"""
    system_text = _system_prompt_v()
    cold_text = _cold_start()
    # 反真空的锚：两处都得是真的渲染出来的长文本（不是空串/占位）
    assert len(system_text) > 5000 and len(cold_text) > 500, (len(system_text), len(cold_text))
    bad = _prompt_problems(system_text, cold_text)
    assert bad == [], "\n".join(bad)
    # 这一档的名字与"七项"在两个文本里各自逐字出现（上面那个 CHECKS 判据只查词，
    # 这里再钉一次"七项"这个数字，免得有人把某几项删掉之后 CHECKS 仍然全中）
    assert "七项" in system_text and "七项" in cold_text


def test_6b_the_two_kinds_of_proof_are_side_by_side() -> None:
    """⑥ 的另一半：两类 proof 并列写在提示词里。

    冷启动那一份（V 的真实入口）把两条路都点名：Lean 形式化（检查器原话）与穷举（E 的
    程序 + ②③ + 这一签）。system 那一份只说"机器核过的那一类"与"穷举这一类"并列 ——
    它刻意不写「形式化」三个字，理由见 `tests/test_lean_switch_points_at_l.py`
    （关着时 L 与 `formal.` 在别人的提示词里必须 0 次）。
    """
    cold = _cold_start()
    assert "Lean 形式化" in cold and "formal.check_formal" in cold, cold[:400]
    assert "穷举" in cold
    system_text = _system_prompt_v()
    assert "两类 proof 并列" in system_text, system_text[:400]
    assert "穷举" in system_text
    for sentence in STALE_SENTENCES:
        assert sentence not in system_text and sentence not in cold


# ------------------------------------------------------------------ ⑦ 唤起者

def test_7_the_summoners_are_f_e_and_b() -> None:
    """⑦ 唤起者写成 F / E / B：职责行、技能 when、渲染后的提示词三处。"""
    # ① 职责行（`specs/v.py` 的真身：`brief.boundary` 的第一条就是渲染出来那句）
    boundary = V_SPEC.SPEC.brief.boundary[0]
    assert SUMMONERS in boundary, boundary
    # ② 技能 when
    skill = next(s for s in SK._v_skills() if s.slug.startswith("复核"))
    assert SUMMONERS in skill.when, skill.when
    # ③ 渲染后的提示词
    assert SUMMONERS in _system_prompt_v()


# ------------------------------------------------------------------ ⑧ 反真空

def test_8_removing_the_cold_start_section_makes_6_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑧ 反真空：把 cold_start 里那一档删掉 ⇒ ⑥ 必红（判据压的正是那段话）。"""
    real = VR.cold_start_prompt

    def _without_the_section(*a, **kw) -> str:
        text = real(*a, **kw)
        return re.sub(r"\n## " + SECTION + r".*?(?=\n## |\Z)", "\n", text, flags=re.S)

    stubbed = _without_the_section("命题", "证明")
    assert SECTION not in stubbed, "打桩没生效：那一段还在（这条反真空就没有对照）"
    system_text = _system_prompt_v()
    assert _prompt_problems(system_text, stubbed) != []
    with pytest.raises(AssertionError):
        assert _prompt_problems(system_text, stubbed) == []
    # 正控：不删的时候它是绿的（上面那条红不是"恒红"）
    monkeypatch.setattr(VR, "cold_start_prompt", real, raising=True)
    assert _prompt_problems(system_text, _cold_start()) == []
