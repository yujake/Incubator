# agent_c —— C：关系分析（只读角色）

**职责（声明原文）**：关系分析 —— 用确定性代码算图与计数，只在排序与措辞这两件事上动用模型。
**典型误根**：把模型给的排序当成算出来的评分。

- 声明在 [`../specs/c.py`](../specs/c.py)：10 个动作、**出边为空**、写集只有
  `analysis_reports` + `search_requests`、`read_only=True`。
- 结构上拿不到**通用**写工具（`table.*` 只有读的那几件：count / get / list / schema / search）；
  落库只有两个面，都在 `capabilities.READ_ONLY_WRITE_EXCEPTIONS["C"]` 里逐条登记：
  ① `analysis_reports` —— 动作 `handle` 的产出登记口 `_support.AnalysisReport.persist()`
  **与**工具面里的 `analysis.register_report` 走的是**同一个** `persist()`（那件工具是
  `tools.base.READONLY_CALL_EXCEPTIONS["C"]` 的受控例外，只写这一张表）；
  ② `search_requests` —— `gaps(submit_requests=true)` 落的检索请求。
  （改前本行写"结构上拿不到写工具 / 落库只经 handle"，漏了 `analysis.register_report`；
  2026-11-22 ROLEDOC-1 更正。）实现类 `agent_c:AgentC`。
- **谁读**：改分析口径的人；C 的每个动作都是"一个动作一个文件"。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentC` 骨架（装 mixin） |
| `handle.py` | 动作 `handle`：自然语言需求 → 分派到分析器；**产出登记口** |
| `hottest.py` | 动作 `hottest`：度数中心性最热榜 |
| `cold.py` | 动作 `cold`：冷门 / 孤立概念 |
| `gaps.py` | 动作 `gaps`：结构缺口候选（可选提交检索请求） |
| `neighbors.py` | 动作 `neighbors`：某概念的邻居（可指定深度） |
| `paths.py` | 动作 `paths`：两概念之间的关系路径 |
| `relations_between.py` | 动作 `relations_between`：两概念之间的全部关系 |
| `contradictions.py` | 动作 `contradictions`：互相矛盾的关系对 |
| `structural_duplicates.py` | 动作 `structural_duplicates`：结构重复候选（I5 的输入） |
| `proof_chain.py` | 动作 `proof_chain`：一条成果的最短证明依赖链 |
| `path_shape.py` | 候选路径的"形状"读数（供 `paths` 与 D 读，不是声明动作） |
| `_support.py` | 包内共用小工具 |

## 怎么用

```powershell
python -m agentflow.agent_c        # 零模型自检
# 在工具面里看 C 拿到什么（应当没有任何写工具）
python -m agentflow.cli tools --role C

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['C'].actions))"
```

## 邻居

上游（能召唤 C 的，`capabilities.ALLOWED_EDGES` 现算）：**B / D / F / G / L / M** ——
数据上游是 **B** 的 `relations` 行（以及 G 的稿、D 的研究问题）。
（改前本行只写"上游：B"，漏了 **M** 与 **D** —— 还有 F / G / L；2026-11-22 ROLEDOC-1 更正。）
下游：**D**（把 C 的报告消化成研究问题）。
C 的报告落 `<ws>/work/C/<report_id>-<kind>.md` 与 `analysis_reports` 一行（2026-11-22 起；
旧落点 `reports/` 已退役，不再写）；它不写
`statements` / `literature` —— 那是 B 与 A 的表。
