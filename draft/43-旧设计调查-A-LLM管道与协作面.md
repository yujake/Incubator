# 旧设计调查 A：LLM 管道残留与「多智能体协作面」

> **题目**：把「多智能体协作时代的 LLM 管道残留」查清。
> **口径**：只写「是什么 / 当年为什么存在 / 今天谁在用 / 有没有负面效果」，不写修改建议。
> **不修改仓库任何文件**；本报告是本次唯一写入。
> **取证范围**：`D:\Incubator\agentflow\projects`（58 个）+ `D:\Incubator\projects`（23 个）= 81 个工作区；
> 140 份 `sessions/*.jsonl`、15435 条事件；4127 行 `data/tasks.json`；2067 份 `out/tasks/*.json`。
> 未做：未跑模型、未出网、未跑全量 pytest。没有 `file:line` 或命令输出支撑的一律写「未核实」。

---

## 0. 一句话结论

今天真机上只有**一条**模型管道在跑：`agent_loop` → `llmseam` → `modelgw`
（5952 次调用全部 `scope="reason"`、`model="deepseek-chat"`、`ok=True`）。另外**三代模型模块**
（`llm` / `llmseam` / `modelclient`+`modelgw`）与**两个几乎同名的判据模块**（`judge` / `judges`）
各自管不同的事、没有一个是重复实现，但它们服务的对象不同代：`llm.py`+`modelclient.py` 服务的是
「B 用模型读文献」，而真机上 B 是**确定性动作**（`scope="extract"` 调用 0 次）。

协作面里，**集体插话与 relay 在真机上一次都没走到**（`agent_interjection*` 0、`agent_summon_request` 0），
而**没有任何机器判据会因为「零条」而报错**；relay 反而是 M 每趟收工前**主动去查了 30 次空队列**。

---

## 1. 总表

「真机计数」的口径见 §7；`—` 表示无法用事件计数回答，另在逐条里给证据。

