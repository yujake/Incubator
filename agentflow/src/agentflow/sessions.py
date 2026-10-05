# -*- coding: utf-8 -*-
"""按项目存放的会话记录（学 harness 的"按工作区存放"）。

## 为什么要这一层

`tasks` 表是运行时状态：谁在跑、结局如何、花了多少。它回答"现在怎么样"，
但它不是"这次运行的叙事"——谁在什么时候对谁说了什么、产出了什么、为什么被拒。
`draft/31` 的元判据要求"台账能重建 M 的决策序列"，而 M 自己的叙述（计划、改道、
观察）今天只活在会话里。

harness 的做法是按工作区存会话：换个工作区就是另一段历史，互不污染。
本项目照做，落点是 `<项目根>/sessions/<会话号>.jsonl`：

- 一个项目一个目录 ⇒ 翻 p2-review 的会话不必读全局目录，也不会把两个项目的
  叙事混在一起（本项目同时在跑 7 个旧项目 + p2-review）；
- 追加写、一行一事件 ⇒ 中断后仍可读，坏行能逐条报出（不是"读不出来就当没有"）；
- 会话号默认取环境变量 `AGENTFLOW_SESSION`，否则取当天日期（一天一段，够用且稳定）。

## 三态

目录不存在 = 还没有会话（合法初态，不是错误）；会话文件有坏行 ⇒ 逐行报出；
`append` 失败 ⇒ 返回失败原因（调用方决定要不要因此改变终态 —— 本模块的建议是不改变：
会话记录是叙事，不是判据本身）。
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from filelock import FileLock

from .jsonlfile import read_jsonl

SESSIONS_DIR_NAME = "sessions"
ENV_SESSION = "AGENTFLOW_SESSION"


def _file_lock(path: str) -> FileLock:
    """跨进程写锁（同一工作区上 CLI 与驱动器可能同时在写同一份会话）。"""
    return FileLock(path, timeout=30.0)


def sessions_dir(root: Any) -> pathlib.Path:
    """`<项目根>/sessions/`（只算路径，不建目录）。"""
    return pathlib.Path(str(root)) / SESSIONS_DIR_NAME


def session_id() -> str:
    """本次会话号：环境变量优先，否则当天日期（UTC+8 由调用环境决定，这里用本地时区）。"""
    env = str(os.environ.get(ENV_SESSION) or "").strip()
    if env:
        return env
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")


def session_path(root: Any, sid: str | None = None) -> pathlib.Path:
    return sessions_dir(root) / f"{sid or session_id()}.jsonl"


#: 每个会话文件一把进程内写锁（并发写者的交错就在这里被挡住）。
#:
#: 为什么必须锁（E5 之后的全量套件实测，2026-10-05）：`LlmBackend` 会在一波里并发跑
#: 同一角色的多个实例（线程），它们各自往同一个 `sessions/<sid>.jsonl` 追加事件。
#: 没有锁时两次 `write` 会在一个多字节字符中间交错 ⇒ 文件里出现非法 UTF-8 字节
#: （实测报错：`UnicodeDecodeError: byte 0xa8 in position 9472`），于是
#: "读会话记录"整条路直接炸 —— 而会话记录是本框架唯一的叙事审计面。
#: 表现形态也记在这里：它不总是红，只在真正并发时才红（所以它此前被当成"偶发 flaky"）。
_APPEND_LOCKS: dict[str, Any] = {}
_APPEND_LOCKS_GUARD = threading.Lock()


def _append_lock(path: pathlib.Path) -> Any:
    key = str(path).lower()
    with _APPEND_LOCKS_GUARD:
        lock = _APPEND_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _APPEND_LOCKS[key] = lock
        return lock


def append(root: Any, event: Mapping[str, Any], *, sid: str | None = None) -> tuple[pathlib.Path | None, str]:
    """追加一条事件；返回 `(路径, 问题)`，问题为空串才算写成。

    两种写者都要挡住：线程（同波并发跑的几个实例，用 `_append_lock`）与
    进程（CLI 与驱动器同时跑在同一个工作区上，用 `filelock`）。锁只包住"把这一行
    写完"这一段：拿锁之前先把整行序列化好，临界区里只有一次 `write`。
    """
    path = session_path(root, sid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(event)
        row.setdefault("ts", datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))
        line = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        with _append_lock(path):
            with _file_lock(str(path) + ".lock"):
                with path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(line)
    except (OSError, TypeError, ValueError) as e:  # noqa: BLE001 - 见模块 docstring
        return None, f"{type(e).__name__}: {e}"
    return path, ""


def read_session(root: Any, sid: str | None = None) -> tuple[list[dict], list[str]]:
    """读一段会话；返回 `(事件, 问题)`。坏行逐条报出，不静默跳过。

    JSONL 的读法只有一份实现：:func:`jsonlfile.read_jsonl`（`draft/36` T-6 合并）。
    合并前三处（这里、`artifacts`、`signatures`）各写了一份同形的循环 ——
    漂移的表现是"同一份坏文件，`verify` 说它坏、`session show` 说它好"，而没有东西会报错。
    """
    return read_jsonl(session_path(root, sid))


def list_sessions(root: Any) -> list[dict]:
    """列出这个项目的所有会话（按文件名排序）。目录不存在 ⇒ 空列表（合法初态）。"""
    d = sessions_dir(root)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(d.glob("*.jsonl")):
        events, problems = read_session(root, p.stem)
        out.append({
            "sid": p.stem,
            "path": str(p),
            "events": len(events),
            "bad_lines": len(problems),
            "first_ts": str(events[0].get("ts") or "") if events else "",
            "last_ts": str(events[-1].get("ts") or "") if events else "",
        })
    return out


def summarize(events: Iterable[Mapping[str, Any]]) -> dict:
    """按角色 / 动作 / 结局计数（给 `session show` 与报告用）。"""
    roles: dict[str, int] = {}
    actions: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for e in events:
        for bucket, key in ((roles, str(e.get("role") or "")),
                            (actions, str(e.get("action") or "")),
                            (outcomes, str(e.get("outcome") or "")),
                            (kinds, str(e.get("kind") or ""))):
            if key:
                bucket[key] = bucket.get(key, 0) + 1
    return {"roles": roles, "actions": actions, "outcomes": outcomes, "kinds": kinds}


def selftest() -> int:
    """就地自检：追加 → 读回 → 坏行逐条报出 → 按项目隔离。"""
    import tempfile

    base = pathlib.Path(tempfile.mkdtemp(prefix="agentflow_sessions_"))
    ok = True

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f" —— {detail}" if detail else ""))
        ok = ok and cond

    p1, prob1 = append(base / "projA", {"kind": "task_end", "role": "E", "action": "run_experiment",
                                        "outcome": "ok"})
    check("追加成功", p1 is not None and not prob1, f"{p1}")
    append(base / "projA", {"kind": "task_end", "role": "H", "action": "review", "outcome": "refused"})
    ev, probs = read_session(base / "projA")
    check("读回两条且无坏行", len(ev) == 2 and not probs, f"{len(ev)} 条")
    check("按项目隔离：projB 没有会话", list_sessions(base / "projB") == [])
    # 注入一条坏行
    path = session_path(base / "projA")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{这不是 JSON\n")
    ev2, probs2 = read_session(base / "projA")
    check("坏行逐条报出（不是静默跳过）", len(ev2) == 2 and len(probs2) == 1, str(probs2))
    s = summarize(ev2)
    check("汇总按角色/结局计数", s["roles"] == {"E": 1, "H": 1} and s["outcomes"] == {"ok": 1, "refused": 1},
          json.dumps(s, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
