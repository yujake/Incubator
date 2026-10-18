#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2: pointwise cross-check of inf_P Var_phi L_P(phi) for the ellipse family
x^2/a^2 + y^2/b^2 = 1 (a != b).

Depends on S1 (exp:000008).  S1 minimised Var over |P| <= 0.9*min(a,b) with a
2000-direction analytic chord formula and found the smallest value at a/b = 1.01
(var_inf = 1.2253700694081736e-09, P* = (1.661e-08, -0.14037079420907037)).
This script re-minimises in the neighbourhood of that P*, with 8000 directions,
and reports BOTH the 2000-direction and the 8000-direction variance at the final
point.

Refutation criterion (conjecture 000000.testable.refutation_criterion, quoted):
  "if on any (a,b) one finds P with 2000-direction chord-length variance < 1e-18
   and 8000-direction cross-check also < 1e-18 (with |P| clearly nonzero, ruling
   out numerical noise), the conjecture is refuted".
We apply exactly that test.  Nothing here is a proof; a failure to refute is
supporting numeric evidence only.  No Rychlik convex-body negative solution is
used as a proof step anywhere in this script.

Numeric honesty note printed in the output: with chord lengths L ~ O(1) in
double precision, Var computed by the two-pass formula has a rounding floor of
order eps * mean(L^2) (eps = 2.22e-16), i.e. ~1e-15 for these ellipses.  A
measured variance below that floor cannot be distinguished from exact zero by
this code path, so the 1e-18 threshold sits BELOW this implementation's
detection floor.  We report the floor explicitly instead of pretending a value
below it would be meaningful.
"""
import json
import math
import time

import numpy as np

TWO_PI = 2.0 * math.pi
EPS = np.finfo(float).eps


def chord_lengths(a, b, P, n_dirs):
    """Analytic chord lengths through interior point P, uniform directions."""
    k = np.arange(n_dirs, dtype=np.float64)
    phi = TWO_PI * k / n_dirs
    c = np.cos(phi)
    s = np.sin(phi)
    px, py = float(P[0]), float(P[1])
    A = (c * c) / (a * a) + (s * s) / (b * b)
    B = px * c / (a * a) + py * s / (b * b)
    C = (px * px) / (a * a) + (py * py) / (b * b)
    disc = B * B - A * (C - 1.0)
    if np.any(disc <= 0.0):
        raise RuntimeError("point outside ellipse or degenerate direction")
    return 2.0 * np.sqrt(disc) / A


def stats(a, b, P, n_dirs):
    L = chord_lengths(a, b, P, n_dirs)
    m1 = float(np.mean(L))
    m2 = float(np.mean(L * L))
    var = m2 - m1 * m1
    floor = 8.0 * EPS * m2
    return {
        "var": var,
        "mean": m1,
        "Lmin": float(np.min(L)),
        "Lmax": float(np.max(L)),
        "rel_var": var / (m1 * m1),
        "rounding_floor_8eps_meanL2": floor,
    }


def inside_domain(P, R):
    return math.hypot(P[0], P[1]) <= R


def project(P, R):
    r = math.hypot(P[0], P[1])
    if r <= R:
        return [P[0], P[1]]
    return [P[0] * R / r, P[1] * R / r]


def compass(f, x0, R, step0, tol=1e-9, max_eval=20000):
    """Pattern search on 8 directions, step halved; P kept inside |P| <= R."""
    x = project(list(x0), R)
    fx = f(x)
    step = step0
    n_eval = 1
    dirs = [(math.cos(TWO_PI * i / 8.0), math.sin(TWO_PI * i / 8.0)) for i in range(8)]
    while step > tol and n_eval < max_eval:
        improved = False
        for dx, dy in dirs:
            y = project([x[0] + step * dx, x[1] + step * dy], R)
            fy = f(y)
            n_eval += 1
            if fy < fx:
                x, fx = y, fy
                improved = True
                break
        if not improved:
            step *= 0.5
    return x, fx, n_eval


def run_case(a, b, P0, R_dom, R_loc, tag, ndirs_list, out_cases, scaling, done, total):
    t0 = time.time()
    cases_out = {}
    for ndirs in ndirs_list:
        f = lambda P: stats(a, b, P, ndirs)["var"]
        x0 = project(list(P0), R_loc)
        P_fin, v2000_at, n_local = compass(f, x0, R_loc, step0=0.02, tol=1e-9)
        s2k = stats(a, b, P_fin, 2000)
        s8k = stats(a, b, P_fin, 8000)
        cases_out["minimize_with_%ddirs" % ndirs] = {
            "start_P": x0,
            "P_star": P_fin,
            "abs_P_star": math.hypot(P_fin[0], P_fin[1]),
            "local_evals": n_local,
            "var_at_minimiser_%ddirs" % ndirs: v2000_at,
            "var_2000dirs_at_P_star": s2k["var"],
            "var_8000dirs_at_P_star": s8k["var"],
            "var_8000dirs_minus_2000dirs": s8k["var"] - s2k["var"],
            "rel_var_2000dirs": s2k["rel_var"],
            "rel_var_8000dirs": s8k["rel_var"],
            "mean_chord_8000dirs": s8k["mean"],
            "Lmin_8000dirs": s8k["Lmin"],
            "Lmax_8000dirs": s8k["Lmax"],
            "rounding_floor_8eps_meanL2": s8k["rounding_floor_8eps_meanL2"],
            "below_rounding_floor": s8k["var"] < s8k["rounding_floor_8eps_meanL2"],
        }
    # take the best over the two minimisation runs for reporting
    best = min(cases_out.values(), key=lambda d: d["var_8000dirs_at_P_star"])
    cases_out["best"] = {
        "P_star": best["P_star"],
        "abs_P_star": best["abs_P_star"],
        "var_2000dirs": best["var_2000dirs_at_P_star"],
        "var_8000dirs": best["var_8000dirs_at_P_star"],
        "rounding_floor_8eps_meanL2": best["rounding_floor_8eps_meanL2"],
        "satisfies_refutation_criterion": (
            best["var_2000dirs_at_P_star"] < 1e-18
            and best["var_8000dirs_at_P_star"] < 1e-18
            and best["abs_P_star"] > 1e-3
        ),
    }
    secs = time.time() - t0
    scaling.append(
        {
            "n": tag,
            "a": a,
            "b": b,
            "a_over_b": a / b,
            "directions_minimised": ndirs_list,
            "seconds": round(secs, 4),
            "P_search_domain_radius": R_dom,
            "P_local_search_radius": R_loc,
        }
    )
    out_cases[tag] = cases_out
    print(
        "PROGRESS: "
        + json.dumps(
            {
                "task": "S2",
                "done": done,
                "total": total,
                "case": tag,
                "P_star": best["P_star"],
                "var_2000dirs": best["var_2000dirs_at_P_star"],
                "var_8000dirs": best["var_8000dirs_at_P_star"],
                "seconds": round(secs, 4),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return cases_out


def main():
    t_start = time.time()
    # (a, b, S1 P*, S1 var_inf, tag) -- primary = S1 argmin over the tested grid
    S1 = [
        (1.01, 1.0, [1.661009595586317e-08, -0.14037079420907037], 1.2253700694081736e-09, "1.01/1"),
        (1.1, 1.0, [-2.7613838554949325e-09, 0.41661646772447836], 1.0330498044123298e-05, "1.1/1"),
    ]
    out = {
        "task": "S2 pointwise inf cross-check (2000 vs 8000 directions)",
        "depends_on": "exp 000008 (S1 power-law calibration), conjecture 000000",
        "refutation_criterion_quoted": "2000-direction variance < 1e-18 AND 8000-direction variance < 1e-18 AND |P| clearly nonzero",
        "method": "analytic quadratic chord-length formula (exact per direction), compass/pattern search in the neighbourhood of the S1 minimiser, 8 directions, step halved from 0.02 to 1e-9, P kept inside |P| <= 0.9*min(a,b)",
    }
    cases_out = {}
    scaling = []
    total = len(S1)
    any_refutes = False
    for idx, (a, b, P0, v1, tag) in enumerate(S1, start=1):
        R_dom = 0.9 * min(a, b)
        R_loc = 0.1  # neighbourhood of the S1 minimiser
        c = run_case(a, b, P0, R_dom, R_loc, tag, [2000, 8000], cases_out, scaling, idx, total)
        cases_out[tag] = c
        if c["best"]["satisfies_refutation_criterion"]:
            any_refutes = True

    prim = cases_out["1.01/1"]["best"]
    out["cases"] = cases_out
    out["primary_case"] = "1.01/1"
    out["primary_P_star"] = prim["P_star"]
    out["primary_abs_P_star"] = prim["abs_P_star"]
    out["primary_var_2000dirs"] = prim["var_2000dirs"]
    out["primary_var_8000dirs"] = prim["var_8000dirs"]
    out["primary_rounding_floor"] = prim["rounding_floor_8eps_meanL2"]
    out["min_var_2000dirs_over_cases"] = min(c["best"]["var_2000dirs"] for c in cases_out.values())
    out["min_var_8000dirs_over_cases"] = min(c["best"]["var_8000dirs"] for c in cases_out.values())
    out["n_cases"] = len(cases_out)
    out["directions"] = [2000, 8000]
    out["search_domain"] = "local neighbourhood |P - P*_S1| bounded, P kept inside |P| <= 0.9*min(a,b)"
    out["detection_floor_note"] = (
        "two-pass variance in float64 has rounding floor ~8*eps*mean(L^2) ~ 1e-15 for these ellipses; "
        "the criterion threshold 1e-18 is BELOW this implementation's detection floor, so a value under the "
        "floor would not be interpretable as evidence of exact equality"
    )
    out["strategy"] = "analytic chord length + compass(8-dir) local refinement from the S1 minimiser; dual direction counts (2000/8000) at the same point"
    out["scaling"] = scaling
    out["runtime_sec"] = round(time.time() - t_start, 4)
    out["note"] = (
        "numeric evidence only, NOT a proof; no Rychlik convex-body negative solution is used as a proof step; "
        "a failure to refute on these two (a,b) does not establish the conjecture"
    )
    if any_refutes:
        bad = [t for t, c in cases_out.items() if c["best"]["satisfies_refutation_criterion"]][0]
        a, b = [(x[0], x[1]) for x in S1 if x[4] == bad][0]
        out["result"] = "refutes"
        out["counterexample"] = {
            "a": a,
            "b": b,
            "P_star": cases_out[bad]["best"]["P_star"],
            "abs_P_star": cases_out[bad]["best"]["abs_P_star"],
            "var_2000dirs": cases_out[bad]["best"]["var_2000dirs"],
            "var_8000dirs": cases_out[bad]["best"]["var_8000dirs"],
            "criterion": "both variances < 1e-18 and |P| clearly nonzero",
        }
    else:
        out["result"] = "supports"
    print("REPRO_RESULT: " + json.dumps(out, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
