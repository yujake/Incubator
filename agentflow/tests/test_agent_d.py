"""智能体 D（`agent_d.py`）的性质测试。

D 的核心是管理"问题 → 证据 → 缺口 → 新证据"的循环（DESIGN-TOOLS §4），
这里锁住五条最容易悄悄做错的性质：

- `ingest` 提取的问题必须带代号溯源（origin 里有报告号与关系代号链，
  `related_*_ids` 非空且都真实存在）；
- `assess` 的判据必须可核实（关键词零命中 / 度数低且无可核验引文 / 表述互相矛盾）；
- `submit_gap` 对"已有未完成请求"的问题不得重复提交；
- `poll` 只看等待集 + 请求终局 + 文献 processed（这是"D 继续"能自动接上的唯一依据）；
- 置信度不许拔高：证据不足就是 `low`，LLM 钩子只能调低。

全部离线、确定性：`trace_tools` 走真身（它已经落地），不联网、不调 LLM。
"""

from __future__ import annotations

import json

import pytest

from agentflow import conceptrows as CR
from agentflow import interactions as X
from agentflow import schema as S
from agentflow.agent_c import AgentC
from agentflow.agent_d import AgentD, analyze_gaps, detect_contradictions, evidence_confidence, install_d_tools
from agentflow.store import Store
from agentflow.tools import research_tools as RT
from agentflow.verify import verify_all

from conftest import add_concept, add_literature, add_relation, add_request, sync_counters
from demo_dataset_helper import build_demo

TS = "2026-01-01T00:00:00+00:00"


# ============================================================ 辅助


def add_question(st: Store, qid: str, **kw) -> dict:
    """插入一条合法的 research_questions 行（conftest 里没有这个问题表的构造器）。"""
    row = S.ResearchQuestion(
        question_id=qid,
        question=kw.get("question", "这是一个研究问题"),
        origin=kw.get("origin", "C:paths:0000:0000"),
        related_concept_ids=list(kw.get("related_concept_ids", [])),
        related_relation_ids=list(kw.get("related_relation_ids", [])),
        status=kw.get("status", "open"),
        priority=kw.get("priority", "medium"),
        evidence_lit_ids=list(kw.get("evidence_lit_ids", [])),
        waiting_request_ids=list(kw.get("waiting_request_ids", [])),
        # 批 R22 补上两格：I2 的对账读数需要 `kind="contradiction"` 与它自己的请求台账
        # （`add_question` 从前不传这两格 ⇒ 用它的用例永远造不出矛盾问题）。
        kind=kw.get("kind", "gap"),
        contradiction_relation_ids=list(kw.get("contradiction_relation_ids", [])),
        contradiction_request_ids=list(kw.get("contradiction_request_ids", [])),
        notes=kw.get("notes", ""),
        created_at=TS,
        updated_at=TS,
    )
    row.validate()
    with st.tx("research_questions", actor="test", note="fixture") as tx:
        tx.upsert("research_questions", row.to_dict())
    return row.to_dict()


def _opaque_store(root) -> Store:
    """造一个"关键词必然零命中"的小库：概念名是单字（会被关键词切分过滤掉）。

    关系文本刻意用与问题毫无重叠的记号，用来验证判据 (a)：关键词命中数为 0。
    """
    st = Store(root)
    st.init()
    add_concept(st, "0001", "甲", definition="d", sync=False)
    add_concept(st, "0002", "乙", definition="d", sync=False)
    add_relation(
        st,
        "0000",
        ["0001", "0002"],
        "0000",
        description="zzz qqq",
        quote="zzz qqq",
        quote_verified=None,
        sync=False,
    )
    sync_counters(st)
    return st


class _FakeLLM:
    """只会把置信度往高里写的假 LLM：用来验证"不许拔高"这条硬规则。"""

    def __init__(self, confidence: str = "high") -> None:
        self.confidence = confidence
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return json.dumps(
            {"analysis": "LLM 写的分析", "conclusion": "LLM 的结论", "suggestions": ["看看"], "confidence": self.confidence},
            ensure_ascii=False,
        )


# ============================================================ [1] ingest：代号溯源


