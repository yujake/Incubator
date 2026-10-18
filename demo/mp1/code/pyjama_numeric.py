"""pyjama_numeric.py -- deterministic numerics for the stripe-covering ("Pyjama") functional

    r(Theta) = sup_{p in R^2} min_i dist(p . u_i, Z),   u_i = (cos th_i, sin th_i)

dist(t, Z) = |t - floor(t + 0.5)|.   Every number printed by this file is produced by
this file; the summary line is

    REPRO_RESULT: {"result": ..., "bound": ..., "strategy": ..., "scaling": ..., "data": ...}

Modes (argv[1]): part1 | part2 | part3
  part1 : k=1 (r=1/2), k=2 family theta2/theta1 rational (r=1/2, exact linear solve),
          k=3 equilateral (r=1/3 witness), k=3/4 generic (grid lower bound -> 1/2),
          k=4 rational-direction set with period 5Z^2.
  part2 : minimal k for eps=0.1, 0.05 -- exhaustive over all subsets of a rational
          direction pool, k <= 6, plus the equilateral k=3 reference.
  part3 : counterexample search -- a concrete point (x,y) with all dists > eps.
"""

import json
import math
import sys
import time
from itertools import combinations

TWO_PI = 2.0 * math.pi


def dist_int(t):
    return abs(t - math.floor(t + 0.5))


def cs(thetas):
    return [(math.cos(t), math.sin(t)) for t in thetas]


def fmin(th, x, y):
    m = 1.0
    for c, s in th:
        d = abs((x * c + y * s) - math.floor(x * c + y * s + 0.5))
        if d < m:
            m = d
    return m


def dists(th, x, y):
    return [abs((x * c + y * s) - math.floor(x * c + y * s + 0.5)) for c, s in th]


def grid_scan(th, Q, R):
    """max over rational points p=(a/q,b/q), 1<=q<=Q, |a|,|b|<=q*R."""
    t0 = time.time()
    best = (-1.0, 0.0, 0.0)
    n = 0
    for q in range(1, Q + 1):
        lim = max(1, int(round(q * R)))
        for a in range(-lim, lim + 1):
            x = a / q
            for b in range(-lim, lim + 1):
                y = b / q
                v = fmin(th, x, y)
                n += 1
                if v > best[0]:
                    best = (v, x, y)
    return best, n, time.time() - t0


def box_scan(th, lo, hi, step):
    """max over the regular grid lo..hi (step) in both coordinates."""
    t0 = time.time()
    best = (-1.0, 0.0, 0.0)
    n = 0
    m = int(round((hi - lo) / step))
    for i in range(m + 1):
        x = lo + i * step
        for j in range(m + 1):
            y = lo + j * step
            v = fmin(th, x, y)
            n += 1
            if v > best[0]:
                best = (v, x, y)
    return best, n, time.time() - t0


def refine(th, x0, y0, h0, iters=200):
    """local axis/diagonal hill climb with step halving (deterministic)."""
    best = [fmin(th, x0, y0), x0, y0]
    h = h0
    dirs = ((h, 0.0), (-h, 0.0), (0.0, h), (0.0, -h),
            (h, h), (h, -h), (-h, h), (-h, -h))
    for _ in range(iters):
        moved = False
        for dx, dy in dirs:
            v = fmin(th, best[1] + dx, best[2] + dy)
            if v > best[0] + 1e-16:
                best = [v, best[1] + dx, best[2] + dy]
                moved = True
        if not moved:
            h *= 0.5
            for k in range(len(dirs)):
                pass
            dirs = ((h, 0.0), (-h, 0.0), (0.0, h), (0.0, -h),
                    (h, h), (h, -h), (-h, h), (-h, -h))
            if h < 1e-14:
                break
    return tuple(best)


def solve2(u1, u2, t1, t2):
    """solve (p.u1, p.u2) = (t1, t2) for p in R^2 (2x2 linear system)."""
    (c1, s1) = u1
    (c2, s2) = u2
    det = c1 * s2 - c2 * s1
    if abs(det) < 1e-13:
        return None, det
    x = (t1 * s2 - t2 * s1) / det
    y = (c1 * t2 - c2 * t1) / det
    return (x, y), det


