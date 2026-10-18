"""D 侧的新增交互：I1（C 服务化）/ I2（矛盾闭环）/ §3.1（问题等价类）/ §3.2（证据就绪判据）。

对应 `DESIGN-INTERACTIONS.md` §1 I1·I2 与 §3 的 3.1 / 3.2。这四条交互各有一条
负控（§4 的要求：只有正向信号时，"有"和"没有"一样容易通过测试），以及把
"没查"与"查了没有"分开的三态用例。

全部离线、确定性：C 服务用契约形状的假对象（不依赖 `agent_c.py` 的当前版本），
少数集成用例在真身存在时才跑。
"""

from __future__ import annotations

import json

import pytest

from agentflow import interactions as IX
from agentflow import schema as S
from agentflow import agent_d as AD
from agentflow.agent_d import AgentD
from agentflow.store import Store

from conftest import TS, add_concept, add_literature, add_relation, add_request, sync_counters

# ============================================================ 辅助


def add_question(st: Store, qid: str, **kw) -> dict:
    """插入一条合法的 research_questions 行（conftest 只覆盖了四张主表，没有这张）。

    与 `test_agent_d.py` 的同名辅助保持一致，另外支持 I2 的矛盾字段
    （`kind` / `contradiction_relation_ids` / `contradiction_rounds`）。

    手工插行之后必须把 `counters.question` 推到 max+1：否则 `tx.alloc_id("question")`
    会发出一个已被占用的号，而按主键 upsert 会静默覆盖那一行
    （见 `AgentD.adjudicate` 里那段防御）。`conftest.sync_counters` 只管
    lit/concept/relation 三类，所以这里自己补。
    """
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
        kind=kw.get("kind", "gap"),
        contradiction_relation_ids=list(kw.get("contradiction_relation_ids", [])),
        contradiction_rounds=int(kw.get("contradiction_rounds", 0)),
        contradiction_verdict=kw.get("contradiction_verdict"),
        contradiction_request_ids=list(kw.get("contradiction_request_ids", [])),
        notes=kw.get("notes", ""),
        created_at=TS,
        updated_at=TS,
    )
    row.validate()
    with st.tx("research_questions", actor="test", note="fixture") as tx:
        tx.upsert("research_questions", row.to_dict())
    _sync_question_counter(st)
    return row.to_dict()


def _sync_question_counter(st: Store) -> None:
    """把 counters.question 对齐到 max(已用 question_id)+1（见 add_question 的说明）。"""
    p = st.data / "counters.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    ids = [int(r["question_id"]) for r in st.rows("research_questions") if r.get("question_id")]
    doc.setdefault("counters", {})["question"] = (max(ids) + 1) if ids else 0
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rows(st: Store, table: str) -> list[dict]:
    return list(st.rows(table))


def _qrow(st: Store, qid: str) -> dict:
    return next(r for r in st.rows("research_questions") if str(r.get("question_id")) == qid)


def _requests_of(st: Store, qid: str) -> list[dict]:
    """该问题矛盾驱动的检索请求（按 contradiction_request_ids 取）。"""
    row = _qrow(st, qid)
    wanted = {str(x) for x in (row.get("contradiction_request_ids") or [])}
    return [r for r in st.rows("search_requests") if str(r.get("request_id")) in wanted]


class RecordingC:
    """契约形状的假 C：记录被调用的 api 与参数，用来断言 D 的"点菜参数"。

    为什么不用真 `AgentC`：I1 的实现必须能在 C 服务缺席/版本不匹配时照常跑完，
    因此测试也不能把 C 的当前版本当成前提（C 与 D 是并行开发的模块）。
    另有一组 `_real_c` 集成用例，在真身提供这些方法时才跑。
    """

    def __init__(self, *, raise_on: tuple[str, ...] = (), checked: bool = True, contradictions: list | None = None) -> None:
        self.calls: list[dict] = []
        self.raise_on = set(raise_on)
        self.checked = checked
        # 属性名不能叫 self.contradictions：那会遮蔽同名服务方法，
        # 于是 `getattr(c, "contradictions")` 拿到一个 list ⇒ D 记"版本不匹配"。
        self.contradiction_items = list(contradictions or [])

    def _rec(self, api: str, **params) -> None:
        self.calls.append({"api": api, "params": dict(params)})
        if api in self.raise_on:
            raise RuntimeError(f"假 C 在 {api} 上炸了")

    def _base(self, reason: str = "stub") -> dict:
        return {"checked": self.checked, "truncated": False, "reason": reason}

    def neighbors(self, concept_id: str, *, depth: int = 1, max_nodes=None) -> dict:
        self._rec("neighbors", concept_id=concept_id, depth=depth)
        out = self._base()
        out.update(
            {
                "concept_id": concept_id,
                "depth": depth,
                "nodes": [{"concept_id": concept_id, "name": "起点", "distance": 0}],
                "edges": [],
                "empty": True,
            }
        )
        return out

    def relations_between(self, a: str, b: str, *, include_inactive: bool = True) -> dict:
        self._rec("relations_between", a=a, b=b, include_inactive=include_inactive)
        out = self._base()
        out.update({"a": a, "b": b, "relation_ids": ["0000"], "relations": [], "empty": False})
        return out

    def contradictions(self, *, relation_ids=None, limit=None) -> dict:
        self._rec("contradictions", relation_ids=relation_ids, limit=limit)
        out = self._base()
        out.update(
            {
                "scope": "stub",
                "scanned": len(relation_ids or []),
                "contradictions": list(self.contradiction_items),
                "limit": limit,
                "method": "literal",
                "method_note": "stub",
            }
        )
        return out


class MissingApiC:
    """没有那四个服务方法的 C：模拟"版本不匹配"（接口还没落地）。"""


