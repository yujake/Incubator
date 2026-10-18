#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conjectures:000000 的 testable 判据实跑（E 本趟；只做可复现的事）。

做四件事，全部确定性：
 1) 按 testable 写死的参数域（k∈{2,3,4}, m∈{3,4,5}, N∈{8,16,32,64}，每个 (k,N) 一个固定种子）
    用一个"候选估计器"生成 readings。候选估计器 = scripts/f_conj000000_delta.py 里的
    均匀采样估计器（在 8 字母环境里均匀采样长度 N 的约化词，命中的字母全落在 A_k 内的比例
    估计 p = V_X/V_env，delta_hat = ln(V_env * p_hat)/ln N）。它与已作废代理量 E2 同形，
    这里只作为"有没有合格估计器"的候选被测，不作为结论来源。
 2) 把 readings 落盘。
 3) 以子进程调用 scripts/conj000000_verdict_gate.py（确定性闸门）判出 verdict —— 判定只认它的
    输出，本脚本不改写、不解释。
 4) 以子进程调用 scripts/conj000000_infeasible_record.py 产出记录侧 JSON（缺失估计器的不存在性记录）。

不做的事：不生成任何"更有利"的读数；feasible=false 的格子（解析命中率 < 1e-3）不做采样、
不写入 readings（gate 的 Q3 会把 NaN/0 当越界，那是噪声），只在 coverage 里如实登记为
"未采样（解析预判不可行）"。参数域不放大也不缩小。

