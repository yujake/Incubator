"""`agentflow.interactions` —— 跨智能体冻结契约的回归测试。

这个文件的存在理由：`interactions.py` 是 A/B/C/D/E/F/G/H 共用的唯一权威判据
模块（"同一判据写在两处 ⇒ 必然漂移"）。它一旦出错，错误会以静默的形式
扩散到每一个智能体 —— 例如"矛盾判据误报"会让 B 给 24% 的关系打上
`status="suspect"`，而没有任何地方报错。

因此这里同时覆盖：
- 正向（该触发的确实触发）；
- 负控（不该触发的确实没触发）—— 每个判据都有；
- 签名约束（I6 的"纯函数、不接收 store"是硬约束，写在导入期断言里）。
"""

from __future__ import annotations

import inspect

import pytest

from agentflow import interactions as I
from agentflow import schema as S


# ============================================================ 文本判据


def test_contains_uses_word_boundaries_for_ascii():
    """ASCII 词按词边界匹配：`no ` 不得命中 `non-commutative`。"""
    assert I.contains("this is not true", "not") is True
    assert I.contains("non-commutative ring", "no") is False, "词边界失效会把'非交换'判成'否定'"
    assert I.contains("非交换环", "交换") is True, "中文按子串匹配"


def test_negated_does_not_fire_on_technical_terms():
    """否定标记刻意只留"不" —— "非"/"无" 会命中术语本身，让判据恒为真。"""
    assert I.negated("A 不是 B") is True
    assert I.negated("非交换环") is False
    assert I.negated("无穷维空间") is False
    assert I.negated("non-commutative") is False


def test_concept_pair_key_is_none_for_fewer_than_two():
    """少于两个概念时显式返回 None（"这不是一对"），而不是空串。"""
    assert I.concept_pair_key(["0001"]) is None
    assert I.concept_pair_key([]) is None
    assert I.concept_pair_key(["0002", "0001"]) == "0001|0002"


# ============================================================ I2 矛盾检测


def _rel(rid: str, cids: list[str], text: str) -> dict:
    return {
        "relation_id": rid,
        "concept_ids": sorted(cids),
        "description": text,
        "lit_id": "0000",
    }


def test_detect_contradictions_strong_on_explicit_opposition():
    """正向：一句明确肯定、另一句明确否定 → `strength="strong"`。"""
    rels = [_rel("0001", ["0000", "0001"], "A 是 B。"), _rel("0002", ["0000", "0001"], "A 不是 B。")]
    got = I.detect_contradictions(rels)
    assert len(got) == 1
    assert got[0]["strength"] == "strong"
    assert got[0]["relation_ids"] == ["0001", "0002"]
    assert got[0]["strong_signals"]


def test_detect_contradictions_negative_control_mention_vs_silence():
    """负控（真实缺陷的回归）：一方提到肯定式、另一方压根没提这个词，
    不得被判成对立。

    旧实现写的是 `only_a != only_b`，其中 `only_x = 命中肯定式 and 未命中否定式`，
    于是"提到"与"没提"被算成两种相反态度。中文里 `("是","不是")` 的"是"
    无处不在（"等号是公开问题"），这在真实论文数据上产生了 24% 的假阳性。
    """
    rels = [_rel("0001", ["0000", "0001"], "等号是公开问题。"), _rel("0002", ["0000", "0001"], "该结果取自配套书。")]
    assert I.detect_contradictions(rels) == []


def test_detect_contradictions_negative_control_bare_negation_marker():
    """负控：裸否定标记（"不必"/"No …"）不是"否定主张"，只能出 `weak`。"""
    rels = [
        _rel("0001", ["0000", "0001"], "|S| = 0 的见证是显式的。"),
        _rel("0002", ["0000", "0001"], "端点 0 不必用数值搜索。"),
    ]
    got = I.detect_contradictions(rels)
    assert len(got) == 1
    assert got[0]["strength"] == "weak", "裸否定标记不得被当成对立主张"
    assert got[0]["strong_signals"] == []
    assert got[0]["weak_signals"]


