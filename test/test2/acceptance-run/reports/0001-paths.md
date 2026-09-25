# C 分析报告：paths

- 生成者：`agent-C`
- 标题摘要：找到 4 条高信息量路径（另有 medium 0 条、low 0 条）：K(m)→S̃_m（0008，score=3.40）；K(m)→spectrum of a periodic graph→cospectral→S̃_m（0016→0007→0007，score=4.57）；K(m)→girth→spectral invariant→S̃_m（0023→0011→0011，score=4.57）

查询：**K(m)（0000）** ↔ **S̃_m（0001）**

- 图搜索到 24 条简单路径（截断=False，原因=无，预算 61/20000；按跳数分布 {'1': 1, '2': 6, '3': 8, '4': 9}）
- 低重合度筛选后保留 4 条，报告展开 4 条，因重合度丢弃 20 条，因 max_paths 丢弃 0 条
- 信息量判决：high 4 / medium 0 / low 0
- LLM 钩子：未启用 LLM 钩子：路径顺序完全由确定性评分决定。

## 正文（仅高信息量路径）

### 路径 1（高信息量，score=3.40，1 跳）

- 概念链：K(m)(0000) → S̃_m(0001)
- **关系代号链**：0008
- 涉及文献：0000
    - 第 1 跳 K(m)(0000) → S̃_m(0001)：候选 4 条 ['0008', '0007', '0002', '0011']，选中 `0008`

评分明细（为什么是这个等级）：

- 引文已校验比例：quote_verified=True 的跳数 1/1 = 1.00 → +2.0
- 引文校验失败比例：quote_verified=False 的跳数 0/1 = 0.00 → +-0.0
- suspect 比例：status=suspect 的跳数 0/1 = 0.00 → +-0.0
- 跳数：min(跳数 1, 3) = 1（边际递减） → +0.6
- 跨文献多样性：不同文献 1 篇 / 跳数 1 = 1.00 → +0.8
- 描述过短：平均描述长度 71.0 字符 → 不计入 → +-0.0
- 绕开最常见节点：不在热门集里的概念 无 → 不计入 → +0.0

    合计 3.4（阈值 high>=3.0 / medium>=1.5）⇒ **high**

### 路径 2（高信息量，score=4.57，3 跳）

- 概念链：K(m)(0000) → spectrum of a periodic graph(0005) → cospectral(0007) → S̃_m(0001)
- **关系代号链**：0016 → 0007 → 0007
- 涉及文献：0000
    - 第 1 跳 K(m)(0000) → spectrum of a periodic graph(0005)：候选 7 条 ['0016', '0017', '0019', '0015', '0003', '0022', '0007']，选中 `0016`
    - 第 2 跳 spectrum of a periodic graph(0005) → cospectral(0007)：候选 1 条 ['0007']，选中 `0007`（来自已用过的文献，但可信度/信息量更优）
    - 第 3 跳 cospectral(0007) → S̃_m(0001)：候选 1 条 ['0007']，选中 `0007`（来自已用过的文献，但可信度/信息量更优）

评分明细（为什么是这个等级）：

- 引文已校验比例：quote_verified=True 的跳数 3/3 = 1.00 → +2.0
- 引文校验失败比例：quote_verified=False 的跳数 0/3 = 0.00 → +-0.0
- suspect 比例：status=suspect 的跳数 0/3 = 0.00 → +-0.0
- 跳数：min(跳数 3, 3) = 3（边际递减） → +1.8
- 跨文献多样性：不同文献 1 篇 / 跳数 3 = 0.33 → +0.2667
- 描述过短：平均描述长度 85.0 字符 → 不计入 → +-0.0
- 绕开最常见节点：不在热门集里的概念 ['0007'] → 计入 → +0.5

    合计 4.5667（阈值 high>=3.0 / medium>=1.5）⇒ **high**

### 路径 3（高信息量，score=4.57，3 跳）

- 概念链：K(m)(0000) → girth(0008) → spectral invariant(0011) → S̃_m(0001)
- **关系代号链**：0023 → 0011 → 0011
- 涉及文献：0000
    - 第 1 跳 K(m)(0000) → girth(0008)：候选 5 条 ['0023', '0008', '0020', '0011', '0005']，选中 `0023`
    - 第 2 跳 girth(0008) → spectral invariant(0011)：候选 1 条 ['0011']，选中 `0011`（来自已用过的文献，但可信度/信息量更优）
    - 第 3 跳 spectral invariant(0011) → S̃_m(0001)：候选 1 条 ['0011']，选中 `0011`（来自已用过的文献，但可信度/信息量更优）

评分明细（为什么是这个等级）：

- 引文已校验比例：quote_verified=True 的跳数 3/3 = 1.00 → +2.0
- 引文校验失败比例：quote_verified=False 的跳数 0/3 = 0.00 → +-0.0
- suspect 比例：status=suspect 的跳数 0/3 = 0.00 → +-0.0
- 跳数：min(跳数 3, 3) = 3（边际递减） → +1.8
- 跨文献多样性：不同文献 1 篇 / 跳数 3 = 0.33 → +0.2667
- 描述过短：平均描述长度 72.0 字符 → 不计入 → +-0.0
- 绕开最常见节点：不在热门集里的概念 ['0011'] → 计入 → +0.5

    合计 4.5667（阈值 high>=3.0 / medium>=1.5）⇒ **high**

