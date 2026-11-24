#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 本趟任务 (3)：大 p 上 A_diag 与 A_face 贴近极限的方向与量级（抗尖峰求积）。

口径 = exp:000014 / 000016 / 000020 / 000022 的同一套 A_diag 与 A_face。
要回答：p > p*(=4.9982) 之后 rho = A_face/A_diag 是升向 4sqrt2/(3sqrt3)=1.088662 还是回落
（任务原文断言 Delta 在 (20,inf) 上还有第二次零点；exp:000020 已给出 [20,1e6] 上无变号，
 本行把它钉到 1e8，并给出 A_diag-3sqrt3 与 A_face-4sqrt2 的符号与量级）。

关键写法（不是装饰，是去掉相消）：
  A_diag(p) - 3sqrt3 = (3/4) int_0^{2pi} [S^{-2/p} - M^{-2}] dth,
  S^{-2/p} = e^{-2m} exp(-(2/p) ls),  M^{-2} = e^{-2m},  m = ln max_i a_i,
  ls = log1p( sum_{i != argmax} e^{p(ln a_i - m)} ) >= 0
  => 被积函数 = e^{-2m} * expm1(-(2/p) ls)  <= 0,  逐点无相消（p=1e8 时差值 1e-15 量级，
     直接写 S^{-2/p} - M^{-2} 会被 1e-16 的舍入吃掉；写成 expm1 之后没有相消）。
  主项是闭式：(3/4) int M^{-2} dth = 3 sqrt3（脚本里另算一次 int M^{-2} 与 4 sqrt3 对拍）。

抗尖峰：p 大时 S^{-2/p} 的「非平凡部分」集中在两个最大者打平的四个点
  th0 in {0, pi/3, pi, 5pi/3}（那里 M = sqrt3/2、第三个值为 0），层宽 ~ sigma/p，sigma = 2M0 = sqrt3。
  每个 th0 的两侧各换元 u = p|th-th0|/sigma（dth = (sigma/p) du），在 u in [0,U] 上求积
  （被积函数在 u 里光滑：e^{p(ln a_i - m)} 变成 e^{-kappa u}）；
  层外残段（|th-th0| > delta = sigma U / p）照常六段 tanh-sinh 补齐（大 p 时那里逐点为 0）。

  A_face(p) - 4sqrt2 = 4sqrt2 * expm1(L),   L = -(ln2)/p + 2 lnG(1+1/p) - lnG(1+2/p)
  L 用两条路算：lgamma 与 x=1/p 的幂级数 L = -x ln2 - sum_{k>=2} (-1)^k zeta(k)(2^k-2) x^k / k，
  互为对照（大 p 时级数那条更准：L ~ -6.9e-9，lgamma 的两项相消到 1e-16）。

判据（硬编码、由脚本判，不过模型）：
  (A) 四点 p in {1e2,1e4,1e6,1e8}: A_diag-3sqrt3 < 0 且 A_face-4sqrt2 < 0（都从下方逼近）
  (B) Delta = A_face - A_diag 四点全 > 0 且严格递增；0 < (4sqrt2-3sqrt3)-Delta 严格递减；
      rho 四点严格递增且 < 4sqrt2/(3sqrt3)
  (C) 收敛控制：int M^{-2} 与 4sqrt3 相对差 < 1e-12；J*p^2 在步长 h 与 h/2 下相对变化 < 1e-6；
      p=20 与 p=100 上「3sqrt3+J」与直接六段 tanh-sinh 的 A_diag 相对差 < 1e-10；
      p=1,2 的精确值自检 < 1e-12
  (A)(B) 全过且 (C) 过 => supports；(A) 或 (B) 有反例 => refutes（counterexample 点名读数）；
  (C) 不过 => inconclusive（精度不足不是数学反例）。
