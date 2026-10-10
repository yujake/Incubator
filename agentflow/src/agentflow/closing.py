# -*- coding: utf-8 -*-
"""收工门（`draft/37` §16 P3）：把"能不能交"从一句判断变成八格各自能造红的读数。

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
| `report_shape` | 报告形状：附件三件套判实（来源 / 依据 / 版本 sha）+ M 声明的体例有没有兑现 |
| `user_pending` | 没有还在等用户回答的问题（有 ⇒ 必须停在"等待用户"，不许续跑） |
| `substance` | 实质产出：`documents` / `relations` / `experiments` / `review_findings` / `statements` 至少一张非空（全 0 ⇒ 不许报「可交付」；`tasks`/`usage_ledger` 不算 —— 派过活、花过钱可以在什么都没产出时也非空） |
| `artifact_ledger` | 产物台账（`ARTIFACTS.jsonl`）与盘上一致：`missing`/`unreadable` ⇒ `fail`，只有 `changed` ⇒ `unknown`（登记后被正常改写是常态） |

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
from . import schema as S
from . import textutil as T
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
    # 第八格（EE-05，`draft/52` C4）：产物台账必须与盘上一致。
    # 「进格」是人的裁定（`draft/46-04` §2.10 ③ 原本把它列为独立裁定项）；
    # 但判据强度按三态收窄：`changed` 记 `unknown`（登记之后被正常改写是常态），
    # 只有 `missing`/`unreadable` 判 `fail`。
    "artifact_ledger",
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
    "reviewed_then_digested_rows": "**审过之后有没有被逐条消化**：`status ∈ accepted/revised` 的"
                                   "`documents` 行里，至少有一条断言已经落成 `statements` 行"
                                   "（`origin=own_result`、`doc_id` 指向该稿件、`kind != \"concept\"`）"
                                   "的份数 —— 缺省阈值 1。它问的是「审完之后有没有人把它变成可引的"
                                   "台账行」，与 `reviewed_current_rows` 分工：后者问「审过没有」。"
                                   "为什么单列（业主 2026-10-09：「D 的手稿过审后是否被 B 消化或"
                                   "研究成果逐条入库。前置条件具备了，C 才能在里面找依赖链」）："
                                   "T2 第 22 趟（`t2a`）现场就是「① 手稿成稿、② H 过审」都有而 "
                                   "`statements=0` —— 没有任何读数说得出来缺的是这一环，"
                                   "而 C 的依赖链正是建在它上面。明细里按「定理 N 条 / 定义 M 条 / "
                                   "审过 D 份 / 消化 X 份」分列（定义也入库那一档要看得见）",
    "manuscript_edited": "可改的主稿有没有**实质**改动（`out/paper/main.tex` 与只读基线 "
                         "`source/main.tex` 去空白规范化之后仍不相同 ⇒ 1，相同 ⇒ 0）——"
                         "缺只读基线时这一行记 `not_applicable`（E-05 ③ / CC-05）",
    "citation_records_vs_bibitems": "逐条核验引文：带比对记录的行数（`statements`/`relations` 里 "
                                    "`quote_verified` 非 null，或 `quote_reason` 非空 —— 后者是"
                                    "三态里的「未查+理由」）要不少于**只读基线** `source/main.tex` "
                                    "里 `bibitem` 的条数（分母不许由可改的主稿自己给，E-05 ②）",
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
    "numeric_experiment_rows": "给了结论的数值/计算实验条数（`experiments` 里 `method=numeric` "
                               "且 `result` 是 `supports`/`refutes`、带 `search_bound` 或 "
                               "`certificate`）—— 从零做研究时「先算一遍」是最便宜的证据来源，"
                               "但「跑过」不是产出、「跑出结论」才是（`draft/39` §6.49 的 D66，"
                               "用户 2026-10-06 裁：全是 `inconclusive` 的 10 条实验不该让这一环变绿；"
                               "`method=formal` 那一档另有 `proof_experiment_rows` 管）",
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
    # ---- EE-05（`draft/44` J-24 / `draft/52` C4）：产物台账与盘上一致吗
    "artifact_ledger_bad_rows": "**产物台账对不上盘上**的行数（`ARTIFACTS.jsonl` 里逐条重算 "
                               "sha256：`changed`（内容变了）+ `missing`（盘上没了）+ "
                               "`unreadable`（读不到）—— 三档分开报，**不折成一个布尔**）。"
                               "这一档的方向与 `unfinished_request_rows` 同一根轴："
                               "**越少越好**（`implicit_max = 0`）。为什么单列（`draft/43-D` "
                               "§2.4 / `draft/44` 批次 5 的红线「产物登记必须与盘上一致」）："
                               "`renderanchor` 只盯 PDF 那一维（回执里的 `pdf_sha256`），"
                               "而「这份登记过的产物还是不是登记时那一版」在收工门上**没有任何读数**。"
                               "注意三态：`changed` 在真机上是**常见**的（根 B 589 条 ≈18.75%："
                               "登记之后又被正常改写），所以 `DEFAULT_CHECKS` 的第八格只把 "
                               "`missing`/`unreadable` 判 `fail`，`changed` 记 `unknown`"
                               "（把正常产物读成坏正是这一格要防的假读数）",
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
    na_only: list[str] = []
    missing: list[str] = []
    for label, members in RESEARCH_CHAIN_GROUPS:
        hit = [k for k in members if k in used]
        marked = [k for k in members if k in na_used]
        # 真的按台账算过的那些行（E-04b 的读数口径）：`hit` 里去掉只靠 `na` 顶着的。
        computed = [k for k in members if k in used and k not in na_used]
        groups[label] = hit
        na_groups[label] = marked
        if not computed and marked:
            # E-04b（`draft/52` C1）：整环只有 `na` 行 —— 如实报出来（读数级），
            # 但不改 `missing` 的算法、不判 fail/unknown：`na` 是 D49 明确要保留的
            # 第三态出口，"这一行算不算把整环覆盖了"是语义判断（裁决 5 归 M/秘书）。
            # 机器只保证这件事看得见（`draft/49-03` 决策 1 方案 A）。
            na_only.append(label)
        if researched and not hit and not marked:
            missing.append(f"{label}（可以写 {' / '.join(members)} 里的任意一档；"
                           f"这一档天然不适用就在那一行上写 `\"na\": true` 并写明理由）")
    return {
        "researched": researched,
        "rows": len(used),
        "groups": groups,
        "na_groups": na_groups,
        #: 只被 `na` 行覆盖的环节（E-04b 的读数）。它的存在不改变 `missing`：
        #: 一行 `na` 依旧让整环在覆盖面这一层"算覆盖"，但这件事现在是看得见的。
        #: 判"算不算覆盖"由 M/秘书做（`draft/52` 裁决 5 / C1）。
        "na_only_groups": na_only,
        "missing": missing,
        "note": ("研究型项目（有 `research_questions` 行）的验收表要覆盖研究链八个环节，"
                 "每个环节至少一行。覆盖面管的是「那一行在不在」；那一行的读数够不够"
                 "由它自己那一档判（`min` 缺省时按该档的口径，多数是 ≥ 1；"
                 "`unfinished_request_rows` 那一档的方向相反 —— 它的缺省口径是 ≤ 0）—— "
                 "所以删掉一行与写着 0 都会红，但后者留下的是读数，前者留下的是一个空环节。"
                 "某一档对这个项目**天然不适用**时（例如调查型任务没有「算或造」那一步），"
                 "在那一行上写 `\"na\": true` 并在 `note` 里写明理由 —— `na` ≠ 通过 ≠ 失败。"
                 "`na_only_groups` 是**读数**：哪些环节只被 `na` 行撑着 —— 它不改变 `missing`，"
                 "「一行 `na` 算不算把整环覆盖了」由 M / 秘书判断（机器只保证这件事看得见）。"
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


def claim_evidence_fit(
    claim: Mapping[str, Any],
    *,
    exps: Mapping[str, Mapping[str, Any]],
    lits: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """一条断言与它引的证据对不对口 —— 逐条判据的唯一实现（`D61`/`D62`）。

    两个调用方共用它，这是刻意的（`R003` 那条纪律：同一判据不许有第二份实现）：

    - `citation_fit`（收工门那一档，读全库）；
    - `doc_tools.citation_coverage`（写稿那一刻的读数）—— T4 第 3 趟 `t4c` 的真机读数
      逼出来的：那一趟 `documents/0000` 的 5 条断言里 2 条把数学教育论文当出处，
      收工门的 `citation_fit` 点名了、M 调了 5 次 `closing` 看到之后仍按 met=true 收工；
      而写稿期那条读数当时只报"引了几条"，不报"对不对口"。
      同一份判据放到写稿那一刻，才有机会在收工前改掉。

    判据分两条腿，都是特征交集（详见 `citation_fit` 的 docstring）：
    引 `exp:` 比整数特征，引 `lit:` 比英文实词；两侧任一侧没有可判特征 ⇒ `unjudged`
    （"没查成"，绝不读成"对上了"）。
    """
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
    return {"verdict": verdict, "why": why[:3],
            "numbers_in_claim": sorted(claim_nums)[:6],
            "words_in_claim": sorted(claim_words)[:6]}


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
            # 逐条判据只有一份实现（`claim_evidence_fit`，写稿期那条读数共用它）。
            one = claim_evidence_fit(claim, exps=exps, lits=lits)
            checked.append({"doc_id": str(doc.get("doc_id") or ""),
                            "claim_id": str(claim.get("claim_id") or ""),
                            "citations": [str(c) for c in (claim.get("citations") or [])],
                            "verdict": one["verdict"], "why": one["why"],
                            "numbers_in_claim": one["numbers_in_claim"],
                            "words_in_claim": one["words_in_claim"]})
    fits = [c for c in checked if c["verdict"] == "fit"]
    bad = [c for c in checked if c["verdict"] == "mismatch"]
    unknown = [c for c in checked if c["verdict"] == "unjudged"]
    return {"claims": checked, "fit": len(fits), "mismatch": len(bad), "unjudged": len(unknown),
            "judged": len(fits) + len(bad), "mismatches": bad[:8], "unjudged_rows": unknown[:8]}


# ============================================================ 内容判据（D66 / D67 / T1 / T3 口径）

#: 「算」那一环算不算有结论（`draft/39` §6.49 八 的 D66，用户 2026-10-06 裁）：
#: 「跑过实验」不是产出，「跑出结论」才是。这两个取值就是 `EXPERIMENT_RESULTS` 里
#: 的非 `inconclusive` 两项（见 `schema.EXPERIMENT_RESULTS`）。
CONCLUSIVE_EXPERIMENT_RESULTS: tuple[str, ...] = ("supports", "refutes")

#: 论文正文里算「本轮结果」的台账前缀（T3 口径）。元素形态与
#: `schema.Document.claims` 的 `citations` 一致（`stmt:` / `exp:` / `rel:`）；
#: 为什么不把 `lit:` 算进来：引文献说明的是「别人做过」，承载本轮结果的是
#: 我们自己的命题 / 实验 / 关系（这三个前缀各有一张本工作区的表）。
PAPER_LEDGER_PREFIXES: tuple[str, ...] = ("stmt:", "exp:", "rel:")

#: 论文里「核查章节」的节名特征（T3 口径：核查章节不能替代结果章节）。
#: 真机读数（`p6r-paper-from-results/out/paper/main.tex` 第 112 行）：那一篇 5 节里
#: 有一节叫 `Evidence and status`，本轮结果（`exp:0008`）只出现在那一节里。
PAPER_CHECK_SECTION_WORDS: tuple[str, ...] = (
    "evidence", "status", "verification", "verify", "audit", "check",
    "limitation", "disclaimer", "self-check",
    "核查", "核验", "验证", "证据", "状态", "局限", "自检",
)


def experiment_concludes(row: Mapping[str, Any]) -> bool:
    """这一条实验有没有给出结论（D66「算」半边的机械判据）。

    三条同时成立才算：

    1. `result` 是 `supports` / `refutes`（`inconclusive` 不是结论 —— 真机读数
       T2 `p6q`：10 条实验全 `inconclusive`，而旧口径照样让「算」那一环变绿）；
    2. 结论带着它的适用范围：`search_bound` 或 `certificate` 非空
       （用户原话「supports|refutes + 界/证书」）—— 脱开边界的「在 N 以内没有反例」
       是一句无法复核的话，`schema` 对穷举类已经强制这一条（见 `Experiment.validate`）；
    3. 形式化那一支（`method="formal"`）走检查器输出的口子：`evidence_kind="proof"`
       且 `verifier_output` 非空（`schema` 同样已强制）。
    """
    if str(row.get("result") or "") not in CONCLUSIVE_EXPERIMENT_RESULTS:
        return False
    if str(row.get("evidence_kind") or "") == "proof" \
            and str(row.get("verifier_output") or "").strip():
        return True
    if row.get("certificate"):
        return True
    return bool(row.get("search_bound"))


def _tex_sections(text: str) -> list[tuple[str, str]]:
    """把 LaTeX 主稿按 `\\section{...}` 切成 `(标题, 正文)`。

    没有 `\\section` 时整篇算一节（标题为空串）—— 「这一个工作区没有分节」是读数，
    不是「读不出来」。
    """
    marks = list(re.finditer(r"\\section\*?\{([^{}]*)\}", text))
    if not marks:
        return [("", text)]
    out: list[tuple[str, str]] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1).strip(), text[m.end():end]))
    return out


def _is_check_section(title: str) -> bool:
    """这一节的标题像不像「核查 / 证据 / 状态」那一类（T3 口径）。"""
    low = title.lower()
    return any(w in low for w in PAPER_CHECK_SECTION_WORDS)


def paper_ledger_reading(project_root: Path) -> dict[str, Any]:
    """论文有没有承载本轮结果（T3 口径，用户 2026-10-06 裁）。

    三条读数（都不看自述，只看 `out/paper/main.tex` 这一份盘上的稿子）：

    - `bibitems`：主稿里 `\\bibitem` 的条数（真机读数 `p6r`：1 条）；
    - `result_sections`：正文里出现 `stmt:` / `exp:` / `rel:` 的非核查章节
      （这一条才是「承载本轮结果」：真机 `p6r` 的 `exp:0008` 只出现在
      `Evidence and status` 那一节里 ⇒ 结果被写进了核查章节）；
    - `check_sections`：只出现在核查章节里的那些引用（读数，用来分开报）。

    没有 `out/paper/main.tex` ⇒ `LegNotApplicable`（这个工作区没有论文，
    这一档用不上；不是「查过了没问题」）。
    """
    draft = Path(project_root) / "out" / "paper" / "main.tex"
    if not draft.is_file():
        raise LegNotApplicable("paper_ledger_rows", f"这个工作区没有论文主稿：{draft}")
    text = draft.read_text(encoding="utf-8", errors="replace")
    result_sections: list[dict[str, Any]] = []
    check_sections: list[dict[str, Any]] = []
    for title, body in _tex_sections(text):
        cites = sorted({f"{p}{m}" for p in PAPER_LEDGER_PREFIXES
                        for m in re.findall(re.escape(p) + r"(\d{3,4})", body)})
        if not cites:
            continue
        item = {"section": title[:60], "citations": cites[:6]}
        (check_sections if _is_check_section(title) else result_sections).append(item)
    return {
        "manuscript": "out/paper/main.tex",
        "bibitems": text.count("\\bibitem"),
        # 这一份到底是不是一篇论文（T3 口径只在它是论文时说话）：真机上
        # `p6r-paper-from-results/out/paper/main.tex` 是 `\documentclass{article}` 起头的
        # 5 节稿；而测试夹具与某些工作区里那一份只是一个占位文件（`\date{}` + 一行 body），
        # 拿"参考文献 ≥ 2"去要求占位文件是判错了对象。
        "looks_like_article": ("\\documentclass" in text or "\\begin{document}" in text),
        "sections": [t[:60] for t, _ in _tex_sections(text)],
        "result_sections": result_sections,
        "check_sections": check_sections,
        "result_citations": sorted({c for s in result_sections
                                   for c in s["citations"]})[:8],
        "check_citations": sorted({c for s in check_sections
                                  for c in s["citations"]})[:8],
    }


def c_products_in_delivery(store: Any, project_root: Path) -> dict[str, Any]:
    """C 的分析产物有没有进交付面（`draft/39` §6.49 八 的 D67）。

    真机读数（T5 第 7 趟 `p8g-fermat-shorter-proof`）：`tasks` 里 role=C 四行
    `done`（`hottest` / `contradictions` / `gaps` / `cold`）、`relations` 107 行，
    而 `analysis_reports` 0 行、手稿 `refs` 里一条 `rel:` 都没有 ——
    C 是这几趟里唯一产出真知识的角色，产物却被扔掉了。

    两条出口（任一成立就算进了交付面）：

    - `rel:` 引用出现在手稿账本的 `refs` 里，或出现在 `documents` 的断言
      `citations` 里（`manuscripts.OBJECT_REFS` 已经认这个前缀并逐条校验指向的
      关系行在不在册）；
    - 或 `analysis_reports` 有行（C 的报告落进了 `reports/<id>-<kind>.md`
      与那张表）。
    """
    from . import manuscripts as MS

    rel_refs: list[str] = []
    try:
        all_rows, _bad = MS.read_rows(project_root)
    except Exception:  # noqa: BLE001 —— 账本读不出来时这一条不算数（不当成"没有"）
        all_rows = []
    for row in all_rows:
        for ref in (row.get("refs") or []):
            if str(ref).startswith("rel:"):
                rel_refs.append(f"{row.get('id')}:{ref}")
    doc_rel_refs: list[str] = []
    for doc in store.rows("documents"):
        for claim in (doc.get("claims") or []):
            if not isinstance(claim, Mapping):
                continue
            for cite in (claim.get("citations") or []):
                if str(cite).startswith("rel:"):
                    doc_rel_refs.append(f"{doc.get('doc_id')}/{claim.get('claim_id')}:{cite}")
    reports = [dict(r) for r in store.rows("analysis_reports")]
    return {
        "manuscript_rel_refs": rel_refs[:8],
        "document_rel_refs": doc_rel_refs[:8],
        "analysis_reports": len(reports),
        "report_kinds": sorted({str(r.get("kind") or "") for r in reports})[:6],
    }


def content_leg_unmet(store: Any, project_root: Path, *,
                      researched: bool,
                      computed_kinds: Iterable[str]) -> tuple[list[str], dict[str, Any]]:
    """五条内容判据（`draft/39` §6.49 八；用户 2026-10-06 裁「产出太保守」）。

    为什么要有这一批（用户逐字）：「我检查了 T1 到 T4 的产出，都是颇为保守（即根本
    没啥实质的研究产出，功夫全用在核查上了）……看 handoffs 里面没有几条有效信息全在
    强调纪律」。根因的第一层写在同处：门的判据只会因为「过程/诚实」问题拦人，
    永远不会因为「这数学太平凡」拦人，而最省力的过关方式是如实记缺口
    （`na` + 理由）⇒ 系统学到的是「少做、如实说」。

    这一批把五条「过程读数」升级成「产出读数」（前四条对应 §6.49 八的四条，
    第五条是 T5 第 7 趟暴露的「论文没承载本轮结果」）：

    1. 「算」那一环要结论（D66 算半边，只对研究型项目说话）；
    2. 「造」那一环要我方派生的命题（D66 造半边，只在表里声明了这一环时判）；
    3. C 的分析产物要进交付面（D67）；
    4. 逐字引文一条都没核到不算交付（T1 口径）；
    5. 论文要承载本轮结果（T3 口径）。

    三态纪律：读不出来的一律不当成「没有」（那一档各自 try 住，读数里留 `unreadable`）。
    """
    kinds = {str(k) for k in computed_kinds}
    unmet: list[str] = []
    readings: dict[str, Any] = {}

    # ---- ① 「算」那一环要结论（D66 算半边）。
    # 只在「表里真的声明了这一环」时判（`kinds` = 真算过的行）：研究链覆盖面那一格
    # 已经管「一行都没写」，这一格管的是「写了却说不出结论」。这样既不会误伤
    # 调查型项目（T4 的清单不声明算/造），也不会被 `na` 关掉（E-04a 的守卫口径）。
    compute_leg_kinds = {"numeric_experiment_rows", "search_frontier_rows",
                         "enumeration_optimization_rows", "reviewed_proof_rows",
                         "counterexample_or_proof_rows"}
    declared_compute_leg = bool(kinds & compute_leg_kinds)
    exps = [dict(r) for r in store.rows("experiments")]
    conclusive = [e for e in exps if experiment_concludes(e)]
    inconclusive_ids = [str(e.get("experiment_id") or "") for e in exps
                        if str(e.get("result") or "") not in CONCLUSIVE_EXPERIMENT_RESULTS]
    readings["compute_leg"] = {
        "experiments": len(exps), "conclusive": len(conclusive),
        "conclusive_ids": [str(e.get("experiment_id") or "") for e in conclusive[:8]],
        "inconclusive": len(inconclusive_ids), "inconclusive_ids": inconclusive_ids[:8],
        "researched": bool(researched), "declared": declared_compute_leg,
    }
    if researched and declared_compute_leg and exps and not conclusive:
        unmet.append(
            f"「算」那一环没有结论：{len(exps)} 条实验里 {len(inconclusive_ids)} 条 "
            f"`result=inconclusive`（{'、'.join(inconclusive_ids[:6])}），"
            f"没有一条给出 `supports` / `refutes` + 界或证书 —— "
            "「跑过实验」不是产出，「跑出结论」才是：把实验做到能下结论"
            "（给出 `search_bound` / `certificate`，形式化那一支给出 `verifier_output`），"
            "或者如实把结论写成「这一族在界 B 内无反例（证书 …）」")

    # ---- ② 「造」那一环要我方派生的命题（D66 造半边）。
    if kinds & {"reviewed_proof_rows", "counterexample_or_proof_rows"}:
        stmts = [dict(r) for r in store.rows("statements")]
        own = [s for s in stmts if str(s.get("origin") or "") == "own_result"]
        basis = [s for s in own if list(s.get("derived_from") or [])
                 or str(s.get("source_lit_id") or "").strip()]
        readings["construct_leg"] = {
            "statements": len(stmts), "own_result": len(own), "with_basis": len(basis),
            "own_ids": [str(s.get("stmt_id") or "") for s in own[:8]],
        }
        if not basis:
            unmet.append(
                f"「造」那一环没有我方派生的命题：`statements` {len(stmts)} 行里 "
                f"`origin=own_result` 的 {len(own)} 行，其中**没有任何一行写清它派生于什么**"
                f"（`derived_from` 与 `source_lit_id` 都是空的）—— "
                "「造」= 我方自己提出并证明的命题（`origin=own_result`），"
                "而且要说清它由哪几条已登记的命题 / 哪一篇文献推出来；"
                "把命题与它的来路一起登记（`B.register_statement` / `D.register_conjecture`）")

    # ---- ③ C 的分析产物要进交付面（D67）。
    try:
        c_runs, _c_detail = _leg_reading(store, "c_analysis_runs", project_root)
    except Exception:  # noqa: BLE001 —— 读不出来时这一条不算数
        c_runs = 0
    c_face = c_products_in_delivery(store, project_root)
    c_face["c_analysis_runs"] = c_runs
    readings["c_delivery"] = c_face
    in_delivery = bool(c_face["manuscript_rel_refs"] or c_face["document_rel_refs"]
                       or c_face["analysis_reports"])
    if c_runs and not in_delivery:
        unmet.append(
            f"C 的关系分析跑了 {c_runs} 次，而**产物一条都没进交付面**"
            f"（手稿 `refs` 里 0 条 `rel:`、文档断言里 0 条 `rel:`、"
            f"`analysis_reports` 0 行）—— 用户点名「重点考察 C」，"
            "而 C 的读数（`hottest` / `gaps` / `contradictions`）至少要能被交付物引到："
            "在手稿或文档断言里引一条 `rel:` 编号（`refs: [\"rel:0007\"]`，"
            "`manuscripts` 会校验它指向的关系行在不在册），"
            "或让 C 的分析报告落进 `reports/<id>-<kind>.md` 与 `analysis_reports` 表")

    # ---- ④ 逐字引文一条都没核到不算交付（T1 口径）。
    # 只看 `origin="external_lit"` 的行：`quote_verified` 管的是「文献里的原文摘录有没有
    # 逐字核过」，我方自产的命题（`own_result`）本来就没有外部原文可比对 —— 把
    # 自产命题算进来会把「自己证的定理」当成「没核到的引文」（真机 T1 的 7 行全是
    # `external_lit`：`projects/p5-review-t17/data/statements.json`）。
    base = project_root / "source" / "main.tex"
    quote_rows = [dict(r) for r in store.rows("statements")
                  if str(r.get("origin") or "") == "external_lit"]
    verified = [q for q in quote_rows if q.get("quote_verified") is True]
    baseline_bibitems = (base.read_text(encoding="utf-8", errors="replace").count("\\bibitem")
                         if base.is_file() else 0)
    readings["quote_verification"] = {
        "baseline": "source/main.tex", "baseline_bibitems": baseline_bibitems,
        "citation_rows": len(quote_rows), "verified": len(verified),
        "unverified_ids": [str(q.get("stmt_id") or "") for q in quote_rows
                           if q.get("quote_verified") is not True][:8],
    }
    if baseline_bibitems and quote_rows and not verified:
        unmet.append(
            f"逐字引文一条都没核到：只读基线 `source/main.tex` 有 {baseline_bibitems} 条 "
            f"`\\bibitem`，台账里 {len(quote_rows)} 条引文记录**没有一条 "
            f"`quote_verified=True`** —— 「哪几条没查到」本身不是交付（T1 口径）："
            "原文取不回就派检索把原文取回来、或者换成核得到的引文；"
            "只有真的取不回才允许记「未核到」，而且要在 `quote_reason` 里写清"
            "为什么解决不了（不是把同一句「原文未取回」抄 N 遍）")

    # ---- ⑤ 论文要承载本轮结果（T3 口径）。
    # 只在「这一趟是从结果写论文」时判：T1 那一类审阅项目的 `out/paper/main.tex`
    # 是被审的稿件本身（只读基线 `source/main.tex` 在盘上），它的参考文献与
    # 引用形态由原稿决定 —— 拿 T3 的口径去判它是判错了对象（同 `draft/38` §7 的
    # 「review 项目不触发研究链那一环」）。T3 的工作区没有只读基线。
    has_baseline = (project_root / "source" / "main.tex").is_file()
    try:
        paper = paper_ledger_reading(project_root) if not has_baseline else None
    except LegNotApplicable:
        paper = None
    except Exception as exc:  # noqa: BLE001 —— 读不出来时留读数
        paper = None
        readings["paper_leg"] = {"unreadable": f"{type(exc).__name__}: {exc}"}
    if paper is not None and not paper.get("looks_like_article"):
        # 占位文件（不是论文）⇒ 这一档不说话，但读数留着（"为什么没判"要看得见）。
        readings["paper_leg_note"] = ("out/paper/main.tex 不是一篇论文（没有 "
                                      "`\\documentclass` / `\\begin{document}`）⇒ "
                                      "T3 口径这一档不判它")
        paper = None
    if paper is not None:
        readings["paper_leg"] = paper
        if int(paper["bibitems"]) < 2:
            unmet.append(
                f"论文的参考文献只有 {paper['bibitems']} 条（`out/paper/main.tex` 里 "
                f"`\\bibitem` 的条数）—— 一篇承载研究结果的论文不会只引 1 条文献："
                "把本轮实际用到的文献（`literature` 里取回的那些）写进参考文献")
        if not paper["result_sections"]:
            only = ("；只出现在核查章节里：" + "、".join(paper["check_citations"])
                    if paper["check_citations"] else "")
            unmet.append(
                "论文没有在**正文结果章节**里引本轮台账（`stmt:` / `exp:` / `rel:`）"
                f"{only} —— 核查章节（节名带 evidence / status / 核查 / 证据 那一类）"
                "不能替代结果章节：把本轮的结果（命题 / 实验 / 关系）写进结果章节并就地引用")

    return unmet, readings


def artifact_ledger_reading(project_root: Path) -> tuple[int, dict[str, Any]]:
    """产物台账（`ARTIFACTS.jsonl`）与盘上一致吗（EE-05，`draft/52` C4）。

    返回 `(对不上的行数, 明细)`；三档分开报，不折成一个布尔：

    - `changed`：登记时钉的 sha256 与盘上现在这一版不同（登记之后被改写）；
    - `missing`：台账里登记过、盘上没了；
    - `unreadable`：文件在但读不到（`OSError`），外加台账里读不出来的行（`bad_lines`）。

    台账不在盘上 ⇒ `LegNotApplicable`（"这个工作区没有产物台账"是"没有这一栏"，
    不是"查过了没问题"；由调用方按各自的三态纪律落读数）。
    """
    from . import artifacts as A

    led = A.ledger_path(project_root)
    if not led.is_file():
        raise LegNotApplicable(
            "artifact_ledger_bad_rows", f"这个工作区没有产物台账：{led}")
    records, bad_lines = A.read_ledger(project_root)
    # ---- D9（业主 2026-10-09 裁"收窄"，即选择题 T1c 的 1c-1）：
    # 台账是 append-only 历史，逐行比必然把任何被改写过的文件读成 `changed`
    # （真机 t1u：23 条全是框架自己幂等重写的 `out/tasks/*.json`）⇒
    # 按路径取最后一条登记比 —— 那才是"交出去的那一版"。
    latest: dict[str, dict[str, Any]] = {}
    for rec in records:
        latest[str(rec.get("path") or "")] = rec        # 后写覆盖先写 = 取最后一条
    rows = A.verify_entries(project_root, list(latest.values()))
    counts: dict[str, int] = {"ok": 0, "changed": 0, "missing": 0,
                              "unreadable": 0, "not_a_file": 0}
    for r in rows:
        counts[str(r.get("status") or "unknown")] = \
            counts.get(str(r.get("status") or "unknown"), 0) + 1
    bad = [r for r in rows if str(r.get("status") or "") != "ok"]
    unreadable = counts.get("unreadable", 0) + len(bad_lines)
    changed = counts.get("changed", 0)
    missing = counts.get("missing", 0) + counts.get("not_a_file", 0)
    got = changed + missing + unreadable
    detail: dict[str, Any] = {
        "ledger": str(led), "entries": len(rows),
        "ok": counts.get("ok", 0), "changed": changed,
        "missing": missing, "unreadable": unreadable,
        # 这一档的方向是「上限」：0 才是达标（与 `unfinished_request_rows` 同一根轴）。
        "implicit_max": 0,
        "bad_rows": [{"path": r.get("path"), "status": r.get("status")}
                     for r in bad[:8]],
        "note": ("产物台账要和盘上一致：`renderanchor` 只盯 PDF 那一维"
                 "（回执里的 `pdf_sha256`），这一档盯的是**每一条登记过的产物**。"
                 "**按路径取最后一条登记**比（D9：台账是 append-only 历史，"
                 "逐行比会把正常改写读成 changed）。三态分开报："
                 "`changed`（最后一次登记之后又被改写 ⇒ **pass + warning**，"
                 "可见性不减）、`missing`（盘上没了 ⇒ 真缺陷）、"
                 "`unreadable`（读不到 ⇒ 没查成那一行）"),
    }
    if bad_lines:
        detail["ledger_bad_lines"] = bad_lines[:3]
    return got, detail


def _leg_reading(store: Any, kind: str, project_root: Path) -> tuple[int, dict[str, Any]]:
    """按受控档位现算一行验收读数 ⇒ `(条数, 明细)`。

    读不到时抛出去，由调用方落成 `unknown`（"问不出来"不许读成"没有"）。
    `project_root` 只有"要读盘上文件"的那几档用得上（台账那几档不看它）。
    """
    if kind == "artifact_ledger_bad_rows":
        return artifact_ledger_reading(project_root)
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
    if kind == "reviewed_then_digested_rows":
        # 「审过之后有没有被逐条消化」（业主 2026-10-09；口径与判据见 `draft/97` §9.4）。
        #
        # 为什么要有这一档：T2 第 22 趟（`t2a`）现场是「① 手稿成稿 + ② H 过审」都有、
        # 而 `statements=0`（手稿里的成果一条都没变成台账行）—— 收工门只报得出
        # "报告缺附件那一件"，没有任何一格说得出来缺的是"消化"这一环；
        # 而 C 的最短依赖链（`C.proof_chain`）正是建在它上面：
        # 前置条件具备了，C 才找得到依赖链。
        from . import signatures as SIG

        docs = [dict(r) for r in store.rows("documents")]
        stmts = [dict(r) for r in store.rows("statements")]
        claimed_statuses = tuple(SIG.SIGNABLE_STATUSES)
        reviewed = [d for d in docs if str(d.get("status") or "") in claimed_statuses]
        per_doc: dict[str, dict[str, int]] = {}
        digested: list[str] = []
        for d in reviewed:
            did = str(d.get("doc_id") or "")
            mine = [s for s in stmts
                    if str(s.get("doc_id") or "") == did
                    and str(s.get("origin") or "") == "own_result"]
            # `concept` 不算"成果"：它是依赖图上的节点（良定义性证明那一档），
            # 不是这一档要数的"手稿里的研究结果"。
            theorems = [s for s in mine if str(s.get("kind") or "") != "concept"]
            concepts = [s for s in mine if str(s.get("kind") or "") == "concept"]
            per_doc[did] = {"theorems": len(theorems), "concepts": len(concepts)}
            if theorems:
                digested.append(did)
        return len(digested), {
            "docs_reviewed": len(reviewed),
            "docs_digested": len(digested),
            "theorems": sum(v["theorems"] for v in per_doc.values()),
            "concepts": sum(v["concepts"] for v in per_doc.values()),
            # 未消化的逐份点名 + 出路（这一档红的时候要能直接照着做）
            "undigested": [{"doc_id": did, **per_doc[did]} for did in per_doc
                           if did not in digested],
            "next_step": ("手稿过了审而成果没逐条登记 ⇒ 派 B 的 `register_statement`"
                          "（`origin=own_result` + `doc_id`/`line_range` 作出处，"
                          "并把 `deps` 一起给）"),
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
        #: 「该被签」的状态单一来源 = `signatures.SIGNABLE_STATUSES`（E-07 / `draft/52` D5：
        #: `accepted` + `revised`）。这一档与 `signature_problems` 必须认同一组状态 ——
        #: 分叉的症状是"签名的判据说这份稿子没问题"而"这一档说它没被钉住"（真机 `p8e`：
        #: 两处相反）。`statuses_aligned` 把这件事变成当场的读数，而不是一句注释。
        claimed_statuses = tuple(SIG.SIGNABLE_STATUSES)

        def _records_of(doc_id: str) -> list[Mapping[str, Any]]:
            return [r for r in recs if str(r.get("doc_id") or "") == doc_id]

        claimed = [d for d in docs
                   if str(d.get("status") or "") in claimed_statuses
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
            # D5「两处都改」：这一档与 `signatures.SIGNABLE_STATUSES` 必须认同一组状态。
            # `statuses_aligned` 是当场的读数（不等就说明两处口径分叉了）。
            "signable_statuses": list(claimed_statuses),
            "statuses_aligned": tuple(claimed_statuses) == tuple(REVIEWED_DOC_STATUSES),
            # EE-10（`draft/44` J-24）：两条台账（产物 / 签名）只合并读法 ——
            # 读 JSONL 的那一层已经是唯一实现（`jsonlfile.read_jsonl`，`draft/36` T-6）。
            # 这里如实标出这一档读的是哪一条台账，好让"同一份产物被两个台账各钉一次"
            # 这件事看得见（两条台账钉的是不同哈希空间，不许合并本体）。
            "ledger_module": "signatures",
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
        # 「实质改动」那一半（`draft/46-04` §2.2 ③）：比 sha 会把"只差空白"
        # 也算成改过（一个字节即算），而任务要的是"把正文里的问题改掉"。
        # 判据改成"去空白规范化之后仍有差异"，并把两个读数并列出来
        # （`raw_changed` 是旧口径的数，`substantive` 才是这一档的取值）。
        if not draft.is_file():
            raise LegNotApplicable(kind, f"可改的主稿不在盘上：{draft}")
        if not base.is_file():
            # CC-05：缺只读基线 = 这一行不适用（`not_applicable`），
            # 不是"整张表没查成"。真机 `p6i` 的 P1 就是这一支
            # （`ValueError` ⇒ 整格 unknown ⇒ 后面 10 行连读数都没有）。
            raise LegNotApplicable(
                kind, f"只读基线不在盘上：{base}（比不出「改没改」）—— "
                      f"这一档要的是「主稿相对基线的实质改动」，没有基线就没有分母")
        d_raw = draft.read_text(encoding="utf-8", errors="replace")
        b_raw = base.read_text(encoding="utf-8", errors="replace")
        d_norm = re.sub(r"\s+", " ", d_raw).strip()
        b_norm = re.sub(r"\s+", " ", b_raw).strip()
        d_sha = RA.file_digest(draft)
        b_sha = RA.file_digest(base)
        same = d_sha == b_sha
        substantive = d_norm != b_norm
        return (0 if not substantive else 1), {
            "manuscript": "out/paper/main.tex", "baseline": "source/main.tex",
            "manuscript_sha256": d_sha, "baseline_sha256": b_sha,
            "manuscript_bytes": draft.stat().st_size, "baseline_bytes": base.stat().st_size,
            "edited": substantive, "raw_edited": not same,
            # E-05 ③ 的两个读数：`raw_changed` = 逐字节（旧口径），
            # `substantive` = 去空白后仍有差异（本档的取值，与 `got` 同义）。
            "raw_changed": not same, "substantive": substantive,
            "normalized_equal": not substantive,
        }
    if kind == "citation_records_vs_bibitems":
        # 「逐条」的那一档（`draft/37` §103）：把"有没有做过比对"换成"每条 `\bibitem` 都有记录"。
        # 为什么必须按条数比：§102 的第 12 趟只落了一条 `quote_verified=false` 就算满足了 ——
        # 那是"做一条就算"的口子，而任务原文要的是"逐条核验"。
        # 记录认两种：`quote_verified` 非 null（真/假两种比对结论），或 `quote_reason` 非空
        # （三态里的"未查 + 理由" —— 外部原文不在盘上时，这正是诚实的结论）。
        draft = project_root / "out" / "paper" / "main.tex"
        base = project_root / "source" / "main.tex"
        # E-05 ②：分母取只读基线（`source/main.tex`），不取可改的主稿。
        #
        # 为什么：这一档问的是"每条引文有没有比对记录"，而"要几条"这个分母
        # 若由可改的那份稿子自己给，写表的人（或模型）就能通过删文献
        # 把分母一起改小 —— 那是"自己给自己定阈值"（`draft/43-C` C-05/C-06）。
        # 只读基线是这一趟任务的输入，改不动 ⇒ 它才是分母的真源。
        # 基线不在盘上 ⇒ `LegNotApplicable`（第四态，CC-05）：
        # 那是"这一档在这个工作区用不上"，不是"整张表没查成"。
        src = base
        if not src.is_file():
            raise LegNotApplicable(
                kind, f"只读基线不在盘上：{base}（主稿在不在都不改变这一档的分母口径）")
        text = src.read_text(encoding="utf-8", errors="replace")
        bibitems = text.count("\\bibitem")
        draft_items = (draft.read_text(encoding="utf-8", errors="replace").count("\\bibitem")
                       if draft.is_file() else None)
        rows = list(store.rows("statements")) + list(store.rows("relations"))
        verdict = [r for r in rows if r.get("quote_verified") is not None]
        reasoned = [r for r in rows
                    if r.get("quote_verified") is None and str(r.get("quote_reason") or "").strip()]
        return len(verdict) + len(reasoned), {
            "records": len(verdict) + len(reasoned), "with_verdict": len(verdict),
            "unchecked_with_reason": len(reasoned), "bibitems": bibitems,
            # 这一档的阈值由只读基线自己定：每条 `\bibitem` 一条记录
            # （E-05 ②：分母不再取主稿）。
            "implicit_min": bibitems,
            "counted_from": "source/main.tex",
            # 对照读数（只为看得见差异，不参与判据）
            "denominator_from": "source/main.tex",
            "draft_bibitems": draft_items,
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
        #
        # `draft/39` §6.49 的 D64（用户 2026-10-06 裁）：口径再收紧成只数自写的。
        # 真机读数（T1–T5 五趟的账本逐行分类）：92 / 96 / 118 / 62 / 94 行里
        # 100% 是框架派生的模板（`note` 写着「框架据动作结果派生」/「框架据派活派生」），
        # 而且每一行的 `refs` 都是空的，正文是"从/到/一句话/时间/引用"的填空。
        # 用户的原话：「handoffs 里面没有几条有效信息全在强调纪律」。
        # 一个被模板灌满的读数会替噪声背书 ⇒ 这一档只数"模型自己写的"那些，
        # 框架派生的另列一栏（不假装没有，也不让它冒充交接）。
        from . import manuscripts as MS

        all_rows, bad_lines = MS.read_rows(project_root)
        good = [r for r in all_rows if not MS.missing_fields(r)]
        derived = [r for r in good if "框架据" in str(r.get("note") or "")]
        authored = [r for r in good if r not in derived]
        folder = project_root / MS.MANUSCRIPTS_DIR
        legacy = [str(got.get("id") or "")
                  for got in [MS.parse_name(p) or {} for p in
                              (sorted(folder.glob("*.md")) if folder.is_dir() else [])] if got]
        detail: dict[str, Any] = {
            "ledger": f"{MS.MANUSCRIPTS_DIR}/{MS.HANDOFFS_NAME}",
            "rows": len(all_rows),
            "authored_rows": [str(r.get("id") or "") for r in authored[:10]],
            "derived_rows": len(derived),
            "derived_note": ("这些行是框架替动作结果/派活自动填的模板（同样的信息在 `tasks` 与 "
                             "`out/tasks/*.json` 里，那才是它们的落点）—— 它们不算交接，"
                             "也不会让这一档变绿"),
            "refs_ok": [str(r.get("id") or "") for r in authored
                        if list(r.get("refs") or [])][:10],
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
        return len(authored), detail
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
        #
        # `draft/39` §6.49 的 D65：按内容去重（`content_sha256`）。真机读数
        # （T2 第 15 趟 `p6q`）：`documents` 4 行，而 0000/0001/0002/0003 的 claims 逐字相同
        # —— 那是同一份内容重复登记，不是四份稿子；按行数会让"反复重建同一份"看起来像产出。
        docs = [dict(r) for r in store.rows("documents")]
        seen: dict[str, str] = {}
        unique: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        for d in docs:
            key = str(d.get("content_sha256") or "") or f"id:{d.get('doc_id')}"
            if key in seen:
                duplicates.append({"doc_id": str(d.get("doc_id") or ""),
                                   "same_as": seen[key]})
                continue
            seen[key] = str(d.get("doc_id") or "")
            unique.append(d)
        with_claims = [d for d in unique if list(d.get("claims") or [])]
        return len(unique), {
            "documents": len(docs), "unique_documents": len(unique),
            "duplicate_rows": duplicates[:8],
            "with_claims": len(with_claims),
            "kinds": sorted({str(d.get("kind") or "") for d in unique}),
            "statuses": sorted({str(d.get("status") or "") for d in unique}),
            "ids": [str(d.get("doc_id") or "") for d in unique[:8]],
            "note": ("这一档就是「交付物本身在不在」：任务说交付手稿 / 清单 / 综述时，"
                     "盘上得有 `documents` 行。按 `content_sha256` 去重：同一份内容重建多次"
                     "只算一份（重复行列在 `duplicate_rows`）。0 行时这一档不成立，"
                     "而 `substance` 那一格可能已经是绿的（它只看五张表里有没有非空的）"),
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
        #
        # 三态（`draft/57` 组 9 的 R3 读侧；主控 2026-10-07 派单）：这一段的读数必须分得开
        # ① 这条命题「根本没有位记录」（产出方没走过 / 老数据）· ② 有记录、但等级只到
        # `conjecture`（算出来了、就是低档）· ③ 有记录、且到 `pre_theorem`/`theorem`
        # （这一档要数的）。①与②在旧读数里同形（都表现为"没被计入"），
        # 而"没算过"与"算了、不够档"是两件事（三态纪律：没查成 ≠ 没通过）。
        from . import evidencebits as EB

        rows = list(store.rows("statements"))
        counted: list[dict[str, Any]] = []
        grades: dict[str, int] = {}
        grades_with_bits: dict[str, int] = {}
        cited_skipped = 0
        cited_skipped_rows: list[dict[str, str]] = []
        without_bits_ids: list[str] = []
        for r in rows:
            sid = str(r.get("stmt_id") or r.get("id") or "")
            has_bits = isinstance(r.get("bits"), dict) and bool(r.get("bits"))
            if not has_bits:
                without_bits_ids.append(sid)
            # 等级只许现算：唯一入口是 `bits_from_row`（内部物化 `grade` 走 `derive_grade`）。
            # 盘上那份 `bits["grade"]` 只当缓存 —— 本读侧一个字都不读它
            # （判据见 `tests/test_closing_gate.py::test_the_grade_reading_comes_from_bits_from_row`）。
            bits = EB.bits_from_row(r)
            grade = str(bits.get("grade") or "")
            grades[grade] = grades.get(grade, 0) + 1
            if has_bits:
                grades_with_bits[grade] = grades_with_bits.get(grade, 0) + 1
            if grade in ("pre_theorem", "theorem"):
                if str(bits.get("origin") or "") == "external_lit":
                    cited_skipped += 1
                    cited_skipped_rows.append({
                        "stmt_id": sid, "grade": grade,
                        "label": str(r.get("label") or "")[:60],
                    })
                    continue
                counted.append({"stmt_id": sid, "grade": grade,
                                "label": str(r.get("label") or "")[:60]})
        detail: dict[str, Any] = {
            "statements": len(rows),
            # ---- 三态的逐档读数（分母必须并列，否则"0 条高档"读不出是哪一种 0）
            "statements_with_bits": len(rows) - len(without_bits_ids),
            "statements_without_bits": len(without_bits_ids),
            "without_bits_ids": without_bits_ids[:8],
            "counted": counted[:8],
            #: 全行的等级分布（兼容读数：没有位记录的行按"五位全空"算，进 `conjecture`）。
            "grades": grades,
            #: 只数「真的有位记录」的行 —— 这一格才是"算了之后落在哪一档"。
            "grades_with_bits": grades_with_bits,
            "cited_skipped": cited_skipped,
            "cited_skipped_rows": cited_skipped_rows[:8],
            "cited_skipped_reason": (
                "被跳过的是「引用外部文献得来的高档」（`origin=external_lit`：第 2+3 位的凭据"
                "是文献代号，不是我们自己的证明过程与审校）。这一档数的是「我方造出的判决性"
                "证据」，把别人的定理算进来就等于拿引用满足了「我们自己造」；"
                "引用命题的承重与证据链归 `load_bearing` 那一格管，不归这里"),
            "note": (
                "三态分开读：①没有位记录的行 = 产出方没走过（老数据）⇒ 它们的等级是按"
                "「五位全空」现算的（唯一的例外是 `origin=external_lit` 且逐字核过的引用命题，"
                "那种行即使没有位记录也能派生到预备定理级）—— 见 `statements_without_bits`；"
                "②有记录但只到 `conjecture` = 算出来了、就是低档（见 `grades_with_bits`）；"
                "③有记录且我方到 `pre_theorem`/`theorem` = 这一档要数的（见 `counted`）。"
                "「没算过」不等于「算了、不够档」，所以这两件事的分母必须分开给"),
        }
        if rows and not counted:
            detail["note"] += ("；本趟一条都没走到「预备定理级」—— 要么没有证明过程，"
                               "要么没审过（五位里第 2/3 位为空）；自报的 `status=proved` / "
                               "`evidence_kind=proof` 不算凭据（先看 `statements_without_bits` "
                               "是不是等于 `statements`：若是，说明产出方这一趟没写过位记录）")
        return len(counted), detail
    if kind == "numeric_experiment_rows":
        # `draft/39` §6.49 八 的 D66（用户 2026-10-06 裁「产出太保守」）：这一档从
        # 「跑过多少次数值实验」改成「跑出过几个结论」—— 旧口径只数
        # `method="numeric"`，于是全 `inconclusive` 也能让「算」那一环变绿
        # （真机 T2 `p6q`：10 条实验全 `inconclusive`，读数 10 ⇒ 绿）。
        # 判据见 `experiment_concludes`：结论 + 界/证书（形式化那一支看检查器输出）。
        numeric = [r for r in store.rows("experiments") if str(r.get("method") or "") == "numeric"]
        rows = [r for r in numeric if experiment_concludes(r)]
        return len(rows), {
            "experiments": [str(r.get("experiment_id") or "") for r in rows[:8]],
            "numeric_rows": len(numeric),
            "conclusive": len(rows),
            "inconclusive_ids": [str(r.get("experiment_id") or "") for r in numeric
                                 if not experiment_concludes(r)][:8],
            "note": ("这一档数的是**给了结论的**数值/计算实验（`result` 是 supports/refutes "
                     "且带 `search_bound` 或 `certificate`；形式化那一支看 `verifier_output`）"
                     "——「跑过」不算产出（D66）"),
        }
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
    """把「验收表结构级没查成」同时写成 finding 与读数（`draft/39` §6.25 的 D35）。

    只留给"没有行可读"的那两态（`draft/52` CC-02 裁定 (a)）：
    顶层不是 JSON、或顶层不是数组。行级的坏（一行读不懂）不走这里 ——
    那一行记 `unreadable`、其余行照常判（见 :func:`acceptance_row_state`）。

    为什么读数不能缺：这一格原先只 push 一条 `Finding`，`readings["acceptance"]` 留在
    `None` 上 —— 于是"为什么没查成"在交付面（报告 / 我的离线复算 / 状态报告）里只剩一个
    `null`，而三态纪律要的是"没查成"本身可读。
    """
    rep.status["acceptance"] = "unknown"
    rep.readings["acceptance"] = {"status": "unknown", "code": code, "detail": detail,
                                  "checks_file": checks_file,
                                  "reading_version": ACCEPTANCE_READING_VERSION,
                                  "rows": []}
    rep.findings.append(Finding("acceptance", code, "warning", detail))


#: 一行验收读数在读表这一层的状态（`draft/52` CC-02 裁定 (a)）。
#:
#: 只有这一处定义：行循环产出 `state`，四条自动分支的守卫（E-04a）与覆盖率
#: 各档的集合都消费它 —— "改一次，两处同时正确"（分别写两份 = 各修一半）。
#:
#: - `computed` —— 真的按台账算出了 `got`（唯一算"这一档被算过"的状态）；
#: - `na` —— 写表的人标了 `na` + 理由（D49 的第三态出口，只豁免这一行）；
#: - `not_applicable` —— 这一档在这个工作区算不出来（缺只读基线，CC-05 第四态）；
#: - `unreadable` —— 这一行读不懂（不是对象 / 词表外 `kind` / `na` 无理由 /
#:   `na` 非布尔 / `min`·`max` 非整数 / 台账读不到 / `id` 缺失或重复）。
#:
#: 三态纪律：`unreadable` 既不是通过、也不进 `unmet`，整格由调用方落 `unknown`
#: （绝不 `pass`）—— "没查成"不许读成"没问题"，同时不再因为一行坏就把好行的读数一起丢掉。
ROW_STATES: tuple[str, ...] = ("computed", "na", "not_applicable", "unreadable")


def acceptance_row_state(row: Mapping[str, Any]) -> str:
    """一行的状态 —— 全仓唯一的定义（见 :data:`ROW_STATES`）。

    兼容老读数行（没有 `state` 键时按旧语义推）：`na` 优先，其次 `not_applicable`，
    其余算 `computed`。这样 204 行历史读数与测试里手写的行对象仍读得对。
    """
    explicit = str(row.get("state") or "")
    if explicit in ROW_STATES:
        return explicit
    if row.get("na") is True:
        return "na"
    if row.get("not_applicable") is True:
        return "not_applicable"
    return "computed"


def acceptance_kinds_with_state(rows: Iterable[Mapping[str, Any]],
                                state: str) -> set[str]:
    """某一状态的行涉及的 `kind` 集合（守卫与覆盖率共用这一处）。"""
    return {str(r.get("kind") or "") for r in rows if acceptance_row_state(r) == state}


def _acceptance_row_problem(cid: str, raw: Mapping[str, Any],
                            seen_ids: set[str]) -> str:
    """这一行读不读得懂 ⇒ 不读得懂时返回理由（空串 = 读得懂）。

    只判"形状与字段类型"，不判阈值、不碰台账 —— 那些在循环里由 `_leg_reading` 判。
    """
    rid = str(raw.get("id") or "")
    if not rid.strip():
        return (f"验收行缺 `id`（没有 id 的读数没法与表上那一行对上）")
    if rid in seen_ids:
        return f"验收行 id={rid!r} **重复**（同一份表里两行同名 ⇒ 读数无法归属）"
    if "na" in raw and raw.get("na") is not True and raw.get("na") is not False:
        return (f"验收行 {rid} 的 `na`={raw.get('na')!r} 不是布尔 —— `na` 只认 `true`/`false`。"
                "旧的宽松口径会把它当普通行判（`na` 的语义被静默丢掉："
                "既不生效、也不报错），那是假绿方向")
    for key in ("min", "max"):
        if key in raw and raw.get(key) is not None and not isinstance(raw.get(key), int):
            return (f"验收行 {rid} 的 `{key}`={raw.get(key)!r} 不是整数 "
                    f"（收到 {type(raw.get(key)).__name__}）—— 阈值只认整数或 null")
        if isinstance(raw.get(key), bool):
            return f"验收行 {rid} 的 `{key}` 是布尔（`true`/`false` 不是阈值）"
    return ""


def _check_acceptance(rep: ClosingReport, store: Any, project_dir: str) -> None:
    """验收表的机器可判行（`draft/37` §94）：逐行现算，任一不满足 ⇒ `fail`。

    三态（`draft/52` CC-02 裁定 (a) 之后按结构级 / 行级分界）：

    - 文件不在 ⇒ `pass` 并写明"这个项目没有机器可判的验收行"（"没有这一栏"）；
    - 结构级读不懂（顶层不是 JSON / 不是数组）⇒ 整格 `unknown`（没有行可读）；
    - 行级读不懂（一行不是对象/词表外 `kind`/`na` 无理由/`na` 非布尔/
      `min`·`max` 非整数/台账读不到/id 缺失或重复）⇒ 该行 `unreadable`，
      其余行照常判；整格 = 有好行不达标 ⇒ `fail`，否则有任何 `unreadable` ⇒ `unknown`
      （绝不 `pass`）；
    - 逐行都满足 ⇒ `pass`。
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
                                      "reading_version": ACCEPTANCE_READING_VERSION,
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
    #: 落在 `not_applicable`（第四态，CC-05）上的行：缺只读基线那一类。
    #: 它们不算 `na`（`na` 是"这一档对这个项目天然不适用"，由写表的人判断），
    #: 也不算通过、不算失败 —— 是"这个工作区里这一档算不出来"。
    na_kind_rows: list[str] = []
    #: 落在 `unreadable`（CC-02 裁定 (a)）上的行：这一行读不懂。
    #: 它们不进 `unmet`、不参与阈值判定、也不算 `computed`（见 `acceptance_row_state`）——
    #: 整格由它们落 `unknown`（绝不 `pass`），而其余行的读数照常留下。
    unreadable_rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []

    def _mark_unreadable(idx: int, raw: Any, code: str, why: str) -> None:
        """把第 `idx` 行记成 `unreadable`（并留一条 warning）。"""
        rid = str(raw.get("id") or "") if isinstance(raw, Mapping) else ""
        kind = str(raw.get("kind") or "") if isinstance(raw, Mapping) else ""
        unreadable_rows.append({"id": rid or f"#{idx}", "kind": kind, "code": code,
                                "reason": why})
        if rid and rid in seen_ids and rid not in duplicate_ids:
            duplicate_ids.append(rid)
        rep.findings.append(Finding("acceptance", code, "warning", why))
        out.append({"id": rid, "name": str(raw.get("name") or "")
                    if isinstance(raw, Mapping) else "",
                    "kind": kind, "min": None, "max": None, "got": None, "ok": None,
                    "state": "unreadable", "unreadable": True, "reason": why, "code": code})

    for idx, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _mark_unreadable(idx, row, "acceptance_row_unreadable",
                             f"验收行 #{idx} 必须是对象，收到了 {type(row).__name__} "
                             f"⇒ 这一行读不懂（其余行照常判）")
            continue
        cid = str(row.get("id") or "")
        kind = str(row.get("kind") or "")
        name = str(row.get("name") or "")
        note = str(row.get("note") or "")
        # ---- 行级形状/字段类型（`draft/52` CC-02）：读不懂 ⇒ 这一行 `unreadable`。
        # 为什么先判它：`min`/`max` 非整数此前会抛异常穿出 `check_closing`（门崩），
        # `na` 非布尔此前被静默当普通行判（假绿）—— 两者都在这一处收口。
        problem = _acceptance_row_problem(cid, row, seen_ids)
        if problem:
            _mark_unreadable(idx, row, "acceptance_row_unreadable", problem)
            if cid:
                seen_ids.add(cid)
            continue
        seen_ids.add(cid)
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
                # CC-02：只有这一行是坏的（缺理由）⇒ 记 `unreadable`，
                # 不再把整张表折成"没查成"（好行的读数照留）。
                _mark_unreadable(idx, row, "acceptance_na_without_reason",
                                 f"验收行 {cid} 标了 `na`，却没有写理由（`note` 为空）"
                                 f"⇒ 这一行读不懂。`na` 不是「跳过」的快捷键："
                                 f"要写清这一档为什么对这个项目不适用"
                                 f"（例如「这是调查型任务，没有数值/构造那一步」）")
                continue
            na_rows.append(cid)
            out.append({"id": cid, "name": name, "kind": kind, "min": want_min, "max": None,
                        "got": None, "ok": True, "na": True, "state": "na", "note": note})
            continue
        if kind not in LEG_CHECK_KINDS:
            # CC-02：词表外 `kind` 只废这一行；整格仍由下面的汇总落 `unknown`
            # （绝不 `pass`）—— 自造名字的威慑一点没减，只是不再连坐好行的读数。
            _mark_unreadable(idx, row, "acceptance_unknown_kind",
                             f"验收行 {cid} 的 kind={kind!r} 不在受控词表 "
                             f"{tuple(LEG_CHECK_KINDS)} 里 ⇒ 这一行读不懂（不是「满足了」）。"
                             f"别自造名字：写表时从受控词表里逐字挑"
                             f"（那一串逐字写在主控的 brief 里）")
            continue
        try:
            got, detail = _leg_reading(store, kind, Path(resolve_under_workspace(store, project_dir)))
        except LegNotApplicable as na_exc:
            # ---- CC-05（`draft/44` J-21：与 E-05 同批）：缺基线 = 这一行不适用。
            #
            # 与"读不到台账 = 没查成"分界（`draft/46-04` §2.8 ③ 逐字）：
            # 缺只读基线是"这一档在这个工作区用不上"（换一档写得出来的），
            # 不是"整张表没查成" —— 后者会让后面每一行连读数都不肯留下（真机 `p6i`：
            # `rows=0`、整格 `unknown`，而表里另外 10 行本来算得出）。
            na_kind_rows.append(cid)
            out.append({"id": cid, "name": name, "kind": kind, "min": want_min, "max": None,
                        "got": None, "ok": None, "state": "not_applicable",
                        "not_applicable": True, "reason": na_exc.reason})
            continue
        except Exception as exc:  # noqa: BLE001 —— 台账读不到 = 这一行没查成
            _mark_unreadable(idx, row, "acceptance_leg_unreadable",
                             f"验收行 {cid}（{kind}）的读数算不出来（{type(exc).__name__}: {exc}）"
                             f"⇒ 这一行没查成（不是「不满足」，也不是「满足」）。"
                             f"台账读不到、JSON 坏都属于这一档；"
                             f"而「缺只读基线 `source/`」不是这一档 —— 那是 "
                             f"`not_applicable`（CC-05）")
            continue
        # ---- E-05 ①：阈值取大（`min` 从此只能把阈值提高）。
        #
        # 旧口径是"显式优先"：表里写 `min: 1` 而这一档自己算出来是 3 时，
        # 用 1 —— 等于写表的人可以合法地把门槛压低（`draft/43-C` C-05）。
        # 现在 `effective = max(declared, kind_min)`，并把三个数并列进读数
        # （`min_overridden`），让"表里的声明值"与"真正生效的值"分得开。
        declared_min = int(row.get("min") or 0)
        kind_min = detail.get("implicit_min")
        if kind_min is None:
            # 这一档没有自算下限：只声明了上限的档（`unfinished_request_rows`）
            # 达标线是 `<= max`，下限是 0；其余档缺省 1。
            want_min = declared_min or (0 if detail.get("implicit_max") is not None else 1)
        else:
            want_min = max(declared_min, int(kind_min))
        min_overridden = {"declared": declared_min, "kind_min": kind_min, "effective": want_min}
        if want_max is None and detail.get("implicit_max") is not None:
            want_max = int(detail["implicit_max"])
        ok_row = got >= want_min and (want_max is None or got <= want_max)
        if isinstance(detail, dict):
            detail = dict(detail)
            detail["min_overridden"] = min_overridden
        out.append({"id": cid, "name": name, "kind": kind, "min": want_min, "max": want_max,
                    "got": got, "ok": ok_row, "state": "computed", "detail": detail})
        if not ok_row:
            if got < want_min:
                why = f"{got} 条，要求 ≥ {want_min} 条"
            else:
                why = (f"{got} 条，上限 {want_max} 条（这一档要的是「上限」："
                       f"越多越不达标 —— 0 才是达标）")
            unmet.append(f"{cid}（{name or LEG_CHECK_KINDS[kind]}）：{why} —— 读数 {detail}"
                         + (f"；{note}" if note else "")
                         # 同一环里现在就能达标的其它成员档（T4 第 6 趟 `t4f` 的真机读数）：
                         # M 把"想"那一环声明成 `conjecture_rows`（0 条），而同一环的
                         # `statement_rows` 有 448 条 —— 它选了唯一为 0 的那一档，而当时
                         # 门只说了"这行没达标"，没说"同一环换个成员档就达标"。
                         + _alternatives_note(store, kind,
                                              Path(resolve_under_workspace(store, project_dir))))

    # ---- 四条自动分支的守卫（E-04a）：只看「真算过的 kind」。
    #
    # 为什么（`draft/44` J-17 / `draft/46-04` §2.1）：这四条分支是门替没写进表里的档
    # 说话的那四条（改完没复核 / 骨架稿 / 引文对不上 / 账本被模板灌满）。
    # 旧守卫看的是"表里有没有这个 `kind`"—— 于是给这四档写一行 `na` 就能让分支整条闭嘴，
    # 而 `na` 的本意只是"这一行对这个项目天然不适用"（D49），不是"门不许问这件事"。
    # 现在守卫只看 `computed_kinds`（非 `na` 的行）：`na` 只豁免它自己那一行的阈值判定。
    # 真机实现证据（内存复算）：`p7b` +6 行、`p5-review-t17`/`p8g` 各 +3 行 `na` ⇒ 旧门读成 `pass`。
    # 对 33 份真表 0 处翻转：4 行合法 `na` 所在的四档
    # （`numeric_experiment_rows`/`supported_claims`/`reviewed_proof_rows`/`proof_experiment_rows`）
    # 一行都不在这四条分支认的四个档上（`46-04` §2.1 末段）。
    # 现在守卫只看 `computed_kinds`（真算过的行）：`na`/`not_applicable`/`unreadable`
    # 都不算 —— 它们都不是"这一档被算过"（`draft/52` CC-02 把这条定义收进
    # `acceptance_row_state` 一处，行循环与这四条守卫共用）。
    computed_kinds = acceptance_kinds_with_state(out, "computed")
    na_kinds_in_table = acceptance_kinds_with_state(out, "na")
    _branch_kinds = ("reviewed_current_rows", "document_body_rows",
                     "claim_evidence_fit_rows", "manuscript_rows")
    # E-04b（机器报缺口）：这四档里"只被 `na` 行顶着"的那些 —— 如实报出来，
    # "算不算覆盖"的判断归 M/秘书（`draft/52` 裁决 5），机器不判 fail/unknown。
    na_only_branch_kinds = sorted(k for k in _branch_kinds
                                  if k in na_kinds_in_table and k not in computed_kinds)

    rep.readings["acceptance"] = {
        "checks_file": str(path), "rows": out,
        # C4/C6：验收读数的口径版本（口径每改一次就要能说清"从哪一趟起变了"）。
        "reading_version": ACCEPTANCE_READING_VERSION,
        # CC-05/CC-02 的读数：真的算过的行 / 不适用 / na / 读不懂，四档分开。
        "rows_read": len([r for r in out if acceptance_row_state(r) == "computed"]),
        "rows_na": len(na_rows),
        "rows_not_applicable": len(na_kind_rows),
        "not_applicable_rows": list(na_kind_rows),
        # CC-02：行级读不懂的那些（逐条给 id/kind/code/reason）+ 重复 id 的读数。
        "rows_unreadable": len(unreadable_rows),
        "unreadable_rows": list(unreadable_rows),
        "duplicate_ids": list(duplicate_ids),
        # E-04a/E-04b 的读数：哪几个"自动分支档"只被 `na` 行顶着
        # （`na` 不再能关掉分支；这里如实报出"表里只给了 na"这件事）。
        "na_only_branch_kinds": na_only_branch_kinds,
        "note": ("`reading_version` 变了 ⇒ 与历史读数**不可直接比**（口径变了）。"
                 "`rows_read` 只数真的按台账现算过的行（`state == computed`）；"
                 "`na` / `not_applicable` / `unreadable` 三种都不是「算过」："
                 "`na` 是写表的人对**这一行**的判断，`not_applicable` 是缺只读基线，"
                 "`unreadable` 是这一行读不懂（有它 ⇒ 整格 `unknown`，**绝不 `pass`**）。"
                 "`na` 不再能关掉门的自动分支（E-04a）"),
    }
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
    # 参与覆盖面的行 = 除 `unreadable` 以外的所有行（读不懂的行连 `kind` 都不可信）。
    coverage_kinds = [str(r.get("kind") or "") for r in out
                      if acceptance_row_state(r) != "unreadable"]
    try:
        chain = research_chain_gaps(store, coverage_kinds,
                                    na_kinds=sorted(na_kinds_in_table))
    except RuntimeError as exc:
        rep.status["acceptance"] = "unknown"
        rep.findings.append(Finding(
            "acceptance", "acceptance_chain_unreadable", "warning",
            f"{exc} ⇒ 研究链覆盖面这一格没查成（不是「覆盖齐了」）"))
        return
    rep.readings["acceptance"]["research_chain"] = chain
    # E-04b：整环只有 `na` 行的那些环 —— 如实报出来（读数），
    # "这算不算覆盖"由 M/秘书判断（机器不判 fail/unknown，`draft/52` C1）。
    rep.readings["acceptance"]["research_chain"]["na_only_groups"] = chain["na_only_groups"]
    if chain["missing"]:
        unmet.append("研究链覆盖面：验收表里一行都没有的环节 —— " + "；".join(chain["missing"]))
    # ---- 稿子改完之后有没有再复核（`draft/39` §6.46 的 D57）：验收表里没写这一档时，
    # 门替它报出来 —— 否则「G.revise 追加的断言从未被审过」可以整趟静默留下
    # （T5 第 5 趟：`review_findings` 0 条、七格全绿，而现行版 `68bfc4c7…` 没有任何签名）。
    # 这一档写进验收表时由它自己那一行判（含 `na` + 理由那条出口），门不重复说话。
    if "reviewed_current_rows" not in computed_kinds:
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
                  "现行版。注意：写一行 `na` 关不掉这一条（它读的是签名链与现行版哈希，"
                  "与验收表怎么写无关）")
    # ---- 稿件是骨架还是手稿（`draft/39` §6.48 的 D63）：有 sections 却每节都空的行，
    # 验收表里没写这一档时由门报出来（真机读数 T5 第 7 趟 `p8g`：三节 body 全是空串）。
    if "document_body_rows" not in computed_kinds:
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
                  "把每一节的正文写进去（`G.build_document` 的 `sections` 要带 `body`）。"
                  "注意：给这一档写一行 `na` 关不掉它 —— 这一条是从 `documents` 表**现算**的"
                  "（E-04a 的守卫只看真算过的行）；没有 sections 的清单型交付本来就不进这一档")
    # ---- 断言与它引的证据对不对得上（`draft/39` §6.48 的 D61/D62）：验收表里没写这一档时，
    # 门把「对不上」的那些断言逐条报出来（真机读数 T5 第 7 趟 `p8g`：两条 exp 引用互换、
    # 一条 lit 引用跑题，而所有机械读数全绿）。
    if "claim_evidence_fit_rows" not in computed_kinds:
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
                + " —— 把引文改成真的支持这条断言的那一条（或改断言让它与证据相符）。"
                  "注意：写一行 `na` 关不掉它（这一条是从 `documents` 现算的）；"
                  "两侧都取不到可判特征的那一类记 `unjudged`，不会进这一条")
    # ---- 交接账本是不是被模板灌满（`draft/39` §6.49 的 D64，用户 2026-10-06 裁）：
    # 验收表里没写这一档时，门替它报出来 —— 五趟真机的账本里 100% 是框架派生的模板、
    # `refs` 全空，而"手稿 N 行"这个读数一直在替噪声背书。
    if "manuscript_rows" not in computed_kinds:
        try:
            _got, ms_detail = _leg_reading(
                store, "manuscript_rows",
                Path(resolve_under_workspace(store, project_dir)))
        except Exception:  # noqa: BLE001 —— 读不出来时这一档不算数
            ms_detail = None
        if ms_detail and int(ms_detail.get("derived_rows") or 0) > 0 and _got == 0:
            unmet.append(
                f"交接账本里 {ms_detail['derived_rows']} 行**全是框架派生的模板**"
                f"（`refs` 全空、正文是填空），**没有一份模型自己写的交接** —— "
                "带信息的交接应当是：写清交给谁什么结论、依据哪几个编号（`refs` 非空）"
                "（派活时带 `notify`，收工时的 `final.notify`）。"
                "注意：写一行 `na` 关不掉它（这一条是从 `manuscripts/handoffs.jsonl` 现算的）；"
                "动作驱动的一趟也能自撰交接 —— 用一次 `handoff` 把结论与编号写给下一位")
    # ---- 五条「内容」判据（`draft/39` §6.49 八；用户 2026-10-06 裁「产出太保守」）：
    # D66（算要结论 / 造要我方派生命题）· D67（C 的产物要进交付）· T1 口径（一条都没核到
    # 不算交付）· T3 口径（论文要承载本轮结果）。与上面四条同族：门替没写进表里的档说话，
    # `na` 关不掉它们（E-04a 的守卫口径一致）；读不出来的当成「没查成」记读数，
    # 绝不折成「通过」。
    try:
        content_unmet, content_readings = content_leg_unmet(
            store, Path(resolve_under_workspace(store, project_dir)),
            researched=bool(chain.get("researched")), computed_kinds=computed_kinds)
    except Exception as exc:  # noqa: BLE001 —— 这一批判据自己出问题时不冒充通过
        content_unmet = []
        content_readings = {"unreadable": f"{type(exc).__name__}: {exc}"}
    rep.readings["acceptance"]["content_branches"] = content_readings
    unmet.extend(content_unmet)
    if unmet:
        rep.status["acceptance"] = "fail"
        rep.findings.append(Finding(
            "acceptance", "acceptance_unmet", "blocker",
            "验收表里机器可判的这几行**没满足**（这一趟的交付缺了任务点名的凭据）："
            + "；".join(unmet)
            + "。台账是唯一能复算的地方 —— 把凭据落进台账（不是只写进报告）再收工"))
    elif unreadable_rows:
        # CC-02（`draft/52` 裁定 (a)）：行级读不懂 ⇒ 整格 `unknown`（绝不 `pass`），
        # 而好行的读数已经在上面留下了。逐条理由已各自 push 成 warning。
        rep.status["acceptance"] = "unknown"
        rep.findings.append(Finding(
            "acceptance", "acceptance_rows_unreadable", "warning",
            f"验收表里有 {len(unreadable_rows)} 行**读不懂**（"
            + "；".join(f"{u['id']}：{u['reason']}" for u in unreadable_rows[:4])
            + f"）⇒ 这一格记 `unknown`（不是「通过」，也不是「不满足」）。"
            "其余行的读数照常给出 —— 这与「结构级读不懂（顶层不是 JSON / 不是数组）」"
            "不同一档：那时没有任何行可读"))
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

