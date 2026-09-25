# 工具层 + 智能体 C/D —— 设计基线 (v0.2)

> 本文件是 `DESIGN.md`（A/B 基线）的**扩展**。凡与 `DESIGN.md` 冲突处，以 `DESIGN.md` 的既有结论为准
> （数据模型、并发模型、判重、引文校验都不变）；本文件只**新增**。

---

## 0. 本轮需求与"最低可用"的边界

需求原文两件事：

1. **工具化**：给 A/B 配齐"所有涉及文件"的增删改查工具；A 要有强大的文献检索工具，B 要有 OCR 工具。
   总原则：**把"根据给定信息完成标准操作"尽量用自动化脚本/工具实现，以不打扰智能体的思维链**。
   实现 C 时也要做工具。
2. **两个新智能体**：
   - **C（关系分析）**：接 B 的关系表，**用程序分析**，产出报告。四类需求：统计最热门概念 / 查询两概念间关系 / 研究冷门概念 / 完善关系图。
   - **D（研究）**：接 C 的报告做系统分析，按代号溯源到表述、按需溯源到文献内容，评估值得研究的问题并做初步研究；**知识不足就向 A 提交查询请求**，A 查完 B 立刻消化，B 消化完让 D 看，D 继续。产出较详细的初步研究报告。

**本轮边界**：框架先搭起来，功能"堪堪可用"。因此：
- 一切**能确定性做到**的（计数、图搜索、编号溯源、索引、CRUD、OCR 调度）都必须用程序实现，**不交给 LLM**。
- 只在**真正需要语义判断**的地方（C 的"最合理关系链"排序的语义部分、D 的"值得研究的问题"）留出 **LLM 钩子**，
  并同时提供一个**确定性回退**，保证无 API key 也能端到端跑通、可测试。

---

## 1. 核心设计原则：为什么必须有"工具层"

原来的 A/B 直接调 `store` / `providers` 的函数。智能体一旦由 LLM 驱动，这就不够了：

| 问题 | 后果 |
|---|---|
| LLM 需要"手写 JSON 去改表" | 一次转义错误就写坏数据；且**每改一行都要占一轮思维链** |
| 没有统一的输入校验 | 参数错了要到深处才炸 |
| 没有统一的副作用声明 | 无法判断一个动作是否会改盘，也就无法决定要不要审批 |
| 无 LLM 时无法复用 | 同一套能力在"脚本模式"和"LLM 模式"下要写两遍 |

**工具层要解决的正是这四件事**：把"标准操作"固化成**有名字、有 schema、有校验、有结构化返回、声明副作用**的原子工具。
智能体的思维链只花在**判断该调哪个工具**上，不花在**怎么把参数拼对**上。

于是 `ToolSpec` 必须有：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                 # 唯一名，如 "table.create_row"
    summary: str              # 一句话（给 LLM 看）
    params: dict              # JSON Schema（object 根），用于校验 + 未来喂给 function-calling
    handler: Callable[..., Any]
    side_effect: str          # "none" | "write_local" | "network"  ← 决定是否需要审批
    roles: tuple[str, ...]    # 哪些智能体可以拿这个工具
    returns: str = ""         # 返回结构的人话说明
