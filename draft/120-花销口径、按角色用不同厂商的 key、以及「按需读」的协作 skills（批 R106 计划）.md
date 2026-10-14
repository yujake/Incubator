# 120-花销口径、按角色用不同厂商的 key、以及「按需读」的协作 skills（批 R106 计划）

> **这份文件就是「记载新 goal 的文件」。**
> 业主 2026-10-14 当面下达；上一阶段那三件（① `reach_fit` 提示词 ② 四位编号改六位
> ③ 二层唤起）已在 `b02b393` / `018b3ae` / `2371d6f` / `ff96251` / `4921556` 落地，
> 全套 `pytest tests` 5159 passed —— **老 goal 到此为止，结尾那句话是**：
>
> > **做完了就去看记载新 goal 的文件** —— 就是这一份。
>
> 新 goal：上限 **30 轮**，**每一轮必须完成足够多的任务**。四件事的落点在 §一，
> 现状清点在 §一的那张表，施工顺序在 §三，**待业主审批的 10 条能力在 §四**。

## 〇、新 goal 的原话（逐字留档，免得中转一次就走样）

> 将花销计算标准调整到与模型供应商定价吻合。更新设置面板与相应文件，允许不同角色智能体
> 用不同模型厂商的不同 api key（所有智能体的秘书另外共用一个 api key）。做提示词增强，
> 将面对不同类型任务应唤起的协作方式写成各智能体的 skills，以防止前置大量提示词，现做现读。
> 大量调研现有科研类 skills，抽出其中适用的工作逻辑改写成我们系统的智能体协作链 skills
> 或者各智能体自己的 skills，如果特别适合该智能体职责可直接写进智能体的前置提示词，
> 至少为每种智能体特地去找至少 5 个 skill 来综合考量（注意不是硬性要求给每个智能体写 5 个
> skill，定制 skill 时需保证描述无歧义、准确适配角色、动作都可实现），特别要给 M 多找素材
> （毕竟它是军师）。一个优质来源是 `D:\Incubator\temp\deepmath\moonshine\assets\skills\builtin`。
> 注意一定要改写成适合智能体协作系统的工作模式，不能照搬市面上 skill 的原文，
> 不能虚构我们系统不存在的动作！如果有某些动作是那些科研 skill（特别地，我们做的是数学科研）
> 特别推荐的但我们系统无法完成的，请先记录，统一等我审批是否实现这些动作。
> 这是下一阶段的 goal。请开一篇 draft 记录后开始工作。在 goal 的每一轮必须完成足够多的任务，
> 总轮次上限 30 轮。

（进度：**R106** 花销三档 token；**R107** 设置文件 `models`/`secretary` 两段 + 取缝梯子
+ 秘书换缝的装配口 + 台面读数；**R108** 设置面板接上两档（三段表单键、十个角色 × 四格、
  类型再生成、bundle 重出）—— ① 的台面那一半；**R109** 价目表按**厂商 × 模型 × 峰谷**