#: 收工判据的那一句话（业主 2026-10-09 逐字）——三处（`to_dict` / 工具 / CLI）共用一份措辞，
#: 免得"谁判收工"这件事在不同出口里被说成三件不同的事。
VERDICT_NOTE = (
    "收工与否由 M 判（业主 2026-10-09：「是否收工不要用机械判据，由 M 制定的目标是否达成为准」"
    "＋「所有智能体是否能停都是看自己被派的活有没有做完，M 也不例外，只是 M 需要根据用户指令"
    "给自己设计任务列表」）：`can_close` = M 在 `m_verdict.met` 里说的那一句（它按自己列的"
    "`tasks` 判『活做完了没有』）；机器八格（`status` / `machine_pass`）是读数。"
    "两者不一致时 `overrode` 逐格点名、自述与自己的列表对不上时 `verdict_conflicts` 逐项点名"
    "—— 判据归 M，读数照旧一格不减。M 没提交判据 ⇒ `can_close=false`（『没人判过』不是"
    "『判过能交』）。"
)

#: 报告体例由 M 裁定（R9 / `draft/52` 裁决 1 = C''）—— 门不再自带任何节名清单。
#:
#: ## 为什么删掉了九节（`REPORT_SECTIONS`）与分栏标记（`SPLIT_MARKERS`）
#:
#: 那两样出自 `draft/37` §14.4，是review 线的交付规格（"审稿报告该有哪九节"
#: 是那一条线的排版约定）。它被塞进通用收工门的 `report_shape` 档之后，
#: 每一个研究型工作区都被按审稿报告的排版来判 —— 那是"只为某一条线建的标准"
#: （用户 2026-10-06 口径：直接废除，不是降为读数）。
#: 真机读数也说明它判错了对象：46 份报告里 45 份"九节齐全"，而缺附件三件套的有 9 份
#: —— 门在排版上一分不让，在"这条结论是不是我们自己做的、依据在哪、文件有没有被换过"
#: 上却一个字都没判（"算了不判 = 假读数"）。
#:
#: 现在的口径：体例归 M。门只核对两件事：
#:
#: ① 附件三件套（`ATTACHMENT_FIELDS`）—— 它是来源与完整性，不是排版，保留判实；
#: ② M 声明的体例有没有兑现 —— M 若在工作区里落下 `REPORT-STYLE.json`
#:    （`{"sections": [...]}`，见 :data:`REPORT_STYLE_NAME`），门就逐节核它在不在报告里；
#:    没声明 ⇒ 不判体例（不是"通过"，是"这一趟没有体例声明"，读数里如实写 `none`）。
REPORT_STYLE_NAME = "out/review/REPORT-STYLE.json"