```

`side_effect` 是刻意设计的：`network` 与 `write_local` 的工具在无人值守场景需要审批，
`none` 的不需要。**把审批判断建立在声明上，而不是靠人工记忆。**

### 1.1 工具清单（本轮）

| 组 | 工具 | 角色 | 副作用 |
|---|---|---|---|
| 表 CRUD | `table.list` / `table.get` / `table.create` / `table.update` / `table.delete` / `table.count` / `table.schema` | A B C D | write_local |
| 文件 CRUD | `fs.list` / `fs.read` / `fs.write` / `fs.delete` / `fs.move` / `fs.stat` / `fs.search` | A B C D | write_local |
| 文献检索（A 专用） | `search.literature` / `search.download` / `search.dedup_check` / `search.providers` | A | network |
| OCR（B 专用） | `ocr.run` / `ocr.detect_text_layer` / `ocr.backends` | B | none |
| 图分析（C 专用） | `graph.build` / `graph.hottest` / `graph.paths` / `graph.cold` / `graph.gaps` | C | none |
| 溯源（D 专用） | `trace.relation` / `trace.concept` / `trace.literature` / `trace.quote` | C D | none |
| 研究（D 专用） | `research.submit_gap` / `research.list_gaps` / `research.write_note` | D | write_local / network |

**注意 `graph.*` 与 `trace.*` 都是 `side_effect="none"`（纯读）** —— C 的核心诉求是"用程序分析"，
它应当能**任意多次、任意组合**地查询，而不触发任何审批或写盘。这是把分析做成工具而不是做成 LLM 提示的关键收益。

---

## 2. 新增数据表

在 `DESIGN.md` §1 的四张表之外新增两张（同样 4 位 ID、同样受 `Store.tx` 保护）：

### 2.1 `data/research_questions.json`（D 的工作台）

```jsonc
{
  "question_id": "0000",
  "question": "阿贝尔群与域之间的交换性条件是否可推广到非交换环？",
  "origin": "C:paths:0000->0003",          // 溯源：哪份报告/哪次分析提出的
  "related_concept_ids": ["0000","0003"],
  "related_relation_ids": ["0000","0007"],
  "status": "open",                         // open | needs_evidence | researching | answered | dropped
  "priority": "high",                       // high | medium | low
  "evidence_lit_ids": [],
  "waiting_request_ids": [],                // 已向 A 提交的查询请求（用于"查完回来接着想"）
  "notes": "",
  "created_at": "...", "updated_at": "..."
}
```

**为什么要 `waiting_request_ids`**：需求说"D 知识不足 → 向 A 提交查询 → A 查完 B 消化 → D 继续"。
这个"继续"要能**自动接上**，就必须记住"我之前在等哪几个请求"。否则 D 无法判断
"新文献来了，哪些问题现在可以往下走了"。

### 2.2 `data/analysis_reports.json`（C 的产出登记）

```jsonc
{
  "report_id": "0000",
  "kind": "hottest|paths|cold|gaps",
  "request": "统计最热门的 5 个概念",        // 原始需求原文
  "params": { "top_n": 5 },                 // 结构化参数
  "summary": "……",                          // 结论摘要（给 D 读的第一入口）
  "payload": { },                           // 结构化结果（机器可读，D 靠它溯源）
  "markdown_path": "reports/0000-hottest.md",
  "created_at": "...", "created_by": "agent-C"
}
```

**为什么报告要"登记表 + 文件"双份**：D 需要**机器可读**的部分来溯源（`payload` 里的代号链），
人需要**可读**的部分（markdown 文件）。只存 markdown，D 就得解析自然语言才能拿到代号；
只存 JSON，人读不了。

---

## 3. 智能体 C（关系分析）

### 3.1 定位：**程序做分析，LLM 只做排序与措辞**

需求说得很明确——"用程序分析关系表"。所以：

- 计数、索引、图搜索、路径枚举、去重、溯源，**全部是确定性代码**；
- 只有两处留 LLM 钩子：① 路径的"最合理关系链"选择；② "是否值得研究"的判断。
  两者都有确定性回退，**无 API key 时功能降级但不缺失**。

### 3.2 图模型

```
节点 = 概念（concept_id）
边   = 关系（relation_id），连接 concept_ids 里的每对概念
      （注意：一条关系可以连 >2 个概念 —— 需求里"概念代号组"是数组）
