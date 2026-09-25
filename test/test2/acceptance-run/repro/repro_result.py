"""
repro_result.py -- the tiny harness shared by the five experiment scripts.

Framework contract (fixed by the delegating task):
  * stdout carries exactly one line  REPRO_RESULT: {json}
  * all checks passing  -> the string ALL CHECKS PASS  and exit code 0
  * any check failing   -> the string ALL CHECKS FAIL   and exit code 1
  * evidence_kind is ALWAYS "cross_check": numerical experiments are never
    proofs (the paper says the same at main-paper-text.txt:404).
"""

from __future__ import annotations

import json
import sys
import time
import traceback

RESULT_KEYS = ("result", "evidence_kind", "negation_kind", "observations",
               "counterexample")


class Checks:
    """Accumulates named checks.  Each check has a name, a boolean and a detail
    string, so a failure can always be attributed to a specific check."""

    def __init__(self):
        self.items = []
        self.observations = {}
        self.notes = []
        self.counterexample = None
        self._t0 = time.time()

    # ---- checks ---------------------------------------------------------
    def check(self, name, ok, detail=""):
        self.items.append({"check": name, "ok": bool(ok), "detail": str(detail)})
        return bool(ok)

    def observe(self, key, value):
        self.observations[key] = value
        return value

    def note(self, text):
        self.notes.append(str(text))

    def set_counterexample(self, obj):
        self.counterexample = obj

    # ---- reporting ------------------------------------------------------
    @property
    def failed(self):
        return [c for c in self.items if not c["ok"]]

    @property
    def elapsed(self):
        return time.time() - self._t0

    def all_ok(self):
        return not self.failed and bool(self.items)

    def result_dict(self, negation_kind_default="not_proved"):
        failed = self.failed
        if failed:
            result = "refutes"
            neg = "no_local_evidence"
        else:
            result = "supports"
            neg = negation_kind_default
        obs = dict(self.observations)
        obs["checks"] = self.items
        obs["n_checks"] = len(self.items)
        obs["n_failed"] = len(failed)
        obs["elapsed_seconds"] = round(self.elapsed, 3)
        if self.notes:
            obs["notes"] = self.notes
        if failed:
            obs["failed_checks"] = [c["check"] for c in failed]
            obs["caught_by"] = "; ".join(
                "%s: %s" % (c["check"], c["detail"]) for c in failed)
        return {
            "result": result,
            "evidence_kind": "cross_check",
            "negation_kind": neg,
            "observations": obs,
            "counterexample": self.counterexample,
        }


def emit(result, json_path=None, verbose=True):
    """Print the REPRO_RESULT line, the PASS/FAIL banner, optionally write the
    JSON file, and return the exit code (0 pass, 1 fail)."""
    line = "REPRO_RESULT: " + json.dumps(result, sort_keys=True, default=str)
    print(line, flush=True)
    if json_path:
        try:
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2, sort_keys=True, default=str)
            if verbose:
                print("wrote %s" % json_path, flush=True)
        except OSError as exc:                       # pragma: no cover
            print("could not write %s: %s" % (json_path, exc), flush=True)
    ok = result["result"] == "supports"
    print("ALL CHECKS PASS" if ok else "ALL CHECKS FAIL", flush=True)
    if not ok:
        for c in result["observations"]["checks"]:
            if not c["ok"]:
                print("  FAILED CHECK %s :: %s" % (c["check"], c["detail"]), flush=True)
    return 0 if ok else 1


def guard(fn):
    """Wrap a main() so that an unexpected exception still produces a
    well-formed (refuting) REPRO_RESULT line and a non-zero exit code."""
    try:
        return fn()
    except Exception as exc:                          # noqa: BLE001
        tb = traceback.format_exc()
        res = {
            "result": "refutes",
            "evidence_kind": "cross_check",
            "negation_kind": "no_local_evidence",
            "observations": {"exception": "%s: %s" % (type(exc).__name__, exc),
                             "traceback": tb, "checks": [
                                 {"check": "script_completed", "ok": False,
                                  "detail": "unhandled %s" % type(exc).__name__}]},
            "counterexample": None,
        }
        code = emit(res)
        sys.exit(code)
