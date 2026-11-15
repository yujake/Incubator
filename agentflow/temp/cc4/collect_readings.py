# -*- coding: utf-8 -*-
"""CC4 读数采集：把五条链各跑一趟，落一份机读的盘上终态（报告 §二 用它）。

跑法：python temp/cc4/collect_readings.py
产物：temp/cc4/readings.json（不含长事件流；只留判据读的那几格）
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "temp" / "cc4"))

BASE = pathlib.Path(__file__).resolve().parent / "bt_readings"


class _MP:
    """`monkeypatch` 的最小替身（本脚本只改一处 transport + 两个 env）。"""

    def __init__(self) -> None:
        self._undo: list[tuple[object, str, object]] = []

    def setenv(self, key: str, value: str) -> None:
        os.environ[key] = str(value)

    def setattr(self, obj: object, name: str, value: object) -> None:
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self) -> None:
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)


def _fresh(name: str) -> pathlib.Path:
    path = BASE / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def main() -> int:
    import test_rehearsal_c13_wake as C13
    import test_rehearsal_c4_revision_loop as C4
    import test_rehearsal_c9_concept_graph as C9
    import test_rehearsal_d_pointer_only as D
    import test_rehearsal_f_plan_lifecycle as F

    out: dict[str, object] = {}

    mp = _MP()
    try:
        got = F._run(_fresh("f"), mp, lean="0")
        read = F._chain_reading(got)
        out["f_plan_lifecycle"] = {
            "rc": got["rc"], "calls": len(got["wire"].bodies),
            "plans": [{"plan_id": r.get("plan_id"), "key": r.get("problem_key"),
                       "status": r.get("status"),
                       "history": [(h.get("action"), h.get("abandon_kind"))
                                   for h in (r.get("history") or [])]}
                      for r in read["plans"]],
            "tasks": [{"task_id": t.get("task_id"), "role": t.get("role"),
                       "status": t.get("status"), "outcome": t.get("outcome")}
                      for t in read["tasks"]],
            "form_rows": len(read["form_rows"]), "fit_rows": len(read["fit_rows"]),
            "handoffs": [(r.get("sender"), r.get("summary")) for r in read["handoffs"]],
            "manuscripts": read["manuscripts"],
            "run_ends": [(e.get("role"), e.get("stop_reason")) for e in read["runs_end"]],
        }
    finally:
        mp.undo()

    mp = _MP()
    try:
        got = C4._run(_fresh("c4"), mp, lean="0")
        read = C4._chain_reading(got)
        out["c4_revision_loop"] = {
            "rc": got["rc"], "calls": len(got["wire"].bodies),
            "sha_before": read["sha_before"], "sha_after": read["sha_after"],
            "before_body": read["lines_before"], "after_body": read["lines_after"],
            "pending": [{"sha": r.get("proof_sha256"), "defect_step": r.get("defect_step"),
                         "axis": (r.get("secretary_judge") or {}).get("axis"),
                         "why": r.get("why")}
                        for r in read["pending"]],
            "sign_files": sorted(p.name for p in (read["ws"] / "out" / "vsigns").glob("*.json"))
            if (read["ws"] / "out" / "vsigns").is_dir() else [],
            "steps": [(s["data"].get("proof_mode"), s["data"].get("proof_sha256"))
                      for s in read["steps"]],
            "v_kinds": [c["data"].get("kind") for c in read["v_calls"]],
            "defect_in_f_prompt": [C4.DEFECT in p for p in read["f_prompts"]],
        }
    finally:
        mp.undo()

    mp = _MP()
    try:
        got = D._run(_fresh("d"), mp, lean="0")
        read = D._chain_reading(got)
        out["d_pointer_only"] = {
            "rc": got["rc"], "calls": len(got["wire"].bodies),
            "carried": read["carried"], "report_has_pointer_section":
                "## 携带的证明手稿" in read["report"],
            "report_has_receipt": "B 收下 1 条" in read["report"],
            "statements": [{"stmt_id": r.get("stmt_id"), "kind": r.get("kind"),
                            "evidence_kind": r.get("evidence_kind"),
                            "manuscript_id": r.get("manuscript_id"),
                            "statement_full": r.get("statement_full"),
                            "bits": {k: (r.get("bits") or {}).get(k)
                                     for k in ("proof", "reviewed")}}
                           for r in read["statements"]],
            "deps": len(read["deps"]), "b_decisions": len(read["b_decisions"]),
        }
    finally:
        mp.undo()

    mp = _MP()
    try:
        got = C9._run(_fresh("c9"), mp, lean="0")
        read = C9._chain_reading(got)
        out["c9_concept_graph"] = {
            "rc": got["rc"], "calls": len(got["wire"].bodies),
            "reports": [(r.get("report_id"), r.get("kind")) for r in read["reports"]],
            "questions": [{"qid": r.get("question_id"), "origin": r.get("origin"),
                           "status": r.get("status"),
                           "related": r.get("related_concept_ids")}
                          for r in read["questions"]],
            "merge": {"verdict": read["merge_decision"]["data"].get("verdict"),
                      "merged_id": read["merge_decision"]["data"].get("merged_id"),
                      "survivor_id": read["merge_decision"]["data"].get("survivor_id"),
                      "applied": read["merge_resolve"]["data"].get("applied"),
                      "rewritten": read["merge_resolve"]["data"].get(
                          "rewritten_relation_ids")},
            "reject": {"verdict": read["reject_decision"]["data"].get("verdict"),
                       "applied": read["reject_resolve"]["data"].get("applied")},
            "tombstones": [{"stmt_id": r.get("stmt_id"), "status": r.get("status")}
                           for r in read["statements"]],
        }
    finally:
        mp.undo()

    mp = _MP()
    try:
        got = C13._run(_fresh("c13"), mp)
        read = C13._chain_reading(got)
        out["c13_wake"] = {
            "rc": got["rc"], "calls": len(got["wire"].bodies),
            "owner": {k: read["owner"].get(k) for k in
                      ("task_id", "role", "status", "outcome")},
            "item": {k: read["item"].get(k) for k in
                     ("task_id", "item_state", "item_close", "inputs")},
            "wakes": [{"state": w["data"].get("state"),
                       "count": w["data"].get("count"),
                       "cells": [{k: c.get(k) for k in
                                  ("item_id", "task_id", "verdict", "started",
                                   "refusal_code", "mark", "why")}
                                 for c in (w["data"].get("items") or [])]}
                      for w in read["wakes"]],
            "m_runs": len([e for e in read["runs"] if str(e.get("role")) == "M"]),
            "d_runs": [e.get("task_id") for e in read["runs"]
                       if str(e.get("role")) == "D"],
            "stdout_tail": [ln for ln in read["stdout"].splitlines()
                            if "自主跑完" in ln or "第 1 轮" in ln or "第 2 轮" in ln],
        }
    finally:
        mp.undo()

    path = pathlib.Path(__file__).resolve().parent / "readings.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
