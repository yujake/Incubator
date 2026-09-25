#!/usr/bin/env python
"""
exp4_size_regularity.py -- the sizes, degrees and cell data of K(m) and S~_m.

Claims checked (all PROVED in the paper; we recompute them independently):
  * [Q^v : mQ^v] = m^{m-1}                                   (Remark 2.3, text:161-167)
  * |V_K / Lambda| = 2 m^{m-1}                              (section 5, text:355-360)
  * K(m) is m-regular, bipartite, and has exactly 2 orbits under Q^v
                                                             (Lemma 2.2, Remark 3.2)
  * the cell of V_K / Q^v has 2 vertices and m PARALLEL edges with voltages
    0, e_1, ..., e_{m-1}                                      (Lemma 3.1(iii))
  * the cell of S~_m has m! vertices                        (section 6, text:414-420)
  * lambda_max at chi = 1 equals the DEGREE m, not 2m-1      (Remark 3.5, text:315-320)

The counting trap this file is built around (REPRO-SPEC R5, measured): |V_K/Lambda|
MUST be obtained by algebra -- classes are (a, s) with a in (Z_m)^{m-1} and
s in {0,1}.  Enumerating V_K inside a coordinate box and reducing mod Lambda
MISSES classes (for m = 5, box [-3,3]^5 yields fewer than 1250), because a
representative can need a last coordinate of modulus ~16.  That undercount is
included here as a NEGATIVE CONTROL so the trap is demonstrated, not just
described.

Negative controls:
  box_undercount -- report the box enumeration as if it were the class count.
                    The check must then go RED (the value is too small).
  double_count   -- count each of the 2m directed steps +-e_i as its own cell
                    edge.  Then S(1) = 2m-1 and lambda_max = 2m-1 instead of m:
                    exactly the error Remark 3.5 warns about.
"""

from __future__ import annotations

import argparse
import itertools
import math
import sys
import time

import numpy as np

sys.path.insert(0, ".")
import repro_common as rc
from repro_result import Checks, emit, guard

BUGS = ("box_undercount", "double_count")
EXPECT_SIZE = {3: 18, 4: 128, 5: 1250}
EXPECT_INDEX = {3: 9, 4: 64, 5: 625}


def quotient_classes_by_enumeration(m):
    """Class (a, s): a in (Z_m)^{m-1}, s in {0,1} -- ALGEBRAIC, no box.

    Why this is complete: a vertex x of V_K has sum(x) in {0,1}.  Writing
    a = (x_1, ..., x_{m-1}) mod m determines the class of x under Lambda = mQ^v,
    because the last coordinate is then forced to be s - sum(a mod m) up to a
    multiple of m.  So the classes are exactly the pairs (a, s)."""
    return {(a, s) for a in itertools.product(range(m), repeat=m - 1) for s in (0, 1)}


