# -*- coding: utf-8 -*-
"""秘书的行轴与活口（唯一判据，从 secretary.py 的 U08 尾段逐字搬出）。

我保证哪条不变式：一行是哪一轴（agent / 开着的项 / 关掉的项 / 根 / 其它）与它是不是活口，各只有一问、各只有一处判；别的模块只许问它，不许自己再判一次。

## 为什么它能单独成文件（依赖方向）

`secretary_axis` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_axis` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    LIVE_TASK_STATUSES,
    RAN_STATUSES,
    ROW_AXIS_AGENT,
    ROW_AXIS_ITEM_CLOSED,
    ROW_AXIS_ITEM_OPEN,
    ROW_AXIS_OTHER,
    ROW_AXIS_ROOT,
    TOP_LEVEL_ACTION,
)


class AxisMixin:
    """行轴与活口（唯一判据）（从 secretary.py 搬出的混入类）。"""

    #: `status` 那一格的取值（S-H，裁定 14）。前三档照 DSH `list-agents.js:24-29` 的算法逐字：
    #: 不在 live registry ⇒ `ready`；在且在跑 ⇒ `running`；否则 `idle`。
    #: 第四档 `retired` 是我们的如实加一档（见 `roster_view` 的 docstring）：
    #: DSH 的 `ready` 说的是"没有活着的 Agent、但仍可续"，而我们的销号名字永久不复用
    #: ⇒ 把它也读成 `ready` 会让模型去 `send_message` 一个再也叫不醒的名字。
    STATUS_VALUES: tuple[str, ...] = ("running", "idle", "ready", "retired")

    def _resolve(self, owner: str, name: str) -> tuple[str, str]:
        index, bad = self.roster_index(owner)
        if bad:
            return "", f"对照表有 {len(bad)} 行读不出来 ⇒ 不译（{bad[0]}）"
        for r in index:
            if str(r.get("name") or "") == str(name) and not r.get("retired"):
                return str(r.get("task_id") or ""), ""
        return "", f"对照表里没有 {name!r}（未登记或已退役）"


def ran_but_unnamed(row: Mapping[str, Any],
                    known: Mapping[str, Any] | set[str] | frozenset[str]) -> bool:
    """这条台账行是不是「真跑过、名册里却没有它」—— 全仓唯一的判据。

    ## 为什么要有这一格（`draft/160` 的问题定义）

    81 趟的 `t-000106`：父点名 `E2`，而 `E2` 已被一个从没跑过的号（`t-000030`，派活闸
    `concurrency_exceeded`）占着 ⇒ 名册写口受控拒绝（`name_taken`），派活照跑、子代理
    真跑完（`done/ok`、有产物），然后两条补名路都关着（`draft/160` 一-c）⇒ 它永久没有
    名字，而盘上没有任何一格读数看得出这件事。

    ## 四个条件，一条都不能少（每一条都对着一个已堵住的洞）

    1. `status ∈ RAN_STATUSES`：跑完了（`done` / `failed` / `cancelled`）。在飞的
       （`pending` / `running`）不算 —— 那是 159 那个"台账行已落、名册还没落"的窗口，
       把它算进来就会把兄弟行报成"无名"（同一族误判，`draft/159` §一）。
    2. `outcome != "refused"`：派活闸拒掉的号不许进这一格。这是 d9ebb7fe / 1cdacbf6
       划的那条界（"没跑过"与"跑过没名"是两件事），也是本格不重开那两个洞的证明。
    3. `ended_at` 非空：与 1 互为兜底 —— 只有真的有过结束时刻才叫跑完。
    4. `task_id ∉ known`：`known` 是那个父名下「名册接过」的全部号（`add` ∪ `bind`，
       与 `Secretary._roster_history` 同一份口径）。有名字的当然不算无名。

    `known` 收 `Mapping` 或集合：前者就是 `_roster_history` 的返回值（号 → 名字），
    后者给只需要"在不在"的读者用（`webui.readers` 那一格）。
    """
    if str(row.get("kind") or ""):
        # 板项行（`message` / `notice`）不是代理：它们没有"跑过"这回事。
        return False
    tid = str(row.get("task_id") or "")
    if not tid or tid in known:
        return False
    if not str(row.get("parent_task_id") or ""):
        # 没有父的绝对编号 ⇒ 不在任何人的名册上，也无从"该有名字"（顶趟就是这样）。
        return False
    if str(row.get("status") or "") not in RAN_STATUSES:
        return False
    if str(row.get("outcome") or "") == "refused":
        return False
    return bool(str(row.get("ended_at") or ""))


def _state_reading(branch: str, retired: bool, cond: Any, task_id: str, *,
                   branch_checked: bool = True) -> dict[str, Any]:
    """四态折叠（`draft/92` §2）＋ 三态位：`{"state", "state_checked", "state_reason"}`。

    `branch` 来自 `conductor.retire_ready`（`active` / `waiting_with_children` /
    `waiting_no_children`）；"待命"再看 `keep_alive_of`（那一格只回答"声明过待命没有"）。
    两个读侧正交，折叠只在这一处做（不许让它们互相猜）。

    ## 为什么多了 `state_checked`（2026-10-27）
    改前"待命声明读不成"折成 `state="已停"` —— 那是把"没查成"写成一条结论，而这一格
    会被父代理读成"它停了、可以销号"。五档取值域不改（前端与读侧都按它显示），
    改成另一格回答可不可信：
    - `state_checked=True`：`state` 是查过的结论；
    - `state_checked=False`：`state` 只是五档里的占位（落"未登记"，五档里唯一不声称
      任何结论的那一档），真读数在 `state_reason` 里（谁没读成、为什么）。
    读侧不许在 `state_checked=False` 时把 `state` 当"它停了"用（判据
    `tests/test_roster_state_is_checkable.py`）。

    ## 三态位怎么定
    - 已退役 / 活跃 / 未登记（branch 为空）：`state_checked=True` —— 这三档都是"读到了
      台账、读到了就绪读数"之后的结论；
    - `branch_checked=False`（那一层的 `retire_ready` 没读成）：`state_checked=False`；
    - 待命声明读不成（`keep_alive_of` 的 `checked=False`）：`state_checked=False`，
      且 `state` 落"未登记"（不落"已停"）。
    """
    if retired:
        return {"state": "已退役", "state_checked": True, "state_reason": ""}
    if branch == "active":
        return {"state": "活跃", "state_checked": True, "state_reason": ""}
    if not branch:
        if not branch_checked:
            return {"state": "未登记", "state_checked": False,
                    "state_reason": "这一层的就绪读数（`retire_ready`）没读成 ⇒ 它属哪一档判不了"}
        return {"state": "未登记", "state_checked": True, "state_reason": ""}
    try:
        ka = cond.keep_alive_of(task_id)
    except Exception as exc:  # noqa: BLE001
        ka = {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not ka.get("checked"):
        return {"state": "未登记", "state_checked": False,
                "state_reason": (f"待命声明没读成（{ka.get('reason') or '未给理由'}）"
                                 "⇒ '待命'与'已停'分不开")}
    if ka.get("keep_alive"):
        return {"state": "待命", "state_checked": True, "state_reason": ""}
    return {"state": "已停", "state_checked": True, "state_reason": ""}


def _status_enum(facts: Mapping[str, Any], *, retired: bool) -> str:
    """`status` 那一格（S-H，裁定 14）。前三档照 DSH `list-agents.js:24-29` 逐字。

    - 不在 live registry（我们这边 = 台账里没有它正在跑的行）⇒ `ready`；
    - 在且 `status in (pending, running)` ⇒ `running`；
    - 否则 ⇒ `idle`（DSH 的 `maintenance`（正在收尾）也算 idle，我们这边 `closing`
      那一档同理 —— 收尾不是"在干活"）。

    第四档 `retired` 是如实加的一档（我们的销号名字永久不复用）：
    DSH 的 `ready` 逐字意思是"没有活着的 Agent、但仍可续"，把销号读成它会让模型
    去叫一个再也叫不醒的名字 ⇒ 那个错法的代价比"多一个取值"大。
    """
    if retired:
        return "retired"
    if not facts:
        # 台账里没有它这一行（未登记 / 已被清）⇒ `ready`：那一档的语义正是
        # "不在活的登记表里"，而"能不能续"由旁边那格 `state` 回答。
        return "ready"
    if str(facts.get("status") or "") in LIVE_TASK_STATUSES:
        return "running"
    return "idle"


def row_axis(row: Mapping[str, Any]) -> str:
    """一行 `tasks` 落在哪根轴上（唯一判据，2026-10-26 Q18；Q27 起只管轴）。

    三件事实按这个次序定：

    1. `kind` 非空 ⇒ 板项行（`conductor.open_item` 建的行：`notice` / `message` /
       `report` / `delegation`）。板项行的 `status` 永远是 `pending`（`open_item` 写死、
       `_set_item` 只改 `item_state`）⇒ 拿 `status` 判"在跑"必然把它们算进去。
       "收口了没有"由 `item_state == "done"` 回答：它和"这是哪根轴"是两个问题，
       但都只在这里判（改前收口与否根本没进读数，已 ack 的板项也照样算在跑）。
    2. `kind` 为空、`action == "run"` 且没有父 ⇒ 顶趟行：它是"用户发起的那一趟"本身，
       不是谁的子代理（`open_top_level_run` 与队列认领的树根都是这个形态）。
       为什么形状这么写：真机那 18 条代理行里 16 条 `action` 是空串、1 条 `run_once`
       —— "action 属跑活的那几档"的白名单会把 16 条真代理漏掉，那是反向的谎。
       所以这里只排顶趟哨兵，而且要求"没有父"：父派给它一次 `A.run` 那种真子代理
       带着 `parent_task_id`，不许被一起排掉。
    3. 其余 `kind` 为空的行：`status` 在活档 ⇒ 代理行；否则 ⇒ 别的（历史终态行）。
       终态行不是"被排除的候选"，它已经收过工了，两根轴都不进、也不进任何一个计数。

    读不成不是"没有行"：异常由调用方折成三态，本函数只认拿到的那一行。

    与 Q18 的 `task_row_axis` 逐字同形（五档、同输入同输出）—— 这一批只是改名并把
    "活不活"那一问搬进 :func:`is_live_agent`，读数一个都不许动。判据见
    `tests/test_the_axis_and_liveness_are_asked_separately.py`。
    """
    if str(row.get("kind") or ""):
        if str(row.get("item_state") or "") == "done":
            return ROW_AXIS_ITEM_CLOSED
        return ROW_AXIS_ITEM_OPEN
    if (str(row.get("action") or "") == TOP_LEVEL_ACTION
            and not str(row.get("parent_task_id") or "")):
        return ROW_AXIS_ROOT
    if str(row.get("status") or "") in LIVE_TASK_STATUSES:
        return ROW_AXIS_AGENT
    return ROW_AXIS_OTHER


def is_live_agent(row: Mapping[str, Any]) -> bool:
    """这一行是不是"一个活着的代理"（唯一判据，2026-10-26 Q27）。

    与 :func:`row_axis` 的分工：轴回答"这一行是什么"（板项 / 顶趟 / 代理 / 别的），
    这一问回答"它还算不算在跑"。两者此前挤在同一个返回值里，于是要"所有代理行
    （含终态）"的读点拿不到、要"活着的代理"的读点只能自己再写一遍
    `kind == "" and status in {pending, running}` —— 而自己写的那几份就是 Q18 之前
    板项被数成"在跑的子代理"的来源。

    判法只有一句：轴是 `agent` 就是活着的代理（活档的判定在 :func:`row_axis` 的
    第 3 步，这里不重复写状态词表）。顶趟行、板项行、终态代理行都不是。

    改前它的三处调用方各写一遍判据，其中两处（`conductor._in_flight_children_of`
    与 `statusreport.collect`）连"哪一行是板项"都要自己判 `kind`；迁移的判据见
    `tests/test_the_axis_and_liveness_are_asked_separately.py`。
    """
    return row_axis(row) == ROW_AXIS_AGENT


def _diagnose_line(problem: str) -> dict[str, Any]:
    """一条坏行读数 → 逐行 diagnostic（DSH `list-agents.js:30-47` 的三档）。

    `corrupt` = 那一行不是合法 JSON / 不是对象；`unavailable` = 整个文件读不出来
    （IO 层失败）；`unsupported` = 其余（形状能读、但我们不认这一行的内容）——
    第三档留着是因为把"没见过的东西"折进前两档会让"这一行到底坏在哪"失去分辨率。
    """
    text = str(problem or "")
    if "读不出来（" in text and "第 " not in text:
        kind = "unavailable"
    elif "第 " in text and "行" in text:
        kind = "corrupt"
    else:
        kind = "unsupported"
    return {"line": text, "kind": kind}
