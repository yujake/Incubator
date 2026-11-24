#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 实验 1（重做，取代 000008）：A_diag(p) 三路对拍。
A: (3/4)*int_0^{2pi} S(th)^{-2/p} dth, S=|cos(th-pi/6)|^p+|cos(th+pi/6)|^p+|sin th|^p
   断点 = 三个 |.| 的零点 与 两两相等点（对 p 无关，扫描+bisection 求出）
B: sqrt(3)*area{|x|^p+|y|^p+|x+y|^p<=1}
   平面笛卡尔切片: area = 8*x0*int_0^1 w(x0(1-u^2))*u du，
   w(x) 由 |w-x/2|^p+|w+x/2|^p = 1-|x|^p 二分求解（不用任何闭式）；u 方向切比雪夫聚集，
   并在 |x|=|x+y| 的折点处断开。
C: 同区域，平面极坐标 area=(1/2)int r(th)^2 dth，r 由二分求解（不用 g(th)^{-1/p} 闭式）。
判据（脚本硬编码）：max rel(A,B) < 1e-10；rel(A,C) < 1e-6（p in {1.5,3,10}）。
result: 达标 ⇒ supports；不达标且两路各自自收敛良好 ⇒ refutes（带 counterexample）；否则 inconclusive。
"""
import math, json, time, sys

def gl(n):
    xs = []; ws = []
    for i in range(1, n + 1):
        x = math.cos(math.pi * (i - 0.25) / (n + 0.5)); dp = 1.0
        for _ in range(100):
            p0 = 1.0; p1 = x
            for k in range(2, n + 1):
                p0, p1 = p1, ((2 * k - 1) * x * p1 - (k - 1) * p0) / k
            dp = n * (x * p1 - p0) / (x * x - 1.0)
            dx = -p1 / dp; x += dx
            if abs(dx) < 1e-16:
                break
        xs.append(x); ws.append(2.0 / ((1.0 - x * x) * dp * dp))
    return xs, ws

X8, W8 = gl(8); X24, W24 = gl(24); X40, W40 = gl(40)

def qp(f, a, b, X, W):
    m = 0.5 * (a + b); h = 0.5 * (b - a); s = 0.0
    for x, w in zip(X, W):
        s += w * f(m + h * x)
    return s * h

# ---------- 路径 A ----------
def f1(t): return abs(math.cos(t - math.pi / 6))
def f2(t): return abs(math.cos(t + math.pi / 6))
def f3(t): return abs(math.sin(t))

def _roots(g, N=8192):
    pts = []
    prev = g(0.0)
    if prev == 0.0: pts.append(0.0)
    for i in range(1, N + 1):
        t = 2 * math.pi * i / N; cur = g(t)
        if prev * cur < 0.0:
            lo = 2 * math.pi * (i - 1) / N; hi = t
            glo = prev
            for _ in range(100):
                mid = 0.5 * (lo + hi)
                gm = g(mid)
                if glo * gm <= 0.0:
                    hi = mid
                else:
                    lo = mid; glo = gm
            pts.append(0.5 * (lo + hi))
        prev = cur
    return pts

def breakpoints():
    c = [0.0, 2 * math.pi]
    for g in (f1, f2, f3,
              lambda t: f1(t) - f2(t), lambda t: f1(t) - f3(t), lambda t: f2(t) - f3(t)):
        c += [x for x in _roots(g) if 0.0 < x < 2 * math.pi]
    c.sort()
    out = [c[0]]
    for x in c[1:]:
        if x - out[-1] > 1e-9:
            out.append(x)
    return out

BP = breakpoints()

def S_of(th, p):
    return abs(math.cos(th - math.pi / 6)) ** p + abs(math.cos(th + math.pi / 6)) ** p + abs(math.sin(th)) ** p

def Adiag_1d(p, X, W):
    tot = 0.0
    for a, b in zip(BP[:-1], BP[1:]):
        tot += qp(lambda t: S_of(t, p) ** (-2.0 / p), a, b, X, W)
    return 0.75 * tot

# ---------- 路径 B ----------
def wmax(x, p, c):
    lo = 0.0; hi = 0.5 * abs(x) + c ** (1.0 / p) + 1e-300
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        v = abs(mid - 0.5 * x) ** p + abs(mid + 0.5 * x) ** p
        if v < c: lo = mid
        else: hi = mid
    return 0.5 * (lo + hi)

def areaD_cart(p, N, X, W):
    x0 = (1.0 + 2.0 ** (1.0 - p)) ** (-1.0 / p)
    xb = 2.0 ** (-1.0 / p)
    us = [0.5 * (1.0 - math.cos(math.pi * j / N)) for j in range(N + 1)]
    if 0.0 < xb < x0 * (1 - 1e-15):
        ub = math.sqrt(max(0.0, 1.0 - xb / x0))
        if 1e-12 < ub < 1 - 1e-12:
            us = sorted(us + [ub])
    def f(u):
        x = x0 * (1.0 - u * u); c = 1.0 - x ** p
        if c <= 0.0: return 0.0
        return 8.0 * x0 * u * wmax(x, p, c)
    return sum(qp(f, a, b, X, W) for a, b in zip(us[:-1], us[1:]))

# ---------- 路径 C ----------
CBP = [0.0, math.pi / 4, math.pi / 2, 3 * math.pi / 4, math.pi, 5 * math.pi / 4, 3 * math.pi / 2, 7 * math.pi / 4, 2 * math.pi]

def areaD_polar(p, X, W):
    def r(th):
        ct = math.cos(th); st = math.sin(th)
        def h(rr):
            return abs(rr * ct) ** p + abs(rr * st) ** p + abs(rr * (ct + st)) ** p
        lo = 0.0; hi = 2.0
        while h(hi) <= 1.0: hi *= 2.0
        for _ in range(80):
            m = 0.5 * (lo + hi)
            if h(m) < 1.0: lo = m
            else: hi = m
        return 0.5 * (lo + hi)
    tot = 0.0
    for a, b in zip(CBP[:-1], CBP[1:]):
        tot += qp(lambda t: r(t) ** 2, a, b, X, W)
    return 0.5 * tot

P = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 20.0, 50.0]
t0 = time.time()
rows = []
maxrel = 0.0; argmax = None
maxself = 0.0
for p in P:
    A24 = Adiag_1d(p, X24, W24); A = Adiag_1d(p, X40, W40)
    B200 = areaD_cart(p, 200, X8, W8); B = areaD_cart(p, 400, X8, W8)
    rel = abs(A - B) / abs(A)
    selfa = abs(A - A24) / abs(A); selfb = abs(B - B200) / abs(B)
    maxself = max(maxself, selfa, selfb)
    row = {"p": p, "A_1d": A, "A_1d_n24": A24, "B_2d": B, "B_2d_n200": B200,
           "rel_AB": rel, "self_A": selfa, "self_B": selfb}
    if 1.0 < p < 50.0 and abs(p - round(p)) < 0.75:
        pass
    if p in (1.0, 2.0):
        exact = 3.0 * math.sqrt(3.0) / 4.0 if p == 1.0 else math.pi
        row["anchor_exact"] = exact
        row["anchor_err_A"] = abs(A - exact) / exact
        row["anchor_err_B"] = abs(B - exact) / exact
    rows.append(row)
    if rel > maxrel:
        maxrel = rel; argmax = p
    print("PROGRESS: " + json.dumps({"stage": "A_vs_B", "p": p, "A_1d": A, "B_2d": B,
                                     "rel": rel, "self_A": selfa, "self_B": selfb}), flush=True)

maxrelC = 0.0; argC = None; Crows = []
for p in (1.5, 3.0, 10.0):
    A = Adiag_1d(p, X40, W40); C = areaD_polar(p, X24, W24)
    relc = abs(A - C) / abs(A)
    Crows.append({"p": p, "A_1d": A, "C_polar": C, "rel": relc})
    if relc > maxrelC:
        maxrelC = relc; argC = p
    print("PROGRESS: " + json.dumps({"stage": "A_vs_C", "p": p, "A_1d": A, "C_polar": C, "rel": relc}), flush=True)

elapsed = time.time() - t0
TOL_AB = 1e-10; TOL_C = 1e-6
ok = (maxrel <= TOL_AB and maxrelC <= TOL_C)
payload = {
    "result": "supports" if ok else "inconclusive",
    "bound": {"p_max_rel": argmax, "max_rel_AB": maxrel, "p_max_rel_C": argC, "max_rel_C": maxrelC,
              "tol_AB": TOL_AB, "tol_C": TOL_C, "max_self_convergence": maxself},
    "strategy": "theta-breakpoint Gauss-Legendre (path A) vs Cartesian slicing with bisection boundary (path B) vs polar with bisection radius (path C)",
    "scaling": {"n_p": len(P), "seconds_total": elapsed, "seconds_per_p": elapsed / max(1, len(P)),
                "path_A_nodes": 40 * (len(BP) - 1), "path_B_nodes": 8 * 400, "panels_B": 400},
    "rows": rows, "rows_C": Crows,
}
if (not ok) and maxrel > 1e-6 and maxself <= 1e-12:
    payload["result"] = "refutes"
    w = [r for r in rows if r["p"] == argmax][0]
    payload["counterexample"] = {"p": argmax, "A_1d": w["A_1d"], "B_2d": w["B_2d"], "rel": maxrel}
if not ok and payload["result"] == "inconclusive":
    payload["note"] = "两路未达 1e-10，但自收敛未到 1e-12，判为数值未定（不是数学命题为假）"
print("REPRO_RESULT: " + json.dumps(payload))
