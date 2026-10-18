#!/usr/bin/env python3
"""attack-000000-sg3b.py -- attack plan 000000, subgoal sg3 (owner E): exhaustive commensurable sweep.

DEFINITION (identical to scripts/attack-000000-sg1.py and scripts/attack-000000-sg3.py):
    Theta = {u_1,...,u_k}, u_i = (cos th_i, sin th_i),
    r(Theta) = sup_{p in R^2} min_i dist(p . u_i, Z),   dist(t,Z) = |t - round(t)| in [0,1/2].

SEARCHED RANGE (exhaustive, no random seed):
    For N in {12, 24} and every listed k, ALL k-subsets of the N-th roots of unity
    { (cos(2*pi*j/N), sin(2*pi*j/N)) : j = 0..N-1 } are enumerated.  Nothing is sampled.

CERTIFICATION LEDGER (read this before quoting any number):
  (L-cert) gmax(Theta) = f(p*) at one explicit grid point p* in B = [-1,1]^2.
           Any single point gives r(Theta) >= f(p*), so gmax >= 1/(2k) CERTIFIES
           'r(Theta) >= 1/(2k)' FOR THAT THETA (double precision, rounding ~1e-15).
  (U-box)  bup(Theta) = gmax + h*sqrt(2)/2 with h = 2/G the grid step.  f is 1-Lipschitz
           (|dist(t,Z)-dist(t',Z)| <= |t-t'| and |u_i| = 1), so bup bounds sup over the BOX B only.
           It is not a bound on r(Theta) over R^2.  Promotion would need a period vector
           v != 0 with v.u_i in Z for all i, checked in EXACT arithmetic; for k >= 3 there is
           no rank-2 period lattice and a rank-1 period (when it exists) can only be used with
           exact arithmetic, which this numeric script deliberately does not do.  So bup < 1/(2k)
           is a CANDIDATE for a refutation, never a refutation.
  A REFUTATION would need a certified GLOBAL upper bound r(Theta) < 1/(2k).  This script cannot
  produce one; candidate cells are reported as candidates and the verdict is 'inconclusive'
  unless zero candidates were seen AND every enumerated Theta carries a witness >= 1/(2k).

EVIDENCE LEVEL: numeric / cross_check.  Lean is disabled in this session: nothing here is 'proof'.

Output: one 'PROGRESS: {...}' line per finished (N,k) block, exactly one 'REPRO_RESULT: {...}'.
"""

import itertools
import json
import math
import time

import numpy as np

SQ2_2 = math.sqrt(2.0) / 2.0
DIRS8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def f_at(us, p):
    """f(p) = min_i dist(p . u_i, Z), float."""
    m = 1.0
    for (c, s) in us:
        t = p[0] * c + p[1] * s
        d = abs(t - round(t))
        if d < m:
            m = d
    return m


def refine(us, p0, step0, tol=1e-13, maxit=300):
    """Deterministic 8-direction pattern search from p0. Returns (value, point, iters)."""
    best = f_at(us, p0)
    p = [p0[0], p0[1]]
    step = step0
    it = 0
    while step > tol and it < maxit:
        moved = False
        for dx, dy in DIRS8:
            q = (p[0] + dx * step, p[1] + dy * step)
            v = f_at(us, q)
            if v > best:
                best, p, moved = v, [q[0], q[1]], True
                break
        if not moved:
            step *= 0.5
        it += 1
    return best, p, it


