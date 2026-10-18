"""E diagnostic v2 for conj000000 / plan 000000 / sg-a: corrected Monte-Carlo cross-check.

WHY THIS SCRIPT EXISTS (reading of experiments:000001)
  experiments:000001 ran the supplied executor scripts/f_conj000000_delta.py through a
  protocol wrapper. Its own convergence flag said converged=True on 7 of the 12 (k,N)
  cells, but on 3 of those 7 the estimator missed the exact count by rel_err > 0.1
  (e.g. k=2,N=8: rel_err=0.4237). The cause is in the SAMPLER, not in the count:
  the original draws a string of EXACTLY N letters uniform over 8 letters and keeps it
  iff all letters lie in A_k -- probability (k/4)^N -- but then multiplies by
  V_env(N), the number of REDUCED words of length <= N. So it estimates
  V_env * (k/4)^N, which is not V_X(k,N) = 1 + sum_l 2k(2k-1)^(l-1).
  Hence experiments:000001's "refutes" is a refutation of the supplied estimator's
  claim to cross-check the count, NOT a refutation of delta_N(X_k).

WHAT THIS SCRIPT TESTS (criterion fixed before the run)
  (A) COUNT: for k in {2,3,4} and l <= 4, the closed form #reduced words of length
      exactly l over A_k = 2k(2k-1)^(l-1) is checked against exhaustive enumeration.
      Any mismatch => refutes (with the offending (k,l) as counterexample).
  (B) CORRECTED SAMPLER: draw a reduced word over the 8-letter alphabet with length
      l distributed exactly as the reduced-word length distribution truncated at N
      (weights = the same closed forms), then test whether all letters lie in A_k.
      This is unbiased for p_exact = V_X/V_env. On every cell the script flags
      converged (rel_se <= 0.1 and hits >= 50) we require
            rel_err = |delta_hat - delta_exact| / delta_exact <= TOL = 0.1.
      Any converged cell violating it => refutes (with that cell as counterexample).
      At least one converged cell and none violating => supports.
      No converged cell => inconclusive.  A crash => inconclusive.

LIMITS carried with every number (unchanged from the original header):
  delta_0 is NOT a factor invariant; everything is defined only for the standard free
  generator tuple X_k = (u_1,...,u_k) of W*(F_k); readings are at best
  supported_not_proved; none of them is a proof.
"""

import json
import math
import random
import sys
import time

REL_SE_MAX = 0.1
H_MIN = 50
P_MAX = 1e-3
TOL = 0.1
K_VALUES = [2, 3, 4]
N_VALUES = [8, 16, 32, 64]
M_BY_N = {8: 200000, 16: 100000, 32: 100000, 64: 100000}
BRUTE_LMAX = 4

ALPHA8 = [1, -1, 2, -2, 3, -3, 4, -4]


def seed_of(k, N):
    return 100000 + 1000 * k + N


def cnt_exact(m, l):
    """#reduced words of length exactly l over an m-letter alphabet {+-1..+-(m//2)}."""
    if l == 0:
        return 1
    return m * (m - 1) ** (l - 1)


def V(m, N):
    return 1 + sum(cnt_exact(m, l) for l in range(1, N + 1))


def V_X(k, N):
    return V(2 * k, N)


def V_env(N):
    return V(8, N)


def delta_exact(k, N):
    return math.log(V_X(k, N)) / math.log(N)


def brute_count(k, l):
    """Exhaustive enumeration of reduced words of length exactly l over A_k."""
    allowed = set(range(1, k + 1)) | set(range(-k, 0))
    words = [[]]
    for _ in range(l):
        nxt = []
        for w in words:
            for s in allowed:
                if w and s == -w[-1]:
                    continue
                nxt.append(w + [s])
        words = nxt
    return len(words)


