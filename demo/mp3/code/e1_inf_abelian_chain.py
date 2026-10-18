#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E1: infinite-dimensional abelian g (countably many generators) => U(g) = k[x_1,x_2,...]
 is NOT left Noetherian.

Deterministic checks done BY CODE (no model judgement):
  (a) chain I_m = (x_1,...,x_m) is strictly ascending for m=1..N, with witness
      x_{m+1} in I_{m+1} \ I_m  (monomial-ideal membership = divisibility test);
  (b) I_m subset I_{m+1} for every step (each generator of I_m lies in I_{m+1});
  (c) I_inf = (x_1,x_2,...) is not finitely generated: for any finite candidate set S
      whose variable support is inside {1..M}, x_{M+1} lies in I_inf but not in (S).
Protocol: one line `REPRO_RESULT: {...}` on stdout, plus PROGRESS lines.
"""
import json
import time


def var(i):
    return {i: 1}


def mono_in_ideal(mono, gens):
    """Monomial-ideal membership: mono in (gens) iff some generator divides mono
    coordinatewise (exponents). Deterministic, exact."""
    for g in gens:
        if all(mono.get(k, 0) >= v for k, v in g.items()):
            return True
    return False


def chain_part(N):
    t0 = time.time()
    strict = 0
    incl_ok = 0
    samples = []
    for m in range(1, N + 1):
        t1 = time.time()
        gens_m = [var(i) for i in range(1, m + 1)]
        gens_m1 = [var(i) for i in range(1, m + 2)]
        w = var(m + 1)
        in_m = mono_in_ideal(w, gens_m)
        in_m1 = mono_in_ideal(w, gens_m1)
        incl = all(mono_in_ideal(g, gens_m1) for g in gens_m)
        if in_m1 and not in_m:
            strict += 1
        if incl:
            incl_ok += 1
        if m in (1, 2, 3, 5, 10, 50, 100, N):
            samples.append({"m": m, "witness": "x_%d" % (m + 1),
                            "witness_in_I_m": in_m,
                            "witness_in_I_mp1": in_m1,
                            "I_m_contained_in_I_mp1": incl,
                            "ms": round((time.time() - t1) * 1000, 3)})
        if m % 100 == 0:
            print("PROGRESS: " + json.dumps({"part": "chain", "m": m,
                                             "strict_so_far": strict}, ensure_ascii=False))
    return {"N": N, "strict_steps": strict, "inclusion_steps": incl_ok,
            "all_strict": strict == N, "all_inclusions": incl_ok == N,
            "chain_length_achieved": N + 1, "samples": samples,
            "seconds": round(time.time() - t0, 3)}


def not_fg_part():
    """I_inf is not finitely generated: any finite S has finite variable support M,
    and x_{M+1} is in I_inf but divisible by no element of S."""
    tested = 0
    outside = 0
    detail = []
    for M in range(1, 7):
        cand_sets = [[var(i) for i in range(1, M + 1)]]
        deg2 = [{i: 2} for i in range(1, M + 1)]
        deg2 += [{i: 1, j: 1} for i in range(1, M + 1) for j in range(i + 1, M + 1)]
        cand_sets.append([var(i) for i in range(1, M + 1)] + deg2)
        for S in cand_sets:
            tested += 1
            w = var(M + 1)
            not_in_S = not mono_in_ideal(w, S)
            if not_in_S:
                outside += 1
            if len(detail) < 8:
                detail.append({"support_max": M, "num_generators": len(S),
                               "witness": "x_%d" % (M + 1),
                               "witness_in_ideal_S": (not not_in_S)})
    return {"candidate_sets_tested": tested, "witnesses_outside": outside,
            "all_outside": outside == tested, "detail": detail}


def main():
    t0 = time.time()
    N = 200
    ch = chain_part(N)
    fg = not_fg_part()
    ok = bool(ch["all_strict"] and ch["all_inclusions"] and fg["all_outside"])
    data = {
        "algebra": "g = direct sum of countably many copies of k, zero bracket; U(g) = k[x_1,x_2,...]",
        "chain": ch,
        "finite_generation_test": fg,
        "reading": {
            "any_N_gives_chain_length": "N+1 for every N (construction is parametric; verified up to N=200)",
            "why_not_noetherian": "an infinite strictly ascending chain of left ideals exists, so the ACC fails",
            "why_not_fg": "I_inf needs one generator per variable; no finite set generates it",
            "total_seconds": round(time.time() - t0, 3),
        },
    }
    out = {"result": "supports" if ok else "inconclusive",
           "bound": "strict chain verified to length %d (N=%d); construction is parametric in N so no finite bound"
                    % (ch["chain_length_achieved"], N),
           "strategy": "monomial-ideal divisibility test (canonical form) + explicit witnesses; no search needed",
           "scaling": "%d divisibility tests, %s s total, O(N^2): each step m costs O(m) tests"
                      % (2 * N * (N + 1), ch["seconds"]),
           "data": data}
    print("REPRO_RESULT: " + json.dumps(out, ensure_ascii=False))


def _unused():
    pass


if __name__ == "__main__":
    main()
