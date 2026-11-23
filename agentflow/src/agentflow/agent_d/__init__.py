"""智能体 D：研究循环。

设计基线：`test/test1/DESIGN-TOOLS.md` §4（D 的状态机 / 溯源三级 / 知识不足判据 /
报告结构）与 §5（编排里 D 的位置）。D 的核心不是"生成文本"，而是管理一个循环（§4.1）。
四个不可让步的设计，每条背后都有具体的失败模式：

1. 提取问题必须确定性 + 可解释（`ingest`）：从 `report.payload` 读结构化发现（hottest
   的 top 概念、paths 的高信息量链条、cold 的"冷门但连接强"、gaps 的 candidate_gaps），
   用模板生成问题文本，并把 `origin` 与 `related_concept_ids` / `related_relation_ids`
   一并记下。
2. 知识不足的判据必须可核实（`assess` / `analyze_gaps`）：只有三类判据，全部能逐条
   打印中间值 —— 关键词在现有关系的 `quote` / `description` 里命中数为 0；相关概念度数
   低于阈值且没有一条 `quote_verified=True` 的关系；两条关键关系给出互相矛盾的表述
   （最有价值，记 `priority="high"`）。
3. "继续"靠等待集，不靠猜测（`poll`）：每一轮"能不能往下走"只依据
   `waiting_request_ids` + 请求的 `outcome` + 文献的 `processed`（§4.2）。
4. 置信度不许拔高（`research` / `evidence_confidence`）：确定性证据算出来的置信度是
   上限，LLM 钩子只允许把它调低、不允许调高（见 `_llm_refine` 里的 `_rank_min`）。

LLM 的位置：`llm=None` 时全部走确定性回退（模板化措辞 + 证据罗列），因此无 API key 也能
端到端跑通。另外几条：I1 C 作为可调用服务（`probe_c`）—— D 现场推导参数去问 C，拿不到
方法 / 方法抛异常 / 返回值不是 dict 都必须记成 `checked=False` + 明确理由，绝不把"没调用
成功"静默当成"没有结果"；I2 矛盾闭环（`adjudicate`）—— 只有 `strength == "strong"` 的
矛盾才允许建问题与自动追问，`weak` 假阳性极高，只记录为线索；问题等价类（`ingest` 第三
层去重）用 `interactions.find_equivalent_question`，命中就把 `origin` 合并进已有问题；
§3.2 证据就绪（`poll`）再加一层 `interactions.evidence_relevance`。

判据只有一份：本模块对 `interactions` 的委托（`_contains` / `_negated` /
`_opposite_flags` / `detect_contradictions` 等）保留原名但函数体只做转发 —— I6 要求 B
在写入期用同一份判据问"这条新关系与已有的是否矛盾"。

拆包只做入口与命名空间保持：import 面不许变，动作各自在 `agent_d/<动作>.py`。
"""
from __future__ import annotations

from .core import AgentD, REPORTS_SUBDIR_DEFAULT
from .core import (_selftest,
)
from ._support import (AgentBrief, AgentSpec, Any, CONFIDENCE_LABELS, 
    C_API_MISSING_REASON, C_NO_EVIDENCE, EvidenceError, IX, Iterable, Mapping, Path, ROLES, RT, 
    S, SPEC, Sequence, Store, StoreError, ToolError, ToolRegistry, _C_AUTO, _NEGATION_MARKERS, 
    _OPPOSITE_PAIRS, _STOPWORDS, _TOKEN_SPLIT_RE, _UNSPECIFIED, _as_report_dict, _conf_label, 
    _contains, _digest, _fallback_trace_tools, _negated, _opposite_flags, _rank, _rank_min, 
    _report_field, analyze_gaps, annotations, detect_contradictions, evidence_confidence, 
    install_d_tools, json, keyword_hits, load_trace_tools, question_keywords, re, 
    validate_tool_roles,
)
from ..specs.d import SPEC

__all__ = [
    "AgentD",
    "REPORTS_SUBDIR_DEFAULT",
    "EvidenceError",
    "analyze_gaps",
    "install_d_tools",
    "load_trace_tools",
    "validate_tool_roles",
    "SPEC",
]
