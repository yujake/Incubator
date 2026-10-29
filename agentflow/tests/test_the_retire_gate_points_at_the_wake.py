# -*- coding: utf-8 -*-
"""旧口径清理（F）：block 项的"出口"只许指到唤醒，不许再指到 ack / 作废。

## 这一份钉住的是什么

2026-10-29 之前，工具面与能力层的三处措辞把 block 项的出路指向了走不通的门：

```text
旧：销号前置 ... 先把那些项逐条处置掉再来销            （conductor.retire_child 描述）
旧：先用 `conductor.ack` 把已办的那些确认掉             （板项闸的拒信）
旧：—— 先用 `conductor.ack` 把它们收口                 （级联销号的拒信）
旧：`block` 今天没有写入者，它的四条出边一律 back        （ITEM_MOVES 的注释）
```

前三条错在两个地方，两个都实测过（temp 里的探针读数，见那次提交的信息）：
- 收件人自己对一条 block 板项 ack ⇒ 状态机拒（`state_error`："已经到过 'block'
  （不许倒退或重复迁移）"）—— ack 这条路对 block 行根本走不通；
- 父替收件人 ack ⇒ `not_yours`（只有收件人自己能确认）—— 所以"让父去 ack"是
  一条双重走不通的建议。
第四条是事实错误：`stopctl.block_remaining_tasks` 从 2026-10-13 起就在写 block
（status 与名下板项一起翻），而 2026-10-29 起 `wake_blocked` 又用直写把它翻回 queued。

## 判据的形态（为什么读描述而不读源码）

模型照做的是描述（`ToolSpec.summary` 会进 function-calling 的 description，
`tools/base.py` 的 `returns` 那一格同理）。所以这三条断言读的是真实装配出来的
`ToolSpec.summary`、以及 `Conductor` 的源码文本（那一格是给读代码的人看的口径），
而不是"文件里搜得到"。

## 反真空（两条）

1. 同一套检查函数喂进旧文必须报出来 —— 否则它只是"字符串恰好不在了"；
2. `ITEM_MOVES` 的那一格事实必须仍然成立（`("block","done")` 是 `back`）——
   判据守的是"状态机没有出边、外面的路是唤醒"，不是"改了几句漂亮话"。
"""

from __future__ import annotations

import inspect
import re
from typing import Iterable

from agentflow.conductor import Conductor
from agentflow.tools import conductor_tools as CT

#: 三条描述里必须点到的那件工具（指向唤醒，而不是 ack / 作废）。
WAKE = "conductor.wake_blocked"

#: 旧文（每一条都必须已经不在了）。判据自己拿它们做负控，证明检查函数有分辨率。
OLD_PHRASES: tuple[str, ...] = (
    "先把那些项逐条处置掉再来销",
    "先用 `conductor.ack` 把已办的那些确认掉",
    "先用 `conductor.ack` 把它们收口",
    "`block` 今天没有写入者",
)


def _summary(tool: str) -> str:
    """某个工具真实装配出来的描述（不是从源码里抠出来的那一份）。"""
    for fn, _deps in CT._TOOL_FUNCTIONS:  # noqa: SLF001 —— 判据要的是"装配面那一份声明"
        spec = getattr(fn, "__tool_spec__", None)
        if spec is not None and str(spec.name) == tool:
            return str(spec.summary)
    raise AssertionError(f"工具的装配面上没有 {tool} —— 这一格没查成（不是'没有问题'）")


def _source_problems(text: str, *, where: str) -> list[str]:
    """一套检查函数：某段文本里"还指着旧路"的地方（空表 = 干净）。"""
    problems: list[str] = []
    for old in OLD_PHRASES:
        if old in text:
            problems.append(f"{where} 里还留着旧口径：{old!r}")
    return problems


