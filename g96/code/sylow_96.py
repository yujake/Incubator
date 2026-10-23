#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sylow_96.py -- deterministic Sylow counting for |G| = 96 = 2^5 * 3.

Pure Python 3.  No network, no GAP, no randomness, no external data files.
Every number printed here or written to the CSV is computed by this script.

What it decides:
  (1) all solutions of  n_3 | 32  with  n_3 = 1 (mod 3),
      and of  n_2 | 3  with  n_2 odd;
  (2) for the six cells (n_3, n_2):  |N_G(Q)| = 96/n_3  (Q in Syl_3),
      |N_G(P)| = 96/n_2  (P in Syl_2), and the orbit-stabiliser identity
      n_3 = [G : N_G(Q)] = 96/|N_G(Q)|  (same for n_2);
  (3) for every cell, under the extra hypothesis
      H : distinct Sylow 3-subgroups of G intersect in the identity,
      the number of elements of order 3 is exactly 2*n_3; the remaining
      96 - 2*n_3 elements split as (#2-elements) + (#elements of order
      divisible by 3 and > 3), and bounds for those two numbers follow from
      |Syl_2| = 32 and the union bound 1 + 31*n_2 on the union of the Sylow
      2-subgroups;
  (4) CSV  out/sylow_96.csv : cell -> decidable invariants.

Explicitly NOT decided here (reported as unverified, never as proved):
  - the number of isomorphism classes of groups of order 32 (claimed 51);
  - the number of isomorphism classes of groups of order 96 (claimed 231);
  - which of the six cells are actually realised by some group of order 96.
  These need a group library / enumeration of isomorphism classes (GAP);
  a pure-Python script on this machine cannot settle them.
