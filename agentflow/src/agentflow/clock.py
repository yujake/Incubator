# -*- coding: utf-8 -*-
"""系统时钟：全系统唯一的取时口，计时器与闹钟都依附在它上面。

## 时钟的定位

把时钟做成系统原生工具，让 M 在派活完后启动计时器（计时器依托时钟实现），
到点后时钟自动给 M 发消息检查，检查完成后 M 再启动计时器。其它人要看表
（看时钟读数）或计时、定闹钟也可以用 —— 这是个通用工具。
时钟只有一个，依附于其上的计时进程可以很多。

## 这个模块负责什么，不负责什么

负责：

1. 唯一的读数口 `now()`：一次给出墙钟与单调计数，两者各自可能读不到；
2. 注入点：判据可以把假时钟装进来（`use(FakeClock(...))`），业务代码一律
   经 `now()` 取时，不许自己调 `time.time()`；
3. 计时器/闹钟的登记与落盘（`<工作区>/out/clock/state.json`），重启后仍在；
4. 到点判定 `is_due` 与"把到点的那些交出去"`fire_due()`；
5. 唤醒标记的落盘与读数（`<工作区>/out/clock/wake.json`），以及给消费端用的
   `consume_wakes()`。

不负责：把 mailbox 项写进 `tasks` 表。那件事需要 Store / Conductor，属于工具层
（`tools/clock_tools.py` 的 `_deliver_due`）。本模块只提供"谁到点了"这一份事实，
到点动作由工具层注册进来（`set_due_handler`）。这样切的理由：时钟要能被判据
单独喂假时钟、单独检查读数，不该为了一个 mailbox 写口把 Store 拖进来。

## 三态纪律（本模块的核心）

时钟读数有三个状态，不许折平：

- `ok`：墙钟与单调计数都读到了；
- `partial`：只读到一个来源（`source` 说明是哪一个）；
- `unknown`：两个都读不到。此时 `wall` 与 `monotonic` 都是 `None`，
  绝不是 0 —— 把"读不到"折成 0 会让"1970 年"变成一个看起来合法的时间点。

`timer_list` 里的 `remaining_sec` 同样是三态：读不到时钟时是 `None`，不是 0。
到点判定在读不到时钟时返回"判不了"（`is_due` 为假），于是计时器保持 pending，
等下一次时钟恢复；它不会被误触发，也不会被静默丢掉。

## 计时器与闹钟的区别

两者是同一个数据结构，只差 `kind` 与 due 是怎么算出来的：计时器给 `after_sec`
（相对现在多久之后），闹钟给 `at`（绝对 ISO 时刻）。两者都是
一次性：到点即消耗（`state="fired"`），不自动重排。业主口径是"检查完成后 M
自己再启动计时器"，所以重排必须是调用方显式再起一次。

## 重启之后怎么判 due

每条计时器同时记 `due_at`（墙钟，绝对时刻）与 `due_mono`（起表那个进程的单调
计数）。单调计数只在同一个时钟实例（`clock_token` 相同）里可比；重启后 token
变了，于是退化到按墙钟比较。这不是"两个来源二选一"的随意取舍：单调计数跨重启
没有意义（它从进程启动算起），而墙钟是重启后唯一还能对齐的绝对时刻。

## 消费端怎么接

"到点唤醒正在等子的父"由两件事一起保证：落一条 `tasks` 板项（可审计）与置一条唤醒标记
（可读、可消费）。消费端
（`agent_loop` 的等待/续跑那一处）需要做的是：在等子代理的
等待点上读 `pending_wakes(root, my_task_id)`，或调
`consume_wakes(root, my_task_id)`，并把"有唤醒"折进它本来就有的唤醒判据。
本模块不改 `agent_loop.py`，只把可读的落点交出去。

## 计时类任务的申请形状

主时钟要控制所有计时类工作，所以申请形状只有两半，两半各自成立：

1. 等待时间：`after_sec`（多久之后）或 `at`（到哪个钟点）；
2. 等待谁：`wait_for`（名册名 / 绝对编号 / `task:<号>` / `agent:<名>`），
   到被等对象收口时报醒。

两个都给 => 受控拒绝并说清只能选一个；一个都不给 => 受控拒绝。

智能体忘填目的时不报错，只是让它追加目的：照常在给出的一半时序上受起表，读数带
`purpose_missing=true`，其后的读数与到点消息里追问一句；补一句目的走
`set_purpose`，同一条计时器被填上，不是新建一条。
计时到点后向智能体发送信息「目的+等待时间+时间到」。

## 周期性：M 的巡视就是这一类

`start_periodic(every_sec, purpose, ...)`：到点不消耗，`next_at` 前移到下一拍，
`fires` 递增，直到 `periodic_stop` / `until_sec` 到 / 被等的对象收口。
口径写死：M 的巡视是「等 20 分钟 + 周期性巡查」（`every_sec=1200`、
`purpose="周期性巡查"`），不许写成"睡 20 分钟"这种没有目的的形。

## 到点那条消息的格式（业主定死）

    时间到：<目的>｜等了 <时长>（起于 <HH:MM:SS>，到于 <HH:MM:SS>）
    巡查时间到：<目的>｜每 <间隔>一次（第 <N> 次）

目的缺了那一趟写 `（目的未填）` 并追问补一句。三样（目的 / 等待时间 / 时间到）
必须在同一句里，不许只报"到点了"。拼这句话的落点是 `due_message`（唯一实现），
工具层与唤醒标记都读它，不许各拼一份。

## 等待账：为什么框架内部的等待也要进这本账

"主时钟控制了所有计时类工作"这句话今天不成立，因为框架内部还有一批
`time.sleep` / 有界等待不在任何账上（下载重试、检索重试、调度轮询、排水轮询……）。
本模块因此提供两个入口，所有等待都必须走其中之一：

- `await_io(seconds, purpose, kind=..., where=...)`：真睡（保持原语义）并记一条账；
- `note_wait(seconds, purpose, kind=..., where=...)`：不睡，只记一条账 —— 给那些
  阻塞由同步原语/子进程调用完成、不能替换成 sleep 的等待用。

账记的是聚合而不是每一次：同一个 `(kind, where, purpose)` 只占一行，累加次数与
时长。几百次重试不会把账写成几万行。

机器判据是普查：`raw_wait_census()` 用 AST 扫 `src/agentflow` 下的全部模块，把
"没走上面两个入口的原始等待"逐个点出来（文件:行 + 所在函数 + 形态）。`coverage()`
把普查与"已记账的等待"合起来给一份读数，`clock.now` 的复合读数里就有
`waits_outside_clock`。它是"是否全被主时钟控制"的机器判据，不是一句声明。

三态纪律同样适用：扫描读不成 => `checked=false`，不许折成"0 处，很干净"。

允许的例外逐条登记在 `ALLOWED_RAW_WAITS` 里，每条必须写 `why` 与 `blocked_by`；
`coverage()` 把它们单列（`waits_exempt`），不并进 `waits_outside_clock` ——
"被禁改区挡住的等待"与"没人管的等待"是两件事，折平就等于把没做完的活报成做完了。

## 四条裁定

1. 计时器的"等谁"可以等某程序：运行一个程序时会自动启动一个计时器，
   程序运行完成时计时器会返回。
2. "等子代理"的"目的"与名册机制的 task 结合，自动以 task 填充目的。
3. 计时器不阻塞智能体动作，智能体可在多计时器同时存在时继续手上工作，
   直到它认为无事可做时，可启动计时器"等待任意计时器返回"。如果已无事可做且无计时器，
   这意味着它交差了，需要向父代理报告，父代理把它记为静默子代理。
4. 如果一个子代理还有活跃子代理，必存在一个等待该子代理的计时器，所以"静默"
   定义良好。

四条各自的机器落点（本节逐条对应）：

1. 等程序：`program_span(...)` 是起外部程序的唯一入口。进作用域就 `start_program`
   登记一条 `kind="program"` 的计时器，出作用域 `finish_program` 把它收口并写上
   结局（`exited` / `failed` / `timed_out` / `killed`）、`elapsed_sec`、`exit_code`。
   读数是 `programs(workspace)`。另有 `program_census()` 用 AST 把"起进程却没进
   程序计时器"的地方逐个点出来 —— "程序在跑而账上没有计时器"是机器判据，不是声明。
2. 目的自动填：`start_timer(wait_for=...)` 不给 `reason` 时，用"等谁"读口（
   `set_target_probe`）给出的 `task_text` 填目的，读数标 `purpose_source="target_task"`；
   显式给了就是 `given`；两边都拿不到还是 `purpose_missing=true` 加追问（原语义不变）。
3. 计时器不阻塞动作：计时器只是账上的一条，循环该调模型就调模型（`agent_loop._park_gate`
   的判据是"有没有 `wait_any` / 是不是真的无事可做"，不是"有没有计时器"）。
   显式要求"等待任意计时器返回"走 `request_wait_any(...)`，读数 `wait_any_reading(...)`。
4. 交差与静默：无事可做且一条计时器都没有 ⇒ `record_handoff(...)` 记下这次交差
   （父代理据此把它记为静默），父侧的读数是 `read_handoffs(workspace, parent_task_id=…)`。
   不变量（有活跃子代理 ⇒ 必有一条等它的计时器）由父代理派活时自动起表保证
   （`conductor` 的 summon 落点）并由 `conductor.child_wait_invariant` 判定。

## 这份文件为什么变成门面（2026-11-20）

业主口径「还有超800的？派人拆」⇒ 本文件 6,777 行按依赖方向由底向上拆。现在它只做两件事：
再导出（`from .clockbase import ...` / `from .clockrun import ...`，所有
`from .clock import X` 的调用点一个字都不用改）与继续承载还没搬走的那几层。
每一层的落位与"为什么它必须是顶层模块"写在 `tests/test_release_all.py` 的
`_AGENTFLOW_TOP_LEVEL_MODULES` 里；依赖方向一律是「上层 → 下层」，不许反向：

     clockbase（词表 / 三态读数 / 事件原语）
        ↑
     clockrun（唯一取时口 / 进程内簿记 / 复位 / 到点消息拼句）
        ↑
     其余各层（events / TimerBook / Timer / programs / fire_due …）

"可变量没有跨模块共享，只有归谁所有"这条纪律写在 `clockrun` 模块头。
"""

