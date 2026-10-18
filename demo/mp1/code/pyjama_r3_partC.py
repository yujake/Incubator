"""Round 3 part (3): search angle sets WITH an integer relation sum n_i u_i = 0 (|n_i|<=3)
for the smallest covering radius r(Theta) = sup_p min_i dist(p.u_i, Z), k = 3..10.

Method (deterministic except a fixed seed for polygon sampling):
  For each k, enumerate / sample coefficient vectors n in {1,2,3}^k.
  Each n is realised as a closed k-gon with side lengths n_i: sample directions for
  sides 1..k-2 uniformly (fixed RNG seed), then close with the last two sides by the
  two-circle intersection (feasible iff |n_{k-1}-n_k| <= |S| <= n_{k-1}+n_k).
  The edge directions u_i are the angle set; they satisfy sum n_i u_i = 0.
  r bounds: the function f(p)=min_i dist(p.u_i,Z) is periodic w.r.t. L={p: p.u_i in Z};
  grid over the fundamental parallelogram spanned by a basis w1,w2 of L:
      LB = max over grid of f,  UB = LB + 0.5*(hx+hy)   [1-Lipschitz, safe half-diagonal]
      (also report the task's form UB_task = LB + 0.5*sqrt(hx^2+hy^2))
  plus local hill climbing from the best grid point to improve LB.

Output: one line 'REPRO_RESULT: {...}' with result/bound/strategy/scaling/data,
and one 'PROGRESS: {...}' line per finished k.
"""
import json, math, random, time
import numpy as np

SEED = 20261019
NGRID = 90
NSAMP = 3

def f_vals(thetas, pts):
    best = None
    for t in thetas:
        v = pts @ np.array([math.cos(t), math.sin(t)])
        d = np.abs(v - np.round(v))
        best = d if best is None else np.minimum(best, d)
    return best

def lattice_basis(thetas):
    c1, s1 = math.cos(thetas[0]), math.sin(thetas[0])
    c2, s2 = math.cos(thetas[1]), math.sin(thetas[1])
    det = c1 * s2 - s1 * c2
    if abs(det) < 1e-10:
        return None
    w1 = np.array([s2, -c2]) / det
    w2 = np.array([-s1, c1]) / det
    return w1, w2

def r_bounds(thetas, N=NGRID, climb=True):
    basis = lattice_basis(thetas)
    if basis is None:
        return None
    w1, w2 = basis
    s = np.linspace(0.0, 1.0, N, endpoint=False)
    S, T = np.meshgrid(s, s, indexing='ij')
    pts = S.reshape(-1, 1) * w1[None, :] + T.reshape(-1, 1) * w2[None, :]
    vals = f_vals(thetas, pts)
    L = float(vals.max())
    hx = float(np.linalg.norm(w1)) / N
    hy = float(np.linalg.norm(w2)) / N
    ub_safe = L + 0.5 * (hx + hy)
    ub_task = L + 0.5 * math.hypot(hx, hy)
    fbest = L
    if climb:
        p = pts[int(vals.argmax())].copy()
        step = max(hx, hy)
        for _ in range(160):
            improved = False
            for d in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                q = p + step * np.array(d, float)
                fq = float(f_vals(thetas, q[None, :])[0])
                if fq > fbest + 1e-16:
                    p, fbest = q, fq
                    improved = True
            if not improved:
                step *= 0.5
                if step < 1e-12:
                    break
    lb = max(L, fbest)
    return {"lb": lb, "ub_safe": ub_safe, "ub_task": ub_task, "grid_lb": L, "hx": hx, "hy": hy}

def sample_polygon(sides, rng, max_try=200):
    k = len(sides)
    a, b = sides[-2], sides[-1]
    for _ in range(max_try):
        ang = [rng.uniform(0, 2 * math.pi) for _ in range(k - 2)]
        # place sides 1..k-1 (index 0..k-2) so that the sum of first k-2 plus the
        # last two closes: accumulate S = -(sum_{i<=k-2} n_i u_i)
        S = np.zeros(2)
        for i in range(k - 2):
            S -= sides[i] * np.array([math.cos(ang[i]), math.sin(ang[i])])
        d = float(np.linalg.norm(S))
        if d < 1e-12:
            continue
        if d > a + b or d < abs(a - b):
            continue
        cosal = (a * a + d * d - b * b) / (2 * a * d)
        cosal = max(-1.0, min(1.0, cosal))
        al = math.acos(cosal)
        psi = math.atan2(S[1], S[0])
        for sgn in (1.0, -1.0):
            ua = psi + sgn * al
            u = np.array([math.cos(ua), math.sin(ua)])
            v = (S - a * u) / b
            if abs(np.linalg.norm(v) - 1.0) < 1e-9:
                ang2 = ang + [ua, math.atan2(v[1], v[0])]
                return [x % (2 * math.pi) for x in ang2]
    return None

