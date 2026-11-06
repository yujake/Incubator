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

#: 作废那一档的两档口径（业主 2026-11-06 裁定 ①）：每一档是一组必须同时出现的针。
#: `revoke` 档的正当性是权限（直接父 / 主控 M），`revoke=False` 旧档才是「叫不醒」那道
#: 证明 —— 两档都在描述里，模型才知道工具面走的是哪一档、旧档凭什么收窄过。
#: 只收在描述里的字面针（不是从源码里抠的）：模型照做的正是这一份 `summary`。
ARMS: dict[str, tuple[str, ...]] = {
    "revoke 档（权限决定）": ("权限", "直接父", "主控 M"),
    "revoke=False 旧档（叫不醒才轮得到）": ("revoke=False", "叫不醒"),
}

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


def _arm_problems(summary: str, *, where: str) -> list[str]:
    """两档口径各有哪几针不在（空表 = 两档都写清了）。

    分开数两档，是为了让读数能回答"缺的是权限那一档还是叫不醒那一档" —— 只报
    "缺叫不醒"会把 2026-11-06 那一次口径变更读成一句漏写。
    """
    problems: list[str] = []
    for arm, needles in ARMS.items():
        missing = [needle for needle in needles if needle not in summary]
        if missing:
            problems.append(f"{where} 没说清 `{arm}` 那一档：缺 {missing}"
                            "（权限与叫不醒是两档，不是同一句话的两种写法）")
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
    """作废那一档 2026-11-06 起分两档：`revoke` 档由权限定，`revoke=False` 旧档才要"叫不醒"。

    2026-10-29 那一版的口径是「静默不够，叫不醒才轮得到作废」—— 它只对旧档成立。
    业主 2026-11-06 裁定 ① 之后工具面走的是 `revoke` 档：**收件人的直接父代理、或
    主控 M** 有权撤，`expects=work` 也收 —— 正当性是**权限**，"叫不醒"不再是必要
    条件。所以这里把两件独立的事分开钉：

    - block 项的出路仍然是 `conductor.wake_blocked`（撤销撤的是「不再需要做」的项，
      不是唤醒）—— 这一句一个字没变，仍是 `_pointing_problems` 那一条；
    - 描述里**两档都得看得到**：`revoke` 档 = 权限（直接父 / 主控 M），`revoke=False`
      旧档 = 「收件人叫不醒」那道证明（收窄过的旧口径仍然有效，只是不再是唯一正当性）。

    两向反真空都实测过（删任一段 ⇒ 本用例必红，读数见这一批的提交信息）：
    删「`revoke` 档由权限决定」那一段 ⇒ `权限` / `直接父` / `主控 M` 三针红；
    删「`revoke=False` 旧档才要叫不醒」那一段 ⇒ `revoke=False` / `叫不醒` 两针红。
    """
    problems: list[str] = []
    summary = _summary("conductor.void_items")
    problems += _pointing_problems(summary, where="conductor.void_items 的描述")
    problems += _arm_problems(summary, where="conductor.void_items 的描述")
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
    """负控：把旧文喂进去，同一套函数必须报出来（否则它只是在测"文件里没这句话"）。

    两档口径各喂一次"只写了一半"的样本：只有权限那一档、只有叫不醒那一档 ——
    两向都必须报出来，否则 `_arm_problems` 只是在测"这两个词在不在文件里"。
    """
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
    # 两档口径：写全两档 ⇒ 过；只写一半（任意一半）⇒ 必须报。
    both = ("权限：收件人的直接父代理或主控 M 有权撤；"
            "`revoke=False` 旧档只作废叫不醒者。")
    if _arm_problems(both, where="正控样本"):
        problems.append("写全两档的正控样本没过检查 —— 两档的针与这次的措辞不一致")
    only_authority = "权限：收件人的直接父代理或主控 M 有权撤。"
    if not _arm_problems(only_authority, where="负控样本"):
        problems.append("只写权限那一档（没写 revoke=False / 叫不醒）却没被报出来")
    only_deaf = "`revoke=False` 旧档只作废叫不醒者。"
    if not _arm_problems(only_deaf, where="负控样本"):
        problems.append("只写叫不醒那一档（没写权限 / 直接父 / 主控 M）却没被报出来")
    assert problems == [], problems
