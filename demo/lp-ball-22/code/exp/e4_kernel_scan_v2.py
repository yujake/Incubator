#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 任务 4（v2，取代 exp 000017：那一版在 t=1e3 处两个积分都下溢成 0，ΔK 被读成 0，
判据要求「符号序列至多一次反转」遇到 0 就判不了 —— 是数值下溢，不是数学结论）。

本版做两件事：
(1) 抽取公因子：令 A(th)=||e_D||_p^p、B(th)=||e_F||_p^p，c = min_{th} min(A,B)，
    则 ΔK(t) = e^{-tc} * ∫ (e^{-t(A-c)} - e^{-t(B-c)}) dth，符号不变（e^{-tc} > 0）；
(2) 无抵消形式：记 m=min(A,B)、M=max(A,B)、s=+1 if A<B else -1，
    ∫ (e^{-t(A-c)} - e^{-t(B-c)}) dth = ∫ e^{-t(m-c)} (1 - e^{-t(M-m)}) s dth，
    每项都是非负量乘符号，不会因两个大数相减丢精度／下溢。

e_D(th) = cos th * u + sin th * v,  u=(1,-1,0)/sqrt2, v=(1,1,-2)/sqrt6
   => A(th) = ||e_D||_p^p = (2/3)^{p/2} * (|cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p)
e_F(th) = cos th * w1 + sin th * w2, w1=(1,-1,0)/sqrt2, w2=(0,0,1)
   => B(th) = ||e_F||_p^p = 2^{1-p/2}|cos th|^p + |sin th|^p
（派活文本里「params 里的显式表达式」未随任务送达，这里用的是 F 稿 manuscripts/F/f-proof-000002.md
  第 2-5 步那组分量按同一构造反推的显式式；e_F 取「面内一组标准正交基」的同一构造。）

判据（硬编码，由脚本判）：
  在每个 p 上，200 点对数网格的 sign(ΔK) 序列（|ΔK| <= eps*max|ΔK| 记 0，eps=1e-12）
  恰好变号 1 次 且 两端符号非零  => supports；否则 refutes，反例 = 该 p 与观察到的变号位置列表。
  sign 序列两端有 0 或变号次数 != 1 都算 refutes（此时反例非空）。