```

一条 `concept_ids = [A,B,C]` 的关系会产生 3 条两两边，但**共享同一个 relation_id**。
这一点必须在路径输出里体现：路径给出的是**关系代号链**，而不是概念链。

### 3.3 四类需求各自的算法

#### (1) 统计最热门的几个概念 — `hottest(top_n)`

1. 遍历关系表，对每条关系的 `concept_ids` 里每个概念 **+1 次出现**（不是 +1 条关系：一条关系涉及 3 个概念就算 3 次出现）。
2. 另记 `relation_count`（参与的关系条数）与 `group_count`（作为概念组出现次数）。
3. 按 `occurrences` 降序取 top_n，**把代号翻译回概念名**（需求明确要求"翻译回到底是啥概念"）。
4. 同时给出每个热门概念的**代表关系**（引用数最高的 3 条），便于人工核对热度是否名副其实。
5. 输出必须带 `concept_id ↔ name ↔ counts`，且**排序稳定**（同分按 concept_id 升序），否则每次跑结果不同。

#### (2) 查询两个概念间的关系 — `paths(a, b, ...)`

这是 C 最复杂的功能，逐步拆解：

1. **图搜索**：从 a 到 b 做**有界**的简单路径枚举（节点不重复，`max_len` 默认 4 跳）。
   有界是必须的：概念图可能很密，无界枚举会爆炸。
2. **多路径 + 低重合度**（需求："给出多条实质上重合度不高的路径"）：
   按节点集合的 Jaccard 相似度做贪心筛选 —— 新路径若与已选路径的节点重合度 > `max_overlap`（默认 0.5）则丢弃。
   只按"路径不同"筛选是不够的：两条只差一个中间节点的路径，实质上是同一条。
3. **每步读全部相关关系**（需求："阅读每条路径每步的所有关系（毕竟包含概念 a 和概念 b 的关系可能挺杂）"）：
   对路径上**每一跳的两个端点**，取出**所有**把它们相连的关系（含不在该路径上的），
   因为"最合理的链"未必是搜索算法随机选中的那条边。
4. **为每条路径选最合理的关系链**：对每一跳，在候选关系里按确定性评分排序取最优：
   `quote_verified is True` > `None` > `False`；`status == active` > `suspect` > `rejected`；
   再比 description 信息量、文献多样性。LLM 钩子可在这一步重排（可选）。
5. **信息量判决 低/中/高**（需求要求"评估每条关系链蕴含的实际信息量"）：
   确定性评分 = 加权的几个可核实信号，见 §3.4。
6. **只写高信息量的**（需求："写进报告的都是信息量高的"）：
   `level == "high"` 的路径进正文；`medium` 进附录；`low` **只在统计里计数**，不展开。
   若全部为 low，报告要**明说"没有找到高信息量路径"**，而不是硬凑。

#### (3) 研究冷门概念 — `cold(top_n)`

1. 由度数（degree = 参与的关系条数）升序取最冷门的 top_n（**排除 degree == 0 的孤立概念**，
   它们单独归一类"完全孤立"，因为"没人研究"和"没人连接"是两件事）。
2. 对每个冷门概念，列出它与**热门概念**（top_n 热门集合）之间的全部关系 —— 需求要求"报告冷门概念和一些热门概念间的关系"。
3. **评估哪些关系连接较弱**：弱连接的判据是**可核实的**：
   `quote_verified is not True`、`status == suspect`、它是该概念**唯一**的连接、
   或该关系另一端概念本身也很冷门（无法借力）。给出 `weak_score` 与理由字符串。
4. 输出"冷门但连接强"的概念单独列出 —— 这一类最可能是**被低估的研究点**，是给 D 的核心输入。

#### (4) 完善关系图 — `gaps(limit)`

1. 找出**频次较少的概念组**（`concept_group_key` 出现次数 < 阈值的组合），
   以及**结构洞**：两个概念有共同邻居但彼此之间没有直接关系（这是"应该有边却缺失"的经典信号）。
2. 对每个候选项评估"是否确实可能有值得研究的关系"：
   - **可核实的正向信号**：有共同邻居（结构洞）、两个概念都在热门集里、所属领域文献充足；
   - **可核实的负向信号**：两者已被判过重复（`duplicate_of` 非空）、引文校验失败、概念名明显不是概念（长度异常/含停用词）。
3. 输出 `candidate_gaps`，每条带 `reason` 与 `confidence`。需求说"若确实有，则报告"——所以要有明确的
   "确实有/证据不足"二元结论，**不能把"没找到"包装成"找到了"**。

### 3.4 信息量评分（确定性，可解释）

```
score = 0
score += 2.0 * (quote_verified 为 True 的比例)        # 有原文支撑是最强信号
score -= 1.5 * (quote_verified 为 False 的比例)       # 引文找不到 = 可疑
score -= 1.0 * (status == suspect 的比例)
score += 0.6 * min(跳数, 3)                           # 多跳 = 更多推理链（但边际递减）
score += 0.8 * (不同文献数 / 跳数)                     # 跨文献的链条更有价值
score -= 0.5 * (description 平均长度 < 12 字符 ? 1:0)  # 描述过短 = 信息量低
score += 0.5 * (路径上出现了不出现在 top 热门集里的概念 ? 1:0)  # 绕开了最常见节点
判决：score >= 3.0 → high；>= 1.5 → medium；否则 low
```

阈值放在 `config.yaml`，不写死。**评分函数必须能逐项打印中间值** —— 报告要给出"为什么判成 high"，
否则 D 无法判断该不该信这条链。

### 3.5 C 的接口

```python
class AgentC:
    def __init__(self, store, config=None, actor="agent-C")
    def build_graph(self) -> RelationGraph
    def hottest(self, top_n=5) -> AnalysisReport
    def paths(self, a: str, b: str, *, max_paths=5, max_len=4, max_overlap=0.5) -> AnalysisReport
    def cold(self, top_n=5) -> AnalysisReport
    def gaps(self, limit=10) -> AnalysisReport
    def handle(self, request_text: str) -> AnalysisReport   # 自然语言需求 → 分派到上面四个