stdout 末尾一行：REPRO_RESULT: {json}
"""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(WS, "scripts", "conj000000_verdict_gate.py")
RECORD = os.path.join(WS, "scripts", "conj000000_infeasible_record.py")
OUTDIR = os.path.join(WS, "out", "experiments")
READINGS_PATH = os.path.join(OUTDIR, "conj000000_readings.json")
VERDICT_PATH = os.path.join(OUTDIR, "conj000000_verdict.json")
RECORD_PATH = os.path.join(WS, "reports", "conj000000_infeasible_record.json")

# --- testable 写死的参数域（不放大不缩小） ---
KS = [2, 3, 4]
MS = [3, 4, 5]
RUNGS = [8, 16, 32, 64]

# --- 候选估计器的常数（与 scripts/f_conj000000_delta.py 一致） ---
REL_SE_MAX = 0.1
H_MIN = 50
P_MAX = 1e-3
M_BY_N = {8: 200000, 16: 100000, 32: 100000, 64: 100000}
ESTIMATOR = "uniform_env_word_sampling_lnV_hat_over_lnN"


def seed_of(k, N):
    return 100000 + 1000 * k + N


def V_env(N):
    return 1 + 8 * ((7 ** N - 1) // 6)


def V_X(k, N):
    return 1 + (2 * k) * ((2 * k - 1) ** N - 1) // (2 * k - 2)


def sample_hits(k, N, seed, M):
    rng = random.Random(seed)
    allowed = set(range(1, k + 1)) | set(range(-k, 0))
    hits = 0
    for _ in range(M):
        ok = True
        for _l in range(N):
            a = rng.randint(1, 8)
            s = a if a <= 4 else -(a - 4)
            if s not in allowed:
                ok = False
                break
        if ok:
            hits += 1
    return hits


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    t_all = time.time()
    readings = []
    cells = []

    for k in KS:
        for N in RUNGS:
            t0 = time.time()
            ve = V_env(N)
            vx = V_X(k, N)
            p_exact = vx / ve
            cell = {"k": k, "N": N, "M_planned": M_BY_N[N], "seed": seed_of(k, N),
                    "p_exact": p_exact}
            if p_exact < P_MAX:
                # 解析预判：即使把 M 打满，期望命中数 < 1，采样不产生读数（不伪造数字）
                cell.update({"status": "not_sampled_infeasible_by_analytic_precheck",
                             "expected_hits": p_exact * M_BY_N[N]})
                cells.append(cell)
                print("PROGRESS: " + json.dumps({"stage": "cell_skipped", "k": k, "N": N,
                                                 "p_exact": p_exact,
                                                 "expected_hits": p_exact * M_BY_N[N],
                                                 "elapsed_sec": round(time.time() - t0, 3)},
                                                ensure_ascii=False), flush=True)
                continue
            M = M_BY_N[N]
            hits = sample_hits(k, N, seed_of(k, N), M)
            p_hat = hits / float(M)
            v_hat = ve * p_hat
            if hits > 0:
                delta_hat = math.log(v_hat) / math.log(N)
                rel_se = math.sqrt((1.0 - p_hat) / (M * p_hat))
            else:
                delta_hat = float("nan")
                rel_se = float("inf")
            converged = bool(rel_se <= REL_SE_MAX and hits >= H_MIN)
            feasible = not (p_exact < P_MAX or p_hat < P_MAX)
            readings.append({
                "estimator": ESTIMATOR,
                "k": k,
                "N": N,
                "seed": seed_of(k, N),
                "delta_hat": delta_hat,
                "rel_se": rel_se,
                "converged": converged,
                "feasible": feasible,
                "normalization_scale": 1.0,
                "M": M,
                "hits": hits,
                "p_hat": p_hat,
                "delta_exact_lnVX_over_lnN": math.log(vx) / math.log(N),
            })
            cell.update({"status": "measured", "M": M, "hits": hits, "p_hat": p_hat,
                         "delta_hat": delta_hat, "rel_se": rel_se,
                         "converged": converged, "feasible": feasible})
            cells.append(cell)
            print("PROGRESS: " + json.dumps({"stage": "cell_measured", "k": k, "N": N,
                                             "hits": hits, "p_hat": p_hat,
                                             "delta_hat": delta_hat, "rel_se": rel_se,
                                             "converged": converged,
                                             "elapsed_sec": round(time.time() - t0, 3)},
                                            ensure_ascii=False), flush=True)

    payload = {"readings": readings,
               "provenance": {
                   "conjecture_id": "000000",
                   "estimator": ESTIMATOR,
                   "estimator_source": "scripts/f_conj000000_delta.py（同一估计器定义，未改参数）",
                   "domain": {"k": KS, "m": MS, "N": RUNGS,
                              "seed_rule": "seed(k,N)=100000+1000k+N；每个 (k,N) 一个确定性种子（按 testable 原文）"},
                   "skipped_cells": [{"k": c["k"], "N": c["N"], "p_exact": c["p_exact"]}
                                     for c in cells if c["status"] != "measured"],
                   "limits": "delta_0 不是因子不变量；仅在标准自由生成元元组上；至多 supported_not_proved",
               }}
    with open(READINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("PROGRESS: " + json.dumps({"stage": "readings_written", "path": READINGS_PATH,
                                     "n_readings": len(readings),
                                     "elapsed_sec": round(time.time() - t_all, 3)},
                                    ensure_ascii=False), flush=True)

    # --- 3) 确定性闸门（子进程；判定只认它） ---
    gp = subprocess.run([sys.executable, GATE, "--readings", READINGS_PATH, "--out", VERDICT_PATH],
                        cwd=WS, capture_output=True, text=True)
    gate_stdout = gp.stdout or ""
    gate_stderr = gp.stderr or ""
    verdict = None
    try:
        verdict = json.loads(gate_stdout) if gate_stdout.strip() else None
    except Exception as e:  # noqa: BLE001
        verdict = {"_parse_error": repr(e), "_raw_head": gate_stdout[:2000]}
    print("PROGRESS: " + json.dumps({"stage": "gate_ran", "exit_code": gp.returncode,
                                     "stdout_bytes": len(gate_stdout),
                                     "stderr_tail": gate_stderr[-800:]},
                                    ensure_ascii=False), flush=True)

    # --- 4) 记录侧（缺失估计器的不存在性记录） ---
    rp = subprocess.run([sys.executable, RECORD], cwd=WS, capture_output=True, text=True)
    record_statuses = None
    try:
        rec = json.loads(rp.stdout)
        approaches = rec.get("approaches") or rec.get("approach_records") or []
        record_statuses = [{"approach_id": a.get("approach_id"), "status": a.get("status")}
                           for a in approaches if isinstance(a, dict)]
        if record_statuses is None and isinstance(rec, dict):
            record_statuses = {"keys": sorted(rec.keys())}
    except Exception as e:  # noqa: BLE001
        record_statuses = {"_parse_error": repr(e), "_stdout_head": (rp.stdout or "")[:1500]}
    print("PROGRESS: " + json.dumps({"stage": "record_ran", "exit_code": rp.returncode,
                                     "wrote": os.path.exists(RECORD_PATH),
                                     "stderr_tail": (rp.stderr or "")[-500:]},
                                    ensure_ascii=False), flush=True)

    # --- 覆盖度（代码算，不靠判读） ---
    measured = {(r["k"], r["N"]) for r in readings if r.get("feasible")}
    pairs_all = [(k, m) for k in KS for m in MS if m != k]
    pairs_measured = [(k, m) for (k, m) in pairs_all
                      if {n for (kk, n) in measured if kk == k} and {n for (kk, n) in measured if kk == m}]
    coverage = {
        "k_domain": KS, "k_measured": sorted({k for k, _ in measured}),
        "m_domain": MS, "m_measured": sorted({m for _, m in pairs_measured}),
        "N_domain": RUNGS, "N_measured": sorted({n for _, n in measured}),
        "cells_total": len(KS) * len(RUNGS), "cells_measured": len(measured),
        "cells_not_sampled": [{"k": c["k"], "N": c["N"], "reason": c["status"]}
                              for c in cells if c["status"] != "measured"],
        "pairs_total": pairs_all, "pairs_with_readings_on_both_sides": pairs_measured,
        "seeds_per_cell": 1,
    }

    gate_status = (verdict or {}).get("gate", {}).get("status")
    gate_reasons = (verdict or {}).get("gate", {}).get("reasons")
    crit_status = (verdict or {}).get("criterion", {}).get("status")

    if crit_status == "supports":
        result = "supports"
    elif crit_status == "refutes":
        result = "refutes"
    else:
        result = "inconclusive"

    res = {
        "result": result,
        "gate_exit_code": gp.returncode,
        "gate_status": gate_status,
        "gate_reasons": gate_reasons,
        "criterion_status": crit_status,
        "criterion_reasons": (verdict or {}).get("criterion", {}).get("reasons"),
        "n_readings": len(readings),
        "coverage": coverage,
        "record_side": {"exit_code": rp.returncode, "statuses": record_statuses,
                        "path": RECORD_PATH},
        "bound": {"k": KS, "m": MS, "N": RUNGS, "cells_measured": len(measured),
                  "seeds_per_cell": 1},
        "strategy": "analytic_hitrate_precheck + uniform_env_word_sampling + deterministic_gate_subprocess",
        "scaling": [{"k": c["k"], "N": c["N"], "M": c.get("M"),
                     "p_exact": c["p_exact"], "status": c["status"]}
                    for c in cells],
        "total_runtime_sec": round(time.time() - t_all, 3),
        "estimator_note": ("本趟唯一可执行的候选估计器与已作废代理量 E2 同形"
                           "（delta_hat = ln V_hat / ln N，随 N 增长）；gate 的 Q1/Q3 结构性不过，"
                           "所以它拿不到 ①/② 的读数。"),
        "gate_impl_note": ("testable.gate_criteria 的 Q4 原文是『可行性：不可行档 ≥2 则该估计器不能支撑全序列判定』，"
                           "而 scripts/conj000000_verdict_gate.py 实现的 Q4 是『归一化不变性』；"
                           "两者不一致，本趟按脚本实现执行，并把 testable 原文的可行性档数另记在 coverage 里。"),
        "limits": ("delta_0 不是因子不变量；只在标准自由生成元元组上；读数至多 supported_not_proved。"
                   "gate 未过 ⇒ 结构性缺口（缺合格估计器），不是猜想被数据反驳。"),
    }
    print("REPRO_RESULT: " + json.dumps(res, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
