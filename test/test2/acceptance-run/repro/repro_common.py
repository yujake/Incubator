"""
repro_common.py -- shared building blocks for an independent numerical
reproduction of

    Jiaqi Yu, "Cospectral periodic graphs: the spectrum does not determine
    the graph", 2026-09-21 (unpublished).

This module was written from the paper's TEXT only.  The paper's own scripts
(code/verify_all.py, code/spec_K_proof.py) were NOT distributed with the
manuscript and were not available, so nothing here is copied from them.

Everything here is *numerical cross-checking*, never proof.

Contents
--------
K(m)   : sum_ok, vertex_set_K, neighbors_K, bfs_girth_K,
         bfs_girth_K_allow_backtrack, cycles_through_root_K,
         bfs_girth_K_per_vertex, floquet_K, S_value, eigvals_K
S_m/Y_a: perm_mul, perm_inv, perm_act, permutation_generators,
         WeylElement, weyl_mul, affine_generators, coxeter_matrix,
         coxeter_matrix_from_generators, affine_group_self_check,
         build_w_ball, weyl_right_neighbors, ball_girth,
         cycles_through_identity, explicit_cycle_is_valid
S~_m   : stilde_class_representatives, stilde_voltage_table, stilde_degree,
         stilde_floquet, eigvals_stilde, hermiticity_defect,
         real_form_eigvals
spectra: max_gap, grid_z, random_z, coverage_report, sample_spectrum_union,
         path_eigenvalue_tracking

Line numbers such as (text:234-246) refer to main-paper-text.txt.
"""

from __future__ import annotations

import itertools
import math
import time
from collections import deque

import numpy as np

TOL_HERM = 1e-12          # Hermiticity gate (our own choice, not the paper's)
TOL_SPECTRUM = 1e-9       # containment gate for sampled eigenvalues


def sum_ok(x, m=None):
    """x in V_K  <=>  sum(x) in {0,1}   (eq. (1), text:32-38)."""
    return sum(x) in (0, 1)


# ==========================================================================
# 1. K(m): vertex set and adjacency   (Definition 1.1, text:39-40)
# ==========================================================================

def vertex_set_K(m, box):
    """All x in V_K with -box <= x_i <= box, sorted for determinism."""
    out = []
    rng = range(-box, box + 1)
    if m == 1:
        return [(0,), (1,)]
    for head in itertools.product(rng, repeat=m - 1):
        s_head = sum(head)
        for s in (0, 1):
            last = s - s_head
            if -box <= last <= box:
                out.append(tuple(head) + (last,))
    out.sort()
    return out


def neighbors_K(x, m):
    """Neighbours in K(m): the y = x +- e_i that still lie in V_K.

    Definition 1.1 + Lemma 2.2 (text:39-40, 138-142): for each i exactly one
    of x+e_i, x-e_i has coordinate sum in {0,1}, so the answer has size m.
    """
    res = []
    for i in range(m):
        for s in (+1, -1):
            y = list(x)
            y[i] += s
            if sum(y) in (0, 1):
                res.append(tuple(y))
    return res


def degree_K(m, x=None):
    """Degree of a vertex of K(m), computed from the realised neighbours.
    Lemma 2.2 (text:138-142) says it is m for every vertex."""
    if x is None:
        x = tuple([0] * m)
    return len(neighbors_K(x, m))


def degree_profile_K(m, box):
    """The set of degrees over all vertices of a box -- a real check of
    m-regularity that could fail (e.g. if the adjacency rule were wrong)."""
    degs = {}
    for x in vertex_set_K(m, box):
        degs.setdefault(len(neighbors_K(x, m)), 0)
        degs[len(neighbors_K(x, m))] += 1
    return {"distinct_degrees": sorted(degs), "counts": {str(k): v for k, v in degs.items()},
            "regular_of_degree_m": sorted(degs) == [m]}


def ball_vertices_K(m, radius, root=None):
    """Vertices of K(m) at distance <= radius from root (as a list, BFS order)."""
    if root is None:
        root = tuple([0] * m)
    order = [root]
    dist = {root: 0}
    q = deque([root])
    while q:
        u = q.popleft()
        if dist[u] >= radius:
            continue
        for v in neighbors_K(u, m):
            if v not in dist:
                dist[v] = dist[u] + 1
                order.append(v)
                q.append(v)
    return order


def girth_edge_deletion(vertices, neighbor_fn, radius_note=None,
                        verify_chordless=True):
    """Exact girth of the graph induced on `vertices`, by the edge-deletion
    algorithm:

        girth = min over edges {a,b} of ( dist_{G - ab}(a,b) + 1 ).

    Why this is exact and why the candidate is a genuine simple cycle: a
    shortest path P from a to b in G - ab is chordless and simple, so P + ab
    is a simple cycle of length |P| + 1.  Conversely a shortest cycle C of G is
    a shortest a-b path in G - ab for any edge ab of C (were there a shorter
    one, that path plus ab would be a shorter cycle).  So the minimum is the
    girth.  Unlike BFS-tree laddering, this cannot return a closed walk with a
    chord.

    `verify_chordless` additionally recomputes the induced edge count on the
    returned cycle and rejects it if it is not exactly the cycle length -- a
    belt-and-braces guard that makes a wrong answer detectable rather than
    silently accepted.
    """
    n = len(vertices)
    idx = {v: i for i, v in enumerate(vertices)}
    nbrs = [[idx[w] for w in neighbor_fn(v) if w in idx] for v in vertices]
    best, best_cycle = None, None
    tree = {}
    for a in range(n):
        for b in nbrs[a]:
            if b < a:
                continue
            if best is not None and best <= 3:
                break
            seen = {a: -1}
            frontier = [a]
            found = False
            depth = 0
            while frontier and not found:
                depth += 1
                nxt = []
                for u in frontier:
                    for v in nbrs[u]:
                        if (u == a and v == b) or (u == b and v == a):
                            continue
                        if v in seen:
                            continue
                        seen[v] = u
                        if v == b:
                            found = True
                            break
                        nxt.append(v)
                    if found:
                        break
                frontier = nxt
            if b not in seen or seen[b] == -1:
                continue
            L = depth + 1
            if best is not None and L >= best:
                continue
            path = []
            t = b
            while t != -1:
                path.append(t)
                t = seen[t]
            if len(set(path)) != len(path):
                continue
            if verify_chordless:
                S = set(path)
                ec = sum(1 for u in path for v in nbrs[u] if v in S) // 2
                if ec != len(path):
                    raise AssertionError(
                        "candidate cycle of length %d has %d induced edges -- "
                        "not chordless; edge-deletion result is unsound here"
                        % (len(path), ec))
            best, best_cycle = L, tuple(vertices[i] for i in path)
    return {"girth": best, "cycle_vertices": best_cycle, "ball_size": n,
            "searched_vertices": n, "radius": radius_note,
            "method": "edge-deletion shortest cycle"}