def test_detect_contradictions_derives_concept_pair_key_in_place():
    """回归（静默失效）：行里只有 `concept_group_key`、没有 `concept_pair_key` 时，
    仍须能检测到矛盾。

    旧实现直接读 `concept_pair_key` ⇒ 对直接从表里读出来的行恒返回 `[]`，
    不报错、不告警，看起来就像"没有矛盾"。修法是就地推导派生态。
    """
    rels = [
        {"relation_id": "0001", "concept_ids": ["0000", "0001"], "description": "A 是 B。",
         "lit_id": "0000", "concept_group_key": "0000|0001"},
        {"relation_id": "0002", "concept_ids": ["0000", "0001"], "description": "A 不是 B。",
         "lit_id": "0000", "concept_group_key": "0000|0001"},
    ]
    got = I.detect_contradictions(rels)
    assert len(got) == 1 and got[0]["strength"] == "strong", (
        "从表里读出的行（只有 concept_group_key）必须也能检测到矛盾"
    )


def test_detect_contradictions_ignores_different_concept_groups():
    """负控：不同概念组之间永远不比较（矛盾只可能发生在谈同一件事的两句话之间）。"""
    rels = [_rel("0001", ["0000", "0001"], "A 是 B。"), _rel("0002", ["0002", "0003"], "A 不是 B。")]
    assert I.detect_contradictions(rels) == []


def test_detect_contradictions_skips_empty_text():
    """负控：没有可判文本时不猜（返回空，而不是"看起来像矛盾"）。"""
    rels = [
        {"relation_id": "0001", "concept_ids": ["0000", "0001"], "description": "A 是 B。", "lit_id": "0000"},
        {"relation_id": "0002", "concept_ids": ["0000", "0001"], "description": "", "lit_id": "0000"},
    ]
    assert I.detect_contradictions(rels) == []


# ============================================================ I2 裁决


def _contra(a: str = "0001", b: str = "0002") -> dict:
    return {"relation_ids": sorted([a, b])}


def _srel(rid: str, cids: list[str], text: str, *, status: str = "active", dup: str | None = None) -> dict:
    return {
        "relation_id": rid,
        "concept_ids": sorted(cids),
        "description": text,
        "lit_id": "0000",
        "status": status,
        "duplicate_of": dup,
    }


def test_adjudicate_resolved_when_a_side_is_gone():
    """一方已不在关系表 ⇒ resolved（矛盾在结构上已不存在）。"""
    scope = [_srel("0001", ["0000", "0001"], "A 是 B。")]
    got = I.adjudicate_contradiction(_contra(), scope_relations=scope)
    assert got["verdict"] == "resolved" and got["code"] == "side_removed"
    assert got["winner_relation_id"] == "0001"


def test_adjudicate_resolved_when_both_sides_gone():
    got = I.adjudicate_contradiction(_contra(), scope_relations=[])
    assert got["verdict"] == "resolved" and got["code"] == "side_removed"


def test_adjudicate_resolved_when_side_superseded_by_dedup():
    """一方被判重 ⇒ resolved，胜者是另一方。"""
    scope = [
        _srel("0001", ["0000", "0001"], "A 是 B。"),
        _srel("0002", ["0000", "0001"], "A 不是 B。", dup="0001"),
    ]
    got = I.adjudicate_contradiction(_contra(), scope_relations=scope)
    assert got["verdict"] == "resolved" and got["code"] == "side_superseded"
    assert got["winner_relation_id"] == "0001"


def test_adjudicate_resolved_when_text_no_longer_conflicts():
    """两条都还在，但重抽取改写了其中一条 ⇒ resolved / no_longer_conflicting。

    这是最有价值的一种解决：新证据让人把陈述改对了，而不是靠删掉一方。
    """
    scope = [
        _srel("0001", ["0000", "0001"], "A 是 B。"),
        _srel("0002", ["0000", "0001"], "A 也是 B。"),
    ]
    got = I.adjudicate_contradiction(_contra(), scope_relations=scope)
    assert got["verdict"] == "resolved" and got["code"] == "no_longer_conflicting"


