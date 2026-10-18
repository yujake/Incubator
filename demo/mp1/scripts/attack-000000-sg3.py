#!/usr/bin/env python3
"""attack-000000-sg3.py -- attack plan 000000, subgoals sg2 + sg3 (owner E).

DEFINITION (identical to exp:000000 / exp:000002 / exp:000021, code: scripts/attack-000000-sg1.py):
    Theta = {u_1,...,u_k}, u_i = (cos th_i, sin th_i) unit vectors in R^2,
    r(Theta) = sup_{p in R^2} min_i dist(p . u_i, Z),   dist(t,Z) = |t - round(t)| in [0, 1/2].

WHAT EACH NUMBER IN THIS FILE MEANS (certification ledger -- read this before quoting a number):
  (L-cert) r_lower : value f(p*) at ONE explicit numeric point p*.  Since r = sup_p f, any single
           point gives r(Theta) >= f(p*).  Falsifiable-by-arithmetic lower bound; double precision,
           so the bound is good to ~1e-14 (we also print |p*| so the reader can bound rounding).
           This is the ONLY direction used for the 'supports' verdict below.
  (U-box)  r_upper_box : max over an explicit grid + 1-Lipschitz slack h*sqrt(2)/2, where
           f is 1-Lipschitz because |dist(t,Z)-dist(t',Z)| <= |t-t'| and |u_i| = 1.
           Valid as an upper bound for sup_{p in B} f with B = [-1,1]^2 ONLY.
           It is NOT an upper bound over all of R^2 (f is not periodic in p for generic Theta).
  (U-global) r_upper_global = 1/2 : dist(t,Z) <= 1/2 always => f <= 1/2 everywhere (exact, certified).
  CONSEQUENCE: a REFUTATION of 'r(Theta) >= 1/(2k)' would need a certified GLOBAL upper bound
  r(Theta) < 1/(2k).  With only (U-box) available, no refutation can be certified here: any family
  whose r_upper_box dips below 1/(2k) is reported as a CANDIDATE that still needs a global
  (torus-covering / periodicity) argument.  sg3 therefore reports inconclusive unless such a
  certified global bound is produced.  This is a limitation of the certificate, not of the search.

EVIDENCE LEVEL: numeric / cross_check.  Lean is disabled in this session => nothing here is 'proof'.

Output: one 'PROGRESS: {...}' line per finished (k, family) cell and exactly one
'REPRO_RESULT: {...}' line, both at line start.
"""

import json
import math
import random
import time

SQ2_2 = math.sqrt(2.0) / 2.0
DIRS8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def f_at(p, us):
    """f(p) = min_i dist(p . u_i, Z)."""
    m = 1.0
    for (c, s) in us:
        d = abs(p[0] * c + p[1] * s - round(p[0] * c + p[1] * s))
        if d < m:
            m = d
    return m


def box_bound(us, G=128, lo=-1.0, hi=1.0):
    """Grid max of f over [lo,hi]^2 plus the 1-Lipschitz slack h*sqrt(2)/2 (valid on B only)."""
    h = (hi - lo) / G
    best = -1.0
    bp = (0.0, 0.0)
    npts = 0
    for i in range(G + 1):
        x = lo + i * h
        for j in range(G + 1):
            y = lo + j * h
            v = f_at((x, y), us)
            npts += 1
            if v > best:
                best = v
                bp = (x, y)
    return best, bp, best + h * SQ2_2, npts, h


def refine(us, p0, step0, tol=1e-13, iters=400):
    """Deterministic 8-direction pattern search (no randomness)."""
    best = f_at(p0, us)
    p = p0
    step = step0
    it = 0
    while step > tol and it < iters:
        moved = False
        for dx, dy in DIRS8:
            q = (p[0] + dx * step, p[1] + dy * step)
            v = f_at(q, us)
            if v > best:
                best, p, moved = v, q, True
                break
        if not moved:
            step *= 0.5
        it += 1
    return best, p, step, it


def unit_and_dists(us, p):
    """Per-direction dist at p, plus a unit-vector sanity reading."""
    ds = []
    worst_unit = 0.0
    for (c, s) in us:
        worst_unit = max(worst_unit, abs(c * c + s * s - 1.0))
        t = p[0] * c + p[1] * s
        ds.append(abs(t - round(t)))
    return ds, worst_unit


