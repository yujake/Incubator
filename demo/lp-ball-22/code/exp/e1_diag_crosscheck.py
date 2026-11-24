#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E1: A_diag(p) 三路对拍（纯 stdlib，确定性）。

Path A: (3/4) * int_0^{2pi} S(th)^{-2/p} dth,
        S(th) = |cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin(th)|^p
        （Gauss-Legendre，断点取 cos(th +- pi/6)=0 与 sin th=0: 0, pi/3, 2pi/3, pi, 4pi/3, 5pi/3, 2pi）
Path B: sqrt(3) * area{(x,y): |x|^p+|y|^p+|x+y|^p <= 1}
        沿 x 切片：area = 2 * int_0^{x0} L(x) dx，L(x) = |{y: |y|^p+|x+y|^p <= 1-x^p}|
        内层端点由纯二分在定义式上解出（不用任何闭式），外层用 tanh-sinh(DE) 积掉端点代数奇性。
Path C: 平面上的 Green 公式边界积分：area = sum_{6 段光滑弧} (1/2) int lam(u)^2 (A B' - B A') du，
        lam(u) 由二分在定义式上解出；外加固定种子的粗蒙特卡洛（只作几何 sanity，精度 ~1e-3）。

协议：stdout 打 PROGRESS 行（每个 p 一行）与一行 REPRO_RESULT。
"""
import math, json, random, time

PI = math.pi
SQRT3 = math.sqrt(3.0)


# ---------------- 数值工具 ----------------
def gl_nodes(n):
    xs = [0.0] * n
    ws = [0.0] * n
    m = (n + 1) // 2
    for i in range(m):
        z = math.cos(PI * (i + 0.75) / (n + 0.5))
        pp = 1.0
        for _ in range(100):
            p1 = 1.0
            p2 = 0.0
            for j in range(1, n + 1):
                p3 = p2
                p2 = p1
                p1 = ((2.0 * j - 1.0) * z * p2 - (j - 1.0) * p3) / j
            pp = n * (z * p1 - p2) / (z * z - 1.0)
            z1 = z
            z = z1 - p1 / pp
            if abs(z - z1) < 1e-16:
                break
        xs[i] = -z
        xs[n - 1 - i] = z
        w = 2.0 / ((1.0 - z * z) * pp * pp)
        ws[i] = w
        ws[n - 1 - i] = w
    return xs, ws


_GLC = {}


def gl(n):
    if n not in _GLC:
        _GLC[n] = gl_nodes(n)
    return _GLC[n]


def gl_int(f, a, b, n=300):
    xs, ws = gl(n)
    mid = 0.5 * (a + b)
    half = 0.5 * (b - a)
    s = 0.0
    for x, w in zip(xs, ws):
        s += w * f(mid + half * x)
    return s * half


def de_int(f, a, b, h=0.0625, T=6.5):
    """tanh-sinh (double exponential) 求积，处理端点代数奇性。"""
    mid = 0.5 * (a + b)
    half = 0.5 * (b - a)
    s = 0.0
    k = 0
    while k * h <= T:
        t = k * h
        signs = (1.0,) if k == 0 else (1.0, -1.0)
        for sg in signs:
            tt = sg * t
            u = PI / 2.0 * math.sinh(tt)
            if abs(u) > 330.0:
                continue
            eu = math.exp(u)
            emu = math.exp(-u)
            den = eu + emu
            x = (eu - emu) / den
            if 1.0 - abs(x) <= 0.0:
                continue
            w = (PI / 2.0) * math.cosh(tt) * 4.0 / (den * den)
            s += w * f(mid + half * x)
        k += 1
    return s * half * h


# ---------------- Path A ----------------
BPS = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]


def a_diag_1d(p, n=300):
    def f(th):
        s = (abs(math.cos(th - PI / 6.0)) ** p
             + abs(math.cos(th + PI / 6.0)) ** p
             + abs(math.sin(th)) ** p)
        return s ** (-2.0 / p)
    tot = 0.0
    for a, b in zip(BPS[:-1], BPS[1:]):
        tot += gl_int(f, a, b, n)
    return 0.75 * tot


# ---------------- Path B ----------------
def _slice_len(x, p):
    c = 1.0 - x ** p
    if c <= 0.0:
        return 0.0
    pmin = 2.0 * (x / 2.0) ** p
    if c < pmin:
        return 0.0
    ystar = -0.5 * x
    cr = c ** (1.0 / p)
    lo, hi = ystar, cr
    for _ in range(200):
        m = 0.5 * (lo + hi)
        if abs(m) ** p + abs(x + m) ** p < c:
            lo = m
        else:
            hi = m
        if hi - lo < 1e-17 * (1.0 + abs(lo)):
            break
    yhi = 0.5 * (lo + hi)
    lo, hi = -x - cr, ystar
    for _ in range(200):
        m = 0.5 * (lo + hi)
        if abs(m) ** p + abs(x + m) ** p > c:
            lo = m
        else:
            hi = m
        if hi - lo < 1e-17 * (1.0 + abs(lo)):
            break
    ylo = 0.5 * (lo + hi)
    return yhi - ylo


def a_diag_2d_slices(p, h=0.0625):
    x0 = (1.0 + 2.0 ** (1.0 - p)) ** (-1.0 / p)
    area = 2.0 * de_int(lambda x: _slice_len(x, p), 0.0, x0, h=h)
    return SQRT3 * area


# ---------------- Path C ----------------
ARCS = [((1.0, 0.0), (0.0, 1.0)),
        ((0.0, 1.0), (-1.0, 1.0)),
        ((-1.0, 1.0), (-1.0, 0.0)),
        ((-1.0, 0.0), (0.0, -1.0)),
        ((0.0, -1.0), (1.0, -1.0)),
        ((1.0, -1.0), (1.0, 0.0))]


def _lam(A, B, p):
    def h(r):
        return abs(r * A) ** p + abs(r * B) ** p + abs(r * (A + B)) ** p - 1.0
    lo = 0.0
    hi = 1.0
    while h(hi) < 0.0:
        hi *= 2.0
        if hi > 1e12:
            return hi
    for _ in range(200):
        m = 0.5 * (lo + hi)
        if h(m) < 0.0:
            lo = m
        else:
            hi = m
        if hi - lo <= 1e-16 * (1.0 + hi):
            break
    return 0.5 * (lo + hi)


def area_green(p, h=0.0625):
    total = 0.0
    for d0, d1 in ARCS:
        A0, B0 = d0
        A1, B1 = d1
        dA = A1 - A0
        dB = B1 - B0

        def f(u, A0=A0, B0=B0, dA=dA, dB=dB):
            A = A0 + dA * u
            B = B0 + dB * u
            lam = _lam(A, B, p)
            return lam * lam * (A * dB - B * dA)
        total += 0.5 * de_int(f, 0.0, 1.0, h=h)
    return total


def a_diag_2d_green(p):
    return SQRT3 * area_green(p)


def a_diag_mc(p, n=2000000, seed=20261124, L=1.1):
    random.seed(seed)
    cnt = 0
    for _ in range(n):
        x = random.uniform(-L, L)
        y = random.uniform(-L, L)
        if abs(x) ** p + abs(y) ** p + abs(x + y) ** p <= 1.0:
            cnt += 1
    area = (2.0 * L) ** 2 * cnt / float(n)
    return SQRT3 * area


def main():
    t0 = time.time()
    ps = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 20.0, 50.0]
    rows = []
    worst = 0.0
    worst_p = None
    seconds = {}
    for p in ps:
        ta = time.time()
        a = a_diag_1d(p)
        b = a_diag_2d_slices(p)
        rel = abs(a - b) / max(abs(a), 1e-300)
        seconds[str(p)] = round(time.time() - ta, 4)
        rows.append({"p": p, "A_1d": a, "A_2d_slice": b, "rel_ab": rel})
        if rel > worst:
            worst = rel
            worst_p = p
        print("PROGRESS: " + json.dumps({"stage": "A_vs_B", "p": p, "A_1d": a,
                                          "A_2d_slice": b, "rel": rel}))
    exact1 = 3.0 * SQRT3 / 4.0
    a1 = rows[0]["A_1d"]
    rel_exact1 = abs(a1 - exact1) / exact1
    print("PROGRESS: " + json.dumps({"stage": "exact_p1", "A_1d": a1, "exact": exact1,
                                      "rel": rel_exact1}))
    # 第三条路：只在一部分 p 上做
    c_rows = []
    for p in [1.5, 3.0, 10.0]:
        ta = time.time()
        a = a_diag_1d(p)
        g = a_diag_2d_green(p)
        m = a_diag_mc(p)
        rel_g = abs(a - g) / max(abs(a), 1e-300)
        rel_m = abs(a - m) / max(abs(a), 1e-300)
        c_rows.append({"p": p, "A_1d": a, "A_green": g, "rel_green": rel_g,
                       "A_mc": m, "rel_mc": rel_m, "sec": round(time.time() - ta, 3)})
        print("PROGRESS: " + json.dumps({"stage": "C_green_mc", "p": p, "A_1d": a,
                                          "A_green": g, "rel_green": rel_g,
                                          "A_mc": m, "rel_mc": rel_m}))
    # 判决（全部由读数判，不经模型）
    ab_tol = 1e-10
    hard_tol = 1e-6
    c_tol = 1e-6
    ab_bad = [r for r in rows if not (r["rel_ab"] < ab_tol)]
    ab_hard_bad = [r for r in rows if not (r["rel_ab"] < hard_tol)]
    c_bad = [r for r in c_rows if not (r["rel_green"] < c_tol)]
    if ab_hard_bad:
        result = "refutes"
        counterexample = {"p": ab_hard_bad[0]["p"], "A_1d": ab_hard_bad[0]["A_1d"],
                          "A_2d_slice": ab_hard_bad[0]["A_2d_slice"],
                          "rel": ab_hard_bad[0]["rel_ab"]}
        why = "path A 与 path B 的相对偏差超过 1e-6（不是精度问题）"
    elif ab_bad:
        result = "inconclusive"
        counterexample = None
        why = "path A/B 偏差超过 1e-10 但小于 1e-6：落在数值精度档，不足以判命题真假"
    elif c_bad:
        result = "inconclusive"
        counterexample = None
        why = "path A/B 一致，但第三条路（Green 边界积分）没到 1e-6"
    else:
        result = "supports"
        counterexample = None
        why = "11 个 p 上 A/B 相对偏差均 < 1e-10，且 p in {1.5,3,10} 的 Green/MC 交叉核对达标"
    payload = {
        "result": result,
        "bound": "p in {1,1.25,1.5,2,2.5,3,4,6,10,20,50}（A/B）；p in {1.5,3,10}（C）",
        "strategy": "A: Gauss-Legendre(300)x6 段（按 cos(th+-pi/6)=0, sin th=0 切开）; "
                    "B: x 切片 + tanh-sinh(DE) 外层 + 定义式二分内层; "
                    "C: Green 定理 6 段弧 + 定义式二分 + 固定种子 MC(2e6)",
        "scaling": seconds,
        "exact_p1": {"A_1d": a1, "exact": exact1, "rel": rel_exact1},
        "worst_ab": {"rel": worst, "p": worst_p},
        "path_C": c_rows,
        "per_p": rows,
        "why": why,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    if counterexample is not None:
        payload["counterexample"] = counterexample
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
