# -*- coding: utf-8 -*-
"""用户端 Web 界面：本地小服务 + 服务端渲染（只读投影 + 一个写回答的入口）。

## 这是什么

一个标准库级别的小服务（`http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`），
把工作区盘上的三样东西渲染成人能读的页面：

- 「全局待回答面板」 —— 谁在问、问了多久、问了什么、有哪些选项，以及就地提交回答；
- 「运行态」 —— 每一趟（按会话号分组）的角色、步数、停止理由、花销、是否停在等谁；
- 「一趟详情」 —— 会话事件的可回放卡片 + 这一趟的交付说明 `out/review/REPORT.md`。

外加 `GET /api/state` 给出同一批读数的 JSON（供测试与将来的前端轮询）。

## 为什么需要它（不是"CLI 不好用"）

CLI 够用，但「有一趟正停在等你回答」这件事在终端里只有你恰好打开那个终端才看得见。
我们在 `docs/USER-END-DSH-STYLE.md` §3 抄了 DSH 的界面纪律（状态不进组件 state、
卡片渲染已落盘的切片、全局面板），而其中「全局可达」这一条在「我们自己的结构」里
同样成立：`DESIGN-CONDUCTOR.md` §1.1「用户只对主控说话」⇒ 人需要一个不挑会话的
入口，因为提问正阻塞着某一趟、而那一趟可能不在人当前看的地方。
所以 `GET /` 的待答面板「从不按会话过滤」。

## 三条纪律（两条抄的是 DSH 的界面纪律，一条是本项目结构决定的）

1. 「状态一律从盘上派生」（界面纪律，抄自 DSH：状态不进组件 state）：每次请求都重新
   读会话文件、台账、报告，页面里不缓存、不做后台轮询线程。读一次快照抽成纯函数
   :func:`snapshot`，同一份盘上数据渲染两次得到逐字节相同的 HTML。
2. 「每个事实行给两个独立读数」（界面纪律，抄自 DSH：行里给两个独立事实）：例如运行态
   行同时给「盘上最后一条事件是什么」与「这一页读到了多少条事件」；读不到的东西写
   `unknown` / `没查成`（这是我们自己的三态纪律，`DESIGN-INTERACTIONS.md` §3.4），
   绝不折成 0 或空。
3. 「回答的文本两种口径都认」（不是抄来的：这是本项目自己的兼容要求 —— 并行的
   `userio` 改造要与旧会话文件共存）：`custom` 非空取它，否则 `"、".join(selected)`，
   否则退回旧的 `answer` 字段。读 `userio` 的返回一律用 `getattr(obj, "x", None)` /
   `dict.get`，不假设新字段一定存在。

## 安全与失败姿态

- 服务默认只听 `127.0.0.1`；`--token` 给一个共享口令（或 `AGENTFLOW_WEB_TOKEN`），
  给了就要求 `?token=` 或 `Authorization: Bearer`；
- 用户与模型产生的「一切文本都经 :func:`html.escape` 转义后」才进 HTML（负控在
  `tests/test_webui.py`）；
- 写失败不许折成 200：`POST /answer` 的 qid 不在待答清单 ⇒ 409 并在页面上说清
  「已经被谁什么时候答过了」或「没有这个号」；落盘失败 ⇒ 500 并原样给出错误；
- 成功 ⇒ 303 重定向回 `/`（PRG：刷新不重复提交）。

## 设计依据与判据

设计依据：`docs/USER-END-DSH-STYLE.md`（§1 抄了什么、§2 令牌体系、§3 界面纪律、
§4 三处刻意差异）。判据：`tests/test_webui.py`（正控与负控各若干条，逐条见那里的
docstring）。`APP_CSS` 只用 `--dsw-alias-*` / `--ds-*` 令牌这条，由
`tests/test_webui.py::test_app_css_uses_only_tokens` 用正则机械地查。
"""

from __future__ import annotations

import argparse
import json
import html as _html
import os
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import sessions as SS
from . import userio as U
from .web.assets import STYLESHEET

__all__ = ["snapshot", "serve", "run", "render_root", "render_run", "answer_text_of"]

#: 默认监听端口。
DEFAULT_PORT = 8788
#: 默认监听地址（只对本机开）。
DEFAULT_HOST = "127.0.0.1"
#: 页面里 JSON 摘要的截断长度（读数页不该被一条超长 payload 撑爆）。
CLIP = 400
#: 交付说明的落点（工作区相对路径，`docs`/`agent_prompts` 的口径）。
REPORT_REL = ("out", "review", "REPORT.md")
#: 会话号允许的字符集（它会被拼进文件名，必须挡目录穿越）。
_SID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
#: 停止理由 → 徽标词汇：三态加一档「停在等待用户」。
_STOP_BADGES = {
    "final": ("badge-pass", "跑完"),
    "budget": ("badge-unknown", "预算用尽"),
    "max_steps": ("badge-unknown", "步数用尽"),
    "not_wired": ("badge-fail", "没接线"),
    "bad_json_limit": ("badge-fail", "坏 JSON 连击"),
    "bad_args_limit": ("badge-fail", "坏参数连击"),
    # `draft/37` §136：同调用 + 同读数连着到上限 ⇒ 这一趟停在"没有新事实"。
    # 刻意不是 `badge-fail`：那不是出错，是"这一趟没有往前走"（一档读数）。
    "no_progress_limit": ("badge-unknown", "原地打转"),
    "waiting_for_user": ("badge-pending", "停在等用户"),
}


