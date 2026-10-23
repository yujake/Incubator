"""Deterministic finite-group toolkit (permutation representation).

A group of order m is represented as a set of m permutations of {0..m-1}
(the left-regular image).  Multiplication = composition: mul(p,q)[i] = p[q[i]].
Everything here is deterministic: no randomness, no model judgement.
"""
import sys


def mul(p, q):
    return tuple(p[q[i]] for i in range(len(q)))


def inv(p):
    n = len(p)
    r = [0] * n
    for i, x in enumerate(p):
        r[x] = i
    return tuple(r)


def eperm(n):
    return tuple(range(n))


_OC = {}


def order_of(g):
    k = _OC.get(g)
    if k is None:
        n = len(g)
        e = eperm(n)
        x = g
        k = 1
        while x != e:
            x = mul(g, x)
            k += 1
            if k > 100000:
                raise RuntimeError('order overflow')
        _OC[g] = k
    return k


def closure(gens, n):
    """BFS closure; returns (elements, index, words) with x = s_{w1}*...*s_{wk}."""
    e = eperm(n)
    elems = [e]
    idx = {e: 0}
    rep = {e: ()}
    frontier = [e]
    while frontier:
        nxt = []
        for x in frontier:
            for i, s in enumerate(gens):
                y = mul(s, x)
                if y not in idx:
                    idx[y] = len(elems)
                    elems.append(y)
                    rep[y] = (i,) + rep[x]
                    nxt.append(y)
        frontier = nxt
    return elems, idx, rep


def gens_min(G):
    """Greedy generating set, biggest element order first (better pruning)."""
    n = len(next(iter(G)))
    gs = []
    cur = {eperm(n)}
    for g in sorted(G, key=lambda z: (-order_of(z), z)):
        if g not in cur:
            gs.append(g)
            cur = set(closure(gs, n)[0])
    return gs


def invariants(G):
    """Deterministic invariant tuple used as a cheap isomorphism pre-filter."""
    Gl = list(G)
    n = len(Gl[0])
    invs = [inv(g) for g in Gl]
    ords = tuple(sorted(order_of(g) for g in Gl))
    Z = [z for z in Gl if all(mul(z, g) == mul(g, z) for g in Gl)]
    comms = [mul(mul(a, b), mul(invs[i], invs[j]))
             for i, a in enumerate(Gl) for j, b in enumerate(Gl)]
    D = set(closure(comms, n)[0]) if comms else {eperm(n)}
    zord = tuple(sorted(order_of(z) for z in Z))
    return (len(Gl), ords, len(Z), zord, len(D))


def iso_test(G, H):
    """Deterministic isomorphism test: invariants, then generator-image search
    with prefix homomorphism/injectivity pruning (never a model judgement)."""
    if len(G) != len(H):
        return False
    if invariants(G) != invariants(H):
        return False
    n = len(next(iter(G)))
    e = eperm(n)
    gs = gens_min(G)
    Gel, Gidx, Grep = closure(gs, n)
    if len(Gel) != len(G):
        return False
    Hb = {}
    for h in H:
        Hb.setdefault(order_of(h), []).append(h)
    Hset = set(H)

    def ev(images, x):
        v = e
        for i in reversed(Grep[x]):
            v = mul(images[i], v)
        return v

    def ok_prefix(k, images):
        pgs = gs[:k]
        pel, pidx, prep = closure(pgs, n)
        mp = {}
        for x in pel:
            v = e
            for i in reversed(prep[x]):
                v = mul(images[i], v)
            mp[x] = v
        if len(set(mp.values())) != len(pel):
            return False
        for a in pel:
            for b in pel:
                if mul(mp[a], mp[b]) != mp[mul(a, b)]:
                    return False
        return True

    def dfs(i, images):
        if i == len(gs):
            mp = {x: ev(images, x) for x in Gel}
            if len(set(mp.values())) != len(G):
                return False
            if set(mp.values()) != Hset:
                return False
            for a in Gel:
                for b in Gel:
                    if mul(mp[a], mp[b]) != mp[mul(a, b)]:
                        return False
            return True
        for h in Hb.get(order_of(gs[i]), ()):
            images.append(h)
            if ok_prefix(i + 1, images) and dfs(i + 1, images):
                return True
            images.pop()
        return False

    return dfs(0, [])


