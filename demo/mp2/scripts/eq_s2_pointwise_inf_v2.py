#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2 (v2): pointwise cross-check of inf_P Var_phi L_P(phi) for ellipses
x^2/a^2 + y^2/b^2 = 1 (a != b), conjecture 000000.

Why v2 (v1 = scripts/eq_s2_pointwise_inf.py crashed with exit_code=1 and, while
alive, searched the WRONG region):
  (1) v1 confined the local search to |P| <= 0.1 instead of a neighbourhood of
      S1's minimiser, so it walked away from P* to a worse point;
  (2) v1 built its REPRO_RESULT with numpy bool_ -> json.dumps raised
      TypeError: Object of type bool is not JSON serializable (exit_code=1);
  (3) v1 used the one-pass variance mean(L^2)-mean(L)^2.  The refutation
      threshold 1e-18 is far below what that formula can resolve in double
      precision, so a 'measured value < 1e-18' would have been noise.  v2 uses
      a two-pass variance and re-evaluates the final point in 50-digit mpmath
      arithmetic so the 1e-18 scale is actually resolvable.

S1 (exp:000008) minimised with 2000 directions over |P| <= 0.9*min(a,b) and got
the smallest var_inf at a/b = 1.01 (1.2253700694081736e-09 at
P* = (1.661009595586317e-08, -0.14037079420907037)); a/b = 1.1 is carried as a
secondary/robustness case.

Refutation criterion (conjecture 000000.testable.refutation_criterion, quoted):
  only if the 2000-direction variance AND the 8000-direction variance are both
  < 1e-18 AND |P| is clearly nonzero does this count as a counterexample;
  otherwise it is supporting numeric evidence only, never a proof.
