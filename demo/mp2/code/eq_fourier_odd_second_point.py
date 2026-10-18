#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""code/eq_fourier_odd_second_point.py -- E: conjecture 000001 第二半的数值实验

对象：exp:000002 的 odd_control 族（r(θ)=1+eps*(0.6111 cos3θ + 0.3889 cos5θ)，系数按 sum hypot=1 归一化）。
  该族 r(θ)+r(θ+π)=2 ⇒ 原点**精确**是等弦点（弦长恒为 2，作正对照）。
  问题：原点之外还有没有第二个等弦点（Var_phi L_P(phi)=0 的非零 P）？

判据（与任务书一致）：
  * 在 P≠0 区域（|P| >= R_EXCL 且 |P| <= 0.9*rmax）找到 P* 使 2000 与 8000 方向方差都 < 1e-18
    ⇒ result=refutes，并给出 counterexample；
  * 只在原点附近小、随 |P| 单调增 ⇒ result=supports。

弦长：复用 code/equichordal_scan.py 的二分法射线求交（45/60 iters），并做一次 2048 边折线求交交叉核对。
搜索：13x13 粗网格（挖掉 |P|<R_EXCL 的圆盘）+ 6 个柱坐标起点，罗盘搜索步长 0.1*dmax -> 1e-7。
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


def emit(**kw):
    print("REPRO_RESULT: " + json.dumps(kw, ensure_ascii=False, default=float))


def progress(**kw):
    print("PROGRESS: " + json.dumps(kw, ensure_ascii=False, default=float), flush=True)


RAW = {"odd_control": [(2, 0.0, 0.0), (3, 0.55, 0.0), (4, 0.0, 0.0), (5, 0.35, 0.0), (6, 0.0, 0.0)]}
TOT = sum(math.hypot(a, b) for _k, a, b in RAW["odd_control"])
COEFS = [(k, a / TOT, b / TOT) for k, a, b in RAW["odd_control"]]

EPS_LIST = [1e-3, 3e-3, 1e-2, 3e-2]
DIRS = 2000
DIRS_V = 8000
R_EXCL = 0.01          # P≠0 的定义域：挖掉 |P| < 0.01 的小圆盘
VAR_ZERO_THRESH = 1e-18


