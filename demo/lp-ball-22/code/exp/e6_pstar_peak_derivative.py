#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 本趟任务 (2)：用导数判据把 p in (2,20] 上的 Delta 零点与 rho 的驻点加密到 1e-9，并判 rho 的单调性。

口径 = exp:000014 / exp:000016 / exp:000020（同一 A_diag 与 A_face）：
  A_diag(p) = (3/4) int_0^{2pi} S(th)^{-2/p} dth,
              S = |cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p
              六段 tanh-sinh(DE, 步长 h)，断点 {0,pi/3,2pi/3,pi,4pi/3,5pi/3,2pi}
              被积函数走 log-sum-exp（p 大时 a_i^p 不下溢）
  导数用精确恒等式（不是差商）：d/dp S^{-2/p} = S^{-2/p} * (2/p^2) * ln S
    => A_diag'(p) = (3/4)*(2/p^2) * int S^{-2/p} * ln S dth（同一套断点与求积）
  A_face(p) = 2^{1/2-1/p} * 4 * Gamma(1+1/p)^2 / Gamma(1+2/p)
    => A_face'(p) = A_face(p) * p^{-2} * [ln2 - 2 psi(1+1/p) + 2 psi(1+2/p)]
       （psi 脚本内自实现：递推 + 渐近级数；与 lgamma 的中心差商对拍）
两套约定都算、各自报符号：
  R2（任务原文）：rho2 = A_face/A_diag,  Delta2 = A_face - A_diag
  R1（exp:000014/000016 落库）：rho1 = A_diag/A_face = 1/rho2,  Delta1 = -Delta2

脚本判据（硬编码、由脚本判、不过模型）：
  (a) Delta2 在 (2,20] 上恰有一个零点；Newton + 夹逼，相对宽度 <= 1e-12；
  (b) rho2 的驻点在 (2,20] 上唯一（rho2' 在 120 点对数采样上变号恰一次）；
  (c) 单调性：rho2' 在 (2,p_ext) 与 (p_ext,20] 上的符号是否各自恒定（各 150 点 + 最小裕度）；
  (d) 自检：A_diag(1)/A_diag(2)/A_face(2) 精确值；A_face' 与中心差商；A_diag' 与 Delta 的中心差商；
      Delta2 与 rho2' 在 p=3.02/5/10 上的 h-细化（h=0.05 vs 0.025）。
result：任务原文那条断言（(i) 零点唯一且可加密；(ii) rho 在 p_peak~3.02 取极大、(2,p_peak) 严格增、
        (p_peak,p*) 严格减）与读数不符 => refutes（counterexample 点名反例点与读数）；相符 => supports；
        自检不过 => inconclusive（数值精度不足不是数学反例）。