def girth_dfs(vertices, neighbor_fn, radius_note=None):
    """Girth by EXHAUSTIVE depth-first search of simple cycles inside the given
    vertex set.  Exponential in the worst case; used as an independent
    cross-check on small balls only (m = 3, 4).  Each cycle is enumerated
    exactly once, from its minimal vertex in the given order.
    """
    n = len(vertices)
    idx = {v: i for i, v in enumerate(vertices)}
    nbrs = [[idx[w] for w in neighbor_fn(v) if w in idx] for v in vertices]
    best = None
    best_cycle = None
    counter = [0]

    def dfs(start, cur, visited, visited_set):
        nonlocal best, best_cycle
        counter[0] += 1
        if counter[0] > 40_000_000:
            raise RuntimeError("girth_dfs exceeded its step budget")
        for j in nbrs[cur]:
            if j == start:
                if len(visited) >= 3 and (best is None or len(visited) < best):
                    best = len(visited)
                    best_cycle = tuple(vertices[i] for i in visited)
                continue
            if j < start or j in visited_set:
                continue
            if best is not None and len(visited) + 1 >= best:
                continue
            visited.append(j)
            visited_set.add(j)
            dfs(start, j, visited, visited_set)
            visited_set.discard(j)
            visited.pop()

    for start in range(n):
        if best is not None and best <= 3:
            break
        dfs(start, start, [start], {start})
    return {"girth": best, "cycle_vertices": best_cycle, "ball_size": n,
            "searched_vertices": n, "radius": radius_note,
            "method": "exhaustive simple-cycle DFS", "steps": counter[0]}


def bfs_girth_K(m, radius, root=None, method="edge_deletion"):
    """Girth of K(m), inside the ball of the given radius around `root`.

    The name is kept for compatibility with the brief.  Exactness: every
    vertex of a shortest cycle C is at distance <= |C|/2 from `root`, so C lies
    in the radius-3 ball and radius 3 finds a girth of 4 or 6.

    Backtracking x -> y -> x can never be reported: girth_edge_deletion and
    girth_dfs require a cycle with >= 3 distinct vertices.
    """
    if root is None:
        root = tuple([0] * m)
    verts = ball_vertices_K(m, radius, root=root)
    fn = lambda x: neighbors_K(x, m)
    if method == "dfs":
        r = girth_dfs(verts, fn, radius_note=radius)
    else:
        r = girth_edge_deletion(verts, fn, radius_note=radius)
    r["root"] = list(root)
    r["radius"] = radius
    return r


def bfs_girth_K_allow_backtrack(m, radius, root=None):
    """Deliberately WRONG variant for --inject-bug allow_backtrack: treats the
    immediate reversal x -> x +- e_i -> x as a closed walk of length 2."""
    if root is None:
        root = tuple([0] * m)
    dist = {root: 0}
    q = deque([root])
    while q:
        u = q.popleft()
        if dist[u] >= radius:
            continue
        for v in neighbors_K(u, m):
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    first = neighbors_K(root, m)[0]
    return {"girth": 2, "cycle_vertices": None, "ball_size": len(dist),
            "radius": radius, "root": list(root),
            "note": "backtrack x -> x +- e_i -> x counted as a cycle"}


def cycles_through_root_K(m, root, length, limit=None):
    """Enumerate simple cycles of exactly `length` steps through `root`: closed
    walks root -> x_1 -> ... -> x_{length-1} -> root whose intermediate
    vertices x_1..x_{length-1} are pairwise distinct and differ from root.
    (The walk then has `length` distinct vertices, i.e. it is a genuine cycle.)

    This is an independent route to "shortest cycle through root" and shares no
    code with bfs_girth_K.  Note the parity consequence: K(m) is bipartite
    (Remark 3.2, text:273-277), so no such cycle can have odd length -- a check
    that catches a traversal that muddles vertices with steps.
    """
    found = []
    root = tuple(root)

    def rec(path):
        if len(path) == length:
            if root in neighbors_K(path[-1], m):
                found.append(tuple(path))
            return
        for v in neighbors_K(path[-1], m):
            if v in path or v == root:
                continue
            path.append(v)
            rec(path)
            path.pop()

    for first in neighbors_K(root, m):
        rec([first])
    return found


def bfs_girth_K_per_vertex(m, radius, box, max_roots=12):
    """Second independent check: run the exact girth computation from many
    different roots and take the minimum.  K(m) is vertex-transitive
    (Lemma 2.2, text:142), so every root must give the same value; a
    disagreement would falsify the claim.
    """
    best = None
    best_root = None
    values = {}
    verts = vertex_set_K(m, box)[:max_roots]
    for x in verts:
        r = bfs_girth_K(m, radius, root=x)
        values[str(list(x))] = r["girth"]
        if r["girth"] is not None and (best is None or r["girth"] < best):
            best, best_root = r["girth"], x
    return {"girth": best, "root": best_root, "per_root": values,
            "n_roots": len(verts), "all_roots_agree": len(set(values.values())) == 1}


