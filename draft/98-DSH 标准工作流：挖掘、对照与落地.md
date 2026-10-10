# draft/98 —— DSH 标准工作流：挖掘、对照与落地

> 业主 2026-10-10（第 146 轮）指令逐字：
> 「每个智能体执行思考、工具调用等等，及上下文管理、及决策等等东西，其执行格式可以用 dsh，
> 其实现方式我们已经做好。即我们接下来做的是将 dsh 中标准工作流挖来，让我们的每个智能体
> 自己干活时用」
>
> 本页就是这件事的第一步：**把 DSH 的标准工作流挖出来、逐条对照我们今天的形态、
> 排出落地顺序**。口径按指令原文读成两半：**形状照 DSH**（执行格式：思考 / 工具调用 /
> 上下文管理 / 决策的表示法），**实现用我们已有的**（`modelgw` / `llmseam` / `agent_loop` /
> `promptkit` / `tools/` / `conductor` / `secretary` 都不重写）。

## §0 读法与出处（本页每条都能被复核）

- DSH 装在本机：`C:\Users\ysc20\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\node_modules\@deepseek-ai\`。
- 每个包自带的 `README.zh.md` 就是它的**权威规格**（DSH 自己的约定：可观察行为写在
  README，`lib/index.js` 是实现）。本页的引用形如 `dsh-agent-loop/README.zh.md:119`。
- 本页只写"读到的"，读不到就写「未读到」；不把推测写成规格。
- 相关包共 **172 个**（`@deepseek-ai/dsh-*`），与"一个智能体自己干活"直接相关的是一小组：
  `dsh-agent-loop`（循环本体）、`dsh-agent`（agent 句柄与事件）、`dsh-system-prompt` +
  `dsh-agent-instructions`（提示词装配）、`dsh-tools` + `dsh-tool-*`（工具契约）、
  `dsh-compaction*` + `dsh-output-retention` + `dsh-spill*`（上下文管理）、
  `dsh-session*`（会话记录）、`dsh-plan-mode` / `dsh-goal` / `dsh-tool-todo` /
  `dsh-tool-subagent` / `dsh-user-approval`（决策闸门）。
  **本页先落最核心的一件：`dsh-agent-loop` 的一步/一轮是什么形状**，随后把另外四组
  （提示词装配 / 会话回合 / 上下文管理 / 工具契约与决策闸门）逐组归拢。
- **状态（本页写作的当轮就写完）**：五组都在本页（§1–§5 循环核心、§7 提示词、§8 会话回合、
  §9 上下文管理、§10 工具与闸门），候选批次 **B1–B10** 见各节末与 §11。**只有计划，没有代码** ——
  业主当轮的口径是"现在全在写计划书，不动代码"。

## §1 一个「步骤」做什么（DSH 的原文口径）

`dsh-agent-loop/README.zh.md:75` 逐字（一段话把整个循环说完了）：

> 每个步骤都会发送会话的派生历史——最新的非空 `system/message` 节点是有效提示词，
> 渲染提示词为空时则没有系统消息——及其可见工具 schema；模型的工具调用经过受守卫的
> 工具流水线，每个被接纳的事实都会在下一步据此派生之前追加到会话日志。并行安全调用
> 最多可重叠 `maxParallelToolCalls` 个；独占调用单独运行并构成排序屏障。取消是协作式的：
> `agent.cancel()` 中止当前活动，并在未设置 `keepInbox` 时清除待处理工作；被取消的流会
> 终结已送达用户的文本。

拆成五条可落地的形状：

1. **每步发的是"派生历史"**，不是"一句拼好的提示词"：历史 = 会话日志里那一串表层消息
   （`dsh-agent-loop/README.zh.md:166`：「已接纳的 user 消息、assistant 消息、工具调用与结果、
   注入上下文与 steering 都会记录，并在后续步骤中发送。原始流分片、生命周期边界与其他
   仅写入日志的事件会被排除」）。
2. **提示词是历史里的一个节点**（`system/message`），**最新一条非空的就是有效提示词**；
   渲染为空 ⇒ 历史里一条系统消息都没有。**请求体里没有 `system` 字段**
   （`dsh-agent-loop/README.zh.md:119`：「请求由 `header.config`、`deriveMessages()` 与
   `header.tools` 构成，不携带 `system` 字段」）。
3. **工具 schema 与历史一起发**，且 schema 变化本身是"换序列"的三种原因之一（§3）。
4. **每个被接纳的事实先落日志、再由日志派生下一步**（append-only + derive）。这条是
   整套东西的地基：模型看到的东西永远等于日志里记着的东西。
5. **并行是分类的，不是开关**：并行安全调用有界重叠（`maxParallelToolCalls`，默认 10）；
   **独占调用单独跑并充当排序屏障**；「策略、持久结果与结果上下文保持模型顺序」
   （`:119` 末句）。已知限制一句：分类是**一元**的（`:197`「安全性取决于比较同级调用或
   资源的调用必须保持独占」）。

## §2 轮次与步骤的九步流程（`dsh-agent-loop/README.zh.md:119` 的顺序，逐条抄）

| # | DSH 做什么 | 关键点（读到的原话） |
|---|---|---|
| 1 | 轮次边界：先打开**持久轮次**，再**原子领取**待处理的 next-step 输入与一条排队提示词；步骤之间只领取 next-step 输入 | "原子领取" ⇒ 并发下不会两个步骤领到同一条 |
| 2 | 组装提示词与工具、**投影 runtime 上下文**、运行 `agent/pre-step` | 「被拒绝的决定或空的首批输入**不打开步骤**」 |
| 3 | 首次尝试：记 `step/start` → 跑 `agent/request` waterfall 与 `prepareCall()` | 这两个异步阶段看不到"待提交的系统提示词与已接纳用户消息" |
| 4 | 协调渲染提示词与存活 `system/message` 节点；**仅首次尝试**追加已接纳的 `user/message` 批次；按需记 header 与 context | 提示词准入的规则见 §3 |
| 5 | 派生并**深冻结**请求，经绑定的已准备调用发起流式请求 | 冻结证明按消息对象复用（§5） |
| 6 | 重试**复用同一份已渲染组装结果**：不重复组装、不重复 `agent/pre-step`、不重复用户消息准入 | "重试不是一个新步骤" |
| 7 | 每次模型尝试发一个进程本地 `start`；只在匹配的持久 assistant-frame 结算后才发 `chunk`；**恰好一个终态 `end`** | 最终组装或消息追加失败 ⇒ 以 `aborted` 结算；`committed` 出现在持久 `assistant/message` 之后 |
| 8 | 流被取消 ⇒ 追加带 `interrupted: true` 的锚点并**携带已交付前缀** | "使下一次请求包含用户看到的内容" |
| 9 | 步骤内：独占调用形成屏障；并行安全调用用**有界滚动池**；顺序保持 | 见 §1 第 5 条 |

另外两条与"收工/预算"直接相关（`:200`）：**没有内置轮次预算** —— 「工具调用或 steering 会让
当前轮次继续；限制失控轮次的策略必须从既有生命周期扩展点（如 `agent/turn-stopping`）执行取消」。
⇒ DSH 把"什么时候收工"留给策略层，而不是写死在循环里。**这一条与业主第 146 轮第 1 条
裁定（收工由 M 判）是同一条纪律的两种说法。**

## §3 提示词准入：四类事件 + 三种"换序列"（本页最值得抄的一段）

`dsh-agent-loop/README.zh.md:121` 是一整段（本页只摘判据，不摘实现）：

| 情形 | DSH 的处置 | 为什么 |
|---|---|---|
| 没有系统节点 | 即使提示词为空也**追加**（预留第 0 号节点，但不产生协议消息） | 节点是锚，位置要稳定 |
| 路由**不具备** `systemPromptUpdate: in-history`，或**新序列**开始 | 非空渲染文本**归并到首个系统节点**；每个非空的后续系统节点收到有日志记录的**空内容替换**，随后按需重写头节点 | 旧指令必须消失（"模型不会继续看到旧指令"） |
| 延续中的 `in-history` 序列 | 有效提示词不变 ⇒ **不产生事件**；非空变更 ⇒ **追加**到已缓存历史之后 | KV cache：直到历史末尾的前缀仍可复用 |
| 渲染文本变空 | 逐节点空内容替换清掉每个非空后续节点，再按需清空头节点；**重复清除与恢复会话都保持为空** | 幂等 |
| **开启新序列**的三种情况 | ① pre-step 决定声明 `startsRequestSeries`；② surface 替换（压缩或任何替换）generation 变化；③ **可见工具 schema 变化** | 恢复与单纯的 provider/model 切换**延续**序列 |

准入的判据来源有一句话很硬（`:121` 首句）：**「提示词准入依据实际的 `prepareCall()` 结果，
而非先前的 `request/context`」** —— 即"我以为路由支持"不算，要拿这次真实解析出来的能力。

## §4 工具流水线 / 失败 / 取消 / 冻结（读到的形状，留给下一批细挖）

- **守卫**：工具调用经过"受守卫的工具流水线"（`:75`）；参数校验、超时策略、重复调用提醒分别在
  `dsh-tools` / `dsh-tool-call-timeout-policy` / `dsh-repeat-tool-reminder`（下一批归拢）。
- **取消的两个形态**：未分发的调用收到合成的一对 `tool/call` + `ABORTED_BEFORE_DISPATCH`
  （结果文本 `Error: tool call aborted before dispatch`，`:180`）；已流式交付的文本**保留**
  并以 `interrupted: true` 锚点回放（`:75`、`:119`）。
- **失败分层**（`:125`）：最终适配器选择/分发/迭代失败 ⇒ `agent/request-error`，有恢复权的
  监听器可回 `{kind:'retry'}`，**未被处理即终态**；middleware / 结果处理 / 工具 / 扩展失败
  ⇒ 抛出并**直接关闭轮次**（"插件失败结束的是轮次，不是循环"）。
- **冻结与派生**（`:95`、`:119`）：每条派生消息对象**首次进入请求时深冻结**，同一 agent 内
  复用该证明；恢复的消息保留对象身份；**构造请求不冻结事件包装对象**；请求 = header.config +
  deriveMessages() + header.tools。
- **写所有权与崩溃修复**（`:115`）：`create` ⇒ `persistence.create(header)`（发布前取得写所有权）；
  `resume` ⇒ 先 `open(id,'write')`（**排除同 id 的并发恢复**），并把"在轮次中途崩溃的日志"
  用 `interruptedTurnClosers` 作为普通批次补上 —— 而**语义崩溃修复是 agent 层的职责，
  不是存储入口的**。⇒ 与我们"三态纪律 + 审计面"同族，且给了"一半的轮次"该长什么样。

## §5 与 agentflow 的逐条对照（有 / 缺 / 不一致）

我们今天的形态（复核过的实测）：`agent_loop.py:2211` 起是 `for step in range(...)`，
`transcript += _step_line(...)`（`agent_loop.py:544`）累积**一整段文本**，
`_prompt(transcript, step=step)`（`:1912`）把这段文本 + 协议尾 + 预算 + `JSON_TAIL`
拼成**一条 user 消息**，`system = AP.system_prompt(...)`（`:2153`）另发一条系统消息。

| DSH 的条目 | agentflow 今天 | 状态 | 最小落点 |
|---|---|---|---|
| 每步发**派生历史**（消息序列） | 每步发**一整段拼好的 transcript**（一条 user 消息） | **不一致（结构性）** | `agent_loop._prompt` + `_step_line`：把 `transcript: str` 换成 `messages: list[dict]`（`role` 三态 + `tool_calls` / `tool` 结果），会话日志仍是权威来源 |
| 提示词是**历史里的节点**，请求不带 `system` | 提示词走请求的 `system` 字段（`modelgw._payload` 拼 `{"role":"system"}`） | **不一致** | 短期：`llmseam.ask_step` 已能把 system 与 messages 分开送（`modelgw.complete(system=...)`）；长期按 DSH 归并规则做"新序列 ⇒ 归并到头部" |
| **工具结果**是历史里的 `tool` 消息 | 工具结果进 `transcript` 的文本行（`_payload_line` / `_bad_args_line`） | **不一致** | 与第一条同一处；原生 `tool_calls` 那条路已经有真 `tool_call_id`（`ModelReply.tool_calls`） |
| assistant 帧有 `start/chunk/end` + **恰好一个终态** | 有 `agent_step` 事件（`llm_call` 记 ok/problem/tokens/usd） | **部分有** | 会话事件加"step 的终态"字段，或按 DSH 的 `committed` / `aborted` 两值收敛 |
| 被取消的流保留**已交付前缀** + `interrupted: true` | 取消 ⇒ 停机开关 + `stop_reason`（`agent_run_end`） | **有读数、缺前缀回放** | `LoopRun.stop_reason` 已有；补"已交付文本进 transcript"（续跑那一趟已能重建 transcript，`resume_transcript`） |
| 并行安全调用**有界滚动池** + 独占屏障 | `maxParallelToolCalls` 无；并行在**代理层**（`conductor` 的扇出、`instance`） | **不同层** | 我们不需要同层并行（一步一件事是刻意的）；只需把这条写进对照表，避免误抄 |
| **没有内置轮次预算**，收工交策略 | `max_steps` / `usd_budget` / `wall_clock_sec` 在循环里 | **比 DSH 强**（保留） | 无（这是我们的裁定第 1、3 条要的形态） |
| 提示词**深冻结**（进请求即冻结） | 无（`str` 不可变，天然安全） | **不适用** | 无 |
| 写所有权 `open(id,'write')` 排除并发恢复 | `sessions.append` 用 `filelock` 串行化；续跑按 sid | **有（弱形式）** | 若上"两趟同 sid 并跑"，要按 DSH 的写所有权补闸门 |
| `interruptedTurnClosers`（崩溃轮次补尾） | `rebuild()` 从事件日志重放；`agent_run_end` 缺行时无补 | **缺** | `closing` 或 `sessions` 加"上一趟没有 `agent_run_end` ⇒ 补一条 `interrupted` 读数" |
| `prepareCall()` 决定**提示词准入**（"实际能力"说了算） | 无对应物（我们每步都发同一份 system） | **缺** | 与第 2 条一起落 |
| **三种换序列**：pre-step 声明 / 压缩 / 工具 schema 变化 | 无（每步 system 逐字相同 ⇒ 事实上没有"换序列"这回事） | **缺** | 一旦按 DSH 做节点化准入，这三条必须一起落（否则漂移） |

一句话结论：**我们与 DSH 的差不是"没有循环"，而是"每步的形状"** —— 我们把一条消息序列
压成了一段字符串（`transcript`），于是 DSH 那一整套"历史 / 节点 / 序列 / 冻结 / 前缀回放"
在我们的读数里根本不存在。

## §6 落地顺序（按"价值 ÷ 风险"排，每批带判据形态）

**B1（最小、最高价值）：把"每步的历史"从文本换成消息序列。**
- 落点：`agent_loop._step_line` / `_prompt` / `LoopRun.transcript`；会话日志与
  `resume_transcript` 的**逐字节相等**判据（`tests/test_user_channel_stop_and_resume.py:288`
  的 `test_resume_transcript_is_byte_equal_to_the_live_transcript`）
  是这一批必须保住的既有资产 —— 换成序列之后它要改成"重建出来的序列逐条相等"。
- 判据：① 正控 —— 一次两步的循环，第二步发给模型的是 `[system, user, assistant(tool_calls), tool]`
  四条，且第 4 条的 `tool_call_id` 等于第 3 条给的 id；② 负控 —— 把 `tool` 消息错挂到别的 id ⇒
  夹具当场红；③ 反真空 —— 序列里 assistant 那条**必须**带工具调用（否则这条判据只测了拼接）。

**B2：提示词节点化 + 三类"换序列"。**
- 落点：`llmseam.ask_step`（把 system 与 messages 分开送）+ `modelgw`（已支持 `system=`）；
  序列边界按 DSH 的三条（pre-step 声明 / 压缩 / 工具面变化）。
- 判据：① 同一序列内 system 逐字不变 ⇒ 请求里**不出现**第二次 system；② 工具面变化 ⇒
  下一次请求"归并到头部"（不是追加第二条 system）；③ 负控：把"追加"写成"改写"会命中
  `test_...sequence` 的断言。

**B3（口径已按挖掘结果更正）：把已有的 `contextbudget` 接进循环的步骤边界。**
- **先更正一处我自己的想当然**：agentflow **不是**"没有上下文管理" ——
  `src/agentflow/contextbudget.py`（725 行，FC-17）已经实现 prune / spill / compact 三件套，
  `config.yaml` 的 `context_budget:` 块也开满了（`threshold_chars 8000` / `head 3000` /
  `tail 1000` / `max_inline_bytes 64000` / `compaction_threshold_chars 200000` /
  `compaction_keep_recent 8`）。**真正的缺口是：`compact()` 在生产代码里从未被调用** ——
  全仓 `compact` 命中只有 `contextbudget` 自己、判据、以及 `cli.py:2213` 一个无关的
  `--compact` 开关；`agent_loop.py` 根本不 import 它，循环的 `transcript` 是单一累加字符串
  （`transcript += _step_line(...)` L2561 → `self.seam.ask_step(self._prompt(transcript,...))` L2256），
  **没有阈值、没有压缩、没有窗口读数**。唯一在产线上跑的是 `tools/base.py:1504-1509` 的自动剪枝。
- 最小落点（子代理给的）：在 `agent_loop.py` 的步骤边界（L2237 读插话之前、L2256 `ask_step` 之前）
  加一次 pre-step 判定：把 `agent_step` 事件重建成条目列表 → `contextbudget.load_budget(config)`
  → 超阈值时 `contextbudget.compact(items, budget=…, summarize=None)` → 用返回的 `text`
  替换/前置 transcript 段，并把 `CompactResult.reason` 作为三态审计写进事件。
- **两条刻意的不一致（不许"顺手改成 DSH 那样"）**：
  ① `summarize=None` 走**机械摘要**是刻意的（FC-16 确定性；`contextbudget.py:520-523`
  自陈"默认路径绝不调 LLM"）—— DSH 是 LLM 摘要，我们不是；
  ② `config.yaml` 的 `context_budget` 数值有钉值判据（`tests/test_context_budget.py:116-120`），
  改数值前先看它们。
- 判据：① 正控 —— 造一段超阈值的 transcript，步骤边界真的发生一次压缩（`agent_step` 里能看到
  读数）；② 负控 —— 未超阈值时**一次也不压**（"没压"与"压了没效果"必须分开）；
  ③ 反真空 —— 压缩后转录里**仍然有**节点 0 的任务原文（DSH 的不变量：系统提示词/前缀永不遮蔽）；
  ④ 三态 —— 容量读不到（`unmeasurable`）时既不静默当零、也不阻断这一趟。

**B4（子代理报上来的最高优先级缺口）：文件"读后写"（观察策略）。**
- DSH 是**强制判据**：`fs/edit-intent` 未见 ⇒ 拒 `FS_NOT_OBSERVED`（原话
  `edit requires reading "<path>" first`，`dsh-fs-observation-policy/README.zh.md:46`）；
  观测过的版本变了 ⇒ `FS_STALE_VERSION` 并追加 `— re-read the file, then retry`（`:109`）；
  "读缺失路径授权带防护的创建"（`:12`）；**观察状态不持久化**，恢复的会话必须重读（`:12`、`:82`）。
- 我们今天的形态：`fs_edit` 的 `sha256` 是**可选**参数（`src/agentflow/tools/fs_tools.py:667`），
  `fs_write` 没有闸 ⇒ 可以静默覆盖一个从没读过的文件。**代价不可逆**（这正是业主对
  M 用 `fs.write` 重写正文那一类事故的顾虑）。
- 判据：① 正控 —— 没读过就 `fs.edit` ⇒ 拒，错误码与 DSH 同形（`not_observed`）；
  ② 正控 —— 读过、版本一致 ⇒ 放行；③ 负控 —— 读完之后文件被别处改过 ⇒ 拒 `stale_version`；
  ④ 反真空 —— 恢复会话（观察表为空）时，正控必须仍然拒（"没观察过"不许被当成"观察过且没变"）。

**B5：重复工具调用提醒的"建议 / 判停"拆分。**
- DSH 只提醒、绝不阻止（`dsh-repeat-tool-reminder/README.zh.md:12`），阈值为 `[3,5,8]`
  且**第 3 次**才提醒；我们同一读数（`dead_loop_nudge=3`）会升级成 `no_progress_limit`
  **判停**（`agent_loop.py:2533/2570`）。
- 这不是"谁对谁错"：我们的判停是刻意的（业主裁定"收工由 M 判"之后仍要防死循环）。
  ⇒ 结论写进计划：**提醒照 DSH 的形状（可选），判停保留为我们的策略**，两者在读数上分开。

**B6：推理内容（`reasoning_content`）要不要回放。**
- DSH 逐字：「此前 assistant 轮次的推理内容会原样传回，无论该轮次是否调用了工具」
  （`dsh-llm-deepseek/README.zh.md:155`）。
- 我们刚落的形态（`8fbb6e5`）：收到 `ModelReply.reasoning` 但**只记字数**、不回放
  （`llmseam.SeamCall.reasoning_chars`）—— 这是一个**声明过的取舍**（省 token、避免把思维链
  当正文）。
- ⇒ 这一条要业主裁：回放（DSH 形态，KV cache 友好但与我们的"思维链绝不进正文"纪律要划清界）
  还是保持只记字数。**本轮不动代码。**

## §7 挖到的第二组：提示词与指令装配（DSH ↔ 我们）

出处：`dsh-system-prompt` / `dsh-agent-instructions` / `dsh-persona` / `dsh-agent-presets` /
`dsh-agent` 的 `README.zh.md` 与 `lib/index.js`。

**§7.1 DSH 的装配顺序（权威表 `dsh-system-prompt/lib/index.js:10-42` 的 `SECTION_ORDERS`）**

固定开场白（-1000）→ 部署 persona 前缀（0）→ `PLAN_POLICY`(500)/`TEAM_POLICY`(600)/
`PTC_ONLY`(800) → 每工具段（`TOOL_BASH` 1000 … `TOOL_SUBAGENT` 2800/`TOOL_REPORT` 2900）
→ `TOOLS_SDK`(5000) → `DELIVERABLE_FILE_REFERENCES`(9000) → `STRUCTURED_OUTPUT`(9900)
→ `HARNESS_SOURCE`(10000) → `WEB_SURFACE`(10100) → 部署 persona 后缀（10200）。
排序规则逐字：「先按 order 升序拼接，同号时再按名称的代码单元顺序排列」（`README.zh.md:56`）；
**每段是否生效是 per-agent / per-assembly 的**，每次 `assemble()` 重跑（`lib/index.js:308-358`）
⇒ 工具面与变量是 per-step 的。

**§7.2 指令（`AGENTS.md` 那一类）不进系统提示词**
逐字：「第一次请求包含一条持久基线消息：先是用户全局 `$DSH_HOME/AGENTS.md`，再按从宽泛到具体的
顺序包含项目指令链」（`:32`）；「更具体的指令优先于更宽泛的」（`:137`）。刷新**由 touch 驱动、
没有 watcher**（`:215`）；按 **SHA-1 内容标识**去重，较宽泛的先省略、最具体的最后截断（`:97`、`:72`）。
⇒ 与我们的 `AGENT-PROFILES.md`（每次运行重新生成一份可 `fs.read` 的画像）是**两种形态**：
DSH 是"指令链进历史"，我们是"画像落盘 + 提示词指路"。

**§7.3 提示词变化的三条路（与 §3 同一处，这里补"谁说了算"）**
渲染后的提示词是 surface 的 `system/message` **节点**，不在 request header 里
（`dsh-agent-loop/README.zh.md:93`；`dsh-session/README.zh.md:112`）。能力路由 + 序列延续 ⇒
非空变化**追加**在缓存历史之后；否则**重写首节点 + 逐条空内容替换**后续节点
（`agent-loop/lib/index.js:274-283` 的 `project()`）。空提示词必须**逐节点**清
（`dsh-session/README.zh.md:54`）。三类"新序列"触发见 §3。

**§7.4 漂移检测：DSH 靠比较，不靠摘要**
DSH 侧**没有提示词文本的摘要/版本号**：`systemPrompt.update` 比文本
（`latest.text === rendered` ⇒ 不产生事件，`agent-loop/lib/index.js:279`），
`toolsChanged()` 比 header（`:909-917`），唯一的哈希是指令文件的 SHA-1（`agent-instructions
README.zh.md:97`）。**我们反过来**：有 `PROMPT_VERSION`（`agent_prompts.py:147`）与
`prompt_audit().prompt_sha256`（`:2159`，落进 `agent_run_start`，`agent_loop.py:2169`），
但**只记不判**（没有任何地方拿它对账；续跑指纹只对任务，不对提示词）。
⇒ 计划里这一条要写清：**我们的版本号是"换没换过"的读数，DSH 的文本比较是"现在是不是同一份"的
判据** —— 两者不是同一件事，移植时不要用一个替另一个。

**§7.5 硬拒绝（逐条，都可抄成判据）**
未知/无值/格式错误的变量引用 ⇒ 组装抛错（`:105`「格式错误的提示词比明确失败更糟」）；
生效的 complete 段 > 1 ⇒ 组装失败（`:56`）；同层重名段/上下文/变量 ⇒ 注册即抛
（`lib/index.js:188-190`）；段名非空、不重复、`text` 必须是 string；变量名匹配
`^[a-z][a-z0-9_]*$`（`dsh-system-prompt/lib/invariant.js`）；指令文本里的字面
`</system-reminder>` 会被转义（"仓库控制的文本无法关闭插件控制的框架"，
`dsh-agent-instructions/README.zh.md:106`）。

**§7.6 对照（结论）**：我们的 `promptkit` 已经把 DSH 的**装配机制**搬对了
（`SECTION_ORDERS` 一一对应、`PromptSection{name,order,text,complete}` + `assemble()` 同构、
严格 `{{name}}` 插值四类失败、作用域遮蔽）。**没搬的是"装完之后"那一段**：
DSH 有组装 waterfall（`system-prompt/assemble` 可插拔）+ 不变式伴生 + **提示词节点化准入**；
我们装配一次就在整趟里逐字复用（`agent_loop.py:2152-2153` 装、`:2256` 每步原样发）。

**§7.7 提示词里写了哪些"面"（逐条对照，含几处我们比 DSH 多/少的）**

| 面 | DSH | 我们 |
|---|---|---|
| 工具 | 每工具一段 `tool:<name>`（1000 起；实证段名 `tools:ptc-only`、`tools:sdk`） | 每工具一段 `TOOL_<NN>`（1000+序号×10）—— 同形 |
| 工具 SDK | `TOOLS_SDK`(5000)＝代码运行时 SDK 用法（`## Writing code for run_code`） | `AGENT_TOOLS_SDK`(5000)＝**循环协议**（非同一样东西） |
| 伙伴/团队 | **没有伙伴表段**；只有 runtime context `subagent:delegation`(120)；`TEAM_POLICY`(600)/`TOOL_REPORT`(2900) 是**预留但无人注册**的空槽 | `PARTNERS`(4500)＝由 `ALLOWED_EDGES` 现算的一张伙伴表（我们比 DSH 多这一面） |
| 时间 | 不是段：每步读数的 `time-context` 节（`Time sampled while preparing turn …, step 1: …`），默认组合不挂 | 无（我们的时间事实在工具读数里） |
| 工作区 | `HARNESS_SOURCE`(10000) + `WEB_SURFACE`(10100)；工作区**指令**走 user 消息（`<system-reminder>` 框架） | `WORKSPACE_FACTS`(10000) + `TOOLCHAIN_FACTS`(9000)；指令走 `AGENT-PROFILES.md` 落盘 + 提示词指路 |
| 计划 | `plan:policy`(500)，仅 plan 模式生效时非空 | 无政策段（计划在 F 的工具体与 board 那一段） |
| 沙箱/审批/委派 | runtime context 三节：`SANDBOX_POLICY`(110)、`APPROVAL_POLICY`(115)、`SUBAGENT_DELEGATION`(120)；快照标题逐字 "Current runtime context. This snapshot supersedes earlier runtime-context snapshots." | 无 runtime-context 快照类；动态事实（收件箱/板/插话/步号）走**每一步的 user 消息**（`agent_loop.py:1912-1935`） |