def main():
    t0 = time.time()
    N_K = [(12, [3, 4, 5, 6, 7, 8]), (24, [3, 4, 5])]
    G = 24
    h = 2.0 / G
    pts = np.linspace(-1.0, 1.0, G + 1)
    PX, PY = np.meshgrid(pts, pts)
    gx = PX.ravel().copy()
    gy = PY.ravel().copy()
    npts = int(gx.size)
    CH = 512
    blocks = []
    failures = []
    total_candidates = 0
    hardest = None
    for N, klist in N_K:
        CS = np.array([math.cos(2.0 * math.pi * j / N) for j in range(N)])
        SN = np.array([math.sin(2.0 * math.pi * j / N) for j in range(N)])
        for k in klist:
            ts = time.time()
            th = 1.0 / (2.0 * k)
            n_sets = 0
            n_wit = 0
            n_cand = 0
            min_gmax = 2.0
            min_set = None
            min_p = None
            combos = itertools.combinations(range(N), k)
            while True:
                chunk = list(itertools.islice(combos, CH))
                if not chunk:
                    break
                idx = np.array(chunk, dtype=np.int64)
                C = CS[idx]
                S = SN[idx]
                t = C[:, :, None] * gx[None, None, :] + S[:, :, None] * gy[None, None, :]
                d = np.abs(t - np.round(t))
                mn = d.min(axis=1)
                mx = mn.max(axis=1)
                ar = mn.argmax(axis=1)
                n_sets += int(idx.shape[0])
                n_wit += int(np.count_nonzero(mx >= th))
                n_cand += int(np.count_nonzero(mx + h * SQ2_2 < th))
                j = int(np.argmin(mx))
                v = float(mx[j])
                if v < min_gmax:
                    min_gmax = v
                    min_set = tuple(int(x) for x in idx[j])
                    p_i = int(ar[j])
                    min_p = (float(gx[p_i]), float(gy[p_i]))
            us_min = [(float(CS[j]), float(SN[j])) for j in min_set]
            r_ref, p_ref, it_ref = refine(us_min, min_p, h)
            bup = min_gmax + h * SQ2_2
            row = {
                "N": N,
                "k": k,
                "n_sets": n_sets,
                "threshold_1_over_2k": th,
                "hardest_set_indices": list(min_set),
                "hardest_set_angles_over_N": ["%d/%d" % (j, N) for j in min_set],
                "min_grid_max": round(min_gmax, 12),
                "box_upper_at_hardest": round(bup, 12),
                "candidate_gap_threshold_minus_box_upper": round(th - bup, 12),
                "n_witness_ge_threshold": n_wit,
                "n_box_candidates": n_cand,
                "refined_r_lower": round(r_ref, 12),
                "refined_point": [round(p_ref[0], 12), round(p_ref[1], 12)],
                "refine_iters": it_ref,
                "seconds": round(time.time() - ts, 3),
            }
            blocks.append(row)
            total_candidates += n_cand
            if hardest is None or r_ref < hardest["refined_r_lower"]:
                hardest = {
                    "N": N,
                    "k": k,
                    "refined_r_lower": row["refined_r_lower"],
                    "threshold_1_over_2k": th,
                    "set_angles_over_N": row["hardest_set_angles_over_N"],
                    "witness_point": row["refined_point"],
                    "margin_above_threshold": round(r_ref - th, 12),
                }
            print("PROGRESS: " + json.dumps({
                "N": N, "k": k, "n_sets": n_sets,
                "hardest_set_indices": row["hardest_set_indices"],
                "min_grid_max": row["min_grid_max"],
                "box_upper_at_hardest": row["box_upper_at_hardest"],
                "threshold_1_over_2k": round(th, 12),
                "candidate_gap": row["candidate_gap_threshold_minus_box_upper"],
                "n_witness_ge_threshold": n_wit,
                "n_box_candidates": n_cand,
                "refined_r_lower": row["refined_r_lower"],
                "seconds": row["seconds"],
            }), flush=True)
            if bup < th:
                failures.append({"item": "box_candidate_N%d_k%d" % (N, k),
                                 "reason": "box upper bound below 1/(2k) -- candidate only, no global certification"})
            if n_wit < n_sets:
                failures.append({"item": "witness_shortfall_N%d_k%d" % (N, k),
                                 "reason": "%d of %d sets have no grid witness >= 1/(2k)" % (n_sets - n_wit, n_sets)})

    total_sets = sum(b["n_sets"] for b in blocks)
    all_wit = all(b["n_witness_ge_threshold"] == b["n_sets"] for b in blocks)
    verdict = "supports" if (total_candidates == 0 and all_wit) else "inconclusive"
    payload = {
        "result": verdict,
        "cells": len(blocks),
        "bound": {
            "N": [12, 24],
            "k_range": [3, 8],
            "sets_enumerated": total_sets,
            "grid_points_per_box": npts,
            "grid_step": h,
            "box": [-1.0, 1.0],
            "lipschitz_slack": round(h * SQ2_2, 12),
            "hardest_cell": hardest,
            "box_candidates_total": total_candidates,
            "every_set_has_witness_ge_threshold": bool(all_wit),
            "global_upper_bound_available": False,
            "global_upper_bound_note": "only the exact universal bound f <= 1/2; the box bound is local because a rank-1 period cannot be used without exact arithmetic",
        },
        "strategy": "exhaustive enumeration of ALL k-subsets of the N-th roots of unity (N=12: k=3..8; N=24: k=3,4,5); numpy grid max over [-1,1]^2 as the point-witness lower bound (L-cert); 1-Lipschitz box slack as a local upper bound (U-box); deterministic 8-direction pattern refinement of the hardest cell; no random sampling, no seed",
        "scaling": [{"N": b["N"], "k": b["k"], "sets": b["n_sets"], "seconds": b["seconds"]} for b in blocks],
        "rows": blocks,
        "failures": failures,
        "criterion": "supports iff (a) every enumerated Theta has an explicit point p with f(p) >= 1/(2k), and (b) no Theta has a box upper bound below 1/(2k); a refutation would additionally need a GLOBAL certified upper bound, which this script cannot produce",
        "runtime_sec": round(time.time() - t0, 3),
    }
    print("REPRO_RESULT: " + json.dumps(payload), flush=True)


if __name__ == "__main__":
    main()
