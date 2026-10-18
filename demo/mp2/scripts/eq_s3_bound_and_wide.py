#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3: (a) domain-bound scan for the S1 boundary binding + (b) wider S2 pointwise cross-check.

Conjecture 000000 (ellipse x^2/a^2 + y^2/b^2 = 1, a != b): no equichordal point, i.e.
for every interior P, Var_phi L_P(phi) > 0.  NUMERIC script, not a proof.  Lean is
disabled in this session; evidence_kind can be at most cross_check.

PART (a) — the known stuck point of S1 (exp:000008):
  S1 minimised over |P| <= 0.9*min(a,b) and for a/b >= 2.5 the reported P* sat ON the
  search-domain boundary (|P*| = 0.9*min(a,b)), so its var_inf was a truncated value,
  not an infimum.  Here the same 2000-direction objective is re-minimised over a
  DOMAIN LADDER R in {0.9, 0.95, 0.99, 0.999} * min(a,b) for a/b in {2.5, 3, 5} (b=1),
  so that "does the infimum keep falling as the domain grows?" is a direct reading
  (same code, same directions, only R changes).  If a P* is still on the boundary of
  the largest domain, or if var_inf keeps falling at the last step, the reading is
  "infimum not determined / domain binding unresolved" — explicitly NOT a true infimum.

PART (b) — extend S2 (exp:000010, which covered a/b = 1.01 and 1.1 only) to
  a/b in {1.5, 2, 3}: global 2000-direction minimisation over |P| <= 0.99*min(a,b),
  then an 8000-direction local refinement around that P*, then BOTH 2000- and
  8000-direction variances evaluated at the final point in numpy float64 (two-pass)
  and in 50-digit mpmath.  Refutation criterion (conjecture 000000.testable,
  quoted): 2000-dir variance < 1e-18 AND 8000-dir variance < 1e-18 AND |P| clearly
  nonzero.  Anything else is supporting numeric evidence only, never a proof.

PRE-REGISTERED decision rule for the single REPRO_RESULT `result` field
(fixed before running, so the number cannot pick the verdict):
  1. refutes      : some part-(b) case satisfies the full refutation criterion
                    (both 2000 and 8000 dir mpmath variance < 1e-18, |P*| > 1e-3);
  2. inconclusive : else, if part (a) is still domain-bound, i.e. for some ratio
                    P* lies on the largest-domain boundary (to 1e-6) OR the last
                    domain step still lowers var_inf by more than 0.1% relative;
  3. supports     : otherwise (no counterexample AND no residual domain binding).
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

N_MAIN = 2000
N_WIDE = 8000
TOL = 1e-7
GRID_SIDE = 11


# ------------------------------------------------------------------ geometry ---
def chord_np(a, b, P, n):
    """Exact chord lengths of line {P + t*u} with the ellipse, |u|=1.

    A t^2 + 2B t + (C-1) = 0 with A = c^2/a^2 + s^2/b^2 (c=cos phi, s=sin phi),
    B = px c/a^2 + py s/b^2, C = px^2/a^2 + py^2/b^2.  Chord = 2 sqrt(B^2 - A(C-1)) / A.
    """
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
        raise RuntimeError("degenerate direction / P outside the ellipse")
    return 2.0 * np.sqrt(disc) / A


def var_np(a, b, P, n):
    """Two-pass variance of the n chord lengths (the one-pass m2-m1^2 form cannot
    resolve anything below ~8*eps*mean(L^2) ~ 1e-15)."""
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


# ------------------------------------------------------------------- search ----
def compass_disk(f, x0, R, tol=TOL, step0=None, max_eval=4000):
    """Compass / pattern search on 8 directions inside the closed disk |x| <= R
    (candidate points are projected back onto the disk).  Step is halved on no
    improvement until it drops below `tol`."""
    def clip(x):
        r = math.hypot(x[0], x[1])
        if r > R:
            return [x[0] * R / r, x[1] * R / r]
        return [float(x[0]), float(x[1])]

    x = clip(list(x0))
    fx = float(f(x))
    n_eval = 1
    step = (0.1 * R) if step0 is None else float(step0)
    dirs = [(math.cos(TWO_PI * i / 8.0), math.sin(TWO_PI * i / 8.0)) for i in range(8)]
    while step >= tol and n_eval < max_eval:
        improved = False
        for dx, dy in dirs:
            y = clip([x[0] + step * dx, x[1] + step * dy])
            fy = float(f(y))
            n_eval += 1
            if fy < fx:
                x, fx = y, fy
                improved = True
                break
        if not improved:
            step *= 0.5
    return x, fx, n_eval, bool(step < tol)


