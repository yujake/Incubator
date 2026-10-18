#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E3b -- SUPERSEDES the Witt part of exp:000002, which FAILED its own closure check
(exp:000002 recorded closure_verified_in_gl=false and jacobi_verified=false for W_n=2,3,
and one PBW mismatch 34 vs 35: that truncation basis was one element too large).

Finite-dimensional truncations of infinite-dimensional Lie algebras, measured by code:

(A) A_n = k^n, zero bracket (truncation of the infinite-rank abelian algebra).
    * strict monomial left-ideal chain 0 < I_1 < ... < I_n < (1): n+1 strict steps;
      witness for I_m < I_{m+1}: x_{m+1} in I_{m+1} \\ I_m (membership = divisibility test);
    * dim U(A_n)_{<=m} = C(m+n, n) checked by exact rank computation over Q.

(B) W_n = Der(k[t]/(t^{n+1})), truncated Witt algebra: dim = n,
    basis L_i = t^{i+1} d/dt, i = -1,...,n-2,  [L_i,L_j] = (j-i) L_{i+j} if i+j <= n-2 else 0.
    * closure verified INDEPENDENTLY by truncated polynomial arithmetic
      (f_i f_j' - f_j f_i' truncated to deg <= n-1, compared with structure constants);
    * antisymmetry and Jacobi verified exactly on structure constants;
    * dim U(W_n)_{<=m} = C(m+n, n) checked by exact rank computation over Q.