| # | 机制 | 代码落点 | 当年为什么存在（draft 出处） | 今天谁在用（src / CLI） | 真机计数 | 负面效果 |
|---|---|---|---|---|---|---|
| 1 | `llm.py` 抽取层 | `llm.py:313,819,751` | 离线基线与可插拔模型抽取；引文逐字回查 fail-closed（`llm.py:8-21`） | `extract.py:805,876`、`host.py:75,225`、`projects.py:424`、`pipeline.py:610` | `scope="extract"` 调用 **0** | 有：`llm.py:19` 的「fail-closed 保证引文」与 `projects.py:418` 的「`extractor=None` 时用真模型」在真机都没走到 ⇒ 纸面防线（§2.1） |
| 2 | `llmseam.py` 模型缝（唯一审计入口） | `llmseam.py:129,43` | 一次模型调用 = 一条可审计记录；三态纪律（`llmseam.py:5-9`） | `agent_loop.py:55`、`autonomy.py:60`、`cli.py:1383,1648`、`deliver.py:303`、`host.py:442,464,479`、`judges.py:35` | `llm_call` **5952**，全 `scope=reason`/`ok=True` | 当前未观测到负面效果（它是今天唯一在跑的那条） |
| 3 | `modelgw.py` 网关 | `modelgw.py:259,73-79` | 「在本文件出现之前，全仓 grep `API_KEY`/`httpx`/`base_url` **0 命中**」（`modelgw.py:5-8`） | `llmseam.py:38`、`modelclient.py:45`、`host.py:96`、`cli.py:583`、`projects.py:531`、`runflow.py:127` | 经 `llmseam` 间接 5952 次 | 当前未观测到负面效果（只是被包了一层） |
| 4 | `modelclient.py` 抽取适配器 | `modelclient.py:87,187,62` | 「整条『模型读书 + 逐字回验』的链路在仓里建好了却从没被真模型驱动过」（`modelclient.py:5-9`） | 只有 `host.py:82`、`projects.py:425` | 真机构造 **0** | 有：与 #2/#3 构成**三条记账口径**（§2.2） |
| 5 | `judge.py` 判定缝（`judge_json` 一个函数） | `judge.py:67,38` | 「所有角色用同一个 LLM 缝」，词表唯一来源（`judge.py:4-5`；`draft/29` §3.1） | `llmseam.py:36`（**只用词表**）、`agent_prompts.py:33`、`agent_f/core.py:370` | `judge_json` src 调用 **0** | 有：`draft/28:16108-16109` 记「有定义、零调用点」；今天仍无调用点（§2.3） |
| 6 | `judges.py` 语义判据注册表 | `judges.py:39,42,282,325` | 「`judge.judge_json` 有定义零调用点」这个洞的补法（`judges.py:5-11`） | `deliver.py:35,208`（`gate`）、`agent_h/core.py:71,73`；CLI `gate`（`cli.py:1641`）/`--semantic-review`（`cli.py:2317`） | `delivery_gate` 事件 **0**；`gates/` 目录 0 份 | 有：判据版本号 `j1` 与提示词版本号 `PROMPT_VERSION` 是**两个版本号**（§2.3） |
| 7 | notebook 草稿本 + inbox 收件箱 | `agent_loop.py:863,879,884,2340,2501` | 「人人都能写草稿本，不碰数据面；最近几条进下一次 prompt」（`draft/28:16290,16305`）；留言是不打断同伴的持久通道（`conductor_tools.py:470-472`） | 步循环内建；CLI 无独立动词 | `agent_note` **1011**；`notes/*.md` 65 份（M 55/E 5/H 4/G 1）；`agent_message` **565**、`agent_inbox` **16**、`shape="message"` **10**/5269 | 有：notebook「人人可写」退化成「M 一个人写」（85%）；留言 565:10 ⇒ 主要是**框架日志通道**（§3.1） |
| 8 | 集体插话三件套 | `agent_loop.py:741,764,790,1528-1545,2404` | 用户 2026-10-05 口径「广播改成集体插话发送」（`agent_loop.py:745-747`；`draft/39:346-351,1225`） | 发送口只有 `conductor.stop(notify=True)`（`conductor_tools.py:494`） | `agent_interjection`/`_seen`/`_effect` **0/0/0**；`【插话】` 0 命中 | 有：`statusreport.py:283-284` 为「发了 N 条被读 0 次」写的告警**自身也跑不到**（§3.2） |
| 9 | relay「请代唤」 | `agent_loop.py:91,2265,2303,2329`；`ledger(view="relays")` | 用户原话「至少要能向主控申请唤起别的智能体」（`draft/28:18097-18100`；实现 `draft/28:18138`） | 触发 `_do_summon`/`_do_summon_many`；受理 M 的 `ledger(view="relays")` | `agent_summon_request` **0**；`subject=请代唤` **0**/565；M **查 30 次全空** | 有：**提示词承诺了不存在的路径**，30 次空查是可量化浪费（§3.3） |
| 10 | `final.notify` 强制 | `agent_loop.py:1121-1205,1645-1675,2037-2062` | 「除主控外每个角色收工都要留一份交接手稿」用户 2026-10-05 裁（`agent_loop.py:682-688`） | 步循环内建；派生兜底 `_derived_dispatch_notify:2005` | `shape="final"` **0**/5269；`stop_reason="no_notify"` **0** | 有：强制闸门的唯一触发点从未出现（§3.4） |
| 11 | `--subagents` / `--drive` / `DEFAULT_LLM_LOOPS` | `cli.py:1390,1476-1495`；`host.py:410` | 「哪些动作走模型是部署选择，不是写死的」（`draft/35:332`）；「各角色像主控的 subagent 的部署开关」（`cli.py:1477`） | `run-agent`；默认表刻意空（`host.py:408-409`） | `--subagents` 未核实；`agent_run_start` 116（M 82/G 15/E 12/H 7） | 有：`cli.py:1484-1487` 自记真机代价——替换确定性动作后「3 个 B 各烧 7–8 步、`bad_json_limit`、概念关系一条没涨」（§3.5） |
| 12 | `autonomy.py` 多轮驱动 | `autonomy.py:351,238,72`；`cli.py:1569-1602` | 「`agent_loop` … 一次只跑一轮」的补法（`draft/41-H:88`） | `run-agent --rounds>1` | `autonomy_round` **2**/`autonomy_report` **2**（仅 `p6d`） | 有：两套停止判据并存 ⇒ 行为分叉，注释与实现相反（`draft/41-H:100-108`）（§3.6） |
| 13 | `scheduler.py` 并发/波次/血缘 | `scheduler.py:208,69,289-299` | 同角色多实例并发（`draft/28:18138` 第 3 条）；`lineage` 喂循环判据 | `agent_loop.py:2133,2151,2158` → `conductor.run_plan`（`conductor.py:1416-1426`） | `summon_many` 形状 **689**；带 `instance` 的任务行 **1763** ⇒ **在生产路径真在用** | 有：`lineage` 恒空 ⇒ 循环/深度/扇出零读数（§3.7） |
| 14 | `capabilities` 边表 + `policy` 四道配额 | `capabilities.py:1204`；`policy.py:41-48,258-317` | 谁唤起谁是白名单；「只有总量没有并发 ⇒ 无限扇出」（`draft/13:351`、FC-18） | `policy.check` 九步 | `forbidden_edge` **7**（全是「M 不可被召唤」）；`depth/cycle/fanout/concurrency/budget_exceeded` **全 0** | 有：「看起来有、其实永不响」（`draft/42:159` 逐字写过）（§4.1） |
| 15 | `interactions.admit_*` 在途闸门 | `interactions.py:1125,1189` | 「为什么要拒绝而不是无限排队：无上限的队列会让最关键的那条矛盾也一起变慢」（`interactions.py:1137-1140`；`draft/12:128`、`draft/13:489-500`） | A/C/D/F 的提交路径 | `search_requests` 367 行，**拒绝 0 次**；`reprocess_requests` **81 个工作区全 0 行** | 有：I7 唯一终止条件零实例；I4 整条链零实例（§4.2） |
| 16 | `USAGE_SCOPES` 六档 | `schema.py:2060`；`llmseam.py:43` | 用途归口唯一来源（`modelgw.py:49-53` 解释为什么不各写一份） | `modelgw`/`modelcost`/`llmseam` | 只用 `reason` 一档，另五档 **全 0** | 有：六档里五档零产出（与 `draft/41-G:255-273` 独立普查一致） |

---

## 2. 模型管道

### 2.1 `llm.py` 抽取层——服务于「B 用模型读文献」，而 B 今天是确定性动作

- **是什么**：`RuleExtractor`（`llm.py:313`）、`LLMExtractor`（`:819`，调 `.complete(prompt)->str`
  并逐字回验）、`parse_llm_json`（`:751`）、`NullExtractor`（`:1080`）。
- **当年为什么存在**：`llm.py:8-11` 逐字：「`RuleExtractor` 不是要做出学术级抽取。它的价值是给整条
  A/B 流水线一个确定性的、诚实的基线」；`:16-21`：「对 `LLMExtractor` 而言这靠回验 + 剔除
  （fail-closed）来保证」。
- **今天谁在用**：`extract.py:805,876`、`host.py:75,225`、`projects.py:424`、`pipeline.py:610`；
  `judge.py:29`、`llmseam.py:376,428,646` 只用 `parse_llm_json`。
- **真机计数**：`llm_call` 的 `scope` 只有 `reason`（5952/5952）⇒ `LLMExtractor` 那条
  `scope="extract"` 的路零调用。B 的真机动作是 `run_once`（415 次）/`register_statement`（208 次），
  都不是抽取器构造点。
- **负面效果（具体机制）**：**判据分叉**。`llm.py:19` 把引文防线挂在 `LLMExtractor` 的 fail-closed 上，
  `projects.py:418` 写「`extractor=None` 时用真模型」——两条在真机都没走到；于是「B 的引文防线」
  实际只剩 `quoteverify`/`check_quote` 那条，`llm.py` 那条是纸面防线。
