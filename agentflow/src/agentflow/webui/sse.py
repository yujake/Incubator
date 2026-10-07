# -- coding: utf-8 --
"""服务端推送（SSE）的事件词表、广播器与 `GET /api/stream`（`draft/73` §2.4）。

## 这一层是什么

前端 `ui/src/sse.ts` 逐个注册事件 kind；后端在这里定义那些 kind（:data:`EVENT_KINDS`）
并把事件推出去。两侧靠契约判据 B（事件对齐） 钉死：`sse.ts` 的 `KINDS` 集合与
:data:`EVENT_KINDS` 不相等就红（`tests/test_webui_contracts.py` 的 `test_b_*`）。
所以词表只有这一份，加一个 kind 必须同时改 `sse.ts` —— 那不是"顺手"，那正是它。

## 六个 kind（`draft/75 §1.2` 的 C2 表）

| kind | payload | 何时发 |
|---|---|---|
| `state` | `{snapshot}` | 会话/台账有新行（`sessions.append` 之后） |
| `question` | `{qid, sid, role, text, options, multi, ts, timeout_sec}` | 新 `user_question` |
| `answered` | `{qid, sid}` | 新 `user_answer` |
| `checkpoint` | `{sid, role, step, stop_reason, waiting_for, spend}` | 检查点文件被改写 |
| `stop` | `{stop_path, requested_by, at, live_pids, running_loops}` | 停机开关变化 |
| `heartbeat` | `{at}` | 每 `heartbeat_sec` |

## 续传（`?since=N`）与心跳（可注入）

- `?since=N`：把 id 大于 N 的事件按顺序补发（client 断线重连时用）。
  补发来自 :class:`Broadcaster` 的环形缓冲（只留最近 :data:`REPLAY_LIMIT` 条）——
  "补不出来"时不编：缓冲里最早那条的 id 大于 `since+1` 就在流里发一条
  `state` 的全量快照（读模型永远是现算的，所以补不到旧事件也不会让页面停在旧状态）。
- 心跳周期可注入（`Broadcaster(heartbeat_sec=...)` 与 `serve` 的开关），
  于是判据可以用 0.2 秒跑它，而不是等 15 秒。

## 三态

`EVENT_KINDS` 是常量，不存在"读不出来"。这里的三态落在补发上：`since` 给了
但缓冲里已经补不齐 ⇒ 事件里带 `reason` 说清（而不是静默少发几条）。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Sequence

from .. import sessions as SS
from .. import stopctl as SC
from .. import userio as U

__all__ = [
    "EVENT_KINDS", "HANDLERS", "PENDING_ENDPOINTS", "REPLAY_LIMIT", "Broadcaster",
    "Subscription", "attach", "begin_serving", "close_all", "default_broadcaster",
    "detach", "format_event", "handle_stream", "heartbeat_event", "hook_problems",
    "publish", "reset_default_broadcaster", "serving", "subscribe",
]

#: 后端会发的事件种类（C2 契约的后端一侧）。必须与 `ui/src/sse.ts` 的 `KINDS`
#: 逐字相同，否则 `tests/test_webui_contracts.py` 的 B 条当场红。
EVENT_KINDS: tuple[str, ...] = (
    "state", "question", "answered", "checkpoint", "stop", "heartbeat",
)

#: 环形缓冲留多少条（`?since=` 的补发上限）。只留最近这些：SSE 是"当前状态"的
#: 推送面，不是审计面（审计面是 `sessions/*.jsonl` 与 `store` 的台账）。
REPLAY_LIMIT = 128

#: 订阅者的队列上限。慢客户端不许把服务端内存吃光；满了就丢最旧的（并记一条
#: `dropped`——丢了多少是可读的，不是静默的）。
QUEUE_LIMIT = 256

#: `GET /api/stream` 那一条表项住在 `webui/readers.py` 的 `ROUTES` 里 —— 理由
#: 是硬的：`routes.py` 的总表是 `自有 + READER_ROUTES + WRITE_ROUTES` 三个子表拼出来
#: 的，`sse.py` 不是其中任何一个子表的主人，写在这里的端点永远进不了总表。
#: 本模块只提供处理器真身（:func:`handle_stream`）：`routes.handler_for("handle_stream")`
#: 会来这里取它（`readers.HANDLERS` 里登记的也是同一个可调用对象）。
HANDLERS: dict[str, Any] = {"handle_stream": None}   # 真身在文件末登记（函数要先存在）

#: 契约判据 D 的例外面：声明了、但后端还没落地的端点（`{端点: 理由}`）。
#: `/api/stream` 在 W2（本批）落地了 ⇒ 这一张表必须是空的；判据有一条反向断言
#: 专门抓"永不生效的豁免"（登记了却已经在总表里 ⇒ 红）。
PENDING_ENDPOINTS: dict[str, str] = {}

#: 默认广播器的单例（进程内）。`serve()` 起来之后所有写者都往它发。
_DEFAULT: "Broadcaster | None" = None
_DEFAULT_LOCK = threading.Lock()

#: 起停计数：`begin_serving()` 打开一个"代"，`close_all()` 关掉当前这一代。
#: 流处理循环每次迭代都读它，于是一个开着流的服务也能被 `serve()` 收尾关掉。
#: 为什么不用 `srv.shutdown()` 就完事：`shutdown()` 只停 accept 循环，
#: `ThreadingHTTPServer` 的入站请求线程不受影响 —— 一条开着的流会把那个线程
#: 一直占住（判据与 `serve()` 的 finally 都会因此卡住）。
_GENERATION = 0


def begin_serving(*, heartbeat_sec: float = 15.0) -> Broadcaster:
    """开一代新的默认广播器（`serve()` 起来时调）；返回它。"""
    return reset_default_broadcaster(heartbeat_sec=heartbeat_sec)


def serving() -> bool:
    """当前这一代还在不在（流循环用它决定要不要收尾）。"""
    return _GENERATION > 0


def _generation() -> int:
    """当前这一代的编号（流循环把它取一次，之后只在同一代里继续跑）。"""
    return _GENERATION


def _now_iso() -> str:
    """当前本地时间（ISO，秒）—— 心跳与事件的时间戳都用它（判据可钉住它）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def format_event(*, kind: str, data: Mapping[str, Any], event_id: int | None = None) -> bytes:
    """把一条事件分帧成 SSE 的线上格式（`event:` + `data:` + 空行）。

    为什么 `data` 一定是单行 JSON：SSE 的 `data:` 以换行为界，多行 JSON 会被
    客户端读成多个 data 段（浏览器会把它们用换行拼起来，但 `EventSource` 的
    `lastEventId` 与我们的 `?since=` 就对不上了）。`ensure_ascii=False` 保留中文，
    `sort_keys=True` 让同一份数据每次给出逐字节相同的帧（判据按字节比）。
    """
    body = json.dumps(dict(data), ensure_ascii=False, sort_keys=True, default=str)
    head = f"event: {kind}\n"
    if event_id is not None:
        head += f"id: {int(event_id)}\n"
    return (head + f"data: {body}\n\n").encode("utf-8")