def emit(result, bound, strategy, scaling, data, extra=None):
    payload = {"result": result, "bound": bound, "strategy": strategy,
               "scaling": scaling, "data": data}
    if extra:
        payload.update(extra)
    print("REPRO_RESULT: " + json.dumps(payload, ensure_ascii=False))


def part1():
    out = []
    scal = []
    t_start = time.time()

    # ---- k = 1 ------------------------------------------------------------
    th = cs([0.7])
    u1 = th[0]
    p = (0.5 * u1[0], 0.5 * u1[1])
    out.append({"case": "k=1 theta=[0.7] exact witness p=u/2",
                "r": fmin(th, p[0], p[1]),
                "dists": dists(th, p[0], p[1]),
                "witness_xy": [p[0], p[1]],
                "note": "p.u = 1/2 exactly; dist<=1/2 always => r = 1/2"})
    b, n, dt = grid_scan(th, 40, 1.0)
    r_ref = refine(th, b[1], b[2], 0.03)
    out.append({"case": "k=1 rational grid Q=40 R=1.0 + local refine",
                "grid_max": b[0], "refined": r_ref[0],
                "witness_xy": [r_ref[1], r_ref[2]],
                "points": n, "sec": round(dt, 2)})
    scal.append({"case": "k=1", "points": n, "sec": round(dt, 2)})
    print("PROGRESS: " + json.dumps({"part": "part1", "case": "k=1",
                                     "grid_max": round(b[0], 9),
                                     "refined": round(r_ref[0], 9)}))

    # ---- k = 2, family theta2/theta1 rational -----------------------------
    for ratio in (1.5, 2.0, 5.0 / 3.0, 8.0 / 5.0, 1.01):
        thetas = [0.3, 0.3 * ratio]
        th = cs(thetas)
        p2, det = solve2(th[0], th[1], 0.5, 0.5)
        exact = fmin(th, p2[0], p2[1]) if p2 else None
        b, n, dt = grid_scan(th, 30, 1.0)
        r_ref = refine(th, b[1], b[2], 0.04)
        out.append({"case": "k=2 theta1=0.3 theta2/theta1=%.6f" % ratio,
                    "det(u1,u2)": det,
                    "r_exact_linear_solve": exact,
                    "dists_at_exact": dists(th, p2[0], p2[1]) if p2 else None,
                    "exact_witness_xy": [p2[0], p2[1]] if p2 else None,
                    "grid_max": b[0], "refined": r_ref[0],
                    "points": n, "sec": round(dt, 2)})
        scal.append({"case": "k=2 ratio=%.6f" % ratio, "points": n, "sec": round(dt, 2)})
        print("PROGRESS: " + json.dumps({"part": "part1", "case": "k=2",
                                         "ratio": ratio,
                                         "r_exact": exact,
                                         "refined": round(r_ref[0], 9)}))

    # ---- k = 3 equilateral -------------------------------------------------
    eq_angles = [0.4, 0.4 + TWO_PI / 3.0, 0.4 + 2.0 * TWO_PI / 3.0]
    thE = cs(eq_angles)
    pE, detE = solve2(thE[0], thE[1], 1.0 / 3.0, 1.0 / 3.0)
    dE = dists(thE, pE[0], pE[1])
    b, n, dt = grid_scan(thE, 40, 1.2)
    r_ref = refine(thE, b[1], b[2], 0.03)
    out.append({"case": "k=3 equilateral theta=0.4+{0,2pi/3,4pi/3}",
                "det(u1,u2)": detE,
                "exact_witness_xy": [pE[0], pE[1]],
                "dists_at_exact": dE,
                "r_from_witness": min(dE),
                "note": "u1+u2+u3=0 so p.u3 = -2/3 = 1/3 mod 1; r=1/3 by construction",
                "grid_max": b[0], "refined": r_ref[0],
                "points": n, "sec": round(dt, 2)})
    scal.append({"case": "k=3 equilateral", "points": n, "sec": round(dt, 2)})
    print("PROGRESS: " + json.dumps({"part": "part1", "case": "k=3 equilateral",
                                     "witness_min_dist": min(dE),
                                     "grid_max": round(b[0], 9),
                                     "refined": round(r_ref[0], 9)}))

    # ---- generic k=3, k=4 (no integer relation: torus closure = T^k) -------
    for tag, thetas in (("k=3 generic [0.3,1.1,2.7]", [0.3, 1.1, 2.7]),
                        ("k=4 generic [0.3,1.1,2.7,4.0]", [0.3, 1.1, 2.7, 4.0])):
        th = cs(thetas)
        b, n, dt = grid_scan(th, 30, 1.0)
        r_ref = refine(th, b[1], b[2], 0.04)
        out.append({"case": tag + " (grid LOWER bound only)",
                    "grid_max": b[0], "refined": r_ref[0],
                    "witness_xy": [r_ref[1], r_ref[2]],
                    "points": n, "sec": round(dt, 2),
                    "note": "no integer relation among u_i => closure of the image in T^k is the whole torus => sup = 1/2, attained only in the limit; the number here is a lower bound"})
        scal.append({"case": tag, "points": n, "sec": round(dt, 2)})
        print("PROGRESS: " + json.dumps({"part": "part1", "case": tag,
                                         "grid_max": round(b[0], 9),
                                         "refined": round(r_ref[0], 9)}))

    # ---- k = 4 rational directions (period lattice contains 5Z^2) ----------
    th4 = cs([math.atan2(0, 1), math.atan2(1, 0),
              math.atan2(4, 3), math.atan2(-3, 4)])
    b, n, dt = box_scan(th4, 0.0, 5.0, 0.05)
    r_ref = refine(th4, b[1], b[2], 0.02)
    out.append({"case": "k=4 rational directions (1,0),(0,1),(3,4),(4,-3) / |.| ; period 5Z^2",
                "box_max": b[0], "refined": r_ref[0],
                "witness_xy": [r_ref[1], r_ref[2]],
                "dists_at_witness": dists(th4, r_ref[1], r_ref[2]),
                "points": n, "sec": round(dt, 2),
                "note": "5Z^2 subset of the period lattice, so [0,5)^2 is a full fundamental domain; grid 0.05 then local refine"})
    scal.append({"case": "k=4 rational", "points": n, "sec": round(dt, 2)})
    print("PROGRESS: " + json.dumps({"part": "part1", "case": "k=4 rational",
                                     "box_max": round(b[0], 9),
                                     "refined": round(r_ref[0], 9)}))

    scal.append({"case": "part1 total", "points": sum(s["points"] for s in scal),
                 "sec": round(time.time() - t_start, 2)})
    bound = ("search box: rational points p=(a/q,b/q), 1<=q<=Q, |a|,|b|<=qR (Q,R as listed per case); "
             "for the k=4 rational set the box [0,5)^2 is a full fundamental domain (5Z^2 in the period lattice). "
             "Exact witnesses are verified by direct evaluation of all k distances. "
             "Generic (relation-free) sets: sup = 1/2 is a density statement, the grid figure is only a lower bound.")
    strategy = ("exact 2x2 linear solve for the target (= 1/2 for k<=2, = 1/3 for the equilateral k=3) "
                "+ rational/Farey grid enumeration + deterministic local hill-climb refinement")
    emit("supports", bound, strategy, scal, out)


