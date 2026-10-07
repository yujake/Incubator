# 用户端设计依据：抄 DSH 的**皮**，协作纪律用**我们自己的**

> 用户 2026-10-03 的两条裁定，这一份按它们划界：
>
> 1. "用户端好好学习 deepseek harness 的设计风格，我很喜欢……甚至允许你复制人家的代码微调。"
>    ⇒ 视觉与界面形态可以照搬（DSH 是 **MIT**，见 §1.1）。
> 2. "我们的协作纪律和 DSH 是有不同的，我叫你抄 DSH 的 GUI 又没叫你全抄它的协作纪律。"
>    ⇒ **协作纪律一律以我们自己的文件为准**（§4），DSH 的提问/审批纪律降级成参考读物（§5）。
>
> 还有一条界线（用户 2026-10-03 当场纠正的）：**开发时纪律**（我们改这个仓库时的纪律：
> FC-27、三态退出码、提示词优先、活先落 board、目标变更先问、登记 + 提交）**不是**运行时
> 协作纪律（智能体之间怎么协作）。两者混在一起写，会让人拿"我们改代码的规矩"去解释
> "智能体该怎么说话" —— 这一份把它们分在两节：§4 是运行时，§6 是开发时。

---

## §1 抄了什么（只有"皮"）

| 我们这边的文件 | 来源（DSH 包内路径） | 抄的形态 |
|---|---|---|
| `src/agentflow/web/assets.py` 的令牌层 | `dsh-client-ui-theme/lib/client.js` 内联的 `design-platform.css.mjs` + `base.css.mjs` + `scrollbar.css.mjs` | 令牌**整份照搬**（两层色板 + 明暗两套 + 运动/字体），只把选择器 `body` / `body[data-ds-dark-theme]` 改成 `:root` / `:root[data-ds-dark-theme]` |
| `src/agentflow/web/assets.py` 的组件层 | 同上，外加 `dsh-client-ui-user-questions` / `dsh-client-ui-approval` 的取值习惯 | 我们自己的组件（卡片/行/徽标/按钮）**只用令牌**写，不写死颜色 |
| `src/agentflow/webui/` 的界面纪律（2026-10-07 拆包前是 `webui.py`，见 `draft/73` §1.2） | `dsh-client-ui-cordis` / `dsh-client-ui-user-questions` 的 README | 三条：状态不进组件 state、待答面板全局可达、卡片渲染已落盘的 call/result 切片（§3） |

`assets.py` 里逐字保留 DSH 的令牌名（`--dsw-*` / `--ds-*`）**是有意的**：
名字一改，将来 DSH 更新令牌时我们就得靠肉眼比对；名字保留，升级就只是替换文件。

### §1.1 许可（照搬代码的前提，已核实）

DSH 各包是 **MIT**，逐字为（读的是 `dsh-client-ui-theme/LICENSE` 与
`dsh-tool-ask-user/LICENSE`，两份相同）：

```text
MIT License

Copyright (c) 2026 DeepSeek
```

照搬的文件头必须留下这段声明**加来源路径**（例如
`来源：@deepseek-ai/dsh 0.1.5-rc.2 → packages/client/ui-theme/src/styles/design-platform.css.mjs`），
并写明"本文件是照搬 + 选择性微调（列出改了哪几处）"。这一条不是形式主义：
MIT 只要求保留版权与许可声明，**丢了它就等于把一段有主的代码写成自己的**。

## §2 令牌体系（两层 + 明暗两套）

DSH 的色板是**两层**的，这是我们最该抄的一条结构：

1. **原始色板** `--dsw-static-<色>-<档>`：`neutral / neutral-bluish / deepseek / blue /
   amber / green / red`，档位 `00…1000`（如 `--dsw-static-neutral-bluish-900:#1b1b1c`）。
   这一层**只描述颜色本身**，不含用途。
2. **语义别名** `--dsw-alias-*`：79 条，按用途分组 —— `bg-*`（`base` / `layer-1..3` /
   `overlay` / `mask-1..3` / `module-platform` / `multi-select` / `skeleton`）、
   `border-*`（`l1..l4` / `inverted`）、`label-*`（`primary` / `secondary` / `tertiary` /
   `caption` / `dimmed` / `link` / `brand-text` / `primary-foreground` / `inverted`）、
   `button-*`（`primary` / `ghost` / `elevated` / `floating` / `info` / `tool-bar` 各自带
   `hover` / `active` / `dimmed`）、`interactive-*`（`bg-hover` / `bg-active` /
   `bg-hover-accent` / `bg-hover-danger`）、`state-*`（`success` / `warn` / `error` /
   `business` 各带 `primary` / `secondary` / `tertiary` / `label`）、`markdown-*`、
   `scrollbar-*`、`toast-bg`。

