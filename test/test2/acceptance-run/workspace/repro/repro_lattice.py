"""
repro_lattice.py -- exact (integer) lattice bookkeeping for Lemma 2.2 and
Remark 2.3 of the paper (text:127-163): the period lattice Q^v, the sublattice
Lambda = m Q^v, its index in Q^v, and the cell V_K/Lambda.

Kept separate from repro_common.py so the exact-integer part can be read and
audited on its own.  Same rules apply: numerical/algebraic cross-checks only,
never a proof.
"""

from __future__ import annotations

import fractions
import itertools
import math

import repro_common as rc


# --------------------------------------------------------------------------
# exact integer linear algebra
# --------------------------------------------------------------------------

def det_int(M):
    """Exact determinant of a square integer matrix (fraction-free Bareiss)."""
    n = len(M)
    if n == 0:
        return 1
    if n == 1:
        return int(M[0][0])
    A = [[int(t) for t in row] for row in M]
    sign = 1
    prev = 1
    for k in range(n - 1):
        if A[k][k] == 0:
            sw = next((i for i in range(k + 1, n) if A[i][k] != 0), None)
            if sw is None:
                return 0
            A[k], A[sw] = A[sw], A[k]
            sign = -sign
        for i in range(k + 1, n):
            for j in range(k + 1, n):
                A[i][j] = (A[i][j] * A[k][k] - A[i][k] * A[k][j]) // prev
        prev = A[k][k]
        for i in range(k + 1, n):
            A[i][k] = 0
    return sign * A[n - 1][n - 1]


def smith_normal_form(rows, max_steps=20000):
    """Diagonal (invariant factors) of the Smith normal form of the integer
    matrix with the given rows.  Pure integer arithmetic."""
    A = [[int(t) for t in r] for r in rows]
    if not A:
        return []
    nrows, ncols = len(A), len(A[0])
    diag = []
    r = c = 0
    steps = 0
    while r < nrows and c < ncols:
        steps += 1
        if steps > max_steps:
            raise RuntimeError("smith_normal_form did not terminate")
        piv = None
        for i in range(r, nrows):
            for j in range(c, ncols):
                if A[i][j] and (piv is None or abs(A[i][j]) < abs(A[piv[0]][piv[1]])):
                    piv = (i, j)
        if piv is None:
            break
        pi, pj = piv
        A[r], A[pi] = A[pi], A[r]
        for row in A:
            row[c], row[pj] = row[pj], row[c]
        changed = True
        while changed:
            changed = False
            for i in range(r + 1, nrows):
                if A[i][c]:
                    q = A[i][c] // A[r][c]
                    for j in range(c, ncols):
                        A[i][j] -= q * A[r][j]
                    if A[i][c]:
                        A[r], A[i] = A[i], A[r]
                        changed = True
            for j in range(c + 1, ncols):
                if A[r][j]:
                    q = A[r][j] // A[r][c]
                    for i in range(r, nrows):
                        A[i][j] -= q * A[i][c]
                    if A[r][j]:
                        for row in A:
                            row[c], row[j] = row[j], row[c]
                        changed = True
        diag.append(abs(A[r][c]))
        r += 1
        c += 1
    return diag


def coordinates_in_basis(vectors, basis):
    """Exact coordinates of each vector of `vectors` in the lattice spanned by
    `basis` (both lists of equal-length integer tuples of full rank).  Returns
    a list of integer tuples."""
    n = len(basis)
    dim = len(basis[0])
    out = []
    for b in vectors:
        M = [[fractions.Fraction(basis[k][j]) for k in range(n)]
             + [fractions.Fraction(int(b[j]))] for j in range(dim)]
        piv_cols = []
        row = 0
        for col in range(n):
            pr = next((i for i in range(row, dim) if M[i][col] != 0), None)
            if pr is None:
                continue
            M[row], M[pr] = M[pr], M[row]
            pv = M[row][col]
            M[row] = [t / pv for t in M[row]]
            for i in range(dim):
                if i != row and M[i][col] != 0:
                    f = M[i][col]
                    M[i] = [M[i][j] - f * M[row][j] for j in range(n + 1)]
            piv_cols.append(col)
            row += 1
        sol = [fractions.Fraction(0) for _ in range(n)]
        for i, col in enumerate(piv_cols):
            sol[col] = M[i][n]
        assert all(t.denominator == 1 for t in sol), \
            "vector %s is not in the lattice spanned by %s" % (b, basis)
        out.append(tuple(int(t) for t in sol))
    return out