def main():
    t_all = time.time()
    rng = random.Random(SEED)
    out = {}
    scaling = {}
    for k in range(3, 11):
        t0 = time.time()
        if k <= 7:
            from itertools import product
            coefs = [c for c in product((1, 2, 3), repeat=k)]
        else:
            coefs = [tuple(rng.choice((1, 2, 3)) for _ in range(k)) for _ in range(220)]
        best = None
        n_eval = 0
        for nvec in coefs:
            if max(nvec) > sum(nvec) - max(nvec):
                continue
            for _ in range(NSAMP):
                ang = sample_polygon(list(nvec), rng)
                if ang is None:
                    continue
                rb = r_bounds(ang)
                if rb is None or "ub_safe" not in rb:
                    continue
                n_eval += 1
                if best is None or rb["ub_safe"] < best["r_ub_safe"]:
                    best = {"r_lb": rb["lb"], "r_ub_safe": rb["ub_safe"],
                            "r_ub_task": rb["ub_task"], "grid_lb": rb["grid_lb"],
                            "theta_rad": [round(x, 12) for x in ang],
                            "theta_deg": [round(math.degrees(x), 6) for x in ang],
                            "relation_side_lengths": list(nvec),
                            "relation_parity_sum": int(sum(nvec) % 2),
                            "hx": rb["hx"], "hy": rb["hy"]}
        dt = time.time() - t0
        out[k] = {"n_coef_vectors": len(coefs), "n_evaluated_angle_sets": n_eval,
                  "best": best, "vs_1_over_2k": (None if best is None else best["r_ub_safe"] * 2 * k),
                  "secs": round(dt, 2)}
        scaling[str(k)] = {"secs": round(dt, 2), "n_eval": n_eval, "grid_pts": NGRID * NGRID}
        print("PROGRESS: " + json.dumps({"k": k, "n_eval": n_eval, "secs": round(dt, 2),
              "best_r_ub_safe": (None if best is None else round(best["r_ub_safe"], 9)),
              "best_r_lb": (None if best is None else round(best["r_lb"], 9))}), flush=True)
    # ---- sanity: the 120-degree triple, whose only relation is u1+u2+u3=0 (sum 3, odd) ----
    tri = [0.0, 2 * math.pi / 3, 4 * math.pi / 3]
    sanity = r_bounds(tri, N=300)
    # ---- verdict ----
    certified = {k: v["best"] for k, v in out.items() if v["best"] and v["best"]["r_ub_safe"] < 0.5 - 1e-3}
    if certified:
        result = "supports"
    else:
        result = "inconclusive"
    mins = {str(k): (None if out[k]["best"] is None else out[k]["best"]["r_ub_safe"]) for k in out}
    payload = {
        "result": result,
        "bound": {
            "k_min_r_lb": mins,
            "certified_r_below_half_for_k": sorted(certified.keys()),
            "sanity_120deg_triple": {"lb": sanity["lb"], "ub_safe": sanity["ub_safe"],
                                     "expected_exact": 1.0 / 3.0},
            "grid_N": NGRID,
            "ub_rule": "UB = LB_grid + 0.5*(hx+hy)  (1-Lipschitz, safe); also reported UB_task = LB + 0.5*sqrt(hx^2+hy^2)"
        },
        "strategy": "integer-relation families: enumerate n in {1,2,3}^k, realise as closed k-gon with side lengths n_i (last two sides by two-circle closure), grid on fundamental parallelogram of L={p:p.u_i in Z} + local hill climbing",
        "scaling": {"per_k": scaling, "seed": SEED, "samples_per_coef_vector": NSAMP,
                    "wall_secs": round(time.time() - t_all, 2)},
        "data": {"per_k": out,
                 "reading": {"r_ranges_from_LB_to_UB": "each k: [best r_lb, best r_ub_safe] is a two-sided bracket on inf_Theta r(Theta) over the searched family"}}
    }
    print("REPRO_RESULT: " + json.dumps(payload), flush=True)

if __name__ == "__main__":
    main()