组件**只准用第二层**。这是"换皮只换一层"的前提：我们那套三态读数
（`pass` / `fail` / `unknown`）正好落到 `state-success-*` / `state-error-*` /
`state-warn-*` 三组别名上，语义与颜色一一对应，不需要在组件里写任何色值。

3. **运动与排印**（`base.css.mjs`，整份只有一行）：`--ds-ease-in-out:cubic-bezier(.4,0,.2,1)`、
   `--ds-transition-duration:.2s`（`-fast:.1s` / `-slow:.3s`）、`--dsw-font-family`
   （系统字体栈，含 `PingFang SC` / `Microsoft YaHei`）、`--ds-font-family-code`
   （`SF Mono` / `JetBrains Mono` / `Consolas`…）。我们的读数、id、路径一律用
   `--ds-font-family-code`。
4. **圆角是一个签名**：`corner-shape.css.mjs` 在 `@supports (corner-shape:superellipse(1.5))`
   里把 `--dsw-corner-shape` 设成 `superellipse(1.5)`，并对所有元素生效 —— 支持这个
   属性的浏览器上圆角是"超椭圆"，不支持就退回普通圆角。照搬，因为它零成本、且一眼可辨。

## §3 界面纪律（抄的"皮"的另一半）

- **状态不进组件 state**（`dsh-client-ui-cordis`）：事实活在"谁能关闭它、就归谁"的
  观察量里。⇒ 我们的页面**只做投影**：每次请求都从盘上（会话事件、台账、报告）派生，
  读一次快照抽成纯函数 `snapshot()`，同一份数据渲染两次逐字节相同（判据
  `tests/test_webui.py::test_rendering_is_a_projection_not_a_cache`）。
- **卡片渲染已落盘的 call/result 切片**（`dsh-client-ui-user-questions`）⇒ 运行详情页
  回放会话里的事件，不另存一份展示用的副本。
- **行里给两个独立事实**（同上）⇒ 运行态那一行同时给"盘上最后一条事件是什么"与
  "这一页读到了多少条事件"，不许折成一个。
- **待答面板全局可达** —— 这一条抄的是形态，而它在**我们自己的结构**里也必然成立：
  提问正阻塞着某一趟运行，而"用户只对主控说话"（`DESIGN-CONDUCTOR.md` §1.1）⇒
  人需要一个不挑会话的入口。判据
  `tests/test_webui.py::test_pending_list_is_never_filtered_by_session`。
- **接口形状**（用户在 2026-10-03 的裁定里点名的口径，字段名与 DSH 一致）：
  问题 `{id, question, header, options:[{label, description}], multiSelect}`、
  回答 `{id, selected:[…], custom:"…"}`；推荐项放首位、label 末尾写 `(Recommended)`
  ——推荐是一个**可读的事实**，不是默认选中的状态。实现见 `userio.Option` / `Question`。

## §3.1 六个页面各自读什么（2026-10-07 W1 落地）

六个客户端路由对应六页（`ui/src/pages/*.tsx`），**每一页每一个栏位都能指到盘上的一行真数据**。
这张表就是那份对照（后端出处与逐栏字段的完整矩阵在 `../draft/74-前端×后端配合矩阵（按前端文件）.md` §3，
这里给的是"读哪条端点、读哪几栏、空态与三态怎么办"）：