（官方定价页 2026-10-14 现抓：flash 0.003/0.006 命中、0.15/0.3 未命中、0.6/1.2 输出；
v4-pro 0.022/0.044、0.66/1.32、1.98/3.96），缺省价从过时的 0.27/1.10 换成 flash 低谷价，
`AGENTFLOW_MODEL_PEAK` 可钉峰谷。**① 已完成**（R106 三档 token → R107 按角色 key + 秘书共用那一档 → R108 设置面板 →
R109 官方价目表（厂商 × 模型 × 峰谷）→ R110 账本那一行自带计价口径 →
**R113 最后一处没走价目表的路（`runflow`）也收进同一处口径**）。
**② 骨架已落地**（R111）：`agent_skills` 目录（一处定义）+ 前置只加 `SKILLS_INDEX` 索引段 +
`materialize` 落盘到工作区 `skills/<角色>/<slug>.md`（现做现读）+ `validate()` 逐条核
"动作真实存在且够得到、工具在面上、描述无歧义"，判据 8 条（含三条反负控）。
**③ 第一批内容**（R111）：M 四条（立项 / 派活分波 / 卡点定位 / 收工）+ shared 两条（研究闭环 /
证据先行），来源 38 个 builtin 里挑出来综合的（`SURVEY` 逐格 ≥5 条，判据核名字）。
**③ 第二批内容**（R112–R113）：索引**按角色补齐** —— B 三条、E 三条、H 两条、V 两条、
F 两条、A 两条、C 两条、D 两条、G 两条，M 再加第五条「指派-按任务类型选收件人」
（把业主那句「面对不同类型任务应唤起的协作方式」落成一张决策表，并写明两条**只能间接走**的链
`M → D → F` 与 `F → V`：M 到 F/V 没有直接边，直接派会被 `forbidden_edge` 拒）。
十岗 + shared 全部有内容，共 **27 条**。
同轮修掉三处「判据/内容自己的毛病」（都是查了个假面、或人眼看不出来那一类）：
① `validate()` 旧口径用不带工作区根的 `build_registry()` 取工具面 ⇒ `fs.*` 整组不注册、
真名被判成「不在工具面上」；改成按角色 `for_role()`（已过只读过滤）那一份，并加反负控
「工具在注册表里、但本角色拿不到 ⇒ 红」。
② 加 slug 三格机器判据（非空 / 无空白 / 能当文件名 / 全目录唯一）—— 真机里真出现过一条 slug
行首多一个空格、另有一条含空格，两处旧判据全绿；都已改名。
③ shared 两条 skill 声明用 `table.*`，而 M 的工具面里没有库表类工具 ⇒ 改成人人有的 `fs.read`，
正文里写明「库表工具在多数角色手上、主控用 `fs.read` 读同一份 JSON」。
提示词版本 **p106 → p107**（十格摘要全动）；面快照重冻并**逐格走查**（差异 10 条 = 十个角色的
`prompt` 各多出自己那几行索引，`actions`/`tools`/边/计数等其余各格逐字未动）、FC-27 台账签 2 名 reviewer。
**下一件**：③ 的深度（每岗再补 1–2 条，M 继续加素材），§四 那 10 条待审批能力仍等裁决。

**③ 的深度（R114，第三轮调研）**：把 38 个来源里与"研究怎么推进"直接相关的那一批
逐条读完，抽出六组工作逻辑改写成 6 条新 skill —— **M 加三条**（`验收-一份拆解要过四问` /
`失败-三档分类并据此改派` / `留什么-耐久的才落盘`，业主点名"特别给 M 多找素材"）、
**D 加一条**（`立题-精确到能动手`）、**F 加一条**（`拆解-子目标要能独立核`）、
**V 加一条**（`自足-核的是那一行字面`）。目录 **27 → 33 条**；`SURVEY` 按真读过的来源补齐
（M 12 / D 7 / F 7 / V 6，其余各 5–6）。
其中特别值得记的三条纪律（都是从来源里抽出来、再对到我们真实读数上的）：
① **不许把难点藏进含糊的子目标**（"先建立合适的框架"过不了"可独立核"那一关）；
② **失败要指到那一步并分三档**（技术性 / 结构性 / 反例不成立 —— 三档处置完全不同，
一律"再试一次"是浪费）；③ **自由文本的讨论不等于核验结果**（签名落在 `verifications` 那一行）。
提示词 **p107 → p108**，作用域读数：只有 M / D / F / V 四格换值，其余六格**逐字未动**；
面快照逐格走查（六格只差版本行、四格各多出自己新增的那几行索引，其余各格逐字未动）。
§四 新增两条待批（多维聚合裁决 + 多评审者计数；记忆写入的触发判定与路由），并把 #3 / #5
改成"阅读纪律已落地、缺的是**读数与台账字段**"的现状。

