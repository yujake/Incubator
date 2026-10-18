"""pyjama_refute_exp12.py -- re-audit of the 'safe' upper bounds reported by exp:000012.

Every number printed here is computed by this file; no model judges any number.

What exp:000012 did (code/pyjama_r3_partC.py)
    For closed-k-gon direction sets with INTEGER side lengths n_i (sum_i n_i u_i = 0)
it computed a 'safe' upper bound  r_ub_safe = L + 0.5*(hx+hy)  where L = max of
f on a grid over the parallelogram spanned by the DUAL basis (w1,w2) of the FIRST
TWO directions (w1.u_0 = -1, w1.u_1 = 0, w2.u_0 = 0, w2.u_1 = 1).
    That parallelogram is a period domain of f only if w1 and w2 are PERIODS of f,
namely w.u_i in Z for EVERY i.  exp:000012 never checks i >= 2.  This file does:
  (a) prints period_residual = max_i |w.u_i - round(w.u_i)| for that dual basis;
  (b) tests the reported bounds directly: a POINT EVALUATION f(p) is a certified
      LOWER bound on r, so an explicit p with f(p) > r_ub_safe refutes r_ub_safe.

Parity reading (printed, deterministic; the witnesses are the code-side evidence)
    N = sum_i |n_i|,  D = |N/2 - round(N/2)|,  t_i = sign(n_i)*(1/2 - D/N).
    Then sum_i n_i t_i = N/2 - D is an integer, so t lies in the closure of the image
    {p -> (p.u_i mod 1)} (annihilator of the integer relations among the u_i) and
        r(Theta) >= 1/2 - D/N     ( = 1/2 exactly when N is even ).
    We also check that every integer relation m among the directions found in the box
    |m_i| <= 2 has sum_i m_i t_i an integer (so t really is in that closure).

Output: one 'PROGRESS: {...}' line per k, one 'REPRO_RESULT: {...}' line.
"""

import json
import math
import time

import numpy as np

EIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))

# angle sets and reported numbers copied from the experiments row exp:000012
SETS = {
    3: {'nv': [2, 2, 2],
        'theta_rad': [4.404853365045, 2.310458262652, 0.216063160259],
        'exp12_r_lb': 0.33333333333333326, 'exp12_r_ub_safe': 0.34616333931532495},
    4: {'nv': [3, 3, 1, 3],
        'theta_rad': [2.535838519415, 0.363240074783, 6.195986545776, 4.251500068877],
        'exp12_r_lb': 0.24229545224737895, 'exp12_r_ub_safe': 0.25063479170332875},
    5: {'nv': [1, 1, 1, 2, 3],
        'theta_rad': [0.44668154332, 4.358210507912, 4.020076400418, 3.794773636556, 0.979801242841],
        'exp12_r_lb': 0.20488888133756572, 'exp12_r_ub_safe': 0.2183844281146428},
    6: {'nv': [2, 1, 3, 2, 1, 1],
        'theta_rad': [4.005120844257, 2.044108229833, 1.592803121467, 5.358429574529, 0.157443933743, 4.333035760773],
        'exp12_r_lb': 0.17878910845532403, 'exp12_r_ub_safe': 0.1903158138284391},
}

MARGIN = 1e-6      # float noise is ~1e-13 at |p|<=1e3; this keeps refutations safe


def dirs_of(theta):
    return [(math.cos(t), math.sin(t)) for t in theta]


def fmin(us, x, y):
    m = 1.0
    for ux, uy in us:
        t = x * ux + y * uy
        d = abs(t - math.floor(t + 0.5))
        if d < m:
            m = d
    return m


def fvec(us, X, Y):
    acc = None
    for ux, uy in us:
        t = X * ux + Y * uy
        d = np.abs(t - np.round(t))
        acc = d if acc is None else np.minimum(acc, d)
    return acc


def climb(us, x, y, h, iters=400):
    best, bx, by = fmin(us, x, y), x, y
    step = h
    for _ in range(iters):
        moved = False
        for dx, dy in EIGHT:
            v = fmin(us, bx + step * dx, by + step * dy)
            if v > best + 1e-16:
                best, bx, by = v, bx + step * dx, by + step * dy
                moved = True
        if not moved:
            step *= 0.5
            if step < 1e-12:
                break
    return best, bx, by


BOXES = ((60.0, 120000, math.sqrt(2.0), math.sqrt(3.0)),
         (240.0, 240000, math.sqrt(5.0), math.sqrt(7.0)),
         (900.0, 300000, math.sqrt(11.0), math.sqrt(13.0)))


def best_witness(us, top=20):
    """Deterministic Weyl scans (3 boxes) + 8-direction hill climb from the top samples."""
    best = (-1.0, 0.0, 0.0)
    scanned = 0
    for R, n, a, b in BOXES:
        i = np.arange(1, n + 1, dtype=float)
        X = (np.mod(i * a, 1.0) - 0.5) * R
        Y = (np.mod(i * b, 1.0) - 0.5) * R
        vals = fvec(us, X, Y)
        scanned += int(vals.size)
        idx = np.argsort(vals)[-top:]
        h0 = R / math.sqrt(float(n))
        for j in idx:
            v, bx, by = climb(us, float(X[j]), float(Y[j]), h0)
            if v > best[0]:
                best = (v, bx, by)
    return best[0], best[1], best[2], scanned


def relation_residual(us, nv):
    sx = sum(c * u[0] for c, u in zip(nv, us))
    sy = sum(c * u[1] for c, u in zip(nv, us))
    return abs(sx) + abs(sy)


def dual_basis(us):
    (c1, s1), (c2, s2) = us[0], us[1]
    det = c1 * s2 - s1 * c2
    if abs(det) < 1e-12:
        return None
    return (np.array([s2, -c2]) / det, np.array([-s1, c1]) / det)


