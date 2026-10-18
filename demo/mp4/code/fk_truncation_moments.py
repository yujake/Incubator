#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E-role finite-dimensional truncation experiment (heuristic only; NOT a proof).

Falsifiable question:
  On n x n random-matrix truncations of generators of W*(F_k), do the first
  MAX_ORDER moments and free cumulants of the REAL-PART spectral distribution
  agree for k = 2, 3, 4 and k = inf (=8 as a finite stand-in, plus the analytic
  free-CLT limit)?  If they agree => moment invariants of the finite truncation
  cannot separate k.

Two generator models:
  route A ('GUE / free semicircular tuple'): k independent GUE-type self-adjoint
      matrices, per-sample normalised so that tau(g_i^2)=1; W = (1/sqrt k) sum g_i;
      W is self-adjoint so 'real part' = W.
  route B ('Haar random permutation unitaries'): k independent uniform random
      permutation matrices u_i; V = (1/sqrt k) sum u_i; R = (V + V^T)/2 is the
      real part, and its spectral distribution is the reading (NO renormalisation).

Readings per (route, n, k):
  m_1..m_6 = tau(R^j) = tr(R^j)/n ; free cumulants kappa_1..kappa_6 from the
  moments by the noncrossing-partition recursion (deterministic; self-checked on
  the semicircle); standardised kappa_2, kappa_4/kappa_2^2, kappa_6/kappa_2^3;
  Monte-Carlo standard error = std/sqrt(S) over the per-sample readings.

d1-type finite-dimensional dimension-defect reading:
  Delta_n(L) := 1 - rank_R{ words in the u_i^{+-1} of length <= L } / n^2 ,
  rank over R of the n^2-dimensional vectorisation, words capped at
  DEFECT_WORD_CAP per length (so rank is a LOWER bound and Delta an UPPER bound).
  It measures how much of M_n the first L word layers fail to span; it is a crude
  finite-n dimension-flavour reading, NOT an isomorphism invariant -- k-dependence
  here says nothing about W*(F_k) ~ W*(F_m).

Verdict logic is decided in code (no model judgement):
  distinguishable = |standardised cumulant diff| > 4 * combined SE  AND
                    |diff| > 1% of the larger |value|;
  result = 'refutes' if route B is distinguishable (the agreement claim fails),
           'supports' if neither route is distinguishable and the SE of the
           k-decisive reading is < 0.05 (small enough to see a 1/k-size effect),
           'inconclusive' otherwise.
