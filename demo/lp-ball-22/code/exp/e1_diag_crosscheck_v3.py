#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 实验（取代 000008/000009）：A_diag(p) 三路对拍，纯 stdlib，确定性。

A 路：(3/4)*int_0^{2pi} S(th)^{-2/p} dth
      S(th) = |cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p
B 路：sqrt(3)*area(D)，D = {(x,y): |x|^p+|y|^p+|x+y|^p <= 1}
      平面极坐标 area = (1/2) int_0^{2pi} R(th)^2 dth，R 由定义式二分求（不代入任何闭式）
C 路（第三路）：同一 D 的另一套坐标 (w,d) = (x+y, x-y)
      jacobian dx dy = (1/2) dw dd  =>  area = 2*int_0^{wmax} dmax(w) dw，dmax 由定义式二分求
断点只取几何断点（|cos|=0 / |sin|=0 / x+y=0 / 折点 d=w），每段两端做 t=u^4 代换后
用 48 点 Gauss-Legendre（t^p 在这些点上成为 u 的多项式，故端点奇性被消掉）。
判据（硬编码）：max_p rel(A,B) < 1e-10；p in {1.5,3,10}: rel(A,C) < 1e-6。
"""
import json
import math
import time

PI = math.pi


def gauss_legendre(n):
    xs = [0.0] * n
    ws = [0.0] * n
    for i in range((n + 1) // 2):
        z = math.cos(PI * (i + 0.75) / (n + 0.5))
        pp = 1.0
        for _ in range(100):
            p0, p1 = 1.0, 0.0
            for j in range(1, n + 1):
                p2 = p1
                p1 = p0
                p0 = ((2 * j - 1) * z * p1 - (j - 1) * p2) / j
            pp = n * (z * p0 - p1) / (z * z - 1.0)
            dz = p0 / pp
            z -= dz
            if abs(dz) < 1e-15:
                break
        xs[i] = -z
        xs[n - 1 - i] = z
        w = 2.0 / ((1.0 - z * z) * pp * pp)
        ws[i] = w
        ws[n - 1 - i] = w
    return xs, ws


GLX, GLW = gauss_legendre(48)


def integrate_piece(f, a, b):
    """int_a^b f；两端各用 (端点距离) t = u^4 代换，再 48 点 Gauss-Legendre。"""
    if b <= a:
        return 0.0
    h = 0.5 * (b - a)
    s = 0.0
    for base, sgn in ((a, 1.0), (b, -1.0)):
        for x, w in zip(GLX, GLW):
            u = 0.5 * (x + 1.0)
            uu = u * u
            s += w * (sgn * 2.0 * h * uu * u) * f(base + sgn * h * uu * uu)
    return s


def integrate(f, breaks):
    return sum(integrate_piece(f, breaks[i], breaks[i + 1]) for i in range(len(breaks) - 1))


def integrate_01(g):
    s = 0.0
    for x, w in zip(GLX, GLW):
        s += 0.5 * w * g(0.5 * (x + 1.0))
    return s


# ---------- A 路 ----------
ABRK = [0.0, PI / 3.0, 2 * PI / 3.0, PI, 4 * PI / 3.0, 5 * PI / 3.0, 2 * PI]


def S_val(p, th):
    return (abs(math.cos(th - PI / 6.0)) ** p
            + abs(math.cos(th + PI / 6.0)) ** p
            + abs(math.sin(th)) ** p)


def A_path_A(p):
    return integrate(lambda th: 0.75 * S_val(p, th) ** (-2.0 / p), ABRK)


# ---------- B 路 ----------
BBRK = [0.0, PI / 2.0, 3 * PI / 4.0, PI, 3 * PI / 2.0, 7 * PI / 4.0, 2 * PI]


def radius_B(p, th):
    c = math.cos(th)
    s = math.sin(th)
    lo, hi = 0.0, 4.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if abs(mid * c) ** p + abs(mid * s) ** p + abs(mid * (c + s)) ** p <= 1.0:
            lo = mid
        else:
            hi = mid
    return lo


def A_path_B(p):
    return math.sqrt(3.0) * integrate(lambda th: 0.5 * radius_B(p, th) ** 2, BBRK)


# ---------- C 路 ----------
def wmax_C(p):
    return 2.0 / (2.0 + 2.0 ** p) ** (1.0 / p)


def dmax_C(p, w):
    rhs = 2.0 ** p * (1.0 - w ** p)
    lo, hi = 0.0, 4.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if abs(w + mid) ** p + abs(w - mid) ** p <= rhs:
            lo = mid
        else:
            hi = mid
    return lo


def A_path_C(p):
    wm = wmax_C(p)
    wst = 2.0 ** (-1.0 / p)          # 折点：dmax(w) = w
    tot = integrate_piece(lambda w: 2.0 * dmax_C(p, w), 0.0, wst)
    L = wm - wst
    if L > 0.0:
        def g(u):
            return 2.0 * dmax_C(p, wm - L * u ** p) * L * p * u ** (p - 1.0)
        tot += integrate_01(g)
    return math.sqrt(3.0) * tot


def main():
    t0 = time.time()
    ps = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 20.0, 50.0]
    exact = {1.0: 3.0 * math.sqrt(3.0) / 4.0, 2.0: PI}
    rows = []
    worst_ab = 0.0
    for p in ps:
        t1 = time.time()
        a = A_path_A(p)
        b = A_path_B(p)
        rel = abs(a - b) / abs(a)
        row = {"p": p, "A_1d": a, "A_2d": b, "rel_AB": rel, "sec": round(time.time() - t1, 4)}
        if p in exact:
            e = exact[p]
            row["exact"] = e
            row["rel_exact_A"] = abs(a - e) / e
            row["rel_exact_B"] = abs(b - e) / e
        rows.append(row)
        worst_ab = max(worst_ab, rel)
        print("PROGRESS: " + json.dumps({"stage": "A_vs_B", "p": p, "A_1d": a,
                                         "A_2d": b, "rel": rel, "sec": row["sec"]}))
    crows = []
    worst_ac = 0.0
    for p in (1.5, 3.0, 10.0):
        t1 = time.time()
        a = A_path_A(p)
        c = A_path_C(p)
        rel = abs(a - c) / abs(a)
        cr = {"p": p, "A_1d": a, "A_3": c, "rel_AC": rel, "sec": round(time.time() - t1, 4)}
        if p in exact:
            e = exact[p]
            cr["rel_exact_A"] = abs(a - e) / e
            cr["rel_exact_C"] = abs(c - e) / e
        crows.append(cr)
        worst_ac = max(worst_ac, rel)
        print("PROGRESS: " + json.dumps({"stage": "A_vs_C", "p": p, "A_3": c, "rel": rel}))
    ok_ab = worst_ab < 1e-10
    ok_ac = worst_ac < 1e-6
    result = "supports" if (ok_ab and ok_ac) else "inconclusive"
    payload = {
        "result": result,
        "tol_AB": 1e-10,
        "tol_C": 1e-6,
        "worst_rel_AB": worst_ab,
        "worst_rel_AC": worst_ac,
        "bound": "p in {1,1.25,1.5,2,2.5,3,4,6,10,20,50}",
        "strategy": "breakpoint Gauss-Legendre(48) + u^4 endpoint smoothing (A); polar area with bisection radius (B); (w,d)=(x+y,x-y) reduction with bisection boundary (C)",
        "scaling": {"total_sec": round(time.time() - t0, 3),
                    "per_p_sec": [r["sec"] for r in rows]},
        "rows": rows,
        "rows_C": crows,
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
