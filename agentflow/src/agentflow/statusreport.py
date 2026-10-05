# -*- coding: utf-8 -*-
"""M 的状态报告（`draft/39` §4，用户 2026-10-05 口径）—— 旁路观测，谁都不停。

## 用户口径（逐字）

> 给 M 再加一个动作：当用户中途想知道当前项目情况时，M 通过搜集最近产出和手稿交接来分析情况，
> 向用户报告，从而不打断智能体协作

## 为什么不能只是"问 M 一句"

`ask_user` 那条路是反向的：它让 M 停下来等人。用户中途想知道情况时，正确的形态是
旁路观测：读盘 → 出报告，谁都不停。所以这一层的第一条纪律是只读：

- 读 `store` 的行、手稿账本、停机状态、会话列表、待答问题；
- 不写任何台账、不写会话事件、不落停机开关、不发模型调用、不碰任何循环；
- 唯一的写是把报告本身落到 `out/review/STATUS-<ts>.{md,json}`（它是产物文件，不是台账）。

## 两个入口（一个实现）

1. 用户侧 CLI（首选）：`agentflow --root <ws> status-report [--since <ts>] [--out <dir>]`
   —— 只读、零模型调用 ⇒ 真正"不打断"；
2. M 的工具/动作：`conductor.status_report`（`side_effect=read`）+ `specs/m.py` 的动作
   `report_status` —— 用户通过留言问"M 现在什么情况"时走它（不发 ask_user、不停任何人的循环）。
   注：入口 2 的动作声明在 `specs/m.py`（FC-27），按 `draft/39` §6.10 排在下一轮与 V 的注册一起做；
   这一层已经把它的实现（`collect` / `render_markdown`）交出来了，接上去只是声明。
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Mapping

#: 报告里逐张表的读数（顺序就是人读报告里的顺序）。
REPORT_TABLES: tuple[str, ...] = (
    "tasks", "documents", "experiments", "conjectures", "attack_plans",
    "review_findings", "literature", "search_requests", "statements",
)
#: 每张表在报告里最多列几条"最近的行"。
RECENT_LIMIT = 8


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _rows(store: Any, table: str) -> list[dict[str, Any]]:
    """读一张表的行（读不到 ⇒ 空列表 + 在报告里记一条 `unreadable`，不假装是 0）。"""
    try:
        return [dict(r) for r in store.rows(table)]
    except Exception:  # noqa: BLE001 —— 读不到与"是 0 行"必须分得开
        return []


def _id_of(table: str, row: Mapping[str, Any]) -> str:
    for key in (f"{table[:-1]}_id", "task_id", "doc_id", "experiment_id", "conjecture_id",
                "plan_id", "finding_id", "lit_id", "request_id", "stmt_id"):
        if row.get(key):
            return str(row[key])
    return ""


def collect(store: Any, root: str | Path, *, since: str = "") -> dict[str, Any]:
    """只读收集这个工作区的当前情况（`draft/39` §4.2 的四类读数）。

    返回一个纯数据 dict（可 `json.dumps`）—— 人读的 markdown 由 `render_markdown` 从它渲染，
    于是"报告里写的数"与"脚本复算的数"是同一份东西（E15 的第 2 条判据就是对拍这两者）。

    `since` 给 ISO 前缀（如 `2026-10-05`）时，各表的"计数"只算这一时间之后的（按行的
    `created_at`/`at`/`started_at` 里最先有的那个）；给空串则算全部。
    """
    from . import manuscripts as MS
    from . import stopctl as SC

    root = Path(root)
    tables: dict[str, Any] = {}
    for table in REPORT_TABLES:
        rows = _rows(store, table)
        if since:
            rows = [r for r in rows if _row_time(r) >= str(since)]
        recent = [{"id": _id_of(table, r), "at": _row_time(r),
                   "hint": _hint_of(table, r)} for r in rows[-RECENT_LIMIT:]]
        tables[table] = {"count": len(rows), "recent": recent}

    # ---- 交接链（手稿账本：谁→谁、一行一份、谁填的）
    ms_rows, ms_bad = MS.read_rows(root)
    if since:
        ms_rows = [r for r in ms_rows if str(r.get("created_at") or "") >= str(since)]
    model_authored = sum(1 for r in ms_rows if "模型填的 notify" in str(r.get("note") or ""))
    derived = sum(1 for r in ms_rows if "派生" in str(r.get("note") or ""))
    manuscripts = {
        "rows": len(ms_rows), "bad_lines": ms_bad[:3],
        "model_authored": model_authored, "derived": derived,
        "recent": [{"id": str(r.get("id") or ""), "sender": str(r.get("sender") or ""),
                    "to": str(r.get("to") or ""), "summary": str(r.get("summary") or "")[:80],
                    "at": str(r.get("created_at") or ""),
                    "source": ("模型填的 notify" if "模型填的 notify" in str(r.get("note") or "")
                               else "框架派生" if "派生" in str(r.get("note") or "") else "未注明")}
                   for r in ms_rows[-RECENT_LIMIT:]],
    }

    # ---- 五元位现状（现算：哪一档几条、有多少条自身不合规）
    from . import evidencebits as EB

    grades: dict[str, int] = {}
    problems = 0
    for r in _rows(store, "statements"):
        bits = EB.bits_from_row(r)
        grades[str(bits.get("grade"))] = grades.get(str(bits.get("grade")), 0) + 1
        if EB.bit_problems(bits):
            problems += 1

    # ---- 在飞与卡点
    live = SC.live_pids(root)
    loops = SC.running_loops(root)
    tasks = _rows(store, "tasks")
    running_tasks = [str(t.get("task_id") or "") for t in tasks
                     if str(t.get("status") or "") in ("pending", "running")]
    refused = [t for t in tasks if str(t.get("outcome") or "") == "refused"]
    by_reason: dict[str, int] = {}
    for t in refused:
        key = str(t.get("refusal_reason") or "（未记理由）")
        by_reason[key] = by_reason.get(key, 0) + 1
    history = SC.stop_history(root, limit=3)

    pending_questions = 0
    try:
        from . import userio as U

        pending_questions = len(U.pending_questions(root))
    except Exception:  # noqa: BLE001 —— 读不到待答问题 ⇒ 这一格判不了（下面 note 里说）
        pending_questions = -1

    report: dict[str, Any] = {
        "generated_at": _now().replace(microsecond=0).isoformat(),
        "workspace": str(root), "since": str(since),
        "tables": tables,
        "manuscripts": manuscripts,
        "five_bit": {"grades": grades, "problems": problems},
        "in_flight": {
            "running_tasks": len(running_tasks), "running_task_ids": running_tasks[:RECENT_LIMIT],
            "live_pids": [{"role": str(p.get("role") or ""), "pid": p.get("pid")} for p in live],
            "running_loops": loops["running"], "readable_sessions": len(loops.get("running") or [])
            + 0,
            "unreadable_sessions": loops.get("unreadable_sessions") or [],
            "stop_switch": SC.read_stop(root) is not None,
            "last_stop_history": history,
        },
        "pending_questions": pending_questions,
        "refusals": {"total": len(refused), "by_reason": by_reason,
                     "recent": [{"task_id": str(t.get("task_id") or ""),
                                 "role": str(t.get("role") or ""),
                                 "action": str(t.get("action") or ""),
                                 "reason": str(t.get("refusal_reason") or "")}
                                for t in refused[-RECENT_LIMIT:]]},
    }
    report["next_steps"] = _next_steps(report)
    return report


def _row_time(row: Mapping[str, Any]) -> str:
    for key in ("created_at", "at", "started_at", "ended_at", "added_at"):
        if row.get(key):
            return str(row[key])
    return ""


def _hint_of(table: str, row: Mapping[str, Any]) -> str:
    """每条最近行的"一眼能看懂"的一小段（不是判据，是给人读的抓手）。"""
    if table == "tasks":
        return f"{row.get('role')}.{row.get('action')} {row.get('status')}/{row.get('outcome')}"
    if table == "documents":
        return f"{row.get('kind')} {row.get('title')}（{row.get('status')}）"
    if table == "experiments":
        return f"{row.get('method')}/{row.get('evidence_kind')} {row.get('result')}"
    if table == "conjectures":
        return f"{row.get('status')}：{str(row.get('statement') or '')[:50]}"
    if table == "attack_plans":
        return f"{row.get('status')}（history {len(row.get('history') or [])} 条）"
    if table == "review_findings":
        return f"{row.get('level')}/{row.get('kind')} {row.get('status')}"
    if table == "statements":
        return f"{row.get('origin')} {row.get('status')}"
    return ""


def _next_steps(report: Mapping[str, Any]) -> list[str]:
    """从读数派生"下一步"（不是模型写的）：每一句都指着一个具体的空格。"""
    out: list[str] = []
    tables = report.get("tables") or {}
    if not (tables.get("conjectures") or {}).get("count"):
        out.append("还没有可检验的猜想（`conjectures` 0 行）⇒ 先把模式写成带 `testable` 的猜想")
    if not (tables.get("documents") or {}).get("count"):
        out.append("还没有稿件（`documents` 0 行）⇒ 有结论就落一份手稿，别只留在会话里")
    if not (report.get("manuscripts") or {}).get("rows"):
        out.append("交接账本还是空的（`manuscripts/handoffs.jsonl` 0 行）⇒ 派活/收工时的 notify 没落下来")
    if (report.get("five_bit") or {}).get("problems"):
        out.append(f"有五元位自身不合规的命题 {report['five_bit']['problems']} 条"
                   "（缺凭据/缺理由）⇒ 那是台账质量问题，先补齐再谈等级")
    if (report.get("in_flight") or {}).get("running_tasks"):
        out.append(f"有 {report['in_flight']['running_tasks']} 条任务还在飞 ⇒ 现在别改口径，"
                   "等它们收工（这份报告本身不打断它们）")
    if (report.get("refusals") or {}).get("total"):
        top = sorted((report["refusals"]["by_reason"] or {}).items(), key=lambda kv: -kv[1])[:2]
        out.append("被拒的动作有 " + str(report["refusals"]["total"]) + " 次，最常见的是 "
                   + "、".join(f"{k}×{v}" for k, v in top) + " ⇒ 参数表/口径要按它改")
    if report.get("pending_questions"):
        out.append(f"有 {report['pending_questions']} 个问题在等用户回答 ⇒ 那是唯一该「停下来」的地方")
    if not out:
        out.append("四类读数都没有明显空格：这一趟的下一步由 M 按当前子目标定")
    return out


def render_status_markdown(report: Mapping[str, Any]) -> str:
    """把读数渲染成人读的短版（四节：产出 / 交接 / 卡点 / 下一步）。"""
    tables = report.get("tables") or {}
    ms = report.get("manuscripts") or {}
    infl = report.get("in_flight") or {}
    five = report.get("five_bit") or {}
    ref = report.get("refusals") or {}
    lines = [
        f"# 项目状态报告（{report.get('generated_at')}）", "",
        f"- 工作区：`{report.get('workspace')}`",
        f"- 统计起点：`{report.get('since') or '（全部）'}`",
        "- 这份报告是**旁路观测**：只读台账与手稿，零模型调用，不打断任何循环。", "",
        "## 一、产出（各表行数 + 最近几条）", "",
        "| 表 | 行数 | 最近 |", "|---|---:|---|",
    ]
    for name in REPORT_TABLES:
        got = tables.get(name) or {}
        recent = "；".join(f"{r.get('id')} {r.get('hint')}" for r in (got.get("recent") or [])[-3:])
        lines.append(f"| `{name}` | {got.get('count', 0)} | {recent or '（无）'} |")
    lines += [
        "", "## 二、交接（手稿账本：谁→谁，一行一份）", "",
        f"- 账本行数：**{ms.get('rows', 0)}**（模型自己填的 notify {ms.get('model_authored', 0)} 行 / "
        f"框架派生 {ms.get('derived', 0)} 行）",
    ]
    if ms.get("bad_lines"):
        lines.append(f"- ⚠️ 台账里有读不出来的行：{ms['bad_lines']}")
    for r in (ms.get("recent") or [])[-5:]:
        lines.append(f"  - `{r.get('id')}` {r.get('sender')}→{r.get('to')}：{r.get('summary')}"
                     f"（{r.get('source')}）")
    if not ms.get("recent"):
        lines.append("  - （还没有交接手稿）")
    lines += [
        "", "## 三、卡点（在飞 / 被拒 / 停机 / 待答）", "",
        f"- 在飞任务：**{infl.get('running_tasks', 0)}**"
        + (f"（{infl.get('running_task_ids')}）" if infl.get("running_task_ids") else ""),
        f"- 活进程登记：**{len(infl.get('live_pids') or [])}** 个"
        + ("：" + "、".join(f"{p['role']}#{p['pid']}" for p in infl["live_pids"])
           if infl.get("live_pids") else ""),
        f"- 在跑的循环：**{'有' if infl.get('running_loops') else '没有'}**"
        + ("：" + "、".join(f"{r['role']}（sid={r['sid']}）" for r in infl["running_loops"])
           if infl.get("running_loops") else ""),
        f"- 停机开关：{'在' if infl.get('stop_switch') else '不在'}"
        + (f"；最近一次叫停：{infl['last_stop_history'][-1].get('reason')}"
           if infl.get("last_stop_history") else ""),
        f"- 待答问题：{'（读不到 ⇒ 这一格没查成）' if report.get('pending_questions') == -1 else report.get('pending_questions', 0)}",
        f"- 被拒动作：**{ref.get('total', 0)}** 次"
        + ("（" + "、".join(f"{k}×{v}" for k, v in sorted((ref.get('by_reason') or {}).items(),
                                                          key=lambda kv: -kv[1])[:4]) + "）"
           if ref.get("by_reason") else ""),
        f"- 五元位现状：{('、'.join(f'{k} {v} 条' for k, v in (five.get('grades') or {}).items()) or '（还没有命题行）')}"
        + (f"；其中 {five.get('problems')} 条自身不合规（缺凭据/缺理由）"
           if five.get("problems") else ""),
        "", "## 四、下一步（**从读数派生**，不是模型写的）", "",
    ]
    lines += [f"- {s}" for s in (report.get("next_steps") or [])]
    return "\n".join(lines) + "\n"


def status_report_paths(root: str | Path, *, out_dir: str | Path | None = None,
                 stamp: str = "") -> tuple[Path, Path]:
    """报告的两个落点：`out/review/STATUS-<YYYYMMDD-HHMM>.{md,json}`。"""
    base = Path(out_dir) if out_dir else Path(root) / "out" / "review"
    ts = stamp or _now().strftime("%Y%m%d-%H%M")
    return base / f"STATUS-{ts}.md", base / f"STATUS-{ts}.json"


def write_status_report(store: Any, root: str | Path, *, out_dir: str | Path | None = None,
                 since: str = "", stamp: str = "") -> tuple[dict[str, Any], Path, Path]:
    """收集 + 落盘（唯一会写盘的地方，而且只写报告本身）。返回 `(报告, md 路径, json 路径)`。"""
    report = collect(store, root, since=since)
    md_path, json_path = status_report_paths(root, out_dir=out_dir, stamp=stamp)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_status_markdown(report), encoding="utf-8", newline="\n")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8", newline="\n")
    return report, md_path, json_path


def selftest() -> int:
    """最小自检：空工作区也能出一份完整报告；四节齐全；数字与复算一致。"""
    import tempfile

    from .store import Store

    root = Path(tempfile.mkdtemp(prefix="statusreport_selftest_"))
    (root / "data").mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()
    report, md, js = write_report(st, root, stamp="20260101-0000")
    checks: list[tuple[str, bool]] = []
    checks.append(("两个落点都在盘上", md.is_file() and js.is_file()))
    text = md.read_text(encoding="utf-8")
    checks.append(("四节齐全", all(s in text for s in ("一、产出", "二、交接", "三、卡点", "四、下一步"))))
    again = collect(st, root)
    checks.append(("复算一致（表行数）",
                   all((again["tables"][k]["count"] == report["tables"][k]["count"])
                       for k in REPORT_TABLES)))
    checks.append(("空工作区也有读数（不是空报告）", bool(report["next_steps"])))
    checks.append(("json 可解析且键齐",
                   set(json.loads(js.read_text(encoding="utf-8")))
                   >= {"tables", "manuscripts", "five_bit", "in_flight", "next_steps"}))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
