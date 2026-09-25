"""智能体 C：关系分析（**程序做分析，LLM 只做排序与措辞**）。

## 定位（DESIGN-TOOLS.md §3.1）

需求原文是"用程序分析关系表"。所以本模块的默认实现里：

- **计数、索引、图搜索、路径枚举、去重、评分、溯源，全部是确定性代码**
  （图与索引在 `tools/graph_tools.py`，代号溯源在 `tools/trace_tools.py`）；
- 只有两处留 LLM 钩子，且**默认关闭**（构造时 `llm=None` 即可）：
  ① 路径"最合理关系链"的**排序**；② "是否值得研究"的**判断**。
  两个钩子都有确定性回退，因此**没有 API key 时功能降级但不缺失**，
  并且整条链路可以在单测里被断言（自检块就是这么做的）。

为什么要这么克制地使用 LLM：C 的产出是 D 的证据来源。如果"最热门的 5 个概念"
这种纯计数问题也过一遍模型，那么同一份数据两次运行会给出不同的报告 ——
D 无法引用一个会变的结论，人也无法审计"你凭什么说它热门"。把语义判断留在
钩子里、把事实判断钉死在代码里，是唯一能让报告**可复现**的做法。

## 四类分析器与它们各自最容易做错的地方

1. `hottest`：热度是 **occurrences**（概念在 `concept_ids` 里出现的次数），
   不是关系条数 —— 一条涉及 3 个概念的关系对其中每个概念都算 1 次出现。
   排序**必须稳定**（同分按 `concept_id` 升序），否则同分概念的相对顺序会随
   字典插入顺序漂移，报告每次都不一样。
2. `paths`：见下方"三条不让步的规则"。
3. `cold`："没人研究"（degree 小）与"没人连接"（degree=0 的完全孤立）是两件事，
   必须分开归类；否则"孤立概念"会混进冷门榜把真正的冷门方向挤掉。
4. `gaps`：需求说"**若确实有，则报告**"。所以必须有明确的"确实有/证据不足"
   二元结论，且**不允许把"没找到"包装成"找到了"** —— 那会让 D 去研究一个
   不存在的缺口，浪费一整个循环。凡被否决的候选都要留下否决理由。

## paths 的三条不让步的规则

**(a) 只按"路径不同"去重是不够的。** 两条只差一个中间节点的路径
（a-x-b 与 a-x-y-b）字面上是两条，实质上共享了绝大部分推理内容。
所以按**节点集合的 Jaccard 相似度**贪心筛：新路径与任何已选路径的重合度
`> max_overlap`（默认 0.5）就丢弃。注意是**严格大于** —— 恰好等于 0.5 时保留，
因为 a-x-b 与 a-y-b 这类"换一个中间节点"的路径正是需求要的"多条不同路径"，
它们的 Jaccard 恰好是 0.5，用 `>=` 会把它们全部误杀。

**(b) 每一跳都要重新读"全部"候选关系。** 搜索算法扩展时只是随手挑了一条边，
而这一对概念之间可能同时存在好几条关系（不同文献、不同表述）。
"最合理的链"往往不是搜索时选中的那条。取候选后按 §3.3(4) 的确定性序重选。

**(c) 评分必须能逐项打印。** 报告要给 D 的不只是"high"这个标签，而是
"为什么判成 high"：`score_breakdown` 里逐项列出每个信号的输入值与贡献值。
否则 D 只能盲信一个分数，而分数是最不该被盲信的东西。同理，**若一条 high
都没有，报告必须明说"没有找到高信息量路径"**，不许把 medium 硬凑成 high。

## 报告形态：登记表 + 文件双份（§2.2）

`AnalysisReport.payload` 是 D 溯源用的机器可读部分（代号链、评分明细），
`AnalysisReport.markdown` 是人读的部分。`persist()` 把两者分别落到
`reports/<report_id>-<kind>.md` 与 `analysis_reports` 表。

## 服务面（DESIGN-INTERACTIONS.md §1 I1 / I3 / I5）

四类分析器是**批处理**：跑一次、产一份报告、进 `analysis_reports` 表。但真实研究是
问题驱动的 —— D 在追问某个问题时需要"这两个概念之间到底有哪些链条"，而那一刻 C 早已
跑完、上次报告里没有恰好那一条。所以本模块另外提供**服务方法**（`neighbors` /
`relations_between` / `contradictions` / `structural_duplicates`）：

- **同步、只读、有界**，返回 **dict**（不产报告、不写知识表）；
- 每个结果都带 **`checked` 三态位**（`False` = 没查，`True` + `empty=True` = 查了没有）；
- 触及预算一定给 **`truncated=True`** 并说明原因 —— 静默截断会被下游读成
  "就这些"，而它是一条**口吻确定的错误结论**；
- 判据一律委托给冻结契约 `interactions`（矛盾、结构重复、冲突检查），
  **绝不在这里写第二份**。

唯一的写入路径是 `gaps(submit_requests=True)`（I3：把"应该有边却缺失"的候选直接
变成 A 的检索请求），默认**关闭**，且由 `gaps()` 的确定性代码路径完成 —— 它不经过
C 的工具与推理，写的也不是知识。工具面（`register_tools`）因此可以保持**全量只读**。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import dedup as D
from . import interactions
from . import schema as S
from . import textutil as T
from .store import Store, StoreError
from .tools.base import ToolRegistry, fail, ok, tool
from .tools.graph_tools import PathSearchResult, RelationGraph, relation_sort_key

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
]


# ---------------------------------------------------------------- 评分与阈值

#: §3.4 的评分权重，**逐字照抄设计文档**。放在这里而不是散在函数体里，
#: 是为了让"评分公式与设计文档是否一致"这件事可以被一眼核对。
#: 允许用 config 的 `score_weights` 键局部覆盖（不同学科对"多跳更有价值"的
#: 看法不同），但默认值必须与文档完全一致。
DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "quote_true": 2.0,  # 有原文支撑是最强信号
    "quote_false": -1.5,  # 引文找不到 = 可疑
    "suspect": -1.0,  # 判重存疑
    "hop": 0.6,  # 多跳 = 更多推理链（min(跳数,3) 边际递减）
    "lit_diversity": 0.8,  # 跨文献的链条更有价值
    "short_desc": -0.5,  # 描述过短 = 信息量低
    "avoid_hot": 0.5,  # 绕开了最常见节点
}

#: 判决阈值默认值。**必须能从 config 读**（§3.4 末句），所以它们只是兜底。
DEFAULT_THRESHOLD_HIGH = 3.0
DEFAULT_THRESHOLD_MEDIUM = 1.5

#: 路径信息量等级。
LEVELS = ("high", "medium", "low")

#: C 的四个分析器名（`handle` 的分派目标，也是 `graph.*` 分析工具名的一部分）。
ANALYZERS = ("hottest", "paths", "cold", "gaps")


# ---------------------------------------------------------------- I1 服务面的预算
#
# C 从"批处理"变成"服务"之后多了一类新风险：**下游可以任意多次点菜**。
# 批处理跑一次是有限成本，服务被调用 N 次就是 N 倍成本，而 N 由别人决定。
# 所以服务面的每一个参数都必须**有界**，且触及边界时**说出来**（见各方法的 truncated）。
#
# 为什么把上限写成模块常量而不是塞进函数体：它们是"服务有多贵"这件事的唯一出处，
# 分散在四个函数里之后没人能一眼回答"点一次菜最多花多少"。

#: `neighbors` 的最大跳数。
SERVICE_MAX_DEPTH = 3
#: `neighbors` 单次最多展开多少节点。
SERVICE_MAX_NODES = 500
#: `contradictions` 单次最多返回多少条矛盾（检测本身扫全表，这里限的是返回条数）。
SERVICE_MAX_CONTRADICTIONS = 50
#: `structural_duplicates` 单次最多返回多少对候选（`interactions` 另有一道枚举上限）。
SERVICE_MAX_STRUCTURAL_PAIRS = 100

#: C 提交检索请求时的**提交方身份**（I3），也决定默认优先级（`schema.SUBMITTER_DEFAULT_PRIORITY`）。
#:
#: 为什么不用 `self.actor`：`actor` 是"**这一次运行**的标签"（写进报告与事件日志，便于审计
#: 是哪次跑出来的），而 `submitted_by` 是"**提交方身份**"（配额与默认优先级按它查表）。
#: 两者混用会让 `actor="agent-C-selftest"` 这种运行标签落到"未登记的提交方"上，
#: 默认优先级静默从 medium 掉到 low —— 一次改名就把 C 的请求降级，且不会报错。
SUBMITTER = "agent-C"

#: I6 写入期闸门的**再导出**（全项目只有这一个实现，`interactions.check_conflict`）。
#:
#: ⚠️ 它**绝不能接收 store**：B 在**自己的事务内**调用它，若它去查 store 就是锁重入
#: （`filelock` 在同一进程内重入同一把锁会直接抛错，在别的实现里则是死锁）。
#: `interactions` 的导入期断言 `assert_store_free()` 就是为这件事设的。
#: C 这边只是把它**暴露到工具层**：让"写入期闸门"在 C 的工具目录里可见、可点菜，
#: 从而 B / D 都不必自己再写一份判据 —— 同一判据写在两处必然漂移，
#: 而"写入期认为不矛盾、事后 C 认为矛盾"这种分裂不会报任何错。
check_conflict = interactions.check_conflict


# ---------------------------------------------------------------- 配置读取


def _cfg_get(cfg: Mapping[str, Any], key: str, default: Any = None, *, aliases: tuple[str, ...] = ()) -> Any:
    """按 key（及别名）取配置，支持扁平的 `agent_c:` 段与嵌套的 `agent_c.score:` 段。

    为什么要支持嵌套：阈值天然属于"评分"这件事，写进 `score: {high: 3.0}` 更清楚；
    但扁平写法在测试里更省事。两种都认，免得同一份配置出现两套读法。
    """
    for k in (key, *aliases):
        if k in cfg:
            return cfg[k]
    sub = cfg.get("score")
    if isinstance(sub, Mapping):
        for k in (key, *aliases):
            if k in sub:
                return sub[k]
    return default


def _cfg_int(cfg: Mapping[str, Any], key: str, default: int, *, aliases: tuple[str, ...] = ()) -> int:
    try:
        return int(_cfg_get(cfg, key, default, aliases=aliases))
    except (TypeError, ValueError):
        return int(default)


def _cfg_float(cfg: Mapping[str, Any], key: str, default: float, *, aliases: tuple[str, ...] = ()) -> float:
    try:
        return float(_cfg_get(cfg, key, default, aliases=aliases))
    except (TypeError, ValueError):
        return float(default)


def _atomic_write_text(path: Path, text: str) -> None:
    """写临时文件 → fsync → os.replace（与 Store 落盘同一套原子语义）。

    报告文件也要原子写：D 可能在 C 写文件的同时去读它（两个进程），
    看到半份 markdown 会让它引用到不存在的段落。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------- 报告对象


