"""`python -m agentflow.agent_c` 的自检入口（`goal-7f5116c1` M6/M7）。

为什么需要这个文件：包形态下 `python -m agentflow.agent_c` 执行的是
`agent_c/__main__.py`。拆包时自检块被搬进了 `core.py`，于是它还在但永不被执行
—— 而 `python -m` 退出码 0 这条契约写在 `docs/ROLE-SPECS.md` 与
`scripts/release_check.py` 第 2 项里。这个文件把那一段块逐字搬回来。
"""
from __future__ import annotations

import pathlib

from .. import conceptrows as CR   # 并表过渡期：夹具/自检走这一处写口
from ._support import D, Path, S, Store, T, interactions
from .core import AgentC

#: 包形态下 `__file__` 比原来深一层目录，而自检块里按 `Path(__file__)` 的
#: 层级找 `demo/` 目录 —— 这里把它钉回原来那个模块的位置
#: （`src/agentflow/agent_c.py`），块体才能逐字搬移而行为不变。
__file__ = str(pathlib.Path(__file__).resolve().parents[1] / "agent_c.py")

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    # 运行方式：在 src/ 下执行 `python -m agentflow.agent_c`（或设 PYTHONPATH=src 后在任意目录执行）
    # 说明：本仓库的 tools/ 目录没有 __init__.py（那是别人的交付物边界），
    # 靠 Python 3 的命名空间包机制导入。若在某些工具链下 `python -m` 不成立，
    # 用：python -c "import sys; sys.path.insert(0,'.'); from agentflow import agent_c; agent_c._selftest()"
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        # 控制台编码重配失败无所谓：它只影响打印中文时的字形，不影响任何一条自检结论
        # （重定向到文件/管道时就会走到这里）。这是"有理由地忽略"，不是静默吞掉 ——
        # R001 要求的正是把这两件事区分开。
        pass

    from ..tools.base import ToolRegistry
    from ..tools.graph_tools import register as register_graph_tools
    from ..tools.trace_tools import register as register_trace_tools

    CHECKS: list[tuple[str, bool]] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        CHECKS.append((label, bool(cond)))
        print(f"    [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    def make_store(tag: str) -> Store:
        """临时工作区。优先系统临时目录；被沙箱拒绝时退到仓库内的 demo/ 目录。"""
        try:
            root = Path(tempfile.mkdtemp(prefix=f"agentflow_agentc_{tag}_"))
        except OSError:
            root = Path(__file__).resolve().parents[2] / "demo" / f"agentc_selftest_{tag}"
        st = Store(root)
        st.init(force=True)
        return st

    # ============================================================ 数据集
    # 至少 6 个概念、8 条关系；0000(群) 与 0002(域) 之间有 2 跳与 3 跳两条以上
    # 不同长度的路径；含一条 quote_verified=False（0002 号关系）与一条
    # status=suspect（0006/0011 号关系），用来验证评分确实会降级。
    def build_dataset(st: Store) -> None:
        concepts = [
            ("0000", "群", "带二元运算且满足结合律的集合"),
            ("0001", "阿贝尔群", "交换的群"),
            ("0002", "域", "乘法可交换的除环"),
            ("0003", "交换环", "乘法可交换的环"),
            ("0004", "模", "环在阿贝尔群上的作用"),
            ("0005", "理想", "环的加法子群且对乘法封闭"),
            ("0006", "孤立概念", "与任何概念都没有关系的概念"),
            ("0007", "子群", "群的非空子集且在运算下封闭"),
            ("0008", "环同态", "保持加法与乘法运算的映射"),
            ("0009", "素理想", "商环为整环的理想"),
        ]
        def rel(rid, cids, desc, lit, qv, status="active", page=None):
            return {
                "relation_id": rid,
                "concept_ids": sorted(cids),
                "description": desc,
                "lit_id": lit,
                "page_range": page or {"start": 1, "end": 1, "label": "p. 1"},
                "quote": f"原文引文 {rid}",
                "quote_normalized": f"原文引文 {rid}",
                "quote_verified": qv,
                "statement": desc,
                "status": status,
                "concept_group_key": "|".join(sorted(cids)),
            }

        relations = [
            rel("0000", ["0000", "0001"], "阿贝尔群是一种交换的群", "0000", True),
            rel("0001", ["0001", "0002"], "每个域都是阿贝尔群", "0001", True),
            # ↓ 引文校验失败：评分必须因此降级
            rel("0002", ["0000", "0003"], "交换环的加法群是阿贝尔群", "0002", False),
            rel("0003", ["0002", "0003"], "域是交换环", "0003", True),
            rel("0004", ["0000", "0004"], "模是群在环上的作用", "0004", True),
            rel("0005", ["0004", "0005"], "理想使模的构造成为可能", "0005", None),
            # ↓ status=suspect 且引文无法校验：评分必须因此降级
            rel("0006", ["0002", "0005"], "理想与商环的对应关系", "0006", None, status="suspect"),
            rel("0007", ["0000", "0005"], "群作用下的不变量", "0006", True),
            rel("0008", ["0001", "0004"], "阿贝尔群上的模结构", "0001", True),
            # 一条涉及 3 个概念的关系：产生 3 对边，共享同一个 relation_id
            rel("0009", ["0002", "0004", "0005"], "域上模与理想的三元关系", "0007", True),
            # 冷门概念 0007（子群）与两个热门概念之间的弱连接（低信息量路径的素材）
            rel("0010", ["0000", "0007"], "子群判定", "0002", False, status="suspect"),
            rel("0011", ["0007", "0002"], "待查", "0002", None, status="suspect"),
            # 一条3 跳且与前面几条 2 跳路径重合度低（Jaccard 0.4）的链：
            # 群 -环同态- 素理想- 域。用来验证"不同长度的路径"与"多跳=更多推理链"。
            rel("0012", ["0000", "0008"], "环同态保持群的加法运算结构", "0008", True),
            rel("0013", ["0008", "0009"], "素理想在环同态下的原像性质", "0009", True),
            rel("0014", ["0009", "0002"], "域中的素理想只有零理想这一个", "0010", None),
        ]
        literatures = [
            {"lit_id": "0000", "title": "代数结构导论", "type": "M", "summary": "教材", "path": "l0.txt", "processed": True, "year": 2001},
            {"lit_id": "0001", "title": "群论讲义", "type": "M", "summary": "讲义", "path": "l1.txt", "processed": True, "year": 1998},
            {"lit_id": "0002", "title": "环与模", "type": "M", "summary": "专著", "path": "l2.txt", "processed": True, "year": 2010},
            {"lit_id": "0003", "title": "域论初步", "type": "J", "summary": "论文", "path": "l3.txt", "processed": True, "year": 2015},
            {"lit_id": "0004", "title": "模论", "type": "M", "summary": "专著", "path": "l4.txt", "processed": True, "year": 2005},
            {"lit_id": "0005", "title": "理想与商环", "type": "J", "summary": "论文", "path": "l5.txt", "processed": True, "year": 2012},
            {"lit_id": "0006", "title": "群作用", "type": "J", "summary": "论文", "path": "l6.txt", "processed": True, "year": 2018},
            {"lit_id": "0007", "title": "三元关系研究", "type": "J", "summary": "论文", "path": "l7.txt", "processed": True, "year": 2020},
            {"lit_id": "0008", "title": "环同态", "type": "M", "summary": "专著", "path": "l8.txt", "processed": True, "year": 2003},
            {"lit_id": "0009", "title": "素理想与局部化", "type": "J", "summary": "论文", "path": "l9.txt", "processed": True, "year": 2016},
            {"lit_id": "0010", "title": "域论续", "type": "J", "summary": "论文", "path": "l10.txt", "processed": True, "year": 2019},
        ]
        (st.library).mkdir(parents=True, exist_ok=True)
        (st.library / "l0.txt").write_text(
            "An abelian group is a group in which the commutative law holds.\n", encoding="utf-8"
        )
        concept_rows = []
        for cid, name, definition in concepts:
            concept_rows.append(
                {
                    "concept_id": cid,
                    "name": name,
                    "definition": definition,
                    "normalized_name": T.normalize(name),
                    "related_concepts": D.derive_related_concepts(cid, relations),
                    "created_at": S.now_iso(),
                }
            )
        with st.tx(*CR.tables_for_concept_write("relations", "literature"),
                   actor="selftest", note="fixture") as tx:
            for r in concept_rows:
                CR.upsert_legacy_shaped(tx, r)
            for r in relations:
                tx.upsert("relations", r)
            for r in literatures:
                tx.upsert("literature", r)

    print("=" * 72)
    st = make_store("main")
    build_dataset(st)
    print(f"[1] 临时工作区 {st.root}")
    print(f"    概念 {len(CR.view(st, shape='legacy')['rows'])} 关系 {len(st.rows('relations'))} 文献 {len(st.rows('literature'))}")

    c = AgentC(st, config={"high": 3.0, "medium": 1.5}, actor="agent-C-selftest")
    g = c.build_graph()
    s = g.summary()
    print(f"[2] build_graph：节点={s['concept_count']} 关系={s['relation_count']} 两两边={s['pair_count']} "
          f"孤立={s['isolated_concepts']} 校验分布={s['quote_verified_counts']}")

    print("[3] 工具注册（低层图工具 + 溯源工具 + C 分析工具），并确认全是 read")
    reg = ToolRegistry(name="agentc-selftest")
    # 绑定角色（`P-14`）：本自检只调 `graph.*` / `trace.*`，那些工具的 `roles` 是 `("C","D")`，
    # 而这张注册表代表的是 C（只读）。不绑的话下面每一处 `reg.call` 都会以
    # "调用方没有声明角色"失败 —— 只读约束的刀不许靠"没写"来拿。
    reg.bound_role = "C"
    low = register_graph_tools(reg, store=st)
    tr = register_trace_tools(reg, store=st)
    ana = c.register_tools(reg)
    print(f"    graph 低层={low}")
    print(f"    trace   ={tr}")
    print(f"    分析器  ={ana}")
    print(f"    全部只读={all(reg.get(n).side_effect == 'read' for n in reg.names())}（共 {len(reg.names())} 个工具）")
    print(f"    graph.build -> {reg.call('graph.build').data['concept_count']} 个概念")

    print("[4] hottest(top_n=3)：出现次数 + 关系条数 + 概念组次数 + 代表关系")
    hr = c.hottest(top_n=3, request="统计最热门的 3 个概念")
    print(f"    summary: {hr.summary}")
    for e in hr.payload["entries"]:
        print(f"    {e['concept_id']} {e['name']}: occ={e['occurrences']} rel={e['relation_count']} grp={e['group_count']}")
        for r in e["representative_relations"]:
            print(f"        代表关系 {r['relation_id']} qv={r['quote_verified']} {r['status']} {r['description']!r}")
    check("hottest 命中概念名翻译", all(e["name"] and "(" not in e["name"] for e in hr.payload["entries"]))
    check("hottest 排序稳定（同分按 concept_id 升序）",
          hr.payload["hot_ids"] == sorted(hr.payload["hot_ids"], key=lambda x: (-g.counts()[x]["occurrences"], x)))

    print("[5] paths('0000','0002')：图搜索 → Jaccard 去重 → 逐跳重选关系 → 评分 → 分流")
    # 这里刻意用 max_paths=8（默认是 5）：按"长度升序"筛完后，2 跳路径恰好有 5 条，
    # 默认值会把 3 跳的那条挤到 dropped_by_max_paths 里，看不到"不同长度的路径"。
    # 这也顺带说明了 max_paths 是一个真实的展开上限，而不是装饰参数。
    P_MAX = 8
    pr = c.paths("0000", "0002", max_paths=P_MAX, max_len=4, max_overlap=0.5, request="查询 群 与 域 之间的关系")
    sh = pr.payload["search"]
    dd = pr.payload["dedup"]
    print(f"    summary: {pr.summary}")
    print(f"    图搜索：raw={sh['raw_path_count']} 截断={sh['truncated']} reasons={sh['truncation_reasons']} 预算={sh['budget_used']}/{sh['node_budget']}")
    print(f"    **未筛选前**的原始路径集合（按跳数分布 {sh['raw_paths_by_hops']}）：")
    for p in sh["raw_paths"]:
        print(f"      {'→'.join(p)}（{len(p) - 1} 跳）")
    print(f"    去重：保留={dd['kept_after_overlap_filter']} 展开={dd['selected_for_report']} 因重合丢弃={len(dd['dropped_by_overlap'])} 因max_paths丢弃={len(dd['dropped_by_max_paths'])}")
    for d in dd["dropped_by_overlap"]:
        print(f"      丢弃 {'→'.join(d['path'])}（Jaccard={d['max_jaccard']} vs {'→'.join(d['against'])}）")
    print(f"    判决：high={pr.payload['levels']['high']} medium={pr.payload['levels']['medium']} low={pr.payload['levels']['low']}")
    for it in pr.payload["paths"]:
        print(f"    - {'→'.join(it['concept_path'])} 链={'→'.join(it['relation_chain'])} 跳={it['hops']} score={it['score']} => {it['level']}")
        for h in it["hop_details"]:
            print(f"        跳{h['hop']} {h['from']}-{h['to']} 候选{h['candidate_count']}条{h['candidate_ids']} 选中{h['chosen']}")
        for t in it["score_breakdown"]["terms"]:
            print(f"        {t['name']}: {t['detail']} -> {t['contribution']:+}")
    check("存在多条不同长度的路径（2 跳与 3 跳都有）",
          any(it["hops"] == 2 for it in pr.payload["paths"]) and any(it["hops"] == 3 for it in pr.payload["paths"]))
    print(f"    定性证据：未筛选前 3 跳路径 {sh['raw_paths_by_hops'].get('3', 0)} 条（图搜索确实找到了它们），"
          f"其中 {sum(1 for d in dd['dropped_by_overlap'] if len(d['path']) - 1 == 3)} 条因高重合被丢弃；"
          f"筛选后仍有 3 跳路径={any(it['hops'] == 3 for it in pr.payload['paths'])}")
    check("Jaccard 去重确实丢掉了高重合路径", len(dd["dropped_by_overlap"]) >= 1)
    check("三个等级都被真实触发（high/medium/low 均 > 0）",
          pr.payload["levels"]["high"] > 0 and pr.payload["levels"]["medium"] > 0 and pr.payload["levels"]["low"] > 0)
    check("引文校验失败的那条路径被降级（不是 high）",
          all(it["level"] != "high" for it in pr.payload["paths"] if "0002" in it["relation_chain"]))
    check("每条路径都有可逐项打印的 score_breakdown",
          all(len(it["score_breakdown"]["terms"]) == 7 for it in pr.payload["paths"]))
    # ---- 正文/附录/统计的分流必须按小节内容核对，而不是靠字符串计数
    # （早先这里用 "'→'.join(concept_path) in md_body" 去查，而正文渲染的是带概念名的
    #   "群(0000) → 阿贝尔群(0001)"，那个紧凑串只出现在统计段 —— 断言恒假，
    #   却"看起来"在检查正文。现在改成解析小节：正文段里不允许出现任何非 high 的路径标题。）
    def _section(md: str, start_marker: str, end_marker: str | None) -> str:
        seg = md.split(start_marker, 1)[1] if start_marker in md else ""
        if end_marker and end_marker in seg:
            seg = seg.split(end_marker, 1)[0]
        return seg

    body = _section(pr.markdown, "## 正文（仅高信息量路径）", "## 附录")
    appendix = _section(pr.markdown, "## 附录", "## 统计")
    stats_sec = _section(pr.markdown, "## 统计", "## 被重合度筛掉")
    body_high = body.count("（高信息量，score=")
    body_other = body.count("（中信息量，score=") + body.count("（低信息量，score=")
    md_high = pr.markdown.count("（高信息量，score=")
    print(f"    分流核对：正文段 high 标题 {body_high} 个 / 非 high 标题 {body_other} 个；"
          f"附录段 medium 标题 {appendix.count('（中信息量，score=')} 个；统计段低信息量行 {stats_sec.count('score=')} 个")
    check("正文只含 high 路径（段落级核对，不是字符串计数）",
          body_high == pr.payload["levels"]["high"] and body_other == 0 and appendix.count("（中信息量，score=") == pr.payload["levels"]["medium"]
          and md_high == pr.payload["levels"]["high"])
    check("附录明确标注'未达正文标准'", "未达正文标准" in pr.markdown)

    print("[6] 预算截断如实回报：node_budget=3 的 AgentC 必须给出 truncated=True 与警告")
    tiny = AgentC(st, config={"node_budget": 3}, actor="agent-C-tiny")
    tr_rep = tiny.paths("0000", "0002", request="截断自检")
    print(f"    truncated={tr_rep.truncated} reasons={tr_rep.payload['search']['truncation_reasons']} "
          f"raw={tr_rep.payload['search']['raw_path_count']} 预算={tr_rep.payload['search']['budget_used']}/3")
    print(f"    summary: {tr_rep.summary[:80]}…")
    for w in tr_rep.warnings:
        print(f"    warning: {w[:90]}…")
    check("预算截断被如实标出", tr_rep.truncated and tr_rep.payload["search"]["truncation_reasons"] == ["node_budget"])

    print("[7] '没有找到高信息量路径'必须明说：把阈值抬到 99，所有 high 都该消失")
    strict = AgentC(st, config={"high": 99.0, "medium": 1.5}, actor="agent-C-strict")
    sr = strict.paths("0000", "0002", max_paths=5, request="阈值自检")
    print(f"    summary: {sr.summary}")
    print(f"    has_high={sr.payload['has_high']} 正文里是否明说={'没有找到高信息量路径' in sr.markdown}")
    check("无 high 时明说'没有找到高信息量路径'",
          (not sr.payload["has_high"]) and ("没有找到高信息量路径" in sr.markdown) and ("没有找到高信息量路径" in sr.summary))

    print("[8] LLM 钩子（构造时传入假模型）：只重排顺序，评分与内容不变")
    class _FakeLLM:
        def rank_paths(self, payload):
            # 故意给一个逆序排列，验证"顺序被采纳、内容与分数没变"
            return list(reversed([p["index"] for p in payload["paths"]]))

        def judge_gaps(self, payload):
            return {c["key"]: {"worth": True, "confidence": "medium", "reason": "假模型复核通过"} for c in payload["candidates"]}

    hooked = AgentC(st, config={}, actor="agent-C-llm", llm=_FakeLLM())
    hr2 = hooked.paths("0000", "0002", max_paths=P_MAX, request="钩子自检")
    print(f"    used_for_ordering={hr2.payload['hook']['used_for_ordering']} note={hr2.payload['hook']['note']}")
    print(f"    第一跳链={hr2.payload['paths'][0]['relation_chain']} score={hr2.payload['paths'][0]['score']} llm_ranked={hr2.payload['paths'][0]['llm_ranked']}")
    same_scores = sorted(p["score"] for p in hr2.payload["paths"]) == sorted(p["score"] for p in pr.payload["paths"])
    check("LLM 钩子只改顺序、不改评分", hr2.payload["hook"]["used_for_ordering"] and same_scores)
    hr3 = hooked.hottest(top_n=3)
    check("无钩子的分析器（hottest）不受 LLM 影响", hr3.payload["entries"] == hr.payload["entries"])
    # 钩子抛异常时必须回退
    class _BrokenLLM:
        def rank_paths(self, payload):
            raise RuntimeError("模型挂了")

        def judge_gaps(self, payload):
            raise RuntimeError("模型挂了")
    broken = AgentC(st, config={}, llm=_BrokenLLM())
    br = broken.paths("0000", "0002", max_paths=P_MAX)
    print(f"    钩子抛异常后：used={br.payload['hook']['used_for_ordering']} warnings={[w[:40] for w in br.warnings]}")
    check("钩子失败时回退到确定性顺序且不丢结果",
          (not br.payload["hook"]["used_for_ordering"]) and len(br.payload["paths"]) == len(pr.payload["paths"]))

    print("[9] cold(top_n=2)：冷门榜、完全孤立、弱连接判据、'冷门但连接强'")
    cr = c.cold(top_n=2, request="研究冷门概念")
    print(f"    summary: {cr.summary}")
    for e in cr.payload["entries"]:
        print(f"    {e['concept_id']} {e['name']}: degree={e['degree']} 与热门概念的关系={len(e['relations_to_hot'])} 弱关系={len(e['weak_relations'])} undervalued={e['undervalued']}")
        for r in e["relations_to_hot"]:
            print(f"        [{r['relation_id']}] 与 {'/'.join(o['name'] for o in r['other_concepts'])} weak_score={r['weak_score']} 理由={r['weak_reasons']}")
    print(f"    完全孤立：{[x['concept_id'] + ':' + x['name'] for x in cr.payload['isolated']]}")
    print(f"    冷门但连接强：{cr.payload['undervalued_ids']}")
    check("孤立概念（degree=0）被单独归类、不进冷门榜",
          "0006" in [x["concept_id"] for x in cr.payload["isolated"]] and all(e["degree"] > 0 for e in cr.payload["entries"]))
    check("弱判据给到了理由字符串",
          all(r["weak_reasons"] for e in cr.payload["entries"] for r in e["weak_relations"]))
    check("'冷门但连接强'单独列出（0003 与热门概念 0002 的连接引文已证实）",
          "0003" in cr.payload["undervalued_ids"])

    print("[10] gaps(limit=5)：低频概念组 + 结构洞 + 二元结论")
    gr = c.gaps(limit=5, request="完善关系图，找结构洞")
    print(f"    verdict={gr.payload['verdict']} has_candidates={gr.payload['has_candidates']}")
    print(f"    conclusion: {gr.payload['conclusion']}")
    print(f"    检索范围={gr.payload['searched']} truncated={gr.truncated}")
    for cg in gr.payload["candidate_gaps"][:5]:
        print(f"    候选[{cg['kind']}] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 置信度={cg['confidence']}")
        print(f"        理由={cg['reason']}")
    print(f"    被否决（low）{len(gr.payload['low_confidence_candidates'])} 条，示例理由：")
    for cg in gr.payload["low_confidence_candidates"][:3]:
        print(f"      - {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 负向={'；'.join(cg['negative_signals'])}")
    check("gaps 给出明确二元结论", gr.payload["verdict"] in ("有", "无"))
    check("candidate_gaps 只收 medium 以上置信度",
          all(x["confidence"] in ("high", "medium") for x in gr.payload["candidate_gaps"]))

    print("[11] gaps 的'证据不足'路径：候选只有'引文全失败'这类依据时，否决项必须直接剔除，不许包装成'找到了'")
    st2 = make_store("nogap")
    with st2.tx(*CR.tables_for_concept_write("relations", "literature"),
                actor="selftest", note="nogap") as tx:
        for cid, name in [
            ("0000", "这是一整句话并不是概念因为它确实太长了甲"),
            ("0001", "这是一整句话并不是概念因为它确实太长了乙"),
            ("0002", "桥"),
        ]:
            CR.upsert_legacy_shaped(tx, {"concept_id": cid, "name": name, "definition": "", "normalized_name": T.normalize(name), "related_concepts": []})
        for rid, cids in [("0000", ["0000", "0002"]), ("0001", ["0001", "0002"])]:
            tx.upsert(
                "relations",
                {
                    "relation_id": rid,
                    "concept_ids": sorted(cids),
                    "description": "可疑关系",
                    "lit_id": "0000",
                    "page_range": {"start": 1, "end": 1, "label": "p. 1"},
                    "quote": "",
                    "quote_verified": False,
                    "status": "active",
                    "concept_group_key": "|".join(sorted(cids)),
                },
            )
        tx.upsert("literature", {"lit_id": "0000", "title": "样例", "type": "M", "summary": "", "path": None, "processed": True})
    c2 = AgentC(st2, config={}, actor="agent-C-nogap")
    g2 = c2.gaps(limit=5, request="完善关系图")
    print(f"    verdict={g2.payload['verdict']}")
    print(f"    conclusion: {g2.payload['conclusion']}")
    print(f"    候选={len(g2.payload['candidate_gaps'])} 否决={len(g2.payload['vetoed_candidates'])} "
          f"净分不足={len(g2.payload['low_confidence_candidates'])} "
          f"结构洞={g2.payload['searched']['structural_holes']} 低频组={g2.payload['searched']['rare_group_candidates']}")
    for cg in g2.payload["vetoed_candidates"][:4]:
        print(f"      - [veto] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} "
              f"（本可判 {cg['confidence_deterministic']}）理由={'；'.join(cg['veto_reasons'])}")
    for cg in g2.payload["low_confidence_candidates"][:3]:
        print(f"      - [low ] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 负向={'；'.join(cg['negative_signals'])}")
    check("证据不足时 verdict='无' 且候选为空",
          g2.payload["verdict"] == "无" and g2.payload["candidate_gaps"] == [] and "证据不足" in g2.payload["conclusion"])
    check("否决项生效：'引文全部失败/名字不是概念'的候选被 veto 而不是靠扣分压低",
          len(g2.payload["vetoed_candidates"]) > 0 and all(c["veto_reasons"] for c in g2.payload["vetoed_candidates"]))
    check("veto 候选仍在报告里逐条留理由（不是静默丢弃）",
          "被否决项（veto）剔除的候选" in g2.markdown and all(c["veto_reasons"][0] in g2.markdown for c in g2.payload["vetoed_candidates"][:1]))

    print("[12] trace 工具与报告联动：关系代号链 → L1 表述 → L3 正文（按需）")
    chain = pr.payload["paths"][0]["relation_chain"]
    tch = reg.call("trace.chain", relation_ids=list(chain))
    print(f"    trace.chain({chain}) ok={tch.ok}")
    for line in tch.data["chain_text"].splitlines():
        print(f"      {line}")
    l1 = reg.call("trace.relation", relation_id=chain[0])
    print(f"    trace.relation({chain[0]}) 概念名={l1.data['concept_names']} 页码={l1.data['page_range']} 三态={l1.data['quote_verified_label']}")
    l3 = reg.call("trace.literature", lit_id=l1.data["lit_id"], max_chars=200)
    print(f"    trace.literature({l1.data['lit_id']}) status={l3.data['status']} 正文={l3.data['text'][:48]!r}")
    l3b = reg.call("trace.literature", lit_id="0003")
    print(f"    trace.literature(0003，只登记了路径没落文件) status={l3b.data['status']}")
    check("链条溯源可用且下钻 L3 如实报告状态", tch.ok and l3.data["status"] == "ok" and l3b.data["status"] == "file_missing")

    print("[13] persist()：reports/<id>-<kind>.md + analysis_reports 登记行")
    info = pr.persist()
    print(f"    {info}")
    # 取「这一次」 persist 拿到的号对应的登记行，不能取 `rows[0]`：
    # 2026-10-12 业主裁定 CS-10 ②（"直接调分析器也落库"）之后，`AgentC._report`
    # 在 `ok` 且 kind 在受控词表里时会收口一次 `persist()`（`core.py` 的那段
    # "产出即登记"）。于是走到本段时 `analysis_reports` 里已经有本文件前面几个
    # 分析器各自落的行，`rows[0]` 是「第一份」报告而不是这一份 —— 旧断言
    # (`rows[0]`) 是"产出即登记"之前的写法，它过期了，不是这里该变绿。
    matched = [r for r in st.rows("analysis_reports") if r["report_id"] == info["report_id"]]
    row = matched[0] if matched else {}
    print(f"    登记行：id={row.get('report_id')} kind={row.get('kind')} "
          f"request={row.get('request')!r} path={row.get('markdown_path')}")
    print(f"    summary={str(row.get('summary') or '')[:60]}…")
    md_file = st.root / info["markdown_path"]
    print(f"    文件存在={md_file.exists()} 大小={md_file.stat().st_size} 字节；"
          f"payload 键={sorted((row.get('payload') or {}).keys())[:6]}…")
    check("persist 落盘且登记行一致（按这次拿到的号定位，且该号只有一行）",
          len(matched) == 1 and row.get("report_id") == info["report_id"]
          and row.get("markdown_path") == info["markdown_path"] and md_file.exists())
    no_persist = c.handle("随便说点什么不相干的话")
    try:
        no_persist.persist()
        check("kind='unknown' 被拒绝登记", False)
    except ValueError as exc:
        print(f"    拒绝登记 unknown：{exc}")
        check("kind='unknown' 被拒绝登记", True)
    csv = c.hottest(top_n=2).persist()
    print(f"    第二份报告：{csv}")

    print("[14] handle() 关键词分派（确定性）")
    cases = [
        ("统计最热门的 5 个概念", "hottest"),
        ("查询 群 与 域 之间的关系", "paths"),
        ("研究冷门概念", "cold"),
        ("完善关系图，找缺失的结构洞", "gaps"),
    ]
    for text, want in cases:
        rep = c.handle(text)
        print(f"    {text!r} -> kind={rep.kind} ok={rep.ok} summary={rep.summary[:56]}…")
        check(f"handle 分派 {text!r} → {want}", rep.kind == want and rep.ok)
    bad = c.handle("查询 群 与 不存在的概念 之间的关系")
    print(f"    解析失败示例：ok={bad.ok} error={bad.error}")
    print(f"    summary={bad.summary}")
    print(f"    候选概念（前3）={[x['name'] for x in bad.payload['candidate_concepts'][:3]]}")
    check("概念解析不到时 fail 并列出候选概念",
          (not bad.ok) and bad.error and len(bad.payload["candidate_concepts"]) == len(g.concept_by_id))
    unk = c.handle("帮我看看这个怎么样")
    check("未命中关键词时如实说无法分派", (not unk.ok) and "无法分派" in unk.summary)

    # ============================================================ I1 服务面
    print("[15] I1 服务面：neighbors / relations_between / contradictions / structural_duplicates")
    # 知识表的磁盘字节前后不变（C 是只读角色）。并表之后概念行住 `statements`
    # ⇒ 取样面换成"新标准里的概念行 + relations + literature"：
    # 老表已退役，`concepts.json` 不再是这批行该在的地方。
    _kn = ("statements", "relations", "literature")
    kn_before = {n: (st.data / f"{n}.json").read_bytes() for n in _kn}
    nb1 = c.neighbors("0000", depth=1)
    nb2 = c.neighbors("0000", depth=2)
    nbt = c.neighbors("0000", depth=1, max_nodes=2)
    nbx = c.neighbors("9999")
    rb1 = c.relations_between("0000", "0001")
    rb0 = c.relations_between("0000", "0006")  # 0006 是孤立概念
    kn_after = {n: (st.data / f"{n}.json").read_bytes() for n in _kn}
    print(f"    neighbors(0000,depth=1)：{[(n['concept_id'], n['distance']) for n in nb1['nodes']]}")
    print(f"    neighbors(0000,depth=2) 的 2 跳节点："
          f"{[n['concept_id'] for n in nb2['nodes'] if n['distance'] == 2]}")
    print(f"    neighbors(max_nodes=2)：truncated={nbt['truncated']} 节点数={len(nbt['nodes'])} 理由={nbt['reason'][-40:]!r}")
    print(f"    neighbors(9999)：checked={nbx['checked']} empty={nbx['empty']} reason={nbx['reason'][:36]!r}…")
    print(f"    relations_between(0000,0001)：{rb1['relation_ids']}；"
          f"relations_between(0000,0006)：ids={rb0['relation_ids']} empty={rb0['empty']} checked={rb0['checked']}")
    check("neighbors 的 1 跳恰好是图索引里的直接邻居",
          {n["concept_id"] for n in nb1["nodes"] if n["distance"] == 1} == set(g.neighbors("0000"))
          and any(n["distance"] == 0 for n in nb1["nodes"]))
    check("neighbors 的 2 跳把 2 跳新节点并进来且带上 distance",
          any(n["distance"] == 2 for n in nb2["nodes"])
          and "0006" not in {n["concept_id"] for n in nb2["nodes"]})
    check("neighbors 超 max_nodes ⇒ truncated=True（不静默截断）",
          nbt["truncated"] is True and len(nbt["nodes"]) == 2 and "max_nodes" in nbt["reason"])
    check("neighbors 查不到代号 ⇒ checked=True 且说明'该代号不在概念表里'",
          nbx["checked"] is True and nbx["nodes"] == [] and "不在概念表里" in nbx["reason"])
    check("relations_between 三态：有边给 relation_ids；无边 checked=True+empty=True",
          rb1["relation_ids"] == ["0000"] and rb0["relation_ids"] == [] and rb0["empty"] is True
          and rb0["checked"] is True and "没有关系" in rb0["reason"])
    check("I1 服务面只读：三张知识表逐字节不变", kn_before == kn_after)

    # ---- 矛盾 / 结构重复：另起一个小工作区，人造"矛盾对 + 重复对"
    st4 = make_store("service")

    def _svc_rel(rid, cids, desc, lit, qv=True):
        return {
            "relation_id": rid, "concept_ids": sorted(cids), "description": desc, "lit_id": lit,
            "page_range": {"start": 1, "end": 1, "label": "p. 1"}, "quote": f"引文 {rid}",
            "quote_normalized": f"引文 {rid}", "quote_verified": qv, "statement": desc,
            "status": "active", "concept_group_key": "|".join(sorted(cids)),
        }

    with st4.tx(*CR.tables_for_concept_write("relations", "literature"),
                actor="selftest", note="service") as tx:
        for cid, name in [("0000", "群"), ("0001", "阿贝尔群"), ("0002", "环"),
                          ("0003", "环"), ("0004", "桥甲"), ("0005", "桥乙"),
                          ("0006", "孤儿甲"), ("0007", "孤儿乙")]:
            CR.upsert_legacy_shaped(tx, {"concept_id": cid, "name": name, "definition": "d",
                                   "normalized_name": T.normalize(name), "related_concepts": []})
        for r in [
            # 人造矛盾对：同概念组，一句明确肯定、一句明确否定（才够格 strong）
            _svc_rel("0000", ["0000", "0001"], "群是阿贝尔群", "0000"),
            _svc_rel("0001", ["0000", "0001"], "群不是阿贝尔群", "0001"),
            # 结构重复对：0002/0003 邻域完全相同且名字规范化后相同 ⇒ merge
            _svc_rel("0002", ["0002", "0004"], "环与桥甲", "0000"),
            _svc_rel("0003", ["0002", "0005"], "环与桥乙", "0000"),
            _svc_rel("0004", ["0003", "0004"], "环与桥甲（另一代号）", "0000"),
            _svc_rel("0005", ["0003", "0005"], "环与桥乙（另一代号）", "0000"),
        ]:
            tx.upsert("relations", r)
    c4 = AgentC(st4, actor="agent-C-service")
    con = c4.contradictions()
    con_scoped = c4.contradictions(relation_ids=["0000", "0001"])
    sd = c4.structural_duplicates()
    # 单独用"枚举上限=1"跑一次：验证"截断通知被单列"这条约束（正向/负控都要能测）
    sd_trunc = AgentC(st4, config={"structural_duplicate_max_pairs": 1}).structural_duplicates()
    print(f"    contradictions()：checked={con['checked']} scanned={con['scanned']} "
          f"命中={[x['relation_ids'] for x in con['contradictions']]} "
          f"strong={con['strong_count']} weak={con['weak_count']} method={con['method']}")
    print(f"    contradictions(relation_ids=[0000,0001])：scanned={con_scoped['scanned']} "
          f"命中={len(con_scoped['contradictions'])}")
    print(f"    structural_duplicates()：候选={[(x['concept_ids'], x['proposal']) for x in sd['candidates']]} "
          f"truncation_notice={'有' if sd['truncation_notice'] else '无'}")
    print(f"    枚举上限=1 时：候选={len(sd_trunc['candidates'])} 条，"
          f"truncation_notice={'有' if sd_trunc['truncation_notice'] else '无'}")
    check("contradictions 命中人造矛盾对且标为 strong；method_note 声明分档与假阳性",
          con["checked"] is True and len(con["contradictions"]) == 1
          and con["contradictions"][0]["strength"] == "strong"
          and con["strong_count"] == 1 and con["weak_count"] == 0
          and con["method"] == "literal"
          and "只做字面判据，不声称能判定一般语义矛盾" in con["method_note"]
          and "strong" in con["method_note"] and "假阳性" in con["method_note"])
    check("contradictions 给了 relation_ids 就只扫这些（scanned 等于给定条数）",
          con_scoped["scope"] == "given_relation_ids" and con_scoped["scanned"] == 2
          and len(con_scoped["contradictions"]) == 1)
    check("structural_duplicates 正向：邻域相同 + 同名 ⇒ proposal=merge",
          any(x["proposal"] == "merge" and set(x["concept_ids"]) == {"0002", "0003"} for x in sd["candidates"]))
    check("structural_duplicates 负控：邻域相同但名字不同 ⇒ proposal=review 且写明'不得据此合并'",
          any(x["proposal"] == "review" and set(x["concept_ids"]) == {"0004", "0005"}
              and "不得据此合并" in x["reason"] for x in sd["candidates"]))
    check("structural_duplicates 负控：孤立概念不参与枚举",
          all("0006" not in x["concept_ids"] and "0007" not in x["concept_ids"] for x in sd["candidates"]))
    check("structural_duplicates 的截断通知与候选分开（下游不会把它当成一对概念）",
          sd_trunc["truncation_notice"] is not None
          and sd_trunc["truncation_notice"]["is_truncation_notice"] is True
          and all(not x.get("is_truncation_notice") for x in sd_trunc["candidates"]))

    # ============================================================ I3 缺口直连 A
    print("[16] I3 缺口直连 A：gaps(submit_requests=True) 的闸门与三态")
    st5 = make_store("i3")

    def _i3_fixture(target: Store) -> None:
        # 概念号与关系里的 concept_ids 必须「同一套」：2026-10-14 业主裁定
        # "所有四位编号改成六位"之后 `S.format_id` 发的是 `000000…`，而这里
        # 原先概念行用 `S.format_id(i)`、关系行却写死 `"0000"…` ⇒ 图里每个
        # 概念代号都查不到名字，候选全被 `_looks_like_non_concept` 否决，
        # 于是 I3 正向与闸门两条断言测的都不是闸门（Fixture 过期，见 F-2/F-3）。
        cid = [S.format_id(i) for i in range(4)]
        with target.tx(*CR.tables_for_concept_write("relations", "literature"),
                       actor="selftest", note="i3") as tx:
            for i in range(4):
                CR.upsert_legacy_shaped(tx, {"concept_id": cid[i], "name": f"概念{i}", "definition": "d",
                                       "normalized_name": T.normalize(f"概念{i}"), "related_concepts": []})
            for r in [
                _svc_rel(S.format_id(0), [cid[0], cid[1]], "一条足够长的关系描述用于评分", S.format_id(0)),
                _svc_rel(S.format_id(1), [cid[0], cid[2]], "一条足够长的关系描述用于评分", S.format_id(1)),
                _svc_rel(S.format_id(2), [cid[1], cid[3]], "一条足够长的关系描述用于评分", S.format_id(0)),
            ]:
                tx.upsert("relations", r)

    _i3_fixture(st5)
    c5 = AgentC(st5, actor="agent-C-i3")
    req_before = (st5.data / "search_requests.json").read_bytes()
    rep_off = c5.gaps(submit_requests=False)
    req_after_off = (st5.data / "search_requests.json").read_bytes()
    rep_on = c5.gaps(submit_requests=True)
    rows5 = st5.rows("search_requests")
    topics5 = {"、".join(x["concept_names"]) for x in rep_on.payload["candidate_gaps"]}
    # 单轮上限是 `interactions.DEFAULTS["max_gap_requests_per_run"]`（裁定 C9：3 → 30）。
    # 旧断言把它写死成 `<= 3`：那是 2026-10-12 之前的口径，「过期的是这个数字」，
    # 不是闸门被放宽了。断言改成"新增条数 == min(候选数, 当次上限)"，比原来更紧：
    # 它同时钉住"候选真的被提交"与"每轮上限真的生效"。
    max_per_run = int(interactions.DEFAULTS["max_gap_requests_per_run"])
    n_cand = len(rep_on.payload["candidate_gaps"])
    print(f"    候选={n_cand} 条；"
          f"关闭时新增={len(rep_off.payload['submitted_request_ids'])} 条"
          f"（enabled={rep_off.payload['request_submission']['enabled']}）"
          f"；每轮上限 max_gap_requests_per_run={max_per_run}")
    print(f"    开启后新增={len(rows5)} 条："
          f"{[(r['request_id'], r['topic'], r['submitted_by'], r['priority'], r['mode']) for r in rows5]}")
    print(f"    被拒={len(rep_on.payload['rejected_requests'])} 条，"
          f"示例理由={rep_on.payload['rejected_requests'][0]['reason'][:48] if rep_on.payload['rejected_requests'] else '（无）'}…")
    check("I3 默认关闭：submit_requests=False 时一条 search_requests 都不写（逐字节不变）",
          req_before == req_after_off
          and rep_off.payload["submitted_request_ids"] == [] and rep_off.payload["request_submission"]["enabled"] is False)
    check("I3 正向：新增 == min(候选数, 每轮上限)，且 submitted_by/priority/mode/topic 全部合规",
          0 < len(rows5) == min(n_cand, max_per_run)
          and all(r["submitted_by"] == "agent-C" and r["priority"] == "medium"
                  and r["mode"] == "topical" and r["topic"] in topics5 and not r["done"] for r in rows5))

    # 闸门用例要「把在途填到当次上限」（`interactions.DEFAULTS["max_inflight_requests"]`，
    # 裁定 C9：20 → 200）。旧夹具固定填 20 行并称"20/20 上限"——上限改成 200 之后
    # 那 20 行只是"在途 20/200"，闸门当然放行。过期的是夹具里的数字。
    inflight_limit = int(interactions.DEFAULTS["max_inflight_requests"])
    st6 = make_store("i3gate")
    _i3_fixture(st6)
    with st6.tx("search_requests", actor="selftest", note="i3gate") as tx:
        for i in range(inflight_limit):
            row = S.SearchRequest(
                request_id=f"r-{S.format_id(i + 1)}", timestamp=S.now_iso(), topic=f"占位主题{i}",
                mode="topical", submitted_by="agent-D",
            )
            row.validate()
            tx.upsert("search_requests", row.to_dict())
    gate_before = (st6.data / "search_requests.json").read_bytes()
    rep_gate = AgentC(st6, actor="agent-C-i3gate").gaps(submit_requests=True)
    print(f"    在途 {inflight_limit}/{inflight_limit}（上限）时：新增={len(rep_gate.payload['submitted_request_ids'])} 条，"
          f"被拒={len(rep_gate.payload['rejected_requests'])} 条")
    check("I3 闸门：在途到上限时拒绝而不是无限排队，且逐条留下理由",
          rep_gate.payload["candidate_gaps"]
          and rep_gate.payload["submitted_request_ids"] == []
          and gate_before == (st6.data / "search_requests.json").read_bytes()
          and len(rep_gate.payload["rejected_requests"]) == len(rep_gate.payload["candidate_gaps"])
          and all("已达上限" in r["reason"] for r in rep_gate.payload["rejected_requests"]))

    print("=" * 72)
    failed = [lbl for lbl, okk in CHECKS if not okk]
    print(f"自检断言：{len(CHECKS) - len(failed)}/{len(CHECKS)} 通过")
    if failed:
        for lbl in failed:
            print(f"  FAILED: {lbl}")
    # 汇总行与退出码同源（F-7）：README/`release_check.py`/CI 读的都是「退出码」，
    # 所以"打印 FAILED 却退 0"等于把三态折平（FAILED 降级成 pass）。
    passed = len(CHECKS) - len(failed)
    print(f"SELF-CHECK {'DONE' if not failed else 'FAILED'}（agent_c）："
          f"{passed} 项通过 / {len(failed)} 项失败")
    raise SystemExit(0 if not failed else 1)