**① 的面板回显补齐（R115）**：用户报过一次「设置面板启动后应该同步设置文件里的参数，
不然空空的就像啥都没设置过一样」（2026-10-13），这一轮又抓到同一族的三处**读侧**缺口 ——
它们都不会让任何旧判据变红，表现全是"盘上写了、面板上空的"：
① `SettingsReading.model.vendor` 在 `type_decls()` 里**声明着**、读侧却从没给过
（顶层那个 `ModelSpec` 是现搭的，搭的时候漏了 `vendor`）；
② `models.<槽>` 与 `secretary` 两处的新读数压根没有 `vendor` 这一格；
③ `models.<槽>.key_source` 取的是**全局** `key_source()`（读 `model` 段）⇒
每一档都报同一个来源：`models.A` 明明是从设置文件取的，读数却说"哪儿都没找到"。
修法：`ModelSpec.redacted()` 加 `vendor`；三处读侧都带上 `vendor`；每档的 `key_source`
取**这一档自己的** `spec_for(...)` 结果。面板同时补两处显示：顶层那一行加 `vendor`，
每个角色加一枚"配了（来源 `models.A`）/ 沿用下一档"的徽章 —— 不显的话，
只有点开每一格才知道哪个角色真的配了自己的 key。
判据 9 → **12 条**（`tests/test_role_models.py`），三条新的都**在旧代码下逐条验证过会红**
（vendor 三处回显 / 每档自己的 `key_source` / 读侧覆盖写侧词表且非真空）。
端到端在真起的本地服务上核过：`GET /` 引用的就是新 bundle `index.DpOVMT89.js`，
`GET /api/machine` 回 `model.vendor=deepseek`、`models.A.vendor=deepseek`（`source=models.A`、
`configured=true`）、`secretary.vendor=acme`，且响应里**不含**任何真 key。

**① 的收尾（同一批）**：`agentflow run` / `runflow.run_topic` 那条路此前**没走价目表** ——
`modelcost.price_of` 只读环境变量与缺省价。于是同一个工作区里，多智能体那条按厂商价目表算、
单跑那条按旧缺省价（0.27/1.10）算，**两个数字都自洽、谁也不会报错**。这一批把它收成一处：
「从配置里读厂商与模型」只有 `modelgw.vendor_model_of` 一处实现（含"没配 vendor 就按
`base_url` 的**主机名**认一家"），`price_of` / `price_of_full` / `llmseam._price_now` 都走它；
`runflow` 改成按**这一趟自己的时间戳**取价（`price_of(cfg, at=stamp)`）—— 跑在低谷、收尾时
进峰值的那一趟，读墙钟会被整趟按峰值计价，而账面上看不出来。新加两条判据：
`test_the_two_number_price_also_knows_the_vendor_and_the_clock`、
`test_the_run_prices_at_its_own_timestamp_not_the_wall_clock`（后者含反真空：峰值那趟必须是低谷那趟的两倍）。

**同批清掉的四处旧债**（都是"全量跑才看得见"的那一类）：
① `test_cli_run` 里手抄的单价 `0.00137`（= 0.27/1.10 那对旧价）在换价目表后静默过期，
三个预算类用例全红 ⇒ 改成按 `modelcost` 现算。
② `test_r5_orchestration_cost` 在**导入期** `os.environ.setdefault(AGENTFLOW_MODEL_PEAK, "0")`
—— pytest 收集期就导入全部测试文件，于是它改了整台进程的环境，`test_cost_matches_vendor`
的峰谷判据在全量跑里拿到 `peak_source='env'` 而红、单跑却绿 ⇒ 改成按用例作用域的 autouse fixture，
钟那条判据自己传 `env={}`。
③ `agent_skills.py`（R111 新增）没登记进 `tests/test_release_all._AGENTFLOW_TOP_LEVEL_MODULES`
与 `docs/READING-MAP.md` ⇒ 两条"孤儿模块"判据红；同批修掉 `agent_loop.py` / `runflow.py` 的过期行数。
④ `tests/golden/run_topic_snapshot.json` 自 R106 起就没重冻（差 45 格：旧平价的 0.27/1.10 →
表价 0.15/0.6 及其派生的每一个 usd 数、`reply` 上新增的 `cache_hit_tokens`/`cache_miss_tokens`=null）
⇒ 重冻并**逐格走查**（键级核对过 `result` / `tasks` / `usage`：只有 usd 那几个数动，签名与其余各格逐字未动）、
连同面快照一起登记 FC-27 台账。

