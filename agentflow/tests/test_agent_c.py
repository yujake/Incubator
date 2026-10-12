"""智能体 C（`agent_c.py`）的性质测试 —— 本轮的重点。

C 的定位是"程序做分析，LLM 只做排序与措辞"，所以这里全部走确定性路径
（`AgentC(..., llm=None)`），并逐条钉住设计基线 §3 里那些"做错了也不报错"的地方：

- `hottest` 的计数口径与稳定排序（同分按 concept_id 升序，跑两次逐字节一致）；
- `paths` 的低重合度筛选（Jaccard 严格大于才丢，丢弃理由带 Jaccard 值）、
  关系代号链可回查、逐项 `score_breakdown`、正文只含 high（段落级断言）、
  一条 high 都没有时必须明说"没有找到高信息量路径"；
- `cold` 把 degree=0 的孤立概念单独归类，并单列"冷门但连接强"；
- `gaps` 的二元结论：否决项直接剔除、被剔除的逐条留理由，
  全部候选都被否决时 `verdict=="无"` 且 `candidate_gaps==[]`（不许把"没找到"包装成"找到了"）；
- `handle` 的关键词分派与"解析不到就如实失败并列出候选"。
"""

from __future__ import annotations

import json

import pytest

from agentflow import schema as S
from agentflow.agent_c import LEVELS, AgentC, AnalysisReport
from agentflow.store import Store

from conftest import add_concept, add_relation, sync_counters
from demo_dataset_helper import build_demo

_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}
_LONG_DESC = "这是一条足够长的关系描述，用来说明信息量不低"
_SHORT_DESC = "短描述"


# ============================================================ 数据集构造


def _concepts(st: Store, *ids: str) -> None:
    for cid in ids:
        add_concept(st, cid, f"概念{cid}", definition=f"{cid} 的定义", sync=False)


