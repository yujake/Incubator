# -*- coding: utf-8 -*-
"""判据：C 的提示词只教它真做得到的事（三处，外加污染面怎么查）。

## 改前实测的三处"教做不到的事"

1. `specs/c.py` 的 policy 教"报一个数（度数 / 割点 / 结构洞 / 绕行）"，而全仓
   没有 articulation 读数（没有这个工具、没有这个动作，`graph.*` 也没有割点）——
   教了也报不出来；
2. 同一处 boundary 写"知识表（文献 / 概念 / 关系）"，而 `concepts` 表已经不存在
   （S1r 并表：概念行住 `statements`，`kind="concept"`）—— 点名一张不存在的表；
3. 同一处把"污染面"当读数报，却没教怎么查；业主 2026-11-04 裁定：污染面指的就
   是"依赖一个错误命题的其他命题号"，从依赖面查，C 完全做得到 —— 所以要教它自己
   用 `table.list` / `table.get` 读 `dependencies` 行反向走多跳，而不是等框架给读数。

## 判据（两面）

a. 正面：这些"做不到的教法"都不在了；污染面那一段把"从依赖面反向多跳、用 `table.*`
   读 `dependencies` 的 `source_stmt_id` / `used_by`"教清楚，并明说框架不给这个读数；
b. 反面（反真空）：把旧句逐处回灌 / 把污染面那段抽掉，检查函数必须点名报出来 ——
   否则"提示词里没有 X"与"检查函数永远返回空"长得一模一样。
"""
from __future__ import annotations

from agentflow import agent_prompts as AP


def _c_text() -> str:
    """C 的边界 + 政策（提示词里常驻渲染的那两栏，`stance` 不算）。"""
    brief = AP.ROLE_BRIEFS["C"]
    return "\n".join(brief.boundary) + "\n" + "\n".join(brief.policy)


def _problems(text: str) -> list[str]:
    """这份 C 提示词里"教了做不到的事 / 没教怎么做"的地方（空列表 = 干净）。"""
    out: list[str] = []
    if "割点" in text:
        out.append("还在教「割点」：全仓没有 articulation 读数，C 报不出这个数")
    if "文献 / 概念 / 关系" in text:
        out.append("还把 `concepts` 当表名：`concepts` 已退役（概念行住 `statements`，kind=concept）")
    if "kind=concept" not in text:
        out.append("没有说清概念行的真身（`statements` 里的 `kind=concept`）")
    for needle, why in (
        ("污染面不是框架给你的读数", "没明说污染面不是框架给的（会把 C 该算的活推给框架）"),
        ("依赖面", "没点名从依赖面查污染面"),
        ("从依赖面反向", "没点名从依赖面反向走（业主 2026-11-04 的原话）"),
        ("多跳", "没点名要反向走多跳（直接 + 间接）"),
        ("table.list", "没点名用哪件工具读依赖行"),
        ("dependencies", "没点名读哪张表"),
        ("source_stmt_id", "没教从依赖行上取被依赖的那条命题"),
        ("used_by", "没教从依赖行上取用到它的那一方"),
        ("stmt:", "没教只取 `stmt:` 前缀的命题依赖（doc/relation/experiment 不是命题）"),
        ("#pN", "没教去掉 `#pN` 证明号尾巴（同一命题的第 2 份依赖会算两次）"),
        ("空集", "没教空集也是诚实读数（不是'工具坏了'，也不是'没有问题'）"),
    ):
        if needle not in text:
            out.append(f"污染面那一段缺「{needle}」：{why}")
    return out


def test_c_prompt_does_not_teach_the_impossible() -> None:
    """a：三处都按裁定改过了；污染面那段是真教法，不是一句"给个读数"。"""
    bad = _problems(_c_text())
    assert not bad, "C 的提示词还在教做不到的事 / 没把污染面教清：\n  " + "\n  ".join(bad)


