"""智能体 C：关系分析（程序做分析，LLM 只做排序与措辞）。

定位：计数、索引、图搜索、路径枚举、去重、评分、溯源全部是确定性代码（图与索引在
`tools/graph_tools.py`，代号溯源在 `tools/trace_tools.py`）；只有两处留 LLM 钩子且默认
关闭（构造时 `llm=None`）：路径"最合理关系链"的排序，以及分析器要措辞时的缝。

分析器口径：`hottest` 的热度是 occurrences（概念在 `concept_ids` 里出现的次数），不是
关系条数；排序必须稳定（同分按 `concept_id` 升序），否则相对顺序会随字典插入顺序漂移。
`paths` 见"三条不让步的规则"。`cold` 把"没人研究"（degree 小）与"没人连接"（degree=0）
分开归类。`gaps` 按节点集合的 Jaccard 相似度贪心筛（重合度 `> max_overlap` 默认 0.5
就丢弃），取候选后按确定性序重选。报告要给 D 的不只是"high"这个标签，而是"为什么判成
high"：`score_breakdown` 逐项列出每个信号的输入值与贡献值。

报告形态：登记表 + 文件双份（§2.2）。`AnalysisReport.payload` 是机器可读部分（代号链、
评分明细），`markdown` 是人读的部分；`persist()` 把两者分别落到
`work/C/<report_id>-<kind>.md`（2026-11-22 起；旧落点 `reports/` 已退役）与
`analysis_reports` 表。

服务面（I1 / I3 / I5）四类分析器是批处理。`neighbors` / `relations_between` /
`contradictions` / `structural_duplicates` 每个结果都带 `checked` 三态位（`False` = 没查，
`True` + `empty=True` = 查了没有）；触及预算一定给 `truncated=True` 并说明原因。判据一律
委托给冻结契约 `interactions`。唯一的写入路径是 `gaps(submit_requests=True)`（I3），
默认关闭，由确定性代码路径完成 —— 工具面因此保持全量只读。

拆包只做入口与命名空间保持：import 面不许变，动作各自在 `agent_c/<动作>.py`。
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
#: `join_segments` 是同一份口径的另一面：把两批读数按前沿接起来，给 C 核对接缝用
#: （核对材料，不是自动拼链器 —— 要不要接着搜由模型定）。
from .path_shape import join_segments, path_shapes

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
    "join_segments",
    "path_shapes",
    "SPEC",
]
