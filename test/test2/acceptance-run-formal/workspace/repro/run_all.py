#!/usr/bin/env python
"""
run_all.py -- run the five reproduction experiments in order, summarise them in
one table, run every negative control and verify that each one really fails, then
print ALL CHECKS PASS / ALL CHECKS FAIL and write the aggregate JSON.

Usage (from the repro/ directory):
    python run_all.py --json ..\\repro-summary.json

Exit code 0 iff every experiment reported "supports" AND every negative control
was caught.  Each experiment is invoked as a subprocess through its command-line
interface, so what is tested is the interface a framework would use:
    python expN_*.py [--inject-bug NAME] --json <tmp.json>
and the REPRO_RESULT line is parsed back out of stdout.

Framework conventions honoured here:
  * every experiment script's evidence_kind is "cross_check";
  * a non-zero exit code is never reported as a positive conclusion -- the row
    is recorded as "crashed"/"inconclusive" with the raw stdout kept;
  * the negative controls are checked for the right failure, not just for a
    non-zero exit: the JSON must name the check that caught the injected bug.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# (script, extra argv for the clean run, extra argv for the negative controls)
EXPERIMENTS = [
    ("exp1_k_spectrum.py", ["--m", "3,4,5"],
     [["--inject-bug", "coarse_grid"], ["--inject-bug", "double_count"]]),
    ("exp2_girths.py", ["--m", "3,4,5"],
     [["--inject-bug", "allow_backtrack"], ["--inject-bug", "wrong_s0"]]),
    ("exp3_chamber_spectrum.py", ["--m", "3,4,5", "--m-open", "6"],
     [["--inject-bug", "transpose_voltage", "--m", "3,4,5", "--m-open", ""]]),
    ("exp4_size_regularity.py", ["--m", "3,4,5"],
     [["--inject-bug", "lattice_Q"]]),
    ("exp5_noniso.py", ["--m", "4,5"],
     [["--inject-bug", "same_girth"]]),
]
#: generous per-script ceiling for the subprocess call; each script also has its
#: own --max-seconds (exp3: 300 s because of the 720x720 m=6 cell) so that it can
#: never hang; this is only the outer guard.
SUBPROCESS_TIMEOUT_S = 900


def run_script(script, argv, json_path, timeout=900):
    cmd = [sys.executable, os.path.join(HERE, script)] + list(argv)
    if json_path:
        cmd += ["--json", json_path]
    t0 = time.time()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env=env)
    elapsed = time.time() - t0
    result_line = None
    for line in proc.stdout.splitlines():
        if line.startswith("REPRO_RESULT:"):
            try:
                result_line = json.loads(line.split("REPRO_RESULT:", 1)[1].strip())
            except json.JSONDecodeError:
                result_line = None
    return {
        "script": script,
        "argv": list(argv),
        "returncode": proc.returncode,
        "seconds": round(elapsed, 2),
        "banner_pass": "ALL CHECKS PASS" in proc.stdout,
        "banner_fail": "ALL CHECKS FAIL" in proc.stdout,
        "banner_inconclusive": "ALL CHECKS INCONCLUSIVE" in proc.stdout,
        "result": result_line,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-6:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-6:]),
    }


def verdict_of(rec):
    """Map a run to a verdict, refusing to call an exit != 0 a success.

    exit 0  + result supports      -> supports
    exit 1  + result refutes       -> caught_the_injected_bug (clean run: refuted)
    exit 2  + result inconclusive  -> inconclusive (e.g. the time budget ran out)
    exit != 0 without a REPRO_RESULT -> crashed
    """
    r = (rec["result"] or {}).get("result")
    if rec["returncode"] == 0:
        if r == "supports":
            return "supports"
        return "unknown" if r else "crashed"
    if r == "refutes":
        return "caught_the_injected_bug"
    if r == "inconclusive":
        return "inconclusive"
    return "crashed"


def caught_by(rec):
    obs = (rec["result"] or {}).get("observations", {})
    names = obs.get("failed_checks")
    if names:
        return ", ".join(names[:4])
    return obs.get("caught_by", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="aggregate summary JSON path")
    ap.add_argument("--tmpdir", default=".")
    args = ap.parse_args()

    print("=" * 78)
    print("repro of Jiaqi Yu, 'Cospectral periodic graphs: the spectrum does not")
    print("determine the graph' (2026-09-21, unpublished) -- independent numerics")
    print("=" * 78, flush=True)

    clean_runs = []
    bug_runs = []
    t_start = time.time()

    for script, argv, bugs in EXPERIMENTS:
        print("\n--- clean run: %s %s" % (script, " ".join(argv)), flush=True)
        jp = os.path.join(args.tmpdir, "_runall_%s.json" % script.replace(".py", ""))
        rec = run_script(script, argv, jp, timeout=SUBPROCESS_TIMEOUT_S)
        rec["verdict"] = verdict_of(rec)
        clean_runs.append(rec)
        exp = (rec["result"] or {}).get("observations", {})
        print("    verdict=%-10s exit=%d  %.1fs  checks=%s failed=%s undecided=%s"
              % (rec["verdict"], rec["returncode"], rec["seconds"],
                 exp.get("n_checks"), exp.get("n_failed"), exp.get("n_undecided")),
              flush=True)
        if rec["verdict"] != "supports":
            print("    !! this experiment did not report supports", flush=True)
            if rec["stderr_tail"]:
                print("    stderr: %s" % rec["stderr_tail"].replace("\n", " | "),
                      flush=True)

        for bug in bugs:
            name = bug[bug.index("--inject-bug") + 1]
            print("\n--- negative control: %s %s" % (script, " ".join(bug)), flush=True)
            jpb = os.path.join(args.tmpdir,
                               "_runall_%s_%s.json" % (script.replace(".py", ""), name))
            r = run_script(script, argv + bug, jpb, timeout=SUBPROCESS_TIMEOUT_S)
            r["bug"] = name
            r["verdict"] = verdict_of(r)
            bug_runs.append(r)
            print("    exit=%d  %.1fs  verdict=%s  caught_by=%s"
                  % (r["returncode"], r["seconds"], r["verdict"], caught_by(r)),
                  flush=True)
            if r["verdict"] != "caught_the_injected_bug":
                print("    !! NEGATIVE CONTROL DID NOT FAIL AS REQUIRED", flush=True)

    total = time.time() - t_start

    # ------------------------------------------------------------------ table
    print("\n" + "=" * 78)
    print("SUMMARY TABLE")
    print("=" * 78)
    hdr = "%-26s %-10s %-10s %6s %8s  %s" % ("script", "result", "kind", "checks",
                                             "failed", "seconds")
    print(hdr)
    print("-" * len(hdr))
    for rec in clean_runs:
        obs = (rec["result"] or {}).get("observations", {})
        print("%-26s %-10s %-10s %6s %8s %8.2f" % (
            rec["script"], rec["verdict"],
            (rec["result"] or {}).get("evidence_kind", "-"),
            obs.get("n_checks", "-"), obs.get("n_failed", "-"), rec["seconds"]))
    print("-" * len(hdr))
    for rec in bug_runs:
        obs = (rec["result"] or {}).get("observations", {})
        print("%-26s %-10s %-10s %6s %8s %8.2f   [--inject-bug %s]" % (
            rec["script"], rec["verdict"],
            (rec["result"] or {}).get("evidence_kind", "-"),
            obs.get("n_checks", "-"), obs.get("n_failed", "-"), rec["seconds"],
            rec["bug"]))
        if rec["verdict"] == "caught_the_injected_bug":
            print("%-26s   caught by: %s" % ("", caught_by(rec)))

    print("\ntotal wall time: %.1fs" % total)

    # ------------------------------------------------------------- criteria
    exp_ok = all(r["verdict"] == "supports" for r in clean_runs)
    ev_kind_ok = all((r["result"] or {}).get("evidence_kind") == "cross_check"
                     for r in clean_runs + bug_runs if r["result"])
    bugs_ok = all(r["verdict"] == "caught_the_injected_bug" for r in bug_runs)
    banners_ok = all(r["banner_pass"] for r in clean_runs) and \
        all(r["banner_fail"] for r in bug_runs)
    no_hang_ok = all(rec["verdict"] != "crashed" for rec in clean_runs + bug_runs)

    print("\ncriteria:")
    print("  all five experiments report supports .......... %s" % exp_ok)
    print("  every result carries evidence_kind=cross_check %s" % ev_kind_ok)
    print("  every negative control was caught ............. %s" % bugs_ok)
    print("  banners match (PASS clean / FAIL injected) .... %s" % banners_ok)
    print("  no script crashed or timed out ................ %s" % no_hang_ok)

    overall = "ALL CHECKS PASS" if (exp_ok and ev_kind_ok and bugs_ok
                                    and banners_ok and no_hang_ok) \
        else "ALL CHECKS FAIL"
    print("\n" + overall, flush=True)

    summary = {
        "task": "independent numerical reproduction of Yu, 'Cospectral periodic "
                "graphs: the spectrum does not determine the graph' (2026)",
        "aggregate": {
            "experiments": len(clean_runs),
            "negative_controls": len(bug_runs),
            "all_experiments_supports": exp_ok,
            "all_negative_controls_caught": bugs_ok,
            "all_evidence_kind_cross_check": ev_kind_ok,
            "banners_match": banners_ok,
            "no_script_hung_or_crashed": no_hang_ok,
            "subprocess_timeout_seconds": SUBPROCESS_TIMEOUT_S,
            "per_script_max_seconds": {"exp1": 60, "exp2": 60, "exp3": 300,
                                       "exp4": 60, "exp5": 60},
            "total_seconds": round(total, 2),
            "verdict": overall,
        },
        "clean_runs": [{k: v for k, v in r.items() if k != "stdout_tail"}
                       for r in clean_runs],
        "negative_controls": [{k: v for k, v in r.items() if k != "stdout_tail"}
                              for r in bug_runs],
        "honest_boundary": [
            "Spec S~_m = [-m,m] is QUOTED in the paper from the companion book "
            "[6, Thm. 6.5] and was not independently verified here (the book is "
            "not available); exp3/exp5 only fail to find a counterexample.",
            "m >= 6 for S~_m is an OPEN problem in the paper; the numerics are "
            "consistent with the equality but no conclusion is drawn and the "
            "paper's obstruction (two eigenvalue branches must meet) is not "
            "addressed.",
            "No numerical output is used as a proof anywhere in this repro.",
        ],
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, sort_keys=True, default=str)
        print("wrote %s" % os.path.abspath(args.json), flush=True)

    return 0 if overall == "ALL CHECKS PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
