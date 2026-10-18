"""Deterministic spec / executor for delta_N(X_k) finite-truncation estimate.
conjecture: conjectures:000000 ; plan: attack_plans:000000 ; subgoal: sg-a

LIMITS (must travel with every number below):
  delta_0 is NOT a factor invariant. Everything here is defined only for the
  standard free generator tuple X_k=(u_1,...,u_k) of W*(F_k). Readings are at best
  supported_not_proved; none of them is a proof.

Conventions
  alphabet A_k = {+1,-1,...,+k,-k}; a word is a reduced word over the 8-letter
  alphabet {+1,-1,...,+4,-4} whose letters all lie in A_k, with length in [0,N].
  V_X(k,N)   = 1 + sum_{l=1..N} 2k (2k-1)^(l-1)     # reduced words over A_k, len<=N
  V_env(N)   = 1 + sum_{l=1..N} 8 * 7^(l-1)         # same over the 8-letter alphabet
  delta_exact(k,N) = ln V_X(k,N) / ln N
Estimator (uniform sampling of env words, truncated at length N)
  hits = #samples whose letters all lie in A_k
  p_exact = V_X/V_env ; p_hat = hits/M ; V_hat = V_env * p_hat
  H = -ln p_hat ; rel_se = sqrt((1-p_hat)/(M p_hat))
  converged          = (rel_se <= rel_se_max) and (hits >= H_min)
  sampling_infeasible= (p_exact < p_max) or (p_hat < p_max)
Seeds are fixed: seed(k,N) = 100000 + 1000*k + N  (no wall-clock dependence).
"""
import json
import math
import random
import sys
import time

REL_SE_MAX = 0.1
H_MIN = 50
P_MAX = 1e-3
K_VALUES = [2, 3, 4]
N_VALUES = [8, 16, 32, 64]
M_BY_N = {8: 200000, 16: 100000, 32: 100000, 64: 100000}


def seed_of(k, N):
    return 100000 + 1000 * k + N


def V_env(N):
    return 1 + 8 * ((7 ** N - 1) // 6)


def V_X(k, N):
    return 1 + (2 * k) * ((2 * k - 1) ** N - 1) // (2 * k - 2)


def delta_exact(k, N):
    return math.log(V_X(k, N)) / math.log(N)


def sample_hits(k, N, seed, M):
    rng = random.Random(seed)
    allowed = set(range(1, k + 1)) | set(range(-k, 0))
    hits = 0
    for _ in range(M):
        ok = True
        for _l in range(N):
            a = rng.randint(1, 8)          # 1..4 -> +1..+4 ; 5..8 -> -1..-4
            s = a if a <= 4 else -(a - 4)
            if s not in allowed:
                ok = False
                break
        if ok:
            hits += 1
    return hits


def run_one(k, N):
    t0 = time.time()
    M = M_BY_N[N]
    seed = seed_of(k, N)
    ve = V_env(N)
    vx = V_X(k, N)
    p_exact = vx / ve
    hits = sample_hits(k, N, seed, M)
    p_hat = hits / M
    v_hat = ve * p_hat
    if hits > 0:
        H = -math.log(p_hat)
        rel_se = math.sqrt((1.0 - p_hat) / (M * p_hat))
        delta_hat = math.log(v_hat) / math.log(N)
        rel_err = abs(delta_hat - delta_exact(k, N))
    else:
        H = float("inf")
        rel_se = float("inf")
        delta_hat = float("nan")
        rel_err = float("nan")
    converged = (rel_se <= REL_SE_MAX) and (hits >= H_MIN)
    infeasible = (p_exact < P_MAX) or (p_hat < P_MAX)
    return {
        "k": k, "N": N, "seed": seed, "M": M,
        "V_env": ve, "V_X": vx,
        "delta_exact": round(delta_exact(k, N), 6),
        "p_exact": p_exact,
        "hits": hits,
        "p_hat": p_hat,
        "H": H,
        "V_hat": v_hat,
        "delta_hat": delta_hat,
        "rel_se": rel_se,
        "rel_err": rel_err,
        "sampling_infeasible": infeasible,
        "converged": converged,
        "runtime_seconds": round(time.time() - t0, 3),
    }


def main():
    rows = []
    t_all = time.time()
    for k in K_VALUES:
        for N in N_VALUES:
            row = run_one(k, N)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    total = round(time.time() - t_all, 3)
    trial = [r for r in rows if r["k"] == 2 and r["N"] == 8][0]
    summary = {
        "kind": "summary",
        "total_runtime_seconds": total,
        "trial_k2_N8": {
            "delta_hat": trial["delta_hat"],
            "delta_exact": trial["delta_exact"],
            "hits": trial["hits"],
            "rel_se": trial["rel_se"],
            "converged": trial["converged"],
            "runtime_seconds": trial["runtime_seconds"],
        },
        "infeasible_cells": [[r["k"], r["N"]] for r in rows if r["sampling_infeasible"]],
        "delta_exact_table": {"%d,%d" % (r["k"], r["N"]): r["delta_exact"] for r in rows},
        "limits": "delta_0 is not a factor invariant; only standard free generator tuples; supported_not_proved at best",
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