- **`llmseam.py` 那一层（当年为什么存在）**：`llmseam.py:5-9` 逐字：「在它之前，"接模型"这件事在仓里
  有两种纪律：`runflow` 那条流程把 `prompt_version` 落进 run-manifest（可复现），而 C/D 的钩子直接
  `self.llm.complete(prompt)`（没有版本、没有模型名、没有落库的调用记录）。于是同一个问题在两处有两个
  答案」。**是什么**：`LlmSeam`（`:129`）、`SeamCall`（`:51`）、`SEAM_SCOPE="reason"`（`:43`）、
  `build_tool_face`（`:594`）。**谁在用**：`agent_loop.py:55`、`autonomy.py:60`、
  `cli.py:1383,1648`、`deliver.py:303`、`host.py:442,464,479`、`judges.py:35`；CLI 经
  `run-agent`（`cli.py:1457`）与 `gate`（`:1641`）的 `_agent_seam_factory` 造缝。**真机**：
  `llm_call` 5952 条、`prompt_version` 14 档（p18…p34，p34 占 4045）、`not_checked=False`、
  `ok=True` 全真。**测试**：`test_agent_loop.py` 里 27 处引用；另 `test_judge_seam.py`(4)、
  `test_ledger_charging.py`、`test_native_tool_calls.py`。**负面效果**：当前未观测到负面效果
  （只是残留）——但它与 #3/#4 构成三代叠加（§2.3）。

### 2.2 `modelgw.py` 与 `modelclient.py`——网关与它的一个专用适配器

- **是什么**：`ModelGateway`（`modelgw.py:259`）、`MODEL_ERROR_KINDS`（`:56`）、`NOT_CHECKED`（`:68`）、
  `spec_from_env`（`:138`）；`ModelClient`（`modelclient.py:87`）、`client_from_env`（`:187`）、
  `SCOPE_EXTRACT="extract"`（`:62`）。
- **当年为什么存在**：网关自述「在本文件出现之前，全仓 `src/agentflow` 里 grep `API_KEY` /
  `api_key` / `httpx` / `base_url` **0 命中** —— 也就是说 A–H 八个角色从来没有真正调用过模型」
  （`modelgw.py:5-8`）。适配器自述它补 `LLMExtractor`「真实调用点一处都没有」
  （`modelclient.py:5-9`）。
- **今天谁在用**：网关被 `llmseam`/`runflow`/`modelcost` 用（真机 5952 次间接）；适配器只有
  `host.py:82`（`b_extractor`）与 `projects.py:425` 两个调用点。
- **真机计数**：`scope="extract"` 的 `llm_call` **0** ⇒ 适配器在真机未被驱动。
- **测试覆盖**：`test_modelgw.py`(16)、`test_modelclient.py`(6)。
- **负面效果（具体机制）**：**三条记账口径并存**。三层的记账方式不同：

| 层 | 记账方式 | 谁用 | 真机 |
|---|---|---|---|
| `runflow.py` | 自己调 `modelcost.charge_reply`（`runflow.py:1300`） | `agentflow run`（`cli.py:584`） | 未核实（该动词不写 `llm_call`） |
| `llmseam.LlmSeam` | **自己**写账（`llmseam.py:281-285` 明说「为什么不用 `charge_reply`」） | `run-agent` / `gate` | 5952 次 |
| `modelclient.ModelClient` | 走 `modelcost.charge_reply`（`modelclient.py:142`） | 只有 `b_extractor` 两个调用点 | 0 次 |

  `llmseam.py:281-285` 的理由是成立的（`SeamCall` 没有 `attempts` 字段，走 `charge_reply` 会把
  `usd_total = usd × attempts` 算错），但结果是「一次调用花了多少」这个数字**取决于走了哪一代模块**，
  且三代的幂等键命名空间不同（`modelcost.idempotency_key`/`settle_key`/`llmseam.py:327`）。
  真机只有一代在跑 ⇒ 今天观测不到后果；这是**残留的分叉面**，不是活的分叉。

### 2.3 `judge.py` 与 `judges.py`——两个名字近似、职责相邻的模块

- **`judge.py`**（协议层）：`judge_json(llm, prompt, *, point)`（`judge.py:67`）+ 词表
  `JUDGE_PROBLEMS`（`:38`）+ 两个异常（`:49,53`）。自述「所有角色用同一个 LLM 缝」（`:4-5`）。
- **`judges.py`**（内容层）：`CRITERIA` 注册表（`judges.py:42`）+ `Criterion`（`:46`）+
  `judge()`（`:282`）+ `semantic_judge_for()`（`:325`）+ `NEGATIVE_CONTROLS`（`:184`）+
  `JUDGE_VERSION="j1"`（`:39`）。
- **当年为什么存在**：`judges.py:5-11` 逐字：「`judge.judge_json` 在 `draft/28` §178 里被记成
  "有定义、零调用点"：框架里有一处"唯一的 LLM 缝"，但没有任何判据真的走它。而"高观点 / 敢创新 /
  有品味"这三项官能如果只写在提示词里，就等于把质量交给运气」。
- **今天谁在用**：`judge.py` 的三个 import（`llmseam.py:36`、`agent_prompts.py:33`、
  `agent_f/core.py:370`）**都只取词表/字符串**，`judge_json` 本身在 `src/` 仍无调用点。
  `judges.py` 经 `deliver.py:35,208`（`gate` 逐条判据）与 `agent_h/core.py:71,73`
  （`semantic_judge_for(self.llm)` → `review_tools` 的 `semantic_judge=`）。
- **CLI 可达性**：`agentflow gate`（`cli.py:1641-1669`）与 `run-agent --semantic-review`
  （`cli.py:2317`；`host.py:463`）。
- **真机计数**：`delivery_gate` 事件 **0**；`gates/*.json` **0** 份、`work_items.jsonl` **0** 份；
  `--semantic-review` 无会话证据（未核实）。
