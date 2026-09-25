# 15 · 本地先例对照：dsh「数学模式」preset 与 DeepMath 团队智能体

> 只读观摩报告。两处先例的所有结论均给出路径 + 行号；未能核实的一律标注。
> 对照基准是 `D:\Incubator\test\test1`（8 角色 A–H）与 `D:\Incubator\draft\13-数学研究多智能体协同框架-正式设计草案.md`。

**路径约定**
- Preset 简称 `<P>` = `C:\Users\ysc20\.dsh\.agent-presets\math-research\`
- DeepMath 简称 `<D>` = `D:\Incubator\temp\deepmath\`

---

## 1. dsh 数学模式是什么

### 1.1 它不是一个"多智能体程序"，而是一份**插件装配清单 + 一段 persona**

`<P>preset.yml` 全文只有 2 行（`name: 数学模式` + 一段 description）。真正的全部内容在 `<P>agent.cordis.yml`（450 行）。它的第 51–57 行把自己的定位说得很清楚：

> 「This file is an AGENT-PLANE composition. The roster mounts it ONCE under a standing scope... The host composition (`dsh-base` + `dsh-web-app` bundles + profile patch) keeps everything a preset must not own: the registries themselves, the sandbox and approval stack, persistence, and the model route.」（`agent.cordis.yml:51-57`）

也就是说：**它不实现任何"研究流程引擎"**。流程全部写在 persona 的提示词里，由 LLM 自觉遵守；插件层只提供"工具"和"提示段"。

### 1.2 装配清单（名字 / 作用 / 关键参数）

| 行号 | id | 插件 / 文件 | 作用 | 关键参数 |
|---|---|---|---|---|
| 77–127 | `persona` | `@deepseek-ai/dsh-persona` | **整个数学研究方法论都塞在这里** | `prefix` = 约 40 行 Markdown（唯一实质内容）；`suffix` 空 |
| 129–132 | `agent-instructions` | `@deepseek-ai/dsh-agent-instructions` | 读工作区 AGENTS.md 类指令文件 | `maxBytes: 65536` |
| 142–144 | `tool-bash` | `@deepseek-ai/dsh-tool-bash` | shell | `disabled: process.platform === 'win32'` |
| 146–148 | `tool-pwsh` | `@deepseek-ai/dsh-tool-pwsh` | shell（Win） | `disabled: !== 'win32'` |
| 154–155 | `tool-fs` | `@deepseek-ai/dsh-tool-fs` | 文件读写 | — |
| 157–160 | `tool-fs-search` | `@deepseek-ai/dsh-tool-fs-search` | glob/grep | `sampleOverCapGlobResults: false`（超限不抽样，宁可截断） |
| 171–172 | `tool-jobs` | `@deepseek-ai/dsh-tool-jobs` | 后台任务收集/终止 | — |
| 181–185 | `skill-filesystem` + `tool-skill` | 同名插件 | 技能发现 + 目录/加载 | — |
| 197–201 | `command-goal` + `tool-goal` | 同名插件 | 目标域 | — |
| 207–227 | `planning`（isolate `planMode`） | `@deepseek-ai/dsh-plan-mode` | 计划模式 | `section` 内含 6 段纪律：只读探索、`exit_plan_mode` 必须是最后唯一调用、不确认即不批准 |
| 241–265 | `compaction`（isolate `compaction`,`toolResultPruner`） | `compaction-basic` / `command-compact` / `tool-result-pruner` | 上下文压缩与工具结果裁剪 | `thresholdChars: 8192` / `headChars: 4096` / `tailChars: 1024`（行 263-265；行 254-259 说明 tail 的 1024 是"errors 和 UNSAT core 浮出来的地方"） |
| 284–350 | `delegation`（isolate `workflowEngine`） | `tool-subagent-control`、`.../list-agents`、`tool-subagent`(spawn)、`tool-subagent`(fork)、codex/claude-code(`disabled: true`)、`workflow-worker-thread`、`tool-workflow`、`tool-ralph` | 子代理 / workflow / ralph | `backgroundMode: continuable`（两个都）、`modelSelectionSettings: false`（行 307，理由见 301-306：子代理继承父路由，**评审不得漂移到别的模型**）、`maxRounds: 64` |
| 354–360 | `tool-ask-user` + `tool-todo` | 同名插件 | 提问 / 待办 | `allowParallelInProgress: true` |
| 372–377 | `tool-web` | `@deepseek-ai/dsh-tool-web` | 网页检索+抓取 | `fetch: true`、`fetchMaxOutputChars: 60000`、`searchTimeoutMs: 60000` |
| 382–383 | `present` | `@deepseek-ai/dsh-tool-present` | 交付物卡片 | — |
| 402–403 | `danus-console` | `./danus-console.mjs`（47 KB） | `danus` 工具：worker 控制 + supervise + deadline | 17 个 action，见 §5 |
| 408–409 | `danus-prompt` | `./danus-prompt.mjs` | 提示段 `danus:collaboration` | `order: 20`（`danus-prompt.mjs:19-21`） |
| 418–419 | `paper-tools` | `./paper.mjs`（61 KB） | `paper` 工具 + 提示段 | 提示段 `math:paper`，`order: 21`（`paper.mjs:1242-1244`） |
| 429–430 | `global-deadline` | `./global-deadline.mjs`（16 KB） | `deadline` 工具 + 提示段 | 提示段 `global:deadline`，`order: 25`（`global-deadline.mjs:241-243`） |
| 439–440 | `ocr-tools` | `./ocr.mjs` | `ocr` 工具 + 提示段 | `math:ocr`，`order: 22`（`ocr.mjs:227-228`） |
| 449–450 | `mo-tools` | `./mo.mjs` | `mo` 工具（MathOverflow）+ 提示段 | `math:overflow`，`order: 23`（`mo.mjs:207-208`） |

**提示段顺序链**（关键机制）：persona(0) → `danus:collaboration`(20) → `math:paper`(21) → `math:ocr`(22) → `math:overflow`(23) → `global:deadline`(25)。即"身份 → 协作 → 取证工具 → 收尾纪律"。本地插件都刻意与 persona 分离，`danus-prompt.mjs:5` 的理由是"便于日后单独开关/编辑"。

### 1.3 `preset.yml` 的每一句承诺落在哪个文件

| preset.yml 承诺（行 2） | 落实位置 |
|---|---|
| ultra-long thinking | persona 行 87（"Ultra-long thinking = more rounds, angles, verification depth — not longer narration"） |
| mandatory rigor | persona 行 90（Three Iron Rules 第 1 条，**明令禁用** obviously / clearly / trivial / left to reader 等 9 个词） |
| computational assistance (numerical/SAT) | persona 行 105–106 |
| research-director loop (R→R→T→P) | persona 行 94–95（见 §2） |
| three-direction attack | persona 行 95（"Hard propositions: 3 directions — forward proof, falsification (counterexample/search), probing (numerical/enumeration/SAT)"） |
| multi-role review | persona 行 124（6 角色 A–F，见 §2） |
| literature search and Zotero | persona 行 109 + `paper.mjs:1121-1150`（Zotero 本地 API `127.0.0.1:23119`） |
| Danus swarm orchestration | `danus-console.mjs` + `danus-prompt.mjs`（见 §5） |
| token-compact paper lookup via OpenAlex + S2 + DataCite | `paper.mjs:30-32`（三个 base URL） |
| works entirely in English | persona 行 84 |
| token-efficient sentence discipline | persona 行 97–102 |
| writes a timestamped Markdown report after every thinking round | persona 行 115（`analysis/cycle_<N>_report_<YYYYMMDD>_<HHMMSS>.md`） |
| Danus read/status run in-process | `agent.cordis.yml:28-30` + `danus-core.mjs:61-115`（`node:fs`/`node:net` 直读 `.status.json`/`.pid`，只有必须执行命令时才走 shell，`danus-core.mjs:131-142`） |
| capped web-fetch output | `agent.cordis.yml:376`（`fetchMaxOutputChars: 60000`） |
| tighter tool-result pruning | `agent.cordis.yml:263-265` |

⚠️ **一句话结论**：这份 preset 的"研究框架"是**纯提示词**，没有状态机、没有 schema 校验、没有角色间契约。可复用的是它的**纪律条款**和**外部工具设计**，不是它的架构。

---

## 2. 研究循环 R→R→T→P、三方向攻击、多角色评审

### 2.1 R→R→T→P 逐字母

唯一出处是 `agent.cordis.yml:94-95`：

```
94:      # Loop (R→R→T→P; one round per cycle)
95:      Research: read relevant files, run verifications; ... Record: persist outputs to analysis/. Think: update state, detect contradictions, confidence (0-100%), decisive path, meta-review strategy. Plan: next actions (Plan-Before-Action). ...
```

| 字母 | 含义 | 出处 |
|---|---|---|
| **R** | **Research**：读相关文件、跑验证；动手前先登记"什么结果能推翻它、怎么判定"，再从 **≥2 个角度**攻击，事后拿结论对照那个**预先登记的判据** | 行 95 第 1 段 "Research: read relevant files, run verifications; before attacking a claim register what result would refute it..." |
| **R** | **Record**：把产物落盘到 `analysis/` | 行 95 第 2 段 "Record: persist outputs to analysis/." |
| **T** | **Think**：更新状态、检测矛盾、置信度（0-100%）、决定性路径、元评审策略 | 行 95 第 3 段 "Think: update state, detect contradictions, confidence (0-100%), decisive path, meta-review strategy." |
| **P** | **Plan**：下一步动作，且必须 **Plan-Before-Action**（非平凡动作前先把短计划写进本轮报告或计划文件；读文件/搜索/小计算不必） | 行 95 第 4 段 "Plan: next actions (Plan-Before-Action)." |

补充约束（同一行 95）：一轮 = 一个 cycle（行 94 "one round per cycle"）；**第一轮不许收敛**（"Never converge first round — expand problem space (known/unknown/paths/traps) first"）；卡住的缺口按固定顺序兜（"relax assumptions → think backwards → experiment → smallest non-trivial case → record open problem, switch direction"）。

**⚠️ 未核实**：`R→R→T→P` 这个首字母缩写**在文件中从未被显式展开**。上面的映射是我根据行 95 的四个段落标签（Research / Record / Think / Plan）推断的。另一处可能相关的线索：行 115 强制要求每轮结束写一份带时间戳的报告（"Recording Discipline"），如果按"轮末报告"算，第二个 R 也可能是 Record-the-round。两种读法指向同一件事，不影响取用。

### 2.2 "三方向攻击"具体机制

三处证据拼起来才完整：

1. **方向定义**（`agent.cordis.yml:95`）："Hard propositions: 3 directions — forward proof, falsification (counterexample/search), probing (numerical/enumeration/SAT)"。即 **正向证明 / 反证（反例+搜索）/ 探针（数值+枚举+SAT）**。
2. **防退化的关键**（`agent.cordis.yml:40-42` 的文件头注释 + 行 95）：方向攻击必须对着**预先登记的 refutation criterion** 判定，而不是事后下结论。注释原话：「A claim is attacked against a pre-registered refutation criterion instead of a post-hoc verdict, which is what keeps "3 directions" from decaying into confirmation seeking.」——**这条是整个 preset 里最有价值的一句话**。
3. **方向落到哪里执行**（`danus-prompt.mjs:36`）：「3 directions: forward in-context; falsification & probing at scale → `start <p>`」——正向证明留在主上下文里做，反证与探针**丢给 Danus 集群批量跑**。

### 2.3 "多角色评审"具体机制

`agent.cordis.yml:124` 一段话定义完全部机制：

| 项 | 内容 |
|---|---|
| 触发条件 | **中心定理 / 论文完成** → 跑完整 6 角色评审；**中间引理** → 只需 ≥A+B + 逐行检查 |
| 6 角色 | A technical（技术）、B logic（逻辑）、C devil's advocate（魔鬼代言人）、D journal format（期刊格式）、E hand-waving scan（含糊扫描）、F lay reader（外行读者） |
| 强制项 | "Reconcile all comments, zero exceptions"（全部意见必须处理，无例外）；顺序 "fatal first, then severe/moderate"；改动过的部分要**重评审**，大改动走完整流水线 |
| 一条锐利的规定 | "tool-confirmed conclusions still need logic check (**verification ≠ proof**)"（行 124）—— 机器验证通过 ≠ 证明成立，仍需逻辑审查 |
| Danus 侧的复用 | `danus-prompt.mjs:40`："Load-bearing: Iron Rules + 6-role"；即承重结论在 Danus 事实入库后，还要再过一遍 6 角色 |

**与我们的差别（预告 §7）**：它的 6 角色是**同一个 LLM 在同一次会话里扮演**，没有独立上下文、没有结构化产出、没有"每条发现必须带 evidence"的硬契约；而且"Reconcile all comments, zero exceptions"是提示词纪律，不是可校验的字段。我们的 H 角色是**独立只读**且发现必须带 evidence，这一层比它强。

---

## 3. 预算与截止机制（`global-deadline.mjs`）

### 3.1 它是墙钟闹钟，不是预算账本

**⚠️ 重要区分**：`global-deadline.mjs` **不追踪 token、不追踪金额、不追踪轮数**。全文没有任何 token/cost/round 计数。它是一个纯粹的**到点停一切**的墙钟定时器。所以"预算机制"这个说法对它**不成立**——它只有"截止（deadline）"。

### 3.2 机制拆解

| 部件 | 位置 | 说明 |
|---|---|---|
| 状态与日志 | `global-deadline.mjs:21-22` | `global-deadline.json`（状态）+ `global-deadline.log`（日志），均在工作区 |
| 轮询 | 行 23 `CHECK_MS = 5000`、行 52-56 | 5 秒 tick，`ctx.effect` 注册清理 |
| 默认强杀延迟 | 行 24 `DEFAULT_FORCE_MIN = 10` | 到点后 10 分钟强杀兜底；行 206 夹紧到 `[0,120]` |
| **两阶段** | 行 77-154 | graceful（优雅）→ force（强杀）。`forceAt = at + forceMin*60000`（行 211） |
| 优雅阶段停什么 | 行 90-141 | ① Danus worker 全项目优雅停（复用 `danus stop` 语义）→ ② 本会话后台 jobs 全 kill（行 114-120）→ ③ 子孙 subagent 全部 interrupt + `drainContinuableDescendants`（行 121-128）→ ④ goal 的 objective **追加一句**"FINAL ROUND: write research-final-\<ts\>.md wrap-up, then update_goal complete"（行 136-138） |
| 强杀阶段 | 行 90-112、129-140 | Danus `--force`、jobs 再杀、subagents 再 drain、goal **pause**（行 140） |
| **永不杀宿主** | 行 219、264 | "不杀 DSH 宿主" / "never kills the DSH host" |
| 幂等与崩溃安全 | 行 167-192 | 先把 `forceStarted/graceStarted` **持久化再干活**（注释行 169："先持久化 started,再干长活 —— 崩溃也不会重放"）；失败则回滚标志位可重试 |
| 不并发 | 行 156-159 | `tickBusy` 互斥，"杜绝停停风暴" |
| **主动唤醒** | 行 60-75、82-87、147-152 | 每个阶段**开始和结束都推 notice**（`agent.followup`/`agent.steer`），理由（行 81）："用户第一时间知道 deadline 真的触发了、正在做什么" |
| 真实完成度汇报 | 行 102-110 | 优雅停之后再去数一次存活 worker，如实报告 "N worker(s) still finishing rounds — force phase will follow" |
| 工具契约 | 行 262-294 | `{ok, action, output, error}`；`cmd: arm|cancel|status`，`time: HH:MM`，`force_after_min` |
| 纪律条款 | 行 248-257 | arm 前先 `status`（有 pending 就先 `cancel`，"避免双闹钟打架"）；到点前改主意就 `cancel`；**arm 后不要空等**（"正常值班…不要空等"） |

### 3.3 与我们的 F 三维预算 / E 超时对照

先把我们的两套机制摆出来（证据见 §7 引用）：

- **F 的三维预算**（`test1\src\abflow\tools\attack_tools.py:12-15`，默认值 `:63-68`，schema 强制 `schema.py:866-877`）：
  ① `max_rounds` = **生命周期总量**（一个计划一生能走多少轮）；② `max_parallel_subgoals` = **瞬时并发**（一轮能同时挂几个子目标）；③ `max_persist_attempts` = **单点重试**（一个子目标能重试几次）；外加第 4 个键 `max_depth` = **嵌套深度**。四类键缺一即抛。缺一即抛的理由写在 `schema.py:870-871`：「只有轮数上限则单轮可以无限扇出，只有并发上限则可以无限轮」
- **E 的超时**：默认 `timeout=600` 秒（`agent_e.py:387-388`、`:527`）；超时**杀掉子进程**（`:465`、`:487`、`:494` 追加 `[超时]` 到 stderr）；超时的结局是 `result="inconclusive"` **且带可见 reason**（`:559-567`）；F 会把每个子目标的 `timeout` 转发给 E（`agent_f.py:740`）

| 维度 | dsh preset | 我们的框架 | 判定 |
|---|---|---|---|
| 预算类型 | **仅墙钟截止**；无 token / 金额 / 轮数 / 并发预算 | F 三维（总量/并发/重试）+ 深度；`interactions.DEFAULTS`（`interactions.py:92-100`）另有 6 个 loop 上限；E 有单次实验墙钟超时 600 s | **我们维度更多**（但 token 维我们也没有：FC-19 未落地，`13-...md:698`） |
| 触发主体 | 用户在对话里给"今晚 23:00 必须停"→ **LLM 自己**调 `deadline arm`（`global-deadline.mjs:249`） | F 的预算是**任务级参数**（`create_plan` 时写入并被 schema 校验） | **我们更可靠**：LLM 忘了 arm 就没有截止；我们的预算写不进表就抛 |
| 超时后的产出 | 强制"写 `research-final-<ts>.md` 再 complete"（`global-deadline.mjs:137`） | `status="stalled"` + `best_partial` **必填非空**（`schema.py:846-848`、`:929`）；E 超时 ⇒ `inconclusive` + reason（`agent_e.py:559-567`） | **等价**，我们更结构化 |
| **覆盖范围** | **跨四层**：Danus worker（全项目）+ 后台 jobs + 子孙 subagent + goal（`global-deadline.mjs:90-141`） | **没有墙钟截止**：`deadline|wall_clock|max_seconds|global_timeout` 在 `test1\src\abflow` **0 命中**；FC-20（取消语义）在 §7 矩阵里标 **未落地**（`13-...md:699`，并被 `:710` 列入"完全未落地 6 条"） | **这是它唯一比我们强的地方**（见 §7.6） |
| 停机可见性 | 每个阶段**开始和结束各推一次通知**；优雅停之后**再数一次存活 worker 并如实报告**"N worker(s) still finishing rounds"（行 81-87、102-110、147-152） | 未核实（无长时运行场景） | 值得抄（§7.6） |
| 崩溃安全 | 先把 `started` 标志**持久化再干长活**；失败回滚标志位可重试；`tickBusy` 互斥防"停停风暴"（行 156-159、167-192） | 设计草案 `:179`「**写实体先于翻状态位**」+ LESSONS P5/P6 | **同一条原则，已覆盖** |
| 边界声明 | "不杀 DSH 宿主"（行 219、264） | 各角色"已知边界"章节 | 已覆盖 |

**结论**：dsh 的"预算"其实只是**一个墙钟闹钟**，没有账本。它的独特价值不在"预算更多维"，而在**截止是跨层的、且停机过程对用户可见**。我们 F/E 的预算与超时**比它精确得多**，缺的只是那一个跨层墙钟（§7.6）。

---

## 4. 文献工具 `paper.mjs` 与我们 A 的 `providers.py` 对照

### 4.1 提供方与回退链

| 提供方 | 常量 | 用途 | 位置 |
|---|---|---|---|
| OpenAlex | `https://api.openalex.org` | **主检索**（`/works?search=`）+ DOI/W-id 精确取 | `paper.mjs:30`、`240-253`、`255-264` |
| Semantic Scholar | `.../graph/v1` | **arXiv id 首查**，另有 429 单次重试（`sleep(2000)`） | `paper.mjs:31`、`266-277` |
| DataCite | `api.datacite.org/dois` | **arXiv id 兜底**（`10.48550/arXiv.<id>`） | `paper.mjs:32`、`300-320` |
| Unpaywall | `api.unpaywall.org/v2/` | DOI → OA 全文候选；注释说明理由："OpenAlex `is_oa:false` can miss repository copies Unpaywall has" | `paper.mjs:757-786` |
| alphaxiv.org | — | arXiv id → PDF 镜像 | `paper.mjs:681` |
| Google Scholar / Bing 抓取 | — | 非 OA 论文的**发现式**下载 | `paper.mjs:703-953` |