#: 附件三件套（§16 P3 报告行逐字要求）。
ATTACHMENT_FIELDS: tuple[str, ...] = ("origin=own_result", "依据", "sha")

#: 验收读数的口径版本（`draft/46-04` §6.4 第 1 条：每改一次口径必须能说清
#: "从哪一趟起口径变了"）。`readings["acceptance"]["reading_version"]` 直接读它。
#:
#: 为什么必须有：33 份历史表 / 204 行今天读出的 `got` 是旧口径下的数。
#: 同一份表、同一个工作区、不同趟次读出的数不同时，没有版本号就无从判断
#: 差异来自"研究对象变了"还是"门的口径变了"。口径锚点取 `p8g`
#: （唯一覆盖面 8/8 齐的工作区）。
#:
#: 版本沿革：
#: - `"2026-10-06-C"`：E-05（`min` 与 `implicit_min` 取大 + 引文分母改用只读基线
#:   `source/main.tex` + `manuscript_edited` 去空白后比）、CC-05（缺基线 ⇒ 该行
#:   `not_applicable` 而不是整格 `unknown`）、E-04a（四条自动分支的守卫改看
#:   真算过的 kind，`na` 只豁免它自己那一行）、E-04b（整环只有 `na` 行时
#:   如实报出来，判断归 M/秘书）、R9（九节与分栏判据废除）。
#: - `"2026-10-06-C2"`（`draft/52` CC-02 裁定 (a)）：结构级 / 行级分界 ——
#:   一行读不懂只废那一行（`state="unreadable"`，整格 `unknown`、绝不 `pass`），
#:   好行的读数不再被一起丢掉；行状态判据收进 `acceptance_row_state` 一处
#:   （行循环与四条自动分支的守卫共用）；读数新增 `rows_unreadable` /
#:   `unreadable_rows` / `duplicate_ids`。
#: - `"2026-10-06-C3"`（`draft/39` §6.49 八；用户 2026-10-06 裁「产出太保守」）：
#:   五条内容判据（`content_leg_unmet`）与一处读数换口径 ——
#:   ①`numeric_experiment_rows` 从「跑过多少次数值实验」改成「跑出过几个结论」
#:   （结论 + 界/证书；形式化那一支看检查器输出）；②「算」那一环在研究型项目里
#:   全 `inconclusive` ⇒ 门自己报；③「造」那一环声明的项目要求有 `origin=own_result`
#:   且写清来路（`derived_from` / `source_lit_id`）的命题；④C 的关系分析跑过而
#:   产物没进交付面（手稿/文档里 0 条 `rel:`、`analysis_reports` 0 行）⇒ 门报；
#:   ⑤只读基线有 `\bibitem` 而台账里一条 `quote_verified=True` 都没有 ⇒ 门报（T1 口径）；
#:   ⑥有论文主稿时：`\bibitem` < 2、或本轮 `stmt:`/`exp:`/`rel:` 引用只出现在
#:   核查章节里 ⇒ 门报（T3 口径）。读数新增 `readings["acceptance"]["content_branches"]`。
ACCEPTANCE_READING_VERSION = "2026-10-06-C3"