- **测试覆盖**：`test_judge.py`(13)、`test_judge_seam.py`(4)、`test_judges.py`(17)、
  `test_semantic_review.py`(10)、`test_deliver.py`。
- **负面效果（具体机制）**：
  1. **「唯一缝协议」在语义判据这条路上不成立**：`judge.py:11-22` 的四条三态纪律在
     `judges.judge()`（`judges.py:282-330`）里被重新实现一遍，`judge_json` 没被用。
  2. **两个版本号并存**：`judges.py:37-39` 的 `JUDGE_VERSION="j1"` vs `llmseam` 记的
     `agent_prompts.PROMPT_VERSION`——「这次审的是哪一版判据」与「这次用的是哪版提示词」是两个字段，
     而它们都进同一条会话记录，事后追一次语义判定要拼两个字段。

---

## 3. 角色循环与协作面

### 3.1 notebook 与 inbox——开放给所有人，只有一个调用者

- **notebook**：`note_path`（`agent_loop.py:863`）、`write_note`（`:879`，append-only 落
  `<项目根>/notes/<角色>.md`）、`notebook_digest`（`:884`，最近 6 条进下一条 prompt）、
  `_do_note`（`:2501`）。**当年为什么存在**：`draft/28:16290` 逐字：「**草稿本**：人人可写、
  不碰数据面（这是 C/H 唯一合法的"手"）」；`:16305`：「人人都能写草稿本 `<项目根>/notes/<角色>.md`
  （append-only，最近几条进下一次 prompt）」。**真机**：`agent_note` 1011 条
  （M 897/G 80/E 24/H 10）；`notes/*.md` 65 份非空（M 55/E 5/H 4/G 1），**C/D/F 一份都没有**。
  **负面效果**：「人人可写」退化成「M 一个人写」（55/65 = 85%）；`draft/28:16398` 另记
  「`runs/` 与 `notes/` 无上限……没有保留策略，也没进 CLI 的视图」。
- **inbox**：`read_messages`（`agent_loop.py:815`）、`send_message`（`:837`）、`mark_delivered`
  （`:851`，写 `agent_inbox` 事件 `:857`）、`_do_message`（`:2340`）。**真机**：`agent_message`
  **565** 条，收件人 `#public` 402/G 76/E 57/M 18/H 9/F 3；`agent_inbox` **16**（M 15/G 1）；
  步形状 `message` **10**/5269（0.19%）。**负面效果（具体机制）**：**565:10 的落差**——
  绝大多数留言不是模型主动沟通，而是框架在派活/收工时代写的留痕（`subject` 形如
  「手稿 NNNN：派活：…」）；`mark_delivered` 只发生 16 次 ⇒「谁读过谁的留言」这个读数基本是空的。

### 3.2 集体插话——真机 0 条

- **是什么**：`send_interjection`（`agent_loop.py:741`）、`read_interjections`（`:764`）、
  `mark_interjections_seen`（`:790`）、`_interjection_block`（`:802`）、步循环读取（`:1528-1545`）、
  效果读数 `_record_interjection_effect`（`:2404`）。事件三种：`agent_interjection` /
  `_seen` / `_effect`。
- **当年为什么存在**：`agent_loop.py:745-747` 逐字：「插话与留言的区别不是措辞，是送达方式：
  留言躺在收件箱里等下一趟/下一步被"听"到，而插话由框架在下一步开头单列一段【插话】……
  用户 2026-10-05 的口径："广播改成集体插话发送"」。原始裁定 `draft/39:346-351`；
  实现规格 `draft/39:1225`（编号顺发 `i-0001…`、`is_stop`、`changed_action` 按
  「这一步的调用键与上一步是否不同」判）。
- **今天谁在用**：**唯一发送口**是 `conductor.stop(notify=True)`
  （`tools/conductor_tools.py:478,494`）；读取侧在步循环内建。CLI 的 `stop` 动词（`cli.py:2360`）
  走的是另一个实现（`stopctl` 开关），工具体 `conductor.stop` 由 M 在循环里调。
- **真机计数**：三种事件 **0/0/0**；会话文本里 `【插话】` **0** 命中。
- **测试覆盖**：`test_agent_interjection.py`(5)、`test_stop_tools.py`（已改用插话口径）、
  `test_stop_broadcast.py`。
- **负面效果（具体机制）**：**机制存在但零实例，而文档/读数承诺了它的读数**。
  `statusreport.py:195-215` 专门统计 `interjections`（`sent`/`seen_events`/`changed_action`/
  `unchanged_action`），`:283-284` 还为一种异常写了告警：「发过 N 条插话而**一次都没被读到**
  （`agent_interjection_seen` 0 条）⇒ 那位同伴要么没在跑、要么读插话那一步没走到」——
  而 `sent` 恒为 0，所以这条告警自身也永不触发。

### 3.3 relay「请代唤」——真机 0 条申请，而 M 查了 30 次空队列

- **是什么**：`RELAY_SUBJECT="请代唤"`（`agent_loop.py:91`）、`RELAY_REFUSALS`（`:83` 附近）、
  `_needs_relay`（`:2281`）、`_request_relay`（`:2303`，落 `agent_summon_request` 事件 `:2329`）；
  受理侧 `conductor.ledger(view="relays")`（`fulfilled` 判据）。
- **当年为什么存在**：用户原话在 `draft/28:18097-18100`：「如果互相唤起困难，至少要能向主控申请
  唤起别的智能体做任务。而且各角色智能体的行为应该就像主控的 subagents。」
  实现说明 `draft/28:18138` 第 2 条：「**越权 ⇒ 自动代唤申请**：`_do_summon` 在
  `forbidden_edge` / `depth_exceeded`，**或** `invalid_params` 且目标不在自己的伙伴表里时……
  给 M 发一条 `subject=请代唤` 的留言 + 落一条 `agent_summon_request` 事件；返回里带
  `relay_requested`，`ok` 仍然如实是 `False`。」
  提示词侧 `agent_prompts.py:1450-1456`（「subject 固定写「请代唤」」）；
  M 的义务 `agent_prompts.py:906-907`（「收到 subject=「请代唤」的留言：**本轮内必须处理**」）。