⇒ 一句话：**DSH 的"面"是分层的（段 / runtime-context 快照 / surface 节点）**，
我们的"面"是**一层**（段 + 每步一条 user 消息）。这是 §3 那条差异在提示词侧的投影。

## §8 挖到的第三组：会话与回合框架（DSH ↔ 我们）

出处：`dsh-session`（含 `lib/types/invariant.js`）、`dsh-llm` 的消息类型、
`dsh-session-persistence-jsonl`、`dsh-session-turn-outline`、`dsh-repeat-tool-reminder`、
`dsh-fs-observation-policy`。

**§8.1 记录词表（逐字）**
- 模型可见 surface 四类：`system/message`、`user/message`、`assistant/message`、`tool/result`
  （`dsh-session/lib/types/types.d.ts:413`）；`SurfaceOp = 'append' | {op:'replace', startSeq, endSeq}`
  （`:429-433`）。
- 事件信封：`{type, seq, time, data}` + `ignorable?: true`（`:460-483`）；已知事件 56 项
  （`lib/types/known-event-types.js:21-78`）。
- 角色：`'system' | 'user' | 'assistant'`（`dsh-llm/lib/types/message.d.ts:124`）；
  **工具结果是 user 角色**（`:150-152`）；内容块：`text`/`reasoning`/`image`/`file`/`tool-call`/`tool-result`
  （`dsh-llm/lib/types/types.d.ts:91-97`）；来源 kind：`user`/`plugin`/`model`/`tool`（`message.d.ts:94-104`）。