# ====================================================================== 取值帮手
def _dict(obj: Any) -> dict[str, Any]:
    """把一个可能是 dict / 对象 / 别的东西读成 dict（读不到就是空 dict）。"""
    if isinstance(obj, Mapping):
        return dict(obj)
    if obj is None:
        # 这里不折叠三态：本函数是渲染期的宽松取值帮手，`None` 的语义就是
        # 「这个对象没有字段可读」（调用方随后用取值帮手把它写成 `unknown`），
        # 所以空 dict 是它的正确答案，而不是「没读到就当成空」。
        return {}
    for name in ("to_dict", "model_dump", "as_dict"):
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                got = fn()
            except Exception:  # noqa: BLE001 - 读数页不该因为一个字段崩掉
                continue
            if isinstance(got, Mapping):
                return dict(got)
    return {}


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """按候选名字依次取一个字段（dict 与对象两种形态都认）。"""
    src = _dict(obj)
    for name in names:
        if name in src:
            return src[name]
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _text(value: Any) -> str:
    """把任意值是安全地读成字符串（None / 读不出来 ⇒ 空串）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _clip(value: Any, limit: int = CLIP) -> str:
    """把任意值读成一段可显示的短文本（长了两头留、中间省）。"""
    if isinstance(value, str):
        s = value
    else:
        try:
            s = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            s = str(value)
    s = s.strip()
    if len(s) <= limit:
        return s
    head = max(1, limit - 40)
    return f"{s[:head]} …（共 {len(s)} 字，已截断）"


def _esc(value: Any) -> str:
    """进 HTML 前的唯一一道转义（用户与模型产生的文本一个都不许绕过）。"""
    return _html.escape(_text(value), quote=True)


def _e(value: Any) -> str:
    """短别名：给 f-string 里用，少写点括号。"""
    return _esc(value)


def _num(value: Any, default: str = "unknown") -> str:
    """读数：读得到数字就打印它，读不到就 `unknown`（绝不折成 0）。"""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return str(value)
    s = _text(value).strip()
    return s if s else default


def _usd(value: Any, default: str = "unknown") -> str:
    """花销读数：None / 读不出来 ⇒ `unknown`（「没查成」不是「花了零」）。"""
    if isinstance(value, bool) or value is None:
        return default
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    """当前本地时间（ISO，秒）。渲染在页脚「最后更新」那一行 —— 它是投影的一部分，
    所以 `tests/test_webui.py::test_rendering_is_a_projection_not_a_cache` 会把这只钟
    钉成常量再比字节：否则两次请求跨一秒就会红（2026-10-03 的全量里真红过一次）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _age(ts: str, ref: str) -> str:
    """'问了多久'：两个时间戳之差；算不出来就 `没查成`（不是 0）。"""
    if not ts or not ref:
        return "没查成"
    try:
        a = datetime.fromisoformat(ts)
        b = datetime.fromisoformat(ref)
    except ValueError:
        return "没查成"
    if a.tzinfo is None:
        a = a.replace(tzinfo=b.tzinfo)
    if b.tzinfo is None:
        b = b.replace(tzinfo=a.tzinfo)
    sec = (b - a).total_seconds()
    if sec < 0:
        return f"{ts}（时钟早于现在？）"
    if sec < 90:
        return f"{int(sec)} 秒"
    if sec < 5400:
        return f"{sec / 60:.1f} 分钟"
    if sec < 172800:
        return f"{sec / 3600:.1f} 小时"
    return f"{sec / 86400:.1f} 天"


def answer_text_of(event: Mapping[str, Any] | Any) -> str:
    """从一条回答事件里读出「用户到底说了什么」，两种口径都认。

    新口径（与并行的 `userio` 改造对齐）：`custom` 非空取它，
    否则 `"、".join(selected)`；旧口径：`answer` 字段。
    """
    custom = _text(_get(event, "custom"))
    if custom:
        return custom
    selected = _get(event, "selected")
    if isinstance(selected, (list, tuple)):
        picked = [_text(x).strip() for x in selected]
        picked = [x for x in picked if x]
        if picked:
            return "、".join(picked)
    return _text(_get(event, "answer", default=""))


def option_view(raw: Any) -> dict[str, Any]:
    """把一个选项读成 `{label, description, multi}`。

    `userio.Question.options` 今天是 `tuple[str, ...]`，但 DSH 的形状是
    `{label, description}`（`docs/USER-END-DSH-STYLE.md` §3）。所以这里两种都认：
    裸字符串 ⇒ `label` 就是它、`description` 空；dict/对象 ⇒ 取 `label` / `description`
    （也接受 `text` / `value` / `desc` / `hint` 这几个近义名，读不到就是空）。
    """
    if isinstance(raw, str):
        return {"label": raw, "description": "", "multi": False}
    if raw is None:
        return {"label": "", "description": "", "multi": False}
    label = _text(_get(raw, "label", "text", "value", "id", default=""))
    desc = _text(_get(raw, "description", "desc", "hint", "detail", default=""))
    multi = bool(_get(raw, "multiSelect", "multi", "multiple", default=False))
    if not label and not desc:
        label = _clip(raw, 200)
    return {"label": label, "description": desc, "multi": multi}


def _sid_ok(sid: str) -> bool:
    """会话号是不是一个安全的文件名主干（挡 `../` 这类穿越）。"""
    return bool(sid) and all(ch in _SID_OK for ch in sid) and ".." not in sid


# ====================================================================== 快照
def _scan(session_root: Path, sid: str, events: Sequence[Mapping[str, Any]],
          problems: Sequence[str]) -> dict[str, Any]:
    """把一个会话的事件扫成「待答问题 + 每一趟的运行态」（纯函数，不碰盘）。"""
    events = list(events)
    # ---- 提问与回答的配对（同一会话内配对；跨会话的 qid 各归各的会话）
    answers: dict[str, dict[str, Any]] = {}
    answer_index: dict[str, int] = {}
    for i, e in enumerate(events):
        if str(e.get("kind") or "") == "user_answer":
            qid = _text(e.get("qid"))
            if qid and qid not in answers:
                answers[qid] = dict(e)
                answer_index[qid] = i
    asked_qids: set[str] = set()
    pending: list[dict[str, Any]] = []
    for i, e in enumerate(events):
        if str(e.get("kind") or "") != "user_question":
            continue
        qid = _text(e.get("qid"))
        if not qid:
            continue
        asked_qids.add(qid)
        if qid in answers:
            continue
        opts = [_opts_view(x) for x in (e.get("options") or [])]
        pending.append({
            "qid": qid,
            "sid": sid,
            "role": _text(e.get("role")),
            "ts": _text(e.get("ts")),
            "timeout_sec": e.get("timeout_sec"),
            "text": _text(e.get("text")),
            "options": opts,
            "multi": bool(e.get("multiSelect") or e.get("multi")
                          or any(o["multi"] for o in opts)),
            "index": i,
        })
    # ---- 每一趟 = 一条 `agent_run_start` 到它之后的 `agent_run_end`（或文件尾）。
    #
    # 没有开始标记的事件「不许」被折成一趟：那是「轮次之外的零散事件」（例如人刚
    # 提交的一条 `user_answer`，或者一次不带 `--sid` 的 CLI 调用写的 `task_end`）。
    # 把它们折成"一趟 0 步的运行"会让"最近一趟"被一个空壳顶掉，而真机里那正好发生
    # 在人按下「提交」的那一刻（父的复现：`agent_run_end` 之后紧跟的 `user_answer`
    # 成了新一轮的开始）。所以零散事件单独收成一栏，并如实写"没有开始标记"。
    runs: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    last_kind = ""
    last_seq = -1
    for i, e in enumerate(events):
        kind = str(e.get("kind") or "")
        if kind:
            last_kind = kind
            last_seq = max(last_seq, int(e.get("seq") or i))
        if kind == "agent_run_start":
            cur = {
                "sid": sid, "role": _text(e.get("role")), "task": _text(e.get("task")),
                "start_index": i, "start_ts": _text(e.get("ts")),
                "steps": 0, "llm_calls": 0, "usd": None, "unknown_usd": 0,
                "stop_reason": "", "final_chars": None, "summons": None,
                "messages": None, "elapsed_sec": None, "last_shape": "",
                "end_index": None, "end_ts": "",
            }
            runs.append(cur)
            continue
        if cur is None:
            # 轮次之外：只记账（条数、起止时间、有哪些 kind），不当成一趟运行。
            orphans.append({"sid": sid, "index": i, "kind": kind or "unknown",
                            "ts": _text(e.get("ts")), "role": _text(e.get("role"))})
            continue
        if kind == "agent_step":
            cur["steps"] += 1
            cur["last_shape"] = _text(e.get("shape"))
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
            cur["stop_reason"] = _text(e.get("stop_reason"))
            cur["final_chars"] = e.get("final_chars")
            cur["summons"] = e.get("summons")
            cur["messages"] = e.get("messages")
            cur["elapsed_sec"] = e.get("elapsed_sec")
            cur["end_index"] = i
            cur["end_ts"] = _text(e.get("ts"))
            cur = None
    # ---- 把待答问题挂到「正在等它」的那一趟上
    for run in runs:
        hi = run["end_index"] if run["end_index"] is not None else len(events)
        mine = [q["qid"] for q in pending if run["start_index"] < q["index"] <= hi]
        run["waiting_on"] = mine
        # 停止理由是空的、但确实停在一个没答的问题上 ⇒ 那一档是「停在等用户」
        if not run["stop_reason"] and mine:
            run["stop_reason"] = "waiting_for_user"
        run["waiting"] = bool(mine) and run["stop_reason"] == "waiting_for_user"
        run["events_in_run"] = max(0, hi - run["start_index"])
    # 挂在某一趟上的零散事件（同一会话里、在某趟范围内）不算「轮次之外」：
    # 判据是它有没有落在某条 run 的 [start, end] 区间里。
    def _inside(idx: int) -> bool:
        for r in runs:
            hi = r["end_index"] if r["end_index"] is not None else len(events)
            if r["start_index"] < idx <= hi:
                return True
        return False

    orphans = [o for o in orphans if not _inside(o["index"])]
    ordered = sorted(orphans, key=lambda o: o["index"])
    return {
        "sid": sid,
        "events_seen": len(events),
        "bad_lines": list(problems),
        "pending": pending,
        "runs": runs,
        "orphans": orphans,
        "orphan_kinds": sorted({o["kind"] for o in orphans}),
        "orphan_from": ordered[0]["ts"] if ordered else "",
        "orphan_to": ordered[-1]["ts"] if ordered else "",
        "last_kind": last_kind,
        "last_seq": last_seq,
    }


