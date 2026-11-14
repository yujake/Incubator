# -*- coding: utf-8 -*-
"""用户端 Web 界面的读模型：把工作区盘上的事实读成一份快照（只读，不缓存）。

## 这一层是什么

`snapshot()` 与它的内部件（`_scan` / `_orphan_summary` / `_read_ledger` /
`_read_report` / 取值帮手）只做一件事：给它一个工作区根，它给你一个纯数据快照。
它与渲染、与 HTTP 都无关。

## 三条纪律

1. 「状态一律从盘上派生」：每次调用都重新读会话文件、台账、报告，不缓存、
   不做后台轮询线程。同一份盘上数据读两次得到逐字节相同的快照骨架
   （除了 `generated_at`，它读的是这只钟 —— 取钟的路径见 :func:`_clock`）。
2. 「读到的点数与读不到分开」：读不到的东西是 `None` / `""`，绝不折成 0；
   渲染层再把它们写成 `unknown` / `没查成`。
3. 「回答的文本两种口径都认」（`answer_text_of`）：`custom` 非空取它，否则
   `"、".join(selected)`，否则退回旧的 `answer` 字段。读 `userio` 的返回一律用
   `getattr(obj, "x", None)` / `dict.get`，不假设新字段一定存在。

## 待答问题与选项的读法只有一处实现

在 `userio`：本模块的 `answer_text_of` / `option_view` 只是转发，`_scan` 不再自己扫
`user_question` / `user_answer`（那一栏由 `snapshot()` 从
`userio.workspace_pending_view` 取一次、按会话号切给它）。公开名与签名未动。
"""

from __future__ import annotations

import html as _html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import sessions as SS

__all__ = ["snapshot", "answer_text_of", "option_view", "project_reading",
           "current_reading", "TOP_RUN_TASK_ID", "top_run", "top_run_closed",
           "mark_stale_loops"]

#: 页面里 JSON 摘要的截断长度（读数页不该被一条超长 payload 撑爆）。
CLIP = 400
#: 交付说明的落点（工作区相对路径，`docs`/`agent_prompts` 的口径）。
REPORT_REL = ("out", "review", "REPORT.md")
#: 会话号允许的字符集（它会被拼进文件名，必须挡目录穿越）。
_SID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")

#: 项目卡与项目标记的文件名。两件都只由 `projects.create_project` /
#: `adopt_project` 写，读侧不许另造第三种「这是不是一个项目」的判据。
PROJECT_CARD_NAME = "project.json"
PROJECT_MARKER_NAME = ".agentflow-workspace"

#: 事件里记「这是第几轮」的键名。三档都认：不同写入点历史上用过不同的名字。
ROUND_KEYS: tuple[str, ...] = ("round", "rounds", "round_index")


def round_of(root: str | Path, sid: str = "",
             events: Sequence[Mapping[str, Any]] | None = None) -> int:
    """这一段会话现在跑到第几轮（读事件里的轮号；读不到就是 0）。

    为什么是 0 而不是 1：网页/命令行打开的那一刻可能什么都还没跑过，写 1 会让
    「还没开始」与「正在第 1 轮」长得一样。

    为什么住在这里、而不各写一份：`agentflow start --watch` 打印的「当前轮」与网页
    `/api/state` 的 `current.round` 必须是同一个数。两份实现漂移的形态是「命令行说第 3
    轮、网页说第 2 轮」，而没有任何东西会报错 —— 所以口径只有这一处，两个读者都调它
    （命令行那一侧是 `cli._current_round`，它是本函数的薄转发）。

    为什么落在这一层而不是 `sessions.py`：`sessions` 是写入侧（它管落地与格式），
    这一格是读数，与 `current_reading` 是同一件事的一半。本仓对 >800 行的源文件
    有硬基线（`tests/test_repo_survey_does_not_get_worse.py`），把它加进 `sessions.py`
    会把那一格抬上去；而这里已经过线，加它不新增过线文件。

    `events` 给了就不读盘（调用方已经有一份解析好的事件时用它，避免重复读同一段会话）。
    """
    if events is None:
        if not sid:
            return 0
        try:
            events, _problems = SS.read_session(root, sid=sid)
        except Exception:  # noqa: BLE001 - 读不到轮号是"没读到"，不是 0 轮
            return 0
    best = 0
    for event in events:
        for key in ROUND_KEYS:
            value = event.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > best:
                best = value
    return best


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
    # 字典这一档直接按名字读：`_dict(obj)` 会先整份拷贝一份，而读模型的每一格都过这里。
    src = obj if isinstance(obj, Mapping) else _dict(obj)
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
    钉成常量再比字节：否则两次请求跨一秒就会红（全量里真红过一次）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _clock() -> str:
    """取一次时间：优先用包命名空间里那个 `_now_iso`。

    为什么要绕这一层（拆包带来的唯一一处取钟路径变化，语义没变）：上面那条判据
    是用 `monkeypatch.setattr(agentflow.webui, "_now_iso", ...)` 把钟钉住的，
    而补丁落在包的命名空间上。包化之后 `snapshot()` 住在 `webui/state.py`，
    若它直接叫本模块的 `_now_iso`，那次补丁就落不到调用点上 —— 判据会静默退化成
    "两次请求碰巧落在同一秒才绿"，而且它自己不会响。
    所以取钟统一走这里：包命名空间里能拿到就叫它（打到补丁时拿到的就是它），
    拿不到才回退到本模块的实现。这个回退不是第二条实现，是同一个函数。
    """
    pkg = sys.modules.get(__package__)
    fn = getattr(pkg, "_now_iso", None) if pkg is not None else None
    if callable(fn):
        return fn()
    return _now_iso()


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
    """从一条回答事件里读出「用户到底说了什么」（裁定 L1：转发到 `userio`）。

    这一层曾经有一份自己的实现（`custom` 非空取它，否则 `"、".join(selected)`，
    否则退回旧的 `answer` 字段）。裁定 L1 把它收敛到 `userio.reply_text` —— 同一件事
    两份实现的漂移形态是"CLI 说这一句、网页说那一句"，而没有任何东西会报错。

    保留这个名字的理由是契约：它在 `webui.__all__` 里、被 `writes.py` 与判据
    读、也由 `temp/_verify_w0.py` 对着公开面对账 —— 签名与返回形状逐字不变，
    只是实现从"第二份"变成"转发"。
    """
    from .. import userio as U

    return U.reply_text(event)