from __future__ import annotations

from .clockbase import ClockError
from .clockbase import RECONCILE_EVERY_SEC
from .clockbase import Reading
from .clockbase import UTC
from .clockbase import _iso
from .clockbase import _parse_iso
from datetime import datetime
import heapq

import ast
import contextlib
import contextvars
import heapq
import json
import os
import signal
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from .canonical import json_default
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockbase.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockbase`（单向）。
from .clockbookindex import (  # noqa: F401 — 混入类 / Periodic / _target_key / MAX_TERMINAL_KEPT 的再导出
    MAX_TERMINAL_KEPT,
    Periodic,
    _BookIndexMixin,
    _target_key,
)
from .clockbase import (  # noqa: F401 — 再导出，保持公开面不变
    ARGV_EXCERPT,
    ClockError,
    ClockNoTimersToWait,
    ClockNotFound,
    ClockParamError,
    ClockStateError,
    ClockUnreadable,
    ClockWaiterNotResolvable,
    DUE_TRIGGERS,
    DueDeferred,
    EVENT_CLOSE_HOOKS,
    EVENT_EXCERPT,
    EVENT_KINDS,
    LIFELINE_KIND,
    LIFELINE_REASON,
    LIFELINE_SUPPRESSED,
    NO_TIMERS_TO_WAIT,
    ObservedEvent,
    PARK_STATES,
    PATROL_CLEAN_TEXT,
    PATROL_DUE_HEAD,
    PATROL_GUIDE_HEAD,
    PATROL_INTERVAL_SEC,
    PATROL_REASON,
    PATROL_ROLE,
    PERIODIC_STATES,
    PROGRAM_OUTCOMES,
    PURPOSE_FROM_TARGET,
    PURPOSE_MISSING_TEXT,
    PURPOSE_PROMPT,
    PURPOSE_SOURCES,
    READING_STATES,
    RECONCILE_EVERY_SEC,
    RETIRED_TIMING_TOOLS,
    Reading,
    SCHEMA,
    STATE_REL,
    TARGET_STATES,
    TIMER_KINDS,
    TIMER_STATES,
    UTC,
    WAITER_NOT_RESOLVABLE,
    WAITS_REL,
    WAIT_FOR_KINDS,
    WAKE_REL,
    WOKE_REASONS,
    WORK_EVENT_KINDS,
    _EVENTS,
    _EVENT_COUNTS,
    _EVENT_LOCK,
    _hhmmss,
    _iso,
    _looks_like_task_id,
    _parse_iso,
    _parse_target_loose,
    _reading,
    human_sec,
    iso,
    near_seconds,
    no_timers_refusal,
    parse_iso,
    parse_wait_for,
    retire_hint,
    waiter_refusal,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockrun.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockrun`（单向）。