def _opts_view(raw: Any) -> dict[str, Any]:
    """选项的渲染视图（见 :func:`option_view`；这个别名只为下文顺手）。"""
    return option_view(raw)


def snapshot(root: str | Path) -> dict[str, Any]:
    """把工作区盘上的事实读成一份快照（纯函数：只读盘，不缓存、不写任何东西）。

    返回：`{"root", "generated_at", "sessions", "pending_questions", "runs", "orphans",
    "orphan_summary", "last_run", "ledger", "problems"}`。

    三态纪律在这份快照里体现为：读不到的字段是 `None` / `""` 而不是 0，
    页面渲染时再把它们写成 `unknown` / `没查成`。另外两条：

    - `runs` 只收「真的开始了的运行」（有 `agent_run_start` 事件）。没有开始标记的
      事件进 `orphans`（「轮次之外的零散事件」），并记下条数、事件种类与起止时间 ——
      它们不是「一趟 0 步的运行」（父的复现：`agent_run_end` 之后紧跟的一条
      `user_answer` 曾把「最近一趟」顶成一个空壳）；
    - `last_run` 因此只可能是 `runs` 里的一趟；一趟都没有 ⇒ `None`，
      页面写「还没有跑过」，不拿空壳或 `unknown` 顶替。
    """
    root_p = Path(str(root))
    problems: list[str] = []
    sessions: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    try:
        listed = SS.list_sessions(root_p)
    except Exception as exc:  # noqa: BLE001 - 读不到会话目录 = 没查成，不是「没有会话」
        listed = []
        problems.append(f"会话目录没查成：{type(exc).__name__}: {exc}")
    for item in listed:
        sid = _text(item.get("sid"))
        if not _sid_ok(sid):
            problems.append(f"会话号不安全，跳过：{sid!r}")
            continue
        try:
            events, bad = SS.read_session(root_p, sid=sid)
        except Exception as exc:  # noqa: BLE001
            events, bad = [], [f"{type(exc).__name__}: {exc}"]
        got = _scan(root_p, sid, events, bad)
        sessions.append({
            "sid": sid,
            "path": _text(item.get("path")),
            "events_seen": got["events_seen"],
            "events_listed": item.get("events"),
            "bad_lines": len(bad),
            "first_ts": _text(item.get("first_ts")),
            "last_ts": _text(item.get("last_ts")),
            "last_kind": got["last_kind"] or "unknown",
            "last_seq": got["last_seq"],
            "pending": len(got["pending"]),
            "runs": len(got["runs"]),
            "orphans": len(got["orphans"]),
        })
        pending.extend(got["pending"])
        runs.extend(got["runs"])
        orphans.extend(got["orphans"])
        problems.extend(f"{sid}: {p}" for p in bad)
    pending.sort(key=lambda q: (q["sid"], q["index"]))
    runs.sort(key=lambda r: (r["sid"], r["start_index"]))
    orphans.sort(key=lambda o: (o["sid"], o["index"]))
    # 「最近一趟」只认「真的开始了的运行」（有 `agent_run_start`）。整个工作区一趟都
    # 没有 ⇒ `None`（页面写「还没有跑过」），绝不拿一条空壳顶上去。
    last_run: dict[str, Any] | None = None
    for run in runs:
        key = (run["sid"], run["start_index"])
        if last_run is None or key > (_text(last_run.get("sid")),
                                      int(last_run.get("start_index") or 0)):
            last_run = run
    orphan_summary = _orphan_summary(orphans)
    ledger = _read_ledger(root_p, problems)
    return {
        "root": str(root_p),
        "generated_at": _now_iso(),
        "sessions": sessions,
        "pending_questions": pending,
        "runs": runs,
        "orphans": orphans,
        "orphan_summary": orphan_summary,
        "last_run": last_run,
        "ledger": ledger,
        "problems": problems,
    }