| 路由 | 页面 | 端点（`ui/src/api.ts` 的 `ENDPOINTS`） | 读的栏位（后端键逐字） | 空态（"读到了，里面是 0"） | 三态落点 |
|---|---|---|---|---|---|
| `/` | `Home.tsx` | `GET /api/state` | `pending_questions`（**全局，不按会话过滤**）· `sessions`（`events_seen`/`bad_lines`/`last_kind`/`pending`/`runs`/`orphans`）· `problems` · `ledger.events`/`tables`/`tables_note` · `runs[].waiting_on` | "没有待回答的问题（合法初态，不是「没查成」）" | `problems` 非空 ⇒ 顶部横幅显红；`bad_lines > 0` ⇒ 行内徽标 |
| `/run/:sid` | `Run.tsx` | `GET /api/run/{sid}` + `GET /api/run-index` | `runs[]`（`steps`/`llm_calls`/`usd`/`unknown_usd`/`last_shape`/`stop_reason`/`waiting_on`/`events_in_run`）· `report`（`ok`/`missing`/`unknown`）· `checkpoint.spend`（首选花销）· `drift`/`usable`/`tri`（趟次索引对账）· `orphans`/`orphan_summary` | "这一段会话里一趟都没有" + "没有轮次之外的零散事件" | 索引 `tri != computed` ⇒ 显红并说明"本页回退现算"；两个花销来源都读到才谈"是否一致"，任一边没读到 ⇒ "没查成"；交付说明走 `ReportTri` 那一套词 |
| `/evidence` | `Evidence.tsx` | `GET /api/evidence` | `statements` · `conjectures`（含 `counterexample_experiment_id`）· `experiments` · `review_findings` · `relations.quote_verified`（真/假/未查三个数）· `verifications` · `secretary` | 每一栏各自的 `<栏>_tri == computed` 且 0 行 ⇒ "0 条（读到了，里面是空的）" | **逐栏**读 `<栏>_tri`（整面一个词会吞掉"哪一栏没读成"）；`quote_verified !== true` 必须连 `quote_reason` 一起看 |
| `/artifacts` | `Artifacts.tsx` | `GET /api/artifacts` | `ledger` · `ledger_verify`（台账钉的 sha vs 盘上现在这一版）· `handoffs`（`body` 按 `CLIP=400` 截断）· `checks` · `style.sections` · `secretary` · `products`（六件，裁定 J2 的夹具样本）· `tasks` | 逐栏："台账 0 行（读到了，里面是空的）" | 逐栏 `<栏>_tri`；`products_tri == not_applicable` ⇒ "这一路本机还没跑过"，不是"六件都不在" |
| `/acceptance` | `Acceptance.tsx` | `GET /api/acceptance`（`?project_dir=` `?report_path=` `?cap_usd=`） | `criteria`（5 条，值 `pass`/`fail`/`unknown`）· `details` · `auxiliary`（5 条）· `failed` · `auxiliary_note` | "一条判据都没读到"（判据名表来自 `reviewaccept.CRITERIA`，页面不另抄） | `unknown` 显成"没查成（不是通过）"；**不给 `cap_usd` ⇒「在成本上限内」那一格必为 `unknown`** |
| `/machine` | `Machine.tsx` | `GET /api/machine` | `provers`（含 `checked` 与 `sources` —— "从哪一档找到的"）· `mathlib` · `lean_ready`/`can_do_formal` · `settings.path`/`exists`/三段 · `settings.model.configured`（**永无 key 值**） | "探测读数里一格都没有" | `provers.checked=false` ⇒ 整面 `unreadable`（探测没跑完 ≠ 一个都没找到）；`lean_ready`/`can_do_formal` 的 `null` 显 `unknown`，不折成 `false` |

**两套三态词表在组件层合流、在字符串层不通用**（裁定 N1）：`types.ts` 的
`Tri`（`computed` / `unreadable` / `not_applicable`）与 `ReportTri`（`ok` / `missing` / `unknown`）
都投影到 `components/TriState.tsx` 的三种视觉态（`ok` / `unknown` / `na`），映射只有那一处
（`visualOf()`）；页面里不许把一个词表的值当另一个用。

**五处如实标注的缺口（页面显 `not_applicable` + 原因，不编数）**：`draft/74 §3` 的矩阵里有五栏
写的输入在今天的后端**不存在** —— 停机状态（`GET /api/state` 的 `stop`）与检索腿
（`search_requests` 汇总）都在 `snapshot()` 被公开面对账钉住的 10 个顶层键之外；文献库
（`library`）不在 `ArtifactsView` 里；"与工具面同源"（`conductor.closing` 的 `review_acceptance` 子树）
与"污染面"不在 `AcceptanceView` 里。它们要各加一条只读端点才能给读数 —— 本批没有加，
页面把这件事写在卡片上，而不是显示一个 0。

## §4 我们的**运行时**协作纪律（与 DSH 无关，出处全是本项目）

这一节才是"智能体之间怎么协作"。用户端（人机通道 + 网页）落在它的第 6 条上。

1. **用户只对主控说话**：`DESIGN-CONDUCTOR.md` §1.1 逐字"它是用户唯一面对的东西"——
   用户说"帮我复现这篇论文"，主控负责理解 → 拆解 → 召唤 → 汇总 → 报告。
2. **主控的产出只有两类**：召唤与"给用户的汇总"。它不产出知识、不写关系、不改稿件；
   它的"正确性" = 发出的召唤序列是否满足策略与预算（同节）。
3. **主控在策略之内、且不可被召唤**：`capabilities.NON_SUMMONABLE = {"M"}`
   ⇒ 主控永远是顶层入口；`ALLOWED_EDGES` 里 `M → A–H` 全部、`A→B`、`B→C`、
   `D→{E,C,B,F,A}`、`E→{B,D}`、`F→{C,E,D,B,A}`、`G→{F,A,E,D}`、`H→{G,A,E}`。
4. **A–H 对召唤者负责**：被动（主控召唤）或同伴召唤，受三条约束 —— 边必须被策略允许、
   深度有限（默认 3）、同一 `(role, action, input_key)` 不得在祖先链上重复（§1.2）。
5. **并发是策略、不是常量**；可并发的判据是"会不会写同一张表的同一批行"（§1.3）；
   写集由 `capabilities.WRITE_SETS` 定义，只读角色（C/H）拿不到写工具。
