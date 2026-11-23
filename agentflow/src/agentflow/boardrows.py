# -*- coding: utf-8 -*-
"""板项行的「状态」投影：`tasks` 表里 `kind` 非空那一行的读数怎么念。

`tasks` 混着两类行：代理行（`kind` 为空，一次召唤）与板项行（`kind` 非空：
notice / message / report / delegation 一类）。板项行的 `status` 设计上恒为
`pending` —— 它是"这一行是板项"的类型标记，不是"还没收口"；真正的收口状态在
`item_state` / `item_close`。拿 `status` 当状态打印，读的人看到的是一句假话
（"清干净了"与"还堆着"会长得一模一样）。

这一格的三档投影只有这一处实现（:func:`tasks_row_reading` 与三个常量）：
`statusreport._hint_of`（报告）与 `webui.readers` 的 `TaskRow.status_reading`
（网页）必须走同一处，否则同一行在两处有两种状态。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

#: 代理行那一轴「还欠着活」的活档。真身在 `secretary_vocab`（`conductor.UNFINISHED_STATUSES`
#: 与 `secretary.LIVE_TASK_STATUSES` 都是它的转发）—— 这里按名字回引，不写第二份字面量。
from .secretary_vocab import LIVE_TASK_STATUSES

#: 板项行那一格"状态"的投影前缀：把"这是板项"写进读数，免得读的人把 `done/acked`
#: 当成"一次召唤跑完了"。
BOARD_ITEM_STATUS_MARK = "板项"
#: 还没有 `item_close` 时的读法（空串不许印成空白：那会被读成"这一格没有状态"）。
BOARD_ITEM_NOT_CLOSED = "未收口"
#: 连 `item_state` 都没记（板那几格扩列之前落的行）时的读法 —— 三态里"没读到"那一档，
#: 不许折成 `queued`（那会让一条读不出来的行看起来像"正等着人处理"）。
BOARD_ITEM_STATE_UNKNOWN = "（未记）"


def tasks_row_reading(row: Mapping[str, Any]) -> str:
    """一条 `tasks` 行的"状态"那一格 —— 板项行按 `item_state`/`item_close` 投影。

    三档返回值：

    - 板项、已收口 ⇒ `板项 done/acked`（`item_close` 有值就念它）；
    - 板项、还开着 ⇒ `板项 queued/未收口` —— 不许把所有板项都说成 done；
    - 代理行（`kind` 为空）⇒ `<status>/<outcome>`（这一格对代理行本来就是真的）。

    只读那一行、不改它、不落盘：这是读侧投影，写入侧一个字节都不动。
    """
    if str(row.get("kind") or ""):
        state = str(row.get("item_state") or "") or BOARD_ITEM_STATE_UNKNOWN
        close = str(row.get("item_close") or "") or BOARD_ITEM_NOT_CLOSED
        return f"{BOARD_ITEM_STATUS_MARK} {state}/{close}"
    return f"{row.get('status')}/{row.get('outcome')}"


def row_is_open(row: Mapping[str, Any]) -> bool:
    """这一行还欠着活吗 —— 两轴分开的唯一判据（板项按 `item_state`，代理行按 `status`）。

    - 板项行（`kind` 非空）：欠不欠活由生命周期那一轴回答。`item_state == "done"`
      （`item_close` 是 `acked` / `completed` / `expired` 哪一档都一样）⇒ 已收口，不算；
    - 代理行（`kind` 为空）：`status` 在活档（`LIVE_TASK_STATUSES`）才算还开着。

    为什么不能只看 `status`：板项行的 `status` 是「类型标记」（`conductor._item_row`
    建行写死 `pending`，板的状态机只改 `item_state`），不是"还没收口"。真机
    `projects/sylow-1` 的 58 条 `status=pending` 全是板项、其中 57 条
    `item_state=done`（53 条 `item_close=acked`）⇒ 直接数 `status` 会把"已经收口的
    通知"读成"还堆着的待办"（假积压 58 vs 真待办 1）。

    三态：这一行两格都没记（老行 / 读坏）⇒ 代理行按 `status` 判、板项按
    `item_state` 判；两个都空 ⇒ `False`（不在活档），调用方若要分辨"没记"请自己读格。
    """
    if str(row.get("kind") or ""):
        return str(row.get("item_state") or "") != "done"
    return str(row.get("status") or "") in LIVE_TASK_STATUSES


def pending_reading(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """台账里「还有几条 pending」的唯一口径（`status` 那一格不再被当口径用）。

    返回 `{checked, total, agents, items, by_kind, open_ids, raw, gap, caliber}`：

    - `total` = 真开着的那几行（:func:`row_is_open`）；
    - `agents` / `items` = 代理行与板项行各自的条数（两轴分开报，不许折成一个数）；
    - `by_kind` = 开着的板项按 `kind` 的条数（"待办里是哪几类"）；
    - `open_ids` = 开着的行号（按 `task_id` 排序；给收工/编排面点名用，不进判定）；
    - `raw` = 直接数 `status ∈ LIVE_TASK_STATUSES` 的条数 —— 「旧口径，留着当反真空读数」：
      它把已收口的板项一起数进来；
    - `gap` = `raw - total`：类型标记被当成状态的那部分（正数 = 假积压；负数只可能出现在
      "板项被优雅停止翻成 `block`（`status` 离开活档）、而它其实还欠着活"那一档 ——
      两个方向都要能看见，所以不把它折成 `max(0, …)`）。

    读不成不在这里判：调用方拿到 `rows` 之前那次读表失败要自己折三态（本函数只算）。
    """
    agents = 0
    items = 0
    by_kind: dict[str, int] = {}
    open_ids: list[str] = []
    raw = 0
    for row in rows:
        status_live = str(row.get("status") or "") in LIVE_TASK_STATUSES
        if status_live:
            raw += 1
        if not row_is_open(row):
            continue
        open_ids.append(str(row.get("task_id") or ""))
        if str(row.get("kind") or ""):
            items += 1
            kind = str(row.get("kind") or "")
            by_kind[kind] = by_kind.get(kind, 0) + 1
        else:
            agents += 1
    open_ids.sort()
    return {
        "checked": True,
        "total": agents + items,
        "agents": agents,
        "items": items,
        "by_kind": by_kind,
        "open_ids": open_ids,
        "raw": raw,
        "gap": raw - (agents + items),
        "caliber": ("tasks 台账里『还开着』的唯一口径：代理行按 status∈"
                    "LIVE_TASK_STATUSES、板项行按 item_state!=done（boardrows.row_is_open）；"
                    "`raw` 是直接数 status 的旧口径，两者之差 `gap` 就是『类型标记被当成"
                    "状态』的那部分"),
    }
