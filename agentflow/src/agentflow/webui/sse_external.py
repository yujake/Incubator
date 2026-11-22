# -- coding: utf-8 --
"""外部事实源：`/api/stream` 那条流"盘上被别的进程写了什么"的读数（WEBFIX2 · F3）。

## 为什么单独一个模块

`webui/sse.py` 已经有一万多字节的广播器与 HTTP 外壳，而这里这一族（签名表 / 增量读 /
一拍该发哪些帧）自己就有一百多行。把它搬出来两条理由，都不是"好看"：

1. `sse.py` 有一个体量软基线（800 行，三格告警之一）：F3 的修法是往它里面加东西，
   不搬出来就会把那个数抬上去；
2. 这一族与广播器是两件事：广播器只管"把帧投给订阅者"，它不知道帧从哪来。
   外部事实源是"帧的来源"之一（另一个来源是那四个进程内钩子）。

对外接口仍在 `webui/sse.py` 上（`sse.watch_face` / `sse.ExternalWatch` /
`sse.WATCH_SEC` / `sse.WATCH_MAX_BYTES`）—— 那一层只是转发，于是调用方与判据读的名字
不变。判据要打桩时打的是本模块的 `watch_face`（`ExternalWatch.poll` 在这里解析它），
不是 `sse.watch_face` 这个转发名。

## 三处来源

- `sessions/*.jsonl`（M 的提问 / 回答 / 插话 / 进度全在会话事件流里）；
- 停机开关（`.agentflow-stop`）—— 外部进程叫停，或本进程叫停后被外部循环消费掉；
- `web-actions.jsonl`（另一个网页服务进程的写台账）。

## 纪律

- 只 `stat`，真正读的只有"上次之后新增的那一段字节"（记 offset，不做全表扫）；
- 一次最多读 `WATCH_MAX_BYTES`，超了只读尾部并发一条 `state`（不假装读全了）；
- 不开线程：本模块只是一组函数与一个对象，轮询长在 `sse.handle_stream` 已有的循环里。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import stopctl as SC
from .. import userio as U

__all__ = ["ExternalWatch", "WATCH_MAX_BYTES", "WATCH_SEC", "watch_face"]

#: 轮询周期（秒）。为什么是 0.5：页面上"M 提了个问"要能在人眼还觉得"实时"的窗口里
#: 出现（判据钉的是 ≤2 s，留 4 倍余量给慢盘），而每周期只做一次 `os.scandir` +
#: 每文件一次 `stat` —— 真机 lp-ball-15 只有一段会话文件，代价近似为 0。
WATCH_SEC = 0.5

#: 一次轮询最多从单个文件里读多少新增字节。超了只读尾部：宁可发一条"可能不完整"的
#: `state`（读模型是现算的，页面照样刷成对的），也不许把 14 MB 会话一口气读进内存。
WATCH_MAX_BYTES = 262144


def _actions_path(root: Any) -> Path:
    """审计台账的落点（`web-actions.jsonl`）—— 真身在 `webui/audit.py`，这里只转一手。

    为什么惰性 import：`audit.py` 是写路径那一侧的模块，而本模块在任何时候都可能被
    `sse` 先导入。调用期导入既安全又便宜。
    """
    from .audit import actions_path  # noqa: PLC0415 - 见上面那句

    return Path(actions_path(root))


def watch_face(root: Any) -> dict[str, tuple[int, int]]:
    """外部事实源的签名表：`{绝对路径: (字节数, mtime_ns)}`（只 stat，不读内容）。

    读不到的目录 / 文件一律跳过（不是 0）：`sessions/` 不存在是合法初态（空工作区），
    单个文件 stat 失败是权限/竞态那一档 —— 两种都不该让这条流炸掉，也都不该被读成
    "盘上没有变化"以外的任何结论（下一周期还会再看一次）。
    """
    base = Path(str(root))
    out: dict[str, tuple[int, int]] = {}
    try:
        entries = list(os.scandir(base / "sessions"))
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        entries = []
    for entry in entries:
        try:
            if not entry.name.endswith(".jsonl") or not entry.is_file():
                continue
            info = entry.stat()
        except OSError:
            continue
        out[str(Path(entry.path))] = (int(info.st_size), int(info.st_mtime_ns))
    for extra in (Path(str(SC.stop_path(base))), _actions_path(base)):
        try:
            info = extra.stat()
        except OSError:
            continue
        out[str(extra)] = (int(info.st_size), int(info.st_mtime_ns))
    return out


def _jsonl_records(text: str) -> list[dict[str, Any]]:
    """把一段 JSONL 文本读成记录表（坏行跳过：它是"这一行没读成"，不是"没有事件"）。

    为什么坏行只跳过不报错：这段读的是尾部的一段字节，读到半行是正常竞态（写者刚
    write 完还没 flush 完），那种半行会在下一次轮询里补全 —— 把它当错误报出去只会让
    一条正常的流每半秒喊一次。
    """
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict):
            out.append(got)
    return out


class ExternalWatch:
    """一条流自己的"外部进程写了什么"读数：记 offset，只读新增的那一段。

    生命周期（`sse.handle_stream` 里那三步）：`baseline()` 在首帧快照之前跑，于是
    "连上那一刻盘上已有什么"不会被当成新事件重放一遍；之后每拍 `poll()` 返回这一拍
    要发出去的帧；流结束时对象跟着丢弃（没有线程、没有全局表）。

    `baseline()` 与首帧的先后是硬的：先快照后 baseline 的话，两条之间落盘的那一条问
    （最多几十毫秒的窗口）既不在快照里、也不在增量里 —— 那一帧就永远不出现。
    """

    def __init__(self, root: Any, *, max_bytes: int = WATCH_MAX_BYTES) -> None:
        self.root = Path(str(root))
        self.max_bytes = max(1024, int(max_bytes))
        self._sigs: dict[str, tuple[int, int]] = {}
        self._offsets: dict[str, int] = {}
        self._tails: dict[str, str] = {}

    @property
    def watched(self) -> int:
        """这一拍看了几个文件（判据拿它断言"真的看着东西"，而不是空表恒绿）。"""
        return len(self._sigs)

    def baseline(self) -> int:
        """记下"现在盘上是什么样"，并返回看了几个文件。

        每个文件从当前大小起算（不重放历史）：历史已经在首帧快照里了，重放一遍等于
        把整段会话当新事件推给页面。
        """
        self._sigs = watch_face(self.root)
        self._offsets = {path: size for path, (size, _mtime) in self._sigs.items()}
        self._tails = {}
        return len(self._sigs)

    def _drain(self, path: str, size: int) -> str:
        """读 `path` 从 offset 到 `size` 那一段；返回解出来的文本（可能为空）。

        三种"接不上"的情形各自处置：

        - 文件变小了（被截断 / 重写）⇒ 回到 0 重读，并丢掉上一拍残留的半行；
        - 新增超过 `WATCH_MAX_BYTES` ⇒ 只读尾部那一段（页面会收到一条 `state`，
          读模型是现算的，所以"这一段没逐条读"不影响它读到的状态对不对）；
        - 读失败（权限 / 竞态）⇒ 返回空串并把 offset 推到 `size`：下一拍从新位置继续，
          不让一条坏文件把这条流卡在原地反复读同一段。
        """
        start = self._offsets.get(path, 0)
        if size < start:
            start = 0
            self._tails.pop(path, None)
        if size - start > self.max_bytes:
            start = size - self.max_bytes
            self._tails.pop(path, None)
        head = self._tails.pop(path, "")
        self._offsets[path] = size
        if size <= start:
            self._tails[path] = head
            return ""
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                blob = handle.read(size - start)
        except OSError:
            return ""
        text = head + blob.decode("utf-8", "replace")
        if not text.endswith("\n"):
            cut = text.rfind("\n")
            text, tail = (text[:cut + 1], text[cut + 1:]) if cut >= 0 else ("", text)
            self._tails[path] = tail
        return text

    def poll(self) -> list[bytes]:
        """这一拍的读数 ⇒ 要写进流里的帧（按发生顺序；没有变化就是空表）。

        帧的选择（与 C2 表逐条对应，不新开 kind）：

        - 外部写了一条 `user_question` ⇒ `question`（页面据此把待答面板拉一遍）；
        - 外部写了一条 `user_answer` ⇒ `answered`；
        - 停机开关变了（出现 / 升级 / 被消费掉）⇒ `stop`；
        - 其余一切（进度、插话、索引变化、文件被删）⇒ 一条 `state`（带全量快照）。

        "其余⇒一条 state"是刻意的合并：M 每一步都会往会话里写一条事件，若每条都发一帧
        全量快照，代价与"每步读一遍全盘"相同。一拍只发一条，页面照样刷新到最新。

        帧的构造走 `webui/sse.py` 里那几个 `_*_payload`（与进程内钩子同一份形状定义）：
        本模块只负责"哪一条事件该发哪种帧"，不负责拼 payload。
        """
        from . import sse as _sse  # noqa: PLC0415 - 避免导入期成环（sse 导入本模块）

        live = watch_face(self.root)
        stop_path = str(Path(str(SC.stop_path(self.root))))
        questions: list[bytes] = []
        answers: list[bytes] = []
        stop_changed = False
        state_needed = False
        for path in sorted(set(live) | set(self._sigs)):
            sig = live.get(path)
            old = self._sigs.get(path)
            if sig == old:
                continue
            if sig is None:
                self._sigs.pop(path, None)
                self._offsets.pop(path, None)
                self._tails.pop(path, None)
                state_needed = True
                continue
            self._sigs[path] = sig
            if path == stop_path:
                stop_changed = True
                continue
            if not path.endswith(".jsonl"):
                state_needed = True
                continue
            sid = Path(path).stem
            for event in _jsonl_records(self._drain(path, sig[0])):
                kind = str(event.get("kind") or "")
                if kind == U.ASK_KIND:
                    questions.append(_sse.format_event(
                        kind="question",
                        data=_sse._question_payload(U._question_of(event), sid)))  # noqa: SLF001
                elif kind == U.ANSWER_KIND:
                    answers.append(_sse.format_event(
                        kind="answered",
                        data={"qid": str(event.get("qid") or ""), "sid": sid}))
                else:
                    state_needed = True
        frames = questions + answers
        if stop_changed:
            frames.append(_sse.format_event(
                kind="stop",
                data=_sse._stop_payload(self.root, SC.read_stop(self.root) or {})))  # noqa: SLF001
        if state_needed or stop_changed:
            frames.append(_sse.format_event(kind="state",
                                            data=_sse._snapshot_payload(self.root)))  # noqa: SLF001
        return frames
