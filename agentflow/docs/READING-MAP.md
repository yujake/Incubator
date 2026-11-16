# 读代码的入口：八层 + "想改什么 ⇒ 读哪几个文件"

> **这份文件回答一个问题：我现在要改的东西，代码在哪、判据在哪。**
>
> 起因（`draft/36` §3）：`src/agentflow` 里文件多、单文件大。**当次读数（观测 2026-11-16，
> 口径：`src/` 下全部 `*.py`（`__pycache__` 不在里面），逐文件 `read_text().splitlines()` 求和）：
> **314 个 `.py`、290454 行**，**75 个文件超过 800 行**（**全仓最大的是 `secretary.py`，16007 行（`agent_loop.py`，14617 行）**；§3 那张表里最大的一行同为 `agent_loop.py` —— 批 R40 把它补进了那张表）。
> 复跑命令（三格一次打全）：
> `python -c "import pathlib;fs=sorted((pathlib.Path('src')).rglob('*.py'));L=[len(p.read_text(encoding='utf-8').splitlines()) for p in fs];print(len(fs), sum(L), sum(1 for n in L if n>800))"`
> **2026-11-16 FC-27 批 apply 之后（`c2cead2b` 落地引起的读数漂移）**：314 个 `.py`、75 个 `>800`
> 都不变；总行数 290412 → **290454**（+42：`agent_prompts.py` +37、`tools/table_tools.py` +5、
> `specs/h.py` +4、`tools/verify_tools.py` +3、`capabilities.py` -7；`specs/d.py` / `specs/f.py` /
> `specs/m.py` 净 0）。§3 表 `capabilities.py` 3375 → 3368。三格（75 / 94 / 2）逐格未抬（上限 75 / 95 / 5）。
> **2026-11-16 EC3（`mss:` 提交记号带族）**：314 个 `.py`、75 个 `>800` 都不变；总行数
> 289,987 → **290,412**（+425：`agent_f/submission.py` +259、`manuscriptsubmission.py` +93、
> `manuscriptclosing.py` +35、`agent_d/write_report.py` +37、`agent_skills.py` +1 —— 记号头改
> `mss:<族>-<号>`、老记号 `mss:<号>` 三态兼容读（载体路径 / 上下文唯一确定才用，跨族同号不猜）、
> E 收工幂等按 (族, 稿号)；判据 `tests/test_submission_tokens_are_family_and_id.py`）。
> 三格（75 / 94 / 2）逐格未抬（上限 75 / 95 / 5）。
> **2026-11-16 EC2（携带单 `mss:` 键带族）**：314 个 `.py`、75 个 `>800` 都不变；总行数
> 289,825 → **289,987**（+162，全在 `src/agentflow/depsection.py`：携带单的 `mss:` 键从单号
> 改成 `(族, 稿号)`、老键三态兼容读、键与载体族对不上就整节拒 + 两处纯函数拆出；判据
> `tests/test_carried_sheet_keys_are_family_and_id.py`）。三格（75 / 94 / 2）逐格未抬
> （上限 75 / 95 / 5）。
> **2026-11-16 TR3（概念 + 未签稿的拒信排到判档之前）**：314 个 `.py`、75 个 `>800` 都不变；总行数
> 289,811 → **289,825**（+14，全部在 `agent_b/register_statement.py`：那道确定性闸从概念口径块
> 搬到 NT2 判档之前）。三格（75 / 94 / 2）逐格未抬（上限 75 / 95 / 5）。
> **2026-11-14 TR 收口（第二份证明的稿归属 / 台账查口收口 / 登记表补登，本批记账）**：312 个 `.py`、
> 75 个 `>800` 都不变；总行数 285,034 → **285,055**（+21：`agent_b/register_statement.py` +16、
> `dispatchpolicy.py` +3、`verifications.py` +2；`secretary.py` 只改注释、行数不变）。三格（75 / 94 / 2）
> 逐格未抬（上限 75 / 95 / 5）。
> **2026-11-14 CLI（`--project` 落点 / auto 台账 / 越档旗标拒收，本批记账）**：312 个 `.py` 不变
> （本笔不加模块）；总行数 284,836 → **285,034**（+198，全在 `cli.py`：`--project` 在
> `_spec_of_start` 里四档共用一次解析、`START_FLAG_MODES` 越档旗标拒收表、`_has_ledger`
> 改读 `data/tasks.json`、`budget --status` 只读守卫、`interject --sid`）；`>800 行` 的 **75**
> 不变（`cli.py` 5,938 → 6,136，仍在阈值下）；三格（75 / 94 / 2）逐格未抬（上限 75 / 95 / 5）。
> **2026-11-13 W1（F 的命题形态闸挪到写盘之前，本批记账）**：304 个 `.py` 不变（本笔不加模块）；
> 本笔动 `agent_f/core.py`（+213）与 `agent_f/manuscript.py`（+55），合计 **+268** 行；同一时点
> 已在册的另两笔（W2 的 `agent_b/register_statement.py` +117、R5 的
> `agent_f/core.py`/`agent_f/create_plan.py`/`agent_loop.py` +117）⇒ 合 **278,177**（按 `HEAD` 现算复核）。
> 尚在途的字节（`agent_f/abandon_plan.py` / `planabandon.py` / `specs/f.py` / `tools/attack_tools.py`）
> 不计入本读数，由它们自己那一笔认领并重记这一句。三格（75 / 92 / 2）
> 一格未抬：`>800 行` 仍 **75**、`>200 行` def 仍 **92**、重复 docstring 段仍 **2**（判据
> `tests/test_f_form_gate_precedes_the_write.py` 与 `tools/repo_survey.py`）。
> **2026-11-13 p281（四方合批收口，本批记账）**：304 → **307 个 `.py`**（新增
> `propositionrewrite.py`（W2 的原位重写写口）/ `dispatchpolicy.py`（X1 的派活判据）/
> `planabandon.py` 与 `agent_f/abandon_plan.py`（X1 的 plan 级放弃口）——W1 那一笔记的
> 「尚在途」字节与本批的其余模块自此全部入账）；总行数 278,177 → **279,504**。
> `>800 行` 仍 **75**、`>200 行` def 仍 **92**、重复 docstring 段仍 **2** —— 三格一格未抬；
> 全仓最大 `secretary.py` 15,124、`agent_loop.py` 14,585。
> **2026-11-13 p280（提示词批路 · 设计对齐最后一项，本批记账）**：304 个 `.py` 不变；
> 总行数 277,127 → **277,168**（净 +41：`agent_prompts.py` +32 的 p280 版本账、
> `agent_skills.py` +5 的教法文本、`specs/{b,b_sign_policy,e,f,l,m}.py` 合计 +4 同段改写）；
> `>800 行` 的 **75** 与全仓最大 `secretary.py` 14,839 都不变；三格（75 / 92 / 2）一格未抬。
> **2026-11-12 p279（G 的 revise 轮次教法，本批记账）**：304 个 `.py` 不变（没有新模块），
> 总行数 283,476 → **283,491**（+15，全在 `agent_prompts.py` 的 p279 版本说明一段；
> `specs/g.py` 是同一行内替换、行数不变）；`>800 行` 的 **75** 与全仓最大
> `agent_loop.py` 14,566 都不变。三格读数见上；本笔只认领这三格，不认领并行 lane 的字节。
>
> **2026-11-12 全库清扫（在途，本批只认领三格）**：`.py` 文件数 304 不变（清扫不改模块集合）；
> 总行数 283,491 → **281,811**（−1,680，全部是八条清扫 lane 删掉的过期注释与双倍行距空行，
> 代码与字符串常量零改动，每个文件都用「剥掉 docstring 后 AST 逐字相同」验过）；
> `>800 行` 仍 **75**、全仓最大 `secretary.py` **14,844**、`agent_loop.py`，14,569 行。
>
> **2026-11-12 全库清扫收口（364/364 已清理、103/364 已优化）**：`.py` 文件数 304 不变；
> 总行 **282,619**（较清扫前 283,491 少 872 行，其中清扫净删注释 ~2,300 行、优化新增的私有 helper
> 与等价说明又把一部分补回来）；`>800 行` **75**、最大文件换成 `secretary.py` 14,786。
> 三格基线（75 / 95 / 5）一格未抬；`>200 行函数` 仍 95、重复 docstring 段 2。
> **2026-11-11 甲/乙（轮次账跟着复审 / 同处旧判被覆盖，本批记账）**：304 个 `.py` 不变
> （没有新模块），总行数 283,277 → **283,476**（净 +199，全在既有文件里：
> `tools/review_tools.py` 甲+乙的轮次推进与覆盖规则、读数与注释；`schema.py` 的
> `superseded` 状态值与 `superseded_by` 指针（ReviewFinding，FC-27 已按业主放行登记）；
> `agent_g/revise.py` 的"改稿不再推进轮次"；`verify.py` 的 `accepted_with_open_error`
> 认 `superseded` 为已处置；`agent_skills.py` 的 G 手册那半句；`agent_h/core.py`
> 自检的变化点清单多 `review_rounds` 一格）；`>800 行` 的 **75** 与全仓最大
> `agent_loop.py` 14,566 都不变。三格读数见上；本笔只认领这三格，不认领并行 lane 的字节。
> **2026-11-11 乙（按签拦收工，本批记账）**：304 个 `.py` 不变（没有新模块），
> 总行数 283,051 → **283,277**（+226，全在 `agent_loop.py`：收工门从「送审后必须起
> `wait_for=V` 的计时器」改成业主追裁的「计划号/稿没有现行的 V 签、也没有被明确放弃
> 才拦」—— 三个角色的读法拆到类外四个 helper，方法本身只留三态与拒信）；
> `>800 行` 的 **75** 不变；全仓最大 `agent_loop.py` 14,340 → **14,566**。
> **2026-11-11 真机三裁定（甲 + 丙，本批记账）**：303 → **304** 个 `.py`（+1：
> `specs/b_sign_policy.py` 44 行 —— B 的「送审与交稿」两段从 `specs/b.py` 整段搬出，
> 因为 `specs/b.py` 在 HEAD 上正好 800 行、再写就顶过软基线）；总行数 282,537 → **283,051**
> （+514：`agent_loop.py` +102 的送审等签收工门、`tools/review_tools.py` +93 的
> `_open_findings_gate` 与读数、`manuscriptsubmission.py` +137 的签触发提交、
> `vsigns.py` +23 的 `issue(store=...)` 接线、三份 specs 的题面与其余接线）；
> `>800 行` 的 **75** 不变（`specs/b.py` 搬完回到 789，没有新文件越过 800）、
> 全仓最大 `agent_loop.py` 14,238 → **14,340**。
> **2026-11-11 甲/乙/丙 + webui 真回归四批（本批记账）**：303 个 `.py` 不变（没有新
> 模块），总行数 282,534 → **282,537**（+3，全在注释里：`capabilities.py` +2 的
> `two_layer_reconciliation` 沿革、`specs/g.py` +1 的判据出处；`ui/` 与入库的
> `web/static/` 不是 `.py`、不进这三格）；`>800 行` 的 **75** 与 `agent_loop.py`
> 14,238 都不变。
> **2026-11-11 B 收录的第二条入口也分配路径号（本批记账）**：文件数 303 不变（没有新
> 模块），总行数 282,310 → **282,534**（+224，全在本批改的两个既有文件里：
> `agent_b/register_statement.py` +213、`secretary.py` +11 —— ② 逐份 inline 登记也调
> `manuscriptpaths.assign_path_group`、三条读数同号、单段扫描认这个号）。`>800 行` 的
> **75** 不变（两个文件本来就过线）、全仓最大仍是 `agent_loop.py` 14,238。
> **2026-11-11 P1 七件一致化 + G/H 边集（本批记账）**：301 个 `.py` 不变（没有新模块），
> 总行数 281,304 → **282,221**（+917：B 的 `open_polish_copy` 动作声明与 `-pN` 退役、
> D→B 指针支的路径号、`manuscripts.submission_reading` 工具、F/V/D 题面那条禁令、
> 以及并行 lane 的 G/H/C 题面与 D 的向上汇报）；`>800 行` 的 75 不变；
> 全仓最大仍是 `agent_loop.py` 14,238。
> **2026-11-11 四块（体量拆回 / 工具登记 / 多证明判据 / webui 生成物）（本批记账）**：
> 301 → **303** 个 `.py`（+2：`agent_b/proof_receipt.py` 47 行、`agent_g/revise_gates.py`
> 80 行，都是甲从既有大函数里整段搬出来的新模块）；总行数按现盘重算 = **282,310**
> （相对上面那一格 282,221 的差值 = +89；本批自己的字节 = +74：甲两个新模块 127 行、
> 两个原函数净 -63 行，丁 `webui/readers.py` +8 —— 另外 15 行是这一批开工前盘上就已经
> 存在的差值）。`>800 行` 的 **75** 不变、全仓最大仍是 `agent_loop.py` 14,238。
> **2026-11-11 手稿产出侧 / 呈递侧退役 `proof_no`（本批记账）**：本批只改既有文件的字节
> （F 的稿头不再写 `- 证明号：`、登记条目不再写 `proof_no` / 版本段不再写 `p<N>@`、D 的
> 携带行与 `mss:` 记号不再带这一格；读侧对老盘两种格式照旧），没有新模块。三格按现盘
> 重算 279,785 → **281,183**：文件数 294 → 298（+4 个新模块）、`>800 行` 的 75 → 76
> （新增的 `manuscriptsubmission.py` 越过 800）—— 这两格增量来自并行 lane 的新模块，
> 本笔只认领三格读数、不认领它们的字节。
> **2026-11-11 三块（V 父编码 / E 收工自动提交 / B 收录置提交与多证明路径）**：按职责拆成
> `manuscriptsubmission.py`（统一读口 + B 收录记号）、`manuscriptclosing.py`（E 收工自动提交）、
> `manuscriptproducers.py`（路径族 ⇒ 产出方 + V 的父名单）、`manuscriptpaths.py`（多证明路径号）；
> `agent_b/autosubmit.py` / `agent_e/autosubmit.py` 只是薄转发，不各自实现一遍。
> **2026-11-11 甲/乙 两笔并入后按现盘重算（本批记账）**：279,436 → **279,531**（净 +95：
> 甲 `tools/fs_tools.py` +93 —— B 的窄豁免与那段理由注释；乙 `agent_f/delivery.py` +2 ——
> 未签稿扫描的前缀改从 `manuscriptfamily` 派生）。文件数 291、`>800 行` 的 77、
> 全仓最大 `secretary.py` 14,206 / `agent_loop.py` 14,189 都不变。
> **2026-11-11 拿签之后冻结 / 优化副本 / 每族一条稿号（本批记账）**：本批四块各一处落点 ——
> `manuscriptfreeze.py`（新，171 行：拿签之后"这一份只读"的唯一判据，数据只从 V 的颁发表读）
> 与 `agent_b/open_polish_copy.py`（新，297 行：B 的优化副本 = 取已拿签的稿 → 复制成 B 号 →
> 清签）；`manuscriptids.py` 泛化成"每族一条计数器"（F/B/E 证明/E 数值）；
> `vsigns.py` 的拿签稿表（`signed_table` / `signed_manuscripts`，复用颁发表、不新建账）；
> `tools/fs_tools.py` 四个写口共用一道冻结闸。文件数 290 → **291**（两个新模块）、
> `>800 行` 的 77 不变；全仓最大 `secretary.py` 14,206、`agent_loop.py` 14,189 都不变。
> **2026-11-11 V 签侧退役 `proof_no`（本批记账）**：本批只动 V 签侧的四个写侧文件
> （`vsigns.py` / `verifications.py` / `vreceipts.py` / `agent_v/core.py`）与一份新判据
> （`tests/test_v_sign_no_proof_no.py`，a–d 四格）。文件数 291 → **294**、行数
> 279,608 → **279,785**、`>800 行` 的 77 → **75**（按现盘重算；含并行 lane 的未提交文件）；
> 全仓最大 `secretary.py` 14,206 / `agent_loop.py` 14,189 都不变。
> **2026-11-11 补第 ④ 条证据（收录之后按行上 `manuscript_id` 找回那份已签的稿）**：279,531 → **279,608**
> （净 +77：`agent_b/open_polish_copy.py` 297 → 374 —— 第 ④ 条证据、`_statement_manuscript_id`
> 与两段解释；判据补在同一份 `tests/test_b_open_polish_copy.py`）。文件数 291、`>800 行` 的 77、
> 全仓最大 `secretary.py` 14,206 / `agent_loop.py` 14,189 都不变。
> **2026-11-11 拆模块后按现盘重算（本批记账）**：276,432 → **276,662**（净 +230：另一条 lane
> 两笔并入 +188 —— d3ba5285「V 的在册闸认稿号」+152 与 07d263bb「被引稿也认稿号」+36；
> 本批 +42 —— `agent_v/core.py` 把 `manuscript_identity` 移进 `verify_proof` 的初值
> （`fail_closed_manuscript_identity`）＋ `tools/verify_tools.py` 的 `returns=` 补这一格）。
> 文件数 289、`>800 行` 的 75、全仓最大 `secretary.py` 14,206 / `agent_loop.py` 14,189 都不变。
> **2026-11-11 p283（先签后收录：认领之后升 kind）**：276,662 → **276,749**（净 +87：
> `verifications._gap_from_pending` 把「已认领给本命题、载体稿号与行上一致」的 pending 签
> 读成 `pending=False / claimed=True`（未认领的仍是 pending）；`agent_b/register_statement.py`
> 在认领回写之后补一次 kind 重评（`_attach_proofs` → `allow_pending=False` 照样认它）；
> `evidencebits` 两条 docstring 跟着改口径。判据是新文件
> `tests/test_the_first_sign_before_registration_still_lifts_the_kind.py`）。
> 文件数 289、`>800 行` 的 75、全仓最大 `secretary.py` 14,206 / `agent_loop.py` 14,189 都不变。
> **2026-11-11 p284（认领只解除来路，不解除票数）**：276,749 → **276,877**（净 +128：
> `verifications._pending_claim_streak` 数一叠 pending 台账的尾部连续票数与"最新一票的
> sha 是不是本条正文"（计数仍复用 `_hold_run_lengths`），`pending_sign` 交回那一叠的
> 全部行（`passes`），`_gap_from_pending` 于是要求认领之后仍满 `SIGN_STREAK_NEED` 票、
> 同一份正文才 `ok=True`（一票 / 两票 / 票数够但 sha 不一 ⇒ `holding`）；
> `evidencebits.kind_following_grade` 把"还差门槛"与"一次都没签"分开说）。
> 文件数 289、`>800 行` 的 75、全仓最大 `secretary.py` 14,206 / `agent_loop.py` 14,189 都不变。
> **2026-11-11 F 的读数面列出已签概念（本批记账）**：276,877 → **276,950**（净 +73：
> `agent_f/manuscript.py` 把已签（`reviewed=true`）概念逐条列进 4.1 的可读面并说清
> "概念可读不可引（可引门只放命题）"，未签的仍只报条数；`agent_f/core.py` 的 4.1 段
> 跟着把"下面列出来的都是够格的"改成"命题都够格、概念可读不可引"）。
> 文件数 289、`>800 行` 的 75、全仓最大 `secretary.py` 14,206 / `agent_loop.py` 14,189 都不变。
> **2026-11-11 F 可以把写好的证明交进来（本批记账）**：276,950 → **277,425**（净 +475：
> `attackround.py` 新增 `HANDED_PRODUCT_SCHEMA` 与 `clean_proof_steps` / `clean_new_subgoals`
> 两份共用判据（`parse_round` 也改读它们）、`agent_f/core.py` 新增 `parse_handed_product` /
> `_handed_product_round` / `_foreign_cite_hits`、`agent_f/step.py` 的 `step(product=…)` 分支、
> `tools/attack_tools.py` 的 `attack.step(product=…)` 参数面与装配、`specs/f.py` 的动作表
> 与一条教法、`agent_prompts.py` 的 p275 版本账；新判据
> `tests/test_f_can_hand_in_its_own_proof.py` 不在 `src/` 里 ⇒ 不进这三格）。
> 文件数 289、`>800 行` 的 75（`attackround.py` 789）、全仓最大 `secretary.py` 14,206 /
> `agent_loop.py` 14,189 都不变。
> **2026-11-10 F 侧撤"按命题号写证明"（p274，本批）**：276,029 → **276,185**（净 +156：
> `specs/f.py` 的送审参数表删掉"在册后给号"那一格并改写四处按号教法、`agent_f/manuscript.py`
> 两个"兼容形参" `statement_id` 删掉、`agent_f/core.py` 的登记面改成交稿号 ＋ 正文、
> `agent_f/vsign.py` 的送审提示只点稿路径、`agent_skills.py` 的 F 手册按新口径重写；
> 另一条 lane 与判据文件的行数按现值并入）。文件数 286 不变、`>800 行` 的 78 不变；
> 全仓最大 `secretary.py` 14,206、`agent_loop.py` 14,189 不变。
> **2026-11-10 F 的空稿号补号（p275，本批）**：276,185 → **276,281**（净 +96：
> `agent_f/core.py` 的 `_hand_proof` 在空稿号时按「调用方给的 / 沿用子目标的 /
> 向 F 自己的号源新取」补号并回传 `manuscript_id_source`，于是 F 的新写路径不再
> 落在 `f-proof-plan-*` 那一支；`agent_f/step.py` 把这一格带进返回值）；
> 文件数 286 不变、`>800 行` 的 78 不变；全仓最大 `secretary.py` 14,206、
> `agent_loop.py` 14,189 不变。
> **2026-11-10 C 的关系推断：局部树的按需展开（p273，A + B 批）**：274,431 → **276,029**
> （本批新增 `ledgerindex.py`（只读索引 + 局部树，约 900 行）与 `tools/ledger_tools.py`
> （`ledger.resolve` / `ledger.expand` 两件），`specs/c.py` 的关系推断教法由"手算多跳"
> 改成"选根 → 按层展开 → 对 frontier 拼接"，`agent_prompts.py` 记 p273 的版本账；
> 其余增量是另一条 lane 在 p272 之后的改动按现值并入）。文件数 283 → **286**、
> `>800 行` 的 75 → **78**；全仓最大 `secretary.py` 14,206、`agent_loop.py` 14,189 不变。
> **2026-11-10 立项用计划号、入账才建命题行（p271）**：274,299 → **274,431**（净 +132：
> `specs/m.py` +33（policy 三句教法：立项不建在命题台账上 / 决定即立项 / 成果是收录的产物）、
> `agent_skills.py` +70（M 手册那一条的镜像，含计划稿三种落点那张表）、
> `agent_prompts.py` +29 的版本账；三处教法都只进题面 / 手册，入口闸、B 的收录闸与
> closing 的判定一个字没改）。文件数 283、`>800 行` 的 75 都不变；
> 全仓最大 `secretary.py` 14,205、`agent_loop.py` 14,189 不变（新判据
> `tests/test_registration_is_the_hard_sequence.py` 不在 `src/` 里 ⇒ 不进这三格）。
> **2026-11-10 体量：不抬基线，改搬（撤回 p268 那一抬）**：`specs/b.py` 824 → 773 行 ——
> policy 里「收录与识稿」九条逐字搬进同包的 `specs/b_ingest_policy.py`（新文件 78 行，同样登记在
> `.noai-paths`），`specs/b.py` 在原位置用 `*INGEST_POLICY` 摊回，渲染出来的提示词一个字没变。
> 文件数 +1（282 → 283）、`>800 行` 的 76 → 75（回到原值）；总行数见上面那句当次读数。
> **2026-11-10 递审只递框架手稿（p270）**：274,251 → **274,299**（净 +48：`specs/f.py` +4、
> `specs/v.py` +6、`specs/d.py` +3、`agent_skills.py` +18、`agent_prompts.py` +17 的版本账；
> 三处教法都只进题面 / 手册，入口闸一个字没改）。文件数 283、`>800 行` 的 75 都不变；
> 全仓最大 `secretary.py` 14,205、`agent_loop.py` 14,189 不变。
> **2026-11-10 自产概念在 B 的动作面有入口（p268）**：273,939 → **274,029**（净 +90：
> `agent_b/register_statement.py` +48（`self_authored` 参数与概念 origin 三档处置）、
> `specs/b.py` +24（参数面一格 + policy 一条教法；800 → 824 ⇒ **首次越过 800 行**）、
> `agent_prompts.py` +18（p268 版本那一段说明）。文件数 282 不变、`>800 行` 的 75 → **76**
> （多出来的就是 `specs/b.py`）；`agent_loop.py` 14,189 与全仓最大 `secretary.py` 14,205 都不变）。
> **2026-11-10 概念良定义证明有落点（业主裁定 甲）**：273,454 → **273,913**（净 +459：
> `conceptrows.py` 的良定义证明三态读数与构造口、`secretary.py` 的签判据与五元位委托、
> `agent_b/register_statement.py` 的 concept 证据重算与未签闸、`verify.py` 的审计改口径、
> `verifications.py` 的概念读侧分档（有签 ⇒ 良定义证明、无签 ⇒ 照旧点名）；
> 新判据 `tests/test_concept_well_definedness_has_a_landing.py` 不在 `src/` 里 ⇒ 不进文件数）。
> 文件数 282、`>800 行` 的 75 都不变（`specs/b.py` 净 +11 但停在 800 行整，未越过）。
> 全仓最大改为 `secretary.py` 14,190（本批 +61 行量级；`agent_loop.py` 14,189 紧随其后）。
> **2026-11-10 概念批体量收口（不抬基线，改拆 + 去重）**：273,913 → **273,939**（净 +26：
> `agent_b/register_statement.py::_ingest_apply_evidence` 211 → 157（概念分支搬到
> `_concept_evidence_replay`）、`secretary.py::write_concept_row` 211 → 171（新建 / 过渡同步的行
> 数据搬到 `_concept_row_payload`）；`conceptrows.py::concept_bits` 与 `secretary.py::_concept_bits`
> 那段逐字重复的 docstring 收成一处在 `conceptrows`、秘书那处改成引用 ⇒
> `dup_docstring_segments` 6 → 5、`src_functions_gt200_lines` 97 → 95、`>800 行` 仍 75；
> 全仓最大 `secretary.py` 14,190 → 14,205）。
> **2026-11-10 被引面读数（现盘读数并计同期 concept / 手稿切节两条 lane）**：273,014 → **273,454**（`statementledger.py` 加反向读数 `cited_by`：给定一条命题 ⇒
> `dependencies` 里 `source_stmt_id == 它` 的那些 `used_by`（逐条带 `kind` / `label` / `status` /
> `created_at`，另有 `by_status`）；`rows_of` 加 `table=` 让 `statements` / `dependencies` 走同一份
> try/except —— 被引面不自己再扫一遍依赖账。写侧一个字没改（B 登记先拿号、再按那个号写 `used_by`，
> 判据 `tests/test_the_cited_face_is_read_from_the_dependency_ledger.py`）。文件数 282、
> `>800 行` 的 75、`agent_loop.py` 14,189 都不变。
> **2026-11-10 体量：不抬基线，改拆函数**：272,930 → **273,014**（净 +84：`agent_b/register_statement.py`
> 把三条越过 200 行的函数各按内部自然分段拆开 —— `_ingest_apply` 239 → 160（numeric_evidence /
> dependencies 两格各搬成一个方法）、`_ingest_apply_evidence` 229 → 158（按现行事实重建证据面 /
> 按现行证据面双向落回 kind 各搬成一个方法）、`_attach_proofs._transition` 209 → 164（挂新证明清单 /
> 刷新已有 kind 留痕各搬成一个方法）；六个新函数 30–64 行，行为逐字不变。文件数 282、
> `>800 行` 的 75、`agent_loop.py` 14,189 都不变；`src_functions_gt200_lines` 仍 95。
> **2026-11-10 T1 kind 升档凭据收口**：272,859 → **272,930**（净 +71：`evidencebits.kind_following_grade`
> 加 `allow_pending`（B 的登记 / 收录路传 False：升档只认这一条命题自己的台账那一签；
> "命题还没在册时审的那一签"只够过准入闸）；`verifications.proof_review_gap` 多一格
> `pending` 的来路读数；`verifications.sign_statement` 把签发侧文件挪到判 kind 之前
> （签名那一笔的 `_kind_upgrade.basis` 才能点名 witness，与 B 那一支同一句）；
> 配套新判据 `test_d37_kind_follows_grade::test_criterion6_a_pending_sign_alone_does_not_lift_a_new_row`。
> 文件数 282、`>800 行` 的 75、`agent_loop.py` 14,189 都不变）。
> **2026-11-10 T1 拆包补课**：272,414 → **272,442**（净 +28：T1 把 `land_manuscript` /
> `ingest_manuscript` 两个动作写进了 `agent_b/register_statement.py`，违反 M6/M7 的
> 「一个动作一个文件」—— 本批把两个动作各自搬回 `agent_b/land_manuscript.py`（102 行）与
> `agent_b/ingest_manuscript.py`（213 行），`agent_b/_support.py` 收两个路径 helper（243 → 273 行），
> `agent_b/register_statement.py` 7,200 → 6,879 行；`capabilities.py` 的对账读数跟着 T1 改成 66 = 25 + 41 + 0）。
> 文件数 282（+2）、`>800 行` 的 75、`agent_loop.py` 14,189 都不变）。
> **2026-11-10 T1 收录证据补口**：272,442 → **272,859**（净 +417：`agent_b/register_statement.py`
> 把 D-37 的 `kind` 升档收进 `_attach_proofs`（判据仍是 `evidencebits.kind_following_grade`），
> 并让 `mode=apply` 写完正文之后走 `_ingest_apply_evidence` 与登记路同一份证据重算；
> 追加裁量 ①②③：重放双向重算、`_kind_upgrade` 统一措辞、kind 格 receipt。文件数 282、
> `>800 行` 的 75、`agent_loop.py` 14,189 都不变）。
> **2026-11-10 T1 收口再改一次**：271,341 → **272,414**（净 +1,073：`agent_b/register_statement.py`
> 新增 `land_manuscript` 的显式落稿参数与 `ingest_manuscript`（位置 + 格 + 逐格回执 + I1/I2）、
> `secretary.py` 新增提取口 `extract_manuscript`、`manuscriptintake.py` 新增 `INGEST_MODES`、
> `capabilities.py` 登记两个 `own.*` 动作；`specs/b.py` 净 +141 但仍在线下（789 行）。
> 文件数 280、`>800 行` 的 75、`agent_loop.py` 14,189 都不变）。
> **2026-11-10 D268 批 2 再改一次**：271,400 → **271,341**（净 -59：`bits_after_sign` /
> `sign_filing_reading` / `sign_reading` 改为只认可复算凭据，B 的两条旁路与秘书/收工/F
> 四个读点改读 `sign_reading`，网页新增 `recomputable_signs`；删掉 `closing` 的两个
> 块读数 helper。文件数 280、`>800 行` 的 75、`agent_loop.py` 14,189 都不变）。
> **2026-11-10 D268 批 1 再改一次**：269,889 → **270,572**（本批净 +683，且是纯新增：
> `vsigns.py` 只在文件末尾追加了签的唯一读口 `sign_reading` / `credential_reading` /
> `_recomputable`（只读、本批不接线），既有函数一个字节都没动；另加配套只读 CLI
> `scripts/sign_audit.py` 与 `tests/test_sign_reading.py`（都不在 `src/` 里，不影响文件数）。
> 文件数 280、`>800 行` 的 75、`agent_loop.py` 14,139 都不变）。
> **2026-11-10 D5 收口（`c2472c1a`）再改一次**：271,339 → **271,400**（`tools/fs_tools.py` 的
> A/B 写手稿形名字受控拒（notes/ 与 -v2 不再绕过唯一写口）+ 配套判据；文件数 280 与
> `>800 行` 的 75 都不变，`agent_loop.py` 14,189 不变）。
> **2026-11-10 D3 批 2 再改一次（与同期的 D1 收口两笔合并计入）**：270,572 → **271,339**
> （D3 批 2 净 +594：写侧分类三格 + 后果分叉的 `terminal="report"` / 类别读侧 +
> `report_fix_list` + 回执与义务；同期 D1 两笔净 +173。文件数 280 与 `>800 行` 的 75 都不变，
> `agent_loop.py` 14,139 → **14,189**）。
> **2026-11-10 D3 批 1 再改一次**：269,521 → **269,828**（本批净 +300：`verifications.py` 新增
> 只读的 `fault_kind_of` / `is_a_vote` / `vote_reading` 与 `FAULT_KINDS` / `FAULT_KIND_VALUES` /
> `FAULT_KIND_SOURCES`，另加配套只读 CLI `scripts/verify_audit.py`（不在 `src/` 里，不影响文件数）；
> 图上旧读数与 HEAD 之间另有 7 行是批前已落盘的漂移；文件数 280 与 `>800 行` 的 75 都不变，
> `agent_loop.py` 14,139 不变）。
> **2026-11-10 D3 批 1 收口再改一次**：269,828 → **269,889**（report_gap 从 kind 挪到 cause、
> `fault_kind` 按"键在不在"区分新老行；净 +61，文件数 280 与 `>800 行` 的 75 都不变，
> `agent_loop.py` 14,139 不变）。
> **2026-11-09 拆模块（D10 的 refvocab）再改一次**：269,322 → **269,377**（文件数 278 → **279**，
> `>800 行` 77 → **76**：`refvocab.py` 839 行拆成 `refvocab.py` 680 + `refspecs.py` 214 ——
> 词表/号形那一半整段搬走，解析与存在性留在原名下、按名字回引；`tools/repo_survey.py`
> 的软判据（`tests/test_repo_survey_does_not_get_worse.py`）量的是"不许多"，处置是拆、
> 不是抬基线。`agent_loop.py` 14,139 行不变）。
> **2026-11-09 拆模块（D12 的板项投影）再改一次**：269,377 → **269,417**（文件数 279 → **280**，
> `>800 行` 76 → **75**：`statusreport.py` 808 行拆出 `boardrows.py`（板项行的状态投影
> `tasks_row_reading` 与它的三个常量）—— 同一笔处置、同一条软判据；`statusreport.tasks_row_reading`
> 仍可用（按名字回引），`agent_loop.py` 行数不变）。
> **2026-11-09 拆函数（未在册穷举那一支）再改一次**：269,417 → **269,460**（文件数 280 与
> `>800 行` 75 都不变：`agent_v/core.py::_review_unregistered_exhaustion` 206 行拆成
> 编排层 + `_read_unregistered_exhaustion_ctx`（107）+ `_finish_unregistered_exhaustion`（80），
> 三段都 ≤200 —— 同一条软判据的函数那一格；行为逐字不变，读数见 `temp/_probe_v_exhaustion.py`）。
> 2026-11-09 再改一次：266,332 → **266,484**（两把尺统一：`textutil.py` 抽出唯一的关键词
> 命中判据、`tools/table_tools.py` 的 statements 搜索分支改调它（+128）；同日的声明面收口
> （`table.search` 的 summary 与 `query` / `fields` 说明改真口径、`PROMPT_VERSION` 抬到 p263）
> 再 +24 行；文件数 275 与 `>800 行` 的 75 都不变，`agent_loop.py` 行数也不变）。
> **2026-11-09 D11 收口再改一次**：268,334 → **268,340**（D11 ①②③ 的运行期文案、
> 进度标记与两处撤销注释改写；另把 12-K 的原文逐字照登并标时点；净增 6 行，全在
> `agent_loop.py` ⇒ 14,133 → **14,139**；文件数 277 与 `>800 行` 的 76 都不变）。
> **2026-11-09 T2 收口再改一次**：269,235 → **269,322**（净 +87：`manuscriptfamily.py` +5
> —— `classify` 改名 `classify_manuscript`，短名让路给 `projects.classify`；两把 sha 尺
> 拆开命名 —— `proofregistry.py` +21、`verifications.py` +21（签的对拍尺 vs 原样
> `text_sha`），`vsigns.py` +14、`evidencebits.py` +14 是惰性转发，`agent_v/core.py` +1
> 是三处 `given != body` 改用原样尺，其余 11 个模块各 +1 的 import；`manuscriptintake.py`
> / `vreceipts.py` 净 0；文件数 278 与 `>800 行` 的 77 都不变，`agent_loop.py` 14,139 不变）。
> 新人打开任何一个文件都是一本小册子，
> 于是"从哪读起"本身成了一道门槛 —— 这份图就是为了把这道门槛拆掉。
> （本行原先写"188 个 `.py`、98,217 行、37 个文件超过 800 行"（观测 2026-10-06），
> 再原先写"77 个文件、77,391 行、38 个文件超过 800 行"，都过期了 ——
> 批 R27 按现算改正并把复跑命令写进这一行；**批 R46 又改了一次行数**：
> 123,924 → **123,931**（动的是 `agent_prompts.py` 的 `p95` 变更，净 +7 行 ——
> 这个数会被 `temp/_probe_doc_vs_code.py` 的 ③ 抓住，见 `draft/108` §三 的常驻探针那一段）；
> **批 R47 再改一次**：123,931 → **123,991**（`llmseam.py` 补 `framework_handoff` /
> `framework_interrupt` 两个广告面与 `framework_final.blocked` 的透传，净 +60 行）；
> **批 R48 再改一次**：123,991 → **124,026**（`llmseam.py` 补派活那一栏的
> `DISPATCH_NOTIFY_JSON_SCHEMA` 并挂到 `framework_summon` / `framework_summon_many`，
> 净 +35 行）；**批 R52 再改一次**：124,026 → **124,044**（工具层改
> `doc.paper_render` 的摘要 + `agent_prompts.py` 的纸包两处，净 +18 行）；
> **批 R54 再改一次**：124,044 → **124,068**（CS-10 ② 的产出即登记 + 四处 `specs/` 的文本，
> 净 +24 行）；**批 R56 再改一次**：124,068 → **124,112**（纸包第六节的删减 + G/H 版的
> 第八节整块替换，净 +44 行）；**2026-10-13 再改一次**：125,256 → **124,829**
> （`paper_package` 整条退场：删 `renderanchor` / `paperbuild` / `agent_g/paper_package`
> 三个模块、加 `papercompile.py`，净 −427 行；三格里的文件数 213 → **211**，`>800 行` 仍是 44。
> **2026-10-13 R72 收尾再改一次**：124,829 → **124,841**（净 +12 行：改掉三条被全量套件抓出来的
> 陈旧读数 —— `capabilities.py` 里被 `test_r4_roles_surface` 逐字比对的那句对账读数、
> `tools/doc_tools.py` 的成功支从 `ok(body)` 改成字面量键表；文件数 211 与 `>800 行` 的 44 都不变。
> **2026-10-21 再改一次**：124,841 → **145,384**（文件数 211 → **218**，`>800 行` 44 → **50**；
> `agent_loop.py` 6,511 → **7,615** 行，新增 `litstage.py` / `promptstability.py` 等模块）。
> **2026-10-23 再改一次**：145,384 → **165,088**（文件数 218 → **241**，`>800 行` 50 → **58**；
> `agent_loop.py` 7,615 → **8,521** 行，新增 `agent_l/` 与 Lean 线那五个模块
> （`leanscope.py` / `leantoolchain.py` / `proofreport.py` / `quoteevidence.py` / `statementbody.py`）
> 与缓存那一排（`cachectl.py` / `tools/cache_tools.py` / `webui/cacheface.py`））。
> **2026-10-26 再改一次**：165,088 → **209,413**（文件数 241 → **255**，`>800 行` 58 → **69**；
> `agent_loop.py` 8,535 → **12,063** 行；同批新增的 `clock.py` / `agenttrace.py` /
> `depsection.py` / `errorstats.py` / `propositionkey.py` / `readouts.py` /
> `statementfission.py` / `stepdispatch.py` 与 `tools/clock_tools.py` 已在下面的分层表里各有一行）。
> **2026-11-03 再改一次**：209,413 → **223,941**（文件数 255 → **257**，`>800 行` 69 → **70**；
> `agent_loop.py` 12,063 → **12,760** 行）。同批把"谁抓这三个数"从 `temp/_probe_doc_vs_code.py`
> 的 ③（**不在 `tests/` 里、CI 不跑**）搬成判据 `tests/test_reading_map_counts.py`：那三个数
> 上一次更新是 2026-10-26，之后漂了 8 天而没有任何东西会红 —— 探针抓得到、但没人跑它。
> 复算命令就是上面那一条）。
> **2026-11-03 第二批再改一次**：223,941 → **225,440**（文件数 257 与 `>800 行` 70 都不变；
> `agent_loop.py` 12,760 → **12,826** 行、`cli.py` 5,329 → **5,493** 行 —— 这一批加的是判据与源码，
> 没有新模块，所以只有行数漂）。
> **2026-11-01 再改一次**：225,440 → **227,823**（文件数 257 → **258**，`>800 行` 70 → **71**；
> `agent_loop.py` 12,826 → **12,959** 行）。本批新增 `vsigns.py`（1033 行，新增的单职责模块：
> 写签 / 认签 / 派生索引 / 回执与送达读口），另有 `closing.py` / `verifications.py` /
> `agent_b/register_statement.py` 的增行；`vsigns.py` 已在第 1 层的表里有一行。
> **2026-11-03 第三批再改一次**：227,823 → **229,901**（文件数 258 → **261**，`>800 行`
> 71 → **72**；`agent_loop.py` 12,959 → **12,973** 行）。本批新增 `proofauthors.py`
> （112 行：谁写的这份证明）与 `vreceipts.py`（840 行：V 回执的 outbox / 投递 / 补投 /
> 读口）两个单职责模块 —— 两个都已在第 1 层的表里各有一行；`>800 行` 那一格
> +1 只来自 `vreceipts.py`（逐文件比对基线提交 `ddace7ae` 的 71 个过线文件：新过线的
> 只有它一个）。行数里还有 `vreceipts.py:163` 的 `json.dumps` 拆行补 `default=str`
> 净 +1 行（对纯 JSON 载荷不改变任何字节）。
> **2026-11-01 再改一次（扩面那一批）**：229,901 → **234,549**（文件数 261 → **262**，
> `>800 行` 72 → **73**；`agent_loop.py` 12,973 → **12,995** 行）。本批新增
> `statementabandon.py`（「放弃原命题」的标记与写口，已在第 1 层的表里有一行），
> 另有错误动作读数扩面（`errorstats.py` 2151 行 / 15 类新增）与
> `tools/conductor_tools.py` / `tools/table_tools.py` / `tools/text_tools.py` 的说明面压缩、
> `cli.py` 的增行。
> `>800 行` 那一格 +1 **不是**来自新模块（新模块 100 行级），而是 `webui/state.py`
> 785 → 857（跨线于 1328e94b）；逐提交量过，不是"顺手改了数"。
> **2026-11-02 再改一次（当次盘上）**：234,721 → **235,885**（文件数 262 → **263**，
> `>800 行` 仍是 **73**；`agent_loop.py` 12,995 → **13,198** 行）。逐文件比对基线提交
> `27e803c7` 的 blob 与当次盘上，三段来源都能点名：
> · **+199 行在 `agent_loop.py`** —— 编排那三笔：d6d7ba05（`conductor.summon_many`
>   工具入口并入同一条可抢占拼法，+56）、2984c2c8（顶趟落终态：收行包进 `try/finally`
>   + 三档映射 + `runs` 的 `end_ts`，+208/−105）、ea86a3db（单条 `own.*` 调用落
>   `agent_step_call`，+44/−4）；
> · **+284 行是新模块 `webui/facecache.py`**（dbc7c254：`/api/package` 与 `/api/artifacts`
>   按盘失效缓存 + cache 三格可观测）—— 文件数 262 → 263 就是它，`>800 行` 那一格不动；
> · 其余 **+667 行**是并发施工落在既有文件里的增行（`vsigns.py` +191、`verifications.py`
>   +132、`tools/table_tools.py` +98、`secretary.py` +65、`agent_v/core.py` +60 等），
>   同一次逐文件比对得出，没有一条是新过 800 行的文件。
> · 本批清账**自己**又 +14 行（`webui/readers.py` +5 = `CheckpointView` 类型声明三格、
>   `stop_reasons.py` +5 = `crashed` 登记、`agent_loop.py` +4 = `crashed` 的任务结局
>   补账）—— 所以这三格是按写完之后的盘上再抓一次的，不是抄前一次的数。
> 这一次不靠 `temp/_probe_doc_vs_code.py` 的 ③（那个探针不在 `tests/` 里、CI 不跑）：
> `tests/test_reading_map_counts.py` 现算钉住这三格 + 最大文件那一格。
> **2026-11-02 再改一次（裁定「甲」的收尾重抓）：235,885 → 236,722**（文件数
> 263 → 264；`>800 行` 73 与 `agent_loop.py` 13,198 行都不变）。本批自己的增行是
> `webui/readers.py` 的 `run_digest()`（趟次档案：从事件流现算、不读也不落索引）、
> `webui/server.py` 的 `handle_run_digest`（按盘失效缓存复用 `facecache`）、
> `webui/routes.py` 的一条自有端点，以及配套判据。文件数 +1 来自并行的 F 线
> （`agent_f/vsign.py`，不在本批改动面里；收尾时按同一份盘上现算，不抄前一次的数）。
> **退场的那三个模块名这里刻意不写 `.py` 扩展名**：本图自己的判据要求图里每个像文件名的
> token 都在盘上真的存在，写全名会让那条判据红 —— 而它们确实已经不在盘上了）。）
> **2026-11-03 收尾重抓**：240,210 → **240,333**（文件数 265、`>800 行` 73 与最大文件那一格都不变）。
> 240,210 是网页端那批收尾时的观测；此后盘上又有增行（V 线那两处改动当时尚未提交，净 +52 行），
> 本次按 `:10` 的复跑命令对**当次盘上**再抓一次，不是抄上一次的数。
> **2026-11-03 件一/件二收尾**：240,333 → **240,460**（同一份盘上现算；本批净 +127 行：
> 件一 `agent_v/core.py` / `vsigns.py` / `agent_f/vsign.py`，件二 `verifications.py`）。
> **2026-11-03 三条 lane 全落完后重抓**：240,460 → **240,475**（文件数 265、`>800 行` 73 与
> 最大文件那一格都不变；这是最后一路收尾提交（`7a2d69f0`）之后按 `:10` 的复跑命令对
> 当次盘上再算的一次，不是抄上一条的数）。
> **2026-11-04 p236 收口再抓**：245,449 → **245,470**（文件数 267、`>800 行` 74 与
> `agent_loop.py` 13,352 行都不变）。这 +21 行是 p236 的账本注（`agent_prompts.py` 的
> p236 段，只写注释、不改模型可见文本）与同批的两份 golden / 基线重冻之后按 `:10`
> 的复跑命令再算的一次；判据 `tests/test_reading_map_counts.py` 钉着。
> **2026-11-04 p237 收口再抓**：245,470 → **245,491**（文件数 267、`>800 行` 74 与
> `agent_loop.py` 13,352 行都不变）。这 +21 行是 p237 的账本注（`agent_prompts.py` 的
> p237 段，只写注释、不改模型可见文本 —— 段只动 B / G 两格）；golden（agent 面）与
> warm 读数重冻之后按 `:10` 的复跑命令再算的一次；判据 `tests/test_reading_map_counts.py` 钉着。
> **2026-11-04 p238 收口再抓**：245,491 → **245,521**（文件数 267、`>800 行` 74 与
> `agent_loop.py` 13,352 行都不变）。这 +30 行分两处：+22 是 p238 的账本注（`agent_prompts.py`
> 的 p238 段，只写注释、不改模型可见文本 —— 段只动 G 一格）；另 +8 是 `0ed46fb3` 在
> `specs/g.py` 的 `LEAN_FILE_ROW` 上方加的口径注（改的是三处字，注是解释为什么）。
> golden（agent 面）与 warm 读数重冻之后按 `:10` 的复跑命令再算的一次；判据
> `tests/test_reading_map_counts.py` 钉着。
> **2026-11-04 p241 收口再抓**：247,512 → **248,079**（文件数 267 → **268**，`>800 行`
> 75 → **74**；`agent_loop.py` 13,352 行不变）。文件数 +1 是新增模块 `manuscriptform.py`
> （743 行：证明手稿的唯一实现，F 的 `f-proof` 与 B 的 `b-proof` 共用；已在第 1 层的表里
> 补一行）；`>800 行` 少 1 是 `agent_f/manuscript.py` 改成转发壳之后 890 → 468 行
> （逐文件比对基线提交 `035b7365`）。本次由 `tests/test_reading_map.py` 的孤儿模块与
> `tests/test_reading_map_counts.py` 的开头三格同时点名，按 `:10` 的复跑命令对当次盘上重算。
> **2026-11-04 p235 收口重抓**：243,001 → **245,449**（文件数 266 → **267**，`>800 行`
> 73 → **74**；`agent_loop.py` 13,352 行不变）。逐文件对账基线提交 `74d7c646`：
> · 文件数 +1 是新增模块 `bmanuscript.py`（221 行：B 的改写手稿，`reports/b-proof-<命题号>.md`
>   的可签载体，与 F / E 同形；已在第 1 层的表里有一行）；
> · `>800 行` +1 只有一个新过线的文件：`agent_d/write_report.py`；
> · 其余 2,227 行落在既有文件里，最大的几笔是今晚收口的几处：`papermapping.py` +565
>   （`6fb014f5` 三条已知缝隙的通道判定统一）、`closing.py` +220、
>   `agent_f/manuscript.py` +169、`agent_skills.py` +159、`specs/g.py` +141、
>   `agent_d/write_report.py` +127（同一条 lane 的收口）。
> 本次是三条判据（`tests/test_reading_map.py` 的孤儿模块与 §3 行数、`tests/test_reading_map_counts.py`
> 的开头三格）同时点名的过期读数，按 `:10` 的复跑命令对当次盘上重算，不是抄上一次的数。
>
> **它自己也有判据**：`tests/test_reading_map.py` 会断言
> ①图里提到的每个文件名都真实存在；②`src/agentflow` 的每个模块至少在这张图里出现一次
> （不许有"孤儿文件"）。所以图不会烂成过期文档。