6. **人机通道归主控**（由 1 与 3 推出，不是抄来的）：只有 `schema.CONDUCTOR_ROLE`
   可以当面问人；A–H 把未决问题写进自己的结果交回召唤者。落点
   `agent_loop._do_ask_user`（`role != CONDUCTOR_ROLE` ⇒ `not_conductor`），
   判据 `tests/test_user_channel_stop_and_resume.py::test_only_the_conductor_may_ask_the_user`。
   人工直接驱动单个角色（`agentflow run-agent D`）是**运维/测试**路径，不是用户通道。
7. **交互契约**（`DESIGN-INTERACTIONS.md`）：I2 矛盾闭环、I6 写入期一致性闸门
   （B 提交关系前问 C）、I7 检索配额；闸门在事务内、签名里不许带 `store`（冻结契约，
   `interactions.py` 是实现面）。每个新交互都要有**可判定的**验收（§4）。
8. **所有"空"必须三态**（§3.4）：没查 ≠ 没有 ≠ 通过。人机通道上的落点是
   `pending`（还停在等）/ `refused`（没人在场）/ `cancelled`（这一趟被叫停）三态分开，
   加上"问题没落档"那一档 —— 四档不许折成两档。
9. **证据等级纪律**（`DESIGN-ROLES.md` §1，FC-22）：E 的计算类方法**永远**拿不到 proof
   等级；F 的子目标只有拿到 proof 才允许 `closed`；G 的 `cross_check` 必须自带
   "不构成证明"。

## §5 参考读物：DSH 的提问与审批纪律（**不构成我们的规则**）

下面是照抄 GUI 时读到的原文，留在这里是为了"将来要查出处时有地方查"。
**它们不是我们的规则**：与 §4 冲突时以 §4 为准；我们也没有审批通道（`DESIGN.md:497`
把"审批与人机协同"登记为未做）。

- 提问（`dsh-tool-ask-user/README.zh.md`）：选项是 `{label, description}`、推荐项首位 +
  `(Recommended)`、回答 `{id, selected, custom}`（`custom` 对多选是补充、对单选是覆盖）、
  调用**阻塞到作答**且不声明 timeout 预算、等待期不产生 token 开销。
- 审批（`dsh-user-approval/README.zh.md`）：结果词汇一次性（`allowed-once` / 拒绝 / 取消 /
  不可用）、没有 "allow always"、会话策略 `ask` / `never`、`never` 是确定性拒绝、
  应答者缺失即 fail-closed、审计成对（`approval/asked` → `approval/decided`）、
  中止 = 撤回问题、迟到的回答被丢弃。
- 子 agent（同上）：归属另一个 agent 的存活子级**不许**直接问用户
  （`DELEGATED_CALLER`）。我们**不用**这条作依据 —— 我们的第 6 条是从 §1.1 与
  `NON_SUMMONABLE` 推出来的，两者结论相同、出处不同（这一点是有意的：
  依据必须是我们的）。

## §6 我们的**开发时**纪律（不是协作纪律；改这个仓库时才适用）

这一节写给"要改这份交付物的人"，与"智能体之间怎么协作"无关（用户 2026-10-03 的纠正）。
完整版在 `AGENTS.md` 与 `DEVELOPMENT.md`，这里只列与用户端改动直接相关的那几条：

- **FC-27 禁改区**：命中 ⇒ 停，由人编写或人逐行走查 + 2 名 reviewer；门是机器执行的
  （`python scripts/noai_gate.py --git`，退出码 0/1/2）；
- **三态退出码**：`0` 收工 / `1` 失败 / `2` 没查成；`unknown` 绝不是 `clean`；
- **判据优先**：动行为就补判据（含负控），判据红了先怀疑自己的工具；
- **提示词优先**：动作表尽量不动；
- **活先落 board**、**目标变更必须问用户**；
- **每轮四读数 + 登记**：lint / 全量 pytest / FC-27 门 + 登记 `draft/37` §NNN 后提交。

## §7 我们与 DSH 的三处刻意差异

1. **持久化**：DSH 的草稿只活在页面生命周期里（"从不把草稿写入主机、`localStorage` 或磁盘"）；
   我们的会话记录是 **append-only 的审计面** —— 问题与回答都落盘（`user_question` /
   `user_answer`），因为我们的判据要读它（`triage_branch_recorded` / `user_pending`）。
   于是"迟到的回答"我们**保留**（DSH 丢弃）：保留不等于生效，它只在下一次运行被读到。
2. **读数词表**：DSH 是 `allowed-once/denied/cancelled/unavailable`；我们是三态
   `pass/fail/unknown` 加一档"停在等待用户"（`waiting_for_user`）。
3. **语言**：界面与提示词以中文为主（用户的输入原样显示，不做二次加工）。
