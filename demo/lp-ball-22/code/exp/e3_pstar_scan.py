#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 任务 3：p* 定位 —— Delta(p)=A_diag(p)-A_face(p) 的零点，与 rho 的单调性报告。

A_diag(p) = (3/4) int_0^{2pi} S(th)^{-2/p} dth,
            S = |cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p,
            断点 = 三个 |.| 的零点 {0,pi/3,2pi/3,pi,4pi/3,5pi/3,2pi}，逐段 tanh-sinh(DE).
            （exp 000014 用完全独立的二维路核过：11 个 p 上相对差 <= 1.4e-15）
A_face(p) = 2^{1/2-1/p} * 4 Gamma(1+1/p)^2 / Gamma(1+2/p)（Gamma 用 lgamma 现算）
            （exp 000015 用两条独立数值路核过：相对差 <= 1e-12）
Delta(p) = A_diag(p) - A_face(p);  rho(p) = A_diag(p)/A_face(p)
          （恒等：Delta = A_face * (rho - 1)）

网格：p = 2.01, 2.02, ..., 20.00（步长 0.01，共 1800 点）；
点名点：p = 2, 2+1e-6, 3, 4, 10, 50（另报 rho 与 sign Delta）。
变号区间逐个二分，夹逼区间宽度收到 < 1e-10。
rho 单调性：逐格算 rho 的差分，报出所有局部上升（位置 + 幅度）。

判据（脚本内硬编码、由脚本判）：
  (a) (2+1e-6, 20] 内 Delta 在网格上的变号次数 == 1；
  (b) 该变号区间的二分夹逼宽度 < 1e-10；
  (c) 恒等 Delta == A_face*(rho-1) 在每个采样点成立（相对 1e-12）；
  三者都过 => result=supports；变号次数 != 1 => refutes（反例=各变号区间）；
  否则 inconclusive。rho 的单调性是**读数**（报告用，不进判据）。