---

## §0 三条使用规则

1. **先看"谁是权威"再看实现**。这个仓库里同一件事的**声明**与**实现**常常分处两个文件
   （声明：`capabilities.py` / `schema.py` / `AGENTS.md`；实现：`agent_*.py` / `store.py`）。
   改之前先问："这条规则的权威定义在哪？"——§2 的表里"先读"那一列就是它。
2. **每个结论都要落到一条会红的判据上**。§4 给"哪一类判据在哪个测试文件"。
   找不到判据的改动 = 改完没人拦。
3. **禁改区先看 `AGENTS.md`**。清单在 `AGENTS.md` 与 `.noai-paths` 两处，必须逐条一致；
   命中就要 2 名 reviewer（`scripts/noai_gate.py` 是机器判据）。

---

### §0.1 已知欠账（可见地记着，不许静默）

- **`ocr.*` 三件（`ocr.detect_text_layer` / `ocr.backends` / `ocr.run`）—— 已接线（2026-10-07）。**
  **接线前的欠账**（2026-10-07 02:2x）：只有角色 B 的工具面拿得到这三件，而 `agent_b/core.py` 的抽取链撞到
  "无文本层"时直接放弃（`_load_doc_for` 里那句「无文本层（扫描版？）⇒ 无从逐字定位」），从不调它们
  ⇒ 文档在教一个生产面没人调的工具。
  **接线的落点**：`agent_b/core.py` 的 `_load_doc_for` ⇒ `_ocr_retry`（经**工具面**调 `ocr.backends` /
  `ocr.detect_text_layer` / `ocr.run`）—— 无文本层 ⇒ 先试 OCR ⇒ 重新抽取 ⇒ 仍空才回原来那句原因，
  且原因要能区分"没试 OCR"与"试了 OCR 还是没有"。
  **接线后的真机读数**（`temp/_r2b_ocr_probe_after.txt`，2026-10-07）：真机扫描件
  `projects/project5/library/扫描件.pdf`（6.5 MB）上 `_load_doc_for` 返回的不可用原因是
  「文献 0000 无文本层，**且本机没有可用的 OCR 后端（unavailable）**⇒ 无从逐字定位」——
  本机 `ocr.backends` 报 `available: []`（easyocr 因 torch/numpy 不兼容不可用、pytesseract 缺 tesseract
  可执行文件），`ocr.detect_text_layer` 报 `has_text_layer: False | source_kind: pdf | pages: 0 | chars: 0`。
  即：这条路径**真的被走到了**，且"没试过 OCR"与"试了、后端不可用"在原因里分得开。
  **两版读数并列**。**口径逐字写死**（免得下一个人按"出现处数"去数、数出第三种结果）：
  数的是**含 `ocr.` 的「行数」**（不是匹配总数 —— 同一行出现多次只算一行），
  `src` 递归 `-Recurse`、`docs` 只算顶层 `.md`。**在 `agentflow/` 目录下跑**（本文档所在目录）：
  ```powershell
  (Get-ChildItem src  -Recurse -File -Filter *.py | Select-String -Pattern 'ocr\.' | Measure-Object).Count
  (Get-ChildItem docs -File -Filter *.md          | Select-String -Pattern 'ocr\.' | Measure-Object).Count
  ```
  | 时刻 | `src/**/*.py` | `docs/*.md` 原始 | 本条自身 | `docs` 扣除本条 |
  |---|---:|---:|---:|---:|
  | 接线前（2026-10-07 02:2x） | 56 | 39 | 0（本条当时还没写） | 39 |
  | 接线后（2026-10-07，A 落地并复核后） | 68 | **47（测于 2026-10-07 02:47）** | **8（同刻）** | **39** |
  「原始」与「本条自身」两格是**自指**的（改这一条，它们自己就变）⇒ 它们各带**测量时刻**：
  上面那两个数是 **2026-10-07 02:47** 测的。**净数 `39` 是可复算的稳定量**（只要 `docs/` 别的文件不动），
  下一个读者按上面的命令数出别的数时，看时刻就知道那是本条改写前的读数。
  docs 明细（接线后，同一口径，测于 2026-10-07 02:47）：`ROLE-SPECS.md` 18 · `PROPOSALS.md` 12 · `READING-MAP.md` 8 · `PROPOSAL-side-effect-axes.md` 7 · `TOOLBOX-DRAFT-roles.md` 2。
  **读这张表时要知道四件事**（否则会把数读歪）：
  ① 唯一干净的接线前后对比是 `src` 一列：**56 → 68**（+12 = 接线新增的引用；`agent_b/core.py` 里 `ocr.` 现为 14 行）；
  ② `docs` 侧的 **+8 全部是本条目自己**（这一条本身就在讲 `ocr.`）⇒ **扣除本条后 39 → 39，无净变化** ——
  所以 `docs` 那一列**不能当接线效果的读数**，它只证明"文档侧没有因此多出/少掉别的引用"；
  ③ 本条目自身的 8 行是**同一口径下的行数**；它还会随这条被改写而变（**这个数只在本条定稿的那一刻成立**），
  所以引用本表时请连口径与时刻一起引；要现值就用上面那两条命令重跑；
  ④ 旧记的「44 → 53 处」口径不明，**本条目一律以本口径为准**；历史读数**不改成现值**
  （按主控判例：带日期、带口径的历史读数保留原样）。

