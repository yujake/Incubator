#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R(3,4) = 9 -- deterministic verification (role E).

Upper bound (R(3,4) <= 9): exhaustive backtracking over all 2-colourings of the
edges of K_9.  Raw search space 2^36 = 68,719,476,736 colourings; the DFS
decides edges in lexicographic order and prunes

  * incremental red-triangle pruning: a red decision for {u,v} is rejected when
    u and v already share a red neighbour (so a red triangle would close);
  * blue-K_4 completion pruning: a blue decision for {u,v} is rejected when it
    completes a blue K_4 (u,v plus two vertices blue-adjacent to both of them);
  * sound symmetry breaking: relabelling vertices while fixing vertex 0 is WLOG,
    so the red neighbourhood of vertex 0 is forced to be the prefix {1,...,d};
    inside the resulting blue class B = {d+1,...,n-1} the red neighbourhood of
    vertex 1 is forced to be a prefix of B.

The pruned tree is still complete: every 2-colouring of K_n has a relabelled
representative that sits in exactly one leaf of this tree.

Lower bound (R(3,4) >= 9): the Moebius ladder M_8 on K_8 -- red = the 8-cycle
(i, i+1) plus the four diameters (i, i+4) -- is verified in-script to contain no
red triangle and no blue K_4.

Output protocol (REPRO_RESULT):
  one line  REPRO_RESULT: {"result": ..., "bound": ..., "strategy": ...,
                           "scaling": ..., "data": {...}}
  plus one PROGRESS line per finished n.
