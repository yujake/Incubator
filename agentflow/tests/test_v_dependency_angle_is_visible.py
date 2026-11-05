# -*- coding: utf-8 -*-
"""V 的可见面必须有「依赖面」这一条审查角度。

调查报告：`temp/dep_probe/REPORT-dependency-surface.md`。改前 V 关于依赖只有两句，
且都不是"检查依赖面"：③ 逻辑里那一句只问「依赖有没有循环」，另有一句讲缺陷沿依赖边
上溯。于是「这一步该引谁、引了谁、正文点名的前置写没写进依赖段」根本不在审查角度里。

这一段是业主 2026-11-04 放权动禁改区（FC-27，类别 auth-audit）。本文件读的是
`agent_prompts.ROLE_BRIEFS["V"].policy` —— 它就是 `system_prompt()` 渲染进可见面的
同一份政策；不读 `specs/v.py` 的源码（注释里写着而可见面上没有，在这里必须读成红）。
"""
from __future__ import annotations

from agentflow import agent_prompts as AP

#: 新加的第六条角度（逐字；测试用它做"摘掉 ⇒ 红"的反真空）。
DEPENDENCY_ANGLE = (
    "⑥ **依赖面** —— 这一步引了什么？正文点了名的前置有没有写进依赖段？"
    "该引而没引的，指到第几步。"
)

#: 逐字针（同样的三格，拆开钉住"角度"本体、比对动作、与退回时指步号）。
NEEDLES: tuple[str, ...] = (
    "⑥ **依赖面**",
    "正文点了名的前置有没有写进依赖段",
    "该引而没引的，指到第几步",
)


def _v_policy() -> str:
    """V 的政策原文（渲染进可见面的那一份）。"""
    return "\n".join(str(x) for x in AP.ROLE_BRIEFS["V"].policy)


def test_v_visible_surface_carries_the_dependency_angle() -> None:
    """角度在、与另外五条同段，且"五条角度"那一句跟着改成六条（口径不漂）。"""
    text = _v_policy()
    missing = [n for n in NEEDLES if n not in text]
    assert not missing, f"V 的可见面缺依赖面这一条角度：{missing}"

    # 它必须是同一个「审查角度」段里的 ⑥，而不是另起一节的补充。
    items = [str(x) for x in AP.ROLE_BRIEFS["V"].policy]
    carriers = [i for i, body in enumerate(items) if DEPENDENCY_ANGLE in body]
    assert len(carriers) == 1, f"依赖面角度不在唯一一条政策里：{carriers}"
    body = items[carriers[0]]
    for sibling in ("**审查角度", "⑤ **台账一致**"):
        assert sibling in body, (
            f"依赖面角度没有与另外五条角度同段（缺 {sibling!r}）—— 它会被读成另起一节的补充")

    assert "六条角度" in text and "五条角度" not in text, (
        "角度从五条变成六条，但「沿下面五条角度」那一句没跟着改 —— 同一个岗位的两处读数打架")


def test_removing_the_dependency_angle_turns_the_same_criterion_red() -> None:
    """反真空：把这一句从可见面上摘掉 ⇒ 同一个尺子必须逐针报红。"""
    text = _v_policy()
    stripped = text.replace(DEPENDENCY_ANGLE, "")
    assert stripped != text, "夹具有一句对不上真身 ⇒ 这条反真空失去对象（先看措辞是否又改了）"

    missing = [n for n in NEEDLES if n not in stripped]
    assert missing == list(NEEDLES), (
        f"摘掉这一句之后三个针应当全部报红；实得 {missing}")
