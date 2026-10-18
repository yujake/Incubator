"""pyjama_greedy_minr.py -- deterministic multi-start angle-coordinate search
that tries to MINIMISE the sampled maximum of

    f(p) = min_i dist(p . u_i, Z),   u_i = (cos th_i, sin th_i),
    dist(t, Z) = |t - round(t)|,

over angle sets Theta = (th_1,...,th_k) for k = 3,4,5,6.

Everything printed here is computed by this file.  Nothing is judged by a model.

WHAT IS REPORTED (and what it is NOT)
  For a fixed Theta,  r(Theta) = sup_p f(p)  and
      grid_max(Theta) = max_{p in BOX} f(p)  <=  r(Theta)
  is a LOWER bound on r(Theta) (the grid only samples points).  A hill-climb
  refinement starting from the grid argmax can only raise the value, so the
  refined figure is still a LOWER bound.  Therefore:
    * "r_estimate" columns are LOWER bounds on r(Theta);
    * a value < eps proves nothing (it does not certify r(Theta) < eps);
    * a value > eps DOES prove r(Theta) > eps (hence that angle set cannot
      serve as a covering set for that eps).
  The search over angle sets is a deterministic multi-start coordinate descent,
  NOT an exhaustive search of angle space: the reported "best" set is the best
  found among the listed starts, not a proven global optimum.

SELF-CHECK (decides result, in code)
  For the equilateral 3-line set {0, pi/3, 2pi/3} the exact value is r = 1/3
  (witness p with p.u_i = 1/3 for all i).  The script requires the numerical
  estimate of that set to lie in [1/3 - 1e-3, 1/3 + 1e-3].  If the self-check
  fails the script reports result="refutes" with the failing reading as the
  counterexample; it never reports success on a failed self-check.

Modes: argv[1] in {k3,k4,k5,k6,all} (default all).  No dependence on env vars.
"""

import json
import math
import sys
import time

import numpy as np

R_BOX = 8.0
H_GRID = 0.25
TOL_SELFCHECK = 1e-3


def make_box(R=R_BOX, h=H_GRID):
    n = int(round(2.0 * R / h)) + 1
    xs = np.linspace(-R, R, n)
    X, Y = np.meshgrid(xs, xs, indexing="ij")
    return np.stack([X.ravel(), Y.ravel()], axis=1), n * n


BOX, NBOX = make_box()


def fvals(thetas, P=BOX):
    U = np.stack([np.cos(thetas), np.sin(thetas)], axis=1)  # (k,2)
    T = P @ U.T                                            # (N,k)
    D = np.abs(T - np.rint(T))
    return D.min(axis=1)


def hill(thetas, x0, y0, h0=H_GRID, max_iter=400):
    """deterministic 8-direction hill climb with step halving; raises f only."""
    best_v = float(fvals(np.asarray(thetas), np.array([[x0, y0]]))[0])
    bx, by = float(x0), float(y0)
    h = float(h0)
    while h > 1e-13:
        moved = False
        offs = [(h, 0.0), (-h, 0.0), (0.0, h), (0.0, -h),
                (h, h), (h, -h), (-h, h), (-h, -h)]
        Pts = np.array([[bx + dx, by + dy] for dx, dy in offs])
        vs = fvals(np.asarray(thetas), Pts)
        j = int(np.argmax(vs))
        if float(vs[j]) > best_v + 1e-15:
            best_v = float(vs[j])
            bx, by = float(Pts[j, 0]), float(Pts[j, 1])
            moved = True
        if not moved:
            h *= 0.5
        if max_iter <= 0:
            break
        max_iter -= 1
    return best_v, bx, by


def r_estimate(thetas):
    """LOWER bound on r(Theta): max over the box grid, then hill-climb."""
    v = fvals(np.asarray(thetas))
    i = int(np.argmax(v))
    g = float(v[i])
    r, x, y = hill(thetas, BOX[i, 0], BOX[i, 1])
    return max(g, r), x, y, g


def dists_at(thetas, x, y):
    p = np.array([[x, y]])
    U = np.stack([np.cos(np.asarray(thetas)), np.sin(np.asarray(thetas))], axis=1)
    T = p @ U.T
    return [float(abs(t - round(t))) for t in T[0]]


def normalize(thetas):
    out = np.array(thetas, dtype=float) % math.pi
    return np.sort(out)


def optimize(thetas0, step0=0.05, floor=1e-4):
    th = np.array(thetas0, dtype=float)
    best_v, bx, by, _ = r_estimate(th)
    step = step0
    evals = 1
    while step > floor:
        improved = False
        for i in range(len(th)):
            for s in (+1.0, -1.0):
                cand = th.copy()
                cand[i] += s * step
                v, x, y, _ = r_estimate(cand)
                evals += 1
                if v < best_v - 1e-12:
                    best_v, bx, by, th = v, x, y, cand
                    improved = True
        if not improved:
            step *= 0.5
    return th, best_v, bx, by, evals


def starts(k):
    """deterministic start sets (no RNG): equally spaced, equilateral offsets,
    and two fixed arithmetic families."""
    s = []
    s.append(("equally_spaced", [math.pi * i / k for i in range(k)]))
    s.append(("shifted_0.3", [0.3 + math.pi * i / k for i in range(k)]))
    s.append(("golden", [(0.13 + i * 0.617) % math.pi for i in range(k)]))
    s.append(("two_clusters", [(0.05 if i % 2 == 0 else 0.9) + 0.3 * i for i in range(k)]))
    return s


