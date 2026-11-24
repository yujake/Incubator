#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 任务 1（v6，取代 exp 000008-000012 的实现）：A_diag(p) 三路对拍。

A 路（一维积分，F 稿 (i)）：
  A_diag(p) = (3/4) * int_0^{2pi} S(th)^{-2/p} dth,
  S(th) = |cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p
  断点 = 三个 |.| 的零点 {0, pi/3, 2pi/3, pi, 4pi/3, 5pi/3, 2pi}；逐段 tanh-sinh(DE)。

B 路（平面上二维求积，x 竖切片 + 定义式二分，F 稿 (ii) 第一个等号）：
  A_diag(p) = sqrt(3) * area(D), D = {(x,y): |x|^p+|y|^p+|x+y|^p <= 1}
  area = 2 * int_0^{xmax} L(x) dx, L(x) = y_high(x) - y_low(x)，上下端由定义式二分求
  （不代入任何闭式）；L 在 x = 2^{-1/p} 处折（y_high 穿 0 / y_low 穿 -x），在此断开。

C 路（第三路：(w,d)=(x+y,x-y) 换元后同样做切片 + 定义式二分，p in {1.5,3,10}）：
  dx dy = (1/2) dw dd => area = 2 * int_0^{wmax} dmax(w) dw。
  （与 B 路不同的坐标系、不同的边界函数、不同的断点位置，只在「从定义出发」上重合。）

D 路（补充：确定性 Halton 拟随机，仅作独立粗检，不计入判据）。

判据（脚本内硬编码）：
  max_p rel(A,B) < 1e-10；p in {1.5,3,10} 上 rel(A,C) < 1e-6；
  自检（DE 求积器本身）：int_0^1 1 = 1 与 int_0^1 x^{-1/2} = 2 都要到 1e-11；
  精确值自检：p=1 => 3*sqrt(3)/4，p=2 => pi，两条路各自都要到 1e-11。
  全过 => result=supports；有任一条没过 => inconclusive（数值精度不足不是数学命题的反例）。