"""

import csv
import json
import os
import sys
import time

ORDER = 96
T0 = time.time()


def factorise(n):
    fac = {}
    d = 2
    while d * d <= n:
        while n % d == 0:
            fac[d] = fac.get(d, 0) + 1
            n //= d
        d += 1
    if n > 1:
        fac[n] = fac.get(n, 0) + 1
    return fac


def divisors(n):
    return [d for d in range(1, n + 1) if n % d == 0]


def main():
    checks = []

    def chk(name, cond, detail):
        checks.append({"check": name, "ok": bool(cond), "detail": str(detail)})
        return bool(cond)

    print("=== Sylow counting for |G| = %d ===" % ORDER)

    fac = factorise(ORDER)
    fac_txt = " * ".join("%d^%d" % (p, e) for p, e in sorted(fac.items()))
    chk("factorisation 96 = 2^5 * 3", fac == {2: 5, 3: 1}, fac_txt)
    print("(0) factorisation by trial division: %d = %s" % (ORDER, fac_txt))

    D32 = divisors(32)
    D3 = divisors(3)
    n3_set = [d for d in D32 if d % 3 == 1]
    n2_set = [d for d in D3 if d % 2 == 1]

    chk("n_3 solutions", n3_set == [1, 4, 16], n3_set)
    chk("n_2 solutions", n2_set == [1, 3], n2_set)
    print("(1) divisors(32) = %s ; those = 1 mod 3 : n_3 in %s" % (D32, n3_set))
    print("(1) divisors(3)  = %s ; those odd       : n_2 in %s" % (D3, n2_set))

    all_orders = divisors(ORDER)
    two_part = [m for m in all_orders if m % 3 != 0]
    three_part = [m for m in all_orders if m % 3 == 0]
    chk("order spectrum divides 96",
        two_part == [1, 2, 4, 8, 16, 32] and three_part == [3, 6, 12, 24, 48, 96],
        "%s" % all_orders)
    print("(spectrum) element orders must divide 96 (Lagrange): %s" % all_orders)
    print("           orders coprime to 3: %s ; orders divisible by 3: %s" % (two_part, three_part))

    SYL2 = ORDER // 3  # = 32, the order of every Sylow 2-subgroup

    rows = []
    for n3 in n3_set:
        for n2 in n2_set:
            t_cell = time.time()
            NGQ = ORDER // n3          # |N_G(Q)| for Q in Syl_3(G)
            NGP = ORDER // n2          # |N_G(P)| for P in Syl_2(G)
            idxQ = ORDER // NGQ        # [G : N_G(Q)]
            idxP = ORDER // NGP        # [G : N_G(P)]
            identity_ok = (idxQ == n3 and idxP == n2
                           and NGQ * n3 == ORDER and NGP * n2 == ORDER)
            chk("orbit-stabiliser identity n_3=%d n_2=%d" % (n3, n2), identity_ok,
                "|N_G(Q)|=%d [G:N_G(Q)]=%d ; |N_G(P)|=%d [G:N_G(P)]=%d" % (NGQ, idxQ, NGP, idxP))

            # --- (3) under H: distinct Sylow 3-subgroups intersect trivially ----
            # 3 || 96, so every Sylow 3-subgroup is cyclic of order 3 and has
            # exactly 2 elements of order 3.  Under H these 2*n3 elements are
            # pairwise distinct, and they exhaust the elements of 3-power order.
            count_order3 = 2 * n3                 # #elements of order 3, iff H holds
            sylow3_union = 1 + 2 * n3             # |union of the Sylow 3-subgroups|, iff H holds
            leftover = ORDER - count_order3       # elements that are NOT of order 3
            # Always (even without H) the count of order-3 elements is <= 2*n3.
            order3_bound_general = 2 * n3

            # --- 2-part structure of the leftovers -------------------------------
            B_min = SYL2                                   # a Sylow 2-subgroup has 32 elements
            B_max_union = 1 + n2 * (SYL2 - 1)              # union bound: all Sylow 2's share 1
            B_max = min(B_max_union, leftover)
            B_forced = SYL2 if n2 == 1 else None           # unique Sylow 2 is normal = all 2-elements
            feasible = (B_max >= B_min)
            if B_forced is not None:
                feasible = feasible and (leftover >= B_forced)
                C_min = C_max = leftover - B_forced
            else:
                C_min = leftover - B_max
                C_max = leftover - B_min
            chk("counting feasibility n_3=%d n_2=%d" % (n3, n2), feasible,
                "leftover=%d, 2-elements B in [%d,%d], 3-divisible-of-order>3 C in [%d,%d]"
                % (leftover, B_min, B_max, C_min, C_max))

            if n3 == 1:
                H_note = "vacuous: with n_3=1 there is only one Sylow 3-subgroup"
            else:
                H_note = "hypothesis on G; NOT decidable from the pair (n_3,n_2)"

            row = {
                "cell": "n3=%d,n2=%d" % (n3, n2),
                "n3": n3,
                "n2": n2,
                "NGQ": NGQ,
                "NGP": NGP,
                "index_Q": idxQ,
                "index_P": idxP,
                "identity_ok": identity_ok,
                "count_order3_iff_H": count_order3,
                "count_order3_bound_general": order3_bound_general,
                "sylow3_union_size_iff_H": sylow3_union,
                "leftover_not_order3": leftover,
                "two_elements_min": B_min,
                "two_elements_max": B_max,
                "two_elements_forced": "" if B_forced is None else B_forced,
                "order3div_gt3_min": C_min,
                "order3div_gt3_max": C_max,
                "counting_feasible": feasible,
                "H_status": H_note,
                "candidate_order_spectrum": "1,2,3,4,6,8,12,16,24,32,48,96",
            }
            rows.append(row)

            print("--- cell (n_3, n_2) = (%d, %d) ---" % (n3, n2))
            print("    |N_G(Q)| = 96/%d = %d ; [G:N_G(Q)] = %d  (= n_3 ? %s)"
                  % (n3, NGQ, idxQ, idxQ == n3))
            print("    |N_G(P)| = 96/%d = %d ; [G:N_G(P)] = %d  (= n_2 ? %s)"
                  % (n2, NGP, idxP, idxP == n2))
            print("    H assumed (%s)" % H_note)
            print("    #elements of order 3 = 2*%d = %d (<= %d always); |union Syl_3| = 1+2*%d = %d"
                  % (n3, count_order3, order3_bound_general, n3, sylow3_union))
            print("    leftover 96-%d = %d elements not of order 3, split into"
                  " (#2-elements B) + (#order divisible by 3 but >3 : C)" % (count_order3, leftover))
            print("    B in [%d, %d]%s ; C in [%d, %d] ; counting feasible: %s"
                  % (B_min, B_max,
                     " (forced to %d: n_2=1 => unique Sylow 2 is normal)" % B_forced if B_forced else "",
                     C_min, C_max, feasible))
            print("PROGRESS: " + json.dumps({"cell": row["cell"], "n3": n3, "n2": n2,
                                             "NGQ": NGQ, "NGP": NGP,
                                             "order3": count_order3, "leftover": leftover,
                                             "B_range": [B_min, B_max],
                                             "C_range": [C_min, C_max],
                                             "feasible": feasible,
                                             "seconds": round(time.time() - t_cell, 5)},
                                            sort_keys=True))

    # ------------------------------ (4) CSV ---------------------------------
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.normpath(os.path.join(script_dir, "..", "out"))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        out_dir = os.path.abspath("out")
        os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "sylow_96.csv")
    fieldnames = list(rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print("(4) CSV written to %s (%d rows, %d columns)" % (csv_path, len(rows), len(fieldnames)))
    with open(csv_path, "r", encoding="utf-8") as fh:
        for line in fh:
            print("CSV| " + line.rstrip("\n"))

    ok_all = all(c["ok"] for c in checks)
    rel_csv = "out/sylow_96.csv"
    summary = {
        "result": "supports" if ok_all else "inconclusive",
        "claim_key": "sylow96-counting",
        "group_order": ORDER,
        "n3_solutions": n3_set,
        "n2_solutions": n2_set,
        "cells": [r["cell"] for r in rows],
        "normalizer_orders": {r["cell"]: [r["NGQ"], r["NGP"]] for r in rows},
        "order3_counts_iff_H": {r["cell"]: r["count_order3_iff_H"] for r in rows},
        "leftover_not_order3": {r["cell"]: r["leftover_not_order3"] for r in rows},
        "two_elements_range": {r["cell"]: [r["two_elements_min"], r["two_elements_max"]] for r in rows},
        "order3div_gt3_range": {r["cell"]: [r["order3div_gt3_min"], r["order3div_gt3_max"]] for r in rows},
        "checks_passed": sum(1 for c in checks if c["ok"]),
        "checks_total": len(checks),
        "csv": rel_csv,
        "unverified": [
            "number of isomorphism classes of groups of order 32 (the value 51 is NOT verified here)",
            "number of isomorphism classes of groups of order 96 (the value 231 is NOT verified here)",
            "which cells (n_3,n_2) are realised by an actual group of order 96",
        ],
        "bound": "exhaustive over divisors(32) and divisors(3); counting bounds from |Syl_2|=32 and union bound 1+31*n_2",
        "strategy": "brute force divisor enumeration + inclusion-exclusion + union bound",
        "scaling": {"cells": len(rows), "seconds": round(time.time() - T0, 4)},
    }
    print("checks: %d/%d passed" % (summary["checks_passed"], summary["checks_total"]))
    print("REPRO_RESULT: " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    if not ok_all:
        for c in checks:
            if not c["ok"]:
                print("FAILED CHECK: %s :: %s" % (c["check"], c["detail"]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