def test_adjudicate_unresolved_within_budget():
    scope = [_srel("0001", ["0000", "0001"], "A 是 B。"), _srel("0002", ["0000", "0001"], "A 不是 B。")]
    got = I.adjudicate_contradiction(_contra(), scope_relations=scope, rounds=0, max_rounds=2)
    assert got["verdict"] == "unresolved" and got["code"] == "still_conflicting"
    assert got["rounds_after"] == 1


def test_adjudicate_persistent_when_budget_exhausted():
    """终止性：真矛盾追问到预算尽头必须标 persistent 并停止 —— 不是无限循环。"""
    scope = [_srel("0001", ["0000", "0001"], "A 是 B。"), _srel("0002", ["0000", "0001"], "A 不是 B。")]
    got = I.adjudicate_contradiction(_contra(), scope_relations=scope, rounds=2, max_rounds=2)
    assert got["verdict"] == "persistent" and got["code"] == "budget_exhausted"
    assert "停止自动追问" in got["reason"]


def test_adjudicate_new_contradiction_takes_priority_over_unresolved():
    """冒出新矛盾对是新信息，优先于"仍未解决"。"""
    scope = [
        _srel("0001", ["0000", "0001"], "A 是 B。"),
        _srel("0002", ["0000", "0001"], "A 不是 B。"),
        _srel("0003", ["0000", "0001"], "A 是 B 的充要条件成立。"),
    ]
    got = I.adjudicate_contradiction(_contra("0001", "0002"), scope_relations=scope, rounds=0, max_rounds=6)
    assert got["verdict"] == "new_contradiction", got
    assert got["new_relation_ids"]


def test_adjudicate_rejects_malformed_record():
    """负控：矛盾记录必须恰有 2 个 relation_ids（矛盾只可能发生在两句话之间）。"""
    with pytest.raises(ValueError):
        I.adjudicate_contradiction({"relation_ids": ["0001"]}, scope_relations=[])
    with pytest.raises(ValueError):
        I.adjudicate_contradiction({"relation_ids": ["0001", "0002", "0003"]}, scope_relations=[])


# ============================================================ I6 写入期闸门


def test_check_conflict_signature_has_no_store():
    """签名级断言：I6 的闸门绝不能接收 store/tx —— B 在自己的事务里调它，
    去查 store 就是 filelock 同进程重入（或死锁）。"""
    names = set(inspect.signature(I.check_conflict).parameters)
    assert names == {"draft_relation", "existing_relations"}, names
    assert not (names & {"store", "tx", "st"})
    I.assert_store_free(I.check_conflict)  # 不抛


def test_assert_store_free_catches_a_violation():
    """负控：`assert_store_free` 必须真的能抓住违规（否则那条约束只是装饰）。"""

    def bad(draft, *, store=None):  # noqa: ANN001
        return None

    with pytest.raises(AssertionError):
        I.assert_store_free(bad)


def test_check_conflict_three_states():
    """三态：`checked=False, conflict=None`（没检查）≠ `checked=True, conflict=False`（查了不冲突）。"""
    draft = {"concept_ids": ["0000", "0001"], "description": "A 是 B。", "lit_id": "0000"}
    none_chk = I.check_conflict(draft, existing_relations=None)
    assert none_chk["checked"] is False and none_chk["conflict"] is None
    assert none_chk["strength"] is None

    empty_chk = I.check_conflict(draft, existing_relations=[])
    assert empty_chk["checked"] is True and empty_chk["conflict"] is False
    assert empty_chk["compared"] == 0