**§8.2 回合与步 + 两套停止词表（逐字）**
- step 的定义逐字：「one model call plus the tool executions it requested」（`types.d.ts:264`）。
- `TurnEndReason`：`completed` / `aborted` / `blocked` / `error` / `max-tokens` / `interrupted`
  （`types.d.ts:165-199`）。其中 `interrupted` **只在事后补**：「The loop never emits this marker live」
  （`:196-198`）；`max-tokens` 的措辞「At least one step reached its output-token ceiling,
  even if a plugin continued the turn」（`:186-189`）。
- `FinishReason`：`stop` / `tool-calls` / `max-tokens` / `aborted` / `error`
  （`dsh-llm/lib/types/types.d.ts:107-125`），**可扩展**（`:105`）。
- 明示不含 ACP 的 `refusal` / `max_turn_requests`（`dsh-session/README.zh.md:185`）。
⇒ 对照：我们的 `stop_reason` 是一串**自由字符串**
（`final/budget/max_steps/not_wired/bad_json_limit/bad_args_limit/no_progress_limit/waiting_for_user`
+ `ask_cancelled/no_checkpoint/checkpoint_mismatch/already_finished/resume_no_transcript`），
唯一登记点是 `webui/server.py:136-147` 的徽章表，**没有 `kind` 联合守卫**。