def _contradiction_store(tmp_path, *, statuses: tuple[str, str] = ("active", "active")):
    """两个概念 + 一对对立关系（同一概念组、一方带否定）。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0001", "非交换环", definition="d", sync=False)
    add_concept(st, "0002", "交换性条件", definition="d", sync=False)
    add_relation(
        st, "0002", ["0001", "0002"], "0000",
        description="交换性条件不能推广到非交换环。", quote="", quote_verified=None, status=statuses[0], sync=False,
    )
    add_relation(
        st, "0003", ["0001", "0002"], "0001",
        description="交换性条件可以推广到非交换环。", quote="", quote_verified=None, status=statuses[1], sync=False,
    )
    add_literature(st, "0000", title="A", processed=True, sync=False)
    add_literature(st, "0001", title="B", processed=True, sync=False)
    sync_counters(st)
    return st


def _pair_store(tmp_path):
    """四个概念 + 三条关系，供 §3.1 的等价/非等价用例使用。"""
    st = Store(tmp_path / "ws")
    st.init()
    for cid, name in (("0001", "甲"), ("0002", "乙"), ("0003", "丙"), ("0004", "丁")):
        add_concept(st, cid, name, definition="d", sync=False)
    add_relation(st, "0000", ["0001", "0002"], "0000", description="甲与乙有关", quote="q0", sync=False)
    add_relation(st, "0001", ["0002", "0003"], "0000", description="乙与丙有关", quote="q1", sync=False)
    add_relation(st, "0002", ["0003", "0004"], "0000", description="丙与丁有关", quote="q2", sync=False)
    add_literature(st, "0000", title="A", processed=True, sync=False)
    sync_counters(st)
    return st


def _paths_report(rid: str, paths: list[dict], extra: dict | None = None) -> dict:
    payload: dict = {"paths": paths}
    payload.update(extra or {})
    return {
        "report_id": rid,
        "kind": "paths",
        "request": "查询两概念间的关系",
        "params": {},
        "summary": "（测试用报告）",
        "payload": payload,
    }


# ============================================================ I1：C 服务化


def test_i1_research_derives_c_query_params_from_the_question(tmp_path):
    """I1 正向：research 必须带上 ≥1 条 C 查询，且参数由本问题的代号推导（不是照抄报告）。"""
    st = _pair_store(tmp_path)
    c = RecordingC()
    agent = AgentD(st, c=c)
    add_question(
        st, "0000",
        question="甲与乙之间的链条是否成立？",
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0000"],
        status="researching",
    )

    res = agent.research("0000")
    queries = res["evidence"]["c_queries"]
    assert queries, "I1：research() 必须至少发起一次 C 查询"
    assert all(q["checked"] is True for q in queries), queries
    assert all(set(q) >= {"api", "params", "checked", "truncated", "digest", "reason"} for q in queries)

    by_api = {q["api"]: q for q in queries}
    assert set(by_api) == {"neighbors", "relations_between", "contradictions"}
    # 参数来自问题自己的概念/关系代号
    assert by_api["neighbors"]["params"]["concept_id"] in {"0001", "0002"}
    assert {by_api["relations_between"]["params"]["a"], by_api["relations_between"]["params"]["b"]} == {"0001", "0002"}
    assert by_api["contradictions"]["params"]["relation_ids"] == ["0000"]
    # 不是照抄报告：报告 payload 里引用过的另一条关系（0009）不得出现在参数里
    assert "0009" not in json.dumps(by_api["contradictions"]["params"])
    # digest 要能看出实际得到了什么（不是布尔）
    assert by_api["relations_between"]["digest"]["relation_ids"] == ["0000"]
    assert by_api["contradictions"]["digest"]["contradiction_count"] == 0
    # 全部成功 ⇒ 不许出现"无 C 侧证据"的标注
    assert AD.C_NO_EVIDENCE not in res["conclusion"]


def test_i1_assess_also_issues_c_queries(tmp_path):
    """I1：assess 阶段也要点菜（报告需要"这个问题的结论有没有 C 侧证据"这个事实）。"""
    st = _pair_store(tmp_path)
    add_question(st, "0000", question="甲与乙有关吗", related_concept_ids=["0001"], related_relation_ids=["0000"])
    agent = AgentD(st, c=RecordingC())
    verdict = agent.assess("0000")
    assert verdict["c_queries"], "assess 阶段没有发起任何 C 查询"
    assert verdict["c_evidence"]["any_success"] is True


def test_i1_missing_api_is_not_reported_as_no_result(tmp_path):
    """I1 三态：C 没有那些方法 ⇒ checked=False + 理由，不是"查了没有"。"""
    st = _pair_store(tmp_path)
    agent = AgentD(st, c=MissingApiC())
    add_question(st, "0000", question="甲与乙有关吗", related_concept_ids=["0001"], related_relation_ids=["0000"])

    res = agent.research("0000")
    queries = res["evidence"]["c_queries"]
    assert queries
    assert all(q["checked"] is False for q in queries)
    assert all(str(q["reason"]).strip() for q in queries), "没查成功必须给出理由"
    assert all(q["reason"] == AD.C_API_MISSING_REASON for q in queries)
    assert all(q["digest"] is None for q in queries), "没查成功时不许给 digest（那会被读成'查了、没有'）"
    assert res["c_evidence"]["any_success"] is False
    # 结论必须显式标注"无 C 侧证据"，且不许给确定语气
    assert AD.C_NO_EVIDENCE in res["conclusion"]
    assert "不得把本节的措辞当作已核实的判断引用" in res["conclusion"]

    out = agent.write_report(tmp_path / "ws" / "reports" / "i1.md")
    text = open(out, encoding="utf-8").read()
    assert AD.C_NO_EVIDENCE in text, "渲染出的报告文本里必须能看到「无 C 侧证据」"
    assert AD.C_API_MISSING_REASON in text


def test_i1_raising_api_is_visible_and_blocks_confident_tone(tmp_path):
    """I1 三态：C 的方法抛异常 ⇒ 失败在报告里可见，且结论仍被标注「无 C 侧证据」。"""
    st = _pair_store(tmp_path)
    c = RecordingC(raise_on=("neighbors", "relations_between", "contradictions"))
    agent = AgentD(st, c=c)
    add_question(st, "0000", question="甲与乙有关吗", related_concept_ids=["0001"], related_relation_ids=["0000"])

    res = agent.research("0000")
    reasons = [q["reason"] for q in res["evidence"]["c_queries"]]
    assert all("RuntimeError" in r for r in reasons), reasons
    assert res["c_evidence"]["any_success"] is False
    assert AD.C_NO_EVIDENCE in res["conclusion"]

    out = agent.write_report(tmp_path / "ws" / "reports" / "i1b.md")
    text = open(out, encoding="utf-8").read()
    assert "RuntimeError" in text, "C 调用失败必须在报告里可见（静默失败比崩溃更危险）"


def test_i1_explicit_none_disables_c_but_stays_visible(tmp_path):
    """I1：显式 `c=None`（明确禁用）与"没接线"必须能区分，且都要留痕。"""
    st = _pair_store(tmp_path)
    agent = AgentD(st, c=None)
    add_question(st, "0000", question="甲与乙有关吗", related_concept_ids=["0001"], related_relation_ids=["0000"])
    res = agent.research("0000")
    assert agent.c_wiring["mode"] == "disabled"
    assert all(q["checked"] is False for q in res["evidence"]["c_queries"])
    assert all("未接入 C 服务" in q["reason"] for q in res["evidence"]["c_queries"])
    assert AD.C_NO_EVIDENCE in res["conclusion"]


@pytest.mark.skipif(not hasattr(__import__("agentflow.agent_c", fromlist=["AgentC"]).AgentC, "neighbors"),
                    reason="agent_c 还没提供四个只读服务方法（并行开发中）")
def test_i1_against_the_real_c_service(tmp_path):
    """集成：C 真身提供了服务方法时，D 的自动装配必须真的查到东西（digest 非空）。"""
    from agentflow.agent_c import AgentC

    st = _pair_store(tmp_path)
    agent = AgentD(st)  # 不注入 ⇒ 惰性装配 AgentC
    assert agent.c_wiring["mode"] == "auto"
    add_question(st, "0000", question="甲与乙有关吗", related_concept_ids=["0001", "0002"], related_relation_ids=["0000"])

    res = agent.research("0000")
    queries = res["evidence"]["c_queries"]
    assert queries and all(q["checked"] for q in queries), queries
    assert any(q["digest"].get("relation_count") for q in queries if q["api"] == "relations_between")
    assert AD.C_NO_EVIDENCE not in res["conclusion"]
    assert isinstance(AgentC(st), AgentC)


def test_delegation_to_interactions_has_no_drift():
    """判据只有一份：agent_d 的同名函数必须与 interactions 完全同结果。"""
    assert AD._NEGATION_MARKERS is IX.NEGATION_MARKERS
    assert AD._OPPOSITE_PAIRS is IX.OPPOSITE_PAIRS
    texts = [
        "交换性条件不能推广到非交换环。",
        "交换性条件可以推广到非交换环。",
        "non-commutative rings are not commutative",
        "",
    ]
    for t in texts:
        assert AD._negated(t) == IX.negated(t)
        assert AD._opposite_flags(t) == IX.opposite_flags(t)
        assert AD._contains(t, "交换") == IX.contains(t, "交换")
    rels = [
        {"relation_id": "0002", "concept_pair_key": "0001|0002", "statement": "条件不能推广"},
        {"relation_id": "0003", "concept_pair_key": "0001|0002", "statement": "条件可以推广"},
    ]
    assert AD.detect_contradictions(rels) == IX.detect_contradictions(rels)


def test_i2_strong_affirm_vs_deny_makes_a_contradiction_question(tmp_path):
    """I2 正向（strength=strong）：`"A 是 B"` / `"A 不是 B"` ⇒ 建 high 矛盾问题。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0001", "端点", definition="d", sync=False)
    add_concept(st, "0002", "见证", definition="d", sync=False)
    add_relation(st, "0007", ["0001", "0002"], "0000",
                 description="端点 0 的见证是显式的。", quote="q", sync=False)
    add_relation(st, "0008", ["0001", "0002"], "0001",
                 description="端点 0 的见证不是显式的。", quote="q2", sync=False)
    add_literature(st, "0000", title="A", processed=True, sync=False)
    sync_counters(st)

    rels = _rows(st, "relations")
    detected = IX.detect_contradictions(rels)
    assert len(detected) == 1 and detected[0]["strength"] == "strong", detected

    agent = AgentD(st, c=RecordingC())
    report = _paths_report(
        "0000",
        [{"concept_path": ["0001", "0002"], "relation_chain": ["0007"], "level": "high", "hops": 1}],
        extra={"contradictions": detected},  # 直接把 I1 的 c.contradictions() 结果喂进来
    )
    created = agent.ingest(report, c_contradictions={"checked": True, "contradictions": detected, "reason": "stub"})
    contra = [r for r in _rows(st, "research_questions") if r.get("kind") == "contradiction"]
    assert len(contra) == 1, "strong 矛盾没有被建成问题"
    assert contra[0]["priority"] == "high"
    assert contra[0]["contradiction_relation_ids"] == ["0007", "0008"]
    assert contra[0]["question_id"] in created
    assert contra[0]["origin"] == "C:contradictions:0007+0008"