"""
import json
import sys
import time

import numpy as np

SEED = 20261018
MAX_ORDER = 6
N_LIST = [8, 16, 32, 64]
K_LIST = [2, 3, 4, 8]
SAMPLES_BY_N = {8: 40, 16: 30, 32: 20, 64: 12}
DEFECT_N = [8, 16]
DEFECT_K = [2, 3, 4, 8]
DEFECT_SAMPLES = 3
DEFECT_MAX_LEN = 6
DEFECT_WORD_CAP = 200
RANK_TOL = 1e-8

CLAIM = ("在 n<=64 的有限维随机矩阵截断上（route A: GUE 自由半圆元组；"
         "route B: Haar 随机置换矩阵求和的实部谱），k=2,3,4,8(=inf 替身) 的前 6 阶矩"
         "与自由累积量一致 —— 若一致则矩不变量的有限截断不能区分 k。")

T0 = time.time()


def progress(**kw):
    kw['elapsed_sec'] = round(time.time() - T0, 3)
    print('PROGRESS: ' + json.dumps(kw, ensure_ascii=False, sort_keys=True), flush=True)


# ---------------- noncrossing partitions / free cumulants ----------------
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


def is_noncrossing(blocks):
    pos = {}
    for bi, b in enumerate(blocks):
        for x in b:
            pos[x] = bi
    n = len(pos)
    for a in range(n):
        for b in range(a + 1, n):
            for c in range(b + 1, n):
                for d in range(c + 1, n):
                    if pos[a] == pos[c] and pos[b] == pos[d] and pos[a] != pos[b]:
                        return False
    return True


def nc_partitions(n):
    return [p for p in all_partitions(n) if is_noncrossing(p)]


NC = {n: nc_partitions(n) for n in range(1, MAX_ORDER + 1)}


def cumulants_from_moments(mom, max_order=MAX_ORDER):
    """mom[n] = sum over NC partitions pi of prod_{B in pi} kappa_|B| ; invert."""
    kap = [0.0] * (max_order + 1)
    kap[1] = mom[1]
    for n in range(2, max_order + 1):
        s = 0.0
        for p in NC[n]:
            if len(p) == 1:
                continue
            prod = 1.0
            for blk in p:
                prod *= kap[len(blk)]
            s += prod
        kap[n] = mom[n] - s
    return kap


def selfcheck():
    """Deterministic checks: NC counts, Bell counts, semicircle cumulants."""
    mom = [1.0, 0.0, 1.0, 0.0, 2.0, 0.0, 5.0]  # semicircle var 1
    kap = cumulants_from_moments(mom, MAX_ORDER)
    ok = (abs(kap[2] - 1.0) < 1e-12 and abs(kap[3]) < 1e-12 and abs(kap[4]) < 1e-12
          and abs(kap[5]) < 1e-12 and abs(kap[6]) < 1e-12)
    return {
        'semicircle_cumulants_ok': bool(ok),
        'semicircle_cumulants': [round(k, 12) for k in kap[1:]],
        'nc_partition_counts_1_to_6': [len(NC[n]) for n in range(1, MAX_ORDER + 1)],
        'bell_counts_1_to_6': [len(all_partitions(n)) for n in range(1, MAX_ORDER + 1)],
    }


# ---------------- spectral readings ----------------
def spectral_readings(R):
    n = R.shape[0]
    M = np.eye(n)
    mom = [0.0] * (MAX_ORDER + 1)
    mom[0] = 1.0
    for j in range(1, MAX_ORDER + 1):
        M = M @ R
        mom[j] = float(np.trace(M)) / n
    kap = cumulants_from_moments(mom, MAX_ORDER)
    return mom, kap


def permutation_matrix(n, rng):
    p = rng.permutation(n)
    M = np.zeros((n, n))
    M[np.arange(n), p] = 1.0
    return M


def route_gue(n, k, samples, rng):
    mom_l, kap_l = [], []
    for _ in range(samples):
        W = np.zeros((n, n))
        for _i in range(k):
            G = rng.normal(0.0, 1.0 / np.sqrt(n), size=(n, n))
            g = (G + G.T) / np.sqrt(2.0)
            tr2 = float(np.trace(g @ g)) / n
            if tr2 <= 0:
                raise RuntimeError('degenerate GUE normalisation: tau(g^2)<=0')
            W = W + g / np.sqrt(tr2)   # force tau(g^2)=1 per sample
        W = W / np.sqrt(k)
        mom, kap = spectral_readings(W)
        mom_l.append(mom)
        kap_l.append(kap)
    return mom_l, kap_l


def route_perm(n, k, samples, rng):
    mom_l, kap_l = [], []
    for _ in range(samples):
        V = np.zeros((n, n))
        for _i in range(k):
            V = V + permutation_matrix(n, rng)
        V = V / np.sqrt(k)
        R = (V + V.T) / 2.0   # real part of the normalised sum of unitaries
        mom, kap = spectral_readings(R)
        mom_l.append(mom)
        kap_l.append(kap)
    return mom_l, kap_l


def summarize(mom_l, kap_l):
    def agg(vals):
        a = np.asarray(vals, dtype=float)
        m = float(a.mean())
        se = float(a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 else 0.0
        return m, se

    out = {}
    for j in range(1, MAX_ORDER + 1):
        out['m%d' % j] = agg([m[j] for m in mom_l])
    for j in range(1, MAX_ORDER + 1):
        out['k%d' % j] = agg([x[j] for x in kap_l])
    out['k4_over_k2sq'] = agg([x[4] / x[2] ** 2 for x in kap_l])
    out['k6_over_k2cu'] = agg([x[6] / x[2] ** 3 for x in kap_l])
    return out


# ---------------- d1-type dimension-defect reading ----------------
def word_span_defect(n, k, rng, samples, max_len, cap):
    per_L = {L: [] for L in range(1, max_len + 1)}
    for _ in range(samples):
        gens = [permutation_matrix(n, rng) for _ in range(k)]
        letters = []
        for g in gens:
            letters.append(g)
            letters.append(g.T)
        levels = {0: [np.eye(n)]}
        for L in range(1, max_len + 1):
            cur = []
            stop = False
            for W in levels[L - 1]:
                for A in letters:
                    cur.append(A @ W)
                    if len(cur) >= cap:
                        stop = True
                        break
                if stop:
                    break
            levels[L] = cur
        for L in range(1, max_len + 1):
            words = [M for L2 in range(0, L + 1) for M in levels[L2]]
            mat = np.stack([M.reshape(-1) for M in words], axis=1)
            rank = int(np.linalg.matrix_rank(mat, tol=RANK_TOL))
            per_L[L].append(1.0 - rank / float(n * n))
    return {L: float(np.mean(v)) for L, v in per_L.items()}


# ---------------- main ----------------
def main():
    rng = np.random.default_rng(SEED)
    checks = selfcheck()
    progress(stage='selfcheck', ok=checks['semicircle_cumulants_ok'],
             nc_counts=checks['nc_partition_counts_1_to_6'])
    if not checks['semicircle_cumulants_ok']:
        raise RuntimeError('selfcheck failed: free-cumulant recursion wrong')

    rows = []
    scaling = []
    for n in N_LIST:
        t_n = time.time()
        S = SAMPLES_BY_N[n]
        for k in K_LIST:
            mom_l, kap_l = route_perm(n, k, S, rng)
            rows.append({'route': 'B_perm_realpart', 'n': n, 'k': k, 'samples': S,
                         'readings': summarize(mom_l, kap_l)})
            progress(stage='routeB', n=n, k=k, samples=S)
        for k in K_LIST:
            mom_l, kap_l = route_gue(n, k, S, rng)
            rows.append({'route': 'A_gue', 'n': n, 'k': k, 'samples': S,
                         'readings': summarize(mom_l, kap_l)})
            progress(stage='routeA', n=n, k=k, samples=S)
        scaling.append({'n': n, 'samples_per_cell': S, 'k_cells': len(K_LIST),
                        'cell_sec': round((time.time() - t_n) / (2.0 * len(K_LIST)), 4),
                        'n_sec': round(time.time() - t_n, 3),
                        'work_per_cell': 'k matrix products (n^3 each) + 6 matrix powers (n^3 each), n=%d' % n})

    defects = []
    for n in DEFECT_N:
        for k in DEFECT_K:
            d = word_span_defect(n, k, rng, DEFECT_SAMPLES, DEFECT_MAX_LEN, DEFECT_WORD_CAP)
            defects.append({'n': n, 'k': k, 'samples': DEFECT_SAMPLES,
                            'word_cap_per_length': DEFECT_WORD_CAP,
                            'defect_by_len': {str(L): d[L] for L in sorted(d)}})
            progress(stage='defect', n=n, k=k)

    n_max = max(N_LIST)

    def get(route, k):
        for r in rows:
            if r['route'] == route and r['n'] == n_max and r['k'] == k:
                return r['readings']
        return None

    REF = {'A_gue': {'k2': 1.0, 'k4_over_k2sq': 0.0, 'k6_over_k2cu': 0.0},
           'B_perm_realpart': {'k2': 0.5, 'k4_over_k2sq': 0.0, 'k6_over_k2cu': 0.0}}
    TAGS = ['k2', 'k4_over_k2sq', 'k6_over_k2cu']
    comparisons = []
    for route, ref in REF.items():
        for i, k1 in enumerate(K_LIST):
            r1 = get(route, k1)
            if r1 is None:
                continue
            for k2 in K_LIST[i + 1:]:
                r2 = get(route, k2)
                if r2 is None:
                    continue
                for tag in TAGS:
                    v1, s1 = r1[tag]
                    v2, s2 = r2[tag]
                    diff = abs(v1 - v2)
                    se = float(np.hypot(s1, s2))
                    flag = bool(diff > 4.0 * se + 1e-12 and diff > 0.01 * max(abs(v1), abs(v2), 1e-12))
                    comparisons.append({'route': route, 'pair': [k1, k2], 'tag': tag,
                                        'v1': v1, 'v2': v2, 'diff': diff,
                                        'se': se, 'ratio': diff / max(se, 1e-12),
                                        'distinguishable': flag})
            for tag in TAGS:
                v1, s1 = r1[tag]
                vr = ref[tag]
                diff = abs(v1 - vr)
                flag = bool(diff > 4.0 * s1 + 1e-12
                            and diff > 0.01 * max(abs(v1), abs(vr), 1e-12))
                comparisons.append({'route': route, 'pair': [k1, 'inf_ref'], 'tag': tag,
                                    'v1': v1, 'v2': vr, 'diff': diff, 'se': s1,
                                    'ratio': diff / max(s1, 1e-12),
                                    'distinguishable': flag})

    B_dist = [c for c in comparisons if c['route'].startswith('B') and c['distinguishable']]
    A_dist = [c for c in comparisons if c['route'].startswith('A') and c['distinguishable']]
    res_se = max(get('B_perm_realpart', k)['k4_over_k2sq'][1] for k in K_LIST)

    if B_dist:
        result = 'refutes'
    elif (not A_dist) and res_se < 0.05:
        result = 'supports'
    else:
        result = 'inconclusive'

    counter = None
    if result == 'refutes':
        best = max(B_dist, key=lambda c: c['ratio'])
        counter = {'route': best['route'], 'k_pair': best['pair'], 'reading': best['tag'],
                   'value_k1': best['v1'], 'value_k2': best['v2'],
                   'diff': best['diff'], 'combined_se': best['se'],
                   'ratio_diff_over_se': best['ratio'], 'n': n_max,
                   'samples': SAMPLES_BY_N[n_max],
                   'note': '同一 (route,n,samples) 下两个 k 的标准化自由累积量差异超过 4 倍标准误'
                           ' => 该截断读数可以区分这两个 k'}

    payload = {
        'result': result,
        'claim': CLAIM,
        'method_note': 'heuristic/numeric only: no proof of anything about W*(F_k) is claimed',
        'bound': {'n_set': N_LIST, 'n_max': n_max, 'k_set': K_LIST,
                  'k_inf_proxy': 8, 'k_inf_analytic_ref': REF,
                  'max_moment_order': MAX_ORDER,
                  'samples_max': max(SAMPLES_BY_N.values()),
                  'defect_n': DEFECT_N, 'defect_word_cap': DEFECT_WORD_CAP,
                  'rank_tol': RANK_TOL, 'seed': SEED},
        'strategy': ('Monte Carlo over Haar random permutation unitaries (route B, '
                     'no renormalisation) and GUE/free-semicircular tuples (route A, '
                     'per-sample tau(g^2)=1); moments m_j=tau(R^j) by repeated matrix '
                     'powers; free cumulants from moments by noncrossing-partition '
                     'recursion (Bell(6)=203 enumerated, NC(6)=132); d1-type defect by '
                     'word-span rank (incremental+pruning with a word cap)'),
        'scaling': scaling,
        'data': {
            'rows': rows,
            'defect_rows': defects,
            'selfcheck': checks,
            'comparisons_at_nmax': comparisons,
            'distinguishable_routeA': bool(A_dist),
            'distinguishable_routeB': bool(B_dist),
            'routeB_k4_ratio_max_se': res_se,
            'notes': [
                'm_j = tau(R^j) = tr(R^j)/n, R = real part of the normalised sum; kappa from moments.',
                'route A expectations: kappa_2=1, kappa_4=kappa_6=0 identically for every k (free cumulants add under freeness, semicircular has only kappa_2) => moments of the semicircular tuple are k-independent by construction.',
                'route B (Haar unitary real part) is NOT semicircular: its cumulants depend on k; the k=inf reference is the free-CLT circular real part (semicircle of variance 1/2).',
                'k=inf is NOT realised in finite dimension: 8 is a finite stand-in and the analytic free-CLT value is used as the k=inf reference.',
                'Finite-n deviations from asymptotic freeness are visible at small n; compare the n-trend in scaling/rows before trusting any small difference.',
                'The d1-type defect here is a word-span rank deficit, a crude finite-dimensional proxy: k-dependence there is NOT evidence about isomorphism of the factors.',
                'No statement about W*(F_k) ~ W*(F_m) follows from any row of this file: moment data of a chosen generating tuple is not an isomorphism invariant.',
            ],
        },
    }
    if counter is not None:
        payload['counterexample'] = counter

    print('REPRO_RESULT: ' + json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - report the failure honestly
        print('REPRO_RESULT: ' + json.dumps(
            {'result': 'inconclusive', 'error': '%s: %s' % (type(exc).__name__, exc),
             'strategy': 'aborted before producing readings',
             'bound': {'n_set': N_LIST, 'k_set': K_LIST}}, ensure_ascii=False), flush=True)
        sys.exit(1)
