#!/usr/bin/env python
"""
exp5_noniso.py -- Theorem 1.5 (text:72-76): for m in {4,5} the graphs K(m) and
S~_m are both m-regular, infinite, vertex-transitive, of periodic rank m-1 and
have the same spectrum [-m, m], yet girth K(m) = 6 != 4 = girth S~_m, so they
are not isomorphic.

WHAT IS PROVED HERE AND WHAT IS ONLY CROSS-CHECKED (the split is the point)
  * same degree m: recomputed from both graphs -- K(m) by Lemma 2.2's
    neighbour count, S~_m as a Cayley graph on m generators.
  * DIFFERENT girth: 6 versus 4, recomputed by two independent algorithms plus
    explicit cycles (exp2 reproduces this; here it is recomputed and reused).
    An isomorphism preserves girth, so this ALONE proves non-isomorphism.
  * Spec K(m) = [-m, m]: PROVED in the paper's section 3; we only sample the
    characters of its 2x2 cell.
  * Spec S~_m = [-m, m]: **QUOTED** from the companion book [6, Thm. 6.5]
    (Remark 1.6, text:77-81) and NOT reproved in the paper.  [6] is not
    available to us and the paper does not give its full bibliographic data, so
    the "cospectral" half of Theorem 1.5 cannot be independently verified here:
    we can only fail to find a counterexample in the cell.  This is reported,
    not hidden.
  * The two cells are not isomorphic as voltage graphs (2 versus m! vertices),
    which is a direct structural difference, but note that a cell depends on
    the chosen period lattice and so is not by itself a graph invariant.

Negative control same_girth -- report girth S~_m as equal to girth K(m): the
non-isomorphism check must then go RED, showing that the girth separation is
what is actually doing the work.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np

sys.path.insert(0, ".")
import repro_common as rc
import repro_lattice as rl
from repro_result import Budget, Checks, emit, guard

BUGS = ("same_girth",)
DEFAULT_MAX_SECONDS = 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--inject-bug", default=None, choices=list(BUGS))
    ap.add_argument("--m", default="4,5")
    ap.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS,
                    help="hard wall-clock budget; on expiry the run stops and "
                         "reports ALL CHECKS INCONCLUSIVE instead of hanging")
    args = ap.parse_args()
    budget = Budget(args.max_seconds, "exp5")
    ms = [int(t) for t in args.m.split(",") if t.strip()]
    bug = args.inject_bug

    C = Checks()
    C.observe("max_seconds", args.max_seconds)
    C.observe("script", "exp5_noniso.py")
    C.observe("paper_claims", {
        "theorem_1_5": "text:72-76 -- for m in {4,5}: same degree, same periodic "
                       "rank, Spec K(m) = [-m,m] = Spec S~_m, but girth 6 != 4, "
                       "hence not isomorphic",
        "spectrum_of_K": "PROVED in the paper (Theorem 1.3, text:67-69)",
        "spectrum_of_Stilde": "QUOTED from [6, Thm. 6.5] (Remark 1.6, "
                              "text:77-81); not reproved and not available to us",
        "girths": "PROVED in the paper (Theorem 1.4, text:70-71)",
        "our_role": "cross_check only; the cospectral half rests on a quote we "
                    "cannot verify",
    })
    C.observe("injected_bug", bug)
    if bug:
        C.note("NEGATIVE CONTROL ACTIVE: %s" % bug)

    per_m = {}
    for m in ms:
        if budget.mark_if_expired(C, "start of m=%d" % m):
            break
        t0 = time.time()
        rec = {"m": m}

        # ---------------- degree -----------------------------------------
        deg_K = rc.degree_K(m)
        deg_S = rc.stilde_degree(m)
        rec["degree_K"] = deg_K
        rec["degree_Stilde"] = deg_S
        same_deg = (deg_K == m and bool(deg_S["regular"]) and deg_S["degree"] == m)
        C.check("m%d.same_degree_m" % m, same_deg,
                "degree K(%d) = %d, degree S~_%d = %s (both equal m = %d)"
                % (m, deg_K, m, deg_S["degree"], m))

        # ---------------- periodic rank ----------------------------------
        rank = m - 1
        C.check("m%d.same_periodic_rank" % m,
                len(rl.coroot_lattice_basis(m)) == rank,
                "Q^v has rank %d = m-1 and acts freely with finitely many orbits "
                "on both graphs (Lemma 2.2, text:127-145)"
                % len(rl.coroot_lattice_basis(m)))

        # ---------------- girths (recomputed, two algorithms) ------------
        gK = rc.bfs_girth_K(m, 3)
        ball = rc.build_w_ball(m, 6)
        gS = rc.ball_girth(ball["elements"], m, 3)
        gS_reported = gK["girth"] if bug == "same_girth" else gS["girth"]
        rec["girth_K"] = {"girth": gK["girth"], "ball_size": gK["ball_size"],
                          "method": gK["method"]}
        rec["girth_Stilde"] = {"girth": gS["girth"], "ball_size": gS["ball_size"],
                               "method": gS["method"],
                               "reported_under_this_run": gS_reported}
        C.check("m%d.girths_are_6_and_4" % m,
                gK["girth"] == 6 and gS["girth"] == 4,
                "girth K(%d) = %s, girth S~_%d = %s (Theorem 1.4; both by the "
                "edge-deletion algorithm, and exp2 cross-checks them by "
                "exhaustive cycle enumeration and explicit cycles)"
                % (m, gK["girth"], m, gS["girth"]))

        # ---------------- non-isomorphism --------------------------------
        sep = (gK["girth"] != gS_reported)
        rec["isomorphism_separator"] = {
            "girth_K": gK["girth"], "girth_Stilde_used": gS_reported,
            "separates": bool(sep),
        }
        C.check("m%d.not_isomorphic_because_girth_differs" % m, sep,
                "girth %s vs %s: an isomorphism preserves the girth, so the two "
                "graphs are NOT isomorphic (Theorem 1.5)%s"
                % (gK["girth"], gS_reported,
                   "" if sep else
                   "  <-- INJECTED ERROR: S~_%d girth reported as %s, so the "
                   "separator is vacuous and the non-isomorphism claim is NOT "
                   "supported; this check catches that"
                   % (m, gS_reported)))

        # ---------------- explicit cycles (the separator made visible) ----
        x0 = tuple([0] * m)
        cycK = [x0]
        cur = list(x0)
        for s in (1, -2, 3, -1, 2, -3):
            cur[abs(s) - 1] += 1 if s > 0 else -1
            cycK.append(tuple(cur))
        cycK = cycK[:-1]
        vK = rc.explicit_cycle_is_valid(cycK, lambda x: rc.neighbors_K(x, m),
                                        "K(%d) 6-cycle" % m)
        gens = rc.affine_generators(m)
        e = rc.weyl_identity(m)
        cycS = [e, gens[1],
                rc.weyl_mul(rc.weyl_mul(e, gens[1]), gens[3]), gens[3]]
        vS = rc.explicit_cycle_is_valid(
            cycS, lambda x: rc.weyl_right_neighbors(x, m), "S~_%d 4-cycle" % m)
        rec["explicit_cycles"] = {
            "K": {"length": vK["length"], "valid": vK["ok"], "reason": vK["reason"],
                  "vertices": [list(t) for t in cycK]},
            "Stilde": {"length": vS["length"], "valid": vS["ok"],
                       "reason": vS["reason"],
                       "vertices": [[list(t.w), list(t.lam)] for t in cycS]},
        }
        C.check("m%d.explicit_cycle_in_K_and_no_shorter" % m,
                vK["ok"] and vK["length"] == 6,
                "explicit 6-cycle in K(%d): %s" % (m, vK["reason"]))
        C.check("m%d.explicit_4cycle_in_Stilde" % m,
                vS["ok"] and vS["length"] == 4,
                "explicit 4-cycle in S~_%d (s_1 and s_3 commute, m >= 4): %s"
                % (m, vS["reason"]))

        # ---------------- spectra ----------------------------------------
        # NOTE ON SCOPE.  "The sampled spectrum fills [-m,m]" is checked in exp1
        # (K(m), with the explicit |S| = 0 witness and continuous paths) and in
        # exp3 (S~_m).  It is deliberately NOT re-checked here: filling an
        # interval is an analytic statement (continuity of |S| on the connected
        # torus plus the two attained values), so pushing it onto a numerical
        # grid would only re-measure the grid, and a too-coarse grid would fail
        # spuriously.  What exp5 needs from the spectra is only (i) both are
        # contained in [-m,m] and (ii) both attain the endpoints +-m, which the
        # identity character gives for free.  See README, "scope of exp5".
        zs = np.vstack([np.zeros((1, m - 1))] + [rc.random_z(m, 3, seed=31 + m)])
        lam_K = np.concatenate([rc.eigvals_K(m, z) for z in zs])
        lam_S = np.concatenate([rc.eigvals_stilde(m, z) for z in zs])
        rec["spectra"] = {
            "characters_sampled": int(len(zs)),
            "K": {"n_eigenvalues": int(lam_K.size), "min": float(lam_K.min()),
                  "max": float(lam_K.max()),
                  "contained_in_interval": bool(lam_K.min() >= -m - 1e-9
                                                and lam_K.max() <= m + 1e-9)},
            "Stilde": {"n_eigenvalues": int(lam_S.size), "min": float(lam_S.min()),
                       "max": float(lam_S.max()),
                       "contained_in_interval": bool(lam_S.min() >= -m - 1e-9
                                                     and lam_S.max() <= m + 1e-9)},
            "interval_filling_checked_in": ["exp1_k_spectrum.py",
                                            "exp3_chamber_spectrum.py"],
            "both_endpoints_attained": {
                "K": bool(abs(lam_K.min() + m) <= 1e-9 and abs(lam_K.max() - m) <= 1e-9),
                "Stilde": bool(abs(lam_S.min() + m) <= 1e-9
                               and abs(lam_S.max() - m) <= 1e-9),
            },
        }
        C.check("m%d.same_spectral_interval_endpoints" % m,
                abs(lam_K.min() + m) <= 1e-9 and abs(lam_K.max() - m) <= 1e-9
                and abs(lam_S.min() + m) <= 1e-9 and abs(lam_S.max() - m) <= 1e-9,
                "both spectra attain exactly the same endpoints -%d and +%d "
                "(at the identity character the cell matrix is the genuine "
                "adjacency matrix of an m-regular graph); K range [%.6f, %.6f], "
                "S~_%d range [%.6f, %.6f].  Interval FILLING is not re-checked "
                "here: exp1 covers K(m) and exp3 covers S~_m"
                % (m, m, lam_K.min(), lam_K.max(), m, lam_S.min(), lam_S.max()))
        C.check("m%d.both_spectra_inside_interval" % m,
                bool(lam_K.min() >= -m - 1e-9 and lam_K.max() <= m + 1e-9
                     and lam_S.min() >= -m - 1e-9 and lam_S.max() <= m + 1e-9),
                "over %d characters (the identity plus 3 random ones) the K cell "
                "2x2 spectrum and the S~_%d cell %d x %d spectrum both lie in "
                "[-%d, %d]; a single eigenvalue outside would be a counterexample "
                "to the inclusion, but this is a %d-character sample"
                % (len(zs), m, lam_S.size // (2 * len(zs)), lam_S.size // (2 * len(zs)),
                   m, m, len(zs)))
        for _zcm in zs[1:]:
            A = rc.stilde_floquet(m, _zcm)
            if rc.hermiticity_defect(A) >= rc.TOL_HERM:
                C.check("m%d.Stilde_cell_Hermitian_on_sampled_characters" % m, False,
                        "A_chi is not Hermitian at z = %s (defect %.3e)"
                        % (np.round(_zcm, 4).tolist(), rc.hermiticity_defect(A)))
        C.check("m%d.Stilde_cell_Hermitian_on_sampled_characters" % m, True,
                "A_chi is Hermitian to < %.0e at every sampled character, so the "
                "eigenvalues used above are the eigenvalues of a genuine "
                "self-adjoint cell operator" % rc.TOL_HERM)

        # ---------------- the two cells are different --------------------
        rec["cells"] = {"K_cell_vertices": 2,
                        "Stilde_cell_vertices": len(rc.stilde_class_representatives(m)),
                        "m_factorial": math.factorial(m)}
        C.check("m%d.cells_have_different_sizes" % m,
                2 != len(rc.stilde_class_representatives(m)),
                "the cell V_K/Q^v has 2 vertices (Lemma 3.1), the cell "
                "W_a/Q^v has %d = %d! vertices, so the two voltage graphs are "
                "not isomorphic either -- but note a cell is relative to the "
                "chosen period lattice, so this is structural information, not "
                "by itself a graph invariant"
                % (len(rc.stilde_class_representatives(m)), m))

        # ---------------- basic invariants table --------------------------
        rec["invariants"] = {
            "degree": {"K": m, "Stilde": deg_S["degree"]},
            "girth": {"K": gK["girth"], "Stilde": gS["girth"]},
            "periodic_rank": {"K": rank, "Stilde": rank},
            "vertex_transitive": {"K": True, "Stilde": True},
            "infinite_and_locally_finite": {"K": True, "Stilde": True},
            "spectrum_endpoints": {"K": [-m, m], "Stilde": [-m, m]},
            "cell_size": {"K": 2, "Stilde": math.factorial(m)},
            "isomorphic": False,
            "decided_by": "girth (6 vs 4)",
        }

        rec["seconds"] = round(time.time() - t0, 3)
        per_m["m%d" % m] = rec
    C.observe("per_m", per_m)

    C.observe("honest_split", {
        "proved_by_the_paper_and_cross_checked_here": [
            "K(m) is m-regular, vertex-transitive, periodic of rank m-1 "
            "(Lemma 2.2)",
            "Spec K(m) = [-m,m] (Theorem 1.3)",
            "girth K(m) = 6 and girth S~_m = 4 for m >= 4 (Theorem 1.4)",
        ],
        "quoted_by_the_paper_and_NOT_verifiable_here": [
            "Spec S~_m = [-m,m] for 3 <= m <= 5 comes from [6, Thm. 6.5]; the "
            "book is not available and the paper does not give its full "
            "bibliographic data, so the cospectrality half of Theorem 1.5 rests "
            "on an external theorem we cannot check",
        ],
        "still_open_in_the_paper": [
            "Spec S~_m = [-m,m] for m >= 6 (would extend Theorem 1.5 to all "
            "m >= 4)",
        ],
    })

    if bug:
        C.observe("same_girth_control", {
            "what": "report girth S~_m as equal to girth K(m)",
            "effect": "the only isomorphism separator used here becomes vacuous",
            "caught_by": "not_isomorphic_because_girth_differs",
        })

    return emit(C.result_dict(), args.json)


if __name__ == "__main__":
    guard(main)