## 一、这一阶段要做的四件事（业主原话逐条落点）

### ① 花销口径与「谁能用哪个厂商的哪把 key」

业主原话：「将花销计算标准调整到与模型供应商定价吻合。更新设置面板与相应文件，
允许不同角色智能体用不同模型厂商的不同 api key（所有智能体的秘书另外共用一个 api key）。」

现状（本轮现读）：

| 那一格 | 今天在哪 | 今天是什么样 |
|---|---|---|
| 单价 | `modelcost.py` 的 `DEFAULT_PRICE_IN_USD_PER_M = 0.27` / `DEFAULT_PRICE_OUT_USD_PER_M = 1.10`（可被两条环境变量覆盖） | **一把价**打天下：不分厂商、不分模型、不分缓存命中/未命中 |
| 计价 | `LlmSeam(price=...)` → `modelcost.price_of()` → `usage_ledger.usd` | 每趟按当次 `tokens_in/out × 单价` 记账 |
| 机器设置 | `settings.py`：三段 `toolchain` / `model` / `workspace`，`MODEL_KEYS = (api_key, base_url, name, reasoning_effort)` | **只有一段 `model`**：全部角色共用一把 key、一个端点、一个模型名 |
| 角色拿缝 | `llmseam.LlmSeam.for_role(role, ...)` → `modelgw.spec_from_env()` | 与角色无关：谁都拿同一个 `ModelSpec` |
| 秘书 | `Secretary` 由宿主按角色派生（业主 T14「每唤起一个智能体就自带一个秘书」） | 秘书没有自己的模型缝 ⇒ 谈不上「另外共用一把 key」 |
| 设置面板 | `ui/src/pages/Machine.tsx` + `POST /api/settings`（`webui/writes.py::handle_settings`）+ `GET /api/machine`（`webui/readers.py::_settings_reading`） | 只编辑那一段 `model`；`api_key` 回显恒为掩码 |

要做成什么（**先把口径订死，再动代码**）：

1. **价目表按「厂商 × 模型」落一份**（一处定义），并区分**输入/输出/缓存命中**三类单价 ——
   供应商定价表就是这么给的（DeepSeek 的定价页把 cache hit / cache miss / output 分开）。
   口径来源要写进注释（哪一个厂商、哪一天抓的、单位是「每百万 token 的美元」）。
2. **记账口径改成「这次调用用的是哪一档价」**：`usage_ledger` 里那笔 `usd` 必须能追到
   `(vendor, model, price_tier)`，否则「花销与供应商账单对不上」这件事无法定位。
3. **按角色配模型**：设置文件从「一段 `model`」扩成「一段 `models`（按角色）+ 一段 `secretary`」，
   角色缺档时回落到 `models.default`；秘书那一段**所有角色的秘书共用**（业主点名的第二把 key）。
4. **设置面板**跟上：能按角色填 `vendor / base_url / model / api_key`，能填秘书那一档；
   `api_key` 永远只回显掩码（沿用今天那条纪律，不许为了「看得见」就回显真 key）。
   **回显那一半与编辑那一半同等重要**（R115 补）：面板输入框的初值取自
   `GET /api/machine` 的 `settings`，所以"读侧少一格"的表现就是**盘上写了、面板上永远空的**
   —— 而 placeholder 还会说"盘上没设过"。判据按**写侧词表** `settings.MODEL_KEYS` 判：
   那一份词表里的每一格，`model` / 每个 `models.<槽>` / `secretary` 三处读侧都必须有。
5. 判据：单价表的**唯一来源** + 按角色取缝的回落链 + 秘书那一档真的被用上（三态读数）+
   面板与 `/api/settings` 的键集合一致（不许有一边偷偷多一格）。

### ② 把「该唤起谁」写成按需读的 skills（现做现读）

业主原话：「做提示词增强，将面对不同类型任务应唤起的协作方式写成各智能体的 skills，
以防止前置大量提示词，现做现读。」

