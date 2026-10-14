"""C 的 I1 服务面 与 I3 缺口直连 A 的性质测试（DESIGN-INTERACTIONS.md §1）。

这一组测试要钉住的是三类"做错了也不报错"的地方：

1. 静默截断：有界查询一旦悄悄少给结果，D 会把"我只展开了一部分"读成
   "就这些邻居/就这些矛盾"，进而写出一个口吻确定的错误结论。
   所以每条有界路径都必须有"超预算 ⇒ truncated=True"的正向断言。
2. 三态被压平："没查"（`checked=False`）与"查了没有"（`checked=True` + `empty=True`）
   被压成同一个 `[]` / `False` 是本项目最贵的教训（DESIGN §3.4）。所以每个负控
   都同时断言 `checked` 的取值，而不是只断言"结果是空的"。
3. 越权写入：I3 之外的任何一次服务调用都不得改动知识表；
   而 I3 本身默认关闭，且受每轮上限 / 在途上限 / 主题去重三道闸门约束。

每个交互都配了负控（"它不该触发的场景，断言它确实没触发"）——
只有正向信号时，"有"与"没有"一样容易通过测试。
"""

from __future__ import annotations

import json

import pytest

from agentflow import conceptrows as CR
from agentflow import schema as S
from agentflow.agent_c import SUBMITTER, AgentC, check_conflict
from agentflow.store import Store
from agentflow.tools.base import ToolRegistry
from agentflow.tools.graph_tools import register as register_graph_tools

from conftest import add_concept, add_relation, add_request, read_data_bytes, sync_counters
from demo_dataset_helper import build_demo

_LONG_DESC = "这是一条足够长的关系描述，用来说明信息量不低"


# ============================================================ 夹具


@pytest.fixture
def demo(tmp_path) -> Store:
    """演示数据集：10 概念 / 15 关系（含 2 跳与 3 跳路径、一个孤立概念）。"""
    return Store(build_demo(tmp_path / "demo"))