---

## §1 八层与它们各自的文件

> **层号怎么对**：本文第 0 层是"入口"（`cli.py` / `webui/` / `web/` / `ui/` 等），第 1–7 层与
> [`DEVELOPMENT-SPEC.md`](DEVELOPMENT-SPEC.md) §2 的 ①–⑦ 逐层对应；那份规范里的第 ⑧ 层
> **Web / 用户端**就是本文第 0 层那三行（`webui/` / `web/` / `ui/`）。层数是 **八层**
> （`DEVELOPMENT-SPEC.md` §2 由 `draft/35` 的"七层"改为八层，那一份的分层表多出第 ⑧ 层）。

层与层之间是**单向**的：上层可以读下层，下层不反向 import 上层。
括号里是这个文件存在的理由（取自它自己的模块 docstring）。

### 第 0 层 · 入口

| 文件 | 是什么 |
|---|---|
| `cli.py` | 命令行入口（27 个子命令；`project`/`run`/`run-agent`/`verify`/`tools`/`web`/`doctor`/`cache`…） |
| `stop_reasons.py` | 停止理由的单一真身（Q23，2026-10-26）：`reason → (退出码, 徽标 class, 徽标文案, live)`。`cli.EXIT_CODE_BY_STOP` 只投影 `live=True`，`webui.server._STOP_BADGES` 投影全部（含只有徽标的旧读数 `max_steps`）；改前两张表各写一份，`final_refused` 只进了退出码表、`max_steps` 只在徽标表，两处错误恰好被 `len()` 比较抵消。判据 `tests/test_loop_liveness.py` |
| `webui/` | 用户端网页（包；2026-10-07 的 W0 从单文件模块一次拆到位）：`webui/state.py` 是**读模型**（`snapshot()`：全局待回答面板 + 运行态 + 一趟的事件回放，只读投影；待答与选项按裁定 L1 转发到 `userio`）、`webui/readers.py` 是**只读面**（`/api/state` · `/api/run/{sid}` · `/api/run/{sid}/events`（题 T2-a 的逐条事件：`index` 与 `run_view` 的 `start_index`/`end_index` 同一套编号，`since_index`/`limit` 游标分页） · `/api/evidence` · `/api/artifacts` · `/api/acceptance` · `/api/machine`，各带三态头）、`webui/sse.py` 是 `GET /api/stream` 的广播器 + 写路径钩子（`attach`/`detach`，谁开的代谁接 —— 生产路径在 `server.serve()`）、`webui/writes.py` 是唯一写路径（`POST /answer` → `userio.answer_question`）与它的写面、`webui/cacheface.py` 是两档提示词缓存的两条端点（`GET /api/cache` 只读读数 + `POST /api/cache/warm` 写：走同一套回环来源 / CSRF / `--allow-writes` / `confirm=1` 闸门，真预热起 detached 子进程）、`webui/routes.py` 是路由表 `ROUTES`（= `_OWN` + `readers.ROUTES` + `writes.ROUTES`）、`webui/server.py` 是 http.server + 静态路由 + 两条页面入口（`/` 与 `/run/{sid}`）的 SPA 外壳 + SPA 回退 + 服务器自己写的那几张错误页；服务端渲染的旧壳已在 W5 清仓（裁定 P1 的两面都迁到 SPA 外壳，那个文件整件退场）；公开面由 `webui/__init__.py` re-export（W5 收窄：旧壳的两个渲染入口随之退场） |
| `settings.py` | **机器级设置的一处定义**（2026-10-07 起）：落点（默认是 `agentflow/` 下的那份，被 git 忽略；`AGENTFLOW_SETTINGS` 指到别处）、键名（`toolchain.*` / `model.*` / `workspace.projects_dir`）与**唯一口径的优先级**（环境变量 > 设置文件 > 内置默认/自动探测，唯一实现 `env_or_setting`）。为什么要有它：本机路径与模型 key 此前散在"代码里的字面量 + 环境变量"两处 —— 换一台机器就有一句假话。判据 `tests/test_settings.py`（含"源码里 0 条死地址"与三道 key 安全阀） |
| `budget.py` | 可追加的总预算：盘上寄存器（工作区根下那一个 JSON）+ 每次花钱前现读的口子 —— 花销不在这里（唯一权威账是 `usage_ledger`） |
| `toolchain.py` | 这台机器上的证明工具链（一处定义）：显式配置（`AGENTFLOW_LEAN_BIN` 等）→ `AGENTFLOW_PROVER_PATH`（两者都是环境变量）→ **设置文件的 `toolchain.*`** → PATH 四档查找 + 三态探测 + Mathlib 那一轴；探测（禁改区的 `verify_tools.detect_verifier`）与调用（`formalgw.find_lean`）共用这一个答案，`agentflow doctor` 把读数打给人看（打的是"从哪一档找到的"） |
| `leantoolchain.py` | **Lean 工具链的开机自检**（业主 2026-10-22「防止用户提供虚构的lean环境」）：四步 —— 解析解释器（`--lean` > `AGENTFLOW_LEAN_BIN` > 设置文件 > `config.yaml` 的 `lean_path` > PATH）→ `lean --version` 要解析出 4.x 且与钉住的一致 → 最小正样例（`1 = 1`）必须过 → **反控（`1 = 2`）必须失败**。四档状态 `off` / `unknown` / `unusable` / `usable` 互不混；只读读数走 `lean_selfcheck_reading()`，`formal_evidence_state()` 是"防虚构环境"的落点（只有 `usable` 才允许把形式化证据记成 verified）。判据 `tests/test_lean_selfcheck_catches_a_fake_environment.py` |
| `web/` | 网页的样式与令牌：DSH 的令牌整份照搬（来源与 MIT 见 `docs/USER-END-DSH-STYLE.md`）；`web/assets.py` 是令牌的唯一真身（**我们自己的组件样式在 W5 随旧壳退场，搬到了前端工程的 `ui/src/theme/app.css`**）、`web/emit_theme.py` 把它生成到前端；`web/static/` 是**前端构建产物**（裁定 B1：入库；`index.html` + `assets/*.js|css`，`GET /` 与 `GET /run/{sid}` 吐的就是它） |
| `ui/` | 用户端前端工程（Preact + Vite，裁定 A2）：源码在 `ui/src/`（九页 `pages/*.tsx` · 九组件 `components/*.tsx`（2026-10-23 加 `PromptCache.tsx`：两档缓存面板 + 换 key 横幅）· `main.tsx` 路由 · `api.ts` 端点表 · `sse.ts` 订阅 · `live.tsx` 一次订阅分发给九页 · `theme/app.css`），其中 `ui/src/types.ts` 与 `ui/src/theme/generated/theme.css` 是生成物（`python -m agentflow.web.emit_types` / `python -m agentflow.web.emit_theme`，手改必红）；构建产物落到 `src/agentflow/web/static/` 并按裁定 B1 入库；开发说明见 `ui/README-DEV.md` |
| `__main__.py` | `python -m agentflow` 的入口 |
| `__init__.py` | 包说明与公开面 |
| `demo.py` | 离线端到端演示：不访问网络，把 A→B→校验整条链路真跑一遍 |
| `console.py` | 把 CLI 的输出编码钉在 UTF-8 上 —— 这一件事只有一份实现 |
| `tty.py` | 终端呈现层（统一、好看、在任何终端都不崩） |
| `userio.py` | 用户频道：向用户提问、等回答、"没答"这一档三态 |

