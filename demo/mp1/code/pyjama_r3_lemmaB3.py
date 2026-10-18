"""Lemma B round 3: no-integer-relation direction sets => sup min_i dist(p.u_i,Z) -> 1/2.

Method (deterministic, no randomness):
  For a direction set theta (k directions), search integer vectors m=(m_1..m_k):
  take first two directions, solve the exact 2x2 linear system
        x c_1 + y s_1 = 1/2 + m_1
        x c_2 + y s_2 = 1/2 + m_2
  for (x,y); then score = min_i dist(x c_i + y s_i, Z).
  Enumerate (m_1,m_2) in [-M,M]^2 -> record max score over the box, plus the (x,y).
  Report: max score vs M (scaling), the first M reaching 0.5-1e-6 and 0.5-1e-9,
  and a rational reconstruction p ~ (a/q, b/q) with Fraction.limit_denominator.
Precondition: integer-relation check sum n_i u_i = 0, |n_i| <= NMAX, brute force.
"""
import json, math, time
from fractions import Fraction

THETA_SETS = [[0.3, 1.1, 2.7],
              [0.3, 1.1, 2.7, 0.71],
              [0.3, 1.1, 2.7, 0.71, 1.93]]
M_LIST = [20, 50, 100, 200, 400, 800, 1600]
NMAX = 4


def d1(t):
    return abs(t - round(t))


def int_relation(thetas, nmax=NMAX):
    k = len(thetas)
    us = [(math.cos(t), math.sin(t)) for t in thetas]
    rngs = [range(-nmax, nmax + 1)] * k
    found = []
    cur = [0] * k

    def rec(i):
        if i == k:
            if all(v == 0 for v in cur):
                return
            sx = sum(n * u[0] for n, u in zip(cur, us))
            sy = sum(n * u[1] for n, u in zip(cur, us))
            if math.hypot(sx, sy) < 1e-9:
                found.append(list(cur))
            return
        for v in rngs[i]:
            cur[i] = v
            rec(i + 1)
        cur[i] = 0
    rec(0)
    return found


def solve2(c1, s1, c2, s2, r1, r2):
    det = c1 * s2 - c2 * s1
    if abs(det) < 1e-12:
        return None
    return ((r1 * s2 - r2 * s1) / det, (c1 * r2 - c2 * r1) / det)


def score(us, x, y):
    return min(d1(x * c + y * s) for (c, s) in us)


def run_set(thetas):
    k = len(thetas)
    us = [(math.cos(t), math.sin(t)) for t in thetas]
    rels = int_relation(thetas)
    c1, s1 = us[0]
    c2, s2 = us[1]
    curve = []
    best = {"score": -1.0, "M": 0, "x": None, "y": None}
    hits = {}
    thresh = {"1e-6": 0.5 - 1e-6, "1e-9": 0.5 - 1e-9}
    for M in M_LIST:
        t0 = time.time()
        bM = (-1.0, None, None)
        for m1 in range(-M, M + 1):
            r1 = 0.5 + m1
            for m2 in range(-M, M + 1):
                sol = solve2(c1, s1, c2, s2, r1, 0.5 + m2)
                if sol is None:
                    continue
                x, y = sol
                sc = score(us, x, y)
                if sc > bM[0]:
                    bM = (sc, x, y)
        dt = time.time() - t0
        curve.append({"M": M, "n_points": (2 * M + 1) ** 2, "max_min_dist": bM[0],
                      "gap_to_half": 0.5 - bM[0], "seconds": dt})
        if bM[0] > best["score"]:
            best = {"score": bM[0], "M": M, "x": bM[1], "y": bM[2]}
        for name, tv in thresh.items():
            if name not in hits and bM[0] >= tv:
                hits[name] = {"M": M, "score": bM[0], "point": [bM[1], bM[2]],
                              "denominator_q": max(Fraction(bM[1]).limit_denominator(10 ** 6).denominator,
                                                   Fraction(bM[2]).limit_denominator(10 ** 6).denominator),
                              "rat_approx": [str(Fraction(bM[1]).limit_denominator(10 ** 6)),
                                             str(Fraction(bM[2]).limit_denominator(10 ** 6))]}
    return {"theta": thetas, "k": k, "integer_relations_found": rels,
            "dense_free": len(rels) == 0, "curve": curve,
            "best": best, "thresholds_reached": hits}


def main():
    out = [run_set(th) for th in THETA_SETS]
    done_1e6 = sum(1 for o in out if "1e-6" in o["thresholds_reached"])
    done_1e9 = sum(1 for o in out if "1e-9" in o["thresholds_reached"])
    all_free = all(o["dense_free"] for o in out)
    res = "supports" if (all_free and done_1e9 == len(out)) else "inconclusive"
    data = {"sets": out,
            "n_sets": len(out), "n_free_of_integer_relation": sum(1 for o in out if o["dense_free"]),
            "n_reaching_0.5-1e-6": done_1e6, "n_reaching_0.5-1e-9": done_1e9}
    print("REPRO_RESULT: " + json.dumps({
        "result": res,
        "bound": {"thresholds": [0.499999, 0.499999999], "n_reaching_1e-6": done_1e6,
                  "n_reaching_1e-9": done_1e9,
                  "max_M": M_LIST[-1],
                  "best_min_dist": [o["best"]["score"] for o in out]},
        "strategy": "exact 2x2 solve over integer box (m1,m2) in [-M,M]^2 + integer-relation brute force |n_i|<=%d" % NMAX,
        "scaling": {"M_list": M_LIST,
                    "points_list": [(2 * M + 1) ** 2 for M in M_LIST],
                    "seconds_per_set": [[r["seconds"] for r in o["curve"]] for o in out]},
        "data": data}, ensure_ascii=False))


if __name__ == "__main__":
    main()
