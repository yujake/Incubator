#!/usr/bin/env python3
"""Exhaustive computational verification for R(3,4) = 9.

Claim under test
----------------
(i)  Every red/blue 2-colouring of the edges of K_9 contains a red K_3 or a
     blue K_4.                                  (hence R(3,4) <= 9)
(ii) There exists a red/blue 2-colouring of the edges of K_8 that contains
     neither a red K_3 nor a blue K_4.          (hence R(3,4) > 8)

Method
------
Deterministic depth-first search over the 2^m edge colourings (m = n(n-1)/2),
edges in lexicographic order (0,1),(0,2),...,(n-2,n-1).  A branch is cut
exactly when the partial colouring already contains a forbidden configuration,
because every extension of such a partial colouring still contains it.  So the
number of complete colourings reached is the EXACT number of valid colourings:
the search is exhaustive, not sampled.

For n = 9 the plain search is run with a node cap (it may not finish), and a
*degree-bounded* variant is run as well.  The variant also cuts a branch as
soon as some vertex has more than 3 red edges.  Justification (lemma proved on
paper, and checked empirically here by comparing solution counts of the two
searches at n = 7 and n = 8):

  L. In a colouring with no red K_3 and no blue K_4, the red neighbourhood
     N_R(v) of any vertex v is red-independent (else a red triangle through v),
     hence every edge inside N_R(v) is blue, hence |N_R(v)| <= 3 (four vertices
     of N_R(v) would span a blue K_4).  So every valid colouring has red degree
     <= 3 at every vertex, and cutting partial states with red degree >= 4
     loses no valid colouring.

Self-calibration: the same machinery is applied to (red K_3, blue K_3), whose
answers R(3,3) = 6 are known, as a check that the code is not silently wrong.

Output: human-readable log plus one line starting with REPRO_RESULT: holding a
JSON object with result / bound / strategy / scaling / data.
"""

import itertools
import json
import time


def blue_edge_creates_clique(blue, i, j, blue_clique):
    """Would colouring edge (i, j) blue create a blue K_{blue_clique}?
    Only that edge is new, so only cliques through it can be new."""
    s = blue[i] & blue[j]
    if blue_clique == 3:
        return s != 0
    # blue_clique == 4: two common blue neighbours must be joined by a blue edge
    while s:
        low = s & -s
        a = low.bit_length() - 1
        s ^= low
        if s & blue[a]:
            return True
    return False


def search(n, blue_clique=4, max_red_deg=None, cap_nodes=None, cap_seconds=None, keep=10):
    """Count (and record up to `keep` of) the red/blue colourings of E(K_n) with
    no red K_3 and no blue K_{blue_clique}.  Returns a stats dict."""
    edges = [(i, j) for i in range(n) for j in range(i + 1, n)]
    m = len(edges)
    red = [0] * n
    blue = [0] * n
    rdeg = [0] * n
    colour = {}
    stats = {
        "n": n, "blue_clique": blue_clique, "max_red_deg": max_red_deg,
        "edges": m, "nodes": 0, "count": 0, "capped": False,
        "cap_reason": None, "solutions": [], "seconds": 0.0,
    }
    t0 = time.time()

    def over_cap():
        if cap_nodes is not None and stats["nodes"] > cap_nodes:
            stats["capped"] = True
            stats["cap_reason"] = "nodes"
            return True
        if cap_seconds is not None and (stats["nodes"] & 0x3FFFF) == 0:
            if time.time() - t0 > cap_seconds:
                stats["capped"] = True
                stats["cap_reason"] = "seconds"
                return True
        return False

    def dfs(e):
        stats["nodes"] += 1
        if over_cap():
            return True
        if e == m:
            stats["count"] += 1
            if len(stats["solutions"]) < keep:
                stats["solutions"].append(dict(colour))
            return False
        i, j = edges[e]
        bi, bj = 1 << i, 1 << j
        # --- colour this edge red (forbidden: red triangle, red degree bound)
        if not (red[i] & red[j]):
            if max_red_deg is None or (rdeg[i] + 1 <= max_red_deg and rdeg[j] + 1 <= max_red_deg):
                colour[(i, j)] = 0
                red[i] |= bj
                red[j] |= bi
                rdeg[i] += 1
                rdeg[j] += 1
                abort = dfs(e + 1)
                red[i] &= ~bj
                red[j] &= ~bi
                rdeg[i] -= 1
                rdeg[j] -= 1
                del colour[(i, j)]
                if abort:
                    return True
        # --- colour this edge blue (forbidden: blue K_{blue_clique})
        if not blue_edge_creates_clique(blue, i, j, blue_clique):
            colour[(i, j)] = 1
            blue[i] |= bj
            blue[j] |= bi
            abort = dfs(e + 1)
            blue[i] &= ~bj
            blue[j] &= ~bi
            del colour[(i, j)]
            if abort:
                return True
        return False

    dfs(0)
    stats["seconds"] = round(time.time() - t0, 3)
    return stats