def _kn_store(root) -> Store:
    """一张有结构洞的小图：4 概念 / 3 关系，形成 0000-0003 与 0001-0002 两个洞。

    刻意造成"多条候选都达到 medium"的局面，好让 I3 的"每轮最多 3 条"这道闸门
    真的被触发（否则测的是"提交了几条"，而不是"上限生效了"）。
    """
    st = Store(root)
    st.init()
    for i in range(4):
        add_concept(st, f"{i:04d}", f"概念{i}", definition="d", sync=False)
    add_relation(st, "0000", ["0000", "0001"], "0000", description=_LONG_DESC, quote="q0", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0000", "0002"], "0001", description=_LONG_DESC, quote="q1", quote_verified=True, sync=False)
    add_relation(st, "0002", ["0001", "0003"], "0000", description=_LONG_DESC, quote="q2", quote_verified=True, sync=False)
    sync_counters(st)
    return st


@pytest.fixture
def kn(tmp_path) -> Store:
    return _kn_store(tmp_path / "ws")


def _contradiction_store(root) -> Store:
    """同一概念组的两条关系：一条明确肯定、一条明确否定同一对立词组。

    刻意写成 "群是阿贝尔群" / "群不是阿贝尔群"（而不是"一定是/一定不是"）：
    `interactions` 现在把字面判据分两档，只有"一方明确肯定、另一方明确否定"才算
    `strong`；掺进"一定"这类修饰词会退化成 `weak`（见 test_..._weak_only）。
    """
    st = Store(root)
    st.init()
    add_concept(st, "0000", "群", definition="d", sync=False)
    add_concept(st, "0001", "阿贝尔群", definition="d", sync=False)
    add_relation(
        st, "0000", ["0000", "0001"], "0000",
        description="群是阿贝尔群", quote="q0", quote_verified=True, sync=False,
    )
    add_relation(
        st, "0001", ["0000", "0001"], "0001",
        description="群不是阿贝尔群", quote="q1", quote_verified=True, sync=False,
    )
    sync_counters(st)
    return st


def _dup_store(root, *, same_name: bool = True, direct: bool = False) -> Store:
    """结构重复的素材：0000 与 0001 的邻域完全相同（都只连 0002、0003）。

    两个"桥"概念 0002/0003 的邻域也完全相同 —— 它们名字显然不同，
    正好当"只有结构证据 ⇒ proposal=review"的负控素材。
    """
    st = Store(root)
    st.init()
    add_concept(st, "0000", "群", definition="d", sync=False)
    add_concept(st, "0001", "群" if same_name else "环", definition="d", sync=False)
    add_concept(st, "0002", "桥甲", definition="d", sync=False)
    add_concept(st, "0003", "桥乙", definition="d", sync=False)
    add_relation(st, "0000", ["0000", "0002"], "0000", description=_LONG_DESC, quote="q0", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0000", "0003"], "0000", description=_LONG_DESC, quote="q1", quote_verified=True, sync=False)
    add_relation(st, "0002", ["0001", "0002"], "0000", description=_LONG_DESC, quote="q2", quote_verified=True, sync=False)
    add_relation(st, "0003", ["0001", "0003"], "0000", description=_LONG_DESC, quote="q3", quote_verified=True, sync=False)
    if direct:
        add_relation(st, "0004", ["0000", "0001"], "0000", description=_LONG_DESC, quote="q4", quote_verified=True, sync=False)
    sync_counters(st)
    return st


def _pair_keys(candidates) -> set[frozenset[str]]:
    return {frozenset(str(c) for c in cand["concept_ids"]) for cand in candidates}


# ============================================================ (1) neighbors


def test_neighbors_returns_exact_one_hop_and_two_hop_sets(demo):
    """1 跳必须恰好是图上的直接邻居；2 跳必须把它们的新邻居并进来（含 distance）。"""
    c = AgentC(demo)

    one = c.neighbors("0000", depth=1)
    assert one["checked"] is True and one["truncated"] is False and one["empty"] is False
    got1 = {n["concept_id"] for n in one["nodes"] if n["distance"] == 1}
    assert got1 == {"0001", "0002", "0005", "0006", "0008"}
    assert [n for n in one["nodes"] if n["distance"] == 0 and n["concept_id"] == "0000"], "起点必须以 distance=0 出现"
    # 边必须给出关系代号（否则 D 还要自己再查一次才能溯源）
    assert all(e["relation_ids"] for e in one["edges"])
    assert {e["from"] for e in one["edges"]} <= {n["concept_id"] for n in one["nodes"]}

    two = c.neighbors("0000", depth=2)
    got2 = {n["concept_id"]: n["distance"] for n in two["nodes"]}
    assert got2["0000"] == 0
    for nid in got1:
        assert got2[nid] == 1
    assert got2["0003"] == 2 and got2["0004"] == 2 and got2["0007"] == 2
    assert "0009" not in got2, "孤立概念永远不该出现在别人的邻域里"
    assert two["depth"] == 2


def test_neighbors_reports_truncation_instead_of_silently_returning_less(demo):
    """超 max_nodes 必须 truncated=True + 说明原因；不许悄悄只给一部分。"""
    c = AgentC(demo)
    full = c.neighbors("0000", depth=1, max_nodes=500)
    small = c.neighbors("0000", depth=1, max_nodes=2)

    assert small["checked"] is True
    assert small["truncated"] is True, "静默截断会让 D 以为'就这些邻居'"
    assert small["max_nodes"] == 2
    assert len(small["nodes"]) == 2 < len(full["nodes"])
    assert "max_nodes" in small["reason"] and "不完整" in small["reason"]
    assert small["budget_notes"] and "max_nodes=2" in small["budget_notes"][0]
    # 截断只影响"给多少"，不影响"给的对不对"：返回的节点必须是真实的近邻
    assert {n["concept_id"] for n in small["nodes"]} <= {n["concept_id"] for n in full["nodes"]}


def test_neighbors_unknown_concept_is_checked_true_not_false(demo):
    """查不存在的概念 ⇒ checked=True（查了、没有），reason 必须点明"不在概念表里"。"""
    res = AgentC(demo).neighbors("9999")

    assert res["checked"] is True, "『没有这个概念』是查过之后的结论，不是『没查』"
    assert res["nodes"] == [] and res["edges"] == []
    assert res["empty"] is True and res["truncated"] is False
    assert "不在概念表里" in res["reason"] and "9999" in res["reason"]


def test_neighbors_is_unchecked_when_there_is_no_concept_table(tmp_path):
    """概念表为空 ⇒ checked=False（"根本没查"，与"查了没有"必须能区分）。"""
    st = Store(tmp_path / "empty")
    st.init()
    res = AgentC(st).neighbors("0000")

    assert res["checked"] is False and res["empty"] is True
    assert "概念表为空" in res["reason"] and "没查" in res["reason"]


def test_neighbors_on_isolated_concept_is_checked_and_empty(tmp_path):
    """孤立概念：checked=True 但 empty=True —— 这正是三态要保住的那种答案。"""
    st = Store(tmp_path / "iso")
    st.init()
    add_concept(st, "0000", "孤立概念", definition="d", sync=False)
    sync_counters(st)
    res = AgentC(st).neighbors("0000")

    assert res["checked"] is True and res["empty"] is True and res["truncated"] is False
    assert [n["concept_id"] for n in res["nodes"]] == ["0000"], "起点本身仍在结果里（distance=0）"
    assert "孤立概念" in res["reason"]


# ============================================================ (2) relations_between


def test_relations_between_returns_relation_ids_and_brief_rows(demo):
    """有边时必须给出 relation_ids 与够用的精简行（含三态 quote_verified）。"""
    res = AgentC(demo).relations_between("0000", "0001")
    assert res["checked"] is True and res["empty"] is False
    assert res["relation_ids"] == ["0000"]
    row = res["relations"][0]
    for field in ("relation_id", "concept_ids", "description", "lit_id", "page_range", "quote_verified", "status", "statement"):
        assert field in row, f"精简行缺字段 {field}"
    assert row["quote_verified"] is True and row["status"] == "active"

    # 无向：反过来查同一对概念必须得到同一批关系
    assert AgentC(demo).relations_between("0001", "0000")["relation_ids"] == ["0000"]


def test_relations_between_no_edge_is_checked_true_and_empty(demo):
    """三态负控：无边 ⇒ relation_ids==[] 且 empty=True 且 checked=True。"""
    res = AgentC(demo).relations_between("0000", "0009")

    assert res["checked"] is True, "查过了、没有 —— 绝不能压成 checked=False（那是『没查』）"
    assert res["relation_ids"] == [] and res["relations"] == []
    assert res["empty"] is True
    assert "没有关系" in res["reason"]


def test_relations_between_include_inactive_filter_is_reported(tmp_path):
    """include_inactive=False 过滤掉的是"确实存在但不 active"的关系 —— 必须如实说过滤了几条。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0000", "群", definition="d", sync=False)
    add_concept(st, "0001", "阿贝尔群", definition="d", sync=False)
    add_relation(st, "0000", ["0000", "0001"], "0000", description=_LONG_DESC, quote="q0", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0000", "0001"], "0000", description=_LONG_DESC, quote="q1", status="suspect", sync=False)
    sync_counters(st)
    c = AgentC(st)

    on = c.relations_between("0000", "0001")
    off = c.relations_between("0000", "0001", include_inactive=False)
    assert sorted(on["relation_ids"]) == ["0000", "0001"]
    assert off["relation_ids"] == ["0000"] and off["filtered_out"] == 1
    assert "过滤" in off["reason"]


def test_relations_between_is_unchecked_when_there_is_no_concept_table(tmp_path):
    """概念表为空 ⇒ checked=False（"没查"），与"查了没有"分开。"""
    st = Store(tmp_path / "empty")
    st.init()
    res = AgentC(st).relations_between("0000", "0001")

    assert res["checked"] is False and res["relation_ids"] == [] and res["empty"] is True
    assert "概念表为空" in res["reason"]


# ============================================================ (3) contradictions


def test_contradictions_hits_a_handmade_literal_pair(tmp_path):
    """正向：同概念组、一句明确肯定一句明确否定 ⇒ 命中，且标为 `strong`。"""
    st = _contradiction_store(tmp_path / "ws")
    res = AgentC(st).contradictions()

    assert res["checked"] is True and res["scope"] == "all_relations"
    assert res["scanned"] == 2
    assert len(res["contradictions"]) == 1
    pair = res["contradictions"][0]
    assert sorted(pair["relation_ids"]) == ["0000", "0001"]
    assert pair["detection"] == "literal"
    # 明确对立主张 = strong；只有 strong 才够格当研究线索
    assert pair["strength"] == "strong" and pair["strong_signals"]
    assert res["strong_count"] == 1 and res["weak_count"] == 0
    assert res["strong_relation_id_pairs"] == [["0000", "0001"]]
    # 诚实性：绝不许把"字面检测"说成"语义分析"，也不许把 weak 说成矛盾
    assert res["method"] == "literal"
    assert "只做字面判据，不声称能判定一般语义矛盾" in res["method_note"]
    assert "strong" in res["method_note"] and "weak" in res["method_note"]
    assert "假阳性" in res["method_note"]


def test_contradictions_separates_strong_from_weak_and_says_weak_is_only_a_clue(tmp_path):
    """strong / weak 必须分开统计：weak（仅否定词出现与否不一致）假阳性极高。

    实测教训（`interactions` 的 docstring）：25 条真实关系里 weak 报了 6 条，没有一条
    是矛盾。把它们混进同一个计数，等于训练人忽略告警。
    """
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0000", "群", definition="d", sync=False)
    add_concept(st, "0001", "阿贝尔群", definition="d", sync=False)
    add_concept(st, "0002", "域", definition="d", sync=False)
    # strong 对：明确肯定 vs 明确否定
    add_relation(st, "0000", ["0000", "0001"], "0000", description="群是阿贝尔群", quote="q0", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0000", "0001"], "0000", description="群不是阿贝尔群", quote="q1", quote_verified=True, sync=False)
    # weak 对：只是"不必"这种否定词出现了，并没有对立主张
    add_relation(st, "0002", ["0000", "0002"], "0000", description="域上不必用数值搜索", quote="q2", quote_verified=True, sync=False)
    add_relation(st, "0003", ["0000", "0002"], "0000", description="域上可以用符号计算", quote="q3", quote_verified=True, sync=False)
    sync_counters(st)
    res = AgentC(st).contradictions()

    assert res["scanned"] == 4
    assert res["strong_count"] == 1 and res["weak_count"] == 1
    by_strength = {x["strength"]: x for x in res["contradictions"]}
    assert sorted(by_strength["strong"]["relation_ids"]) == ["0000", "0001"]
    assert sorted(by_strength["weak"]["relation_ids"]) == ["0002", "0003"]
    assert "线索" in by_strength["weak"]["weak_signals"][0]
    assert "不得当作矛盾呈现" in res["reason"]


def test_contradictions_negative_control_consistent_pair_is_not_hit(tmp_path):
    """负控：同概念组但表述一致（都不带否定、都只说肯定式）⇒ 不命中。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0000", "群", definition="d", sync=False)
    add_concept(st, "0001", "阿贝尔群", definition="d", sync=False)
    add_relation(st, "0000", ["0000", "0001"], "0000", description="群是阿贝尔群", quote="q0", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0000", "0001"], "0000", description="每个群都是阿贝尔群", quote="q1", quote_verified=True, sync=False)
    sync_counters(st)
    res = AgentC(st).contradictions()

    assert res["checked"] is True and res["scanned"] == 2
    assert res["contradictions"] == [], "表述一致的两条关系被误判成矛盾（假矛盾会把 D 引向不存在的问题）"
    assert "不等于" in res["reason"], "没查到矛盾时必须限制结论的强度，不能读成'文献之间没有分歧'"


def test_contradictions_scans_only_the_given_relation_ids(tmp_path):
    """只复核给定关系（I2 的用法）：scanned 必须等于给定条数，且不越界扫别的。"""
    st = _contradiction_store(tmp_path / "ws")
    add_concept(st, "0002", "域", definition="d", sync=False)
    add_relation(st, "0002", ["0000", "0002"], "0002", description="群不是域", quote="q2", quote_verified=True, sync=False)
    sync_counters(st)
    c = AgentC(st)

    assert c.contradictions()["scanned"] == 3
    res = c.contradictions(relation_ids=["0000", "0001"])
    assert res["scope"] == "given_relation_ids"
    assert res["scanned"] == 2, "给了两个关系就应该只扫两条"
    assert len(res["contradictions"]) == 1

    # 只给一条：同组里没有第二条可比 ⇒ 查了、没有（不是"没查"）
    one = c.contradictions(relation_ids=["0000"])
    assert one["checked"] is True and one["scanned"] == 1 and one["contradictions"] == []


def test_contradictions_unknown_ids_are_unchecked_not_clean(tmp_path):
    """三态负控：给定的 relation_ids 一条都不存在 ⇒ checked=False（没查），不是"不矛盾"。"""
    st = _contradiction_store(tmp_path / "ws")
    res = AgentC(st).contradictions(relation_ids=["8888", "9999"])

    assert res["checked"] is False and res["scanned"] == 0 and res["contradictions"] == []
    assert res["missing_relation_ids"] == ["8888", "9999"]
    assert "没检查" in res["reason"] or "没查" in res["reason"]


def test_contradictions_truncates_the_returned_pairs_honestly(tmp_path):
    """超 limit 时只返回前 limit 条，但必须 truncated=True 并说明"不能说只有这些"。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0000", "群", definition="d", sync=False)
    add_concept(st, "0001", "阿贝尔群", definition="d", sync=False)
    for i in range(3):  # 三条"一句带否定、一句不带"的对照组
        add_relation(st, f"000{i}", ["0000", "0001"], "0000", description="群一定是阿贝尔群", quote=f"a{i}", quote_verified=True, sync=False)
    add_relation(st, "0010", ["0000", "0001"], "0001", description="群一定不是阿贝尔群", quote="b0", quote_verified=True, sync=False)
    sync_counters(st)
    res = AgentC(st).contradictions()

    assert res["checked"] is True and res["scanned"] == 4
    assert len(res["contradictions"]) == 3, "一条带否定的关系应当与三条不带否定的各组成一对"
    capped = AgentC(st).contradictions(limit=1)
    assert len(capped["contradictions"]) == 1 and capped["truncated"] is True
    assert "不能据此说" in capped["reason"]


# ============================================================ (4) structural_duplicates


def test_structural_duplicates_proposes_merge_when_the_name_agrees(tmp_path):
    """正向：邻域相同 + 规范化名字相同 ⇒ 出现，且 proposal=="merge"。"""
    st = _dup_store(tmp_path / "ws", same_name=True)
    res = AgentC(st).structural_duplicates()

    assert res["checked"] is True
    assert res["scanned_concepts"] == 4
    hits = [x for x in res["candidates"] if frozenset(x["concept_ids"]) == frozenset({"0000", "0001"})]
    assert hits, "邻域相同 + 同名 的两个概念没有被提出（I5 的整条链路就断了）"
    hit = hits[0]
    assert hit["proposal"] == "merge"
    assert hit["name_evidence"] == "same_normalized_name"
    assert hit["neighborhood_size"] == 2
    assert sorted(hit["neighbors"]) == ["0002", "0003"]
    # 两者之间没有直接关系 ⇒ 没有任何一条关系同时涉及它们（`shared_relation_ids` 必为空）
    assert hit["shared_relation_ids"] == []
    assert res["truncation_notice"] is None and res["truncated"] is False


def test_structural_duplicates_negative_control_different_names_only_review(tmp_path):
    """负控（重要）：邻域相同但名字显然不同 ⇒ 出现但 proposal=="review"，理由含"不得据此合并"。"""
    st = _dup_store(tmp_path / "ws", same_name=True)
    res = AgentC(st).structural_duplicates()

    others = [x for x in res["candidates"] if frozenset(x["concept_ids"]) == frozenset({"0002", "0003"})]
    assert others, "桥甲/桥乙 的邻域也相同，应当被提出（提出≠合并）"
    hit = others[0]
    assert hit["name_evidence"] == "none"
    assert hit["proposal"] == "review", "只有结构证据就给 merge 建议，等于逼 B 去否决自己"
    assert "不得据此合并" in hit["reason"]
    assert "结构等价 ≠ 同义" in hit["reason"]


def test_structural_duplicates_negative_control_isolated_concepts_are_not_candidates(tmp_path):
    """负控：两个孤立概念（邻域都是空集）不得成为候选（否则是 O(n²) 纯噪声）。"""
    st = _dup_store(tmp_path / "ws", same_name=True)
    add_concept(st, "0004", "孤儿甲", definition="d", sync=False)
    add_concept(st, "0005", "孤儿乙", definition="d", sync=False)
    # 给它们相同的规范化名字，把"名字证据"这条路也堵死 —— 连名字一样都不该合并孤立节点
    # （概念行的读/写都走并表过渡层：`tx.rows("concepts")` 在新 schema 下是受控错，
    # "改一条概念行"这件事由 `upsert_legacy_shaped` 一处落盘 —— 老表还在时两处同号。）
    with st.tx(*CR.tables_for_concept_write(), actor="test") as tx:
        live = {c["concept_id"]: c for c in CR.view_tx(tx, shape="legacy")["rows"]}
        for cid in ("0004", "0005"):
            row = live[cid]
            row["name"] = "孤儿"
            row["normalized_name"] = "孤儿"
            CR.upsert_legacy_shaped(tx, row, note="test:same_orphan_name")
    sync_counters(st)
    res = AgentC(st).structural_duplicates()

    assert res["checked"] is True
    keys = _pair_keys(res["candidates"])
    assert frozenset({"0004", "0005"}) not in keys
    assert not any("0004" in k or "0005" in k for k in keys), "孤立概念不该参与结构重复枚举"


def test_structural_duplicates_negative_control_directly_related_pair_is_not_a_candidate(tmp_path):
    """负控：彼此已有直接关系的两个概念不得成为候选（它们已被声明为两个东西）。"""
    st = _dup_store(tmp_path / "ws", same_name=True, direct=True)
    res = AgentC(st).structural_duplicates()

    keys = _pair_keys(res["candidates"])
    assert frozenset({"0000", "0001"}) not in keys, "已有一条 a-b 关系，说明它们不是同一个节点"


def test_structural_duplicates_keeps_the_truncation_notice_out_of_candidates(tmp_path):
    """截断通知必须单列：混进 candidates 会被下游当成一对（代号为空的）概念。"""
    st = _dup_store(tmp_path / "ws", same_name=True)
    res = AgentC(st).structural_duplicates(limit=1)

    assert res["truncated"] is True
    assert len(res["candidates"]) == 1
    assert all(not x.get("is_truncation_notice") for x in res["candidates"])
    # 本夹具只有 2 对候选，limit=1 时是我们的 limit 生效（interactions 的枚举上限没被触及）
    assert res["truncation_notice"] is None
    assert "不能说'只有这些结构重复'" in res["reason"]

    tiny = AgentC(st, config={"structural_duplicate_max_pairs": 1}).structural_duplicates()
    assert tiny["truncation_notice"] is not None, "触及 interactions 的枚举上限时必须单列通知"
    assert tiny["truncation_notice"]["is_truncation_notice"] is True
    assert tiny["truncation_notice"]["concept_ids"] == []
    assert all(not x.get("is_truncation_notice") for x in tiny["candidates"])


# ============================================================ (5) 只读纪律


def test_the_four_service_methods_do_not_touch_a_single_byte(demo):
    """只读性：调用四个服务方法前后，三张知识表必须逐字节不变。

    这是 C 的硬规则（DESIGN §2）：一旦 C 能写，它就成为绕过 B 引文逐字回验的写入路径，
    而那是全系统唯一能自动发现幻觉引文的地方。
    """
    c = AgentC(demo)
    before = read_data_bytes(demo)
    c.neighbors("0000", depth=2)
    c.neighbors("9999")
    c.relations_between("0000", "0001")
    c.relations_between("0000", "0009")
    c.contradictions()
    c.contradictions(relation_ids=["0000", "0007"])
    c.structural_duplicates()
    check_conflict({"concept_ids": ["0000", "0001"], "statement": "群不是阿贝尔群"}, existing_relations=[])
    after = read_data_bytes(demo)

    # 概念行并表之后住 statements（kind="concept"）⇒ 只读性必须打在 statements.json 上。
    # 老写法列的是 concepts.json：那个文件在新 schema 下不存在，`read_data_bytes`
    # 对它前后都给同一个占位 ⇒ "概念表没被碰过"这条判据会退化成恒真。
    for name in ("statements.json", "relations.json", "literature.json"):
        assert before[name] == after[name], f"{name} 被服务调用改动了（C 必须只读）"
    # 顺带：连事件日志都不该多一行（事件是写入的证据）
    assert before["events.jsonl"] == after["events.jsonl"]


def test_tool_registry_exposes_only_read_side_effects(demo):
    """工具面只读：注册表里没有任何 side_effect != "read" 的工具。

    工具不只声明能力，它就是权限面（tools/base.py 的注释）：一个声明"只读"
    却可能写盘的工具，会让整张权限表变成空话。
    """
    reg = ToolRegistry(name="c-service")
    # 绑定角色（`P-14`）：这张表代表只读的 C（下面的用例要真的调 `graph.*`）。
    reg.bound_role = "C"
    register_graph_tools(reg, store=demo)
    added = AgentC(demo).register_tools(reg)

    assert all(reg.get(n).side_effect == "read" for n in reg.names())
    assert all(reg.get(n).needs_approval is False for n in reg.names())
    assert "graph.contradictions" in added and "graph.structural_duplicates" in added
    assert "graph.check_conflict" in added

    got = reg.call("graph.contradictions", relation_ids=["0000", "0007"])
    assert got.ok and got.data["method"] == "literal" and "checked" in got.data
    sd = reg.call("graph.structural_duplicates")
    assert sd.ok and "truncation_notice" in sd.data and "candidates" in sd.data
    # 省略 existing_relations ⇒ "没能力检查" ⇒ checked=False（不是"不冲突"）
    cc = reg.call("graph.check_conflict", draft_relation={"concept_ids": ["0000", "0001"], "statement": "群不是阿贝尔群"})
    assert cc.ok and cc.data["checked"] is False and cc.data["conflict"] is None
    cc2 = reg.call(
        "graph.check_conflict",
        draft_relation={"concept_ids": ["0000", "0001"], "statement": "群不是阿贝尔群"},
        existing_relations=[{"relation_id": "0000", "concept_ids": ["0000", "0001"], "statement": "群是阿贝尔群"}],
    )
    assert cc2.ok and cc2.data["checked"] is True and cc2.data["conflict"] is True
    assert cc2.data["conflicts_with"] == ["0000"]


def test_check_conflict_reexport_is_the_frozen_interactions_implementation():
    """`agent_c.check_conflict` 必须就是 `interactions.check_conflict`，且签名里没有 store。"""
    import inspect

    from agentflow import interactions

    assert check_conflict is interactions.check_conflict
    assert "store" not in inspect.signature(check_conflict).parameters
    assert "tx" not in inspect.signature(check_conflict).parameters


# ============================================================ (6) I3 缺口直连 A


def test_i3_default_is_off_and_writes_nothing(kn):
    """负控 1：默认 submit_requests=False ⇒ `search_requests.json` 逐字节不变。"""
    c = AgentC(kn)
    before = read_data_bytes(kn)
    rep = c.gaps(submit_requests=False)
    after = read_data_bytes(kn)

    assert rep.payload["candidate_gaps"], "夹具本身要能产出候选，否则这条负控是空过的"
    assert before["search_requests.json"] == after["search_requests.json"]
    assert kn.rows("search_requests") == []
    assert rep.payload["submitted_request_ids"] == []
    assert rep.payload["request_submission"]["enabled"] is False
    assert "默认" in rep.payload["request_submission"]["reason"]
    # 三态：关闭 ≠ 缺字段（D 的读取端不必区分两种形状）
    for key in ("submitted_request_ids", "rejected_requests", "skipped_duplicate_topics"):
        assert key in rep.payload


def test_i3_submits_at_most_three_well_formed_requests(kn):
    """正向：新增 ≤3 条，每条 submitted_by/priority/mode 合规，且 topic 能对应到某个候选。"""
    c = AgentC(kn)
    rep = c.gaps(submit_requests=True)

    rows = kn.rows("search_requests")
    assert 0 < len(rows) <= 3, "单次 gaps 最多直连 3 条（无闸门会把 A 的队列淹没）"
    assert len(rows) == len(rep.payload["submitted_request_ids"]) == 3
    cand_topics = {"、".join(x["concept_names"]) for x in rep.payload["candidate_gaps"]}
    for row in rows:
        assert row["submitted_by"] == SUBMITTER == "agent-C"
        assert row["priority"] == "medium", "agent-C 的默认优先级是 medium（I7 的表）"
        assert row["mode"] == "topical"
        assert row["done"] is False and row["for_question_id"] is None
        assert row["topic"] in cand_topics, f"topic={row['topic']!r} 对不上任何候选"
        assert row["content_description"], "content_description 必须带候选的理由（否则 A 不知道在查什么）"
    # 按净分降序：净分最高的那条一定在里面
    best = sorted(rep.payload["candidate_gaps"], key=lambda x: (-x["net_score"], x["key"]))[0]
    assert "、".join(best["concept_names"]) in {r["topic"] for r in rows}
    # 超上限的候选被显式拒绝而不是静默丢弃
    assert rep.payload["rejected_requests"]
    assert all(r["reason"] for r in rep.payload["rejected_requests"])
    assert any("每轮上限" in r["reason"] for r in rep.payload["rejected_requests"])


def test_i3_negative_control_inflight_limit_rejects_instead_of_queueing(kn):
    """负控 2：在途请求已到上限 ⇒ 一条都不新增，且 rejected_requests 里留下理由。"""
    for i in range(20):  # max_inflight_requests 的默认值
        add_request(kn, f"r-{i + 1:04d}", topic=f"占位主题{i}", done=False)
    c = AgentC(kn)
    before = read_data_bytes(kn)
    rep = c.gaps(submit_requests=True)
    after = read_data_bytes(kn)

    assert rep.payload["candidate_gaps"], "夹具要能产出候选"
    assert before["search_requests.json"] == after["search_requests.json"], "超限时不许新增"
    assert rep.payload["submitted_request_ids"] == []
    rejected = rep.payload["rejected_requests"]
    assert rejected, "被拒绝也要留下记录（静默丢弃会让编排层以为'没有缺口'）"
    assert all(r.get("reason") for r in rejected)
    assert len(rejected) == len(rep.payload["candidate_gaps"])
    assert "在途检索请求已达上限" in rejected[0]["reason"]


def test_i3_negative_control_duplicate_topic_is_skipped(kn):
    """负控 3：已存在同主题的未完成请求 ⇒ 跳过并记进 skipped_duplicate_topics。

    刻意用空格代替顿号写主题：去重走的是规范化比对（`textutil.normalize`），
    不是字符串相等 —— 否则"概念0、概念1"与"概念0 概念1"会被当成两个主题。
    """
    add_request(kn, "r-0001", topic="概念0 概念3", done=False)
    c = AgentC(kn)
    rep = c.gaps(submit_requests=True)

    skipped = rep.payload["skipped_duplicate_topics"]
    assert [x["topic"] for x in skipped] == ["概念0、概念3"]
    assert "未完成" in skipped[0]["reason"]
    topics = [r["topic"] for r in kn.rows("search_requests")]
    assert "概念0、概念3" not in topics, "没有为重复主题新建请求（那条在途请求的行保持原样）"
    assert len(rep.payload["submitted_request_ids"]) == 3, "被跳过的那条由后面的候选顶上（不是白白浪费一个名额）"
    assert len(kn.rows("search_requests")) == 4


def test_i3_skips_topics_already_in_flight_on_a_second_run(kn):
    """跨轮次也不重复排：第二次调用时前三名的主题都已在途 ⇒ 只剩第 4 名可提交。"""
    c = AgentC(kn)
    first = c.gaps(submit_requests=True).payload
    assert len(first["submitted_request_ids"]) == 3
    second = c.gaps(submit_requests=True).payload

    assert second["submitted_request_ids"] == [f"r-{S.format_id(4)}"]
    assert len(second["skipped_duplicate_topics"]) == 3
    first_run_topics = {
        r["topic"] for r in kn.rows("search_requests") if r["request_id"] in (f"r-{S.format_id(1)}", f"r-{S.format_id(2)}", f"r-{S.format_id(3)}")
    }
    assert {x["topic"] for x in second["skipped_duplicate_topics"]} == first_run_topics
    assert len(kn.rows("search_requests")) == 4


def test_i3_payload_reports_the_structural_duplicate_summary(demo):
    """I5 检测侧：gaps 的 payload 里带结构重复摘要（纯读，且指向真能调到的那条路）。

    CS-12（批 R22）：这一格从前叫 `detail_tool` 且取值是 `graph.structural_duplicates…`
    —— 而 `graph.*` 那 9 件只在 C 的 CLI 自检面注册，编排路径上调它只会拿到
    `unknown_action`。现在改成 `detail_reading`，指向本动作自己的 `limit`。
    """
    rep = AgentC(demo).gaps()
    summary = rep.payload["structural_duplicates"]

    assert summary["checked"] is True
    assert summary["candidate_count"] == summary["merge_proposals"] + summary["review_proposals"]
    assert "limit" in summary["detail_reading"], summary["detail_reading"]
    assert "不要在编排路径上调 `graph.*`" in summary["detail_reading"], (
        "这一格的取值必须先给真能调到的路（调大 limit 再调一次本动作），"
        "再明确否掉那 9 件取不到的 `graph.*`：只说'不要用'而不给替代，模型会照旧去试")
    assert "结构等价 ≠ 同义" in summary["method_note"]
    assert isinstance(json.loads(json.dumps(summary)), dict), "摘要必须可 JSON 序列化（要落进报告表）"


def test_i3_requests_are_valid_schema_rows(kn):
    """落进 search_requests 的每一行都必须能通过 schema 校验（否则 A 读到就炸）。"""
    AgentC(kn).gaps(submit_requests=True)
    rows = kn.rows("search_requests")
    assert rows
    for row in rows:
        assert row["request_id"].startswith("r-")
        assert S.is_valid_id(row["request_id"][2:]), "search_requests 用 r-NNNN 形态（不占用 4 位 ID 空间）"
        S.SearchRequest(**{k: v for k, v in row.items() if k in S.SearchRequest.__dataclass_fields__}).validate()
    # 业主 2026-10-12 裁定 CS-10 ②「直接调分析器也落库」：`gaps` 自己登记一条
    # （改前这条断言是 `== []`，钉的是"要落盘必须显式 persist"—— 那条口径已被裁定改掉）。
    reports = kn.rows("analysis_reports")
    assert [r["kind"] for r in reports] == ["gaps"], (
        f"直接调 `gaps` 就该自己登记一条 `analysis_reports`（CS-10 ②）；实到 {reports}")