class LegNotApplicable(Exception):
    """这一档在这个工作区里算不出来，而原因是"它本来就该用别的档"。

    与"读不到台账 ⇒ 没查成"必须分开（`draft/46-04` §2.8 ③ 逐字）：

    - 缺只读基线（`manuscript_edited` / `citation_records_vs_bibitems` 要
      `source/main.tex`）⇒ 这是这一行不适用（`not_applicable`），
      不是"整张表没查成" —— 真机 `p6i` 就是被这一条判成了整格 `unknown`，
      后面 10 行连读数都没留下；
    - 台账读不到 ⇒ 这一行 `unreadable`（CC-02 之后按行记账，整格仍 `unknown`，
      保留 `acceptance_leg_unreadable` 那一档）。
    """

    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(f"{kind}：{reason}")
        self.kind = kind
        self.reason = reason

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
    """各条检查的读数。`status` 每条一个三态值；`findings` 是拦门的原因。

    `m_verdict`（业主 2026-10-09 的裁定）：M 自己的判据 ——
    `{"goal": "我这一趟的目标", "met": True/False, "basis": "依据哪几条读数", "at": …}`。
    `can_close` 由它决定；机器那八格（`status` / `machine_pass`）退成读数。
    """

    status: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    readings: dict[str, Any] = field(default_factory=dict)
    #: M 的判据（`None` = 它没提交 ⇒ `can_close=false` + "没人判过"的读数）。
    m_verdict: dict[str, Any] | None = None

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
    def machine_pass(self) -> bool:
        """机器读数：八格每条都 `pass` 且没有 blocker（老口径的机械合取）。

        业主 2026-10-09 的裁定之后它只是一个读数（收工不由它定）：
        「是否收工不要用机械判据，由 M 制定的目标是否达成为准」。
        """
        return all(v == "pass" for v in self.status.values()) and not self.blockers

    @property
    def can_close(self) -> bool:
        """M 判"我这一趟的目标达成了" —— 收工与否由 M 判，机器只给读数（业主 2026-10-09）。

        - M 提交了 `m_verdict.met=True` ⇒ `True`（哪怕机器某几格是 fail/unknown：
          那些格子照样进读数与 `overrode`，不是静默放行）；
        - M 提交了 `met=False` ⇒ `False`（哪怕机器八格全 pass —— 那是"机器觉得没问题、
          它自己知道没做到"，也必须由它说了算）；
        - M 没提交 ⇒ `False` + `m_verdict=False` 那一档的读数（"没人判过" ≠ "判过能交"）。

        旧的机械口径原样保留在 :attr:`machine_pass`，两者不一致时逐格记进 :attr:`overrode`。
        """
        return bool(self.m_verdict and self.m_verdict.get("met"))

    @property
    def overrode(self) -> list[dict[str, Any]]:
        """机器读数与 M 的判断不一致的那些格（空列表 = 两者一致）。

        两个方向都记（这就是"不许静默放行"的落点）：
        - M 说达成、而某几格是 `fail`/`unknown` ⇒ 逐格点名；
        - M 说没达成、而八格全 `pass` ⇒ 记一格 `"*"`（机器觉得没问题，它自己知道没做到）。
        """
        if not self.m_verdict:
            return []
        met = bool(self.m_verdict.get("met"))
        bad = [{"check": k, "state": v, "why": "机器读数不是 pass，而 M 判达成"}
               for k, v in sorted(self.status.items()) if v != "pass"]
        if met:
            # 拦门读数的正文也要看得见（同一格可能有既非 pass 又有 blocker 的情况 ⇒ 去重）
            seen = {x["check"] for x in bad}
            bad += [{"check": f.check, "state": f.level, "why": f.detail}
                    for f in self.blockers if f.check not in seen]
            return bad
        if not bad and self.machine_pass:
            return [{"check": "*", "state": "pass", "why": "机器八格全 pass，而 M 判没达成"}]
        return []

    @property
    def verdict_conflicts(self) -> list[dict[str, Any]]:
        """M 的自述与它自己的任务列表对不上的地方（空列表 = 自洽）。

        业主 2026-10-09 的第二句：「所有智能体是否能停都是看自己被派的活有没有做完，
        M 也不例外，只是 M 需要根据用户指令给自己设计任务列表」⇒ 停的判据是
        任务列表（M 自己列的），所以"说达成"与"列表里还有没做完的项"必须对得上；
        对不上时不阻断（判据归 M），但逐项点名，让人看得见它凭什么说停。
        """
        if not self.m_verdict:
            return []
        tasks = [t for t in (self.m_verdict.get("tasks") or []) if isinstance(t, Mapping)]
        met = bool(self.m_verdict.get("met"))
        open_items = [{"what": str(t.get("what") or ""), "state": str(t.get("state") or ""),
                       "why": str(t.get("why") or "")}
                      for t in tasks if str(t.get("state") or "") != "done"]
        if met and open_items:
            return [{**x, "conflict": "M 说目标达成，而它自己的任务列表里这一项不是 done"}
                    for x in open_items]
        if not met and tasks and not open_items:
            return [{"what": "*", "state": "done", "why": "任务列表全 done，而 M 说没达成",
                     "conflict": "自述比列表更严"}]
        return []

    @property
    def escalation_gaps(self) -> list[dict[str, Any]]:
        """任务列表里"干不了/还没做完"的项，有没有上报（业主 2026-10-09 第三句）。

        > 「如果某代理认为某件任务自己无法胜任且无法通过派子代理解决，则会将情况上报父智能体。
        > 特别地，M 向用户上报。」

        机器形态：这些项要在这一段会话里找得到一次上行 —— M 的上行是"问用户"
        （`ask_user`）或已经答过的回答；子代理的上行是"给父的报文"（板项/留言，S1k 的名字面）。
        这一格是读数（不阻断）：判据仍归 M（它说停就能停），但"闷着不说"必须看得见 ——
        找不到上报的项逐项进 `gaps`；读不成 ⇒ `checked=False`（"没读成"不是"没上报"）。
        """
        got = self.readings.get("verdict_escalation") or {}
        if not got.get("checked"):
            return []
        return list(got.get("gaps") or [])

    def to_dict(self) -> dict[str, Any]:
        """整份读数的可读视图（CLI、工具与落档共用同一个形状）。"""
        return {
            "can_close": self.can_close,
            "machine_pass": self.machine_pass,
            "m_verdict": dict(self.m_verdict) if self.m_verdict else None,
            "overrode": self.overrode,
            "verdict_conflicts": self.verdict_conflicts,
            "escalation_gaps": self.escalation_gaps,
            "verdict_note": VERDICT_NOTE,
            "status": dict(self.status),
            "failed": self.failed,
            "unknowns": self.unknowns,
            "findings": [f.to_dict() for f in self.findings],
            "readings": dict(self.readings),
        }

    def summary(self) -> str:
        """一句话读数（给 CLI 与交付说明用；不许盖过明细）。"""
        machine = (f"机器八格：pass {sum(1 for v in self.status.values() if v == 'pass')}/"
                   f"{len(self.status)}"
                   + (f"；fail={self.failed}" if self.failed else "")
                   + (f"；unknown={self.unknowns}" if self.unknowns else ""))
        if not self.m_verdict:
            return (f"收工门：{machine} —— M 没有提交自己的判据（它按自己列的任务列表判"
                    "『活做完了没有』）⇒ `can_close=false`")
        tasks = [t for t in (self.m_verdict.get("tasks") or []) if isinstance(t, Mapping)]
        done = sum(1 for t in tasks if str(t.get("state") or "") == "done")
        list_note = f"；任务列表 {done}/{len(tasks)} done" if tasks else "；任务列表：没提交"
        met = "做完了" if self.m_verdict.get("met") else "没做完"
        tail = (f"；与列表/机器对不上的：{[x.get('what') for x in self.verdict_conflicts]}"
                if self.verdict_conflicts else "")
        gaps = self.escalation_gaps
        gap_note = (f"；没上报的项：{[x.get('what') for x in gaps]}" if gaps else "")
        return (f"收工门：M 判「我这一趟的活{met}」⇒ can_close={self.can_close}"
                f"（{machine}{list_note}{tail}{gap_note}）")


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


