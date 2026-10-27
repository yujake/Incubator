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

import hashlib
import json
import os
import pathlib
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from filelock import FileLock

from .jsonlfile import read_jsonl, read_jsonl_state

SESSIONS_DIR_NAME = "sessions"
#: 趟次索引的落点目录名（工作区根下）。
#:
#: 为什么另起一个目录而不塞进 `runs/`：`runs/` 是 `agent_loop` 写检查点
#: `runs/agent-<角色>-<会话号>.json` 的地方，它的读者用 `agent-.json` 这个形状认文件。
#: 索引是另一族派生数据（不是检查点），混进同一个目录会让那些形状匹配多看见一个文件 ——
#: 改一个目录名的代价，比让每个既有读者都学会"跳过索引那份"小得多。
RUN_INDEX_DIR_NAME = "index"
#: 索引文件名。
RUN_INDEX_NAME = "run-index.json"
#: 索引的形状版本。它是派生数据：版本变了不许猜，一律重建。
RUN_INDEX_VERSION = 1
ENV_SESSION = "AGENTFLOW_SESSION"

#: 提问 / 回答那两种事件的 kind。字面量与 `userio.ASK_KIND` / `userio.ANSWER_KIND`
#: 逐字相同（`userio.py:85`），但不从那里导入：`userio` 是 `sessions` 的下游
#: （`userio` 导入本模块），反向导入会成环。判据 `tests/test_run_index.py` 有一条
#: 断言这里两处字面量与 `userio` 的常量相等 —— 于是"抄了一份"这件事有机器读数守着。
QUESTION_EVENT_KIND = "user_question"
ANSWER_EVENT_KIND = "user_answer"


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


# ====================================================================== 写路径上的可选钩子
#
# 这一族是"网页端实时刷新"的接入点（裁定 1a）：`sse.attach()` 把监听器装到这里，
# 于是每次会话追加成功之后会顺着它发一条 `state` 事件出去。三条纪律：
#
# 1. 缺省 `None` ⇒ 既有行为逐字节不变（调用点上只多一个 `is not None`）；
# 2. 监听器是旁路：它坏掉不许把写路径带坏。写成功了就是成功了；监听器抛出的
#    异常被接住并记进 `append_hook_problem()` —— 不是静默吞掉，是"写成了、但旁路
#    没查成"这一档（三态纪律：不许把"没查成"折成"没发生"）；
# 3. 只有真的写成（`problem` 为空）才通知：写失败还发事件，会让网页端显示
#    一条盘上并不存在的事件。
#
#: 追加成功后的监听器：`(root, event) -> None`。`None` = 没人接。
_APPEND_HOOK: "Callable[[Any, Mapping[str, Any]], None] | None" = None
#: 上一次监听器抛出的问题（空串 = 没出过问题）。只留最近一条：这是"旁路坏没坏"的
#: 读数，不是一条日志（日志归 `store` 的事件面）。
_APPEND_HOOK_PROBLEM: str = ""


def set_append_hook(hook: "Callable[[Any, Mapping[str, Any]], None] | None"
                    ) -> "Callable[[Any, Mapping[str, Any]], None] | None":
    """装上/撤掉"追加成功之后"的监听器；返回被替换掉的那一个（可能为 `None`）。

    为什么把旧的返回出来：装配方（`sse.attach`）要能说清"我顶掉了谁"，而判据要能
    在用例结束时把钩子还原成它进来时的样子（`detach` 用它，见 `webui/sse.py`）。
    """
    global _APPEND_HOOK  # noqa: PLW0603 - 一个进程一个槽，见上面那一节
    previous, _APPEND_HOOK = _APPEND_HOOK, hook
    return previous


def append_hook_problem() -> str:
    """监听器上一次抛出的问题（空串 = 没出过问题）。"""
    return _APPEND_HOOK_PROBLEM


