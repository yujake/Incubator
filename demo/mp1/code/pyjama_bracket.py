'''pyjama_bracket.py -- two-sided (Lipschitz-certified) brackets for

    r(Theta) = sup_{p in R^2} min_i dist(p . u_i, Z),   dist(t,Z) = |t - round(t)|.

Every number printed here is computed by this file; nothing is judged by a model.

Facts used (both elementary):
 (i)  f(p) = min_i dist(p.u_i,Z) is 1-Lipschitz: |f(p)-f(q)| <= |p-q|
      (each g_i(p)=dist(p.u_i,Z) is 1-Lipschitz and |min g_i(p)-min g_i(q)| <= max|g_i(p)-g_i(q)|).
 (ii) f is periodic under Lambda = {p : p.u_i in Z for all i}; for any sublattice L' of
      Lambda a fundamental domain of L' is a full search domain.
Therefore, on such a domain covered by an axis grid of meshes (hx,hy),
      L = max over grid samples and locally refined points of f
      U = L + 0.5*sqrt(hx*hx + hy*hy)
satisfies   L <= r(Theta) <= U.   (float noise ~1e-15, far below the correction term.)

Cases (deterministic):
 A  6 lines, normals = primitive integer vectors of length 5: (5,0),(0,5),(3,4),(4,3),(3,-4),(4,-3).
    5Z^2 is a sublattice of Lambda, domain [0,5)^2.  Exact rational certificate:
    p=(5/2,5/2) gives dist = 1/2 for every i (Fraction arithmetic) => r = 1/2 exactly.
 B  equilateral 3 normals (1,0),(-1/2,sqrt3/2),(-1/2,-sqrt3/2).
    Lambda = {(x,y): x in Z, sqrt3*y in Z}, domain [0,1) x [0,1/sqrt3).
 C  12 lines, normals = primitive integer vectors of length 5 (6 of them) and of length 13:
    (13,0),(0,13),(5,12),(12,5),(5,-12),(12,-5).  65Z^2 subset Lambda, domain [0,65)^2.

No argv needed: one run does A, B, C and prints one REPRO_RESULT line.
'''

import json
import math
import time
from fractions import Fraction

import numpy as np

EPS_LIST = [0.1, 0.05]


def fmin(us, x, y):
    m = 1.0
    for ux, uy in us:
        t = x * ux + y * uy
        d = abs(t - math.floor(t + 0.5))
        if d < m:
            m = d
    return m


def refine(us, x, y, h, iters=80):
    best = [fmin(us, x, y), x, y]
    for _ in range(iters):
        moved = False
        for dx, dy in ((h, 0.0), (-h, 0.0), (0.0, h), (0.0, -h),
                       (h, h), (h, -h), (-h, h), (-h, -h)):
            v = fmin(us, best[1] + dx, best[2] + dy)
            if v > best[0]:
                best = [v, best[1] + dx, best[2] + dy]
                moved = True
        if not moved:
            h *= 0.5
            if h < 1e-13:
                break
    return best


def grid_max(us, W, H, hx, hy, x0=0.0, y0=0.0, chunk=64):
    nx = int(round(W / hx))
    ny = int(round(H / hy))
    xs = x0 + np.arange(nx) * hx
    ys = y0 + np.arange(ny) * hy
    best_v = -1.0
    best_pt = (0.0, 0.0)
    npts = 0
    for i0 in range(0, nx, chunk):
        X = xs[i0:i0 + chunk][:, None]
        acc = None
        for ux, uy in us:
            t = X * ux + ys[None, :] * uy
            d = np.abs(t - np.round(t))
            acc = d if acc is None else np.minimum(acc, d)
        j = int(np.argmax(acc))
        ii, jj = divmod(j, ny)
        v = float(acc[ii, jj])
        npts += int(acc.size)
        if v > best_v:
            best_v = v
            best_pt = (float(xs[i0 + ii]), float(ys[jj]))
    return best_v, best_pt, npts, nx, ny


def unit(a, b):
    n = math.isqrt(a * a + b * b)
    return (a / n, b / n), n


def exact_certificate_A():
    vs = [(5, 0), (0, 5), (3, 4), (4, 3), (3, -4), (4, -3)]
    x = Fraction(5, 2)
    y = Fraction(5, 2)
    ds = []
    for a, b in vs:
        n = math.isqrt(a * a + b * b)
        t = (a * x + b * y) / n
        fl = t.numerator // t.denominator
        r = t - fl
        if r > Fraction(1, 2):
            r = 1 - r
        ds.append(r)
    return all(r == Fraction(1, 2) for r in ds), [str(r) for r in ds], str(x), str(y)