# ==========================================================================
# 2. Floquet matrix of K(m)   (Lemma 3.1(iii), text:234-246)
# ==========================================================================

def S_value(m, z, double_count=False):
    """S(chi) = 1 + sum_{i<m} z_i with z_i = exp(2 pi i z_i).

    double_count=True reproduces the edge-count error of Remark 3.5
    (text:315-320): counting each of the 2m directed steps +-e_i as its own
    cell edge, giving S(1) = 2(m-1)+1 = 2m-1 instead of m.
    """
    z = np.asarray(z, dtype=float)
    S = complex(1.0, 0.0)
    for i in range(m - 1):
        S += np.exp(2j * np.pi * z[i])
        if double_count:
            S += np.exp(-2j * np.pi * z[i])
    return S


def floquet_K(m, z, double_count=False):
    """2x2 Floquet matrix of K(m) at the character chi with
    chi(e_i) = exp(2 pi i z_i), z in [0,1)^{m-1}.

    Lemma 3.1(iii): the cell is two vertices with m parallel edges of voltages
    0, e_1, ..., e_{m-1}; Remark 2.6 says the characters of parallel edges are
    SUMMED.  Hence

        A_chi = [[0, S(chi)], [conj(S(chi)), 0]],  S(chi) = 1 + z_1 + ... + z_{m-1}.

    Equation (6) as typeset shows S in both off-diagonal slots, but its verbal
    statement ("and the conjugate in the opposite direction", text:262-265)
    and the claim Spec A_chi = {+-|S|} force the (B,A) entry to be conj(S).
    We implement the conjugate; see README "possibly wrong in the paper".
    """
    S = S_value(m, z, double_count=double_count)
    A = np.zeros((2, 2), dtype=complex)
    A[0, 1] = S
    A[1, 0] = np.conj(S)
    return A


def eigvals_K(m, z, double_count=False):
    return np.linalg.eigvalsh(floquet_K(m, z, double_count=double_count))


# ==========================================================================
# 3. Symmetric group S_m
# ==========================================================================

def perm_identity(m):
    return tuple(range(m))


def perm_mul(w, v):
    """Composition of the underlying bijections: (w v)(i) = w(v(i)).

    This is the composition making the group law of Definition 1.2,
    (w,lam)(v,mu) = (wv, lam + w(mu))  (text:49-50, 399), agree with the
    affine action on Z^m:  w . (v . x) = (w v) . x  holds with perm_act below.
    (The opposite composition would describe the same abstract group with
    s_0 <-> s_{m-1} relabelled; we fix this one so that s_0 = (tau_0, theta)
    really is the affine reflection in the wall <x, theta> = 1.)
    """
    return tuple(w[v[i]] for i in range(len(v)))


def perm_inv(w):
    out = [0] * len(w)
    for i, wi in enumerate(w):
        out[wi] = i
    return tuple(out)


def perm_act(w, vec):
    """The affine action on Z^m: (w . vec)_i = vec_{w^{-1}(i)}.

    This is the standard coordinate action of S_m, and it is exactly the one
    that makes (w,lam)(v,mu) = (wv, lam + w(mu)) associative together with
    perm_mul(w,v) = w o v.  Verified numerically by
    affine_group_self_check["associativity"] and pinned down geometrically by
    affine_reflection_self_check.
    """
    winv = perm_inv(w)
    return tuple(vec[winv[i]] for i in range(len(vec)))


def permutation_generators(m):
    """tau_i for i = 1..m-1 swaps (i-1, i); tau_0 swaps (0, m-1).  0-based."""
    gens = {}
    gens[0] = tuple((m - 1) if i == 0 else (0 if i == m - 1 else i) for i in range(m))
    for i in range(1, m):
        tau = list(range(m))
        tau[i - 1], tau[i] = tau[i], tau[i - 1]
        gens[i] = tuple(tau)
    return gens


# ==========================================================================
# 4. Affine Weyl group W_a = Q^v |x S_m
# ==========================================================================

class WeylElement(tuple):
    """Element (w, lam) of W_a: w a permutation, lam in Q^v (m ints, sum 0)."""

    __slots__ = ()

    def __new__(cls, w, lam):
        return tuple.__new__(cls, (tuple(w), tuple(int(t) for t in lam)))

    @property
    def w(self):
        return self[0]

    @property
    def lam(self):
        return self[1]

    def __repr__(self):
        return "(%s|%s)" % ("".join(str(i) for i in self[0]), ",".join(str(t) for t in self[1]))


def weyl_mul(a, b, bug_convention=False):
    """Group law of Q^v |x S_m (Definition 1.2, text:47-50; text:399):

        (w, lam) (v, mu) = (w v, lam + w(mu)).

    bug_convention=True implements the WRONG mixture (w v, lam + v(mu)),
    which fails associativity.  affine_group_self_check's associativity test
    catches it -- the girth alone does NOT.
    """
    w, lam = a
    v, mu = b
    shifted = perm_act(v, mu) if bug_convention else perm_act(w, mu)
    return WeylElement(perm_mul(w, v), tuple(lam[i] + shifted[i] for i in range(len(lam))))


def weyl_identity(m):
    return WeylElement(perm_identity(m), tuple([0] * m))


def affine_generators(m, wrong_s0=False):
    """s_i = (tau_i, 0) for i = 1..m-1, and s_0 = (tau_0, theta) with
    theta = e_1 - e_m   (Definition 1.2, text:47-57).

    wrong_s0=True drops theta (s_0 = (tau_0, 0)) -- the error the negative
    control --inject-bug wrong_s0 must catch.
    """
    taus = permutation_generators(m)
    zero = tuple([0] * m)
    theta = tuple(1 if i == 0 else (-1 if i == m - 1 else 0) for i in range(m))
    gens = {0: WeylElement(taus[0], zero if wrong_s0 else theta)}
    for i in range(1, m):
        gens[i] = WeylElement(taus[i], zero)
    return gens


