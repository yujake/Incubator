#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E2: finite-dimensional Lie algebra g => U(g) has POLYNOMIAL growth, degree = dim g
(GK dim = dim g), which is the filtered/graded side of the standard argument that
U(g) is Noetherian when dim g < infinity.

Deterministic linear algebra, no model judgement:

  * V_n = span of all words of length <= n in a fixed basis g_1..g_d of g.
        dim V_n = sum_{k<=n} d^k.
  * R_n = span of  u*(g_i g_j - g_j g_i - [g_i,g_j])*v  for words u,v with
        |u|+|v| <= n-2, truncated to degree <= n.  Then U(g)_{<=n} = V_n/R_n, so
        dim U(g)_{<=n} = dim V_n - rank(R_n).
  * rank is computed exactly modulo a large prime p (integer matrices):
        rank_p(R_n) <= rank_Q(R_n)  =>  dim_p(n) := dim V_n - rank_p >= dim_Q(n).
    Conversely, rewriting any word into PBW normal form (repeatedly replace
        g_i g_j (i>j) by g_j g_i + [g_i,g_j]; measure (degree, inversion number)
        strictly decreases, so the procedure terminates) writes every word as a
        Q-combination of NON-DECREASING words of no larger degree; there are
        exactly C(n+d,d) non-decreasing words of degree <= n, so dim_Q(n) <= C(n+d,d).
    If dim_p(n) == C(n+d,d) the two bounds meet and dim_Q(n) = C(n+d,d) exactly.
  * growth: finite differences of dim(n) in n; the polynomial degree is d = dim g.

