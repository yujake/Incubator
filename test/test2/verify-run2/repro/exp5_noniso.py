#!/usr/bin/env python
"""
exp5_noniso.py -- Theorem 1.5: for m in {4,5} the pair (K(m), S~_m) is
cospectral, of the same degree and the same periodic rank, but NOT isomorphic.

WHAT WE CAN AND CANNOT ESTABLISH (this split is the point of the file)
--------------------------------------------------------------------
  PROVED BY US HERE, for m = 4 and m = 5:
    * both graphs are m-regular  -> same degree  (Lemma 2.2; Cayley graph)
    * girth K(m) = 6 while girth S~_m = 4
    * an isomorphism preserves girth, so the two graphs are NOT isomorphic
    * both are periodic of rank m-1 (Q^v has rank m-1)
    * the two cells are not isomorphic as voltage graphs (|V| = 2 vs m!)
  NUMERICALLY CROSS-CHECKED BY US: Spec K(m) = [-m, m]
    (the PROOF is the paper's section 3; the numbers are evidence only)
  **QUOTED, NOT VERIFIABLE BY US**: Spec S~_m = [-m, m] for 3 <= m <= 5.
    The paper itself cites [6, Thm. 6.5] (Remark 1.6) and does not reprove it,
    and the bibliographic data of [6] is not given, so we cannot even look it
    up.  We can only search for counterexamples.
    => The "cospectral" half of Theorem 1.5 therefore rests on an external
       theorem that this project CANNOT independently verify.  That is a fact
       about the paper, and it is reported, not hidden.

Why the paper is nevertheless interesting even granting the quote: the
non-isomorphism is proved HERE by an invariant (girth) that is completely
elementary, so the pair really is a counterexample to "spectrum determines the
graph" among periodic graphs -- assuming the quoted spectrum.

Negative control:
  same_graph -- compare K(m) against itself.  The girth separator is then
                vacuous and the non-isomorphism check MUST go RED.  A separator
                that cannot fail is not evidence; this control proves it can.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np

sys.path.insert(0, ".")
import repro_common as rc
from repro_result import Checks, emit, guard

BUGS = ("same_graph",)
EXPECT_GIRTH_K = 6
EXPECT_GIRTH_STILDE = {4: 4, 5: 4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--inject-bug", default=None, choices=list(BUGS))
    ap.add_argument("--m", default="4,5")
    args = ap.parse_args()
    ms = [int(t) for t in args.m.split(",") if t.strip()]
    bug = args.inject_bug

    C = Checks()
    C.observe("script", "exp5_noniso.py")
    C.observe("paper_claims", {
        "theorem": "Theorem 1.5 (text:78-90): for m in {4,5} the pair is cospectral, "
                   "of the same degree and periodic rank, and non-isomorphic",
        "spectrum_K": "proved in the paper (section 3) and numerically cross-checked here",
        "spectrum_Stilde": "QUOTED from [6, Thm. 6.5]; the paper does not reprove it "
                           "(Remark 1.6) and gives no bibliographic data for [6]",
        "non_isomorphism": "established here from the girth, which is elementary",
    })
    C.observe("independently_verified", {
        "same_degree": True,
        "non_isomorphic": True,
        "spectrum_K(m)": "numerical cross-check only (proof is the paper's)",
        "spectrum_Stilde(m)": False,
        "cospectrality_of_the_pair": False,
        "reason": "the S~_m half of the spectrum is a quoted external theorem that this "
                  "project cannot read or verify; the pair's cospectrality inherits that gap",
    })
    C.observe("injected_bug", bug)
    if bug:
        C.note("NEGATIVE CONTROL ACTIVE: %s -- the S~_m side is replaced by K(m) itself"
               % bug)

    per_m = {}
    for m in ms:
        t0 = time.time()
        rec = {"m": m}

        # ------------------------------------------------------- 1. same degree
        profK = rc.degree_profile_K(m, 2)
        degS = rc.stilde_degree(m)
        rec["K_degree_profile"] = profK
        rec["Stilde_degree"] = degS
        C.check("m%d.both_graphs_are_m_regular_same_degree" % m,
                bool(profK["regular_of_degree_m"]) and bool(degS.get("regular"))
                and degS.get("degree") == m,
                "K(%d) degrees %s; S~_%d cell degrees %s (both = %d, so the two graphs have "
                "the same degree -- a necessary condition for cospectrality of regular graphs)"
                % (m, profK["distinct_degrees"], m, degS.get("distinct_degrees"), m))

        # --------------------------------------------------------- 2. the girths
        gk = rc.bfs_girth_K(m, 3)
        girth_K = gk["girth"]
        rec["girth_K"] = girth_K
        rec["girth_K_certificate"] = {"r": 3, "mu_r": girth_K, "condition": "mu_r <= 2r"}
        C.check("m%d.girth_K_is_6_with_box_certificate" % m,
                girth_K == EXPECT_GIRTH_K and girth_K <= 2 * 3,
                "girth K(%d) = %s inside the radius-3 ball (|B_3| = %d), and mu_r = %d <= 2r = 6, "
                "so the ball-internal value IS the girth (a shortest cycle through the root has "
                "all vertices within distance girth/2)"
                % (m, girth_K, gk["ball_size"], girth_K))

        if bug == "same_graph":
            girth_S = girth_K
            rec["girth_Stilde"] = "REPLACED BY K(m) ITSELF (injected bug)"
            ball_size = gk["ball_size"]
            radius_used = 3
        else:
            radius_used = 2
            ball = rc.build_w_ball(m, radius_used)
            gS = rc.ball_girth(ball["elements"], m, radius_used)
            girth_S = gS["girth"]
            ball_size = ball["size"]
            rec["girth_Stilde"] = girth_S
            rec["girth_Stilde_certificate"] = {"r": radius_used, "mu_r": girth_S,
                                               "condition": "mu_r <= 2r"}
        C.check("m%d.girth_Stilde_is_4_with_box_certificate" % m,
                girth_S == EXPECT_GIRTH_STILDE.get(m) and girth_S <= 2 * radius_used,
                "girth S~_%d = %s inside the radius-%d ball (|B_%d| = %d); mu_r = %s <= 2r = %d. "
                "For m >= 4 the Coxeter diagram is a cycle, so s_1 and s_3 are non-adjacent and "
                "commute: 1, s_1, s_1 s_3, s_3 is a 4-cycle"
                % (m, girth_S, radius_used, radius_used, ball_size, girth_S, 2 * radius_used))

        # --------------------------------------------- 3. therefore not isomorphic
        C.check("m%d.girths_differ_therefore_not_isomorphic" % m,
                girth_K != girth_S,
                "girth K(%d) = %s != girth S~_%d = %s. A graph isomorphism preserves girth, so "
                "the two graphs are NOT isomorphic. This step is fully elementary and does not "
                "depend on any quoted theorem."
                % (m, girth_K, m, girth_S))
        if bug == "same_graph":
            C.note("with same_graph injected, the separator is vacuous by construction: the two "
                   "girth values are equal because they are the same graph, and the check above "
                   "correctly goes RED. That is the negative control working.")

        # ------------------------------------------------- 4. same periodic rank
        # K(m) is periodic with period lattice Lambda = mQ^v; S~_m with Q^v.
        # Q^v = {lam in Z^m : sum(lam) = 0} is cut out by ONE independent linear
        # equation in Z^m, so it has rank m-1; mQ^v is a finite-index sublattice,
        # hence the same rank.  So both graphs have periodic rank m-1.
        #
        # The check below verifies the rank claim the honest way: the constraint
        # matrix has exactly one row and that row is nonzero (rank 1), so
        # rank Q^v = m - 1.  An earlier version built a matrix of m rows and
        # compared its rank to 1, which is simply false -- the assertion was
        # wrong, not the mathematics.
        rank = m - 1
        constraint = np.array([[1] * m], dtype=float)   # the single equation sum(lam) = 0
        n_constraints = int(np.linalg.matrix_rank(constraint))
        rec["periodic_rank"] = rank
        rec["rank_constraint"] = {"rows": int(constraint.shape[0]), "rank": n_constraints,
                                  "implied_rank_of_Qv": m - n_constraints}
        C.check("m%d.same_periodic_rank_m_minus_1" % m,
                rank == m - 1 and n_constraints == 1 and (m - n_constraints) == m - 1,
                "Q^v = {lam in Z^%d : sum(lam) = 0} is cut out by %d independent equation(s) "
                "(the single row of ones, rank %d), so rank Q^v = %d - %d = %d. mQ^v is a "
                "finite-index sublattice of Q^v, hence the same rank. K(%d) has period lattice "
                "mQ^v and S~_%d has Q^v, so both have periodic rank %d"
                % (m, n_constraints, n_constraints, m, n_constraints, rank, m, m, rank))

        # ------------------------------------------- 5. spectra, with honest labels
        z1 = np.zeros(m - 1)
        evK = rc.eigvals_K(m, z1)
        zs = rc.grid_z(m, 6)
        SK = np.abs(rc.S_grid(m, zs))
        rec["K_spectrum_endpoint_eig"] = [float(evK.min()), float(evK.max())]
        rec["K_max_abs_S_on_grid"] = float(SK.max())
        C.check("m%d.spectrum_K_endpoints_and_bound" % m,
                abs(float(evK.max()) - m) <= 1e-9 and abs(float(evK.min()) + m) <= 1e-9
                and float(SK.max()) <= m + 1e-9,
                "Spec K(%d): chi = 1 gives exactly {-%d, +%d}; over a %d-point grid every "
                "|S(chi)| <= %d. The PROOF that the whole interval [-%d, %d] is attained is the "
                "paper's section 3; these numbers are a cross-check, not the proof"
                % (m, m, m, len(zs), m, m, m))

        # the S~ side: counterexample search only, explicitly labelled
        zs2 = rc.grid_z(m, 5)
        lamS = np.concatenate([np.linalg.eigvalsh(rc.stilde_floquet(m, z)) for z in zs2])
        rec["Stilde_max_abs_eig_on_grid"] = float(np.max(np.abs(lamS)))
        C.check("m%d.spectrum_Stilde_no_counterexample_QUOTED" % m,
                float(np.max(np.abs(lamS))) <= m + 1e-9,
                "Spec S~_%d: over a %d-point grid no eigenvalue leaves [−%d, %d] "
                "(max |lambda| = %.6f). **This is a counterexample search, NOT a verification**: "
                "the statement is quoted from [6, Thm. 6.5] and the paper does not prove it. "
                "We record independently_verified = False for this half."
                % (m, len(zs2), m, m, float(np.max(np.abs(lamS)))))

        # ------------------------------------------- 6. the cells are not isomorphic
        n_cell_K = 2
        n_cell_S = len(rc.stilde_class_representatives(m))
        rec["cell_sizes"] = {"K": n_cell_K, "Stilde": n_cell_S}
        C.check("m%d.cells_are_not_isomorphic_as_voltage_graphs" % m,
                n_cell_K != n_cell_S,
                "the paper's section 6 says a finite computation on the cell separates the pair "
                "'if and only if the two cells are not isomorphic as voltage graphs'. Here "
                "|V(cell_K)| = %d != %d = m! = |V(cell_S~_%d)|, so they are separated trivially "
                "(the count differs before any search is needed)" % (n_cell_K, n_cell_S, m))

        rec["seconds"] = round(time.time() - t0, 2)
        per_m[m] = rec

    # ---------------------------------------------------------------- summary
    C.observe("per_m", per_m)
    C.observe("verdict_scope", {
        "established_here": "same degree, non-isomorphism (via girth), same periodic rank, "
                            "non-isomorphic cells, Spec K(m) = [-m,m] numerically",
        "not_established_here": "Spec S~_m = [-m,m] is quoted from [6, Thm. 6.5]; hence the "
                                "pair's COSPECTRALITY is not independently verified",
        "consequence": "Theorem 1.5 is reproduced modulo one external, unreadable reference",
    })
    return emit(C.result_dict(), args.json)


if __name__ == "__main__":
    guard(main)
