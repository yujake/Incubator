# -*- coding: utf-8 -*-
"""F 读 V 的结论：只剩两态（业主 2026-10-30：「不应该有『看不出来』，『看不出错』就是没毛病」）。

## 要落成的口径（三句）

```text
· V 只会退回两种结论：成立（没找到缺陷）/ 有毛病（找到缺陷，指到步号与原句）
· F 读到「有毛病」时：按那条缺陷改稿/补步骤；读到「成立」= 这一格被审过、不再重交
· 不再有「三态」「看不出来」这一档；历史台账里若出现 `看不出来`，按兼容读当成
  「成立（没找到缺陷）」，并在文案里写明那是历史行
```

上一批（d839936b / 89e784a2）把 V 的产出面收成 `成立 / 有毛病`（历史值只作兼容读），
但 F 侧的文案还指着那个已经不存在的档：`specs/f.py` 的 policy（「V 报 `看不出来` 时
把它当成『这一格还没被签』」）与 `agent_skills._f_skills()` 的两份手册（「三态退回来的
活怎么接」／「『看不出来』是合法的三态之一」）。这一份把两处都收成两态。

## 三条判据（f1/f2 先红后绿；f3 是 f1 的负控）

| # | 它守什么 | 改前为什么红 |
|---|---|---|
| f1 | 渲染后的 F 提示词（`system_prompt("F")`，含技能索引）里没有旧档那句、也没有 `看不出来`；两态那一段逐字在 | policy 写着「报 `看不出来` 时把它当成『这一格还没被签』，别当通过」 |
| f2 | F 自己那份手册（`CATALOG["F"]`）同样只剩两态，并写清"历史行里的 `看不出来` 按成立读" | 两份手册各有一段三态 /「看不出来」那一档 |
| f3 | 负控：把那句经「渲染面」（`ROLE_BRIEFS["F"]`）临时拼回旧文案 ⇒ f1 的判据函数必须当场报 | —（f1 绿着时它证明判据量的是那句话，不是"文件里没这个词"） |

反真空各一条：f1 除了"旧档没了"还单独断言"两态那句在"（否则删掉整段也能让它变绿）；
f2 的 blob 逐条核过 slug/长度（不是空串）；f3 先断言探针真的改变了渲染文本。

零真模型调用，零网络。
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow import agent_skills as AL  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

#: 两态那一段（业主口径的逐字要求；F 侧与 V 侧用的是同一句，改了它两边一起红）。
TWO_STATES = ("V 只会退回两种结论：成立（没找到缺陷）/ 有毛病（找到缺陷，指到步号与原句）")

#: F 读到两态之后各做什么（两句都是要求的"口径"那一半，f1/f2 各核一次）。
REACT_ON_DEFECT = "按那条缺陷改稿/补步骤"
REACT_ON_CLEAN = "这一格被审过、不再重交"

#: 改前 `specs/f.py:114-116` 那一句（三行拼成一条 policy）。f3 拿它拼回渲染面 ——
#: 它就是"这一档还在"的最小载体，判据必须能点名它。
OLD_POLICY = ("过去。V 报 `有毛病` 时按它给的步号**补那一步**，不要重写整篇；"
              "报 `看不出来` 时把它当成「这一格还没被签」，别当通过 —— ")

#: "三态"被用来「列出 V 的结论」的几种形态（不是 `三态纪律` / `三态词表` / `三态：可销`
#: 那几族 —— 它们说的是"没查成"与主控/退役读数；也不是 `index_block` 末尾那句
#: "回执（… + 三态结论）由 B 带回" —— 那是 L 的形式化回执，另一根轴）。
#: 判据只认"把成立 / 有毛病 与第三个词排在一起"的行，或下面这几个旧说法本身。
OLD_TIER_WORDS = ("三态退回", "结论只有三个", "合法的三态之一", "这一格还没被签")

#: 手册里 `看不出来` 唯一允许的载体：它是「历史行」（只作兼容读）或一句否定式。
HISTORY_MARKERS = ("历史行", "历史台账", "不存在")


def _f_prompt() -> str:
    """渲染后的 F 提示词（F 每一趟真正读到的 system prompt，含技能索引摘要）。"""
    return AP.system_prompt("F", registry=build_registry().registry)


def _f_manual_blob() -> str:
    """F 自己那份手册的全部文本（`CATALOG["F"]`：slug / 标题 / 索引两格 / 正文）。"""
    parts: list[str] = []
    for skill in AL.CATALOG["F"]:
        parts.append(f"### {skill.slug}")
        for field in ("title", "summary", "when", "body"):
            parts.append(str(getattr(skill, field)))
    return "\n".join(parts)


def _line_lists_a_third_state(line: str) -> bool:
    """这一行是不是把 V 的结论排成了三态（成立 / 有毛病 / 第三个词）？

    只认"三态 + 那两个结论词同现"：`三态纪律`（没查到 / 没接线 / 被拒）、`三态词表`
    （没查成的几个码）、`三态：可销 ⇒ state=retired`（销号读数）与 L 的形式化回执
    （`三态结论`）都与 V 的结论无关，不许被这条判据连坐。
    """
    return "三态" in line and "成立" in line and "有毛病" in line


def _tier_line_problems(label: str, text: str, *, allow_history: bool) -> list[str]:
    """指向旧档的那些行（f1/f2 共用；`allow_history` 决定 `看不出来` 许不许当历史行出现）。"""
    bad: list[str] = []
    for line in text.splitlines():
        if _line_lists_a_third_state(line):
            bad.append(f"{label} 这一行还把 V 的结论排成三态：{line.strip()[:160]}")
        if "看不出来" in line:
            if allow_history and any(m in line for m in HISTORY_MARKERS):
                continue
            bad.append(f"{label} 这一行还指着『看不出来』那一档：{line.strip()[:160]}")
    return bad


def _f_prompt_problems(text: str) -> list[str]:
    """"渲染后的 F 提示词是不是只剩两态"的判据本体（f1 与 f3 共用）。

    三件事：① 两态那句在；② 旧档那几种说法不在；③ `看不出来` 一个字都不许有
    （F 的可见面上它已经没有任何合法位置 —— 历史兼容是台账读取侧的事，不是 F 的读法）。
    """
    bad: list[str] = []
    if TWO_STATES not in text:
        bad.append(f"没有写清 V 只会退回两态（成立 / 有毛病）：缺那一句 {TWO_STATES!r}")
    for phrase in OLD_TIER_WORDS:
        if phrase in text:
            bad.append(f"旧档那句还在：{phrase!r}")
    bad.extend(_tier_line_problems("F 提示词", text, allow_history=False))
    return bad


def _f_manual_problems(blob: str) -> list[str]:
    """"F 的手册是不是只剩两态、并且写清了历史行怎么读"的判据本体（f2）。"""
    bad: list[str] = []
    if TWO_STATES not in blob:
        bad.append(f"手册没写清 V 只会退回两态：缺那一句 {TWO_STATES!r}")
    for phrase in (REACT_ON_DEFECT, REACT_ON_CLEAN):
        if phrase not in blob:
            bad.append(f"手册没写清 F 读到两态之后做什么：缺 {phrase!r}")
    for phrase in OLD_TIER_WORDS:
        if phrase in blob:
            bad.append(f"手册里旧档那句还在：{phrase!r}")
    bad.extend(_tier_line_problems("F 手册", blob, allow_history=True))
    # 历史行的读法必须逐字写明（不是"删掉那一档"就算完 —— 台账里真的出现过那个值）
    carriers = [ln for ln in blob.splitlines()
                if "看不出来" in ln and "历史行" in ln and ("兼容读" in ln or "成立" in ln)]
    if not carriers:
        bad.append("手册没有写清『历史行里的 `看不出来` 按成立（没找到缺陷）读』"
                   "（要求同一行同时出现 看不出来 / 历史行 / 成立或兼容读）")
    return bad


# ------------------------------------------------------------------ f1

def test_f1_the_rendered_f_prompt_points_at_only_two_verdicts() -> None:
    """f1：F 的提示词里旧档那句没了，两态那一段逐字在。

    改前为什么红：`specs/f.py` 的 policy 让 F 在 V 报 `看不出来` 时"把它当成这一格还没被签"
    —— 那个档在 d839936b 之后已经不存在（模型回那一族措辞会被折成 `成立`）。
    """
    text = _f_prompt()
    # 反真空锚：这是真的渲染出来的整份提示词（不是空串 / 占位）
    assert len(text) > 5000, len(text)

    bad = _f_prompt_problems(text)
    assert bad == [], "F 的提示词还指着旧档：\n" + "\n".join(bad)

    # 正向那一半单独再断言一次（"旧档没了"可以是删掉整段的副作用）
    assert TWO_STATES in text, "F 的提示词没有两态那一段（删掉整段不算改成两态）"
    assert REACT_ON_DEFECT in text and REACT_ON_CLEAN in text, (
        "F 的提示词没有写清读到两态之后各做什么（有毛病 ⇒ 改稿/补步骤；成立 ⇒ 不再重交）")


# ------------------------------------------------------------------ f2

def test_f2_the_f_manual_reads_the_two_states_and_knows_the_legacy_row() -> None:
    """f2：F 自己那份手册同样只剩两态，并写清"历史行的 `看不出来` 按成立读"。

    改前为什么红：`交付-证明要能被别人复核` 里那一节叫「三态退回来的活怎么接」、
    正文写「V 的结论只有三个：成立 / 有毛病 / 看不出来」；`攻坚-一次一步并留中间态`
    的「卡住时」也写着「『看不出来』是合法的三态之一」。
    """
    own = AL.CATALOG["F"]
    assert len(own) >= 4, f"F 的手册只剩 {len(own)} 份 ⇒ 这不是 F 那一份目录（判据失去对象）"
    # F 这一趟真的读得到这几份（手册目录与 skills_for 不许分家）
    reachable = {s.slug for s in AL.skills_for("F")}
    assert {s.slug for s in own} <= reachable, (
        f"CATALOG['F'] 里有 skills_for('F') 读不到的：{sorted({s.slug for s in own} - reachable)}")

    blob = _f_manual_blob()
    # 反真空锚：四份手册的正文叠起来是几千字（不是空串 / 占位；改前实测 5705 字）
    assert len(blob) > 5000, len(blob)

    bad = _f_manual_problems(blob)
    assert bad == [], "F 的手册还指着旧档：\n" + "\n".join(bad)


# ------------------------------------------------------------------ f3

def test_f3_putting_the_old_sentence_back_makes_f1_red(monkeypatch) -> None:
    """f3：负控 —— 把那句经渲染面拼回旧文案 ⇒ f1 的判据函数必须当场报。

    打的是「渲染面」（`agent_prompts.ROLE_BRIEFS["F"]`，`system_prompt` 真正读的那张表），
    不是文件里的字面量：旧句与两态那句同时在，于是"变红"只可能来自旧句本身，
    不可能来自"两态那句被顺手删了"。

    这一条与 f1 合起来才成立：f1 证明"现在干净"，f3 证明"脏的时候它会响"
    —— 只有 f1 的话，判据恒返回空列表也能绿。
    """
    before = _f_prompt()
    baseline = _f_prompt_problems(before)
    brief = AP.ROLE_BRIEFS["F"]
    patched = dataclasses.replace(brief, policy=tuple(brief.policy) + (OLD_POLICY,))
    monkeypatch.setattr(AP, "ROLE_BRIEFS", {**AP.ROLE_BRIEFS, "F": patched})
    try:
        after = _f_prompt()
        assert after != before, "探针没改变渲染面 ⇒ 这一条负控是空转（判据没有对象）"
        assert OLD_POLICY in after, "旧句没进渲染面 ⇒ 负控打不中"

        bad = _f_prompt_problems(after)
        assert bad, "把旧句拼回渲染面，判据却一声不吭 ⇒ f1 量到的不是那句话"
        assert any("看不出来" in x for x in bad), (
            "判据报红了，但没点名『看不出来』那一档 ⇒ 它不是量那句话的：" + " | ".join(bad))
        # 基线干净时（f1 绿着），"变红"必须只由拼回去的旧句引起 —— 否则这一条只证明了
        # "判据会因别的原因红"。改前基线不干净（f1 本来就红），这一半不适用。
        if not baseline:
            assert not [x for x in bad if "看不出来" not in x], (
                "拼回旧句之后多报了别的东西 ⇒ 红的原因不止那句话：" + " | ".join(bad))
    finally:
        monkeypatch.undo()
        assert _f_prompt() == before, "负控之后渲染面没恢复 ⇒ 后面的用例会被污染"
