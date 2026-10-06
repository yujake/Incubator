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
import re
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
    "reviewed_proof_rows": "**我方**走完「有证明过程 + 审过」的命题行数（`statements` 里"
                           "五元位派生出 `预备定理级` / `正式定理` 的行，且 `origin != external_lit`）"
                           "—— 引用命题不算：它的第 2 位凭据是文献代号，不是我们造的东西"
                           "（`draft/39` §3.17 A5：非数值方向的项目靠这一档满足「算或造」）",
    "reviewed_documents": "被审到有裁决的我方稿件行数（`documents` 里状态被推成 "
                          "accepted/revised 的行，或 `review_rounds >= 1` 的行）",
    "reviewed_current_rows": "现行版本被审校记录钉住的稿件份数（`doc-signatures` 里该 `doc_id` 有一条"
                             "签名的 `content_sha256` 等于稿件行现在的 `content_sha256`）—— 缺省阈值 "
                             "= 台账里自称被审过的稿件份数（status ∈ accepted/revised 或 "
                             "`review_rounds >= 1`）。它问的是「改完之后有没有再复核」，与 "
                             "`reviewed_documents` 是两件事：后者只看状态，而 G.revise 把状态推成 "
                             "`revised` 的那一刻，签名还钉着改之前那一版。为什么单列"
                             "（`draft/39` §6.46 的 D57）：T5 第 5 趟里 H 判的是旧版的三条断言"
                             "（签名钉 `e7346eb7…`），随后 G.revise 追加了第 4 条断言（现行版 "
                             "`68bfc4c7…`）—— 那一条断言从未被任何一次审校看过，而收工门读的是 "
                             "`status=revised` ⇒ 七格全绿、`review_findings` 0 条",
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
    "retrieval_ok_rows": "**真的取回了东西**的检索次数（`search_requests` 里 `outcome=ok` 的行）"
                         "—— 缺省阈值 = `research_questions` 的行数（每个立起来的问题至少要被一次"
                         "成功取回服务过；这个数由台账算出来，不是我拍的）。它与 `retrieval_attempts` "
                         "分开：「查过」与「查到了」是两件事 —— 前者把 `no_results` 也算进去。"
                         "为什么单列（`draft/39` §6.47 的 D60）：T5 第 6 趟 `p8f` 里 4 次检索有 2 次 "
                         "`no_results`（都是题面式说法，没按纪律换规范术语重查），`literature` 只 8 行，"
                         "而 M 自己在报告的「未决问题」里写着「未按纪律用规范术语再查一轮」——"
                         "纪律写在 brief 里，可**没有读数的地方纪律管不住**",
    "document_rows": "交付的稿件份数（`documents` 的行数）—— 任务说「交付进展手稿 / 清单 / 综述」时，"
                     "这一档就是「那份东西在不在」的读数。为什么单列（`draft/39` §6.47 的 D59）："
                     "T5 第 6 趟 `p8f` 里 `documents` **0 行**（一次稿子都没写），而 M 把 "
                     "`plan_progress_rows`（F 的计划推进）填进了「交」那一环 ⇒ 收工门七格全绿、"
                     "`can_close=true`；`substance` 那一格只看五张表里有没有非空的"
                     "（`relations` 47 行就够让它绿），所以「任务说要交的那份东西在不在」"
                     "必须有自己的一档",
    "document_body_rows": "**有正文**的稿件份数（`documents` 行里「至少一节、且每一节的 `body` 都非空」"
                          "的行）—— 有 sections 却每节都空的那种稿件是**骨架**，不是手稿。"
                          "为什么单列（`draft/39` §6.48 的 D63）：T5 第 7 趟 `p8g` 里 `documents` 一行、"
                          "`document_rows` 与 `document_literature_citations` 都绿，而那份 survey 的"
                          "三节 body **全是空串**（`documents/0000.md` 里只有框架生成的骨架与三条"
                          "claim）—— 读数说「交了一份 survey」，实际交的是骨架。"
                          "没有 sections 的稿件（清单型交付）不在这一档说话（那是另一种形态）",
    "document_claim_rows": "手稿里**带引文的断言**条数（`documents` 各行 `claims` 之和）—— 缺省阈值 = "
                           "`research_questions` 的行数（每个立起来的问题至少要有一条落进手稿的断言；"
                           "这个数由台账算出来）。它与 `document_rows` 分工：后者问「那份东西在不在」，"
                           "这一档问「它有没有把立起来的问题说进去」。真机读数（T5 第 7 趟 `p8g`）："
                           "3 条研究问题、手稿 3 条断言 —— 恰好各对一条；而第 6 趟 `p8f` 是"
                           "3 条问题、**0 条断言**（没有稿子）",
    "claim_evidence_fit_rows": "**断言与它引的证据对得上**的条数（确定性判据，见 `citation_fit`）—— "
                               "两条腿：引 `exp:` 的断言，其正文里的数字要与被引实验的 `claim` / "
                               "`search_bound` / `params` 里的数字**有交集**；引 `lit:` 的断言，其正文"
                               "的实词要与被引文献的题名/摘要**有交集**。任何一侧没有可判特征 ⇒ 那一条"
                               "记「不可判」（不冒充通过）。缺省阈值 = **可判的**断言条数。"
                               "为什么单列（`draft/39` §6.48 的 D61/D62）：T5 第 7 趟 `p8g` 的手稿里 "
                               "claim-2（n=3，界 2000）引的是 `exp:0000`（n=4，界 1000）、claim-3"
                               "（n=4，界 1000）引的是 `exp:0001`（n=3，界 2000）—— **两条互换**；"
                               "claim-1（Wiles 证明的三条承重腿）引的 `lit:0000` 是「PRIMES is in P」"
                               "（AKS 素性检验）—— 而所有机械读数全绿："
                               "`claims_supported_by_their_evidence` 只问「引到的实验是不是 "
                               "`result=supports`」（两条都是），`document_literature_citations` 只数"
                               "「`lit:` 出现了几次」",
    "unfinished_request_rows": "队列里**没做完**的请求条数（`search_requests` 里 `done` 不为真的行 + "
                               "`reprocess_requests` 里 `status=pending` 的行）—— 它数的是「提交了、"
                               "没人做」。这一档的缺省判据是**上限 0**（不是「越多越好」：要么派 A 把请求"
                               "认领跑完（`A.run_once` / `A.run`），要么在那一行写 `\"na\": true` + 理由"
                               "说清为什么留着）；所以它红的时候说的是「队列没闭环」，不是「做得少」。"
                               "为什么单列（`draft/39` §6.45 的 D56）：T5 第 5 趟里 F 的攻坚子目标用 "
                               "`submit_search_request` 提交了 `r-0004`（`done=false` / `claimed_by=null` / "
                               "`attempts=0`），计划就卡在「等 A 完成检索请求 r-0004」上，而七格全绿、"
                               "`can_close=true`。`retrieval_attempts` 数的是**做过的**条数，这一档数的是"
                               "**没做的那些** —— 少了它，「请求提交了没人做」在收工门上一个读数都没有",
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
    "c_analysis_runs": "关系分析真的跑过几次（`tasks` 里 role=C 且跑过的任务行）—— C 的产物"
                       "是返回值本身、不落台账，所以「这一趟用没用 C」只有任务行能回答；"
                       "0 表示一次都没用过（`draft/39` §6.41 的 D52：T5 第 1 趟用户点名"
                       "「重点考察 C」，而 role=C 的任务行是 0、七格全绿、无人察觉）",
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
    "manuscript_rows": "**交接手稿**份数（`manuscripts/handoffs.jsonl` 的**行数**，"
                       "每行要求 `to`/`summary`/`body` 齐全）—— 用户口径「传信息就传手稿编号」"
                       "落在盘上的那一份（`draft/37` §134）。为什么单列：T2 第 5 趟这一类"
                       "**一次也没用**（M 写了 26 条 `note`，只活在会话里；收工之后"
                       "「谁把什么交给了谁」在盘上查不到）。为什么从「数文件」改成「数行」"
                       "（`draft/39` §C1，用户 2026-10-05 裁）：旧口径要文件名能被 "
                       "`<编号>-<谁>to<谁>.md` 认出来 ⇒ 改个名就读成 0（读数被文件名的形状绑住），"
                       "而账本是追加写的、撞号与覆盖在结构上不可能发生",
}

