#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1: power-law calibration of inf_P Var_phi L_P(phi) for ellipses x^2/a^2 + y^2/b^2 = 1.

Conjecture 000000: for a != b the ellipse has NO equichordal point, i.e. for every
interior P, Var_phi L_P(phi) > 0 strictly.

This script is NUMERIC, not a proof. It does the cheap half of the job:
  * ratios a/b in {1.01,1.05,1.1,1.25,1.5,2,2.5,3,4,5} with b=1, a=ratio,
    plus the extra pair (a,b)=(2.5,1.5) as requested;
  * search domain |P| <= 0.9*min(a,b): 11x11 coarse grid + compass(pattern) search,
    step halved down to 1e-7;
  * chord lengths from the EXACT analytic quadratic formula (no ray shooting);
  * N = 2000 sample directions for the variance.
  * calibration only: log(var_inf) = p*log(a/b - 1) + c.

Per conjectures.000000.testable.refutation_criterion a refutation needs var < 1e-18
at BOTH 2000 and 8000 directions with |P| clearly nonzero. This script supplies only
the 2000-direction half, so it can never register a refutation; the 8000-direction
recheck lives in scripts/eq_s2_crosscheck.py.

Also: var_inf -> 0 as a/b -> 1 only says the infimum degenerates with the ratio;
the power law is a calibration, NOT evidence against the conjecture.
"""
import json
import math
import os
import sys
import time

import numpy as np


# ---------------------------------------------------------------- geometry ---
def chord_lengths(a, b, P, n_dirs):
    """Exact chord lengths through interior point P in n_dirs uniform directions.

    Line P + t*u (|u|=1) cut with x^2/a^2 + y^2/b^2 = 1 gives
    A t^2 + B t + C = 0 with A = ux^2/a^2 + uy^2/b^2, B = 2(px*ux/a^2 + py*uy/b^2),
    C = px^2/a^2 + py^2/b^2 - 1 < 0.  Chord length = t+ - t- = sqrt(B^2-4AC)/A.
    """
    th = np.arange(n_dirs, dtype=np.float64) * (2.0 * math.pi / n_dirs)
    ux = np.cos(th)
    uy = np.sin(th)
    A = (ux * ux) / (a * a) + (uy * uy) / (b * b)
    B = 2.0 * ((P[0] * ux) / (a * a) + (P[1] * uy) / (b * b))
    C = (P[0] * P[0]) / (a * a) + (P[1] * P[1]) / (b * b) - 1.0
    disc = B * B - 4.0 * A * C
    np.maximum(disc, 0.0, out=disc)
    L = np.sqrt(disc) / A
    return L


def variance(a, b, P, n_dirs):
    L = chord_lengths(a, b, P, n_dirs)
    m = L.mean()
    d = L - m
    return float((d * d).mean()), float(m), float(L.min()), float(L.max())


# ---------------------------------------------------------------- search -----
def compass(f, x0, R, tol=1e-7, max_eval=4000):
    """Compass / pattern search on 8 directions, step halved on no improvement."""
    x = [float(x0[0]), float(x0[1])]
    fx = float(f(x))
    n = 1
    step = 0.1 * R
    dirs = [(math.cos(2.0 * math.pi * k / 8.0), math.sin(2.0 * math.pi * k / 8.0))
            for k in range(8)]
    while step >= tol and n < max_eval:
        improved = False
        for dx, dy in dirs:
            y = (x[0] + step * dx, x[1] + step * dy)
            if math.hypot(y[0], y[1]) > R:
                continue
            fy = float(f(y))
            n += 1
            if fy < fx:
                x, fx = [y[0], y[1]], fy
                improved = True
                break
        if not improved:
            step *= 0.5
    return x, fx, n, bool(step < tol)


def grid_points(R, n_side=11):
    pts = []
    for i in range(n_side):
        px = -R + 2.0 * R * i / (n_side - 1)
        for j in range(n_side):
            py = -R + 2.0 * R * j / (n_side - 1)
            if math.hypot(px, py) <= R + 1e-12:
                pts.append((px, py))
    return pts


# ---------------------------------------------------------------- cases ------
CASES = [
    ("1.01/1", 1.01, 1.0),
    ("1.05/1", 1.05, 1.0),
    ("1.1/1", 1.1, 1.0),
    ("1.25/1", 1.25, 1.0),
    ("1.5/1", 1.5, 1.0),
    ("2/1", 2.0, 1.0),
    ("2.5/1", 2.5, 1.0),
    ("3/1", 3.0, 1.0),
    ("4/1", 4.0, 1.0),
    ("5/1", 5.0, 1.0),
    ("2.5/1.5", 2.5, 1.5),
]

N_DIRS = 2000
TOL = 1e-7


def main():
    t0 = time.time()
    results = []
    scaling = []
    total_done = len(CASES)
    for idx, (tag, a, b) in enumerate(CASES, start=1):
        tc0 = time.time()
        R = 0.9 * min(a, b)

        def f(P):
            return variance(a, b, P, N_DIRS)[0]

        pts = grid_points(R, 11)
        scored = []
        for P in pts:
            scored.append((f(P), P))
        scored.sort(key=lambda t: t[0])
        n_evals = len(scored)

        best_var, best_P = scored[0][0], list(scored[0][1])
        starts = [scored[k][1] for k in range(min(3, len(scored)))]
        conv = []
        for s in starts:
            x, fx, ne, cvg = compass(f, s, R, tol=TOL)
            n_evals += ne
            conv.append(cvg)
            if fx < best_var:
                best_var, best_P = fx, x

        _, meanL, Lmin, Lmax = variance(a, b, best_P, N_DIRS)
        secs = time.time() - tc0
        results.append({
            "case": tag,
            "a": a,
            "b": b,
            "a_over_b": a / b,
            "search_radius_0.9min": R,
            "directions": N_DIRS,
            "var_inf": best_var,
            "P_star": [best_P[0], best_P[1]],
            "abs_P_star": math.hypot(best_P[0], best_P[1]),
            "P_star_on_domain_boundary": bool(abs(math.hypot(best_P[0], best_P[1]) - R) < 1e-6),
            "evals": n_evals,
            "grid_points": len(pts),
            "converged": bool(all(conv)),
            "mean_chord": meanL,
            "Lmin": Lmin,
            "Lmax": Lmax,
            "seconds": secs,
        })
        scaling.append({"n": tag, "seconds": round(secs, 4), "evals": n_evals,
                        "dirs": N_DIRS})
        print("PROGRESS: " + json.dumps({"task": "S1", "done": idx, "total": total_done,
                                         "case": tag, "var_inf": best_var,
                                         "abs_P_star": math.hypot(best_P[0], best_P[1]),
                                         "seconds": round(secs, 4)}, sort_keys=True),
              flush=True)

    # ---- calibration fit: log var_inf vs log(a/b - 1), b=1 ratio cases only ----
    xs, ys, tags_fit = [], [], []
    for r in results:
        if abs(r["b"] - 1.0) > 1e-15:
            continue
        x = math.log(r["a_over_b"] - 1.0)
        if r["var_inf"] <= 0.0:
            continue
        xs.append(x)
        ys.append(math.log(r["var_inf"]))
        tags_fit.append(r["case"])
    fit = None
    if len(xs) >= 2:
        X = np.asarray(xs)
        Y = np.asarray(ys)
        p, c = np.polyfit(X, Y, 1)
        pred = p * X + c
        resid = Y - pred
        rms = float(np.sqrt((resid * resid).mean()))
        fit = {"power_exponent_p": float(p), "intercept": float(c),
               "residual_rms_logspace": rms,
               "n_points": len(xs), "points": tags_fit,
               "residuals": {t: float(v) for t, v in zip(tags_fit, resid)},
               "note": "calibration only: var_inf->0 as a/b->1 says the infimum degenerates with the ratio, it is NOT evidence against conjecture 000000"}
        print("S1_FIT: " + json.dumps(fit, sort_keys=True), flush=True)

    min_case = min(results, key=lambda r: r["var_inf"])
    refute_candidates = [r["case"] for r in results if r["var_inf"] < 1e-18]
    if refute_candidates:
        result = "inconclusive"
        verdict_note = ("candidate(s) %s have 2000-direction variance < 1e-18; "
                        "the 8000-direction recheck (S2) is required, S1 alone cannot refute"
                        % refute_candidates)
    else:
        result = "supports"
        verdict_note = ("no (a,b) in the tested grid had 2000-direction variance < 1e-18; "
                        "minimum var_inf = %.6e at %s" % (min_case["var_inf"], min_case["case"]))

    os.makedirs("out/eq_s1", exist_ok=True)
    payload = {"cases": results, "fit": fit, "min_case": min_case["case"],
               "min_var_inf": min_case["var_inf"],
               "directions": N_DIRS, "search_domain": "|P| <= 0.9*min(a,b)",
               "compass_tol": TOL, "runtime_sec": time.time() - t0}
    with open(os.path.join("out", "eq_s1", "results.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)

    summary = {r["case"]: {"var_inf": r["var_inf"], "P_star": r["P_star"],
                            "abs_P_star": r["abs_P_star"], "evals": r["evals"],
                            "converged": r["converged"]} for r in results}
    out = {
        "result": result,
        "bound": {"search_domain": "|P| <= 0.9*min(a,b)", "directions": N_DIRS,
                  "compass_step_tol": TOL, "n_cases": len(results),
                  "min_var_inf": min_case["var_inf"], "min_case": min_case["case"],
                  "cases": summary},
        "strategy": "coarse 11x11 grid (multistart) + compass/pattern search (8 directions, step halved to 1e-7) + analytic quadratic chord-length formula",
        "scaling": scaling,
        "fit_power_law": fit,
        "note": verdict_note + "; numeric evidence only, not a proof; no Rychlik convex-body negative solution is used as a proof step",
        "runtime_sec": time.time() - t0,
    }
    print("REPRO_RESULT: " + json.dumps(out, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