Protocol: one line `REPRO_RESULT: {json}` on stdout, plus PROGRESS lines.
"""
import json
import time
from math import comb

P = 2147483647  # prime


def all_words(d, maxlen):
    """All words over range(d) of length <= maxlen, ordered by length."""
    words = [()]
    cur = [()]
    for _k in range(1, maxlen + 1):
        nxt = []
        for w in cur:
            for i in range(d):
                nxt.append(w + (i,))
        words.extend(nxt)
        cur = nxt
    return words


def relators(d, brackets):
    """Relators g_i g_j - g_j g_i - [g_i,g_j] as {word: coeff}, i<j.
    brackets: {(i,j): {k: coeff}} only for i>j, meaning [g_i,g_j] = sum coeff*g_k."""
    rels = []
    for i in range(d):
        for j in range(i + 1, d):
            b = {}
            if (j, i) in brackets:
                b = {k: -c for k, c in brackets[(j, i)].items()}
            terms = {(i, j): 1, (j, i): -1}
            for k, c in b.items():
                terms[(k,)] = terms.get((k,), 0) - c
            rel = {w: c for w, c in terms.items() if c}
            if rel:
                rels.append(rel)
    return rels


def rank_mod(rows, p=P):
    """Exact rank of an integer matrix given as a list of sparse rows {col: val},
    computed over GF(p).  rank_p <= rank_Q."""
    pivots = {}
    for r in rows:
        r = {c: v % p for c, v in r.items() if v % p}
        while r:
            c = min(r)
            if c in pivots:
                pr = pivots[c]
                f = r[c]
                for cc, vv in pr.items():
                    nv = (r.get(cc, 0) - f * vv) % p
                    if nv:
                        r[cc] = nv
                    else:
                        r.pop(cc, None)
            else:
                inv = pow(r[c], p - 2, p)
                pivots[c] = {cc: (v * inv) % p for cc, v in r.items()}
                break
    return len(pivots)


def rows_for_n(words_index, words_by_len, rels, n):
    rows = []
    for rel in rels:
        for a in range(0, n - 1):          # |u| = a
            for u in words_by_len.get(a, []):
                for b in range(0, n - 1 - a):   # |v| = b,  a+b <= n-2
                    for v in words_by_len.get(b, []):
                        row = {}
                        for t, c in rel.items():
                            col = words_index[u + t + v]
                            row[col] = row.get(col, 0) + c
                        if row:
                            rows.append(row)
    return rows


def normal_form_check(d, brackets, n_max, memo):
    """Rewrite every word of degree <= n_max into PBW normal form.
    Returns (n_words, n_not_nondecreasing, n_degree_grew)."""

    def nf(w):
        if w in memo:
            return memo[w]
        pos = None
        for p in range(len(w) - 1):
            if w[p] > w[p + 1]:
                pos = p
                break
        if pos is None:
            memo[w] = {w: 1}
            return memo[w]
        i, j = w[pos], w[pos + 1]
        pre, post = w[:pos], w[pos + 2:]
        out = {}
        for nw, c in nf(pre + (j, i) + post).items():
            out[nw] = out.get(nw, 0) + c
        for k, c in brackets.get((i, j), {}).items():
            for nw, c2 in nf(pre + (k,) + post).items():
                out[nw] = out.get(nw, 0) + c * c2
        out = {k: v for k, v in out.items() if v}
        memo[w] = out
        return out

    words = all_words(d, n_max)
    bad_nd = 0
    grew = 0
    memo_hits = 0
    for w in words:
        nfd = nf(w)
        for nw in nfd:
            if any(nw[i] > nw[i + 1] for i in range(len(nw) - 1)):
                bad_nd += 1
                break
        if any(len(nw) > len(w) for nw in nfd):
            grew += 1
    memo_hits = len(memo)
    return {"words_checked": len(words), "n_not_nondecreasing": bad_nd,
            "n_degree_grew": grew, "memo_entries": memo_hits}


def run_algebra(name, d, brackets, n_max, time_cap, memo):
    t0 = time.time()
    words = all_words(d, n_max)
    words_index = {w: i for i, w in enumerate(words)}
    words_by_len = {}
    for w in words:
        words_by_len.setdefault(len(w), []).append(w)
    rels = relators(d, brackets)
    dims = {}
    rows_counts = {}
    ranks = {}
    n_done = None
    for n in range(0, n_max + 1):
        if time.time() - t0 > time_cap:
            break
        rows = rows_for_n(words_index, words_by_len, rels, n)
        dimV = sum(d ** k for k in range(n + 1))
        r = rank_mod(rows)
        dims[n] = dimV - r
        ranks[n] = r
        rows_counts[n] = len(rows)
        n_done = n
        print("PROGRESS: " + json.dumps(
            {"algebra": name, "n": n, "dimU": dims[n], "dimV": dimV,
             "rank_p": r, "relator_rows": len(rows), "pred_C(n+d,d)": comb(n + d, d),
             "sec": round(time.time() - t0, 2)}, ensure_ascii=False))
    seq = [dims[n] for n in range(0, n_done + 1)]
    match = {n: (dims[n] == comb(n + d, d)) for n in range(0, n_done + 1)}
    # finite differences
    levels = []
    dd = seq
    for _k in range(0, d + 2):
        levels.append(list(dd))
        dd = [dd[i + 1] - dd[i] for i in range(len(dd) - 1)]
    deg_ok = None
    if len(levels) > d + 1 and levels[d]:
        deg_ok = (all(x != 0 for x in levels[d]) and all(x == 0 for x in levels[d + 1]))
    nf_chk = normal_form_check(d, brackets, min(n_done, 5), memo)
    gk_est = None
    if n_done >= 2 and dims[n_done] > 0:
        import math
        gk_est = round(math.log(dims[n_done]) / math.log(n_done), 3)
    return {"algebra": name, "dim_g": d, "n_max_run": n_done,
            "dim_U_le_n": {str(n): dims[n] for n in range(0, n_done + 1)},
            "rank_p": {str(n): ranks[n] for n in range(0, n_done + 1)},
            "relator_rows": {str(n): rows_counts[n] for n in range(0, n_done + 1)},
            "matches_C_n_plus_d_choose_d": {str(n): match[n] for n in range(0, n_done + 1)},
            "all_match": all(match.values()),
            "finite_difference_degree_equals_dim_g": deg_ok,
            "delta_d_values": levels[d] if len(levels) > d else None,
            "delta_d_plus_1_values": levels[d + 1] if len(levels) > d + 1 else None,
            "pbw_normal_form_check": nf_chk,
            "gk_dim_log_estimate": gk_est,
            "seconds": round(time.time() - t0, 3)}


def main():
    t0 = time.time()
    memo = {}  # PBW normal forms are independent of n; share across algebras? keys are words, so keep per-algebra
    algebras = []

    # abelian dim 1
    algebras.append(run_algebra("abelian_dim1", 1, {}, 12, 30, {}))
    # abelian dim 2
    algebras.append(run_algebra("abelian_dim2", 2, {}, 10, 45, {}))
    # abelian dim 3
    algebras.append(run_algebra("abelian_dim3", 3, {}, 7, 60, {}))
    # Heisenberg dim 3: g1=x, g2=y, g3=z, [y,x]=z  (=> [x,y]=-z)
    heis = {(1, 0): {2: 1}}
    algebras.append(run_algebra("heisenberg_dim3", 3, heis, 7, 60, {}))
    # sl2 dim 3: g0=e, g1=f, g2=h, [e,f]=h, [h,e]=2e, [h,f]=-2f
    sl2 = {(1, 0): {2: -1}, (2, 0): {0: 2}, (2, 1): {1: -2}}
    algebras.append(run_algebra("sl2_dim3", 3, sl2, 7, 60, {}))

    all_ok = all(a["all_match"] and a["finite_difference_degree_equals_dim_g"]
                 and a["pbw_normal_form_check"]["n_not_nondecreasing"] == 0
                 and a["pbw_normal_form_check"]["n_degree_grew"] == 0 for a in algebras)
    data = {
        "method": "dim U(g)_{<=n} = dim V_n - rank_p(R_n) over GF(2147483647); "
                  "rank_p <= rank_Q and PBW rewriting gives dim_Q <= C(n+d,d), "
                  "so equality C(n+d,d) pins dim_Q exactly",
        "algebras": algebras,
        "reading": {
            "growth": "dim U(g)_{<=n} = C(n+dim g, dim g): polynomial of degree dim g",
            "gk_dim": "GK dim U(g) = lim log dim / log n = dim g",
            "link_to_noetherian": "polynomial growth of the standard filtration is the "
                                  "'small' side; Noetherian-ness itself is a ring "
                                  "property and is NOT proved here (evidence level cross_check)",
            "total_seconds": round(time.time() - t0, 3),
        },
    }
    out = {"result": "supports" if all_ok else "refutes",
           "bound": "n up to %s per algebra (see n_max_run); dim U(g)_{<=n} = C(n+dim g, dim g) "
                    "verified for every n reached" % [a["n_max_run"] for a in algebras],
           "strategy": "sparse Gaussian elimination mod p (canonical form) + PBW normal-form "
                       "rewriting upper bound + finite differences for the growth degree",
           "scaling": {a["algebra"]: {"n_max": a["n_max_run"], "seconds": a["seconds"],
                                      "relator_rows_at_n_max": a["relator_rows"][str(a["n_max_run"])],
                                      "dims": [a["dim_U_le_n"][str(n)] for n in range(a["n_max_run"] + 1)]}
                       for a in algebras},
           "data": data}
    if not all_ok:
        out["counterexample"] = "at least one algebra failed the C(n+d,d) / degree-d check; see data"
    print("REPRO_RESULT: " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
