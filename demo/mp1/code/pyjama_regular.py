"""pyjama_regular.py -- r(Theta) for equally spaced families of k LINES, deterministic grid.

    r(Theta) = sup_{p in R^2} min_i dist(p . u_i, Z),  u_i = (cos th_i, sin th_i),
    dist(t, Z) = |t - floor(t + 0.5)|.

Since dist(p.u, Z) = dist(p.(-u), Z), a family of k LINES is the same normal set modulo sign;
the equally spaced model family used here is  theta_i = i*pi/k, i = 0..k-1  (k lines in [0,pi)).

Claim under test (code decides, not the author):
  for every k in 3..12, the deterministic grid estimate of r for the equally spaced family
  is >= 0.1  -- i.e. inside this one family and this k-range the eps=0.1 covering does not occur.
The script computes the verdict itself and prints exactly one line

    REPRO_RESULT: {"result": ..., "bound": ..., "strategy": ..., "scaling": ..., "data": ...}

PROGRESS: one JSON line per finished k (so a timeout still leaves "how far did we get").
Sanity anchor: k=3 (equilateral as lines) must come out at 1/3 -- it is printed as a check.
"""

import json
import math
import sys
import time

TWO_PI = 2.0 * math.pi
EPS_LIST = [0.1, 0.05]
K_RANGE = list(range(3, 13))
P = 10.0        # grid box: p in [-P, P)^2
H = 0.02        # grid step (both coordinates)


def fmin(us, x, y):
    m = 1.0
    for c, s in us:
        t = x * c + y * s
        d = abs(t - math.floor(t + 0.5))
        if d < m:
            m = d
    return m


def refine(us, x0, y0, h0, iters=2000):
    """deterministic axis/diagonal hill climb with step halving."""
    best = [fmin(us, x0, y0), x0, y0]
    h = h0
    while h > 1e-14 and iters > 0:
        moved = False
        for dx, dy in ((h, 0.0), (-h, 0.0), (0.0, h), (0.0, -h),
                       (h, h), (h, -h), (-h, h), (-h, -h)):
            v = fmin(us, best[1] + dx, best[2] + dy)
            iters -= 1
            if v > best[0] + 1e-15:
                best = [v, best[1] + dx, best[2] + dy]
                moved = True
        if not moved:
            h *= 0.5
    return tuple(best)


def grid_max(us, P, h):
    """max over the regular grid [-P,P)^2 of min_i dist; returns (value, point, npoints, backend)."""
    try:
        import numpy as np
    except Exception:
        np = None
    if np is not None:
        n = int(round(2.0 * P / h))
        xs = -P + h * np.arange(n)
        X, Y = np.meshgrid(xs, xs, indexing="ij")
        M = np.full(X.shape, 1.0)
        for c, s in us:
            T = X * c + Y * s
            D = np.abs((T + 0.5) - np.floor(T + 0.5))
            M = np.minimum(M, D)
        idx = int(np.argmax(M))
        return float(M.flat[idx]), (float(X.flat[idx]), float(Y.flat[idx])), n * n, "numpy"
    best = (-1.0, 0.0, 0.0)
    n = int(round(2.0 * P / h))
    cnt = 0
    for i in range(n):
        x = -P + i * h
        for j in range(n):
            y = -P + j * h
            v = fmin(us, x, y)
            cnt += 1
            if v > best[0]:
                best = (v, x, y)
    return best[0], (best[1], best[2]), cnt, "python"


def emit(result, bound, strategy, scaling, data, extra=None):
    payload = {"result": result, "bound": bound, "strategy": strategy,
               "scaling": scaling, "data": data}
    if extra:
        payload.update(extra)
    print("REPRO_RESULT: " + json.dumps(payload, ensure_ascii=False))


def main():
    t_start = time.time()
    rows = []
    scal = []
    for k in K_RANGE:
        thetas = [i * math.pi / k for i in range(k)]
        us = [(math.cos(t), math.sin(t)) for t in thetas]
        t0 = time.time()
        g, pt, npts, backend = grid_max(us, P, H)
        rf = refine(us, pt[0], pt[1], H)
        dt = time.time() - t0
        row = {"k": k,
               "angles_deg": [round(math.degrees(t), 6) for t in thetas],
               "grid_max_unrefined": round(g, 9),
               "r_estimate": round(rf[0], 9),
               "witness_xy": [rf[1], rf[2]],
               "dists_at_witness": [round(abs((rf[1] * c + rf[2] * s)
                                              - math.floor(rf[1] * c + rf[2] * s + 0.5)), 9)
                                    for c, s in us],
               "grid_points": npts,
               "backend": backend,
               "eps_met": {str(e): bool(rf[0] <= e) for e in EPS_LIST},
               "sec": round(dt, 2)}
        rows.append(row)
        scal.append({"k": k, "points": npts, "sec": round(dt, 2)})
        print("PROGRESS: " + json.dumps({"part": "regular", "k": k,
                                         "r_estimate": row["r_estimate"],
                                         "sec": row["sec"]}))
        sys.stdout.flush()

    # sanity anchor: k=3 equally spaced lines is the equilateral set, known r = 1/3
    anchor = [r for r in rows if r["k"] == 3][0]["r_estimate"] / (1.0 / 3.0) - 1.0

    est = {str(r["k"]): r["r_estimate"] for r in rows}
    verdict_ok = all(r["r_estimate"] >= min(EPS_LIST) for r in rows)
    # the claim tested is about eps=0.1 (the larger eps); 0.05 is reported, not asserted
    claim_ge = 0.1
    verdict_ok = all(r["r_estimate"] >= claim_ge for r in rows)
    result = "supports" if verdict_ok else "inconclusive"
    best = min(rows, key=lambda r: r["r_estimate"])

    scal.append({"case": "total", "points": sum(s["points"] for s in scal),
                 "sec": round(time.time() - t_start, 2)})
    bound = ("search box p in [-P,P)^2 with P=%g, step h=%g (both coordinates, %.0f x %.0f grid points per k), "
             "then deterministic axis/diagonal hill climb with step halving down to 1e-14; "
             "angle family = equally spaced lines theta_i = i*pi/k, i=0..k-1, k in %s. "
             "r_estimate is a LOWER bound for sup (max over a finite grid); no upper bound is claimed, "
             "so 'r >= 0.1' is supported only up to the grid resolution. Scope: this ONE family only, "
             "not all angle sets; the numbering of lines is modulo sign (dist(p.u,Z)=dist(p.-u,Z))."
             % (P, H, 2 * P / H, 2 * P / H, K_RANGE))
    strategy = ("structured family (equally spaced lines) + dense deterministic grid over [-P,P)^2 "
                "+ local hill-climb refinement; numpy vectorised min-over-i when available, pure python fallback")
    data = {"per_k": rows, "r_estimate_by_k": est, "claim_threshold": claim_ge,
            "min_over_k": {"k": best["k"], "r_estimate": best["r_estimate"]},
            "k3_vs_1over3_rel_error": round(anchor, 9),
            "eps_checked": EPS_LIST}
    emit(result, bound, strategy, scal, data)


if __name__ == "__main__":
    main()
