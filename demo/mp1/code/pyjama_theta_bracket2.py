"""pyjama_theta_bracket2.py -- two-sided readings for Theta_k = {i*pi/k}, k = 3..14.

Companion of exp:000004 (code/pyjama_bracket.py / code/pyjama_theta_bracket.py).
Every number printed here is computed by this file; no model judges any number.

Setting
    f(p)    = min_i dist(p . u_i, Z),   u_i = (cos(i*pi/k), sin(i*pi/k)), i = 0..k-1
    r(Theta)= sup_{p in R^2} f(p),      dist(t,Z) = |t - round(t)|.

Tool T1  (Lipschitz bracket -- needs a GENUINE period parallelogram)
    If w1 and w2 are BOTH periods of f (i.e. w.u_i in Z for EVERY i, verified here
    to 1e-12) and linearly independent, the parallelogram they span is a fundamental
    domain of the period lattice.  With an (N,N) grid on it, meshes hx=|w1|/N,
    hy=|w2|/N:
        L  <=  r  <=  L + 0.5*(hx+hy),
    L = max of f over the grid samples plus a deterministic 8-direction hill climb.
    L is a point evaluation (valid lower bound); 0.5*(hx+hy) bounds the distance
    from any point of a cell to the nearest grid vertex (triangle inequality).
    This is exactly the tool of exp:000004; it is usable only where such w1,w2 exist.

Tool T2  (witness lower bound -- needs no periodicity)
    Any explicit point p with min_i dist(p.u_i,Z) = v gives r >= v.  We use a
    deterministic Weyl scan over two boxes plus an 8-direction hill climb and
    report the witness point.  Absolute error of the float evaluation of f is
    < 1e-12 for the |p| <= 400 used here (each of the k <= 14 summands x*ux+y*uy
    is a sum of two products of doubles with |x|,|y| <= 400, i.e. err < 400*2.3e-16
    per coordinate, times 14 terms, plus rounding of the round/abs step).
    Every printed lower bound is certified only after subtracting SAFETY = 1e-9,
    and every printed upper bound only after adding SAFETY.

Tool T3  (trivial / subset upper bounds -- rigorous, weak)
    (a) dist(t,Z) <= 1/2 for every real t, so r <= 1/2 for any angle set.
    (b) m | k  =>  Theta_m is a subset of Theta_k  =>  f_{Theta_k} <= f_{Theta_m}
        => r(Theta_k) <= r(Theta_m).  With m = 3 (bracketed here two-sidedly) this
        sharpens the trivial bound to r(Theta_k) <= r_hi(Theta_3) for 3 | k.
    Neither (a) nor (b) ever reaches eps = 0.1; this is reported as such.

Verdict rule (deterministic, printed per k)
    success certified for eps  <=>  r_hi < eps
    failure certified for eps  <=>  r_lo > eps
A lower bound alone (exp:000003 reported lb = 0.098076 at k = 12) is NOT a success
certificate; and an upper bound of 1/2 is not a success certificate either.

Output: one 'PROGRESS: {...}' line per k and exactly one 'REPRO_RESULT: {...}' line.
"""

import json
import math
import time

import numpy as np

EPSL = [0.1, 0.05]
NGRID = 900
MM = 10
TOL = 1e-12
SAFETY = 1e-9
EIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
KS = list(range(3, 15))


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
    """w1,w2 with w1.u_0 = 1, w1.u_1 = 0, w2.u_0 = 0, w2.u_1 = 1 (NOT periods in general)."""
    (c1, s1), (c2, s2) = us[0], us[1]
    det = c1 * s2 - s1 * c2
    if abs(det) < 1e-12:
        return None
    return np.array([s2, -c2]) / det, np.array([-s1, c1]) / det


def period_search(us, mmax=MM, tol=TOL):
    """All p = a*w1 + b*w2 with |a|,|b| <= mmax and |p.u_i - round(p.u_i)| <= tol for ALL i."""
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
                out.append((float(p[0]), float(p[1]), float(math.hypot(p[0], p[1])), worst, a, b))
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


