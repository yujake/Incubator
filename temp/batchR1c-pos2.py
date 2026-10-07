# -*- coding: utf-8 -*-
"""R1c **新正控**（口径裁决①）：3 条审计各有**不同的观察面** ⇒ 必须 approved。

## 为什么另立这条正控（而不是继续用 `reaudit5-R1b-pos.py`）

`temp/reaudit5-R1b-pos.py` 的三条审计**共用同一句** `--audit-scope 'target.py VALUE bump'`
⇒ 观察面只有 1 个。那正是 `R5-R1b-1` 说的弱点：它看起来像三次独立观察，其实是
**同一个面被数了三次**。裁决①：那条探针**原样保留**（它是 R1b 的历史证据），
但它不再是本批的地基；本批的地基是这条脚本 —— 三条审计的 scope 分别指向目标里
**不同的标识符**（`f` / `g` / `h`），证据文件各自记录**不同的观察**。

## 判据（跑完必须成立）

    exit=0 / verdict=clean / approval_status=approved / clean_audits=3 /
    distinct_auditors=3 / distinct_dimensions=3 / observation_surfaces=3（两两不相交）

## 探针自校（两个方向都跑）

- 必然通过：上面的合规场景；
- 必然失败：把其中两条的 scope 改成同一个落点（= 旧正控的形态）⇒ 必须 unapproved。

只读 `agentflow/`；一切写入落在 `temp/batchR1c-pos2/` 下。
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
BASE = Path(r"D:\Incubator\temp\batchR1c-pos2")
WS = BASE / "ws"
TARGET_REL = "src/target.py"

MANIFEST = (
    "[category: auth-audit] 七、权限与审计（谁能做什么，以及谁做过了什么）\n"
    "\n"
    "src/target.py  [category: auth-audit] 合成工作区的被审对象：符号 `alpha` 与 `beta` 与 `gamma`\n"
)

#: 目标里有三个**不同的**符号，供三条审计各占一个观察面。
#: （名字刻意用 5 个字母：`_scope_tokens` 只收长度 ≥3 的 token，单字符符号名会被
#:  当成"不是一个符号名"滤掉 —— 那是判据本来的口径，不是这里的特例。）
TARGET_SRC = (
    '"""合成被审对象：三个不同的符号 alpha / beta / gamma。"""\n'
    "\n"
    "alpha = 1\n"
    "beta = 2\n"
    "\n"
    "\n"
    "def gamma() -> int:\n"
    "    return alpha + beta\n"
)

NC = ("负控：拿同一套判据去审改前那一版（`git show HEAD:src/target.py`）—— "
      "改前那一版没有 `gamma` 这个符号，判据必须报红，否则说明它没有分辨力。")

#: 三条审计：`(auditor, dimension, scope, 各自不同的观察记录）`
AUDITS = [
    ("pos2-A1", "axes", "target.py alpha",
     "在目标里逐行读到 `alpha = 1`（模块级常量定义，值 1）；"
     "整份文件里 alpha 只在这一处被绑定，没有第二处赋值。"),
    ("pos2-A2", "roles", "target.py beta",
     "在目标里逐行读到 `beta = 2`（模块级常量定义，值 2）；"
     "它与 alpha 分处两行，绑定互不覆盖，可以分别改动。"),
    ("pos2-A3", "errors", "target.py gamma",
     "在目标里逐行读到 `def gamma() -> int:` 与 `return alpha + beta`（函数定义，返回两个常量之和）；"
     "函数体只有一条 return，没有异常分支，因此没有可吞掉的异常。"),
]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(*argv: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(GATE), *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(REPO),
    )
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))


def fingerprint() -> dict:
    t = GATE.read_text(encoding="utf-8")
    return {"sha256": sha256(GATE), "lines": len(t.splitlines()),
            "has_rule2": "观察面数 ≥ 维度数" in t}


def fresh() -> str:
    if WS.exists():
        shutil.rmtree(WS)
    (WS / "src").mkdir(parents=True)
    (WS / "temp").mkdir(parents=True)
    (WS / TARGET_REL).write_text(TARGET_SRC, encoding="utf-8", newline="\n")
    (WS / ".noai-paths").write_text(MANIFEST, encoding="utf-8", newline="\n")
    return sha256(WS / TARGET_REL)


def evidence_text(who: str, dim: str, digest: str, scope: str, observation: str) -> str:
    return (
        f"审计者标识（独立词）：{who}\n"
        f"维度：{dim}\n"
        f"开审版本 sha256 = {digest}\n"
        f"覆盖 scope 符号：{scope}\n"
        f"{observation}\n"
        f"{NC}\n"
    )


def scenario(label: str, *, collapse: bool) -> dict:
    """跑完整场景。`collapse=True` 时把三条的 scope 改成同一个落点（旧正控形态）。"""
    print("=" * 78)
    print(f"场景：{label}")
    print("=" * 78)
    fp = fingerprint()
    print(f"  探针指纹   gate sha256={fp['sha256']}  行数={fp['lines']}  "
          f"判据 2（观察面数 ≥ 维度数）在源码里？ {fp['has_rule2']}")
    digest = fresh()
    print(f"  合成工作区 = {WS}")
    print(f"  被审对象 {TARGET_REL} sha256 = {digest}")

    rc, out = run("--root", str(WS), "--paths", TARGET_REL, "--baseline")
    print(f"\n  $ --baseline                        exit={rc}")

    for who, dim, scope, observation in AUDITS:
        eff_scope = "target.py alpha" if collapse else scope
        ev_rel = f"temp/EV-{who}.txt"
        (WS / ev_rel).write_text(
            evidence_text(who, dim, digest, eff_scope, observation),
            encoding="utf-8", newline="\n")
        rc, out = run(
            "--root", str(WS), "--record-audit", TARGET_REL,
            "--auditor", who, "--dimension", dim,
            "--evidence", ev_rel, "--evidence-path", ev_rel,
            "--negative-control", NC,
            "--audit-scope", eff_scope,
            "--audit-started-sha256", digest,
            "--independence", f"我是子审计代理 {who}，与该条目的作者不是同一主体（署名者未知）",
        )
        first = out.strip().splitlines()[0] if out.strip() else ""
        print(f"\n  $ --record-audit {who}/{dim}  scope={eff_scope!r}   exit={rc}")
        print(f"      {first[:150]}")
        for ln in out.strip().splitlines():
            if "观察面" in ln or "⚠️" in ln:
                print(f"      {ln.strip()[:150]}")

    entry = json.loads((WS / ".noai-approvals.json").read_text(encoding="utf-8"))["entries"][0]
    print("\n  -- 盘上台账里 audits 逐条 --")
    for a in entry["audits"]:
        print(f"      auditor={a['auditor']:<10} dim={a['dimension']:<7} "
              f"scope={a['scope']!r:<20} ev={a['evidence_path']!r}")

    rc, out = run("--root", str(WS), "--paths", TARGET_REL, "--check-approvals", "--json")
    j = json.loads(out)
    ap = j["approvals"][0]
    reading = {
        "exit": rc,
        "verdict": j["verdict"],
        "status": ap["approval_status"],
        "reason": ap["approval_reason"],
        "clean_audits": len(ap.get("clean_audits") or []),
        "distinct_auditors": ap.get("distinct_auditors"),
        "distinct_dimensions": list(ap.get("distinct_dimensions") or []),
        "observation_surfaces": ap.get("observation_surfaces"),
        "audit_timestamps": ap.get("audit_timestamps"),
        "evidence_problems": ap.get("evidence_problems"),
    }
    print(f"\n  $ --check-approvals --json           exit={rc}")
    for k, v in reading.items():
        print(f"      {k:<22} = {v}")
    print(f"      detail                 = {str(ap.get('detail'))[:300]}")
    return reading


def main() -> int:
    BASE.mkdir(parents=True, exist_ok=True)
    print("#" * 78)
    print("# A. 新正控：3 条审计各有**不同**的观察面")
    print("#" * 78)
    ok = scenario("新正控（scope 分别指向 f / g / h）", collapse=False)
    good = (
        ok["exit"] == 0 and ok["verdict"] == "clean" and ok["status"] == "approved"
        and ok["clean_audits"] == 3 and ok["distinct_auditors"] == 3
        and len(ok["distinct_dimensions"]) == 3
        and len(ok["observation_surfaces"] or []) == 3
    )
    print(f"\n  >>> 新正控断言（exit=0 / clean / approved / clean_audits=3 / 3×3 / 观察面=3）"
          f" ⇒ {'通过' if good else '不通过'}")
    print(f"      （旧正控 `temp/reaudit5-R1b-pos.py` 的形态 —— 三条共用一个观察面 —— "
          f"在本判据下会被判 unapproved；那条探针原样保留，仅作为 R1b 的历史证据）")

    print()
    print("#" * 78)
    print("# B. 探针自校：把三条的 scope 改成同一个落点（旧正控形态）⇒ 必须不通过")
    print("#" * 78)
    bad = scenario("自校（三条 scope 全写 'target.py alpha'）", collapse=True)
    calibrated = bad["status"] != "approved"
    print(f"\n  >>> 自校断言（同观察面 ⇒ 非 approved） ⇒ {'通过' if calibrated else '不通过'}")

    print()
    print("=" * 78)
    print(f"总结：新正控 {'PASS' if good else 'FAIL'} / 自校 {'PASS' if calibrated else 'FAIL'}")
    print("=" * 78)
    return 0 if (good and calibrated) else 1


if __name__ == "__main__":
    raise SystemExit(main())