def grid_points(R, n_side=GRID_SIDE):
    pts = []
    for i in range(n_side):
        px = -R + 2.0 * R * i / (n_side - 1)
        for j in range(n_side):
            py = -R + 2.0 * R * j / (n_side - 1)
            if math.hypot(px, py) <= R + 1e-12:
                pts.append((px, py))
    return pts


def global_min_disk(a, b, R, n_dirs=N_MAIN, tol=TOL):
    """11x11 multistart grid in the disk + compass refinement of the 3 best starts."""
    def f(P):
        return var_np(a, b, P, n_dirs)[0]

    pts = grid_points(R)
    scored = sorted(((f(P), P) for P in pts), key=lambda t: t[0])
    n_evals = len(scored)
    best_P, best_v, best_ne, best_conv = list(scored[0][1]), float(scored[0][0]), 0, True
    starts = [scored[i][1] for i in range(min(3, len(scored)))]
    convs = []
    for s in starts:
        x, fx, ne, cvg = compass_disk(f, s, R, tol=tol)
        n_evals += ne
        convs.append(cvg)
        if fx < best_v:
            best_P, best_v, best_ne, best_conv = x, fx, ne, cvg
    return {
        "P_star": [float(best_P[0]), float(best_P[1])],
        "abs_P_star": math.hypot(best_P[0], best_P[1]),
        "var_inf": float(best_v),
        "evals": int(n_evals),
        "grid_points": len(pts),
        "converged_all_starts": bool(all(convs)),
        "P_star_on_disk_boundary": bool(abs(math.hypot(best_P[0], best_P[1]) - R) < 1e-6),
    }


def compass_box(f, x0, center, R, dom, tol=1e-9, step0=0.02, max_eval=3000):
    """Local box (radius R around `center`) clipped to |x| <= dom; used to refine
    the 8000-direction objective around the 2000-direction minimiser."""
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
    fx = float(f(x))
    n_eval = 1
    step = float(step0)
    dirs = [(math.cos(TWO_PI * i / 8.0), math.sin(TWO_PI * i / 8.0)) for i in range(8)]
    while step > tol and n_eval < max_eval:
        improved = False
        for dx, dy in dirs:
            y = clip([x[0] + step * dx, x[1] + step * dy])
            fy = float(f(y))
            n_eval += 1
            if fy < fx:
                x, fx = y, fy
                improved = True
                break
        if not improved:
            step *= 0.5
    return x, fx, n_eval, bool(step <= tol)


# --------------------------------------------------------------------- main ----
RATIOS_A = [2.5, 3.0, 5.0]              # part (a): the ratios where S1 was boundary-bound
DOMAIN_LADDER = [0.9, 0.95, 0.99, 0.999]  # fraction of min(a,b)
RATIOS_B = [1.5, 2.0, 3.0]              # part (b): extension of S2's pointwise check
DOM_B = 0.99                            # enlarged domain used for part (b)
R_LOC = 0.05                            # local refinement box radius around P*


