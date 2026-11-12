# -*- coding: utf-8 -*-
"""`agentflow verify-audit`：只读的证明台账读数口（零模型、零写盘）。

它回答四个问题（四张表）：
1. 每条证明的票数：最近那一趟送审里，从 `review_pass=1` 起连续
   :func:`agentflow.verifications.is_a_vote` 为真的轮数；停在哪一行、停因是哪一类
   （`math` / `procedural` / `style` / `contract` / `report_gap`）。
2. `report_gap` 清单：「没记录反例构造尝试」不算缺陷，这里逐条列出（哪条命题、
   哪一行、什么理由），让"V 的报告缺了什么"可见。
3. `legacy_*` 三类计数：老行没有 `secretary_judge.fault_kind` 这一格，读侧按确定性
   规则推定（`legacy_math_evidence` / `legacy_shape` / `legacy_default`）；三类各多少
   条必须能一眼读出来，否则"哪些行是被推定的"就不可复核。
4. 同一 sha 同一 review_call 里 clean → fault 的逐条点名：同一份正文、同一趟调用，
   前一转 clean、后一转 fault，只差回复里的半句话。它不改任何判定，只让"这条轴
   测的是什么"在读数里显形。

读 `<root>/verifications/*.jsonl`（唯一正本，`verifications.list_verifications`）；
一个字节都不写 —— 不建目录、不加锁、不写报告、不碰台账。退出码：`0` 查过了（含"0 行"）
/ `2` 没查成（工作区不在盘上 / 台账有读不出来的行）。`2` 不是"没有问题"：它是"这一格
没查成"，与 `0` 必须分开（三态纪律）。

跑法：

    python scripts/verify_audit.py --root projects/paper-rewrite-98b
    python scripts/verify_audit.py --root projects/paper-rewrite-98b --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping, Sequence

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import verifications as VR  # noqa: E402

EXIT_OK = 0
EXIT_UNKNOWN = 2


def _statement_of(row: Mapping[str, Any]) -> str:
    """这一行属于哪条命题（正名 `stmt_id`，老行读 `statement_id`）。"""
    return str(row.get("stmt_id") or row.get("statement_id") or "")


def _pass_no(row: Mapping[str, Any]) -> int:
    """`review_pass` 归一成整数；没有 / 读不出 ⇒ 0（老行没有轮次标记）。"""
    try:
        return int(row.get("review_pass") or 0)
    except (TypeError, ValueError):
        return 0


def _latest_call_rows(group: Sequence[Mapping[str, Any]],
                      ) -> tuple[list[Mapping[str, Any]], str]:
    """这一份证明的"最近一趟送审"：最后一个非空 `review_call` 的那一组。

    没有 `review_call` 的行走 legacy 支（整组按台账序读）—— 与 :func:`_votes_of`
    同一条口径：老行没有"哪一趟"这回事，只能按历史形态读。
    """
    by_call: "OrderedDict[str, list[Mapping[str, Any]]]" = OrderedDict()
    for row in group:
        call = str(row.get("review_call") or "").strip()
        if call:
            by_call.setdefault(call, []).append(row)
    if not by_call:
        return list(group), ""
    call = list(by_call)[-1]
    return by_call[call], call


def _votes_of(rows: Sequence[Mapping[str, Any]]) -> tuple[int, dict[str, Any] | None]:
    """前导 clean 票数 + 第一个非票行的 :func:`vote_reading`（跑满 ⇒ `None`）。"""
    votes = 0
    stop: dict[str, Any] | None = None
    for row in sorted(rows, key=_pass_no):
        reading = VR.vote_reading(row)
        if reading["vote"]:
            votes += 1
            continue
        stop = reading
        break
    return votes, stop


def _state_of(votes: int, need: int, stop: Mapping[str, Any] | None) -> str:
    """`state` 投影（只作读数；本脚本不据此改任何行为）。"""
    if stop is not None:
        kind = str(stop.get("kind") or "")
        cause = str(stop.get("cause") or "")
        if kind == "math":
            return "rejected"
        if kind == "contract":
            return "gate"
        if kind in ("procedural", "style") or cause in ("report_gap", "self_declared"):
            return "retry_report"
        return "unsigned"
    if votes >= need:
        return "unissued"
    if votes > 0:
        return "holding"
    return "unsigned"


def audit(root: str | Path) -> dict[str, Any]:
    """把四张表算成一份可 JSON 化的读数（纯读；不写任何工作区）。"""
    root_p = Path(str(root))
    out: dict[str, Any] = {
        "checked": False,
        "root": str(root_p),
        "rows": 0,
        "problems": [],
        "need": int(VR.SIGN_STREAK_NEED),
        "statements": [],
        "report_gaps": [],
        "legacy_counts": {source: 0 for source in VR.FAULT_KIND_SOURCES},
        "flips": [],
        "summary": {
            "fault_rows": 0,
            "clean_rows": 0,
            "vote_rows": 0,
        },
        "why": "",
    }
    if not root_p.is_dir():
        out["why"] = "工作区不在盘上 ⇒ 没查成（不是「0 行」）"
        return out
    rows, problems = VR.list_verifications(root_p, limit=None)
    out["rows"] = len(rows)
    out["problems"] = list(problems)
    out["checked"] = not problems

    groups: "OrderedDict[tuple[str, int], list[Mapping[str, Any]]]" = OrderedDict()
    by_sha_call: "OrderedDict[tuple[str, int, str, str], list[Mapping[str, Any]]]" = (
        OrderedDict())
    for row in rows:
        sid_now, no_now = _statement_of(row), VR.proof_no_of(row)
        groups.setdefault((sid_now, no_now), []).append(row)
        call_now = str(row.get("review_call") or "").strip()
        if call_now:
            by_sha_call.setdefault(
                (sid_now, no_now, str(row.get("proof_sha256") or ""), call_now),
                []).append(row)

    for (sid, proof_no), group in groups.items():
        latest, call = _latest_call_rows(group)
        votes, stop = _votes_of(latest)
        need = int(VR.SIGN_STREAK_NEED)
        out["statements"].append({
            "statement_id": sid,
            "proof_no": proof_no,
            "review_call": call,
            "proof_sha256": str(latest[-1].get("proof_sha256") or "") if latest else "",
            "rows": len(group),
            "votes": votes,
            "need": need,
            "stop_kind": str(stop.get("kind") or "") if stop else "",
            "stop_cause": str(stop.get("cause") or "") if stop else "",
            "stop_why": str(stop.get("why") or "") if stop else "",
            "stop_verification_id": (str(stop.get("verification_id") or "")
                                     if stop else ""),
            "state": _state_of(votes, need, stop),
        })

    for row in rows:
        reading = VR.fault_kind_of(row)
        source = str(reading.get("source") or "")
        if source in out["legacy_counts"]:
            out["legacy_counts"][source] += 1
        if (str(reading.get("cause") or "") == "report_gap"
                or str(reading.get("report_gap") or "")):
            out["report_gaps"].append({
                "statement_id": _statement_of(row),
                "proof_no": VR.proof_no_of(row),
                "verification_id": str(row.get("verification_id") or ""),
                "at": str(row.get("at") or ""),
                "proof_sha256": str(row.get("proof_sha256") or ""),
                "review_call": str(row.get("review_call") or ""),
                "review_pass": row.get("review_pass"),
                "source": source,
                "cause": str(reading.get("cause") or ""),
                "report_gap": str(reading.get("report_gap") or ""),
                "reason": str((row.get("secretary_judge") or {}).get("reason") or ""),
            })
        axis = VR.ledger_axis(row)
        if axis == "fault":
            out["summary"]["fault_rows"] += 1
        elif axis == "clean":
            out["summary"]["clean_rows"] += 1
        if VR.is_a_vote(row):
            out["summary"]["vote_rows"] += 1

    for (sid, proof_no, sha, call), group in by_sha_call.items():
        ordered = sorted(group, key=_pass_no)
        for index, earlier in enumerate(ordered):
            if VR.ledger_axis(earlier) != "clean":
                continue
            for later in ordered[index + 1:]:
                if VR.ledger_axis(later) != "fault":
                    continue
                reading = VR.fault_kind_of(later)
                out["flips"].append({
                    "statement_id": sid,
                    "proof_no": proof_no,
                    "proof_sha256": sha,
                    "review_call": call,
                    "clean_verification_id": str(
                        earlier.get("verification_id") or ""),
                    "clean_review_pass": earlier.get("review_pass"),
                    "fault_verification_id": str(later.get("verification_id") or ""),
                    "fault_review_pass": later.get("review_pass"),
                    "fault_kind": str(reading.get("kind") or ""),
                    "fault_cause": str(reading.get("cause") or ""),
                    "fault_reason": str(
                        (later.get("secretary_judge") or {}).get("reason") or ""),
                })

    if out["checked"]:
        out["why"] = (
            f"读了 {out['rows']} 行台账（{len(groups)} 条证明），"
            f"fault {out['summary']['fault_rows']} 行、clean {out['summary']['clean_rows']} 行、"
            f"算票 {out['summary']['vote_rows']} 行；本次没有写任何工作区")
    return out


def render(reading: Mapping[str, Any]) -> list[str]:
    """四张表的人读渲染（不改变任何判定，只排版）。"""
    lines: list[str] = []
    lines.append(f"verify-audit  root={reading.get('root')}")
    lines.append(f"  {reading.get('why')}")
    if reading.get("problems"):
        lines.append("  ⚠️ 台账有读不出来的行（这一格没查成，不是「没有问题」）：")
        for problem in reading["problems"]:
            lines.append(f"    - {problem}")
    lines.append("")
    lines.append("== 1. per-statement：votes / need / 停因 kind（cause 在括号里）==")
    if not reading.get("statements"):
        lines.append("  （没有台账行）")
    for one in reading.get("statements") or ():
        stop = (one.get("stop_cause") or one.get("stop_kind") or "-")
        if one.get("stop_cause") and one.get("stop_kind"):
            stop = f"{one['stop_kind']}({one['stop_cause']})"
        lines.append(
            f"  {one['statement_id']}#p{one['proof_no']}  "
            f"votes={one['votes']}/{one['need']}  "
            f"stop={stop}  state={one['state']}  "
            f"call={one['review_call'] or '(legacy)'}  "
            f"sha={str(one['proof_sha256'])[:12]}…"
            + (f"  stop_why={one['stop_why']}" if one["stop_why"] else ""))
    lines.append("")
    lines.append("== 2. report_gap 清单（业主 2026-11-09 裁定 ①：不算缺陷）==")
    gaps = reading.get("report_gaps") or []
    if not gaps:
        lines.append("  （没有 report_gap 行）")
    for one in gaps:
        lines.append(
            f"  {one['statement_id']}#p{one['proof_no']} {one['verification_id']} "
            f"({one['at']}) source={one['source']} cause={one['cause'] or '-'} "
            f"pass={one['review_pass']}")
        if one.get("report_gap"):
            lines.append(f"    report_gap: {one['report_gap']}")
        lines.append(f"    reason: {one['reason']}")
    lines.append("")
    lines.append("== 3. legacy_* 三类计数 ==")
    counts = reading.get("legacy_counts") or {}
    lines.append("  " + "  ".join(f"{source}={counts.get(source, 0)}"
                                 for source in (
                                     "legacy_math_evidence", "legacy_shape",
                                     "legacy_default", "row")))
    lines.append("  （legacy_* 是读侧推定：老行没有 `secretary_judge.fault_kind` 这个键；"
                 "`row` 是新行显式带了这个键 —— 值可以是空串）")
    lines.append("")
    lines.append("== 4. 同一 sha 同一 review_call：clean → fault 逐条点名 ==")
    flips = reading.get("flips") or []
    if not flips:
        lines.append("  （没有这种形态）")
    for one in flips:
        lines.append(
            f"  {one['statement_id']}#p{one['proof_no']} call={one['review_call']} "
            f"sha={str(one['proof_sha256'])[:12]}…")
        fault_reading = one["fault_kind"] or one["fault_cause"] or "?"
        lines.append(
            f"    {one['clean_verification_id']} (pass {one['clean_review_pass']}) clean "
            f"→ {one['fault_verification_id']} (pass {one['fault_review_pass']}) "
            f"fault kind/cause={fault_reading}")
        lines.append(f"    fault reason: {one['fault_reason']}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：只读、零写盘；`0` 查过了 / `2` 没查成。"""
    parser = argparse.ArgumentParser(
        prog="agentflow verify-audit",
        description="D3 批 1 的只读读数：票数 / report_gap / legacy_* / clean→fault 点名")
    parser.add_argument("--root", default=".", help="工作区根（默认当前目录）")
    parser.add_argument("--json", action="store_true", help="打成 JSON（同一份读数）")
    args = parser.parse_args(argv)

    reading = audit(args.root)
    if args.json:
        print(json.dumps(reading, ensure_ascii=False, indent=2))
    else:
        for line in render(reading):
            print(line)
    if not reading.get("checked"):
        print(f"[unknown] 没查成：{reading.get('why')}"
              "（这里的 0 不是「没有」，是「没查成」）", file=sys.stderr)
        return EXIT_UNKNOWN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