@dataclass
class AnalysisReport:
    """C 的**返回对象**（注意：与 `schema.AnalysisReport` 那个"登记行"不是同一个东西）。

    为什么要分成两个类：返回对象要带 `markdown` 全文与逐项评分明细（可能很大），
    而登记行是要落进 `analysis_reports` 表的**结构化记录**。把返回对象直接当行写入，
    会让表里塞进整篇 markdown；把行当返回值用，D 就拿不到过程信息。
    `persist()` 负责把前者投影成后者，投影关系是显式的、可审计的。
    """

    kind: str
    request: str = ""
    params: dict = field(default_factory=dict)
    summary: str = ""
    payload: dict = field(default_factory=dict)
    markdown: str = ""
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False
    #: 分析是否**完成**。False 表示"这次没能给出结论"（概念解析不到、关系表为空等），
    #: 与"分析完成但结论是没找到"是两件事 —— 前者需要调用方换参数，后者就是结论。
    ok: bool = True
    error: str | None = None
    report_id: str | None = None
    markdown_path: str | None = None
    created_at: str = ""
    created_by: str = "agent-C"

    # `_store` 不作为 dataclass 字段：它是运行期句柄，不该被 to_dict 序列化，
    # 也不该参与相等比较。用普通属性挂上去（dataclass 默认允许）。
    # 有了它，`report.persist()` 才能不带参数地工作。

    def to_dict(self) -> dict:
        """机器可读视图（不含 markdown 全文的重复拷贝，markdown 单列一栏）。"""
        return {
            "kind": self.kind,
            "request": self.request,
            "params": dict(self.params),
            "summary": self.summary,
            "payload": self.payload,
            "markdown": self.markdown,
            "warnings": list(self.warnings),
            "truncated": self.truncated,
            "ok": self.ok,
            "error": self.error,
            "report_id": self.report_id,
            "markdown_path": self.markdown_path,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    # ------------------------------------------------------------ 落盘

    def persist(
        self,
        store: Store | None = None,
        *,
        actor: str | None = None,
        reports_dir: str | Path | None = None,
    ) -> dict:
        """写 markdown 文件 + 登记行（`tx` + `alloc_id("report")`）。

        **顺序是刻意的：先在事务内拿号、写文件，再写登记行、提交。**

        - 先写文件：如果反过来（先提交登记行、再写文件），一旦写文件失败，
          表里就留下一行**指向不存在文件**的记录。D 读的是登记行，它会照着
          `markdown_path` 去打开一个不存在的文件 —— 这是最坏的失败形态。
          现在的顺序最坏情况只是一个**没有登记行引用的孤儿文件**，无害且可清理。
        - 登记行与 ID 在同一事务里：`alloc_id` 必须在持锁事务内进行，否则两个
          C 实例会拿到同一个 `report_id`，而按主键 upsert 会静默互相覆盖。

        `kind` 必须是 §schema 的受控词表之一。`handle()` 在无法分派时给出的
        `kind="unknown"` **不能落盘** —— 落进表里的 report 必须能被 D 按
        `kind` 分派到对应的解析逻辑，塞一个表外的 kind 进去会让 D 的读取端出洞。
        """
        st = store or getattr(self, "_store", None)
        if st is None:
            raise ValueError(
                "persist() 需要 store：请用 AgentC 生成的报告（会自动带上 store），"
                "或显式传入 persist(store)。"
            )
        if self.kind not in S.REPORT_KINDS:
            raise ValueError(
                f"kind={self.kind!r} 不在受控词表 {S.REPORT_KINDS} 里，拒绝登记。"
                "（'unknown' 这类分派失败的结果不该进表：D 读表时无法处理表外的 kind。）"
            )
        if not self.markdown.strip():
            raise ValueError("markdown 为空，拒绝登记一个没有内容的报告。")
        if not self.summary.strip():
            raise ValueError("summary 不能为空（D 的第一入口就是它）。")
        try:
            json.dumps(self.payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"payload 必须可 JSON 序列化，否则落盘时会写坏表：{exc}"
            ) from exc

        who = actor or self.created_by or "agent-C"
        out_dir = Path(reports_dir) if reports_dir else (Path(st.root) / "reports")
        with st.tx("analysis_reports", actor=who, note=f"analysis_report:{self.kind}") as tx:
            rid = tx.alloc_id("report")
            rel_name = f"reports/{rid}-{self.kind}.md"
            abs_path = out_dir / f"{rid}-{self.kind}.md"
            _atomic_write_text(abs_path, self.markdown)
            row = S.AnalysisReport(
                report_id=rid,
                kind=self.kind,
                request=self.request,
                params=dict(self.params),
                summary=self.summary,
                payload=self.payload,
                markdown_path=rel_name,
                created_at=S.now_iso(),
                created_by=who,
            )
            row.validate()  # 早炸：summary/payload/路径不合法就别进事务
            tx.upsert("analysis_reports", row.to_dict(), note=f"persist:{self.kind}")
        self.report_id = rid
        self.markdown_path = rel_name
        self.created_at = row.created_at
        self.created_by = who
        return {"report_id": rid, "markdown_path": rel_name, "abs_path": str(abs_path)}


# ---------------------------------------------------------------- 智能体


class AgentC:
    """关系分析智能体。构造时 `llm=None` 即完全确定性（默认，也是可测试的路径）。"""

    def __init__(
        self,
        store: Store,
        config: Mapping[str, Any] | None = None,
        actor: str = "agent-C",
        llm: Any = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        #: LLM 钩子。**只需**两个可选方法（都是鸭子类型，缺任何一个都自动回退）：
        #:   `rank_paths(payload) -> list[int]`   路径顺序（§3.3(2) 第 4 步的语义部分）
        #:   `judge_gaps(payload)  -> dict`       候选缺口是否值得研究（§3.3(4) 第 2 步）
        #: 也可以只提供 `complete(prompt) -> str`，由本模块解析 JSON 结果。
        self.llm = llm
        self._graph: RelationGraph | None = None
        self.weights: dict[str, float] = dict(DEFAULT_SCORE_WEIGHTS)
        override = self.cfg.get("score_weights")
        if isinstance(override, Mapping):
            for k, v in override.items():
                if k in self.weights:
                    try:
                        self.weights[k] = float(v)
                    except (TypeError, ValueError):
                        pass
        self.threshold_high = _cfg_float(
            self.cfg, "threshold_high", DEFAULT_THRESHOLD_HIGH, aliases=("high", "high_threshold", "score_high")
        )
        self.threshold_medium = _cfg_float(
            self.cfg, "threshold_medium", DEFAULT_THRESHOLD_MEDIUM, aliases=("medium", "medium_threshold", "score_medium")
        )

    # ------------------------------------------------------------ 图

    def build_graph(self) -> RelationGraph:
        """重建并缓存关系图索引（一次构建、多次查询）。"""
        self._graph = RelationGraph.from_store(self.store)
        return self._graph

    def _g(self) -> RelationGraph:
        """取缓存的图；没有就建一次。四个分析器**共享**同一张图。"""
        if self._graph is None:
            return self.build_graph()
        return self._graph

    def _hot_ids(self, top_n: int | None = None) -> list[str]:
        """热门概念集合（`hottest` 的口径），用于评分里的"绕开最常见节点"项。"""
        g = self._g()
        n = top_n if top_n is not None else _cfg_int(self.cfg, "hot_top_n", 5)
        counts = g.counts()
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1]["occurrences"], kv[0]))
        return [cid for cid, _ in ranked[: max(0, n)]]

    # ------------------------------------------------------------ 报告工厂

    def _report(
        self,
        kind: str,
        request: str,
        params: Mapping[str, Any],
        *,
        summary: str,
        payload: Mapping[str, Any],
        markdown: str = "",
        warnings: Iterable[str] = (),
        truncated: bool = False,
        ok_: bool = True,
        error: str | None = None,
    ) -> AnalysisReport:
        rep = AnalysisReport(
            kind=kind,
            request=request,
            params=dict(params),
            summary=summary,
            payload=dict(payload),
            markdown=markdown,
            warnings=list(warnings),
            truncated=bool(truncated),
            ok=ok_,
            error=error,
            created_by=self.actor,
        )
        rep._store = self.store  # type: ignore[attr-defined]  让 report.persist() 免参数可用
        return rep

    def _md_head(self, kind: str, summary: str, warnings: Sequence[str]) -> list[str]:
        lines = [
            f"# C 分析报告：{kind}",
            "",
            f"- 生成者：`{self.actor}`",
            f"- 标题摘要：{summary}",
        ]
        if warnings:
            lines.append("- 警告：")
            lines += [f"    - {w}" for w in warnings]
        lines.append("")
        return lines

    # ============================================================ (1) hottest

    def _relation_brief_for_report(self, g: RelationGraph, rel: Mapping[str, Any], focus: str | None = None) -> dict:
        """报告里展示关系时统一用它，避免每处各写一套字段名。"""
        cids = [str(c) for c in (rel.get("concept_ids") or [])]
        return {
            "relation_id": rel.get("relation_id"),
            "concept_ids": cids,
            "concept_names": [g.name_of(c) for c in cids],
            "other_concepts": [
                {"concept_id": c, "name": g.name_of(c)} for c in cids if focus is None or c != focus
            ],
            "description": rel.get("description") or "",
            "statement": rel.get("statement") or "",
            "quoted": bool(rel.get("quote")),
            "quote_verified": rel.get("quote_verified"),
            "status": rel.get("status"),
            "lit_id": rel.get("lit_id"),
            "page_range": rel.get("page_range") or {},
        }

    def hottest(self, top_n: int = 5, request: str = "") -> AnalysisReport:
        """统计最热门的几个概念（§3.3(1)）。

        §3.3(1) 第 1 步的"出现次数"口径很关键：**对每条关系的 `concept_ids` 里
        每个概念 +1 次出现**，一条关系涉及 3 个概念就算 3 次。这不是"关系条数"：
        把"关系数"当热度，会让一个只跟"集合"发生关系的高频概念排到前面，
        而它其实只是被反复提及，并没有形成多少知识联系。
        这里由 `RelationGraph.counts()` 统一提供两种口径（occurrences 与
        relation_count），报告里两个都给，D 可以自己交叉验证。

        代表关系按 §3.3(4) 的确定性序取前 3（引文已校验优先、其次状态、
        再次信息量），**不是**随机取 3 条 —— 需求要的是"便于人工核对热度是否
        名副其实"，那就必须给最能代表这个概念的关系。
        """
        g = self._g()
        top_n = max(0, int(top_n))
        counts = g.counts()
        counts_all = dict(counts)
        warnings: list[str] = []
        if not g.relations:
            # 这两种"空"必须分清：没有关系表数据 ≠ 没有热门概念。
            return self._report(
                "hottest",
                request,
                {"top_n": top_n},
                summary="关系表为空：还没有任何关系数据可供统计（这不是'没有热门概念'，而是'数据还没进来'）。",
                payload={"entries": [], "hot_ids": [], "relation_total": 0, "concept_total": len(g.concept_by_id)},
                markdown="\n".join(
                    self._md_head("hottest", "关系表为空，无法统计热度。", ["关系表 rows 为 0"])
                    + ["## 结论", "", "关系表为空，没有可统计的对象。请先让 B 抽取关系。"]
                ),
                warnings=["关系表为空"],
            )

        ranked = sorted(counts.items(), key=lambda kv: (-kv[1]["occurrences"], kv[0]))
        top = ranked[:top_n]
        hot_ids = [cid for cid, _ in top]
        entries: list[dict] = []
        for cid, vals in top:
            rels = [g.relation_by_id[r] for r in g.concept_relations.get(cid, []) if r in g.relation_by_id]
            reps = sorted(rels, key=relation_sort_key)[:3]
            entries.append(
                {
                    "concept_id": cid,
                    "name": g.name_of(cid),
                    "occurrences": vals["occurrences"],
                    "relation_count": vals["relation_count"],
                    "group_count": vals["group_count"],
                    "degree": g.degree(cid),
                    "representative_relations": [self._relation_brief_for_report(g, r, focus=cid) for r in reps],
                }
            )
        isolated = sorted(cid for cid, v in counts.items() if v["relation_count"] == 0)
        if len(ranked) > top_n and ranked[top_n - 1][1]["occurrences"] == ranked[top_n][1]["occurrences"]:
            warnings.append(
                "第 %d 名与第 %d 名的 occurrences 相同（都是 %d）：同分按 concept_id 升序取舍，"
                "截断线附近的名次没有语义差别。" % (top_n, top_n + 1, ranked[top_n][1]["occurrences"])
            )
        payload = {
            "top_n": top_n,
            "relation_total": len(g.relations),
            "concept_total": len(counts),
            "occurrence_basis": "对每条关系的 concept_ids 里每个概念 +1 次出现（3 个概念的关系算 3 次）",
            "entries": entries,
            "hot_ids": hot_ids,
            "isolated_ids": isolated,
            "all_counts_tail": [
                {"concept_id": cid, **vals} for cid, vals in ranked[top_n : top_n + 10]
            ],
            "sort_rule": "occurrences 降序，同分按 concept_id 升序（稳定，保证可复现）",
        }
        md = self._md_head("hottest", f"最热门的 {len(entries)} 个概念（按出现次数）。", warnings)
        md += ["| 概念代号 | 概念名 | 出现次数 | 关系条数 | 概念组次数 |", "|---|---|---|---|---|"]
        md += [
            f"| {e['concept_id']} | {e['name']} | {e['occurrences']} | {e['relation_count']} | {e['group_count']} |"
            for e in entries
        ]
        md += ["", "## 代表关系（按引文校验与信息量的确定性序取前 3）", ""]
        for e in entries:
            md.append(f"### {e['name']}（{e['concept_id']}）")
            if not e["representative_relations"]:
                md.append("- （没有任何关系）")
                continue
            for r in e["representative_relations"]:
                md.append(
                    f"- `{r['relation_id']}` {r['description']}（{r['status']}，"
                    f"引文校验={r['quote_verified']}，文献 {r['lit_id']}）"
                )
        if isolated:
            md += ["", f"## 完全孤立的概念（degree=0，共 {len(isolated)} 个）：{', '.join(isolated)}", ""]
        return self._report(
            "hottest",
            request,
            {"top_n": top_n},
            summary=f"最热门的 {len(entries)} 个概念：" + "、".join(f"{e['name']}({e['occurrences']}次)" for e in entries),
            payload=payload,
            markdown="\n".join(md) + "\n",
            warnings=warnings,
        )

    # ============================================================ (2) paths

    def _score_chain(
        self,
        path_nodes: Sequence[str],
        chain_ids: Sequence[str],
        rels: Sequence[Mapping[str, Any]],
        hot_ids: Iterable[str],
    ) -> dict:
        """§3.4 的信息量评分，**返回可逐项打印的明细**。

        为什么非要"可逐项打印"：D 拿到一条 high 路径后要判断"该不该信它"。
        如果只给一个 3.47，D 唯一能做的就是相信这个数字 —— 而数字本身没有
        说服力。给出 `ratio_true=1.00 → +2.00`、`跳数=2 → +1.20` 之后，D 可以
        自己看出"这条链之所以高，是因为两跳的引文都过了校验"，也可以反驳
        "只有两跳，推理链太短"。**可解释性在这里是功能，不是装饰。**
        """
        w = self.weights
        hops = len(chain_ids)
        n = max(1, len(rels))
        verified = [r.get("quote_verified") for r in rels]
        ratio_true = sum(1 for v in verified if v is True) / n
        ratio_false = sum(1 for v in verified if v is False) / n
        ratio_suspect = sum(1 for r in rels if str(r.get("status") or "") == "suspect") / n
        n_true = sum(1 for v in verified if v is True)
        n_false = sum(1 for v in verified if v is False)
        n_none = sum(1 for v in verified if v is None)
        n_suspect = sum(1 for r in rels if str(r.get("status") or "") == "suspect")
        lits = {str(r.get("lit_id") or "") for r in rels}
        n_lits = len(lits)
        desc_lens = [len(str(r.get("description") or "").strip()) for r in rels]
        avg_desc = (sum(desc_lens) / len(desc_lens)) if desc_lens else 0.0
        hot = set(hot_ids)
        off_hot = [cid for cid in path_nodes if cid not in hot]
        avoids_top = 1.0 if off_hot else 0.0

        terms = [
            {
                "name": "引文已校验比例",
                "detail": f"quote_verified=True 的跳数 {n_true}/{hops} = {ratio_true:.2f}",
                "weight": w["quote_true"],
                "contribution": w["quote_true"] * ratio_true,
            },
            {
                "name": "引文校验失败比例",
                "detail": f"quote_verified=False 的跳数 {n_false}/{hops} = {ratio_false:.2f}",
                "weight": w["quote_false"],
                "contribution": w["quote_false"] * ratio_false,
            },
            {
                "name": "suspect 比例",
                "detail": f"status=suspect 的跳数 {n_suspect}/{hops} = {ratio_suspect:.2f}",
                "weight": w["suspect"],
                "contribution": w["suspect"] * ratio_suspect,
            },
            {
                "name": "跳数",
                "detail": f"min(跳数 {hops}, 3) = {min(hops, 3)}（边际递减）",
                "weight": w["hop"],
                "contribution": w["hop"] * min(hops, 3),
            },
            {
                "name": "跨文献多样性",
                "detail": f"不同文献 {n_lits} 篇 / 跳数 {hops} = {(n_lits / hops if hops else 0):.2f}",
                "weight": w["lit_diversity"],
                "contribution": w["lit_diversity"] * ((n_lits / hops) if hops else 0.0),
            },
            {
                "name": "描述过短",
                "detail": f"平均描述长度 {avg_desc:.1f} 字符 → {'计入' if avg_desc < 12 else '不计入'}",
                "weight": w["short_desc"],
                "contribution": w["short_desc"] * (1.0 if avg_desc < 12 else 0.0),
            },
            {
                "name": "绕开最常见节点",
                "detail": (
                    f"不在热门集里的概念 {off_hot or '无'} → {'计入' if avoids_top else '不计入'}"
                ),
                "weight": w["avoid_hot"],
                "contribution": w["avoid_hot"] * avoids_top,
            },
        ]
        total = sum(t["contribution"] for t in terms)
        level = "high" if total >= self.threshold_high else ("medium" if total >= self.threshold_medium else "low")
        for t in terms:
            t["contribution"] = round(t["contribution"], 4)
        return {
            "score": round(total, 4),
            "level": level,
            "score_breakdown": {
                "inputs": {
                    "hops": hops,
                    "quote_verified_true": n_true,
                    "quote_verified_false": n_false,
                    "quote_verified_unknown": n_none,
                    "suspect": n_suspect,
                    "distinct_literature": n_lits,
                    "average_description_length": round(avg_desc, 2),
                    "concepts_outside_hot_set": off_hot,
                    "hot_set_size": len(hot),
                },
                "terms": terms,
                "total": round(total, 4),
                "thresholds": {"high": self.threshold_high, "medium": self.threshold_medium},
                "level": level,
            },
        }

    def paths(
        self,
        a: str,
        b: str,
        *,
        max_paths: int = 5,
        max_len: int = 4,
        max_overlap: float = 0.5,
        request: str = "",
    ) -> AnalysisReport:
        """查询两个概念间的关系（§3.3(2) 的 6 步，逐条落地）。"""
        g = self._g()
        params = {"a": a, "b": b, "max_paths": max_paths, "max_len": max_len, "max_overlap": max_overlap}
        warnings: list[str] = []
        unknown = [x for x in (a, b) if x not in g.adjacency]
        if unknown:
            return self._report(
                "paths",
                request,
                params,
                summary=f"无法查询：图里没有概念 {', '.join(unknown)}。",
                payload={"unknown": unknown, "known_concepts": self._concept_candidates(g)},
                warnings=["起点或终点不存在"],
                ok_=False,
                error=f"未知概念：{unknown}",
            )
        if a == b:
            return self._report(
                "paths",
                request,
                params,
                summary="无法查询：起点与终点是同一个概念（路径长度为 0，没有意义）。",
                payload={"a": a, "b": b},
                warnings=["a == b"],
                ok_=False,
                error="a 与 b 相同",
            )

        hot_top_n = _cfg_int(self.cfg, "hot_top_n", 5)
        hot_ids = self._hot_ids(hot_top_n)
        node_budget = _cfg_int(self.cfg, "node_budget", 20000)
        search_max = _cfg_int(self.cfg, "search_max_paths", max(50, int(max_paths) * 10))

        # ---- 第 1 步：有界图搜索
        raw: PathSearchResult = g.paths(a, b, max_len=int(max_len), max_paths=search_max, node_budget=node_budget)
        # 把"未筛选前"的原始集合按跳数统计并留在 payload 里：这是回答
        # "3 跳路径到底是没有，还是被去重丢掉了"的唯一证据。没有它，
        # 读报告的人只能相信"筛选后剩几条"这个二手结论。
        raw_by_hops: dict[str, int] = {}
        for _p in raw:
            k = str(len(_p) - 1)
            raw_by_hops[k] = raw_by_hops.get(k, 0) + 1
        if raw.truncated:
            warnings.append(
                "图搜索被截断（" + "、".join(raw.reasons) + f"）；已展开 {raw.budget_used} 个节点 / "
                f"预算 {raw.node_budget}。以下结论**只覆盖已搜到的部分**，不代表'两点之间只有这些路径'。"
            )

        # ---- 第 2 步：低重合度筛选（Jaccard）
        ordered = sorted(raw, key=lambda p: (len(p), list(p)))
        kept: list[list[str]] = []
        dropped_by_overlap: list[dict] = []
        for p in ordered:
            worst: tuple[float, list[str]] | None = None
            for q in kept:
                j = g.jaccard_nodes(p, q)
                if worst is None or j > worst[0]:
                    worst = (j, q)
            if worst is not None and worst[0] > float(max_overlap):
                dropped_by_overlap.append(
                    {
                        "path": list(p),
                        "concept_names": [g.name_of(c) for c in p],
                        "max_jaccard": round(worst[0], 4),
                        "against": list(worst[1]),
                        "reason": f"与已选路径节点重合度 {worst[0]:.2f} > max_overlap={max_overlap}（本质上同一条路径）",
                    }
                )
                continue
            kept.append(p)
        selected = kept[: max(0, int(max_paths))]
        dropped_by_limit = [
            {"path": list(p), "reason": f"超过 max_paths={max_paths}，仅在统计中计数"} for p in kept[max(0, int(max_paths)) :]
        ]
        if dropped_by_limit:
            warnings.append(f"另有 {len(dropped_by_limit)} 条低重合度路径因 max_paths={max_paths} 未展开（仅在统计里计数）。")

        # ---- 第 3/4 步：每一跳读全部候选关系，再选最合理的关系
        path_items: list[dict] = []
        incomplete: list[dict] = []
        for p in selected:
            hop_details: list[dict] = []
            chain_ids: list[str] = []
            used_lits: set[str] = set()
            broken = False
            for i in range(len(p) - 1):
                cands = g.relations_between(p[i], p[i + 1])
                if not cands:
                    broken = True
                    hop_details.append(
                        {
                            "hop": i + 1,
                            "from": p[i],
                            "to": p[i + 1],
                            "candidate_count": 0,
                            "candidate_ids": [],
                            "chosen": "",
                            "note": "这一跳在图上成立但关系表里找不到对应关系（数据不一致）",
                        }
                    )
                    chain_ids.append("")
                    continue
                ranked_cands = sorted(cands, key=relation_sort_key)
                best = g.best_relation(cands, used_lits)
                assert best is not None
                lit = str(best.get("lit_id") or "")
                hop_details.append(
                    {
                        "hop": i + 1,
                        "from": p[i],
                        "from_name": g.name_of(p[i]),
                        "to": p[i + 1],
                        "to_name": g.name_of(p[i + 1]),
                        "candidate_count": len(cands),
                        "candidate_ids": [str(c.get("relation_id")) for c in ranked_cands],
                        "chosen": str(best.get("relation_id")),
                        "chosen_description": best.get("description") or "",
                        "chosen_status": best.get("status"),
                        "chosen_quote_verified": best.get("quote_verified"),
                        "chosen_lit_id": lit,
                        "chosen_lit_already_used": lit in used_lits,
                        "note": f"共 {len(cands)} 条候选，按 quote_verified→status→信息量 的确定性序取最优",
                    }
                )
                chain_ids.append(str(best.get("relation_id")))
                used_lits.add(lit)
            rels = [g.relation_by_id[r] for r in chain_ids if r in g.relation_by_id]
            if broken or len(rels) != len(chain_ids):
                incomplete.append({"concept_path": list(p), "relation_chain": chain_ids})
                warnings.append(f"路径 {p} 存在无法解析的跳，已排除出正文（数据不一致，请先 verify）。")
                continue
            scored = self._score_chain(p, chain_ids, rels, hot_ids)
            path_items.append(
                {
                    "concept_path": list(p),
                    "concept_names": [g.name_of(c) for c in p],
                    "relation_chain": chain_ids,
                    "hops": len(chain_ids),
                    "hop_details": hop_details,
                    "chain_literature_ids": sorted({str(r.get("lit_id") or "") for r in rels}),
                    "llm_ranked": False,
                    **scored,
                }
            )

        # ---- 第 4 步的 LLM 钩子（可选）：只重排顺序，不改内容
        hook_used = False
        hook_note = "未启用 LLM 钩子：路径顺序完全由确定性评分决定。"
        if self.llm is not None and path_items:
            order = self._llm_rank_paths(a, b, path_items)
            if order:
                try:
                    reordered = [path_items[i] for i in order]
                    if sorted(order) == list(range(len(path_items))):
                        for it in reordered:
                            it["llm_ranked"] = True
                        path_items = reordered
                        hook_used = True
                        hook_note = "已按 LLM 返回的顺序重排路径（内容与评分仍为确定性结果）。"
                    else:
                        warnings.append("LLM 排序钩子返回的不是一个合法排列，已回退到确定性顺序。")
                except (IndexError, TypeError) as exc:
                    warnings.append(f"LLM 排序钩子结果无法应用（{exc}），已回退到确定性顺序。")
            else:
                hook_note = "LLM 钩子存在但未给出可用排序，已回退到确定性顺序。"

        # ---- 第 5/6 步：按等级分流
        high = [it for it in path_items if it["level"] == "high"]
        medium = [it for it in path_items if it["level"] == "medium"]
        low = [it for it in path_items if it["level"] == "low"]

        if not path_items:
            if raw.truncated:
                summary = (
                    "没有找到任何完整路径，且**搜索被截断**：不能据此判断两点不连通，"
                    "请提高 node_budget/max_len 或降低 max_overlap 后重试。"
                )
            else:
                summary = "没有找到任何路径：这两点之间在给定跳数内确实不连通（这是确定性结论，搜索未被截断）。"
        elif not high:
            # 需求："若全部为 low，报告要明说'没有找到高信息量路径'，而不是硬凑。"
            summary = (
                f"**没有找到高信息量路径**（候选 {len(selected)} 条：medium {len(medium)} 条、low {len(low)} 条）。"
                f"最高分 {max((it['score'] for it in path_items), default=0):.2f}，"
                f"未达 high 阈值 {self.threshold_high}；不把 medium 当作 high 上报。"
            )
        else:
            summary = (
                f"找到 {len(high)} 条高信息量路径"
                f"（另有 medium {len(medium)} 条、low {len(low)} 条）："
                + "；".join(
                    f"{'→'.join(it['concept_names'])}（{'→'.join(it['relation_chain'])}，score={it['score']:.2f}）"
                    for it in high[:3]
                )
            )

        payload = {
            "a": {"concept_id": a, "name": g.name_of(a)},
            "b": {"concept_id": b, "name": g.name_of(b)},
            "search": {
                "raw_path_count": len(raw),
                "raw_paths": [list(p) for p in raw],
                "raw_paths_by_hops": raw_by_hops,
                "truncated": raw.truncated,
                "truncation_reasons": list(raw.reasons),
                "budget_used": raw.budget_used,
                "node_budget": raw.node_budget,
                "max_len": int(max_len),
                "search_max_paths": search_max,
            },
            "dedup": {
                "kept_after_overlap_filter": len(kept),
                "selected_for_report": len(selected),
                "max_overlap": float(max_overlap),
                "dropped_by_overlap": dropped_by_overlap,
                "dropped_by_max_paths": dropped_by_limit,
                "rule": "节点集合 Jaccard 相似度 > max_overlap 即丢弃（严格大于，等于阈值时保留）",
            },
            "levels": {"high": len(high), "medium": len(medium), "low": len(low)},
            "has_high": bool(high),
            "incomplete_paths": incomplete,
            "paths": path_items,
            "hot_ids": hot_ids,
            "hot_basis": f"occurrences 前 {hot_top_n}",
            "score_thresholds": {"high": self.threshold_high, "medium": self.threshold_medium},
            "score_weights": dict(self.weights),
            "hook": {"llm_available": self.llm is not None, "used_for_ordering": hook_used, "note": hook_note},
        }
        md = self._md_head("paths", summary, warnings)
        md += [
            f"查询：**{g.name_of(a)}（{a}）** ↔ **{g.name_of(b)}（{b}）**",
            "",
            f"- 图搜索到 {len(raw)} 条简单路径（截断={raw.truncated}，原因={raw.reasons or '无'}，"
            f"预算 {raw.budget_used}/{raw.node_budget}；按跳数分布 {raw_by_hops}）",
            f"- 低重合度筛选后保留 {len(kept)} 条，报告展开 {len(selected)} 条，"
            f"因重合度丢弃 {len(dropped_by_overlap)} 条，因 max_paths 丢弃 {len(dropped_by_limit)} 条",
            f"- 信息量判决：high {len(high)} / medium {len(medium)} / low {len(low)}",
            f"- LLM 钩子：{hook_note}",
            "",
            "## 正文（仅高信息量路径）",
            "",
        ]
        if not high:
            md.append("**没有找到高信息量路径。**（medium 见附录，low 只在统计里计数、不展开。）")
            md.append("")
        for idx, it in enumerate(high, 1):
            md += self._md_path(idx, it, g, "高")
        md += ["", "## 附录（中等信息量路径，仅供参考，**未达正文标准、不作为证据**）", ""]
        if not medium:
            md.append("（无）")
        for idx, it in enumerate(medium, 1):
            md += self._md_path(idx, it, g, "中")
        md += ["", "## 统计（低信息量路径不展开，仅计数）", ""]
        md.append(f"- 低信息量路径：{len(low)} 条；分数区间：" + (
            f"{min((it['score'] for it in low), default=0):.2f} ~ {max((it['score'] for it in low), default=0):.2f}"
            if low
            else "（无）"
        ))
        for it in low:
            md.append(
                f"    - {'→'.join(it['concept_names'])}（{'→'.join(it['relation_chain'])}，score={it['score']:.2f}，"
                f"未达 medium 阈值 {self.threshold_medium}）"
            )
        if dropped_by_overlap:
            md += ["", "## 被重合度筛掉的路径（说明去重确实起了作用）", ""]
            for d in dropped_by_overlap:
                md.append(f"- {'→'.join(d['concept_names'])}：{d['reason']}（与 {'→'.join(d['against'])} 比）")
        return self._report(
            "paths",
            request,
            params,
            summary=summary,
            payload=payload,
            markdown="\n".join(md) + "\n",
            warnings=warnings,
            truncated=bool(raw.truncated) or bool(dropped_by_limit),
        )

    def _md_path(self, idx: int, it: Mapping[str, Any], g: RelationGraph, tag: str) -> list[str]:
        """单条路径的 markdown（含逐项评分明细 —— 见 `_score_chain` 的说明）。"""
        sb = it["score_breakdown"]
        lines = [
            f"### 路径 {idx}（{tag}信息量，score={it['score']:.2f}，{it['hops']} 跳）",
            "",
            f"- 概念链：{' → '.join(f'{n}({c})' for n, c in zip(it['concept_names'], it['concept_path']))}",
            f"- **关系代号链**：{' → '.join(it['relation_chain'])}",
            f"- 涉及文献：{', '.join(it['chain_literature_ids'])}",
        ]
        for h in it["hop_details"]:
            lines.append(
                f"    - 第 {h['hop']} 跳 {h.get('from_name', h['from'])}({h['from']}) → "
                f"{h.get('to_name', h['to'])}({h['to']})：候选 {h['candidate_count']} 条 "
                f"{h['candidate_ids']}，选中 `{h['chosen']}`"
                + ("（来自已用过的文献，但可信度/信息量更优）" if h.get("chosen_lit_already_used") else "")
            )
        lines += ["", "评分明细（为什么是这个等级）：", ""]
        for t in sb["terms"]:
            sign = "+" if t["contribution"] >= 0 else ""
            lines.append(f"- {t['name']}：{t['detail']} → {sign}{t['contribution']}")
        lines += [
            "",
            f"    合计 {sb['total']}（阈值 high>={sb['thresholds']['high']} / "
            f"medium>={sb['thresholds']['medium']}）⇒ **{sb['level']}**",
            "",
        ]
        return lines

    # ============================================================ (3) cold

    def _weak_assessment(
        self,
        g: RelationGraph,
        cid: str,
        rel: Mapping[str, Any],
        others: Sequence[str],
        hot_ids: set[str],
        cold_ids: set[str],
    ) -> dict:
        """§3.3(3) 的弱连接判据（**全部可核实**，没有一条靠语感）。

        四条判据各计 1 分（`weak_score = 得分 / 4`）：
        1. `quote_verified is not True`（含 False 与 None）：引文没被证实；
        2. `status == "suspect"`：判重存疑；
        3. 它是该概念**唯一**的连接：断了这个概念就彻底孤立；
        4. 另一端也很冷门：借不到力。

        为什么用"等权计数"而不是拍一个加权分：这四个信号**没有客观的强弱次序**，
        随便定权重会变成一个无法辩护的数字。等权 + 逐条理由字符串，读者可以
        自己决定"哪条理由在这个学科里更要紧"。

        刻意**不**把 `status == "rejected"` 计进来：§3.3(3) 列的四条是"弱连接"
        信号，而 rejected 的关系语义上是"已被否决"，它不是"弱"而是"不该存在"。
        把它混进弱分会让"唯一连接是 rejected"这种极端情况被稀释成一个 0.25；
        所以单独用 `has_rejected` 标出来，交给人/D 直接处理。
        """
        points = 0
        reasons: list[str] = []
        qv = rel.get("quote_verified")
        if qv is not True:
            points += 1
            reasons.append(f"引文未获证实（quote_verified={qv}）")
        if str(rel.get("status") or "") == "suspect":
            points += 1
            reasons.append("状态为 suspect（判重存疑）")
        if g.degree(cid) <= 1:
            points += 1
            reasons.append("它是该概念唯一的连接（一旦失效该概念即完全孤立）")
        peer_degree = _cfg_int(self.cfg, "cold_weak_peer_degree", 1)
        cold_peers = sorted(
            o for o in others if o in cold_ids or g.degree(o) <= peer_degree
        )
        if cold_peers:
            points += 1
            reasons.append(
                "另一端也很冷门（无法借力）："
                + "、".join(f"{g.name_of(o)}(degree={g.degree(o)})" for o in cold_peers)
            )
        return {
            "weak_points": points,
            "weak_score": round(points / 4.0, 4),
            "weak_reasons": reasons or ["四条弱判据都不成立：引文已证实、状态正常、存在多条连接、另一端是热门概念"],
            "has_rejected": str(rel.get("status") or "") == "rejected",
        }

    def cold(self, top_n: int = 5, request: str = "") -> AnalysisReport:
        """研究冷门概念（§3.3(3)）。

        两个刻意的分类决定：

        1. **degree==0 的"完全孤立"单独归一类**，不进冷门榜。"没人研究"（有关系但少）
           与"没人连接"（一条关系都没有）需要完全不同的动作：前者可能因为冷门而被
           低估，后者更可能是抽取遗漏或概念本身不该存在。混在一起会让 top_n 被
           孤立概念占满，而它们根本列不出"与热门概念的关系"（§3.3(3) 第 2 步）。
        2. **"冷门但连接强"单独列出**：这是本分析器给 D 的核心输入。一个度数很低、
           但它与热门概念之间的连接**引文已证实、状态正常、且不是唯一连接**的概念，
           最可能是"被低估的研究点"；反过来，连接全是 suspect 的冷门概念，
           更可能是抽取噪声，不该占用 D 的循环。
        """
        g = self._g()
        top_n = max(0, int(top_n))
        counts = g.counts()
        warnings: list[str] = []
        if not g.relations:
            return self._report(
                "cold",
                request,
                {"top_n": top_n},
                summary="关系表为空：无法判断冷门（这不是'没有冷门概念'，而是'还没有关系数据'）。",
                payload={"entries": [], "isolated": [], "relation_total": 0},
                markdown="\n".join(
                    self._md_head("cold", "关系表为空，无法评估冷门概念。", ["关系表 rows 为 0"])
                    + ["## 结论", "", "关系表为空，没有可评估的对象。"]
                ),
                warnings=["关系表为空"],
            )

        isolated = sorted(cid for cid, v in counts.items() if v["relation_count"] == 0)
        candidates = sorted(
            ((cid, v) for cid, v in counts.items() if v["relation_count"] > 0),
            key=lambda kv: (kv[1]["relation_count"], kv[0]),
        )
        coldest = candidates[:top_n]
        cold_ids = {cid for cid, _ in coldest}
        hot_ids = set(self._hot_ids(max(top_n, _cfg_int(self.cfg, "hot_top_n", 5))))

        entries: list[dict] = []
        for cid, vals in coldest:
            rels = [g.relation_by_id[r] for r in g.concept_relations.get(cid, []) if r in g.relation_by_id]
            to_hot: list[dict] = []
            weak: list[dict] = []
            for rel in rels:
                others = [str(c) for c in (rel.get("concept_ids") or []) if str(c) != cid]
                wa = self._weak_assessment(g, cid, rel, others, hot_ids, cold_ids)
                brief = self._relation_brief_for_report(g, rel, focus=cid)
                item = {**brief, **wa}
                if any(o in hot_ids for o in others):
                    to_hot.append(item)
                if wa["weak_points"] > 0:
                    weak.append(item)
            strong_to_hot = [x for x in to_hot if x["weak_points"] == 0]
            entries.append(
                {
                    "concept_id": cid,
                    "name": g.name_of(cid),
                    "definition": (g.concept_by_id.get(cid) or {}).get("definition") or "",
                    "degree": g.degree(cid),
                    "occurrences": vals["occurrences"],
                    "group_count": vals["group_count"],
                    # 需求："报告冷门概念和一些热门概念间的关系"
                    "relations_to_hot": to_hot,
                    "weak_relations": weak,
                    "all_relation_count": len(rels),
                    "strong_connections_to_hot": strong_to_hot,
                    # 核心输入：是否属于"冷门但连接强"
                    "undervalued": bool(strong_to_hot),
                    "undervalued_reason": (
                        "与热门概念的连接中至少有一条不满足任何弱判据（引文已证实/状态正常/非唯一连接/另一端热门）"
                        if strong_to_hot
                        else "与热门概念的连接全部至少满足一条弱判据，或根本没有与热门概念的连接"
                    ),
                }
            )
        undervalued = [e for e in entries if e["undervalued"]]
        if not hot_ids:
            warnings.append("热门集为空（关系表没有可排名的概念），因此'与热门概念的关系'一栏为空。")

        summary = (
            f"最冷门的 {len(entries)} 个概念（degree 升序）："
            + "、".join(f"{e['name']}(degree={e['degree']})" for e in entries)
            + f"；其中'冷门但连接强'（最可能被低估）{len(undervalued)} 个："
            + ("、".join(e["name"] for e in undervalued) if undervalued else "无")
            + f"；完全孤立（degree=0）{len(isolated)} 个，单独归类。"
        )
        payload = {
            "top_n": top_n,
            "cold_ids": [e["concept_id"] for e in entries],
            "entries": entries,
            "undervalued_ids": [e["concept_id"] for e in undervalued],
            "isolated": [{"concept_id": cid, "name": g.name_of(cid)} for cid in isolated],
            "hot_ids": sorted(hot_ids),
            "weak_criteria": [
                "quote_verified is not True（引文未获证实）",
                "status == 'suspect'（判重存疑）",
                "它是该概念唯一的连接",
                "另一端概念本身也很冷门（degree <= cold_weak_peer_degree）",
            ],
            "weak_score_rule": "四条判据各计 1 分，weak_score = 得分 / 4；全部理由都写进 weak_reasons",
            "relation_total": len(g.relations),
        }
        md = self._md_head("cold", summary, warnings)
        md += [
            f"- 冷门 top{top_n}（已排除 degree=0）：{', '.join(e['name'] for e in entries)}",
            f"- 完全孤立（degree=0，单列）：{', '.join(cid for cid in isolated) if isolated else '（无）'}",
            f"- 热门集合（用于比对）：{', '.join(g.name_of(c) for c in sorted(hot_ids)) if hot_ids else '（无）'}",
            "",
        ]
        for e in entries:
            md += [f"## {e['name']}（{e['concept_id']}，degree={e['degree']}）", ""]
            if e["definition"]:
                md.append(f"定义：{e['definition']}")
            if not e["relations_to_hot"]:
                md.append("- 与热门概念之间没有任何关系（它的连接都在冷门概念之间）。")
            for r in e["relations_to_hot"]:
                mark = "**连接强**" if r["weak_points"] == 0 else f"弱（weak_score={r['weak_score']}）"
                md.append(
                    f"- `{r['relation_id']}` 与 {', '.join(o['name'] for o in r['other_concepts'])}："
                    f"{r['description']}（{r['status']}，引文校验={r['quote_verified']}）→ {mark}"
                )
                if r["weak_points"] > 0:
                    for reason in r["weak_reasons"]:
                        md.append(f"    - 弱判据：{reason}")
            md.append("")
        md += ["## 冷门但连接强（最可能被低估的研究点，给 D 的核心输入）", ""]
        if not undervalued:
            md.append("（无：所有冷门概念与热门概念的连接都至少满足一条弱判据。）")
        for e in undervalued:
            md.append(
                f"- **{e['name']}**（{e['concept_id']}，degree={e['degree']}）："
                + "；".join(
                    f"`{r['relation_id']}` 与 {'/'.join(o['name'] for o in r['other_concepts'])} 的连接"
                    f"（引文校验={r['quote_verified']}，{r['status']}）"
                    for r in e["strong_connections_to_hot"]
                )
            )
        return self._report(
            "cold",
            request,
            {"top_n": top_n},
            summary=summary,
            payload=payload,
            markdown="\n".join(md) + "\n",
            warnings=warnings,
        )

    # ============================================================ (4) gaps

    def _looks_like_non_concept(self, g: RelationGraph, cid: str) -> str | None:
        """"概念名明显不是概念"的**可核实**判据，返回理由或 None。

        只用能一眼复核的规则，不做语言模型式的判断：
        - 过长（> 24 字符且不含空格）：典型症状是整句话被当成了概念名；
        - 过短（纯 ASCII 单字母）：多半是公式符号碎片；
        - 含句读/停用词（"这个""因此""由此可见"）：抽取器的典型缺陷。
        """
        name = str((g.concept_by_id.get(cid) or {}).get("name") or "").strip()
        if not name:
            return f"{cid} 在概念表里没有名称"
        if len(name) > 24 and " " not in name:
            return f"概念名过长且无空格（{len(name)} 字符），像是整句话：{name[:24]}…"
        if len(name) == 1 and name.isascii():
            return f"概念名只有一个 ASCII 字符（{name}），像是符号碎片"
        for token in ("这个", "因此", "由此可见", "综上", "我们", "本文", "如表", "见图"):
            if token in name:
                return f"概念名含非术语成分 {token!r}：{name}"
        if re.search(r"[，。；：、,.;:!?]", name):
            return f"概念名含句读标点：{name}"
        return None

    def _concepts_relations(self, g: RelationGraph, cids: Sequence[str]) -> list[dict]:
        out: list[dict] = []
        for cid in cids:
            for rid in g.concept_relations.get(cid, []):
                rel = g.relation_by_id.get(rid)
                if rel is not None and rel not in out:
                    out.append(rel)
        return out

    def _evaluate_gap(
        self,
        g: RelationGraph,
        concepts: Sequence[str],
        *,
        kind: str,
        base_reason: str,
        common_neighbors: Sequence[str] = (),
        hot_ids: Iterable[str] = (),
    ) -> dict:
        """对一个候选缺口评估"是否确实可能有值得研究的关系"（§3.3(4) 第 2 步）。

        信号分**两档**，这个区分是需求"若确实有，则报告"能否成立的关键：

        - **否决项（veto）**：相关关系的 `quote_verified` **全部**为 False、
          概念名明显不是概念、两者已被判重（`duplicate_of` 非空）。
          这三条中的任何一条都意味着"**这条候选拿不出可核实的依据**"。
          它们**不参与净分**，而是直接把候选剔除出 `candidate_gaps`。
          为什么不能当扣分项：扣除 -0.5 之后，共同邻居、热门度、文献数这些
          正向分足以把净分抬回 medium —— 于是报告会声称"找到了值得研究的缺口"，
          而它其实**一条能在原文里找到的引文都没有**。这正是必须避免的
          "把没找到包装成找到了"。
        - **扣分项（仍参与净分）**：引文校验**部分**失败、`status=suspect` 占比、
          存在 rejected、候选端仅有单一连接。这些是"证据偏弱"而非"没有证据"，
          所以扣分但不剔除。

        正向与负向信号都留下 `signals` 文本，使"为什么被否决/为什么置信度低"
        在报告里可以被反驳，而不是一句黑箱结论。
        """
        hot = set(hot_ids)
        pos = 0.0
        neg = 0.0
        pos_signals: list[str] = []
        neg_signals: list[str] = []
        veto_reasons: list[str] = []

        cn = list(common_neighbors)
        if cn:
            add = min(len(cn), 3) * 0.5
            pos += add
            pos_signals.append(
                f"结构洞信号：有 {len(cn)} 个共同邻居（{'、'.join(g.name_of(c) for c in cn)}）却无直接关系"
            )
        hot_in = [c for c in concepts if c in hot]
        if hot_in:
            add = 0.5 * len(hot_in)
            pos += add
            pos_signals.append(f"热门概念参与：{'、'.join(g.name_of(c) for c in hot_in)} 在热门集里")
        rels = self._concepts_relations(g, concepts)
        lits = {str(r.get("lit_id") or "") for r in rels}
        if len(lits) >= 2:
            pos += 0.5
            pos_signals.append(f"文献充足：相关关系分布在 {len(lits)} 篇文献里")

        # ---------------- 否决项（veto）：直接剔除，不进 candidate_gaps
        for cid in concepts:
            why = self._looks_like_non_concept(g, cid)
            if why:
                veto_reasons.append(f"概念名明显不是概念：{why}")
        if any(r.get("duplicate_of") for r in rels):
            veto_reasons.append("相关关系里有已被判重（duplicate_of 非空）的条目：这两个概念已被判定为同一个/重复关系")
        qvs = [r.get("quote_verified") for r in rels]
        if rels and all(v is False for v in qvs):
            veto_reasons.append(
                f"相关关系的引文校验**全部**失败（{len(qvs)}/{len(qvs)} 条 quote_verified=False）："
                "这条候选没有任何能在原文里逐字核实的依据"
            )

        # ---------------- 扣分项（仍参与净分）
        n_rel = len(rels)
        n_false = sum(1 for v in qvs if v is False)
        if n_rel and 0 < n_false < n_rel:
            neg += 0.5
            neg_signals.append(f"引文校验部分失败（{n_false}/{n_rel} 条）")
        n_sus = sum(1 for r in rels if str(r.get("status") or "") == "suspect")
        if n_rel and n_sus:
            neg += 0.5 * (n_sus / n_rel)
            neg_signals.append(f"status=suspect 占 {n_sus}/{n_rel}")
        if any(str(r.get("status") or "") == "rejected" for r in rels):
            neg += 0.5
            neg_signals.append("相关关系里有 status=rejected 的条目")
        peer_degree = _cfg_int(self.cfg, "cold_weak_peer_degree", 1)
        thin = [c for c in concepts if g.degree(c) <= peer_degree]
        if thin:
            neg += 0.25 * (len(thin) / max(1, len(concepts)))
            neg_signals.append(
                "候选端连接薄弱：" + "、".join(f"{g.name_of(c)}(degree={g.degree(c)})" for c in thin)
            )

        net = pos - neg
        confidence = "high" if net >= 2.0 else ("medium" if net >= 1.0 else "low")
        key = "|".join(concepts)
        return {
            "key": key,
            "kind": kind,
            "concept_ids": list(concepts),
            "concept_names": [g.name_of(c) for c in concepts],
            "common_neighbors": [{"concept_id": c, "name": g.name_of(c)} for c in cn],
            "reason": base_reason + ("；" + "；".join(pos_signals) if pos_signals else ""),
            "positive_score": round(pos, 4),
            "negative_score": round(neg, 4),
            "net_score": round(net, 4),
            "confidence": confidence,
            "confidence_deterministic": confidence,
            #: 是否通过否决门。False ⇒ **不算候选**，无论净分多高（见 docstring）。
            "passed_veto": not veto_reasons,
            "vetoed": bool(veto_reasons),
            "veto_reasons": veto_reasons,
            "positive_signals": pos_signals,
            "negative_signals": neg_signals,
            "related_relation_ids": [str(r.get("relation_id")) for r in rels],
        }

    def gaps(self, limit: int = 10, request: str = "", *, submit_requests: bool = False) -> AnalysisReport:
        """完善关系图（§3.3(4)）：找频次少的概念组 + 结构洞，并给出**二元结论**。

        需求原文是"**若确实有，则报告**"。这句话把责任压在了实现上：
        - 必须能明确说出"确实有"或"证据不足"；
        - **不允许**把"没找到"包装成"找到了"（例如把一堆 low 置信度候选
          列在 `candidate_gaps` 里，让下游误以为发现了缺口）。

        所以 `candidate_gaps` 只收 `confidence >= medium` 的候选，其余进
        `low_confidence_candidates` 并**逐条带上被否决的理由**；
        `verdict` 字段给出"有"/"无"的二元答案，`conclusion` 给出人话结论。

        I3（缺口直连 A）：`submit_requests=True` 时，把 `candidate_gaps` 里
        通过 veto 且 confidence >= medium 的候选**直接**变成 A 的检索请求
        （`submitted_by="agent-C"`、`priority` 按 `SUBMITTER_DEFAULT_PRIORITY`、
        `mode="topical"`），单次最多 `max_gap_requests_per_run` 条、按净分降序、
        与已有未完成请求主题去重、超在途上限则**拒绝而不是排队**。
        **默认 False**（见下方那段为什么必须默认关闭）。

        I5（检测侧）：payload 里另附 `structural_duplicates` 摘要
        （结构重复概念的候选计数与少量样本；完整候选按 `graph.structural_duplicates` 取）。

        ── 为什么 I3 的写入不构成"绕过 B 引文回验"（必须写清楚，否则下一个维护者会
        以为这里有个权限漏洞，然后"顺手"把整条服务面也开成可写）──

            C 的**工具面**（`register_tools`）保持全量只读 —— C 的推理链不能写任何东西。
            I3 的 `search_requests` 写入是 `gaps()` 里的**确定性代码路径**，不经过 C 的
            工具与推理，且它写的**不是知识**（不是概念/关系/引文），而是"请 A 去查一查"
            的请求。因此它不构成"绕过 B 引文回验"的风险。这也是为什么它默认关闭、
            由编排层显式开启。
        """
        g = self._g()
        limit = max(0, int(limit))
        min_group = _cfg_int(self.cfg, "gap_group_min_count", 2)
        pair_budget = _cfg_int(self.cfg, "gap_pair_budget", 5000)
        hot_ids = self._hot_ids(_cfg_int(self.cfg, "hot_top_n", 5))
        warnings: list[str] = []
        truncated = False

        # ---- 候选 A：频次较少的概念组
        rare_groups: list[dict] = []
        for gk, cnt in sorted(g.group_counts.items()):
            if cnt >= min_group:
                continue
            cids = [c for c in gk.split("|") if c]
            if len(cids) < 2:
                continue
            rare_groups.append(
                self._evaluate_gap(
                    g,
                    cids,
                    kind="rare_group",
                    base_reason=f"概念组频次 {cnt} < 阈值 {min_group}（该组合只被研究过 {cnt} 次）",
                    common_neighbors=sorted(set(g.neighbors(cids[0])) & set(g.neighbors(cids[1]))) if len(cids) >= 2 else [],
                    hot_ids=hot_ids,
                )
            )

        # ---- 候选 B：结构洞（有共同邻居但彼此无直接关系）
        holes: dict[str, dict] = {}
        used_pairs = 0
        stop = False
        for u in sorted(g.adjacency):
            nbrs = g.neighbors(u)
            for i in range(len(nbrs)):
                if stop:
                    break
                for j in range(i + 1, len(nbrs)):
                    used_pairs += 1
                    if used_pairs > pair_budget:
                        truncated = True
                        stop = True
                        break
                    x, y = nbrs[i], nbrs[j]
                    if y in g.adjacency.get(x, {}):
                        continue  # 已有直接关系 ⇒ 不是结构洞
                    key = "|".join(sorted((x, y)))
                    holes.setdefault(key, {"concepts": sorted((x, y)), "common": []})["common"].append(u)
        if truncated:
            warnings.append(
                f"结构洞枚举触及 pair_budget={pair_budget} 被截断：只覆盖了部分三元组，"
                "**不能据此断言'没有更多结构洞'**。"
            )
        hole_candidates = [
            self._evaluate_gap(
                g,
                h["concepts"],
                kind="structural_hole",
                base_reason="结构洞：两个概念有共同邻居但彼此之间没有直接关系（'应该有边却缺失'的经典信号）",
                common_neighbors=sorted(set(h["common"])),
                hot_ids=hot_ids,
            )
            for _k, h in sorted(holes.items())
        ]

        all_cands = sorted(rare_groups + hole_candidates, key=lambda c: (-c["net_score"], c["key"]))
        # 三分法：否决项剔除 / 净分不足 / 真正的候选。
        # **只有 passed_veto 且净分 >= medium 的才进 candidate_gaps** ——
        # 这是 verdict 语义干净的前提（见 _evaluate_gap 的 docstring）。
        vetoed = [c for c in all_cands if not c["passed_veto"]]
        survivors = [c for c in all_cands if c["passed_veto"]]
        candidates = [c for c in survivors if c["confidence"] in ("high", "medium")]
        low_conf = [c for c in survivors if c["confidence"] == "low"]
        reported = candidates[:limit]
        overflow = candidates[limit:]
        if overflow:
            warnings.append(f"另有 {len(overflow)} 条中等以上置信度候选超出 limit={limit} 未展开（已在统计中计数）。")

        # ---- LLM 钩子（可选）：只加一层语义复核，确定性结论始终保留
        hook_note = "未启用 LLM 钩子：'是否值得研究'完全由确定性信号决定。"
        if self.llm is not None and reported:
            judged = self._llm_judge_gaps(reported)
            if judged is None:
                hook_note = "LLM 钩子存在但未给出可用判断，已回退到确定性结论。"
            else:
                hook_note = "已叠加 LLM 语义复核；确定性结论保留在 confidence_deterministic 字段里以便对照。"
                for c in reported:
                    v = judged.get(c["key"])
                    if not isinstance(v, Mapping):
                        continue
                    c["llm_judgement"] = dict(v)
                    conf = str(v.get("confidence") or "")
                    if conf in LEVELS:
                        c["confidence"] = conf
                    if v.get("worth") is False:
                        c["llm_worth"] = False
                        c["reason"] = c["reason"] + "；LLM 复核认为不值得研究：" + str(v.get("reason") or "")

        worth = [c for c in reported if c.get("llm_worth", True) is not False]

        # ---- I3：把候选缺口**直接**变成 A 的检索请求（默认关闭；见 docstring）
        # 放在这里（而不是函数开头）：I3 只允许用"已经算好的候选"，也就是说它
        # **不能**引入自己的判据。若把提交提前到候选确定之前，就不得不复制一份
        # veto / 置信度逻辑 —— 那正是"同一判据两处实现"的开端。
        submission = self._submit_gap_requests(worth, enabled=bool(submit_requests))
        # ---- I5 检测侧摘要（纯读；完整候选走 structural_duplicates()）
        structural = self._structural_duplicate_summary(g)

        # ---- 二元结论（需求："若确实有，则报告"）
        if worth:
            verdict = "有"
            conclusion = (
                f"确实有：发现 {len(worth)} 条值得研究的关系候选"
                f"（最高置信度 {worth[0]['confidence']}）。"
                f"检查范围：{len(g.group_counts)} 个概念组、{len(holes)} 个结构洞；"
                f"被否决项剔除 {len(vetoed)} 条、净分不足 {len(low_conf)} 条。"
            )
        else:
            verdict = "无"
            reasons: list[str] = []
            if vetoed:
                reasons.append(
                    f"{len(vetoed)} 条候选被**否决项**直接剔除"
                    "（引文全部无法核实 / 概念名不是概念 / 已被判重）—— 它们没有可核实的依据，"
                    "扣分再多也不能算'确实有'"
                )
            if low_conf:
                reasons.append(f"{len(low_conf)} 条候选净分未达 medium（正向信号被扣分项抵消）")
            if not rare_groups and not hole_candidates:
                reasons.append("既没有低频概念组，也没有结构洞")
            if reported and not worth:
                reasons.append("LLM 复核否决了全部候选")
            conclusion = (
                "证据不足：本次没有发现确实可能存在的研究关系。"
                + ("原因：" + "；".join(reasons) if reasons else "候选的信号强度不足以支持'确实有'的判断。")
            )

        summary = (
            f"{conclusion}（结构洞 {len(holes)} 个、低频概念组 {len(rare_groups)} 个、"
            f"否决 {len(vetoed)} 条、净分不足 {len(low_conf)} 条，截断={truncated}）"
        )
        payload = {
            "verdict": verdict,
            "has_candidates": bool(worth),
            "conclusion": conclusion,
            "candidate_gaps": worth,
            "rejected_by_llm": [c for c in reported if c.get("llm_worth") is False],
            #: 被否决项剔除的候选：**不算"有"**，但逐条留理由供复核。
            "vetoed_candidates": vetoed,
            "low_confidence_candidates": low_conf,
            "overflow_candidates": overflow,
            "veto_rules": [
                "相关关系的 quote_verified 全部为 False（没有任何可核实的原文依据）",
                "概念名明显不是概念（过长/纯符号/含停用词/含句读）",
                "两者已被判重（相关关系的 duplicate_of 非空）",
            ],
            "deduction_rules": [
                "引文校验部分失败（-0.5）",
                "status=suspect 占比（-0.5 × 占比）",
                "存在 status=rejected（-0.5）",
                "候选端连接薄弱（degree <= cold_weak_peer_degree，-0.25 × 占比）",
            ],
            "searched": {
                "group_count": len(g.group_counts),
                "rare_group_candidates": len(rare_groups),
                "structural_holes": len(holes),
                "triples_examined": used_pairs,
                "pair_budget": pair_budget,
                "vetoed": len(vetoed),
            },
            "thresholds": {"gap_group_min_count": min_group, "limit": limit,
                           "confidence_high_net": 2.0, "confidence_medium_net": 1.0},
            "hot_ids": hot_ids,
            "hook": {"llm_available": self.llm is not None, "note": hook_note},
            # ---- I3：直连 A 的结果（**始终存在**，关闭时是空列表 + enabled=False；
            # 用"空列表"而不是"缺键"是为了让 D 的读取端不必区分两种形状，
            # 用 enabled 位来区分"没做"与"做了没结果"—— 三态纪律见 §3.4）
            "submitted_request_ids": list(submission["submitted_request_ids"]),
            "rejected_requests": list(submission["rejected_requests"]),
            "skipped_duplicate_topics": list(submission["skipped_duplicate_topics"]),
            "request_submission": submission,
            # ---- I5 检测侧摘要
            "structural_duplicates": structural,
        }
        md = self._md_head("gaps", summary, warnings)
        md += [
            f"- **二元结论：{verdict}** —— {conclusion}",
            "",
            f"- 检索范围：概念组 {len(g.group_counts)} 个（其中低频 {len(rare_groups)} 个）、"
            f"结构洞 {len(holes)} 个（检查三元组 {used_pairs} 个，预算 {pair_budget}，截断={truncated}）",
            f"- 否决项剔除 {len(vetoed)} 条；净分不足（low）{len(low_conf)} 条",
            f"- LLM 钩子：{hook_note}",
            "",
        ]
        # ---- I3/I5 的结论也进人读的 markdown：payload 只有 D 看，而"要不要把请求
        # 排进 A 的队列"是人也需要一眼确认的事（尤其是被拒的那几条）。
        md += [
            "## I3 缺口直连 A（search_requests 写入）",
            "",
            f"- 开关：**{'开启' if submit_requests else '关闭（默认）'}** —— {submission['reason']}",
            f"- 提交：{submission['submitted_request_ids'] or '（无）'}"
            f"（单次上限 {submission['max_per_run']}，全局在途上限 {submission['inflight_limit']}）",
        ]
        for r in submission["skipped_duplicate_topics"]:
            md.append(f"- 跳过重复主题：{r['topic']} —— {r['reason']}")
        for r in submission["rejected_requests"]:
            md.append(f"- 拒绝：{r.get('topic') or r.get('key')} —— {r['reason']}")
        md += [
            "",
            "## I5 结构重复概念（检测侧摘要）",
            "",
            f"- 候选 {structural['candidate_count']} 对（merge 建议 {structural['merge_proposals']} 对 / "
            f"review {structural['review_proposals']} 对，截断={structural['truncated']}）",
            f"- {structural['method_note']}",
            f"- 完整候选按需查询：`{structural['detail_tool']}`",
            "",
            "## 候选缺口（通过了否决门，且 confidence 至少 medium）",
            "",
        ]
        if not worth:
            md.append("**没有候选达到'确实有'的标准。**（这不是'找到了但没写'，而是证据不足。）")
            md.append("")
        for c in worth:
            md += [
                f"### {c['kind']}：{' ↔ '.join(c['concept_names'])}（{c['key']}，置信度 {c['confidence']}）",
                f"- 理由：{c['reason']}",
                f"- 正向信号（{c['positive_score']}）：" + ("；".join(c["positive_signals"]) or "无"),
                f"- 负向信号（-{c['negative_score']}）：" + ("；".join(c["negative_signals"]) or "无"),
                f"- 净分 {c['net_score']}；涉及关系：{', '.join(c['related_relation_ids']) or '（无）'}",
                "",
            ]
        md += ["## 被否决项（veto）剔除的候选 —— 它们**不算**“有”", ""]
        md.append(
            "否决项的语义：候选**拿不出可核实的依据**，因此无论正向分多高都不进候选。"
            "逐条列出理由，便于独立复核“证据不足”这个结论。"
        )
        md.append("")
        if not vetoed:
            md.append("（无）")
        for c in vetoed[:20]:
            md.append(
                f"- {c['kind']} {' ↔ '.join(c['concept_names'])}（净分 {c['net_score']}，"
                f"本可判 {c['confidence_deterministic']}）：被否决 —— " + "；".join(c["veto_reasons"])
            )
        md += ["", "## 净分不足（low）的候选 —— 有依据但证据偏弱", ""]
        if not low_conf:
            md.append("（无）")
        for c in low_conf[:20]:
            md.append(
                f"- {c['kind']} {' ↔ '.join(c['concept_names'])}：净分 {c['net_score']}（正 {c['positive_score']} / 负 {c['negative_score']}）"
                + ("；" + "；".join(c["negative_signals"]) if c["negative_signals"] else "")
            )
        return self._report(
            "gaps",
            request,
            {"limit": limit},
            summary=summary,
            payload=payload,
            markdown="\n".join(md) + "\n",
            warnings=warnings,
            truncated=truncated,
        )

    # ============================================================ (5) I1 服务面
    #
    # 与上面四个分析器的分工：分析器回答"结论是什么"（产出报告、进 analysis_reports 表），
    # 服务方法回答"图上具体是什么样"（**不产出报告、不写任何表**，只回一个 dict）。
    #
    # 为什么要有这一层（DESIGN-INTERACTIONS.md §1 I1）：
    # D 在追问某个具体问题时需要"这两个概念之间到底有哪些链条"，而那一刻 C 早已跑完、
    # 上次报告里没有恰好那一条。批处理模式下 D 只能吃套餐，服务模式让它能点菜。
    #
    # 三条纪律，四个方法都遵守：
    #   1. **只读**：不调用 `store.tx`，不 upsert，连 `mark_dirty` 都不碰
    #      （C 一旦能写，就成了绕过 B 引文逐字回验的写入路径 —— 见 DESIGN §2 的硬规则）；
    #   2. **有界**：`depth` / `max_nodes` / `limit` 都被夹在服务上限内，超预算返回
    #      `truncated=True` 并说明原因，**不静默截断**；
    #   3. **三态**：`checked` 显式区分"没查"（False）与"查了没有"（True + empty=True）。

    @staticmethod
    def _service_checkable(g: RelationGraph) -> tuple[bool, str]:
        """服务面能否检查：返回 `(checked, reason)`。

        `checked=False` **只**留给"根本无法检查"这一种情况。在知识表为空时，
        "没有这个概念"与"概念表是空的"会被下游压成同一个结论
        （"图里没有它"），而后者其实是"知识还没有进来，问也问不出"。
        这两种情况需要 D 采取完全不同的动作（改查询 vs 等 A/B 先跑），
        所以必须用 `checked` 分开，而不是靠 reason 里的一句话。
        """
        if not g.concept_by_id:
            return False, (
                "概念表为空 ⇒ **没查**（不是'查了没有'）。"
                "此刻任何'图里没有这个概念'的结论都是假的：知识还没进来，"
                "请先让 A/B 把概念写进表里"
            )
        return True, ""

    def _relation_brief(self, g: RelationGraph, rel: Mapping[str, Any]) -> dict:
        """服务面返回关系时统一用它（字段清单是**契约**，不能各处各写一套）。

        `quote_verified` 原样透传（`True`/`False`/`None` 三态）—— 这里一旦"顺手"
        把 None 归一成 False，D 就无法区分"引文没校验过"与"校验失败了"，
        而这两种情况对研究决策的含义完全相反。
        """
        cids = [str(c) for c in (rel.get("concept_ids") or [])]
        return {
            "relation_id": rel.get("relation_id"),
            "concept_ids": cids,
            "concept_names": [g.name_of(c) for c in cids],
            "description": rel.get("description") or "",
            "statement": rel.get("statement") or "",
            "lit_id": rel.get("lit_id"),
            "page_range": rel.get("page_range") or {},
            "quote_verified": rel.get("quote_verified"),
            "status": rel.get("status"),
        }

    def neighbors(self, concept_id: str, *, depth: int = 1, max_nodes: int | None = None) -> dict:
        """某概念的 `depth` 跳邻域（**同步、只读、有界**）。

        返回
        ----
        ``{"checked", "concept_id", "depth", "nodes": [{concept_id, name, distance}],
           "edges": [...], "truncated", "reason", "empty", ...}``

        - `nodes` **含起点本身**（`distance=0`）。不含起点的话，"查不到这个概念"
          与"它是个孤立节点"在返回值上长得一模一样，而那两件事要求 D 做不同的事：
          前者要改查询，后者才是"这个方向确实没人研究"。
        - `empty` 的口径：**这次查询没有找到起点之外的任何节点**（孤立概念、或
          depth 内无邻居）。它与 `checked` 正交 —— `checked=True & empty=True`
          才是"查了、确实没有邻居"。
        - `depth` 与 `max_nodes` 都会被夹进服务上限（`truncated=True` + `reason` 明说）；
          触及 `max_nodes` 时**只展开到边界为止**并如实标截断。静默截断会让 D 以为
          "就这些邻居"，进而得出一个**口吻确定的错误结论**。
        - 概念不存在 ⇒ `checked=True`、`nodes=[]`、`reason` 说清"该代号不在概念表里"。
          `checked=False` 只留给"概念表为空 / 图上没有任何可查代号"。
        """
        g = self._g()
        cid = str(concept_id or "")
        checked, why = self._service_checkable(g)

        depth_ceiling = max(1, _cfg_int(self.cfg, "service_max_depth", SERVICE_MAX_DEPTH))
        node_ceiling = max(1, _cfg_int(self.cfg, "service_max_nodes", SERVICE_MAX_NODES))
        try:
            want_depth = int(depth)
        except (TypeError, ValueError):
            want_depth = 1
        try:
            want_nodes = node_ceiling if max_nodes is None else int(max_nodes)
        except (TypeError, ValueError):
            want_nodes = node_ceiling
        eff_depth = max(1, min(want_depth, depth_ceiling))
        eff_nodes = max(1, min(want_nodes, node_ceiling))

        clamped: list[str] = []
        if want_depth > depth_ceiling:
            clamped.append(
                f"请求 depth={want_depth} 超过服务上限 {depth_ceiling} ⇒ 按 {depth_ceiling} 跳计算"
            )
        if max_nodes is not None and want_nodes > node_ceiling:
            clamped.append(
                f"请求 max_nodes={want_nodes} 超过服务上限 {node_ceiling} ⇒ 按 {node_ceiling} 个节点计算"
            )

        if not checked:
            return {
                "checked": False,
                "concept_id": cid,
                "depth": eff_depth,
                "max_nodes": eff_nodes,
                "nodes": [],
                "edges": [],
                "truncated": False,
                "empty": True,
                "reason": why,
                "budget_notes": list(clamped),
            }

        if cid not in g.concept_by_id:
            return {
                "checked": True,
                "concept_id": cid,
                "depth": eff_depth,
                "max_nodes": eff_nodes,
                "nodes": [],
                "edges": [],
                "truncated": False,
                "empty": True,
                "reason": (
                    f"该代号不在概念表里：{cid}（概念表现有 {len(g.concept_by_id)} 个代号）⇒ "
                    "查过了、**没有这个概念**。这不是 checked=False —— checked=False 是'根本没查'，"
                    "请勿把两者压成同一个结论"
                ),
                "budget_notes": list(clamped),
            }

        nb = g.neighborhood(cid, depth=eff_depth, max_nodes=eff_nodes)
        nodes = list(nb["nodes"])
        edges = list(nb["edges"])
        notes = list(clamped)
        if nb["truncated"]:
            notes.append(
                f"已展开 {nb['node_count']} 个节点即触及 max_nodes={eff_nodes}"
                f"（触发原因：{'、'.join(nb['reasons'])}）"
            )
        truncated = bool(nb["truncated"]) or bool(clamped)
        empty = len(nodes) <= 1
        if empty:
            reason = (
                f"{g.name_of(cid)}（{cid}）在概念表里，但 {eff_depth} 跳内**没有任何邻居**"
                "（它是孤立概念）⇒ 查过了、确实没有邻居"
            )
        else:
            reason = (
                f"{g.name_of(cid)}（{cid}）在 {eff_depth} 跳内命中 {len(nodes) - 1} 个邻居"
                f"（含起点共 {len(nodes)} 个节点、{len(edges)} 条边）"
            )
        if truncated:
            reason += (
                "；⚠️ **结果不完整**：" + "；".join(notes)
                + "。不能据此断言'邻居就这些'——那正是静默截断最坏的形态"
            )
        return {
            "checked": True,
            "concept_id": cid,
            "name": g.name_of(cid),
            "depth": eff_depth,
            "max_nodes": eff_nodes,
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "empty": empty,
            "reason": reason,
            "budget_notes": notes,
        }

    def relations_between(self, a: str, b: str, *, include_inactive: bool = True) -> dict:
        """两个概念之间的**全部**关系（**同步、只读、有界**）。

        返回
        ----
        ``{"checked", "a", "b", "relation_ids", "relations": [精简行...],
           "empty", "reason", ...}``

        三态在这里的分工（DESIGN §3.4 明写的一条）：

        - ``relation_ids == []`` + ``empty=True`` + ``checked=True`` —— **查了，没有**；
        - ``checked=False`` —— **没查**（概念表为空，图上没有任何可查代号）。

        把前者压成后者（或反过来）会让 D 分不清"这两点确实没有关系"与"我根本没查到"，
        而前者是一条**可以写进研究结论的确定性判断**，后者只是一个待办。

        `include_inactive=False` 只过滤 `status != "active"` 的关系（判重存疑/已否决）。
        被过滤掉多少条会写进 `reason` 与 `filtered_out` —— 否则"过滤后为空"
        与"本来就没有"又是同一个形状。
        """
        g = self._g()
        aid, bid = str(a or ""), str(b or "")
        checked, why = self._service_checkable(g)
        unknown = sorted({x for x in (aid, bid) if x and x not in g.concept_by_id})
        base = {
            "a": aid,
            "b": bid,
            "a_name": g.name_of(aid) if g.concept_by_id else "",
            "b_name": g.name_of(bid) if g.concept_by_id else "",
            "include_inactive": bool(include_inactive),
            "unknown_concepts": unknown,
        }
        if not checked:
            return {**base, "checked": False, "relation_ids": [], "relations": [], "empty": True,
                    "filtered_out": 0, "reason": why}

        all_rels = g.relations_between(aid, bid)
        rels = (
            list(all_rels)
            if include_inactive
            else [r for r in all_rels if str(r.get("status") or "") == "active"]
        )
        filtered_out = len(all_rels) - len(rels)
        briefs = [self._relation_brief(g, r) for r in rels]
        empty = not briefs
        if aid == bid:
            reason = f"a 与 b 是同一个概念（{aid}）：自己与自己之间不存在关系 ⇒ 查过了、没有"
        elif empty:
            reason = f"查过了：{aid} 与 {bid} 之间没有关系（关系表这一对上是空的）"
        else:
            reason = (
                f"查到了 {len(briefs)} 条关系："
                + "、".join(str(x["relation_id"]) for x in briefs)
            )
        if filtered_out:
            reason += (
                f"；另有 {filtered_out} 条非 active 的关系被 include_inactive=False 过滤掉了"
                "（**它们确实存在**，只是本次查询不要它们）"
            )
        if unknown:
            reason += (
                f"；注意 {'、'.join(unknown)} 不在概念表里（可能只出现在关系的 concept_ids 上），"
                "因此这个名字来自图索引而非概念表"
            )
        return {
            **base,
            "checked": True,
            "relation_ids": [str(x["relation_id"]) for x in briefs],
            "relations": briefs,
            "empty": empty,
            "filtered_out": filtered_out,
            "reason": reason,
        }

    def contradictions(self, *, relation_ids: Sequence[str] | None = None, limit: int | None = None) -> dict:
        """矛盾检查（**同步、只读、有界**），判据**全部来自 `interactions`**。

        返回
        ----
        ``{"checked", "scope", "scanned", "contradictions", "strong_count", "weak_count",
           "strong_relation_id_pairs", "truncated", "limit", "method": "literal",
           "method_note", "reason"}``

        `contradictions` 里每一项保留 `interactions` 给的 `strength`
        （`strong` = 明确对立主张；`weak` = 仅否定词出现与否不一致）。**两者必须分开看**：
        实测里 `weak` 的假阳性极高，把它当矛盾呈现会让 D 去追一个不存在的问题。

        范围：给了 `relation_ids` 就用这些（I2 的"只复核这两个具体的关系"靠它 ——
        重跑整个分析既慢又会引入与本次复核无关的噪音），否则用全部关系。

        ⚠️ `method_note` **必须存在且诚实**：本方法只做**可逐字核实**的形态，
        它**不声称**能判定一般语义矛盾；而且字面判据本身还分两档（`strong` / `weak`，
        见 `interactions.detect_contradictions`）：只有 `strong`（一方明确肯定、另一方
        明确否定同一对立词组）才够格当研究线索，`weak`（仅否定词出现与否不一致）
        在真实数据上假阳性极高。把"字面检测"说成"语义分析"、或把 `weak` 线索
        说成"发现了矛盾"，都会让 D 去追一个不存在的问题。

        自己**不实现**任何判据：全部委托 `interactions.detect_contradictions`。
        两个模块各持一套判据的后果是"写入期（B 问 C）认为不矛盾、事后（C 自己扫）
        认为矛盾"这种**没有报错的静默分裂**。

        传进去的是**原始表行**（图快照里的副本），**不预先注入** `concept_pair_key`：
        那个派生字段由 `interactions` 就地推导 —— 这避免了
        "忘了算派生态 ⇒ 静默拿到空结果"这类失效（见 `_with_pair_key` 的说明）。
        """
        g = self._g()
        checked, why = self._service_checkable(g)
        lim = max(1, _cfg_int(self.cfg, "service_max_contradictions", SERVICE_MAX_CONTRADICTIONS))
        if limit is not None:
            try:
                lim = max(1, min(int(limit), lim))
            except (TypeError, ValueError):
                pass
        meta = {
            "method": "literal",
            "method_note": (
                "只做字面判据，不声称能判定一般语义矛盾。且字面判据分两档："
                "strong（明确对立主张）才可作为研究线索；"
                "weak（仅否定词出现与否不一致）在实测中假阳性极高，仅供参考。"
            ),
            "limit": lim,
        }
        if not checked:
            return {**meta, "checked": False, "scope": "none", "scanned": 0,
                    "contradictions": [], "strong_count": 0, "weak_count": 0,
                    "strong_relation_id_pairs": [], "truncated": False,
                    "missing_relation_ids": [], "reason": why}

        missing: list[str] = []
        if relation_ids is None:
            scope = "all_relations"
            rows = list(g.relations)
        else:
            scope = "given_relation_ids"
            wanted = [str(x) for x in relation_ids]
            rows = [g.relation_by_id[r] for r in wanted if r in g.relation_by_id]
            missing = sorted({r for r in wanted if r not in g.relation_by_id})
            if not rows:
                return {
                    **meta, "checked": False, "scope": scope, "scanned": 0, "contradictions": [],
                    "strong_count": 0, "weak_count": 0, "strong_relation_id_pairs": [],
                    "truncated": False, "missing_relation_ids": missing,
                    "reason": (
                        f"给定的 relation_ids（{wanted or '空'}）**一条都不在关系表里** ⇒ 没检查。"
                        "这与'检查过、不矛盾'完全不同：后者才能作为结论使用"
                    ),
                }

        # ⚠️ 传进去的是**原始表行**，**不预先注入** `concept_pair_key`。
        #
        # 曾经这里是"C 自己补一个派生字段再传进去"（因为 `relations` 表存的字段名是
        # `concept_group_key`，而 `detect_contradictions` 只读 `concept_pair_key`）。
        # 那是一个**完全静默**的失效形态：任何忘了补这一步的调用路径都会恒得到 `[]`
        # —— 不报错、不告警，看起来就像"没有矛盾"（实测同一批 25 条真实关系，
        # 直接传表行得 0 条，补过字段得 8 条）。
        # 现在 `interactions.detect_contradictions` 由 `concept_ids` **就地推导**该字段，
        # 调用方只传真源。派生字段由唯一权威实现算 —— 这避免了
        # "忘了算派生态 ⇒ 静默拿到空结果"这类失效，也避免了第二份推导规则。
        prepared = list(rows)
        found = interactions.detect_contradictions(prepared)
        truncated = len(found) > lim
        kept = found[:lim]
        # `strength` 由 interactions 判定，这里只做**分开统计**，不改判据、不改强度。
        # 为什么必须在返回值里分档：下游（D 的追问、人的复核）要能一眼看出
        # "这条是真对立"还是"这条只是否定词不一致"。混在一起报，就等于
        # 把 24% 假阳性的线索当成矛盾 —— 那会让 `status=suspect` 这个标记失去意义。
        strong = [x for x in kept if str(x.get("strength") or "") == "strong"]
        weak = [x for x in kept if str(x.get("strength") or "") != "strong"]
        reason = (
            f"范围={scope}，扫描 {len(prepared)} 条关系，命中 {len(found)} 对字面候选"
            f"（strong {sum(1 for x in found if str(x.get('strength')) == 'strong')} 对、"
            f"weak {sum(1 for x in found if str(x.get('strength')) != 'strong')} 对）"
        )
        if truncated:
            reason += f"；⚠️ 仅返回前 {lim} 对（truncated=True）：**不能据此说'只有这些矛盾'**"
        if missing:
            reason += f"；给定的 {'、'.join(missing)} 不在关系表里，未被扫描（**没查**，不是'不矛盾'）"
        if weak:
            reason += (
                f"；其中 {len(weak)} 条是 weak（仅否定词出现与否不一致），"
                "**实测假阳性极高，不得当作矛盾呈现**，只能作为继续查的线索"
            )
        if not found:
            reason += (
                "。注意这个结论的强度：它只说明'在可逐字核实的形态下没有发现矛盾'，"
                "**不等于'文献之间没有分歧'**（一般语义矛盾本方法判定不了）"
            )
        return {
            **meta,
            "checked": True,
            "scope": scope,
            "scanned": len(prepared),
            "contradictions": kept,
            "strong_count": len(strong),
            "weak_count": len(weak),
            "strong_relation_id_pairs": [list(x["relation_ids"]) for x in strong],
            "truncated": truncated,
            "missing_relation_ids": missing,
            "reason": reason,
        }

    def structural_duplicates(self, *, limit: int | None = None) -> dict:
        """结构重复概念候选（I5 的**检测侧**，**同步、只读、有界**）。

        返回
        ----
        ``{"checked", "candidates", "truncation_notice", "truncated", "scanned_concepts",
           "scanned_relations", "method", "method_note", "reason"}``

        判据全部来自 `interactions.structural_duplicate_pairs`（**不另写一份**）：
        邻域完全相同 **且** 两者之间没有直接关系 **且** 邻域非空。

        `is_truncation_notice=True` 的那条**单独**放进 `truncation_notice`，不混进
        `candidates`：它是一句"枚举被上限截断"的元信息，形状却是"一个概念对"。
        一旦混在一起，下游（尤其是不看这个字段的 LLM）会把它当成第 N 对候选，
        去 B 那里请求合并两个代号为空的概念。

        ⚠️ `method_note` 与 `proposal` 一起表达同一件事：**结构等价 ≠ 同义**。
        两个不同的概念完全可能都连着同一批邻居，所以只有结构证据时
        `proposal="review"`（其 `reason` 里写着"不得据此合并"），
        **合并决定权在 B**，且 B 必须给出理由。
        """
        g = self._g()
        checked, why = self._service_checkable(g)
        lim = max(1, _cfg_int(self.cfg, "service_max_structural_pairs", SERVICE_MAX_STRUCTURAL_PAIRS))
        if limit is not None:
            try:
                lim = max(1, min(int(limit), lim))
            except (TypeError, ValueError):
                pass
        meta = {
            "method": "structural_neighborhood_equality",
            "method_note": (
                "只做'邻域完全相同 + 两者之间无直接关系'的结构判据；"
                "结构等价 ≠ 同义（两个不同概念可能连着同一批邻居），"
                "因此只有结构证据时只给 proposal=review，合并决定权在 B"
            ),
            "limit": lim,
        }
        if not checked:
            return {**meta, "checked": False, "candidates": [], "truncation_notice": None,
                    "truncated": False, "scanned_concepts": 0, "scanned_relations": 0, "reason": why}

        pairs = self._structural_pairs(g)
        notices = [p for p in pairs if p.get("is_truncation_notice")]
        cands = [p for p in pairs if not p.get("is_truncation_notice")]
        truncated = bool(notices) or len(cands) > lim
        kept = cands[:lim]
        merge_n = sum(1 for p in kept if p.get("proposal") == "merge")
        reason = (
            f"扫描 {len(g.concept_by_id)} 个概念、{len(g.relations)} 条关系，"
            f"命中 {len(cands)} 对结构等价候选（其中 {merge_n} 对名字侧也有证据 ⇒ proposal=merge，"
            f"其余 {len(kept) - merge_n} 对只有结构证据 ⇒ proposal=review，**不得据此合并**）"
        )
        if len(cands) > lim:
            reason += f"；⚠️ 仅返回前 {lim} 对（truncated=True）：不能说'只有这些结构重复'"
        if notices:
            reason += "；枚举本身触及 interactions 的 max_pairs 上限，已单列 truncation_notice"
        if not cands:
            reason += "。这是'查过了、没有'（checked=True），不是'没查'"
        return {
            **meta,
            "checked": True,
            "candidates": kept,
            "truncation_notice": notices[0] if notices else None,
            "truncated": truncated,
            "scanned_concepts": len(g.concept_by_id),
            "scanned_relations": len(g.relations),
            "reason": reason,
        }

    # ------------------------------------------------------------ I5 结构重复：共享调用口 + 摘要

    def _structural_pairs(self, g: RelationGraph) -> list[dict]:
        """`interactions.structural_duplicate_pairs` 的**唯一**调用口（含枚举上限配置）。

        为什么把枚举上限做成可配置：`interactions` 的上限（默认 200 对）是防 O(n²) 爆炸的，
        而"触及上限"这件事**必须能测**——否则"截断通知被单列"这条约束永远只有正向用例，
        而负控（通知混进 candidates）就没人拦得住。测试里把上限调到 1 即可覆盖。
        """
        mp = _cfg_get(self.cfg, "structural_duplicate_max_pairs", None)
        try:
            cap: int | None = None if mp is None else int(mp)
        except (TypeError, ValueError):
            cap = None
        return interactions.structural_duplicate_pairs(g.concepts, g.relations, max_pairs=cap)

    def _structural_duplicate_summary(self, g: RelationGraph) -> dict:
        """`gaps` payload 里的结构重复摘要（I5 检测侧，**纯读、不写表**）。

        为什么把检测放在 `gaps` 里也带一份：`gaps` 的候选是"**应该有边却缺失**"，
        而结构重复正是它的**对偶**问题 —— 已经有两条边（两个代号）其实是同一个东西。
        两者一起看，D 才不会一边给"缺边"的靶子、一边对重复节点视而不见。
        摘要只给计数与少量样本：完整候选走 `structural_duplicates()`，
        免得 `gaps` 的 payload 被一份可以随时再查的清单撑大（报告要可读、可存）。
        """
        pairs = self._structural_pairs(g)
        cands = [p for p in pairs if not p.get("is_truncation_notice")]
        notices = [p for p in pairs if p.get("is_truncation_notice")]
        return {
            "checked": bool(g.concept_by_id),
            "candidate_count": len(cands),
            "merge_proposals": sum(1 for p in cands if p.get("proposal") == "merge"),
            "review_proposals": sum(1 for p in cands if p.get("proposal") == "review"),
            "truncated": bool(notices),
            "sample": [
                {
                    "concept_ids": p.get("concept_ids"),
                    "concept_names": p.get("concept_names"),
                    "proposal": p.get("proposal"),
                    "name_evidence": p.get("name_evidence"),
                }
                for p in cands[:5]
            ],
            "method_note": "结构等价 ≠ 同义：只有结构证据时 proposal=review，合并决定权在 B",
            "detail_tool": "graph.structural_duplicates（按需取完整候选）",
        }

    # ------------------------------------------------------------ I3 缺口直连 A

    def _submit_gap_requests(self, candidates: Sequence[Mapping[str, Any]], *, enabled: bool) -> dict:
        """把 `gaps` 的候选直接变成 A 的检索请求（I3，**唯一的确定性写入路径**）。

        默认**关闭**。开启时的全部动作都在**一个** `store.tx("search_requests")` 里完成
        —— 不是"图省事"，而是因为配额判定（`admit_search_request`）与写入必须看到
        **同一份**在途清单：分成两个事务的话，两次判定之间另一个提交方可能已经占满配额，
        于是"闸门说可以"与"实际写进去"不再对应，配额形同虚设。

        三条闸门（缺一条都会把 A 的队列淹掉）：
        1. 只收**通过 veto 且 confidence >= medium** 的候选 —— 它们就是 `gaps` 里
           已经算好的 `candidate_gaps`。不达标却硬提，等于把"证据不足"洗成"去查一查"；
        2. 单次最多 `interactions.DEFAULTS["max_gap_requests_per_run"]` 条，按净分降序；
        3. 全局在途上限由 `interactions.admit_search_request` 判定，**超限就拒绝**
           并把理由留在 `rejected_requests` 里 —— 拒绝会把压力传导回提交方，
           而"无限排队"只会让所有请求（包括最关键的那条矛盾）一起变慢。

        主题去重与已有**未完成**请求比对（复用 `textutil.normalize`，不另写规范化）。
        去重放在配额闸门**之前**：一个重复主题的正确标签是"跳过重复"，
        而不是"因配额被拒" —— 后者会让报告把"本来就不该提交"说成"资源不够"。
        """
        max_per_run = int(interactions.DEFAULTS["max_gap_requests_per_run"])
        out: dict = {
            "enabled": bool(enabled),
            "attempted": 0,
            "max_per_run": max_per_run,
            "inflight_limit": int(interactions.DEFAULTS["max_inflight_requests"]),
            "submitted_request_ids": [],
            "rejected_requests": [],
            "skipped_duplicate_topics": [],
            "reason": "",
        }
        if not enabled:
            out["reason"] = (
                "submit_requests=False（默认）：C 不写 search_requests。"
                "C 的工具面保持**全量只读**，写入只可能来自编排层显式开启这条确定性代码路径"
            )
            return out

        eligible = [
            c
            for c in candidates
            if c.get("passed_veto") and str(c.get("confidence") or "") in ("high", "medium")
        ]
        ordered = sorted(
            eligible, key=lambda c: (-float(c.get("net_score") or 0.0), str(c.get("key") or ""))
        )
        out["attempted"] = len(ordered)
        if not ordered:
            out["reason"] = (
                "本次 gaps 没有'通过 veto 且 confidence >= medium'的候选 ⇒ 没有可提交的请求"
                "（这是'查了、没有'，不是'没查'）"
            )
            return out

        prio, prio_why = interactions.resolve_priority(SUBMITTER, None)
        with self.store.tx(
            "search_requests", actor=SUBMITTER, note=f"gaps:submit_requests(run_by={self.actor})"
        ) as tx:
            rows = tx.rows("search_requests")
            open_topics = {
                T.normalize(str(r.get("topic") or ""))
                for r in interactions.inflight_requests(rows)
            }
            open_topics.discard("")
            for cand in ordered:
                topic = "、".join(str(n) for n in (cand.get("concept_names") or []) if str(n))
                key = str(cand.get("key") or "")
                if not topic.strip():
                    out["rejected_requests"].append(
                        {"key": key, "topic": topic, "reason": "候选没有概念名，构造不出 topic；空 topic 会让 A 无从查询"}
                    )
                    continue
                tnorm = T.normalize(topic)
                if tnorm and tnorm in open_topics:
                    out["skipped_duplicate_topics"].append(
                        {
                            "key": key,
                            "topic": topic,
                            "reason": "已存在同主题的未完成请求（主题规范化后相同）⇒ 跳过，不重复排进 A 的队列",
                        }
                    )
                    continue
                if len(out["submitted_request_ids"]) >= max_per_run:
                    out["rejected_requests"].append(
                        {
                            "key": key,
                            "topic": topic,
                            "reason": (
                                f"本次 gaps 已达每轮上限 max_gap_requests_per_run={max_per_run} ⇒ 未提交。"
                                "显式拒绝而不是无限排队：无上限的队列会让最关键的那条请求也一起变慢"
                            ),
                        }
                    )
                    continue
                admit = interactions.admit_search_request(
                    rows, submitted_by=SUBMITTER, explicit_priority=prio, for_question_id=None
                )
                if not admit.get("admitted"):
                    out["rejected_requests"].append(
                        {"key": key, "topic": topic, "priority": admit.get("priority"), "reason": admit.get("reason")}
                    )
                    continue
                rid = interactions.next_prefixed_id(rows, "request_id", "r")
                row = S.SearchRequest(
                    request_id=rid,
                    timestamp=S.now_iso(),
                    topic=topic,
                    mode="topical",
                    content_description=str(cand.get("reason") or ""),
                    done=False,
                    submitted_by=SUBMITTER,
                    priority=str(admit.get("priority") or prio),
                    for_question_id=None,
                    submit_note=(
                        f"由 C.gaps 直连 A（I3）：候选 kind={cand.get('kind')}、key={key}、"
                        f"net_score={cand.get('net_score')}、confidence={cand.get('confidence')}；"
                        f"优先级理由：{prio_why}"
                    ),
                )
                row.validate()  # 早炸：schema 就在手边，别等落盘时才在 store 里炸
                tx.upsert("search_requests", row.to_dict(), note="gaps:submit_gap_request")
                out["submitted_request_ids"].append(rid)
                if tnorm:
                    open_topics.add(tnorm)

        out["reason"] = (
            f"提交 {len(out['submitted_request_ids'])} 条（上限 {max_per_run}，优先级 {prio}：{prio_why}）；"
            f"跳过重复主题 {len(out['skipped_duplicate_topics'])} 条；"
            f"拒绝 {len(out['rejected_requests'])} 条（理由逐条留在 rejected_requests 里）"
        )
        return out

    # ============================================================ LLM 钩子

    def _llm_rank_paths(self, a: str, b: str, items: Sequence[Mapping[str, Any]]) -> list[int] | None:
        """① 路径排序钩子。**失败一律回退到确定性顺序**，绝不因钩子而丢掉结果。

        钩子只被允许做一件事：给一个排列。它**不能**改分数、不能删路径 ——
        那样"可解释的确定性评分"就会被一个不可复现的模型输出悄悄替换掉。
        """
        compact = [
            {
                "index": i,
                "concepts": list(it["concept_names"]),
                "relations": list(it["relation_chain"]),
                "score": it["score"],
                "level": it["level"],
                "descriptions": [h.get("chosen_description", "") for h in it["hop_details"]],
            }
            for i, it in enumerate(items)
        ]
        try:
            fn = getattr(self.llm, "rank_paths", None)
            if callable(fn):
                out = fn({"a": a, "b": b, "paths": compact})
            elif hasattr(self.llm, "complete"):
                prompt = (
                    "下面是同一对概念之间的若干条路径。请只输出一个 JSON 数组，"
                    "按'关系链最合理'从高到低给出路径的 index，不要输出任何解释。\n"
                    + json.dumps(compact, ensure_ascii=False)
                )
                out = json.loads(str(self.llm.complete(prompt)).strip())
            else:
                return None
            if isinstance(out, Mapping):
                out = out.get("order") or out.get("indices")
            if isinstance(out, (list, tuple)):
                idx = [int(x) for x in out]
                if sorted(idx) == list(range(len(items))):
                    return idx
            return None
        except Exception:  # noqa: BLE001 - 钩子的任何异常都不该影响主流程
            return None

    def _llm_judge_gaps(self, candidates: Sequence[Mapping[str, Any]]) -> dict | None:
        """② "是否值得研究"钩子。同样只叠加、不替换确定性结论。"""
        compact = [
            {
                "key": c["key"],
                "kind": c["kind"],
                "concepts": list(c["concept_names"]),
                "reason": c["reason"],
                "confidence_deterministic": c["confidence_deterministic"],
                "net_score": c["net_score"],
            }
            for c in candidates
        ]
        try:
            fn = getattr(self.llm, "judge_gaps", None)
            if callable(fn):
                out = fn({"candidates": compact})
            elif hasattr(self.llm, "complete"):
                prompt = (
                    "下面是从关系图里找出的候选研究缺口。请只输出一个 JSON 对象，"
                    "形如 {\"<key>\": {\"worth\": true/false, \"confidence\": \"high|medium|low\", \"reason\": \"...\"}}，"
                    "不要输出任何解释文字。\n" + json.dumps(compact, ensure_ascii=False)
                )
                out = json.loads(str(self.llm.complete(prompt)).strip())
            else:
                return None
            if isinstance(out, Mapping):
                return {str(k): v for k, v in out.items()}
            return None
        except Exception:  # noqa: BLE001
            return None

    # ============================================================ handle

    #: 关键词分派表。**顺序即优先级**，因为一句需求可能同时命中多组词：
    #: "查询 群 与 域 之间的关系" 里既有"查询"也有"关系"，但只有后者定义了任务；
    #: 而"统计最热门的 5 个概念"里没有"之间/关系"，所以不会被误分派到 paths。
    _PATH_HINTS = ("之间", "关系链", "的关系", "路径", "联系", "关联")
    _HOT_HINTS = ("最热门", "热门", "统计", "频次", "排行", "排名")
    _COLD_HINTS = ("冷门", "孤立", "被忽视", "没人研究")
    _GAP_HINTS = ("完善", "缺口", "结构洞", "补全", "缺失", "遗漏")

    def handle(self, request_text: str) -> AnalysisReport:
        """自然语言需求 → 分派到四个分析器（**关键词分派，确定性、可测试**）。

        为什么不用 LLM 做分派：分派错了会产出**答非所问的报告**（例如把
        "研究冷门概念"当成"统计热门"），而报告本身看起来完全正常 —— 这种错误
        最难被发现。关键词分派可以被穷举测试，也可以被人工一眼验证。
        """
        text = (request_text or "").strip()
        if not text:
            return self._report(
                "unknown",
                "",
                {},
                summary="空请求：无法分派。请说明是统计最热门、查询两概念间关系、研究冷门，还是完善关系图。",
                payload={"available": list(ANALYZERS)},
                ok_=False,
                error="空请求",
            )
        if any(k in text for k in self._PATH_HINTS):
            return self._handle_paths(text)
        if any(k in text for k in self._HOT_HINTS):
            return self.hottest(top_n=self._parse_int(text, 5, 1, 100), request=text)
        if any(k in text for k in self._COLD_HINTS):
            return self.cold(top_n=self._parse_int(text, 5, 1, 100), request=text)
        if any(k in text for k in self._GAP_HINTS):
            return self.gaps(limit=self._parse_int(text, 10, 1, 100), request=text)
        return self._report(
            "unknown",
            text,
            {},
            summary=(
                "无法分派这条需求（关键词未命中）。可用说法示例：'统计最热门的 5 个概念'、"
                "'查询 群 与 域 之间的关系'、'研究冷门概念'、'完善关系图/找结构洞'。"
            ),
            payload={"available": list(ANALYZERS), "request": text},
            ok_=False,
            error="关键词未命中",
        )

    @staticmethod
    def _parse_int(text: str, default: int, low: int, high: int) -> int:
        """从需求文本里取一个数字参数（如"最热门的 5 个"），取不到就用默认值。

        只在 [low, high] 内采信：需求里出现的数字多半是概念名的一部分
        （"查询 0000 与 0001"），越界就说明它不可能是 top_n。
        """
        m = re.search(r"(\d{1,4})", text)
        if not m:
            return default
        try:
            n = int(m.group(1))
        except ValueError:
            return default
        return n if low <= n <= high else default

    def _handle_paths(self, text: str) -> AnalysisReport:
        """paths 分支：从需求里抽两个概念名 → 解析成代号；解析不到就**失败并列出候选**。"""
        g = self._g()
        rows = list(g.concepts)
        pairs = self._extract_pair_candidates(text)
        attempts: list[dict] = []
        for raw_a, raw_b in pairs:
            ra = self._resolve_concept(rows, raw_a) if raw_a else None
            rb = self._resolve_concept(rows, raw_b) if raw_b else None
            attempts.append(
                {
                    "raw": [raw_a, raw_b],
                    "resolved": [
                        {"query": raw_a, "concept_id": ra[0] if ra else None, "name": ra[1] if ra else None},
                        {"query": raw_b, "concept_id": rb[0] if rb else None, "name": rb[1] if rb else None},
                    ],
                }
            )
            if ra and rb and ra[0] != rb[0]:
                return self.paths(
                    ra[0],
                    rb[0],
                    max_paths=_cfg_int(self.cfg, "max_paths", 5),
                    max_len=_cfg_int(self.cfg, "max_len", 4),
                    max_overlap=_cfg_float(self.cfg, "max_overlap", 0.5),
                    request=text,
                )
        # ---- 解析失败：fail 并列出候选概念名（需求明确要求）
        candidates = self._concept_candidates(g)
        parsed = [p for a in attempts for p in (a["raw"][0], a["raw"][1]) if p]
        summary = (
            "无法解析出两个已有的概念代号，因此没有执行路径查询。"
            f"从需求里抽到的候选名：{parsed or '（没抽到）'}；"
            f"现有概念候选：{'、'.join(c['name'] for c in candidates[:20])}"
            + ("…" if len(candidates) > 20 else "")
        )
        return self._report(
            "paths",
            text,
            {},
            summary=summary,
            payload={
                "parsed_candidates": parsed,
                "attempts": attempts,
                "candidate_concepts": candidates,
                "hint": "概念名必须与概念表里的名称/别名一致（只做规范化精确匹配，不做相似度归并）。",
            },
            markdown="\n".join(
                self._md_head("paths", summary, ["概念名解析失败"])
                + ["## 现有概念候选", ""]
                + [f"- {c['concept_id']} {c['name']}" for c in candidates[:50]]
            )
            + "\n",
            warnings=["概念名解析失败"],
            ok_=False,
            error="无法解析出两个概念代号",
        )

    @staticmethod
    def _extract_pair_candidates(text: str) -> list[tuple[str, str]]:
        """从需求文本里抽"两个概念名"的**候选对**（按可信度降序）。

        刻意抽多组而不是抽一组：中文里"A 与 B 之间的关系"和"A 和 B 之间"的
        连接词不同，英文概念名里又可能自带空格。多抽几组、逐个尝试解析，
        比写一个"完美正则"更可靠，也更符合"解析不到就如实失败"的要求 ——
        反正失败的兜底是列出候选概念，不会误导。
        """
        body = re.sub(r"[?？。！!]+$", "", (text or "").strip())
        body = re.sub(r"(?:之间|间)?\s*的?\s*(?:关系链|关系|路径|联系|关联)\s*$", "", body).strip()
        body = re.sub(
            r"^(?:请|帮我|帮忙|麻烦|我想|我要|请你)?\s*(?:查询|查一下|查|分析|查找|寻找|看看|给出|列出|看|统计|梳理|探究|研究|整理)+",
            "",
            body,
        ).strip()
        body = body.strip(" ：:，,的")
        pairs: list[tuple[str, str]] = []
        for sep in ("以及", " vs ", " VS ", " vs.", "与", "和", "跟", "同", "及", "、", ",", "vs"):
            if sep in body:
                a, _, b = body.partition(sep)
                a, b = a.strip(" 　的"), b.strip(" 　的")
                if a and b:
                    pairs.append((a, b))
        if not pairs and body:
            pairs.append((body, ""))
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for p in pairs:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    @staticmethod
    def _resolve_concept(rows: Sequence[dict], query: str) -> tuple[str, str] | None:
        """概念名 → `(concept_id, name)`。

        解析规则（与 `dedup.find_concept` 同一口径，**不另写一套匹配**）：
        1. 先走 `D.find_concept`（规范化名字 + 别名，精确匹配）；
        2. 都不中时退一步做**唯一**子串匹配（"群" 命中 "阿贝尔群" 的场合），
           但只有**恰好一个**候选命中时才采信 —— 有歧义就返回 None，
           让上层如实报告"解析不到"并列出候选，而不是替 D 猜一个。
        """
        q = (query or "").strip().strip("“”\"'《》")
        if not q:
            return None
        row = D.find_concept(list(rows), q)
        if row is None and q:
            nq = T.normalize(q)
            hits = [
                r
                for r in rows
                if nq
                and (
                    nq in (r.get("normalized_name") or T.normalize(r.get("name", "")))
                    or (r.get("normalized_name") or T.normalize(r.get("name", ""))) in nq
                )
            ]
            if len(hits) == 1:
                row = hits[0]
        if row is None:
            return None
        return str(row.get("concept_id")), str(row.get("name") or "")

    def _concept_candidates(self, g: RelationGraph) -> list[dict]:
        """现有概念清单（按 occurrences 降序，同分按代号升序）。失败报告要用它。"""
        counts = g.counts()
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1]["occurrences"], kv[0]))
        return [
            {"concept_id": cid, "name": g.name_of(cid), "occurrences": v["occurrences"]}
            for cid, v in ranked
        ]

    # ============================================================ 工具注册

    def register_tools(self, registry: ToolRegistry) -> list[str]:
        """把四个分析器 + I1 服务面注册成工具（`graph.*`，**全部** `side_effect="read"`）。

        DESIGN-TOOLS.md §1.1 把 `graph.hottest/paths/cold/gaps` 列为 C 的工具。
        它们与 `tools/graph_tools.py` 里那四个**低层**图查询工具共用 `graph.` 前缀：
        低层工具回答"图长什么样"，这里回答"结论是什么"；I1 新增的五个服务工具
        （neighbors / relations_between / contradictions / structural_duplicates /
        check_conflict）回答"就我现在追问的这一点，图上具体是什么情况"。

        **C 的工具面必须全量只读**（DESIGN-INTERACTIONS.md §2 的硬规则）：一旦 C 能写，
        它就成了绕过 B 引文逐字回验的写入路径，而那是全系统唯一能自动发现幻觉引文的地方。
        所以：
        - 这里注册的每一个工具都是 `side_effect="read"`；
        - `graph.gaps` 刻意**不暴露** `submit_requests`（I3 的写入口只能由编排层直接调方法，
          见该处的注释）。

        ⚠️ **已知的命名冲突（本次改造发现，未擅自修改）**：`graph.neighbors` 与
        `graph.relations_between` 这两个名字**已被低层图工具占用**。按"同名跳过"的既有约定，
        若先注册低层工具，C 的**服务版**（三态 + 有界）就会被跳过，D 通过工具层拿到的是
        低层形状（没有 checked/empty/truncated），而两种形状取决于**注册顺序** ——
        这是"同名不同义"的典型隐患。本次**不改**低层工具（它们各有既有测试与调用方），
        服务版始终可以通过 `AgentC.neighbors()` / `AgentC.relations_between()` 直接调用；
        真要统一，应由主控决定给服务版另起名字（例如 `graph.service.*`）或改低层的返回契约。
        """
        added: list[str] = []

        def _register(name: str, summary: str, params: dict, fn: Any, returns: str) -> None:
            if name in registry:
                return
            wrapped = tool(name, summary, params, side_effect="read", roles=("C", "D"), returns=returns)(fn)
            registry.register_function(wrapped)
            added.append(name)

        _register(
            "graph.hottest",
            "统计最热门的 top_n 个概念（出现次数口径，含代表关系与概念名翻译）。",
            {
                "type": "object",
                "properties": {"top_n": {"type": "integer", "minimum": 1, "maximum": 100}},
                "required": [],
                "additionalProperties": False,
            },
            lambda top_n=5: self.hottest(int(top_n)).to_dict(),
            "{kind, summary, payload, markdown, warnings, truncated, ok}",
        )
        _register(
            "graph.paths",
            "查询两个概念之间的多条低重合度路径，给出关系代号链与逐项信息量评分。",
            {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "minLength": 4, "maxLength": 4},
                    "b": {"type": "string", "minLength": 4, "maxLength": 4},
                    "max_paths": {"type": "integer", "minimum": 1, "maximum": 50},
                    "max_len": {"type": "integer", "minimum": 1, "maximum": 8},
                    "max_overlap": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
            lambda a, b, max_paths=5, max_len=4, max_overlap=0.5: self.paths(
                a, b, max_paths=int(max_paths), max_len=int(max_len), max_overlap=float(max_overlap)
            ).to_dict(),
            "{kind, summary, payload.paths[...score_breakdown...], markdown, truncated}",
        )
        _register(
            "graph.cold",
            "研究冷门概念：degree 升序列出，标出与热门概念的连接强度，单独给出'冷门但连接强'。",
            {
                "type": "object",
                "properties": {"top_n": {"type": "integer", "minimum": 1, "maximum": 100}},
                "required": [],
                "additionalProperties": False,
            },
            lambda top_n=5: self.cold(int(top_n)).to_dict(),
            "{kind, summary, payload.entries/undervalued_ids/isolated, markdown}",
        )
        _register(
            "graph.gaps",
            "完善关系图：找低频概念组与结构洞，给出'确实有/证据不足'的二元结论与候选缺口。",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                "required": [],
                "additionalProperties": False,
            },
            lambda limit=10: self.gaps(int(limit)).to_dict(),
            "{kind, summary, payload.verdict/candidate_gaps, markdown, truncated}",
        )
        # ⚠️ `graph.gaps` **刻意不暴露** `submit_requests`（I3 的写入口）：
        # 本工具声明的是 `side_effect="read"`，而 `submit_requests=True` 会往
        # `search_requests` 写行。一个声明"只读"却可能写盘的工具，会让整张权限表
        # 变成一句空话 —— 而权限表是"哪种副作用需要审批"的**唯一**依据。
        # I3 只由编排层直接调 `AgentC.gaps(submit_requests=True)` 开启。

        # ---- I1 服务面工具（同步、只读、有界、三态）。让 D 能"点菜"：
        # 低层 graph.* 回答"图长什么样"，分析器回答"结论是什么"，这一组回答
        # "就我现在追问的这一点，图上具体是什么情况"。
        # ⚠️ **命名冲突（已处理）：服务版不能叫 `graph.neighbors` /
        # `graph.relations_between`** —— 这两个名字已被 `tools/graph_tools.py` 的
        # 低层工具占用，而它们的**返回形状不同**
        # （低层给 `{degree, neighbors[]}`，服务版给 `{checked, nodes[], truncated}`）。
        # 同一个名字挂两种契约，结果取决于**注册顺序** —— 而注册顺序
        # 是一个没人会去读的细节。这正是本项目最恨的"同名不同义"。
        # 服务版因此改名为 `graph.svc_*`：`svc` 一眼表明它是
        # **三态的服务接口**（D 点菜用），而不是“图长什么样”的低层查询。
        # 方法层 `AgentC.neighbors()` / `AgentC.relations_between()` **名字不变** ——
        # D 的 `_c_digest` 就是按方法层读的。
        _register(
            "graph.svc_neighbors",
            "某概念的 depth 跳邻域（有界 BFS；超 max_nodes 返回 truncated=True 而不是静默截断）。"
            "查不到该代号时 checked=True 且 reason 说明'不在概念表里'，checked=False 只表示'根本没查'。",
            {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string", "minLength": 4, "maxLength": 4},
                    "depth": {"type": "integer", "minimum": 1, "maximum": max(1, SERVICE_MAX_DEPTH)},
                    "max_nodes": {"type": "integer", "minimum": 1},
                },
                "required": ["concept_id"],
                "additionalProperties": False,
            },
            lambda concept_id, depth=1, max_nodes=None: self.neighbors(
                concept_id, depth=int(depth), max_nodes=(None if max_nodes is None else int(max_nodes))
            ),
            "{checked, concept_id, depth, nodes[], edges[], truncated, empty, reason}",
        )
        _register(
            "graph.svc_relations_between",
            "两个概念之间的全部关系（三态：checked=False 表示没查，relation_ids=[] 且 empty=True "
            "表示查了没有）；include_inactive=False 只保留 status=active 的关系。",
            {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "minLength": 4, "maxLength": 4},
                    "b": {"type": "string", "minLength": 4, "maxLength": 4},
                    "include_inactive": {"type": "boolean"},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
            lambda a, b, include_inactive=True: self.relations_between(
                a, b, include_inactive=bool(include_inactive)
            ),
            "{checked, a, b, relation_ids[], relations[], empty, filtered_out, reason}",
        )
        _register(
            "graph.contradictions",
            "矛盾检查（判据全部来自 interactions.detect_contradictions）。给了 relation_ids 就只扫这些 "
            "（I2 的'只复核这两个具体的关系'），否则扫全部关系。method=literal，只做字面判据；"
            "结果按 strength 分档（strong 才可作为研究线索，weak 假阳性极高，仅供参考），"
            "并给出 strong_count / weak_count。",
            {
                "type": "object",
                "properties": {
                    "relation_ids": {"type": "array"},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": [],
                "additionalProperties": False,
            },
            lambda relation_ids=None, limit=None: self.contradictions(
                relation_ids=relation_ids, limit=(None if limit is None else int(limit))
            ),
            "{checked, scope, scanned, contradictions[], strong_count, weak_count, truncated, method, method_note, reason}",
        )
        _register(
            "graph.structural_duplicates",
            "结构重复概念候选（I5 检测侧）：邻域完全相同且彼此无直接关系。只有结构证据时 "
            "proposal=review（**不得据此合并**），合并决定权在 B。截断通知单独放在 truncation_notice。",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1}},
                "required": [],
                "additionalProperties": False,
            },
            lambda limit=None: self.structural_duplicates(limit=(None if limit is None else int(limit))),
            "{checked, candidates[], truncation_notice, truncated, scanned_concepts, method, reason}",
        )
        _register(
            "graph.check_conflict",
            "I6 写入期一致性闸门（**纯函数**，全项目唯一实现 interactions.check_conflict）："
            "判断一条草稿关系与给定已有关系是否矛盾。签名里没有 store —— B 在自己的事务内调用它，"
            "若它去查 store 就是锁重入/死锁。**省略 existing_relations 表示'没能力检查'（checked=False），"
            "绝不等于'检查过、不冲突'**。",
            {
                "type": "object",
                "properties": {
                    "draft_relation": {"type": "object"},
                    "existing_relations": {"type": "array"},
                },
                "required": ["draft_relation"],
                "additionalProperties": False,
            },
            lambda draft_relation, existing_relations=None: check_conflict(
                draft_relation, existing_relations=existing_relations
            ),
            "{checked, conflict, conflicts_with[], reason, method, scope, compared}",
        )
        return added


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    # 运行方式：cd D:\Incubator\test\test1\src && python -m abflow.agent_c
    # 说明：本仓库的 tools/ 目录**没有** __init__.py（那是别人的交付物边界），
    # 靠 Python 3 的命名空间包机制导入。若在某些工具链下 `python -m` 不成立，
    # 用：python -c "import sys; sys.path.insert(0,'.'); from abflow import agent_c; agent_c._selftest()"
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from .tools.base import ToolRegistry
    from .tools.graph_tools import register as register_graph_tools
    from .tools.trace_tools import register as register_trace_tools

    CHECKS: list[tuple[str, bool]] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        CHECKS.append((label, bool(cond)))
        print(f"    [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    def make_store(tag: str) -> Store:
        """临时工作区。优先系统临时目录；被沙箱拒绝时退到仓库内的 demo/ 目录。"""
        try:
            root = Path(tempfile.mkdtemp(prefix=f"abflow_agentc_{tag}_"))
        except OSError:
            root = Path(__file__).resolve().parents[2] / "demo" / f"agentc_selftest_{tag}"
        st = Store(root)
        st.init(force=True)
        return st

    # ============================================================ 数据集
    # 至少 6 个概念、8 条关系；0000(群) 与 0002(域) 之间有 2 跳与 3 跳两条以上
    # 不同长度的路径；含一条 quote_verified=False（0002 号关系）与一条
    # status=suspect（0006/0011 号关系），用来验证评分确实会降级。
    def build_dataset(st: Store) -> None:
        concepts = [
            ("0000", "群", "带二元运算且满足结合律的集合"),
            ("0001", "阿贝尔群", "交换的群"),
            ("0002", "域", "乘法可交换的除环"),
            ("0003", "交换环", "乘法可交换的环"),
            ("0004", "模", "环在阿贝尔群上的作用"),
            ("0005", "理想", "环的加法子群且对乘法封闭"),
            ("0006", "孤立概念", "与任何概念都没有关系的概念"),
            ("0007", "子群", "群的非空子集且在运算下封闭"),
            ("0008", "环同态", "保持加法与乘法运算的映射"),
            ("0009", "素理想", "商环为整环的理想"),
        ]
        def rel(rid, cids, desc, lit, qv, status="active", page=None):
            return {
                "relation_id": rid,
                "concept_ids": sorted(cids),
                "description": desc,
                "lit_id": lit,
                "page_range": page or {"start": 1, "end": 1, "label": "p. 1"},
                "quote": f"原文引文 {rid}",
                "quote_normalized": f"原文引文 {rid}",
                "quote_verified": qv,
                "statement": desc,
                "status": status,
                "concept_group_key": "|".join(sorted(cids)),
            }

        relations = [
            rel("0000", ["0000", "0001"], "阿贝尔群是一种交换的群", "0000", True),
            rel("0001", ["0001", "0002"], "每个域都是阿贝尔群", "0001", True),
            # ↓ 引文校验失败：评分必须因此降级
            rel("0002", ["0000", "0003"], "交换环的加法群是阿贝尔群", "0002", False),
            rel("0003", ["0002", "0003"], "域是交换环", "0003", True),
            rel("0004", ["0000", "0004"], "模是群在环上的作用", "0004", True),
            rel("0005", ["0004", "0005"], "理想使模的构造成为可能", "0005", None),
            # ↓ status=suspect 且引文无法校验：评分必须因此降级
            rel("0006", ["0002", "0005"], "理想与商环的对应关系", "0006", None, status="suspect"),
            rel("0007", ["0000", "0005"], "群作用下的不变量", "0006", True),
            rel("0008", ["0001", "0004"], "阿贝尔群上的模结构", "0001", True),
            # 一条涉及 3 个概念的关系：产生 3 对边，共享同一个 relation_id
            rel("0009", ["0002", "0004", "0005"], "域上模与理想的三元关系", "0007", True),
            # 冷门概念 0007（子群）与两个热门概念之间的**弱**连接（低信息量路径的素材）
            rel("0010", ["0000", "0007"], "子群判定", "0002", False, status="suspect"),
            rel("0011", ["0007", "0002"], "待查", "0002", None, status="suspect"),
            # 一条**3 跳**且与前面几条 2 跳路径重合度低（Jaccard 0.4）的链：
            # 群 -环同态- 素理想- 域。用来验证"不同长度的路径"与"多跳=更多推理链"。
            rel("0012", ["0000", "0008"], "环同态保持群的加法运算结构", "0008", True),
            rel("0013", ["0008", "0009"], "素理想在环同态下的原像性质", "0009", True),
            rel("0014", ["0009", "0002"], "域中的素理想只有零理想这一个", "0010", None),
        ]
        literatures = [
            {"lit_id": "0000", "title": "代数结构导论", "type": "M", "summary": "教材", "path": "l0.txt", "processed": True, "year": 2001},
            {"lit_id": "0001", "title": "群论讲义", "type": "M", "summary": "讲义", "path": "l1.txt", "processed": True, "year": 1998},
            {"lit_id": "0002", "title": "环与模", "type": "M", "summary": "专著", "path": "l2.txt", "processed": True, "year": 2010},
            {"lit_id": "0003", "title": "域论初步", "type": "J", "summary": "论文", "path": "l3.txt", "processed": True, "year": 2015},
            {"lit_id": "0004", "title": "模论", "type": "M", "summary": "专著", "path": "l4.txt", "processed": True, "year": 2005},
            {"lit_id": "0005", "title": "理想与商环", "type": "J", "summary": "论文", "path": "l5.txt", "processed": True, "year": 2012},
            {"lit_id": "0006", "title": "群作用", "type": "J", "summary": "论文", "path": "l6.txt", "processed": True, "year": 2018},
            {"lit_id": "0007", "title": "三元关系研究", "type": "J", "summary": "论文", "path": "l7.txt", "processed": True, "year": 2020},
            {"lit_id": "0008", "title": "环同态", "type": "M", "summary": "专著", "path": "l8.txt", "processed": True, "year": 2003},
            {"lit_id": "0009", "title": "素理想与局部化", "type": "J", "summary": "论文", "path": "l9.txt", "processed": True, "year": 2016},
            {"lit_id": "0010", "title": "域论续", "type": "J", "summary": "论文", "path": "l10.txt", "processed": True, "year": 2019},
        ]
        (st.library).mkdir(parents=True, exist_ok=True)
        (st.library / "l0.txt").write_text(
            "An abelian group is a group in which the commutative law holds.\n", encoding="utf-8"
        )
        concept_rows = []
        for cid, name, definition in concepts:
            concept_rows.append(
                {
                    "concept_id": cid,
                    "name": name,
                    "definition": definition,
                    "normalized_name": T.normalize(name),
                    "related_concepts": D.derive_related_concepts(cid, relations),
                    "created_at": S.now_iso(),
                }
            )
        with st.tx("concepts", "relations", "literature", actor="selftest", note="fixture") as tx:
            for r in concept_rows:
                tx.upsert("concepts", r)
            for r in relations:
                tx.upsert("relations", r)
            for r in literatures:
                tx.upsert("literature", r)

    print("=" * 72)
    st = make_store("main")
    build_dataset(st)
    print(f"[1] 临时工作区 {st.root}")
    print(f"    概念 {len(st.rows('concepts'))} 关系 {len(st.rows('relations'))} 文献 {len(st.rows('literature'))}")

    c = AgentC(st, config={"high": 3.0, "medium": 1.5}, actor="agent-C-selftest")
    g = c.build_graph()
    s = g.summary()
    print(f"[2] build_graph：节点={s['concept_count']} 关系={s['relation_count']} 两两边={s['pair_count']} "
          f"孤立={s['isolated_concepts']} 校验分布={s['quote_verified_counts']}")

    print("[3] 工具注册（低层图工具 + 溯源工具 + C 分析工具），并确认全是 read")
    reg = ToolRegistry(name="agentc-selftest")
    low = register_graph_tools(reg, store=st)
    tr = register_trace_tools(reg, store=st)
    ana = c.register_tools(reg)
    print(f"    graph 低层={low}")
    print(f"    trace   ={tr}")
    print(f"    分析器  ={ana}")
    print(f"    全部只读={all(reg.get(n).side_effect == 'read' for n in reg.names())}（共 {len(reg.names())} 个工具）")
    print(f"    graph.build -> {reg.call('graph.build').data['concept_count']} 个概念")

    print("[4] hottest(top_n=3)：出现次数 + 关系条数 + 概念组次数 + 代表关系")
    hr = c.hottest(top_n=3, request="统计最热门的 3 个概念")
    print(f"    summary: {hr.summary}")
    for e in hr.payload["entries"]:
        print(f"    {e['concept_id']} {e['name']}: occ={e['occurrences']} rel={e['relation_count']} grp={e['group_count']}")
        for r in e["representative_relations"]:
            print(f"        代表关系 {r['relation_id']} qv={r['quote_verified']} {r['status']} {r['description']!r}")
    check("hottest 命中概念名翻译", all(e["name"] and "(" not in e["name"] for e in hr.payload["entries"]))
    check("hottest 排序稳定（同分按 concept_id 升序）",
          hr.payload["hot_ids"] == sorted(hr.payload["hot_ids"], key=lambda x: (-g.counts()[x]["occurrences"], x)))

    print("[5] paths('0000','0002')：图搜索 → Jaccard 去重 → 逐跳重选关系 → 评分 → 分流")
    # 这里刻意用 max_paths=8（默认是 5）：按"长度升序"筛完后，2 跳路径恰好有 5 条，
    # 默认值会把 3 跳的那条挤到 dropped_by_max_paths 里，看不到"不同长度的路径"。
    # 这也顺带说明了 max_paths 是一个**真实的展开上限**，而不是装饰参数。
    P_MAX = 8
    pr = c.paths("0000", "0002", max_paths=P_MAX, max_len=4, max_overlap=0.5, request="查询 群 与 域 之间的关系")
    sh = pr.payload["search"]
    dd = pr.payload["dedup"]
    print(f"    summary: {pr.summary}")
    print(f"    图搜索：raw={sh['raw_path_count']} 截断={sh['truncated']} reasons={sh['truncation_reasons']} 预算={sh['budget_used']}/{sh['node_budget']}")
    print(f"    **未筛选前**的原始路径集合（按跳数分布 {sh['raw_paths_by_hops']}）：")
    for p in sh["raw_paths"]:
        print(f"      {'→'.join(p)}（{len(p) - 1} 跳）")
    print(f"    去重：保留={dd['kept_after_overlap_filter']} 展开={dd['selected_for_report']} 因重合丢弃={len(dd['dropped_by_overlap'])} 因max_paths丢弃={len(dd['dropped_by_max_paths'])}")
    for d in dd["dropped_by_overlap"]:
        print(f"      丢弃 {'→'.join(d['path'])}（Jaccard={d['max_jaccard']} vs {'→'.join(d['against'])}）")
    print(f"    判决：high={pr.payload['levels']['high']} medium={pr.payload['levels']['medium']} low={pr.payload['levels']['low']}")
    for it in pr.payload["paths"]:
        print(f"    - {'→'.join(it['concept_path'])} 链={'→'.join(it['relation_chain'])} 跳={it['hops']} score={it['score']} => {it['level']}")
        for h in it["hop_details"]:
            print(f"        跳{h['hop']} {h['from']}-{h['to']} 候选{h['candidate_count']}条{h['candidate_ids']} 选中{h['chosen']}")
        for t in it["score_breakdown"]["terms"]:
            print(f"        {t['name']}: {t['detail']} -> {t['contribution']:+}")
    check("存在多条不同长度的路径（2 跳与 3 跳都有）",
          any(it["hops"] == 2 for it in pr.payload["paths"]) and any(it["hops"] == 3 for it in pr.payload["paths"]))
    print(f"    定性证据：未筛选前 3 跳路径 {sh['raw_paths_by_hops'].get('3', 0)} 条（图搜索确实找到了它们），"
          f"其中 {sum(1 for d in dd['dropped_by_overlap'] if len(d['path']) - 1 == 3)} 条因高重合被丢弃；"
          f"筛选后仍有 3 跳路径={any(it['hops'] == 3 for it in pr.payload['paths'])}")
    check("Jaccard 去重确实丢掉了高重合路径", len(dd["dropped_by_overlap"]) >= 1)
    check("三个等级都被真实触发（high/medium/low 均 > 0）",
          pr.payload["levels"]["high"] > 0 and pr.payload["levels"]["medium"] > 0 and pr.payload["levels"]["low"] > 0)
    check("引文校验失败的那条路径被降级（不是 high）",
          all(it["level"] != "high" for it in pr.payload["paths"] if "0002" in it["relation_chain"]))
    check("每条路径都有可逐项打印的 score_breakdown",
          all(len(it["score_breakdown"]["terms"]) == 7 for it in pr.payload["paths"]))
    # ---- 正文/附录/统计的分流必须**按小节内容**核对，而不是靠字符串计数
    # （早先这里用 "'→'.join(concept_path) in md_body" 去查，而正文渲染的是带概念名的
    #   "群(0000) → 阿贝尔群(0001)"，那个紧凑串只出现在统计段 —— 断言恒假，
    #   却"看起来"在检查正文。现在改成解析小节：正文段里不允许出现任何非 high 的路径标题。）
    def _section(md: str, start_marker: str, end_marker: str | None) -> str:
        seg = md.split(start_marker, 1)[1] if start_marker in md else ""
        if end_marker and end_marker in seg:
            seg = seg.split(end_marker, 1)[0]
        return seg

    body = _section(pr.markdown, "## 正文（仅高信息量路径）", "## 附录")
    appendix = _section(pr.markdown, "## 附录", "## 统计")
    stats_sec = _section(pr.markdown, "## 统计", "## 被重合度筛掉")
    body_high = body.count("（高信息量，score=")
    body_other = body.count("（中信息量，score=") + body.count("（低信息量，score=")
    md_high = pr.markdown.count("（高信息量，score=")
    print(f"    分流核对：正文段 high 标题 {body_high} 个 / 非 high 标题 {body_other} 个；"
          f"附录段 medium 标题 {appendix.count('（中信息量，score=')} 个；统计段低信息量行 {stats_sec.count('score=')} 个")
    check("正文只含 high 路径（段落级核对，不是字符串计数）",
          body_high == pr.payload["levels"]["high"] and body_other == 0 and appendix.count("（中信息量，score=") == pr.payload["levels"]["medium"]
          and md_high == pr.payload["levels"]["high"])
    check("附录明确标注'未达正文标准'", "未达正文标准" in pr.markdown)

    print("[6] 预算截断如实回报：node_budget=3 的 AgentC 必须给出 truncated=True 与警告")
    tiny = AgentC(st, config={"node_budget": 3}, actor="agent-C-tiny")
    tr_rep = tiny.paths("0000", "0002", request="截断自检")
    print(f"    truncated={tr_rep.truncated} reasons={tr_rep.payload['search']['truncation_reasons']} "
          f"raw={tr_rep.payload['search']['raw_path_count']} 预算={tr_rep.payload['search']['budget_used']}/3")
    print(f"    summary: {tr_rep.summary[:80]}…")
    for w in tr_rep.warnings:
        print(f"    warning: {w[:90]}…")
    check("预算截断被如实标出", tr_rep.truncated and tr_rep.payload["search"]["truncation_reasons"] == ["node_budget"])

    print("[7] '没有找到高信息量路径'必须明说：把阈值抬到 99，所有 high 都该消失")
    strict = AgentC(st, config={"high": 99.0, "medium": 1.5}, actor="agent-C-strict")
    sr = strict.paths("0000", "0002", max_paths=5, request="阈值自检")
    print(f"    summary: {sr.summary}")
    print(f"    has_high={sr.payload['has_high']} 正文里是否明说={'没有找到高信息量路径' in sr.markdown}")
    check("无 high 时明说'没有找到高信息量路径'",
          (not sr.payload["has_high"]) and ("没有找到高信息量路径" in sr.markdown) and ("没有找到高信息量路径" in sr.summary))

    print("[8] LLM 钩子（构造时传入假模型）：只重排顺序，评分与内容不变")
    class _FakeLLM:
        def rank_paths(self, payload):
            # 故意给一个逆序排列，验证"顺序被采纳、内容与分数没变"
            return list(reversed([p["index"] for p in payload["paths"]]))

        def judge_gaps(self, payload):
            return {c["key"]: {"worth": True, "confidence": "medium", "reason": "假模型复核通过"} for c in payload["candidates"]}

    hooked = AgentC(st, config={}, actor="agent-C-llm", llm=_FakeLLM())
    hr2 = hooked.paths("0000", "0002", max_paths=P_MAX, request="钩子自检")
    print(f"    used_for_ordering={hr2.payload['hook']['used_for_ordering']} note={hr2.payload['hook']['note']}")
    print(f"    第一跳链={hr2.payload['paths'][0]['relation_chain']} score={hr2.payload['paths'][0]['score']} llm_ranked={hr2.payload['paths'][0]['llm_ranked']}")
    same_scores = sorted(p["score"] for p in hr2.payload["paths"]) == sorted(p["score"] for p in pr.payload["paths"])
    check("LLM 钩子只改顺序、不改评分", hr2.payload["hook"]["used_for_ordering"] and same_scores)
    hr3 = hooked.hottest(top_n=3)
    check("无钩子的分析器（hottest）不受 LLM 影响", hr3.payload["entries"] == hr.payload["entries"])
    # 钩子抛异常时必须回退
    class _BrokenLLM:
        def rank_paths(self, payload):
            raise RuntimeError("模型挂了")

        def judge_gaps(self, payload):
            raise RuntimeError("模型挂了")
    broken = AgentC(st, config={}, llm=_BrokenLLM())
    br = broken.paths("0000", "0002", max_paths=P_MAX)
    print(f"    钩子抛异常后：used={br.payload['hook']['used_for_ordering']} warnings={[w[:40] for w in br.warnings]}")
    check("钩子失败时回退到确定性顺序且不丢结果",
          (not br.payload["hook"]["used_for_ordering"]) and len(br.payload["paths"]) == len(pr.payload["paths"]))

    print("[9] cold(top_n=2)：冷门榜、完全孤立、弱连接判据、'冷门但连接强'")
    cr = c.cold(top_n=2, request="研究冷门概念")
    print(f"    summary: {cr.summary}")
    for e in cr.payload["entries"]:
        print(f"    {e['concept_id']} {e['name']}: degree={e['degree']} 与热门概念的关系={len(e['relations_to_hot'])} 弱关系={len(e['weak_relations'])} undervalued={e['undervalued']}")
        for r in e["relations_to_hot"]:
            print(f"        [{r['relation_id']}] 与 {'/'.join(o['name'] for o in r['other_concepts'])} weak_score={r['weak_score']} 理由={r['weak_reasons']}")
    print(f"    完全孤立：{[x['concept_id'] + ':' + x['name'] for x in cr.payload['isolated']]}")
    print(f"    冷门但连接强：{cr.payload['undervalued_ids']}")
    check("孤立概念（degree=0）被单独归类、不进冷门榜",
          "0006" in [x["concept_id"] for x in cr.payload["isolated"]] and all(e["degree"] > 0 for e in cr.payload["entries"]))
    check("弱判据给到了理由字符串",
          all(r["weak_reasons"] for e in cr.payload["entries"] for r in e["weak_relations"]))
    check("'冷门但连接强'单独列出（0003 与热门概念 0002 的连接引文已证实）",
          "0003" in cr.payload["undervalued_ids"])

    print("[10] gaps(limit=5)：低频概念组 + 结构洞 + 二元结论")
    gr = c.gaps(limit=5, request="完善关系图，找结构洞")
    print(f"    verdict={gr.payload['verdict']} has_candidates={gr.payload['has_candidates']}")
    print(f"    conclusion: {gr.payload['conclusion']}")
    print(f"    检索范围={gr.payload['searched']} truncated={gr.truncated}")
    for cg in gr.payload["candidate_gaps"][:5]:
        print(f"    候选[{cg['kind']}] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 置信度={cg['confidence']}")
        print(f"        理由={cg['reason']}")
    print(f"    被否决（low）{len(gr.payload['low_confidence_candidates'])} 条，示例理由：")
    for cg in gr.payload["low_confidence_candidates"][:3]:
        print(f"      - {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 负向={'；'.join(cg['negative_signals'])}")
    check("gaps 给出明确二元结论", gr.payload["verdict"] in ("有", "无"))
    check("candidate_gaps 只收 medium 以上置信度",
          all(x["confidence"] in ("high", "medium") for x in gr.payload["candidate_gaps"]))

    print("[11] gaps 的'证据不足'路径：候选只有'引文全失败'这类依据时，否决项必须直接剔除，不许包装成'找到了'")
    st2 = make_store("nogap")
    with st2.tx("concepts", "relations", "literature", actor="selftest", note="nogap") as tx:
        for cid, name in [
            ("0000", "这是一整句话并不是概念因为它确实太长了甲"),
            ("0001", "这是一整句话并不是概念因为它确实太长了乙"),
            ("0002", "桥"),
        ]:
            tx.upsert("concepts", {"concept_id": cid, "name": name, "definition": "", "normalized_name": T.normalize(name), "related_concepts": []})
        for rid, cids in [("0000", ["0000", "0002"]), ("0001", ["0001", "0002"])]:
            tx.upsert(
                "relations",
                {
                    "relation_id": rid,
                    "concept_ids": sorted(cids),
                    "description": "可疑关系",
                    "lit_id": "0000",
                    "page_range": {"start": 1, "end": 1, "label": "p. 1"},
                    "quote": "",
                    "quote_verified": False,
                    "status": "active",
                    "concept_group_key": "|".join(sorted(cids)),
                },
            )
        tx.upsert("literature", {"lit_id": "0000", "title": "样例", "type": "M", "summary": "", "path": None, "processed": True})
    c2 = AgentC(st2, config={}, actor="agent-C-nogap")
    g2 = c2.gaps(limit=5, request="完善关系图")
    print(f"    verdict={g2.payload['verdict']}")
    print(f"    conclusion: {g2.payload['conclusion']}")
    print(f"    候选={len(g2.payload['candidate_gaps'])} 否决={len(g2.payload['vetoed_candidates'])} "
          f"净分不足={len(g2.payload['low_confidence_candidates'])} "
          f"结构洞={g2.payload['searched']['structural_holes']} 低频组={g2.payload['searched']['rare_group_candidates']}")
    for cg in g2.payload["vetoed_candidates"][:4]:
        print(f"      - [veto] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} "
              f"（本可判 {cg['confidence_deterministic']}）理由={'；'.join(cg['veto_reasons'])}")
    for cg in g2.payload["low_confidence_candidates"][:3]:
        print(f"      - [low ] {' ↔ '.join(cg['concept_names'])} 净分={cg['net_score']} 负向={'；'.join(cg['negative_signals'])}")
    check("证据不足时 verdict='无' 且候选为空",
          g2.payload["verdict"] == "无" and g2.payload["candidate_gaps"] == [] and "证据不足" in g2.payload["conclusion"])
    check("否决项生效：'引文全部失败/名字不是概念'的候选被 veto 而不是靠扣分压低",
          len(g2.payload["vetoed_candidates"]) > 0 and all(c["veto_reasons"] for c in g2.payload["vetoed_candidates"]))
    check("veto 候选仍在报告里逐条留理由（不是静默丢弃）",
          "被否决项（veto）剔除的候选" in g2.markdown and all(c["veto_reasons"][0] in g2.markdown for c in g2.payload["vetoed_candidates"][:1]))

    print("[12] trace 工具与报告联动：关系代号链 → L1 表述 → L3 正文（按需）")
    chain = pr.payload["paths"][0]["relation_chain"]
    tch = reg.call("trace.chain", relation_ids=list(chain))
    print(f"    trace.chain({chain}) ok={tch.ok}")
    for line in tch.data["chain_text"].splitlines():
        print(f"      {line}")
    l1 = reg.call("trace.relation", relation_id=chain[0])
    print(f"    trace.relation({chain[0]}) 概念名={l1.data['concept_names']} 页码={l1.data['page_range']} 三态={l1.data['quote_verified_label']}")
    l3 = reg.call("trace.literature", lit_id=l1.data["lit_id"], max_chars=200)
    print(f"    trace.literature({l1.data['lit_id']}) status={l3.data['status']} 正文={l3.data['text'][:48]!r}")
    l3b = reg.call("trace.literature", lit_id="0003")
    print(f"    trace.literature(0003，只登记了路径没落文件) status={l3b.data['status']}")
    check("链条溯源可用且下钻 L3 如实报告状态", tch.ok and l3.data["status"] == "ok" and l3b.data["status"] == "file_missing")

    print("[13] persist()：reports/<id>-<kind>.md + analysis_reports 登记行")
    info = pr.persist()
    print(f"    {info}")
    row = st.rows("analysis_reports")[0]
    print(f"    登记行：id={row['report_id']} kind={row['kind']} request={row['request']!r} path={row['markdown_path']}")
    print(f"    summary={row['summary'][:60]}…")
    md_file = st.root / info["markdown_path"]
    print(f"    文件存在={md_file.exists()} 大小={md_file.stat().st_size} 字节；payload 键={sorted(row['payload'].keys())[:6]}…")
    check("persist 落盘且登记行一致",
          row["report_id"] == info["report_id"] and row["markdown_path"] == info["markdown_path"] and md_file.exists())
    no_persist = c.handle("随便说点什么不相干的话")
    try:
        no_persist.persist()
        check("kind='unknown' 被拒绝登记", False)
    except ValueError as exc:
        print(f"    拒绝登记 unknown：{exc}")
        check("kind='unknown' 被拒绝登记", True)
    csv = c.hottest(top_n=2).persist()
    print(f"    第二份报告：{csv}")

    print("[14] handle() 关键词分派（确定性）")
    cases = [
        ("统计最热门的 5 个概念", "hottest"),
        ("查询 群 与 域 之间的关系", "paths"),
        ("研究冷门概念", "cold"),
        ("完善关系图，找缺失的结构洞", "gaps"),
    ]
    for text, want in cases:
        rep = c.handle(text)
        print(f"    {text!r} -> kind={rep.kind} ok={rep.ok} summary={rep.summary[:56]}…")
        check(f"handle 分派 {text!r} → {want}", rep.kind == want and rep.ok)
    bad = c.handle("查询 群 与 不存在的概念 之间的关系")
    print(f"    解析失败示例：ok={bad.ok} error={bad.error}")
    print(f"    summary={bad.summary}")
    print(f"    候选概念（前3）={[x['name'] for x in bad.payload['candidate_concepts'][:3]]}")
    check("概念解析不到时 fail 并列出候选概念",
          (not bad.ok) and bad.error and len(bad.payload["candidate_concepts"]) == len(g.concept_by_id))
    unk = c.handle("帮我看看这个怎么样")
    check("未命中关键词时如实说无法分派", (not unk.ok) and "无法分派" in unk.summary)

    # ============================================================ I1 服务面
    print("[15] I1 服务面：neighbors / relations_between / contradictions / structural_duplicates")
    kn_before = {n: (st.data / f"{n}.json").read_bytes() for n in ("concepts", "relations", "literature")}
    nb1 = c.neighbors("0000", depth=1)
    nb2 = c.neighbors("0000", depth=2)
    nbt = c.neighbors("0000", depth=1, max_nodes=2)
    nbx = c.neighbors("9999")
    rb1 = c.relations_between("0000", "0001")
    rb0 = c.relations_between("0000", "0006")  # 0006 是孤立概念
    kn_after = {n: (st.data / f"{n}.json").read_bytes() for n in ("concepts", "relations", "literature")}
    print(f"    neighbors(0000,depth=1)：{[(n['concept_id'], n['distance']) for n in nb1['nodes']]}")
    print(f"    neighbors(0000,depth=2) 的 2 跳节点："
          f"{[n['concept_id'] for n in nb2['nodes'] if n['distance'] == 2]}")
    print(f"    neighbors(max_nodes=2)：truncated={nbt['truncated']} 节点数={len(nbt['nodes'])} 理由={nbt['reason'][-40:]!r}")
    print(f"    neighbors(9999)：checked={nbx['checked']} empty={nbx['empty']} reason={nbx['reason'][:36]!r}…")
    print(f"    relations_between(0000,0001)：{rb1['relation_ids']}；"
          f"relations_between(0000,0006)：ids={rb0['relation_ids']} empty={rb0['empty']} checked={rb0['checked']}")
    check("neighbors 的 1 跳恰好是图索引里的直接邻居",
          {n["concept_id"] for n in nb1["nodes"] if n["distance"] == 1} == set(g.neighbors("0000"))
          and any(n["distance"] == 0 for n in nb1["nodes"]))
    check("neighbors 的 2 跳把 2 跳新节点并进来且带上 distance",
          any(n["distance"] == 2 for n in nb2["nodes"])
          and "0006" not in {n["concept_id"] for n in nb2["nodes"]})
    check("neighbors 超 max_nodes ⇒ truncated=True（不静默截断）",
          nbt["truncated"] is True and len(nbt["nodes"]) == 2 and "max_nodes" in nbt["reason"])
    check("neighbors 查不到代号 ⇒ checked=True 且说明'该代号不在概念表里'",
          nbx["checked"] is True and nbx["nodes"] == [] and "不在概念表里" in nbx["reason"])
    check("relations_between 三态：有边给 relation_ids；无边 checked=True+empty=True",
          rb1["relation_ids"] == ["0000"] and rb0["relation_ids"] == [] and rb0["empty"] is True
          and rb0["checked"] is True and "没有关系" in rb0["reason"])
    check("I1 服务面只读：三张知识表逐字节不变", kn_before == kn_after)

    # ---- 矛盾 / 结构重复：另起一个小工作区，人造"矛盾对 + 重复对"
    st4 = make_store("service")

    def _svc_rel(rid, cids, desc, lit, qv=True):
        return {
            "relation_id": rid, "concept_ids": sorted(cids), "description": desc, "lit_id": lit,
            "page_range": {"start": 1, "end": 1, "label": "p. 1"}, "quote": f"引文 {rid}",
            "quote_normalized": f"引文 {rid}", "quote_verified": qv, "statement": desc,
            "status": "active", "concept_group_key": "|".join(sorted(cids)),
        }

    with st4.tx("concepts", "relations", "literature", actor="selftest", note="service") as tx:
        for cid, name in [("0000", "群"), ("0001", "阿贝尔群"), ("0002", "环"),
                          ("0003", "环"), ("0004", "桥甲"), ("0005", "桥乙"),
                          ("0006", "孤儿甲"), ("0007", "孤儿乙")]:
            tx.upsert("concepts", {"concept_id": cid, "name": name, "definition": "d",
                                   "normalized_name": T.normalize(name), "related_concepts": []})
        for r in [
            # 人造矛盾对：同概念组，一句**明确肯定**、一句**明确否定**（才够格 strong）
            _svc_rel("0000", ["0000", "0001"], "群是阿贝尔群", "0000"),
            _svc_rel("0001", ["0000", "0001"], "群不是阿贝尔群", "0001"),
            # 结构重复对：0002/0003 邻域完全相同且名字规范化后相同 ⇒ merge
            _svc_rel("0002", ["0002", "0004"], "环与桥甲", "0000"),
            _svc_rel("0003", ["0002", "0005"], "环与桥乙", "0000"),
            _svc_rel("0004", ["0003", "0004"], "环与桥甲（另一代号）", "0000"),
            _svc_rel("0005", ["0003", "0005"], "环与桥乙（另一代号）", "0000"),
        ]:
            tx.upsert("relations", r)
    c4 = AgentC(st4, actor="agent-C-service")
    con = c4.contradictions()
    con_scoped = c4.contradictions(relation_ids=["0000", "0001"])
    sd = c4.structural_duplicates()
    # 单独用"枚举上限=1"跑一次：验证"截断通知被单列"这条约束（正向/负控都要能测）
    sd_trunc = AgentC(st4, config={"structural_duplicate_max_pairs": 1}).structural_duplicates()
    print(f"    contradictions()：checked={con['checked']} scanned={con['scanned']} "
          f"命中={[x['relation_ids'] for x in con['contradictions']]} "
          f"strong={con['strong_count']} weak={con['weak_count']} method={con['method']}")
    print(f"    contradictions(relation_ids=[0000,0001])：scanned={con_scoped['scanned']} "
          f"命中={len(con_scoped['contradictions'])}")
    print(f"    structural_duplicates()：候选={[(x['concept_ids'], x['proposal']) for x in sd['candidates']]} "
          f"truncation_notice={'有' if sd['truncation_notice'] else '无'}")
    print(f"    枚举上限=1 时：候选={len(sd_trunc['candidates'])} 条，"
          f"truncation_notice={'有' if sd_trunc['truncation_notice'] else '无'}")
    check("contradictions 命中人造矛盾对且标为 strong；method_note 声明分档与假阳性",
          con["checked"] is True and len(con["contradictions"]) == 1
          and con["contradictions"][0]["strength"] == "strong"
          and con["strong_count"] == 1 and con["weak_count"] == 0
          and con["method"] == "literal"
          and "只做字面判据，不声称能判定一般语义矛盾" in con["method_note"]
          and "strong" in con["method_note"] and "假阳性" in con["method_note"])
    check("contradictions 给了 relation_ids 就只扫这些（scanned 等于给定条数）",
          con_scoped["scope"] == "given_relation_ids" and con_scoped["scanned"] == 2
          and len(con_scoped["contradictions"]) == 1)
    check("structural_duplicates 正向：邻域相同 + 同名 ⇒ proposal=merge",
          any(x["proposal"] == "merge" and set(x["concept_ids"]) == {"0002", "0003"} for x in sd["candidates"]))
    check("structural_duplicates 负控：邻域相同但名字不同 ⇒ proposal=review 且写明'不得据此合并'",
          any(x["proposal"] == "review" and set(x["concept_ids"]) == {"0004", "0005"}
              and "不得据此合并" in x["reason"] for x in sd["candidates"]))
    check("structural_duplicates 负控：孤立概念不参与枚举",
          all("0006" not in x["concept_ids"] and "0007" not in x["concept_ids"] for x in sd["candidates"]))
    check("structural_duplicates 的截断通知与候选分开（下游不会把它当成一对概念）",
          sd_trunc["truncation_notice"] is not None
          and sd_trunc["truncation_notice"]["is_truncation_notice"] is True
          and all(not x.get("is_truncation_notice") for x in sd_trunc["candidates"]))

    # ============================================================ I3 缺口直连 A
    print("[16] I3 缺口直连 A：gaps(submit_requests=True) 的闸门与三态")
    st5 = make_store("i3")

    def _i3_fixture(target: Store) -> None:
        with target.tx("concepts", "relations", "literature", actor="selftest", note="i3") as tx:
            for i in range(4):
                tx.upsert("concepts", {"concept_id": f"{i:04d}", "name": f"概念{i}", "definition": "d",
                                       "normalized_name": T.normalize(f"概念{i}"), "related_concepts": []})
            for r in [
                _svc_rel("0000", ["0000", "0001"], "一条足够长的关系描述用于评分", "0000"),
                _svc_rel("0001", ["0000", "0002"], "一条足够长的关系描述用于评分", "0001"),
                _svc_rel("0002", ["0001", "0003"], "一条足够长的关系描述用于评分", "0000"),
            ]:
                tx.upsert("relations", r)

    _i3_fixture(st5)
    c5 = AgentC(st5, actor="agent-C-i3")
    req_before = (st5.data / "search_requests.json").read_bytes()
    rep_off = c5.gaps(submit_requests=False)
    req_after_off = (st5.data / "search_requests.json").read_bytes()
    rep_on = c5.gaps(submit_requests=True)
    rows5 = st5.rows("search_requests")
    topics5 = {"、".join(x["concept_names"]) for x in rep_on.payload["candidate_gaps"]}
    print(f"    候选={len(rep_on.payload['candidate_gaps'])} 条；"
          f"关闭时新增={len(rep_off.payload['submitted_request_ids'])} 条"
          f"（enabled={rep_off.payload['request_submission']['enabled']}）")
    print(f"    开启后新增={len(rows5)} 条："
          f"{[(r['request_id'], r['topic'], r['submitted_by'], r['priority'], r['mode']) for r in rows5]}")
    print(f"    被拒={len(rep_on.payload['rejected_requests'])} 条，"
          f"示例理由={rep_on.payload['rejected_requests'][0]['reason'][:48] if rep_on.payload['rejected_requests'] else '（无）'}…")
    check("I3 默认关闭：submit_requests=False 时一条 search_requests 都不写（逐字节不变）",
          req_before == req_after_off
          and rep_off.payload["submitted_request_ids"] == [] and rep_off.payload["request_submission"]["enabled"] is False)
    check("I3 正向：新增 ≤3 条，且 submitted_by/priority/mode/topic 全部合规",
          0 < len(rows5) <= 3
          and all(r["submitted_by"] == "agent-C" and r["priority"] == "medium"
                  and r["mode"] == "topical" and r["topic"] in topics5 and not r["done"] for r in rows5))

    st6 = make_store("i3gate")
    _i3_fixture(st6)
    with st6.tx("search_requests", actor="selftest", note="i3gate") as tx:
        for i in range(20):
            row = S.SearchRequest(
                request_id=f"r-{i + 1:04d}", timestamp=S.now_iso(), topic=f"占位主题{i}",
                mode="topical", submitted_by="agent-D",
            )
            row.validate()
            tx.upsert("search_requests", row.to_dict())
    gate_before = (st6.data / "search_requests.json").read_bytes()
    rep_gate = AgentC(st6, actor="agent-C-i3gate").gaps(submit_requests=True)
    print(f"    在途 20/20（上限）时：新增={len(rep_gate.payload['submitted_request_ids'])} 条，"
          f"被拒={len(rep_gate.payload['rejected_requests'])} 条")
    check("I3 闸门：在途到上限时拒绝而不是无限排队，且逐条留下理由",
          rep_gate.payload["candidate_gaps"]
          and rep_gate.payload["submitted_request_ids"] == []
          and gate_before == (st6.data / "search_requests.json").read_bytes()
          and len(rep_gate.payload["rejected_requests"]) == len(rep_gate.payload["candidate_gaps"])
          and all("已达上限" in r["reason"] for r in rep_gate.payload["rejected_requests"]))

    print("=" * 72)
    failed = [lbl for lbl, okk in CHECKS if not okk]
    print(f"自检断言：{len(CHECKS) - len(failed)}/{len(CHECKS)} 通过")
    if failed:
        for lbl in failed:
            print(f"  FAILED: {lbl}")
    print("SELF-CHECK " + ("DONE" if not failed else "FAILED"))
