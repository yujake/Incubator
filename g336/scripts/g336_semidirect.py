#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
g336_semidirect.py -- deterministic experiment for conjecture 000000, part 1:
order-336 groups with a normal Sylow 7-subgroup (n_7 = 1), and separation of
their isomorphism classes by the invariant triple
(element order spectrum, |Z(G)|, |G'|).

Method (encoded here and then RE-CHECKED by brute force on every group built):
  n_7 = 1  =>  the Sylow 7-subgroup C_7 is normal; Schur-Zassenhaus gives
  G = C_7 x|_chi H with |H| = 48.
  Aut(C_7) = C_6 is abelian, so chi: H -> C_6 factors through H/H'.  Hence chi
  is determined, up to an automorphism of C_7, by its kernel K = ker chi, and
  the possible kernels are exactly the subgroups K <= H with
      H' <= K,  K normal in H,  H/K cyclic of order m in {1, 2, 3, 6}
  (m = 1 is the trivial action).  Every such K gives a well defined G.

For every H in h_catalogue() (16 explicit groups of order 48: the 5 abelian
ones plus 11 non-abelian ones) we enumerate all such K, build G = C_7 x| H as an
explicit group of 336 elements with a full multiplication table, and compute by
brute force:
    |G| (must be 336),  n_7 = #{g : ord(g) = 7} / 6,
    element order spectrum,  |Z(G)|,  the derived series (hence |G'| and
    solvability).
A closed-form prediction of the same three invariants from (H, K) is computed
independently and compared with the brute-force value for EVERY constructed G.

The triple (order spectrum, |Z(G)|, |G'|) is an isomorphism invariant, so two
groups with different triples are non-isomorphic; the number of distinct triples
is therefore a lower bound for the number of isomorphism classes among the
constructed groups.

GAP / gapy is probed and reported, but it is never consulted for the numbers
below.  The set of H used here is an explicit SUBSET of the 52 classes of groups
of order 48 (see checks.note_H_subset).
'''

import itertools
import json
import shutil
import sys
import time


def probe_environment():
    info = {'gap_executable': shutil.which('gap')}
    try:
        import gapy  # noqa: F401
        info['gapy_importable'] = True
    except Exception as exc:
        info['gapy_importable'] = False
        info['gapy_error'] = type(exc).__name__ + ': ' + str(exc)
    return info


# ------------------------------------------------------ explicit group data

def op_cyclic(n):
    elems = list(range(n))

    def mul(a, b, n=n):
        return (a + b) % n

    return elems, mul, 0


def op_direct(*factors):
    elems = [()]
    for (e, m, i) in factors:
        elems = [t + (x,) for t in elems for x in e]

    def mul(a, b, factors=factors):
        return tuple(factors[k][1](a[k], b[k]) for k in range(len(factors)))

    ident = tuple(f[2] for f in factors)
    return elems, mul, ident


def op_dihedral(n):
    elems = [(i, s) for s in (0, 1) for i in range(n)]

    def mul(a, b, n=n):
        i, s = a
        j, t = b
        return ((i + (j if s == 0 else -j)) % n, (s + t) % 2)

    return elems, mul, (0, 0)


def op_c3_by_c16():
    elems = [(i, s) for s in range(16) for i in range(3)]

    def mul(a, b):
        i, s = a
        j, t = b
        return ((i + (j if s % 2 == 0 else -j)) % 3, (s + t) % 16)

    return elems, mul, (0, 0)


def op_q16():
    elems = [(i, s) for s in (0, 1) for i in range(8)]

    def mul(a, b):
        i, s = a
        j, t = b
        if s == 0:
            return ((i + j) % 8, t)
        if t == 0:
            return ((i - j) % 8, 1)
        return ((i - j + 4) % 8, 0)

    return elems, mul, (0, 0)


def op_q8():
    elems = [(u, s) for s in (0, 1) for u in range(4)]
    unit = {
        (0, 0): (0, 0), (0, 1): (1, 0), (0, 2): (2, 0), (0, 3): (3, 0),
        (1, 0): (1, 0), (1, 1): (0, 1), (1, 2): (3, 0), (1, 3): (2, 1),
        (2, 0): (2, 0), (2, 1): (3, 1), (2, 2): (0, 1), (2, 3): (1, 0),
        (3, 0): (3, 0), (3, 1): (2, 0), (3, 2): (1, 1), (3, 3): (0, 1),
    }

    def mul(a, b):
        (u, s) = a
        (v, t) = b
        w, f = unit[(u, v)]
        return (w, (s + t + f) % 2)

    return elems, mul, (0, 0)


def op_perm(n, even_only=False):
    elems = []
    for p in itertools.permutations(range(n)):
        if even_only:
            inv = sum(1 for i in range(n) for j in range(i + 1, n) if p[i] > p[j])
            if inv % 2:
                continue
        elems.append(p)

    def mul(a, b, n=n):
        return tuple(a[b[i]] for i in range(n))

    return elems, mul, tuple(range(n))


def op_matrix2(p, det_mode):
    elems = []
    for a in range(p):
        for b in range(p):
            for c in range(p):
                for d in range(p):
                    det = (a * d - b * c) % p
                    if det_mode == 1:
                        if det != 1:
                            continue
                    elif det == 0:
                        continue
                    elems.append((a, b, c, d))

    def mul(x, y, p=p):
        a, b, c, d = x
        e, f, g, h = y
        return ((a * e + b * g) % p, (a * f + b * h) % p,
                (c * e + d * g) % p, (c * f + d * h) % p)

    return elems, mul, (1, 0, 0, 1)


def op_c2_4_by_c3():
    def sigma(v):
        return (v[1], v[2], v[0], v[3])

    vecs = [(a, b, c, d) for a in (0, 1) for b in (0, 1) for c in (0, 1) for d in (0, 1)]
    elems = [(v, t) for t in range(3) for v in vecs]

    def mul(x, y):
        v, t = x
        w, u = y
        for k in range(t):
            w = sigma(w)
        return (tuple((v[k] + w[k]) % 2 for k in range(4)), (t + u) % 3)

    return elems, mul, ((0, 0, 0, 0), 0)


def h_catalogue():
    return [
        ('C48', op_cyclic(48)),
        ('C24xC2', op_direct(op_cyclic(24), op_cyclic(2))),
        ('C12xC4', op_direct(op_cyclic(12), op_cyclic(4))),
        ('C12xC2xC2', op_direct(op_cyclic(12), op_cyclic(2), op_cyclic(2))),
        ('C6xC2xC2xC2', op_direct(op_cyclic(6), op_cyclic(2), op_cyclic(2), op_cyclic(2))),
        ('D48', op_dihedral(24)),
        ('Q16xC3', op_direct(op_q16(), op_cyclic(3))),
        ('D16xC3', op_direct(op_dihedral(8), op_cyclic(3))),
        ('C3_C16', op_c3_by_c16()),
        ('Q8xS3', op_direct(op_q8(), op_perm(3))),
        ('S4xC2', op_direct(op_perm(4), op_cyclic(2))),
        ('A4xC4', op_direct(op_perm(4, True), op_cyclic(4))),
        ('SL23xC2', op_direct(op_matrix2(3, 1), op_cyclic(2))),
        ('GL23', op_matrix2(3, 0)),
        ('C2_4_C3', op_c2_4_by_c3()),
        ('Q8xC6', op_direct(op_q8(), op_cyclic(6))),
    ]


# ------------------------------------------------------------ group object

class Group(object):
    def __init__(self, name, spec):
        elems, mul, ident = spec
        elems = list(elems)
        self.name = name
        self.elems = [ident] + [e for e in elems if e != ident]
        self.idx = {e: i for i, e in enumerate(self.elems)}
        if len(self.idx) != len(self.elems):
            raise AssertionError(name + ': duplicate elements in catalogue entry')
        self.n = len(self.elems)
        self.table = [[self.idx[mul(a, b)] for b in self.elems] for a in self.elems]
        self.inv = [0] * self.n
        for i in range(self.n):
            for j in range(self.n):
                if self.table[i][j] == 0 and self.table[j][i] == 0:
                    self.inv[i] = j
                    break

    def orders(self):
        out = []
        for i in range(self.n):
            x = i
            k = 1
            while x != 0:
                x = self.table[x][i]
                k += 1
            out.append(k)
        return out

    def center(self):
        t = self.table
        n = self.n
        out = set()
        for i in range(n):
            row = t[i]
            ok = True
            for j in range(n):
                if row[j] != t[j][i]:
                    ok = False
                    break
            if ok:
                out.add(i)
        return out

    def derived_subgroup(self):
        n = self.n
        flat = []
        for r in self.table:
            flat.extend(r)
        return derived_closure(flat, n, self.inv, range(n))


def derived_closure(table, n, inv, subset):
    gens = set()
    for i in subset:
        bi = i * n
        for j in subset:
            a = table[bi + j]
            b = table[j * n + i]
            c = table[a * n + inv[b]]
            if c != 0:
                gens.add(c)
    if not gens:
        return {0}
    gens = sorted(gens)
    seen = {0}
    stack = [0]
    while stack:
        s = stack.pop()
        bs = s * n
        for g in gens:
            u = table[bs + g]
            if u not in seen:
                seen.add(u)
                stack.append(u)
    return seen


def extend_subgroup(H, closed, x):
    t = H.table
    total = set(closed)
    cur = set(closed)
    while True:
        nxt = set()
        for s in cur:
            u = t[s][x]
            if u not in total:
                nxt.add(u)
        if not nxt:
            return frozenset(total)
        total |= nxt
        cur = nxt


def all_subgroups(H):
    start = frozenset([0])
    known = {start}
    frontier = [start]
    while frontier:
        nf = []
        for S in frontier:
            for x in range(H.n):
                T = extend_subgroup(H, S, x)
                if T not in known:
                    known.add(T)
                    nf.append(T)
        frontier = nf
    return known


def valid_kernels(H, hder, subs):
    '''All K with H_derived <= K, K normal, H/K cyclic of order m in {1,2,3,6}.
    For each K we also return the induced chi: H -> C_6 (as a list of values).'''
    out = []
    for K in subs:
        k = len(K)
        if H.n % k:
            continue
        m = H.n // k
        if m not in (1, 2, 3, 6):
            continue
        if not hder <= K:
            continue
        normal = True
        for h in range(H.n):
            ih = H.inv[h]
            for a in K:
                if H.table[H.table[h][a]][ih] not in K:
                    normal = False
                    break
            if not normal:
                break
        if not normal:
            continue
        gen = None
        for g in range(H.n):
            pw = []
            x = 0
            for j in range(m):
                x = H.table[x][g]
                pw.append(x)
            if pw[-1] not in K:
                continue
            if any(pw[j] in K for j in range(m - 1)):
                continue
            gen = g
            break
        if gen is None:
            continue
        chi = [0] * H.n
        if m > 1:
            gp = [0]
            x = 0
            for j in range(1, m):
                x = H.table[x][gen]
                gp.append(x)
            step = 6 // m
            for h in range(H.n):
                t = None
                for j in range(m):
                    if H.table[h][H.inv[gp[j]]] in K:
                        t = j
                        break
                if t is None:
                    raise AssertionError('kernel enumeration: coset representative missing')
                chi[h] = (step * t) % 6
        out.append((K, m, chi))
    return out


class SemidirectProduct(object):
    def __init__(self, H, chi):
        self.H = H
        self.chi = chi
        self.n = 7 * H.n
        self.table = self._build()

    def _build(self):
        H = self.H
        Hn = H.n
        n = self.n
        tH = H.table
        chi = self.chi
        table = [0] * (n * n)
        for x in range(7):
            for h in range(Hn):
                base = (x * Hn + h) * n
                c = chi[h]
                a = pow(3, c, 7)  # chi[h] is the EXPONENT in Aut(C_7) = <3> = C_6, not the multiplier itself
                for y in range(7):
                    off = base + y * Hn
                    cx = (x + a * y) % 7
                    for g in range(Hn):
                        table[off + g] = cx * Hn + tH[h][g]
        return table

    def invariants(self):
        table = self.table
        n = self.n
        hist = {}
        for i in range(n):
            x = i
            k = 1
            while x != 0:
                x = table[x * n + i]
                k += 1
            hist[k] = hist.get(k, 0) + 1
        n7 = hist.get(7, 0) // 6
        z = 0
        for i in range(n):
            bi = i * n
            ok = True
            for j in range(n):
                if table[bi + j] != table[j * n + i]:
                    ok = False
                    break
            if ok:
                z += 1
        inv = [0] * n
        for i in range(1, n):
            for j in range(n):
                if table[i * n + j] == 0 and table[j * n + i] == 0:
                    inv[i] = j
                    break
        cur = set(range(n))
        series = [len(cur)]
        while len(cur) > 1:
            cur = derived_closure(table, n, inv, cur)
            series.append(len(cur))
        return hist, z, series, n7


def closed_form(H, K, m, chi, center, hder, orders):
    '''Independent prediction of (order spectrum, |Z(G)|, |G_derived|) from (H,K).'''
    hist = {}
    for h in range(H.n):
        o = orders[h]
        if chi[h] != 0:
            hist[o] = hist.get(o, 0) + 7
        else:
            hist[o] = hist.get(o, 0) + 1
            hist[7 * o] = hist.get(7 * o, 0) + 6
    if m == 1:
        z = 7 * len(center)
        d = len(hder) if len(hder) > 1 else 1
    else:
        z = len(center & set(K))
        d = 7 * len(hder)
    return hist, z, d


def main():
    t0 = time.time()
    env = probe_environment()
    print('ENV ' + json.dumps(env, sort_keys=True))
    sys.stdout.flush()

    catalogue = h_catalogue()
    records = []
    scaling = []
    mismatches = []
    for name, spec in catalogue:
        ts = time.time()
        H = Group(name, spec)
        if H.n != 48:
            raise AssertionError(name + ': order ' + str(H.n) + ' is not 48')
        orders = H.orders()
        center = H.center()
        hder = frozenset(H.derived_subgroup())
        subs = all_subgroups(H)
        kernels = valid_kernels(H, hder, subs)
        for (K, m, chi) in kernels:
            G = SemidirectProduct(H, chi)
            hist, z, series, n7 = G.invariants()
            d1 = series[1] if len(series) > 1 else 1
            cf = closed_form(H, K, m, chi, center, hder, orders)
            if cf[0] != hist or cf[1] != z or cf[2] != d1:
                mismatches.append({
                    'H': name, 'ker_size': len(K), 'm': m,
                    'closed_order_spectrum': dict(sorted(cf[0].items())),
                    'brute_order_spectrum': dict(sorted(hist.items())),
                    'closed_Z': cf[1], 'brute_Z': z,
                    'closed_derived': cf[2], 'brute_derived': d1,
                })
            records.append({
                'H': name, 'm': m, 'ker_size': len(K),
                'group_order': G.n, 'n7': n7,
                'order_spectrum': dict(sorted(hist.items())),
                'Z': z, 'derived_order': d1, 'derived_series': series,
                'solvable': series[-1] == 1,
                'key': json.dumps([sorted(hist.items()), z, d1]),
            })
        scaling.append({
            'H': name, 'H_order': H.n, 'H_derived_order': len(hder),
            'H_center_order': len(center), 'subgroup_count': len(subs),
            'kernel_count': len(kernels), 'seconds': round(time.time() - ts, 2),
        })
        print('PROGRESS ' + json.dumps({
            'H': name, 'subgroups': len(subs), 'kernels': len(kernels),
            'H_derived_order': len(hder), 'H_center_order': len(center),
            'total_seconds': round(time.time() - t0, 1),
        }, sort_keys=True))
        sys.stdout.flush()

    classes = {}
    for r in records:
        classes.setdefault(r['key'], []).append(r)
    distinct = len(classes)
    reps = []
    for k, rows in classes.items():
        rows.sort(key=lambda r: (r['H'], r['m'], r['ker_size']))
        r = rows[0]
        reps.append({
            'H': r['H'], 'm': r['m'], 'ker_size': r['ker_size'],
            'Z': r['Z'], 'derived_order': r['derived_order'],
            'order_spectrum': r['order_spectrum'],
            'multiplicity_in_constructions': len(rows),
        })
    reps.sort(key=lambda x: (x['Z'], x['derived_order'], x['H'], x['m'], x['ker_size']))

    checks = {
        'constructions': len(records),
        'distinct_invariant_triples': distinct,
        'all_constructed_groups_have_order_336': all(r['group_order'] == 336 for r in records),
        'all_have_n7_equal_1': all(r['n7'] == 1 for r in records),
        'all_solvable': all(r['solvable'] for r in records),
        'closed_form_mismatches': len(mismatches),
        'H_subset_size': len(catalogue),
        'H_subset_complete': False,
        'note_H_subset': ('there are 52 isomorphism classes of groups of order 48; this run uses '
                          '16 explicit ones (5 abelian and 11 non-abelian). The claim tested is a '
                          'lower bound claim so a subset suffices for it, but the TOTAL number of '
                          'order-336 classes with n_7 = 1 is not determined here.'),
    }
    summary = {
        'environment': env, 'checks': checks, 'scaling': scaling,
        'representative_triples': reps, 'mismatches': mismatches,
    }
    try:
        with open('out/g336_semidirect_summary.json', 'w') as fh:
            json.dump(summary, fh, indent=1, sort_keys=True)
        print('WROTE out/g336_semidirect_summary.json')
    except Exception as exc:
        print('WARN could not write summary json: ' + type(exc).__name__ + ': ' + str(exc))

    ok = (checks['all_constructed_groups_have_order_336']
          and checks['all_have_n7_equal_1']
          and len(mismatches) == 0)
    if ok and distinct >= 8:
        result = 'supports'
    else:
        result = 'inconclusive'
    repro = {
        'result': result,
        'claim': ('order-336 groups: at least 8 pairwise non-isomorphic classes with n_7 = 1 exist and are '
                  'pairwise separated by the triple (element order spectrum, size of centre, size of derived subgroup)'),
        'bound': {
            'lower_bound_classes_with_n7_1': distinct,
            'constructions_done': len(records),
            'H_subset_size': len(catalogue),
            'H_subset_is_full_52_classes': False,
        },
        'strategy': ('explicit construction over ker(chi): normal K <= H with H_derived <= K and H/K cyclic of '
                     'order 2, 3 or 6; G = C7 semidirect H built as an explicit 336-element group; invariants by '
                     'brute force (order spectrum, centre, derived series); dedupe by invariant triple; '
                     'cross-checked against an independent closed form'),
        'scaling': scaling,
        'checks': checks,
    }
    print('REPRO_RESULT: ' + json.dumps(repro, sort_keys=True))
    sys.stdout.flush()


if __name__ == '__main__':
    main()