def test_check_conflict_negative_control_draft_without_text():
    """负控：草稿没有可判文本 ⇒ `checked=False`（不是"不冲突"）。"""
    got = I.check_conflict({"concept_ids": ["0000", "0001"], "lit_id": "0000"}, existing_relations=[])
    assert got["checked"] is False and got["conflict"] is None
    assert "没检查" in got["reason"]


def test_check_conflict_strong_only_drives_conflict_flag():
    """核心分流：只有 strong 命中才让 `conflict=True`；weak 只被记录。

    为什么：`conflict=True` 的后果是 `status="suspect"`。若 weak 也能置它，
    实测会有 ~24% 的关系被打上 suspect，那时这个标记就不再指示任何东西 ——
    而"假报警比不校验更糟，因为它会训练人忽略告警"。
    """
    existing = [
        {"relation_id": "0001", "concept_ids": ["0000", "0001"], "description": "|S| = 0 的见证是显式的。",
         "lit_id": "0000"}
    ]
    weak_draft = {"concept_ids": ["0000", "0001"], "description": "端点 0 不必用数值搜索。", "lit_id": "0000"}
    got = I.check_conflict(weak_draft, existing_relations=existing)
    assert got["checked"] is True
    assert got["conflict"] is False, "weak 线索不得驱动 conflict"
    assert got["strength"] == "weak_only"
    assert got["weak_signals"] and got["weak_signals"][0]["relation_id"] == "0001"
    assert not got["conflicts_with"]

    strong_draft = {"concept_ids": ["0000", "0001"], "description": "A 不是 B。", "lit_id": "0000"}
    existing2 = [
        {"relation_id": "0002", "concept_ids": ["0000", "0001"], "description": "A 是 B。", "lit_id": "0000"}
    ]
    got2 = I.check_conflict(strong_draft, existing_relations=existing2)
    assert got2["conflict"] is True and got2["conflicts_with"] == ["0002"]
    assert got2["strength"] == "strong"


def test_check_conflict_scope_is_same_concept_group_only():
    """负控：概念组不同则不在比较范围内 —— "A 是 B" 与 "A 不是 C" 不是矛盾。"""
    existing = [
        {"relation_id": "0001", "concept_ids": ["0000", "0002"], "description": "A 不是 C。", "lit_id": "0000"}
    ]
    draft = {"concept_ids": ["0000", "0001"], "description": "A 是 B。", "lit_id": "0000"}
    got = I.check_conflict(draft, existing_relations=existing)
    assert got["checked"] is True and got["conflict"] is False and got["compared"] == 0


def test_check_conflict_draft_without_relation_id_still_compares():
    """回归：草稿还没有 relation_id 时，占位符必须确保比较不会因两边都是 None 而静默跳过。"""
    existing = [
        {"relation_id": "0001", "concept_ids": ["0000", "0001"], "description": "A 是 B。", "lit_id": "0000"}
    ]
    draft = {"concept_ids": ["0000", "0001"], "description": "A 不是 B。", "lit_id": "0000"}
    got = I.check_conflict(draft, existing_relations=existing)
    assert got["conflict"] is True, "草稿无 relation_id 时闸门不得恒不报冲突"


# ============================================================ I5 结构重复


def _concept(cid: str, name: str, *, aliases: list[str] | None = None) -> dict:
    return {"concept_id": cid, "name": name, "aliases": aliases or [], "normalized_name": ""}


def test_structural_duplicates_positive_with_name_evidence():
    """正向：邻域相同 + 规范化名字相同 → 候选且 `proposal="merge"`。"""
    concepts = [_concept("0000", "群"), _concept("0001", "群"), _concept("0002", "环")]
    rels = [
        {"relation_id": "0001", "concept_ids": ["0000", "0002"]},
        {"relation_id": "0002", "concept_ids": ["0001", "0002"]},
    ]
    got = I.structural_duplicate_pairs(concepts, rels)
    assert len(got) == 1 and not got[0].get("is_truncation_notice")
    assert got[0]["concept_ids"] == ["0000", "0001"]
    assert got[0]["name_evidence"] == "same_normalized_name"
    assert got[0]["proposal"] == "merge"