def weyl_right_neighbors(e, m, wrong_s0=False, bug_convention=False):
    """Right multiplication by the m generators = Cayley-graph neighbours."""
    gens = affine_generators(m, wrong_s0=wrong_s0)
    return [weyl_mul(e, gens[i], bug_convention=bug_convention) for i in range(m)]


def affine_reflection_self_check(m, wrong_s0=False):
    """Check that s_0 really is the affine reflection of the affine Weyl group
    of type A~_{m-1} for the wall <x, theta> = 1, theta = e_1 - e_m, i.e. that
    it acts on Z^m by

        s(x) = x - ( <x, theta> - 1 ) theta         (the affine functional
                                                     psi(x) = <x,theta> - 1),

    while s_i (i >= 1) acts by the transposition tau_i.  Together with the
    Coxeter checks and the associativity check this pins down Definition 1.2
    (text:47-57) independently of any convention guess.  It fails when the
    translation part of s_0 is dropped.

    Note psi is the correct affine functional (the wall opposite the origin
    alcove), not <x,theta>: for x = e_1 one has psi = 0 (a fixed point) and for
    x = e_m one has psi = -2.
    """
    gens = affine_generators(m, wrong_s0=wrong_s0)
    theta = highest_root_A(m)

    def affine_action(g, x):
        w, lam = g
        return tuple(perm_act(w, x)[k] + lam[k] for k in range(m))

    def reflection(x):
        ip = sum(x[k] * theta[k] for k in range(m)) - 1
        return tuple(x[k] - ip * theta[k] for k in range(m))

    tests = [tuple(1 if k == i else 0 for k in range(m)) for i in range(m)]
    tests += [theta, tuple([0] * m), tuple([2] + [0] * (m - 2) + [-2])]
    bad = []
    for x in tests:
        got = affine_action(gens[0], x)
        want = reflection(x)
        if got != want:
            bad.append([list(x), list(got), list(want), "s_0"])
    for i in range(1, m):
        x = tuple(1 if k == (i - 1) else (-1 if k == i else 0) for k in range(m))
        got = affine_action(gens[i], x)
        want = tuple(-t for t in x)
        if got != want:
            bad.append([list(x), list(got), list(want), "s_%d" % i])
    # s_0 must be an involution and move the origin
    if affine_action(gens[0], affine_action(gens[0], tuple([0] * m))) != tuple([0] * m):
        bad.append(["s_0^2 != id on 0"])
    if affine_action(gens[0], tuple([0] * m)) == tuple([0] * m):
        bad.append(["s_0 fixes the origin -- translation part missing?"])
    return {"ok": not bad, "failures": bad[:5],
            "detail": "s_0 acts as x -> x - (<x,theta>-1) theta; s_i as tau_i"
                      if not bad else "s_0 (or some s_i) does not act as specified"}


def _reflection_perm(m, i):
    """The linear part of s_i: tau_0 = (0, m-1), tau_i = (i-1, i). 0-based."""
    return permutation_generators(m)[i]


# --- roots of type A_{m-1} and the affine root theta = e_1 - e_m -----------

def finite_roots_A(m):
    """The m(m-1)/2 roots of A_{m-1}, as vectors in Z^m with coordinate sum 0."""
    return [tuple(1 if k == i else (-1 if k == j else 0) for k in range(m))
            for i in range(m) for j in range(i + 1, m)]


def highest_root_A(m):
    """theta = e_1 - e_m (1-based) = e_0 - e_{m-1} (0-based)."""
    return tuple(1 if k == 0 else (-1 if k == m - 1 else 0) for k in range(m))


def cartan_matrix_affine_A(m):
    """Cartan matrix of the affine system, indexed
    [0] = affine node alpha_0 = delta - theta, [i] = alpha_i (1 <= i <= m-1).

    All A_{m-1} roots are conjugate, so with the normalisation
    <alpha_i, alpha_i> = 2 one has A[i][j] = <alpha_i, alpha_j> (the standard
    inner product on the hyperplane sum = 0).
    """
    roots = [highest_root_A(m)]
    for i in range(1, m):
        roots.append(tuple(1 if k == i - 1 else (-1 if k == i else 0) for k in range(m)))
    A = [[0] * m for _ in range(m)]
    for i in range(m):
        for j in range(m):
            A[i][j] = sum(roots[i][k] * roots[j][k] for k in range(m))
    return A, roots


def coxeter_matrix_from_cartan(A):
    """Coxeter matrix from a Cartan matrix:
    A_ij A_ji = 4 cos^2(pi/m_ij)  =>  m_ij = 2 for 0, 3 for 1, 4 for 2,
    6 for 3 (and m = infinity for the affine pairs, where A_ij A_ji = 4).
    """
    m = len(A)
    M = [[1] * m for _ in range(m)]
    for i in range(m):
        for j in range(m):
            if i == j:
                M[i][j] = 1
                continue
            p = A[i][j] * A[j][i]
            if p == 0:
                M[i][j] = 2
            elif p == 1:
                M[i][j] = 3
            elif p == 2:
                M[i][j] = 4
            elif p == 3:
                M[i][j] = 6
            elif p == 4:
                M[i][j] = 0          # affine pair: infinite order
            else:
                M[i][j] = -1         # unexpected
    return M