def test_i2_weak_clue_is_recorded_but_never_asked(tmp_path):
    """I2 负控（新增，重要）：只有 weak 线索的关系对不得建问题、不得提交任何请求。

    弱信号的形态是"否定标记出现与否不一致"，而它在自然语言里不是否定命题
    （"不必用数值搜索"）。实测 25 条真实关系里 weak 报了 24%，没有一条是真矛盾 ——
    拿它驱动检索等于用 A 的产能换假问题。
    """
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0001", "端点 0", definition="d", sync=False)
    add_concept(st, "0002", "见证", definition="d", sync=False)
    add_relation(st, "0005", ["0001", "0002"], "0000",
                 description="端点 0 不必用数值搜索。", quote="q", sync=False)
    add_relation(st, "0006", ["0001", "0002"], "0001",
                 description="|S|=0 的见证是显式的。", quote="q2", sync=False)
    add_literature(st, "0000", title="A", processed=True, sync=False)
    sync_counters(st)

    rels = _rows(st, "relations")
    detected = IX.detect_contradictions(rels)
    assert len(detected) == 1 and detected[0]["strength"] == "weak", detected

    agent = AgentD(st, c=RecordingC())
    # 先放一条已有问题（共享关系代号 0005），用来验证弱线索会落进它的 notes
    add_question(st, "0000", question="端点 0 与见证的关系？",
                 related_concept_ids=["0001", "0002"], related_relation_ids=["0005"])
    report = _paths_report(
        "0000",
        [{"concept_path": ["0001", "0002"], "relation_chain": ["0006"], "level": "high", "hops": 1}],
        extra={"contradictions": detected},
    )
    created = agent.ingest(report, c_contradictions={"checked": True, "contradictions": detected, "reason": "stub"})

    rows = _rows(st, "research_questions")
    assert not [r for r in rows if r.get("kind") == "contradiction"], "weak 线索被建成了矛盾问题"
    assert all(r.get("origin") != "C:contradictions:0005+0006" for r in rows)
    assert st.rows("search_requests") == [], "weak 线索不得提交任何检索请求"
    assert created == [] or all(_qrow(st, q)["kind"] != "contradiction" for q in created)

    # 但"这条弱线索被记录过"必须看得到：last_ingest + 已有问题的 notes + 报告
    clues = agent.last_ingest["contradictions"]["weak_clues"]
    assert len(clues) == 1
    assert clues[0]["relation_ids"] == ["0005", "0006"]
    assert clues[0]["strength"] == "weak"
    assert agent.last_ingest["weak_clues_noted"][0]["question_id"] == "0000"
    assert "weak_conflict_clue" in _qrow(st, "0000")["notes"]

    out = agent.write_report(tmp_path / "ws" / "reports" / "weak.md")
    text = open(out, encoding="utf-8").read()
    assert "弱线索（不追问）" in text and "0005" in text