def test_ingest_questions_carry_origin_and_real_ids(tmp_path):
    """ingest 产出问题必须带代号溯源：origin 里有报告号与关系代号链，related_*_ids 真实存在。"""
    st = Store(build_demo(tmp_path / "demo"))
    report = AgentC(st).paths("0000", "0002", max_paths=8, request="查询 群 与 域 之间的关系")
    report.persist()
    rid = str(report.report_id)

    agent = AgentD(st)
    created = agent.ingest(report)
    assert created, "一份含 high 路径的报告应当能提出至少一个问题"

    rows = st.rows("research_questions")
    assert len(rows) == len(created) == len(set(created))
    real_relations = {r["relation_id"] for r in st.rows("relations")}
    # 概念行读口走并表过渡层（老字段名投影）：概念住哪张表由那一处决定，
    # 这条判据只关心"问题引用的概念代号真的存在"。
    real_concepts = {r["concept_id"] for r in CR.view(st, shape="legacy")["rows"]}
    expected_chains = {
        "->".join(p["relation_chain"]) for p in report.payload["paths"] if p["level"] in ("high", "medium")
    }
    seen_chains = set()
    for row in rows:
        assert row["origin"].startswith(f"C:paths:{rid}:"), row["origin"]
        chain = row["origin"].split(":", 3)[3]
        assert chain, "origin 里必须带关系代号链"
        seen_chains.add(chain)
        assert set(chain.split("->")) <= real_relations, "origin 里的关系代号必须真实存在"
        assert row["related_concept_ids"], "related_concept_ids 不能为空"
        assert row["related_relation_ids"], "related_relation_ids 不能为空"
        assert set(row["related_concept_ids"]) <= real_concepts
        assert set(row["related_relation_ids"]) <= real_relations
        assert row["status"] == "open" and row["priority"] in S.PRIORITIES
        assert f"来源报告 {rid}" in row["notes"], "问题必须留下它从哪份报告来的"
    assert seen_chains == expected_chains


def test_ingest_then_trace_question_yields_nonempty_l1(tmp_path):
    """回归：ingest 出来的问题在溯源时必须拿到非空的 L1 证据（D 曾误报"L1/L2 均为空"）。"""
    st = Store(build_demo(tmp_path / "demo"))
    report = AgentC(st).paths("0000", "0002", max_paths=8)
    report.persist()
    agent = AgentD(st)
    qid = agent.ingest(report)[0]

    ev = agent.trace_question(qid)
    assert ev["trace_mode"] == "external", "溯源工具存在时不该走降级替身"
    assert ev["claims"], "L1 证据为空 —— 链条没接上"
    assert ev["l2"], "L2 证据为空 —— 概念定义没接上"
    for claim in ev["claims"]:
        assert claim["relation_id"] and claim["concept_pair_key"]
    assert any(t["level"] == "chain" for t in ev["traces"]), "多跳问题应当顺带取回链条的表述"


def test_ingest_same_report_twice_is_idempotent(tmp_path):
    """同一份 C 报告 ingest 两次不得产生重复问题（跨轮次幂等）。"""
    st = Store(build_demo(tmp_path / "demo"))
    report = AgentC(st).paths("0000", "0002", max_paths=8)
    report.persist()
    agent = AgentD(st)
    first = agent.ingest(report)
    assert first
    before = len(st.rows("research_questions"))
    again = agent.ingest(report)
    assert again == []
    assert len(st.rows("research_questions")) == before
    assert agent.last_ingest["merged"] or agent.last_ingest["skipped"], "重复 ingest 必须留下被去重的记录"


def test_ingest_dedups_by_kind_and_relation_chain_across_reports(tmp_path):
    """去重口径是 `(kind, 排序后的关系代号)`：不同报告指向同一条链时不得重复建问题。"""
    st = Store(build_demo(tmp_path / "demo"))
    agent = AgentD(st)
    first = AgentC(st).paths("0000", "0002", max_paths=8)
    first.persist()
    assert agent.ingest(first)

    second = AgentC(st).paths("0000", "0002", max_paths=8)  # 另一次分析：不同 report_id、同样的链
    second.persist()
    assert second.report_id != first.report_id

    before = len(st.rows("research_questions"))
    created = agent.ingest(second)
    assert created == [], "同一个研究点被换了个报告号又提了一遍"
    assert len(st.rows("research_questions")) == before
    assert agent.last_ingest["merged"], "内容等价的候选必须留下「另见报告」的痕迹"
    keys = [tuple(c["content_key"]) for c in agent.last_ingest["candidates"]]
    assert all(k[0] == "paths" and list(k[1]) == sorted(k[1]) for k in keys), "内容键必须是 kind + 排序后的关系代号"


# ============================================================ [2]/[3] assess：可核实判据


def test_assess_zero_keyword_hits_counts_as_insufficient(tmp_path):
    """判据 (a)：关键词在现有关系的引文/描述里 0 命中 ⇒ 证据不足，且中间值可逐项复核。"""
    st = _opaque_store(tmp_path / "ws")
    add_question(
        st,
        "0000",
        question="关于韦伊猜想的证明路径是否已经完整",
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0000"],
    )
    verdict = AgentD(st).assess("0000")
    assert verdict["insufficient"] is True
    assert [c["id"] for c in verdict["criteria"]] == ["a_no_keyword_hit", "b_low_degree_unverified"]
    assert verdict["priority"] == "high", "「库里完全没谈过」应当是高优先级"
    assert verdict["hits"]["distinct_hit_keywords"] == 0
    assert verdict["hits"]["keyword_count"] > 0
    assert sum(verdict["hits"]["per_keyword"].values()) == 0


