#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E: 猜想 000001 的判定性数值检验。

断言（conjectures.000001.statement）：Fourier 奇谐波扰动族（exp:000002 的 odd_control 型）
在原点 P=0 处精确等弦，且该族在原点之外不含任何第二等弦点。

族参数化逐字复用 code/equichordal_scan.py 的 fourier_curve + odd_control 系数
（R(theta) = 1 + eps * sum_k (a_k cos k*theta + b_k sin k*theta)，k=3:0.55, k=5:0.35）：
因为只有奇谐波，r(th)+r(th+pi)=2 恒成立 => 过原点的每一条弦长都恰为 2（原点精确等弦）。

判据（conjectures.000001.testable.refutation_criterion 逐字）：
  若在任一 eps 上找到 P≠0 使 2000 方向弦长方差 < 1e-18 且 8000 方向复核同样 < 1e-18
  => refutes（必须给非空 counterexample）；
  若只在 P=0 附近出现小方差且随 |P| 单调增 => supports。
原点邻域按题面排除：|P| < 1e-6 的点不作为候选（目标函数在该邻域返回罚值 1e6，
所以局部搜索不会停到里面去）。

搜索：|P| <= 0.9*rmax 正方形粗网格(13x13) + 近原点环带(13 个半径 x 32 角) 打分，
取分数最低的 5 个起点做罗盘(pattern)搜索（step_min=1e-9, max_evals=600），
最优点用 8000 方向复核；另外打 var 随 |P| 的环带剖面（每半径 32 个角取最小）。

输出协议：每个 eps 一行 PROGRESS: {...}；结尾一行 REPRO_RESULT: {...}（五键 + refutes 时 counterexample）。

复现：python code/eq_fourier_odd_second_point_search.py
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
_SPEC = importlib.util.spec_from_file_location("equichordal_scan", MAIN)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

# exp:000002 / code/equichordal_scan.py:432 的 odd_control 系数（逐字）
ODD_CONTROL = [(2, 0.0, 0.0), (3, 0.55, 0.0), (4, 0.0, 0.0), (5, 0.35, 0.0), (6, 0.0, 0.0)]
EPS_LIST = [1e-3, 3e-3, 1e-2, 3e-2]
VAR_THRESH = 1e-18
ORIGIN_EXCLUDE = 1e-6