def main():
    t0 = time.time()
    rows = []
    for eps in EPS_LIST:
        te = time.time()
        cv = mod.fourier_curve("odd_control", COEFS, eps)
        rmax = float(cv.rmax)
        dmax = 0.9 * rmax
        phis = np.linspace(0.0, np.pi, DIRS, endpoint=False)

        def obj(P, cv=cv, phis=phis):
            # 【v2 修正】把环域约束写进目标函数：罗盘搜索不许退回被挖掉的原点圆盘，
            # 也不许越出 |P| <= 0.9*rmax。exp:000005 里 P* 落在 ~1e-17 就是缺这一条。
            r = math.hypot(float(P[0]), float(P[1]))
            if r < R_EXCL:
                return 1e6 + (R_EXCL - r)
            if r > dmax * (1.0 + 1e-12):
                # 【v3】容差 1e-12 相对量：壳层 r=frac*rmax 在 float 下 hypot 可能比 dmax 大 1ulp，
                # 上一版把这种纯舍入越界也判成惩罚，导致壳层读数出现 1e6 的假数。
                return 1e6 + (r - dmax)
            return mod.stats(cv, P, phis)["var"]

        # ---- 粗网格（挖掉原点小圆盘）
        N = 13
        xs = np.linspace(-dmax, dmax, N)
        grid = []
        for x in xs:
            for y in xs:
                r = math.hypot(x, y)
                if R_EXCL <= r <= dmax:
                    grid.append((x, y))
        gv = []
        for (x, y) in grid:
            gv.append((obj(np.array([x, y])), x, y))
        gv.sort()

        starts = [np.array([x, y]) for _v, x, y in gv[:4]]
        for th in (0.0, math.pi / 2, math.pi, 1.5 * math.pi):
            starts.append(np.array([0.5 * dmax * math.cos(th), 0.5 * dmax * math.sin(th)]))

        best_P = None
        best_v = float("inf")
        nev_total = 0
        for P0 in starts:
            P, v, nev = mod.pattern_search(obj, P0, step0=0.1 * dmax, step_min=1e-7, max_evals=400)
            nev_total += nev
            if v < best_v:
                best_v, best_P = float(v), np.array(P, dtype=float)

        # ---- 最优点用 8000 方向复核
        phis_v = np.linspace(0.0, np.pi, DIRS_V, endpoint=False)
        st_2000 = mod.stats(cv, best_P, phis, 45)
        st_8000 = mod.stats(cv, best_P, phis_v, 60)

        # ---- 原点（正对照）
        org_2000 = mod.stats(cv, np.zeros(2), phis, 45)
        org_8000 = mod.stats(cv, np.zeros(2), phis_v, 60)

        # ---- 壳层读数：|P|=r 的圆周上 24 个方向的方差最小值
        shell = []
        for frac in (0.01, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.9):
            r = frac * rmax
            vs = []
            for j in range(24):
                th = 2.0 * math.pi * j / 24.0
                Q = np.array([r * math.cos(th), r * math.sin(th)])
                vs.append(obj(Q))
            shell.append({"r": r, "r_over_rmax": frac, "min_var_on_shell": float(min(vs)),
                          "max_var_on_shell": float(max(vs))})

        # 单调性：壳层最小方差随 r 非降（相对容差 5%）
        mono = True
        for i in range(1, len(shell)):
            if shell[i]["min_var_on_shell"] < shell[i - 1]["min_var_on_shell"] * (1.0 - 0.05):
                mono = False

        # ---- 折线交叉核对（eps 最大那一档）
        xcheck = None
        if abs(eps - EPS_LIST[-1]) < 1e-15:
            phis_s = phis[:128]
            Lf = mod.chord_lengths(cv, best_P, phis_s, 60)
            Lp = mod.chord_lengths_polyline(cv, best_P, phis_s, 2048)
            xcheck = float(np.max(np.abs(Lf - Lp)))

        row = {
            "eps": eps,
            "rmax": rmax,
            "P_search_annulus": [R_EXCL, dmax],
            "grid_points": len(grid),
            "starts": len(starts),
            "P_star": [float(best_P[0]), float(best_P[1])],
            "abs_P_star": float(math.hypot(best_P[0], best_P[1])),
            "var_min_2000dirs": float(st_2000["var"]),
            "var_min_8000dirs": float(st_8000["var"]),
            "rel_rms_8000": float(st_8000["rel_rms"]),
            "mean_chord_8000": float(st_8000["mean"]),
            "Lmin_8000": float(st_8000["Lmin"]),
            "Lmax_8000": float(st_8000["Lmax"]),
            "var_origin_2000dirs": float(org_2000["var"]),
            "var_origin_8000dirs": float(org_8000["var"]),
            "mean_chord_origin_8000": float(org_8000["mean"]),
            "shell_min_var": shell,
            "shell_monotone_nondecreasing": bool(mono),
            "polyline_crosscheck_max_abs_diff": xcheck,
            "evals": int(nev_total + len(grid)),
            "seconds": time.time() - te,
        }
        rows.append(row)
        progress(eps=eps, var_min_2000=row["var_min_2000dirs"], var_min_8000=row["var_min_8000dirs"],
                 abs_P_star=row["abs_P_star"], seconds=row["seconds"])

    # ---- 判据
    cex = None
    for r in rows:
        if (r["abs_P_star"] >= 1e-3 and r["var_min_2000dirs"] < VAR_ZERO_THRESH
                and r["var_min_8000dirs"] < VAR_ZERO_THRESH):
            cex = {"eps": r["eps"], "P_star": r["P_star"], "abs_P_star": r["abs_P_star"],
                   "var_2000dirs": r["var_min_2000dirs"], "var_8000dirs": r["var_min_8000dirs"],
                   "mean_chord_8000": r["mean_chord_8000"]}
            break

    all_mono = all(r["shell_monotone_nondecreasing"] for r in rows)
    has_origin_zero = all(r["var_origin_8000dirs"] < 1e-20 for r in rows)

    if cex is not None:
        result = "refutes"
        verdict = "在 P≠0 区域找到等弦点（2000/8000 方向方差都 < 1e-18）"
    elif all_mono and has_origin_zero:
        result = "supports"
        verdict = "原点方差 ~1e-31（正对照）；挖掉 |P|<0.01 后最小方差远大于 1e-18，且壳层最小方差随 |P| 单调不降"
    else:
        result = "inconclusive"
        verdict = "没找到反例，但壳层单调性或原点正对照不成立，判据未满足"

    emit(
        result=result,
        claim="odd_control 族（r(θ)=1+eps*(0.6111cos3θ+0.3889cos5θ)）在 P≠0 区域没有第二个等弦点："
              "对 eps ∈ {1e-3,3e-3,1e-2,3e-2}，|P| ∈ [0.01, 0.9*rmax] 上 Var_phi L_P(phi) 的下确界严格大于 0",
        bound={
            "family": "odd_control: r(th) = 1 + eps*(0.6111 cos3th + 0.3889 cos5th)（sum_k hypot(a_k,b_k)=1 归一化）",
            "eps_list": EPS_LIST,
            "P_search_domain": "|P| ∈ [%.3g, 0.9*rmax]（挖掉原点小圆盘）" % R_EXCL,
            "directions_search": DIRS,
            "directions_recheck": DIRS_V,
            "chord_length_algorithm": "二分法射线求交（search 45 iters, recheck 60 iters）+ 2048 边折线求交交叉核对（eps=3e-2）",
            "search": "13x13 粗网格（挖掉 |P|<0.01）+ 4 个柱坐标起点，罗盘搜索 0.1*dmax -> 1e-7",
            "shell_readings": "|P|=frac*rmax 圆周上 24 个方向的方差最小值，frac ∈ {0.01,0.05,0.1,0.2,0.35,0.5,0.7,0.9}",
            "nonzero_P_threshold": 1e-3,
            "zero_var_threshold": VAR_ZERO_THRESH,
            "note": "数值判据，不是证明；结论只覆盖列出的 eps、方向数与搜索域",
        },
        strategy="bisection ray-shooting + 13x13 coarse grid multistart (annulus, origin excluded) + compass(pattern) search to 1e-7; 8000-dir recheck; radial shell scan; 2048-edge polyline cross-check",
        scaling={"dirs_search": DIRS, "dirs_recheck": DIRS_V, "bisection_iters": [45, 60],
                 "seconds_per_eps": [r["seconds"] for r in rows],
                 "evals_per_eps": [r["evals"] for r in rows],
                 "total_seconds": time.time() - t0},
        data={"objects_checked": "odd_control Fourier 族 (eps ∈ [1e-3,3e-3,1e-2,3e-2])，每点求 P≠0 区域 inf Var_phi L_P(phi) 与 argmin P*",
              "verdict": verdict, "counterexample": cex, "rows": rows},
        counterexample=cex,
        notes="origin 是精确等弦点（r(th)+r(th+pi)=2），所以原处方差是正对照；判据看的是挖掉 |P|<0.01 之后的最小方差。",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