def test_assess_flags_contradiction_as_high_priority(tmp_path):
    """判据 (c)：两条关键关系给出互相矛盾的表述 ⇒ 优先级 high（这是最有价值的发现）。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0001", "非交换环", definition="d", sync=False)
    add_concept(st, "0003", "交换性条件", definition="d", sync=False)
    add_relation(
        st, "0002", ["0001", "0003"], "0001",
        description="交换性条件不能推广到非交换环。", quote="", quote_verified=None, status="suspect", sync=False,
    )
    add_relation(
        st, "0003", ["0001", "0003"], "0001",
        description="交换性条件可以推广到非交换环。", quote="", quote_verified=None, status="suspect", sync=False,
    )
    sync_counters(st)
    add_question(
        st,
        "0000",
        question="交换性条件能否推广到非交换环",
        origin="C:gaps:0000:0001,0003",
        related_concept_ids=["0001", "0003"],
        related_relation_ids=["0002", "0003"],
        priority="high",
    )

    verdict = AgentD(st).assess("0000")
    assert "c_contradiction" in [c["id"] for c in verdict["criteria"]]
    assert verdict["priority"] == "high"
    assert len(verdict["contradictions"]) == 1
    pair = verdict["contradictions"][0]
    assert pair["relation_ids"] == ["0002", "0003"]
    assert pair["signals"], "矛盾必须给出可核实的信号（否定标记 / 对立词组）"
    assert "可以" in "".join(pair["signals"]) or "不" in "".join(pair["signals"])


def test_analyze_gaps_and_detect_contradictions_are_pure_functions():
    """判据总装是纯函数：同样的关系列表必须给出同样的结论与中间值。"""
    rels = [
        {"relation_id": "0000", "concept_pair_key": "0000|0001", "statement": "A 是 B", "quote_verified": None},
        {"relation_id": "0001", "concept_pair_key": "0000|0002", "statement": "A 不是 C", "quote_verified": False},
    ]
    out = analyze_gaps(["0000", "0001"], rels, keywords=["完全不存在的词"], degree=1, degree_threshold=2, concept_count=2)
    assert out["insufficient"] is True
    assert {c["id"] for c in out["criteria"]} == {"a_no_keyword_hit", "b_low_degree_unverified"}
    assert out["verified_count"] == 0
    assert detect_contradictions(rels) == []
    # 明确矛盾：同一对概念，一句话"可以"、另一句"不能"
    pair = [
        {"relation_id": "0000", "concept_pair_key": "0001|0003", "statement": "条件可以推广"},
        {"relation_id": "0001", "concept_pair_key": "0001|0003", "statement": "条件不能推广"},
    ]
    found = detect_contradictions(pair)
    assert len(found) == 1 and found[0]["relation_ids"] == ["0000", "0001"]


# ============================================================ [4] submit_gap：查重


def test_submit_gap_does_not_resubmit_while_a_request_is_unfinished(tmp_path):
    """同一问题已有未完成请求时不得重复提交（否则会刷爆 A 的队列）。"""
    st = _opaque_store(tmp_path / "ws")
    add_question(st, "0000", question="完全不存在的关键词XYZ", related_concept_ids=["0001", "0002"], related_relation_ids=["0000"])

    reg = install_d_tools(st)
    first = reg.call("research.submit_gap", question_id="0000", topic="甲 乙", mode="topical", description="第一次")
    assert first.ok and first.data["duplicated"] is False
    assert first.data["request_id"] == "r-0001"

    second = reg.call("research.submit_gap", question_id="0000", topic="甲 乙", mode="topical", description="第二次")
    assert second.ok and second.data["duplicated"] is True
    assert second.data["request_id"] is None
    assert "未重复提交" in second.data["reason"]
    assert len(st.rows("search_requests")) == 1, "查重失效：请求表里出现了两条"

    row = st.rows("research_questions")[0]
    assert row["status"] == "needs_evidence", "提交后状态必须与等待集同时落盘"
    assert row["waiting_request_ids"] == ["r-0001"]

    # 同一件事在 AgentD 层再做一遍：方法级也要省掉这次调用
    agent = AgentD(st)
    assert agent.submit_gaps("0000") == []
    assert "未重复提交" in agent.last_submit_skip["reason"]
    assert len(st.rows("search_requests")) == 1


def test_submit_gap_respects_budget_and_reports_it(tmp_path):
    """预算用尽时不提问，但必须把原因写进笔记（静默少提会让报告与事实不符）。"""
    st = _opaque_store(tmp_path / "ws")
    add_question(st, "0000", question="完全不存在的关键词XYZ", related_concept_ids=["0001", "0002"], related_relation_ids=["0000"])
    agent = AgentD(st, config={"max_requests_per_question": 0})
    assert agent.submit_gaps("0000") == []
    assert st.rows("search_requests") == []
    assert "[budget]" in st.rows("research_questions")[0]["notes"]


def test_submit_gap_writes_the_structured_question_id(tmp_path):
    """提交出来的请求行必须带 `for_question_id`（CS-2）。

    为什么值得一条判据：`schema.SearchRequest.for_question_id` 的注释逐字写着它就是
    "该请求是为哪个研究问题服务的（I2 矛盾闭环 / 证据就绪判据都要它）"，
    而同角色的矛盾那一支（`agent_d/adjudicate.py`）一直是填的 —— 只有缺口这一支没填，
    于是消费方只能拿 `content_description` 里的 `[q:NNNN]` 做正则（CS-3）。
    这条判据钉的是"结构化字段真的写进去了"，不是"描述文本里有没有那句话"。
    """
    st = _opaque_store(tmp_path / "ws")
    add_question(st, "0000", question="完全不存在的关键词XYZ", related_concept_ids=["0001", "0002"], related_relation_ids=["0000"])
    reg = install_d_tools(st)
    got = reg.call("research.submit_gap", question_id="0000", topic="甲 乙", mode="topical")
    assert got.ok and got.data["duplicated"] is False, got
    row = st.rows("search_requests")[0]
    assert row["for_question_id"] == "0000", (
        "缺口路径没有写结构化归属 ⇒ I2 闭环与证据就绪判据读不到它是为哪个问题服务的")
    # 查重那一支不许改既有行（"没做"与"做了没结果"要分得开）
    again = reg.call("research.submit_gap", question_id="0000", topic="甲 乙", mode="topical")
    assert again.data["duplicated"] is True
    assert st.rows("search_requests")[0]["for_question_id"] == "0000"


def test_submit_gap_goes_through_the_i7_gate(tmp_path):
    """缺口提交必须过 I7 在途闸门（CS-1：这条路径曾是唯一不过闸门的角色面）。

    在途到上限时，`research.submit_gap` 必须一行都不写，并如实说清是被配额挡下的：
    `request_id is None`、理由里含"已达上限"，而 `duplicated` 仍是 False ——
    它不是"查重挡下的"（那件事由上一支负责），两者压进同一个布尔位调用方就再也分不开了。

    为什么判据长在工具层：`agent_d/submit_gaps.py` 自己那一层预算只挡得住 D 自己；
    工具层才是"任何调用方走这条路"的咽喉（`demo.py`、`agent_c/__main__.py` 的转交、
    手敲的工具调用都从这里过）。

    反真空一并在内：把在途腾出一格 ⇒ 同一条路必须放行（否则"加了闸门"与"把这条路
    整个堵死"在读数上同形）。
    """
    st = _opaque_store(tmp_path / "ws")
    add_question(st, "0000", question="完全不存在的关键词XYZ",
                 related_concept_ids=["0001", "0002"], related_relation_ids=["0000"])
    limit = X.DEFAULTS["max_inflight_requests"]
    with st.tx("search_requests", actor="agent-C", note="fixture") as tx:
        for i in range(limit):
            row = S.SearchRequest(
                request_id=f"r-{i + 1:04d}", timestamp=TS, topic=f"占位主题{i}",
                mode="topical", content_description="", done=False, submitted_by="agent-C",
            )
            row.validate()
            tx.upsert("search_requests", row.to_dict(), note="fixture")

    reg = install_d_tools(st)
    got = reg.call("research.submit_gap", question_id="0000", topic="甲 乙", mode="topical",
                   description="在途满时提问")
    assert got.ok, got
    assert got.data["request_id"] is None, got.data
    assert got.data["duplicated"] is False, (
        "配额挡下不是查重挡下 —— 两者压成同一个布尔位，调用方就分不开了")
    assert "已达上限" in got.data["reason"], got.data["reason"]
    assert got.data["open_requests"] == [], got.data
    assert len(st.rows("search_requests")) == limit, "被挡下时一行都不许写"
    qrow = st.rows("research_questions")[0]
    assert qrow["waiting_request_ids"] == [], (
        "被挡下的请求不许进等待集（否则 D 会永远等一条不存在的请求）")
    assert qrow["status"] == "open", "被挡下时状态也不许动"

    # 反真空：腾出一格 ⇒ 放行，且行的 priority 与闸门现算的那个值一致。
    with st.tx("search_requests", actor="agent-C", note="fixture") as tx:
        tx.delete("search_requests", "r-0001")
    room = reg.call("research.submit_gap", question_id="0000", topic="甲 乙", mode="topical",
                    description="留出一格")
    assert room.ok and room.data["duplicated"] is False, room
    assert room.data["request_id"] is not None, room.data
    new_row = next(r for r in st.rows("search_requests")
                   if r["request_id"] == room.data["request_id"])
    assert new_row["priority"] == S.SUBMITTER_DEFAULT_PRIORITY["agent-D"], new_row
    assert new_row["priority"] == "medium", "改前那一行的 priority 就是 medium，本批不许改行为"


def test_the_per_question_budget_prefers_the_structured_field(tmp_path):
    """每问题预算优先读 `for_question_id`，老行（没有那个键）才回落到描述文本（CS-3）。

    判据两头都钉：① 结构化字段在、描述里没有 `[q:NNNN]` ⇒ 也算进那一问；
    ② 结构化字段为空、描述里有 ⇒ 仍按老口径算（并表之前的行不能被读成"不属于任何问题"）。
    """
    st = _opaque_store(tmp_path / "ws")
    add_question(st, "0000", question="完全不存在的关键词XYZ", related_concept_ids=["0001", "0002"], related_relation_ids=["0000"])
    agent = AgentD(st, config={"max_requests_per_question": 1, "max_total_requests": 10})

    # ① 结构化归属（描述里故意不写 [q:]）
    with st.tx("search_requests", actor="agent-D", note="t") as tx:
        tx.upsert("search_requests", {
            "request_id": "r-0001", "timestamp": "2026-01-01T00:00:00+00:00",
            "topic": "甲", "mode": "topical", "content_description": "没有方括号问题号",
            "done": False, "submitted_by": "agent-D", "for_question_id": "0000",
        }, note="t")
    budget = agent._budget()
    assert budget["per_question"] == {"0000": 1}, budget
    assert budget["remaining"] == 9, budget

    # ② 老行：没有 for_question_id，靠描述里的 [q:0000] 认领
    with st.tx("search_requests", actor="agent-D", note="t") as tx:
        tx.upsert("search_requests", {
            "request_id": "r-0002", "timestamp": "2026-01-01T00:00:00+00:00",
            "topic": "乙", "mode": "topical",
            "content_description": "[q:0000] origin=user；老行",
            "done": False, "submitted_by": "agent-D",
        }, note="t")
    budget = agent._budget()
    assert budget["per_question"] == {"0000": 2}, budget

    # ③ 两条都没有 ⇒ 不计入任何一问（"读不到"不许折成"属于 0000"）
    with st.tx("search_requests", actor="agent-D", note="t") as tx:
        tx.upsert("search_requests", {
            "request_id": "r-0003", "timestamp": "2026-01-01T00:00:00+00:00",
            "topic": "丙", "mode": "topical", "content_description": "谁也不属于",
            "done": False, "submitted_by": "agent-D",
        }, note="t")
    budget = agent._budget()
    assert budget["per_question"] == {"0000": 2}, budget
    assert budget["total"] == 3, budget


def test_the_budget_counts_the_contradiction_channel_too(tmp_path):
    """矛盾闭环提交的请求必须进 `_budget` 的账（CS-3 的另一半）。

    从前 `_budget` 按 `submitted_by == self.actor` 精确过滤，而矛盾那一支写的是
    `agent-D:contradiction`（那个后缀是有意的：`resolve_priority` 按它分成 high / medium
    两档）⇒ 那一整类请求一条都不进账：全局上限（共享资源 A 的产能）与"每问题 2 轮"
    都少算。判据两头都钉：① 带后缀的行计入 `total` / `per_question` / `by_channel`；
    ② 只认冒号后缀（`agent-D2` 那种别的实例不许被吞进来 —— 实例轴是 CS-15 要裁的事）。
    """
    st = _opaque_store(tmp_path / "ws")
    add_question(st, "0000", question="完全不存在的关键词XYZ",
                 related_concept_ids=["0001", "0002"], related_relation_ids=["0000"])
    rows = [
        ("r-0001", "agent-D", "0000"),                    # 缺口那一支
        ("r-0002", "agent-D:contradiction", "0000"),      # 矛盾那一支（同一个问题）
        ("r-0003", "agent-D2", "0000"),                   # 别的实例：不许被吞进来
        ("r-0004", "agent-C", "0000"),                    # 别人提的：更不许
    ]
    with st.tx("search_requests", actor="agent-D", note="fixture") as tx:
        for rid, who, qid in rows:
            tx.upsert("search_requests", {
                "request_id": rid, "timestamp": "2026-01-01T00:00:00+00:00",
                "topic": "甲", "mode": "topical", "content_description": "",
                "done": False, "submitted_by": who, "for_question_id": qid,
            }, note="fixture")

    budget = AgentD(st)._budget()
    assert budget["total"] == 2, budget
    assert budget["per_question"] == {"0000": 2}, budget
    assert budget["by_channel"] == {"gap": 1, "contradiction": 1}, budget
    assert budget["remaining"] == budget["total_limit"] - 2, budget


def test_the_contradiction_ledgers_are_reconciled(tmp_path):
    """两本账的对账读数：问题行上的台账 vs 请求行上的归属（CS-3 的另一半）。

    两本账今天由 `adjudicate` 在同一笔事务里一起写 ⇒ 必然相等；但没有任何判据守它，
    所以这里把另一个方向也数出来，并钉住"不相等时读得出来"。
    """
    st = Store(tmp_path / "ws")
    st.init()
    add_question(st, "0000", question="关系 0002 与 0003 的陈述互相矛盾",
                 kind="contradiction", related_relation_ids=["0002", "0003"],
                 contradiction_relation_ids=["0002", "0003"],
                 contradiction_request_ids=["r-0001"])
    with st.tx("search_requests", actor="agent-D", note="fixture") as tx:
        tx.upsert("search_requests", {
            "request_id": "r-0001", "timestamp": "2026-01-01T00:00:00+00:00",
            "topic": "甲", "mode": "topical", "content_description": "",
            "done": False, "submitted_by": "agent-D:contradiction",
            "for_question_id": "0000",
        }, note="fixture")
    agent = AgentD(st)
    got = agent._contradiction_budget()
    assert got["used"] == 1 and got["by_rows"] == 1 and got["reconciled"] is True, got

    # 反真空：把请求行换成一个不属于任何矛盾问题的（归属指到另一个问题上）⇒
    # 对账必须当场变 False（否则这两格读数只是"看起来在算"）。
    with st.tx("search_requests", actor="agent-D", note="fixture") as tx:
        row = tx.find("search_requests", request_id="r-0001")
        row["for_question_id"] = "9999"
        tx.upsert("search_requests", row, note="fixture")
    bad = agent._contradiction_budget()
    assert bad["used"] == 1 and bad["by_rows"] == 0 and bad["reconciled"] is False, bad


# ============================================================ [6] poll：等待集


def test_poll_waiting_requires_done_request_and_processed_literature(tmp_path):
    """就绪的两个条件缺一不可：请求已结束 且 其 result_lit_ids 都被 B 消化。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "0000", title="补齐文献", processed=False, sync=False)
    add_request(st, "r-0000", done=False, result_lit_ids=[])
    add_question(st, "0000", question="q", related_concept_ids=["0001"], waiting_request_ids=["r-0000"], status="needs_evidence")

    step1 = RT.research_poll_waiting(st).data
    assert step1["counts"] == {"ready": 0, "waiting": 1, "questions_with_waiting": 1}
    assert "未结束" in step1["waiting"][0]["reason"]

    # A 跑完，但 B 还没消化
    with st.tx("search_requests", actor="fake-A") as tx:
        req = tx.find("search_requests", request_id="r-0000")
        req["done"] = True
        req["outcome"] = "ok"
        req["result_lit_ids"] = ["0000"]
        tx.upsert("search_requests", req)
    step2 = RT.research_poll_waiting(st).data
    assert step2["ready"] == []
    assert step2["waiting"][0]["details"][0]["state"] == "waiting_b"
    assert step2["waiting"][0]["details"][0]["unprocessed_lit_ids"] == ["0000"]
    assert "还没被 B 消化" in step2["waiting"][0]["reason"]

    # B 消化完 ⇒ 就绪
    with st.tx("literature", actor="fake-B") as tx:
        lit = tx.find("literature", lit_id="0000")
        lit["processed"] = True
        tx.upsert("literature", lit)
    step3 = RT.research_poll_waiting(st).data
    assert step3["waiting"] == []
    assert [r["question_id"] for r in step3["ready"]] == ["0000"]
    assert step3["ready"][0]["new_lit_ids"] == ["0000"]
    assert "可以拉回 researching" in step3["ready"][0]["reason"]


