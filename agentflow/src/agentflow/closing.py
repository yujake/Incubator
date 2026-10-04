# -*- coding: utf-8 -*-
"""收工门（`draft/37` §16 P3）：把"能不能交"从一句判断变成五条各自能造红的读数。

## 为什么需要一个门（而不是让 M 自己总结一句"我觉得可以交了"）

真机读数里最贵的一类失败不是"做错了"，而是"做完了"与"能交"被当成同一件事：
包是旧的（锚 `drifted`）、有一条依赖还挂着争议、承重的那条结论只有数值支持却写着
"已证明"、报告缺了三节、还有一个问题在等用户回答 —— 这些每一条都能被机器判，
而它们混在一段总结里就只剩一句"基本完成"。

## 各条（`DEFAULT_CHECKS`）+ 三态

| 检查 | 判什么 |
|---|---|
| `anchor` | 渲染锚必须 `consistent`（`renderanchor.check_package` 的同一份实现） |
| `contradictions` | 没有未裁决的矛盾：`dependencies.status ∈ {disputed, refuted}`、
|  | `statements.status = disputed`、稿件 `status = unresolved_review` |
| `load_bearing` | 承重结论（正文里 `evidence_kind="proof"` 的断言）必须有 T3（形式化）或已降档 |
| `report_shape` | 报告九节齐全（§14.4）+ "我们补的/原文的"分栏 + 附件三件套 |
| `user_pending` | 没有还在等用户回答的问题（有 ⇒ 必须停在"等待用户"，不许续跑） |
| `substance` | 实质产出：`documents` / `relations` / `experiments` / `review_findings` / `statements` 至少一张非空（全 0 ⇒ 不许报「可交付」；`tasks`/`usage_ledger` 不算 —— 派过活、花过钱可以在什么都没产出时也非空） |

三态纪律：每条给出 `pass` / `fail` / `unknown`，`unknown` 不是通过
（"没查成"与"查过了没问题"必须分得开）。`can_close` 只在每一条都 `pass` 时为真。

## 每一条都能单独造红

判据见 `tests/test_closing_gate.py`：每条各一条负控（把这一条弄坏 ⇒ 它单独红、
其余各条仍然绿），外加一条反真空（好数据必须全绿）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import renderanchor as RA
from . import userio as U

#: 检查的名字（顺序就是报告里的顺序）。
#:
#: 2026-10-03（`draft/37` §86）加了第六条 `substance`：T1 实测里
#: `documents`/`statements`/`relations`/`experiments`/`review_findings` 全是 0，
#: 而前五条全过、`can_close=true`、报告写着「可交付」—— 五格里没有一格问
#:「这一趟到底产出了什么」。这不是新判据，是把已有的三态纪律补到它该管的地方：
#: 「没做」不许读成「没问题」。
DEFAULT_CHECKS: tuple[str, ...] = (
    "anchor", "contradictions", "load_bearing", "report_shape", "user_pending", "substance",
    "acceptance",
)

#: 「实质产出」那一格认的表：至少一张非空 ⇒ 这一趟真的产出了东西。
#:
#: 为什么是这五张：它们分别对应「稿件 / 概念关系 / 实验证据 / 审校发现 / 命题台账」——
#: 一份 review 交付至少要在其中一格留下痕迹。`tasks` / `usage_ledger` 刻意不算：
#: 它们记的是"派过活、花过钱"，而那两件事恰恰可以在什么都没产出时也非空
#: （T1 就是 30 行 tasks、0 行产出）。
SUBSTANCE_TABLES: tuple[str, ...] = ("documents", "relations", "experiments",
                                      "review_findings", "statements")

#: 「这一趟的验收表里，机器可判的那几行」落在哪张文件上（项目根相对）。
#:
#: ## 为什么需要这一格（`draft/37` §94 的真机读数）
#:
#: T1 第 7、8 趟：任务原文点名的那两条腿（逐字核验引文、形式化验证）那一趟都没落台账，
#: 而收工门六格全过、`can_close=true` —— `substance` 只问"五张表里有没有非空的"，
#: 而那一趟 `statements`/`literature` 是 0、`documents` 与 `experiments` 非空，
#: 于是"缺了两条腿"被读成了"可交付"。验收表（人给的那张）才是任务口径的来源，
#: 但它此前只被 `conductor.acceptance` 读、从来没有被判。
#:
#: 判据的形式：验收表是人写的散文（"这一行怎么算数"散在读数栏里），散文没法复算；
#: 所以人给的机器可判行另落一份声明文件（JSON），每行一个受控的 `kind` + 阈值。
#: 这一格就是把这些行从台账现算一遍：不满足 ⇒ `fail`（并逐行给出读数）。
ACCEPTANCE_CHECKS_NAME = "out/paper/ACCEPTANCE-CHECKS.json"

#: 机器可判的验收行只有这几档（受控词表）。加一档 = 加一条能被复算的验收口径，
#: 所以它必须在这里逐档实现，不许写成"任意表达式"（那等于让验收表能执行代码）。
LEG_CHECK_KINDS: dict[str, str] = {
    "quote_verified_rows": "台账里带逐字比对记录的命题行数（`statements` 或 `relations` "
                           "里 `quote_verified` 非 null 的行）",
    "proof_experiment_rows": "台账里的 proof 级形式化实验行数（`experiments` 里 "
                             "`method=formal` 且 `evidence_kind=proof` 的行）",
    "reviewed_documents": "被审到有裁决的我方稿件行数（`documents` 里状态被推成 "
                          "accepted/revised 的行，或 `review_rounds >= 1` 的行）",
    "manuscript_edited": "可改的主稿有没有实质改动（`out/paper/main.tex` 与只读基线 "
                         "`source/main.tex` 的 sha256 不同 ⇒ 1，相同 ⇒ 0）",
    "citation_records_vs_bibitems": "逐条核验引文：带比对记录的行数（`statements`/`relations` 里 "
                                    "`quote_verified` 非 null，或 `quote_reason` 非空 —— 后者是"
                                    "三态里的「未查+理由」）要不少于主稿里 `bibitem` 的条数",
    "retrieval_attempts": "盘外引文先检索：真的跑过的检索请求数（`search_requests` 里 `done=True` "
                          "的行）。为什么单列一档：「盘上没有原文」不是终点 —— A 的 "
                          "`search_literature` + `search.download` 能把引文原文查回来"
                          "（2026-10-04 实测：一次查询就登记了 9 行文献，其中就有 Kuchment 那篇、"
                          "带 DOI 10.1090/bull/1528）；先检索，取不回原文才允许写「未查」",
    # ---- 研究类（`draft/38` 的 T2：从零做一轮研究，考察 A/B/D/E/F 与 M 的调度）----
    "research_question_rows": "立起来的研究问题行数（`research_questions`）—— 从零做研究的第一步："
                              "把「要研究什么」写成一行可追踪的问题，而不是散在对话里",
    "analysis_report_rows": "分析报告行数（`analysis_reports`）—— 这一档的**写者是 "
                            "`AgentC.handle`**（`capabilities.py` 逐字登记：analysis_reports 是 "
                            "C 自己的产出登记行），D 只是它的读者（`D.ingest(report)`）。"
                            "别把它当成 D 的交付物（2026-10-04 真机读数：主控为此重试 7 次、"
                            "换实例，最后只能如实记未核到 —— 因为 D 的动作面里没有写这张表的动作）",
    "report_files": "D 写出来的报告文件数 —— D 的动作 `write_report` 只写文件、不落表"
                    "（签名 `write_report(out_path=None) -> str`）；要看它有没有真的产出，"
                    "数这个才是数对了地方。落位取并集：`out/reports/` 与写者自己用的那个"
                    "子目录（`agent_d.reports_subdir`，缺省 `reports`）—— 写者读配置，"
                    "读数就得读同一份配置（2026-10-04 T2 第 1 趟：报告真的写出来了，"
                    "而读数只看一个写死的目录 ⇒ 读到 0 条）",
    "attack_plan_rows": "攻坚计划行数（`attack_plans`）—— F 的交付物：子目标进展与终止原因",
    "numeric_experiment_rows": "数值/计算实验行数（`experiments` 里 `method=numeric`）—— 从零做研究时"
                               "「先算一遍」是最便宜的证据来源（`method=formal` 那一档另有 "
                               "`proof_experiment_rows` 管）",
    "document_literature_citations": "手稿引用的「文献来源」条数（`documents` 各行的 claims 里 "
                                     "`citations` 提到的不同 `lit:` / `rel:` 代号）—— 研究手稿的"
                                     "第一条要求是「知道别人做过什么」：检索回来的文献与提取出的"
                                     "关系必须真的进到稿子里。为什么单列一档（2026-10-04 T2 第 2 趟"
                                     "真机）：那一趟 A 取回 35 条文献、B 整理出 32 条关系，而手稿的"
                                     "三条断言**全部只引 `exp:`**（一条文献都没引）—— 门照样全绿，"
                                     "因为没有任何一行问过这件事。而库里就躺着直接对口的那几篇"
                                     "（`on-edge-girth-regular-graphs-lower-bounds-and-new-families` 等）",
    "claims_supported_by_their_evidence": "手稿的断言与它所引实验的结论**一致**的稿件份数"
                                          "（`documents` 里每一条 claim 都「有据」的稿件算一份）—— "
                                          "「有据」的定义逐条写死：引了 `exp:` 的断言，必须每条被引实验"
                                          "的 `result` 都是 `supports`；或者这条断言本身就是"
                                          "「没得出结论」那一档（`is_negative` 且给了 `negation_kind`）；"
                                          "没引 `exp:` 的断言不参与这一档（文献类断言的诚实性由 B 的"
                                          "逐字核验与 H 判）。为什么单列（2026-10-04 T2 第 3 趟真机）："
                                          "稿子写着「Heawood 图围长 6」，而它引的那条实验行 stdout 逐字"
                                          "是 `\"girth\": 4` 且 `result=inconclusive` —— 门照样全绿："
                                          "没有任何一行问过「断言与它引的证据说的一样吗」",
    "supported_claims": "手稿里**被实验支持**的断言条数（`documents` 各行的 claims 中，"
                        "至少引到一条 `result=supports` 的实验的那些）—— 与上一档是一对："
                        "上一档问「有没有夸大」，这一档问「有没有真东西」。为什么必须有这一档"
                        "（2026-10-04 T2 第 4 趟真机）：那一趟为了满足上一档，把**正面断言也标成**"
                        "`is_negative`（「K4 是 3-正则、围长 3、每条边恰在两个三角形里」被标成"
                        "「没得出结论」）—— 于是上一档过了，而稿子里一条有实验支持的断言都没有。"
                        "这一档要求的是「本轮真的跑出了结论并写进稿子」；跑不出就得如实写缺口 "
                        "（那正是这一档要逼出来的那句实话）",
    # ---- 数学对象的进度（`draft/37` §133：判「数学」，不判「台账厚度」）----
    "conjecture_rows": "可检验的猜想条数（`conjectures` 里 `statement` 与 `testable` 都非空的行）"
                       "—— 为什么单列（2026-10-04 T2 四趟的读数）：`conjectures`/`statements`/"
                       "`dependencies` 三张数学对象表全程 0 行，而 `tasks`/`documents`/`experiments`"
                       "这些流程表塞得满满的（95 任务 / 16 稿 / 22 实验）—— 系统把「该做的动作」"
                       "做了一遍，数学本身一步没走。`testable` 是这一档的关键：给不出可检验形式"
                       "就得落 `needs_evidence` 并写清为什么",
    "statement_rows": "命题台账行数（`statements`）—— 文献里逐字核过的断言（`quote_verified` 非 null）"
                      "与我方派生的断言都记在这张表；它此前也全程 0 行，于是「手稿里的每句话从哪来」"
                      "在台账上没有落点",
    "plan_progress_rows": "真的被推进过的攻坚计划数（`attack_plans` 里 `history` 非空的行）"
                          "—— 立项 ≠ 推进：T2 里 `attack_plans` 有 2 行，`history` 一次都没长过，"
                          "而计划的意义正是「一轮一轮逼近」（子目标进展 + 终止原因）",
    "counterexample_or_proof_rows": "判决性证据行数：`experiments` 里 `evidence_kind=proof` 的行，"
                                    "或 `result=refutes` 且带非空 `counterexample` 的行 —— "
                                    "数学研究的推进只有三种：证明、反例、以及诚实的「还没有」；"
                                    "这一档数的是前两种（没有它们时，交付里应当只有第三种）",
    "search_frontier_rows": "**有界记录的搜索**条数（`experiments` 里 `search_bound` 非空的不同 "
                            "`claim_key` 数）—— 为什么单列（`draft/37` §133 的用户口径："
                            "「数值实验时间长是正常的……后面逐渐发现模式、优化枚举策略才把时间"
                            "压下去」）：慢实验不是问题，**说不清搜到哪儿**才是问题。有了界，"
                            "「这一轮把界往前推到哪」与「同一界有没有更快」才成为可比较的读数",
    "enumeration_optimization_rows": "**枚举策略真的被优化过**的 claim 数（同一个 `claim_key` 上存在"
                                     "两条实验：后一条的界更大而耗时不多于前一条，或界相同而耗时"
                                     "降到 80% 以下）—— 这一档量的就是用户那句「把时间压下去」："
                                     "不是「跑得更久」，而是「同样的活更快、或更大的活同样快」",
    "manuscript_rows": "**交接手稿**份数（`manuscripts/` 下真实存在、文件名能被 "
                       "`<编号>-<谁>to<谁>.md` 认出来的那些）—— 用户口径「传信息就传手稿编号」"
                       "落在盘上的那一份（`draft/37` §134）。为什么单列：T2 第 5 趟这一类"
                       "**一次也没用**（M 写了 26 条 `note`，只活在会话里；收工之后"
                       "「谁把什么交给了谁」在盘上查不到），而手稿是第三方可复核的那条通道",
}

#: 「被审过」这一档认的稿件状态：H 的裁决把 `draft` 推成这几个之一。
#:
#: 为什么不能只看 `review_rounds`（`draft/37` §95 的真机读数）：T1 第 9 趟里
#: `documents/0000` 是 `status=accepted`、`review_rounds=0` —— H 审过并给了裁决，
#: 而"轮次"只在真的改过稿时才会加。按 `review_rounds >= 1` 判会把一次
#: 已经审过且通过的稿件读成"没审过"（判据恒红 ⇒ 谁都不会再信它）。
REVIEWED_DOC_STATUSES: tuple[str, ...] = ("accepted", "revised")

#: 「研究链的四个环节」——从零做研究时，验收表每个环节至少要有一行（`draft/37` §137）。
#:
#: ## 为什么需要这一条（T2 四趟的真机读数，`draft/37` §133）
#:
#: 那一趟的验收表是人（主控 M）自己写的，于是它写的是最容易满足的那几行：
#: 立了问题、检索过、跑过实验、报告更新了 —— 而研究链上真正决定"有没有往前走"的
#: 四件事（猜想、计划推进、文献进稿、留下界）一行都没有。结果：`can_close=true`、
#: 七格全绿，而 `conjectures`/`statements` 0 行、`attack_plans` 0 推进、手稿一条文献没引。
#:
#: 这份覆盖面判据只做一件事：让"没看那一格"变成不可能。它不要求那些读数是正数
#: （0 也是读数：那一行照样要写出来）—— 它要求的是那一行存在。
#: 一个把"猜想 0 条（没有可检验形式）"写进验收表的交付，与一个根本没提猜想的交付，
#: 是完全不同的两件事；后者在这条判据之前没有任何读数能区分。
#: （注意覆盖面与阈值是两件事：写着 0 的那一行仍会按它自己那一档的阈值判不成立 ——
#: 两者都红，但前者留下读数、后者留下一个空环节。）
#:
#: 触发条件只有一条：这个项目里有 `research_questions` 行（= 它是个"研究型"项目）。
#: review 型（T1）不触发 —— 那些项目的验收表是任务书给的 P1–P11，与本判据无关。
RESEARCH_CHAIN_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("立题与检索", ("research_question_rows", "retrieval_attempts")),
    ("算并留下界", ("numeric_experiment_rows", "search_frontier_rows",
                    "enumeration_optimization_rows")),
    ("想（猜想或判决性证据）", ("conjecture_rows", "statement_rows",
                                "counterexample_or_proof_rows")),
    ("交（文献进稿、计划推进）", ("document_literature_citations", "plan_progress_rows",
                                  "supported_claims")),
)


def research_chain_gaps(store: Any, kinds: Iterable[str]) -> dict[str, Any]:
    """研究型项目的验收表覆盖面：四个环节里哪些一行都没有。

    返回 `{"researched", "rows", "groups", "missing", "note"}`：
    `researched=False`（这个项目没有 `research_questions` 行）时 `missing` 恒为空 ——
    这条判据对非研究型项目不说话（不是"通过"，是"不适用"）。
    """
    used = {str(k) for k in kinds}
    try:
        researched = len(list(store.rows("research_questions"))) > 0
    except Exception as exc:  # noqa: BLE001 —— 读不到研究问题表 ⇒ 这一格判不了，由调用方落 unknown
        raise RuntimeError(f"研究问题表读不到：{type(exc).__name__}: {exc}") from exc
    groups: dict[str, list[str]] = {}
    missing: list[str] = []
    for label, members in RESEARCH_CHAIN_GROUPS:
        hit = [k for k in members if k in used]
        groups[label] = hit
        if researched and not hit:
            missing.append(f"{label}（可以写 {' / '.join(members)} 里的任意一档）")
    return {
        "researched": researched,
        "rows": len(used),
        "groups": groups,
        "missing": missing,
        "note": ("研究型项目（有 `research_questions` 行）的验收表要覆盖研究链四个环节，"
                 "每个环节至少一行。覆盖面管的是「那一行在不在」；那一行的读数够不够"
                 "由它自己那一档判（`min` 缺省时按该档的口径，多数是 ≥ 1）—— "
                 "所以删掉一行与写着 0 都会红，但后者留下的是读数，前者留下的是一个空环节。"
                 "非研究型项目不受这一条约束（`researched=false`）。"),
    }



def _leg_reading(store: Any, kind: str, project_root: Path) -> tuple[int, dict[str, Any]]:
    """按受控档位现算一行验收读数 ⇒ `(条数, 明细)`。

    读不到时抛出去，由调用方落成 `unknown`（"问不出来"不许读成"没有"）。
    `project_root` 只有"要读盘上文件"的那几档用得上（台账那几档不看它）。
    """
    if kind == "quote_verified_rows":
        st = store.rows("statements")
        rel = store.rows("relations")
        s_rows = [r for r in st if r.get("quote_verified") is not None]
        r_rows = [r for r in rel if r.get("quote_verified") is not None]
        return len(s_rows) + len(r_rows), {
            "statements": len(s_rows), "relations": len(r_rows),
            "true": sum(1 for r in s_rows + r_rows if r.get("quote_verified") is True),
            "false": sum(1 for r in s_rows + r_rows if r.get("quote_verified") is False),
            "unchecked": sum(1 for r in s_rows + r_rows if r.get("quote_verified") is None),
        }
    if kind == "proof_experiment_rows":
        rows = [r for r in store.rows("experiments")
                if str(r.get("method") or "") == "formal"
                and str(r.get("evidence_kind") or "") == "proof"]
        return len(rows), {"experiments": [str(r.get("experiment_id") or "") for r in rows[:8]]}
    if kind == "reviewed_documents":
        rows = [r for r in store.rows("documents")
                if str(r.get("status") or "") in REVIEWED_DOC_STATUSES
                or int(r.get("review_rounds") or 0) >= 1]
        return len(rows), {"documents": [
            {"doc_id": str(r.get("doc_id") or ""), "status": str(r.get("status") or ""),
             "review_rounds": int(r.get("review_rounds") or 0)} for r in rows[:8]]}
    if kind == "manuscript_edited":
        # 任务原文第一句（"改掉正文里的问题"）的机器可判形式：可改的主稿与只读基线不同。
        # 为什么必须有一档盯它（`draft/37` §96 的真机读数）：第 9 趟三条腿的凭据全齐、
        # 收工门七格全过，而主稿一个字节都没改 —— "引文核过、形式化验过"与
        # "把正文里的问题改掉"是三件事，前两件有判据，第三件当时没有。
        draft = project_root / "out" / "paper" / "main.tex"
        base = project_root / "source" / "main.tex"
        if not draft.is_file():
            raise ValueError(f"可改的主稿不在盘上：{draft} ⇒ 这一档没查成")
        if not base.is_file():
            raise ValueError(f"只读基线不在盘上：{base} ⇒ 这一档没查成（比不出'改没改'）")
        d_sha = RA.file_digest(draft)
        b_sha = RA.file_digest(base)
        same = d_sha == b_sha
        return (0 if same else 1), {
            "manuscript": "out/paper/main.tex", "baseline": "source/main.tex",
            "manuscript_sha256": d_sha, "baseline_sha256": b_sha,
            "manuscript_bytes": draft.stat().st_size, "baseline_bytes": base.stat().st_size,
            "edited": not same,
        }
    if kind == "citation_records_vs_bibitems":
        # 「逐条」的那一档（`draft/37` §103）：把"有没有做过比对"换成"每条 `\bibitem` 都有记录"。
        # 为什么必须按条数比：§102 的第 12 趟只落了一条 `quote_verified=false` 就算满足了 ——
        # 那是"做一条就算"的口子，而任务原文要的是"逐条核验"。
        # 记录认两种：`quote_verified` 非 null（真/假两种比对结论），或 `quote_reason` 非空
        # （三态里的"未查 + 理由" —— 外部原文不在盘上时，这正是诚实的结论）。
        draft = project_root / "out" / "paper" / "main.tex"
        base = project_root / "source" / "main.tex"
        src = draft if draft.is_file() else base
        if not src.is_file():
            raise ValueError(f"主稿与基线都不在盘上（{draft} / {base}）⇒ 数不出 bibitem 条数")
        text = src.read_text(encoding="utf-8", errors="replace")
        bibitems = text.count("\\bibitem")
        rows = list(store.rows("statements")) + list(store.rows("relations"))
        verdict = [r for r in rows if r.get("quote_verified") is not None]
        reasoned = [r for r in rows
                    if r.get("quote_verified") is None and str(r.get("quote_reason") or "").strip()]
        return len(verdict) + len(reasoned), {
            "records": len(verdict) + len(reasoned), "with_verdict": len(verdict),
            "unchecked_with_reason": len(reasoned), "bibitems": bibitems,
            # 这一档的阈值由主稿自己定：每条 `\bibitem` 一条记录。调用方给了 `min`
            # 就用它的（显式优先），没给就按这个 —— 否则"要几条"会退化成缺省的 1，
            # 于是"做一条就算"（那正是 §102 第 12 趟钻过去的那个口子）。
            "implicit_min": bibitems,
            "counted_from": "out/paper/main.tex" if src is draft else "source/main.tex",
            "true": sum(1 for r in verdict if r.get("quote_verified") is True),
            "false": sum(1 for r in verdict if r.get("quote_verified") is False),
        }
    if kind == "manuscript_rows":
        # 交接手稿那一档（`draft/37` §134/§140）：`manuscripts/` 下真实存在的
        # `<编号>-<谁>to<谁>.md` 份数。为什么单列：用户点名要"传信息就传手稿编号"，
        # 而 T2 第 5 趟这一类一次也没用（M 写了 26 条 `note` —— 只活在会话里）。
        # 判据只看盘上的文件（文件名要能被 `manuscripts.NAME_RE` 认出来）：索引不算数。
        from . import manuscripts as MS

        folder = project_root / MS.MANUSCRIPTS_DIR
        files = sorted(p.name for p in folder.glob("*.md")) if folder.is_dir() else []
        good = [n for n in files if MS.parse_name(n)]
        return len(good), {"dir": str(folder), "files": good[:10], "total_files": len(files),
                           "unparsable": [n for n in files if n not in good][:5]}
    if kind == "retrieval_attempts":
        # 「盘外引文先检索」那一档（`draft/37` §105）：用户一句话点破了我的口径 ——
        # "盘上没有就 false？A 不会去查吗"。实测：`A.search_literature("An overview of
        # periodic elliptic operators")` 一次就登记了 9 行文献、含 Kuchment 那篇（带 DOI），
        # 而 A 的工具面里还有 `search.download`。所以"原文不在工作区"不是结论，
        # 它只是"还没去取" —— 这一档就是要求"真的查过"。
        reqs = store.rows("search_requests")
        done = [r for r in reqs if r.get("done") is True]
        lit = store.rows("literature")
        from_provider = [r for r in lit if list(r.get("source_request_ids") or [])]
        downloaded = [r for r in lit
                      if str(r.get("download") or "").strip() not in ("", "{}", "None")]
        return len(done), {
            "search_requests": len(reqs), "done": len(done),
            "from_provider": len(from_provider), "downloaded": len(downloaded),
            "topics": [str(r.get("topic") or "")[:60] for r in done[:8]],
        }
    if kind == "research_question_rows":
        rows = list(store.rows("research_questions"))
        return len(rows), {"research_questions": [
            {"id": str(r.get("question_id") or r.get("id") or ""),
             "status": str(r.get("status") or "")} for r in rows[:8]]}
    if kind == "analysis_report_rows":
        rows = list(store.rows("analysis_reports"))
        return len(rows), {"analysis_reports": [
            {"id": str(r.get("report_id") or r.get("id") or ""),
             "status": str(r.get("status") or "")} for r in rows[:8]]}
    if kind == "attack_plan_rows":
        rows = list(store.rows("attack_plans"))
        return len(rows), {"attack_plans": [
            {"id": str(r.get("plan_id") or r.get("id") or ""),
             "status": str(r.get("status") or "")} for r in rows[:8]]}
    if kind == "report_files":
        # D 的 `write_report` 只写文件（返回路径），不落 `analysis_reports` —— 这一档就数文件。
        #
        # 落位取并集（`draft/37` §118）：写者的缺省落位是 `<工作区>/<reports_subdir>`
        # （`AgentD.__init__` 从 `agent_d.reports_subdir` 取，缺省 `reports`），
        # 而主控显式传 `out_path` 时常见的落点是 `out/reports`。写者读配置，读数就得
        # 读同一份配置 —— 只看一个写死的目录会出现「报告写出来了、读数说 0 条」
        # （T2 第 1 趟实际就是这么读错的，而那一趟报告确实写了 8 次）。
        subs = ["out/reports"]
        cfg_sub = _reports_subdir_of(project_root)
        subs.append(cfg_sub or "reports")
        files: list[Path] = []
        seen: set[str] = set()
        per_dir: dict[str, int] = {}
        for sub in subs:
            d = project_root / sub
            got = sorted(d.glob("*.md")) if d.is_dir() else []
            per_dir[sub] = len(got)
            for p in got:
                key = str(p.resolve())
                if key not in seen:
                    seen.add(key)
                    files.append(p)
        detail: dict[str, Any] = {
            "dirs": per_dir,
            "reports_subdir": cfg_sub or "reports",
            "files": [str(p.relative_to(project_root)).replace("\\", "/") for p in files[:8]],
        }
        if not cfg_sub:
            # 配置在、但读不懂 ⇒ 说清楚"这一档是按缺省落位数出来的"，
            # 而不是让它看起来像"配置说了就是 reports"（三态纪律）。
            detail["note"] = (f"{project_root / 'config.yaml'} 读不懂 ⇒ 按缺省落位 "
                              "reports 数；若写者用的是别的子目录，这一档的读数会偏低")
        return len(files), detail
    if kind == "numeric_experiment_rows":
        rows = [r for r in store.rows("experiments") if str(r.get("method") or "") == "numeric"]
        return len(rows), {"experiments": [str(r.get("experiment_id") or "") for r in rows[:8]]}
    if kind == "document_literature_citations":
        # 「手稿有没有引用文献」那一档（`draft/37` §120）。口径（写清楚，免得下次又问错）：
        # 数 `documents` 各行 claims 的 `citations` 里出现过的「不同」代号，只算
        # `lit:<id>` 与 `rel:<id>`（`exp:` 是自家实验、不是文献；`rel:` 是 B 从文献里
        # 逐字提取出来的关系，按定义带着文献来源）。
        # `lit:0003#p.4` 这种带页码/锚点的写法按同一个文献算一次（取 `#` 之前）。
        lit_ids: set[str] = set()
        rel_ids: set[str] = set()
        per_doc: dict[str, dict[str, Any]] = {}
        for r in store.rows("documents"):
            mine = {"lit": set(), "rel": set()}
            for c in r.get("claims") or []:
                if not isinstance(c, Mapping):
                    continue
                for ref in c.get("citations") or []:
                    raw = str(ref).split("#", 1)[0].strip()
                    if raw.startswith("lit:"):
                        mine["lit"].add(raw)
                    elif raw.startswith("rel:"):
                        mine["rel"].add(raw)
            doc_id = str(r.get("doc_id") or r.get("id") or "")
            per_doc[doc_id] = {"lit": sorted(mine["lit"]), "rel": sorted(mine["rel"])}
            lit_ids |= mine["lit"]
            rel_ids |= mine["rel"]
        return len(lit_ids) + len(rel_ids), {
            "lit_ids": sorted(lit_ids)[:12], "rel_ids": sorted(rel_ids)[:12],
            "lit_count": len(lit_ids), "rel_count": len(rel_ids),
            "documents": per_doc,
            # 三态：库里有多少可以引的东西 —— 让"引了 0 条"与"库里本来就没有"分得开。
            "available": {"literature": len(store.rows("literature")),
                          "relations": len(store.rows("relations"))},
        }
    if kind == "claims_supported_by_their_evidence":
        # 「断言与它引的实验说的一样吗」那一档（`draft/37` §122）。判据逐条写死：
        #   - 引了 `exp:` 的断言 ⇒ 每条被引实验的 `result` 都必须是 `supports`；
        #   - 或者这条断言本身是「没得出结论」那一档（`is_negative` 且 `negation_kind` 非空）
        #     —— 那是「诚实」的形态：它与一条 `inconclusive` 的实验是一致的；
        #   - 没引 `exp:` 的断言（纯文献类）不参与这一档。
        # 计数单位是「稿件份数」（每一条 claim 都「有据」的稿件算一份），因为
        # 「有一句话被夸大了」不是「这份稿子大体没问题」能折过去的。
        exp_by_id = {str(r.get("experiment_id") or ""): r for r in store.rows("experiments")}
        ok_docs: list[str] = []
        per_doc_bad: dict[str, list[dict[str, Any]]] = {}
        for r in store.rows("documents"):
            doc_id = str(r.get("doc_id") or r.get("id") or "")
            bad: list[dict[str, Any]] = []
            for c in r.get("claims") or []:
                if not isinstance(c, Mapping):
                    continue
                exps = [str(x).split("#", 1)[0].strip() for x in (c.get("citations") or [])
                        if str(x).startswith("exp:")]
                if not exps:
                    continue
                if bool(c.get("is_negative")) and str(c.get("negation_kind") or "").strip():
                    continue                      # 已标成「没得出结论」⇒ 与 inconclusive 一致
                for cid in exps:
                    row = exp_by_id.get(cid.split(":", 1)[1])
                    result = str((row or {}).get("result") or "missing")
                    if result != "supports":
                        bad.append({"claim_id": str(c.get("claim_id") or ""),
                                    "experiment": cid, "result": result,
                                    "claim_evidence_kind": str(c.get("evidence_kind") or ""),
                                    "why": ("被引实验不存在" if row is None else
                                            f"被引实验的 result={result}，而这条断言不是在说「没得出结论」")})
            if bad:
                per_doc_bad[doc_id] = bad
            else:
                ok_docs.append(doc_id)
        return len(ok_docs), {
            "documents_ok": sorted(ok_docs),
            "documents_with_overstated_claims": per_doc_bad,
            "note": ("这一档问的是「断言与它引的证据说的一样吗」：引了 inconclusive/refutes 的"
                     "实验却写成正面结论，就是报告里造假；把话说成「没得出结论」"
                     "（is_negative + negation_kind）或让 E 跑出一个真给出 REPRO_RESULT 的实验，"
                     "两条路都算改对了"),
        }
    if kind == "supported_claims":
        # 「本轮有没有真跑出结论并写进稿子」那一档（`draft/37` §126）。与
        # `claims_supported_by_their_evidence` 是一对：那一档罚"夸大"，这一档逼"真东西"。
        # 口径：一条 claim 只要至少引到一条 `result=supports` 的实验就算一条；
        # 读数里同时给出那些实验的 id（"被什么支持的"要能一眼查到）。
        exp_by_id = {str(r.get("experiment_id") or ""): r for r in store.rows("experiments")}
        supported: list[dict[str, Any]] = []
        for r in store.rows("documents"):
            doc_id = str(r.get("doc_id") or r.get("id") or "")
            for c in r.get("claims") or []:
                if not isinstance(c, Mapping):
                    continue
                backing = [str(x).split("#", 1)[0] for x in (c.get("citations") or [])
                           if str(x).startswith("exp:")
                           and str((exp_by_id.get(str(x).split(":", 1)[1]) or {}).get("result")
                                   or "") == "supports"]
                if backing:
                    supported.append({"doc_id": doc_id,
                                      "claim_id": str(c.get("claim_id") or ""),
                                      "experiments": backing,
                                      "evidence_kind": str(c.get("evidence_kind") or "")})
        supports_rows = [str(r.get("experiment_id") or "") for r in exp_by_id.values()
                         if str(r.get("result") or "") == "supports"]
        return len(supported), {
            "supported_claims": supported[:12],
            "experiments_with_result_supports": supports_rows[:12],
            "experiments_total": len(exp_by_id),
            "note": ("这一档逼的是「本轮真的跑出了结论」：脚本要在 stdout 打印 "
                     "`REPRO_RESULT: {\"result\": \"supports\", ...}`（单独一行）那条实验才落 "
                     "`cross_check`，稿子引它才算「有实验支持的断言」。一条都没有时，"
                     "正确的做法是如实写「这一轮没跑出支持性结论」—— 那也意味着这一档不成立"),
        }
    if kind == "conjecture_rows":
        rows = [r for r in store.rows("conjectures")
                if str(r.get("statement") or "").strip()
                and dict(r.get("testable") or {})]
        return len(rows), {"conjectures": [
            {"id": str(r.get("conjecture_id") or ""), "form": str(r.get("form") or ""),
             "status": str(r.get("status") or ""),
             "testable_keys": sorted(str(k) for k in dict(r.get("testable") or {})),
             "known_lit_id": str(r.get("known_lit_id") or "")} for r in rows[:8]],
            "total_conjectures": len(store.rows("conjectures")),
            "note": ("只有 `statement` 与 `testable` 都非空的才算 —— 给不出可检验形式的猜想"
                     "应当落 `needs_evidence`（那是诚实的「还提不出检验办法」，不是这一档的产物）")}
    if kind == "statement_rows":
        rows = list(store.rows("statements"))
        verified = [r for r in rows if r.get("quote_verified") is not None]
        derived = [r for r in rows if str(r.get("derived_from") or "").strip()]
        return len(rows), {"statements": [
            {"id": str(r.get("stmt_id") or ""), "kind": str(r.get("kind") or ""),
             "status": str(r.get("status") or ""),
             "quote_verified": r.get("quote_verified"),
             "from_literature": bool(str(r.get("source_lit_id") or ""))} for r in rows[:8]],
            "with_quote_verdict": len(verified), "derived": len(derived),
            "note": "文献来的要带 `quote_verified`（真/假/未查+理由），我方派生的要在 `derived_from` 里给出处"}
    if kind == "plan_progress_rows":
        rows = list(store.rows("attack_plans"))
        advanced = [r for r in rows if list(r.get("history") or [])]
        return len(advanced), {"plans": [
            {"id": str(r.get("plan_id") or ""), "status": str(r.get("status") or ""),
             "rounds": int(r.get("rounds") or 0),
             "history_len": len(list(r.get("history") or [])),
             "subgoals": len(list(r.get("subgoals") or []))} for r in rows[:8]],
            "total_plans": len(rows),
            "note": "「立项」不算推进：`F.step` 每推进一轮才追加一条 `history`；"
                    "一份从没被推进过的计划只说明问题被记下来了"}
    if kind == "counterexample_or_proof_rows":
        proof = [r for r in store.rows("experiments")
                 if str(r.get("evidence_kind") or "") == "proof"]
        refuted = [r for r in store.rows("experiments")
                   if str(r.get("result") or "") == "refutes"
                   and dict(r.get("counterexample") or {})]
        return len(proof) + len(refuted), {
            "proof_rows": [str(r.get("experiment_id") or "") for r in proof[:8]],
            "counterexample_rows": [str(r.get("experiment_id") or "") for r in refuted[:8]],
            "note": ("数学的推进只有三种：证明、反例、诚实的「还没有」。这一档数前两种；"
                     "一条都没有时，交付里必须明写「本轮没有判决性结论」——"
                     "而不是拿支持性数值当结论")}
    if kind == "search_frontier_rows":
        rows = [r for r in store.rows("experiments") if dict(r.get("search_bound") or {})]
        keys = {str(r.get("claim_key") or "") for r in rows}
        return len(keys), {"claim_keys": sorted(k for k in keys if k)[:12],
                           "with_bound": len(rows), "experiments_total": len(store.rows("experiments")),
                           "note": ("界从哪来：脚本在 `REPRO_RESULT` 里报 `bound`，或调用方显式给 "
                                    "`search_bound`；被超时杀掉的那次也照样有界（`PROGRESS:` 行）")}
    if kind == "enumeration_optimization_rows":
        by_key: dict[str, list[dict[str, Any]]] = {}
        for r in store.rows("experiments"):
            bound = dict(r.get("search_bound") or {})
            if not bound:
                continue
            by_key.setdefault(str(r.get("claim_key") or ""), []).append(r)

        def _size(bound: Mapping[str, Any]) -> float:
            """界的"大小"：取 `n`（最常用）或所有数值键的最大值；没有数值键时按 0 算。"""
            vals = [float(v) for v in bound.values() if isinstance(v, (int, float))]
            return max(vals) if vals else 0.0

        optimized: list[dict[str, Any]] = []
        for key, rows in by_key.items():
            rows = sorted(rows, key=lambda r: str(r.get("created_at") or ""))
            hit = None
            for i, earlier in enumerate(rows):
                for later in rows[i + 1:]:
                    e_rt, l_rt = float(earlier.get("runtime_sec") or 0.0), float(later.get("runtime_sec") or 0.0)
                    if not e_rt or not l_rt:
                        continue
                    if _size(dict(later["search_bound"])) > _size(dict(earlier["search_bound"])) \
                            and l_rt <= e_rt:
                        hit = {"claim_key": key, "kind": "bigger_in_no_more_time",
                               "earlier": str(earlier.get("experiment_id")),
                               "later": str(later.get("experiment_id")),
                               "bound": [dict(earlier["search_bound"]), dict(later["search_bound"])],
                               "sec": [e_rt, l_rt]}
                    elif _size(dict(later["search_bound"])) == _size(dict(earlier["search_bound"])) \
                            and l_rt <= e_rt * 0.8:
                        hit = {"claim_key": key, "kind": "same_bound_faster",
                               "earlier": str(earlier.get("experiment_id")),
                               "later": str(later.get("experiment_id")),
                               "bound": [dict(earlier["search_bound"]), dict(later["search_bound"])],
                               "sec": [e_rt, l_rt]}
                    if hit:
                        break
                if hit:
                    break
            if hit:
                optimized.append(hit)
        return len(optimized), {"optimized": optimized[:8],
                                "claim_keys_with_bounds": len(by_key),
                                "note": ("这一档只认「可比较的推进」：界更大而耗时不多，或界相同而耗时"
                                         "降到 80% 以下。策略名（`observations.strategy`）与成本曲线"
                                         "（`observations.scaling`）是给人看的证据，不进这一档的判据")}
    raise ValueError(f"没有这一档验收行：{kind!r}（受控词表：{tuple(LEG_CHECK_KINDS)}）")


def _check_acceptance(rep: ClosingReport, store: Any, project_dir: str) -> None:
    """验收表的机器可判行（`draft/37` §94）：逐行现算，任一不满足 ⇒ `fail`。

    三态：文件不在 ⇒ `pass` 并在读数里写明"这个项目没有机器可判的验收行"
    （那是"没有这一栏"，不是"没查成"）；文件在但读不懂/有未知档位/台账读不到 ⇒ `unknown`
    （"没查成"）；逐行都满足 ⇒ `pass`。
    """
    if not str(project_dir or "").strip():
        rep.status["acceptance"] = "unknown"
        rep.findings.append(Finding(
            "acceptance", "acceptance_not_checked", "warning",
            "没给项目根 ⇒ 验收表的机器可判行没查成（不是「没有这一条」）",
        ))
        return
    path = Path(resolve_under_workspace(store, project_dir)) / ACCEPTANCE_CHECKS_NAME
    if not path.is_file():
        # 研究型项目不许"没有这一栏"：`draft/37` §137 —— 缺表时收工门无从回答
        # "这一趟的研究链走到哪一步"，而那正是 §133 读出来的那个缺口
        # （表是人自己写的 ⇒ 只写最容易满足的几行）。
        try:
            chain = research_chain_gaps(store, ())
        except RuntimeError as exc:
            rep.status["acceptance"] = "unknown"
            rep.findings.append(Finding(
                "acceptance", "acceptance_chain_unreadable", "warning",
                f"{exc} ⇒ 研究链覆盖面这一格没查成"))
            return
        rep.readings["acceptance"] = {"checks_file": str(path), "rows": [],
                                      "research_chain": chain}
        if chain["researched"]:
            rep.status["acceptance"] = "fail"
            rep.findings.append(Finding(
                "acceptance", "acceptance_missing_for_research", "blocker",
                f"这是个研究型项目（`research_questions` 有行），却没有 "
                f"{ACCEPTANCE_CHECKS_NAME} ⇒ 这一趟没有可复算的验收口径。"
                f"研究链四个环节每个至少一行：{'；'.join(m for m in chain['missing'])}。"
                "读数不够就把那一行如实写出来（写着 0 ⇒ 那一行自己不成立，但读数留下了）；"
                "缺的是那一行，不是那个数"))
        else:
            rep.status["acceptance"] = "pass"
            rep.readings["acceptance"]["note"] = f"这个项目没有 {ACCEPTANCE_CHECKS_NAME}"
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw["checks"] if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise ValueError("顶层必须是数组，或 {'checks': [...]}")
    except Exception as exc:  # noqa: BLE001 —— 读不懂就说读不懂（unknown 不是 pass）
        rep.status["acceptance"] = "unknown"
        rep.findings.append(Finding(
            "acceptance", "acceptance_unreadable", "warning",
            f"机器可判的验收行读不出来（{path}：{type(exc).__name__}: {exc}）⇒ 没查成",
        ))
        return

    out: list[dict[str, Any]] = []
    unmet: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            rep.status["acceptance"] = "unknown"
            rep.findings.append(Finding(
                "acceptance", "acceptance_unreadable", "warning",
                f"验收行必须是对象，收到了 {type(row).__name__} ⇒ 没查成"))
            return
        cid = str(row.get("id") or "")
        kind = str(row.get("kind") or "")
        name = str(row.get("name") or "")
        note = str(row.get("note") or "")
        want_min = int(row.get("min") or 0)     # 0 = 让这一档自己定阈值（见下面的 implicit_min）
        if kind not in LEG_CHECK_KINDS:
            rep.status["acceptance"] = "unknown"
            rep.findings.append(Finding(
                "acceptance", "acceptance_unknown_kind", "warning",
                f"验收行 {cid} 的 kind={kind!r} 不在受控词表 {tuple(LEG_CHECK_KINDS)} 里 "
                "⇒ 这一行没查成（不是「满足了」）"))
            return
        try:
            got, detail = _leg_reading(store, kind, Path(resolve_under_workspace(store, project_dir)))
        except Exception as exc:  # noqa: BLE001 —— 读不到就落 unknown（§94 的 docstring 承诺了，这一轮才补上）
            rep.status["acceptance"] = "unknown"
            rep.findings.append(Finding(
                "acceptance", "acceptance_leg_unreadable", "warning",
                f"验收行 {cid}（{kind}）的读数算不出来（{type(exc).__name__}: {exc}）"
                "⇒ 这一行没查成（不是「不满足」，也不是「满足」）"))
            return
        if not want_min:
            # 调用方没写 `min` ⇒ 用这一档自己算出来的阈值（`citation_records_vs_bibitems`
            # 就是"每条 `\bibitem` 一条记录"）；连它都没有时才是缺省的 1。
            want_min = int(detail.get("implicit_min") or 1)
        out.append({"id": cid, "name": name, "kind": kind, "min": want_min, "got": got,
                    "ok": got >= want_min, "detail": detail})
        if got < want_min:
            unmet.append(f"{cid}（{name or LEG_CHECK_KINDS[kind]}）：{got} 条，"
                         f"要求 ≥ {want_min} 条 —— 读数 {detail}"
                         + (f"；{note}" if note else ""))

    rep.readings["acceptance"] = {"checks_file": str(path), "rows": out}
    # ---- 覆盖面（`draft/37` §137）：研究型项目的验收表要覆盖研究链四个环节。
    # 「0 也是读数」：所以缺的是那一行，不是那个数（写 0 与删掉一行都会红，
    # 但前者留下读数、后者留下一个空环节 —— 两者分开报）。
    try:
        chain = research_chain_gaps(store, [str(r.get("kind") or "") for r in out])
    except RuntimeError as exc:
        rep.status["acceptance"] = "unknown"
        rep.findings.append(Finding(
            "acceptance", "acceptance_chain_unreadable", "warning",
            f"{exc} ⇒ 研究链覆盖面这一格没查成（不是「覆盖齐了」）"))
        return
    rep.readings["acceptance"]["research_chain"] = chain
    if chain["missing"]:
        unmet.append("研究链覆盖面：验收表里一行都没有的环节 —— " + "；".join(chain["missing"]))
    if unmet:
        rep.status["acceptance"] = "fail"
        rep.findings.append(Finding(
            "acceptance", "acceptance_unmet", "blocker",
            "验收表里机器可判的这几行**没满足**（这一趟的交付缺了任务点名的凭据）："
            + "；".join(unmet)
            + "。台账是唯一能复算的地方 —— 把凭据落进台账（不是只写进报告）再收工"))
    else:
        rep.status["acceptance"] = "pass"

#: 「这次调用没有会话身份」——与 `sid=None`（= 读缺省会话）「刻意分开」的两个输入。
#:
#: 为什么必须分开（`draft/37` §63 的真机读数，修法 B）：运行内 `conductor.closing`
#: 报 `user_pending: pass`，而同一次运行外部带 sid 的读数报 `fail` —— 假绿的病因
#: 是工具体按 `sid=None` 走到了 `sessions/<今天>.jsonl`，而那一趟的提问落在
#: `sessions/real11.jsonl` 里。"读缺省会话"是一个「具体且合法」的问题
#: （运维会问："这个工作区今天那段会话在等什么？"），所以 `sid=None` 的语义不改；
#: 缺的是第三个输入："调用方「没有」会话身份，这一格问不出来"。
#: 把它折进 `sid=None` 就会重演同一个假绿 —— 而这次连"读错了文件"都不会有人发现。
NO_SESSION = ""

#: 报告的九节（逐字照 `draft/37` §14.4 的清单）。
REPORT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("一", "任务与范围"),
    ("二", "逐条读数"),
    ("三", "定理与引理清单"),
    ("四", "形式化覆盖"),
    ("五", "引文核验"),
    ("六", "体例与表述"),
    ("七", "我们做的补救"),
    ("八", "未决问题"),
    ("九", "诚实边界"),
)

#: 附件三件套（§16 P3 报告行逐字要求）。
ATTACHMENT_FIELDS: tuple[str, ...] = ("origin=own_result", "依据", "sha")

#: 分栏标记：报告必须把"我们补的"与"原文的"分开写。
SPLIT_MARKERS: tuple[str, ...] = ("我们补的", "原文的")

#: `draft/37` §10.2 的"什么时候必须上 T3"四条，逐条连同它今天的机械形态。
#: 写进门的意思不是"写进文档"，而是"门要能对每一条说出它判得了还是判不了" ——
#: 判不了的那一条必须明确登记为缺口，不许它悄悄消失。
#:
#:   (条件, 今天的机械形态, `load_bearing` 认不认它)
MUST_T3_CONDITIONS: tuple[tuple[str, str, str], ...] = (
    ("①作为定理写进正文",
     "`documents.claims[].evidence_kind == \"proof\"` 的断言必须引到一条 T3 实验"
     "（`method=\"formal\"` + `evidence_kind=\"proof\"` + `verifier_output` 非空）",
     "enforced"),
    ("②有别的结论依赖它",
     "`statements` 里被别人 `derived_from` 引到的 `active` 命题",
     "counted_only"),
    ("③与外部文献冲突",
     "`dependencies.status ∈ {refuted, disputed}` 或 `statements.status = disputed`",
     "enforced_by_contradictions"),
    ("④要进事实库",
     "`statements` 里 `status=\"active\"` 且 `evidence_kind=\"proof\"` 的命题",
     "counted_only"),
)

#: `counted_only` 那两条为什么今天判不了（写下来，免得下一个人以为是忘了）：
#: `statements` 表没有指向实验的字段（P1 的字段表里没有它）⇒
#: "这条命题有没有 T3 背书"在数据面上不可判定：只能数出"有几条承重命题"，
#: 判不了它们各自有没有形式化。补法有两条（都要改 `schema.py` ⇒ 属字段取舍，留给人）：
#: ① 给 `statements` 加一列指向 `experiments`（如 `proof_experiment_id`）；
#: ② 或者让 E 的 T3 实验反过来登记"我背书的是哪条 stmt"。
#: 在补上之前，收工门会对这两条给出 `counted_only` 的读数，
#: 而不是假装它们过了 —— 那正是"没查成不许折成通过"。
MUST_T3_GAP_NOTE = ("statements 表没有指向 experiments 的字段 ⇒ ②④今天只能数"
                    "（承重命题几条 / 降档几条），判不了逐条有没有 T3 背书。"
                    "补法见 closing.MUST_T3_CONDITIONS 上方的注释（要动 schema.py，留给人裁）")


@dataclass(frozen=True)
class Finding:
    """一条把门拦住的读数。`code` 是处置把手（谁该去做什么，见各处的 message）。"""

    check: str
    code: str
    level: str          # "blocker" | "warning"
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """一条拦门读数的可读视图（落档与工具返回共用同一个形状）。"""
        return {"check": self.check, "code": self.code, "level": self.level, "detail": self.detail}


@dataclass
class ClosingReport:
    """各条检查的读数。`status` 每条一个三态值；`findings` 是拦门的原因。"""

    status: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    readings: dict[str, Any] = field(default_factory=dict)

    @property
    def blockers(self) -> list[Finding]:
        """拦门的读数（`warning` 那些只报不拦：它们是"已知边界"，不是谎报）。"""
        return [f for f in self.findings if f.level == "blocker"]

    @property
    def unknowns(self) -> list[str]:
        """没查成的那些检查（不是通过）。"""
        return sorted(k for k, v in self.status.items() if v == "unknown")

    @property
    def failed(self) -> list[str]:
        """查过了、结论是"被拦住"的那些检查。"""
        return sorted(k for k, v in self.status.items() if v == "fail")

    @property
    def can_close(self) -> bool:
        """每条都 `pass` 才为真 —— `unknown` 与 `fail` 都不算通过。"""
        return all(v == "pass" for v in self.status.values()) and not self.blockers

    def to_dict(self) -> dict[str, Any]:
        """整份读数的可读视图（CLI、工具与落档共用同一个形状）。"""
        return {
            "can_close": self.can_close,
            "status": dict(self.status),
            "failed": self.failed,
            "unknowns": self.unknowns,
            "findings": [f.to_dict() for f in self.findings],
            "readings": dict(self.readings),
        }

    def summary(self) -> str:
        """一句话读数（给 CLI 与交付说明用；不许盖过明细）。"""
        if self.can_close:
            return f"收工门：{len(self.status)} 条全过 ⇒ 可交付"
        return (f"收工门：拦住（fail={self.failed or '无'} / unknown={self.unknowns or '无'}）"
                f"；拦门读数 {len(self.blockers)} 条")


# ------------------------------------------------------------------ 各条实现

def resolve_under_workspace(store: Any, given: str) -> str:
    """把"相对工作区"的路径解析成绝对路径（`"."` = 工作区根）。

    ## 为什么必须有它（`draft/37` §60 的真机读数）

    第十趟主控按工具描述传 `project_dir="."` 与 `report_path="out/review/REPORT.md"`
    （描述逐字写的是"相对工作区"），然后撞上一串怪读数：
    `closing` 报"报告不在盘上"（它明明刚写完、`fs.stat` 也确认 6,743 字节）、
    "锚文件读不到"（文件也在盘上），`conductor.acceptance(project_dir=".")`
    还解析到了工作区上一级。它花了 8 步去查这件事（步 27–34），
    最后结论："`project_dir='.'` 被解析到工作区上一级"。

    病因在实现侧：`Path(given)` 是按进程当前目录解析的，而工具的契约是
    "相对工作区" —— 两个口径不一致时，错的读数看起来像"文件不在"。
    处置：在入口处解析一次（`store.root` 为基准），并把绝对路径原样放过。
    """
    raw = str(given or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if path.is_absolute():
        return str(path)
    root = Path(getattr(store, "root", "."))
    return str((root / path).resolve())


def _reports_subdir_of(project_root: Path) -> str:
    """D 把报告写在哪个子目录（`agent_d.reports_subdir`，缺省 `reports`）。

    为什么读数要读配置（`draft/37` §118）：写者（`AgentD.__init__`）就是从这个键取
    落位的。读数若只看一个写死的目录，就会出现"报告真的写出来了、读数说 0 条" ——
    在验收表里那会被读成"任务没做"，而实际是"读数问错了地方"。

    三态：没有配置文件 ⇒ 返回缺省的 `reports`（这是"全用默认值"的正常形态）；
    文件在、但读不懂 ⇒ 返回空串，由调用方把"没读懂"写进读数（不许静默当成默认值）。
    """
    p = project_root / "config.yaml"
    if not p.is_file():
        return "reports"
    try:
        import yaml

        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        got = (doc.get("agent_d") or {}).get("reports_subdir")
    except Exception:  # noqa: BLE001 —— 读不懂是"没查成"，由调用方落成读数里的一句话
        return ""
    return str(got) if got else "reports"


def _has_paper_package(root: Path) -> bool:
    """这个项目根下「有没有论文包的实物」（`draft/37` §117 的判据）。

    为什么不是"`out/paper/` 目录在不在"：人给的验收表按 `ACCEPTANCE_CHECKS_NAME`
    的定义就住在 `out/paper/` 里 ⇒ 任何有机器可判验收行的项目都必然有那个目录，
    "目录在"于是成了恒真信号（本轮预检实测：空白 T2 工作区 `anchor=unknown`、
    `can_close` 永远为假）。

    认的实物（与 `renderanchor` 的四件同一份口径，不另立一套名字）：
    正文 `main.tex` / 编译产物 `main.pdf` / 渲染锚 `RENDER-ANCHOR.json` /
    编译回执 `COMPILE-RECEIPT.json` / 构建历史 `BUILD-HISTORY.jsonl`。
    验收表、说明、`out/reports/*.md` 「不算」 —— 它们是本框架的记账，不是论文。

    三态纪律：这里只回答"要不要查锚"，不回答"锚对不对"——有正文而无锚仍然走
    `check_package` 那条「可操作的 `unknown`」，不许被这里吞掉。
    """
    pkg = root / "out" / "paper"
    if not pkg.is_dir():
        return False
    return any((pkg / name).is_file() for name in
               ("main.tex", "main.pdf", RA.ANCHOR_NAME, RA.RECEIPT_NAME, RA.HISTORY_NAME))


def _check_anchor(rep: ClosingReport, project_dir: str, store: Any) -> None:
    """锚：复用 `renderanchor.check_package`（同一份实现，不另写一个判据）。

    `project_dir` 要的是项目根，不是论文包目录 —— `check_package` 自己会拼
    `out/paper`。这一点原先只有实现知道、措辞全说反了（工具描述与这里的提示语都写
    "论文包所在目录"），2026-10-02 的真机读数就是后果：主控照描述传 `out/paper`，
    工具去找 `out/paper/out/paper/RENDER-ANCHOR.json`，锚那一格变成 `unknown`，
    白花一步（`draft/37` §44.5）。所以现在两件事一起做：
    措辞改成"项目根"，并在找不到锚时把期望的路径形状点名。
    相对路径按工作区根解析（见 `resolve_under_workspace`）。
    """
    if not str(project_dir or "").strip():
        rep.status["anchor"] = "unknown"
        rep.findings.append(Finding(
            "anchor", "anchor_not_checked", "warning",
            "没给项目根（project_dir）⇒ 渲染锚没查成。这是没查成，不是一致 —— "
            "交付前必须指到**项目根**再跑一次（锚在 <项目根>/out/paper/RENDER-ANCHOR.json）",
        ))
        return
    root = Path(resolve_under_workspace(store, project_dir))
    # 只有"像项目根、但确实没有论文包"才算不适用；`out/paper` 这种把论文包目录当项目根传的
    # 情形必须继续走下面那条可操作的 `unknown`（`draft/37` §44.5 的老账，
    # 判据 `test_the_wrong_directory_gets_an_actionable_message` 正守着它）。
    looks_like_paper_dir = root.name == "paper" or (root / "main.tex").is_file()
    if not looks_like_paper_dir and not _has_paper_package(root):
        # `draft/37` §115 + §117：没有论文包的项目（T2 从零研究、T4 检索类测试…）里，
        # 锚这一格是不适用，不是「没查成」—— 否则 `can_close` 永远为假（它要求七格全 pass），
        # 而那类测试根本不该有论文包。
        #
        # §117 把判据从"`out/paper/` 目录在不在"改成"有没有论文包的实物"：验收表
        # （人给的 `out/paper/ACCEPTANCE-*.json|md`）按 `ACCEPTANCE_CHECKS_NAME` 的定义
        # 「就住在 `out/paper/` 里」，于是任何有机器可判验收行的项目都必然有那个目录
        # ——"目录在"于是成了恒真信号，T2 那类工作区永远关不上门（本轮预检实测：
        # 空白 T2 工作区 `anchor=unknown`）。现在只有盘上有正文/锚/编译产物才算论文包：
        # 有正文而无锚 ⇒ 仍然是那条可操作的 `unknown`（§44.5 的老账不丢）。
        rep.status["anchor"] = "pass"
        rep.readings["anchor"] = {"verdict": "not_applicable", "root": str(root),
                                  "note": ("这个项目没有论文包（out/paper 下没有正文/锚/"
                                           "编译产物）⇒ 锚不适用")}
        return
    got = RA.check_package(str(root), store=store)
    verdict = str(got.get("verdict") or "unknown")
    rep.readings["anchor"] = {"verdict": verdict, "dimensions": got.get("dimensions"),
                              "drift": list(got.get("drift") or [])[:10]}
    if verdict == "consistent":
        rep.status["anchor"] = "pass"
    elif verdict == "drifted":
        rep.status["anchor"] = "fail"
        rep.findings.append(Finding(
            "anchor", "anchor_drifted", "blocker",
            f"渲染锚报 drifted：{('；'.join(list(got.get('drift') or [])[:3]))[:200]} ⇒ "
            "包不是库里现在的样子。重渲染 + 重编译，并在**最后一次写台账之后**再核一次",
        ))
    else:
        rep.status["anchor"] = "unknown"
        hint = ""
        if not got.get("anchor_present"):
            # 没找到锚时把"该给哪个目录"说清楚：这是最常见的调用姿势错误
            # （给论文包目录而不是项目根），而原来的错误只说"读不到"。
            expect = Path(str(project_dir)) / "out" / "paper" / RA.ANCHOR_NAME
            hint = (f"；锚要在 {expect} —— 若你给的是论文包目录（…/out/paper），"
                    "请改传**项目根**（check_package 会自己拼 out/paper）")
        rep.findings.append(Finding(
            "anchor", "anchor_unknown", "warning",
            f"渲染锚报 unknown：{('；'.join(list(got.get('problems') or [])[:3]))[:200]} ⇒ "
            "有一维判不了（锚不在 / 回执不在）。这不是一致" + hint,
        ))


def pollution_set(store: Any, stmt_id: str) -> list[str]:
    """一条命题被推翻时跟着倒的那些命题（`draft/37` §9 / R20 的"污染面"）。

    做法是 `statements.derived_from` 上的传递闭包（谁用到我、谁又用到它……），
    不含自身。为什么必须有它：§9 的处置不是"把这一条划掉"就完事 ——
    `draft/37` 的用词是"如果错的是文献，那么压在它上面的结论就不能再算数"，
    而"压在它上面"在数据面上就是这张有向图。

 已知边界（写成读数而不是假装完整）：今天的污染面只覆盖命题之间的
    `derived_from`。正文断言（`documents.claims[].citations`）今天只认 `lit:` / `exp:` /
    `rel:` 三种前缀，没有引用命题的形式 ⇒ "哪几条正文断言压在这条命题上"判不了。
    补法是给 citations 加一种 `stmt:` 前缀（属字段取舍，留给人裁）——
    在补上之前，本函数只对命题层给读数，并把这条边界写进 `readings`。
    """
    rows = {str(s.get("stmt_id")): s for s in (store.rows("statements") if store else [])}
    if stmt_id not in rows:
        return []
    seen: set[str] = set()
    frontier = {stmt_id}
    while frontier:
        nxt: set[str] = set()
        for sid, row in rows.items():
            if sid in seen or sid == stmt_id:
                continue
            if set(str(x) for x in (row.get("derived_from") or [])) & frontier:
                seen.add(sid)
                nxt.add(sid)
        frontier = nxt
    return sorted(seen)


def _check_contradictions(rep: ClosingReport, store: Any) -> None:
    """未裁决的矛盾：三种病因各自一个 code（`draft/37` §8 / R19）+ 污染面（R20）。

    为什么不能只报一句"有矛盾"：三种病因的处置方向完全不同，而代码就是处置把手 ——

    | 病因 | code | 谁去做什么 |
    |---|---|---|
    | 我们读错了文献（下成另一篇） | `contradiction_wrong_paper` | A：重取对的那一篇（`matched="mismatch"` 已在 P2 落成一栏） |
    | 来源本身有争议（两篇文献两说） | `contradiction_disputed_source` | D 追原始证明 → 判不了就 `ask_user`（§8 的裁决闭环） |
    | 我们自己的证明有洞 | `contradiction_own_hole` | D 给可挽救性评估，E 补 T3，或如实降档 |
    | 稿件审校未过（H 的未决项） | `review_unresolved` | G 修订 / H 复审（§14.4 的"未决问题"那一节） |

    前三种正是 §17.1 要求"三种病因各一条负控"的那三条；第四种来自 §14.4
    的报告第九节，单列是因为它的处置是"回稿子"而不是"回证据"。
    """
    if store is None:
        rep.status["contradictions"] = "unknown"
        rep.findings.append(Finding("contradictions", "no_store", "warning",
                                    "没有 store ⇒ 矛盾没查成（不是没有矛盾）"))
        return
    wrong_paper: list[str] = []
    disputed_source: list[str] = []
    own_hole: list[str] = []
    unresolved_review: list[str] = []
    pollution: dict[str, list[str]] = {}
    #: 被证否、且确实有结论压在它上面的那些（§9：压在上面的结论不能再算数）。
    #: 与 `own_hole` 分开：`own_hole` 说的是"我们的 proof 级证明压在不可用的命题上"，
    #: 而这一条不管压在上面的那几条是什么证据等级 —— 只要有人用，就必须处置。
    pollution_items: list[str] = []

    # ---- ① 我们读错了文献：命中校验 mismatch 且已经被消化（P2 的那一栏）
    for row in store.rows("literature"):
        if str(row.get("matched") or "") == "mismatch" and row.get("processed"):
            wrong_paper.append(f"文献 {row.get('lit_id')}"
                               f"（{str(row.get('title') or '')[:40]}）")

    # ---- ② 来源本身有争议 / 被证否：依赖与命题两处
    stmt_status = {str(s.get("stmt_id")): str(s.get("status") or "")
                   for s in store.rows("statements")}
    for row in store.rows("dependencies"):
        st = str(row.get("status") or "")
        if st in ("disputed", "refuted"):
            disputed_source.append(f"依赖 {row.get('dep_id')} status={st}"
                                   f"（{str(row.get('label') or '')[:40]}）")
    for row in store.rows("statements"):
        st = str(row.get("status") or "")
        if st == "disputed":
            disputed_source.append(f"命题 {row.get('stmt_id')} status=disputed"
                                   f"（{str(row.get('label') or '')[:40]}）")
        if st in ("refuted", "disputed"):
            # ③ 我们自己的证明压在一条不可用的命题上 ⇒ 洞在我们这边
            for other in store.rows("statements"):
                if str(other.get("status") or "") != "active":
                    continue
                if str(other.get("evidence_kind") or "") != "proof":
                    continue
                if str(row.get("stmt_id")) in {str(x) for x in (other.get("derived_from") or [])}:
                    own_hole.append(f"命题 {other.get('stmt_id')} 的证明压在 {row.get('stmt_id')}"
                                    f"（status={st}）上")
            if st == "refuted":
                downstream = pollution_set(store, str(row.get("stmt_id")))
                pollution[str(row.get("stmt_id"))] = downstream
                if downstream:
                    pollution_items.append(f"命题 {row.get('stmt_id')} 被证否 ⇒ "
                                           f"{downstream} 跟着倒")

    for row in store.rows("documents"):
        if str(row.get("status") or "") == "unresolved_review":
            unresolved_review.append(f"稿件 {row.get('doc_id')}")

    rep.readings["contradictions"] = {
        "wrong_paper": wrong_paper,
        "disputed_source": disputed_source,
        "own_hole": own_hole,
        "review_unresolved": unresolved_review,
        "pollution": pollution,
        "pollution_scope": "只覆盖命题之间的 derived_from；正文断言没有引用命题的形式"
                           "（citations 只认 lit:/exp:/rel:）⇒ 断言级污染面今天判不了",
    }
    causes: tuple[tuple[str, str, str, list[str]], ...] = (
        ("contradiction_wrong_paper", "blocker", "我们读错了文献（下成了另一篇）", wrong_paper),
        ("contradiction_disputed_source", "blocker", "来源本身有争议或已被证否", disputed_source),
        ("contradiction_own_hole", "blocker", "我们自己的证明压在不可用的命题上", own_hole),
        ("contradiction_pollution", "blocker",
         "污染面：被证否的命题下面**还压着结论**（§9：它们不能再算数）", pollution_items),
        ("review_unresolved", "blocker", "稿件审校未过（H 的未决项）", unresolved_review),
    )
    fired = False
    for code, level, why, items in causes:
        if not items:
            continue
        fired = True
        extra = ""
        if code == "contradiction_disputed_source":
            extra = ("。处置：追原始证明 → 判不了就 `ask_user`（§8 的裁决闭环）；"
                     "**不许**把有争议的来源当成已确认的")
        elif code == "contradiction_wrong_paper":
            extra = "。处置：重取对的那一篇（这一栏就是 P2 的 `matched`）"
        elif code == "contradiction_own_hole":
            extra = ("。处置：D 给可挽救性评估、E 补 T3，或如实降档 —— "
                     "压在上面的结论在修好之前不能算数")
        elif code == "review_unresolved":
            extra = "。处置：G 修订 / H 复审（§14.4 的未决问题那一节）"
        elif code == "contradiction_pollution":
            extra = ("。处置：要么把被证否那条的来源换掉（重取 / 换一篇），"
                     "要么把压在上面的结论一起降档或撤回")
        pollution_note = ""
        if code == "contradiction_disputed_source" and pollution:
            pollution_note = ("；**污染面**（被证否的那些，谁跟着倒）："
                              + "；".join(f"{k} → {v}" for k, v in sorted(pollution.items())))
        rep.findings.append(Finding(
            "contradictions", code, level,
            f"{why}：共 {len(items)} 处 —— " + "；".join(items[:5]) + extra + pollution_note,
        ))
    rep.status["contradictions"] = "fail" if fired else "pass"


def _has_t3(exp: Mapping[str, Any]) -> bool:
    """T3 的机械形态（§10.2）：形式化方法 + proof 级 + 检查器真的说过话。"""
    return (str(exp.get("method") or "") == "formal"
            and str(exp.get("evidence_kind") or "") == "proof"
            and bool(str(exp.get("verifier_output") or "").strip()))


def _check_load_bearing(rep: ClosingReport, store: Any) -> None:
    """承重结论必须有 T3 或已降档（§10.2 的四条"必须上 T3"在收工门上的形态）。

    承重 = 正文里 `evidence_kind="proof"` 的断言（"作为定理写进正文"那一档，
    §10.2 的第①条）。T3 = 一条 `method="formal"` + `evidence_kind="proof"` +
    `verifier_output` 非空的 `experiments` 行，且被该断言的 `citations` 引到
    （或有一条 `closed` 依赖指向它）。

    负控②（`draft/37` §10.2）：非承重的结论没上 T3 不许因此判失败 ——
    省下来的钱要看得见，所以这里只数承重的那些。
    """
    if store is None:
        rep.status["load_bearing"] = "unknown"
        rep.findings.append(Finding("load_bearing", "no_store", "warning",
                                    "没有 store ⇒ 承重结论没查成"))
        return
    docs = store.rows("documents")
    exps = {str(r.get("experiment_id")): r for r in store.rows("experiments")}
    closed_exp_ids = {str(r.get("source_experiment_id"))
                      for r in store.rows("dependencies")
                      if str(r.get("status") or "") == "closed" and r.get("source_experiment_id")}
    load_bearing = 0
    downgraded = 0
    bad: list[str] = []
    for doc in docs:
        for claim in doc.get("claims") or []:
            if not isinstance(claim, Mapping):
                continue
            if str(claim.get("evidence_kind") or "") != "proof":
                continue          # 非承重（cross_check / heuristic）⇒ 这条门不管它
            load_bearing += 1
            cites = {str(c) for c in (claim.get("citations") or [])}
            backed = any(f"exp:{eid}" in cites and _has_t3(row) for eid, row in exps.items())
            backed = backed or any(eid in closed_exp_ids and _has_t3(row)
                                   for eid, row in exps.items() if f"exp:{eid}" in cites)
            if not backed:
                bad.append(f"{doc.get('doc_id')}#{claim.get('claim_id')}"
                           f"（{str(claim.get('text') or '')[:40]}）")
    # 命题台账那一半：`active` + proof 级 + 有下游（被别人 derived_from 引到）= 承重。
    stmts = store.rows("statements")
    downstream: dict[str, int] = {}
    for s in stmts:
        for dep in s.get("derived_from") or []:
            downstream[str(dep)] = downstream.get(str(dep), 0) + 1
    stmt_load_bearing = 0
    for s in stmts:
        if str(s.get("status") or "") != "active":
            continue
        if not downstream.get(str(s.get("stmt_id"))):
            continue
        stmt_load_bearing += 1
        if str(s.get("evidence_kind") or "") != "proof":
            downgraded += 1          # 已降档：这正是允许的出路
    rep.readings["load_bearing"] = {
        "claims_with_proof": load_bearing,
        "claims_without_t3": len(bad),
        "statements_load_bearing": stmt_load_bearing,
        "statements_downgraded": downgraded,
        "must_t3_conditions": [{"condition": c, "mechanical": m, "status": s}
                               for c, m, s in MUST_T3_CONDITIONS],
        "must_t3_gap": MUST_T3_GAP_NOTE,
    }
    if bad:
        rep.status["load_bearing"] = "fail"
        rep.findings.append(Finding(
            "load_bearing", "load_bearing_without_t3", "blocker",
            f"有 {len(bad)} 条承重结论（正文里 evidence_kind='proof'）没有 T3 背书："
            + "；".join(bad[:5])
            + "。要么补形式化（E 的 check_formal，检查器原话进 verifier_output），"
            "要么如实降档成 cross_check/heuristic 并改稿件的措辞（§10.2："
            "措辞不许出现「已证明/定理/必然」）",
        ))
    else:
        rep.status["load_bearing"] = "pass"


def _check_report_shape(rep: ClosingReport, report_path: str, store: Any) -> None:
    """报告九节 + 分栏 + 附件三件套（§14.4 / §16 P3 的报告行）。"""
    if not str(report_path or "").strip():
        rep.status["report_shape"] = "unknown"
        rep.findings.append(Finding(
            "report_shape", "report_path_missing", "warning",
            "没给报告路径 ⇒ 报告形状没查成（不是「报告没问题」）",
        ))
        return
    path = Path(resolve_under_workspace(store, report_path))
    if not path.is_file():
        rep.status["report_shape"] = "unknown"
        rep.findings.append(Finding(
            "report_shape", "report_not_written", "warning",
            f"报告不在盘上：{path} ⇒ 没查成。报告是 M 的产物（九节；落点 out/review/REPORT.md）",
        ))
        return
    text = path.read_text(encoding="utf-8")
    missing = [f"{num}、{name}" for num, name in REPORT_SECTIONS
               if f"{num}、" not in text and name not in text]
    missing_split = [m for m in SPLIT_MARKERS if m not in text]
    has_attach = [f for f in ATTACHMENT_FIELDS if f in text]
    rep.readings["report_shape"] = {
        "path": str(path), "chars": len(text),
        "missing_sections": missing, "missing_split_markers": missing_split,
        "attachment_fields": has_attach,
    }
    problems: list[str] = []
    if missing:
        problems.append(f"缺 {len(missing)} 节（{'、'.join(missing[:4])}）")
    if missing_split:
        problems.append(f"缺分栏标记（{'、'.join(missing_split)}）—— "
                        "「我们补的」与「原文的」必须分开写")
    if problems:
        rep.status["report_shape"] = "fail"
        rep.findings.append(Finding(
            "report_shape", "report_incomplete", "blocker",
            f"报告形状不齐：{'；'.join(problems)}（§14.4 的九节是形状，不是建议）",
        ))
    else:
        rep.status["report_shape"] = "pass"


def _check_substance(rep: ClosingReport, store: Any) -> None:
    """实质产出：这一趟到底产出了什么（空台账不许报「可交付」）。

    ## 为什么要有这一格（T1 实测，`draft/37` §84 的 D2）

    那一趟退出码 0、报告九节齐全、`user_pending: pass`，而台账是
    `documents=0 / statements=0 / relations=0 / experiments=0 / review_findings=0`
    —— 前五格全过、`can_close=true`、报告写「可交付」。原因不是判据写错了，
    而是没有一格问"产出了什么"：`report_shape` 只看节名，而 `anchor` /
    `contradictions` / `load_bearing` 在空台账上天然为空（真空成立）。
    这正是本项目最忌的同族形态：把"没做"读成"没问题"。

    ## 三态

    - 五张表都读得到：全 0 ⇒ `fail`（读数逐张列出）；有非空 ⇒ `pass`；
    - 有表读不到 ⇒ `unknown`（"问不出来"不是"没问题"）。
    """
    if store is None:
        rep.status["substance"] = "unknown"
        rep.findings.append(Finding("substance", "no_store", "warning",
                                    "没有 store ⇒ 产出了什么问不出来（不是没有产出）"))
        return
    counts: dict[str, int] = {}
    problems: list[str] = []
    for table in SUBSTANCE_TABLES:
        try:
            counts[table] = len(store.rows(table))
        except Exception as e:  # noqa: BLE001 - 表读不到要如实报"问不出来"
            problems.append(f"{table} 读不到（{type(e).__name__}: {e}）")
    detail = "、".join(f"{t}={counts.get(t, '读不到')}" for t in SUBSTANCE_TABLES)
    rep.readings["substance"] = dict(counts)
    if problems:
        rep.status["substance"] = "unknown"
        rep.findings.append(Finding(
            "substance", "substance_unreadable", "warning",
            "有一张表读不到 ⇒ 这一格问不出来：" + "；".join(problems) + f"（读数：{detail}）"))
        return
    total = sum(counts.values())
    if total == 0:
        rep.status["substance"] = "fail"
        rep.findings.append(Finding(
            "substance", "no_substantive_output", "blocker",
            f"这一趟没有任何实质产出（{detail}）⇒ 不许报「可交付」："
            "报告形状对、锚一致、没有矛盾，都不等于**做了事**。"
            "处置：把该产出的东西产出（登记命题 / 跑实验 / 落稿件 / 审校发现），"
            "或如实写清「这一趟什么都没做成、卡在哪」，而不是交一份形式上的交付"))
        return
    rep.status["substance"] = "pass"
    rep.readings["substance_total"] = total


def _check_user_pending(rep: ClosingReport, session_root: Any,
                       *, sid: str | None = None) -> None:
    """还在等用户回答 ⇒ 必须停在"等待用户"（§14.5 第 4 件 / R26）。

    `sid` 的三态（`draft/37` §63）：一个具体会话号 = 读那一段；
    `None` = 读缺省会话（`sessions/<今天>.jsonl`，运维口径，合法）；
    `NO_SESSION` = 「调用方没有会话身份」 ⇒ 这一格是 `unknown`。
    第三个输入是修法 B 加的：装配期没把 sid 注入进来时，按缺省会话读会得出
    "没问过用户"——而真机每一趟都有自己的 sid（实测 `real11`：
    运行内报 pass、外部带 sid 报 fail）。「不许」用缺省值冒充"查过了"。
    """
    if session_root is None:
        rep.status["user_pending"] = "unknown"
        rep.findings.append(Finding("user_pending", "no_session_root", "warning",
                                    "没有会话记录根 ⇒ 待答问题没查成"))
        return
    if sid == NO_SESSION:
        rep.status["user_pending"] = "unknown"
        rep.findings.append(Finding(
            "user_pending", "no_session_identity", "warning",
            "这次调用没有会话身份（装配期没注入 sid，`tools.build_registry(sid=...)`）"
            "⇒ 待答问题**没查成**。不许按缺省会话读：真机每一趟都有自己的 sid，"
            "按缺省读会把「问了还没答」读成「没问过」（`draft/37` §63 的假绿）",
        ))
        return
    # `sid` 必须跟着运行走（`draft/37` §58）：不带它时按默认会话读，
    # 而真机每一趟都有自己的 sid ⇒ 待答问题会被读成「没问过」。
    pending = U.pending_questions(session_root, sid=sid)
    replies = U.read_replies(session_root, sid=sid)
    rep.readings["user_pending"] = {
        "pending": [{"qid": q.qid, "role": q.role, "text": q.text[:80]} for q in pending],
        "answered": len(replies),
        "asked": len(pending) + len(replies),
    }
    if pending:
        rep.status["user_pending"] = "fail"
        rep.findings.append(Finding(
            "user_pending", "waiting_for_user", "blocker",
            f"还有 {len(pending)} 个问题在等用户回答（"
            + "、".join(q.qid for q in pending[:5]) + "）⇒ **必须停在「等待用户」**："
            "不许把它当成默许继续做（三态纪律）。用户答完（`agentflow answer`）再 `--resume` 续跑",
        ))
    else:
        rep.status["user_pending"] = "pass"


# ------------------------------------------------------------------ 入口

def check_closing(store: Any, *, project_dir: str = "", report_path: str = "",
                  session_root: Any = None, checks: tuple[str, ...] = DEFAULT_CHECKS,
                  sid: str | None = None,
                  ) -> ClosingReport:
    """跑收工门，返回读数（不抛业务异常 —— 没查成落成 `unknown`）。

    `session_root` 不给时取 `store.root`（会话记录与工作区本来就是同一个根，
    两处分开写迟早会出现"审计记录落在别处"的静默错位）。
    `project_dir` / `report_path` 不给 ⇒ 对应的那一两格是 `unknown`（不是 pass）：
    门宁可说"我没查成"，也不许在缺少读数时说"可以交"。
    `sid` 三态见 :data:`NO_SESSION`：具体会话号 / `None`（缺省会话）/
    `NO_SESSION`（没有会话身份 ⇒ `user_pending` 那格 `unknown`）。
    """
    rep = ClosingReport()
    root = session_root if session_root is not None else getattr(store, "root", None)
    for name in checks:
        if name == "anchor":
            _check_anchor(rep, project_dir, store)
        elif name == "contradictions":
            _check_contradictions(rep, store)
        elif name == "load_bearing":
            _check_load_bearing(rep, store)
        elif name == "report_shape":
            _check_report_shape(rep, report_path, store)
        elif name == "user_pending":
            _check_user_pending(rep, root, sid=sid)
        elif name == "substance":
            _check_substance(rep, store)
        elif name == "acceptance":
            _check_acceptance(rep, store, project_dir)
        else:
            rep.status[name] = "unknown"
            rep.findings.append(Finding(name, "unknown_check", "warning",
                                        f"没有这个检查：{name!r}（判据表与实现在这里分家了）"))
    return rep


def tri_state_exit_code(rep: ClosingReport) -> int:
    """CLI 的三态退出码：0 可交付 / 1 被拦住 / 2 没查成（`unknown` 不算通过）。"""
    if rep.can_close:
        return 0
    if rep.unknowns and not rep.failed:
        return 2
    return 1
