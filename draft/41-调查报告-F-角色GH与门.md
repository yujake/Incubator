# 调查报告 F：角色 G、H、稿件/论文与收工门

- 仓库：`D:\Incubator\agentflow`；包 `agentflow`；源码 `src/agentflow/`
- 本报告只描述"是什么"，不含修改建议。
- 唯一写入的仓库外产物：本报告；另有三个探针脚本写在仓库外的 `D:\Incubator\temp\gh_probe_1.py` / `gh_probe_2.py` / `gh_probe_3.py`（只在系统临时目录造工作区，不碰仓库）。
- 取证方式：`read` / `grep` / `glob`；`python -B -c` 做 AST 与文本统计；`projects/*` 下的台账、产物、会话当真机证据；`closing` / `renderanchor` / `review_tools` / `signatures` / `evidencebits` 的纯读调用。未跑模型、未跑全量 pytest、未跑 pdflatex。
- 行号口径：全部按**盘上当前版本**（`git status` 显示 `closing.py` / `conductor.py` / `agent_prompts.py` / `specs/m.py` 等有未提交改动，改动时间 2026-10-06 15:00:52–15:01:01，早于本次调查；本次调查未写仓库内任何文件）。

真机证据清单（下文反复引用）：

| 工作区 | 关键读数 |
|---|---|
| `projects/p8g-fermat-shorter-proof` | `documents/0000` 三节 `body` 全为空串、`status=accepted`、`review_rounds=0`、有签名 |
| `projects/p5-review-t17` | `documents/0000` 五节 `body` 全空；锚的 `files` 含 `ACCEPTANCE-CHECKS.json` |
| `projects/p8e-fermat-shorter-proof` | `documents/0000` `status=revised`、`revision=2`，签名钉在旧版（`e7346eb7…` vs 现行 `68bfc4c7…`） |
| `projects/p7b-open-questions` | 验收表里出现 `"na": true` 两行（`numeric_experiment_rows`、`supported_claims`） |
| `p8g`/`p8f`/`p6q`/`p5-review-t17`/`p7b`/`p8e` 的 `manuscripts/handoffs.jsonl` | 62–96 行，100% 是框架派生模板，`refs` 逐行全空 |

---

## 1. 机制

### 1.1 G：一条断言怎么被登记

**构造入口。** `AgentG.compose_claim`（`agent_g/compose_claim.py:10-71`）是纯转发，判据一份在工具层：`doc_tools.compose_claim`（`tools/doc_tools.py:684-810`）。

- `doc_tools.py:749-758`：先判三条"现场信息最全"的（`citations` 为空、正文为空、`citations` 含空元素）并直接抛，理由是它要的报错里带断言原文。
- `doc_tools.py:769`：`evidence_kind == "cross_check"` 时**自动**把 `disclaimer` 填成 `CROSS_CHECK_DISCLAIMER`（常量在 `doc_tools.py:67`，逐字「数值交叉验证，不构成证明」）。这是"结构强制、不靠人记得写"的落点。
- `doc_tools.py:772-791`：§8.3 的 10 个生命周期字段**给了才写键**（`if val is None: continue`）；`freeze_reason` 空串也不写；`frozen is True` 才写。
- `doc_tools.py:798-810`：唯一的判据来源是 `claimanatomy.validate_claim`，取第一个 error 抛出（报错里带族号与正例，`family_note`），并断言 `check.checked` 为真。

**逐条硬校验（都在 `claimanatomy.validate_claim`，`claimanatomy.py:1076-1523`）。**

| 判据 | 位置 | 级别 |
|---|---|---|
| 未声明字段 | `claimanatomy.py:1157-1172`（`undeclared_field`） | warning |
| 必填字段缺失 / 空值 | `1179-1218`（`missing_field` / `empty_required`） | error |
| 类型非法 / 词表外取值 | `1219-1256`（`bad_type` / `bad_enum`） | error |
| `numeric_evidence` 四元组缺键 | `1257-1272`（`incomplete_numeric_evidence`） | error |
| `cross_check` 缺独立 `disclaimer` 栏 | `1282-1301`（`missing_disclaimer`） | error |
| 非 proof 档出现证明性措辞 | `1302-1320`（`overclaim`，词表 `doc_tools.OVERCLAIM_MARKERS:71-74`） | error |
| 否定型未分类 / 非否定型带了分类 | `1331-1362` | error |
| `citations` 空 / 含空元素 | `1371-1398` | error |
| `frozen=True` 无 `freeze_reason` | `1401-1414` | error |
| `status × evidence_kind` 两轴不自洽 | `1419-1432`（`inconsistent_status`） | error |
| 两轴判不了 | `1433-1452`（`unknown_status_axis`） | info（`decided=False`） |
| `status='作废'` 无 `errata_ids`/`freeze_reason` | `1455-1477`（`lifecycle_incomplete`） | error |

`evidence_kind` 三档 = `schema.EVIDENCE_KINDS = ('proof','cross_check','heuristic')`（渲染用的中文标签在 `doc_tools.py:78-82`）。`disclaimer` 必须写在**独立一栏**：写进 `text` 不算（判据只看 `disclaimer` 键，`claimanatomy.py:1282-1301`；工具参数描述也逐字写了这一点，`doc_tools.py:1630-1633`）。

**落库闸门：`build_document`（`doc_tools.py:1186-1349`）。** 顺序刻意是"先逐条机械检查 → 再核引用存在性 → 再核 proof 证据锚 → 再分配 ID → 再渲染 → 最后提交"：

1. `normalize_claims`（`1112-1183`）：丢掉模型自写的 `claim_id`，按顺序补成 `claim-1…claim-N`（`1145-1146`）；本文档内自指（`proof_location="claim-3:12"`）按别名表改写（`1150-1155`）；正文字段名 `statement` → `text`（唯一迁移点，`1162`）；逐条 `scan_claim`，有 error 就抛（带族号与断言原文，`1167-1181`）。
2. `check_citations`（`356-429`）：引用前缀 → 表的映射只有一份 `_CITATION_TABLES = {rel/lit/exp/eval}`（`319-324`），前缀不认识即 fail-closed（`393-405`）。`rows_of is None` ⇒ `checked=False`（"没查"，不是"引用都在"）。
3. `check_proofs`（`477-678`）：`evidence_kind="proof"` 必须至少有一条 `exp:` 引用、被引实验本身必须是 proof 级、必须给 `proof_location`、且 `proof_location` 要么是本文档真实存在的 `claim_id`（`classify_proof_location`，`432-474`），要么指向工作区内盘上真实存在的文件。
4. 覆盖守卫（`1290-1315`）：`out_path` 已存在且不是任何 `documents` 行的 `markdown_path` ⇒ 整笔拒绝（真机案例：26 KB 正文被 4 KB 台账稿覆盖）。
5. 写侧算 `content_sha256`（`1333-1335`，实现只有 `signatures.content_sha256_of`，覆盖 `kind/title/sections/claims/open_problems` 五个字段，`signatures.py:38-71`）。

**`sections` 的形状。** `build_document:1229-1233` 只要求每项是含 `heading` 的对象，`body` 缺省即 `""`；`sections` 本身在工具参数里**不是必填**（`required: ["kind","title","claims"]`，`doc_tools.py:1648`）。渲染层**从不读 `doc["sections"]`**：`render_markdown`（`816-1106`）通篇只用 `claims`（按 `claim.section` 分组）、`open_problems` 与依赖表（`grep sections tools/doc_tools.py` 只命中 8 处，全在 `build_document` 与工具声明里）。因此 `sections[].body` 是人读 markdown 里**看不见**的一栏。

### 1.2 G：稿件的状态机与 `revise`

状态词表 `schema.DOC_STATUSES = ('draft','in_review','revised','accepted','rejected','unresolved_review')`。

- 落稿即 `draft`、`review_rounds=0`、`revision=1`（`doc_tools.py:1324-1326`）。
- H 的 `review` 把状态推成 `accepted` 或停在 `in_review`（`review_tools.py:1045-1046`）。
- `G.revise`（`agent_g/revise.py:10-177`）：`review_rounds += 1`、`status = "revised"`、`revision += 1`、重算 `content_sha256`（`116-128`），然后重渲染 markdown（`148-161`）。`new_claims` 里**代号已存在即替换原断言**，新代号追加（`57-70`）——没有这条替换语义，G 只能"再加一句新话"。三道闸全部复用 `build_document` 的同一批函数：`normalize_claims`（`75`）、`check_citations`（`79`）、`check_proofs`（`102`）。
- `fixed_findings` 只改 `status`/`resolution_note`，内容一个字不改；发现不属于本稿即抛（`130-146`）。G 自称 `fixed` 不是终局：`verify_fixes` 重跑检查、仍复现就改回 `open`（`review_tools.py:1267-1282`）。
- `refresh_markdown`（`agent_g/refresh_markdown.py:10-30`）只重画 markdown、不动任何数据行（依赖是稿件写完后才登记的，所以需要这一步）。