#: 「被审过」这一档认的稿件状态：H 的裁决把 `draft` 推成这几个之一。
#:
#: 为什么不能只看 `review_rounds`（`draft/37` §95 的真机读数）：T1 第 9 趟里
#: `documents/0000` 是 `status=accepted`、`review_rounds=0` —— H 审过并给了裁决，
#: 而"轮次"只在真的改过稿时才会加。按 `review_rounds >= 1` 判会把一次
#: 已经审过且通过的稿件读成"没审过"（判据恒红 ⇒ 谁都不会再信它）。
REVIEWED_DOC_STATUSES: tuple[str, ...] = ("accepted", "revised")

#: 「研究链的六个环节」——从零做研究时，验收表每个环节至少要有一行（`draft/37` §137）。
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
    # 第一环节拆成两环（`draft/39` §6.47 的 D60）：此前它在验收表里的成员是
    # 「research_question_rows 或 retrieval_attempts」——任一条成立就算这一环覆盖了。
    # 真机读数（T5 第 6 趟 `p8f`）：M 只写了 `research_question_rows` 一条，
    # 于是"检索"那一腿整个没有读数；那一趟 4 次检索里 2 次 `no_results`（都是题面式说法，
    # 没有按纪律换规范术语重查），`literature` 只有 8 行 —— 而 M 自己在报告的"未决问题"里
    # 逐字写着「未按纪律用规范术语再查一轮」。没有读数的地方纪律管不住：把"立题"与
    # "检索"分成两环，检索那一环要有一档真的数"取回了什么"。
    ("立题", ("research_question_rows",)),
    ("检索（真的取回）", ("retrieval_ok_rows",)),
    # 第二环节从「算并留下界」扩成「算或造」（`draft/39` §3.17 A5，用户 2026-10-05 裁）：
    # 分析/拓扑方向的项目永远不会有"数值实验"这一行，按旧口径那一格结构性恒空 ——
    # 那是拿数值口径去卡一个不该用数值的方向。扩成"算（数值/界）或造（有证明过程 + 审过、
    # 或构造性反例/族构造）"之后，两条腿各算数；用非数值那条腿时，项目要在验收表里写清
    # "为什么不用数值"（那就是五位里第 1 位 `na` 的理由，`acceptance` 那一格读它）。
    ("算或造", ("numeric_experiment_rows", "search_frontier_rows",
                "enumeration_optimization_rows", "reviewed_proof_rows",
                "counterexample_or_proof_rows")),
    ("想（猜想或判决性证据）", ("conjecture_rows", "statement_rows",
                                "counterexample_or_proof_rows")),
    # 「看（关系分析）」（`draft/39` §6.42 的 D53）：用户点名过"重点考察 C"，
    # 而 C 的产物是返回值本身、不落台账 ⇒ 真机里"C 一次都没被派"可以整趟静悄悄
    # （T5 第 1/2 趟：`tasks` 里 role=C 的行是 0，七格全绿）。把它做成覆盖面的一环之后，
    # 「用没用 C」与其它几环一样要么有读数、要么写 `na` + 理由 —— 不许它悄悄不发生。
    ("看（关系分析）", ("c_analysis_runs",)),
    # 「攻（攻坚推进）」（`draft/39` §6.47 的 D59）：从原来的「交（文献进稿、计划推进）」
    # 里分出来。动机是真机读数（T5 第 6 趟 `p8f`）：那一趟任务原文是"交付进展手稿与说明"，
    # 而盘上 `documents` 0 行——一次稿子都没写；M 把 `plan_progress_rows`（F 的计划推进）
    # 填进了"交"那一环，于是收工门七格全绿、`can_close=true`，而 M 自己在报告的
    # "未决问题"第 5 条里逐字写着「`documents` 0 行：没有稿件」。
    # 根因是那一环的成员里混进了与交付物无关的档：F 的推进是"攻"，不是"交"。
    ("攻（攻坚推进）", ("attack_plan_rows", "plan_progress_rows")),
    # 「交（手稿落盘）」（D59）：这一环现在只认"盘上真的有一份交付物"的读数 ——
    # `document_rows`（documents 行数）或那些必须在稿件里才成立的档
    # （引了文献的断言 / 被实验支持的断言 / 断言与证据一致的稿件）。
    # F 的计划推进不再能顶替它：一份没有稿子的交付不算交付。
    ("交（手稿落盘）", ("document_rows", "document_body_rows", "document_claim_rows",
                        "document_literature_citations",
                        "supported_claims", "claims_supported_by_their_evidence")),
    # 「闭（请求闭环）」（`draft/39` §6.45 的 D56）：别人提交的检索请求
    # （F 的 `submit_search_request` / C 的 `submit_requests=true` / D 的缺口）落在
    # `search_requests` 队列里，消费它的动作是 A 的 `run_once` / `run` —— 而 M 的
    # 伙伴表里那两个无参动作只有一个名字（没有一句说明），也没有任何一档问过
    # 「队列里还有没有人没做的请求」。于是真机里 F 的请求可以整趟没人认领、
    # 子目标永远停在「等 A 完成检索请求」，而收工门七格全绿（T5 第 5 趟 `p8e`）。
    # 与其它几环同一套办法：要么有读数、要么写 `na` + 理由 —— 不许它悄悄不发生。
    ("闭（请求闭环）", ("unfinished_request_rows",)),
)