- **今天谁在用**：触发端 `_do_summon`（`:2225`）/`_do_summon_many`（`:2115`）；
  受理端 M 用 `conductor.ledger(view="relays")`。
- **真机计数（关键）**：`agent_summon_request` **0** 条；`agent_message` 里
  `subject` 含「请代唤」**0** 条（565 条逐条扫过）；M **主动调用** `ledger(view="relays")`
  **30 次**、**30 次全空**（`.jsonl` 全文出现「请代唤」的 24 份文件全是**提示词/模型自述**，
  不是申请记录）；`forbidden_edge` 拒了 **7** 次，全部是「M 不可被召唤（NON_SUMMONABLE）」，
  这一档被 `_needs_relay` 排除。
- **测试覆盖**：`test_review_chain_relay.py`(3，脚本化替身：B 够不到 E ⇒ 申请 ⇒ M 派 E)、
  `test_agent_loop.py` 的端到端协同链用例。
- **负面效果（具体机制）**：**「机制存在但零实例 ⇒ 提示词承诺了不存在的路径」，且可量化**。
  `agent_prompts.py:906-907` 把「收到请代唤必须本轮内处理」写成硬义务，M 忠实执行 30 次、
  每次都是空队列；同时 `draft/35:654-655` 自己记了另一半：「**没有任何机器判据**强制 M 处理」
  ⇒「承诺了但不存在」与「存在但无判据」同时成立，而 30 次空查是唯一可观测的后果。

### 3.4 `final.notify` 强制——触发点在现代步事件里为 0

- **是什么**：`notify_shape_problem`（`agent_loop.py:1143`）、`clean_notify`（`:1168`）、
  `_notify_help`（`:1178`）、`_notify_gate`（`:2037`）、`_notify_bounce`（`:1944`）、
  `max_notify_rejections=3`（`:1252`）、`_do_handoff`（`:2361`）；收工支 `:1645-1675`、
  派活支 `:1691-1708`、派生兜底 `_derived_dispatch_notify`（`:2005`）。
- **当年为什么存在**：`agent_loop.py:682-688` 逐字：「收工时被"强制 notify 表"打回的次数
  （`draft/39` §3.2/§3.3，用户 2026-10-05 裁）……"缺留痕"这件事在台账上的形态是"这一趟被打回了几次、
  最后是不是以 `no_notify` 收的"」。
- **真机计数**：`agent_step` 的 shape 分布里**没有 `final`**（5269 步：`tool` 2933/`note` 1007/
  `summon_many` 689/`summon` 506/`invalid` 116/`message` 10/`ask_user` 8）；
  `agent_run_end` 113 条 `stop_reason`：`final` 98/`bad_json_limit` 11/`stop_file` 3/`force_stop` 1，
  **`no_notify` 0 次**；`notify_rejections` 全为 0（24 条）或缺省（89 条）；带 `handoffs` 的 23 条。
- **负面效果（具体机制）**：**强制闸门的唯一入口（`shape=="final"` 过 `_notify_gate`）
  在真机步事件里从未出现**——留痕实际由派活支的派生兜底承担（`handoffs` 23 条）。
  与 `draft/39` 自记的真机读数同向：账本 92/96/118/62/94 行**全是框架派生的模板**、
  `refs` 逐行全空（引在 `specs/m.py:84`），用户原话「handoffs 里面没有几条有效信息全在强调纪律」。

### 3.5 `--subagents` / `--drive` / `host.DEFAULT_LLM_LOOPS`

- **是什么**：`DEFAULT_LLM_LOOPS: dict = {}`（`host.py:410`，注释 `:408-409`：「刻意是空的：
  装配期不许因为"环境里有 key"就改变行为」）；`_parse_drive`（`cli.py:1390`）；
  `--subagents` 展开（`cli.py:1476-1495`）；`wired_llm_conductor(loops=…)`（`host.py:413`）。
- **当年为什么存在**：`cli.py:1477-1483` 逐字：「`--subagents`（2026-09-30）：把所有已声明的角色
  动作都交给模型驱动 —— "各角色像主控的 subagent"这句话的部署开关。为什么是一个显式开关而不是默认值：
  默认驱动一切会把"确定性代码"的活…也换成模型调用」。
- **真机计数**：`--subagents` 是否用过**未核实**（CLI 参数不进会话事件）；间接读数是
  `agent_run_start` 116 条（M 82/G 15/E 12/H 7）⇒ 子循环确实被驱动过 34 次。
- **负面效果（具体机制）**：`cli.py:1484-1487` 自记**真机实测**代价：「把确定性动作 `B.run_once`
  交给 LLM 循环会替换掉那份确定性整理 —— 3 个 B 实例各烧 7–8 步、以 `bad_json_limit` 收场、
  概念与关系一条没涨」（另见 `draft/28:18345`、`draft/35:362`）。即这个开关的语义是
  「用模型循环**替换**确定性动作」，而名字读起来像「让角色更自主」。
- **`autonomy.py` 多轮驱动**：`run_autonomous`（`autonomy.py:351`）、`_stop_before_round`（`:238`）、
  `_round_task`（`:220`）、`RoundReport`（`:127`）、检查点 `autonomy-<角色>.json`（`:72`）、
  `_publish_report`（`:324`）。**当年为什么存在**：`draft/41-H:88` 逐字引 `autonomy.py:1-13`：
  「`autonomy.py` 自述它补的洞是 `agent_loop` … 一次只跑一轮」。**谁在用**：
  `cli.py:1569-1602`（`run-agent --rounds>1`）；`autonomy.py:507` 调 `agent_loop.run_role`；
  测试 `test_autonomy.py`(11)、`test_autonomy_resume.py`。**真机**：`autonomy_round` **2** /
  `autonomy_report` **2**——都在 `p6d-research-from-zero` 一个工作区（两条 report 正文逐字写着
  「第 1/2 轮」「第 2/2 轮」「本轮唤起过：E、E、E、E、G、G」）。
