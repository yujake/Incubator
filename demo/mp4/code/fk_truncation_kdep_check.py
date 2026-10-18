#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E-role independent cross-check of the k-dependence of standardised free
cumulants of the real-part spectral distribution of Haar-permutation
truncations. HEURISTIC / NUMERIC ONLY -- nothing here is a proof, and no
statement about W*(F_k) isomorphism follows from it.

Claim C2 (the one this script can decide):
  For n x n truncations built from k independent uniform random permutation
  matrices u_1..u_k, the standardised free cumulants of the real part
  R = (V + V^T)/2 with V = k^{-1/2} sum_i u_i follow the free-CLT / arcsine
  reference values  kappa4/kappa2^2 = -1/(2k),  kappa6/kappa2^3 = 1/k^2.

Independence from code/fk_truncation_moments.py: central moments
tau((R-m1)^j) are used, free cumulants come from a fresh noncrossing-partition
recursion (all Bell(6)=203 set partitions enumerated, NC counts 1,2,5,14,42,132
kept), and the arcsine reference is recomputed in code from
E[cos^j theta] = C(j, j/2)/2^j.

Verdict logic is decided in code (no model judgement):
  refutes      : the kappa4 and kappa6 readings at k=2 and k=8 agree within
                 4 combined SE at n = n_max (k-dependence absent) -> the
                 agreeing pair is recorded as the counterexample;
  supports     : every |measured - predicted| <= 3 SE at n = n_max AND the
                 k=2 vs k=8 difference is resolved (|diff| > 4 SE);
  inconclusive : otherwise (k-dependence present but its size at n<=128 does
                 not match the reference value).
