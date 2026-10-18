"""pyjama_rational_block.py -- exact certificate: EVERY rational direction set has r = 1/2.

Setting
    r(Theta) = sup_{p in R^2} f(p),   f(p) = min_i dist(p . u_i, Z),
    dist(t,Z) = |t - round(t)|.

Fact certified here by exact rational arithmetic (fractions.Fraction, no model in the loop)
    Let u = (a,b)/n with coprime integers a,b and n = sqrt(a^2+b^2) an integer
    ("rational direction").  Then n is odd and a+b is odd -- checked EXHAUSTIVELY below
    on a box.  Let L be any odd common multiple of the n_i of a finite family {u_i}.
    For p = (L/2, L/2):
        p . u_i = (L/n_i) * (a_i + b_i) / 2 = odd * odd / 2 = half-integer,
    so dist(p.u_i, Z) = 1/2 for EVERY i, hence f(p) = 1/2.
    With the trivial bound f <= 1/2 (every single dist <= 1/2) this gives
        r(Theta) = 1/2   EXACTLY, for every finite set of rational directions.

Consequence for the Pyjama covering-radius job (exp:000012 / exp:000017 family class)
    No rational direction set can certify r <= eps < 1/2, whatever its size k: the point
    (L/2,L/2) always blocks.  So "more integer-relation directions" cannot reach eps=0.1.
    Irrational families are genuinely different: the equilateral 3-line set has r = 1/3
    (exp:000004 case B exact-free bracket, exp:000016 k=3 [0.3333333, 0.3346163]).

Every number printed here is computed by this file; no model judges any number.
Output: one PROGRESS line per block, exactly one REPRO_RESULT line.
"""

import json
import math
import random
import time
from fractions import Fraction

EPSC = [0.1, 0.05]
LEMMA_BOX = 150
NRAND = 300
SEED = 20261019


def is_square(n):
    r = math.isqrt(n)
    return (r * r == n), r


def dist_to_int(t):
    """exact |t - round(t)| for a Fraction t"""
    fl = math.floor(t)
    r = t - fl
    if r > Fraction(1, 2):
        r = 1 - r
    return r


def family_certificate(vectors):
    """vectors: list of (a,b) nonzero integer pairs.  Returns the exact certificate."""
    ns = []
    for a, b in vectors:
        ok, n = is_square(a * a + b * b)
        if not ok:
            return {'ok': False, 'why': 'non-rational direction (%d,%d)' % (a, b)}
        ns.append(n)
    L = 1
    for n in ns:
        L = L * n // math.gcd(L, n)
    if L % 2 == 0:
        return {'ok': False, 'why': 'even common multiple L=%d' % L}
    for n in ns:
        if L % n:
            return {'ok': False, 'why': 'L=%d not a multiple of n=%d' % (L, n)}
    P = (Fraction(L, 2), Fraction(L, 2))
    ds = []
    for (a, b), n in zip(vectors, ns):
        t = (a * P[0] + b * P[1]) / n
        ds.append(dist_to_int(t))
    ok = all(d == Fraction(1, 2) for d in ds)
    return {'ok': ok, 'L': L, 'n_dirs': len(vectors),
            'lengths': sorted(set(ns)),
            'dists_at_center': [str(d) for d in ds],
            'center_p': [str(P[0]), str(P[1])],
            'f_at_center': str(min(ds))}


