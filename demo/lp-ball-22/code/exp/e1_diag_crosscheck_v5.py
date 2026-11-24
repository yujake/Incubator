#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 实验（任务 1，取代 exp 000008/000009/000010/000011 的实现）：A_diag(p) 三路对拍。

A 路（一维积分，F 稿 (i)）：
  A_diag(p) = (3/4) * int_0^{2pi} S(th)^{-2/p} dth,
  S(th) = |cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p
  断点 = 三个 |.| 的零点 {0, pi/3, 2pi/3, pi, 4pi/3, 5pi/3, 2pi}；逐段 tanh-sinh（双指数）。

B 路（平面上直接二维求积：x 切片 + 定义式二分，F 稿 (ii) 的第一个等号）：
  A_diag(p) = sqrt(3) * area(D),  D = {(x,y): |x|^p+|y|^p+|x+y|^p <= 1}
  area = 2 * int_0^{xmax} L(x) dx,  L(x) = y_high(x) - y_low(x)
  y_high / y_low 由**定义式** h(y)=|y|^p+|x+y|^p <= R(x)=1-|x|^p 二分求解（不代入任何闭式）。
  断点 0, min(2^{-1/p}, xmax), xmax —— 在 2^{-1/p} 处 y_high 穿过 0、y_low 穿过 -x，
  两段内 L(x) 解析（隐函数定理），故 tanh-sinh 可达机器精度。

C 路（第三路，p in {1.5,3,10}）：(w,d) = (x+y, x-y) 坐标
  dx dy = (1/2) dw dd  =>  area = 2 * int_0^{wmax} dmax(w) dw,
  dmax 由定义式 |w+d|^p + |w-d|^p <= 2^p (1-|w|^p) 二分求解；断点 0, min(2^{-1/p}, wmax), wmax。

判据（脚本内硬编码，由脚本判）：max_p rel(A,B) < 1e-10；p in {1.5,3,10}: rel(A,C) < 1e-6。
自检：A(1)=3*sqrt(3)/4、A(2)=pi（两条路各自都要过 1e-11）；自检不过 => inconclusive。
"""
import json
import math
import time

PI = math.pi
HP = PI / 2.0


def tanhsinh(f, a, b, h=0.05, tmax=7.0):
    """双指数（tanh-sinh）求积：int_a^b f；对端点代数/对数奇性与折点稳健。"""
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
    """L(x) = |{y: |y|^p+|x+y|^p <= 1-|x|^p}|；端点由定义式二分求。空集 => None。"""
    R = 1.0 - abs(x) ** p
    if R <= 0.0:
        return None
    xm = -0.5 * x
    if abs(xm) ** p + abs(x + xm) ** p > R:
        return None
    # y_high（最大可行 y），起点 xm 可行、2.0 不可行
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
    # y_low（最小可行 y），起点 -2.0 不可行、xm 可行
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


def main():
    t0 = time.time()
    st1 = tanhsinh(lambda x: 1.0, 0.0, 1.0)
    st2 = tanhsinh(lambda x: (x ** -0.5 if x > 0.0 else 0.0), 0.0, 1.0)
    selftest = {"int_0^1_1": st1, "int_0^1_x^-1/2": st2,
                "ok": (abs(st1 - 1.0) < 1e-13 and abs(st2 - 2.0) < 1e-12)}

    ps = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 20.0, 50.0]
    exact = {1.0: 3.0 * math.sqrt(3.0) / 4.0, 2.0: PI}
    rows = []
    worst_ab = 0.0
    worst_exact = 0.0
    for p in ps:
        ts = time.time()
        a = A_path_A(p)
        b = math.sqrt(3.0) * area_B(p)
        rel = abs(a - b) / abs(a) if a != 0.0 else float('inf')
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
        print("PROGRESS: " + json.dumps({"stage": "A_vs_C", "p": p, "A_1d": a,
                                        "A_3rd": c, "rel": rel}))

    ok_ab = worst_ab < 1e-10
    ok_ac = worst_ac < 1e-6
    ok_exact = worst_exact < 1e-11
    result = "supports" if (selftest["ok"] and ok_ab and ok_ac and ok_exact) else "inconclusive"
    payload = {
        "result": result,
        "tol_AB": 1e-10,
        "tol_AC": 1e-6,
        "tol_exact": 1e-11,
        "worst_rel_AB": worst_ab,
        "worst_rel_AC": worst_ac,
        "worst_rel_vs_exact": worst_exact,
        "selftest": selftest,
        "bound": "p in {1,1.25,1.5,2,2.5,3,4,6,10,20,50}; third path at p in {1.5,3,10}",
        "strategy": "A: 6-piece tanh-sinh on theta integral; B: 2D x-slicing with bisection-on-definition slice ends (breakpoint at 2^{-1/p}); C: (w,d)=(x+y,x-y) slicing with bisection-on-definition ends",
        "scaling": {"total_sec": round(time.time() - t0, 3),
                    "per_p_sec_AB": [r["sec"] for r in rows],
                    "per_p_sec_C": [r["sec"] for r in crows]},
        "rows": rows,
        "rows_C": crows,
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