"""
import json
import math
import time

PI = math.pi
HP = PI / 2.0
ABRK = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]


def tanhsinh_pair(f, a, b, h=0.05, tmax=7.0):
    """一段上同时求两个被积函数（一次遍历，两个累加）。"""
    if b <= a:
        return (0.0, 0.0)
    c = 0.5 * (b - a)
    d = 0.5 * (a + b)
    s0 = 0.0
    s1 = 0.0
    n = int(tmax / h)
    for k in range(-n, n + 1):
        t = k * h
        u = HP * math.sinh(t)
        x = math.tanh(u)
        if x >= 1.0 or x <= -1.0:
            continue
        ch = math.cosh(u)
        w = HP * math.cosh(t) / (ch * ch)
        v0, v1 = f(d + c * x)
        s0 += w * v0
        s1 += w * v1
    return (s0 * c * h, s1 * c * h)


def integrand_pair(p, th):
    """返回 (S^{-2/p}, S^{-2/p} * ln S)，S = sum_i a_i^p；log-sum-exp 形式防下溢。"""
    a = (abs(math.cos(th - PI / 6.0)), abs(math.cos(th + PI / 6.0)), abs(math.sin(th)))
    m = -1.0e308
    for v in a:
        if v > 0.0:
            lv = math.log(v)
            if lv > m:
                m = lv
    s = 0.0
    for v in a:
        if v > 0.0:
            e = p * (math.log(v) - m)
            if e > -745.0:
                s += math.exp(e)
    ls = math.log(s)
    v0 = math.exp(-2.0 * m - (2.0 / p) * ls)
    lnS = p * m + ls
    return (v0, v0 * lnS)


def a_diag_deriv(p, h=0.05):
    t0 = 0.0
    t1 = 0.0
    for i in range(len(ABRK) - 1):
        a, b = ABRK[i], ABRK[i + 1]
        s0, s1 = tanhsinh_pair(lambda th, p=p: integrand_pair(p, th), a, b, h=h)
        t0 += s0
        t1 += s1
    return (0.75 * t0, 0.75 * (2.0 / (p * p)) * t1)


def a_face(p):
    return 2.0 ** (0.5 - 1.0 / p) * 4.0 * math.exp(
        2.0 * math.lgamma(1.0 + 1.0 / p) - math.lgamma(1.0 + 2.0 / p))


def digamma(x):
    """psi(x)，x>0：递推抬到 x>=12 后用渐近级数。"""
    r = 0.0
    while x < 12.0:
        r -= 1.0 / x
        x += 1.0
    inv = 1.0 / x
    u = inv * inv
    return r + math.log(x) - 0.5 * inv - u * (1.0 / 12.0 - u * (1.0 / 120.0 - u * (1.0 / 252.0 - u / 240.0)))


def a_face_deriv(p):
    g = math.log(2.0) - 2.0 * digamma(1.0 + 1.0 / p) + 2.0 * digamma(1.0 + 2.0 / p)
    return a_face(p) * g / (p * p)


def probe(p, h=0.05):
    ad, dad = a_diag_deriv(p, h=h)
    af = a_face(p)
    daf = a_face_deriv(p)
    dr2 = (daf * ad - af * dad) / (ad * ad)
    return {"p": p, "A_diag": ad, "A_face": af,
            "Delta2": af - ad, "dDelta2": daf - dad,
            "rho2": af / ad, "drho2": dr2, "rho1": ad / af, "drho1": -dr2 / ((af / ad) ** 2)}


def d2(p, h=0.05):
    ad, _ = a_diag_deriv(p, h=h)
    return a_face(p) - ad


def dd2(p, h=0.05):
    _, dad = a_diag_deriv(p, h=h)
    return a_face_deriv(p) - dad


def dr2(p, h=0.05):
    ad, dad = a_diag_deriv(p, h=h)
    af = a_face(p)
    daf = a_face_deriv(p)
    return (daf * ad - af * dad) / (ad * ad)


def num_deriv(f, p, rt=1e-5):
    hh = rt * p
    return (f(p + hh) - f(p - hh)) / (2.0 * hh)


def solve_newton(f, df, lo, hi, rtol=1e-12, itmax=200):
    flo = f(lo)
    fhi = f(hi)
    if not (flo * fhi < 0.0):
        return None
    its = 0
    for its in range(1, itmax + 1):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        dm = df(mid)
        cand = mid
        if dm != 0.0:
            c1 = mid - fm / dm
            if lo < c1 < hi:
                cand = c1
        fc = f(cand)
        if fc == 0.0:
            lo = cand
            hi = cand
            break
        if (fc > 0.0) == (flo > 0.0):
            lo, flo = cand, fc
        else:
            hi, fhi = cand, fc
        if (hi - lo) <= rtol * 0.5 * (hi + lo):
            break
    pc = 0.5 * (lo + hi)
    return {"p": pc, "lo": lo, "hi": hi, "rel_width": (hi - lo) / (0.5 * (hi + lo)),
            "value": f(pc), "slope": df(pc), "iters": its}


def scan_sign_changes(g, lo, hi, n=120):
    pts = [lo * (hi / lo) ** (i / (n - 1.0)) for i in range(n)]
    vals = [g(p) for p in pts]
    ch = []
    for i in range(1, n):
        if vals[i] != 0.0 and vals[i - 1] != 0.0 and (vals[i] > 0.0) != (vals[i - 1] > 0.0):
            ch.append([pts[i - 1], pts[i]])
    return pts, vals, ch


def main():
    t0 = time.time()
    exact1 = 3.0 * math.sqrt(3.0) / 4.0

    # ---------------- 自检 ----------------
    st = {
        "a_diag_1_rel": abs(a_diag_deriv(1.0)[0] - exact1) / exact1,
        "a_diag_2_rel": abs(a_diag_deriv(2.0)[0] - PI) / PI,
        "a_face_2_rel": abs(a_face(2.0) - PI) / PI,
    }
    for p in (3.02, 7.0):
        dnum = (a_face(p * (1.0 + 1e-7)) - a_face(p * (1.0 - 1e-7))) / (2.0 * 1e-7 * p)
        st["a_face_deriv_rel@%.2f" % p] = abs(a_face_deriv(p) - dnum) / abs(a_face_deriv(p))
        adp = a_diag_deriv(p * (1.0 + 1e-6))[0]
        adm = a_diag_deriv(p * (1.0 - 1e-6))[0]
        dnum2 = (adp - adm) / (2.0 * 1e-6 * p)
        st["a_diag_deriv_rel@%.2f" % p] = abs(a_diag_deriv(p)[1] - dnum2) / abs(a_diag_deriv(p)[1])

    refine = []
    for p in (3.02, 5.0, 10.0):
        r = {"p": p,
             "Delta2_h005": d2(p, h=0.05), "Delta2_h0025": d2(p, h=0.025),
             "drho2_h005": dr2(p, h=0.05), "drho2_h0025": dr2(p, h=0.025)}
        r["Delta2_rel"] = abs(r["Delta2_h005"] - r["Delta2_h0025"]) / max(1e-300, abs(r["Delta2_h005"]))
        r["drho2_rel"] = abs(r["drho2_h005"] - r["drho2_h0025"]) / max(1e-300, abs(r["drho2_h005"]))
        refine.append(r)
        print("PROGRESS: " + json.dumps({"stage": "h_refine", **{k: r[k] for k in ("p", "Delta2_rel", "drho2_rel")}}))

    selftest_ok = (max(st["a_diag_1_rel"], st["a_diag_2_rel"], st["a_face_2_rel"]) < 1e-12
                   and max(v for k, v in st.items() if "_deriv_rel" in k) < 1e-6
                   and max(r["Delta2_rel"] for r in refine) < 1e-10
                   and max(r["drho2_rel"] for r in refine) < 1e-9)

    # ---------------- Delta2 的零点 ----------------
    pts, vals, ch_d = scan_sign_changes(d2, 2.01, 20.0, n=120)
    print("PROGRESS: " + json.dumps({"stage": "scan_Delta2", "n": len(pts),
                                     "changes": ch_d, "D_at_2.01": vals[0], "D_at_20": vals[-1]}))
    root = solve_newton(d2, dd2, ch_d[0][0], ch_d[0][1]) if len(ch_d) == 1 else None
    if root:
        print("PROGRESS: " + json.dumps({"stage": "root_Delta2", "p_star": root["p"],
                                         "rel_width": root["rel_width"], "Delta2": root["value"],
                                         "dDelta2": root["slope"], "iters": root["iters"]}))

    # ---------------- rho2 的驻点 ----------------
    pts2, vals2, ch_r = scan_sign_changes(dr2, 2.01, 20.0, n=120)
    print("PROGRESS: " + json.dumps({"stage": "scan_drho2", "n": len(pts2), "changes": ch_r,
                                     "drho2_at_2.01": vals2[0], "drho2_at_20": vals2[-1]}))
    ext = None
    if len(ch_r) == 1:
        lo, hi = ch_r[0]
        ext = solve_newton(dr2, lambda x: num_deriv(dr2, x), lo, hi)
        if ext:
            rho2_at = a_face(ext["p"]) / a_diag_deriv(ext["p"])[0]
            ext["rho2"] = rho2_at
            ext["rho1"] = 1.0 / rho2_at
            ext["curvature"] = num_deriv(dr2, ext["p"])
            print("PROGRESS: " + json.dumps({"stage": "stationary", **ext}))

    # ---------------- 单调性（两套约定） ----------------
    mono = {}
    if ext:
        pe = ext["p"]
        left = [2.02 * (pe / 2.02) ** (i / 149.0) for i in range(150)]
        left = [p for p in left if p < pe - 1e-6]
        right = [pe * (19.9 / pe) ** (i / 149.0) for i in range(150)]
        right = [p for p in right if p > pe + 1e-6]
        lv = [dr2(p) for p in left]
        rv = [dr2(p) for p in right]
        mono["left"] = {"n": len(lv), "max_drho2": max(lv), "min_drho2": min(lv),
                        "all_negative": all(v < 0.0 for v in lv),
                        "all_positive": all(v > 0.0 for v in lv),
                        "min_abs": min(abs(v) for v in lv)}
        mono["right"] = {"n": len(rv), "max_drho2": max(rv), "min_drho2": min(rv),
                         "all_negative": all(v < 0.0 for v in rv),
                         "all_positive": all(v > 0.0 for v in rv),
                         "min_abs": min(abs(v) for v in rv)}
        mono["note"] = ("left = (2, p_ext)，right = (p_ext, 20]；drho2 = d/dp(A_face/A_diag)，"
                        "drho1 = -drho2/rho2^2 与它符号相反")
        print("PROGRESS: " + json.dumps({"stage": "monotone", **mono}))

    # ---------------- 反例点（任务原文约定 R2 的两个见证） ----------------
    wit = []
    for p in (2.5, 4.0):
        pr = probe(p)
        wit.append({"p": p, "rho_face_over_diag": pr["rho2"], "drho_face_over_diag": pr["drho2"],
                    "rho_diag_over_face": pr["rho1"], "drho_diag_over_face": pr["drho1"],
                    "Delta_face_minus_diag": pr["Delta2"]})
    for w in wit:
        print("PROGRESS: " + json.dumps({"stage": "witness", **w}))

    # ---------------- 判据 ----------------
    ok_root = (root is not None and len(ch_d) == 1 and root["rel_width"] < 1e-12
               and 2.0 < root["p"] < 20.0)
    ok_ext = (ext is not None and len(ch_r) == 1 and ext["rel_width"] < 1e-12)
    claim_ii_R2 = None
    if ok_ext and mono:
        claim_ii_R2 = (mono["left"]["all_positive"] and mono["right"]["all_negative"])
    if not selftest_ok:
        result = "inconclusive"
        ce = None
        why = "自检/收敛控制未过，读数不可用（精度不足不是数学反例）"
    elif not (ok_root and ok_ext):
        result = "inconclusive"
        ce = None
        why = "零点或驻点未在 (2,20] 上唯一确定（采样级读数不足以判这两条）"
    elif claim_ii_R2:
        result = "supports"
        ce = None
        why = "零点唯一、驻点唯一，且 rho2 在 (2,p_ext) 严格增、(p_ext,20] 严格减"
    else:
        result = "refutes"
        ce = {
            "claim_part": "(ii) rho(p)=A_face/A_diag 在 p_peak~3.02 处取极大，(2,p_peak) 严格增，(p_peak,p*) 严格减",
            "p_peak": ext["p"],
            "rho_A_face_over_A_diag_at_peak": ext["rho2"],
            "rho_A_diag_over_A_face_at_peak": ext["rho1"],
            "curvature_sign": ("rho2'' > 0 => 极小（不是极大）" if ext["curvature"] > 0 else "rho2'' < 0"),
            "witnesses": wit,
            "task_value_1_0116_belongs_to": "A_diag/A_face（R1 约定）在 p_peak 的极大值，不是 A_face/A_diag（R2）的极大值",
        }
        why = "读数与任务原文的单调方向相反：R2 下 rho 在 p_peak 是极小；1.0116 属于 1/rho"

    payload = {
        "result": result,
        "counterexample": ce,
        "why": why,
        "bound": "p in (2,20]; 120-point log scan for sign changes; root and stationary point refined to relative width <= 1e-12 (ok_root requires < 1e-12)",
        "strategy": ("6-piece tanh-sinh (DE, h=0.05) with log-sum-exp integrand; derivatives by analytic "
                     "identities (A_diag' = (3/4)(2/p^2) int S^{-2/p} ln S dth; A_face' via self-implemented "
                     "digamma) — no finite differences in the judged quantities; safeguarded Newton for the "
                     "Delta2 root; safeguarded Newton + central-difference slope for the stationary point of rho; "
                     "h-refinement (0.05 vs 0.025) as convergence control"),
        "scaling": {"total_sec": round(time.time() - t0, 2),
                    "probe_evals_equiv": len(pts) + len(pts2) + 2 * 150 + 40},
        "selftest": st,
        "selftest_ok": selftest_ok,
        "h_refine": refine,
        "scan_Delta2": {"changes": ch_d, "Delta2_at_2.01": vals[0], "Delta2_at_20": vals[-1]},
        "scan_drho2": {"changes": ch_r, "drho2_at_2.01": vals2[0], "drho2_at_20": vals2[-1]},
        "root_Delta2": root,
        "stationary_rho2": ext,
        "monotone": mono,
        "witnesses": wit,
        "checks": {"root_unique_and_tight": ok_root, "stationary_unique_and_tight": ok_ext,
                   "claim_ii_holds_in_R2": claim_ii_R2},
        "note": ("Delta2 = A_face - A_diag，rho2 = A_face/A_diag（任务原文约定）；R1 = 落库约定（reciprocal）。"
                 "A_face 用闭式（exp:000015 已与两条独立数值路核过）；A_diag 用 exp:000014 的六段 tanh-sinh，"
                 "只把被积函数改成 log-sum-exp。单调性是 150+150 点的采样级读数（不是穷举）。"),
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