def bracket(us, W, H, hx, hy, tag):
    t0 = time.time()
    g, pt, n, nx, ny = grid_max(us, W, H, hx, hy)
    rf = refine(us, pt[0], pt[1], hx)
    L = max(g, rf[0])
    U = L + 0.5 * math.sqrt(hx * hx + hy * hy) + 1e-12
    sec = round(time.time() - t0, 3)
    row = {'case': tag, 'grid_max': g, 'refined': rf[0], 'refined_xy': [rf[1], rf[2]],
           'grid_xy': [pt[0], pt[1]], 'grid_shape': [nx, ny], 'points': n, 'sec': sec,
           'L': L, 'U': U,
           'L_gt_eps': {str(e): bool(L > e) for e in EPS_LIST},
           'U_le_eps': {str(e): bool(U <= e) for e in EPS_LIST}}
    print('PROGRESS: ' + json.dumps({'case': tag, 'L': round(L, 9), 'U': round(U, 9),
                                     'sec': sec, 'points': n}))
    return row, {'case': tag, 'points': n, 'sec': sec}


def main():
    t_start = time.time()
    scal = []
    data = {}

    # ---- case A: exact r = 1/2 -------------------------------------------
    okA, dsA, xA, yA = exact_certificate_A()
    usA = [unit(a, b)[0] for a, b in [(5, 0), (0, 5), (3, 4), (4, 3), (3, -4), (4, -3)]]
    rowA, scA = bracket(usA, 5.0, 5.0, 0.01, 0.01, 'A_6lines_len5')
    rowA['exact_ok'] = okA
    rowA['exact_dists'] = dsA
    rowA['exact_p_xy'] = [xA, yA]
    rowA['exact_r'] = '1/2' if okA else 'not verified'
    data['A'] = rowA
    scal.append(scA)

    # ---- case B: equilateral 3 lines -------------------------------------
    s3 = math.sqrt(3.0)
    usB = [(1.0, 0.0), (-0.5, s3 / 2.0), (-0.5, -s3 / 2.0)]
    hxB = 1.0 / 2000.0
    HB = 1.0 / s3
    hyB = HB / 1000.0
    rowB, scB = bracket(usB, 1.0, HB, hxB, hyB, 'B_equilateral3')
    data['B'] = rowB
    scal.append(scB)

    # ---- case C: 12 lines, lengths 5 and 13 ------------------------------
    vsC = [(5, 0), (0, 5), (3, 4), (4, 3), (3, -4), (4, -3),
           (13, 0), (0, 13), (5, 12), (12, 5), (5, -12), (12, -5)]
    usC = [unit(a, b)[0] for a, b in vsC]
    rowC, scC = bracket(usC, 65.0, 65.0, 0.05, 0.05, 'C_12lines_len5_13')
    data['C'] = rowC
    scal.append(scC)

    verdict = {}
    for key in ('B', 'C'):
        r = data[key]
        if r['L'] > max(EPS_LIST):
            verdict[key] = 'certified: r > 0.1 (so this set cannot serve eps=0.1 or 0.05)'
        elif r['U'] <= min(EPS_LIST):
            verdict[key] = 'certified: r <= 0.05 (serves both eps)'
        elif r['U'] <= max(EPS_LIST):
            verdict[key] = 'certified: r <= 0.1 (serves eps=0.1, undecided for 0.05)'
        else:
            verdict[key] = 'undetermined by this bracket'
    data['verdict'] = verdict

    scal.append({'case': 'total', 'sec': round(time.time() - t_start, 3)})
    bound = ('two-sided and certified: on a fundamental domain of a sublattice of the period '
             'lattice, L = max of f over an axis grid + local hill climb is a LOWER bound on r, '
             'and U = L + 0.5*sqrt(hx^2+hy^2) is an UPPER bound (1-Lipschitz). '
             'A: 6Z? no: 6 lines, normals of length 5, domain [0,5)^2, mesh 0.01; r = 1/2 exactly '
             'at p=(5/2,5/2) (exact rational arithmetic). '
             'B: equilateral 3 lines, domain [0,1)x[0,1/sqrt3), meshes 5e-4 and 5.8e-4. '
             'C: 12 lines (normals of length 5 and 13), domain [0,65)^2 (65Z^2 subset Lambda), mesh 0.05 '
             '=> correction 0.03536.')
    strategy = ('exact rational certificate (Fraction) + fundamental-domain axis grid (numpy) '
                '+ deterministic 8-direction hill climb with step halving + Lipschitz upper bound')
    result = 'supports' if okA else 'inconclusive'
    print('REPRO_RESULT: ' + json.dumps({'result': result, 'bound': bound,
                                         'strategy': strategy, 'scaling': scal, 'data': data},
                                        ensure_ascii=False))


if __name__ == '__main__':
    main()