def test_poll_treats_terminal_failure_outcomes_as_finished(tmp_path):
    """`gave_up` / `no_results` 也是有效结论：D 必须能据此继续，而不是永远等下去。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_request(st, "r-0000", done=False, result_lit_ids=[])
    add_question(st, "0000", question="q", waiting_request_ids=["r-0000"], status="needs_evidence")
    with st.tx("search_requests", actor="fake-A") as tx:
        req = tx.find("search_requests", request_id="r-0000")
        req["outcome"] = "gave_up"
        req["last_error"] = "上游始终不可达"
        tx.upsert("search_requests", req)

    data = RT.research_poll_waiting(st).data
    assert [r["question_id"] for r in data["ready"]] == ["0000"]
    assert "可以拉回 researching" in data["ready"][0]["reason"]


def test_poll_promotes_question_and_merges_new_relations(tmp_path):
    """就绪的问题被拉回 researching，并把新到的关系并入证据（这就是"D 继续"）。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0001", "甲", definition="d", sync=False)
    add_concept(st, "0002", "乙", definition="d", sync=False)
    add_concept(st, "0003", "丙", definition="d", sync=False)
    add_relation(st, "0000", ["0001", "0002"], "0000", description="zzz", quote="zzz", quote_verified=None, sync=False)
    sync_counters(st)
    add_request(st, "r-0000", done=True, result_lit_ids=["0000"])
    add_literature(st, "0000", title="新文献", processed=True, sync=False)
    add_question(
        st, "0000", question="q", related_concept_ids=["0001"], related_relation_ids=["0000"],
        waiting_request_ids=["r-0000"], status="needs_evidence",
    )
    # 新到的关系（A 检索 → B 抽取的产物）
    add_relation(st, "0001", ["0001", "0003"], "0000", description="新关系", quote="new", quote_verified=True, sync=False)

    agent = AgentD(st)
    poll = agent.poll()
    assert poll["promoted"] == ["0000"]
    assert poll["merged_relations"]["0000"] == ["0001"]
    row = st.rows("research_questions")[0]
    assert row["status"] == "researching"
    assert row["related_relation_ids"] == ["0000", "0001"], "新关系必须并入证据"
    assert row["evidence_lit_ids"] == ["0000"]
    assert "[poll]" in row["notes"]

    # 再次 poll：已经不是 needs_evidence/open 了，不该再动它
    again = agent.poll()
    assert again["promoted"] == []


