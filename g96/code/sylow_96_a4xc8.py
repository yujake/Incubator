#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sylow_96_a4xc8.py -- explicit witness REFUTING the statement

  "在 |G| = 96 且 H（不同 Sylow 3-子群交于单位元）成立时，2-元个数恒等于
   96 - 2*n_3，因此 n_2 = 1 的格子被排除"

G = A_4 x C_8, |G| = 12 * 8 = 96.  Elements are pairs (p, k) with p an even
permutation of {0,1,2,3} and k in Z/8; group law (p,k)*(q,l) = (p o q, k+l).

Everything below is computed from the 96 elements by this script:
no network, no GAP, no randomness, no external data files.

Why this group is a counterexample:
  A_4 has n_3 = 4, its four subgroups of order 3 meet pairwise only in the
  identity, and its Sylow 2-subgroup V_4 is normal.  Hence in A_4 x C_8
  * n_3 = 4 (NON-vacuous: the intersection hypothesis H really has content),
  * H holds: distinct Sylow 3-subgroups = Q x {0}, pairwise intersection {e},
  * n_2 = 1 (the 2-elements form V_4 x C_8, a normal subgroup of order 32),
  * #elements of order 3 = 8 = 2*n_3,
  * #2-elements = 32, but 96 - 2*n_3 = 88 ;
  the remaining 88 - 32 = 56 elements have order divisible by 3 and > 3
  (orders 6, 12, 24).