### 1.3 G：论文包那条路（`paper_package`）与回执

`AgentG.paper_package`（`agent_g/paper_package.py:37-98`）一次做三件事，顺序是**渲染 → 编译 → 核锚**：

- 渲染 = `DT._paper_render`（`doc_tools.py:1852-1867`）→ `paperbuild.run_script` 跑项目脚本（默认 `code/make_paper.py`），读回脚本自己那行 `REPRO_RESULT: {json}`；"算不算走成"= 退出码 0 且结论行存在且结论行里的 `ok` 不为 `False`（`paperbuild.py:141-161`）。
- 编译 = `DT._paper_compile`（`doc_tools.py:1869-1884`）→ 默认 `code/compile_paper.py`。
- 核锚 = `DT._paper_state`（`doc_tools.py:1824-1844`）→ `paperbuild.state` → `renderanchor.check_package`，**进程内、不起子进程、不出网**（所以只读角色 H 也拿得到：`roles=("G","H")`，`doc_tools.py:2081`）。
- 三段各自的失败归 `render_failed` / `compile_failed` / `state_failed`（`paper_package.py:59-79`）；`verdict=drifted` **不是**这个动作的失败，是读数（`paper_package.py:82-97`）。

锚与回执是**两件东西**（`renderanchor.py:1-25`）：

- 锚 `RENDER-ANCHOR.json`（渲染时写）：`tables` = 六张源表的 `{rows, sha256}`（`ANCHOR_TABLES`，`renderanchor.py:34-35`；`build_anchor:90-112`），`files` = 该次渲染在包目录下产出的**源文件** sha256（`package_files:74-87`，排除 `COMPILE_PRODUCTS` 与 LaTeX 中间产物）。
- 回执 `COMPILE-RECEIPT.json`（编译时写）：`tex_sha256` / `pdf_sha256` / `pages` / `markers_missing` / `compiler_exit_codes`（`build_receipt:115-142`）。
- `main.tex` 的 sha256 进回执的那一步**不在框架里**，在项目脚本里：`projects/p5-review-t17/code/compile_paper.py:22-30` 逐字是 `RA.build_receipt(out, tex_sha256=RA.file_digest(out / "main.tex"), …)`，再写 `out/paper/COMPILE-RECEIPT.json`（该脚本的注释还写明本环境没有 LaTeX 工具链、PDF 未重排、数字照实数记）。
- 核锚三维（`check_package:229-313`）：`tables`（行数+规范哈希逐表比）、`files`（锚里有盘上没了 / 内容不同 / 盘上有锚里没有，三个方向都算漂移）、`receipt`（`main.tex` 现哈希 vs 回执 `tex_sha256`；再比 `main.pdf` 现哈希 vs 回执 `pdf_sha256`）。总体取最坏的一档（`consistency=0 < unknown=1 < drifted=2`，`_result:316-350`）。
- 构建历史 `BUILD-HISTORY.jsonl` 是追加式读数、不参与判定（`renderanchor.py:39-50`；`history:165-207`）。

### 1.4 H：一次 `review` 做了什么

`AgentH.review`（`agent_h/review.py:10-40`）转发 `review_tools.review_document`（`tools/review_tools.py:907-1106`），核心是纯函数 `scan_document`（`307-813`，507 行）：

**机械检查逐条（每一条都带 `evidence` = 触发它的实际值）：**

| 检查 | 位置 |
|---|---|
| 断言不是对象 | `368-381`（`garbled`/error） |
| 无引用 | `389-399`（`unsupported_claim`/error） |
| 引用含空/非字符串元素 | `403-414`（`garbled`/error） |
| `evidence_kind` 非法 | `420-430`（`garbled`/error） |
| `cross_check` 缺 `disclaimer` | `432-442`（`overclaim`/error） |
| 非 proof 档出现证明性措辞 | `443-457`（`overclaim`/error） |
| 否定型未分类 | `463-476`（`missing_negation_kind`/error） |
| 非否定型却带否定分类 / 否定分类非法 | `486-513`（error） |
| 同一 `claim_id` 两段不同文字 | `514-526`（`inconsistent_number`/error） |
| 依赖 `dangling` / `external_unavailable` | `667-718`（前者 error、后者 warning，FC-13 分级） |
| 生命周期/降级/冻结/未声明字段（H 原先没有的那些） | `637-665`，判据来自 `claimanatomy.validate_claim`，`_H_OWN_CODES`（`88-101`）把 H 自己循环里已有的 code 跳过以免同一缺陷报两遍 |

**语义判据**（`review_tools.py:528-625`）：接缝是 `semantic_judge(claim, doc) -> {verdict, reason}`，词表 `SEMANTIC_VERDICTS = ("consistent","stronger_than_evidence","unknown")`（`190`）。**判据只喂被审稿件里当前的每一条 `claims`**（`560-565`），问的是"这条断言的措辞有没有超出它挂的证据等级"。判不出来时：没接线 ⇒ `checked=False` + 逐字理由（`197-201`）、模型答 `unknown` ⇒ 单独计 `claims_unknown`、判据自己抛异常或返回词表外的值 ⇒ `checker_errors += 1` + 一条 warning 级 `garbled`（`566-595`）。LLM 判成 `stronger_than_evidence` 时落一条 **warning** 级 `overclaim`（`600-619`，理由是不把可能犯错的判据升到 error）。判据提示词与负控表在 `judges.py:160-212`（`claims.conclusion_strength`，词表 `within_evidence/overclaimed/unjudgeable`，两条负控）；两套词表的单向映射在 `judges.semantic_judge_for`（`325-370`）。

**覆盖率三态**（`762-778`）：`claims_total` / `claims_reviewed`（逐条检查真的跑过）/ `claims_decided`（其中校验器判成了）/ `claims_semantically_judged`（语义判据真的判过，没接线时恒为 0）。返回值同时给 `dep_check` 与 `semantic_check` 两个"没查"（`795-813`）。

**verdict 分档（`737-744`，与写入路径 `review_document:1035-1043` 逐字一致）**：有 error ⇒ `rejected`；无 error 但 `dep_check.checked is False` ⇒ `unverified`；有 warning ⇒ `accepted_with_warnings`；否则 `accepted`。

**发现落库**（`review_document:941-1106`）：三段式——① 落 `review_findings`（去重键 `_dedup_key = (kind,target,message)`，`899-901`；`round_no` 从库里已有发现的最大轮次往后推，`949-955`）；② 把"G 标了 fixed 但重跑仍复现"的发现重新打开（`1008-1032`）；③ 单独一笔事务改 `documents.status`（`_set_doc_status:839-870`，**只改 `status`**，连 `updated_at` 都不碰）。四种状态字段词表 `schema.FINDING_STATUSES = ('open','fixed','wontfix','disputed')`，落库时固定写 `status="open"`、`resolution_note=""`（`997-998`）。每条发现还按 `P-9` 四键补齐 `axis`/`line`/`line_unavailable_reason`/`verbatim_quote`/`maths`/`suggestion`（`_finding:246-284`；表在 `146-171`）。

**`verify_fixes`**（`1177-1375`）：重跑 `scan_document`，拿当前 findings 的 dedup key 集合与上一轮比：key 仍在 ⇒ `still_open`（`source="prev_round"`，附当前 evidence）；key 不在 ⇒ `resolved`（`1233-1238`）；当前新出现的 ⇒ `still_open` 且 `source="new_issue"`（`1240-1255`）。落状态：resolved ⇒ `fixed`；prev_round 且 G 曾标 fixed 的 ⇒ 回到 `open`（`1257-1285`）。判定用"当前仍存在的 error"：全无 ⇒ `accepted`；有 blocking 且到 `max_review_rounds` ⇒ `unresolved_review`（并把未解决项列进 `unresolved_findings`）；有 blocking 未到上限 ⇒ `revise_again`；只剩 warning ⇒ `accepted`（`1288-1300`）。另外 `accepted` 之前要过签名关（`1319-1330`，见 1.5）。

