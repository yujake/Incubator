"""图查询（`tools/graph_tools.py`）与代号溯源（`tools/trace_tools.py`）的性质测试。

这层是 C/D 的取证基础，最要紧的三条性质：
1. 空库不能崩：分析工具必须能在"还没有任何关系"时给出结构化结论；
2. `relations_between` 给全部：一对概念之间可能同时存在多条关系，
   "最合理的链"往往不是搜索时随手选中的那条；
3. `trace.*` 只陈述事实：缺文件就说缺文件（`status=file_missing`），
   绝不返回空串假装读到了；`quote_verified` 的三态要原样透出。
"""

from __future__ import annotations

import json

import pytest

from agentflow.tools import graph_tools, trace_tools
from agentflow.tools.base import ToolRegistry

from demo_dataset_helper import build_demo

# ============================================================ 夹具


@pytest.fixture
def empty_graph_tools(store):
    """空库上的低层图工具。"""
    reg = ToolRegistry(name="graph")
    graph_tools.register(reg, store=store)
    return reg


@pytest.fixture
def trace_reg(clean_store):
    """在自洽最小数据集上注册的溯源工具。"""
    reg = ToolRegistry(name="trace")
    graph_tools.register(reg, store=clean_store)
    trace_tools.register(reg, store=clean_store)
    return reg


# ============================================================ graph.*


def test_graph_build_and_stats_on_empty_store_do_not_crash(empty_graph_tools):
    """空库上 graph.build / graph.stats 必须给出零规模摘要而不是抛异常。"""
    build = empty_graph_tools.call("graph.build")
    assert build.ok, build.error
    assert build.data["concept_count"] == 0
    assert build.data["relation_count"] == 0
    assert build.data["isolated_concepts"] == []

    stats = empty_graph_tools.call("graph.stats", top_n=5)
    assert stats.ok, stats.error
    assert stats.data["hot"] == []

    rb = empty_graph_tools.call("graph.relations_between", a="0000", b="0001")
    assert rb.ok and rb.data["count"] == 0


def test_graph_relations_between_returns_every_relation(clean_store):
    """relations_between(a,b) 必须返回全部同时含 a、b 的关系（不同文献/不同表述都算）。"""
    from conftest import add_relation, sync_counters

    add_relation(clean_store, "0001", ["0000", "0001"], "0000", quote="second quote", quote_verified=None, sync=False)
    add_relation(clean_store, "0002", ["0000", "0001"], "0000", quote="third quote", quote_verified=False, status="suspect", sync=False)
    sync_counters(clean_store)

    reg = ToolRegistry(name="graph")
    graph_tools.register(reg, store=clean_store)
    res = reg.call("graph.relations_between", a="0000", b="0001")
    assert res.ok, res.error
    assert res.data["count"] == 3
    assert {r["relation_id"] for r in res.data["relations"]} == {"0000", "0001", "0002"}
    for rel in res.data["relations"]:
        assert set(rel["concept_ids"]) == {"0000", "0001"}
    # 确定性排序：quote_verified=True 排最前（§3.3(4)）
    assert res.data["relations"][0]["quote_verified"] is True
    assert res.data["a_name"] == "group" and res.data["b_name"] == "abelian group"


def test_graph_neighbors_and_stats_agree_with_the_relation_table(clean_store):
    """邻居与度数必须与关系表逐条对得上（图是索引，不是另一份事实）。"""
    reg = ToolRegistry(name="graph")
    graph_tools.register(reg, store=clean_store)
    nb = reg.call("graph.neighbors", concept_id="0000")
    assert nb.ok and nb.data["degree"] == 1
    assert [n["concept_id"] for n in nb.data["neighbors"]] == ["0001"]
    assert nb.data["neighbors"][0]["relation_ids"] == ["0000"]


# ============================================================ trace.relation（L1）


def test_trace_relation_returns_citation_and_translates_concept_ids(trace_reg):
    """L1 必须给回引文/陈述/页码/状态，并把概念代号翻译成概念名。"""
    res = trace_reg.call("trace.relation", relation_id="0000")
    assert res.ok, res.error
    d = res.data
    assert d["level"] == "L1"
    assert d["concept_ids"] == ["0000", "0001"]
    assert d["concept_names"] == ["group", "abelian group"]
    assert d["quote"] == "An abelian group is a group in which the commutative law holds."
    assert d["statement"]
    assert d["page_range"]["label"] == "pp. 1-1"
    assert d["status"] == "active"
    assert d["lit_id"] == "0000"
    assert d["literature"]["title"] == "Commutativity in abelian groups"
    assert d["contains_fulltext"] is False


def test_trace_relation_keeps_quote_verified_trinary(trace_reg, clean_store):
    """quote_verified 是三态：True / False / None 必须原样透出，绝不压成布尔。"""
    from conftest import add_relation

    add_relation(clean_store, "0001", ["0000", "0001"], "0000", quote="找不到的引文", quote_verified=False)
    add_relation(clean_store, "0002", ["0000", "0001"], "0000", quote="", quote_verified=None)

    labels = {}
    for rid in ("0000", "0001", "0002"):
        res = trace_reg.call("trace.relation", relation_id=rid)
        assert res.ok, res.error
        labels[rid] = (res.data["quote_verified"], res.data["quote_verified_label"])
    assert labels["0000"][0] is True and "已校验" in labels["0000"][1]
    assert labels["0001"][0] is False and "校验失败" in labels["0001"][1]
    assert labels["0002"][0] is None, "None 表示「无法校验」，不能被写成 False"
    assert "无法校验" in labels["0002"][1] and "不是" in labels["0002"][1]


