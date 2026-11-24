"""协作式预算：到点就在安全点上停，已完成的产物原样交回（B 的抽取面）。

## 为什么要有这一格（真机 lp-ball-21 的读数，2026-11-24）

B 的 `run_once` 自述"处理至多一篇未处理文献"，但一次调用里含
`extract_text(path)` 与 `extractor.extract(doc, …)`，两处都没有任何内部截止、
进度或让出点。同一批 12 篇的逐段实测（`temp/collabbudget/stage_timing.json`）：

- `extract_text`：3.5 MB / 426 页的《Measure, Integration & Real Analysis》只要 0.73 秒；
- `extractor.extract`：那一篇按 10,000 字切出 87 块，每块一次模型调用，
  每次实测中位 58.5 秒（n=92，取自真机 `data/usage_ledger.json` 的
  `scope=extract` 行）⇒ 整篇 ≈ 85 分钟。

于是父看到的是"running、没有新步"，框架的停滞判据（`conductor.step_beats` 读
`out/steps/<台账号>.jsonl`）分不开"工具在干活"与"工具死了" —— 这正是本模块要
补的那一格：把"还要多久、做到哪了"变成盘上的读数，并在安全点上停。

## 三个不许越界的口径

1. 停要停在安全点：块边界 / 页边界。停在半个块里，那一块的产物就只能丢
   （那正是"把活做半截丢掉"）。
2. 到点不是失败：`BudgetStop` 是一个受控停止，与 `ExtractionError` 不是
   同一档 —— 前者说"还有活，下一次接着做"，后者说"这一篇抽不出来"。把两者折平，
   续跑就永远起不来。
3. 不传就是有上限：这一格的缺省是开着的（`DEFAULT_EXTRACT_BUDGET_SEC`）。
   全仓"不传就是无限制"那条口径属于墙钟策略（`Policy.wall_clock_sec`），
   而这里缺的正是"一次调用不许无限长"这条本地约束；显式给 `0` 才是"不限"
   （读数里如实写 `unlimited=True`，不许让"没设"与"设成 0"同形）。

## 时钟可注入

`Budget(clock=…)`：判据要判"到点必停"时不许拿裸 `sleep` 造时间（R5），
所以时钟是一个参数 —— 夹具用假钟把 `spent()` 直接推过线，而不是睡过去。
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping

#: 缺省的单次抽取预算（秒）。取 240 的理由：真机那台机器的停滞阈值是
#: `conductor.STALLED_AFTER_SEC = 600`，而一次模型调用最长实测 111 秒
#: （`stage_timing.json` 的 `gap_max_sec`）⇒ 240 秒保证"到点那一刻手上最多只有
#: 一次在飞的调用"，读数里 `used_sec` 不会离 `limit_sec` 太远（协作式截止的
#: 语义就是"检查点之间不抢跑"，不是"到点精确掐断"）。
DEFAULT_EXTRACT_BUDGET_SEC: float = 240.0

#: 两次进度事件之间至少隔多少秒（同一调用内）。
#:
#: 取 120 的依据是"进度只能报在安全点上"这条物理约束：块边界之间的时间就是一次模型
#: 调用的耗时，真机实测中位 58.5 秒、最长 111 秒（`stage_timing.json` 的
#: `gap_max_sec`，n=92）⇒ 实际可观察的间隔是 `max(tick_sec, 一次块耗时)`。
#: 120 同时是停滞阈值 `conductor.STALLED_AFTER_SEC = 600` 的 1/5：一条进度落后的
#: 最坏情形（两次块调用各 111 秒）仍远在阈值之内，"在干活"不会被读成"死了"。
DEFAULT_TICK_SEC: float = 120.0


class BudgetStop(Exception):
    """受控停止：预算到点，已完成的产物留在原处（在安全点上抛）。

    为什么是一个异常而不是一个布尔返回值：安全点散在两层（`llm.LLMExtractor` 的
    块循环、`extract` 的页循环），返回值要求每一层都在循环里自己记得查一次并把
    "停了"一路手工传回调用方 —— 那是一处漏判就变成"预算形同虚设"的写法。异常让
    "停"这件事穿过那些循环时不可能被忘掉，而它只在安全点上抛。
    """

    def __init__(self, reading: Mapping[str, Any]) -> None:
        super().__init__(f"budget stop: stage={reading.get('stage')} "
                         f"used={reading.get('used_sec')}s of {reading.get('limit_sec')}s")
        #: 停下来那一刻的读数（`Budget.reading()` 的那一份，逐字）：
        #: 调用方把它原样交给结果，不许自己再拼一份"看起来差不多"的。
        self.reading: dict[str, Any] = dict(reading)


class Budget:
    """一次工具调用的预算：`spent()` / `remaining()` / `checkpoint()` / `tick()`。

    用法（抽取器那一侧）：在每个块的开始处调 :meth:`checkpoint` —— 到点它抛
    `BudgetStop`，此时上一块的产物已经在手里了。用法（`extract.py` 的页循环那一侧）：
    在每页开始处调 :meth:`stop_requested`（不抛：页边界上没有"已完成的产物要交回"，
    只有"已抽到的页"，调用方直接返回手上这些页）。
    """

    def __init__(
        self,
        limit_sec: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_tick: Callable[[dict[str, Any]], None] | None = None,
        tick_sec: float = DEFAULT_TICK_SEC,
    ) -> None:
        try:
            self.limit_sec = max(0.0, float(limit_sec))
        except (TypeError, ValueError):
            self.limit_sec = 0.0
        self.tick_sec = max(0.0, float(tick_sec))
        self._clock = clock
        self._on_tick = on_tick
        self.started = float(clock())
        self._last_tick = self.started
        #: 已经发出去几条进度事件（读数用：0 条说明"这一趟太短，没什么可报的"，
        #: 而"一条都没发却跑了很久"是一个该被看见的形态）。
        self.ticks: int = 0
        #: 停过没有（停在哪个安全点由 `reading()["stage"]` 说）。
        self.stopped: bool = False

    # ---- 读数 --------------------------------------------------------- #

    @property
    def unlimited(self) -> bool:
        """`limit_sec <= 0` ⇒ 显式不限（与"没设"不是同一档，见模块 docstring 第 3 条）。"""
        return self.limit_sec <= 0.0

    def spent(self) -> float:
        return max(0.0, float(self._clock()) - self.started)

    def remaining(self) -> float:
        if self.unlimited:
            return float("inf")
        return max(0.0, self.limit_sec - self.spent())

    def expired(self) -> bool:
        return (not self.unlimited) and self.spent() >= self.limit_sec

    def reading(self, *, stage: str = "", done: int = 0, total: int = 0) -> dict[str, Any]:
        """一份现算的读数：已用量与剩余量两个都在，缺一个都答不了"还要多久"。"""
        used = round(self.spent(), 2)
        return {
            "unlimited": bool(self.unlimited),
            "limit_sec": (None if self.unlimited else float(self.limit_sec)),
            "used_sec": used,
            "remaining_sec": (None if self.unlimited else round(self.remaining(), 2)),
            "stage": str(stage or ""),
            "done": int(done or 0),
            "total": int(total or 0),
            "ticks": int(self.ticks),
            "stopped": bool(self.stopped),
        }

    # ---- 让出点 ------------------------------------------------------- #

    def tick(self, *, stage: str = "", done: int = 0, total: int = 0,
             force: bool = False) -> dict[str, Any]:
        """每 `tick_sec` 秒发一条进度（`force=True` 当场发）；返回这一次的读数。

        进度是一旁路：写不成就只丢这条读数，绝不许把这一趟带坏（与
        `sessions.set_append_hook` 的纪律同一条）—— 但它不静默：
        `on_tick` 抛出的异常在这里被接住，因为"进度写失败"不该等价于"抽不出来"。
        """
        reading = self.reading(stage=stage, done=done, total=total)
        now = float(self._clock())
        if force or (self.tick_sec > 0 and (now - self._last_tick) >= self.tick_sec):
            self._last_tick = now
            self.ticks += 1
            if self._on_tick is not None:
                try:
                    self._on_tick(reading)
                except Exception:  # noqa: BLE001 - 旁路：进度写不成不许拦住这一趟
                    pass
        return reading

    def checkpoint(self, *, stage: str = "", done: int = 0, total: int = 0) -> None:
        """安全点上的检查：到点抛 `BudgetStop`（读数是停的那一刻的那一份）。"""
        if self.expired():
            self.stopped = True
            raise BudgetStop(self.tick(stage=stage, done=done, total=total, force=True))
        self.tick(stage=stage, done=done, total=total)

    def stop_requested(self, *, stage: str = "", done: int = 0, total: int = 0) -> bool:
        """不抛版本（页边界用）：`True` = 该停了，手上这些页就是"已抽到的页"。"""
        if self.expired():
            self.stopped = True
            self.tick(stage=stage, done=done, total=total, force=True)
            return True
        self.tick(stage=stage, done=done, total=total)
        return False


# ---------------------------------------------------------------- 写侧：进度落盘


#: 工具执行期那条进度事件的 kind（会话日志里的一行）。
#:
#: 为什么复用会话追加面（`sessions.append`）而不是另开一个文件：它是这个工作区里
#: 所有事件的唯一写口 —— 同一把并发锁、同一个 SSE 钩子、同一张读模型
#: （`webui.readers.run_events` 的 `_EVENT_FIELDS` 里 `payload` 是放行列，所以
#: `payload` 里的 `tool` / `used_sec` / `remaining_sec` 不需要改 webui 就能被读出来）。
#: 另开一份"进度文件"就是第二套读数，而两套读数迟早会分家。
PROGRESS_KIND: str = "agent_tool_progress"


def task_identity() -> tuple[str, str]:
    """`(台账号, 会话号)`：两个都从上下文/环境里现取，取不到就是空串（不编）。"""
    tid = ""
    try:
        from .conductor import current_task_id as _cur
        tid = str(_cur() or "")
    except Exception:  # noqa: BLE001 - 没在台账里跑（单测/自检）⇒ 没有台账号
        tid = ""
    sid = ""
    try:
        from . import sessions as _SS
        sid = str(_SS.session_id() or "")
    except Exception:  # noqa: BLE001 - 会话号读不到 ⇒ 由 append 自己兜底
        sid = ""
    return tid, sid


def stamp_step_beat(root: Any, tid: str, sid: str = "") -> None:
    """把"这一步还活着"追加进同一条步轨迹（`out/steps/<台账号>.jsonl`）。

    为什么必须落在这一条轨迹上：停滞判据（`conductor.step_beats` 是唯一读口）只读它，
    取最后一行算"距现在多少秒"。工具的进度要算进"在干活"，就只能写这里 ——
    写第二个文件就是"另一种读数"，而停滞判据不会去看它。

    步号沿用当前这一步（从轨迹最后一行读出来，重复写同一个号）：一条进度不是
    "多走了一步"，它说的是"这一步还没结束"；伪造一个更大的步号会让"它走了几步"
    这条读数变成假的。
    """
    if not tid:
        return
    try:
        from .conductor import stamp_step as _stamp, step_log_path as _log_path
    except Exception:  # noqa: BLE001 - 没有 conductor 就没有轨迹可写（单测）
        return
    step = 0
    try:
        text = _log_path(root, tid).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in reversed([ln for ln in text.splitlines() if ln.strip()]):
        try:
            got = json.loads(line)
        except ValueError:
            continue          # 撕裂的半行：往回找最后一条读得成的（与读侧同口径）
        try:
            step = int(got.get("step") or 0)
        except (TypeError, ValueError):
            step = 0
        break
    try:
        _stamp(root, task_id=tid, role="B", step=step, sid=sid)
    except Exception:  # noqa: BLE001 - 落痕写不成只影响停滞那一格的可信度
        return


def note_progress(root: Any, lit_id: str, reading: Mapping[str, Any],
                  *, tool: str = "own.run_once", tid: str = "", sid: str = "") -> None:
    """写一条进度：会话事件（人读）+ 步轨迹（停滞判据读）。两处都是现成的写口。"""
    payload = {
        "tool": str(tool),
        "lit_id": str(lit_id),
        "stage": str(reading.get("stage") or ""),
        "used_sec": reading.get("used_sec"),
        "remaining_sec": reading.get("remaining_sec"),
        "limit_sec": reading.get("limit_sec"),
        "done": int(reading.get("done") or 0),
        "total": int(reading.get("total") or 0),
        "ticks": int(reading.get("ticks") or 0),
        "stopped": bool(reading.get("stopped")),
    }
    if not (tid and sid):
        tid, sid = task_identity() if not tid else (tid, sid)
    try:
        from . import sessions as _SS
        _SS.append(root, {"kind": PROGRESS_KIND, "role": "B", "task_id": tid,
                          "payload": payload, "stopped": bool(reading.get("stopped"))},
                   sid=sid or None)
    except Exception:  # noqa: BLE001 - 旁路：进度写不成不许拦住这一趟
        pass
    stamp_step_beat(root, tid, sid)


def progress_sink(root: Any, lit_id: str, *, tool: str = "own.run_once"
                  ) -> Callable[[dict[str, Any]], None]:
    """预算每 `tick_sec` 秒回调一次 —— 落到"盘上那两条进度"上。"""
    def sink(reading: dict[str, Any]) -> None:
        note_progress(root, lit_id, reading, tool=tool)
    return sink


def stop_reading(*, budget: Budget, report: Mapping[str, Any], doc_complete: bool,
                 pages: int, pages_total: int | None) -> dict[str, Any]:
    """这一趟停在哪儿 / 下一块是哪一块：三态（`done` / `extract` / `text_pages`）。

    为什么要把这三态写在一处：三者处置相同（下一次接着做）、读数不同。折成一个
    "没跑完"就答不了"下次该从哪儿接"；而分开写在调用方又会长出第二份"停在哪"的判据。
    """
    chunks_usable = int(report.get("chunks_usable") or 0)
    chunks_done = int(report.get("chunks_done") or 0)
    hit_extract = bool(getattr(budget, "stopped", False)) or bool(report.get("stopped_budget"))
    stage = "extract" if hit_extract else ("" if doc_complete else "text_pages")
    reading = budget.reading(stage=(stage or "done"), done=chunks_done,
                             total=chunks_usable)
    reading["stopped_stage"] = stage
    reading["pages"] = int(pages)
    reading["pages_total"] = pages_total
    if stage:
        reading["why"] = (
            f"停在{'抽取块边界' if stage == 'extract' else '页窗口'}："
            f"已完成的块 {chunks_done}/{chunks_usable}，"
            f"已抽到的页 {pages}/{pages_total if pages_total is not None else '?'}"
            f"（预算 {reading.get('used_sec')}s / {reading.get('limit_sec')}s）")
    return reading


def make_budget(cfg: Mapping[str, Any] | None, lit_id: str, *, root: Any,
                factory: Any = None, tool: str = "own.run_once") -> Budget:
    """这一趟的预算：上限来自 config（缺省开着，见模块 docstring）。

    为什么挂 config 而不是加一个形参：`run_once` 的方法签名在
    `tests/golden/agent_surface_snapshot.json` 里被冻结（禁改区），而"这一次调用
    允许跑多久"是装配面的读数，不该出现在动作的调用面上（模型不该能给自己批
    一个更长的预算 —— 与 B 的概念配额同一个理由）。
    """
    if callable(factory):
        made = factory(lit_id)          # 夹具注入（带假钟）；坏值不许静默放过
        if not isinstance(made, Budget):
            raise TypeError(f"budget factory 必须返回 Budget，收到 {type(made).__name__}")
        return made
    conf = dict(cfg or {})
    raw = conf.get("extract_budget_sec", DEFAULT_EXTRACT_BUDGET_SEC)
    tick = conf.get("extract_progress_sec", DEFAULT_TICK_SEC)
    return Budget(raw, on_tick=progress_sink(root, lit_id, tool=tool), tick_sec=tick)

