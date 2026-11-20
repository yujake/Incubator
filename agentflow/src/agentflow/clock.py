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

业主口径「还有超800的？派人拆」⇒ 本文件 6,777 行按依赖方向由底向上拆成 16 个顶层模块
（每个 ≤ 800 行）。现在门面只做三件事：保留这份契约文档、再导出（所有
`from .clock import X` 的调用点一个字都没改）、以及承载 `observe_message` —— 它是
`sessions.append` 钩子的落点，判据按 `clock.observe_event` 打桩，所以它与被打桩的那个
名字必须同处一份（SPLIT-1 曾把它搬走又退回，见 c2846ec2）。依赖方向一律「上层 → 下层」，
不许反向：

     clockbase（词表 / 三态读数 / 事件原语）
        ↑
     clockrun（唯一取时口 / 进程内簿记 / 复位 / 到点消息拼句）
        ↑
     clockevents（观测窗 / 消账）· clockbookindex（簿记索引面）· clockprobe（等谁探针）
        ↑
     clocktimer（Timer / TimerBook / book / target_state —— 运行期环核）
        ↑
     clockmem（起表）· clockpatrol（巡查）· clockprogram（程序计时器）
        ↑
     clockwaitany（wait_any / 交差）· clockwaits（等待账 / 两把普查）·
     clockwakes（唤醒 / lifeline）· clockcost（到点成本读数）
        ↑
     clockfire（到点）· clockstop（停程序）· clockpublic（公开面清单）

"可变量没有跨模块共享，只有归谁所有"这条纪律写在 `clockrun` 模块头；每一层的落位与
"为什么它必须是顶层模块"写在 `tests/test_release_all.py` 的 `_AGENTFLOW_TOP_LEVEL_MODULES` 里。
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
    await_io,
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

# 2026-11-20（业主口径：体量软基线不抬，只拆）：下面这些名字的实现在
# `clockstop.py`，这里按原样再导出 —— 所有 `from .clock import ...` 的调用点
# 一个字都不用改，依赖方向是 `clock` → `clockstop`（单向）。
from .clockstop import (  # noqa: F401 — 再导出，保持公开面不变
    PROGRAM_STOP_GRACE_SEC,
    PROGRAM_STOP_POLL_SEC,
    PROGRAM_STOP_RESULTS,
    PROGRAM_STOP_WAIT_SEC,
    _elapsed_of,
    _exit_code_of,
    _force_kill_pid,
    _stop_one_program,
    _terminate_pid,
    _terminate_process_handle,
    _wait_until_gone,
    _wake_waiters,
    process_alive,
    programs_owned,
    stop_program,
)

# 2026-11-20（拆 clock.py 收口）：公开面清单 `__all__` 的实现在 `clockpublic.py`，
# 这里原样再导出 —— `clock.__all__` 仍然是那 150 个名字。
from .clockpublic import __all__  # noqa: F401 — 公开面清单的再导出


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
