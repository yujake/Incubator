# -*- coding: utf-8 -*-
"""R-52 探针：产物归属登记（`agentflow.artifacts` + CLI）—— 判据在实现本体上测。

判据本体 = `agentflow.artifacts` 的 `record` / `verify_entries` / `owners_of` / `unowned`
（直接调，不另抄比对逻辑）；CLI 只做"动词到函数的翻译"，另用一次真跑证明它通。

- 正控①（登记→核对→归属）：登记一个真文件 ⇒ sha256 与盘上一致、`verify` 报 ok、
  `owners_of` 给出生产者；
- 正控②（**A4 的真读数**）：把 `projects/p2-review/code/*.py` 六个脚本登记进该项目的台账
  ⇒ `unowned` 从"6 个没有归属"变成"0 个"（这就是"它们不在可审计对象图里"的机器判据）；
- 负控①（注入：篡改文件）⇒ `verify` 必须报 `changed`（不是 ok）；
- 负控②（注入：删除文件）⇒ 必须报 `missing`（不是 changed、不是 ok）；
- 负控③（注入：坏行）⇒ `read_ledger` 逐条报出坏行，且 `verify` 不把它读成"干净"；
- 负控④（fail-closed）：登记不存在的文件 ⇒ 拒收，且台账**一个字节都没多**；
- 负控⑤（fail-closed）：登记越界路径 ⇒ 拒收，台账不变；
- 负控⑥（不许误报）：已登记的路径不许出现在 `unowned` 里。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

AGENTFLOW = pathlib.Path(r"D:\Incubator\agentflow")
sys.path.insert(0, str(AGENTFLOW / "src"))
from agentflow import artifacts as A                     # noqa: E402

P2 = pathlib.Path(r"D:\Incubator\projects\p2-review")
RESULTS: list[dict] = []
EXIT = 0


def note(item: str, ok: bool, reading: str) -> None:
    RESULTS.append({"item": item, "ok": bool(ok), "reading": reading})
    print(f"  [{'PASS' if ok else 'FAIL'}] {item}\n        {reading}")


def lines(root: pathlib.Path) -> int:
    p = A.ledger_path(root)
    return len(p.read_text(encoding="utf-8").splitlines()) if p.is_file() else 0


def main() -> int:                                        # noqa: C901
    global EXIT
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="r52-"))
    (scratch / "out").mkdir()
    f = scratch / "out" / "report.md"
    f.write_text("第一版内容", encoding="utf-8")

    # ---- 正控①
    e = A.record(scratch, path="out/report.md", producer="G", kind="report", task_id="t-0001")
    checks = A.verify_entries(scratch)
    owners = A.owners_of(scratch, "out/report.md")
    note("正控①：登记 → 核对 ok → 归属给出生产者",
         e["sha256"] == A.sha256_of(f) and [c["status"] for c in checks] == ["ok"]
         and [o["producer"] for o in owners] == ["G"],
         f"sha256={e['sha256'][:16]} bytes={e['bytes']} status={[c['status'] for c in checks]} "
         f"owners={[(o['producer'], o['kind'], o['task_id']) for o in owners]}")

    # ---- 负控①：篡改
    f.write_text("第二版内容（被改过）", encoding="utf-8")
    st = [c["status"] for c in A.verify_entries(scratch)]
    note("负控①（注入·篡改文件）：必须报 changed",
         st == ["changed"], f"status={st}")

    # ---- 负控②：删除
    f.unlink()
    st2 = [c["status"] for c in A.verify_entries(scratch)]
    note("负控②（注入·删除文件）：必须报 missing（不是 changed）",
         st2 == ["missing"], f"status={st2}")

    # ---- 负控③：坏行
    with A.ledger_path(scratch).open("a", encoding="utf-8") as fh:
        fh.write("{\"path\": \"out/report.md\", 这行坏了\n")
    recs, bad = A.read_ledger(scratch)
    summ = A.summarize(scratch)
    note("负控③（注入·坏行）：逐条报出且坏行不为零",
         len(recs) == 1 and len(bad) == 1 and summ["bad_lines"] == 1,
         f"records={len(recs)} bad_lines={len(bad)} summary.status={summ['status']}")

    # ---- 负控④/⑤：fail-closed（拒收后台账一个字节都不许多）
    before = lines(scratch)
    refusals = []
    for bad_path in ("out/根本没有这个文件.md", "../越界.md"):
        try:
            A.record(scratch, path=bad_path, producer="G")
            refusals.append((bad_path, "竟然接受了"))
        except A.ArtifactError as exc:
            refusals.append((bad_path, str(exc)[:46]))
    after = lines(scratch)
    note("负控④⑤（fail-closed）：不存在的文件与越界路径都拒收，台账不变",
         all("竟然" not in r[1] for r in refusals) and before == after,
         f"before={before} after={after} ｜ " + " ｜ ".join(f"{p}: {m}" for p, m in refusals))

    # ---- 正控②：A4 的真读数（p2-review 的六个脚本）
    code_dir = P2 / "code"
    scripts = sorted(code_dir.glob("*.py"))
    before_unowned = A.unowned(P2, scripts)
    already = [A.rel_path(P2, s) for s in scripts if A.owners_of(P2, A.rel_path(P2, s))]
    note("正控②-a：登记前，这六个脚本**没有**归属登记（A4 的机器判据）",
         len(before_unowned) + len(already) == len(scripts) and len(scripts) > 0,
         f"code/*.py 共 {len(scripts)} 个：未登记 {len(before_unowned)} 个、"
         f"已登记 {len(already)} 个；未登记清单={before_unowned}")

    recorded = 0
    for s in scripts:
        rel = A.rel_path(P2, s)
        if A.owners_of(P2, rel):
            continue
        A.record(P2, path=rel, producer="M", kind="script", task_id="",
                 note="A4/R-52：产生验收读数的脚本登记（sha256 见台账）")
        recorded += 1
    after_unowned = A.unowned(P2, scripts)
    note("正控②-b：登记之后 `unowned` 为空（归属面收口）",
         after_unowned == [],
         f"本次新登记 {recorded} 条；仍无归属 {after_unowned}")

    # ---- 负控⑥：已登记的路径不许出现在 unowned 里
    note("负控⑥（不许误报）：已登记的路径不在 unowned 里",
         "code/acceptance.py" not in A.unowned(P2, [P2 / "code" / "acceptance.py"]),
         f"acceptance.py 的 unowned={A.unowned(P2, [P2 / 'code' / 'acceptance.py'])}")

    # ---- 正控③：CLI 真跑（动词翻译层）
    proc = subprocess.run(
        [sys.executable, "-m", "agentflow.cli", "--plain", "--root", str(P2),
         "artifacts", "verify"],
        cwd=str(AGENTFLOW), env={"PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8",
                                 "PYTHONUTF8": "1", "SYSTEMROOT": "C:\\Windows"},
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    note("正控③：CLI `artifacts verify` 真跑通（退出码 0/1 都算通，2 = 没查成）",
         proc.returncode in (0, 1), f"exit={proc.returncode}；末行={tail[0][:120]!r}")

    # ---- 真项目读数（写进登记册用）
    print("\n[live] projects/p2-review 台账读数：")
    print("  " + json.dumps(A.summarize(P2), ensure_ascii=False))
    rep = A.render_markdown(P2)
    print(f"  render_markdown：{len(rep.encode('utf-8'))} 字节 / {rep.count(chr(10))} 行")

    ok = all(r["ok"] for r in RESULTS)
    print(f"\nR-52: {sum(1 for r in RESULTS if r['ok'])}/{len(RESULTS)} 通过")
    print("REPRO_RESULT: " + json.dumps({"ok": ok, "checks": RESULTS}, ensure_ascii=False,
                                        sort_keys=True))
    EXIT = 0 if ok else 1
    return EXIT


if __name__ == "__main__":
    sys.exit(main())
