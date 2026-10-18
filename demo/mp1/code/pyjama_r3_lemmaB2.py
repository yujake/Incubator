import json, math, time
import numpy as np
from fractions import Fraction

THETA_SETS = [
    [0.3, 1.1, 2.7],
    [0.3, 1.1, 2.7, 0.71],
    [0.3, 1.1, 2.7, 0.71, 1.93],
]
M_LIST = [50, 100, 200, 400, 800, 1200]


def integer_relation_check(thetas, coef_max=4):
    k = len(thetas)
    us = [(math.cos(t), math.sin(t)) for t in thetas]
    found = []

    def rec(i, cur):
        if i == k:
            if all(v == 0 for v in cur):
                return
            sx = sum(n * u[0] for n, u in zip(cur, us))
            sy = sum(n * u[1] for n, u in zip(cur, us))
            if math.hypot(sx, sy) < 1e-12:
                found.append(list(cur))
            return
        for n in range(-coef_max, coef_max + 1):
            cur.append(n)
            rec(i + 1, cur)
            cur.pop()

    rec(0, [])
    return found


def search(thetas, M):
    """Enumerate integer pairs (m0,m1) in [-M,M]^2, solve the 2x2 system from
    directions 0 and 1 exactly, then measure min_i dist; keep the best point."""
    k = len(thetas)
    c = np.array([math.cos(t) for t in thetas])
    s = np.array([math.sin(t) for t in thetas])
    det = c[0] * s[1] - c[1] * s[0]
    best = -1.0
    rec = None
    grid = np.arange(-M, M + 1, dtype=float)
    for m0 in grid:
        m1v = grid
        r1 = 0.5 + m0
        r2 = 0.5 + m1v
        x = (r1 * s[1] - r2 * s[0]) / det
        y = (c[0] * r2 - c[1] * r1) / det
        md = None
        for i in range(k):
            v = x * c[i] + y * s[i]
            d = np.abs(v - np.round(v))
            md = d if md is None else np.minimum(md, d)
        j = int(np.argmax(md))
        if float(md[j]) > best:
            best = float(md[j])
            rec = (float(x[j]), float(y[j]), int(m0), int(m1v[j]))
    return best, rec


def fit_exponent(Ms, gaps):
    pts = [(math.log(m), math.log(g)) for m, g in zip(Ms, gaps) if g > 0]
    if len(pts) < 2:
        return None
    n = len(pts)
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxx = sum(p[0] ** 2 for p in pts); sxy = sum(p[0] * p[1] for p in pts)
    den = n * sxx - sx * sx
    if abs(den) < 1e-15:
        return None
    return (n * sxy - sx * sy) / den


t0 = time.time()
out = []
all_ok = True
for thetas in THETA_SETS:
    k = len(thetas)
    rels = integer_relation_check(thetas)
    curve = []
    best_overall = -1.0
    best_rec = None
    per_M = {}
    for M in M_LIST:
        val, rec = search(thetas, M)
        per_M[M] = {"best_min_dist": val, "p": [rec[0], rec[1]], "m": [rec[2], rec[3]],
                    "gap_to_half": 0.5 - val}
        curve.append((M, 0.5 - val))
        if val > best_overall:
            best_overall, best_rec = val, rec
    qx = Fraction(best_rec[0]).limit_denominator(10 ** 7).denominator
    qy = Fraction(best_rec[1]).limit_denominator(10 ** 7).denominator
    alpha = fit_exponent([m for m, g in curve], [g for m, g in curve])
    reached_1e6 = (0.5 - best_overall) < 1e-6
    reached_1e9 = (0.5 - best_overall) < 1e-9
    out.append({
        "k": k, "theta": thetas,
        "integer_relations_coef_max4": rels,
        "no_integer_relation": len(rels) == 0,
        "best_min_dist": best_overall,
        "gap_to_half": 0.5 - best_overall,
        "best_p": [best_rec[0], best_rec[1]],
        "p_denominators_rational_reconstruction": [qx, qy],
        "reached_0.5-1e-6_by_M<=%d" % M_LIST[-1]: reached_1e6,
        "reached_0.5-1e-9_by_M<=%d" % M_LIST[-1]: reached_1e9,
        "fitted_exponent_alpha": alpha,
        "predicted_2_over_kminus2": 2.0 / (k - 2),
        "curve_M_vs_gap": per_M,
    })
    if not reached_1e6:
        all_ok = False

result = "supports" if all_ok else "inconclusive"
rr = {
    "result": result,
    "bound": {"M_max": M_LIST[-1], "thresholds": [0.5 - 1e-6, 0.5 - 1e-9],
              "best_min_dist": [o["best_min_dist"] for o in out],
              "reached_1e-9": [o["reached_0.5-1e-9_by_M<=1200"] for o in out]},
    "strategy": "incremental+pruning: exact 2x2 solve from directions 0,1 over integer box |m|<=M (row-chunked numpy); best min_i dist tracked per M; exponent fitted on log(0.5-best) vs log M",
    "scaling": {"M_list": M_LIST,
                "gap_curves": [[o["curve_M_vs_gap"][str(M)]["gap_to_half"] for M in M_LIST] for o in out],
                "fitted_alpha": [o["fitted_exponent_alpha"] for o in out],
                "note": "cost = (2M+1)^2 points per (k,M); hitting a (k-2)-dim target box gives gap ~ M^{-2/(k-2)}, so 0.5-1e-9 needs M~3e4 for k=3 ((2M+1)^2 ~ 4e9 points) and is out of budget here; k=4,5 need even larger M"},
    "data": out,
    "runtime_sec": round(time.time() - t0, 3),
}
print("REPRO_RESULT: " + json.dumps(rr))