def san(o):
    if isinstance(o, dict):
        return {str(k): san(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [san(v) for v in o]
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def emit(obj):
    sys.stdout.write("REPRO_RESULT:" + json.dumps(san(obj), ensure_ascii=False, allow_nan=False) + "\n")
    sys.stdout.flush()


def progress(**kw):
    sys.stdout.write("PROGRESS: " + json.dumps(san(kw), ensure_ascii=False, allow_nan=False) + "\n")
    sys.stdout.flush()


def var_of(cv, P, phis):
    return float(mod.stats(cv, P, phis)["var"])


def run_eps(eps, dirs=2000, check_dirs=8000, grid=13, topk=5, max_evals=600, ring_angles=32):
    t0 = time.time()
    cv = mod.fourier_curve("odd_control", ODD_CONTROL, eps)
    phis = np.linspace(0.0, np.pi, dirs, endpoint=False)
    rmax = float(cv.rmax)
    dmax = 0.9 * rmax

    def feasible(P):
        d = math.hypot(float(P[0]), float(P[1]))
        return (d >= ORIGIN_EXCLUDE) and (d <= dmax)

    def obj(P):
        if not feasible(P):
            return 1e6
        return var_of(cv, P, phis)

    cands = []
    xs = np.linspace(-dmax, dmax, grid)
    for x in xs:
        for y in xs:
            P = np.array([float(x), float(y)])
            if not feasible(P):
                continue
            cands.append((var_of(cv, P, phis), float(x), float(y), "grid"))

    radii = [1e-5, 1e-4, 1e-3, 1e-2, 0.025, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.9]
    ring = {}
    for rad in radii:
        r = rad * rmax
        if r < ORIGIN_EXCLUDE or r > dmax:
            continue
        vals = []
        for j in range(ring_angles):
            al = 2.0 * math.pi * j / ring_angles
            P = np.array([r * math.cos(al), r * math.sin(al)])
            v = var_of(cv, P, phis)
            vals.append(v)
            cands.append((v, float(P[0]), float(P[1]), "ring"))
        ring["%.4g" % rad] = {
            "radius": r,
            "min_var_over_%d_angles" % ring_angles: float(min(vals)),
            "median_var": float(np.median(vals)),
        }

    var_origin = var_of(cv, np.zeros(2), phis)
    cands.sort(key=lambda t: t[0])
    step0 = 2.0 * dmax / (grid - 1)

    refined = []
    for v0, x, y, src in cands[:topk]:
        P, fv, nev = mod.pattern_search(obj, np.array([x, y]), step0=step0,
                                       step_min=1e-9, max_evals=max_evals)
        P = np.array([float(P[0]), float(P[1])])
        if feasible(P):
            refined.append((var_of(cv, P, phis), P, v0, src, int(nev)))
    if not refined:
        return None
    refined.sort(key=lambda t: t[0])
    v_best, P_best, v0_best, src_best, nev_best = refined[0]

    phis_chk = np.linspace(0.0, np.pi, check_dirs, endpoint=False)
    st = mod.stats(cv, P_best, phis)
    st_chk = mod.stats(cv, P_best, phis_chk)

    row = {
        "eps": float(eps),
        "curve": cv.name,
        "rmax": rmax,
        "search_domain_radius": dmax,
        "origin_exclusion_radius": ORIGIN_EXCLUDE,
        "dirs": int(dirs),
        "check_dirs": int(check_dirs),
        "grid": int(grid),
        "ring_angles": int(ring_angles),
        "grid_points_feasible": int(sum(1 for c in cands if c[3] == "grid")),
        "var_at_origin_%ddirs" % dirs: var_origin,
        "P_best": [float(P_best[0]), float(P_best[1])],
        "abs_P_best": float(math.hypot(P_best[0], P_best[1])),
        "start_kind_best": src_best,
        "var_2000dirs": float(v_best),
        "var_8000dirs_check": float(st_chk["var"]),
        "rms_2000dirs": float(st["rms"]),
        "rel_rms_2000dirs": float(st["rel_rms"]),
        "mean_chord_2000dirs": float(st["mean"]),
        "Lmin_2000dirs": float(st["Lmin"]),
        "Lmax_2000dirs": float(st["Lmax"]),
        "evals_compass": int(nev_best),
        "ring_profile": ring,
        "seconds": time.time() - t0,
    }
    return row


def main():
    t0 = time.time()
    rows = []
    for i, eps in enumerate(EPS_LIST):
        row = run_eps(eps)
        if row is None:
            progress(task="fourier_odd_second_point", eps=eps, status="no_feasible_candidate",
                     done=i + 1, total=len(EPS_LIST))
            continue
        rows.append(row)
        progress(task="fourier_odd_second_point", eps=eps, done=i + 1, total=len(EPS_LIST),
                 var_2000=row["var_2000dirs"], var_8000=row["var_8000dirs_check"],
                 abs_P=row["abs_P_best"], seconds=round(row["seconds"], 3))

    hits = [r for r in rows
            if r["abs_P_best"] >= ORIGIN_EXCLUDE
            and r["var_2000dirs"] < VAR_THRESH
            and r["var_8000dirs_check"] < VAR_THRESH]

    result = "refutes" if hits else "supports"
    counterexample = None
    if hits:
        h = hits[0]
        counterexample = {
            "curve_family": "odd_control: R(theta)=1+eps*(0.55*cos(3*theta)+0.35*cos(5*theta))",
            "eps": h["eps"],
            "P": h["P_best"],
            "abs_P": h["abs_P_best"],
            "var_2000dirs": h["var_2000dirs"],
            "var_8000dirs_check": h["var_8000dirs_check"],
            "meaning": "P!=0 且过 P 的 2000 与 8000 方向弦长方差都 < 1e-18：原点之外的第二个等弦点",
        }

    total_seconds = time.time() - t0
    emit({
        "result": result,
        "bound": {
            "family": "Fourier 奇谐波族 odd_control（与 exp:000002 同一参数化），只有 k=3 (0.55) 与 k=5 (0.35) 分量",
            "eps_list": EPS_LIST,
            "P_search_domain": "|P| <= 0.9*rmax，排除 |P| < 1e-6；13x13 正方形粗网格 + 12 个半径环带(每环 32 角)打分，取最低 5 个起点做罗盘搜索（step_min=1e-9, max_evals=600）",
            "directions": "2000 方向求方差，最优点用 8000 方向复核",
            "refutation_threshold": VAR_THRESH,
            "note": "数值判据，不是证明；结论只覆盖上面列出的 eps、搜索域、方向数与局部搜索算法",
        },
        "strategy": "bisection ray-shooting(45 iters) + 粗网格/环带打分筛选 + compass(pattern) search multistart + 8000-dir verification",
        "scaling": {
            "dirs": 2000,
            "check_dirs": 8000,
            "seconds_per_eps": [round(r["seconds"], 3) for r in rows],
            "total_seconds": round(total_seconds, 3),
            "objects": "4 个 eps x (169 格点 + 12 环 x 32 角 + 5 起点 x <=600 次罗盘求值)",
        },
        "data": {
            "conjecture_id": "000001",
            "eps_rows": rows,
            "decision_rule": "任一 eps 上 P 满足 |P|>=1e-6、var_2000<1e-18 且 var_8000<1e-18 => refutes；否则 supports",
            "n_refuting_eps": len(hits),
        },
        "counterexample": counterexample,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
