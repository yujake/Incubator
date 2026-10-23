"""Deterministic enumeration: (3,4)-colorings of K_8 up to S_8.

Claim: the 2-colorings of E(K_8) with no red K_3 and no blue K_4 form exactly
3 orbits under S_8 (red graph G triangle-free, alpha(G)<=3; blue = complement).

Method (fully deterministic, no model in the loop):
  * DFS over the 28 edge pairs in lexicographic order, red/blue branch,
    incremental pruning: red triangle (common red neighbour) and blue K_4
    (common blue neighbourhood containing a blue edge). No symmetry pruning.
  * Leaves = all valid labeled colorings F (red edge set as 28-bit mask).
  * Orbits of F under S_8: union-find over the set F with the 7 adjacent
    transposition generators (0 1),...,(6 7) of S_8.
  * Independent re-check of every leaf: no red K_3, no blue K_4, alpha<=3.
Outputs a JSON certificate on stdout.
"""
import json
from itertools import combinations

N = 8
edges = [(i, j) for i in range(N) for j in range(i + 1, N)]
E = len(edges)
edge_index = {e: k for k, e in enumerate(edges)}

radj = [0] * N
badj = [0] * N
sols = []
nodes = 0
NODE_LIMIT = 20000000


def has_blue_k4(u, v):
    common = badj[u] & badj[v]
    if common == 0:
        return False
    c = common
    while c:
        low = c & -c
        c ^= low
        w = low.bit_length() - 1
        if badj[w] & common:
            return True
    return False


def dfs(k, red):
    global nodes
    nodes += 1
    if nodes > NODE_LIMIT:
        raise RuntimeError("node limit exceeded")
    if k == E:
        sols.append(red)
        return
    u, v = edges[k]
    # branch: colour edge k red, unless it closes a red triangle
    if not (radj[u] & radj[v]):
        radj[u] |= 1 << v
        radj[v] |= 1 << u
        dfs(k + 1, red | (1 << k))
        radj[u] &= ~(1 << v)
        radj[v] &= ~(1 << u)
    # branch: colour edge k blue, unless it completes a blue K_4
    oldu, oldv = badj[u], badj[v]
    badj[u] = oldu | (1 << v)
    badj[v] = oldv | (1 << u)
    if not has_blue_k4(u, v):
        dfs(k + 1, red)
    badj[u], badj[v] = oldu, oldv


dfs(0, 0)

F = len(sols)

# ---------- independent re-verification of every leaf ----------
def check_mask(mask):
    red = [[False] * N for _ in range(N)]
    for k, (i, j) in enumerate(edges):
        if mask >> k & 1:
            red[i][j] = red[j][i] = True
    # red triangles
    tri = 0
    for a, b, c in combinations(range(N), 3):
        if red[a][b] and red[b][c] and red[a][c]:
            tri += 1
    # blue K_4 == independent 4-set in red graph
    k4 = 0
    alpha = 0
    for S in combinations(range(N), 4):
        if not any(red[a][b] for a, b in combinations(S, 2)):
            k4 += 1
    for r in range(1, N + 1):
        for S in combinations(range(N), r):
            if not any(red[a][b] for a, b in combinations(S, 2)):
                alpha = max(alpha, r)
    return tri, k4, alpha


bad = 0
for m in sols:
    tri, k4, alpha = check_mask(m)
    if tri or k4 or alpha > 3:
        bad += 1

# ---------- orbits under S_8 (adjacent transpositions) ----------
trans = [(i, i + 1) for i in range(N - 1)]
perm_edge = []
for a, b in trans:
    p = list(range(N))
    p[a], p[b] = p[b], p[a]
    emap = []
    for i, j in edges:
        x, y = p[i], p[j]
        if x > y:
            x, y = y, x
        emap.append(edge_index[(x, y)])
    perm_edge.append(emap)


def apply_perm(mask, emap):
    out = 0
    for k in range(E):
        if mask >> k & 1:
            out |= 1 << emap[k]
    return out


pos = {m: i for i, m in enumerate(sols)}
parent = list(range(F))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(x, y):
    rx, ry = find(x), find(y)
    if rx != ry:
        parent[rx] = ry


for i, m in enumerate(sols):
    for emap in perm_edge:
        n = apply_perm(m, emap)
        j = pos.get(n)
        if j is None:
            raise AssertionError("colouring set not closed under S_8")
        union(i, j)

groups = {}
for i in range(F):
    groups.setdefault(find(i), []).append(i)

reps = []
for g in groups.values():
    m = min(sols[i] for i in g)
    deg = [0] * N
    elist = []
    for k, (i, j) in enumerate(edges):
        if m >> k & 1:
            deg[i] += 1
            deg[j] += 1
            elist.append([i, j])
    reps.append({
        "orbit_size_labeled": len(g),
        "aut_order": 40320 // len(g),
        "red_edges": len(elist),
        "red_degree_sequence": sorted(deg, reverse=True),
        "red_edge_list": elist,
        "min_mask_hex": format(m, "028b"),
    })
reps.sort(key=lambda r: (-r["red_edges"], r["red_degree_sequence"]))

# Mobius ladder M_8 = C_8 + four diameters
mob = set()
for i in range(N):
    mob.add((min(i, (i + 1) % N), max(i, (i + 1) % N)))
for i in range(4):
    mob.add((i, i + 4))
mob_mask = 0
for e in mob:
    mob_mask |= 1 << edge_index[e]
mob_present = mob_mask in pos

out = {
    "n": N,
    "declared_search_space": 2 ** E,
    "search_space": 2 ** E,
    "pruning": "incremental red-triangle and blue-K4 pruning, no symmetry pruning",
    "dfs_nodes": nodes,
    "valid_labeled_colorings_F": F,
    "orbits": len(groups),
    "leaves_failing_recheck": bad,
    "mobius_ladder_M8_present": mob_present,
    "orbit_representatives": reps,
}
print(json.dumps(out, ensure_ascii=False, indent=1))

# structured conclusion (framework reads this line)
_payload = {
    "result": "supports" if (len(groups) == 3 and bad == 0) else "refutes",
    "evidence_kind": "cross_check",
    "orbits": len(groups),
    "valid_labeled_colorings_F": F,
    "dfs_nodes": nodes,
    "leaves_failing_recheck": bad,
    "mobius_ladder_M8_present": mob_present,
    "search_space": 2 ** E,
}
print("REPRO_RESULT: " + json.dumps(_payload, ensure_ascii=False))
print('{"REPRO_RESULT": ' + json.dumps(_payload, ensure_ascii=False) + '}')
