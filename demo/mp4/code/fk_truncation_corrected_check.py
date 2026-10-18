#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E-role corrected / diagnostic finite-dimensional truncation experiment.
HEURISTIC NUMERIC ONLY -- nothing here is a proof, and no statement about
W*(F_k) isomorphism follows from any row printed by this script.

Why a third script:
  exp 000000 (route B, Haar permutation real part) reported result=refutes with a
  k=2 vs k=8 discrepancy; exp 000002 then showed the same route disagrees with the
  analytic free-cumulant scaling law s4(k) = -1/(2k) already at k=4, n=128.
  So the k>=4 readings of the permutation route were never validated. This script
  (a) rebuilds both routes from EXPLICIT, independently drawn generators,
  (b) prints a deterministic independence probe for the permutation route,
  (c) compares the readings to the analytic free-cumulant law, and
  (d) recomputes the d1-type word-span dimension defect on validated tuples.

Claim tested (C3), stated as the proposition that would make moments k-blind:
  On n<=128 truncations with independently drawn generators, the standardised free
  cumulants s4 = kappa4/kappa2^2 and s6 = kappa6/kappa2^3 of the real part
  R = k^{-1/2} sum_i (u_i + u_i^*)/2 AGREE for k = 2, 4, 8.

Routes:
  H_haar : u_i iid Haar unitaries (QR of a Ginibre matrix, phases fixed)
  B_perm : u_i iid uniform random permutation matrices
Analytic reference (free cumulant additivity + arcsine distribution of Re of a
Haar unitary, x on [-1,1]: kappa2=1/2, kappa4=-1/8, kappa6=1/16):
  s4(k) = -1/(2k),  s6(k) = 1/(2k^2).

Verdict decided in code, not by a model:
  distinguishable(route, k1, k2) : |s4(k1)-s4(k2)| > 4*combined SE and > 1% of max|.|;
  matches_analytic(route, k)    : |s4_meas - s4_ana| <= max(0.25*|s4_ana|, 0.02);
  result = 'refutes'      if H_haar is distinguishable for some pair AND matches the
                             analytic law at every k (=> the readings genuinely differ
                             across k, claim of agreement is false);
           'inconclusive' otherwise (including: H_haar distinguishable but not yet
                             matched to the analytic law => model validity unresolved).

Diagnostics printed:
  nc_counts (Bell/NC self-check), arcsine kappa self-check, independence probe
  tau(u1 u2 u1^T u2^T) (~1/n for independent permutations, =1 if the draws are
  correlated e.g. powers of one permutation).