def _orphan_summary(orphans: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """「轮次之外的零散事件」的汇总读数（按会话分组，三态：不是「一趟 0 步的运行」）。"""
    by_sid: dict[str, list[Mapping[str, Any]]] = {}
    for o in orphans:
        by_sid.setdefault(_text(o.get("sid")), []).append(o)
    groups: list[dict[str, Any]] = []
    for sid in sorted(by_sid):
        items = sorted(by_sid[sid], key=lambda o: int(o.get("index") or 0))
        groups.append({
            "sid": sid,
            "count": len(items),
            "kinds": sorted({_text(o.get("kind")) or "unknown" for o in items}),
            "first_ts": _text(items[0].get("ts")),
            "last_ts": _text(items[-1].get("ts")),
            "first_index": items[0].get("index"),
            "last_index": items[-1].get("index"),
        })
    return {"count": len(orphans), "groups": groups}


def _read_ledger(root: Path, problems: list[str]) -> dict[str, Any]:
    """读台账（`Store`）做第二个独立读数：读不到就报「没查成」，不折成 0。"""
    out: dict[str, Any] = {"path": str(root / "data" / "events.jsonl"), "events": None,
                           "tables": None, "note": ""}
    try:
        from .store import Store

        st = Store(root)
        if not st.events_path.exists():
            out["note"] = "台账还没有（合法初态）"
            return out
        out["events"] = len(st.read_events())
        out["tables"] = len(st.rows("tasks")) if hasattr(st, "rows") else None
        # `R4` ⑨：只写口径，不改语义 —— 这个数就是 `tasks` 台账的全量行数
        # （不筛选、不减一）。它含顶趟行（`role=M` / `action=run` / `called_by=user`），
        # 所以它比"子任务条数"大；读数旁边不写这句，读的人会把它当成子任务数。
        out["tables_note"] = ("含顶趟行（role=M / action=run / called_by=user）—— "
                              "这是 tasks 台账的全量行数，不是子任务条数")
    except Exception as exc:  # noqa: BLE001 - 读数而已，读不到就如实说没查成
        out["note"] = f"台账没查成：{type(exc).__name__}: {exc}"
        problems.append(out["note"])
    return out


def _read_report(root: Path) -> tuple[str, str]:
    """读交付说明 `out/review/REPORT.md`：返回 `(状态, 文本)`。

    状态是 `ok` / `missing` / `unknown` 三态：`missing` = 不在盘上（合法初态），
    `unknown` = 在盘上但读不出来（那是「没查成」，不许显示成空报告）。
    """
    path = root.joinpath(*REPORT_REL)
    try:
        if not path.is_file():
            return "missing", ""
        return "ok", path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "unknown", f"{type(exc).__name__}: {exc}"


# ====================================================================== 渲染
def _top(state: dict[str, Any], *, crumb: str = "") -> str:
    """页面头部：我们是谁、工作区根在哪、待回答几条、最后更新何时。"""
    pend = len(state.get("pending_questions") or [])
    badge = "badge-pending" if pend else "badge-plain"
    root = _text(state.get("root"))
    return (
        '<header class="top">'
        '<div class="brand">agentflow 用户端'
        + (f' <span class="muted">/ {_e(crumb)}</span>' if crumb else "")
        + "</div>"
        f'<div class="sub">工作区根 <span class="mono">{_e(root)}</span></div>'
        '<div class="sub">'
        f'待回答 <span class="badge {badge}">{pend}</span> 条'
        f' · 最后更新 <span class="mono">{_e(state.get("generated_at"))}</span>'
        "</div>"
        "</header>"
    )


def _page(state: dict[str, Any], title: str, body: str, *, crumb: str = "") -> str:
    """套上骨架（`<style>` 内联：零外部请求、零 CDN、零 JS）。"""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n"
        f"<style>{STYLESHEET}</style>\n"
        "</head>\n<body>\n"
        + _top(state, crumb=crumb)
        + '<main class="wrap">' + body + "</main>\n"
        + "</body>\n</html>\n"
    )


def _option_html(qid: str, index: int, opt: dict[str, Any], multi: bool) -> str:
    """一个选项：label 加粗 + description 小字 + 单选/多选控件。"""
    kind = "checkbox" if multi else "radio"
    label = _text(opt.get("label"))
    desc = _text(opt.get("description"))
    value = _esc(label)
    body = f'<span class="label">{_e(label)}</span>'
    if desc:
        body += f'<span class="desc">{_e(desc)}</span>'
    return (
        '<label class="opt">'
        f'<input type="{kind}" name="selected" value="{value}">'
        f'<span class="kv">{body}</span>'
        "</label>"
    )


def _question_card(state: dict[str, Any], q: dict[str, Any]) -> str:
    """一条待答问题：一行两组读数 + 正文 + 选项 + 提交表单。"""
    qid = _text(q.get("qid"))
    sid = _text(q.get("sid"))
    opts = list(q.get("options") or [])
    multi = bool(q.get("multi"))
    ref = _text(state.get("generated_at"))
    ts = _text(q.get("ts"))
    head = _text(q.get("role")) or "（没写角色）"
    opts_html = "".join(
        _option_html(qid, i, o, multi) for i, o in enumerate(opts)
    ) or '<div class="note">这条问题没有给选项 —— 在下面「自定义回答」里写。</div>'
    # 卡片 id 必须带上会话号：qid 是「每段会话内」的编号（两段会话各有 q0001），
    # 只用 qid 会让两张不同的卡片共用一个锚点。
    card_id = f"q-{sid}-{qid}"
    return (
        '<section class="card card-ask" id="' + _e(card_id) + '">'
        '<div class="card-head">'
        f'<span class="caption">会话</span> <span class="mono">{_e(sid)}</span>'
        f'<span class="caption">问题号</span> <span class="mono">{_e(qid)}</span>'
        f'<span class="badge badge-unknown">等回答</span>'
        '<span class="spacer"></span>'
        f'<span class="readings">谁在问 <span class="mono">{_e(head)}</span>'
        f' · 问了多久 <span class="mono">{_e(_age(ts, ref))}</span>'
        f' · 落档时间 <span class="mono">{_e(ts) or "unknown"}</span></span>'
        "</div>"
        f'<div class="question">{_e(q.get("text"))}</div>'
        f'<div class="opts">{opts_html}</div>'
        f'<form class="answer" method="post" action="/answer">'
        f'<input type="hidden" name="qid" value="{_e(qid)}">'
        f'<input type="hidden" name="sid" value="{_e(sid)}">'
        f'<label class="caption" for="custom-{_e(qid)}">自定义回答（单选时覆盖选项，'
        "多选时作为补充；用「custom 优先」的口径读回）</label>"
        f'<textarea id="custom-{_e(qid)}" name="custom" rows="3" '
        'placeholder="想说的原话"></textarea>'
        '<div class="actions">'
        '<button class="btn btn-primary" type="submit">提交回答</button>'
        '<button class="btn btn-ghost" type="submit" name="skip" value="1">跳过此问题</button>'
        '<span class="readings">跳过 = 提交空的 selected（我们的回答口径），'
        "不是「没答」</span>"
        "</div>"
        "</form>"
        "</section>"
    )


def _run_row(state: dict[str, Any], run: dict[str, Any], *, highlight: bool) -> str:
    """一行运行态：两个独立读数 + 三态徽标 + 是否停在等谁。"""
    sid = _text(run.get("sid"))
    role = _text(run.get("role")) or "（没写角色）"
    stop = _text(run.get("stop_reason")) or "unknown"
    cls, word = _STOP_BADGES.get(stop, ("badge-plain", stop))
    waiting = bool(run.get("waiting"))
    if waiting:
        cls, word = "badge-pending", "停在等用户"
    usd = _usd(run.get("usd"))
    unknown_usd = run.get("unknown_usd") or 0
    qids = ", ".join(_text(x) for x in (run.get("waiting_on") or [])) or "（没有）"
    # 两个独立读数（DSH「行里给两个独立事实」）：
    #   读数甲「盘上最后一条事件是什么」= 会话文件尾那一条事件的 kind/形状，读者是文件本身；
    #   读数乙「这一页装载了多少条事件」= 这次渲染时读进来的条数（本趟 / 本会话两条）。
    # 两者读的不是同一个东西，所以它们对不上时正说明「盘在变」或「有坏行没读进来」。
    mine = run.get("events_in_run")
    whole = run.get("events_seen")
    if whole is None:
        whole = next((s.get("events_seen") for s in state.get("sessions") or []
                      if _text(s.get("sid")) == sid), None)
    last_shape = _text(run.get("last_shape")) or "unknown"
    mark = ' <span class="badge badge-plain">最近一趟</span>' if highlight else ""
    return (
        '<div class="row">'
        f'<a class="mono" href="/run/{quote(sid)}">{_e(sid)}</a>'
        f'<span class="mono">{_e(role)}</span>'
        f'<span class="badge {cls}">{_e(word)}</span>'
        + mark
        + '<span class="spacer"></span>'
        '<span class="readings">'
        f'步数 <span class="mono">{_num(run.get("steps"))}</span>'
        f' · 盘上最后一步形状 <span class="mono">{_e(last_shape)}</span>'
        f' · 这一页装载 <span class="mono">{_num(mine)}</span> 条（本趟）'
        f' / <span class="mono">{_num(whole)}</span> 条（本会话）'
        f' · llm 调用 <span class="mono">{_num(run.get("llm_calls"))}</span>'
        f' · 花销 <span class="mono">{_e(usd)}</span> USD'
        + (f'（{_num(unknown_usd)} 次算不出价钱）' if unknown_usd else "")
        + f' · 停在等 <span class="mono">{_e(qids)}</span>'
        "</span>"
        "</div>"
    )


