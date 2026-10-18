#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E: 猜想 000000 的 var_inf 搜索边界读数（独立实验行，不复用 exp:000019 的 data）。

断言（conjectures.000000.statement）：椭圆族 x^2/a^2+y^2/b^2=1（a!=b）不存在等弦点，
即对任意内部点 P，Var_phi L_P(phi) > 0 严格成立。

本脚本只给数值读数（不是证明）：
  * 在 (a,b) 网格上做多起点最小化 var_inf_hat = min_P Var_phi L_P(phi)，
    方向数 2000，最优点用 8000 方向复核；
  * 搜索域 |P| <= 0.9*min(a,b)（猜想 testable.condition 的口径），11x11 正方形粗网格
    截到圆盘内 + 取最低 5 个点做罗盘搜索（另加原点起点），step_min=1e-8；
  * 同时给出径向剖面 rel_rms(|P|) 作单调性读数。

判据（conjectures.000000.testable.refutation_criterion 逐字）：
  任一 (a,b) 上找到 P（|P| 明显不为 0）使 2000 方向弦长方差 < 1e-18 且 8000 方向复核
  也 < 1e-18 => refutes（必须给非空 counterexample）；否则 supports。

曲线与弦长算法逐字复用 code/equichordal_scan.py（ellipse_curve / chord_lengths /
stats / pattern_search），不另写一份参数化。

输出协议：每个 case 一行 PROGRESS: {json}，结尾一行 REPRO_RESULT: {json}
（含 result / bound / strategy / scaling / data 五键；refutes 时另加 counterexample）。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "equichordal_scan.py")
spec = importlib.util.spec_from_file_location("equichordal_scan", MAIN)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

THRESH = 1e-18
NONZERO_P = 1e-6
DIRS = 2000
DIRS_RECHECK = 8000
GRID = 11
N_STARTS = 5
STEP_MIN = 1e-8
MAX_EVALS = 800

CASES = [(1.1, 1.0), (1.5, 1.0), (2.0, 1.0), (2.5, 1.5), (3.0, 1.0)]
RING_FRACS = [0.001, 0.01, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.9]


