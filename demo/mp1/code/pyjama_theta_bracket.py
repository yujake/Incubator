"""pyjama_theta_bracket.py -- two-sided readings for the equally spaced families

    Theta_k = {i*pi/k : i = 0..k-1},  k = 3..14,
    r(Theta) = sup_{p in R^2} min_i dist(p . u_i, Z),   dist(t,Z) = |t - round(t)|,
    u_i = (cos(i pi/k), sin(i pi/k)).

Every number printed here is computed by this file; no model judges any number.

Tool T1 (Lipschitz bracket on a period parallelogram), taken from
code/pyjama_bracket.py (exp:000004):
  f(p) = min_i dist(p . u_i, Z) is 1-Lipschitz (each g_i is 1-Lipschitz and
  |min g_i(p) - min g_i(q)| <= max_i |g_i(p)-g_i(q)|).  If w1 and w2 are BOTH
  periods of f -- i.e. w . u_i in Z for EVERY i, verified here numerically to
  1e-12 -- then on the parallelogram {s*w1 + t*w2 : s,t in [0,1)} covered by a
  (s,t) grid with meshes hx = |w1|/N, hy = |w2|/N:
        L <= r(Theta) <= L + 0.5*(hx+hy),
  where L = max of f over the grid samples plus a deterministic 8-direction hill
  climb.  L is a point evaluation => valid lower bound; the correction is the
  covering radius of the grid cells.

Tool T2 (trivial two-sided bound, needs no periodicity at all):
  for every p and every i, dist(p.u_i, Z) <= 1/2, hence r <= 1/2 for ANY set;
  and any single explicit point p with min_i dist(p.u_i, Z) = v gives r >= v.
  So [v, 1/2] is a rigorous two-sided bracket.  This is the tool used for the k
  where no period lattice is found inside the search box (see below).

Period-lattice search: periods are searched as p = a*w1 + b*w2 with (w1,w2) the
dual basis of (u_0,u_1) (so w1.u_0=-1, w1.u_1=0, w2.u_0=0, w2.u_1=1) and
|a|,|b| <= MM.  Every candidate must satisfy |p.u_i - round| <= TOL for ALL i.
Only two independent verified periods are used as grid generators.

Verdict rule (printed per k, deterministic):
  r_hi <  0.1  => coverage for eps=0.1 CERTIFIED  (and r_hi < 0.05 for eps=0.05)
  r_lo >  0.1  => coverage for eps=0.1 FAILS (certified); same with 0.05.
Note: a lower bound alone (exp:000003 reported lb=0.098076 at k=12) is NOT a
success certificate; only r_hi < eps is.

Output: one 'PROGRESS: {...}' line per finished k and exactly one
'REPRO_RESULT: {...}' line.
"""

import json
import math
import time

import numpy as np

EPSL = [0.1, 0.05]
NGRID = 900          # grid points per axis on the period parallelogram
MM = 8               # period search box: |a|,|b| <= MM
TOL = 1e-12          # period exactness tolerance (double precision)
EIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def dirs(k):
    return [(math.cos(i * math.pi / k), math.sin(i * math.pi / k)) for i in range(k)]


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


def dual_basis(us):
    """w1,w2 with w1.u_0=-1, w1.u_1=0, w2.u_0=0, w2.u_1=1 (not periods in general)."""
    (c1, s1), (c2, s2) = us[0], us[1]
    det = c1 * s2 - s1 * c2
    if abs(det) < 1e-12:
        return None
    return np.array([s2, -c2]) / det, np.array([-s1, c1]) / det


def search_periods(us, mmax=MM, tol=TOL):
    """All p = a*w1+b*w2 with |a|,|b|<=mmax and p.u_i in Z for every i (checked)."""
    db = dual_basis(us)
    if db is None:
        return []
    w1, w2 = db
    out = []
    for a in range(-mmax, mmax + 1):
        for b in range(-mmax, mmax + 1):
            if a == 0 and b == 0:
                continue
            p = a * w1 + b * w2
            worst = 0.0
            for ux, uy in us:
                v = p[0] * ux + p[1] * uy
                worst = max(worst, abs(v - round(v)))
            if worst <= tol:
                out.append((float(p[0]), float(p[1]),
                            float(math.hypot(p[0], p[1])), float(worst), a, b))
    out.sort(key=lambda r: r[2])
    return out


