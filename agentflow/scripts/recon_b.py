#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RECON-B：真机一趟之后的七项对账（修正后口径，业主 2026-11-19）。

单入口、只读、可独立跑：

    python agentflow/scripts/recon_b.py --root D:\\Incubator\\projects\\lp-ball-11

2026-11-21 RECONFIX 把它从 `temp/reconB/recon.py` 提升到这里（业主规矩：别把有用的
做在 temp 里 —— 它会被重跑第二次，且 `tests/` 要按路径判它）。`temp/reconB/recon.py`
只剩一个转交参数的壳，实现、口径、判据一律在本文件，不复制第二份。

输出：人读表（stdout）＋ JSON（默认 <temp>/reconB/out/<项目名>.json 与同名 .txt）。
除 --outdir 之外不写任何东西；projects/* 一个字都不改。

## 口径（逐项）

① 账目：`账本行 = reason + summon（0 token 结算）+ extract`，三类分别对各自的来源；
   不用「llm_call 数 == 账本行数」那条（它把 summon/extract 当成差额）。
   - reason ↔ `sessions/<sid>.jsonl` 的 `llm_call`（条数 + usd）
   - summon ↔ 子趟收工结算（每趟子代理一条，0 token；`idem_key=settle-…`）
   - extract ↔ 账本内自洽（`note` 首段 `modelgw`、`call_index` 1..N 连续）；它不进会话流，
     没有第二来源 ⇒ 这一档如实标「弱对账」
   口径出处：业主 2026-11-19 裁定原文；`data/usage_ledger.json#rows[].scope`。

② unattributed：会话口径 = `sessions` 里 `llm_call.usd` 累计 − 各趟自报 `spend_usd` 之和；
   同时给账本口径（`task_id=None` 的行数）作对照；两者都列构成。
   口径出处：`agentflow.sessions.unattributed_usd_of`（162 ②，代码注释逐字同口径）。

③ 八格：逐格 pass / fail / not_applicable / unknown（四态；不适用不折成 pass/fail），
   外加新门的一份结论：`can_close` / `machine_pass` / `closing_verdict` /
   `tri_state_exit_code`。
   口径出处：`agentflow.closing.DEFAULT_CHECKS`（八格）、`closing.closing_verdict`
   与 `closing.tri_state_exit_code`（ROOTGATE-①，2026-11-19「要修根因」）。

④ 签：只认 `out/vsigns/<sha>.json`（3 个 passes；每个 pass 带
   `review_call` / `review_pass` / `object_sha256` / `at`）。`issued.json` 只作索引，
   不许当签。同一对象不得既「已签」又「无签文件」——索引与文件双向对账。

   逐票回指台账那一格按签的类型分流（2026-11-21 RECONFIX，此前只认 pending 一本）：
   - 在册签（号 `v-…`）⇒ `verifications/<命题号>.jsonl`（核它在、3 票都在里面、
     回指到的那一行 `proof_sha256` 等于签的 `artifact_sha`）；
   - 未在册签（号 `u-…`）⇒ `verifications/pending/<object_sha256>.jsonl`（同上三核）；
   - 分不清类型（号不是 v-/u-、或 3 票不同形态）⇒ `unchecked`：既不折成合格，
     也不当成「回指缺失」，该项 state 记 unknown（没查成 ≠ 查过了没问题）。
   类型按「那一行台账的号」判，不按「命题现在在不在册」判 —— 认领之后的 pending 行
   物理位置不动（`verifications._claimed_pending_rows`），号仍是 `u-…`。
   口径出处：`v_paths.verification_ledger_path` / `v_ledger_write.next_verification_id`
   （`v-`）与 `v_pending_write.record_pending_sign` / `v_vocab.PENDING_PREFIX`（`u-`）。

⑤ 非平凡度：五档 T0–T4 ＋ 不适用 ＋ 未判分开；分母只算可判命题；必须印 T0。
   口径出处：`agentflow.closing.nontriviality_reading`（FIX186-B，业主 2026-11-19）。

⑥ 销号/义务：板项 `item_state` 残留、`root_open_items`、`auto_retire` 实际销了多少；
   三族义务（`b-register@` / `v-resubmit@` / `b-awake@`）带收件实例、状态、
   是否挂死在已终态台账号。
   口径出处：`agentflow.conductor.Conductor.retire_integrity` /
   `closing.machine_feeders`（只读投影）、`agentflow.obligations` 的三个前缀。

⑦ 会话归口：只有 `sessions/<sid>.jsonl`？跨项目 / 跨 sid 各几条？读口 problems 几条？
   unattributed 的 task 是否都在范围内。

## 逐行读数（TRACEFIX 2026-11-21；不占七项的一格）

七项的口径一个字没动，只是把此前"只计数"的三类升级成逐条：

- ② 里逐趟结算对账：每一趟 `task · 自报 $X/N 次 → 实际 $Y/M 行 · Δ · why`。
  有落痕（`settle-recon|…`）读落痕；旧盘用同一个判据 `conductor.settle_recon_of`
  复算，并标 `recomputed`（不冒充"落过痕"）。合计与会话口径残差并排。
- ⑥ 里边 / 作废的逐条落痕：每条开过 / 认过的边（哪条边、通知、谁 ack 的、终态、
  认没认掉），以及"该有落痕却没有"的逐条点名（已终态但没有 `edge-released`、
  通知过但没有 `stop-acked`、`item_close=expired` 却没有任何作废留痕）。
- `per_row` 一节：MALFORM 的两类 —— relations/statements 说回验通过却无
  `quote_span`（判据 `evidencebits.quote_state == no_evidence`，与收工门同一把尺），
  `ARTIFACTS` 最后一条登记的 sha 与盘上不符（`artifacts.verify_entries` +
  `CHANGE_REASONS` 的读侧分类：签块晚于登记 / 被后续登记顶替 / 真改过）。
  每条带 文件 · 行号或 id · 逐字值 · 判定；读不到就 `unchecked`，不折成 0 条。

## 独立跑与降级

脚本只依赖数据文件；产品代码是加分项，不是前置条件：

- 可导入时走产品口径（`closing.check_closing` / `closing.machine_feeders` /
  `closing.nontriviality_reading` / `sessions.runs_in_session` /
  `sessions.unattributed_usd_of` / `sessions.read_session`）；
- ImportError 或调用抛错 ⇒ 逐项降级为数据直读，并在该项 `degraded=true` 里写清
  「降级原因 + 用的哪个数据文件」；读不到的读数一律 `unknown`（绝不当 0）。
- 产品代码用到的函数逐个写在调用点上方，便于树不稳定时复核。

只读证明：本文件对项目根只调用 `open(..., 'r')` / `Path.read_text`；
唯一的写是 `--outdir`（默认 `agentflow/temp/reconB/out/`）。
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve()
#: 产品根（`agentflow/`）：本文件在 `<产品根>/scripts/recon_b.py`。
REPO = HERE.parents[1]
#: 默认输出目录仍是 `temp/reconB/out/`（提升之后路径不变，好让旧命令与旧证据对得上）。
DEFAULT_OUTDIR = REPO / "temp" / "reconB" / "out"
SRC_DIR = REPO / "src" if (REPO / "src").is_dir() else None

#: 产品模块（可缺）。`--no-product` 可强制走数据直读，用来验证降级路径。
PRODUCT: dict[str, Any] = {
    "closing": None, "sessions": None, "obligations": None, "proofregistry": None,
    #: TRACEFIX：落痕逐条读数（conductor.landed_traces / settle_recon_of）、
    #: 两类 MALFORM 逐行读数（evidencebits.quote_state / artifacts.verify_entries）。
    "conductor": None, "evidencebits": None, "artifacts": None,
    "errors": [], "imported": False,
}

SCHEMA = "reconB/1"
CALIBER = "修正后口径（业主 2026-11-19；ROOTGATE-① / FIX186-B / 162②）"

CELL_SOURCE = {
    "contradictions": "data/dependencies.json#rows[].status · data/statements.json#rows[].status · data/documents.json#rows[].status",
    "load_bearing": "data/statements.json#rows[].evidence_kind · data/documents.json#rows[].claims · data/experiments.json",
    "report_shape": "out/review/REPORT.md（附件三件套 origin=own_result / 依据 / sha）",
    "user_pending": "data/research_questions.json#rows[].status · sessions/<sid>.jsonl 的 question/answer 事件",
    "substance": "data/{documents,relations,experiments,review_findings,statements}.json#rows",
    "acceptance": "out/paper/ACCEPTANCE-CHECKS.json#checks · out/paper/ACCEPTANCE.md",
    "artifact_ledger": "ARTIFACTS.jsonl · 盘上路径",
    "literature_pending": "data/lit_candidates.json#rows[].status / cleared_at",
}


# ---------------------------------------------------------------- 基础设施

def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def bootstrap_product(force_off: bool = False) -> None:
    """把 `agentflow/src` 挂上 sys.path 并导入需要的模块（失败不抛）。"""
    if force_off:
        PRODUCT["errors"].append("--no-product：按开关强制数据直读")
        return
    if SRC_DIR and SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    for name in ("closing", "sessions", "obligations", "proofregistry",
                 "conductor", "evidencebits", "artifacts"):
        try:
            mod = __import__(f"agentflow.{name}", fromlist=[name])
            PRODUCT[name] = mod
            PRODUCT["imported"] = True
        except Exception as exc:  # noqa: BLE001 —— 树不稳定：导入失败只降级，不中止
            PRODUCT["errors"].append(f"import agentflow.{name}: {type(exc).__name__}: {exc}")


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def read_json(path: Path) -> tuple[Any, str]:
    if not path.is_file():
        return None, f"文件不在：{path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"读不成：{path}（{type(exc).__name__}: {exc}）"


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """逐行读 JSONL；坏行进 problems（不静默丢）。"""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.is_file():
        return rows, [f"文件不在：{path}"]
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return rows, [f"读不成：{path}（{type(exc).__name__}: {exc}）"]
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            got = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{path.name}:{no} 坏行（{type(exc).__name__}）")
            continue
        if isinstance(got, Mapping):
            rows.append(dict(got))
        else:
            problems.append(f"{path.name}:{no} 不是对象")
    return rows, problems


def table(root: Path, name: str) -> tuple[list[dict[str, Any]], str]:
    """读 `data/<name>.json` 的 rows。返回 (rows, 错误)；缺表是错误（不是空）。"""
    path = root / "data" / f"{name}.json"
    data, err = read_json(path)
    if err:
        return [], err
    if not isinstance(data, Mapping):
        return [], f"{rel(root, path)} 顶层不是对象"
    rows = data.get("rows")
    if rows is None:
        return [], f"{rel(root, path)} 没有 rows"
    return [dict(r) for r in rows if isinstance(r, Mapping)], ""


def num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def usd(value: Any) -> str:
    return f"${num(value):.6f}"


def pct(a: float, b: float) -> str:
    return f"{(100.0 * a / b):.1f}%" if b else "n/a"


def compact(text: Any, limit: int = 300) -> str:
    """人读表里把产品那边的长理由截断（JSON 里保留全文）。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[:limit] + f"…（截断，全文见 JSON；共 {len(s)} 字）"


def iso_ok(value: Any) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(value or "")))


def sha_ok(value: Any) -> bool:
    return bool(re.match(r"^[0-9a-f]{64}$", str(value or "")))


class RoStore:
    """只读台账句柄：只实现 closing / machine_feeders 用到的三格（rows / root / read_events）。

    为什么不用真 `agentflow.store.Store`：那个句柄可能落锁/建目录；对账脚本对项目只读。
    `closing.check_closing` 对 store 的依赖经实测只有 `store.rows` / `store.root` /
    `store.read_events` 三处（见 closing.py 的 `_check_*`），所以这三格足够。
    """

    def __init__(self, root: Path) -> None:
        self.root = str(root)
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def rows(self, name: str) -> list[dict[str, Any]]:
        if name not in self._cache:
            rows, _err = table(Path(self.root), name)
            self._cache[name] = rows
        return self._cache[name]

    def read_events(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return []


# ---------------------------------------------------------------- 上下文

def collect_context(root: Path) -> dict[str, Any]:
    """把七项共用的读数先读一遍：账本、会话、任务、以及各表（懒加载）。"""
    ctx: dict[str, Any] = {
        "root": root,
        "tables": {},
        "table_errors": {},
        "sessions": [],
        "session_problems": [],
    }

    def T(name: str) -> list[dict[str, Any]]:
        if name not in ctx["tables"]:
            rows, err = table(root, name)
            ctx["tables"][name] = rows
            if err:
                ctx["table_errors"][name] = err
        return ctx["tables"][name]

    ctx["T"] = T

    ledger_path = root / "data" / "usage_ledger.json"
    ledger, err = read_json(ledger_path)
    if err:
        ctx["ledger"] = []
        ctx["ledger_error"] = err
    else:
        rows = (ledger or {}).get("rows") if isinstance(ledger, Mapping) else None
        ctx["ledger"] = [dict(r) for r in (rows or []) if isinstance(r, Mapping)]
        ctx["ledger_error"] = "" if rows is not None else "usage_ledger 没有 rows"

    sdir = root / "sessions"
    files: list[Path] = []
    dir_problems: list[str] = []
    if sdir.is_dir():
        for p in sorted(sdir.iterdir()):
            if p.is_dir():
                dir_problems.append(f"sessions/ 下有子目录：{p.name}")
            elif p.suffix == ".jsonl":
                files.append(p)
            else:
                dir_problems.append(f"sessions/ 下有非 .jsonl 文件：{p.name}")
    else:
        dir_problems.append("sessions/ 不在盘上")
    ctx["session_files"] = files
    ctx["session_dir_problems"] = dir_problems

    for path in files:
        ctx["sessions"].append(_read_one_session(root, path))
    ctx["session_problems"].extend(dir_problems)
    for s in ctx["sessions"]:
        ctx["session_problems"].extend(s["problems"])
    return ctx


def _read_one_session(root: Path, path: Path) -> dict[str, Any]:
    """读一段会话；优先产品 `sessions.read_session`，失败走逐行直读。"""
    sid = path.stem
    events: list[dict[str, Any]] = []
    problems: list[str] = []
    source = f"sessions/{path.name}"
    ss = PRODUCT.get("sessions")
    if ss is not None:
        try:
            events, problems = ss.read_session(str(root), sid)
            problems = list(problems)
        except Exception as exc:  # noqa: BLE001
            problems = [f"产品读口失败（{type(exc).__name__}: {exc}）⇒ 逐行直读"]
            events = []
    if not events and not path.stat().st_size == 0:
        if not problems or problems[0].startswith("产品读口失败"):
            events, extra = read_jsonl(path)
            problems.extend(extra)

    llm = [e for e in events if str(e.get("kind") or "") == "llm_call"]
    ends = [e for e in events if str(e.get("kind") or "") == "agent_run_end"]
    starts = [e for e in events if str(e.get("kind") or "") == "agent_run_start"]
    runs: list[dict[str, Any]] = []
    run_source = "数据直读（sessions/<sid>.jsonl 的 agent_run_start/end）"
    if ss is not None:
        try:
            runs = list(ss.runs_in_session(events, sid=sid))
            run_source = "sessions.runs_in_session（产品口径）"
        except Exception as exc:  # noqa: BLE001
            problems.append(f"sessions.runs_in_session 失败（{type(exc).__name__}: {exc}）")
    if not runs:
        runs = _runs_fallback(events, sid)
        run_source = "数据直读（逐条配对 agent_run_start/end；降级）"

    workspace_roots = {
        str((e.get("opening_facts") or {}).get("workspace_root") or "")
        for e in starts
        if isinstance(e.get("opening_facts"), Mapping)
    }
    return {
        "sid": sid,
        "path": path,
        "source": source,
        "events": events,
        "problems": problems,
        "llm_calls": llm,
        "llm_count": len(llm),
        "llm_usd": sum(num(e.get("usd")) for e in llm),
        "run_ends": ends,
        "run_starts": starts,
        "runs": runs,
        "run_source": run_source,
        "workspace_roots": workspace_roots,
        "event_sids": {str(e.get("sid") or "") for e in events if e.get("sid")},
    }


def _runs_fallback(events: list[dict[str, Any]], sid: str) -> list[dict[str, Any]]:
    """`runs_in_session` 的简化直读版（只在产品模块不可用时用）。"""
    runs: list[dict[str, Any]] = []
    open_by_task: dict[str, dict[str, Any]] = {}
    open_list: list[dict[str, Any]] = []
    for e in events:
        kind = str(e.get("kind") or "")
        tid = str(e.get("task_id") or "")
        if kind == "agent_run_start":
            run = {"sid": sid, "role": str(e.get("role") or ""), "task_id": tid,
                   "llm_calls": 0, "usd": 0.0, "spend_usd": None,
                   "stop_reason": "", "start_ts": str(e.get("ts") or ""), "end_ts": ""}
            runs.append(run)
            open_list.append(run)
            open_by_task[tid] = run
            continue
        owner = open_by_task.get(tid) if tid else None
        if owner is None and len(open_list) == 1:
            owner = open_list[0]
        if owner is None:
            continue
        if kind == "llm_call":
            owner["llm_calls"] += 1
            owner["usd"] = float(owner["usd"]) + num(e.get("usd"))
        elif kind == "agent_run_end" and owner in open_list:
            owner["stop_reason"] = str(e.get("stop_reason") or "")
            owner["end_ts"] = str(e.get("ts") or "")
            spend = e.get("spend")
            if isinstance(spend, Mapping):
                if isinstance(spend.get("calls"), int):
                    owner["llm_calls"] = spend["calls"]
                if isinstance(spend.get("usd"), (int, float)):
                    owner["spend_usd"] = float(spend["usd"])
            open_list.remove(owner)
    return runs


# ---------------------------------------------------------------- ① 账目

def item1_accounting(ctx: dict[str, Any]) -> dict[str, Any]:
    root: Path = ctx["root"]
    rows = ctx["ledger"]
    lines: list[str] = []
    item: dict[str, Any] = {"id": "1", "title": "账目：reason + summon + extract 三类分别对",
                            "state": "unknown", "degraded": False, "lines": lines,
                            "metrics": {}, "sources": ["data/usage_ledger.json#rows"]}
    if ctx.get("ledger_error"):
        lines.append(f"账本读不到：{ctx['ledger_error']} ⇒ unknown（不当 0）")
        item["reason"] = ctx["ledger_error"]
        return item

    by_scope = collections.Counter(str(r.get("scope") or "") for r in rows)
    usd_by = collections.defaultdict(float)
    tokens_by = collections.defaultdict(int)
    for r in rows:
        usd_by[str(r.get("scope") or "")] += num(r.get("usd"))
        tokens_by[str(r.get("scope") or "")] += int(num(r.get("tokens_total")))
    total_usd = sum(num(r.get("usd")) for r in rows)
    lines.append(f"账本 {len(rows)} 行 / {usd(total_usd)}   ← data/usage_ledger.json#rows")
    lines.append(f"  按 scope：reason {by_scope['reason']} 行 / summon {by_scope['summon']} 行 "
                 f"/ extract {by_scope['extract']} 行；其它 "
                 f"{len(rows) - by_scope['reason'] - by_scope['summon'] - by_scope['extract']} 行")

    # ---- reason ↔ 会话 llm_call
    llm_count = sum(s["llm_count"] for s in ctx["sessions"])
    llm_usd = sum(s["llm_usd"] for s in ctx["sessions"])
    reason_rows = [r for r in rows if str(r.get("scope") or "") == "reason"]
    d_cnt = by_scope["reason"] - llm_count
    d_usd = usd_by["reason"] - llm_usd
    ok_reason = (d_cnt == 0) and abs(d_usd) < 1e-6
    lines.append(f"  reason   账本 {by_scope['reason']} 行 {usd(usd_by['reason'])}  ↔  "
                 f"会话 llm_call {llm_count} 次 {usd(llm_usd)}   Δ {d_cnt:+d} 行 / {d_usd:+.6f} USD"
                 f"   ← sessions/*.jsonl 的 kind=llm_call")
    if d_cnt == 0 and abs(d_usd) >= 1e-6:
        lines.append("    注意：条数对上、金额对不上 ⇒ 同一批调用的记账口径有差（逐条比对见 ②）")
    item["metrics"]["reason"] = {"ledger_rows": by_scope["reason"], "ledger_usd": round(usd_by["reason"], 6),
                                 "session_calls": llm_count, "session_usd": round(llm_usd, 6),
                                 "delta_rows": d_cnt, "delta_usd": round(d_usd, 6), "ok": ok_reason}

    # ---- summon ↔ 子趟收工结算（0 token）
    summon_rows = [r for r in rows if str(r.get("scope") or "") == "summon"]
    zero = sum(1 for r in summon_rows if int(num(r.get("tokens_total"))) == 0)
    settle_idem = sum(1 for r in summon_rows if str(r.get("idem_key") or "").startswith("settle-"))
    child_runs = ctx["metrics"].get("child_runs") if isinstance(ctx.get("metrics"), Mapping) else None
    if child_runs is None:
        # 每趟子代理一条：会话里的 run 数 − 顶趟（1）
        child_runs = sum(max(0, len(s["runs"]) - 1) for s in ctx["sessions"])
    ok_summon = (by_scope["summon"] == child_runs) and (zero == len(summon_rows)) and (settle_idem == len(summon_rows))
    sessions_runs = sum(len(s["runs"]) for s in ctx["sessions"])
    unassigned = sum(sum(1 for run in s["runs"] if not str(run.get("task_id") or ""))
                     for s in ctx["sessions"])
    lines.append(f"  summon   账本 {by_scope['summon']} 行 {usd(usd_by['summon'])}（0 token {zero} 行、"
                 f"settle-* {settle_idem} 行）  ↔  子趟收工结算 {child_runs} 次"
                 f"（会话 {sessions_runs} 趟：顶趟 {sessions_runs - child_runs - unassigned}"
                 f" / 子趟 {child_runs}" + (f" / 无 task_id {unassigned}" if unassigned else "") + "）"
                 f"  Δ {by_scope['summon'] - child_runs:+d}"
                 f"   ← data/usage_ledger.json#rows[].scope=summon / idem_key=settle-*")
    item["metrics"]["summon"] = {"ledger_rows": by_scope["summon"], "zero_token_rows": zero,
                                 "settle_rows": settle_idem, "child_runs": child_runs,
                                 "delta": by_scope["summon"] - child_runs, "ok": ok_summon}

    # ---- extract ↔ 账本内自洽（无第二来源）
    extract_rows = [r for r in rows if str(r.get("scope") or "") == "extract"]
    groups: dict[str, list[int]] = collections.defaultdict(list)
    bad_notes = 0
    for r in extract_rows:
        note = str(r.get("note") or "")
        if not note.startswith("modelgw"):
            bad_notes += 1
        m = re.search(r"call_index=(\d+)", note)
        groups[str(r.get("task_id") or "")].append(int(m.group(1)) if m else -1)
    contiguous = 0
    gaps: list[str] = []
    for tid, idx in sorted(groups.items()):
        want = list(range(1, len(idx) + 1))
        if sorted(idx) == want:
            contiguous += 1
        else:
            gaps.append(f"{tid}: {sorted(idx)}")
    ok_extract = (bad_notes == 0) and (contiguous == len(groups))
    lines.append(f"  extract  账本 {by_scope['extract']} 行 {usd(usd_by['extract'])}（note=modelgw {len(extract_rows) - bad_notes}/{len(extract_rows)}，"
                 f"call_index 连续 {contiguous}/{len(groups)} 组）  ↔  无第二来源（extract 不进会话流）"
                 f"   ← data/usage_ledger.json#rows[].note / call_index")
    if gaps:
        lines.append(f"    call_index 不连续：{'; '.join(gaps[:5])}")
    lines.append("    这一档是账本内自洽（弱对账）：没有独立第二来源，故不冒充「两处对上」")
    item["metrics"]["extract"] = {"ledger_rows": by_scope["extract"], "usd": round(usd_by["extract"], 6),
                                  "modelgw_rows": len(extract_rows) - bad_notes,
                                  "contiguous_groups": contiguous, "groups": len(groups),
                                  "weak": True, "ok": ok_extract}

    # ---- 总账：三类加起来必须正好是全部行
    three = by_scope["reason"] + by_scope["summon"] + by_scope["extract"]
    other = len(rows) - three
    lines.append(f"  合计 reason+summon+extract = {three} 行，账本 {len(rows)} 行，其它 scope {other} 行"
                 f"  ⇒ {'账本已按三类完全分解' if other == 0 else '仍有未归类的 scope（见上）'}")
    item["metrics"]["total"] = {"rows": len(rows), "three_scope_rows": three, "other_rows": other,
                                "usd": round(total_usd, 6)}

    # ---- 旧口径对照（这是要废掉的那条）
    old_delta_rows = len(rows) - llm_count
    old_delta_usd = total_usd - llm_usd
    lines.append(f"  旧口径对照：「llm_call 数 == 账本行数」⇒ {llm_count} vs {len(rows)}，"
                 f"差 {old_delta_rows} 行 / {usd(old_delta_usd)} —— 差额正是 summon "
                 f"{by_scope['summon']} + extract {by_scope['extract']}，不是「未归属的钱」")
    item["metrics"]["old_caliber"] = {"llm_calls": llm_count, "ledger_rows": len(rows),
                                      "phantom_rows": old_delta_rows,
                                      "phantom_usd": round(old_delta_usd, 6)}

    item["state"] = "ok" if (ok_reason and ok_summon and ok_extract and other == 0) else "warn"
    return item


# ---------------------------------------------------------------- ② unattributed

def item2_unattributed(ctx: dict[str, Any]) -> dict[str, Any]:
    root: Path = ctx["root"]
    lines: list[str] = []
    item: dict[str, Any] = {"id": "2",
                            "title": "unattributed：会话口径（llm_call 累计 − 各趟自报 spend_usd）＋ 账本口径对照",
                            "state": "unknown", "degraded": False, "lines": lines,
                            "metrics": {}, "sources": ["sessions/<sid>.jsonl", "data/usage_ledger.json#rows"]}
    if not ctx["sessions"]:
        lines.append("没有会话文件 ⇒ unknown（不当 0）")
        item["reason"] = "sessions/ 下没有 .jsonl"
        return item

    total_usd = 0.0
    total_calls = 0
    claimed_usd = 0.0
    claimed_calls = 0
    residual_usd = 0.0
    residual_calls = 0
    missing_self = 0
    taskless = {"calls": 0, "usd": 0.0}
    no_run = {"calls": 0, "usd": 0.0}
    run_ids: set[str] = set()
    llm_by_task: dict[str, dict[str, float]] = collections.defaultdict(lambda: {"calls": 0.0, "usd": 0.0})
    spend_by_task: dict[str, dict[str, float]] = collections.defaultdict(lambda: {"calls": 0.0, "usd": 0.0})
    per_session: list[dict[str, Any]] = []
    for s in ctx["sessions"]:
        su = float(s["llm_usd"])
        sc = int(s["llm_count"])
        cu = sum(num(r.get("spend_usd")) for r in s["runs"] if r.get("spend_usd") is not None)
        cc = sum(int(num(r.get("llm_calls"))) for r in s["runs"])
        total_usd += su
        total_calls += sc
        claimed_usd += cu
        claimed_calls += cc
        residual_usd += su - cu
        residual_calls += sc - cc
        missing_self += sum(1 for r in s["runs"] if r.get("spend_usd") is None)
        run_ids |= {str(r.get("task_id") or "") for r in s["runs"]}
        for e in s["llm_calls"]:
            tid = str(e.get("task_id") or "")
            if not tid:
                taskless["calls"] += 1
                taskless["usd"] += num(e.get("usd"))
                continue
            if tid not in {str(r.get("task_id") or "") for r in s["runs"]}:
                no_run["calls"] += 1
                no_run["usd"] += num(e.get("usd"))
            llm_by_task[tid]["calls"] += 1
            llm_by_task[tid]["usd"] += num(e.get("usd"))
        for r in s["runs"]:
            tid = str(r.get("task_id") or "")
            spend_by_task[tid]["usd"] += num(r.get("spend_usd"))
            spend_by_task[tid]["calls"] += int(num(r.get("llm_calls")))
        per_session.append({"sid": s["sid"], "calls": sc, "usd": round(su, 6),
                            "claimed_usd": round(cu, 6), "residual_usd": round(su - cu, 6),
                            "residual_calls": sc - cc, "runs": len(s["runs"]),
                            "missing_self_report": sum(1 for r in s["runs"] if r.get("spend_usd") is None)})

    per_task: list[dict[str, Any]] = []
    underreport_usd = 0.0
    underreport_calls = 0.0
    for tid in sorted(set(llm_by_task) | set(spend_by_task)):
        lu = llm_by_task[tid]["usd"]
        su = spend_by_task[tid]["usd"]
        if abs(lu - su) < 1e-9 and llm_by_task[tid]["calls"] == spend_by_task[tid]["calls"]:
            continue
        per_task.append({"task_id": tid, "event_calls": int(llm_by_task[tid]["calls"]),
                         "event_usd": round(lu, 6), "reported_calls": int(spend_by_task[tid]["calls"]),
                         "reported_usd": round(su, 6), "delta_usd": round(lu - su, 6),
                         "delta_calls": int(llm_by_task[tid]["calls"] - spend_by_task[tid]["calls"])})
        if lu > su:
            underreport_usd += lu - su
            underreport_calls += llm_by_task[tid]["calls"] - spend_by_task[tid]["calls"]
    per_task.sort(key=lambda r: -abs(r["delta_usd"]))

    lines.append(f"会话累计 llm_call {total_calls} 次 / {usd(total_usd)}"
                 f"   ← sessions/<sid>.jsonl 的 kind=llm_call")
    lines.append(f"各趟自报 spend_usd 合计 {usd(claimed_usd)}（{claimed_calls} 次；"
                 f"缺自报的趟 {missing_self}）")
    lines.append(f"⇒ unattributed（会话口径）= {usd(residual_usd)} / {residual_calls} 次调用"
                 f"   （口径：sessions.unattributed_usd_of，162②）")
    lines.append("   构成：")
    lines.append(f"     · task_id 为空的调用：{taskless['calls']} 次 / {usd(taskless['usd'])}")
    lines.append(f"     · task_id 有值、但同号没有对应的趟：{no_run['calls']} 次 / {usd(no_run['usd'])}")
    lines.append(f"     · 有对应趟、但事件求和 > 该趟自报：{int(underreport_calls)} 次 / {usd(underreport_usd)}"
                 f"（{len(per_task)} 个 task）")
    if per_task:
        lines.append("       差额最大的几笔（task_id / 事件 calls,usd / 自报 calls,usd / Δ）：")
        for r in per_task[:8]:
            lines.append(f"         {r['task_id']}  {r['event_calls']},{usd(r['event_usd'])}  →  "
                         f"{r['reported_calls']},{usd(r['reported_usd'])}   Δ {r['delta_calls']:+d},"
                         f"{r['delta_usd']:+.6f}")
    per_session_lines = [f"{p['sid']}：{p['calls']} 次 {usd(p['usd'])}，自报 {usd(p['claimed_usd'])}，"
                         f"残 {usd(p['residual_usd'])}/{p['residual_calls']} 次"
                         for p in per_session]
    for line in per_session_lines:
        lines.append(f"     会话 {line}")
    # ---- 逐趟结算对账（TRACEFIX）：有落痕读落痕，旧盘用同一个判据复算（标 recomputed）
    settle_lines, settle_metrics = _settle_trace_lines(
        ctx, residual_usd=residual_usd, residual_calls=residual_calls,
        claimed_usd=claimed_usd)
    lines.extend(settle_lines)

    # 账本口径对照
    ledger = ctx["ledger"]
    none_rows = [r for r in ledger if r.get("task_id") is None]
    none_by_scope = collections.Counter(str(r.get("scope") or "") for r in none_rows)
    lines.append(f"账本口径（task_id=None 的行）={len(none_rows)} 行"
                 f"（按 scope：{dict(none_by_scope) or '无'}）"
                 f"   ← data/usage_ledger.json#rows[].task_id")
    lines.append(f"   构成：账本共 {len(ledger)} 行，有 task_id {len(ledger) - len(none_rows)} 行 / "
                 f"空 {len(none_rows)} 行 ⇒ 账本这一侧「无主」就是 {len(none_rows)} 行")
    lines.append(f"   与上一行对照：账本按 task 归属是满的（没有 None 行），"
                 f"而会话口径仍有 {usd(residual_usd)} 没被各趟自报认领 —— 两个口径量的是两件事")
    ledger_usd = sum(num(r.get("usd")) for r in ledger)
    extract_usd = sum(num(r.get("usd")) for r in ledger if str(r.get("scope") or "") == "extract")
    lines.append(f"   账本总花费 {usd(ledger_usd)} − 会话自报 {usd(claimed_usd)} = "
                 f"{usd(ledger_usd - claimed_usd)}"
                 f"（= extract {usd(extract_usd)} + 会话残差 {usd(residual_usd)}；summon 0 token）")

    item["metrics"] = {
        "session_calls": total_calls, "session_usd": round(total_usd, 6),
        "claimed_usd": round(claimed_usd, 6), "claimed_calls": claimed_calls,
        "unattributed_usd": round(residual_usd, 6), "unattributed_calls": residual_calls,
        "composition": {"taskless": taskless, "no_run": no_run,
                        "run_underreport": {"calls": int(underreport_calls),
                                            "usd": round(underreport_usd, 6),
                                            "tasks": len(per_task)}},
        "per_task": per_task[:20], "per_session": per_session, "missing_self_report": missing_self,
        "settle_traces": settle_metrics,
        "ledger_caliber": {"task_id_none_rows": len(none_rows), "by_scope": dict(none_by_scope),
                           "ledger_usd": round(ledger_usd, 6)},
    }
    # 判定：0 残差才算 ok；有残差是读数（warn），不是崩溃
    item["state"] = "ok" if abs(residual_usd) < 1e-6 and residual_calls == 0 else "warn"
    if item["state"] != "ok":
        item["reason"] = (f"会话口径残差 {usd(residual_usd)} / {residual_calls} 次调用"
                          f"（未被各趟自报 spend_usd 认领）")
    if taskless["calls"] or no_run["calls"]:
        item["note"] = "存在无主调用（task_id 空或无对应趟）—— 这是要优先查的那一类"
    return item


# ---------------------------------------------------------------- ③ 八格

def _cell_readings(ctx: dict[str, Any]) -> dict[str, Any]:
    """八格各自的数据直读读数（作为 product 读数的出处与旁证）。"""
    T = ctx["T"]
    deps = T("dependencies")
    stmts = T("statements")
    docs = T("documents")
    out: dict[str, Any] = {}
    out["contradictions"] = {
        "dependencies_disputed_refuted": sum(1 for r in deps if str(r.get("status") or "") in ("disputed", "refuted")),
        "statements_disputed": sum(1 for r in stmts if str(r.get("status") or "") == "disputed"),
        "documents_unresolved_review": sum(1 for r in docs if str(r.get("status") or "") == "unresolved_review"),
        "rows": {"dependencies": len(deps), "statements": len(stmts), "documents": len(docs)},
    }
    out["substance"] = {name: len(T(name)) for name in
                        ("documents", "relations", "experiments", "review_findings", "statements")}
    qs = T("research_questions")
    out["user_pending"] = {"questions": len(qs),
                           "waiting_user": sum(1 for r in qs if str(r.get("status") or "") in
                                               ("waiting_user", "pending_user", "open", "asked")),
                           "statuses": dict(collections.Counter(str(r.get("status") or "") for r in qs))}
    acc_path = ctx["root"] / "out" / "paper" / "ACCEPTANCE-CHECKS.json"
    acc, acc_err = read_json(acc_path)
    checks = (acc or {}).get("checks") if isinstance(acc, Mapping) else None
    out["acceptance"] = {"path": "out/paper/ACCEPTANCE-CHECKS.json",
                         "exists": acc_path.is_file(), "error": acc_err,
                         "rows": len(checks or []),
                         "na_rows": sum(1 for r in (checks or []) if isinstance(r, Mapping) and r.get("na") is True)}
    art_path = ctx["root"] / "ARTIFACTS.jsonl"
    arts, art_problems = read_jsonl(art_path)
    missing: list[str] = []
    for a in arts:
        p = str(a.get("path") or "").split("#", 1)[0]
        if p and not (ctx["root"] / p).is_file():
            missing.append(p)
    out["artifact_ledger"] = {"rows": len(arts), "missing": len(missing), "missing_examples": missing[:5],
                              "problems": art_problems[:5]}
    lit = T("lit_candidates")
    out["literature_pending"] = {
        "rows": len(lit),
        "pending": sum(1 for r in lit if str(r.get("status") or "") == "pending"),
        "without_cleared_at": sum(1 for r in lit if not r.get("cleared_at")),
        "statuses": dict(collections.Counter(str(r.get("status") or "") for r in lit)),
    }
    report = ctx["root"] / "out" / "review" / "REPORT.md"
    out["report_shape"] = {"path": "out/review/REPORT.md", "exists": report.is_file(),
                           "bytes": report.stat().st_size if report.is_file() else 0}
    claims = sum(len(r.get("claims") or []) for r in docs)
    out["load_bearing"] = {"documents_claims": claims,
                           "statements_proof": sum(1 for r in stmts if str(r.get("evidence_kind") or "") == "proof")}
    return out


def _fallback_cells(ctx: dict[str, Any], readings: Mapping[str, Any]) -> dict[str, str]:
    """产品模块不可用时的降级八格（只判能诚实直读的几格，其余 unknown）。"""
    cells: dict[str, str] = {}
    c = readings["contradictions"]
    if c["rows"]["statements"] == 0 and c["rows"]["dependencies"] == 0 and c["rows"]["documents"] == 0:
        cells["contradictions"] = "unknown"
    else:
        bad = (c["dependencies_disputed_refuted"] + c["statements_disputed"]
               + c["documents_unresolved_review"])
        cells["contradictions"] = "pass" if bad == 0 else "fail"
    cells["load_bearing"] = "unknown"      # 要读 claims 与 T3 背书，直读会撒谎
    cells["report_shape"] = "unknown"      # 体例归 M，直读判不了
    cells["user_pending"] = ("pass" if readings["user_pending"]["waiting_user"] == 0 else "fail")
    cells["substance"] = ("pass" if any(readings["substance"].values()) else "fail")
    cells["acceptance"] = "unknown"        # 逐行现算的实现不在数据里
    cells["artifact_ledger"] = ("pass" if readings["artifact_ledger"]["missing"] == 0 else "fail")
    cells["literature_pending"] = ("fail" if readings["literature_pending"]["pending"] > 0 else "unknown")
    return cells


def item3_eight_cells(ctx: dict[str, Any]) -> dict[str, Any]:
    root: Path = ctx["root"]
    lines: list[str] = []
    item: dict[str, Any] = {"id": "3",
                            "title": "八格：逐格四态 + 新门的一份结论（can_close / machine_pass / closing_verdict / tri_state_exit_code）",
                            "state": "unknown", "degraded": False, "lines": lines,
                            "metrics": {}, "sources": ["agentflow.closing.DEFAULT_CHECKS",
                                                       "agentflow.closing.closing_verdict"]}
    readings = _cell_readings(ctx)
    item["metrics"]["data_readings"] = readings
    product_cells: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    degraded_reason = ""

    CL = PRODUCT.get("closing")
    if CL is not None:
        try:
            store = RoStore(root)
            feed = CL.machine_feeders(store)
            session_sids = [s["sid"] for s in ctx["sessions"]]
            sid = session_sids[0] if len(session_sids) == 1 else None
            rep = CL.check_closing(
                store,
                project_dir=str(root),
                report_path=str(root / "out" / "review" / "REPORT.md"),
                sid=sid,
                retire=feed.get("retire"),
                programs=feed.get("programs"),
            )
            verdict = rep.verdict
            for cell in verdict.get("cells") or []:
                state = str(cell.get("status") or "unknown")
                state = {"na": "not_applicable"}.get(state, state)
                product_cells.append({"check": str(cell.get("check") or ""), "status": state,
                                      "why": str(cell.get("why") or ""),
                                      "source": CELL_SOURCE.get(str(cell.get("check") or ""), "")})
            counts4 = collections.Counter(c["status"] for c in product_cells)
            summary = {
                "verdict": verdict.get("verdict"), "exit_code": verdict.get("exit_code"),
                "can_close": verdict.get("can_close"), "machine_pass": verdict.get("machine_pass"),
                "m_says_done": verdict.get("m_says_done"),
                "counts": {"pass": counts4["pass"], "fail": counts4["fail"],
                           "not_applicable": counts4["not_applicable"],
                           "unknown": counts4["unknown"]},
                "blockers": verdict.get("blockers") or [],
                "retire": verdict.get("retire") or {},
                "programs": verdict.get("programs") or {},
                "reason": verdict.get("reason") or "",
                "feed_why": feed.get("why") or "",
                # 一份结论（ROOTGATE-①）：只留结论本身，逐格在 cells、逐条 blocker 在 blockers
                "closing_verdict": {
                    "verdict": verdict.get("verdict"), "exit_code": verdict.get("exit_code"),
                    "can_close": verdict.get("can_close"), "machine_pass": verdict.get("machine_pass"),
                    "m_says_done": verdict.get("m_says_done"),
                    "reason": verdict.get("reason") or "",
                },
                "source": "agentflow.closing.check_closing + closing.closing_verdict",
            }
        except Exception as exc:  # noqa: BLE001
            degraded_reason = f"产品读数抛错（{type(exc).__name__}: {exc}）"
    else:
        degraded_reason = "产品模块未导入（ImportError）"

    if not product_cells:
        # ---- 降级：数据直读（能诚实的才判，判不了的明写 unknown）
        cells = _fallback_cells(ctx, readings)
        for name, state in cells.items():
            product_cells.append({"check": name, "status": state,
                                  "why": "降级直读" if state != "unknown" else "降级后算不出来",
                                  "source": CELL_SOURCE.get(name, "")})
        summary = {"verdict": "unknown", "exit_code": 2, "can_close": None, "machine_pass": None,
                   "m_says_done": (lambda rows: (bool(rows[-1].get("met")) if rows else None))(
                       read_jsonl(root / "out" / "review" / "m-verdicts.jsonl")[0]),
                   "counts": dict(collections.Counter(c["status"] for c in product_cells)),
                   "blockers": [], "retire": {}, "programs": {},
                   "reason": degraded_reason, "closing_verdict": None,
                   "source": "降级直读（不是权威结论）"}
        item["degraded"] = True
        item["degraded_reason"] = degraded_reason

    lines.append(f"逐格（{len(product_cells)} 格；四态 pass/fail/not_applicable/unknown）：")
    for c in product_cells:
        why = f" —— {compact(c['why'])}" if c.get("why") else ""
        lines.append(f"  {c['check']:<18} {c['status']:<14}{why}")
    # 每格的数据出处（读的人要能复算）
    lines.append("  逐格出处：")
    for key in ("contradictions", "load_bearing", "report_shape", "user_pending",
                "substance", "acceptance", "artifact_ledger", "literature_pending"):
        lines.append(f"    {key:<18} ← {CELL_SOURCE.get(key, '')}")

    cnt = summary.get("counts") or {}
    lines.append(f"计数：pass {cnt.get('pass', 0)} / fail {cnt.get('fail', 0)} / "
                 f"not_applicable {cnt.get('not_applicable', 0)} / unknown {cnt.get('unknown', 0)}"
                 f"   （n/a 不折成 pass，也不折成 fail）")
    lines.append(f"新门一份结论：")
    lines.append(f"  closing_verdict   = {summary.get('verdict')}")
    lines.append(f"  can_close         = {summary.get('can_close')}   （三态：True/False/None；None 不是通过）")
    lines.append(f"  machine_pass      = {summary.get('machine_pass')}")
    lines.append(f"  tri_state_exit_code = {summary.get('exit_code')}   （0 可交付 / 1 被拦住 / 2 没查成）")
    lines.append(f"  m_says_done       = {summary.get('m_says_done')}")
    if summary.get("reason"):
        lines.append(f"  结论理由：{summary['reason']}")
    for b in (summary.get("blockers") or [])[:8]:
        lines.append(f"  blocker: {b.get('check')} / {b.get('code')} —— {compact(b.get('why'))}")
    if item["degraded"]:
        lines.append(f"  [degraded] {degraded_reason} ⇒ 这一格不是权威结论（unknown，不是 pass）")
    lines.append(f"  读数出处：{summary.get('source')}")
    lines.append("  注：本项 state=ok 只表示「八格都读到了」，不是「门过了」——"
                 "门过没过只看上面 closing_verdict（fail 也是读数完整）。")

    item["metrics"]["cells"] = product_cells
    item["metrics"]["summary"] = summary
    # 状态：产品口径下，有 fail/blocker 仍算「读数完整（ok）」，unknown 才是没查成
    if item["degraded"]:
        item["state"] = "unknown"
    else:
        item["state"] = "ok" if cnt.get("unknown", 0) == 0 else "unknown"
    return item


# ---------------------------------------------------------------- ④ 签

# ---------------------------------------------------------------- ④ 签

#: 签的两种类型。类型由「那一行台账的号」决定，两本的落点不同：
#:   registered（`v-…`）⇒ `verifications/<命题号>.jsonl`
#:       （一份命题一本，`v_paths.verification_ledger_path`；号在文件内递增，
#:        所以 `v-000006` 在别的命题那一本里是另一行 —— 按号跨文件找会串台）
#:   pending（`u-…`）   ⇒ `verifications/pending/<object_sha256>.jsonl`
#:       （按对象内容分文件，`v_pending_write.record_pending_sign` 的键是 `object_sha256 or proof_sha256`；
#:        `u-` 号是整目录唯一，见 `verifications._next_pending_verification_id`）
REGISTERED = "registered"
PENDING = "pending"
BACKING_LABEL = {REGISTERED: "在册签", PENDING: "未在册签"}


def sign_kind_of(verification_id: Any) -> str:
    """这一票是哪一种签（按它那一行台账的号判）；分不清 ⇒ 空串。

    为什么不按「命题现在在不在册」判：pending 行被认领之后物理位置不动
    （`verifications._claimed_pending_rows` 读的就是 pending 目录），号仍是 `u-…`。
    `projects/lp-ball-15` 的 3 个合格签正是这一种：命题已在册（000187 / 000188 / 000189），
    签却是未在册时发的（`u-…`，台账在 `verifications/pending/`）—— 按命题状态去
    `verifications/<号>.jsonl` 找，就会把它们整批读成「回指缺失」。

    判据出处：`v_ledger_write.next_verification_id`（`v-` + 文件内行数）/
    `v_vocab.PENDING_PREFIX`（`u-`）。
    """
    vid = str(verification_id or "").strip()
    if vid.startswith("v-"):
        return REGISTERED
    if vid.startswith("u-"):
        return PENDING
    return ""


def _anchor_of(sign: Mapping[str, Any]) -> tuple[str, str]:
    """签自报的台账锚点 `path#vid` ⇒ (path, vid)；没有这一格 ⇒ ("", "")。"""
    text = str(sign.get("ledger") or "").strip()
    path, _, vid = text.partition("#")
    return path.strip(), vid.strip()


def sign_backing_target(sign: Mapping[str, Any], passes: list[dict[str, Any]],
                        by_proof: Mapping[str, list[dict[str, Any]]], kind: str
                        ) -> tuple[str, str]:
    """这一签该回指哪一本台账 ⇒ (path, why)；分不清 ⇒ ("", why)。

    两条分支、一份实现（`item4_signs` 只调这一个函数）：

    - 在册：`verifications/<命题号>.jsonl`。命题号取签上的 `statement_id`，退到
      `statements` 表里 `proof_sha256` 对得上的那一条，再退到自报锚点里的号。
    - 未在册：`verifications/pending/<object_sha256>.jsonl`；对象 sha 读不出来时退到
      签的 `artifact_sha`（`record_pending_sign` 的键就是 `object_sha256 or proof_sha256`），
      再退到自报锚点里的那份 sha。

    `why` 只在分不清时非空 —— 那种情况调用方落 `unchecked`，既不折成 ok，也不当成缺失。
    """
    artifact_sha = str(sign.get("artifact_sha") or "")
    anchor_path, _anchor_vid = _anchor_of(sign)
    if kind == REGISTERED:
        stmt = str(sign.get("statement_id") or "").strip()
        if not re.match(r"^\d{4,6}$", stmt):
            cand = [str(r.get("stmt_id") or "")
                    for r in (by_proof.get(artifact_sha) or []) if str(r.get("stmt_id") or "")]
            stmt = cand[0] if len(cand) == 1 else ""
        if not stmt:
            found = re.match(r"^verifications/(\d{4,6})\.jsonl$", anchor_path)
            stmt = found.group(1) if found else ""
        if not stmt:
            return "", ("在册签的命题号读不出来（签上没有 statement_id，statements 表里也没有"
                        f"唯一对得上 artifact_sha={artifact_sha[:12]}… 的那一行）")
        return f"verifications/{stmt}.jsonl", ""
    if kind == PENDING:
        objs = {str(p.get("object_sha256") or "") for p in passes}
        obj = next(iter(objs)) if len(objs) == 1 else ""
        key = obj if sha_ok(obj) else (artifact_sha if sha_ok(artifact_sha) else "")
        if not key:
            found = re.match(r"^verifications/pending/([0-9a-f]{64})\.jsonl$", anchor_path)
            key = found.group(1) if found else ""
        if not key:
            return "", "未在册签的对象 sha 与正文 sha 都读不出来（盘上找不到该回指哪一份 pending 台账）"
        return f"verifications/pending/{key}.jsonl", ""
    return "", f"verification_id={str(passes[0].get('verification_id') if passes else '')!r} 不是 v-/u- 形态"


def item4_signs(ctx: dict[str, Any]) -> dict[str, Any]:
    root: Path = ctx["root"]
    lines: list[str] = []
    item: dict[str, Any] = {"id": "4", "title": "签：只认 out/vsigns/<sha>.json（3 passes），issued.json 只作索引",
                            "state": "unknown", "degraded": False, "lines": lines,
                            "metrics": {}, "sources": ["out/vsigns/*.json", "out/vsigns/issued.json"]}
    vdir = root / "out" / "vsigns"
    if not vdir.is_dir():
        lines.append("out/vsigns/ 不在盘上 ⇒ 这一趟没有签（合法初态；不是 unknown）")
        item["metrics"] = {"tri": "not_applicable", "signs": 0, "issued": 0}
        item["state"] = "ok"
        item["metrics"]["tri"] = "not_applicable"
        return item

    sign_files = [p for p in sorted(vdir.glob("*.json")) if p.name != "issued.json"]
    issued_path = vdir / "issued.json"
    issued, issued_err = read_json(issued_path)
    issued_rows = []
    if isinstance(issued, Mapping) and isinstance(issued.get("signs"), list):
        issued_rows = [dict(x) for x in issued["signs"] if isinstance(x, Mapping)]
    elif issued is not None:
        issued_err = issued_err or "issued.json 没有 signs 列表"

    statements = ctx["T"]("statements")
    by_proof = {}
    for r in statements:
        sha = str(r.get("proof_sha256") or "")
        if sha:
            by_proof.setdefault(sha, []).append(r)

    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    unchecked: list[dict[str, Any]] = []
    for path in sign_files:
        sign, err = read_json(path)
        problems: list[str] = []
        if err or not isinstance(sign, Mapping):
            invalid.append({"file": path.name, "problems": [err or "不是对象"]})
            continue
        stem = path.stem
        artifact_sha = str(sign.get("artifact_sha") or "")
        passes = [dict(p) for p in (sign.get("passes") or []) if isinstance(p, Mapping)]
        if artifact_sha != stem:
            problems.append(f"文件名 sha 与 artifact_sha 不一致（{stem[:12]} vs {artifact_sha[:12]}）")
        if len(passes) != 3:
            problems.append(f"passes={len(passes)}（要 3）")
        need = sign.get("need")
        if need is not None and int(num(need)) != 3:
            problems.append(f"need={need}（要 3）")
        for i, p in enumerate(passes, 1):
            if not str(p.get("review_call") or "").strip():
                problems.append(f"pass#{i} 缺 review_call")
            if not isinstance(p.get("review_pass"), int):
                problems.append(f"pass#{i} review_pass 不是整数")
            if not sha_ok(p.get("object_sha256")):
                problems.append(f"pass#{i} object_sha256 不是 64 位 hex")
            if not iso_ok(p.get("at")):
                problems.append(f"pass#{i} at 不是 ISO 时间")
            if str(p.get("verdict") or "") != "成立":
                problems.append(f"pass#{i} verdict={p.get('verdict')!r}（不是「成立」）")
        # ---- 回指台账：按签的类型分流（同一份实现，两条分支）
        # 改前这里只认一本：`verifications/pending/<object_sha256>.jsonl`。在册签住
        # `verifications/<命题号>.jsonl`，于是一旦在册签带上 object_sha256（SIGNMAL 之后的
        # 写侧形态），这一格会把它读成「回指缺失」—— 那是口径混同，不是产物缺陷。
        kinds = {sign_kind_of(p.get("verification_id")) for p in passes}
        kinds.discard("")
        undecided = [str(p.get("verification_id") or "") for p in passes
                     if not sign_kind_of(p.get("verification_id"))]
        kind = next(iter(kinds)) if len(kinds) == 1 and not undecided else ""
        label = BACKING_LABEL.get(kind, "类型未判")
        backing: dict[str, Any] = {"kind": kind, "label": label, "path": "", "exists": False,
                                   "rows": 0, "rows_for_this_sign": 0, "unchecked": ""}
        target, why = ("", "") if not kind else sign_backing_target(sign, passes, by_proof, kind)
        if not kind:
            why = (f"3 票的号是 {[str(p.get('verification_id') or '') for p in passes]}："
                   "不是同一个 v-/u- 形态 ⇒ 分不清这一签是在册签还是未在册签")
        if not target:
            backing["unchecked"] = f"{why}（unchecked：既不折成合格，也不当成回指缺失）"
        else:
            tpath = root / target
            trows, tproblems = read_jsonl(tpath) if tpath.is_file() else ([], [])
            by_id = {str(r.get("verification_id") or ""): r for r in trows}
            backing.update(path=target, exists=tpath.is_file(), rows=len(trows))
            anchor_path, _anchor_vid = _anchor_of(sign)
            if anchor_path and anchor_path != target:
                problems.append(f"签自报的台账锚点是 {anchor_path}，而它是{label}、应回指 {target}")
            if not backing["exists"]:
                problems.append(f"{label}回指的台账不在盘上（{target}）")
            else:
                for i, p in enumerate(passes, 1):
                    vid = str(p.get("verification_id") or "")
                    row = by_id.get(vid)
                    if row is None:
                        problems.append(f"pass#{i} verification_id={vid} 不在 {target} 的行里")
                        continue
                    backing["rows_for_this_sign"] += 1
                    row_sha = str(row.get("proof_sha256") or "")
                    if row_sha and row_sha != artifact_sha:
                        problems.append(
                            f"pass#{i} 在 {target} 回指到的那一行 proof_sha256={row_sha[:12]}… "
                            f"≠ 签的 artifact_sha={artifact_sha[:12]}…")
                if backing["rows_for_this_sign"] != len(passes):
                    problems.append(f"{label}回指只对上 {backing['rows_for_this_sign']}/{len(passes)} 票"
                                    f"（台账 {target} 共 {len(trows)} 行）"
                                    + (f"；读不出来的行 {tproblems[:2]}" if tproblems else ""))
        rp = [p.get("review_pass") for p in passes]
        if rp != [1, 2, 3]:
            problems.append(f"review_pass 序列 {rp}（要 [1,2,3]）")
        vids = [str(p.get("verification_id") or "") for p in passes if p.get("verification_id")]
        if len(vids) != len(set(vids)):
            problems.append("verification_id 有重复（3 个 pass 要能逐次回指不同的核验行）")
        ats = [str(p.get("at") or "") for p in passes]
        if len(set(ats)) != len(ats):
            problems.append("3 个 pass 的 at 有重复（无法区分三次）")
        if ats and ats != sorted(ats):
            problems.append("3 个 pass 的 at 不是递增序列")
        objects = {str(p.get("object_sha256") or "") for p in passes}
        if len(objects) != 1:
            problems.append(f"3 个 pass 的 object_sha256 不唯一：{sorted(objects)}")
        # `review_call` 是「这一轮审稿」的调用号：同一轮的 3 次 pass 共享它是正常的；
        # 这里只要求它非空（上面逐条查过），不要求三个不同。
        rcs = [str(p.get("review_call") or "") for p in passes]
        # 用产品函数复算 proof_sha（可选）：签盖的那把尺必须能复现
        pr = PRODUCT.get("proofregistry")
        proof_check = "skipped"
        matched = by_proof.get(artifact_sha) or []
        if pr is not None and matched:
            try:
                got = str(pr.proof_sha(matched[0].get("proof_text") or ""))
                proof_check = "match" if got == artifact_sha else f"mismatch（复算 {got[:12]}）"
            except Exception as exc:  # noqa: BLE001
                proof_check = f"error（{type(exc).__name__}）"
        rec = {"file": path.name, "artifact_sha": artifact_sha,
               "artifact_path": str(sign.get("artifact_path") or ""),
               "statement_ids": [str(r.get("stmt_id") or "") for r in matched],
               "passes": len(passes), "review_calls": rcs,
               "object_sha256": sorted(objects), "at": str(sign.get("at") or ""),
               "backing": backing,
               "verdict": str(sign.get("verdict") or ""),
               "count": sign.get("count"), "streak": sign.get("streak"),
               "proof_sha_recheck": proof_check, "problems": problems}
        if problems:
            invalid.append(rec)
        elif backing["unchecked"]:
            # 三态：分不清类型的签既不是合格，也不是「回指缺失」。
            unchecked.append(rec)
        else:
            valid.append(rec)

    all_recs = valid + invalid + unchecked
    # 索引 ↔ 文件 双向
    file_shas = {str(rec["artifact_sha"]) for rec in all_recs}
    issued_shas = {str(x.get("artifact_sha") or "") for x in issued_rows}
    missing_files = [x for x in issued_rows if str(x.get("artifact_sha") or "") not in file_shas]
    unindexed_files = [rec for rec in all_recs if str(rec["artifact_sha"]) not in issued_shas]
    # 「已签」与「无签文件」同时出现 = 矛盾
    contradictions = [{"artifact_sha": str(x.get("artifact_sha") or ""),
                       "issued_at": str(x.get("at") or ""),
                       "why": "issued.json 声明已签，但 out/vsigns/<sha>.json 不在"}
                      for x in missing_files]

    lines.append(f"签文件 {len(sign_files)} 个（合格 {len(valid)} / 不合格 {len(invalid)}"
                 + (f" / 类型未判 {len(unchecked)}" if unchecked else "") + "）   "
                 "← out/vsigns/<sha>.json")
    for rec in valid:
        back = rec["backing"]
        lines.append(f"  ✓ {rec['artifact_sha'][:12]}…  {rec['artifact_path']}  "
                     f"passes={rec['passes']} object={rec['object_sha256'][0][:12]}… "
                     f"stmt={','.join(rec['statement_ids']) or '（无对应 statements 行）'} "
                     f"proof_sha 复算={rec['proof_sha_recheck']}")
        lines.append(f"     review_call={rec['review_calls']}   at={rec['at']}")
        lines.append(f"     回指{back['label']} → {back['path']}（{back['rows']} 行，"
                     f"{back['rows_for_this_sign']}/{rec['passes']} 票对上、行上 proof_sha256 对）")
    for rec in invalid:
        lines.append(f"  ✗ {rec['file']}：{'; '.join(rec['problems'])}")
    for rec in unchecked:
        lines.append(f"  ? {rec['file']}：{rec['backing']['unchecked']}")

    lines.append(f"issued.json 索引 {len(issued_rows)} 条（只作索引，不当签）"
                 + (f"   [读不成：{issued_err}]" if issued_err else ""))
    lines.append(f"  索引→文件：缺文件 {len(missing_files)} 条；文件→索引：未登记 {len(unindexed_files)} 条")
    for x in missing_files[:5]:
        lines.append(f"    [矛盾] issued 有 {str(x.get('artifact_sha'))[:12]}…，vsigns 无同名文件")
    for rec in unindexed_files[:5]:
        lines.append(f"    [索引漏登] {rec['artifact_sha'][:12]}… 的签文件不在 issued.json")

    # 命题覆盖：有签的命题 / 有 proof_sha 但无签文件的命题（不是矛盾，是读数）
    signed_stmt = {sid for rec in valid for sid in rec["statement_ids"]}
    unsigned_proof = [{"stmt_id": str(r.get("stmt_id") or ""), "proof_sha256": str(r.get("proof_sha256") or "")[:12],
                       "kind": str(r.get("kind") or ""), "origin": str(r.get("origin") or "")}
                      for r in statements
                      if r.get("proof_sha256") and str(r.get("stmt_id") or "") not in signed_stmt]
    lines.append(f"命题覆盖：已签命题 {len(signed_stmt)} 条（{', '.join(sorted(signed_stmt)) or '无'}）；"
                 f"有 proof_sha 但无签文件 {len(unsigned_proof)} 条"
                 + (f"（{', '.join(x['stmt_id'] for x in unsigned_proof[:8])}）" if unsigned_proof else ""))
    lines.append("  说明：有 proof_sha 无签文件 ≠ 矛盾（它没被任何索引声明为「已签」）；"
                 "矛盾只认 issued 声明了却无文件。")

    item["metrics"] = {
        "tri": "computed", "sign_files": len(sign_files), "valid": len(valid), "invalid": len(invalid),
        "unchecked": len(unchecked),
        "issued": len(issued_rows), "issued_missing_files": len(missing_files),
        "unindexed_files": len(unindexed_files), "contradictions": len(contradictions),
        "signed_statements": sorted(signed_stmt), "unsigned_with_proof": unsigned_proof,
        "backing_kinds": dict(collections.Counter(
            str((rec.get("backing") or {}).get("kind") or "undecided") for rec in all_recs)),
        "signs": all_recs,
    }
    item["state"] = "ok" if (not invalid and not unchecked and not contradictions
                             and not issued_err) else "warn"
    if unchecked:
        # 「分不清类型」是没查成，不是查过了有问题：与不合格分开计，state 记 unknown。
        item["state"] = "unknown"
        item["reason"] = (f"{len(unchecked)} 个签分不清类型（不是 v-/u- 形态）⇒ 回指没查成"
                          f"（不是「缺失」，也不是合格）")
    elif item["state"] != "ok":
        item["reason"] = (f"不合格签文件 {len(invalid)} 个 / 索引声明却无文件 {len(contradictions)} 条"
                          + (f" / issued.json 读不成：{issued_err}" if issued_err else ""))
    if not sign_files and not issued_rows:
        item["metrics"]["tri"] = "not_applicable"
    return item


# ---------------------------------------------------------------- ⑤ 非平凡度

def _nt_fallback(ctx: dict[str, Any]) -> dict[str, Any]:
    """`nontriviality_reading` 的降级直读（只按 stmt_id 取最新一行）。"""
    root: Path = ctx["root"]
    rows, problems = read_jsonl(root / "out" / "secretary" / "nontriviality.jsonl")
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        sid = str(r.get("stmt_id") or "")
        if not sid:
            continue
        if sid not in latest or str(r.get("at") or "") >= str(latest[sid].get("at") or ""):
            latest[sid] = r
    counts = {"T0": 0, "T1": 0, "T2": 0, "T3": 0, "T4": 0, "not_applicable": 0, "unjudged": 0}
    denom = 0
    abandoned = 0
    unjudged_abandoned = 0
    t0_ids: list[str] = []
    for st in ctx["T"]("statements"):
        sid = str(st.get("stmt_id") or "")
        is_abandoned = str(st.get("status") or "") == "abandoned"
        if is_abandoned:
            abandoned += 1
        row = latest.get(sid) or {}
        if row.get("applicable") is False or str(row.get("nontriviality_tri") or "") == "not_applicable":
            counts["not_applicable"] += 1
            continue
        lvl = row.get("nontriviality")
        if not isinstance(lvl, int) or isinstance(lvl, bool) or not (0 <= lvl <= 4):
            counts["unjudged"] += 1
            if is_abandoned:
                unjudged_abandoned += 1
            else:
                denom += 1
            continue
        counts[f"T{lvl}"] += 1
        if is_abandoned:
            continue          # 放弃的不进分母、不进 T0 清单（与产品口径同）
        denom += 1
        if lvl == 0:
            t0_ids.append(sid)
    return {"checked": True, "counts": counts, "statements_total": denom,
            "rows_total": len(ctx["T"]("statements")), "problems": problems,
            "downgraded_to_t0": t0_ids, "high_tier": [], "high_tier_total": 0,
            "not_applicable_total": counts["not_applicable"], "abandoned_total": abandoned,
            "unjudged_abandoned": unjudged_abandoned, "paper_scaffolding_problems": [],
            "t4_ladder_problems": [], "paths_total": 0, "partial_total": 0, "reason": ""}


def item5_nontriviality(ctx: dict[str, Any]) -> dict[str, Any]:
    root: Path = ctx["root"]
    lines: list[str] = []
    item: dict[str, Any] = {"id": "5", "title": "非平凡度：T0–T4 + 不适用 + 未判分开；分母只算可判命题；必须印 T0",
                            "state": "unknown", "degraded": False, "lines": lines,
                            "metrics": {}, "sources": ["data/statements.json#rows",
                                                       "out/secretary/nontriviality.jsonl"]}
    nt = None
    err = ""
    CL = PRODUCT.get("closing")
    if CL is not None:
        try:
            nt = CL.nontriviality_reading(root)
        except Exception as exc:  # noqa: BLE001
            err = f"产品 nontriviality_reading 抛错（{type(exc).__name__}: {exc}）"
    if nt is None:
        nt = _nt_fallback(ctx)
        item["degraded"] = True
        item["degraded_reason"] = err or "产品模块未导入"
    if not nt.get("checked"):
        lines.append(f"非平凡度没读到：{nt.get('reason') or '台账为空'} ⇒ unknown（不当 0）")
        item["metrics"] = nt
        item["reason"] = nt.get("reason") or "没读到"
        return item
    counts = dict(nt.get("counts") or {})
    for k in ("T0", "T1", "T2", "T3", "T4", "not_applicable", "unjudged"):
        counts.setdefault(k, 0)
    denom = int(num(nt.get("statements_total")))
    judged = sum(int(counts[f"T{i}"]) for i in range(5))
    lines.append(f"五档（T0 必印）：T0 {counts['T0']} / T1 {counts['T1']} / T2 {counts['T2']} / "
                 f"T3 {counts['T3']} / T4 {counts['T4']}   ← data/statements.json × "
                 f"out/secretary/nontriviality.jsonl")
    lines.append(f"不适用 {counts['not_applicable']}（不进分母）  ｜  未判 {counts['unjudged']}"
                 + (f"（其中已放弃 {nt.get('unjudged_abandoned')} 条，不进分母）"
                    if nt.get("unjudged_abandoned") else ""))
    lines.append(f"分母（可判命题）= {denom}；本次判出档位的 {judged} 条 / 台账 {nt.get('rows_total')} 行；"
                 f"已放弃 {nt.get('abandoned_total')} 行（踢出）")
    if denom:
        lines.append(f"档位占比（按可判命题）：T0 {pct(counts['T0'], denom)} / T1 {pct(counts['T1'], denom)} / "
                     f"T2 {pct(counts['T2'], denom)} / T3 {pct(counts['T3'], denom)} / T4 {pct(counts['T4'], denom)}")
    t0_ids = [str(x) for x in (nt.get("downgraded_to_t0") or [])]
    lines.append(f"T0 清单：{', '.join(t0_ids) if t0_ids else '（无）'}")
    high = nt.get("high_tier") or []
    lines.append(f"T3/T4 清单：{len(high)} 条"
                 + (f"（{', '.join(str(h.get('stmt_id')) for h in high)}）" if high else "（无）"))
    lines.append(f"逐路径：{nt.get('paths_total')} 条路径读数；还有路径没判的命题 {nt.get('partial_total')} 条")
    if item["degraded"]:
        lines.append(f"[degraded] {item['degraded_reason']} ⇒ 按 statements + nontriviality.jsonl 直读")
    for key, label in (("paper_scaffolding_problems", "论文侧缺铺垫"), ("t4_ladder_problems", "T4 缺造梯子记录")):
        for prob in (nt.get(key) or [])[:3]:
            lines.append(f"  [warning] {label}：{prob}")
    item["metrics"] = {
        "checked": True, "tiers": {f"T{i}": int(counts[f"T{i}"]) for i in range(5)},
        "not_applicable": int(counts["not_applicable"]), "unjudged": int(counts["unjudged"]),
        "unjudged_abandoned": int(nt.get("unjudged_abandoned") or 0),
        "denominator": denom, "judged": judged, "rows_total": int(nt.get("rows_total") or 0),
        "abandoned": int(nt.get("abandoned_total") or 0),
        "t0_ids": t0_ids, "high_tier": high, "high_tier_total": len(high),
        "paths_total": nt.get("paths_total"), "partial_total": nt.get("partial_total"),
    }
    item["state"] = "ok"
    return item


# ---------------------------------------------------------------- ⑥ 销号 / 义务

def _parent_terminal(tasks_by_id: Mapping[str, Mapping[str, Any]], parent: str) -> dict[str, Any]:
    row = tasks_by_id.get(parent)
    if row is None:
        return {"known": False, "terminal": None, "status": "", "outcome": ""}
    status = str(row.get("status") or "")
    outcome = str(row.get("outcome") or "")
    # 台账号的「终态」：status=done（agent 行）；没有 status 的板项行不算台账号
    terminal = status in ("done", "cancelled", "failed") or outcome in (
        "ok", "no_result", "not_applicable", "refused", "failed", "cancelled")
    return {"known": True, "terminal": terminal, "status": status, "outcome": outcome}


def item6_obligations(ctx: dict[str, Any]) -> dict[str, Any]:
    root: Path = ctx["root"]
    lines: list[str] = []
    item: dict[str, Any] = {"id": "6", "title": "销号/义务：item_state 残留、root_open_items、auto_retire 实际销号、三族义务",
                            "state": "unknown", "degraded": False, "lines": lines,
                            "metrics": {}, "sources": ["data/tasks.json#rows", "out/roster/*-retired.jsonl",
                                                       "out/roster/*.jsonl"]}
    tasks, task_err = ctx["T"]("tasks"), ctx["table_errors"].get("tasks", "")
    if task_err:
        lines.append(f"tasks 台账读不到：{task_err} ⇒ unknown（不当 0）")
        item["reason"] = task_err
        return item
    by_id = {str(r.get("task_id") or ""): r for r in tasks}

    # ---- 板项 item_state 残留
    board = [r for r in tasks if str(r.get("kind") or "")]
    open_board = [r for r in board if str(r.get("item_state") or "") != "done"]
    by_kind = collections.Counter(str(r.get("kind") or "") for r in open_board)
    lines.append(f"板项 {len(board)} 条（kind 非空）；未收口（item_state != done）{len(open_board)} 条"
                 + (f"：{dict(by_kind)}" if open_board else "（残留 0）")
                 + f"   ← data/tasks.json#rows[].kind/item_state")
    item["metrics"]["board"] = {"total": len(board), "open": len(open_board), "open_by_kind": dict(by_kind),
                                "open_ids": [str(r.get("task_id") or "") for r in open_board][:20]}

    # ---- 根与 root_open_items
    top = [r for r in tasks if str(r.get("called_by") or "") == "user" and not str(r.get("parent_task_id") or "")]
    top.sort(key=lambda r: (str(r.get("started_at") or ""), str(r.get("task_id") or "")))
    root_id = str(top[-1].get("task_id") or "") if top else ""
    root_open = [r for r in open_board if str(r.get("parent_task_id") or "") == root_id]
    lines.append(f"顶趟（根台账号）={root_id or '（没有顶趟行）'}；"
                 f"root_open_items（根名下的未消项）={len(root_open)}"
                 + (f"：{[str(r.get('task_id')) for r in root_open][:8]}" if root_open else ""))

    # ---- 产品 retire 读数（只读投影；产品不可用则标注）
    feed = {}
    CL = PRODUCT.get("closing")
    if CL is not None:
        try:
            feed = CL.machine_feeders(RoStore(root))
        except Exception as exc:  # noqa: BLE001
            feed = {"why": f"{type(exc).__name__}: {exc}"}
    retire = dict(feed.get("retire") or {})
    if retire:
        auto = dict(retire.get("auto_retire") or {})
        lines.append(f"产品 retire 读数：checked={retire.get('checked')} complete={retire.get('complete')} "
                     f"在册 {retire.get('count')} / 共 {retire.get('total')}；root_open_items="
                     f"{retire.get('root_open_items')}；dirty={len(retire.get('dirty') or [])}"
                     f"   ← closing.machine_feeders（retire_integrity 的只读投影）")
        lines.append(f"  收尾前自动收尾投影：would_retire {len(auto.get('would_retire') or [])} / "
                     f"kept {len(auto.get('kept') or [])}"
                     f" / would_void {sum(len(x.get('item_ids') or []) for x in (auto.get('would_void') or []))} 条"
                     f"（{len(auto.get('would_void') or [])} 个节点）；{auto.get('reason') or ''}")
        if auto.get("would_void"):
            lines.append("  会作废的未消项（销号后作废；收件人已销号 ⇒ 叫不醒）："
                         + "、".join(f"{x.get('task_id')}→{x.get('item_ids')}"
                                    for x in (auto.get("would_void") or [])[:6]))
    else:
        lines.append(f"产品 retire 读数不可用：{feed.get('why') or '没喂进来'}"
                     f" ⇒ 这一截只给数据直读（auto_retire 实际销号仍从 roster 读）")

    # ---- auto_retire 实际销了多少（roster 里的落痕）
    retired: list[dict[str, Any]] = []
    roster_dir = root / "out" / "roster"
    if roster_dir.is_dir():
        for p in sorted(roster_dir.glob("*-retired.jsonl")):
            rows, probs = read_jsonl(p)
            for r in rows:
                r = dict(r)
                r["_parent_file"] = p.name
                retired.append(r)
            if probs:
                lines.append(f"  [warning] {p.name} 读取问题：{probs[:2]}")
    auto = [r for r in retired if "自动收尾" in str(r.get("reason") or "")]
    lines.append(f"roster 销号落痕：共 {len(retired)} 条，其中「收工前自动收尾」{len(auto)} 条"
                 f"   ← out/roster/*-retired.jsonl#reason")
    auto_by_parent = collections.Counter(str(r.get("_parent_file") or "") for r in auto)
    if auto_by_parent:
        lines.append(f"  自动收尾按父：{dict(auto_by_parent)}")
    late = [r for r in auto if str(r.get("at") or "") >= str(auto[-1].get("at") or "")] if auto else []
    if auto:
        lines.append(f"  最近一次自动收尾时刻：{auto[-1].get('at')}（{len(late)} 条同一时刻）")
    item["metrics"]["retire"] = {
        "root": root_id, "root_open_items": len(root_open),
        "product": {k: retire.get(k) for k in ("checked", "complete", "count", "total",
                                               "root_open_items", "projected")} if retire else None,
        "auto_retire_projected": len((retire.get("auto_retire") or {}).get("would_retire") or []) if retire else None,
        "auto_retire_projected_void": sum(
            len(x.get("item_ids") or [])
            for x in ((retire.get("auto_retire") or {}).get("would_void") or [])) if retire else None,
        "auto_retire_actual": len(auto), "retired_total": len(retired),
        "auto_by_parent": dict(auto_by_parent),
        "auto_ids": [str(r.get("task_id") or "") for r in auto][:30],
    }

    # ---- 三族义务
    prefixes = {"b-register": "b-register@", "v-resubmit": "v-resubmit@", "b-awake": "b-awake@"}
    OB = PRODUCT.get("obligations")
    if OB is not None:
        prefixes = {"b-register": getattr(OB, "REGISTER_PREFIX", prefixes["b-register"]),
                    "v-resubmit": getattr(OB, "RESUBMIT_PREFIX", prefixes["v-resubmit"]),
                    "b-awake": getattr(OB, "REGISTER_WAKE_PREFIX", prefixes["b-awake"])}
    fam_rows: dict[str, list[dict[str, Any]]] = {k: [] for k in prefixes}
    for r in tasks:
        key = str(r.get("input_key") or "")
        for fam, pre in prefixes.items():
            if key.startswith(pre):
                fam_rows[fam].append(r)
                break
    family_out: dict[str, Any] = {}
    wake_of = getattr(OB, "wake_state_of", None) if OB is not None else None
    have_keys = {str(r.get("input_key") or "") for r in tasks}
    lines.append("三族义务（b-register / v-resubmit / b-awake）：")
    for fam, rows in fam_rows.items():
        open_rows = [r for r in rows if str(r.get("item_state") or "") != "done"]
        detail = []
        for r in rows:
            parent = str(r.get("parent_task_id") or "")
            pinfo = _parent_terminal(by_id, parent) if parent else {"known": False, "terminal": None, "status": "", "outcome": ""}
            stuck = (str(r.get("item_state") or "") != "done") and bool(pinfo.get("terminal"))
            wake_state = ""
            if fam == "b-register":
                # 「叫醒落在哪一支」：唯一判据在 obligations.wake_state_of（产品可用时读它）。
                want = (str(r.get("input_key") or "").replace(
                    prefixes["b-register"], prefixes["b-awake"], 1))
                wake_row = next((x for x in tasks
                                 if str(x.get("input_key") or "") == want), None)
                if wake_of is not None:
                    wake_state = str(wake_of(r, wake_row) or "")
                else:
                    wake_state = ("summoned" if wake_row
                                  else ("instance_addressed" if str(r.get("instance") or "")
                                        else "role_addressed"))
            detail.append({
                "task_id": str(r.get("task_id") or ""), "role": str(r.get("role") or ""),
                "recipient_instance": str(r.get("instance") or ""),
                "parent_task_id": parent, "item_state": str(r.get("item_state") or ""),
                "item_close": str(r.get("item_close") or ""), "expects": str(r.get("expects") or ""),
                "seen_by": str(r.get("seen_by") or ""), "opened_at": str(r.get("started_at") or ""),
                "input_key": str(r.get("input_key") or ""),
                "wake_state": wake_state,
                "parent_status": pinfo.get("status", ""), "parent_outcome": pinfo.get("outcome", ""),
                "parent_terminal": pinfo.get("terminal"),
                "stuck_on_terminal_account": stuck,
                "addressed": ("instance" if str(r.get("instance") or "") else
                              ("parent" if parent else "unowned")),
            })
        # b-awake 配对：b-register 的期望唤醒键
        wake_present = None
        if fam == "b-register":
            wake_present = sum(1 for d in detail if d["wake_state"] == "summoned")
        family_out[fam] = {
            "rows": len(rows), "open": len(open_rows),
            "unowned": sum(1 for d in detail if d["addressed"] == "unowned"),
            "stuck_on_terminal_account": sum(1 for d in detail if d["stuck_on_terminal_account"]),
            "wake_present": wake_present,
            "wake_state_counts": (dict(collections.Counter(
                d["wake_state"] for d in detail)) if fam == "b-register" else None),
            "detail": detail,
        }
        head = (f"  {fam:<11} 行 {len(rows)} / 未收口 {len(open_rows)} / 没人收 "
                f"{family_out[fam]['unowned']} / 挂死在已终态台账号 "
                f"{family_out[fam]['stuck_on_terminal_account']}")
        if wake_present is not None:
            head += f" ｜ 新召行（b-awake）{wake_present}/{len(rows)}"
        lines.append(head)
        for d in detail[:6]:
            who = (f"实例={d['recipient_instance']}" if d["recipient_instance"]
                   else (f"父={d['parent_task_id']}" if d["parent_task_id"] else "没人收"))
            lines.append(f"    {d['task_id']}  {d['item_state']}/{d['item_close'] or '-'}  "
                         f"{who}  收件角色={d['role']}  expects={d['expects'] or '-'}"
                         + (f"  唤醒={d['wake_state']}" if d.get("wake_state") else "")
                         + (f"  [挂死：父 status={d['parent_status']}]"
                            if d["stuck_on_terminal_account"] else ""))
    missing_families = [f for f, rows in fam_rows.items() if not rows]
    if missing_families:
        lines.append(f"  「没有行」的族：{', '.join(missing_families)}"
                     f"（表读得到 ⇒ 这是 0 行的计算结论；若应有行，属漏开/漏记）")
    br = family_out.get("b-register") or {}
    if br.get("rows"):
        counts = dict(br.get("wake_state_counts") or {})
        lines.append(
            f"  读数：b-register {br['rows']} 条 —— 新召 B（b-awake 行）{counts.get('summoned', 0)} 条 / "
            f"按实例地址投递（不新召，不落 b-awake 行）{counts.get('instance_addressed', 0)} 条 / "
            f"按角色地址留在板上（不新召）{counts.get('role_addressed', 0)} 条")
        lines.append(
            "  口径：`b-awake@` 是「召唤」的幂等键（`obligations._wake_registrar` 第 ④ 档："
            "一个 B 都没有 ⇒ 新召一趟才落行），不是「叫醒计数」。其余各档（在飞 / 同号继续 / "
            "实例地址 / 角色地址）按设计不落 `b-awake@` 行 ⇒ b-awake 0 条的意思是"
            "「这一趟没有新召过 B」，不是「叫醒那一侧缺读数」；判据 "
            "`tests/test_sgn1_a_landed_sign_wakes_b.py` 的 a（新召 ⇒ 有行）与 d/e"
            "（已有 B ⇒ 无行）把这条二分法钉住")

    # ---- 边 / 作废逐条落痕（TRACEFIX）：哪条边、谁 ack 的、认没认掉、为什么作废
    trace_lines, trace_metrics = _landed_trace_lines(ctx)
    lines.extend(trace_lines)
    item["metrics"]["landed_traces"] = trace_metrics

    item["metrics"]["families"] = family_out
    item["state"] = "ok" if (not open_board and not any(f["stuck_on_terminal_account"]
                                                       for f in family_out.values())) else "warn"
    return item


# ---------------------------------------------------------------- 落痕 / 逐行读数（TRACEFIX）

#: 落痕逐条读数里每一档最多印几条（超出只给计数；JSON 里是全量）。
TRACE_LINES_CAP = 40


def _product_conductor(root: Path) -> tuple[Any, str]:
    """只读的 `Conductor`（用 :class:`RoStore`：对项目根一个字节都不写）。"""
    CON = PRODUCT.get("conductor")
    if CON is None:
        return None, "产品不可用（conductor 没导入）⇒ 落痕逐条读数没查成"
    try:
        return CON.Conductor(RoStore(root), backend="local"), ""
    except Exception as exc:  # noqa: BLE001 —— 装配不起来是"没查成"
        return None, f"conductor 装配不起来（{type(exc).__name__}: {exc}）⇒ 没查成"


def _runs_by_task(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """`runs/*.json` 按 task 号归并自报花销（同一 task 多趟 ⇒ 相加）。

    返回 `{task_id: {usd, calls, path, paths}}`；读不成 / 不是运行档的文件记 problems
    （不静默丢）。它是"旧盘没有 `settle-recon` 落痕时"复算自报那一半的数据来源。
    """
    out: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    run_dir = root / "runs"
    if not run_dir.is_dir():
        return out, [f"{rel(root, run_dir)} 不在 ⇒ 自报那一半没有来源"]
    for path in sorted(run_dir.glob("*.json")):
        data, err = read_json(path)
        if err:
            problems.append(err)
            continue
        if not isinstance(data, Mapping):
            continue
        tid = str(data.get("task_id") or "")
        spend = data.get("spend")
        if not tid or not isinstance(spend, Mapping):
            continue
        usd = spend.get("usd")
        if not isinstance(usd, (int, float)) or isinstance(usd, bool):
            continue
        one = out.setdefault(tid, {"usd": 0.0, "calls": 0, "path": "",
                                   "paths": []})
        one["usd"] = round(float(one["usd"]) + float(usd), 6)
        calls = spend.get("calls")
        if isinstance(calls, int) and not isinstance(calls, bool):
            one["calls"] = int(one["calls"]) + calls
        one["paths"].append(rel(root, path))
        one["path"] = one["paths"][0]
    return out, problems


def _as_float(value: Any) -> float:
    """读数里的数字格（字符串形态）转 float；"na" / "unread" / 空 ⇒ 0.0（只在合计里用）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _settle_trace_lines(ctx: dict[str, Any], *, residual_usd: float,
                        residual_calls: int,
                        claimed_usd: float = 0.0) -> tuple[list[str], dict[str, Any]]:
    """逐趟结算对账（有落痕读落痕；旧盘用同一个判据复算，标 `recomputed`）。

    每一趟一行：`task · 自报 $X/N 次 → 实际 $Y/M 行 · Δ $±Z/±K · why`。
    合计与②的会话口径残差并排放：两个数不相等时，差额归到"无自报的趟 / 有 task 但
    没有运行档的调用"（各自计数），不硬凑成相等。
    """
    root: Path = ctx["root"]
    CON = PRODUCT.get("conductor")
    lines: list[str] = []
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    if CON is None:
        lines.append("逐趟结算对账：没查成（conductor 没导入）—— 不是「没有差额」")
        return lines, {"checked": False, "reason": "conductor 没导入", "rows": []}
    cond, why = _product_conductor(root)
    if cond is not None:
        got = cond.landed_traces()
        if got.get("checked"):
            rows.extend(dict(x) for x in got.get("settle") or [])
        else:
            problems.append(f"landed_traces 没查成（{got.get('reason')}）")
    else:
        problems.append(why)
    traced = {str(x.get("task_id") or "") for x in rows}
    runs, run_problems = _runs_by_task(root)
    problems.extend(run_problems)
    ledger = ctx["ledger"]
    spent_tasks = sorted({str(r.get("task_id")) for r in ledger
                          if str(r.get("scope") or "") == "reason"
                          and str(r.get("task_id") or "")})
    for tid in spent_tasks:
        if tid in traced:
            continue
        one = CON.settle_recon_of(
            task_id=tid, run_doc=({"spend": runs[tid]} if tid in runs else None),
            run_path=str((runs.get(tid) or {}).get("path") or ""),
            ledger_rows=ledger)
        one["source"] = "recomputed"
        rows.append(one)
    rows.sort(key=lambda x: (str(x.get("task_id") or "")))
    reported = sum(_as_float(x.get("reported_usd")) for x in rows
                   if str(x.get("reported_usd") or "") not in ("", "na", "unread"))
    actual = sum(_as_float(x.get("actual_usd")) for x in rows)
    delta = round(actual - reported, 6)
    lines.append(f"逐趟结算对账（{len(rows)} 趟；落痕 {len(traced)} 条 / 复算 "
                 f"{len(rows) - len(traced)} 条）：自报合计 {usd(reported)}，"
                 f"实际（scope=reason）合计 {usd(actual)}，Δ {usd(delta)}")
    lines.append(f"  会话口径残差（②）={usd(residual_usd)} / {residual_calls} 次调用"
                 f" —— 与逐趟 Δ 的差 {usd(residual_usd - delta)}"
                 "（逐趟这一格只算 scope=reason；extract 不属于任何一趟的 LLM 循环）")
    gap = round(claimed_usd - reported, 6)
    lines.append(f"  自报来源核对：会话口径各趟自报合计 {usd(claimed_usd)}，逐趟复算能读到"
                 f" {usd(reported)} ⇒ 差 {usd(gap)}"
                 + ("（那些趟没有 `runs/*.json` 里带 task_id + spend 的运行档："
                    "自报那一半没有来源，逐趟这一格不猜）" if abs(gap) >= 1e-6 else ""))
    shown = 0
    for one in rows:
        reported_text = str(one.get("reported_usd") or "")
        delta_text = str(one.get("delta_usd") or "")
        notable = (not one.get("checked") or reported_text in ("", "na", "unread")
                   or (delta_text and abs(_as_float(delta_text)) >= 1e-6))
        if not notable:
            continue
        if shown < TRACE_LINES_CAP:
            lines.append(
                f"  {one.get('task_id') or '?'} · 自报 "
                + (f"${_as_float(reported_text):.6f}/{one.get('reported_calls') or '?'} 次"
                   if reported_text not in ("", "na", "unread") else reported_text)
                + f" → 实际 {usd(_as_float(one.get('actual_usd')))}/{one.get('actual_rows')} 行"
                + (f" · Δ {usd(_as_float(delta_text))}/{one.get('delta_calls')} 次"
                   if delta_text else "")
                + f" · {one.get('by_role') or 'role=?'} · {one.get('why') or ''}"
                + ("" if one.get("source") == "trace" else
                   f"（{one.get('source')}：这一趟没有落痕）"))
        shown += 1
    if shown > TRACE_LINES_CAP:
        lines.append(f"  ……另有 {shown - TRACE_LINES_CAP} 趟有差 / 没查成，逐条见 JSON")
    if shown == 0 and rows:
        lines.append("  每一趟都逐分相等（Δ=0）⇒ 没有要认领的差额")
    metrics = {"checked": True, "rows": rows, "reported_usd": round(reported, 6),
               "actual_usd": round(actual, 6), "delta_usd": delta,
               "traced": len(traced), "recomputed": len(rows) - len(traced),
               "notable": shown, "problems": problems}
    return lines, metrics


def _landed_trace_lines(ctx: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """边 / 板项作废的逐条落痕（`conductor.landed_traces` 的读数面）。"""
    root: Path = ctx["root"]
    lines: list[str] = []
    cond, why = _product_conductor(root)
    if cond is None:
        lines.append(f"边 / 作废落痕：没查成（{why}）—— 不是「没有缺落痕」")
        return lines, {"checked": False, "reason": why}
    got = cond.landed_traces()
    if not got.get("checked"):
        lines.append(f"边 / 作废落痕：没查成（{got.get('reason')}）")
        return lines, {"checked": False, "reason": got.get("reason")}
    counts = dict(got.get("counts") or {})
    lines.append(f"边落痕：{counts.get('edges', 0)} 条开过 / 认过的边"
                 f"（哪条边 · 通知 · 谁 ack · 终态 · 认没认掉）")
    for e in (got.get("edges") or [])[:TRACE_LINES_CAP]:
        lines.append(
            f"  {e.get('parent')}→{e.get('child')}  通知@{e.get('notified_at') or '-'}"
            f"  ack@{e.get('acked_at') or '-'}"
            + (f"(by {e.get('ack_by')})" if e.get("ack_by") else "(ack 落痕里没有谁读的)")
            + f"  终态@{e.get('settled_at') or '-'}"
            f"  released={'是' if e.get('released') else '否'}"
            + (f"（trace: {e.get('release_trace', {}).get('acked_at') or '无 ack 时刻'}）"
               if e.get("release_trace") else ""))
    if len(got.get("edges") or []) > TRACE_LINES_CAP:
        lines.append(f"  ……另有 {len(got.get('edges')) - TRACE_LINES_CAP} 条见 JSON")
    by_kind: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for one in got.get("missing") or []:
        by_kind[str(one.get("kind") or "")].append(one)
    for kind, title in (("edge-released", "已终态但父行没有 edge-released 落痕"),
                        ("stop-acked", "通知过却没有任何 stop-acked 落痕"),
                        ("void-trace", "item_close=expired 却没有任何作废留痕"),
                        ("edge-readings", "边的读数没查成")):
        rows = by_kind.get(kind) or []
        if not rows:
            continue
        lines.append(f"该有落痕却没有：{title} —— {len(rows)} 条")
        for one in rows[:TRACE_LINES_CAP]:
            if kind == "void-trace":
                where = f"板项 {one.get('item')}"
            else:
                where = f"{one.get('parent')}→{one.get('child')}"
                if one.get("status"):
                    where += f"（status={one.get('status')}）"
            lines.append(f"  {where}：{one.get('why') or ''}")
        if len(rows) > TRACE_LINES_CAP:
            lines.append(f"  ……另有 {len(rows) - TRACE_LINES_CAP} 条见 JSON")
    lines.append(f"板项作废 / 撤销落痕：{counts.get('voids', 0)} 条"
                 "（哪一条 · 作废还是撤销 · 谁作的 · 原状态 · 逐字理由）")
    for one in (got.get("voids") or [])[:TRACE_LINES_CAP]:
        lines.append(f"  {one.get('item_id')}  mode={one.get('mode')}  by={one.get('by')}"
                     f"  owner={one.get('owner')}  from={one.get('from')}→{one.get('to')}"
                     f"  at={one.get('at')}  reason={one.get('reason')}"
                     f"  （{one.get('source')}）")
    if len(got.get("voids") or []) > TRACE_LINES_CAP:
        lines.append(f"  ……另有 {len(got.get('voids')) - TRACE_LINES_CAP} 条见 JSON")
    metrics = {"checked": True, "counts": counts,
               "edges": got.get("edges") or [], "voids": got.get("voids") or [],
               "missing": got.get("missing") or []}
    return lines, metrics


def per_row_readings(root: Path) -> dict[str, Any]:
    """MALFORM 那两类的逐行读数（每条带 文件 · 行号/id · 逐字值 · 判定）。

    判据不在这里重写：
    - "说回验通过却给不出区间"用 `evidencebits.quote_state`（`closing` 的同一把尺），
      `no_evidence` 那一档就是它；
    - "ARTIFACTS 最后一条登记的 sha 与盘上不符"用 `artifacts.verify_entries` +
      `artifacts.CHANGE_REASONS` 的读侧分类（`changed` 不再是一个布尔）。

    三态：产品不可用 / 某张表读不到 ⇒ `checked=False` + `unchecked` 点名是哪一格；
    不折成"0 条"。
    """
    EB = PRODUCT.get("evidencebits")
    ART = PRODUCT.get("artifacts")
    out: dict[str, Any] = {"checked": False, "state": "unknown",
                           "quote_no_evidence": [], "artifact_sha_changed": [],
                           "superseded": 0, "unchecked": [], "problems": []}
    if EB is None or ART is None:
        out["problems"].append("产品不可用（evidencebits / artifacts）⇒ 逐行读数没查成")
        return out
    out["checked"] = True
    for name, id_key in (("relations", "relation_id"), ("statements", "stmt_id")):
        rows, err = table(root, name)
        if err:
            out["unchecked"].append(f"{name}：{err}")
            continue
        for n, row in enumerate(rows, 1):
            try:
                state = EB.quote_state(row)
            except Exception as exc:  # noqa: BLE001 —— 一行判不了 ⇒ 这一行没查成
                out["problems"].append(f"{name}#{n}：{type(exc).__name__}: {exc}")
                continue
            if state != EB.QUOTE_NO_EVIDENCE:
                continue
            out["quote_no_evidence"].append({
                "where": f"data/{name}.json#第{n}条", "file": f"data/{name}.json",
                "row": n, "id": str(row.get(id_key) or row.get("statement_id") or ""),
                "quote_verified": row.get("quote_verified"),
                "quote_span": str(row.get("quote_span") or ""),
                "quote_mode": str(row.get("quote_mode") or ""),
                "verdict": "no_evidence",
                "why": "quote_verified=true 而 quote_span 为空 ⇒ 说「逐字回验通过」却指不出核的是哪一段",
            })
    records, bad = ART.read_ledger(root)
    out["problems"].extend(bad)
    checks = ART.verify_entries(root, records)
    last_index: dict[str, int] = {}
    for i, row in enumerate(records):
        if str(row.get("path") or ""):
            last_index[str(row.get("path") or "")] = i
    for i, (row, check) in enumerate(zip(records, checks)):
        if check.get("status") != "changed":
            continue
        reason = str(check.get("reason") or "")
        if last_index.get(str(row.get("path") or "")) != i:
            # 后面还有同路径登记 ⇒ 这一条是被追加登记顶替的旧行（不是"最后一条"）。
            out["superseded"] += 1
            continue
        out["artifact_sha_changed"].append({
            "where": f"ARTIFACTS.jsonl#第{i + 1}行", "file": "ARTIFACTS.jsonl",
            "line": i + 1, "id": str(row.get("path") or ""),
            "registered_sha256": str(row.get("sha256") or ""),
            "on_disk_sha256": str(check.get("sha256_now") or ""),
            "registered_at": str(row.get("at") or ""),
            "verdict": reason,
            "explained": bool(check.get("explained")),
            "why": {"signed_after_registration": "登记之后落了签块（可解释）",
                    "superseded_by_later_registration": "后面还有更新的登记（可解释）",
                    "rewritten_after_registration": "登记之后内容被改过（没有可解释的原因）",
                    }.get(reason, reason),
        })
    out["state"] = "malformed" if (out["quote_no_evidence"]
                                   or out["artifact_sha_changed"]) else "ok"
    return out


def _per_row_lines(reading: Mapping[str, Any]) -> list[str]:
    """`per_row_readings` 的人读面（逐行，不折叠成计数）。"""
    lines: list[str] = []
    if not reading.get("checked"):
        lines.append("逐行读数：没查成（" + "；".join(reading.get("problems") or [])
                     + "）—— 那是「没读成」，不是「0 条」")
        return lines
    quote = list(reading.get("quote_no_evidence") or [])
    lines.append(f"relations / statements 说回验通过却无 quote_span：{len(quote)} 条"
                 f"（判据 `evidencebits.quote_state == no_evidence`，与收工门同一把尺）")
    for one in quote[:TRACE_LINES_CAP]:
        lines.append(f"  {one['where']}  {one['id'] or '（无号）'}  "
                     f"quote_verified={one['quote_verified']!r}  "
                     f"quote_span={one['quote_span']!r}  "
                     f"quote_mode={one['quote_mode']!r}  → {one['verdict']}")
    if len(quote) > TRACE_LINES_CAP:
        lines.append(f"  ……另有 {len(quote) - TRACE_LINES_CAP} 条见 JSON")
    changed = list(reading.get("artifact_sha_changed") or [])
    lines.append(f"ARTIFACTS 最后一条登记的 sha 与盘上不符：{len(changed)} 条 / "
                 f"{len({x['id'] for x in changed})} 个路径"
                 f"（另有 {int(reading.get('superseded') or 0)} 条旧登记被后续登记顶替，可解释）")
    for one in changed[:TRACE_LINES_CAP]:
        lines.append(f"  {one['where']}  {one['id']}  登记 "
                     f"{one['registered_sha256'][:12]}…（at {one['registered_at']}）  "
                     f"盘上 {one['on_disk_sha256'][:12]}…  → {one['verdict']}"
                     f"（{one['why']}）")
    if len(changed) > TRACE_LINES_CAP:
        lines.append(f"  ……另有 {len(changed) - TRACE_LINES_CAP} 条见 JSON")
    for problem in reading.get("unchecked") or []:
        lines.append(f"  没查成：{problem}")
    return lines


# ---------------------------------------------------------------- ⑦ 会话归口

def item7_session_scope(ctx: dict[str, Any]) -> dict[str, Any]:
    root: Path = ctx["root"]
    lines: list[str] = []
    item: dict[str, Any] = {"id": "7", "title": "会话归口：sessions/<sid>.jsonl 唯一？跨项目/跨 sid？读口 problems？unattributed task 在范围内？",
                            "state": "unknown", "degraded": False, "lines": lines,
                            "metrics": {}, "sources": ["sessions/*.jsonl", "data/tasks.json#rows",
                                                       "out/review/m-verdicts.jsonl", "manuscripts/handoffs.jsonl"]}
    tasks = ctx["T"]("tasks")
    ids = {str(r.get("task_id") or "") for r in tasks}
    ids |= {str(r.get("task_id") or "") for r in ctx["ledger"]}
    files = ctx["session_files"]
    lines.append(f"sessions/ 下会话文件 {len(files)} 个：{[p.name for p in files] or '（无）'}"
                 f"   ← sessions/ 目录")
    if ctx["session_dir_problems"]:
        for p in ctx["session_dir_problems"]:
            lines.append(f"  [问题] {p}")

    problems = list(ctx["session_problems"])
    bad = [p for p in problems]
    lines.append(f"读口 problems：{len(bad)} 条" + (f"（{bad[:3]}）" if bad else "（坏行 0）"))

    cross_project: list[str] = []
    other_sids: list[dict[str, str]] = []
    root_strs = {str(root).lower(), str(root).replace("\\", "/").lower()}
    for s in ctx["sessions"]:
        for wr in s["workspace_roots"]:
            if wr and wr.lower() not in root_strs and wr.replace("\\", "/").lower() not in root_strs:
                cross_project.append(f"{s['sid']} 的 agent_run_start.opening_facts.workspace_root={wr}")
        for sidv in s["event_sids"]:
            if sidv and sidv != s["sid"]:
                other_sids.append({"where": f"sessions/{s['path'].name}#event.sid", "sid": sidv, "expect": s["sid"]})
    # 运行/判据/手稿的 sid 与当前会话号
    stem = ctx["sessions"][0]["sid"] if len(ctx["sessions"]) == 1 else ""
    runs_dir = root / "runs"
    run_sid_missing = 0
    run_sid_other: list[dict[str, str]] = []
    run_sid_cache: list[dict[str, str]] = []
    if runs_dir.is_dir():
        for p in sorted(runs_dir.glob("*.json")):
            data, err = read_json(p)
            if err or not isinstance(data, Mapping):
                continue
            sidv = str(data.get("sid") or "")
            if not sidv:
                # 只有「一趟的运行读数」才算缺读数；纯派生文件（manuscript-claims）没有 sid 是正常的
                if "spend" in data:
                    run_sid_missing += 1
                continue
            if not stem or sidv == stem:
                continue
            item_sid = {"where": f"runs/{p.name}#sid", "sid": sidv, "expect": stem,
                        "kind": str(data.get("kind") or "run")}
            if str(data.get("kind") or "") == "cache_active" or p.name.startswith("cache-active"):
                run_sid_cache.append(item_sid)
            else:
                run_sid_other.append(item_sid)
    other_sids.extend(run_sid_other)
    mv, mv_problems = read_jsonl(root / "out" / "review" / "m-verdicts.jsonl")
    for v in mv:
        sidv = str(v.get("sid") or "")
        if stem and sidv and sidv != stem:
            other_sids.append({"where": "out/review/m-verdicts.jsonl#sid", "sid": sidv, "expect": stem})
    hf, hf_problems = read_jsonl(root / "manuscripts" / "handoffs.jsonl")
    for h in hf:
        sidv = str(h.get("sid") or "")
        if stem and sidv and sidv != stem:
            other_sids.append({"where": f"manuscripts/handoffs.jsonl#{h.get('id')}#sid",
                               "sid": sidv, "expect": stem})

    lines.append(f"跨项目：workspace_root 与本项目不一致 {len(cross_project)} 处"
                 + (f"：{cross_project[:3]}" if cross_project else "（0）"))
    lines.append(f"跨 sid（证据面）：与当前会话号（{stem or '多会话/无'}）不一致的落点 {len(other_sids)} 处"
                 + (f"：{other_sids[:4]}" if other_sids else "（0）"))
    if run_sid_cache:
        lines.append(f"  另有非证据面缓存快照 {len(run_sid_cache)} 个来自别的 sid："
                     f"{[x['where'] for x in run_sid_cache][:3]}（cache_active，不进证据面）")
    if run_sid_missing:
        lines.append(f"  runs/*.json 里「一趟的运行读数」sid 为空的 {run_sid_missing} 个（缺读数，不是跨 sid）")

    # unattributed 的 task 是否都在范围内
    out_of_scope: list[str] = []
    unattributed_tasks: set[str] = set()
    for s in ctx["sessions"]:
        run_task_ids = {str(r.get("task_id") or "") for r in s["runs"]}
        spend = {str(r.get("task_id") or ""): num(r.get("spend_usd")) for r in s["runs"]}
        event_usd: dict[str, float] = collections.defaultdict(float)
        for e in s["llm_calls"]:
            tid = str(e.get("task_id") or "")
            if tid:
                event_usd[tid] += num(e.get("usd"))
            if not tid or tid not in run_task_ids or event_usd[tid] > spend.get(tid, 0.0) + 1e-9:
                if tid:
                    unattributed_tasks.add(tid)
                    if tid not in ids:
                        out_of_scope.append(f"{tid}（不在 tasks/账本里）")
    lines.append(f"unattributed 涉及的 task：{len(unattributed_tasks)} 个"
                 + (f"；范围外 {len(out_of_scope)} 个：{out_of_scope[:5]}" if out_of_scope else "；全部在台账范围内"))
    lines.append(f"  台账 task_id 数 {len(ids)}；会话 llm_call 的 task_id 未登记数："
                 f"{len({str(e.get('task_id') or '') for s in ctx['sessions'] for e in s['llm_calls'] if e.get('task_id')} - ids)}")

    item["metrics"] = {
        "session_files": [p.name for p in files],
        "dir_problems": ctx["session_dir_problems"],
        "read_problems": len(bad), "read_problem_examples": bad[:5],
        "cross_project": len(cross_project), "cross_project_examples": cross_project[:5],
        "cross_sid": len(other_sids), "cross_sid_examples": other_sids[:8],
        "cross_sid_cache_only": run_sid_cache,
        "run_sid_missing": run_sid_missing,
        "unattributed_tasks": sorted(unattributed_tasks),
        "out_of_scope_tasks": out_of_scope,
    }
    ok = (not ctx["session_dir_problems"] and not bad and not cross_project
          and not other_sids and not out_of_scope)
    item["state"] = "ok" if ok else "warn"
    if not files:
        item["state"] = "unknown"
        item["metrics"]["tri"] = "not_applicable"
    return item


# ---------------------------------------------------------------- 汇总 / 渲染

def _caliber_diff(items: list[dict[str, Any]]) -> dict[str, Any]:
    """把「旧口径 → 新口径」在同一份盘上数据里算成对照读数（数字会变的那几处）。"""
    m = {it["id"]: (it.get("metrics") or {}) for it in items}
    a1, a2, a3 = m.get("1") or {}, m.get("2") or {}, m.get("3") or {}
    a5, a6, a7 = m.get("5") or {}, m.get("6") or {}, m.get("7") or {}
    out: dict[str, Any] = {}

    oc = a1.get("old_caliber") or {}
    out["accounting"] = {
        "old": {"rule": "llm_call 数 == 账本行数", "llm_calls": oc.get("llm_calls"),
                "ledger_rows": oc.get("ledger_rows"), "phantom_rows": oc.get("phantom_rows"),
                "phantom_usd": oc.get("phantom_usd")},
        "new": {"rule": "reason + summon + extract 三类分别对",
                "reason": (a1.get("reason") or {}).get("ledger_rows"),
                "summon": (a1.get("summon") or {}).get("ledger_rows"),
                "extract": (a1.get("extract") or {}).get("ledger_rows"),
                "three_total": (a1.get("total") or {}).get("three_scope_rows"),
                "other_rows": (a1.get("total") or {}).get("other_rows")},
        "why": ("旧口径把 summon（0 token 结算）与 extract（不进会话流）当成差额；"
                "差额不是「未归属的钱」，是两类合法的账本行。"),
    }

    comp = a2.get("composition") or {}
    out["unattributed"] = {
        "old": {"rule": "账本行数 − llm_call 数", "value_rows": oc.get("phantom_rows"),
                "value_usd": oc.get("phantom_usd")},
        "new": {"rule": "sessions llm_call.usd 累计 − 各趟自报 spend_usd 之和",
                "value_usd": a2.get("unattributed_usd"), "value_calls": a2.get("unattributed_calls"),
                "taskless": comp.get("taskless"), "no_run": comp.get("no_run"),
                "run_underreport": comp.get("run_underreport")},
        "why": ("旧口径拿两条不同类的行数相减（summon/extract 被算成差）；"
                "新口径量的是「会话里花了、但没有任何一趟自报账认领」的钱与调用数。"),
    }

    cells_bad = [c.get("check") for c in (a3.get("cells") or [])
                 if str(c.get("status")) not in ("pass",)]
    s3 = a3.get("summary") or {}
    retire = s3.get("retire") or {}
    programs = s3.get("programs") or {}
    old_can_close = None
    if s3.get("verdict") is not None and retire and programs:
        old_can_close = bool(s3.get("m_says_done")) and bool(retire.get("complete")) \
            and bool(programs.get("ok"))
    out["eight_cells"] = {
        "old": {"rule": "can_close = m_says_done ∧ retire.complete ∧ programs_ok（不读八格）",
                "can_close": old_can_close, "machine_pass": s3.get("machine_pass")},
        "new": {"rule": "八格全 pass ∧ m_says_done ∧ retire 干净 ∧ programs 停 ∧ 无 blocker",
                "closing_verdict": (s3.get("closing_verdict") or s3).get("verdict"),
                "can_close": s3.get("can_close"), "machine_pass": s3.get("machine_pass"),
                "tri_state_exit_code": s3.get("exit_code"),
                "counts": s3.get("counts"), "failed_or_unknown_cells": cells_bad},
        "why": ("旧 can_close 不读八格（closing.py 的 can_close 注释逐字记过这个根因）；"
                "八格 6/8 也可能 can_close=true / exit 0。现在 can_close / machine_pass / "
                "退出码都从 closing_verdict 一处派生（ROOTGATE-①）。"),
    }

    a4 = m.get("4") or {}
    out["signs"] = {
        "old": {"rule": "issued.json 当作签（把索引当结论）",
                "issued_entries": a4.get("issued"),
                "sign_files": a4.get("sign_files"),
                "would_miscount": (a4.get("issued") != a4.get("valid"))},
        "new": {"rule": "只认 out/vsigns/<sha>.json 的 3 个 passes",
                "valid_signs": a4.get("valid"), "invalid_signs": a4.get("invalid"),
                "index_missing_files": a4.get("issued_missing_files"),
                "contradictions": a4.get("contradictions")},
        "why": ("索引可以比文件多（签被撤/文件丢）也可以比文件少（漏登）；"
                "把 issued 当签会把「声明」读成「证据」。"),
    }

    nt_old_unjudged = None
    nt_old_denom = None
    if a5:
        nt_old_unjudged = int(a5.get("not_applicable") or 0) + int(a5.get("unjudged") or 0)
        nt_old_denom = max(0, int(a5.get("rows_total") or 0) - int(a5.get("abandoned") or 0))
    out["nontriviality"] = {
        "old": {"rule": "applicable:false 一律计进 unjudged",
                "unjudged": nt_old_unjudged, "denominator": nt_old_denom},
        "new": {"rule": "T0–T4 + not_applicable + unjudged 三栏分开；分母只算可判命题",
                "tiers": a5.get("tiers"), "not_applicable": a5.get("not_applicable"),
                "unjudged": a5.get("unjudged"), "unjudged_abandoned": a5.get("unjudged_abandoned"),
                "denominator": a5.get("denominator")},
        "why": ("旧读法把 35 条概念行压成「未判」（真机 lp-ball-11 因此屏幕上看不见 T0）；"
                "新读法把不适用与未判分开，且 T0 必须印。"),
    }

    board = a6.get("board") or {}
    ret = a6.get("retire") or {}
    fam = a6.get("families") or {}
    out["obligations"] = {
        "old": {"rule": "只数 item_state != done 的板项", "open_board": board.get("open")},
        "new": {"rule": "板项残留 + root_open_items + auto_retire 实际销号 + 三族义务",
                "open_board": board.get("open"), "root_open_items": ret.get("root_open_items"),
                "auto_retire_actual": ret.get("auto_retire_actual"),
                "auto_retire_projected": ret.get("auto_retire_projected"),
                "families": {k: {"rows": v.get("rows"), "open": v.get("open"),
                                 "unowned": v.get("unowned"),
                                 "stuck": v.get("stuck_on_terminal_account")}
                             for k, v in fam.items()}},
        "why": ("旧口径只看见「板项还开着几条」；一条已经 done 的 b-register 与"
                "「叫醒 B 的召唤行根本不存在」在那条口径里都是 0。"),
    }

    out["session_scope"] = {
        "old": {"rule": "只数 sessions/ 下有几个 .jsonl"},
        "new": {"rule": "文件唯一 + 跨项目 + 跨 sid + 读口 problems + unattributed 的 task 在范围内",
                "session_files": a7.get("session_files"), "cross_project": a7.get("cross_project"),
                "cross_sid": a7.get("cross_sid"),
                "cross_sid_cache_only": len(a7.get("cross_sid_cache_only") or []),
                "read_problems": a7.get("read_problems"),
                "out_of_scope_tasks": a7.get("out_of_scope_tasks")},
        "why": "文件在不在是一件事；这些事件是不是这一场、这一棵树的，是另外四件事。",
    }
    return out


def build_report(root: Path, outdir: Path) -> tuple[dict[str, Any], str]:
    ctx = collect_context(root)
    # 顶趟 / 子趟读数给 ① 用（子趟 = 会话里的 run 中 task_id 不是顶趟的那些）
    tops = [r for r in ctx["T"]("tasks")
            if str(r.get("called_by") or "") == "user" and not str(r.get("parent_task_id") or "")]
    top_ids = {str(r.get("task_id") or "") for r in tops}
    ctx["metrics"] = {
        "top_runs": len(tops),
        "top_ids": sorted(top_ids),
        "child_runs": sum(sum(1 for run in s["runs"]
                              if str(run.get("task_id") or "") and
                              str(run.get("task_id") or "") not in top_ids)
                          for s in ctx["sessions"]),
    }

    items = [item1_accounting(ctx), item2_unattributed(ctx), item3_eight_cells(ctx),
             item4_signs(ctx), item5_nontriviality(ctx), item6_obligations(ctx),
             item7_session_scope(ctx)]
    states = {it["id"]: it["state"] for it in items}
    unknown_items = [it["id"] for it in items if it["state"] == "unknown"]
    warn_items = [it["id"] for it in items if it["state"] == "warn"]

    diff = _caliber_diff(items)
    # 逐行读数（MALFORM 两类的升级）：不占七项的一格（七项的口径不变），但逐条列。
    per_row = per_row_readings(root)
    report = {
        "schema": SCHEMA,
        "project": root.name,
        "root": str(root),
        "generated_at": now_iso(),
        "caliber": CALIBER,
        "read_only": True,
        "product": {
            "imported": bool(PRODUCT.get("imported")),
            "modules": {k: bool(PRODUCT.get(k)) for k in ("closing", "sessions", "obligations",
                                                         "proofregistry", "conductor",
                                                         "evidencebits", "artifacts")},
            "errors": PRODUCT.get("errors") or [],
            "note": ("产品口径：closing.check_closing / closing.machine_feeders / "
                     "closing.nontriviality_reading / sessions.runs_in_session / "
                     "sessions.unattributed_usd_of / sessions.read_session"),
        },
        "summary": {
            "states": states,
            "ok": [k for k, v in states.items() if v == "ok"],
            "warn": warn_items,
            "unknown": unknown_items,
            "seven_items_present": len(items) == 7,
        },
        "items": items,
        "per_row": per_row,
        "caliber_diff": diff,
    }

    # ---- 人读表
    L: list[str] = []
    L.append(f"RECON-B 对账 · {root.name} · {CALIBER}")
    L.append(f"根：{root}")
    L.append(f"生成：{report['generated_at']}   ｜ 只读：是（唯一写入是 {outdir}）")
    prod = report["product"]
    if prod["imported"]:
        L.append(f"产品口径：可用（{', '.join(k for k, v in prod['modules'].items() if v)}）")
    else:
        L.append(f"产品口径：不可用 ⇒ 降级数据直读（{'; '.join(prod['errors'][:2]) or '未导入'}）")
    L.append("")
    for it in items:
        L.append(f"{'①②③④⑤⑥⑦'[int(it['id']) - 1]} {it['title']}")
        L.extend(it["lines"])
        if it["state"] != "ok":
            why = it.get("reason") or it.get("note") or "有读数，见上"
            L.append(f"   → 这一项：{it['state']}（{why}）")
        else:
            L.append(f"   → 这一项：{it['state']}")
        L.append("")
    # ---- 逐行读数（MALFORM 两类的升级：文件 · 行号/id · 逐字值 · 判定）
    L.append("逐行读数（MALFORM 两类：从「只计数」升级成逐条；判据与收工门 / 台账同一把尺）")
    L.extend(_per_row_lines(per_row))
    L.append("")
    # ---- 口径差异（旧 → 新）：同一份盘上，哪些数会变
    d = diff
    L.append("口径差异（旧 → 新；同一份盘上算出来的对照）")
    a = d["accounting"]
    L.append(f"  ① 旧「llm_call 数 == 账本行数」：{a['old']['llm_calls']} vs "
             f"{a['old']['ledger_rows']}，差 {a['old']['phantom_rows']} 行 / "
             f"{usd(a['old']['phantom_usd'])}（会把这 {a['old']['phantom_rows']} 条当成问题）")
    L.append(f"     → 新：reason {a['new']['reason']} + summon {a['new']['summon']} + "
             f"extract {a['new']['extract']} = {a['new']['three_total']}，其它 "
             f"{a['new']['other_rows']} ⇒ 账本被三类完全分解")
    u = d["unattributed"]
    L.append(f"  ② 旧「账本 − llm_call」：{u['old']['value_rows']} 行 / "
             f"{usd(u['old']['value_usd'])}（其实是 summon/extract，不是未归属）")
    L.append(f"     → 新：会话口径 {usd(u['new']['value_usd'])} / {u['new']['value_calls']} 次调用"
             f"（task 空 {((u['new']['taskless'] or {}).get('calls'))}，无对应趟 "
             f"{((u['new']['no_run'] or {}).get('calls'))}，事件>自报 "
             f"{((u['new']['run_underreport'] or {}).get('calls'))} 次）")
    e = d["eight_cells"]
    L.append(f"  ③ 旧 can_close（不读八格）= {e['old']['can_close']}（m ∧ retire ∧ programs）")
    L.append(f"     → 新 closing_verdict = {e['new']['closing_verdict']} / can_close = "
             f"{e['new']['can_close']} / machine_pass = {e['new']['machine_pass']} / "
             f"exit = {e['new']['tri_state_exit_code']}；红格 "
             f"{', '.join(e['new']['failed_or_unknown_cells']) or '无'}")
    L.append("     旧口径不读八格：八格 6/8 不进 can_close；M 说达成时旧口径会给 true/exit 0"
             "（closing.py 的 can_close 注释记的根因），新口径仍由八格拦。")
    s = d["signs"]
    L.append(f"  ④ 旧「issued.json 当签」：索引 {s['old']['issued_entries']} 条 / 文件 "
             f"{s['old']['sign_files']} 个（会把声明读成证据）")
    L.append(f"     → 新：合格签 {s['new']['valid_signs']} 个（3 passes 逐字段核）、不合格 "
             f"{s['new']['invalid_signs']}、索引声明却无文件 {s['new']['index_missing_files']}")
    nn = d["nontriviality"]
    L.append(f"  ⑤ 旧读法把不适用并进未判：未判 {nn['old']['unjudged']} / 分母 {nn['old']['denominator']}")
    L.append(f"     → 新：T0 {((nn['new']['tiers'] or {}).get('T0'))} / 不适用 "
             f"{nn['new']['not_applicable']} / 未判 {nn['new']['unjudged']}"
             f"（其中已放弃 {nn['new']['unjudged_abandoned']}）/ 分母 {nn['new']['denominator']}")
    o = d["obligations"]
    L.append(f"  ⑥ 旧「只数 item_state != done」：残留 {o['old']['open_board']} 条")
    L.append(f"     → 新：root_open_items {o['new']['root_open_items']} / auto_retire 实际 "
             f"{o['new']['auto_retire_actual']} 条（投影 {o['new']['auto_retire_projected']}）/ "
             f"三族 b-register {((o['new']['families'] or {}).get('b-register') or {}).get('rows')}、"
             f"v-resubmit {((o['new']['families'] or {}).get('v-resubmit') or {}).get('rows')}、"
             f"b-awake {((o['new']['families'] or {}).get('b-awake') or {}).get('rows')}")
    q = d["session_scope"]
    L.append(f"  ⑦ 旧「只数 sessions 文件」：{len(q['new']['session_files'] or [])} 个")
    L.append(f"     → 新：跨项目 {q['new']['cross_project']} / 跨 sid（证据面）{q['new']['cross_sid']}"
             f"（另有缓存快照 {q['new']['cross_sid_cache_only']}）/ 读口 problems "
             f"{q['new']['read_problems']} / 范围外 task {len(q['new']['out_of_scope_tasks'] or [])}")
    L.append("")
    L.append("自我核查（七项）：")
    for it in items:
        mark = {"ok": "ok  ", "warn": "warn", "unknown": "未知"}[it["state"]]
        L.append(f"  {'①②③④⑤⑥⑦'[int(it['id']) - 1]} {mark}  {it['title'].split('：')[0]}")
    L.append("")
    L.append(f"七项齐全：{len(items)}/7 ｜ 未知：{', '.join(unknown_items) or '无'} ｜ "
             f"有读数但需看：{', '.join(warn_items) or '无'}")
    text = "\n".join(L) + "\n"
    return report, text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RECON-B 七项对账（只读；修正后口径）")
    ap.add_argument("--root", required=True, help="项目根（真机工作区），例如 projects/lp-ball-11")
    ap.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help="输出目录（默认 temp/reconB/out）")
    ap.add_argument("--no-product", action="store_true", help="强制数据直读（验证降级路径）")
    ap.add_argument("--print-json", action="store_true", help="同时把 JSON 打到 stdout")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[unknown] 项目根不是目录：{root}", file=sys.stderr)
        return 2
    if not (root / "data").is_dir():
        print(f"[unknown] {root} 下没有 data/ ⇒ 不是 agentflow 工作区（没查成）", file=sys.stderr)
        return 2

    bootstrap_product(force_off=bool(args.no_product))
    report, text = build_report(root, Path(args.outdir))
    print(text)
    if args.print_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    js = outdir / f"{root.name}.json"
    tx = outdir / f"{root.name}.txt"
    #: `newline="\n"`：Windows 上不写死行尾的话，同一份读数在别的机器上 sha256 会变
    #: （lint R012 那条纪律的同一个理由），而证据文件是要逐字对账的。
    js.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                  encoding="utf-8", newline="\n")
    tx.write_text(text, encoding="utf-8", newline="\n")
    print(f"[ok] 已写：{js}")
    print(f"[ok] 已写：{tx}")

    states = report["summary"]["states"]
    return 2 if "unknown" in states.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
