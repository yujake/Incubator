#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3e: does the direction count actually reach the evaluator?

exp:000013 (S3d) flagged for a/b in {1.01, 1.1, 1.5} that the 50-digit mpmath
variance at n=125 EQUALS the one at n=8000 and called that a BUG SIGNAL
(H2: the direction count may never reach the evaluator).  But L_P(phi) is
analytic and 2*pi-periodic, so the trapezoid rule converges geometrically and
"n=125 already exact" is the EXPECTED reading for near-circular ellipses.

This script settles it with a reading that cannot be faked:
  * the float64 evaluator ASSERTS L.size == n  (the array really has n entries);
  * the ladder is pushed down to n = 8, 16, 32, 64, where the trapezoid rule is
    definitely NOT converged: if n reaches the evaluator, the variance MUST move
    strongly between n=8 and n=8000;
  * n = 2000 vs 8000 must still agree to < 1e-12 relative.
Reading:  L.size==n  AND  var(8) far from var(8000)  AND  var(2000)==var(8000)
          => H1 (spectral accuracy);  var(8)==var(8000) => H2 (n ignored).

NUMERIC ONLY.  Lean is disabled this session -> evidence_kind <= cross_check;
nothing here is a proof of conjecture 000000.
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
if HAVE_MP:
    mp.mp.dps = 40

LADDER = [8, 16, 32, 64, 125, 250, 500, 2000, 8000]
MP_LADDER = [8, 16, 32, 2000, 8000]
TOL = 1e-7
COARSE_MOVE = 1e-3      # var(8) must differ from var(8000) by more than this
CONVERGED = 1e-12       # var(2000) vs var(8000)


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
    if int(L.size) != int(n):
        raise RuntimeError("direction count did not reach the evaluator: asked %d, got %d"
                           % (n, int(L.size)))
    m = float(L.mean())
    d = L - m
    return float((d * d).mean()), int(L.size), float(m)


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
    v = mp.fsum([(x - m) * (x - m) for x in L]) / n
    return float(v), len(L)


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


# (tag, a, b, P*, source of P*, reference var at that P)
CASES = [
    ("1.01/1", 1.01, 1.0, [1.661009595586317e-08, -0.14037079420907037], "exp:000010", 1.2253700694081736e-09),
    ("1.1/1", 1.1, 1.0, [-2.7613838554949325e-09, 0.41661646772447836], "exp:000010", 1.0330498044123298e-05),
    ("1.5/1", 1.5, 1.0, [1.0902846659559959e-09, -0.746758228829701], "exp:000011", 3.4658867032748945e-03),
    ("2/1", 2.0, 1.0, [-1.145609086761282e-09, -0.8706804795961952], "exp:000011", 3.088312467002024e-02),
    ("3/1", 3.0, 1.0, [-3.4572536363275455e-10, 0.9517419536465388], "exp:000011", 2.108643254213596e-01),
    ("5/1", 5.0, 1.0, None, "re-derived here (exp:000012 reported |P*|=0.9891951945, coords not printed)", 1.0868529973826258),
]