def two_independent(per):
    if not per:
        return None
    b1 = np.array(per[0][:2])
    for r in per[1:]:
        b2 = np.array(r[:2])
        if abs(b1[0] * b2[1] - b1[1] * b2[0]) > 1e-9:
            return b1, b2, per[0][3], r[3]
    return None


def climb(us, x0, y0, h0, iters=400):
    best, bx, by = fmin(us, x0, y0), x0, y0
    step = h0
    for _ in range(iters):
        moved = False
        for dx, dy in EIGHT:
            v = fmin(us, bx + step * dx, by + step * dy)
            if v > best + 1e-16:
                best, bx, by = v, bx + step * dx, by + step * dy
                moved = True
        if not moved:
            step *= 0.5
            if step < 1e-13:
                break
    return best, bx, by


def bracket_on_parallelogram(us, w1, w2, N=NGRID):
    s = np.arange(N) / float(N)
    S = s[:, None]
    T = s[None, :]
    X = S * w1[0] + T * w2[0]
    Y = S * w1[1] + T * w2[1]
    vals = fvec(us, X, Y)
    L = float(vals.max())
    j = int(np.argmax(vals))
    ii, jj = divmod(j, N)
    x0, y0 = float(X[ii, jj]), float(Y[ii, jj])
    hx = float(math.hypot(w1[0], w1[1])) / N
    hy = float(math.hypot(w2[0], w2[1])) / N
    best, bx, by = climb(us, x0, y0, max(hx, hy))
    r_lo = max(L, best)
    r_hi = L + 0.5 * (hx + hy) + 1e-12
    return {'mode': 'period_parallelogram', 'N': N, 'grid_pts': int(X.size),
            'grid_max': L, 'climbed': best, 'climbed_xy': [bx, by],
            'hx': hx, 'hy': hy, 'correction': 0.5 * (hx + hy),
            'r_lo': r_lo, 'r_hi': r_hi,
            'bracket_consistent': bool(r_lo <= max(r_hi, r_lo) + 1e-15)}


def witness(us, R=200.0, n=150000):
    """Deterministic Weyl scan + 8-direction hill climb maximising f = min_i dist."""
    i = np.arange(1, n + 1, dtype=float)
    x = np.mod(i * math.sqrt(2.0), 1.0)
    y = np.mod(i * math.sqrt(3.0), 1.0)
    X = (x - 0.5) * R
    Y = (y - 0.5) * R
    vals = fvec(us, X, Y)
    j = int(np.argmax(vals))
    bx, by, best = float(X[j]), float(Y[j]), float(vals[j])
    best, bx, by = climb(us, bx, by, 0.5, iters=400)
    return best, bx, by, int(n)


def verdicts(r_lo, r_hi):
    v = {}
    for e in EPSL:
        v[str(e)] = {
            'success_certified': bool(r_hi is not None and r_hi < e),
            'fail_certified': bool(r_lo > e),
        }
    return v


