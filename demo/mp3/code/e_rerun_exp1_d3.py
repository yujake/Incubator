#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""e_rerun_exp1_d3: independent re-run of the d=3 group of exp:000001 (the G8 gap).

Claim under test (numeric, cross_check level): for g = abelian_3, heisenberg_3,
sl2 and n = 0..8, dim U(g)_{<=n} = C(n+3,3) = 1,4,10,20,35,56,84,120,165,
so growth is polynomial of degree exactly 3 (third finite difference = 1,
fourth = 0).  NOTE: nothing here proves the filtration ring is Noetherian.

Method (deliberately different from code/e2_finite_dim_growth.py): PBW
normal-form rewriting inside U(g): X_j X_i = X_i X_j + [X_j, X_i] for i < j.
Then dim U(g)_{<=n} = rank of the images of all words of length <= n.
Rank is computed twice, over GF(2147483647) and GF(1000000007).  Sandwich:
rank_p <= rank_Q <= #{sorted monomials of length <= n} = C(n+3,3); equality at
one prime pins the exact rational rank.  The second prime guards against a
prime-specific accident.

Every number below is produced by this script; no LLM verdicts.
Prints PROGRESS lines and one REPRO_RESULT line.
"""
import json
import time
from math import comb, log

P1 = 2147483647
P2 = 1000000007
ALGS = [
    ("abelian_dim3", 3, {}),
    ("heisenberg_dim3", 3, {(0, 1): [(2, 1)]}),
    ("sl2_dim3", 3, {(0, 1): [(2, 1)], (0, 2): [(0, -2)], (1, 2): [(1, 2)]}),
]


def make_norm(d, br):
    memo = {}

    def norm(w):
        r = memo.get(w)
        if r is not None:
            return r
        for idx in range(len(w) - 1):
            if w[idx] > w[idx + 1]:
                j, i = w[idx], w[idx + 1]
                out = {}
                for kk, c in norm(w[:idx] + (i, j) + w[idx + 2:]).items():
                    out[kk] = out.get(kk, 0) + c
                for (k, c) in br.get((i, j), ()):
                    for kk, cc in norm(w[:idx] + (k,) + w[idx + 2:]).items():
                        out[kk] = out.get(kk, 0) - c * cc
                out = dict((k, v) for k, v in out.items() if v)
                memo[w] = out
                return out
        memo[w] = {w: 1}
        return memo[w]

    return norm


def all_words(d, n):
    out = [()]
    frontier = [()]
    for _ in range(n):
        nxt = []
        for w in frontier:
            for g in range(d):
                nxt.append(w + (g,))
        out.extend(nxt)
        frontier = nxt
    return out


def rank_mod(vectors, p):
    basis = {}
    for vec in vectors:
        v = dict((k, c % p) for k, c in vec.items() if c % p)
        while v:
            piv = min(v)
            f = v[piv]
            b = basis.get(piv)
            if b is None:
                fi = pow(f, p - 2, p)
                basis[piv] = dict((k, (c * fi) % p) for k, c in v.items())
                break
            for k, c in b.items():
                nv = (v.get(k, 0) - f * c) % p
                if nv:
                    v[k] = nv
                elif k in v:
                    del v[k]
    return len(basis)


def main():
    nmax = 8
    report = []
    scaling = {}
    ok_all = True
    counterexample = None
    t_start = time.time()
    for (name, d, br) in ALGS:
        norm = make_norm(d, br)
        dims = {}
        detail = []
        for n in range(0, nmax + 1):
            t0 = time.time()
            words = all_words(d, n)
            raws = [norm(w) for w in words]
            r1 = rank_mod(raws, P1)
            r2 = rank_mod(raws, P2)
            expected = comb(n + d, d)
            ok = (r1 == expected and r2 == expected)
            ok_all = ok_all and ok
            dims[n] = r1
            detail.append({"n": n, "words": len(words), "rank_p1": r1, "rank_p2": r2,
                           "expected_C(n+d,d)": expected, "ok": ok,
                           "sec": round(time.time() - t0, 4)})
            print("PROGRESS " + json.dumps({"algebra": name, "n": n, "rank": r1,
                                            "expected": expected,
                                            "sec": round(time.time() - t0, 4)}))
            if not ok and counterexample is None:
                counterexample = {"algebra": name, "n": n, "rank_p1": r1, "rank_p2": r2,
                                  "expected": expected}
        seq = [dims[n] for n in range(0, nmax + 1)]
        d1 = [seq[i + 1] - seq[i] for i in range(len(seq) - 1)]
        d2 = [d1[i + 1] - d1[i] for i in range(len(d1) - 1)]
        d3 = [d2[i + 1] - d2[i] for i in range(len(d2) - 1)]
        d4 = [d3[i + 1] - d3[i] for i in range(len(d3) - 1)]
        deg = 3 if (d3 and len(set(d3)) == 1 and d3[0] != 0 and all(x == 0 for x in d4)) else None
        if deg != d:
            ok_all = False
            if counterexample is None:
                counterexample = {"algebra": name, "finite_difference_degree": deg,
                                  "expected_degree": d,
                                  "third_differences": d3, "fourth_differences": d4}
        gk = round(log(dims[nmax]) / log(nmax), 3) if nmax > 1 else None
        report.append({"algebra": name, "dim_g": d,
                       "dim_U_le_n": dict((str(k), v) for k, v in dims.items()),
                       "matches_C(n+d,d)": all(x["ok"] for x in detail),
                       "finite_difference_degree": deg,
                       "gk_dim_log_estimate": gk,
                       "note_gk": "log(dim)/log(n) is a crude reading only; the exact statement here is the finite-difference degree",
                       "detail": detail})
        scaling[name] = {"n_max": nmax,
                         "words_total": sum(x["words"] for x in detail),
                         "seconds_total": round(sum(x["sec"] for x in detail), 4),
                         "seconds_per_n": dict((str(x["n"]), x["sec"]) for x in detail)}
    bound = {"n_max": nmax, "n_range": [0, nmax], "dim_g": 3,
             "algebras": [a[0] for a in ALGS],
             "words_enumeration": "all words of length <= n over d generators (filter degree not truncated)",
             "rank_method": "two primes GF(2147483647) and GF(1000000007)",
             "sandwich": "rank_p <= rank_Q <= #sorted monomials of length <= n = C(n+d,d); equality at one prime pins rank_Q",
             "scope": "d=3 groups only; does NOT address Noetherian-ness of the filtration ring"}
    strategy = "PBW normal-form rewriting (exact integer coefficients) + echelon rank over two prime fields (double-prime sandwich)"
    payload = {"result": "supports" if ok_all else "refutes",
               "bound": bound, "strategy": strategy, "scaling": scaling,
               "data": {"algebras": report,
                        "total_seconds": round(time.time() - t_start, 3)}}
    if not ok_all:
        payload["counterexample"] = counterexample
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