### 1.5 签名链

实现全在 `signatures.py`（台账文件 `DOC-SIGNATURES.jsonl` + 每条一份证据快照 `doc-signatures/<doc>-<hash前16>-<序号>.json`，`111-114`、`350-359`）。

- **谁能签**：`SIGNER_NAME = "agent-H"`（`117`）。写侧 `append_signature` 硬拒非 H 的 `name`（`333-335`，"禁自批"）；读侧 `verify_signature` 还要求 `name != doc.created_by`（`216-218`）。
- **签什么**：一条记录钉 `doc_id + content_sha256 + claims_hash + name + at + scope + verdict + instance_id + inputs{doc_sha256} + basis{codes_checked/finding_ids/rounds/dimensions}`，外加两个由 `append_signature` 自己产出的证据锚 `evidence_path`/`evidence_sha256`（`142-150`、`361-363`）。判定档只接受 `ACCEPTING_VERDICTS = ("accepted","accepted_with_warnings")`（`122`、`336-338`）。
- **谁签发**：`review_tools._sign_accepted_revision`（`1112-1174`）是唯一入口——只在"状态真的写成 `accepted`"时签（`1132-1133`）。`verify_fixes` 明确**不签**：它只查"台账里有没有一条签名钉在当前这一版内容上"（`signed_revision`），没有就把目标状态退成 `in_review` 并在 reason 里点名要重新 `review`（`1319-1347`）。
- **`stale_signature` 的判据**：`verify_signature` 逐条判五件事——谁签的、判定是不是接受档、`record.content_sha256` 是否等于重算的当前内容哈希、`inputs.doc_sha256` 是否也等于、证据快照是否在工作区内且 sha 对得上（`209-236`）。`signature_problems` 的判据是"**至少一条**签名完全成立"，不是"第一条成立"（`239-280`）。
- **`SIGNABLE_STATUS` 只认 `accepted`**（`131`）：`signature_problems` 对 `status != "accepted"` 的稿件**一律返回空**（`257-258`），`signed`/`formal` 因此对 `revised`/`draft`/`unresolved_review` 都是"没问题"。`verify.py` 直接读这个常量来算"签名这件事查了几行"。
- 写侧闸门还包括必填字段齐（`REQUIRED_SIGNATURE_FIELDS`，`143-146`；`evidence_*` 由本函数补，调用方不能自己填，`148-150`、`329-332`）。

### 1.6 收工门：七格

`DEFAULT_CHECKS`（`closing.py:49-52`）= `anchor / contradictions / load_bearing / report_shape / user_pending / substance / acceptance`。入口 `check_closing`（`2044-2078`），逐格一句话：

| 格 | 判什么 | 位置 |
|---|---|---|
| `anchor` | 复用 `renderanchor.check_package`：`consistent` ⇒ pass；`drifted` ⇒ fail（带漂移行）；`unknown` ⇒ unknown（不是一致）。没有论文包实物的项目判"不适用=pass"（判据是 `out/paper` 下有正文/锚/编译产物之一，`_has_paper_package:1579-1599`） | `_check_anchor:1602-1668` |
| `contradictions` | 五类未裁决矛盾各自一个 code：读错文献（`literature.matched=mismatch` 且已消化）、来源有争议/被证否（依赖 `disputed/refuted`、命题 `disputed`）、自家证明压在不可用命题上、污染面（被证否命题的 `derived_from` 传递闭包仍压着结论，`pollution_set:1671-1699`）、稿件 `unresolved_review`；任一命中即 fail | `_check_contradictions:1702-1816` |
| `load_bearing` | 正文里 `evidence_kind="proof"` 的断言必须有 T3 背书（被引 `experiments` 行 `method=formal` + `evidence_kind=proof` + `verifier_output` 非空，`_has_t3:1819-1823`，或有一条 `closed` 依赖指向它）；另有"命题台账里 active+proof+有下游"计数与降档计数。缺 T3 的逐条列出 ⇒ fail | `_check_load_bearing:1826-1899` |
| `report_shape` | 九节齐全（`REPORT_SECTIONS:1415-1425`）+ 分栏标记「我们补的」「原文的」（`SPLIT_MARKERS:1431`） | `_check_report_shape:1902-1942` |
| `user_pending` | 还有问题在等用户回答 ⇒ fail（必须停在等待用户）；`sid == NO_SESSION` ⇒ unknown | `_check_user_pending:1996-2039` |
| `substance` | 五张表（`documents/relations/experiments/review_findings/statements`，`SUBSTANCE_TABLES:60-61`）至少一张非空；全 0 ⇒ fail；有表读不到 ⇒ unknown | `_check_substance:1945-1993` |
| `acceptance` | 见 1.7 | `_check_acceptance:1145-1401` |

十项官能的"机械那一半"在 `faculty_checks.py`，由 `deliver.py:167-190` 消费（`cli.py:1646` 调 `deliver`）；收工门七格**不读**它——两者是两套交付闸门（`deliver` 的词表是 `pass/needs_work/unknown`）。

### 1.7 收工门：`acceptance` 那一格

验收表落点 `out/paper/ACCEPTANCE-CHECKS.json`（`ACCEPTANCE_CHECKS_NAME:76`）。读法（`_check_acceptance:1145-1401`）：

- 没给 `project_dir` ⇒ unknown；文件不在 ⇒ 用 `research_chain_gaps(store, ())` 判：这个项目有 `research_questions` 行（"研究型"）⇒ fail 并逐条列出缺的环节；不是研究型 ⇒ `pass` + 读数里写"没有这一栏"（`1152-1186`）。
- 顶层可以是数组或 `{"checks": [...]}`（`1187-1196`），读不懂 ⇒ `acceptance_unreadable` + 整格 unknown。
- **逐行现算**：一行一个受控 `kind`（`LEG_CHECK_KINDS`，`80-244`，实测 **30 档**），`_leg_reading(store, kind, project_root)`（`470-1126`，657 行、62 个 `if`）现算 `(条数, 明细)`；`kind` 不认识 ⇒ **整张表判没查成**（`1246-1253`）；某一行算不出来 ⇒ 整格 unknown（`1254-1265`）。
- **阈值语义**（`1213-1278`）：`min` 缺省（或写 0，因为 `int(row.get("min") or 0)` 的 0 是假值）⇒ 用该档自己给的 `implicit_min`；该档没给 ⇒ 缺省 1；只声明上限的档（`unfinished_request_rows`）缺省下限取 0。`max` 缺省取该档给的 `implicit_max`。判定是 `got >= min and (max is None or got <= max)`。实测有 `implicit_min` 的档会用台账自己算出的数当阈值，例如 `retrieval_ok_rows` 的阈值 = `research_questions` 行数、`citation_records_vs_bibitems` 的阈值 = 主稿里 `\bibitem` 条数、`document_claim_rows` 的阈值 = 研究问题数。
- **`na` 的语义**（`1225-1245`）：`"na": true` 的行**不算通过也不算失败**，直接 `ok=True` 并跳过 `_leg_reading`；两条守卫是"必须写 `note` 理由（否则整格 unknown）"与"不许整张表都是 `na`（`acceptance_all_na` ⇒ fail）"（`1291-1298`）。
- **覆盖面八环**（`research_chain_gaps:322-364` + `RESEARCH_CHAIN_GROUPS:272-319`，实测 8 环 20 个成员档）：只有项目有 `research_questions` 行时才说话；每个环节"至少有一行的 `kind` ∈ 该环节成员，或该成员被标了 `na`"；缺的环节逐条列进 `unmet`。
- **四条自动报告分支**（某一档**没写进验收表**时，门替它现算并报出来）：`reviewed_current_rows`（现行版没被签名钉住的稿件，`1319-1337`）、`document_body_rows`（有 `sections` 却每节 `body` 都空 = 骨架稿，`1340-1356`）、`claim_evidence_fit_rows`（断言与引文对不上，`1360-1374`，判据 `citation_fit:395-467`）、`manuscript_rows`（`refs` 全空且全是框架派生的模板行，`1378-1392`）。四条都是"`if kind not in 表里已有的 kind`"才跑。
- 结论：`unmet` 非空 ⇒ `acceptance=fail`（`acceptance_unmet`/blocker，逐条给读数）；否则 `pass`（`1393-1401`）。