def test_i2_weak_pair_is_not_auto_asked_even_if_flagged_resolved_side(tmp_path):
    """I2 负控（裁决侧）：已存在的矛盾问题若只剩 weak 线索 ⇒ persistent，且不提交请求。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0001", "端点 0", definition="d", sync=False)
    add_concept(st, "0002", "见证", definition="d", sync=False)
    add_relation(st, "0005", ["0001", "0002"], "0000",
                 description="端点 0 不必用数值搜索。", quote="q", sync=False)
    add_relation(st, "0006", ["0001", "0002"], "0001",
                 description="|S|=0 的见证是显式的。", quote="q2", sync=False)
    sync_counters(st)
    add_question(
        st, "0000",
        question="关系 0005 与 0006 的陈述互相矛盾，需要判定哪一方成立",
        origin="C:contradictions:0005+0006",
        kind="contradiction",
        contradiction_relation_ids=["0005", "0006"],
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0005", "0006"],
        priority="high",
    )
    agent = AgentD(st, c=RecordingC())
    out = agent.adjudicate("0000")
    assert out["verdict"] == "persistent"
    assert out["code"] == "weak_only_signal"
    assert out["request_ids"] == []
    assert st.rows("search_requests") == [], "weak 线索不得触发检索请求"
    row = _qrow(st, "0000")
    assert row["status"] == "answered"
    assert row["contradiction_verdict"] == "persistent"
    assert row["contradiction_rounds"] == 0, "没有追问过就不该有轮数"


# ============================================================ I2：矛盾闭环


def test_i2_ingest_turns_a_contradiction_into_a_high_priority_question(tmp_path):
    """I2(a)：C 报告里的矛盾要变成 kind=contradiction、priority=high 的问题（带代号链）。"""
    st = _contradiction_store(tmp_path)
    agent = AgentD(st, c=RecordingC())
    report = _paths_report(
        "0000",
        [{"concept_path": ["0001", "0002"], "relation_chain": ["0002"], "level": "high", "hops": 1, "concepts_names": []}],
        extra={
            "contradictions": [
                {
                    "relation_ids": ["0002", "0003"],
                    "signals": ["一方带否定标记（0002 neg=True / 0003 neg=False）"],
                    "detection": "literal",
                }
            ]
        },
    )
    created = agent.ingest(report)
    rows = _rows(st, "research_questions")
    contra = [r for r in rows if r.get("kind") == "contradiction"]
    assert len(contra) == 1, "C 报告里的矛盾没有被吸收成问题"
    row = contra[0]
    assert row["priority"] == "high"
    assert row["contradiction_relation_ids"] == ["0002", "0003"]
    assert row["related_relation_ids"] == ["0002", "0003"]
    assert row["related_concept_ids"] == ["0001", "0002"]
    assert row["origin"] == "C:contradictions:0002+0003"
    assert "互相矛盾" in row["question"] and "判定哪一方成立" in row["question"]
    assert row["question_id"] in created
    assert agent.last_ingest["contradictions"]["source"] == "report_payload"

    # 同一份报告再 ingest 一次：不得再建（origin + 内容键 + 等价类三层都要挡住）
    before = len(rows)
    assert agent.ingest(report) == []
    assert len(_rows(st, "research_questions")) == before


def test_i2_negative_control_consistent_pair_makes_no_contradiction_question(tmp_path):
    """I2 负控：一对不矛盾的关系不得产生 kind=contradiction 的问题。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0001", "非交换环", definition="d", sync=False)
    add_concept(st, "0002", "交换性条件", definition="d", sync=False)
    add_relation(st, "0004", ["0001", "0002"], "0000",
                 description="交换性条件可以推广到非交换环。", quote="", sync=False)
    add_relation(st, "0005", ["0001", "0002"], "0001",
                 description="交换性条件在有限环上也可以推广。", quote="", sync=False)
    add_literature(st, "0000", title="A", processed=True, sync=False)
    sync_counters(st)

    rels = _rows(st, "relations")
    for r in rels:
        r["concept_pair_key"] = IX.concept_pair_key(r.get("concept_ids") or [])
    assert IX.detect_contradictions(rels) == [], "两条同向表述被误判成矛盾（假矛盾比漏判更贵）"

    agent = AgentD(st, c=RecordingC())
    report = _paths_report(
        "0000",
        [{"concept_path": ["0001", "0002"], "relation_chain": ["0004", "0005"], "level": "high", "hops": 2}],
        extra={"contradictions": []},
    )
    agent.ingest(report)
    assert not [r for r in _rows(st, "research_questions") if r.get("kind") == "contradiction"]
    # 也不该有"查不了"的静默：来源与三态位都要记下来
    assert agent.last_ingest["contradictions"]["source"] == "report_payload"