def test_structural_duplicates_negative_control_no_name_evidence():
    """负控（关键）：邻域相同但名字显然不同 ⇒ 只给 `proposal="review"`，
    且理由里写明"不得据此合并"。结构等价 ≠ 同义。"""
    concepts = [_concept("0000", "群"), _concept("0001", "环"), _concept("0002", "域")]
    rels = [
        {"relation_id": "0001", "concept_ids": ["0000", "0002"]},
        {"relation_id": "0002", "concept_ids": ["0001", "0002"]},
    ]
    got = I.structural_duplicate_pairs(concepts, rels)
    assert len(got) == 1
    assert got[0]["name_evidence"] == "none"
    assert got[0]["proposal"] == "review"
    assert "不得据此合并" in got[0]["reason"]


def test_structural_duplicates_negative_control_isolated_concepts():
    """负控：孤立概念（邻域都是空集）不得互相成为候选 —— 否则 O(n²) 噪声。"""
    concepts = [_concept("0000", "甲"), _concept("0001", "乙"), _concept("0002", "丙")]
    assert I.structural_duplicate_pairs(concepts, []) == []


def test_structural_duplicates_negative_control_adjacent_pair():
    """负控：两个概念之间已有直接关系 ⇒ 它们已被声明为不同的东西，不得合并。"""
    concepts = [_concept("0000", "群"), _concept("0001", "群"), _concept("0002", "环")]
    rels = [
        {"relation_id": "0001", "concept_ids": ["0000", "0001"]},
        {"relation_id": "0002", "concept_ids": ["0000", "0002"]},
        {"relation_id": "0003", "concept_ids": ["0001", "0002"]},
    ]
    assert I.structural_duplicate_pairs(concepts, rels) == []


def test_structural_duplicates_truncation_is_reported_not_hidden():
    """截断必须说出来：截断通知单列，不混进候选里。"""
    concepts = [_concept(f"000{i}", f"概念{i}") for i in range(4)] + [_concept("0009", "中心")]
    rels = [{"relation_id": f"000{i}", "concept_ids": [f"000{i}", "0009"]} for i in range(4)]
    got = I.structural_duplicate_pairs(concepts, rels, max_pairs=1)
    notices = [x for x in got if x.get("is_truncation_notice")]
    cands = [x for x in got if not x.get("is_truncation_notice")]
    assert len(notices) == 1 and "被截断" in notices[0]["reason"]
    assert len(cands) <= 1
    assert all(x.get("truncated") is True for x in cands)


# ============================================================ §3.1 问题等价类


def test_find_equivalent_question_by_shared_relation_ids():
    qs = [{"question_id": "0001", "related_relation_ids": ["0007"], "related_concept_ids": ["0000"],
           "status": "open", "question": "?"}]
    got = I.find_equivalent_question(qs, concept_ids=["0009"], relation_ids=["0007"])
    assert got["matched"] is True and got["by"] == "shared_relation_ids"


def test_find_equivalent_question_by_concept_jaccard():
    qs = [{"question_id": "0001", "related_relation_ids": ["0001"], "related_concept_ids": ["0000", "0001", "0002"],
           "status": "open", "question": "?"}]
    got = I.find_equivalent_question(qs, concept_ids=["0000", "0001", "0002"], relation_ids=["0099"])
    assert got["matched"] is True and got["by"] == "concept_jaccard"


def test_find_equivalent_question_negative_control():
    """负控：完全不相关的问题不得被误合并 —— 并且要能区分"查了没有"与"没查"。"""
    qs = [{"question_id": "0001", "related_relation_ids": ["0001"], "related_concept_ids": ["0000", "0001"],
           "status": "open", "question": "?"}]
    got = I.find_equivalent_question(qs, concept_ids=["0007", "0008"], relation_ids=["0099"])
    assert got["matched"] is False and got["by"] is None
    assert "已检查 1 个已有问题" in got["detail"]