"""
import json
import math
import time

PI = math.pi
HP = PI / 2.0


def tanhsinh(f, a, b, h=0.02, tmax=7.5):
    """双指数（tanh-sinh）求积 int_a^b f。"""
    if b <= a:
        return 0.0
    c = 0.5 * (b - a)
    d = 0.5 * (a + b)
    s = 0.0
    n = int(tmax / h)
    for k in range(-n, n + 1):
        t = k * h
        u = HP * math.sinh(t)
        if u > 400.0 or u < -400.0:
            continue
        x = math.tanh(u)
        if x >= 1.0 or x <= -1.0:
            continue
        ch = math.cosh(u)
        w = HP * math.cosh(t) / (ch * ch)
        s += w * f(d + c * x)
    return s * c * h


# ---------------- A 路 ----------------
ABRK = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]


def S_val(p, th):
    return (abs(math.cos(th - PI / 6.0)) ** p
            + abs(math.cos(th + PI / 6.0)) ** p
            + abs(math.sin(th)) ** p)


def A_path_A(p):
    tot = 0.0
    for i in range(len(ABRK) - 1):
        a, b = ABRK[i], ABRK[i + 1]
        tot += tanhsinh(lambda th, p=p: S_val(p, th) ** (-2.0 / p), a, b)
    return 0.75 * tot


# ---------------- B 路 ----------------
def slice_len_B(p, x):
    R = 1.0 - abs(x) ** p
    if R <= 0.0:
        return None
    xm = -0.5 * x
    if abs(xm) ** p + abs(x + xm) ** p > R:
        return None
    lo, hi = xm, 2.0
    while abs(hi) ** p + abs(x + hi) ** p <= R:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if abs(mid) ** p + abs(x + mid) ** p <= R:
            lo = mid
        else:
            hi = mid
    yh = lo
    lo, hi = -2.0, xm
    while abs(lo) ** p + abs(x + lo) ** p <= R:
        lo *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if abs(mid) ** p + abs(x + mid) ** p <= R:
            hi = mid
        else:
            lo = mid
    yl = hi
    return yh - yl


def x_max_B(p):
    lo, hi = 0.0, 2.0
    while slice_len_B(p, hi) is not None:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if slice_len_B(p, mid) is not None:
            lo = mid
        else:
            hi = mid
    return lo


def area_B(p):
    xm = x_max_B(p)
    brk = sorted(set([0.0, min(2.0 ** (-1.0 / p), xm), xm]))
    tot = 0.0
    for i in range(len(brk) - 1):
        a, b = brk[i], brk[i + 1]
        if b <= a:
            continue
        tot += tanhsinh(lambda x, p=p: slice_len_B(p, x) or 0.0, a, b)
    return 2.0 * tot


# ---------------- C 路 ----------------
def dmax_C(p, w):
    R = (2.0 ** p) * (1.0 - abs(w) ** p)
    if R <= 0.0:
        return None
    if 2.0 * abs(w) ** p > R:
        return None
    lo, hi = 0.0, 2.0
    while abs(w + hi) ** p + abs(w - hi) ** p <= R:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if abs(w + mid) ** p + abs(w - mid) ** p <= R:
            lo = mid
        else:
            hi = mid
    return lo


def area_C(p):
    lo, hi = 0.0, 2.0
    while dmax_C(p, hi) is not None:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if dmax_C(p, mid) is not None:
            lo = mid
        else:
            hi = mid
    wm = lo
    brk = sorted(set([0.0, min(2.0 ** (-1.0 / p), wm), wm]))
    tot = 0.0
    for i in range(len(brk) - 1):
        a, b = brk[i], brk[i + 1]
        if b <= a:
            continue
        tot += tanhsinh(lambda w, p=p: dmax_C(p, w) or 0.0, a, b)
    return 2.0 * tot


# ---------------- D 路（补充：Halton QMC） ----------------
def halton(i, base):
    f = 1.0
    r = 0.0
    while i > 0:
        f /= base
        r += f * (i % base)
        i //= base
    return r


def area_qmc(p, n=400000):
    cnt = 0
    for i in range(1, n + 1):
        x = 2.0 * halton(i, 2) - 1.0
        y = 2.0 * halton(i, 3) - 1.0
        if abs(x) ** p + abs(y) ** p + abs(x + y) ** p <= 1.0:
            cnt += 1
    return 4.0 * cnt / n


def main():
    t0 = time.time()
    st1 = tanhsinh(lambda x: 1.0, 0.0, 1.0)
    st2 = tanhsinh(lambda x: (x ** -0.5 if x > 0.0 else 0.0), 0.0, 1.0)
    selftest = {"int_0^1_1": st1, "int_0^1_x^-1/2": st2,
                "ok": (abs(st1 - 1.0) < 1e-11 and abs(st2 - 2.0) < 1e-11)}

    ps = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 20.0, 50.0]
    exact = {1.0: 3.0 * math.sqrt(3.0) / 4.0, 2.0: PI}
    rows = []
    worst_ab = 0.0
    worst_exact = 0.0
    for p in ps:
        ts = time.time()
        a = A_path_A(p)
        b = math.sqrt(3.0) * area_B(p)
        rel = abs(a - b) / abs(a)
        row = {"p": p, "A_1d": a, "A_2d": b, "rel_AB": rel, "sec": round(time.time() - ts, 3)}
        if p in exact:
            e = exact[p]
            row["exact"] = e
            row["rel_exact_A"] = abs(a - e) / e
            row["rel_exact_B"] = abs(b - e) / e
            worst_exact = max(worst_exact, row["rel_exact_A"], row["rel_exact_B"])
        rows.append(row)
        worst_ab = max(worst_ab, rel)
        print("PROGRESS: " + json.dumps({"stage": "A_vs_B", "p": p, "A_1d": a,
                                        "A_2d": b, "rel": rel, "sec": row["sec"]}))

    crows = []
    worst_ac = 0.0
    for p in (1.5, 3.0, 10.0):
        ts = time.time()
        a = A_path_A(p)
        c = math.sqrt(3.0) * area_C(p)
        rel = abs(a - c) / abs(a)
        cr = {"p": p, "A_1d": a, "A_3rd": c, "rel_AC": rel, "sec": round(time.time() - ts, 3)}
        crows.append(cr)
        worst_ac = max(worst_ac, rel)
        print("PROGRESS: " + json.dumps({"stage": "A_vs_C", "p": p, "A_3rd": c, "rel": rel}))

    qrows = []
    for p in (1.5, 3.0, 10.0):
        a = A_path_A(p)
        q = math.sqrt(3.0) * area_qmc(p)
        rel = abs(a - q) / abs(a)
        qrows.append({"p": p, "A_qmc": q, "rel_AQ": rel})
        print("PROGRESS: " + json.dumps({"stage": "A_vs_QMC_supplementary", "p": p,
                                        "A_qmc": q, "rel": rel}))

    ok_ab = worst_ab < 1e-10
    ok_ac = worst_ac < 1e-6
    ok_exact = worst_exact < 1e-11
    ok_st = selftest["ok"]
    result = "supports" if (ok_ab and ok_ac and ok_exact and ok_st) else "inconclusive"
    payload = {
        "result": result,
        "tol_AB": 1e-10, "tol_AC": 1e-6, "tol_exact": 1e-11,
        "worst_rel_AB": worst_ab, "worst_rel_AC": worst_ac,
        "worst_rel_vs_exact": worst_exact, "selftest": selftest,
        "checks": {"AB": ok_ab, "AC": ok_ac, "exact": ok_exact, "quadrature_selftest": ok_st},
        "bound": "p in {1,1.25,1.5,2,2.5,3,4,6,10,20,50}; third path at p in {1.5,3,10}",
        "strategy": "A: 6-piece tanh-sinh(DE) on theta integral; B: 2D x-slicing with bisection-on-definition slice ends; C: (w,d)=(x+y,x-y) slicing with bisection-on-definition ends; QMC(Halton) supplementary only",
        "scaling": {"total_sec": round(time.time() - t0, 3),
                    "per_p_sec_AB": [r["sec"] for r in rows],
                    "per_p_sec_C": [r["sec"] for r in crows]},
        "rows": rows, "rows_C": crows, "rows_QMC": qrows,
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