"""
import json
import math
import time

import numpy as np

try:
    import mpmath as mp
    HAVE_MP = True
except Exception:
    HAVE_MP = False

TWO_PI = 2.0 * math.pi
EPS = np.finfo(float).eps
MP_DPS = 50
if HAVE_MP:
    mp.mp.dps = MP_DPS


def chord_np(a, b, P, n):
    k = np.arange(n, dtype=np.float64)
    phi = TWO_PI * k / n
    c = np.cos(phi)
    s = np.sin(phi)
    px = float(P[0])
    py = float(P[1])
    A = (c * c) / (a * a) + (s * s) / (b * b)
    B = px * c / (a * a) + py * s / (b * b)
    C = (px * px) / (a * a) + (py * py) / (b * b)
    disc = B * B - A * (C - 1.0)
    if np.any(disc <= 0.0):
        raise RuntimeError("degenerate direction / point outside ellipse")
    return 2.0 * np.sqrt(disc) / A


def var_np(a, b, P, n):
    L = chord_np(a, b, P, n)
    m1 = float(np.mean(L))
    d = L - m1
    return float(np.mean(d * d)), m1, float(L.min()), float(L.max())


def chord_mp(a, b, P, n):
    aa = mp.mpf(a)
    bb = mp.mpf(b)
    px = mp.mpf(float(P[0]))
    py = mp.mpf(float(P[1]))
    out = []
    for k in range(n):
        phi = 2 * mp.pi * k / n
        c = mp.cos(phi)
        s = mp.sin(phi)
        A = (c * c) / (aa * aa) + (s * s) / (bb * bb)
        B = px * c / (aa * aa) + py * s / (bb * bb)
        C = (px * px) / (aa * aa) + (py * py) / (bb * bb)
        disc = B * B - A * (C - 1)
        if disc <= 0:
            raise RuntimeError("degenerate direction (mp)")
        out.append(2 * mp.sqrt(disc) / A)
    return out


def var_mp(a, b, P, n):
    L = chord_mp(a, b, P, n)
    m1 = mp.fsum(L) / n
    v = mp.fsum([(x - m1) * (x - m1) for x in L]) / n
    return float(v), float(m1), float(min(L)), float(max(L))


def compass_box(f, x0, center, R, dom, tol=1e-9, step0=0.02, max_eval=3000):
    def clip(x):
        dx = x[0] - center[0]
        dy = x[1] - center[1]
        r = math.hypot(dx, dy)
        if r > R:
            x = [center[0] + dx * R / r, center[1] + dy * R / r]
        rd = math.hypot(x[0], x[1])
        if rd > dom:
            x = [x[0] * dom / rd, x[1] * dom / rd]
        return [float(x[0]), float(x[1])]

    x = clip(list(x0))
    fx = f(x)
    n_eval = 1
    step = step0
    dirs = [(math.cos(TWO_PI * i / 8.0), math.sin(TWO_PI * i / 8.0)) for i in range(8)]
    while step > tol and n_eval < max_eval:
        improved = False
        for dx, dy in dirs:
            y = clip([x[0] + step * dx, x[1] + step * dy])
            fy = f(y)
            n_eval += 1
            if fy < fx:
                x = y
                fx = fy
                improved = True
                break
        if not improved:
            step *= 0.5
    return x, fx, n_eval, step <= tol


def main():
    t_start = time.time()
    S1 = [
        (1.01, 1.0, [1.661009595586317e-08, -0.14037079420907037], 1.2253700694081736e-09, "1.01/1"),
        (1.1, 1.0, [-2.7613838554949325e-09, 0.41661646772447836], 1.0330498044123298e-05, "1.1/1"),
    ]
    out = {
        "task": "S2 pointwise inf cross-check: 2000 vs 8000 directions at the S1 minimiser neighbourhood",
        "depends_on": "exp 000008 (S1), conjecture 000000",
        "v1_failure": "scripts/eq_s2_pointwise_inf.py exited 1 (numpy bool_ not JSON serializable) and its local box was |P|<=0.1, not around P*; row exp:000009 is inconclusive and stays inconclusive",
        "refutation_criterion_quoted": "2000-dir variance < 1e-18 AND 8000-dir variance < 1e-18 AND |P| clearly nonzero",
        "strategy": "compass/pattern search (8 directions, step halved from 0.02 to 1e-9) inside a Euclidean box of radius R_loc around S1's P*, clipped to |P| <= 0.9*min(a,b); 8000-direction minimisation, then BOTH 2000- and 8000-direction variances evaluated at the final point in numpy float64 (two-pass) and in 50-digit mpmath",
        "precision_note": "mpmath 50-digit two-pass variance is used so the 1e-18 threshold is resolvable; the float64 one-pass formula m2-m1^2 cannot resolve anything below ~8*eps*mean(L^2) ~ 1e-15",
        "mpmath_available": HAVE_MP,
    }
    cases = {}
    scaling = []
    total = len(S1)
    for idx, (a, b, P0, v1, tag) in enumerate(S1, start=1):
        t0 = time.time()
        dom = 0.9 * min(a, b)
        R_loc = 0.05
        f8 = lambda P, a=a, b=b: var_np(a, b, P, 8000)[0]
        starts = [P0, [P0[0] + 0.02, P0[1]], [P0[0] - 0.02, P0[1] + 0.01], [0.0, P0[1]]]
        best = None
        runs = []
        for s in starts:
            xs, fs, ne, conv = compass_box(f8, s, P0, R_loc, dom)
            runs.append({"start": [float(s[0]), float(s[1])], "P": [float(xs[0]), float(xs[1])],
                         "var_8000dirs_np": float(fs), "evals": int(ne), "converged": bool(conv)})
            if best is None or fs < best[1]:
                best = (xs, float(fs), ne, conv)
        Pf = [float(best[0][0]), float(best[0][1])]
        v2k_np, m2k, lmin2, lmax2 = var_np(a, b, Pf, 2000)
        v8k_np, m8k, lmin8, lmax8 = var_np(a, b, Pf, 8000)
        rec = {
            "a": a,
            "b": b,
            "a_over_b": a / b,
            "search_domain_radius": dom,
            "local_box_radius_around_S1_Pstar": R_loc,
            "S1_P_star": [float(P0[0]), float(P0[1])],
            "S1_var_inf_2000dirs": v1,
            "P_star": Pf,
            "abs_P_star": math.hypot(Pf[0], Pf[1]),
            "local_runs": runs,
            "local_evals_best": int(best[2]),
            "converged": bool(best[3]),
            "var_2000dirs_np_two_pass": v2k_np,
            "var_8000dirs_np_two_pass": v8k_np,
            "var_8000_minus_2000_np": v8k_np - v2k_np,
            "mean_chord_2000dirs": m2k,
            "mean_chord_8000dirs": m8k,
            "Lmin_2000dirs": lmin2,
            "Lmax_2000dirs": lmax2,
            "Lmin_8000dirs": lmin8,
            "Lmax_8000dirs": lmax8,
            "rel_var_8000dirs": v8k_np / (m8k * m8k),
            "float64_one_pass_noise_floor_8eps_meanL2": 8.0 * EPS * m8k * m8k,
        }
        if HAVE_MP:
            vm2000, mm2000, mlmin2, mlmax2 = var_mp(a, b, Pf, 2000)
            vm8000, mm8000, mlmin8, mlmax8 = var_mp(a, b, Pf, 8000)
            cross2000, _, _, _ = var_mp(a, b, P0, 2000)
            rec.update({
                "mp_dps": MP_DPS,
                "var_2000dirs_mp": vm2000,
                "var_8000dirs_mp": vm8000,
                "var_8000_minus_2000_mp": vm8000 - vm2000,
                "mean_chord_8000dirs_mp": mm8000,
                "Lmin_8000dirs_mp": mlmin8,
                "Lmax_8000dirs_mp": mlmax8,
                "rel_var_8000dirs_mp": vm8000 / (mm8000 * mm8000),
                "var_at_S1_Pstar_2000dirs_mp": cross2000,
                "var_2000dirs_np_minus_mp": v2k_np - vm2000,
                "var_8000dirs_np_minus_mp": v8k_np - vm8000,
                "both_below_1e18_mp": bool(vm2000 < 1e-18 and vm8000 < 1e-18),
                "abs_P_clearly_nonzero": bool(math.hypot(Pf[0], Pf[1]) > 1e-3),
            })
            rec["satisfies_refutation_criterion"] = bool(
                rec["both_below_1e18_mp"] and rec["abs_P_clearly_nonzero"]
            )
        else:
            rec["satisfies_refutation_criterion"] = False
            rec["mp_note"] = "mpmath unavailable: no high-precision cross-check, values are float64 only"
        secs = time.time() - t0
        rec["seconds"] = round(secs, 3)
        scaling.append({"n": tag, "a": a, "b": b, "a_over_b": a / b, "directions_final": [2000, 8000],
                        "local_evals_best": rec["local_evals_best"], "seconds": round(secs, 3),
                        "search_domain_radius": dom, "local_box_radius": R_loc})
        cases[tag] = rec
        print("PROGRESS: " + json.dumps({"task": "S2v2", "done": idx, "total": total, "case": tag,
                                        "P_star": Pf, "abs_P_star": rec["abs_P_star"],
                                        "var_2000dirs_mp": rec.get("var_2000dirs_mp"),
                                        "var_8000dirs_mp": rec.get("var_8000dirs_mp"),
                                        "converged": rec["converged"], "seconds": round(secs, 3)},
                                       sort_keys=True), flush=True)
    refutes = [t for t, r in cases.items() if r.get("satisfies_refutation_criterion")]
    if refutes:
        tag = refutes[0]
        r = cases[tag]
        out["result"] = "refutes"
        out["counterexample"] = {"a": r["a"], "b": r["b"], "P": r["P_star"],
                                 "var_2000dirs_mp": r["var_2000dirs_mp"],
                                 "var_8000dirs_mp": r["var_8000dirs_mp"],
                                 "abs_P_star": r["abs_P_star"]}
    elif HAVE_MP and all(cases[t]["both_below_1e18_mp"] for t in cases):
        out["result"] = "inconclusive"
        out["note"] = "variance below 1e-18 but |P| not clearly nonzero, or not all cases agree: cannot call it a counterexample"
    else:
        out["result"] = "supports"
        out["note"] = ("no tested (a,b) reached 2000/8000-direction variance < 1e-18; the minimum over S1's grid "
                       "(a/b=1.01, |P*| clearly nonzero) stays well above the threshold on both direction counts; "
                       "numeric evidence only, not a proof; no Rychlik convex-body negative solution is used as a proof step")
    out["cases"] = cases
    out["scaling"] = scaling
    out["runtime_sec"] = round(time.time() - t_start, 3)
    print("REPRO_RESULT: " + json.dumps(out, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
