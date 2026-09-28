"""智能体 D：研究循环。

设计基线：``test/test1/DESIGN-TOOLS.md`` §4（D 的状态机 / 溯源三级 / 知识不足判据 /
报告结构）与 §5（编排里 D 的位置）。

## D 到底在做什么

D 的核心不是"生成文本"，而是管理一个循环（§4.1）：

    读 C 报告 → 提取候选问题 → 按代号溯源 → 评估证据是否足够
        ├─ 足够 → 写研究报告
        └─ 不足 → 向 A 提交查询请求（记入等待集）
                    → A 检索 → B 消化 → D 复查（poll）→ 回到"评估"

## 四个不可让步的设计（每一条都有具体的失败模式在背后）

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

## LLM 的位置

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

from . import interactions as IX
from . import schema as S
from .store import Store, StoreError
from .tools import ROLES
from .tools import research_tools as RT
from .tools.base import ToolError, ToolRegistry

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


# ---------------------------------------------------------------- 哨兵

#: ``AgentD(c=...)`` 的默认值哨兵：不传 = "惰性装配 AgentC"（见 :meth:`AgentD._resolve_c`）。
#: 用哨兵而不是 ``None``：``None`` 必须是"明确禁用 C 查询"这一独立语义
#: （"没接线"与"被关掉"在报告里要能分开写）。
_C_AUTO: Any = object()

#: ``AgentD.poll(relations=...)`` 的默认值哨兵。
#: ``_UNSPECIFIED`` = 自己去关系表读；显式传 ``None`` = "调用方无法提供关系快照"，
#: 于是证据相关性判据得到 ``new_relations=None`` ⇒ ``checked=False``。
#: 这与 ``interactions.check_conflict(existing_relations=None)`` 的三态口径完全一致。
_UNSPECIFIED: Any = object()


# ---------------------------------------------------------------- 常量 / 受控词表

#: 置信度三档（§4.5 的 high/medium/low）。
CONFIDENCE_LEVELS = ("high", "medium", "low")

#: 置信度的中文标签。报告一律用中文档位显示：§4.5 的原话是
#: "置信度低必须写『低』，不得为了好看而拔高"。英文枚举名（low/medium/high）
#: 是给机器用的受控词表，出现在给人读的报告里既不符合要求，
#: 也让人需要额外翻译一次才能确认它没被拔高。
CONFIDENCE_LABELS = {"high": "高", "medium": "中", "low": "低"}


def _conf_label(level: str) -> str:
    return f"{CONFIDENCE_LABELS.get(str(level), str(level))}（{level}）"

#: 矛盾检测用的"否定/对立"标记。
#:
#: 本常量只是 :data:`interactions.NEGATION_MARKERS` 的别名（同一份对象的引用）。
#: 唯一权威实现已经移到 ``interactions.py``，理由见模块 docstring 末节：
#: I6 要求 B 在写入期用同一份判据判矛盾，两份实现必然漂移，而漂移是静默的。
_NEGATION_MARKERS = IX.NEGATION_MARKERS

#: 明确的对立词组 ``(肯定式, 否定式)``。同样只是 :data:`interactions.OPPOSITE_PAIRS` 的别名。
_OPPOSITE_PAIRS = IX.OPPOSITE_PAIRS

#: I1：本次研究没有任何一条 C 查询成功时的统一标注。必须出现在报告里 ——
#: 上一版 D 因为"没接工具"静默拿到空证据，却把"查不到"写成了一条听起来很合理的
#: 研究发现。所以"无 C 侧证据"这件事本身要写出来，且结论不许用确定语气。
C_NO_EVIDENCE = "无 C 侧证据"

#: C 未提供某个服务方法时的理由（I1 的三态）。与"查了、没有结果"严格区分。
C_API_MISSING_REASON = "C 未提供该方法（版本不匹配）"

#: 关键词切分：中英文都按"标点/空白"切，再过滤无意义的短词。
#: 刻意不引分词库（不引入新依赖），代价是中文会被切成较长的片段；
#: 因此 :func:`question_keywords` 会额外产出 2-gram 作为补充召回。
_TOKEN_SPLIT_RE = re.compile(r"[\s，。、；：？！,.;:?!()（）\[\]【】\"'“”‘’/\\|<>《》\-—_+=*&^%$#@~`]+")

#: 停用词：这些词在任何研究问题里都会出现，拿它们算"命中"等于没算。
_STOPWORDS = frozenset(
    {
        "是否", "能否", "可以", "可能", "以及", "如果", "那么", "为什么", "什么",
        "如何", "怎样", "关系", "问题", "研究", "值得", "之间", "相关", "以及",
        "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
        "does", "how", "what", "why", "which", "can", "could", "into", "than",
    }
)


# ---------------------------------------------------------------- 报告对象适配


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


# ---------------------------------------------------------------- 关键词与命中


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


# ---------------------------------------------------------------- 判据 3：矛盾（委托 interactions）
#
# 以下四个函数的唯一权威实现已经移到 `interactions.py`，这里只做转发。
#
# 为什么必须只有一份："矛盾"这个判据现在有两个使用者 —— D 的事后分析（判据 3）
# 与 B 的写入期闸门（I6，B 在自己事务里问"这条新关系与已有的是否矛盾"）。
# 如果各写一份 `_negated`，"写入期认为不矛盾、事后 C 认为矛盾"就会变成一个
# 没有报错的静默分裂：矛盾检测恒为假或恒为真，而没有任何地方会报错。
# 保留同名函数是为了不破坏既有调用点与既有测试；函数体一律只转发。


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


# ---------------------------------------------------------------- 判据总装


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


# ---------------------------------------------------------------- 内置最小替身


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
    from .tools.base import spec_from_dataclass_fields, tool

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
        from .tools import trace_tools as _tt  # type: ignore[import-not-found]
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
    from .tools import conjecture_tools as CT

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


# ---------------------------------------------------------------- AgentD


class AgentD:
    """研究智能体。§4.1 的状态机在这里被实现成一组可单独调用的方法。

    每个方法都可以被独立调用与单测（``ingest`` / ``trace_question`` /
    ``assess`` / ``submit_gaps`` / ``poll`` / ``research`` / ``write_report``），
    ``run_round`` 只是把它们按状态机串起来。这样"流程可中断、可续跑"才有可能：
    中断之后可以从任意一步接着跑，而不是只能从头再跑一遍。
    """

    def __init__(
        self,
        store: Store,
        config: Mapping[str, Any] | None = None,
        actor: str = "agent-D",
        tools: ToolRegistry | None = None,
        llm: Any | None = None,
        *,
        trace_tools: Any | None = None,
        c: Any = _C_AUTO,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        self.llm = llm
        #: 工具栏。要么外部注入，要么这里装配（含降级替身）。
        self.tools = tools if tools is not None else install_d_tools(self.store, trace_tools=trace_tools)
        # ---- 绑定角色（`P-14`）：`AgentD._call` 的每次调用都要能回答"这次是谁在调"。
        # 注入进来的注册表（测试与调用方都用这条路径）同样要绑 —— 绑不上就等于
        # D 的每一次工具调用都会以"调用方没有声明角色"被拒，那不是"更安全"，
        # 那是把 D 的手砍掉了。
        if self.tools.bound_role is None:
            self.tools.bound_role = "D"

        # ---- 阈值全部来自 config，不写死在代码里（与 config.yaml 的既有做法一致）
        self.max_questions = int(self.cfg.get("max_questions", 5))  # §8 待决问题 2
        self.degree_threshold = int(self.cfg.get("degree_threshold", 2))
        self.max_requests_per_question = int(self.cfg.get("max_requests_per_question", 2))  # §8 待决问题 3
        self.max_total_requests = int(self.cfg.get("max_total_requests", 20))  # §8 待决问题 3
        self.max_l3_lits = int(self.cfg.get("max_l3_lits", 3))
        #: 报告里 L2 上下文最多展开几条。链条自身（L1）不设上限（它就是重点），
        #: 但上下文必须限量：一个枢纽概念能牵出十几条邻居关系，全列出来会把
        #: 链条淹掉（读者要顺着链读，不是拿到一堆）。截断后报告会写"另有 N 条未展开"。
        self.max_l2_context = int(self.cfg.get("max_l2_context", 6))
        #: L3 是否强制下钻（默认关闭：L3 贵，只在证据互相矛盾或"要写结论但没有一条
        #: 可核验的引文"时才下钻 —— 这正是 §4.3 说的"按需"）。
        self.force_l3 = bool(self.cfg.get("force_l3", False))
        self.reports_subdir = str(self.cfg.get("reports_subdir", "reports"))
        #: 每份 C 报告最多提几个问题；报告 kind -> 允许提取的 kind（便于只跑一类）
        self.enabled_kinds = tuple(self.cfg.get("enabled_kinds") or S.REPORT_KINDS)
        #: ingest 去重开关：同一 origin 已经提过就不再提（跨轮次幂等）
        self.dedup_by_origin = bool(self.cfg.get("dedup_by_origin", True))
        #: ingest 是否从 C 报告/C 服务读矛盾（I2）。关掉它 = 只提取缺口类问题。
        self.ingest_contradictions = bool(self.cfg.get("ingest_contradictions", True))

        # ---- I2 的终止条件（它们必须是可配置的上限，而不是"跑到收敛为止"）
        #: 单条矛盾最多追问几轮。用尽后不是继续，而是标 `persistent` 交人复核。
        self.max_rounds_per_contradiction = int(
            self.cfg.get("max_rounds_per_contradiction", IX.DEFAULTS["max_rounds_per_contradiction"])
        )
        #: 全局最多提交几条矛盾驱动的检索请求（统计口径见 :meth:`_contradiction_budget`）。
        self.max_contradiction_requests = int(
            self.cfg.get("max_contradiction_requests", IX.DEFAULTS["max_contradiction_requests"])
        )
        #: 单个问题最多向 C 点几次菜（I1）。C 是服务，不等于可以无限点单。
        self.max_c_neighbor_queries = int(self.cfg.get("max_c_neighbor_queries", 2))
        self.max_c_pair_queries = int(self.cfg.get("max_c_pair_queries", 2))
        self.max_c_contradictions = int(self.cfg.get("max_c_contradictions", 20))
        #: 单轮最多裁决几条矛盾问题（防"一份报告带进来 20 对矛盾"时一轮打出 20 条请求）。
        self.max_adjudications_per_round = int(self.cfg.get("max_adjudications_per_round", 10))

        # ---- I1：C 服务（点菜用的那只手）
        self.c: Any = None
        #: 工具/事务失败记录（报告审计一节会打印）。在这里就初始化：
        #: 早先它只在 `trace_question` 里惰性建立，于是任何"先失败、后溯源"的路径
        #: （例如 `adjudicate` 里的异常分支）都会以 AttributeError 收场 ——
        #: 记录失败的代码本身炸掉，比失败更坏。
        self.last_tool_errors: list[dict[str, Any]] = []
        #: C 的接线方式与理由（三态：injected / auto / auto_failed / disabled）。
        #: 它必须可审计：报告要能说清"本轮到底有没有能力问 C"。
        self.c_wiring: dict[str, Any] = {}
        self._resolve_c(c)

    # ------------------------------------------------------------ 小工具

    def _stamp(self) -> str:
        return S.now_iso()

    def _reports_dir(self) -> Path:
        return Path(self.store.root) / self.reports_subdir

    def _call(self, name: str, **params: Any) -> Any:
        """调工具并解开 ``ToolResult``；失败返回 ``None`` 并记下原因。

        为什么把失败"吃掉"并返回 None：D 的循环不该因为一次工具失败而中断
        （与 ``ToolRegistry`` 的设计一致）。失败原因进 ``self.last_tool_errors``，
        最终会出现在报告的"审计"一节里，而不是被静默吞掉。
        """
        res = self.tools.call(name, **params)
        if not res.ok:
            self.last_tool_errors.append({"tool": name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data

    # ------------------------------------------------------------ [0b] 猜想台账

    def register_conjecture(self, **params: Any) -> dict:
        """登记或更新一条猜想（转发 `conjecture.register_conjecture`；依据 `draft/31` P7 第 4 张表）。

        ## 为什么失败要抛，而不是像 `_call` 那样返回 `None`

        D 的读路径（`_call`）把失败吃掉是合理的：一次查不到不该中断整轮研究，
        原因落在 `self.last_tool_errors` 里。但写路径不一样：返回 `None` 会让
        `Conductor._end_from_payload` 记成 `outcome="ok"` 而 `payload=None` ——
        台账上看起来"这一步做成了"，而库里一行都没有。这正是本项目最忌的形态
        （"假装跑通并返回空"）。所以这里把失败原样抛出去，让终态是 `failed`。

        ## 三态

        `conjecture_id` 给了但库里没有 ⇒ 抛（不许静默新建一条重复的猜想）。
        `None` = 调用方没提这个字段 ⇒ 保留库里已有的值（更新语义见 `conjecture_tools`）。
        """
        res = self.tools.call("conjecture.register_conjecture", **params)
        if not res.ok:
            # 失败同时进 `last_tool_errors`（报告里的审计一节读它）与异常，
            # 两条路都要：前者让"这一轮 D 犯过什么错"可查，后者保证终态是 failed。
            self.last_tool_errors.append(
                {"tool": "conjecture.register_conjecture", "error": res.error,
                 "kind": res.meta.get("kind")}
            )
            raise EvidenceError(
                f"conjecture.register_conjecture 失败（kind={res.meta.get('kind')}）：{res.error}"
            )
        return dict(res.data)

    # ------------------------------------------------------------ [0] I1：C 服务接线

    def _resolve_c(self, c: Any) -> None:
        """决定 D 用哪个 C 服务（I1），并把"怎么接上的"写进 ``self.c_wiring``。

        三种来源，每一种都留下可审计的痕迹（三态纪律）：

        - 显式注入实例 ⇒ ``mode="injected"``；
        - 显式传 ``None`` ⇒ ``mode="disabled"``，之后所有 C 查询都记
          ``checked=False`` + 理由"D 未接入 C 服务"（这是"没接线"，不是"查了没有"）；
        - 默认哨兵 ⇒ ``mode="auto"``，惰性装配 ``agent_c.AgentC``。
          为什么不硬依赖 pipeline 把 C 传进来：C 与 D 是并行开发的模块，
          D 必须能在 C 缺席（或版本不匹配）时照常跑完，并且在报告里说清
          它这轮其实没有能力问 C。自动装配失败时记 ``mode="auto_failed"``。
        """
        if c is _C_AUTO:
            try:
                from .agent_c import AgentC  # 惰性导入：C 模块缺席时 D 依然可用
            except Exception as e:
                self.c = None
                self.c_wiring = {"mode": "auto_failed", "reason": f"无法导入 agent_c：{type(e).__name__}: {e}"}
                return
            sub = self.cfg.get("agent_c")
            try:
                self.c = AgentC(self.store, config=dict(sub) if isinstance(sub, Mapping) else {})
            except Exception as e:
                self.c = None
                self.c_wiring = {"mode": "auto_failed", "reason": f"构造 AgentC 失败：{type(e).__name__}: {e}"}
                return
            self.c_wiring = {
                "mode": "auto",
                "reason": "调用方未注入 C 服务，D 自行装配 agent_c.AgentC（只读服务，不写盘）",
                "c_type": type(self.c).__name__,
            }
            return
        self.c = c
        if c is None:
            self.c_wiring = {
                "mode": "disabled",
                "reason": "显式传入 c=None ⇒ 本轮不做任何 C 查询（所有记录为 checked=False，报告会标注「无 C 侧证据」）",
            }
        else:
            self.c_wiring = {"mode": "injected", "reason": f"使用调用方注入的 C 服务：{type(c).__name__}"}

    def _c_call(self, api: str, **params: Any) -> dict:
        """防御式调用 C 的服务方法（I1）。

        ## 为什么必须是防御式的

        C 的四个只读服务方法由另一个并行开发的任务提供，D 现在既不能假定
        它们存在，也不能假定签名与冻结契约完全一致。三种情况必须给出三种不同的
        记录，因为它们对读者的含义完全不同：

        ========================================  ==========================================
        情况                                       记录
        ========================================  ==========================================
        拿不到方法（版本不匹配）                    ``checked=False`` + "C 未提供该方法"
        方法抛异常                                  ``checked=False`` + 异常文本（报告里可见）
        返回值不是 dict / 缺少 ``checked`` 三态位    ``checked=False`` + 理由
        ========================================  ==========================================

        绝对不允许把"没调用成功"静默当成"没有结果"。这是本项目最痛的历史
        缺陷：D 曾因"没接工具"而静默拿到空证据，却把"查不到"写成了一条听起来
        很合理的研究发现。失败路径在这里一律返回带 reason 的记录。
        """
        c = getattr(self, "c", None)
        if c is None:
            return {
                "checked": False,
                "reason": "D 未接入 C 服务（c=None 或装配失败）⇒ **没查**，不是查了没有",
            }
        fn = getattr(c, api, None)
        if fn is None or not callable(fn):
            return {"checked": False, "reason": C_API_MISSING_REASON}
        try:
            data = fn(**params)
        except Exception as e:  # noqa: BLE001 - 对方模块的任何异常都不能打断 D 的循环
            return {"checked": False, "reason": f"{type(e).__name__}: {e}"}
        if not isinstance(data, Mapping):
            return {
                "checked": False,
                "reason": f"C.{api} 返回 {type(data).__name__}，不是冻结契约要求的 dict ⇒ 视为没查成功",
            }
        out = dict(data)
        if not out.get("checked"):
            # C 自己说"没查"，或返回值根本没有三态位 ⇒ 保持"没查"，并保证理由非空。
            if not str(out.get("reason") or "").strip():
                out["reason"] = f"C.{api} 返回 checked={out.get('checked')!r} 且未给理由 ⇒ 视为没查成功"
        return out

    @staticmethod
    def _c_digest(api: str, res: Mapping[str, Any]) -> dict:
        """把 C 的返回值压成"看得出实际得到了什么"的摘要（I1）。

        摘要不许只写一个布尔：只有布尔时，"查了、什么也没有"与"没查"
        在报告里长得一模一样，读者无法判断该不该信这个结论。所以每种服务都要
        给出可核对的落点（关系代号、节点代号、矛盾对数与配对）。
        """
        if api == "neighbors":
            nodes = [n for n in (res.get("nodes") or []) if isinstance(n, Mapping)]
            return {
                "concept_id": res.get("concept_id"),
                "depth": res.get("depth"),
                "node_count": len(nodes),
                "nodes": [str(n.get("concept_id")) for n in nodes][:20],
                "edge_count": len(res.get("edges") or []),
                "empty": bool(res.get("empty")),
            }
        if api == "relations_between":
            rids = [str(x) for x in (res.get("relation_ids") or [])]
            return {
                "a": res.get("a"),
                "b": res.get("b"),
                "relation_ids": rids,
                "relation_count": len(rids),
                "empty": bool(res.get("empty")),
            }
        if api == "contradictions":
            cs = [c for c in (res.get("contradictions") or []) if isinstance(c, Mapping)]
            return {
                "scope": res.get("scope"),
                "scanned": res.get("scanned"),
                "contradiction_count": len(cs),
                "relation_pairs": [list(c.get("relation_ids") or []) for c in cs][:10],
                "method": res.get("method"),
            }
        if api == "structural_duplicates":
            cs = [c for c in (res.get("candidates") or []) if isinstance(c, Mapping)]
            return {
                "candidate_count": len(cs),
                "concept_pairs": [list(c.get("concept_ids") or []) for c in cs][:10],
            }
        return {"keys": sorted(str(k) for k in res.keys())[:12]}

    def _c_record(self, api: str, params: Mapping[str, Any], res: Mapping[str, Any]) -> dict:
        """把一次 C 调用规整成证据记录 ``{api, params, checked, truncated, digest, reason}``。

        ``checked`` 严格照抄 C 的三态位（缺失即视为没查成功，而不是乐观地当
        成 True）：一个"乐观默认"会把版本不匹配的 C 变成"查过了、什么都没有"。
        """
        checked = bool(res.get("checked"))
        truncated = res.get("truncated")
        if truncated is not None:
            truncated = bool(truncated)
        reason = str(res.get("reason") or "").strip()
        if not checked and not reason:
            reason = f"C.{api} 未成功返回且未给理由 ⇒ 视为没查（不是'查了没有'）"
        rec: dict[str, Any] = {
            "api": api,
            "params": dict(params),
            "checked": checked,
            "truncated": truncated,
            "digest": self._c_digest(api, res) if checked else None,
            "reason": reason,
        }
        if not checked:
            rec["failure"] = True  # 让报告能一眼筛出"这轮没问到"
        return rec

    @staticmethod
    def _c_summary(queries: Sequence[Mapping[str, Any]]) -> dict:
        """C 查询的三态汇总（I1）。

        ``any_success`` 为 False 时，基于该问题产生的结论必须标注
        「无 C 侧证据」并放弃确定语气（见 :meth:`_apply_c_evidence_caveat`）。
        """
        ok = [q for q in queries if q.get("checked")]
        failed = [q for q in queries if not q.get("checked")]
        return {
            "attempted": len(queries),
            "ok": len(ok),
            "failed": len(failed),
            "any_success": bool(ok),
            "apis": [str(q.get("api")) for q in queries],
            "failures": [{"api": q.get("api"), "reason": q.get("reason")} for q in failed],
        }

    def probe_c(self, qid: str, qrow: Mapping[str, Any] | None = None) -> list[dict]:
        """I1：为某个研究问题现场推导参数并向 C 点菜（而不是吃套餐）。

        ## 参数从哪来

        全部由该问题自己的 ``related_concept_ids`` / ``related_relation_ids``
        推导，绝不照抄报告里已有的结果：

        - ``neighbors(concept_id)``：焦点是该问题的概念（最多
          ``max_c_neighbor_queries`` 个）；
        - ``relations_between(a, b)``：该问题概念的两两组合（最多
          ``max_c_pair_queries`` 对）；
        - ``contradictions(relation_ids=...)``：范围是该问题引用的关系。
          没有关系代号时传 ``relation_ids=None``（= C 的全图范围，参数里显式为
          None，不假装"我限定过范围"）。

        报告是上一次分析的快照，而这个问题的当下需要可能与那次分析的 kind 完全
        不同 —— 这正是"让 D 能点菜，把 C 从批处理变成服务"的意义（§1 I1）。

        查询次数有界：C 是服务，不等于可以无限点单；每个问题最多几次，
        否则 D 的循环会被自己的查询拖住（§1 I1 的终止条件）。
        """
        if qrow is None:
            qrow = next(
                (r for r in self.store.rows("research_questions") if str(r.get("question_id")) == str(qid)), None
            ) or {}
        cids = [str(x) for x in (qrow.get("related_concept_ids") or []) if x]
        rids = sorted({str(x) for x in (qrow.get("related_relation_ids") or []) if x})
        out: list[dict] = []

        for cid in cids[: self.max_c_neighbor_queries]:
            params = {"concept_id": cid, "depth": 1}
            out.append(self._c_record("neighbors", params, self._c_call("neighbors", **params)))

        pairs: list[tuple[str, str]] = []
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                pairs.append((cids[i], cids[j]))
                if len(pairs) >= self.max_c_pair_queries:
                    break
            if len(pairs) >= self.max_c_pair_queries:
                break
        for a, b in pairs:
            params = {"a": a, "b": b, "include_inactive": True}
            out.append(self._c_record("relations_between", params, self._c_call("relations_between", **params)))

        cparams = {"relation_ids": rids or None, "limit": self.max_c_contradictions}
        out.append(self._c_record("contradictions", cparams, self._c_call("contradictions", **cparams)))
        return out

    # ------------------------------------------------------------ [1] 提取候选问题

    def _candidates_from(self, report: dict) -> list[dict]:
        """从 ``report.payload`` 里提取候选问题（确定性 + 可解释）。

        ## 假设的 payload 形状（按契约读取，全部用 ``.get`` 容错）

        与 ``agent_c`` 当前实现核对过（字段名以它为准，未命中的别名一并兼容）：

        - ``hottest``：``payload["entries"] = [{"concept_id","name","occurrences",
          "relation_count","group_count","degree","representative_relations":[...]}]``；
        - ``paths``：``payload["paths"] = [{"concept_path": [...], "relation_chain": [...],
          "hops": N, "level": "high|medium|low", "score": 3.4, "score_breakdown": {...}}]``
          —— 注意链字段叫 relation_chain（旧别名 ``relation_path`` 也认）；
        - ``cold``：``payload["entries"] = [{"concept_id","name","degree","undervalued": bool,
          "relations_to_hot": [{"relation_id","weak_points": 0|1|2,"weak_score": 0.5,...}]}]``，
          ``undervalued is True``（或 ``relations_to_hot`` 里有 ``weak_points == 0`` 的）
          即"冷门但连接强"；
        - ``gaps``：``payload["candidate_gaps"] = [{"concept_ids": [...],
          "related_relation_ids": [...], "positive_signals": [...], "reason": "...",
          "confidence": "..."}]``。

        字段名不符时退化为"就地找代号数组"，不会因为形状变化而抛异常 ——
        C 与 D 是并行开发的，D 必须能容忍对方的小幅字段改名；容错的代价是
        可能少提几个问题（可观测：报告的"候选提炼"一节会写明 skipped 原因）。
        """
        kind = str(report.get("kind") or "")
        payload = report.get("payload") or {}
        rid = str(report.get("report_id") or "????")
        out: list[dict] = []

        def _entries(*names: str) -> list:
            """按候选键名依次取第一个非空列表（兼容字段改名）。"""
            for n in names:
                v = payload.get(n)
                if isinstance(v, list) and v:
                    return v
            return []

        if kind == "hottest":
            concepts = _entries("entries", "concepts", "top_concepts", "hot")[:3]
            top = [c for c in concepts if isinstance(c, Mapping)]
            cids = [str(c.get("concept_id") or c.get("id") or "") for c in top]
            cids = [c for c in cids if S.is_valid_id(c)]
            names = [str(c.get("name") or cid) for c, cid in zip(top, cids)]
            if cids:
                out.append(
                    {
                        "kind": "hottest",
                        "origin": f"C:hottest:{rid}:" + ",".join(cids),
                        "question": f"最热门的 {len(cids)} 个概念（{'、'.join(names)}）为何成为关系网络的枢纽？"
                        "它们之间的联结是否构成一个可检验的共同机制？",
                        "related_concept_ids": cids,
                        "related_relation_ids": self._relation_ids_touching(cids),
                        "seed_names": names,
                        "priority": "medium",
                        "why": f"C 报告 {rid} 统计出这些概念的出现次数最高："
                        + "、".join(
                            f"{n}(occurrences={c.get('occurrences')},relation_count={c.get('relation_count')})"
                            for n, c in zip(names, top)
                        ),
                    }
                )

        elif kind == "paths":
            paths = _entries("paths")
            high = [p for p in paths if isinstance(p, Mapping) and str(p.get("level")) in ("high", "medium")]
            for p in high[:3]:
                cpath = [str(x) for x in (p.get("concept_path") or [])]
                rpath = [str(x) for x in (p.get("relation_chain") or p.get("relation_path") or [])]
                if len(cpath) < 2:
                    continue
                chain = "->".join(rpath) if rpath else "-"
                # 概念名优先用 C 已经翻译好的（口径以 C 为准），缺失再本地查
                cnames = [str(x) for x in (p.get("concept_names") or [])]
                names = cnames if len(cnames) == len(cpath) else [self._concept_name(c) for c in cpath]
                out.append(
                    {
                        "kind": "paths",
                        "origin": f"C:paths:{rid}:" + chain,
                        "question": f"从「{names[0]}」到「{names[-1]}」经由关系链 [{chain}] 的推导是否成立？"
                        "该链条的每一步是否都有原文支撑、能否被反例削弱？",
                        "related_concept_ids": [c for c in cpath if S.is_valid_id(c)],
                        "related_relation_ids": [r for r in rpath if S.is_valid_id(r)],
                        "seed_names": names,
                        "priority": "high" if str(p.get("level")) == "high" else "medium",
                        "why": f"C 报告 {rid} 判定该路径信息量为 {p.get('level')}"
                        f"（score={p.get('score')}，breakdown={p.get('score_breakdown')}，hops={p.get('hops')}）",
                    }
                )

        elif kind == "cold":
            concepts = _entries("entries", "concepts", "cold_concepts")
            selected: list[tuple[Mapping, list]] = []
            for c in concepts:
                if not isinstance(c, Mapping):
                    continue
                links = list(c.get("strong_links") or c.get("strong_relations") or [])
                if not links:
                    # agent_c 的口径：undervalued 为真，或 relations_to_hot 里有
                    # weak_points == 0 的强连接（§3.3(3) 第 4 条）
                    links = [
                        r
                        for r in (c.get("relations_to_hot") or [])
                        if isinstance(r, Mapping) and r.get("weak_points") == 0
                    ]
                if c.get("undervalued") or links:
                    selected.append((c, links))
            for c, links in selected[:3]:
                cid = str(c.get("concept_id") or "")
                if not S.is_valid_id(cid):
                    continue
                rids = [str(x.get("relation_id")) for x in links if isinstance(x, Mapping) and x.get("relation_id")]
                name = str(c.get("name") or self._concept_name(cid))
                out.append(
                    {
                        "kind": "cold",
                        "origin": f"C:cold:{rid}:{cid}",
                        "question": f"冷门概念「{name}」却与热门概念存在强连接（关系 {','.join(rids) or '-'}）——"
                        "它是否是一个被低估的研究切入点？该连接为何长期无人跟进？",
                        "related_concept_ids": [cid],
                        "related_relation_ids": [r for r in rids if S.is_valid_id(r)],
                        "seed_names": [name],
                        "priority": "medium",
                        "why": f"C 报告 {rid} 把 {cid} 归入「冷门但连接强」（degree={c.get('degree')}，"
                        f"undervalued={c.get('undervalued')}），这类最可能是被低估的研究点",
                    }
                )

        elif kind == "gaps":
            gaps = _entries("candidate_gaps", "candidates")[:3]
            for g in gaps:
                if not isinstance(g, Mapping):
                    continue
                cids = [str(x) for x in (g.get("concept_ids") or g.get("concepts") or [])]
                cids = [c for c in cids if S.is_valid_id(c)]
                if len(cids) < 2:
                    continue
                rids = [str(x) for x in (g.get("related_relation_ids") or g.get("relation_ids") or [])]
                cnames = [str(x) for x in (g.get("concept_names") or [])]
                names = cnames if len(cnames) == len(cids) else [self._concept_name(c) for c in cids]
                out.append(
                    {
                        "kind": "gaps",
                        "origin": f"C:gaps:{rid}:" + ",".join(cids),
                        "question": f"「{names[0]}」与「{names[1]}」之间是否应当存在直接关系？"
                        f"（C 的信号：{_digest(g.get('reason'), 120)}）",
                        "related_concept_ids": cids,
                        "related_relation_ids": [r for r in rids if S.is_valid_id(r)],
                        "seed_names": names,
                        "priority": "high" if str(g.get("confidence")) == "high" else "medium",
                        "why": f"C 报告 {rid} 的候选缺口：reason={_digest(g.get('reason'), 160)}，"
                        f"confidence={g.get('confidence')}，positive_signals={g.get('positive_signals')}",
                    }
                )

        # 通用兜底：payload 里直接给了概念/关系代号但没有可识别的分组
        if not out:
            cids = self._collect_ids(payload, ("concept_id", "concept_ids"))
            rids = self._collect_ids(payload, ("relation_id", "relation_ids"))
            if cids or rids:
                names = [self._concept_name(c) for c in cids[:3]]
                out.append(
                    {
                        "kind": kind or "unknown",
                        "origin": f"C:{kind or 'unknown'}:{rid}",
                        "question": (
                            f"C 报告（{kind}）涉及概念 {','.join(cids[:5]) or '-'} 与关系 {','.join(rids[:5]) or '-'}："
                            "这些代号指向的表述之间是否存在尚未被研究的关联？"
                        ),
                        "related_concept_ids": cids[:5],
                        "related_relation_ids": rids[:5],
                        "seed_names": names,
                        "priority": "medium",
                        "why": f"C 报告 {rid} 的 payload 结构未被识别（key={sorted(payload)[:8]}），"
                        "按代号集合生成兜底问题（这是容错路径，不是主路径）",
                    }
                )
        return out

    def _collect_ids(self, node: Any, keys: Sequence[str], *, depth: int = 0) -> list[str]:
        """递归收集 payload 里形如代号的值（容错用，深度受限防环）。"""
        found: list[str] = []
        if depth > 4:
            return found
        if isinstance(node, Mapping):
            for k, v in node.items():
                if k in keys:
                    if isinstance(v, str) and S.is_valid_id(v):
                        found.append(v)
                    elif isinstance(v, list):
                        found.extend(str(x) for x in v if S.is_valid_id(x))
                else:
                    found.extend(self._collect_ids(v, keys, depth=depth + 1))
        elif isinstance(node, (list, tuple)):
            for item in node:
                found.extend(self._collect_ids(item, keys, depth=depth + 1))
        return sorted(set(found))

    def _concept_name(self, cid: str) -> str:
        for row in self.store.rows("concepts"):
            if row.get("concept_id") == cid:
                return str(row.get("name") or cid)
        return f"概念{cid}"

    def _relation_ids_touching(self, concept_ids: Sequence[str]) -> list[str]:
        want = set(concept_ids)
        return sorted(
            str(r.get("relation_id"))
            for r in self.store.rows("relations")
            if want & set(r.get("concept_ids") or [])
        )

    @staticmethod
    def _content_key(kind: str, concept_ids: Sequence[str], relation_ids: Sequence[str]) -> tuple:
        """问题的内容键：决定"两个问题是不是同一个研究点"。

        用户要 D 评估的是"问题"，不是"报告条目"。同一份 C 分析跑两次会产生
        两个 ``report_id``（``AgentC.handle`` 每次都新发一个号），但关系链是同一
        条 —— 只按 ``origin`` 去重的话，第二个报告会把同样两条问题再提一遍，
        后果是 D 重复研究、以及（更贵的）向 A 问同一件事两次。

        键取 ``(kind, 排序后的关系代号)``；问题不带关系代号时（hottest/cold/gaps
        的某些形状）退回概念代号。必须在排序后比较 —— C 的路径可能以不同
        遍历顺序给出同样的链。
        """
        rels = tuple(sorted({str(x) for x in relation_ids if x}))
        concepts = tuple(sorted({str(x) for x in concept_ids if x}))
        return (str(kind), rels) if rels else (str(kind), "concepts", concepts)

    def ingest(self, report: Any, *, c_contradictions: Mapping[str, Any] | None = None) -> list[str]:
        """读 C 报告 → 提取候选问题 → 建 ``research_questions`` 行。

        返回新建的 ``question_id`` 列表（只有新建的）。
        每份报告最多提 ``max_questions`` 个（默认 5，§8 待决问题 2）：
        不设上限的话，一份 hottest 报告就能提出几十个问题，D 的循环会被自己的
        产出淹掉，人也读不完。

        ## 三级去重（缺一不可）

        1. 按 ``origin``：同一份报告重复 ingest 是幂等的（同一 ``report_id``）。
        2. 按内容键（:meth:`_content_key`）：不同报告指向同一条关系链时
           不新建行，而是把新来源追加进该问题的笔记里。多份报告指向同一个
           研究点，本身就是"这个点更值得做"的信号 —— 所以既要去重，也要留痕。
        3. 按等价类（§3.1，``interactions.find_equivalent_question``）：
           内容键只覆盖"关系代号完全一样"的情形；同一份报告里两条不同链条
           共享 ≥1 个关系代号（或概念集 Jaccard ≥ 阈值）时，它们说的是同一件事，
           内容键判不出来。这一层把候选的 ``origin`` 合并进已有问题的 notes
           （写成 ``merged_origins: ...``），而不是新建一行。

        "命中等价问题所以没新建"与"新建了"必须能区分：前者进
        ``last_ingest["equivalent_matched"]``，后者进 ``last_ingest["created"]``，
        每个候选的处置都记在 ``last_ingest["decisions"]`` 里（不靠返回值推断 ——
        返回值按既有契约只含新建的 id）。要一个同时给出两者的返回值，
        用 :meth:`ingest_detailed`。

        ## I2：矛盾的吸收

        ``c_contradictions`` 允许调用方把 I1 的 ``c.contradictions()`` 结果直接喂进来；
        不传时按 :meth:`_contradiction_candidates` 的三态顺序取来源（报告 payload →
        C 服务的有界查询）。矛盾候选一律是 ``kind="contradiction"`` + ``priority="high"``。

        Raises
        ------
        Exception
            任何写入期异常（``schema`` 的 ``ValueError``、``store`` 的
            ``StoreError``、``store.tx`` 的锁超时……）。这是刻意的：
            本方法在 ``try/except`` 里先把原因记进 ``last_ingest["error"]``
            （于是"这一轮到底为什么没建成问题"在报告里看得见），然后原样重抛。
            为什么重抛而不是吞掉：``ingest`` 是写路径，半个事务静默成功会让
            上层以为"报告已吸收"，而事实是候选全丢了 —— 那比崩掉更难查。
            这里显式写出来，是因为它原先只在代码里、docstring 只字未提，
            调用方无法从签名/文档判断"要不要自己包一层"（机械审计把它标成
            ``body_raises_but_docstring_silent``）。
        """
        info = _as_report_dict(report)
        self.last_ingest = {
            "report_id": info["report_id"],
            "kind": info["kind"],
            "candidates": [],
            "skipped": [],
            "merged": [],
            "equivalent_matched": [],
            "decisions": [],
            "contradictions": {},
        }
        if info["kind"] not in self.enabled_kinds:
            self.last_ingest["skipped"].append(f"kind={info['kind']} 不在 enabled_kinds={self.enabled_kinds}")
            return []

        candidates = self._candidates_from(info)
        contra = self._contradiction_candidates(info, c_contradictions)
        self.last_ingest["contradictions"] = {
            "source": contra["source"],
            "checked": contra["checked"],
            "reason": contra["reason"],
            "raw_count": contra["raw_count"],
            "skipped": contra["skipped"],
            "weak_clues": contra["weak_clues"],
        }
        candidates = candidates + contra["candidates"]
        self.last_ingest["candidates"] = [
            {"origin": c["origin"], "kind": c["kind"], "priority": c["priority"],
             "question_kind": c.get("question_kind", "gap"),
             "content_key": list(self._content_key(c["kind"], c["related_concept_ids"], c["related_relation_ids"]))}
            for c in candidates
        ]
        if not candidates:
            self.last_ingest["skipped"].append("payload 里没有可识别的结构化发现（见 _candidates_from 的假设形状）")
            # 没有候选问题不等于"弱线索可以丢"：它仍要落进台账/报告（但同样不追问）。
            if contra["weak_clues"]:
                self.last_ingest["weak_clues_noted"] = self._note_weak_clues(contra["weak_clues"])
            return []

        # 排序：priority 高在前，再按 origin 稳定排序 —— 截断时被丢掉的必须是
        # "最不重要"的那几个，而不是"恰好排在后面"的那几个。
        prio_rank = {p: i for i, p in enumerate(S.PRIORITIES)}
        candidates.sort(key=lambda c: (prio_rank.get(c.get("priority"), 9), str(c.get("origin") or "")))

        rows_now = self.store.rows("research_questions")
        existing_origins = {str(r.get("origin")) for r in rows_now} if self.dedup_by_origin else set()
        #: 内容键 -> 已存在问题号。每次 ingest 都从盘上重建，因此跨进程/跨轮次
        #: 都能识别"另一份报告提过同一个研究点"。
        by_key: dict[tuple, str] = {}
        for r in rows_now:
            key = self._content_key(
                self._kind_of_origin(str(r.get("origin") or "")),
                r.get("related_concept_ids") or [],
                r.get("related_relation_ids") or [],
            )
            by_key.setdefault(key, str(r.get("question_id")))
        #: §3.1 的等价类匹配要看到本次 ingest 里刚建出来的行，否则同一份报告内
        #: 的两条等价链（第 2 条共享第 1 条的关系代号）谁也看不见谁，还是会建两条。
        working: list[dict] = [dict(r) for r in rows_now]
        decisions: list[dict] = self.last_ingest["decisions"]

        new_ids: list[str] = []
        merged: list[dict] = []
        equivalent: list[dict] = []
        try:
            with self.store.tx("research_questions", actor=self.actor, note="ingest") as tx:
                for cand in candidates:
                    if len(new_ids) >= self.max_questions:
                        self.last_ingest["skipped"].append(
                            f"达到 max_questions={self.max_questions}，其余候选被截断（防爆炸，§8 待决问题 2）"
                        )
                        break
                    key = self._content_key(cand["kind"], cand["related_concept_ids"], cand["related_relation_ids"])
                    hit = by_key.get(key)
                    if hit is not None:
                        # ---- 内容等价：不新建行，只把新来源追加进去
                        row = tx.find("research_questions", question_id=hit)
                        if row is None:
                            continue
                        note = (
                            f"[ingest] 另见报告 {info['report_id']}（kind={info['kind']}）的同一条链："
                            f"origin={cand['origin']}。多份报告指向同一研究点 = 该点更值得做的信号。"
                        )
                        old = row.get("notes") or ""
                        if note not in old:
                            row["notes"] = (old + "\n" + note)[:20000]
                        # 重复出现且优先级更高时提升优先级（信号更强，不是更弱）
                        if prio_rank.get(cand["priority"], 9) < prio_rank.get(row.get("priority"), 9):
                            row["priority"] = cand["priority"]
                        row["updated_at"] = self._stamp()
                        S.row_from_dict("research_questions", row).validate()
                        tx.upsert("research_questions", row, note=f"ingest_merge:{info['report_id']}")
                        merged.append({"question_id": hit, "origin": cand["origin"], "from_report": info["report_id"]})
                        decisions.append({"origin": cand["origin"], "action": "merged_by_content_key", "question_id": hit})
                        continue
                    if self.dedup_by_origin and cand["origin"] in existing_origins:
                        self.last_ingest["skipped"].append(f"origin 已存在：{cand['origin']}")
                        decisions.append({"origin": cand["origin"], "action": "skipped_origin_exists"})
                        continue
                    # ---- §3.1 等价类：内容键之外的第二层判据
                    eq = IX.find_equivalent_question(
                        working,
                        concept_ids=cand["related_concept_ids"],
                        relation_ids=cand["related_relation_ids"],
                    )
                    if eq and eq.get("matched") and eq.get("question_id"):
                        row = tx.find("research_questions", question_id=str(eq["question_id"]))
                        if row is not None:
                            note = (
                                f"merged_origins: {cand['origin']}（§3.1 等价类命中：{eq.get('detail')}；"
                                f"来源报告 {info['report_id']}）"
                            )
                            old = row.get("notes") or ""
                            if cand["origin"] not in old:
                                row["notes"] = (old + "\n" + note)[:20000]
                            if prio_rank.get(cand["priority"], 9) < prio_rank.get(row.get("priority"), 9):
                                row["priority"] = cand["priority"]
                            row["updated_at"] = self._stamp()
                            S.row_from_dict("research_questions", row).validate()
                            tx.upsert("research_questions", row, note=f"ingest_equivalent:{info['report_id']}")
                            equivalent.append(
                                {
                                    "question_id": str(eq["question_id"]),
                                    "origin": cand["origin"],
                                    "by": eq.get("by"),
                                    "detail": eq.get("detail"),
                                    "from_report": info["report_id"],
                                }
                            )
                            decisions.append(
                                {"origin": cand["origin"], "action": "merged_by_equivalence",
                                 "question_id": str(eq["question_id"]), "by": eq.get("by")}
                            )
                            continue
                    qid = tx.alloc_id("question")
                    row = S.ResearchQuestion(
                        question_id=qid,
                        question=cand["question"],
                        origin=cand["origin"],
                        # 代号溯源：问题必须带着"它从哪条链/哪个概念来"，否则
                        # 报告里的结论无法被回到关系表里去核对。
                        related_concept_ids=S.sorted_unique(cand["related_concept_ids"]),
                        related_relation_ids=S.sorted_unique(cand["related_relation_ids"]),
                        status="open",
                        priority=cand["priority"],
                        # I2：矛盾驱动的问题必须显式带 kind 与矛盾对，不靠解析 origin 字符串。
                        kind=str(cand.get("question_kind") or "gap"),
                        contradiction_relation_ids=S.sorted_unique(cand.get("contradiction_relation_ids") or []),
                        notes=f"[ingest] 来源报告 {info['report_id']}（kind={info['kind']}）。理由：{cand['why']}",
                        created_at=self._stamp(),
                        updated_at=self._stamp(),
                    )
                    row.validate()
                    tx.upsert("research_questions", row.to_dict(), note=f"ingest:{info['kind']}")
                    new_ids.append(qid)
                    existing_origins.add(cand["origin"])
                    by_key[key] = qid
                    working.append(row.to_dict())
                    decisions.append({"origin": cand["origin"], "action": "created", "question_id": qid})
        except Exception as e:
            self.last_ingest["error"] = f"{type(e).__name__}: {e}"
            raise
        self.last_ingest["created"] = new_ids
        self.last_ingest["merged"] = merged
        self.last_ingest["equivalent_matched"] = equivalent

        # ---- 弱线索落痕（I2）：`strength != strong` 的矛盾对不建问题、不追问，
        # 但也不能丢 —— 它们可能在别的证据到位后变成真问题。落点有两个：
        #   1. 与该线索共享关系代号的已有问题的 notes（研究台账里看得到）；
        #   2. `last_ingest["contradictions"]["weak_clues"]` + 报告审计一节。
        if contra["weak_clues"]:
            self.last_ingest["weak_clues_noted"] = self._note_weak_clues(contra["weak_clues"])
        return new_ids

    def ingest_detailed(self, report: Any, *, c_contradictions: Mapping[str, Any] | None = None) -> dict:
        """``ingest`` 的详细返回形态：每个候选的处置都在这一个 dict 里（§3.1）。

        §3.1 要求"命中等价问题所以没新建"与"新建了"在返回值里体现。
        但 ``ingest`` 的既有契约（以及依赖它的既有测试）是"返回新建的
        question_id 列表" —— 把它改成 dict 会把所有"我只想知道新建了哪些"的调用方
        弄坏。所以保留 ``ingest`` 的窄返回，另给这个宽的：
        一次调用同时能看到 ``created`` / ``merged_by_equivalence`` /
        ``merged_by_content_key`` / ``skipped`` 与每个候选的 ``decisions``。
        """
        created = self.ingest(report, c_contradictions=c_contradictions)
        info = dict(getattr(self, "last_ingest", {}) or {})
        return {
            "created": list(created),
            "created_count": len(created),
            "merged_by_content_key": list(info.get("merged") or []),
            "merged_by_equivalence": list(info.get("equivalent_matched") or []),
            "skipped": list(info.get("skipped") or []),
            "decisions": list(info.get("decisions") or []),
            "contradictions": dict(info.get("contradictions") or {}),
            "weak_clues_noted": list(info.get("weak_clues_noted") or []),
        }

    def _note_weak_clues(self, clues: Sequence[Mapping[str, Any]]) -> list[dict]:
        """把弱矛盾线索追加进"与之共享关系代号"的已有问题 notes，返回落痕记录。

        为什么要落痕而不是只写在内存里：线索的价值在于"以后证据变了能回头查"。
        只放在 `last_ingest` 里，进程一结束就没了；写进问题的 notes 才留在台账中。
        找不到共享关系代号的问题时如实记空（不编一个落点）。
        """
        noted: list[dict] = []
        try:
            with self.store.tx("research_questions", actor=self.actor, note="ingest_weak_clue") as tx:
                rows = tx.rows("research_questions")
                for clue in clues:
                    rids = {str(x) for x in (clue.get("relation_ids") or [])}
                    target = next(
                        (r for r in rows if rids & {str(x) for x in (r.get("related_relation_ids") or [])}),
                        None,
                    )
                    if target is None:
                        noted.append({"relation_ids": sorted(rids), "question_id": None,
                                      "reason": "没有共享这些关系代号的已有问题 ⇒ 只留在报告与 last_ingest 里"})
                        continue
                    line = (
                        f"[ingest] weak_conflict_clue: 关系 {'、'.join(sorted(rids))} 出现"
                        f"「{_digest(clue.get('signals'), 160)}」。strength={clue.get('strength')} ⇒ "
                        "只记录为线索，不建矛盾问题、不自动追问（弱信号的假阳性极高，"
                        "不能让 A 的产能烧在假矛盾上）。若后续证据让其中一方明确被否定，再走 I2。"
                    )
                    old = target.get("notes") or ""
                    if line not in old:
                        target["notes"] = (old + "\n" + line)[:20000]
                        target["updated_at"] = self._stamp()
                        S.row_from_dict("research_questions", target).validate()
                        tx.upsert("research_questions", target, note="weak_clue_noted")
                    noted.append({"relation_ids": sorted(rids), "question_id": str(target.get("question_id")),
                                  "reason": "已落进该问题的研究笔记"})
        except Exception as e:
            self.last_tool_errors.append({"tool": "tx:weak_clue", "error": f"{type(e).__name__}: {e}"})
        return noted

    @staticmethod
    def _kind_of_origin(origin: str) -> str:
        """从 ``C:<kind>:<report_id>[:...]`` 里取回 kind（内容键需要它）。

        ``contradictions`` 要规范化成 ``contradiction``：矛盾问题的
        ``origin`` 契约是 ``C:contradictions:<rid_a>+<rid_b>``（来源名），而问题
        的 kind 是 ``contradiction``（schema 词表）。不归一化的话，内容键
        "报告里读回来的行"与"候选"会永远不相等，跨报告的矛盾去重会静默失效。
        """
        parts = str(origin).split(":")
        kind = parts[1] if len(parts) > 1 else ""
        return "contradiction" if kind == "contradictions" else kind

    def _contradiction_candidates(
        self,
        info: Mapping[str, Any],
        c_contradictions: Mapping[str, Any] | None = None,
    ) -> dict:
        """把"矛盾"转成 ``kind="contradiction"`` 的候选问题（I2 的入口）。

        ## 三个来源，按"最直接优先"的顺序取（且每个来源都如实记账）

        1. ``payload["contradictions"]`` —— C 报告里已经算出来的矛盾（最直接）；
        2. 调用方通过 ``ingest(..., c_contradictions=...)`` 传进来的 I1 结果
           （D 在研究某个问题时点的那次菜，可以顺手交给 ingest 吸收）；
        3. 否则按报告自己引用的关系（范围有界）向 C 点一次菜。

        第 3 条刻意不用 ``relation_ids=None`` 扫全图：那会在每份报告
        ingest 时引入一个与本次分析无关的全局扫描，把无关矛盾灌进 D 的台账，
        表现是"一份 hottest 报告忽然带来十几条矛盾问题"。

        ## 只有 ``strength == "strong"`` 才建问题（这是一次真实缺陷的对策）

        ``interactions.detect_contradictions`` 会给出 ``strength``：

        - ``strong`` —— 一方明确断言肯定式、另一方明确断言对应的否定式
          （"A 是 B" vs "A 不是 B"）⇒ 允许建 ``kind="contradiction"`` 问题并自动追问；
        - ``weak`` —— 只是"否定标记出现与否不一致"（"不"/"not "）⇒ 假阳性极高
          （实测 25 条真实关系里 weak 报了 24%，且没有一条是真矛盾）。
          这一类只记成线索（``weak_clues`` + 落进相关问题的 notes + 报告），
          绝不触发检索请求 —— 否则 D 会把 A 的产能烧在一堆假矛盾上，
          而 I7 的配额本来就是为保护产能而设的。

        报告里的 ``strength`` 可能缺失或来自旧版，因此不信任它：缺失时就地
        用 ``interactions.detect_contradictions`` 对这两条关系重判一次（判据仍只有
        一份）。关系行缺失、无法判定的，保守当线索处理。

        返回 ``{"candidates", "source", "checked", "reason", "skipped", "raw_count",
        "weak_clues"}``。``checked`` 是三态：``True`` 查过、``False`` 查了但失败、
        ``None`` 没查（没接线 / 没有可推导的范围）—— 后两者必须能被分开读。
        """
        if not self.ingest_contradictions:
            return {"candidates": [], "source": "disabled", "checked": None,
                    "reason": "config.ingest_contradictions=False ⇒ 本次 ingest 不吸收矛盾（没查，不是没有矛盾）",
                    "skipped": [], "raw_count": 0, "weak_clues": []}
        payload = info.get("payload") if isinstance(info.get("payload"), Mapping) else {}
        raw: Any = None
        source = "none"
        checked: bool | None = None
        reason = ""

        payload_contras = payload.get("contradictions") if payload else None
        if isinstance(payload_contras, list):
            # 字段存在（哪怕是空列表）就表示报告已经给过这项检查的结论：
            # 空列表 = "查过、范围内没有矛盾"，与"没查"是两件事，所以不退回自动拉取。
            source, checked, raw = "report_payload", True, payload_contras
        elif c_contradictions is not None:
            source = "c_service_explicit"
            checked = bool(c_contradictions.get("checked"))
            reason = str(c_contradictions.get("reason") or "")
            raw = list(c_contradictions.get("contradictions") or []) if checked else []
            if not checked and not reason:
                reason = "调用方传入的 C.contradictions 结果 checked=False 且无理由 ⇒ 视为没查"
        elif getattr(self, "c", None) is not None:
            rids = self._collect_ids(payload, ("relation_id", "relation_ids"))
            if rids:
                res = self._c_call("contradictions", relation_ids=sorted(rids), limit=self.max_c_contradictions)
                source = "c_service"
                checked = bool(res.get("checked"))
                reason = str(res.get("reason") or "")
                raw = list(res.get("contradictions") or []) if checked else []
                if not checked and not reason:
                    reason = "C.contradictions 未成功返回且未给理由 ⇒ 视为没查"
            else:
                source = "c_service"
                checked = None
                raw = []
                reason = (
                    "报告 payload 里没有关系代号，无法推导矛盾查询范围 ⇒ **没查**"
                    "（刻意不退回全图扫描：那会把无关矛盾灌进本报告的台账）"
                )
        else:
            source, checked, raw = "none", None, []
            reason = "D 未接入 C 服务且报告 payload 里没有 contradictions ⇒ **没查**（不是没有矛盾）"

        out: list[dict] = []
        skipped: list[str] = []
        weak_clues: list[dict] = []
        for item in raw or []:
            if not isinstance(item, Mapping):
                skipped.append(f"矛盾记录不是对象：{type(item).__name__} ⇒ 跳过")
                continue
            rids = [str(x) for x in (item.get("relation_ids") or item.get("relation_id_pair") or []) if x]
            if len(rids) != 2 or rids[0] == rids[1]:
                skipped.append(f"矛盾记录必须恰有 2 条**不同**的关系代号，收到 {rids!r} ⇒ 跳过")
                continue
            rids = sorted(set(rids))
            rel_rows: list[dict] = []
            for rid in rids:
                row = next((r for r in self.store.rows("relations") if str(r.get("relation_id")) == rid), None)
                if row is not None:
                    rel_rows.append(row)
            strength = str(item.get("strength") or "")
            if strength not in ("strong", "weak"):
                # 报告里的字段可能是旧版/缺失 ⇒ 就地用唯一权威判据重判，
                # 而不是默认成 strong（那会让一堆弱线索去烧 A 的产能）。
                rec = None
                if len(rel_rows) == 2:
                    rec = next(
                        (x for x in IX.detect_contradictions(rel_rows) if set(x["relation_ids"]) == set(rids)),
                        None,
                    )
                strength = str((rec or {}).get("strength") or "weak")
                if rec:
                    item = {**item, "signals": item.get("signals") or rec.get("signals") or []}
            signals = "；".join(str(x) for x in (item.get("signals") or [])) or "（C 未给出可核实的信号文本）"
            cids = sorted({str(x) for x in (item.get("concept_ids") or []) if x})
            if not cids:
                # 概念集必须由关系行现场推导（C 报告里可能没带）——
                # related_concept_ids 是 D 后续判"新证据是否相关"的依据，不能空着。
                for row in rel_rows:
                    cids.extend(str(x) for x in (row.get("concept_ids") or []) if x)
                cids = sorted(set(cids))
            if strength != "strong":
                # ---- 弱线索：只记录，不建问题、不追问
                weak_clues.append(
                    {
                        "relation_ids": rids,
                        "concept_ids": cids,
                        "strength": strength,
                        "signals": signals,
                        "detection": item.get("detection") or "literal",
                        "note": (
                            "strength != strong ⇒ 只是线索（'否定标记出现与否不一致'的假阳性极高，"
                            "实测 24% 的报警都不是矛盾）⇒ 不建矛盾问题、不提交检索请求"
                        ),
                    }
                )
                skipped.append(
                    f"弱线索（{'、'.join(rids)}，strength={strength or '未知'}）：只记录，不建问题/不追问"
                )
                continue
            names = [self._concept_name(c) for c in cids] or [f"关系{rids[0]}", f"关系{rids[1]}"]
            out.append(
                {
                    "kind": "contradiction",  # 内容键用的"来源类型"
                    "question_kind": "contradiction",  # schema 的问题 kind
                    "origin": f"C:contradictions:{rids[0]}+{rids[1]}",
                    "question": (
                        f"关系 {rids[0]} 与 {rids[1]} 的陈述互相矛盾，需要判定哪一方成立"
                        f"（涉及概念：{'、'.join(names)}；C 的信号：{_digest(signals, 160)}）"
                    ),
                    "related_concept_ids": cids,
                    "related_relation_ids": rids,
                    "contradiction_relation_ids": rids,
                    "seed_names": names,
                    "priority": "high",  # §1 I2：矛盾是最强信号，一律 high
                    "strength": strength,
                    "why": (
                        f"C 检测到矛盾对 {rids[0]} vs {rids[1]}"
                        f"（detection={item.get('detection') or 'literal'}，strength=strong，"
                        f"scope={item.get('scope') or IX.CONFLICT_SCOPE}）：{_digest(signals, 200)}"
                    ),
                    "source": source,
                }
            )
        return {
            "candidates": out,
            "source": source,
            "checked": checked,
            "reason": reason,
            "skipped": skipped,
            "raw_count": len(raw or []),
            "weak_clues": weak_clues,
        }

    # ------------------------------------------------------------ [2] 溯源

    @staticmethod
    def _chain_order(qrow: Mapping[str, Any]) -> list[str]:
        """从 ``origin`` 里读回按跳序的关系链；读不到时退回升序的 ``related_relation_ids``。

        为什么必须从 ``origin`` 读：``ResearchQuestion.related_relation_ids`` 是
        schema 规定"升序去重"的字段，跳序在那里已经丢失。而 C 在 ``origin``
        里写的是它分析出来的真实链条（``C:paths:0000:0009->0010->0005``）。
        报告要让人"顺着链读"，就必须用这个顺序。

        读不到（非 paths 来源、或 origin 被人改过）时退回升序 —— 顺序可能是错的，
        但绝不编一个不存在的链条；报告里会写成"直接相关的关系（无跳序信息）"。
        """
        origin = str(qrow.get("origin") or "")
        parts = origin.split(":")
        if len(parts) >= 4 and parts[1] == "paths":
            ids = [x.strip() for x in parts[3].split("->") if x.strip()]
            ids = [x for x in ids if S.is_valid_id(x) or x == "-"]
            ids = [x for x in ids if S.is_valid_id(x)]
            if ids:
                return list(dict.fromkeys(ids))
        return [str(x) for x in (qrow.get("related_relation_ids") or []) if x]

    def _chain_concept_path(self, qrow: Mapping[str, Any], chain_ids: Sequence[str]) -> list[str]:
        """从原始 C 报告里取回这条链的概念路径（用来标注每一跳的方向）。

        为什么值得多查一次：``trace.relation`` 只知道一条关系连接了哪几个概念
        （``concept_ids`` 是升序的），所以它给出的"素理想 → 环同态"可能把方向
        写反。而 C 在报告 payload 的 ``paths[].concept_path`` 里明确记了这条链的
        走向（群→环同态→素理想→域）。报告要让人"顺着链读"，方向就必须来自
        C 的分析结果，而不是我按代号大小猜一个。

        找不到（报告被移走、payload 形状不符、链不匹配）时返回 ``[]`` ——
        此时渲染退回"概念组"的写法，不编方向。
        """
        origin = str(qrow.get("origin") or "")
        parts = origin.split(":")
        if len(parts) < 3 or not S.is_valid_id(parts[2]):
            return []
        rid = parts[2]
        rep = next((x for x in self.store.rows("analysis_reports") if str(x.get("report_id")) == rid), None)
        if rep is None:
            # R002 的例外，理由（不是把"没做"折叠成"没有"）：
            # 这是渲染层的辅助函数，问的是"C 的报告里有没有记过这条链的方向"。
            # 报告不在库里时，正确答案就是"我没有依据 → 退回概念组的写法"，
            # 而不是"方向是空的"。调用方（`trace_question`）拿到 `[]` 后走的是
            # "不编方向"的分支，不会把 `[]` 当成一个关于世界的断言。
            # 真正的三态由上层负责：证据是否就绪是 `assess()` 的结论，不是这里。
            return []
        wanted = [str(x) for x in chain_ids]
        for p in (rep.get("payload") or {}).get("paths") or []:
            if not isinstance(p, Mapping):
                continue
            if [str(x) for x in (p.get("relation_chain") or [])] == wanted:
                cpath = [str(x) for x in (p.get("concept_path") or [])]
                if len(cpath) == len(wanted) + 1:
                    return cpath
        return []

    def _trace_one(self, tool_name: str, **params: Any) -> Any:
        """调一个溯源工具，返回其 ``data``；工具不存在 / 调用失败返回 None。

        为什么不用 ``self._call``：溯源工具可能压根没被注册（外部的
        ``trace_tools`` 还没写好）；那种情况下我们要的是"安静地降级"，
        而不是往 ``last_tool_errors`` 里灌一堆噪声 —— 降级本身会在证据包的
        ``trace_mode`` 字段里如实写明。
        """
        if tool_name not in self.tools:
            return None
        res = self.tools.call(tool_name, **params)
        if not res.ok:
            if res.meta.get("kind") != "unknown_tool":
                self.last_tool_errors.append({"tool": tool_name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data

    def _relations_by_id(self) -> dict[str, dict]:
        rels = {str(r.get("relation_id")): r for r in self.store.rows("relations")}
        for r in rels.values():
            # `concept_pair_key` 是派生态，这里顺手补上（D 自己的判据计算要读它）。
            #
            # 注意：`interactions.detect_contradictions` 现在自己就会就地推导
            # 这个键（表里存的字段叫 `concept_group_key`，早先直接读 `concept_pair_key`
            # 会让"从表里读出来的行"恒返回空结果 —— 完全静默，看起来像"没有矛盾"）。
            # 所以这里的补字段不再是正确性的前提，只是让 D 侧读起来一致；
            # 谁要是删掉它，矛盾判据也不会再静默失效。
            r["concept_pair_key"] = IX.concept_pair_key([str(c) for c in (r.get("concept_ids") or []) if c])
        return rels

    def trace_question(self, qid: str) -> dict:
        """L1→L2（按需 L3）溯源，返回证据包（§4.3）。

        - L1：``relation_id`` → ``quote`` / ``description`` / ``page_range``；
        - L2：``concept_id`` → 概念定义 + 它参与的全部关系的表述；
        - L3：``lit_id`` → 文献元数据 + 本地文件 + 正文片段。

        L3 是按需的（贵）：只有当"证据互相矛盾"或"要写结论却没有一条
        ``quote_verified=True`` 的关系"时才下钻。这两个条件都是可核实的，
        不做"感觉需要更多细节"这种判断。

        工具调用一律走 ``self.tools.call``：如果 ``trace_tools`` 还没写好，
        本方法用的是内置降级替身（``trace_mode="fallback"``），返回的证据形状
        与真身一致，因此 D 的后续步骤不需要分支。

        Raises
        ------
        EvidenceError
            研究问题 ``qid`` 不在 ``research_questions`` 表里。显式列出
            而不是让它隐式逃逸：调用方（``pipeline``/``cli``）要能区分
            "问题号写错了"（调用方 bug，应立刻停）与"证据不足"（业务状态）。
        """
        qrow = next((r for r in self.store.rows("research_questions") if r.get("question_id") == qid), None)
        if qrow is None:
            raise EvidenceError(f"研究问题 {qid} 不存在")
        # 注：`last_tool_errors` 已在 `__init__` 里初始化（见那里的注释）。
        # 这里原先还有一行 `getattr(self, "last_tool_errors", [])` 的惰性兜底 ——
        # 它既是死代码，又会掩盖"有人在别处绕过 `__init__` 造对象"这种真实错误
        # （兜底之后错误消失，只留下一个莫名其妙的空列表）。故删除。

        rel_index = self._relations_by_id()
        #: 链条自身的步子（L1 的本体），按跳序排列。见 :meth:`_chain_order`。
        chain_ids = self._chain_order(qrow)
        #: 链条的概念走向（群→环同态→素理想→域），来自 C 报告的 payload；
        #: 用来给每一跳标出方向（见 :meth:`_chain_concept_path`）。
        chain_cpath = self._chain_concept_path(qrow, chain_ids) if chain_ids else []
        wanted_rids = [r for r in (qrow.get("related_relation_ids") or []) if r]
        # 概念度数不够时，把"概念当前参与的全部关系"并进候选：
        # 否则一个刚提取出来的问题（只带 0~1 条关系）会永远判成"证据不足"，
        # 而库里其实已经有相关表述了。
        #
        # 这些是 L2 上下文，不是链条本身。两者在报告里必须分开呈现：
        # 混在一个列表里，读者无法分辨"哪几条是这条链的步子、哪些只是顺带捞到的"，
        # 而"按代号溯源"的要求恰恰是让人顺着链读。判据计算仍然用全部 claims
        # （广度是判断证据够不够的依据），受限的只是呈现。
        for cid in qrow.get("related_concept_ids") or []:
            for r in rel_index.values():
                if cid in (r.get("concept_ids") or []):
                    wanted_rids.append(str(r.get("relation_id")))
        # 排序：链条自身在前且按跳序，其余按代号升序（稳定、可复现）
        ordered: list[str] = list(chain_ids) + sorted(set(wanted_rids) - set(chain_ids))
        wanted_rids = list(dict.fromkeys(ordered))

        claims: list[dict] = []
        traces: list[dict] = []
        trace_mode = "external"
        for rid in wanted_rids:
            data = self._trace_one("trace.relation", relation_id=rid)
            if data is None:
                # 工具缺失/失败 => 用本地关系行兜底（只用事实，不做推断）
                data = self._local_relation_claim(rid)
                trace_mode = "fallback"
            if data and str(data.get("source")) == "fallback":
                trace_mode = "fallback"
            if not data or data.get("found") is False:
                traces.append({"level": "L1", "tool": "trace.relation", "relation_id": rid, "found": False})
                continue
            traces.append({"level": "L1", "tool": "trace.relation", "relation_id": rid, "found": True})
            row = rel_index.get(rid) or {}
            # 概念代号：外部返回 `concepts: [{concept_id,...}]`，降级替身返回 `concept_ids: [...]`。
            # 两者都认 —— 否则 `concept_pair_key` 恒为空，§4.4 判据 3（矛盾）永远不会触发。
            cids = data.get("concept_ids")
            if not cids:
                cids = [c.get("concept_id") for c in (data.get("concepts") or []) if isinstance(c, Mapping)]
            cids = [str(c) for c in (cids or row.get("concept_ids") or []) if c]
            claims.append(
                {
                    "relation_id": rid,
                    "lit_id": data.get("lit_id") or row.get("lit_id"),
                    "concept_ids": cids,
                    "concept_names": list(data.get("concept_names") or []),
                    "quote": str(data.get("quote") or ""),
                    "description": str(data.get("description") or ""),
                    "statement": str(data.get("statement") or row.get("statement") or ""),
                    "page_range": data.get("page_range") or row.get("page_range") or {},
                    "status": data.get("status") or row.get("status"),
                    "quote_verified": data.get("quote_verified", row.get("quote_verified")),
                    "concept_pair_key": row.get("concept_pair_key"),
                    "on_path": rid in set(qrow.get("related_relation_ids") or []),
                    "in_chain": rid in chain_ids,
                    "hop": (chain_ids.index(rid) + 1) if rid in chain_ids else None,
                    # 这一跳的两个端点（按 C 的走向）；拿不到就是 None，绝不猜。
                    "hop_from": self._concept_name(chain_cpath[chain_ids.index(rid)])
                    if rid in chain_ids and len(chain_cpath) == len(chain_ids) + 1 else None,
                    "hop_to": self._concept_name(chain_cpath[chain_ids.index(rid) + 1])
                    if rid in chain_ids and len(chain_cpath) == len(chain_ids) + 1 else None,
                }
            )

        # ---- L1+：关系链（`trace.chain`）。问题若来自 C 的 paths 报告，它的
        # `related_relation_ids` 正是一条链；把整条链的表述串起来引用，是需求
        # "按代号溯源到相关表述"在链条维度上的直接体现（报告里可直接引用 chain_text）。
        #
        # 按跳序（hop order）传：`related_relation_ids` 是 schema 要求升序去重的
        # 字段，跳序在那里已经丢了；链子的真实顺序只能从 `origin`
        # （``C:paths:0000:0009->0010->0005``）里读回来。用升序的号去调 trace.chain，
        # 会得到一条"编号递增但语义断裂"的链 —— 而读者要的是能顺着读的推导过程。
        path_chains: list[dict] = []
        if len(chain_ids) >= 2 and "trace.chain" in self.tools:
            chain = self._trace_one("trace.chain", relation_ids=list(chain_ids))
            if isinstance(chain, Mapping):
                if str(chain.get("source")) == "fallback":
                    trace_mode = "fallback"
                traces.append({"level": "chain", "tool": "trace.chain", "found": True,
                               "steps": chain.get("step_count")})
                path_chains.append(
                    {
                        "relation_ids": list(chain.get("relation_ids") or []),
                        "chain_text": chain.get("chain_text") or "",
                        "missing": list(chain.get("missing") or []),
                    }
                )

        # ---- L2：概念定义 + 参与的全部关系
        l2: list[dict] = []
        all_cids: set[str] = set(qrow.get("related_concept_ids") or [])
        for c in claims:
            all_cids.update(c["concept_ids"])
        for cid in sorted(all_cids):
            # `with_relations=True`：L2 的语义就是"概念定义 + 它参与的全部关系的表述"。
            # 不显式打开的话，外部 trace_tools 默认只回定义与度数，D 就拿不到邻居的表述。
            data = self._trace_one("trace.concept", concept_id=cid, with_relations=True)
            if data is None:
                data = self._local_concept(cid)
                trace_mode = "fallback"
            elif str(data.get("source")) == "fallback":
                trace_mode = "fallback"
            if not data or data.get("found") is False:
                traces.append({"level": "L2", "tool": "trace.concept", "concept_id": cid, "found": False})
                continue
            traces.append({"level": "L2", "tool": "trace.concept", "concept_id": cid, "found": True})
            # 两种返回形状必须都认：
            #   - 外部 trace_tools：`{level:'L2', concept:{...}, counts:{relation_count:N}, relations:[...]}`
            #   - 内置降级替身：`{concept_id, name, definition, degree, relations:[...]}`
            # 早先只读扁平形状，结果外部的 degree/name/definition 全被读成空 ——
            # 判据 (b) 于是永远成立，D 会对着有充分证据的问题一直提问。
            inner = data.get("concept") if isinstance(data.get("concept"), Mapping) else {}
            counts = data.get("counts") if isinstance(data.get("counts"), Mapping) else {}
            rels = list(data.get("relations") or [])
            degree = data.get("degree")
            if degree is None:
                degree = counts.get("relation_count")
            if degree is None:
                degree = data.get("relation_count")
            if degree is None:
                degree = len(rels)
            l2.append(
                {
                    "concept_id": cid,
                    "name": data.get("name") or inner.get("name") or "",
                    "definition": data.get("definition") or inner.get("definition") or "",
                    "aliases": list(data.get("aliases") or inner.get("aliases") or []),
                    "related_concepts": list(
                        data.get("related_concepts")
                        or [n.get("concept_id") for n in (data.get("neighbors") or []) if isinstance(n, Mapping)]
                    ),
                    "degree": int(degree or 0),
                    "occurrences": counts.get("occurrences"),
                    "relations": rels,
                }
            )

        return {
            "question_id": qid,
            "question": qrow.get("question") or "",
            "origin": qrow.get("origin") or "",
            "status": qrow.get("status"),
            "priority": qrow.get("priority"),
            "related_concept_ids": list(qrow.get("related_concept_ids") or []),
            "related_relation_ids": list(qrow.get("related_relation_ids") or []),
            "chain_ids": list(chain_ids),
            "chain_concept_path": list(chain_cpath),
            "claims": claims,
            "l2": l2,
            "l3": [],
            "path_chains": path_chains,
            "traces": traces,
            "trace_mode": trace_mode,
            "warnings": list(self.last_tool_errors),
        }

    def _local_relation_claim(self, rid: str) -> dict:
        """L1 的本地兜底：只读关系行，逐字返回，不做任何转写。"""
        row = next((r for r in self.store.rows("relations") if r.get("relation_id") == rid), None)
        if row is None:
            return {"found": False, "relation_id": rid, "source": "fallback"}
        return {
            "found": True,
            "source": "fallback",
            "relation_id": rid,
            "concept_ids": list(row.get("concept_ids") or []),
            "lit_id": row.get("lit_id"),
            "quote": row.get("quote") or "",
            "description": row.get("description") or "",
            "statement": row.get("statement") or "",
            "page_range": row.get("page_range") or {},
            "status": row.get("status"),
            "quote_verified": row.get("quote_verified"),
        }

    def _local_concept(self, cid: str) -> dict:
        """L2 的本地兜底。"""
        row = next((c for c in self.store.rows("concepts") if c.get("concept_id") == cid), None)
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
            for r in self.store.rows("relations")
            if cid in (r.get("concept_ids") or [])
        ]
        if row is None and not rels:
            return {"found": False, "concept_id": cid, "source": "fallback"}
        return {
            "found": True,
            "source": "fallback",
            "concept_id": cid,
            "name": (row or {}).get("name") or "",
            "definition": (row or {}).get("definition") or "",
            "aliases": list((row or {}).get("aliases") or []),
            "related_concepts": list((row or {}).get("related_concepts") or []),
            "relations": rels,
            "degree": len(rels),
        }

    def trace_l3(self, evidence: dict, lit_ids: Sequence[str] | None = None) -> dict:
        """按需 L3：下钻到文献（元数据 + 本地文件 + 正文是否可得）。

        刻意只取"事实"（文件是否存在、是否 processed），不在这里做 OCR 或
        正文抽取：那是 B/K 的职责，D 下钻正文的目的是"核对引文语境"，
        必须由专门的工具返回带页码的片段。工具缺失时如实写 ``found=False``,
        而不是假装读过 —— "没做"和"做了但没结果"是两件事。
        """
        want = list(lit_ids or [])
        if not want:
            want = [str(c.get("lit_id")) for c in evidence.get("claims") or [] if c.get("lit_id")]
        want = sorted(set(want))[: self.max_l3_lits]
        out: list[dict] = []
        for lid in want:
            data = self._trace_one("trace.literature", lit_id=lid)
            source = "external"
            if data is None:
                data = self._local_literature(lid)
                source = "fallback"
            if not data:
                data = {"found": False, "lit_id": lid}
            entry = dict(data)
            entry["lit_id"] = lid
            entry.setdefault("source", source)
            out.append(entry)
            evidence.setdefault("traces", []).append(
                {"level": "L3", "tool": "trace.literature", "lit_id": lid, "found": bool(data.get("found"))}
            )
        evidence["l3"] = out
        return evidence

    def _local_literature(self, lid: str) -> dict:
        row = next((r for r in self.store.rows("literature") if r.get("lit_id") == lid), None)
        if row is None:
            return {"found": False, "lit_id": lid, "source": "fallback"}
        path = None
        try:
            path = self.store.library_path(row.get("path"))
        except StoreError:
            path = None
        return {
            "found": True,
            "source": "fallback",
            "lit_id": lid,
            "title": row.get("title") or "",
            "type": row.get("type"),
            "year": row.get("year"),
            "doi": row.get("doi"),
            "processed": bool(row.get("processed")),
            "download_status": (row.get("download") or {}).get("status"),
            "file_exists": bool(path and path.exists()),
            "text_available": False,
        }

    # ------------------------------------------------------------ [3] 评估

    def assess(self, qid: str, evidence: dict | None = None) -> dict:
        """评估证据是否足够（§4.4 的可核实判据）。

        返回 ``{"sufficient", "insufficient", "criteria", "priority", "confidence",
        "hits", "contradictions", "degree", ...}`` —— 全部中间值都在里面，
        因为 D 的结论必须能被逐项复核（§3.4 对 C 的同一要求适用于 D）。

        ## I1：评估阶段也点一次菜

        判据本身（关键词命中 / 度数 / 矛盾）只依赖 D 侧溯源，不需要 C。
        但"这个问题的结论有没有 C 侧证据"必须在评估阶段就定下来：
        报告要用它决定措辞（无 C 侧证据时不许给确定语气）。所以这里在
        evidence 里还没有 ``c_queries`` 时补一次 :meth:`probe_c`；
        已经有（research 先查过）就复用，绝不重复查。
        """
        ev = evidence if evidence is not None else self.trace_question(qid)
        if ev.get("c_queries") is None:
            ev["c_queries"] = self.probe_c(qid)
        qrow = next((r for r in self.store.rows("research_questions") if r.get("question_id") == qid), None) or {}
        concepts = ev.get("l2") or []
        degree = max((int(c.get("degree") or 0) for c in concepts), default=0)

        keywords = question_keywords(
            qrow.get("question") or ev.get("question") or "",
            extra=[c.get("name") or "" for c in concepts],
        )
        verdict = analyze_gaps(
            [c["relation_id"] for c in ev.get("claims") or []],
            ev.get("claims") or [],
            keywords=keywords,
            degree=degree,
            degree_threshold=self.degree_threshold,
            concept_count=len(concepts),
        )
        verdict.update(
            {
                "question_id": qid,
                "keywords": keywords,
                "trace_mode": ev.get("trace_mode"),
                "claim_count": len(ev.get("claims") or []),
                "sufficient": not verdict["insufficient"],
                "l3_needed": self._l3_needed(verdict, ev),
                "c_queries": list(ev.get("c_queries") or []),
                "c_evidence": self._c_summary(ev.get("c_queries") or []),
                "c_wiring": dict(self.c_wiring),
            }
        )
        self.last_assessment = verdict
        return verdict

    def _l3_needed(self, verdict: dict, evidence: dict) -> bool:
        """是否必须下钻到正文（L3）。判据可核实，不用"感觉需要更多细节"。"""
        if self.force_l3:
            return True
        if verdict.get("contradictions"):
            return True  # 矛盾要靠原文语境判定谁对
        claims = evidence.get("claims") or []
        if claims and not any(c.get("quote_verified") is True for c in claims):
            return True  # 要写结论却一条可核验的引文都没有
        return False

    # ------------------------------------------------------------ [4] 提交查询请求

    def _budget(self) -> dict:
        """请求预算（§8 待决问题 3）。

        两道闸：每个问题最多 2 轮、全局最多 20 个请求。
        没有预算的话，一个措辞有问题的判据就能让 D 对着同一个问题无限提问，
        而 A 的队列是共享资源（别的智能体也在用）。
        """
        requests = self.store.rows("search_requests")
        mine = [r for r in requests if str(r.get("submitted_by") or "") == self.actor]
        per_q: dict[str, int] = {}
        for r in mine:
            note = str(r.get("content_description") or "")
            m = re.search(r"\[q:(\d{4})\]", note)
            if m:
                per_q[m.group(1)] = per_q.get(m.group(1), 0) + 1
        return {
            "total": len(mine),
            "total_limit": self.max_total_requests,
            "remaining": max(0, self.max_total_requests - len(mine)),
            "per_question": per_q,
            "per_question_limit": self.max_requests_per_question,
        }

    def _pending_of(self, qrow: dict) -> list[dict]:
        return RT.pending_requests_of(qrow, self.store.rows("search_requests"))

    def _search_topic_and_desc(self, qrow: dict, evidence: dict) -> tuple[str, str]:
        """构造提交给 A 的 topic 与内容描述。

        topic 用问题的概念名而不是整句问题：A 的 provider 是关键词检索，
        把一整句疑问句扔过去只会得到噪声。缺概念名时退化为问题前 60 字。
        """
        concepts = evidence.get("l2") or []
        names = [c.get("name") for c in concepts if c.get("name")][:4]
        question = str(qrow.get("question") or "")
        topic = " ".join(names) if names else _digest(question, 40)
        desc = (
            f"[q:{qrow.get('question_id')}] origin={qrow.get('origin')}；"
            f"研究问题：{_digest(question, 200)}；"
            f"需要检索的是：能补充该问题证据的文献"
            f"（现有相关关系 {len(evidence.get('claims') or [])} 条，"
            f"其中 quote_verified=True 的 "
            f"{sum(1 for c in evidence.get('claims') or [] if c.get('quote_verified') is True)} 条）"
        )
        return topic, desc

    def submit_gaps(self, qid: str) -> list[str]:
        """不足则提交查询请求（调 ``research.submit_gap``）。返回新提交的 request_id 列表。

        这个方法的全部价值集中在"不重复提交"上：
        1. 先看该问题的等待集里有没有未完成的请求 —— 有就直接返回空列表
           （工具内部还会再查一次重，两道关卡不冲突：方法是"省一次调用"，
           工具是"结构上不可能重复"）；
        2. 再看预算（每问题 2 轮 / 全局 20 个，§8 待决问题 3）。
             预算用完时不提交，但把原因写进 gap_reason —— 静默地少提一个请求
        会让报告里的"已提交查询"一节与事实不符。

        Raises
        ------
        EvidenceError
            研究问题 ``qid`` 不存在（先经 :meth:`trace_question`，同一个判据）。
            与"预算用完"必须分开：前者是调用方给错了号（该停），
            后者是正常业务状态（返回空列表 + 留痕）。
        """
        ev = self.trace_question(qid)
        verdict = self.assess(qid, ev)
        if not verdict["insufficient"]:
            return []

        qrow = next((r for r in self.store.rows("research_questions") if r.get("question_id") == qid), None)
        if qrow is None:
            raise EvidenceError(f"研究问题 {qid} 不存在")

        still_open = self._pending_of(qrow)
        if still_open:
            self.last_submit_skip = {
                "question_id": qid,
                "reason": "已有未完成的查询请求，未重复提交",
                "open_requests": [r.get("request_id") for r in still_open],
            }
            return []

        budget = self._budget()
        used = int(budget["per_question"].get(qid, 0))
        if used >= self.max_requests_per_question:
            self._note(qid, f"[budget] 该问题已提交 {used} 次查询，达到每问题上限 "
                           f"{self.max_requests_per_question}，本轮不再提问（§8 待决问题 3）")
            return []
        if budget["remaining"] <= 0:
            self._note(qid, f"[budget] 全局查询预算已用尽（上限 {self.max_total_requests}），本轮不再提问")
            return []

        topic, desc = self._search_topic_and_desc(qrow, ev)
        criteria = "；".join(f"{c['id']}: {c['detail']}" for c in verdict["criteria"])
        data = self._call(
            "research.submit_gap",
            question_id=qid,
            topic=topic,
            mode="topical",
            description=f"{desc}；触发的可核实判据：{criteria}",
        )
        if not data:
            return []
        if data.get("duplicated"):
            self.last_submit_skip = {"question_id": qid, "reason": data.get("reason")}
            return []
        rid = data.get("request_id")
        self._note(
            qid,
            f"[submit_gap] 证据不足（触发判据 {'/'.join(c['id'] for c in verdict['criteria'])}），"
            f"已向 A 提交查询请求 {rid}（topic={topic}，mode=topical）",
        )
        return [str(rid)] if rid else []

    def _note(self, qid: str, text: str) -> None:
        """追加研究笔记（走工具，保持"所有写操作都经过工具层"这条一致性）。"""
        self._call("research.write_note", question_id=qid, note=text)

    def consider(self, qid: str) -> dict:
        """§4.1 状态机的 [3] 评估 → 分支 这一步，独立成可复用的方法。

        - 证据足够 ⇒ 把问题推进到 ``researching``（下一步就该写结论了）；
        - 证据不足 ⇒ 交给 :meth:`submit_gaps` 提问（它会查重与看预算）。

        为什么必须单独有这个方法：早先"足够"这一支什么都不做，问题就永远停在
        ``open`` —— 而 ``research()`` 只处理 ``researching``，于是证据充足的问题
        永远不会被研究、也永远不会出现在报告的"现有证据"一节里，表现为
        "D 溯源为空"。那不是工具没接上，是状态机少了一条边（§4.1 明写"足够 → [5]
        写研究报告"）。把这一支显式实现出来，问题就再也不会卡在 open。

        返回 ``{"question_id","sufficient","criteria","priority","confidence",
        "promoted","submitted"}``，供编排层记账。
        """
        ev = self.trace_question(qid)
        verdict = self.assess(qid, ev)
        result = {
            "question_id": qid,
            "sufficient": bool(verdict["sufficient"]),
            "criteria": [c["id"] for c in verdict["criteria"]],
            "priority": verdict["priority"],
            "confidence": verdict["confidence"],
            "promoted": False,
            "submitted": [],
        }
        if verdict["sufficient"]:
            # open/needs_evidence -> researching 都是合法迁移（见 research_tools.LEGAL_TRANSITIONS）
            data = self._call("research.set_status", question_id=qid, status="researching",
                              notes="[consider] 证据足够（无判据触发）=> 进入 researching，准备写结论")
            result["promoted"] = bool(data)
            if not data:
                # 工具不可用时也要让状态前进，否则问题会永远卡在 open：
                # 直接经 store 写（同一把锁，同样过 schema 校验）。
                self._promote_to_researching(qid, reason="[consider] 工具层不可用，直接推进状态")
                result["promoted"] = True
            return result
        result["submitted"] = self.submit_gaps(qid)
        return result

    def _promote_to_researching(self, qid: str, *, reason: str = "") -> None:
        """把问题的状态推进到 ``researching``（直写 store 的降级路径）。

        只在工具层不可用/失败时走这里；正常路径一律经 ``research.set_status``，
        以便所有写操作都留在工具层（可审计、可加审批）。这里同样过一遍 schema
        校验，绝不允许"为了推进状态"而写入非法行。
        """
        try:
            with self.store.tx("research_questions", actor=self.actor, note="promote") as tx:
                row = tx.find("research_questions", question_id=qid)
                if row is None:
                    return
                row["status"] = "researching"
                row["updated_at"] = self._stamp()
                if reason:
                    old = row.get("notes") or ""
                    row["notes"] = (old + "\n" + reason)[:20000]
                S.row_from_dict("research_questions", row).validate()
                tx.upsert("research_questions", row, note="promote_researching")
        except Exception as e:
            self.last_tool_errors.append({"tool": "tx:promote", "error": f"{type(e).__name__}: {e}"})

    # ------------------------------------------------------------ [6] 复查等待集

    def poll(self, *, relations: Any = _UNSPECIFIED) -> dict:
        """检查等待中的请求，把就绪的问题拉回 ``researching``（§4.2 + §3.2）。

        为什么这一步不能靠猜：D 每轮开头能看到"库里多了几篇文献"，
        但无法判断这些文献是不是我提的请求带回来的 —— 只有在
        ``waiting_request_ids`` 里记过请求号的 D 才知道该等谁。
        本方法只依据三样落盘数据判断（请求 ``done``/``outcome``、
        文献 ``processed``），因此不需要 LLM，也不会随措辞变化而漂移。

        ## §3.2：再加一层"新证据真的回答了那个问题吗"

        旧判据（请求 done 且其文献都 processed）只说明"消化完了"，
        不说明"这些新证据真的回答了那个问题"。后果是：一个查不到东西的问题
        会反复触发同一件事的检索，把 A 的产能烧在同一个空洞上。
        所以这里把该请求带来的新落库关系交给
        ``interactions.evidence_relevance``：

        - ``relevant`` ⇒ 就绪，按原逻辑拉回 researching 并并入新关系/文献；
        - ``irrelevant`` ⇒ 不推进，notes 记 ``evidence_arrived_but_irrelevant``，
          并降低该问题优先级（high→medium→low，low 不再降）；
        - ``checked is False`` ⇒ 不推进，且只记"没检查"
          （``evidence_relevance_unchecked``）—— 绝不写成一个看起来像结论的
          "不相关"。

        ``relations=None`` 显式表示"调用方无法提供关系快照"（三态），
        与"提供了空列表 = 查了、这批文献没带来新关系"必须能区分。

        ## 为什么矛盾问题不降优先级

        ``kind="contradiction"`` 的优先级来自"知识内部可能互相冲突"这一事实，
        它不会因为一次检索落空而变得不重要；I2 的收敛靠轮数上限 + 全局配额
        而不是靠降优先级。所以那一类只记笔记、不改 priority。
        """
        data = self._call("research.poll_waiting")
        if data is None:
            return {"ok": False, "error": "research.poll_waiting 调用失败", "ready": [], "waiting": []}
        ready = list(data.get("ready") or [])
        waiting = list(data.get("waiting") or [])
        promoted: list[str] = []
        merged: dict[str, list[str]] = {}
        held: list[dict] = []
        relevance_map: dict[str, dict] = {}

        if ready:
            with self.store.tx("research_questions", "relations", actor=self.actor, note="poll") as tx:
                if relations is _UNSPECIFIED:
                    rels: list[dict] = tx.rows("relations")
                    can_check = True
                elif relations is None:
                    rels = []
                    can_check = False  # 调用方明确表示"没有能力提供关系快照"
                else:
                    rels = [dict(r) for r in relations]
                    can_check = True
                for item in ready:
                    qid = str(item.get("question_id"))
                    qrow = tx.find("research_questions", question_id=qid)
                    if qrow is None or qrow.get("status") not in ("needs_evidence", "open"):
                        continue
                    cids = set(qrow.get("related_concept_ids") or [])
                    new_lits = {str(x) for x in (item.get("new_lit_ids") or [])}
                    #: "这些文献新落库的关系" = 该请求带回来的文献所产生的关系。
                    candidate_rels = (
                        [r for r in rels if str(r.get("lit_id") or "") in new_lits] if can_check else []
                    )
                    relevance = IX.evidence_relevance(
                        qrow, new_relations=candidate_rels if can_check else None
                    )
                    relevance["question_id"] = qid
                    relevance["new_relation_count"] = len(candidate_rels)
                    relevance_map[qid] = relevance

                    if not relevance.get("checked"):
                        # ---- 三态之"没查"：既不推进，也不当作"不相关"，更不降级
                        line = (
                            f"[poll] evidence_relevance_unchecked：{relevance.get('reason')}"
                            " ⇒ 本轮不推进（这是「没检查」，不是「不相关」；等待集与优先级都不动）"
                        )
                        qrow["notes"] = self._append_note_once(qrow, line)
                        qrow["updated_at"] = self._stamp()
                        S.row_from_dict("research_questions", qrow).validate()
                        tx.upsert("research_questions", qrow, note="poll_unchecked")
                        held.append({"question_id": qid, "why": "unchecked", "reason": relevance.get("reason")})
                        continue
                    if relevance.get("relevance") != "relevant":
                        # ---- 证据到了但与问题无关：不推进 + 降优先级（§3.2）
                        line = (
                            f"[poll] evidence_arrived_but_irrelevant: 新到 {len(candidate_rels)} 条关系"
                            f"（文献 {sorted(new_lits)}），没有一条落在本问题的概念集 "
                            f"{sorted(cids)} 上 ⇒ 不推进，避免反复检索同一个空洞"
                        )
                        before = str(qrow.get("priority") or "")
                        if str(qrow.get("kind") or "gap") == "contradiction":
                            line += (
                                "；但本问题是矛盾驱动（kind=contradiction），其优先级来自"
                                "「知识内部可能互相冲突」，不因一次检索落空而降级"
                                "（I2 的收敛靠轮数上限与全局配额）"
                            )
                        else:
                            line += f"；优先级 {before} → {self._lower_priority(qrow)}"
                        qrow["notes"] = self._append_note_once(qrow, line)
                        qrow["updated_at"] = self._stamp()
                        S.row_from_dict("research_questions", qrow).validate()
                        tx.upsert("research_questions", qrow, note="poll_irrelevant")
                        held.append(
                            {"question_id": qid, "why": "irrelevant", "priority_before": before,
                             "priority": qrow.get("priority")}
                        )
                        continue

                    new_rids = sorted(
                        str(r.get("relation_id"))
                        for r in rels
                        if cids & set(r.get("concept_ids") or [])
                        and str(r.get("relation_id")) not in set(qrow.get("related_relation_ids") or [])
                    )
                    qrow["related_relation_ids"] = S.sorted_unique(
                        list(qrow.get("related_relation_ids") or []) + new_rids
                    )
                    qrow["evidence_lit_ids"] = S.sorted_unique(
                        list(qrow.get("evidence_lit_ids") or []) + list(item.get("new_lit_ids") or [])
                    )
                    qrow["status"] = "researching"
                    qrow["updated_at"] = self._stamp()
                    line = (
                        f"[poll] 等待的请求 {item.get('waiting_request_ids')} 已结束且文献已被 B 消化，"
                        f"新并入 {len(new_rids)} 条关系 / {len(item.get('new_lit_ids') or [])} 篇文献 => researching；"
                        f"证据相关性判据：relevant（落在问题概念集上的新关系 "
                        f"{relevance.get('relevant_relation_ids')}）"
                    )
                    qrow["notes"] = (qrow.get("notes") or "") + "\n" + line
                    qrow["notes"] = qrow["notes"][:20000]
                    S.row_from_dict("research_questions", qrow).validate()
                    tx.upsert("research_questions", qrow, note="poll_promote")
                    promoted.append(qid)
                    merged[qid] = new_rids

        self.last_poll = {
            "ok": True,
            "ready": [i.get("question_id") for i in ready],
            "waiting": [i.get("question_id") for i in waiting],
            "promoted": promoted,
            "merged_relations": merged,
            "held": held,
            "relevance": relevance_map,
            "counts": data.get("counts") or {},
            "reasons": {i.get("question_id"): i.get("reason") for i in waiting},
        }
        return self.last_poll

    @staticmethod
    def _append_note_once(row: Mapping[str, Any], line: str) -> str:
        """把一条笔记追加进 notes，同一类内容只写一次。

        为什么必须去重：poll 每轮都会重新看到同一批"已完成"的请求。若每次都追加，
        一个查不到东西的问题会在几轮内把 notes 撑到 20000 字的截断线，
        真正有用的研究笔记会被挤掉 —— 那是不可逆的信息损失。
        """
        old = str(row.get("notes") or "")
        marker = line.split("：", 1)[0].split(":", 1)[0]
        if marker and marker in old:
            return old
        return (old + "\n" + line)[:20000]

    @staticmethod
    def _lower_priority(row: dict) -> str:
        """按 ``S.PRIORITIES`` 降一档（high→medium→low）；已是 low 就不再降。"""
        cur = str(row.get("priority") or "low")
        idx = S.PRIORITIES.index(cur) if cur in S.PRIORITIES else len(S.PRIORITIES) - 1
        row["priority"] = S.PRIORITIES[min(idx + 1, len(S.PRIORITIES) - 1)]
        return str(row["priority"])

    # ------------------------------------------------------------ [6'] 矛盾裁决（I2）

    def _contradiction_budget(self) -> dict:
        """全局矛盾检索配额（I2 的硬上限之一）。

        统计口径：所有 ``kind="contradiction"`` 问题的 ``contradiction_request_ids``
        之和 —— 不是"本轮提交了几条"，也不是"还在途几条"。只有用"历史上提交过
        几条"才能保证这个循环一定在有限步内停下来；用"在途条数"会在请求完成
        之后重新腾出配额，循环又活了（这正是"看起来有闸门、实际没有"的形态）。
        """
        rows = self.store.rows("research_questions")
        used = sum(
            len(r.get("contradiction_request_ids") or []) for r in rows if str(r.get("kind")) == "contradiction"
        )
        limit = int(self.max_contradiction_requests)
        return {"used": used, "limit": limit, "remaining": max(0, limit - used), "exhausted": used >= limit}

    def _contradiction_scope(self, rel_ids: Sequence[str]) -> list[dict]:
        """同一概念组的全部关系（重新从表里读，I2 要求"复核"而不是"回忆"）。

        为什么范围是"同概念组"而不是"那两条关系本身"：裁决要判的是
        "这一对是否还对立"，而对立的判据（``detect_contradictions``）本来就只在
        同概念组内成立；把同组关系全带上，才能同时发现新冒出来的矛盾对 ——
        ``new_contradiction`` 这一支的全部输入都来自这里。

        这里给每行补 ``concept_pair_key`` 是为了 D 侧读起来一致：
        `interactions.detect_contradictions` 已改成缺字段时就地推导，
        所以它不再是正确性的前提（早先漏补这个键会让矛盾检测静默返回空）。

        两条关系都已经不在表里（被删/被合并）时返回 ``[]``：那是"争议双方都已消失"
        的证据，``adjudicate_contradiction`` 会据此判 ``side_removed``。
        """
        rows = self.store.rows("relations")
        keys: set[str] = set()
        wanted = {str(x) for x in rel_ids}
        keyed: list[tuple[str, str | None, dict]] = []
        for r in rows:
            key = r.get("concept_pair_key") or IX.concept_pair_key(
                [str(c) for c in (r.get("concept_ids") or []) if c]
            )
            keyed.append((str(r.get("relation_id")), key, dict(r)))
            if str(r.get("relation_id")) in wanted and key:
                keys.add(str(key))
        if not keys:
            return []
        out: dict[str, dict] = {}
        for rid, key, row in keyed:
            if key in keys:
                row["concept_pair_key"] = key
                out[rid] = row
        return [out[k] for k in sorted(out)]

    def _contradiction_request_text(
        self,
        qrow: Mapping[str, Any],
        observed: Sequence[Mapping[str, Any]],
        round_no: int,
        verdict: Mapping[str, Any],
    ) -> tuple[str, str]:
        """构造矛盾追问的 ``topic`` 与内容描述。

        与普通缺口一样，``topic`` 用概念名而不是整句疑问句：A 的 provider 是
        关键词检索，一整句疑问句只会得到噪声。矛盾链的代号也一并写进描述，
        让 A/人看得出"这次追问是为了判定哪两条表述"。
        """
        rids = [str(x) for x in (qrow.get("contradiction_relation_ids") or [])]
        names = [self._concept_name(str(c)) for c in (qrow.get("related_concept_ids") or [])][:4]
        topic = " ".join(n for n in names if n) or f"关系 {rids[0] if rids else '?'} 矛盾"
        quotes = "；".join(
            f"{o.get('relation_id')}：{_digest(o.get('statement') or o.get('description'), 100)}"
            for o in observed
        )
        desc = (
            f"[q:{qrow.get('question_id')}] kind=contradiction 第 {round_no} 轮追问；"
            f"矛盾对 {' vs '.join(rids)}；当前两条表述：{quotes}；"
            f"需要检索的是：能判定该分歧哪一方成立的文献"
            f"（上次裁决 {verdict.get('code')}：{_digest(verdict.get('reason'), 160)}）"
        )
        return topic, desc

    def adjudicate(self, qid: str) -> dict:
        """矛盾裁决（I2 闭环的收敛点）。

        ## verdict → 状态 的映射（这个映射是设计，不是实现细节）

        ====================  ===================  ==========================  ==================================
        verdict               status               contradiction_verdict       后续动作
        ====================  ===================  ==========================  ==================================
        ``resolved``          ``answered``         ``resolved``                清空等待集；notes 写 winner 与 code
        ``unresolved``        ``needs_evidence``   ``unresolved``              轮数 +1，并提交下一轮检索请求
        ``new_contradiction`` ``needs_evidence``   ``new_contradiction``       为新的矛盾对新建一条问题；原问题轮数 +1
        ``persistent``        ``answered``         ``persistent``              停止自动追问，交人复核
        ====================  ===================  ==========================  ==================================

        为什么 ``persistent`` 必须是 ``answered``：``schema.ResearchQuestion.validate``
        明确拒绝"声明 persistent 却还停在 open/researching"—— 那会让循环继续把它当
        活任务。同理，终局状态必须清空等待集，否则 ``verify`` 会报
        ``stale_waiting``（"已完成却还挂着等待项"）。

        为什么 ``contradiction_rounds`` 只在"还要继续追问"时 +1：
        它的语义是"已经发起过几轮追问"。``resolved``/``persistent`` 是终局，
        再加一就会让"轮数 ≤ 上限"这条验收在最后一轮上假性失败。

        ## 终止条件（三条，缺一条就会变成无限循环）

        1. 单条矛盾最多 ``max_rounds_per_contradiction``（默认 2）轮 ——
           由 ``interactions.adjudicate_contradiction`` 的 ``rounds/max_rounds`` 判；
        2. 全局最多 ``max_contradiction_requests``（默认 10）条矛盾驱动的检索请求；
        3. 任一条预算用尽时一律走 ``persistent``，不是 ``unresolved``
           —— 否则"还该继续"和"该停了"会被混为一谈，循环停不下来。
        另外 I7 的在途闸门（``admit_search_request``）拒绝时也走 ``persistent``：
        追问发不出去 = 这一轮事实上无法继续，硬撑成 ``unresolved`` 只会留下
        一个"说要继续、却什么都没提交"的假状态。

        ## 只有 ``strength == "strong"`` 才允许自动追问

        证据的"对立强度"由 ``interactions.detect_contradictions`` 判定：

        - ``strong``（一方明确断言肯定式、另一方明确断言否定式）⇒ 允许追问；
        - ``weak``（只是否定标记出现与否不一致）⇒ 不追问，直接标 ``persistent``，
          ``code="weak_only_signal"``（这是 D 侧的策略码，不在
          ``interactions.ADJUDICATION_CODES`` 里 —— 因为"该不该拿这条线索去问 A"
          是 D 的决策，不是判据本身的一部分；建议后续把它并入那张词表）。

        理由是一次实测：25 条真实论文关系里 weak 报了 6 条（24%），没有一条是真矛盾。
        拿 weak 驱动检索，会把 A 的产能烧在假矛盾上。

        写入纪律
        --------

        全部写入（问题行 + 新请求行 + 新矛盾问题行）在一个事务里完成：
        开两个事务就给了"问题说在等 r-0007、请求表里却没有 r-0007"这种半成品
        状态落盘的机会，而 schema 恰恰要求这两者同生同死。

        ## 只读准备的顺序

        所有读（问题行、关系表、裁决）都在开事务之前完成：``adjudicate`` 会读
        store，而 ``filelock`` 在同一进程内重入同一把锁会直接抛错。这条与 I6 给 B
        的硬约束同源（"在事务里调用会去拿锁的东西"是最容易死锁的形态）。
        """
        qrow = next(
            (r for r in self.store.rows("research_questions") if str(r.get("question_id")) == str(qid)), None
        )
        if qrow is None:
            raise EvidenceError(f"研究问题 {qid} 不存在")
        if str(qrow.get("kind") or "gap") != "contradiction":
            return {
                "question_id": qid,
                "checked": False,
                "action": "not_a_contradiction",
                "reason": (
                    f"问题 {qid} 的 kind={qrow.get('kind')!r}，不是矛盾驱动问题 ⇒ "
                    "不做矛盾裁决（这是「没做」，不是「裁决过、没矛盾」）"
                ),
            }
        rel_ids = sorted({str(x) for x in (qrow.get("contradiction_relation_ids") or []) if x})
        if len(rel_ids) != 2:
            return {
                "question_id": qid,
                "checked": False,
                "action": "bad_row",
                "reason": f"contradiction_relation_ids 必须恰有 2 条，收到 {rel_ids!r} ⇒ 无法裁决（没做）",
            }

        # ---- 重新读这两条关系 + 同概念组的全部关系
        scope = self._contradiction_scope(rel_ids)
        observed = [self._local_relation_claim(r) for r in rel_ids]
        rounds = int(qrow.get("contradiction_rounds") or 0)
        mr = int(self.max_rounds_per_contradiction)
        verdict_info = dict(
            IX.adjudicate_contradiction(
                {"relation_ids": rel_ids}, scope_relations=scope, rounds=rounds, max_rounds=mr
            )
        )
        detected = IX.detect_contradictions(scope)
        this_pair = next((x for x in detected if set(x["relation_ids"]) == set(rel_ids)), None)
        #: 当前这对关系的对立强度。只有 strong 允许驱动状态变更与追问；
        #: weak（"否定标记出现与否不一致"）的假阳性极高 —— 实测 25 条真实关系里
        #: weak 报了 24%，没有一条是真矛盾。把 weak 也拿去问 A，等于用 A 的产能
        #: 换一堆假问题，而 I7 的配额正是为保护产能而设的。
        pair_strength = str((this_pair or {}).get("strength") or "weak")
        if verdict_info.get("verdict") in ("unresolved", "new_contradiction") and pair_strength != "strong":
            verdict_info.update(
                {
                    "verdict": "persistent",
                    "code": "weak_only_signal",
                    "reason": (
                        f"{rel_ids[0]} 与 {rel_ids[1]} 目前只有**弱线索**（strength={pair_strength}："
                        "否定标记出现与否不一致，而非一方明确断言肯定式、另一方明确断言否定式）"
                        "⇒ 不自动追问，标 persistent 交人复核。"
                        "弱信号的假阳性极高，拿它驱动检索会把 A 的产能烧在假矛盾上"
                    ),
                }
            )
        budget = self._contradiction_budget()
        if verdict_info.get("verdict") == "unresolved" and budget["exhausted"]:
            # 全局配额用尽 ⇒ 必须走 persistent（"该停了"与"继续"不能混为一谈）
            verdict_info.update(
                {
                    "verdict": "persistent",
                    "code": "budget_exhausted",
                    "reason": (
                        f"{rel_ids[0]} 与 {rel_ids[1]} 仍对立，但**全局矛盾检索配额已用尽**"
                        f"（{budget['used']}/{budget['limit']}）⇒ 停止自动追问，交人复核。"
                        "这可能是真实的文献分歧（本身就有研究价值），而不是检索不足"
                    ),
                }
            )

        verdict = str(verdict_info.get("verdict"))
        result: dict[str, Any] = {
            "question_id": qid,
            "checked": True,
            "verdict": verdict,
            "code": verdict_info.get("code"),
            "reason": verdict_info.get("reason"),
            "winner_relation_id": verdict_info.get("winner_relation_id"),
            "rounds_before": rounds,
            "rounds_after": rounds,
            "status": qrow.get("status"),
            "action": "",
            "request_ids": [],
            "new_question_ids": [],
            "scope_relation_ids": [str(r.get("relation_id")) for r in scope],
            "observed": [
                {
                    "relation_id": o.get("relation_id"),
                    "found": o.get("found"),
                    "status": o.get("status"),
                    "statement": _digest(o.get("statement") or o.get("description"), 140),
                }
                for o in observed
            ],
            "budget": dict(budget),
            "c_wiring": dict(self.c_wiring),
        }

        #: 新冒出来的矛盾对。`adjudicate_contradiction` 给的 `new_relation_ids` 是
        #: 关系代号的并集，不足以还原"哪两条配成一对"；因此在同一范围上重新
        #: 检测一次，把涉及原关系的新配对取出来（判据仍是 interactions 的那一份）。
        #: 只取 strength=strong 的：弱线索不建问题（理由见 `_contradiction_candidates`）。
        new_pairs: list[list[str]] = []
        if verdict == "new_contradiction":
            new_pairs = [
                list(x["relation_ids"])
                for x in detected
                if str(x.get("strength")) == "strong"
                and set(x["relation_ids"]) != set(rel_ids)
                and ({rel_ids[0], rel_ids[1]} & set(x["relation_ids"]))
            ]

        now = self._stamp()
        with self.store.tx("search_requests", "research_questions", actor=self.actor, note=f"adjudicate:{qid}") as tx:
            row = tx.find("research_questions", question_id=qid)
            if row is None:
                result["checked"] = False
                result["reason"] = f"问题 {qid} 在事务内已不存在（被并发删除）⇒ 裁决未落盘"
                return result
            req_rows = tx.rows("search_requests")
            notes: list[str] = [
                f"[adjudicate] 第 {rounds + 1} 次裁决：verdict={verdict} code={verdict_info.get('code')}；"
                f"{_digest(verdict_info.get('reason'), 300)}"
            ]

            # ---- (1) new_contradiction：为新的矛盾对新建问题（同一事务）
            for pair in new_pairs:
                pair_ids = sorted({str(x) for x in pair})
                if len(pair_ids) != 2:
                    continue
                cids: list[str] = []
                for rid in pair_ids:
                    row_rel = next((r for r in scope if str(r.get("relation_id")) == rid), None)
                    if row_rel:
                        cids.extend(str(x) for x in (row_rel.get("concept_ids") or []) if x)
                cids = sorted(set(cids))
                # 这里刻意不用 §3.1 的 `find_equivalent_question`（"共享 ≥1 个
                # 关系代号即同一件事"）：矛盾问题的身份是那一对具体的表述
                # （`contradiction_relation_ids`）。用共享代号去判，(0002,0003) 与
                # (0002,0004) 会被判成同一个研究点而被合并 —— 可它们是两场不同的
                # 争议，而且轮数/预算的账会记到错误的那一场上。所以这里用
                # "同一对关系已经建过问题吗"这一个更严的判据。
                same = next(
                    (
                        r
                        for r in tx.rows("research_questions")
                        if str(r.get("kind")) == "contradiction"
                        and sorted(str(x) for x in (r.get("contradiction_relation_ids") or [])) == pair_ids
                    ),
                    None,
                )
                if same is not None:
                    other = tx.find("research_questions", question_id=str(same.get("question_id")))
                    if other is not None:
                        line = (
                            f"merged_origins: C:contradictions:{pair_ids[0]}+{pair_ids[1]}"
                            f"（裁决 {qid} 时再次发现同一对矛盾；同一对关系已建过问题，故不新建）"
                        )
                        if line not in (other.get("notes") or ""):
                            other["notes"] = ((other.get("notes") or "") + "\n" + line)[:20000]
                        other["updated_at"] = now
                        S.row_from_dict("research_questions", other).validate()
                        tx.upsert("research_questions", other, note="adjudicate_new_equiv")
                    notes.append(f"新矛盾对 {'+'.join(pair_ids)} 已有问题 {same.get('question_id')}，未新建")
                    continue
                nq = tx.alloc_id("question")
                # 防御：`counters` 落后于表时（手工建行、台账被人改过、外部脚本写入），
                # `alloc_id` 会发出已被占用的号，而 `tx.upsert` 是按主键替换 ——
                # 于是新建的问题会静默覆盖已有那一行（既不报重复 ID、也不报错，
                # 只是那条问题凭空消失）。手工插行在测试与救急脚本里都很常见，
                # 所以这里显式跳过已占用的号。（`ingest` 的建行路径有同样的隐患，
                # 本轮未改它 —— 见最终报告。）
                guard = 0
                while tx.find("research_questions", question_id=nq) is not None:
                    guard += 1
                    if guard > 10000:
                        raise EvidenceError(
                            "question 计数器与表严重不一致：连续 10000 个号都被占用，拒绝继续分配"
                        )
                    nq = tx.alloc_id("question")
                names = [self._concept_name(c) for c in cids] or [f"关系{pair_ids[0]}", f"关系{pair_ids[1]}"]
                new_row = S.ResearchQuestion(
                    question_id=nq,
                    question=(
                        f"关系 {pair_ids[0]} 与 {pair_ids[1]} 的陈述互相矛盾，需要判定哪一方成立"
                        f"（涉及概念：{'、'.join(names)}）"
                    ),
                    origin=f"C:contradictions:{pair_ids[0]}+{pair_ids[1]}",
                    related_concept_ids=S.sorted_unique(cids),
                    related_relation_ids=S.sorted_unique(pair_ids),
                    status="open",
                    priority="high",
                    kind="contradiction",
                    contradiction_relation_ids=S.sorted_unique(pair_ids),
                    notes=(
                        f"[adjudicate] 由问题 {qid} 的裁决（new_contradiction）派生："
                        f"复核 {rel_ids[0]} vs {rel_ids[1]} 时发现涉及它们的新矛盾对。"
                    ),
                    created_at=now,
                    updated_at=now,
                )
                new_row.validate()
                tx.upsert("research_questions", new_row.to_dict(), note=f"adjudicate_new:{qid}")
                result["new_question_ids"].append(nq)
                notes.append(f"新矛盾对 {'+'.join(pair_ids)} ⇒ 新建矛盾问题 {nq}（priority=high）")

            # ---- (2) 状态与轮数
            need_request = verdict in ("unresolved", "new_contradiction")
            refusal: str = ""
            if verdict == "resolved":
                row["status"] = "answered"
                row["contradiction_verdict"] = "resolved"
                row["waiting_request_ids"] = []  # 终局：等待集必须清空（否则 verify 报 stale_waiting）
                row["contradiction_request_ids"] = list(row.get("contradiction_request_ids") or [])
                notes.append(
                    f"争议解决（code={verdict_info.get('code')}）；胜出方 winner_relation_id="
                    f"{verdict_info.get('winner_relation_id')}"
                )
                result["action"] = "answered_resolved"
            elif verdict == "persistent":
                row["status"] = "answered"
                row["contradiction_verdict"] = "persistent"
                row["waiting_request_ids"] = []
                notes.append(
                    "**已停止自动追问，交人复核**；这可能是真实的文献分歧（本身有研究价值），"
                    "而不是检索不足（persistent）"
                )
                result["action"] = "answered_persistent"
            else:
                rounds_after = rounds + 1
                # I7 闸门：在途请求上限。拒绝 ⇒ 这一轮事实上无法继续 ⇒ persistent
                gate = IX.admit_search_request(
                    req_rows,
                    submitted_by="agent-D:contradiction",
                    explicit_priority="high",
                    for_question_id=qid,
                )
                if gate.get("admitted") and not budget["exhausted"]:
                    req_id = IX.next_prefixed_id(req_rows, "request_id", "r")
                    topic, desc = self._contradiction_request_text(row, observed, rounds_after, verdict_info)
                    new_req = S.SearchRequest(
                        request_id=req_id,
                        timestamp=now,
                        topic=topic,
                        mode="topical",
                        content_description=desc,
                        done=False,
                        submitted_by="agent-D:contradiction",
                        # 优先级取自闸门的裁决（它才是"定优先级"的唯一权威实现），
                        # 而不是在这里再写死一个 "high" —— 那是第二套判据的雏形。
                        priority=str(gate.get("priority") or "high"),
                        for_question_id=qid,
                        submit_note=(
                            f"I2 矛盾闭环第 {rounds_after} 轮追问（verdict={verdict}）；"
                            f"优先级依据：{gate.get('priority_why')}"
                        ),
                    )
                    new_req.validate()
                    # `tx.upsert` 会把它插进本事务的行列表；不要再手工 append
                    # 一次，否则同一事务里同一个 request_id 出现两行，提交时会以
                    # "search_requests 出现重复 ID" 炸掉（而错误信息完全不提这条来源）。
                    tx.upsert("search_requests", new_req.to_dict(), note=f"contradiction_round:{qid}")
                    row["contradiction_request_ids"] = S.sorted_unique(
                        list(row.get("contradiction_request_ids") or []) + [req_id]
                    )
                    row["waiting_request_ids"] = S.sorted_unique(
                        list(row.get("waiting_request_ids") or []) + [req_id]
                    )
                    row["status"] = "needs_evidence"  # schema 要求它与非空等待集同生同死
                    row["contradiction_verdict"] = verdict
                    row["contradiction_rounds"] = rounds_after
                    result["request_ids"].append(req_id)
                    result["rounds_after"] = rounds_after
                    notes.append(
                        f"{verdict}：已向 A 提交第 {rounds_after} 轮检索请求 {req_id}"
                        f"（priority={new_req.priority}，submitted_by=agent-D:contradiction，"
                        f"全局矛盾配额 {budget['used'] + 1}/{budget['limit']}）"
                    )
                    result["action"] = f"ask_again_{verdict}"
                else:
                    gate_blocked = not gate.get("admitted")
                    refusal = gate.get("reason") if gate_blocked else (
                        f"全局矛盾检索配额已用尽（{budget['used']}/{budget['limit']}）"
                    )
                    row["status"] = "answered"
                    row["contradiction_verdict"] = "persistent"
                    row["waiting_request_ids"] = []
                    notes.append(
                        f"**无法继续追问 ⇒ 标 persistent 交人复核**：{refusal}。"
                        "硬撑成 unresolved 只会留下一个『说要继续、却什么都没提交』的假状态。"
                    )
                    result["action"] = "answered_persistent"
                    result["verdict"] = "persistent"
                    # D 侧策略码（不在 interactions.ADJUDICATION_CODES 里）：说清是哪一道闸
                    # 挡住了追问 —— "在途请求满了"与"全局矛盾配额用尽"要人做的处置不同。
                    result["code"] = "inflight_limit" if gate_blocked else "budget_exhausted"
                    result["reason"] = refusal

            row["updated_at"] = now
            row["notes"] = ((row.get("notes") or "") + "\n" + "\n".join(notes))[:20000]
            S.row_from_dict("research_questions", row).validate()
            tx.upsert("research_questions", row, note=f"adjudicate:{verdict}")
            result["status"] = row.get("status")
            result["rounds_after"] = int(row.get("contradiction_rounds") or 0)
            result["verdict"] = str(row.get("contradiction_verdict") or result["verdict"])
            if refusal:
                result["reason"] = refusal

        self.last_adjudication = result
        return result

    def _adjudicate_ready_contradictions(self) -> list[dict]:
        """本轮先裁决"可裁决"的矛盾问题（I2），返回裁决结果列表。

        什么叫"可裁决"：``kind="contradiction"``、未终结（不是 answered/dropped、
        也没标 persistent）、且没有未完成的检索请求。

        最后一条很关键：请求还没回来就裁决，只会把同一轮追问重复提交一遍
        （等待集里已经挂着一个在途的请求），把 A 的队列刷爆 —— 那是"闸门看起来
        存在但没起作用"的典型。

        单轮设有 ``max_adjudications_per_round`` 上限：一份报告可能一次带进来
        十几对矛盾，全放出去等于一轮之内打十几条 high 请求。
        """
        rows = [r for r in self.store.rows("research_questions") if str(r.get("kind")) == "contradiction"]
        requests = self.store.rows("search_requests")
        out: list[dict] = []
        for row in sorted(rows, key=lambda r: str(r.get("question_id"))):
            if len(out) >= self.max_adjudications_per_round:
                self.last_tool_errors.append(
                    {
                        "tool": "adjudicate",
                        "error": f"本轮裁决数达到上限 {self.max_adjudications_per_round}，其余矛盾问题留到下一轮",
                    }
                )
                break
            qid = str(row.get("question_id"))
            if str(row.get("status") or "") in ("answered", "dropped"):
                continue
            if str(row.get("contradiction_verdict") or "") == "persistent":
                continue
            pending = RT.pending_requests_of(row, requests)
            if pending:
                out.append(
                    {
                        "question_id": qid,
                        "checked": True,
                        "action": "skipped",
                        "reason": (
                            f"仍有未完成的检索请求 {[r.get('request_id') for r in pending]}，"
                            "等它回来（且有新证据）再裁决"
                        ),
                    }
                )
                continue
            try:
                out.append(self.adjudicate(qid))
            except Exception as e:  # 单条矛盾的失败不能打断整轮
                self.last_tool_errors.append({"tool": "adjudicate", "error": f"{type(e).__name__}: {e}"})
                out.append(
                    {"question_id": qid, "checked": False, "action": "failed",
                     "reason": f"{type(e).__name__}: {e}"}
                )
        self.last_adjudications = out
        return out

    # ------------------------------------------------------------ [5] 初步研究

    def research(self, qid: str) -> dict:
        """对就绪问题做初步研究，产出研究笔记（§4.1 的第 5 步）。

        产出 ``{"question_id","confidence","analysis","conclusion","suggestions",
        "evidence","llm_used","c_queries","c_evidence"}``。置信度由
        :func:`evidence_confidence` 决定；LLM 只能把它调低（``_rank_min``）。

        ## I1：研究前必须先向 C 点一次菜

        ``research()`` 一定会带上 ``c_queries``（每条含
        ``{api, params, checked, truncated, digest, reason}``），参数由该问题的
        ``related_concept_ids`` / ``related_relation_ids`` 现场推导。这不是
        "顺便查一下"：结论里"这两个概念之间还有没有别的链条/别的矛盾关系"这类
        判断只能来自 C 的图查询，而报告本身是上一次分析的快照。

        一条 C 查询都没成功时，结论会被 :meth:`_apply_c_evidence_caveat`
        显式标注「无 C 侧证据」并放弃确定语气 —— 不允许把"没问到"写成
        "查不到"，更不允许在没问到的情况下给出看起来已被核实的判断。
        """
        ev = self.trace_question(qid)
        if ev.get("c_queries") is None:
            ev["c_queries"] = self.probe_c(qid)
        verdict = self.assess(qid, ev)
        if verdict.get("l3_needed") and not ev.get("l3"):
            ev = self.trace_l3(ev)

        qrow = next((r for r in self.store.rows("research_questions") if r.get("question_id") == qid), None) or {}
        confidence = verdict["confidence"]
        analysis, conclusion, suggestions, llm_used = self._compose(ev, verdict)
        conclusion, suggestions = self._apply_c_evidence_caveat(ev, verdict, conclusion, list(suggestions))

        # ---- 落库：笔记 + 证据文献 + 状态
        lit_ids = S.sorted_unique([str(c.get("lit_id")) for c in ev.get("claims") or [] if c.get("lit_id")])
        try:
            with self.store.tx("research_questions", actor=self.actor, note="research") as tx:
                row = tx.find("research_questions", question_id=qid)
                if row is not None:
                    row["evidence_lit_ids"] = S.sorted_unique(list(row.get("evidence_lit_ids") or []) + lit_ids)
                    if row.get("status") in ("open", "needs_evidence"):
                        row["status"] = "researching"
                    row["updated_at"] = self._stamp()
                    csum = self._c_summary(ev.get("c_queries") or [])
                    note = (
                        f"[research] 置信度={confidence}（判据：{'/'.join(c['id'] for c in verdict['criteria']) or '无'}；"
                        f"证据 {len(ev.get('claims') or [])} 条，quote_verified=True "
                        f"{sum(1 for c in ev.get('claims') or [] if c.get('quote_verified') is True)} 条；"
                        f"C 查询成功 {csum['ok']}/{csum['attempted']}；"
                        f"LLM={'yes' if llm_used else 'no'}）"
                        + ("" if csum["any_success"] else f" ⚠️ {C_NO_EVIDENCE}：结论未经 C 的图查询核对")
                    )
                    row["notes"] = ((row.get("notes") or "") + "\n" + note)[:20000]
                    S.row_from_dict("research_questions", row).validate()
                    tx.upsert("research_questions", row, note="researched")
        except Exception as e:
            self.last_tool_errors.append({"tool": "tx:research", "error": f"{type(e).__name__}: {e}"})

        result = {
            "question_id": qid,
            "question": ev.get("question"),
            "origin": ev.get("origin"),
            "priority": verdict.get("priority"),
            "confidence": confidence,
            "criteria": [c["id"] for c in verdict["criteria"]],
            "criteria_detail": verdict["criteria"],
            "hits": verdict["hits"],
            "contradictions": verdict["contradictions"],
            "analysis": analysis,
            "conclusion": conclusion,
            "suggestions": suggestions,
            "evidence": ev,
            "llm_used": llm_used,
            "trace_mode": ev.get("trace_mode"),
            "c_queries": list(ev.get("c_queries") or []),
            "c_evidence": verdict.get("c_evidence") or self._c_summary(ev.get("c_queries") or []),
        }
        self.last_research = getattr(self, "last_research", {})
        self.last_research[qid] = result
        return result

    def _apply_c_evidence_caveat(
        self,
        ev: Mapping[str, Any],
        verdict: Mapping[str, Any],
        conclusion: str,
        suggestions: list[str],
    ) -> tuple[str, list[str]]:
        """I1 的硬要求：一条 C 查询都没成功时，结论必须显式标注「无 C 侧证据」。

        为什么不能只是"悄悄少写一段"：C 的图查询是"这两个概念之间到底有哪些
        链条、还有没有别的矛盾关系"的唯一来源。缺了它，D 的结论只建立在问题
        自己引用的那几条关系上，而报告读起来与有 C 侧证据时一模一样 ——
        读者会把"没查"当成"查过了，就是这样"。

        所以这里做三件事（都是可判定的，不依赖措辞自觉）：
        1. 结论前面加显式标注与失败原因（哪个 api、什么错）；
        2. 结论后面加一条"不得作为确定结论引用"的提醒（覆盖 LLM 写出的确定语气）；
        3. 追加一条后续建议（怎么修）。
        """
        summary = verdict.get("c_evidence") or self._c_summary(ev.get("c_queries") or [])
        if summary.get("any_success"):
            return conclusion, suggestions
        why = "；".join(f"{f.get('api')}: {f.get('reason')}" for f in summary.get("failures") or []) or "未发起任何 C 查询"
        head = (
            f"**{C_NO_EVIDENCE}**：本问题对 C 的按需查询**全部没有成功**"
            f"（共 {summary.get('attempted')} 次；{why}）。以下判断只基于 D 侧溯源到的"
            "关系表述，未经 C 的图查询核对，因此不作确定结论 —— "
            "「没问到」不等于「不存在」。"
        )
        tail = (
            f"⚠️ 本条结论**{C_NO_EVIDENCE}**（失败原因见上）：在 C 服务可用并成功查询之前，"
            "不得把本节的措辞当作已核实的判断引用。"
        )
        return f"{head}\n\n{conclusion}\n\n{tail}", suggestions + [
            f"修复 C 服务接线（I1）后重跑本问题：当前{C_NO_EVIDENCE}，结论未经图查询核对。"
        ]

    def _compose(self, ev: dict, verdict: dict) -> tuple[str, str, list[str], bool]:
        """产出（初步分析, 结论, 后续建议, 是否用了 LLM）。

        确定性回退（``llm=None``）是基线而非残次品：它逐条罗列可核实的证据
        （命中数、度数、quote_verified 分布、矛盾对），措辞朴素但每一句都能被
        回到表里核对。LLM 只被允许在这之上"写得更通顺"，且结论必须能回指证据。
        """
        if self.llm is not None:
            try:
                out = self._llm_refine(ev, verdict)
                if out is not None:
                    return out["analysis"], out["conclusion"], out["suggestions"], True
            except Exception as e:  # LLM 失败绝不能打断循环
                self.last_tool_errors.append({"tool": "llm", "error": f"{type(e).__name__}: {e}"})
        return self._deterministic_compose(ev, verdict)

    def _deterministic_compose(self, ev: dict, verdict: dict) -> tuple[str, str, list[str], bool]:
        claims = ev.get("claims") or []
        hits = verdict.get("hits") or {}
        conf = verdict.get("confidence")
        lines: list[str] = []
        if not claims:
            lines.append("溯源到 L1/L2 后**没有取到任何关系表述**：这个问题目前完全没有可引用的证据。")
        for c in claims:
            lines.append(
                f"- 关系 {c['relation_id']}（文献 {c.get('lit_id')}，status={c.get('status')}，"
                f"quote_verified={c.get('quote_verified')}）逐字引用：「{_digest(c.get('quote'), 120)}」"
                f"；关系描述：「{_digest(c.get('description'), 120)}」"
            )
        # 置信度的因果必须写出来，否则"低"看起来像敷衍
        why = (
            f"命中关键词 {hits.get('distinct_hit_keywords')}/{hits.get('keyword_count')}，"
            f"相关概念度数上限 {verdict.get('degree')}，"
            f"quote_verified=True 的关系 {verdict.get('verified_count')} 条，"
            f"矛盾对 {len(verdict.get('contradictions') or [])} 对"
        )
        analysis = "\n".join(lines) + f"\n\n证据量：{why}。"
        if verdict.get("criteria"):
            analysis += "\n触发的可核实判据：" + "；".join(f"{c['id']}（{c['detail']}）" for c in verdict["criteria"])

        if conf == "low":
            conclusion = (
                "**置信度：低** —— 现有证据不足以支持任何实质性结论；本节的措辞刻意停在"
                "「可能存在/尚未证实」，不作为可引用的判断。"
            )
        elif conf == "medium":
            conclusion = "**置信度：中** —— 证据方向一致但样本有限（且部分引文未通过校验），结论应视为待复核的假设。"
        else:
            conclusion = "**置信度：高** —— 有多条通过引文校验的关系互相支撑，结论可进入后续论证。"
        if verdict.get("contradictions"):
            conclusion += " 注意：现有表述之间存在矛盾，分歧本身即研究价值所在。"

        suggestions: list[str] = []
        if not claims:
            suggestions.append("先补齐最基本的表述：向 A 提交针对性查询（本轮已按判据提交，见「缺口」一节）。")
        if not any(c.get("quote_verified") is True for c in claims):
            suggestions.append("逐条复核引文：当前没有一条关系的 quote 通过校验，无法判断表述是否忠于原文。")
        if verdict.get("contradictions"):
            suggestions.append("围绕矛盾双方各自下钻到文献正文（L3），确认分歧是实质性的还是措辞差异。")
        if verdict.get("degree", 0) < self.degree_threshold:
            suggestions.append("该方向度数偏低，建议扩大检索面（mode=broad）以确认「冷门」是否为真实空白。")
        if not suggestions:
            suggestions.append("证据已初步成形，建议进入下一层验证（构造反例 / 与其它链条交叉核对）。")
        return analysis, conclusion, suggestions, False

    def _llm_refine(self, ev: dict, verdict: dict) -> dict | None:
        """LLM 钩子：把证据包写成更通顺的分析。

        硬规则（写在提示词里、也在代码里强制）：
        - 只能引用证据包中出现过的 ``relation_id`` / ``quote``，不得引入新事实；
        - 置信度只能等于或低于确定性算出的那一档（``_rank_min``）——
          这条在代码里兜底，不依赖模型守规矩。
        """
        prompt = json.dumps(
            {
                "task": "基于给定的证据包写一段初步分析。只能引用给出的 relation_id 与 quote，不得引入外部事实。",
                "question": ev.get("question"),
                "evidence": [
                    {
                        "relation_id": c["relation_id"],
                        "quote": c.get("quote"),
                        "description": c.get("description"),
                        "lit_id": c.get("lit_id"),
                        "quote_verified": c.get("quote_verified"),
                        "status": c.get("status"),
                    }
                    for c in ev.get("claims") or []
                ],
                "criteria": verdict.get("criteria"),
                "max_confidence": verdict.get("confidence"),
                "output_format": {
                    "analysis": "字符串",
                    "conclusion": "字符串",
                    "suggestions": ["字符串"],
                    "confidence": "high|medium|low",
                },
            },
            ensure_ascii=False,
        )
        raw = self.llm.complete(prompt) if hasattr(self.llm, "complete") else self.llm(prompt)
        text = str(raw or "").strip()
        if not text:
            return None
        payload = self._parse_json_block(text)
        if payload is None:
            # 解析不出来就当作"分析文字"用，但结论与置信度仍走确定性路径 ——
            # 宁可少用一点 LLM 的产出，也不让无法解析的东西进报告。
            return {
                "analysis": text,
                "conclusion": self._deterministic_compose(ev, verdict)[1],
                "suggestions": self._deterministic_compose(ev, verdict)[2],
                "confidence": verdict.get("confidence"),
            }
        forced = _rank_min(str(payload.get("confidence") or "low"), verdict.get("confidence") or "low")
        if forced != payload.get("confidence"):
            self.last_tool_errors.append(
                {
                    "tool": "llm",
                    "error": f"LLM 试图把置信度从 {verdict.get('confidence')} 拔高到 {payload.get('confidence')}，已强制降回 {forced}",
                }
            )
        payload["confidence"] = forced
        payload.setdefault("analysis", "")
        payload.setdefault("conclusion", "")
        sugg = payload.get("suggestions") or []
        payload["suggestions"] = [str(s) for s in sugg] if isinstance(sugg, list) else [str(sugg)]
        return payload

    @staticmethod
    def _parse_json_block(text: str) -> dict | None:
        first, last = text.find("{"), text.rfind("}")
        if not (0 <= first < last):
            return None
        try:
            obj = json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None

    # ------------------------------------------------------------ 一轮完整流程

    def run_round(self, report: Any, *, submit: bool = True, limit: int | None = None) -> dict:
        """一轮完整流程（§4.1 + I1/I2）：

        ``ingest → 矛盾裁决 → (逐问题) trace → assess → 不足则 submit_gaps → poll → research``

        ``submit=False`` 表示"只评估不提问"（干跑模式），用于先看看会触发哪些判据
        而不动 A 的队列。``poll`` 放在最后：这样上一轮提交的请求（A、B 已经
        跑完）会在这一轮被拉回 researching，形成闭环。

        ## 为什么矛盾裁决排在缺口流程之前

        §1 I2 的顺序是设计的一部分：矛盾比缺口更强（它说明现有知识里有东西可能是
        错的，而不是"还不够"）。先裁决矛盾，才能保证它的 high 优先级请求在
        这一轮更早进入 A 的队列，而不是排在若干 medium 缺口之后。
        裁决结果写进 ``summary["adjudications"]``，让人看得到本轮裁了什么。

        ``submit=False``（干跑）时不裁决：裁决的落点就是"提交下一轮追问"，
        干跑模式下不做任何状态迁移是它存在的全部意义。
        """
        info = _as_report_dict(report)
        summary: dict[str, Any] = {
            "report_id": info.get("report_id"),
            "kind": info.get("kind"),
            "request": info.get("request"),
            "summary": info.get("summary"),
            "ingested": [],
            "adjudications": [],
            "traced": [],
            "assessed": [],
            "submitted": [],
            "researched": [],
            "confidence": {},
        }
        created = self.ingest(report)
        summary["ingested"] = created

        # ---- I2：先裁决"可裁决"的矛盾问题（含本次 ingest 刚建出来的新矛盾）
        summary["adjudications"] = self._adjudicate_ready_contradictions() if submit else []
        for adj in summary["adjudications"]:
            for rid in adj.get("request_ids") or []:
                summary["submitted"].append(rid)

        # ---- 本轮新提取的问题：溯源 + 评估 + 分支（足够→researching / 不足→提问）
        targets = created[: (limit if limit is not None else self.max_questions)]
        for qid in targets:
            ev = self.trace_question(qid)
            summary["traced"].append(
                {"question_id": qid, "claims": len(ev.get("claims") or []), "trace_mode": ev.get("trace_mode"),
                 "l3": len(ev.get("l3") or []), "path_chains": len(ev.get("path_chains") or [])}
            )
            verdict = self.assess(qid, ev)
            summary["confidence"][qid] = verdict["confidence"]
            if submit:
                decision = self.consider(qid)  # 足够 -> researching；不足 -> 提交请求
            else:
                # 干跑模式（submit=False）：只评估、不改状态、不提问
                decision = {
                    "question_id": qid,
                    "sufficient": verdict["sufficient"],
                    "criteria": [c["id"] for c in verdict["criteria"]],
                    "promoted": False,
                    "submitted": [],
                }
            summary["assessed"].append(
                {
                    "question_id": qid,
                    "sufficient": verdict["sufficient"],
                    "criteria": [c["id"] for c in verdict["criteria"]],
                    "priority": verdict["priority"],
                    "confidence": verdict["confidence"],
                    "hits": verdict["hits"]["distinct_hit_keywords"],
                    "degree": verdict["degree"],
                    "promoted": decision["promoted"],
                }
            )
            summary["submitted"].extend(decision["submitted"])

        # ---- [6] 复查等待集（上一轮的请求可能已经回来）
        summary["poll"] = self.poll()

        # ---- [5] 对"已就绪"的问题做初步研究（状态为 researching 的）
        #
        # 跳过 ``kind="contradiction"``：矛盾问题的推进权在 :meth:`adjudicate`
        # （它的收敛判据是裁决：resolved / persistent），而不是"写一段分析"。
        # 让 research() 也去动它，会把 needs_evidence → researching 的迁移
        # 绕过裁决做掉，于是"我还在等证据"和"我正在研究"就分不出来了。
        rows = self.store.rows("research_questions")
        for row in sorted(rows, key=lambda r: str(r.get("question_id"))):
            if row.get("status") != "researching":
                continue
            if str(row.get("kind") or "gap") == "contradiction":
                continue
            res = self.research(str(row.get("question_id")))
            summary["researched"].append(
                {
                    "question_id": res["question_id"],
                    "confidence": res["confidence"],
                    "criteria": res["criteria"],
                    "llm_used": res["llm_used"],
                }
            )
            summary["confidence"][res["question_id"]] = res["confidence"]
        return summary

    # ------------------------------------------------------------ [5'] 报告

    def _render_claims(self, claims: Sequence[Mapping[str, Any]], *, marker: str = "",
                       numbered: bool = False) -> list[str]:
        """把一组 L1 表述渲染成报告行。

        ``numbered=True`` 用于链条自身的步子：带上跳序（1./2./3.）并写出
        "概念A → 概念B"，让人能顺着读；``numbered=False`` 用于上下文，只给代号
        与出处，避免抢走链条的注意力。

        每条都带代号 + 逐字引文 + 文献与页码：这三个是一组，缺任何一个，
        "按代号溯源到相关表述"就不完整（代号是索引，引文是证据，出处是可核对性）。
        """
        out: list[str] = []
        for i, c in enumerate(claims, 1):
            pr = c.get("page_range") or {}
            pr_label = pr.get("label") or (f"pp.{pr.get('start')}-{pr.get('end')}" if pr.get("start") else "页码未知")
            names = [str(n) for n in (c.get("concept_names") or []) if n]
            if not names:
                names = [self._concept_name(str(x)) for x in (c.get("concept_ids") or [])]
            # 链条自身的步子优先用 C 给的方向（见 AgentD._chain_concept_path）：
            # 一条关系的 concept_ids 是升序的，"素理想 → 环同态"会把方向写反。
            if numbered and c.get("hop_from") and c.get("hop_to"):
                arrow = f"{c['hop_from']} → {c['hop_to']}"
            else:
                arrow = " → ".join(names) if names else "(概念名未知)"
            prefix = f"{i}. " if numbered else "- "
            head = (
                f"{prefix}`R{c['relation_id']}` {arrow}（status={c.get('status')}，"
                f"quote_verified={c.get('quote_verified')}）{marker}："
            )
            out.append(head)
            desc = str(c.get("description") or "").strip()
            if desc:
                out.append(f"   {_digest(desc, 220)}")
            out.append(f"   引文 > {_digest(c.get('quote'), 300) or '（无引文）'}")
            out.append(f"   ← 文献 `{c.get('lit_id')}`，{pr_label}")
        return out

    def write_report(self, out_path: str | Path | None = None) -> str:
        """汇总成较详细的初步研究报告（结构照 §4.5），返回写出的路径。

        每个问题一节：``问题 → 为什么值得研究（引用 C 的证据）→ 现有证据
        （L1/L2 的逐字引用 + 代号链）→ 缺口与已提交的查询 → 初步分析 →
        结论与置信度 → 后续建议``。

        报告末尾额外给一节审计信息（每条判据的中间值、用了真身还是降级替身、
        工具错误），因为"结论可复核"是本系统的核心诉求 —— 一份说不出自己
        依据的报告，读者只能选择全信或全不信。
        """
        rows = sorted(self.store.rows("research_questions"), key=lambda r: str(r.get("question_id")))
        analyses = getattr(self, "last_research", {}) or {}
        run_id = rows[-1]["question_id"] if rows else "0000"
        path = Path(out_path) if out_path else (self._reports_dir() / f"{run_id}-research.md")
        path.parent.mkdir(parents=True, exist_ok=True)

        conf_count = {"high": 0, "medium": 0, "low": 0}
        for qid, res in analyses.items():
            conf_count[res.get("confidence", "low")] = conf_count.get(res.get("confidence", "low"), 0) + 1

        lines: list[str] = []
        lines.append("# D 初步研究报告")
        lines.append("")
        lines.append(f"- 生成时间：{self._stamp()}")
        lines.append(f"- 智能体：`{self.actor}`；问题总数：{len(rows)}")
        conf_desc = "，".join(
            f"{CONFIDENCE_LABELS.get(k, k)}={v}" for k, v in conf_count.items() if v
        ) or "（本轮尚未形成任何结论）"
        lines.append(
            f"- 置信度分布：{conf_desc}（**低就是低，不因篇幅或措辞调整**；括号内为受控词表取值）"
        )
        lines.append(f"- 溯源模式：{'外部 trace_tools' if self._trace_mode_of(analyses) == 'external' else '内置降级替身'}")
        lines.append("")
        lines.append("## 0. 阅读须知")
        lines.append("")
        lines.append("1. 每条问题都带**代号溯源**（`origin` + 概念/关系代号）：任何一句结论都能回到")
        lines.append("   关系表里对应的 `quote` 去核对，这是「完全引用参考文献」要求的延续。")
        lines.append("2. 置信度由**可核实的证据量**算出（通过引文校验的条数、度数、矛盾对数），")
        lines.append("   LLM 只能调低、不能调高。")
        lines.append("3. 「知识不足」由三条可核实判据触发（关键词零命中 / 度数低且无可核验引文 / 表述互相矛盾），")
        lines.append("   不使用「感觉不够」这类无法反驳的判据。")
        lines.append("4. 每个问题都列出**对 C 的按需查询**（I1）：查了就写拿到什么，没查到就写"
                     f"{C_NO_EVIDENCE}，并且那一节的结论不作确定语气。")
        lines.append("5. 矛盾驱动的问题（I2）走**裁决闭环**：追问有轮数上限与全局配额，"
                     "用尽即标 `persistent`（交人复核），不会无限追问。")
        lines.append("")

        # ---- 状态统计
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
        lines.append("## 1. 问题台账总览")
        lines.append("")
        lines.append("| 状态 | 数量 |")
        lines.append("|---|---|")
        for k in S.QUESTION_STATUSES:
            if by_status.get(k):
                lines.append(f"| {k} | {by_status[k]} |")
        lines.append("")
        lines.append("| 问题 | 类型 | 优先级 | 状态 | 来源（代号溯源） | 等待中的请求 |")
        lines.append("|---|---|---|---|---|---|")
        for r in rows:
            kind = str(r.get("kind") or "gap")
            if kind == "contradiction":
                kind = f"contradiction({r.get('contradiction_verdict') or '待裁决'}, {r.get('contradiction_rounds') or 0} 轮)"
            lines.append(
                f"| {r.get('question_id')} | {kind} | {r.get('priority')} | {r.get('status')} | "
                f"`{_digest(r.get('origin'), 60)}` | {', '.join(r.get('waiting_request_ids') or []) or '-'} |"
            )
        lines.append("")

        # ---- 逐问题
        lines.append("## 2. 逐个问题")
        lines.append("")
        for r in rows:
            qid = str(r.get("question_id"))
            res = analyses.get(qid)
            conf = (res or {}).get("confidence", "low")
            lines.append(f"### {qid}. {r.get('question')}")
            lines.append("")
            lines.append(f"- **优先级**：{r.get('priority')}；**状态**：{r.get('status')}")
            lines.append(f"- **结论置信度**：**{_conf_label(conf)}**")
            lines.append(f"- **代号溯源**：`origin={r.get('origin')}`；")
            lines.append(
                f"  相关概念 `{', '.join(r.get('related_concept_ids') or []) or '-'}`；"
                f"相关关系 `{', '.join(r.get('related_relation_ids') or []) or '-'}`"
            )
            if str(r.get("kind") or "gap") == "contradiction":
                lines.append(
                    f"- **矛盾对（I2）**：{' vs '.join(r.get('contradiction_relation_ids') or [])}；"
                    f"裁决={r.get('contradiction_verdict') or '尚未裁决'}；追问轮数={r.get('contradiction_rounds') or 0}"
                    f"（上限 {self.max_rounds_per_contradiction}）；"
                    f"矛盾驱动请求={', '.join(r.get('contradiction_request_ids') or []) or '-'}"
                )
            lines.append("")

            lines.append("**为什么值得研究（引用 C 的证据）**")
            lines.append("")
            origin_note = self._origin_note(r)
            lines.append(f"- C 的证据：{origin_note}")
            lines.append("")

            lines.append("**现有证据（L1/L2 逐字引用 + 代号链）**")
            lines.append("")
            ev = (res or {}).get("evidence")
            # "没做"与"做了但没结果"必须分开写（本文件里反复出现的同一条原则）。
            # 早先这里把两种情况统一写成"未能取到任何关系表述（L1/L2 均为空）——这本身
            # 就是一个重要事实"，于是在"问题还没进入研究步骤"时，报告会断言一个
            # 从未做过的查询没有结果 —— 那是在报告里造假。
            # 现在：没有研究记录 ⇒ 就地补一次溯源（只读，不改任何状态），并如实标注
            # 这次证据是"本轮未研究、报告期补取"的；溯源真的返回空 ⇒ 才说 L1/L2 为空。
            traced_now = False
            if not ev:
                try:
                    ev = self.trace_question(qid)
                    traced_now = True
                except Exception as e:
                    self.last_tool_errors.append({"tool": "trace_question", "error": f"{type(e).__name__}: {e}"})
                    ev = None
            if ev is None:
                lines.append(
                    "- **溯源未执行**（`trace_question` 调用失败）：本节没有证据，"
                    f"但这不等于「查询过且没有结果」。失败原因见审计一节。"
                )
                claims = []
            else:
                claims = ev.get("claims") or []
                if traced_now and not claims:
                    lines.append(
                        f"- 本问题本轮**未进入研究步骤**（状态 {r.get('status')}）；"
                        f"此处证据为报告期补取的溯源结果：trace_mode={ev.get('trace_mode')}，L1/L2 均为空。"
                    )
                elif not claims:
                    lines.append(
                        f"- 溯源已执行（trace_mode={ev.get('trace_mode')}），但 L1/L2 **确实没有取到任何关系表述**"
                        "——这本身就是一个重要事实。"
                    )
            marker = "（报告期补取）" if traced_now else ""
            claims = list(claims)
            chain_ids = [str(x) for x in ((ev or {}).get("chain_ids") or [])]
            by_rid = {str(c["relation_id"]): c for c in claims}
            # ---- 分段：链条自身的步子（L1）vs 相关概念带来的上下文（L2）
            # 这个划分不是美化排版，而是"按代号溯源"的可读性前提：读者要能顺着链读。
            chain_claims = [by_rid[r] for r in chain_ids if r in by_rid]
            context_claims = [c for c in claims if str(c["relation_id"]) not in set(chain_ids)]

            if chain_claims:
                lines.append("")
                lines.append("**链条自身的表述（L1，按跳序）**")
                lines.append("")
                lines.extend(self._render_claims(chain_claims, marker=marker, numbered=True))
            if context_claims:
                lines.append("")
                lines.append("**相关概念的其它表述（L2，上下文，未参与本链）**")
                lines.append("")
                shown = context_claims[: self.max_l2_context]
                lines.extend(self._render_claims(shown, marker=marker, numbered=False))
                rest = len(context_claims) - len(shown)
                if rest > 0:
                    lines.append(
                        f"- …另有 **{rest}** 条上下文未展开（共 {len(context_claims)} 条）。"
                        "它们是相关概念的邻居表述，用于判断证据广度；要逐条看可用 `trace.concept`。"
                    )
            if not chain_claims and not context_claims and claims:
                # 只有链条代号却没有对应关系（链条断裂）时的兜底
                lines.extend(self._render_claims(claims, marker=marker, numbered=False))

            l2 = (ev or {}).get("l2") or []
            if l2:
                lines.append("")
                lines.append("**相关概念的定义与度数（L2）**")
                lines.append("")
            for c in l2:
                lines.append(
                    f"- `C{c['concept_id']}`「{c.get('name') or '（概念名未知）'}」定义："
                    f"{_digest(c.get('definition'), 160) or '（无定义）'}；度数 {c.get('degree')}"
                )
            for pc in (ev or {}).get("path_chains") or []:
                lines.append("")
                lines.append(f"- 关系链 `{'->'.join(pc.get('relation_ids') or [])}` 的逐步表述（`trace.chain`）：")
                lines.append("")
                lines.append("```text")
                lines.append(str(pc.get("chain_text") or "")[:2000])
                lines.append("```")
                if pc.get("missing"):
                    lines.append(f"  ⚠️ 链条断裂：关系表里找不到 {pc['missing']}")
            for t in (ev or {}).get("l3") or []:
                lines.append(
                    f"- L3 下钻 `L{t.get('lit_id')}`《{_digest(t.get('title'), 80)}》："
                    f"文件存在={t.get('file_exists')}，"
                    # 外部 trace_tools 用 has_text_layer，降级替身用 text_available；
                    # 两者都认，缺失时如实写 None 而不是假装 False。
                    f"正文可得={t.get('has_text_layer', t.get('text_available'))}，"
                    f"download_status={t.get('download_status', t.get('status'))}"
                )
            lines.append("")

            # ---- I1：C 侧按需查询（点菜记录）。这一节的存在本身就是设计：
            # "无 C 侧证据"必须是一句写在报告里的话，而不是读者自己发现的空缺。
            lines.append("**C 侧按需查询（I1）**")
            lines.append("")
            cq = [q for q in ((ev or {}).get("c_queries") or []) if isinstance(q, Mapping)]
            if not cq:
                lines.append(
                    "- 本轮**未对 C 发起按需查询**（该问题未进入研究/评估步骤，`evidence.c_queries` 为空）"
                    f"⇒ 本节{C_NO_EVIDENCE}：下面的判断未经 C 的图查询核对。"
                )
            else:
                csum = self._c_summary(cq)
                if not csum["any_success"]:
                    lines.append(
                        f"- **{C_NO_EVIDENCE}**：{csum['attempted']} 次 C 查询**全部没有成功**："
                    )
                    for f in csum["failures"]:
                        lines.append(f"  - `{f.get('api')}`：{_digest(f.get('reason'), 240)}")
                    lines.append(
                        "  - ⇒ 本节的结论只基于 D 侧溯源到的关系表述，**不作为确定结论**引用"
                        "（「没问到」不等于「不存在」）。"
                    )
                else:
                    lines.append(
                        f"- C 查询成功 {csum['ok']}/{csum['attempted']} 次（参数由本问题的代号现场推导）"
                    )
                for q in cq:
                    lines.append(
                        f"- `{q.get('api')}`(params={json.dumps(q.get('params') or {}, ensure_ascii=False)}) "
                        f"checked={q.get('checked')} truncated={q.get('truncated')} "
                        f"digest={json.dumps(q.get('digest'), ensure_ascii=False)}"
                        + (f"；reason={_digest(q.get('reason'), 200)}" if q.get("reason") else "")
                    )
            lines.append("")

            lines.append("**缺口与已提交的查询**")
            lines.append("")
            wait = r.get("waiting_request_ids") or []
            if wait:
                lines.append(f"- 已提交（等待中）：{', '.join(wait)}")
            req_index = {str(x.get("request_id")): x for x in self.store.rows("search_requests")}
            for rid in wait:
                req = req_index.get(rid) or {}
                lines.append(
                    f"  - `{rid}`：done={req.get('done')} outcome={req.get('outcome')} "
                    f"结果文献={req.get('result_lit_ids') or []}"
                )
            if not wait:
                lines.append("- 尚未提交查询请求（证据已足够，或受预算限制；详见审计一节）。")
            if (res or {}).get("criteria_detail"):
                lines.append("- 触发的可核实判据：")
                for c in res["criteria_detail"]:
                    lines.append(f"  - `{c['id']}`：{c['detail']}")
            lines.append("")

            lines.append("**初步分析**")
            lines.append("")
            if res and res.get("analysis"):
                lines.append(res["analysis"])
            elif res:
                lines.append("（有研究记录但分析为空，见审计一节的工具错误。）")
            else:
                lines.append(
                    "（本轮未运行到研究步骤：该问题未进入 `researching`，因此没有分析。"
                    "上一节给出的是报告期补取的溯源证据，不是研究结论。）"
                )
            lines.append("")

            lines.append("**结论与置信度**")
            lines.append("")
            if res and res.get("conclusion"):
                lines.append(res["conclusion"])
            elif res:
                lines.append(f"**置信度：{_conf_label(conf)}** —— 尚未形成结论。")
            else:
                # 没研究过就不给置信度：置信度是"对某组证据的判断"，
                # 没有判断却写一个"低"，看起来像结论，实则是一个没算过的数。
                lines.append(
                    "**本轮未形成结论**：该问题还没进入研究步骤（无 `research()` 记录），"
                    "因此不给出置信度 —— 没有可评估的证据时，任何档位都是编出来的。"
                )
            lines.append("")

            lines.append("**后续建议**")
            lines.append("")
            for s in (res or {}).get("suggestions") or ["（无）"]:
                lines.append(f"- {s}")
            lines.append("")
            if r.get("notes"):
                lines.append("<details><summary>研究笔记（原始记录）</summary>")
                lines.append("")
                lines.append("```")
                lines.append(str(r["notes"])[:4000])
                lines.append("```")
                lines.append("</details>")
                lines.append("")

        # ---- 审计
        lines.append("## 3. 审计信息（结论可复核性）")
        lines.append("")
        lines.append("- 工具调用错误 / 降级记录：")
        errs = getattr(self, "last_tool_errors", [])
        if not errs:
            lines.append("  - 无")
        for e in errs[-30:]:
            lines.append(f"  - `{e.get('tool')}`：{_digest(e.get('error'), 200)}")
        lines.append("")
        lines.append("- 本轮 ingest 情况：")
        ing = getattr(self, "last_ingest", {}) or {}
        lines.append(f"  - 报告 `{ing.get('report_id')}`（kind={ing.get('kind')}）：候选 {len(ing.get('candidates') or [])} 个，"
                     f"新建 {len(ing.get('created') or [])} 个")
        for s in ing.get("skipped") or []:
            lines.append(f"  - 跳过：{_digest(s, 200)}")
        # ---- §3.1：等价类合并必须可区分于"新建"（"命中了所以没建" ≠ "建了"）
        eqm = ing.get("equivalent_matched") or []
        lines.append(
            f"  - §3.1 等价类：命中已有问题而**未新建** {len(eqm)} 个；内容键合并 {len(ing.get('merged') or [])} 个"
        )
        for m in eqm:
            lines.append(
                f"    - `{m.get('origin')}` ⇒ 已存在问题 `{m.get('question_id')}`（by={m.get('by')}；{_digest(m.get('detail'), 160)}）"
            )
        cing = ing.get("contradictions") or {}
        if cing:
            lines.append(
                f"  - I2 矛盾吸收：来源={cing.get('source')} checked={cing.get('checked')} "
                f"读入 {cing.get('raw_count')} 条；{_digest(cing.get('reason'), 200)}"
            )
            for s in cing.get("skipped") or []:
                lines.append(f"    - 跳过：{_digest(s, 200)}")
            weak = cing.get("weak_clues") or []
            if weak:
                lines.append(
                    f"  - I2 **弱线索（不追问）** {len(weak)} 条：`strength != strong` 的矛盾对只记录为线索，"
                    "不建矛盾问题、不向 A 提问（弱信号假阳性极高）"
                )
                noted = {tuple(x.get("relation_ids") or []): x for x in (ing.get("weak_clues_noted") or [])}
                for w in weak:
                    key = tuple(w.get("relation_ids") or [])
                    where = noted.get(key) or {}
                    lines.append(
                        f"    - 关系 {'、'.join(key)}：{_digest(w.get('signals'), 160)}"
                        f"；落痕={where.get('question_id') or '（无共享代号的问题，仅存于本报告与 last_ingest）'}"
                    )
        lines.append("")
        lines.append("- I1 C 服务接线：")
        cw = getattr(self, "c_wiring", {}) or {}
        lines.append(f"  - mode={cw.get('mode')}：{_digest(cw.get('reason'), 240)}")
        lines.append("- I2 本轮矛盾裁决：")
        adjs = getattr(self, "last_adjudications", []) or []
        if not adjs:
            lines.append("  - 本轮没有可裁决的矛盾问题（没有 kind=contradiction 的问题，或都还有在途请求）")
        for a in adjs:
            lines.append(
                f"  - `{a.get('question_id')}`：checked={a.get('checked')} action={a.get('action')} "
                f"verdict={a.get('verdict')} code={a.get('code')} rounds={a.get('rounds_before')}→{a.get('rounds_after')} "
                f"新请求={a.get('request_ids') or []} 新问题={a.get('new_question_ids') or []}；"
                f"{_digest(a.get('reason'), 200)}"
            )
        budget = self._contradiction_budget()
        lines.append(
            f"  - 全局矛盾检索配额：{budget['used']}/{budget['limit']}"
            f"（用尽后不再追问，一律标 persistent 交人复核）"
        )
        lines.append("")
        lines.append("- poll 复检：")
        pol = getattr(self, "last_poll", {}) or {}
        lines.append(f"  - 就绪 {pol.get('ready') or []}；未就绪 {pol.get('waiting') or []}；拉回 researching {pol.get('promoted') or []}")
        for h in pol.get("held") or []:
            lines.append(
                f"  - 未推进 `{h.get('question_id')}`：{h.get('why')}"
                + (f"（优先级 {h.get('priority_before')}→{h.get('priority')}）" if h.get("why") == "irrelevant" else "")
                + f"；{_digest(h.get('reason'), 200)}"
            )
        lines.append("")
        lines.append("- 每条判据的中间值（命中数 / 度数 / 校验分布）见各问题的「触发判据」一节；")
        lines.append("  完整数值由 `AgentD.last_assessment` 保留在内存中，可另行落盘。")
        lines.append("")

        text = "\n".join(lines) + "\n"
        path.write_text(text, encoding="utf-8")
        self.last_report_path = path
        return str(path)

    def _trace_mode_of(self, analyses: dict) -> str:
        for res in analyses.values():
            if (res.get("trace_mode") or "external") != "external":
                return "fallback"
        return "external"

    def _origin_note(self, qrow: Mapping[str, Any]) -> str:
        """把 origin 里的报告号还原成 C 的报告摘要（引用 C 的证据）。"""
        origin = str(qrow.get("origin") or "")
        m = re.search(r"C:(\w+):(\d{4})", origin)
        if not m:
            return f"来源 `{origin}`（无法解析出报告号）"
        kind, rid = m.group(1), m.group(2)
        rep = next((x for x in self.store.rows("analysis_reports") if str(x.get("report_id")) == rid), None)
        if rep is None:
            return f"C 报告 `{rid}`（kind={kind}）未在 analysis_reports 中登记（报告文件可能已被移走）"
        return (
            f"C 报告 `{rid}`（kind={rep.get('kind')}，需求原文：{_digest(rep.get('request'), 80)}）的摘要："
            f"{_digest(rep.get('summary'), 300)}"
        )


# ---------------------------------------------------------------- 自检

def _selftest() -> int:
    # 运行方式：在 src/ 下执行 `python -m agentflow.agent_d`（或设 PYTHONPATH=src 后在任意目录执行）
    #
    # 自检刻意不依赖 trace_tools.py / graph_tools.py / agent_c.py：
    # 造 3~4 个概念、4~5 条关系、一个假的 C 报告对象，走完
    # ingest → trace_question → assess → submit_gaps → poll → research → write_report。
    # trace_tools 缺失时用的是 install_d_tools 注册的内置最小替身（见本文件
    # 的同名函数），自检输出里会写明实际用的是哪一种。
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 —— 理由：控制台不支持重配置（被重定向 / 非交互）时，
        # 唯一后果是中文输出乱码；而"因为控制台编码问题自检根本没跑成"是更坏的结局
        # （那会把一次真实的判定失败伪装成"没输出"）。自检的目的是报告判定结果，不是设编码。
        pass

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agentd-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时 store：{root}")

    # ---- 造数据：4 个概念、5 条关系、2 篇文献
    concepts = [
        ("0000", "阿贝尔群", "满足交换律的群"),
        ("0001", "非交换环", "乘法不满足交换律的环"),
        ("0002", "域", "每个非零元可逆的交换环"),
        ("0003", "交换性条件", "使得运算可交换的附加条件"),
    ]
    relations = [
        # rid, concept_ids, quote, verified, status, lit
        ("0000", ["0000", "0002"], "An abelian group is a group in which the commutative law holds.", True, "active", "0000"),
        ("0001", ["0000", "0003"], "The commutativity condition can be relaxed for finite rings.", True, "active", "0000"),
        ("0002", ["0001", "0003"], "交换性条件不能推广到非交换环。", None, "suspect", "0001"),
        ("0003", ["0001", "0003"], "交换性条件可以推广到非交换环。", None, "suspect", "0001"),
        ("0004", ["0000", "0001"], "Abelian groups are never non-commutative rings.", False, "suspect", "0001"),
    ]
    with st.tx("concepts", "relations", "literature", "analysis_reports", actor="seed", note="fixture") as tx:
        for cid, name, definition in concepts:
            tx.upsert(
                "concepts",
                S.Concept(concept_id=cid, name=name, definition=definition,
                          normalized_name=name, created_at=S.now_iso(), updated_at=S.now_iso()).to_dict(),
                note="seed",
            )
        for rid, cids, quote, ver, status, lid in relations:
            row = S.Relation(
                relation_id=rid,
                concept_ids=sorted(cids),
                description=quote,
                lit_id=lid,
                page_range=S.PageRange(12, 13, "pp. 12–13"),
                quote=quote,
                # 让"矛盾"这一条在真实数据里也成立：关系 0002/0003 谈同一对概念
                # （0001,0003）却给出相反表述 —— 这正是 §4.4 判据 3 要发现的。
                # 注意：0002 带否定、0003 不带，故 detect_contradictions 判定为矛盾。
                statement=quote,
                concept_group_key="|".join(sorted(cids)),
                dedup_key=f"k{rid}",
                status=status,
                quote_verified=ver,
                created_at=S.now_iso(),
            )
            row.validate()
            tx.upsert("relations", row.to_dict(), note="seed")
        for lid, title in (("0000", "Commutativity in algebra"), ("0001", "Non-commutative ring theory")):
            tx.upsert(
                "literature",
                S.Literature(lit_id=lid, title=title, type="J", summary="s", path=None,
                             processed=True, added_at=S.now_iso()).to_dict(),
                note="seed",
            )
        # 一行 C 报告登记（供 write_report 的"引用 C 的证据"使用）
        tx.upsert(
            "analysis_reports",
            S.AnalysisReport(
                report_id="0000",
                kind="paths",
                request="查询 阿贝尔群 与 域 之间的关系",
                summary="找到 2 条高信息量路径，1 条的引文通过校验，另 1 条存在互相矛盾的表述。",
                payload={"paths": []},
                markdown_path="reports/0000-paths.md",
                created_at=S.now_iso(),
            ).to_dict(),
            note="seed",
        )
    print(f"[1] 造数据：概念 {len(concepts)} 个，关系 {len(relations)} 条，文献 2 篇")

    # ---- 假的 C 报告对象（字段名与契约一致：kind/request/params/summary/payload/markdown/warnings/truncated/persist）
    class FakeCReport:
        def __init__(self) -> None:
            self.kind = "paths"
            self.request = "查询 阿贝尔群 与 域 之间的关系"
            self.params = {"a": "0000", "b": "0002"}
            self.summary = "找到 1 条高信息量路径（0000->0002）"
            # 假设的 payload 形状（与 agent_c 当前实现一致，见 _candidates_from 的 docstring）
            self.payload = {
                "paths": [
                    {
                        "concept_path": ["0000", "0002"],
                        "concept_names": ["阿贝尔群", "域"],
                        "relation_chain": ["0000"],
                        "hops": 1,
                        "level": "high",
                        "score": 3.4,
                        "score_breakdown": {"quote_verified": 2.0, "hops": 1.2, "diversity": 0.2},
                    },
                    {
                        # 这一条会落到"互相矛盾"的判据上：0001<->0003 的两条关系
                        "concept_path": ["0001", "0003"],
                        "concept_names": ["非交换环", "交换性条件"],
                        "relation_chain": ["0002", "0003"],
                        "hops": 2,
                        "level": "high",
                        "score": 2.1,
                        "score_breakdown": {"quote_verified": 0.0, "hops": 1.2, "diversity": 0.9},
                    },
                ]
            }
            self.markdown = "# fake"
            self.warnings = ["fake warn"]
            self.truncated = False

        def persist(self) -> dict:
            return {"report_id": "0000"}

    reg = install_d_tools(st)
    trace_external = load_trace_tools() is not None
    print(f"[2] 工具栏：{reg.names()}")
    print(f"    trace_tools 外部模块存在？{trace_external}（False 时用的是内置降级替身）")

    d = AgentD(st, config={"max_questions": 5, "degree_threshold": 2}, actor="agent-D", tools=reg, llm=None)

    print("[3] ingest：从假 C 报告提取候选问题")
    new_ids = d.ingest(FakeCReport())
    print(f"    新建 {len(new_ids)} 个问题：{new_ids}")
    for c in d.last_ingest["candidates"]:
        print(f"    候选：origin={c['origin']} kind={c['kind']} priority={c['priority']}")
    for s in d.last_ingest["skipped"]:
        print(f"    跳过：{s}")
    print(f"    重复 ingest（幂等性）：{d.ingest(FakeCReport())}（应为 []，origin 去重）")

    for qid in new_ids:
        print(f"[4] trace_question({qid})：L1 claims / trace_mode")
        ev = d.trace_question(qid)
        print(f"    claims={len(ev['claims'])} l2={len(ev['l2'])} trace_mode={ev['trace_mode']}")
        for c in ev["claims"][:3]:
            print(f"      R{c['relation_id']} verified={c['quote_verified']} quote={_digest(c['quote'], 60)!r}")

        print(f"[5] assess({qid})：可核实判据")
        v = d.assess(qid, ev)
        print(f"    sufficient={v['sufficient']} criteria={[c['id'] for c in v['criteria']]} "
              f"priority={v['priority']} confidence={v['confidence']} degree={v['degree']} "
              f"命中关键词={v['hits']['distinct_hit_keywords']}/{v['hits']['keyword_count']} "
              f"矛盾对={len(v['contradictions'])}")
        for c in v["criteria"]:
            print(f"      判据 {c['id']}: {_digest(c['detail'], 140)}")

        print(f"[6] submit_gaps({qid})")
        before = len(st.rows("search_requests"))
        rids = d.submit_gaps(qid)
        after = len(st.rows("search_requests"))
        print(f"    新提交请求={rids}（请求表 {before} -> {after}）")
        print(f"    再提交一次（查重）：{d.submit_gaps(qid)}  "
              f"skip={getattr(d, 'last_submit_skip', {}).get('reason')}")
        assert len(st.rows("search_requests")) == after, "查重失败：重复提交了查询请求"

    print("[7] poll：A/B 都还没跑")
    print(f"    {json.dumps(d.poll(), ensure_ascii=False)}")

    print("[8] 模拟 A 跑完 + B 消化，再次 poll")
    open_reqs = [r for r in st.rows("search_requests") if not r.get("done")]
    with st.tx("search_requests", "literature", actor="sim", note="simulate") as tx:
        for i, req in enumerate(open_reqs):
            lid = f"{10 + i:04d}"
            tx.upsert(
                "literature",
                S.Literature(lit_id=lid, title=f"simulated paper {i}", type="J", summary="s", path=None,
                             processed=False, added_at=S.now_iso()).to_dict(),
                note="sim",
            )
            req["done"] = True
            req["outcome"] = "ok"
            req["result_lit_ids"] = [lid]
            S.row_from_dict("search_requests", req).validate()
            tx.upsert("search_requests", req, note="sim_A")
    half = d.poll()
    print(f"    A 完成、B 未消化：ready={half['ready']} waiting={half['waiting']} "
          f"原因={list(half['reasons'].values())[:1]}")
    with st.tx("literature", actor="sim", note="simulate") as tx:
        for r in tx.rows("literature"):
            r["processed"] = True
            tx.upsert("literature", r, note="sim_B")
    full = d.poll()
    print(f"    A+B 都完成：ready={full['ready']} promoted={full['promoted']} merged={full['merged_relations']}")

    print("[9] research：对 researching 的问题做初步研究")
    for qid in full["promoted"] or new_ids:
        res = d.research(qid)
        print(f"    {qid} 置信度={res['confidence']} 判据={res['criteria']} llm_used={res['llm_used']} "
              f"结论={_digest(res['conclusion'], 90)}")
        print(f"      分析：{_digest(res['analysis'], 160)}")
        print(f"      建议：{res['suggestions']}")

    print("[10] LLM 不许拔高置信度：用一个「想拔高」的假 LLM 验证")
    ev = d.trace_question(new_ids[0])
    base = d.assess(new_ids[0], ev)["confidence"]

    class FakeLLM:
        def complete(self, prompt: str) -> str:
            return json.dumps(
                {"analysis": "（LLM 写的分析）", "conclusion": "（LLM 写的结论）",
                 "suggestions": ["（LLM 建议）"], "confidence": "high"},
                ensure_ascii=False,
            )

    d2 = AgentD(st, config={"max_questions": 5}, actor="agent-D", tools=reg, llm=FakeLLM())
    d2.trace_question(new_ids[0])
    got = d2._llm_refine(d2.trace_question(new_ids[0]), d2.assess(new_ids[0]))
    print(f"    确定性置信度={base}；LLM 声称=high；强制后={got['confidence']}")
    assert _rank(got["confidence"]) <= _rank(base), "置信度被拔高了！"

    print("[11] write_report")
    out = d.write_report()
    text = Path(out).read_text(encoding="utf-8")
    print(f"    写出：{out}")
    print(f"    字数：{len(text)}；行数：{text.count(chr(10))}")
    print(f"    含「置信度」小节：{'结论置信度' in text}；含代号溯源：{'origin=' in text}")

    print("[12] run_round：再来一份 gaps 报告，走完整一轮")
    class FakeGapsReport:
        kind = "gaps"
        request = "完善关系图"
        params = {"limit": 10}
        summary = "发现 1 个候选结构洞"
        payload = {
            "verdict": "有",
            "has_candidates": True,
            "candidate_gaps": [
                {"concept_ids": ["0002", "0003"], "concept_names": ["域", "交换性条件"],
                 "related_relation_ids": [], "common_neighbors": [{"concept_id": "0001", "name": "非交换环"}],
                 "reason": "有共同邻居 0001 但彼此无直接关系", "positive_signals": ["结构洞", "两概念均在热门集"],
                 "confidence": "medium"}
            ],
        }
        markdown = "# fake gaps"
        warnings: list = []
        truncated = False

    rr = d.run_round(FakeGapsReport())
    print(f"    ingested={rr['ingested']} assessed={[a['criteria'] for a in rr['assessed']]} "
          f"submitted={rr['submitted']}")
    print(f"    poll.ready={rr['poll']['ready']} researched={[(x['question_id'], x['confidence']) for x in rr['researched']]}")
    print(f"[13] 最终状态：{[ (r['question_id'], r['status'], r['priority']) for r in st.rows('research_questions') ]}")

    print("=" * 72)
    print("SELF-CHECK DONE（agent_d）")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(_selftest())
