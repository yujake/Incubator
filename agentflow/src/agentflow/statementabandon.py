# -*- coding: utf-8 -*-
"""「放弃原命题」的标记：`quote_reason` 里那一条 `abandoned@<ISO8601>@<理由>`。

业主 2026-11-01 逐字裁定：

> 「每个命题和证明的产出最终必须以V签收尾，拿不到V签就得一直改，或者放弃原命题」

于是"已登记的命题"只许落在两处：「有 V 签」，或「被明确放弃（带理由与时间）」。
"明确"这个词在盘上要有载体，否则 `status="abandoned"` 只是换了一个字面量：
一条被标成放弃、却读不出为什么、也不知道什么时候放弃的命题，与"悬着"没有区别
（读的人既没法复核，也没法回答"这件事是几时被放下的"）。

## 为什么标记住在 `quote_reason`，而不是新加两列

同一张表的 `pending_definition`（`draft/93·续` D12 甲）已经用同一套手法把
"为什么空着、谁来补"写进 `quote_reason` 的受控标记（`concept:pending_search` /
`concept:self_authored`，唯一出处是 `migrate_concepts`），由 `schema.Statement.validate`
逐条核。这里照抄那一条纪律：不新增列（新增列就是改磁盘契约，属 FC-27 的
schema 迁移，能不做就不做），标记的写侧（`abandon_marker`）与读侧
（`parse_abandon`）只此一份实现，`schema` 与 `closing` 都从这里取 ——
两处各写一份正则，"什么算明确放弃"就会在两个出口长出两种答案。

## 形状与三态

`abandoned@2026-11-01T21:10:00+08:00@证明第 5 步补不出来，改不动了`

- 时间必须是 `datetime.fromisoformat` 认得的 ISO8601（带不带时区都行，带更好）；
- 理由非空；理由里允许再出现 `@`（只切前两刀），也允许中文与换行；
- `parse_abandon` 的三态：`checked=True` = 是一条可解析的放弃标记；
  `checked=False` + `why` = 不是（空、前缀不对、时间坏了、理由空）。
  `checked=False` 绝不是"没有放弃"——它说的是"这一行自称放弃，而拿不出理由与时间"，
  那种行在收工读数里按未签计（`statements_unsigned` 的
  `abandoned_without_reason` 那一类），而不是按"已放弃"放行。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

#: 标记前缀。它与 `schema.STATEMENT_STATUSES` 里的 `abandoned` 同源命名：
#: 状态那一格说"这一行放弃了"，这一格说"为什么、什么时候"。
ABANDON_MARKER = "abandoned@"

#: 字段分隔符：`<前缀><ISO8601><分隔符><理由>`。
ABANDON_SEP = "@"


def abandon_marker(*, at: str, reason: str) -> str:
    """拼一条放弃标记（写侧唯一实现）。理由为空 ⇒ `ValueError`（不许静默丢理由）。

    为什么时间由调用方给而不是在这里取 `now()`：这一格要能被判据钉死
    （测试里两条一模一样的输入必须给出同一个字符串），"现在几点"的来源留在调用点。
    """
    got = str(reason or "").strip()
    if not got:
        raise ValueError(
            "放弃必须给理由：只写一个 status='abandoned' 等于把'为什么放下'记成一笔"
            "没人能接手的账（与 `quote_verified` 的三态纪律同一条）")
    stamp = str(at or "").strip()
    try:
        datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise ValueError(
            f"放弃标记的时间必须是 ISO8601（收到 {stamp!r}）：{exc}") from exc
    return f"{ABANDON_MARKER}{stamp}{ABANDON_SEP}{got}"


def parse_abandon(text: Any) -> dict[str, Any]:
    """读一条放弃标记（读侧唯一实现）：`{"checked","at","reason","why"}`。

    三态见模块 docstring：`checked=False` 说的是"这不是一条可解析的放弃标记"，
    不是"没有放弃"。
    """
    out: dict[str, Any] = {"checked": False, "at": "", "reason": "", "why": ""}
    raw = str(text or "").strip()
    if not raw:
        out["why"] = "`quote_reason` 是空的 ⇒ 拿不出理由与时间"
        return out
    if not raw.startswith(ABANDON_MARKER):
        out["why"] = (f"`quote_reason` 不以 {ABANDON_MARKER!r} 开头"
                      f"（收到 {raw[:40]!r}）⇒ 这不是一条放弃标记")
        return out
    rest = raw[len(ABANDON_MARKER):]
    stamp, sep, reason = rest.partition(ABANDON_SEP)
    stamp, reason = stamp.strip(), reason.strip()
    if not sep:
        out["why"] = (f"标记缺第二刀：要 `{ABANDON_MARKER}<ISO8601>{ABANDON_SEP}<理由>`，"
                      f"收到 {raw[:60]!r}")
        return out
    out["at"] = stamp
    try:
        datetime.fromisoformat(stamp)
    except ValueError:
        out["why"] = (f"标记里的时间不是 ISO8601（{stamp!r}）⇒ 读不出「什么时候放弃的」")
        return out
    if not reason:
        out["why"] = "标记里有时间没有理由 ⇒ 读不出「为什么放弃」"
        return out
    out.update(checked=True, reason=reason)
    return out