def option_view(raw: Any) -> dict[str, Any]:
    """把一个选项读成 `{label, description, multi}`（裁定 L1：转发到 `userio`）。

    形状的真身是 `userio.option_view`：裸字符串（旧会话事件、`llmseam` 的旧 schema）
    与新形状（`Option` / 字典）都认。本函数现在只是一层转发 —— 判据
    `tests/test_webui_readers.py` 里那条"两处 `option_view` 逐值相等"从此恒真，
    因为两处本来就是同一个函数（这正是 L1 要的结果，不是把判据改宽）。

    它也是前端 `OptionRow` 那个类型的真身（`ui/src/types.ts` 由
    `agentflow/web/emit_types.py` 生成）—— 契约判据 C 拿它的键集合与这里对账。
    """
    from .. import userio as U

    return U.option_view(raw)


def _sid_ok(sid: str) -> bool:
    """会话号是不是一个安全的文件名主干（挡 `../` 这类穿越）。"""
    return bool(sid) and all(ch in _SID_OK for ch in sid) and ".." not in sid


# ====================================================================== 未收尾的循环
#: 顶趟的绝对编号：框架给第一趟（主控那一趟）分配的台账号是 `t-000001`
#: （`conductor.open_top_level_run` 从这台台账的第一个号起用）。没有它时退回
#: "这一场会话里最早开始的那一趟"（老会话 / 夹具里可能没有主控的开场事件）。
TOP_RUN_TASK_ID = "t-000001"