def heartbeat_event(*, at: str = "") -> dict[str, Any]:
    """`heartbeat` 的 payload（`{at}`）—— `at` 不给就现取一次钟。"""
    return {"at": at or _now_iso()}


class Subscription:
    """一个订阅者：一个有界队列 + 它订阅的 sid（`None` = 全部会话）。"""

    def __init__(self, sid: str | None = None, *, limit: int = QUEUE_LIMIT) -> None:
        self.sid = sid
        self.queue: queue.Queue[tuple[int, bytes]] = queue.Queue(maxsize=limit)
        self.dropped = 0
        self.closed = False

    def put(self, event_id: int, frame: bytes) -> None:
        """投递一帧；队列满 ⇒ 丢最旧的一帧并记 `dropped`（不阻塞发布者）。"""
        try:
            self.queue.put_nowait((event_id, frame))
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                # 队列在同一步被读端清空 ⇒ "丢最旧的一帧"这件事已经由读端做了，
                # 这里什么都不用丢；它不影响下面那一投，也不该被当成错误。
                pass
            self.dropped += 1
            try:
                self.queue.put_nowait((event_id, frame))
            except queue.Full:
                # 并发关闭（读端刚把队列填满哨兵）⇒ 这一帧丢给已关闭的订阅者是可接受的：
                # 订阅者已经不再读了，把它记进 dropped 就够了，不该让发布者在这里炸。
                self.dropped += 1

    def close(self) -> None:
        """标记关闭并放一个哨兵，让读端退出（读端不阻塞在空队列上）。"""
        self.closed = True
        try:
            self.queue.put_nowait((-1, b""))
        except queue.Full:
            # 队列满 ⇒ 里面还有真事件，读端下一轮会先把它们读完；`closed=True` 已经
            # 足以让读端在读完那一批之后退出（哨兵只是"立刻退出"的快路径）。
            pass

    def drain(self, *, timeout: float) -> list[tuple[int, bytes]]:
        """取走队列里此刻所有帧（最长等 `timeout` 秒）；哨兵 `(-1, b"")` 表示收尾。"""
        out: list[tuple[int, bytes]] = []
        try:
            first = self.queue.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return out
        if first[0] == -1:
            self.closed = True
            return out
        out.append(first)
        while True:
            try:
                got = self.queue.get_nowait()
            except queue.Empty:
                break
            if got[0] == -1:
                self.closed = True
                break
            out.append(got)
        return out


