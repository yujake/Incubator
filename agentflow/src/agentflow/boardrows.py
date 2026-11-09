# -*- coding: utf-8 -*-
"""板项行的「状态」投影（D12）：`tasks` 表里 `kind` 非空那一行的读数怎么念。

## 这个文件里有什么

`tasks` 表混着两类行：代理行（一次召唤，`kind` 为空）与板项行（`kind` 非空：
notice / message / report / delegation 一类）。板项行的 `status` 设计上恒为
`pending`（它是"这一行是板项"的类型标记，不是"还没收口"），真正的收口状态在
`item_state` / `item_close`。这一格的三档投影只有这一处实现：
:func:`tasks_row_reading` 与它的三个常量。

## 为什么单独一个模块（2026-11-09）

`statusreport.py` 越过了 repo survey 那条软判据的线（`>800 行` 的 src 文件数，
`tests/test_repo_survey_does_not_get_worse.py`）；业主口径是拆、不是抬基线。
切出来的这一族是"板项行的状态该怎么念"，它与报告渲染的其余部分没有共享状态，
只是两个调用方都必须走的同一处口径（`statusreport._hint_of` 与
`webui.readers` 的 `TaskRow.status_reading`）。

搬的是整段（注释逐字不动）。`statusreport` 按名字回引 :func:`tasks_row_reading`
与三个 `BOARD_ITEM_*` 常量，于是 `statusreport.tasks_row_reading` 照旧可用 ——
判据 `tests/test_a_board_item_shows_its_item_state.py` 的 ③ 整格替换的就是它。
"""
from __future__ import annotations

from typing import Any, Mapping

#: 板项行（`kind` 非空）那一格"状态"的投影前缀：`status` 对它们恒为 `pending`，
#: 所以那一格读的是 `item_state`/`item_close` —— 前缀把"这是板项"写在读数里，
#: 免得读的人把 `done/acked` 当成"一次召唤跑完了"。
BOARD_ITEM_STATUS_MARK = "板项"
#: 板项行还没有 `item_close` 时的读法（空串不许印成空白：那会被读成"这一格没有状态"）。
BOARD_ITEM_NOT_CLOSED = "未收口"
#: 板项行连 `item_state` 都没记（板那几格扩列之前落的行）时的读法 —— 三态里
#: "没读到"那一档，不许折成 `queued`（那会让一条读不出来的行看起来像"正等着人处理"）。
BOARD_ITEM_STATE_UNKNOWN = "（未记）"


def tasks_row_reading(row: Mapping[str, Any]) -> str:
    """一条 `tasks` 行的"状态"那一格 —— 板项行按 `item_state`/`item_close` 投影。

    ## 为什么板项行不能打 `status`

    `tasks` 表里板项行（`kind` 非空）的 `status` 设计上永远是 `pending`：
    `conductor._item_row` 建行就写死它（`:4568-4577`），收口只动 `item_state` /
    `item_close`（`_set_item`，`:5348-5360`），源码自己那句逐字写着「板项行 `status`
    永远是 `pending`」（`:5663`）。也就是说那一格是"这一行是板项"的类型标记，
    不是"还没收口" —— 拿它当状态打印出来，读的人看到的是一句假话。

    代价是实测过的：真机 `out/review/STATUS-20261109-1110.md` 里
    `t-000104 B.notice pending/None`，而 `data/tasks.json` 里 71 条 notice 的
    `(status, item_state)` 全是 `("pending", "done")`（acked 46 / expired 24 /
    completed 1）。于是"清干净了"与"还堆着"在读数上长得一模一样 —— 业主看到的
    那屏「大量 notice 任务」就是这一格（D12）。

    ## 两档用同一个函数（改前是两份）

    调用方只有两处，而且必须是同一处口径：
    `statusreport._hint_of`（`.md` / `.json` 的状态报告）与
    `webui.readers.artifacts_face` 的 `TaskRow.status_reading`（`GET /api/artifacts`
    ⇒ 网页「任务产物」那一栏）。两处各写一份 = 同一行在报告与网页上有两种状态，
    而那正是 D12 的形态。

    ## 三档返回值

    - 板项、已收口 ⇒ `板项 done/acked`（`item_close` 有值就念它）；
    - 板项、还开着 ⇒ `板项 queued/未收口` —— 不许把所有板项都说成 done；
    - 代理行（`kind` 为空）⇒ 与改前逐字相同：`<status>/<outcome>`（这一格对代理行
      本来就是真的：`status` 会迁移，`outcome` 收工时写）。

    唯一的输入是那一行（`Mapping`），不改它、不落盘：这是读侧投影，
    `status` 在写入侧一个字节都没动（改 schema 语义是另一件事，见 D12 的边界）。
    """
    if str(row.get("kind") or ""):
        state = str(row.get("item_state") or "") or BOARD_ITEM_STATE_UNKNOWN
        close = str(row.get("item_close") or "") or BOARD_ITEM_NOT_CLOSED
        return f"{BOARD_ITEM_STATUS_MARK} {state}/{close}"
    return f"{row.get('status')}/{row.get('outcome')}"