"""
import json
import time
from itertools import product

import numpy as np

SEED = 20261020
MAX_ORDER = 6
N_LIST = [32, 64, 128]
K_LIST = [2, 4, 8]
SAMPLES = 40
DEFECT_N = [8, 16]
DEFECT_K = [2, 3, 4, 8]
DEFECT_MAX_LEN = 6
DEFECT_WORD_CAP = 200
RANK_TOL = 1e-8
ANA = {k: {'s4': -1.0 / (2.0 * k), 's6': 1.0 / (2.0 * k * k)} for k in K_LIST}

CLAIM = ("在 n<=128 的有限维截断上（生成元显式独立抽样：Haar 酉矩阵 / 均匀随机置换矩阵），"
         "归一化和的实部 R=k^{-1/2}sum_i (u_i+u_i^*)/2 的标准化自由累积量 "
         "s4=kappa4/kappa2^2 与 s6=kappa6/kappa2^3 在 k=2,4,8 下一致 "
         "—— 若一致则矩不变量的有限截断不能区分 k。")

T0 = time.time()


def progress(**kw):
    kw['elapsed_sec'] = round(time.time() - T0, 3)
    print('PROGRESS: ' + json.dumps(kw, ensure_ascii=False, sort_keys=True), flush=True)


# ---------------- noncrossing partitions and free cumulants ----------------
def set_partitions(items):
    items = list(items)
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for smaller in set_partitions(rest):
        for i in range(len(smaller)):
            yield smaller[:i] + [[first] + smaller[i]] + smaller[i + 1:]
        yield [[first]] + smaller


def noncrossing(part, n):
    blk = {}
    for bi, b in enumerate(part):
        for x in b:
            blk[x] = bi
    for a in range(n):
        for b in range(a + 1, n):
            for c in range(b + 1, n):
                for d in range(c + 1, n):
                    if blk[a] == blk[c] and blk[b] == blk[d] and blk[a] != blk[b]:
                        return False
    return True


NC = {}
for nn in range(1, MAX_ORDER + 1):
    parts = list(set_partitions(list(range(nn))))
    NC[nn] = [p for p in parts if noncrossing(p, nn)]
NC_COUNTS = [len(NC[nn]) for nn in range(1, MAX_ORDER + 1)]


def free_cumulants(moments):
    """moments[0]=m_0=1, moments[j]=tau(R^j). Moment-cumulant formula over NC."""
    kappa = {0: 1.0}
    for nn in range(1, MAX_ORDER + 1):
        acc = 0.0
        for p in NC[nn]:
            if len(p) == 1:
                continue  # the single-block partition carries kappa_n itself
            pr = 1.0
            for b in p:
                pr *= kappa[len(b)]
            acc += pr
        kappa[nn] = moments[nn] - acc
    return kappa


def cumulants_from_eigs(lam):
    m = [1.0] + [float(np.mean(lam ** j)) for j in range(1, MAX_ORDER + 1)]
    kap = free_cumulants(m)
    s4 = kap[4] / kap[2] ** 2
    s6 = kap[6] / kap[2] ** 3
    return m, kap, s4, s6


# ---------------- generators ----------------
def haar_unitary(n, rng):
    z = (rng.standard_normal((n, n)) + 1j * rng.standard_normal((n, n))) / np.sqrt(2.0)
    q, r = np.linalg.qr(z)
    d = np.diag(r)
    ph = d / np.abs(d)
    return q * ph


def perm_matrix(p):
    n = int(p.size)
    u = np.zeros((n, n))
    u[np.arange(n), p] = 1.0
    return u


def draw_generators(route, n, k, rng):
    us = []
    for _ in range(k):
        if route == 'H_haar':
            us.append(haar_unitary(n, rng))
        else:
            us.append(perm_matrix(rng.permutation(n)))
    return us


def real_part(us, k):
    V = sum(us) / np.sqrt(float(k))
    return (V + V.conj().T) / 2.0


# ---------------- d1-type defect ----------------
def word_list(k, max_len, cap, rng):
    alphabet = [(i, s) for i in range(k) for s in (1, -1)]
    words = []
    for ell in range(1, max_len + 1):
        if len(alphabet) ** ell <= cap:
            words.extend(product(alphabet, repeat=ell))
        else:
            for _ in range(cap):
                idx = rng.integers(0, len(alphabet), size=ell)
                words.append(tuple(alphabet[j] for j in idx))
    return words


def defect_reading(n, k, rng):
    us = {}
    for i in range(k):
        m = perm_matrix(rng.permutation(n))
        us[(i, 1)] = m
        us[(i, -1)] = m.T
    words = word_list(k, DEFECT_MAX_LEN, DEFECT_WORD_CAP, rng)
    vecs = []
    for w in words:
        M = np.eye(n)
        for key in w:
            M = M @ us[key]
        vecs.append(M.reshape(-1))
    A = np.array(vecs).T
    rk = int(np.linalg.matrix_rank(A, tol=RANK_TOL))
    return 1.0 - rk / float(n * n), rk, len(words)


# ---------------- main ----------------
def main():
    rng = np.random.default_rng(SEED)

    # self-check 1: NC counts
    progress(stage='selfcheck_nc', nc_counts=NC_COUNTS,
             bell6=sum(len(list(set_partitions(list(range(6))))) for _ in [0]))
    # self-check 2: arcsine kappa (m_2j = C(2j,j)/4^j)
    arcs = [1.0] + [float(__import__('math').comb(2 * j, j)) / 4.0 ** j if j % 2 == 0 else 0.0
                    for j in range(1, MAX_ORDER + 1)]
    ka = free_cumulants(arcs)
    progress(stage='selfcheck_arcsine', kappa=[round(ka[j], 6) for j in range(1, MAX_ORDER + 1)],
             target=[0.0, 0.5, 0.0, -0.125, 0.0, 0.0625])
    selfcheck = {'nc_counts': NC_COUNTS,
                 'arcsine_kappa': [round(ka[j], 6) for j in range(1, MAX_ORDER + 1)],
                 'arcsine_target': [0.0, 0.5, 0.0, -0.125, 0.0, 0.0625]}

    # independence probe for the permutation route
    npr = 128
    p1 = rng.permutation(npr)
    p2 = rng.permutation(npr)
    u1, u2 = perm_matrix(p1), perm_matrix(p2)
    probe = float(np.trace(u1 @ u2 @ u1.T @ u2.T).real) / npr
    probe_diag = {'n': npr, 'tau_u1u2u1Tu2T': probe, 'expected_if_independent': 1.0 / npr,
                  'same_permutation': bool(np.array_equal(p1, p2)),
                  'note': 'probe near 1/n => independent draws; probe near 1 => correlated '
                          '(e.g. u_i built as powers/compositions of one permutation), which '
                          'invalidates the asymptotic-freeness approximation'}
    progress(stage='independence_probe', probe=probe)

    rows = []
    readings = {}
    scaling = []
    for route in ['H_haar', 'B_perm']:
        for n in N_LIST:
            t0 = time.time()
            for k in K_LIST:
                s4s, s6s, k2s = [], [], []
                for _ in range(SAMPLES):
                    us = draw_generators(route, n, k, rng)
                    R = real_part(us, k)
                    lam = np.linalg.eigvalsh(R)
                    _m, kap, s4, s6 = cumulants_from_eigs(lam)
                    s4s.append(s4)
                    s6s.append(s6)
                    k2s.append(kap[2])
                s4a = np.array(s4s)
                s6a = np.array(s6s)
                k2a = np.array(k2s)
                row = {'route': route, 'n': n, 'k': k, 'samples': SAMPLES,
                       'kappa2': [float(k2a.mean()), float(k2a.std(ddof=1) / np.sqrt(SAMPLES))],
                       's4': [float(s4a.mean()), float(s4a.std(ddof=1) / np.sqrt(SAMPLES))],
                       's6': [float(s6a.mean()), float(s6a.std(ddof=1) / np.sqrt(SAMPLES))],
                       's4_analytic': ANA[k]['s4'], 's6_analytic': ANA[k]['s6']}
                rows.append(row)
                readings[(route, n, k)] = row
            scaling.append({'route': route, 'n': n, 'seconds': round(time.time() - t0, 3),
                            'objects': SAMPLES * len(K_LIST),
                            'eigh_size': n, 'cumulant_order': MAX_ORDER})
            progress(stage='route', route=route, n=n,
                     s4={k: round(readings[(route, n, k)]['s4'][0], 5) for k in K_LIST},
                     s4_analytic={k: ANA[k]['s4'] for k in K_LIST})

    n_max = max(N_LIST)
    comparisons = []
    route_flags = {}
    for route in ['H_haar', 'B_perm']:
        dist_pairs = []
        for i, k1 in enumerate(K_LIST):
            for k2 in K_LIST[i + 1:]:
                r1 = readings[(route, n_max, k1)]
                r2 = readings[(route, n_max, k2)]
                v1, s1 = r1['s4']
                v2, s2 = r2['s4']
                diff = abs(v1 - v2)
                se = float(np.hypot(s1, s2))
                flag = bool(diff > 4.0 * se + 1e-12 and diff > 0.01 * max(abs(v1), abs(v2), 1e-12))
                comparisons.append({'route': route, 'pair': [k1, k2], 'reading': 's4',
                                    'v1': v1, 'v2': v2, 'diff': diff, 'se': se,
                                    'ratio': diff / max(se, 1e-12), 'distinguishable': flag})
                if flag:
                    dist_pairs.append({'pair': [k1, k2], 'v1': v1, 'v2': v2,
                                       'diff': diff, 'se': se,
                                       'ratio': diff / max(se, 1e-12)})
        match = {}
        for k in K_LIST:
            v = readings[(route, n_max, k)]['s4'][0]
            a = ANA[k]['s4']
            match[k] = bool(abs(v - a) <= max(0.25 * abs(a), 0.02))
        route_flags[route] = {'distinguishable_pairs': dist_pairs,
                              'matches_analytic_s4': match}

    hh = route_flags['H_haar']
    if hh['distinguishable_pairs'] and all(hh['matches_analytic_s4'].values()):
        result = 'refutes'
    else:
        result = 'inconclusive'

    counter = None
    if result == 'refutes':
        best = max(hh['distinguishable_pairs'], key=lambda c: c['ratio'])
        counter = {'route': 'H_haar', 'k_pair': best['pair'], 'reading': 's4=kappa4/kappa2^2',
                   'value_k1': best['v1'], 'value_k2': best['v2'], 'diff': best['diff'],
                   'combined_se': best['se'], 'ratio_diff_over_se': best['ratio'],
                   'n': n_max, 'samples': SAMPLES,
                   'analytic_reference': {str(k): ANA[k]['s4'] for k in K_LIST},
                   'note': 'k=8 与 k=2 的标准化自由累积量 s4 差异远超 4 倍合并标准误，且两条读数'
                           '都落在解析律 s4=-1/(2k) 的 25% 带内 => 同一截断下不同 k 的 s4 读数确实'
                           '不同，故"前 6 阶矩/自由累积量在 k 之间一致"这一命题被数值否证。'}

    defects = []
    for n in DEFECT_N:
        for k in DEFECT_K:
            d, rk, nw = defect_reading(n, k, rng)
            defects.append({'n': n, 'k': k, 'delta': d, 'rank': rk, 'n_squared': n * n,
                            'words': nw, 'max_len': DEFECT_MAX_LEN, 'cap_per_len': DEFECT_WORD_CAP})
        progress(stage='defect', n=n)

    payload = {
        'result': result,
        'claim': CLAIM,
        'method_note': 'heuristic/numeric only; no proof about W*(F_k) is claimed',
        'bound': {'n_set': N_LIST, 'n_max': n_max, 'k_set': K_LIST,
                  'k_inf': 'not realised in finite dimension; no k=inf row is claimed here',
                  'max_moment_order': MAX_ORDER, 'samples': SAMPLES, 'seed': SEED,
                  'analytic_reference_s4': {str(k): ANA[k]['s4'] for k in K_LIST},
                  'analytic_reference_s6': {str(k): ANA[k]['s6'] for k in K_LIST},
                  'defect_n': DEFECT_N, 'defect_max_len': DEFECT_MAX_LEN,
                  'defect_word_cap': DEFECT_WORD_CAP, 'rank_tol': RANK_TOL},
        'strategy': ('Monte Carlo over independently drawn generators (Haar unitary via QR of Ginibre; '
                     'uniform random permutation matrices), S=40 samples per (route,n,k); '
                     'R=k^{-1/2}sum(u_i+u_i^*)/2; moments m_j=mean(lambda^j) from eigvalsh; '
                     'free cumulants from moments by noncrossing-partition recursion (NC(6)=132); '
                     'd1-type defect = 1 - rank(words of length<=6, cap 200/len)/n^2 by exact rank'),
        'scaling': scaling,
        'data': {
            'rows': rows,
            'comparisons_at_nmax': comparisons,
            'route_flags': route_flags,
            'defect_rows': defects,
            'independence_probe': probe_diag,
            'selfcheck': selfcheck,
            'notes': [
                's4=kappa4/kappa2^2, s6=kappa6/kappa2^3; kappa from moments, both deterministic given the sample.',
                'Analytic free-cumulant law for this normalisation: s4(k)=-1/(2k), s6(k)=1/(2k^2); it is a '
                'property of the normalised sum (free cumulants add and scale as k^{1-j/2}), NOT an isomorphism invariant.',
                'The permutation route failed this analytic self-consistency check in exp 000000/000002 at k>=4; '
                'this script re-draws generators explicitly and reports the independence probe so the model '
                'validity is a reading, not an assumption.',
                'k=inf is not realised in finite dimension: no row claims it.',
                'The d1-type defect is a word-span rank deficit, a crude finite-dimensional proxy. Its k-dependence '
                'is NOT evidence about W*(F_k) ~ W*(F_m).',
                'No statement about W*(F_k) ~ W*(F_m) follows from any row of this file: moment data of one chosen '
                'generating tuple is not an isomorphism invariant.',
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
