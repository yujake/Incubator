#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3d: direction-count convergence diagnostic for Var_phi L_P (conjecture 000000).

Context: exp:000011 (S3) and exp:000012 (S3c) reported that the 2000-direction and
8000-direction two-pass variances agree to every printed digit at the S1/S3
minimisers (e.g. both 3.4658867032748945e-03 at a/b=1.5/1).  Two readings:
  (H1) both are spectrally accurate Riemann sums of the same smooth 2*pi-periodic
       analytic integrand (trapezoid rule converges geometrically there), so both
       already equal the CONTINUOUS variance in float64 -> genuine cross-check;
  (H2) the two calls silently used the same direction count (bug) -> the
       agreement is tautological and proves nothing.
This script decides between H1 and H2 with a deterministic reading: for several
points P it evaluates the 50-digit mpmath two-pass variance on the ladder
n = 125,250,500,1000,2000,4000,8000 and prints successive differences, their
shrink ratios and a 25-digit rendering of each value.  Geometric shrinking (with
n=125 clearly different from n=8000) => H1; identical 25-digit values across the
ladder => H2 (bug signal), and then the 2000==8000 agreement of exp:000011/000012
may NOT be used as two independent readings.

NUMERIC ONLY.  Lean is disabled in this session -> evidence_kind <= cross_check.
Nothing here is a proof of conjecture 000000.
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
MP_DPS = 50
if HAVE_MP:
    mp.mp.dps = MP_DPS

LADDER = [125, 250, 500, 1000, 2000, 4000, 8000]
TOL = 1e-7


def chord_np(a, b, P, n):
    k = np.arange(n, dtype=np.float64)
    phi = TWO_PI * k / n
    c = np.cos(phi)
    s = np.sin(phi)
    ia = 1.0 / (a * a)
    ib = 1.0 / (b * b)
    A = c * c * ia + s * s * ib
    B = float(P[0]) * c * ia + float(P[1]) * s * ib
    C = float(P[0]) * float(P[0]) * ia + float(P[1]) * float(P[1]) * ib - 1.0
    disc = B * B - A * C
    if np.any(disc <= 0.0):
        raise RuntimeError("degenerate direction / point outside ellipse")
    return 2.0 * np.sqrt(disc) / A


def var_np(a, b, P, n):
    L = chord_np(a, b, P, n)
    m = float(L.mean())
    d = L - m
    return float((d * d).mean())


def var_mp(a, b, P, n):
    aa = mp.mpf(a)
    bb = mp.mpf(b)
    px = mp.mpf(float(P[0]))
    py = mp.mpf(float(P[1]))
    ia = 1 / (aa * aa)
    ib = 1 / (bb * bb)
    C = px * px * ia + py * py * ib - 1
    L = []
    for k in range(n):
        phi = 2 * mp.pi * k / n
        c = mp.cos(phi)
        s = mp.sin(phi)
        A = c * c * ia + s * s * ib
        B = px * c * ia + py * s * ib
        disc = B * B - A * C
        if disc <= 0:
            raise RuntimeError("degenerate direction (mp)")
        L.append(2 * mp.sqrt(disc) / A)
    m = mp.fsum(L) / n
    return mp.fsum([(x - m) * (x - m) for x in L]) / n


def compass(f, x0, R, tol=TOL, max_eval=4000):
    x = [float(x0[0]), float(x0[1])]
    fx = float(f(x))
    n_eval = 1
    step = 0.1 * R
    dirs = [(math.cos(TWO_PI * k / 8.0), math.sin(TWO_PI * k / 8.0)) for k in range(8)]
    while step >= tol and n_eval < max_eval:
        improved = False
        for dx, dy in dirs:
            y = [x[0] + step * dx, x[1] + step * dy]
            if math.hypot(y[0], y[1]) > R:
                continue
            fy = float(f(y))
            n_eval += 1
            if fy < fx:
                x, fx = y, fy
                improved = True
                break
        if not improved:
            step *= 0.5
    return x, fx, n_eval, bool(step < tol)


def grid_points(R, n_side=11):
    pts = []
    for i in range(n_side):
        px = -R + 2.0 * R * i / (n_side - 1)
        for j in range(n_side):
            py = -R + 2.0 * R * j / (n_side - 1)
            if math.hypot(px, py) <= R + 1e-12:
                pts.append((px, py))
    return pts