def run_k(k):
    t0 = time.time()
    rows = []
    total_evals = 0
    for tag, th0 in starts(k):
        th, v, x, y, ev = optimize(th0)
        total_evals += ev
        thn = normalize(th)
        rows.append({
            "start": tag,
            "start_angles_deg": [round(math.degrees(a), 6) for a in th0],
            "best_angles_deg": [round(math.degrees(a), 6) for a in thn],
            "best_angles_rad": [float(a) for a in thn],
            "r_estimate_lower_bound": round(float(v), 9),
            "witness_xy": [round(float(x), 9), round(float(y), 9)],
            "dists_at_witness": [round(d, 9) for d in dists_at(thn, x, y)],
            "evaluations": ev,
        })
    best = min(rows, key=lambda r: r["r_estimate_lower_bound"])
    dt = time.time() - t0
    out = {
        "k": k,
        "best_over_starts": best,
        "per_start": rows,
        "grid": {"box": [-R_BOX, R_BOX, -R_BOX, R_BOX], "step": H_GRID, "points": NBOX},
        "evaluations_total": total_evals,
        "sec": round(dt, 3),
    }
    print("PROGRESS: " + json.dumps({"part": "greedy_minr", "k": k,
                                     "best_r_lower_bound": best["r_estimate_lower_bound"],
                                     "start": best["start"],
                                     "evals": total_evals,
                                     "sec": round(dt, 3)}))
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    t_start = time.time()

    # ---- self-check: equilateral k=3 must read 1/3 -------------------------
    eq = [0.4, 0.4 + 2.0 * math.pi / 3.0, 0.4 + 4.0 * math.pi / 3.0]
    eqv, eqx, eqy, eqg = r_estimate(eq)
    sc_ok = abs(eqv - 1.0 / 3.0) <= TOL_SELFCHECK
    print("PROGRESS: " + json.dumps({"part": "selfcheck_equilateral_k3",
                                     "r_estimate": round(eqv, 9),
                                     "exact": round(1.0 / 3.0, 9),
                                     "ok": bool(sc_ok)}))

    ks = {"k3": [3], "k4": [4], "k5": [5], "k6": [6]}.get(mode, [3, 4, 5, 6])
    results = [run_k(k) for k in ks]

    # ---- summary: which reported sets are CERTIFIED to exceed eps ----------
    eps_list = [0.1, 0.05]
    certified = []
    for res in results:
        b = res["best_over_starts"]
        v = b["r_estimate_lower_bound"]
        certified.append({
            "k": res["k"],
            "r_estimate_lower_bound": v,
            "angles_deg": b["best_angles_deg"],
            "certified_exceeds": {str(e): bool(v > e) for e in eps_list},
        })

    scaling = [{"k": r["k"], "points": NBOX, "evaluations": r["evaluations_total"],
                "sec": r["sec"]} for r in results]
    scaling.append({"case": "total", "points": NBOX,
                    "evaluations": sum(r["evaluations_total"] for r in results),
                    "sec": round(time.time() - t_start, 3)})

    data = {
        "selfcheck_equilateral_k3": {"r_estimate": round(eqv, 9),
                                     "exact": 1.0 / 3.0,
                                     "witness_xy": [eqx, eqy],
                                     "ok": bool(sc_ok),
                                     "tolerance": TOL_SELFCHECK},
        "per_k": results,
        "summary": certified,
        "angle_search": "deterministic multi-start coordinate descent on the k angles "
                        "(4 fixed starts, step halving 0.05 -> 1e-4, angles taken mod pi); "
                        "NOT exhaustive over angle space",
        "meaning_of_numbers": "r_estimate_lower_bound = max f over a " + str(H_GRID) +
                              "-step grid on the box [-8,8]^2, then hill-climb from that "
                              "argmax; it is a LOWER bound on r(Theta)=sup_p f(p). "
                              "LOWER bound > eps certifies r>eps; LOWER bound < eps proves "
                              "nothing about r<eps.",
    }

    if sc_ok:
        emit("supports",
             "grid box [-8,8]^2 step 0.25 (" + str(NBOX) + " points) + deterministic hill climb; "
             "self-check r(equilateral k=3) = 1/3 within 1e-3 passed; all reported r are LOWER bounds",
             "multi-start angle coordinate descent (step halving) over full-box grid maximisation",
             scaling, data)
    else:
        emit("refutes",
             "grid box [-8,8]^2 step 0.25 + hill climb; self-check on the equilateral k=3 set failed",
             "multi-start angle coordinate descent (step halving) over full-box grid maximisation",
             scaling, data,
             {"counterexample": {"what": "self-check on the equilateral k=3 set",
                                 "expected": 1.0 / 3.0,
                                 "reading": eqv,
                                 "tolerance": TOL_SELFCHECK,
                                 "all_dists_at_witness": [round(d, 9) for d in dists_at(eq, eqx, eqy)]}})


def emit(result, bound, strategy, scaling, data, extra=None):
    payload = {"result": result, "bound": bound, "strategy": strategy,
               "scaling": scaling, "data": data}
    if extra:
        payload.update(extra)
    print("REPRO_RESULT: " + json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