def _notify_append(root: Any, event: Mapping[str, Any]) -> None:
    """把"刚写成的那条事件"交给监听器（没装监听器 ⇒ 立刻返回）。

    接住异常并记一条读数：监听器（网页端的推送）坏掉时，会话记录照样是完整的 ——
    把"推送坏了"变成"审计面少一行"是本末倒置。
    """
    global _APPEND_HOOK_PROBLEM  # noqa: PLW0603 - 见上（只记最近一条）
    hook = _APPEND_HOOK
    if hook is None:
        return
    try:
        hook(root, event)
    except Exception as exc:  # noqa: BLE001 - 旁路：见 `_notify_append` 的 docstring
        _APPEND_HOOK_PROBLEM = f"{type(exc).__name__}: {exc}"
    else:
        _APPEND_HOOK_PROBLEM = ""


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

    写成功之后会通知 `set_append_hook` 装上的那个可选监听器（网页端的 SSE 用它）。
    没有装监听器时（缺省）这条路径与加上它之前逐字节相同：多出来的只有一个
    `is not None` 判断。
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
    _notify_append(root, row)
    return path, ""


def read_session(root: Any, sid: str | None = None) -> tuple[list[dict], list[str]]:
    """读一段会话；返回 `(事件, 问题)`。坏行逐条报出，不静默跳过。

    JSONL 的读法只有一份实现：:func:`jsonlfile.read_jsonl`（`draft/36` T-6 合并）。
    合并前三处（这里、`artifacts`、`signatures`）各写了一份同形的循环 ——
    漂移的表现是"同一份坏文件，`verify` 说它坏、`session show` 说它好"，而没有东西会报错。
    """
    return read_jsonl(session_path(root, sid))


def _iter_sessions(root: Any) -> list[tuple[pathlib.Path, list[dict], list[str]]]:
    """这个项目的每一场会话：`(路径, 事件, 坏行问题)`，按文件名排序、每个文件只读一遍。

    为什么把「读一遍」收成一处：`list_sessions` / `session_ids_with_questions` /
    `compute_run_index` 原先各读一遍盘，于是 `compute_run_index` 一次调用就把整份
    会话语料读了 4 遍（2026-10-27 实测，探针 `temp/rbe4_sessions_reads.py`：6.6MB 的
    `sessions/` 被读成 26.3MB / 404ms；合并后 1.0 遍 / 110ms）。
    三处读的是同一批文件、同一个口径（`jsonlfile.read_jsonl`），合起来只该读一遍。
    目录不存在 ⇒ 空列表（合法初态，不是错误）。
    """
    d = sessions_dir(root)
    if not d.is_dir():
        return []
    return [(p, *read_session(root, p.stem)) for p in sorted(d.glob("*.jsonl"))]


def read_all_sessions(root: Any) -> tuple[list[dict], dict[str, Any]]:
    """读这个工作区的全部会话记录（不按 sid 分）：返回 `(记录, 读数)`。

    ## 与 `read_session` 的分工（2026-10-27，R-BE1 的 ②-1）

    两件事问的不是一个问题，但"怎么读一个 JSONL"只有一份实现（`jsonlfile.read_jsonl_state`）：

    - `read_session(root, sid)`：读一段会话，`problems` 是逐行/逐文件的问题清单
      （`stopctl` / `closing` / `statusreport` / `webui` 按 sid 问）；
    - `read_all_sessions(root)`：读这台机器上跑过的全部记录，把它折成一份"读了多少、
      坏了几行、哪几个文件读不出来"的读数（`errorstats` 与 `readouts` 的
      errors/flow/cost 问的是这个）。

    ## 读数那五格（键名与顺序都是既有输出面的一部分）

    `checked` / `files` / `records` / `bad_lines` / `unreadable_files` / `reason`：
    改前这一份读数是 `errorstats._read_sessions` 自己算的（第二份实现），而它与
    `read_session` 对"读不明白"的判定各说一套。现在两者同源于 `read_jsonl_state`：

    - `unreadable_files`：`state == "unreadable"` 的文件名（读不出来：权限 / 非 UTF-8 /
      读之前被删掉）；
    - `bad_lines`：坏行条数（不是合法 JSON，或合法 JSON 但不是对象 —— 与
      `read_jsonl_state` 的 `problems` 逐条对应）；
    - `files`：读得出来的文件数；`checked`：至少一个文件读得出来
      （"一个都读不出来"是没查成，不是 0 条记录）。

    `reason` 的三句与改前逐字相同（它们是 `sources["sessions"]` 的一部分，换了字就是换了读数）。
    """
    reading: dict[str, Any] = {"checked": False, "files": 0, "records": 0,
                               "bad_lines": 0, "unreadable_files": [], "reason": ""}
    root_path = pathlib.Path(str(root))
    if not root_path.exists() or not root_path.is_dir():
        reading["reason"] = f"工作区不存在：{root}"
        return ([], reading)
    folder = sessions_dir(root_path)
    if not folder.is_dir():
        reading.update(checked=True, reason="没有 sessions 目录（按 0 条读）")
        return ([], reading)
    paths = sorted(p for p in folder.glob("*.jsonl") if p.is_file())
    if not paths:
        reading.update(checked=True, reason="sessions 目录里没有 .jsonl")
        return ([], reading)
    records: list[dict] = []
    bad = 0
    broken: list[str] = []
    for path in paths:
        got, problems, state = read_jsonl_state(path)
        if state in ("unreadable", "absent"):
            # `absent` 只能是"glob 之后被删掉"：按读不出来记，不静默当空文件。
            broken.append(path.name)
            continue
        records.extend(got)
        bad += len(problems)
    readable = len(paths) - len(broken)
    reading.update(files=readable, records=len(records), bad_lines=bad,
                   unreadable_files=broken,
                   checked=readable > 0,
                   reason="" if readable else "sessions 目录里每个文件都读不明白")
    return (records, reading)