并存的另一套验收在 `reviewaccept.py`（与 `acceptance` 那一格不是同一件事）：六条内容级判据各自三态（`CRITERIA:27-35`：报告九节每节有读数 / 定理台账每条有假设与出处（按 `external_lit` 要页码、`own_result` 要 `doc_id` 或 `line_range`）/ 三态分支落盘 / 成本上限 / 每跳可读输入 / 附件诚实），另加五种"容易拿到但证明不了内容"的辅助读数单独分栏、一个都不参与 `passed`（`AUXILIARY_SIGNALS:46-52`、`ReviewAcceptance.passed:72-75`）；成本那一档取"账本合计与会话事件花销的最大值"，并单列"账本没跟上"（`_c_cost:290-351`、`_session_spend_usd:260-287`）；附件诚实那一条含"报告点名的台账行是否真的存在"（`_dangling_report_refs:382-420`）。

### 1.8 `can_close` 与退出码

- `can_close = all(status == "pass") and not blockers`（`1505-1507`）。`unknown` 与 `fail` 都不算通过。
- 退出码三态（`tri_state_exit_code:2081-2087`）：`can_close` ⇒ 0；否则"有 unknown 且没有 fail" ⇒ 2（没查成）；其余 ⇒ 1（被拦住）。
- 两个入口：CLI `agentflow closing`（`cli.py:2090-2098`）与 M 的工具 `conductor.closing`（`tools/conductor_tools.py:986-997`，返回 `can_close/status/findings/readings` 与 `blocked`）。

### 1.9 `statusreport` 收集的读数

`statusreport.collect`（`statusreport.py:63-164`，唯一写入是落 `out/review/STATUS-<ts>.{md,json}`，`363-372`）：

- 九张表逐张计数 + 最近 8 行摘要（`REPORT_TABLES:35-38` = `tasks/documents/experiments/conjectures/attack_plans/review_findings/literature/search_requests/statements`）；`since` 按 `created_at/at/started_at` 前缀过滤；表读不到 ⇒ 空列表（`_rows:47-52`，注释写明"读不到与是 0 行必须分得开"，但返回值里没有区分位——见 5）。
- 交接账本：行数、坏行前 3 条、`model_authored`（`note` 含「模型填的 notify」）/`derived`（`note` 含「派生」）、最近 8 行（`86-100`）。
- 五元位现状：逐 `statements` 行现算 `evidencebits.bits_from_row`，按 `grade` 计档，并数 `bit_problems` 非空的行（`103-111`）。
- 在飞与卡点：`running_tasks`、活进程登记 `live_pids`、在跑的循环、停机开关、最近停机历史、被拒动作按理由分布、待答问题数（读不到记 -1）（`113-155`）。
- 攻坚轮次产物分布与"没有产物的轮次"（`_attack_rounds:167-192`）；集体插话发出/被读/是否改变做法（`_interjections:195-221`）。
- `next_steps` 是从读数派生的（不是模型写的，`250-287`）。

### 1.10 交接手稿账本

`manuscripts.write`（`manuscripts.py:288-347`）：发件人/收件人必须是八个角色 + `M`（收件人另有 `ALL`，`valid_recipient:80-87`）；`summary` 与 `body` 非空；写前逐条核 `refs`——四位手稿编号必须盘上存在，或 `前缀:编号`（`stmt/exp/lit/rel`，`OBJECT_REFS:231-233`）必须在对应台账里存在（`ref_problem:236-270`），任一不成立整笔拒（`318-322`）。编号由 `next_id` 在文件锁内分配（`325-328`），一行一份追加写。

一行的必填字段 `REQUIRED_FIELDS = ("to","summary","body")`（`63`；`missing_fields:417-419`）。

**框架自动派生的行有两条来源**（`note` 里逐字写明来源）：① 动作驱动的一趟结束时 `conductor._write_completion_manuscript`（`conductor.py:1225-1276`，`note="留痕来源：框架据动作结果派生（动作驱动的一趟没有 final 可填）"`，调用 `MS.write(...)` 时**不传 `refs`**）；② 模型派活那一句没填 `notify` 时 `agent_loop._derived_dispatch_notify`（`agent_loop.py:2005-2027`，`"refs": []`）。模型自己填的 `notify` 那一行走 `_dispatch_notify`（`agent_loop.py:1997-2003`），它的 `refs` 会逐条过 `MS.ref_problem`。

收工门 `manuscript_rows` 只数"模型自己写的"（`note` 里不含「框架据」）那些（`closing.py:613-644`），框架派生的另计 `derived_rows`。

---

## 2. 关键文件与函数表

| `file:line` | 一句话职责 |
|---|---|
| `tools/doc_tools.py:189-241` `scan_claim` | 单条断言的机械检查适配层（转发 `claimanatomy.validate_claim`，把 code 翻成 `FINDING_KINDS`） |
| `tools/doc_tools.py:268-303` `_FINDING_KIND_OF_CODE` / `_finding_kind_of` | 判据层 code → 落库层 kind 的唯一映射；未登记 code 显式抛 |
| `tools/doc_tools.py:356-429` `check_citations` | 引用存在性四表核对（三态 `checked`） |
| `tools/doc_tools.py:432-474` `classify_proof_location` | `proof_location` 形态分类（与 `gates.gate_g3` 共用） |
| `tools/doc_tools.py:477-678` `check_proofs` | proof 级断言的证据锚四条判据 |
| `tools/doc_tools.py:684-810` `compose_claim` | 构造一条合规断言的唯一入口 |
| `tools/doc_tools.py:816-1106` `render_markdown` | 人读 markdown 渲染（四张表 + 附录 A） |
| `tools/doc_tools.py:1112-1183` `normalize_claims` | 分配 `claim-1…N`、别名改写、逐条落库前检查 |
| `tools/doc_tools.py:1186-1349` `build_document` | 落一行 `documents` + 渲染（三道闸 + 覆盖守卫） |
| `tools/doc_tools.py:1352-1440` `register_dependency` | 登记依赖；`closed` 用真实数据核来源 |
| `tools/doc_tools.py:1852-1922` `_paper_render/_paper_compile/_paper_anchor/_paper_build` | 论文包四条工具的实现（转发 `paperbuild`） |
| `agent_g/revise.py:10-177` `revise` | 按 H 的发现修订：替换/追加断言、三闸、状态机、重渲染 |
| `agent_g/paper_package.py:37-98` `paper_package` | 渲染 → 编译 → 核锚一次做完 |
| `agent_g/refresh_markdown.py:10-30` | 按库里的数据重画 markdown（补依赖表） |
| `tools/review_tools.py:307-813` `scan_document` | H 的全量机械审校（纯函数，507 行） |
| `tools/review_tools.py:907-1106` `review_document` | 落发现 + 重开谎报 + 改状态 + 判 accepted 即签 |
| `tools/review_tools.py:1112-1174` `_sign_accepted_revision` | 唯一签发入口（只在状态真为 accepted 时） |
| `tools/review_tools.py:1177-1375` `verify_fixes` | 复审：resolved/still_open/新问题 + 终止性 + 签名关 |
| `tools/review_tools.py:1426-1525` `review_report` | G1–G15 审校报告落盘 |
| `agent_h/review.py:10-40` / `verify_fixes.py:10-44` / `review_report.py:9-74` | H 的三个动作转发层 |
| `signatures.py:69-101` `content_sha256_of/claims_hash_of/ref_hash_of/doc_ref` | 内容哈希与内部引用（唯一实现） |
| `signatures.py:209-236` `verify_signature` | 一条签名的五条判据 → 判据码 |
| `signatures.py:239-286` `signature_problems/signed` | "这份稿件的签名有没有问题"（只对 `accepted` 说话） |
| `signatures.py:296-319` `signed_revision` | "现行这一版内容有没有签名钉住" |
| `signatures.py:322-368` `append_signature` | 落证据快照 + 追加台账一行（含链节 `prev_hash`） |
| `renderanchor.py:90-112` `build_anchor` | 算锚（源表 + 渲染出的源文件） |
| `renderanchor.py:115-142` `build_receipt` | 算编译回执（tex/pdf 哈希、页数、退出码） |
| `renderanchor.py:229-313` `check_package` | 三维核锚（tables/files/receipt），总体取最坏 |
| `closing.py:1145-1401` `_check_acceptance` | 验收表逐行现算 + `na` + 覆盖面 + 四条自动分支 |
| `closing.py:470-1126` `_leg_reading` | 30 档受控档位的现算实现（657 行） |
| `closing.py:322-364` `research_chain_gaps` | 研究链八环覆盖面 |
| `closing.py:395-467` `citation_fit` | 断言与引文/实验的确定性比对（数字/实词交集） |
| `closing.py:1602-1668` `_check_anchor` | 锚那一格 |
| `closing.py:1702-1816` `_check_contradictions` | 矛盾五因 + 污染面 |
| `closing.py:1826-1899` `_check_load_bearing` | 承重结论的 T3 判据 |
| `closing.py:1902-1942` `_check_report_shape` | 报告九节 + 分栏 |
| `closing.py:1945-1993` `_check_substance` | 实质产出 |
| `closing.py:1996-2039` `_check_user_pending` | 待答问题 |
| `closing.py:2044-2087` `check_closing/tri_state_exit_code` | 入口与三态退出码 |
| `faculty_checks.py:127-151` `overview_findings` | 高观点的机械半：引用落地（id 不在册）+ 声称的概念对在图里有没有边/路径 |
| `faculty_checks.py:154-187` `conjecture_hygiene` | 敢创新的机械半：猜想卫生四条（无可否证形式 / 支持它的实验不存在 / 僵尸猜想 / 坏提升） |
| `faculty_checks.py:190-215` `style_findings` | 有品味的机械半：一级标题 / 占位符 / 空段 / 免责声明逐字一致 |
| `faculty_checks.py:239-262` `progress_findings` | 脑子的机械半：推进（数据面有增量）/ 明说卡点 / 只核对 三档 |
| `faculty_checks.py:280-327` `claim_strength_findings` | 能思辨的机械半：把 `claimanatomy` 的 `overclaim` 结论翻成 faculty 视图（不另判一次） |
| `faculty_checks.py:330-369` `trace_findings` | 溯源机械半：矛盾双方引用的材料是否存在 + 文内有没有点名 |
| `reviewaccept.py:530-555` `check_review` | 审稿场景六条内容级判据 + 五种辅助读数（辅助不参与 passed） |
| `judges.py:325-370` `semantic_judge_for` | 判据词表 → 审校接缝词表的单向映射 |
| `judges.py:184-212` `NEGATIVE_CONTROLS` | 每条语义判据的负控样本（准入条件） |
| `evidencebits.py:108-128` `bits_from_row` | 五元位唯一读入口（等级现算） |
| `evidencebits.py:186-203` `derive_grade` | 五元位 → 等级（任何自报等级都不认） |
| `manuscripts.py:288-347` `write` | 追加一份交接手稿（refs 逐条核） |
| `manuscripts.py:236-270` `ref_problem` | 一条引用能不能立住 |
| `manuscripts.py:417-419` `missing_fields` | 一行缺哪个必填字段 |
| `statusreport.py:63-164` `collect` | 旁路观测收集（只读） |
| `claimanatomy.py:1076-1523` `validate_claim` | 断言的字段级 + 交叉轴判据唯一来源（448 行） |
| `claimanatomy.py:1695-1716` `revision_hash` | 报告钉住的被审版本哈希 |
| `claimanatomy.py:1732-1756` `main_body_claims/retracted_claims` | 渲染层降级门（作废/移入 open） |