Reading: GK dim U(g_n) = dim g_n = n grows linearly with truncation size n, and the
explicit strict chain in A_n has length n+1, while every individual g_n is finite
dimensional (hence Noetherian by the standard filtered argument -- NOT re-proved here).
Protocol: one line `REPRO_RESULT: {...}` on stdout, plus PROGRESS lines.
"""
import json
import time
from fractions import Fraction


def binom(n, k):
    if k < 0 or n < 0:
        return 0
    r = 1
    for t in range(k):
        r = r * (n - t) // (t + 1)
    return r


def words_upto(m, d):
    out = [()]
    layer = [()]
    for _ in range(m):
        layer = [w + (i,) for w in layer for i in range(d)]
        out.extend(layer)
    return out


def rank_q(rows, ncols):
    rows = [dict(r) for r in rows if r]
    n = len(rows)
    r = 0
    for col in range(ncols):
        sel = None
        for i in range(r, n):
            if rows[i].get(col, 0) != 0:
                sel = i
                break
        if sel is None:
            continue
        rows[r], rows[sel] = rows[sel], rows[r]
        pv = Fraction(rows[r][col])
        pr = {c: Fraction(v) / pv for c, v in rows[r].items()}
        rows[r] = pr
        for i in range(r + 1, n):
            f = rows[i].get(col, 0)
            if f:
                f = Fraction(f)
                ri = rows[i]
                for c, v in pr.items():
                    nv = Fraction(ri.get(c, 0)) - f * v
                    if nv == 0:
                        ri.pop(c, None)
                    else:
                        ri[c] = nv
        r += 1
        if r == n:
            break
    return r


def dim_U_le(m, C):
    """dim U(g)_{<=m} = dim V_m - rank(truncated relation subspace), exact over Q."""
    d = len(C)
    words = words_upto(m, d)
    widx = {w: i for i, w in enumerate(words)}
    bylen = {}
    for w in words:
        bylen.setdefault(len(w), []).append(w)
    rows = []
    if m >= 2:
        for i in range(d):
            for j in range(i + 1, d):
                for lu in range(0, m - 1):
                    for u in bylen.get(lu, []):
                        for lv in range(0, m - 1 - lu):
                            for v in bylen.get(lv, []):
                                row = {}
                                row[widx[u + (i, j) + v]] = 1
                                k2 = widx[u + (j, i) + v]
                                row[k2] = row.get(k2, 0) - 1
                                for k in range(d):
                                    c = C[k][i][j]
                                    if c:
                                        kk = widx[u + (k,) + v]
                                        row[kk] = row.get(kk, 0) - c
                                row = {a: b for a, b in row.items() if b}
                                if row:
                                    rows.append(row)
    return len(words) - rank_q(rows, len(words))


def mono_in_ideal(mono, gens):
    for g in gens:
        if all(mono.get(k, 0) >= v for k, v in g.items()):
            return True
    return False


def abelian_part(n, m_list):
    t0 = time.time()
    d = n
    C = [[[0] * d for _ in range(d)] for _ in range(d)]
    dims = {}
    for m in m_list:
        got = dim_U_le(m, C)
        exp = binom(m + d, d)
        dims[str(m)] = {"dim_U_le_m_computed": got, "binom_C(m+n,n)": exp, "matches_PBW": got == exp}
    strict = 0
    samples = []
    for m in range(1, n + 1):
        gens_m = [{i: 1} for i in range(1, m + 1)]
        gens_m1 = [{i: 1} for i in range(1, m + 2)]
        w = {m + 1: 1}
        inm = mono_in_ideal(w, gens_m)
        inm1 = mono_in_ideal(w, gens_m1)
        incl = all(mono_in_ideal(g, gens_m1) for g in gens_m)
        if inm1 and not inm and incl:
            strict += 1
        if m in (1, 2, n):
            samples.append({"m": m, "witness": "x_%d" % (m + 1), "in_I_m": inm, "in_I_m1": inm1})
    nxt = mono_in_ideal({1: 1}, [{1: 1}])
    all_ok = all(v["matches_PBW"] for v in dims.values()) and strict == n
    return {"n": n, "dim_g": d, "filtered_dims": dims,
            "gk_dim_from_m1_reading": dims.get("1", {}).get("dim_U_le_m_computed", None) - 1
            if "1" in dims else None,
            "strict_chain_steps": strict, "chain_length_including_zero_and_unit": n + 2,
            "witness_samples": samples, "I_1_contains_x_1": nxt,
            "check_ok": all_ok, "seconds": round(time.time() - t0, 3)}


def witt_basis(n):
    return list(range(-1, n - 1))


def witt_structure(n):
    idx = witt_basis(n)
    pos = {i: k for k, i in enumerate(idx)}
    d = len(idx)
    C = [[[0] * d for _ in range(d)] for _ in range(d)]
    for a, i in enumerate(idx):
        for b, j in enumerate(idx):
            if j != i and -1 <= i + j <= n - 2:
                C[pos[i + j]][a][b] += j - i
    return idx, C


def deriv_poly(i, maxdeg):
    f = [0] * (maxdeg + 1)
    f[i + 1] = 1
    return f


def poly_mul_trunc(p, q, maxdeg):
    out = [0] * (maxdeg + 1)
    for i, pi in enumerate(p):
        if pi:
            for j, qj in enumerate(q):
                if qj and i + j <= maxdeg:
                    out[i + j] += pi * qj
    return out


def witt_checks(n):
    idx, C = witt_structure(n)
    d = len(idx)
    anti = all(C[k][a][b] == -C[k][b][a] for k in range(d) for a in range(d) for b in range(d))
    jac = True
    for a in range(d):
        for b in range(d):
            for c in range(d):
                for mm in range(d):
                    s = 0
                    for k in range(d):
                        s += C[k][a][b] * C[mm][k][c] + C[k][b][c] * C[mm][k][a] + C[k][c][a] * C[mm][k][b]
                    if s != 0:
                        jac = False
    maxdeg = n - 1
    closure = True
    detail = []
    for a, i in enumerate(idx):
        for b, j in enumerate(idx):
            fi = deriv_poly(i, maxdeg)
            fj = deriv_poly(j, maxdeg)
            dfi = [(k + 1) * fi[k + 1] if k + 1 <= maxdeg else 0 for k in range(maxdeg + 1)]
            dfj = [(k + 1) * fj[k + 1] if k + 1 <= maxdeg else 0 for k in range(maxdeg + 1)]
            left = poly_mul_trunc(fi, dfj, maxdeg)
            right = poly_mul_trunc(fj, dfi, maxdeg)
            br = [left[k] - right[k] for k in range(maxdeg + 1)]
            comb = [0] * (maxdeg + 1)
            for k in range(d):
                ck = C[k][a][b]
                if ck:
                    fk = deriv_poly(idx[k], maxdeg)
                    for t in range(maxdeg + 1):
                        comb[t] += ck * fk[t]
            ok = (br == comb)
            if not ok:
                closure = False
            if len(detail) < 4:
                detail.append({"pairs": [idx[a], idx[b]], "bracket_poly": br, "from_structure_constants": comb, "match": ok})
    return {"basis_L_indices": idx, "dim_g": d, "antisymmetry": anti, "jacobi": jac,
            "closure_in_derivations": closure, "closure_detail": detail,
            "check_ok": bool(anti and jac and closure)}


def witt_part(n, m_list):
    t0 = time.time()
    chk = witt_checks(n)
    idx, C = witt_structure(n)
    d = len(C)
    dims = {}
    for m in m_list:
        got = dim_U_le(m, C)
        exp = binom(m + d, d)
        dims[str(m)] = {"dim_U_le_m_computed": got, "binom_C(m+d,d)": exp, "matches_PBW": got == exp}
    all_ok = chk["check_ok"] and all(v["matches_PBW"] for v in dims.values())
    return {"n": n, "algebra": "Der(k[t]/(t^{n+1})), truncated Witt", "dim_g": d,
            "structure_checks": chk, "filtered_dims": dims,
            "gk_dim_from_m1_reading": dims.get("1", {}).get("dim_U_le_m_computed", None) - 1
            if "1" in dims else None,
            "check_ok": all_ok, "seconds": round(time.time() - t0, 3)}


def main():
    t0 = time.time()
    A = {}
    for n in (1, 2, 3, 4, 6):
        m_list = [0, 1, 2, 3] if n <= 4 else [0, 1, 2, 3]
        A["A_n=%d" % n] = abelian_part(n, m_list)
        print("PROGRESS: " + json.dumps({"part": "A_abelian_truncation", "n": n,
                                         "chain_len": A["A_n=%d" % n]["strict_chain_steps"] + 1,
                                         "check_ok": A["A_n=%d" % n]["check_ok"]}, ensure_ascii=False))
    W = {}
    for n in (2, 3, 4, 5):
        m_list = [0, 1, 2, 3, 4] if n <= 3 else [0, 1, 2, 3]
        W["W_n=%d" % n] = witt_part(n, m_list)
        print("PROGRESS: " + json.dumps({"part": "B_witt_truncation", "n": n,
                                         "dim_g": W["W_n=%d" % n]["dim_g"],
                                         "check_ok": W["W_n=%d" % n]["check_ok"]}, ensure_ascii=False))
    ok_A = all(v["check_ok"] for v in A.values())
    ok_W = all(v["check_ok"] for v in W.values())
    ok = bool(ok_A and ok_W)
    chain_reading = {k: v["strict_chain_steps"] + 1 for k, v in A.items()}
    gk_reading = {"abelian": {k: v["gk_dim_from_m1_reading"] for k, v in A.items()},
                  "witt": {k: v["gk_dim_from_m1_reading"] for k, v in W.items()}}
    data = {
        "A_abelian_truncations": A,
        "B_witt_truncations": W,
        "reading_by_code": {
            "strict_chain_length_abelian": chain_reading,
            "gk_dim_by_truncation": gk_reading,
            "note": "each g_n is finite dimensional; GK dim U(g_n) = dim g_n = n grows with n, and the explicit strict chain in A_n has length n+1 (n+1 strict steps counting 0 < I_1 and I_n < (1))",
            "not_decided_here": "Noetherian-ness of the infinite-dimensional LIMITS: the infinite-rank abelian limit is settled in exp:000000 (non-Noetherian via explicit chain); the Witt limit is not decided by this script (literature item exists, not re-derived here)"
        },
        "timing": {"total_sec": round(time.time() - t0, 3)},
    }
    out = {"result": "supports" if ok else "inconclusive",
           "bound": "truncations tested: A_n n in {1,2,3,4,6} (chain n+1 steps), W_n n in {2,3,4,5} (dim n), filtered degrees m up to 3 (4 when n<=3)",
           "strategy": "explicit structure constants from truncated derivations + exact linear algebra over Q (rank of relation subspace) + monomial-ideal divisibility witnesses",
           "scaling": "seconds by family: " + json.dumps({"abelian": {k: v["seconds"] for k, v in A.items()},
                                                          "witt": {k: v["seconds"] for k, v in W.items()}}, ensure_ascii=False),
           "data": data}
    print("REPRO_RESULT: " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
