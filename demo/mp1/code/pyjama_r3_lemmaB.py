import json, math, time
import numpy as np
from fractions import Fraction

THETA_SETS = [
    [0.3, 1.1, 2.7],
    [0.3, 1.1, 2.7, 0.71],
    [0.3, 1.1, 2.7, 0.71, 1.93],
]

def integer_relation_check(thetas, coef_max=4, tol=1e-9):
    """Brute force integer relation detection: sum n_i u_i = 0 with |n_i|<=coef_max."""
    k = len(thetas)
    us = [(math.cos(t), math.sin(t)) for t in thetas]
    best = None
    ranges = [range(-coef_max, coef_max + 1)] * k
    found = []
    def rec(i, cur):
        nonlocal best
        if i == k:
            if all(n == 0 for n in cur):
                return
            if cur and any(cur[0] != 0 for _ in [0]):
                pass
            vx = sum(cur[j] * us[j][0] for j in range(k))
            vy = sum(cur[j] * us[j][1] for j in range(k))
            nrm = math.hypot(vx, vy)
            if best is None or nrm < best[0]:
                best = (nrm, list(cur))
            if nrm < tol:
                found.append((nrm, list(cur)))
            return
        for n in ranges[i]:
            cur.append(n)
            rec(i + 1, cur)
            cur.pop()
    rec(0, [])
    return best, found[:3]

def best_over_M(thetas, M):
    c = np.cos(np.array(thetas)); s = np.sin(np.array(thetas))
    k = len(thetas)
    if k < 2:
        return None
    m = np.arange(-M, M + 1, dtype=float)
    M1, M2 = np.meshgrid(m, m, indexing='ij')
    b1 = 0.5 + M1
    b2 = 0.5 + M2
    det = c[0] * s[1] - c[1] * s[0]
    x = (b1 * s[1] - b2 * s[0]) / det
    y = (c[0] * b2 - c[1] * b1) / det
    vals = np.ones(M1.shape)
    for i in range(k):
        d = x * c[i] + y * s[i]
        d = np.abs(d - np.round(d))
        vals = np.minimum(vals, d)
    idx = int(np.argmax(vals))
    return {
        "min_dist": float(vals.flat[idx]),
        "x": float(x.flat[idx]),
        "y": float(y.flat[idx]),
        "m1": int(round(M1.flat[idx])),
        "m2": int(round(M2.flat[idx])),
    }

def denom(v, cap=10 ** 9):
    try:
        return Fraction(v).limit_denominator(cap).denominator
    except Exception:
        return None

data = {"theta_sets": [], "scaling": []}
overall_ok = True
t_start = time.time()

for th in THETA_SETS:
    entry = {"theta": th, "k": len(th)}
    t0 = time.time()
    best, found = integer_relation_check(th, coef_max=4, tol=1e-9)
    entry["integer_relation_best_coeff"] = best[1]
    entry["integer_relation_best_norm"] = best[0]
    entry["integer_relations_found_within_coef4"] = len(found)
    entry["no_integer_relation_up_to_coef4"] = (len(found) == 0)
    # sweep M
    sweep = []
    reached_1e6 = None
    reached_1e9 = None
    for M in [5, 20, 50, 100, 200, 400]:
        ts = time.time()
        b = best_over_M(th, M)
        dt = time.time() - ts
        row = {"M": M, "min_dist": b["min_dist"], "m1": b["m1"], "m2": b["m2"],
               "p_x": b["x"], "p_y": b["y"], "secs": round(dt, 3)}
        if reached_1e6 is None and b["min_dist"] >= 0.5 - 1e-6:
            reached_1e6 = dict(row)
        if reached_1e9 is None and b["min_dist"] >= 0.5 - 1e-9:
            reached_1e9 = dict(row)
        sweep.append(row)
        data["scaling"].append({"k": len(th), "M": M, "secs": round(dt, 3),
                                "objects": (2 * M + 1) ** 2})
    entry["sweep"] = sweep
    if reached_1e6 is None:
        overall_ok = False
        entry["reached_0.5-1e-6"] = None
        entry["status_1e6"] = "not_reached_within_M<=400"
    else:
        reached_1e6["denominator_x"] = denom(reached_1e6["p_x"])
        reached_1e6["denominator_y"] = denom(reached_1e6["p_y"])
        entry["reached_0.5-1e-6"] = reached_1e6
    if reached_1e9 is None:
        entry["reached_0.5-1e-9"] = None
        entry["status_1e9"] = "not_reached_within_M<=400"
    else:
        reached_1e9["denominator_x"] = denom(reached_1e9["p_x"])
        reached_1e9["denominator_y"] = denom(reached_1e9["p_y"])
        entry["reached_0.5-1e-9"] = reached_1e9
    entry["best_min_dist_over_all_M"] = max(r["min_dist"] for r in sweep)
    entry["secs_total"] = round(time.time() - t0, 3)
    data["theta_sets"].append(entry)

data["total_secs"] = round(time.time() - t_start, 3)
data["note"] = ("p=(x,y) with m_i integers: x,y solved from directions 1,2 exactly via "
                "[[c1,s1],[c2,s2]]^{-1}(1/2+m1,1/2+m2); min_i dist(x c_i + y s_i, Z) is then "
                "evaluated for all i, and the max over the (m1,m2) box of |m|<=M is reported. "
                "Denominators are continued-fraction limit_denominator(1e9) of x,y.")

result = "supports" if overall_ok else "inconclusive"
repro = {
    "result": result,
    "bound": {"max_M": 400,
              "thresholds": [0.5 - 1e-6, 0.5 - 1e-9],
              "best_min_dist": [e["best_min_dist_over_all_M"] for e in data["theta_sets"]]},
    "strategy": "incremental+pruning: exact 2x2 solve over integer residue box |m_i|<=M, "
                "vectorized numpy; integer-relation detection by coefficient brute force |n_i|<=4",
    "scaling": data["scaling"],
    "data": data,
}
print("REPRO_RESULT: " + json.dumps(repro))
