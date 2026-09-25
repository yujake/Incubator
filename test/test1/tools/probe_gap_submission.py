"""诊断：D 在"证据不足"时是否真的会向 A 提交查询请求？

这是用户原话里的关键一环：**"遇知识不足就向智能体A提交查询请求"**。
`pipeline --no-search` 的摘要里 `requests_total` 一直是 0，需要区分两种情况：

- **(a) 判据算出来的**：这两条问题的证据确实充分（3 跳全部 `quote_verified=True`），
  所以"不提问"是**正确结论**；
- **(b) 整段被跳过**：因为没接线 A，所以根本没走到"评估→提问"。

本脚本构造一个**证据必然不足**的问题（相关概念之间没有任何关系），
直接调 D 的 `assess` 与 `submit_gaps`，然后检查 `search_requests` 表是否真的多了一行。
`agent_a=None`（不接线 A）也会照测 —— 因为"提交请求"只是一次**本地写表**，不需要 A 在线。

用法：python tools/probe_gap_submission.py
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from abflow import schema as S  # noqa: E402
from abflow.agent_d import AgentD  # noqa: E402
from abflow.store import Store  # noqa: E402
from abflow.tools import build_registry  # noqa: E402


class FakeReport:
    """最小可用的 C 报告替身：一个 hottest 结果 + 两个**互不相关**的概念。

    关键点：`related_relation_ids` 为空 ⇒ 按 §4.4 的判据（关键词 0 命中）必然判为证据不足。
    """

    def __init__(self, qid_placeholder: str = "0000") -> None:
        self.kind = "hottest"
        self.request = "诊断：构造一个证据必然不足的问题"
        self.params = {"top_n": 2}
        self.summary = "诊断用报告"
        self.payload = {
            "top": [
                {"concept_id": "0000", "name": "孤立甲", "occurrences": 0},
                {"concept_id": "0001", "name": "孤立乙", "occurrences": 0},
            ],
            "hot_ids": [],
        }
        self.markdown = "# 诊断报告\n"
        self.warnings: list[str] = []
        self.truncated = False

    def persist(self) -> dict:
        return {"report_id": "0000", "markdown_path": None, "abs_path": None}


def main() -> int:
    td = pathlib.Path(tempfile.mkdtemp(prefix="abflow-gapprobe-"))
    try:
        st = Store(td / "ws")
        st.init()
        # 两个概念，彼此没有任何关系 → 证据必然不足
        with st.tx("concepts", actor="probe") as tx:
            for cid, name in (("0000", "孤立甲"), ("0001", "孤立乙")):
                tx.upsert("concepts", S.Concept(
                    concept_id=cid, name=name, definition="",
                    related_concepts=[], normalized_name=name, aliases=[],
                    definition_source_lit_id=None,
                    created_at=S.now_iso(), updated_at=S.now_iso(),
                ).to_dict())

        reg = build_registry(store=st, workspace_root=td / "ws").registry
        d = AgentD(st, tools=reg)

        rep = FakeReport()
        qids = d.ingest(rep)
        print(f"[1] ingest 产出问题：{qids}")

        for qid in qids:
            ev = d.trace_question(qid)
            a = d.assess(qid)
            print(f"[2] {qid} assess → {json.dumps(a, ensure_ascii=False)[:200]}")
            sub = d.submit_gaps(qid)
            print(f"[3] {qid} submit_gaps → {sub}")

        reqs = st.rows("search_requests")
        print(f"\n[4] search_requests 行数 = {len(reqs)}")
        for r in reqs:
            print(f"      {r['request_id']} by={r.get('submitted_by')} mode={r['mode']} "
                  f"done={r['done']} topic={r['topic'][:40]!r}")
            print(f"          desc={(r.get('content_description') or '')[:80]!r}")

        q = st.rows("research_questions")
        print(f"\n[5] research_questions 状态：")
        for r in q:
            print(f"      {r['question_id']} status={r['status']} waiting={r['waiting_request_ids']} "
                  f"gap_reason={(r.get('gap_reason') or '')[:60]!r}")

        ok = len(reqs) > 0 and any(r["status"] == "needs_evidence" for r in q)
        print(f"\n结论：{'✅ D 会在证据不足时提交请求（本地写表，不需要 A 在线）' if ok else '❌ D 没有提交请求'}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