形态（本轮定）：skills 落盘成**一目录一文件**（`skills/<角色>/<slug>.md`），
前置提示词里只留**一张极短的索引**（slug + 一句话 + 什么时候读它），
正文按需用 `fs.read` 现读。判据：索引里每一条都必须能在盘上找到那个文件、
且索引不许把正文抄进来（抄了就等于回到「前置塞大量提示词」）。

**"读得到"这一条 R116 才真正判起来**：判据不再只查"那个文件在不在"，而是把**索引表里
印出来的每一行路径逐条喂给真的 `fs.read`**（`build_registry(workspace_root=…)` +
`role=<角色>`），必须读得到、且读到的是那一份（正文里的标题对上）。为什么非这样判不可：
这句话的落点是**三处拼在一起**才成立 —— 索引里那个路径、`materialize` 的落点、
`fs.read` 解析路径用的根；三处各自自洽而拼不上时**没有任何地方会报错**
（模型只会读不到，然后把索引当摆设）。同轮把 `host.py` 里那段内联的落盘 `try/except`
抽成 `host._materialize_skills`（此前一条判据都碰不到它），并修掉"没有工作区时
`materialize(".")` 会把 33 份手册写进**进程当前目录**"——改成"这一格**没做**"并留一条
明说的 note（三态：**没做 ≠ 做好了**）。

业主原话里还有半句：「如果特别适合该智能体职责**可直接写进智能体的前置提示词**」。
**今天的落法是不加**，理由是"重复文本"：前置里已经有**形状表**（`COLLAB_SHAPES`：
`tool` / `summon` / `handoff` / `final` … 什么时候用哪个）与**伙伴表**
（谁能派谁、每个伙伴交付什么），M 那第五条「按任务类型选收件人」正是这两张表的**用法**；
再写进前置就是把同一件事说第三遍，而本仓的纪律是"不留重复文本"
（`COLLAB_SHAPES_TEXT` 上方那段注释记着同一条取舍）。
判断标准留在这里：**只有当一条规则在前置里没有落点、且漏了它的代价不可逆时**，才直接写进去。

**"现做现读"到底省了多少（R114 现算读数）**：33 条操作手册（`agent_skills.py` 1500 余行、
正文约 90 KB）落成盘上 33 个 `.md`，而每个角色的前置提示词里只有**一张索引**：
A 600 / C 606 / H 621 / G 657 / V 698 / F 711 / E 725 / B 741 / D 764 字符（11–12 行），
M 因为自己 8 条而最长 —— **1252 字符 / 17 行**。也就是说：新增 6 条操作手册，
前置只多了 6 行索引。这张读数表就是"防止前置大量提示词"这句话的机器形态
（判据：索引里不许出现正文，`tests/test_agent_skills.py`）。

### ③ 调研科研类 skills 并改写成我们的协作链

业主点名的来源：`D:\Incubator\temp\deepmath\moonshine\assets\skills\builtin`（现读：**38 个** skill，
每个一目录一 `SKILL.md`，带 `name/description/allowed-tools/Execution Steps/Tool Calls/Output Contract`）。
它们调用的工具（`query_memory` / `search_knowledge` / `memory/*.jsonl`）**在我们的系统里不存在**
⇒ 一律只抽**工作逻辑**，改写成「哪一步由哪个角色做、用我们哪一个真实动作」。

硬约束（业主逐字）：不照搬原文；不虚构本系统不存在的动作；每种智能体至少调研 5 个 skill
综合考量（不是硬性给每个角色写 5 个）；定制 skill 必须描述无歧义、准确适配角色、动作都可实现。

**第三轮（R114）逐条读完并抽出的工作逻辑**（每条都改写成"哪一步由谁做、用哪个真动作"）：

