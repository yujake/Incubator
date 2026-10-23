"""Deterministic enumeration of groups of order 2,4,8,16,32 and (partial) 96.

Method: index-p extensions.  For p=2: every group of order 2m is an extension
1 -> N -> G -> C2 -> 1, so G is determined by (alpha in Aut(N), c in Z(N)) with
alpha^2 = conj(c) and alpha(c)=c; the group law is
    (i,x)(j,y) = (i+j mod 2, c^{[i+j>=2]} * alpha^{-j}(x) * y).
Same formula with p=3 for order 3m (needs alpha^3 = conj(c), alpha(c)=c).
Dedup: invariant bucket + exact isomorphism test (generator-image search with
prefix homomorphism/injectivity pruning).  No model judgement anywhere.

Output: PROGRESS: {...} per stage, out/enum/groups96.json, and one line
REPRO_RESULT: {...}.
"""
import json
import os
import sys
import time

sys.setrecursionlimit(20000)
sys.path.insert(0, "code")
from grp import mul, inv, eperm, closure, order_of, invariants, iso_test, autos  # noqa: E402

DEADLINE = float(os.environ.get("ENUM_DEADLINE", "600"))
T0 = time.time()


def tl():
    return DEADLINE - (time.time() - T0)


def prog(**kw):
    kw.setdefault("t", round(time.time() - T0, 2))
    print("PROGRESS: " + json.dumps(kw, ensure_ascii=False, sort_keys=True), flush=True)


def shift_maps(alpha, p):
    """A[j] = alpha^{-j} as a dict, j = 0..p-1."""
    ainv = {v: k for k, v in alpha.items()}
    A = [{x: x for x in alpha}]
    for _ in range(1, p):
        prev = A[-1]
        A.append({x: ainv[prev[x]] for x in alpha})
    return A


def build_ext(N, p, alpha, c):
    """Build the order p*|N| group from (N, alpha, c); return frozenset of perms on p*m
    points, or None if the law is not associative (i.e. constraints violated)."""
    Ne = sorted(N)
    m = len(Ne)
    A = shift_maps(alpha, p)
    ys = [(j, y) for j in range(p) for y in Ne]
    idx = {e: i for i, e in enumerate(ys)}
    n = p * m
    perms = []
    for (i, x) in ys:
        perm = [0] * n
        Ax = [A[j % p][x] for j in range(p)]
        for (j, y) in ys:
            z = mul(Ax[j], y)
            k = i + j
            if k >= p:
                k -= p
                z = mul(c, z)
            perm[idx[(j, y)]] = idx[(k, z)]
        perms.append(tuple(perm))
    S = set(perms)
    if len(S) != n:
        return None
    if tuple(range(n)) not in S:
        return None
    for a in perms:
        for b in perms:
            if mul(a, b) not in S:
                return None
    return frozenset(S)


def ext_stage(groups_m, p, cap):
    """All index-p extensions of the given groups of order m (as candidate groups)."""
    res = []
    stats = {"alphas": 0, "built": 0, "rejected": 0, "groups_aut_capped": 0,
             "deadline_hit": False, "aut_nodes": 0}
    for gi, N in enumerate(groups_m):
        if tl() <= 0:
            stats["deadline_hit"] = True
            break
        try:
            auts, nodes, capped = autos(N, node_cap=cap)
        except Exception as exc:  # pragma: no cover
            stats.setdefault("errors", []).append([gi, repr(exc)])
            continue
        stats["aut_nodes"] += int(nodes or 0)
        if capped:
            stats["groups_aut_capped"] += 1
        Z = [z for z in N if all(mul(z, g) == mul(g, z) for g in N)]
        x0 = sorted(N)[0]
        ix0 = inv(x0)
        for alpha in auts:
            if tl() <= 0:
                stats["deadline_hit"] = True
                break
            stats["alphas"] += 1
            ap = {x: x for x in alpha}
            for _ in range(p):
                ap = {x: alpha[ap[x]] for x in alpha}
            c0 = mul(ap[x0], ix0)
            if not all(ap[x] == mul(mul(c0, x), inv(c0)) for x in N):
                continue
            for z in Z:
                c = mul(c0, z)
                if alpha.get(c) != c:
                    continue
                G = build_ext(N, p, alpha, c)
                if G is None:
                    stats["rejected"] += 1
                    continue
                res.append(G)
                stats["built"] += 1
        prog(stage="ext", p=p, source_order=len(N), gi=gi,
             of=len(groups_m), candidates=len(res), sec=round(time.time() - T0, 1))
    return res, stats


def dedupe(cands):
    """Deterministic dedup: invariant bucket, then exact isomorphism test."""
    reps, buckets = [], {}
    for G in cands:
        key = invariants(G)
        bl = buckets.setdefault(key, [])
        dup = False
        for H in bl:
            if len(H) == len(G) and iso_test(G, H):
                dup = True
                break
        if not dup:
            bl.append(G)
            reps.append(G)
    return reps


def cycles(g):
    n = len(g)
    seen = [False] * n
    out = []
    for s in range(n):
        if not seen[s]:
            cyc = []
            x = s
            while not seen[x]:
                seen[x] = True
                cyc.append(x)
                x = g[x]
            if len(cyc) > 1:
                out.append(cyc)
    return out