def part2():
    eps_list = [0.1, 0.05]
    pool = [(1, 0), (0, 1), (3, 4), (4, 3), (-3, 4), (4, -3)]
    pool_ang = [math.atan2(v[1], v[0]) for v in pool]
    pool_cs = cs(pool_ang)
    rows = []
    scal = []
    t_start = time.time()

    for k in range(2, 7):
        best = None
        tried = 0
        tot_pts = 0
        t0 = time.time()
        for idx in combinations(range(len(pool)), k):
            sub = [pool_cs[i] for i in idx]
            b, n, _ = box_scan(sub, 0.0, 5.0, 0.1)
            r = refine(sub, b[1], b[2], 0.05)
            tried += 1
            tot_pts += n
            if best is None or r[0] < best[0][0]:
                best = (r, idx)
        r, idx = best
        sub = [pool_cs[i] for i in idx]
        dt = time.time() - t0
        row = {"k": k,
               "best_r": round(r[0], 6),
               "vectors": [list(pool[i]) for i in idx],
               "angles_deg": [round(math.degrees(pool_ang[i]), 6) for i in idx],
               "best_witness_xy": [round(r[1], 6), round(r[2], 6)],
               "dists_at_witness": [round(d, 6) for d in dists(sub, r[1], r[2])],
               "sets_tried": tried,
               "grid_points_per_set": n,
               "sec": round(dt, 3),
               "eps_met": {str(e): bool(r[0] <= e) for e in eps_list}}
        rows.append(row)
        scal.append({"k": k, "subsets": tried, "points": tot_pts, "sec": round(dt, 3)})
        print("PROGRESS: " + json.dumps({"part": "part2", "k": k,
                                         "best_r": row["best_r"],
                                         "sec": round(dt, 3)}))

    eq_angles = [0.4, 0.4 + TWO_PI / 3.0, 0.4 + 2.0 * TWO_PI / 3.0]
    thE = cs(eq_angles)
    pE, _ = solve2(thE[0], thE[1], 1.0 / 3.0, 1.0 / 3.0)
    dE = dists(thE, pE[0], pE[1])
    ref = {"k": 3, "family": "equilateral (irrational directions)",
           "r_from_exact_witness": round(min(dE), 9),
           "dists": [round(d, 9) for d in dE],
           "angles_deg": [round(math.degrees(a), 6) for a in eq_angles],
           "witness_xy": [pE[0], pE[1]]}
    print("PROGRESS: " + json.dumps({"part": "part2", "case": "equilateral reference",
                                     "r": ref["r_from_exact_witness"]}))

    found = [r for r in rows if r["best_r"] <= min(eps_list)]
    scal.append({"case": "part2 total", "subsets": sum(s["subsets"] for s in scal),
                 "sec": round(time.time() - t_start, 2)})
    bound = ("angle pool = {(1,0),(0,1),(3,4),(4,3),(-3,4),(4,-3)} (rational directions, |v| in {1,5}); "
             "ALL subsets of size k=2..6 enumerated; for each subset the period lattice contains 5Z^2, "
             "so the box [0,5)^2 is a full fundamental domain, scanned on a 0.1 grid then locally refined "
             "(step halving to 1e-14).  Plus the irrational equilateral k=3 set as reference.  "
             "NOT covered: angle sets outside this pool (so 'minimal k' is undetermined, not disproved).")
    strategy = "exhaustive subset enumeration over a rational direction pool + fundamental-domain box grid + deterministic local refinement"
    emit("inconclusive", bound, strategy, scal,
         {"per_k": rows, "equilateral_reference": ref,
          "min_r_by_k": {str(r["k"]): r["best_r"] for r in rows},
          "any_set_with_r_le_eps": bool(found),
          "eps_list": eps_list})


