# -*- coding: utf-8 -*-
"""连接类失败的有界退避闸：从 DSH 的 `ClientBridgeLifecycle` 逐条移植。

## 为什么要有它（本仓的缺口）

`agent_loop` 的 `no_reply` 那一支把失败分成三档：`judge_timeout` /
`judge_output_limit` / `judge_no_reply:<kind>`（连接类）。连接类若只是"记一笔、
立刻进入下一轮"，网络没回来时同一句话会被连着再发两遍，中间没有任何等待 ——
那是"看起来在重试，其实在空转"。

DSH 的浏览器桥用 `ClientBridgeLifecycle` 管这件事：单飞、指数退避、抖动、
成功即重置。本模块把它逐条搬成 Python，语义一个字不加。

## 与 DSH 那段 JS 的逐条对应

DSH 的 `ClientBridgeLifecycle`（`app.asar` 反查原文）只有三个动作：`connected()`
把尝试数归零；`reconnect(connect)` 在"没有待触发的定时器且未关闭"时排一次
`cap = min(maxDelayMs, baseDelayMs * 2 ** attempt)` 的等待（抖动取 `cap/2` 到
`cap`）；定时器到点先清自身、再调 `connect`。

逐条落点（左边是 JS，右边是本模块）：

- `baseDelayMs` -> `base_delay_sec`
- `maxDelayMs` -> `max_delay_sec`
- `reconnectAttempt` -> `attempt`
- `reconnectTimer` -> `pending`（非 None = 已排一次；`schedule` 见到它就返回 None）
- `closed` -> `closed`
- `connected()` -> `connected()`（只把 `attempt` 归零，别的都不动）
- `reconnect(connect)` -> `schedule(fn=None)`（返回这一次的等待秒数；`fn` 就是 JS 的
  `connect` 回调）
- `cap = Math.min(this.maxDelayMs, this.baseDelayMs * 2 ** this.reconnectAttempt)`
  -> `cap = min(self.max_delay_sec, self.base_delay_sec * 2 ** self.attempt)`
- `this.reconnectAttempt++` -> `self.attempt += 1`（只在这一行加；被单飞挡掉的那一次不加）
- `cap / 2 + Math.random() * cap / 2` -> `cap / 2 + self._rng() * cap / 2`
- `setTimeout(..., delay)` -> 同步调用方 `sleep(wait)` 之后 `settle()`；给了 `fn` 时用
  `threading.Timer`（到点先清 `pending`、累计 `waited_total`、再调 `fn`）

## 配置是下发的，不是业务代码写死的

DSH 的 `reconnectBaseMs` / `reconnectMaxMs` 由启动引导下发。本仓的等价物是
`settings` 的梯子（环境变量 > 设置文件 > 内置默认），唯一实现
`settings.env_or_setting`：

- `AGENTFLOW_RECONNECT_BASE_SEC` / `reconnect.base_sec`（默认 5）
- `AGENTFLOW_RECONNECT_MAX_SEC` / `reconnect.max_sec`（默认 60）
- `AGENTFLOW_RECONNECT_TOTAL_SEC` / `reconnect.total_sec`（默认 300）

`agent_loop` 只调 `gate_from_settings()`，不在业务代码里写 5 / 60 / 300。
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from . import settings as SET

#: 环境变量档（优先级最高的一档，与其余键同一条梯子）。
ENV_BASE_SEC = "AGENTFLOW_RECONNECT_BASE_SEC"
ENV_MAX_SEC = "AGENTFLOW_RECONNECT_MAX_SEC"
ENV_TOTAL_SEC = "AGENTFLOW_RECONNECT_TOTAL_SEC"

#: 缺省值（DSH 的 bootstrap 配置下发的是毫秒；本仓统一用秒）。
DEFAULT_BASE_DELAY_SEC = 5.0
DEFAULT_MAX_DELAY_SEC = 60.0
DEFAULT_TOTAL_WAIT_SEC = 300.0

#: 连接类的失败码前缀（`judge.is_no_reply` 三档里"其余带后缀"的那一族）。
CONNECTION_PREFIX = "judge_no_reply:"


def is_connection_problem(problem: str) -> bool:
    """这一次失败是不是"没连上"那一族（`judge_no_reply:<kind>`）。

    成员判据在 `judge.is_no_reply`（三档：超时 / 输出吃光 / 其余带后缀）。本函数
    只认其中带后缀的那一族 —— 前两档各有自己的处置（调大超时、把这一步拆小），
    等待不会让它们变好，所以不在这里重试。
    """
    return str(problem or "").startswith(CONNECTION_PREFIX)


def _read_sec(raw: Any, default: float) -> float:
    """读一个正的秒数；读不出来或不是正数就用缺省（与 `modelgw._float_env` 同一口径）。

    为什么不抛：这三格是"等多久"的旋钮，配错一个字母的后果是多等或少等，
    不是"该做的事没做"；而 `lean_enabled` 那种开关配错会把整条路打开或关掉，
    所以那里 fail-closed、这里回落到缺省。
    """
    try:
        got = float(str(raw or "").strip())
    except (TypeError, ValueError):
        return default
    if not (got > 0):
        return default
    return got


@dataclass(frozen=True)
class ReconnectConfig:
    """连接类失败的等待配置（DSH 的 `reconnectBaseMs` / `reconnectMaxMs` 的等价物）。"""

    base_delay_sec: float = DEFAULT_BASE_DELAY_SEC
    max_delay_sec: float = DEFAULT_MAX_DELAY_SEC
    total_wait_sec: float = DEFAULT_TOTAL_WAIT_SEC

    @classmethod
    def from_settings(cls, path: Any = None, *,
                      env: Mapping[str, str] | None = None) -> "ReconnectConfig":
        """按设置梯子取三个数：环境变量 > 设置文件 `reconnect` 段 > 内置缺省。

        `path` 与 `env` 是判据的注入接缝（与 `settings` 模块同一条口径）：
        给了 `env` 就只认这份映射，不再去探本机的 `settings.json`。
        """
        seg = SET.reconnect_settings(path, env=env)
        base = _read_sec(SET.env_or_setting(ENV_BASE_SEC, seg.get("base_sec", ""),
                                            env=env)[0], DEFAULT_BASE_DELAY_SEC)
        maximum = _read_sec(SET.env_or_setting(ENV_MAX_SEC, seg.get("max_sec", ""),
                                               env=env)[0], DEFAULT_MAX_DELAY_SEC)
        total = _read_sec(SET.env_or_setting(ENV_TOTAL_SEC, seg.get("total_sec", ""),
                                             env=env)[0], DEFAULT_TOTAL_WAIT_SEC)
        return cls(base_delay_sec=base, max_delay_sec=maximum, total_wait_sec=total)

    def gate(self) -> "BackoffGate":
        """按这份配置造一只闸（含 `total_wait_sec`；`BackoffGate` 的两个位置参数与 DSH 同形）。"""
        return BackoffGate(self.base_delay_sec, self.max_delay_sec,
                           total_wait_sec=self.total_wait_sec)


def gate_from_settings(path: Any = None, *,
                       env: Mapping[str, str] | None = None) -> BackoffGate:
    """业务代码的唯一入口：按设置梯子造一只闸（`AgentLoop` 每次 run 现造一只）。"""
    return ReconnectConfig.from_settings(path, env=env).gate()


class BackoffGate:
    """一次运行内的连接等待闸：单飞、指数退避、抖动、成功即重置。

    字段与 DSH 的 `ClientBridgeLifecycle` 逐条对应（见模块 docstring 的映射表）；
    多出来的只有两个读数（`waited_total` / `attempts`）与一个总等待上限
    （`total_wait_sec`，本仓的 ④：等过了还是没回来就停机，不再空转）。

    `rng` 是抖动的注入接缝（判据把它固定成 0 / 0.5 / 1，于是等待可复算）；
    生产里就是 `random.random`。
    """

    def __init__(self, base_delay_sec: float = DEFAULT_BASE_DELAY_SEC,
                 max_delay_sec: float = DEFAULT_MAX_DELAY_SEC,
                 total_wait_sec: float = DEFAULT_TOTAL_WAIT_SEC,
                 rng: Callable[[], float] | None = None) -> None:
        self.base_delay_sec = float(base_delay_sec)
        self.max_delay_sec = float(max_delay_sec)
        self.total_wait_sec = float(total_wait_sec)
        #: 已排过几次等待（DSH 的 `reconnectAttempt`；`connected()` 把它归零）。
        self.attempt = 0
        #: 待触发的那一次等了多久；非 None = 已排一次，`schedule` 据此单飞。
        self.pending: float | None = None
        #: 关闭之后不再排下一次（DSH：prevents reconnection after disposal）。
        self.closed = False
        #: 读数：这一趟一共等了多少秒（跨成功也不清零，总等待上限按它判）。
        self.waited_total = 0.0
        #: 读数：这一趟一共排过几次等待（`attempt` 会被 `connected()` 归零，它不会）。
        self.attempts = 0
        #: 读数：最近一次的 cap（事件流要能解释"为什么等这么久"）。
        self.last_cap = 0.0
        self._rng = rng or random.random
        self._timer: threading.Timer | None = None

    def connected(self) -> None:
        """成功一次 ⇒ 退避归零（DSH 的 `connected()`）。

        只动 `attempt`，刻意不碰 `pending` / `waited_total` / `attempts`：
        前者是 DSH 的原样（成功不取消已排的那一次），后两个是这一趟的累计读数。
        """
        self.attempt = 0

    def schedule(self, fn: Callable[[], Any] | None = None) -> float | None:
        """排下一次等待；返回这一次的等待秒数（被单飞或已关闭挡掉时返回 None）。

        `fn` 是 DSH 的 `connect` 回调：给了就用 `threading.Timer` 到点调它；
        不给就是同步用法（调用方自己 `sleep` 之后调 `settle()`）。
        """
        if self.pending is not None or self.closed:
            return None
        cap = min(self.max_delay_sec, self.base_delay_sec * 2 ** self.attempt)
        self.attempt += 1
        self.attempts += 1
        self.last_cap = cap
        wait = cap / 2 + self._rng() * cap / 2
        self.pending = wait
        if fn is not None:
            timer = threading.Timer(wait, self._fire, args=(fn,))
            timer.daemon = True
            self._timer = timer
            timer.start()
        return wait

    def _take(self) -> float | None:
        """清掉待触发的那一次并把它计入 `waited_total`（同步与定时器两条路共用）。

        同步与定时器两条路共用这一份"结清一次"的实现：取 pending、置 None、累计
        三步的顺序与 DSH 定时器回调一致；两条路因此不会在读数上分叉。
        """
        wait = self.pending
        self.pending = None
        if wait is not None:
            self.waited_total += wait
        return wait

    def settle(self) -> float:
        """同步用法：sleep 结束之后登记这一次等待，返回登记了的秒数。

        对应 DSH 定时器回调里那一步（清 `reconnectTimer`）；累计口径是
        `waited_total`，总等待上限判的就是它。
        """
        wait = self._take()
        return 0.0 if wait is None else wait

    def _fire(self, fn: Callable[[], Any]) -> None:
        """定时器到点：先清 pending、累计 waited_total，再调 `fn`（顺序与 DSH 一致）。"""
        self._take()
        self._timer = None
        fn()

    def close(self) -> None:
        """关闭：撤掉待触发的定时器，之后 `schedule` 一律返回 None。"""
        self.closed = True
        self.pending = None
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.cancel()

    def reading(self) -> dict[str, Any]:
        """这一只闸的读数（事件流与判据共用同一份字段名）。"""
        return {
            "attempt": self.attempt,
            "attempts": self.attempts,
            "pending": None if self.pending is None else round(self.pending, 6),
            "waited_total": round(self.waited_total, 6),
            "last_cap": round(self.last_cap, 6),
            "closed": self.closed,
        }