#: 污染面的残余边界（改前那句已作废，逐字理由见下）。
#:
#: 改前（`R5-组 4` 的 B 方案）这里写的是"断言级污染面判不了：
#: `documents.claims[].citations` 只认 `lit:`/`exp:`/`rel:`，没有引用命题的形式"。
#: 2026-10-07 所有者裁定 `draft/68` 题 1 选 A（本次改动由所有者授权、主控代改）：
#: `citations` 现在认 `stmt:<命题号>` ⇒ "哪几条正文断言压在这条命题上"判得了。
#: 于是这句话从"判不了"改成"判得了，但只覆盖显式写了 `stmt:` 的那些引用" ——
#: 边界没有消失，只是缩小了：没带 `stmt:` 前缀的引用（裸号、或别的表的前缀）
#: 指不到任何一条命题，它对命题层不可见。这句话仍然逐字进读数。
#:
#: 判据在 `tests/test_contradiction_fixtures.py` 的
#: `test_the_assertion_level_boundary_is_verbatim_in_the_readings`
#: （判据侧不 import 本常量，否则把常量改成空串就能让判据跟着一起变绿）。
POLLUTION_SCOPE_BOUNDARY = (
    "断言级污染面只覆盖显式写了 `stmt:<命题号>` 的引用："
    "`documents.claims[].citations` 里没带 `stmt:` 前缀的引用指不到任何命题，"
    "它对命题层不可见")

