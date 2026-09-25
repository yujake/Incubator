"""流水线结果速查：打印问题表、报告表与 D 报告里的证据片段。

用途：验证 D 的"按代号溯源"是否真的取到了表述。
历史背景：D 曾经报告"L1/L2 均为空"，而工具其实是好的 —— 所以这个脚本专门把
「现有证据」一节原文抓出来，避免再靠转述判断。

用法：python tools/inspect_pipeline.py [工作区目录]
"""

from __future__ import annotations

import json
import pathlib
import sys

DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "pipelinedemo"


def main() -> int:
    root = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT
    data = root / "data"

    q = json.loads((data / "research_questions.json").read_text(encoding="utf-8"))["rows"]
    print(f"=== research_questions：{len(q)} 行 ===")
    for r in q:
        print(f"  {r['question_id']} [{r['status']}/{r['priority']}] origin={r.get('origin', '')!r}")
        print(f"      concepts={r.get('related_concept_ids')} rels={r.get('related_relation_ids')}")
        print(f"      waiting={r.get('waiting_request_ids')} gap_reason={(r.get('gap_reason') or '')[:70]!r}")

    rep = json.loads((data / "analysis_reports.json").read_text(encoding="utf-8"))["rows"]
    print(f"\n=== analysis_reports：{len(rep)} 行 ===")
    for r in rep:
        print(f"  {r['report_id']} kind={r['kind']} path={r.get('markdown_path')}")

    reqs = json.loads((data / "search_requests.json").read_text(encoding="utf-8"))["rows"]
    print(f"\n=== search_requests：{len(reqs)} 行 ===")
    for r in reqs:
        print(f"  {r['request_id']} by={r.get('submitted_by')} mode={r['mode']} done={r['done']} "
              f"outcome={r.get('outcome')} topic={r['topic'][:40]!r}")
        print(f"      lit={r.get('result_lit_ids')} err={(r.get('last_error') or '')[:60]!r}")

    # D 报告里的证据片段
    reports_dir = root / "reports"
    d_reports = sorted(reports_dir.glob("*-research.md")) if reports_dir.exists() else []
    if not d_reports:
        print("\n（没有 D 报告）")
        return 0
    latest = d_reports[-1]
    print(f"\n=== D 报告 {latest.name} 的「现有证据」片段 ===")
    text = latest.read_text(encoding="utf-8")
    marker = "**现有证据"
    for chunk in text.split(marker)[1:]:
        seg = chunk.split("**初步分析**")[0]
        lines = [ln for ln in seg.splitlines() if ln.strip()][:6]
        print("  " + marker + lines[0] if lines else "")
        for ln in lines[1:]:
            print("   " + ln[:150])
        print("  ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
