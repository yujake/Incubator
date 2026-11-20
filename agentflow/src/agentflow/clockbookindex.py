# -*- coding: utf-8 -*-
"""计时器簿记的索引面：堆、热集、到点读法、周期记录。

## 这个模块为什么存在

2026-11-20 业主「还有超800的？派人拆」⇒ `clock.py` 由底向上拆的第四刀。
`TimerBook`（615 行、33 个方法）与 `Timer`、`book()`、`target_state()` 构成一个
运行期成环的整体：`Timer.due_reason` 会在没给读数时问 `target_state`，`target_state`
问 `book`，`book` 造 `TimerBook`，`TimerBook` 存 `Timer` —— 四者必须同处一个模块，
否则任一方向的 import 都是环。所以这一刀不是搬顶层块，而是把 `TimerBook` 里
"只碰自己的索引/热集/到点读法"的那 24 个方法整体抽成混入类，让核心那一刀能落进 800 行内。

## 装了什么

`_BookIndexMixin`：`_heap_due` / `_rebuild_index` / `_ensure_index` / `_index_one` /
`_unindex_one` / `sync_index` / `waiters_of` / `waiters_count` / `pending_count` /
`total_count` / `heap_size` / `mark_hot` / `hot_count` / `pop_hot` / `clear_hot` /
`next_due_epoch` / `next_reconcile_epoch` / `next_wake_epoch` / `mark_reconciled` /
`reconcile_count` / `_periodics_quiet` / `needs_full_scan` / `can_early_exit` / `pop_due`。

以及 `Periodic`：周期记录（到点不消耗的那一类）。它只依赖词表、三态读数、
`due_message` 与 `purpose_of`，与 `TimerBook` 的索引面同属"簿记的数据面"，一起放在
`Timer` 之下，于是核心那一刀不再被它撑爆。

## 等价性证据

方法体逐字未改（`temp/split1_mixin.py` 逐方法 AST dump 比对：搬走的 24 个方法全等，
类里一个都没留下）；`TimerBook` 的公开方法面一个字没变（继承之后 `dir()` 相同），
所以 `from .clock import TimerBook` 的调用点与判据不用改。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .clockbase import (  # noqa: F401 — 这些名字由 clockbase 定义
    PERIODIC_STATES,
    TARGET_STATES,
    ClockError,
    Reading,
    _parse_iso,
)
from .clockrun import (  # noqa: F401 — 这些名字由 clockrun 定义
    due_message,
    now,
    purpose_of,
)

from .clockbase import ClockError
from .clockbase import RECONCILE_EVERY_SEC
from .clockbase import Reading
from .clockbase import UTC
from .clockbase import _iso
from .clockbase import _parse_iso
from datetime import datetime
import heapq


class _BookIndexMixin:
    """TimerBook 的混入：见模块头。方法体逐字未改。"""

    @staticmethod
    def _heap_due(timer: Timer) -> float | None:
        """这一条计时器"下一次该被叫醒"的墙钟纪元；`None` = 它不进堆。

        两半取较早者：

        1. 钟点那一半：`due_epoch`（起表时就落盘的那一格）；老行没有它就按 `due_at`
           现解析。两条都读不出来 => 这一条不进堆（三态：判不了就交给补偿对账，
           不许折成"没有到点"）。
        2. 等谁的上限那一半：`created_at + max_wait_sec`（`cap_passed` 判的就是这一格）。
           纯等待（没有上限）两半都没有 => 不进堆。
        """
        if timer.state != "pending":
            return None
        stamps: list[float] = []
        if timer.due_epoch is not None:
            try:
                stamps.append(float(timer.due_epoch))
            except (TypeError, ValueError):
                # 盘上这一格坏掉（手改过 / 老写入方写了字符串）：不当成"没有到点"，
                # 退到下面按 `due_at` 现解析；两条都读不出来才不进堆（交给补偿对账判）。
                pass
        else:
            due = timer.due_datetime()
            if due is not None:
                stamps.append(due.timestamp())
        if timer.max_wait_sec is not None:
            try:
                created = _parse_iso(timer.created_at).timestamp()
            except ClockError:
                created = None
            if created is not None:
                stamps.append(created + max(0.0, float(timer.max_wait_sec)))
        return min(stamps) if stamps else None


    def _rebuild_index(self) -> None:
        """按 `state.json` 的行序重建派生索引（`load` 时一次；判据可随时重放）。"""
        self._waiters = {}
        self._heap = []
        self._seq_of = {}
        self._in_heap = set()
        self._pending = set()
        self._hot = set()
        self._order_seq = 0
        order = sorted(self._timers.values(), key=lambda t: (t.due_at, t.timer_id))
        for timer in order:
            self._order_seq += 1
            self._seq_of[timer.timer_id] = self._order_seq
            if timer.state == "pending":
                self._index_one(timer)
        self._index_ready = True


    def _ensure_index(self) -> None:
        if not self._index_ready:
            self._rebuild_index()


    def _index_one(self, timer: Timer) -> None:
        """把一条 pending 计时器登记进反查索引与堆（重复调用不会重复入堆）。"""
        if timer.state != "pending":
            return
        self._pending.add(timer.timer_id)
        key = _target_key(timer)
        if key:
            self._waiters.setdefault(key, set()).add(timer.timer_id)
        due = self._heap_due(timer)
        if due is not None and timer.timer_id not in self._in_heap:
            heapq.heappush(self._heap,
                           (due, self._seq_of.get(timer.timer_id, 0), timer.timer_id))
            self._in_heap.add(timer.timer_id)


    def _unindex_one(self, timer: Timer) -> None:
        """把它从反查索引里摘掉；堆里那一条留给惰性删除（到点时刻不会变）。"""
        self._pending.discard(timer.timer_id)
        self._hot.discard(timer.timer_id)
        key = _target_key(timer)
        if key:
            peers = self._waiters.get(key)
            if peers is not None:
                peers.discard(timer.timer_id)
                if not peers:
                    self._waiters.pop(key, None)
        self._in_heap.discard(timer.timer_id)


    def sync_index(self, timer: Timer) -> None:
        """一条计时器的状态可能变了 —— 把派生索引与它对上（幂等，O(log N)）。

        调用点只有四个：`add`（新起一条）、`cancel`（转取消态）、到点动作成功之后
        （转 fired）、`load`（重建）。漏掉任何一处，`waiters_by_target` 或堆就会与
        台账分家 —— 两条差分判据（堆 == 线性扫 / 索引 == 全表扫）就是钉子。
        """
        self._ensure_index()
        if timer.timer_id not in self._seq_of:
            self._order_seq += 1
            self._seq_of[timer.timer_id] = self._order_seq
        self._unindex_one(timer)
        self._index_one(timer)


    def waiters_of(self, target_key: str) -> list[Timer]:
        """等这个对象的那几条（O(1) 反查；返回的是快照，调用方可以边遍历边改状态）。"""
        self._ensure_index()
        ids = self._waiters.get(str(target_key or ""))
        if not ids:
            return []
        out: list[Timer] = []
        for tid in ids:
            timer = self._timers.get(tid)
            if timer is not None and timer.state == "pending":
                out.append(timer)
        out.sort(key=lambda t: self._seq_of.get(t.timer_id, 0))
        return out


    def waiters_count(self) -> int:
        """被索引的"等谁"关系有多少条（读数用，不是判据）。"""
        self._ensure_index()
        return sum(len(ids) for ids in self._waiters.values())


    def pending_count(self) -> int:
        """还 pending 的条数（O(1)）。"""
        self._ensure_index()
        return len(self._pending)


    def total_count(self) -> int:
        """台账里的总行数（O(1)；改前的 `pending()` 会把它们全部排序一遍）。"""
        return len(self._timers)


    def heap_size(self) -> int:
        self._ensure_index()
        return len(self._in_heap)


    def mark_hot(self, timer: Timer) -> None:
        """记下"已经判成到点、只等下一次投递"的那一条（事件消账的产物）。

        为什么不在此刻直接投递：投递要写 mailbox 行与唤醒标记，而事件常常发生在另一
        步的中间（子代理落定、程序收口）。当场写会让"本步刚派出去的子代理已经回来了"
        变成一次抢占 —— `agent_loop._wait_for_children` 读到时钟唤醒就提前返场，于是
        每一次扇出都多花一个模型回合。那是拿钱换来的"零时延"，方向反了（实测：
        `tests/test_agent_loop.py::test_a_role_can_fan_out_a_batch_in_one_step` 在
        当场投递的版本下 ok_count 从 2 掉到 1，第二次派的活没在这一步回来）。

        判据要的是"不用等下一拍扫表"：这一格就是那个落点 —— 下一拍只按热表投那几条，
        O(k)，不扫全表。
        """
        self._hot.add(timer.timer_id)


    def hot_count(self) -> int:
        return len(self._hot)


    def pop_hot(self) -> list[Timer]:
        """取出热表里的那几条（按台账序；不在这里判到点 —— 判据仍然只有 `due_reason`）。"""
        self._ensure_index()
        ids = sorted(self._hot, key=lambda t: self._seq_of.get(t, 0))
        self._hot.clear()
        out: list[Timer] = []
        for tid in ids:
            timer = self._timers.get(tid)
            if timer is not None and timer.state == "pending":
                out.append(timer)
        return out


    def clear_hot(self) -> None:
        """全表对账之后热表就空了（对账已经把每一条都判过一遍）。"""
        self._hot.clear()


    def next_due_epoch(self) -> float | None:
        """堆顶那一条的到点时刻（O(1) peek；惰性删掉已经不作数的堆顶）。

        `None` 有两种情形（都不许折成"到点是 0"）：堆里一条都没有（全部是纯等待或
        已经空了），或者读不成 —— 后者由 `load_error` 与 `can_early_exit` 分开报。
        """
        self._ensure_index()
        while self._heap:
            due, _seq, tid = self._heap[0]
            timer = self._timers.get(tid)
            if timer is None or timer.state != "pending" or tid not in self._in_heap:
                heapq.heappop(self._heap)
                self._in_heap.discard(tid)
                continue
            return due
        return None


    def next_reconcile_epoch(self) -> float | None:
        """下一次补偿对账应当发生的时刻；还没对账过 => `None`（第一拍必全扫）。"""
        if self._last_reconcile_at is None:
            return None
        return self._last_reconcile_at + RECONCILE_EVERY_SEC


    def next_wake_epoch(self) -> float | None:
        """下一次"必须醒过来看一眼"的时刻：堆顶 / 下次对账 / 周期性巡查的下一拍。

        口径写死在这里（`next_wake_in_sec` 与挂机片长的封顶都读它）：取三者的较早者。
        为什么把对账也放进来：对账是漏发事件的唯一兜底（见 `EVENT_CLOSE_HOOKS`），
        挂机的人若用一个长拍把对账时刻压过去，那条兜底就要再等一拍才跑。
        为什么把周期性巡查也放进来：它不在计时器的堆里（`Periodic` 是另一本账），
        漏了它就会出现"挂机把一个 20 分钟的巡查睡过去"。
        """
        self._ensure_index()
        cands: list[float] = []
        due = self.next_due_epoch()
        if due is not None:
            cands.append(due)
        rec = self.next_reconcile_epoch()
        if rec is not None:
            cands.append(rec)
        for periodic in self.running_periodics():
            nxt = periodic.next_datetime()
            if nxt is not None:
                cands.append(nxt.timestamp())
            if periodic.until_sec is not None:
                try:
                    created = _parse_iso(periodic.created_at).timestamp()
                except ClockError:
                    created = None
                if created is not None:
                    cands.append(created + max(0.0, float(periodic.until_sec)))
        return min(cands) if cands else None


    def mark_reconciled(self, reading: Reading) -> None:
        """记下"这一拍做了一次全表对账"（早退与 `next_wake_in_sec` 都读它）。"""
        if reading.wall is not None:
            self._last_reconcile_at = reading.wall.timestamp()
        if reading.monotonic is not None:
            self._last_scan_mono = reading.monotonic
        self._reconcile_count += 1


    def reconcile_count(self) -> int:
        """这个簿记一共对账过几次（读数用）。"""
        return self._reconcile_count


    def _periodics_quiet(self, now_epoch: float) -> bool:
        """周期性巡查这一半能不能被早退跳过（能跳 = 这一拍它一定什么都不做）。"""
        for periodic in self.running_periodics():
            if periodic.wait_for:
                # 它等谁 => 那一半要问 target_state，早退会把它压过去。
                return False
            nxt = periodic.next_datetime()
            if nxt is not None and now_epoch >= nxt.timestamp():
                return False
            if periodic.until_sec is not None:
                try:
                    created = _parse_iso(periodic.created_at).timestamp()
                except ClockError:
                    continue
                if now_epoch - created >= max(0.0, float(periodic.until_sec)):
                    return False
        return True


    def needs_full_scan(self, reading: Reading) -> tuple[bool, str]:
        """这一拍要不要"全表对账"（补偿扫描）。返回 `(要不要, 为什么要)`。

        三条要（一条都不许折成"不要"）：

        1. 簿记/时钟读不全：读不成 => 没查成，不许早退；
        2. 还没对过账（第一拍）：改前的行为就是第一拍全扫，这一档照旧；
        3. 到了 `RECONCILE_EVERY_SEC`（补偿对账：漏发事件的兜底），或者这一拍与
           上一次判定之间单调计数没走动。后半条是保守方向：时钟停住（或两拍落在同一刻）
           时"时间没动"意味着这一拍的输入只变了台账那一半，而台账可能被事件漏发、
           被别的进程改过 ⇒ 这一拍照旧全扫。真机上两个来源都按真实时间前进，这一条
           从不触发；它换来的是"时钟停住时最多退化成改前的全扫"，而不是"永久挂起"。
        """
        self._ensure_index()
        if self.load_error:
            return True, self.load_error
        if reading.status != "ok":
            return True, (f"时钟只有 {reading.status} 读数"
                          f"（{reading.reason or '两个来源没有都读到'}）=> 判不了，照旧全扫")
        if reading.wall is None or reading.monotonic is None:
            return True, "墙钟或单调计数读不到 => 判不了，照旧全扫"
        if self._last_reconcile_at is None or self._last_scan_mono is None:
            return True, "这一份簿记还没对过账 => 第一拍照旧全扫"
        if reading.monotonic <= self._last_scan_mono:
            return True, ("这一拍与上一次判定之间单调计数没有走动 => 台账那一半可能变了，"
                          "照旧对账（时钟停住时不许早退）")
        if reading.wall.timestamp() >= self._last_reconcile_at + RECONCILE_EVERY_SEC:
            return True, f"补偿对账到点（每 {RECONCILE_EVERY_SEC:g} 秒一次）"
        return False, ""


    def can_early_exit(self, reading: Reading) -> tuple[bool, str]:
        """这一拍能不能"查过了、没有到点的"就收工（不扫表、不问 target_state）。

        前提是 `needs_full_scan` 已经说"不用对账"；这里只再问一句"现在还没到任何一件
        该醒的事"：`min(堆顶, 下次对账, 下一次周期性巡查)` 还没到，并且周期性巡查
        那一半确实无事可做（`_periodics_quiet`）。

        三态一条不少：这一档下不许有任何"没查成折成没有"的折叠 —— 读不成的情形全部在
        `needs_full_scan` 里被拦成"要全扫"了。
        """
        self._ensure_index()
        if self.load_error or reading.status != "ok" or reading.wall is None:
            return False, "读不全 => 不许早退（交给 needs_full_scan 判）"
        now_epoch = reading.wall.timestamp()
        nxt = self.next_wake_epoch()
        if nxt is None:
            return False, "簿记里既没有到点也没有对账时刻 => 判不了，照旧全扫"
        if now_epoch >= nxt:
            return False, f"下一个到点/对账时刻（{_iso(datetime.fromtimestamp(nxt, UTC))}）已经到了"
        if not self._periodics_quiet(now_epoch):
            return False, "有周期性巡查这一拍就该动了（或它等谁）=> 不能早退"
        return True, ""


    def pop_due(self, reading: Reading) -> list[Timer]:
        """堆里到点时刻已经过了的那些（按台账序；不真的弹出，投递之后由 `sync_index` 摘掉）。

        它是"到点判定"的候选集：调用方仍要逐条过 `due_reason`（那是唯一判据），
        于是"堆给的候选"与"线性扫"在判据上完全同源 —— 堆只决定"谁值得看一眼"。

        为什么不在这里就 `heappop`：候选未必真到点（`due_reason` 空），把没到点的那一条
        从堆里扔掉会让它到点之后再也冒不出来。留在堆里则最坏是"每拍多看它一眼"，
        代价 O(log N)，而丢掉的代价是永久挂起。
        """
        self._ensure_index()
        now_epoch = reading.wall.timestamp() if reading.wall is not None else None
        if now_epoch is None:
            # 空表在这里不是"没有到点"，是"判不了"：墙钟读不到就没法比"现在几点"。
            # 不抛也不编一个 0 —— 调用方（`fire_due`）在进这一支之前已经要求读过 `ok`，
            # 所以这一支只会出现在直接调它的读数路径上，空表就是"这一格没查成"。
            return []
        out: list[Timer] = []
        seen: set[str] = set()
        for due, _seq, tid in sorted(self._heap):
            if due > now_epoch:
                break
            if tid in seen:
                continue
            timer = self._timers.get(tid)
            if timer is None or timer.state != "pending" or tid not in self._in_heap:
                continue
            seen.add(tid)
            out.append(timer)
        out.sort(key=lambda t: self._seq_of.get(t.timer_id, 0))
        return out


@dataclass
class Periodic:
    """一条周期性巡查。M 的"巡视"就是这一类（等 20 分钟 + 周期性巡查）。

    与一次性计时器的区别只在"到点之后怎么走"：一次性到点即消耗，周期性到点不消耗、
    `next_at` 前移到下一拍、`fires` 递增，直到被 `periodic_stop` 停 / `until_sec` 到 /
    被等的那对象收口。三个终态都写进 `stopped_reason`（空 = 还在跑）。
    """

    periodic_id: str
    every_sec: float
    purpose: str
    to: str
    task_id: str
    role: str
    workspace: str
    created_at: str
    next_at: str
    state: str = "running"
    fires: int = 0
    last_fired_at: str = ""
    stopped_at: str = ""
    stopped_reason: str = ""
    until_sec: float | None = None
    wait_for: str = ""
    wait_for_resolved: str = ""
    wait_state: str = ""
    next_mono: float | None = None
    clock_token: str = ""

    def __post_init__(self) -> None:
        if self.state not in PERIODIC_STATES:
            raise ValueError(
                f"state 必须是 {PERIODIC_STATES} 之一，收到 {self.state!r}")
        if float(self.every_sec) <= 0:
            raise ValueError(f"every_sec 必须是正数，收到 {self.every_sec!r}")
        if self.wait_state and self.wait_state not in TARGET_STATES:
            raise ValueError(
                f"wait_state 必须是 {TARGET_STATES} 之一，收到 {self.wait_state!r}")

    @property
    def purpose_missing(self) -> bool:
        return not str(self.purpose or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Periodic":
        fields = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in dict(raw).items() if k in fields})

    def next_datetime(self) -> datetime | None:
        try:
            return _parse_iso(self.next_at)
        except ClockError:
            return None

    def elapsed_sec(self, reading: Reading | None = None) -> float | None:
        """从起表到现在跑了多久（`until_sec` 那条闸按它判）。读不到 => None。"""
        got = reading if reading is not None else now()
        if got.status == "unknown" or got.wall is None:
            return None
        try:
            return max(0.0, (got.wall - _parse_iso(self.created_at)).total_seconds())
        except ClockError:
            return None

    def remaining_sec(self, reading: Reading | None = None) -> float | None:
        """离下一拍还有多少秒。读不到时钟 => None（不是 0）。"""
        got = reading if reading is not None else now()
        if self.state != "running":
            return 0.0
        if got.status == "unknown":
            return None
        nxt = self.next_datetime()
        if nxt is None or got.wall is None:
            return None
        return max(0.0, (nxt - got.wall).total_seconds())

    def last_message(self, reading: Reading | None = None) -> str:
        """上一次报醒那句话（周期性巡查的定死格式；目的走唯一取值口）。"""
        return due_message(purpose=purpose_of(self), waited_sec=None,
                           created_at=None, fired_at=None,
                           every_sec=self.every_sec, fires=self.fires)

    def row(self, reading: Reading | None = None) -> dict[str, Any]:
        """给工具面/判据读的一行。业主点名的六格都在最前面。"""
        got = reading if reading is not None else now()
        return {
            "periodic_id": self.periodic_id,
            "every_sec": self.every_sec,
            "purpose": self.purpose,
            "fires": int(self.fires),
            "next_at": self.next_at,
            "stopped_reason": self.stopped_reason,
            "purpose_missing": self.purpose_missing,
            "state": self.state,
            "to": self.to,
            "task_id": self.task_id,
            "role": self.role,
            "created_at": self.created_at,
            "last_fired_at": self.last_fired_at,
            "remaining_sec": self.remaining_sec(got),
            "until_sec": self.until_sec,
            "wait_for": self.wait_for,
            "wait_for_resolved": self.wait_for_resolved,
            "wait_state": self.wait_state,
            "stopped_at": self.stopped_at,
            "last_message": self.last_message(got) if self.fires else "",
        }


def _target_key(timer: Timer) -> str:
    """"等谁"的读口键：解析后的对象优先（起表时查过一次，不必每次重解析）。"""
    return timer.wait_for_resolved or timer.wait_for