def forbidden_configuration(n, colour, blue_clique=4):
    """Independent brute-force check of one complete colouring.
    Returns None if it contains no red K_3 and no blue K_{blue_clique},
    else a description of a forbidden configuration found."""

    def c(a, b):
        return colour[(min(a, b), max(a, b))]

    for tri in itertools.combinations(range(n), 3):
        if all(c(a, b) == 0 for a, b in itertools.combinations(tri, 2)):
            return "red K3 on %s" % (tri,)
    for q in itertools.combinations(range(n), blue_clique):
        if all(c(a, b) == 1 for a, b in itertools.combinations(q, 2)):
            return "blue K%d on %s" % (blue_clique, q)
    return None


def red_edges(n, colour):
    return [[i, j] for i in range(n) for j in range(i + 1, n) if colour[(i, j)] == 0]


def slim(s):
    return {k: s[k] for k in ("n", "blue_clique", "max_red_deg", "edges",
                              "nodes", "count", "capped", "cap_reason", "seconds")}


def main():
    log = []
    out = {"calibration_R33": {}, "counts_R34": {}, "pruning_crosscheck": {},
           "n9_plain": {}, "n9_degree_bounded": {}, "certificate_K8": {}}

    # ---------- calibration: R(3,3) = 6 ----------
    for n in (5, 6):
        s = search(n, blue_clique=3, cap_seconds=120)
        out["calibration_R33"][str(n)] = slim(s)
        log.append("CALIB R(3,3): n=%d -> %d colourings with no mono triangle "
                   "(nodes=%d, %.3fs, capped=%s)"
                   % (n, s["count"], s["nodes"], s["seconds"], s["capped"]))

    # ---------- R(3,4): plain exhaustive search for n <= 8 ----------
    plain = {}
    for n in (6, 7, 8):
        plain[n] = search(n, blue_clique=4, keep=10)
        out["counts_R34"][str(n)] = slim(plain[n])
        log.append("PLAIN R(3,4): n=%d -> %d colourings with no red K3 and no blue K4 "
                   "(nodes=%d, %.3fs, capped=%s)"
                   % (n, plain[n]["count"], plain[n]["nodes"],
                      plain[n]["seconds"], plain[n]["capped"]))

    # certificate: a valid colouring of K_8, plus an independent brute check
    cert = None
    if plain[8]["solutions"]:
        cand = plain[8]["solutions"][0]
        bad = forbidden_configuration(8, cand, 4)
        cert_ok = (bad is None and len(cand) == 28)
        cert = {"red_edges": red_edges(8, cand), "blue_edges_count": len(cand) - len(red_edges(8, cand)),
                "independent_check": "no red K3 and no blue K4" if cert_ok else ("FOUND " + str(bad)),
                "verified": cert_ok}
        log.append("CERTIFICATE K8: red edges %s ; independent brute check -> %s"
                   % (cert["red_edges"], cert["independent_check"]))
    else:
        cert = {"red_edges": None, "blue_edges_count": None,
                "independent_check": "no valid K8 colouring found", "verified": False}
        log.append("CERTIFICATE K8: NONE FOUND")
    out["certificate_K8"] = cert

    # ---------- pruning cross-check at n = 7, 8 ----------
    for n in (7, 8):
        sd = search(n, blue_clique=4, max_red_deg=3, cap_seconds=300)
        out["pruning_crosscheck"][str(n)] = {
            "plain_count": plain[n]["count"], "degree_bounded_count": sd["count"],
            "agree": (sd["count"] == plain[n]["count"] and not sd["capped"]),
            "degree_bounded_nodes": sd["nodes"], "seconds": sd["seconds"],
        }
        log.append("PRUNING CROSSCHECK n=%d: plain=%d degree_bounded=%d agree=%s"
                   % (n, plain[n]["count"], sd["count"],
                      out["pruning_crosscheck"][str(n)]["agree"]))

    # ---------- n = 9: plain (capped) and degree-bounded ----------
    s9p = search(9, blue_clique=4, cap_nodes=4000000, cap_seconds=180, keep=1)
    out["n9_plain"] = slim(s9p)
    log.append("PLAIN R(3,4): n=9 -> count=%d nodes=%d %.3fs capped=%s(%s)"
               % (s9p["count"], s9p["nodes"], s9p["seconds"], s9p["capped"], s9p["cap_reason"]))
    if s9p["solutions"]:
        bad9 = forbidden_configuration(9, s9p["solutions"][0], 4)
        log.append("PLAIN R(3,4): n=9 found a colouring; independent check -> %s"
                   % ("clean (would REFUTE the claim!)" if bad9 is None else bad9))

    s9d = search(9, blue_clique=4, max_red_deg=3, cap_nodes=40000000, cap_seconds=600, keep=1)
    out["n9_degree_bounded"] = slim(s9d)
    log.append("DEGREE-BOUNDED R(3,4): n=9 -> count=%d nodes=%d %.3fs capped=%s(%s)"
               % (s9d["count"], s9d["nodes"], s9d["seconds"], s9d["capped"], s9d["cap_reason"]))

    # ---------- verdict ----------
    cal_ok = (out["calibration_R33"]["5"]["count"] > 0
              and out["calibration_R33"]["6"]["count"] == 0
              and not out["calibration_R33"]["6"]["capped"])
    cross_ok = all(out["pruning_crosscheck"][k]["agree"] for k in ("7", "8"))
    r33_ok = (out["counts_R34"]["8"]["count"] > 0 and cert["verified"])
    r34_ok = (s9d["count"] == 0 and not s9d["capped"])
    refuted = bool(s9p["solutions"]) and forbidden_configuration(9, s9p["solutions"][0], 4) is None

    if refuted:
        verdict = "refutes"
    elif cal_ok and cross_ok and r33_ok and r34_ok:
        verdict = "supports"
    else:
        verdict = "inconclusive"

    failures = []
    if not cal_ok:
        failures.append("calibration R(3,3)=6 failed")
    if not cross_ok:
        failures.append("degree-bound pruning disagrees with plain search at n=7/8")
    if not r33_ok:
        failures.append("no verified K8 certificate")
    if not r34_ok:
        failures.append("n=9 exhaustive count is not a completed 0 (capped=%s)" % s9d["capped"])

    for ln in log:
        print(ln)
    print("VERDICT: %s" % verdict)
    if failures:
        print("FAILURES: %s" % "; ".join(failures))

    result = {
        "result": verdict,
        "claim": "R(3,4) = 9: every red/blue colouring of E(K_9) has a red K3 or a "
                 "blue K4, and some colouring of E(K_8) has neither",
        "bound": "R(3,4) = 9 exactly (lower: an explicit clean colouring of K_8; "
                 "upper: exhaustive count 0 of clean colourings of K_9)",
        "strategy": "deterministic DFS over all edge 2-colourings in lexicographic edge "
                    "order, pruning only on forbidden configurations (red K3 / blue K4); "
                    "n=9 additionally run with the red-degree<=3 prune (lemma L in the "
                    "module docstring), whose solution count is cross-checked against the "
                    "plain search at n=7 and n=8",
        "scaling": [
            {"n": 5, "edges": 10, "blue_clique": 3, "count": out["calibration_R33"]["5"]["count"],
             "nodes": out["calibration_R33"]["5"]["nodes"], "seconds": out["calibration_R33"]["5"]["seconds"]},
            {"n": 6, "edges": 15, "blue_clique": 3, "count": out["calibration_R33"]["6"]["count"],
             "nodes": out["calibration_R33"]["6"]["nodes"], "seconds": out["calibration_R33"]["6"]["seconds"]},
            {"n": 6, "edges": 15, "blue_clique": 4, "count": out["counts_R34"]["6"]["count"],
             "nodes": out["counts_R34"]["6"]["nodes"], "seconds": out["counts_R34"]["6"]["seconds"]},
            {"n": 7, "edges": 21, "blue_clique": 4, "count": out["counts_R34"]["7"]["count"],
             "nodes": out["counts_R34"]["7"]["nodes"], "seconds": out["counts_R34"]["7"]["seconds"]},
            {"n": 8, "edges": 28, "blue_clique": 4, "count": out["counts_R34"]["8"]["count"],
             "nodes": out["counts_R34"]["8"]["nodes"], "seconds": out["counts_R34"]["8"]["seconds"]},
            {"n": 9, "edges": 36, "blue_clique": 4, "count": out["n9_plain"]["count"],
             "nodes": out["n9_plain"]["nodes"], "seconds": out["n9_plain"]["seconds"],
             "capped": out["n9_plain"]["capped"]},
            {"n": 9, "edges": 36, "blue_clique": 4, "count": out["n9_degree_bounded"]["count"],
             "nodes": out["n9_degree_bounded"]["nodes"], "seconds": out["n9_degree_bounded"]["seconds"],
             "capped": out["n9_degree_bounded"]["capped"], "variant": "red degree <= 3"},
        ],
        "data": {
            "n": 9,
            "blue_clique": 4,
            "objects": "red/blue 2-colourings of E(K_n)",
            "n9_clean_colourings": out["n9_degree_bounded"]["count"],
            "n8_clean_colourings": out["counts_R34"]["8"]["count"],
            "K8_red_edges": cert["red_edges"],
            "calibration_R33": out["calibration_R33"],
            "pruning_crosscheck": out["pruning_crosscheck"],
            "failures": failures,
        },
    }
    print("REPRO_RESULT: " + json.dumps(result, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