**回退优先级**（`getByArxiv`，`paper.mjs:322-334`）：S2 → DataCite → null。**arXiv 的 DataCite DOI 会被特意拆开**（行 363-377）：`10.48550/arXiv.<id>` 先还原成裸 arXiv id 再走 S2/DataCite 链，因为"OpenAlex 不索引它，会回 404"（行 364-366）。

**⚠️ 与我们 A 的差别**：它**没有优先级分层、没有配额**。没有"先查本地、再查权威库、再查预印本"的分层概念，也没有 per-source 配额。唯一的类配额机制是两个内存冷却：

| 机制 | 值 | 位置 |
|---|---|---|
| Scholar 结果缓存 TTL | 30 min | `paper.mjs:709` |
| Scholar 全局限流冷却 | 10 min（`SCHOLAR_COOLUNTIL`） | `paper.mjs:708`、`710-711`、`1107` |
| S2 429 单次重试 | 1 次，等 2 s | `paper.mjs:269-277` |
| HTTP 429 统一处理 | 抛"rate limited (HTTP 429) by \<host\> — wait a few seconds and retry" | `paper.mjs:68-72` |
| 单次 fetch 超时 | `FETCH_TIMEOUT_MS = 20000` | `paper.mjs:33`、`62` |

### 4.2 它的**返回契约是不是三态**？——**不是。**

