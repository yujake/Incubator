# -*- coding: utf-8 -*-
"""到点判定的成本读数：最近一拍花了多少、下一拍该在多少秒后醒。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第十三刀的前半。
业主 2026-10-27 的施工单第 ① 条要一组读数：最近一次 `fire_due` / `due_timers` 的
`pending_count` / `scan_ms` / `target_probe_count` / `reconcile_count`，以及下一拍应当在
多少秒后醒。它必须是读数而不是"本次调用的入参与返回值"：三态分开、读不成是 `None`
不是 0、一个既有字段的含义都不改。

## 为什么单独一刀

`fire_due` / `due_timers` 每一拍都要调 `_cost_note` 记一笔，所以成本读数与到点层是
同一拍的两半；但把成本整块（110 行）与到点整块放进同一个文件会越过 800 行
（实测 833），于是按"读数 / 动作"切开：本模块只记与读，到点层调它。

## 装了什么

`_COST`（根 -> 最近一拍读数）/ `_COST_LAST`（不带工作区时读那个根）/
`COST_FIELDS`（受控键集，判据按它断言"一格不少、一格不多"）/ `_cost_blank` /
`_cost_note` / `cost_reading` / `reset_costs`。

## 可变量与依赖

`_COST` / `_COST_LAST` 的全部读写点都在本模块内（`from .clock import _COST` 是快照，
拆出去就会 split-brain）。依赖方向单向：只 import `clockrun._resolve_root`、
`clockbase._iso` 与 `Reading`（`TimerBook` 只出现在注解里）。
纯搬移，逐名 AST dump 全等，`clock.py` 原样再导出。
"""

from __future__ import annotations

from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    _iso,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    _resolve_root,
)

#: 每个工作区根最近一次的到点判定成本读数。
_COST: dict[str, dict[str, Any]] = {}

#: 最近一次写进 `_COST` 的那个根（不带工作区调 `cost_reading()` 时读它）。
_COST_LAST: list[str] = [""]

#: 这一份读数的受控键集（判据按它断言"一格不少、一格不多"）。
COST_FIELDS: tuple[str, ...] = (
    "checked", "reason", "source", "workspace", "at",
    "pending_count", "total_count", "scan_ms", "target_probe_count",
    "reconcile_count", "reconcile_total", "early_exit",
    "heap_size", "waiters_indexed", "hot_count", "next_wake_in_sec", "next_due_in_sec",
)


def _cost_blank(reason: str, *, workspace: str = "") -> dict[str, Any]:
    """一份"没查成"的成本读数：每一格都是 `None`，不是 0。"""
    row: dict[str, Any] = {k: None for k in COST_FIELDS}
    row.update({"checked": False, "reason": str(reason or ""),
                "workspace": str(workspace or "")})
    return row


def _cost_note(root: str, *, source: str, checked: bool, reason: str,
               scan_ms: float | None, probes: int | None,
               bucket: "TimerBook | None", reading: Reading | None,
               reconcile: int | None, early_exit: bool,
               hot: int | None = None) -> None:
    """把一次到点判定的成本落进读数（`fire_due` / `due_timers` 各调一次）。"""
    now_epoch = (reading.wall.timestamp()
                 if reading is not None and reading.wall is not None else None)
    row = _cost_blank(reason if not checked else "", workspace=root)
    row.update({
        "checked": bool(checked),
        "source": str(source),
        "at": (_iso(reading.wall)
               if reading is not None and reading.wall is not None else ""),
        "scan_ms": None if scan_ms is None else round(float(scan_ms), 4),
        "target_probe_count": probes,
        "reconcile_count": reconcile,
        "early_exit": bool(early_exit),
    })
    if bucket is not None:
        row["pending_count"] = bucket.pending_count()
        row["total_count"] = bucket.total_count()
        row["heap_size"] = bucket.heap_size()
        row["waiters_indexed"] = bucket.waiters_count()
        row["reconcile_total"] = bucket.reconcile_count()
        row["hot_count"] = bucket.hot_count() if hot is None else int(hot)
        if now_epoch is not None:
            wake = bucket.next_wake_epoch()
            due = bucket.next_due_epoch()
            row["next_wake_in_sec"] = (None if wake is None
                                       else round(max(0.0, wake - now_epoch), 6))
            row["next_due_in_sec"] = (None if due is None
                                      else round(max(0.0, due - now_epoch), 6))
    _COST[str(root)] = row
    _COST_LAST[0] = str(root)


