# -*- coding: utf-8 -*-
"""时钟原生工具：`clock.*` 九件，所有角色都能用，到点同时落 mailbox 项与唤醒标记。

## 为什么时钟必须是系统原生工具（D-53 的业主口径）

业主原话（唯一权威）：

    「对于D53，把时钟做成系统原生工具，让M在派活完后启动计时器（计时器依托时钟实现），
      到点后时钟自动给M发消息检查，检查完成后M再启动计时器。如果其它人要看表
      （看时钟读数）或计时、定闹钟什么的也可以用。总之这是个通用工具。
      时钟只有一个，依附于其上的计时进程可以很多。」

改前的形态：M 派完活之后没有任何"过一会儿回来看看"的动作可用，只能靠外部
按时间叫醒它；而"按时间"这件事在工具面上不可见。本模块把时钟、计时器、闹钟、
周期性巡查做成工具，挂在 `clock.` 这一个组下。

## 业主 2026-10-25 的裁定（计时类任务的申请形状）

    「主时钟是否控制了所有计时类工作？如果不是，请规范所有计时类任务申请的形式为：
      等待时间（或等待谁）+目的（必填），例如M的巡视叫等待20分钟+周期性巡查。」

    「注意：让老的未依赖时钟的计时工具退场，当智能体忘填目的时不报错，只是让它追加目的。
      计时到点后向智能体发送信息"目的+等待时间+时间到"」

于是工具面只认两半：`after_sec`（或闹钟的 `at`）与 `wait_for` 二选一，外加一句目的。
两个都不给、或两个都给 => 受控拒绝并说清只能选一个。目的缺了不再打回重来：照常
受理、读数带 `purpose_missing=true`、其后的读数与到点消息里追问一句，补一句目的走
`clock.timer_purpose`（同一个编号，不是新建一条）。

"计时只有主时钟这一处"：代理可见的工具面里不存在第二个计时入口（判据
`tests/test_clock_governs_all_timed_work.py` 逐个数过），框架内部的等待则全部走
`clock.await_io` / `clock.note_wait` 进同一本账。

## 九件工具

| 工具 | 作用 |
|---|---|
| `clock.now` | 读数：现在几点、这一趟跑了多久、有没有等我的唤醒标记、等待账与普查读数 |
| `clock.timer_start` | 起一次性计时器：`after_sec` 或 `wait_for` 二选一 + 目的 |
| `clock.alarm_start` | 定一次闹钟：到 `at`（ISO 时刻）；可另给 `wait_for`，先到者报醒 |
| `clock.periodic_start` | 起周期性巡查：`every_sec` + 目的（M 的巡视就是这一类） |
| `clock.periodic_stop` | 停一条周期性巡查 |
| `clock.timer_purpose` | 给一条已受理的等待补上目的（同一个编号） |
| `clock.timer_list` | 列出计时器与周期性巡查，并给唤醒标记与等待账读数 |
| `clock.timer_cancel` | 取消一条还没到点的计时器（给 `pd-` 号则停周期性巡查） |
| `clock.wait_any` | 手上没事了：记一条「等待任意计时器返回」的意图，谁先回来都行 |

`clock.wait_any` 是 2026-10-27 第二批加进来的第九件 (业主第三条裁定的后半个动作：「直到它
认为无事可做时，可启动计时器"等待任意计时器返回"」)。改前这个动作只有框架内部入口
`clock.request_wait_any`，模型面上没有这一格；工具只写意图与交回读数，挂机与否的判定仍在
`agent_loop._park_gate` 一处 (工具不做控制流)。

## 程序两件（G1，业主 2026-10-26）

| 工具 | 作用 |
|---|---|
| `program.list` | 我这一趟起的程序还在跑的有哪几个（pid / argv 摘要 / 起于何时 / 已跑多久 / 它那条计时器 id / 那条表的目的） |
| `program.stop` | 停掉我名下的一个（或全部）：先宽限、再真杀，然后按 `outcome="killed"` 收口并唤醒等它的人 |

为什么不叫 `clock.program_list` / `clock.program_stop`（业主原话是"名称你来定"）：
`clock.*` 恰好九件是一条被钉住的判据（`tests/test_clock_governs_all_timed_work.py`
的 `CLOCK_NINE`，写死只读角色 C/H/V 面上也是九件）。程序这两件的轴不是"计时"而是
"我起的进程"：`program.stop` 是 `write_local`，只读角色按副作用就该拿不到它
（`tools/__init__.py` 的 `UNIVERSAL_TOOLS` 不在本批可改范围），挂进 `clock.` 会让那条
"恰好九件"的判据只剩改宽这一条路。分一个组，那条判据原样成立。

业主原话（唯一权威）：`「重点完善子代理杀自己发出去的程序进程的工具（由于计时器监控着那些
程序，我想实现起来不会太难），以及注销前检测的能力」`。两件的分工就是这句话的两半：
`program.list` 是"注销前检测"（交差/销号之前先看自己还有没有程序在跑），
`program.stop` 是"杀自己发出去的那个进程"（计时器那条账一并收口，等它的人被叫醒）。

## 到点消息的格式（业主定死，唯一拼法在 `clock.due_message`）

    时间到：<目的>｜等了 <时长>（起于 <HH:MM:SS>，到于 <HH:MM:SS>）
    巡查时间到：<目的>｜每 <间隔>一次（第 <N> 次）

目的缺了那一趟写"（目的未填）"并在同一句后面追问。三样（目的 / 等待时间 / 时间到）
必须齐，不许只报"到点了"。本模块不另拼一份：`detail`、唤醒标记的 `message` 与
读数里的 `message` 都读同一个落点。

## 到点动作必须是两件一起

D-53 的核心修复是"到点后时钟自动给 M 发消息"。今天 D-52 的 mailbox 投递还没修，
所以到点动作由 `_deliver_due` 一次做两件：

1. 落一条 mailbox 项：`tasks` 表一行 `kind="notice"`、`parent_task_id` 是收件人
   的台账号、`detail` 就是上面那句到点消息。这一件可审计；
2. 置一条唤醒标记：`<工作区>/out/clock/wake.json` 里一条事件，带 `task_id` /
   `timer_id` / `mailbox_item_id` / `message`。这一件让"正在等子的父"能立刻拿到
   一个回合，不依赖还没修的 mailbox 投递。

两件都做、任缺一件都不算投递成功（判据 `tests/test_clock_is_a_native_tool.py`
的第 6 条用打桩分别证明两件都是承重的）。

## 消费端还差哪一步（本模块不改 `agent_loop.py`）

消费端（D-52/D-53 统一接的那一处）需要：在等子代理的等待点上读
`clock.pending_wakes(root, my_task_id)` 或调 `clock.consume_wakes(root, my_task_id)`，
并把"有唤醒"折进它本来就有的唤醒判据。本模块只把落点做好、读口交出去。

## 两根轴为什么这样声明（2026-10-24 按业主裁定改为据实）

业主新裁定（逐字，唯一权威）：「通用能力根本不该出现谁能用这个说法」。
这条裁定把两根轴分开了：副作用轴说"它改不改我们拥有的东西"，可达性轴说
"它是不是通用能力"。此前把两根轴压在一起，代价是这三件写表的工具被声明成
`side_effect="read"` —— 只为让 `for_role` 不把只读角色剥掉。那是谎报：
读到声明的人会以为它们不写表，而 `_deliver_due` 与 `C.start_timer` 都会落盘。

现在的声明据实：

| 工具 | side_effect | 为什么 |
|---|---|---|
| `clock.now` / `clock.timer_list` | `read` | 只读 |
| `clock.timer_start` / `clock.alarm_start` / `clock.periodic_start` | `write_local` | 写 `out/clock` 的状态，到点后落一条 `tasks` notice 行与一条唤醒标记 |
| `clock.periodic_stop` / `clock.timer_cancel` / `clock.timer_purpose` / `clock.wait_any` | `write_local` | 改 `out/clock` 的状态（停掉/补目的/记一条等待意图之后不该再有旧的报醒语义） |

可达性不再靠声明绕过去：它们登记在 `tools.UNIVERSAL_TOOLS`（通用能力的受控集合），
`ToolRegistry.for_role` 对通用工具不按副作用等级剥离。它们也不进
`READONLY_CALL_EXCEPTIONS` —— 通用能力不是"例外"。

缺口（曾经据实登记，2026-10-25 晚已补上）：`clock.periodic_start` / `clock.periodic_stop` /
`clock.timer_purpose` 三件一度没登记进 `tools.UNIVERSAL_TOOLS`，于是只读角色 C/H/V 的
工具面上只有五件（"声明了通用、平台按副作用剥掉"的可见缺口）。业主放行后已在
`tools/__init__.py` 的 `UNIVERSAL_TOOLS` 里补了三条登记，现在九件对全部十一个角色都发；
判据是 `tests/test_clock_governs_all_timed_work.py` 的第 17 条（含"写集不越出
`BOOKKEEPING_TABLES`"那一条硬约束）。

硬约束（不许通用集合变成后门）：`UNIVERSAL_TOOLS` 里每件工具登记的写集只许落在
通信/簿记类表上（今天只有 `tasks`；事件流与 `out/clock` 是文件，不在表里）。
写 `statements` / `claims` / `literature` / `relations` / `documents` 这类知识表
⇒ 判据直接红，且它不会被发给只读角色。将来如果时钟改成写领域表，
那就不再是通用能力，必须撤出 `UNIVERSAL_TOOLS` 并走 FC-27 人审。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import clock as C
from .. import schema as S
from ..conductor import clock_waiters, current_caller_role, current_task_id
from . import READ_ONLY_ROLES
from .base import ToolRegistry, ToolResult, fail, ok, tool

#: 九件工具挂给全部角色 + 主控。业主口径是"通用工具"，不是某一角色的专有能力。
_ROLES_ALL: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: 写工具能挂的角色面：只读角色（C/H/V）不声明 —— 与 `conductor_tools.conductor_broadcast`
#: 同一个口径。声明了再让 `for_role` 剥掉会被 `cli tools` 报成"声明错误"
#: （`role_filter_notes` 非空），而那份说明里逐字写着"行为上已被拦下，但声明本身应改"。
#: 只读角色本来也起不了程序（它们没有写工具），所以"停程序"对它们无处可用。
_ROLES_WRITE: tuple[str, ...] = tuple(r for r in S.ROLES if r not in READ_ONLY_ROLES) \
    + (S.CONDUCTOR_ROLE,)

#: 到点消息的逐字前缀：一次性的是 `时间到：`，周期性巡查的是 `巡查时间到：`。
#:
#: 判据按它认出"这是一条到点项"；两个字面量都在 `clock.due_message` 里，这里只是
#: 给读的人与判据一个稳定的常量（不许在别处再拼一份前缀）。
#:
#: 2026-10-27（L2）：轮查计时器那一档还有第三个抬头 `clock.PATROL_DUE_HEAD`
#: （逐字「轮查到点：」）。它刻意不进这张元组，理由与它为什么换抬头是同一条 ——
#: 业主要那一档"不是一句提醒，而是一套动作"，于是它的正文根本不以"到点"二字开头；
#: 把它并进来会让"按前缀认到点项"这条读法把一段 SOP 当成一条通知。
#: 认轮查那一档的判据只有一处：`clock.is_patrol_timer`（读 `reason` 那一格）。
DUE_PREFIX: str = "时间到："
PATROL_PREFIX: str = "巡查时间到："
DUE_PREFIXES: tuple[str, ...] = (DUE_PREFIX, PATROL_PREFIX)

#: 台账里算"还没收口"的任务状态（其余状态都算收口）。
OPEN_TASK_STATUSES: tuple[str, ...] = ("pending", "running")

#: 板项轴里算"已经收口"的那两格（`ITEM_STATES` 的另外三格还在等人）。
CLOSED_ITEM_STATES: tuple[str, ...] = ("done", "block")

#: 工作区 -> 到点投递需要的运行期绑定（store / conductor）。
#:
#: 为什么是运行期字典而不是写进 `state.json`：Store 与 Conductor 都是进程内对象，
#: 落盘没有意义。重启之后由下一次工具调用重新绑定；没绑定时的到点计时器会以
#: `DueDeferred` 保持 pending（不丢、不误标成已投递）。
_BINDINGS: dict[str, dict[str, Any]] = {}


def _resolve_root(root: Any, store: Any) -> Path:
    """工作区根：显式 root 优先，其次 store.root，最后进程 CWD。"""
    if root:
        return Path(root).resolve()
    base = getattr(store, "root", None)
    if base:
        return Path(base).resolve()
    return Path.cwd().resolve()


def _bind(workspace: str | Path, store: Any, conductor: Any = None) -> None:
    _BINDINGS[str(Path(workspace).resolve())] = {"store": store, "conductor": conductor}


def bind_workspace(workspace: str | Path, store: Any, conductor: Any = None) -> None:
    """公开的绑定口：把"这个工作区的 store / conductor"接上。

    谁用：`conductor.arm_child_waiter`（派活时自动起"等这条子代理"的计时器那一处）。
    它必须绑上，否则"等谁"的读口查不成台账/名册 ⇒ 目的自动填那一格只能落到
    `unavailable`（读数里看得见，但那就不是业主要的那个形了）。
    `clock_tools` 在装配期本来就会绑一次；这里是给"装配之前就派活"的那条路补的。
    """
    _bind(workspace, store, conductor)


def _binding(workspace: str | Path) -> dict[str, Any]:
    return _BINDINGS.get(str(Path(workspace).resolve()), {})


def _find_task(store: Any, task_id: str) -> dict[str, Any] | None:
    """台账里按台账号找一行。读不成 => 抛（那是"没查成"，不是"没有这一行"）。"""
    if store is None or not str(task_id or "").strip():
        return None
    try:
        rows = store.rows("tasks")
    except Exception as exc:  # noqa: BLE001
        raise C.ClockStateError(f"tasks 台账读不成：{type(exc).__name__}: {exc}") from None
    want = str(task_id)
    return next((r for r in rows if str(r.get("task_id") or "") == want), None)


def _recipient(store: Any, to: Any) -> dict[str, Any]:
    """解析收件人：`to="self"` 取调用上下文，否则按台账号查台账。"""
    target = str(to or "self").strip()
    if target in ("self", ""):
        task_id = str(current_task_id() or "").strip()
        if not task_id:
            raise C.ClockNotFound(
                "to=\"self\" 但调用上下文里没有台账号 —— 不知道到点该叫醒谁"
                "（这不是'没有任务'，是'没有身份'）")
        row = _find_task(store, task_id)
        role = str(current_caller_role() or "")
        if not role and row is not None:
            role = str(row.get("role") or "")
        if not role:
            raise C.ClockNotFound(
                f"to=\"self\" 解析到 {task_id}，但读不出它的角色 —— "
                "到点项需要 role 才能落成一行 tasks（不许猜一个角色）")
        depth = int((row or {}).get("depth") or 1)
        return {"task_id": task_id, "role": role, "depth": depth}
    row = _find_task(store, target)
    if row is None:
        raise C.ClockNotFound(f"台账里没有 {target} 这一行 —— 到点没有收件人")
    role = str(row.get("role") or "")
    if not role:
        raise C.ClockNotFound(f"{target} 那一行没有角色 —— 到点项不知道开给谁")
    return {"task_id": target, "role": role, "depth": int(row.get("depth") or 1)}


def _mailbox_detail(timer: C.Timer) -> str:
    """落进 `tasks.detail` 的那句话：就是 `clock.due_message` 的产物。

    为什么不在这里再拼一份：到点的三样（目的 / 等待时长 / 时间到）在业主那里是
    定死的格式，唤醒标记的 `message`、`clock.timer_list` 的 `message` 与这里的
    `detail` 必须是同一句；各拼一份迟早会漂，而漂了没有任何判据会红。
    """
    body = str(timer.message or "").strip()
    if body:
        return body
    # 兜底：老台账里的行没有 `message` 这一格（加这一格之前落的盘）。
    return C.due_message(purpose=timer.purpose, waited_sec=timer.waited_seconds(),
                         created_at=timer.created_at,
                         fired_at=timer.fired_at or None)


# ---------------------------------------------------------------- 等谁的读口


def _task_closed(row: Mapping[str, Any]) -> tuple[bool, str]:
    """台账里这一行收口了没有。三态留给调用方（这里只答"是/否 + 为什么"）。"""
    status = str(row.get("status") or "")
    item = str(row.get("item_state") or "")
    ended = str(row.get("ended_at") or "")
    if item and item in CLOSED_ITEM_STATES:
        return True, f"板项已收口（item_state={item}）"
    if status and status not in OPEN_TASK_STATUSES:
        return True, f"任务已收口（status={status}）"
    if ended:
        return True, f"任务已收口（ended_at={ended}）"
    return False, f"还在跑（status={status or '未填'}，item_state={item or '未填'}）"


def _find_task_row(store: Any, task_id: str) -> Mapping[str, Any] | None:
    for row in store.rows("tasks"):
        if str(row.get("task_id") or "") == str(task_id):
            return row
    return None


def _roster_task_id(root: Path, name: str) -> tuple[str, str, str]:
    """名册名 -> 它当前那件活的台账号。返回 `(task_id, 名册主人, 理由)`。

    读的是名册与对照表两份盘上事实（`secretary.roster_*_path` 的唯一落点），折叠
    用秘书自己的折叠函数 —— 本模块不复制那份折叠逻辑（`FC-03`：同一件事不许两份
    实现）。这里刻意不构造 `Secretary` 实例：探针在每次到点判定时都会跑，构造一个
    秘书会连带开日志/装配，代价与副作用都不该落在一次读数上。
    """
    from .. import jsonlfile as JF
    from .. import secretary as SEC

    owners, why = SEC.roster_owners(root)
    if not owners:
        return "", "", why or "还没有人派过活（名册目录是空的）"
    for owner in owners:
        for path, fold in ((SEC.roster_index_path(root, owner), SEC._fold_index),
                           (SEC.roster_path(root, owner), SEC._fold_roster)):
            try:
                rows, _bad = JF.read_jsonl(path)
            except Exception:  # noqa: BLE001 - 一份读不成不该判成"没有这个名字"
                continue
            for item in fold(rows):
                if str(item.get("name") or "") != str(name):
                    continue
                task_id = str(item.get("task_id") or "")
                if task_id:
                    return task_id, str(owner), ""
                return "", str(owner), f"名册里有 {name}，但它名下还没有活（task_id 为空）"
    return "", "", f"名册里没有 {name} 这个名字（找过 {len(owners)} 份名册）"


def _roster_task_text(root: Path, task_id: str) -> str:
    """名册里"这件活"那一行的 task 原文（业主 2026-10-27：目的自动用它填）。

    为什么按 `task_id` 找而不是按名字：`wait_for` 的三种写法里 `task:<号>` 是最常用
    的那一种，而名册的对照表（`<父>-index.jsonl`）每一行都带着 `task_id` 与
    `task_text`（写侧在 `Secretary.roster_add` 里落的）。找不到就回空串 ——
    空串只表示"名册里没有这件活的原文"，不表示"它没有 task"。
    """
    from .. import jsonlfile as JF
    from .. import secretary as SEC

    owners, _why = SEC.roster_owners(root)
    want = str(task_id or "")
    if not want:
        return ""
    for owner in owners:
        for path, fold in ((SEC.roster_index_path(root, owner), SEC._fold_index),
                           (SEC.roster_path(root, owner), SEC._fold_roster)):
            try:
                rows, _bad = JF.read_jsonl(path)
            except Exception:  # noqa: BLE001 - 一份读不成不该判成"没有原文"
                continue
            for item in fold(rows):
                if str(item.get("task_id") or "") != want:
                    continue
                text = str(item.get("task_text") or "")
                if text:
                    return text
    return ""


def _target_probe(workspace: str, kind: str, ref: str) -> dict[str, Any]:
    """等谁的读口（装配期由 `register` 接进 `clock.set_target_probe`）。

    六格三态（见 `clock.set_target_probe`）：
    `checked` 查成没查成、`found` 有没有这个东西、`closed` 收口没有、
    `resolved` 解析成的对象、`why` 理由、`task_text` 被等对象那一行的 task 原文
    （业主 2026-10-27：等子代理的目的自动用它填）。
    """
    root = Path(workspace)
    out: dict[str, Any] = {"checked": False, "found": False, "closed": False,
                           "resolved": f"{kind}:{ref}", "why": "", "task_text": ""}
    if kind == "task":
        store = _binding(workspace).get("store")
        if store is None:
            out["why"] = "这个工作区没有绑定 store => 台账读不成"
            return out
        try:
            row = _find_task_row(store, ref)
        except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
            out["why"] = f"tasks 台账读不成：{type(exc).__name__}: {exc}"
            return out
        out["task_text"] = _roster_task_text(root, str(ref))
        out["checked"] = True
        if row is None:
            out["why"] = f"tasks 台账里没有 {ref} 这一行"
            return out
        out["found"] = True
        closed, why = _task_closed(row)
        out["closed"] = closed
        out["why"] = why
        return out
    # kind == "agent"：名册名先解析成台账号；解析不到再看它是不是一个角色名
    if str(ref) in _ROLES_ALL:
        store = _binding(workspace).get("store")
        if store is None:
            out["why"] = "这个工作区没有绑定 store => 台账读不成"
            return out
        try:
            rows = [r for r in store.rows("tasks") if str(r.get("role") or "") == str(ref)]
        except Exception as exc:  # noqa: BLE001
            out["why"] = f"tasks 台账读不成：{type(exc).__name__}: {exc}"
            return out
        out["checked"] = True
        out["found"] = True
        out["resolved"] = f"agent:{ref}"
        alive = [r for r in rows if not _task_closed(r)[0]]
        out["closed"] = not alive
        out["why"] = (f"角色 {ref} 还有 {len(alive)} 件没收口" if alive
                      else f"角色 {ref} 名下没有未收口的活")
        if alive:
            out["task_text"] = _roster_task_text(root, str(alive[-1].get("task_id") or ""))
        return out
    task_id, owner, why = _roster_task_id(root, str(ref))
    if not task_id:
        out["checked"] = True
        out["why"] = why
        return out
    out["resolved"] = f"task:{task_id}"
    out["task_text"] = _roster_task_text(root, task_id)
    store = _binding(workspace).get("store")
    if store is None:
        out["why"] = "这个工作区没有绑定 store => 台账读不成"
        return out
    try:
        row = _find_task_row(store, task_id)
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"tasks 台账读不成：{type(exc).__name__}: {exc}"
        return out
    out["checked"] = True
    if row is None:
        out["why"] = f"名册名 {ref} 解析到 {task_id}（名册主人 {owner}），但台账里没有这一行"
        return out
    out["found"] = True
    closed, why2 = _task_closed(row)
    out["closed"] = closed
    out["why"] = f"{ref} → {task_id}：{why2}"
    return out


# ---------------------------------------------------------------- 异常清单的读口
#
# 业主 2026-10-26（逐字）：「这个是M定期巡查需要特别注意的异常行为，M可通过发送指导意见干预」。
#
# 这一段把"当拍现算的异常清单"从账上读出来，交给 `clock.patrol_text` 拼进巡查报醒。
# 三条纪律：
#
# 1. 复用不复制：静默与停滞两类只用 `conductor.agent_state`（经 `retire_integrity` 那份
#    唯一实现一次算完整棵树，`stalled` / `stalled_sec` 就是它那两格），未消板项只用
#    `Conductor.open_items_by_parent`（`open_items_of(tid)` 就是它按父取的那一格），
#    不在这里写第二份判据；
# 2. 三态：每一类各有 `checked` / `reason`，查不成的写"条数读不到"，绝不折成 0；
# 3. 停滞不另定阈值：阈值与"最近一步"都在 `agent_state` 那一侧（`STALLED_AFTER_SEC` /
#    `out/steps/<台账号>.json`），这里只把它的 `stalled_sec` 与阈值一起念出来。


def _borrowed_conductor(store: Any) -> Any:
    """借这个工作区"已经存在"的主控实例；没有就 `None`（绝不顺手建一个空壳）。"""
    try:
        from .conductor_tools import cached_conductor

        return cached_conductor(store)
    except Exception:  # noqa: BLE001 - 借不到就按"没有主控"如实报
        return None


def _stalled_cell(nodes: Sequence[Mapping[str, Any]],
                  wait: Mapping[str, Any]) -> dict[str, Any]:
    """① 停滞子：直接读 `retire_integrity` 节点上那两格（`stalled` / `stalled_sec`）。

    判据本体只有一处：`conductor.agent_state`（经 `retire_integrity` 的 `agent_states`
    一次算完整棵树），输入是 `out/steps/<台账号>.json` 那一刻与阈值
    `conductor.STALLED_AFTER_SEC`。这里不写第二份 —— 不在 clock 里另算一遍"最近一步
    多久以前"，也不自己定一个 N。

    三态：步进落痕读不成（`wait["stall_checked"]` 为假）=> 这一格 `checked=False`
    （"判不了停滞"），绝不折成 0（0 说的是"查过了，一个停滞的都没有"）。
    """
    if not wait.get("stall_checked"):
        return {"checked": False, "count": None, "rows": [],
                "reason": str(wait.get("stall_reason")
                              or "步进落痕读不成 => 停滞判不了（不是「没有停滞」）")}
    try:
        threshold = float(wait.get("stall_threshold_sec") or 0.0) or None
    except (TypeError, ValueError):
        threshold = None
    beats = dict(wait.get("stall_by_task") or {})
    rows: list[dict[str, Any]] = []
    for node in nodes:
        if not node.get("stalled"):
            continue
        tid = str(node.get("task_id") or "")
        beat = dict(beats.get(tid) or {})
        rows.append({"task_id": tid, "role": str(node.get("role") or ""),
                     "status": str(node.get("status") or ""),
                     "stalled_sec": node.get("stalled_sec"),
                     "last_step_at": str(beat.get("at") or ""),
                     "last_step_no": beat.get("step")})
    return {"checked": True, "count": len(rows), "rows": rows, "reason": "",
            "threshold_sec": threshold}


def _open_items_cell(box: Any, tree: Mapping[str, Any],
                     root_task_id: str) -> dict[str, Any]:
    """③ 未消板项：这一支名下的板项行里 `item_state != done` 的条数，按 expect 分两档。"""
    try:
        by_parent = dict(box.open_items_by_parent())
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        return {"checked": False, "count": None, "ack": None, "work": None,
                "rows": [], "reason": f"未消板项读不成：{type(exc).__name__}: {exc}"}
    mine = {str(root_task_id or "")}
    for key in ("nodes", "dirty"):
        for node in tree.get(key) or ():
            tid = str((node or {}).get("task_id") or "")
            if tid:
                mine.add(tid)
    rows: list[dict[str, Any]] = []
    for parent, items in by_parent.items():
        if str(parent or "") not in mine:
            continue
        for item in items or ():
            item = dict(item or {})
            rows.append({"task_id": str(item.get("task_id") or ""),
                         "expects": str(item.get("expects") or ""),
                         "item_state": str(item.get("item_state") or ""),
                         "kind": str(item.get("kind") or "")})
    ack = sum(1 for r in rows if r["expects"] == "ack")
    work = sum(1 for r in rows if r["expects"] == "work")
    return {"checked": True, "count": len(rows), "ack": ack, "work": work,
            "other": len(rows) - ack - work, "rows": rows, "reason": ""}


def _refusal_cell(root: Path) -> dict[str, Any]:
    """④ 被拦的结项原因：这一段工作区里最近一次 `final_refused` 的拒信首句。

    读的是会话记录（唯一落点：`agent_loop` 在 `shape == "final"` 那一支把
    `{"final_refused": {...}}` 落进这一步的结果，并可能以 `stop_reason="final_refused"`
    收这一趟）。`count` 是这一段里被拦过的总次数，`rows` 只放最近那一条（报醒要的是
    "最近一次"和它的首句，不是整份拒信）。
    """
    from .. import sessions as SS

    try:
        sids = [str(x.get("sid") or "") for x in SS.list_sessions(root)]
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        return {"checked": False, "count": None, "rows": [],
                "reason": f"会话目录读不成：{type(exc).__name__}: {exc}"}
    if not [s for s in sids if s]:
        return {"checked": True, "count": 0, "rows": [],
                "reason": "这一段工作区还没有会话记录 => 没被拦过（查过了）"}
    hits: list[dict[str, Any]] = []
    bad = 0
    for sid in sids:
        if not sid:
            continue
        events, problems = SS.read_session(root, sid=sid)
        bad += len(problems)
        for event in events:
            kind = str(event.get("kind") or "")
            stamp = str(event.get("ts") or "")
            if kind == "agent_step":
                result = event.get("result")
                result = dict(result) if isinstance(result, Mapping) else {}
                gate = result.get("final_refused")
                if isinstance(gate, Mapping):
                    hits.append({"kind": "final_refused",
                                 "text": str(gate.get("why") or result.get("why") or ""),
                                 "at": stamp,
                                 "task_id": str(gate.get("root") or "")})
            elif kind == "agent_run_end" \
                    and str(event.get("stop_reason") or "") == "final_refused":
                notes = [str(x) for x in (event.get("notes") or ()) if str(x or "").strip()]
                text = next((n for n in notes if "还没销号" in n), notes[0] if notes else "")
                hits.append({"kind": "final_refused", "text": text, "at": stamp,
                             "task_id": str(event.get("task_id") or "")})
    if bad and not hits:
        return {"checked": False, "count": None, "rows": [],
                "reason": f"会话有 {bad} 行读不出来、且没读到任何拒信"}
    if not hits:
        return {"checked": True, "count": 0, "rows": [], "reason": ""}
    hits.sort(key=lambda r: str(r.get("at") or ""))
    latest = dict(hits[-1])
    latest["text"] = str(latest.get("text") or "")
    latest["occurrences"] = len(hits)
    return {"checked": True, "count": len(hits), "rows": [latest], "reason": ""}


def _patrol_probe(workspace: str, task_id: str = "") -> dict[str, Any]:
    """`clock.set_patrol_probe` 的读口：当拍现算的四类异常（装配期由 `register` 接上）。

    口径与三态：

    - 没有 store / 没有主控实例 / 名下的树读不成 => 整份 `checked=false` 加理由
      （报醒会写"异常清单没查成"，绝不写"本轮无异常"）；
    - 每一类各自带 `checked` / `count` / `rows` / `reason`（`open_items` 另带 ack / work）；
    - ② 静默未销号的子取 `retire_integrity` 的 `nodes` 里 `state == "silent"` 的那些：
      `retire_integrity` 的 `nodes` 按定义就是"还在册"（已销号的落 `dirty`），所以
      "不是 retired"这一条由它保证，这里不另判一次。
    """
    root = Path(str(workspace))
    reading = C.now()
    stamp = C.iso(reading.wall) if reading.wall is not None else ""
    blank: dict[str, Any] = {"checked": False, "count": None, "rows": [], "reason": ""}
    out: dict[str, Any] = {"checked": False, "reason": "", "at": stamp, "task_id": str(task_id),
                           "stalled": dict(blank), "silent": dict(blank),
                           "open_items": {**blank, "ack": None, "work": None},
                           "refusals": dict(blank)}
    # ④ 与台账无关（它读会话），先读：台账坏了也不该让这一格跟着变成"没有"。
    out["refusals"] = _refusal_cell(root)
    store = _binding(workspace).get("store")
    if store is None:
        out["reason"] = "这个工作区没有绑定 store => 台账读不成（不许读成「本轮无异常」）"
        return out
    box = _binding(workspace).get("conductor") or _borrowed_conductor(store)
    if box is None:
        out["reason"] = ("没有主控实例 => 名下的树、未消板项与销号读数都读不了"
                         "（这不是「本轮无异常」）")
        return out
    me = str(task_id or "")
    if not me:
        out["reason"] = "这条巡查没有台账号 => 不知道要看哪一棵树（不猜）"
        return out
    try:
        tree = box.retire_integrity(me)
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        out["reason"] = f"名下的树没读成：{type(exc).__name__}: {exc}"
        return out
    if not tree.get("checked"):
        out["reason"] = f"名下的树没读成（{str(tree.get('reason') or '没给理由')}）"
        return out
    nodes = [dict(n) for n in (tree.get("nodes") or ()) if isinstance(n, Mapping)]
    silent_rows = [{"task_id": str(n.get("task_id") or ""),
                    "role": str(n.get("role") or ""),
                    "status": str(n.get("status") or ""),
                    "why": "无工作、无计时器、无活跃子，却还留在册上"}
                   for n in nodes if str(n.get("state") or "") == "silent"]
    out["silent"] = {"checked": True, "count": len(silent_rows), "rows": silent_rows,
                     "reason": ""}
    # 停滞那一格要的那份读数是 `clock_waiters` 里的 `stall_*`（与 `retire_integrity`
    # 同一次三态的三个输入之一）。再读一次是刻意的：它带 `stall_checked`（三态位），
    # 而 `retire_integrity` 的节点上只有结论、没有"这一次判没判得成"。
    try:
        wait = clock_waiters(root)
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        wait = {"stall_checked": False,
                "stall_reason": f"时钟/步进落痕读数抛了 {type(exc).__name__}: {exc}"}
    out["stalled"] = _stalled_cell(nodes, wait)
    out["open_items"] = _open_items_cell(box, tree, me)
    out["checked"] = True
    return out


def _patrol_reading(workspace: str | Path, *, task_id: str = "") -> dict[str, Any]:
    """`clock.periodic_start` 交回去的那一格：这一条巡查的报醒会带什么（含一份样例文本）。

    为什么起表时就要给：M 只有在起表那一刻看得见"到点那一条会带哪几类清单"，才谈得上
    判断这条巡查值不值得一直跳。三态与 `clock.patrol_anomalies` 同源（同一份读数）。
    """
    got = C.patrol_anomalies(workspace, task_id=task_id)
    counts: dict[str, Any] = {}
    for key in ("stalled", "silent", "open_items", "refusals"):
        cell = got.get(key) if isinstance(got.get(key), Mapping) else {}
        counts[key] = {"checked": bool(cell.get("checked")),
                       "count": cell.get("count")}
    return {"checked": bool(got.get("checked")),
            "reason": str(got.get("reason") or ""),
            "at": str(got.get("at") or ""),
            "counts": counts,
            "wake_sample": C.patrol_section(workspace, task_id=task_id, anomalies=got)}


def _open_mailbox_item(store: Any, timer: C.Timer, recipient: Mapping[str, Any],
                       *, conductor: Any = None) -> str:
    """落一条到点项（`tasks` 表一行 notice），返回它的 task_id。

    优先复用 Conductor 的 `open_item`（板项的唯一开项入口，含取号与全字段落盘）；
    主控不在手上时退到 `_write_mailbox_row`。为什么不去 `conductor_for(store)`
    顺手建一个：`cached_conductor` 的 docstring 逐字写着"绝不顺手建一个" ——
    先在装配之前叫它一次，后来的接线会按缓存静默复用到那个空壳。
    """
    if store is None:
        raise C.DueDeferred("没有 store => 到点项写不进 tasks 表")
    detail = _mailbox_detail(timer)
    summary = detail[:200]
    depth = int(recipient.get("depth") or 1) + 1
    box = conductor
    if box is None:
        # 只借"已经存在"的那一个；不存在就走直写，不建空壳。
        try:
            from .conductor_tools import cached_conductor

            box = cached_conductor(store)
        except Exception:  # noqa: BLE001 - 借不到就走下面那条路
            box = None
    if box is not None:
        item_id = box.open_item(
            kind="notice", role=str(recipient.get("role") or ""), expects="ack",
            action="notice", summary=summary, called_by="clock",
            parent_task_id=str(recipient.get("task_id") or ""),
            depth=depth, input_key=f"clock:{timer.timer_id}",
        )
        box.set_item_detail(item_id, detail)
        return str(item_id)
    return _write_mailbox_row(store, timer, recipient, detail=detail, depth=depth)


def _write_mailbox_row(store: Any, timer: C.Timer, recipient: Mapping[str, Any],
                       *, detail: str, depth: int) -> str:
    """直写 `tasks` 表一行 notice（没有 Conductor 时的退路）。

    与 `Conductor._write_new_row` 同一纪律：取号与写行在同一个 `store.tx` 临界区里
    完成，落盘行用 `Task.to_dict()` 补齐到全字段（I-9 的键序口径在这里也成立）。
    """
    from ..interactions import next_prefixed_id

    row = {
        "task_id": "",
        "role": str(recipient.get("role") or ""),
        "action": "notice",
        "called_by": "clock",
        "parent_task_id": str(recipient.get("task_id") or ""),
        "depth": max(1, int(depth)),
        "input_key": f"clock:{timer.timer_id}",
        "status": "pending",
        "outcome": None,
        "refusal_reason": None,
        "instance": "",
        "detail": detail,
        "error": None,
        "started_at": "",
        "ended_at": None,
        "tokens": 0,
        "usd": 0.0,
        "artifacts": [],
        "inputs": [],
        "kind": "notice",
        "expects": "ack",
        "item_state": "queued",
        "item_close": "",
        "seen_by": "",
        "seen_step": None,
        "keep_alive": False,
    }
    with store.tx("tasks", actor="clock", note="clock:fired") as tx:
        row["task_id"] = next_prefixed_id(tx.rows("tasks"), "task_id", "t")
        task = S.Task(
            **{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}
        )
        task.validate()
        tx.upsert("tasks", task.to_dict(), note="clock:fired")
    return str(row["task_id"])


def _record_wake(workspace: str | Path, timer: C.Timer,
                 mailbox_item_id: str) -> dict[str, Any]:
    """置一条唤醒标记（转发 `clock.record_wake`；判据在它上面打桩）。"""
    return C.record_wake(workspace, timer, mailbox_item_id=mailbox_item_id)


def _deliver_due(timer: C.Timer) -> dict[str, Any]:
    """到点动作：同时落 mailbox 项与唤醒标记。返回 receipt（由 `fire_due` 落盘）。

    两件刻意分开 try：一件失败不该把另一件也吞掉。两件的错误都写进 `note`，
    `fire_due` 仍把计时器标成 fired —— "到点这一刻"是已经发生的事实，失败的
    那一件必须留在审计里，而不是靠重复触发去补（那会产生重复的 mailbox 项）。
    """
    workspace = timer.workspace
    binding = _binding(workspace)
    store = binding.get("store")
    if store is None:
        raise C.DueDeferred(
            f"工作区 {workspace} 没有绑定 store => 到点项写不进台账（计时器保持 pending）")
    try:
        recipient = _recipient(store, timer.task_id)
    except C.ClockError as exc:
        raise C.DueDeferred(f"到点收件人解析不了：{exc}") from None
    mailbox_item_id = ""
    mailbox_error = ""
    try:
        mailbox_item_id = _open_mailbox_item(
            store, timer, recipient, conductor=binding.get("conductor"))
    except Exception as exc:  # noqa: BLE001 - 一件失败不带走另一件
        mailbox_error = f"{type(exc).__name__}: {exc}"
    wake: Mapping[str, Any] = {}
    wake_error = ""
    try:
        wake = _record_wake(workspace, timer, mailbox_item_id)
    except Exception as exc:  # noqa: BLE001
        wake_error = f"{type(exc).__name__}: {exc}"
    note_bits = [f"mailbox_item_id={mailbox_item_id or '（空）'}"]
    if wake:
        note_bits.append(f"wake_id={wake.get('wake_id') or ''}")
    if mailbox_error:
        note_bits.append(f"mailbox 失败：{mailbox_error}")
    if wake_error:
        note_bits.append(f"wake 失败：{wake_error}")
    return {"mailbox_item_id": mailbox_item_id,
            "wake_id": str(wake.get("wake_id") or "") if wake else "",
            "note": "；".join(note_bits)}


# ---------------------------------------------------------------- 读数辅助


def _elapsed(store: Any, task_id: str) -> tuple[float | None, str]:
    """这一趟跑了多久。三态：读不到 => (None, "unknown")。

    优先用台账里这一行的 `started_at`（"这一趟"的起点）；没有这一行时退到
    本进程启动那一刻（`clock.process_started()`）。两者都读不到 => unknown。
    """
    reading = C.now()
    if reading.wall is None:
        return None, "unknown"
    row: Mapping[str, Any] = {}
    if store and task_id:
        try:
            row = _find_task(store, task_id) or {}
        except C.ClockStateError:
            # 台账读不成时只影响 elapsed 这一格（它是读数，不是结论）；
            # 时钟本身仍然可用，不许把整个 clock.now 判成失败。
            row = {}
    started = str(row.get("started_at") or "")
    if started:
        try:
            start = datetime.fromisoformat(started.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=reading.wall.tzinfo)
            return max(0.0, (reading.wall - start.astimezone(reading.wall.tzinfo)).total_seconds()), "task"
        except ValueError:
            return None, "unparsed"
    process = C.process_started()
    if process.wall is not None:
        return max(0.0, (reading.wall - process.wall).total_seconds()), "process"
    return None, "unknown"


def _after_seconds(timer: C.Timer) -> float | None:
    """起表时"多久之后"的读数：计时器直接用 after_sec；闹钟按 created -> due 算。

    等谁的那一条没有钟点（`due_at` 为空）=> `None`（不是 0：等的是对象收口）。
    """
    if timer.after_sec is not None:
        return float(timer.after_sec)
    if not timer.due_at:
        return None
    try:
        due = C.parse_iso(timer.due_at)
        created = C.parse_iso(timer.created_at)
        return (due - created).total_seconds()
    except Exception:  # noqa: BLE001 - 回显读不出来不该让起表失败
        return None


def _running_count(store: Any) -> int | None:
    """正在跑的任务行数（`status="running"`）。读不成 => `None`（不是 0）。

    它是业主"活跃 = 正在跑 + 挂机"那一格的左半边；右半边是 `clock.waiters`。两格
    分开列，因为"在跑"与"挂着等"是两件事：后者不许被当成卡住。
    """
    if store is None:
        return None
    try:
        return sum(1 for r in store.rows("tasks")
                   if str(r.get("status") or "") == "running")
    except Exception:  # noqa: BLE001 - 读不成是"没查成"，留给 active 变 None
        return None


def _purpose_reading(timer: C.Timer) -> dict[str, Any]:
    """目的那一格的三样读数（所有起表类工具共用一份）。

    `purpose_missing` 是本轮裁定点名的读数；`purpose_prompt` 是"下一次给它的话里
    追加的那一句"（工具结果里就带着，下一次 `clock.now` / `timer_list` 还会再带）。
    """
    return {
        "purpose": timer.purpose,
        "purpose_missing": timer.purpose_missing,
        "purpose_prompt": C.PURPOSE_PROMPT if timer.purpose_missing else "",
    }


def _start_payload(timer: C.Timer) -> dict[str, Any]:
    reading = C.now()
    payload = {
        "timer_id": timer.timer_id,
        "kind": timer.kind,
        "state": timer.state,
        "to": timer.to,
        "task_id": timer.task_id,
        "role": timer.role,
        "reason": timer.reason,
        "after_sec": _after_seconds(timer),
        "due_at": timer.due_at,
        "at": timer.due_at,
        "remaining_sec": timer.remaining_seconds(reading),
        "created_at": timer.created_at,
        "clock_status": reading.status,
        "wait_for": timer.wait_for,
        "wait_for_resolved": timer.wait_for_resolved,
        "wait_state": timer.wait_state,
        "max_wait_sec": timer.max_wait_sec,
        "park_state": timer.park_state,
        "parked_at": timer.parked_at,
        "parked_sec": timer.parked_seconds(reading),
        "parked_steps": int(timer.parked_steps),
        "parked_calls": int(timer.parked_calls),
    }
    payload.update(_purpose_reading(timer))
    return payload


def _periodic_payload(periodic: C.Periodic) -> dict[str, Any]:
    reading = C.now()
    payload = periodic.row(reading)
    payload["purpose_prompt"] = C.PURPOSE_PROMPT if periodic.purpose_missing else ""
    payload["clock_status"] = reading.status
    return payload


# ---------------------------------------------------------------- 九件工具


@tool(
    "clock.now",
    "读系统时钟：现在几点（墙钟 + 单调计数）、这一趟跑了多久、有没有等我消费的唤醒标记、"
    "等待账与'主时钟控制了所有计时类工作没有'的机器读数（waits_outside_clock）。"
    "读不到时 status=unknown、wall/monotonic 都是 null（绝不折成 0）。"
    "所有角色都能用。",
    {"type": "object",
     "properties": {
         "include_wakes": {"type": "boolean",
                           "description": "是否一并读唤醒标记（缺省是）"},
         "include_waits": {"type": "boolean",
                           "description": "是否一并读等待账与原始等待普查（缺省是）"},
     },
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=_ROLES_ALL,
    returns=("{'clock','status','wall','monotonic','source','reason','task_id','role',"
             "'elapsed_sec','elapsed_from','pending_wakes','wakes_checked','wakes_reason',"
             "'waits_checked','waits_reason','waits_outside_clock','waits_outside_where',"
             "'waits_exempt','waits_exempt_count','waits_master_clock_count',"
             "'waits_on_primitives','waits_on_primitives_ungoverned','waits_recorded',"
             "'waits_recorded_sec','covers_all_timed_work','purpose_pending','parked',"
             "'parked_sec','parked_steps','parked_calls','waiters','waiters_checked',"
             "'running','active','observed_events','observed_total',"
             "'programs','programs_checked','programs_outside_clock',"
             "'programs_outside_where','programs_files_scanned'}"),
    tags=("clock", "time", "read"),
)
def clock_now(store: Any, root: Any, *, include_wakes: bool = True,
              include_waits: bool = True) -> ToolResult:
    """读一次时钟。不写任何东西（等待账的落盘是读之后的顺手动作，失败也不影响读数）。"""
    workspace = _resolve_root(root, store)
    reading = C.now()
    task_id = str(current_task_id() or "")
    role = str(current_caller_role() or "")
    elapsed_sec, elapsed_from = _elapsed(store, task_id)
    if include_wakes:
        wakes = C.pending_wakes(workspace, task_id or None)
        wake_count = int(wakes.get("count") or 0) if wakes.get("checked") else 0
        wakes_checked = bool(wakes.get("checked"))
        wakes_reason = str(wakes.get("reason") or "")
    else:
        wake_count, wakes_checked, wakes_reason = 0, False, "include_wakes=false"
    if include_waits:
        cov = C.coverage()
        waits_checked = bool(cov.get("checked"))
        waits_reason = str(cov.get("reason") or "")
        # 顺手把等待账落盘：读一次就有一份可审计的盘上账（写不成不影响读数）。
        C.flush_waits(workspace)
    else:
        cov = {"waits_outside_clock": None, "waits_outside_where": [],
               "waits_exempt": [], "waits_exempt_count": None,
               "waits_on_primitives": None, "waits_on_primitives_ungoverned": None,
               "waits_recorded": None, "waits_recorded_sec": None,
               "covers_all_timed_work": None}
        waits_checked, waits_reason = False, "include_waits=false"
    try:
        purpose_pending = C.timers_missing_purpose(workspace)
    except C.ClockStateError as exc:
        purpose_pending = [{"id": "", "kind": "", "prompt": "",
                            "error": f"还没写目的的待发条目读不成：{exc}"}]
    try:
        park = C.waiters(workspace)
    except C.ClockStateError as exc:
        park = {"checked": False, "waiters": [], "count": 0, "parked": None,
                "woke": None, "cancelled": None, "parked_sec": None,
                "parked_steps": None, "parked_calls": None,
                "reason": str(exc)}
    running = _running_count(store)
    observed = C.observed_events()
    try:
        programs = dict(C.programs(workspace))
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        programs = {"checked": False, "rows": [], "count": 0, "running": 0,
                    "unbooked": [], "reason": f"{type(exc).__name__}: {exc}"}
    return ok({
        "clock": "agentflow.clock",
        "status": reading.status,
        "wall": reading.to_dict()["wall"],
        "monotonic": reading.monotonic,
        "source": reading.source,
        "reason": reading.reason,
        "task_id": task_id,
        "role": role,
        "elapsed_sec": elapsed_sec,
        "elapsed_from": elapsed_from,
        "pending_wakes": wake_count,
        "wakes_checked": wakes_checked,
        "wakes_reason": wakes_reason,
        "waits_checked": waits_checked,
        "waits_reason": waits_reason,
        "waits_outside_clock": cov.get("waits_outside_clock"),
        "waits_outside_where": list(cov.get("waits_outside_where") or []),
        "waits_exempt": list(cov.get("waits_exempt") or []),
        "waits_exempt_count": cov.get("waits_exempt_count"),
        "waits_master_clock_count": cov.get("waits_master_clock_count"),
        "waits_on_primitives": cov.get("waits_on_primitives"),
        "waits_on_primitives_ungoverned": cov.get("waits_on_primitives_ungoverned"),
        "waits_recorded": cov.get("waits_recorded"),
        "waits_recorded_sec": cov.get("waits_recorded_sec"),
        "covers_all_timed_work": cov.get("covers_all_timed_work"),
        "programs_checked": cov.get("programs_checked"),
        "programs_outside_clock": cov.get("programs_outside_clock"),
        "programs_outside_where": list(cov.get("programs_outside_where") or []),
        "programs_files_scanned": cov.get("programs_files_scanned"),
        # 程序计时器的现读（业主 2026-10-27 第一条：「运行一个程序时会自动启动一个
        # 计时器，程序运行完成时计时器会返回」）。这一格是"有程序在跑要看得见"的那个
        # 可见面：`running` > 0 时 rows 里每一条带 program / pid / elapsed_sec / state。
        # 三态：读不成 ⇒ `checked=false`（不是"没有程序在跑"）。
        "programs": {
            "checked": bool(programs.get("checked")),
            "count": int(programs.get("count") or 0),
            "running": int(programs.get("running") or 0),
            "rows": list(programs.get("rows") or ()),
            "unbooked": list(programs.get("unbooked") or ()),
            "reason": str(programs.get("reason") or ""),
        },
        "purpose_pending": purpose_pending,
        "parked": park.get("parked"),
        "parked_sec": park.get("parked_sec"),
        "parked_steps": park.get("parked_steps"),
        "parked_calls": park.get("parked_calls"),
        "waiters": park.get("waiters") or [],
        "waiters_checked": bool(park.get("checked")),
        "running": running,
        "active": (None if running is None or park.get("parked") is None
                   else int(running) + int(park.get("parked") or 0)),
        "observed_events": observed["counts"],
        "observed_total": observed["total"],
    })


@tool(
    "clock.timer_start",
    "起一个一次性计时器：after_sec（多少秒之后）与 wait_for（等谁收口）二选一，外加一句"
    "目的 reason。到点后时钟自动落一条 notice 板项给收件人（detail 是"
    "\"时间到：目的｜等了多久（起于…，到于…）\"），并同时置一条唤醒标记。"
    "不自动重排：检查完成后要再起一次；周期性巡查用 clock.periodic_start。"
    "目的忘了填不报错（读数带 purpose_missing=true 并追问），补一句走 clock.timer_purpose。"
    "所有角色都能用。",
    {"type": "object",
     "properties": {
         "after_sec": {"type": "number", "minimum": 0.001, "maximum": 315360000,
                       "description": "多少秒之后到点（与 wait_for 二选一）"},
         "wait_for": {"type": "string", "minLength": 1, "maxLength": 200,
                      "description": ("等谁：名册名 / 绝对编号（t000012）/ task:<号> / "
                                      "agent:<名>。被等对象收口时报醒（与 after_sec 二选一）")},
         "max_wait_sec": {"type": "number", "minimum": 0.001, "maximum": 315360000,
                          "description": ("等谁的上限：最多等多久（到点也报醒）。只在给了 "
                                          "wait_for 时有意义")},
         "reason": {"type": "string", "maxLength": 500,
                    "description": ("目的（例：等待20分钟+周期性巡查）。缺了不报错，"
                                    "读数会追问；会进到点项的那句话里")},
         "to": {"type": "string",
                "description": "收件人：self（缺省，叫我这一趟）或 tasks 表的台账号"},
     },
     "required": [], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'timer_id','kind','state','to','task_id','role','reason','after_sec',"
             "'due_at','at','remaining_sec','created_at','clock_status','wait_for',"
             "'wait_for_resolved','wait_state','max_wait_sec','park_state','parked_at',"
             "'parked_sec','parked_steps','parked_calls','purpose','purpose_missing',"
             "'purpose_prompt'}"),
    tags=("clock", "timer", "communication"),
)
def clock_timer_start(store: Any, root: Any, conductor: Any,
                      *, after_sec: float | None = None, reason: str = "",
                      wait_for: str = "", max_wait_sec: float | None = None,
                      to: str = "self") -> ToolResult:
    """起计时器。时间与对象都给/都不给 / 读不到时钟 / 收件人不存在 => 受控失败，零写入。

    目的（`reason`）缺了不再拒绝（业主 2026-10-25）：照常受理，读数带
    `purpose_missing=true`，`purpose_prompt` 就是"下一次给它的话里追加的那一句"。
    """
    workspace = _resolve_root(root, store)
    _bind(workspace, store, conductor)
    try:
        recipient = _recipient(store, to)
        timer = C.start_timer(workspace, after_sec=after_sec, reason=reason,
                              wait_for=wait_for, max_wait_sec=max_wait_sec, to=to,
                              task_id=str(recipient["task_id"]),
                              role=str(recipient["role"]))
    except C.ClockUnreadable as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    except C.ClockParamError as exc:
        return fail(str(exc), kind="param_error", checked=True)
    except C.ClockNotFound as exc:
        return fail(str(exc), kind="not_found", checked=True)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    return ok(_start_payload(timer), timer_id=timer.timer_id)


@tool(
    "clock.alarm_start",
    "定一个一次性闹钟：到 at（ISO 时刻）时叫醒收件人。到点动作与 timer_start 相同"
    "（一条 notice 板项 + 一条唤醒标记），差别只在时间怎么给。可另给 wait_for："
    "到点或等到谁，先到者报醒。定一个具体时刻叫醒自己就用这一件（不是睡一轮）；"
    "撤掉一条没到点的用 clock.timer_cancel(timer_id=…)。目的忘了填同样不报错"
    "（读数带 purpose_missing=true）。所有角色都能用。",
    {"type": "object",
     "properties": {
         "at": {"type": "string", "minLength": 1,
                "description": "到点时刻（ISO；naive 按 UTC 解释；必须晚于现在）"},
         "wait_for": {"type": "string", "minLength": 1, "maxLength": 200,
                      "description": ("可选：等谁（名册名 / 编号 / task:<号> / agent:<名>）。"
                                      "与 at 两个里面先到的那个报醒")},
         "max_wait_sec": {"type": "number", "minimum": 0.001, "maximum": 315360000,
                          "description": "等谁的上限（只在给了 wait_for 时有意义）"},
         "reason": {"type": "string", "maxLength": 500,
                    "description": "目的（缺了不报错，读数会追问）"},
         "to": {"type": "string",
                "description": "收件人：self（缺省，叫我这一趟）或 tasks 表的台账号"},
     },
     "required": ["at"], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'timer_id','kind','state','to','task_id','role','reason','after_sec',"
             "'due_at','at','remaining_sec','created_at','clock_status','wait_for',"
             "'wait_for_resolved','wait_state','max_wait_sec','park_state','parked_at',"
             "'parked_sec','parked_steps','parked_calls','purpose','purpose_missing',"
             "'purpose_prompt'}"),
    tags=("clock", "alarm", "communication"),
)
def clock_alarm_start(store: Any, root: Any, conductor: Any, *, at: str,
                      reason: str = "", wait_for: str = "",
                      max_wait_sec: float | None = None,
                      to: str = "self") -> ToolResult:
    """定闹钟。at 已经过去 / 收件人不存在 => 受控失败，零写入。"""
    workspace = _resolve_root(root, store)
    _bind(workspace, store, conductor)
    try:
        recipient = _recipient(store, to)
        timer = C.start_alarm(workspace, at=at, reason=reason, wait_for=wait_for,
                              max_wait_sec=max_wait_sec, to=to,
                              task_id=str(recipient["task_id"]),
                              role=str(recipient["role"]))
    except C.ClockUnreadable as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    except C.ClockParamError as exc:
        return fail(str(exc), kind="param_error", checked=True)
    except C.ClockNotFound as exc:
        return fail(str(exc), kind="not_found", checked=True)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    return ok(_start_payload(timer), timer_id=timer.timer_id)


@tool(
    "clock.periodic_start",
    "起一条周期性巡查：每 every_sec 秒报醒一次，直到 clock.periodic_stop 或 until_sec 到或"
    "被等对象收口。M 的巡视就是这一类：every_sec=1200 + purpose=周期性巡查"
    "（等 20 分钟 + 周期性巡查，别写成\"睡 20 分钟\"）。到点消息逐字是"
    "\"巡查时间到：目的｜每 20 分钟一次（第 N 次）\"。目的忘了填不报错。",
    {"type": "object",
     "properties": {
         "every_sec": {"type": "number", "minimum": 0.001, "maximum": 315360000,
                       "description": "每一拍隔多久（必须为正；1200 = 20 分钟）"},
         "purpose": {"type": "string", "maxLength": 500,
                     "description": "目的（例：周期性巡查）。缺了不报错，读数会追问"},
         "until_sec": {"type": "number", "minimum": 0.001, "maximum": 315360000,
                       "description": "整条巡查最多跑多久（缺省 = 一直跑到被停）"},
         "wait_for": {"type": "string", "minLength": 1, "maxLength": 200,
                      "description": ("可选：等谁收口。它一收口本条巡查就停，"
                                      "stopped_reason 会点名是谁")},
         "to": {"type": "string",
                "description": "收件人：self（缺省，叫我这一趟）或 tasks 表的台账号"},
     },
     "required": ["every_sec"], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'periodic_id','every_sec','purpose','fires','next_at','stopped_reason',"
             "'purpose_missing','purpose_prompt','state','to','task_id','role','created_at',"
             "'last_fired_at','remaining_sec','until_sec','wait_for','wait_for_resolved',"
             "'wait_state','stopped_at','last_message','clock_status','patrol_checklist'}"),
    tags=("clock", "periodic", "communication"),
)
def clock_periodic_start(store: Any, root: Any, conductor: Any, *, every_sec: float,
                         purpose: str = "", until_sec: float | None = None,
                         wait_for: str = "", to: str = "self") -> ToolResult:
    """起周期性巡查。every_sec 不是正数 / 收件人不存在 => 受控失败，零写入。

    交回去的读数是 `_periodic_payload` 加一格 `patrol_checklist`：这一条巡查每一次报醒会
    带哪四类异常、各自几条，以及一段"样例报醒文本"（`wake_sample`）。起表那一刻就让 M
    看见"到点它会收到什么"，否则这条巡查值不值得一直跳就只能靠猜。

    `patrol_checklist` 这一格进 `returns=` 声明（2026-10-26 的 p210 重冻一并补上）：那一份声明
    此前被 `tests/golden/tool_surface_snapshot.json` 逐字钉住（FC-27 禁改区，重冻要两名
    reviewer），所以它一直是"给了但没声明"的那一档；重冻之后声明与实现同形，
    `tests/test_tools_returns_declaration.py` 两向都验。
    """
    workspace = _resolve_root(root, store)
    _bind(workspace, store, conductor)
    try:
        recipient = _recipient(store, to)
        periodic = C.start_periodic(workspace, every_sec=every_sec, purpose=purpose,
                                    until_sec=until_sec, wait_for=wait_for, to=to,
                                    task_id=str(recipient["task_id"]),
                                    role=str(recipient["role"]))
    except C.ClockUnreadable as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    except C.ClockParamError as exc:
        return fail(str(exc), kind="param_error", checked=True)
    except C.ClockNotFound as exc:
        return fail(str(exc), kind="not_found", checked=True)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    payload = _periodic_payload(periodic)
    payload["patrol_checklist"] = _patrol_reading(
        workspace, task_id=str(recipient["task_id"]))
    return ok(payload, periodic_id=periodic.periodic_id)


@tool(
    "clock.periodic_stop",
    "停一条周期性巡查（到点后不再报醒）。已停的返回 stopped=false + 它当前的状态"
    "（查过了，不是第二次停成功）。所有角色都能用。",
    {"type": "object",
     "properties": {
         "periodic_id": {"type": "string", "minLength": 1, "maxLength": 64,
                         "description": "clock.periodic_start 返回的编号（pd-…）"},
         "reason": {"type": "string", "maxLength": 200,
                    "description": "为什么停（会写进 stopped_reason，供审计）"},
     },
     "required": ["periodic_id"], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'checked','periodic_id','stopped','state','stopped_reason','reason',"
             "'periodic','running_count','clock_status'}"),
    tags=("clock", "periodic", "communication"),
)
def clock_periodic_stop(store: Any, root: Any, *, periodic_id: str,
                        reason: str = "") -> ToolResult:
    """停周期性巡查。找不到不是失败（三态：查过了、没有这一条）。"""
    workspace = _resolve_root(root, store)
    reading = C.now()
    try:
        periodic, state = C.stop_periodic(workspace, periodic_id, reason=reason)
        running = len(C.book(workspace).running_periodics())
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False,
                    periodic_id=periodic_id)
    note = ""
    if periodic is None:
        note = f"没有 {periodic_id} 这一条（不是'已经停过'）"
    elif state == "already_stopped":
        note = f"{periodic_id} 早就是停态（查过了，不是第二次停成功）"
    return ok({
        "checked": True,
        "periodic_id": str(periodic_id),
        "stopped": state == "stopped",
        "state": periodic.state if periodic is not None else "not_found",
        "stopped_reason": (periodic.stopped_reason if periodic is not None else ""),
        "reason": note,
        "periodic": _periodic_payload(periodic) if periodic is not None else None,
        "running_count": running,
        "clock_status": reading.status,
    })


@tool(
    "clock.timer_purpose",
    "给一条已经受理的等待补上目的（同一个编号，不是新建一条）。"
    "起表时忘了写目的就走这一件：补上之后到点那条报醒里就有目的可念，"
    "purpose_missing 转 false。计时器（tm-…）与周期性巡查（pd-…）都认。"
    "所有角色都能用。",
    {"type": "object",
     "properties": {
         "entry_id": {"type": "string", "minLength": 1, "maxLength": 64,
                      "description": "要补目的的编号：clock.timer_start 的 tm-… 或 periodic_start 的 pd-…"},
         "purpose": {"type": "string", "minLength": 1, "maxLength": 500,
                     "description": "目的（例：等待20分钟+周期性巡查）"},
     },
     "required": ["entry_id", "purpose"], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'checked','entry_id','filled','state','purpose','purpose_missing',"
             "'reason','entry','clock_status'}"),
    tags=("clock", "timer", "communication"),
)
def clock_timer_purpose(store: Any, root: Any, *, entry_id: str,
                        purpose: str) -> ToolResult:
    """补目的。找不到 / 已经到点 / 早有目的 => 受控读数，不新建条目。"""
    workspace = _resolve_root(root, store)
    reading = C.now()
    try:
        entry, state = C.set_purpose(workspace, entry_id, purpose)
    except C.ClockParamError as exc:
        return fail(str(exc), kind="param_error", checked=True, entry_id=entry_id)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False, entry_id=entry_id)
    note = ""
    if entry is None:
        note = (f"没有 {entry_id} 这一条（计时器与周期性巡查都找过）—— "
                "补目的是补已有那条的空白，不是新建一条")
    elif state == "already_filled":
        note = (f"{entry_id} 早就有目的（{getattr(entry, 'purpose', '')}）—— "
                "补目的不覆盖已有的那句话")
    elif state == "not_pending":
        note = (f"{entry_id} 当前状态是 {getattr(entry, 'state', '')}，已经到点/已停，"
                "补不上目的了（到点消息里那一趟会写'目的未填'）")
    as_timer = entry if isinstance(entry, C.Timer) else None
    as_periodic = entry if isinstance(entry, C.Periodic) else None
    return ok({
        "checked": True,
        "entry_id": str(entry_id),
        "filled": state == "filled",
        "state": getattr(entry, "state", "not_found") if entry is not None else "not_found",
        "purpose": getattr(entry, "purpose", "") if entry is not None else "",
        "purpose_missing": (entry.purpose_missing if entry is not None else None),
        "reason": note,
        "entry": (_start_payload(as_timer) if as_timer is not None
                  else (_periodic_payload(as_periodic) if as_periodic is not None else None)),
        "clock_status": reading.status,
    })


@tool(
    "clock.timer_list",
    "列出计时器：待发 / 已到点 / 已取消，各带 due_at、remaining_sec（读不到时钟时为 null）"
    "与到点项编号；同时列周期性巡查（`periodics` / `periodic_count`）、挂机等待者"
    "（`waiters` / `waiters_parked`）与唤醒标记的读数。挂机等待者回答「谁在等、等什么」，"
    "所以这一件也是「这一拍会不会被挂起」的读口。所有角色都能用。",
    {"type": "object",
     "properties": {
         "include_done": {"type": "boolean",
                          "description": "是否含已到点/已取消的（缺省是）"},
     },
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=_ROLES_ALL,
    returns=("{'checked','clock','status','wall','monotonic','timers','count','periodics',"
             "'periodic_count','waiters','waiters_parked','pending_count','fired_count',"
             "'cancelled_count','pending_wakes','wakes_checked','observed_events','reason'}"),
    tags=("clock", "timer", "read"),
)
def clock_timer_list(store: Any, root: Any, *, include_done: bool = True) -> ToolResult:
    """读计时器与唤醒标记。读不成 => checked=False（不是"没有计时器"）。

    四条分支（正常 / 读不出计时器 / 读不出挂机等待者 / 读不出周期性巡查）的顶层键集合
    逐字相同（2026-10-26，与 `attack.create_plan` 2026-10-27 统一那四条分支同法）：
    读不出的那一格给空值，不删声明 —— 缺键会让调用方读 `data["periodics"]` 时拿到
    KeyError，而"这一格读不出来"本来是一句能说清的话。哪几格没读成由 `checked` 与
    `reason` 交代；空值（`[]` / `0` / `null`）只表示"这一格没有数据"，不表示
    "查过了、什么都没有"。

    判据：`tests/test_clock_timer_list_branches_agree.py`。
    """
    workspace = _resolve_root(root, store)
    reading = C.now()
    checked = True
    problems: list[str] = []
    try:
        all_timers = C.timers(workspace)
    except C.ClockStateError as exc:
        all_timers, checked = [], False
        problems.append(f"计时器读不成：{exc}")
    shown = [t for t in all_timers if include_done or t.state == "pending"]
    rows = [t.row(reading) for t in shown]
    wakes = C.read_wakes(workspace)
    try:
        park = C.waiters(workspace)
    except C.ClockStateError as exc:
        # `parked` 给 None 不给 0：0 是"查过了、没人挂在时钟上"那个结论（三态）。
        park, checked = {"waiters": [], "parked": None}, False
        problems.append(f"挂机等待者读不成：{exc}")
    try:
        periodic_rows = [p.row(reading) for p in C.periodics(workspace)]
    except C.ClockStateError as exc:
        periodic_rows, checked = [], False
        problems.append(f"周期性巡查读不成：{exc}")
    observed = C.observed_events()
    reason = str(wakes.get("reason") or "")
    if problems:
        reason = "；".join(problems + ([reason] if reason else []))
    return ok({
        "checked": checked,
        "clock": "agentflow.clock",
        "status": reading.status,
        "wall": reading.to_dict()["wall"],
        "monotonic": reading.monotonic,
        "timers": rows,
        "count": len(rows),
        "periodics": periodic_rows,
        "periodic_count": len(periodic_rows),
        "waiters": list(park.get("waiters") or []),
        "waiters_parked": park.get("parked"),
        "pending_count": sum(1 for t in all_timers if t.state == "pending"),
        "fired_count": sum(1 for t in all_timers if t.state == "fired"),
        "cancelled_count": sum(1 for t in all_timers if t.state == "cancelled"),
        "pending_wakes": int(wakes.get("count") or 0) if wakes.get("checked") else 0,
        "wakes_checked": bool(wakes.get("checked")),
        "observed_events": observed["counts"],
        "reason": reason,
    })


@tool(
    "clock.timer_cancel",
    "取消一条还没到点的计时器/闹钟（到点后不再触发）。已到点或已取消的返回 "
    "cancelled=false + 它当前的状态（查过了，不是第二次取消）。编号是 tm- 那一种；"
    "周期性巡查不归这一件（它用 clock.periodic_stop(periodic_id=pd-…)）。"
    "所有角色都能用。",
    {"type": "object",
     "properties": {
         "timer_id": {"type": "string", "minLength": 1, "maxLength": 64,
                      "description": "clock.timer_start / alarm_start 返回的编号"},
     },
     "required": ["timer_id"], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'checked','timer_id','cancelled','state','reason','timer',"
             "'pending_count','clock_status'}"),
    tags=("clock", "timer", "communication"),
)
def clock_timer_cancel(store: Any, root: Any, *, timer_id: str) -> ToolResult:
    """取消计时器。找不到不是失败（三态：查过了、没有这一条）。"""
    workspace = _resolve_root(root, store)
    reading = C.now()
    try:
        timer, state = C.cancel_timer(workspace, timer_id)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False, timer_id=timer_id)
    try:
        pending_count = len(C.book(workspace).pending())
    except C.ClockStateError:
        pending_count = 0
    reason = ""
    if timer is None:
        reason = f"没有 {timer_id} 这一条（不是'已经取消'）"
    elif state == "already_cancelled":
        reason = f"{timer_id} 早就是取消态（查过了，不是第二次取消成功）"
    elif state != "cancelled":
        reason = f"{timer_id} 当前状态是 {state}，不是待发"
    return ok({
        "checked": True,
        "timer_id": str(timer_id),
        "cancelled": state == "cancelled",
        "state": timer.state if timer is not None else "not_found",
        "reason": reason,
        "timer": timer.row(reading) if timer is not None else None,
        "pending_count": pending_count,
        "clock_status": reading.status,
    })


@tool(
    "clock.wait_any",
    "等待任意计时器返回：手上没事了，谁先回来都行，回来叫我。"
    "这是显式意图（不是「有计时器」这一件事本身）：记下之后循环这一拍不调模型；"
    "到任一计时器返回或我等的人说了话，就把「目的 + 现场等了多久 + 时间到 + 对方说的话」"
    "发给你。手上有活要接着做就别起这个意图 —— 计时器不会阻塞动作。"
    "已无事可做且一条计时器都没有时起这个意图，等于交差（框架向父代理报告）——"
    "读数里的 requested=true / waiting=false 说的就是这一档（要求过等、而没有可等的东西），"
    "它不是「没在等」。所有角色都能用。",
    {"type": "object",
     "properties": {
         "purpose": {"type": "string", "maxLength": 200,
                     "description": "等这一趟是为了什么（可省；省了读数里 purpose 为空，"
                                    "不影响受理）"},
     },
     "required": [], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_ALL,
    returns=("{'checked','task_id','role','wait_id','purpose','requested','waiting',"
             "'pending','pending_count','woke','woke_count','intents','reason',"
             "'clock_status'}"),
    tags=("clock", "timer", "communication"),
)
def clock_wait_any(store: Any, root: Any, *, purpose: str = "") -> ToolResult:
    """记一条「等待任意计时器返回」的意图，并把这一格的读数交回去。

    业主 2026-10-27 第三条裁定的后半个动作（逐字）：「直到它认为无事可做时，可启动
    计时器"等待任意计时器返回"」。改前这个动作只有框架内部入口（`clock.request_wait_any`），
    模型面上没有这一格 ⇒ 模型没法表达这个意图。

    三件一起做，缺一件这个动作就成了"起一条不存在的表"：

    1. 写意图（`C.request_wait_any`）：同一个台账号只留最新一条（再要一次 = 继续等）；
    2. 现读这一格（`C.wait_any_reading`）：`requested` = 它要求过等，`waiting` = 确实还有
       计时器没回来，`pending` 是那几条的编号，`woke` 是起意之后回来的那几条；
    3. 把两样都交回去 —— 模型据此知道"这一拍会不会被挂起"，而挂起的判定仍在
       `agent_loop._park_gate` 一处（工具不做控制流）。

    失败姿态：没有台账号 ⇒ 受控拒绝（`checked=false`），不是"没有计时器"；账读不成/写不成
    ⇒ `checked=false` + 原话（三态纪律：「没查成」不许折成「没在等」）。
    """
    workspace = _resolve_root(root, store)
    task_id = str(current_task_id() or "")
    role = str(current_caller_role() or "")
    if not task_id:
        return fail("等待任意计时器返回要一个台账号：这一趟不知道自己是谁（不是「没有计时器」）",
                    kind="no_task", checked=False)
    try:
        row = C.request_wait_any(workspace, task_id=task_id, role=role, purpose=purpose)
    except C.ClockParamError as exc:
        return fail(str(exc), kind="bad_request", checked=False)
    except C.ClockStateError as exc:
        return fail(str(exc), kind="unreadable", checked=False)
    reading = dict(C.wait_any_reading(workspace, task_id))
    clock = C.now()
    pending = [str(x) for x in (reading.get("pending") or ())]
    woke = list(reading.get("woke") or ())
    # 全量意图读数（`clock.read_wait_any`）：这一趟、以及同一工作区里别人留下的等待意图。
    # 为什么要给模型看全量：`waiting` 那一格只回答"我要不要挂"，不回答"这一支现在挂了几个人"；
    # 主控要判断"这一支是不是全挂上了"，缺这一格就只能靠猜。三态：读不成 ⇒ checked=false。
    try:
        intents = dict(C.read_wait_any(workspace))
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        intents = {"checked": False, "rows": [], "count": 0,
                   "reason": f"{type(exc).__name__}: {exc}"}
    return ok({
        "checked": bool(reading.get("checked")),
        "task_id": task_id,
        "role": role,
        "wait_id": str(row.get("wait_id") or ""),
        "purpose": str(row.get("purpose") or ""),
        "requested": bool(reading.get("requested")),
        "waiting": bool(reading.get("waiting")),
        "pending": pending,
        "pending_count": len(pending),
        "woke": woke,
        "woke_count": len(woke),
        "intents": {
            "checked": bool(intents.get("checked")),
            "count": int(intents.get("count") or 0),
            "rows": list(intents.get("rows") or ()),
            "reason": str(intents.get("reason") or ""),
        },
        "reason": str(reading.get("reason") or ""),
        "clock_status": clock.status,
    })


#: 工具与它需要的装配期依赖（`register` 只按位置把依赖绑上去）。
# ---------------------------------------------------------------- 程序两件（G1）

#: `program.list` 里 `unowned` 那一桶最多逐项列几条。
#:
#: 为什么要上限：改前的存量是 1420 条空归属的程序计时器（真机读数），`include_done=true`
#: 一读就会把这一千多行塞进模型的上下文。条数（`unowned_count`）永远是全量实数，
#: 只截断逐项清单，并单列 `unowned_shown` 让人看得见"列了几条、一共几条"。
UNOWNED_SHOWN: int = 50

#: 程序那一行的读数格：`program_row()` 的格 + 这一批加的三格现场读数。
#:
#: `age_sec`：从登记到现在过了多久（`Timer.waited_seconds`，读不到时钟时是 null）。
#: `alive`：这个 pid 现在还在不在（`process_alive`，三态：没有 pid 时是 null ——
#: "没有 pid"与"进程没了"必须分得开，否则"账上少一格"会被读成"它已经退出了"）。
#: `owner`：这一条归谁（`program_owner`：台账号 / 角色 / 有没有归属）。


def _program_line(timer: C.Timer) -> dict[str, Any]:
    """一行程序读数（`program.list` 的 items 就是它的数组）。"""
    row = dict(timer.program_row())
    row["age_sec"] = timer.waited_seconds()
    pid = timer.pid
    row["alive"] = (C.process_alive(int(pid))
                    if isinstance(pid, int) and int(pid) > 0 else None)
    row["owner"] = C.program_owner(timer)
    return row


def _program_note(mine: Sequence[Mapping[str, Any]], unowned: Sequence[Mapping[str, Any]],
                  others_running: int, *, unowned_count: int = 0,
                  unowned_shown: int = 0) -> str:
    """`program.list` 的那句读数（交差/销号前自查要能一句话看懂）。"""
    running = [r for r in mine if str(r.get("state") or "") == "pending"]
    bits: list[str] = []
    if running:
        pids = "、".join(str(r.get("pid")) for r in running)
        bits.append(f"我名下还有 {len(running)} 个程序在跑（pid {pids}）—— "
                    "交差或销号之前先 program.stop（或者说明它们为什么该继续跑）")
    else:
        bits.append("我名下没有还在跑的程序（查过了，不是没查成）")
    if unowned_count:
        bits.append(f"；另：账上有 {unowned_count} 条没有归属的旧程序行"
                    "（改前那批：它们不归任何人，既不算我的，也不会被我停掉）")
        if unowned_shown < unowned_count:
            bits.append(f"（这里只逐项列了前 {unowned_shown} 条）")
    if others_running:
        bits.append(f"；别人的程序在跑的有 {others_running} 个（不列细节）")
    return "".join(bits)


@tool(
    "program.list",
    "列出我这一趟起的程序（缺省只列还在跑的）：program / pid / argv 摘要 / 起于何时 / "
    "已跑多久 / 它那条计时器 id / 那条表的目的，外加 alive（pid 现在还在不在）。"
    "空归属的旧账单列在 unowned 里 —— 它们不归任何人，既不算我的、也不会被我停掉。"
    "这是交差/销号之前的自查口：retire_ready=false 就说明我还有程序在跑，先 program.stop。"
    "所有角色都能用。",
    {"type": "object",
     "properties": {
         "include_done": {"type": "boolean",
                          "description": "是否含已经收口的程序行（缺省否：只看还在跑的）"},
     },
     "required": [], "additionalProperties": False},
    side_effect="read",
    roles=_ROLES_ALL,
    returns=("{'checked','task_id','role','programs','count','running','unowned',"
             "'unowned_count','unowned_shown','unowned_running','others','others_running',"
             "'include_done','retire_ready','note','reason'}"),
    tags=("clock", "program", "read"),
)
def program_list(store: Any, root: Any, *, include_done: bool = False) -> ToolResult:
    """我名下的程序读数（三态：簿记读不成 => checked=False，不是"没有程序在跑"）。"""
    workspace = _resolve_root(root, store)
    task_id = str(current_task_id() or "")
    role = str(current_caller_role() or "")
    try:
        got = C.programs_owned(workspace, task_id=task_id, role=role,
                               include_done=bool(include_done))
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        got = {"checked": False, "mine": [], "unowned": [], "others": 0,
               "others_running": 0, "count": 0, "running": 0,
               "reason": f"程序计时器读不成：{type(exc).__name__}: {exc}"}
    mine = [_program_line(t) for t in (got.get("mine") or ())]
    unowned_all = [_program_line(t) for t in (got.get("unowned") or ())]
    unowned = unowned_all[:UNOWNED_SHOWN]
    running = sum(1 for r in mine if str(r.get("state") or "") == "pending")
    unowned_running = sum(1 for r in unowned_all if str(r.get("state") or "") == "pending")
    checked = bool(got.get("checked"))
    return ok({
        "checked": checked,
        "task_id": task_id,
        "role": role,
        "programs": mine,
        "count": len(mine),
        "running": running,
        "unowned": unowned,
        "unowned_count": len(unowned_all),
        "unowned_shown": len(unowned),
        "unowned_running": unowned_running,
        "others": int(got.get("others") or 0),
        "others_running": int(got.get("others_running") or 0),
        "include_done": bool(include_done),
        # 注销前检测的那一格：三态（None = 没查成，绝不折成"可以销号"）。
        "retire_ready": (None if not checked else running == 0),
        "note": ("" if not checked else
                 _program_note(mine, unowned, int(got.get("others_running") or 0),
                               unowned_count=len(unowned_all),
                               unowned_shown=len(unowned))),
        "reason": str(got.get("reason") or ""),
    })


#: `program.stop` 那一份 `data` 的唯一形状（受控拒绝、找不到、真停，三档共用）。
#: 声明（`returns=`）与实现在这里只有一处来源，`test_tools_returns_declaration` 两向都验。
def _program_stop_payload(**kw: Any) -> dict[str, Any]:
    """把逐条读数与汇总装成同一份形状（每一档都给全键，缺的那档是 0 / 空表）。"""
    items = list(kw.get("items") or ())
    counts = {code: sum(1 for r in items if str(r.get("result") or "") == code)
              for code in C.PROGRAM_STOP_RESULTS}
    killed = int(counts.get("killed") or 0)
    still_alive: list[int] = []
    for row in items:
        for pid in (row.get("still_alive") or ()):
            if int(pid) not in still_alive:
                still_alive.append(int(pid))
    woken = sum(int(r.get("woken") or 0) for r in items)
    bits = [f"我杀了 {killed} 个自己的程序"]
    if counts.get("already_exited"):
        bits.append(f"{counts['already_exited']} 个早就结束了（already_exited：查过了，不是第二次杀掉）")
    if counts.get("timeout"):
        bits.append(f"{counts['timeout']} 个杀不动（timeout：还在跑的 pid "
                    + "、".join(str(p) for p in still_alive) + "）")
    if counts.get("not_mine"):
        bits.append(f"{counts['not_mine']} 个不是我的（not_mine：一个进程都没碰）")
    if counts.get("not_found"):
        bits.append(f"{counts['not_found']} 个查不到可停的对象（not_found）")
    if woken:
        bits.append(f"等它们的 {woken} 条计时器已经被叫醒")
    return {
        "checked": bool(kw.get("checked", True)),
        "task_id": str(kw.get("task_id") or ""),
        "role": str(kw.get("role") or ""),
        "mode": str(kw.get("mode") or ""),
        "requested": list(kw.get("requested") or ()),
        "stopped": killed,
        "killed": killed,
        "already_exited": int(counts.get("already_exited") or 0),
        "timeout": int(counts.get("timeout") or 0),
        "not_mine": int(counts.get("not_mine") or 0),
        "not_found": int(counts.get("not_found") or 0),
        "count": len(items),
        "items": items,
        "still_alive": still_alive,
        "woken": woken,
        "note": "" if not items else "；".join(bits),
        "session_event": str(kw.get("session_event") or ""),
        "reason": str(kw.get("reason") or ""),
        "clock_status": str(kw.get("clock_status") or ""),
    }


def _program_stop_session(workspace: str | Path, *, task_id: str, role: str,
                          note: str, items: Sequence[Mapping[str, Any]]) -> str:
    """把这一刀的读数落一条会话事件（`run.notes` 的旁路，见模块 docstring）。

    为什么落会话：`run.notes` 只有 `agent_loop` 能写（它不在本批可改范围），而这件事
    必须在审计面上有一行 —— 会话文件是框架唯一的叙事审计面。写不成如实返回原因，
    不许静默（"我杀了 N 个"这句话没有落盘与"杀了但没说"在读数上必须分得开）。
    """
    try:
        from ..conductor import current_session

        session_root, sid = current_session()
    except Exception as exc:  # noqa: BLE001 - 取不到会话身份：如实报，不静默
        return f"没落成（会话身份取不到：{type(exc).__name__}: {exc}）"
    if not str(session_root or ""):
        return "没落（这一趟没有会话根：读数在工具返回与程序行的 note 里）"
    try:
        from .. import sessions as SS

        _path, problem = SS.append(str(session_root), {
            "kind": "agent_program_stop", "role": str(role or ""),
            "task_id": str(task_id or ""), "note": str(note or ""),
            "count": len(list(items or ())),
            "results": [str(r.get("result") or "") for r in (items or ())],
            "timer_ids": [str(r.get("timer_id") or "") for r in (items or ())],
            "still_alive": [int(p) for r in (items or ())
                            for p in (r.get("still_alive") or ())],
        }, sid=(sid or None))
    except Exception as exc:  # noqa: BLE001 - 落不成是"没写成"，不许折成"没发生"
        return f"没落成（{type(exc).__name__}: {exc}）"
    return "" if not problem else f"没落成（{problem}）"


@tool(
    "program.stop",
    "停掉我这一趟起的程序：先给它一个宽限窗口让它自己收尾，过了窗口才真杀；然后把那条"
    "程序计时器按 outcome=\"killed\" 收口，并唤醒正在等它的人。"
    "只许碰自己起的：别人的与账上没有归属的旧行一律受控拒绝（not_mine，一个进程都不碰）。"
    "已经结束的返回 already_exited（幂等，那一行一个字都不改）；杀不动的返回 timeout 并点名"
    "还在跑的 pid（账上那条保持 pending）；编号不存在返回 not_found。都不抛异常。"
    "给 timer_id 停一条，给 all_programs=true 停我名下全部。"
    "只发给能起程序的角色（只读角色 C/H/V 不在面上：它们本来也起不了程序）。",
    {"type": "object",
     "properties": {
         "timer_id": {"type": "string", "minLength": 1, "maxLength": 64,
                      "description": ("要停的那一条（program.list 里的 tm-…；"
                                      "与 all_programs 二选一）")},
         "all_programs": {"type": "boolean",
                          "description": "停我名下全部还在跑的程序（缺省否；与 timer_id 二选一）"},
         "reason": {"type": "string", "maxLength": 200,
                    "description": "为什么停（写进那条程序行的 note，供审计）"},
     },
     "required": [], "additionalProperties": False},
    side_effect="write_local",
    roles=_ROLES_WRITE,
    returns=("{'checked','task_id','role','mode','requested','stopped','killed',"
             "'already_exited','timeout','not_mine','not_found','count','items',"
             "'still_alive','woken','note','session_event','reason','clock_status'}"),
    tags=("clock", "program", "communication"),
)
def program_stop(store: Any, root: Any, *, timer_id: str = "",
                 all_programs: bool = False, reason: str = "") -> ToolResult:
    """停一条（或我名下全部）程序。四档读数见 `C.PROGRAM_STOP_RESULTS`，不抛异常。"""
    workspace = _resolve_root(root, store)
    _bind(workspace, store)
    reading = C.now()
    task_id = str(current_task_id() or "")
    role = str(current_caller_role() or "")
    payload = partial(_program_stop_payload, task_id=task_id, role=role,
                      clock_status=reading.status)
    if not task_id:
        # 没有台账号 = 这一趟不知道自己是谁。空归属的程序不许被任何一趟当成自己的，
        # 所以这一档是受控拒绝，而不是"退到角色相等去停"（那是把别人的进程算成我的）。
        data = payload(checked=False, mode="", requested=[],
                       reason=("停程序要一个台账号：这一趟不知道自己是谁 ⇒ "
                               "既分不出哪些是我起的，也不许按角色去猜（不是「没有可停的程序」）"))
        return fail(data["reason"], kind="no_task", **data)
    if bool(timer_id) == bool(all_programs):
        data = payload(checked=True, mode="", requested=[],
                       reason=("timer_id（停一条）与 all_programs（停全部）只能选一个："
                               "两个都不给就不知道停哪条，两个都给就不知道是哪一个意思"))
        return fail(data["reason"], kind="bad_request", **data)
    mode = "one" if timer_id else "all"
    requested: list[str] = []
    items: list[dict[str, Any]] = []
    try:
        if timer_id:
            requested = [str(timer_id)]
            items = [C.stop_program(workspace, str(timer_id), task_id=task_id,
                                    role=role, reason=reason)]
        else:
            got = C.programs_owned(workspace, task_id=task_id, role=role,
                                   include_done=False)
            if not got.get("checked"):
                data = payload(checked=False, mode=mode, requested=[],
                               reason=str(got.get("reason") or "程序计时器读不成"))
                return fail(data["reason"], kind="unreadable", **data)
            running = [t for t in (got.get("mine") or ())
                       if str(getattr(t, "state", "")) == "pending"]
            requested = [str(t.timer_id) for t in running]
            items = [C.stop_program(workspace, str(t.timer_id), task_id=task_id,
                                    role=role, reason=reason) for t in running]
    except C.ClockStateError as exc:
        data = payload(checked=False, mode=mode, requested=requested,
                       reason=f"时钟簿记读不成：{exc}")
        return fail(data["reason"], kind="unreadable", **data)
    data = payload(checked=True, mode=mode, requested=requested, items=items,
                   reason=("我名下没有还在跑的程序 ⇒ 没有可停的（查过了，不是没查成）"
                           if not items else ""))
    if items:
        problem = _program_stop_session(workspace, task_id=task_id, role=role,
                                        note=data["note"], items=items)
        data["session_event"] = problem or "written"
    return ok(data, **data)


#: 工具与它需要的装配期依赖（`register` 只按位置把依赖绑上去）。
_TOOL_FUNCTIONS: tuple[tuple[Any, tuple[str, ...]], ...] = (
    (clock_now, ("store", "root")),
    (clock_timer_start, ("store", "root", "conductor")),
    (clock_alarm_start, ("store", "root", "conductor")),
    (clock_periodic_start, ("store", "root", "conductor")),
    (clock_periodic_stop, ("store", "root")),
    (clock_timer_purpose, ("store", "root")),
    (clock_timer_list, ("store", "root")),
    (clock_timer_cancel, ("store", "root")),
    (clock_wait_any, ("store", "root")),
    (program_list, ("store", "root")),
    (program_stop, ("store", "root")),
)

#: 会话写路径的旁路钩子只装一次（装配会跑很多遍：每角色一份注册表）。
_HOOK_INSTALLED: bool = False
#: 我们顶掉的那个旧钩子（网页端的 SSE 用同一个槽，必须把它接在我们后面）。
_HOOK_PREV: Any = None


def _observe_session_event(root: Any, event: Mapping[str, Any]) -> None:
    """会话事件 -> 时钟观测（发消息/答复/回合），然后交给被我们顶掉的那个钩子。

    为什么走 `sessions.set_append_hook`：这是仓库里已有的"追加成功之后"旁路，
    `webui/sse.py` 用的是同一个槽。本模块按它的设计把它顶掉，再把旧钩子接在自己
    后面（`set_append_hook` 返回被顶掉的那一个就是为了这件事）。

    观测只做三件事：消息/答复进事件窗（唤醒挂机中的父/子）、`agent_step` 记到挂机
    中的 waiter 上（证明挂机期间没有轮询）。任何一件失败都不许把写路径带坏
    （`sessions` 那一侧本来也会接住，这里再接一层是为了自己的 bug 不外溢）。
    """
    try:
        rec = dict(event or {})
        C.observe_message(rec)
        C.observe_work(rec)
    except Exception:  # noqa: BLE001 - 旁路：观测炸了不许影响写
        pass
    previous = _HOOK_PREV
    if callable(previous):
        try:
            previous(root, event)
        except Exception:  # noqa: BLE001 - 旧钩子自己会记读数，这里不再抛
            pass


def _install_append_hook() -> str:
    """把时钟接进会话写路径（只装一次）。返回这一趟做了什么（进装配读数）。"""
    global _HOOK_INSTALLED, _HOOK_PREV
    if _HOOK_INSTALLED:
        return "already"
    from .. import sessions as SS

    _HOOK_PREV = SS.set_append_hook(_observe_session_event)
    _HOOK_INSTALLED = True
    return "installed"


def register(registry: ToolRegistry, *, store: Any = None, root: Any = None,
             workspace_root: Any = None, conductor: Any = None,
             **_: Any) -> list[str]:
    """把九件 `clock.*` 装进注册表，返回工具名列表。

    同时做四件装配期的事：

    1. 把到点动作接到 `clock.set_due_handler`：这是"到点后时钟自动动作"的接线点；
    2. 把"等谁"的读口接到 `clock.set_target_probe`：台账/名册里那东西收口了没有；
    3. 把这一趟的工作区与 store 绑进运行期表：到点动作需要它写 mailbox 项；
    4. 把会话写路径的旁路钩子接上（消息/答复/回合 -> 时钟观测）。

    外加一件（业主 2026-10-26）：把异常清单的读口接到 `clock.set_patrol_probe`，
    于是"巡查时间到"那句报醒带的是当拍现算的四类异常，而不是一句空话。
    """
    C.set_due_handler(_deliver_due)
    C.set_target_probe(_target_probe)
    # 异常清单的读口（业主 2026-10-26）：巡查到点那句报醒要带当拍现算的四类异常。
    C.set_patrol_probe(_patrol_probe)
    workspace = _resolve_root(root if root else workspace_root, store)
    _bind(workspace, store, conductor)
    # 进程缺省工作区：`program_span` 落在工具层之下（agent_e / cancellation /
    # papercompile …），那里拿不到 `AgentLoop.workspace_root` —— 挂上这一个，
    # 程序计时器才写得进同一本 `<工作区>/out/clock/state.json`。
    C.set_default_workspace(workspace)
    _install_append_hook()
    bound: dict[str, Any] = {
        "store": store,
        "root": workspace,
        "conductor": conductor,
    }
    names: list[str] = []
    for fn, deps in _TOOL_FUNCTIONS:
        spec = replace(fn.__tool_spec__,
                       handler=partial(fn, *[bound[k] for k in deps]))
        names.append(registry.register(spec).name)
    return names


__all__ = ["DUE_PREFIX", "DUE_PREFIXES", "PATROL_PREFIX", "register"]