class Broadcaster:
    """进程内的 SSE 广播器：一个环形缓冲（补发用）+ 若干订阅者。

    为什么是"进程内、无后台线程"：这个服务是单进程小服务（`ThreadingHTTPServer`），
    事件的来源就在同一个进程里（会话追加、回答落盘、检查点改写）。跨进程的那一半
    （CLI 与驱动器同时写同一个工作区）由 `?since=` 的补发 + 前端的降级轮询承担 ——
    不在这一层假装有一个跨进程的消息总线。
    """

    def __init__(self, *, heartbeat_sec: float = 15.0, replay_limit: int = REPLAY_LIMIT,
                 clock: Any = None) -> None:
        self.heartbeat_sec = float(heartbeat_sec)
        self.replay_limit = int(replay_limit)
        self._clock = clock or _now_iso
        self._lock = threading.Lock()
        self._next_id = 1
        self._buffer: list[tuple[int, str, bytes]] = []
        self._subs: list[Subscription] = []

    # ------------------------------------------------------------ 读
    @property
    def subscribers(self) -> int:
        """当前订阅者数（判据用它断言"断开之后真的清掉了"）。"""
        with self._lock:
            return len(self._subs)

    @property
    def last_id(self) -> int:
        """已经发出去的最后一条事件的 id（0 = 一条都还没发）。"""
        with self._lock:
            return self._next_id - 1

    def replay_since(self, since: int) -> tuple[list[tuple[int, bytes]], str]:
        """补发 id 大于 `since` 的事件；返回 `(帧, 补不齐的说明)`。

        说明非空 = "缓冲里已经补不齐了"（最早那条的 id 比 `since+1` 大）。
        这时调用方应当另发一条全量 `state`（读模型是现算的），而不是假装补全了。
        """
        with self._lock:
            rows = list(self._buffer)
        frames: list[tuple[int, bytes]] = []
        for event_id, _kind, frame in rows:
            if event_id > since:
                frames.append((event_id, frame))
        if not rows:
            return frames, ""
        oldest = rows[0][0]
        if since + 1 < oldest:
            return frames, (f"缓冲里只留到 id={oldest}（你给的 since={since}）——"
                            "补不齐的那一段已经不在内存里了；这一次改用全量快照")
        return frames, ""

    # ------------------------------------------------------------ 写
    def publish(self, kind: str, data: Mapping[str, Any]) -> int:
        """发一条事件：返回它的 id。kind 必须在 :data:`EVENT_KINDS` 里（否则抛）。"""
        if kind not in EVENT_KINDS:
            raise ValueError(f"不认识的事件 kind：{kind!r}（只认 {EVENT_KINDS}）")
        payload = dict(data)
        if kind == "heartbeat":
            payload.setdefault("at", self._clock())
        with self._lock:
            event_id = self._next_id
            self._next_id += 1
            frame = format_event(kind=kind, data=payload, event_id=event_id)
            self._buffer.append((event_id, kind, frame))
            if len(self._buffer) > self.replay_limit:
                del self._buffer[:len(self._buffer) - self.replay_limit]
            subs = list(self._subs)
        for sub in subs:
            sub.put(event_id, frame)
        return event_id

    def subscribe(self, sid: str | None = None) -> Subscription:
        """登记一个订阅者（`sid=None` = 收全部会话的事件）。"""
        sub = Subscription(sid)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """注销（幂等）：断开连接时一定要走到这里，否则订阅者表只增不减。"""
        sub.close()
        with self._lock:
            self._subs = [s for s in self._subs if s is not sub]

    def close_all(self) -> None:
        """收尾：把所有订阅者关掉并清空表（`serve()` 退出时用）。"""
        with self._lock:
            subs = list(self._subs)
            self._subs = []
        for sub in subs:
            sub.close()

    def events(self, sub: Subscription, *, timeout: float) -> Iterator[tuple[int, bytes]]:
        """读一个订阅者的事件（最长等 `timeout` 秒）；订阅者被关掉就结束迭代。"""
        while not sub.closed:
            got = sub.drain(timeout=timeout)
            if not got:
                return
            for event_id, frame in got:
                yield event_id, frame


