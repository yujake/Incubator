"""Repro wrapper around scripts/f_conj000000_delta.py (E, conj000000 / plan 000000 / sg-a).

What this script adds to the original executor:
  (1) it runs the SAME per-cell code path (imports run_one from the original module,
      no copy of the numerics) and prints every cell reading verbatim;
  (2) it applies the REPRO_RESULT protocol line (draft/37 122/126) with
      bound / strategy / scaling, plus a PROGRESS line per finished cell;
  (3) it decides ONE deterministic, pre-stated criterion (see TOL below) about the
      Monte-Carlo cross-check, so a machine -- not a model -- reads the verdict.

Criterion (fixed before running, TOL = the original module's REL_SE_MAX):
  the script's own convergence test is rel_se <= 0.1, i.e. "this cell's estimate is
  pinned to (roughly) 10% relative precision". A cross-check against the exact
  combinatorial count must therefore satisfy, on every cell flagged converged:
        |delta_hat - delta_exact| / delta_exact <= TOL      (rel_err <= TOL)
  Any converged cell that violates it is a refutation of "the Monte-Carlo estimator
  cross-checks the exact count".
  If a cell crashes, the verdict is inconclusive (crash, not a refutation).

LIMITS carried with every number (from the original header):
  delta_0 is NOT a factor invariant; everything is defined only for the standard
  free generator tuple X_k = (u_1,...,u_k) of W*(F_k); readings are at best
  supported_not_proved; none of them is a proof.
"""

import importlib.util
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "scripts", "f_conj000000_delta.py")

TOL = 0.1  # = REL_SE_MAX of the original module; fixed before the run


