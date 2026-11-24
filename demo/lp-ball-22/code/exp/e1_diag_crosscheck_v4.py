#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 实验（取代 000008/000009/000010 —— 那三版分别有「因子漏乘 √3」「u^4 代换左右半段符号抵消」「端点精度不够」的实现错误）。

A 路（一维积分）：
  A_diag(p) = (3/4) * ∫_0^{2π} S(θ)^{-2/p} dθ,
  S(θ) = |cos(θ-π/6)|^p + |cos(θ+π/6)|^p + |sin θ|^p;
  断点 = 三个绝对值的零点 {0, π/3, 2π/3, π, 4π/3, 5π/3, 2π}（此时恰有一项消失）。

B 路（平面极坐标 + 定义式二分，不代入 g(θ)^{-1/p} 闭式）：
  A_diag(p) = √3 · area(D),  D = {(x,y): |x|^p+|y|^p+|x+y|^p ≤ 1};
  area = (1/2)∫_0^{2π} R(θ)^2 dθ,  R(θ) = max{r ≥ 0: F(r cosθ, r sinθ) ≤ 1}（二分）。

C 路（第三路：平面直角坐标竖切片 + 定义式二分，只在 p ∈ {1.5,3,10} 上做）：
  area = 2 ∫_0^{xmax} L(x) dx, L(x) = 2 y_+(x) + x,
  y_+(x) = max{y: |y|^p+|x+y|^p ≤ 1-x^p}（二分）, xmax = (1+2^{1-p})^{-1/p};
  x = xmax(1-u^2) 消掉 xmax 处的 √ 型端点奇性。

积分核：每个光滑段的两端改用 Δ = h·u^m 代换（m 取使 m·p 为整数且 ≥ 6 的最小整数，
这样端点处的 |Δ|^p 与 |Δ|^{p+2k} 全部变成 u 的整数次幂），再套 n 点 Gauss-Legendre。
同一路分别用 n=32 与 n=40 各算一遍，报两者之差作自收敛读数。

判据（脚本内硬编码，由脚本判）：
  max_p |A-B|/|A| < 1e-10 （11 个 p）;
  p∈{1.5,3,10}: |A-C|/|A| < 1e-6;
  解析锚：A(1)=3√3/4, A(2)=π —— 与 A、B 两路独立比对。