def list_sessions(root: Any) -> list[dict]:
    """列出这个项目的所有会话（按文件名排序）。目录不存在 ⇒ 空列表（合法初态）。"""
    return [
        {
            "sid": p.stem,
            "path": str(p),
            "events": len(events),
            "bad_lines": len(problems),
            "first_ts": str(events[0].get("ts") or "") if events else "",
            "last_ts": str(events[-1].get("ts") or "") if events else "",
        }
        for p, events, problems in _iter_sessions(root)
    ]


# ====================================================================== 趟次索引（裁定 O2）
#
# 名字的边界（不许混用，见 `draft/78 §7` 的提醒）：这里的「趟次」是「一个会话文件里
# 的第几趟运行」（一条 `agent_run_start` 到它之后的 `agent_run_end` 或文件尾）。
# `projects.py` 的 `run_index: int` 是另一个概念（这个项目第几趟，配 `out/run-<n>`），
# 两者不同模块、不同语义，本模块不去碰那一个、也不把这张表塞进 `projects.py`。
#
# 为什么要有索引：`webui.state._scan` 每次请求都对每个会话文件现切一遍。索引是同一批
# 事实的派生表 —— 它读一次、落一次，GUI 读它；现切降为回退。派生数据的第一条纪律是
# 「它可能与源不一致」：所以这里同时给出 `reconcile_run_index`，把索引与事件现算结果
# 逐趟对账。对不上就是 `drift`，绝不静默用索引顶替现算。


def run_index_path(root: Any) -> pathlib.Path:
    """趟次索引的落点（只算路径，不建目录）。"""
    return pathlib.Path(str(root)) / RUN_INDEX_DIR_NAME / RUN_INDEX_NAME


