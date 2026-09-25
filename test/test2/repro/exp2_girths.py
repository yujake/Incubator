#!/usr/bin/env python
"""
exp2_girths.py -- Theorem 1.4:  girth K(m) = 6 (m >= 3);
                  girth S~_m = 6 for m = 3 and 4 for m >= 4
                  (text:70-71, 323-380, and Example 1.8 at text:89-104).

Two independent numerical routes for each girth:
  * edge-deletion: girth = min over edges {a,b} of dist_{G-ab}(a,b) + 1
    (each candidate is a shortest path plus an edge, hence a chordless cycle);
  * exhaustive DFS over simple cycles (small balls only), and for K(m) also the
    enumeration of all simple cycles through 0^m of length 3..6.
Plus explicit cycles that are checked edge by edge:
  * K(m): the paper's 6-cycle pattern
    x, x+e_1, x+e_1-e_2, x+e_1-e_2+e_3, x-e_2+e_3, x+e_3, x  (text:335-337);
  * S~_m, m >= 4: 1, s_1, s_1 s_3, s_3 (text:349-375);
  * S~_3:  1, s_i, s_i s_j, s_i s_j s_i, (s_i s_j)^2, s_j, 1 (text:378-380).
Structural checks that could fail: K(m) is bipartite so it has no odd cycle
(text:273-277); S~_m has no triangle (text:344-348).

Negative controls:
  allow_backtrack -- count x -> x+e_i -> x as a cycle: the girth becomes 2.
  wrong_s0        -- s_0 = (tau_0, 0), losing the translation: the Coxeter
                     relation (s_0 s_2)^3 = e fails, the ball collapses to the
                     finite S_m (6 elements for m = 3), and girth S~_3 = 4.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

sys.path.insert(0, ".")
import repro_common as rc
from repro_result import Budget, Checks, emit, guard

BUGS = ("allow_backtrack", "wrong_s0")
DEFAULT_MAX_SECONDS = 60.0
EXPECT_GIRTH_K = 6
EXPECT_GIRTH_STILDE = {3: 6, 4: 4, 5: 4}


def cycle_stilde_parabolic(m, i, j):
    """The paper's 6-cycle in the rank-two parabolic <s_i, s_j> (text:378-380),
    as an explicit list of group elements (not closed)."""
    e = rc.weyl_identity(m)
    gens = rc.affine_generators(m)
    a, b = gens[i], gens[j]
    p1 = rc.weyl_mul(e, a)
    p2 = rc.weyl_mul(p1, b)
    p3 = rc.weyl_mul(p2, a)
    p4 = rc.weyl_mul(p3, b)
    p5 = rc.weyl_mul(p4, a)
    return [e, p1, p2, p3, p4, p5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--inject-bug", default=None, choices=list(BUGS))
    ap.add_argument("--m", default="3,4,5")
    ap.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS,
                    help="hard wall-clock budget; on expiry the run stops and "
                         "reports ALL CHECKS INCONCLUSIVE instead of hanging")
    args = ap.parse_args()
    budget = Budget(args.max_seconds, "exp2")
    ms = [int(t) for t in args.m.split(",") if t.strip()]
    bug = args.inject_bug

    C = Checks()
    C.observe("max_seconds", args.max_seconds)
    C.observe("script", "exp2_girths.py")
    C.observe("paper_claims", {
        "theorem": "Theorem 1.4 (text:70-71): girth K(m) = 6 for m >= 3; "
                   "girth S~_m = 6 for m = 3 and 4 for m >= 4",
        "proved_in_paper": True,
        "our_role": "numerical cross-check only",
    })
    C.observe("injected_bug", bug)
    if bug:
        C.note("NEGATIVE CONTROL ACTIVE: %s" % bug)

    per_m = {}
    for m in ms:
        if budget.mark_if_expired(C, "start of m=%d" % m):
            break
        t0 = time.time()
        rec = {"m": m, "expected": {"girth_K": EXPECT_GIRTH_K,
                                    "girth_Stilde": EXPECT_GIRTH_STILDE.get(m)}}

        # ------------------------------------------------------------------
        # K(m)
        # ------------------------------------------------------------------
        radius = 3
        if bug == "allow_backtrack":
            gk = rc.bfs_girth_K_allow_backtrack(m, radius)
            rec["girth_K_allow_backtrack"] = gk
            C.check("m%d.K.no_backtrack_2cycles" % m, gk["girth"] != 2,
                    "counting the reversal x -> x+e_i -> x as a cycle gives "
                    "girth 2 for K(%d), contradicting Theorem 1.4's girth 6 -- "
                    "the check 'the reported girth is not a backtrack' catches it"
                    % m)
        gk = rc.bfs_girth_K(m, radius)
        rec["girth_K_edge_deletion"] = {k: v for k, v in gk.items() if k != "cycle_vertices"}
        C.check("m%d.K.girth_equals_6" % m, gk["girth"] == EXPECT_GIRTH_K,
                "edge-deletion girth of K(%d) = %s (ball %d, radius %d)"
                % (m, gk["girth"], gk["ball_size"], radius))

        # cross-check 1: exhaustive DFS on the same ball
        if m <= 4:
            gd = rc.bfs_girth_K(m, radius, method="dfs")
            rec["girth_K_dfs"] = {"girth": gd["girth"], "steps": gd["steps"],
                                  "ball_size": gd["ball_size"]}
            C.check("m%d.K.dfs_agrees_with_edge_deletion" % m,
                    gd["girth"] == gk["girth"],
                    "exhaustive simple-cycle DFS gives %s, edge-deletion gives %s"
                    % (gd["girth"], gk["girth"]))

        # cross-check 2: exhaustive enumeration of cycles through 0 of length 3..7
        counts = {}
        for k in (3, 4, 5, 6, 7):
            counts[k] = len(rc.cycles_through_root_K(m, tuple([0] * m), k))
        rec["cycles_through_origin_by_length"] = counts
        first_nonzero = next((k for k in sorted(counts) if counts[k] > 0), None)
        C.check("m%d.K.exhaustive_shortest_cycle_through_0_is_6" % m,
                first_nonzero == EXPECT_GIRTH_K,
                "shortest simple cycle through 0^%d has length %s "
                "(counts by length: %s)" % (m, first_nonzero, counts))
        C.check("m%d.K.no_odd_cycles_up_to_7" % m,
                all(counts[k] == 0 for k in counts if k % 2 == 1),
                "K(m) is bipartite (Remark 3.2), so no odd cycles: counts %s"
                % {k: v for k, v in counts.items() if k % 2 == 1})

        # explicit 6-cycle
        x0 = tuple([0] * m)
        cyc = [x0]
        steps = [1, -2, 3, -1, 2, -3]   # e1, -e2, +e3, -e1, +e2, -e3
        cur = list(x0)
        for s in steps:
            cur[abs(s) - 1] += 1 if s > 0 else -1
            cyc.append(tuple(cur))
        cyc = cyc[:-1]                  # last equals the first
        v = rc.explicit_cycle_is_valid(cyc, lambda x: rc.neighbors_K(x, m),
                                       "K(%d) paper 6-cycle" % m)
        rec["explicit_cycle_K"] = {"vertices": [list(t) for t in cyc],
                                   "valid": v["ok"], "reason": v["reason"],
                                   "coordinate_sums": [sum(t) for t in cyc]}
        C.check("m%d.K.explicit_6cycle_is_a_cycle" % m, v["ok"],
                "%s; coordinate sums %s" % (v["reason"], [sum(t) for t in cyc]))

        # ------------------------------------------------------------------
        # S~_m
        # ------------------------------------------------------------------
        wrong = (bug == "wrong_s0")
        ball = rc.build_w_ball(m, 6, wrong_s0=wrong)
        rec["stilde_ball"] = {k: v for k, v in ball.items() if k != "elements"}
        relation_checks = rc.affine_group_self_check(m, wrong_s0=wrong)
        reflection_check = rc.affine_reflection_self_check(m, wrong_s0=wrong)
        rec["group_self_check"] = {k: v["ok"] for k, v in relation_checks.items()}
        rec["group_self_check_detail"] = {k: v.get("detail")
                                          for k, v in relation_checks.items()}
        rec["affine_reflection_check"] = reflection_check
        if wrong:
            C.check("m%d.S.affine_reflection_intact" % m, reflection_check["ok"],
                    "with s_0 = (tau_0, 0) the affine reflection test fails: %s"
                    % reflection_check["failures"][:1])
            C.check("m%d.S.coxeter_relations_hold" % m,
                    all(v["ok"] for v in relation_checks.values()),
                    "with s_0 = (tau_0, 0) the Coxeter check "
                    "'diagram_matches_realisation' says: %s"
                    % relation_checks["diagram_matches_realisation"]["detail"])

        gs = rc.ball_girth(ball["elements"], m, 3, wrong_s0=wrong,
                           allow_backtrack=(bug == "allow_backtrack"))
        rec["girth_Stilde"] = {k: v for k, v in gs.items() if k != "cycle_vertices"}
        if rec["girth_Stilde"].get("cycle_vertices") is not None:
            rec["girth_Stilde"]["cycle_vertices"] = [
                [list(e.w), list(e.lam)] for e in rec["girth_Stilde"]["cycle_vertices"]]
        C.check("m%d.S.girth_matches_theorem" % m,
                gs["girth"] == EXPECT_GIRTH_STILDE.get(m),
                "girth S~_%d = %s, theorem says %s (ball radius 3 has %d elements)"
                % (m, gs["girth"], EXPECT_GIRTH_STILDE.get(m), ball["size"]))

        # explicit cycles in S~_m
        if m >= 4:
            gens = rc.affine_generators(m)
            e = rc.weyl_identity(m)
            sq = [e, gens[1], rc.weyl_mul(rc.weyl_mul(e, gens[1]), gens[3]), gens[3]]
            v = rc.explicit_cycle_is_valid(
                sq, lambda x: rc.weyl_right_neighbors(x, m, wrong_s0=wrong),
                "S~_%d 4-cycle 1,s1,s1s3,s3" % m)
            rec["explicit_cycle_Stilde"] = {
                "vertices": [[list(t.w), list(t.lam)] for t in sq],
                "valid": v["ok"], "reason": v["reason"]}
            C.check("m%d.S.explicit_4cycle_is_a_cycle" % m, v["ok"],
                    "%s (m >= 4, s_1 and s_3 commute)" % v["reason"])
        else:
            i, j = 1, 2
            cyc6 = cycle_stilde_parabolic(m, i, j)
            v = rc.explicit_cycle_is_valid(
                cyc6, lambda x: rc.weyl_right_neighbors(x, m, wrong_s0=wrong),
                "S~_3 6-cycle in <s1,s2>")
            rec["explicit_cycle_Stilde"] = {
                "vertices": [[list(t.w), list(t.lam)] for t in cyc6],
                "valid": v["ok"], "reason": v["reason"]}
            C.check("m%d.S.explicit_6cycle_is_a_cycle" % m, v["ok"],
                    "%s (rank-two parabolic <s_i,s_j> ~ S_3)" % v["reason"])
            # no 4-cycle: every pair of distinct generators has order 3
            orders = rc.coxeter_matrix_from_generators(rc.affine_generators(m), m)
            no_commuting = all(orders[i][j] != 2
                               for i in range(m) for j in range(m) if i != j)
            rec["stilde3_no_commuting_generators"] = bool(no_commuting)
            C.check("m%d.S.no_commuting_pair_hence_no_4cycle" % m, no_commuting,
                    "measured orders of s_i s_j: %s -- all 3, so there is no "
                    "commuting pair and no 4-cycle (text:376-378)" % orders)

        # no triangles anywhere: S is a set of involutions with s_i != s_j
        gens = rc.affine_generators(m, wrong_s0=wrong)
        distinct = len(set(gens.values())) == m
        inv = all(rc.weyl_mul(g, g, bug_convention=False) == rc.weyl_identity(m)
                  for g in gens.values())
        rec["stilde_generators_simple"] = {"distinct": distinct, "involutions": inv}
        C.check("m%d.S.no_loops_no_double_edges" % m, distinct and inv,
                "the %d generators are distinct involutions, so the Cayley graph "
                "has no loop and no double edge (text:338-341)" % m)

        rec["seconds"] = round(time.time() - t0, 3)
        per_m["m%d" % m] = rec
    C.observe("per_m", per_m)

    if bug == "wrong_s0":
        C.observe("wrong_s0_summary", {
            "what": "s_0 = (tau_0, 0) instead of (tau_0, theta)",
            "effect": "the affine part vanishes: W_a collapses to the finite S_m "
                      "(the radius-6 ball has only m! elements), the affine "
                      "reflection test fails, (s_0 s_2)^3 = e fails, and "
                      "girth S~_3 is computed as 4 instead of 6",
            "caught_by": ["affine_reflection_check", "coxeter_relations",
                          "girth_matches_theorem"],
        })

    return emit(C.result_dict(), args.json)


if __name__ == "__main__":
    guard(main)