def test_poll_on_question_without_waiting_set_does_nothing(tmp_path):
    """没有等待集的问题不该出现在 poll 的 ready/waiting 里（"我没在等谁"是明确的事实）。"""
    st = _opaque_store(tmp_path / "ws")
    add_question(st, "0000", question="q", related_concept_ids=["0001"])
    data = RT.research_poll_waiting(st).data
    assert data["counts"]["questions_with_waiting"] == 0
    assert data["ready"] == [] and data["waiting"] == []


# ============================================================ 状态机不变量


def test_verify_flags_stale_waiting_on_terminal_status(tmp_path):
    """状态机不变量：answered/dropped 的问题不该仍挂着 waiting_request_ids（verify 报 stale_waiting）。"""
    st = _opaque_store(tmp_path / "ws")
    add_request(st, "r-0000", done=True, result_lit_ids=[], last_error="查不到（no_results）")
    add_question(
        st, "0000", question="q", related_concept_ids=["0001"], waiting_request_ids=["r-0000"],
        status="answered", notes="已经给出结论",
    )
    issues = [i for i in verify_all(st).issues if i.code == "stale_waiting"]
    assert issues, "verify 没有发现「已完成却还挂着等待项」"
    assert issues[0].level == "warning"
    assert issues[0].row_id == "0000"