#: 命题层闭包分布的规模上限：超过就只给"有/没有下游"，闭包分布如实记成没算
#: （宁可说"这一格没算"，也不许让读数在两万条命题上跑成分钟级、更不许拿 0 冒充）。
POLLUTION_CLOSURE_MAX_NODES = 2000


def pollution_scope_text() -> str:
    """`pollution_scope` 那一格的整段文字：残余边界 + 今天判到哪两层。"""
    return (POLLUTION_SCOPE_BOUNDARY
            + "；今天判两层：命题层（`statements.derived_from` 上的传递闭包）"
              "+ 正文断言层（`documents.claims[].citations` 里的 `stmt:<命题号>`，"
              "读数见 `pollution_assertion_level`）；"
              "`stmt:` 是 `schema.CITATION_PREFIXES` 登记的前缀，"
              "前缀由 `claimanatomy` 判、目标存在性由写入期 `doc_tools.check_citations` "
              "与审计期 `verify` 判（三态：没查到 / 不存在 / 合法）")


def _pollution_closure(rows: Mapping[str, Any], stmt_id: str) -> list[str]:
    """`statements.derived_from` 上的传递闭包（不含自身）—— 纯函数，不读盘。"""
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


def _statement_rows(store: Any) -> tuple[dict[str, Any] | None, str]:
    """读命题台账：返回 (rows, 失败原因)；读不到时 rows 是 `None`（不是空字典）。

    这一对返回值的形状就是三态的载体：`None` = 没查成，`{}` = 查成了、账本是空的。
    折平它（例如失败时也回 `{}`）正是"没查成与没有同形"那个老毛病。
    """
    if store is None:
        return None, "没有 store ⇒ 没查成（不是「没有下游」，也不是「没有问题」）"
    try:
        return {str(s.get("stmt_id")): s for s in store.rows("statements")}, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"`statements` 读不到（{type(exc).__name__}）⇒ 没查成"


def _document_rows(store: Any) -> tuple[list[Any] | None, str]:
    """读 `documents`：返回 (rows, 失败原因)；`None` = 没查成（同 `_statement_rows` 的三态）。

    与 `_statement_rows` 分开的理由：这两张表各自可能单独读不到（权限、半截文件），
    而"命题账本读不到"与"稿件读不到"是两条不同的处置路径。
    """
    if store is None:
        return None, "没有 store ⇒ 没查成（不是「没有正文断言压着」）"
    try:
        return list(store.rows("documents")), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"`documents` 读不到（{type(exc).__name__}）⇒ 没查成"


def _statement_citations(rows: Iterable[Any]) -> list[dict[str, str]]:
    """扫稿件取出全部 `stmt:<命题号>` 引用（纯函数，不读盘）。

    解析走 `textutil.citation_ref_parts`（`P-5` 的唯一实现）：`stmt:0003#p.4`
    这类带锚点的写法按同一个命题算一次 —— 与 `verify` 的 `dangling_citation`
    同口径，否则"写入期算成一条、审计期算成两条"。
    """
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        doc_id = str(row.get("doc_id") or row.get("id") or "")
        for c in row.get("claims") or []:
            if not isinstance(c, Mapping):
                continue
            claim_id = str(c.get("claim_id") or "")
            for raw in c.get("citations") or []:
                kind, ref = T.citation_ref_parts(raw)
                if kind == "stmt":
                    out.append({"doc_id": doc_id, "claim_id": claim_id,
                                "citation": str(raw), "stmt_id": ref})
    return out


def statements_cited_by_claims(store: Any) -> dict[str, Any]:
    """正文断言引了哪些命题（按命题号归拢）+ 其中悬空的那几条。

    口径只有一句：`documents.claims[].citations` 里带 `stmt:` 前缀的引用，
    就是"这条正文断言压在那条命题上"这条边（`draft/68` 题 1，2026-10-07 所有者裁定 A；
    本次改动由所有者授权、主控代改）。

    三态（这是本函数的核心，不是细节）：

    ====================  ==================================================================
    state                 含义
    ====================  ==================================================================
    `computed`            查过了：`by_statement` / `dangling` 都是算出来的读数
    `unreadable`          `documents` 或 `statements` 读不到 ⇒ 没查成（不是"没有断言压着"）
    ====================  ==================================================================

    `dangling` 单独一栏是"目标不存在"那一态的载体：`stmt:9999` 这种引用的目标不在
    命题账本里，它既不许被静默算成"压在 9999 上"，也不许被静默丢掉 ——
    它是悬空引用，写入期（`doc_tools.check_citations`）与审计期（`verify`）各自报 error。
    """
    rows, why = _document_rows(store)
    if rows is None:
        return {"state": "unreadable", "reason": why, "documents": None,
                "claims_total": None, "citations": None, "claims": None,
                "by_statement": None, "dangling": None}
    claims_total = sum(len(r.get("claims") or []) for r in rows if isinstance(r, Mapping))
    cites = _statement_citations(rows)
    claims = {(x["doc_id"], x["claim_id"]) for x in cites}
    srows, swhy = _statement_rows(store)
    if srows is None:
        return {"state": "unreadable", "reason": swhy, "documents": len(rows),
                "claims_total": claims_total, "citations": len(cites),
                "claims": len(claims), "by_statement": None, "dangling": None}
    by: dict[str, list[dict[str, str]]] = {}
    dangling: list[dict[str, str]] = []
    for x in cites:
        if x["stmt_id"] in srows:
            by.setdefault(x["stmt_id"], []).append(x)
        else:
            dangling.append(x)
    return {
        "state": "computed",
        "reason": (f"查过了：{len(cites)} 条 `stmt:` 引用（{len(claims)} 条正文断言）"
                   + (f"，其中 {len(dangling)} 条指向不存在的命题（悬空引用）" if dangling
                      else "，全部指向存在的命题")),
        "documents": len(rows), "claims_total": claims_total,
        "citations": len(cites), "claims": len(claims),
        "by_statement": by, "dangling": dangling,
    }


def assertions_pressing_on(store: Any, stmt_id: str) -> dict[str, Any]:
    """哪几条正文断言压在这条命题上（`stmt:<命题号>` 引用）。三态。

    为什么单独一个函数而不是把这一格塞进 `pollution_set` 的返回值：`pollution_set`
    回的是命题号列表，而这里是"稿件行 + 断言号"的二元组 —— 两种东西混进同一个列表，
    读的人再也分不清"跟着倒的命题"与"压在上面的正文断言"（而它们的处置不同：
    前者要撤结论，后者要改稿）。所以两者分开给，但同处一个三态读数里。

    ====================  ==========================================================
    state                 含义
    ====================  ==========================================================
    `computed`            查过了（`assertions` 可能为空 = 确实没有断言引它）
    `no_such_statement`   命题账本里没有这条命题 ⇒ 判不了（不是"没有断言引它"）
    `unreadable`          这一趟没查成（`documents` 或 `statements` 读不到）
    ====================  ==========================================================
    """
    cites = statements_cited_by_claims(store)
    if cites["state"] != "computed":
        return {"state": "unreadable", "assertions": None, "dangling": None,
                "reason": cites["reason"]}
    srows, _ = _statement_rows(store)
    if srows is None or str(stmt_id) not in srows:
        return {"state": "no_such_statement", "assertions": None, "dangling": None,
                "reason": (f"`statements` 里没有 {stmt_id} ⇒ "
                           "判不了有没有正文断言压着它（不是「没有」）")}
    hits = list(cites["by_statement"].get(str(stmt_id), []))
    return {
        "state": "computed", "assertions": hits, "dangling": list(cites["dangling"]),
        "reason": ("查过了：这条命题确实没有被任何正文断言引用" if not hits
                   else f"查过了：{len(hits)} 条正文断言压在它上面"),
    }


def pollution_reading(store: Any, stmt_id: str) -> dict[str, Any]:
    """一条命题的污染面 —— 带 `state` 的三态版本，两层（命题层 + 正文断言层）。

    为什么必须有它：`pollution_set` 只回一个列表，于是"这条命题确实没有任何下游"
    与"这一趟没查成"都表现成 `[]`。三态纪律里"没查成 ≠ 没有"，而且两者的处置
    完全不同：前者什么都不用做，后者要有人去修台账 / 补 store。

    两层各自的读数：
      - `downstream`：`statements.derived_from` 上的传递闭包（命题层）；
      - `assertions`：`documents.claims[].citations` 里写了 `stmt:<这条命题>` 的
        那些正文断言（`draft/68` 题 1 选 A 之后才判得了）。`None` = 这一层没查成。
    """
    rows, why = _statement_rows(store)
    pressed = statements_cited_by_claims(store)
    if pressed["state"] == "computed":
        hits: list[dict[str, str]] | None = list(
            pressed["by_statement"].get(str(stmt_id), []))
        a_reason = ("查过了：确实没有正文断言引这条命题" if not hits
                    else f"查过了：{len(hits)} 条正文断言引它")
        a_state = "computed"
    else:
        hits, a_reason, a_state = None, pressed["reason"], "unreadable"
    if rows is None:
        return {"state": "unreadable", "downstream": [], "reason": why,
                "assertions": None, "assertion_state": a_state,
                "assertions_reason": a_reason}
    if stmt_id not in rows:
        return {"state": "no_such_statement", "downstream": [],
                "reason": f"`statements` 里没有 {stmt_id} ⇒ 判不了它有没有下游"
                          "（不是「没有下游」）",
                "assertions": None, "assertion_state": a_state,
                "assertions_reason": a_reason}
    downstream = _pollution_closure(rows, stmt_id)
    reason = ("查过了：这条命题确实没有任何下游" if not downstream
              else f"查过了：下游闭包 {len(downstream)} 条")
    return {"state": "computed", "downstream": downstream, "reason": reason,
            "assertions": hits, "assertion_state": a_state,
            "assertions_reason": a_reason}


def pollution_set(store: Any, stmt_id: str) -> list[str]:
    """一条命题被推翻时跟着倒的那些命题（`draft/37` §9 / R20 的"污染面"）。

    做法是 `statements.derived_from` 上的传递闭包（谁用到我、谁又用到它……），
    不含自身。为什么必须有它：§9 的处置不是"把这一条划掉"就完事 ——
    `draft/37` 的用词是"如果错的是文献，那么压在它上面的结论就不能再算数"，
    而"压在它上面"在数据面上就是这张有向图。

    第二层（正文断言层）：`documents.claims[].citations` 里的 `stmt:<命题号>`
    引用也是"压在它上面"，但那一条边连着的是稿件里的断言，不是命题 ——
    所以它不进本函数的返回值（把两种东西混进一个列表就再也分不清了），
    而是走 :func:`assertions_pressing_on` 与 `pollution_reading` 的 `assertions` 格。
    2026-10-07 所有者裁定 `draft/68` 题 1 选 A 之前，这一层没有数据形式可判
    （`citations` 只认 `lit:`/`exp:`/`rel:`），现在有 `stmt:` 前缀了，
    于是"哪几条正文断言压在这条命题上"从一个边界文字变成一条真读数。

    三态：本函数只回闭包本身，`[]` 既可能是"没有下游"也可能是"没查成"——
    要分清就读 :func:`pollution_reading`（它多回一个 `state`）。
    """
    return list(pollution_reading(store, stmt_id)["downstream"])


def proposition_level_pollution(store: Any) -> dict[str, Any]:
    """命题层污染面的现算读数：多少命题有下游 + 闭包大小分布。

    为什么要单独这一格：`pollution` 只装着"被证否的那些命题"的闭包 ——
    从一个（可能为空的）`pollution` 字典里读不出"这一趟到底有没有命题压在别人身上"。
    """
    rows, why = _statement_rows(store)
    if rows is None:
        return {"state": "unreadable", "reason": why, "statements": 0,
                "with_downstream": 0, "without_downstream": 0,
                "closure_sizes": None, "max_closure": None}
    referenced = {str(x) for row in rows.values()
                  for x in (row.get("derived_from") or [])}
    with_downstream = sum(1 for sid in rows if sid in referenced)
    out: dict[str, Any] = {
        "state": "computed",
        "reason": "查过了：命题层的闭包分布是现算的",
        "statements": len(rows),
        "with_downstream": with_downstream,
        "without_downstream": len(rows) - with_downstream,
        "closure_sizes": None,
        "max_closure": None,
    }
    if len(rows) > POLLUTION_CLOSURE_MAX_NODES:
        out["state"] = "too_large"
        out["reason"] = (f"命题数 {len(rows)} 超过 {POLLUTION_CLOSURE_MAX_NODES} ⇒ "
                         "闭包分布没算（不是「没有下游」；有/没有下游那一格仍然算得出来）")
        return out
    sizes = [len(_pollution_closure(rows, sid)) for sid in rows]
    hist: dict[str, int] = {}
    for n in sizes:
        hist[str(n)] = hist.get(str(n), 0) + 1
    out["closure_sizes"] = hist
    out["max_closure"] = max(sizes) if sizes else 0
    return out


