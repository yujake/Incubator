"""关系分析智能体。构造时 `llm=None` 即完全确定性（默认，也是可测试的路径）。

`goal-7f5116c1` M6 把本模块拆成包：这里只做入口与命名空间的保持 ——
拆包不许改变 import 面，所以原来能在 `agentflow.agent_c` 下 import 到的名字
（含私有名）都逐个再导出；动作各自在 `agent_c/<动作>.py`。
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

__all__ = ["AgentC", "SPEC"]
