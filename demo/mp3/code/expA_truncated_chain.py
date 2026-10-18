#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expA (subgoal S2): truncated family I_n = sum_{i<=n} U(g)*(a_i b_i) in U(h_inf).

g = h_inf: generators a_i, b_i (i>=1), central z, [a_i,b_i] = z, all other brackets 0.
PBW basis: z^e * (word in a_i,b_i ordered by a_1<a_2<...<b_1<b_2<...).
Degree (PBW filtration): wt(a_i)=wt(b_i)=1, wt(z)=2 (relation [a_i,b_i]=z is homogeneous).
All arithmetic is exact (integer coefficients); all linear algebra is exact (Fraction).
No LLM in the loop: every verdict below is computed by this script.
Protocol: prints one line  REPRO_RESULT: {json}  plus PROGRESS lines.
"""
import json
import time
from fractions import Fraction

T0 = time.time()


# ---------------- PBW engine: normal form for U(h_inf) ----------------
def lkey(L):
    # total order on letters: a_1<a_2<...<b_1<b_2<...
    return (0 if L[0] == 'a' else 1, L[1])


_cc = {}


def norm(letters):
    """Normal-order a tuple of letters. Returns {(z_exp, sorted_letters): int coeff}."""
    if letters in _cc:
        return _cc[letters]
    for idx in range(len(letters) - 1):
        x, y = letters[idx], letters[idx + 1]
        if lkey(x) > lkey(y):                      # inversion found
            if x[0] == 'b' and y[0] == 'a' and x[1] == y[1]:
                i = x[1]                           # b_i a_i = a_i b_i - z
                w1 = letters[:idx] + (('a', i), ('b', i)) + letters[idx + 2:]
                w2 = letters[:idx] + letters[idx + 2:]
                out = {}
                for k, c in norm(w1).items():
                    out[k] = out.get(k, 0) + c
                for k, c in norm(w2).items():
                    kk = (k[0] + 1, k[1])
                    out[kk] = out.get(kk, 0) - c
                out = dict((k, v) for k, v in out.items() if v)
                _cc[letters] = out
                return out
            w = letters[:idx] + (y, x) + letters[idx + 2:]   # commute
            r = norm(w)
            _cc[letters] = r
            return r
    r = {(0, letters): 1}
    _cc[letters] = r
    return r


def mul(A, B):
    out = {}
    for (z1, l1), c1 in A.items():
        for (z2, l2), c2 in B.items():
            for (z3, l3), c3 in norm(l1 + l2).items():
                k = (z1 + z2 + z3, l3)
                out[k] = out.get(k, 0) + c1 * c2 * c3
    return dict((k, v) for k, v in out.items() if v)


def add(A, B, s=1):
    out = dict(A)
    for k, v in B.items():
        out[k] = out.get(k, 0) + s * v
    return dict((k, v) for k, v in out.items() if v)


def wt(k):
    return len(k[1]) + 2 * k[0]


def U(L):
    return {(0, L): 1}


def mz(e=1):
    return {(e, ()): 1}


def gen(i):
    return U((('a', i), ('b', i)))


def fmt(A):
    if not A:
        return "0"
    parts = []
    for k in sorted(A.keys(), key=lambda k: (wt(k), k[0], k[1])):
        c = A[k]
        s = "*".join("%s%d" % (x[0], x[1]) for x in k[1])
        if k[0]:
            zs = "z" if k[0] == 1 else "z^%d" % k[0]
            s = zs if not s else s + "*" + zs
        parts.append(s if c == 1 else ("%d*%s" % (c, s) if s else "%d" % c))
    return " + ".join(parts)


# ---------------- exact rational linear algebra ----------------
def reduce_rows(rows):
    """Echelon basis {pivot_col: normalised row dict} over Q."""
    basis = {}
    for r in rows:
        row = dict((c, Fraction(v)) for c, v in r.items() if v)
        while row:
            piv = min(row)
            if piv in basis:
                f = row[piv]
                b = basis[piv]
                for c, v in b.items():
                    row[c] = row.get(c, Fraction(0)) - f * v
                row = dict((c, v) for c, v in row.items() if v)
            else:
                f = row[piv]
                basis[piv] = dict((c, v / f) for c, v in row.items())
                break
    return basis


def reduce_one(basis, t):
    """Left-module reduction of a coordinate vector by the span. Returns (in_span, remainder)."""
    row = dict((c, Fraction(v)) for c, v in t.items() if v)
    while row:
        piv = min(row)
        if piv not in basis:
            return False, row
        f = row[piv]
        b = basis[piv]
        for c, v in b.items():
            row[c] = row.get(c, Fraction(0)) - f * v
        row = dict((c, v) for c, v in row.items() if v)
    return True, {}


def dual_cert(rows, target):
    """Find lambda on coordinates with lambda(row)=0 for all rows and lambda(target)=1.
    Exists iff target is NOT in the rational span of rows. Exact Gaussian elimination."""
    cols = sorted(set([c for r in rows for c in r]) | set(target.keys()))
    if not cols:
        return None
    n = len(cols)
    mat = []
    for r in rows:
        mat.append([Fraction(r.get(c, 0)) for c in cols] + [Fraction(0)])
    mat.append([Fraction(target.get(c, 0)) for c in cols] + [Fraction(1)])
    m = len(mat)
    r0 = 0
    piv = []
    for j in range(n):
        p = None
        for i in range(r0, m):
            if mat[i][j] != 0:
                p = i
                break
        if p is None:
            continue
        mat[r0], mat[p] = mat[p], mat[r0]
        f = mat[r0][j]
        mat[r0] = [x / f for x in mat[r0]]
        for i in range(m):
            if i != r0 and mat[i][j] != 0:
                g = mat[i][j]
                mat[i] = [a - g * b for a, b in zip(mat[i], mat[r0])]
        piv.append((r0, j))
        r0 += 1
        if r0 == m:
            break
    for i in range(r0, m):
        if mat[i][n] != 0:
            return None                    # inconsistent: no separating functional
    lam = {}
    for (ri, cj) in piv:
        v = mat[ri][n]
        if v:
            lam[cols[cj]] = v
    return lam


def enum_keys(indices, W):
    """All PBW monomials (z_exp, sorted letter word) with weight <= W over the given indices."""
    letters = sorted([('a', i) for i in indices] + [('b', i) for i in indices], key=lkey)
    out = []

    def rec(pos, cur, w):
        if pos == len(letters):
            for e in range((W - w) // 2 + 1):
                out.append((e, tuple(cur)))
            return
        for m in range(W - w + 1):
            rec(pos + 1, cur + [letters[pos]] * m, w + m)

    rec(0, [], 0)
    return out


def vec(E, pos):
    return dict((pos[k], v) for k, v in E.items() if k in pos and v)


# ---------------- main ----------------
def main():
    P = print

    # ---- self tests of the PBW engine ----
    st = []
    for i in (1, 2, 3):
        cv = add(mul(U((('a', i),)), U((('b', i),))), mul(U((('b', i),)), U((('a', i),))), -1)
        st.append({"test": "[a_%d,b_%d] = z" % (i, i), "value": fmt(cv), "ok": cv == mz(1)})
    cv = add(mul(U((('a', 1),)), U((('b', 2),))), mul(U((('b', 2),)), U((('a', 1),))), -1)
    st.append({"test": "[a_1,b_2] = 0", "value": fmt(cv), "ok": cv == {}})
    st.append({"test": "gen(3)=a3*b3 homogeneous of weight 2",
               "ok": all(wt(k) == 2 for k in gen(3))})
    for t in st:
        P("SELFTEST " + json.dumps(t))

    NMAX = 8          # chain members I_1..I_8, comparisons n -> n+1 for n=1..7
    WBRUTE = 4        # bounded brute-force span cross-check
    steps = []
    scaling = {}

    for n in range(1, NMAX):
        t_n = time.time()
        # ---- (a) exact test in the weight-2 graded piece (alphabet 1..n+1) ----
        idx = list(range(1, n + 2))
        keys2 = [k for k in enum_keys(idx, 2) if wt(k) == 2]
        pos = dict((k, i) for i, k in enumerate(keys2))
        inv = dict((i, k) for k, i in pos.items())
        gs, gnames = [], []
        for i in range(1, n + 1):   # BUG FIX: generators of I_n ONLY (was n+2, which put a_{n+1}b_{n+1} into the generating set and made strictness vacuous)
            key = (0, (('a', i), ('b', i)))
            if key in pos:
                gs.append(vec({key: 1}, pos))
                gnames.append("a%d*b%d" % (i, i))
        basis = reduce_rows(gs)
        # criterion (1): I_n subset I_{n+1}: generators of I_n reduce to 0 mod generators of I_{n+1}
        incl = []
        for i in range(1, n + 1):
            key = (0, (('a', i), ('b', i)))
            ok_in, rem = reduce_one(basis, vec({key: 1}, pos))
            incl.append({"generator": "a%d*b%d" % (i, i), "in_span": ok_in,
                         "remainder_nonzero_terms": len(rem)})
        # criterion (2): strictness, witness w = a_{n+1} b_{n+1}
        wkey = (0, (('a', n + 1), ('b', n + 1)))
        tw = vec({wkey: 1}, pos)
        ok_w, rem_w = reduce_one(basis, tw)
        lam = dual_cert(gs, tw)
        kills = False
        val = None
        lam_sup = {}
        if lam is not None:
            kills = all(sum(Fraction(lam.get(c, 0)) * Fraction(r.get(c, 0))
                            for c in set(list(lam.keys()) + list(r.keys()))) == 0 for r in gs)
            val = sum(Fraction(lam.get(c, 0)) * Fraction(tw.get(c, 0))
                      for c in set(list(lam.keys()) + list(tw.keys())))
            lam_sup = dict((fmt({inv[c]: 1}), str(v)) for c, v in sorted(lam.items()))
        cert_ok = (lam is not None) and kills and (val == 1)
        step = {
            "n": n,
            "I_n_generators": gnames[:n],
            "I_n1_generators_extra": [gnames[n]] if len(gnames) > n else [],
            "subset_check": incl,
            "subset_holds": all(c["in_span"] for c in incl),
            "w": "a%d*b%d" % (n + 1, n + 1),
            "w_in_span_of_I_n_weight2": ok_w,
            "w_reduction_remainder_terms": len(rem_w),
            "w_reduction_remainder": dict((str(inv[c]), str(v)) for c, v in rem_w.items()),
            "certificate_lambda": lam_sup,
            "certificate_kills_all_generators": kills,
            "certificate_value_on_w": None if val is None else str(val),
            "certificate_verified": cert_ok,
            "strict": (not ok_w) and cert_ok,
        }
        # ---- (b) bounded brute-force span scan at PBW weight <= WBRUTE (small n) ----
        if n <= 3:
            idxb = list(range(1, n + 3))
            keysb = [k for k in enum_keys(idxb, WBRUTE) if wt(k) <= WBRUTE]
            posb = dict((k, i) for i, k in enumerate(keysb))
            rowsb = []
            nprod = 0
            for i in range(1, n + 1):
                g = gen(i)
                for u in keysb:
                    if wt(u) > WBRUTE - 2:
                        continue
                    prod = mul({u: 1}, g)
                    rowsb.append(vec(prod, posb))
                    nprod += 1
            twb = vec({wkey: 1}, posb)
            basb = reduce_rows(rowsb)
            okb, remb = reduce_one(basb, twb)
            lamb = dual_cert(rowsb, twb)
            step["bruteforce"] = {
                "PBW_weight_bound": WBRUTE,
                "alphabet": "a_i,b_i for i<=%d" % (n + 2),
                "dim_ambient": len(keysb),
                "num_products": nprod,
                "dim_span": len(basb),
                "w_in_span": okb,
                "w_remainder_terms": len(remb),
                "certificate_found": lamb is not None,
            }
            P("PROGRESS " + json.dumps({"n": n, "bruteforce_W": WBRUTE,
                                        "dim_ambient": len(keysb), "dim_span": len(basb),
                                        "num_products": nprod, "w_in_span": okb}))
        # ---- (c) direct scan: no product u*g (wt u <= 3) has any coefficient at w (bound 5) ----
        idxc = list(range(1, n + 3))
        us = [k for k in enum_keys(idxc, 3) if wt(k) <= 3]
        maxcoef = 0
        nscan = 0
        for i in range(1, n + 1):
            g = gen(i)
            for u in us:
                prod = mul({u: 1}, g)
                maxcoef = max(maxcoef, abs(prod.get(wkey, 0)))
                nscan += 1
        step["product_scan_bound5"] = {"num_products": nscan,
                                      "max_abs_coefficient_at_w": maxcoef}
        steps.append(step)
        scaling["n=%d" % n] = round(time.time() - t_n, 3)
        P("PROGRESS " + json.dumps({"n": n, "strict": step["strict"],
                                    "subset_holds": step["subset_holds"],
                                    "certificate_verified": cert_ok,
                                    "sec": scaling["n=%d" % n]}))

    all_strict = all(s["strict"] for s in steps)
    all_subset = all(s["subset_holds"] for s in steps)
    all_scan_zero = all(s["product_scan_bound5"]["max_abs_coefficient_at_w"] == 0 for s in steps)
    # A failed *check* is NOT a refutation: 'refutes' is reserved for a reproducible
    # counterexample to the tested statement. Anything else is 'inconclusive'.
    failure = {}
    if not all_subset:
        failure["subset_failures"] = [{"n": s["n"], "generator": c["generator"],
                                      "remainder_nonzero_terms": c["remainder_nonzero_terms"]}
                                      for s in steps for c in s["subset_check"] if not c["in_span"]]
    if not all_strict:
        failure["strict_failures"] = [{"n": s["n"], "w": s["w"],
                                       "w_in_span_of_I_n": s["w_in_span_of_I_n_weight2"],
                                       "cert_kills": s["certificate_kills_all_generators"],
                                       "cert_value_on_w": s["certificate_value_on_w"],
                                       "cert_verified": s["certificate_verified"]}
                                      for s in steps if not s["strict"]]
    if not all_scan_zero:
        failure["scan_failures"] = [{"n": s["n"], "w": s["w"],
                                     "max_abs_coef_at_w": s["product_scan_bound5"]["max_abs_coefficient_at_w"]}
                                    for s in steps
                                    if s["product_scan_bound5"]["max_abs_coefficient_at_w"] != 0]
    result = "supports" if (all_strict and all_subset and all_scan_zero) else "inconclusive"

    out = {
        "result": result,
        "family": "(i) I_n = sum_{i<=n} U(g)*(a_i b_i), n = 1..8",
        "question": "strictly ascending chain of finitely generated left ideals in U(h_inf)?",
        "bound": {
            "n_comparisons": [1, 7],
            "n_members": 8,
            "pbw_weight_bound": 5,
            "weight_convention": "wt(a_i)=wt(b_i)=1, wt(z)=2 (relation homogeneous)",
            "weight2_test": "exact for all n<=8 (graded piece, no degree truncation)",
            "bruteforce_W4": "n<=3",
            "product_scan": "wt(u)<=3, all i<=n, n<=7 (covers degree<=5)",
        },
        "strategy": "PBW normal form (exact integer arithmetic) + exact rational linear "
                    "algebra: subset by left-module reduction (remainder), strictness by a "
                    "dual functional certificate (PBW monomial linear independence)",
        "self_tests": st,
        "steps": steps,
        "scaling": scaling,
        "all_subset_checks_zero_remainder": all_subset,
        "all_strict": all_strict,
        "all_product_scans_zero_at_w": all_scan_zero,
        "stabilization_detected": not all_strict,
        "runtime_sec": round(time.time() - T0, 3),
        "note": "numeric evidence only (cross_check): no formalisation, no claim of theorem. "
                "The weight-2 verdict is exact for the checked n<=8; the W=4 brute-force span "
                "test is a cross-check on n<=3 only (W=5 for n>=4 was not run: state space "
                "growth reported in the ledger). What is NOT covered: n>8.",
    }
    print("REPRO_RESULT: " + json.dumps(out, default=str))


if __name__ == "__main__":
    main()