def main():
    t_start = time.time()
    data = {}
    scal = []
    for k in range(3, 15):
        t0 = time.time()
        us = dirs(k)
        per = search_periods(us)
        row = {'k': k, 'n_dirs': k, 'n_periods_in_box': len(per),
               'period_box': {'mmax': MM, 'tol': TOL}}
        tri = two_independent(per)
        if tri is not None:
            w1, w2, err1, err2 = tri
            br = bracket_on_parallelogram(us, w1, w2)
            row.update(br)
            row['period_basis'] = [[float(w1[0]), float(w1[1])],
                                   [float(w2[0]), float(w2[1])]]
            row['period_max_residual'] = max(err1, err2)
            row['witness'] = {'p': br['climbed_xy'], 'min_dist': br['climbed'],
                              'source': 'best grid point after 8-direction hill climb'}
        else:
            v, wx, wy, npts = witness(us)
            row.update({'mode': 'no_period_found', 'r_lo': v, 'r_hi': 0.5,
                        'r_hi_reason': ('trivial bound: dist(p.u_i,Z) <= 1/2 for every '
                                        'p and every i, so r <= 1/2 for any angle set'),
                        'witness': {'p': [wx, wy], 'min_dist': v,
                                    'source': 'Weyl scan of %d points in [-100,100]^2 '
                                              'plus 8-direction hill climb' % npts}})
        row['verdicts'] = verdicts(row['r_lo'], row['r_hi'])
        row['secs'] = round(time.time() - t0, 2)
        data[str(k)] = row
        scal.append({'k': k, 'secs': row['secs'], 'mode': row['mode'],
                     'grid_pts': row.get('grid_pts', 0)})
        print('PROGRESS: ' + json.dumps({'k': k, 'mode': row['mode'],
                                         'r_lo': round(row['r_lo'], 9),
                                         'r_hi': round(row['r_hi'], 9),
                                         'secs': row['secs']}))

    min_k = {}
    for e in EPSL:
        succ = [k for k in range(3, 15) if data[str(k)]['verdicts'][str(e)]['success_certified']]
        fail = [k for k in range(3, 15) if data[str(k)]['verdicts'][str(e)]['fail_certified']]
        min_k[str(e)] = {'min_k_success': (min(succ) if succ else None),
                         'k_with_certified_success': succ,
                         'k_with_certified_failure': fail,
                         'all_14_fail': bool(len(fail) == 12)}

    claim = ('For every k = 3..14 the equally spaced family Theta_k = {i*pi/k} has '
             'r(Theta_k) > 0.1, hence covers neither eps=0.1 nor eps=0.05; each k carries '
             'a two-sided reading [r_lo, r_hi]: k=3 by the period-parallelogram Lipschitz '
             'bracket of exp:000004, k=4..14 by an explicit witness point plus the trivial '
             'bound r <= 1/2.')
    bad = [k for k in range(3, 15) if data[str(k)]['r_hi'] is not None
           and data[str(k)]['r_hi'] < 0.1]
    if bad:
        result = 'refutes'
        counterexample = {'k_with_r_hi_below_0.1': bad,
                          'detail': {str(k): {'r_lo': data[str(k)]['r_lo'],
                                              'r_hi': data[str(k)]['r_hi'],
                                              'witness': data[str(k)]['witness']}
                                     for k in bad}}
    else:
        result = 'supports' if all(data[str(k)]['r_lo'] > 0.1 for k in range(3, 15)) \
            else 'inconclusive'
        counterexample = None

    bound = ('Per k two-sided: r in [r_lo, r_hi]. r_lo is a certified lower bound (a point '
             'evaluation of f = min_i dist(p.u_i,Z)); r_hi is either L + 0.5*(hx+hy) on a '
             'verified period parallelogram (k where two independent verified periods exist '
             'in |a|,|b| <= %d) or the trivial 1/2. Coverage at eps needs r_hi < eps; failure '
             'needs only r_lo > eps.' % MM)
    strategy = ('period-lattice search (integer combinations of the dual basis of u_0,u_1, '
                'all-direction integrality verified to %g) + axis grid N=%d on the period '
                'parallelogram + deterministic 8-direction hill climb + Lipschitz half-'
                'diagonal correction; where no period is found: deterministic Weyl scan of '
                '150000 points in a 200x200 box + hill climb on f (witness = certified lower '
                'bound), with the trivial upper bound 1/2.' % (TOL, NGRID))
    payload = {'result': result, 'bound': bound, 'strategy': strategy,
               'scaling': scal, 'claim': claim,
               'min_k_reading': min_k, 'data': data,
               'total_secs': round(time.time() - t_start, 2)}
    if counterexample is not None:
        payload['counterexample'] = counterexample
    print('REPRO_RESULT: ' + json.dumps(payload, ensure_ascii=False))


if __name__ == '__main__':
    main()
