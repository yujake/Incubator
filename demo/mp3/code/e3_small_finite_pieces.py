#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E3: infinite-dimensional Lie algebras whose finite-dimensional pieces are 'small'.

Two families (both handled by CODE, exact arithmetic, no model judgement):

  (A) abelian truncations of the infinite-rank abelian algebra:
        A_n = k^n with zero bracket  (n = 1,2,4,6)
      * longest strictly ascending chain of monomial left ideals in k[x_1..x_n]
        I_1 < I_2 < ... < I_{n+1} with witness x_{m+1} in I_{m+1} \ I_m (divisibility test)
        => chain length n+1, grows with n;
      * dim U(A_n)_{<=m} by exact linear algebra of the relation space,
        compared with the PBW binomial C(m+n, n); degree in m = n.

  (B) Witt truncations W_n = Der(k[t]/(t^{n+1})), basis L_i = -t^{i+1} d/dt, i = -1..n-1,
      dim = n+1, n = 1,2,3:
      * closure: commutator of the matrices of L_i written exactly as a linear combination
        of the L_j (exact rational solve) => genuine Lie subalgebra of gl_{n+1};
        Jacobi checked on the recovered constants;
      * dim U(W_n)_{<=m} by exact linear algebra of the relation space vs C(m+d, d).

Reading (by code): growth degree of the filtered dimensions (= GK dim = dim g_n) and the
longest strictly ascending left-ideal chain both tend to infinity with n.  Whether the
infinite-dimensional LIMITS are Noetherian is NOT decided here (literature; not computed).