def test_no_stale_waiting_after_the_full_d_loop(tmp_path):
    """跑完"提交→A 完成→B 消化→poll→research"后，问题表里不该出现任何 stale_waiting。"""
    st = _opaque_store(tmp_path / "ws")
    add_question(st, "0000", question="完全不存在的关键词XYZ", related_concept_ids=["0001", "0002"], related_relation_ids=["0000"])
    agent = AgentD(st)
    rid = agent.submit_gaps("0000")[0]
    with st.tx("search_requests", "literature", actor="fake-A") as tx:
        req = tx.find("search_requests", request_id=rid)
        req["done"] = True
        req["outcome"] = "ok"
        req["result_lit_ids"] = ["0000"]
        tx.upsert("search_requests", req)
        tx.upsert(
            "literature",
            S.Literature(lit_id="0000", title="补齐", type="J", summary="s", path=None, processed=True, added_at=TS).to_dict(),
        )
    assert agent.poll()["promoted"] == ["0000"]
    result = agent.research("0000")
    assert result["confidence"] == "low"
    codes = {i.code for i in verify_all(st).issues}
    assert "stale_waiting" not in codes


# ============================================================ 置信度


def test_confidence_stays_low_when_evidence_is_insufficient(tmp_path):
    """证据不足时置信度必须是 low（"低"就写"低"，不许为了好看拔高）。"""
    assert evidence_confidence([]) == "low"
    st = _opaque_store(tmp_path / "ws")
    add_question(
        st, "0000", question="关于韦伊猜想的证明路径是否已经完整", related_concept_ids=["0001", "0002"],
        related_relation_ids=["0000"], status="researching",
    )
    result = AgentD(st).research("0000")
    assert result["confidence"] == "low"
    assert "**置信度：低**" in result["conclusion"]
    assert "不作为可引用的判断" in result["conclusion"]
    assert result["criteria"] == ["a_no_keyword_hit", "b_low_degree_unverified"]