| 来源 skill | 抽出的工作逻辑 | 落在哪 |
|---|---|---|
| `propose-subgoal-decomposition` / `propose-research-plan-*` | 方案要**实质不同**（不是同一路线换序）、子目标**可独立核**、依赖显式**无循环**、中间结论**可复用**、每份带**第一个筛选测试**；**不许把难点藏进含糊的子目标** | M`验收-一份拆解要过四问`、F`拆解-子目标要能独立核` |
| `identify-key-failures` | 失败要**指到那一步**并分三档（技术性 / 结构性 / 反例不成立）—— 三档处置完全不同 | M`失败-三档分类并据此改派` |
| `strengthening-agent` | 反复失败后允许"加强"，判据是**澄清数学而不是绕开**；加强过的那条**不算原文的背书** | 同上（接 H 的 `stronger_than_source`） |
| `problem-generator` / `problem-refiner` / `quality-assessor` | 好问题"精确到能动手"而非"有趣"；四问给依据；四档处置 accept/refine/defer/reject；**细化要减少歧义、不是把问题变平凡**；被拒的变体连理由一起留 | D`立题-精确到能动手` |
| `verify-overall` / `verify-correctness-{assumption,computation,logic}` | 送核的命题必须**自足**（假设/定义/范围/论域/结论都在那一行）；三轴逐轴看、**任一轴不过整条不过**；**自由文本讨论不等于核验结果** | V`自足-核的是那一行字面` |
| `memory-trigger-evaluator` / `extract-project-memory` / `problem-solver` | 留"耐久"的（能脱离这轮对话单独读懂），一次性的措辞不落；只跑**最小必要**的那几件抽取 | M`留什么-耐久的才落盘` |

**"动作都可实现"这一条 R117 才把正文也判上**：`actions` 那一格早就在查（存在 + 够得到），
但正文是另一回事 —— 正文里写「你自己去调 `A.run_once`」或「调 `Z.fly_to_moon`」，
声明那一格查得再严也管不到，**而模型照做的对象是正文**。现在正文里每一个
「大写角色.动作」都要**存在 + 从本角色出发够得到**。实测 33 条正文里 3 处够不到，
**三处都是正当的"指到别人"**（「由 D 的 `D.adjudicate` 收口」/「由 **H** 做（`H.review`）」/
「`E.check_formal` 过的那几条」）⇒ 用**具名豁免表** `_BODY_CROSS_REFS` 逐条登记
（理由抄原话），并加一条**反腐烂**判据：登记不成立就报出来请人删掉
（一张永不生效的豁免表会腐烂成"看起来还在挡着什么"）。

`SURVEY` 逐格记录真读过的来源（M 12 / D 7 / F 7 / V 6，其余各 5–6 条，名字都在那 38 个里）。

### ④ 我们做不了但科研 skill 特别推荐的动作：**记录，等审批**

单列一节（本文件 §四）：逐条记「哪个 skill 推荐了什么能力 → 我们缺哪个动作/工具 →
为什么值得实现 / 代价」。**不擅自实现。**

## 二、来源清点（第一轮已读）

`builtin/` 下 38 个 skill（按目录名）：

```
conclusion-manage  construct-counterexamples  construct-counterexamples-neural-network-functions
construct-toy-examples  cross-domain-explore  direct-proving
direct-proving-neural-network-functions  examination-of-special-cases-neural-network-functions
extract-conclusion-memory  extract-project-claims  extract-project-memory  extract-reference-memory
extract-user-memory  identify-key-failures  lemma-prover  literature-survey  math-research-loop
memory-hygiene  memory-trigger-evaluator  pessimistic-verifier  problem-generator
problem-generator-neural-network-functions  problem-refiner  problem-solver  proof-constructor
proof-corrector  propose-research-plan-neural-network-functions  propose-subgoal-decomposition
quality-assessor  query-memory  record-novelty  research-consolidation  strengthening-agent
understanding-problems-neural-network-functions  verify-correctness-assumption
verify-correctness-computation  verify-correctness-logic  verify-overall
```

我们这一侧的「真实动作面」是唯一权威：`capabilities.ACTION_TABLE`（10 角色 / 60 动作）与
`capabilities.ALLOWED_EDGES`（32 条边）。**任何 skill 里出现的动作名都必须在这两张表里存在**，
否则它只能进 §四 的待审批清单。