### 第 1 层 · 数据面（磁盘契约）

| 文件 | 是什么 |
|---|---|
| `schema.py` | 数据模型与校验（**表的权威定义**；禁改区） |
| `store.py` | 共享存储：跨进程锁、原子写、事务、事件日志、ID 分配、重建（禁改区） |
| `canonical.py` | 规范 JSON 字节串 —— 唯一实现（判定"同一份数据"的前提） |
| `jsonlfile.py` | JSONL 文件的读法 —— 唯一实现（`draft/36` T-6：三处曾各写一份） |
| `sessions.py` | 按项目存放的会话记录 |
| `fulltextstore.py` | 抽取正文的内容寻址库：整本书的正文只存一份 |
| `signatures.py` | 稿件内容的规范哈希 |
| `vsigns.py` | V 签的侧文件（一稿一签）：`out/vsigns/<artifact_sha>.json` 按被签正文的 sha 命名，未达门槛一个字节都不写、已有就不覆盖；`issued.json` 是派生归档（原子 tmp+replace、`sort_keys`、按 `at` 排序 —— 只给人看，谁都不许拿它下结论）；回执与送达不落文件（读台账那一行）。D268 批 1（2026-11-10，只读、零行为翻转）在文件末尾追加了签的唯一读口：`sign_reading()`（八档 + `retry_report` + `body_state ∈ present|absent|unreadable`；正文取 `proof_text` / 手稿，**不**取 `statements.proof_text`）、`credential_reading()` / `_recomputable()`（文件在不算签：`passes` 必须在锚点那本台账上点出 `need` 行、同 `review_call`、`review_pass` 1..need、sha 相符、`row_signable`；老形态按锚点往前数）、票只数 `verifications.is_a_vote`；配套只读 CLI `scripts/sign_audit.py`（signed / unissued / unbacked / borrowed / view_conflict / legacy_clean_only / 不可复算签文件七张表，不写盘）。D268 批 2 已接线：`bits_after_sign` / `sign_filing_reading` / B 的两条旁路 / 秘书门 / 收工门 / F 的交付读数全部改读它；网页新增 `recomputable_signs`（`sign_files` 原名保留一个批次）。判据 `tests/test_sign_reading.py` 与 `tests/test_signing_never_lies.py` 的第 7 条（N1） |
| `proofauthors.py` | **「谁写的这份证明」的唯一读数**（业主 2026-11-01 裁定）：`author_reading` 三态（`checked` / `author` / `source` / `reason`）—— 先认调用方显式交的 `proof_authors`，再按登记时读到的来源路径推（`reports/` ⇒ F、`out/paper/` ⇒ G、`documents/` ⇒ B）；读不出来就记「作者未记录」，不许默认成 B、也不许默认成送审者。`recorded` 把读数变成写进 `statements` 行的 `proof_authors`（只加数据：不改 `bits`、不改收录行为、不改 `created_by`）。**谁用**：登记口 `secretary.record_statement`（B 的写入代理）写它，V 回执的投递口 `vreceipts._author_of` 读它判「送审者该不该是这个人」（"F 写的证明 F 送审、B 侧收录"）。判据 `tests/test_b_records_the_proof_author.py` |
| `vreceipts.py` | **V 回执的投递**（167 的丙案，业主 2026-11-01）：先落意图再开板项 —— ① 追加 `out/vreceipts/outbox.jsonl`（append-only，pending）→ ② 开板项（幂等键 = `v-verdict@<label>@<vid>@<recipient>`）→ ③ 记 `dispatched` / `undelivered`，整段在**同一把跨进程锁**里（`tasks.input_key` 没有唯一约束，锁是唯一的并发保证）。收件人只有一个来源：`conductor.current_parent()`（这一趟召唤的父 = 送审者），读不到就记 `undelivered`，不拿"谁醒着"当收件人。`backfill` 是收工前的补投（81 的老 8 条按「台账号时间窗唯一」重解析），`outbox_index` / `outbox_digest` 是读口；`dispatched`（有板项）与 `delivered`（收件人真读过）分成两个数。**谁用**：`agent_v/core.py` 的 `_publish_receipt`（判完就投）与 `conductor.closing`（收工前补投）。判据 `tests/test_v_receipt_delivery_does_not_wait_for_the_recipient.py` |
| `proofloc.py` | `dependencies.used_by` 里那个 `#pN` 尾巴的**唯一解析点**（业主 2026-10-22 多证明模型）：`used_by_of` 造尾巴、`parse_used_by` / `parse_used_by_checked` 拆尾巴、`proof_nos_of` 取一组。全仓别的模块要拆这个尾巴就调它 —— 两份解析意味着"台账上是第 2 条、读出来是第 1 条"这种错没有任何东西会报（口径由 `tests/test_proofloc_parses_proof_positions.py` 逐条钉住） |
| `statementbody.py` | **命题正文的唯一真身**（D2，业主 2026-10-22）：`statement_full` 是真身、`statement_text` 是派生的短版 —— 改前 13 条命题的 `statement_text` 全是 0 长度而 `statement_full` 有正文，于是 `closing` / `agent_v` / `webui` 三处各读一格、给出三种答案。取值理由（`Statement.validate` 要求真身非空 / 写入侧只有它必填 / 下游靠它做事 / 老数据只有它）写在模块 docstring 里；本模块是"读哪一格"这一句话的唯一定义点 |
| `statementabandon.py` | **「放弃原命题」的那条标记的唯一实现**（业主 2026-11-01：「每个命题和证明的产出最终必须以 V 签收尾，拿不到 V 签就得一直改，或者放弃原命题」）：`abandon_marker` 拼 `abandoned@<ISO8601>@<理由>`、`parse_abandon` 解析（三态：没标 / 标了读得懂 / 标了读不懂）、`apply_abandonment` 是写口（改状态 + 落理由与时间 + 作废重送义务）。标记住在 `quote_reason` 而不新增列（新增列就是改磁盘契约，属 FC-27 的 schema 迁移）；`schema.Statement.validate` 与 `closing` 的两格读数都从这里取 —— 两份正则会让"什么算明确放弃"在两个出口长出两种答案。判据 `tests/test_statements_unsigned_and_resubmit.py`（③ 明确放弃 ⇒ 进 `statements_abandoned`、不出现在 `statements_unsigned`） |

### 第 2 层 · 声明面（"谁能做什么"的权威定义）