# ============================================================ §3.2 证据就绪判据


def test_evidence_relevance_three_states():
    q = {"related_concept_ids": ["0000"], "evidence_lit_ids": []}
    none_chk = I.evidence_relevance(q, new_relations=None)
    assert none_chk["checked"] is False and none_chk["relevance"] is None

    irrelevant = I.evidence_relevance(q, new_relations=[{"relation_id": "0001", "concept_ids": ["0007"]}])
    assert irrelevant["checked"] is True and irrelevant["relevance"] == "irrelevant"
    assert irrelevant["advice"] == "lower_priority"

    relevant = I.evidence_relevance(q, new_relations=[{"relation_id": "0001", "concept_ids": ["0000", "0007"]}])
    assert relevant["checked"] is True and relevant["relevance"] == "relevant"
    assert relevant["relevant_relation_ids"] == ["0001"]


def test_evidence_relevance_negative_control_empty_list_is_checked():
    """三态负控：空列表是"查了、没有"，不是"没查"。"""
    got = I.evidence_relevance({"related_concept_ids": ["0000"]}, new_relations=[])
    assert got["checked"] is True and got["relevance"] == "irrelevant"


# ============================================================ I7 优先级与配额


def test_priority_rank_unknown_falls_to_low():
    assert I.priority_rank("high") < I.priority_rank("medium") < I.priority_rank("low")
    assert I.priority_rank(None) == I.priority_rank("low")
    assert I.priority_rank("HIGH") == I.priority_rank("low"), "大小写不同不得被当成高优先级"


def test_resolve_priority_table_and_fallback():
    assert I.resolve_priority("agent-D:contradiction")[0] == "high"
    assert I.resolve_priority("agent-B")[0] == "low"
    p, why = I.resolve_priority("agent-unregistered")
    assert p == "low" and "未登记" in why
    p2, why2 = I.resolve_priority("agent-B", "high")
    assert p2 == "high", "显式给出的合法优先级优先"
    p3, why3 = I.resolve_priority("agent-B", "HIGHEST")
    assert p3 == "low" and "非法" in why3


def test_order_pending_requests_high_before_low_then_fifo():
    rows = [
        {"request_id": "r-0001", "done": False, "priority": "low", "timestamp": "2026-01-01T00:00:00+00:00",
         "lease_until": None},
        {"request_id": "r-0002", "done": False, "priority": "high", "timestamp": "2026-01-01T00:00:09+00:00",
         "lease_until": None},
        {"request_id": "r-0003", "done": False, "priority": "high", "timestamp": "2026-01-01T00:00:01+00:00",
         "lease_until": None},
    ]
    order = [r["request_id"] for r in I.order_pending_requests(rows)]
    assert order == ["r-0003", "r-0002", "r-0001"], "先 high；同级按 timestamp FIFO"


def test_order_pending_requests_negative_control_done_never_picked():
    rows = [{"request_id": "r-0001", "done": True, "priority": "high", "timestamp": "t", "lease_until": None}]
    assert I.order_pending_requests(rows) == []


def test_order_pending_requests_expired_lease_first_within_priority():
    """同级下，租约已过期的排在全新任务前面（收回沉没成本）。"""
    rows = [
        {"request_id": "r-0001", "done": False, "priority": "medium", "timestamp": "2026-01-01T00:00:00+00:00",
         "lease_until": "2099-01-01T00:00:00+00:00", "claimed_by": "agent-A"},
        {"request_id": "r-0002", "done": False, "priority": "medium", "timestamp": "2026-01-01T00:00:05+00:00",
         "lease_until": "2000-01-01T00:00:00+00:00", "claimed_by": "agent-A"},
    ]
    order = [r["request_id"] for r in I.order_pending_requests(rows)]
    assert order == ["r-0002", "r-0001"]