def default_broadcaster() -> Broadcaster:
    """进程内那一个广播器（首次调用时建；`serve()` 与判据都读它）。"""
    global _DEFAULT  # noqa: PLW0603 - 进程内单例：一个服务一个广播器
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = Broadcaster()
        return _DEFAULT


def reset_default_broadcaster(*, heartbeat_sec: float = 15.0) -> Broadcaster:
    """换一个干净的默认广播器（判据用；`serve()` 起来时也换一个）。

    为什么要能换：心跳周期要可注入（判据用 0.2 秒跑），而"进程内单例"若不能换，
    判据就只能等 15 秒。它同时保证两条判据之间不互相看见对方的事件。
    """
    global _DEFAULT, _GENERATION  # noqa: PLW0603 - 进程内单例与起停代
    with _DEFAULT_LOCK:
        _DEFAULT = Broadcaster(heartbeat_sec=heartbeat_sec)
        _GENERATION += 1
        return _DEFAULT


def close_all() -> None:
    """收尾当前这一代：关掉所有订阅者，并把 `serving()` 置回假。

    `serve()` 的 finally 调它 —— 于是开着流退出时，那些流循环会在下一次
    迭代（最长一个心跳周期）看到代已结束并自己退出，不会把线程占住。
    """
    global _GENERATION  # noqa: PLW0603 - 同上
    with _DEFAULT_LOCK:
        bc = _DEFAULT
        _GENERATION = 0
    if bc is not None:
        bc.close_all()


def publish(kind: str, data: Mapping[str, Any]) -> int:
    """往默认广播器发一条事件（写者用这个，不必自己拿单例）。"""
    return default_broadcaster().publish(kind, data)


def subscribe(sid: str | None = None) -> Subscription:
    """订阅默认广播器（`/api/stream` 用这个）。"""
    return default_broadcaster().subscribe(sid)


# ====================================================================== 写路径上的装配（裁定 1a）
#
# 这一节是"事件真的有来源"的那一半：`/api/stream` 只负责把事件推出去，而事件从哪来
# 靠这里把三个写路径模块（`sessions` / `userio` / `stopctl`）各自的可选钩子接上。
# 三条设计约束，逐条都有判据：
#
# 1. 不改既有行为：缺省（没调 `attach`）时那三个模块的钩子都是 `None`，
#    调用点上只多一个 `is not None`；
# 2. 幂等：重复 `attach()` 是替换（每次都用同一组新闭包覆盖四个槽），
#    回调表里永远只有一份；`attach()` 把"被自己顶掉的外来钩子"报出来；
# 3. 可撤：`detach()` 把四个槽清零，回到"没人接"的状态 —— 判据用它保证
#    一条用例装的钩子不会污染下一条。
#
# `checkpoint` 这个 kind（检查点文件被改写 ⇒ 发事件）本批刻意不做：那需要一个
# 轮询/watch 点，而"状态一律从盘上派生、不做后台轮询线程"是本服务的既有纪律
# （`webui/__init__.py` 的纪律 1）。真要做，正确的位置是"写检查点的那一处"
# （`agent_loop.save_run_checkpoint`）加一个与这里同形的钩子 —— 那属于驱动线的
# 文件，不在本线。这条写在报告里，不偷偷起线程。

#: `attach()` 装上的四个闭包（`detach()` 与"幂等替换"的识别靠它）。
_ATTACHED: dict[str, Any] = {}


def _snapshot_payload(root: Any) -> dict[str, Any]:
    """`state` 事件的 payload：`{snapshot: StateSnapshot}`（`draft/75 §1.2` 的 C2 表）。

    惰性 import `readers`：`routes.py` 导入期就 import 了 `readers`，而 `readers` 一旦
    哪天开始 import `sse`，模块级互相导入就会成环 —— 与 `routes.handler_for` 同一条
    理由（调用期导入既安全又便宜）。

    已知代价（写在这里，不藏）：`append` 是热路径（一步一条事件），而这里每次都现算
    一份全量快照（读遍会话文件 + 台账）。于是"开着网页端跑一趟"会比不打开时多花
    O(趟内事件数 x 会话数) 次读盘。本批接受它，两条理由：`attach()` 只在网页端起服务
    时被调用（没人看着就不付这份代价），且快照的语义必须与 `/api/state` 逐字同源。
    要摊平它得引入节流/合并 —— 那是一个独立的选择（它会把"盘上新增 ⇒ 流里出现"
    从"立刻"变成"最多晚 N 毫秒"），不在本批。
    """
    from .readers import state_face  # noqa: PLC0415 - 见上面那句

    return {"snapshot": state_face(root).get("snapshot")}