`paper` 工具的 output schema 是**二态信封**（`paper.mjs:1277-1288`）：

```js
{ ok: boolean, action: string, data: {}, output: string, error: string }
```

`render` 只会输出 `ok` 或 `failed`（行 1291-1293）。所有 action 都以 `{ok:false, action, error: <字符串>}` 收尾（行 1235、1237、355、361、385、399、410、429、431、958、976、1011、1016、1018、1116）。

**但它的"失败"字符串里其实携带了多态信息**，只是**没有结构化**。`fulltext` 放弃时的措辞（`paper.mjs:1101-1116`）区分了 5 种终止情形：

| 情形 | 输出行（行号） |
|---|---|
| 根本没有可下载候选 | `no reachable full text. metadata=<来源>`（1102） |
| 有一批候选但都失败 | `main candidates (N tried): ...`（1103） |
| 搜到页面但没找到 PDF | `scanned (search-engine/repository pages): ...`（1105） |
| 找到但被 Cloudflare/付费墙挡 | `blocked (Cloudflare/paywall): ...`（1106） |
| 搜到 PDF 链接但不可达 | `pdf links found but unreachable:` + 每条的错误（1111-1113） |
| 限流导致**只做了部分发现** | `note: Google Scholar is rate-limited (captcha cooldown) — discovery was partial; retry later for a fuller hunt.`（1107） |

**这正是"三态"该出现而没出现的地方**：`blocked`（被挡，换渠道可能成功）、`not_found`（确实没有，别重试）、`partial`（限流，重试可能更全）——三种语义完全不同的结局，全被塞进一个 `ok:false` 的自由文本 `error` 里，机器读不出来，只有 LLM 读得懂。

另一个**很强的防幻觉设计**是 `titleResembles`（`paper.mjs:336-351`）：

> 注释原话（行 336-341）："Whether an OpenAlex top hit is close enough to the query to be presented as that paper... **This is the guard that stops a mistyped title from becoming a confident, wrong citation.**"

规则：查询词与标题的 ≥4 字符 token 重合数必须 ≥ `max(2, ceil(q/2))`（行 349-350）。行 402-427 进一步说明：**OpenAlex 对任何搜索都会回东西**，没有这道闸，一个打错的标题就会变成一条自信的假引文。若不过闸，它返回 `ok:false` 并把 OpenAlex 返回的**最近 3 个标题**列出来让用户自己判断（行 419-426）——**拒绝给答案 + 给出邻近候选**，这个模式很值得学。

还有一道**正文相关性闸** `isRelevant`（`paper.mjs:1020-1043`）：下载到的 PDF 抽出的头部若与标题词/作者姓毫无重合，判为"拿错了副本"而跳过；注释说明 OCR 会打乱词，所以故意放宽（行 1022-1023）。

### 4.3 Token 经济学（它的核心卖点）

| 手段 | 值 | 位置 |
|---|---|---|
| 摘要上限（`get`） | 2200 字符 | `paper.mjs:34` |
| 摘要片段上限（`search`，默认关闭） | 280 字符 | `paper.mjs:35`、`1267` |
| 单页抓取上限 | 60 000 字符（`tool-web`） | `agent.cordis.yml:376` |
| 全文默认/最大 | 8000 / 30000 字符 | `paper.mjs:42-43`、`959` |
| 单 PDF 字节上限 | 30 MB | `paper.mjs:41` |
| 空白折叠 + "Abstract:" 前缀剥离 | — | `paper.mjs:86-96` |
| 截断时提示继续读 | "…(truncated at N chars — call again with a larger maxChars to read more)" | `paper.mjs:964` |
| **确定性本地缓存键** | `keyFor(m)` = arXiv id 或 DOI slug；`paper fulltext` 先查 `papers/` 本地库，"a stored paper is never re-downloaded" | `paper.mjs:500-527`、`1043`、`1254` |
| `references.md` 追加一行引文 | `refLineFor` | `paper.mjs:529-537`、`1212` |

**"store 一次，之后 fulltext 离线即时"**（`paper.mjs:1249`）是一个很干净的成本控制思路：把"下载"与"阅读"解耦，并用**确定性键**保证同一篇论文永不重复下载。

---

## 5. Danus 集成：Danus 被当成什么用

### 5.1 装配形态：**一个工具** + **一段提示**

- `danus-console.mjs`（47 KB）注册工具 `danus`（`danus-console.mjs:759-820`），17 个 action：`health/list/status/ps/start/stop/finalize/new/problem/assign/project/facts/search/memory/worker/supervise/deadline`（行 768）。
- `danus-prompt.mjs`（5.5 KB）只注册提示段 `danus:collaboration`（`order: 20`），不含任何逻辑。

### 5.2 定位：Danus 是**执行底座 + 内部验证器**，不是评审员

`danus-prompt.mjs:24` 一句话定义：

> 「`danus` drives the local swarm (C:/Users/ysc20/Danus, deepseek-v4-flash, Windows): **parallel workers prove, one stateless verifier gates every fact, per-project fact graph = only truth.** You orchestrate via the tool; math runs in swarm contexts, not yours.」

关键条款：

| 条款 | 原文要点 | 行号 |
|---|---|---|
| **派什么** | lemma proofs、counterexample/enumeration/SAT searches、long autonomous explorations、brute-force sweeps | 29 |
| **留什么** | decomposition、synthesis、final judgment、load-bearing review、paper decisions | 30 |
| **回传契约** | "fact_id + one-line digest + status — **never full derivations**"；承重事实要**再核一遍**（Iron Rule 2） | 31 |
| **事实闸门** | `fact_submit` → verifier；**只有 verifier 说 `correct` 才是 fact** | 40 |
| **验证器的边界（最重要）** | 「Facts (by id) = truth; global memory = awareness, **never proof**. **Verifier = strong LLM, NOT formal proof — final review yours.**」 | 59 |
| **没有撤回动作** | 「No revoke action: retraction → surface to user (Danus main agent holds `fact_revoke`; cascades)」 | 59 |
| **派活粒度** | "Worker = one lemma, deep focus, verifier-gated — more specialized & cheaper than in your context" | 29 |
| 入口/改靶 | `new <p> [roles high:3,xhigh:4]` → `problem <p> --text "<target>"`；**中途改靶走 `assign`**，"do not overwrite PROBLEM.md casually, it re-scopes the whole swarm" | 35、37 |
| 何时用 `ps` | `status` = 心跳；`ps` = **进程真相**（"reach for it when status says running but nothing progresses"） | 46 |
| 停止 | `stop`（跑完本轮再干净退出，no orphans）vs `stop --force`（"only when a worker is stuck beyond status' `stuck?` soft, deadlocked, or the user demands an immediate halt"） | 42 |

### 5.3 编排层：supervise（值班节奏）+ deadline（Danus 专属闹钟）

