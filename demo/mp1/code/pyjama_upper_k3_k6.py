"""pyjama_upper_k3_k6.py -- densified integer-relation construction, k = 3..6.

Task (2) and (3) of the Pyjama covering-radius job.  Every number printed here is
computed by this file; no model judges any number.

Setting
    Theta = {u_1,...,u_k} unit normals,  r(Theta) = sup_{p in R^2} f(p),
    f(p) = min_i dist(p . u_i, Z),       dist(t,Z) = |t - round(t)|.

Construction class (as in exp:000012 / code/pyjama_r3_partC.py, densified here)
    closed k-gon with INTEGER side lengths n_i in 1..5, realised as a direction set
    u_i with sum_i n_i u_i = 0; the k directions are required to stay DISTINCT
    modulo pi (dist(p.u,Z) = dist(p.(-u),Z), so only lines matter and a repeated
    line is not an extra direction); gcd(n_1..n_k) = 1; polygon inequality.
    Sampling uses the deterministic-seed two-circle closure of exp:000012 (SEED).

Certified two-sided reading for one angle set
    w is a GENUINE period of f iff w.u_i is an integer for EVERY i.  Candidates
    w = a*w1_dual + b*w2_dual with |a|,|b| <= MM are CHECKED against all k
    directions to 1e-10 (this check is exactly what exp:000012 did not do: there
    only the two basis directions were made integral by construction).
    With two independent genuine periods: grid N x N on the fundamental
    parallelogram, L = max f over the grid + deterministic 8-direction hill climb,
        r_lb      = climbed value                      (point evaluation => LB),
        r_ub_safe = L + 0.5*max(|hx*w1hat + hy*w2hat|, |hx*w1hat - hy*w2hat|)
    (half the longest cell diagonal; f is 1-Lipschitz).  No genuine period lattice
    inside the search box  =>  r_ub_safe = 0.5 (trivial: dist <= 1/2 always),
    flagged upper_bound_mode = "trivial_1/2".

Also reported, and NOT used as an upper bound: the exp:000012 quantity
    r_ub_exp12_style = L_dual + 0.5*(hx + hy)
    on the parallelogram spanned by the dual basis of (u_1,u_2), even when that
    parallelogram is not a fundamental domain of f
    (see per-candidate dual_basis_check.dual_basis_is_genuine_period).

Task (3): with the best certified r_ub_safe per k in 3..6, report the smallest k
with r_ub_safe <= eps for eps in {0.1, 0.05} and contrast with 1/(2*eps) = 5, 10.
Verdict rule (deterministic, printed): "refutes" only with an exhibited angle set
(min k found strictly below 1/(2eps)); "supports" iff min k found == 1/(2eps);
otherwise "inconclusive" with the searched range stated (a bounded search cannot
refute the existence of a family outside this class).

Output: one 'PROGRESS: {...}' line per k and exactly one 'REPRO_RESULT: {...}' line.
"""

import json
import math
import random
import time
from itertools import product

import numpy as np

SEED = 20261019
K_LIST = [3, 4, 5, 6]
COEF_MAX = 5
NSAMP_COARSE = 1
NSAMP_FINE = 4
N_COARSE = 40
N_FINE = 200
TOP = 24
MM = 24
PTOL = 1e-10
EPSL = (0.1, 0.05)
EIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def fmin(us, x, y):
    m = 1.0
    for ux, uy in us:
        t = x * ux + y * uy
        d = abs(t - math.floor(t + 0.5))
        if d < m:
            m = d
    return m


def fvec(us, X, Y):
    acc = None
    for ux, uy in us:
        t = X * ux + Y * uy
        d = np.abs(t - np.round(t))
        acc = d if acc is None else np.minimum(acc, d)
    return acc


def climb(us, x0, y0, h0, iters=300):
    best, bx, by = fmin(us, x0, y0), x0, y0
    step = h0
    for _ in range(iters):
        moved = False
        for dx, dy in EIGHT:
            v = fmin(us, bx + step * dx, by + step * dy)
            if v > best + 1e-16:
                best, bx, by = v, bx + step * dx, by + step * dy
                moved = True
        if not moved:
            step *= 0.5
            if step < 1e-13:
                break
    return best, bx, by