def _question_payload(question: Any, sid: str) -> dict[str, Any]:
    """`question` 事件的 payload：C2 表那 8 栏（`index` 是待答面板的排序位，不发）。"""
    view = U.question_view(question, sid=sid)
    view.pop("index", None)
    return view


def _stop_payload(root: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    """`stop` 事件的 payload：C2 表那 5 栏（谁叫停 + 现在还有几个活进程/活循环）。

    `live_pids` / `running_loops` 是现算的（停机事件很少，一次读盘换一个如实读数
    是划算的）。这两栏读不出来时给空表/空表 —— 那是"读到 0 个"，不是"没查成"：
    真读不出来时 `stopctl` 那两处自己会把问题说清（本函数不替它编数字）。
    """
    try:
        live = SC.live_pids(root)
    except Exception:  # noqa: BLE001 - 读数而已：这一栏读不到就报空表
        live = []
    try:
        loops = SC.running_loops(root)
    except Exception:  # noqa: BLE001 - 同上
        loops = {}
    return {"stop_path": str(SC.stop_path(root)),
            # `requested_by` 取自开关内容（`cleared` 时是撤掉之前那一份）；
            # 读不出来就是空串 = 这一栏没读到，不拿后来的人顶上。
            "requested_by": str(payload.get("by") or ""),
            "at": str(payload.get("at") or _now_iso()), "live_pids": live,
            "running_loops": loops}


def attach(*, publish: Any = None) -> dict[str, Any]:
    """把四个写路径钩子接到"发对应 kind 的事件"上（裁定 1a）；返回这一次装了什么。

    | 槽 | 谁触发 | 发出去的 kind |
    |---|---|---|
    | `append` | `sessions.append` 写成功之后 | `state`（payload=全量快照） |
    | `question` | `userio.ask_user` 真的落了一条新问题之后 | `question` |
    | `answered` | `userio.answer_question` 写成功之后 | `answered` |
    | `stop` | `stopctl` 的开关真的变了（created/upgraded/cleared） | `stop` |

    `publish` 可注入（缺省 = `default_broadcaster().publish`）：判据用一个记账函数
    替掉它，就能断言"发了几条、哪几条"，而不必起一条流。

    返回 `{"attached": (四个槽), "replaced": (被顶掉的外来钩子), "problem": ""}`。
    幂等 = 替换：第二次调用会先把上一次装的那四个闭包换掉（它们不会出现在
    `replaced` 里 —— 那是自己装的），所以回调表里永远只有一份，不会叠加。
    """
    def emit(kind: str, payload: Mapping[str, Any]) -> None:
        """按 `publish` 参数的注入情况选发送口（缺省 = 默认广播器）。"""
        if publish is not None:
            publish(kind, payload)
        else:
            default_broadcaster().publish(kind, payload)

    wired: dict[str, Any] = {
        "append": lambda root, event: emit("state", _snapshot_payload(root)),
        "question": lambda root, question, sid: emit("question",
                                                     _question_payload(question, sid)),
        "answered": lambda root, qid, sid: emit("answered", {"qid": qid, "sid": sid}),
        "stop": lambda root, action, payload: emit("stop",
                                                   _stop_payload(root, payload)),
    }
    previous = {
        "append": SS.set_append_hook(wired["append"]),
        "question": U.set_question_hook(wired["question"]),
        "answered": U.set_answer_hook(wired["answered"]),
        "stop": SC.set_stop_hook(wired["stop"]),
    }
    # "被顶掉的"只算不是自己上一次装的那个：自己那一份每轮都换新闭包，
    # 若按 `is not None` 算，第二次 `attach()` 会把自己的旧闭包报成"外来钩子"。
    replaced = tuple(sorted(name for name, old in previous.items()
                            if old is not None and old is not _ATTACHED.get(name)))
    _ATTACHED.clear()
    _ATTACHED.update(wired)
    return {"attached": tuple(sorted(wired)), "replaced": replaced, "problem": ""}


def detach() -> dict[str, Any]:
    """撤掉 `attach()` 装的钩子（回到"没人接"）；返回撤掉了哪几个槽。

    撤的是当前槽里的东西（不管它是不是 `attach` 装的）：这样判据能保证
    "这条用例结束时四个槽一定是空的"，而调用方也不会留一个自己不知道的钩子在跑。
    """
    removed = {
        "append": SS.set_append_hook(None),
        "question": U.set_question_hook(None),
        "answered": U.set_answer_hook(None),
        "stop": SC.set_stop_hook(None),
    }
    _ATTACHED.clear()
    return {"detached": tuple(sorted(name for name, old in removed.items()
                                     if old is not None))}


def hook_problems() -> dict[str, str]:
    """旁路坏没坏的读数：`{模块: 那一段的问题}`（空串 = 没出过问题）。

    为什么要有它：监听器抛出的异常是被接住的（写路径不许被旁路带坏），但"接住了"
    与"没发生"必须分得开 —— 三态纪律。判据拿它断言"注入一个坏 publish 之后，
    写路径照常成功，而这件事读得出来"。
    """
    return {"sessions": SS.append_hook_problem(), "userio": U.hook_problem(),
            "stopctl": SC.stop_hook_problem()}


# ====================================================================== HTTP 外壳
def handle_stream(handler: Any, params: Mapping[str, str],
                  query: Mapping[str, Sequence[str]]) -> None:
    """`GET /api/stream`：`text/event-stream` 的推送流。

    流程（`draft/73` §2.4）：先回响应头（`no-store` + `no-cache` + `keep-alive`）⇒
    按 `?since=` 补发缓冲里能补的那些（补不齐就先发一条全量 `state`）⇒
    进入循环：有新事件就发，闲着就按 `heartbeat_sec` 发心跳，客户端断开就退出。

    `sid`（可选）只订这一段会话的事件；心跳周期取默认广播器上那个可注入的值。
    """
    del params
    sid_vals = query.get("sid") or []
    sid = str(sid_vals[0]) if sid_vals else None
    since_raw = (query.get("since") or [""])[0]
    try:
        since = int(str(since_raw)) if str(since_raw).strip() else 0
    except ValueError:
        # 解不出的 since 按 0 处置：那是"从头补"（比"静默当成最后一页"安全 ——
        # 后者会让页面停在旧状态而看不出为什么）。
        since = 0
    bc = default_broadcaster()
    sub = bc.subscribe(sid)
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "keep-alive")
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()
        # ① 补发
        if since > 0:
            frames, why = bc.replay_since(since)
            for _event_id, frame in frames:
                handler.wfile.write(frame)
            if why:
                from .readers import state_face

                face = state_face(handler.root)
                miss = format_event(kind="state",
                                    data={"snapshot": face.get("snapshot"),
                                          "reason": why})
                handler.wfile.write(miss)
        handler.wfile.flush()
        # ② 循环：事件 / 心跳 / 收尾
        mine = _generation()
        last_beat = time.monotonic()
        while serving() and _generation() == mine:
            got = sub.drain(timeout=min(0.2, max(0.01, bc.heartbeat_sec)))
            for _event_id, frame in got:
                handler.wfile.write(frame)
            if got:
                handler.wfile.flush()
            if sub.closed:
                break
            if time.monotonic() - last_beat >= bc.heartbeat_sec:
                handler.wfile.write(format_event(kind="heartbeat",
                                                 data=heartbeat_event()))
                handler.wfile.flush()
                last_beat = time.monotonic()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        # 客户端断开是这条流的正常终点（不是错误）：退出并注销订阅者。
        pass
    finally:
        bc.unsubscribe(sub)


def handlers() -> dict[str, Any]:
    """`{名字: 处理器}`（本模块自己那一份的实名表）—— 与 `readers.HANDLERS` 同一族。"""
    return {name: fn for name, fn in HANDLERS.items() if fn is not None}


def bind_handlers(cls: Any) -> tuple[str, ...]:
    """把本模块的处理器绑到一个类上；返回绑上去的名字（排序）。

    这条不是接缝的正路（A 线已经改用 `routes.handler_for` 按子表取处理器了），
    留着它是给判据与 `WebHandler` 一起做实验用的：绑上之后同一个端点在"类方法"那条
    查找路径上也找得到。生产路径不依赖它。
    """
    for name, func in handlers().items():
        setattr(cls, name, func)
    return tuple(sorted(handlers()))


#: 表项的登记（函数得先存在，所以放在文件末）。
HANDLERS["handle_stream"] = handle_stream
