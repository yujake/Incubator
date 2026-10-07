# -*- coding: utf-8 -*-
"""R1b 正控（最关键的一条）：真 CLI 端到端 —— 合规记录必须通过。

场景：合成工作区里走真实命令行（不是内存对象）：
    --baseline  →  3 次 --record-audit（3 名审计者 × 3 个维度）  →  --check-approvals
断言：exit=0 / verdict=clean / approval_status=approved / clean_audits=3 /
      distinct_auditors=3 / distinct_dimensions=3。

并对同一场景跑「改前负控」：用 temp/_mk_preparse.py 造一份
「当前实现减掉 `_parse_audit` 的两行读回」的副本（这就是 `R1-AN-1` 的改前形态），
把同一批命令以 `python <副本>` 重跑 ⇒ 同一场景必须 clean=0 / exit=1。

探针自校：`_parse_audit` 在「当前实现」里必须带 `audit_started_sha256=` 读回那一行，
在「改前副本」里必须不带 —— 否则负控是假绿（跑的还是当前实现）。

只读 agentflow/；一切写入落在 temp/reaudit5-R1b-pos/ 下。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\Incubator\agentflow")
GATE = REPO / "scripts" / "noai_gate.py"
BASE = Path(r"D:\Incubator\temp\reaudit5-R1b-pos")
WS = BASE / "ws"
MUT = BASE / "noai_gate_preparse.py"

DIGEST_TAG = "audit_started_sha256=str(item.get("
FIX_LINES = ('        audit_started_sha256=str(item.get("audit_started_sha256", "") or ""),\n'
             '        independence=str(item.get("independence", "") or ""),\n')

MANIFEST = (
    "[category: auth-audit] 七、权限与审计（谁能做什么，以及谁做过了什么）\n"
    "\n"
    "src/target.py  [category: auth-audit] 合成工作区的被审对象：符号 `VALUE` 与 `bump`\n"
)

TARGET_SRC = (
    '"""合成被审对象：只有两个符号 VALUE 与 bump。"""\n'
    "\n"
    "VALUE = 1\n"
    "\n"
    "\n"
    "def bump() -> int:\n"
    "    return VALUE + 1\n"
)

NC = ("负控：拿同一套判据去审改前那一版（`git show HEAD:src/target.py`）—— "
      "改前那一版没有 `bump` 这个符号，判据必须报红，否则说明它没有分辨力。")

AUDITS = [
    ("reaudit5-A1", "axes", "temp/EV1.txt"),
    ("reaudit5-A2", "roles", "temp/EV2.txt"),
    ("reaudit5-A3", "errors", "temp/EV3.txt"),
]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(gate: Path, *argv: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(gate), *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO),
    )
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))


def write_mutant() -> None:
    """把当前实现减掉 `_parse_audit` 的两行读回 ⇒ 改前（R1-AN-1）形态。"""
    t = GATE.read_text(encoding="utf-8")
    for ln in FIX_LINES.splitlines(keepends=True):
        if t.count(ln) != 1:
            raise SystemExit(f"定位失败：{ln!r} 出现 {t.count(ln)} 次")
        t = t.replace(ln, "")
    MUT.write_text(t, encoding="utf-8", newline="\n")


def fingerprint(gate: Path) -> dict:
    t = gate.read_text(encoding="utf-8")
    return {
        "file": str(gate),
        "sha256": sha256(gate),
        "lines": len(t.splitlines()),
        "parse_audit_reads_started": DIGEST_TAG in t,
        "has_counted_audits": "counted_audits" in t,
        "has_norm_evidence_rel": "_norm_evidence_rel" in t,
    }


def fresh_ws() -> None:
    if WS.exists():
        shutil.rmtree(WS)
    (WS / "src").mkdir(parents=True)
    (WS / "temp").mkdir(parents=True)
    (WS / "src" / "target.py").write_text(TARGET_SRC, encoding="utf-8", newline="\n")
    (WS / ".noai-paths").write_text(MANIFEST, encoding="utf-8", newline="\n")


def scenario(label: str, gate: Path) -> dict:
    """跑完整场景，返回读数。"""
    print("=" * 78)
    print(f"场景：{label}")
    print("=" * 78)
    fp = fingerprint(gate)
    print(f"  探针指纹   file={fp['file']}")
    print(f"             sha256={fp['sha256']}")
    print(f"             行数={fp['lines']}  "
          f"`_parse_audit` 读回 audit_started_sha256 ? {fp['parse_audit_reads_started']}  "
          f"counted_audits ? {fp['has_counted_audits']}  "
          f"_norm_evidence_rel ? {fp['has_norm_evidence_rel']}")
    fresh_ws()
    target = WS / "src" / "target.py"
    digest = sha256(target)
    print(f"  合成工作区 = {WS}")
    print(f"  被审对象 src/target.py sha256 = {digest}")

    rc, out = run(gate, "--root", str(WS), "--paths", "src/target.py", "--baseline")
    print(f"\n  $ --baseline                        exit={rc}")
    for ln in out.strip().splitlines():
        print(f"      {ln}")

    for i, (who, dim, ev_rel) in enumerate(AUDITS, 1):
        ev = WS / ev_rel
        ev.write_text(
            f"审计者标识（独立词）：{who}\n"
            f"维度：{dim}\n"
            f"开审版本 sha256 = {digest}\n"
            f"覆盖 scope 符号：target.py 的 VALUE 与 bump\n"
            f"{NC}\n",
            encoding="utf-8", newline="\n")
        rc, out = run(
            gate, "--root", str(WS), "--record-audit", "src/target.py",
            "--auditor", who, "--dimension", dim,
            "--evidence", ev_rel, "--evidence-path", ev_rel,
            "--negative-control", NC,
            "--audit-scope", "target.py VALUE bump",
            "--audit-started-sha256", digest,
            "--independence", f"我是子审计代理 {who}，与该条目的作者不是同一主体（署名者未知）",
        )
        print(f"\n  $ --record-audit {who}/{dim}   exit={rc}")
        for ln in out.strip().splitlines():
            print(f"      {ln}")

    led = json.loads((WS / ".noai-approvals.json").read_text(encoding="utf-8"))
    entry = led["entries"][0]
    print("\n  -- 盘上台账里 audits 数组逐条（写进 JSON 的字段）--")
    for a in entry["audits"]:
        print(f"      auditor={a['auditor']:<14} dim={a['dimension']:<7} "
              f"started={a.get('audit_started_sha256', '<缺>')[:12]:<12} "
              f"indep={'有' if a.get('independence') else '<缺>'} "
              f"ev_path={a.get('evidence_path')!r}")
    print(f"      盘上 audits 条数 = {len(entry['audits'])}")

    rc, out = run(gate, "--root", str(WS), "--paths", "src/target.py", "--check-approvals", "--json")
    print(f"\n  $ --check-approvals --json           exit={rc}")
    j = json.loads(out)
    ap = j["approvals"][0]
    reading = {
        "exit": rc,
        "verdict": j["verdict"],
        "approval_status": ap["approval_status"],
        "approval_reason": ap["approval_reason"],
        "clean_audits": len(ap.get("clean_audits") or []),
        "distinct_auditors": ap.get("distinct_auditors"),
        "distinct_dimensions": len(ap.get("distinct_dimensions") or []),
        "distinct_dimensions_list": ap.get("distinct_dimensions"),
        "receipt_records": (ap.get("receipt_chain") or {}).get("records"),
        "evidence_problems": ap.get("evidence_problems"),
    }
    for k, v in reading.items():
        print(f"      {k:<24} = {v}")
    print(f"      detail                   = {str(ap.get('detail'))[:400]}")
    ledger_started = [a.get("audit_started_sha256", "") for a in entry["audits"]]
    print(f"      盘上 started 字段全非空 ? {all(x.strip() for x in ledger_started)}")
    reading["ledger_started_all_nonempty"] = all(x.strip() for x in ledger_started)
    return reading


def main() -> int:
    BASE.mkdir(parents=True, exist_ok=True)
    write_mutant()

    print("#" * 78)
    print("# A. 当前实现（冻结字节）")
    print("#" * 78)
    cur = scenario("当前实现", GATE)
    ok_current = (
        cur["exit"] == 0 and cur["verdict"] == "clean"
        and cur["approval_status"] == "approved"
        and cur["clean_audits"] == 3
        and cur["distinct_auditors"] == 3
        and cur["distinct_dimensions"] == 3
        and cur["ledger_started_all_nonempty"] is True
    )
    print(f"\n  >>> 正控断言（exit=0 / clean / approved / clean_audits=3 / 3×3 / 盘上字段非空）"
          f" ⇒ {'通过' if ok_current else '不通过'}")

    print()
    print("#" * 78)
    print("# B. 改前负控（`_parse_audit` 减掉两行读回 = R1-AN-1 的改前形态）")
    print("#" * 78)
    mut = scenario("改前副本", MUT)
    mut_fp = fingerprint(MUT)
    inject_ok = (
        mut_fp["parse_audit_reads_started"] is False
        and mut_fp["sha256"] != fingerprint(GATE)["sha256"]
        and mut_fp["lines"] < fingerprint(GATE)["lines"]
    )
    print(f"\n  负控注入是否生效：改前副本不带那两行读回 = "
          f"{mut_fp['parse_audit_reads_started'] is False}；"
          f"sha 与当前不同 = {mut_fp['sha256'] != fingerprint(GATE)['sha256']}；"
          f"行数 {mut_fp['lines']} < 当前 {fingerprint(GATE)['lines']} "
          f"= {mut_fp['lines'] < fingerprint(GATE)['lines']}")
    ok_neg = (
        inject_ok and mut["clean_audits"] == 0
        and mut["distinct_auditors"] == 0 and mut["distinct_dimensions"] == 0
        and mut["exit"] != 0 and mut["approval_status"] != "approved"
        and mut["ledger_started_all_nonempty"] is False
    )
    print(f"  >>> 负控断言（注入生效 + clean=0 + exit!=0 + 未批准 + 盘上字段被清空）"
          f" ⇒ {'通过' if ok_neg else '不通过'}")

    print()
    print("=" * 78)
    print(f"总结：正控 {'PASS' if ok_current else 'FAIL'} / 负控 {'PASS' if ok_neg else 'FAIL'}")
    print("=" * 78)
    return 0 if (ok_current and ok_neg) else 1


if __name__ == "__main__":
    raise SystemExit(main())