def render_root(state: dict[str, Any]) -> str:
    """`GET /`：全局待回答面板 + 运行态（纯函数，同一份快照两次渲染逐字节相同）。"""
    pending = list(state.get("pending_questions") or [])
    runs = list(state.get("runs") or [])
    orphans = list(state.get("orphans") or [])
    last = state.get("last_run")
    # 台账（第二个独立读数）与坏行：先算好，正文按顺序拼
    ledger = state.get("ledger") or {}
    ledger_html = (
        '<div class="card"><div class="card-head">'
        '<span class="caption">台账（第二个独立读数）</span></div>'
        f'<div class="readings">台账事件 <span class="mono">'
        f'{_num(ledger.get("events"))}</span> 条'
        f' · 台账里的任务行 <span class="mono">{_num(ledger.get("tables"))}</span>'
        f' · 落点 <span class="mono">{_e(ledger.get("path"))}</span>'
        + (f' · {_e(ledger.get("note"))}' if ledger.get("note") else "")
        + "</div></div>"
    )
    problems = list(state.get("problems") or [])
    prob_html = ""
    if problems:
        items = "".join(f'<div class="row"><span class="mono">{_e(p)}</span></div>'
                        for p in problems)
        prob_html = ('<div class="card problem"><div class="card-head">'
                     '<span class="badge badge-fail">没查成</span>'
                     f'<span class="readings">{len(problems)} 条读盘问题'
                     "（不是「没有」，是「没读到」）</span></div>" + items + "</div>")
    if pending:
        ask_html = "".join(_question_card(state, q) for q in pending)
    else:
        ask_html = ('<div class="card"><span class="badge badge-plain">没有待回答</span>'
                    ' <span class="muted">盘上没有尚未回答的提问（合法初态，'
                    "不是「没查成」——同一份读数见下方运行态与 <code>/api/state</code>）。"
                    "</span></div>")
    by_sid: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_sid.setdefault(_text(run.get("sid")), []).append(run)
    run_blocks: list[str] = []
    for sid in sorted(by_sid):
        rows = "".join(
            _run_row(state, r, highlight=(last is not None and r is last))
            for r in by_sid[sid]
        )
        run_blocks.append(
            '<div class="card">'
            f'<div class="card-head"><span class="caption">会话</span>'
            f' <a class="mono" href="/run/{quote(sid)}">{_e(sid)}</a>'
            f'<span class="spacer"></span><span class="readings">'
            f'{len(by_sid[sid])} 趟</span></div>'
            f"{rows}</div>"
        )
    if not run_blocks:
        # 三态：一趟都没有 = 「还没有跑过」，不是「一趟 0 步的运行」，也不是「没查成」。
        run_blocks.append('<div class="card"><span class="badge badge-plain">还没有跑过'
                          "</span> <span class=\"muted\">盘上没有 "
                          "<code>agent_run_start</code> 事件 —— 这个工作区一次运行都"
                          "还没开始过（合法初态）。"
                          + (f"轮次之外另有 {len(orphans)} 条零散事件，见下一栏。"
                             if orphans else "")
                          + "</span></div>")
    orphan_html = ""
    summary = state.get("orphan_summary") or {}
    groups = list(summary.get("groups") or [])
    if groups:
        body_rows = []
        for g in groups:
            sid = _text(g.get("sid"))
            body_rows.append(
                '<div class="row">'
                f'<a class="mono" href="/run/{quote(sid)}">{_e(sid)}</a>'
                '<span class="badge badge-plain">没有开始标记</span>'
                '<span class="spacer"></span>'
                f'<span class="readings">{_num(g.get("count"))} 条'
                f' · 事件种类 <span class="mono">'
                f'{_e("、".join(_text(k) for k in (g.get("kinds") or [])))}</span>'
                f' · 第 <span class="mono">{_num(g.get("first_index"))}</span>'
                f'–<span class="mono">{_num(g.get("last_index"))}</span> 条'
                f' · <span class="mono">{_e(g.get("first_ts"))}</span> → '
                f'<span class="mono">{_e(g.get("last_ts"))}</span>'
                "</span></div>")
        orphan_html = (
            f'<h2 class="sec-title">轮次之外的零散事件 '
            f'<span class="readings">共 {_num(summary.get("count"))} 条</span></h2>'
            '<div class="card"><div class="readings">这些事件不在任何一趟的运行区间里'
            "（它们前面没有 <code>agent_run_start</code>）—— 典型来源是一次不带 "
            "<code>--sid</code> 的 CLI 调用写的台账事件，或者你刚提交、还没被下一趟读到"
            "的回答。它们不代表一次运行，所以不参与「最近一趟」与运行态计数。"
            "</div>" + "".join(body_rows) + "</div>")
    body = (
        f'<h2 class="sec-title">待回答（全局，不按会话过滤）'
        f' <span class="badge {"badge-unknown" if pending else "badge-plain"}">'
        f"{len(pending)}</span></h2>"
        '<div class="stack">' + ask_html + "</div>"
        f'<h2 class="sec-title">运行态 <span class="readings">共 {len(runs)} 趟 / '
        f'{len(by_sid)} 个会话'
        + ("（最近一趟：" + _e(_text(last.get("sid"))) + " / "
           + _e(_text(last.get("role")) or "（没写角色）") + "）"
           if isinstance(last, Mapping) else "（还没有跑过）")
        + "</span></h2>"
        '<div class="stack">' + "".join(run_blocks) + "</div>"
        + orphan_html
        + prob_html
        + ledger_html
        + '<h2 class="sec-title">怎么用</h2>'
        '<div class="card"><div class="readings">'
        "提交后是 PRG（303 回首页），刷新不会重复提交；"
        "回答落进会话记录的 <code>user_answer</code> 事件，"
        "下一趟运行会读到它。读数 JSON 在 <a href=\"/api/state\">/api/state</a>。"
        "</div></div>"
    )
    return _page(state, "agentflow 用户端 · 待回答与运行态", body)