def test_trace_relation_unknown_id_fails_with_candidates(trace_reg):
    """代号不存在时如实失败并给出已知代号提示（D 可以据此改参数）。"""
    res = trace_reg.call("trace.relation", relation_id="9999")
    assert res.ok is False
    assert "9999" in res.error
    assert res.meta.get("known_relations") == ["0000"]


# ============================================================ trace.concept（L2）


def test_trace_concept_gives_statements_only_not_fulltext(trace_reg, clean_store):
    """L2 只给表述与代号，绝不下钻文献正文（正文是 L3 的贵操作）。"""
    from conftest import add_literature, write_library_file

    marker = "UNIQUE-FULLTEXT-MARKER-9f3a"
    write_library_file(clean_store, "0000/other.txt", marker)
    add_literature(clean_store, "0001", title="另一篇", path="0000/other.txt", processed=True)

    res = trace_reg.call("trace.concept", concept_id="0000")
    assert res.ok, res.error
    d = res.data
    assert d["level"] == "L2"
    assert d["contains_fulltext"] is False
    assert d["concept"]["name"] == "group"
    assert d["counts"]["relation_count"] == 1
    assert [r["relation_id"] for r in d["relations"]] == ["0000"]
    assert d["relations"][0]["description"]
    assert marker not in json.dumps(d, ensure_ascii=False), "L2 竟然把正文带出来了"


def test_trace_concept_with_relations_false_returns_no_statements(trace_reg):
    """with_relations=False 时只给定义与计数（D 想省 token 时可以关掉）。"""
    res = trace_reg.call("trace.concept", concept_id="0001", with_relations=False)
    assert res.ok and res.data["relations"] == []
    assert res.data["relation_count"] == 1


# ============================================================ trace.literature（L3）


def test_trace_literature_reports_missing_file_truthfully(trace_reg, clean_store):
    """文件缺失要如实报 status=file_missing，不能返回空串假装读到了。"""
    from conftest import add_literature

    add_literature(clean_store, "0001", title="丢了", path="0001/gone.txt", processed=False)
    res = trace_reg.call("trace.literature", lit_id="0001")
    assert res.ok, res.error
    d = res.data
    assert d["status"] == "file_missing"
    assert d["status"] in trace_tools.L3_STATUSES
    assert d["file_exists"] is False
    assert d["has_text_layer"] is False
    assert d["text"] == ""
    assert d["note"], "必须解释「为什么读不到」"


def test_trace_literature_without_path_is_not_the_same_as_missing(trace_reg, clean_store):
    """`path` 为空（没下载）与"文件丢了"是两件事，状态必须不同。"""
    from conftest import add_literature

    add_literature(clean_store, "0001", title="没下载", path=None, processed=False)
    d = trace_reg.call("trace.literature", lit_id="0001").data
    assert d["status"] == "no_path"
    assert d["file_exists"] is False
    assert "未下载" in d["note"]


def test_trace_literature_reads_real_text_when_present(trace_reg):
    """有文件且是文本时，L3 才真的给正文片段（标出可定位的页与来源类型）。"""
    d = trace_reg.call("trace.literature", lit_id="0000").data
    assert d["status"] == "ok"
    assert d["file_exists"] is True and d["has_text_layer"] is True
    assert "commutative law" in d["text"]


# ============================================================ trace.chain


def test_trace_chain_returns_every_step(tmp_path):
    """trace.chain 必须真的返回每一步（D 曾误报"L1/L2 均为空"，而工具其实是好的）。"""
    from agentflow.agent_c import AgentC
    from agentflow.store import Store

    dest = build_demo(tmp_path / "demo")
    st = Store(dest)
    reg = ToolRegistry(name="trace")
    graph_tools.register(reg, store=st)
    trace_tools.register(reg, store=st)

    paths = AgentC(st).paths("0000", "0002", max_paths=8).payload["paths"]
    chain = [str(x) for x in max(paths, key=lambda p: p["hops"])["relation_chain"]]
    assert len(chain) >= 2, "演示数据集里应当能找到多跳链条"

    res = reg.call("trace.chain", relation_ids=chain)
    assert res.ok, res.error
    d = res.data
    assert d["level"] == "chain"
    assert d["step_count"] == len(chain)
    assert len(d["steps"]) == len(chain), "链条有断裂：steps 少了一步"
    assert d["missing"] == []
    assert [s["relation_id"] for s in d["steps"]] == chain
    for step in d["steps"]:
        assert step["description"] or step["quote"], "每一步都必须有表述"
        assert step["concept_names"], "每一步都必须翻译出概念名"
        assert step["quote_verified_label"]
    for rid in chain:
        assert rid in d["chain_text"], f"{rid} 没有出现在 chain_text 里"


def test_trace_chain_lists_missing_ids_instead_of_silently_dropping(trace_reg):
    """链条里混入不存在的代号时，missing 要如实列出，且已存在的步骤照常返回。"""
    d = trace_reg.call("trace.chain", relation_ids=["0000", "9999"]).data
    assert d["step_count"] == 1
    assert d["missing"] == ["9999"]
    assert "9999" in d["chain_text"]
    assert [s["relation_id"] for s in d["steps"]] == ["0000"]
