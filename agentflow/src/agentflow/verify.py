"""全局不变量校验。

为什么需要一个独立的校验器，而不是"相信写入路径是对的"：

- 写入路径只覆盖"正常流程"。而本系统的数据会被**两个智能体 + 可能的人工编辑**同时
  触碰，schema 级校验（`schema.validate`）只能保证"单行自洽"，管不了**跨表一致性**
  ——例如 `relations.lit_id` 指向的文献是否真的存在、`related_concepts` 是否与关系表
  一致、`processed=true` 的文献是否真的处理过。
- 校验器也是**自愈的入口**：`related_concepts` 若与派生结果不一致，报告里会给出
  "应该是多少"，可以直接据此修复，而不是靠人肉比对。

`verify` 分两级：默认只做静态检查（快，随时可跑）；`--deep` 会重新打开文献做引文复核
（慢，需要文件在本地）。
"""

from __future__ import annotations

import re

import json
from dataclasses import dataclass, field
from typing import Any

from . import dedup as D
from . import schema as S
from . import textutil as T
from .quoteverify import check_quote
from .store import MAX_ID, Store


@dataclass
class Issue:
    level: str  # error | warning
    table: str
    row_id: str | None
    code: str
    message: str

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "table": self.table,
            "row_id": self.row_id,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class VerifyReport:
    checked: dict[str, int] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    deep: bool = False

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "deep": self.deep,
            "checked": self.checked,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


def _id_contiguity(rows: list[dict], id_field: str) -> tuple[bool, list[str], int]:
    """检查 4 位 ID 是否从 0000 起连续无空洞。

    空洞本身**不是错误**（ID 只需唯一+单调），但值得报警告：它通常意味着
    "分配了 ID 却没建成行"，也就是某次事务中途出过问题。
    """
    ids = sorted(r[id_field] for r in rows if id_field in r)
    if not ids:
        return True, [], -1
    missing: list[str] = []
    for i in range(len(ids)):
        want = f"{i:04d}"
        if ids[i] != want:
            missing.append(want)
    return (not missing), missing, int(ids[-1])