def group_info(G, family, idx):
    Gl = sorted(G)
    n = len(Gl)
    d = len(Gl[0])
    e = tuple(range(d))
    prof = {}
    for g in Gl:
        k = order_of(g)
        prof[str(k)] = prof.get(str(k), 0) + 1
    Z = [z for z in Gl if all(mul(z, g) == mul(g, z) for g in Gl)]
    Gli = [inv(g) for g in Gl]
    comms = []
    for i, a in enumerate(Gl):
        for j, b in enumerate(Gl):
            comms.append(mul(mul(a, b), mul(Gli[i], Gli[j])))
    D = closure(comms, d)[0]
    n3 = len([g for g in Gl if order_of(g) == 3]) // 2
    gens = []
    cur = {e}
    for g in sorted(Gl, key=lambda z: (-order_of(z), z)):
        if len(cur) == n:
            break
        if g not in cur:
            gens.append(g)
            cur = set(closure(gens, d)[0])
    return {
        "index": idx,
        "order": n,
        "family": family,
        "order_profile": prof,
        "center_order": len(Z),
        "derived_order": len(D),
        "n_3": n3,
        "n_2": 1 if family == "n3=1" else None,
        "n_2_note": ("P (order 32) is normal by construction" if family == "n3=1"
                     else "not computed (family not enumerated to completion)"),
        "generators_cycles": [cycles(g) for g in gens],
        "degree": d,
    }


def main():
    known = {1: 1, 2: 1, 4: 2, 8: 5, 16: 14, 32: 51, 96: 231}
    groups = {1: [frozenset({(0,)})]}
    scaling = []
    order = 1
    while order <= 16 and tl() > 0:
        t = time.time()
        cands, stats = ext_stage(groups[order], 2, cap=200000)
        reps = dedupe(cands)
        groups[order * 2] = reps
        scaling.append({"order": order * 2, "classes": len(reps),
                        "literature_count": known.get(order * 2),
                        "raw_candidates": len(cands),
                        "sec": round(time.time() - t, 2), "stats": stats})
        prog(stage="order", order=order * 2, classes=len(reps), known=known.get(order * 2))
        order *= 2

    # order 32 (index-2 extensions of the 14 groups of order 16)
    if 16 in groups and tl() > 0:
        t = time.time()
        cands, stats = ext_stage(groups[16], 2, cap=200000)
        reps = dedupe(cands)
        groups[32] = reps
        scaling.append({"order": 32, "classes": len(reps), "literature_count": known[32],
                        "raw_candidates": len(cands), "sec": round(time.time() - t, 2),
                        "stats": stats})
        prog(stage="order", order=32, classes=len(reps), known=known[32])

    # order 96, only the n_3 = 1 family (P normal of order 32, G = P.C3)
    g96 = []
    stats96 = {}
    if 32 in groups and tl() > 0:
        t = time.time()
        cands, stats = ext_stage(groups[32], 3, cap=60000)
        reps = dedupe(cands)
        g96 = reps
        stats96 = {"raw_candidates": len(cands), "classes_n3_eq_1": len(reps),
                   "sec": round(time.time() - t, 2), "stats": stats}
        prog(stage="order", order=96, family="n3=1", classes=len(reps))

    infos = [group_info(G, "n3=1", i) for i, G in enumerate(g96)]
    os.makedirs("out/enum", exist_ok=True)
    with open("out/enum/groups96.json", "w", encoding="utf-8") as fh:
        json.dump({"method": "index-p extension enumeration (deterministic)",
                   "orders_enumerated": {str(k): len(v) for k, v in sorted(groups.items())},
                   "order_96_families": ["n3=1 (P.C3)"],
                   "classes": infos}, fh, indent=1, sort_keys=True)

    counts = {str(k): len(v) for k, v in sorted(groups.items())}
    check_upto16 = all(counts.get(str(k)) == known[k] for k in (1, 2, 4, 8, 16))
    total96 = len(g96)
    result = "inconclusive"
    why = []
    if counts.get("32") != known[32]:
        why.append("order-32 count %r != literature 51" % counts.get("32"))
    if total96 != known[96]:
        why.append("order-96 enumeration incomplete: only the n_3=1 family (P normal, "
                   "P.C3) was enumerated (%d classes); families n_3=4 and n_3=16 were not "
                   "enumerated, so the 231 count is neither confirmed nor refuted" % total96)
    data = {"counts_by_order": counts, "literature_counts": {str(k): v for k, v in known.items()},
            "small_orders_match": check_upto16,
            "order_96_classes_found_n3_eq_1": total96, "order_96_stats": stats96,
            "scaling": scaling, "why_inconclusive": why,
            "json_out": "out/enum/groups96.json"}
    print("REPRO_RESULT: " + json.dumps({"result": result,
                                         "bound": "groups of order 1,2,4,8,16,32 enumerated "
                                                  "completely (if counts match); order 96 only "
                                                  "n_3=1 family",
                                         "strategy": "index-p extensions (p=2,3) + automorphism "
                                                     "enumeration + cocycle parameter c in Z(N) + "
                                                     "invariant/iso-test dedup",
                                         "scaling": scaling, "data": data}, sort_keys=True),
          flush=True)


if __name__ == "__main__":
    main()
