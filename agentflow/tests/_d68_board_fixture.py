# -*- coding: utf-8 -*-
"""D-68 的夹具助手：让替身角色"自己把板清了"。

## 为什么夹具需要这一步

业主 D-68 那两句话合起来是一条链：

```
「在"销号"时，如果 task_board 没清，发提醒，不准直接销号」
「最终 final 时应该是 M 下整棵树都已销号，否则不记 final」
```

于是：一个子代理若带着"读过却没 ack"的板项离场，它的父就永远销不掉它，M 的 final
就永远记不下来。生产里的解法是子代理自己调 `conductor.ack`（那只手正是 D-68 加的），
提示词负责让它惦记着去清。而判据里的角色是替身模型：它只有固定剧本，写不出
"自己名下那几条的 id"，也永远不会 ack。

所以夹具在这一处替它做那一步 —— 显式地、只写在一处、并在注释里说清
"这一句模拟的是子代理在自己收工前调用 `conductor.ack`"。

它不是框架兜底：`agent_loop` 里没有任何第二处自动收口的路径，这一点由
`tests/test_ack_is_the_hand_and_retire_needs_a_clean_board.py` 的 h 条
（扫代码 ＋ 行为断言：run 结束后未 ack 的项仍然是 seen）逐条钉着。

## 挂在哪

`Conductor.summon_run` —— `summon` 与 `summon_many` 两条路都经过它。每一环召唤返回之后，
把新子名下的项用 `Conductor.ack_items` 清掉。深度不限：D 派 E 时用的是
同一个 conductor 实例，那一层同样被包住。

`queued`（从没被读过的）项也一起清：那是替身模型欠下的那一次 ack，见下面那一段。
"""

from __future__ import annotations

from typing import Any


def ack_seen_items_of(conductor: Any, child_id: str) -> list[str]:
    """把 `child_id` 名下还没消的板项替它 ack 掉；返回确认掉的编号。

    为什么连 `queued` 的也清：这一句模拟的是"子代理在自己收工前把它名下该确认的都确认掉"
    —— 生产里它有一整轮上下文，见到什么就 ack 什么（`conductor.ack` 对 `queued` 的项
    先补记一次 seen 再推 done，见 `Conductor.ack_items` 的 docstring）。替身模型只有
    固定剧本，这一步只能由夹具代做；而只要留下一两条，父就永远销不掉它（业主 D-68
    的销号门），于是整条链在夹具里根本走不到 `final`。
    """
    if not str(child_id or ""):
        return []
    try:
        rows = conductor._tasks()
    except Exception:  # noqa: BLE001 —— 夹具本身不是被考察的对象；读不成就清不了
        return []
    open_ids = [str(r.get("task_id") or "") for r in rows
                if str(r.get("parent_task_id") or "") == str(child_id)
                and str(r.get("kind") or "")
                and str(r.get("item_state") or "") != "done"]
    if not open_ids:
        return []
    conductor.ack_items(open_ids, by_task_id=str(child_id),
                        note="夹具：替身角色收工前自己清板（模拟它调 conductor.ack）")
    return open_ids


def children_clean_their_boards(conductor: Any) -> Any:
    """把这个 conductor 上的每一环召唤改成"返回后替子代理清板"（见模块 docstring）。

    返回同一个 conductor（方便写成一行的夹具尾巴）。重复调用是幂等的：第二层会把
    第一层那一次包在里面，行为不变（只是多一层调用），但判据不需要那样。
    """
    real = conductor.summon_run

    def _summon_then_clean(*args: Any, **kwargs: Any) -> Any:
        res = real(*args, **kwargs)
        child = str(getattr(res, "task_id", "") or "")
        if child:
            ack_seen_items_of(conductor, child)
        return res

    conductor.summon_run = _summon_then_clean  # type: ignore[method-assign]
    return conductor