def coxeter_matrix(m):
    """Coxeter matrix of the generating set {s_0, s_1, ..., s_{m-1}} of the
    paper's Definition 1.2 (text:47-57):

        s_0 = (tau_0, theta) with tau_0 = (1 m) and theta = e_1 - e_m,
        s_i = (tau_i, 0)      with tau_i = (i, i+1),  1 <= i <= m-1.

    WARNING about the labelling.  With this labelling the affine node s_0 is
    adjacent in the Dynkin diagram to s_1 and to s_{m-1} (they share a
    coordinate with tau_0), and the diagram is the cycle
    0 - 1 - 2 - ... - (m-1) - 0, i.e. the affine diagram of type A~_{m-1} --
    but NOT in cycle order: reading the nodes 0,1,2,...,m-1 does not walk
    around the cycle, because the edge 0-(m-1) is present while 0 and m-2 are
    not adjacent.  Consequently (s_0 s_2)^3 = 1, not (s_0 s_2)^2 = 1.  This is
    verified numerically in cartan_and_length_self_check.
    """
    A, _ = cartan_matrix_affine_A(m)
    M = coxeter_matrix_from_cartan(A)
    return M


def cartan_and_length_self_check(m, max_radius=4):
    """Two further independent checks of the group and its presentation.

    (1) cartan_matrix_affine_A must reproduce, through A_ij A_ji = 4cos^2(pi/m_ij),
        exactly the orders measured in the realised group.  This shows the
        realised generating set {s_0,...,s_{m-1}} really is the affine Coxeter
        generating set of type A~_{m-1}: the diagram is the cycle
        0-1-...-(m-1)-0, just not in cycle order.

    (2) Coxeter's length formula for the FINITE Weyl group part: for every ball
        element with lam = 0 the word length must equal the inversion number of
        w.  This is an independent check of the permutation convention and of
        the Cayley graph, and it is stated only for the finite part: for
        elements with lam != 0 the length needs the affine root system (roots
        alpha + k*delta paired with the coroots), which this module does NOT
        implement -- see README "what we did not verify".
    """
    A, roots = cartan_matrix_affine_A(m)
    Mc = coxeter_matrix_from_cartan(A)
    Mn = coxeter_matrix_from_generators(affine_generators(m), m)

    gens = list(affine_generators(m).values())
    ident = weyl_identity(m)
    seen = {ident: 0}
    q = deque([ident])
    while q:
        u = q.popleft()
        if seen[u] >= max_radius:
            continue
        for g in gens:
            v = weyl_mul(u, g)
            if v not in seen:
                seen[v] = seen[u] + 1
                q.append(v)
    finite_tested = 0
    mismatches = []
    for e, d in seen.items():
        if any(t != 0 for t in e.lam):
            continue
        finite_tested += 1
        inv = sum(1 for i in range(m) for j in range(i + 1, m) if e.w[i] > e.w[j])
        if inv != d:
            mismatches.append([list(e.w), list(e.lam), d, inv])
    return {
        "cartan_A": A,
        "cartan_roots": [list(r) for r in roots],
        "coxeter_matrix_from_cartan": Mc,
        "coxeter_matrix_measured": Mn,
        "cartan_matches_realised_generators": Mc == Mn,
        "finite_length_formula_ok": not mismatches,
        "finite_length_mismatches": mismatches[:5],
        "finite_elements_tested": finite_tested,
        "elements_in_ball": len(seen),
        "max_radius": max_radius,
        "scope": "length formula checked for lam = 0 elements only (finite Weyl "
                 "group); the affine length formula is NOT verified here",
    }


def coxeter_matrix_from_generators(gens, m, bug_convention=False, cap=20):
    """Order of g_i g_j, measured numerically (capped at `cap`)."""
    out = [[0] * m for _ in range(m)]
    e = weyl_identity(m)
    for i in range(m):
        for j in range(m):
            g = weyl_mul(gens[i], gens[j], bug_convention=bug_convention)
            prod = e
            k = 0
            while k < cap:
                k += 1
                prod = weyl_mul(prod, g, bug_convention=bug_convention)
                if prod == e:
                    break
            out[i][j] = k
    return out


def affine_group_self_check(m, wrong_s0=False, bug_convention=False,
                            assoc_trials=60, seed=20260921):
    """Self-checks of the W_a implementation.  Every entry can fail.

    (a) generators_are_involutions : s_i^2 = e
    (b) coxeter_relations          : (s_i s_j)^{m_ij} = e for the A~ diagram
    (c) diagram_matches_realisation: measured order of s_i s_j equals m_ij
    (d) generators_distinct
    (e) associativity              : (ab)c = a(bc) on random ball elements
    """
    e = weyl_identity(m)
    gens = affine_generators(m, wrong_s0=wrong_s0)
    res = {}

    sq = all(weyl_mul(gens[i], gens[i], bug_convention=bug_convention) == e
             for i in range(m))
    res["generators_are_involutions"] = {
        "ok": bool(sq),
        "detail": "s_i^2 == e for all i = 0..%d" % (m - 1) if sq
                  else "some s_i^2 != e (affine part of s_0 lost?)",
    }

    M = coxeter_matrix(m)
    Mn = coxeter_matrix_from_generators(gens, m, bug_convention=bug_convention)
    bad = []
    for i in range(m):
        for j in range(m):
            prod = e
            g = weyl_mul(gens[i], gens[j], bug_convention=bug_convention)
            for _ in range(M[i][j]):
                prod = weyl_mul(prod, g, bug_convention=bug_convention)
            if prod != e:
                bad.append([i, j, M[i][j]])
    res["coxeter_relations"] = {
        "ok": not bad,
        "detail": "all (s_i s_j)^m_ij == e" if not bad
                  else "FAILED for (i,j,m_ij) = %s" % (bad,),
        "diagram_m_ij": M,
    }
    res["diagram_matches_realisation"] = {
        "ok": Mn == M,
        "measured_order_of_s_i_s_j": Mn,
        "expected": M,
        "detail": "measured orders equal the A~ diagram" if Mn == M
                  else "measured orders differ from the A~ diagram",
    }

    distinct = len(set(gens.values())) == m
    res["generators_distinct"] = {
        "ok": bool(distinct) and e not in gens.values(),
        "detail": "the m generators are pairwise distinct and none is the identity"
                  if distinct else "two generators coincide",
    }

    ball = build_w_ball(m, 3, wrong_s0=wrong_s0, bug_convention=bug_convention)
    elems = ball["elements"]
    rng = np.random.default_rng(seed)
    n = min(assoc_trials, max(1, len(elems) ** 3))
    idx = rng.integers(0, len(elems), size=(n, 3))
    assoc_ok, bad_triple = True, None
    for (i, j, k) in idx:
        a, b, c = elems[i], elems[j], elems[k]
        if weyl_mul(weyl_mul(a, b, bug_convention), c, bug_convention) != \
           weyl_mul(a, weyl_mul(b, c, bug_convention), bug_convention):
            assoc_ok, bad_triple = False, (a, b, c)
            break
    res["associativity"] = {
        "ok": bool(assoc_ok),
        "detail": ("associativity holds on %d random triples from the radius-3 ball" % n)
                  if assoc_ok else "associativity FAILS, e.g. a=%s b=%s c=%s" % bad_triple,
        "triples_tested": int(n),
    }
    return res


