# PRESET-RETIREMENT —— 预设（presets）为什么曾经存在、为什么退役

> 一句话：**这一段说的是"一段写死的提示词正文该住在哪"**。
> 2026-11-22 之前答案是"随包预设目录"，之后是"角色声明文件 `specs/<role>.py`"。
> 本文记的是那条搬家的理由与留下的教训 —— 退役的是机制，不是那段正文。

## 一、两根轴：写死的正文 vs 运行时值

同一棵树里有两个"配置"，很容易问"明明有 settings 为啥还有过 presets"。判据只有一句：
**写死的提示词正文归代码与声明文件；运行时值归 settings。**

| 你要改的是 | 放哪 | 谁读 | 什么时候生效 |
|---|---|---|---|
| 提示词的**正文**（人设、做法、检索式教法、证据契约里写死的那一段） | `src/agentflow/specs/<role>.py`（职责 / 边界 / policy / `SEARCH_STYLE` 一类模块级常量）或 `agent_prompts.py` 里那段写死的常量 | `agent_prompts.role_prompt_registry` 装配时 | 下一次装配 |
| 这台机器 / 这个工作区的**运行时值**（lean 路径、模型 key、projects 目录、阈值、开关） | `settings.json`（机器级）/ `config.yaml`（工作区级） | `settings.py` / `cli.load_config` / 各角色构造 | 下一次调用现读（lean 开关连缓存都没有，见 `leanscope.py`） |

两条边界：

1. **只有写死的正文能进声明面。** 工具清单 / 官能 / 证据字面 / 伙伴 / 任务框 / 事实是
   **现算的块**，由代码按注册表与当次事实给。把它们搬进一份数据文件，等于允许"文件与
   事实各说一套"（`draft/103` §4.1b 的原话）。
2. **settings 是运行时配置，而且 `settings.json` 是机器级的**（不进仓库、带模型 key）。
   两边的读者、生效时机、信任面都不同 ⇒ 不并成一棵树
   （完整迁移方案与代价见 `temp/presetmerge/REPORT.md`，那是当次提案）。

一条规则放哪边，自问两句：这句话是**写给模型的正文**吗（人设、做法、口径）→ 声明面；
这个值是**代码要读的参数**吗（路径、key、上限、开关）→ settings / config.yaml。

## 二、为什么曾经有预设

2026-10-11（`p68`，接线批 C1）把 A 的第一段写死正文搬进了
`presets/roles/a/blocks/search_style.md`（后来压平成 `presets/a/`），段名 `A_SEARCH_STYLE`。
那一层是 DSH 的 `dsh-agent-presets` 的移植：一个预设一个目录（`preset.yml` 显示两件 +
组装行 `assembly`）、随包根前置、坏预设列出来带理由、以"承载组装行那份文件的 mtime+size"
为生成戳、创作面只有复制。它回答的问题是"**写死的块由哪段文件给**"——
听起来像一条通用的部署面，实际上只有一个角色用得上。

## 三、为什么退役（2026-11-22，业主裁定）

业主逐字：

> **presets 那条为什么单独做 A 不做别人，这肯定是陈旧东西，整合进它该在的地方。**

取证坐实了这句话：随包预设只有 `a/` 一份（`preset.yml` + `blocks/search_style.md`），
而 B–H / V / L / M 的写死正文全部在 `specs/<role>.py` 里（`SPEC.brief` 的
duty / boundary / policy / stance，或 `b_ingest_policy.py` 一类同族常量）。
于是那套机制的**唯一效果**是"A 的一段正文住在数据文件里、与同族 policy 分家"：

- 发现 / 根优先级 / 三档 trust / 生成戳 / 复制式创作 / 旧双文件形状 —— 没有第二个用户；
- 组装行名解析表（`agentflow.text_blocks` / `agentflow.brief_blocks`）—— 前者只有 A 一份，
  后者从来没有过用户（"预留"）；
- 结论：这不是一条部署面，是一段正文的历史外挂。

## 四、搬到哪里去了

| 东西 | 现在住在哪 |
|---|---|
| A 的检索式教法正文 | `src/agentflow/specs/a.py::SEARCH_STYLE`（与 A 的 policy / boundary 同一份声明文件；`specs/` 是 FC-27 `auth-audit` 禁改区，改它需要人审） |
| 它进提示词的那一步 | `agent_prompts.role_prompt_registry`：只给 A 注册 `Section("A_SEARCH_STYLE", SECTION_ORDERS["A_SEARCH_STYLE"], SEARCH_STYLE)` |
| 段号（它排在哪） | `promptkit.SECTION_ORDERS["A_SEARCH_STYLE"] = 2000`（工具指引之后、证据契约之前）—— 位置仍然只有这一个来源 |
| 预设机制本体（发现 / 挂载 / 创作 / 行名解析 / `prompt_audit["preset"]`） | 退役（模块与数据目录都已删除） |

验收口径是**十一格渲染逐字节不变**：A 的正文、段名、段号、顺序四样原样，其余十个角色
一格不动。这一头由 `tests/test_agent_prompts.py` 的冻结摘要表守着；退役本身的四条正控
与一条反真空在 `tests/test_presets_retired.py`。

## 五、留下的教训（为什么记这一页而不是直接删掉）

1. **"机制"要为第二个用户存在。** 一套带发现、优先级、信任档、生成戳、复制式创作的
   机制，只有一个用户时，它付出的复杂度全部变成了"读的人要多查一处"。
2. **写死的正文要有唯一的家。** 同族的东西分开住（A 在数据文件、别人在 `specs/`）时，
   "改这一段该动哪个文件"就没有答案，而没有任何读数会红。
3. **退役要能算账。** 判据不是"删干净了"，而是"内容一个字节没丢、位置与顺序没动、
   十一格摘要不变"—— `temp/presetretire/` 里的 dump/compare 读数就是那本账。

## 邻居

- 段与号段：`src/agentflow/promptkit.py`（`SECTION_ORDERS`）
- 装配入口：`src/agentflow/agent_prompts.py`（`role_prompt_registry` / `prompt_audit`）
- A 的声明：`src/agentflow/specs/a.py`
- 版本账（提示词每抬一格在这里追加一段）：`docs/PROMPT-HISTORY.md`
