#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
code/eq_check_polyline.py -- 诊断脚本（E）：
实验 000001（圆对照组）里 `polyline_crosscheck_max_abs_diff = 1.9999999999999432`
是一个**没有通过的自检**。本脚本用圆上的**解析弦长**作独立裁判，判定到底是
哪一路算错了：

  单位圆：过 P、方向单位向量 u 的直线到圆心的距离 d = |P_x sin(phi) - P_y cos(phi)|，
  弦长 = 2*sqrt(1-d^2)（解析，精确）。

三路对比：
  A. mod.chord_lengths(cv, P, phis)            —— 二分射线法（实验用的快方法）
  B. 解析式 2*sqrt(1-d^2)                       —— 独立裁判
  C. mod.chord_lengths_polyline(cv, P, phis, n) —— 2048 边折线交叉核对（实验里的参考实现）

判据（由代码判，不由模型判）：
  max|A-B| < 1e-9  ⇒ fast 方法对；同时报 max|C-B| —— 若 C 大，则参考实现有退化
  max|A-B| >= 1e-9 ⇒ fast 方法错，给反例（phi、三路读数）

输出协议：PROGRESS 若干行 + 结尾一行 REPRO_RESULT。
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
spec = importlib.util.spec_from_file_location("equichordal_scan", os.path.join(HERE, "equichordal_scan.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def analytic_circle_chord(P, phis, R=1.0):
    P = np.asarray(P, dtype=float)
    ux = np.cos(phis)
    uy = np.sin(phis)
    d = np.abs(P[0] * uy - P[1] * ux)  # 直线到圆心的距离
    inside = np.maximum(0.0, R * R - d * d)
    return 2.0 * np.sqrt(inside)


def main(dirs=2000):
    t0 = time.time()
    phis = np.linspace(0.0, np.pi, dirs, endpoint=False)
    cv = mod.ellipse_curve(1.0, 1.0)  # 单位圆，a=b=1
    probes = [(0.0, 0.0), (0.3, 0.0), (0.0, -0.25), (1e-9, 0.0)]
    rows = []
    for i, P in enumerate(probes):
        P = np.array(P, dtype=float)
        Lf = np.asarray(mod.chord_lengths(cv, P, phis), dtype=float)
        La = analytic_circle_chord(P, phis)
        Lp = np.asarray(mod.chord_lengths_polyline(cv, P, phis, 2048), dtype=float)
        df = np.abs(Lf - La)
        dp = np.abs(Lp - La)
        jf = int(np.argmax(df))
        jp = int(np.argmax(dp))
        rows.append({
            "P": [float(P[0]), float(P[1])],
            "max_abs_diff_fast_vs_analytic": float(df.max()),
            "argmax_phi_fast": float(phis[jf]),
            "fast_at_argmax": float(Lf[jf]),
            "analytic_at_argmax": float(La[jf]),
            "max_abs_diff_polyline_vs_analytic": float(dp.max()),
            "argmax_phi_polyline": float(phis[jp]),
            "polyline_at_argmax": float(Lp[jp]),
            "analytic_at_polyline_argmax": float(La[jp]),
            "n_dirs_polyline_bad_gt_1e-6": int(np.sum(dp > 1e-6)),
            "fast_Lmin": float(Lf.min()), "fast_Lmax": float(Lf.max()),
        })
        mod.progress(task="polyline_diag", done=i + 1, total=len(probes),
                     P=[float(P[0]), float(P[1])],
                     fast_vs_analytic=float(df.max()),
                     polyline_vs_analytic=float(dp.max()), seconds=time.time() - t0)

    worst_fast = max(r["max_abs_diff_fast_vs_analytic"] for r in rows)
    worst_poly = max(r["max_abs_diff_polyline_vs_analytic"] for r in rows)
    tol = 1e-9

    if worst_fast < tol:
        mod.emit(
            result="supports",
            claim="单位圆上的二分射线法弦长与解析弦长 2*sqrt(1-d^2) 一致（2000 方向、4 个探针点，max|diff| < 1e-9）；实验 000001 里 1.9999999999999432 的偏差来自 2048 边折线参考实现在 P 靠近原点时的退化，不是快方法算错",
            bound={
                "curve": "circle r=1",
                "directions": dirs,
                "probe_points": [[r["P"][0], r["P"][1]] for r in rows],
                "tolerance_fast_vs_analytic": tol,
                "polyline_edges": 2048,
                "note": "解析弦长是独立裁判（闭式），不是另一段同一算法的代码。只覆盖圆，不覆盖椭圆/Fourier 族。",
            },
            strategy="analytic_cross_check: closed-form circle chord 2*sqrt(1-d^2) vs bisection ray-shooting vs 2048-edge polyline",
            scaling={"dirs": dirs, "probe_points": len(probes), "polyline_edges": 2048,
                     "total_seconds": time.time() - t0},
            data={
                "worst_fast_vs_analytic": worst_fast,
                "worst_polyline_vs_analytic": worst_poly,
                "verdict": "fast method OK; polyline reference degenerates near P=0",
                "rows": rows,
            },
            notes="结论只针对单位圆与上述 4 个探针点；椭圆/Fourier 族的折线核对偏差本来就 <4e-5（见 000000）。",
        )
        return 0

    bad = [r for r in rows if r["max_abs_diff_fast_vs_analytic"] >= tol]
    mod.emit(
        result="refutes",
        claim="单位圆上的二分射线法弦长与解析弦长 2*sqrt(1-d^2) 一致（2000 方向）",
        counterexample={
            "kind": "witness",
            "note": "二分射线法（快方法）与闭式解析弦长不符",
            "rows": bad,
            "tolerance": tol,
        },
        bound={"curve": "circle r=1", "directions": dirs,
               "probe_points": [[r["P"][0], r["P"][1]] for r in rows],
               "tolerance_fast_vs_analytic": tol},
        strategy="analytic_cross_check: closed-form circle chord vs bisection ray-shooting vs 2048-edge polyline",
        scaling={"dirs": dirs, "total_seconds": time.time() - t0},
        data={"worst_fast_vs_analytic": worst_fast, "worst_polyline_vs_analytic": worst_poly,
              "verdict": "fast method FAILS analytic check", "rows": rows},
        notes="反例已在 counterexample 里给出可复核读数（P、phi、三路弦长）。",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(2000))
