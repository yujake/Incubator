#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把每个**能落产物的智能体**的标志性产物各落一遍，并逐条查"落地正常吗"。

## 为什么要这一件

业主 2026-10-15：**「重点审查所有能落产物的智能体的产物落地行为是否正常，
建一个 example 文件夹让每个智能体把它能落的标志性产物落一遍。」**

起因是一次真跑：抽取的产出**没回来**（`output_exhausted`：推理把输出预算吃光、
正文 0 字），而盘上看起来只是"B 什么都没抽到"。**"产出丢了"与"没产出"
在台账上同形** —— 那正是这一件要挡的：把"每个角色到底能不能把它的东西落到盘上"
逐条跑出来、逐条查。

## 四条纪律

1. **一分钱不花**：全走确定性路径（不接线模型、显式给 `RuleExtractor`、
   离线检索），不发任何模型调用 —— 业主同日：「我们没有其他预算，
   只有总账的钱的预算」。判据：跑完之后本工作区的 `usage_ledger` 必须是 **0 行**。
2. **走真身**：每个产物都由**它自己的那个声明动作**落，且经 `Conductor.summon`
   那条真路（含准入判据：边、深度、扇出、墙钟）—— 不是脚本替它写文件，
   否则验的是脚本，不是产品。
3. **父代理必须是真有边的那一个**（业主 2026-10-10 裁定第 4 条：主控不许直接
   控制 B/F/V，只能间接由父代理转达）。所以每一步的召唤方从
   `capabilities.ALLOWED_EDGES` 里**现取**，取不到就让这一条判据红 ——
   写死角色名会在权限面变动时静默失效。
4. **落地判据是"该有的东西都在"**：台账**行** + 盘上**文件**（若有）+ 文件**非空**
   + 该动作特有的那一件（例如 H 要的是"稿件状态被它改过"）。少一样就报出来，
   退出码非零。

用法：

    python -B example/land_artifacts.py [--keep]

`--keep` 保留上一次的工作区（缺省重建，保证读数是这一次跑出来的）。
`example/LANDING.md` 是这一件生成的报告（逐条读数 + 判定）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))

WS = HERE / "ws"                      # 工作区（产物都落在这里）

#: 每个角色一件标志性产物。
#:
#: - `by`：**谁能召唤它**（从 `capabilities.ALLOWED_EDGES` 现取，见 `_parent_for`）。
#:   这一格是硬约束，不是装饰：主控没有到 B/F/V 的边。
#: - `table`：该动作该留下的台账行；`None` = 它的产物不在台账里（例如 V 的回执）。
#: - `path`：该动作该落下的盘上文件；`{...}` 按台账现取，不许写死号。
STEPS = (
    ("A", "ingest_local", "文献登记 + 全文入库", "literature", None),
    ("B", "run", "概念与关系（抽取产物）", "relations", None),
    ("C", "hottest", "关系分析报告", "analysis_reports", "reports/{report_id}-hottest.md"),
    ("D", "propose_question", "研究问题一行", "research_questions", None),
    ("E", "run_experiment", "实验行 + 原始输出日志", "experiments",
     "out/experiments/{experiment_id}.log"),
    ("F", "create_plan", "攻坚计划一行", "attack_plans", None),
    ("B", "register_statement", "命题一行", "statements", None),
    ("V", "verify_proof", "逐行走查的回执", None, "verifications/{statement_id}.jsonl"),
    ("G", "build_document", "稿件一行 + 渲染出的正文", "documents", "documents/{doc_id}.md"),
    ("H", "review", "审校：稿件状态被它改过", None, None),
)