def part3():
    eps = 0.1
    cases = []

    # (A) k=2, independent normals: p with p.u1 = p.u2 = 1/2
    thA = cs([0.3, 0.55])
    pA, detA = solve2(thA[0], thA[1], 0.5, 0.5)
    cases.append({"angles_deg": [round(math.degrees(0.3), 6), round(math.degrees(0.55), 6)],
                  "k": 2, "det": detA, "witness_xy": [pA[0], pA[1]],
                  "dists": dists(thA, pA[0], pA[1])})

    # (B) k=3 equilateral: p with p.u1 = p.u2 = 1/3, third forced to 1/3
    eq_angles = [0.4, 0.4 + TWO_PI / 3.0, 0.4 + 2.0 * TWO_PI / 3.0]
    thB = cs(eq_angles)
    pB, detB = solve2(thB[0], thB[1], 1.0 / 3.0, 1.0 / 3.0)
    cases.append({"angles_deg": [round(math.degrees(a), 6) for a in eq_angles],
                  "k": 3, "det": detB, "witness_xy": [pB[0], pB[1]],
                  "dists": dists(thB, pB[0], pB[1])})

    # (C) k=6 = whole rational pool: best (largest) escape found by grid+refine
    pool = [(1, 0), (0, 1), (3, 4), (4, 3), (-3, 4), (4, -3)]
    thC = cs([math.atan2(v[1], v[0]) for v in pool])
    b, n, dt = box_scan(thC, 0.0, 5.0, 0.05)
    rC = refine(thC, b[1], b[2], 0.02)
    cases.append({"angles_deg": [round(math.degrees(math.atan2(v[1], v[0])), 6) for v in pool],
                  "k": 6, "witness_xy": [rC[1], rC[2]],
                  "dists": dists(thC, rC[1], rC[2]),
                  "grid_points": n})

    Q = 10 ** 6
    best = None
    for c in cases:
        ds = c["dists"]
        x, y = c["witness_xy"]
        a = int(round(x * Q))
        bq = int(round(y * Q))
        c["min_dist"] = min(ds)
        c["all_gt_eps_0.1"] = bool(min(ds) > 0.1)
        c["all_gt_eps_0.05"] = bool(min(ds) > 0.05)
        c["rational_witness"] = {"a": a, "b": bq, "q": Q,
                                 "x": a / Q, "y": bq / Q}
        c["rational_witness_dists"] = None
        if best is None or min(ds) > best[0]:
            best = (min(ds), c)

    # re-verify the winner at the rounded rational point (deterministic evaluation)
    win = best[1]
    if win["k"] == 3:
        thw = cs([math.radians(g) for g in win["angles_deg"]])
    elif win["k"] == 2:
        thw = cs([math.radians(g) for g in win["angles_deg"]])
    else:
        thw = cs([math.radians(g) for g in win["angles_deg"]])
    rw = win["rational_witness"]
    dw = dists(thw, rw["x"], rw["y"])
    win["rational_witness_dists"] = dw
    win["rational_min_dist"] = min(dw)

    for c in cases:
        print("PROGRESS: " + json.dumps({"part": "part3", "k": c["k"],
                                         "min_dist": round(c["min_dist"], 6),
                                         "gt_eps_0.1": c["all_gt_eps_0.1"]}))

    counter = {"angles_deg": win["angles_deg"], "k": win["k"], "eps": 0.1,
               "point_xy": win["rational_witness"],
               "dists": [round(d, 9) for d in win["rational_witness_dists"]],
               "min_dist": round(win["rational_min_dist"], 9),
               "statement": "all |p.u_i - nearest integer| > 0.1 at this (x,y)"}

    scal = [{"case": "k=%d" % c["k"], "points": c.get("grid_points", 0)} for c in cases]
    scal.append({"case": "total_sec", "sec": round(dt, 2)})
    bound = ("witnesses are explicit points in R^2 (also rounded to a/q,b/q with q=1e6 and re-evaluated); "
             "each claim 'all dists > eps' is checked by direct evaluation of every i. "
             "k=2,k=3 witnesses come from exact 2x2 solves (target 1/2 resp. 1/3); "
             "k=6 witness comes from a 0.05 grid on the fundamental domain [0,5)^2 + local refinement.")
    strategy = "exact 2x2 linear solve (k=2,3) and fundamental-domain grid + local refinement (k=6), then rounding to a rational point and re-verification"
    data = {"cases": cases, "eps_checked": [0.1, 0.05]}
    emit("refutes", bound, strategy, scal, data, {"counterexample": counter})


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "part1"
    if mode == "part1":
        part1()
    elif mode == "part2":
        part2()
    elif mode == "part3":
        part3()
    else:
        emit("inconclusive", "unknown mode", "none", {}, {"argv": sys.argv})