def coxeter_matrix_from_generators_bug(gens, m, bug_convention, cap=20):
    """Kept for backwards compatibility; use coxeter_matrix_from_generators."""
    return coxeter_matrix_from_generators(gens, m, bug_convention=bug_convention, cap=cap)


def build_w_ball(m, radius, wrong_s0=False, bug_convention=False, cap=400000):
    """Ball of radius `radius` around the identity in the word metric of
    {s_0,...,s_{m-1}} (BFS, so the returned list is sorted by word length)."""
    t0 = time.time()
    e = weyl_identity(m)
    seen = {e}
    order = [e]
    frontier = [e]
    capped = False
    for _ in range(radius):
        new = []
        for x in frontier:
            for y in weyl_right_neighbors(x, m, wrong_s0=wrong_s0,
                                          bug_convention=bug_convention):
                if y not in seen:
                    seen.add(y)
                    order.append(y)
                    new.append(y)
                    if len(order) > cap:
                        capped = True
                        break
            if capped:
                break
        frontier = new
        if capped or not frontier:
            break
    return {"elements": order, "size": len(order), "capped": capped,
            "seconds": time.time() - t0}


def ball_girth(elements, m, radius, wrong_s0=False, bug_convention=False,
               allow_backtrack=False):
    """Girth of the Cayley graph inside the ball, by the same exhaustive
    simple-cycle search as girth_dfs (not by BFS-tree laddering).

    Correct whenever radius >= girth/2: a shortest cycle C through the
    identity has all its vertices at distance <= |C|/2 from the identity along
    C, so C is contained in the ball.  For girth 4 or 6, radius 3 suffices.

    allow_backtrack=True is the deliberately wrong variant used by
    --inject-bug allow_backtrack: it reports 2 for the walk s_i, s_i.
    """
    if allow_backtrack:
        return {"girth": 2, "cycle_vertices": None, "ball_size": len(elements),
                "radius": radius, "searched_vertices": len(elements),
                "note": "backtrack 1 -> s_i -> 1 counted as a cycle"}
    r = girth_edge_deletion(
        elements,
        lambda x: weyl_right_neighbors(x, m, wrong_s0=wrong_s0,
                                       bug_convention=bug_convention),
        radius_note=radius)
    return r


def cycles_through_identity(m, radius, length, wrong_s0=False,
                            bug_convention=False, max_found=1):
    """Exhaustive search for simple cycles of exactly `length` through the
    identity inside the radius-`radius` ball, returned as generator words.

    Independent of ball_girth (no BFS-tree argument).  Returns
    (count, first_word).
    """
    ball = build_w_ball(m, radius, wrong_s0=wrong_s0, bug_convention=bug_convention)
    elems = set(ball["elements"])
    ident = weyl_identity(m)
    found = []

    def neigh(x):
        return weyl_right_neighbors(x, m, wrong_s0=wrong_s0,
                                    bug_convention=bug_convention)

    def rec(path, word):
        if len(found) >= max_found:
            return
        if len(path) == length:
            if ident in neigh(path[-1]):
                found.append(tuple(word))
            return
        for gi, v in enumerate(neigh(path[-1])):
            if v not in elems:
                continue
            if v in path or v == ident:
                continue
            path.append(v)
            word.append(gi)
            rec(path, word)
            word.pop()
            path.pop()

    for gi, first in enumerate(neigh(ident)):
        if first == ident:
            continue
        if len(found) >= max_found:
            break
        rec([first], [gi])
    return len(found), (found[0] if found else None)


def explicit_cycle_is_valid(vertices, neighbor_fn, name=""):
    """Verify a claimed cycle: consecutive vertices adjacent (cyclically), all
    vertices pairwise distinct, length >= 3.  Every clause can fail."""
    n = len(vertices)
    out = {"name": name, "length": n, "ok": False, "reason": ""}
    if n < 3:
        out["reason"] = "length < 3"
        return out
    if len(set(vertices)) != n:
        out["reason"] = "repeated vertex: %s" % [v for v in vertices if list(vertices).count(v) > 1]
        return out
    for i in range(n):
        u = vertices[i]
        v = vertices[(i + 1) % n]
        if v not in neighbor_fn(u):
            out["reason"] = "vertices %d and %d are not adjacent" % (i, (i + 1) % n)
            return out
    out["ok"] = True
    out["reason"] = "all consecutive pairs adjacent, all %d vertices distinct" % n
    return out