---

## 3. 可疑的逻辑 bug

### B1（最要紧）语义判据产生的发现，会被一次"跑不了语义判据"的复审判成 fixed

- 【现象】H 的 `review` 用装了语义判据的缝落了一条 warning 级 `overclaim`（"结论的强度超出引文能支撑的范围"）；随后 `verify_fixes` 重跑检查时**没有语义判据**，于是这条发现的 dedup key 不在"当前 findings"里 ⇒ 被判 `resolved ⇒ fixed` 并写回 `status='fixed'`。整条链上没有任何地方报"语义这一维这一轮没查"。
- 【证据】`tools/review_tools.py:1215` `scan = scan_document(doc, dependencies=deps)`（无 `semantic_judge` 参数）；`1233-1238`（key 不在 `current` 即 `resolved`）；`1739` `_WRITE_TOOL_FUNCTIONS` 里 `verify_fixes` 的注入名是 `('_not_wired','store','actor')`，结构上拿不到 `semantic_judge`；返回字典 `1359-1375` 里既没有 `semantic_check` 也没有 `coverage`（`review_document` 是有的，`1094-1098`）。探针 `gh_probe_1.py::C_semantic_finding_resolved` 实跑输出：`C1 review：verdict = accepted_with_warnings | 新发现 = [('overclaim','warning',...)] | semantic_check.checked = True`；`C2 verify_fixes：verdict = accepted | resolved = [('overclaim','warning')] | still_open = []`；`C3 返回里有 semantic_check 吗 = False`；`C4 复审后库里 finding 状态 = [('overclaim','fixed')]`。
- 【影响面】语义维（"措辞干净但结论强于引文"）是本框架唯一一条非机械的可信度判据；它在复审这一格上**没有复现能力**，因此凡是 LLM 报出的过度声称都必然在下一轮被"修好"——H 的发现被系统性地清零，而读数上看起来是"G 改好了"。
- 【是否复现】复现（探针 C，三步即得）。

### B2 一行 `"na": true` + 任意非空 `note` 可以关掉一整档判据与对应的自动分支（"写一行就绕过"）

- 【现象】同一份骨架稿：不写 `document_body_rows` 那一行 ⇒ `acceptance=fail`（自动分支报"交付的稿件只有骨架"）；写了 `{"kind":"document_body_rows","na":true,"note":"清单型交付"}` ⇒ `acceptance=pass`。`na` 行既不现算也不判阈值，且自动分支的前提是"这一档没写进表里"。
- 【证据】`closing.py:1225-1245`（`na` ⇒ `ok=True`、`continue`，只校验 `note` 非空）、`1340-1356`（`if "document_body_rows" not in {…}`）、`1360-1374`、`1378-1392`、`1319-1337`。探针 `gh_probe_1.py::A_na_bypass` 实跑：`A1 无 document_body_rows 行 → acceptance = fail`；`A2 写了 na 行 → acceptance = pass | findings = []`；`A3 写了这一行但不标 na → acceptance = fail`。真机里 `na` 已被实际使用：`projects/p7b-open-questions/out/paper/ACCEPTANCE-CHECKS.json` 有 `{"id":"B1","kind":"numeric_experiment_rows","min":0,"na":true,…}` 与 `{"id":"D2","kind":"supported_claims","min":0,"na":true,…}`。
- 【影响面】四条自动分支覆盖的正是"骨架稿 / 改完没复核 / 引文对不上 / 账本被模板灌满"这四类真机翻过车的问题；写表的人（M）手里有这条出口，且 `note` 的内容没有任何判据（写"。"也能过，见探针 B2 里 `note='。'` 的那一行只在"整表全 na"时才被拦）。绕过成本是一行 JSON。
- 【是否复现】复现（探针 A；真机侧 p7b 已在用该形态）。

### B3 一个 `na` 顶掉整个研究链环节；`na` 的理由不受任何判据

- 【现象】`research_chain_gaps` 判"环节被覆盖"的条件是 `hit or marked`——只要该环节**任一**成员档被标 `na`，整环就算"被如实标注过"。`算或造` 那一环有 5 个成员档（`numeric_experiment_rows / search_frontier_rows / enumeration_optimization_rows / reviewed_proof_rows / counterexample_or_proof_rows`），标一个即可。
- 【证据】`closing.py:342-349`；`RESEARCH_CHAIN_GROUPS:272-319`（8 环 20 档，实测）。探针 `gh_probe_1.py::B_na_covers_group`：`B1 只有一行 numeric_experiment_rows(na) → '算或造' 组 hit=['numeric_experiment_rows'] marked=[…] | 该组仍 missing = []`；`B0 空验收表 → missing 环节数 = 8`。
- 【影响面】D49 设计的"这一档对项目天然不适用"出口，实际形态是"整环可以只靠一行 `na` 通过"，且理由不做机械判定（对比："min/阈值"那一半至少还留了读数）。
- 【是否复现】复现（探针 B1）。

### B4 `document_body_rows` 对"没有 sections 的稿子"完全不说话；而 `sections` 是可省的