# --------------------------------------------------------------------------
# Q^v and Lambda = m Q^v
# --------------------------------------------------------------------------

def coroot_lattice_basis(m):
    """Q^v = {x in Z^m : sum x = 0}; basis e_i - e_{i+1}, i = 1..m-1 (0-based)."""
    return [tuple(1 if k == i else (-1 if k == i + 1 else 0) for k in range(m))
            for i in range(m - 1)]


def lattice_index_report(m):
    """Index [Q^v : m Q^v], computed three independent ways:
      (1) the coordinate matrix of m*(coroot basis) inside the coroot basis is
          m*I, so the index is m^(m-1) exactly;
      (2) the Smith normal form of that coordinate matrix;
      (3) a brute-force count of the residue classes of Q^v modulo m Q^v.
    The paper's Remark 2.3 (text:158-162) states this index is m^(m-1)."""
    B = coroot_lattice_basis(m)
    coord = coordinates_in_basis([[m * t for t in r] for r in B], [list(r) for r in B])
    coord = [list(r) for r in coord]
    det = abs(det_int(coord))
    snf = smith_normal_form(coord)
    snf_prod = 1
    for d in snf:
        snf_prod *= d
    by_residues = len(set(itertools.product(range(m), repeat=m - 1)))
    return {
        "m": m,
        "coroot_basis": [list(t) for t in B],
        "coordinate_matrix_of_mQcoroot_in_Qcoroot": coord,
        "index_by_determinant": det,
        "smith_normal_form": snf,
        "index_by_smith_normal_form": snf_prod,
        "index_by_residue_count": by_residues,
        "index_formula_m_pow_m_minus_1": m ** (m - 1),
        "all_agree": det == snf_prod == by_residues == m ** (m - 1),
    }


def classes_VK_mod_Lambda(m, sub_lattice="mQcoroot"):
    """Count the classes of V_K by the lattice Lambda, and return canonical
    representatives.

    x in V_K is determined by (x_1,...,x_{m-1}) and the value of sum(x) in
    {0,1}.  An element of Q^v shifts x by an integer vector of sum 0; m Q^v
    shifts it by m times such a vector, so modulo Lambda two vertices of V_K
    are equivalent exactly when their first m-1 coordinates agree mod m.  Hence

        |V_K/Lambda| = 2 * m^(m-1)        (Remark 2.3, text:159-162)

    with canonical representatives ((x_1..x_{m-1}) mod m, sum(x)).

    sub_lattice="Qcoroot" is the deliberately wrong lattice used by
    --inject-bug lattice_Q: with Lambda = Q^v the two level sets above are the
    only classes, giving 2.
    For sub_lattice="mQcoroot_small" (a wrong step size) the count is 2*k^(m-1).
    """
    if sub_lattice == "Qcoroot":
        # With Lambda = Q^v the two level sets are exactly the two orbits
        # (Lemma 2.2, text:127-137), so the quotient has 2 classes.
        by_level = {0: set(), 1: set()}
        for x in rc.vertex_set_K(m, 4):
            # quotient by Q^v: two vertices of V_K are equivalent iff they lie
            # in the same level (Q^v is transitive on each level)
            by_level[sum(x)].add(sum(x))
        return {"sub_lattice": "Q^v (WRONG: step 1 instead of m)",
                "n_classes": len(by_level[0]) + len(by_level[1]),
                "n_classes_expected": 2 * m ** (m - 1),
                "note": "Q^v is transitive on each level set, so V_K/Q^v has "
                        "exactly 2 classes"}
    if sub_lattice.startswith("step"):
        k = int(sub_lattice[4:])
        reps = set()
        for head in itertools.product(range(k), repeat=m - 1):
            for s in (0, 1):
                reps.add((head, s))
        return {"sub_lattice": "step %d (WRONG)" % k, "n_classes": len(reps),
                "n_classes_expected": 2 * m ** (m - 1)}
    reps = set()
    for head in itertools.product(range(m), repeat=m - 1):
        for s in (0, 1):
            reps.add((head, s))
    return {"sub_lattice": "m Q^v", "n_classes": len(reps),
            "n_classes_expected": 2 * m ** (m - 1),
            "representatives_sample": sorted(reps)[:8]}