def _event_card(index: int, event: Mapping[str, Any]) -> str:
    """把一条会话事件渲染成一张可回放的卡片（界面纪律，抄自 DSH：渲染已落盘的切片）。"""
    kind = _text(event.get("kind")) or "（没有 kind）"
    ts = _text(event.get("ts"))
    role = _text(event.get("role"))
    cls = "card"
    rows: list[str] = []
    if kind == "agent_run_start":
        rows.append(f'<div class="title">这一趟开始</div>')
        rows.append(f'<div class="clip">{_e(_clip(event.get("task"), 400))}</div>')
        rows.append(
            '<div class="readings">'
            f'角色 <span class="mono">{_e(role)}</span>'
            f' · 由谁发起 <span class="mono">{_e(event.get("summoned_by"))}</span>'
            f' · 深度 <span class="mono">{_num(event.get("depth"))}</span>'
            f' · 台账号 <span class="mono">{_e(event.get("task_id"))}</span>'
            f' · 提示词版本 <span class="mono">{_e(event.get("prompt_version"))}</span>'
            "</div>")
    elif kind == "llm_call":
        rows.append('<div class="title">模型调用摘要</div>')
        rows.append(
            '<div class="readings">'
            f'说明 <span class="mono">{_e(event.get("note"))}</span>'
            f' · 模型 <span class="mono">{_e(event.get("model"))}</span>'
            f' · 协议 <span class="mono">{_e(event.get("protocol"))}</span>'
            f' · 结果 <span class="mono">{"ok" if event.get("ok") else "fail"}</span>'
            f' · tokens in/out <span class="mono">{_num(event.get("tokens_in"))}'
            f"/{_num(event.get('tokens_out'))}</span>"
            f' · 花销 <span class="mono">{_e(_usd(event.get("usd")))}</span> USD'
            f' · 提示词 <span class="mono">{_num(event.get("prompt_chars"))}</span> 字'
            f' · 回文 <span class="mono">{_num(event.get("text_len"))}</span> 字'
            f' · 落档 <span class="mono">{_e(event.get("recorded")) or "ok"}</span>'
            "</div>")
        if event.get("problem"):
            rows.append(f'<div class="clip">problem: '
                        f'<span class="mono">{_e(event.get("problem"))}</span> — '
                        f'{_e(_clip(event.get("detail"), 300))}</div>')
    elif kind == "agent_step":
        shape = _text(event.get("shape")) or "unknown"
        cls = "card"
        rows.append(f'<div class="title">第 {_num(event.get("index"))} 步 · '
                    f'<span class="mono">{_e(shape)}</span></div>')
        rows.append(f'<div class="clip">问（payload）：'
                    f'<span class="mono">{_e(_clip(event.get("payload")))}</span></div>')
        rows.append(f'<div class="clip">答（result）：'
                    f'<span class="mono">{_e(_clip(event.get("result")))}</span></div>')
    elif kind == "user_question":
        cls = "card card-ask"
        rows.append('<div class="title">问用户</div>')
        rows.append(f'<div class="question">{_e(event.get("text"))}</div>')
        rows.append(
            '<div class="readings">'
            f'问题号 <span class="mono">{_e(event.get("qid"))}</span>'
            f' · 谁在问 <span class="mono">{_e(role)}</span>'
            f' · 超时 <span class="mono">{_num(event.get("timeout_sec"))}</span> 秒'
            "</div>")
        for opt in (event.get("options") or []):
            ov = option_view(opt)
            line = f'<span class="label">{_e(ov["label"])}</span>'
            if ov["description"]:
                line += f' <span class="desc">{_e(ov["description"])}</span>'
            rows.append(f'<div class="row">{line}</div>')
    elif kind == "user_answer":
        rows.append('<div class="title">用户回答</div>')
        rows.append(f'<div class="question">{_e(answer_text_of(event))}</div>')
        rows.append(
            '<div class="readings">'
            f'问题号 <span class="mono">{_e(event.get("qid"))}</span>'
            f' · 谁答的 <span class="mono">{_e(event.get("by")) or "user"}</span>'
            f' · 迟到 <span class="mono">{_e(event.get("late"))}</span>'
            f' · selected <span class="mono">'
            f'{_e(_clip(event.get("selected"), 200))}</span>'
            f' · custom <span class="mono">'
            f'{_e(_clip(event.get("custom"), 200))}</span>'
            "</div>")
    elif kind == "agent_run_end":
        stop = _text(event.get("stop_reason")) or "unknown"
        bcls, word = _STOP_BADGES.get(stop, ("badge-plain", stop))
        cls = "card"
        rows.append(f'<div class="title">这一趟结束 '
                    f'<span class="badge {bcls}">{_e(word)}</span></div>')
        rows.append(
            '<div class="readings">'
            f'停止理由 <span class="mono">{_e(stop)}</span>'
            f' · 步数 <span class="mono">{_num(event.get("steps"))}</span>'
            f' · 召唤 <span class="mono">{_num(event.get("summons"))}</span>'
            f' · 消息 <span class="mono">{_num(event.get("messages"))}</span>'
            f' · 交付说明 <span class="mono">{_num(event.get("final_chars"))}</span> 字'
            f' · 耗时 <span class="mono">{_num(event.get("elapsed_sec"))}</span> 秒'
            "</div>")
        rows.append(f'<div class="clip">{_e(_clip(event.get("final"), 600))}</div>')
    else:
        rows.append(f'<div class="title">{_e(kind)}</div>')
        rows.append(f'<div class="clip">{_e(_clip(event, 600))}</div>')
    return (
        f'<section class="{cls}">'
        '<div class="card-head">'
        f'<span class="mono">#{index}</span>'
        f'<span class="caption">{_e(kind)}</span>'
        f'<span class="spacer"></span>'
        f'<span class="readings mono">{_e(ts) or "unknown"}</span>'
        "</div>" + "".join(rows) + "</section>"
    )