### 路径 4（高信息量，score=4.50，4 跳）

- 概念链：K(m)(0000) → Floquet matrix(0006) → spectrum of a periodic graph(0005) → spectral invariant(0011) → S̃_m(0001)
- **关系代号链**：0018 → 0015 → 0009 → 0011
- 涉及文献：0000
    - 第 1 跳 K(m)(0000) → Floquet matrix(0006)：候选 3 条 ['0018', '0015', '0014']，选中 `0018`
    - 第 2 跳 Floquet matrix(0006) → spectrum of a periodic graph(0005)：候选 1 条 ['0015']，选中 `0015`（来自已用过的文献，但可信度/信息量更优）
    - 第 3 跳 spectrum of a periodic graph(0005) → spectral invariant(0011)：候选 1 条 ['0009']，选中 `0009`（来自已用过的文献，但可信度/信息量更优）
    - 第 4 跳 spectral invariant(0011) → S̃_m(0001)：候选 1 条 ['0011']，选中 `0011`（来自已用过的文献，但可信度/信息量更优）

评分明细（为什么是这个等级）：

- 引文已校验比例：quote_verified=True 的跳数 4/4 = 1.00 → +2.0
- 引文校验失败比例：quote_verified=False 的跳数 0/4 = 0.00 → +-0.0
- suspect 比例：status=suspect 的跳数 0/4 = 0.00 → +-0.0
- 跳数：min(跳数 4, 3) = 3（边际递减） → +1.8
- 跨文献多样性：不同文献 1 篇 / 跳数 4 = 0.25 → +0.2
- 描述过短：平均描述长度 81.8 字符 → 不计入 → +-0.0
- 绕开最常见节点：不在热门集里的概念 ['0011'] → 计入 → +0.5

    合计 4.5（阈值 high>=3.0 / medium>=1.5）⇒ **high**


## 附录（中等信息量路径，仅供参考，**未达正文标准、不作为证据**）

（无）

## 统计（低信息量路径不展开，仅计数）

- 低信息量路径：0 条；分数区间：（无）

## 被重合度筛掉的路径（说明去重确实起了作用）

- K(m)→periodic graph→S̃_m：与已选路径节点重合度 0.67 > max_overlap=0.5（本质上同一条路径）（与 0000→0001 比）
- K(m)→spectrum of a periodic graph→S̃_m：与已选路径节点重合度 0.67 > max_overlap=0.5（本质上同一条路径）（与 0000→0001 比）
- K(m)→cospectral→S̃_m：与已选路径节点重合度 0.67 > max_overlap=0.5（本质上同一条路径）（与 0000→0001 比）
- K(m)→girth→S̃_m：与已选路径节点重合度 0.67 > max_overlap=0.5（本质上同一条路径）（与 0000→0001 比）
- K(m)→vertex-transitive→S̃_m：与已选路径节点重合度 0.67 > max_overlap=0.5（本质上同一条路径）（与 0000→0001 比）
- K(m)→spectral invariant→S̃_m：与已选路径节点重合度 0.67 > max_overlap=0.5（本质上同一条路径）（与 0000→0001 比）
- K(m)→spectrum of a periodic graph→spectral invariant→S̃_m：与已选路径节点重合度 0.60 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→spectrum of a periodic graph→companion book [6]→S̃_m：与已选路径节点重合度 0.60 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→Floquet matrix→spectrum of a periodic graph→S̃_m：与已选路径节点重合度 0.60 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→cospectral→spectrum of a periodic graph→S̃_m：与已选路径节点重合度 1.00 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→spectral invariant→spectrum of a periodic graph→S̃_m：与已选路径节点重合度 0.60 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→spectral invariant→girth→S̃_m：与已选路径节点重合度 1.00 > max_overlap=0.5（本质上同一条路径）（与 0000→0008→0011→0001 比）
- K(m)→spectrum of a periodic graph→spectral invariant→girth→S̃_m：与已选路径节点重合度 0.80 > max_overlap=0.5（本质上同一条路径）（与 0000→0008→0011→0001 比）
- K(m)→Floquet matrix→spectrum of a periodic graph→cospectral→S̃_m：与已选路径节点重合度 0.80 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→Floquet matrix→spectrum of a periodic graph→companion book [6]→S̃_m：与已选路径节点重合度 0.67 > max_overlap=0.5（本质上同一条路径）（与 0000→0006→0005→0011→0001 比）
- K(m)→cospectral→spectrum of a periodic graph→spectral invariant→S̃_m：与已选路径节点重合度 0.80 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→cospectral→spectrum of a periodic graph→companion book [6]→S̃_m：与已选路径节点重合度 0.80 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→girth→spectral invariant→spectrum of a periodic graph→S̃_m：与已选路径节点重合度 0.80 > max_overlap=0.5（本质上同一条路径）（与 0000→0008→0011→0001 比）
- K(m)→spectral invariant→spectrum of a periodic graph→cospectral→S̃_m：与已选路径节点重合度 0.80 > max_overlap=0.5（本质上同一条路径）（与 0000→0005→0007→0001 比）
- K(m)→spectral invariant→spectrum of a periodic graph→companion book [6]→S̃_m：与已选路径节点重合度 0.67 > max_overlap=0.5（本质上同一条路径）（与 0000→0006→0005→0011→0001 比）
