"""写作期探针：把一个 D 问题推进到 needs_evidence，观察台账的产生与 verify 检查。

流程：造数据集 → 跑 pipeline（C+D）→ 再让 D 从全部已登记报告 ingest（含 cold）
→ 那个"完全孤立概念"的问题必然证据不足 → 提交 gap → 台账产生。
随后跑 verify，观察 ledger_* 检查项是否生效。

用法：python tools/probe_gap_ledger.py [目标工作区]
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentflow import schema as S  # noqa: E402
from agentflow.agent_d import AgentD, install_d_tools  # noqa: E402
from agentflow.pipeline import run_pipeline  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools.research_tools import LEDGER_FILE  # noqa: E402


def main() -> int:
    dest = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "gapprobe"
    if dest.exists():
        import shutil

        shutil.rmtree(dest)
    st = Store(dest)
    st.init(force=True)

    # 直接拷 pipelinedemo 的三张表（省掉造数据）
    src = ROOT / "pipelinedemo" / "data"
    with st.tx("concepts", "relations", "literature", actor="probe", note="seed") as tx:
        for t in ("concepts", "relations", "literature"):
            for r in json.loads((src / f"{t}.json").read_text(encoding="utf-8"))["rows"]:
                tx.upsert(t, r)
    st._atomic_write(st.data / "counters.json",
                     {"schema_version": S.SCHEMA_VERSION,
                      "counters": {"lit": 9, "concept": 10, "relation": 15,
                                   "question": 0, "report": 0}})

    print("===== 1. 跑 C 的 cold 分析（产生一个'孤立概念'的研究点） =====")
    out = run_pipeline(
        st,
        request="研究冷门概念",
        gap_rounds=1,
        config={"agent_d": {"dedup_by_origin": True}},
        resume=False,
    )
    print(json.dumps({"report_ids": out["report_ids"], "questions": out["questions"],
                      "requests_submitted": out.get("requests_submitted")},
                     ensure_ascii=False, indent=2))

    print("\n===== 2. 让 D 从全部已登记报告 ingest（含 paths 与 cold） =====")
    d = AgentD(st, config={"dedup_by_origin": False}, tools=install_d_tools(st))
    for r in st.rows("analysis_reports"):
        res = d.run_round(r)
        print(f"  报告 {r['report_id']} kind={r['kind']} ingested={res.get('ingested')} "
              f"submitted={res.get('submitted')} assessed="
              f"{[(a['question_id'], a['criteria']) for a in res.get('assessed', [])]}")

    print("\n===== 3. research_questions 现状 =====")
    for r in st.rows("research_questions"):
        print(f"  {r['question_id']} status={r['status']} priority={r['priority']} "
              f"waiting={r['waiting_request_ids']} rels={r['related_relation_ids']}")
        print(f"      gap_reason={(r.get('gap_reason') or '')[:160]}")

    print("\n===== 4. search_requests 现状 =====")
    for r in st.rows("search_requests"):
        print(f"  {r['request_id']} submitted_by={r.get('submitted_by')} mode={r['mode']} "
              f"done={r['done']} outcome={r.get('outcome')} topic={r['topic']!r}")
        print(f"      description={(r.get('description') or '')[:200]}")

    lp = dest / "data" / LEDGER_FILE
    print(f"\n===== 5. 台账 {LEDGER_FILE} 存在={lp.exists()} =====")
    if lp.exists():
        print(lp.read_text(encoding="utf-8"))

    print("\n===== 6. verify（观察 ledger_* 检查） =====")
    from agentflow.verify import verify_all

    rep = verify_all(st)
    print(f"  错误 {rep.error_count()} / 警告 {rep.warning_count()}；checked={rep.checked}")
    for i in rep.issues:
        print(f"  - [{i.level}] {i.code} {i.where}: {i.message[:150]}")

    print("\n===== 7. 删掉台账后再 verify（受控偏离的代价：退化为可能重复提问一次） =====")
    if lp.exists():
        lp.unlink()
    rep2 = verify_all(st)
    print(f"  错误 {rep2.error_count()} / 警告 {rep2.warning_count()}")
    for i in rep2.issues:
        print(f"  - [{i.level}] {i.code} {i.where}: {i.message[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