- **`autonomy` 的负面效果（具体机制）**：**两套停止判据并存 ⇒ 行为分叉**
  （`draft/41-H:100-108` 已复现）：
  `cli.py:1562-1563` 在多轮时把 `stop_file` 传 `None`，而 `autonomy.py:507-511` 调 `run_role`
  时**不传 `stop_file`**；步循环在空串时照样读工作区缺省开关（`agent_loop.py:1900-1914`）
  ⇒「轮中途」会被停；同时 `autonomy._stop_before_round` 的「每轮之间」判据（`:268`）在缺省路径下
  恒不成立。`agent_loop.py:1286-1289` 的注释与实现相反（注释说「空串 = 不查这一条」）。
  真机侧印证：4 次开关停止（`stop_file` 3/`force_stop` 1）全在单趟会话。

### 3.6 `scheduler.py`——并发引擎在生产路径**在用**，但血缘判据结构性不可达

- **是什么**：`run_waves`（`scheduler.py:208`）、`TaskCall`（`:46`）、`lineage`（`:69`）、
  `ConcurrencyProbe`（`:144`）、`MemoryBudgetTracker`（`:76`）、别名 `run_tasks`（`:308`）。
- **当年为什么存在**：同角色多实例并发（`draft/28:18138` 第 3 条：「`scheduler.TaskCall.instance` +
  `policy._same_role_other_instance`」）；`draft/13:351`：「只有总量没有并发 ⇒ 无限扇出；
  只有并发没有总量 ⇒ 配额被打爆」。
- **今天谁在用**：`agent_loop._do_summon_many`（`agent_loop.py:2133,2151,2158`）→
  `conductor.run_plan`（`conductor.py:1416-1426`）→ `SC.run_waves`；`_guarded`（`scheduler.py:269`）
  每次调 `conductor.summon(..., lineage=tuple(call.lineage))`（`:289-299`）。
- **真机计数**：`summon_many` 形状 **689** 次（5269 步的 13%）；`tasks` 带 `instance` 的
  **1763** 行/4127 ⇒ 并发引擎确实在跑。
- **负面效果（具体机制）**：**血缘链恒空 ⇒ 循环/深度/扇出三条判据零读数**。本轮独立复算：
  4127 行 task 的 `parent_task_id` **全空**、`depth` **全 = 1**、`called_by` 4112 行 `M`
  （15 行 `cli`）；`refusal_reason` 只有 `invalid_params` 838/`unknown_action` 52/`not_wired` 7/
  `forbidden_edge` 7/`deadline_exceeded` 1，**`cycle_detected`/`depth_exceeded`/`fanout_exceeded`/
  `concurrency_exceeded`/`budget_exceeded` 全 0**（与 `draft/41-A:279-296` 的 B3 同向）。
  合理机制：`TaskCall.lineage` 缺省 `()` 而 `conductor.py:897` 判 `if lineage is not None`
  ⇒ `()` 不触发重建；`_do_summon_many` 构造 `TaskCall` 时不传 `lineage`（`agent_loop.py:2151-2157`），
  M 的 `my_task_id` 为空 ⇒ `parent_task_id=None`（`:2153`）。

---

## 4. 权限/声明层里与「角色当 LLM 智能体」绑定的部分

### 4.1 `capabilities` 边表 + `policy` 四道配额

- **是什么**：`NON_SUMMONABLE`（`capabilities.py:1204`）、`ALLOWED_EDGES`/`CAPABILITIES`/`WRITE_SETS`
  （同文件；`AGENTS.md` 的 auth-audit 条称它是「A–H 调用矩阵的**权威定义**」）；
  消费点 `policy.check` 第 [1][2] 步（`policy.py:252-273`）。四道配额
  `max_depth=3`/`max_fanout=5`/`max_concurrency=4`/`max_tasks_per_run=200`（`policy.py:41-48`），
  判据在 [3]–[7] 步（`:276,287,296,304,312`），`validate()`（`:69-82`）要求四者必须为正数。
- **当年为什么存在**：`draft/28:18125` 第 2 条：「**"要证据"的边被边表截断**：G 够不到 A、
  H 够不到 A/E、C 出边为空；而越权被拒后角色**没有任何下一步**（`forbidden_edge` 就结束了）」
  ——relay（§3.3）就是为这条缺口建的。配额那半边：`draft/13:351` 逐字「只有总量没有并发 ⇒
  无限扇出；只有并发没有总量 ⇒ 配额被打爆」；`policy.py:13-16` 的表格又写一遍
  （「`max_depth` | 每一层都能无限宽」）。
- **真机计数**：`forbidden_edge` **7** 次、`unknown_action` **52**、`not_wired` **7**；
  7 次 `forbidden_edge` **全部**是 `role=M, action=summon` + detail「M 不可被召唤（NON_SUMMONABLE）」，
  同属一个 `task_id=t-0171`。五档结构上限拒绝码（含 `deadline_exceeded` 之外的四档）**全 0**。
- **负面效果（具体机制）**：
  1. **越权确实发生了，但落在一档不会触发 relay 的理由上**（`_needs_relay` 只认
     `forbidden_edge`/`depth_exceeded` + 「`invalid_params` 且目标不在伙伴表」）。
     即**边表截断（当年 relay 的动机）在真机上没产出一次 relay**。
     `invalid_params` 838 次是最大拒绝族，其中「目标不在伙伴表」那一档有多少无法从台账区分
     （`detail` 只有参数报错文本）——**未核实**。
  2. **「看起来有、其实永不响」**。`draft/42:159` 逐字写过这条形态：
     「祖先链恒空 ⇒ 循环/深度/扇出零读数……**"看起来有、其实永不响"的判据比没有更糟：
     它让人以为有护栏**」。补充读数：`max_fanout=5` 与 689 次 `summon_many` 并存，
     而 `summon_many` 的每项仍过一次 `Conductor.summon`（`agent_loop.py:2158` 那批 `TaskCall`
     由 `run_waves` 逐项调）⇒ 扇出计数理应有正读数；具体断点（`conductor.py:877-891` 的
     `Decision` 构造处与 `policy` 实际入参）**未核实**。

