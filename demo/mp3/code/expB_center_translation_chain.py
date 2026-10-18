#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expB (subgoal S2, family (ii)): central-translation family in U(h_inf).

g = h_inf: generators a_i, b_i (i>=1), z central, [a_i,b_i] = z, all other brackets 0.
PBW normal form: z^e * (word in a_i,b_i ordered by a_1<a_2<...<b_1<b_2<...).
Weight: wt(a_i) = wt(b_i) = 1, wt(z) = 2 (relation [a_i,b_i]=z is homogeneous).

Family (ii): I_n = U(g) * g_n  with  g_n = a_1*b_1 - n*z,  n = 1..8.

Tested statement (bounded):
  (T) for every n = 1..7 the adjacent inclusion I_n <= I_{n+1} holds, i.e. there is a
      multiplier u with wt(u) <= WU (=4) such that u * g_{n+1} = g_n;
      and more generally for m != n, g_m lies in U(g) g_n.

Everything is decided here, by code:
  * exact integer PBW normal forms (relation b_i a_i = a_i b_i - z, other letters commute),
  * exact rational linear algebra over the weight-2 graded piece,
  * a dual functional certificate for every negative membership answer: a functional
    lambda with lambda(u * g_n) = 0 for all tested multipliers u and lambda(g_m) = 1.
    That functional is a machine-checkable certificate of g_m NOT in U(g) g_n.