def research_chain_gaps(store: Any, kinds: Iterable[str], *,
                        na_kinds: Iterable[str] = ()) -> dict[str, Any]:
    """研究型项目的验收表覆盖面：八个环节里哪些一行都没有。

    返回 `{"researched", "rows", "groups", "na_groups", "missing", "note"}`：
    `researched=False`（这个项目没有 `research_questions` 行）时 `missing` 恒为空 ——
    这条判据对非研究型项目不说话（不是"通过"，是"不适用"）。

    `na_kinds`（`draft/39` §6.39 的 D49）：标了 `na` 的行算"这一环节被如实标注过"
    —— 调查型任务天然没有"算或造"那一步，那件事要能被写成读数，而不是只能被读成"没做"。
    """
    used = {str(k) for k in kinds}
    na_used = {str(k) for k in na_kinds}
    try:
        researched = len(list(store.rows("research_questions"))) > 0
    except Exception as exc:  # noqa: BLE001 —— 读不到研究问题表 ⇒ 这一格判不了，由调用方落 unknown
        raise RuntimeError(f"研究问题表读不到：{type(exc).__name__}: {exc}") from exc
    groups: dict[str, list[str]] = {}
    na_groups: dict[str, list[str]] = {}
    missing: list[str] = []
    for label, members in RESEARCH_CHAIN_GROUPS:
        hit = [k for k in members if k in used]
        marked = [k for k in members if k in na_used]
        groups[label] = hit
        na_groups[label] = marked
        if researched and not hit and not marked:
            missing.append(f"{label}（可以写 {' / '.join(members)} 里的任意一档；"
                           f"这一档天然不适用就在那一行上写 `\"na\": true` 并写明理由）")
    return {
        "researched": researched,
        "rows": len(used),
        "groups": groups,
        "na_groups": na_groups,
        "missing": missing,
        "note": ("研究型项目（有 `research_questions` 行）的验收表要覆盖研究链八个环节，"
                 "每个环节至少一行。覆盖面管的是「那一行在不在」；那一行的读数够不够"
                 "由它自己那一档判（`min` 缺省时按该档的口径，多数是 ≥ 1；"
                 "`unfinished_request_rows` 那一档的方向相反 —— 它的缺省口径是 ≤ 0）—— "
                 "所以删掉一行与写着 0 都会红，但后者留下的是读数，前者留下的是一个空环节。"
                 "某一档对这个项目**天然不适用**时（例如调查型任务没有「算或造」那一步），"
                 "在那一行上写 `\"na\": true` 并在 `note` 里写明理由 —— `na` ≠ 通过 ≠ 失败。"
                 "非研究型项目不受这一条约束（`researched=false`）。"),
    }



def _numbers_in(text: Any) -> set[int]:
    """一段文本里的整数（判"断言与它引的实验说的是不是同一个界"用的特征）。"""
    return {int(m) for m in re.findall(r"\d+", str(text or ""))}


#: 判"文献引用有没有跑题"时不算实词的词（判据与读数共用这一份，不各写一套）。
#: 只为把"the/and/证明/定理"这类词从两侧都去掉；去掉之后剩下的实词若两边一个都不共，
#: 才判"对不上"（有意保守：宁可记「不可判」，也不要把改写过的引用判成跑题）。
_FIT_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "has", "have",
    "not", "its", "our", "their", "which", "where", "when", "into", "than", "then", "there",
    "these", "those", "such", "only", "also", "been", "being", "does", "did", "without",
    "within", "against", "after", "before", "because", "therefore", "however", "thus",
    "proof", "proofs", "theorem", "theorems", "lemma", "lemmas", "case", "cases", "result",
    "results", "check", "checks", "finite", "integer", "integers", "solution", "solutions",
    "positive", "primitive", "exponent", "exponents", "method", "methods", "using", "over",
    "under", "between", "each", "all", "any", "some", "more", "most", "other", "standard",
    "version", "paper", "survey", "overview", "study", "note", "notes",
})


def _words_in(text: Any) -> set[str]:
    """一段文本里的英文实词（小写、长度 ≥ 4、去掉停用词）。"""
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", str(text or ""))
    return {w.lower() for w in words if w.lower() not in _FIT_STOPWORDS}


