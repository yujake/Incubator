"""智能体 D：研究循环。

设计基线：``test/test1/DESIGN-TOOLS.md`` §4（D 的状态机 / 溯源三级 / 知识不足判据 /
报告结构）与 §5（编排里 D 的位置）。

## D 到底在做什么

D 的核心不是"生成文本"，而是管理一个循环（§4.1）：

    读 C 报告 → 提取候选问题 → 按代号溯源 → 评估证据是否足够
        ├─ 足够 → 写研究报告
        └─ 不足 → 向 A 提交查询请求（记入等待集）
                    → A 检索 → B 消化 → D 复查（poll）→ 回到"评估"

## [契约] 四个不可让步的设计（每一条都有具体的失败模式在背后）

1. 提取问题必须是确定性 + 可解释的（``ingest``）。
   绝不做"让 LLM 想几个问题"：那既无法复现，也无法解释"这个问题是怎么来的"。
   改为从 ``report.payload`` 里读结构化发现（hottest 的 top 概念、paths 的
   高信息量链条、cold 的"冷门但连接强"、gaps 的 candidate_gaps），用模板生成
   问题文本，并把 ``origin``（如 ``"C:paths:0000->0003"``）与
   ``related_concept_ids`` / ``related_relation_ids`` 一并记下。

   为什么问题必须带代号溯源：人是靠"这条链/这个概念"去核对结论的。
   一个不带代号的问题（"交换性是否可推广？"）在报告里无法被验证 ——
   读者既不知道它从哪来，也无法回到关系表里看那几条原文。
   代号把"结论"与"证据"钉在一起，这是本系统对"完全引用参考文献"这一
   需求的直接延续。

2. 知识不足的判据必须可核实（``assess`` / :func:`analyze_gaps`）。
   只有三类判据，全部可以逐条打印出中间值：
   (a) 关键词在现有关系的 ``quote``/``description`` 里命中数为 0；
   (b) 相关概念度数低于阈值且没有一条 ``quote_verified=True`` 的关系；
   (c) 两条关键关系给出互相矛盾的表述（最有价值，记 ``priority="high"``）。
   绝不用"感觉不够"这种判据：那种判据无法被反驳，于是 D 会无限向 A 提问，
   把 A 的队列刷爆，而且没有任何一处能说明"为什么不够"。

3. "继续"靠等待集，不靠猜测（``poll``）。
   每一轮的"能不能往下走"只依据 ``waiting_request_ids`` + 请求的 ``outcome``
   + 文献的 ``processed``（§4.2）。没有等待集，D 就无法判断"新来的文献是不是
   我在等的" —— 库里多几篇文献可能是因为别的需求，也可能是因为我提的请求；
   只有等待集能把这两件事分开。这一串判断全是确定性的，不需要 LLM。

4. 置信度不许拔高（``research`` / :func:`evidence_confidence`）。
   确定性证据算出来的置信度是上限：LLM 钩子只允许把它调低，不允许调高
   （见 ``_llm_refine`` 里的 ``_rank_min``）。报告里"低"就写"低" ——
   一份把"低"写成"中"的报告会让人把猜想当成结论去用，那比没有报告更坏。

## [为什么] LLM 的位置

``llm=None`` 时全部走确定性回退（模板化措辞 + 证据罗列），因此无 API key
也能端到端跑通（§0 的"最低可用"边界）。LLM 只用于两件事：
把证据包写成更通顺的分析文字、以及对问题做"值得研究吗"的补充判断；
两者的结果都必须经过确定性校验（置信度不许升、结论必须能回指证据）。

## 本轮新增：I1 / I2 / §3.1 / §3.2（见 DESIGN-INTERACTIONS.md）

5. I1 C 作为可调用服务（``probe_c``）：D 不再只消费 ``analysis_reports``，
   而是在研究/评估某个问题时现场推导参数去问 C（``neighbors`` /
   ``relations_between`` / ``contradictions``）。关键纪律是防御式适配：
   C 的服务方法由并行开发的任务提供，拿不到方法、方法抛异常、返回值不是 dict，
   这三种情况都必须记成 ``checked=False`` + 明确理由，绝不允许把
   "没调用成功"静默当成"没有结果" —— 那正是上一版"D 没接工具却把查不到
   写成一条听起来很合理的研究发现"的形态。一条 C 查询都没成功时，结论必须
   显式标注「无 C 侧证据」并放弃确定语气。

6. I2 矛盾闭环（``adjudicate`` / ``_adjudicate_ready_contradictions``）：
   C 检测到矛盾 → D 建 ``kind="contradiction"`` 的高优先级问题 → 裁决
   （``interactions.adjudicate_contradiction``）→ ``unresolved`` 就再问一轮、
   ``resolved``/``persistent`` 就收口。必须有终止条件（单条矛盾轮数上限 +
   全局矛盾检索配额），否则它是一个天然的无限循环。
   只有 ``strength == "strong"`` 的矛盾才允许建问题与自动追问：
   ``weak``（只是否定标记出现与否不一致）的假阳性极高（实测 24%），
   只记录为线索 —— 拿它去问 A 等于用 A 的产能换假问题。

7. §3.1 问题等价类（``ingest`` 里第三层去重）：内容键之外再用
   ``interactions.find_equivalent_question`` 判"是不是同一个研究点"，
   命中就把 ``origin`` 合并进已有问题的 notes，而不是新建一行。

8. §3.2 证据就绪判据（``poll``）：旧的"请求 done 且文献 processed"只说明
   消化完了，不说明这些证据真的回答了那个问题。再加一层
   ``interactions.evidence_relevance``：不相关就不推进并降优先级，
   没检查（``checked=False``）则既不推进也不当作"不相关"。

### 判据只有一份：本模块对 ``interactions`` 的委托

下面这些名字（``_contains`` / ``_negated`` / ``_opposite_flags`` /
``detect_contradictions`` / ``_NEGATION_MARKERS`` / ``_OPPOSITE_PAIRS``）
保留原名但函数体只做转发：唯一权威实现已经移到 ``interactions.py``。
理由：I6 要求 B 在写入期用同一份判据问"这条新关系与已有的是否矛盾"。
两份实现必然漂移，而漂移的后果是"写入期认为不矛盾、事后 C 认为矛盾"这种
没有任何报错的静默分裂 —— 那比崩溃更难发现。

`goal-7f5116c1` M6/M7 把本模块拆成包：这里只做入口与**命名空间的保持** ——
拆包不许改变 import 面，所以原来能在 `agentflow.agent_d` 下 import 到的名字（含私有名，也包括住在 `core.py` 的
`_selftest` / `selftest`）都逐个再导出；动作各自在 `agent_d/<动作>.py`，
`python -m agentflow.agent_d` 的自检入口在同目录 `__main__.py`。
"""
from __future__ import annotations

from .core import AgentD
from .core import (_selftest,
)
from ._support import (AgentBrief, AgentSpec, Any, CONFIDENCE_LABELS, CONFIDENCE_LEVELS, 
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
    "EvidenceError",
    "analyze_gaps",
    "install_d_tools",
    "load_trace_tools",
    "validate_tool_roles",
    "SPEC",
]