- 【现象】`document_body_rows` 只把"有 `sections` 的行"纳入统计：没有 `sections` 的行直接 `continue`。于是"只交骨架"还有第二种形态——**干脆不交 sections**：`got=0`、`implicit_min=0`（阈值只数有 sections 的行）、`empty_section_docs=[]`，自动分支也不报。`build_document` 的 `sections` 不是必填，`body` 缺省就是 `""`。
- 【证据】`closing.py:672-674`（`if not secs: continue`）、`686`（`implicit_min = with_body + empty_sections`）、`1340-1356`；`doc_tools.py:1229-1233`、`1639`、`1648`（`required=["kind","title","claims"]`）。探针 `gh_probe_2.py::E_no_sections`：`got = 0 | implicit_min = 0 | 按实现判出的 want_min = 0 → ok = True`、`该档读数里『骨架稿』一栏 = []`、`验收表只写 document_rows → acceptance = pass | findings = []`。对照真机：`p5-review-t17` 与 `p8g` 的骨架稿是"有 sections、body 全空"的形态，所以被自动分支抓到（`p8g` 实跑 `closing` 得 `acceptance=fail`、`acceptance_unmet`，明细逐字列出三节空 body）。
- 【影响面】"骨架不是手稿"这条判据（D63）只封了一半：带空 body 的 sections 会被抓，不带 sections 的同类稿件从这一档里静默消失。
- 【是否复现】复现（探针 E）。

### B5 验收行里的 `min` 可以低于该档自己算出来的阈值（显式值优先）

- 【现象】同一份台账：不写 `min` 时 `retrieval_ok_rows` 的生效阈值是 3（= `research_questions` 行数），该行判 `ok=False`；写 `"min": 1` 后生效阈值变成 1，同一读数下该行判 `ok=True`。也就是说"阈值随台账自己长"这一设计可以被表里一个数字压回去（唯一不能压的是 0，因为 `int(row.get("min") or 0)` 把 0 读成"没给"）。
- 【证据】`closing.py:1213`（`want_min = int(row.get("min") or 0)`）、`1266-1278`（`if not want_min:` 才用 `implicit_min`；`want_max` 同理）。探针 `gh_probe_2.py::F_min_override`：`retrieval_ok_rows: got = 1 | 该档自己算的 implicit_min = 3`；`行里 min=None → 生效阈值 = [3] | 这一行 ok = [False]`；`行里 min=1 → 生效阈值 = [1] | 这一行 ok = [True] | 该档自算 implicit_min = [3]`（该次整格仍 fail 是因为同一项目还缺其它环节）。
- 【影响面】所有"阈值由台账算出来"的档（`retrieval_ok_rows`、`document_claim_rows`、`citation_records_vs_bibitems`、`reviewed_current_rows`）都可以被写表的人用一个更小的 `min` 降档；读数里 `got` 与 `detail.implicit_min` 仍在，所以事后可比对，但门本身不再拦。
- 【是否复现】复现（探针 F）。

### B6 签名判据只对 `accepted` 生效，`revised` 完全够不着

- 【现象】`signature_problems` 对非 `accepted` 状态一律返回空列表。实测四种状态：`accepted` → 报 `accepted_without_signature`；`revised` / `unresolved_review` / `draft` → 都返回 `[]`。真机 `p8e`：稿件 `status=revised`、现行内容 `68bfc4c7…`，台账里唯一一条签名钉的是 `e7346eb7…`（改稿前那一版）——"改稿之后旧审批不许沿用"这件事在签名判据这一层**看不见**。
- 【证据】`signatures.py:131`（`SIGNABLE_STATUS = "accepted"`）、`257-258`（非该状态直接返回 `[]`）；探针 `gh_probe_1.py::D_signature_revised` 四状态输出。真机：`p8e` 的 `DOC-SIGNATURES.jsonl` 逐字是 `content_sha256 = e7346eb775b4…`，`documents/0000` 现行 `content_sha256 = 68bfc4c7a397…`；`closing._leg_reading('reviewed_current_rows')` 在 `p8e` 上得 `got=0, claimed=1, stale_signoffs=[{'doc_id':'0000','current':'68bfc4c7a397','signed':['e7346eb775b4'],'status':'revised','revision':2}]`。
- 【影响面】"接受 = 有一次针对这一版的审+签"的唯一机器判据落在 `closing` 的 `reviewed_current_rows` 那一档上；而那一档既可以被一行 `na` 关掉（B2），也可以不被写进验收表（此时靠自动分支兜）。一旦兜底被关掉，"没复核的现行版"在签名链与验收表两处都没有判据。
- 【是否复现】复现（探针 D + p8e 真机读数）。

### B7 `report_shape` 的"附件三件套"被读出来但从不参与判定

- 【现象】`_check_report_shape` 算了 `has_attach = [f for f in ATTACHMENT_FIELDS if f in text]` 并写进读数，但 `problems` 只由"九节缺没缺"与"分栏标记缺没缺"产生。实测：一份只有"九节名字清单 + 两个分栏词"的报告（没有 `origin=own_result`、没有 `依据`、没有 `sha`）判 `pass`，读数里 `attachment_fields: []`。
- 【证据】`closing.py:1428`（`ATTACHMENT_FIELDS = ("origin=own_result","依据","sha")`）、`1923`、`1927`、`1929-1942`；`grep has_attach` 全仓只有 `1923`/`1927` 两处。探针 `gh_probe_3.py` 与后续一行命令：九节名字清单（无节标题、无附件）→ `status = fail` 但 `findings=['report_incomplete']`、`missing_sections: []`、`attachment_fields: []`；补上两个分栏词后 → `status = pass | findings = []`、`attachment_fields: []`。同一处还显示"九节齐全"的判据是**宽松**的：只要节名出现在正文任意位置（`f"{num}、" not in text and name not in text`，`1920-1921`），一份清单式文本就算"九节齐全"（对照：`reviewaccept._c_report` 用的是严格标题正则 `^#{2,3}\s*([一二三四五六七八九])、`，`reviewaccept.py:54`、`113-135`——同一件事两份判据、强度不同）。
- 【影响面】§16 P3 报告行逐字要求的"附件诚实"（我们补的/依据读数/版本 sha）在收工门上没有读数——`reviewaccept._c_attachment` 只判"来源造假 / 过度声称 / 引用悬空"三条，也不判三件套是否出现。
- 【是否复现】复现（探针 3 + 一行命令）。

### B8 `citation_records_vs_bibitems` 的阈值取自主稿本身；`manuscript_edited` 对任何一个字节都算"改过"

- 【现象】同一份台账 3 条比对记录：`source/main.tex` 有 3 条 `\bibitem` ⇒ `got=3, implicit_min=3`；把 `out/paper/main.tex` 换成只剩 1 条 `\bibitem` ⇒ `got=3, implicit_min=1, counted_from=out/paper/main.tex`。也就是说"每条 `\bibitem` 一条记录"这条逐条判据的分母是**被测物自己**——主稿里删掉引用，要求跟着降低。`manuscript_edited` 只比 `out/paper/main.tex` 与 `source/main.tex` 的 sha256：多一个换行即 `got=1, edited=True`（判"改过"），且这一格不检查 `source/` 自身有没有被改动。
- 【证据】`closing.py:575-596`（`src = draft if draft.is_file() else base`；`"implicit_min": bibitems`、`counted_from`）、`549-568`；探针 `gh_probe_2.py::I_bibitem_threshold_from_draft` 与 `::J_manuscript_edited_any_byte` 的输出逐行如上。代码里读 `source/` 的只有 `closing.py:554-566`（`manuscript_edited`）与 `575-577`（`citation_records_vs_bibitems`）两处（`593` 只是把来源写进读数）；`agent_prompts.py:444` 逐字要求"基线 `source/` 逐字节未改"，但没有任何判据读这一条。
- 【影响面】`manuscript_edited` 的判据是"不同"而不是"实质改了"（`P2` 那一档最小阈值 1，一个换行就满足）；同时"只读基线不许改"这句话在收工门上没有落点。
- 【是否复现】复现（探针 I、J）。

### B9 `document_rows` 的去重键在 `content_sha256` 为空时退化成行号，同一份内容多行照数

- 【现象】`document_rows` 按 `content_sha256` 去重；该字段为空时键退化成 `id:<doc_id>`，于是两行逐字相同的内容被数成 2 份。真机 `p6q` 的 4 行 `documents` 都有 sha（`8ca0…/7937…/3d30…/aaff…`），所以去重路径今天是有效的；空 sha 的行（历史行、非 `build_document` 写入口写的行）会绕过它。
- 【证据】`closing.py:728-739`（`key = str(d.get("content_sha256") or "") or f"id:{d.get('doc_id')}"`）；探针 `gh_probe_2.py::H_dedupe_without_sha`：`两行内容逐字相同且 sha 为空 → got = 2 | unique_documents = 2 | duplicate_rows = []`（对照：`build_document` 写侧一定补 sha，`doc_tools.py:1333-1335`）。
- 【影响面】D65 要修的"同一份内容重复登记被读成四份稿子"在 sha 缺失的那一类行上仍然成立；读数里 `duplicate_rows` 为空，读者看不出"这两行其实同容"。
- 【是否复现】复现（探针 H）。