def citation_fit(store: Any) -> dict[str, Any]:
    """逐条断言核「它引的证据是不是说的同一件事」（确定性、可复算，D61/D62）。

    判据分两条腿，都是特征交集：
    - 引 `exp:`：断言正文的整数集合 与 被引实验的 `claim` / `claim_key` / `search_bound` /
      `params` 里的整数集合，两边都非空时必须有交集（真机读数：一条断言说"n=3，界 2000"，
      引的实验是"n=4，界 1000" ⇒ 交集为空 ⇒ 对不上）；
    - 引 `lit:`：断言正文的英文实词集合 与 被引文献的题名/摘要的实词集合，两边都非空时
      必须有交集（真机读数：讲 Wiles 三条承重腿的断言引了「PRIMES is in P」⇒ 交集为空）。

    三态：两边任何一侧没有可判特征 ⇒ 那一条记 `unjudged`（"没查成"，绝不读成"对上了"）。
    一条断言引了多条证据时，只要有一条判成"对得上"就算这一条对得上（不因为一条
    跑题的引文把整条断言判死 —— 但也绝不放过"全都对不上"）。
    """
    docs = [dict(r) for r in store.rows("documents")]
    exps = {str(r.get("experiment_id") or ""): dict(r) for r in store.rows("experiments")}
    lits = {str(r.get("lit_id") or ""): dict(r) for r in store.rows("literature")}
    checked: list[dict[str, Any]] = []
    for doc in docs:
        for claim in (doc.get("claims") or []):
            if not isinstance(claim, Mapping):
                continue
            claim_nums = _numbers_in(claim.get("text"))
            claim_words = _words_in(claim.get("text"))
            verdict = "unjudged"
            why: list[str] = []
            for cite in (claim.get("citations") or []):
                cid = str(cite)
                if cid.startswith("exp:"):
                    exp = exps.get(cid[4:])
                    if exp is None:
                        why.append(f"{cid}：实验行不在册 ⇒ 不可判")
                        continue
                    ev_nums = (_numbers_in(exp.get("claim")) | _numbers_in(exp.get("claim_key"))
                               | _numbers_in(json.dumps(exp.get("search_bound") or {},
                                                        ensure_ascii=False))
                               | _numbers_in(json.dumps(exp.get("params") or {},
                                                        ensure_ascii=False)))
                    if not claim_nums or not ev_nums:
                        why.append(f"{cid}：一侧没有数字特征 ⇒ 不可判")
                        continue
                    if claim_nums & ev_nums:
                        verdict = "fit"
                    elif verdict != "fit":
                        verdict = "mismatch"
                        why.append(f"{cid}：断言里的数字 {sorted(claim_nums)[:6]} 与被引实验的 "
                                   f"{sorted(ev_nums)[:6]} 没有交集 ⇒ 说的不是同一个界/参数")
                elif cid.startswith("lit:"):
                    lit = lits.get(cid[4:].split("#", 1)[0])
                    if lit is None:
                        why.append(f"{cid}：文献行不在册 ⇒ 不可判")
                        continue
                    ev_words = _words_in(lit.get("title")) | _words_in(lit.get("summary"))
                    if len(claim_words) < 2 or not ev_words:
                        why.append(f"{cid}：一侧没有实词特征 ⇒ 不可判")
                        continue
                    if claim_words & ev_words:
                        verdict = "fit"
                    elif verdict != "fit":
                        verdict = "mismatch"
                        why.append(f"{cid}：断言的实词与《{str(lit.get('title') or '')[:40]}》"
                                   f"没有交集 ⇒ 引文可能跑题")
            checked.append({"doc_id": str(doc.get("doc_id") or ""),
                            "claim_id": str(claim.get("claim_id") or ""),
                            "citations": [str(c) for c in (claim.get("citations") or [])],
                            "verdict": verdict, "why": why[:3],
                            "numbers_in_claim": sorted(claim_nums)[:6],
                            "words_in_claim": sorted(claim_words)[:6]})
    fits = [c for c in checked if c["verdict"] == "fit"]
    bad = [c for c in checked if c["verdict"] == "mismatch"]
    unknown = [c for c in checked if c["verdict"] == "unjudged"]
    return {"claims": checked, "fit": len(fits), "mismatch": len(bad), "unjudged": len(unknown),
            "judged": len(fits) + len(bad), "mismatches": bad[:8], "unjudged_rows": unknown[:8]}


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
    if kind == "reviewed_current_rows":
        # 「改完之后有没有再复核」那一档（`draft/39` §6.46 的 D57）。
        #
        # 三件事分开报，因为它们的原因不同：
        # ① pinned —— 现行版被某一条签名钉住（这一档要数的就是它）；
        # ② stale —— 自称审过、而且台账里有该稿件的签名，但没有一条钉在现行版上
        #    ⇒ 这是「改完之后没再复核」（G.revise 追加/替换断言后忘了找 H）；
        # ③ no_signature_record —— 自称审过却一条签名记录都没有。它与 ② 分开：
        #    那可能是"这个工作区根本没有签名链"（真机：T3 的工作区是把上一趟的
        #    `documents` 复制过来的，`doc-signatures/` 没跟过来），`verify_all` 的
        #    `accepted_without_signature` 管那半边。这一档只在 ② 上放自动判据。
        from . import signatures as SIG

        docs = [dict(r) for r in store.rows("documents")]
        recs, bad_lines = SIG.read_ledger(SIG.ledger_path(project_root))

        def _records_of(doc_id: str) -> list[Mapping[str, Any]]:
            return [r for r in recs if str(r.get("doc_id") or "") == doc_id]

        claimed = [d for d in docs
                   if str(d.get("status") or "") in REVIEWED_DOC_STATUSES
                   or int(d.get("review_rounds") or 0) >= 1]
        pinned = [d for d in claimed if SIG.signed_revision(d, recs) is not None]
        stale = [d for d in claimed
                 if SIG.signed_revision(d, recs) is None and _records_of(str(d.get("doc_id") or ""))]
        never = [d for d in claimed
                 if not _records_of(str(d.get("doc_id") or ""))]
        detail: dict[str, Any] = {
            "documents": len(docs), "claimed_reviewed": len(claimed),
            "claimed_ids": [str(d.get("doc_id") or "") for d in claimed[:8]],
            "pinned_to_current": [str(d.get("doc_id") or "") for d in pinned[:8]],
            "stale_signoffs": [
                {"doc_id": str(d.get("doc_id") or ""),
                 "current": str(d.get("content_sha256") or "")[:12],
                 "signed": sorted({str(r.get("content_sha256") or "")[:12]
                                   for r in _records_of(str(d.get("doc_id") or ""))})[:4],
                 "status": str(d.get("status") or ""), "revision": d.get("revision"),
                 "review_rounds": d.get("review_rounds")}
                for d in stale[:8]],
            "no_signature_record": [str(d.get("doc_id") or "") for d in never[:8]],
            "signature_ledger": str(SIG.ledger_path(project_root)),
            "implicit_min": len(claimed),
            "note": ("这一档数的是「现行版本被审校记录钉住的稿件份数」，缺省阈值 = 自称被审过的稿件"
                     "份数。差的那几份就是「改完之后没再复核」—— 派 `H.verify_fixes` / `H.review` "
                     "复核现行版，或者如实标 `na` + 理由（`stale_signoffs` 与 "
                     "`no_signature_record` 分开报：前者是「改过了没复核」，后者是「没有签名链」）"),
        }
        if bad_lines:
            detail["ledger_bad_lines"] = bad_lines[:3]
        return len(pinned), detail
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
        # 交接手稿那一档（`draft/37` §134/§140；`draft/39` §C1 起存储改成追加式 JSONL）：
        # 数 `manuscripts/handoffs.jsonl` 的行数（一份交接一行）。为什么从"数文件"改成
        # "数行"（用户 2026-10-05 裁）：旧口径要求文件名能被 `<编号>-<谁>to<谁>.md` 认出来，
        # 于是改个名或少个字段就读成 0 —— 读数被文件名的形状绑住；而账本是追加写的，
        # 撞号与覆盖在结构上不可能发生（这正是 D16/D17 的终结判据）。
        # 旧格式（`.md` 文件）不计入这一档，但在明细里另列一栏：既不假装没有，
        # 也不让它冒充新格式。
        from . import manuscripts as MS

        all_rows, bad_lines = MS.read_rows(project_root)
        good = [r for r in all_rows if not MS.missing_fields(r)]
        folder = project_root / MS.MANUSCRIPTS_DIR
        legacy = [str(got.get("id") or "")
                  for got in [MS.parse_name(p) or {} for p in
                              (sorted(folder.glob("*.md")) if folder.is_dir() else [])] if got]
        detail: dict[str, Any] = {
            "ledger": f"{MS.MANUSCRIPTS_DIR}/{MS.HANDOFFS_NAME}",
            "rows": len(all_rows),
            "complete_rows": [str(r.get("id") or "") for r in good[:10]],
            "unparsable_lines": bad_lines[:5],
            "legacy_md_files": legacy[:10],
            "rows_missing_fields": [{"id": str(r.get("id") or ""), "missing": MS.missing_fields(r)}
                                    for r in all_rows if MS.missing_fields(r)][:5],
        }
        if legacy:
            detail["note"] = (f"另有 {len(legacy)} 份旧格式 `.md` 手稿（不计入这一档）："
                              "新口径数的是账本行；旧文件仍在 `manuscripts.list` 里可见")
        if bad_lines:
            detail["note"] = ("账本里有读不出来的行 ⇒ 这一档的读数偏低，按 `unparsable_lines` "
                              "逐条去查（读不出不等于没有）")
        return len(good), detail
    if kind == "retrieval_ok_rows":
        # 「真的取回了东西」那一档（`draft/39` §6.47 的 D60）。
        #
        # 阈值不是拍出来的数：它等于台账里 `research_questions` 的行数 ——
        # 「每个立起来的问题至少要被一次成功取回服务过」。问题数由台账算，
        # 所以这条判据随项目自己长（立了 3 个问题 ⇒ 至少 3 次成功取回）。
        reqs = [dict(r) for r in store.rows("search_requests")]
        ok = [r for r in reqs if str(r.get("outcome") or "") == "ok"]
        empty = [r for r in reqs if str(r.get("outcome") or "") == "no_results"]
        questions = list(store.rows("research_questions"))
        return len(ok), {
            "search_requests": len(reqs), "ok": len(ok), "no_results": len(empty),
            "research_questions": len(questions),
            "ok_topics": [str(r.get("topic") or "")[:60] for r in ok[:8]],
            "no_result_topics": [str(r.get("topic") or "")[:60] for r in empty[:8]],
            "implicit_min": len(questions),
            "note": ("这一档数的是「查到了」：`no_results` 的请求不算。缺省阈值 = 立起来的研究问题"
                     "条数（每个问题至少要被一次成功取回服务过）。一条 `no_results` 是合法终局，"
                     "但按纪律它要用**规范术语**再查一次（题面式说法查不到不等于这个方向没有文献）"
                     "—— `no_result_topics` 就是用来核这件事的读数"),
        }
    if kind == "document_body_rows":
        # 「有正文的稿件」那一档（`draft/39` §6.48 的 D63）：有 sections 却每节都空 ⇒ 骨架，不是手稿。
        docs = [dict(r) for r in store.rows("documents")]
        with_body: list[dict[str, Any]] = []
        empty_sections: list[dict[str, Any]] = []
        for d in docs:
            secs = [s for s in (d.get("sections") or []) if isinstance(s, Mapping)]
            if not secs:
                continue                        # 没有 sections 的形态（清单型交付）不在这一档说话
            if all(str(s.get("body") or "").strip() for s in secs):
                with_body.append(d)
            else:
                empty_sections.append({"doc_id": str(d.get("doc_id") or ""),
                                       "sections": [str(s.get("heading") or "") for s in secs[:6]],
                                       "empty": [str(s.get("heading") or "") for s in secs
                                                 if not str(s.get("body") or "").strip()][:6]})
        detail: dict[str, Any] = {
            "documents": len(docs), "with_body": len(with_body),
            "with_body_ids": [str(d.get("doc_id") or "") for d in with_body[:8]],
            "empty_section_docs": empty_sections[:8],
            "implicit_min": len(with_body) + len(empty_sections),
            "note": ("这一档数的是「稿件里真的有正文」：有 sections 的行要求每一节的 body 都非空。"
                     "有 sections 却每节都空的行是**骨架**（真机读数 T5 第 7 趟 `p8g`：那份 survey 的"
                     "三节 body 全是空串，而 `document_rows` 与 `document_literature_citations` 都绿）；"
                     "没有 sections 的稿件（清单型交付）不在这一档说话"),
        }
        return len(with_body), detail
    if kind == "claim_evidence_fit_rows":
        # 「断言与它引的证据对得上」那一档（`draft/39` §6.48 的 D61/D62），判据在 `citation_fit`。
        fit = citation_fit(store)
        detail = {
            "claims": len(fit["claims"]), "fit": fit["fit"], "mismatch": fit["mismatch"],
            "unjudged": fit["unjudged"],
            "mismatches": fit["mismatches"], "unjudged_rows": fit["unjudged_rows"],
            "implicit_min": fit["judged"],
            "note": ("这一档数的是「断言与它引的证据说的是同一件事」：引 `exp:` 的要比数字特征、"
                     "引 `lit:` 的要比实词特征（`citation_fit` 是唯一实现）。两边任何一侧没有可判"
                     "特征 ⇒ 那一条记「不可判」，不冒充通过。缺省阈值 = 可判的断言条数"),
        }
        return fit["fit"], detail
    if kind == "document_claim_rows":
        # 「手稿有没有把立起来的问题说进去」那一档（`draft/39` §6.48 的 D63）：阈值随问题数走。
        docs = [dict(r) for r in store.rows("documents")]
        rows = [c for d in docs for c in (d.get("claims") or []) if isinstance(c, Mapping)]
        with_cites = [c for c in rows if list(c.get("citations") or [])]
        questions = list(store.rows("research_questions"))
        return len(with_cites), {
            "claims": len(rows), "with_citations": len(with_cites),
            "research_questions": len(questions),
            "documents": len(docs),
            "ids": [str(c.get("claim_id") or "") for c in with_cites[:10]],
            "implicit_min": len(questions),
            "note": ("这一档数的是「手稿里带引文的断言」，缺省阈值 = 立起来的研究问题条数"
                     "（每个问题至少一条断言落进手稿）。`document_rows` 问「那份东西在不在」，"
                     "这一档问「它有没有把问题说进去」"),
        }
    if kind == "document_rows":
        # 「任务说要交的那份东西在不在」那一档（`draft/39` §6.47 的 D59）。
        docs = [dict(r) for r in store.rows("documents")]
        with_claims = [d for d in docs if list(d.get("claims") or [])]
        return len(docs), {
            "documents": len(docs),
            "with_claims": len(with_claims),
            "kinds": sorted({str(d.get("kind") or "") for d in docs}),
            "statuses": sorted({str(d.get("status") or "") for d in docs}),
            "ids": [str(d.get("doc_id") or "") for d in docs[:8]],
            "note": ("这一档就是「交付物本身在不在」：任务说交付手稿 / 清单 / 综述时，"
                     "盘上得有 `documents` 行。0 行时这一档不成立，而 `substance` 那一格"
                     "可能已经是绿的（它只看五张表里有没有非空的）—— 两者分开报"),
        }
    if kind == "unfinished_request_rows":
        # 「提交了、没人做」那一档（`draft/39` §6.45 的 D56）。
        #
        # 两处刻意的口径：
        # ① 两条队列一起数 —— `search_requests`（A 的：去外面找新东西）与
        #    `reprocess_requests`（B 的：把已有的东西重看一遍）。两条队列的"没做完"
        #    字段名不同（`done` 是布尔、另一张是 `status`），所以判据写在同一个地方，
        #    别让调用方各判一套。
        # ② 这一档的缺省判据是上限 0（`implicit_max`），不是 `got >= min`：
        #    「没做完的请求」越少越好，0 才是达标。`_check_acceptance` 认这个方向
        #    （缺省 `min` 变成 0、`max` 缺省取这一档给的上限）。
        #
        # 真机读数（T5 第 5 趟 `p8e-fermat-shorter-proof`）：`r-0004` 由 F 的攻坚计划
        # 0000 子目标 s1 提交，`done=false` / `claimed_by=null` / `attempts=0`；
        # 计划那一行写着「等 A 完成检索请求 r-0004」，而七格全绿。这档读数就是那件事。
        search_rows = [dict(r) for r in store.rows("search_requests")]
        try:
            repro_rows = [dict(r) for r in store.rows("reprocess_requests")]
        except Exception:  # noqa: BLE001 —— 这张表读不到就不假装它没有（另开一栏说明）
            repro_rows = []
            repro_note = "重抽取请求表读不到 ⇒ 这一档只数了检索请求（读数偏低，不是「没有」）"
        else:
            repro_note = ""
        open_search = [r for r in search_rows if r.get("done") is not True]
        open_repro = [r for r in repro_rows if str(r.get("status") or "pending") == "pending"]
        detail = {
            "search_requests": len(search_rows), "search_unfinished": len(open_search),
            "reprocess_requests": len(repro_rows), "reprocess_unfinished": len(open_repro),
            "unfinished": [
                {"id": str(r.get("request_id") or ""), "topic": str(r.get("topic") or "")[:60],
                 "submitted_by": str(r.get("submitted_by") or ""),
                 "claimed_by": r.get("claimed_by"), "attempts": int(r.get("attempts") or 0)}
                for r in open_search[:8]
            ] + [
                {"id": str(r.get("reprocess_id") or ""), "topic": str(r.get("reason") or "")[:60],
                 "submitted_by": str(r.get("submitted_by") or ""),
                 "claimed_by": r.get("claimed_by"), "attempts": int(r.get("attempts") or 0)}
                for r in open_repro[:8]
            ],
            # 「上限 0」不是缺省阈值 1 的变体：这一档要的就是"一条都不剩"。
            "implicit_min": 0, "implicit_max": 0,
            "note": ("这一档的判据是**上限**：队列里没做完的请求应为 0。有人做了"
                     "（派 `A.run_once` / `A.run` 认领）或如实标 `na` + 理由，两种都算数；"
                     "「提交了没人做」不算数"),
        }
        if repro_note:
            detail["table_note"] = repro_note
        return len(open_search) + len(open_repro), detail
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
    if kind == "c_analysis_runs":
        # C 的关系分析跑过几次（`draft/39` §6.41 的 D52）。
        #
        # 为什么必须单列这一档：C 的八个动作产物就是返回值本身、不落台账
        # （`draft/39` 记过这件事）—— 于是"这一趟到底用没用 C"在收工门上无处可读。
        # 真机读数（T5 第 1 趟 `p8-fermat-shorter-proof`）：用户点名"重点考察 C"，
        # 而 `tasks` 表里 role=C 的行是 0，七格全绿、无人察觉。
        # 这一档数的是任务行（`tasks` 里 role=C 且跑过的），不是 C 的产物 ——
        # 因为 C 的产物本来就不落盘；"它被用过没有"只有任务行能回答。
        rows = [dict(r) for r in store.rows("tasks")
                if str(r.get("role") or "") == "C"]
        ran = [r for r in rows if str(r.get("status") or "") in ("done", "ok", "failed")]
        return len(ran), {"c_tasks": [
            {"id": str(r.get("task_id") or r.get("id") or ""),
             "action": str(r.get("action") or ""),
             "status": str(r.get("status") or "")} for r in rows[:8]],
            "note": ("C 的动作产物是它的返回值、不落台账 ⇒ 这一档数的是 `tasks` 里 role=C 的任务行"
                     "（跑过的都算）。0 表示这一趟**一次都没用过 C**")}
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
    if kind == "reviewed_proof_rows":
        # 「造判决性证据」那一档（`draft/39` §3.17 A5 + §3.14 五元位）：我方命题里
        # 五元位派生出「预备定理级」（有证明过程 + 审过）或「正式定理」（有证明过程 +
        # 形式化通过）的行数。等级一律现算（`evidencebits.bits_from_row` ⇒
        # `derive_grade`），不读盘上存的等级 —— 自报的等级不算数。
        # 引用命题（`origin=external_lit`）不算：它的第 2 位凭据是文献代号，
        # 混进来就等于"引一篇别人的定理"满足了"我们自己造了判决性证据"。
        from . import evidencebits as EB

        rows = list(store.rows("statements"))
        counted: list[dict[str, Any]] = []
        grades: dict[str, int] = {}
        cited_skipped = 0
        for r in rows:
            bits = EB.bits_from_row(r)
            grade = str(bits.get("grade") or "")
            grades[grade] = grades.get(grade, 0) + 1
            if grade in ("pre_theorem", "theorem"):
                if str(bits.get("origin") or "") == "external_lit":
                    cited_skipped += 1
                    continue
                counted.append({"stmt_id": str(r.get("stmt_id") or r.get("id") or ""),
                                "grade": grade, "label": str(r.get("label") or "")[:60]})
        detail: dict[str, Any] = {"statements": len(rows), "counted": counted[:8],
                                  "grades": grades, "cited_skipped": cited_skipped}
        if rows and not counted:
            detail["note"] = ("台账里有命题行，但一条都没走到「预备定理级」—— "
                              "要么没有证明过程，要么没审过（五位里第 2/3 位为空）；"
                              "自报的 `status=proved` / `evidence_kind=proof` 不算凭据")
        return len(counted), detail
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