#: 两篇夹具文献。**必须有"定义句式 + 同句出现另一个已知概念"**，
#: 否则 `RuleExtractor` 抽不出关系（它是离线基线，只认定义句）——
#: 而"抽不出关系"会让 C 那一步合理地拒绝，于是这条审查测不到 C 的落地。
BOOKS = {
    "group.md": (
        "# 群与交换群\n\n"
        "A group is a set with an associative binary operation and inverses. "
        "An abelian group is a group in which the commutative law holds. "
        "Every subgroup of an abelian group is normal.\n"
    ),
    "ring.md": (
        "# 环与域\n\n"
        "A ring is a set with two operations and additive inverses. "
        "A field is a ring in which every nonzero element has a multiplicative inverse.\n"
    ),
}

#: E 要跑的那个脚本（确定性、秒级、按契约打印 `REPRO_RESULT:` 那一行）。
EXPERIMENT_CODE = (
    "import json\n"
    "ok = all((i % 2 == 0) for i in (0, 2, 4, 6, 8))\n"
    "print('REPRO_RESULT: ' + json.dumps({\n"
    "    'result': 'supports' if ok else 'refutes',\n"
    "    'observations': {'n_checked': 5},\n"
    "    'counterexample': None,\n"
    "    'negation_kind': 'not_proved',\n"
    "}))\n"
)


def _parent_for(role: str) -> str:
    """谁有到它的协作边 —— 从 `ALLOWED_EDGES` 现取（取不到就抛，不猜）。

    为什么必须现取而不是写死"反正是 M"：主控**没有**到 B/F/V/D/E 的边
    （业主 2026-10-10 裁定第 4 条：主控只能间接由父代理转达）。写死 M 会让
    这条审查在"边表变了"时静默变成一串 `forbidden_edge` —— 而那时它会看起来
    像"这些角色的产物落不下来"，diagnosis 完全指错方向。
    """
    from agentflow import capabilities as C

    # 优先主控（顶层编排），否则取第一个能到它的角色：顺序稳定 ⇒ 可复现。
    cands = [by for by, targets in C.ALLOWED_EDGES.items() if role in (targets or ())]
    for prefer in ("M", "A", "D", "B", "H"):
        if prefer in cands:
            return prefer
    if cands:
        return sorted(cands)[0]
    raise RuntimeError(f"没有哪个角色有到 {role} 的边（{role} 在非可召唤表里？）")


def _write_books() -> None:
    books = WS / "books"
    books.mkdir(parents=True, exist_ok=True)
    for name, text in BOOKS.items():
        (books / name).write_text(text, encoding="utf-8")