这句话现在**是机器查的**，不是靠自觉：`agent_skills.validate()` 逐条核
（动作存在 + 从拥有它的角色出发够得到；工具在**该角色自己那一份**已过只读过滤的工具面上；
slug 非空/无空白/能当文件名/全目录唯一），由 `tests/test_agent_skills.py` 六条反负控守着
（虚构动作 / 越权动作 / `when` 空 / 工具在注册表但本角色拿不到 / slug 带空白 / slug 重名）。

## 三、施工顺序（每轮至少完成一件可验证的事）

1. **R106**：本 draft + ① 的价目表与记账口径（先把「单价从哪来、记到哪一格」订死，再动设置面）。
2. **R107**：`settings.models`（按角色）+ `secretary` 那一档 + `llmseam.for_role` 的回落链 + 判据。
3. **R108**：设置面板（`Machine.tsx`）+ `/api/settings` / `/api/machine` 的键集合判据 + 类型再生成。
4. **R109–R113**：② 的 skills 骨架（目录约定 + 索引段 + 判据）与 ③ 的角色 skills
   （先 M，再 B/E/H/V，再 A/C/D/F/G）—— **已落地**（27 条，十岗 + shared 全覆盖）。
   同批把 ① 的最后一处漏网（`runflow`）收进同一处口径。
5. **R114**：③ 的**深度**（第三轮调研 → M 加 3 条、D/F/V 各加 1 条，共 **33 条**；
   `SURVEY` 按真读过的来源补齐；提示词 p107 → p108，只有 M/D/F/V 四格换值）。
6. **R115**：① 的**面板回显**（三处读侧补 `vendor`、每档取自己的 `key_source`、
   面板加"配了没配 + 来源"徽章；判据 9 → 12 条，三条新的都在旧代码下验证过会红；
   端到端在真起的本地服务上核过 URL 与 payload）。
7. **R116**：②③ 的**最后一公里**（`host.py` 那段落盘代码此前一条判据都碰不到，抽成
   `_materialize_skills` 并可判；同轮修掉"没有工作区时把 33 份手册写进进程当前目录"；
   新增**闭环判据**：每个角色索引表里印的每一行路径，用真的 `fs.read` 逐条读得到）。
8. **R117**：④ 的**正文那一半**（`validate()` 加一格：正文里点名的 `角色.动作` 也要
   **存在 + 够得到**；实测 3 处"指到别人"的正当写法用**具名豁免表** `_BODY_CROSS_REFS`
   登记，且登记本身有反腐烂判据；判据 17 → 20 条，非真空核对过：关掉判据那两条负控当场失效）。
9. 每批都跑全套 + FC-27 流程（`noai_gate.py` → `noai_batch_sign.py` → 提交台账）。
10. **下一步**：④ 待审批那些（已 12 条）等业主裁决后再动；③ 继续按需补（重点是让每条
   skill 都指到**真实的读数位置**，而不是再多写条目）。

## 四、待审批：科研 skill 推荐、而我们今天做不到的能力（逐条累积）

> 口径：**只记录，不实现**。每条写清「哪个 skill、要什么能力、我们缺什么、我的判断（该不该做）」。