So H does not force "#2-elements = 96 - 2*n_3", and it does not exclude n_2 = 1.
"""

import json
import sys
import time
from itertools import permutations
from math import gcd

T0 = time.time()
ORDER = 96

# ------------------------------------------------------------------ A_4 -----


def compose(p, q):
    return tuple(p[q[i]] for i in range(4))


def perm_order(p):
    seen = [False] * 4
    o = 1
    for i in range(4):
        if not seen[i]:
            j, c = i, 0
            while not seen[j]:
                seen[j] = True
                j = p[j]
                c += 1
            o = o * c // gcd(o, c)
    return o


def sign(p):
    s = 1
    for i in range(4):
        for j in range(i + 1, 4):
            if p[i] > p[j]:
                s = -s
    return s


A4 = [p for p in permutations(range(4)) if sign(p) == 1]

# ------------------------------------------------------- G = A_4 x Z/8 ------

ELS = [(p, k) for p in A4 for k in range(8)]
IDENT = ((0, 1, 2, 3), 0)


def mul(x, y):
    return (compose(x[0], y[0]), (x[1] + y[1]) % 8)


def inv(x):
    p = x[0]
    pinv = [0] * 4
    for i in range(4):
        pinv[p[i]] = i
    return (tuple(pinv), (-x[1]) % 8)


def order(x):
    p, k = x
    ok = 1 if k == 0 else 8 // gcd(k, 8)
    op = perm_order(p)
    return op * ok // gcd(op, ok)


checks = []


def chk(name, ok, detail):
    ok = bool(ok)
    checks.append({"check": name, "ok": ok, "detail": detail})
    print("CHECK %s %s %s" % (name, "OK" if ok else "FAIL", detail))


chk("|A_4| = 12", len(A4) == 12, "%d" % len(A4))
chk("|G| = 96 and elements are distinct",
    len(ELS) == ORDER and len(set(ELS)) == ORDER, "%d" % len(ELS))
chk("identity acts trivially",
    all(mul(IDENT, x) == x and mul(x, IDENT) == x for x in ELS), "96 elements")
chk("every element has an inverse",
    all(mul(x, inv(x)) == IDENT for x in ELS), "96 elements")

ORD = {e: order(e) for e in ELS}
SPECTRUM = {}
for e in ELS:
    SPECTRUM[ORD[e]] = SPECTRUM.get(ORD[e], 0) + 1
print("order spectrum of A_4 x C_8: %s" % dict(sorted(SPECTRUM.items())))

# ord((p,k)) = lcm(ord(p), ord(k)); ord(p) in {1,2,3}, ord(k) in {1,2,4,8}
EXPECTED = {1: 1, 2: 7, 3: 8, 4: 8, 6: 8, 8: 16, 12: 16, 24: 32}
chk("order spectrum matches the lcm formula", SPECTRUM == EXPECTED,
    "spectrum=%s" % dict(sorted(SPECTRUM.items())))
chk("spectrum sums to |G|", sum(SPECTRUM.values()) == ORDER,
    "sum=%d" % sum(SPECTRUM.values()))

TWO = set(e for e in ELS if ORD[e] & (ORD[e] - 1) == 0)   # 2-power order


def is_subgroup(S):
    if IDENT not in S:
        return False
    for x in S:
        for y in S:
            if mul(x, y) not in S:
                return False
    return True


def normalizer(S):
    return set(g for g in ELS
               if set(mul(mul(g, s), inv(g)) for s in S) == S)


# --------------------------------------------------- Sylow 3-subgroups ------
SUBS3 = set()
for g in ELS:
    if ORD[g] == 3:
        SUBS3.add(frozenset((IDENT, g, mul(g, g))))
S3 = [set(s) for s in SUBS3]
N3 = len(S3)
chk("every order-3 subgroup is closed of order 3",
    all(len(S) == 3 and is_subgroup(S) for S in S3), "n_3 = %d" % N3)
chk("n_3 = 4", N3 == 4, "distinct subgroups of order 3: %d" % N3)

H_OK = True
for i in range(len(S3)):
    for j in range(i + 1, len(S3)):
        if (S3[i] & S3[j]) != {IDENT}:
            H_OK = False
chk("H: distinct Sylow 3-subgroups meet only in e  (NON-vacuous, n_3 = 4 > 1)",
    H_OK, "pairwise intersections all {e}")

# --------------------------------------------------- Sylow 2-subgroup -------
chk("2-element set is a subgroup of order 32",
    is_subgroup(TWO) and len(TWO) == 32, "|{g : ord(g) is a 2-power}| = %d" % len(TWO))
NGP = normalizer(TWO)
N2 = ORDER // len(NGP)
chk("n_2 = 1  (unique Sylow 2, normal)",
    N2 == 1 and len(NGP) == ORDER,
    "|N_G(P)| = %d, n_2 = 96/|N_G(P)| = %d" % (len(NGP), N2))

# ------------------------------------------------ normalisers of Sylow 3 ----
NGQ_SIZES = sorted(len(normalizer(S)) for S in S3)
chk("|N_G(Q)| = 96/n_3 = 24 for every Sylow 3-subgroup",
    all(s * N3 == ORDER for s in NGQ_SIZES), "sizes=%s" % NGQ_SIZES)
chk("orbit-stabiliser identity n_3 = [G:N_G(Q)]",
    all(ORDER // s == N3 for s in NGQ_SIZES), "n_3 = %d" % N3)

# ------------------------------------------------------ the refutation ------
ORDER3 = SPECTRUM.get(3, 0)
LEFT = ORDER - ORDER3
TWO_COUNT = len(TWO)
THREE_DIV_GT3 = sum(1 for e in ELS if ORD[e] % 3 == 0 and ORD[e] > 3)

print("elements of order 3                     = %d  (= 2*n_3 = %d)" % (ORDER3, 2 * N3))
print("elements NOT of order 3                 = %d  (= 96 - 2*n_3)" % LEFT)
print("  of which 2-elements                   = %d" % TWO_COUNT)
print("  of which ord divisible by 3 and > 3   = %d  (orders 6,12,24)" % THREE_DIV_GT3)

chk("#elements of order 3 = 2*n_3", ORDER3 == 2 * N3, "%d = 2*%d" % (ORDER3, N3))
chk("leftover decomposes into 2-elements + order divisible by 3 and > 3",
    TWO_COUNT + THREE_DIV_GT3 == LEFT,
    "%d + %d = %d" % (TWO_COUNT, THREE_DIV_GT3, LEFT))
chk("REFUTATION: #2-elements != 96 - 2*n_3", TWO_COUNT != LEFT,
    "%d != %d" % (TWO_COUNT, LEFT))
for k in (1, 2, 3, 4, 6, 8, 12, 24):
    print("PROGRESS: " + json.dumps({"order": k, "count": SPECTRUM.get(k, 0),
                                    "seconds": round(time.time() - T0, 4)},
                                   sort_keys=True))

COUNTEREXAMPLE = {
    "group": "A_4 x C_8 (explicit pairs (even permutation, k in Z/8))",
    "group_order": ORDER,
    "n_3": N3,
    "n_2": N2,
    "NGQ": NGQ_SIZES,
    "NGP": len(NGP),
    "H_holds_nonvacuously": True,
    "num_elements_order_3": ORDER3,
    "num_2_elements": TWO_COUNT,
    "num_order_divisible_by_3_gt_3": THREE_DIV_GT3,
    "leftover_not_order3": LEFT,
    "note": ("H holds with n_3 = 4 > 1 and yet n_2 = 1: the 2-elements form "
             "V_4 x C_8 of order 32, while 96 - 2*n_3 = 88. The missing 56 "
             "elements have order 6, 12 or 24. So H does NOT force "
             "'#2-elements = 96 - 2*n_3' and does NOT exclude n_2 = 1."),
}

REFUTED = ("在 |G| = 96 且 H（不同 Sylow 3-子群交于单位元）成立时，2-元个数恒等于 "
           "96 - 2*n_3，因此 n_2 = 1 的格子被排除")

ok_all = all(c["ok"] for c in checks)
print("checks: %d/%d passed" % (sum(1 for c in checks if c["ok"]), len(checks)))
summary = {
    "result": "refutes" if ok_all else "inconclusive",
    "refuted_statement": REFUTED,
    "counterexample": COUNTEREXAMPLE if ok_all else None,
    "group_order": ORDER,
    "n3": N3,
    "n2": N2,
    "NGQ": NGQ_SIZES[0] if NGQ_SIZES else None,
    "NGP": len(NGP),
    "order3_count": ORDER3,
    "two_elements": TWO_COUNT,
    "leftover_not_order3": LEFT,
    "order_divisible_by_3_gt_3": THREE_DIV_GT3,
    "spectrum": {str(k): v for k, v in sorted(SPECTRUM.items())},
    "H_holds_nonvacuously": bool(H_OK and N3 > 1),
    "checks_passed": sum(1 for c in checks if c["ok"]),
    "checks_total": len(checks),
    "bound": ("complete enumeration of the 96 elements of the single explicit "
              "group A_4 x C_8; no search over groups of order 96"),
    "strategy": ("explicit construction + brute force over 96 elements "
                 "(orders, subgroup closure, normaliser closure, "
                 "Sylow-3 intersection test)"),
    "scaling": {"elements": ORDER, "normalizer_passes": 1 + len(S3),
                "seconds": round(time.time() - T0, 4)},
    "unverified": [
        "number of isomorphism classes of groups of order 32 (the value 51 is NOT verified here)",
        "number of isomorphism classes of groups of order 96 (the value 231 is NOT verified here)",
        "which cells (n_3,n_2) are realised by some group of order 96 "
        "(witnessed here: (1,1) and (4,1); (16,1),(1,3),(4,3),(16,3) NOT witnessed)",
    ],
}
print("REPRO_RESULT: " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

if not ok_all:
    for c in checks:
        if not c["ok"]:
            print("FAILED CHECK: %s :: %s" % (c["check"], c["detail"]))
    sys.exit(1)
sys.exit(0)