def _pointing_problems(summary: str, *, where: str) -> list[str]:
    """这一段的"出路"是不是指到了唤醒那一条（而不是 ack / 作废）。"""
    problems = _source_problems(summary, where=where)
    if WAKE not in summary:
        problems.append(f"{where} 没有点到 {WAKE} —— block 项的出路在那一处，"
                        "指到 ack 或作废都是走不通的门")
    return problems


def test_the_retire_gate_points_at_the_wake_not_at_an_ack() -> None:
    """销号那三道门的措辞：block 档先唤醒，ack 是收件人的动作。"""
    problems: list[str] = []
    summary = _summary("conductor.retire_child")
    problems += _pointing_problems(summary, where="conductor.retire_child 的描述")
    problems += _source_problems(inspect.getsource(CT.conductor_retire_child),
                                 where="conductor_retire_child 的实现")
    assert problems == [], problems


def test_the_void_gate_says_only_the_deaf_ones_are_voided() -> None:
    """作废那一档 2026-10-29 之后收窄成"叫不醒"，措辞不许再写"静默/退役"就够。"""
    problems: list[str] = []
    summary = _summary("conductor.void_items")
    problems += _pointing_problems(summary, where="conductor.void_items 的描述")
    for needle in ("叫不醒", "静默"):
        if needle not in summary:
            problems.append(f"conductor.void_items 的描述里没有说清 {needle!r} 那一档"
                            "（收窄之后的口径：静默不够，叫不醒才轮得到作废）")
    problems += _source_problems(inspect.getsource(Conductor.void_items),
                                 where="Conductor.void_items 的实现")
    assert problems == [], problems


def test_the_ack_tool_warns_that_block_rows_need_a_wake_first() -> None:
    """`conductor.ack` 自己要说清 block 例外（否则模型会一直试到 state_error）。"""
    problems: list[str] = []
    summary = _summary("conductor.ack")
    problems += _source_problems(summary, where="conductor.ack 的描述")
    for needle in ("block", WAKE):
        if needle not in summary:
            problems.append(f"conductor.ack 的描述里没有点到 {needle!r}"
                            "（block 行先唤醒才 ack 得动，这一句是模型唯一的提示）")
    assert problems == [], problems


def test_the_state_machine_still_has_no_edge_out_of_block() -> None:
    """事实那一半：`("block", "done")` 仍然是 `back`，而注释不再说"没有写入者"。

    为什么这一条与措辞分开：措辞可以改得漂亮，但"block 出不去"是状态机的事实 ——
    唤醒之所以必须是直写（`wake_blocked`），靠的正是这一格。
    """
    problems: list[str] = []
    if Conductor.ITEM_MOVES.get(("block", "done")) != Conductor.ITEM_MOVE_BACK:
        problems.append("状态机里 (block, done) 不再是 back —— 那条'先唤醒才 ack 得动'"
                        "的口径就过期了，重新核一遍再改措辞")
    source = inspect.getsource(Conductor)
    problems += _source_problems(source, where="Conductor 的源码")
    if "wake_blocked" not in source:
        problems.append("Conductor 的源码里没有出现 wake_blocked —— 这一格的注释漏了"
                        "唯一那条把 block 翻回去的路")
    assert problems == [], problems


def test_the_check_functions_can_actually_go_red() -> None:
    """负控：把旧文喂进去，同一套函数必须报出来（否则它只是在测"文件里没这句话"）。"""
    problems: list[str] = []
    for old in OLD_PHRASES:
        if not _source_problems(f"前一句。{old}。后一句", where="负控样本"):
            problems.append(f"旧文 {old!r} 没有被检查函数抓到 —— 这条判据是橡皮图章")
    if not _pointing_problems("把那些项逐条处置掉再来销", where="负控样本"):
        problems.append("一段既没有 wake_blocked、又留着旧指路的文本没被报出来")
    # 正控：新文必须过
    if _pointing_problems(f"block 那一档先由 {WAKE} 唤醒（翻回 queued）。",
                          where="正控样本"):
        problems.append("新文自己没过检查 —— 检查函数与这次的措辞不一致")
    assert problems == [], problems