def test_i2_resolved_in_one_round_when_a_side_is_gone(tmp_path):
    """I2 正向（一轮 resolved）：其中一方变成 rejected ⇒ 争议消失、问题 answered。"""
    st = _contradiction_store(tmp_path)
    add_question(
        st, "0000",
        question="关系 0002 与 0003 的陈述互相矛盾，需要判定哪一方成立",
        origin="C:contradictions:0002+0003",
        kind="contradiction",
        contradiction_relation_ids=["0002", "0003"],
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0002", "0003"],
        priority="high",
    )
    # "新证据"把其中一方判掉了（B 重抽取后把它标成 rejected）
    with st.tx("relations", actor="fake-B") as tx:
        rel = tx.find("relations", relation_id="0003")
        rel["status"] = "rejected"
        S.row_from_dict("relations", rel).validate()
        tx.upsert("relations", rel)

    agent = AgentD(st, c=RecordingC())
    out = agent.adjudicate("0000")
    assert out["checked"] is True
    assert out["verdict"] == "resolved"
    assert out["code"] in ("side_removed", "side_superseded")
    assert out["winner_relation_id"] == "0002"
    row = _qrow(st, "0000")
    assert row["status"] == "answered"
    assert row["contradiction_verdict"] == "resolved"
    assert row["waiting_request_ids"] == [], "终局必须清空等待集（否则 verify 报 stale_waiting）"
    assert "winner_relation_id" in row["notes"] and out["code"] in row["notes"]
    assert st.rows("search_requests") == [], "resolved 不该再追问"


def test_i2_unresolved_asks_exactly_one_more_round(tmp_path):
    """I2 正向（未解决）：两条都还 active 且仍对立 ⇒ unresolved + 轮数自增 + 一条 high 请求。"""
    st = _contradiction_store(tmp_path)
    add_question(
        st, "0000",
        question="关系 0002 与 0003 的陈述互相矛盾，需要判定哪一方成立",
        origin="C:contradictions:0002+0003",
        kind="contradiction",
        contradiction_relation_ids=["0002", "0003"],
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0002", "0003"],
        priority="high",
    )
    agent = AgentD(st, c=RecordingC())
    out = agent.adjudicate("0000")
    assert out["verdict"] == "unresolved"
    assert out["code"] == "still_conflicting"
    assert out["rounds_before"] == 0 and out["rounds_after"] == 1

    row = _qrow(st, "0000")
    assert row["status"] == "needs_evidence"
    assert row["contradiction_rounds"] == 1
    assert row["contradiction_verdict"] == "unresolved"
    assert row["contradiction_request_ids"] and row["waiting_request_ids"] == row["contradiction_request_ids"]

    reqs = [r for r in st.rows("search_requests") if str(r.get("request_id")) in row["contradiction_request_ids"]]
    assert len(reqs) == 1
    assert reqs[0]["priority"] == "high"
    assert reqs[0]["submitted_by"] == "agent-D:contradiction"
    assert reqs[0]["for_question_id"] == "0000"
    assert reqs[0]["submitted_by"] != "agent-D", "矛盾请求必须与普通缺口可分（配额统计按它来）"


def test_i2_new_contradiction_spawns_a_question_and_keeps_asking(tmp_path):
    """I2：冒出新矛盾对 ⇒ 新建一条矛盾问题；原问题轮数 +1 且继续等证据。"""
    st = _contradiction_store(tmp_path)
    # 第三条同概念组的关系：与 0002 对立（0002 带否定，它不带）
    add_relation(st, "0004", ["0001", "0002"], "0001",
                 description="交换性条件可以推广到一切环。", quote="", sync=False)
    add_question(
        st, "0000",
        question="关系 0002 与 0003 的陈述互相矛盾，需要判定哪一方成立",
        origin="C:contradictions:0002+0003",
        kind="contradiction",
        contradiction_relation_ids=["0002", "0003"],
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0002", "0003"],
        priority="high",
    )
    agent = AgentD(st, c=RecordingC())
    out = agent.adjudicate("0000")
    assert out["verdict"] == "new_contradiction"
    assert len(out["new_question_ids"]) == 1

    row = _qrow(st, "0000")
    assert row["contradiction_rounds"] == 1
    assert row["status"] == "needs_evidence"
    assert row["contradiction_verdict"] == "new_contradiction"

    new_row = _qrow(st, out["new_question_ids"][0])
    assert new_row["kind"] == "contradiction"
    assert new_row["priority"] == "high"
    assert new_row["contradiction_relation_ids"] == ["0002", "0004"]
    assert new_row["origin"] == "C:contradictions:0002+0004"
    # 原问题仍然要继续追问（1 条新请求）
    assert len(out["request_ids"]) == 1