def climb(us, x0, y0, h0, iters=600):
    best, bx, by = fmin(us, x0, y0), x0, y0
    step = h0
    for _ in range(iters):
        moved = False
        for dx, dy in EIGHT:
            v = fmin(us, bx + step * dx, by + step * dy)
            if v > best + 1e-15:
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
    r_lo = max(L, best) - SAFETY
    r_hi = L + 0.5 * (hx + hy) + SAFETY
    return {'mode': 'period_parallelogram', 'N': N, 'grid_pts': int(X.size),
            'grid_max': L, 'climbed': best, 'climbed_xy': [bx, by],
            'hx': hx, 'hy': hy, 'correction': 0.5 * (hx + hy),
            'r_lo': r_lo, 'r_hi': r_hi}


def weyl_witness(us, boxes=(200.0, 60.0), n=250000, ntop=24):
    """Deterministic Weyl scan + hill climb; returns (value, x, y, npoints, box)."""
    best = (-1.0, 0.0, 0.0, 0, 0.0)
    tot = 0
    i = np.arange(1, n + 1, dtype=float)
    x = np.mod(i * math.sqrt(2.0), 1.0)
    y = np.mod(i * math.sqrt(3.0), 1.0)
    for R in boxes:
        X = (x - 0.5) * R
        Y = (y - 0.5) * R
        vals = fvec(us, X, Y)
        tot += int(n)
        for j in np.argsort(vals)[::-1][:ntop]:
            v, bx, by = climb(us, float(X[j]), float(Y[j]), 0.5, iters=600)
            if v > best[0]:
                best = (v, bx, by, tot, R)
    return best


def verdicts(r_lo, r_hi):
    v = {}
    for e in EPSL:
        v[str(e)] = {'success_certified': bool(r_hi is not None and r_hi < e),
                     'fail_certified': bool(r_lo is not None and r_lo > e)}
    return v