def runs_in_session(events: Iterable[Mapping[str, Any]], *, sid: str = "") -> list[dict]:
    """把一段会话的事件扫成「每一趟的运行读数」（纯函数，不碰盘）。

    一趟 = 一条 `agent_run_start` 到它之后的 `agent_run_end`（或文件尾）。没有开始
    标记的事件不算一趟：那是「轮次之外的零散事件」，折成"一趟 0 步的运行"会让
    「最近一趟」被一个空壳顶掉（`webui/state.py` 的 `_scan` 把这条纪律写在同一处）。

    键与 `webui.state._scan` 逐字相同（20 个）—— `draft/75 §1.3` 的 `RunRow`：
    `sid, role, task, start_index, start_ts, steps, llm_calls, usd, unknown_usd,
    stop_reason, final_chars, summons, messages, elapsed_sec, last_shape,
    end_index, end_ts, waiting_on, waiting, events_in_run`。
    `usd`/`final_chars`/`summons`/`messages`/`elapsed_sec` 读不到就是 `None`
    （三态：不是 0）；`unknown_usd` 是"算不出价钱的那几次"的计数，它天然是 0 起算。
    """
    rows = list(events)
    runs: list[dict] = []
    cur: dict[str, Any] | None = None
    for i, e in enumerate(rows):
        kind = str(e.get("kind") or "")
        if kind == "agent_run_start":
            cur = {
                "sid": sid, "role": str(e.get("role") or ""),
                "task": str(e.get("task") or ""),
                "start_index": i, "start_ts": str(e.get("ts") or ""),
                "steps": 0, "llm_calls": 0, "usd": None, "unknown_usd": 0,
                "stop_reason": "", "final_chars": None, "summons": None,
                "messages": None, "elapsed_sec": None, "last_shape": "",
                "end_index": None, "end_ts": "",
            }
            runs.append(cur)
            continue
        if cur is None:
            continue
        if kind == "agent_step":
            cur["steps"] += 1
            cur["last_shape"] = str(e.get("shape") or "")
        elif kind == "llm_call":
            cur["llm_calls"] += 1
            usd = e.get("usd")
            if usd is None:
                cur["unknown_usd"] += 1
            else:
                try:
                    cur["usd"] = float(usd) + (cur["usd"] or 0.0)
                except (TypeError, ValueError):
                    cur["unknown_usd"] += 1
        elif kind == "agent_run_end":
            cur["stop_reason"] = str(e.get("stop_reason") or "")
            cur["final_chars"] = e.get("final_chars")
            cur["summons"] = e.get("summons")
            cur["messages"] = e.get("messages")
            cur["elapsed_sec"] = e.get("elapsed_sec")
            cur["end_index"] = i
            cur["end_ts"] = str(e.get("ts") or "")
            cur = None
    # 待答问题挂在「正在等它」的那一趟上：与 `_scan` 同一口径
    # （停止理由空着却停在一个没答的问题上 ⇒ 那一档写 `waiting_for_user`）。
    pending_idx: list[int] = []
    answered = {str(e.get("qid")) for e in rows if e.get("kind") == ANSWER_EVENT_KIND}
    for i, e in enumerate(rows):
        if e.get("kind") != QUESTION_EVENT_KIND:
            continue
        qid = str(e.get("qid") or "")
        if qid and qid not in answered:
            pending_idx.append(i)
    for run in runs:
        hi = run["end_index"] if run["end_index"] is not None else len(rows)
        mine = [str(rows[j].get("qid") or "") for j in pending_idx
                if run["start_index"] < j <= hi]
        run["waiting_on"] = mine
        if not run["stop_reason"] and mine:
            run["stop_reason"] = "waiting_for_user"
        run["waiting"] = bool(mine) and run["stop_reason"] == "waiting_for_user"
        run["events_in_run"] = max(0, hi - run["start_index"])
    return runs


def compute_run_index(root: Any) -> dict:
    """从 `sessions/*.jsonl` 现算整份索引（不改盘；坏行不影响其余会话）。

    读不到某一场会话时它按"这一场一趟都没有"收下 —— 但这不是抹掉三态：
    `reconcile_run_index` 会把"盘上读到的东西与索引不一致"报成 `drift`，
    而"整条会话目录读不到"由 :func:`list_sessions` 的既有口径（空目录 = 合法初态）承担。
    """
    root_p = pathlib.Path(str(root))
    sessions: dict[str, dict] = {}
    asked: list[str] = []
    # 一趟读完：`list_sessions` + `read_session` + `session_ids_with_questions` 原先
    # 各读一遍（放大到 4.0×），现在同一个文件只读一次（口径见 `_iter_sessions`）。
    for path, events, _problems in _iter_sessions(root_p):
        sid = path.stem
        if not sid:
            continue
        runs = runs_in_session(events, sid=sid)
        enders = [int(r["end_index"]) for r in runs if isinstance(r.get("end_index"), int)]
        sessions[sid] = {
            "runs": runs,
            "last_end_index": max(enders) if enders else None,
            "digest": digest_runs(runs),
        }
        if any(e.get("kind") == QUESTION_EVENT_KIND for e in events):
            asked.append(sid)
    for sid in asked:
        # 提问但一趟都没跑起来的会话也要在表里（否则"待答问题的归属会话"在索引里不存在，
        # 读者会以为那场会话没被扫过）。
        sessions.setdefault(sid, {"runs": [], "last_end_index": None,
                                  "digest": digest_runs([])})
    return {"version": RUN_INDEX_VERSION,
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "sessions": sessions}