No LLM is in the loop. Protocol: PROGRESS lines + exactly one REPRO_RESULT line.
"""
import json
import time
from fractions import Fraction

T0 = time.time()


# ---------------- PBW engine for U(h_inf) ----------------
def lkey(L):
    # total order on letters: a_1<a_2<...<b_1<b_2<...
    return (0 if L[0] == 'a' else 1, L[1])


_cc = {}


def norm(letters):
    """Normal-order a tuple of letters -> {(z_exp, letter_word): int coeff}."""
    if letters in _cc:
        return _cc[letters]
    for idx in range(len(letters) - 1):
        x, y = letters[idx], letters[idx + 1]
        if lkey(x) > lkey(y):
            if x[0] == 'b' and y[0] == 'a' and x[1] == y[1]:
                i = x[1]                       # b_i a_i = a_i b_i - z
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


def gen_n(n):
    """g_n = a_1 b_1 - n z  in PBW normal form."""
    return {(0, (('a', 1), ('b', 1))): 1, (1, ()): -n}


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
    """Reduce a coordinate vector by the span. Returns (in_span, remainder)."""
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
    """lambda with lambda(row)=0 for all rows and lambda(target)=1, or None.
    Exists iff target is NOT in the rational span of rows. Exact elimination."""
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
    """All PBW monomials (z_exp, sorted letter word) of weight <= W over given indices."""
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

    # ---- engine self tests ----
    st = []
    cv = add(mul(U((('a', 1),)), U((('b', 1),))), mul(U((('b', 1),)), U((('a', 1),))), -1)
    st.append({"test": "[a_1,b_1] = z", "value": fmt(cv), "ok": cv == {(1, ()): 1}})
    cv = add(mul(U((('a', 1),)), U((('b', 2),))), mul(U((('b', 2),)), U((('a', 1),))), -1)
    st.append({"test": "[a_1,b_2] = 0", "value": fmt(cv), "ok": cv == {}})
    # NOTE: U((('b',1),('a',1))) puts an *un-normalised* key into the dict, so the
    # equality below can never hold; build b_1*a_1 through mul() so it is normal-ordered.
    cv = add(mul(U((('b', 1),)), U((('a', 1),))), gen_n(1), -1)
    st.append({"test": "b_1 a_1 = a_1 b_1 - z", "value": fmt(cv), "ok": cv == {}})
    st.append({"test": "g_n homogeneous of weight 2",
               "ok": all(wt(k) == 2 for k in gen_n(5))})
    for t in st:
        P("SELFTEST " + json.dumps(t))

    IDX = [1, 2]      # alphabet a_i,b_i for i in IDX, plus the central z
    WU = 4            # weight bound on the multiplier u
    NMEM = 8          # chain members I_1..I_8
    ukeys = [k for k in enum_keys(IDX, WU) if wt(k) <= WU]
    keys2 = [k for k in enum_keys(IDX, 2) if wt(k) == 2]
    pos2 = dict((k, i) for i, k in enumerate(keys2))
    inv2 = dict((i, k) for k, i in pos2.items())
    P("PROGRESS " + json.dumps({"stage": "setup", "dim_weight2_space": len(keys2),
                                "num_multipliers": len(ukeys), "multiplier_weight_bound": WU,
                                "alphabet": "a_1,b_1,a_2,b_2,z",
                                "weight": "wt(a)=wt(b)=1, wt(z)=2"}))

    # ---- check (in range): only the constant multiplier can contribute weight-2 components ----
    bad = []
    for n in range(1, NMEM + 1):
        for u in ukeys:
            if wt(u) == 0:
                continue
            prod = mul({u: 1}, gen_n(n))
            if any(wt(k) == 2 for k in prod):
                bad.append({"n": n, "u": str(u)})
    P("PROGRESS " + json.dumps({"stage": "only_constant_multiplier_hits_weight2",
                                "violations": len(bad), "example": bad[:3]}))

    # ---- diagonal control: u = 1 gives 1 * g_n = g_n (machinery can see membership) ----
    ident = {(0, ()): 1}
    diag = {}
    for n in range(1, NMEM + 1):
        diag[n] = (mul(ident, gen_n(n)) == gen_n(n))
    P("PROGRESS " + json.dumps({"stage": "diagonal_witness",
                                "all_ok": all(diag.values())}))

    # ---- pairwise: is g_m in U(g) g_n ?  (certificate when not) ----
    pairs = {}
    scale = {}
    for n in range(1, NMEM + 1):
        t_n = time.time()
        rows2 = [vec(mul({u: 1}, gen_n(n)), pos2) for u in ukeys]
        rows2 = [r for r in rows2 if r]
        for m in range(1, NMEM + 1):
            key = "L%d:%d" % (n, m)          # key reads: 'is g_m in U(g) g_n ?'
            if m == n:
                pairs[key] = {"membership": True, "witness": "u = 1, 1*g_n = g_n"}
                continue
            tgt = vec(gen_n(m), pos2)
            lam = dual_cert(rows2, tgt)
            if lam is None:
                pairs[key] = {"membership": "undecided_no_separating_functional"}
                continue
            kills = all(sum(Fraction(lam.get(c, 0)) * Fraction(r.get(c, 0))
                            for c in set(list(lam.keys()) + list(r.keys()))) == 0
                        for r in rows2)
            val = sum(Fraction(lam.get(c, 0)) * Fraction(tgt.get(c, 0))
                      for c in set(list(lam.keys()) + list(tgt.keys())))
            pairs[key] = {"membership": False,
                          "num_products_with_weight2_component": len(rows2),
                          "certificate_kills_all_products": kills,
                          "certificate_value_on_target": str(val),
                          "certificate_verified": bool(kills and val == 1),
                          "separation_functional": dict((fmt({inv2[c]: 1}), str(v))
                                                        for c, v in sorted(lam.items()))}
        scale["n=%d" % n] = round(time.time() - t_n, 3)
        P("PROGRESS " + json.dumps({"stage": "row_n_done", "n": n,
                                    "nonzero_products_in_weight2": len(rows2),
                                    "dim_ambient_weight2": len(keys2)}))

    adj = []
    for n in range(1, NMEM):
        e = pairs["L%d:%d" % (n, n + 1)]
        adj.append({"n": n, "I_n_subset_I_n1": e.get("membership"),
                    "certificate_verified": e.get("certificate_verified", None)})

    adj_all_fail = all(a["I_n_subset_I_n1"] is False for a in adj)
    adj_certs = all(a.get("certificate_verified") for a in adj)
    offdiag = [v for k, v in pairs.items() if k.split(":")[0][1:] != k.split(":")[1]]
    offdiag_all_false = all(v.get("membership") is False for v in offdiag)
    certs_all = all(v.get("certificate_verified") for v in offdiag)
    result = "refutes" if (all(st) and adj_all_fail and adj_certs and offdiag_all_false and certs_all) else "inconclusive"

    ce = None
    if result == "refutes":
        e = pairs["L1:2"]
        ce = {"n": 1,
              "statement_refuted": "I_1 <= I_2, i.e. g_1 = a_1*b_1 - 1*z lies in U(g)*(a_1*b_1 - 2*z)",
              "generator_of_I_2": "g_2 = a_1*b_1 - 2*z",
              "multiplier_weight_bound": WU,
              "num_multipliers_tested": len(ukeys),
              "num_products_with_weight2_component": e.get("num_products_with_weight2_component"),
              "separation_functional": e.get("separation_functional"),
              "certificate_kills_all_products": e.get("certificate_kills_all_products"),
              "certificate_value_on_target": e.get("certificate_value_on_target"),
              "certificate_verified": e.get("certificate_verified"),
              "check": "for every tested u: lambda(u*g_2)=0 while lambda(g_1)=1",
              "reproduce": "python code/expB_center_translation_chain.py"}

    out = {
        "result": result,
        "family": "(ii) I_n = U(g)*(a_1 b_1 - n z), n = 1..8",
        "question": "does the central-translation family give an ascending chain of left ideals in U(h_inf)?",
        "bound": {"n_members": NMEM, "n_adjacent_comparisons": [1, NMEM - 1],
                  "multiplier_weight_bound": WU,
                  "coordinate_space": "weight-2 graded piece over alphabet a_1,b_1,a_2,b_2,z",
                  "dim_weight2_space": len(keys2),
                  "weight_convention": "wt(a_i)=wt(b_i)=1, wt(z)=2 (relation homogeneous)",
                  "not_covered": "multipliers of weight > 4 (outside this run); n > 8"},
        "strategy": "exact integer PBW normal forms + exact rational dual-functional certificate "
                    "per non-membership answer (kills every tested product u*g_n, value 1 on g_m); "
                    "diagonal u=1 as positive control",
        "self_tests": st,
        "diagonal_control": dict((str(k), v) for k, v in diag.items()),
        "nonconstant_multiplier_hits_weight2_violations": len(bad),
        "pairwise_Ln_contains_gm": pairs,
        "adjacent_inclusions": adj,
        "scaling": {"per_n_sec": scale, "total_sec": round(time.time() - T0, 3)},
        "counterexample": ce,
        "note": "numeric evidence only (cross_check, no formalisation, no theorem). "
                "Reading: family (ii) is NOT ascending in the checked range -- adjacent inclusions "
                "fail with explicit separating functionals; the 8 members are pairwise non-comparable "
                "in the weight-2 graded piece. This refutes the *candidate family*, NOT the general "
                "existence question (family (i), exp 000008, numerically supports existence for n<=8).",
    }
    P("REPRO_RESULT: " + json.dumps(out, default=str))


if __name__ == "__main__":
    main()