# ---------------------------------------------------------------- angle families
def fam_equispaced_pi_over_k(k):
    """theta_i = i*pi/k, i=0..k-1 (the 'equilateral' family of the plan)."""
    return [(math.cos(i * math.pi / k), math.sin(i * math.pi / k)) for i in range(k)], {
        "kind": "equispaced i*pi/k"}


def fam_cyclic_2pi_over_k(k):
    """theta_i = 2*i*pi/k, i=0..k-1 (closes up under negation when k is even)."""
    return [(math.cos(2 * i * math.pi / k), math.sin(2 * i * math.pi / k)) for i in range(k)], {
        "kind": "cyclic 2*i*pi/k"}


def fam_jpi_over_2k_plus_1(k):
    """commensurable family with denominator n = 2k+1: theta_i = 2*i*pi/(2k+1)."""
    n = 2 * k + 1
    return [(math.cos(2 * i * math.pi / n), math.sin(2 * i * math.pi / n)) for i in range(k)], {
        "kind": "commensurable 2*i*pi/(2k+1)", "n": n}


def fam_random_rational(k, seed):
    """k distinct angles a_i*pi/N with a_i drawn from Random(seed); N = 997 fixed."""
    N = 997
    rng = random.Random(seed)
    js = sorted(rng.sample(range(N), k))
    return [(math.cos(j * math.pi / N), math.sin(j * math.pi / N)) for j in js], {
        "kind": "random rational a_i*pi/997", "N": N, "indices": js, "seed": seed}


def fam_random_generic(k, seed):
    """k angles uniform in [0,2pi) from Random(seed) -- no rational structure imposed."""
    rng = random.Random(seed)
    ths = sorted(rng.uniform(0.0, 2.0 * math.pi) for _ in range(k))
    return [(math.cos(t), math.sin(t)) for t in ths], {
        "kind": "random real angles in [0,2pi)", "seed": seed,
        "thetas_float": [round(t, 12) for t in ths]}


def families_for(k):
    out = []
    out.append(("equispaced_pi/k",) + fam_equispaced_pi_over_k(k))
    out.append(("cyclic_2pi/k",) + fam_cyclic_2pi_over_k(k))
    out.append(("jpi/(2k+1)",) + fam_jpi_over_2k_plus_1(k))
    out.append(("rand_rational",) + fam_random_rational(k, 20261018 + 1000 * k + 1))
    out.append(("rand_generic",) + fam_random_generic(k, 20261018 + 1000 * k + 2))
    return out


