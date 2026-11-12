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

from typing import Any, Mapping

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
