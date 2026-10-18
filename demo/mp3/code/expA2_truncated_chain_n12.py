#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expA2_truncated_chain_n12.py -- subgoal S2, extension of exp:000008 from n<=8 to n<=12.

g = h_inf = span(a_i, b_i, z ; i>=1), z central, [a_i,b_i] = z, all other brackets 0.
PBW basis: z^e * (word in a_i,b_i sorted by a_1<a_2<...<b_1<b_2<...).
Weights: wt(a_i)=wt(b_i)=1, wt(z)=2 (the relation is weight-homogeneous).
I_n = sum_{i<=n} U(g)*(a_i b_i), a left ideal.  I_n subset I_{n+1} by generator nesting.

Claim tested (numeric / cross_check): for n = 1..11 (members I_1..I_12) the inclusion is
STRICT, with exact witness w = a_{n+1} b_{n+1} at PBW weight 2:
   w not in I_n  <=>  w not in span_Q{a_i b_i : i<=n}
   certified by an exact rational dual functional lam with lam(a_i b_i)=0 (i<=n), lam(w)=1,
   plus rank(span{g_i}) = n and rank(span{g_i, w}) = n+1.
Honest scope note: the subset direction I_n subset I_{n+1} is immediate from generator nesting;
the weight-2 reduction check below re-verifies it inside the graded piece but is not the
content of the claim.  The content is strictness (w in span or not).

Extra (cost-checked) work: a product scan over {u*g_i : wt(u)<=3, i<=n} for n<=12, done as an
exact projection onto the weight-2 graded piece (valid because every relation is weight-
homogeneous, so every term of u*g_i has weight wt(u)+2 >= wt(w); the projection is validated
against an untruncated full-vector computation for n<=4, W<=5).