| # | 来源 skill | 它要的能力 | 我们今天的缺口 | 初步判断 |
|---|---|---|---|---|
| 1 | `math-research-loop` / `extract-*-memory` / `query-memory`（几乎全部） | 跨趟的**结构化科研记忆**（`memory/research_log.jsonl`、按类型的 `verified_conclusion.md`、可查询索引 `*.sqlite`） | 我们有会话记录（`sessions/*.jsonl`）、草稿本（`notes/<角色>.md`）、台账表，但**没有「按类型可查询的结论记忆」**（`query_memory` / `search_knowledge` 这两个工具不存在） | 值得做：它是这批 skill 的地基（「现做现读」也靠它）；但它是**新工具 + 新表**，属架构级改动，等业主裁 |
| 2 | `lemma-prover` / `proof-constructor` / `direct-proving` | 逐引理**交互式**证明推进（一次一个引理、带回溯） | 我们有 `F` 的 `create_plan` / `step` / `attack_plan` 与 Lean 桥（`verify_tools`），但**没有「引理级」的计划对象**（计划是「难题」级） | 值得做的小半步：把 plan 的粒度降到引理；要先看 F 的真机读数 |
| 3 | `verify-correctness-*`（assumption / computation / logic 三条） | 把「验证」拆成**假设、计算、逻辑**三条独立的检查轴 | 我们有 V 的三态复核 + E 的数值/形式化实验 + H 的审校，**没有「按这三条轴分别出结论」的动作** | **R114 把"逐轴看"的阅读纪律写进了 V 的 skill**（用现有的 `V.verify_proof`，不新增动作）；仍然缺的是**逐轴的独立结论 / 独立台账字段 / 谁签哪条轴** —— 那一件等业主裁 |
| 4 | `pessimistic-verifier` | **悲观验证**：默认「这条结论有问题」，找反例优先 | 我们的 V/H 是「审」，没有「默认否定」的把关角色 | 可做：V 的提示词里加一档，成本低；但要业主认这是不是 V 的职责 |
| 5 | `record-novelty` / `quality-assessor` | 新颖性 / 质量**打分**并与既有文献对照（官方口径是加权四维：影响 40% / 可行 25% / 新意 20% / 延展 15%，一次一过并把评审落成 `problem_review`） | 我们没有「新颖性」这一格读数（`relations` 有重复判定，但没有「新不新」），也没有"评分闸门 + 持久化评审"这一件 | **R114 把四问与四档处置（accept/refine/defer/reject）写进了 D 的 skill**（阅读纪律，不落分）；仍然缺的是**打分作为一条读数 + `problem_review` 那种持久化闸门** —— 谨慎：分口径难定死、容易变成自报，建议先不做 |
| 6 | `identify-key-failures` | 从失败里抽出**关键失败模式**并回灌下一轮 | 我们有 `review_findings`、`attack_plans.history`，但没有「失败模式库」 | 与 §四#1 同族（记忆），一起裁 |
| 7 | `cross-domain-explore` | 跨领域类比检索 | `A.search_literature` 能检索，但没有「跨领域」这一维的编排 | 可做：`search_requests` 的 `mode` 里加一档；等业主裁 |
| 8 | `propose-subgoal-decomposition` / `propose-research-plan-*` | 把难题拆成子目标并排序 | 我们有（F 的 `create_plan` + `subgoals`），**只差提示词侧的写法** | 不用新动作：直接改写成 F/D 的 skill |
| 9 | `literature-survey` | 系统性文献综述（检索式、纳入/排除、缺口表） | 我们有检索（`A`）、关系图（`C`）、台账；**没有「综述」这一件产物** | 可做：`documents` 的 `kind` 里加一类 + G 的编排 |
| 10 | `construct-counterexamples` / `construct-toy-examples` | 构造反例 / 玩具例子作为一等动作 | 我们有（E 的实验、D 的立题），没有「反例/玩具例」的**独立交付物** | 值得做：它是数学科研里最常用的两手，建议进「动作表」待批 |
| 11 | `verify-overall`（R114 新读到） | **多维聚合裁决**：三条轴各自跑、**全过才算过**再聚合出一条总结论；且带 `review_count`（一次调用里跑几位独立评审者，缺省不让调用方随便改） | 我们的 V 是**一位**复核者、只出**一条三态**结论；没有"同一份证明跑多位独立评审者再聚合"这一件，也没有聚合裁决的落点 | 值得做：它与 §四#3 是一对（#3 逐轴、这条聚合与多评审者）；但它是**新动作 + 新台账字段**，等业主裁 |
| 12 | `memory-trigger-evaluator`（R114 新读到） | 记忆写入前的**触发判定与路由**：先判"这段材料值不值得记"，再只跑**最小必要**的那几件抽取器，判定回成结构化 JSON（`run` / `skills` / `reason`） | 我们每一趟都在落台账，但**没有"该不该记、记哪几类"这一道判定**（B 的抽取是照派活跑的，不是按触发判的） | 与 §四#1 同族（记忆），一起裁；其中"最小必要"那半条**已写进 M 的 skill**（`留什么-耐久的才落盘`），不需要新动作 |

（本表随每轮调研继续加行；业主批一条我实现一条。）