def test_order_pending_requests_total_order_is_deterministic():
    """全序：优先级、时间都相同时用 request_id 兜底，否则断言会随机失败。"""
    rows = [
        {"request_id": "r-0002", "done": False, "priority": "high", "timestamp": "t", "lease_until": None},
        {"request_id": "r-0001", "done": False, "priority": "high", "timestamp": "t", "lease_until": None},
    ]
    assert [r["request_id"] for r in I.order_pending_requests(rows)] == ["r-0001", "r-0002"]


def test_admit_search_request_rejects_at_limit():
    rows = [{"request_id": "r-0001", "done": False}, {"request_id": "r-0002", "done": False}]
    got = I.admit_search_request(rows, submitted_by="agent-D", max_inflight=2)
    assert got["admitted"] is False and got["inflight"] == 2 and got["limit"] == 2
    assert "拒绝新请求" in got["reason"]


def test_admit_search_request_admits_below_limit_and_resolves_priority():
    rows = [{"request_id": "r-0001", "done": True}]
    got = I.admit_search_request(rows, submitted_by="agent-D:contradiction", max_inflight=2)
    assert got["admitted"] is True and got["priority"] == "high"
    assert got["inflight"] == 0, "done 的请求不算在途"


def test_reprocess_counts_ignores_rejected_rows():
    """口径负控：被拒的不计入 —— 否则闸门会用"我拒绝过"来证明"我做过了"，
    拒绝两次之后一个从未被处理过的关系就再也进不来了。"""
    rows = [
        {"reprocess_id": "p-0001", "relation_ids": ["0001"], "status": "rejected"},
        {"reprocess_id": "p-0002", "relation_ids": ["0001"], "status": "done"},
        {"reprocess_id": "p-0003", "relation_ids": ["0002"], "status": "pending"},
    ]
    assert I.reprocess_counts(rows) == {"0001": 1, "0002": 1}


def test_admit_reprocess_request_negative_control_empty_target():
    """负控：无目标的重抽取会退化成全量重抽 ⇒ 必须拒绝。

    这一条只覆盖 `relation_ids=[]` 这一种写法。纯空白 `["", "  "]` 在语义上
    与它同形（零个有效目标），而实现按过滤前的集合判空 ⇒ 今天被放行：
    那是已登记为 `G-8` 的缺陷（`docs/PROPOSALS.md`），修法要动
    `interactions.py`（FC-27 禁改区）。

    所以这里不重复那条断言，只留指路：纯空白当前行为的绿侧判据是
    `tests/test_coverage_interactions.py::test_blank_only_targets_are_still_admitted_today`
    （它带一条"按 `G-8` 修好之后必红"的负控）。同一个判据写两处会让两处口径
    各自漂移（`R003` 的形态）。
    """
    got = I.admit_reprocess_request([], relation_ids=[], reason="low_information")
    assert got["admitted"] is False and "全量重抽" in got["reason"]


def test_admit_reprocess_request_negative_control_bad_reason():
    got = I.admit_reprocess_request([], relation_ids=["0001"], reason="因为我觉得")
    assert got["admitted"] is False and "reason 必须是" in got["reason"]


def test_admit_reprocess_request_respects_per_relation_cap():
    rows = [
        {"reprocess_id": "p-0001", "relation_ids": ["0001"], "status": "done"},
        {"reprocess_id": "p-0002", "relation_ids": ["0001"], "status": "pending"},
    ]
    got = I.admit_reprocess_request(rows, relation_ids=["0001", "0002"], reason="quote_unverifiable",
                                    max_per_relation=2)
    assert got["admitted"] is False and got["blocked"] == ["0001"]

    ok_got = I.admit_reprocess_request(rows, relation_ids=["0002"], reason="quote_unverifiable",
                                       max_per_relation=2)
    assert ok_got["admitted"] is True


def test_next_prefixed_id_skips_used_numbers():
    rows = [{"request_id": "r-0001"}, {"request_id": "r-0003"}, {"request_id": "p-0009"}]
    assert I.next_prefixed_id(rows, "request_id", "r") == "r-0004"
    assert I.next_prefixed_id([], "reprocess_id", "p") == "p-0001"