def top_run(runs: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """这一场会话的顶趟（`t-000001`；没有就取最早开始的那一趟）。一趟都没有 ⇒ `None`。"""
    for run in runs:
        if str(run.get("task_id") or "") == TOP_RUN_TASK_ID:
            return run
    if not runs:
        return None
    return min(runs, key=lambda r: int(r.get("start_index") or 0))


def top_run_closed(runs: Sequence[Mapping[str, Any]]) -> bool:
    """顶趟是不是已经收到自己的 `agent_run_end`（"这一趟的宿主循环已经走完"）。

    三态口径：没有顶趟 / 顶趟没收到 end ⇒ `False`。`False` 在这里只有一种意思 ——
    "判不出它已收尾"，不是"它还在跑"：`stale_loop` 那一格拿它当「关闭条件」用，
    所以读不到时只会让行留在"未收尾"那一档（保守方向 = 不替它宣布死亡）。
    """
    top = top_run(runs)
    return top is not None and top.get("end_index") is not None


def mark_stale_loops(runs: Sequence[dict[str, Any]]) -> Sequence[dict[str, Any]]:
    """给每一趟补一格 `stale_loop`：「有 start 没 end、而顶趟已经收尾」。

    ## 这一格回答的是什么

    `end_index is None`（或 `end_ts` 为空）只说得清"这一段记录没收到 end"，
    说不清"它还在跑"。82 的定格数据就是这条缺陷的现场：两条 D 的
    `agent_run_start`（20:38:22 / 20:38:23）一直没有对应的 `agent_run_end`，
    而顶趟 `t-000001` 在 20:59:28 以 `stop_file` 收尾、宿主进程也已退出 ——
    它们是被父叫停打断的循环记录，不是活着的循环。判据：

    | 形态 | `stale_loop` |
    |---|---|
    | 有 start 有 end（已收尾） | `False` |
    | 有 start 没 end，且顶趟已收尾（宿主走了 / 被叫停） | `True` |
    | 有 start 没 end，但顶趟还在跑（那时它真的还在飞） | `False` |

    ## 为什么判据挂在"顶趟"上

    子循环跑在父进程里（线程），它们没有各自的 pid 登记（`stopctl.running_loops`
    的注释写着同一件事）——所以"宿主还在不在"只能从顶趟读：顶趟收了 end ⇒ 那一趟
    宿主循环已经走完，它名下还没收尾的子循环只可能是"被打断后剩下的记录"。
    纪律与 run-index 那套一致：不许把"没收到 end"说成"还在跑"。

    ## 为什么在这一层（读侧）加

    盘上格式一个字节都不动（`sessions.py` 的 `runs_in_session` 仍是纯会话读数）；
    这一格是读模型给页面用的派生读数，两个读口（本模块的 `_scan` 与
    `readers.run_view`）都调这一个函数，于是它们不会各说一套。
    """
    closed = top_run_closed(runs)
    for run in runs:
        run["stale_loop"] = bool(closed and run.get("end_index") is None)
    return runs


# ====================================================================== 快照
def _scan(session_root: Path, sid: str, events: Sequence[Mapping[str, Any]],
          problems: Sequence[str],
          pending: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """把一个会话的事件扫成「待答问题 + 每一趟的运行态」（纯函数，不碰盘）。

    `pending` 由调用方给（裁定 L1：待答与选项的口径只有一个来源 —— `userio` 的
    `workspace_pending_view`）。这一版之前，"哪些问题还没答"是在本函数里〔第二次〕
    扫一遍 `user_question` / `user_answer` 事件算出来的，而 `userio` 里有同一件事的
    另一份实现：两份漂移的形态是"CLI 说还有三条待答、网页说没有"，且没有任何东西
    会报错。现在本函数只负责运行态（趟次与零散事件），待答那一栏是搬进来的。

    `session_root` 保留在签名里（调用方与它对齐；本函数自己不用它）。
    """
    del session_root
    events = list(events)
    pending = [dict(q) for q in pending]
    # ---- 每一趟 = 一条 `agent_run_start` 到它自己那条 `agent_run_end`（或文件尾）。
    #
    # 配对键是 `task_id`，不是"当前那趟"（`draft/158` §三）：会话文件是一个工作区一天
    # 一份、所有子代理共写；若每一条 start 覆盖 `cur`、每一条 end 关掉"当前那趟"，
    # 两端都不看任务号 ⇒ 81 那趟 63/71 行的终态为空或挂的是别人的 end。这一份与
    # `sessions.runs_in_session` 是两处同形实现（只改一处等于再造一次"两个读口各说一套"），
    # 所以三档归属与"收工行自报步数"必须逐句同形。
    #
    # 没有开始标记的事件「不许」被折成一趟：那是「轮次之外的零散事件」（例如人刚
    # 提交的一条 `user_answer`，或者一次不带 `--sid` 的 CLI 调用写的 `task_end`）。
    # 把它们折成"一趟 0 步的运行"会让"最近一趟"被一个空壳顶掉，而真机里那正好发生
    # 在人按下「提交」的那一刻（父的复现：`agent_run_end` 之后紧跟的 `user_answer`
    # 成了新一轮的开始）。所以零散事件单独收成一栏，并如实写"没有开始标记"。
    runs: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    #: 还没闭合的趟：`(task_id, run)`，按开始顺序（`task_id` 只留在这里，不进行）。
    open_runs: list[tuple[str, dict[str, Any]]] = []
    last_kind = ""
    last_seq = -1

    def _owner_of(tid: str, role: str) -> tuple[str, dict[str, Any]] | None:
        """这条事件该记到哪一趟上（找不到 ⇒ `None`，不猜）。三档同 `runs_in_session`。"""
        if tid:
            for item in reversed(open_runs):
                if item[0] == tid:
                    return item
            return None
        for item in reversed(open_runs):
            if _text(item[1].get("role")) == role:
                return item
        if len(open_runs) == 1:
            return open_runs[0]
        return None

    for i, e in enumerate(events):
        kind = str(e.get("kind") or "")
        if kind:
            last_kind = kind
            last_seq = max(last_seq, int(e.get("seq") or i))
        if kind == "agent_run_start":
            start_tid = _text(e.get("task_id"))
            cur = {
                "sid": sid, "role": _text(e.get("role")), "task": _text(e.get("task")),
                # 绝对编号只从这一趟自己的开场事件来（读不到 ⇒ ""，不造假编号）。
                # `runs_in_session` 里同一句。
                "task_id": start_tid,
                "task_id_source": "event" if start_tid else "missing",
                "start_index": i, "start_ts": _text(e.get("ts")),
                "steps": 0, "llm_calls": 0, "usd": None, "unknown_usd": 0,
                # 收工那一刻才有的两格（没有收工行 ⇒ 保持 None，不是 0）
                "spend_usd": None, "spend_unknown_usd_calls": None,
                # 归属计数从它自己的开始那一行起算（`events_span` 也把它算进跨度）
                "events_owned": 1,
                "stop_reason": "", "final_chars": None, "summons": None,
                "messages": None, "elapsed_sec": None, "last_shape": "",
                "end_index": None, "end_ts": "",
            }
            runs.append(cur)
            open_runs.append((start_tid, cur))
            continue
        hit = _owner_of(_text(e.get("task_id")), _text(e.get("role")))
        if hit is None:
            # 轮次之外：只记账（条数、起止时间、有哪些 kind），不当成一趟运行。
            orphans.append({"sid": sid, "index": i, "kind": kind or "unknown",
                            "ts": _text(e.get("ts")), "role": _text(e.get("role"))})
            continue
        cur = hit[1]
        # 这条事件归到这一趟了 ⇒ 归属计数 +1（与 `events_span` 是两个问题：
        # 一个是"谁写的"，一个是"占了几行下标"）。`runs_in_session` 里同一句。
        cur["events_owned"] += 1
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
            # 这一趟自己写的账优先（`runs_in_session` 里那一段逐句同形）：多代理交错时
            # 按事件位置数步会数到别家头上，而收工行是这一趟自己写的。缺格 ⇒ 保留逐条数。
            steps = e.get("steps")
            if isinstance(steps, int) and not isinstance(steps, bool) and steps >= 0:
                cur["steps"] = steps
            spend = e.get("spend")
            if isinstance(spend, Mapping):
                calls = spend.get("calls")
                if isinstance(calls, int) and not isinstance(calls, bool) and calls >= 0:
                    cur["llm_calls"] = calls
                # 收工行自报的花销 —— 单独成格，「不顶替」 `usd`（事件求和）。
                # 逐格回退（`runs_in_session` 里那一段逐句同形）：缺哪一格就那一格留 None。
                reported_usd = spend.get("usd")
                if (isinstance(reported_usd, (int, float))
                        and not isinstance(reported_usd, bool)):
                    cur["spend_usd"] = float(reported_usd)
                unknown_reported = spend.get("unknown_usd_calls")
                if (isinstance(unknown_reported, int)
                        and not isinstance(unknown_reported, bool) and unknown_reported >= 0):
                    cur["spend_unknown_usd_calls"] = unknown_reported
            open_runs.remove(hit)
    # ---- 未收尾的循环（82 的定格数据）：给每一趟补 `stale_loop`。
    # 判据与逐格读数见 :func:`mark_stale_loops`：有 start 没 end、且顶趟已收尾 ⇒ True。
    mark_stale_loops(runs)
    # ---- 把待答问题挂到「正在等它」的那一趟上
    for run in runs:
        hi = run["end_index"] if run["end_index"] is not None else len(events)
        # 只挂"在事件里有下标"的那几条：`userio.question_view` 的 `index` 读不到时是
        # `None`（那是"这一条不知道落在第几行"，不是一个可以拿来比大小的 0）。
        mine = [str(q.get("qid") or "") for q in pending
                if isinstance(q.get("index"), int) and run["start_index"] < q["index"] <= hi]
        run["waiting_on"] = mine
        # 停止理由是空的、但确实停在一个没答的问题上 ⇒ 那一档是「停在等用户」
        if not run["stop_reason"] and mine:
            run["stop_reason"] = "waiting_for_user"
        run["waiting"] = bool(mine) and run["stop_reason"] == "waiting_for_user"
        run["events_span"] = max(0, hi - run["start_index"])
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
        # 这一段会话里「事件流有、而没有任何一趟的自报账认得」的钱。
        # 算在 `sessions.unattributed_usd_of` 一处（两处各写一遍就是同一个数两份实现）。
        "unattributed_usd": SS.unattributed_usd_of(events, runs),
    }


def project_reading(root: str | Path) -> dict[str, Any]:
    """这一份快照是哪个项目的读数（名字 / 路径 / 是不是项目 / 判据出处）。

    ## 为什么要这一格（2026-11-14 的落点事故）

    命令行 `start --project P` 改后落在 `projects/P`，而网页端只印过
    `workspace`（= 服务起来时的那个根）。于是"我在看哪个项目"这件事在页面上没有名字：
    同时开两个项目的两页，两页看起来一模一样。这一格把项目名与路径摆出来，并且
    不许自己算第二份 —— 名字的唯一来源是项目文件夹自己的名字（`projects.resolve`
    就是拿它当 `ProjectRef.name` 的），`project.json` / `.agentflow-workspace` 里
    记的那份只用来交叉核对（`source` 说这一格是从哪读来的）。

    ## 三态

    - `tri="computed"`：读到了，`is_project` 说它是不是一个项目文件夹；
    - `tri="not_applicable"`：这个根不是项目（裸工作区 `kind="workspace"`、空目录
      `kind="empty"`、不存在 `kind="absent"`）—— 那是合法初态，不是"没查成"；
    - `tri="unreadable"`：判据本身读不出来（分类器抛异常，或项目卡是坏 JSON）。

    `why` 逐字来自 `projects.classify()`：状态词与理由只有那一处实现，网页这一层
    不许再判一次"这算不算一个项目"。
    """
    root_p = Path(str(root))
    out: dict[str, Any] = {
        "tri": "unreadable", "reason": "",
        # 名字的唯一来源是文件夹名（`projects.resolve` 的口径）；读不到目录名时留空。
        "name": root_p.name, "path": str(root_p),
        "state": "unknown", "why": "", "is_project": False,
        "card": "", "marker": "", "source": "none",
    }
    try:
        from .. import projects as P

        state, why = P.classify(root_p)
    except Exception as exc:  # noqa: BLE001 - 分类器读不出来 = 没查成，不是"没有项目"
        out["reason"] = f"项目判据没查成：{type(exc).__name__}: {exc}"
        return out
    out["state"], out["why"] = state, why
    card = root_p / PROJECT_CARD_NAME
    marker = root_p / PROJECT_MARKER_NAME
    out["card"] = str(card) if card.is_file() else ""
    out["marker"] = str(marker) if marker.is_file() else ""
    out["is_project"] = bool(out["card"] or out["marker"])
    # 名字的来源：卡 > 标记 > 文件夹名。三档都只读、都不改盘；`source` 如实说是哪一档，
    # 于是"页面上那个名字是不是卡里记的"不需要猜。
    from_card = ""
    if out["card"]:
        try:
            data = json.loads(card.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out["tri"] = "unreadable"
            out["reason"] = f"项目卡读不出来（{type(exc).__name__}: {exc}）"
            out["source"] = "card"
            return out
        if isinstance(data, Mapping):
            from_card = _text(data.get("name"))
            out["source"] = "card"
    if not from_card and out["marker"]:
        try:
            text = marker.read_text(encoding="utf-8")
        except OSError as exc:
            out["tri"] = "unreadable"
            out["reason"] = f"项目标记读不出来（{type(exc).__name__}: {exc}）"
            out["source"] = "marker"
            return out
        for line in text.splitlines():
            if line.startswith("name="):
                from_card = line[len("name="):].strip()
                out["source"] = "marker"
                break
    if from_card:
        out["name"] = from_card
    elif out["is_project"]:
        out["source"] = "dirname"
    out["tri"] = "computed" if out["is_project"] else "not_applicable"
    if not out["is_project"]:
        # 「还没初始化」与「这不是一个项目」是两件事：前者是 `--watch` 先起网页、
        # 真机还没开跑那一刻的正常形态（文件夹刚被 mkdir 出来），后者是有人把网页
        # 指到了一个别的目录。把它们折成同一句话，读的人会以为落点选错了。
        if state in ("absent", "empty"):
            out["reason"] = (f"这个项目还没初始化（{state}：{why}）—— 跑起来之后会落 "
                             "project.json 与 data/")
        else:
            out["reason"] = (f"这不是一个项目文件夹（{state}：{why}）"
                             "—— 这一份读数是一个裸工作区")
    return out


#: `current.source` 的三个取值（给前端与判据同一份词表）。
CURRENT_SOURCES: tuple[str, ...] = ("cli", "newest_session", "none")


def current_reading(root: str | Path, sid: str = "", *,
                    sessions: Sequence[Mapping[str, Any]] = (),
                    events_of: Mapping[str, Sequence[Mapping[str, Any]]] | None = None
                    ) -> dict[str, Any]:
    """「当前这一段会话 + 当前轮」—— 与 `agentflow start --watch` 印出来的那两个数同源。

    ## 为什么不能各自算

    `--watch` 的 sid 是它自己定的（`--sid` 或当天），页面上若按"最近一段会话"再挑一次，
    两个数就可能在多段会话并存时指向不同的段 —— 而两处都写着「当前会话」。所以
    `serve(sid=…)` 把这个号交给服务，快照照抄（`source="cli"`）；只有没人交代时
    （直接 `agentflow web`）才退回"最近一段"，并把这件事写进 `source`。

    `round` 只调本模块的 `round_of()`（命令行那个 `_current_round` 是它的薄转发），
    `events` 沿调用方已经解析好的那份传进去（`snapshot()` 已经读过一遍），
    于是这一格不额外读盘，也不会与命令行分叉。
    """
    root_p = Path(str(root))
    given = str(sid or "")
    chosen = given
    source = "cli" if given else "none"
    if not chosen:
        # 没有交代 ⇒ 最近的这一段（按 `last_ts`；并列时留先出现的那个，与
        # `sessions.list_sessions` 的顺序一致）。选了什么不藏：`source` 说清楚。
        best: Mapping[str, Any] | None = None
        for row in sessions:
            if not _text(row.get("sid")):
                continue
            if best is None or _text(row.get("last_ts")) >= _text(best.get("last_ts")):
                best = row
        if best is not None:
            chosen = _text(best.get("sid"))
            source = "newest_session"
    found = bool(chosen) and (
        any(_text(row.get("sid")) == chosen for row in sessions)
        or (events_of is not None and chosen in events_of))
    events = None
    if events_of is not None and chosen in events_of:
        events = list(events_of.get(chosen) or ())
    round_no = round_of(root_p, chosen, events=events) if chosen else 0
    return {
        "sid": chosen,
        "round": int(round_no),
        "source": source,
        # `found=False` 且 `sid` 非空是合法形态：`--watch` 先起网页、再开跑，
        # 那一刻这一段会话文件还不存在。它不是"没查成"。
        "found": found,
    }


def snapshot(root: str | Path, *, sid: str = "") -> dict[str, Any]:
    """把工作区盘上的事实读成一份快照（纯函数：只读盘，不缓存、不写任何东西）。

    返回：`{"root", "generated_at", "project", "current", "sessions",
    "pending_questions", "runs", "orphans", "orphan_summary", "last_run", "ledger",
    "problems"}`。

    `project` / `current` 是 2026-11-14 补的两格（见 :func:`project_reading` /
    :func:`current_reading`）：命令行 `start --watch --project P` 印出来的
    「项目 / 工作区 / sid / 当前轮」四格里，前两格由 `root` 与 `project` 回答、
    后两格由 `current` 回答。`sid` 由 `serve(sid=…)` 交下来（`--watch` 定的那一个），
    不给就退回"最近一段会话"并在 `current.source` 里说明。

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
    # ---- 会话文件只读一遍。
    #
    # 这一份快照若把同一批会话文件读 4 遍（`list_sessions` 一遍、待答那一路
    # （`session_ids_with_questions` → `list_sessions` 一遍 + 自己 `read_session` 一遍，
    # 有未答问题时 `pending_view` 再一遍）、下面主循环再一遍），真机 81 单个会话文件
    # 26 MB / 约 436 ms ⇒ 一次 `/api/state` 光"读会话"就要 1.6–2.0 s。
    # 现在 `list_sessions(read_cache=…)` 把那一遍读出来的 `{sid: (事件, 坏行)}` 交出来，
    # 待答与主循环都用它。这是"同一份盘上事实只解析一遍"，不是缓存：
    # 每个请求仍然现读现算，读到的东西与单读几遍逐字节相同。
    read_cache: dict[str, tuple[list[dict], list[str]]] = {}
    cache_ok = True
    sessions_problem = ""
    try:
        listed = SS.list_sessions(root_p, read_cache=read_cache)
    except Exception as exc:  # noqa: BLE001 - 读不到会话目录 = 没查成，不是「没有会话」
        listed = []
        # 没读成就不能拿"空缓存"冒充"这个工作区没有会话"：把口子关掉，让下游照旧自己读。
        cache_ok = False
        sessions_problem = f"会话目录没查成：{type(exc).__name__}: {exc}"
    # ---- 待答问题：唯一来源是 `userio`（裁定 L1）。
    #
    # 一次取全工作区（`workspace_pending_view`），再按会话号切给下面的 `_scan` ——
    # 为什么不逐会话各取一次：那会每个会话多读一遍盘；为什么不自己扫事件：
    # 那正是 L1 要删掉的那份第二实现（"哪些问题还没答"的口径必须只有一处）。
    # 这一层读不出来时如实记 `problems`（"没查成"不是"没有待答"），并让待答那一栏
    # 保持空 —— 页面据 `problems` 显示"没查成"的横幅。
    # 交出去的是 `{sid: 事件}` 那份视图（`read_cache` 里存的是 `(事件, 坏行)` 两格）。
    events_of: dict[str, list[dict]] = {sid: got_events
                                        for sid, (got_events, _bad) in read_cache.items()}
    try:
        from .. import userio as _U

        pending_all: list[dict[str, Any]] = _U.workspace_pending_view(
            root_p, cache=events_of if cache_ok else None)
    except Exception as exc:  # noqa: BLE001 - 读数层：读不到就如实说没查成
        pending_all = []
        problems.append(f"待答清单没查成：{type(exc).__name__}: {exc}")
    # `problems` 的次序是读数的一部分："待答"那条在前、会话目录那条在后，
    # 这里照旧（两处同时失败时正文才不会换序），所以上面那一条先记、这里再补。
    if sessions_problem:
        problems.append(sessions_problem)
    by_sid: dict[str, list[dict[str, Any]]] = {}
    for one in pending_all:
        by_sid.setdefault(_text(one.get("sid")), []).append(one)
    for item in listed:
        sid = _text(item.get("sid"))
        if not _sid_ok(sid):
            problems.append(f"会话号不安全，跳过：{sid!r}")
            continue
        events, bad = read_cache.get(sid, ([], []))
        got = _scan(root_p, sid, events, bad, by_sid.get(sid, ()))
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
            # 先占位：这一格在下面从全局那份待答清单里数出来（见循环之后那段）。
            "pending": 0,
            "runs": len(got["runs"]),
            "orphans": len(got["orphans"]),
            # 没人认领的那笔钱（见 `_scan` 返回处那一格）
            "unattributed_usd": got["unattributed_usd"],
        })
        pending.extend(got["pending"])
        runs.extend(got["runs"])
        orphans.extend(got["orphans"])
        problems.extend(f"{sid}: {p}" for p in bad)
    # ---- 会话概览那一格的「待答」：与面板那份清单（`pending_questions`）数同一份列表。
    #
    # 这两处若"各算一遍"—— 每一段会话把自己那一片的
    # `len()` 写进 `SessionRow.pending`，全局清单再把各片拼起来。两处恰好相等，
    # 所以没有任何判据会红；而"概览说 3 条、面板列出 2 条"这种漂移一旦出现，
    # 它也只会在用户眼里出现，不在测试里出现。现在只有一个来源：
    # 会话行那一格是从这份列表数出来的（不是从它自己那片算的）。
    per_sid: dict[str, int] = {}
    for q in pending:
        key = _text(q.get("sid"))
        per_sid[key] = per_sid.get(key, 0) + 1
    for row in sessions:
        row["pending"] = per_sid.get(_text(row.get("sid")), 0)
    pending.sort(key=lambda q: (q["sid"], q["index"]))
    runs.sort(key=lambda r: (r["sid"], r["start_index"]))
    orphans.sort(key=lambda o: (o["sid"], o["index"]))
    # 「最近一趟」只认「真的开始了的运行」（有 `agent_run_start`）。整个工作区一趟都
    # 没有 ⇒ `None`（页面写「还没有跑过」），绝不拿一条空壳顶上去。
    # `runs` 刚按 `(sid, start_index)` 升序排过 ⇒ 末项就是原来那趟逐项比较选出来的
    # 最大值（原来的循环用严格大于，并列时留先出现的那个；排序稳定，末项仍是它）。
    last_run: dict[str, Any] | None = runs[-1] if runs else None
    orphan_summary = _orphan_summary(orphans)
    ledger = _read_ledger(root_p, problems)
    # 「这是哪个项目」与「当前是哪一段会话、第几轮」两格（2026-11-14 的对齐）：
    # 它们与命令行 `start --watch --project P` 印出来的四格读数逐字同源 ——
    # 项目名来自项目文件夹本身（`projects.resolve` 的口径），sid/轮号来自
    # `serve(sid=…)` 交下来的号 + `webui.state.round_of()`（命令行印的那两个数）。
    project = project_reading(root_p)
    current = current_reading(root_p, sid, sessions=listed, events_of=events_of)
    return {
        "root": str(root_p),
        "generated_at": _clock(),
        "project": project,
        "current": current,
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
    """读台账（`Store`）做第二个独立读数：读不到就报「没查成」，不折成 0。

    ## 这一格不再把 `events.jsonl` 的总行数叫作「台账事件 N 条」

    `Store._append_events` 每提交一次事务写 `rows + 1` 行：N 行事件，末尾再补一行
    `op="commit"` 的提交标记（重放靠它分批，见那边的 docstring）。所以"文件行数"
    与"写了多少笔"是两个数（一次写入占两行），而这一格此前读的是前者、名字叫后者，
    并且与旁边那格「会话 N 段」并排 —— 一个翻倍地回答"写了多少笔"的数，页面上
    没有任何字提示这件事。

    现在拆成三格（`upserts` / `commit_markers` / `events_note`）：

    - `upserts`：写入笔数（= 非 commit 标记的行数）；
    - `commit_markers`：提交标记的行数；
    - `events`：保留这个名字（`types.ts` 与既有读者都认它），口径
      与 `upserts` 逐字相同 —— 它不再等于文件总行数。

    守恒：`upserts + commit_markers == events.jsonl 的总行数`（一行都不丢，也不重复
    计数）。读不成 JSON 的坏行（`op="corrupt"` 的占位行）按行计入 `upserts` ——
    合计仍是总行数，坏行条数写进 `events_note`，不静默吞。
    """
    out: dict[str, Any] = {"path": str(root / "data" / "events.jsonl"),
                           "events": None, "upserts": None, "commit_markers": None,
                           "tables": None, "note": "", "tables_note": "", "events_note": ""}
    try:
        from ..store import Store

        st = Store(root)
        if not st.events_path.exists():
            out["note"] = "台账还没有（合法初态）"
            # 三态：文件不在 ⇒ 笔数与标记都是 unknown（不是 0 笔）。
            out["events_note"] = ("台账文件不在盘上 ⇒ 写入笔数与 commit 标记都记 unknown"
                                  "（不是「一笔都没写」）")
            return out
        rows = st.read_events()
        commits = corrupt = 0
        for one in rows:
            op = str(one.get("op") or "")
            if op == "commit":
                commits += 1
            elif op == "corrupt":
                corrupt += 1
        upserts = len(rows) - commits
        out["upserts"] = upserts
        out["commit_markers"] = commits
        # 同一个口径的另一个名字（见 docstring：`events` 不再等于文件总行数）。
        out["events"] = upserts
        out["tables"] = len(st.rows("tasks")) if hasattr(st, "rows") else None
        note = (f"台账写入 {upserts} 笔（其中 commit 标记 {commits} 行）：每提交一次事务占两行"
                "（一行事件 + 一行 commit 标记），所以两数相加 = events.jsonl 的总行数")
        if corrupt:
            note += f"；另有 {corrupt} 行读不成 JSON（坏行，按行计入「写入」这一格）"
        out["events_note"] = note
        # `R4` ⑨：只写口径，不改语义 —— 这个数就是 `tasks` 台账的全量行数
        # （不筛选、不减一）。它含顶趟行（`role=M` / `action=run` / `called_by=user`），
        # 所以它比"子任务条数"大；读数旁边不写这句，读的人会把它当成子任务数。
        out["tables_note"] = "含顶趟行；为 tasks 全量行数，非子任务条数"
    except Exception as exc:  # noqa: BLE001 - 读数而已，读不到就如实说没查成
        out["note"] = f"台账没查成：{type(exc).__name__}: {exc}"
        out["events_note"] = "台账没查成 ⇒ 写入笔数与 commit 标记都记 unknown（不是 0）"
        problems.append(out["note"])
    return out


def _read_report(root: Path) -> tuple[str, str]:
    """读交付说明 `out/review/REPORT.md`：返回 `(状态, 文本)`。

    状态是 `ok` / `missing` / `unknown` 三态：`missing` = 不在盘上（合法初态），
    `unknown` = 在盘上但读不出来（那是「没查成」，不许显示成空报告）。
    前端 `ReportReading`（生成物 `ui/src/types.ts`）就是这两栏的字典口径。
    """
    path = root.joinpath(*REPORT_REL)
    try:
        if not path.is_file():
            return "missing", ""
        return "ok", path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "unknown", f"{type(exc).__name__}: {exc}"


# ====================================================================== 类型声明
# 前端唯一类型来源（`ui/src/types.ts`）由 `agentflow/web/emit_types.py` 生成，而它
# 不再写死任何接口清单：它把三条零交线各自的 `type_decls()` 拼起来（`draft/78 §3`）。
# 本模块这一份是「快照 / 场次 / 趟次」那一家 —— 也就是 `snapshot()` 真读出来的那些
# 键，外加趟次的检查点（`run` 那一族的读数）。
#
# 一条纪律：这里的字段名逐字等于后端自己的键，不许改名、不许把后端一定会给的键
# 写成可选。对齐由 `tests/test_webui_contracts.py` 的 C 条守着（生成物键集合 vs
# 后端在夹具工作区上真读出来的键集合）。

#: 三态词表。两套并存是裁定 N1（不许互相顶替）：
#: `computed / unreadable / not_applicable` 是 reviewaccept 那一套（其余面用），
#: `ok / missing / unknown` 只给「交付说明」那一格用。两者在前端都映射到组件
#: `TriState` 的三种视觉态，但字符串本身不通用。
_TS_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("Tri", '"computed" | "unreadable" | "not_applicable"',
     "三态（reviewaccept 词表）：算出来了 / 没查成 / 用不着"),
    ("ReportTri", '"ok" | "missing" | "unknown"',
     "交付说明那一格专用的三态（`webui/state.py` 的 `_read_report`）"),
)

#: 本模块声明、但没有真读数可对账的接口（`{接口名: 理由}`）。
#: 判据 C 的两份名单都从模块自己的属性上读（`tests/test_webui_contracts.py`），
#: 所以"这个接口为什么还没被核对"只写在这里一处。
UNCHECKED_TYPES: dict[str, str] = {
    "RunIndex": "趟次索引是派生数据（`sessions.compute_run_index` 现算、"
                "`rebuild_run_index` 落盘），夹具工作区默认不建索引；判据 C 的落点是"
                "「后端真读出来的键」，而没建索引时读出来的是 None（按设计没有键可比）"
                "⇒ 以 `sessions.compute_run_index` 的形状为准，另由 "
                "`tests/test_webui_pages.py` 判它真的读得出来",
    "RunIndexSession": "同上（`RunIndex.sessions` 的表值：runs / last_end_index / digest）",
    "RunIndexDrift": "同上（`sessions.run_index_report` 的返回值；三档 tri 由它给）",
}


#: 本模块声明、而且判据 C 会在夹具工作区上真读出来的接口。
#:
#: 为什么是这三个（2026-11-14）：`project_reading()` / `current_reading()` 的键
#: 在任何工作区上都在（"这不是一个项目"与"没人交代当前会话"都只是三态的另一个取值，
#: 不是"读不出键"），所以它们进受核对名单 —— 与 `readers.CHECKED_TYPES` 里那批
#: 「顶层键在任何工作区上都存在」的接口同一条口径。`StateSnapshot` 自己在
#: `tests/test_webui_contracts.py` 的 W0 名单里。
CHECKED_TYPES: tuple[str, ...] = ("ProjectReading", "CurrentReading")


#: 逐接口的字段表。每一项 `(TS 名字, 后端出处, ((字段, TS 类型), ...))`。
#: 出处写的是"这个键是从哪段程序读出来的"，不是行号（行号会漂）。
_TS_TYPES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("OptionRow",
     "option_view() —— 一个选项的渲染视图（注意：快照里的 `options` 是这一族对象，"
     "不是裸字符串；`draft/75 §1.3` 那里写的 `string[]` 与盘上读数不一致，以这里为准）",
     (("label", "string"), ("description", "string"), ("multi", "boolean"))),
    ("OrphanGroup",
     "orphan_summary() 的 `groups[]` 元素 —— 按会话分组的「轮次之外的零散事件」",
     (("sid", "string"), ("count", "number"), ("kinds", "string[]"),
      ("first_ts", "string"), ("last_ts", "string"),
      ("first_index", "number"), ("last_index", "number"))),
    ("OrphanSummary",
     "orphan_summary() —— 「轮次之外的零散事件」的汇总读数",
     (("count", "number"), ("groups", "OrphanGroup[]"))),
    ("ProjectReading",
     "project_reading() —— 「这一份快照是哪个项目」的读数（名字的唯一来源是项目文件夹名，"
     "`projects.resolve` 就是拿它当 `ProjectRef.name` 的；卡/标记只用来自证与交叉核对）",
     (("tri", "Tri"), ("reason", "string"), ("name", "string"), ("path", "string"),
      ("state", "string"), ("why", "string"), ("is_project", "boolean"),
      ("card", "string"), ("marker", "string"), ("source", "string"))),
    ("CurrentReading",
     "current_reading() —— 「当前是哪一段会话、第几轮」。sid 由 `serve(sid=…)` 从命令行"
     "交下来，`round` 只调 `webui.state.round_of()`（命令行 `--watch` 印的是同一个函数）",
     (("sid", "string"), ("round", "number"), ("source", "string"),
      ("found", "boolean"))),
    ("StateSnapshot",
     "snapshot() —— 工作区盘上事实的只读投影（返回键逐字见它的 docstring）",
     (("root", "string"), ("generated_at", "string"),
      ("project", "ProjectReading"), ("current", "CurrentReading"),
      ("sessions", "SessionRow[]"), ("pending_questions", "PendingQuestion[]"),
      ("runs", "RunRow[]"), ("orphans", "OrphanRow[]"),
      ("orphan_summary", "OrphanSummary"), ("last_run", "RunRow | null"),
      ("ledger", "LedgerReading"), ("problems", "string[]"))),
    ("SessionRow",
     "snapshot() 的 `sessions[]` —— 一段会话的读盘读数",
     (("sid", "string"), ("path", "string"), ("events_seen", "number"),
      ("events_listed", "number | null"), ("bad_lines", "number"),
      ("first_ts", "string"), ("last_ts", "string"), ("last_kind", "string"),
      ("last_seq", "number"), ("pending", "number"), ("runs", "number"),
      ("orphans", "number"),
      # 这一段会话里「事件流有、而没有任何一趟的自报账认得」的钱
      # （= `llm_call.usd` 合计 − 各趟 `spend_usd` 合计）。会话文件读不出来时是 `null`。
      ("unattributed_usd", "number | null"))),
    ("PendingQuestion",
     "snapshot() 的 `pending_questions[]` —— 一条待答问题（全局，不按会话过滤）",
     (("qid", "string"), ("sid", "string"), ("role", "string"), ("ts", "string"),
      ("timeout_sec", "number | null"), ("text", "string"),
      ("options", "OptionRow[]"), ("multi", "boolean"), ("index", "number"))),
    ("RunRow",
     "snapshot() 的 `runs[]` —— 一趟运行（一条 agent_run_start 到它之后的 agent_run_end）",
     (("sid", "string"), ("role", "string"), ("task", "string"),
      # 这一趟的「绝对编号」（`agent_run_start.task_id`）。读不到写 `""`，
      # 不造一个假编号；`task_id_source` 说这个编号从哪来（`event` / `missing`）。
      # 这一面刻意只有两个取值：编号只能来自它自己的开场事件，不从相邻事件借。
      ("task_id", "string"), ("task_id_source", "string"),
      ("start_index", "number"), ("start_ts", "string"), ("steps", "number"),
      ("llm_calls", "number"), ("usd", "number | null"), ("unknown_usd", "number"),
      # 收工那一行自己报的账（`agent_run_end.spend`）。「不顶替 `usd`」 ——
      # `usd` 是事件求和，是同一趟的另一个来源（`readers.run_view` 的并排卡靠它）。
      # 没有收工行 ⇒ 两格都是 `null`（不是 0）。
      ("spend_usd", "number | null"), ("spend_unknown_usd_calls", "number | null"),
      ("stop_reason", "string"), ("final_chars", "number | null"),
      ("summons", "number | null"), ("messages", "number | null"),
      ("elapsed_sec", "number | null"), ("last_shape", "string"),
      ("end_index", "number | null"), ("end_ts", "string"),
      ("waiting_on", "string[]"), ("waiting", "boolean"),
      # `events_span` 是下标跨度（原 `events_in_run` 改名，数一个字节没动）；
      # `events_owned` 是按三档归属「只数归到这一趟」的（含没有 `task_id` 的 `agent_step`）。
      ("events_span", "number"), ("events_owned", "number"),
      # 「有 start 没 end」不等于「还在跑」（82 的定格数据）。这一格只说
      # "这一段记录没收到 end、而这一场会话的顶趟已经收尾" ⇒ 它是被打断后剩下的循环
      # 记录，不是活着的循环。顶趟还在跑时它恒为 false（那时它真的还在飞）。
      ("stale_loop", "boolean"))),
    ("OrphanRow",
     "snapshot() 的 `orphans[]` —— 轮次之外的一条零散事件（不许折成一趟运行）",
     (("sid", "string"), ("index", "number"), ("kind", "string"),
      ("ts", "string"), ("role", "string"))),
    ("LedgerReading",
     "snapshot() 的 `ledger` —— 台账（第二个独立读数）。`events` 与 `upserts` 同口径"
     "（`D21`：它不再是 events.jsonl 的总行数），`commit_markers` 是其中提交标记的行数",
     (("path", "string"), ("events", "number | null"), ("upserts", "number | null"),
      ("commit_markers", "number | null"), ("tables", "number | null"),
      ("note", "string"), ("tables_note", "string"), ("events_note", "string"))),
    ("ReportReading",
     "_read_report() —— 交付说明 `out/review/REPORT.md` 的读数（二元组 status/text 的字典口径）",
     (("status", "ReportTri"), ("text", "string"))),
    # 裁定 5a：这里曾经还有一对 `CheckpointSpend` / `Checkpoint`（W0 留的、没有
    # reader 的两条声明）。B 线的 `readers.py` 里声明的 `CheckpointView` / `CheckpointSpendView`
    # 才是带真读数的那一对（字段出自 `agent_loop.save_run_checkpoint` 与
    # `llmseam.SeamSpend.to_dict`），两对并存只会让读 `types.ts` 的人猜该用哪一个 ——
    # 所以这一对删掉，检查点那一族只留 B 的那一份。
    ("RunIndexSession",
     "趟次索引里的一场会话（`sessions.compute_run_index` 的 `sessions[sid]`）",
     (("runs", "RunRow[]"), ("last_end_index", "number | null"), ("digest", "string"))),
    ("RunIndex",
     "`GET /api/run-index` 的 `index` 那一栏 —— 趟次索引本体（裁定 O2；"
     "`sessions.compute_run_index` / `rebuild_run_index` 落的盘上那一份）",
     (("version", "string"), ("generated_at", "string"),
      ("sessions", "Record<string, RunIndexSession>"))),
    ("RunIndexDrift",
     "`GET /api/run-index` 的返回值 —— `sessions.run_index_report(root)` 逐字："
     "索引可用性与它与事件现算结果的对账结论（`tri != \"computed\"` ⇒ 显红）",
     (("usable", "boolean"), ("tri", "Tri"), ("reason", "string"),
      ("drift", "string[]"), ("sessions", "string[]"),
      ("index", "RunIndex | null"))),
)


def type_decls(
    types: Sequence[tuple[str, str, Sequence[tuple[str, str]]]] | None = None,
    aliases: Sequence[tuple[str, str, str]] | None = None,
) -> str:
    """一段 TS 声明文本 —— 本仓 `type_decls` 的唯一实现（三条零交线共用它）。

    形状是 `draft/78 §3` 的接缝之一：`agentflow/web/emit_types.py` 把三条零交线
    各自的 `type_decls()` 拼成 `ui/src/types.ts`。于是加接口这件事永远发生在
    自己那一行里 —— 生成器不必再被碰。

    为什么它在这里、且带两个入参：渲染只有这一份，`readers.py` / `writes.py` 里的
    同名函数是薄转发（`state.type_decls(<自己的表>, ())`）—— 改排版一处三处一起变，
    `scripts/lint_rules.py` 的 R003 因此把它们认成转发而不是独立实现。

    `types` / `aliases` 给了才覆盖本模块那两张表：默认值让 `emit_types` 的
    `state.type_decls()` 与只传零个入参时逐字节相同。
    """
    use_types = _TS_TYPES if types is None else types
    use_aliases = _TS_ALIASES if aliases is None else aliases
    parts: list[str] = []
    for name, ts, note in use_aliases:
        parts.append(f"/** {note}。 */\nexport type {name} = {ts};\n")
    for name, source, fields in use_types:
        lines = [f"/** 出处：{source}。 */", f"export interface {name} {{"]
        lines += [f"  {field}: {ts};" for field, ts in fields]
        parts.append("\n".join(lines + ["}"]) + "\n")
    return "\n".join(parts)