**§8.3 重发什么 / 只留审计什么（逐字）**
重发：已接纳 user/assistant 消息、工具调用与结果、注入上下文与 steering（`dsh-agent-loop
README.zh.md:166`）。只留审计：原始流分片、生命周期边界、`assistant/attempt`、`request/header`、
`request/context`（`:166`；`dsh-session/README.zh.md:138`、`:166`）。
**推理回放逐字**：「此前 assistant 轮次的推理内容会原样传回，无论该轮次是否调用了工具」
（`dsh-llm-deepseek/README.zh.md:155`）。工具结果的 `arguments` 是「raw `arguments` JSON string
exactly as the model produced it (unparsed)」（`types.d.ts:329-332`）。
⇒ 对照：我们**没有** assistant/tool 消息之分（一条 `agent_step` + transcript 文本），
工具结果还会被 `_clip_fields`（`agent_loop.py:217`）限长 —— 不是"原样"。

**§8.4 追加式日志的 16 条不变量（DSH 侧逐条有源码依据）**
关键的几条：`seq` 严格递增（`dsh-session/lib/types/invariant.js:22-24`）；一个 start 对一个 end
（`:33-54`）；**`turn/end` 时不得有开着的 step**（`:48-50`）；step 必须在开着的轮内（`:55-58`）；
`tool/result` 必须有同 step 的 `tool/call`（唯一例外是合成的 `TOOL_NOT_STARTED`，`:99-101`）；
「**模型可见即已记录**：任何到达模型请求的内容都必须能从日志重建」（`dsh-session/README.zh.md:84`）；
「surface 是派生历史的唯一来源」（`:108`）；已提交事件绝不重写、崩溃只追加合成 closer
（`dsh-session-persistence-jsonl/README.zh.md:74`）；未知必填事件「MUST refuse to reconstruct
the session instead of silently dropping the event」（`types.d.ts:470-477`）。
⇒ 对照：我们用 `resume_transcript` 的**逐字相等**判据替代了 DSH 的运行时不变式伴生插件
（已覆盖其中约 9/16 条语义），缺的是"轮/步开闭配对"与"工具调用/结果配对"的**结构性**断言。