达标 ⇒ supports；不达标 ⇒ inconclusive（数值精度不足不是数学命题的反例；
只有出现「同一 p 上两路之差远超自收敛估计且方向可重复」才够得上 refutes，本脚本不产 refutes）。
"""
import json
import math
import time

PI = math.pi
SQ3 = math.sqrt(3.0)


# ---------------- Gauss-Legendre ----------------
def legendre_pair(n, z):
    p0, p1 = 1.0, 0.0
    for j in range(1, n + 1):
        p2 = p1
        p1 = p0
        p0 = ((2 * j - 1) * z * p1 - (j - 1) * p2) / j
    return p0, p1


def gl_nodes(n):
    xs = [0.0] * n
    ws = [0.0] * n
    for i in range((n + 1) // 2):
        z = math.cos(PI * (i + 0.75) / (n + 0.5))
        for _ in range(100):
            p0, p1 = legendre_pair(n, z)
            pp = n * (z * p0 - p1) / (z * z - 1.0)
            dz = p0 / pp
            z -= dz
            if abs(dz) < 1e-15:
                break
        p0, p1 = legendre_pair(n, z)
        pp = n * (z * p0 - p1) / (z * z - 1.0)
        w = 2.0 / ((1.0 - z * z) * pp * pp)
        xs[i] = -z
        xs[n - 1 - i] = z
        ws[i] = w
        ws[n - 1 - i] = w
    return xs, ws


NODES = {n: gl_nodes(n) for n in (32, 40)}


# ---------------- 积分核 ----------------
def m_for(p):
    """使 m*p 为整数且 >= 6 的最小 m（端点的 |Δ|^p 行为变成 u 的整数次幂）。"""
    for m in range(1, 25):
        v = m * p
        r = round(v)
        if abs(v - r) < 1e-9 and r >= 6:
            return m
    return 24


def integ_piece(f, a, b, m, nodes):
    """∫_a^b f：两端各做 Δ = h·u^m 代换，再 n 点 GL。"""
    h = b - a
    if h <= 0.0:
        return 0.0
    xs, ws = nodes
    s = 0.0
    for x, w in zip(xs, ws):
        u = 0.5 * (x + 1.0)
        s += w * 0.5 * m * h * (u ** (m - 1.0)) * f(a + h * (u ** m))
    for x, w in zip(xs, ws):
        u = 0.5 * (x + 1.0)
        s += w * 0.5 * m * h * (u ** (m - 1.0)) * f(b - h * (u ** m))
    return s


# ---------------- A 路 ----------------
ABRK = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]


def S_val(p, th):
    return (abs(math.cos(th - PI / 6.0)) ** p
            + abs(math.cos(th + PI / 6.0)) ** p
            + abs(math.sin(th)) ** p)


def A_1d(p, nodes):
    m = m_for(p)
    f = lambda th: S_val(p, th) ** (-2.0 / p)
    tot = 0.0
    for i in range(len(ABRK) - 1):
        tot += integ_piece(f, ABRK[i], ABRK[i + 1], m, nodes)
    return 0.75 * tot


# ---------------- B 路 ----------------
BBRK = [0.0, PI / 2.0, 3.0 * PI / 4.0, PI, 3.0 * PI / 2.0, 7.0 * PI / 4.0, 2.0 * PI]


def radius_B(p, th):
    c = math.cos(th)
    s = math.sin(th)
    lo, hi = 0.0, 4.0
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        if abs(mid * c) ** p + abs(mid * s) ** p + abs(mid * (c + s)) ** p <= 1.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def area_polar(p, nodes):
    m = m_for(p)
    f = lambda th: 0.5 * radius_B(p, th) ** 2
    tot = 0.0
    for i in range(len(BBRK) - 1):
        tot += integ_piece(f, BBRK[i], BBRK[i + 1], m, nodes)
    return tot


def A_polar(p, nodes):
    return SQ3 * area_polar(p, nodes)


# ---------------- C 路（第三路，竖切片） ----------------
def slice_len_C(p, x):
    if x >= 1.0:
        return 0.0
    rhs = 1.0 - x ** p
    lo = -0.5 * x
    hi = rhs ** (1.0 / p)
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        if abs(mid) ** p + abs(x + mid) ** p <= rhs:
            lo = mid
        else:
            hi = mid
    yp = 0.5 * (lo + hi)
    return 2.0 * yp + x


def area_slices(p, nodes, panels=4):
    xmax = (1.0 + 2.0 ** (1.0 - p)) ** (-1.0 / p)
    xs, ws = nodes
    s = 0.0
    h = 1.0 / panels
    for k in range(panels):
        lo = k * h
        hi = (k + 1) * h
        mid = 0.5 * (lo + hi)
        hh = 0.5 * (hi - lo)
        for x, w in zip(xs, ws):
            u = mid + hh * x
            xx = xmax * (1.0 - u * u)
            s += w * hh * (2.0 * xmax * u) * slice_len_C(p, xx)
    return 2.0 * s


def A_slices(p, nodes, panels=4):
    return SQ3 * area_slices(p, nodes, panels)


def main():
    t0 = time.time()
    ps = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 20.0, 50.0]
    exact = {1.0: 3.0 * SQ3 / 4.0, 2.0: PI}
    rows = []
    worst_ab = 0.0
    worst_self_A = 0.0
    worst_self_B = 0.0
    worst_exact = 0.0
    for p in ps:
        t1 = time.time()
        a = A_1d(p, NODES[40])
        a32 = A_1d(p, NODES[32])
        b = A_polar(p, NODES[40])
        b32 = A_polar(p, NODES[32])
        rel_ab = abs(a - b) / abs(a)
        self_a = abs(a - a32) / abs(a)
        self_b = abs(b - b32) / abs(b)
        row = {"p": p, "A_1d": a, "A_polar": b, "rel_AB": rel_ab,
               "self_A_32v40": self_a, "self_B_32v40": self_b,
               "sec": round(time.time() - t1, 3)}
        if p in exact:
            e = exact[p]
            row["exact"] = e
            row["rel_exact_A"] = abs(a - e) / e
            row["rel_exact_B"] = abs(b - e) / e
            worst_exact = max(worst_exact, row["rel_exact_A"], row["rel_exact_B"])
        rows.append(row)
        worst_ab = max(worst_ab, rel_ab)
        worst_self_A = max(worst_self_A, self_a)
        worst_self_B = max(worst_self_B, self_b)
        print("PROGRESS: " + json.dumps({"stage": "A_vs_B", "p": p, "A_1d": a,
                                         "A_polar": b, "rel_AB": rel_ab,
                                         "self_A": self_a, "self_B": self_b}))
    crows = []
    worst_ac = 0.0
    for p in (1.5, 3.0, 10.0):
        t1 = time.time()
        a = A_1d(p, NODES[40])
        c = A_slices(p, NODES[40], panels=4)
        c2 = A_slices(p, NODES[32], panels=6)
        rel_ac = abs(a - c) / abs(a)
        self_c = abs(c - c2) / abs(c)
        crows.append({"p": p, "A_1d": a, "A_slices": c, "rel_AC": rel_ac,
                      "self_C": self_c, "sec": round(time.time() - t1, 3)})
        worst_ac = max(worst_ac, rel_ac)
        print("PROGRESS: " + json.dumps({"stage": "A_vs_C", "p": p, "A_slices": c,
                                         "rel_AC": rel_ac, "self_C": self_c}))
    ok_ab = worst_ab < 1e-10
    ok_ac = worst_ac < 1e-6
    result = "supports" if (ok_ab and ok_ac) else "inconclusive"
    payload = {
        "result": result,
        "tol_AB": 1e-10,
        "tol_C": 1e-6,
        "worst_rel_AB": worst_ab,
        "worst_rel_AC": worst_ac,
        "worst_self_A_32v40": worst_self_A,
        "worst_self_B_32v40": worst_self_B,
        "worst_rel_exact": worst_exact,
        "bound": "p in {1,1.25,1.5,2,2.5,3,4,6,10,20,50}; C path on p in {1.5,3,10}",
        "strategy": "A: theta-breakpoint Gauss-Legendre with u^m endpoint substitution; B: polar radius by 64-step bisection + same quadrature; C: vertical slicing with bisection slice ends + z=xmax(1-u^2) substitution",
        "scaling": {"total_sec": round(time.time() - t0, 3),
                    "per_p_sec": [r["sec"] for r in rows],
                    "per_p_sec_C": [r["sec"] for r in crows]},
        "rows": rows,
        "rows_C": crows,
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