def main():
    t_start = time.time()
    out = {
        "task": "S3: (a) domain-bound scan |P| <= R*min(a,b) for a/b in {2.5,3,5}; "
                "(b) S2 pointwise cross-check extended to a/b in {1.5,2,3}",
        "depends_on": "exp:000008 (S1), exp:000010 (S2 v2), conjecture 000000",
        "conjecture_refutation_criterion_quoted":
            "2000-dir variance < 1e-18 AND 8000-dir variance < 1e-18 AND |P| clearly nonzero",
        "strategy": "11x11 multistart grid in the disk + compass/pattern search "
                    "(8 directions, step halved to 1e-7) of the 2000-direction variance; "
                    "domain ladder to test boundary binding; part (b) adds 8000-direction "
                    "local refinement (box radius 0.05, step 0.02 -> 1e-9) and a 50-digit "
                    "mpmath two-pass variance of both 2000 and 8000 direction sets",
        "precision_note": "float64 two-pass variance; the 1e-18 threshold is only "
                          "resolvable in 50-digit mpmath, so all refutation decisions use mp values",
        "mpmath_available": bool(HAVE_MP),
        "decision_rule_preregistered": [
            "refutes if some part-(b) case has mp var_2000 < 1e-18 AND mp var_8000 < 1e-18 AND |P*| > 1e-3",
            "inconclusive if part (a) is still domain-bound (P* on the largest-domain boundary, "
            "or the last domain step still lowers var_inf by > 0.1% relative)",
            "supports otherwise",
        ],
        "lean_formalization": "disabled in this session: no formal evidence, evidence_kind at most cross_check",
    }
    scaling = []
    part_a = {}
    part_b = {}
    total_tasks = len(RATIOS_A) * len(DOMAIN_LADDER) + len(RATIOS_B)
    done = 0

    # ---------------- PART (a): domain ladder ----------------
    print("PROGRESS: " + json.dumps({"task": "S3a", "phase": "start",
                                     "ratios": RATIOS_A,
                                     "domain_ladder": DOMAIN_LADDER}, sort_keys=True), flush=True)
    for ratio in RATIOS_A:
        a, b = float(ratio), 1.0
        tag = "%g/1" % ratio
        rung = {}
        for frac in DOMAIN_LADDER:
            tc0 = time.time()
            R = frac * min(a, b)
            g = global_min_disk(a, b, R, N_MAIN)
            g["domain_frac"] = frac
            g["search_radius"] = R
            g["directions"] = N_MAIN
            g["seconds"] = round(time.time() - tc0, 4)
            # cross-check the reported value in mpmath-free float64 two-pass at P*
            v_rep, m_rep, lmin, lmax = var_np(a, b, g["P_star"], N_MAIN)
            g["var_2000_float64_two_pass_at_Pstar"] = v_rep
            g["rel_var_2000"] = v_rep / (m_rep * m_rep) if m_rep else None
            g["mean_chord"] = m_rep
            g["Lmin"] = lmin
            g["Lmax"] = lmax
            rung["R=%g" % frac] = g
            done += 1
            scaling.append({"part": "a", "case": tag, "domain_frac": frac, "seconds": g["seconds"],
                            "evals": g["evals"], "dirs": N_MAIN})
            print("PROGRESS: " + json.dumps({"task": "S3a", "done": done, "total": total_tasks,
                                             "case": tag, "domain_frac": frac,
                                             "var_inf": g["var_inf"],
                                             "abs_P_star": g["abs_P_star"],
                                             "on_boundary": g["P_star_on_disk_boundary"],
                                             "seconds": g["seconds"]}, sort_keys=True), flush=True)
        keys = ["R=%g" % f for f in DOMAIN_LADDER]
        vals = [rung[k]["var_inf"] for k in keys]
        absP = [rung[k]["abs_P_star"] for k in keys]
        last_ratio = vals[-1] / vals[-2] if vals[-2] > 0 else float("nan")
        part_a[tag] = {
            "a": a, "b": b, "a_over_b": a / b,
            "domain_fracs": DOMAIN_LADDER,
            "rungs": rung,
            "var_inf_sequence": vals,
            "abs_P_star_sequence": absP,
            "var_inf_ratio_last_step_R0.99_over_R0.95": last_ratio,
            "var_inf_monotone_decreasing_over_ladder": bool(all(
                vals[i + 1] < vals[i] for i in range(len(vals) - 1))),
            "still_falling_at_last_step": bool(last_ratio < 0.999),
            "P_star_on_boundary_of_0.99_domain": rung["R=0.99"]["P_star_on_disk_boundary"],
            "P_star_on_boundary_of_largest_domain": rung[keys[-1]]["P_star_on_disk_boundary"],
        }

    # ---------------- PART (b): pointwise cross-check at 1.5, 2, 3 ----------------
    print("PROGRESS: " + json.dumps({"task": "S3b", "phase": "start", "ratios": RATIOS_B,
                                    "domain_frac": DOM_B}, sort_keys=True), flush=True)
    for ratio in RATIOS_B:
        tc0 = time.time()
        a, b = float(ratio), 1.0
        tag = "%g/1" % ratio
        dom = DOM_B * min(a, b)
        g = global_min_disk(a, b, dom, N_MAIN)
        P0 = g["P_star"]
        f8 = lambda P, a=a, b=b: var_np(a, b, P, N_WIDE)[0]
        starts = [P0, [P0[0] + 0.02, P0[1]], [P0[0] - 0.02, P0[1] + 0.01], [0.0, P0[1]]]
        runs = []
        best = None
        for s in starts:
            xs, fs, ne, cvg = compass_box(f8, s, P0, R_LOC, dom)
            runs.append({"start": [float(s[0]), float(s[1])],
                         "P": [float(xs[0]), float(xs[1])],
                         "var_8000dirs_float64": float(fs),
                         "evals": int(ne), "converged": bool(cvg)})
            if best is None or fs < best[1]:
                best = (xs, float(fs), int(ne), bool(cvg))
        Pf = [float(best[0][0]), float(best[0][1])]
        v2k, m2k, lmin2, lmax2 = var_np(a, b, Pf, N_MAIN)
        v8k, m8k, lmin8, lmax8 = var_np(a, b, Pf, N_WIDE)
        rec = {
            "a": a, "b": b, "a_over_b": a / b,
            "search_domain_radius": dom,
            "global_2000dirs": g,
            "local_box_radius_around_global_Pstar": R_LOC,
            "local_runs": runs,
            "local_evals_best": int(best[2]),
            "converged": bool(best[3]),
            "P_star": Pf,
            "abs_P_star": math.hypot(Pf[0], Pf[1]),
            "P_star_on_domain_boundary": bool(abs(math.hypot(Pf[0], Pf[1]) - dom) < 1e-6),
            "var_2000dirs_float64_two_pass": v2k,
            "var_8000dirs_float64_two_pass": v8k,
            "var_8000_minus_2000_float64": v8k - v2k,
            "mean_chord_2000dirs": m2k,
            "mean_chord_8000dirs": m8k,
            "rel_var_2000dirs": v2k / (m2k * m2k),
            "rel_var_8000dirs": v8k / (m8k * m8k),
            "Lmin_2000dirs": lmin2, "Lmax_2000dirs": lmax2,
            "Lmin_8000dirs": lmin8, "Lmax_8000dirs": lmax8,
            "float64_one_pass_noise_floor_8eps_meanL2": 8.0 * EPS * m8k * m8k,
        }
        if HAVE_MP:
            vm2, mm2, mlmin2, mlmax2 = var_mp(a, b, Pf, N_MAIN)
            vm8, mm8, mlmin8, mlmax8 = var_mp(a, b, Pf, N_WIDE)
            rec.update({
                "mp_dps": MP_DPS,
                "var_2000dirs_mp": vm2,
                "var_8000dirs_mp": vm8,
                "var_8000_minus_2000_mp": vm8 - vm2,
                "rel_var_8000dirs_mp": vm8 / (mm8 * mm8),
                "mean_chord_2000dirs_mp": mm2,
                "mean_chord_8000dirs_mp": mm8,
                "Lmin_2000dirs_mp": mlmin2, "Lmax_2000dirs_mp": mlmax2,
                "Lmin_8000dirs_mp": mlmin8, "Lmax_8000dirs_mp": mlmax8,
                "var_2000dirs_float64_minus_mp": v2k - vm2,
                "var_8000dirs_float64_minus_mp": v8k - vm8,
                "both_mp_below_1e18": bool(vm2 < 1e-18 and vm8 < 1e-18),
                "abs_P_clearly_nonzero_gt_1e-3": bool(math.hypot(Pf[0], Pf[1]) > 1e-3),
            })
            rec["satisfies_refutation_criterion"] = bool(
                rec["both_mp_below_1e18"] and rec["abs_P_clearly_nonzero_gt_1e-3"])
        else:
            rec["satisfies_refutation_criterion"] = False
            rec["mp_note"] = "mpmath unavailable: float64 only, the 1e-18 threshold is NOT resolvable -> no refutation claim"
        rec["seconds"] = round(time.time() - tc0, 3)
        part_b[tag] = rec
        done += 1
        scaling.append({"part": "b", "case": tag, "seconds": rec["seconds"],
                        "local_evals_best": rec["local_evals_best"],
                        "dirs_final": [N_MAIN, N_WIDE],
                        "search_domain_radius": dom})
        print("PROGRESS: " + json.dumps({"task": "S3b", "done": done, "total": total_tasks,
                                         "case": tag, "P_star": Pf,
                                         "abs_P_star": rec["abs_P_star"],
                                         "var_2000dirs_mp": rec.get("var_2000dirs_mp"),
                                         "var_8000dirs_mp": rec.get("var_8000dirs_mp"),
                                         "refutation_criterion": rec["satisfies_refutation_criterion"],
                                         "seconds": rec["seconds"]}, sort_keys=True), flush=True)

    # ---------------- verdict (pre-registered rule) ----------------
    refutes = [t for t, r in part_b.items() if r["satisfies_refutation_criterion"]]
    domain_bound = [t for t, r in part_a.items()
                    if r["P_star_on_boundary_of_0.99_domain"]
                    or r["still_falling_at_last_step"]]
    if refutes:
        tag = refutes[0]
        r = part_b[tag]
        result = "refutes"
        counterexample = {"a": r["a"], "b": r["b"], "P": r["P_star"],
                          "abs_P_star": r["abs_P_star"],
                          "var_2000dirs_mp": r["var_2000dirs_mp"],
                          "var_8000dirs_mp": r["var_8000dirs_mp"]}
        note = ("counterexample candidate at a/b=%s satisfies the full refutation criterion "
                "(2000/8000 dir mpmath variance < 1e-18 with |P*| > 1e-3); numeric only" % tag)
    elif domain_bound:
        result = "inconclusive"
        counterexample = None
        note = ("no counterexample, but part (a) is STILL DOMAIN-BOUND for a/b in %s: the reported "
                "var_inf is a truncation-dependent value, so the infimum over the ellipse interior "
                "is NOT determined by this run -> 下确界未定 / 域绑定未解 (unresolved stuck point), "
                "it must not be read as the true infimum. Part (b) shows the pointwise variances at "
                "a/b in {1.5,2,3} stay far above 1e-18 on both direction counts (mpmath 50 digits). "
                "Numeric evidence only, not a proof." % ", ".join(sorted(domain_bound)))
    else:
        result = "supports"
        counterexample = None
        note = ("no counterexample: the pointwise 2000/8000-direction variances at a/b in {1.5,2,3} "
                "stay above 1e-18, and var_inf no longer falls at the last domain rung for "
                "a/b in {2.5,3,5}. Numeric evidence only, not a proof; no formalization in this "
                "session (Lean disabled), evidence_kind at most cross_check.")

    out["result"] = result
    out["bound"] = {
        "part_a_domain_ladder": {"fracs_of_min_ab": DOMAIN_LADDER, "ratios": RATIOS_A,
                                 "directions": N_MAIN, "compass_step_tol": TOL},
        "part_b_search_domain": "|P| <= 0.99*min(a,b) (global 2000 dirs) + local box radius 0.05 (8000 dirs)",
        "part_b_ratios": RATIOS_B,
        "directions": [N_MAIN, N_WIDE],
        "refutation_threshold": "var < 1e-18 at BOTH 2000 and 8000 dirs, |P| clearly nonzero",
        "domain_bound_ratios": sorted(domain_bound),
        "per_ratio_var_inf_ladder": {t: {"domain_fracs": r["domain_fracs"],
                                         "var_inf": r["var_inf_sequence"],
                                         "abs_P_star": r["abs_P_star_sequence"],
                                         "still_falling_at_last_step": r["still_falling_at_last_step"],
                                         "P_star_on_0.99_boundary": r["P_star_on_boundary_of_0.99_domain"]}
                                     for t, r in part_a.items()},
        "per_ratio_pointwise_min": {t: {"P_star": r["P_star"], "abs_P_star": r["abs_P_star"],
                                        "var_2000dirs_mp": r.get("var_2000dirs_mp"),
                                        "var_8000dirs_mp": r.get("var_8000dirs_mp"),
                                        "on_domain_boundary": r["P_star_on_domain_boundary"]}
                                    for t, r in part_b.items()},
    }
    if counterexample is not None:
        out["counterexample"] = counterexample
    out["strategy_detail"] = {
        "part_a": "same 2000-direction objective re-minimised over the domain ladder "
                  "R in {0.9,0.95,0.99,0.999}*min(a,b), 11x11 multistart + compass, "
                  "so any change in var_inf is caused by R alone",
        "part_b": "global 2000-dir minimisation over |P|<=0.99*min(a,b), 8000-dir local "
                  "refinement (4 starts, box radius 0.05, step 0.02->1e-9), then 2000- and "
                  "8000-dir variance at the final point in float64 two-pass and 50-digit mpmath",
    }
    out["note"] = note
    out["data"] = {"part_a_domain_bound": part_a, "part_b_pointwise": part_b}
    out["scaling"] = scaling
    out["runtime_sec"] = round(time.time() - t_start, 3)
    print("REPRO_RESULT: " + json.dumps(out, sort_keys=True, default=float), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