def _sufficient_store(root) -> Store:
    """三个概念 + 三条关系，使 `analyze_gaps` 的三条判据一条都不触发（sufficient）。

    度数 ≥ 阈值、关键词在关系的 quote/description 里有命中、没有成对矛盾。
    刻意让 `confidence` 仍是 low：置信度衡量证据强度，sufficient 衡量"有没有触发'不足'
    的判据" —— 两者不是一回事（CS-5 的收口判据不许拿置信度当门槛）。
    """
    st = Store(root)
    st.init()
    for cid, name in (("0001", "甲"), ("0002", "乙"), ("0003", "丙"), ("0004", "丁")):
        add_concept(st, cid, name, definition="d", sync=False)
    add_relation(st, "0000", ["0001", "0002"], "0000", description="甲与乙有关", quote="q0", sync=False)
    add_relation(st, "0001", ["0002", "0003"], "0000", description="乙与丙有关", quote="q1", sync=False)
    add_relation(st, "0002", ["0003", "0004"], "0000", description="丙与丁有关", quote="q2", sync=False)
    add_literature(st, "0000", title="A", processed=True, sync=False)
    sync_counters(st)
    return st


def test_research_closes_a_sufficient_question_and_clears_the_waiting_set(tmp_path):
    """证据足够 ⇒ `research()` 自己把状态收口到 `answered`，并按终态纪律清空等待集（CS-5）。

    为什么值得一条判据：`researching → answered` 这条边早就在状态机表里
    （`research_tools.LEGAL_TRANSITIONS`），但缺口这条路上没有任何代码走它 —— 真机 118 行
    `research_questions` 里 `answered` 0 行，于是两道"已下结论就跳过"的过滤
    （`pipeline.py` 的复查、`agent_d/core.py` 的裁决）永远不生效，同一个问题每一轮都被
    重新研究、重新评估。不清空等待集的话 `verify` 会报 `stale_waiting` —— 与矛盾闭环
    （`agent_d/adjudicate.py` 的 `resolved` 那一支）同一条纪律。

    反真空在下面那一条里（不足时不许收口）。
    """
    st = _sufficient_store(tmp_path / "ws")
    with st.tx("search_requests", actor="test", note="fixture") as tx:
        req = S.SearchRequest(
            request_id="r-0001", timestamp=TS, topic="甲与乙", mode="topical",
            content_description="", done=True, submitted_by="agent-D", outcome="ok",
            result_lit_ids=["0000"], for_question_id="0000",
        )
        req.validate()
        tx.upsert("search_requests", req.to_dict(), note="fixture")
    add_question(
        st, "0000", question="甲与乙之间的链条是否成立？", related_concept_ids=["0001", "0002"],
        related_relation_ids=["0000"], status="researching", waiting_request_ids=["r-0001"],
    )

    agent = AgentD(st)
    assert agent.assess("0000")["sufficient"] is True, "夹具前提崩了：这一档应当是 sufficient"
    res = agent.research("0000")

    row = st.rows("research_questions")[0]
    assert row["status"] == "answered", (
        "证据够却不收口 ⇒ 问题永远停在 researching，台账里没有结论")
    assert row["waiting_request_ids"] == [], (
        "终态必须清空等待集，否则 verify 报 stale_waiting（也说明这一问不该再等谁）")
    assert res["confidence"] == "low", "收口不等于拔高置信度（这两件事必须分得开）"
    codes = {i.code for i in verify_all(st).issues}
    assert "stale_waiting" not in codes


