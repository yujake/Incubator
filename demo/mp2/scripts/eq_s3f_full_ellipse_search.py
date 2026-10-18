#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3f: is the disk-restricted minimum from exp:000012 the infimum over the WHOLE ellipse?

exp:000011 / exp:000012 minimised Var_phi L_P over the disk |P| <= 0.99*min(a,b) and
reported interior minima at |P*| = 0.9238287043 (a/b=2.5), 0.9517419086 (a/b=3),
0.9891951945 (a/b=5), with the value flat between the 0.99 and 0.999 disks.

But for a/b > 1 that disk is a PROPER subset of the ellipse: it excludes the whole outer
part of the major axis (a/b=5, b=1 -> disk radius 0.99 while the ellipse reaches x=+-5).
So "the value stopped falling when the disk grew 0.9 -> 0.999" does NOT by itself say the
reported numbers are the infimum over the ellipse.  This script closes exactly that hole.

Reading (deterministic, no model judgement):
  * scaled coordinates P = (a*s*cos(theta), b*s*sin(theta)), s in (0, SMAX=0.98]:
    40 theta x 15 s (+ the centre) = 601 multistarts, 2000-direction two-pass variance;
  * compass/pattern search (8 directions, step halved from 0.1*min(a,b) to 1e-7) of the
    2000-direction variance from the 3 best grid points, clipped to s <= SMAX;
  * the winner is refined again on the 8000-direction variance (step 0.05 -> 1e-9) and
    then evaluated at 2000 and 8000 directions in float64 two-pass AND in 50-digit
    mpmath (analytic quadratic chord-length formula throughout, no ray shooting).

Claim tested (NUMERIC ONLY -- Lean is disabled this session, so evidence_kind can be at
most cross_check, and nothing here is a proof of conjecture 000000):
  a whole-ellipse multistart search finds NO point whose Var_phi L_P is below the
  exp:000012 disk value by more than 1e-6 relative, for a/b in {2.5, 3, 5}.
If it DOES find one, this script returns result=refutes with that point as the
counterexample -- a refutation of THIS calibration claim (the disk number was not the
infimum), explicitly NOT a refutation of conjecture 000000.
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

SMAX = 0.98
N_DIRS = 2000
N_WIDE = 8000
TOL = 1e-7
REL_TOL = 1e-6
RATIOS = [2.5, 3.0, 5.0]

# disk-restricted minima reported by exp:000012 (S3c: 8000 dirs + 50-digit mpmath)
DISK_REF = {
    2.5: {"var": 0.09829965992649131, "abs_P": 0.9238287043052498},
    3.0: {"var": 0.21086432542140776, "abs_P": 0.9517419085948138},
    5.0: {"var": 1.086852997382626, "abs_P": 0.9891951944994553},
}


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
    return float(mp.fsum([(v - m) * (v - m) for v in L]) / n)


def clip_full(x, a, b, smax):
    s = math.hypot(x[0] / a, x[1] / b)
    if s > smax:
        k = smax / s
        return [float(x[0] * k), float(x[1] * k)]
    return [float(x[0]), float(x[1])]


def compass_full(f, x0, a, b, smax, tol=TOL, max_eval=4000):
    x = clip_full([float(x0[0]), float(x0[1])], a, b, smax)
    fx = float(f(x))
    n_eval = 1
    step = 0.1 * min(a, b)
    dirs = [(math.cos(TWO_PI * k / 8.0), math.sin(TWO_PI * k / 8.0)) for k in range(8)]
    while step >= tol and n_eval < max_eval:
        improved = False
        for dx, dy in dirs:
            y = clip_full([x[0] + step * dx, x[1] + step * dy], a, b, smax)
            fy = float(f(y))
            n_eval += 1
            if fy < fx:
                x, fx = y, fy
                improved = True
                break
        if not improved:
            step *= 0.5
    return x, fx, n_eval, bool(step < tol)


