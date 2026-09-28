#!/usr/bin/env python
"""
exp4_size_regularity.py -- Lemma 2.2 and Remark 2.3 (text:127-163): the period
lattice, the size of the cell, and m-regularity.

Checks, per m in {3,4,5}
  1. [Q^v : m Q^v] = m^(m-1) = 9 / 64 / 625, computed three independent ways:
     the determinant of the coordinate matrix of m*(coroot basis) in the coroot
     basis, its Smith normal form, and a brute-force residue count.
  2. |V_K / Lambda| = 2 m^(m-1) = 18 / 128 / 1250, from the canonical residue
     parameterisation (classes are (x_1..x_{m-1} mod m, sum(x) in {0,1})), plus
     the verification that every one of the 2 m^(m-1) residue pairs is actually
     realised by a vertex of V_K.
  3. m-regularity, in the two forms that are actually true:
     (a) every vertex has exactly m neighbours in V_K (Lemma 2.2) -- this holds
         on the boundary of a box too, because the neighbour count is taken in
         V_K and not in the box;
     (b) inside the box [-b,b]^m the INDUCED degree is m for every INTERIOR
         vertex, while boundary vertices can have fewer.  The boundary effect is
         measured and reported: asserting m-regularity from a box-induced degree
         profile over the whole box would be simply false (for m = 3, b = 2 the
         induced degrees are {2, 3}), and that is recorded rather than hidden.
  4. vertex-transitivity: x -> x + lam (lam in the coroot basis) preserves
     adjacency; and V_K has exactly the two levels sum = 0 and sum = 1
     (Remark 3.2, text:273-277).

Negative control lattice_Q -- use Lambda = Q^v instead of m Q^v.  Q^v is
transitive on each level set, so the quotient then has exactly 2 classes
instead of 2 m^(m-1); the class-count check catches it.
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")
import repro_common as rc
import repro_lattice as rl
from repro_result import Budget, Checks, emit, guard
#: 本脚本验证的**论文命题原文**（`E-9`）：与 `run_acceptance.py` 的 P5 计划表
#: 逐字相同，由 P5 的 `_paper_declaration_audit()` 交叉核对。
#: 为什么要写在这里：脚本自报的 `supports` 需要有一个**外部锚** —— 否则
#: 『论文声称 vs 独立计算』就只剩脚本自己作证。
PAPER_CLAIM = '|V_K/Λ| = 2m^{m−1}（m=3,4,5）与 m-正则性'


BUGS = ("lattice_Q",)
DEFAULT_MAX_SECONDS = 60.0
BOXES = {3: 2, 4: 2, 5: 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--inject-bug", default=None, choices=list(BUGS))
    ap.add_argument("--m", default="3,4,5")
    ap.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS,
                    help="hard wall-clock budget; on expiry the run stops and "
                         "reports ALL CHECKS INCONCLUSIVE instead of hanging")
    args = ap.parse_args()
    budget = Budget(args.max_seconds, "exp4")
    ms = [int(t) for t in args.m.split(",") if t.strip()]
    bug = args.inject_bug

    C = Checks()
    C.observe("max_seconds", args.max_seconds)
    C.observe("script", "exp4_size_regularity.py")
    C.observe("paper_claims", {
        "lemma_2_2": "text:127-145 -- K(m) is Q^v-periodic of rank m-1 with "
                     "exactly two orbits on V_K; both graphs are m-regular and "
                     "vertex-transitive",
        "remark_2_3": "text:146-163 -- Lambda = m Q^v has index m^(m-1) in Q^v "
                      "and gives a cell with 2 m^(m-1) vertices",
        "paper_section_5": "text:389-391 -- |V_K/Lambda| = 2m^{m-1} = 18, 128, "
                           "1250 for m = 3,4,5",
        "proved_in_paper": True,
        "our_role": "exact-integer and numerical cross-check only",
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

        # ---------------- 1. index of m Q^v in Q^v -----------------------
        idx = rl.lattice_index_report(m)
        rec["lattice_index"] = idx
        C.check("m%d.index_of_mQ_in_Q_is_m_pow_m_minus_1" % m, idx["all_agree"],
                "[Q^v : mQ^v]: determinant %d, Smith normal form %s (product %d), "
                "residue count %d, formula m^(m-1) = %d (Remark 2.3)"
                % (idx["index_by_determinant"], idx["smith_normal_form"],
                   idx["index_by_smith_normal_form"], idx["index_by_residue_count"],
                   idx["index_formula_m_pow_m_minus_1"]))

        # ---------------- 2. class count ---------------------------------
        sub = "Qcoroot" if bug == "lattice_Q" else "mQcoroot"
        cl = rl.classes_VK_mod_Lambda(m, sub_lattice=sub)
        rec["classes"] = cl
        want = 2 * m ** (m - 1)
        C.check("m%d.class_count_is_2_m_pow_m_minus_1" % m, cl["n_classes"] == want,
                "period lattice %s gives %d classes, expected 2*m^(m-1) = %d%s"
                % (cl["sub_lattice"], cl["n_classes"], want,
                   "  <-- WRONG LATTICE: with Lambda = Q^v the two level sets are "
                   "the two orbits, so the count collapses to 2 and this check "
                   "FAILS; that is the injected error being caught"
                   if bug == "lattice_Q" else ""))
        if bug != "lattice_Q":
            csz = rl.class_size_check(m)
            rec["class_size_check"] = csz
            C.check("m%d.every_residue_pair_is_realised" % m,
                    csz["all_candidates_realised"],
                    "level 0: %d of %d residue classes realised, level 1: %d of "
                    "%d; the residue map V_K -> Z_m^{m-1} x {0,1} is onto, so no "
                    "class is missed and the count is exactly 2 m^(m-1)"
                    % (csz["n_classes_level_0"], csz["expected_each_level"],
                       csz["n_classes_level_1"], csz["expected_each_level"]))

        # ---------------- 3a. neighbour count in V_K ---------------------
        bad = None
        verts1 = rc.vertex_set_K(m, 1)
        for x in verts1:
            if rc.degree_K(m, x) != m:
                bad = x
                break
        C.check("m%d.every_vertex_has_m_neighbours_in_V_K" % m, bad is None,
                "all %d vertices of the box [-1,1]^%d have exactly %d neighbours "
                "in V_K (first failure: %s)"
                % (len(verts1), m, m, bad))

        # ---------------- 3b. box-induced degrees, boundary excluded -----
        box = BOXES.get(m, 2)
        inter = rl.degree_profile_K_interior(m, box)
        whole = rl.degree_profile_K(m, box)
        rec["interior_degree_profile"] = inter
        rec["box_degree_profile"] = whole
        C.check("m%d.interior_of_box_is_m_regular" % m,
                inter["interior_regular_of_degree_m"],
                "box [-%d,%d]^%d: all %d INTERIOR vertices have induced degree "
                "exactly %d; the other %d box vertices have degrees %s, because "
                "neighbours leaving the box are lost -- so a box-based "
                "regularity test must exclude the boundary (the whole-box "
                "profile is %s, which would falsely suggest irregularity)"
                % (box, box, m, inter["n_interior_vertices"], m,
                   inter["n_vertices_in_box"] - inter["n_interior_vertices"],
                   inter["boundary_degrees"], whole["distinct_degrees"]))

        # ---------------- 4. transitivity and the two levels -------------
        shifts = [tuple(1 if k == i else (-1 if k == i + 1 else 0) for k in range(m))
                  for i in range(m - 1)]
        tv = rl.translation_invariance_K(m, box, shifts)
        rec["vertex_transitivity"] = tv
        C.check("m%d.translation_by_coroots_is_an_automorphism" % m,
                tv["all_shifts_are_automorphisms"],
                "x -> x + lam for the coroot basis vectors lam = %s preserves "
                "adjacency on the box-induced graph (Lemma 2.2)"
                % [r["shift"] for r in tv["shifts"]])
        levels = {}
        for x in rc.vertex_set_K(m, box):
            levels[sum(x)] = levels.get(sum(x), 0) + 1
        rec["levels_in_box"] = levels
        C.check("m%d.V_K_has_exactly_two_levels" % m, sorted(levels) == [0, 1],
                "the box contains %s vertices with sum 0 and %s with sum 1 and no "
                "other sums -- the two Q^v-orbits of Lemma 2.2"
                % (levels.get(0), levels.get(1)))

        # ---------------- 5. the paper's numbers -------------------------
        C.check("m%d.paper_table_matches" % m,
                want == {3: 18, 4: 128, 5: 1250}[m],
                "2 m^(m-1) = %d agrees with the paper's table (18, 128, 1250 for "
                "m = 3,4,5; text:389-391)" % want)

        # ---------------- 6. the box undercount trap, measured -----------
        # Enumerating V_K inside a coordinate box and reducing modulo m DOES miss
        # classes, because a representative may need large |coordinates|.  This
        # is a property of the naive method, not a counterexample to the paper,
        # so it is recorded as an observation with a demonstration.
        if m == 5:
            seen = set()
            for x in rc.vertex_set_K(m, 3):
                seen.add((tuple(t % m for t in x[:-1]), sum(x)))
            diag = {"box": 3, "n_classes_found": len(seen), "n_classes_true": want,
                    "undercounts": len(seen) < want,
                    "comment": "box enumeration is NOT a valid way to count the "
                               "classes; the residue count in check 2 is"}
            rec["box_undercount_diagnostic"] = diag
            C.observe("m5_box_undercount_diagnostic", diag)

        rec["seconds"] = round(time.time() - t0, 3)
        per_m["m%d" % m] = rec
    C.observe("per_m", per_m)

    if bug:
        C.observe("lattice_Q_control", {
            "what": "Lambda = Q^v instead of Lambda = m Q^v (Remark 2.3, "
                    "text:146-163, warns that the choice of period lattice "
                    "matters)",
            "effect": "Q^v is transitive on each level set, so V_K/Lambda has 2 "
                      "classes instead of 2 m^(m-1)",
            "caught_by": "class_count_is_2_m_pow_m_minus_1",
        })

    return emit(C.result_dict(), args.json)


if __name__ == "__main__":
    guard(main)