def load_src(path):
    spec = importlib.util.spec_from_file_location("f_delta_src", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clean(o):
    """Make the payload strict-JSON safe: non-finite floats become strings."""
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
    mod = load_src(SRC)
    ks, ns = list(mod.K_VALUES), list(mod.N_VALUES)
    total = len(ks) * len(ns)

    rows, crashes = [], []
    t_all = time.time()
    i = 0
    for k in ks:
        for n in ns:
            i += 1
            t0 = time.time()
            try:
                r = mod.run_one(k, n)
            except Exception as e:  # noqa: BLE001 - a crash is a reading, not a verdict
                crashes.append({"k": k, "N": n, "error": repr(e)})
                print("PROGRESS: " + json.dumps(
                    clean({"done": i, "total": total, "k": k, "N": n,
                           "status": "crash", "error": repr(e)})), flush=True)
                continue

            # extra deterministic diagnostic: what does the sampler actually estimate?
            # the sampler draws a word of EXACTLY N letters kept iff all in A_k, so its
            # probability is (k/4)^N, while p_exact in the module is V_X/V_env over
            # words of length <= N.  z-score of p_hat against that fixed-length model.
            p_fixed = (k / 4.0) ** n
            if 0.0 < p_fixed < 1.0:
                z = (r["p_hat"] - p_fixed) / math.sqrt(p_fixed * (1.0 - p_fixed) / r["M"])
            else:
                z = None
            r["p_fixed_length_model"] = p_fixed
            r["sampler_z_vs_fixed_length"] = z
            rows.append(r)

            print(json.dumps(clean(r), ensure_ascii=False), flush=True)
            print("PROGRESS: " + json.dumps(clean({
                "done": i, "total": total, "k": k, "N": n,
                "elapsed_cell": round(time.time() - t0, 3),
                "hits": r["hits"], "rel_se": r["rel_se"],
                "converged": r["converged"],
                "sampling_infeasible": r["sampling_infeasible"]})), flush=True)

    wall = round(time.time() - t_all, 3)

    converged = [r for r in rows if r["converged"]]
    infeasible = [r for r in rows if r["sampling_infeasible"]]
    neither = [r for r in rows
               if not r["converged"] and not r["sampling_infeasible"]]
    mismatch = [r for r in converged
                if not (isinstance(r["rel_err"], float) and math.isfinite(r["rel_err"])
                        and r["rel_err"] <= TOL)]

    def cell(r):
        return [r["k"], r["N"]]

    counterexample = None
    if mismatch:
        m = sorted(mismatch, key=lambda r: (r["N"], r["k"]))[0]
        counterexample = {
            "k": m["k"], "N": m["N"], "seed": m["seed"], "M": m["M"],
            "hits": m["hits"], "p_hat": m["p_hat"], "p_exact": m["p_exact"],
            "delta_hat": m["delta_hat"], "delta_exact": m["delta_exact"],
            "rel_err": m["rel_err"], "tolerance": TOL,
            "why": ("this cell is flagged converged=True by the script's own criterion "
                    "(rel_se <= 0.1) yet delta_hat misses the exact value by rel_err > TOL: "
                    "the sampler draws words of exactly N letters with all letters in A_k "
                    "(prob (k/4)^N), while p_exact = V_X/V_env counts words of length <= N"),
        }

    if crashes:
        result = "inconclusive"
    elif mismatch:
        result = "refutes"
    elif converged:
        result = "supports"
    else:
        result = "inconclusive"

    payload = {
        "result": result,
        "criterion": ("on every cell the script flags converged, "
                      "rel_err = |delta_hat - delta_exact|/delta_exact must be <= TOL = 0.1"),
        "cells_total": total,
        "cells_run": len(rows),
        "crashes": crashes,
        "converged_cells": [cell(r) for r in converged],
        "sampling_infeasible_cells": [cell(r) for r in infeasible],
        "neither_converged_nor_infeasible_cells": [cell(r) for r in neither],
        "converged_but_mismatch_cells": [cell(r) for r in mismatch],
        "rel_err_by_cell": {"%d,%d" % (r["k"], r["N"]): r["rel_err"] for r in rows},
        "delta_exact_by_cell": {"%d,%d" % (r["k"], r["N"]): r["delta_exact"] for r in rows},
        "delta_hat_by_cell": {"%d,%d" % (r["k"], r["N"]): r["delta_hat"] for r in rows},
        "hits_by_cell": {"%d,%d" % (r["k"], r["N"]): r["hits"] for r in rows},
        "sampler_len_check": {
            "%d,%d" % (r["k"], r["N"]): {"p_hat": r["p_hat"],
                                         "p_fixed_length_model": r["p_fixed_length_model"],
                                         "z": r["sampler_z_vs_fixed_length"]}
            for r in rows},
        "counterexample": counterexample,
        "bound": ("all k in {2,3,4} x N in {8,16,32,64}, 12 cells, seeds fixed "
                  "seed(k,N)=100000+1000k+N, M in {200000 (N=8), 100000 (N=16,32,64)}"),
        "strategy": "brute force exact count (closed form) + randomized+certificate (fixed-seed Monte Carlo)",
        "scaling": {"wall_seconds_total": wall,
                    "per_cell_seconds": {"%d,%d" % (r["k"], r["N"]): r["runtime_seconds"]
                                         for r in rows}},
        "limits": ("delta_0 is not a factor invariant; standard free generator tuples only; "
                   "supported_not_proved at best; this run neither proves nor disproves any "
                   "statement about delta_0 itself"),
        "source_script": "scripts/f_conj000000_delta.py",
        "source_sha256_note": "bound via verify.code_hash in the experiments row",
    }

    print(json.dumps(clean({"kind": "summary", "table": [
        {"k": r["k"], "N": r["N"], "hits": r["hits"], "p_hat": r["p_hat"],
         "p_exact": r["p_exact"], "delta_hat": r["delta_hat"],
         "delta_exact": r["delta_exact"], "rel_err": r["rel_err"],
         "converged": r["converged"], "sampling_infeasible": r["sampling_infeasible"],
         "z_vs_fixed_len": r["sampler_z_vs_fixed_length"]} for r in rows]}),
        ensure_ascii=False), flush=True)
    print("REPRO_RESULT: " + json.dumps(clean(payload), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