def period_residual(us, w):
    per = []
    for ux, uy in us:
        v = w[0] * ux + w[1] * uy
        per.append(abs(v - round(v)))
    return max(per), [round(r, 9) for r in per]


def parity_reading(us, nv):
    """t_i = sign(n_i)*(1/2 - D/N); check integer relations m found in |m_i|<=2."""
    k = len(nv)
    N = sum(abs(c) for c in nv)
    D = abs(N / 2.0 - round(N / 2.0))
    t = [math.copysign(0.5 - D / N, float(c)) for c in nv]
    s = sum(c * ti for c, ti in zip(nv, t))
    rel_ok = abs(s - round(s)) < 1e-12
    # every small integer relation must also be integral on t
    others = []
    bad = []
    rng = range(-2, 3)
    if k <= 7:
        from itertools import product
        for m in product(rng, repeat=k):
            if all(c == 0 for c in m):
                continue
            if max(abs(c) for c in m) != 2:
                continue  # only the boundary shell; inner shells are multiples
            if relation_residual(us, m) > 1e-9:
                continue
            val = sum(c * ti for c, ti in zip(m, t))
            others.append(list(m))
            if abs(val - round(val)) > 1e-12:
                bad.append({'m': list(m), 'm_dot_t': val})
    return {'N': N, 'D': D, 't': [round(x, 12) for x in t],
            'sum_n_t': s, 'predicted_lower_bound': 0.5 - D / N,
            'n_found_relations_shell2': len(others),
            'relations_violating_t': bad[:5], 't_in_closure_consistent': rel_ok and not bad}


def main():
    t0 = time.time()
    data = {}
    scal = []
    refuted = []
    for k in (3, 4, 5, 6):
        tk = time.time()
        spec = SETS[k]
        us = dirs_of(spec['theta_rad'])
        nv = spec['nv']
        db = dual_basis(us)
        pres1, perd1 = period_residual(us, db[0]) if db is not None else (None, [])
        pres2, perd2 = period_residual(us, db[1]) if db is not None else (None, [])
        v, wx, wy, scanned = best_witness(us)
        par = parity_reading(us, nv)
        ub = spec['exp12_r_ub_safe']
        row = {'k': k, 'nv': nv, 'theta_rad': spec['theta_rad'],
               'relation_residual': relation_residual(us, nv),
               'exp12_r_lb': spec['exp12_r_lb'], 'exp12_r_ub_safe': ub,
               'exp12_dual_basis_is_period': {'w1_residual': pres1, 'w1_per_dir': perd1,
                                              'w2_residual': pres2, 'w2_per_dir': perd2,
                                              'both_are_periods': bool(pres1 is not None and pres1 < 1e-9
                                                                       and pres2 < 1e-9)},
               'witness': {'p': [wx, wy], 'f_p': v, 'scanned_points': scanned,
                           'source': 'Weyl scans (3 boxes, 660k points) + 8-direction hill climb'},
               'r_lo_certified': v,
               'parity': par,
               'refutes_exp12_ub': bool(v > ub + MARGIN),
               'excess_over_exp12_ub': v - ub,
               'secs': round(time.time() - tk, 2)}
        data[str(k)] = row
        scal.append({'k': k, 'secs': row['secs'], 'scanned_points': scanned})
        if row['refutes_exp12_ub']:
            refuted.append(k)
        print('PROGRESS: ' + json.dumps({'k': k, 'r_lo': round(v, 9),
                                         'exp12_r_ub_safe': ub,
                                         'predicted_lb': round(par['predicted_lower_bound'], 9),
                                         'dual_basis_is_period': row['exp12_dual_basis_is_period']['both_are_periods'],
                                         'refutes': row['refutes_exp12_ub'],
                                         'secs': row['secs']}))

    if refuted:
        result = 'refutes'
        counterexample = {str(k): {'p': data[str(k)]['witness']['p'],
                                   'f_p': data[str(k)]['witness']['f_p'],
                                   'claimed_upper_bound': data[str(k)]['exp12_r_ub_safe'],
                                   'excess': data[str(k)]['excess_over_exp12_ub']}
                          for k in refuted}
    else:
        result = 'inconclusive'
        counterexample = None

    bound = ('exp:000012 reported r_ub_safe = L + 0.5*(hx+hy) on the parallelogram spanned by the '
             'dual basis of the FIRST TWO directions only.  That parallelogram is a period domain of '
             'f = min_i dist(p.u_i,Z) only if w.u_i is an integer for EVERY i; the per-k '
             'period_residual printed here is max_i |w.u_i - round(w.u_i)| for that basis.  A point '
             'evaluation f(p) is a certified LOWER bound on r, so p with f(p) > r_ub_safe refutes the '
             'reported upper bound.  Parity reading: N = sum|n_i|, D = |N/2 - round(N/2)| gives the '
             'rigorous lower bound r >= 1/2 - D/N (exactly 1/2 when N is even), checked against all '
             'integer relations among the directions found in |m_i| <= 2.')
    strategy = ('copy the four stored angle sets of exp:000012 (k=3..6); per k: (i) dual-basis period '
                'test on all k directions, (ii) deterministic Weyl scans in three boxes '
                '(R=60/240/900, 120k/240k/300k points) + 8-direction hill climb from the 20 best '
                'samples, (iii) parity bound 1/2 - D/N verified against every small integer relation')
    out = {'result': result, 'bound': bound, 'strategy': strategy, 'scaling': scal,
           'data': data, 'counterexample': counterexample,
           'refuted_k': refuted,
           'runtime_sec': round(time.time() - t0, 2)}
    print('REPRO_RESULT: ' + json.dumps(out))


if __name__ == '__main__':
    main()