def verify_all(
    store: Store,
    *,
    deep: bool = False,
    extract_text: Any = None,
    quote_widen: int = 1,
    allow_fulltext_quote_fallback: bool = False,
) -> VerifyReport:
    """校验全局不变量。

    `quote_widen` / `allow_fulltext_quote_fallback` **必须与 agent_b 用的一致**，
    否则 `--deep` 会按一套比写入时更严的规则重算，把"写入时合规"的引文报成
    `quote_not_found` —— 那是**假报警**，比不校验更糟，因为它会训练人忽略告警。
    调用方（CLI）负责从同一份配置里取这两个值。
    """
    rep = VerifyReport(deep=deep)

    # ---- schema 级（逐表逐行）
    for table in S.TABLES:
        doc = store.read(table)
        rep.checked[table] = len(doc.get("rows") or [])
        try:
            S.validate_table(table, doc)
        except ValueError as e:
            rep.issues.append(Issue("error", table, None, "schema_invalid", str(e)))

    requests = store.rows("search_requests")
    literature = store.rows("literature")
    concepts = store.rows("concepts")
    relations = store.rows("relations")

    lit_by_id = {r["lit_id"]: r for r in literature}
    con_by_id = {r["concept_id"]: r for r in concepts}
    rel_by_id = {r["relation_id"]: r for r in relations}

    # ---- ID 唯一性与连续性
    #
    # ⚠️ **"哪些表属于 4 位编号空间"必须从 schema 推导，不许写死表名。**
    #
    # 这里原先只写了 `if table == "search_requests": continue`。新增
    # `reprocess_requests`（ID 形如 `p-NNNN`）之后，`_id_contiguity` 会对它做
    # `int("p-0001")` ⇒ **verify 自己崩掉**，而崩掉的原因与"库里有没有问题"
    # 完全无关。这类"写死一张名单"的缺陷在本项目里已经出现过三次
    # （roles 字符串、sync_counters 的 kind 列表、现在这里）。
    # 判据只有一个：**这个表的 id_field 是否被 ID_COUNTERS 覆盖**。
    counter_fields = set(S.ID_COUNTERS.values())
    for table, spec in S.TABLES.items():
        rows = store.rows(table)
        idf = spec["id_field"]
        ids = [r.get(idf) for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        for d in sorted(dupes):
            rep.issues.append(Issue("error", table, d, "duplicate_id", f"{idf}={d} 重复出现"))
        if idf not in counter_fields:
            continue  # 非 4 位编号空间（`r-NNNN` / `p-NNNN` 这类过程记录）
        contiguous, missing, maxid = _id_contiguity(rows, idf)
        if not contiguous:
            rep.issues.append(
                Issue(
                    "warning",
                    table,
                    None,
                    "id_gap",
                    f"{idf} 不连续，缺 {missing[:8]}{'…' if len(missing) > 8 else ''}；"
                    "通常是某次事务分配了 ID 但未建成行（无害，但值得查）",
                )
            )

    # ---- counters 与已用 ID 的一致性
    counters = (store.read("counters") or {}).get("counters", {}) or {}
    rep.checked["counters"] = len(counters)
    for kind, field in S.ID_COUNTERS.items():
        # 从 ID_COUNTERS 反查表名，而不是写死一张映射 —— 否则每新增一张表都要改这里，
        # 忘了改就会在 verify 里 KeyError（新增 research_questions/analysis_reports 时正是如此）。
        table = next((t for t, sp in S.TABLES.items() if sp["id_field"] == field), None)
        if table is None:
            continue
        used = [int(r[field]) for r in store.rows(table) if field in r]
        want = (max(used) + 1) if used else 0
        got = int(counters.get(kind, 0))
        if got < want:
            rep.issues.append(
                Issue(
                    "error",
                    "counters",
                    kind,
                    "counter_behind",
                    f"{kind} 计数器为 {got}，但表里已用到 {want - 1}；继续分配会**撞号**。"
                    "处理：把 counters.json 的该值改为 max(已用)+1，或 `agentflow rebuild`。",
                )
            )
        if got > MAX_ID + 1:
            rep.issues.append(Issue("error", "counters", kind, "counter_overflow", f"{kind} 计数器 {got} 超出 4 位空间"))

    # ---- 请求 ↔ 文献 双向可追溯
    for r in requests:
        rid = r.get("request_id")
        for lid in r.get("result_lit_ids") or []:
            if lid not in lit_by_id:
                rep.issues.append(
                    Issue("error", "search_requests", rid, "dangling_lit_ref",
                          f"result_lit_ids 含不存在的文献 {lid}")
                )
        # ⚠️ **这条检查必须与 schema 的规则一致，否则它就是一个假警报源。**
        #
        # 原实现是"`done=true` 且既无 `result_lit_ids` 也无 `last_error` ⇒ error"。
        # 但 `outcome="no_results"`（搜索正常执行、确实没有命中）**本来就是一个
        # 有效的终局**：它没有文献、也没有错误，而 `schema.SearchRequest.validate`
        # 明确允许这种组合（见 `SEARCH_OUTCOMES` 的说明："no_results —— 搜索正常
        # 执行但确实没有命中（这是一个**有效结论**）"）。
        #
        # 后果实测：一条 `outcome="no_results"` 的请求（A 在无检索后端时如实登记）
        # 让 `verify` 报 error —— 而"假报警比不校验更糟，因为它会训练人忽略告警"。
        # 这正是 FC-11（校验器与写入方必须共享同一份规则）的教科书形态。
        #
        # 修法：**只在 schema 判不出语义的那一种情况下报**——`outcome` 缺失
        # （历史数据）且既无文献也无错误，此时"跑过了"与"空转"确实无法区分。
        # 其余情形交由 `schema.SearchRequest.validate` 负责（它在写表时已经跑过）。
        if r.get("done") and r.get("outcome") is None \
                and not (r.get("result_lit_ids") or r.get("last_error")):
            rep.issues.append(
                Issue("error", "search_requests", rid, "done_without_result",
                      "done=true、outcome 缺失、且既无 result_lit_ids 也无 last_error —— "
                      "无法判断是真的搜索过还是空转。请补 outcome（ok/no_results/search_failed/gave_up）")
            )
    for l in literature:
        lid = l.get("lit_id")
        for rid in l.get("source_request_ids") or []:
            if not any(x.get("request_id") == rid for x in requests):
                rep.issues.append(
                    Issue("warning", "literature", lid, "unknown_request_ref",
                          f"source_request_ids 指向未知请求 {rid}")
                )

    # ---- 文献：文件是否真的在
    for l in literature:
        lid = l.get("lit_id")
        p = l.get("path")
        dl = l.get("download") or {}
        if p:
            try:
                ap = store.library_path(p)
            except Exception as e:
                rep.issues.append(Issue("error", "literature", lid, "path_escape", str(e)))
                continue
            if ap is None or not ap.exists():
                rep.issues.append(
                    Issue("error", "literature", lid, "file_missing",
                          f"表里登记了 path={p} 但文件不存在（B 会跳过它）")
                )
        elif dl.get("status") == "ok":
            rep.issues.append(
                Issue("warning", "literature", lid, "ok_without_path",
                      "download.status=ok 但没有 path，元数据与实际不一致")
            )
        elif dl.get("status") == "content_mismatch":
            # 缺陷 #8 的契约：检测到内容类型不符时，**字节必须留作证据**。
            # 丢了文件就再也无法回答"对方到底返回了什么"，而那个答案正是修复的依据。
            rep.issues.append(
                Issue("warning", "literature", lid, "mismatch_without_evidence",
                      "download.status=content_mismatch 但没有 path —— 证据字节没被保留，"
                      "事后无法核查对方返回了什么（缺陷 #8 的契约要求保留）")
            )

    # ---- 关系
    for r in relations:
        rid = r.get("relation_id")
        cids = r.get("concept_ids") or []
        if len(cids) < 2:
            rep.issues.append(Issue("error", "relations", rid, "too_few_concepts", f"概念组只有 {len(cids)} 个"))
        if cids != sorted(set(cids)):
            rep.issues.append(Issue("error", "relations", rid, "unsorted_concepts", f"concept_ids 未升序去重：{cids}"))
        for c in cids:
            if c not in con_by_id:
                rep.issues.append(Issue("error", "relations", rid, "dangling_concept", f"引用了不存在的概念 {c}"))
        if r.get("concept_group_key") != T.concept_group_key(cids):
            rep.issues.append(
                Issue("error", "relations", rid, "stale_group_key",
                      f"concept_group_key={r.get('concept_group_key')!r} 与 concept_ids 派生的 "
                      f"{T.concept_group_key(cids)!r} 不一致（判重会失效）")
            )
        lid = r.get("lit_id")
        if lid not in lit_by_id:
            rep.issues.append(Issue("error", "relations", rid, "dangling_lit", f"引用了不存在的文献 {lid}"))
        else:
            # 需求的因果顺序：只有处理过的文献才可能产出关系
            if not lit_by_id[lid].get("processed"):
                rep.issues.append(
                    Issue("error", "relations", rid, "lit_not_processed",
                          f"文献 {lid} 的 processed=false，但它已经有了关系（违反 §2.4 的写入顺序）")
                )
        if r.get("duplicate_of") and r["duplicate_of"] not in rel_by_id:
            rep.issues.append(Issue("warning", "relations", rid, "dangling_duplicate_of",
                                    f"duplicate_of 指向不存在的关系 {r['duplicate_of']}"))
        pr = r.get("page_range") or {}
        if pr.get("start") is not None and pr.get("end") is not None and pr["start"] > pr["end"]:
            rep.issues.append(Issue("error", "relations", rid, "bad_page_range", f"页码 start>end：{pr}"))

    # ---- 关系去重自检：同一概念组内不应存在两条 quote_normalized 相同的 active 关系
    by_group: dict[str, list[dict]] = {}
    for r in relations:
        if r.get("status") == "rejected":
            continue
        by_group.setdefault(r.get("concept_group_key", ""), []).append(r)
    for gk, rows in by_group.items():
        seen: dict[str, str] = {}
        for r in rows:
            q = r.get("quote_normalized") or T.normalize_for_quote(r.get("quote", ""))
            if not q:
                continue
            if q in seen:
                rep.issues.append(
                    Issue("error", "relations", r.get("relation_id"), "duplicate_quote",
                          f"与 {seen[q]} 在同一概念组 {gk} 内有完全相同的引文（判重漏了）")
                )
            else:
                seen[q] = r.get("relation_id")
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                qa = a.get("quote_normalized") or T.normalize_for_quote(a.get("quote", ""))
                qb = b.get("quote_normalized") or T.normalize_for_quote(b.get("quote", ""))
                if not qa or not qb or qa == qb:
                    continue
                s = T.similarity(qa, qb)
                if s >= 0.92:
                    rep.issues.append(
                        Issue("warning", "relations", b.get("relation_id"), "near_duplicate",
                              f"与 {a.get('relation_id')} 相似度 {s:.3f} ≥ 0.92 却都被标为 "
                              f"{b.get('status')}/{a.get('status')}（判重阈值配置可能被改动）")
                    )

    # ---- 概念：related_concepts 是否与关系表派生结果一致
    for c in concepts:
        cid = c.get("concept_id")
        related = c.get("related_concepts") or []
        if related != sorted(set(related)):
            rep.issues.append(Issue("error", "concepts", cid, "unsorted_related", f"related_concepts 未升序去重：{related}"))
        if cid in related:
            rep.issues.append(Issue("error", "concepts", cid, "self_related", "related_concepts 含自身"))
        for r in related:
            if r not in con_by_id:
                rep.issues.append(Issue("error", "concepts", cid, "dangling_related", f"related_concepts 含不存在的概念 {r}"))
        want = D.derive_related_concepts(cid, relations, include_suspect=True)
        if related != want:
            rep.issues.append(
                Issue(
                    "warning",
                    "concepts",
                    cid,
                    "related_drift",
                    f"related_concepts 与关系表派生结果不一致：表中 {related}，应为 {want}。"
                    "可用 `agentflow repair --related` 整体重算修复。",
                )
            )

    # ---- C/D 新增表的代号外键（DESIGN-TOOLS.md §8.4）
    # 这两张表全靠 4 位代号互相引用（`origin`、`related_*_ids`、`waiting_request_ids`）。
    # 代号引错是静默的：报告照样生成，只是溯源到不存在的东西。所以必须在校验器里拦住。
    questions = store.rows("research_questions")
    reports = store.rows("analysis_reports")
    req_ids = {r.get("request_id") for r in requests}

    for q in questions:
        qid = q.get("question_id")
        for cid in q.get("related_concept_ids") or []:
            if cid not in con_by_id:
                rep.issues.append(Issue("error", "research_questions", qid, "dangling_concept_ref",
                                        f"related_concept_ids 含不存在的概念 {cid}"))
        for rid in q.get("related_relation_ids") or []:
            if rid not in rel_by_id:
                rep.issues.append(Issue("error", "research_questions", qid, "dangling_relation_ref",
                                        f"related_relation_ids 含不存在的关系 {rid}"))
        for lid in q.get("evidence_lit_ids") or []:
            if lid not in lit_by_id:
                rep.issues.append(Issue("error", "research_questions", qid, "dangling_lit_ref",
                                        f"evidence_lit_ids 含不存在的文献 {lid}"))
        for rid in q.get("waiting_request_ids") or []:
            if rid not in req_ids:
                rep.issues.append(Issue("error", "research_questions", qid, "dangling_request_ref",
                                        f"waiting_request_ids 含不存在的请求 {rid}"))
        # 状态与等待集的一致性（schema 只保证"needs_evidence 必须有等待集"，
        # 这里反向检查"已完成的问题不该还挂着等待项"）
        if q.get("status") in ("answered", "dropped") and q.get("waiting_request_ids"):
            rep.issues.append(Issue("warning", "research_questions", qid, "stale_waiting",
                                    f"status={q.get('status')} 却仍挂着 waiting_request_ids="
                                    f"{q.get('waiting_request_ids')}（应清空，否则 poll 会永远等下去）"))

    for ar in reports:
        arid = ar.get("report_id")
        mp = ar.get("markdown_path")
        if mp:
            p = store.root / mp
            if not p.exists():
                rep.issues.append(Issue("warning", "analysis_reports", arid, "report_file_missing",
                                        f"登记了 markdown_path={mp} 但文件不存在"))

    # ---- E/F/G/H 新增表的交叉引用（同样是"悬空引用"检查的一部分）
    #
    # 为什么每个新表都要在这里过一遍：`schema.py` 的行校验只能保证**本行内部**自洽
    # （字段非空、枚举合法、交叉字段一致），它**看不到别的表**。
    # "这个 lit_id 真的存在吗"这种问题只有在这里才可能被发现 —— 而它正是
    # "依赖集不闭合"的技术形态。
    experiments = store.rows("experiments")
    plans = store.rows("attack_plans")
    documents = store.rows("documents")
    dependencies = store.rows("dependencies")
    findings = store.rows("review_findings")

    exp_by_id = {r["experiment_id"]: r for r in experiments}
    doc_by_id = {r["doc_id"]: r for r in documents}
    # FC-24：稿件可以引评测结果，所以它的索引要在稿件检查之前就绪
    eval_by_id = {r["eval_id"]: r for r in store.rows("eval_results")}
    q_id_set = {q.get("question_id") for q in questions}

    for e in experiments:
        eid = e.get("experiment_id")
        qid = e.get("for_question_id")
        if qid and qid not in q_id_set:
            rep.issues.append(Issue("error", "experiments", eid, "dangling_question_ref",
                                    f"for_question_id 指向不存在的研究问题 {qid}"))
        # FC-22 的**第二道**闸：schema 已在写入时拒绝"计算类称 proof"，
        # 这里再核一遍表里的存量数据（历史数据、手工改过的数据都在射程内）。
        if e.get("evidence_kind") == "proof" and e.get("method") != "formal":
            rep.issues.append(Issue("error", "experiments", eid, "evidence_kind_overclaim",
                                    f"method={e.get('method')!r} 却记录 evidence_kind='proof'。"
                                    "数值/符号/穷举都只是交叉验证，不构成证明（FC-22）"))
        if e.get("code_path") and not str(e.get("code_hash") or "").strip():
            rep.issues.append(Issue("error", "experiments", eid, "unhashed_experiment_code",
                                    "有 code_path 却没有 code_hash：这样的'可复现'只是口号"
                                    "（脚本一改，记录就指向了另一段代码）"))
        if e.get("result") == "refutes" and not e.get("counterexample"):
            rep.issues.append(Issue("error", "experiments", eid, "refutation_without_counterexample",
                                    "result='refutes' 但没给 counterexample ⇒ '证否'不可复核"))

    plan_ids = {r["plan_id"] for r in plans}
    for pl in plans:
        pid = pl.get("plan_id")
        qid = pl.get("for_question_id")
        if qid and qid not in q_id_set:
            rep.issues.append(Issue("error", "attack_plans", pid, "dangling_question_ref",
                                    f"for_question_id 指向不存在的研究问题 {qid}"))
        ppid = pl.get("parent_plan_id")
        if ppid and ppid not in plan_ids:
            rep.issues.append(Issue("error", "attack_plans", pid, "dangling_plan_ref",
                                    f"parent_plan_id 指向不存在的计划 {ppid}"))
        # 子目标引用的实验必须真的存在 —— "有数值支持"这句话必须可核对
        for sg in pl.get("subgoals") or []:
            for xid in list(sg.get("experiment_ids") or []) + list(sg.get("proof_experiment_ids") or []):
                if str(xid) not in exp_by_id:
                    rep.issues.append(Issue("error", "attack_plans", pid, "dangling_experiment_ref",
                                            f"子目标 {sg.get('sid')} 引用了不存在的实验 {xid}"))
        if pl.get("status") == "stalled" and not str(pl.get("best_partial") or "").strip():
            rep.issues.append(Issue("error", "attack_plans", pid, "stalled_without_partial",
                                    "stalled 却没写 best_partial：攻坚停下来了却什么都不交出去"))

    # ---- I12 / FC-23：**依赖闭合检查**（本块是 verify 里最"数学"的一条）
    #
    # 数学上把引用的定理当成自己的定理，会**静默放大结论的适用范围**。
    # 下面这条检查把"我们依赖了一个拿不到的外部结论"变成一条**可查询的事实**，
    # 而不是藏在引文角标里。
    dep_ok = 0
    for d in dependencies:
        did = d.get("dep_id")
        used_by = str(d.get("used_by") or "")
        st = str(d.get("status") or "")
        if st == "closed":
            lid, xeid = d.get("source_lit_id"), d.get("source_experiment_id")
            if lid and lid not in lit_by_id:
                rep.issues.append(Issue("error", "dependencies", did, "dangling_dep",
                                        f"status='closed' 但 source_lit_id={lid} 不在文献表里 ⇒ 空头支票"))
            elif xeid and xeid not in exp_by_id:
                rep.issues.append(Issue("error", "dependencies", did, "dangling_dep",
                                        f"status='closed' 但 source_experiment_id={xeid} 不在实验表里 ⇒ 空头支票"))
            else:
                dep_ok += 1
        elif st == "external_unavailable":
            # ⚠️ 分级（FC-13）：这是"我们**已经知道并记录**了这个前提拿不到" ——
            # 属于**已知边界**，不是谎报 ⇒ warning。
            # 报成 error 会把红灯训练成噪音，于是真正的 error 也会被忽略。
            rep.issues.append(Issue(
                "warning", "dependencies", did, "dangling_dep_external",
                f"{used_by} 依赖的「{str(d.get('label') or '')[:80]}」在本项目可得范围之外："
                f"{str(d.get('status_reason') or '')[:160]}。"
                "**引用该结论时必须一并声明这一前提**",
            ))
        elif st == "dangling":
            rep.issues.append(Issue("error", "dependencies", did, "dangling_dep",
                                    f"{used_by} 的依赖「{str(d.get('label') or '')[:80]}」悬空且未闭合。"
                                    "要么补上来源（closed），要么说明为什么拿不到（external_unavailable）"))
    rep.checked["dependencies_closed"] = dep_ok

    # ---- **依赖的缺陷继承**（来自对本地先例 Danus 的观摩）
    #
    # Danus 的收束点是"让**前提不干净**沿着依赖链传播下去"。我们已经有
    # `dependencies` 表了，缺的只是**让它在前提变脏时说话**。三条检查：
    #
    # 1. `proof` 级断言引用的实验本身不是 `proof` 级 ⇒ error。
    #    这是"证据等级被偷偷升级"的机械形态：断言的等级不能强于它的依据。
    # 2. `status="closed"` 的依赖指向一条 `inconclusive` 的实验 ⇒ error。
    #    "closed" 的意思是"这条依赖有支撑"；一条没跑出结论的实验不是支撑。
    # 3. `proof` 级断言挂在一条**未闭合**（`dangling`/`external_unavailable`）的依赖上 ⇒ error。
    #    这是最要紧的一条：整套框架允许"引用一个拿不到的外部定理"，但**必须限制它的后果** ——
    #    拿不到的前提撑不起 `proof` 级的主张。（若挂的是 `cross_check` 级断言，维持原来的 warning。）
    weaker: list[tuple[str, str, str, str]] = []  # (docid, cid, expid, exp_kind)
    for doc in documents:
        docid = str(doc.get("doc_id") or "")
        for c in doc.get("claims") or []:
            if c.get("evidence_kind") != "proof":
                continue
            cid = str(c.get("claim_id") or "")
            for x in c.get("citations") or []:
                kind, _, ref = str(x).partition(":")
                ref = ref.split("#")[0]
                if kind != "exp":
                    continue
                e = exp_by_id.get(ref)
                if e is not None and str(e.get("evidence_kind")) != "proof":
                    weaker.append((docid, cid, ref, str(e.get("evidence_kind"))))
    for docid, cid, expid, exp_kind in weaker:
        rep.issues.append(Issue(
            "error", "documents", docid, "proof_claim_rests_on_weaker_evidence",
            f"断言 {cid} 声称 evidence_kind='proof'，但它引用的实验 {expid} 只有 "
            f"evidence_kind={exp_kind!r} ⇒ **断言不能强于它的依据**（FC-22）",
        ))

    for d in dependencies:
        if str(d.get("status")) != "closed":
            continue
        did = d.get("dep_id")
        xeid = d.get("source_experiment_id")
        if xeid and str(exp_by_id.get(str(xeid), {}).get("result")) == "inconclusive":
            rep.issues.append(Issue(
                "error", "dependencies", did, "closed_dep_on_inconclusive_experiment",
                f"标为 closed 的依赖指向实验 {xeid}，而该实验的结果是 inconclusive ⇒ "
                "没有结论的实验不能作为已闭合的支撑",
            ))

    for d in dependencies:
        if str(d.get("status")) not in ("dangling", "external_unavailable"):
            continue
        used_by = str(d.get("used_by") or "")
        kind, _, ref = used_by.partition(":")
        if kind != "doc":
            continue
        docid, _, cid = ref.partition("#")
        doc = doc_by_id.get(docid)
        if doc is None or not cid:
            continue
        claim = next((c for c in doc.get("claims") or [] if str(c.get("claim_id")) == cid), None)
        if claim is None:
            continue
        if claim.get("evidence_kind") == "proof":
            rep.issues.append(Issue(
                "error", "dependencies", d.get("dep_id"), "proof_claim_with_unclosed_dependency",
                f"断言 {docid}#{cid} 声称 evidence_kind='proof'，却挂在一条未闭合的依赖上"
                f"（「{str(d.get('label') or '')[:60]}」，status={d.get('status')}）⇒ "
                "**拿不到的前提撑不起 proof 级的主张**。要么把该断言的等级降为 cross_check，"
                "要么补上可得的来源。",
            ))

    # ---- 稿件断言的可追溯性（FC-02）
    #
    # ⚠️ 这里除了"引用存不存在"，还要查**被引用的东西现在还算不算数**。
    #
    # 这一条来自对本地先例 Danus 的观摩：它有明确的**撤回（retraction）语义**，
    # 并强调"撤回会级联"、"没有 revoke 动作时要把撤回面向上暴露"。
    # 我们此前只有 `duplicate_of` / `status="rejected"` 这类**行级**状态，
    # 却**没有一条检查**去问"引用了它的那些结论还站得住吗" ——
    # 于是"关系被判重否决"与"稿件还在拿它当依据"可以长期共存而**没有任何报错**。
    # 这就是撤回不级联的形态：知识被撤回了，依赖它的结论却静默地留在那里。
    rejected_by_id: dict[str, dict] = {}
    suspect_ids: set[str] = set()
    for r in relations:
        rid = str(r.get("relation_id") or "")
        if not rid:
            continue
        st = str(r.get("status") or "active")
        if st == "rejected" or r.get("duplicate_of"):
            rejected_by_id[rid] = r
        elif st == "suspect":
            suspect_ids.add(rid)

    for doc in documents:
        docid = doc.get("doc_id")
        for c in doc.get("claims") or []:
            cid = str(c.get("claim_id") or "")
            cites = c.get("citations") or []
            if not cites:
                rep.issues.append(Issue("error", "documents", docid, "unsupported_claim",
                                        f"断言 {cid} 没有 citations（无引用的断言不允许进入稿件）"))
                continue
            for x in cites:
                kind, _, ref = str(x).partition(":")
                ref = ref.split("#")[0]
                if kind == "rel" and ref not in rel_by_id:
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的关系 {ref}"))
                elif kind == "lit" and ref not in lit_by_id:
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的文献 {ref}"))
                elif kind == "exp" and ref not in exp_by_id:
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的实验 {ref}"))
                elif kind == "eval" and ref not in eval_by_id:
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的评测结果 {ref}"))
                elif kind not in ("rel", "lit", "exp", "eval"):
                    rep.issues.append(Issue("warning", "documents", docid, "unknown_citation_kind",
                                            f"断言 {cid} 的引用 {x!r} 前缀无法识别（应为 rel:/lit:/exp:）"))
                # ---- **撤回级联**：引用了已被否决的关系 ⇒ 结论失去依据
                if kind == "rel" and ref in rejected_by_id:
                    row = rejected_by_id[ref]
                    why = (f"判重（duplicate_of={row.get('duplicate_of')}）"
                           if row.get("duplicate_of") else "status='rejected'")
                    rep.issues.append(Issue(
                        "error", "documents", docid, "citation_to_retracted_relation",
                        f"断言 {cid} 引用了已被否决的关系 {ref}（{why}）⇒ "
                        "该结论的依据已被撤回。**撤回必须级联**：请改引幸存关系，或删掉这条断言。"
                        "（Danus 的做法是把撤回面向上暴露；我们在这里把它变成一条 error）",
                    ))
                elif kind == "rel" and ref in suspect_ids:
                    rep.issues.append(Issue(
                        "warning", "documents", docid, "citation_to_suspect_relation",
                        f"断言 {cid} 引用的关系 {ref} 处于 status='suspect'（依据可疑，未判定）⇒ "
                        "该结论目前只有**未经确认**的依据",
                    ))
            if c.get("evidence_kind") == "cross_check" and not str(c.get("disclaimer") or "").strip():
                rep.issues.append(Issue("error", "documents", docid, "overclaim",
                                        f"断言 {cid} 是 cross_check 却没有 disclaimer（FC-22）"))

    # ---- 研究问题的依据是否也已被撤回（同一类级联，作用在 D 的台账上）
    for q in questions:
        qid = q.get("question_id")
        stale = sorted(str(r) for r in (q.get("related_relation_ids") or []) if str(r) in rejected_by_id)
        if stale:
            rep.issues.append(Issue(
                "warning", "research_questions", qid, "question_based_on_retracted_relation",
                f"该问题的 related_relation_ids 含已被否决的关系 {stale} ⇒ "
                "研究可能建立在已撤回的依据上（需人工确认是否降级/关闭该问题）",
            ))

    # ---- 审校发现（H）
    for f in findings:
        fid = f.get("finding_id")
        doc_row = doc_by_id.get(str(f.get("doc_id")))
        if doc_row is None:
            rep.issues.append(Issue("error", "review_findings", fid, "dangling_doc_ref",
                                    f"finding 指向不存在的稿件 {f.get('doc_id')}"))
        if not str(f.get("evidence") or "").strip():
            rep.issues.append(Issue("error", "review_findings", fid, "finding_without_evidence",
                                    "审校发现没有 evidence —— 审校者的判断也需要证据"))
        if doc_row is not None and str(doc_row.get("status") or "") == "accepted" \
                and str(f.get("level")) == "error" \
                and str(f.get("status")) not in ("fixed", "wontfix", "disputed"):
            rep.issues.append(Issue("error", "review_findings", fid, "accepted_with_open_error",
                                    "稿件已被 accepted，但它还有未处置的 error 级发现"))

    # ---- 主控编队 / 花销 / 评测口径（`tasks` / `usage_ledger` / `eval_results`）
    tasks = store.rows("tasks")
    usage = store.rows("usage_ledger")
    # ---- 幂等键的唯一性（"同一笔账被记了两次"的**唯一**自动防线）
    #
    # 为什么必须新增而不是复用 duplicate_id：重复记账的**两行 usage_id 不同**，
    # 所以按主键数重复永远不响；而 tasks.tokens 与账本汇总是**一起**虚高的，
    # 所以 usage_task_total_mismatch 也不响 —— 它们仍然"相等"，只是相等的是错的数。
    seen_idem: dict[str, str] = {}
    for u in usage:
        k = str(u.get("idem_key") or "").strip()
        if not k:
            continue
        if k in seen_idem:
            rep.issues.append(Issue(
                "error", "usage_ledger", u.get("usage_id"), "duplicate_idem_key",
                f"幂等键 {k} 出现两次（{seen_idem[k]} 与 {u.get('usage_id')}）⇒ "
                "同一笔账被记了两次，花销与预算翻倍",
            ))
        else:
            seen_idem[k] = str(u.get("usage_id"))
    evals = store.rows("eval_results")

    task_by_id = {str(r.get("task_id")): r for r in tasks}
    for r in tasks:
        tid = r.get("task_id")
        pid = r.get("parent_task_id")
        # 父任务必须存在 —— 否则"深度"这条链断了，而深度是判循环与判越权的依据
        if pid is not None and str(pid) not in task_by_id:
            rep.issues.append(Issue("error", "tasks", tid, "dangling_parent_task",
                                    f"parent_task_id={pid} 不在 tasks 表里 ⇒ 召唤链断了"
                                    "（深度/循环判据都依赖这条链）"))
        elif pid is not None:
            p = task_by_id[str(pid)]
            if int(r.get("depth") or 0) != int(p.get("depth") or 0) + 1:
                rep.issues.append(Issue("error", "tasks", tid, "task_depth_discontinuous",
                                        f"depth={r.get('depth')} 但父任务 {pid} 的 depth="
                                        f"{p.get('depth')} ⇒ 子任务深度必须恰为父+1（FC-18 ③）"))
        # 判重键为空 ⇒ 循环检测对它无效
        if not str(r.get("input_key") or "").strip():
            rep.issues.append(Issue("warning", "tasks", tid, "task_without_input_key",
                                    "input_key 为空 ⇒ 这条召唤**无法参与循环检测**"
                                    "（同一 (role, action, input_key) 出现在祖先链上才算循环）"))
        # 僵尸：verify 是离线跑的，所以任何仍在 running 的行都是"没有 end 的 start"
        if str(r.get("status")) == "running":
            rep.issues.append(Issue("warning", "tasks", tid, "task_still_running",
                                    f"status=running（started_at={r.get('started_at')}）—— "
                                    "离线校验时它是一条**没有 end 的 start**。可能是崩溃残留；"
                                    "本项目**不自动续跑**（重跑一个可能已经写了半张表的任务更危险），"
                                    "由人决定是弃掉还是重发"))
        # artifacts 形如 "table:id"，必须真的存在
        for a in r.get("artifacts") or []:
            kind, _, ref = str(a).partition(":")
            target = {"experiments": exp_by_id, "documents": doc_by_id,
                      "literature": lit_by_id, "relations": rel_by_id,
                      "eval_results": eval_by_id, "usage_ledger": {x.get("usage_id"): x for x in usage},
                      "tasks": task_by_id}.get(kind)
            if target is None:
                rep.issues.append(Issue("warning", "tasks", tid, "unknown_artifact_kind",
                                        f"artifacts 里的 {a!r} 前缀无法识别"))
            elif ref not in target:
                rep.issues.append(Issue("error", "tasks", tid, "dangling_task_artifact",
                                        f"artifacts 指向不存在的行：{a!r}"))

    usage_by_task: dict[str, int] = {}
    for u in usage:
        uid = u.get("usage_id")
        tk = u.get("task_id")
        if tk is not None and str(tk) not in task_by_id:
            rep.issues.append(Issue("error", "usage_ledger", uid, "dangling_usage_task",
                                    f"task_id={tk} 不在 tasks 表里 ⇒ 这笔花销挂不到任何一次召唤上"))
        if tk is not None:
            usage_by_task[str(tk)] = usage_by_task.get(str(tk), 0) + int(u.get("tokens_total") or 0)
    for tk, total in sorted(usage_by_task.items()):
        declared = int((task_by_id.get(tk) or {}).get("tokens") or 0)
        if declared != total:
            rep.issues.append(Issue(
                "warning", "tasks", tk, "usage_task_total_mismatch",
                f"tasks.tokens={declared} 与 usage_ledger 汇总的 {total} 不一致 ⇒ "
                "两处对同一次召唤的花销给出了不同的数字（预算判断会按哪一份？）",
            ))
    rep.checked["usage_tokens_total"] = sum(int(u.get("tokens_total") or 0) for u in usage)

    # 同一口径下的同一个数字不该有两个值
    eval_key: dict[tuple, list[dict]] = {}
    for e in evals:
        k = (str(e.get("claim_key")), str(e.get("benchmark")), str(e.get("benchmark_version")),
             str(e.get("split")), int(e.get("k") or 0))
        eval_key.setdefault(k, []).append(e)
    for k, rows in sorted(eval_key.items()):
        vals = {float(r.get("value") or 0.0) for r in rows}
        if len(vals) > 1:
            rep.issues.append(Issue(
                "error", "eval_results", rows[0].get("eval_id"), "eval_duplicate_conflicting",
                f"同一口径 {k} 下出现了互相冲突的值 {sorted(vals)} ⇒ "
                "口径相同却给出不同的数字，至少有一条是错的（FC-24：口径就是数字的一部分）",
            ))

    # ---- FC-24 的**渲染层 gate**：报告里的数字必须能追到一条带完整口径的评测结果
    #
    # 为什么这条检查必须有：FC-24 的判据②是"缺任一字段的数字**不得进入对外报告**"。
    # 而 `EvalResult.validate` 只能在**登记时**保证字段齐全 —— 它管不到
    # **正文里写了一个数字却没引用任何评测记录**这种情况。
    # 而后者才是真正会流出去的形态：报告里一句"pass@1 达到 97%"，
    # 读者无法知道那是 LLM judge 分、还是端到端精确值、还是别人论文的数字。
    #
    # 同一个 miniF2F 数字可以是四件完全不同的事，同对模型在两口径下差 13–30 个百分点
    # （`08-…md` §A.5.5）。**所以"没带口径的数字"与"没有出处的断言"是同一类错误。**
    #
    # 判据写成"出现了基准数字的形态 **且** 没有任何 `eval:` 引用" ⇒ warning。
    # 分级为 warning 而不是 error：正则识别"基准数字"必然有假阳性
    # （正文里的年份、章节号、页码都可能是数字），所以它交付的是**指针**，
    # 而不是缺陷判定 —— 与 linter 的 R006 同一取舍。
    _bench_number = re.compile(r"(pass@\s*\d+|\d+(?:\.\d+)?\s*%|\bSOTA\b|\bstate[- ]of[- ]the[- ]art\b)")
    for doc in documents:
        docid = doc.get("doc_id")
        for c in doc.get("claims") or []:
            cid = str(c.get("claim_id") or "")
            text = str(c.get("text") or "")
            m = _bench_number.search(text)
            if not m:
                continue
            kinds = {str(x).partition(":")[0] for x in (c.get("citations") or [])}
            if "eval" in kinds:
                continue
            rep.issues.append(Issue(
                "warning", "documents", docid, "number_without_eval_scope",
                f"断言 {cid} 的正文里出现了基准数字「{m.group(0)}」，但它**没有引用任何 "
                "`eval:` 评测记录** ⇒ 这个数字的口径（基准/版本/切分/k/去污染/来源）无法追溯。"
                "FC-24：**口径不是补充说明，口径就是那个数字的一部分**。"
                "请补一条 `eval:<id>` 引用，或改写这句话去掉数字",
            ))

    # ---- FC-05：每个数组字段都必须声明是"集合"还是"序列"
    import dataclasses as _dc

    for table, spec in S.TABLES.items():
        row_cls = spec["row"]
        declared = S.array_kinds(table)
        for f in _dc.fields(row_cls):
            if f.type in ("list[str]", "list[dict]", "list[Any]") or str(f.type).startswith("list["):
                if f.name not in declared:
                    rep.issues.append(Issue(
                        "error", table, None, "undeclared_array_field",
                        f"字段 {table}.{f.name} 是数组但没在 schema.ARRAY_FIELD_KINDS 里声明"
                        "是 set 还是 seq。未声明的数组会被默认当成集合 ⇒ **顺序被静默破坏**"
                        "（FC-05 的由来正是'跳序被升序不变量吃掉'）",
                    ))

    # ---- D 的提问台账（模块私有文件，不在 schema 里）
    # `tools/research_tools.py` 刻意把"本问题已经问过 A 什么"记在
    # `data/research_request_ledger.json` 而不是 schema 表里（避免牵动 LOCK_ORDER/rebuild）。
    # 代价是它**不能从 events.jsonl 重建**。既然接受了这个代价，就必须让它**可观测**：
    # 否则台账与主表一旦漂移，D 会重复提问或永远等不到，而没有任何地方会报错。
    ledger_path = store.data / "research_request_ledger.json"
    if ledger_path.exists():
        try:
            led = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            rep.issues.append(Issue("error", "research_request_ledger", None, "ledger_corrupt",
                                    f"台账不是合法 JSON（{e}）；注意它**无法从 events.jsonl 重建**，"
                                    "只能人工修复或删除（删除会退化为'可能重复提问一次'）"))
            led = None
        if isinstance(led, dict):
            q_by_id = {q["question_id"]: q for q in questions}
            for i, row in enumerate(led.get("rows") or []):
                if not isinstance(row, dict):
                    rep.issues.append(Issue("error", "research_request_ledger", None, "ledger_bad_row",
                                            f"第 {i} 行不是对象"))
                    continue
                qid = row.get("question_id")
                if qid and qid not in q_by_id:
                    rep.issues.append(Issue("error", "research_request_ledger", qid, "ledger_dangling_question",
                                            f"台账引用了不存在的研究问题 {qid}"))
                for rid in row.get("request_ids") or row.get("waiting_request_ids") or []:
                    if rid not in req_ids:
                        rep.issues.append(Issue("error", "research_request_ledger", qid, "ledger_dangling_request",
                                                f"台账引用了不存在的请求 {rid}"))
                # 台账说"还在等"，主表却说这个问题的等待集是空的 → 两者漂移
                if row.get("open") and qid in q_by_id:
                    if not q_by_id[qid].get("waiting_request_ids"):
                        rep.issues.append(Issue("warning", "research_request_ledger", qid, "ledger_drift",
                                                "台账认为该问题仍有未完成提问，但 research_questions."
                                                "waiting_request_ids 为空 —— 两者已漂移，D 的去重判断会失准"))

    # ---- 深度：重新打开文献复核引文
    if deep:
        if extract_text is None:
            rep.issues.append(Issue("warning", "relations", None, "deep_unavailable",
                                    "要求 --deep 但未提供 extract_text，跳过引文复核"))
        else:
            doc_cache: dict[str, Any] = {}
            for r in relations:
                rid = r.get("relation_id")
                lid = r.get("lit_id")
                if lid not in lit_by_id:
                    continue
                if lid not in doc_cache:
                    ap = store.library_path(lit_by_id[lid].get("path"))
                    try:
                        doc_cache[lid] = extract_text(ap) if ap and ap.exists() else None
                    except Exception as e:
                        doc_cache[lid] = None
                        rep.issues.append(Issue("warning", "literature", lid, "reextract_failed", str(e)))
                doc = doc_cache[lid]
                if doc is None:
                    continue
                pr = S.PageRange.from_dict(r.get("page_range"))
                chk = check_quote(
                    doc,
                    r.get("quote", ""),
                    pr,
                    widen=quote_widen,
                    allow_fulltext_fallback=allow_fulltext_quote_fallback,
                )
                stored = r.get("quote_verified")
                if chk.verified is not stored:
                    rep.issues.append(
                        Issue("warning", "relations", rid, "quote_state_changed",
                              f"重算引文校验为 {chk.verified}（{chk.reason}），表中记录为 {stored}")
                    )
                if chk.verified is False:
                    # 区分"表里已经承认这条引文不可核实"与"表里说能核实、实际找不到"：
                    #  - 表里 `quote_verified=False` → 这是一个**已知并被记录**的缺陷，
                    #    重算只是**确认**它，不该升级成 error（否则任何刻意保留坏样本的数据集
                    #    都会永远 verify 失败，而 error 应当是"需要动手修的不一致"）。
                    #  - 表里 `quote_verified=True` → 表与现实矛盾，这才是 error（上面那条
                    #    `quote_state_changed` 已经报了，这里再补一条更明确的原因）。
                    level = "warning" if stored is False else "error"
                    code = "quote_known_unverifiable" if stored is False else "quote_not_found"
                    rep.issues.append(
                        Issue(level, "relations", rid, code,
                              f"引文在文献 {lid} 的声明页范围（{pr.label or pr}）内找不到："
                              f"{r.get('quote', '')[:80]!r}…"
                              + ("（表里已记录 quote_verified=false，属已知并承认的缺陷）" if stored is False else ""))
                    )

    return rep