| 文件 | 是什么 |
|---|---|
| `capabilities.py` | 角色能力表 + 写集 + 允许的召唤边（**A–H 调用矩阵的权威定义**；禁改区） |
| `agentspec.py` | **一个 agent 的声明**（`AgentSpec`/`AgentBrief` + 注册表）：职责与门面、官能轻重、只读与否、能召唤谁、写集、实现类。每个角色在自己的模块里写一份 `SPEC`；装配面正在从它读（`goal-7f5116c1` 的 M2/M3/M4，对账判据见 `tests/test_agent_spec_reconciliation.py`） |
| `leanscope.py` | **Lean 开关下 L 的可见性唯一判定入口**（业主 2026-10-22「在Lean开关没开时隔绝L」）：`lean_reading()` 读 `settings.lean_enabled()`（开关梯子只有那一份），`is_hidden` / `visible_roles` / `require_visible` / `hidden_refusal` 是其余每一处（角色表 / 工具装配 / 提示词 / 按名取角色）唯一允许的调法 —— 关着时 L 不是"跑不动"，是"不存在"（按名取它的入口给受控拒绝 `lean_off`）。`LEAN_ONLY_ROLES` / `LEAN_ONLY_TOOL_MODULES` 是"这一档下没有谁"的规则本身（判据 `tests/test_lean_switch.py`） |
| `specs/<角色>.py` | **角色动作表的真身**（`goal-7f5116c1` M3）：一个角色一个文件，`ACTIONS`（动作表，逐条 `ActionSpec`）+ `SPEC`（职责与门面、官能轻重、边、写集、实现类）。`capabilities.py` 的四张表**从它派生**，`agent_<角色>.py` 只是再导出 —— 这一包在 `.noai-paths` 里受保护（改它等于改权限面） |
| `policy.py` | 策略层：允许哪些召唤、四类上限 |
| `interactions.py` | 跨智能体交互的冻结契约（I1–I7）（禁改区） |
| `verify.py` | 全局不变量校验（表与表之间的一致性；禁改区） |
| `gates.py` | H 的 G1–G15 门引擎 —— 15 道独立、有名字、可单独查询的检查器 |
| `stopctl.py` | 停机的唯一实现（`draft/37` §128）：停机开关（`.agentflow-stop`）+ 子进程登记（`runs/<role>-<sid>.pid`）+ 优雅停止与强制停止（`taskkill /T /F` 连子孙）。为什么要它："用户叫停"这条通道此前只在多轮路径存在 —— 单趟 `run-agent` 里叫停之后它继续跑到第 123 步；而 E 的实验子进程会把 600 s 跑满（开关落盘后 0.2 s 内被终止） |
| `refusals.py` | 角色动作的「拒绝」只有一个形态（`draft/37` §88）：`refuse(kind, error, **extra)` 造出 `ok=False` + 受控 `refusal_reason` 的那一笔。为什么要它：终态映射原先只看"handler 有没有返回 dict"，于是 `ok=False` 被记成 `outcome=ok`（T1 第 2 趟真机：8 次拒绝在台账上像 8 次成功，而 `statements` 是 0 行）—— 现在声明了受控理由的落 `refused`，没声明的落 `failed`，两者不再同形 |
| `manuscripts.py` | **交接手稿**的唯一实现（`draft/37` §134 用户口径 + `draft/39` §C1 存储改追加式）：账本 `handoffs.jsonl`（在 `manuscripts/` 下）**一行一份交接**（`to`/`summary`/`body` 必填），编号从 `0000` 起**由脚本在锁内分配**（扫"账本行 + 旧 `.md` 文件"的并集），并发写不撞号不覆盖；旧格式 `<编号>-<谁>to<谁>.md`（给所有人写 `toALL`）仍然读得回来但不算账本行。为什么要它：交接的"派活依据"与"溯源"此前只活在对话里 —— 写了手稿之后每一跳都能被第三方从盘上复核。写走循环形状 `handoff`（要知道"我是谁"，而工具层拿不到 per-call 身份），收工时的强制 `notify` 表也走它；读/列走 `tools/manuscript_tools.py`（A–H 八面，M 用 `fs.*` 白名单读同一批文件），按编号/收发/时间/引用检索走 `scripts/manuscripts_query.py`（顺手打被引用命题的五元位快照） |
| `bmanuscript.py` | **B 的改写手稿：可签的载体**（业主 2026-11-04 裁定 A 甲「B 的改写要有可签的载体」）：B 改写在册证明时，正文与在册那一版不同 ⇒ 旧签读成 stale、台账行也盖不住新正文；`AgentB.register_statement` 把 B 交上来的正文渲染成 `reports/b-proof-<命题号>.md`（与 F / E 同形：`## 命题` / `## 证明` / `## 依赖` 三节），V 读这一份、三转成立后由收方秘书（`secretary:B`）把签块落回稿里，B 再带这份稿入库 ⇒ `vsigns.manuscript_sign_standing` 读到「签到位」。写侧读数三档：`written` / `preserved+signed`（目标稿已是同一份正文的已签版，一个字节都不动）/ `problem`（目标稿已签而这一笔是另一份正文 ⇒ 不覆盖、把冲突留在读数里）。B 没有文件写口，稿由框架在登记入口落盘。判据 `tests/test_b_rewrite_manuscript_gets_signed.py` |
| `manuscriptform.py` | **证明手稿的唯一实现（F 的 `reports/f-proof-<号>.md` 与 B 的 `reports/b-proof-<号>.md` 共用）**（业主 2026-11-04「两族在形式上必须完全统一」）：命名（`<prefix>-proof-<号>[-p<N>].md`，解析只走 `vsigns.parse_manuscript_name`）、渲染（`## 命题` / `## 证明` / `## 依赖` 三节同一段代码，前缀与角色名只是参数）、搬签块（`carry_sign_block` 按 sha 相符才搬、第 9 格手稿号按新名重算）、落盘事务（写稿 + `## 依赖` 段 + `dependencies` 边同成功同失败，落边失败把刚写的稿回滚）、拒信码（`multiple_propositions` / `not_washed` / `bad_manuscript_name` / `no_proof_section` / `dependency_section_missing`）全部只在这里定义一次。两个转发壳：`agent_f/manuscript.py`（F 侧）与 `bmanuscript.py`（B 侧）不另写一份；落盘事务那三件零件 2026-11-11 搬到 `manuscriptwrite.py`（本行讲的"落盘事务"仍是它调的那一段）。判据 `tests/test_f_and_b_manuscripts_are_one_implementation.py` |
| `manuscriptwrite.py` | **手稿落盘事务的三件零件**（2026-11-11 从 `manuscriptform.py` 拆出，体量软基线不抬）：`_atomic_write`（同目录临时文件 + `os.replace`，读侧要么看到旧文件、要么看到新文件）、`_refusal`（落盘事务受控拒绝的返回形状：`ok=False` + `refused` + `problem{kind, stage, why}`）、`_signed_version_reading`（目标名上签住的是不是另一份正文；读不出来时 `checked=False, blocked=True` —— 「没查成」不折成「没签」）。三件都只被 `manuscriptform.commit_manuscript` 调用；`manuscriptform` 回引它们，所以 `manuscriptform._atomic_write` 这个既有名字（`proofregistry` 也在用）照旧可读。判据 `tests/test_f_and_b_manuscripts_are_one_implementation.py` |
| `proofregistry.py` | **手稿登记与重写的唯一入口**（业主 2026-11-07：「要让注册命题和写证明两件事解耦，不然无法做到只一遍又一遍修改证明」）：`register_or_rewrite` 决定"新命题登记一次 / 同一条命题只换 `## 证明`"（新命题过 F 秘书形态闸、`proof_no` 递增、正文 sha 重算、版本 append-only）；`parse_entry` 读稿头登记元信息（命题号 / 正文 sha / 命题指纹 / 命题类型 / 登记时间 / `- 版本：`）—— 「命题类型」那一行 2026-11-14 前叫 `- 证据种类：`（名字借了**证据档位**那根轴的词），老盘旧名照读、写侧只写 `- 命题类型：`（字面量与交叉核对的口径在 `manuscriptkind.py`，本模块只回引 `kind_crosscheck` 这个名字）；`same_slot_reading` 是"这一笔是不是同一条命题的槽"的判据（命题号 → 计划+子目标 → 标签，且必须有登记元信息 —— 手写带 `- 标签：` 的头不算）；`entries_on_disk` / `proof_revisions` 是收工读数（2026-11-11 搬到 `proofrevisions.py`）。路径由 `manuscriptform.name_reading` 定，身份由本模块定，合起来是「一份命题只住一份稿」的全部实现。判据 `tests/test_proof_registration_is_decoupled.py` |
| `manuscriptkind.py` | **命题类型那一轴（2026-11-14 解耦）**：`PROPOSITION_KIND_MARK`（`- 命题类型：`）与 `LEGACY_PROPOSITION_KIND_MARK`（老盘 `- 证据种类：`，只读兼容）是稿头那一行字面量的唯一权威来源（写侧与两个读侧都从这里取）；`kind_crosscheck` 是「台账 `statements.kind` 为准、稿头声明只作交叉核对」的唯一实现（`agree` / `mismatch` / `manuscript_absent` / `ledger_absent` 四档，不一致给 `kind_crosscheck_mismatch` 读数，不静默取其一）；`extract_kind` / `plan_kind` / `KIND_RANK` 是收录那一格的两个纯函数与词表（2026-11-14 为不抬 `manuscriptintake.py` 的 800 行软基线整块搬出；`manuscriptintake` 仍转调同一份实现）。判据 `tests/test_kind_and_grade_axes_are_decoupled.py` |
| `proofrevisions.py` | **手稿登记条目的收工读数**（2026-11-11 从 `proofregistry.py` 拆出，体量软基线不抬；本模块不写盘）：`entries_on_disk`（扫 `reports/` 下两族的稿，逐份给 `parse_entry` 的登记条目）、`proof_revisions`（「登记几次 / 证明几版」：`registrations` / `proof_versions` / 逐条的 `versions` 与形态闸拒收数；读不出来 `checked=False` 且 `reason` 说「没查成」，不折成零）、`registration_note`（提示词里「登记新命题 / 重写证明」那一句的唯一出处）。写入口仍住 `proofregistry`，两处共用同一份 `parse_entry`（不重写第二套解析）；`proofregistry` 回引它们，既有名字照旧可读。判据 `tests/test_proof_registration_is_decoupled.py` |
| `proofoutcomes.py` | **登记 / 重写两档的结局读数**（2026-11-11 从 `proofregistry.py` 拆出，体量软基线不抬；本模块不碰稿件字节、不写盘）：`form_gate_reading`（新命题登记前跑一次 F 秘书的形态闸：放行 / 受控拒 / 闸自己炸了 fail-closed —— 三态同一形状）/ `preserved_reading`（同一份正文再挂一次 ⇒ 一个字节不动、`preserved=True`）/ `REFUSED_*` 六个受控码也在这里定义。`proofregistry` 顶层回引它们（公开名与受控码字符串一个字没变）。判据 `tests/test_proof_registration_is_decoupled.py` |
| `manuscriptfamily.py` | **手稿族 / 号 / 后缀的唯一判定表**（T2，2026-11-09，纯函数零 I/O）：`FAMILY_ORDER` 四族（`f-proof` / `b-proof` / `e-proof` / `e-num`）、每族的目录 / 号形 / 证明号后缀 / 要不要签 / 允许格 / 派生列 / `evidence_kind` / `kind` 缺省 / 出处收成一张表；`tier` 把"这是哪一族"读成 `family` / `legacy` / `bad_name` / `unrecognized` 四档（`-v2` 一类历史后缀只读成 `legacy`、`proof_no` 恒 0）。**2026-11-09 收编后**：`vsigns` 的名字解析与签载体、`manuscriptform` 的前缀、`depsection` 的族前缀、`exhaustionreport` 的两个前缀、`vreceipts` 的载体表、`closing` 与 `agent_v` 的拼名、B 登记口的族判定都从它派生，不再各写一份字面量。判据 `tests/test_manuscript_family_is_one_table.py` |
| `manuscriptids.py` | **F 的稿号分配器**（p272，2026-11-10，业主裁定「F 的稿自己维护一套号源，不依赖命题号和计划号」）：`next_manuscript_id(root)` 从 `data/counters.json` 的 `manuscript` 号段取下一个号、在 `reports/f-proof-<号>.md` 上核占用（已存在 ⇒ 推进，绝不覆盖）、同一进程内串行、六位用尽受控抛 `ManuscriptIdError`。三个号各管一件事：稿号是**签的单位**（F 自己发）、计划号管去留、命题号 B 收录时现取。判据 `tests/test_f_manuscript_ids_are_its_own_source.py` |
| `manuscriptintake.py` | **手稿的逐格提取**（T1 的提取侧，2026-11-09，纯函数零 I/O）：输入（稿正文 + 族 + 要填的格），输出逐格 `{outcome, source{section,lines,sha}, value, why}`；三态 `present` / `absent` / `unreadable` 与 D4 同一口径（缺节不拿别的节顶替）；`plan_cells` 是逐格冲突矩阵（`filled` / `unchanged` / `kept` / `refused` / `not_applicable`）外加 `diff`（请求了没填 / 填了没请求）与 `derived_write`。写台账与认签不在这一层（接线后归 `Secretary.extract_manuscript` / `own.ingest_manuscript`）。判据 `tests/test_manuscript_intake_extracts_by_cell.py` |
| `conjectureledger.py` | **猜想台账的唯一写点**（业主 2026-11-13 裁定「D 不该立项临时命题」）：`register()`（D13 判重 / `None`=没提 / `Conjecture.validate` / 跨对象存在性）由 E 的 `run_experiment`、F 的 `_open_manuscript`、B 的 `register_statement` / `ingest_manuscript` 三处各调一次；另三个读数 `status_for_experiment` / `mark_refuted` / `promoted_to_statement`。D 侧没有写口（只读） |
| `errorstate.py` | **台账命题「错误」与等级「错误」的唯一读口**（业主 2026-11-13 裁定「两处读法必须恒等」）：`statement_refuted`（台账命题三态：是 / 不是 / 读不出来）与 `conjecture_refuted`（临时命题三态），外加双读过渡的两个常量 —— `status=错误 ⇔ 等级=错误` 这句判据只在这里变成机器读数 |
| `statementrefute.py` | **命题的另外两个终态**（业主 2026-11-13 裁定）：`refuted`（标记为错误：三选一证据 + 名下那份稿一并作废）与「优化栏 = 难以自证」（status 不动、只写 `hard_to_prove`、稿不动）。已有的作废载荷在 `evidencebits`，本模块是它唯一的合法生产调用者 |
| `refutation.py` | **证伪通道（库层）**：把一份 V 签过的「证伪论证」翻译成被证伪命题的「证伪签」—— 输入只有两样（锁定命题号的证伪稿 + 它的 V 签），error 等级由证伪签算、证伪签在则否决其它等级 |
| `manuscriptopen.py` | **开稿口（三族共用）**（业主 2026-11-13 裁定「统一 B、E、F 注册稿和写稿的流程」）：写命题 → 命题形式过审（`Secretary.judge_proposition_form`，按正文 sha 缓存）→ 拿稿号 → 写稿（`ROLE_FAMILIES` 定族，稿允许慢慢 edit）四步的唯一入口 |
| `manuscriptretire.py` | **「命题退休 ⇒ 它名下那份稿一并作废」的唯一判据**（业主 2026-11-13 裁定）：1:1 是每族各自的 1:1（f-稿 / e-稿 / b-稿三族稿号可互不相同，与 `manuscriptopen.ROLE_FAMILIES` 同一条角色-族绑定） |

### 第 3 层 · 工具面（角色手上的"手与眼"）

| 文件 | 是什么 |
|---|---|
| `tools/__init__.py` | 工具层装配（按角色组装 `ToolRegistry`；禁改区） |
| `tools/base.py` | 工具层基座：`ToolSpec`/`ToolResult`/`ToolRegistry`/参数校验（禁改区） |
| `tools/table_tools.py` | 表 CRUD（共用数据面原子动作） |
| `tools/fs_tools.py` | 文件 CRUD（共用，沙箱在工作区内） |
| `tools/search_tools.py` | A 专用：provider 探测 / 检索 / 下载 / 判重检查 / 文献登记 |
| `litstage.py` | **待新增文献列表的判据真身**（业主 2026-10-20；不在 `tools/` 下，但工具层是它的手）：条数上限（`MAX_ADMIT_PER_CALL` / `MAX_ADMIT_PER_DELEGATION`）、重叠口径（`OVERLAP_HIGH_JACCARD` / `OVERLAP_KINDS`）、状态机（`schema.CANDIDATE_STATUSES`）、筛选理由码、报告两块结构只有这一处；`tools/search_tools.py` 的四件 `lit.*` 只把它的结论翻成 `ToolResult`（不重新判一遍） |
| `tools/ocr_tools.py` | B 专用：后端探测 / 文本层判断 / 按页 OCR |
| `tools/graph_tools.py` | 图索引与查询（纯读） |
| `tools/trace_tools.py` | 代号溯源（纯读） |
| `agenttrace.py` | **父子链的只读追踪**（业主 2026-10-24：「普通代理能追一层，M能想追几层追几层」）：`children_with_facts` 给"我直接下级"的行为读数（非 M 角色的深度由 `clamp_depth` 钉成 1，返回值里带 `deeper` 逐字写"更深要看请向 M 请求"）、`watch_rows` 沿 `parent_task_id` 向下走全树给 M、`node_facts` 汇四格读数（状态 / 最近 N 步 / 被拒类目 / 产出是否落盘）。一层工具 `trace.children` 与全树工具 `conductor.watch` 共用这一份读侧；本模块不注册工具、不写盘 |
| `tools/clock_tools.py` | **时钟的原生工具面**（D-53，业主 2026-10-24/25）：`clock.*` 九件 —— 读数 `clock.now`、一次性计时 `clock.timer_start`、闹钟 `clock.alarm_start`、补目的 `clock.timer_purpose`、看表 / 等谁 / 记等待 / 取消各一件；所有角色都能用，到点同时落 mailbox 项与唤醒标记。申请形状只认两半：`after_sec`（或 `at`）与 `wait_for` 二选一 + 一句目的（目的缺了只追问、不打回）。实现全在 `clock.py`，本文件只做工具面；判据 `tests/test_clock_governs_all_timed_work.py` |
| `tools/text_tools.py` | A 专用：`text.extract`（读 PDF 自带的文字层、写 `library/<编号>.txt`；2026-10-17 新增，原 PDF 原样保留、写盘前核质量） |
| `tools/analysis_tools.py` | C 的**产出登记通道**（业主 2026-10-18 裁定「只读角色的产出要能进台账」）：唯一一件工具 `analysis.register_report`，`roles=("C",)` —— 把这一趟 C **自己算出来的**分析经 `agent_c._support.AnalysisReport.persist` 落成 `analysis_reports` 一行（存盘顺序、发号、文件名都还是那一份实现，这里不重写），`kind` 取 `schema.REPORT_KINDS`，`markdown` 写正文与边界。**为什么要有它**：C 的十个动作（`gaps`/`handle`/`paths`/`cold`/`hottest`/`neighbors`/`relations_between`/`contradictions`/`structural_duplicates`/`proof_chain`）只能由父代理 `summon` 唤起，空动作的自由任务里 C 手上一件写工具都没有 ⇒ `analysis_reports` 恒 0、图读数只活在回复里（`projects/mp3` 末节第 5 条）。**边界**：只写 `analysis_reports`（`capabilities.TOOL_WRITE_SETS` 与实现 AST 逐格比对，不碰 `claims`/`literature`/`relations`；`_not_wired` 如实失败、绝不返回假 `report_id`）。**谁读它**：D 的 `write_report` 路径按 `report_id` 回读（`agent_d/core.py`）、`pipeline.py` 的 replay 分支、`closing.py` 的 `analysis_report_rows` 那一档、`verify.py` 的 `report_file_missing`。判据 `tests/test_readonly_output_channel.py` + `tests/test_tools_returns_declaration.py` |
| `ledgerindex.py` | **C 的关系推断索引**（`draft/181` 的 A 批，2026-11-10）：只读快照一次建好、**不进上下文** —— 节点表（`stmt_id → kind/status/grade/label/statement_full/proof_no`）+ 正邻接（`source_stmt_id → used_by`，依赖面）+ 反邻接（`used_by → source_stmt_id`，被引面）+ 外部根读数（`doc:` / `relation:` / `experiment:` 与 `source_lit_id` / `source_experiment_id` / `source_doc_id` 三种来源不入节点）。`expand` 给局部树（七样字段、依赖面全路径按证明路径分组、被引面一层、有界 `truncated` / `budget_used`、无句柄增量 `added_nodes` / `already_known`）；概念行与命题**平权**（不读 `relations` 表、不开特例分支）；`LedgerHolder` 与 `_GraphHolder` 同形（可外部传入已建索引）。按面读的那一半（`dependency_face` / `cited_face` / `expand`）2026-11-11 搬到 `ledgerface.py`，索引与邻接仍只在这里建。判据 `tests/test_the_ledger_tree_is_expanded_on_demand.py` |
| `ledgerface.py` | **台账索引的三种读法**（2026-11-11 从 `ledgerindex.py` 拆出，体量软基线不抬）：`dependency_face`（依赖面全路径、按证明路径分组）、`cited_face`（被引面一层）、`expand`（`ledger.expand` 的局部树：七样字段、有界 `truncated` / `budget_used`、无句柄增量 `added_nodes` / `already_known`）。入参是一个已建好的 `ledgerindex.LedgerIndex` —— 索引与双向邻接仍只建一份；`LedgerIndex.dependency_face` / `cited_face` / `expand` 转发到这里。判据 `tests/test_the_ledger_tree_is_expanded_on_demand.py` |
| `tools/ledger_tools.py` | C 的两件关系推断工具（`draft/181` 的 B 批）：`ledger.resolve`（选根：候选五格，**不是树**；按号 / 按标签走 `statementledger` 既有的两条口径）与 `ledger.expand`（`depth` **必填**、由 C 决定 —— 不填 ⇒ 缺参数提示并给可照抄例子；`direction` up / down / both；`roles=("C",)`）。工具体只做参数判据，索引与树在 `ledgerindex.py` |
| `tools/research_tools.py` | D 专用：研究问题台账 + 知识缺口提问 |
| `tools/verify_tools.py` | E 的工具：数值实验与形式化验证（禁改区） |
| `tools/attack_tools.py` | F 的工具：多轮难题攻坚 |
| `tools/doc_tools.py` | G 的工具：论文撰写 |
| `tools/review_tools.py` | H 的工具：审校（`review.scan` 的工具体在这里；判据与口径在 `texaudit.py`） |
| `texaudit.py` | **论文正文的机械扫描**（业主 2026-11-01「将 H 的所有机械扫描工具统一成一个」）：`scan_tex()` 是七类（`text_integrity` / `cites` / `inputs` / `refs` / `proofs` / `duplicates` / `ledger_match`）的唯一实现，返回八键（`checked` / `kinds` / `findings` / `counts` / `bad` / `detail` / `scanned` / `reason`）；`findings[]` 九键恒定（不适用给如实空值），逐类三态在 `detail[]`。口径从这里只能读出一份：引用命令是六个（只认 `\ref` 会静默漏报悬空 `\eqref`），没被引用过的标签只进 `facts.unused_labels`（真稿 703 个标签里 229 个没被引，报出来就是 229 条假阳性），`ledger_match` 只回五个数 + `statement_surplus` 而不发明"proof 环境数 == 台账定理类数"。判据 `tests/test_texaudit.py` |
| `tools/conductor_tools.py` | 主控工具：给 M 配手与眼（派活 / 台账 / 停止 / 状态） |
| `tools/cache_tools.py` | **两档提示词缓存的两件工具**（业主 2026-10-23）：`cache.status`（只读：两档 × 四格读数 + 换 key 提醒）与 `cache.warm`（写 + 起子进程：真预热一档，`dry_run` 缺省）—— `roles=("M",)`，A–H/V/L 一个都拿不到。实现转发到 `cachectl.py`（本文件不另算一份）；没挂进 `tools._MODULES` 是合并点的交代，见该文件 docstring 与施工报告 |
| `tools/formal_tools.py` | **L 的三件工具**（业主 2026-10-22）：`formal.formalize` / `formal.check_formal` / `formal.record`，`roles` 只有 L（`_ROLES_L`），副作用与外部性两根轴逐条声明；handler 惰性构造 `agent_l.AgentL`（与 E 的 `verify_tools` 同一个形状）。它是 L 的**写权限面落点之一**（`record` 会写 `experiments` 一行）—— 少一个字母就等于把形式化入口漏给别的角色，而工具层不会报错，它只会"成功"。判据 `tests/test_l_formalizes_what_b_says.py` |