# ==========================================================================
# 5. Floquet matrix of the chamber graph S~_m  (INDEPENDENT DERIVATION)
# ==========================================================================
#
# Derivation (this is mine, done from Definitions 1.2 / 2.4 and Remark 2.6
# and not taken from any distributed code):
#
# The translation lattice of S~_m is the LEFT action of Q^v,
#
#       mu . (w, lam) = (w, lam + mu)            (text:61-63),
#
# so the cell -- the quotient by the translation lattice -- is
#
#       W_a / Q^v  ~=  S_m ,   class of (w, lam) <-> w,
#
# with m! = |W_a/Q^v| vertices (Lemma 2.2, text:130).
#
# Right multiplication by a generator s = (s_w, lam_s) is
#
#       (w, lam) . s = (w s_w, lam + w(lam_s)),
#
# so it takes the class w to the class w s_w and the translation vector
# REALISING that transition is w(lam_s) -- it depends on the source class w,
# not only on the target.  Definition 2.4 (text:164-172) defines the Floquet
# entry as the sum of chi(lam) over all adjacencies x ~ y + lam inducing the
# class transition, and Remark 2.6 (text:197-201) says parallel edges are
# summed.  Therefore
#
#       A_chi(w, w . s_w)  +=  chi( w(lam_s) )    for every generator s,
#
# where chi(lam) = exp(2 pi i <z, (lam_1,...,lam_{m-1})>), z in [0,1)^{m-1}.
# (The first m-1 coordinates determine lam because sum(lam) = 0.)
#
# Specialisations: for s_i with i >= 1, lam_s = 0 so chi(0) = 1; only s_0
# contributes a non-trivial character, chi(w(theta)) -- and theta = e_1 - e_m
# has first m-1 coordinates (1, 0, ..., 0), so w(theta)_1 = 1 iff
# w^{-1}(1) = 1 (0-based: w[0] == 0), giving the entry exp(2 pi i z_0), else 1.
#
# Independent consistency checks run by the experiments:
#   * Hermiticity ||A - A^H|| < 1e-12.  Automatic for the correct voltage
#     because (w,t) -> (t,w) is the inverse transition and chi is unitary;
#     dropping the "w ." breaks it.
#   * chi = 1 reproduces the genuine adjacency matrix of the Cayley graph of
#     S_m on {tau_0,...,tau_{m-1}}; that graph is m-regular, so lambda_max = m
#     with all-ones eigenvector, and lambda_min = -m (bipartite by sign).
#   * Spec A_chi computed by eigvalsh agrees with Spec of the real symmetric
#     2n x 2n form to 1e-9 (independent numerical route).

def _chi(z, lam):
    """chi(lam) = exp(2 pi i sum_i z_i lam_i) for lam in Q^v, using the first
    len(z) coordinates of lam."""
    arg = 0.0
    for i in range(len(z)):
        if lam[i]:
            arg += z[i] * lam[i]
    if arg == 0.0:
        return complex(1.0, 0.0)
    return complex(math.cos(2 * math.pi * arg), math.sin(2 * math.pi * arg))


def stilde_class_representatives(m):
    """One representative (w, 0) per class of W_a/Q^v, i.e. per w in S_m."""
    return [WeylElement(w, tuple([0] * m)) for w in itertools.permutations(range(m))]


def stilde_voltage_table(m, wrong_s0=False):
    """The cell of S~_m, explicitly: for each generator g and each class w,
    the target class and the voltage realising the transition."""
    gens = affine_generators(m, wrong_s0=wrong_s0)
    reps = stilde_class_representatives(m)
    table = []
    for g in range(m):
        rows = []
        for rep in reps:
            nxt = weyl_mul(rep, gens[g])
            rows.append({"source": list(rep.w), "target": list(nxt.w),
                         "voltage": list(perm_act(rep.w, gens[g].lam)),
                         "generator_voltage": list(gens[g].lam)})
        table.append(rows)
    return table


def stilde_voltage_is_well_defined(m):
    """The cell must be a well-defined voltage graph: replacing the
    representative (w, lam) of a class by (w, lam + mu) -- the same class,
    since the translation lattice acts on the second coordinate only -- must
    not change which class the right multiplication by s reaches.

        (w, lam+mu) . s = (w s_w, (lam+mu) + w(lam_s))

    so the transition is independent of the representative and the voltage
    changes by exactly mu.  Returns dict(ok, trials, witness).
    """
    gens = affine_generators(m)
    mu = tuple([1, -1] + [0] * (m - 2)) if m >= 3 else tuple([0] * m)
    reps = stilde_class_representatives(m)
    bad = None
    trials = 0
    for rep in reps:
        shifted = WeylElement(rep.w, tuple(rep.lam[i] + mu[i] for i in range(m)))
        for g in range(m):
            trials += 1
            a = weyl_mul(rep, gens[g])
            b = weyl_mul(shifted, gens[g])
            if a.w != b.w:
                bad = ("class changed", rep, mu, g)
            elif tuple(b.lam[i] - a.lam[i] for i in range(m)) != mu:
                bad = ("voltage shift is not mu", rep, mu, g, a.lam, b.lam)
    return {"ok": bad is None, "trials": trials, "witness": bad}


def stilde_degree(m, wrong_s0=False):
    """Degree of every vertex of the cell (no self-loops since s_w != 1)."""
    reps = stilde_class_representatives(m)
    gens = affine_generators(m, wrong_s0=wrong_s0)
    degs = set()
    for rep in reps:
        c = sum(1 for g in range(m) if weyl_mul(rep, gens[g]).w != rep.w)
        degs.add(c)
    return {"distinct_degrees": sorted(degs), "regular": len(degs) == 1,
            "degree": sorted(degs)[0] if len(degs) == 1 else None}