def sample_polygon(sides, rng, max_try=120):
    """Closed k-gon with side lengths sides[]; directions of the counted edges."""
    k = len(sides)
    a, b = sides[-2], sides[-1]
    for _ in range(max_try):
        ang = [rng.uniform(0.0, 2.0 * math.pi) for _ in range(k - 2)]
        S = np.zeros(2)
        for i in range(k - 2):
            S -= sides[i] * np.array([math.cos(ang[i]), math.sin(ang[i])])
        d = float(np.linalg.norm(S))
        if d < 1e-12:
            continue
        if d > a + b or d < abs(a - b):
            continue
        cosal = (a * a + d * d - b * b) / (2.0 * a * d)
        cosal = max(-1.0, min(1.0, cosal))
        al = math.acos(cosal)
        psi = math.atan2(S[1], S[0])
        for sgn in (1.0, -1.0):
            ua = psi + sgn * al
            u = np.array([math.cos(ua), math.sin(ua)])
            v = (S - a * u) / b
            if abs(float(np.linalg.norm(v)) - 1.0) < 1e-9:
                ang2 = ang + [ua, math.atan2(v[1], v[0])]
                return [x % (2.0 * math.pi) for x in ang2]
    return None


def lines_mod_pi(ang):
    out = []
    for a in ang:
        a = a % math.pi
        if all(min(abs(a - b), math.pi - abs(a - b)) > 1e-9 for b in out):
            out.append(a)
    return sorted(out)


def uset(lines):
    return [(math.cos(a), math.sin(a)) for a in lines]


def dual_basis(us):
    """w1,w2 with w1.u1 = 1, w1.u2 = 0, w2.u1 = 0, w2.u2 = 1 (periods only for i<=2)."""
    (c1, s1), (c2, s2) = us[0], us[1]
    det = c1 * s2 - s1 * c2
    if abs(det) < 1e-12:
        return None
    return np.array([s2, -c2]) / det, np.array([-s1, c1]) / det


def find_periods(us, M=MM, tol=PTOL):
    """All p = a*w1 + b*w2, |a|,|b| <= M, with p.u_i integral for EVERY i."""
    db = dual_basis(us)
    if db is None:
        return []
    w1, w2 = db
    out = []
    for a in range(-M, M + 1):
        for b in range(-M, M + 1):
            if a == 0 and b == 0:
                continue
            p0 = a * w1[0] + b * w2[0]
            p1 = a * w1[1] + b * w2[1]
            worst = 0.0
            for ux, uy in us:
                v = p0 * ux + p1 * uy
                worst = max(worst, abs(v - round(v)))
                if worst > tol:
                    break
            if worst <= tol:
                out.append((float(p0), float(p1), float(math.hypot(p0, p1))))
    out.sort(key=lambda r: r[2])
    return out


def two_independent(per):
    if not per:
        return None
    b1 = np.array(per[0][:2])
    for r in per[1:]:
        b2 = np.array(r[:2])
        if abs(b1[0] * b2[1] - b1[1] * b2[0]) > 1e-9:
            return b1, b2
    return None


def grid_max_on(us, w1, w2, N):
    s = np.arange(N) / float(N)
    X = s[:, None] * w1[0] + s[None, :] * w2[0]
    Y = s[:, None] * w1[1] + s[None, :] * w2[1]
    vals = fvec(us, X, Y)
    L = float(vals.max())
    j = int(np.argmax(vals))
    ii, jj = divmod(j, N)
    return L, float(X[ii, jj]), float(Y[ii, jj]), int(X.size)


def cell_cover_radius(w1, w2, N):
    n1 = float(math.hypot(w1[0], w1[1]))
    n2 = float(math.hypot(w2[0], w2[1]))
    hx, hy = n1 / N, n2 / N
    e1 = np.array(w1, dtype=float) / n1
    e2 = np.array(w2, dtype=float) / n2
    d1 = float(math.hypot(hx * e1[0] + hy * e2[0], hx * e1[1] + hy * e2[1]))
    d2 = float(math.hypot(hx * e1[0] - hy * e2[0], hx * e1[1] - hy * e2[1]))
    return 0.5 * max(d1, d2), hx, hy


def certified_bracket(us, w1, w2, N=N_FINE):
    L, x0, y0, npts = grid_max_on(us, w1, w2, N)
    corr, hx, hy = cell_cover_radius(w1, w2, N)
    best, bx, by = climb(us, x0, y0, max(hx, hy), iters=300)
    return {"grid_max": L, "climbed": best, "climb_xy": [bx, by],
            "grid_pts": int(npts), "correction": corr, "hx": hx, "hy": hy,
            "r_lb": max(L, best), "r_ub_safe": L + corr + 1e-12}