def test_i2_stops_within_budget_and_marks_persistent(tmp_path):
    """I2 终止（最重要）：真矛盾怎么查都不收敛 ⇒ 必须在预算内停下并标 persistent。"""
    st = _contradiction_store(tmp_path)
    add_question(
        st, "0000",
        question="关系 0002 与 0003 的陈述互相矛盾，需要判定哪一方成立",
        origin="C:contradictions:0002+0003",
        kind="contradiction",
        contradiction_relation_ids=["0002", "0003"],
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0002", "0003"],
        priority="high",
    )
    agent = AgentD(st, c=RecordingC())
    cap = IX.DEFAULTS["max_rounds_per_contradiction"]
    seen: list[dict] = []
    # 模拟"A 检索 → B 消化 → 回来再裁决"；真矛盾永远不收敛。
    # 循环上界跟着 `cap` 走（2026-10-15 裁定 C9 把它从 2 抬到 12）——
    # 写死 10 会让这条判据在 cap 抬高之后**因为跑不完而断言失败**，
    # 而失败的原因看起来像"真矛盾没收敛"，会被读成功能坏了。
    for _ in range(cap + 2):
        out = agent.adjudicate("0000")
        seen.append(out)
        # 把这一轮提交的请求标成完成（A 跑完），并让它们带回的文献被"消化"
        for rid in out["request_ids"]:
            with st.tx("search_requests", actor="fake-A") as tx:
                req = tx.find("search_requests", request_id=rid)
                req["done"] = True
                req["outcome"] = "ok"
                req["result_lit_ids"] = ["0000"]
                S.row_from_dict("search_requests", req).validate()
                tx.upsert("search_requests", req)
        if str(out["verdict"]) == "persistent":
            break

    assert seen[-1]["verdict"] == "persistent", "真矛盾没有收敛成 persistent"
    assert seen[-1]["code"] == "budget_exhausted"
    assert len(seen) <= cap + 1, f"裁决次数 {len(seen)} 超出预算（cap={cap}）—— 这是一个停不下来的循环"
    row = _qrow(st, "0000")
    assert row["contradiction_rounds"] <= cap
    assert row["contradiction_verdict"] == "persistent"
    assert row["status"] == "answered", "persistent 必须是终局（schema 也拒绝 open/researching）"
    assert row["waiting_request_ids"] == []
    assert "交人复核" in row["notes"] and "真实的文献分歧" in row["notes"]
    # 追问轮数不超过上限：请求条数 == 上限（不是无限多）
    assert len(row["contradiction_request_ids"]) <= cap

    # 再裁决一次也不该复活（幂等）：不得再产生新请求
    before = json.dumps(st.rows("search_requests"), ensure_ascii=False, sort_keys=True)
    assert agent.adjudicate("0000")["verdict"] == "persistent"
    assert json.dumps(st.rows("search_requests"), ensure_ascii=False, sort_keys=True) == before


def test_i2_global_quota_refuses_new_requests_byte_identically(tmp_path):
    """I2 全局配额：矛盾驱动的请求总数达到上限后不再新增（search_requests.json 逐字节不变）。"""
    st = _contradiction_store(tmp_path)
    add_question(
        st, "0000",
        question="关系 0002 与 0003 的陈述互相矛盾，需要判定哪一方成立",
        origin="C:contradictions:0002+0003",
        kind="contradiction",
        contradiction_relation_ids=["0002", "0003"],
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0002", "0003"],
        priority="high",
    )
    agent = AgentD(st, c=RecordingC(), config={"max_contradiction_requests": 1})
    first = agent.adjudicate("0000")
    assert first["verdict"] == "unresolved" and len(first["request_ids"]) == 1
    # 两本账都要对得上（批 R22 新增的两格读数）：`used` 是问题行上的台账口径（判定用），
    # `by_rows` 是请求行口径（本角色提交的、挂在矛盾问题上的行数），`reconciled` 只回答
    # "这两本账今天对不对得上"，不是"配额是否用完"（那是 `exhausted`）。
    assert agent._contradiction_budget() == {
        "used": 1, "limit": 1, "remaining": 0, "exhausted": True,
        "by_rows": 1, "reconciled": True,
    }

    path = st.data / "search_requests.json"
    before = path.read_bytes()
    second = agent.adjudicate("0000")
    assert path.read_bytes() == before, "配额用尽后仍然写了 search_requests.json"
    assert second["request_ids"] == []
    assert second["verdict"] == "persistent" and second["code"] == "budget_exhausted"
    assert _qrow(st, "0000")["status"] == "answered"
    assert len(_requests_of(st, "0000")) == 1


def test_i2_adjudicate_is_a_noop_for_gap_questions(tmp_path):
    """I2 负控：缺口类问题不得被"裁决"（三态：这是"没做"，不是"裁决过、没矛盾"）。"""
    st = _pair_store(tmp_path)
    add_question(st, "0000", question="甲与乙有关吗", related_concept_ids=["0001"], related_relation_ids=["0000"])
    out = AgentD(st, c=RecordingC()).adjudicate("0000")
    assert out["checked"] is False
    assert out["action"] == "not_a_contradiction"
    assert "没做" in out["reason"].replace("**", "")
    assert st.rows("search_requests") == []


