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
    """Print the REPRO_RESULT line, the banner, optionally write the JSON file,
    and return the exit code: 0 = supports, 1 = refutes, 2 = inconclusive.

    An inconclusive result is NOT a pass: the banner says so explicitly and the
    exit code is non-zero, so a framework that treats "exit 0" as success cannot
    mistake it for one.
    """
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
    kind = result["result"]
    if kind == "supports":
        print("ALL CHECKS PASS", flush=True)
        return 0
    if kind == "inconclusive":
        print("ALL CHECKS INCONCLUSIVE", flush=True)
    else:
        print("ALL CHECKS FAIL", flush=True)
    for c in result["observations"]["checks"]:
        if not c["ok"]:
            print("  %s CHECK %s :: %s"
                  % ("FAILED" if c.get("severity", "must_hold") == "must_hold"
                     else "UNDECIDED", c["check"], c["detail"]), flush=True)
    return 1 if kind == "refutes" else 2


class Budget:
    """A hard wall-clock bound for a script.  Nothing here may hang silently:
    when the budget is exhausted the script stops starting new work, records an
    explicit undecided check saying so, and finishes with an honest
    "inconclusive" result rather than running until an external timeout."""

    def __init__(self, seconds, label="script"):
        self.seconds = float(seconds)
        self.label = label
        self.t0 = time.time()

    @property
    def elapsed(self):
        return time.time() - self.t0

    def expired(self):
        return self.seconds > 0 and self.elapsed >= self.seconds

    def describe(self):
        return ("%s: %.1fs elapsed of the %.1fs budget"
                % (self.label, self.elapsed, self.seconds))

    def mark_if_expired(self, checks, where):
        """Record an undecided check if the budget is gone.  Returns True if the
        caller must stop starting new work."""
        if self.expired():
            checks.check_maybe(
                "budget_not_exceeded",
                False,
                "%s -- work stopped at '%s'.  The checks that did run are "
                "reported, everything after this point was NOT attempted, and "
                "the run is INCONCLUSIVE rather than a hang.  Raise "
                "--max-seconds to attempt the rest." % (self.describe(), where))
            return True
        return False


def guard(fn):
    """Wrap a main() so that the process exit code is the one from emit() and an
    unexpected exception still produces a well-formed (refuting) REPRO_RESULT
    line and a non-zero exit."""
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