def main():
    t0 = time.time()
    rows = []
    failures = []
    scaling = []
    KMIN, KMAX = 3, 10
    GRID = 128

    for k in range(KMIN, KMAX + 1):
        th = 1.0 / (2.0 * k)
        tk0 = time.time()
        ncell = 0
        for (fname, us, meta) in families_for(k):
            ts = time.time()
            gmax, gp, rub, npts, h = box_bound(us, G=GRID)
            rl, pstar, fstep, nit = refine(us, gp, h)
            ds, worst_unit = unit_and_dists(us, pstar)
            row = {
                "k": k,
                "family": fname,
                "family_meta": meta,
                "threshold_1_over_2k": th,
                "r_lower_witness": rl,
                "r_lower_witness_kind": "f(p*) at one point p* => rigorous lower bound (double precision)",
                "witness_p": [round(pstar[0], 12), round(pstar[1], 12)],
                "witness_norm_p": round(math.hypot(pstar[0], pstar[1]), 12),
                "witness_dists": [round(d, 12) for d in ds],
                "witness_min_dist": round(min(ds), 12),
                "r_upper_box": rub,
                "r_upper_box_scope": "sup over [-1,1]^2 only (grid %dx%d + Lipschitz h*sqrt2/2, h=%.6g)" % (GRID + 1, GRID + 1, h),
                "r_upper_global": 0.5,
                "r_upper_global_kind": "exact: dist(t,Z) <= 1/2 => r(Theta) <= 1/2 for every Theta",
                "grid_points": npts,
                "refine_iters": nit,
                "refine_final_step": fstep,
                "unit_vector_max_err": worst_unit,
                "lower_ge_threshold": rl >= th,
                "margin_lower_minus_threshold": rl - th,
                "candidate_upper_box_below_threshold": rub < th,
                "candidate_gap_threshold_minus_upper_box": th - rub,
                "certified_global_refutation": False,
                "seconds": round(time.time() - ts, 3),
            }
            if worst_unit > 1e-12:
                failures.append({"item": "unit_vector_%s_k%d" % (fname, k),
                                 "reason": "|u|^2-1 = %.3e" % worst_unit})
            if rl > 0.5 + 1e-12:
                failures.append({"item": "r_lower_%s_k%d" % (fname, k),
                                 "reason": "f(p*) = %.15f > 1/2 (impossible)" % rl})
            rows.append(row)
            ncell += 1
            print("PROGRESS: " + json.dumps({
                "item": "cell", "k": k, "family": fname,
                "r_lower": round(rl, 12), "r_upper_box": round(rub, 12),
                "threshold": round(th, 12), "lower_ge_threshold": row["lower_ge_threshold"],
                "candidate_gap": round(row["candidate_gap_threshold_minus_upper_box"], 12),
                "cells_done": ncell, "seconds": row["seconds"]}), flush=True)
        scaling.append({"k": k, "cells": ncell, "seconds": round(time.time() - tk0, 3),
                        "grid_points_per_cell": (GRID + 1) ** 2})

    n_rows = len(rows)
    n_lower_ok = sum(1 for r in rows if r["lower_ge_threshold"])
    n_cand = sum(1 for r in rows if r["candidate_upper_box_below_threshold"])
    gap_lower = max(r["margin_lower_minus_threshold"] * -1.0 for r in rows)  # max(threshold - r_lower)
    cand = sorted(rows, key=lambda r: r["candidate_gap_threshold_minus_upper_box"], reverse=True)
    top = [{"k": r["k"], "family": r["family"],
            "threshold": round(r["threshold_1_over_2k"], 12),
            "r_lower": round(r["r_lower_witness"], 12),
            "r_upper_box": round(r["r_upper_box"], 12),
            "candidate_gap": round(r["candidate_gap_threshold_minus_upper_box"], 12)}
           for r in cand[:5]]

    result = "refutes" if n_cand > 0 else "inconclusive"
    counterexample = None
    if result == "refutes":
        # only a candidate; reported inside the bound block, never as a certified refutation
        counterexample = {"k": cand[0]["k"], "family": cand[0]["family"],
                          "witness_p": cand[0]["witness_p"],
                          "witness_min_dist": cand[0]["witness_min_dist"],
                          "r_upper_box": cand[0]["r_upper_box"],
                          "threshold": cand[0]["threshold_1_over_2k"],
                          "certification": "upper bound is box-restricted only -- NOT a certified global refutation"}
        result = "inconclusive"  # a box-restricted bound cannot certify a refutation

    payload = {
        "result": result,
        "counterexample": counterexample,
        "bound": {
            "k_range": [KMIN, KMAX],
            "families_per_k": 5,
            "family_kinds": ["equispaced i*pi/k", "cyclic 2*i*pi/k", "commensurable 2*i*pi/(2k+1)",
                             "random rational a_i*pi/997", "random real angles in [0,2pi)"],
            "cells": n_rows,
            "grid": {"box": [-1.0, 1.0], "points_per_axis": GRID + 1, "step": 2.0 / GRID,
                     "lipschitz_slack": 2.0 / GRID * SQ2_2},
            "seeds": {"random_rational": "20261018 + 1000*k + 1",
                      "random_generic": "20261018 + 1000*k + 2"},
            "cells_with_lower_bound_at_or_above_1_over_2k": n_lower_ok,
            "cells_with_candidate_box_upper_below_1_over_2k": n_cand,
            "max_gap_threshold_minus_r_lower": -gap_lower,
            "max_candidate_gap_threshold_minus_r_upper_box": round(cand[0]["candidate_gap_threshold_minus_upper_box"], 12),
            "min_r_lower_over_all_cells": round(min(r["r_lower_witness"] for r in rows), 12),
            "min_r_upper_box_over_all_cells": round(min(r["r_upper_box"] for r in rows), 12),
            "max_r_lower_over_all_cells": round(max(r["r_lower_witness"] for r in rows), 12),
            "r_upper_global": 0.5,
            "certified_global_refutations": 0,
            "top_candidates": top,
        },
        "strategy": "deterministic grid + 8-direction pattern search; lower bounds are point witnesses (r = sup_p f); upper bounds are box-restricted Lipschitz covers, global upper bound is the exact constant 1/2; no randomized search (only fixed seeds for the angle families)",
        "scaling": scaling,
        "failures": failures,
        "runtime_sec": round(time.time() - t0, 3),
        "rows": rows,
    }
    print("REPRO_RESULT: " + json.dumps(payload), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