**§8.5 另外两条可移植的机制**
- **重复工具调用提醒**：阈值默认 `[3,5,8]`，键是 `(tool name, canonical arguments)`
  （忽略属性顺序）；排除项既不计数也不重置；被拒调用也计数；新用户提示词清零；
  **恢复的会话从零开始**；超过最高阈值不再提醒（`dsh-repeat-tool-reminder/README.zh.md:12,81-87,174`）。
  它作为**注入的 `user/message`** 追加在该步工具结果之后（`:91`），且「**绝不替换 `content`**：
  用于审计的 `tool/result` 事件仍保留工具自己的输出」（`:91`）。
- **文件观察策略**：见 §6 的 B4（这是子代理报上来的**最大缺口**）。

## §9 挖到的第四组：上下文管理（DSH ↔ 我们）

出处：`dsh-compaction` / `dsh-compaction-basic` / `dsh-compaction-tool-result-pruner` /
`dsh-output-retention` / `dsh-spill` / `dsh-spill-policy` / `dsh-token-meter`。

**§9.1 触发与决策点：决策者是后端策略，不是循环、也不是模型**
`compactIfNeeded`（自动，`pressure` / `context-overflow`）/ `compactNow`（人来敲 `/compact`）/
`compactRegion`（显式范围）。阈值默认 `thresholdRatio 0.8`、保留 `retainRatio 0.16`
（`dsh-compaction-basic/README.zh.md:62`「默认在已路由模型上下文窗口的 80% 处开始压缩，
并逐字保留最新的 16%」）。挂载点是 `agent/pre-step`（派生前查压力）+ `agent/request-error`
（对 `CONTEXT_WINDOW_EXCEEDED` 绕过阈值重试）。顺序：**先剪枝、再摘要**，剪完回到阈值内就
整个跳过摘要（`:89`）。三态是**三态**：`busy` / 需要但无安全范围（返回 `null`，
`README.zh.md:81`「不会有任何改变，也不会向会话日志写入任何内容」）/ 真失败。
一条硬纪律（`dsh-compaction/README.zh.md:158`）：**模型不能自己触发压缩**
（「不会注册面向模型的压缩工具」）。

**§9.2 丢什么、保什么（优先级）**
① 先剪**超大工具结果的中间段**（无模型调用，最便宜）；② 仍超阈值才摘要**最旧的平衡范围**，
尾部逐字保留；③ 范围边界必须**工具配对平衡**（`lib/index.js:408`
`toolPairingBalancedBefore(...)`）；④ **绝不动**：surface 节点 0 的系统提示词、工具 schema、
会话前缀（`dsh-compaction/README.zh.md:160`、`dsh-compaction-basic/README.zh.md:112`
「位于 surface 节点 0 的系统提示词永不会被遮蔽」）；⑤ 原始事件**绝不移除，只被遮蔽**
（`dsh-compaction/README.zh.md:12`「被压缩的内容仍保留在会话日志中，因此回放会话可以还原出
完全相同的对话」）。

**§9.3 超大工具结果：剪枝与 spill 是两条策略**
- 剪枝器：确定性、无模型调用、只按码点，`thresholdChars 8192 / headChars 4096 / tailChars 1024`，
  标记字面量 `"\n\n[... tool result middle pruned ...]\n\n"`
  （`dsh-compaction-tool-result-pruner/lib/index.js:8`）。**它是替换，不是 spill**：
  没有路径、没有指针，中间段只留在 append-only 日志里。
- spill 是另一条（`maxInlineBytes` 预算）：模型看到有界 head/tail 预览 + 一条通知，
  通知的拼装字面量在 `dsh-spill-policy/lib/index.js:5-8`（`" Full formatted result stored at: "`），
  `SpillRef` 三字段 `locator` / `bytes` / `retrievalHint`（`dsh-spill/README.zh.md:58`）；
  取回靠**指引文本 + 模型自己的 read/grep**，API 不提供取回（`:12`）。
- 两个保险：post-execute **跳过 `read`**（防 read→spill→read 循环，`lib/index.js:54-55`）；
  通知装不下时**放弃替换、保留原始内联结果**（`README.zh.md:149`）。

**§9.4 读数（词表）**
`measure()` → `totalTokens` / `surfaceTokens` / `nodes[]`（节点带 `tokens` 与 `heuristicTokens`）；
`TokenUsage` 的桶**互斥**：`inputTokens`（**仅未缓存输入**）/ `outputTokens` / `cacheReadTokens` /
`cacheWriteTokens` / `reasoningTokens`（`dsh-llm/lib/types/types.d.ts:130-149`）；
三个投影键 `tokenUsage` / `contextPressure` / `contextBreakdown`（`systemTokens` / `toolsTokens` /
`messageTokens`），且 **`contextWindow` 本身是可选**（可能读不到）。
压缩侧：`CompactionResult{compactionId,startSeq,summarySeq,endSeq,summary,shadowedRange,shadowedSeqs,shadowedTokenCount}`
与事件 `compaction/start|summary|end|prune`。启发式口径「每 token 四字符 + 块与角色开销」，
并明说「占用是参考数字，不是计费记录」（`README.zh.md:66`）。

**§9.5 三态与失败形态（可抄成判据的六条）**
① `unmeasurable` ≠ 零：容量读不到时自动路径只警告一次并带完整历史继续，手动路径抛；
② `null`（没压缩）≠ 失败 ≠ `busy`（`ManualCompactionError.code` 是封闭集合
`'busy'|'cancelled'|'changed'|'summary'|'commit'|'persistence'`）；
③ 摘要失败保留最新持久表层，自动路径记警告后继续；
④ 「更小」是**硬校验**：`if (framedSummaryTokenCount >= prepared.shadowedRouteTokenCount) throw`
（`lib/index.js:572`）—— 拒绝一个不缩小源内容的摘要；
⑤ 预算事实不许混入上游失败（`dsh-output-retention/README.zh.md:79`「它绝不表示上游不完整」）；
⑥ 文本识别不是认证（`dsh-spill-policy/README.zh.md:147`「工具也能打印相同的通知文本」）。