```

`handle()` 用**关键词分派**（"最热门"/"查询…关系"/"冷门"/"完善"）—— 确定性、可测试。
LLM 钩子可选。

---

## 4. 智能体 D（研究）

### 4.1 定位与状态机

D 的核心不是"生成文本"，而是**管理一个"问题 → 证据 → 缺口 → 新证据"的循环**。

```
        读 C 报告
            ↓
   [1] 提取候选研究问题          → research_questions(status=open)
            ↓
   [2] 对每个问题做溯源          → 关系 → 引文/陈述 → 文献 → 正文片段
            ↓
   [3] 评估证据是否足够
        ├─ 足够 → [5] 写研究报告
        └─ 不足 → [4] 向 A 提交查询请求（status=needs_evidence, waiting_request_ids=[r-xxxx]）
                        ↓
                   A 检索 → B 消化 → 新文献/新关系落库
                        ↓
   [6] 重新检查：等待中的请求完成了吗？有新关系能回答这个问题吗？
        └─→ 回到 [3]（这就是需求说的"D 继续思考研究"）
```

### 4.2 关键点：**"继续"靠等待集，不靠猜测**

`waiting_request_ids` 是这套循环能自动接上的唯一依据：
- D 提交请求时记下 `request_id`，并把问题置为 `needs_evidence`；
- 每轮开始时，D 检查这些请求是否 `done`（复用 `search_requests.outcome`）；
- 完成的请求取出 `result_lit_ids`，看这些文献是否已经 `processed`（即 B 消化完了）；
- 都消化完了，就把问题从 `needs_evidence` 拉回 `researching`，**并把新得到的关系并入证据**。
这一串全是确定性判断，不需要 LLM。

### 4.3 溯源的三个层级（需求："按代号溯源到相关表述，按需溯源到文献内容"）

| 层级 | 从 | 到 | 工具 |
|---|---|---|---|
| L1 | `relation_id` | `quote` / `description` / `page_range` | `trace.relation` |
| L2 | `concept_id` | 概念定义 + 它参与的全部关系的表述 | `trace.concept` |
| L3 | `lit_id` | 文献元数据 + 本地文件 + **正文片段**（按需，可能触发 OCR） | `trace.literature` |

L3 是**按需**的（贵）：只有 L1/L2 的表述不足以判断时才下钻到正文。

### 4.4 什么时候算"知识不足"

必须是**可核实的**判据，否则 D 会无限向 A 提问：

1. 问题的关键词在现有关系的 `quote`/`description` 里命中数为 0；
2. 或相关概念度数低于阈值且没有一条 `quote_verified=True` 的关系；
3. 或两条关键关系给出**互相矛盾**的 `statement`（这其实是最有价值的情况，应记为高优先级）。
每次提问前还必须查重：**同一问题已经提过且未完成时，不得重复提交**（否则会刷爆 A 的队列）。

### 4.5 D 的报告

按问题组织，每个问题一节：
`问题 → 为什么值得研究（引用 C 的证据）→ 现有证据（L1/L2 的逐字引用 + 代号链）→
缺口与已提交的查询 → 初步分析 → 结论与置信度（high/medium/low）→ 后续建议`。
**置信度低必须写"低"**，不得为了好看而拔高。

---

## 5. 编排：把 A→B→C→D 串起来

新增一条命令：

```
python -m agentflow.cli pipeline --request "查询 群 与 域 之间的关系" --gap-rounds 2
```

流程：`C 分析 → D 提取问题 → D 溯源 → 若缺证据则提交请求 → A 跑 → B 跑 → D 复查 → 重复 gap_rounds 轮 → 写报告`。
每轮的中间产物都落盘（报告 + 问题表），使流程**可中断、可续跑、可审计**。

---

## 6. 目录与文件（新增部分）

```
test/test1/
├── DESIGN-TOOLS.md              本文件
├── src/agentflow/
│   ├── tools/
│   │   ├── base.py              ToolSpec / ToolResult / ToolRegistry / 参数校验
│   │   ├── table_tools.py       表 CRUD
│   │   ├── fs_tools.py          文件 CRUD（沙箱在工作区内）
│   │   ├── search_tools.py      A：检索 / 下载 / 去重检查
│   │   ├── ocr_tools.py         B：OCR（后端可插拔）
│   │   ├── graph_tools.py       C：图索引与查询
│   │   ├── trace_tools.py       C/D：代号溯源
│   │   └── research_tools.py    D：问题与缺口
│   ├── agent_c.py               关系分析
│   ├── agent_d.py               研究循环
│   └── pipeline.py              A→B→C→D 编排
├── reports/                     C 的报告（markdown）+ D 的研究报告
└── tests/test_tools_*.py, test_agent_c.py, test_agent_d.py
```

---

## 7. OCR 的现实约束（已勘察）

| 后端 | 状态 | 说明 |
|---|---|---|
| `easyocr` | ✅ 已安装（PyTorch，**不需要系统二进制**） | 首次使用会下载模型（~100MB）；初始化慢 |
| `pytesseract` | ⚠️ 已安装但 **`tesseract` 可执行文件不存在** | 直接调用会失败；必须**探测**而非假定可用 |
| `pdftoppm` | ✅ 存在（来自 MiKTeX） | 但我们优先用已安装的 `fitz` 做栅格化，少一个外部依赖 |

**设计要点**：`ocr.backends` 必须**真实探测**（尝试 `pytesseract.get_tesseract_version()`、
尝试构造 easyocr Reader），并把探测结果如实报告。**没有可用后端时必须返回
`available=False` 且理由明确**，绝不允许"假装 OCR 成功返回空文本" ——
那会与 `DESIGN.md` §6.3 的"无文本层返回 `None` 而不是 `False`"精神一致：
**"没做"和"做了但没结果"是两件事。**

## 8. 待决问题

1. C 的"最合理关系链"是否允许 LLM 重排？本轮实现确定性排序 + 钩子占位。
2. D 的"值得研究的问题"数量上限？（本轮默认每份 C 报告最多提 5 个，防爆炸）
3. D 向 A 提问的**预算**（每个问题最多几轮、全局最多几个请求）？本轮默认每问题 2 轮、全局 20 个。
4. 新增两张表是否要参与 `verify` 的全局不变量检查？（本轮：参与，且检查代号外键）
5. 概念"孤立"（degree=0）是否要单独出报告？本轮只在 `cold` 里分类统计。

---

## 9. 实现期记录：一处受控的架构偏离

### 9.1 D 的提问台账刻意不进 schema（`data/research_request_ledger.json`）

**是什么**：`tools/research_tools.py` 把"本问题已经问过 A 什么"记在一个**模块私有的 JSON 文件**里，
而不是放进 `research_questions` 表。

**为什么允许**（实现方给出的理由，本设计接受）：
- 它是**模块私有**的去重台账，语义上是"提问历史"，而 `waiting_request_ids` 只表达"当前在等谁"；
  问题答完之后等待集会被清空，历史就丢了 —— 而"这个坑我挖过、答案是查不到"恰恰是 D 最需要记住的。
- 放进 `schema.TABLES` 会牵动 `LOCK_ORDER` / `verify` / `rebuild` 三个公共契约，
  在"最低可用"阶段成本高于收益。
- 它用**同一把 `research_questions.lock`** 保护（所有读写都在已持有该锁的事务内），
  所以并发安全性与主表一致。

**代价（必须记住，不许淡化成"无所谓"）**：
- ⚠️ **台账不能从 `events.jsonl` 重建**。`agentflow rebuild` 会恢复主表但**不会**恢复台账。
  删掉台账的后果是"可能重复向 A 提问一次"——可接受，但必须知情。
- 因此已给它加了 `verify` 检查：`ledger_corrupt` / `ledger_dangling_question` /
  `ledger_dangling_request` / `ledger_drift`（台账说"还在等"但主表等待集为空）。
  **接受一个偏离的前提是让它可观测**，否则漂移会静默发生。

**何时应当纠正**：如果 D 的提问历史需要参与审计或跨机迁移，就应把它提升为 schema 表
（届时同步改 `LOCK_ORDER` 与 `rebuild`）。