def assertion_level_pollution(store: Any) -> dict[str, Any]:
    """正文断言层的污染面：多少条正文断言引了命题 + 每条命题被几条断言压着。

    改前这一格按设计是 `not_judged`（缺的是数据形式：`citations` 没有引用命题的
    写法）。2026-10-07 所有者裁定 `draft/68` 题 1 选 A（本次改动由所有者授权、
    主控代改）之后它变成一条现算读数 —— 判据跟着改的地方与理由写在
    `tests/test_contradiction_fixtures.py` 对应用例的 docstring 里。

    三态：

    ====================  ==========================================================
    state                 含义
    ====================  ==========================================================
    `computed`            查过了（下面每一格都是算出来的读数，`0` 是真 0）
    `unreadable`          `documents` 或 `statements` 读不到 ⇒ 没查成
    ====================  ==========================================================

    为什么 `claims_total` 与 `claims_citing_a_statement` 必须分开给：
    "这一批稿件里没有一条断言引命题"（0 / 40）与"这一趟一条断言都没扫到"（0 / 0）
    是两件事 —— 只给一个 0，读的人分不清"这一层干净"与"这一层根本没数据"。
    """
    cites = statements_cited_by_claims(store)
    if cites["state"] != "computed":
        return {"state": "unreadable", "readable": False,
                "documents": cites["documents"], "claims_total": None,
                "claims_citing_a_statement": None, "statements_cited": None,
                "by_statement": None, "dangling": None, "reason": cites["reason"]}
    if not cites["citations"]:
        reason = ("查过了：这一批稿件的正文断言里没有任何 `stmt:<命题号>` 引用 ⇒ "
                  "这一层读数是 0（不是没查成）。" + POLLUTION_SCOPE_BOUNDARY)
    else:
        reason = cites["reason"]
    return {"state": "computed", "readable": True, "documents": cites["documents"],
            "claims_total": cites["claims_total"],
            "claims_citing_a_statement": cites["claims"],
            "statements_cited": len(cites["by_statement"]),
            "by_statement": cites["by_statement"], "dangling": cites["dangling"],
            "reason": reason}


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
        # 没查成也要留读数（三态纪律）：改前 `store=None` 时这一格整格缺席，
        # 于是"没查成"与"没有这一格"同形 —— 读的人只能去猜。
        rep.readings["contradictions"] = {
            "wrong_paper": [], "disputed_source": [], "own_hole": [],
            "review_unresolved": [], "pollution": {},
            "pollution_states": {}, "pollution_unreadable": ["没有 store ⇒ 污染面没查成"],
            "pollution_scope": pollution_scope_text(),
            "pollution_proposition_level": proposition_level_pollution(None),
            "pollution_assertion_level": assertion_level_pollution(None),
            # 没查成的那两格给 `None`（不是 `{}`）：空字典会被读成"查过了、没有"。
            "pollution_assertions": None,
            "pollution_dangling_statements": None,
        }
        rep.findings.append(Finding("contradictions", "no_store", "warning",
                                    "没有 store ⇒ 矛盾没查成（不是没有矛盾）"))
        return
    wrong_paper: list[str] = []
    disputed_source: list[str] = []
    own_hole: list[str] = []
    unresolved_review: list[str] = []
    pollution: dict[str, list[str]] = {}
    #: 被证否的每一条命题，这一趟的污染面是"判了"还是"没判成"（三态的第二格）。
    pollution_states: dict[str, str] = {}
    #: 没判成的原因（空 = 全都判了）。
    pollution_unreadable: list[str] = []
    #: 被证否、且确实有结论压在它上面的那些（§9：压在上面的结论不能再算数）。
    #: 与 `own_hole` 分开：`own_hole` 说的是"我们的 proof 级证明压在不可用的命题上"，
    #: 而这一条不管压在上面的那几条是什么证据等级 —— 只要有人用，就必须处置。
    pollution_items: list[str] = []
    #: 正文断言层的逐条读数：`{命题号: [{doc_id, claim_id, citation}]}`。
    #: `draft/68` 题 1 选 A 之前这一格不存在（数据形式都没有）；现在它是
    #: "哪几条正文断言压在这条命题上"的机器读数（`_check_contradictions` 用它
    #: 决定 §9 的级联要不要覆盖稿件）。
    pollution_assertions: dict[str, list[dict[str, str]]] = {}
    #: 这一趟扫到的全部 `stmt:<命题号>` 引用里，目标命题不存在的那几条（悬空引用）。
    #: 它们不许被静默算成"压在某条命题上"，也不许被静默丢掉 —— 单独一栏报出来。
    dangling_statement_citations: list[dict[str, str]] = []
    cited_by_claims = statements_cited_by_claims(store)
    if cited_by_claims["state"] == "computed":
        dangling_statement_citations = list(cited_by_claims["dangling"])
    else:
        pollution_unreadable.append(
            "正文断言层的 `stmt:` 引用没查成：" + str(cited_by_claims["reason"]))

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
                sid = str(row.get("stmt_id"))
                reading = pollution_reading(store, sid)
                pollution_states[sid] = str(reading["state"])
                if reading["state"] != "computed":
                    pollution_unreadable.append(f"命题 {sid}：{reading['reason']}")
                downstream = list(reading["downstream"])
                pollution[sid] = downstream
                # 正文断言层（`draft/68` 题 1 选 A）：谁在稿件里引了这条被证否的命题。
                # 它单独一栏，不并进 `downstream`：两者处置不同 —— 命题要撤结论，
                # 稿件要 G 改稿（删断言或换依据）。
                pressed = list(reading["assertions"] or [])
                pollution_assertions[sid] = pressed
                if downstream or pressed:
                    why_parts: list[str] = []
                    if downstream:
                        why_parts.append(f"命题 {downstream} 跟着倒")
                    if pressed:
                        where = "、".join(f"{x['doc_id']}#{x['claim_id']}"
                                          for x in pressed[:6])
                        why_parts.append(f"正文断言 {where} 压在它上面（共 {len(pressed)} 条）")
                    pollution_items.append(f"命题 {sid} 被证否 ⇒ " + "；".join(why_parts))

    for row in store.rows("documents"):
        if str(row.get("status") or "") == "unresolved_review":
            unresolved_review.append(f"稿件 {row.get('doc_id')}")

    rep.readings["contradictions"] = {
        "wrong_paper": wrong_paper,
        "disputed_source": disputed_source,
        "own_hole": own_hole,
        "review_unresolved": unresolved_review,
        "pollution": pollution,
        "pollution_states": pollution_states,
        "pollution_unreadable": pollution_unreadable,
        "pollution_scope": pollution_scope_text(),
        # 命题层：现算（多少命题有下游 + 闭包大小分布）。
        "pollution_proposition_level": proposition_level_pollution(store),
        # 正文断言层：现算（多少条正文断言引了命题 + 每条命题被几条压着）。
        # 改前这一格是 `not_judged`（缺数据形式），现在是 `computed`/`unreadable`。
        "pollution_assertion_level": assertion_level_pollution(store),
        # 逐条命题的正文断言：`{命题号: [{doc_id, claim_id, citation}]}`。
        "pollution_assertions": pollution_assertions,
        # 悬空引用：引了 `stmt:<不存在的命题>` 的那些（单独一栏，不许折进上面两格）。
        "pollution_dangling_statements": dangling_statement_citations,
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
                     "要么把压在上面的结论一起降档或撤回。"
                     "压在它上面的**正文断言**（`pollution_assertions` 那一格）"
                     "由 G 改稿：删掉那条断言，或换成引一条还站得住的命题")
        pollution_note = ""
        if code == "contradiction_disputed_source" and pollution:
            pollution_note = ("；**污染面**（被证否的那些，谁跟着倒）："
                              + "；".join(f"{k} → {v}" for k, v in sorted(pollution.items())))
        rep.findings.append(Finding(
            "contradictions", code, level,
            f"{why}：共 {len(items)} 处 —— " + "；".join(items[:5]) + extra + pollution_note,
        ))
    rep.status["contradictions"] = "fail" if fired else "pass"
    if pollution_unreadable:
        # 污染面没查成 ⇒ 这一格不许说"通过"（三态：没查成落 unknown，不是 pass）。
        rep.findings.append(Finding(
            "contradictions", "pollution_unreadable", "warning",
            "污染面没查成（不是「没有下游」）：" + "；".join(pollution_unreadable[:3])))
        if not fired:
            rep.status["contradictions"] = "unknown"


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


def _alternatives_note(store: Any, kind: str, project_root: Path) -> str:
    """同一环里现在就能达标的其它成员档 —— 一段读数，接在没达标那一行的话后面。

    为什么要有它（T4 第 6 趟 `t4f` 的真机读数）：M 把"想"那一环声明成 `conjecture_rows`
    （这一趟 0 条），而同一环的 `statement_rows` 有 448 条 —— 它选了唯一为 0 的那一档，
    于是收工门报 `blocker acceptance_unmet`，M 看到之后仍按 `met=true` 收工。
    验收表的成员档本来就是可选的（`RESEARCH_CHAIN_GROUPS` 每一环给好几档），
    但"换一档就达标"这件事当时没有任何地方说出来 —— 这一句就是那句话。

    只报数、不判：哪一档是诚实的声明仍归 M 判（某个项目这一环真的没有对应产物时，
    正确做法是写 `na` + 理由，而不是挑一档数字好看的）。
    读不出来的档跳过（不编）。
    """
    for _label, members in RESEARCH_CHAIN_GROUPS:
        if kind not in members:
            continue
        alts: list[str] = []
        for m in members:
            if m == kind:
                continue
            try:
                got, detail = _leg_reading(store, m, project_root)
            except Exception:  # noqa: BLE001 —— 这一档读不出来就不提它（不编）
                continue
            kmin = (detail or {}).get("implicit_min") if isinstance(detail, dict) else None
            need = int(kmin) if kmin is not None else 1
            # 要有实质：`got ≥ 1` 且不低于它自己的下限。`got=0 / need=0` 那种"因为这一环
            # 没有研究问题、门槛被算成 0"的档不算出路 —— 提它等于教人换一档空声明。
            if int(got) >= max(1, need):
                alts.append(f"`{m}`（{got} ≥ {max(1, need)}）")
        if not alts:
            return ""
        return ("。同一环里现在就能达标的其它成员档：" + "、".join(alts)
                + " —— 验收表那一行写哪一档由你定（这一环的成员档是可选的）；"
                  "若这一环这个项目真的没有产物，写 `na` + 理由才是诚实的做法")
    return ""


def declared_report_sections(store: Any, report_path: str) -> tuple[list[str], str]:
    """M 声明的报告体例（`REPORT_STYLE_NAME`）；返回 `(节名, 为什么读不到)`。

    R9（`draft/52` 裁决 1 = C''）之后，报告体例由 M 裁定：门不再自带任何节名清单，
    只核对"M 声明的体例有没有兑现"。声明的落点是一份机器可读的小文件
    （`out/review/REPORT-STYLE.json`，形如 `{"sections": ["一、任务与范围", ...]}`）。

    三态（与全仓其余读数同一套纪律）：

    - 声明文件不在盘上 ⇒ `([], "")`：这一趟没有体例声明，门不判体例
      （不是"通不过"，也不是"通过"—— 读数里写 `style_source: "none"`）；
    - 读不懂 / 形状不对 ⇒ `([], 原因)`：没查成（不许折成"没声明"）；
    - 读到了 ⇒ `(节名, "")`，由调用方逐节核它在不在报告里。
    """
    if not str(report_path or "").strip():
        return [], ""
    try:
        style_path = Path(resolve_under_workspace(store, str(Path(report_path).parent / "REPORT-STYLE.json")))
    except Exception:  # noqa: BLE001 —— 解析不了 ⇒ 这一格没查成，由调用方落 unknown
        return [], "体例声明文件的路径解析不了 ⇒ 体例这一格没查成"
    if not style_path.is_file():
        return [], ""
    try:
        raw = json.loads(style_path.read_text(encoding="utf-8"))
        sections = raw["sections"] if isinstance(raw, dict) else raw
        if not isinstance(sections, list):
            raise ValueError("顶层必须是数组，或 {'sections': [...]}")
        out = [str(s).strip() for s in sections if str(s).strip()]
    except Exception as exc:  # noqa: BLE001 —— 读不懂就说读不懂
        return [], (f"{REPORT_STYLE_NAME} 读不出来（{type(exc).__name__}: {exc}）"
                    f"⇒ 体例这一格没查成（不是「M 没声明体例」）")
    return out, ""


def _check_report_shape(rep: ClosingReport, report_path: str, store: Any) -> None:
    """报告那一格：报告在不在、附件三件套齐不齐、M 声明的体例兑现没有（全是读数）。

    ## 为什么不再是"九节"

    R9（`draft/52` 裁决 1 = C''）："报告要写九节"是 review 线的交付规格，
    被当成通用判据用 ⇒ 直接废除（`REPORT_SECTIONS` / `SPLIT_MARKERS` 已删）。

    ## 为什么现在也不卡"形式"（业主 2026-10-09）

    逐字：「T1的5不是已经说过工作内容和交付形式由M决定了吗？不卡机械判据。但M需要知道
    一些任务需要的明确的交付格式，如什么叫论文包之类的。这样M在排任务的时候自然会把这些
    内容的生产写进任务排期。」

    ⇒ 这一格只做两件事：报告在不在盘上（不在 ⇒ `unknown` + warning；读不成 ⇒
    `unknown`）与把缺的件逐条摆出来（附件三件套、M 声明的体例，各进一条 warning）。
    报告在盘上且读得成 ⇒ `pass`。此前它把"缺附件三件套的一件"读成 `fail` + `blocker`
    （T1 `t1v` 与 T2 `t2a` 连续两趟就是被这一格拦下的），而裁定 3 已经定了收工由 M 判。

    两个码分开（`attachment_fields_missing` / `declared_sections_missing`）：
    它们要读的人不同 —— 前者是"这条结论的来路没写全"，后者是"M 自己声明的体例没兑现"。
    （`draft/44` J-19 那条"并入同一个 code"针对的是拦门的码表；
    这一格已经不拦门，两条读数各自点名比合成一句更好读。）
    """
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
            f"报告不在盘上：{path} ⇒ 没查成。报告是 M 的产物（落点 out/review/REPORT.md）",
        ))
        return
    text = path.read_text(encoding="utf-8")
    has_attach = [f for f in ATTACHMENT_FIELDS if f in text]
    missing_attach = [f for f in ATTACHMENT_FIELDS if f not in text]
    declared, style_why = declared_report_sections(store, report_path)
    headings = [line for line in text.splitlines() if line.lstrip().startswith("#")]
    missing_declared = [s for s in declared
                        if not any(s in line for line in headings)]
    rep.readings["report_shape"] = {
        "path": str(path), "chars": len(text),
        # 兼容读数：既有的测试与下游读这两个键
        "attachment_fields": has_attach,
        "missing_attachment_fields": missing_attach,
        "style_source": REPORT_STYLE_NAME if declared else ("none" if not style_why else ""),
        "declared_sections": declared,
        "missing_declared_sections": missing_declared,
        "note": ("体例由 M 裁定（R9）：门只核对 M 在 "
                 f"{REPORT_STYLE_NAME} 里声明的节名有没有在报告的标题行里兑现；"
                 "没声明就不判体例（读数 `style_source: \"none\"`）。"
                 "附件三件套与体例**都只作读数**（业主 2026-10-09：交付形式由 M 决定，"
                 "不卡机械判据）—— 缺哪几件逐条进 `findings`（warning），"
                 "报告在盘上这一格就 `pass`；报告不在盘上/读不成才 `unknown`。"),
    }
    if style_why:
        # 体例文件在、读不成 ⇒ 这一格 `unknown`（"没查成"不是"通过"）。
        # 注意这与上面那条裁定不冲突：这是"读不成"，不是"形式不合我意"。
        rep.status["report_shape"] = "unknown"
        rep.findings.append(Finding(
            "report_shape", "report_style_unreadable", "warning",
            f"{style_why}（体例这一格没查成，不是「体例没问题」）",
        ))
        return
    # ---- 交付形式归 M（业主 2026-10-09）：「工作内容和交付形式由 M 决定……不卡机械判据」。
    #
    # 这一格此前把"附件三件套缺一件"与"M 声明的体例没兑现"读成 `fail` + `blocker`
    # （T1 t1v 与 T2 t2a 连续两趟就是被这一格拦下的，而两趟的 M 都自己判过"活做完了"）。
    # 现在这两件事逐条进读数与 warning：可见性一格不减，强度归零 ——
    # 形式是 M 的决定，机器只负责把它摆在纸上。报告不在盘上/读不成仍 `unknown`
    # （"没查成"不许折成"通过"）。
    if missing_attach:
        rep.findings.append(Finding(
            "report_shape", "attachment_fields_missing", "warning",
            f"报告里没有附件三件套的 {len(missing_attach)} 件"
            f"（{'、'.join(missing_attach)}）—— 它们不是排版，是「这条结论是不是我们自己"
            "做的（`origin=own_result`）、依据在哪（`依据`）、文件有没有被换过（`sha`）」；"
            "**交付形式由 M 定**（业主 2026-10-09），这一条只作读数不拦收工",
        ))
    if missing_declared:
        rep.findings.append(Finding(
            "report_shape", "declared_sections_missing", "warning",
            f"缺 M 声明的体例里 {len(missing_declared)} 节"
            f"（{'、'.join(missing_declared[:4])}）—— 体例由 M 自己裁定"
            f"（{REPORT_STYLE_NAME}），这一句是「你说的和你写的不一致」的读数，不是拦门",
        ))
    rep.status["report_shape"] = "pass"