def test_research_leaves_an_insufficient_question_researching(tmp_path):
    """反真空：判据触发（证据不足）⇒ 不许收口成 `answered`。

    把"收口"错写成"凡是 `research()` 都收口"，缺口就再也没有出口：
    `submit_gaps` 与 `poll` 都只在非终态上工作，而 `answered` 是终态。
    """
    st = _opaque_store(tmp_path / "ws")
    add_question(
        st, "0000", question="关于韦伊猜想的证明路径是否已经完整",
        related_concept_ids=["0001", "0002"], related_relation_ids=["0000"],
        status="researching",
    )
    res = AgentD(st).research("0000")
    assert res["criteria"] == ["a_no_keyword_hit", "b_low_degree_unverified"], res
    assert st.rows("research_questions")[0]["status"] == "researching", (
        "证据不足还收口 ⇒ 这一问再也没有机会去要检索")


def test_llm_hook_cannot_raise_confidence(tmp_path):
    """LLM 钩子只能把置信度调低：它写 high 也必须被强制降回确定性算出的 low。"""
    st = _opaque_store(tmp_path / "ws")
    add_question(
        st, "0000", question="关于韦伊猜想的证明路径是否已经完整", related_concept_ids=["0001", "0002"],
        related_relation_ids=["0000"], status="researching",
    )
    llm = _FakeLLM(confidence="high")
    agent = AgentD(st, llm=llm)
    result = agent.research("0000")
    assert llm.calls, "LLM 钩子应当被调用过"
    assert result["llm_used"] is True
    assert result["confidence"] == "low", "LLM 把置信度拔高了"
    assert any("拔高" in str(e.get("error")) for e in agent.last_tool_errors)
    # 分析文字可以用 LLM 的，但结论与置信度必须保持确定性口径
    assert result["analysis"] == "LLM 写的分析"


def test_install_d_tools_prefers_the_external_trace_tools(tmp_path):
    """D 的工具栏优先用外部 trace_tools（真身），缺失时才降级到内置替身。"""
    st = _opaque_store(tmp_path / "ws")
    reg = install_d_tools(st)
    names = set(reg.names())
    assert {"trace.relation", "trace.concept", "trace.literature"} <= names
    assert {"research.list_gaps", "research.submit_gap", "research.poll_waiting"} <= names
    assert not getattr(reg, "trace_fallback_reason", None), "外部溯源工具存在时不该走降级替身"

    fallback = install_d_tools(st, trace_tools=None)
    assert "trace.relation" in fallback