def main():
    t_start = time.time()
    cases = {}
    scaling = []
    bad = []
    total = len(CASES)
    for idx, (tag, a, b, P0, src, v_ref) in enumerate(CASES, start=1):
        tc0 = time.time()
        R = 0.99 * min(a, b)
        if P0 is None:
            f = lambda P, a=a, b=b: var_np(a, b, P, 2000)[0]
            scored = sorted(((f(P), P) for P in grid_points(R, 11)), key=lambda t: t[0])
            best_v = scored[0][0]
            best_P = [float(scored[0][1][0]), float(scored[0][1][1])]
            for k in range(min(3, len(scored))):
                x, fx, ne, cvg = compass(f, scored[k][1], R)
                if fx < best_v:
                    best_v = fx
                    best_P = [float(x[0]), float(x[1])]
            P = best_P
            p_source = "re-derived: 11x11 multistart grid + compass (8 dirs, 0.1R -> 1e-7) on the 2000-dir variance, |P|<=0.99*min(a,b)"
            v_ref_here = best_v
        else:
            P = [float(P0[0]), float(P0[1])]
            p_source = "reference minimiser from " + src
            v_ref_here = v_ref

        ladder = []
        sizes = []
        for n in LADDER:
            v, sz, meanL = var_np(a, b, P, n)
            ladder.append({"n": n, "var_np_two_pass": v, "array_len": sz, "mean_chord": meanL})
            sizes.append(sz)
        mp_ladder = []
        if HAVE_MP:
            for n in MP_LADDER:
                vm, szm = var_mp(a, b, P, n)
                mp_ladder.append({"n": n, "var_mp": vm, "array_len_mp": szm})

        v_by_n = {rec["n"]: rec["var_np_two_pass"] for rec in ladder}
        v8 = v_by_n[8000]
        v2k = v_by_n[2000]

        def rel(x, y):
            d = abs(y)
            return abs(x - y) / d if d > 0 else (0.0 if x == y else float("inf"))

        rel_8_to_8000 = rel(v_by_n[8], v8)
        rel_16_to_8000 = rel(v_by_n[16], v8)
        rel_32_to_8000 = rel(v_by_n[32], v8)
        rel_64_to_8000 = rel(v_by_n[64], v8)
        rel_125_to_8000 = rel(v_by_n[125], v8)
        rel_2000_to_8000 = rel(v2k, v8)
        distinct = len({round(x, 30) for x in v_by_n.values()})
        sizes_ok = all(s == n for s, n in zip(sizes, LADDER))
        coarse_moves = rel_8_to_8000 > COARSE_MOVE
        converged_at_2000 = rel_2000_to_8000 < CONVERGED
        hyp = "H1_spectral" if (sizes_ok and coarse_moves and converged_at_2000) else (
            "H2_n_ignored" if not coarse_moves else "unsettled")
        if hyp != "H1_spectral":
            bad.append(tag)
        secs = time.time() - tc0
        cases[tag] = {
            "a": a, "b": b, "a_over_b": a / b,
            "P": P, "abs_P": math.hypot(P[0], P[1]),
            "P_source": p_source,
            "reference_var_at_P": v_ref_here,
            "ladder_np": ladder,
            "ladder_mp": mp_ladder,
            "rel_diff_vs_n8000": {"n8": rel_8_to_8000, "n16": rel_16_to_8000,
                                  "n32": rel_32_to_8000, "n64": rel_64_to_8000,
                                  "n125": rel_125_to_8000, "n2000": rel_2000_to_8000},
            "distinct_values_on_ladder": distinct,
            "array_len_equals_n_all": bool(sizes_ok),
            "coarse_n8_moves_vs_n8000": bool(coarse_moves),
            "converged_at_n2000": bool(converged_at_2000),
            "variant": hyp,
            "seconds": round(secs, 3),
        }
        scaling.append({"n": tag, "directions": LADDER, "mp_directions": MP_LADDER,
                        "seconds": round(secs, 3), "mpmath": HAVE_MP})
        print("PROGRESS: " + json.dumps({"task": "S3e", "done": idx, "total": total,
                                        "case": tag, "var_n8": v_by_n[8], "var_n2000": v2k,
                                        "var_n8000": v8, "rel_n8_vs_n8000": rel_8_to_8000,
                                        "rel_n2000_vs_n8000": rel_2000_to_8000,
                                        "array_len_ok": bool(sizes_ok), "variant": hyp,
                                        "seconds": round(secs, 3)}, sort_keys=True), flush=True)

    if bad:
        result = "inconclusive"
        note = ("direction-count question NOT settled for %s (either the array length did not match n, "
                "or n=8 already equals n=8000); the 2000==8000 agreement of exp:000011/exp:000012 "
                "cannot be used as an independent direction-count cross-check until this is resolved" % bad)
    else:
        result = "supports"
        note = ("H1 (spectral accuracy) on all %d points: the chord-length array length equals the requested n "
                "at every rung, the n=8 variance differs from the n=8000 one by a large relative amount "
                "(so the direction count does reach the evaluator), and n=2000 vs n=8000 agree to <1e-12 "
                "relative.  Consequences: (i) the BUG SIGNAL reported by exp:000013 for a/b=1.01,1.1,1.5 is a "
                "false positive of that script's criterion (trapezoid rule on an analytic 2*pi-periodic "
                "integrand is already exact at n=125 on near-circular ellipses); (ii) the 2000==8000 equality "
                "in exp:000011/exp:000012 is convergence, NOT a repeated computation -- but it is a "
                "convergence check plus a float64-vs-50-digit-mpmath arithmetic check, NOT two independent "
                "direction-count samples.  Numeric evidence only (Lean disabled this session), "
                "evidence_kind <= cross_check, no proof of conjecture 000000 is claimed." % len(cases))

    out = {
        "result": result,
        "bound": {
            "direction_ladder": LADDER,
            "mp_direction_ladder": MP_LADDER,
            "reference_points": {t: {"P": cases[t]["P"], "abs_P": cases[t]["abs_P"],
                                     "source": cases[t]["P_source"]} for t in cases},
            "coarse_move_threshold_relative": COARSE_MOVE,
            "converged_threshold_relative": CONVERGED,
            "per_case": {t: {"variant": cases[t]["variant"],
                             "rel_diff_vs_n8000": cases[t]["rel_diff_vs_n8000"],
                             "distinct_values_on_ladder": cases[t]["distinct_values_on_ladder"],
                             "array_len_equals_n_all": cases[t]["array_len_equals_n_all"]} for t in cases},
            "cases_not_settled": bad,
        },
        "strategy": "fixed reference point P per case; chord-length array length asserted equal to n inside the "
                    "evaluator; float64 two-pass variance on the direction ladder n=8,16,32,64,125,250,500,2000,8000 "
                    "plus 40-digit mpmath on n=8,16,32,2000,8000; analytic quadratic chord-length formula, no ray "
                    "shooting.  Coarse rungs (n<=64) are the decisive reading: they cannot be spectrally exact, so "
                    "they separate 'direction count reaches the evaluator' from 'direction count is ignored'.",
        "scaling": scaling,
        "data": {"cases": cases},
        "note": note,
        "runtime_sec": round(time.time() - t_start, 3),
    }
    print("REPRO_RESULT: " + json.dumps(out, sort_keys=True, default=float), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