**§9.6 不变量（九条）**：系统提示词/工具/前缀永不压缩；绝不切断未回答的 assistant 工具调用；
表层只变更一次且替换在锁对内；标记对＝事务锁、每次失败**恰好一次**闭合尝试；摘要不得出现图片
输出（以 `UNSUPPORTED_CONTENT` 失败而不是消失）；摘要器只回放会话自己的前缀、只有返回文本进检查点；
压缩期间用户提示词不丢不重排；**模型不能自己触发压缩**；spill 失败绝不把成功调用变成错误。

**§9.7 对照表（有 / 缺 / 不一致）**

| DSH 的哪一条 | agentflow 今天 | 状态 | 依据 |
|---|---|---|---|
| compaction seam（策略/后端分离） | `contextbudget.ContextBudget` + `compact()` | **有** | 模块 docstring：压缩/剪枝/spill 三件套（FC-17） |
| 阈值自动触发（`agent/pre-step`） | `agent_loop` 的步骤边界 | **缺** | `agent_loop` 不 import `contextbudget`；`transcript` 只累加（L2561） |
| 0.8 × contextWindow 的**token** 压力 | `compact()` 比**字符数**（`compaction_threshold_chars=200000`） | **不一致** | 我们用 `sum(len(t))`，DSH 用路由定价 token |
| 保留最近尾部逐字 | `compaction_keep_recent: int = 8` | **有** | 同一件事的字符版 |
| 节点 0 系统提示词永不遮蔽 | 无对应 | **缺** | 我们的 `compact` 只按条数切片，不认识"系统前缀" |
| 工具配对平衡边界 | 无对应 | **缺** | 循环的 transcript 是字符串，没有调用/结果配对概念 |
| 超大工具结果剪枝 | `contextbudget.prune()` + `prune_tool_result()` + `tools/base.py:1504-1509` | **有**（但剪枝标记文本不同，且对声明 `budget` 参数的工具主动跳过） | 读到的实现 |
| spill 落盘 + 路径指针 | `prune()` 里就地落盘全文 + sha256 | **有**（落的是未剪枝原文） | 读到的实现 |
| spill 与剪枝分属两条策略 | 同一个 `prune()` 内两态（落盘分支默认不可达，docstring L38-43 自陈） | **不一致** | — |
| `read` 结果不被 spill（防循环） | 无对应 | **缺** | DSH `dsh-spill-policy/lib/index.js:54-55` |
| token 读数（桶/缓存/窗口压力） | `tokenmeter.TokenMeter` 只记账本花销（`Charge.spent_tokens/usd`） | **不一致** | 没有 `cacheReadTokens` / `contextWindow` / surface 压力读数 |
| 三态：`limited=False` ≠ 够用 | `MeterReading` 的 docstring | **有** | 与 DSH 同款三态纪律 |
| 三态：`null`（没压缩）≠ 失败 | `CompactResult.summarizer ∈ {injected, mechanical, none}` | **有** | — |
| 压缩标记对/锁（busy 可复位） | 无对应 | **缺** | `CompactResult` 无 id/起止 seq，也没有"进行中" |
| 「摘要必须更小」硬校验 | 无对应 | **缺** | 我们只报 `kept_chars` |

**§9.8 结论**：我们在这一块**不是从零开始**（三件套与三态纪律都在），差的是
**把它接到循环的那个动作**（B3）与**三条 DSH 的不变量**（节点 0 永不遮蔽 / 工具配对平衡 /
摘要必须更小）。**"我们缺上下文管理"这句话是错的，已在 B3 里更正。**

## §10 挖到的第五组：工具契约与决策闸门（DSH ↔ 我们）

出处：`dsh-tools`、`dsh-tool-call-timeout-policy`、`dsh-plan-mode`、`dsh-goal`、
`dsh-goal-round-driver`、`dsh-tool-goal`、`dsh-tool-todo`、`dsh-tool-subagent`、
`dsh-tool-subagent-control`、`dsh-user-approval`、`dsh-user-questions`、`dsh-tool-ask-user`。
**读限一条（如实登记）**：DSH 各 README 里指向的 `docs/` 与 `.agents/notes/` 在**已安装的包里不存在**
（实测 `Test-Path <dsh>/docs == False`），所以这一组只以 README 正文与 `lib/*.d.ts`、`lib/index.js` 为据。

**§10.1 声明与结果的精确形状**
- 模型可见的声明只有三个字段：`ToolSchema{name, description, parameters}`
  （`dsh-llm/lib/types/types.d.ts:397-402`）。作者侧的 `ToolDefinition` 多出
  `output{ schema, render, presentationMeta? }` / `execute` / `finalizeContent?` / `timeoutMs?` /
  `isConcurrencySafe?` / `presentCall?` / `presentResult?`（`dsh-tools/lib/types/index.d.ts:97-172`），
  而**这些字段绝不泄漏到协议**（`dsh-tools/README.zh.md:103`）；`timeoutMs` 另外逐字写着
  「it is NEVER sent to the model」（`index.d.ts:133-139`）。
- 执行结果是**判别联合**，判别字段 `isError`：成功 `{isError:false, value, content, meta?,
  additionalContexts?, concludesTurn?}`；失败 `{isError:true, error:{message, info?:{name, code}},
  content, value?: never}`（`index.d.ts:362-410`）。`value` 的注释逐字
  「Execution-local canonical value; deliberately omitted from durable events」。
- 模型实际收到的四种文本：成功 ⇒ `output.render` 投出的块；失败 ⇒ `Error: <message>`
  （`dsh-tools/lib/index.js:3496`）；**未执行**（派发前取消）⇒ `Error: tool call aborted before
  dispatch` + `ABORTED_BEFORE_DISPATCH`；**已开始后取消** ⇒ `Error: tool call aborted` + `ABORTED`
  （`index.d.ts:353-355`；`README.zh.md:121`「调用主体前的取消为 `ABORTED_BEFORE_DISPATCH`，
  调用主体后的取消只能把成功结果替换为 `ABORTED`」）。
- 线形状：`ToolCallBlock{ id, name, arguments: <原始 JSON 字符串> }` 与
  `ToolResultBlock{ toolCallId, content, isError? }`（`dsh-llm/lib/types/types.d.ts:72-86`）。

**§10.2 坏 JSON：不修、不丢，原样下传成"根类型不对"**
`dsh-agent-loop/lib/index.js:540-547` 逐字注释：「Parse model arguments, preserving invalid JSON as
text and mapping empty input to `{}`」（`try { return raw ? JSON.parse(raw) : {} } catch { return raw }`）。
于是下游收到的是一个**字符串**，注册表的校验把它说成
`Error: invalid arguments: "arguments" must be an object`（code `INVALID_ARGS`，
`dsh-tools/lib/index.js:812-819`、`lib/types/json-schema.js:474`）。
**没有自动重试**：失败但**轮次继续**（`README.zh.md:121`），重试是模型的决定
（`dsh-tool-call-timeout-policy/README.zh.md:46`「从而决定重试、调整或放弃」）。

**§10.3 工具调用超时：逐工具声明 + 包装层执行，且是协作式的**
`timeoutMs` 挂在工具定义上、由**包装层**读注册表执行（注册表自己不强制，
`dsh-tools/README.zh.md:226`）。**没有统一默认**：只有声明了的工具才有截止时间，
随附的 `bash`/`read`/`write`/`edit` **有意不声明**（`dsh-tool-call-timeout-policy/README.zh.md:123`）。
超时时把结果替换成 `Error: tool call timed out after <ms>ms` + `TOOL_TIMEOUT`
（`:69`），并且**只通知不硬杀**（`:122`「协作式，绝不是硬终止」——只通过 `exec.signal` 通知；
忽略信号的工具会让调用方继续等，且在它自己完成前不产生超时结果，`:46`）。