def grid_points_scaled(a, b, smax, n_theta=40, n_s=15):
    pts = [(0.0, 0.0)]
    for i in range(1, n_s + 1):
        s = smax * i / n_s
        for j in range(n_theta):
            th = TWO_PI * j / n_theta
            pts.append((a * s * math.cos(th), b * s * math.sin(th)))
    return pts


def main():
    t_start = time.time()
    cases = {}
    scaling = []
    lower = []
    total = len(RATIOS)
    for idx, ratio in enumerate(RATIOS, start=1):
        t0 = time.time()
        b = 1.0
        a = ratio * b
        tag = "%g/1" % ratio
        ref = DISK_REF[ratio]

        def f(P, a=a, b=b):
            return var_np(a, b, P, N_DIRS)

        pts = grid_points_scaled(a, b, SMAX, 40, 15)
        scored = []
        for P in pts:
            scored.append((f(P), P))
        scored.sort(key=lambda t: t[0])
        n_eval = len(scored)

        best_v = scored[0][0]
        best_P = [float(scored[0][1][0]), float(scored[0][1][1])]
        runs = []
        for k in range(min(3, len(scored))):
            x, fx, ne, cvg = compass_full(f, scored[k][1], a, b, SMAX)
            n_eval += ne
            runs.append({"start": [float(scored[k][1][0]), float(scored[k][1][1])],
                         "P": [float(x[0]), float(x[1])], "var_2000dirs": float(fx),
                         "evals": int(ne), "converged": bool(cvg)})
            if fx < best_v:
                best_v = float(fx)
                best_P = [float(x[0]), float(x[1])]

        # 8000-direction local refinement around the 2000-direction winner
        v8 = lambda P, a=a, b=b: var_np(a, b, P, N_WIDE)
        x8, fx8, ne8, cvg8 = compass_full(v8, best_P, a, b, SMAX, tol=1e-9, max_eval=2000)
        n_eval += ne8
        Pf = [float(x8[0]), float(x8[1])]
        v2000 = var_np(a, b, Pf, 2000)
        v8000 = var_np(a, b, Pf, 8000)
        rec = {
            "a": a,
            "b": b,
            "a_over_b": a / b,
            "search_domain": "whole ellipse in scaled coordinates s = hypot(x/a, y/b) <= %g" % SMAX,
            "grid_starts": len(pts),
            "grid_best_var_2000dirs": float(scored[0][0]),
            "grid_best_P": [float(scored[0][1][0]), float(scored[0][1][1])],
            "compass_runs": runs,
            "P_star": Pf,
            "abs_P_star": math.hypot(Pf[0], Pf[1]),
            "scaled_radius_s": math.hypot(Pf[0] / a, Pf[1] / b),
            "var_2000dirs_np_two_pass": v2000,
            "var_8000dirs_np_two_pass": v8000,
            "local_8000dirs_refine_evals": int(ne8),
            "local_8000dirs_refine_converged": bool(cvg8),
            "disk_ref_var_exp000012": ref["var"],
            "disk_ref_abs_P_exp000012": ref["abs_P"],
            "evals": int(n_eval),
        }
        if HAVE_MP:
            vm2000 = var_mp(a, b, Pf, 2000)
            vm8000 = var_mp(a, b, Pf, 8000)
            rec["var_2000dirs_mp"] = vm2000
            rec["var_8000dirs_mp"] = vm8000
            rec["abs_P_clearly_nonzero"] = bool(math.hypot(Pf[0], Pf[1]) > 1e-3)
            final_var = vm8000
        else:
            rec["mp_note"] = "mpmath unavailable: float64 only"
            final_var = v8000
        rec["final_var_used"] = final_var
        rec["rel_diff_vs_disk_ref"] = (final_var - ref["var"]) / ref["var"]
        rec["below_disk_ref_by_more_than_1e-6"] = bool(final_var < ref["var"] * (1.0 - REL_TOL))
        if rec["below_disk_ref_by_more_than_1e-6"]:
            lower.append(tag)
        secs = time.time() - t0
        rec["seconds"] = round(secs, 3)
        cases[tag] = rec
        scaling.append({"n": tag, "starts": len(pts), "evals": int(n_eval),
                        "directions": [N_DIRS, N_WIDE], "seconds": round(secs, 3)})
        print("PROGRESS: " + json.dumps({"task": "S3f", "done": idx, "total": total,
                                         "case": tag, "P_star": Pf,
                                         "abs_P_star": rec["abs_P_star"],
                                         "scaled_radius_s": rec["scaled_radius_s"],
                                         "var_8000dirs_final": final_var,
                                         "disk_ref_var": ref["var"],
                                         "rel_diff_vs_disk_ref": rec["rel_diff_vs_disk_ref"],
                                         "seconds": round(secs, 3)}, sort_keys=True),
              flush=True)

    if lower:
        tag = lower[0]
        r = cases[tag]
        out = {
            "result": "refutes",
            "counterexample": {
                "claim_refuted": "exp:000012 disk-restricted values are the whole-ellipse infimum (within 1e-6)",
                "case": tag, "a": r["a"], "b": r["b"], "P": r["P_star"],
                "abs_P_star": r["abs_P_star"],
                "var_2000dirs_mp": r.get("var_2000dirs_mp"),
                "var_8000dirs_mp": r.get("var_8000dirs_mp"),
                "disk_ref_var_exp000012": r["disk_ref_var_exp000012"],
                "rel_diff_vs_disk_ref": r["rel_diff_vs_disk_ref"],
            },
            "bound": {"search_domain": "whole ellipse, s <= %g" % SMAX,
                      "grid_starts": 601, "directions": [N_DIRS, N_WIDE],
                      "ratios": RATIOS, "rel_tol": REL_TOL,
                      "cases_below_disk_ref": lower},
            "strategy": "scaled-coordinate multistart (40 theta x 15 s + centre) + compass/pattern search (8 dirs) of the 2000-direction variance, 8000-direction local refinement (step 0.05 -> 1e-9), 50-digit mpmath two-pass variance at the final point; analytic quadratic chord-length formula",
            "scaling": scaling,
            "data": {"cases": cases},
            "note": ("a whole-ellipse point beats the exp:000012 disk value: the disk number was NOT the "
                     "infimum over the ellipse, so exp:000012's per-ratio values must not be quoted as the "
                     "whole-ellipse infimum. NUMERIC ONLY (Lean disabled), evidence_kind <= cross_check. "
                     "This refutes the calibration reading, NOT conjecture 000000: the variance is still "
                     "> 0."),
            "runtime_sec": round(time.time() - t_start, 3),
        }
    else:
        out = {
            "result": "supports",
            "bound": {"search_domain": "whole ellipse, s = hypot(x/a, y/b) <= %g" % SMAX,
                      "grid_starts": 601, "directions": [N_DIRS, N_WIDE],
                      "ratios": RATIOS, "rel_tol": REL_TOL,
                      "cases_below_disk_ref": []},
            "strategy": "scaled-coordinate multistart (40 theta x 15 s + centre) + compass/pattern search (8 dirs) of the 2000-direction variance, 8000-direction local refinement (step 0.05 -> 1e-9), 50-digit mpmath two-pass variance at the final point; analytic quadratic chord-length formula",
            "scaling": scaling,
            "data": {"cases": cases},
            "note": ("within the searched coverage no whole-ellipse point beats the exp:000012 disk values by "
                     "more than 1e-6 relative, so those interior minima are not an artifact of the "
                     "|P| <= 0.99*min(a,b) truncation (the 0.9-boundary hits of exp:000008 were: they are "
                     "reproduced as 0.103960 / 0.253103 / 1.483730 at R=0.9 and fall to 0.098300 / "
                     "0.210864 / 1.086853 once the disk is allowed to be larger). Search is a multistart "
                     "heuristic: global minimality over the ellipse is NOT proven. NUMERIC ONLY (Lean "
                     "disabled), evidence_kind <= cross_check, no proof of conjecture 000000 is claimed."),
            "runtime_sec": round(time.time() - t_start, 3),
        }
    print("REPRO_RESULT: " + json.dumps(out, sort_keys=True, default=float), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