"""
import json
import math
import time

import numpy as np

SEED = 20261019
N_LIST = [32, 64, 128]
K_LIST = [2, 4, 8]
SAMPLES = 40
ORD = 6
T0 = time.time()
CLAIM = ('在 n<=128 的 Haar 随机置换矩阵截断上（k=2,4,8），实部谱 R=(V+V^T)/2, '
         'V=k^{-1/2} sum u_i 的标准化自由累积量随 k 的依赖为 '
         'kappa4/kappa2^2 = -1/(2k)、kappa6/kappa2^3 = 1/k^2（自由 CLT / arcsine 参照）。')


def progress(**kw):
    kw['elapsed_sec'] = round(time.time() - T0, 3)
    print('PROGRESS: ' + json.dumps(kw, ensure_ascii=False, sort_keys=True), flush=True)


def all_partitions(n):
    res = []

    def rec(i, blocks):
        if i == n:
            res.append([tuple(b) for b in blocks])
            return
        for b in blocks:
            b.append(i)
            rec(i + 1, blocks)
            b.pop()
        blocks.append([i])
        rec(i + 1, blocks)
        blocks.pop()

    rec(0, [])
    return res


def is_nc(blocks):
    pr = [(x, y, i) for i, B in enumerate(blocks) for x in B for y in B if x < y]
    for a, c, i in pr:
        for b, d, j in pr:
            if i != j and a < b < c < d:
                return False
    return True


NC = {n: [p for p in all_partitions(n) if is_nc(p)] for n in range(1, ORD + 1)}


def free_cumulants(m):
    kap = {1: m[1]}
    for n in range(2, ORD + 1):
        tot = m[n]
        for pi in NC[n]:
            if len(pi) == 1:
                continue
            prod = 1.0
            for B in pi:
                prod *= kap[len(B)]
            tot -= prod
        kap[n] = tot
    return kap


def perm_matrix(n, rng):
    U = np.zeros((n, n))
    U[np.arange(n), rng.permutation(n)] = 1.0
    return U


def readings(R):
    n = R.shape[0]
    m1 = float(np.trace(R)) / n
    R0 = R - m1 * np.eye(n)
    m = [0.0] * (ORD + 1)
    M = np.eye(n)
    for j in range(1, ORD + 1):
        M = M @ R0
        m[j] = float(np.trace(M)) / n
    kap = free_cumulants(m)
    return {'kappa2': kap[2],
            'k4_over_k2sq': kap[4] / kap[2] ** 2,
            'k6_over_k2cu': kap[6] / kap[2] ** 3}


TAGS = ['kappa2', 'k4_over_k2sq', 'k6_over_k2cu']


def main():
    semicircle = [0.0, 0.0, 1.0, 0.0, 2.0, 0.0, 5.0]
    sc_k = free_cumulants(semicircle)
    arc = [0.0] * (ORD + 1)
    for j in range(1, ORD + 1):
        arc[j] = (math.comb(j, j // 2) / 2.0 ** j) if j % 2 == 0 else 0.0
    arc_k = free_cumulants(arc)
    checks = {
        'nc_counts_1_to_6': [len(NC[j]) for j in range(1, ORD + 1)],
        'semicircle_kappa': {str(j): sc_k[j] for j in range(1, ORD + 1)},
        'arcsine_moments': {str(j): arc[j] for j in range(1, ORD + 1)},
        'arcsine_kappa': {str(j): arc_k[j] for j in range(1, ORD + 1)},
        'arcsine_k4_over_k2sq_per_k': {str(k): (arc_k[4] / arc_k[2] ** 2) / k for k in K_LIST},
        'arcsine_k6_over_k2cu_per_k': {str(k): (arc_k[6] / arc_k[2] ** 3) / (k * k) for k in K_LIST},
    }
    progress(stage='selfcheck', **checks)

    pred = {k: {'k4_over_k2sq': (arc_k[4] / arc_k[2] ** 2) / k,
                'k6_over_k2cu': (arc_k[6] / arc_k[2] ** 3) / (k * k)} for k in K_LIST}

    res = {}
    rows = []
    scaling = []
    for n in N_LIST:
        for k in K_LIST:
            rng = np.random.default_rng(SEED + 1000 * n + 7 * k)
            t0 = time.time()
            acc = {tag: [] for tag in TAGS}
            for _ in range(SAMPLES):
                V = np.zeros((n, n))
                for _i in range(k):
                    V += perm_matrix(n, rng)
                V /= math.sqrt(k)
                R = (V + V.T) / 2.0
                rd = readings(R)
                for tag in TAGS:
                    acc[tag].append(rd[tag])
            res[(n, k)] = {}
            for tag in TAGS:
                a = np.asarray(acc[tag], dtype=float)
                res[(n, k)][tag] = (float(a.mean()), float(a.std(ddof=1) / math.sqrt(len(a))))
            dt = round(time.time() - t0, 2)
            scaling.append({'n': n, 'k': k, 'samples': SAMPLES, 'seconds': dt,
                            'matrix_entries_per_sample': 2 * n * n, 'cumulant_order': ORD})
            rows.append({'n': n, 'k': k, 'samples': SAMPLES,
                         'kappa2': res[(n, k)]['kappa2'],
                         'k4_over_k2sq': res[(n, k)]['k4_over_k2sq'],
                         'k6_over_k2cu': res[(n, k)]['k6_over_k2cu'],
                         'predicted_k4_over_k2sq': pred[k]['k4_over_k2sq'],
                         'predicted_k6_over_k2cu': pred[k]['k6_over_k2cu'],
                         'seconds': dt})
            progress(stage='routeB', n=n, k=k, seconds=dt,
                     k4_over_k2sq=res[(n, k)]['k4_over_k2sq'],
                     k4_pred=pred[k]['k4_over_k2sq'],
                     k6_over_k2cu=res[(n, k)]['k6_over_k2cu'],
                     k6_pred=pred[k]['k6_over_k2cu'])

    nmax = N_LIST[-1]
    decisive = {}
    for k in K_LIST:
        for tag in ('k4_over_k2sq', 'k6_over_k2cu'):
            v, s = res[(nmax, k)][tag]
            p = pred[k][tag]
            decisive['%s|k=%d' % (tag, k)] = {
                'measured': v, 'se': s, 'predicted': p,
                'z': (v - p) / max(s, 1e-12),
                'ci95': [v - 2.0 * s, v + 2.0 * s],
            }

    d4 = res[(nmax, 2)]['k4_over_k2sq'][0] - res[(nmax, 8)]['k4_over_k2sq'][0]
    se4 = math.hypot(res[(nmax, 2)]['k4_over_k2sq'][1], res[(nmax, 8)]['k4_over_k2sq'][1])
    d6 = res[(nmax, 2)]['k6_over_k2cu'][0] - res[(nmax, 8)]['k6_over_k2cu'][0]
    se6 = math.hypot(res[(nmax, 2)]['k6_over_k2cu'][1], res[(nmax, 8)]['k6_over_k2cu'][1])
    resolved = bool((abs(d4) > 4.0 * se4) or (abs(d6) > 4.0 * se6))
    maxz = max(abs(d['z']) for d in decisive.values())

    counter = None
    if (abs(d4) <= 4.0 * se4) and (abs(d6) <= 4.0 * se6):
        result = 'refutes'
        counter = {'n': nmax, 'samples': SAMPLES, 'k_pair': [2, 8],
                   'reading_k4_over_k2sq': [res[(nmax, 2)]['k4_over_k2sq'][0],
                                            res[(nmax, 8)]['k4_over_k2sq'][0]],
                   'reading_k6_over_k2cu': [res[(nmax, 2)]['k6_over_k2cu'][0],
                                            res[(nmax, 8)]['k6_over_k2cu'][0]],
                   'se': [se4, se6],
                   'note': 'k=2 与 k=8 的标准化自由累积量在 4 倍合并标准误内一致 => 该读数不随 k 变化'}
    elif maxz <= 3.0 and resolved:
        result = 'supports'
    else:
        result = 'inconclusive'

    payload = {
        'result': result,
        'claim': CLAIM,
        'method_note': 'heuristic/numeric only; no proof of anything about W*(F_k)',
        'bound': {'n_set': N_LIST, 'n_max': nmax, 'k_set': K_LIST,
                  'k_inf': 'not realised in finite dimension: no k=inf row here; the analytic k->inf limit of the -1/(2k), 1/k^2 laws is the reference',
                  'max_moment_order': ORD, 'samples': SAMPLES, 'seed': SEED,
                  'se_definition': 'std(ddof=1)/sqrt(samples) over per-sample readings'},
        'strategy': ('Monte Carlo over Haar random permutation matrices; central moments '
                     'tau((R-m1)^j) by 6 repeated matrix products; free cumulants from a '
                     'noncrossing-partition recursion (Bell(6)=203 enumerated); arcsine '
                     'reference recomputed in code from E[cos^j theta]; verdict by |z| '
                     'against 3 SE and k=2 vs k=8 separation against 4 combined SE'),
        'scaling': scaling,
        'data': {'rows': rows, 'decisive_at_nmax': decisive,
                 'k2_vs_k8': {'diff_k4_over_k2sq': d4, 'se_k4': se4,
                              'diff_k6_over_k2cu': d6, 'se_k6': se6,
                              'resolved': resolved},
                 'max_abs_z': maxz,
                 'selfcheck': checks,
                 'notes': [
                     'k=inf is not realised in finite dimension: no row claims it.',
                     'kappa_n(R)=k^{1-n/2} kappa_n(x) with x=cos(theta) arcsine on [-1,1] gives the -1/(2k) and 1/k^2 laws; that is a normalisation artefact of the sum, not an isomorphism invariant.',
                     'Nothing here bears on W*(F_k) =~ W*(F_m): moment data of one chosen generating tuple is not an invariant.',
                 ]},
    }
    if counter is not None:
        payload['counterexample'] = counter
    print('REPRO_RESULT: ' + json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('REPRO_RESULT: ' + json.dumps(
            {'result': 'inconclusive', 'error': '%s: %s' % (type(exc).__name__, exc),
             'bound': {'n_set': N_LIST, 'k_set': K_LIST}}, ensure_ascii=False), flush=True)