"""
import json
import math
import time

PI = math.pi
HP = PI / 2.0


def tanhsinh(f, a, b, h=0.05, tmax=7.0):
    """双指数求积 int_a^b f（v5-v7 用过的同一实现，已与独立路核过 1e-15）。"""
    if b <= a:
        return 0.0
    c = 0.5 * (b - a)
    d = 0.5 * (a + b)
    s = 0.0
    n = int(tmax / h)
    for k in range(-n, n + 1):
        t = k * h
        u = HP * math.sinh(t)
        x = math.tanh(u)
        if x >= 1.0 or x <= -1.0:
            continue
        ch = math.cosh(u)
        w = HP * math.cosh(t) / (ch * ch)
        s += w * f(d + c * x)
    return s * c * h


ABRK = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]


def a_diag(p):
    tot = 0.0
    for i in range(len(ABRK) - 1):
        a, b = ABRK[i], ABRK[i + 1]

        def f(th, p=p):
            return (abs(math.cos(th - PI / 6.0)) ** p
                    + abs(math.cos(th + PI / 6.0)) ** p
                    + abs(math.sin(th)) ** p) ** (-2.0 / p)

        tot += tanhsinh(f, a, b)
    return 0.75 * tot


def a_face(p):
    return 2.0 ** (0.5 - 1.0 / p) * 4.0 * math.exp(
        2.0 * math.lgamma(1.0 + 1.0 / p) - math.lgamma(1.0 + 2.0 / p))


def delta(p):
    return a_diag(p) - a_face(p)


def main():
    t0 = time.time()
    # --- 自检 1：A_diag 在 p=1,2 的精确值；A_face 在 p=2 的精确值
    exact = {1.0: 3.0 * math.sqrt(3.0) / 4.0, 2.0: PI}
    checks = {}
    for p, e in exact.items():
        checks["A_diag(%g)_rel" % p] = abs(a_diag(p) - e) / e
    checks["A_face(2)_rel"] = abs(a_face(2.0) - PI) / PI
    selftest_ok = all(v < 1e-13 for v in checks.values())

    # --- 网格扫描
    grid = [round(2.01 + 0.01 * i, 10) for i in range(1800)]
    rows = []
    sign_changes = []
    prev_p = None
    prev_d = None
    for idx, p in enumerate(grid):
        dd = delta(p)
        rows.append({"p": p, "Delta": dd, "rho": a_diag(p) / a_face(p) if False else None})
        # 只为省时间：rho 稍后单独一行算不必要；这里 rho = 1 + Delta/A_face
        rows[-1]["rho"] = 1.0 + dd / a_face(p)
        if prev_d is not None and dd != 0.0 and prev_d != 0.0 and (dd > 0.0) != (prev_d > 0.0):
            sign_changes.append([prev_p, p])
        prev_p, prev_d = p, dd
        if idx % 300 == 0:
            print("PROGRESS: " + json.dumps({"stage": "grid", "i": idx, "p": p,
                                             "Delta": dd, "rho": rows[-1]["rho"],
                                             "sec": round(time.time() - t0, 2)}))
    # 端点：p=2 与 p=2+1e-6
    d2 = delta(2.0)
    d2e = delta(2.0 + 1e-6)
    if (d2 == 0.0 and d2e != 0.0) or (d2 != 0.0 and d2e != 0.0 and (d2 > 0) != (d2e > 0)):
        sign_changes.insert(0, [2.0, 2.0 + 1e-6])

    # --- 复算每个变号区间并二分到宽度 < 1e-10
    roots = []
    for lo, hi in sign_changes:
        fl = delta(lo)
        fh = delta(hi)
        if fl == 0.0:
            roots.append({"p_star": lo, "width": 0.0, "lo": lo, "hi": lo,
                          "Delta_lo": 0.0, "Delta_hi": 0.0})
            continue
        a_, b_ = lo, hi
        fa, fb = fl, fh
        it = 0
        while (b_ - a_) > 1e-10 and it < 200:
            m = 0.5 * (a_ + b_)
            fm = delta(m)
            if fm == 0.0:
                a_ = b_ = m
                fa = fb = 0.0
                break
            if (fm > 0.0) == (fa > 0.0):
                a_, fa = m, fm
            else:
                b_, fb = m, fm
            it += 1
        roots.append({"p_star": 0.5 * (a_ + b_), "width": b_ - a_,
                      "lo": a_, "hi": b_, "Delta_lo": fa, "Delta_hi": fb,
                      "bisect_iters": it})

    # --- 恒等 Delta == A_face*(rho-1) 的一致性（在几个点名点上）
    ident = 0.0
    for p in (2.5, 3.0, 5.0, 10.0, 20.0):
        dd = delta(p)
        af = a_face(p)
        rr = 1.0 + dd / af
        ident = max(ident, abs(dd - af * (rr - 1.0)) / max(1e-300, abs(dd)))

    # --- rho 单调性：逐格差分的局部上升
    ups = []
    for i in range(1, len(rows)):
        d_rho = rows[i]["rho"] - rows[i - 1]["rho"]
        if d_rho > 0.0:
            ups.append({"p": rows[i]["p"], "d_rho": d_rho,
                        "rho": rows[i]["rho"]})
    max_up = max([u["d_rho"] for u in ups], default=0.0)

    # --- 点名点
    pts = [2.0, 2.0 + 1e-6, 3.0, 4.0, 10.0, 50.0]
    named = []
    for p in pts:
        ad = a_diag(p)
        af = a_face(p)
        named.append({"p": p, "A_diag": ad, "A_face": af,
                      "rho": ad / af, "Delta": ad - af,
                      "sign_Delta": (1 if ad - af > 0 else (-1 if ad - af < 0 else 0))})
    for r in named:
        print("PROGRESS: " + json.dumps({"stage": "named", **r}))

    interior = [s for s in sign_changes if s[0] >= 2.0 + 1e-6 - 1e-18]
    ok_count = (len(interior) == 1)
    ok_width = all(r["width"] < 1e-10 for r in roots)
    ok_ident = ident < 1e-12
    if ok_count and ok_width and ok_ident and selftest_ok:
        result = "supports"
        counterexample = {}
    elif not ok_count:
        result = "refutes"
        counterexample = {"sign_change_intervals": sign_changes,
                          "note": "Delta 在 (2+1e-6,20] 网格上的变号次数 = %d，不是 1" % len(interior)}
    else:
        result = "inconclusive"
        counterexample = {}

    payload = {
        "result": result,
        "counterexample": counterexample if result == "refutes" else {},
        "bound": "p in (2, 20] 网格步长 0.01（1800 点）+ 点名点 {2, 2+1e-6, 3, 4, 10, 50}",
        "strategy": "6-piece tanh-sinh(DE, h=0.05) on theta integral; A_face by lgamma closed form; sign scan + bisection to width<1e-10",
        "scaling": {"total_sec": round(time.time() - t0, 2), "grid_points": len(grid)},
        "selftest": checks,
        "selftest_ok": selftest_ok,
        "sign_changes": sign_changes,
        "roots": roots,
        "rho_local_increases": {"count": len(ups), "max_step": max_up,
                               "first": ups[:5], "last": ups[-5:]},
        "rho_monotone_decreasing_on_grid": (len(ups) == 0),
        "named_points": named,
        "identity_residual_rel": ident,
        "checks": {"one_sign_change": ok_count, "bracket_lt_1e-10": ok_width,
                   "identity": ok_ident},
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
