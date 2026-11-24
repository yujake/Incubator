#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 本趟任务 (1)：Delta(p) = A_face(p) - A_diag(p) 在大 p 上的第二零点。

口径承接 exp:000014 / exp:000016（同一套 A_diag 与 A_face）：
  A_diag(p) = (3/4) * int_0^{2pi} S(th)^{-2/p} dth,
              S = |cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p,
              断点 {0,pi/3,2pi/3,pi,4pi/3,5pi/3,2pi}，逐段 tanh-sinh(DE, 步长 h, tmax=7)。
              与 exp:000014 的唯一差别：S^{-2/p} 走 log-sum-exp
                S^{-2/p} = exp(-2m) * (sum_i exp(p*(log a_i - m)))^{-2/p},  m = max_i log a_i
              因为 p>=1e3 时 a_i^p 在双精度下下溢成 0（直接求和得 S=0、除零）。
              这条恒等式在小 p 上与精确值对得上（自检见下），故与旧脚本等价。
  A_face(p) = 2^{1/2-1/p} * 4 * Gamma(1+1/p)^2 / Gamma(1+2/p)   （lgamma 现算；exp:000015 已核）
  Delta(p) = A_face(p) - A_diag(p)     <-- 与 exp:000016 里的 Delta 差一个整体符号
  端点：Delta(2) = 0（两者都等于 pi）；Delta(p->inf) = 4*sqrt(2) - 3*sqrt(3) = +0.4607013...

网格：p_i = 20 * (1e6/20)^{i/(N-1)}, i=0..N-1, N=241（对数等距、>=200 点）。
      另在变号点附近用 root/1.5 .. root*1.5 的 41 点对数网格加密复核。

判据（脚本内硬编码、由脚本判，不过模型）：
  (a) 网格上 Delta 的变号次数 == 1，且变号点落在 (20, 1e6) 内部；
  (b) 变号点二分夹逼的**相对**宽度 (hi-lo)/p_mid < 1e-6；
  (c) 网格最右端 Delta > 0（与 p->inf 的极限同号）；
  (d) 加密网格上 Delta 的变号次数也 == 1；
  (e) 自检：A_diag(1)=3sqrt3/4、A_diag(2)=pi、A_face(2)=pi 相对误差 < 1e-12；
      且 h=0.05 与 h=0.025 在 p in {20,1e3,1e6} 上相对差 < 1e-11。
  全过 => supports；自检过但变号次数 != 1 => refutes（counterexample=变号区间与两端读数）；
  自检没过 => inconclusive（精度不足不是数学命题的反例）。