# ============================================================ 预算默认值


def test_defaults_are_complete_and_positive():
    """所有闸门都必须有正的默认值 —— 0 或缺失会静默把闸门关掉。"""
    for k, v in I.DEFAULTS.items():
        assert isinstance(v, (int, float)) and not isinstance(v, bool), (k, v)
        assert v > 0, (k, v)
    # 计数量类的闸门必须是整数（用 0.5 轮的预算没有意义，只会让边界不可判定）
    for k in ("max_inflight_requests", "max_rounds_per_contradiction", "max_contradiction_requests",
              "max_gap_requests_per_run", "max_reprocess_per_relation", "structural_duplicate_max_pairs"):
        assert isinstance(I.DEFAULTS[k], int), k
    assert 0 < I.DEFAULTS["question_jaccard_threshold"] <= 1
    assert set(I.ADJUDICATION_CODES) == {
        "side_removed", "side_superseded", "no_longer_conflicting",
        "still_conflicting", "budget_exhausted", "new_conflict",
    }
    assert set(S.CONTRADICTION_VERDICTS) >= {"resolved", "unresolved", "new_contradiction", "persistent"}


# ============================================================ P-4：取号的 4 位上限


def test_next_prefixed_id_normal_range_is_unchanged():
    """正控（`P-4`）：正常范围内的取号序列必须逐字不变。

    上限下沉最大的风险是"顺手改了取号语义"。这条用例把改前的行为逐条钉住
    （改前实测序列见 `temp/_b5a_p4_before.txt`）。
    """
    assert I.next_prefixed_id([], "request_id", "r") == "r-0001"
    assert I.next_prefixed_id([{"request_id": "r-0001"}], "request_id", "r") == "r-0002"
    # 中间有空洞 ⇒ 仍然取 max+1（不复用空洞里的号，避免静默指向另一条请求）
    rows = [{"request_id": "r-0001"}, {"request_id": "r-0003"}]
    assert I.next_prefixed_id(rows, "request_id", "r") == "r-0004"
    # 前缀各自独立
    assert I.next_prefixed_id([{"reprocess_id": "p-0042"}], "reprocess_id", "p") == "p-0043"
    assert I.next_prefixed_id([{"task_id": "t-0005"}], "task_id", "t") == "t-0006"
    # 上限之内最大的那一档仍然照常发号（9999 本身是合法 4 位 ID）
    assert I.next_prefixed_id([{"request_id": "r-9998"}], "request_id", "r") == "r-9999"


def test_next_prefixed_id_refuses_past_the_4_digit_ceiling():
    """负控（`P-4`）：编号已到上限 ⇒ 必须抛，且错误信息里给出上限值。

    改前实测：这里静默返回 `"r-10000"`（5 位），而 `SearchRequest.validate`
    只查非空 ⇒ 它会一路落库。所以这条负控钉的是"静默升位宽"这个形态本身。
    """
    from agentflow.store import MAX_ID

    with pytest.raises(ValueError) as ei:
        I.next_prefixed_id([{"request_id": "r-9999"}], "request_id", "r")
    msg = str(ei.value)
    assert str(MAX_ID) in msg, f"错误信息必须给出上限值 {MAX_ID}：{msg}"
    assert "r-10000" in msg, f"必须回显那个越界号（可诊断）：{msg}"


def test_next_prefixed_id_refuses_when_rows_already_contain_5_digit_id():
    """负控的第二条路径：表里已经有 `r-10000` ⇒ 也要拒绝，不许继续往上加。"""
    with pytest.raises(ValueError):
        I.next_prefixed_id([{"request_id": "r-10000"}], "request_id", "r")


def test_next_prefixed_id_still_refuses_a_prefix_with_separator():
    """既有负控不许被这次改动放松：带连接号的前缀仍然当场炸。"""
    with pytest.raises(ValueError):
        I.next_prefixed_id([], "request_id", "r-")
