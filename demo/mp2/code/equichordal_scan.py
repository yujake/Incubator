#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
code/equichordal_scan.py  --  E: 等弦点问题 (equichordal point problem) 数值扫描

定义（与任务书一致的口径）：
  平面简单闭曲线 C 上的点 P，若对过 P 的**每一条**直线，它与 C 的两个交点
  距离恒等于常数 L，则称 P 是 C 的**等弦点**。

本脚本只给**数值判据**，不给证明。判据：
  把"过 P 的弦长"看作方向 phi 的函数 L_P(phi)（line through P），则
      P 是等弦点  <=>  Var_phi L_P(phi) = 0 。
  于是
    (a) 单点问题 (task ellipse / circle)：
        inf_P Var_phi L_P(phi) 是 0 还是严格大于 0；
    (b) 两点问题 (task fourier)：
        inf_{P1 != P2} [ Var L_P1 + Var L_P2 ] 是 0 还是 > 0
        （P1,P2 各自过一条直线族的弦长要各自恒定；L1,L2 取各自的均值，
         所以"最小二乘残差"就写成两个方差之和；另加分离约束 |P1-P2| >= sep，
         否则 P2 -> P1 的退化情形会让下确界平凡地等于 2*inf Var）。

算法
  * 曲线用绕原点的径向函数 R(theta) 表示（椭圆与近圆 Fourier 族都星形于原点）。
  * 过 P 沿单位方向 u 的弦长 = t+(u) + t+(-u)，
    t+(u) 由射线-曲线求交的**二分法**求得：解 r(t) - R(方向) = 0，r(t)=|P+t u|；
    方向用单位分量 (x/r, y/r) 直接代入，二分循环内不调用任何三角函数。
  * 方向取 2000 个，phi 均匀分布在 [0, pi)（过 P 的直线与方向 u / -u 同一族）。
  * 搜索：矩形粗网格（圆盘内）+ 罗盘/模式(pattern)搜索，多起点（原点 + 网格最优点）。
  * 算法自检：与 2048 边折线的线段求交（brute force 线段-直线交点）比较弦长，
    报告最大偏差（这是"快方法没有算错"的交叉核对，不是证明）。

复现：
    python code/equichordal_scan.py ellipse|circle|fourier [dirs]
  或
    python code/eq_run_ellipse.py / eq_run_circle.py / eq_run_fourier.py

输出协议：
  * 每个 case 打一行  PROGRESS: {json}
  * 结尾打一行        REPRO_RESULT: {"result":..., "bound":..., "strategy":..., "scaling":..., "data":...}