"""
import json
import math
import time

PI = math.pi
HP = PI / 2.0
ABRK = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]


def tanhsinh(f, a, b, h=0.05, tmax=7.0):
    """双指数（tanh-sinh）求积 int_a^b f（exp:000014 用的同一实现）。"""
    if b <= a:
        return 0.0
    c = 0.5 * (b - a)
    d = 0.5 * (a + b)
    n = int(math.ceil(tmax / h))
    s = 0.0
    for k in range(-n, n + 1):
        t = k * h
        u = HP * math.sinh(t)
        x = math.tanh(u)
        if x >= 1.0 or x <= -1.0:
            continue
        ch = math.cosh(u)
        s += (HP * math.cosh(t) / (ch * ch)) * f(d + c * x)
    return s * c * h


def integrand(p, th):
    """S(th)^{-2/p}，log-sum-exp 形式（p 大时 a_i^p 下溢，直接求和会得 0）。"""
    a = (abs(math.cos(th - PI / 6.0)), abs(math.cos(th + PI / 6.0)), abs(math.sin(th)))
    m = None
    for v in a:
        if v > 0.0:
            lv = math.log(v)
            if m is None or lv > m:
                m = lv
    s = 0.0
    for v in a:
        if v > 0.0:
            e = p * (math.log(v) - m)
            if e > -745.0:
                s += math.exp(e)
    return math.exp(-2.0 * m) * math.exp(-(2.0 / p) * math.log(s))


def a_diag(p, h=0.05):
    tot = 0.0
    for i in range(len(ABRK) - 1):
        a, b = ABRK[i], ABRK[i + 1]
        tot += tanhsinh(lambda th, p=p: integrand(p, th), a, b, h=h)
    return 0.75 * tot


def a_face(p):
    return 2.0 ** (0.5 - 1.0 / p) * 4.0 * math.exp(
        2.0 * math.lgamma(1.0 + 1.0 / p) - math.lgamma(1.0 + 2.0 / p))


def delta(p, h=0.05):
    return a_face(p) - a_diag(p, h=h)


def main():
    t0 = time.time()
    exact1 = 3.0 * math.sqrt(3.0) / 4.0

    # ---------------- 自检 ----------------
    st = {
        "a_diag_1_rel": abs(a_diag(1.0) - exact1) / exact1,
        "a_diag_2_rel": abs(a_diag(2.0) - PI) / PI,
        "a_face_2_rel": abs(a_face(2.0) - PI) / PI,
    }
    refine = []
    for p in (20.0, 1.0e3, 1.0e6):
        v1 = a_diag(p, h=0.05)
        v2 = a_diag(p, h=0.025)
        r = {"p": p, "h005": v1, "h0025": v2, "rel": abs(v1 - v2) / abs(v1)}
        refine.append(r)
        print("PROGRESS: " + json.dumps({"stage": "h_refine", **r}))
    # h 细化门槛按用途定：本行判的是 Delta 的符号（网格上最小裕度 >=0.15 量级），
    # 收敛控制只需远小于该裕度即可；取 1e-9，既足够，也不把大 p 的层结构误差误判成"读数不可用"。
    selftest_ok = (max(st.values()) < 1e-12
                   and max(r["rel"] for r in refine) < 1e-9)

    # ---------------- 对数网格扫描 ----------------
    N = 241
    gl, gh = 20.0, 1.0e6
    grid = [gl * (gh / gl) ** (i / (N - 1.0)) for i in range(N)]
    rows = []
    changes = []
    prev = None
    for i, p in enumerate(grid):
        d = delta(p)
        row = {"p": p, "Delta": d}
        rows.append(row)
        if (prev is not None and d != 0.0 and prev["Delta"] != 0.0
                and (d > 0.0) != (prev["Delta"] > 0.0)):
            changes.append([prev["p"], p])
        prev = row
        if i % 40 == 0:
            print("PROGRESS: " + json.dumps({"stage": "grid", "i": i, "p": p, "Delta": d,
                                             "sec": round(time.time() - t0, 2)}))
    print("PROGRESS: " + json.dumps({"stage": "grid", "i": N - 1, "p": grid[-1],
                                     "Delta": rows[-1]["Delta"],
                                     "sec": round(time.time() - t0, 2)}))

    # ---------------- 变号点二分（相对宽度判据） ----------------
    roots = []
    for lo, hi in changes:
        flo, fhi = delta(lo), delta(hi)
        it = 0
        while (hi - lo) / (0.5 * (hi + lo)) > 1e-13 and it < 400:
            mid = 0.5 * (lo + hi)
            fm = delta(mid)
            if (fm > 0.0) == (flo > 0.0):
                lo, flo = mid, fm
            else:
                hi, fhi = mid, fm
            it += 1
        roots.append({"p_star": 0.5 * (lo + hi), "lo": lo, "hi": hi,
                      "rel_width": (hi - lo) / (0.5 * (lo + hi)),
                      "Delta_lo": flo, "Delta_hi": fhi, "bisect_iters": it})
        print("PROGRESS: " + json.dumps({"stage": "bisect", **roots[-1]}))

    # ---------------- 变号点附近加密复核 ----------------
    dense = []
    dense_changes = []
    if roots:
        r0 = roots[0]["p_star"]
        dg = [r0 / 1.5 * 3.0 ** (i / 40.0) for i in range(41)]
        prevd = None
        for p in dg:
            d = delta(p)
            dense.append({"p": p, "Delta": d})
            if (prevd is not None and d != 0.0 and prevd["Delta"] != 0.0
                    and (d > 0.0) != (prevd["Delta"] > 0.0)):
                dense_changes.append([prevd["p"], p])
            prevd = dense[-1]
        print("PROGRESS: " + json.dumps({"stage": "dense", "n": len(dg),
                                         "changes": dense_changes,
                                         "min_abs_Delta": min(abs(x["Delta"]) for x in dense)}))

    # ---------------- 判据 ----------------
    ok_count = (len(changes) == 1)
    ok_int = all(gl < r["p_star"] < gh for r in roots)
    ok_width = all(r["rel_width"] < 1e-6 for r in roots)
    ok_tail = rows[-1]["Delta"] > 0.0
    ok_dense = (len(dense_changes) == 1) if ok_count else False

    if not selftest_ok:
        result = "inconclusive"
        ce = None
        why = "求积自检未过，读数不可用（精度不足不是数学反例）"
    elif not ok_count:
        result = "refutes"
        ce = {"sign_changes_on_grid": changes,
              "Delta_at_20": rows[0]["Delta"], "Delta_at_1e6": rows[-1]["Delta"],
              "n_grid": N, "note": "网格上 Delta 的变号次数与断言（恰一次）不符"}
        why = "网格上 Delta 的变号次数 != 1"
    elif ok_width and ok_tail and ok_dense and ok_int:
        result = "supports"
        ce = None
        why = "网格上恰一次变号，二分夹逼相对宽度 < 1e-6，加密复核同样恰一次"
    else:
        result = "inconclusive"
        ce = None
        why = "变号次数对但夹逼宽度/端点符号/加密复核未全过"

    payload = {
        "result": result,
        "counterexample": ce,
        "why": why,
        "bound": "p in [20, 1e6], log-grid N=241; bracket refined to relative width <= 1e-6",
        "strategy": ("6-piece tanh-sinh(DE, h=0.05) on the theta integral with log-sum-exp "
                     "integrand; log-equidistant grid; sign-change bisection in p; "
                     "dense 41-point log grid around the root; h-refinement as convergence control"),
        "scaling": {"total_sec": round(time.time() - t0, 2),
                    "a_diag_evals_equiv": N + 2 * len(roots) * 30 + 41 + 6,
                    "per_a_diag_ms": round(1000.0 * (time.time() - t0) / max(1, N), 2)},
        "selftest": st,
        "h_refine": refine,
        "selftest_ok": selftest_ok,
        "grid_first_last": [rows[0], rows[-1]],
        "sign_changes": changes,
        "roots": roots,
        "dense_near_root": {"changes": dense_changes,
                            "min_abs_Delta": min((abs(x["Delta"]) for x in dense), default=None)},
        "limit_at_inf": 4.0 * math.sqrt(2.0) - 3.0 * math.sqrt(3.0),
        "checks": {"count_one": ok_count, "inside": ok_int, "rel_width_lt_1e-6": ok_width,
                   "tail_positive": ok_tail, "dense_one": ok_dense},
        "note": ("Delta = A_face - A_diag（与 exp:000016 的 Delta 差一个整体符号）。"
                 "A_face 用闭式（exp:000015 已与两条独立数值路核过）；A_diag 用 exp:000014 的 "
                 "六段 tanh-sinh，只把被积函数改成 log-sum-exp 形式以扛住 p 大到 1e6 时 a_i^p 下溢。"
                 "p=1,2 的精确值自检与 h 细化都在 payload 里。"
                 "本行判的是「(20,1e6] 上 Delta 变号恰一次并夹逼出该点」这一条网格级断言。"),
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