def render_run(root: str | Path, sid: str, state: dict[str, Any]) -> tuple[int, str]:
    """`GET /run/<sid>`：一趟的详情（事件卡片 + 交付说明）。返回 `(状态码, HTML)`。"""
    root_p = Path(str(root))
    if not _sid_ok(sid):
        return 404, _page(state, "没有这个会话", _not_found(state, f"会话号不安全：{sid}"))
    path = SS.session_path(root_p, sid)
    if not path.is_file():
        return 404, _page(state, "没有这个会话",
                          _not_found(state, f"会话文件不在盘上：{sid}"))
    events, problems = SS.read_session(root_p, sid=sid)
    cards = "".join(_event_card(i, e) for i, e in enumerate(events, 1))
    if not cards:
        cards = ('<div class="card"><span class="badge badge-plain">这一趟还没有事件'
                 '</span> <span class="muted">文件在盘上，但一条事件都没有。</span></div>')
    rstatus, rtext = _read_report(root_p)
    if rstatus == "ok":
        report = (f'<div class="card"><div class="card-head">'
                  f'<span class="caption">交付说明</span>'
                  f'<span class="spacer"></span><span class="readings mono">'
                  f'{_e("/".join(REPORT_REL))} · {len(rtext)} 字</span></div>'
                  f"<pre>{_e(rtext)}</pre></div>")
    elif rstatus == "missing":
        report = ('<div class="card"><div class="card-head">'
                  '<span class="badge badge-unknown">没查到</span>'
                  '<span class="readings">交付说明不在盘上：'
                  f'<span class="mono">{_e("/".join(REPORT_REL))}</span>'
                  "（合法初态：这一趟还没写）</span></div></div>")
    else:
        report = ('<div class="card problem"><div class="card-head">'
                  '<span class="badge badge-fail">没查成</span>'
                  f'<span class="readings">交付说明读不出来：{_e(rtext)}'
                  "（不是「没有」，是「没读到」）</span></div></div>")
    prob_html = ""
    if problems:
        prob_html = ('<div class="card problem"><div class="card-head">'
                     f'<span class="badge badge-fail">坏行 {len(problems)} 条</span></div>'
                     + "".join(f'<div class="row"><span class="mono">{_e(p)}</span></div>'
                               for p in problems) + "</div>")
    body = (
        '<div class="card"><div class="card-head">'
        f'<span class="caption">会话</span> <span class="mono">{_e(sid)}</span>'
        '<span class="spacer"></span>'
        f'<span class="readings">读盘读数：本会话 <span class="mono">'
        f'{len(events)}</span> 条事件 · 坏行 <span class="mono">{len(problems)}</span> 条'
        f' · 文件 <span class="mono">{_e(str(path))}</span></span>'
        "</div>"
        '<div class="readings">'
        f'盘上最后一条事件 <span class="mono">'
        f'{_e(_text(events[-1].get("kind")) if events else "unknown")}</span>'
        f" · 这一页读到 <span class=\"mono\">{len(events)}</span> 条"
        "（两个独立读数：一个来自文件尾，一个来自这次装载）</div>"
        "</div>"
        + prob_html
        + report
        + f'<h2 class="sec-title">事件回放 <span class="readings">共 {len(events)} 条</span>'
        "</h2>"
        '<div class="stack">' + cards + "</div>"
    )
    return 200, _page(state, f"agentflow · 会话 {sid}", body, crumb=sid)


def _not_found(state: dict[str, Any], why: str) -> str:
    """404 的正文（说清是什么没找到，不是把 404 折成空页）。"""
    return ('<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">404</span>'
            f'<span class="readings">{_e(why)}</span></div>'
            '<div class="readings">回到 <a href="/">首页</a> 看全局待回答与运行态。</div>'
            "</div>")


# ====================================================================== 回答
def _answer_action(root: Path, form: Mapping[str, Sequence[str]]) -> tuple[int, str, str]:
    """处理一次回答提交：返回 `(状态码, 重定向目标, HTML 正文)`。

    三态纪律：qid 不在待答清单里 ⇒ 409（不是 200），并在页面上说清是哪一档：
    已经被谁什么时候答过、还是根本没有这个号。写失败 ⇒ 500 并原样给出错误。
    """
    def one(name: str) -> str:
        """取表单里某个字段的第一个值（没有就给空串 —— 表单字段缺失是常态，不是错误）。"""
        vals = form.get(name) or []
        return _text(vals[0]) if vals else ""

    qid = one("qid").strip()
    sid_in = one("sid").strip()
    selected = [_text(x) for x in (form.get("selected") or [])]
    custom = one("custom")
    skip = one("skip").strip() in {"1", "true", "on", "yes"}
    state = snapshot(root)
    # 查待答问题必须「按 (sid, qid) 这一对」，不能只按 qid：每段会话各自从 q0001 开始
    # 编号，所以同一个工作区里"另一个会话的 q0001"完全可能同时待答。只按 qid 索引时，
    # 给一个「已经答过」的会话再提交（表单带着它自己的 sid）会因为"别处还有个 q0001"
    # 而通过存在性检查，于是往那个会话里写下第二条回答 —— 跨会话串味。
    match = None
    for q in state["pending_questions"]:
        if _text(q.get("qid")) != qid:
            continue
        if sid_in and _text(q.get("sid")) != sid_in:
            continue
        match = q
        break
    if not qid or match is None:
        # 分两档说清楚：答过了（在哪个会话）/ 没有这个号
        answered: dict[str, dict[str, Any]] = {}
        for sid_item in state["sessions"]:
            sid = _text(sid_item.get("sid"))
            if not _sid_ok(sid) or (sid_in and sid != sid_in):
                continue
            events, _bad = SS.read_session(root, sid=sid)
            for e in events:
                if str(e.get("kind") or "") == "user_answer" and _text(e.get("qid")) == qid:
                    answered.setdefault(sid, dict(e))
        if answered:
            who = ", ".join(
                f'{sid}（by {_text(e.get("by")) or "user"} @ {_text(e.get("ts"))}）'
                for sid, e in answered.items())
            html_body = (
                '<div class="card problem"><div class="card-head">'
                '<span class="badge badge-unknown">409 · 已经答过了</span></div>'
                f'<div class="readings">问题号 <span class="mono">{_e(qid)}</span> '
                f"已经不在待答清单里 —— 它已经被回答过：{_e(who)}。"
                f'回答文本：<span class="mono">'
                f'{_e(_clip(answer_text_of(list(answered.values())[0]), 300))}</span>'
                "</div>"
                '<div class="readings">这不是失败，是「迟到了」：'
                "回答只会在下一趟运行被读到。<a href=\"/\">回首页</a></div></div>")
            return 409, "", html_body
        html_body = (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">409 · 没有这个号</span></div>'
            f'<div class="readings">问题号 <span class="mono">{_e(qid) or "（空）"}</span>'
            " 不在任何会话的待答清单里，也不是一条已落盘的问答 —— 什么都没写。"
            '<a href="/">回首页</a> 看看现在在等什么。</div></div>')
        return 409, "", html_body
    q = match
    sid = sid_in or _text(q.get("sid"))
    if not _sid_ok(sid):
        sid = _text(q.get("sid"))
    if skip:
        selected = []
        custom = ""
    # 口径：「选项归 `selected`、自写归 `custom`」（我们的回答口径；字段名与 DSH 一致）。
    # 这里曾经把两者拼成一句 `text` 再以 `answer=text` 落盘，于是"点了哪个选项"
    # 被记成"自己写的一句话"（实测：表单提交 `selected=全保留` ⇒ 事件里
    # `selected: []` / `custom: "全保留"`）—— 那会把"人选了它"与"人写了它"
    # 折成一档，而这正是审阅线反复要分开的两件事。落盘只走 `userio.answer_question`
    # 这一个写入口（事件形状由它定义，本模块不再拼第二份）。
    try:
        problem = U.answer_question(root, qid=qid, selected=[x.strip() for x in selected
                                                             if x.strip()],
                                    custom=custom.strip(), by="web", sid=sid)
    except Exception as exc:  # noqa: BLE001 - 写失败不许折成 200
        return 500, "", (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">500 · 写失败</span></div>'
            f'<div class="readings">落盘时抛异常：'
            f'<span class="mono">{_e(f"{type(exc).__name__}: {exc}")}</span></div></div>')
    if problem:
        return 500, "", (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">500 · 写失败</span></div>'
            f'<div class="readings">会话记录没写成：'
            f'<span class="mono">{_e(problem)}</span>'
            f"（问题号 <span class=\"mono\">{_e(qid)}</span>，"
            f"会话 <span class=\"mono\">{_e(sid)}</span>）</div></div>")
    return 303, "/", ""