def dual_style_value(us, N=N_FINE):
    db = dual_basis(us)
    if db is None:
        return None
    w1, w2 = db
    L, x0, y0, npts = grid_max_on(us, w1, w2, N)
    n1 = float(math.hypot(w1[0], w1[1]))
    n2 = float(math.hypot(w2[0], w2[1]))
    hx, hy = n1 / N, n2 / N
    return {"L_dual": L, "hx": hx, "hy": hy,
            "r_ub_exp12_style": L + 0.5 * (hx + hy)}


def screen_value(us, N=N_COARSE):
    db = dual_basis(us)
    if db is None:
        return 1e9
    w1, w2 = db
    L, x0, y0, npts = grid_max_on(us, w1, w2, N)
    hx = float(math.hypot(w1[0], w1[1])) / N
    hy = float(math.hypot(w2[0], w2[1])) / N
    return L + 0.5 * (hx + hy)


def weyl_witness(us, R=120.0, n=60000):
    i = np.arange(1, n + 1, dtype=float)
    x = np.mod(i * math.sqrt(2.0), 1.0)
    y = np.mod(i * math.sqrt(3.0), 1.0)
    X = (x - 0.5) * R
    Y = (y - 0.5) * R
    vals = fvec(us, X, Y)
    j = int(np.argmax(vals))
    best, bx, by = climb(us, float(X[j]), float(Y[j]), 0.5, iters=300)
    return best, [bx, by], int(n)


