#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""code/eq_ellipse_family.py -- E: conjecture 000000 的数值实验（不复用 exp:000000 的 5 个点）

对象：椭圆 x^2/a^2 + y^2/b^2 = 1，取 a/b ∈ {1.01,1.05,1.1,1.3,1.5,2,2.5,3,5}（9 个点，b=1）。
  过 P 沿方向 phi 的弦长 L_P(phi)；P 是等弦点 <=> Var_phi L_P(phi) = 0。
  求 inf_{|P| <= 0.9*min(a,b)} Var_phi L_P(phi) 与最优点 P*。

弦长用解析二次方程（无二分误差）：把 P + t u 代入椭圆方程
  A t^2 + B t + C = 0, A = ux^2/a^2 + uy^2/b^2, B = 2(Px ux/a^2 + Py uy/b^2),
  C = Px^2/a^2 + Py^2/b^2 - 1；弦长 = sqrt(B^2-4AC)/A。
  另与 2048 边折线求交做一次交叉核对（a/b=1.3 那个 case）。

搜索：11x11 粗网格（|P|<=0.9*min(a,b)）多起点（原点 + 网格最好的 3 个）+ 罗盘搜索
  （8 方向，步长 0.2*dmax -> 1e-7，域外投影回边界）。
复核：最优点用 2000 与 8000 方向方差各算一遍（同一解析弦长口径）。

判据（任务书）：某 (a,b) 上 2000 与 8000 方向方差都 < 1e-18 且 |P*| > 1e-3 => refutes（附反例）；
  否则 supports，并拟合 var_inf ≈ c*(a/b-1)^p 的 p 与 R^2。