`danus-console.mjs:620-691` 的 `runSupervise` 是一个**节奏状态机**：`start`(interval_min 默认 30 / max 720，可选 `until` HH:MM，行 629-635) → 到点推 notice 唤醒主进程（行 497-534）→ `beat` 巡检（行 668-689，未到点就回 "挂起等待"，**不空转**）→ `record` 落盘关键产出 → `final`（全部 worker 停）则做总分析、写 `research-final-<ts>.md`、`stop`（行 683-689）。

**这是它在"长时无人值守"上最实用的东西**：不让 LLM 自己轮询（费钱），而是**插件定时推 notice 唤醒**（行 532-534）。`global-deadline.mjs:60-75` 用的是同一套 `agent.followup`/`agent.steer` 唤醒原语，注释明说是"goal-round-driver 同款"。

### 5.4 与我们的对照（预告）

我们的 D 角色做"矛盾闭环+三级溯源"、E 做"证据等级 proof/cross_check/heuristic"。Danus 的思路与 E **同构但更弱**：它只有"verifier 说 correct 才是 fact"一个**二值**闸门（`danus-prompt.mjs:40`），没有证据分级；但它**诚实标注了闸门的边界**——"Verifier = strong LLM, NOT formal proof"（行 59）。我们 E 的 `proof/cross_check/heuristic` 三级 + "计算类拿不到 proof"是对同一问题的**更强解**。

---

## 6. DeepMath 团队的智能体与流程

