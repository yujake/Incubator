# -*- coding: utf-8 -*-
"""状态报告里「产物畸形」那一格的接线与措辞（MALFORM 路，2026-11-21）。

## 为什么单独一个模块

这一格是 MALFORM 路接进 `statusreport.collect` 的：判据本体在
:mod:`agentflow.wellformed`（一处判据），报告这一侧只做两件事 —— 取一次全量检查的
读数、把它渲染成人读的一行。两件事都不属于状态报告那四节，却让 `statusreport.py`
为它们多次跨过 800 行软基线（业主口径：不许抬体量基线）。

把它们搬到这里是纯搬运：措辞逐个字节相同，读数面拿到的键与含义一个字都没变。

## 它不是闸门

业主口径（2026-11-21）：「畸形要看得见，而不是再拦一道」。所以本模块只读、零模型
调用、不改盘，也不产生任何 blocker —— 畸形被看见之后改不改、什么时候改，由人定。

## 三态纪律

`unchecked` 绝不折成 `ok`：没查成那一支印的是「那是『没读成』，不是『没有畸形』」。
`info` 的 Finding 不进"要处置"那个数（它是"有读数、且已有解释"的那一档，例如手稿
登记之后才落的签块让 ARTIFACTS 的 sha 落后一格）；把它算进去会让每一份签过的稿都
被读成畸形。
"""

from __future__ import annotations

from typing import Any, Mapping


def wellformed_reading(root: str | Any) -> dict[str, Any]:
    """取一次全量畸形检查的读数（`wellformed.workspace_reading` 的唯一转发口）。

    为什么接在这里而不是另开一屏：`agentflow status` 与收尾补落的那份状态报告是
    "随时看一眼现在什么情况"的既有读数面，畸形属于同一屏该看见的东西。

    惰性 import：`statusreport` 是"随时看一眼"的轻入口，而 `wellformed` 会拉
    schema / litread / closing 一串；只为装配这一格就在模块导入期付那笔代价不值得
    （与 `statusreport.collect` 里 `closing` 那一处同一种做法）。
    """
    from . import wellformed as WF

    return WF.workspace_reading(root)


def wellformed_line(reading: Mapping[str, Any]) -> str:
    """产物畸形那一行（读数只读、不进闸门）。

    三态都在这一行里分开：没查成 / 没有畸形 / 有畸形。`info` 的 Finding 不进
    "要处置"那个数 —— 它是"有读数、且已有解释"（例如手稿登记之后才落的签块让
    ARTIFACTS 的 sha 落后一格），把它算进去会让每一份签过的稿都读成畸形。
    """
    if not reading.get("checked"):
        return ("- 产物畸形：没查成（" + str(reading.get("reason") or "读不到")
                + "）—— 那是「没读成」，不是「没有畸形」")
    by_sev = reading.get("by_severity") or {}
    actionable = int(by_sev.get("error") or 0) + int(by_sev.get("warning") or 0)
    info = int(by_sev.get("info") or 0)
    if not actionable:
        return (f"- 产物畸形：{actionable} 条要处置"
                + (f"（另有 {info} 条 info 读数，例如已解释的签块落后）" if info else "")
                + "；判据 `wellformed`（`python scripts/check_wellformed.py`）")
    examples = "；".join(
        f"`{one.get('where')}`（{one.get('code')}）"
        for one in (reading.get("examples") or [])[:3])
    unchecked = list(reading.get("unchecked") or [])
    return (f"- 产物畸形：{actionable} 条要处置"
            f"（error {by_sev.get('error', 0)} / warning {by_sev.get('warning', 0)}；"
            f"另有 {info} 条 info）"
            + (f"；没查成 {len(unchecked)} 类：{'、'.join(unchecked)}" if unchecked else "")
            + (f"；例如 {examples}" if examples else "")
            + " —— 这条读数不构成闸门，处置由人定")