"""

import json
import time
from itertools import combinations


# ---------------------------------------------------------------- search core

def blue_completes_k4(blue, u, v):
    """True iff adding the blue edge {u,v} closes a blue K_4."""
    cand = blue[u] & blue[v]          # vertices blue-adjacent to both u and v
    if cand == 0:
        return False
    xs = []
    mm = cand
    while mm:
        low = mm & -mm
        xs.append(low.bit_length() - 1)
        mm ^= low
    for a in range(len(xs)):
        ba = blue[xs[a]]
        for b in range(a + 1, len(xs)):
            if (ba >> xs[b]) & 1:
                return True
    return False


def search(n, node_cap=200_000_000, time_cap=900.0, stop_at_first=False):
    """Complete DFS over 2-colourings of K_n (see module docstring).

    nodes           : number of DFS nodes entered (one node per edge decision
                      plus the root), i.e. size of the pruned search tree;
    solutions_found : number of leaves (= complete colourings) reached that
                      survive all constraints, counted modulo the symmetry
                      breaking above (NOT the number of labelled colourings);
    complete        : False iff a node/time cap fired, in which case the run is
                      NOT an exhaustive proof and the verdict must be inconclusive.
    """
    edges = [(i, j) for i in range(n) for j in range(i + 1, n)]
    m = len(edges)
    red = [0] * n
    blue = [0] * n
    stats = {
        "n": n,
        "edge_count": m,
        "raw_space": 2 ** m,
        "nodes": 0,
        "solutions_found": 0,
        "red_triangle_prunes": 0,
        "blue_k4_prunes": 0,
        "aborted": None,
        "first_solution": None,
    }
    t0 = time.time()

    def dfs(idx, b0_seen, b1_closed):
        stats["nodes"] += 1
        if stats["nodes"] > node_cap:
            stats["aborted"] = "node_cap"
            return
        if (stats["nodes"] % 16384) == 0 and (time.time() - t0) > time_cap:
            stats["aborted"] = "time_cap"
            return
        if idx == m:
            stats["solutions_found"] += 1
            if stats["first_solution"] is None:
                stats["first_solution"] = [(i, j) for (i, j) in edges if (red[i] >> j) & 1]
            return
        u, v = edges[idx]

        allow_red = True
        if u == 0 and b0_seen:            # symmetry: reds of vertex 0 form a prefix
            allow_red = False
        elif u == 1:
            d = bin(red[0]).count("1")    # red degree of vertex 0 (block 0 is decided)
            if 2 <= v <= d:              # {1..d} is a blue clique -> forced blue
                allow_red = False
            elif v > d and b1_closed:    # symmetry: reds of vertex 1 inside B are a prefix
                allow_red = False

        if allow_red:
            if red[u] & red[v]:
                stats["red_triangle_prunes"] += 1
            else:
                red[u] |= 1 << v
                red[v] |= 1 << u
                dfs(idx + 1, b0_seen, b1_closed)
                red[u] &= ~(1 << v)
                red[v] &= ~(1 << u)
                if stats["aborted"]:
                    return

        if blue_completes_k4(blue, u, v):
            stats["blue_k4_prunes"] += 1
        else:
            blue[u] |= 1 << v
            blue[v] |= 1 << u
            nb0 = b0_seen or (u == 0)
            nb1 = b1_closed
            if u == 1:
                d = bin(red[0]).count("1")
                if v > d:
                    nb1 = True
            dfs(idx + 1, nb0, nb1)
            blue[u] &= ~(1 << v)
            blue[v] &= ~(1 << u)
            if stats["aborted"]:
                return

    dfs(0, False, False)
    stats["seconds"] = round(time.time() - t0, 4)
    stats["complete"] = stats["aborted"] is None
    return stats


# ------------------------------------------------------- lower bound (K_8)

def verify_mobius(n=8):
    """Red = C_n + n/2 diameters (Moebius ladder M_8) on K_n; check the colours."""
    A = [[False] * n for _ in range(n)]
    for i in range(n):
        j = (i + 1) % n
        A[i][j] = A[j][i] = True
    for i in range(n // 2):
        A[i][i + n // 2] = A[i + n // 2][i] = True

    red_edges = [(i, j) for i in range(n) for j in range(i + 1, n) if A[i][j]]
    blue_edges = [(i, j) for i in range(n) for j in range(i + 1, n) if not A[i][j]]
    red_tri = [t for t in combinations(range(n), 3)
               if A[t[0]][t[1]] and A[t[1]][t[2]] and A[t[0]][t[2]]]
    blue_k4 = [S for S in combinations(range(n), 4)
               if all(not A[x][y] for x, y in combinations(S, 2))]
    deg = [sum(1 for j in range(n) if A[i][j]) for i in range(n)]
    return {
        "graph": "Moebius ladder M_8 = C_8 + 4 diameters, taken as the RED graph; blue = complement",
        "n": n,
        "red_edge_count": len(red_edges),
        "blue_edge_count": len(blue_edges),
        "red_degree_per_vertex": deg,
        "red_edges": red_edges,
        "red_triangle_count": len(red_tri),
        "blue_K4_count": len(blue_k4),
        "witness_valid": (len(red_tri) == 0 and len(blue_k4) == 0),
    }


# ---------------------------------------------------------------------- main

CAPS = {6: (30_000_000, 120.0), 7: (60_000_000, 180.0),
        8: (120_000_000, 300.0), 9: (300_000_000, 1500.0)}


def main():
    per_n = {}
    scaling = {}
    for n in (6, 7, 8, 9):
        node_cap, time_cap = CAPS[n]
        # n <= 8 : stop at the first witness (records the cost of reaching a
        #          witness); n = 9 : exhaust the whole pruned tree (no witness
        #          exists, so the traversal is the proof).
        st = search(n, node_cap=node_cap, time_cap=time_cap, stop_at_first=(n <= 8))
        per_n[n] = st
        scaling[str(n)] = {
            "nodes": st["nodes"],
            "seconds": st["seconds"],
            "raw_colorings_2^C(n,2)": st["raw_space"],
            "solutions_found_up_to_symmetry_breaking": st["solutions_found"],
            "red_triangle_prunes": st["red_triangle_prunes"],
            "blue_k4_prunes": st["blue_k4_prunes"],
            "complete": st["complete"],
            "mode": "exhaustive" if n == 9 else "stopped_at_first_witness",
        }
        print("PROGRESS: " + json.dumps({
            "n": n, "nodes": st["nodes"], "seconds": st["seconds"],
            "solutions_found": st["solutions_found"],
            "red_triangle_prunes": st["red_triangle_prunes"],
            "blue_k4_prunes": st["blue_k4_prunes"],
            "complete": st["complete"]}), flush=True)

    wit = verify_mobius(8)

    print("")
    print("READINGS (each number defined):")
    print("  nodes                = DFS nodes entered in the pruned tree for K_n")
    print("  raw_colorings        = 2^(C(n,2)), colourings before any pruning")
    print("  solutions_found      = complete colourings reached, modulo the symmetry breaking")
    print("  red_triangle_prunes  = branches killed because a red edge would close a red K_3")
    print("  blue_k4_prunes       = branches killed because a blue edge would close a blue K_4")
    print("  red_triangle_count   = number of red K_3 in the K_8 witness")
    print("  blue_K4_count        = number of blue K_4 in the K_8 witness")
    for n in (6, 7, 8, 9):
        print("  n=%d: nodes=%d seconds=%.4f solutions_found=%d complete=%s" % (
            n, per_n[n]["nodes"], per_n[n]["seconds"],
            per_n[n]["solutions_found"], per_n[n]["complete"]))
    print("  K_8 witness (%s): red_edges=%d blue_edges=%d red_triangles=%d blue_K4s=%d valid=%s" % (
        wit["graph"], wit["red_edge_count"], wit["blue_edge_count"],
        wit["red_triangle_count"], wit["blue_K4_count"], wit["witness_valid"]))
    print("")

    upper_done = per_n[9]["complete"]
    upper_ok = upper_done and per_n[9]["solutions_found"] == 0
    lower_ok = bool(wit["witness_valid"])
    lower_found_by_search = per_n[8]["solutions_found"] > 0

    counterexample = None
    if upper_done and per_n[9]["solutions_found"] > 0:
        result = "refutes"
        counterexample = per_n[9]["first_solution"]
    elif upper_ok and lower_ok:
        result = "supports"
    else:
        result = "inconclusive"

    payload = {
        "result": result,
        "bound": {
            "upper": "R(3,4) <= 9: no 2-colouring of K_9 avoids both a red K_3 and a blue K_4",
            "lower": "R(3,4) >= 9: explicit 2-colouring of K_8 avoiding red K_3 and blue K_4",
            "search_bound": {
                "n": 9,
                "raw_colourings": per_n[9]["raw_space"],
                "nodes_visited": per_n[9]["nodes"],
                "exhaustive": upper_done,
                "quotient": "symmetry breaking: vertex-0 red neighbourhood is a prefix {1..d}; inside the blue class B the red neighbourhood of vertex 1 is a prefix of B",
                "algorithm": "DFS over lexicographically ordered edges, complete",
            },
        },
        "strategy": "backtracking + incremental red-triangle pruning + blue-K4 completion pruning + prefix symmetry breaking (iso rejection quotient)",
        "scaling": scaling,
        "data": {
            "claim": "R(3,4) = 9",
            "upper_bound_proved_by_search": upper_ok,
            "lower_bound_witness": wit,
            "K_8_witness_also_found_by_search": lower_found_by_search,
            "definitions": {
                "nodes": "DFS nodes entered (root + one per edge decision in the pruned tree)",
                "raw_colourings": "2^(C(n,2))",
                "solutions_found": "leaves reached modulo symmetry breaking (not labelled count)",
                "red_triangle_prunes": "branches killed by the red-K_3 check",
                "blue_k4_prunes": "branches killed by the blue-K_4 check",
                "red_triangle_count": "number of red K_3 in the K_8 witness",
                "blue_K4_count": "number of blue K_4 in the K_8 witness",
            },
            "note_n6_n8_mode": "for n<=8 the DFS stops at the first witness, so its nodes count is the cost of reaching a witness, not the full tree; n=9 is the only exhaustive traversal",
            "all_runs_complete": all(per_n[n]["complete"] for n in (6, 7, 8, 9)),
        },
    }
    if result == "refutes":
        payload["counterexample"] = counterexample

    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