def main():
    t_all = time.time()
    scal = []
    data = {}

    # ---- lemma: primitive square-norm vector => n odd and a+b odd ----------------
    t0 = time.time()
    n_prim = 0
    n_sq = 0
    bad = []
    for a in range(-LEMMA_BOX, LEMMA_BOX + 1):
        for b in range(-LEMMA_BOX, LEMMA_BOX + 1):
            if a == 0 and b == 0:
                continue
            if math.gcd(abs(a), abs(b)) != 1:
                continue
            n_prim += 1
            ok, n = is_square(a * a + b * b)
            if not ok:
                continue
            n_sq += 1
            if n % 2 == 0 or (a + b) % 2 == 0:
                bad.append([a, b, n])
    lemma = {'box': LEMMA_BOX, 'n_primitive_vectors': n_prim,
             'n_with_square_norm': n_sq, 'violations': bad,
             'n_violations': len(bad), 'secs': round(time.time() - t0, 2)}
    data['lemma_parity'] = lemma
    scal.append({'block': 'lemma', 'vectors': n_prim, 'secs': lemma['secs']})
    print('PROGRESS: ' + json.dumps({'block': 'lemma_parity', 'checked': n_prim,
                                     'square_norm': n_sq, 'violations': len(bad)}))

    # ---- exp:000004 case A and case C as instances --------------------------------
    vA = [(5, 0), (0, 5), (3, 4), (4, 3), (3, -4), (4, -3)]
    vC = [(5, 0), (0, 5), (3, 4), (4, 3), (3, -4), (4, -3),
          (13, 0), (0, 13), (5, 12), (12, 5), (5, -12), (12, -5)]
    data['exp4_caseA_6lines'] = family_certificate(vA)
    data['exp4_caseC_12lines'] = family_certificate(vC)
    print('PROGRESS: ' + json.dumps({'block': 'exp4_cases',
                                     'A_ok': data['exp4_caseA_6lines']['ok'],
                                     'C_ok': data['exp4_caseC_12lines']['ok'],
                                     'A_L': data['exp4_caseA_6lines']['L'],
                                     'C_L': data['exp4_caseC_12lines']['L']}))

    # ---- random rational families, sizes 1..8 ------------------------------------
    t0 = time.time()
    rng = random.Random(SEED)
    pool = []
    for a in range(-120, 121):
        for b in range(-120, 121):
            if a == 0 and b == 0:
                continue
            if a < 0 or (a == 0 and b < 0):
                continue                      # one representative per line
            if math.gcd(abs(a), abs(b)) != 1:
                continue
            ok, n = is_square(a * a + b * b)
            if ok:
                pool.append((a, b))
    fam = []
    n_fail = 0
    n_dirs_total = 0
    for _ in range(NRAND):
        k = rng.randint(1, 8)
        vec = rng.sample(pool, k)
        cert = family_certificate(vec)
        n_dirs_total += k
        if not cert['ok']:
            n_fail += 1
            fam.append({'vectors': vec, 'cert': cert})
    rand = {'pool_size': len(pool), 'n_families': NRAND, 'n_directions_total': n_dirs_total,
            'n_failed': n_fail, 'failures': fam[:5], 'secs': round(time.time() - t0, 2)}
    data['random_families'] = rand
    scal.append({'block': 'random_rational', 'families': NRAND, 'secs': rand['secs']})
    print('PROGRESS: ' + json.dumps({'block': 'random_rational', 'pool': len(pool),
                                     'families': NRAND, 'failed': n_fail,
                                     'secs': rand['secs']}))

    # ---- verdict -----------------------------------------------------------------
    allcases = [lemma['n_violations'] == 0,
                data['exp4_caseA_6lines']['ok'],
                data['exp4_caseC_12lines']['ok'],
                rand['n_failed'] == 0]
    eps_ok = {str(e): {'any_rational_family_with_r_below_eps': False} for e in EPSC}
    data['eps_reading'] = eps_ok
    if all(allcases):
        result = 'supports'
        counterexample = None
    else:
        result = 'refutes'
        counterexample = {'lemma_violations': lemma['violations'][:5],
                          'failed_families': rand['failures'][:3],
                          'caseA': data['exp4_caseA_6lines'],
                          'caseC': data['exp4_caseC_12lines']}

    bound = ('EXACT (Fraction arithmetic, no floats in the certificate): for every finite set of '
             'rational directions u_i = (a_i,b_i)/n_i (coprime integers, n_i = sqrt(a_i^2+b_i^2) '
             'integer) and L = any odd common multiple of the n_i, the single point '
             'p = (L/2, L/2) has p.u_i = (L/n_i)(a_i+b_i)/2 = odd*odd/2 = half-integer for every i, '
             'hence f(p) = min_i dist(p.u_i,Z) = 1/2.  Since dist <= 1/2 always, r(Theta) = 1/2 '
             'exactly.  Consequence (scope): in the construction class of exp:000012 / exp:000017 '
             '(closed polygons with INTEGER side lengths, rational directions) the covering radius is '
             'pinned at 1/2 for EVERY k, so neither eps=0.1 nor eps=0.05 can ever be certified there '
             '-- the failure of exp:000012 ub in exp:000018 and the trivial 1/2 in exp:000017 are '
             'not search artefacts.  Irrational families are different: equilateral 3 lines has '
             'r = 1/3 (exp:000004 case B; exp:000016 k=3 gives [0.3333333, 0.3346163]).')
    strategy = ('exact rational arithmetic (Fraction) at the single witness point (L/2,L/2) + '
                'exhaustive parity lemma check on primitive vectors |a|,|b| <= %d + deterministic '
                'sampling of %d rational families of size 1..8 from %d primitive square-norm lines '
                '(seed %d)' % (LEMMA_BOX, NRAND, rand['pool_size'], SEED))
    scal.append({'block': 'total', 'secs': round(time.time() - t_all, 2)})
    print('REPRO_RESULT: ' + json.dumps({
        'result': result, 'counterexample': counterexample, 'bound': bound,
        'strategy': strategy, 'scaling': scal,
        'claim': ('Every finite set of rational directions (u_i=(a_i,b_i)/n_i with n_i integer) has '
                  'covering radius r(Theta) = sup_p min_i dist(p.u_i,Z) equal to exactly 1/2.'),
        'data': data}, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
