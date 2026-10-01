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
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from .. import interactions as IX
from .. import schema as S
from ..store import Store, StoreError
from ..tools import ROLES
from ..tools import research_tools as RT
from ..tools.base import ToolError, ToolRegistry
from ..agentspec import AgentBrief, AgentSpec
__all__ = [
    "AgentD",
    "EvidenceError",
    "analyze_gaps",
    "install_d_tools",
    "load_trace_tools",
    "validate_tool_roles",
]
class EvidenceError(RuntimeError):
    """证据包不完整（例如问题行不存在）。"""
_C_AUTO: Any = object()
_UNSPECIFIED: Any = object()
CONFIDENCE_LEVELS = ("high", "medium", "low")
CONFIDENCE_LABELS = {"high": "高", "medium": "中", "low": "低"}
def _conf_label(level: str) -> str:
    return f"{CONFIDENCE_LABELS.get(str(level), str(level))}（{level}）"
_NEGATION_MARKERS = IX.NEGATION_MARKERS
_OPPOSITE_PAIRS = IX.OPPOSITE_PAIRS
C_NO_EVIDENCE = "无 C 侧证据"
C_API_MISSING_REASON = "C 未提供该方法（版本不匹配）"
_TOKEN_SPLIT_RE = re.compile(r"[\s，。、；：？！,.;:?!()（）\[\]【】\"'“”‘’/\\|<>《》\-—_+=*&^%$#@~`]+")
_STOPWORDS = frozenset(
    {
        "是否", "能否", "可以", "可能", "以及", "如果", "那么", "为什么", "什么",
        "如何", "怎样", "关系", "问题", "研究", "值得", "之间", "相关", "以及",
        "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
        "does", "how", "what", "why", "which", "can", "could", "into", "than",
    }
)
def _report_field(report: Any, name: str, default: Any = None) -> Any:
    """同时接受"对象"和"dict"两种报告形态。

    为什么需要这一层：设计契约（DESIGN-TOOLS.md §3.5 / §2.2）说
    ``agent_c`` 返回的是 ``AnalysisReport`` 对象，但真的把它落库之后，
    D 从盘上读回来的是 dict（``store.rows("analysis_reports")``）。
    同一个 D 必须能处理两者，否则"从报告行续跑"这条可中断/可续跑的路径就走不通。
    """
    if report is None:
        return default
    if isinstance(report, Mapping):
        return report.get(name, default)
    return getattr(report, name, default)
def _as_report_dict(report: Any) -> dict:
    """把报告对象/字典规整成 dict（只取 D 用得到的字段）。"""
    return {
        "report_id": _report_field(report, "report_id"),
        "kind": _report_field(report, "kind", ""),
        "request": _report_field(report, "request", "") or "",
        "params": dict(_report_field(report, "params", {}) or {}),
        "summary": _report_field(report, "summary", "") or "",
        "payload": dict(_report_field(report, "payload", {}) or {}),
        "warnings": list(_report_field(report, "warnings", []) or []),
        "truncated": bool(_report_field(report, "truncated", False)),
        "markdown_path": _report_field(report, "markdown_path"),
    }