def test_i2_terminal_state_satisfies_global_invariants(tmp_path):
    """I2：终局状态必须过 `verify` 的全局不变量（尤其 `stale_waiting`）。"""
    from agentflow.verify import verify_all

    st = _contradiction_store(tmp_path)
    add_question(
        st, "0000",
        question="关系 0002 与 0003 的陈述互相矛盾，需要判定哪一方成立",
        origin="C:contradictions:0002+0003",
        kind="contradiction",
        contradiction_relation_ids=["0002", "0003"],
        related_concept_ids=["0001", "0002"],
        related_relation_ids=["0002", "0003"],
        priority="high",
    )
    agent = AgentD(st, c=RecordingC())
    for _ in range(5):
        out = agent.adjudicate("0000")
        for rid in out["request_ids"]:
            with st.tx("search_requests", actor="fake-A") as tx:
                req = tx.find("search_requests", request_id=rid)
                req["done"] = True
                req["outcome"] = "ok"
                req["result_lit_ids"] = ["0000"]
                S.row_from_dict("search_requests", req).validate()
                tx.upsert("search_requests", req)
        if out["verdict"] == "persistent":
            break

    issues = verify_all(st).issues
    assert not [i for i in issues if i.code == "stale_waiting"], "终局状态还挂着等待项"
    assert not [i for i in issues if i.level == "error"], [str(i) for i in issues]


def test_i2_run_round_reports_adjudications(tmp_path):
    """I2(c)：run_round 必须先把可裁决的矛盾裁掉，并在返回值里给出 adjudications。"""
    st = _contradiction_store(tmp_path)
    agent = AgentD(st, c=RecordingC())
    report = _paths_report(
        "0000",
        [{"concept_path": ["0001", "0002"], "relation_chain": ["0002"], "level": "high", "hops": 1}],
        extra={"contradictions": [{"relation_ids": ["0002", "0003"], "signals": ["对立表述"]}]},
    )
    summary = agent.run_round(report)
    adjs = summary["adjudications"]
    assert adjs, "run_round 没有裁决本轮新吸收的矛盾"
    contra_adj = [a for a in adjs if a.get("action") == "ask_again_unresolved"]
    assert len(contra_adj) == 1
    qid = contra_adj[0]["question_id"]
    assert _qrow(st, qid)["kind"] == "contradiction"
    assert contra_adj[0]["request_ids"], "unresolved 必须真的提交了下一轮请求"
    assert set(contra_adj[0]["request_ids"]) <= set(summary["submitted"])
    # 矛盾问题不走"写分析"那一步（推进权在裁决，不在 research）
    assert qid not in [r["question_id"] for r in summary["researched"]]


# ============================================================ §3.1 问题等价类


def test_31_equivalent_questions_from_one_report_are_merged(tmp_path):
    """§3.1 正向：同一份报告里两条链条共享 ≥1 个关系代号 ⇒ 只生成 1 条问题。"""
    st = _pair_store(tmp_path)
    agent = AgentD(st, c=RecordingC())
    report = _paths_report(
        "0000",
        [
            {"concept_path": ["0001", "0002"], "relation_chain": ["0000", "0001"], "level": "high", "hops": 2},
            {"concept_path": ["0002", "0003"], "relation_chain": ["0001", "0002"], "level": "high", "hops": 2},
        ],
    )
    created = agent.ingest(report)
    assert len(created) == 1, f"共享关系代号的等价链没有被合并：{created}"
    rows = [r for r in _rows(st, "research_questions")]
    assert len(rows) == 1
    assert agent.last_ingest["equivalent_matched"], "必须能区分「命中等价类所以没新建」与「新建了」"
    assert agent.last_ingest["equivalent_matched"][0]["question_id"] == created[0]
    assert agent.last_ingest["equivalent_matched"][0]["by"] == "shared_relation_ids"
    assert created[0] in agent.last_ingest["created"]
    assert "merged_origins:" in rows[0]["notes"], "等价合并要留下 origin 痕迹"
    actions = [d["action"] for d in agent.last_ingest["decisions"]]
    assert actions.count("created") == 1 and actions.count("merged_by_equivalence") == 1


def test_31_ingest_detailed_return_value_distinguishes_created_from_merged(tmp_path):
    """§3.1：详细返回值里必须能一眼区分"新建"与"命中等价类所以没新建"。"""
    st = _pair_store(tmp_path)
    agent = AgentD(st, c=RecordingC())
    report = _paths_report(
        "0000",
        [
            {"concept_path": ["0001", "0002"], "relation_chain": ["0000", "0001"], "level": "high", "hops": 2},
            {"concept_path": ["0002", "0003"], "relation_chain": ["0001", "0002"], "level": "high", "hops": 2},
        ],
    )
    out = agent.ingest_detailed(report)
    assert out["created_count"] == len(out["created"]) == 1
    assert len(out["merged_by_equivalence"]) == 1
    assert out["merged_by_equivalence"][0]["question_id"] == out["created"][0]
    assert [d["action"] for d in out["decisions"]] == ["created", "merged_by_equivalence"]
    assert out["merged_by_content_key"] == []


def test_31_unrelated_questions_are_not_merged(tmp_path):
    """§3.1 负控：完全无关的问题不得被误合并（确实新建了两条）。"""
    st = _pair_store(tmp_path)
    agent = AgentD(st, c=RecordingC())
    report = _paths_report(
        "0000",
        [
            {"concept_path": ["0001", "0002"], "relation_chain": ["0000"], "level": "high", "hops": 1},
            {"concept_path": ["0003", "0004"], "relation_chain": ["0002"], "level": "high", "hops": 1},
        ],
    )
    created = agent.ingest(report)
    assert len(created) == 2, "无关的问题被误合并了"
    assert agent.last_ingest["equivalent_matched"] == []
    assert len(_rows(st, "research_questions")) == 2