def cost_reading(workspace: str | Path | None = None) -> dict[str, Any]:
    """最近一次 `fire_due` / `due_timers` 的成本读数（三态；读不成不折 0）。

    键集就是 `COST_FIELDS`，逐格的含义：

    | 键 | 是什么 | 读不成时 |
    |---|---|---|
    | `checked` | 这一次到点判定本身查成了没有 | —— |
    | `reason` | 没查成的理由（时钟读不到 / 簿记读不成 / 还没跑过） | —— |
    | `source` | 这份读数来自 `fire_due` 还是 `due_timers` | `None` |
    | `pending_count` | 那一拍 pending 的条数（早退路径也是真数，O(1)） | `None` |
    | `total_count` | 台账总行数（改前 `pending()` 会把它整表排序） | `None` |
    | `scan_ms` | 那一次判定花了几毫秒（早退路径 ≈ 0，但不是 0 假数） | `None` |
    | `target_probe_count` | 那一拍问了几次"被等对象收口了没有" | `None` |
    | `reconcile_count` | 那一拍做了几次补偿对账（0 或 1） | `None` |
    | `reconcile_total` | 这一份簿记累计对账过几次 | `None` |
    | `early_exit` | 那一拍是不是走了早退（没扫表、没问 target_state） | `False` |
    | `heap_size` | 堆里还有几条（早退之后它才是"下一次要判的东西"） | `None` |
    | `waiters_indexed` | 反查索引里的"等谁"关系条数 | `None` |
    | `next_wake_in_sec` | 下一拍应当在多少秒后醒 = `min(堆顶, 下次对账, 下一次周期性巡查) - 现在`，负数按 0 读 | `None` |
    | `next_due_in_sec` | 只取堆顶那一条（不含对账与周期性巡查），负数按 0 读 | `None` |

    `next_wake_in_sec` 的口径写死成"三者取较早者"，理由见 `TimerBook.next_wake_epoch`；
    挂机那一侧的片长封顶读的就是这一格（`agent_loop._park_sleep_once`）。

    两个 `None` 的除法：`next_wake_in_sec` 为 `None` 有两种情形 —— 这一格没查成，
    或者簿记里既没有到点、也没有对账时刻、也没有周期性巡查。后者是"没有任何事会把它叫醒"，
    与"马上要醒"是两件事，所以不折成 0。

    ## 它是读数，不是门；今天只有判据读它

    这一格今天没有"生产者以外的读者"：只有 `tests/test_the_clock_scales_with_the_book.py`
    与 `temp/_clock_bench.py` 读它。谁都不许拿它做闸 —— 时钟不许因为 `scan_ms` 超过某个数
    就拒绝起表、不许因为 `target_probe_count` 大就跳过判定、不许因为 `next_wake_in_sec`
    小就把一次 `fire_due` 报成没查成。把它接成闸的那一刻，"这几毫秒"就变成了"可能不做"，
    而本模块的全部三态纪律都是为了"不做"必须显式报出来。

    待办（下一批，不在这一批的范围内）：M 的巡查（`conductor.patrol`）可以把它作为一个格
    读出来（例如 `cost_reading()["scan_ms"]` 与 `["next_wake_in_sec"]` 并进那一拍的四格），
    但接线时只许"读出来给 M 看"，不许在这里加闸。这一句写在这里而不是只写在交接单里：
    将来读代码的人要能看见"谁该来读、以及读它时不许做什么"。
    """
    if workspace is not None:
        root = _resolve_root(workspace)
        row = _COST.get(root)
        if row is None:
            return _cost_blank(
                f"{root} 还没跑过到点判定（fire_due / due_timers 各一次都没跑）=> 这一格没查成",
                workspace=root)
        return dict(row)
    root = _COST_LAST[0]
    if not root or root not in _COST:
        return _cost_blank("本进程还没跑过任何到点判定 => 这一格没查成")
    return dict(_COST[root])


def reset_costs() -> None:
    """清空成本读数（判据之间的隔离点）。"""
    _COST.clear()
    _COST_LAST[0] = ""