### 第 4 层 · 角色面（十个角色各自的一本账）

| 文件 | 是什么 |
|---|---|
| `agent_a/`（包） | A：文献搜索（唯一带网络副作用的角色）；`goal-7f5116c1` M7 起：一个动作一个文件 |
| `agent_b/`（包） | B：文献整理（抽取概念与关系，引文逐字回验）；M7 起同上 |
| `agent_c/`（包） | C：关系分析（程序做分析，LLM 只做排序与措辞） |
| `agent_d/`（包） | D：研究循环（**最大的角色**，见 §3） |
| `agent_e/`（包） | E：数值实验与形式化验证 |
| `agent_f/`（包） | F：多轮难题攻坚 |
| `agent_g/`（包） | G：论文撰写 |
| `agent_h/`（包） | H：审校（只读） |
| `agent_v/`（包） | V：**证明级验证**（只读，`draft/39` §3.21 一/五/六）：把 F 交回来的证明按写成后的样子整体重读，给三态结论（`成立`/`有毛病`/`看不出来`）并签五元位第 3 位；`agent_v/core.py` 的 `AgentV`（三个动作：`verify_proof`/`list_verifications`/`read_proof`）+ `agent_v/__main__.py` 的自检入口（`python -m agentflow.agent_v`，17 条 `[PASS]`）。声明真身在 `specs/v.py`，读写在 `verifications.py`。未在册穷举那一支（2026-11-09 拆函数）：`_review_unregistered_exhaustion` 只做编排，读稿/比对在 `_read_unregistered_exhaustion_ctx`、判定分支（pending + 颁发/落签 + 返回值）在 `_finish_unregistered_exhaustion`，三轮机械会审在 `_review_exhaustion_rounds` |
| `agent_l/`（包） | L：**Lean 形式化者**（2026-10-22 新设，照 E 的 Lean 面复制出来的可运行角色）：三个动作 `formalize` / `check_formal` / `record` 各一个文件 + `agent_l/report.py`（L→B 的受控汇报）+ core + _support + `__main__`。E 的代码一行没删、行为没改（复用它的 `_CheckFormal` 与 `verify.check_formal` 桥接层），L 只在前者前面加一道 Lean 自检闸；协作面只有 `B → L` 入边与 `L → C` 出边，声明真身在 `specs/l.py`。开关关着时它整条不存在（见 `leanscope.py`）。判据 `tests/test_l_formalizes_what_b_says.py`、`tests/test_l_collab_and_secretary.py` |

> 十个角色（除主控 M；2026-10-22 起的 L 与它们同形）的包形状是一样的（`goal-7f5116c1` M6/M7 + F-02 的 V）：入口 `__init__.py`、
> 其余成员与 mixin 组装在 `agent_a/core.py` 这样的 core 模块里、模块级 helper 与常量在
> `agent_a/_support.py`、一个动作一个文件（如 `agent_a/search_literature.py`）、
> `python -m agentflow.agent_a` 的自检入口在同目录的 `agent_a/__main__.py`。
| `agents` 的公共零件：`claimanatomy.py` | 断言解剖学 —— `documents.claims` 每个元素的唯一判据来源 |
| `claims.py` | 原子断言拆分（把一段答复切成可逐条回验的断言） |
| `statementledger.py` | **命题台账的查口**（只读、零模型、不写盘、不开事务）：两种口径分开 —— `by_id`（按编号：主键逐字相等、不过滤 status/kind；0 命中 = 确定性事实）与 `by_keywords`（按内容：`label`/`statement_full` 经 `textutil.normalize` 后包含任一关键词；0 命中 ≠ 不在册）；底座 `rows_of`/`pool`/`index_by_id`/`duplicate_hits` 各一份，池与常量由调用方传（命题池与概念行池过滤条件不同，不焊死在查里）。2026-11-09 把全仓 62 处"自己扫全表拿一行/建索引"收成这 5 个入口（判据 `tests/test_the_statement_ledger_has_two_ways_to_be_asked.py`）；同日晚第 4 步把 C/L/V 的三个库模块/B/D/F 的台账读点也接到这组入口（角色侧 `rows("statements")` 27 → 0，判据 `tests/test_each_role_queries_the_statement_ledger.py` 的「只给一种输入 + 反真空」）；`table.get` 仍是通用按号取行；`table.search` 在 `statements` 上已与这里**同一把尺**（2026-11-09 起：只搜 `label` / `statement_full`，判据是同一份 `textutil.matched_keywords`），其它表仍是通用列文本搜（`casefold`、全部标量字符串字段）—— 判据 `tests/test_the_two_rulers_agree_on_the_ledger.py`。**2026-11-10 加被引面读数 `cited_by`**（业主：「在命题台账加被引面读数…把命题号打进各依赖面的被引面，是自动维护」）：它不是第三种"在 `statements` 里找行"的口径，而是 `dependencies` 的反向投影 —— `source_stmt_id == 这一条` 的那些行，逐条给 `used_by` / `citer_stmt_id` / `proof_no` / `kind` / `label` / `status` / `created_at` / `path_group`，外加 `by_status`（依赖行状态计数）与 `citers`（`used_by` 去重集合）；`found` 是三态（int / 0 / `None`，读不到 ≠ 没人引）。`rows_of` 加 `table=`（默认 `statements`）让依赖账走同一份取数口；写侧一个字没动（B 登记先拿号、再按那个号写 `used_by`）。判据 `tests/test_the_cited_face_is_read_from_the_dependency_ledger.py`（正控 / 多引用 / 三态 / 两条反真空 / concept 负控） |
| `propositionkey.py` | **命题同一性与同种证明的判据**（纯函数、确定性、零模型调用；2026-10-24 业主改口径：「不用机械判据，让秘书洗定理名，让秘书判」+ 准绳「定理描述一致（什么条件推出什么结论），就是一个定理」）：本模块只在终判的上游做两件事 —— `judgeable`（够不够格当一条命题）与 `proposition_key` / `prose_similarity`（同一性的候选读数）；终判在 `secretary.Secretary.adjudicate_proposition`（一次模型调用，二档 same / different，判不了 = 没判成，按正文 sha256 缓存） |
| `propositionrewrite.py` | **未入册命题的 `## 命题` 原位重写的唯一写口**（W2·甲，2026-11-13，业主问 2 选 a）：`rewrite_proposition` 三条边界缺一不许 —— ① 只在"这份稿还没被收进 statements"时允许（按稿号 / 逐路径记录 / 命题指纹三处判，任一命中即拒 `proposition_already_registered`）；② 改后必须过语义同一性判定（复用 `proposition_identity` 轴，判不了 ⇒ `proposition_identity_unjudged`，没有文字相似度兜底）；③ 受控写口不开冻结面的洞：只换 `## 命题` 与稿头命题指纹，`## 证明` 的正文 sha 落盘前先核一次（变了整笔不写），三句声明进读数。判据 `tests/test_f_proposition_rewrite_port.py`（a–f） |
| `jobobject.py` | 进程树治理（`draft/39` §3.21 五 I13，D03 的根因修法）：Windows **作业对象**（`KILL_ON_JOB_CLOSE`）—— `create_job`/`assign`/`assign_tree`（根 + 现有后代；作业归属**不向前追溯**）/ `grace_then_kill`（先宽限再 `TerminateJobObject`）/ `reap`/`close`；后代枚举走 Toolhelp 快照。`stopctl` 的强制停止优先走它（`via="job"`），`taskkill` 只作退路 |
| `attackround.py` | F 的**一轮真推理**形态（`draft/39` §3.16）：四种产物 `reduction`/`proof`/`counterexample_request`/`dead_end`（**没有 `no_change`**）、策略工具箱（每轮必填方法与理由）、#5 缝的两条合法出口（写出来 / 声明成前提）、花钱前的确定性闸门（I9）、缺陷继承（I11）、超预算的 `too_large`（I16） |
| `statusreport.py` | M 的**状态报告**（`draft/39` §4）：`collect()` **只读**四类读数（台账增量 / 交接链 / 在飞与卡点 / 拒绝与超时），`render_status_markdown()` 渲染成人读四节，`write_status_report()` 落 `out/review/STATUS-<ts>.{md,json}` —— 用户侧入口是 `agentflow status-report`（零模型调用、不打断任何循环；不是去问 M 一句）。板项行的"状态"投影不在本文件里（见下一行） |
| `boardrows.py` | **板项行的状态投影**（D12，2026-11-09 从 `statusreport.py` 整段搬出来）：`tasks` 表里 `kind` 非空那一行的 `status` 恒为 `pending`（类型标记，不是"还没收口"），真正的收口状态在 `item_state` / `item_close` ⇒ `tasks_row_reading` 按三档投影（板项已收口 / 板项还开着 / 代理行照旧 `<status>/<outcome>`），三个 `BOARD_ITEM_*` 常量是那三档的措辞。两个调用方（`statusreport._hint_of` 与 `webui.readers` 的 `TaskRow.status_reading`）必须是同一处口径 —— `statusreport.tasks_row_reading` 按名字回引本模块 |
| `verifications.py` | 验证者 **V** 的证明级审校台账（`draft/39` §3.21）：`verifications/<命题号>.jsonl` 追加式一行一次审校（三态结论 `成立/有毛病/看不出来`、`defect_step`、逐条 findings 带步号、输入证明 sha）；`cold_start_prompt()` 是纯函数（签名里没有 store/conductor/registry ⇒ 冷启动是结构性质）；`signs_bit3()`/`bit3_payload()` 决定并产出五元位第 3 位的凭据。D3 批 1（2026-11-09，只读、零行为翻转）新增缺陷类别读数：`fault_kind_of()`（`kind` ∈ `math` / `procedural` / `style` / `contract`；`report_gap` 不是 kind，落在 `cause` 上；老行按 `legacy_math_evidence` / `legacy_shape` / `legacy_default` 推定；新老行按 `secretary_judge` 里有没有 `fault_kind` 这个键区分）、`is_a_vote()`（D268 的 `sign_reading.votes` 唯一允许数的行局部谓词，只看 `kind==""`，带 report_gap 的 clean 行照常算票）、`vote_reading()`（人读的 why）；配套只读 CLI `scripts/verify_audit.py`（票数 / report_gap / legacy_* / clean→fault 四张表，不写盘） |
| `proofreport.py` | **形式化困难的受控汇报形态**（业主 2026-10-22 晚的协作面裁定）：L→B 的汇报与 B→D 的升级，两边落点都是既有的 `agent_message` 收件箱（`agent_loop.send_message` 写 / `read_messages` 读），本模块只把"这一条汇报说的是什么"压成受控形态 —— `FAILURE_TYPES`（失败类型词表）/ `SEVERITIES`（`normal` 与 `research` 两档：B 改证明就够 / 路线可能不成立 ⇒ B 通知 D 开展研究）/ `SUGGESTIONS`（失败类型 → B 该补什么）/ `payload` / `violations` / `deliver`。自由文本没法被下游按类分派，而"漏了一步"与"命题本身不对"该做的事完全不同 |
| `secretary.py` | **「秘书」**：每个智能体自带的随员（`draft/53` v3 定位 · `draft/55` 接口规范 · `draft/54 §2`）。它**不是一个同级角色**：不占 `schema.ROLES`、不加注册工具、不改权限面声明 ⇒ 一个计数都不变。四条职责（格式与内容优化 / 委派评估 / 委托加工 / 闭环提醒）+ 手稿通道的增改查（`handoff_add`/`handoff_revise`/`handoff_query`）+ **命题写入代理**（`wash_statement`/`record_statement`，业主 2026-10-09：B 交内容、秘书落盘——洗格式 / 拿编号 / 查重 / 改表四件，写集只有 `statements` 与 `dependencies`）+ **名册**（S1k，业主 2026-10-19/20：「名册 = 父 + 子 + 绝对编号」）：落点 `out/roster/<父编号>.jsonl`（append-only，`_fold_roster` 折叠 `add`/`bind`/`retire`/`keep_alive`，另有 `<父编号>-index.jsonl` 对照表与 `<父编号>-retired.jsonl` 销号名单），`roster_view` / `parent_of` 答"我的父是谁、我的子是谁"（行里带绝对编号 `task_id` 与名册名 `name`），`brief_source` 记简介是父给的原话（`parent`）还是秘书代写（`secretary`）；两条实质红线（格式补不全、或加工后发现实质缺陷）走 `negotiate()`（≤2 轮）+ 台账留痕 —— **它从不替本体表态**（"委托秘书洗一遍格式"是**两段式**：`wash_proposed` 请示 ⇒ 父用 `accept_proposal`/`reject_proposal` 定） |
| `evidencebits.py` | 命题的**五元证据位**与派生等级（`draft/39` §3.14）：哪位角色欠哪一位（数值验证/有证明/审过/形式化通过/正式审查）、`na` 与"还没做"分得开的四态、等级**机械派生**（数值封顶在"强猜想"）、引用命题凭文献代号进第 2+3 位、作废四条缺一不可。另加**位 ⇒ 台账的映射**（`BIT_LEDGERS`：哪一位去哪张表查；`bit_evidence_gaps`：位上说有、表里要查得到）——业主 2026-10-09 点名的那一条。纯函数层：不读盘、不写盘，读入口是 `bits_from_row()`（收工门的 `reviewed_proof_rows` 与状态报告都走它） |
| `quoteverify.py` | 引文校验：引文级回验（禁改区） |
| `quoteevidence.py` | 引文回验的**证据叶子**（D1 的落点）：`verify_quote_evidence` 用禁改区那一个 `quoteverify.check_quote` 判，再把 `quote_mode` / `quote_span` / `quote_reason` / `quote_call_sha256` 逐栏落到命题行上 —— 改前 8 条命题写着"逐字回验通过"而三栏全是空串（核了哪一段、在第几页、花没花模型钱一条都读不出来）。判决本身仍只有 `quoteverify` 一份，本模块补的是"调动方"那一半 |
| `refvocab.py` | **受控引用词表的唯一真身**（D10 B1，2026-11-09，纯模块零 `agentflow` 依赖）：`parse_ref` 只判形状（命名空间 / 地址 / legacy），`ref_problem` / `ref_reading` 在工作区根下判存在性，三态 `ok` / `legacy_ok` / `missing` / `unchecked` / `bad` / `ambiguous` 不许折平。改前 refs 有四套写法（`manuscripts.OBJECT_REFS` / `schema.CITATION_PREFIXES` / `depsection.CARRIED_KEYS` / 提示词），同一个字符串在两张表里结论相反（`doc:` 在 citations 合法、在 refs 非法）—— 真机已因此丢过一整份交接。判据 `tests/test_ref_vocabulary_is_one_table.py`。2026-11-09 拆成两个模块（repo survey 的 `>800 行` 软判据，不抬基线）：**本文件只留解析与存在性**（`parse_ref` / `ref_reading` / `explain`），词表与号形在下一行 |
| `refspecs.py` | **受控引用词表的规格那一半**（2026-11-09 从 `refvocab.py` 整段搬出来，纯数据、零读盘、零 `agentflow` 依赖）：三态/受控码词表（`STATE_*` / `CODE_*`）、三类目标（`KIND_*`）、`RefSpec` 与唯一词表 `REF_NAMESPACES` / `REF_SPECS`、手稿族名与文件名正则、以及"一个号有几种写法"（`_id_forms` / `_anchor_forms` / `_manuscript_from_name`）。`refvocab` 按名字回引它，`refvocab.parse_ref` / `refvocab.REF_SPECS` 等公开名照旧可用（re-export，不是第二份实现） |
| `dedup.py` | 判重：文献 / 概念 / 关系（禁改区） |
| `experiment_methods.py` | E 收得下的三种计算法（`numeric` / `symbolic` / `exhaustive_search`）的唯一来源 `COMPUTATIONAL_METHODS`：动作面 `specs/e.py` 与工具面 `verify.run_experiment` 的 `method.enum` 都从它取（`formal` 不在这里 —— 形式化归 L，`schema.EXPERIMENT_METHODS` 仍含它）。中立模块、不属于任何 `agent_*` 包：常量先落地，`specs/e.py` 才不会与 `agent_e/_support.py` 成环 |

### 第 5 层 · 循环面（模型自己决定调什么）