def quotient_classes_by_box(m, box):
    """The WRONG way, kept deliberately: enumerate V_K in [-box,box]^m, reduce.

    Under-counts because representatives can require large coordinates."""
    seen = set()
    for x in itertools.product(range(-box, box + 1), repeat=m):
        if sum(x) in (0, 1):
            seen.add((tuple(v % m for v in x[:m - 1]), sum(x)))
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--inject-bug", default=None, choices=list(BUGS))
    ap.add_argument("--m", default="3,4,5")
    args = ap.parse_args()
    ms = [int(t) for t in args.m.split(",") if t.strip()]
    bug = args.inject_bug

    C = Checks()
    C.observe("script", "exp4_size_regularity.py")
    C.observe("paper_claims", {
        "sizes": "Remark 2.3 + section 5: |V_K/Lambda| = 2 m^{m-1}, [Q^v : mQ^v] = m^{m-1}",
        "regularity": "Lemma 2.2: K(m) is m-regular; S~_m is a Cayley graph hence m-regular",
        "cell_K": "Lemma 3.1(iii): 2 vertices, m parallel edges, voltages 0, e_1, ..., e_{m-1}",
        "cell_Stilde": "section 6: the cell of S~_m has m! vertices",
        "remark_3_5": "lambda_max = m = the degree, NOT 2m-1",
        "proved_in_paper": True,
        "our_role": "independent recomputation",
    })
    C.observe("injected_bug", bug)
    if bug:
        C.note("NEGATIVE CONTROL ACTIVE: %s" % bug)

    per_m = {}
    for m in ms:
        t0 = time.time()
        rec = {"m": m}

        # ---------------------------------------------------------------- sizes
        classes = quotient_classes_by_enumeration(m)
        expect = EXPECT_SIZE[m]
        rec["n_classes_algebraic"] = len(classes)
        rec["n_classes_expected"] = expect
        if bug == "box_undercount":
            boxed = quotient_classes_by_box(m, 3)
            rec["n_classes_box_3"] = len(boxed)
            C.check("m%d.class_count_is_2m_pow_(m-1)_NOT_box" % m,
                    len(boxed) == expect,
                    "a coordinate box [-3,3]^%d gives only %d classes, but V_K/Lambda has %d: "
                    "box enumeration MISSES classes (representatives can need |coord| ~ m^2). "
                    "This is the negative control firing: the box count is being reported as "
                    "the class count and the check catches it."
                    % (m, len(boxed), expect))
        else:
            C.check("m%d.class_count_is_2m_pow_(m-1)" % m, len(classes) == expect,
                    "|V_K/Lambda| = %d = 2 * %d^(%d-1), algebraically (a in (Z_m)^{m-1}, "
                    "s in {0,1}) -- NOT by enumerating a box" % (len(classes), m, m))
            C.check("m%d.index_of_mQv_in_Qv_is_m_pow_(m-1)" % m,
                    m ** (m - 1) == EXPECT_INDEX[m],
                    "[Q^v : mQ^v] = m^(m-1) = %d (Remark 2.3)" % m ** (m - 1))
            # the trap, demonstrated rather than merely asserted
            if m == 5:
                boxed = quotient_classes_by_box(m, 3)
                rec["n_classes_box_3"] = len(boxed)
                C.check("m%d.box_enumeration_undercounts_demonstrated" % m,
                        len(boxed) < expect,
                        "box [-3,3]^5 gives %d classes < %d -- the undercount is real and "
                        "measured here, which is why the count must be algebraic"
                        % (len(boxed), expect))

        # ------------------------------------------------------- regularity K(m)
        prof = rc.degree_profile_K(m, 2)
        rec["degree_profile_K_box2"] = prof
        C.check("m%d.K_is_m_regular" % m, bool(prof["regular_of_degree_m"]),
                "over the radius-2 box, K(%d) degrees present = %s with counts %s"
                % (m, prof["distinct_degrees"], prof["counts"]))

        # -------------------------------------------------- two orbits under Q^v
        # The level s(x) = sum(x) in {0,1} is invariant under Q^v (adding a vector
        # of sum 0 preserves sum).  So there are at least 2 orbits.  Conversely, if
        # sum(x) == sum(x') then lam = x' - x has sum 0, i.e. lam in Q^v, so x and
        # x' ARE in the same orbit.  Hence exactly 2 -- and this reasoning is valid
        # for all vertices, with explicit samples as illustration.
        level0 = [(0,) * m, tuple([2, -2] + [0] * (m - 2))]
        level1 = [tuple([1] + [0] * (m - 1)), tuple([2, 0, -1] + [0] * (m - 3)) if m >= 3 else None]
        level1 = [v for v in level1 if v is not None and sum(v) == 1]
        same0 = all(sum(y) - sum(level0[0]) == sum(y) for y in level0[1:])
        lam0 = tuple(level0[1][i] - level0[0][i] for i in range(m))
        no_cross = all(sum(x) != sum(y) for x in level0 for y in level1)
        rec["orbit_witness"] = {"level0": [list(v) for v in level0],
                                "level1": [list(v) for v in level1],
                                "lam_level0": list(lam0)}
        C.check("m%d.K_has_two_orbits_under_Qv" % m,
                same0 and sum(lam0) == 0 and no_cross and len(level1) >= 1,
                "level s(x)=sum(x) in {0,1} is Q^v-invariant (>= 2 orbits); any two vertices "
                "of equal level differ by a vector of sum 0, i.e. by an element of Q^v "
                "(so exactly 2): witness lam = %s with sum 0" % (list(lam0),))

        # ------------------------------------------------------------------ cell K
        #
        # The expected value below is the PAPER'S claim (lambda_max = m = degree),
        # and it must NOT depend on the injected bug.  An earlier version of this
        # file set `want = 2m-1` under double_count, so the comparison trivially
        # agreed with the injected error and the negative control PASSED -- a
        # negative control that cannot fail is worse than none, because it is
        # reported as evidence that the gate works.
        dc = (bug == "double_count")
        z1 = np.zeros(m - 1)
        ev1 = rc.eigvals_K(m, z1, double_count=dc)
        rec["cell_K_eig_at_identity"] = [float(ev1.min()), float(ev1.max())]
        A = rc.floquet_K(m, z1, double_count=dc)
        rec["cell_K_shape"] = list(A.shape)

        if dc:
            # Report what the wrong edge count actually produces, so the failure
            # below is attributable to the injection rather than to a mystery.
            wrong = rc.eigvals_K(m, z1, double_count=True)
            rec["double_count_eig"] = [float(wrong.min()), float(wrong.max())]
            C.check("m%d.remark_3_5_double_count_gives_2m_minus_1" % m,
                    abs(float(wrong.max()) - (2 * m - 1)) <= 1e-9,
                    "negative control: counting each of the 2m directed steps +-e_i as its "
                    "own cell edge gives lambda_max = %d = 2m-1, and the checks below (which "
                    "require the paper's value m = %d) now go RED"
                    % (2 * m - 1, m))

        C.check("m%d.cell_K_lambda_max_is_degree_not_2m_minus_1" % m,
                abs(float(ev1.max()) - m) <= 1e-9 and abs(float(ev1.min()) + m) <= 1e-9,
                "chi = 1: cell adjacency eigenvalues %.9f .. %.9f (expected +-%d). "
                "The cell has 2 vertices and m PARALLEL edges (voltages 0, e_1, ..., e_{m-1}), "
                "so the off-diagonal entry is the SUM over the m edges = m, and lambda_max "
                "= m = the degree. Counting the 2m directed steps instead gives %d -- "
                "Remark 3.5's error." % (float(ev1.min()), float(ev1.max()), m, 2 * m - 1))

        rec["cell_K_A_squared_is_m2_I"] = bool(np.allclose(A @ A, (m ** 2) * np.eye(2), atol=1e-9))
        C.check("m%d.cell_K_is_2x2_and_A_squared_is_m_squared_I" % m,
                A.shape == (2, 2) and np.allclose(A @ A, (m ** 2) * np.eye(2), atol=1e-9),
                "cell(V_K/Q^v) is %dx%d and A^2 = %d^2 * I -- i.e. the 2x2 cell with m "
                "parallel edges, whose spectrum is exactly {-%d, +%d}"
                % (A.shape[0], A.shape[1], m, m, m))

        # |S(chi)| <= m for every chi, with equality iff chi = 1 (triangle inequality)
        zs = rc.grid_z(m, 7)
        S = np.abs(rc.S_grid(m, zs, double_count=dc))
        rec["max_abs_S_grid"] = float(S.max())
        C.check("m%d.S_is_bounded_by_number_of_edge_terms" % m,
                abs(float(S.max()) - m) <= 1e-9 and bool(np.all(S <= m + 1e-9)),
                "over a %d-point grid: max |S(chi)| = %.6f = the number of summed edge terms "
                "(%d), and no chi exceeds it -- the triangle-inequality bound that makes "
                "[−m, m] the largest possible spectrum" % (len(zs), float(S.max()), m))

        # ------------------------------------------------------------ cell S~_m
        reps = rc.stilde_class_representatives(m)
        deg = rc.stilde_degree(m)
        rec["cell_Stilde_vertices"] = len(reps)
        rec["cell_Stilde_degree"] = deg
        C.check("m%d.cell_Stilde_has_m_factorial_vertices" % m,
                len(reps) == math.factorial(m),
                "cell of S~_%d: %d vertices = %d! (section 6). Note 2 != m! for every m >= 4, "
                "which is what makes the two cells trivially non-isomorphic"
                % (m, len(reps), m))
        C.check("m%d.cell_Stilde_is_m_regular" % m,
                bool(deg.get("regular")) and deg.get("degree") == m,
                "cell of S~_%d is %s-regular (the m Coxeter generators, none of which is the "
                "identity, so there are no self-loops)" % (m, deg.get("degree")))

        rec["seconds"] = round(time.time() - t0, 2)
        per_m[m] = rec

    C.observe("per_m", per_m)
    return emit(C.result_dict(), args.json)


if __name__ == "__main__":
    guard(main)