### B10 验收表本身进了渲染锚的 `files`，锚与验收表互相咬

- 【现象】`package_files` 收包目录下所有非编译产物文件，而验收表 `ACCEPTANCE-CHECKS.json` 的定义落点就是 `out/paper/`。真机 `p5-review-t17` 的 `RENDER-ANCHOR.json` 的 `files` 逐字是 `['ACCEPTANCE-CHECKS.json','ACCEPTANCE.md','main.tex']`。顺序上它现在是"先写验收表（20:21）→ 后渲染（20:38）→ 写锚（20:38:24）"，所以锚一致；若改动验收表发生在最后一次渲染之后，`files` 那一维会报"盘上有、锚里没有" ⇒ 锚 `drifted`。
- 【证据】`renderanchor.py:74-87`、`276-289`；`closing.py:76`（`ACCEPTANCE_CHECKS_NAME = "out/paper/ACCEPTANCE-CHECKS.json"`）；真机文件与 mtime：`p5-review-t17/out/paper/ACCEPTANCE-CHECKS.json` 20:21:01、`main.tex` 20:38:19、锚 `generated_at=2026-10-05T20:38:24+08:00`；`RA.check_package` 现跑 `verdict=consistent`。
- 【影响面】`anchor` 与 `acceptance` 两格互相咬：改验收表（交付时最常见的动作之一）会让锚那一格红；反过来，为了让锚绿，验收表的改动时机被渲染时刻绑住。这条耦合没有写在 `closing` 或 `renderanchor` 的注释里。
- 【是否复现】静态可判（真机锚文件逐字列出了验收表）；未实测"改表后锚变 drifted"的完整往返（见第 5 节）。

### B11 非研究型项目没有验收表时 `acceptance` 直接 pass

- 【现象】`acceptance` 文件不存在时，只有"有 `research_questions` 行"的项目判 fail；否则判 `pass` 并在读数里写"这个项目没有 ACCEPTANCE-CHECKS.json"。实测非研究型临时工作区：`research_questions = 0 → acceptance = pass | findings = []`。
- 【证据】`closing.py:1160-1186`；探针 `gh_probe_2.py::G_no_checks_file_non_research`。真机 `p5-review-t17`（F 类审阅任务）虽然**有** 5 行验收表，但同一批工作区里 `p6r`/`p7b`/`p8e` 的验收表覆盖也不齐（实跑 `closing` 均 `acceptance=fail`，原因是覆盖面缺环）。
- 【影响面】七格里最贴任务口径的那一格，对"非研究型且不写验收表"的项目是空过；此时只剩 `substance`（五张表任一非空，`closing.py:60-61`、`1982-1992`）在回答"做了没有"，而它按设计不看"任务点名的那份东西在不在"（真机 D59 的成因）。
- 【是否复现】复现（探针 G）。

### B12 `reviewaccept.check_review` 在生产路径上没有调用点

- 【现象】六条内容级判据（报告九节每节有读数 / 定理台账有假设与出处 / 三态分支落盘 / 成本上限 / 每跳可读输入 / 附件诚实）与五种辅助读数的实现都在 `reviewaccept.py`，但全仓调用它的只有 `tests/`（`test_review_acceptance.py`、`test_ledger_charging.py`、`test_intake_actions.py`、`test_sid_scoped_questions.py`、`test_relative_paths_under_workspace.py`）；`cli.py:1380` 只在注释里提它。
- 【证据】`grep 'check_review|reviewaccept'` 全仓 41 处命中，生产代码里只有 `reviewaccept.py:530`（定义自身）与 `closing.py:478`（另一件事：`CL.check_closing(store, checks=("load_bearing",))`）；其余命中都在 `tests/` 与注释里。
- 【影响面】`passed` 这个读数在真机路径上没有任何人读；"验收"这件事在收工门上由 `closing.acceptance` 那一格承担，两套判据（内容级 vs 验收表阈值）并存而只有后者在跑。
- 【是否复现】静态可判（grep 输出）。

### B13 `statements.bits` 没有产出方，`reviewed_proof_rows` 这一档对自家命题恒为 0

- 【现象】`reviewed_proof_rows`（"算或造"环节里非数值方向的那一档）判据是"五元位派生出 `预备定理级`/`正式定理` 且 `origin != external_lit`"。而唯一写 `statements` 行的是 `agent_b/register_statement.py:180-199`，它构造 `S.Statement(...)` 时**不传 `bits`**；`bits_from_row` 对没有 `bits` 栏的行只回传 `origin/source_lit_id/quote_verified`，于是 `own_result` 行的 `proof`/`reviewed` 恒为 False、等级恒为 `conjecture`——即使这行带着 `proof_text`。唯一能到 `pre_theorem` 的是 `external_lit + quote_verified=True`，而那一类被这一档显式排除。
- 【证据】`closing.py:885-914`（`EB.bits_from_row` + `origin != external_lit` 的排除）；`agent_b/register_statement.py:180-199`；`evidencebits.py:64-105`（`bits_of` 的参数里才有 `proof`/`proof_process`/`reviewed`）、`108-128`（fallback 只传三个字段）；`verifications.bit3_payload`（第 3 位那份读数）全仓只有 `tests/test_verifier_role.py` 调它。实测：`bits_from_row({'origin':'own_result','proof_text':'逐步论证……'}) → grade=conjecture, proof=False, reviewed=False`；真机 `_leg_reading('reviewed_proof_rows')` 在 `p7b` 得 `got=0, grades={'pre_theorem':2,'conjecture':2}, cited_skipped=2`（那两条 `pre_theorem` 是 `external_lit`），在 `p8g`/`p6q` 得 `got=0, grades={'conjecture':1}`。
- 【影响面】这一档在"表里写了 `reviewed_proof_rows` 且不标 `na`"时结构性恒红（真机 `specs/m.py:76` 记录的 `p8c` 就是"做对了活、写错了档"）；反过来它逼着写表的人用 `numeric_experiment_rows`/`search_frontier_rows` 或 `na` 顶替（`p7b` 的 `B1` 正是 `na`）。同时"五元位"这一套证据模型在生产数据上没有任何写入者，`statusreport.five_bit` 与 `closing.reviewed_proof_rows` 读到的都是空位。
- 【是否复现】复现（两行命令 + 三个工作区读数）。

### B14 `resolve_under_workspace` 对绝对路径与 `..` 不做包含性检查

- 【现象】`closing`/`reviewaccept` 共用的路径解析口对绝对路径原样返回、对相对路径只做 `(root/path).resolve()`，不判是否仍在工作区内。实测 `resolve_under_workspace(store, 'C:/Windows') → C:\Windows`、`'../../..' → D:\Incubator`。
- 【证据】`closing.py:1530-1553`（`if path.is_absolute(): return str(path)`；相对路径直接 resolve，无 `relative_to`）；对照 `doc_tools.resolve_out_path:154-183`（写侧有包含性拒绝）与 `doc_tools._resolve_project_root:1790-1813`（论文包侧有包含性拒绝）。
- 【影响面】只读影响：`anchor`/`acceptance`/`manuscript_edited`/`citation_records_vs_bibitems`/`report_shape` 这些格子的读数可以被指到工作区之外的文件（例如把 `project_dir` 或 `report_path` 传成绝对路径，读数就来自那里）。写侧不受影响。
- 【是否复现】复现（一行命令）。

---

## 4. 冗长与可读性观察（只描述）

统计口径：`python -B -c` + `ast`；"注释行"= 整行以 `#` 开头的行；"docstring 行"= 各 `Module/Class/Function` docstring 的行数之和（可能与注释行重叠，两者分开列）。

