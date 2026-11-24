#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 任务 3b（订正 exp:000016 里被漏判的那一句）：
命题「rho(p) = A_diag(p)/A_face(p) 在 p ∈ (2,20] 的步长 0.01 网格上严格单调下降」的真假。

背景：exp:000016 的 claim 里同时写了「Δ 恰变号一次」与「ρ 严格单调下降」；
它的读数里 Δ 那一半成立（p* = 4.998215596862，区间宽 7.45e-11），
但 ρ 那一半被它自己的读数**否掉**（101 处局部上升，ρ 从 1 升到 ~1.01157），
而那一行的判据没有把单调性纳入 checks，于是打了 supports —— 这是判据缺项，不是数学结论。
本脚本把单调那一条单独当命题来判：出现上升 ⇒ result=refutes 并给出可复核的那一步。

A_diag(p) = (3/4) int_0^{2pi} S(th)^{-2/p} dth,
            S = |cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p,
            断点 = 三个 |.| 的零点 {0,pi/3,2pi/3,pi,4pi/3,5pi/3,2pi}，逐段 tanh-sinh(DE, h=0.05)。
            （exp:000014 已用完全独立的二维路核过 11 个 p：相对差 <= 1.4e-15）
A_face(p) = 2^{1/2-1/p} * 4 Gamma(1+1/p)^2 / Gamma(1+2/p)（lgamma 现算）
            （exp:000015 已用两条独立数值路核过：相对差 <= 1e-12）

自检（脚本内）：A_diag(1)=3sqrt3/4、A_diag(2)=pi、A_face(2)=pi，相对差须 < 1e-12，否则 inconclusive。
判词：出现至少一处 rho(p_{k+1}) > rho(p_k) ⇒ refutes（counterexample = 第一处，含两侧数值）；
      全网格严格下降 ⇒ supports。
"""
import json
import math
import time

PI = math.pi
HP = PI / 2.0


def tanhsinh(f, a, b, h=0.05, tmax=7.0):
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


ABRK = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]


def S_val(p, th):
    return (abs(math.cos(th - PI / 6.0)) ** p
            + abs(math.cos(th + PI / 6.0)) ** p
            + abs(math.sin(th)) ** p)


def A_diag(p):
    tot = 0.0
    for i in range(len(ABRK) - 1):
        tot += tanhsinh(lambda th, p=p: S_val(p, th) ** (-2.0 / p), ABRK[i], ABRK[i + 1])
    return 0.75 * tot


def A_face(p):
    return 2.0 ** (0.5 - 1.0 / p) * 4.0 * math.exp(
        2.0 * math.lgamma(1.0 + 1.0 / p) - math.lgamma(1.0 + 2.0 / p))


def main():
    t0 = time.time()
    e1 = 3.0 * math.sqrt(3.0) / 4.0
    st = {"A_diag_1_rel": abs(A_diag(1.0) - e1) / e1,
          "A_diag_2_rel": abs(A_diag(2.0) - PI) / PI,
          "A_face_2_rel": abs(A_face(2.0) - PI) / PI}
    st["ok"] = all(v < 1e-12 for v in st.values() if isinstance(v, float))

    ps = [2.0 + 0.01 * k for k in range(1, 1801)]   # 2.01 .. 20.00
    rows = []
    for i, p in enumerate(ps):
        ad = A_diag(p)
        af = A_face(p)
        rows.append({"p": p, "A_diag": ad, "A_face": af, "rho": ad / af, "Delta": ad - af})
        if i % 300 == 0:
            print("PROGRESS: " + json.dumps({"stage": "grid", "i": i, "p": p,
                                             "rho": ad / af, "Delta": ad - af,
                                             "sec": round(time.time() - t0, 3)}))

    rises = []
    for i in range(len(rows) - 1):
        d = rows[i + 1]["rho"] - rows[i]["rho"]
        if d > 0.0:
            rises.append({"p_left": rows[i]["p"], "p_right": rows[i + 1]["p"],
                          "rho_left": rows[i]["rho"], "rho_right": rows[i + 1]["rho"],
                          "d_rho": d})
    imax = max(range(len(rows)), key=lambda i: rows[i]["rho"])
    peak = rows[imax]
    # 峰值之后的下降段是否严格（不严格就点名）
    tail_viol = [{"p_left": rows[i]["p"], "p_right": rows[i + 1]["p"],
                  "d_rho": rows[i + 1]["rho"] - rows[i]["rho"]}
                 for i in range(imax, len(rows) - 1)
                 if rows[i + 1]["rho"] - rows[i]["rho"] >= 0.0]

    named = {}
    for p in (2.0 + 1e-6, 3.0, 4.0, 10.0, 50.0):
        ad = A_diag(p)
        af = A_face(p)
        named["p=%r" % p] = {"p": p, "A_diag": ad, "A_face": af,
                             "rho": ad / af, "Delta": ad - af,
                             "sign_Delta": (1 if ad > af else (-1 if ad < af else 0))}

    if not st["ok"]:
        result = "inconclusive"
        counter = None
        reason = "求积/闭式自检没过（读数见 selftest），不当判定用"
    elif rises:
        result = "refutes"
        first = rises[0]
        counter = {"p_left": first["p_left"], "p_right": first["p_right"],
                   "rho_left": first["rho_left"], "rho_right": first["rho_right"],
                   "d_rho": first["d_rho"],
                   "note": ("rho 在相邻网格点上升：p=%.2f 处 rho=%.17g，p=%.2f 处 rho=%.17g，"
                            "d_rho=%.3e > 0 ⇒ 不是严格单调下降"
                            % (first["p_left"], first["rho_left"], first["p_right"],
                               first["rho_right"], first["d_rho"]))}
        reason = "在 (2,20] 网格上找到 %d 处上升，第一处在 p=%.2f→%.2f" % (
            len(rises), first["p_left"], first["p_right"])
    else:
        result = "supports"
        counter = None
        reason = "全网格 1799 个相邻差都 < 0"

    payload = {
        "result": result,
        "counterexample": counter,
        "reason": reason,
        "claim_tested": "rho(p)=A_diag(p)/A_face(p) 在 p in (2,20] 步长 0.01 的网格上严格单调下降",
        "bound": "p in (2,20] 步长 0.01（1800 点）",
        "strategy": ("A_diag: 6-piece tanh-sinh(DE,h=0.05); A_face: lgamma closed form; "
                     "adjacent-difference scan on the 0.01 grid"),
        "selftest": st,
        "n_upward_steps": len(rises),
        "first_5_upward_steps": rises[:5],
        "last_2_upward_steps": rises[-2:],
        "rho_peak": {"p": peak["p"], "rho": peak["rho"], "A_diag": peak["A_diag"],
                     "A_face": peak["A_face"], "Delta": peak["Delta"]},
        "rho_strictly_decreasing_after_peak": (len(tail_viol) == 0),
        "tail_violations": tail_viol[:5],
        "named_points": named,
        "scaling": {"total_sec": round(time.time() - t0, 3), "grid_points": len(rows)},
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
