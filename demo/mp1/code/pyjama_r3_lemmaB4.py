"""Round 3, part (2): lemma B -- no-integer-relation direction sets admit p_n with
min_i dist(p_n . u_i, Z) -> 1/2, with explicit p_n and denominators.

Deterministic method.
  k=3: the three conditions dist(p.u_i,Z) ~ 1/2 are ONE Diophantine condition on the two
  free integers (m1,m2) that pin p through directions 1,2.  With
      p = A^{-1}(1/2+m1, 1/2+m2),  A = [[c1,s1],[c2,s2]],
  the third residual is exactly  alpha*m1 + beta*m2 + gamma  (mod 1)  with
      alpha = (c3 s1 - s3 c1)/det A ,  beta = (s3 c0 - c3 s0)/det A , gamma=(alpha+beta)/2.
  We run the Euclidean/continued-fraction (Ostrowski) reduction on the pair (alpha,beta)
  with exact coefficient tracking, then represent the target t = 1/2 - gamma in that basis
  by the greedy algorithm.  All checks are done at 60 decimal digits (mpmath).
  k=4,5: the same scheme needs a 2-dim / 3-dim simultaneous Diophantine approximation
  (lattice reduction).  Here we only report deterministic box-search lower bounds over
  (m1,m2) in [-M,M]^2 for M in MS, and say honestly that no 1e-6/1e-9 certificate was
  obtained for those two sets in this round.
"""
import json, math, time
import mpmath as mp

mp.mp.dps = 60
THETA_SETS = [[0.3, 1.1, 2.7], [0.3, 1.1, 2.7, 0.71], [0.3, 1.1, 2.7, 0.71, 1.93]]
THRESH = [mp.mpf('1e-6'), mp.mpf('1e-9')]

def integer_relation_check(thetas, cmax=4):
    k = len(thetas)
    us = [(mp.cos(mp.mpf(str(t))), mp.sin(mp.mpf(str(t)))) for t in thetas]
    rel_zero, rel_int = [], []
    from itertools import product
    for n in product(range(-cmax, cmax + 1), repeat=k):
        if all(v == 0 for v in n):
            continue
        vx = sum(ni * u[0] for ni, u in zip(n, us))
        vy = sum(ni * u[1] for ni, u in zip(n, us))
        if abs(vx) < mp.mpf('1e-25') and abs(vy) < mp.mpf('1e-25'):
            rel_zero.append(list(n))
        if abs(vx - mp.nint(vx)) < mp.mpf('1e-25') and abs(vy - mp.nint(vy)) < mp.mpf('1e-25'):
            rel_int.append(list(n))
    return {"coef_max": cmax, "relations_sum_zero": rel_zero[:5],
            "n_relations_sum_zero": len(rel_zero),
            "relations_sum_integer": rel_int[:5], "n_relations_sum_integer": len(rel_int)}

def ostrowski(alpha, beta, target, tol, maxit=400):
    """Reduce the pair (alpha,beta) by the Euclidean algorithm tracking integer
    coefficients, then represent `target` greedily.  Returns integer coeffs (c1,c2)."""
    seq = [((1, 0), alpha), ((0, 1), beta)]
    a_c, a_r = (1, 0), alpha
    b_c, b_r = (0, 1), beta
    for _ in range(maxit):
        if abs(b_r) > abs(a_r):
            a_c, a_r, b_c, b_r = b_c, b_r, a_c, a_r
        if abs(b_r) < tol or abs(b_r) < mp.mpf('1e-55'):
            break
        k = int(mp.nint(a_r / b_r))
        if k == 0:
            k = 1
        n_r = a_r - k * b_r
        n_c = (a_c[0] - k * b_c[0], a_c[1] - k * b_c[1])
        seq.append((n_c, n_r))
        a_c, a_r = n_c, n_r
        if abs(n_r) < tol:
            break
    rem = target
    c = (0, 0)
    for cc, r in seq:
        if abs(r) < mp.mpf('1e-55'):
            continue
        k = int(mp.nint(rem / r))
        if k:
            rem -= k * r
            c = (c[0] + k * cc[0], c[1] + k * cc[1])
    return c, rem

def p_from_m(m1, m2, c, s):
    det = c[0] * s[1] - c[1] * s[0]
    v1 = mp.mpf('0.5') + m1
    v2 = mp.mpf('0.5') + m2
    x = (s[1] * v1 - s[0] * v2) / det
    y = (-c[1] * v1 + c[0] * v2) / det
    return x, y

def min_dist(p, c, s):
    vals = [abs(c[i] * p[0] + s[i] * p[1] - mp.nint(c[i] * p[0] + s[i] * p[1])) for i in range(len(c))]
    return min(vals)

def frac_q(x, qmax):
    from fractions import Fraction
    f = Fraction(float(x)).limit_denominator(qmax)
    return {"frac": f"{f.numerator}/{f.denominator}", "den": int(f.denominator)}

