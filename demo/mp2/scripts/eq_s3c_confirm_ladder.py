#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3c: 8000-direction + 50-digit confirmation of the enlarged-domain minima from S3 (exp:000011).

Conjecture 000000: the ellipse x^2/a^2 + y^2/b^2 = 1 with a != b has no equichordal point,
i.e. Var_phi L_P(phi) > 0 for every interior P.  NUMERIC ONLY: Lean is disabled in this
session, so evidence_kind <= cross_check; nothing here is a proof.

What this closes
exp:000011 (S3) grew the search disk from 0.9*min(a,b) to 0.99*min(a,b) (ladder
0.9 -> 0.95 -> 0.99 -> 0.999) and reported for a/b in {2.5, 3, 5} that var_inf falls
(0.103960 -> 0.0982997 at |P*|=0.92383; 0.253103 -> 0.210864 at |P*|=0.95174;
1.483730 -> 1.086853 at |P*|=0.98920) and is then FLAT between R=0.99 and R=0.999 with
P* inside the disk.  That reading used a 2000-direction objective, so two loopholes
remain: (i) the argmin might be a 2000-direction discretisation artifact; (ii) the
reported variance might not be the continuum variance.  This script repeats the whole
ladder with an 8000-direction objective (independent argmin) and evaluates both the
2000- and 8000-direction variances at the reported minima in 50-digit mpmath (two-pass),
so the 1e-18 refutation threshold is actually resolvable.  It also re-evaluates the
R=0.9 minima in mpmath, which pins down S1's (exp:000008) domain-bound values exactly
at the points S1 used.
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


# ---------------------------------------------------------------- geometry ---
def chord_np(a, b, P, n):
    """Exact chord lengths through interior P in n uniform directions (analytic quadratic)."""
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
        raise RuntimeError("degenerate direction (point on/outside the ellipse)")
    return 2.0 * np.sqrt(disc) / A


def var_np(a, b, P, n):
    L = chord_np(a, b, P, n)
    m1 = float(np.mean(L))
    d = L - m1
    return float(np.mean(d * d)), m1, float(L.min()), float(L.max())


def var_mp(a, b, P, n):
    """50-digit two-pass variance over n uniform directions."""
    aa = mp.mpf(a)
    bb = mp.mpf(b)
    px = mp.mpf(float(P[0]))
    py = mp.mpf(float(P[1]))
    vals = []
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
        vals.append(2 * mp.sqrt(disc) / A)
    m1 = mp.fsum(vals) / n
    v = mp.fsum([(x - m1) * (x - m1) for x in vals]) / n
    return float(v), float(m1)


# ---------------------------------------------------------------- search -----
def compass(f, x0, R, tol=1e-7, step0=None, max_eval=6000):
    def clip(x):
        r = math.hypot(x[0], x[1])
        if r > R:
            return [x[0] * R / r, x[1] * R / r]
        return [float(x[0]), float(x[1])]

    x = clip(list(x0))
    fx = float(f(x))
    n_eval = 1
    step = 0.1 * R if step0 is None else step0
    dirs = [(math.cos(TWO_PI * i / 8.0), math.sin(TWO_PI * i / 8.0)) for i in range(8)]
    while step > tol and n_eval < max_eval:
        improved = False
        for dx, dy in dirs:
            y = clip([x[0] + step * dx, x[1] + step * dy])
            fy = float(f(y))
            n_eval += 1
            if fy < fx:
                x, fx, improved = y, fy, True
                break
        if not improved:
            step *= 0.5
    return x, fx, n_eval, bool(step <= tol)


def grid_points(R, n_side=11):
    pts = []
    for i in range(n_side):
        px = -R + 2.0 * R * i / (n_side - 1)
        for j in range(n_side):
            py = -R + 2.0 * R * j / (n_side - 1)
            if math.hypot(px, py) <= R + 1e-12:
                pts.append((px, py))
    return pts


def global_min(a, b, R, n_dirs, n_side=11):
    def f(P):
        return var_np(a, b, P, n_dirs)[0]

    pts = grid_points(R, n_side)
    scored = sorted(((f(P), P) for P in pts), key=lambda t: t[0])
    n_eval = len(scored)
    best_var, best_P = float(scored[0][0]), list(scored[0][1])
    conv = []
    for s in [scored[k][1] for k in range(min(3, len(scored)))]:
        x, fx, ne, cvg = compass(f, s, R, tol=1e-7)
        n_eval += ne
        conv.append(cvg)
        if fx < best_var:
            best_var, best_P = fx, list(x)
    return best_var, [float(best_P[0]), float(best_P[1])], n_eval, bool(all(conv))


