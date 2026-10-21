"""角色 D 的动作 `propose_question`（`draft/37` §115）：把一句话研究问题落成台账一行。

## 为什么需要这个动作（真机读数逼出来的）

T2 第 1 趟（从零做一轮研究）里，主控手上一件可召唤的动作都没法把第一个研究问题立起来：

- `submit_gaps(qid)` / `research(qid)` / `consider(qid)` / `assess(qid)` / 
`adjudicate(qid)` /`trace_question(qid)` / `probe_c(qid)` —— 全部要求 qid 已经存在；- 
`run_round(report)` 要一份 C 的分析报告（那是 `pipeline` 的 C→D 路）；- `ingest(report)` 读的也是 C 的报告；
- `write_report(out_path=None) -> str` 只写文件、不落表。

创建路径只有两条，都不在 D 的可召唤动作面上：`pipeline`（C→D）与 D 的内部工具`research.submit_gap` —— 而工具只能由 D 自己的模
型循环调用，主控够不到。于是那一趟 R1（立起研究问题）永远是 0 行，而这不是"模型不干活"。

## 与既有实现的关系（一份写入口）

行的构造与号段分配与 `agent_d/adjudicate.py` 里那次"新建等价问题"走同一条路：`tx.alloc_id("question")` + 
`S.ResearchQuestion(...).validate()` + `tx.upsert`，并且同样带防重号的那段防御（`counters` 落后于表时 
`alloc_id` 会发出已占用的号，而 `tx.upsert` 是按主键替换 ⇒ 会静默覆盖已有行）。
"""
from __future__ import annotations

from ._support import S
from ..refusals import refuse

#: 合法的问题种类与优先级（与 `schema` 的受控词表同源，不另写一份）。
#:
#: 名字刻意不带 `_KINDS` 后缀（`draft/37` §118 的机械判据逼出来的）：
#: `src/agentflow/schema.py` 的注释用裸词 `_KINDS` 举"别这样起名"的例子，而
#: `tests/test_r5_orchestration_cost.py` 的登记表逐条记着"这个 token 全仓只有文本提及、
#: 没有真符号" —— 我在这里定义一个 `_KINDS` 会让那条登记过期（判据当场红），
#: 而且它会让 `tools/vocab_census.py` 的 `VOCAB_SUFFIXES` 把这里当成一张受控词表。
_KIND_VALUES = tuple(getattr(S, "QUESTION_KINDS", ("gap",)))
_PRIORITY_VALUES = tuple(getattr(S, "PRIORITIES", ("high", "medium", "low")))


class _ProposeQuestion:
    def propose_question(
        self,
        *,
        question: str,
        kind: str = "gap",
        priority: str = "medium",
        gap_reason: str = "",
        notes: str = "",
    ) -> dict:
        """把一句话研究问题落成 `research_questions` 一行，返回 `{'ok', 'question_id', 'row'}`。

        从零做研究的第一步是"把要研究什么写下来"—— 这一步此前在动作面上不存在
        （见模块 docstring）。拒绝走统一形态（`agentflow.refusals.refuse`），
        所以主控在台账里看到的是 `refused / invalid_params`，而不是一个异常。
        """
        text = str(question or "").strip()
        if not text:
            return refuse("bad_question",
                          "question 不能为空 —— 空问题立不起来任何研究（零写入）")
        if kind not in _KIND_VALUES:
            return refuse("bad_kind", f"kind 必须是 {_KIND_VALUES} 之一，收到 {kind!r}")
        if priority not in _PRIORITY_VALUES:
            return refuse("bad_priority",
                          f"priority 必须是 {_PRIORITY_VALUES} 之一，收到 {priority!r}")

        with self.store.tx("research_questions", actor=self.actor,
                           note="propose_question") as tx:
            qid = tx.alloc_id("question")
            # 防御：`counters` 落后于表时 `alloc_id` 可能发出已占用的号，
            # 而 `tx.upsert` 是按主键替换 ⇒ 会静默覆盖已有行（既不报重复也不报错）。
            while tx.find("research_questions", question_id=qid) is not None:
                qid = tx.alloc_id("question")
            row = S.ResearchQuestion(
                question_id=qid,
                question=text,
                origin=str(getattr(self, "actor", "") or "agent-D"),
                related_concept_ids=[],
                related_relation_ids=[],
                evidence_lit_ids=[],
                waiting_request_ids=[],
                contradiction_relation_ids=[],
                contradiction_request_ids=[],
                relation_chain=[],
                kind=str(kind),
                priority=str(priority),
                status="open",
                gap_reason=str(gap_reason or ""),
                notes=str(notes or ""),
                created_at=S.now_iso(),
                updated_at=S.now_iso(),
            )
            try:
                row.validate()
            except ValueError as exc:  # 形状不对就整笔不写（不许留半行）
                return refuse("bad_row", f"这一行过不了 schema：{exc}（整笔不写）")
            data = row.to_dict()
            tx.upsert("research_questions", data, note="propose_question")
            return {"ok": True, "question_id": qid, "row": data,
                    "note": ("立起来 ≠ 有进展：status=open 是「要研究」这一档，"
                             "后续的 assess / consider / adjudicate 才推进它")}