- **`interactions.admit_*` 在途闸门（是什么 / 当年为什么存在）**：`admit_search_request`
  （`interactions.py:1125`，I7 在途上限 `DEFAULTS["max_inflight_requests"]=20`（`:153`））、
  `admit_reprocess_request`（`:1189`，I4）、`inflight_requests`（`:1065`）、`reprocess_counts`
  （`:1172`）。两者都「在调用方的 tx 内执行，自己不加锁」（模块 docstring `:29-31`）。
- **当年为什么存在**：`interactions.py:1137-1140` 逐字：「为什么要**拒绝**而不是"无限排队"：
  队列无上限时，提交方（尤其是循环里的 D）永远不会感到压力，于是"知识不足就提问"会退化成
  "每轮都问"，而 A 的产能是固定的 —— 结果是**所有**请求都变慢，包括最关键的那条矛盾。
  显式拒绝会把压力**传导回提交方**」。规格 `draft/13:489-500`（I7）；`draft/12:128`
  「全局在途 ≤20，同级 FIFO；超上限**拒绝新请求**，而不是无限排队」。
- **今天谁在用**：I7 → `agent_a/core.py:63`、`agent_c/core.py:662`、`agent_d/adjudicate.py:311`、
  `agent_f/core.py:673`；I4 → `agent_b/core.py:305`、`agent_f/core.py:758`。
- **真机计数**：`search_requests` **367** 行（`submitted_by`：`agent-F` 155/`unknown` 40/
  `human` 30/`agent-A-*` 多档/`agent-C` 6/`agent-D` 3）；**在途拒绝 0 次**（逐行扫
  `admitted=False` 与「拒绝」关键字零命中）；`reprocess_requests` **81 个工作区全 0 行**、
  `status="rejected"` 0 条。
- **负面效果（具体机制）**：
  1. **I7 闸门零实例**：`interactions.py:1148-1160` 那条「已达上限 20 ⇒ 拒绝新请求」的分支
     从未执行，而它是 `draft/13` §I7 的**唯一**终止条件（`draft/13:497`）。
  2. **D 的缺口提交路径不过这道闸门**（`draft/41-A:92` 的 D-4 用探针复现：「在途 25
     （上限 20、闸门 `admitted=False`）时仍落 `r-0026`，在途变 26」）⇒ 367 行里有一族绕过闸门。
  3. **I4 整条链零实例**：不只闸门，被它管的表 81 个工作区全空 ⇒「重抽取会改数据，所以要有上限」
     这条论证在真机上没有被检验过一次。
  4. **三态回读缺口**：`AGENTS.md` 的 auth-audit 条声明这两个闸门「靠三态位
     （`checked`/`admitted`）保证"没查"与"查过了没问题"分得开」，而 `search_requests` 行里
     没有 `admitted` 字段（本轮读了一行样例）⇒「查过了没问题」这一态在台账上不可回读。
     367 行未逐行核对该字段，**未核实**。

---

## 5. 哪些机制在真机上一次都没走到

| 机制 | 事件/字段 | 真机计数 | 判定 |
|---|---|---|---|
| 集体插话 | `agent_interjection` / `_seen` / `_effect` | 0 / 0 / 0 | 一次未走到 |
| relay 申请 / relay 留言 | `agent_summon_request` / `subject="请代唤"` | 0 / 0 | 一次未走到 |
| relay 受理 | M 查 `ledger(view="relays")` | **30 次，30 次全空** | 走了，但永远是空队列 |
| `final.notify` 强制闸门 | `shape="final"` 的 step | 0 / 5269 | 触发点未出现 |
| `no_notify` 收场 | `agent_run_end.stop_reason` | 0 | 未走到 |
| 交付闸门 + 语义判据 | `delivery_gate` 事件 / `gates/*.json` | 0 / 0 份 | 一次未走到 |
| `LLMExtractor` / `modelclient` | `llm_call.scope == "extract"` | 0 | 一次未走到 |
| `judge.judge_json` | src 调用点 | 0（只有词表被 import） | 一次未走到 |
| I7 在途拒绝 | `admit_search_request` 拒绝分支 | 0 / 367 行请求 | 一次未走到 |
| I4 重抽取配额 | `reprocess_requests` 表 | 0 行 / 81 个工作区 | 一次未走到 |
| 深度/循环/扇出/并发/总量拒绝 | `refusal_reason` | 全 0 / 4127 行任务 | 判据结构性不可达 |
| 多轮自主驱动 | `autonomy_round` | 2（仅 `p6d`） | 走到过，只一次 |
| 子循环（非 M 的 `--drive`） | `agent_run_start` 非 M | 34（G 15/E 12/H 7） | 走到过 |
| 并发/波次引擎 | `summon_many` / 带 `instance` 的任务行 | 689 / 1763 | **在生产路径真在用** |

---

## 6. 哪些是「为一种从未发生的协作形态而设计的」

按「设计意图 → 真机形态」给四组，判据全用上表计数：

1. **「角色之间会互相呼唤、够不到就请主控代唤」（relay 整条链）**。意图逐字在
   `draft/28:18097-18100`；实现完备（触发/落事件/发留言/可判定队列 `fulfilled`）；
   真机 `agent_summon_request` **0**、`subject=请代唤` **0**，而 M 忠实执行提示词义务
   **30 次空查**。这是最干净的一条「为从未发生的形态而建」。
2. **「用户/主控会在循环中途插话，框架读『有没有改变做法』」**。意图在 `draft/39:346-351`；
   三种事件全 0；专为它写的读数（`statusreport.py:195-215`）与告警（`:283-284`）也没有现场。