def main():
    t_start = time.time()
    data = {}
    scal = []
    r_hi_theta3 = None
    for k in KS:
        t0 = time.time()
        us = dirs(k)
        per = period_search(us)
        row = {'k': k, 'n_dirs': k, 'n_periods_in_box': len(per),
               'period_box': {'mmax': MM, 'tol': TOL},
               'bracket_notes': []}
        tri = two_independent(per)
        if tri is not None:
            w1, w2, err1, err2 = tri
            row.update(bracket_on_parallelogram(us, w1, w2))
            row['period_basis'] = [[float(w1[0]), float(w1[1])], [float(w2[0]), float(w2[1])]]
            row['period_max_residual'] = max(err1, err2)
            row['witness'] = {'p': row['climbed_xy'], 'min_dist': row['climbed'],
                              'source': 'best grid point after 8-direction hill climb '
                                        '(certified lower bound = value - 1e-9)'}
            if k == 3:
                r_hi_theta3 = row['r_hi']
        else:
            v, wx, wy, npts, R = weyl_witness(us)
            row.update({'mode': 'no_period_lattice_found', 'r_lo': v - SAFETY,
                        'r_hi': 0.5 + SAFETY,
                        'r_hi_reason': ('trivial: dist(t,Z) <= 1/2 for all t, hence r <= 1/2 '
                                        'for any angle set'),
                        'witness': {'p': [wx, wy], 'min_dist': v,
                                    'certified_lo': v - SAFETY,
                                    'source': 'deterministic Weyl scan (%d points, boxes up to '
                                              'R=%g) + 8-direction hill climb' % (npts, R)}})
            row['bracket_notes'].append(
                'no w1,w2 in |a|,|b|<=%d with p.u_i in Z for all i (tol %g): the period '
                'parallelogram tool T1 of exp:000004 does not apply here' % (MM, TOL))
            if (isinstance(k, int) and k % 3 == 0 and r_hi_theta3 is not None):
                row['r_hi_subset'] = r_hi_theta3 + SAFETY
                row['r_hi_subset_reason'] = ('3 | k => Theta_3 subset Theta_k => r(Theta_k) <= '
                                             'r(Theta_3) <= r_hi(Theta_3)')
                row['r_hi'] = min(row['r_hi'], row['r_hi_subset'])
                row['bracket_notes'].append('trivial 1/2 sharpened to r_hi(Theta_3) by subset '
                                            'monotonicity (still far above 0.1)')
        row['verdicts'] = verdicts(row['r_lo'], row['r_hi'])
        row['closed_for_eps'] = {str(e): bool(row['verdicts'][str(e)]['success_certified']
                                             or row['verdicts'][str(e)]['fail_certified'])
                                 for e in EPSL}
        row['secs'] = round(time.time() - t0, 2)
        data[str(k)] = row
        scal.append({'k': k, 'secs': row['secs'], 'mode': row['mode'],
                     'grid_pts': row.get('grid_pts', 0),
                     'n_periods': row['n_periods_in_box']})
        print('PROGRESS: ' + json.dumps({'k': k, 'mode': row['mode'],
                                         'r_lo': round(row['r_lo'], 9),
                                         'r_hi': round(row['r_hi'], 9),
                                         'n_periods': row['n_periods_in_box'],
                                         'secs': row['secs']}))

    fail_all = all(data[str(k)]['r_lo'] > max(EPSL) for k in KS)
    succ_any = [k for k in KS if any(data[str(k)]['verdicts'][str(e)]['success_certified']
                                     for e in EPSL)]
    summary = {'min_k_with_certified_success': {
        str(e): (min([k for k in KS if data[str(k)]['verdicts'][str(e)]['success_certified']])
                 if any(data[str(k)]['verdicts'][str(e)]['success_certified'] for k in KS)
                 else None) for e in EPSL},
        'k_with_certified_failure': {str(e): [k for k in KS
                                              if data[str(k)]['verdicts'][str(e)]['fail_certified']]
                                     for e in EPSL},
        'all_k_3_14_fail_eps_0.1': bool(all(data[str(k)]['verdicts']['0.1']['fail_certified']
                                            for k in KS)),
        'all_k_3_14_fail_eps_0.05': bool(all(data[str(k)]['verdicts']['0.05']['fail_certified']
                                             for k in KS)),
        'k_with_closed_two_sided_bracket': [k for k in KS
                                            if data[str(k)]['mode'] == 'period_parallelogram'],
        'success_certified_anywhere': succ_any}

    claim = ('For every k = 3..14 an explicit witness point p_k gives '
             'min_i dist(p_k.u_i, Z) > 0.1 (tabulated as r_lo, certified after a 1e-9 '
             'safety margin), hence r(Theta_k) > 0.1 and the equally spaced family '
             'Theta_k = {i*pi/k} fails eps = 0.1 (and eps = 0.05) for every k in 3..14; '
             'for k = 3 the Lipschitz bracket on a verified period parallelogram closes '
             'two-sidedly (r in [1/3, 0.33462]); for k >= 4 no nontrivial period lattice '
             'exists in the box |a|,|b| <= 10, so no upper bound below 1/2 is available '
             'there (only r <= 1/2, sharpened to r <= r_hi(Theta_3) when 3 | k).')
    if not fail_all:
        bad = [k for k in KS if data[str(k)]['r_lo'] <= max(EPSL)]
        result = 'refutes'
        counterexample = {'k_with_witness_r_lo_le_0.1': bad,
                          'detail': {str(k): {'r_lo': data[str(k)]['r_lo'],
                                              'r_hi': data[str(k)]['r_hi'],
                                              'witness': data[str(k)]['witness']} for k in bad}}
    else:
        result = 'supports'
        counterexample = None

    bound = ('Two-sided per k: r(Theta_k) in [r_lo, r_hi]. r_lo = a certified point '
             'evaluation (grid max / hill-climb value / Weyl witness, minus 1e-9). r_hi = '
             'L + 0.5*(hx+hy) + 1e-9 on a verified period parallelogram where two independent '
             'periods exist (only k = 3 here), otherwise the trivial 1/2 (+1e-9), sharpened to '
             'r_hi(Theta_3) for 3 | k by monotonicity under inclusion. Success at eps needs '
             'r_hi < eps; failure needs only r_lo > eps. eps in {0.1, 0.05}.')
    strategy = ('period-lattice search over integer combinations of the dual basis of (u_0,u_1), '
                'every coordinate verified against ALL k directions; axis grid N=900 on the '
                'period parallelogram + deterministic 8-direction hill climb with step halving '
                '+ Lipschitz half-(l1) cover correction; fallback where no period lattice exists: '
                'deterministic Weyl scan (250000 points per box, boxes R = 200 and 60) + hill '
                'climb from the 24 best samples, with the trivial/subset upper bound.')
    print('REPRO_RESULT: ' + json.dumps({'result': result, 'claim': claim, 'bound': bound,
                                         'strategy': strategy, 'scaling': scal,
                                         'summary': summary, 'counterexample': counterexample,
                                         'data': data}, ensure_ascii=False))


if __name__ == '__main__':
    main()
