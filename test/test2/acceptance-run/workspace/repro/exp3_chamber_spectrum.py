#!/usr/bin/env python
"""
exp3_chamber_spectrum.py -- the spectrum of the chamber graph S~_m.

STATUS OF THIS CLAIM IN THE PAPER (this distinction is the whole point)
----------------------------------------------------------------------
  * Spec S~_m = [-m, m] for 3 <= m <= 5 is QUOTED, not proved: Remark 1.6
    (text:77-81) attributes it to the companion book [6, Thm. 6.5], whose
    bibliographic data the paper does not even give.  [6] is not available to
    us, so NOTHING here verifies it.  What we can do is build the cell of S~_m
    from Definition 1.2 alone and SEARCH FOR COUNTEREXAMPLES inside it.
  * m >= 6: the paper leaves the equality OPEN (text:407-417); only the
    inclusion into [-m,m] and the endpoints +-m are proved there.  We sample
    m = 6 as a counterexample search and draw NO conclusion.  The paper's stated
    obstruction -- "one must show that two branches meet, with no explicit
    witness available" -- is not addressed by sampling, and we do not pretend
    otherwise.

MY OWN DERIVATION OF THE CELL AND ITS FLOQUET MATRIX (not from any distributed
code; the paper's code/ directory was not distributed)
------------------------------------------------------
The translation lattice acts by LEFT translation, mu . (w, lam) = (w, lam + mu)
(text:61-63), so the cell is W_a/Q^v ~= S_m with m! vertices indexed by the
permutation part w.  Right multiplication by a generator s = (s_w, lam_s) is

    (w, lam) . s = (w s_w, lam + w(lam_s)),

so it takes the class w to the class w s_w, and the translation REALISING that
transition is w(lam_s) -- it depends on the source class, not only on the
target.  Definition 2.4 (text:164-172) defines the Floquet entry as the sum of
chi(lam) over all adjacencies realising the class transition, and Remark 2.6
(text:197-201) says parallel edges are summed.  Hence

    A_chi(w, w . s_w) += chi( w(lam_s) )     for every generator s,

with chi(lam) = exp(2 pi i <z, (lam_1,...,lam_{m-1})>), z in [0,1)^{m-1}.
Internally this is checked by Hermiticity plus the chi = 1 identity.

Negative control: transpose_voltage -- use chi(lam_s) instead of chi(w(lam_s));
the matrix stops being Hermitian and the 1e-12 gate catches it.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np

sys.path.insert(0, ".")
import repro_common as rc
from repro_result import Budget, Checks, emit, guard

BUGS = ("transpose_voltage",)
TOL = 1e-9
#: exp3 is the only experiment whose m = 6 block is genuinely expensive (the cell
#: is 720x720 and one eigvalsh costs ~0.27 s), so its default budget is larger.
#: It still cannot hang: on expiry it stops and reports INCONCLUSIVE.
DEFAULT_MAX_SECONDS = 300.0
#: word-metric ball sizes |B_3| of {s_0,...,s_{m-1}}; verified by this module
#: (build_w_ball) for m = 3..7.  A dropped translation in s_0 makes the group
#: finite and collapses this number, which is how wrong_s0 is caught by name.
#: 本脚本验证的**论文命题原文**（`E-9`）：与 `run_acceptance.py` 的 P5 计划表
#: 逐字相同，由 P5 的 `_paper_declaration_audit()` 交叉核对。
#: 为什么要写在这里：脚本自报的 `supports` 需要有一个**外部锚** —— 否则
#: 『论文声称 vs 独立计算』就只剩脚本自己作证。
PAPER_CLAIM = 'Spec S̃_m 的区间填充性（3≤m≤5 数值旁证；m=6 公开问题）'

EXPECT_BALL3 = {3: 19, 4: 35, 5: 56, 6: 84}
GRID_POINTS = {3: 12, 4: 8, 5: 5, 6: 3}      # points per angle (recorded in JSON)
GAP_THRESHOLD = {3: 0.05, 4: 0.05, 5: 0.05, 6: 0.02}
PATH_STEPS = {3: 200, 4: 150, 5: 80, 6: 12}
PATH_RAYS = {3: 6, 4: 5, 5: 4, 6: 3}
TIME_BUDGET_S = 300.0
QUOTED_RANGE = (3, 4, 5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--inject-bug", default=None, choices=list(BUGS))
    ap.add_argument("--m", default="3,4,5")
    ap.add_argument("--m-open", default="6")
    ap.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS,
                    help="hard wall-clock budget; on expiry the run stops and "
                         "reports ALL CHECKS INCONCLUSIVE instead of hanging")
    args = ap.parse_args()
    budget = Budget(args.max_seconds, "exp3")
    ms = [int(t) for t in args.m.split(",") if t.strip()]
    ms_open = [int(t) for t in args.m_open.split(",") if t.strip()]
    bug = args.inject_bug
    tv = (bug == "transpose_voltage")

    C = Checks()
    C.observe("max_seconds", args.max_seconds)
    C.observe("script", "exp3_chamber_spectrum.py")
    C.observe("paper_claims", {
        "quoted_theorem": "Remark 1.6 (text:77-81): Spec S~_m = [-m,m] is quoted "
                          "from the companion book [6, Thm. 6.5], proved there "
                          "for 3 <= m <= 5",
        "open_problem": "for m >= 6 only the inclusion into [-m,m] and the two "
                        "endpoints +-m are proved there; the equality is open "
                        "(text:407-417)",
        "proved_in_this_paper": False,
        "source_available_to_us": False,
        "obstruction_not_addressed": "the paper says one must show that two "
                                     "eigenvalue branches MEET, with no explicit "
                                     "witness available; sampling cannot show it",
        "our_role": "counterexample search in the cell ONLY; a failure to find a "
                    "counterexample is not a proof of the quoted theorem",
    })
    C.observe("independently_verified", False)
    C.observe("injected_bug", bug)
    if bug:
        C.note("NEGATIVE CONTROL ACTIVE: %s" % bug)

    kernel = lambda mm, z, **extra: rc.stilde_floquet(mm, z,
                                                     transpose_voltage=tv, **extra)

    # ------------------------------------------------------------------
    # independent sanity of the cell construction (before any spectrum)
    # ------------------------------------------------------------------
    wd = rc.stilde_voltage_is_well_defined(4)
    C.check("cell.voltage_well_defined", wd["ok"],
            "replacing a class representative (w,lam) by (w,lam+mu) keeps the "
            "target class and shifts the voltage by exactly mu (%d trials); "
            "witness %s" % (wd["trials"], wd["witness"]))
    deg4 = rc.stilde_degree(4)
    C.check("cell.degree_is_m", deg4["regular"] and deg4["degree"] == 4,
            "every class of W_a/Q^v has %s outgoing Cayley edges (s_w != 1 for "
            "every generator, so no self-loops)" % deg4["degree"])
    C.observe("cell_degree_m4", deg4)

    per_m = {}
    for m in ms:
        if budget.mark_if_expired(C, "start of m=%d" % m):
            break
        t0 = time.time()
        rec = {"m": m, "status": "quoted_from_[6]_Thm_6.5" if m in QUOTED_RANGE
               else "cross_checked", "npts": GRID_POINTS.get(m),
               "time_budget_seconds": TIME_BUDGET_S}

        # (a) the cell itself: m! vertices, one class per permutation
        reps = rc.stilde_class_representatives(m)
        deg = rc.stilde_degree(m)
        ball3 = rc.build_w_ball(m, 3)
        rec["cell_vertices"] = len(reps)
        rec["cell_degree"] = deg
        rec["ball3_size"] = ball3["size"]
        C.check("m%d.cell_has_m_factorial_vertices" % m,
                len(reps) == math.factorial(m),
                "the cell W_a/Q^v has %d vertices = %d! (paper section 6, "
                "text:414)" % (len(reps), m))
        C.check("m%d.cell_is_m_regular" % m,
                bool(deg["regular"]) and deg["degree"] == m,
                "cell degree %s" % deg["degree"])
        C.check("m%d.word_metric_ball_size_matches_definition" % m,
                ball3["size"] == EXPECT_BALL3[m],
                "|B_3| in the word metric of {s_0..s_{m-1}} = %d, expected %d; a "
                "dropped translation in s_0 or a non-associative group law "
                "changes this number (it is how wrong_s0 is detected in exp2)"
                % (ball3["size"], EXPECT_BALL3[m]))

        # (b) Hermiticity gate
        zs_probe = np.vstack([rc.grid_z(m, 3), rc.random_z(m, 25, seed=7 + m)])
        herm = [rc.hermiticity_defect(rc.stilde_floquet(m, z, transpose_voltage=tv))
                for z in zs_probe]
        worst_herm = float(max(herm))
        rec["hermiticity"] = {"n_characters": len(zs_probe),
                              "worst_defect": worst_herm, "gate": rc.TOL_HERM}
        C.check("m%d.Hermiticity_gate" % m, worst_herm < rc.TOL_HERM,
                "max ||A_chi - A_chi^H|| over %d characters = %.3e (gate %.0e); "
                "the voltage chi(w(lam_s)) makes A_chi Hermitian, dropping the "
                "'w .' does not" % (len(zs_probe), worst_herm, rc.TOL_HERM))

        # (c) identity character: the genuine adjacency matrix of the cell
        A1 = kernel(m, np.zeros(m - 1))
        ev1 = np.linalg.eigvalsh(A1)
        rec["identity_character"] = {
            "hermiticity_defect": rc.hermiticity_defect(A1),
            "lambda_max": float(ev1.max()), "lambda_min": float(ev1.min()),
            "n_cell_vertices": int(A1.shape[0]),
        }
        C.check("m%d.identity_char_extremes_are_pm_m" % m,
                abs(ev1.max() - m) <= 1e-9 and abs(ev1.min() + m) <= 1e-9,
                "at chi = 1 (the %d x %d adjacency matrix of the S_m-Cayley "
                "cell) eigenvalues run %.9f .. %.9f, expected -%d .. %d"
                % (A1.shape[0], A1.shape[0], ev1.min(), ev1.max(), m, m))

        # (d) sampled union over the character grid
        npts = GRID_POINTS.get(m, 3)
        zs = rc.grid_z(m, npts)
        t_grid = time.time()
        vals = []
        for z in zs:
            vals.extend(np.linalg.eigvalsh(kernel(m, z)))
        vals = np.array(vals)
        grid_seconds = time.time() - t_grid
        contained = bool(vals.max() <= m + TOL and vals.min() >= -m - TOL)
        gap, nsamp = rc.max_gap(vals, -float(m), float(m))
        rel = gap / (2.0 * m)
        min_abs = float(np.min(np.abs(vals)))
        rec["grid_sampling"] = {
            "grid_points_per_angle": npts, "grid_total": int(len(zs)),
            "n_eigenvalues": int(nsamp), "seconds": round(grid_seconds, 2),
            "min": float(vals.min()), "max": float(vals.max()),
            "min_abs_eigenvalue": min_abs,
            "contained_in_interval": contained,
            "endpoint_plus_m_reached": bool(vals.max() >= m - TOL),
            "endpoint_minus_m_reached": bool(vals.min() <= -m + TOL),
            "max_gap": gap, "max_gap_relative": rel,
        }
        C.check("m%d.no_counterexample_leaves_interval" % m, contained,
                "%d sampled eigenvalues over a %d-point-per-angle grid lie in "
                "[%.9f, %.9f] vs [-%d, %d] -- no counterexample to the inclusion; "
                "this does NOT verify the quoted equality"
                % (nsamp, npts, vals.min(), vals.max(), m, m))
        C.check("m%d.endpoints_attained" % m,
                vals.max() >= m - TOL and vals.min() <= -m + TOL,
                "the sampled union attains +%d and -%d" % (m, m))
        # "the two branches meet" needs a minimum |lambda| near 0, but WHERE they
        # meet is a single character, so a finite sample may simply miss it.  The
        # threshold is deliberately coarse and the exact value is reported.
        C.check("m%d.branches_meet_min_abs_is_small" % m, min_abs <= 0.05 * m,
                "min |lambda| over the sample = %.4e (coarse threshold 0.05*m = "
                "%.3f); with only %d grid characters this is a weak signal -- a "
                "single generic character already gives min|lambda| ~ 0 because "
                "the two branches cross somewhere" % (min_abs, 0.05 * m, len(zs)))

        thr = GAP_THRESHOLD.get(m, 0.05)
        ok_gap = rel <= thr
        if m in QUOTED_RANGE:
            C.check("m%d.sampled_union_fills_interval" % m, ok_gap,
                    "max gap of the sampled union over [-%d,%d] is %.5f (%.2f%% "
                    "of the interval; threshold %.2f%%) with %d samples"
                    % (m, m, gap, 100 * rel, 100 * thr, nsamp))

        # (e) continuous paths
        targets = [np.array([0.5] + [i / float(m - 2) for i in range(m - 2)])]
        for k in range(PATH_RAYS.get(m, 3) - 1):
            targets.append(np.array([((k + 1) * 0.13 + 0.37 * i) % 1.0
                                     for i in range(m - 1)]))
        worst_jump = worst_mat = 0.0
        path_union = []
        rays = []
        t_path = time.time()
        for tgt in targets:
            pt = rc.path_eigenvalue_tracking(m, np.zeros(m - 1), tgt,
                                             PATH_STEPS.get(m, 30), rc.stilde_floquet,
                                             transpose_voltage=tv)
            worst_jump = max(worst_jump, pt["max_step_jump"])
            worst_mat = max(worst_mat, pt["max_matrix_step"])
            path_union.append(pt["values"])
            rays.append({"target": [round(float(t), 6) for t in tgt],
                         "max_step_jump": round(pt["max_step_jump"], 6),
                         "max_matrix_step": round(pt["max_matrix_step"], 6),
                         "branches_consistent": pt["matching_of_branches_is_consistent"]})
        path_seconds = time.time() - t_path
        path_union = np.concatenate(path_union)
        pgap, pn = rc.max_gap(path_union, -float(m), float(m))
        prel = pgap / (2.0 * m)
        rec["continuous_paths"] = {
            "n_rays": len(rays), "steps_per_ray": PATH_STEPS.get(m, 30),
            "n_eigenvalues": int(pn), "seconds": round(path_seconds, 2),
            "worst_step_jump": worst_jump, "worst_matrix_step": worst_mat,
            "all_branches_consistent": all(r["branches_consistent"] for r in rays),
            "max_gap": pgap, "max_gap_relative": prel, "rays": rays,
        }
        C.check("m%d.path_branch_matching_is_lipschitz" % m,
                all(r["branches_consistent"] for r in rays),
                "the largest per-step change of the sorted eigenvalue list "
                "(%.3e) does not exceed the largest matrix step (%.3e) "
                "(Weyl's inequality), so the branch matching along the paths is "
                "genuine and the eigenvalues do follow continuous curves"
                % (worst_jump, worst_mat))
        C.check("m%d.path_stays_in_interval" % m,
                bool(np.max(np.abs(path_union)) <= m + TOL),
                "over %d path eigenvalues: max |lambda| = %.6f <= %d"
                % (pn, float(np.max(np.abs(path_union))), m))
        if m in QUOTED_RANGE:
            C.check("m%d.path_sweeps_interval" % m, prel <= thr,
                    "%d path eigenvalues sweep [-%d,%d] with maximum gap %.5f "
                    "(%.2f%% of the interval; %.1fs)"
                    % (pn, m, m, pgap, 100 * prel, path_seconds))

        # (f) independent numerical route on a small case
        if m <= 4:
            A = kernel(m, np.full(m - 1, 0.1))
            e1 = np.sort(np.linalg.eigvalsh(A))
            e2 = np.sort(rc.real_form_eigvals(A))[::2]
            dev = float(np.abs(e1 - e2).max()) if e2.size == e1.size else float("inf")
            rec["real_form_cross_check"] = {"max_abs_deviation": dev}
            C.check("m%d.real_symmetric_form_agrees" % m, dev <= 1e-9,
                    "eigvalsh vs the real symmetric 2n x 2n route at z = 0.1: max "
                    "deviation %.3e" % dev)

        rec["seconds"] = round(time.time() - t0, 2)
        if rec["seconds"] > TIME_BUDGET_S:
            C.note("m=%d took %.1fs, above the %.0fs budget"
                   % (m, rec["seconds"], TIME_BUDGET_S))
        per_m["m%d" % m] = rec

    # ------------------------------------------------------------------
    # the OPEN case m >= 6 -- reported, never asserted
    # ------------------------------------------------------------------
    for m in ms_open:
        if budget.mark_if_expired(C, "start of open case m=%d" % m):
            break
        t0 = time.time()
        npts = GRID_POINTS.get(m, 3)
        # Scale the grid down if the remaining budget cannot afford it: one
        # 720x720 eigvalsh costs ~0.3 s, and the resolution is reported either
        # way.  This is what keeps the script from ever exceeding its budget.
        while npts > 2 and budget.elapsed + 0.45 * (npts ** (m - 1)) > budget.seconds:
            npts -= 1
            C.note("m=%d grid reduced to %d points per angle to stay inside the "
                   "%.0fs budget" % (m, npts, budget.seconds))
        zs = rc.grid_z(m, npts)
        vals = []
        t_grid = time.time()
        for z in zs:
            vals.extend(np.linalg.eigvalsh(kernel(m, z)))
        vals = np.array(vals)
        grid_seconds = time.time() - t_grid
        gap, nsamp = rc.max_gap(vals, -float(m), float(m))
        rel = gap / (2.0 * m)
        contained = bool(vals.max() <= m + TOL and vals.min() >= -m - TOL)
        # continuous paths
        targets = [np.array([0.5] + [i / float(m - 2) for i in range(m - 2)])]
        for k in range(PATH_RAYS.get(m, 3) - 1):
            targets.append(np.array([((k + 1) * 0.13 + 0.37 * i) % 1.0
                                     for i in range(m - 1)]))
        worst_jump = worst_mat = 0.0
        path_union = []
        for tgt in targets:
            pt = rc.path_eigenvalue_tracking(m, np.zeros(m - 1), tgt,
                                             PATH_STEPS.get(m, 30), rc.stilde_floquet,
                                             transpose_voltage=tv)
            worst_jump = max(worst_jump, pt["max_step_jump"])
            worst_mat = max(worst_mat, pt["max_matrix_step"])
            path_union.append(pt["values"])
        path_union = np.concatenate(path_union)
        pgap, pn = rc.max_gap(path_union, -float(m), float(m))
        prel = pgap / (2.0 * m)
        secs = time.time() - t0
        C.observe("open_case_m%d" % m, {
            "status": "OPEN QUESTION IN THE PAPER (Remark 1.6, text:407-417)",
            "grid_points_per_angle": npts, "grid_characters": int(len(zs)),
            "n_eigenvalues": int(nsamp),
            "max_gap": gap, "max_gap_relative": rel,
            "path_rays": len(targets), "path_steps": PATH_STEPS.get(m, 30),
            "path_max_gap": pgap, "path_max_gap_relative": prel,
            "path_worst_step_jump": worst_jump,
            "path_worst_matrix_step": worst_mat,
            "contained_in_interval": contained,
            "seconds": round(secs, 2),
            "resolution_sufficient": bool(rel <= GAP_THRESHOLD.get(m, 0.02)),
            "resolves_the_obstruction": False,
            "conclusion": "NONE. The sample is consistent with Spec S~_m = "
                          "[-m,m], but coverage of an interval by a finite sample "
                          "is not the equality, and in particular it does not "
                          "show that the two eigenvalue branches MEET -- the "
                          "obstruction the paper identifies. No claim is made.",
        })
        C.check("m%d.open_case_no_counterexample_in_sample" % m, contained,
                "m = %d is OPEN in the paper; %d characters (grid %d/angle) give "
                "eigenvalues in [%.6f, %.6f] and %d path eigenvalues, so this "
                "sample contains no counterexample to the inclusion. No "
                "conclusion beyond that is drawn."
                % (m, len(zs), npts, vals.min(), vals.max(), pn))
        C.check_maybe("m%d.open_case_sample_resolution_is_sufficient" % m,
                      rel <= GAP_THRESHOLD.get(m, 0.02),
                      "m = %d: the %d-character grid leaves a maximum gap of "
                      "%.5f (%.2f%% of the interval) and the %d path eigenvalues "
                      "leave %.5f (%.2f%%); %.1fs. Even if this passes, it does "
                      "not determine coverage of the interval by the true "
                      "spectrum, and it does NOT address the paper's obstruction "
                      "('two branches must meet, with no explicit witness'). "
                      "Marked undecided when the 2%% threshold is missed."
                      % (m, len(zs), gap, 100 * rel, pn, pgap, 100 * prel, secs))
        per_m["m%d" % m] = {"m": m, "status": "open_case", "seconds": round(secs, 2),
                            "max_gap_relative": rel, "path_max_gap_relative": prel}

    C.observe("per_m", per_m)
    C.observe("what_this_cannot_show", [
        "Spec S~_m = [-m,m] for 3 <= m <= 5 is a QUOTED theorem ([6, Thm. 6.5], "
        "not distributed and not fully cited); we only fail to find a "
        "counterexample inside the cell.",
        "For m >= 6 the equality is an open problem in the paper itself: our "
        "numerics are consistent with it but establish neither the equality nor "
        "the meeting of the two eigenvalue branches.",
        "Every number here is a cross_check, never a proof.",
    ])
    if bug:
        C.observe("transpose_voltage_control", {
            "what": "chi(lam_s) instead of chi(w(lam_s)) in the Floquet entry",
            "why_wrong": "the translation realising w -> w s_w is w(lam_s), which "
                         "depends on the source class w; dropping the 'w .' makes "
                         "A_chi non-Hermitian",
            "caught_by": "the Hermiticity gate ||A - A^H|| < 1e-12",
        })

    return emit(C.result_dict(), args.json)


if __name__ == "__main__":
    guard(main)