**§10.4 计划模式（`/plan`）：引导而非强制，但"未评审不许开工"是硬的**
逐字「它不限制 agent：每个工具仍可调用」（`dsh-plan-mode/README.zh.md:32`）、
「引导而非强制——计划模式只通过文本约束」（`:183`）。真正的闸门在**退出**那一步：
计划以 markdown 从标题写起、调用 `exit_plan_mode` 交人评审（`:61`）；批准 ⇒ `{approved: true}`，
拒绝 ⇒ 带反馈的失败调用，放弃 ⇒ 指明用户接手的失败调用（`:166`）；**没有可用的交互评审通道
就失败关闭**，手动退路只有 `/plan off`（`:93`）。**工具目录不变**：进入/离开只改提示词段
（`plan:policy`，order 500），不改请求里的工具表（`:93`）。另外：被另一个存活 agent 拥有的子级
**打不开评审**，必须把未决决策写进最终结果（`:186`）。

**§10.5 目标轮次（Goal Round）与"受阻"的判据**
- 预算只有轮数一维：`defaultMaxGoalRounds` 默认 **256**（`dsh-goal/README.zh.md:46`），
  且逐字「只有 Round 数量预算——不计量 token、货币、挂钟时间或提供方配额」（`:159`）。
- 一个 Round = 一条**保留的 user 角色 `<goal_round>` 块**（点明完整目标与正数轮号，
  `dsh-goal-round-driver/README.zh.md:109`）；**只有进入步骤的 goal 消息消耗上限**（`:49`）。
- 额度耗尽 ⇒ 以稳定代码 `round-limit` 记一个 blocker（`:53`）。触发三合一：agent 空闲 +
  续行启用 + 还有额度（`:12`）。
- **完成 vs 受阻**：自主 `complete` 可以立即完成；自主 `blocked` 在达到
  `blockedAfterConsecutiveRounds`（默认 **3**）之前被**机械拒绝**，且必须把那个具体的条件写进
  `blocked_reason`（持久化为稳定代码 `model-reported`）（`dsh-tool-goal/README.zh.md:48/51/55/40`）。
  模型指引原文（阈值插入）：*Mark blocked only after the same blocking condition persists for at
  least **3 consecutive goal rounds**, and report that concrete condition in blocked_reason;
  difficulty, uncertainty, or useful remaining work is not blocked.*（`:117`）
- **无独立评估器**：逐字「记录完成或阻塞的调用方拥有最终决定权」（`dsh-goal/README.zh.md:160`）。
- 会话 resume/fork 之后 active goal **一律停用续行**（`dsh-goal/README.zh.md:72`）、
  持久 `paused` 不许模型自行 resume（`GOAL_TOOL_RESUME_PAUSED`）；同一会话只允许一个当前 goal
  （`:32`）。
⇒ **这一组与业主第 146 轮第 1 条裁定（「收工由 M 判」）是同一件事的两种写法**：
DSH 把"能不能收工"交给**调用方**（不是机器判据），我们说"未达标的行是读数、不是拦收工的门"。
**我们已有的比 DSH 更完整**（`closing` 的八格读数 + M 的裁决），DSH 只有"轮数耗尽"一个 blocker。

**§10.6 待办清单（`todo_write`）：整表替换，没有部分更新**
逐字「agent 每次更新都发送完整列表；新列表替换旧列表，因此没有部分更新或逐项编辑」（`dsh-tool-todo/README.zh.md:52`）；
「没有部分更新、没有回读工具、没有逐项编辑」（`:162`）。被拒的四条稳定文本（`:143`）：
空内容 / 重复内容 / 需要拥有该列表的会话 / （`allowParallelInProgress: false` 时）最多一个
`in_progress`。成功文本逐字 `Updated todo list: <pending> pending, <inProgress> in progress,
<completed> completed.`。**"何时必须创建"这条硬规则：未读到**（挂不挂载是部署决定）。

**§10.7 子代理委托：自足 prompt + 只回最终文本**
- 两个必填参数：`description`（逐字「A short (3-5 word) description of the delegated task,
  for display.」）与 `prompt`；工具描述逐字「Give it a complete, standalone prompt:
  it does not see this conversation.」（`dsh-tool-subagent/lib/index.js:350-351`）。
- **"无对话种子"随后端变化**：全新子代理的措辞是 "it does not see this conversation"，
  fork 子代理的是 "it does not see the current in-flight turn"
  （`README.zh.md:95`）——「模型既不会复述、也不会省略并不存在的上下文」。
- **返回的是最终消息，不是有界结构化报告**：前置成功「只包含子 agent 的最终文本」，
  其他终止原因映射成 `Error: <终止原因>` + 安全诊断 + 部分 assistant 文本；
  「子 agent 中间步骤不会进入父级」（`:180`）。可继续模式的结算**不走返回值**，
  以服务通知到达父级（`:194`、`:211`）。
- 深度 `maxDepth` 默认 3（`:53`），**工具在达到上限时仍然可见**，每次尝试启动才检查（`:63`）；
  失败的运行返回错误、不给部分成功（`:12`）。
- 控制面：`send_message` **只回接受结果**（稳定 `messageId`），绝不回回复（`:49`）；
  `interrupt_agent` **只停目标当前轮次**（已排队消息留着、后代继续跑，`:53`）；
  `list_agents` 状态三档 `running`/`idle`/`ready`，一次性子级被**有意排除**（`:57`）。

**§10.8 审批与提问：无人应答 = 失败关闭**
- 决策点在 `tools/pre-execute`：`PreToolDecision = allow | deny{reason} | ask{reason?}`
  （`dsh-tools/lib/index.js:85`、`index.d.ts:419-427`）。
- **没有应答者 ⇒ `unavailable` ⇒ 以拒绝方式关闭**（`dsh-user-approval/README.zh.md:12/32`），
  工具层物化的拒信逐字 `tool "<name>" requires approval, but no approval channel is available`。
- **只有一次性授权**：结果词汇有 `allowed-once`，**没有** `allow-always`、记住的规则、撤销或授权库
  （`:155`）；**请求不携带工具参数**（`:156`）。
- `never` 策略在 waterfall **之前**确定性拒绝，后注册的监听器也绕不过（`:36`、`:78`）。
- 提问面：`ask()` 只允许**确切的存活运行时根**（`dsh-user-questions/README.zh.md:41`），
  无 answerer ⇒ 以错误失败而不是降级；**被别的存活 agent 拥有的子级不许问用户**，
  必须把未决问题写进最终结果（`dsh-tool-ask-user/README.zh.md:60/142`）。

**§10.9 必须停下来的决策点（24 条里对我们有用的 10 条）**
① `pre-execute` 判 deny ⇒ 不执行；② `ask` 且无审批通道 ⇒ 拒（fail-closed）；
③ 派发前取消 ⇒ 工具体根本不执行；④ 声明了限时且截止先到 ⇒ `TOOL_TIMEOUT`；
⑤ 未知工具/坏参数/输出违反声明 ⇒ 这一次失败但轮次继续；⑥ `post-execute` 返回 `block` ⇒
成功结果被改成 `isError` + 纠正性 `feedback`；⑦ 纯 ptc 模式直呼别的工具 ⇒ 在策略之前
`UNKNOWN_TOOL`（**通告面与可调用面必须一致**）；⑧ 未声明 `isConcurrencySafe` 的调用是**排他的**；
⑨ 计划模式必须停下交人评审；⑩ goal 的 `create/edit/pause/resume` **必须有人类直接请求**
（`{kind:'user'}`），子代理不能创建或编辑 goal。

**§10.10 对照表（只列承重的那些格）**