from .clockrun import (  # noqa: F401 — 再导出，保持公开面不变
    RESOLVED_ROOTS_MAX,
    RealClock,
    _BOOKS,
    _CLOCK,
    _CURRENT_RUN_ROLE,
    _CURRENT_RUN_TASK_ID,
    _CURRENT_WORKSPACE,
    _DEFAULT_WORKSPACE,
    _PROBE_CALLS,
    _PROCESS_START,
    _PROGRAM_UNBOOKED,
    _RESOLVED_ROOTS,
    _RESOLVED_ROOTS_LOCK,
    _atomic_json,
    _resolve_root,
    advance,
    current,
    current_run_identity,
    current_workspace,
    due_message,
    is_lifeline,
    is_patrol_timer,
    lifeline_key,
    now,
    process_started,
    purpose_of,
    reset,
    reset_books,
    reset_programs,
    run_as,
    set_default_workspace,
    state_path,
    use,
    using_workspace,
    waiting_on_text,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockevents.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockevents`（单向）。
from .clockevents import (  # noqa: F401 — 再导出，保持公开面不变
    EVENT_BUFFER,
    _CLOSE,
    _CLOSE_DEPTH,
    _CLOSE_LOCK,
    _CLOSE_STATS,
    _EVENT_SEQ,
    _PARKED,
    _close_waiters_for_event,
    _event_hits,
    _event_seq,
    _event_target_keys,
    _register_parked,
    _unregister_parked,
    event_close_reading,
    observe_event,
    observe_work,
    observed_events,
    reset_event_close,
    reset_observed_events,
    reset_parked,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockprobe.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockprobe`（单向）。
from .clockprobe import (  # noqa: F401 — 再导出，保持公开面不变
    _TARGET_PROBE,
    _judge_target,
    _probe_read,
    set_target_probe,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clocktimer.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clocktimer`（单向）。
from .clocktimer import (  # noqa: F401 — 再导出，保持公开面不变
    Timer,
    TimerBook,
    book,
    target_state,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockmem.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockmem`（单向）。
from .clockmem import (  # noqa: F401 — 再导出，保持公开面不变
    _new_timer,
    _waiter_handle_hint,
    cancel_timer,
    periodics,
    set_purpose,
    start_alarm,
    start_periodic,
    start_timer,
    stop_periodic,
    timers,
    timers_missing_purpose,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockpatrol.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockpatrol`（单向）。
from .clockpatrol import (  # noqa: F401 — 再导出，保持公开面不变
    _PATROL_PROBE,
    _first_sentence,
    _patrol_cell,
    _patrol_ids,
    next_patrol,
    patrol_anomalies,
    patrol_section,
    patrol_sop_text,
    patrol_text,
    set_patrol_probe,
    start_patrol_timer,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockprogram.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockprogram`（单向）。
from .clockprogram import (  # noqa: F401 — 再导出，保持公开面不变
    ProgramSpan,
    _calling_identity,
    _note_unbooked,
    _workspace_of,
    argv_digest,
    attach_program_pid,
    finish_program,
    is_my_program,
    not_mine_refusal,
    program_message,
    program_owner,
    program_purpose,
    program_span,
    programs,
    programs_running,
    start_program,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockwaitany.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockwaitany`（单向）。
from .clockwaitany import (  # noqa: F401 — 再导出，保持公开面不变
    HANDOFF_REL,
    HANDOFF_SUBJECT,
    WAIT_ANY_REL,
    _fired_after,
    _load_handoffs,
    _load_wait_any,
    cancel_wait_any,
    handoff_path,
    mark_handoff_seen,
    read_handoffs,
    read_wait_any,
    record_handoff,
    request_wait_any,
    reset_handoffs,
    wait_any_path,
    wait_any_reading,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockwaits.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockwaits`（单向）。
from .clockwaits import (  # noqa: F401 — 再导出，保持公开面不变
    ALLOWED_RAW_WAITS,
    CENSUS_FORMS,
    EXEMPT_PRIMITIVE_WAITS,
    GOVERNED_PRIMITIVE_WAITS,
    PROGRAM_ALLOWED_RAW,
    PROGRAM_OS_SPAWNS,
    PROGRAM_SPAWN_CALLS,
    _CENSUS_CACHE,
    _CENSUS_ROOTS,
    _LEDGER,
    _LEDGER_LOCK,
    _LEDGER_WRITTEN,
    _PROGRAM_CENSUS_CACHE,
    _SpawnVisitor,
    _WaitVisitor,
    _census_roots,
    _exempt_for,
    _iter_py_files,
    _iter_source_files,
    _ledger_key,
    _primitive_governed,
    _wait_form,
    coverage,
    flush_waits,
    note_process_wait,
    note_wait,
    program_census,
    raw_wait_census,
    reset_waits,
    set_census_roots,
    waits,
    waits_path,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockwakes.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockwakes`（单向）。
from .clockwakes import (  # noqa: F401 — 再导出，保持公开面不变
    _LIFELINE_WAKE_HANDLER,
    _LIVE_LOOPS,
    _load_wake_doc,
    _new_lifeline_timer,
    _renew_lifeline,
    arm_lifeline,
    consume_wakes,
    kill_lifeline,
    lifeline_of,
    lifeline_suppressed,
    live_loops,
    loop_ended,
    loop_is_live,
    loop_started,
    pending_wakes,
    read_wakes,
    record_wake,
    set_lifeline_wake_handler,
    wake_path,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockcost.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockcost`（单向）。
from .clockcost import (  # noqa: F401 — 再导出，保持公开面不变
    COST_FIELDS,
    _COST,
    _COST_LAST,
    _cost_blank,
    _cost_note,
    cost_reading,
    reset_costs,
)

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockfire.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockfire`（单向）。
from .clockfire import (  # noqa: F401 — 再导出，保持公开面不变
    FakeClock,
    MAX_CATCHUP_FIRES,
    PeriodicShot,
    _DUE_HANDLER,
    _FIRE_LOCK,
    _deliver_one,
    _deliver_one_locked,
    _fire_periodics,
    _probe_targets,
    _remember_wait_state,
    _select_due,
    due_timers,
    fire_due,
    next_due,
    set_due_handler,
    waiters,
)


# ---------------------------------------------------------------- 读数


# ---------------------------------------------------------------- 申请形状的两半


# ---------------------------------------------------------------- 异常清单（巡查报醒）
#
# 业主 2026-10-26：「这个是M定期巡查需要特别注意的异常行为，M可通过发送指导意见干预」。
#
# 于是"巡查时间到"那句话不许只有目的 / 间隔 / 第几次：它还要带一份当拍现算的异常清单。
# 只叫醒而不告诉 M 要看什么，那一拍就只是闹钟；清单里四类的口径见 `patrol_text`。
#
# 分工与 `set_due_handler` / `set_target_probe` 同一条切法：本模块只负责"把清单拼进报醒"
# 这一半。清单里每一条事实（停滞 / 静默 / 未消板项 / 被拦的结项原因）都要读台账、板项
# 与名册，那是工具层的事，经 `set_patrol_probe` 接进来 —— 本模块不拖 Store 进来。

# 停滞那一段的阈值从哪来：读口给的那一格（`stalled` 里 `threshold_sec`）。本模块刻意不写
# 自己的 N —— 判据的真身在 `conductor.agent_state`（`STALLED_AFTER_SEC` 加
# `out/steps/<台账号>.json` 那一刻），报醒只负责把它的 `stalled_sec` 与阈值念出来。
# 两处各写一个 N 的代价很具体：同一个子在巡查里"停滞"、在页面读数里"没停滞"。


def observe_message(rec: Mapping[str, Any]) -> ObservedEvent | None:
    """从一条会话事件里认出"发消息 / 答复"，转成时钟事件。返回 `None` = 不关时钟的事。

    认法（三态归到三类里，不许漏）：

    - `kind != "agent_message"` => 不是消息，返回 `None`；
    - `progress` 为真 => 「只落消息、不记事件」，返回 `None`（D11 第③件：进度对账
      不许唤醒"等它"的计时器；消息本身已由 `send_message` 落在会话里，父照常读得到）；
    - 有 `reply_to` => `reply`（对某条消息的答复）；
    - 其余 => `message`。

    `target`（谁产生的）优先取 `from_task_id`（发信人那件活），其次取 `from`
    （角色名）—— 等的是任务号就按任务号对上，等的是角色就按角色对上。
    """
    if str(rec.get("kind") or "") != "agent_message":
        return None
    if rec.get("progress"):
        #: 进度上报（D11 第③件，2026-11-09）：`send_message(..., extra={"progress": True})`
        #: 标记的是"还在跑"的对账（每满 N 步的步数报告），不是"被等对象说了话"。
        #: 消息本身已经落进会话（`send_message` 先 append，本钩子只是旁路）⇒ 父下一步
        #: 照常从收件箱读到；这里只是「不」把它记成时钟事件 ⇒ 不参与 `_event_hits`、
        #: 也不触发 `target_event` 唤醒（否则父的等待计时器会被一条进度留言叫醒，
        #: 真机 33 条「时间到」里有 8 条就是这么来的）。
        return None
    body = str(rec.get("body") or "")
    subject = str(rec.get("subject") or "")
    content = f"{subject}：{body}" if subject else body
    kind = "reply" if str(rec.get("reply_to") or "") else "message"
    sender = str(rec.get("from_task_id") or "")
    recipient = str(rec.get("to") or "")
    event = observe_event(
        kind,
        task_id=sender,
        from_task_id=sender,
        to_task_id=recipient,
        role=str(rec.get("from") or ""),
        content=content,
        message_id=str(rec.get("msg_id") or ""),
    )
    # 投递这一侧再记一格（业主 2026-10-26：「等父也要真的能醒」）：`message` 认的是
    # "谁说的"，而"等父"要认的是"父给我投来了一条话" —— 父不交差（那是 handoff），
    # 它只会发消息；两档分开记，读的人（与判据）能看见投递这件事真的发生过。
    try:
        observe_event("delivery", task_id=sender, from_task_id=sender,
                      to_task_id=recipient, role=str(rec.get("from") or ""),
                      content=content, message_id=str(rec.get("msg_id") or ""))
    except ClockError:  # pragma: no cover - 受控词表刚加这一档，这里只做防御
        pass
    return event


# ------------------------------------------------------- 轮查：一个特殊计时器 + 一套动作
#
# 业主 2026-10-27 傍晚（唯一权威，逐字）：
#
#     「20分钟计时 -> 时间到立刻进自动审阅工具 -> 审完后 M 自由行动 -> M 无事可做后
#       启动轮查计时。注意：20分钟间隔内接收到任何其它消息 M 一样会被唤醒（这与计时器
#       不阻塞进程的设计一致，轮查也不阻塞进程，轮查只是个特殊计时器，到点后不是返回
#       一句提醒，而是一套需执行的规范动作）」
#
# 两半各落在哪：特殊计时器这一半是 `start_patrol_timer` / `next_patrol` /
# `is_patrol_timer`（本节），"到点那一下的正文是 SOP"这一半是 `patrol_sop_text`
# 与 `due_message` 的 `patrol_sop` 那一格。异常清单那一半不在这里另写 —— 它仍然只有
# `patrol_section` 一份（周期性巡查早就用它，轮查这一条读同一个落点）。


# ---------------------------------------------------------------- 时钟实现


# ---------------------------------------------------------------- 计时器


# ---------------------------------------------------------------- 等程序（业主 2026-10-27 第一条）


# ---------------------------------------------------------------- 停程序（G1）

#: 停一条程序时给它的宽限秒数：先让它自己收尾，过了这个窗口才真杀。
#:
#: 为什么是常量而不是工具的参数（业主 2026-10-26 的 G1 施工单：「先 terminate、
#: 超时再 kill（给宽限秒数常量）」）：宽限是"这一刀的手感"，不是每一次调用该重新
#: 商量的口径。模型多给一个参数就多一种把宽限调成 0 的写法 —— 那是把"优雅"变成
#: "直接砍"，而读数上两者长得一样。
PROGRAM_STOP_GRACE_SEC: float = 3.0

#: 宽限与等待窗口里的轮询间隔（每一拍都进主时钟的等待账）。
PROGRAM_STOP_POLL_SEC: float = 0.1

#: 真杀之后最多再等它从进程表上消失多久；等不到就如实报 `timeout`。
PROGRAM_STOP_WAIT_SEC: float = 5.0

#: "停一条程序"的受控读数（`stop_program` 的 `result` 只取这几档，一档都不许折平）：
#:
#: - `killed`：真的把它停掉了（进程没了，那条程序计时器按 `outcome="killed"` 收口）；
#: - `already_exited`：它本来就结束了（幂等那一档：查过了、不是第二次杀成功，行不改）；
#: - `timeout`：杀不动 —— 窗口过了它还在跑（账上那条保持 pending，"它还在跑"必须读得出来）；
#: - `not_mine`：不是这一趟起的（受控拒绝；别人的与账上没有归属的都在这一档）；
#: - `not_found`：查过了、没有可停的那一条（编号不存在 / 不是程序计时器 / 账上没有 pid）。
#:
#: 为什么 `timeout` 与 `killed` 不许合并：合并之后"我杀了它"与"我没杀掉它"在读数上
#: 一样，而那正是这一批要修的东西（昨晚 15 个野进程是被"看起来杀了"留下的）。
PROGRAM_STOP_RESULTS: tuple[str, ...] = ("killed", "already_exited", "timeout",
                                         "not_mine", "not_found")


def process_alive(pid: int) -> bool:
    """这个 pid 还活着吗（唯一判法在 `stopctl.alive`，本模块不另写一份）。

    为什么不在这里写 `os.kill(pid, 0)`：Windows 上那不是探活，它会
    `TerminateProcess`（把被探测的进程杀掉）；`tasklist` 在受限环境里又拿不到读数。
    `stopctl.alive` 两条路都实测过（`OpenProcess(SYNCHRONIZE)` +
    `WaitForSingleObject`）。探不了时它说"不活着" —— 调用方据此不杀，绝不假装杀过。

    代价写在明处：探不了的那一档，`stop_program` 会落成 `already_exited`（不杀是安全
    方向，但"没查成"与"它已经自己走了"在这一格分不开 —— 探活是唯一判法，它没有三态口）。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        from . import stopctl as SC
    except Exception:  # noqa: BLE001 - 连探活模块都读不到：按"不活着"处置
        return False
    try:
        return bool(SC.alive(pid_int))
    except Exception:  # noqa: BLE001 - 见 docstring 最后一句
        return False


def _exit_code_of(pid: int) -> int | None:
    """被杀进程的退出码（读得到就给，读不到就是 None —— 不是 0）。

    两种平台各一条路，都不用 subprocess（`program_census` 会把 clock.py 里新出现的
    起进程点报成"程序在跑而账上没有计时器"）：

    - Windows：`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
      `GetExitCodeProcess`；`STILL_ACTIVE`（259）说明它其实还在跑 ⇒ None。
      句柄一关进程对象就没了 ⇒ 这条常常读不到，那是诚实的 None。
    - POSIX：只有自家子进程收得到（`waitpid(WNOHANG)`）；不是自家子进程的
      `ChildProcessError` ⇒ None（"读不到"与"退出码是 0"必须分得开）。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return None
    if pid_int <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = ctypes.c_void_p
            k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = k32.OpenProcess(0x1000, 0, pid_int)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                code = ctypes.c_ulong()
                if not k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                    return None
                value = int(code.value)
            finally:
                k32.CloseHandle(ctypes.c_void_p(handle))
            return None if value == 259 else value   # 259 = STILL_ACTIVE
        except Exception:  # noqa: BLE001 - 读不到就是 None
            return None
    try:
        got, status = os.waitpid(pid_int, os.WNOHANG)
    except (ChildProcessError, OSError):
        return None
    if got != pid_int:
        return None
    return int(os.waitstatus_to_exitcode(status)) if hasattr(os, "waitstatus_to_exitcode") \
        else None


def _terminate_pid(pid: int) -> dict[str, Any]:
    """第一刀：请它自己停。如实报"这一刀走了哪条路、有没有真的发出去"。

    ## Windows 上"优雅"到底指什么（业主 2026-10-26 的裁定）

    本平台没有"发给 console 子进程的请停信号"：`os.kill` 在这里就是
    `TerminateProcess`，与 kill 是同一个系统调用 —— 所以 Windows 上"先请停再强杀"
    在信号语义上没有任何差别。这一批里"优雅"指的是时机与告知，不是信号语义：

    1. 先落一条"有人喊停"的账（这一条程序计时器的 note 与 `program.stop` 的读数），
       并且先给它一个宽限窗口让它自己退出（有的程序会看自己的哨兵文件、或收到自己的
       停机条件就收尾）；
    2. 只有宽限窗口过了、它还在，才真动手；动手那一刻读数里写着 `force_kill`。
    3. 真要发 CTRL_BREAK 必须有进程组（`CREATE_NEW_PROCESS_GROUP`）——今天七个起程序
       的落点都没有开进程组（只有网页端的 detached 起法开了），所以这一档不假装发过：
       `sent=False` 逐字写着"没发"。

    POSIX 上这一刀是真信号（SIGTERM），收尾机会就落在这一步里。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return {"sent": False, "via": "", "why": f"pid 不是整数：{pid!r}"}
    if os.name != "nt":
        try:
            os.kill(pid_int, signal.SIGTERM)
            return {"sent": True, "via": "SIGTERM", "why": ""}
        except OSError as exc:
            return {"sent": False, "via": "SIGTERM", "why": f"{type(exc).__name__}: {exc}"}
    return {"sent": False, "via": "",
            "why": ("Windows 上没有可发给 console 子进程的请停信号（这一档由宽限窗口"
                    "承担：先等它自己退，过了窗口才强杀）")}


def _terminate_process_handle(pid: int, *, exit_code: int = 9) -> dict[str, Any]:
    """最后一刀（只在没有作业对象时用）：`TerminateProcess`，只收根进程。"""
    try:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.OpenProcess(0x0001, 0, int(pid))   # PROCESS_TERMINATE
        if not handle:
            return {"killed": False, "via": "TerminateProcess",
                    "why": f"OpenProcess 失败（错误码 {ctypes.get_last_error()}）"}
        try:
            ok = bool(k32.TerminateProcess(ctypes.c_void_p(handle), int(exit_code)))
            why = "" if ok else f"TerminateProcess 失败（错误码 {ctypes.get_last_error()}）"
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
        return {"killed": ok, "via": "TerminateProcess", "why": why,
                "note": "这条路只收根进程：它已经生出来的子孙不在这一刀里"}
    except Exception as exc:  # noqa: BLE001 - 杀不成要如实报，不许假装
        return {"killed": False, "via": "TerminateProcess",
                "why": f"{type(exc).__name__}: {exc}"}


def _force_kill_pid(pid: int) -> dict[str, Any]:
    """第二刀：真收掉它（Windows 优先走作业对象，一次收掉整棵传递树）。"""
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return {"killed": False, "via": "", "why": f"pid 不是整数：{pid!r}"}
    if os.name != "nt":
        try:
            os.kill(pid_int, signal.SIGKILL)
            return {"killed": True, "via": "SIGKILL", "why": ""}
        except OSError as exc:
            return {"killed": False, "via": "SIGKILL", "why": f"{type(exc).__name__}: {exc}"}
    job_why = ""
    try:
        from . import jobobject as JO

        if JO.available():
            job = JO.create_job(f"agentflow-program-stop-{pid_int}")
            try:
                placed = JO.assign_tree(job, pid_int)
                ok = bool(JO.terminate(job, exit_code=9))
                left = JO.assigned_pids(job)
                return {"killed": ok or not process_alive(pid_int), "via": "job",
                        "why": "", "assigned": list(placed.get("assigned") or ()),
                        "failed": list(placed.get("failed") or ()),
                        "left": list(left.get("pids") or ())}
            finally:
                try:
                    JO.close(job)
                except Exception:  # noqa: BLE001 - 关句柄失败不该带走调用方
                    pass
        job_why = f"作业对象用不了：{JO.unavailable_reason()}"
    except Exception as exc:  # noqa: BLE001 - 这条路走不通就退回下一刀（读数里留着）
        job_why = f"作业对象那条路失败：{type(exc).__name__}: {exc}"
    got = dict(_terminate_process_handle(pid_int))
    if job_why:
        got["job_attempt"] = job_why
    return got


def _wait_until_gone(pid: int, seconds: float, *, purpose: str) -> float:
    """等这个 pid 从进程表上消失，返回实际等了多久（不抛）。

    每一拍都走 `await_io`（主时钟的等待账是"所有等一会儿"的唯一入口，也是
    `raw_wait_census` 的判据：clock.py 里不许出现裸 `time.sleep`）。轮询次数由
    `PROGRAM_STOP_POLL_SEC` 与窗口长度算出来 —— 装上假时钟时 `await_io` 不真睡，
    光靠单调计数会把这里变成忙转，所以圈数也要有上限。
    """
    limit = max(0.0, float(seconds))
    step = max(0.01, float(PROGRAM_STOP_POLL_SEC))
    rounds = max(1, int(limit / step) + 2)
    started = time.monotonic()
    for _ in range(rounds):
        if not process_alive(int(pid)):
            break
        left = limit - (time.monotonic() - started)
        if left <= 0:
            break
        await_io(min(step, left), purpose, kind="program_stop",
                 where="clock._wait_until_gone", waited_for=f"pid:{int(pid)}")
    return max(0.0, time.monotonic() - started)


def _elapsed_of(timer: Timer) -> float | None:
    """这条程序从登记到现在过了多久（读不到时钟 => None，不是 0）。"""
    got = now()
    if got.status == "unknown" or got.wall is None:
        return None
    try:
        created = _parse_iso(timer.created_at)
    except ClockError:
        return None
    return max(0.0, (got.wall - created).total_seconds())


def _wake_waiters(workspace: str | Path, timer_id: str) -> dict[str, Any]:
    """把"等这条程序"的那几条表推一次到点（走既有的 `fire_due`，不另拼一条报醒）。

    为什么不是在 `finish_program` 里直接投递：收口与投递是两件事（一条程序计时器收口
    之后可能根本没人等它），而投递的唯一实现在到点动作那一处（`_deliver_due`：落
    mailbox 项 + 唤醒标记）。这里只是"别等到下一步才推"。
    """
    out: dict[str, Any] = {"checked": False, "watching": 0, "woken": 0,
                           "wake_ids": [], "reason": ""}
    wanted = f"program:{str(timer_id)}"
    try:
        bucket = book(workspace)
        watching = [t for t in bucket.all()
                    if t.state == "pending"
                    and str(t.wait_for_resolved or t.wait_for or "") == wanted]
    except ClockStateError as exc:
        out["reason"] = f"等它的那几条表读不成（{exc}）"
        return out
    out["watching"] = len(watching)
    # 程序收口是事件产生点（`EVENT_CLOSE_HOOKS["stop_program"]` 那一行）：按 `program:<号>`
    # 撞一次反查索引，把等它的那几条判进热表 —— 于是下面这一次 `fire_due` 只会投它们，
    # 不必扫全表（也因此在"什么都没到点"的拍上不会退化成 O(全表)）。
    try:
        _close_waiters_for_event("stop_program", [wanted])
    except Exception as exc:  # noqa: BLE001 - 消账炸了不带走下面这一次推进
        out["reason"] = f"消账没跑成（{type(exc).__name__}: {exc}）"
    try:
        report = fire_due(workspace)
    except Exception as exc:  # noqa: BLE001 - 推不成是"没查成"，不许折成"没人等它"
        out["reason"] = (f"到点动作没推成（{type(exc).__name__}: {exc}）⇒ "
                         "等它的那几条保持 pending，下一次步进会再推")
        return out
    out["checked"] = bool(report.get("checked", True))
    ids = {str(t.timer_id) for t in watching}
    woken = [r for r in (report.get("fired") or ()) if str(r.get("timer_id")) in ids]
    out["woken"] = len(woken)
    out["wake_ids"] = [str(r.get("wake_id") or "") for r in woken if r.get("wake_id")]
    if not out["checked"]:
        out["reason"] = f"时钟读不到 ⇒ 判不了 due（{report.get('reason') or '没查成'}）"
    elif watching and not woken:
        out["reason"] = "等它的那几条还在 pending（到点动作没接上或被推迟）⇒ 这一刀没把它们叫醒"
    return out


def _stop_one_program(workspace: str | Path, timer_id: str, *, task_id: str,
                      role: str, grace_sec: float, wait_sec: float,
                      reason: str) -> dict[str, Any]:
    """停一条（`stop_program` 的真身：逐条读数与四档判据都在这里）。"""
    out: dict[str, Any] = {
        "checked": True, "timer_id": str(timer_id), "result": "not_found",
        "program": "", "argv_digest": "", "pid": None, "state": "", "outcome": "",
        "elapsed_sec": None, "exit_code": None, "mine": False,
        "task_id": "", "role": "", "owner": {}, "terminate": {}, "force_kill": {},
        "waited_sec": 0.0, "still_alive": [], "watching": 0, "woken": 0,
        "wake_ids": [], "reason": "",
    }
    bucket = book(workspace)      # 读不成抛 ClockStateError：由工具层报 checked=False
    timer = bucket.get(str(timer_id))
    if timer is None:
        out["reason"] = f"没有 {timer_id} 这一条程序计时器（不是'已经结束了'）"
        return out
    if not timer.is_program:
        out["state"] = timer.state
        out["reason"] = (f"{timer_id} 是 kind={timer.kind!r} 的条目，不是程序计时器 —— "
                         "停程序只认 kind='program' 那一条（等时间/等谁的表用 clock.timer_cancel）")
        return out
    out.update({"program": timer.program, "argv_digest": timer.argv_digest,
                "pid": timer.pid, "state": timer.state, "outcome": timer.outcome,
                "elapsed_sec": timer.elapsed_sec, "exit_code": timer.exit_code,
                "task_id": str(timer.task_id or ""), "role": str(timer.role or ""),
                "owner": program_owner(timer),
                "mine": is_my_program(timer, task_id=task_id, role=role)})
    if not out["mine"]:
        out["result"] = "not_mine"
        out["reason"] = not_mine_refusal(timer, task_id=task_id, role=role)
        return out
    if timer.state != "pending":
        out["result"] = "already_exited"
        out["reason"] = (f"{timer_id} 早就收口了（state={timer.state}, "
                         f"outcome={timer.outcome or '没记'}）—— 查过了，不是第二次杀掉；"
                         "这一行一个字都不改（幂等）")
        return out
    try:
        pid = int(timer.pid or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        out["reason"] = ("这一条账上没有 pid（attach_program_pid 没补上）⇒ 没有可停的对象；"
                         "程序行保持 pending，它还在不在看 program.list 的 running 那一格")
        return out
    if not process_alive(pid):
        out["result"] = "already_exited"
        out["reason"] = (f"pid {pid} 已经不在进程表上了 —— 查过了、它自己走掉的；"
                         "账上那条还是 pending（收口归起它的 program_span，这一刀不改行）")
        return out
    # ---- 第一刀 + 宽限窗口（"优雅"= 时机与告知，见 `_terminate_pid` 的 docstring）
    terminate = _terminate_pid(pid)
    out["terminate"] = terminate
    waited = _wait_until_gone(pid, float(grace_sec),
                              purpose="停程序：宽限期里等它自己收尾")
    # ---- 第二刀：只有还活着才动手（读数里写着走了哪条路）
    force: dict[str, Any] = {}
    if process_alive(pid):
        force = _force_kill_pid(pid)
        out["force_kill"] = force
        waited += _wait_until_gone(pid, float(wait_sec),
                                   purpose="停程序：真杀之后等它从进程表上消失")
    out["waited_sec"] = round(waited, 3)
    if process_alive(pid):
        out["result"] = "timeout"
        out["still_alive"] = [pid]
        out["state"] = timer.state
        out["reason"] = (f"pid {pid} 在 {float(grace_sec):g}+{float(wait_sec):g} 秒里没有消失"
                         f"（杀不动：{force.get('why') or terminate.get('why') or '原因没有读数'}）"
                         "—— 账上那条保持 pending、程序行不改：它还在跑这件事必须读得出来")
        return out
    # ---- 真没了：按 killed 收口（走既有的 finish_program），再推一次等它的人
    elapsed = _elapsed_of(timer)
    exit_code = _exit_code_of(pid)
    note_bits = [f"被点名停下（program.stop，操作者台账号 {task_id or '（没给）'}）"]
    if str(reason or "").strip():
        note_bits.append(str(reason).strip())
    if terminate.get("via"):
        note_bits.append(f"第一刀 {terminate['via']}")
    elif terminate.get("why"):
        note_bits.append(f"第一刀没发（{terminate['why']}）")
    if force.get("via"):
        note_bits.append(f"第二刀 {force['via']}")
    closed, state = finish_program(workspace, timer_id, outcome="killed",
                                   exit_code=exit_code, elapsed_sec=elapsed,
                                   note="；".join(note_bits))
    out.update({"result": "killed", "state": getattr(closed, "state", ""),
                "outcome": getattr(closed, "outcome", ""),
                "elapsed_sec": getattr(closed, "elapsed_sec", None),
                "exit_code": getattr(closed, "exit_code", None),
                "finish_state": state})
    out["reason"] = program_message(program=timer.program, outcome="killed",
                                    exit_code=out["exit_code"],
                                    elapsed_sec=out["elapsed_sec"],
                                    purpose=timer.purpose)
    wake = _wake_waiters(workspace, timer_id)
    out.update({"watching": int(wake.get("watching") or 0),
                "woken": int(wake.get("woken") or 0),
                "wake_ids": list(wake.get("wake_ids") or ()),
                "wake_checked": bool(wake.get("checked")),
                "wake_reason": str(wake.get("reason") or "")})
    return out


def stop_program(workspace: str | Path, timer_id: str, *, task_id: str,
                 role: str = "", grace_sec: float = PROGRAM_STOP_GRACE_SEC,
                 wait_sec: float = PROGRAM_STOP_WAIT_SEC,
                 reason: str = "") -> dict[str, Any]:
    """停掉一条"我这一趟起的"程序：先宽限、再真杀，然后按 `killed` 收口并唤醒等它的人。

    业主 2026-10-26 的 G1（逐字）：「重点完善子代理杀自己发出去的程序进程的工具」。

    ## 这个函数做四件，缺一件就等于没做

    1. 受控拒绝：不是这一趟起的（别人的 / 账上没有归属的）⇒ `result="not_mine"`，
       一个进程都不碰（`is_my_program` 是唯一判据，`not_mine_refusal` 是唯一拒信）；
    2. 先 terminate、超时再 kill：宽限 `PROGRAM_STOP_GRACE_SEC` 秒（`_terminate_pid`），
       过了窗口还在才 `_force_kill_pid`（Windows 上优先走作业对象，一次收整棵树）；
    3. 等它真的消失（`_wait_until_gone`，上限 `PROGRAM_STOP_WAIT_SEC`）——
       等不到就 `result="timeout"` 并点名还在跑的 pid，账上那条保持 pending；
    4. 收口 + 唤醒：真没了才 `finish_program(outcome="killed", elapsed_sec=…,
       exit_code=…)`，再推一次 `fire_due` 把等它的那几条叫醒。

    ## 不抛异常

    这四档是读数，不是异常（`PROGRAM_STOP_RESULTS`）。唯一的抛出是簿记读不成
    （`ClockStateError`）—— 那是"没查成"，由工具层折成 `checked=False`，
    绝不折成"没有这一条"。

    ## 已知边界（两条，都不假装）

    - pid 复用：这个 pid 是起进程那一刻记下的，且只在 pending 的账上；账上那条如果
      已经被别的进程占着同一个 pid，这一刀还是会落下去 —— pid 级杀法没有更强的
      身份校验（`Popen` 对象早就不在手上了）。
    - Windows 上的"优雅"是时机而不是信号语义（见 `_terminate_pid`）。
    """
    grace = max(0.0, float(grace_sec))
    wait = max(0.0, float(wait_sec))
    out = _stop_one_program(workspace, str(timer_id), task_id=str(task_id or ""),
                            role=str(role or ""), grace_sec=grace, wait_sec=wait,
                            reason=str(reason or ""))
    out["grace_sec"] = round(grace, 3)
    out["wait_sec"] = round(wait, 3)
    return out


def programs_owned(workspace: str | Path, *, task_id: str = "",
                   role: str = "", include_done: bool = False) -> dict[str, Any]:
    """这个工作区的程序按归属分桶（`program.list` 的读侧，判据也读这里）。

    四桶，一格都不折平：

    - `mine`：我这一趟起的（`is_my_program` 为真；`include_done` 决定含不含已收口的）；
    - `unowned`：账上没有归属的（改前存量的形态：`task_id` 空）—— 它们不归任何人，
      既不算我的，也不许被 `program.stop` 杀掉；单列出来是为了让人看见"存量还在"；
    - `others`：别人的（有归属、但不是我的）—— 只给条数，不给 pid（别人的程序不该
      在我的读数里被点名）；
    - 三态：簿记读不成 => `checked=False`（"没查成"不是"没有程序在跑"）。
    """
    out: dict[str, Any] = {"checked": False, "mine": [], "unowned": [], "others": 0,
                           "others_running": 0, "count": 0, "running": 0,
                           "reason": ""}
    try:
        rows = [t for t in book(workspace).all() if t.is_program]
    except Exception as exc:  # noqa: BLE001 - 读不成是"没查成"
        out["reason"] = f"程序计时器读不成：{type(exc).__name__}: {exc}"
        return out
    if not include_done:
        rows = [t for t in rows if t.state == "pending"]
    mine: list[Timer] = []
    unowned: list[Timer] = []
    others = 0
    others_running = 0
    running = 0
    for timer in rows:
        if timer.state == "pending":
            running += 1
        if not str(timer.task_id or ""):
            unowned.append(timer)
        elif is_my_program(timer, task_id=task_id, role=role):
            mine.append(timer)
        else:
            others += 1
            if timer.state == "pending":
                others_running += 1
    out.update({"checked": True, "mine": mine, "unowned": unowned,
                "others": others, "others_running": others_running,
                "count": len(rows),
                "running": running,
                "reason": ""})
    return out


# ---------------------------------------------------------------- 等待任意计时器返回


# ---------------------------------------------------------------- 交差（业主 2026-10-27 第四条）


# ---------------------------------------------------------------- 工作区挂点


# ---------------------------------------------------------------- 被时钟观测到的事件


# ---------------------------------------------------------------- 到点动作


# ---------------------------------------------------------------- 成本读数
#
# 业主 2026-10-27 的施工单第 ① 条：「最近一次 fire_due / due_timers 的 pending_count /
# scan_ms / target_probe_count / reconcile_count，以及下一拍应当在多少秒后醒」。
#
# 它必须是读数，不是"本次调用的入参与返回值"：
#   · 三态：没跑过 / 跑不成 / 跑成了，三档分开，`checked=False` 加 `reason`；
#   · 读不成的格子是 `None`，不是 0 —— 把"没量到"折成 0 会把一次成功但零成本的判定
#     和一次根本没量的判定读成同一件事；
#   · 不许改任何既有字段的含义：这一格里一个既有的键都不出现（它是新增的一份旁路账）。


# ---------------------------------------------------------------- 事件消账
#
# 业主 2026-10-27 第二条：「等谁」的那一半不许等下一拍扫表 —— 事件一到，等它的那条表
# 当场判掉。三层缺一不可：
#
# 1. 反查索引 `TimerBook._waiters`：`target_key -> 等它的计时器集合`，O(1) 查到人；
# 2. 事件消账（本节）：事件产生点到达时，用它带的对象键哈希查一次索引，
#    把等它的那几条就地判成到点并交给 `_DUE_HANDLER`（不扫表）；
# 3. 补偿对账（`RECONCILE_EVERY_SEC`）：任何漏发事件的等待，下一次对账时照样判掉。
#    没有它，事件驱动就是"漏一个事件 => 那条表永久挂起"。
#
# 判据（`tests/test_the_clock_scales_with_the_book.py`）：
#   · 事件到达 => 那条表在下一次 pump 之前就 fired，时延读数 ≈ 0（c）；
#   · 故意把某个产生点打桩掉 => 对账之后仍然 fired（d，安全阀）；
#   · 未登记的 source => `ClockParamError`（表是强制的，不是注释）。


# ---------------------------------------------------------------- 等待账


# ---------------------------------------------------------------- 原始等待的普查


# ---------------------------------------------------------------- 唤醒标记


def await_io(seconds: float, purpose: str, *, kind: str = "io", where: str = "",
             waited_for: str = "", sleep: Callable[[float], None] | None = None
             ) -> dict[str, Any]:
    """真睡 `seconds` 秒（保持原语义），并在主时钟的账上记一条。

    这是框架内部所有"等一会儿"的唯一入口。`kind` 说这是哪一类等待（`retry` /
    `rate_limit` / `poll` / `drain` / `user` …），`where` 说它落在哪个位置
    （`fetch._download_via` 这种），`purpose` 说为什么等 —— 三样都进账，
    `clock.now` 的复合读数把账汇总成 `waits_recorded`。

    假时钟在装的时候不免掉真睡是不可接受的：判据里等 20 分钟没有意义，而且
    "主时钟是假的"本来就意味着"时间由我拨"。所以当前时钟是假的时候真睡被免掉，
    账上照记，`skipped` 计数 +1（读数里看得见"这几条没真等"）。
    """
    body = str(purpose or "").strip()
    if not body:
        raise ClockParamError(
            "框架内部的等待必须写目的（purpose）：写不出目的的等待不许存在")
    step = float(seconds)
    if step < 0:
        raise ClockParamError(f"等待时长不能是负数，收到 {seconds!r}")
    fake = str(getattr(current(), "name", "real") or "") == "fake"
    do_sleep = sleep if sleep is not None else (None if fake else time.sleep)
    took = 0.0
    if do_sleep is not None and step > 0:
        start = time.monotonic()
        do_sleep(step)
        took = time.monotonic() - start
    return note_wait(step, body, kind=kind, where=where, waited_for=waited_for,
                     slept=took if do_sleep is not None else 0.0,
                     skipped=fake or do_sleep is None)

__all__ = [
    "ALLOWED_RAW_WAITS",
    "ARGV_EXCERPT",
    "CENSUS_FORMS",
    "ClockError",
    "ClockNotFound",
    "ClockNoTimersToWait",
    "ClockParamError",
    "ClockStateError",
    "ClockUnreadable",
    "ClockWaiterNotResolvable",
    "NO_TIMERS_TO_WAIT",
    "WAITER_NOT_RESOLVABLE",
    "no_timers_refusal",
    "waiter_refusal",
    "waiting_on_text",
    "DUE_TRIGGERS",
    "EVENT_BUFFER",
    "EVENT_EXCERPT",
    "EVENT_KINDS",
    "DueDeferred",
    "HANDOFF_REL",
    "HANDOFF_SUBJECT",
    "ObservedEvent",
    "PROGRAM_ALLOWED_RAW",
    "PROGRAM_OUTCOMES",
    "PROGRAM_SPAWN_CALLS",
    "PROGRAM_STOP_GRACE_SEC",
    "PROGRAM_STOP_POLL_SEC",
    "PROGRAM_STOP_RESULTS",
    "PROGRAM_STOP_WAIT_SEC",
    "PURPOSE_FROM_TARGET",
    "PURPOSE_SOURCES",
    "PATROL_DUE_HEAD",
    "PATROL_INTERVAL_SEC",
    "PATROL_REASON",
    "PATROL_ROLE",
    "ProgramSpan",
    "WAIT_ANY_REL",
    "WOKE_REASONS",
    "EXEMPT_PRIMITIVE_WAITS",
    "FakeClock",
    "GOVERNED_PRIMITIVE_WAITS",
    "MAX_CATCHUP_FIRES",
    "PERIODIC_STATES",
    "PURPOSE_MISSING_TEXT",
    "PURPOSE_PROMPT",
    "Periodic",
    "PeriodicShot",
    "READING_STATES",
    "Reading",
    "RealClock",
    "SCHEMA",
    "STATE_REL",
    "TARGET_STATES",
    "TIMER_KINDS",
    "TIMER_STATES",
    "Timer",
    "TimerBook",
    "WAITS_REL",
    "WAIT_FOR_KINDS",
    "WAKE_REL",
    "advance",
    "argv_digest",
    "attach_program_pid",
    "await_io",
    "book",
    "cancel_timer",
    "cancel_wait_any",
    "consume_wakes",
    "coverage",
    "current",
    "current_run_identity",
    "current_workspace",
    "due_message",
    "due_timers",
    "finish_program",
    "fire_due",
    "flush_waits",
    "handoff_path",
    "human_sec",
    "now",
    "note_wait",
    "observe_event",
    "observe_message",
    "observed_events",
    "parse_iso",
    "parse_wait_for",
    "pending_wakes",
    "periodics",
    "iso",
    "is_my_program",
    "not_mine_refusal",
    "process_alive",
    "process_started",
    "program_census",
    "program_message",
    "program_owner",
    "program_span",
    "programs",
    "programs_owned",
    "programs_running",
    "program_purpose",
    "purpose_of",
    "is_patrol_timer",
    "next_patrol",
    "patrol_sop_text",
    "raw_wait_census",
    "read_handoffs",
    "mark_handoff_seen",
    "read_wakes",
    "read_wait_any",
    "start_patrol_timer",
    "record_handoff",
    "record_wake",
    "request_wait_any",
    "reset_handoffs",
    "reset_programs",
    "retire_hint",
    "RETIRED_TIMING_TOOLS",
    "reset",
    "reset_books",
    "reset_observed_events",
    "reset_waits",
    "run_as",
    "set_census_roots",
    "set_default_workspace",
    "set_due_handler",
    "set_purpose",
    "set_target_probe",
    "arm_lifeline",
    "is_lifeline",
    "lifeline_key",
    "lifeline_of",
    "start_alarm",
    "start_periodic",
    "start_program",
    "start_timer",
    "state_path",
    "stop_periodic",
    "stop_program",
    "target_state",
    "timers",
    "timers_missing_purpose",
    "use",
    "using_workspace",
    "wait_any_path",
    "wait_any_reading",
    "waits",
    "waits_path",
    "wake_path",
]


# ---------------------------------------------------------------- 兜底计时器（业主 2026-10-29）