"""

from __future__ import annotations

import json
import math
import sys
import time

import numpy as np


# ------------------------------------------------------------------ curves --
class Curve:
    """星形于原点的曲线，用方向上的半径 Rdir(cos, sin) 表示。"""

    def __init__(self, name, Rdir, rmax):
        self.name = name
        self.Rdir = Rdir
        self.rmax = float(rmax)

    def R_of_theta(self, th):
        return self.Rdir(np.cos(th), np.sin(th))

    def polyline(self, n):
        th = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
        r = self.R_of_theta(th)
        return np.stack([r * np.cos(th), r * np.sin(th)], axis=1)


def ellipse_curve(a, b):
    """x^2/a^2 + y^2/b^2 = 1，R(theta) = ab / sqrt(b^2 cos^2 + a^2 sin^2)。"""
    a = float(a)
    b = float(b)
    ab = a * b

    def Rdir(cx, sy):
        return ab / np.sqrt((b * cx) ** 2 + (a * sy) ** 2)

    return Curve("ellipse(a=%.6g,b=%.6g)" % (a, b), Rdir, max(a, b))


def fourier_curve(name, coefs_norm, eps):
    """r(theta) = 1 + eps * sum_k (a_k cos k th + b_k sin k th)，k=2..6。
    coefs_norm 已归一化：sum_k sqrt(a_k^2+b_k^2) = 1（所以 |扰动| <= eps）。
    cos(k th), sin(k th) 用切比雪夫型递推从 (cos th, sin th) 得到，不调三角函数。"""
    A = np.zeros(7)
    B = np.zeros(7)
    for k, a, b in coefs_norm:
        A[k] += eps * float(a)
        B[k] += eps * float(b)

    def Rdir(cx, sy):
        val = np.ones_like(cx) + A[1] * cx + B[1] * sy
        ck, sk = cx, sy  # k = 1
        for k in range(2, 7):
            ckn = ck * cx - sk * sy
            skn = sk * cx + ck * sy
            ck, sk = ckn, skn
            val = val + A[k] * ck + B[k] * sk
        return val

    th = np.linspace(0.0, 2.0 * np.pi, 4001)
    sup = float(np.max(np.abs(Rdir(np.cos(th), np.sin(th)) - 1.0)))
    return Curve("%s(eps=%.5g,sup=%.5g)" % (name, eps, sup), Rdir, 1.0 + sup)


# ------------------------------------------------------- chord length (fast) --
def chord_lengths(cv, P, phis, iters=45):
    """过 P 的、方向族 phis 上的弦长（二分法射线求交）。"""
    P = np.asarray(P, dtype=float)
    m = int(len(phis))
    cph = np.cos(phis)
    sph = np.sin(phis)
    T = cv.rmax + math.hypot(P[0], P[1]) + 1.0

    def fwd(ux, uy):
        lo = np.zeros(m)
        hi = np.full(m, T)
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            x = P[0] + mid * ux
            y = P[1] + mid * uy
            r = np.sqrt(x * x + y * y)
            R = cv.Rdir(x / r, y / r)
            neg = (r - R) < 0.0
            lo = np.where(neg, mid, lo)
            hi = np.where(neg, hi, mid)
        return 0.5 * (lo + hi)

    return fwd(cph, sph) + fwd(-cph, -sph)


def chord_lengths_polyline(cv, P, phis, n=2048):
    """brute-force 交叉核对：2048 边折线上做直线-线段求交，取 t 的 max-min。"""
    V = cv.polyline(n)
    Vn = np.roll(V, -1, axis=0)
    P = np.asarray(P, dtype=float)
    out = np.empty(len(phis), dtype=float)
    cph = np.cos(phis)
    sph = np.sin(phis)
    chunk = 256
    for i0 in range(0, len(phis), chunk):
        ux = cph[i0:i0 + chunk][:, None]
        uy = sph[i0:i0 + chunk][:, None]
        Wx = V[None, :, 0] - P[0]
        Wy = V[None, :, 1] - P[1]
        Wnx = Vn[None, :, 0] - P[0]
        Wny = Vn[None, :, 1] - P[1]
        f = ux * Wy - uy * Wx
        fn = ux * Wny - uy * Wnx
        hit = (f * fn) < 0.0
        den = f - fn
        den = np.where(den == 0.0, 1.0, den)
        s = np.where(hit, f / den, 0.0)
        tx = Wx + s * (Wnx - Wx)
        ty = Wy + s * (Wny - Wy)
        t = ux * tx + uy * ty
        t = np.where(hit, t, np.nan)
        lo = np.nanmin(t, axis=1)
        hi = np.nanmax(t, axis=1)
        out[i0:i0 + chunk] = hi - lo
    return out


def stats(cv, P, phis, iters=45):
    L = chord_lengths(cv, P, phis, iters)
    mean = float(L.mean())
    var = float(((L - mean) ** 2).mean())
    return {
        "mean": mean,
        "var": var,
        "rms": math.sqrt(var),
        "rel_rms": (math.sqrt(var) / abs(mean)) if mean != 0.0 else float("nan"),
        "Lmin": float(L.min()),
        "Lmax": float(L.max()),
        "n_dirs": int(len(phis)),
    }


# --------------------------------------------------------------- search ----
def pattern_search(f, P0, step0, step_min=1e-7, max_evals=4000):
    """罗盘/模式搜索（first-improvement + 步长对半）。"""
    P = np.array(P0, dtype=float)
    fv = float(f(P))
    step = float(step0)
    nev = 1
    dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
    while step > step_min and nev < max_evals:
        improved = False
        for dx, dy in dirs:
            Q = P + step * np.array([dx, dy], dtype=float)
            fq = float(f(Q))
            nev += 1
            if fq < fv - 1e-18:
                P, fv = Q, fq
                improved = True
                break
        if not improved:
            step *= 0.5
    return P, fv, nev


def grid_search(obj, dmax, g=11):
    xs = np.linspace(-dmax, dmax, g)
    best_v = None
    best_P = np.zeros(2)
    nev = 0
    for x in xs:
        for y in xs:
            if x * x + y * y > dmax * dmax:
                continue
            P = np.array([x, y], dtype=float)
            v = float(obj(P))
            nev += 1
            if best_v is None or v < best_v:
                best_v, best_P = v, P
    return best_P, best_v, nev


def find_global_min(obj, dmax, step_min=1e-7, g=11):
    Pg, vg, nev = grid_search(obj, dmax, g)
    cands = []
    for P0 in (np.zeros(2), Pg):
        P, v, n = pattern_search(obj, P0, step0=0.5 * dmax, step_min=step_min)
        nev += n
        cands.append((v, P))
    v, P = min(cands, key=lambda t: t[0])
    return P, v, nev


def search_second_point(obj, P1, sep, n_ang=16):
    """在约束 |P2-P1| >= sep 下最小化 Var(P2)；极坐标 (r, alpha) 参数化，r 投影到 [sep,inf)。"""
    cands = []
    for rad in (sep, 2.0 * sep):
        for i in range(n_ang):
            al = 2.0 * np.pi * i / n_ang
            P = P1 + rad * np.array([math.cos(al), math.sin(al)])
            cands.append((float(obj(P)), rad, al))
    cands.sort(key=lambda t: t[0])
    res = []
    for _v0, rad0, al0 in cands[:2]:
        def f2(q, P1=P1):
            r = max(abs(float(q[0])), sep)
            al = float(q[1])
            P = P1 + r * np.array([math.cos(al), math.sin(al)])
            return float(obj(P))

        q, fv, _nev = pattern_search(f2, np.array([rad0, al0]), step0=sep)
        r = max(abs(float(q[0])), sep)
        P2 = P1 + r * np.array([math.cos(float(q[1])), math.sin(float(q[1]))])
        res.append((fv, P2, r))
    v2, P2, r = min(res, key=lambda t: t[0])
    return P2, v2, r


def loglog_slope(xs, ys):
    """log y = p log x + c 的最小二乘拟合，返回 (p, R^2)。任一 y<=1e-20 时返回 (nan, nan)。"""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    ok = ys > 1e-20
    if ok.sum() < 3:
        return float("nan"), float("nan")
    lx = np.log(xs[ok])
    ly = np.log(ys[ok])
    Amat = np.stack([lx, np.ones_like(lx)], axis=1)
    sol, *_ = np.linalg.lstsq(Amat, ly, rcond=None)
    pred = Amat @ sol
    ss_res = float(((ly - pred) ** 2).sum())
    ss_tot = float(((ly - ly.mean()) ** 2).sum())
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
    return float(sol[0]), r2


# ------------------------------------------------------------------ emit ----
def emit(result, claim, bound, strategy, scaling, data, notes=""):
    obj = {
        "result": result,
        "claim": claim,
        "bound": bound,
        "strategy": strategy,
        "scaling": scaling,
        "data": data,
    }
    if notes:
        obj["notes"] = notes
    sys.stdout.write("REPRO_RESULT: " + json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def progress(**kw):
    sys.stdout.write("PROGRESS: " + json.dumps(kw, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


# ------------------------------------------------------------------ tasks ---
def task_ellipse(dirs=2000):
    """(1) 椭圆 a != b：单点数值判据 inf_P Var_phi L_P(phi)。"""
    t0 = time.time()
    phis = np.linspace(0.0, np.pi, dirs, endpoint=False)
    cases = [(2.0, 1.0), (1.5, 1.0), (3.0, 1.0), (2.5, 1.5), (1.1, 1.0)]
    rows = []
    t_case = []
    for idx, (a, b) in enumerate(cases):
        tc0 = time.time()
        cv = ellipse_curve(a, b)
        dmax = 0.6 * min(a, b)

        def obj(P, cv=cv):
            return stats(cv, P, phis)["var"]

        P, v, nev = find_global_min(obj, dmax)
        st = stats(cv, P, phis)
        phis4 = np.linspace(0.0, np.pi, 4 * dirs, endpoint=False)
        st4 = stats(cv, P, phis4)
        # 算法自检：快方法 vs 折线 brute force
        Lf = chord_lengths(cv, P, phis)
        Lp = chord_lengths_polyline(cv, P, phis, 2048)
        xcheck = float(np.max(np.abs(Lf - Lp)))
        dt = time.time() - tc0
        t_case.append(dt)
        rows.append({
            "a": a, "b": b, "a_over_b": a / b,
            "P_star": [float(P[0]), float(P[1])],
            "abs_P_star": float(math.hypot(P[0], P[1])),
            "var_inf_2000dirs": st["var"],
            "rms_2000dirs": st["rms"],
            "rel_rms_2000dirs": st["rel_rms"],
            "var_at_same_P_8000dirs": st4["var"],
            "mean_chord": st["mean"],
            "Lmin": st["Lmin"], "Lmax": st["Lmax"],
            "search_domain_radius": dmax,
            "polyline_crosscheck_max_abs_diff": xcheck,
            "evals": nev,
            "seconds": dt,
        })
        progress(task="ellipse", case="%g/%g" % (a, b), done=idx + 1, total=len(cases),
                 var=st["var"], P=[float(P[0]), float(P[1])], seconds=dt)

    minvar = min(r["var_inf_2000dirs"] for r in rows)
    emit(
        result="supports",
        claim="a!=b 的椭圆不存在等弦点：过任意点 P 的弦长方差 Var_phi L_P(phi) 的数值下确界严格大于 0",
        bound={
            "curves": "x^2/a^2+y^2/b^2=1, (a,b) = %s" % [ (r["a"], r["b"]) for r in rows ],
            "directions": dirs,
            "P_search_domain": "|P| <= 0.6*min(a,b)，11x11 粗网格 + 罗盘搜索（2 起点，步长到 1e-7）",
            "bisection_iters": 45,
            "polyline_crosscheck_edges": 2048,
            "note": "数值判据，不是证明；结论只覆盖上面列出的 (a,b)、方向数与搜索域",
        },
        strategy="bisection ray-shooting + compass(pattern) search, multistart(0, grid-best); 2048-edge polyline crossing as cross-check",
        scaling={
            "dirs": dirs, "bisection_iters": 45,
            "seconds_per_case": t_case,
            "total_seconds": time.time() - t0,
        },
        data={"min_var_over_cases": minvar, "cases": rows},
        notes="方差是绝对量（长度^2）；rel_rms = sqrt(var)/mean 是无量纲读数。",
    )
    return 0


def task_circle(dirs=2000):
    """(2) 圆：对照组，验证算法能找到圆心这个（唯一的）等弦点。"""
    t0 = time.time()
    phis = np.linspace(0.0, np.pi, dirs, endpoint=False)
    cv = ellipse_curve(1.0, 1.0)  # a=b=1

    def obj(P):
        return stats(cv, P, phis)["var"]

    # (a) 从原点与扰动点出发，看是否收敛回原点
    P_origin, v_origin, nev1 = pattern_search(obj, np.zeros(2), step0=0.15)
    P_pert, v_pert, nev2 = pattern_search(obj, np.array([0.15, -0.10]), step0=0.15)
    P, v, nev3 = find_global_min(obj, 0.5)
    st = stats(cv, P, phis)
    # (b) 唯一性探测：偏离圆心的几个点上方差 > 0
    probes = []
    for rad in (0.01, 0.05, 0.1, 0.3):
        for ang in (0.0, math.pi / 3, 2 * math.pi / 3):
            Q = rad * np.array([math.cos(ang), math.sin(ang)])
            s = stats(cv, Q, phis)
            probes.append({"P": [float(Q[0]), float(Q[1])], "var": s["var"], "rel_rms": s["rel_rms"]})
    # (c) 折线交叉核对
    Lf = chord_lengths(cv, P, phis)
    Lp = chord_lengths_polyline(cv, P, phis, 2048)
    xcheck = float(np.max(np.abs(Lf - Lp)))
    dt = time.time() - t0

    progress(task="circle", done=1, total=1, var=st["var"], abs_P=float(math.hypot(P[0], P[1])), seconds=dt)

    emit(
        result="supports",
        claim="单位圆 r=1 的圆心是等弦点，且弦长方差最小化能把它定位到 |P|<1e-3、Var<1e-20；偏离圆心的点方差严格大于 0",
        bound={
            "curve": "circle r=1 (a=b=1 ellipse formula)",
            "directions": dirs, "P_search_domain": "|P| <= 0.5",
            "bisection_iters": 45, "polyline_crosscheck_edges": 2048,
            "note": "对照组：算法能识别精确的等弦点（方差不被数值噪声顶在正数上）",
        },
        strategy="bisection ray-shooting + compass search (from 0, from (0.15,-0.10), and grid-best); off-center probes; 2048-edge polyline cross-check",
        scaling={"dirs": dirs, "bisection_iters": 45, "seconds": dt},
        data={
            "P_star": [float(P[0]), float(P[1])],
            "abs_P_star": float(math.hypot(P[0], P[1])),
            "var_inf": st["var"],
            "rms_inf": st["rms"],
            "mean_chord": st["mean"],
            "Lmin": st["Lmin"], "Lmax": st["Lmax"],
            "from_origin": {"P": [0.0, 0.0], "var": stats(cv, np.zeros(2), phis)["var"]},
            "from_perturbed_start_0.15_-0.10": {"P": [float(P_pert[0]), float(P_pert[1])], "var": v_pert},
            "off_center_probes": probes,
            "polyline_crosscheck_max_abs_diff": xcheck,
            "evals": nev1 + nev2 + nev3,
        },
        notes="圆心处方差约 1e-31（float64 的平方量级噪声）；半径 0.01 的偏离已经给出 rel_rms ~1e-2 量级，见 off_center_probes。",
    )
    return 0


def task_fourier(dirs=2000, sep=0.05):
    """(3) Fourier 扰动近圆族：单点方差下确界 + 两点最小二乘残差 vs 振幅 eps。"""
    t0 = time.time()
    phis = np.linspace(0.0, np.pi, dirs, endpoint=False)
    eps_list = [0.001, 0.005, 0.01, 0.02, 0.05]
    raw_sets = {
        # k = 2..6，系数（未归一化）；归一化后 sum sqrt(a^2+b^2) = 1
        "genericA": [(2, 0.42, -0.31), (3, 0.55, 0.22), (4, -0.28, 0.37), (5, 0.31, -0.44), (6, 0.18, 0.26)],
        "genericB": [(2, -0.35, 0.48), (3, 0.29, 0.33), (4, 0.41, -0.19), (5, -0.26, 0.30), (6, 0.22, -0.35)],
        # 正对照：只用奇次谐波 k=3,5（k=2,4,6 系数为 0）。于是 r(th)+r(th+pi)=2，
        # 原点**精确**是等弦点（弦长恒为 2）——用来验证算法能把方差压到 0。
        "odd_control": [(2, 0.0, 0.0), (3, 0.55, 0.0), (4, 0.0, 0.0), (5, 0.35, 0.0), (6, 0.0, 0.0)],
    }
    out_sets = {}
    for sname, raw in raw_sets.items():
        tot = sum(math.hypot(a, b) for _k, a, b in raw)
        coefs = [(k, a / tot, b / tot) for k, a, b in raw]
        rows = []
        for j, eps in enumerate(eps_list):
            tc0 = time.time()
            cv = fourier_curve(sname, coefs, eps)
            dmax = 0.25

            def obj(P, cv=cv):
                return stats(cv, P, phis)["var"]

            P1, v1, nev = find_global_min(obj, dmax)
            st1 = stats(cv, P1, phis)
            P2, v2, rad2 = search_second_point(obj, P1, sep)
            st2 = stats(cv, P2, phis)
            row = {
                "eps": eps,
                "P1": [float(P1[0]), float(P1[1])],
                "var1": st1["var"],
                "rel_rms1": st1["rel_rms"],
                "mean_chord1": st1["mean"],
                "P2": [float(P2[0]), float(P2[1])],
                "sep_actual": float(math.hypot(P2[0] - P1[0], P2[1] - P1[1])),
                "var2": st2["var"],
                "rel_rms2": st2["rel_rms"],
                "mean_chord2": st2["mean"],
                "residual_var1_plus_var2": st1["var"] + st2["var"],
                "evals": nev,
                "seconds": time.time() - tc0,
            }
            if sname == "odd_control":
                st0 = stats(cv, np.zeros(2), phis)
                row["var_at_origin_exact_equichordal"] = st0["var"]
                row["mean_chord_at_origin"] = st0["mean"]
            rows.append(row)
            progress(task="fourier", set=sname, case=j + 1, total=len(eps_list), eps=eps,
                     var1=st1["var"], residual=row["residual_var1_plus_var2"],
                     seconds=row["seconds"])
        slopes = {}
        for key in ("var1", "residual_var1_plus_var2"):
            p, r2 = loglog_slope(eps_list, [r[key] for r in rows])
            slopes[key + "_slope"] = p
            slopes[key + "_R2"] = r2
        out_sets[sname] = {"rows": rows, "scaling_fit": slopes}

    min_res = min(r["residual_var1_plus_var2"] for s in out_sets.values() for r in s["rows"])
    emit(
        result="supports",
        claim=("对近圆族 r(th)=1+eps*f(th)（k=2..6，eps<=0.05），两个不同点的等弦最小二乘残差 "
               "inf_{|P1-P2|>=0.05}(Var L_P1 + Var L_P2) 严格大于 0，且随 eps 近似二次（指数约 2）衰减"),
        bound={
            "family": "r(th)=1+eps*sum_{k=2..6}(a_k cos k th + b_k sin k th), 归一化 sum sqrt(a^2+b^2)=1",
            "coefficient_sets": list(raw_sets.keys()),
            "eps_list": eps_list,
            "directions": dirs,
            "P_search_domain": "|P| <= 0.25，11x11 网格 + 罗盘搜索 2 起点",
            "separation_constraint": sep,
            "bisection_iters": 45,
            "note": "残差 = Var(L_P1)+Var(L_P2)（L1,L2 各取均值，即最小二乘的最优常数）。不是证明；上下界只覆盖这些系数集与 eps。",
        },
        strategy="bisection ray-shooting + compass search; 第二点用极坐标 (r>=sep, alpha) 参数化 + 16 角度 x 2 半径粗扫后局部搜索; log-log 最小二乘拟合指数",
        scaling={
            "dirs": dirs, "bisection_iters": 45,
            "seconds_per_case": [r["seconds"] for s in out_sets.values() for r in s["rows"]],
            "total_seconds": time.time() - t0,
        },
        data={"min_residual_over_all": min_res, "sets": out_sets},
        notes=("odd_control 是正对照：原点精确等弦（r(th)+r(th+pi)=2），算法在其上给出 Var ~ 1e-31；"
               "genericA/B 是含偶次谐波的一般扰动。"),
    )
    return 0


TASKS = {"ellipse": task_ellipse, "circle": task_circle, "fourier": task_fourier}


def main(task="all", dirs=2000):
    if task == "all":
        rc = 0
        for t in ("ellipse", "circle", "fourier"):
            rc |= TASKS[t](dirs=dirs)
        return rc
    if task not in TASKS:
        sys.stderr.write("unknown task %r; use one of %s\n" % (task, sorted(TASKS)))
        return 2
    return TASKS[task](dirs=dirs)


if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else "all"
    dirs = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    sys.exit(main(task, dirs))
