# -*- coding: utf-8 -*-
"""巡查文案与异常清单：`patrol_*` 那一整层。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第八刀。
业主 2026-10-26：「这个是 M 定期巡查需要特别注意的异常行为，M 可通过发送指导意见干预」。
于是"巡查时间到"那句话不许只有目的 / 间隔 / 第几次：它还要带一份当拍现算的异常清单。
清单里每一条事实（停滞 / 静默 / 未消板项 / 被拦的结项原因）要读台账、板项与名册，
那是工具层的事 —— 本模块只负责"把清单拼进报醒"这一半，读口经 `set_patrol_probe` 接进来。

## 装了什么

`_PATROL_PROBE`（唯一读口槽）+ `set_patrol_probe`（唯一写点）+ `patrol_anomalies`
（四类异常的三态读数）+ `_patrol_cell` / `_patrol_ids` / `_first_sentence`（拼句零件）+
`patrol_text`（异常清单正文）+ `patrol_section`（清单 + 干预指引）+ `patrol_sop_text`
（巡查 SOP 四步）+ `next_patrol`（"已经有一条了吗"的唯一读口）+ `start_patrol_timer`
（挂机那一拍起表，M 角色才挂）。

## 可变量与依赖

`_PATROL_PROBE` 的写点与读点同处这一个模块（跨模块 `global` 只改本模块命名空间）。
依赖方向单向：`book` / `start_timer` 在 `clocktimer` / `clockmem`，本模块在它们之上；
`_deliver_one_locked`（`clockfire.py`）与 `PeriodicShot` 反过来 import 本模块的拼句口。
纯搬移，逐名 AST dump 全等，`clock.py` 原样再导出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    ClockError,
    ClockStateError,
    ClockUnreadable,
    PATROL_CLEAN_TEXT,
    PATROL_GUIDE_HEAD,
    PATROL_INTERVAL_SEC,
    PATROL_REASON,
    PATROL_ROLE,
    _iso,
    human_sec,
)
from .clockmem import (  # noqa: F401 — 这些名字由 clockmem 定义
    start_timer,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    is_patrol_timer,
    now,
)
from .clocktimer import (  # noqa: F401 — 这些名字由 clocktimer 定义
    book,
)

#: 异常清单的读口：`probe(workspace, task_id) -> dict`。
#:
#: 键集见 `patrol_anomalies`；三态由它自己的 `checked` / `reason` 给。工具层在装配期
#: 用 `set_patrol_probe` 把它接上（与 `set_due_handler` 同一处：`clock_tools.register`）。
_PATROL_PROBE: Callable[[str, str], Mapping[str, Any]] | None = None


def set_patrol_probe(probe: Callable[[str, str], Mapping[str, Any]] | None
                     ) -> Callable[[str, str], Mapping[str, Any]] | None:
    """接上"当拍现算的异常清单"读口，返回被替换掉的那一个。

    签名是 `probe(workspace, task_id) -> dict`，必须回这五格：

    - `checked`：这一次查成没查成（读不成台账 / 没有主控实例 => False）；
    - `reason`：没查成的理由（读数要能读出"为什么这一拍没有清单"）；
    - `at`：当拍时刻（ISO；读不到时钟就是空串）；
    - `stalled` / `silent` / `open_items` / `final_refusals`：四类各一格，每格是
      `{"checked", "count", "rows", "reason"}`（`open_items` 另带 `ack` / `work`）。

    第四格为什么叫 `final_refusals`（2026-11-03，153-U-09）：它数的是会话里的
    `final_refused` 事件（收工被拒），与台账里"动作被拒"的 `action_refusals`、
    名册写口拒绝的 `registration_refusals` 是三件事 —— 三件事各一个名字。

    为什么放在工具层：这四类要读台账、板项与名册，而本模块的纪律是"能被判据单独喂假时钟、
    单独检查读数"，不为一个查询把 Store 拖进来（与 `set_target_probe` 逐字同一条理由）。
    """
    global _PATROL_PROBE
    previous = _PATROL_PROBE
    _PATROL_PROBE = probe
    return previous


def _patrol_cell(blank: Mapping[str, Any], raw: Any, *, name: str) -> dict[str, Any]:
    """把读口给的一格规整成 `{checked, count, rows, reason}`（缺格 => 没查成，不是 0）。

    缺格折成 0 会把"这一格没读"读成"这一类没有" —— 那正好是这一批要分开的那两件事。
    """
    if not isinstance(raw, Mapping):
        return {**dict(blank), "checked": False,
                "reason": f"读口没给 {name} 那一格 => 这一类没查成"}
    cell = {**dict(blank), **dict(raw)}
    cell["rows"] = [dict(r) for r in (cell.get("rows") or ()) if isinstance(r, Mapping)]
    if cell.get("count") is None and bool(cell.get("checked", True)):
        cell["count"] = len(cell["rows"])
    return cell


def patrol_anomalies(workspace: str | Path, *, task_id: str = "") -> dict[str, Any]:
    """当拍现算的异常清单（唯一入口；读口由工具层在装配期接上）。

    返回的键集固定（判据与 `patrol_text` 都按它读）：

    ```
    {"checked", "reason", "at", "task_id",
     "stalled":     {"checked", "count", "rows", "reason"},
     "silent":      {...},
     "open_items":  {"checked", "count", "ack", "work", "rows", "reason"},
     "final_refusals": {...}}
    ```

    三态：`checked=False` 加 `reason` 就是"这一拍没查成"（读口没接 / 读口抛了 / 读口说
    没查成）。这一档绝不退回"四类都是 0"：那会把"没查"折成"没有"，而这一拍的全部价值
    正好在分得开这两件事。同理，某一格没给出来时那一类单独记"没查成"（`_patrol_cell`），
    其余三类照常报。

    为什么它是唯一入口：反真空判据要把"异常清单这一步"打桩成返回空，而在别处再算一份
    清单就没有那个桩可打 —— 桩打不到，判据证明的只是"打桩坏了"。
    """
    reading = now()
    stamp = _iso(reading.wall) if reading.wall is not None else ""
    blank: dict[str, Any] = {"checked": False, "count": None, "reason": "", "rows": []}
    out: dict[str, Any] = {"checked": False, "reason": "", "at": stamp,
                           "task_id": str(task_id or ""),
                           "stalled": dict(blank), "silent": dict(blank),
                           "open_items": {**blank, "ack": None, "work": None},
                           "final_refusals": dict(blank)}
    probe = _PATROL_PROBE
    if probe is None:
        out["reason"] = "没有接上异常清单的读口（set_patrol_probe 还没接）=> 这一拍没查成"
        return out
    try:
        got = dict(probe(str(Path(workspace).resolve()), str(task_id or "")) or {})
    except Exception as exc:  # noqa: BLE001 - 读口炸了是"没查成"，不是"没有异常"
        out["reason"] = f"异常清单读口抛了 {type(exc).__name__}: {exc}"
        return out
    if not got.get("checked"):
        out["reason"] = str(got.get("reason") or "读口说这一次没查成（没给理由）")
        return out
    out["checked"] = True
    out["at"] = str(got.get("at") or stamp)
    out["stalled"] = _patrol_cell(blank, got.get("stalled"), name="stalled")
    out["silent"] = _patrol_cell(blank, got.get("silent"), name="silent")
    out["final_refusals"] = _patrol_cell(blank, got.get("final_refusals"),
                                         name="final_refusals")
    items = _patrol_cell({**blank, "ack": None, "work": None},
                         got.get("open_items"), name="open_items")
    out["open_items"] = items
    return out


def _patrol_ids(cell: Mapping[str, Any]) -> list[str]:
    """一格里的绝对编号（去重、保序）。"""
    out: list[str] = []
    for row in cell.get("rows") or ():
        tid = str((row or {}).get("task_id") or "")
        if tid and tid not in out:
            out.append(tid)
    return out


def _first_sentence(text: Any, *, limit: int = 160) -> str:
    """一句话的首句（拒信要的是"首句"，不是整段）。空 => 空串。"""
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    for mark in ("。", "；", "！"):
        head = body.split(mark, 1)[0]
        if head:
            body = head
            break
    return body[:limit]


def patrol_text(anomalies: Mapping[str, Any]) -> str:
    """把一份异常读数拼成报醒里那一段（唯一一份拼法）。

    四类各占一句，每句都带"条数"两个字（判据按它认出"这一类查过了"）：

        ① 停滞子：`status=running` 而超过阈值没有新步（点名绝对编号 + stalled_sec）
        ② 静默未销号的子：已收工、没别的事（只在等与它有关的消息或委托），却不是 retired（给销号指路）
        ③ 未消板项：`item_state != done` 的条数，按 expect 分 ack / work
        ④ 被拦的结项原因：最近一次 final_refused / 板项闸的拒信首句

    四类都空 => 末尾逐字写 `本轮无异常`。有异常子（① / ② 非空）=> 末尾给一句可执行的
    干预指引，并点名那个子的绝对编号（业主：「M可通过发送指导意见干预」）。
    某一类读不到 => 那一类写"条数读不到（理由）"，不许折成 0。
    """
    cells: dict[str, Mapping[str, Any]] = {}
    for key in ("stalled", "silent", "open_items", "final_refusals"):
        got = anomalies.get(key)
        cells[key] = got if isinstance(got, Mapping) else {}

    def _count_of(cell: Mapping[str, Any], label: str) -> str:
        if not cell.get("checked", True) or cell.get("count") is None:
            return f"{label} 条数读不到（{str(cell.get('reason') or '没查成')}）"
        return f"{label} 条数 {int(cell.get('count') or 0)}"

    stalled = cells["stalled"]
    silent = cells["silent"]
    items = cells["open_items"]
    final_refusals = cells["final_refusals"]

    bits: list[str] = []
    if not stalled.get("checked", True) or stalled.get("count") is None:
        bits.append(_count_of(stalled, "① 停滞子"))
    elif int(stalled.get("count") or 0):
        threshold = stalled.get("threshold_sec")
        named = "、".join(
            f"{str(r.get('task_id') or '?')}（{str(r.get('role') or '?')}"
            f"，stalled_sec={int(float(r.get('stalled_sec') or 0))}"
            + (f"，阈值 {int(threshold)} 秒" if threshold else "")
            + (f"，最近一步在 {str(r.get('last_step_at') or '')}" if r.get("last_step_at") else "")
            + "）"
            for r in (stalled.get("rows") or ()))
        bits.append(f"① 停滞子 条数 {int(stalled['count'])}：{named}")
    else:
        bits.append("① 停滞子 条数 0")

    if not silent.get("checked", True) or silent.get("count") is None:
        bits.append(_count_of(silent, "② 静默未销号的子"))
    elif int(silent.get("count") or 0):
        named = "、".join(
            f"{str(r.get('task_id') or '?')}（{str(r.get('role') or '?')}"
            f"，{str(r.get('why') or '已收工、没别的事（只在等与它有关的消息或委托），却还在册')}；"
            "要销号它吗 —— 走 conductor.retire_child）"
            for r in (silent.get("rows") or ()))
        bits.append(f"② 静默未销号的子 条数 {int(silent['count'])}：{named}")
    else:
        bits.append("② 静默未销号的子 条数 0")

    if not items.get("checked", True) or items.get("count") is None:
        bits.append(_count_of(items, "③ 未消板项"))
    else:
        ack = int(items.get("ack") or 0)
        work = int(items.get("work") or 0)
        other = items.get("other")
        other = (int(other) if other is not None
                 else max(0, int(items["count"]) - ack - work))
        extra = f" / 未标 expect {other}" if other else ""
        line = (f"③ 未消板项 条数 {int(items['count'])}"
                f"（待 ack {ack} / 待 work {work}{extra}）")
        ids = _patrol_ids(items)
        bits.append(f"{line}：{'、'.join(ids)}" if ids else line)

    if not final_refusals.get("checked", True) or final_refusals.get("count") is None:
        bits.append(_count_of(final_refusals, "④ 被拦的结项原因"))
    elif int(final_refusals.get("count") or 0):
        rows = list(final_refusals.get("rows") or ())
        head = rows[0] if rows else {}
        text = _first_sentence(head.get("text"))
        kind = str(head.get("kind") or "final_refused")
        where = f"（{kind}" + (f"，{str(head.get('at') or '')}" if head.get("at") else "") + "）"
        bits.append(f"④ 被拦的结项原因 条数 {int(final_refusals['count'])}（最近一条）："
                    f"{text or '读不到拒信原文'}{where}")
    else:
        bits.append("④ 被拦的结项原因 条数 0")

    at = str(anomalies.get("at") or "")
    head = f"异常清单（当拍现算 {at or '时刻读不到'}）："
    all_checked = all(bool(cells[k].get("checked", True)) for k in cells)
    has_any = any(int(cells[k].get("count") or 0) for k in cells if cells[k].get("checked", True))
    if all_checked and not has_any:
        return f"{head}{'；'.join(bits)} => {PATROL_CLEAN_TEXT}"

    body = f"{head}{'；'.join(bits)}"
    stalled_ids = _patrol_ids(stalled)
    targets = stalled_ids + [t for t in _patrol_ids(silent) if t not in stalled_ids]
    if targets:
        body = (f"{body}。干预指引：{PATROL_GUIDE_HEAD}给上面点名的那个子 —— 走既有的名册"
                f"寻址（名册名或绝对编号都行）与秘书链：用 message 到 {'、'.join(targets)}，"
                "正文只到链尾；发过之后它的下一步应该变：再读 conductor.tree / clock.now 时，"
                "上面点名那个子的步号要比现在大、或它的 status 转成终态；两样都没变就是没送到"
                "或它没听，再发一次，或按 ② 的指路把它销号")
    elif has_any:
        body = (f"{body}。处置指路：③ 的项逐条用 conductor.ack 确认（板项闸认的是"
                "item_state=done），④ 那一句就是下一次 final 会被拦的原因，先把整棵树销号"
                "再收工；这一拍没有异常子，所以不点名任何子")
    return body


def patrol_section(workspace: str | Path, *, task_id: str = "",
                   anomalies: Mapping[str, Any] | None = None) -> str:
    """这一拍报醒里要附的那一段（清单没查成 => 明说没查成，绝不写"本轮无异常"）。

    `anomalies` 给了就直接用（调用方刚算过一份，别为了拼文本再读一遍会话/台账）。

    两处 try 是同一个理由：这一段的任何失败都不许把"到点报醒"本身带走 —— 那一拍是
    M 唯一会醒来的凭据，清单坏掉只该少一段文字，不该少一次唤醒。
    """
    try:
        got = dict(anomalies) if isinstance(anomalies, Mapping) else \
            patrol_anomalies(workspace, task_id=task_id)
    except Exception as exc:  # noqa: BLE001 - 清单算不出来是"没查成"
        got = {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not got.get("checked"):
        # 逐字不出现「本轮无异常」：那一句是"四类都空"的专用读数，这里能 grep 到它
        # 就等于把"没查成"伪装成了"没有异常"（而"没有"与"没查"正是要分开的那两件事）。
        return (f"异常清单没查成（{str(got.get('reason') or '读口没给理由')}）"
                " => 这一拍没有清单可报（没查到与没有是两件事）")
    try:
        return patrol_text(got)
    except Exception as exc:  # noqa: BLE001 - 拼不出来也不许吞掉这次唤醒
        return f"异常清单拼不出来（{type(exc).__name__}: {exc}）=> 这一拍没有清单可报"


def patrol_sop_text(*, interval_sec: float | None = PATROL_INTERVAL_SEC) -> str:
    """轮查到点那一刻的正文：一套现在就要执行的规范动作（不是"时间到了"这种提醒句）。

    为什么正文必须是 SOP：业主给的那一句里说得最重的是最后半句 ——「到点后不是返回一句
    提醒，而是一套需执行的规范动作」。一句"时间到了"只告诉 M 一个它已经知道的事实
    （它在 20 分钟前自己挂的表到点了），而 M 缺的是"接下来做什么"；那件事今天已经有工具
    了（`conductor.patrol` / `conductor.patrol_verdict`，L1 落的三件），所以正文的任务是
    把工具按顺序摆到它面前，四步一步不少：

    ① 立刻调 `conductor.patrol`（一次拿全，不逐个 `review_child` 地去翻）；
    ② 对每一个活跃子代理给结论：`pass`（过）或 `guide`（指导意见）；
    ③ 结完这一轮，才允许做别的（自由行动）；
    ④ 无事可做（要挂机等）时，挂上下一个轮查计时器。

    第 ④ 步为什么还留在正文里、而框架其实会自动挂（`agent_loop._park_gate` 那一侧）：
    这一句是给 M 的"不要手工再起一条"的交代 —— 挂点那一侧保证的是"恰好一条"，模型读了
    SOP 又自己 `clock.timer_start(after_sec=1200, reason="轮查")` 一次，就变成两条、
    两个 20 分钟的报醒错开半分钟，而"轮查"这件事按定义同一时刻只有一条在跑。

    `interval_sec` 只用于正文里念间隔，不改任何计时行为（间隔的真身是
    `PATROL_INTERVAL_SEC`，挂表那一处读的就是它）。

    判据的"反真空"要能把它换成空串：`fire_due` 按名字调本函数（模块级），
    打桩之后到点那条正文里四步必须一句不剩 —— 于是"正文里真有 SOP"这件事是机器证明的，
    不是读代码读出来的。
    """
    every = human_sec(interval_sec if interval_sec is not None else PATROL_INTERVAL_SEC)
    return (
        f"【轮查】这是规范动作，不是提醒：按下面四步做完再干别的（每 {every}一次）。\n"
        "① 立刻调 conductor.patrol：一次拿全活跃子代理（在飞 / 待机）、名册绝对编码链、"
        "正在执行的任务、未做完的板项与现在在做哪项、计时器四格。\n"
        "② 对每一个活跃子代理给结论：conductor.patrol_verdict(code, \"pass\") 说「过」，"
        "或 conductor.patrol_verdict(code, \"guide\", text) 给指导意见"
        "（guide 走既有秘书链，正文只到链尾）；那一轮里漏掉任何一个活跃号都算没做完。\n"
        "③ 结完这一轮，才允许做别的（自由行动）。\n"
        "④ 无事可做（要挂机等）时，挂上下一个轮查计时器：框架在挂机那一下自动挂好"
        "（reason 是「轮查」的那一条），不要再手工起第二条。"
    )


def next_patrol(workspace: str | Path) -> dict[str, Any]:
    """下一条还没到的轮查计时器（三态）。

    返回 `{"checked","pending","count","timer_id","due_at","remaining_sec","reason"}`。
    `pending=False` 是"查过了、现在没有轮查计时器"，`checked=False` 是"没查成"——
    挂下一轮那一处按前者决定"该挂"，后者只记一句"不知道"，两者不许折平。

    为什么要有这一格读数（两个读者，一处实现）：

    1. 挂点（`agent_loop._park_gate`）每一拍都要问"已经有一条了吗"；
    2. 挂机的一拍还要用它把睡眠封顶在轮查到点那一刻 —— 业主的口径是"时间到立刻进
       自动审阅工具"，而挂机的一拍最长 `PARK_SLICE_MAX_SEC`（300 秒），不封顶就会
       把"立刻"读成"最多晚 5 分钟"。
    """
    out: dict[str, Any] = {"checked": False, "pending": False, "count": 0, "timer_id": "",
                           "due_at": "", "remaining_sec": None, "reason": ""}
    try:
        rows = [t for t in book(workspace).pending() if is_patrol_timer(t)]
    except (ClockStateError, OSError) as exc:
        out["reason"] = f"计时器簿记读不成：{type(exc).__name__}: {exc}"
        return out
    out["checked"] = True
    out["count"] = len(rows)
    if not rows:
        return out
    rows.sort(key=lambda t: (str(t.due_at or ""), str(t.timer_id or "")))
    head = rows[0]
    out.update(pending=True, timer_id=str(head.timer_id or ""),
               due_at=str(head.due_at or ""), remaining_sec=head.remaining_seconds(now()))
    return out


def start_patrol_timer(workspace: str | Path, *, task_id: str = "", role: str = "",
                       to: str = "self") -> dict[str, Any]:
    """挂下一轮轮查计时器 —— 恰好一条（业主 2026-10-27 傍晚：「无事可做后启动轮查计时」）。

    两条规则，缺一条就会出两种相反的错：

    1. 只有主控（`PATROL_ROLE`）才挂：轮查要执行的动作是 `conductor.patrol` /
       `conductor.patrol_verdict`，那两件只有 M 有；子代理挂一条自己的"轮查"表既没有
       可执行的动作，又会把"无事可做"这个读数搅浑（它会永远有一条计时器在跑）；
    2. 已经有一条 pending 的轮查计时器就不再挂：挂点每一拍都会经过
       （`_park_gate` 的第 ①/④ 两支），不判重的话一分钟能挂出几十条，而"轮查"这件事
       按定义同一时刻只有一条在跑。

    返回 `{"checked","mounted","skipped","timer_id","interval_sec","remaining_sec","reason"}`。
    `mounted=False` 时 `skipped` 说清为什么（`role` / `already` / `unreadable` / `error`）：
    读数要能把"没挂"与"不该挂"分开，否则挂点那一侧只能把三件事写成一句话。

    三态：时钟读不到时 `start_timer` 抛 `ClockUnreadable`，这里折成 `checked=False`
    （不是"已经有一条"）—— 挂点据此知道"这一拍不知道"，下一拍还会再问一次。
    """
    out: dict[str, Any] = {"checked": False, "mounted": False, "skipped": "",
                           "timer_id": "", "interval_sec": float(PATROL_INTERVAL_SEC),
                           "remaining_sec": None, "reason": ""}
    who = str(role or "").strip()
    if who != PATROL_ROLE:
        out.update(checked=True, skipped="role",
                   reason=(f"轮查计时器只挂给主控（{PATROL_ROLE}）："
                           f"这一趟是 {who or '（没有角色）'} ⇒ 不挂"))
        return out
    known = next_patrol(workspace)
    if not known.get("checked"):
        out.update(checked=False, skipped="unreadable",
                   reason=str(known.get("reason") or "计时器簿记读不成 ⇒ 不知道有没有"))
        return out
    if known.get("pending"):
        out.update(checked=True, skipped="already",
                   timer_id=str(known.get("timer_id") or ""),
                   remaining_sec=known.get("remaining_sec"),
                   reason=(f"已经有一条 pending 的轮查计时器 {known.get('timer_id')}"
                           f"（还剩 {human_sec(known.get('remaining_sec')) or '读不到'}）"
                           "⇒ 不再挂第二条"))
        return out
    try:
        timer = start_timer(workspace, reason=PATROL_REASON, after_sec=PATROL_INTERVAL_SEC,
                            to=str(to or "self"), task_id=str(task_id or ""), role=who)
    except ClockUnreadable as exc:
        out.update(checked=False, skipped="unreadable", reason=str(exc))
        return out
    except ClockError as exc:  # 参数/簿记坏掉：照实报，不假装挂上了
        out.update(checked=False, skipped="error",
                   reason=f"{type(exc).__name__}: {exc}")
        return out
    out.update(checked=True, mounted=True, timer_id=str(timer.timer_id or ""),
               remaining_sec=timer.remaining_seconds(now()),
               reason=(f"挂上了下一条轮查计时器 {timer.timer_id}"
                       f"（每 {human_sec(PATROL_INTERVAL_SEC)}一次）"))
    return out