def emit(obj):
    sys.stdout.write("REPRO_RESULT: " + json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def progress(**kw):
    sys.stdout.write("PROGRESS: " + json.dumps(kw, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main():
    t0 = time.time()
    phis = np.linspace(0.0, np.pi, DIRS, endpoint=False)
    phis_rc = np.linspace(0.0, np.pi, DIRS_RECHECK, endpoint=False)
    rows = []
    t_case = []
    total_evals = 0

    for idx, (a, b) in enumerate(CASES):
        tc0 = time.time()
        cv = mod.ellipse_curve(a, b)
        dmax = 0.9 * min(a, b)

        def obj(P, cv=cv):
            return mod.stats(cv, P, phis)["var"]

        # ---- 粗网格（正方形截圆盘）-----------
        xs = np.linspace(-dmax, dmax, GRID)
        cands = []
        for x in xs:
            for y in xs:
                if math.hypot(x, y) > dmax:
                    continue
                P = np.array([x, y], dtype=float)
                cands.append((float(obj(P)), P))
        cands.sort(key=lambda t: t[0])
        starts = [P for _, P in cands[:N_STARTS]]

        # ---- 多起点罗盘搜索（含原点起点）------
        results = []
        evals = 0
        for P0 in starts + [np.zeros(2)]:
            P, fv, nev = mod.pattern_search(obj, P0, step0=0.1 * dmax,
                                            step_min=STEP_MIN, max_evals=MAX_EVALS)
            results.append((float(fv), np.array(P, dtype=float)))
            evals += int(nev)
        total_evals += evals
        v_best, P_best = min(results, key=lambda t: t[0])

        st = mod.stats(cv, P_best, phis)
        st_rc = mod.stats(cv, P_best, phis_rc)
        v_origin = float(obj(np.zeros(2)))

        # ---- 径向剖面（单调性读数）----------
        ring = {}
        for fr in RING_FRACS:
            rad = fr * dmax
            minv = float("inf")
            med_list = []
            for j in range(32):
                ang = 2.0 * math.pi * j / 32.0
                Q = rad * np.array([math.cos(ang), math.sin(ang)])
                vv = float(obj(Q))
                med_list.append(vv)
                minv = min(minv, vv)
            ring["%.3g" % fr] = {
                "radius": rad,
                "min_var_over_32_angles": minv,
                "median_var_over_32_angles": float(np.median(med_list)),
                "min_rel_rms_over_32_angles": math.sqrt(minv) / abs(float(mod.stats(cv, rad * np.array([1.0, 0.0]), phis)["mean"])),
            }

        dt = time.time() - tc0
        t_case.append(dt)
        rows.append({
            "a": a, "b": b, "a_over_b": a / b,
            "curve": cv.name,
            "P_star": [float(P_best[0]), float(P_best[1])],
            "abs_P_star": float(math.hypot(P_best[0], P_best[1])),
            "var_inf_2000dirs": float(v_best),
            "rel_rms_2000dirs": st["rel_rms"],
            "var_at_same_P_8000dirs": float(st_rc["var"]),
            "rel_rms_8000dirs": st_rc["rel_rms"],
            "var_at_origin_2000dirs": v_origin,
            "mean_chord_at_P_star": st["mean"],
            "Lmin_at_P_star": st["Lmin"],
            "Lmax_at_P_star": st["Lmax"],
            "search_domain_radius": dmax,
            "grid_points_feasible": len(cands),
            "evals_compass": evals,
            "ring_profile": ring,
            "seconds": dt,
        })
        progress(task="ellipse_varinf", case="%g/%g" % (a, b), done=idx + 1,
                 total=len(CASES), var_inf=float(v_best),
                 abs_P_star=float(math.hypot(P_best[0], P_best[1])),
                 var_at_origin=v_origin, seconds=dt)

    # ---------------- 判定 ----------------
    hits = [r for r in rows
            if r["abs_P_star"] > NONZERO_P
            and r["var_inf_2000dirs"] < THRESH
            and r["var_at_same_P_8000dirs"] < THRESH]
    if hits:
        h = hits[0]
        result = "refutes"
        counterexample = {
            "a": h["a"], "b": h["b"], "P": h["P_star"],
            "abs_P": h["abs_P_star"],
            "var_2000dirs": h["var_inf_2000dirs"],
            "var_8000dirs": h["var_at_same_P_8000dirs"],
            "note": "|P|>1e-6 且 2000/8000 方向方差均 <1e-18",
        }
    else:
        result = "supports"
        counterexample = None

    min_row = min(rows, key=lambda r: r["var_inf_2000dirs"])

    obj = {
        "result": result,
        "bound": {
            "family": "ellipse x^2/a^2+y^2/b^2=1, (a,b) 网格 = %s" % ([",".join(["%g" % v for v in c]) for c in CASES]),
            "a_over_b_list": [c[0] / c[1] for c in CASES],
            "P_search_domain": "|P| <= 0.9*min(a,b)（圆盘），%dx%d 正方形粗网格截圆盘 + 最低 %d 个起点 + 原点起点做罗盘搜索（step_min=%g, max_evals=%d）" % (GRID, GRID, N_STARTS, STEP_MIN, MAX_EVALS),
            "directions": "%d 方向求方差，最优点用 %d 方向复核" % (DIRS, DIRS_RECHECK),
            "chord_length_algorithm": "二分法射线求交（45 iters，与 code/equichordal_scan.py 同一实现）",
            "refutation_threshold": THRESH,
            "nonzero_P_threshold": NONZERO_P,
            "ring_profile": "|P|=frac*0.9*min(a,b) 圆周上 32 个方向的方差（min 与 median），frac ∈ %s" % (RING_FRACS,),
            "note": "数值判据，不是证明；读数只覆盖上面列出的 (a,b)、方向数、搜索域与局部搜索算法",
        },
        "strategy": "bisection ray-shooting + coarse grid (11x11, disk-truncated) multistart + compass(pattern) search to 1e-8; 8000-dir recheck at argmin; radial shell scan for monotonicity",
        "scaling": {
            "cases": len(CASES),
            "dirs": DIRS,
            "dirs_recheck": DIRS_RECHECK,
            "grid": GRID,
            "seconds_per_case": [round(t, 2) for t in t_case],
            "total_seconds": round(time.time() - t0, 2),
            "compass_evals_total": total_evals,
            "cost_note": "粗网格点数 O(GRID^2) * 2000 方向；单点方差 = 2000 方向 x 45 次二分，向量化",
        },
        "data": {
            "conjecture_id": "000000",
            "decision_rule": "任一 (a,b) 上 |P|>1e-6 且 var_2000<1e-18 且 var_8000<1e-18 => refutes；否则 supports",
            "min_var_inf_over_cases": min_row["var_inf_2000dirs"],
            "min_var_inf_case": [min_row["a"], min_row["b"]],
            "cases": rows,
        },
    }
    if counterexample is not None:
        obj["counterexample"] = counterexample
    emit(obj)
    return 0


if __name__ == "__main__":
    sys.exit(main())
