# -*- coding: utf-8 -*-
"""CC3 交付读数采集：四条链各跑 Lean 开/关一趟，打印报告要用的盘上终态。"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1] / "tests"
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(TESTS))

import pytest  # noqa: E402

import test_rehearsal_c1_literature_chain as C1  # noqa: E402
import test_rehearsal_c3_numeric_chain as C3  # noqa: E402
import test_rehearsal_c10_writing as C10  # noqa: E402
import test_rehearsal_c12_closing as C12  # noqa: E402
from agentflow import closing as CL  # noqa: E402
from agentflow import modelcost as MC  # noqa: E402


class _MP:
    """pytest 的 MonkeyPatch 没有上下文管理器协议：这里包一层，收尾一定 undo。"""

    def __enter__(self):
        self.mp = pytest.MonkeyPatch()
        return self.mp

    def __exit__(self, *exc):
        self.mp.undo()
        return False


def _money(st):
    got = MC.reconcile_usage(st)
    return {k: got.get(k) for k in ("ledger_rows", "unattributed", "dangling", "equal")}


def c1(lean):
    with _MP() as mp:
        got = C1._run(Path(tempfile.mkdtemp(prefix=f"cc3-c1-{lean}-")), mp, lean=lean)
    r = C1._chain_reading(got)
    return {
        "rc": got["rc"],
        "wire_calls": len(got["wire"].bodies),
        "search_requests": [(x.get("outcome"), x.get("topic")) for x in r["requests"]],
        "literature": [(x.get("path"), x.get("processed")) for x in r["literature"]],
        "relations": [(x.get("status"), str(x.get("quote_reason") or "")[:40])
                      for x in r["relations"]],
        "concepts": [x.get("name") for x in r["concepts"]],
        "digest": r["digest"],
        "tasks": [(t.get("role"), t.get("outcome")) for t in r["tasks"]
                  if not str(t.get("kind") or "")],
        "money": _money(r["store"]),
        "chain_problems": C1._chain_problems(r),
    }


def c3(lean):
    with _MP() as mp:
        got = C3._run(Path(tempfile.mkdtemp(prefix=f"cc3-c3-{lean}-")), mp, lean=lean)
    r = C3._chain_reading(got)
    e_task = [t for t in r["tasks"]
              if str(t.get("role")) == "E" and not str(t.get("kind") or "")]
    return {
        "rc": got["rc"],
        "wire_calls": len(got["wire"].bodies),
        "experiments": [(x.get("experiment_id"), x.get("method"), x.get("result"),
                         x.get("evidence_kind")) for x in r["experiments"]],
        "statements": [(x.get("stmt_id"), x.get("kind"), x.get("evidence_kind"),
                        dict(x.get("bits") or {}).get("numeric"),
                        [no for no, _t in __import__("agentflow.verifications",
                                                     fromlist=["x"]).proof_list(x)])
                       for x in r["statements"]],
        "reports": r["reports"],
        "pending_rows": len(r["pending"]),
        "pending_groups": sorted({int(x.get("path_group") or 0) for x in r["pending"]}),
        "sign_envelope": sorted(p.name for p in
                                (Path(r["store"].root) / "out" / "vsigns").glob("*.json")),
        "review_passes": [p.get("pass") for p in
                          (r["reviewed"]["data"].get("review_passes") or [])],
        "review_kind": r["reviewed"]["data"].get("kind"),
        "e_task_outcome": e_task[0].get("outcome") if e_task else "",
        "e_final_refusal": _e_refusal(r),
        "money": _money(r["store"]),
        "chain_problems": C3._chain_problems(r),
    }


def _e_refusal(r):
    for e in r["events"]:
        if (e.get("kind") == "agent_step" and e.get("role") == "E"
                and e.get("shape") == "final"):
            res = e.get("result") or {}
            if res.get("final_refused"):
                fr = res["final_refused"]
                return {"complete": fr.get("complete"),
                        "problems": [str(p.get("what") or "")[:90]
                                     for p in (fr.get("problems") or [])]}
    return {}


def c10(lean, close_as=True):
    with _MP() as mp:
        got = C10._run(Path(tempfile.mkdtemp(prefix=f"cc3-c10-{lean}-")), mp,
                       lean=lean, close_as=close_as)
    r = C10._reading(got)
    doc = r["doc"]
    return {
        "rc": got["rc"],
        "wire_calls": len(got["wire"].bodies),
        "doc": {k: doc.get(k) for k in ("doc_id", "status", "review_rounds",
                                        "markdown_path")},
        "claims": [{"claim_id": c.get("claim_id"), "disclaimer": c.get("disclaimer")}
                   for c in (doc.get("claims") or [])],
        "findings": [(f.get("finding_id"), f.get("kind"), f.get("level"),
                      f.get("status"), f.get("target")) for f in r["findings"]],
        "dependencies": [(d.get("dep_id"), d.get("used_by"), d.get("status"))
                         for d in r["dependencies"]],
        "review_verdict": r["reviewed"]["data"].get("verdict"),
        "revise_status": r["revised"]["data"].get("status"),
        "verify_verdict": r["verified"]["data"].get("verdict"),
        "verify_still_open": [(f.get("kind"), f.get("level")) for f in
                              (r["verified"]["data"].get("still_open") or [])],
        "money": _money(r["store"]),
        "chain_problems": C10._chain_problems(r),
    }


def c12(lean, pending=False):
    with _MP() as mp:
        got = C12._run(Path(tempfile.mkdtemp(prefix=f"cc3-c12-{lean}-")), mp,
                       lean=lean, pending_question=pending)
    data = C12._closing_result(C12._events(got["ws"]))["data"]
    return {
        "rc": got["rc"],
        "wire_calls": len(got["wire"].bodies),
        "m_says_done": data.get("m_says_done"),
        "can_close": data.get("can_close"),
        "closable": data.get("closable"),
        "machine_pass": data.get("machine_pass"),
        "status": data.get("status"),
        "failed": data.get("failed"),
        "unknowns": data.get("unknowns"),
        "verdict_written": data.get("verdict_written"),
        "m_verdict_rows": C12._verdict_rows(got["ws"]),
        "money": _money(got["store"]),
    }


out = {}
for lean in ("0", "1"):
    out[f"c1_lean{lean}"] = c1(lean)
    out[f"c3_lean{lean}"] = c3(lean)
    out[f"c10_lean{lean}"] = c10(lean)
    out[f"c10_no_close_as_lean{lean}"] = c10(lean, close_as=False)
    out[f"c12_lean{lean}"] = c12(lean)
out["c12_pending_question"] = c12("0", pending=True)
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