"""
import json
import math
import time

PI = math.pi
HP = PI / 2.0
ABRK = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]
TIES = [0.0, PI / 3.0, PI, 5.0 * PI / 3.0]        # 两个最大者打平的点
CUT = TIES + [2.0 * PI]                           # 层邻域的裁剪点（2pi 与 0 是同一点）
M0 = math.sqrt(3.0) / 2.0
SIG = 2.0 * M0                                    # = sqrt(3)
S3 = math.sqrt(3.0)
LIM_D = 4.0 * math.sqrt(2.0) - 3.0 * S3           # Delta 的极限
LIM_R = 4.0 * math.sqrt(2.0) / (3.0 * S3)         # rho 的极限

Z2 = PI * PI / 6.0
Z3 = 1.2020569031595942854
Z4 = PI ** 4 / 90.0
Z5 = 1.0369277551433699263
Z6 = PI ** 6 / 945.0
Z7 = 1.0083492773819228268
ZETA = {2: Z2, 3: Z3, 4: Z4, 5: Z5, 6: Z6, 7: Z7}


# ------------------------------------------------------------------ 求积
def tanhsinh(f, a, b, h=0.05, tmax=7.0):
    if b <= a:
        return 0.0
    c = 0.5 * (b - a)
    d = 0.5 * (a + b)
    s = 0.0
    n = int(math.ceil(tmax / h))
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


# ------------------------------------------------------------------ 被积函数
def aa(th):
    return (abs(math.cos(th - PI / 6.0)), abs(math.cos(th + PI / 6.0)), abs(math.sin(th)))


def logsum(th, p):
    """返回 (m, ls)：m = ln max_i a_i；ls = log1p(sum_{i != argmax} e^{p(ln a_i - m)}) >= 0。"""
    a = aa(th)
    imax = 0
    if a[1] > a[imax]:
        imax = 1
    if a[2] > a[imax]:
        imax = 2
    if a[imax] <= 0.0:
        return (None, None)
    m = math.log(a[imax])
    others = 0.0
    for i in (0, 1, 2):
        if i == imax or a[i] <= 0.0:
            continue
        e = p * (math.log(a[i]) - m)
        if e > -700.0:
            others += math.exp(e)
    return (m, math.log1p(others))


def g_diff(th, p):
    """S(.)^{-2/p} - M(.)^{-2} = e^{-2m} * expm1(-(2/p) ls)"""
    m, ls = logsum(th, p)
    if m is None:
        return 0.0
    return math.exp(-2.0 * m) * math.expm1(-(2.0 / p) * ls)


def m_neg2(th):
    """M(th)^{-2}"""
    m = max(aa(th))
    return 0.0 if m <= 0.0 else 1.0 / (m * m)


def a_diag_direct(p, h=0.05):
    """直接六段 tanh-sinh（不经换元）：只用于自检与交叉核对。"""
    def f(th, p=p):
        m, ls = logsum(th, p)
        if m is None:
            return 0.0
        return math.exp(-2.0 * m - (2.0 / p) * ls)

    tot = 0.0
    for i in range(len(ABRK) - 1):
        tot += tanhsinh(f, ABRK[i], ABRK[i + 1], h=h)
    return 0.75 * tot


def a_face(p):
    x = 1.0 / p
    return 2.0 ** (0.5 - x) * 4.0 * math.exp(
        2.0 * math.lgamma(1.0 + x) - math.lgamma(1.0 + 2.0 * x))


def logfac(p):
    """L = ln(A_face / 4sqrt2)：lgamma 路与幂级数路各一条。"""
    x = 1.0 / p
    l_lg = -x * math.log(2.0) + 2.0 * math.lgamma(1.0 + x) - math.lgamma(1.0 + 2.0 * x)
    l_se = -x * math.log(2.0)
    for k in (2, 3, 4, 5, 6, 7):
        l_se -= ((-1.0) ** k) * ZETA[k] * (2.0 ** k - 2.0) * (x ** k) / float(k)
    return l_lg, l_se


# ------------------------------------------------------------------ J = A_diag - 3sqrt3
def J_of_p(p, h=0.04, U=None):
    """J(p) = (3/4) int (S^{-2/p} - M^{-2}) = 层内换元部分 + 层外残段。"""
    if U is None:
        U = min(40.0, 0.9 * (PI / 6.0) * p / SIG)
    # 层内：四个打平点、各两侧
    lay = 0.0
    for th0 in TIES:
        for sgn in (1.0, -1.0):
            def f(u, th0=th0, sgn=sgn, p=p):
                return g_diff(th0 + sgn * (SIG / p) * u, p)
            lay += tanhsinh(f, 0.0, U, h=h, tmax=8.0)
    lay *= (SIG / p)
    # 层外：六段里挖掉 delta 邻域
    delta = SIG * U / p
    out = 0.0
    for i in range(len(ABRK) - 1):
        segs = [(ABRK[i], ABRK[i + 1])]
        for th0 in CUT:
            new = []
            lo, hi = th0 - delta, th0 + delta
            for (x, y) in segs:
                if hi <= x or lo >= y:
                    new.append((x, y))
                    continue
                if x < lo:
                    new.append((x, lo))
                if hi < y:
                    new.append((hi, y))
            segs = new
        for (x, y) in segs:
            if y > x:
                out += tanhsinh(lambda th, p=p: g_diff(th, p), x, y, h=h)
    J = 0.75 * (lay + out)
    return J, {"layer": 0.75 * lay, "outer": 0.75 * out, "U": U, "delta": delta}


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()

    # ---- 自检 1：int M^{-2} = 4 sqrt3（主项是闭式，这里独立算一次）
    tot = 0.0
    for i in range(len(ABRK) - 1):
        tot += tanhsinh(m_neg2, ABRK[i], ABRK[i + 1], h=0.05)
    chk_M = {"int_M_neg2": tot, "closed_form_4sqrt3": 4.0 * S3,
             "rel": abs(tot - 4.0 * S3) / (4.0 * S3)}
    print("PROGRESS: " + json.dumps({"stage": "selftest_intM2", **chk_M}))

    # ---- 自检 2：p=1,2 的精确值
    sel = {}
    for p, e in ((1.0, 3.0 * S3 / 4.0), (2.0, PI)):
        v = a_diag_direct(p, h=0.05)
        sel["A_diag_%g_rel" % p] = abs(v - e) / e
    sel["A_face_2_rel"] = abs(a_face(2.0) - PI) / PI
    sel_ok = max(sel.values()) < 1e-12
    print("PROGRESS: " + json.dumps({"stage": "selftest_exact", "vals": sel, "ok": sel_ok}))

    # ---- 交叉核对：层化方案 vs 直接六段 tanh-sinh（p=20, 100）
    cross = []
    for p in (20.0, 100.0):
        Jx, _ = J_of_p(p, h=0.04)
        v = 3.0 * S3 + Jx
        d1 = a_diag_direct(p, h=0.05)
        d2 = a_diag_direct(p, h=0.025)
        rec = {"p": p, "limit_plus_J": v, "direct_h005": d1, "direct_h0025": d2,
               "rel_vs_direct": abs(v - d1) / d1,
               "direct_self_rel": abs(d1 - d2) / d1, "J": Jx}
        cross.append(rec)
        print("PROGRESS: " + json.dumps({"stage": "cross_check", **rec}))

    # ---- 四个点名点
    PTS = [1.0e2, 1.0e4, 1.0e6, 1.0e8]
    rows = []
    for p in PTS:
        J1, info1 = J_of_p(p, h=0.04)
        J2, _ = J_of_p(p, h=0.02)
        L_lg, L_se = logfac(p)
        F = 4.0 * math.sqrt(2.0) * math.expm1(L_se)
        A_diag = 3.0 * S3 + J1
        A_face_v = 4.0 * math.sqrt(2.0) + F
        dl = A_face_v - A_diag
        rho = A_face_v / A_diag
        row = {"p": p,
               "Adiag_minus_3sqrt3": J1, "Aface_minus_4sqrt2": F,
               "Delta": dl, "rho": rho,
               "sign_Adiag_gap": (1 if J1 > 0 else (-1 if J1 < 0 else 0)),
               "sign_Aface_gap": (1 if F > 0 else (-1 if F < 0 else 0)),
               "J_p2": J1 * p * p, "J_p2_h_half": J2 * p * p,
               "J_conv_rel": abs(J1 * p * p - J2 * p * p) / max(1e-300, abs(J2 * p * p)),
               "L_lgamma": L_lg, "L_series": L_se, "L_abs_diff": abs(L_lg - L_se),
               "U": info1["U"], "delta": info1["delta"],
               "layer": info1["layer"], "outer": info1["outer"],
               "limit_minus_Delta": LIM_D - dl, "LIM_rho_minus_rho": LIM_R - rho,
               "ratio_gap_face_over_diag": (F / J1) if J1 != 0.0 else None}
        rows.append(row)
        print("PROGRESS: " + json.dumps(row))

    # ---- 判据
    A_ok = all((r["Adiag_minus_3sqrt3"] < 0.0) and (r["Aface_minus_4sqrt2"] < 0.0) for r in rows)
    ds = [r["Delta"] for r in rows]
    rhos = [r["rho"] for r in rows]
    B_parts = {
        "Delta_all_positive": all(d > 0.0 for d in ds),
        "Delta_strictly_increasing": all(ds[i] < ds[i + 1] for i in range(len(ds) - 1)),
        "limit_minus_Delta_positive": all((LIM_D - d) > 0.0 for d in ds),
        "limit_minus_Delta_decreasing": all((LIM_D - ds[i]) > (LIM_D - ds[i + 1])
                                            for i in range(len(ds) - 1)),
        "rho_strictly_increasing": all(rhos[i] < rhos[i + 1] for i in range(len(rhos) - 1)),
        "rho_below_limit": all(r < LIM_R for r in rhos),
    }
    B_ok = all(B_parts.values())
    C_parts = {
        "intM2_ok": chk_M["rel"] < 1e-12,
        "exact_selftest_ok": sel_ok,
        "J_scaling_conv_ok": all(r["J_conv_rel"] < 1e-6 for r in rows),
        "cross_check_ok": all(c["rel_vs_direct"] < 1e-10 for c in cross),
    }
    C_ok = all(C_parts.values())

    if (not C_ok) and (A_ok and B_ok):
        result = "inconclusive"
        ce = None
        why = "收敛控制未过（精度不足不是数学反例）"
    elif A_ok and B_ok:
        result = "supports"
        ce = None
        why = "四点符号与单调方向全对：两量都从下方逼近极限，Delta 递增趋于 4sqrt2-3sqrt3，rho 升向 1.088662"
    else:
        result = "refutes"
        failing = [k for k, v in (("A", A_ok), ("B", B_ok)) if not v]
        ce = {"failing_checks": failing,
              "B_detail": B_parts,
              "rows": [{k: r[k] for k in ("p", "Adiag_minus_3sqrt3", "Aface_minus_4sqrt2",
                                          "Delta", "rho")} for r in rows],
              "limits": {"Delta_limit": LIM_D, "rho_limit": LIM_R}}
        why = "符号/单调方向与断言不符（反例见 counterexample）"

    payload = {
        "result": result,
        "counterexample": ce,
        "why": why,
        "bound": ("p in {1e2, 1e4, 1e6, 1e8} for the four named points; cross-check and "
                  "layer/outer convergence control at p in {20, 100}; integrand identity "
                  "verified at p in {1, 2}"),
        "strategy": ("limit-plus-difference quadrature: A_diag-3sqrt3 = (3/4) int expm1 form "
                     "(no cancellation); tie-layer substitution u = p|th-th0|/sigma on the four "
                     "tie points + six-piece tanh-sinh on the outer remainder; A_face-4sqrt2 via "
                     "expm1 of the log-factor, L computed by lgamma AND by the x=1/p power series; "
                     "convergence control by halving the tanh-sinh step in the u variable"),
        "scaling": {"total_sec": round(time.time() - t0, 3),
                    "J_p2_sequence": [r["J_p2"] for r in rows],
                    "note": "J*p^2 基本恒定 => A_diag-3sqrt3 ~ c/p^2；A_face-4sqrt2 ~ -(4sqrt2 ln2)/p"},
        "selftest_intM2": chk_M,
        "selftest_exact": sel,
        "cross_check": cross,
        "rows": rows,
        "checks": {"A": A_ok, "B": B_ok, "C": C_ok, "B_parts": B_parts, "C_parts": C_parts},
        "limits": {"Delta": LIM_D, "rho": LIM_R, "3sqrt3": 3.0 * S3, "4sqrt2": 4.0 * math.sqrt(2.0)},
        "note": ("Delta = A_face - A_diag, rho = A_face/A_diag（任务原文约定）。"
                 "被积函数的差分写法 e^{-2m} expm1(-(2/p) ls) 是大 p 能算的前提："
                 "p=1e8 时 A_diag-3sqrt3 只有 1e-15 量级，直算会被舍入吃掉。"
                 "尖峰处理按四个打平点做换元，层外残段用同一套六段 tanh-sinh 补齐。"),
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
