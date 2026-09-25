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
    string, so a failure can always be attributed to a specific check.

    Three severities are supported:
      check(name, ok, detail)         -- must hold; a failure refutes
      check_maybe(name, ok, detail)   -- an undecided outcome: it is reported
                                         but does not, by itself, refute.  Used
                                         when the honest verdict is "resolution
                                         too coarse to decide" (severity
                                         "undecided" in the JSON).
    """

    def __init__(self):
        self.items = []
        self.observations = {}
        self.notes = []
        self.counterexample = None
        self.undecided = []
        self._t0 = time.time()

    # ---- checks ---------------------------------------------------------
    def check(self, name, ok, detail="", severity="must_hold"):
        self.items.append({"check": name, "ok": bool(ok),
                           "severity": severity, "detail": str(detail)})
        return bool(ok)

    def check_maybe(self, name, ok, detail=""):
        return self.check(name, ok, detail, severity="undecided")

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
        return [c for c in self.items
                if not c["ok"] and c["severity"] == "must_hold"]

    @property
    def undecided_items(self):
        return [c for c in self.items
                if not c["ok"] and c["severity"] == "undecided"]

    @property
    def elapsed(self):
        return time.time() - self._t0

    def all_ok(self):
        return not self.failed and bool(self.items)

    def result_dict(self, negation_kind_default="not_proved"):
        failed = self.failed
        undecided = self.undecided_items
        if failed:
            result = "refutes"
            neg = "no_local_evidence"
        elif undecided:
            result = "inconclusive"
            neg = "no_local_evidence"
        else:
            result = "supports"
            neg = negation_kind_default
        obs = dict(self.observations)
        obs["checks"] = self.items
        obs["n_checks"] = len(self.items)
        obs["n_failed"] = len(failed)
        obs["n_undecided"] = len(undecided)
        obs["elapsed_seconds"] = round(self.elapsed, 3)
        if self.notes:
            obs["notes"] = self.notes
        if failed:
            obs["failed_checks"] = [c["check"] for c in failed]
            obs["caught_by"] = "; ".join(
                "%s: %s" % (c["check"], c["detail"]) for c in failed)
        if undecided:
            obs["undecided_checks"] = [
                {"check": c["check"], "detail": c["detail"]} for c in undecided]
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
    """Wrap a main() so that the process exit code is the one from emit() (0 for
    ALL CHECKS PASS, 1 for ALL CHECKS FAIL) and an unexpected exception still
    produces a well-formed (refuting) REPRO_RESULT line and a non-zero exit."""
    try:
        code = fn()
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
    sys.exit(0 if code is None else int(code))