def _store_with_three_level_paths(root) -> Store:
    """构造一张图：0000→0009 之间有三条两跳路径，分别是 high / medium / low。"""
    st = Store(root)
    st.init()
    _concepts(st, "0000", "0001", "0002", "0003", "0009")
    # P1（high）：两跳引文都通过校验、两篇不同文献、描述够长
    add_relation(st, "0000", ["0000", "0001"], "0000", description=_LONG_DESC, quote="q0", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0001", "0009"], "0001", description=_LONG_DESC, quote="q1", quote_verified=True, sync=False)
    # P2（medium）：一跳校验失败
    add_relation(st, "0002", ["0000", "0002"], "0002", description=_LONG_DESC, quote="q2", quote_verified=False, sync=False)
    add_relation(st, "0003", ["0002", "0009"], "0003", description=_LONG_DESC, quote="q3", quote_verified=True, sync=False)
    # P3（low）：两跳都"无法校验"、描述过短、且两条来自同一篇文献
    add_relation(st, "0004", ["0000", "0003"], "0004", description=_SHORT_DESC, quote="q4", quote_verified=None, sync=False)
    add_relation(st, "0005", ["0003", "0009"], "0004", description=_SHORT_DESC, quote="q5", quote_verified=None, sync=False)
    sync_counters(st)
    return st


@pytest.fixture
def three_levels(tmp_path) -> Store:
    return _store_with_three_level_paths(tmp_path / "levels")


@pytest.fixture
def demo(tmp_path) -> Store:
    return Store(build_demo(tmp_path / "demo"))


# ============================================================ (1) hottest


def test_hottest_counts_every_concept_slot_in_a_relation(tmp_path):
    """计数口径：一条关系里每个概念各计 1 次出现（3 概念的关系贡献 3 次），并把代号翻译成名字。"""
    st = Store(tmp_path / "ws")
    st.init()
    _concepts(st, "0000", "0001", "0002", "0003", "0004")
    add_relation(st, "0000", ["0000", "0001", "0002"], "0000", description=_LONG_DESC, quote="q0", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0003", "0004"], "0001", description=_LONG_DESC, quote="q1", quote_verified=True, sync=False)
    add_relation(st, "0002", ["0000", "0003"], "0002", description=_LONG_DESC, quote="q2", quote_verified=True, sync=False)
    sync_counters(st)

    rep = AgentC(st).hottest(top_n=5)
    assert rep.kind == "hottest" and rep.ok
    entries = {e["concept_id"]: e for e in rep.payload["entries"]}
    assert entries["0000"]["occurrences"] == 2 and entries["0000"]["relation_count"] == 2
    assert entries["0001"]["occurrences"] == 1, "3 概念关系里的概念也应当各被计 1 次"
    assert entries["0002"]["occurrences"] == 1
    # 3 概念关系贡献 3 次出现：所有概念的 occurrence 之和 == 所有关系的概念槽位总数
    total_slots = sum(len(r["concept_ids"]) for r in st.rows("relations"))
    assert sum(e["occurrences"] for e in rep.payload["entries"]) == total_slots == 7
    assert "3 个概念" in rep.payload["occurrence_basis"]
    # 代号必须翻译成名字；代表关系要给出，便于人工核对热度是否名副其实
    assert all(e["name"] == f"概念{e['concept_id']}" for e in rep.payload["entries"])
    assert all(e["representative_relations"] for e in rep.payload["entries"])
    assert len(entries["0000"]["representative_relations"]) <= 3


def test_hottest_sort_is_stable_and_byte_identical_across_runs(tmp_path):
    """排序必须稳定（同分按 concept_id 升序）：同一份数据连跑两次结果逐字节一致。"""
    st = Store(tmp_path / "ws")
    st.init()
    _concepts(st, "0000", "0001", "0002", "0003", "0004")
    add_relation(st, "0000", ["0000", "0001"], "0000", description=_LONG_DESC, quote="q0", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0002", "0003"], "0001", description=_LONG_DESC, quote="q1", quote_verified=True, sync=False)
    sync_counters(st)

    first = AgentC(st).hottest(top_n=5)
    second = AgentC(st).hottest(top_n=5)
    assert first.payload["hot_ids"] == second.payload["hot_ids"]
    assert first.markdown == second.markdown, "两次运行的报告必须逐字节一致"
    assert json.dumps(first.payload, ensure_ascii=False) == json.dumps(second.payload, ensure_ascii=False)

    ranked = [(e["concept_id"], e["occurrences"]) for e in first.payload["entries"]]
    for i in range(len(ranked) - 1):
        cur, nxt = ranked[i], ranked[i + 1]
        assert cur[1] >= nxt[1], "必须按出现次数降序"
        if cur[1] == nxt[1]:
            assert cur[0] < nxt[0], "同分必须按 concept_id 升序"


def test_hottest_on_empty_relation_table_says_data_is_missing(tmp_path):
    """关系表为空要说"数据还没进来"，而不是"没有热门概念"。"""
    st = Store(tmp_path / "ws")
    st.init()
    _concepts(st, "0000")
    rep = AgentC(st).hottest(top_n=5)
    assert rep.payload["entries"] == []
    assert "关系表为空" in rep.summary
    assert rep.warnings == ["关系表为空"]


# ============================================================ (2) paths：低重合度筛选


def test_paths_drops_high_overlap_path_with_jaccard_reason(tmp_path):
    """只差一个中间节点的两条路径实质上是一条：重合度高者必须被丢弃，且理由里带 Jaccard 值。"""
    st = Store(tmp_path / "ws")
    st.init()
    _concepts(st, "0000", "0001", "0002", "0005")
    add_relation(st, "0000", ["0000", "0001"], "0000", description=_LONG_DESC, quote="a", quote_verified=True, sync=False)
    add_relation(st, "0001", ["0001", "0005"], "0000", description=_LONG_DESC, quote="b", quote_verified=True, sync=False)
    add_relation(st, "0002", ["0000", "0002"], "0000", description=_LONG_DESC, quote="c", quote_verified=True, sync=False)
    add_relation(st, "0003", ["0001", "0002"], "0000", description=_LONG_DESC, quote="d", quote_verified=True, sync=False)
    sync_counters(st)

    rep = AgentC(st).paths("0000", "0005", max_paths=10)
    assert rep.payload["search"]["raw_path_count"] == 2
    dropped = rep.payload["dedup"]["dropped_by_overlap"]
    assert len(dropped) == 1, "只差一个中间节点的高重合路径必须被丢弃"
    assert dropped[0]["path"] == ["0000", "0002", "0001", "0005"]
    assert dropped[0]["max_jaccard"] == pytest.approx(0.75)
    assert "0.75" in dropped[0]["reason"] and "max_overlap" in dropped[0]["reason"]
    assert rep.payload["dedup"]["kept_after_overlap_filter"] == 1
    assert [p["concept_path"] for p in rep.payload["paths"]] == [["0000", "0001", "0005"]]


def test_paths_keeps_paths_whose_overlap_equals_the_threshold(tmp_path):
    """Jaccard 恰好等于 max_overlap 时必须保留（严格大于才丢）—— a-x-b 与 a-y-b 正是需求要的多路径。"""
    st = _store_with_three_level_paths(tmp_path / "ws")
    rep = AgentC(st).paths("0000", "0009", max_overlap=0.5)
    assert rep.payload["dedup"]["dropped_by_overlap"] == []
    assert rep.payload["dedup"]["kept_after_overlap_filter"] == 3


# ============================================================ (2) paths：链条 / 评分 / 分流


def test_paths_relation_chain_is_resolvable_and_scored(demo):
    """每条路径都要给出可回查的关系代号链与可逐项打印的 score_breakdown。"""
    rel_ids = {r["relation_id"] for r in demo.rows("relations")}
    rep = AgentC(demo).paths("0000", "0002", max_paths=8)
    assert rep.ok and rep.payload["paths"], rep.summary
    for item in rep.payload["paths"]:
        chain = item["relation_chain"]
        assert chain, "关系代号链不能为空"
        assert len(chain) == item["hops"] == len(item["concept_path"]) - 1, "第 k 个关系必须对应第 k 跳"
        assert all(rid in rel_ids for rid in chain), f"链条里有查不到的关系代号：{chain}"
        sb = item["score_breakdown"]
        assert isinstance(sb, dict) and sb["terms"], "评分必须可逐项打印"
        assert len(sb["terms"]) >= 5
        for term in sb["terms"]:
            assert {"name", "detail", "weight", "contribution"} <= set(term)
        assert sb["total"] == pytest.approx(item["score"])
        assert sb["level"] == item["level"] in LEVELS
        assert len(item["hop_details"]) == item["hops"]


def test_paths_markdown_body_contains_only_high_level_paths(three_levels):
    """正文只含 high、附录只含 medium、low 只在统计段计数（段落级断言，不看紧凑字符串）。"""
    rep = AgentC(three_levels).paths("0000", "0009", max_paths=10)
    assert rep.payload["levels"] == {"high": 1, "medium": 1, "low": 1}

    sections = _sections(rep.markdown)
    body = sections["## 正文（仅高信息量路径）"]
    appendix = sections["## 附录（中等信息量路径，仅供参考，**未达正文标准、不作为证据**）"]
    stats = sections["## 统计（低信息量路径不展开，仅计数）"]

    assert [h for h in body if h.startswith("### ")] == ["### 路径 1（高信息量，score=4.00，2 跳）"]
    assert all("高信息量" in h for h in body if h.startswith("### "))
    assert all("中信息量" in h for h in appendix if h.startswith("### "))
    assert not [h for h in body + appendix + stats if h.startswith("### ") and "低信息量" in h], "low 不该被展开"
    assert any("低信息量路径：1 条" in line for line in stats)

    # 三条路径的概念链各自只出现在它该出现的段落里
    items = {it["level"]: it for it in rep.payload["paths"]}
    for level, section in (("high", body), ("medium", appendix)):
        line = _concept_chain_line(items[level])
        assert any(line in ln for ln in section), f"{level} 的概念链应当出现在对应段落里：{line}"
    low_line = _concept_chain_line(items["low"])
    assert not any(low_line in ln for ln in body), "low 路径被写进正文了"
    assert not any(low_line in ln for ln in appendix)


def test_paths_says_no_high_path_when_none_reaches_the_threshold(tmp_path):
    """一条 high 都没有时必须明说"没有找到高信息量路径"，不许把 medium/low 硬凑成 high。"""
    st = Store(tmp_path / "ws")
    st.init()
    _concepts(st, "0000", "0001", "0009")
    add_relation(st, "0000", ["0000", "0001"], "0000", description=_SHORT_DESC, quote="a", quote_verified=None, sync=False)
    add_relation(st, "0001", ["0001", "0009"], "0000", description=_SHORT_DESC, quote="b", quote_verified=None, sync=False)
    sync_counters(st)

    rep = AgentC(st).paths("0000", "0009")
    assert rep.payload["has_high"] is False
    assert rep.payload["levels"]["high"] == 0
    assert "没有找到高信息量路径" in rep.summary
    assert any("**没有找到高信息量路径。**" in line for line in _sections(rep.markdown)["## 正文（仅高信息量路径）"])
    assert "不把 medium 当作 high 上报" in rep.summary


def test_score_penalizes_unverified_quote_and_suspect_status(three_levels):
    """评分方向性：quote_verified=False 与 status=suspect 必须降低分数，且等级不升。"""
    agent = AgentC(three_levels)
    path = ["0000", "0001", "0009"]
    chain = ["0000", "0001"]
    base = [
        {"relation_id": "0000", "lit_id": "0000", "description": _LONG_DESC, "quote_verified": True, "status": "active"},
        {"relation_id": "0001", "lit_id": "0001", "description": _LONG_DESC, "quote_verified": True, "status": "active"},
    ]
    bad = [
        {**base[0], "quote_verified": False, "status": "suspect"},
        {**base[1], "quote_verified": False, "status": "suspect"},
    ]
    good_s = agent._score_chain(path, chain, base, hot_ids=[])
    bad_s = agent._score_chain(path, chain, bad, hot_ids=[])

    assert bad_s["score"] < good_s["score"], "引文校验失败 + suspect 竟然没有降分"
    assert _LEVEL_RANK[bad_s["level"]] <= _LEVEL_RANK[good_s["level"]]
    assert good_s["level"] == "high" and bad_s["level"] == "low"
    # 分数变化必须能逐项解释
    terms = {t["name"]: t["contribution"] for t in bad_s["score_breakdown"]["terms"]}
    assert terms["引文校验失败比例"] < 0
    assert terms["suspect 比例"] < 0
    assert bad_s["score_breakdown"]["inputs"]["quote_verified_false"] == 2
    assert bad_s["score_breakdown"]["inputs"]["suspect"] == 2

    # 端到端：未校验/suspect 的那条路径在报告里确实更弱
    rep = agent.paths("0000", "0009", max_paths=10)
    levels = {tuple(it["concept_path"]): it["level"] for it in rep.payload["paths"]}
    assert levels[("0000", "0001", "0009")] == "high"
    assert levels[("0000", "0002", "0009")] == "medium"


def test_paths_reports_budget_truncation_honestly(demo):
    """极小的 node_budget 必须如实回报 truncated=True + warning，不许假装搜完了。"""
    rep = AgentC(demo, config={"node_budget": 1}).paths("0000", "0002")
    assert rep.truncated is True
    assert rep.payload["search"]["truncated"] is True
    assert "node_budget" in rep.payload["search"]["truncation_reasons"]
    assert any("截断" in w for w in rep.warnings), "截断必须写进 warnings"
    assert rep.payload["search"]["budget_used"] <= 3

    full = AgentC(demo).paths("0000", "0002")
    assert full.truncated is False


def test_paths_unknown_concept_fails_with_candidates(demo):
    """起点/终点不存在时如实失败，并列出已知概念（调用方才能改参数）。"""
    rep = AgentC(demo).paths("0000", "9999")
    assert rep.ok is False
    assert "9999" in (rep.error or "")
    assert rep.payload["known_concepts"], "失败报告必须列出候选概念"


# ============================================================ (3) cold


def test_cold_separates_isolated_concepts_and_flags_undervalued(tmp_path):
    """degree=0 的"完全孤立"必须单独归类；"冷门但连接强"要单列；弱连接要给 weak_score + 理由。"""
    st = Store(tmp_path / "ws")
    st.init()
    _concepts(st, *[f"{i:04d}" for i in range(10)])
    for rid, cids in (
        ("0000", ["0000", "0001"]),
        ("0001", ["0000", "0002"]),
        ("0002", ["0000", "0003"]),
        ("0003", ["0000", "0004"]),
        ("0004", ["0001", "0002"]),
        ("0005", ["0000", "0005"]),
        ("0006", ["0005", "0006"]),
    ):
        add_relation(st, rid, cids, "0000", description=_LONG_DESC, quote=f"q{rid}", quote_verified=True, sync=False)
    # 0007：唯一连接 + 引文无法校验 + suspect → 弱连接
    add_relation(st, "0007", ["0000", "0007"], "0000", description=_LONG_DESC, quote="q7", quote_verified=None, status="suspect", sync=False)
    # 0008：两条独立的、引文已校验的连接（都指向同一个热门概念）→ 冷门但连接强
    add_relation(st, "0008", ["0000", "0008"], "0000", description=_LONG_DESC, quote="q8", quote_verified=True, sync=False)
    add_relation(st, "0009", ["0000", "0008"], "0001", description=_LONG_DESC, quote="q9", quote_verified=True, sync=False)
    sync_counters(st)
    # 0009 号概念刻意不与任何概念相连（完全孤立）

    rep = AgentC(st).cold(top_n=8)
    payload = rep.payload
    isolated_ids = [x["concept_id"] for x in payload["isolated"]]
    assert isolated_ids == ["0009"]
    assert "0009" not in payload["cold_ids"], "孤立概念不该混进冷门榜（没人连接 ≠ 没人研究）"
    assert all(e["degree"] >= 1 for e in payload["entries"])
    assert "完全孤立" in rep.summary and "单独归类" in rep.summary

    entries = {e["concept_id"]: e for e in payload["entries"]}
    # "冷门但连接强"必须是单独的一类，并指出是哪条连接
    assert "0008" in payload["undervalued_ids"]
    strong = [x for x in entries["0008"]["strong_connections_to_hot"] if x["weak_points"] == 0]
    assert strong, "0008 的两条连接都该被判定为强连接"
    assert entries["0008"]["undervalued"] is True
    assert "冷门但连接强" in rep.markdown

    # 弱连接必须给出 weak_score 与逐条理由字符串
    weak = entries["0007"]["weak_relations"]
    assert weak, "0007 的关系应当被判为弱连接"
    assert weak[0]["weak_score"] == pytest.approx(0.75)
    assert weak[0]["weak_points"] == 3
    assert len(weak[0]["weak_reasons"]) == 3
    assert all(isinstance(r, str) and r for r in weak[0]["weak_reasons"])
    assert any("唯一" in r for r in weak[0]["weak_reasons"])
    assert any("quote_verified=None" in r for r in weak[0]["weak_reasons"])
    assert weak[0]["has_rejected"] is False


# ============================================================ (4) gaps


def _gaps_store(root, *, quote_verified: bool = False, name_ok: bool = True, duplicate_of: str | None = None) -> Store:
    st = Store(root)
    st.init()
    names = [f"概念{i}" for i in range(5)]
    if not name_ok:
        names[0] = "这是一个被错误抽取成整句话的概念名称而且它很长没有任何空格"
    for i, nm in enumerate(names):
        add_concept(st, f"{i:04d}", nm, definition="d", sync=False)
    for rid, cids in (
        ("0000", ["0000", "0001"]),
        ("0001", ["0000", "0002"]),
        ("0002", ["0000", "0003"]),
        ("0003", ["0001", "0004"]),
        ("0004", ["0002", "0004"]),
    ):
        add_relation(
            st,
            rid,
            cids,
            "0000",
            description=_LONG_DESC,
            quote=f"q{rid}",
            quote_verified=quote_verified,
            duplicate_of=duplicate_of if rid == "0000" else None,
            sync=False,
        )
    sync_counters(st)
    return st


def test_gaps_verdict_is_no_when_every_candidate_is_vetoed(tmp_path):
    """所有候选都该被否决时：verdict 必须为「无」、candidate_gaps 必须为空，且逐条留否决理由。"""
    st = _gaps_store(tmp_path / "ws", quote_verified=False)
    rep = AgentC(st).gaps()
    payload = rep.payload

    assert payload["verdict"] == "无"
    assert payload["candidate_gaps"] == [], "把「没找到」包装成「找到了」是最不能接受的失败形态"
    assert payload["has_candidates"] is False
    assert payload["vetoed_candidates"], "被否决的候选必须逐条留下"
    for cand in payload["vetoed_candidates"]:
        assert cand["passed_veto"] is False
        assert cand["veto_reasons"], "被否决却没有理由"
        assert any("quote_verified=False" in r for r in cand["veto_reasons"])
    assert payload["conclusion"].startswith("证据不足")
    assert "否决项" in payload["conclusion"]
    assert "## 被否决项（veto）剔除的候选 —— 它们**不算**“有”" in rep.markdown


def test_gaps_rejects_candidates_whose_concept_name_is_not_a_concept(tmp_path):
    """否决项之一：概念名明显不是概念（过长且无空格）必须直接剔除并留下理由。"""
    st = _gaps_store(tmp_path / "ws", quote_verified=True, name_ok=False)
    payload = AgentC(st).gaps().payload

    reasons = [r for c in payload["vetoed_candidates"] for r in c["veto_reasons"]]
    assert any("概念名明显不是概念" in r for r in reasons), reasons
    assert any("过长" in r or "整句话" in r for r in reasons)
    # 被否决的候选一律不得出现在正式候选里
    vetoed_keys = {c["key"] for c in payload["vetoed_candidates"]}
    assert not (vetoed_keys & {c["key"] for c in payload["candidate_gaps"]})


def test_gaps_rejects_candidates_with_duplicate_of(tmp_path):
    """否决项之一：相关关系里有 duplicate_of 非空的条目（已判定为重复）必须直接剔除。"""
    st = _gaps_store(tmp_path / "ws", quote_verified=True, duplicate_of="0001")
    payload = AgentC(st).gaps().payload

    dup_vetoed = [
        c for c in payload["vetoed_candidates"] if any("duplicate_of" in r for r in c["veto_reasons"])
    ]
    assert dup_vetoed, "看到 duplicate_of 的候选没有被否决"
    assert all(c["passed_veto"] is False for c in dup_vetoed)
    # 被否决的候选一律不得出现在正式候选里
    assert {c["key"] for c in dup_vetoed} & {c["key"] for c in payload["candidate_gaps"]} == set()
    # 那条被判重的关系同时涉及 0000 与 0001，涉及它们的候选必须都被拦下
    assert any("0000" in c["key"] or "0001" in c["key"] for c in dup_vetoed)
    assert any("0000" in c["key"] or "0001" in c["key"] for c in dup_vetoed if c["kind"] == "rare_group")


def test_gaps_reports_yes_when_a_candidate_passes_the_veto_gate(tmp_path):
    """有可核实依据的候选必须真的被报出来（否则"二元结论"只剩「无」这一半）。"""
    st = _gaps_store(tmp_path / "ws", quote_verified=True)
    payload = AgentC(st).gaps().payload
    assert payload["verdict"] == "有"
    assert payload["candidate_gaps"], "有正向信号的候选被漏掉了"
    for cand in payload["candidate_gaps"]:
        assert cand["passed_veto"] is True
        assert cand["confidence"] in ("high", "medium")
        assert cand["reason"] and cand["related_relation_ids"]
    assert "确实有" in payload["conclusion"]


# ============================================================ handle 分派


def test_handle_dispatches_the_four_request_kinds(demo):
    """四类需求各分派一次：统计最热门 / 查询关系 / 研究冷门 / 完善关系图。"""
    agent = AgentC(demo)

    hot = agent.handle("统计最热门的 3 个概念")
    assert hot.kind == "hottest" and hot.ok and hot.params["top_n"] == 3

    paths = agent.handle("查询 群 与 域 之间的关系")
    assert paths.kind == "paths" and paths.ok, paths.summary
    assert paths.payload["a"]["concept_id"] == "0000" and paths.payload["b"]["concept_id"] == "0002"

    cold = agent.handle("研究冷门概念")
    assert cold.kind == "cold" and cold.ok

    gaps = agent.handle("完善关系图，找找结构洞")
    assert gaps.kind == "gaps" and gaps.ok


def test_handle_fails_and_lists_candidates_when_concepts_cannot_be_resolved(demo):
    """概念名解析不到时：ok=False、明说无法解析，并列出候选概念名。"""
    rep = AgentC(demo).handle("查询 张三 与 李四 之间的关系")
    assert rep.ok is False
    assert rep.kind == "paths"
    assert "无法解析" in (rep.error or "") or "无法解析" in rep.summary
    candidates = rep.payload["candidate_concepts"]
    assert candidates, "失败报告必须列出候选概念"
    names = {c["name"] for c in candidates}
    assert {"群", "域"} <= names
    assert "群" in rep.summary, "候选概念名必须出现在人读的摘要里"


def test_handle_says_it_cannot_dispatch_when_no_keyword_matched(demo):
    """未命中任何关键词时必须如实说无法分派，不许默认猜一个分析器。"""
    rep = AgentC(demo).handle("今天天气不错")
    assert rep.ok is False
    assert rep.kind == "unknown"
    assert "无法分派" in rep.summary
    assert (rep.error or "") == "关键词未命中"
    assert rep.payload["available"] == ["hottest", "paths", "cold", "gaps"]

    empty = AgentC(demo).handle("   ")
    assert empty.ok is False and empty.kind == "unknown" and "空请求" in empty.summary


# ============================================================ 落盘


def test_persist_writes_markdown_file_and_registers_report_row(demo):
    """`persist` 必须双份落盘：`reports/<id>-<kind>.md` 文件 + `analysis_reports` 登记行。

    批 R54（业主 2026-10-12 裁定 CS-10 ②「直接调分析器也落库」）之后：`hottest` 自己
    已经登记了一条，所以这里显式 `persist()` 写的是第二条（显式双份落盘仍然允许；
    `handle` 那条路靠 `report_id` 幂等，不会重复写）。两号必须不同、两条行都在表里。
    """
    rep = AgentC(demo).hottest(top_n=3, request="统计最热门的 3 个概念")
    sealed = rep.report_id
    assert sealed, "分析器产出即登记（CS-10 ②）—— `hottest` 返回时就该带 report_id"
    out = rep.persist()
    rid = out["report_id"]
    assert S.is_valid_id(rid) and rid != sealed, f"两次落盘各拿一个号：{sealed} / {rid}"
    assert out["markdown_path"] == f"reports/{rid}-hottest.md"

    path = demo.root / out["markdown_path"]
    assert path.exists() and path.read_text(encoding="utf-8") == rep.markdown
    rows = demo.rows("analysis_reports")
    assert [r["report_id"] for r in rows] == [sealed, rid], (
        "第一条是分析器自己落的、第二条是这次显式 persist 落的")
    row = next(r for r in rows if r["report_id"] == rid)
    assert row["kind"] == "hottest"
    assert row["request"] == "统计最热门的 3 个概念"
    assert row["summary"] and row["payload"]["entries"]
    assert row["markdown_path"] == out["markdown_path"]
    assert row["created_by"] == "agent-C"
    assert rep.report_id == rid


def test_persist_rejects_kind_outside_the_controlled_vocabulary(demo):
    """非法 kind 绝不能进表（D 读表时无法处理表外的 kind）。"""
    bad = AnalysisReport(kind="unknown", summary="有摘要", payload={}, markdown="# 有内容\n")
    bad._store = demo  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="受控词表"):
        bad.persist()

    no_md = AnalysisReport(kind="hottest", summary="有摘要", payload={}, markdown="  ")
    no_md._store = demo  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="markdown 为空"):
        no_md.persist()

    no_summary = AnalysisReport(kind="hottest", summary="", payload={}, markdown="# x\n")
    no_summary._store = demo  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="summary"):
        no_summary.persist()

    assert demo.rows("analysis_reports") == []


# ============================================================ 辅助


def _sections(markdown: str) -> dict[str, list[str]]:
    """按二级标题切分 markdown（段落级解析，避免"某紧凑字符串是否出现"这种弱断言）。"""
    out: dict[str, list[str]] = {}
    current = ""
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line.strip()
            out.setdefault(current, [])
        else:
            out.setdefault(current, []).append(line)
    return out


def _concept_chain_line(item: dict) -> str:
    """与 `AgentC._md_path` 完全一致的概念链行（用段落里的真实文本做断言，而不是"名字是否相邻出现"）。"""
    return "- 概念链：" + " → ".join(f"{n}({c})" for n, c in zip(item["concept_names"], item["concept_path"]))