def _write_experiment_code() -> str:
    p = WS / "code" / "example_parity.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(EXPERIMENT_CODE, encoding="utf-8")
    return "code/example_parity.py"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="每个角色的标志性产物各落一遍（$0）")
    ap.add_argument("--keep", action="store_true", help="保留上一次的工作区")
    args = ap.parse_args(argv)

    from agentflow import manuscripts as MS
    from agentflow import statusreport as SR
    from agentflow.host import wired_conductor
    from agentflow.llm import RuleExtractor
    from agentflow.store import Store

    if WS.exists() and not args.keep:
        shutil.rmtree(WS)
    WS.mkdir(parents=True, exist_ok=True)
    st = Store(WS)
    st.init(force=True)
    _write_books()
    script_rel = _write_experiment_code()

    # 确定性接线：不接线模型（`llm=None`）、抽取器显式给离线基线、
    # 检索走本地书架。**一分钱不花**是这一件的硬约束（见模块 docstring 第 1 条）。
    c = wired_conductor(st, workspace_root=WS, extractor=RuleExtractor())
    seen: list[dict] = []

    def summon(role: str, action: str, params: dict, *, parent_task_id: str | None = None):
        by = _parent_for(role)
        res = c.summon(role, action, params, by=by, parent_task_id=parent_task_id,
                       input_key=f"example:{role}.{action}")
        seen.append({"role": role, "action": action, "by": by,
                     "status": res.status, "outcome": res.outcome,
                     "refusal_reason": res.refusal_reason or "",
                     "detail": str(res.detail or "")[:200], "task_id": res.task_id})
        return res

    # ---- 主线：M → A（登记本地文献）→ A → B（抽取）→ B → C（分析）
    r_a = summon("A", "ingest_local", {"books_dir": "books", "pattern": "*.md"})
    lit_id = ""
    if st.rows("literature"):
        lit_id = str(st.rows("literature")[0].get("lit_id") or "")

    r_b = summon("B", "run", {"max_docs": 4}, parent_task_id=r_a.task_id)

    # 关系存在了 C 才做得成（它 refuse 得有理有据：关系表为空时不出报告）
    r_c = summon("C", "hottest", {"top_n": 5, "request": "示例：最热的五个概念"},
                 parent_task_id=r_b.task_id)

    # ---- M → D（立题 + 研究稿）
    r_d = summon("D", "propose_question", {
        "question": "示例：交换性在有限群里的最小反例是什么？",
        "kind": "gap", "priority": "medium",
        "gap_reason": "示例用：留一行可追溯的研究问题（本趟不花任何模型调用）。"})
    qid = ""
    if st.rows("research_questions"):
        qid = str(st.rows("research_questions")[-1].get("question_id") or "")
    if qid:
        summon("D", "write_report", {"out_path": f"reports/{qid}-research.md"},
               parent_task_id=r_d.task_id)

    # ---- D → E（实验：确定性脚本 + 原始输出落盘）
    r_e = summon("E", "run_experiment", {
        "claim": "前五个偶数都是偶数", "claim_key": "example_even_parity",
        "script_path": script_rel, "method": "numeric"}, parent_task_id=r_d.task_id)

    # ---- D → F（立项：四维预算缺一不可）
    summon("F", "create_plan", {
        "problem": "示例：给交换性找一条可判定的判据",
        "problem_key": "example_commutativity",
        "subgoals": [{"sid": "S1", "text": "写出判据", "owner": "F"}],
        "budget": {"max_rounds": 2, "max_parallel_subgoals": 1,
                   "max_persist_attempts": 2, "max_depth": 1}},
        parent_task_id=r_d.task_id)

    # ---- A → B（登记一条**外部文献里的**命题：出处三件套必须齐）
    r_stmt = summon("B", "register_statement", {
        "statement_full": "设 G 是交换群，则 G 的每个子群都是正规子群。",
        "statement_text": "交换群的子群皆正规",
        "kind": "theorem", "label": "交换群的子群正规性",
        "origin": "external_lit", "source_lit_id": lit_id,
        "page_range": {"start": 1, "end": 1},
        "proof_text": "Proof. 交换群的每个子群都满足 gH = Hg，故正规。",
        "evidence_kind": "cross_check",
        "quote_verified": True,
        "quote_reason": "逐字比对通过（示意用：引文来自本地夹具文献）",
    }, parent_task_id=r_b.task_id)
    stmt_id = ""
    if st.rows("statements"):
        stmt_id = str(st.rows("statements")[-1].get("stmt_id") or "")

    # ---- B → V（逐行走查：回执落 verifications/<命题号>.jsonl）
    if stmt_id:
        summon("V", "verify_proof", {
            "statement_id": stmt_id,
            "proof_text": "Proof. 交换群的每个子群都满足 gH = Hg，故正规。"},
            parent_task_id=r_stmt.task_id)

    # ---- M → G（成稿：一行 documents + 渲染出的正文）
    r_g = summon("G", "build_document", {
        "kind": "survey", "title": "示例：交换性与整除（落地审查用）",
        "claims": [
            {"claim_id": "c1", "section": "一、范围",
             "text": "交换群的每个子群都是正规子群（引自本地夹具文献）。",
             "evidence_kind": "cross_check",
             "citations": [f"lit:{lit_id}"] if lit_id else [],
             "disclaimer": "示例用：证据链只到「本地夹具文献」这一级"},
            {"claim_id": "c2", "section": "二、结论",
             "text": "n(n+1) 恒被 2 整除（由 E 的确定性实验交叉验证）。",
             "evidence_kind": "cross_check", "citations": []},
        ],
        "sections": [{"heading": "一、范围", "body": "本文只是落地审查用的示例。"},
                     {"heading": "二、结论", "body": "两条断言如上。"}]})
    doc_id = ""
    if st.rows("documents"):
        doc_id = str(st.rows("documents")[0].get("doc_id") or "")

    # ---- B → H（审校：它的产物是"稿件状态被改过" + 若干发现）
    status_before = str(st.rows("documents")[0].get("status") or "") if st.rows("documents") else ""
    r_h = None
    if doc_id:
        r_h = summon("H", "review", {"doc_id": doc_id}, parent_task_id=r_b.task_id)
    status_after = str(st.rows("documents")[0].get("status") or "") if st.rows("documents") else ""

    # ---- 共用面：状态报告（M 的那一件）+ 交接手稿
    sr_problem = ""
    try:
        SR.write_status_report(st, WS)
    except Exception as exc:  # noqa: BLE001 —— 落不下来要如实报，不许吞
        sr_problem = f"{type(exc).__name__}: {exc}"
    ms_problem = ""
    try:
        MS.write(WS, sender="B", recipient="D", title="示例交接",
                 summary="示例：把这一条的结论交给 D", body="示例正文。", refs=[])
    except Exception as exc:  # noqa: BLE001
        ms_problem = f"{type(exc).__name__}: {exc}"

    # =====================================================================
    # 逐条查"落地正常吗"
    # =====================================================================
    ctx = {
        "report_id": str(st.rows("analysis_reports")[0]["report_id"])
        if st.rows("analysis_reports") else "",
        "experiment_id": str(st.rows("experiments")[0]["experiment_id"])
        if st.rows("experiments") else "",
        "doc_id": doc_id,
        "statement_id": stmt_id,
        "question_id": qid,
    }

    def _size(p: Path | None) -> int:
        return p.stat().st_size if (p is not None and p.is_file()) else 0

    def _rel_path(rel: str | None) -> Path | None:
        if not rel:
            return None
        try:
            return WS / rel.format(**ctx)
        except KeyError:
            return None

    results: list[dict] = []
    for role, action, label, table, rel in STEPS:
        n = len(st.rows(table)) if table else 0
        p = _rel_path(rel)
        exists = bool(p is not None and p.is_file())
        size = _size(p)
        extra = ""
        if action == "review":
            # H 的判据不是"有多少条发现"（干净的稿子**本该**零发现），
            # 而是"它真的动了这份稿件的状态" —— 那是它唯一的写权之一。
            changed = bool(status_after) and status_after != status_before
            ok = changed
            extra = f"{status_before} → {status_after or '(没读回)'}"
            if not ok:
                extra += f"（review 返回：{json.dumps(r_h or {}, ensure_ascii=False)[:160]}）"
        else:
            ok = (n > 0 if table else True) and (exists and size > 0 if rel else True)
        results.append({"role": role, "action": action, "label": label,
                        "table": table or "", "rows": n if table else None,
                        "path": (str(p.relative_to(WS)).replace("\\", "/") if exists and p else ""),
                        "bytes": size, "ok": ok, "extra": extra})

    # 共用面（不在 STEPS 里，因为它们的落点不是"某个角色的某个动作"）
    sr = sorted((WS / "out" / "review").glob("STATUS-*.md")) if (WS / "out" / "review").is_dir() else []
    srj = sorted((WS / "out" / "review").glob("STATUS-*.json")) if (WS / "out" / "review").is_dir() else []
    hp = MS.handoffs_path(WS)
    shared = (
        ("状态报告（md）", sr[-1] if sr else None, sr_problem),
        ("状态报告（json）", srj[-1] if srj else None, sr_problem),
        ("交接手稿", hp if Path(hp).is_file() else None, ms_problem),
    )
    for label, p, problem in shared:
        size = _size(p)
        results.append({"role": "共用", "action": label, "label": label, "table": "",
                        "rows": None,
                        "path": (str(Path(p).relative_to(WS)).replace("\\", "/") if p else ""),
                        "bytes": size, "ok": bool(p) and size > 0, "extra": problem})

    ledger_rows = len(st.rows("usage_ledger"))
    spent = sum(float(r.get("usd") or 0) for r in st.rows("usage_ledger"))

    # ---- 写报告
    bad = [r for r in results if not r["ok"]]
    refused = [s for s in seen if s["outcome"] != "ok"]
    lines = [
        "# 每个智能体的标志性产物 —— 落地审查（$0）",
        "",
        "这一份由 `example/land_artifacts.py` 生成：**每个角色用它自己的声明动作**"
        "把标志性产物落一遍（经 `Conductor.summon` 那条真路，含边/深度/扇出准入），"
        "再逐条查「台账行 + 盘上文件 + 文件非空 + 该动作特有的那一件」。",
        "",
        f"- 工作区：`example/ws/`（可重跑：`python -B example/land_artifacts.py`）",
        f"- 模型调用：**0 次**（不接线模型 + `RuleExtractor`）；"
        f"`usage_ledger` **{ledger_rows} 行** / **${spent:.6f}**",
        f"- 判定：{'**全部落成**' if not bad else f'**{len(bad)} 条没落成**'}",
        "",
        "| 角色 | 动作 | 标志性产物 | 台账 | 盘上文件 | 字节 | 判定 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['role']} | `{r['action']}` | {r['label']} | "
            f"{r['rows'] if r['rows'] is not None else '—'} | "
            f"{'`' + r['path'] + '`' if r['path'] else '—'} | "
            f"{r['bytes'] or '—'} | {'✅' if r['ok'] else '❌'} |")
    lines += [
        "",
        "## 十次召唤的结局（`summon` 的返回值，逐条）",
        "",
        "| 角色 | 动作 | 召唤方 | status | outcome | 拒绝理由 |",
        "|---|---|---|---|---|---|",
    ]
    for s in seen:
        lines.append(f"| {s['role']} | `{s['action']}` | {s['by']} | {s['status']} | "
                     f"{s['outcome']} | {s['refusal_reason'] or '—'} |")
    if refused:
        lines += ["", "> 结局不是 `ok` 的那几条，原文如下：", ""]
        for s in refused:
            lines.append(f"- `{s['role']}.{s['action']}`（召唤方 {s['by']}）："
                         f"{s['outcome']} / {s['refusal_reason'] or '无理由'} — {s['detail']}")
    lines += ["", "## 读数明细（机器可复核）", "", "```json",
              json.dumps({"steps": results, "summons": seen,
                          "spent_usd": spent, "ledger_rows": ledger_rows,
                          "status_before": status_before, "status_after": status_after},
                         ensure_ascii=False, indent=1), "```", ""]
    (HERE / "LANDING.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")

    for r in results:
        print(f"  [{'OK ' if r['ok'] else 'MISS'}] {r['role']}.{r['action']:16s} "
              f"{r['label'][:20]:22s} 行={'-' if r['rows'] is None else r['rows']:>2} "
              f"{(r['path'] or '-'):42s} {r['bytes']:>7}B {r['extra']}")
    for s in refused:
        print(f"  拒绝：{s['role']}.{s['action']}（{s['by']}→）"
              f"{s['outcome']}/{s['refusal_reason']}：{s['detail'][:90]}")
    print(f"\n  花销：{ledger_rows} 行 / ${spent:.6f}（必须为 0 行）")
    print(f"  报告：{HERE / 'LANDING.md'}")
    if bad or ledger_rows:
        print(f"\n  ⇒ {len(bad)} 条没落成、{ledger_rows} 行账，退出码 1")
        return 1
    print("\n  ⇒ 全部落成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