| 文件 | 行数 | 函数数 | 类数 | 注释行(占比) | docstring 行 |
|---|---:|---:|---:|---:|---:|
| `tools/doc_tools.py` | 2092 | 34 | 1 | 201 (9.6%) | 381 |
| `closing.py` | 2087 | 29 | 2 | 298 (14.3%) | 205 |
| `tools/review_tools.py` | 1789 | 21 | 0 | 293 (16.4%) | 254 |
| `claimanatomy.py` | 1756 | 33 | 3 | 153 (8.7%) | 332 |
| `reviewaccept.py` | 555 | 14 | 1 | 22 (4.0%) | 176 |
| `judges.py` | 476 | 14 | 3 | 15 (3.2%) | 64 |
| `manuscripts.py` | 470 | 27 | 0 | 16 (3.4%) | 103 |
| `renderanchor.py` | 427 | 11 | 0 | 32 (7.5%) | 66 |
| `statusreport.py` | 404 | 13 | 0 | 14 (3.5%) | 46 |
| `signatures.py` | 399 | 19 | 0 | 41 (10.3%) | 102 |
| `agent_h/core.py` | 419 | 5 | 2 | 71 (16.9%) | 17 |
| `agent_g/core.py` | 399 | 8 | 2 | 35 (8.8%) | 51 |

各文件最长 5 个函数（行数 / 位置）：

| 文件 | 函数 | 行数 | 起始行 |
|---|---|---:|---:|
| `closing.py` | `_leg_reading` | 657 | 470（内部 62 个 `if`） |
| `closing.py` | `_check_acceptance` | 257 | 1145 |
| `closing.py` | `_check_contradictions` | 115 | 1702 |
| `closing.py` | `_check_load_bearing` | 74 | 1826 |
| `closing.py` | `citation_fit` | 73 | 395 |
| `doc_tools.py` | `render_markdown` | 291 | 816 |
| `doc_tools.py` | `check_proofs` | 202 | 477 |
| `doc_tools.py` | `_register_paper_tools` | 168 | 1925 |
| `doc_tools.py` | `build_document` | 164 | 1186 |
| `doc_tools.py` | `compose_claim` | 127 | 684 |
| `review_tools.py` | `scan_document` | 507 | 307 |
| `review_tools.py` | `review_document` | 200 | 907 |
| `review_tools.py` | `verify_fixes` | 199 | 1177 |
| `review_tools.py` | `review_report` | 100 | 1426 |
| `review_tools.py` | `_sign_accepted_revision` | 63 | 1112 |
| `claimanatomy.py` | `validate_claim` | 448 | 1076 |
| `claimanatomy.py` | `validate_document_claims` | 66 | 1539 |
| `claimanatomy.py` | `status_evidence_consistency` | 53 | 917 |
| `judges.py` | `selftest` | 65 | 406 |
| `signatures.py` | `append_signature` | 47 | 322 |
| `agent_h/core.py` | `_selftest` | 270 | 150 |
| `agent_g/core.py` | `_selftest` | 231 | 169 |

模块级清单的体量：`closing.LEG_CHECK_KINDS` 实测 30 档（`closing.py:80-244`，`_leg_reading` 是一条 30 段 `if` 链）；`RESEARCH_CHAIN_GROUPS` 8 环 20 档（`272-319`）；`REPORT_SECTIONS` 9 条（`1415-1425`）；`reviewaccept.CRITERIA` 6 条（`reviewaccept.py:27-35`）、`AUXILIARY_SIGNALS` 5 条（`46-52`）。

重复实现（`file:line` 对；此处只列"同一件事有两份实现"的形态）：

1. **"报告九节"两份判据、强度不同**：`closing.py:1415-1425` + `1920-1921`（只要求节名/序号出现在任意位置）对 `reviewaccept.py:54` + `113-135`（要求 `^#{2,3}\s*[一二三四五六七八九]、` 的标题形态，且每节要有数字或台账引用）。
2. **"空节/骨架"两份判据**：`closing.py:666-692`（按 `documents.sections[].body` 判）对 `faculty_checks.py:204-206`（按 markdown 正则判空段）。后者只被 `deliver.py:188` 调，收工门不读它。
3. **"handoff 账本怎么分类"两份口径**：`closing.py:617-618`（`"框架据" in note` 即派生，其余算自写）对 `statusreport.py:89-98`（`"模型填的 notify"` / `"派生"` 两个标记，两者都不命中时记 `未注明`）。同一份账本两处给出的"自写/派生"分类规则不同。
4. **"引用编号是否可归属"三份解析**：`doc_tools.check_citations:388-420`（`textutil.citation_ref_parts` + 四张表）对 `faculty_checks.unknown_ids:75-93`（自写正则 `LABELED_ID:34-35` + `PROCESS_ID_TOKEN:30`）对 `manuscripts.ref_problem:248-269`（`前缀:编号` + 直接读 `data/<table>.json`）。
5. **判据层 code → 落库层 kind 两张映射表**：`doc_tools.py:268-285`（`_FINDING_KIND_OF_CODE`）与 `review_tools.py:106-114`（`_H_FINDING_KIND_OF_CA_CODE`）；两张表都登记了 `duplicate_claim_id`，而 `validate_claim` 从不产出这个 code（它只由 `validate_document_claims:1584/1595` 产出），因此这两项在两处入口上都不可达。
6. **不可达的重复代号判据**：`doc_tools.normalize_claims:1164-1165` 的 `if cid in seen: raise`——`cid` 在 1145 行被强制赋成 `claim-{i}`，永远唯一。
7. **`_sign_accepted_revision` 与 `append_signature` 之间没有第二份判据**（前者只做"该不该签"的装配，后者做字段/角色/档位的写入期闸门），这一对是分工而非重复；记录在此以便与上面六条区分。

---

## 5. 未核实与缺口

1. **B10 的完整往返未实测**：只核到真机 `p5-review-t17` 的锚里含 `ACCEPTANCE-CHECKS.json`（静态事实 + mtime 顺序）。"改验收表之后重跑 `closing` 会让 `anchor` 变 `drifted`"没有实跑（需要改工作区文件，超出本任务的只读范围）。
2. **`deliver.py` 那条交付闸门未在运行路径上核对**：它被判据表登记为"十项官能"的交付入口（`tests/test_release_all.py:2231`），调用点是 `cli.py:1646`；它与 `closing` 的关系（谁在真机上先跑、`deliver` 的 `pass/needs_work/unknown` 是否进交付说明）未核实。
3. **`reviewaccept.check_review` 的六条判据在真机工作区上的实际读数未逐个核**：`grep` 显示生产代码无调用点（B12），因此没有"真机它判了什么"的样本；本报告只核到"没有调用点"。
4. **会话侧读数未核**：`user_pending` / `reviewaccept._c_triage` 需要带 `sid` 读会话；本次只用 `sid=''`（`NO_SESSION`）跑，得到的都是 `unknown`（`closing.py:2012-2019`），"真机上这一格给过什么"未核实。
5. **`cost` 那一档未核**：`reviewaccept._c_cost` 的"账本 vs 会话事件取大"需要 `usage_ledger` 与会话事件两份数据；本次未读真机会话的 `llm_call.usd`。
6. **未跑任何测试**：`tests/` 里与本节相关的用例（`test_closing_gate.py`、`test_review_acceptance.py`、`test_agent_h.py`、`test_p910_p9_review_finding_format`）只按名称与注释引用，没有执行；因此"是否有反向用例已经守着这些形态"未核实。
7. **`judges.py` 的语义判据是否在真机上被完整接线未核**：`host.wired_llm_conductor(..., semantic_review=True)` 会按角色造 H 的缝（`host.py:462-469`），而真机运行是否带这个开关（`cli.py:1560` 从 `--semantic-review` 读）没有在 `projects/*/sessions` 里逐趟核对；因此"真机上 `claims_semantically_judged > 0 出现过几次"未核实。
8. **`manuscripts.write` 的 `refs` 在真机上被拒过几次未核**：只核到"框架派生的两条调用路径都不传 refs"与"模型填的 notify 会逐条核"（`agent_loop.py:1997-2000`）；真机会话里 `notify.refs` 的拒绝次数没有统计。
9. **`claimanatomy` 的字段表与 `schema.Document.validate` 的双向一致性未核**：本报告只读了 `claimanatomy` 一侧；`schema.py` 在 FC-27 禁改区，本次未逐条比对两处的硬约束。
10. **`closing._leg_reading` 30 档里本次实跑了 7 档**：`reviewed_current_rows / manuscript_edited / citation_records_vs_bibitems / document_body_rows / document_rows / reviewed_proof_rows / retrieval_ok_rows`（含 `p8e`/`p8g`/`p6q`/`p5-review-t17`/`p7b` 五处真机 + 临时工作区）；其余各档（`quote_verified_rows`、`proof_experiment_rows`、`reviewed_documents`、`claim_evidence_fit_rows`、`unfinished_request_rows`、`enumeration_optimization_rows`、`c_analysis_runs`、`report_files` 等）只按代码读，未逐档造数验证。