def main():
    t_all = time.time()
    rng = random.Random(SEED)
    data = {}
    scaling = []
    for k in K_LIST:
        t0 = time.time()
        coefs = []
        for n in product(range(1, COEF_MAX + 1), repeat=k):
            if max(n) > sum(n) - max(n):
                continue
            g = 0
            for v in n:
                g = math.gcd(g, v)
            if g != 1:
                continue
            coefs.append(n)
        screened = []
        n_scr = 0
        for n in coefs:
            for _ in range(NSAMP_COARSE):
                ang = sample_polygon(list(n), rng)
                if ang is None:
                    continue
                lines = lines_mod_pi(ang)
                if len(lines) != k:
                    continue
                us = uset(lines)
                sv = screen_value(us)
                n_scr += 1
                screened.append((sv, n))
        screened.sort(key=lambda r: r[0])
        picked, seen = [], set()
        for sv, n in screened:
            if n in seen:
                continue
            seen.add(n)
            picked.append(n)
            if len(picked) >= TOP:
                break
        best = None
        n_fine = 0
        n_cert = 0
        for n in picked:
            for _ in range(NSAMP_FINE):
                ang = sample_polygon(list(n), rng)
                if ang is None:
                    continue
                lines = lines_mod_pi(ang)
                if len(lines) != k:
                    continue
                us = uset(lines)
                n_fine += 1
                per = find_periods(us)
                tri = two_independent(per) if per else None
                cand = {"relation_side_lengths": list(n),
                        "theta_rad": [round(a, 12) for a in lines],
                        "theta_deg": [round(math.degrees(a), 6) for a in lines],
                        "n_dirs_distinct": k,
                        "n_genuine_periods_in_box": len(per)}
                db = dual_basis(us)
                if db is not None:
                    worst = 0.0
                    for ux, uy in us:
                        v = db[0][0] * ux + db[0][1] * uy
                        worst = max(worst, abs(v - round(v)))
                        v = db[1][0] * ux + db[1][1] * uy
                        worst = max(worst, abs(v - round(v)))
                    cand["dual_basis_check"] = {
                        "w1": [float(db[0][0]), float(db[0][1])],
                        "w2": [float(db[1][0]), float(db[1][1])],
                        "max_residual_all_dirs": worst,
                        "dual_basis_is_genuine_period": bool(worst <= 1e-9)}
                if tri is not None:
                    w1, w2 = tri
                    br = certified_bracket(us, w1, w2)
                    cand.update({"upper_bound_mode": "period_lattice",
                                 "period_basis": [[float(w1[0]), float(w1[1])],
                                                  [float(w2[0]), float(w2[1])]],
                                 "r_lb": br["r_lb"], "r_ub_safe": br["r_ub_safe"],
                                 "grid_max": br["grid_max"], "grid_pts": br["grid_pts"],
                                 "correction": br["correction"],
                                 "witness_xy": br["climb_xy"]})
                    n_cert += 1
                else:
                    wv, wxy, npts = weyl_witness(us)
                    cand.update({"upper_bound_mode": "trivial_1/2",
                                 "r_lb": wv, "r_ub_safe": 0.5,
                                 "witness_xy": wxy, "witness_scan_pts": npts})
                ds = dual_style_value(us)
                if ds is not None:
                    cand["r_ub_exp12_style_not_certified"] = ds["r_ub_exp12_style"]
                if best is None:
                    best = cand
                else:
                    kn = (0 if cand["upper_bound_mode"] == "period_lattice" else 1,
                          cand["r_ub_safe"], -cand["r_lb"])
                    ko = (0 if best["upper_bound_mode"] == "period_lattice" else 1,
                          best["r_ub_safe"], -best["r_lb"])
                    if kn < ko:
                        best = cand
        best["k_times_r_ub_safe"] = k * best["r_ub_safe"]
        best["ratio_2k_r_ub_safe_to_1"] = 2.0 * k * best["r_ub_safe"]
        dt = time.time() - t0
        data[str(k)] = {"k": k, "n_coef_vectors": len(coefs),
                        "n_screened_angle_sets": n_scr,
                        "n_fine_angle_sets": n_fine,
                        "n_certified_period_lattice": n_cert,
                        "best": best, "secs": round(dt, 2)}
        scaling.append({"k": k, "secs": round(dt, 2), "n_coefs": len(coefs),
                        "n_screened": n_scr, "n_fine": n_fine,
                        "n_certified": n_cert})
        print("PROGRESS: " + json.dumps({"k": k, "n_coefs": len(coefs),
                                         "n_fine": n_fine, "n_certified": n_cert,
                                         "best_ub": round(best["r_ub_safe"], 9),
                                         "best_lb": round(best["r_lb"], 9),
                                         "mode": best["upper_bound_mode"],
                                         "secs": round(dt, 2)}))

    ub = {}
    for k in K_LIST:
        b = data[str(k)]["best"]
        ub[k] = b["r_ub_safe"] if b["upper_bound_mode"] == "period_lattice" else None
    conj = {}
    refute_cex = None
    for eps in EPSL:
        target = int(math.ceil(1.0 / (2.0 * eps)))
        ks = sorted([k for k in K_LIST if ub[k] is not None and ub[k] <= eps + 1e-12])
        min_k = ks[0] if ks else None
        if min_k is not None and min_k < target:
            verdict = "refutes"
            if refute_cex is None:
                b = data[str(min_k)]["best"]
                refute_cex = {"eps": eps, "k": min_k, "one_over_2eps": target,
                              "relation_side_lengths": b["relation_side_lengths"],
                              "theta_deg": b["theta_deg"],
                              "r_lb": b["r_lb"], "r_ub_safe": b["r_ub_safe"]}
        elif min_k is not None and min_k == target:
            verdict = "supports"
        else:
            verdict = "inconclusive"
        conj[str(eps)] = {"one_over_2eps": target, "searched_k": K_LIST,
                          "certified_ub_by_k": {str(k): ub[k] for k in K_LIST},
                          "min_k_with_r_ub_le_eps": min_k, "verdict": verdict}

    all_cert = all(data[str(k)]["best"]["upper_bound_mode"] == "period_lattice"
                   for k in K_LIST)
    if refute_cex is not None:
        result = "refutes"
    elif all_cert:
        result = "supports"
    else:
        result = "inconclusive"

    bound = ('Per k: a two-sided certified bracket on a GENUINE period lattice '
             '(w.u_i integral for every i, checked to 1e-10) -- r_lb = point-evaluation '
             'lower bound (grid max + 8-direction hill climb), r_ub_safe = L + half the '
             'longest grid-cell diagonal (1-Lipschitz). Where no genuine period lattice '
             'exists in |a|,|b| <= %d, r_ub_safe = 0.5 (trivial). r_ub_exp12_style = '
             'L_dual + 0.5*(hx+hy) on the dual-basis parallelogram is reported but is '
             'NOT used as an upper bound.' % MM)
    strategy = ('coefficient enumeration n in 1..%d^k with gcd=1 and polygon inequality; '
                'coarse screen at grid N=%d on the dual-basis parallelogram; top-%d '
                'coefficient vectors re-sampled %d times and evaluated at N=%d; period '
                'lattice = integer combinations of the dual basis checked against ALL k '
                'directions; deterministic 8-direction hill climb with step halving; '
                'deterministic Weyl witness scan when no period lattice exists'
                % (COEF_MAX, N_COARSE, TOP, NSAMP_FINE, N_FINE))
    print('REPRO_RESULT: ' + json.dumps(
        {"result": result, "bound": bound, "strategy": strategy,
         "scaling": scaling, "conjecture": conj, "data": data,
         "counterexample": refute_cex,
         "elapsed_sec": round(time.time() - t_all, 2)},
        ensure_ascii=False))


if __name__ == '__main__':
    main()