def test_31_equivalence_layer_is_behind_the_content_key(tmp_path):
    """§3.1：内容键那一层保留（同一条链换报告号不得重复建问题）。"""
    st = _pair_store(tmp_path)
    agent = AgentD(st, c=RecordingC())
    paths = [
        {"concept_path": ["0001", "0002"], "relation_chain": ["0000", "0001"], "level": "high", "hops": 2},
        {"concept_path": ["0003", "0004"], "relation_chain": ["0002"], "level": "high", "hops": 1},
    ]
    assert len(agent.ingest(_paths_report("0000", paths))) == 2
    second = agent.ingest(_paths_report("0001", paths))
    assert second == []
    assert agent.last_ingest["merged"], "内容键合并层被等价类取代了（它必须保留）"
    assert len(_rows(st, "research_questions")) == 2


# ============================================================ §3.2 证据就绪判据


def _waiting_setup(tmp_path, *, new_relation_concepts: list[str]):
    """一个"请求已完成、文献已消化、但新关系落在别处"的等待场景。"""
    st = Store(tmp_path / "ws")
    st.init()
    for cid, name in (("0001", "甲"), ("0002", "乙"), ("0003", "丙"), ("0004", "丁")):
        add_concept(st, cid, name, definition="d", sync=False)
    add_relation(st, "0000", ["0001", "0002"], "0000", description="原有关系", quote="q", sync=False)
    add_literature(st, "0001", title="新文献", processed=True, sync=False)
    # A 检索 → B 抽取出来的新关系（属于新文献 0001）
    add_relation(st, "0001", new_relation_concepts, "0001", description="新关系", quote="new", sync=False)
    add_request(st, "r-0000", done=True, result_lit_ids=["0001"])
    sync_counters(st)
    add_question(
        st, "0000", question="q", priority="high",
        related_concept_ids=["0001", "0002"], related_relation_ids=["0000"],
        waiting_request_ids=["r-0000"], status="needs_evidence",
    )
    return st


def test_32_relevant_new_evidence_promotes_the_question(tmp_path):
    """§3.2 正向：新到关系落在问题概念集上 ⇒ relevant，问题推进（并记下判据）。"""
    st = _waiting_setup(tmp_path, new_relation_concepts=["0001", "0003"])
    agent = AgentD(st, c=RecordingC())
    poll = agent.poll()
    assert poll["promoted"] == ["0000"]
    assert poll["relevance"]["0000"]["relevance"] == "relevant"
    assert poll["relevance"]["0000"]["checked"] is True
    assert poll["relevance"]["0000"]["relevant_relation_ids"] == ["0001"]
    assert poll["held"] == []
    row = _qrow(st, "0000")
    assert row["status"] == "researching"
    assert row["related_relation_ids"] == ["0000", "0001"]
    assert "relevant" in row["notes"]


def test_32_irrelevant_new_evidence_holds_and_lowers_priority(tmp_path):
    """§3.2 负控：新到关系不落在概念集上 ⇒ irrelevant、不推进、优先级确实被降低。"""
    st = _waiting_setup(tmp_path, new_relation_concepts=["0003", "0004"])
    agent = AgentD(st, c=RecordingC())
    poll = agent.poll()
    assert poll["promoted"] == []
    assert poll["relevance"]["0000"]["relevance"] == "irrelevant"
    assert poll["held"] == [
        {"question_id": "0000", "why": "irrelevant", "priority_before": "high", "priority": "medium"}
    ]
    row = _qrow(st, "0000")
    assert row["status"] == "needs_evidence", "不相关的证据不得把问题推进"
    assert row["priority"] == "medium", "high→medium：优先级确实被降低了"
    assert "evidence_arrived_but_irrelevant" in row["notes"]
    assert row["related_relation_ids"] == ["0000"], "不相关的新关系不得并入证据"

    # 再 poll 两次：notes 不重复膨胀，优先级最低只到 low
    agent.poll()
    again = agent.poll()
    assert again["held"][0]["priority"] == "low"
    assert _qrow(st, "0000")["notes"].count("evidence_arrived_but_irrelevant") == 1


def test_32_unchecked_is_not_irrelevant(tmp_path):
    """§3.2 三态：`new_relations=None` ⇒ checked=False，不推进，且不是被当成 irrelevant。"""
    st = _waiting_setup(tmp_path, new_relation_concepts=["0003", "0004"])
    agent = AgentD(st, c=RecordingC())
    poll = agent.poll(relations=None)  # 显式：调用方没有能力提供关系快照
    assert poll["promoted"] == []
    rel = poll["relevance"]["0000"]
    assert rel["checked"] is False
    assert rel["relevance"] is None, "没检查时不许给出 relevance 取值"
    assert poll["held"][0]["why"] == "unchecked"
    row = _qrow(st, "0000")
    assert row["status"] == "needs_evidence"
    assert row["priority"] == "high", "「没检查」不得被当成「不相关」而降级"
    assert "evidence_relevance_unchecked" in row["notes"]
    assert "evidence_arrived_but_irrelevant" not in row["notes"]
    assert "不是「不相关」" in row["notes"]


def test_32_contradiction_priority_is_not_lowered(tmp_path):
    """§3.2：矛盾驱动的问题不因一次检索落空而降级（I2 的收敛靠轮数与全局配额）。"""
    st = _waiting_setup(tmp_path, new_relation_concepts=["0003", "0004"])
    with st.tx("research_questions", actor="test") as tx:
        q = tx.find("research_questions", question_id="0000")
        q["kind"] = "contradiction"
        q["contradiction_relation_ids"] = ["0000", "0001"]
        S.row_from_dict("research_questions", q).validate()
        tx.upsert("research_questions", q)
    agent = AgentD(st, c=RecordingC())
    poll = agent.poll()
    assert poll["promoted"] == []
    assert poll["held"][0]["why"] == "irrelevant"
    row = _qrow(st, "0000")
    assert row["priority"] == "high", "矛盾问题的优先级不因一次落空而降级"
    assert "evidence_arrived_but_irrelevant" in row["notes"]
    assert "矛盾驱动" in row["notes"]
