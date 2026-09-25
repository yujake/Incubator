#!/usr/bin/env python
"""
exp1_k_spectrum.py -- Theorem 1.3:  Spec K(m) = [-m, m]   (text:67-69, 278-299)

Numerical cross-checks (never a proof):
 (a) identity character: the Floquet matrix at z = 0 is the genuine adjacency
     matrix of the cell, so lambda_max must be exactly +m -- the degree, by
     Lemma 2.2 (text:138-142).
 (b) grid + random sampling of characters: every sampled eigenvalue must lie in
     [-m, m] to 1e-9.
 (c) EXPLICIT witness for S = 0 (not a grid search): text:293-296 gives
     m = 3: z = (1/3, 2/3)
     m >= 4: z_1 = 1/2 and z_2..z_{m-1} the (m-2)-th roots of unity.
     Assert |S| < 1e-12.
 (d) continuous path from z = 0 (|S| = m) to the witness (|S| = 0): sampled
     |S| values must cover [0, m] with a small maximum gap -- the numerical
     shadow of the connectedness argument of text:297-298.
 (e) negative control coarse_grid: reproduce Remark 3.3 (text:305-310), the
     trap that a coarse character grid misses |S| = 0.  Diagnostic: report the
     coarse-grid minimum and compare with the algebraic witness.
 (f) negative control double_count: reproduce Remark 3.5 (text:315-320), the
     edge-count error giving S(1) = 2m-1 and lambda_max = 2m-1 != m.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
import repro_common as rc
from repro_result import Checks, emit, guard

BUGS = ("coarse_grid", "double_count")
GRID_POINTS = {3: 40, 4: 25, 5: 16}      # points per angle; recorded in the JSON
FINE_POINTS = {4: 200, 5: 60}            # reference grid for the coarse-grid diagnostic
MAX_GAP_REL = 0.05                       # 5% of the interval width 2m


def witness_z(m):
    """The paper's explicit witness of |S| = 0 (text:293-296), in the
    parameterisation z_i with chi(e_i) = exp(2 pi i z_i)."""
    if m == 2:
        return np.array([0.5])
    if m == 3:
        return np.array([1.0 / 3, 2.0 / 3])
    # z_1 = -1, and z_2..z_{m-1} run through all (m-2)-th roots of unity
    return np.array([0.5] + [i / float(m - 2) for i in range(m - 2)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--inject-bug", default=None, choices=list(BUGS))
    ap.add_argument("--m", default="3,4,5")
    args = ap.parse_args()
    ms = [int(t) for t in args.m.split(",") if t.strip()]
    bug = args.inject_bug
    if bug and bug not in BUGS:
        raise SystemExit("unknown bug")

    C = Checks()
    C.observe("script", "exp1_k_spectrum.py")
    C.observe("paper_claims", {
        "theorem": "Theorem 1.3 (text:67-69): Spec K(m) = [-m,m] for all m >= 3",
        "proved_in_paper": True,
        "our_role": "numerical cross-check only, no output is used as a proof",
    })
    C.observe("injected_bug", bug)
    if bug:
        C.note("NEGATIVE CONTROL ACTIVE: %s" % bug)

    per_m = {}
    for m in ms:
        t0 = time.time()
        rec = {"m": m}

        # ---------------- (a) identity character -------------------------
        A0 = rc.floquet_K(m, np.zeros(m - 1), double_count=(bug == "double_count"))
        ev0 = np.linalg.eigvalsh(A0)
        deg = rc.degree_K(m)
        rec["identity_character"] = {
            "S_at_z0": [float(A0[0, 1].real), float(A0[0, 1].imag)],
            "lambda_max": float(ev0.max()),
            "lambda_min": float(ev0.min()),
            "degree_from_adjacency": deg,
            "lambda_max_equals_degree": bool(abs(ev0.max() - m) <= 1e-12),
        }
        C.check("m%d.a.identity_char_lambda_max_is_degree" % m,
                abs(ev0.max() - m) <= 1e-12,
                "lambda_max = %.12f, degree m = %d, S(1) = %.1f%+.1fj"
                % (ev0.max(), m, A0[0, 1].real, A0[0, 1].imag))
        if bug == "double_count":
            C.check("m%d.f.lambda_max_catches_double_count" % m,
                    abs(ev0.max() - (2 * m - 1)) <= 1e-12 and abs(ev0.max() - m) > 1e-9,
                    "with the double-counted voltage S(1) = 2m-1 = %d and "
                    "lambda_max = %d != degree %d -- the comparison of "
                    "lambda_max with the degree catches it (Remark 3.5)"
                    % (2 * m - 1, round(ev0.max()), m))

        # ---------------- (b) sampled eigenvalues in [-m, m] -------------
        npts = GRID_POINTS.get(m, 12)
        zs = rc.grid_z(m, npts)
        extra = rc.random_z(m, 200, seed=1234 + m)
        samples = np.vstack([zs, extra])
        if bug == "double_count":
            vals = []
            for z in samples:
                vals.extend(np.linalg.eigvalsh(rc.floquet_K(m, z, double_count=True)))
            vals = np.array(vals)
        else:
            vals = np.concatenate([rc.eigvals_K(m, z) for z in samples])
        contained = bool(vals.max() <= m + 1e-9 and vals.min() >= -m - 1e-9)
        rec["sampling"] = {
            "grid_points_per_angle": npts,
            "grid_total": int(len(zs)),
            "random_extra": int(len(extra)),
            "n_eigenvalues_sampled": int(len(vals)),
            "min": float(vals.min()), "max": float(vals.max()),
            "contained_in_interval": contained,
        }
        C.check("m%d.b.sampled_eigenvalues_in_interval" % m, contained,
                "sampled %d eigenvalues, range [%.6f, %.6f] vs [-%d, %d]"
                % (len(vals), vals.min(), vals.max(), m, m))

        # ---------------- (c) explicit witness for |S| = 0 ---------------
        zw = witness_z(m)
        S = rc.S_value(m, zw)
        rec["witness_ABS_S_zero"] = {
            "z": [float(t) for t in zw], "S": [float(S.real), float(S.imag)],
            "abs_S": float(abs(S)),
        }
        C.check("m%d.c.explicit_witness_abs_S_zero" % m, abs(S) < 1e-12,
                "z = %s gives S = %.3e%+.3ej, |S| = %.3e"
                % (np.round(zw, 6).tolist(), S.real, S.imag, abs(S)))
        if bug == "coarse_grid":
            # ---- Remark 3.3 diagnostic, run as a WRONG check -------------
            ncoarse = 60
            off = 0.5 / ncoarse
            zg = rc.grid_z(m, ncoarse) + off
            coarse_min = float(np.abs(rc.S_grid(m, zg)).min())
            nfine = FINE_POINTS.get(m, 120)
            fine_min = float(np.abs(rc.S_grid(m, rc.grid_z(m, nfine))).min())
            rec["remark_3_3_diagnostic"] = {
                "coarse_points_per_angle": ncoarse,
                "coarse_grid_offset": off,
                "coarse_min_abs_S": coarse_min,
                "fine_points_per_angle": nfine,
                "fine_min_abs_S": fine_min,
                "witness_abs_S": float(abs(S)),
                "paper_value_quoted": 0.04,
                "reproduced": None,
            }
            thr = max(200.0 * fine_min, 1e-9)
            C.check("m%d.e.coarse_grid_finds_the_zero" % m, coarse_min <= thr,
                    "coarse %d-point grid (offset by half a step) gives min|S| = %.6f, "
                    "so the grid does NOT reach the algebraic witness |S| = %.3e; the "
                    "assumption under test was 'the coarse grid already resolves the "
                    "zero'.  Paper Remark 3.3 quotes about 0.04 for m = 4; our shifted "
                    "60-grid gives %.6f, while the unshifted natural grid j/60 gives 0.0 "
                    "because z = (0.4, 0.5, 0.9) is such a grid point -- so the quoted "
                    "0.04 depends on the grid convention and is NOT reproduced here."
                    % (ncoarse, coarse_min, abs(S), coarse_min))

        # ---------------- (d) continuous path ----------------------------
        paths = []
        targets = [zw]
        for k in range(6):
            t = np.array([(k + 1) / 7.0 + (i % 3) * 0.09 for i in range(m - 1)])
            targets.append(t % 1.0)
        nsteps = 400
        allvals = []
        worst_jump = 0.0
        worst_mat = 0.0
        for tgt in targets:
            pt = rc.path_eigenvalue_tracking(m, np.zeros(m - 1), tgt, nsteps,
                                             rc.floquet_K)
            allvals.append(pt["values"])
            worst_jump = max(worst_jump, pt["max_step_jump"])
            worst_mat = max(worst_mat, pt["max_matrix_step"])
            paths.append({
                "target": [round(float(t), 6) for t in tgt],
                "max_step_jump": round(pt["max_step_jump"], 6),
                "max_matrix_step": round(pt["max_matrix_step"], 6),
                "branches_consistent": pt["matching_of_branches_is_consistent"],
                "coverage_max_gap": pt["coverage"]["max_gap"],
            })
        allvals = np.concatenate(allvals)
        gap, nsamp = rc.max_gap(allvals, -float(m), float(m))
        rel = gap / (2.0 * m)
        rec["continuous_path"] = {
            "n_paths": len(targets),
            "steps_per_path": nsteps,
            "worst_sorted_step_jump": worst_jump,
            "worst_matrix_step_norm": worst_mat,
            "all_branches_consistent": all(p["branches_consistent"] for p in paths),
            "n_path_eigenvalues": int(nsamp),
            "max_gap": gap, "max_gap_relative": rel,
            "paths": paths,
        }
        C.check("m%d.d.path_branches_continuous" % m,
                all(p["branches_consistent"] for p in paths),
                "worst eigenvalue step %.3e <= worst matrix step %.3e along %d paths"
                % (worst_jump, worst_mat, len(targets)))
        C.check("m%d.d.path_sweeps_interval" % m, rel <= MAX_GAP_REL,
                "the %d path eigenvalues sweep [-%d,%d] with maximum gap %.5f "
                "(%.2f%% of the interval, threshold %.2f%%)"
                % (nsamp, m, m, gap, 100 * rel, 100 * MAX_GAP_REL))

        rec["seconds"] = round(time.time() - t0, 3)
        per_m["m%d" % m] = rec
    C.observe("per_m", per_m)

    # cross-check the arithmetic of 2m-1 for the double_count control
    if bug == "double_count":
        C.observe("remark_3_5", {
            "explanation": "each of the 2m directed steps +-e_i counted as its own "
                           "cell edge (text:315-320)",
            "S_at_identity": {str(m): 2 * m - 1 for m in ms},
            "lambda_max_observed": {str(m): float(rc.eigvals_K(m, np.zeros(m - 1),
                                                               double_count=True).max())
                                    for m in ms},
            "true_degree": {str(m): m for m in ms},
        })

    return emit(C.result_dict(), args.json)


if __name__ == "__main__":
    guard(main)