对照的仓库在 `<D>moonshine\`（Python 包，约 150 文件）与 `<D>deepmath-ci\`（runner + 2 个技能 + 测试 + 2 个 GH workflow）。`<D>deepmath-dataset\` 本轮**未核实**。

### 6.1 一个数学研究任务的步骤怎么组织

**它真有状态机**（这是与 dsh preset 最根本的区别）。`<D>moonshine\agent_runtime\research_workflow.py`：

| 项 | 内容 | 行号 |
|---|---|---|
| 版本 | `WORKFLOW_VERSION = 3` | `:44` |
| 阶段（只有 2 个） | `RESEARCH_STAGES = ["problem_design", "problem_solving"]` | `:64` |
| 阶段 1 的 6 个活动 | `"literature_scan", "cross_domain_explore", "problem_generation", "quality_evaluation", "problem_refinement", "design_checkpoint"` | `:66-73` |
| 阶段 2 的 8 个活动 | `"problem_decomposition", "solver_branching", "lemma_extraction", "proof_integration", "pessimistic_verification", "correction", "strengthening", "persistence"` | `:75-84` |
| 活动元数据表 | `ACTIVITY_SPECS`：14 个 dict，每个带 `stage/label/goal/skills/tools/good_outputs` | `:94-219` |
| 转移不是图，是"模型选 + 代码校验" | `stage_decision` 枚举 `["stay_in_stage","advance_to_problem_solving","return_to_problem_design","complete_project"]` | `:433-436` |
| 转移解析器（**硬护栏都在这**） | `_resolve_next_stage_and_activity` | `:3785-3857` |
| 状态文件 | `projects/<p>/memory/research_workflow.json`、`research_state.json`、`ledger.jsonl`、`research_index.sqlite`、`verification.jsonl` | `:902-920` |
| 全局硬不变量 | `GLOBAL_HARD_INVARIANTS`：如 `:348`「Do not promote unverified claims into formal knowledge memory…」、`:350`「Any serious verifier objection means the proof is not established.」 | `:347-353` |

**它的硬护栏值得逐条看**（这是全仓库最有价值的一段）：

1. **质量门拒绝 ⇒ 强制退回**（`:3826-3835`）：质量评估不通过时，代码**强制**回到 `problem_design`，并注入一句指令「Call `load_skill_definition` for `quality-assessor`, then call `assess_problem_quality` once…」——不是"提醒模型"，是改写下一次的状态与提示。
2. **verdict ≠ verified ⇒ 改道**（`:3838-3841`）：`persistence` 被重定向到 `correction`。即"你自己说完成了"被代码否决。
3. **完成需要两把钥匙**（`:3844-3847`）：`complete_project` 要求 `final_verification_gate.ready_for_final_verification` **且** `verdict=="verified"`。
4. **修不好就升级**（`:3849-3855`）：修正次数 ≥3 ⇒ 强制进入 `strengthening`（换方向），而不是继续修。
5. **进入阶段 2 的前置门**（`:2539-2565`）：`can_enter_problem_solving` 要求非空 `active_problem` + `review_status=="passed"` + `metadata.skill_slug=="quality-assessor"` + `overall >= 0.55`（`:2563`）。

**两个诚实的补充**：① 它装了 `langgraph`，但 `LangGraphCheckpointAdapter`（`:818-868`）只用了**一个名为 `checkpoint` 的节点**（`:830-834`）；真正的流程控制在 `_resolve_next_stage_and_activity` 里，LangGraph 是装饰性的。② 状态机在 `deepmath-ci` 侧退化成队列：`run_archive.py:46` `DISCOVERY_ROW_STATUSES = {"selecting","proposed","running","verified","failed","stopped"}`，修复循环只被 `--max-turns` 约束（`:1472-1611`）；阶段 2 的 Codex 控制器"intentionally thin"（`mathematical-concept-agent\README.md:8-12`，**据文档，未在代码中核实**），轮次契约只有三态 `status ∈ ["continue","complete","blocked"]`（`schemas\turn-result.schema.json:5-8`）。

### 6.2 角色划分：**不是角色，是"技能 + 3 个 agent profile"**

| 类型 | 内容 | 路径 |
|---|---|---|
| agent profile（只有 3 个） | `research-control-loop`（`:5` "Prompt instructions for long-running autonomous mathematical research."，`:35` Stage 1 / `:69` Stage 2 / `:45` 质量门 / `:106` 最终 `verify_overall(scope="final")`）、`moonshine-core`（`:5` "Research-first agent profile…"，`:8` `"default": true`）、`agent-neural-network-functions`（正文未核实） | `<D>moonshine\assets\agents\builtin\*\AGENT.md` |
| **技能（36 个）** | 研究类：`literature-survey`、`cross-domain-explore`、`problem-generator`、`quality-assessor`、`problem-refiner`、`propose-subgoal-decomposition`、`problem-solver`、`lemma-prover`、`direct-proving`、`construct-toy-examples`、`construct-counterexamples`、`proof-constructor`、`proof-corrector`、`identify-key-failures`、`strengthening-agent`、`research-consolidation`、`record-novelty`、`math-research-loop`、`conclusion-manage`、`query-memory`、`memory-hygiene`；验证类：`pessimistic-verifier`、`verify-overall`、`verify-correctness-{assumption,computation,logic}`；内部类（被 `tools\catalog_tools.py:33-34` 挡住，模型不可见）：`extract-*`、`memory-trigger-evaluator` | `<D>moonshine\assets\skills\builtin\` |
| 质量门白名单 | `QUALITY_GATE_AGENT_SLUGS = {"research-control-loop","neural-network-functions-researcher"}` | `<D>moonshine\agent_runtime\research_mode.py:113-116` |

**关键设计思想**：`research-control-loop\AGENT.md:122-123` 明写「**Skills are not workflow nodes.**」「**Tools are not reasoning substitutes.**」——技能是"可加载的方法论文本"，流程节点另有 `ACTIVITY_SPECS`。**它把"方法"（skill）与"流程位置"（activity）彻底分开了**，这是与我们 A–H 平铺角色最不同的组织方式。

### 6.3 防幻觉机制（4 条，都有代码）

| # | 机制 | 证据 |
|---|---|---|
| 1 | **严格结构化输出**：所有 LLM 返回的 schema 一律 `additionalProperties: False` | `research_workflow.py:48-62`、`:225-237` `QUALITY_SCORE_SCHEMA`、`:240-268` `STATE_ASSESSMENT_SCHEMA`（含 `stuck`/`repairing`/`verified_partial`）、`:271-281`、`:284-294`、`:297-307` `FINAL_VERIFICATION_GATE_SCHEMA`；`tools\verification_tools.py:19-35` `PESSIMISTIC_REVIEW_SCHEMA`（含 `gaps` `:29`、`hidden_assumptions` `:30`、`citation_issues` `:31`）；`tools\research_tools.py:16-47`（`:95` 处校验）；`memory_schemas.py:9` `STATUS_ENUM=["candidate","partial","verified","retracted"]` |
| 2 | **悲观多维验证**：assumption / computation / logic 三个维度，**全过才算过**；失败默认 fail-closed | `verification_tools.py:336-357` 逐维 `focus_rule`（如 "Only check whether every condition and assumption involved in the subproblem has been used."）；`:986-996` `verify_overall`「Run all three correctness dimensions and pass only if all pass」（合取在 `:1031`）；**`:385-395` `_failure_review` 在失败时返回 `verdict="inconclusive"` 且所有布尔为 False**（默认悲观，不是默认通过） |
| 3 | **出处归档（origin archive）**：验证工具**绑定项目+会话**、标题必须匹配、sha256 留痕、fail-closed 合取 | `run_archive.py:873-994`：`:893-896` 越界调用直接 raise「verification tool was called outside its bound project/session」；`:919-920` 标题必须匹配；`:955-960` 数学+历史+格式+无待修项的**合取**；`:978` `archive_sha256`、`:979` `historical_evidence_sha256`、`:980` `source_material_count`；`:991` 只有全过才返回 `verified_archive`；确定性格式检查 `:766`/`:926`/`:953`；材料哈希 `:243`/`:251`/`:262`；测试含"旧状态无指纹必须 fail-closed"（`tests\test_run_archive_material_provenance.py:101`）与 8 条篡改测试（`tests\test_discovery_state_integrity.py:44`） |
| 4 | **声明哈希去重 + 全局不变量** | `research_workflow.py:1178` `verified_claim_hashes`；`:347-353` `GLOBAL_HARD_INVARIANTS` |

**⚠️ 反向发现（重要的负面结论）**：它的**引文纪律比我们弱得多**。全仓库找不到"引文必须逐字回验"的硬规则：`citation_issues` 只是一个 schema 字段 + 聚合（`verification_tools.py:31`），而 `<D>deepmath-ci\skills\verify-math-object-origin-archive\SKILL.md:26` 明确写「**citations or a separate evidence note are not acceptance requirements**」。与之相对，`pessimistic-verifier\SKILL.md:31` 只说"若评审报了 citation issue 就算证明未成立"。也就是说：**引文错误在它那里是"评审员可能会提"的事，在我们这里是被 schema + 三态计数 + 负控强制的事。这一层我们明显更强，不要向它靠拢。**

### 6.4 评估机制

| 项 | 内容 | 证据 |
|---|---|---|
| 评分表 | 「Score each dimension from 0 to 1 using weights: **impact 40%, feasibility 25%, novelty 20%, richness 15%**」 | `moonshine\tools\research_tools.py:133`；镜像在 `research_workflow.py:122` |
| 阈值 | `overall >= 0.55` 才放行进入阶段 2 | `research_workflow.py:2558-2564` |
| 评审次数上限 | `verification_tools.py:360-382`；默认 `verification_dimension_review_count: 1` | `moonshine_constants.py:152` |
| CI | `offline-runner-tests.yml:13` `timeout-minutes: 5`、`:17` matrix `["3.9","3.11"]`、`:29` `unittest discover`；`moonshine-integration-tests.yml:23` **钉死 `MOONSHINE_COMMIT: bb0e4aa...`**、`:28` `timeout-minutes: 10` | `<D>deepmath-ci\.github\workflows\` |
| 确定性裁判 | `integration_run_archive_moonshine.py:77` `ScriptedArchiveProvider`、`:115` `PassingVerificationProvider`（**用脚本化 provider 替代真 LLM，使评估可复现**） | `<D>deepmath-ci\tests\` |
| 测试规模 | `test_run_archive_offline.py:162`（17 条，`:381` 多余 issue 即 fail-closed、`:390` 输出必须绑定会话/项目+哈希匹配、`:437` provider 预检 fail-closed）；`test_discovery_state_integrity.py:44`（8 条篡改）；`moonshine\tests\test_architecture.py`（**8493 行**，`:2834` 断言"质量门在未通过评审时阻止 `advance_to_problem_solving`"） |  |
| 数值型研究质量基准 | **未核实**（未找到 benchmark 文件） |  |

### 6.5 与我们的对照摘要

| 维度 | DeepMath | 我们 | 判定 |
|---|---|---|---|
| 流程表达 | 代码里的活动常量表 + 状态机 + 硬护栏（`research_workflow.py:94-219`、`:3785-3857`） | 12 张表 + I1–I12 冻结契约（`interactions.py`） | **各有取向**；它的"转移硬护栏"是我们要学的那部分 |
| 防幻觉 | 结构化 schema + 悲观多维验证 + 出处归档哈希 | 三态纪律 + 证据等级 + 未接线即失败 + 负控 + `code_hash` | **我们略强**；它的**出处归档哈希**与**工具绑定会话**是新增量 |
| 引文 | 弱（`SKILL.md:26` 明确不要求） | 逐字回验 + 三态计数（`schema.py:385`） | **我们强，别学它** |
| 评估 | **问题质量门**（加权评分 + 0.55 阈值 + 未过强制退回） | **没有"这个问题值不值得攻"的门**；D 只判"证据是否不足"，F 只判"预算是否用尽" | **它的最大增量**（§7.10） |
| 预算 | token 级预算 + 8 个 agent 限额（`moonshine_constants.py:143-153`，`max_tool_rounds 8` / `max_model_rounds 12` / `research_max_iterations 100`） | F 三维预算 + `interactions.DEFAULTS` 六个 loop 上限 + E 600 s 超时 | **等价**；它的 token 预算是 FC-19（我们**未落地**）的一个先例 |
| 幻觉类 | 无 USD/金额预算（**未核实**） | 无 | 相同 |

---

## 7. ⭐ 值得取用的具体点子

按"是否现在值得做"排序。每条给出：是什么（路径+行号）/ 为什么 / 落在我们哪里 / 成本 / 值不值得。

### 7.1 ⭐ SAT/UNSAT/穷举结果必须携带**证书**（条件必填字段）—— 现在就该做

**是什么（dsh）**：`agent.cordis.yml:106`
> 「SAT/UNSAT and enumeration results carry a **certificate** (assignment, core, exhaustive boundary) before entering the fact graph」

同一句还要求：「re-run the same script to the same output and **re-derive one instance independently**（hand or second method）」。动机写在文件头 `:43-45`：「a run is not evidence on the program's word alone」。

**为什么有价值**：这是数学自动化里最容易过声称的一处——"穷举到 N 没找到反例"与"不存在反例"之间隔着**搜索边界**。我们现在的 `Experiment.observations`（`schema.py:728`）是自由 dict，注释只是举例"极值、命中数、网格分辨率"，**没有任何字段被强制要求写下边界**；`counterexample` 只在 `result="refutes"` 时必填（`schema.py:776-778`），而"穷举支持"这一支什么都不缺。grep 证据：`certificate|witness|unsat|enumeration_bound` 在 `test1\src\abflow` 中 **0 命中**。

**落在我们哪里**：`schema.py` 的 `Experiment`（`:700-739`）+ `validate()`（`:741-799`）。**我们已经有 5 条同型条件必填的先例**：
- `:757-762` 计算类方法不得声称 `evidence_kind="proof"`
- `:764-768` 声称 proof 必须有 `verifier_output`
- `:770-774` `exit_code != 0` 时 result 必须 `inconclusive`
- `:776-785` `refutes` 必须有 `counterexample`
- `:794-799` 有 `code_path` 就必须有 `code_hash`

照着加第 6 条即可：`method in ("numeric","symbolic","exhaustive_search")` 且 `result != "inconclusive"` 且 `negation_kind in ("not_proved","no_local_evidence")` 时，必须有非空 `certificate`（或 `observations["search_bound"]`）。另外把"独立复现"落成 `reproduced_by`（第二方法名或第二 `experiment_id`）。

**成本：小**。1 个字段 + 1 条 `validate` 分支 + 1 条负控测试（负控套件的位置见 FC-09，`13-...md:688`）。不动表结构、不改 `interactions.py` 签名、不碰 `LOCK_ORDER`。

**值得：值得，且可以立刻做**。它是"在最容易说谎的那一格加一道机械闸门"，与我们 FC-22（"数值只是交叉验证"）同一族，且延续了我们自己已有的条件必填模式。

### 7.2 ⭐ 让 F 消费"连续无进展轮次"作为提前终止 —— 修的是我们自己的 P4

**是什么（dsh）**：`agent.cordis.yml:115`
> 「**Stop after 2 consecutive no-progress rounds** (empty counts): no new falsifiable claim, proof step, or confirmed artifact from the prior round — **restating a summary is not progress**.」

配套动机在文件头 `:48-49`：「The stop rule now names what counts as progress, closing the loophole where **restating a summary reads as a productive round**.」

**为什么有价值**：我们 F **只**按预算停——`agent_f.py:472` 的 `can_round(...)` 只看 `max_rounds` / `depth`。但 `history[i]["outcome"]` 已经在写 `"no_change"`（`agent_f.py:491`、`:507`），**这个信号被生产出来，却没有任何代码消费它**。这正是 `LESSONS.md` P4「**检测到了却没有消费**」（`test2\LESSONS.md:199`）的又一处实例——和当初"引文三态检测到了但计数合并"是同一类。

**落在我们哪里**：`agent_f.py` 的 `step()` 终止判定处（`agent_f.py:466-512`），紧挨现有的"轮数用尽 ⇒ stalled + best_partial"分支，并列成第二种触发。`stalled` + `best_partial` 的既有契约完全不变（`schema.py:929`）。**判据必须是机械的**（照 FC-26 的要求，"不许感觉"）：连续 N 轮 `outcome == "no_change"`，N 默认 2；并把 dsh 那句"什么算进展"写进 docstring 作为判据定义。

**成本：小**（读 `history` 计数 + 一个常量 + 1 条测试）。**值得：值得**——纯用现有字段、不改契约，顺手补了我们 P4 的一个真实缺口。

### 7.3 预注册反驳判据：先写下"什么结果会推翻它"，再动手

**是什么（dsh）**：`agent.cordis.yml:95`
> 「before attacking a claim **register what result would refute it and how you would decide** — then attack from ≥2 angles and judge the outcome against that criterion, **not after the fact**」

配套的文件头注释 `:40-42` 解释了为什么这是关键：「A claim is attacked against a pre-registered refutation criterion instead of a post-hoc verdict, which is what **keeps "3 directions" from decaying into confirmation seeking**.」

**为什么有价值**：我们 D 这一层其实做得不错——`a_no_keyword_hit` / `b_low_degree_unverified` / `contradiction` 三条判据（`agent_d.py:34`、`:336-402`）把"查不到"如实归类为**证据不足**而不是"研究结论"，`13-...md:203` 也强调"'知识不足'必须是可核实判据，不许'感觉'"。**但 F 没有这一层**：`AttackPlan.subgoals[i]` 只有 `text/owner/status/...`（`schema.py:836-839`），没有任何"这个子目标怎样算被证否"的字段——因此一个失败子目标只能**事后**补 `blocked_reason`，判据是事后写的。dsh 的增量就是那个**时序**：先登记，后裁决。

**落在我们哪里**：`AttackPlan.subgoals[i]` 增一个 `refutation_criterion`（或 `decisive_test`），在 `create_plan` 时**必填非空**（照 `problem_key` 的既有强制模式，`schema.py:855-858`）；`verify.py` 里加一条"子目标以 `closed`/`blocked` 收尾时，`history` 里至少有一条记录引用了该判据"。类型上它是 FC-26（可核实判据）在 F 上的补全。

**成本：小**（1 字段 + 1 条 validate + 1 条 verify 检查）。风险是让 `create_plan` 更难调用——但那正是它的目的。

**值得：值得（P1）**。注意别退化成一句空话：判据要写成"可判定测试"的形状（例如"若存在 n ≤ 10⁶ 使 P(n) 为假，则本子目标被证否"），并在文档里给 2–3 个正例。

### 7.4 模糊匹配闸门：**不够像就拒绝给答案，并列出最近的候选**

**是什么（dsh）**：`paper.mjs:342-351` `titleResembles` —— 查询词与标题的 **≥4 字符 token** 重合数必须 ≥ `max(2, ⌈q/2⌉)`；不过闸时的行为在 `:419-426`：返回 `ok:false` **并把上游返回的最近 3 个标题列出来**让调用者自己判断。动机注释 `:336-341`：
> 「**This is the guard that stops a mistyped title from becoming a confident, wrong citation.**」

配套还有下载后的**正文相关性闸** `isRelevant`（`:1020-1043`）：抽出的正文头与标题词/作者姓毫无重合 ⇒ 判为"拿错了副本"而跳过（注释 `:1022-1023` 说明 OCR 会打乱词，所以故意放宽）。

**为什么有价值**：我们的 `dedup_key_of`（`providers.py:466`）是 DOI → title+year → title hash，属于**精确/规范化**匹配。当上游用**自由文本**（标题、概念名）去探测时，provider 一定会回东西——`paper.mjs:402-408` 的注释把这句说透了：「OpenAlex **always** answers a search with *something*, so without it a mistyped or nonexistent title came back as a confident, unrelated paper, which is a fabricated citation」。我们的 `_merge_candidates`（`providers.py:1688`）只做"填空不覆盖"，也不能拦住一个"错但完整的 top hit"。

**落在我们哪里**：`providers.py` 的候选归并层（`_merge_candidates` `:1688` 之前）与/或 `dedup.py:102` `find_existing_literature`；概念绑定处（B 的"概念名 → canonical concept"，参考 `agent_d.py:1043` 的口径优先级）。形态：一个**纯函数** `looks_like_same(query, candidate) -> bool`；不过闸时返回 `no_match` + `nearest: [≤3 个标题]`，而不是取 top1。这与 FC-25 天然合拍：**没有候选过闸 ⇒ `not_found`；provider 挂了 ⇒ `unverified`；两者不许合并**。

**成本：小**（约 20 行纯函数 + 一条负控：喂一个打错的标题，断言"不给记录"且 `nearest` 非空）。

**值得：值得做，但有一个前提我未核实** —— **未核实**：我们当前是否真的存在"自由文本标题/概念名 → 文献或概念"的模糊绑定点（A 的 provider 层拿的是结构化查询 `_QueryPlan.channel`，`providers.py:895`）。如果这条路径不存在，就先不做，等它出现时再做。

### 7.5 检索失败的第四态：`blocked`（被挡）≠ `failed`（没有）≠ `skipped`（没查）

**是什么（dsh）**：`paper.mjs:1101-1116`。放弃全文时它把结局分成五类并**逐条列出试过哪些候选**：
- `no reachable full text. metadata=<来源>`（`:1102`）
- `main candidates (N tried): ...`（`:1103`）
- `scanned (search-engine/repository pages): ...`（`:1105`）
- **`blocked (Cloudflare/paywall): ...`**（`:1106`）
- `pdf links found but unreachable:` + 每条的具体错误（`:1111-1113`）
- `note: Google Scholar is rate-limited (captcha cooldown) — discovery was **partial**; retry later`（`:1107`）

**为什么有价值**：这正是我们的 **FC-25**（"未证明 / 已证否 / 未搜索"三种否定必须分开，`test2\LESSONS.md:696`；`13-...md:704` 标**已落地**）在**检索层**的缺失对应物。我们的 `DOWNLOAD_STATUSES = ("ok","content_mismatch","failed","skipped")`（`schema.py:89`）里**没有"被挡/付费墙/限流"**这一类；`SEARCH_OUTCOMES = ("ok","no_results","search_failed","gave_up")`（`schema.py:76`）也不区分"对方拒绝"与"网络坏了"。而处置完全不同：`failed` 不该重试（省成本），`blocked` 换渠道/换镜像就能成功，`rate_limited` 应当稍后重试。

**落在我们哪里**：`schema.py:89` 的受控词表（受 `tools\table_tools.py:370` 的 `_NESTED_VOCAB` 强制）；A 的失败路径（`agent_a.py:203-211` 的 `gave_up`）。

**成本：小**（加枚举值 + validate + 下游分支）。⚠️ 但 FC-04 要求受控词表在 schema 层强制——**加值便宜，"改含义"不便宜**，所以一次想清楚：建议 `blocked` 与 `rate_limited` **两个**值，而不是一个含糊的 `other`。

**值得：值得做，但与 P1-6「接真实检索」同期**。现在没接真实检索，加了也没有生产者——`13-...md:1004` 对 FC-17/19 的"没有需求面，先做会是没人用的配置"这条论证同样适用。**现在应做的是把这个分类写进 A 的边界文档。**

### 7.6 跨层统一墙钟截止（优雅 → 如实报残余 → 强杀，且每阶段推通知）

**是什么（dsh）**：`global-deadline.mjs` 全文。要点：两阶段 `graceful` → `force`（`:77-154`）；覆盖**四层**（Danus worker 全项目 / 后台 jobs / 子孙 subagent / goal，`:90-141`）；**每个阶段开始和结束各推一次通知**（`:81-87`、`:147-152`，理由在 `:81`："用户第一时间知道 deadline 真的触发了、正在做什么"）；优雅停之后**再数一次**存活 worker 并如实报告残余（`:102-110`）；先把 `started` 标志持久化再干长活，崩溃不重放（`:167-192`）；`tickBusy` 互斥防"停停风暴"（`:156-159`）；**永不杀 DSH 宿主**（`:219`、`:264`）。

**为什么有价值**：我们**完全没有**墙钟截止——`deadline|wall_clock|max_seconds|global_timeout` 在 `test1\src\abflow` **0 命中**；§7 矩阵里 **FC-20（取消语义）标未落地**（`13-...md:699`）。我们现有的终止全是**计数器**（F 三维预算 + `interactions.DEFAULTS` 六个 loop 上限 + E 600 s 单次实验超时）。计数器管不了"这一批任务总共只能跑 40 分钟"。

**落在我们哪里**：实现 FC-20 时一并落地。形态：一个会话级 `DeadlineGuard`，各角色 `run()` 接受一个**共享取消信号**；到点先要求每个 in-flight 角色写 `best_partial` + `truncated=True`，再强杀。

**成本：中**。它要改**所有角色的 `run()` 契约**——这正是它贵的原因（也是 dsh 那边为什么做成了"插件旁路"而不是改工具）。

**值得：现在不值得做；但形状值得现在记下来。** 理由与我们自己文档一致：`13-...md:1004`（P2-2）判断 FC-17/19"本轮不跑长 LLM 会话，没有需求面"。截止同理。**建议现在只做一件事**：把 dsh 这个形状（两阶段 + 逐层 + 起止各推通知 + 崩溃安全标志 + 永不杀宿主 + 优雅停后如实报残余）作为 FC-20 的实现蓝本写进设计草案的 P2-2 条目，避免将来重新发明。

### 7.7 resume / 冷热启动：重新载入依赖链的**原文**，不许只凭摘要续做

**是什么（dsh）**：`agent.cordis.yml:118`
> 「Cold (no state): read README, latest state map, methodology guide, task list → rebuild state → plan cycle 1. **Hot (existing state / after compaction): reload state map + proof/evidence files of the active dependency chain; never continue from distilled reports alone.**」

配套 `:115`：「**Cite only disk-persisted details**（context-only derivations must be saved first）」。

**为什么有价值**：我们的表**就是**原文，所以现在不存在"摘要漂移"。但 FC-12（可重建存储的信息量守恒，`test2\LESSONS.md:586`，已落地）管的是"重建不应更少"；dsh 这条管的是**续做时的重载义务**。一旦 **FC-17（上下文压缩/剪枝/spill，`13-...md:696` 未落地）** 落地，这条就变成必需品：被压缩过的会话必须回到表里重读依赖链，而不是相信自己手上的折叠摘要。

**落在我们哪里**：FC-17 的实现文档 + 各角色 LLM 钩子的 resume 流程。

**成本：小**（一条流程纪律 + 一个"重载后依赖链表非空"的断言）。

**值得：现在不值得，与 FC-17 同期。** 现在写进设计草案作为 FC-17 的验收判据之一即可（成本几乎为零，收益是将来不必重新发现）。

### 7.8 环境性不可达要写进**运行期可见的**工具契约文本

**是什么（dsh）**：`paper.mjs:1115` 在失败输出的最后一行固定写「arxiv.org is SNI-blocked on this network; try a proxy, or the abstract via `paper get`.」；工具 description 里也写了（`:1254`）。同型做法：`agent.cordis.yml:447-448` 对 MathOverflow ——「Discussions are informal leads, **never citable as-is**」。

**为什么有价值**：我们每个角色的"已知边界"写得比它全（`13-...md:179`、`:203`、`:216`、`:579`），但那是**设计文档**；dsh 把它放在**模型每次调用都能看到的工具描述与错误文本**里。如果 D/E/G 的 LLM 钩子开了，文档里的边界不一定进上下文，而工具描述一定会——否则模型会反复重试一条注定失败的路（费钱）。

**落在我们哪里**：各角色工具声明的 description，以及 `ToolResult.fail` 的 message（`tools\base.py`）。

**成本：小**。**值得：值得（低优先级）**。原则一句话：**"已知边界"必须出现在 LLM 可见的位置，而不是只在设计文档里。**

### 7.9 ⭐【DeepMath】问题质量门：加权评分 + 阈值 + 未过强制退回

**是什么（DeepMath）**：
- 评分表（`<D>moonshine\tools\research_tools.py:133`，镜像 `moonshine\agent_runtime\research_workflow.py:122`）：「Score each dimension from 0 to 1 using weights: **impact 40%, feasibility 25%, novelty 20%, richness 15%**」
- 阈值 `overall >= 0.55`（`research_workflow.py:2558-2564`）
- **阶段门**：`can_enter_problem_solving` 要求 `review_status=="passed"` + `metadata.skill_slug=="quality-assessor"` + `overall >= 0.55`（`:2539-2565`）
- **未过则代码强制退回**并注入下一步指令（`:3826-3835`）
- 活动元数据里也写了：`quality_evaluation` 的 goal 就是那四个权重（`:119-126`）
- 测试锁死：`moonshine\tests\test_architecture.py:2834` 断言质量门在未通过评审时**阻止** `advance_to_problem_solving`

**为什么有价值**：这是我们**结构上真的缺的一块**。我们 D 的三条判据（`a_no_keyword_hit` / `b_low_degree_unverified` / `contradiction`，`agent_d.py:336-402`）回答的是"**证据够不够**"；F 的 `create_plan` 回答的是"**要不要多轮攻**"。**没有任何地方回答"这个问题值不值得攻"**。在接了真实检索、真开始消耗 token 之后，"哪些问题该放弃"会是最大的成本旋钮。DeepMath 给的形态非常可落地：**四个命名的维度 + 显式权重 + 一个阈值 + 一条强制退回转移**。

**落在我们哪里**：`research_questions`（`schema.py:494`）加分数与 `quality_verdict`，或在 D 上新增一个纯函数阶段（照 C 的 `score_breakdown`/`gaps` 的既有形态，`13-...md:579`）；门放在"从 question 升格为 `attack_plans` 之前"（即 I10 之前，`13-...md:529`）。**注意不要引入新 LLM**：四个维度都可以由已有表格数据确定性算出（impact≈被引用/关联概念数、feasibility≈能否找到支撑文献、novelty≈`a_no_keyword_hit`、richness≈关联关系数）——这才符合我们的 FC-16「确定性的部分绝不交给 LLM」（`test2\LESSONS.md:620`，已落地）。

**成本：中**（一个新评分函数 + 2–3 个字段 + 门 + 阈值标定 + 负控）。**最大风险**：权重与阈值没有数据支撑就是"拍脑袋的数"——会撞上 LESSONS 经验 5「同一个数字可以是四件不同的事，基准口径必须先对齐再引用」（`test2\LESSONS.md:91`）与 FC-24（基准口径是必填字段，**未落地**，`13-...md:703`）。所以如果做，**必须同时把权重来源与口径写成字段**。

**值得：值得（P1，但排在 7.1/7.2 之后）**。理由：它是唯一一条从"缺一整块能力"出发的建议，而 dsh 那边完全没有对应物。

### 7.10 ⭐【DeepMath】验证工具**绑定上下文**：不允许在别的语境里被调用

**是什么（DeepMath）**：`<D>deepmath-ci\run_archive.py:893-896` —— 归档验证工具被绑定到 project+session，**越界调用直接 raise**：「verification tool was called outside its bound project/session」；同时要求标题匹配（`:919-920`），并把 `archive_sha256`（`:978`）、`historical_evidence_sha256`（`:979`）、`source_material_count`（`:980`）写进记录，只有合取全过才返回 `verified_archive`（`:955-960`、`:991`）。测试覆盖"旧状态无指纹必须 fail-closed"（`tests\test_run_archive_material_provenance.py:101`）。

**为什么有价值**：它挡的是一种很隐蔽的过度声称——**用一次"验证过"的绿灯去担保另一条命题**。我们的 E 已经有很强的等级约束（`schema.py:757-762` 计算类不得 proof、`:764-768` proof 必须有 `verifier_output`），但**`verifier_output` 是一个自由字符串**：没有东西强制它属于 `Experiment.claim_key`。也就是说，格式上允许把 A 命题的检查器输出粘到 B 命题的行上。

**落在我们哪里**：`Experiment`（`schema.py:700-739`）。两个小改：① 新增 `verifier_subject_key`，`evidence_kind="proof"` 时**必须**等于 `claim_key`（条件必填，同型先例已有 5 条）；② 把"能力绑定"写进 E 的边界文档（FC-06「角色即权限面」目前标**部分落地**，`13-...md:685`）。

**成本：小**（1 字段 + 1 条 validate 分支 + 1 条负控）。**值得：值得，可归入 7.1 一起做**（同一次改 `Experiment.validate`）。

### 7.11 ⭐【DeepMath】悲观默认：验证失败必须是 `inconclusive`，不是 `False`

**是什么（DeepMath）**：`<D>moonshine\tools\verification_tools.py:385-395` `_failure_review` —— 验证器失败时返回 `verdict="inconclusive"` 且**所有布尔为 False**（fail-closed 默认）；`:986-996` `verify_overall` 三个维度**合取**（`:1031`）。

**为什么有价值**：这条**我们已经有了**——`agent_e.py` 的"exit_code 优先于脚本自己打印的 supports"（`tests\test_agent_e.py:184`）与超时 ⇒ `inconclusive` + reason（`agent_e.py:559-567`）是同一条原则；FC-01 三态纪律（`test2\LESSONS.md:494`）与 LESSONS 经验 3「"没做"与"做了但没结果"必须可区分」（`test2\LESSONS.md:73`）覆盖得更全。**结论：不需要改。** 列在这里只是为了让读者知道这是两个独立先例的**收敛点**（两处都独立得出同一结论 → 这条原则的置信度更高）。

### 7.12 不需要改的（我们的对应物已等价或更强）

| dsh / DeepMath 的做法 | 出处 | 我们的对应物 | 结论 |
|---|---|---|---|
| `paper` 工具二态信封 `{ok, data, output, error}` | `paper.mjs:1277-1288` | FC-01（`13-...md:680`）+ FC-25（`13-...md:704`，已落地）；关键判定都是三态：`quote_verified: bool\|None`（`schema.py:385`）、`keyword_hit() -> bool\|None`（`providers.py:442`）、provider probe `probed_ok/probed_fail/unverified`（`search_tools.py:272,285,294,302,328,343`）、`evidence_for.checked`（`13-...md:578`） | **我们更强，无需改**。dsh 的 `blocked`/`not_found`/`partial` 全塞进自由文本 `error`（`:1101-1116`），机器读不出来 |
| Danus 的"verifier 说 `correct` 才是 fact"（二值闸门） | `danus-prompt.mjs:40` | E 的三级 `proof/cross_check/heuristic`（`schema.py:633`）+ 计算类永远拿不到 proof（`schema.py:757-762`）+ FC-22（`13-...md:701` 标"已落地（最强）"） | **我们更强**。dsh 自己也标了闸门边界（`danus-prompt.mjs:59` "Verifier = strong LLM, **NOT formal proof**"） |
| "撤回必须级联；没有 revoke 动作就把撤回面向上暴露" | `danus-prompt.mjs:59` | `verify.py:487-558` **已经照它做了**：`citation_to_retracted_relation`=error、`question_based_on_retracted_relation`=warning、`suspect` 降为 warning（FC-13，`13-...md:692`） | **已经取用过了**——代码注释原文写着"来自对本地先例 Danus 的观摩" |
| "先持久化 started，再干长活，崩溃不重放" | `global-deadline.mjs:167-192` | 设计草案 `:179`「写实体先于翻状态位（先写 relations 再置 `processed`）」；LESSONS P5/P6（`test2\LESSONS.md:207,215`） | **同一条原则，已覆盖** |
| `ps`（进程真相）vs `status`（心跳）："当 status 说在跑但毫无进展时去看进程" | `danus-prompt.mjs:46` | `tests\test_agent_e.py:184`「即使脚本**已经打印了** supports，也不能被采信：**exit_code 优先**」；LESSONS P13 恒值计数器（`test2\LESSONS.md:271`） | **已覆盖，且我们已有实测断言** |
| 本地确定性缓存键：`store` 一次后 `fulltext` 永不重下 | `paper.mjs:500-527`、`:1043`、`:1249` | `dedup.py:6` 三级硬键 + `dedup_key_of`（`providers.py:466`）+ `_merge_candidates` 只填空不覆盖（`providers.py:1688`） | **已覆盖**（**未核实**：下载的 PDF 本体是否也有确定性缓存路径） |
| 提示段按 `order` 装配（persona 0 → 协作 20 → 工具 21/22/23 → 截止 25） | `agent.cordis.yml` 各行 | —— | **不需要**：这是 dsh 宿主机制，不是研究方法论 |
| 插件定时推 notice 唤醒主进程，代替 LLM 轮询 | `danus-console.mjs:497-534`、`global-deadline.mjs:60-75` | 我们的角色由主循环驱动，没有"等时间"的 LLM 轮询 | **不需要** |
| DeepMath 的 `pessimistic_verify` fail-closed 默认 | `verification_tools.py:385-395` | `tests\test_agent_e.py:184` + `agent_e.py:559-567` + FC-01 | **已覆盖**（见 7.11） |
| DeepMath 的"声明哈希去重" | `research_workflow.py:1178` | `claim_key` 去重（`schema.py:715`、I11 按 `claim_key` 去重，`13-...md:541`） | **已覆盖** |

---

## 8. 不该学的 / 不适用的

| # | 不学什么 | 具体理由（带证据） |
|---|---|---|
| 1 | **把方法论写成 persona 提示词、不落成 schema 与判据** | dsh preset 的"Three Iron Rules""R→R→T→P""6 角色评审"全是提示词纪律（`agent.cordis.yml:87-127`），**没有一条可机械校验**——文件里没有任何 schema、没有任何 validate、没有任何测试。我们的 FC-01/04/08/09/18 之所以能标"已落地"，恰恰因为它们是 schema 里的 `raise` 和测试里的负控。**persona 的措辞可以抄，治理方式不能抄。** |
| 2 | **无法证伪的绝对条款**，如"Reconcile all comments, zero exceptions" | `agent.cordis.yml:124` 的"zero exceptions"没有任何判定方式（谁来数？漏了怎么发现？）。我们的 FC-26 要求"每个缺口/结论必须是可核实判据，不许感觉"（`test2\LESSONS.md:704`）。**抄它的顺序是好的**（fatal 先于 severe/moderate、改过的部分要重评审、大改动走完整流水线），**抄它的绝对性是坏的。** |
| 3 | **6 角色由同一个 LLM 在同一次会话里扮演** | `agent.cordis.yml:124` 的 A–F 六个视角是同一次生成里的角色切换：没有独立上下文、没有结构化产出、**不要求每条发现带证据**。我们的 H 是只读 + `evidence` 必填（`schema.py:1129-1133`，docstring `:1095-1101` 讲得很清楚："审校者的判断也需要证据…否则审校就会变成另一种幻觉的来源"）+ `FINDING_LEVELS` 三分档（`schema.py:693`）。**"6"这个数字不是重点，"独立 + 带证据 + 只读"才是。** 若要借鉴，借鉴的是"中心定理走全流程、中间引理走精简流程"这个**分级**（`:124`），而不是角色数量。 |
| 4 | **`paper.mjs` 那套 Google Scholar / Bing 抓取式"发现"** | `paper.mjs:696-953`：与 Cloudflare 斗智（`:703` `CLOUDFLARE_MARK`）、维护 30 分钟缓存 + 10 分钟冷却（`:709-710`），而且**它自己承认结果可能只是部分**（`:1107`）。我们的 A 走 `providers.py` 的正式 API + `RateLimiter`（`providers.py:65,68`），可复现、可测试。抓 HTML 会让"检索"退化成不可复现的爬虫，直接冲突 LESSONS P14「外部契约只能实测，不能推断」（`test2\LESSONS.md:279`）。**唯一值得抄的是 7.4 的闸门。** |
| 5 | **把 Danus 这类外部推理集群当成评审者** | `danus-prompt.mjs:24` 说得很清楚：Danus 的位置是"parallel workers **prove**, one stateless verifier gates every fact"——它是**执行与入库**，不是对论文做同行评审。`:30` 明确把 "decomposition / synthesis / **final judgment** / **load-bearing review**" 留给主进程。我们的 G↔H 是同构的撰写-审校回路（I8，`13-...md:504`），引入外部 LLM 集群只会增加一个不可控的把关者。**值得借鉴的只有"把 gate 的边界写明"这一条诚实性**（`danus-prompt.mjs:59`）。 |
| 6 | **照搬 DeepMath 的 `ACTIVITY_SPECS` 式活动常量表** | `<D>moonshine\agent_runtime\research_workflow.py:94-219` 把 14 个节点的 `stage/label/goal/skills/tools/good_outputs` 写成代码常量。我们的流程由 **12 张表 + I1–I12 契约**承载，节点语义在 schema 里。再抄一份节点常量表，就制造了"两处定义同一件事"的分叉风险——正是 **FC-03**（跨模块字符串必须集中定义 + 装配期断言，已落地）与 **FC-11**（校验器与写入方共享同一配置来源）要防的东西。**值得学的是它的"转移硬护栏"，不是它的活动表。** |
| 7 | **照搬它的测试规模与 CI 时长** | `moonshine\tests\test_architecture.py` 有 **8493 行**，CI `timeout-minutes: 5/10`（`offline-runner-tests.yml:13`、`moonshine-integration-tests.yml:28`）。规模是它们多轮迭代的**结果**，不是设计原则；照抄会让我们为了维护测试而维护测试。**值得学的是它"每个硬护栏都有一条断言"的比例**（如 `test_architecture.py:2834` 锁死质量门），不是行数。 |
| 8 | **DeepMath 的引文处理** | `<D>deepmath-ci\skills\verify-math-object-origin-archive\SKILL.md:26` 明确写「citations or a separate evidence note **are not acceptance requirements**」；全仓库没有引文逐字回验的硬规则，`citation_issues` 只是一个会被评审员"可能提出"的 schema 字段（`verification_tools.py:31`）。我们的 B 做逐字回验 + 三态计数（`schema.py:385`）是**明显更强的一层，绝不能向它退化。** |
| 9 | **DeepMath 的 `LangGraphCheckpointAdapter`** | `research_workflow.py:818-868` 装了 langgraph 却只用一个名为 `checkpoint` 的节点（`:830-834`）——一个**装饰性依赖**，真正的控制在 `_resolve_next_stage_and_activity`。引入一个只为"看起来像有图"的重依赖，与我们"确定性部分绝不交给 LLM"（FC-16，已落地）和无谓依赖最小化的取向相反。 |
| 10 | **dsh 的"LLM 自己调 `deadline arm`"这一触发方式** | `global-deadline.mjs:249` 把"记住设定截止"交给模型。模型忘了就没有截止，且**没有任何地方会因此报错**。我们的取向是"预算写不进表就抛"（`schema.py:866-877`）。**要它的跨层覆盖面，不要它的触发方式**（见 7.6）。 |

---

## 9. 一句话总结

dsh「数学模式」是一份**写得极好的提示词 + 一批设计精巧的外部工具**，但它的"研究框架"没有任何机械约束——真正能搬走的是它的**具体机制**（计算结果的证书与独立复现、预注册反驳判据、模糊匹配拒绝给答案、检索失败四态、跨层墙钟截止的形状、边界写进工具描述）和它那批**反静默的诚实条款**；DeepMath 才是**真有状态机与硬护栏**的那一个，它最值得学的是"**LLM 说完成不算完成**"（完成需要两把钥匙、未过质量门就强制退回、修不好就升级）以及**问题质量门（加权评分 + 阈值 + 强制退回）——这一块我们结构上确实缺**；而两处先例在三件事上都**弱于我们**：引文逐字回验、证据分级、以及"没做 vs 做了没结果"的三态区分——这三条我们已经做得更强，**不要向它们退化**。

---

## 附：本报告的核实边界

**已在代码/文件中核实的**：本报告正文中所有 `/path:行号` 引用（dsh 侧 9 个文件、`test1` 侧 `schema.py`/`agent_e.py`/`agent_f.py`/`verifiers`、`test2\LESSONS.md`、`draft\13-...md`、`<D>moonshine\`、`<D>deepmath-ci\`）。

**明确标注"未核实"的**：
1. **`R→R→T→P` 的首字母展开**：文件从未显式写出映射，我的 R=Research / R=Record / T=Think / P=Plan 是据 `agent.cordis.yml:95` 的四个段落标签推断。
2. **我们是否存在"自由文本标题/概念名 → 文献/概念"的模糊绑定点**（7.4 的前提）。
3. **下载的 PDF 本体是否已有确定性缓存路径**（7.12 末行）。
4. **A 是否已有"非正式来源不可引用"的标记位**：未找到 `citable` 字段；同时我们的 provider 全是正式源（OpenAlex / Crossref / DOAJ / Europe PMC），所以**目前无需求**，不列为建议。
5. `<D>deepmath-dataset\DeepMath-Creative` 与 `DeepMath-generator`：**未打开**，本报告对它们零结论。
6. `<D>moonshine\agent_runtime\research_workflow.py` 的 `LangGraphCheckpointAdapter` 是否在运行时真的启用 langgraph：只核到"只有一个 checkpoint 节点"与 backend 标签，**是否被调用未核实**。
7. `<D>mathematical-concept-agent\README.md:8-12` 关于"控制器是薄的"的叙述：**据文档，未在代码中核实**（命令 `agent.py:902/1050/1151/1117` 已核实存在）。
8. `<D>moonshine\assets\agents\builtin\agent-neural-network-functions\AGENT.md` 正文、`OPEN MATHEMATICAL PROBLEMS\`、`Neural Jacobian Conjecture\` 内容：**未核实**。
9. `QUALITY_GATE_AGENT_SLUGS` 里的 `neural-network-functions-researcher`：本 clone 中**没有**对应的 builtin AGENT.md，**未核实**是否运行时生成。
10. DeepMath 是否有数值型研究质量基准或 USD 预算：**未核实**（未找到）。
11. 我们的 `interactions.py` 契约**没有版本号**（只查到一个文献层的 `SCHEMA_VERSION = 1`，`schema.py:18`）；"冻结"是靠 `assert_store_free` 的 import 期签名断言实现的（`interactions.py:1166`、`:1198`），**未找到 contract version 整数**。

**只读承诺**：本次观摩未修改 `<P>`（`C:\Users\ysc20\.dsh\.agent-presets\math-research\`）与 `<D>`（`D:\Incubator\temp\deepmath\`）中的任何文件；未运行任何代码、测试、子进程或网络/LLM 调用。过程笔记：dsh 侧的证据即本报告 §1–§5 正文（未另存文件）；`test1`/设计草案侧与 DeepMath 侧的原始清点分别落在 `D:\Incubator\temp\our-framework-notes.md` 与 `D:\Incubator\temp\deepmath-notes.md`。