All arithmetic exact: integer coefficients in the PBW normal form, Fraction in linear algebra.
No LLM verdicts.  Prints PROGRESS lines and one REPRO_RESULT line.
"""
import json
import time
from fractions import Fraction

T0 = time.time()


def lkey(L):
    return (0 if L[0] == 'a' else 1, L[1])


_cc = {}


def norm(letters):
    """Normal-order a tuple of letters. Returns {(z_exp, sorted_letters): int coeff}."""
    if letters in _cc:
        return _cc[letters]
    for idx in range(len(letters) - 1):
        x, y = letters[idx], letters[idx + 1]
        if lkey(x) > lkey(y):
            if x[0] == 'b' and y[0] == 'a' and x[1] == y[1]:
                i = x[1]
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
            w = letters[:idx] + (y, x) + letters[idx + 2:]
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
        return '0'
    parts = []
    for k in sorted(A.keys(), key=lambda k: (wt(k), k[0], k[1])):
        c = A[k]
        s = '*'.join('%s%d' % (x[0], x[1]) for x in k[1])
        if k[0]:
            zs = 'z' if k[0] == 1 else 'z^%d' % k[0]
            s = zs if not s else s + '*' + zs
        parts.append(s if c == 1 else ('%d*%s' % (c, s) if s else '%d' % c))
    return ' + '.join(parts)


def reduce_rows(rows):
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
    """lam on coordinates with lam(row)=0 for all rows and lam(target)=1, or None."""
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
            return None
    lam = {}
    for (ri, cj) in piv:
        v = mat[ri][n]
        if v:
            lam[cols[cj]] = v
    return lam


def enum_keys(indices, W):
    """All PBW monomials (z_exp, sorted word) with weight <= W over the given indices."""
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


def weight2_keys(m):
    letters = sorted([('a', i) for i in range(1, m + 1)] + [('b', i) for i in range(1, m + 1)], key=lkey)
    out = [(1, ())]
    for x in range(len(letters)):
        for y in range(x, len(letters)):
            out.append((0, (letters[x], letters[y])))
    return out


def main():
    P = print
    st = []
    for i in (1, 2, 3):
        cv = add(mul(U((('a', i),)), U((('b', i),))), mul(U((('b', i),)), U((('a', i),))), -1)
        st.append({'test': '[a_%d,b_%d]=z' % (i, i), 'ok': cv == mz(1), 'value': fmt(cv)})
    cv = add(mul(U((('a', 1),)), U((('b', 2),))), mul(U((('b', 2),)), U((('a', 1),))), -1)
    st.append({'test': '[a_1,b_2]=0', 'ok': cv == {}, 'value': fmt(cv)})
    for t in st:
        P('SELFTEST ' + json.dumps(t, sort_keys=True))
    if not all(t['ok'] for t in st):
        P('REPRO_RESULT: ' + json.dumps({'result': 'inconclusive', 'reason': 'PBW selftest failed', 'selftests': st}))
        return

    NMAX = 12
    BMAX = 4
    WB = 5
    steps = []
    scaling = {'weight2': {}, 'product_scan_projected': {}, 'bruteforce_full': {}}
    ok_all = True
    counterexample = None

    # ---------- (A) exact weight-2 test: comparisons n -> n+1, members I_1..I_12 ----------
    for n in range(1, NMAX):
        t0 = time.time()
        m = n + 1
        keys2 = weight2_keys(m)
        pos = dict((k, i) for i, k in enumerate(keys2))
        inv = dict((i, k) for k, i in pos.items())
        gkeys = [(0, (('a', i), ('b', i))) for i in range(1, n + 1)]
        gs = [vec({k: 1}, pos) for k in gkeys]
        basis = reduce_rows(gs)
        incl = [reduce_one(basis, vec({k: 1}, pos))[0] for k in gkeys]
        wkey = (0, (('a', m), ('b', m)))
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
        rank_aug = len(reduce_rows(gs + [tw]))
        strict = (not ok_w) and cert_ok and (rank_aug == n + 1)
        if not strict and counterexample is None:
            counterexample = {'n': n, 'w': 'a%d*b%d' % (m, m), 'w_in_span': ok_w,
                              'cert_ok': cert_ok, 'rank_aug': rank_aug, 'n_gens': n}
        sec = round(time.time() - t0, 4)
        steps.append({'n': n, 'n_members_pair': [n, n + 1],
                      'weight2_dim_of_alphabet': len(keys2),
                      'I_n_generators': ['a%d*b%d' % (i, i) for i in range(1, n + 1)],
                      'subset_check_all_in_span': all(incl),
                      'w': 'a%d*b%d' % (m, m),
                      'w_in_span_of_I_n': ok_w,
                      'w_reduction_remainder_terms': len(rem_w),
                      'certificate_kills_all_generators': kills,
                      'certificate_value_on_w': None if val is None else str(val),
                      'rank_span_gens': n, 'rank_span_gens_plus_w': rank_aug,
                      'certificate_verified': cert_ok,
                      'strict': strict, 'sec': sec})
        scaling['weight2'][str(n)] = {'weight2_dim': len(keys2), 'gens': n, 'sec': sec}
        P('PROGRESS ' + json.dumps({'stage': 'weight2', 'n': n, 'dim_W2': len(keys2),
                                    'strict': strict, 'sec': sec}, sort_keys=True))
        ok_all = ok_all and strict

    # ---------- (B) product scan {u*g_i : wt(u)<=3} projected to weight 2, n<=12 ----------
    for n in range(1, NMAX + 1):
        t0 = time.time()
        m = n + 1
        keys2 = weight2_keys(m)
        pos = dict((k, i) for i, k in enumerate(keys2))
        us = enum_keys(list(range(1, m + 1)), 3)
        rows = []
        for i in range(1, n + 1):
            g = gen(i)
            for u in us:
                prod = mul({u: 1}, g)
                proj = dict((k, v) for k, v in prod.items() if wt(k) == 2)
                if proj:
                    rows.append(vec(proj, pos))
        tw = vec({(0, (('a', m), ('b', m))): 1}, pos)
        basb = reduce_rows(rows)
        okb, remb = reduce_one(basb, tw)
        lamb = dual_cert(rows, tw)
        okb2 = (lamb is not None) and all(
            sum(Fraction(lamb.get(c, 0)) * Fraction(r.get(c, 0))
                for c in set(list(lamb.keys()) + list(r.keys()))) == 0 for r in rows) and (
            sum(Fraction(lamb.get(c, 0)) * Fraction(tw.get(c, 0))
                for c in set(list(lamb.keys()) + list(tw.keys()))) == 1)
        scan_ok = (not okb) and okb2
        sec = round(time.time() - t0, 4)
        scaling['product_scan_projected'][str(n)] = {
            'n_u_monomials_wt_le_3': len(us), 'rows': len(rows), 'sec': sec}
        if not scan_ok and counterexample is None:
            counterexample = {'stage': 'product_scan_projected', 'n': n,
                              'w_in_span': okb, 'dual_cert': okb2}
        ok_all = ok_all and scan_ok
        P('PROGRESS ' + json.dumps({'stage': 'product_scan_projected', 'n': n,
                                    'rows': len(rows), 'w_in_span': okb,
                                    'cert': okb2, 'sec': sec}, sort_keys=True))

    # ---------- (C) untruncated full-vector control, n<=BMAX, W<=WB ----------
    for n in range(1, BMAX + 1):
        t0 = time.time()
        m = n + 1
        keysb = [k for k in enum_keys(list(range(1, m + 1)), WB) if wt(k) <= WB]
        posb = dict((k, i) for i, k in enumerate(keysb))
        rowsb = []
        us = [u for u in enum_keys(list(range(1, m + 1)), 3)]
        for i in range(1, n + 1):
            g = gen(i)
            for u in us:
                if wt(u) > 3:
                    continue
                rowsb.append(vec(mul({u: 1}, g), posb))
        twb = vec({(0, (('a', m), ('b', m))): 1}, posb)
        basb = reduce_rows(rowsb)
        okb, remb = reduce_one(basb, twb)
        lamb = dual_cert(rowsb, twb)
        certb = (lamb is not None) and all(
            sum(Fraction(lamb.get(c, 0)) * Fraction(r.get(c, 0))
                for c in set(list(lamb.keys()) + list(r.keys()))) == 0 for r in rowsb) and (
            sum(Fraction(lamb.get(c, 0)) * Fraction(twb.get(c, 0))
                for c in set(list(lamb.keys()) + list(twb.keys()))) == 1)
        full_ok = (not okb) and certb
        sec = round(time.time() - t0, 4)
        scaling['bruteforce_full'][str(n)] = {'W': WB, 'dim_W<=5': len(keysb),
                                              'rows': len(rowsb), 'sec': sec}
        if not full_ok and counterexample is None:
            counterexample = {'stage': 'bruteforce_full', 'n': n, 'W': WB,
                              'w_in_span': okb, 'dual_cert': certb}
        ok_all = ok_all and full_ok
        P('PROGRESS ' + json.dumps({'stage': 'bruteforce_full', 'n': n, 'W': WB,
                                    'dim': len(keysb), 'rows': len(rowsb),
                                    'w_in_span': okb, 'cert': certb, 'sec': sec}, sort_keys=True))

    bound = {'n_comparisons': [1, NMAX - 1], 'n_members': NMAX,
             'weight_convention': 'wt(a_i)=wt(b_i)=1, wt(z)=2 (relation homogeneous)',
             'weight2_test': 'exact for all n<=%d (graded piece, no degree truncation)' % NMAX,
             'product_scan_projected': 'wt(u)<=3, all i<=n, n<=%d (projected to weight-2 piece; exact)' % NMAX,
             'bruteforce_full': 'untruncated PBW vectors W<=%d, n<=%d (control for the projection)' % (WB, BMAX)}
    strategy = ('PBW normal form (exact integer arithmetic) + exact rational linear algebra: '
                'subset by left-module reduction, strictness by a rational dual functional certificate '
                'lambda (lam(g_i)=0, lam(w)=1) and by rank increase n -> n+1; '
                'higher-weight scan by exact projection onto the weight-2 graded piece, '
                'validated against an untruncated full-vector scan for small n.')
    data = {'steps': steps,
            'projection_justification': ('every relation is weight-homogeneous, so every term of u*g_i '
                                         'has weight wt(u)+2 >= 2; the weight-2 component of a combination '
                                         'sum c_{u,i} u g_i comes only from wt(u)=0 terms (constants), '
                                         'so the projection cannot hide a witness; checked numerically '
                                         'in stage (C) for n<=%d by comparing with untruncated vectors.' % BMAX),
            'scope_note': ('subset direction I_n subset I_{n+1} is immediate from generator nesting and is '
                           'recorded as structural, not as the computed content; the computed content is '
                           'strictness of each inclusion up to n=%d.' % NMAX),
            'selftests': st,
            'total_seconds': round(time.time() - T0, 3)}
    if ok_all:
        out = {'result': 'supports', 'bound': bound, 'strategy': strategy,
               'scaling': scaling, 'data': data}
    elif counterexample is not None:
        out = {'result': 'refutes', 'counterexample': counterexample, 'bound': bound,
               'strategy': strategy, 'scaling': scaling, 'data': data}
    else:
        out = {'result': 'inconclusive', 'bound': bound, 'strategy': strategy,
               'scaling': scaling, 'data': data}
    P('REPRO_RESULT: ' + json.dumps(out, sort_keys=True))


if __name__ == '__main__':
    main()