def main():
    t_all = time.time()
    out = {}
    scaling = {}
    for thetas in THETA_SETS:
        k = len(thetas)
        key = str(k)
        t0 = time.time()
        rel = integer_relation_check(thetas)
        c = [mp.cos(mp.mpf(str(t))) for t in thetas]
        s = [mp.sin(mp.mpf(str(t))) for t in thetas]
        entry = {"theta": thetas, "integer_relation": rel}
        if k == 3:
            det = c[0] * s[1] - c[1] * s[0]
            alpha = (c[2] * s[1] - s[2] * c[1]) / det
            beta = (s[2] * c[0] - c[2] * s[0]) / det
            gamma = (alpha + beta) / 2
            target = mp.mpf('0.5') - gamma
            target = target - mp.nint(target)
            entry["linear_form"] = {"alpha": mp.nstr(alpha, 25), "beta": mp.nstr(beta, 25),
                                    "gamma": mp.nstr(gamma, 25), "target": mp.nstr(target, 25)}
            hits = {}
            for tol in THRESH:
                cc, rem = ostrowski(alpha, beta, target, tol)
                m1, m2 = cc
                p = p_from_m(m1, m2, c, s)
                md = min_dist(p, c, s)
                gap = mp.mpf('0.5') - md
                rec = {"m": [int(m1), int(m2)], "abs_m_inf": int(max(abs(m1), abs(m2))),
                       "residual_mod1": mp.nstr(rem, 12),
                       "p_x": mp.nstr(p[0], 30), "p_y": mp.nstr(p[1], 30),
                       "min_dist": mp.nstr(md, 30), "gap_to_half": mp.nstr(gap, 12),
                       "reached": bool(gap < tol),
                       "x_den": frac_q(p[0], 10**12), "y_den": frac_q(p[1], 10**12)}
                hits[mp.nstr(tol, 3)] = rec
                print("PROGRESS: " + json.dumps({"k": 3, "tol": mp.nstr(tol, 3), "gap": mp.nstr(gap, 6),
                      "abs_m": rec["abs_m_inf"], "n_hits": sum(1 for v in hits.values() if v["reached"])}), flush=True)
            entry["hits"] = hits
            entry["n_thresholds_reached"] = sum(1 for v in hits.values() if v["reached"])
        else:
            import numpy as np
            cd = np.array([float(x) for x in c]); sd = np.array([float(x) for x in s])
            A = np.array([[cd[0], sd[0]], [cd[1], sd[1]]])
            best = None
            curve = {}
            for M in (200, 1000, 3000):
                ts = time.time()
                g = np.arange(-M, M + 1, dtype=np.float64)
                bb = None
                for chunk in range(0, len(g), 200):
                    m1 = g[chunk:chunk + 200][:, None]
                    m2 = g[None, :]
                    v1 = 0.5 + m1; v2 = 0.5 + m2
                    X = (sd[1] * v1 - sd[0] * v2) / (cd[0] * sd[1] - cd[1] * sd[0])
                    Y = (-cd[1] * v1 + cd[0] * v2) / (cd[0] * sd[1] - cd[1] * sd[0])
                    vals = np.abs(np.mod(np.outer(np.ones(1), np.zeros(1)) + 0, 1))  # placeholder
                    dists = []
                    for i in range(k):
                        z = cd[i] * X + sd[i] * Y
                        dists.append(np.abs(z - np.round(z)))
                    md = np.minimum.reduce(dists)
                    idx = np.unravel_index(int(np.argmax(md)), md.shape)
                    cand = (float(md[idx]), int(m1[idx[0], 0]), int(m2[0, idx[1]]))
                    if bb is None or cand[0] > bb[0]:
                        bb = cand
                curve[str(M)] = {"best_min_dist": bb[0], "gap_to_half": 0.5 - bb[0],
                                 "m": [bb[1], bb[2]], "secs": round(time.time() - ts, 2),
                                 "n_points": (2 * M + 1) ** 2}
                if best is None or bb[0] > best[0]:
                    best = bb
                print("PROGRESS: " + json.dumps({"k": k, "M": M, "best_min_dist": round(bb[0], 9),
                      "gap": round(0.5 - bb[0], 9), "secs": round(time.time() - ts, 2)}), flush=True)
            p = p_from_m(best[1], best[2], c, s)
            md = min_dist(p, c, s)
            entry["box_search"] = curve
            entry["best"] = {"m": [best[1], best[2]], "min_dist": mp.nstr(md, 25),
                             "gap_to_half": mp.nstr(mp.mpf('0.5') - md, 12),
                             "x_den": frac_q(p[0], 10**12), "y_den": frac_q(p[1], 10**12)}
            entry["n_thresholds_reached"] = 0
            entry["note"] = ("box search only: a 1e-6 / 1e-9 certificate for k>=4 needs a 2-dim "
                             "simultaneous Diophantine approximation (lattice reduction); not obtained here")
        entry["secs"] = round(time.time() - t0, 2)
        scaling[key] = {"secs": entry["secs"], "n_thresholds_reached": entry["n_thresholds_reached"]}
        out[key] = entry
    k3_ok = out["3"]["n_thresholds_reached"] == len(THRESH)
    result = "supports" if k3_ok else "inconclusive"
    payload = {
        "result": result,
        "bound": {"thresholds": [mp.nstr(t, 3) for t in THRESH],
                  "k3_all_thresholds_reached": bool(k3_ok),
                  "k3_gaps": {t: v["gap_to_half"] for t, v in out["3"]["hits"].items()},
                  "k4_gap_best": out["4"]["best"]["gap_to_half"],
                  "k5_gap_best": out["5"]["best"]["gap_to_half"]},
        "strategy": "k=3: Ostrowski/continued-fraction reduction of (alpha,beta) + greedy target "
                    "representation, verified at 60 dps; k=4,5: deterministic box search over "
                    "(m1,m2) in [-M,M]^2 with M in {200,1000,3000}",
        "scaling": scaling,
        "data": out,
    }
    print("REPRO_RESULT: " + json.dumps(payload), flush=True)
    print("PROGRESS: " + json.dumps({"done": True, "secs": round(time.time() - t_all, 2)}), flush=True)

if __name__ == "__main__":
    main()