def _check_artifact_ledger(rep: ClosingReport, store: Any, project_dir: str) -> None:
    """第八格（EE-05，`draft/52` C4）：产物台账必须与盘上一致。

    三态按判据强度收窄（这是 C4 的核心，避免把正常产物读成坏）：

    - 全部 `ok` ⇒ `pass`；
    - 有 `missing` / `unreadable` ⇒ `fail`（登记过的东西盘上没了 / 读不到 —— 真缺陷）；
    - 只有 `changed` ⇒ `pass` + warning（D9，2026-10-09 裁定"收窄"）：比对口径改成
      按路径取最后一条登记（台账是 append-only 历史，逐行比会把正常改写读成 changed），
      而"最后一次登记之后又被改写"是常态（真机 t1u：23 条全是框架自己幂等重写的
      `out/tasks/*.json`）⇒ 不再把这一格读成 `unknown`（旧口径下任何有派活的跑批都收不了工）；
    - 台账不在盘上 ⇒ `pass` + 读数写明"没有这一栏"（`absent: true`）——
      与 `acceptance` 对非研究型项目的口径一致："没有这一栏"不是"没查成"。
      要说清的是"这一趟没有产物台账"，而不是"产物与盘上一致"（读数里 `entries: 0`
      与 `absent: true` 分得开）。
    """
    if not str(project_dir or "").strip():
        rep.status["artifact_ledger"] = "unknown"
        rep.findings.append(Finding(
            "artifact_ledger", "no_project_dir", "warning",
            "没给项目根 ⇒ 产物台账这一格没查成（不是「盘上一致」）"))
        return
    root = Path(resolve_under_workspace(store, project_dir))
    try:
        got, detail = artifact_ledger_reading(root)
    except LegNotApplicable as exc:
        rep.status["artifact_ledger"] = "pass"
        rep.readings["artifact_ledger"] = {"reason": exc.reason, "absent": True,
                                           "entries": 0, "implicit_max": 0}
        return
    except Exception as exc:  # noqa: BLE001 —— 读不到就落 unknown
        rep.status["artifact_ledger"] = "unknown"
        rep.readings["artifact_ledger"] = {"error": f"{type(exc).__name__}: {exc}"}
        rep.findings.append(Finding(
            "artifact_ledger", "artifact_ledger_unreadable", "warning",
            f"产物台账读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"))
        return
    rep.readings["artifact_ledger"] = detail
    missing, unreadable, changed = detail["missing"], detail["unreadable"], detail["changed"]
    if missing or unreadable:
        rep.status["artifact_ledger"] = "fail"
        rep.findings.append(Finding(
            "artifact_ledger", "artifact_ledger_bad_rows", "blocker",
            f"产物台账与盘上对不上："
            + "；".join(x for x in (
                f"{missing} 条登记过的产物盘上没了" if missing else "",
                f"{unreadable} 条读不到 / 台账里有坏行" if unreadable else "") if x)
            + f"（对不上的行共 {got} 条；明细见读数 `artifact_ledger.bad_rows`）。"
              "产物登记必须与盘上一致：盘上没了就是没了，不要留在台账里充当产出"))
        return
    if changed:
        # D9（业主 2026-10-09 裁"收窄"）：最后一次登记之后又被改写 ⇒ pass + warning。
        # 依据：真机 t1u 的 23 条 changed 全是框架自己幂等重写的 `out/tasks/*.json`
        # （per-task 摘要），旧口径把它们读成 `unknown` ⇒ 任何有派活的跑批都收不了工。
        # 判"交出去的那一版有没有被换过"是 `anchor` / 编译回执那一维的事。
        rep.status["artifact_ledger"] = "pass"
        rep.findings.append(Finding(
            "artifact_ledger", "artifact_ledger_changed_only", "warning",
            f"有 {changed} 条产物的**最后一次登记**之后又被改写过（盘上还在，"
            "只是不是登记时那一版）⇒ 这一格仍记 `pass`，但这件事看得见："
            "改写在研究流程里是常态（真机上 23 条全是框架自己重写的 `out/tasks/*.json`），"
            "直接判 fail 会把正常产物读成坏。要判「交出去的那一版有没有被换过」"
            " ⇒ 看 `anchor` / 编译回执那一维",))
        return
    rep.status["artifact_ledger"] = "pass"


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

def _escalation_reading(session_root: Any, sid: str | None, tasks: list[dict[str, Any]],
                        ) -> dict[str, Any]:
    """"干不了/没做完"的那些项，有没有在本段会话里上报（业主 2026-10-09 第三句）。

    「如果某代理认为某件任务自己无法胜任且无法通过派子代理解决，则会将情况上报父智能体。
    特别地，M 向用户上报。」⇒ 上报要有落盘的载体，本函数按两处找：

    - M → 用户：`userio.pending_questions`（还没答的）+ `userio.read_replies`（答过的）
      —— 这两处合起来就是"问过用户"的全集；
    - 子 → 父：会话里的 `agent_message`（S1k 的名字面：给父/给名下子代理的报文，
      `to` 是名册名或角色名）与 `agent_handoff`（交接手稿那一行也是上行）。

    匹配是字面的：项里的 `what`（去掉空白）要出现在某条上报的正文/标题/问题正文里。
    这是刻意的弱判据 —— 它只回答"这件事有没有被说出来"，不评价说得对不对
    （那要人读）。`what` 太短（<2 字）时不做字面匹配，只认"有上报"这一档，
    免得一个单字把任何一条报文都判成"说到了"。

    三态：会话读不成 / 没有会话根 ⇒ `checked=False` + `reason`（"没读成"不是"没上报"）。
    """
    open_items = [{"what": str(t.get("what") or ""), "state": str(t.get("state") or ""),
                   "why": str(t.get("why") or "")}
                  for t in tasks if str(t.get("state") or "") != "done"]
    if not open_items:
        return {"checked": True, "open_items": [], "escalations": [], "gaps": [], "reason": ""}
    if session_root is None:
        return {"checked": False, "open_items": open_items, "escalations": [], "gaps": [],
                "reason": "没有会话记录根 ⇒ 上报这一格没查成"}
    from . import sessions as SS

    texts: list[dict[str, Any]] = []
    try:
        for q in U.pending_questions(session_root, sid=sid):
            texts.append({"kind": "question", "id": str(getattr(q, "qid", "")),
                          "text": str(getattr(q, "text", ""))})
        for r in U.read_replies(session_root, sid=sid):
            texts.append({"kind": "answer", "id": str((r or {}).get("qid") or ""),
                          "text": str((r or {}).get("answer") or "")})
        events, problems = SS.read_session(session_root, sid=sid)
        if problems:
            return {"checked": False, "open_items": open_items, "escalations": [], "gaps": [],
                    "reason": f"会话有 {len(problems)} 处读不出来：{problems[0]}"}
        for e in events:
            if str(e.get("kind")) in ("agent_message",):
                texts.append({"kind": "message", "id": str(e.get("msg_id") or ""),
                              "text": f"{e.get('subject') or ''}\n{e.get('body') or ''}"})
            elif str(e.get("kind")) in ("agent_handoff", "handoff"):
                texts.append({"kind": "handoff", "id": str(e.get("id") or ""),
                              "text": f"{e.get('summary') or ''}\n{e.get('body') or ''}"})
    except Exception as exc:  # noqa: BLE001 —— 读不成不等于没上报
        return {"checked": False, "open_items": open_items, "escalations": [], "gaps": [],
                "reason": f"{type(exc).__name__}: {exc}"}
    found: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for item in open_items:
        needle = "".join(str(item["what"]).split())
        hit = None
        if len(needle) >= 2:
            for t in texts:
                if needle and needle in "".join(t["text"].split()):
                    hit = t
                    break
        elif texts:
            hit = texts[0]          # `what` 太短 ⇒ 只认"有上报"这一档（并如实记下这一档）
        if hit:
            found.append({**item, "via": hit["kind"], "ref": hit["id"]})
        else:
            gaps.append(item)
    return {"checked": True, "open_items": open_items, "escalations": found, "gaps": gaps,
            "reason": ""}


def check_closing(store: Any, *, project_dir: str = "", report_path: str = "",
                  session_root: Any = None, checks: tuple[str, ...] = DEFAULT_CHECKS,
                  sid: str | None = None,
                  goal: str = "", goal_met: bool | None = None, basis: str = "",
                  task_list: Iterable[Mapping[str, Any]] = (),
                  ) -> ClosingReport:
    """跑收工门，返回读数（不抛业务异常 —— 没查成落成 `unknown`）。

    `session_root` 不给时取 `store.root`（会话记录与工作区本来就是同一个根，
    两处分开写迟早会出现"审计记录落在别处"的静默错位）。
    `project_dir` / `report_path` 不给 ⇒ 对应的那一两格是 `unknown`（不是 pass）：
    门宁可说"我没查成"，也不许在缺少读数时说"可以交"。
    `sid` 三态见 :data:`NO_SESSION`：具体会话号 / `None`（缺省会话）/
    `NO_SESSION`（没有会话身份 ⇒ `user_pending` 那格 `unknown`）。

    ## 收工由 M 判（业主 2026-10-09）

    第一句：「是否收工不要用机械判据，由 M 制定的目标是否达成为准」；
    第二句：「所有智能体是否能停都是看自己被派的活有没有做完，M 也不例外，
    只是 M 需要根据用户指令给自己设计任务列表」⇒ 于是：

    - `task_list` 是 M 自己列的任务（`[{what, state: done|not_done|cannot, why}]`）——
      停的判据是它，不是八格；
    - `goal_met` 是 M 的一句话结论（`None` = 它没判 ⇒ `can_close=false` + 「没人判过」）；
    - `goal` / `basis` 是它的自述（目标是什么、依据哪几条读数）；
    - 八格照旧逐格现算，作为读数（`status` / `machine_pass`）与 `overrode`
      （不一致逐格点名）留在报告里；`verdict_conflicts` 再点名"自述与自己的任务列表
      对不上"的地方 —— 判据归 M，读数的可见性不减。
    """
    rep = ClosingReport()
    tasks = [dict(t) for t in (task_list or ()) if isinstance(t, Mapping)]
    root = session_root if session_root is not None else getattr(store, "root", None)
    if goal_met is not None or tasks:
        rep.m_verdict = _m_verdict_payload(goal=goal, met=goal_met, basis=basis,
                                           tasks=tasks)
        rep.readings["verdict_source"] = {"where": "这一次调用给的（M 自己在运行内交的）",
                                          "path": "", "count": 0, "at": rep.m_verdict["at"]}
    else:
        # ---- 回退：读落盘的 M 判据（业主 2026-10-09 第 3 句裁定之后的"运行外出口"）
        #
        # 为什么必须有这一支：判据由 M 在运行内给（`conductor.closing` 那一步把它
        # 落盘），而门还有运行外的出口（`agentflow closing`、发布门）。没有这一支，
        # 运行外那一趟会得出"没人判过"（退出码 2），而运行内 M 明明判过
        # —— 那正是 `draft/37` §63 记过的"运行内/外部读数不一致"。
        #
        # 三态：读不成 ⇒ 如实落 `verdict_source`（`checked=False`），并仍然按
        # "没有判据"走（2）—— 绝不用一个读不到的东西冒充 M 判过。
        #
        # `project_dir` 的解析必须走 `resolve_under_workspace`：工具契约写的是
        # "相对工作区"，而 `Path(".")` 是按进程当前目录解析的 —— 真机 t1v 就是
        # 这么把判据写到了跑批的工作目录（`agentflow/out/review/`）而不是工作区里，
        # 于是两处读数当场分家：M 判了达成，而外部门说"没人判过"。
        vroot_s = resolve_under_workspace(store, project_dir) if str(project_dir or "").strip() \
            else (str(root) if root is not None else "")
        vroot = Path(vroot_s) if vroot_s else None
        if vroot is not None:
            got = read_m_verdict(vroot)
            rep.readings["verdict_source"] = {
                "where": "落盘的 M 判据（`out/review/m-verdicts.jsonl`）",
                "path": str(got.get("path") or ""), "count": int(got.get("count") or 0),
                "checked": bool(got.get("checked")),
                "reason": str(got.get("reason") or ""),
                "at": str((got.get("verdict") or {}).get("at") or "")}
            if got.get("checked") and got.get("verdict"):
                rep.m_verdict = dict(got["verdict"])
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
        elif name == "artifact_ledger":
            _check_artifact_ledger(rep, store, project_dir)
        else:
            rep.status[name] = "unknown"
            rep.findings.append(Finding(name, "unknown_check", "warning",
                                        f"没有这个检查：{name!r}（判据表与实现在这里分家了）"))
    # 上报那一格（业主 2026-10-09 第三句）：它不属于八格，是 M 的判据的伴生读数 ——
    # "干不了/没做完的项有没有说出来"。放这里是因为它要读会话，而会话根只在这个入口有。
    if rep.m_verdict:
        rep.readings["verdict_escalation"] = _escalation_reading(
            root, sid, list(rep.m_verdict.get("tasks") or []))
    return rep


#: M 的收工判据落盘的地方（append-only，一行一次判断）。
#:
#: 为什么必须有这一格（业主 2026-10-09 第 3 句裁定之后）：判据由 M 在运行内给出
#: （`conductor.closing` 带着 `goal_met` 的那一次调用），而门还有运行外的出口
#: （`agentflow closing` 给 CI / 发布门用）。两个出口必须得出同一个结论 ——
#: `draft/37` §63 记过一次"运行内报 `can_close=true`、外部带 sid 报 `failed=[...]`"
#: 的假绿，成因就是"运行内那一份判据没有落盘"。
#:
#: 所以：M 给判据那一次调用把它落盘（`write_m_verdict`），运行外的出口读它
#: （`check_closing` 在没有显式入参时的回退，`read_m_verdict` 三态）。
#: 读侧取最后一行（append-only 的历史留着，人能看到判据是怎么变的）。
M_VERDICT_FILE: tuple[str, ...] = ("out", "review", "m-verdicts.jsonl")


def m_verdicts_path(root: str | Path) -> Path:
    """M 的收工判据落在哪儿（`<root>/out/review/m-verdicts.jsonl`）。"""
    return Path(root).joinpath(*M_VERDICT_FILE)


def _m_verdict_payload(*, goal: str, met: bool | None, basis: str,
                       tasks: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """把 M 的自述折成一条判据（`check_closing` 与 `write_m_verdict` 共用一处形状）。"""
    items = [dict(t) for t in (tasks or ()) if isinstance(t, Mapping)]
    return {"goal": str(goal or ""),
            "met": bool(met) if met is not None else False,
            "basis": str(basis or ""), "tasks": items,
            "counts": {"done": sum(1 for t in items
                                   if str(t.get("state") or "") == "done"),
                       "not_done": sum(1 for t in items
                                       if str(t.get("state") or "") == "not_done"),
                       "cannot": sum(1 for t in items
                                     if str(t.get("state") or "") == "cannot"),
                       "total": len(items)},
            "at": S.now_iso()}


def write_m_verdict(root: str | Path, *, goal: str = "", met: bool | None = None,
                    basis: str = "", tasks: Iterable[Mapping[str, Any]] = (),
                    sid: str = "", who: str = "M") -> tuple[bool, str]:
    """把 M 这一次的收工判据追加落盘。返回 `(成不成, 为什么)`。

    调用点是运行内那一次 `conductor.closing`（M 自己交判据的那一步）——
    门本身（`check_closing`）仍然只读：它不写任何东西，只回退读这一份。
    """
    from .secretary import append_jsonl          # 唯一的 jsonl 追加口（带锁）

    rec = {"kind": "m_verdict", "who": str(who or "M"), "sid": str(sid or ""),
           **_m_verdict_payload(goal=goal, met=met, basis=basis, tasks=tasks)}
    try:
        path = m_verdicts_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        return append_jsonl(path, rec)
    except Exception as exc:  # noqa: BLE001 —— 落盘失败要说出来（不许当"判过没达成"）
        return False, f"{type(exc).__name__}: {exc}"


def read_m_verdict(root: str | Path) -> dict[str, Any]:
    """读回落盘的 M 判据（三态）：`{"checked","verdict","count","path","reason"}`。

    - 文件没有 / 一行都没落过 ⇒ `checked=True, verdict=None`（"还没判过"，
      不是"判过没达成"—— 这两件事在退出码上分得很开：2 与 1）；
    - 有坏行 ⇒ `checked=False` + 理由（不猜一行出来，也不静默跳过当"没判过"）；
    - 取最后一行（append-only：判据改过几次都留在纸上，取最新那一次）。
    """
    path = m_verdicts_path(root)
    out: dict[str, Any] = {"checked": True, "verdict": None, "count": 0,
                           "path": str(path), "reason": ""}
    if not path.is_file():
        out["reason"] = "还没落过 M 的收工判据（不是『判过、没达成』）"
        return out
    rows: list[dict[str, Any]] = []
    bad: list[str] = []
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"第 {i} 行读不出来（{type(exc).__name__}）")
                continue
            if isinstance(rec, Mapping) and str(rec.get("kind") or "") == "m_verdict":
                rows.append(dict(rec))
    except Exception as exc:  # noqa: BLE001
        out.update(checked=False, reason=f"判据落盘读不成（{type(exc).__name__}: {exc}）")
        return out
    if bad:
        out.update(checked=False, reason="；".join(bad[:3]))
        return out
    out["count"] = len(rows)
    if rows:
        out["verdict"] = rows[-1]
    else:
        out["reason"] = "这一份里没有 `kind=m_verdict` 的行（不是『判过、没达成』）"
    return out


def tri_state_exit_code(rep: ClosingReport) -> int:
    """CLI 的三态退出码：0 可交付 / 1 被拦住 / 2 没查成。

    口径按业主 2026-10-09 的裁定改：0 只在 M 判了"达成"时给（`can_close`）；
    M 没判 ⇒ 2（"没人判过" = 没查成，不是"被拦住"也不是"可交付"）；
    M 判了"没达成" ⇒ 1。机器那八格只在读数里说话（`machine_pass` / `failed` / `unknowns`）。
    """
    if rep.can_close:
        return 0
    if not rep.m_verdict:
        return 2
    return 1
