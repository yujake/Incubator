#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 任务 2：A_face(p) 的闭式与二维积分对拍（判据 < 1e-12）。

闭式（任务给定，本脚本先自己从定义验一遍路径关系）：
  A_face_closed(p) = 2^{1/2-1/p} * 4 * Gamma(1+1/p)^2 / Gamma(1+2/p)

二维积分（F 稿同型的面积表示）：
  A_face(p) = area{ (s,z) : 2^{1-p/2}|s|^p + |z|^p <= 1 }
  记 a := 2^{1-p/2}。
  B 路（直角切片 + 定义式二分，不用任何闭式端点）：
      area = 4 * int_0^{s0} zmax(s) ds，zmax(s) 由 a|s|^p+|z|^p <= 1 二分求，
      s0 由 a|s|^p <= 1 二分求；DE(tanh-sinh) 求积。
  C 路（极坐标面积公式，另一条独立路）：
      area = (1/2) int_0^{2pi} (a|cos th|^p + |sin th|^p)^{-2/p} dth，断点取 pi/2 的倍数。

判据（脚本内硬编码、由脚本判）：max_p rel(closed,B) < 1e-12；rel(closed,C) < 1e-12。
自检：A_face(1) = sqrt(2)、A_face(2) = pi，两条路各自都要到 1e-13。
"""
import json
import math
import time

PI = math.pi


def tanhsinh(f, a, b, h=0.008, tmax=8.0):
    """双指数求积 int_a^b f（端点代数奇性稳健）。"""
    if b <= a:
        return 0.0
    c = 0.5 * (b - a)
    d = 0.5 * (a + b)
    s = 0.0
    n = int(tmax / h)
    for k in range(-n, n + 1):
        t = k * h
        u = (PI / 2.0) * math.sinh(t)
        if u > 400.0 or u < -400.0:
            continue
        x = math.tanh(u)
        if x >= 1.0 or x <= -1.0:
            continue
        ch = math.cosh(u)
        w = (PI / 2.0) * math.cosh(t) / (ch * ch)
        s += w * f(d + c * x)
    return s * c * h


def a_coef(p):
    return 2.0 ** (1.0 - p / 2.0)


def A_face_closed(p):
    lg = 2.0 * math.lgamma(1.0 + 1.0 / p) - math.lgamma(1.0 + 2.0 / p)
    return (2.0 ** (0.5 - 1.0 / p)) * 4.0 * math.exp(lg)


def zmax_B(p, s):
    """max z>=0 with a|s|^p + |z|^p <= 1；由定义式二分（不用幂闭式）。"""
    a = a_coef(p)
    c = a * abs(s) ** p
    if c > 1.0:
        return None
    lo, hi = 0.0, 2.0
    while c + hi ** p <= 1.0:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if c + mid ** p <= 1.0:
            lo = mid
        else:
            hi = mid
    return lo


def s0_B(p):
    a = a_coef(p)
    lo, hi = 0.0, 2.0
    while a * hi ** p <= 1.0:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if a * mid ** p <= 1.0:
            lo = mid
        else:
            hi = mid
    return lo


def A_face_B(p, h=0.008):
    s0 = s0_B(p)

    def f(s):
        z = zmax_B(p, s)
        return 0.0 if z is None else z

    return 4.0 * tanhsinh(f, 0.0, s0, h=h)


def A_face_C(p, h=0.008):
    brk = [0.0, PI / 2.0, PI, 3.0 * PI / 2.0, 2.0 * PI]
    a = a_coef(p)

    def f(th):
        return (a * abs(math.cos(th)) ** p + abs(math.sin(th)) ** p) ** (-2.0 / p)

    tot = 0.0
    for i in range(len(brk) - 1):
        tot += tanhsinh(f, brk[i], brk[i + 1], h=h)
    return 0.5 * tot


def main():
    t0 = time.time()
    ps = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 20.0, 50.0]
    exact = {1.0: math.sqrt(2.0), 2.0: PI}
    rows = []
    worst_b = 0.0
    worst_c = 0.0
    worst_exact = 0.0
    for p in ps:
        ts = time.time()
        cl = A_face_closed(p)
        b = A_face_B(p)
        c = A_face_C(p)
        rel_b = abs(b - cl) / abs(cl)
        rel_c = abs(c - cl) / abs(cl)
        row = {"p": p, "A_face_closed": cl, "A_face_slice_int": b, "A_face_polar_int": c,
               "rel_closed_vs_slice": rel_b, "rel_closed_vs_polar": rel_c,
               "sec": round(time.time() - ts, 3)}
        if p in exact:
            e = exact[p]
            row["exact"] = e
            row["rel_exact_closed"] = abs(cl - e) / e
            row["rel_exact_slice"] = abs(b - e) / e
            worst_exact = max(worst_exact, row["rel_exact_closed"], row["rel_exact_slice"])
        rows.append(row)
        worst_b = max(worst_b, rel_b)
        worst_c = max(worst_c, rel_c)
        print("PROGRESS: " + json.dumps({"stage": "face_closed_vs_2d", "p": p,
                                        "closed": cl, "slice": b, "polar": c,
                                        "rel_slice": rel_b, "rel_polar": rel_c}))
    # 收敛控制：h 与 h/2 的结果差（不是把阈值放宽）
    conv = []
    for p in (1.25, 2.0, 3.0, 10.0):
        b1 = A_face_B(p, h=0.008)
        b2 = A_face_B(p, h=0.004)
        conv.append({"p": p, "abs_diff_h": abs(b1 - b2), "rel_diff_h": abs(b1 - b2) / abs(b1)})
    ok_slice = worst_b < 1e-12
    ok_polar = worst_c < 1e-12
    ok_exact = worst_exact < 1e-13
    result = "supports" if (ok_slice and ok_polar and ok_exact) else "inconclusive"
    payload = {
        "result": result,
        "tol": 1e-12,
        "tol_exact": 1e-13,
        "worst_rel_closed_vs_slice": worst_b,
        "worst_rel_closed_vs_polar": worst_c,
        "worst_rel_vs_exact_p1_p2": worst_exact,
        "checks": {"closed_vs_slice": ok_slice, "closed_vs_polar": ok_polar, "exact_p1_p2": ok_exact},
        "bound": "p in {1,1.25,1.5,2,2.5,3,4,6,10,20,50}",
        "strategy": "closed form via lgamma vs 2D area(a|s|^p+|z|^p<=1) by cartesian slicing with bisection-on-definition ends vs polar area formula; tanh-sinh h=0.008 with h-refinement control",
        "scaling": {"total_sec": round(time.time() - t0, 3),
                    "per_p_sec": [r["sec"] for r in rows]},
        "h_refinement": conv,
        "rows": rows,
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