def _acceptance_unknown(rep: ClosingReport, code: str, detail: str, *,
                        checks_file: str = "") -> None:
    """把「验收表没查成」同时写成 finding 与读数（`draft/39` §6.25 的 D35）。

    为什么读数不能缺：这一格原先只 push 一条 `Finding`，`readings["acceptance"]` 留在
    `None` 上 —— 于是"为什么没查成"在交付面（报告 / 我的离线复算 / 状态报告）里只剩一个
    `null`，而三态纪律要的是"没查成"本身可读。真机读数（T2 第 7 趟 `p6i`）：验收表 P1 用了
    `manuscript_edited`，而这个从零工作区没有只读基线 `source/` ⇒ 那一行抛错 ⇒ 整格
    `unknown` + 读数 `null`，我离线复算时看到的就是一个没有理由的空格。
    """
    rep.status["acceptance"] = "unknown"
    rep.readings["acceptance"] = {"status": "unknown", "code": code, "detail": detail,
                                  "checks_file": checks_file}
    rep.findings.append(Finding("acceptance", code, "warning", detail))


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
        _acceptance_unknown(rep, "acceptance_unreadable",
                            f"机器可判的验收行读不出来（{path}：{type(exc).__name__}: {exc}）"
                            f"⇒ 没查成", checks_file=str(path))
        return

    out: list[dict[str, Any]] = []
    unmet: list[str] = []
    #: 标了 `na` 的行（`draft/39` §6.39 的 D49）：它们算"这一环节被如实标注过"，
    #: 但不参与阈值判定 —— 最后还要用它挡住"整张表全 na"。
    na_rows: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            _acceptance_unknown(rep, "acceptance_unreadable",
                                f"验收行必须是对象，收到了 {type(row).__name__} ⇒ 没查成",
                                checks_file=str(path))
            return
        cid = str(row.get("id") or "")
        kind = str(row.get("kind") or "")
        name = str(row.get("name") or "")
        note = str(row.get("note") or "")
        want_min = int(row.get("min") or 0)     # 0 = 让这一档自己定阈值（见下面的 implicit_min）
        #: 上限（`draft/39` §6.45 的 D56）：`max` 缺省取这一档自己给的 `implicit_max`。
        #:
        #: 为什么需要"上限"这一根轴：多数档问的是「做得够不够」（`got >= min`），而
        #: `unfinished_request_rows` 问的是「剩下多少没做」—— 它的达标线是 0，
        #: 用 `min` 表达不出来（`min=0` 会被读成"没给阈值"）。所以受控档可以声明
        #: `implicit_max`：那一档的行不带 `min`/`max` 时，判据就是 `got <= implicit_max`。
        #: 这不是给验收表开一个"任意表达式"的口子：上限只能由这一档的实现给出，
        #: 写表的人最多把它写得更松（`max`），写不出一档都不存在的方向。
        want_max: int | None = None
        if row.get("max") is not None:
            want_max = int(row["max"])
        # ---- `na` 行（`draft/39` §6.39 的 D49）：这一档对这个项目天然不适用。
        #
        # 三态：`na` ≠ 通过 ≠ 失败（与五位证据模型的 `pending|na|failed|verified` 同一套口径）。
        # 真机读数（T4 第 1 趟 `t4a`）：那是一趟调查任务（"交付一份清单"），它天然没有
        # "算或造"这一环 —— M 按纪律如实写了 0（红得精确），可那份诚实没有出口：
        # 政策里提过 `na` 这个词，实现里只认 `got >= min`。于是"这一档不适用"只能被读成
        # "没做"。两条守卫：①`na` 必须写出理由（`note` 非空），否者等于没标注；
        # ②不许整张表都是 `na`（一张全 na 的验收表等于没有验收表）。
        if row.get("na") is True:
            if not note.strip():
                _acceptance_unknown(
                    rep, "acceptance_na_without_reason",
                    f"验收行 {cid} 标了 `na`，却没有写理由（`note` 为空）⇒ 没查成。"
                    f"`na` 不是「跳过」的快捷键：要写清这一档为什么对这个项目不适用"
                    f"（例如「这是调查型任务，没有数值/构造那一步」）",
                    checks_file=str(path))
                return
            na_rows.append(cid)
            out.append({"id": cid, "name": name, "kind": kind, "min": want_min, "max": None,
                        "got": None, "ok": True, "na": True, "note": note})
            continue
        if kind not in LEG_CHECK_KINDS:
            _acceptance_unknown(
                rep, "acceptance_unknown_kind",
                f"验收行 {cid} 的 kind={kind!r} 不在受控词表 {tuple(LEG_CHECK_KINDS)} 里 "
                f"⇒ 这一行没查成（不是「满足了」）。**一个 kind 不认识 ⇒ 整张表都判没查成**，"
                f"所以别自造名字：写表时从受控词表里逐字挑（那一串逐字写在主控的 brief 里）",
                checks_file=str(path))
            return
        try:
            got, detail = _leg_reading(store, kind, Path(resolve_under_workspace(store, project_dir)))
        except Exception as exc:  # noqa: BLE001 —— 读不到就落 unknown（§94 的 docstring 承诺了，这一轮才补上）
            _acceptance_unknown(
                rep, "acceptance_leg_unreadable",
                f"验收行 {cid}（{kind}）的读数算不出来（{type(exc).__name__}: {exc}）"
                f"⇒ 这一行没查成（不是「不满足」，也不是「满足」）。"
                f"有的档只在特定工作区里可读（例如 `manuscript_edited` / "
                f"`citation_records_vs_bibitems` 要只读基线 `source/`）——"
                f"那是「这一档在这个工作区用不上」，换一档写得出来的",
                checks_file=str(path))
            return
        if not want_min:
            # 调用方没写 `min` ⇒ 用这一档自己算出来的阈值（`citation_records_vs_bibitems`
            # 就是"每条 `\bibitem` 一条记录"）；连它都没有时才是缺省的 1。
            implicit = detail.get("implicit_min")
            if implicit is None:
                # 只声明了上限的档（`unfinished_request_rows`）：它的达标线是 `<= max`，
                # 下限是 0 —— 这里若退回缺省的 1，"队列干净"反而会被读成不达标。
                want_min = 0 if detail.get("implicit_max") is not None else 1
            else:
                want_min = int(implicit)
        if want_max is None and detail.get("implicit_max") is not None:
            want_max = int(detail["implicit_max"])
        ok_row = got >= want_min and (want_max is None or got <= want_max)
        out.append({"id": cid, "name": name, "kind": kind, "min": want_min, "max": want_max,
                    "got": got, "ok": ok_row, "detail": detail})
        if not ok_row:
            if got < want_min:
                why = f"{got} 条，要求 ≥ {want_min} 条"
            else:
                why = (f"{got} 条，上限 {want_max} 条（这一档要的是「上限」："
                       f"越多越不达标 —— 0 才是达标）")
            unmet.append(f"{cid}（{name or LEG_CHECK_KINDS[kind]}）：{why} —— 读数 {detail}"
                         + (f"；{note}" if note else ""))

    rep.readings["acceptance"] = {"checks_file": str(path), "rows": out}
    if out and len(na_rows) == len(out):
        rep.status["acceptance"] = "fail"
        rep.findings.append(Finding(
            "acceptance", "acceptance_all_na", "blocker",
            "验收表里**每一行都标了 `na`** ⇒ 这一趟没有任何可复算的口径。"
            "`na` 是给「这一档对这个项目天然不适用」用的，不是给「这一趟什么都没做」用的 —— "
            "至少要有几行是真的按台账现算的"))
        return
    # ---- 覆盖面（`draft/37` §137）：研究型项目的验收表要覆盖研究链四个环节。
    # 「0 也是读数」：所以缺的是那一行，不是那个数（写 0 与删掉一行都会红，
    # 但前者留下读数、后者留下一个空环节 —— 两者分开报）。
    try:
        chain = research_chain_gaps(store, [str(r.get("kind") or "") for r in out],
                                    na_kinds=[str(r.get("kind") or "") for r in out
                                              if r.get("na") is True])
    except RuntimeError as exc:
        rep.status["acceptance"] = "unknown"
        rep.findings.append(Finding(
            "acceptance", "acceptance_chain_unreadable", "warning",
            f"{exc} ⇒ 研究链覆盖面这一格没查成（不是「覆盖齐了」）"))
        return
    rep.readings["acceptance"]["research_chain"] = chain
    if chain["missing"]:
        unmet.append("研究链覆盖面：验收表里一行都没有的环节 —— " + "；".join(chain["missing"]))
    # ---- 稿子改完之后有没有再复核（`draft/39` §6.46 的 D57）：验收表里没写这一档时，
    # 门替它报出来 —— 否则「G.revise 追加的断言从未被审过」可以整趟静默留下
    # （T5 第 5 趟：`review_findings` 0 条、七格全绿，而现行版 `68bfc4c7…` 没有任何签名）。
    # 这一档写进验收表时由它自己那一行判（含 `na` + 理由那条出口），门不重复说话。
    if "reviewed_current_rows" not in {str(r.get("kind") or "") for r in out}:
        try:
            _got, cur_detail = _leg_reading(
                store, "reviewed_current_rows",
                Path(resolve_under_workspace(store, project_dir)))
        except Exception:  # noqa: BLE001 —— 读不出来时这一档不算数（`acceptance_leg_unreadable` 管那一档）
            cur_detail = None
        stale = list((cur_detail or {}).get("stale_signoffs") or [])
        if stale:
            unmet.append(
                "现行版本没有被审校记录钉住的稿件："
                + "；".join(f"{s.get('doc_id')}（现行版 {s.get('current')}…，"
                            f"签名钉的是 {'、'.join(s.get('signed') or []) or '（空）'}…，"
                            f"status={s.get('status')} revision={s.get('revision')}）"
                            for s in stale)
                + " —— 改完之后没再复核（G.revise 把稿子推成 revised，而签名还钉着改之前"
                  "那一版）⇒ 交付里会带着没审过的断言。派 `H.verify_fixes` / `H.review` 复核"
                  "现行版；确实要这样交，就在验收表里写一行 `reviewed_current_rows` 并标 "
                  "`\"na\": true` + 理由")
    # ---- 稿件是骨架还是手稿（`draft/39` §6.48 的 D63）：有 sections 却每节都空的行，
    # 验收表里没写这一档时由门报出来（真机读数 T5 第 7 趟 `p8g`：三节 body 全是空串）。
    if "document_body_rows" not in {str(r.get("kind") or "") for r in out}:
        try:
            _got, body_detail = _leg_reading(
                store, "document_body_rows",
                Path(resolve_under_workspace(store, project_dir)))
        except Exception:  # noqa: BLE001 —— 读不出来时这一档不算数
            body_detail = None
        hollow = list((body_detail or {}).get("empty_section_docs") or [])
        if hollow:
            unmet.append(
                "交付的稿件只有骨架、没有正文："
                + "；".join(f"{h.get('doc_id')}（{len(h.get('empty') or [])} 节 body 为空："
                            f"{'、'.join(h.get('empty') or [])}）" for h in hollow)
                + " —— 有 headings 却每一节都没写正文的稿子是骨架，不是手稿。"
                  "把每一节的正文写进去（`G.build_document` 的 `sections` 要带 `body`）；"
                  "确实是清单型交付（没有 sections），就在验收表里写一行 `document_body_rows` "
                  "并标 `\"na\": true` + 理由")
    # ---- 断言与它引的证据对不对得上（`draft/39` §6.48 的 D61/D62）：验收表里没写这一档时，
    # 门把「对不上」的那些断言逐条报出来（真机读数 T5 第 7 趟 `p8g`：两条 exp 引用互换、
    # 一条 lit 引用跑题，而所有机械读数全绿）。
    if "claim_evidence_fit_rows" not in {str(r.get("kind") or "") for r in out}:
        try:
            fit = citation_fit(store)
        except Exception:  # noqa: BLE001 —— 读不出来时这一档不算数
            fit = None
        bad = list((fit or {}).get("mismatches") or [])
        if bad:
            unmet.append(
                "断言与它引的证据对不上（确定性判据：数字特征/实词特征无交集）："
                + "；".join(f"{b.get('doc_id')}/{b.get('claim_id')}"
                            f"（引 {'、'.join(b.get('citations') or [])}："
                            f"{'；'.join(b.get('why') or [])}）" for b in bad)
                + " —— 把引文改成真的支持这条断言的那一条（或改断言让它与证据相符）；"
                  "确实要这样交，就在验收表里写一行 `claim_evidence_fit_rows` 并标 "
                  "`\"na\": true` + 理由")
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