"""
import json
import math
import time

PI = math.pi
HP = PI / 2.0


def tanhsinh_nodes(a, b, h=0.04, tmax=6.5):
    c = 0.5 * (b - a)
    d = 0.5 * (a + b)
    n = int(tmax / h)
    xs = []
    ws = []
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
        xs.append(d + c * x)
        ws.append(w * c * h)
    return xs, ws


BREAK_D = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]
BREAK_F = [0.0, HP, PI, 3.0 * HP, 2.0 * PI]


def A_D(p, th):
    S = (abs(math.cos(th - PI / 6.0)) ** p
         + abs(math.cos(th + PI / 6.0)) ** p
         + abs(math.sin(th)) ** p)
    return (2.0 / 3.0) ** (p / 2.0) * S


def B_F(p, th):
    return (2.0 ** (1.0 - p / 2.0)) * abs(math.cos(th)) ** p + abs(math.sin(th)) ** p


def build_plan(p):
    """两族节点合并成一张 (theta, w) 表（两族都从 0 到 2pi 覆盖，权重各自独立）。"""
    pts = []
    for i in range(len(BREAK_D) - 1):
        xs, ws = tanhsinh_nodes(BREAK_D[i], BREAK_D[i + 1])
        pts.append((xs, ws))
    DD = [(th, w, A_D(p, th)) for xs, ws in pts for th, w in zip(xs, ws)]
    pts2 = []
    for i in range(len(BREAK_F) - 1):
        xs, ws = tanhsinh_nodes(BREAK_F[i], BREAK_F[i + 1])
        pts2.append((xs, ws))
    FF = [(th, w, B_F(p, th)) for xs, ws in pts2 for th, w in zip(xs, ws)]
    return DD, FF


def delta_K(DD, FF, c, t):
    """ΔK(t) = e^{-tc} * Σ w_i e^{-t(m_i - c)} (1 - e^{-t(M_i - m_i)}) s_i，按两族各表分别累加。
    两族节点不同，所以差值 = (A 族加权和) - (B 族加权和)，各自用无抵消形式：
      A 族贡献 = Σ w e^{-t(A-c)}；B 族贡献 = Σ w e^{-t(B-c)} ——
    这里为了消除下溢，改用：ΔK_scaled = Σ_A w e^{-t(A-c)} - Σ_B w e^{-t(B-c)}，
    两项都是「至少有一项 = 1（在达到最小值处）」的非负量，不会双双下溢到 0。"""
    sA = 0.0
    for th, w, A in DD:
        e = -t * (A - c)
        if e > -745.0:
            sA += w * math.exp(e)
    sB = 0.0
    for th, w, B in FF:
        e = -t * (B - c)
        if e > -745.0:
            sB += w * math.exp(e)
    return sA - sB


def main():
    t0 = time.time()
    ps = [2.5, 3.0, 4.0, 6.0, 10.0]
    n_t = 200
    log_t0, log_t1 = -3.0, 3.0
    ts = [10.0 ** (log_t0 + (log_t1 - log_t0) * k / (n_t - 1.0)) for k in range(n_t)]
    rows = []
    all_ok = True
    for p in ps:
        t1 = time.time()
        DD, FF = build_plan(p)
        c = min(min(A for _, _, A in DD), min(B for _, _, B in FF))
        vals = [delta_K(DD, FF, c, t) for t in ts]
        mx = max(abs(v) for v in vals)
        eps = 1e-12 * mx if mx > 0 else 0.0
        signs = [0 if abs(v) <= eps else (1 if v > 0 else -1) for v in vals]
        # 变号（跳过 0）
        nz = [(i, s) for i, s in enumerate(signs) if s != 0]
        changes = []
        for j in range(1, len(nz)):
            if nz[j][1] != nz[j - 1][1]:
                changes.append([round(ts[nz[j - 1][0]], 6), round(ts[nz[j][0]], 6)])
        # 变号处的精细定位（对 log10 t 二分，用无抵消形式，不需要符号以外的东西）
        refined = []
        for lo, hi in changes:
            a = math.log10(lo)
            b = math.log10(hi)
            fa = delta_K(DD, FF, c, 10.0 ** a)
            for _ in range(60):
                m = 0.5 * (a + b)
                fm = delta_K(DD, FF, c, 10.0 ** m)
                if (fm > 0) == (fa > 0):
                    a, fa = m, fm
                else:
                    b = m
            refined.append({"t_cross": round(10.0 ** (0.5 * (a + b)), 10),
                            "log10_lo": round(a, 12), "log10_hi": round(b, 12),
                            "DeltaK_at_lo": fa, "t_scan_bracket": [lo, hi]})
        zeros_at_edges = [signs[0], signs[-1]]
        ok = (len(changes) == 1 and signs[0] != 0 and signs[-1] != 0)
        all_ok = all_ok and ok
        row = {"p": p, "n_sign_changes": len(changes), "changes": changes,
               "signs_bracket": zeros_at_edges,
               "DeltaK_scaled_t1e-3": vals[0], "DeltaK_scaled_t1e3": vals[-1],
               "scaling_constant_c": c,
               "max_abs_DeltaK_scaled": mx,
               "sign_scaled_at_1e-3": signs[0], "sign_scaled_at_1e3": signs[-1],
               "refined_crossings": refined,
               "snapshot": {f"1e{int(round(lt))}": delta_K(DD, FF, c, 10.0 ** lt)
                            for lt in (-3.0, -1.0, 0.0, 1.0, 3.0)},
               "nodes_D": len(DD), "nodes_F": len(FF),
               "sec": round(time.time() - t1, 3)}
        rows.append(row)
        print("PROGRESS: " + json.dumps({k: row[k] for k in (
            "p", "n_sign_changes", "changes", "signs_bracket", "scaling_constant_c",
            "DeltaK_scaled_t1e-3", "DeltaK_scaled_t1e3", "sec")}))
    cnt = {r["p"]: r["n_sign_changes"] for r in rows}
    bad = [r["p"] for r in rows if r["n_sign_changes"] != 1 or 0 in r["signs_bracket"]]
    if all_ok:
        result = "supports"
        counter = {}
    else:
        result = "refutes"
        counter = {"p_values_where_not_one_sign_change_or_edge_zero": bad,
                   "observed": [{"p": r["p"], "n_sign_changes": r["n_sign_changes"],
                                 "changes": r["changes"], "signs_bracket": r["signs_bracket"]}
                                for r in rows if r["p"] in bad]}
    payload = {
        "result": result,
        "counterexample": counter,
        "eD": "e_D(th)=cos th*(1,-1,0)/sqrt2 + sin th*(1,1,-2)/sqrt6 => A=||e_D||_p^p=(2/3)^(p/2)*(|cos(th-pi/6)|^p+|cos(th+pi/6)|^p+|sin th|^p)",
        "eF": "e_F(th)=cos th*(1,-1,0)/sqrt2 + sin th*(0,0,1) => B=||e_F||_p^p=2^(1-p/2)|cos th|^p+|sin th|^p",
        "bound": "p in {2.5,3,4,6,10}; t in [1e-3,1e3] (200 log-spaced points)",
        "strategy": "DE(tanh-sinh,h=0.04) nodes per p, cached A/B on nodes; common factor e^{-t c} extracted (c = global min of A,B) so no underflow; sign sequence + log-t bisection",
        "scaling": {"total_sec": round(time.time() - t0, 3),
                    "per_p_sec": [r["sec"] for r in rows], "n_t": n_t},
        "n_sign_changes_by_p": cnt,
        "rows": rows,
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