def stilde_floquet(m, z, transpose_voltage=False, wrong_s0=False,
                   bug_convention=False):
    """m! x m! Floquet matrix of the chamber graph S~_m (derivation above)."""
    z = np.asarray(z, dtype=float)
    reps = stilde_class_representatives(m)
    index = {r.w: i for i, r in enumerate(reps)}
    gens = affine_generators(m, wrong_s0=wrong_s0)
    n = len(reps)
    A = np.zeros((n, n), dtype=complex)
    for i, rep in enumerate(reps):
        for g in range(m):
            nxt = weyl_mul(rep, gens[g], bug_convention=bug_convention)
            j = index[nxt.w]
            lam_s = gens[g].lam
            if transpose_voltage:
                A[i, j] += _chi(z, lam_s)              # the "w ." is dropped
            else:
                A[i, j] += _chi(z, perm_act(rep.w, lam_s))
    return A


def eigvals_stilde(m, z, **kw):
    return np.linalg.eigvalsh(stilde_floquet(m, z, **kw))


def hermiticity_defect(A):
    return float(np.linalg.norm(A - A.conj().T))


def real_form_eigvals(A):
    """Eigenvalues of a Hermitian A via its real symmetric 2n x 2n form -- an
    independent numerical route to Spec A."""
    n = A.shape[0]
    R = np.zeros((2 * n, 2 * n))
    R[:n, :n] = A.real
    R[:n, n:] = -A.imag
    R[n:, :n] = A.imag
    R[n:, n:] = A.real
    return np.linalg.eigvalsh(R)


# ==========================================================================
# 6. spectral-set utilities
# ==========================================================================

def max_gap(values, lo, hi):
    """Largest gap between consecutive sampled values, including the boundary
    gaps to lo and hi.  Small max_gap == the sample 'fills' [lo,hi]."""
    v = np.sort(np.asarray(values, dtype=float))
    v = v[(v >= lo - 1e-9) & (v <= hi + 1e-9)]
    if v.size == 0:
        return float("inf"), 0
    pts = np.concatenate(([lo], v, [hi]))
    return float(np.diff(pts).max()), int(v.size)


def grid_z(m, npts):
    """Cartesian grid with npts points per angle on T^{m-1}."""
    axes = [np.arange(npts) / float(npts) for _ in range(m - 1)]
    mesh = np.meshgrid(*axes, indexing="ij")
    return np.stack([g.ravel() for g in mesh], axis=1)


def S_grid(m, zs, double_count=False):
    """Vectorised S(chi) = 1 + sum_i exp(2 pi i z_i) for many characters."""
    zs = np.atleast_2d(np.asarray(zs, dtype=float))
    S = np.ones(zs.shape[0], dtype=complex)
    for i in range(m - 1):
        S += np.exp(2j * np.pi * zs[:, i])
        if double_count:
            S += np.exp(-2j * np.pi * zs[:, i])
    return S


def random_z(m, n, seed=0):
    return np.random.default_rng(seed).random((n, m - 1))


def coverage_report(values, m):
    lo, hi = -float(m), float(m)
    g, n = max_gap(values, lo, hi)
    v = np.asarray(values, dtype=float)
    return {
        "m": m,
        "interval": [lo, hi],
        "n_sampled_eigenvalues": n,
        "max_gap": g,
        "max_gap_relative": (g / (2.0 * m)) if n else None,
        "min_sampled": float(v.min()) if v.size else None,
        "max_sampled": float(v.max()) if v.size else None,
        "endpoint_plus_m_reached": bool(v.size and v.max() >= m - 1e-9),
        "endpoint_minus_m_reached": bool(v.size and v.min() <= -m + 1e-9),
        "contained_in_interval": bool(v.size and v.max() <= m + 1e-9 and v.min() >= -m - 1e-9),
    }


def sample_spectrum_union(m, zs, matrix_fn, **kw):
    """Union of Spec A_{chi} over a list of characters; returns (values, per_char)."""
    vals = []
    per = []
    for z in zs:
        ev = np.linalg.eigvalsh(matrix_fn(m, z, **kw))
        vals.append(ev)
        per.append(ev)
    if not vals:
        return np.array([]), []
    return np.concatenate(vals), per


def path_eigenvalue_tracking(m, z_start, z_end, nsteps, matrix_fn, **kw):
    """Track the m! eigenvalues along the continuous path
    z(t) = z_start + t (z_end - z_start), t = 0..1 in `nsteps` steps.

    Returns dict with
      * max_step_jump : max over consecutive samples of the sorted-matching
        distance max_k |lam_k(t_{j+1}) - lam_k(t_j)|.  For a Hermitian family
        Weyl's inequality gives |lam_k(A) - lam_k(B)| <= ||A-B||_2, so this
        quantity being <= ||A(t_{j+1}) - A(t_j)||_2 + slack certifies that the
        branch matching is genuine (no jump to a different branch); a value
        far above that bound would mean the path is not continuous.
      * max_matrix_step : max ||A(t_{j+1}) - A(t_j)||_2
      * values : every eigenvalue seen along the path
      * coverage : coverage_report of the union over the path
    """
    n = nsteps + 1
    zs = [np.asarray(z_start) + (np.asarray(z_end) - np.asarray(z_start)) * (j / nsteps)
          for j in range(n)]
    prev = None
    prevA = None
    max_jump = 0.0
    max_mat = 0.0
    allv = []
    for z in zs:
        A = matrix_fn(m, z, **kw)
        ev = np.linalg.eigvalsh(A)
        if prev is not None:
            d = float(np.abs(ev - prev).max())          # both sorted
            max_jump = max(max_jump, d)
            max_mat = max(max_mat, float(np.linalg.norm(A - prevA, 2)))
        prev, prevA = ev, A
        allv.append(ev)
    vals = np.concatenate(allv)
    cov = coverage_report(vals, m)
    return {
        "n_steps": nsteps,
        "max_step_jump": max_jump,
        "max_matrix_step": max_mat,
        "matching_of_branches_is_consistent": bool(max_jump <= max_mat + 1e-9),
        "values": vals,
        "coverage": cov,
    }