| 文件 | 是什么 |
|---|---|
| `agent_loop.py` | LLM 驱动的角色循环：模型决定调哪个工具、唤起谁、给谁留言，框架负责执行与留痕 |
| `reconnect.py` | **连接类失败的有界退避闸**（2026-11-03，从 DSH 的 `ClientBridgeLifecycle` 逐条移植）：`agent_loop._ask_step_with_reconnect` 在 `judge_no_reply:<kind>`（"没连上"那一族）之后按 `cap = min(max, base * 2 ** attempt)` 在 `[cap/2, cap]` 里等一段再问同一轮 —— 单飞（`pending` 非 None 就不再排）、成功即归零（`connected`）、抖动可注入（`rng`）、总等待上限（`total_wait_sec`；超了就 `model_unreachable` 并说清"等过 N 秒"）；三个数走 `settings` 梯子（`AGENTFLOW_RECONNECT_*` / `reconnect.base_sec|max_sec|total_sec` / 默认 5·60·300），业务代码不写死。等待本身走 `clock.await_io`（真耗墙钟、进主时钟的账，不在账外的裸 `time.sleep`）。判据 `tests/test_reconnect_backoff.py` |
| `stepdispatch.py` | **一步一条的入口层**（角色无关的公共层；业主裁定「multi_call 应该让系统自动整理拆分」）：`catch_step_request` 先把"这一步模型要求做什么"整包接住，`StepRequest` / `StepItem` / `StepDispatch` 再拆成有序条目、交给循环逐条执行（每条走完整的准入 / 预算 / 记账），最后汇总成一份读数回给模型。改前的形态是解析层取 `tool_call_list[0]`、其余静默丢弃（真机三趟共 76 个多调用步、被丢 107 条）—— 本层就是那个缺口的落点 |
| `agent_prompts.py` | A–H + V（含 M）的前置提示词：身份、边界、政策、工具、伙伴、契约、三态、循环协议 |
| `agent_skills.py` | 各智能体的 skills（业主 2026-10-14「现做现读」）：目录 / 正文 / 索引只有 `CATALOG` 一处定义，正文由 `materialize` 落到工作区 `skills/<角色>/<slug>.md`，前置提示词里只出现 `index_block(role)` 那一小段；`validate()` 逐条核"动作真实存在且够得到、工具在该角色自己的面上、描述无歧义"（`draft/120` §②） |
| `llm.py` | 抽取层：`Extractor` 协议 + 离线基线 + 可插拔 `LLMExtractor` |
| `llmseam.py` | 统一的模型缝：一次模型调用 = 一条可审计的记录 |
| `judge.py` | LLM 判定的唯一缝协议 |
| `judges.py` | 语义判据的接入方式：注册表 + 三态 + 引用落地过滤 |
| `promptkit.py` | 提示词装配：有序段 + 变量 + 作用域遮蔽 + 动态上下文（快照那一类） |
| `promptstability.py` | **system 提示词的前缀稳定性**（2026-10-19/21）：静态 / 动态分离（`STEP_VOLATILE_FACTS` 登记表 + `SYSTEM_PLACEHOLDERS` 静态替身）、逐字节判据、缓存读数汇总 —— 上游前缀缓存要求前缀**逐字节相同**，而 system 过去每一步都在重算（`budget_left` 一变整条前缀作废）；登记表现已扩成"**跨 run 会变**"的事实，它们改在 user 消息里现读（判据 `tests/test_cross_run_prefix_is_reused.py`） |
| `cachectl.py` | **两档提示词缓存的用户面**（业主 2026-10-23）：`status()`（两档 × 四格：是否落地 / 是否新鲜 / 覆盖几个 / 缺谁，三态带理由）、`plan()`（要预热几个目标、预计花费、已新鲜可跳过）、`warm()`（真预热；发请求前先打印 key 来源与模型，不打印 key）、`fingerprint()` / `key_reading()`（`sha256(key)[:16]` + 模型 + `base_url`，换 key 后比出 `stale` 并点名受影响智能体）、`annotate_run()`（把指纹补进刚写下的那一趟读数）。渲染与新鲜度的唯一真身仍是 `scripts/warm_prompt_cache.py`（按路径加载），命令行 `agentflow cache status|warm` 与网页那两个按钮都从这里取数 |
| `persona.py` | 身份的两个具名槽位 + 唯一注册入口：部署那一份无条件注册、角色那一份靠同名遮蔽、`scope` 必填（学 DSH 的 `dsh-persona`；`draft/101` §3） |
| `presets.py` | 预设机制：目录 = 一个预设（`preset.<yaml>` + `agent.<宿主>.yml`，DSH 的 YAML 形状；两份的名字是常量 `PRESET_MANIFEST_NAME` / `COMPOSITION_NAME`）、根优先级、坏预设带理由、挂一次 + 生成戳、只许复制式创作、`!!js` 门落 conditional（学 DSH 的 `dsh-agent-presets`；`draft/101` §2） |
| `composition.py` | 预设的**接线层**：组装行名 → 解析函数（今天两行：`agentflow.text_blocks` 给写死的正文块、`agentflow.brief_blocks` 声明五格身份文本由真身 `specs/<role>.py` 渲染）、随包预设根 `agentflow/presets/roles/`、角色 id → 预设 id（小写化）、以及回落时的读数 `prompt_audit["preset"]`；约定只有一条：预设决定"写死的块由哪段文件给"，代码永远给现算的块（`draft/103` §4.1b） |
| `instructions.py` | 工作区指令通道：AGENTS.md 一类文件的发现 / 去重 / maxBytes 降级 / 转义 / 追加式状态（学 DSH 的 `dsh-agent-instructions`；`draft/101` §4） |
| `contextbudget.py` | 上下文预算：压缩 / 剪枝 / spill |
| `tokenestimate.py` | 固定密度估值器（S-B/12-H：DSH 常数 + `chars_per_token` 配置项） |
| `tool_timeout.py` | 逐工具超时：协作式截止 + 一张限时表（S-E/12-D/12-G） |
| `fs_observation.py` | 文件"读后写"的观测闸门（S-A/9甲：没读过就不许改） |
| `autonomy.py` | 自主轮次 + 周期汇报 |

### 第 6 层 · 编排与接线面

| 文件 | 是什么 |
|---|---|
| `conductor.py` | 主控编队：把"一次召唤"做成可审计、可拒绝、可取消、可重建的台账行 |
| `clock.py` | **系统时钟**（D-53；业主原话「把时钟做成系统原生工具……时钟只有一个，依附于其上的计时进程可以很多」）：全系统唯一的取时口 —— `Reading`（墙钟 + 单调计数，三态 `ok`/`partial`/`unknown`）、`RealClock` / `FakeClock`、`Timer` / `TimerBook`（落盘在 `out/clock/` 下的那一个 state 文件），以及 `now` / `start_timer` / `start_alarm` / `cancel_timer` / `timers` / `due_timers` / `fire_due` / `record_wake` / `read_wakes` / `pending_wakes` / `consume_wakes` / `await_io` / `note_wait`。工具面在 `tools/clock_tools.py`，框架内部的每一处等待也进同一本账（判据 `tests/test_clock_governs_all_timed_work.py`） |
| `scheduler.py` | 调度：按写集互斥分波并发 |
| `host.py` | 主控接线：把 A–H 接到 `LocalBackend` |
| `runflow.py` | 端到端一条命令：给一个主题、一个美元上限，产出可复核的完整运行记录 |
| `pipeline.py` | 编排：把 A→B→C→D 串成可中断、可续跑、可审计的流水线 |
| `projects.py` | 项目工作区：一个项目一个文件夹，冷/热启动按"文件夹在不在"判定 |
| `locallib.py` | 把本地目录里的 PDF 灌进项目库（按内容 hash 幂等） |
| `cancellation.py` | 取消语义（四条纪律） |
| `faculty_checks.py` | 十项官能里"可机械判的那一半" |
| `deliver.py` | 交付前的判据闸门：逐项判据 + 机械半 → 结论、报告、派回去的工作项 |
| `closing.py` | 收工门（`draft/37` §16 P3）：**七格**各自一个三态读数（`closing.DEFAULT_CHECKS` 是权威清单）—— 无未裁决矛盾 / 承重结论有 T3 或已降档 / 报告九节齐全 / 没有还在等用户回答的问题 / 实质产出（`documents`/`relations`/`experiments`/`review_findings`/`statements` 至少一张非空）/ 验收表的机器可判行 / 产物台账与盘上一致（`ARTIFACTS.jsonl` 逐条重算）。**工具 `conductor.closing` 与 CLI `agentflow closing` 都调 `closing.check_closing`（同一份实现、两个入口）**；`unknown` 不是通过。论文那一格（回执里的 `tex_sha256` 与盘上那份 `main.tex` 的摘要对得上；没有 `main.tex` ⇒ 不适用，回执读不到 ⇒ 没查成）已退出这门（业主裁定：出不出 paper 由 M 判断时机）：它落 `readings["paper"]`，不进 `status` / `machine_pass` |
| `reviewaccept.py` | 审稿场景的**内容级**验收（`draft/37` §17.3）：报告九节且每栏有读数 / 定理台账每条有完整假设与出处页码 / 三态分支落盘可查 / 在成本上限内 / 每跳留下可读输入。**判据与辅助读数分栏** —— `sha`/页数/锚/行数那五种"容易拿到"的读数照原样给出，但**一个都不参与 `passed`** |
| `migrate_concepts.py` | `concepts` 并进 `statements` 的折叠内核与**迁移计划**（`draft/97` §10/§14/§15.2）：`plan_migration`（计划 = 折叠 + 关系改号 + 逐条落账 + 边界读数，真跑的那一笔照抄它）、`counter_alloc`（确定性发号替身，让预演与真跑的号逐条对得上）、`ledger_lines`（改号台账的行形状：`out/` 下那份 `migrate-map` 记录）、`fold_concepts` / `remap_concept_ids`（内核：概念号走同一分配器重发、定义待补标记、别名带过）。纯函数，不碰盘 |
| `conceptrows.py` | 并表**过渡期**概念行的唯一读写口（`draft/97` §10.3）：写的时候新标准（`statements`）先写、老表（`concepts`）照旧镜像且**两处同号**；读的时候合成一个视图（新标准优先，逐行标 `via="statements"/"legacy"`）；`legacy_present` 三态（表已退役而老文件还在 ⇒ `stale_file` 点名）；四个计数分开给（`merged` / `legacy_only` / `definition_only_in_legacy` / `statements`）—— 有了它，读侧可以一个一个搬到新标准，而"两边不同步"永远看得见 |
| `paperledger.py` | S1q **正文重建**（`draft/97` §9.5 + §16.1）：台账里的定理搬进论文正文时，逐字（①）、重写论文号（②）、带 `stmt:` 引用（③）、映射落 `dependencies`（④，字段组合照 §9.5 —— 只挂**手稿**那一端，"四选一"是硬闸），以及 `check_paper_ledger` 的五条判据（逐字 / 引用在 / 映射唯一 / **两个方向都判**：正文有而映射缺、映射有而正文没有、`\ref` 悬空 / 论文里不许引 `doc:`）。正文排版仍归人/模型 —— 这一层只判"搬进来的对不对得上台账" |
| `papermapping.py` | **论文对应表**（业主 2026-10-22）：G 写正文之前先有这张表、H 依据它逐行核，三个落点一份内容（论文包里的 `MAPPING.json` 是唯一真身，`MAPPING.md` 与 `mapping-appendix.tex` 都由它渲染）。逐行给 `kind` / `label` / `env_no` / `ledger_id` / `proof_no` / `file`（包内相对路径）/ `citation_loc` / `lean_file` 这些格的口径与校验；`write_mapping` 是唯一写口（"手写第二份"在结构上不可能发生），`sync_markdown` 是改了 json 之后唯一合法的修法。数值实验定理那一行另有 `numeric_evidence` / `exhaustion_note` 两格（业主 2026-10-23，E-1）：那一行的 `file` 是程序的相对仓库路径，判据见 `numerictheorem.py` |
| `numericproof.py` | **穷举 proof 与"有数值实验支持"的分界**（业主 2026-10-23，E-1）：`exhaustion_problems`（搜索空间 + 布尔 `exhaustive` + ②③）、`compose_proof_column` / `parse_proof_column`（证明栏三段：`程序：` / `程序设计：` / `穷举论证：`）、`is_signed_exhaustion`（V 签字、E 作 ②③）、`sign_experiment`（写侧升档）、`filing_problems`（B 的入库闸：own_result 的 proof 不许自签）、`formal_slot`（"形式化"那一格：数值实验定理填程序、理论定理填 `.lean`） |
| `exhaustionreport.py` | **E 那两块读数的落盘**（业主 2026-10-23）：`compose_report` / `write_report` 把 ②③ 落成一份读数（落点由 `exhaustionreport.report_relpath` 算：按实验号分目录；三块标题、文件名与署名都是固定字面量，抬头写 `exp:` 编号），`read_report` / `blocks_of` / `disk_problems` 是"这份读数在不在、三块齐不齐"的唯一实现，`review` 是读稿人视角的逐条判据（搜索空间数字与代码里的循环/参数对不对得上、对称性理由成不成立） |
| `numerictheorem.py` | **数值实验定理怎么读**（业主 2026-10-23，E-1 的 G 侧）：三块与署名的记号（取自 `exhaustionreport` 与 `numericproof`，不另抄一份）、`blocks_missing`（"三块齐全"的唯一判定）、`corpus_problems`（E 那份读数在不在、缺哪一块、有没有那条 `exp:` 编号）、`program_state`（证明栏那份程序在不在盘上）、`citation_present`（正文那一段有没有指回 E 的读数）、以及那一组拦门的问题类别 `NUMERIC_KINDS`（接线在 `papermapping.ALL_PROBLEM_KINDS`） |
| `researchbase.py` | **G 能依赖的研究成果池**（业主 2026-10-28 逐字：「G写论文时能依赖的只有系统侧的研究成果…如果产出不足不可杜撰，应上报父代理要求扩大研究面」）：`research_base` 读一次 `statements`，三态回答 `ready` / `insufficient` / `unreadable`（读不到**不**等于"没有成果"）。算"成果"的判据只有两条：`proof_text` 非空（B 收进来的证明正文）或 `quote_verified is True`（逐字引文回验通过）—— 只登记了标题的命题行不算。顺着它们往外看的是"B 有引用记录"的那一侧：`source_lit_id`（文献）与 `doc_id`（手稿）。闸门在 `tools/doc_tools.py::_doc_write_mapping`（成文门，`kind=no_evidence_chain` / `ledger_unreadable`，**一个字节都不写**）；判据 `tests/test_g_cannot_write_a_paper_on_an_empty_research_base.py` |

### 第 7 层 · 质量与产物面

| 文件 | 是什么 |
|---|---|
| `evidence.py` | 证据层：先检索、再逐字回验 —— 每条结论都落在某段真实原文上 |
| `researchpending.py` | 344 | 把「研究还没做完」读成一份可判的清单（批 M96，2026-11-06）：概念面缺（`concept_missing`，动作对象是 B 不是 C：概念行只由 B 经 `Secretary.write_concept_row` 写，C 的动作面只产 `AnalysisReport`）/ 有确定性结论却没命题（`candidate_unfiled`）/ 命题未签 / 已签未收录 / 开着的题 / 无稿 —— 六档里每档都只读既有台账（零模型），`conductor.patrol` 的异常清单与 M 的挂机判据共用同一份 | M 原来「板上没活就挂机等 20 分钟」会把研究停在这里：D 交出可核验结论后没人立命题。这张清单是那一步的判据来源 |
| `artifacts.py` | 产物登记：谁在哪个路径产出了什么 |
| `depsection.py` | **F 手稿依赖段的唯一解析点 + 引用档位的唯一判据**（业主 2026-10-24：「作者只写内容，登记由收方读稿产生」）：`SECTION_HEADING` 那一节按三列表格（路径号不进稿，第四列只在老盘材料里读回）读成 `dependencies`（`used_by="stmt:<命题号>#pN"` + `path_group` + `source_stmt_id`），`citation_levels` / `citation_level_allowed` 是引用档位本身，`read_manuscript` 按命题号找 F 的手稿。`## 证明` 那一格是**三态**（2026-11-09，D4）：`proof_body` 严格（缺节 ⇒ 空串，不再退到 `## 依赖` / 整份全文）、`proof_body_reading` 给 `present` / `absent`、`read_proof_body` 多一个文件侧的 `unreadable`；只有"入参本来就是一段无标题证明正文"的两处（`read_manuscript` 按正文认稿的指纹、`proofregistry.proof_sha`）才走显式命名的 `proof_body_or_whole`（返回值带 `fell_back=True`）。2026-11-10 切节口径（真机 DCT 彩排）：`SECTION_TITLES`（手稿"节"的标题闭集）/ `heading_level`（行首 `#` 的个数）/ `is_section_heading`（这一行是不是一节）三格是唯一来源 —— `## 证明` 到下一个同级且是手稿一节的标题（或更高级标题）为止，`## 记号与约定` 这类同级自由小标题与 `###` 小标题留作正文；`manuscriptintake` 与 `proofregistry` 的切节都从这三格取同一份口径（判据 `tests/test_proof_body_is_three_state.py`）。F 自己不写依赖台账、也没有写台账的工具；`secretary`、B 的入库、D 的汇报、F 的手稿四处都读这一份（与 V 读 F 的手稿再签字同构） |
| `papercompile.py` | 把智能体写好的 `out/paper/main.tex` 编成 `main.pdf`，并写框架自己的编译回执：判"这份 PDF 是不是盘上这份 tex 编的"（`receipt_matches_tex`） |
| `litread.py` | 文献本地字节的**唯一解析点**（2026-11-05 加）：`resolve_literature_path` 按「先 library 基准、再 workspace 基准」两处解析并存下 `path_base` 读数（同一个 `literature.path` 曾被两个坐标系读，真机上出现过 `library/library/…` 的 file_missing）；`fulltext_tier` / `with_fulltext` 是 `download.fulltext` 三档（ok / no_text_layer / no_fulltext）的**唯一写点与清除点** |
| `modelgw.py` | 模型网关：全仓唯一读 API key 的地方 |
| `modelclient.py` | 把 `modelgw` 适配成抽取层要的 `.complete(prompt) -> str` |
| `modelcost.py` | 模型花销入账适配器 |
| `tokenmeter.py` | token / 花销记账（`usage_ledger` 的唯一写入方）：**硬约束只剩钱那一轴**（2026-10-15 撤掉 token 预算，token 只是读数），重试也计入 |
| `providers.py` | 文献检索 provider 层（禁改区） |
| `fetch.py` | 下载层：流式下载、原子落盘、限速重试、镜像回退 |
| `extract.py` | 文本抽取层：`extract_text(path) -> DocumentText`（禁改区） |
| `formalgw.py` | Lean 形式化验证后端 |
| `textutil.py` | 文本规范化、相似度、slug、页码解析 |
| `errorstats.py` | **按角色 × 类目的「错误动作计数」**（业主口径逐字在模块 docstring：统计"被各种判据拦下或被秘书拦下"的行为，按角色细分多类）：只读事件流与会话记录，一份都不写（不建表、不改行、不追加事件、不落报告）；`ERROR_CATEGORIES` / `CODE_TABLE`（码→类目→`file:line` 出处）/ `primary_code`（一条记录只算一次的主码规则）/ `error_action_stats`（三态 `checked` + `state` + `reason`）/ `render_text` / `stats_json`。人看 `agentflow stats errors`，程序看 `as_dict()` |
| `readouts.py` | **四个只读读数的统一外层**（`draft/145`，业主 2026-10-24 的 B/F 两格）：`errors_readout` / `flow_readout` / `cost_readout` / `gates_readout` 共用同一个外层五键（`checked` / `state` / `reason` / `data` / `problems`）—— 同一份口径同时供 CLI 与网页读，"没读到"不折成 0。判据 `tests/test_readouts_are_the_single_shape.py` |
| `dispatchpolicy.py` | **D 派活文本的机械判据**（块乙，业主 2026-11-08 逐字：「那条猜想只是参考意见，D不能直接把自己的猜想登记到命题台账，也不能命令E或F必须把它做出来，这只是研究方向参考」）：`d_dispatch_records` 从 `sessions/*.jsonl` 的 `agent_step` 事件里取 D 真的交给 E/F 的那一段（`role="D"`、`shape="summon"` 的 `payload`，三态 `checked`）；`dispatch_text_problems` 判两半 —— ① 派活文本里出现 D 自己登记的某条 `conjecture_id`（`conj:NNNNNN` 或裸 6 位，且那个号真在 `conjectures` 台账里）⇒ `violations` 逐条点名 sid / index / 猜想号；② 归属到某段派活文本的 `attack_plans`（`problem` 是那段文本的子串，或 `problem_key` 就是它给的值）同样点名；认不出归属的计划记 `self_authored_plans`、不算违规（F 自己想证不算 D 的命令）。只写研究方向（不提号）⇒ 绿；会话记录读不出来 ⇒ `checked=False`（没查成 ≠ 没有违规）。纯函数、不注册工具、零模型调用、不写盘；判据 `tests/test_d_gives_a_direction_not_a_conjecture_order.py` |
| `statementfission.py` | **形态读数：一条定理有没有被拆成多条独立命题**（D-54，只报不拦；业主 2026-10-24 在 `projects/sylow3` 看到同一条 Sylow 定理被登记成三条、第 2 份证明一份没用）：`suspected_splits` 用并查集把"表述不同、其实是同一条"的候选并起来，`describe` / `summary` 出人读读数；判重仍归 `secretary` 的 `_same_proposition_candidate`，本模块只出读数、不改台账 |