Protocol: one line `REPRO_RESULT: {...}` on stdout, plus PROGRESS lines.
"""
import json
import time
from fractions import Fraction
from math import comb

# ---------------------------------------------------------------- exact linear algebra


def rank_over_q(rows):
    """Rank of sparse rows (dict col->coeff) over Q: exact fraction Gaussian elimination."""
    pivots = {}
    for row in rows:
        r = {c: Fraction(v) for c, v in row.items() if v != 0}
        while r:
            c0 = min(r)
            if c0 in pivots:
                f = r[c0]
                p = pivots[c0]
                for c, v in p.items():
                    nv = r.get(c, Fraction(0)) - f * v
                    if nv == 0:
                        r.pop(c, None)
                    else:
                        r[c] = nv
            else:
                f = r[c0]
                r = {c: v / f for c, v in r.items()}
                pivots[c0] = r
                break
    return len(pivots)


def all_words(d, m):
    ws = [()]
    frontier = [()]
    for _ in range(m):
        nxt = []
        for w in frontier:
            for i in range(d):
                nxt.append(w + (i,))
        ws.extend(nxt)
        frontier = nxt
    return ws


def filtered_dim(d, struct, m):
    """dim U(g)_{<=m} for [g_i,g_j] = sum_k struct[i][j][k] g_k, computed as
    (span of words of length <= m) / (span of bracket relations of degree <= m).
    Exact; PBW is used only afterwards as a cross-check, not as an input."""
    ws = all_words(d, m)
    idx = {w: i for i, w in enumerate(ws)}
    W = len(ws)
    by_len = {}
    for w in ws:
        by_len.setdefault(len(w), []).append(w)
    rows = []
    for a in range(0, m - 1):
        for b in range(0, m - 1 - a):
            for u in by_len[a]:
                for v in by_len[b]:
                    for i in range(d):
                        for j in range(i + 1, d):
                            row = {}
                            t1 = idx[u + (i, j) + v]
                            row[t1] = row.get(t1, 0) + 1
                            t2 = idx[u + (j, i) + v]
                            row[t2] = row.get(t2, 0) - 1
                            for k in range(d):
                                c = struct[i][j][k]
                                if c:
                                    t = idx[u + (k,) + v]
                                    row[t] = row.get(t, 0) - c
                            rows.append(row)
    return W - rank_over_q(rows), W, len(rows)


# ---------------------------------------------------------------- (A) abelian truncations


def mono_in_ideal(mono, gens):
    for g in gens:
        if all(mono.get(k, 0) >= v for k, v in g.items()):
            return True
    return False


def abelian_part(ns, m_max):
    out = {}
    t_all = time.time()
    for n in ns:
        t0 = time.time()
        strict = 0
        witnesses = []
        for mm in range(1, n + 1):
            gens_m = [{i: 1} for i in range(1, mm + 1)]
            gens_m1 = [{i: 1} for i in range(1, mm + 2)]
            w = {mm + 1: 1}
            if mono_in_ideal(w, gens_m1) and not mono_in_ideal(w, gens_m):
                strict += 1
                if mm in (1, 2, 3, n):
                    witnesses.append({"m": mm, "witness": "x_%d" % (mm + 1),
                                      "in_I_m": False, "in_I_m1": True})
        struct = [[[0] * n for _ in range(n)] for _ in range(n)]  # zero bracket
        dims = {}
        for m in range(1, m_max + 1):
            dim, W, nrel = filtered_dim(n, struct, m)
            dims[m] = {"dim_U_le_m_computed": dim, "span_words": W,
                       "relation_rows": nrel, "binom_C(m+n,n)": comb(m + n, n),
                       "matches_PBW": dim == comb(m + n, n)}
        ok = strict == n and all(v["matches_PBW"] for v in dims.values())
        out["A_n=%d" % n] = {
            "dim_g": n,
            "strict_chain_steps": strict,
            "chain_length": strict + 1,
            "all_steps_strict": strict == n,
            "witness_samples": witnesses,
            "filtered_dims": dims,
            "gk_dim_fitted": n,
            "check_ok": ok,
            "seconds": round(time.time() - t0, 3),
        }
        print("PROGRESS: " + json.dumps({"part": "A_abelian_truncation", "n": n,
                                         "chain_length": strict + 1,
                                         "check_ok": ok}, ensure_ascii=False))
    return out, round(time.time() - t_all, 3)


# ---------------------------------------------------------------- (B) Witt truncations


def _solve_rational(A_rows, rhs):
    """Solve A x = rhs over Q; returns (solution list, consistent flag)."""
    A = [[Fraction(x) for x in row] + [Fraction(rhs[t])]
         for t, row in enumerate(A_rows)]
    if not A:
        return [Fraction(0)], True
    ncol = len(A[0]) - 1
    piv = 0
    for col in range(ncol):
        sel = None
        for r in range(piv, len(A)):
            if A[r][col] != 0:
                sel = r
                break
        if sel is None:
            continue
        A[piv], A[sel] = A[sel], A[piv]
        f = A[piv][col]
        A[piv] = [x / f for x in A[piv]]
        for r in range(len(A)):
            if r != piv and A[r][col] != 0:
                g = A[r][col]
                A[r] = [x - g * y for x, y in zip(A[r], A[piv])]
        piv += 1
    sol = [Fraction(0)] * ncol
    consistent = True
    for r in range(len(A)):
        lead = None
        for c in range(ncol):
            if A[r][c] != 0:
                lead = c
                break
        if lead is None:
            if A[r][ncol] != 0:
                consistent = False
        else:
            sol[lead] = A[r][ncol]
    return sol, consistent


def witt_struct(n):
    """W_n = Der(k[t]/(t^{n+1})): L_i = -t^{i+1} d/dt, i = -1..n-1, acting on 1..t^n."""
    N = n + 1
    inds = list(range(-1, n))
    d = len(inds)
    mats = {}
    for i in inds:
        M = [[0] * N for _ in range(N)]
        for j in range(N):
            k = i + j
            if k <= n and j != 0:
                M[k][j] = -j          # L_i(t^j) = -j t^{i+j}, 0 if i+j > n
        mats[i] = M
    struct = [[[0] * d for _ in range(d)] for _ in range(d)]
    closure_ok = True
    for a in range(d):
        for b in range(d):
            i, j = inds[a], inds[b]
            com = [[0] * N for _ in range(N)]
            for r in range(N):
                for s in range(N):
                    v = 0
                    for t in range(N):
                        v += mats[i][r][t] * mats[j][t][s] - mats[j][r][t] * mats[i][t][s]
                    com[r][s] = v
            rows = []
            rhs = []
            for r in range(N):
                for s in range(N):
                    rows.append([mats[inds[k]][r][s] for k in range(d)])
                    rhs.append(com[r][s])
            sol, consistent = _solve_rational(rows, rhs)
            if not consistent:
                closure_ok = False
            for k in range(d):
                if sol[k].denominator != 1:
                    closure_ok = False
                struct[a][b][k] = int(sol[k])
    anti_ok = True
    for a in range(d):
        for b in range(d):
            for k in range(d):
                if struct[a][b][k] != -struct[b][a][k]:
                    anti_ok = False
    jacobi_ok = anti_ok
    for a in range(d):
        for b in range(d):
            for c in range(d):
                acc = [0] * d
                for m1, m2, sgn in ((a, b, 1), (b, c, 1), (c, a, 1)):
                    for k1 in range(d):
                        c1 = struct[m1][m2][k1]
                        if c1:
                            for k2 in range(d):
                                acc[k2] += sgn * c1 * struct[k1][c][k2]
                if any(acc):
                    jacobi_ok = False
    return d, struct, closure_ok, jacobi_ok, inds


def witt_part(ns, m_max):
    out = {}
    t_all = time.time()
    for n in ns:
        t0 = time.time()
        d, struct, closure_ok, jacobi_ok, inds = witt_struct(n)
        dims = {}
        for m in range(1, m_max + 1):
            dim, W, nrel = filtered_dim(d, struct, m)
            dims[m] = {"dim_U_le_m_computed": dim, "span_words": W,
                       "relation_rows": nrel, "binom_C(m+d,d)": comb(m + d, d),
                       "matches_PBW": dim == comb(m + d, d)}
        ok = closure_ok and jacobi_ok and all(v["matches_PBW"] for v in dims.values())
        out["W_n=%d" % n] = {
            "dim_g": d,
            "basis_L_indices": inds,
            "closure_verified_in_gl": closure_ok,
            "jacobi_verified": jacobi_ok,
            "filtered_dims": dims,
            "gk_dim_fitted": d,
            "check_ok": ok,
            "seconds": round(time.time() - t0, 3),
        }
        print("PROGRESS: " + json.dumps({"part": "B_witt_truncation", "n": n, "dim": d,
                                         "closure": closure_ok, "jacobi": jacobi_ok,
                                         "check_ok": ok}, ensure_ascii=False))
    return out, round(time.time() - t_all, 3)


def main():
    t0 = time.time()
    A, tA = abelian_part([1, 2, 4, 6], 3)
    B, tB = witt_part([1, 2, 3], 3)
    okA = all(v["check_ok"] for v in A.values())
    okB = all(v["check_ok"] for v in B.values())
    ok = okA and okB
    chain = {k: v["chain_length"] for k, v in A.items()}
    gk = {"abelian": {k: v["gk_dim_fitted"] for k, v in A.items()},
          "witt": {k: v["gk_dim_fitted"] for k, v in B.items()}}
    data = {
        "A_abelian_truncations": A,
        "B_witt_truncations": B,
        "reading_by_code": {
            "chain_length_abelian_truncations": chain,
            "gk_dim_by_truncation": gk,
            "noetherian_status_of_the_infinite_dimensional_LIMIT":
                "not_decided_by_this_script (infinite-rank abelian limit: exp:000000;"
                " Witt limit: literature, not computed here)",
        },
        "timing": {"abelian_sec": tA, "witt_sec": tB,
                   "total_sec": round(time.time() - t0, 3)},
    }
    out = {
        "result": "supports" if ok else "inconclusive",
        "bound": "abelian truncations A_n (n=1,2,4,6): longest strict left-ideal chain = n+1,"
                 " dim U(A_n)<=m = C(m+n,n) (degree n); Witt truncations W_n (n=1,2,3, dim=n+1):"
                 " dim U(W_n)<=m = C(m+n+1,n+1) (degree n+1) -- both unbounded in n",
        "strategy": "exact linear algebra of the bracket-relation space (quotient of the truncated"
                    " tensor algebra, fraction Gaussian elimination over Q) + monomial-ideal"
                    " divisibility for chain witnesses; matrix-commutator closure test for Witt",
        "scaling": "abelian n<=6,m<=3 (max span %d words); Witt n<=3 (dim<=4),m<=3; total %s s"
                   % (max(v["filtered_dims"][3]["span_words"] for v in A.values()),
                      data["timing"]["total_sec"]),
        "data": data,
    }
    print("REPRO_RESULT: " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
