# 用户端的设计基线：跟 DSH（DeepSeek Harness）学什么、抄什么、怎么微调

> 这一份是**设计依据**，不是使用说明。它把"用户端应该长什么样、为什么"钉在
> **可复核的出处**上：DSH 装在本机 `%APPDATA%\npm\node_modules\@deepseek-ai\dsh`
> （版本 `0.1.5-rc.2`，**MIT 许可**，见各包 `LICENSE`），下面的每条规则都能在
> 那个目录里读到原文；我们**照搬**的部分在文件头注明来源与许可。
>
> 用户 2026-10-03 的裁定："用户端好好学习 deepseek harness 的设计风格，我很喜欢……甚至允许你复制人家的代码微调。"

## §1 抄了什么（落地位置与来源）

| 我们这边的文件 | 来源（DSH 包内路径） | 抄的形态 |
|---|---|---|
| `src/agentflow/web/theme.css` | `dsh-client-ui-theme/lib/client.js` 内联的 `design-platform.css.mjs` + `base.css.mjs` + `scrollbar.css.mjs` | 令牌**整份照搬**（两层色板 + 明暗两套 + 运动/字体），只把选择器从 `body` 改成 `:root, [data-ds-dark-theme]` |
| `src/agentflow/web/app.css` | 同上，外加 `dsh-client-ui-user-questions` / `dsh-client-ui-approval` 的取值习惯 | 我们自己的组件（卡片/行/徽标/按钮）**只用令牌**写，不写死颜色 |

`theme.css` 里逐字保留 DSH 的令牌名（`--dsw-*` / `--ds-*`）**是有意的**：
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

DSH 的色板是**两层**的，这是我们最该学的一条结构：

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
   `--ds-font-family-code` —— 与 DSH 里工具输出/代码块的做法一致。
4. **圆角是一个签名**：`corner-shape.css.mjs` 在 `@supports (corner-shape:superellipse(1.5))`
   里把 `--dsw-corner-shape` 设成 `superellipse(1.5)`，并对所有元素生效 —— 支持这个
   属性的浏览器上圆角是"超椭圆"，不支持就退回普通圆角。照搬，因为它零成本、且一眼可辨。

## §3 交互规则（从 DSH 的 README 与包契约里提炼，逐条带出处）

### 3.1 提问（`dsh-tool-ask-user/README.zh.md`）

- **形状**：`{"questions": [{"id", "question", "header", "options": [{"label", "description"}], "multiSelect"?}]}`
  —— 稳定 `id`（回答里原样带回）、短标题 `header`、选项是 `{label, description}` 而不是裸字符串；
- **推荐的选项放首位，并在 label 末尾写 `(Recommended)`**（原文："推荐选项放在首位，
  并在标签末尾追加 `(Recommended)`"）—— 推荐是一个**可读的事实**，不是默认选中的状态；
- **回答形状**：`{"answers": [{"id", "selected": ["<label>"], "custom": "<text>"}]}`
  —— `selected` 可以 0/1/n 个；`custom` 对多选是**补充**、对单选是**覆盖**；不用就省略；
- **阻塞语义**：调用**阻塞到用户作答**，"只能通过当前轮次的信号取消"；**不声明 timeout 预算**；
  "等待用户时不会产生 token 开销"（这条对我们很重要：停着 = 不烧钱）；
- **失败不许降级**：没有 answerer 接受时，"工具调用会以错误失败，而不是降级"；
- **子 agent 不许直接问用户**（`DELEGATED_CALLER`）：归属另一个 agent 的存活子级被拒，
  "必须在最终结果中包含尚未解决的问题或决定"。

### 3.2 审批（`dsh-user-approval/README.zh.md`）

- 结果词汇是**一次性的**：`allowed-once` / 拒绝 / 取消 / 不可用；**没有 "allow always"**、
  没有记住的规则、没有撤销与授权存储；会话策略只有 `ask` / `never`；
- `never` 是**确定性拒绝**（"在交互式分发之前确定性地拒绝每个请求"）——这是 CI 与无人值守的姿态；
- **fail closed**：应答者缺失/抛异常/返回不合词汇 ⇒ `unavailable` ⇒ 以拒绝方式关闭；
  "服务自身绝不会提示人类"；
- **审计成对**：先追加 `approval/asked`、再追加 `approval/decided`，且必须在同一个未结束的轮次内；
- 中止 = **撤回问题**：请求以 `cancelled` 结算，**迟到的回答被丢弃**。

### 3.3 界面（`dsh-client-ui-cordis/README.zh.md`、`dsh-client-ui-user-questions/README.zh.md`）

- **状态不进组件 state**："两者都不把运行态放进组件 state"，事实活在"谁能关闭它、就归谁"
  的观察量里。⇒ 我们的页面**只做投影**：每次渲染都从盘上（会话事件、台账、报告）派生；
- **待回答的东西必须是全局可达的**：面板做成全局，"因为 run 请求会阻塞模型、且可能点名一个
  当前没人在看的会话里的定义；审批入口若只存在于那个会话的对话流里，就会在它正阻塞模型的
  时候恰好不可达"。⇒ 我们要一个**全局待回答面板**，不按会话过滤；
- **卡片渲染已落盘的 call/result 切片**，所以"replay 显示同一张卡"；行里给**两个独立事实**
  （host 在跑什么 / 这一页装载了什么），不许折成一个；
- 公告触发**重读清单**而不是就地打补丁（"公告不携带标签，而定义可能在两次公告之间出现或消失"）；
- 提问界面本身：翻页器在问题之间导航、单选选中即前进、`Enter` 继续（提交需全部已回答或跳过）、
  `Shift+Enter` 换行、IME 组合期间 `Enter` 只确认候选；**「跳过此问题」发出空 `{selected: []}`**、
  **关闭以 `ASK_CANCELLED` 拒绝整个等待**；长内容用限高卡片 + 内部滚动，标题/导航/提交固定。

## §4 我们与 DSH 的三处刻意差异

1. **持久化**：DSH 的草稿只活在页面生命周期里（"从不把草稿写入主机、`localStorage` 或磁盘"）；
   我们的会话记录是 **append-only 的审计面** —— 问题与回答都落盘（`user_question` /
   `user_answer`），因为我们的判据要读它（`triage_branch_recorded` / `user_pending`）。
   于是"迟到的回答"我们**保留**（DSH 丢弃）：保留不等于生效，它只在下一次运行被读到。
2. **读数词表**：DSH 是 `allowed-once/denied/cancelled/unavailable`；我们是三态
   `pass/fail/unknown` 加一档"停在等待用户"（`waiting_for_user`）。
3. **语言**：界面与提示词以中文为主（DSH 的编辑器外壳文案是 zh/en 双语的，
   问题与选项文本"来自模型并原样渲染"——我们照这条：用户的输入原样显示，不做二次加工）。