def count_selfcheck():
    rows, bad = [], []
    for k in K_VALUES:
        for l in range(0, BRUTE_LMAX + 1):
            b = brute_count(k, l)
            f = cnt_exact(2 * k, l)
            rows.append({"k": k, "l": l, "brute": b, "closed_form": f})
            if b != f:
                bad.append({"k": k, "l": l, "brute": b, "closed_form": f})
    return rows, bad


def sample_word(rng, N, k):
    """Draw length l ~ (cnt_exact(8,l))_{l<=N}, then a uniform reduced 8-letter word."""
    cum, tot = [], 0
    for l in range(0, N + 1):
        tot += cnt_exact(8, l)
        cum.append(tot)
    r = rng.randrange(tot)
    lo, hi = 0, N
    while lo < hi:  # first index with cum[idx] > r
        mid = (lo + hi) // 2
        if cum[mid] > r:
            hi = mid
        else:
            lo = mid + 1
    l = lo
    allowed = set(range(1, k + 1)) | set(range(-k, 0))
    word, prev = [], None
    for _ in range(l):
        if prev is None:
            j = rng.randrange(8)
        else:
            e = 2 * (abs(prev) - 1) + (0 if -prev > 0 else 1)  # index of -prev
            j = rng.randrange(7)
            if j >= e:
                j += 1
        s = ALPHA8[j]
        word.append(s)
        prev = s
        if s not in allowed:
            # early exit is NOT allowed here: the test is on the whole word, but
            # a single bad letter already decides; remaining letters irrelevant.
            return False
    return True


def run_one(k, N, M):
    t0 = time.time()
    rng = random.Random(seed_of(k, N))
    ve, vx = V_env(N), V_X(k, N)
    p_exact = vx / ve
    hits = 0
    for _ in range(M):
        if sample_word(rng, N, k):
            hits += 1
    p_hat = hits / M
    v_hat = ve * p_hat
    if hits > 0:
        H = -math.log(p_hat)
        rel_se = math.sqrt((1.0 - p_hat) / (M * p_hat))
        delta_hat = math.log(v_hat) / math.log(N)
        rel_err = abs(delta_hat - delta_exact(k, N)) / delta_exact(k, N)
    else:
        H, rel_se, delta_hat, rel_err = float("inf"), float("inf"), float("nan"), float("nan")
    return {
        "k": k, "N": N, "seed": seed_of(k, N), "M": M,
        "V_env": ve, "V_X": vx, "p_exact": p_exact,
        "delta_exact": round(delta_exact(k, N), 6),
        "hits": hits, "p_hat": p_hat, "H": H, "V_hat": v_hat,
        "delta_hat": delta_hat, "rel_se": rel_se, "rel_err": rel_err,
        "converged": (rel_se <= REL_SE_MAX) and (hits >= H_MIN),
        "sampling_infeasible": (p_exact < P_MAX) or (p_hat < P_MAX),
        "runtime_seconds": round(time.time() - t0, 3),
        "estimator": "corrected: reduced-word length distribution + uniform reduced word",
    }


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        if math.isnan(o):
            return "nan"
        return "inf" if o > 0 else "-inf"
    return o