def autos(N, order_k=None, node_cap=None):
    """All automorphisms of N (dict element->image), optionally those x with x^order_k = id.
    Returns (list_of_maps, nodes_visited, capped_flag)."""
    n = len(next(iter(N)))
    e = eperm(n)
    gs = gens_min(N)
    Nel, Nidx, Nrep = closure(gs, n)
    buckets = {}
    for x in N:
        buckets.setdefault(order_of(x), []).append(x)
    res = []
    nodes = [0]
    capped = [False]

    def ev(images, x):
        v = e
        for i in reversed(Nrep[x]):
            v = mul(images[i], v)
        return v

    def ok_prefix(k, images):
        pgs = gs[:k]
        pel, pidx, prep = closure(pgs, n)
        mp = {}
        for x in pel:
            v = e
            for i in reversed(prep[x]):
                v = mul(images[i], v)
            mp[x] = v
        if len(set(mp.values())) != len(pel):
            return False
        for a in pel:
            for b in pel:
                if mul(mp[a], mp[b]) != mp[mul(a, b)]:
                    return False
        return True

    def dfs(i, images):
        if capped[0]:
            return
        nodes[0] += 1
        if node_cap is not None and nodes[0] > node_cap:
            capped[0] = True
            return
        if i == len(gs):
            mp = {x: ev(images, x) for x in Nel}
            if len(set(mp.values())) != len(N):
                return
            for a in Nel:
                for b in Nel:
                    if mul(mp[a], mp[b]) != mp[mul(a, b)]:
                        return
            if order_k:
                for x in Nel:
                    y = x
                    for _ in range(order_k):
                        y = mp[y]
                    if y != x:
                        return
            res.append(mp)
            return
        for h in buckets.get(order_of(gs[i]), ()):
            images.append(h)
            if ok_prefix(i + 1, images):
                dfs(i + 1, images)
            images.pop()
            if capped[0]:
                return

    dfs(0, [])
    return res, nodes[0], capped[0]


def build_index2(N, n, phi, phinv, a):
    """Group G = <N, t | t n t^-1 = phi(n), t^2 = a> as perms on 2n points.
    Element (eps, g) means g (eps=0) or t*g (eps=1); point = eps*n + idx[g].
    Products: (0,x)(0,y)=(0,xy); (0,x)(1,y)=(1, phi^-1(x) y);
              (1,x)(0,y)=(1,xy);   (1,x)(1,y)=(0, phi(x) a y).
    """
    Nl = list(N)
    idx = {g: i for i, g in enumerate(Nl)}
    out = []
    for eps in (0, 1):
        for g in Nl:
            p = [0] * (2 * n)
            for h in Nl:
                j = idx[h]
                if eps == 0:
                    p[j] = idx[mul(g, h)]
                    p[n + j] = n + idx[mul(phinv[g], h)]
                else:
                    p[j] = n + idx[mul(g, h)]
                    p[n + j] = idx[mul(mul(phi[g], a), h)]
            out.append(tuple(p))
    return out


def extensions_index2(N, node_cap=None):
    """All groups of order 2|N| having N as a normal subgroup of index 2
    (in the abstract sense: N given as its left-regular image)."""
    n = len(next(iter(N)))
    inns = {}
    for a in N:
        ia = inv(a)
        inns[a] = {x: mul(mul(a, x), ia) for x in N}
    auts, nodes, capped = autos(N, node_cap=node_cap)
    out = []
    for phi in auts:
        phi2 = {x: phi[phi[x]] for x in N}
        phinv = {v: k for k, v in phi.items()}
        for a in N:
            if inns[a] == phi2 and phi[a] == a:
                out.append(build_index2(N, n, phi, phinv, a))
    return out, len(auts), nodes, capped


def dedupe(groups):
    """Deterministic isomorphism-class dedupe (invariant buckets + iso_test)."""
    reps = []
    buckets = {}
    for G in groups:
        key = invariants(G)
        hit = False
        for H in buckets.get(key, []):
            if iso_test(G, H):
                hit = True
                break
        if not hit:
            buckets.setdefault(key, []).append(G)
            reps.append(G)
    return reps