3. **「每个角色都是 LLM 智能体，因此需要一套语义判据与一套抽取管线」**。
   `judge.py` 的「所有角色用同一个 LLM 缝」（`judge.py:4-5`）与 `judges.py` 的逐官能判据表服务的是
   这个形态；真机只有一个角色（M）跑 LLM 循环，`delivery_gate` **0** 条；
   另一半 `modelclient`+`LLMExtractor` 的 `scope="extract"` 也是 **0**。
4. **「嵌套召唤会形成链，因此需要深度/循环/扇出/并发四道闸」**。意图在 `draft/13:351` 与 FC-18；
   真机 4127 行 `depth` 全 = 1、`parent_task_id` 全空、五档拒绝码全 0。
   **反例同时存在**：并发引擎（`summon_many` → `scheduler.run_waves`）确实在用（689/1763）
   ⇒ 这一族的正确切分是「并发那一半活着，血缘/深度那一半空转」。

---

## 7. 复算命令

全部只读、不出网、不跑 pytest。工作目录 `D:\Incubator`。下面 3 段按顺序执行，输出即本报告引用的全部真机读数。

**(1) 会话事件：kind 分布 + `llm_call` 三态 + 留言主题 + 步形状（证明没有 `final`）**

```powershell
python -B -c "
import json,glob,collections
c=collections.Counter(); s=collections.Counter(); sb=collections.Counter(); sh=collections.Counter()
W=glob.glob('D:/Incubator/agentflow/projects/*/sessions/*.jsonl')+glob.glob('D:/Incubator/projects/*/sessions/*.jsonl')
for f in W:
 for ln in open(f,encoding='utf-8',errors='replace'):
  try: o=json.loads(ln)
  except Exception: continue
  k=str(o.get('kind') or ''); c[k]+=1
  if k=='llm_call': s[(o.get('scope'),o.get('model'),o.get('ok'),o.get('not_checked'))]+=1
  if k=='agent_message': sb[str(o.get('subject'))[:30]]+=1
  if k=='agent_step': sh[str(o.get('shape'))]+=1
print(dict(c)); print(dict(s)); print(sum(sb.values()),sum(v for k,v in sb.items() if '请代唤' in k)); print(dict(sh))
"
```

**(2) 插话/relay 零实例 + M 查 relays 的次数与结果（30 次全空）**

```powershell
python -B -c "
import json,glob,collections
m=collections.Counter(); g=collections.Counter()
W=glob.glob('D:/Incubator/agentflow/projects/*/sessions/*.jsonl')+glob.glob('D:/Incubator/projects/*/sessions/*.jsonl')
for f in W:
 for ln in open(f,encoding='utf-8',errors='replace'):
  try: o=json.loads(ln)
  except Exception: continue
  k=str(o.get('kind') or '')
  if 'interjection' in k or k=='agent_summon_request': m[k]+=1
  if k=='agent_step' and 'relays' in str(((o.get('payload') or {}).get('args') or {}).get('view') or ''):
   g['calls']+=1
   g['has_relay' if 'relay_pending' in json.dumps(o.get('result') or {},ensure_ascii=False) else 'no_relay']+=1
print(dict(m)); print(dict(g))
"
```

**(3) 任务台账（拒绝原因/深度/父任务/实例）+ 配额闸门是否响过 + 测试覆盖计数**

```powershell
python -B -c "
import json,glob,collections
c=collections.Counter(); n=0; q=collections.Counter()
for root in ('D:/Incubator/agentflow/projects','D:/Incubator/projects'):
 for f in glob.glob(root+'/*/data/tasks.json'):
  try: d=json.load(open(f,encoding='utf-8'))
  except Exception: continue
  rows=d if isinstance(d,list) else (d.get('rows') if isinstance(d,dict) else [])
  for r in rows if isinstance(rows,list) else []:
   if isinstance(r,dict):
    n+=1
    c['rr:'+str(r.get('refusal_reason') or '-')]+=1; c['depth:'+str(r.get('depth'))]+=1
    c['parent_none' if not r.get('parent_task_id') else 'parent_set']+=1
    if r.get('instance'): c['instance_set']+=1
 for f in glob.glob(root+'/*/data/search_requests.json'):
  for r in json.load(open(f,encoding='utf-8')) or []:
   q['search_rows']+=1
   if r.get('admitted') is False or '拒绝' in str(r.get('admit_reason') or ''): q['search_rejected']+=1
 for f in glob.glob(root+'/*/data/reprocess_requests.json'):
  q['reprocess_rows']+=len(json.load(open(f,encoding='utf-8')) or [])
print('rows',n); print(dict(c)); print(dict(q))
"
Select-String -Path tests/test_judge.py,tests/test_judge_seam.py,tests/test_judges.py,tests/test_modelgw.py,tests/test_modelclient.py,tests/test_agent_interjection.py,tests/test_review_chain_relay.py,tests/test_forced_notify.py,tests/test_semantic_review.py,tests/test_autonomy.py -Pattern '^def test_' | Group-Object Filename | ForEach-Object { "$($_.Count)  $($_.Name)" }
```

## 8. 未核实项（不许折成「没问题」）

1. `--subagents` 是否在真机用过：CLI 参数不进会话事件。
2. `--semantic-review` 的真机 `claims_semantically_judged` 值：81 个工作区里没有
   `delivery_gate` 事件，该读数只出现在 `out/` 报告里。
3. `runflow`（`agentflow run`，`cli.py:584`）那条 `charge_reply` 记账路的真机次数：该动词不写
   `llm_call` 事件。
4. `policy` 的 `fanout`/`running`/`total` 三个计数入参在真机路径上填了什么：本报告只核实了
   「对应拒绝码全 0」，没逐行走查 `conductor.py:877-891` 的 `Decision` 构造处。
5. `invalid_params` 838 次里「目标不在伙伴表」（该转 relay 的那一档）有多少：`detail` 只有参数
   报错文本，无法从台账区分；`search_requests` 行是否有 `admitted` 字段也只核了一行样例。
6. `agent_run_artifact` 33 条 vs `agent_run_start` 116 条的差额归属（哪一档不落产物）。
