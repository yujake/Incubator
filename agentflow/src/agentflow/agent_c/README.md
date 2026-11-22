# agent_c —— C：关系分析（只读角色）

**职责（声明原文）**：关系分析 —— 用确定性代码算图与计数，只在排序与措辞这两件事上动用模型。
**典型误根**：把模型给的排序当成算出来的评分。

- 声明在 [`../specs/c.py`](../specs/c.py)：10 个动作、**出边为空**、写集只有
  `analysis_reports` + `search_requests`、`read_only=True`。
- 结构上拿不到写工具；它落库只经 `handle` 那一个登记口（外加 `gaps(submit_requests=true)`
  落检索请求）。实现类 `agent_c:AgentC`。
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

上游：**B**（`relations` 行是分析输入）。下游：**D**（把 C 的报告消化成研究问题）。
C 的报告落 `<ws>/reports/<report_id>-<kind>.md` 与 `analysis_reports` 一行；它不写
`statements` / `literature` —— 那是 B 与 A 的表。