输出：每个 ratio 一行 PROGRESS，结尾一行 REPRO_RESULT。
"""

from __future__ import annotations

import json
import math
import time

import numpy as np

THRESH = 1e-18
NONZERO_P = 1e-3
RATIOS = [1.01, 1.05, 1.1, 1.3, 1.5, 2.0, 2.5, 3.0, 5.0]
N_DIRS = 2000
N_DIRS_CHECK = 8000


def chords_analytic(a, b, P, phis):
    ux = np.cos(phis)
    uy = np.sin(phis)
    ia = 1.0 / (a * a)
    ib = 1.0 / (b * b)
    A = ux * ux * ia + uy * uy * ib
    B = 2.0 * (P[0] * ux * ia + P[1] * uy * ib)
    C = P[0] * P[0] * ia + P[1] * P[1] * ib - 1.0
    disc = B * B - 4.0 * A * C
    disc = np.where(disc > 0.0, disc, 0.0)
    return np.sqrt(disc) / A


def var_at(a, b, P, phis):
    L = chords_analytic(a, b, P, phis)
    m = float(L.mean())
    v = float(((L - m) ** 2).mean())
    return v, m, float(L.min()), float(L.max())


def R_of_theta(a, b, th):
    c = np.cos(th)
    s = np.sin(th)
    return a * b / np.sqrt((b * c) ** 2 + (a * s) ** 2)


def chords_polyline(a, b, P, phis, n=2048):
    """brute-force 折线交叉核对（与 exp:000000 同一口径）。"""
    th = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    r = R_of_theta(a, b, th)
    V = np.stack([r * np.cos(th), r * np.sin(th)], axis=1)
    Vn = np.roll(V, -1, axis=0)
    P = np.asarray(P, float)
    cph = np.cos(phis)
    sph = np.sin(phis)
    out = np.empty(len(phis))
    for i in range(len(phis)):
        ux, uy = cph[i], sph[i]
        Wx = V[:, 0] - P[0]
        Wy = V[:, 1] - P[1]
        Wnx = Vn[:, 0] - P[0]
        Wny = Vn[:, 1] - P[1]
        f = ux * Wy - uy * Wx
        fn = ux * Wny - uy * Wnx
        hit = (f * fn) < 0.0
        den = f - fn
        den = np.where(den == 0.0, 1.0, den)
        s = np.where(hit, f / den, 0.0)
        tx = Wx + s * (Wnx - Wx)
        ty = Wy + s * (Wny - Wy)
        t = ux * tx + uy * ty
        t = np.where(hit, t, np.nan)
        out[i] = np.nanmax(t) - np.nanmin(t)
    return out


def compass(f, P0, step0, step_min=1e-7, max_evals=500):
    P = np.array(P0, float)
    fv = float(f(P))
    nev = 1
    step = float(step0)
    dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
    while step > step_min and nev < max_evals:
        improved = False
        for dx, dy in dirs:
            Q = P + step * np.array([dx, dy], float)
            fq = float(f(Q))
            nev += 1
            if fq < fv:
                P, fv, improved = Q, fq, True
                break
        if not improved:
            step *= 0.5
    return P, fv, nev


def main():
    t0 = time.time()
    rows = []
    xcheck = None
    for idx, ratio in enumerate(RATIOS):
        a, b = float(ratio), 1.0
        dmax = 0.9 * min(a, b)
        phis = np.linspace(0.0, np.pi, N_DIRS, endpoint=False)
        tc = time.time()

        def obj_dom(P, a=a, b=b, phis=phis, dmax=dmax):
            r = math.hypot(float(P[0]), float(P[1]))
            if r > dmax:
                P = np.asarray(P, float) * (dmax / r)
            return var_at(a, b, P, phis)[0]

        g = np.linspace(-dmax, dmax, 11)
        grid = []
        for x in g:
            for y in g:
                if x * x + y * y > dmax * dmax:
                    continue
                v = obj_dom(np.array([x, y]))
                grid.append((v, float(x), float(y)))
        grid.sort()
        starts = [(0.0, 0.0)] + [(x, y) for _v, x, y in grid[:3]]
        best = None
        nev_tot = 0
        for S in starts:
            P, v, nev = compass(obj_dom, np.array(S, float), step0=0.2 * dmax)
            nev_tot += nev
            if best is None or v < best[1]:
                best = (P, v)
        P_star = np.asarray(best[0], float)
        v2000, mean2000, lmin, lmax = var_at(a, b, P_star, phis)
        phis8 = np.linspace(0.0, np.pi, N_DIRS_CHECK, endpoint=False)
        v8000, mean8000, lmin8, lmax8 = var_at(a, b, P_star, phis8)
        if xcheck is None and abs(ratio - 1.3) < 1e-12:
            ph = np.linspace(0.0, np.pi, 128, endpoint=False)
            Lf = chords_analytic(a, b, P_star, ph)
            Lp = chords_polyline(a, b, P_star, ph, 2048)
            xcheck = float(np.max(np.abs(Lf - Lp)))
        row = {
            "a_over_b": ratio,
            "a": a,
            "b": b,
            "P_search_radius": dmax,
            "P_star": [float(P_star[0]), float(P_star[1])],
            "abs_P_star": float(math.hypot(float(P_star[0]), float(P_star[1]))),
            "var_inf_2000dirs": v2000,
            "var_inf_8000dirs": v8000,
            "mean_chord_8000": mean8000,
            "rel_rms_8000": (math.sqrt(v8000) / mean8000) if mean8000 else float("nan"),
            "Lmin_8000": lmin8,
            "Lmax_8000": lmax8,
            "grid_points": len(grid),
            "starts": len(starts),
            "evals": nev_tot,
            "seconds": time.time() - tc,
        }
        rows.append(row)
        print("PROGRESS: " + json.dumps({
            "task": "ellipse_family", "done": idx + 1, "total": len(RATIOS),
            "a_over_b": ratio, "var_2000": v2000, "var_8000": v8000,
            "abs_P_star": row["abs_P_star"], "seconds": row["seconds"],
        }, ensure_ascii=False), flush=True)

    # ---- 拟合 var_inf ~ c*(a/b-1)^p
    xs = [math.log(r["a_over_b"] - 1.0) for r in rows]
    ys = [math.log(max(r["var_inf_8000dirs"], 1e-300)) for r in rows]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    p = sxy / sxx if sxx else float("nan")
    c_log = my - p * mx
    c = math.exp(c_log)
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (c_log + p * x)) ** 2 for x, y in zip(xs, ys))
    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")

    # ---- 判据
    refuters = [r for r in rows
                if r["var_inf_2000dirs"] < THRESH and r["var_inf_8000dirs"] < THRESH
                and r["abs_P_star"] > NONZERO_P]
    if refuters:
        bad = refuters[0]
        result = "refutes"
        counterexample = {
            "a_over_b": bad["a_over_b"], "a": bad["a"], "b": bad["b"],
            "P_star": bad["P_star"], "abs_P_star": bad["abs_P_star"],
            "var_2000dirs": bad["var_inf_2000dirs"],
            "var_8000dirs": bad["var_inf_8000dirs"],
            "n_refuters": len(refuters),
        }
    else:
        result = "supports"
        counterexample = None

    minvar2000 = min(r["var_inf_2000dirs"] for r in rows)
    minvar8000 = min(r["var_inf_8000dirs"] for r in rows)

    out = {
        "result": result,
        "claim": ("a!=b 的椭圆没有等弦点：inf_{|P|<=0.9*min(a,b)} Var_phi L_P(phi) 严格大于 0 "
                  "（9 个 a/b 比值、2000 与 8000 方向、解析弦长）"),
        "bound": {
            "curves": [{r["a"]: 1, "b": 1, "a_over_b": r["a_over_b"]} for r in rows],
            "P_search_domain": "|P| <= 0.9*min(a,b)（b=1 时即 |P| <= 0.9）",
            "grid": "11x11 均匀网格（圆盘内裁剪）+ 原点，共 %d 个候选起点" % len(grid),
            "starts_used": "原点 + 网格最好的 3 个，共 %d 个" % len(starts),
            "search_dirs": N_DIRS,
            "recheck_dirs": N_DIRS_CHECK,
            "compass_step": "0.2*dmax -> 1e-7（步长对半）",
            "chord_length_algorithm": "椭圆二次方程解析解 chord=sqrt(B^2-4AC)/A（无二分误差）",
            "polyline_crosscheck": {"a_over_b": 1.3, "edges": 2048, "dirs": 128,
                                    "max_abs_diff": xcheck},
            "note": "数值判据，不是证明；结论只覆盖列出的 a/b、方向数与搜索域",
        },
        "strategy": "analytic quadratic chord + 11x11 coarse grid multistart + compass search (8 dirs, step halving); recheck best point at 8000 dirs; 2048-edge polyline cross-check",
        "scaling": {
            "ratios": len(rows),
            "dirs_search": N_DIRS,
            "dirs_recheck": N_DIRS_CHECK,
            "evals_per_ratio": [r["evals"] for r in rows],
            "seconds_per_ratio": [round(r["seconds"], 3) for r in rows],
            "total_seconds": round(time.time() - t0, 3),
        },
        "data": {
            "objects_checked": "椭圆族 x^2/a^2+y^2/b^2=1，a/b = %s（b=1）；每点求 inf Var_phi L_P(phi) 与 argmin P*"
                               % [r["a_over_b"] for r in rows],
            "threshold_var": THRESH,
            "nonzero_P_threshold": NONZERO_P,
            "min_var_2000dirs": minvar2000,
            "min_var_8000dirs": minvar8000,
            "fit_var_inf_vs_ratio_minus_1": {
                "model": "var_inf ~= c*(a/b-1)^p",
                "p": p, "c": c, "R2": r2, "log_least_squares_on_log_var": True,
                "inputs": [{"a_over_b": r["a_over_b"], "var_inf_8000dirs": r["var_inf_8000dirs"]} for r in rows],
            },
            "rows": rows,
        },
        "notes": {
            "far_from_zero": "var_inf 最小者远大于阈值 %g" % THRESH,
            "crosscheck": "解析弦长与 2048 边折线求交的最大偏差见 bound.polyline_crosscheck.max_abs_diff",
            "evidence_kind": "cross_check（数值，不是证明；Lean 本会话关闭）",
        },
    }
    if counterexample is not None:
        out["counterexample"] = counterexample
    print("REPRO_RESULT: " + json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