| # | DSH 的哪一条 | agentflow 今天 | 状态 | 依据 |
|---|---|---|---|---|
| 1 | `ToolSchema{name,description,parameters}` | `tools/base.py::ToolSpec` + `to_function_schema()` | **有** | 字段名是 `summary` 而非 `description`；`params` 根必须是 object（同一约束） |
| 2 | 作者侧输出契约 `output{schema,render,presentationMeta}` | `ToolResult{ok,data,error,meta}` | **缺** | 工具返回任意值即被 `ok(...)` 包住，没有"声明的输出 schema + 渲染投影" |
| 3 | 结果是判别联合、判别字段 `isError`、错误码在 `error.info.code` | 拒因写进 `meta["kind"]`（`unknown_tool`/`role_denied`/`param_error`/`unexpected`） | **不一致** | `base.py:1381/1440/1469/1495` |
| 4 | 失败统一文本面 `Error: <message>` | 模型看到 `{"tool":…,"ok":false,"error":…}` 且逐字段截断 | **不一致** | `agent_loop.py:217-250`、`:289-293` |
| 5 | 坏 JSON 原样保留为文本 | `judge_bad_args` / `judge_bad_json` 两档，注释自陈与 DSH 同一条纪律 | **有** | `llmseam.py:741-749` |
| 6 | `INVALID_ARGS` 交回工具层 | `ParamError` → `kind="param_error"`，连击另计 | **有** | `base.py:1466-1469`；`agent_loop.py:2291-2332` |
| 7 | `UNKNOWN_TOOL` | `kind="unknown_tool"` + **并列候选回映** | **有（比 DSH 多一层）** | `base.py:942-950`「机器只列候选、不自动改写」 |
| 8 | 逐工具 `timeoutMs` + 包装层截止 | 无 | **缺** | 只有运行级墙钟（`policy.py:453-455`）、脚本级 `timeout_sec`（`agent_e/core.py:161`）、模型级（`modelgw.py:259`） |
| 9 | 计划模式（评审闸门） | 无 | **缺** | `SHAPES` 里没有类似形状；`agent_f/create_plan.py` 是 F 的**领域**计划，不是"先评审再执行" |
| 10 | 持久 goal + Round 预算 + `blocked_reason` | 无（只有 `max_steps` 与 `autonomy` 多轮） | **缺** | 正是 §10.5 说的：我们的"收工由 M 判"更强，但**没有跨轮持久 goal 这一层** |
| 11 | `todo_write` 整表替换 | 无 | **缺** | `SHAPES` 无 todo 形状；F 的 `subgoals` 是领域表 |
| 12 | `subagent` 委派（深度/失败语义） | `Conductor.summon` + 循环形状 | **有（等价变形）** | 八条判据集中在 `policy.check`（`policy.py:317-455`），拒绝以受控词表返回 |
| 13 | `subagent_fork`（继承已完成轮次） | 无 | **缺** | 只有 spawn 语义 |
| 14 | "无对话种子"写进**工具描述** | 子代理确实只拿任务文本+收件箱，但**广告面没写这句话** | **不一致** | `agent_loop.py:631-642`；`llmseam.py:803-814` |
| 15 | `send_message`/`interrupt_agent`/`list_agents` | 有 `message` 形状 + `read_messages`/`roster`/`retire` | **不一致** | **没有** `interrupt_agent` 等价物，也没有"列出子代理与状态"的模型面 |
| 16 | 审批 seam（`ask`/`never`、一次性、无应答者 fail-closed） | `ToolSpec.needs_approval` **只用于展示** | **缺（最危险的一格）** | `base.py:1296` 与 `cli.py:448` 打「⚠需审批」，而 `ToolRegistry.call` 里**没有任何审批判据**（`base.py:1304-1519`）——"声明了要审批"与"真的需要签字"之间没有执行面 |
| 17 | `ask_user_question` 只有运行时根能问 | `userio.ask_user` + `_do_ask_user`（只有主控能问） | **有** | `ASK_NOT_CONDUCTOR`；四档状态机；pending ⇒ 停循环 `waiting_for_user` |
| 18 | 无人值守 = 确定性拒绝（不是降级） | `userio.ask_user` 的 `unattended`（fail-closed） | **有** | `userio.py:660-671` |
| 19 | 收工/验收的决策门 | `closing.check_closing` + M 的裁决 | **有（归属相反）** | 我们：`can_close` 由 M 判、机器八格退成读数；DSH：plan 要人批、goal 归调用方 |
| 20 | 无新事实/额度耗尽就停轮 | `stop_reason` 族（`no_progress_limit`/`bad_json_limit`/`max_steps`/`budget`） | **有** | DSH 另有 `round-limit` 一档（我们无 goal 层） |

**§10.11 结论与候选批次（B7–B10）**
- **B7（最高优先）：把 `needs_approval` 从"展示"变成"执行面"。** 今天的形态是**声明与执行分家**
  （§10.10 第 16 行）——这与我们反复登记的"声明层与实现层必须一致"是同一条纪律的反面。
  判据：① 正控 —— 声明了要审批的工具，在没有审批通道时**必须拒**（而不是照跑）；
  ② 负控 —— 未声明审批的工具不受影响；③ 反真空 —— 至少有一件真工具声明了它，否则这条是空转。
- **B8：逐工具超时（`timeoutMs` 的等价物）。** 现在只有三层粗粒度上限，没有"这次工具调用"的
  协作式截止。判据：正控（声明 1s 的工具真的在 ~1s 后收到超时结果）+ 负控（未声明的工具不受影响）
  + 三态（限时读不到时不许当零）。
- **B9：把"它看不到这段对话"写进子代理的广告面。** 这是 §10.10 第 14 行的不一致，
  代价是"子代理以为父代理知道上下文"⇒ 提示词残缺。判据：正控 —— 广告面的描述里逐字含那句话。
- **B10：`interrupt_agent` / `list_agents` 的模型面。** 今天我们能在会话事件里看到子任务，
  但**模型手上没有"叫停一个子代理"和"列出子代理状态"的工具** —— 与业主第 146 轮第 5 条
  （父代理要等/管自己的子代理）直接相关。判据：正控（父代理能列出自己的子任务与状态）
  + 负控（列不到别人的子任务）。

## §11 归拢完毕：四组都在本页了

| 主题 | 小节 | 用来落哪一批 |
|---|---|---|
| 循环与每步的形状（核心） | §1–§5 | B1 + B2 |
| 提示词与指令装配 | §7 | B2 |
| 会话与回合框架 | §8 | B1 + B4 + B5 |
| 上下文管理 | §9 | B3 |
| 工具契约与决策闸门 | §10 | B7–B10 |

**候选批次总表**：B1 每步发消息序列 / B2 提示词节点化 + 三类换序列 / B3 把 `contextbudget`
接进循环 / B4 文件读后写 / B5 提醒与判停拆开 / B6 推理回放待裁 / B7 审批的执行面 /
B8 逐工具超时 / B9 子代理广告面补那句话 / B10 子代理控制面。
**推荐顺序**（价值 ÷ 风险，且互不阻塞）：**B4 → B7 → B3 → B1 → B2 → B9 → B10 → B8**；
B5/B6 是"要不要改口径"的问题，等业主发话。

**口径登记（业主 2026-10-10 当轮）**：**现在全在写计划书、不动代码** —— 本页是挖掘与计划；
上面 B1–B10 的落点与判据是"回来能直接施工"的程度，但在业主发话之前不改任何 `.py`。
已经落地的两个提交（`8fbb6e5` thinking/key 的来源读数、`7742bdb` M 的出边设限）是这条口径
**之前**的批次。

| 提示词装配与指令层 | `dsh-system-prompt`、`dsh-agent-instructions`、`dsh-persona`、`dsh-agent-presets` | B2 |
| 上下文管理 | `dsh-compaction*`、`dsh-output-retention`、`dsh-spill*`、`dsh-token-meter` | B3 |
| 会话/回合框架 | `dsh-session*`、`dsh-repeat-tool-reminder`、`dsh-fs-observation-policy` | B1 + B3 |
| 工具契约与决策闸门 | `dsh-tools`、`dsh-tool-call-timeout-policy`、`dsh-plan-mode`、`dsh-goal`、`dsh-tool-todo`、`dsh-tool-subagent`、`dsh-user-approval`、`dsh-user-questions` | B1（工具结果形状）+ 收工/委托纪律 |

**登记（本页写作时的状态）**：四组已并行开挖（各自只读、逐条带出处）；本页 §1–§6 是先落地
的那一部分，§4 与 §7 会在它们回来后补成逐条判据。**本页不是计划书，是一份可复核的挖掘记录**：
先有"DSH 到底怎么做的"这个读数，才有资格谈"我们改成什么样"。