def class_size_check(m, box=None):
    """Verify that |V_K/Lambda| really is 2*m^(m-1) for Lambda = m Q^v, by
    checking that EVERY candidate residue pair (head mod m, level) is realised
    by an actual vertex of V_K.  (The classes themselves are infinite, so there
    is no such thing as a uniform finite class size inside a box; what has to be
    checked is that the residue map is surjective onto the 2*m^(m-1) candidates,
    and injective by the argument in classes_VK_mod_Lambda.)

    Note the subtlety that makes this non-trivial: the ceiling vector c =
    (m-1,...,m-1) has sum m(m-1), so c itself is NOT in V_K; the vertices whose
    first m-1 coordinates hit a given residue are spread over the levels, and a
    residue (head, s) is realisable iff the level-s vertex exists with those
    coordinates modulo m.
    """
    boxes = box if box is not None else 2 * m
    verts = rc.vertex_set_K(m, boxes)
    realised = {0: set(), 1: set()}
    for x in verts:
        realised[sum(x)].add(tuple(t % m for t in x[:-1]))
    n0, n1 = len(realised[0]), len(realised[1])
    expected_each = m ** (m - 1)
    return {
        "m": m, "box": boxes, "vertices_in_box": len(verts),
        "n_classes_level_0": n0, "n_classes_level_1": n1,
        "n_classes_total": n0 + n1,
        "expected_each_level": expected_each,
        "expected_total": 2 * expected_each,
        "all_candidates_realised": n0 == n1 == expected_each,
    }


def degree_profile_K_interior(m, box):
    """Degree of every vertex of the box-induced graph, restricted to the
    INTERIOR of the box (every coordinate strictly inside [-box,box]), where no
    neighbour can fall outside the box.  This is the honest way to test
    m-regularity by box enumeration: a boundary vertex of the box can have fewer
    neighbours *inside the box* while the graph itself is perfectly regular, so
    the boundary has to be excluded (or the box made larger and only the
    boundary discarded)."""
    verts = rc.vertex_set_K(m, box)
    vset = set(verts)
    inside = [x for x in verts if all(abs(t) < box for t in x)]
    degs = {}
    for x in inside:
        d = len([y for y in rc.neighbors_K(x, m) if y in vset])
        degs[d] = degs.get(d, 0) + 1
    boundary_degs = {}
    outside = [x for x in verts if x not in set(inside)]
    for x in outside:
        d = len([y for y in rc.neighbors_K(x, m) if y in vset])
        boundary_degs[d] = boundary_degs.get(d, 0) + 1
    return {"box": box, "n_vertices_in_box": len(verts),
            "n_interior_vertices": len(inside),
            "interior_degrees": sorted(degs),
            "interior_counts": {str(k): v for k, v in degs.items()},
            "interior_regular_of_degree_m": sorted(degs) == [m],
            "boundary_degrees": sorted(boundary_degs),
            "boundary_counts": {str(k): v for k, v in boundary_degs.items()},
            "note": "neighbors_K(x,m) counts neighbours in V_K (not in the box), "
                    "and Lemma 2.2 says that count is always m"}


def degree_profile_K(m, box):
    """Degree profile over the whole box-induced graph, to demonstrate the
    boundary effect explicitly (some boundary degrees are < m)."""
    verts = rc.vertex_set_K(m, box)
    vset = set(verts)
    degs = {}
    for x in verts:
        d = len([y for y in rc.neighbors_K(x, m) if y in vset])
        degs[d] = degs.get(d, 0) + 1
    return {"box": box, "distinct_degrees": sorted(degs),
            "counts": {str(k): v for k, v in degs.items()}}


def translation_invariance_K(m, box, shifts):
    """K(m) is vertex-transitive (Lemma 2.2, text:142): x -> x + lam for
    lam in Q^v is a graph automorphism.  Checked on the induced box graph for
    the given shifts by comparing neighbour sets inside the smaller box."""
    verts = set(rc.vertex_set_K(m, box))
    results = []
    for lam in shifts:
        ok = True
        tested = 0
        for x in verts:
            y = tuple(x[k] + lam[k] for k in range(m))
            if y not in verts:
                continue
            tested += 1
            for nb in rc.neighbors_K(x, m):
                shifted = tuple(nb[k] + lam[k] for k in range(m))
                if shifted not in verts:
                    continue
                if shifted not in rc.neighbors_K(y, m):
                    ok = False
        results.append({"shift": list(lam), "tested": tested, "ok": bool(ok)})
    return {"n_vertices_in_box": len(verts), "shifts": results,
            "all_shifts_are_automorphisms": all(r["ok"] for r in results)}