# ====================================================================== 路由
class WebHandler(BaseHTTPRequestHandler):
    """只认四条 GET 路由加一条 POST（其余 404 / 405），全部服务端渲染。"""

    server_version = "agentflow-webui"
    protocol_version = "HTTP/1.0"

    #: 由 :func:`serve` 挂上去的三个事实：根目录、口令、路由表。
    root: Path = Path(".")
    token: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 基类签名
        """默认日志会往 stderr 打每一行请求；改成一条短行（测试里也不吵）。"""
        sys.stderr.write("[webui] %s\n" % (fmt % args))

    # ------------------------------------------------------------ 口令
    def _token_ok(self, query: Mapping[str, Sequence[str]]) -> bool:
        """给了口令就要求它：`?token=` 或 `Authorization: Bearer`。"""
        want = self.token or os.environ.get("AGENTFLOW_WEB_TOKEN", "")
        if not want:
            return True
        got = ""
        vals = query.get("token") or []
        if vals:
            got = _text(vals[0])
        if not got:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
        return got == want

    # ------------------------------------------------------------ 输出
    def _send(self, code: int, body: bytes, ctype: str,
              extra: Mapping[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, code: int, text: str,
              extra: Mapping[str, str] | None = None) -> None:
        self._send(code, text.encode("utf-8"), "text/html; charset=utf-8", extra)

    def _json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
        self._send(code, (body + "\n").encode("utf-8"),
                   "application/json; charset=utf-8")
        return

    def _redirect(self, code: int, location: str) -> None:
        self._send(code, b"", "text/plain; charset=utf-8", {"Location": location})

    # ------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802 - 基类签名
        """GET 路由：`/` 首页（全局待回答 + 运行态）、`/run/<sid>` 一趟详情、`/api/state` 读数 JSON。"""
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not self._token_ok(query):
            self._html(401, "<!DOCTYPE html><html><body><h1>401</h1>"
                            "<p>口令不对或没给（<code>?token=</code> 或 "
                            "<code>Authorization: Bearer</code>）。</p></body></html>")
            return
        root = self.root
        if path in ("/", "/index.html"):
            state = snapshot(root)
            self._html(200, render_root(state))
            return
        if path == "/api/state":
            state = snapshot(root)
            self._json(200, state)
            return
        if path.startswith("/run/"):
            sid = unquote(path[len("/run/"):])
            state = snapshot(root)
            code, text = render_run(root, sid, state)
            self._html(code, text)
            return
        state = snapshot(root)
        self._html(404, _page(state, "没有这个页面", _not_found(state, f"没有路由：{path}")))

    # ------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802 - 基类签名
        """POST 路由：目前只有 `/answer`（PRG：303 回首页；qid 不待答 409；写失败 500）。"""
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not self._token_ok(query):
            self._html(401, "<!DOCTYPE html><html><body><h1>401</h1>"
                            "<p>口令不对或没给。</p></body></html>")
            return
        if path != "/answer":
            state = snapshot(self.root)
            self._html(404, _page(state, "没有这个页面",
                                  _not_found(state, f"POST 没有路由：{path}")))
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        form = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
        code, location, body = _answer_action(self.root, form)
        if code == 303:
            self._redirect(303, location)
            return
        state = snapshot(self.root)
        self._html(code, _page(state, f"回答没有落地（{code}）", body))

    def do_HEAD(self) -> None:  # noqa: N802 - 基类签名
        """HEAD 按 GET 处理（`_send` 不写正文），方便探活。"""
        self.do_GET()

    def _reject(self) -> None:
        self._send(405, b"405 method not allowed\n", "text/plain; charset=utf-8",
                   {"Allow": "GET, HEAD, POST"})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _reject  # type: ignore[assignment]


# ====================================================================== 服务
def serve(root: str | Path, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          token: str = "") -> ThreadingHTTPServer:
    """建好服务器并返回（不调 `serve_forever`）。

    测试用 `port=0` 起随机端口：返回后读 `srv.server_address[1]` 拿真实端口，
    在 `finally` 里 `srv.shutdown()` + `srv.server_close()`。
    """
    handler = type("BoundWebHandler", (WebHandler,), {
        "root": Path(str(root)), "token": token,
    })
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def run(argv: Sequence[str] | None = None) -> int:
    """命令行入口：起服务；`--json` 只打印一行 `{"url": ...}` 便于后台任务取 URL。

    为什么叫 `run` 而不是 `main`：`cli.py` 里已经有一个公开的 `main`（整套 CLI 的
    唯一入口），同名两份独立实现是本项目 R003 点名的形态。`cli.py` 那边加
    `agentflow web` 子命令时调本函数（或直接调 :func:`serve`）。
    """
    from .cli import DEFAULT_ROOT

    ap = argparse.ArgumentParser(
        prog="agentflow-webui",
        description="agentflow 用户端：全局待回答面板 + 运行态 + 一趟回放（服务端渲染）")
    ap.add_argument("--root", default="", help="工作区根（不给就用 DEFAULT_ROOT）")
    ap.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址（默认 {DEFAULT_HOST}）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"监听端口（默认 {DEFAULT_PORT}；给 0 让系统挑）")
    ap.add_argument("--token", default="", help="共享口令（也可用 AGENTFLOW_WEB_TOKEN）")
    ap.add_argument("--open", action="store_true", help="起好之后用浏览器打开首页")
    ap.add_argument("--json", action="store_true",
                    help="只打印一行 URL 的 JSON（便于起后台任务后拿到确切 URL）")
    args = ap.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve() if args.root else Path(DEFAULT_ROOT).resolve()
    token = args.token or os.environ.get("AGENTFLOW_WEB_TOKEN", "")
    srv = serve(root, host=args.host, port=args.port, token=token)
    host, port = srv.server_address[0], srv.server_address[1]
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}/"
    # `flush=True` 是「必须」的，不是洁癖：这两行之后进程就进 `serve_forever()` 永不返回，
    # 而 stdout 被管道/文件接走时是「块缓冲」（8 KB 才吐一次）⇒ 起后台任务的人
    # 永远等不到那一行 URL。实测撞到：`python -B -m agentflow.webui --port 0 --json`
    # 在后台跑了很久，输出里一个字都没有（URL 就卡在缓冲区里）。
    # 而 `--json` 这个开关存在的唯一目的就是"让调用方立刻拿到确切 URL"。
    if args.json:
        print(json.dumps({"url": url, "root": str(root)}, ensure_ascii=False), flush=True)
    else:
        print(f"agentflow 用户端：{url}", flush=True)
        print(f"工作区根：{root}", flush=True)
        print("Ctrl-C 停止。", flush=True)
    if args.open:
        try:
            webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001 - 打不开浏览器不该拖垮服务
            sys.stderr.write(f"[webui] 打不开浏览器：{type(exc).__name__}: {exc}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        # Ctrl-C 是停止服务的正常路径（不是错误）：吞掉它，
        # 让 finally 去 shutdown + close，退出码仍是 0。
        pass
    finally:
        srv.shutdown()
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
