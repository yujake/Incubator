"""智能体 C：关系分析（程序做分析，LLM 只做排序与措辞）。
定位（DESIGN-TOOLS.md §3.1）- 计数、索引、图搜索、路径枚举、去重、评分、溯源，全部是确定性代码（图与索引在 `tools/graph_tools.py`，代号溯源在 `tools/trace_tools.py`）；- 只有
两处留 LLM 钩子，且默认关闭（构造时`llm=None` 即可）：① 路径"最合理关系链"的排序； 1. `hottest`：热度是 occurrences（概念在 `concept_ids` 里出现的次数），不是关系条数 —— 一条涉及
3 个概念的关系对其中每个概念都算 1 次出现。排序必须稳定（同分按 `concept_id` 升序），否则同分概念的相对顺序会随字典插入顺序漂移，报告每次都不一样。 2. `paths`：见下方"三条不让步的规则"。 3. `cold`："没
人研究"（degree 小）与"没人连接"（degree=0 的完全孤立）是两件事，必须分开归类； 4. `gaps`：需求说"若确实有，则报告"。所以按节点集合的 Jaccard 相似度贪心筛：新路径与任何已选路径的重合度
`> max_overlap`（默认 0.5）就丢弃。取候选后按 §3.3(4) 的确定性序重选。报告要给 D 的不只是"high"这个标签，而是"为什么判成 high"：`score_breakdown` 里逐项列出每个信号的输入值与贡献值。
报告形态：登记表 + 文件双份（§2.2）`AnalysisReport.payload` 是 D 溯源用的机器可读部分（代号链、评分明细），`AnalysisReport.markdown` 是人读的部分。`persist()` 把两者分别落
到`reports/<report_id>-<kind>.md` 与 `analysis_reports` 表。服务面（DESIGN-INTERACTIONS.md §1 I1 / I3 / I5）四类分析器是批处理：跑一次、产一份报告、进 
`analysis_reports` 表。所以本模块另外提供服务方法（`neighbors` /`relations_between` / `contradictions` / `structural_duplicates`）：- 每个结果都带
`checked` 三态位（`False` = 没查，`True` + `empty=True` = 查了没有）；- 触及预算一定给 `truncated=True` 并说明原因 —— 静默截断会被下游读成"就这些"，而它是一条口吻确定的错误结
论；- 判据一律委托给冻结契约 `interactions`（矛盾、结构重复、冲突检查），绝不在这里写第二份。唯一的写入路径是 `gaps(submit_requests=True)`（I3：把"应该有边却缺失"的候选直接变成 A 的检索请求），
默认关闭，且由 `gaps()` 的确定性代码路径完成 —— 它不经过 C 的工具与推理，写的也不是知识。工具面（`register_tools`）因此可以保持全量只读。`goal-7f5116c1` M6/M7 把本模块拆成包：这里只做入口与
命名空间的保持 ——拆包不许改变 import 面，所以原来能在 `agentflow.agent_c` 下 import 到的名字（含私有名，也包括住在`core.py` 的`_selftest` / `selftest`）都逐个再导出；动作
各自在 `agent_c/<动作>.py`，`python -m agentflow.agent_c` 的自检入口在同目录 `__main__.py`。
"""
from __future__ import annotations

from .core import AgentC
from ._support import (ANALYZERS, AgentBrief, AgentSpec, AnalysisReport, Any, D, 
    DEFAULT_SCORE_WEIGHTS, DEFAULT_THRESHOLD_HIGH, DEFAULT_THRESHOLD_MEDIUM, Iterable, LEVELS, 
    Mapping, Path, PathSearchResult, RelationGraph, S, SERVICE_MAX_CONTRADICTIONS, 
    SERVICE_MAX_DEPTH, SERVICE_MAX_NODES, SERVICE_MAX_STRUCTURAL_PAIRS, SPEC, SUBMITTER, 
    Sequence, Store, StoreError, T, ToolRegistry, _MISSING, _atomic_write_text, _cfg_float, 
    _cfg_get, _cfg_int, _service_int, annotations, check_conflict, dataclass, fail, field, 
    interactions, json, ok, os, re, relation_sort_key, tool,
)
from ..specs.c import SPEC
#: 候选路径的形状读数（业主 2026-10-22）：`proof_chain` 的 payload 里那一列
#: (`path_shapes`) 就是它算的，单独导出是为了让判据能直接喂图进去复核口径。
from .path_shape import path_shapes

__all__ = [
    "AgentC",
    "AnalysisReport",
    "DEFAULT_SCORE_WEIGHTS",
    "SERVICE_MAX_CONTRADICTIONS",
    "SERVICE_MAX_DEPTH",
    "SERVICE_MAX_NODES",
    "SERVICE_MAX_STRUCTURAL_PAIRS",
    "SUBMITTER",
    "check_conflict",
    "path_shapes",
    "SPEC",
]