def test_the_checker_is_not_vacuous() -> None:
    """b：逐处回灌旧句 / 抽掉污染面那段 ⇒ 检查函数必须点名（不是永远返回空）。"""
    text = _c_text()

    # ① 回灌"割点"
    doctored = text.replace("度数 / 结构洞 / 绕行", "度数 / 割点 / 结构洞 / 绕行")
    assert doctored != text, "夹具前提：新文案里有「度数 / 结构洞 / 绕行」可回灌"
    hit = _problems(doctored)
    assert any("割点" in one for one in hit), hit

    # ② 回灌旧的概念表文案
    doctored = text.replace("文献 / 命题 / 关系", "文献 / 概念 / 关系")
    assert doctored != text, "夹具前提：新文案里有「文献 / 命题 / 关系」可回灌"
    hit = _problems(doctored)
    assert any("concepts" in one for one in hit), hit

    # ③ 抽掉"不是框架给的"那句 ⇒ 必须点名（把 C 该算的活推给框架）
    cut = text.replace("污染面不是框架给你的读数", "")
    assert cut != text, "夹具前提：污染面那一段在提示词里"
    hit = _problems(cut)
    assert any("污染面不是框架给的" in one for one in hit), hit

    # ③' 把"依赖面"抹掉（教法退化成"报个读数"）⇒ 必须点名依赖面那两条
    cut = text.replace("依赖面", "图")
    hit = _problems(cut)
    assert any("没点名从依赖面" in one for one in hit), hit

    # ④ 空串 ⇒ 全部事实都报缺（检查函数不是对任何串都返回空）
    assert len(_problems("")) >= 12, _problems("")


# ---------------------------------------------------------------- 手册三句（同一件）


def _c_manual_text() -> str:
    """C 的三条 skill 正文（`agent_skills.CATALOG["C"]`，真跑时进提示词的那一份）。"""
    from agentflow import agent_skills as AS

    return "\n\n".join(skill.body for skill in AS.CATALOG["C"])


def _manual_problems(text: str) -> list[str]:
    """C 的手册里"教了做不到的事"的地方（空列表 = 干净）。"""
    out: list[str] = []
    if "产出登记口只有 `C.handle`" in text:
        out.append("还说 `C.handle` 是产出登记口：它是动作、不在 C 的工具面上")
    if "产出登记口只有 `analysis.register_report`" not in text:
        out.append("没有点名真登记口 `analysis.register_report`")
    if "`manuscripts.read` 同理" in text:
        out.append("还说 `manuscripts.read` 能截段：它只有 `id`，没有 start_line / max_lines")
    if "`manuscripts.read` **只有 `id`**" not in text:
        out.append("没有把 `manuscripts.read` 的实参说清（只有 `id`）")
    if "`path_shape.join_segments" in text and "没有工具面入口" not in text:
        out.append("还把 `path_shape.join_segments` 写成可调用的读数（没有工具面入口）")
    if "没有工具面入口" not in text:
        out.append("没有说清 `join_segments` 没有工具面入口")
    return out


def test_c_manual_does_not_teach_the_impossible() -> None:
    """a（手册三句）：登记口 / `manuscripts.read` 的参数 / `join_segments` 的入口都改成真话。"""
    bad = _manual_problems(_c_manual_text())
    assert not bad, "C 的手册还在教做不到的事：\n  " + "\n  ".join(bad)


def test_the_manual_checker_is_not_vacuous() -> None:
    """b（手册三句）：逐处回灌旧句 ⇒ 检查函数必须点名。"""
    text = _c_manual_text()

    hit = _manual_problems(text.replace(
        "产出登记口只有 `analysis.register_report`", "产出登记口只有 `C.handle`"))
    assert any("C.handle" in one for one in hit), hit

    hit = _manual_problems(text.replace(
        "`manuscripts.read` **只有 `id`**", "`manuscripts.read` 同理"))
    assert any("manuscripts.read" in one for one in hit), hit

    hit = _manual_problems(text.replace("没有工具面入口", ""))
    assert any("join_segments" in one or "没有工具面入口" in one for one in hit), hit

    assert len(_manual_problems("")) >= 3, _manual_problems("")