def _digest(text: Any, width: int = 200) -> str:
    """单行化 + 截断。报告里引用原文时用，保证 markdown 表格不被打散。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"
def question_keywords(question: str, extra: Iterable[str] = ()) -> list[str]:
    """从问题文本里抽出用于核实命中数的关键词。

    规则：按标点/空白切分 → 去停用词与单字 → 对较长的中文片段补 2-gram。
    这是"可核实判据"的基础：判据 (a) 说的"关键词命中数为 0"，命中的对象
    就是这里产出的词。
    """
    words: list[str] = []
    for raw in _TOKEN_SPLIT_RE.split(str(question or "")):
        token = raw.strip()
        if len(token) < 2 or token.lower() in _STOPWORDS:
            continue
        if token not in words:
            words.append(token)
    for extra_text in extra:
        token = str(extra_text or "").strip()
        if len(token) >= 2 and token not in words:
            words.append(token)
    # 中文长片段补 2-gram：整段"阿贝尔群与域之间的交换性条件"几乎不可能
    # 逐字出现在某条 quote 里，2-gram 才是有实际召回力的单位。
    grams: list[str] = []
    for token in words:
        if len(token) >= 5 and not re.fullmatch(r"[\x00-\x7f]+", token):
            grams.extend(token[i : i + 2] for i in range(len(token) - 1))
    for g in grams:
        if g not in words:
            words.append(g)
    return words[:40]
def keyword_hits(keywords: Sequence[str], relations: Sequence[Mapping[str, Any]]) -> dict:
    """关键词在关系 ``quote``/``description`` 里的命中统计（判据 a 的中间值）。

    返回值刻意把每个关键词的命中数与命中样例都打出来：
    §3.4 要求"评分函数必须能逐项打印中间值，否则 D 无法判断该不该信"，
    这条判据同理 —— D 的结论必须能被逐项复核。
    """
    per: dict[str, int] = {}
    samples: dict[str, str] = {}
    for kw in keywords:
        n = 0
        sample = ""
        for rel in relations:
            blob = f"{rel.get('quote') or ''}\n{rel.get('description') or ''}"
            if kw and kw in blob:
                n += 1
                if not sample:
                    sample = f"{rel.get('relation_id')}:{_digest(blob, 80)}"
        per[kw] = n
        if sample:
            samples[kw] = sample
    total = sum(per.values())
    hit_kws = [k for k, v in per.items() if v > 0]
    return {
        "per_keyword": per,
        "samples": samples,
        "total": total,
        "hit_keywords": hit_kws,
        "distinct_hit_keywords": len(hit_kws),
        "keyword_count": len(keywords),
    }
def _contains(haystack: str, needle: str) -> bool:
    """按词边界包含判断。转发到 :func:`interactions.contains`（唯一权威实现）。"""
    return IX.contains(haystack, needle)
def _negated(text: str) -> bool:
    """文本里是否出现否定标记。转发到 :func:`interactions.negated`。"""
    return IX.negated(text)
def _opposite_flags(text: str) -> set[tuple[str, str]]:
    """文本命中的"对立词组"。转发到 :func:`interactions.opposite_flags`。"""
    return IX.opposite_flags(text)
def detect_contradictions(relations: Sequence[Mapping[str, Any]]) -> list[dict]:
    """找出互相矛盾的两条关系（§4.4 判据 3）。

    转发到 :func:`interactions.detect_contradictions`（唯一权威实现）：
    判据（同一概念组 + 否定/对立标记不一致）与返回结构都由那里定义，
    本函数不再持有任何自己的判定逻辑。
    """
    return IX.detect_contradictions(relations)
def analyze_gaps(
    relation_ids: Sequence[str],
    relations: Sequence[Mapping[str, Any]],
    *,
    keywords: Sequence[str],
    degree: int,
    degree_threshold: int = 2,
    concept_count: int = 0,
) -> dict:
    """按 §4.4 的三条可核实判据评估"知识是否不足"。

    返回 ``{"insufficient": bool, "criteria": [...], "priority": str, "confidence": str}``
    以及全部中间值（命中数、度数、已验证条数、矛盾对数），使结论可以被逐项复核。

    判据与优先级：

    | 判据 | 条件 | 优先级 | 理由 |
    |---|---|---|---|
    | a 关键词零命中 | 命中关键词数 == 0 | high | 库里完全没谈过这件事，不是"谈得少" |
    | b 度数低且无核验 | degree < 阈值 且 无 ``quote_verified=True`` | medium | 谈过，但既冷门又没原文支撑 |
    | c 内在矛盾 | 存在矛盾关系对 | high | 文献之间真实分歧，最值得研究 |

    ``insufficient`` 只要任一条成立。没有"感觉不够"这一条，
    也没有"关系太少就说不够"这种看上去合理、实则无法反驳的软判据。
    """
    verified = [r for r in relations if r.get("quote_verified") is True]
    hits = keyword_hits(keywords, relations)
    contradictions = detect_contradictions(relations)

    criteria: list[dict] = []
    if hits["distinct_hit_keywords"] == 0 and keywords:
        criteria.append(
            {
                "id": "a_no_keyword_hit",
                "ok": True,
                "priority": "high",
                "detail": (
                    f"关键词 {hits['keyword_count']} 个，在 {len(relations)} 条相关关系的 quote/description 中"
                    f"命中数为 0（逐词命中：{hits['per_keyword']}）"
                ),
            }
        )
    if degree < degree_threshold and not verified:
        criteria.append(
            {
                "id": "b_low_degree_unverified",
                "ok": True,
                "priority": "medium",
                "detail": (
                    f"相关概念度数 {degree} < 阈值 {degree_threshold}，且 {len(relations)} 条关系里"
                    "没有一条 quote_verified=True（连一条有原文支撑的关系都没有）"
                ),
            }
        )
    if contradictions:
        criteria.append(
            {
                "id": "c_contradiction",
                "ok": True,
                "priority": "high",
                "detail": (
                    f"发现 {len(contradictions)} 对互相矛盾的表述："
                    + "；".join(
                        f"{c['relation_ids'][0]} vs {c['relation_ids'][1]}（{'，'.join(c['signals'])}）"
                        for c in contradictions[:3]
                    )
                ),
            }
        )

    if any(c["priority"] == "high" for c in criteria):
        priority = "high"
    elif criteria:
        priority = "medium"
    else:
        priority = "low"

    return {
        "insufficient": bool(criteria),
        "criteria": criteria,
        "priority": priority,
        "confidence": evidence_confidence(
            relations, degree=degree, concept_count=concept_count, contradictions=len(contradictions)
        ),
        "hits": hits,
        "contradictions": contradictions,
        "verified_count": len(verified),
        "degree": degree,
        "degree_threshold": degree_threshold,
    }
def evidence_confidence(
    relations: Sequence[Mapping[str, Any]],
    *,
    degree: int = 0,
    concept_count: int = 0,
    contradictions: int = 0,
) -> str:
    """由可核实的证据量算出置信度上限（§4.5）。

    评分刻意保守：
      + 每条 ``quote_verified=True`` 的关系 +1（有原文支撑是唯一强信号）
      + 度数 >= 3 再加 1（不是孤例）
      + 两个以上概念相关再加 0.5
      - 每条 ``quote_verified=False`` 的关系 -1（引文找不到 = 可疑）
      - 存在矛盾 -0.5（分歧未解决，结论只能是低）
    阈值：>=3 high；>=1.5 medium；否则 low。

    这个函数是上限：``_llm_refine`` 只允许把它调低。
    """
    if not relations:
        return "low"
    score = 0.0
    for r in relations:
        if r.get("quote_verified") is True:
            score += 1.0
        elif r.get("quote_verified") is False:
            score -= 1.0
    if degree >= 3:
        score += 1.0
    if concept_count >= 2:
        score += 0.5
    if contradictions:
        score -= 0.5
    if score >= 3.0:
        return "high"
    if score >= 1.5:
        return "medium"
    return "low"
def _rank(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(level, 0)
def _rank_min(a: str, b: str) -> str:
    """取较低的一档。用于"LLM 不许拔高置信度"这条硬规则。"""
    return a if _rank(a) <= _rank(b) else b
def _fallback_trace_tools(store: Any) -> list[Any]:
    """内置的最小替身：只在 ``tools.trace_tools`` 缺失/注册失败时才被注册。

    这不是"重新实现别人的模块"，而是降级路径：
    - 外部 ``trace_tools`` 缺失或注册失败时，本函数产出的工具才会被注册
      （判断在 :func:`install_d_tools`：注册表里一个 ``trace.*`` 都没有 ⇒ 走降级）；
    - 外部存在且注册成功时，D 走的是真正的溯源工具，本函数的产物一个都不注册；
    - 降级时，D 至少要能把"关系 → 引文/陈述 → 文献"这条 L1/L2 链路走完，
      否则整个 D 循环都无法自检。它返回的数据形状与 DESIGN-TOOLS.md §4.3
      描述的 L1/L2 一致（关系行 + 概念行 + 文献行），不做任何额外推断。

    两条形态上的硬要求（都踩过坑）：
    1. ``roles`` 必须是 ``("C", "D")`` —— 与 ``schema.ROLES`` 逐字一致。
       这三个 spec 原先写的是 ``("agent-C", "agent-D")``，而 ``install_d_tools``
       绕过 ``build_registry`` 的角色断言，于是它们装上了却永远过滤不出来。
    2. 读表失败必须转成 ``ToolError``（见内部 ``_table``）：否则 ``StoreError``
       会逃逸成 ``kind="unexpected"``，"表读不出来"与"表里没有这一行"就分不清了。
    """
    from ..tools.base import spec_from_dataclass_fields, tool

    def _table(name: str) -> list[dict]:
        """读表；失败时抛 ``ToolError`` 而不是把原异常漏出去。

        为什么必须转换：``ToolRegistry.call`` 只把 ``ToolError`` 映射成有类型的
        ``kind="tool_error"``，其余异常一律兜成 ``kind="unexpected"``
        （映射点就是 ``tools.base.ToolRegistry.call`` 里那两支 ``except``）—— 那是"类型信息丢失"的失败，
        报告审计一节只能显示 ``StoreError: ...`` 而说不出这是表读不出来。
        转换之后，"表坏了"与"表里确实没有这一行"在 ``last_tool_errors`` 里
        是两种可区分的记录（三态：读到 / 没读到 / 读不了）。
        """
        try:
            return store.rows(name)
        except StoreError as e:
            raise ToolError(f"读表 {name} 失败：{e}") from e

    @tool(
        "trace.relation",
        "【内置降级替身】按 relation_id 取该关系的逐字表述（quote/description/page_range/status）。",
        spec_from_dataclass_fields("trace.relation", {"relation_id": "string"}, required=("relation_id",)),
        side_effect="read",
        # 角色名必须与 `schema.ROLES` 逐字一致（这里是 "C"/"D"，不是
        # "agent-C"/"agent-D"）。原先写的是带前缀的形态，而 `install_d_tools`
        # 绕过了 `build_registry` 的角色断言 ⇒ `for_role("C")/("D")` 永远拿不到
        # 这三个替身工具（静默少工具）。现在装配期会断言（见 `validate_tool_roles`）。
        roles=("C", "D"),
        tags=("trace", "fallback"),
    )
    def trace_relation(relation_id: str):
        row = next((r for r in _table("relations") if r.get("relation_id") == relation_id), None)
        if row is None:
            return {"found": False, "relation_id": relation_id, "source": "fallback"}
        return {
            "found": True,
            "source": "fallback",
            "relation_id": relation_id,
            "concept_ids": list(row.get("concept_ids") or []),
            "lit_id": row.get("lit_id"),
            "quote": row.get("quote") or "",
            "description": row.get("description") or "",
            "statement": row.get("statement") or "",
            "page_range": row.get("page_range") or {},
            "status": row.get("status"),
            "quote_verified": row.get("quote_verified"),
        }

    @tool(
        "trace.concept",
        "【内置降级替身】按 concept_id 取概念定义 + 它参与的全部关系的表述。",
        spec_from_dataclass_fields("trace.concept", {"concept_id": "string"}, required=("concept_id",)),
        side_effect="read",
        roles=("C", "D"),
        tags=("trace", "fallback"),
    )
    def trace_concept(concept_id: str):
        row = next((c for c in _table("concepts") if c.get("concept_id") == concept_id), None)
        rels = [
            {
                "relation_id": r.get("relation_id"),
                "concept_ids": list(r.get("concept_ids") or []),
                "quote": r.get("quote") or "",
                "description": r.get("description") or "",
                "status": r.get("status"),
                "quote_verified": r.get("quote_verified"),
                "lit_id": r.get("lit_id"),
            }
            for r in _table("relations")
            if concept_id in (r.get("concept_ids") or [])
        ]
        if row is None and not rels:
            return {"found": False, "concept_id": concept_id, "source": "fallback"}
        return {
            "found": True,
            "source": "fallback",
            "concept_id": concept_id,
            "name": (row or {}).get("name") or "",
            "definition": (row or {}).get("definition") or "",
            "related_concepts": list((row or {}).get("related_concepts") or []),
            "aliases": list((row or {}).get("aliases") or []),
            "relations": rels,
            "degree": len(rels),
        }

    @tool(
        "trace.literature",
        "【内置降级替身】按 lit_id 取文献元数据与本地文件存在的**事实**（不读正文，正文由 K 的 L3 工具负责）。",
        spec_from_dataclass_fields("trace.literature", {"lit_id": "string"}, required=("lit_id",)),
        side_effect="read",
        roles=("C", "D"),
        tags=("trace", "fallback"),
    )
    def trace_literature(lit_id: str):
        row = next((r for r in _table("literature") if r.get("lit_id") == lit_id), None)
        if row is None:
            return {"found": False, "lit_id": lit_id, "source": "fallback"}
        path = None
        try:
            path = store.library_path(row.get("path"))
        except StoreError:
            path = None
        return {
            "found": True,
            "source": "fallback",
            "lit_id": lit_id,
            "title": row.get("title") or "",
            "type": row.get("type"),
            "year": row.get("year"),
            "doi": row.get("doi"),
            "processed": bool(row.get("processed")),
            "download_status": (row.get("download") or {}).get("status"),
            "file_exists": bool(path and path.exists()),
            # 刻意不返回正文：内置替身不做正文抽取（那是 L3 的贵操作），
            # 宁可在报告里写"未下钻正文"，也不假装读过。
            "text_available": False,
        }

    return [trace_relation, trace_concept, trace_literature]
def load_trace_tools() -> Any | None:
    """惰性导入 ``tools.trace_tools``。

    为什么惰性：该模块由别人同时编写，D 必须能在它还不存在时被导入、
    doctest、自检、跑端到端。用一个模块级 try/except 换来的代价只是
    "用到时才知道缺" —— 而那时我们有明确的降级路径。
    """
    try:
        from ..tools import trace_tools as _tt  # type: ignore[import-not-found]
    except Exception:
        return None
    return _tt
def validate_tool_roles(reg: ToolRegistry) -> None:
    """装配期断言：注册表里每个 spec 声明的角色都必须在 :data:`ROLES` 里。

    ## 为什么要把这段校验复制到 D 的装配路径上（而不是"再写一份判据"）

    判据本身只有一份，就是 :data:`ROLES`（定义在 ``schema.ROLES``，
    ``tools/__init__.py`` 里那句 ``from ..schema import ROLES`` 只是把它引过来）。
    本函数做的是用同一份判据在第二个装配入口上执行同一条断言：

    ``tools/__init__.py`` 的 ``build_registry`` 已经做过这件事，
    但 :func:`install_d_tools` 不走 ``build_registry``（它自己
    ``ToolRegistry(name="agent-D")`` + ``register_function``），于是那段断言
    在这里完全缺席。后果是实测过的：``_fallback_trace_tools`` 的三个 spec
    写成 ``roles=("agent-C", "agent-D")``，角色名非法却一路注册成功，
    ``for_role("C")/("D")`` 永远拿不到它们 —— 静默少工具，
    正是 ``build_registry`` 里那段历史 bug 注释（``tools/__init__.py``，
    后来由 ``tools.base.ToolRegistry._reject_unknown_roles`` 把判据前移到注册期）
    记的同型复发。

    这里刻意只写符号名、不写行号：行号在本仓库的并行开发下几十分钟就会漂，
    而符号名可被断言存在（``.noai-paths`` 的维护纪律：
    理由里用反引号写符号名、刻意不写 ``文件:行号``）。

    为什么不能"什么都不做、只改对角色名"：那样只是修好了这一次的拼写。
    判据必须在每个装配入口都执行，否则下一个改这里的会重犯。
    为什么不能改 ``tools/__init__.py`` 把这段抽成公开函数：该文件不在本次
    可改范围内（见报告"要改但不能改"一节）。因此这里直接复用
    ``ROLES`` 这一唯一判据 + ``ToolError`` 这一唯一异常类型，
    错误文案与 ``build_registry`` 保持一致（同一个判据、同一句话）。

    Raises
    ------
    ToolError
        存在角色名不在 ``ROLES`` 里的工具；错误里逐条列出"工具名 → 非法角色"。
    """
    bad_roles: dict[str, list[str]] = {}
    for spec in reg._specs.values():
        unknown = [r for r in spec.roles if r not in ROLES]
        if unknown:
            bad_roles[spec.name] = unknown
    if bad_roles:
        raise ToolError(
            f"以下工具声明了不在 ROLES{ROLES} 里的角色：{bad_roles}。"
            "角色名是跨模块约定，拼法不一致会让 for_role() 静默漏掉这些工具。"
        )
def install_d_tools(
    store: Store,
    *,
    registry: ToolRegistry | None = None,
    trace_tools: Any | None = None,
) -> ToolRegistry:
    """装配 D 的工具栏：研究工具 + 溯源工具（外部优先，缺失时用内置替身）。

    返回装配好的 ``ToolRegistry``。D 只通过 ``registry.call(...)`` 使用这些
    工具（而不是直接 import 函数），因此：
    - 外部工具还没写好时，D 不会 ImportError；
    - 未来把工具换成 LLM 可调用的形态时，D 一行都不用改。

    装配完成后必经 :func:`validate_tool_roles`：角色名拼错必须在装配期炸，
    不能变成"装是装上了，按角色过滤时静默少几个"。注意这条校验也覆盖
    ``registry=`` 注入的注册表（那正是外部 ``trace_tools`` 的入口）。

    Raises
    ------
    ToolError
        任一已注册工具声明了非法角色名（见 :func:`validate_tool_roles`）。
    """
    reg = registry if registry is not None else ToolRegistry(name="agent-D")
    RT.install(reg, store)
    # 猜想台账的产出面（`draft/30` §T3-P3）：T1 只落了数据面与判据，
    # 提出/检验/否证/升格这些语义动作在这里才接线 —— 没有它，
    # 验收 P7 的第 4 张表（猜想表）没有任何数据可渲染。
    from ..tools import conjecture_tools as CT

    CT.register(reg, store=store, actor="agent-D")

    tt = trace_tools if trace_tools is not None else load_trace_tools()
    last: Exception | None = None
    if tt is not None:
        # 外部 `trace_tools.register` 目前是 `register(registry, *, store=None, graph=None)`
        # —— store 是仅关键字参数。所以必须按关键字传：位置传会 TypeError。
        # 两种形态都试一遍是为了兼容对方后续可能的签名调整（register(registry, store)）。
        for call in (lambda f: f(reg, store=store), lambda f: f(reg, store)):
            fn = getattr(tt, "register", None)
            if not callable(fn):
                last = TypeError(f"{type(tt).__name__} 没有可调用的 register()")
                break
            try:
                call(fn)
                break
            except TypeError as e:
                last = e
                # 只吞"签名不匹配"这一种 TypeError：如果 register 已经把工具注册进去了
                # 才报别的 TypeError，重试另一种形态会撞上"工具名重复"，所以先看结果。
                if any(n.startswith("trace.") for n in reg.names()):
                    break
                continue
            except Exception as e:  # 对方模块自身的 bug：不阻断 D，走降级
                last = e
                break
    if not any(n.startswith("trace.") for n in reg.names()):
        # 外部缺失 / 形态不匹配 => 注册内置降级替身，保证 D 至少能走 L1/L2
        for fn in _fallback_trace_tools(store):
            name = getattr(getattr(fn, "__tool_spec__", None), "name", "")
            if name and name not in reg:
                reg.register_function(fn)
        # 降级是可观测的：原因记在 registry 上，报告与自检都会打印它，
        # 而不是悄悄少用一部分能力（"没做"和"做了但没结果"必须能区分）。
        setattr(reg, "trace_fallback_reason", f"{type(last).__name__}: {last}" if last else "trace_tools 不可用")
    # 放在最后：降级替身也要过校验（它们曾经正是出错的那一批）。
    validate_tool_roles(reg)
    # ---- 绑定角色（`P-14`）：这张注册表代表 D，`AgentD._call` 的每次调用都会被
    # 判一次"D 拿不拿得到这个工具"（`research.*` 是 D 的，`graph.*` / `trace.*` 是 C/D 共用的）。
    # 不绑的话那些调用会全部以"调用方没有声明角色"失败 —— 只读约束的刀不许靠"没写"来拿，
    # 但也不能因为"没写"把 D 自己的手一起砍掉。
    if reg.bound_role is None:
        reg.bound_role = "D"
    return reg
from ..specs.d import SPEC  # noqa: E402,F401