CASES = [
    ("1.01/1", 1.01, 1.0, [1.661009595586317e-08, -0.14037079420907037], 1.2253700694081736e-09, "exp:000010 (S2 v2)"),
    ("1.1/1", 1.1, 1.0, [-2.7613838554949325e-09, 0.41661646772447836], 1.0330498044123298e-05, "exp:000010 (S2 v2)"),
    ("1.5/1", 1.5, 1.0, [1.0902846659559959e-09, -0.746758228829701], 3.4658867032748945e-03, "exp:000011 (S3 part b)"),
    ("3/1", 3.0, 1.0, [-3.4572536363275455e-10, 0.9517419536465388], 2.108643254213596e-01, "exp:000011 (S3 part b)"),
    ("5/1", 5.0, 1.0, None, 1.0868529973826258, "exp:000012 (S3c); coords re-derived here by search"),
]


def main():
    t_start = time.time()
    cases = {}
    scaling = []
    total = len(CASES)
    bug_signals = []
    for idx, (tag, a, b, P0, v_ref, src) in enumerate(CASES, start=1):
        tc0 = time.time()
        R = 0.99 * min(a, b)
        if P0 is None:
            f = lambda P, a=a, b=b: var_np(a, b, P, 2000)
            scored = sorted(((f(P), P) for P in grid_points(R, 11)), key=lambda t: t[0])
            best_v = scored[0][0]
            best_P = [float(scored[0][1][0]), float(scored[0][1][1])]
            for k in range(min(3, len(scored))):
                x, fx, ne, cvg = compass(f, scored[k][1], R)
                if fx < best_v:
                    best_v = fx
                    best_P = [float(x[0]), float(x[1])]
            P = best_P
            p_source = "re-derived in this script: 11x11 multistart grid + compass (8 dirs, step 0.1R -> 1e-7) on the 2000-direction variance inside |P| <= 0.99*min(a,b)"
        else:
            P = [float(P0[0]), float(P0[1])]
            p_source = "reference minimiser taken from " + src

        ladder = []
        for n in LADDER:
            rec = {"n": n, "var_np_two_pass": var_np(a, b, P, n)}
            if HAVE_MP:
                vm = var_mp(a, b, P, n)
                rec["var_mp"] = float(vm)
                rec["var_mp_25d"] = mp.nstr(vm, 25)
            ladder.append(rec)

        diffs = []
        for i in range(1, len(ladder)):
            if HAVE_MP:
                v_prev = ladder[i - 1]["var_mp"]
                v_cur = ladder[i]["var_mp"]
            else:
                v_prev = ladder[i - 1]["var_np_two_pass"]
                v_cur = ladder[i]["var_np_two_pass"]
            d = abs(v_cur - v_prev)
            diffs.append({"n_from": ladder[i - 1]["n"], "n_to": ladder[i]["n"],
                          "abs_diff": float(d),
                          "rel_diff": (float(d / abs(v_cur)) if v_cur != 0 else None)})
        shrink = []
        for i in range(1, len(diffs)):
            if diffs[i - 1]["abs_diff"] > 0:
                shrink.append(float(diffs[i]["abs_diff"] / diffs[i - 1]["abs_diff"]))

        v2000 = [r for r in ladder if r["n"] == 2000][0]
        v4000 = [r for r in ladder if r["n"] == 4000][0]
        v8000 = [r for r in ladder if r["n"] == 8000][0]
        if HAVE_MP:
            d_2k_8k = abs(v8000["var_mp"] - v2000["var_mp"])
            base8k = abs(v8000["var_mp"])
        else:
            d_2k_8k = abs(v8000["var_np_two_pass"] - v2000["var_np_two_pass"])
            base8k = abs(v8000["var_np_two_pass"])
        rec = {
            "case": tag,
            "a": a,
            "b": b,
            "a_over_b": a / b,
            "P": P,
            "abs_P": math.hypot(P[0], P[1]),
            "search_domain_radius_0.99min": R,
            "P_source": p_source,
            "var_reference_from_previous_experiment": v_ref,
            "var_np_2000dirs": v2000["var_np_two_pass"],
            "ladder": ladder,
            "successive_diffs": diffs,
            "diff_shrink_ratios": shrink,
            "monotone_shrinking_diffs": bool(all(diffs[i]["abs_diff"] <= diffs[i - 1]["abs_diff"] for i in range(1, len(diffs)))),
            "ladder_endpoints_differ_at_25digits": (bool(ladder[0]["var_mp_25d"] != ladder[-1]["var_mp_25d"]) if HAVE_MP else None),
            "float64_2000_equals_8000": bool(v2000["var_np_two_pass"] == v8000["var_np_two_pass"]),
            "float64_4000_equals_8000": bool(v4000["var_np_two_pass"] == v8000["var_np_two_pass"]),
            "mp_25digit_2000_equals_8000": (bool(v2000.get("var_mp_25d") == v8000.get("var_mp_25d")) if HAVE_MP else None),
            "abs_diff_2000_to_8000": float(d_2k_8k),
            "rel_diff_2000_to_8000": (float(d_2k_8k / base8k) if base8k else None),
            "seconds": round(time.time() - tc0, 3),
        }
        cases[tag] = rec
        scaling.append({"n": tag, "direction_counts": LADDER,
                        "total_direction_evaluations": int(sum(LADDER)),
                        "seconds": round(time.time() - tc0, 3)})
        if HAVE_MP and ladder[0]["var_mp_25d"] == ladder[-1]["var_mp_25d"]:
            bug_signals.append(tag)
        print("PROGRESS: " + json.dumps({"task": "S3d", "done": idx, "total": total, "case": tag,
                                        "P": [round(P[0], 12), round(P[1], 12)],
                                        "abs_P": math.hypot(P[0], P[1]),
                                        "var_mp_2000": v2000.get("var_mp"),
                                        "var_mp_8000": v8000.get("var_mp"),
                                        "rel_diff_2000_to_8000": rec["rel_diff_2000_to_8000"],
                                        "bug_signal": bool(HAVE_MP and tag in bug_signals),
                                        "seconds": rec["seconds"]}, sort_keys=True, default=float),
              flush=True)

    rels = [cases[t]["rel_diff_2000_to_8000"] for t in cases
            if cases[t]["rel_diff_2000_to_8000"] is not None]
    if not HAVE_MP:
        result = "inconclusive"
        note = ("mpmath unavailable: only a float64 ladder, which cannot resolve the 1e-18 scale; "
                "the question (is n=2000 already the continuous limit?) stays open")
    elif bug_signals:
        result = "inconclusive"
        note = ("BUG SIGNAL at %s: the 25-digit mpmath variance at n=125 equals that at n=8000, so the "
                "direction count may never reach the evaluator; the 2000==8000 agreement in "
                "exp:000011/exp:000012 must then NOT be read as two independent readings" % bug_signals)
    elif rels and max(rels) < 1e-12 and all(cases[t]["monotone_shrinking_diffs"] for t in cases):
        result = "supports"
        note = ("H1 confirmed on the tested points: the successive differences over n=125..8000 shrink "
                "monotonically and the n=2000 vs n=8000 50-digit values differ by at most %.3e relative, "
                "so at n>=2000 the discrete variance has reached the continuous variance in double "
                "precision; the identical 2000/8000 float64 values are spectral accuracy, not a repeated "
                "computation. NUMERIC ONLY, cross_check, not a proof." % max(rels))
    else:
        result = "inconclusive"
        note = ("ladder did not settle: max relative 2000-vs-8000 difference is %s and monotone shrinking "
                "holds for %d/%d cases; do not read the discrete variances as converged"
                % (max(rels) if rels else None,
                   sum(1 for t in cases if cases[t]["monotone_shrinking_diffs"]), len(cases)))

    out = {
        "result": result,
        "bound": {
            "direction_ladder": LADDER,
            "cases": [c[0] for c in CASES],
            "question": "at the reported minimisers, is the n=2000 discrete variance already the continuous variance in double precision (H1), or is the 2000==8000 agreement vacuous / a direction-count bug (H2)?",
            "max_rel_diff_2000_to_8000": (max(rels) if rels else None),
            "per_case_rel_diff_2000_to_8000": {t: cases[t]["rel_diff_2000_to_8000"] for t in cases},
            "bug_signals": bug_signals,
        },
        "strategy": "fixed point P per case; two-pass 50-digit mpmath variance over the direction ladder n = 125,250,500,1000,2000,4000,8000 (uniform angles, analytic quadratic chord-length formula, no ray shooting); successive differences and their shrink ratios are printed to distinguish spectral convergence from a direction-count bug",
        "scaling": scaling,
        "data": {"cases": cases},
        "note": note + "; numeric evidence only (Lean disabled this session), evidence_kind <= cross_check, no proof of conjecture 000000 is claimed",
        "runtime_sec": round(time.time() - t_start, 3),
    }
    print("REPRO_RESULT: " + json.dumps(out, sort_keys=True, default=float), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