def main():
    t_all = time.time()
    check_rows, bad_counts = count_selfcheck()
    print("PROGRESS: " + json.dumps(clean({
        "stage": "count_selfcheck", "brute_force_pairs": len(check_rows),
        "mismatches": len(bad_counts)})), flush=True)

    rows, crashes = [], []
    total = len(K_VALUES) * len(N_VALUES)
    i = 0
    for k in K_VALUES:
        for N in N_VALUES:
            i += 1
            try:
                r = run_one(k, N, M_BY_N[N])
            except Exception as e:  # noqa: BLE001
                crashes.append({"k": k, "N": N, "error": repr(e)})
                print("PROGRESS: " + json.dumps(clean(
                    {"done": i, "total": total, "k": k, "N": N, "status": "crash",
                     "error": repr(e)})), flush=True)
                continue
            rows.append(r)
            print(json.dumps(clean(r), ensure_ascii=False), flush=True)
            print("PROGRESS: " + json.dumps(clean({
                "done": i, "total": total, "k": k, "N": N,
                "elapsed_cell": r["runtime_seconds"], "hits": r["hits"],
                "rel_se": r["rel_se"], "rel_err": r["rel_err"],
                "converged": r["converged"],
                "sampling_infeasible": r["sampling_infeasible"]})), flush=True)

    wall = round(time.time() - t_all, 3)
    converged = [r for r in rows if r["converged"]]
    infeasible = [r for r in rows if r["sampling_infeasible"]]
    mismatch = [r for r in converged
                if not (math.isfinite(r["rel_err"]) and r["rel_err"] <= TOL)]

    counterexample = None
    if bad_counts:
        b = bad_counts[0]
        counterexample = {"kind": "count_formula_wrong", **b,
                          "why": "closed form 2k(2k-1)^(l-1) disagrees with exhaustive enumeration"}
    elif mismatch:
        m = sorted(mismatch, key=lambda r: (r["N"], r["k"]))[0]
        counterexample = {"kind": "corrected_sampler_misses_exact_count",
                          "k": m["k"], "N": m["N"], "seed": m["seed"], "M": m["M"],
                          "hits": m["hits"], "p_exact": m["p_exact"], "p_hat": m["p_hat"],
                          "delta_exact": m["delta_exact"], "delta_hat": m["delta_hat"],
                          "rel_err": m["rel_err"], "tolerance": TOL,
                          "why": "converged=True by rel_se<=0.1 yet rel_err > TOL"}

    if crashes or bad_counts:
        result = "inconclusive" if crashes and not bad_counts else (
            "refutes" if bad_counts else "inconclusive")
    elif mismatch:
        result = "refutes"
    elif converged:
        result = "supports"
    else:
        result = "inconclusive"

    payload = {
        "result": result,
        "criterion": ("(A) closed-form length-l reduced-word count == exhaustive count for "
                      "k in {2,3,4}, l<=4 ; (B) on every cell flagged converged "
                      "(rel_se<=0.1 and hits>=50): rel_err=|delta_hat-delta_exact|/delta_exact <= 0.1"),
        "cells_total": total,
        "cells_converged": [[r["k"], r["N"]] for r in converged],
        "cells_sampling_infeasible": [[r["k"], r["N"]] for r in infeasible],
        "cells_neither": [[r["k"], r["N"]] for r in rows
                          if not r["converged"] and not r["sampling_infeasible"]],
        "cells_rel_err_gt_TOL_among_converged": [[r["k"], r["N"], r["rel_err"]]
                                                 for r in mismatch],
        "crash_count": len(crashes), "crashes": crashes,
        "count_selfcheck_pairs": len(check_rows),
        "count_selfcheck_mismatches": len(bad_counts),
        "delta_exact_table": {"%d,%d" % (r["k"], r["N"]): r["delta_exact"] for r in rows},
        "rel_err_table": {"%d,%d" % (r["k"], r["N"]): r["rel_err"] for r in rows},
        "wall_seconds": wall,
        "bound": {"k": K_VALUES, "N": N_VALUES, "M_by_N": M_BY_N,
                  "brute_force_length_max": BRUTE_LMAX},
        "strategy": ("brute force exact count (closed form) + exhaustive enumeration "
                     "self-check for l<=4 + randomized+certificate (fixed-seed Monte Carlo "
                     "over reduced words, exact integer length sampler)"),
        "scaling": [{"k": r["k"], "N": r["N"], "M": r["M"],
                     "seconds": r["runtime_seconds"]} for r in rows],
        "limits": ("delta_0 is not a factor invariant; only the standard free generator "
                   "tuple X_k; supported_not_proved at best; this is a numerical cross-check, "
                   "not a proof"),
    }
    if counterexample is not None:
        payload["counterexample"] = counterexample
    print("REPRO_RESULT: " + json.dumps(clean(payload), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