# ---------------------------------------------------------------- cases ------
LADDER = [0.9, 0.95, 0.99, 0.999]
RATIOS = [(2.0, 1.0, "2/1"), (2.5, 1.0, "2.5/1"), (3.0, 1.0, "3/1"), (5.0, 1.0, "5/1")]
N_MAIN = 8000
N_CROSS = 2000


def main():
    t_start = time.time()
    ladder_recs = {}
    scaling = []
    total = len(RATIOS)
    for idx, (a, b, tag) in enumerate(RATIOS, start=1):
        t0 = time.time()
        rmin = min(a, b)
        rows = []
        n_tot = 0
        for frac in LADDER:
            R = frac * rmin
            v, P, ne, cvg = global_min(a, b, R, N_MAIN)
            n_tot += ne
            absP = math.hypot(P[0], P[1])
            rows.append({
                "frac_of_min_ab": frac,
                "search_radius": R,
                "var_inf_8000dirs_np": v,
                "P_star": P,
                "abs_P_star": absP,
                "rel_margin_to_domain_boundary": (R - absP) / R,
                "P_star_on_domain_boundary": bool(abs(R - absP) < 1e-6),
                "evals": ne,
                "converged": cvg,
            })
        v_last = rows[-1]["var_inf_8000dirs_np"]
        v_prev = rows[-2]["var_inf_8000dirs_np"]
        v_first = rows[0]["var_inf_8000dirs_np"]
        flat = bool(abs(v_last - v_prev) <= 1e-9 * max(1.0, abs(v_last)))
        P_09 = rows[0]["P_star"]
        P_last = rows[-1]["P_star"]
        shift = math.hypot(P_last[0] - P_09[0], P_last[1] - P_09[1])
        rec = {
            "case": tag,
            "a": a,
            "b": b,
            "a_over_b": a / b,
            "directions": N_MAIN,
            "strategy": "11x11 multistart grid in the disk + compass/pattern search "
                        "(8 directions, step halved from 0.1*R to 1e-7), 8000-direction objective",
            "ladder": rows,
            "var_inf_at_0.9_domain": v_first,
            "var_inf_at_0.999_domain": v_last,
            "value_drop_from_0.9_to_0.999": v_first - v_last,
            "flat_between_0.99_and_0.999": flat,
            "P_star_shift_0.9_to_0.999": shift,
            "argmin_interior_at_0.999": bool(not rows[-1]["P_star_on_domain_boundary"]),
        }
        if HAVE_MP:
            v2k, m2k = var_mp(a, b, P_last, N_CROSS)
            v8k, m8k = var_mp(a, b, P_last, N_MAIN)
            v2k_09, _ = var_mp(a, b, P_09, N_CROSS)
            rec.update({
                "mp_dps": MP_DPS,
                "var_2000dirs_mp_at_P_0.999": v2k,
                "var_8000dirs_mp_at_P_0.999": v8k,
                "mean_chord_2000dirs_mp": m2k,
                "mean_chord_8000dirs_mp": m8k,
                "var_8000_minus_2000_mp": v8k - v2k,
                "var_2000dirs_mp_at_P_0.9": v2k_09,
                "np_minus_mp_8000dirs_at_P_0.999": rows[-1]["var_inf_8000dirs_np"] - v8k,
                "abs_P_star": rows[-1]["abs_P_star"],
                "below_1e18_both_direction_counts": bool(v2k < 1e-18 and v8k < 1e-18),
                "abs_P_clearly_nonzero": bool(rows[-1]["abs_P_star"] > 1e-3),
            })
            rec["satisfies_refutation_criterion"] = bool(
                rec["below_1e18_both_direction_counts"] and rec["abs_P_clearly_nonzero"])
        else:
            rec["satisfies_refutation_criterion"] = False
            rec["mp_note"] = "mpmath unavailable: float64 only, 1e-18 threshold not resolvable"
        secs = time.time() - t0
        rec["seconds"] = round(secs, 3)
        rec["total_evals"] = n_tot
        ladder_recs[tag] = rec
        scaling.append({"n": tag, "a": a, "b": b, "a_over_b": a / b,
                        "directions": N_MAIN, "domain_fracs": LADDER,
                        "evals": n_tot, "seconds": round(secs, 3)})
        print("PROGRESS: " + json.dumps({"task": "S3c", "done": idx, "total": total,
                                         "case": tag,
                                         "var_inf_0.999_8000dirs_np": v_last,
                                         "abs_P_star_0.999": rows[-1]["abs_P_star"],
                                         "flat_0.99_to_0.999": flat,
                                         "seconds": round(secs, 3)}, sort_keys=True),
              flush=True)

    counterexample = None
    for t, r in ladder_recs.items():
        if r.get("satisfies_refutation_criterion"):
            counterexample = {"case": t, "a": r["a"], "b": r["b"], "P_star": r["P_star"],
                              "var_2000dirs_mp": r.get("var_2000dirs_mp_at_P_0.999"),
                              "var_8000dirs_mp": r.get("var_8000dirs_mp_at_P_0.999")}
            break

    all_flat = all(r["flat_between_0.99_and_0.999"] for r in ladder_recs.values())
    all_interior = all(r["argmin_interior_at_0.999"] for r in ladder_recs.values())
    if counterexample is not None:
        result = "refutes"
        note = ("counterexample candidate %s: both 2000- and 8000-direction 50-digit variance "
                "< 1e-18 at a point with |P| clearly nonzero" % counterexample["case"])
    else:
        result = "supports"
        note = ("no counterexample: at every tested ratio the 50-digit 2000- and 8000-direction "
                "variance at the enlarged-domain minimum is far above 1e-18. "
                "Domain-binding reading (part (a) of the assignment): flat_0.99_to_0.999=%s, "
                "argmin interior at R=0.999 for all ratios=%s. The 8000-direction argmin is an "
                "independent recomputation of the argmin found with 2000 directions in exp:000011; "
                "a small P_star_shift means the 2000-direction argmin was NOT a discretisation "
                "artifact. Consequence for exp:000008: the a/b>=2.5 values it fitted were "
                "domain-bound UPPER BOUNDS at R=0.9*min(a,b), not the infimum over the interior, "
                "so its power-law exponent must not be read beyond a/b ~ 2. Scope: the search "
                "domain is a disk of radius 0.999*min(a,b), a strict subset of the ellipse "
                "interior; the numbers are the smallest values found by multistart compass "
                "search over that disk, not a proved infimum. Numeric evidence only, not a proof; "
                "no Rychlik convex-body negative solution is used."
                % (all_flat, all_interior))

    out = {
        "result": result,
        "bound": {
            "search_domain": "|P| <= frac*min(a,b), frac in " + str(LADDER),
            "directions": [N_MAIN, N_CROSS],
            "compass_step_tol": 1e-7,
            "ratios": [t for _, _, t in RATIOS],
            "refutation_threshold": "var < 1e-18 at BOTH 2000 and 8000 dirs and |P| clearly nonzero",
            "flat_between_0.99_and_0.999_all_ratios": all_flat,
            "argmin_interior_at_0.999_all_ratios": all_interior,
            "per_ratio": {t: {"var_inf_8000dirs_ladder": [row["var_inf_8000dirs_np"] for row in r["ladder"]],
                              "abs_P_star_ladder": [row["abs_P_star"] for row in r["ladder"]],
                              "var_2000dirs_mp_at_P_0.999": r.get("var_2000dirs_mp_at_P_0.999"),
                              "var_8000dirs_mp_at_P_0.999": r.get("var_8000dirs_mp_at_P_0.999"),
                              "P_star_shift_0.9_to_0.999": r["P_star_shift_0.9_to_0.999"],
                              "P_star_on_0.999_boundary": r["ladder"][-1]["P_star_on_domain_boundary"]}
                          for t, r in ladder_recs.items()},
        },
        "strategy": "per ratio: 11x11 multistart grid inside the disk + compass/pattern search "
                    "(8 directions, step 0.1*R -> 1e-7) minimising the 8000-direction variance, "
                    "over a domain ladder R in {0.9,0.95,0.99,0.999}*min(a,b); then 2000- and "
                    "8000-direction two-pass variances at the reported minima in 50-digit mpmath; "
                    "analytic quadratic chord-length formula throughout (no ray shooting)",
        "scaling": scaling,
        "data": ladder_recs,
        "note": note,
        "runtime_sec": round(time.time() - t_start, 3),
    }
    if counterexample is not None:
        out["counterexample"] = counterexample
    print("REPRO_RESULT: " + json.dumps(out, sort_keys=True, default=float), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