def session_ids_with_questions(root: Any) -> list[str]:
    """哪些会话里出现过提问（本模块的本地实现，只为索引不漏会话）。

    为什么不调 `userio.session_ids_with_questions`：`sessions.py` 是 `userio` 的下游
    （`userio` 导入本模块），反向导入会成环。判据 `tests/test_run_index.py` 有一条
    断言这两处读出的会话号集合相同 —— 于是"两份实现"这件事有机器读数守着。
    读盘走 `_iter_sessions`（每个文件一遍），本函数不再自己扫第二遍。
    """
    return [
        p.stem
        for p, events, _problems in _iter_sessions(root)
        if p.stem and any(e.get("kind") == QUESTION_EVENT_KIND for e in events)
    ]


def digest_runs(runs: Iterable[Mapping[str, Any]]) -> str:
    """一批趟次读数的摘要（规范化 JSON 的 sha256；空批 ⇒ 空表也有摘要）。

    它的用途只有一个：让「索引被人手改了一个字节」这件事有一个字节级的机器读数
    （改 `steps` 会改摘要，于是对账报 `drift`）。
    """
    canon = json.dumps([dict(r) for r in runs], ensure_ascii=False, sort_keys=True,
                       default=str, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def load_run_index(root: Any) -> tuple[dict | None, str]:
    """读索引：返回 `(索引, 读不到的原因)`。原因非空 ⇒ 索引是 `None`（没查成）。

    三态在这里落成三句话：文件不在盘上 ⇒ 原因里明说"还没建"（合法初态，调用方据此
    回退现算）；文件在但解不开 ⇒ 原因里带异常类型（那是"没查成"，不是"没有"）；
    版本不认识 ⇒ 原因里带两个版本号（不许猜）。
    """
    path = run_index_path(root)
    if not path.is_file():
        return None, f"索引不在盘上（还没建）：{path}"
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"索引读不出来：{type(exc).__name__}: {exc}"
    if not isinstance(got, dict):
        return None, f"索引的形状不对（顶层不是对象）：{type(got).__name__}"
    version = got.get("version")
    if version != RUN_INDEX_VERSION:
        return None, (f"索引的形状版本不认识：盘上 {version!r}，本模块只认 "
                      f"{RUN_INDEX_VERSION}")
    if not isinstance(got.get("sessions"), dict):
        return None, "索引里没有 sessions 这一张表"
    return got, ""


def rebuild_run_index(root: Any) -> dict:
    """现算一份索引并原子落盘；返回那份索引。

    原子写（先写临时文件再 `replace`）：索引是派生数据，读的人不该看见半份 JSON。
    写失败不吞掉 —— 调用方要知道"这次没落成"（没落成时返回值仍然可用，它是算出来的）。
    """
    index = compute_run_index(root)
    path = run_index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    body = json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    tmp.replace(path)
    return index


def reconcile_run_index(root: Any) -> dict:
    """把索引与「事件现算结果」逐趟对账：返回 `{tri, drift, reason, sessions}`。

    `tri` 三档（与 `reviewaccept` 同一套词表）：
    - `computed`：索引在、读得出、且与现算结果逐趟一致（`drift` 为空）；
    - `unreadable`：索引不在盘上或读不出来（`reason` 说清是哪一档）——
      不是 `computed`，也不是"零处不一致"；
    - `not_applicable`：这个工作区一场会话都没有 ⇒ 没有可对账的东西
      （不是"对上了"，是没有源）。

    对账逐会话比三件事：索引里有而盘上没有（会话被删 / 被改名 ⇒ 报 `drift`）、
    盘上有而索引里没有（新会话没进索引 ⇒ 报 `drift`）、两边的趟次读数现算不同
    （手改索引一个字节 ⇒ 摘要不同 ⇒ 报 `drift`）。
    """
    computed = compute_run_index(root)
    live = computed["sessions"]
    if not live:
        return {"tri": "not_applicable", "drift": [], "sessions": [],
                "reason": "这个工作区一场会话都没有（合法初态：没有可对账的源）"}
    index, why = load_run_index(root)
    if index is None:
        return {"tri": "unreadable", "drift": [], "sessions": sorted(live),
                "reason": why}
    stored = index.get("sessions") or {}
    drift: list[str] = []
    for sid in sorted(set(stored) - set(live)):
        _rec = stored.get(sid)
        _rec = _rec if isinstance(_rec, dict) else {}
        drift.append(f"会话 {sid}：索引里有它（{len(_rec.get('runs') or [])} 趟），"
                     "而盘上已经没有这场会话了")
    for sid in sorted(set(live) - set(stored)):
        drift.append(f"会话 {sid}：盘上有它，索引里没有（索引落后或没建全）")
    for sid in sorted(set(live) & set(stored)):
        want = live[sid]
        got = stored.get(sid) or {}
        # ① 索引自己就是不守恒的（表里的 `runs` 复算摘要 ≠ 表里存着的 `digest`）
        #    ⇒ 这一格被人动过。它与下面 ② 分开报：一个是"索引内部对不上"，
        #    一个是"索引与盘上的事件对不上"，读的人要对两种漂移做不同处置。
        stored_runs = got.get("runs")
        if isinstance(stored_runs, list) and got.get("digest") != digest_runs(stored_runs):
            drift.append(f"会话 {sid}：索引内部对不上 —— 表里的 runs 复算摘要与它自己"
                         f"存的 digest 不是同一个（表被手改过，而 digest 没跟着改）")
        if got.get("digest") == want["digest"]:
            continue
        n_stored = len(got.get("runs") or [])
        n_live = len(want["runs"])
        if n_stored != n_live:
            drift.append(f"会话 {sid}：索引里 {n_stored} 趟，盘上现算是 {n_live} 趟")
        else:
            drift.append(f"会话 {sid}：{n_live} 趟的读数与索引里的不一致"
                         f"（索引摘要 {str(got.get('digest'))[:12]}…，"
                         f"现算摘要 {want['digest'][:12]}…）")
    reason = "" if not drift else "索引与事件现算结果对不上，见 drift（逐条）"
    return {"tri": "computed", "drift": drift, "sessions": sorted(live), "reason": reason}


def run_index_report(root: Any) -> dict:
    """给消费者的一次完整读数：`{usable, tri, reason, drift, sessions, index}`。

    为什么在 `reconcile_run_index` 之外还要这一层：回退判据是"索引不可用就现算"，
    而那件事要求一次读里同时拿到"索引本身"与"对账结论"。分两次调用（先读、再对账）
    的话，两次之间盘上的东西可能已经变了 —— 那正是索引这类派生数据最难查的一类缺陷
    （读到的索引与当时的对账结论不是同一份）。

    `usable` 只有两种情况为真：索引读得出，且对账没有 `drift`。`tri` 把它写成
    同一件事的三个词：`computed`（可用）/ `unreadable`（读不出或对不上）/ 
    `not_applicable`（没有会话可对账 —— 索引按空表算，仍可用）。
    """
    verdict = reconcile_run_index(root)
    index, why = load_run_index(root)
    if verdict["tri"] == "unreadable":
        return {"usable": False, "tri": "unreadable", "reason": verdict["reason"],
                "drift": list(verdict["drift"]), "sessions": verdict["sessions"],
                "index": None}
    if verdict["tri"] == "not_applicable":
        return {"usable": True, "tri": "not_applicable", "reason": verdict["reason"],
                "drift": [], "sessions": [], "index": None}
    if verdict["drift"]:
        return {"usable": False, "tri": "unreadable", "reason": verdict["reason"],
                "drift": list(verdict["drift"]), "sessions": verdict["sessions"],
                "index": index}
    del why  # 走 here 时索引一定读得出来（上面 unreadable 那一支已经接住了它）
    return {"usable": True, "tri": "computed", "reason": "", "drift": [],
            "sessions": verdict["sessions"], "index": index}


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
          json.dumps(s, ensure_ascii=False, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