**仓库根还有四处不属于 `src/`，但改代码时会碰到**：
`agentflow/tests/`（判据）、`agentflow/tools/`（发布门）、`agentflow/scripts/`（lint 与 FC-27 门）、
`agentflow/docs/`（角色规格 `ROLE-SPECS.md`、提案 `PROPOSALS.md`、治理 `NOAI-GOVERNANCE.md`）。

---

## §2 想改什么 ⇒ 读哪几个文件（3 跳以内）

| 我想… | 先读（权威） | 再读（实现） | 判据 / 副作用 |
|---|---|---|---|
| 加一个新的**工具** | `tools/base.py`（`ToolSpec`/`register`） | `tools/<模块>.py` | `tests/test_tools_returns_declaration.py`（`TOOL_COUNT`）、`docs/ROLE-SPECS.md` §R0、`tests/test_role_specs_complete.py` |
| 加一个**角色动作** | `specs/<角色>.py` 的 `ACTIONS` + `SPEC`（**声明真身**；禁改区）→ `capabilities.py`（`CAPABILITIES` 由它派生；禁改区） | `agent_<x>/<动作>.py` 的方法 | `tests/test_coverage_policy.py`、`tests/test_capabilities_two_layer.py`、`capabilities._KNOWN_UNMATCHED_ACTIONS` |
| 改**谁能叫谁**（召唤边） | `specs/<角色>.py` 的 `SPEC.edges`（**声明真身**；禁改区）→ `capabilities.py`（`ALLOWED_EDGES` 由它派生；禁改区） | `policy.py`、`conductor.py` | `tests/test_policy.py`、`tests/test_v_signing_belongs_to_b_e_f.py`、`.noai-approvals.json`（登记 ≠ 批准） |
| 改**表结构 / 字段** | `schema.py`（禁改区） | `store.py`、`verify.py` | `tests/test_schema.py`、`tests/test_verify*.py` |
| 跑一次**端到端** | `cli.py`（`cmd_run`） | `runflow.py`（`run_topic`）→ `evidence.py` / `claims.py` | `tests/test_r5_orchestration_cost.py` |
| 动**项目工作区 / 本地书架** | `cli.py`（`cmd_project`） | `projects.py` → `locallib.py` | `tests/test_projects.py`、`tests/test_user_quickstart.py` |
| 动 **A 的检索** | `agent_a/`（包） | `providers.py` → `fetch.py` → `tools/search_tools.py` | `tests/test_agent_a.py`、`tests/test_providers_online.py` |
| 动 **B 的抽取** | `agent_b/`（包） | `llm.py` → `extract.py` → `dedup.py` | `tests/test_agent_b*.py`、`tests/test_quoteverify.py` |
| 动 **C 的图分析** | `agent_c/`（包） | `tools/graph_tools.py`、`tools/trace_tools.py` | `tests/test_agent_c*.py` |
| 动 **D 的研究循环** | `agent_d/`（包） | `claimanatomy.py`、`tools/research_tools.py` | `tests/test_agent_d*.py`、`tests/test_claimanatomy.py` |
| 动 **E 的实验 / 形式化** | `agent_e/`（包） | `formalgw.py`、`tools/verify_tools.py`（禁改区） | `tests/test_agent_e*.py` |
| 动 **F 的攻坚** | `agent_f/`（包） | `tools/attack_tools.py` | `tests/test_agent_f.py` |
| 动 **G 的写作** | `agent_g/`（包） | `gates.py`、`tools/doc_tools.py`、`papercompile.py` | `tests/test_agent_g.py`、`tests/test_papercompile.py` |
| 动 **H 的审校** | `agent_h/`（包） | `gates.py`、`tools/review_tools.py` | `tests/test_agent_h.py`、`tests/test_gates.py` |
| 动 **V 的证明级验证** | `agent_v/`（包）、`specs/v.py`（禁改区：边与写集在那里） | `verifications.py`（台账 / 冷启动提示词 / 签位）、`tools/verify_tools.py`（禁改区：三件工具） | `tests/test_verifier_role.py`、`tests/test_capabilities_two_layer.py` |
| 动**主控编队 / 并发** | `conductor.py` | `scheduler.py` → `host.py` → `tools/conductor_tools.py` | `tests/test_conductor.py`、`tests/test_scheduler.py`、`tests/test_host_wiring.py` |
| 动**角色循环**（模型自己决定） | `agent_loop.py` | `agent_prompts.py` → `host.py` → `llmseam.py` | `tests/test_agent_loop.py`、`tests/test_agent_prompts.py` |
| 动**连接类失败的等待 / 重试**（"没连上"之后等多久、要不要停） | `reconnect.py`（`BackoffGate`：单飞 / 指数退避 / 抖动 / 成功归零 / 总等待上限；配置走 `settings` 梯子） | `agent_loop.py` 的 `_ask_step_with_reconnect`（唯一调用方）→ `clock.await_io`（等待记账） | `tests/test_reconnect_backoff.py`（a–e 五条，含反真空"摘掉闸"）、`tests/test_clock_governs_all_timed_work.py::test_e_waits_outside_clock_is_zero_and_a_raw_sleep_turns_it_red`（裸 `time.sleep` 会被它抓） |
| 往**提示词**里加一句话 | `agent_prompts.py` | 它引用的现算来源：`capabilities.py` / `tools.build_registry` | `tests/test_agent_prompts.py`（每条都要与现算一致） |
| 动**模型调用与花销** | `modelgw.py`（key 的**唯一入口**：环境变量 → 设置文件 → 默认，见 `settings.py`） | `modelclient.py` → `tokenmeter.py` → `modelcost.py` → `llmseam.py` | `tests/test_modelgw.py`、`tests/test_tokenmeter.py` |
| 换一台机器 / 改**本机的工具链落点与模型 key** | 设置文件的示例 `settings.example.json`（真正那份被 git 忽略，本机键名与优先级见 `settings.py` 的模块 docstring） | `docs/FORMAL-TOOLCHAIN.md` §6（落点表 / 键名表 / 安全阀） | `tests/test_settings.py`（含"真正那份既不在索引里、也确被忽略"与"示例里没有真 key"） |
| 动**判据 / 质量门** | `verify.py`（禁改区） | `gates.py`、`deliver.py`、`faculty_checks.py` | `tests/test_verify*.py`、`tests/test_gates.py` |
| 动**发布门** | `tools/release_all.py`（禁改区） | `tools/coverage_zero_test.py`、`tools/run_each_test_file.py` | `tests/test_release_all.py`、`README.md` §6 |
| 动**lint 规则** | `scripts/lint_rules.py`（禁改区） | `tools/vocab_census.py`（禁改区） | `tests/test_lint_rules*.py` |
| 改**禁改区规则本身** | `AGENTS.md` + `.noai-paths`（两处必须逐条一致） | `scripts/noai_gate.py`（禁改区） | `tests/test_noai_gate.py`、`--check-consistency` |
| 改**用户端网页**（页面 / 端点 / SSE） | `ui/src/api.ts` 的 `ENDPOINTS`（端点的唯一出口）+ `webui/routes.py`（`ROUTES`） | `ui/src/pages/*.tsx`（九页）· `ui/src/live.tsx`（一次订阅分发给九页）· `webui/readers.py`（只读面：`readers.ROUTES` **现读 14** 条，含 2026-10-13 加的预算/在飞/用量/状态报告与后加的 `/api/chat`、`/api/roster`）· `webui/sse.py`（流与钩子）· `webui/server.py`（`/` 的外壳与静态路由） | `tests/test_webui_contracts.py`（A–D 四条名字层 + 新鲜度）、`tests/test_webui_pages.py`（每页真读数/空态/三态）、`tests/test_webui_readers.py`（各面正控/负控 + 逐条事件的分页与编号口径）、`tests/test_webui_sse.py`（流）、`tests/test_webui_static.py`（`/` 与静态）、`ui/README-DEV.md` |
| 加一个**子命令** | `cli.py`（`build_parser`） | 对应 `cmd_*` | `tests/test_cli_run.py`、`tests/test_user_quickstart.py` |
| 查**一次运行到底做了什么** | 产物目录 `out/run-N/`（六件） | `runflow.py`、`evidence.py` | `report.md` / `run-manifest.json` |
| 查**谁在什么时候说了什么** | `sessions.py` 的会话记录 | `agent_loop.py`（事件种类） | `tests/test_sessions.py` |

---

## §3 这些文件为什么这么大（读之前先知道边界）

| 文件 | 行数 | 它的边界 | 为什么大（不是"没整理"，是职责本身宽） |
|---|---:|---|---|
| `agent_d/core.py` | 1748 | D 的全部动作（15 个，**拆包**：一个动作一个文件；`agent_d/core.py` 是其余成员（含 core 自身共 1707 行）；`agent_d/_support.py` 是模块级 helper 与常量，867 行）：摄入 / 溯源 / 评估 / 提问（`propose_question`）/ 裁决 / 研究 / 汇报（批 R22 把两处请求账本收成一处 `_d_requests`，1702 → 1772 行） | 每个动作都自带"数据面前置检查 + 落库 + 三态"三段，15 个叠起来就是几千行 |
| `agent_loop.py` | 14617 | 角色循环：模型决定调哪个工具 / 唤起谁 / 给谁留言，框架负责执行与留痕（**批 R40 补进本表** —— 它此前只在 §2 的用途表里；2026-11-16 读数：全仓最大的是 `secretary.py`，本表里最大的一行仍是它）。批 R62：`max_output_tokens` 8,192 → 32,768（严格口径 T1 的 `ModelReplyNotOk` 与 2026-10-03 第八趟的整份重写被截断，是同一格）。批 R68：新增一档 `no_reply`（"没拿到可用的回复"：超时与"思考吃光输出预算"分开计数、分开收场，各配一句只对它说的纠正）。批 R105：新增 `_registry_with_own_action`（把"我这一趟被派的那个动作"包成 `own.<动作>` 交给循环 —— `--subagents` 那一档的收尾）。批 R119：新增 B 入库前的秘书判档（只在那件动作**真在注册表里**时才问）；NT2（2026-11-15）判/落拆段之后，判在 `Secretary.judge_statement`、落行在 `Secretary.record_nontriviality`（拿到命题号与路径号之后），本文件只把回执抬成 `out["tier"]` | 一次循环要管八种形状、每一步的提醒/闸门/读数与续跑重建 |
| `agent_c/core.py` | 1137 | C 的 10 个纯读分析动作（**拆包**：一个动作一个文件；`agent_c/core.py` 是其余成员（含 core 自身共 1087 行）（批 R54 的 CS-10 ② 加了 `_report` 的产出即登记）；`agent_c/_support.py` 是模块级 helper 与常量，268 行）（批 R22 把 payload 里那句取不到的 `graph.*` 换成 `detail_reading`） | 分析类动作的**输出形状**很宽（每条都要给人读的措辞 + 给机器读的结构） |
| `capabilities.py` | 3368 | 动作表 + 写集 + 边表 + 导入期交叉断言（批 R21 加了空写集的并发含义表 `EMPTY_WRITE_SETS` 与它的两条反真空断言：2490 → 2569 行；2026-10-15 加 `A.walk_citations` 之后两层对账的读数更新为 61 = 22 + 39 + 0；2026-11-09 T1 加 B 的两条动作之后两层对账读数更新为 66 = 25 + 41 + 0；2026-11-11 `open_polish_copy` 进 unmatched 之后现算 67 = 25 + 42 + 0，只动注释、+2 行） | 声明本身不长，长的是**逐条理由**与断言（禁改区，必须写清为什么） |
| `agent_skills.py` | 4644 | 各智能体的 skills（业主 2026-10-14「现做现读」）：**45 条**操作手册的**目录 + 正文 + 索引**（一处定义）、`SURVEY`（38 个来源 skill 的调研记录）、`validate()`（动作可达 + 工具在**本角色**的面上 + **正文里点名**的动作/工具也算 + **落点必须在登记过的根下** + slug 可当文件名，配一张具名的"指到别人"豁免表）与 `materialize()`（2026-10-15：A/C/B/D 各补手册 + A 一条讲引文图，38 → 40；同日再加 `shared/取数-编号一律从台账读`，40 → 41 条 shared→**44 条**；2026-10-16：第 10 趟 T5 真机读数驱动 D 的攻坚口径更正；2026-10-30：F 的两份手册从三态收成两态） | 正文是**给人（模型）读的操作手册**，一条一大段；叠起来就是两千多行 —— 但它**不占前置提示词**（前置里只有索引），这正是"现做现读"要换来的东西 |
| `providers.py` | 3356 | 每个数据源一个 `_parse_*` + 查询编排 + 限速重试（2026-10-15 两件：① `_europepmc_urls` 不再把 Europe PMC 报来的 `?pdf=render` 网站页当下载直链 —— 它永远 403；有 `pmcid` 且 `isOpenAccess=Y` 时走 EBI 的 OA 全文路由，T5 的可读语料 6 → 11 篇；② 新增 `walk_citations` / `_fetch_one_work` 给新动作 `A.walk_citations`，`SELECT_FIELDS` 加 `referenced_works`；**取不到源记录时抛错而不是返回空表**） | 上游越多、字段越脏，解析越长（禁改区） |
| `gates.py` | 2944 | G1–G15 十五道独立检查器 | 一道门一个函数，每道门都带判据说明与负控 |
| `schema.py` | 4046 | 17 张表的 dataclass + 词表 + 校验 | 字段多、每个字段都带契约注释（禁改区）。S1r 并表（2026-10-10）：`concepts` 从 `TABLES` 退役、`SCHEMA_VERSION=2` |
| `runflow.py` | 1733 | 一次 `run` 的全流程（取材料 → 跑模型 → 落六件产物） | 主路径把每个阶段的失败分支都写全了；`run_topic` 已按 `T-7` 拆成 6 个 `_phase_*`（最长 228 行）+ 130 行编排层。批 R113：单价改成按**这一趟自己的时间戳**取（`price_of(cfg, at=stamp)`），不再读结账时的墙钟 |
| `evidence.py` | 1909 | 检索 + 逐字回验 + 来源登记 | 三档回验级别各一套路径 |
| `cli.py` | 6191 | 27 个子命令的入口与打印 | 每个子命令的 `--help`、三态 / 六档退出码（门是三态 `0/1/2`；`run-agent` 是六档 `0/1/2/3/4/5`，见 `cli.EXIT_CODE_BY_STOP`）、卡片式输出 |
| `claimanatomy.py` | 1893 | 断言解剖学（每条断言的可判定性）；批 R71 加了第 5 族的第二个码 `uncontrolled_disclaimer`（自造免责声明不再过关，见 `draft/116`） | 判据多且互相独立 |
| `agent_b/core.py` | 1381 | B 的 9 个动作（**拆包**：一个动作一个文件；`agent_b/core.py` 是其余成员（含 core 自身共 1377 行）；`agent_b/_support.py` 是模块级 helper 与常量，273 行）：入库 / 重抽取 / 结构重复裁决 / 登记命题 / 显式落稿 / 按位置与格收录 | 回验是"每条关系都要过"，代码密度高 |
| `verify.py` | 2141 | 全局不变量审计（`verify_all` 已按 `T-5` 拆成 14 个 `_check_*` + 30 行编排层；批 R19 在 `_check_2` 里加了 I7 在途上限的两条读数） | 40 多条不变量平铺（禁改区，见 T-5） |
| `tools/text_tools.py` | 284 | 文字层抽取 `text.extract`（2026-10-17 新增；业主口径：**A 负责搜索/下载/转纯文字稿入库**，其它角色只读那份纯文字稿；**原 PDF 原样保留**）—— 读 PDF 自带文字层、页间插 `===== page N =====`、写 `library/<编号>.txt`；**写盘前核质量**（NUL/替换字符/控制字符占比超标 ⇒ `garbled_text`，不写盘） | 不读写任何表 |

---

## §4 判据在哪（改完拿什么证明没改坏）

| 你改的是 | 至少跑这些 | 说明 |
|---|---|---|
| 任何东西 | `python -m pytest -q -p no:cacheprovider` | 全量（约 20 分钟） |
| 任何东西 | `python -B scripts/lint_rules.py` | error 必须 0（warning/info 有基线读数） |
| 工具面 / 角色面 | `python -B tools/verify_role_specs.py`、`tests/test_role_specs_complete.py` | 工具条数与文档一致 |
| 禁改区 | `python -B scripts/noai_gate.py --git --since <ref>` | 退出码 1 = 需要 2 名 reviewer |
| 发布相关 | `python -B tools/release_all.py`、`python -B tools/coverage_zero_test.py --level 2` | 发布门与覆盖门 |
| 文档里写了数字 | 先看 `docs/DEVELOPMENT-SPEC.md` §1.2 的"手抄数字清单" | 哪些数字有判据、哪些要人同步 |

---

## §5 这张图自己的判据

`tests/test_reading_map.py` 钉两件事（这条判据本身也是"文档不许烂"的一部分）：

1. **图里出现的每个文件名都真实存在**（相对 `agentflow/` 或仓库根解析得到）；
2. **`src/agentflow` 的每个模块都被这张图提到过**（不许有"孤儿文件"）——
   新增一个模块却忘了在这张图上给它位置，判据会红。
