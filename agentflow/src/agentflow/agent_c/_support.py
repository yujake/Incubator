"""智能体 C：关系分析（程序做分析，LLM 只做排序与措辞）。

## 定位（DESIGN-TOOLS.md §3.1）

需求原文是"用程序分析关系表"。所以本模块的默认实现里：

- 计数、索引、图搜索、路径枚举、去重、评分、溯源，全部是确定性代码
  （图与索引在 `tools/graph_tools.py`，代号溯源在 `tools/trace_tools.py`）；
- 只有两处留 LLM 钩子，且默认关闭（构造时 `llm=None` 即可）：
  ① 路径"最合理关系链"的排序；② "是否值得研究"的判断。
  两个钩子都有确定性回退，因此没有 API key 时功能降级但不缺失，
  并且整条链路可以在单测里被断言（自检块就是这么做的）。

为什么要这么克制地使用 LLM：C 的产出是 D 的证据来源。如果"最热门的 5 个概念"
这种纯计数问题也过一遍模型，那么同一份数据两次运行会给出不同的报告 ——
D 无法引用一个会变的结论，人也无法审计"你凭什么说它热门"。把语义判断留在
钩子里、把事实判断钉死在代码里，是唯一能让报告可复现的做法。

## 四类分析器与它们各自最容易做错的地方

1. `hottest`：热度是 occurrences（概念在 `concept_ids` 里出现的次数），
   不是关系条数 —— 一条涉及 3 个概念的关系对其中每个概念都算 1 次出现。
   排序必须稳定（同分按 `concept_id` 升序），否则同分概念的相对顺序会随
   字典插入顺序漂移，报告每次都不一样。
2. `paths`：见下方"三条不让步的规则"。
3. `cold`："没人研究"（degree 小）与"没人连接"（degree=0 的完全孤立）是两件事，
   必须分开归类；否则"孤立概念"会混进冷门榜把真正的冷门方向挤掉。
4. `gaps`：需求说"若确实有，则报告"。所以必须有明确的"确实有/证据不足"
   二元结论，且不允许把"没找到"包装成"找到了" —— 那会让 D 去研究一个
   不存在的缺口，浪费一整个循环。凡被否决的候选都要留下否决理由。

## paths 的三条不让步的规则

(a) 只按"路径不同"去重是不够的。 两条只差一个中间节点的路径
（a-x-b 与 a-x-y-b）字面上是两条，实质上共享了绝大部分推理内容。
所以按节点集合的 Jaccard 相似度贪心筛：新路径与任何已选路径的重合度
`> max_overlap`（默认 0.5）就丢弃。注意是严格大于 —— 恰好等于 0.5 时保留，
因为 a-x-b 与 a-y-b 这类"换一个中间节点"的路径正是需求要的"多条不同路径"，
它们的 Jaccard 恰好是 0.5，用 `>=` 会把它们全部误杀。

(b) 每一跳都要重新读"全部"候选关系。 搜索算法扩展时只是随手挑了一条边，
而这一对概念之间可能同时存在好几条关系（不同文献、不同表述）。
"最合理的链"往往不是搜索时选中的那条。取候选后按 §3.3(4) 的确定性序重选。

(c) 评分必须能逐项打印。 报告要给 D 的不只是"high"这个标签，而是
"为什么判成 high"：`score_breakdown` 里逐项列出每个信号的输入值与贡献值。
否则 D 只能盲信一个分数，而分数是最不该被盲信的东西。同理，若一条 high
都没有，报告必须明说"没有找到高信息量路径"，不许把 medium 硬凑成 high。

## 报告形态：登记表 + 文件双份（§2.2）

`AnalysisReport.payload` 是 D 溯源用的机器可读部分（代号链、评分明细），
`AnalysisReport.markdown` 是人读的部分。`persist()` 把两者分别落到
`reports/<report_id>-<kind>.md` 与 `analysis_reports` 表。

## 服务面（DESIGN-INTERACTIONS.md §1 I1 / I3 / I5）

四类分析器是批处理：跑一次、产一份报告、进 `analysis_reports` 表。但真实研究是
问题驱动的 —— D 在追问某个问题时需要"这两个概念之间到底有哪些链条"，而那一刻 C 早已
跑完、上次报告里没有恰好那一条。所以本模块另外提供服务方法（`neighbors` /
`relations_between` / `contradictions` / `structural_duplicates`）：

- 同步、只读、有界，返回 dict（不产报告、不写知识表）；
- 每个结果都带 `checked` 三态位（`False` = 没查，`True` + `empty=True` = 查了没有）；
- 触及预算一定给 `truncated=True` 并说明原因 —— 静默截断会被下游读成
  "就这些"，而它是一条口吻确定的错误结论；
- 判据一律委托给冻结契约 `interactions`（矛盾、结构重复、冲突检查），
  绝不在这里写第二份。

唯一的写入路径是 `gaps(submit_requests=True)`（I3：把"应该有边却缺失"的候选直接
变成 A 的检索请求），默认关闭，且由 `gaps()` 的确定性代码路径完成 —— 它不经过
C 的工具与推理，写的也不是知识。工具面（`register_tools`）因此可以保持全量只读。
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from .. import dedup as D
from .. import interactions
from .. import schema as S
from .. import textutil as T
from ..store import Store, StoreError
from ..tools.base import ToolRegistry, fail, ok, tool
from ..tools.graph_tools import PathSearchResult, RelationGraph, relation_sort_key
from ..agentspec import AgentBrief, AgentSpec
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
DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "quote_true": 2.0,  # 有原文支撑是最强信号
    "quote_false": -1.5,  # 引文找不到 = 可疑
    "suspect": -1.0,  # 判重存疑
    "hop": 0.6,  # 多跳 = 更多推理链（min(跳数,3) 边际递减）
    "lit_diversity": 0.8,  # 跨文献的链条更有价值
    "short_desc": -0.5,  # 描述过短 = 信息量低
    "avoid_hot": 0.5,  # 绕开了最常见节点
}
DEFAULT_THRESHOLD_HIGH = 3.0
DEFAULT_THRESHOLD_MEDIUM = 1.5
LEVELS = ("high", "medium", "low")
ANALYZERS = ("hottest", "paths", "cold", "gaps")
SERVICE_MAX_DEPTH = 3
SERVICE_MAX_NODES = 500
SERVICE_MAX_CONTRADICTIONS = 50
SERVICE_MAX_STRUCTURAL_PAIRS = 100
SUBMITTER = "agent-C"
check_conflict = interactions.check_conflict
_MISSING = object()
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
    """读一个整数配置。

    三态纪律，这里只有两种"没读到"，而且必须分开：

    - 没有这个键 ⇒ 用 `default`（正常的"没配置"）；
    - 有这个键但值不是整数 ⇒ 当场抛（显式失败）。

    旧写法把两者都压成"用 default"，于是 `service_max_depth: "深"` 或
    `hot_top_n: null` 会静默地按默认值跑：不报错、不告警，只是上限/口径悄悄
    变成了另一个数。配置是人的意图，人的意图读不懂时必须说出来（FC-08）。
    """
    raw = _cfg_get(cfg, key, _MISSING, aliases=aliases)
    if raw is _MISSING:
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"配置项 {key}={raw!r} 不是整数（也可写成 {aliases}）。"
            "配置一旦读不动就必须显式失败：静默退回默认值会让上限/口径悄悄变掉而无人知道"
        ) from e
def _cfg_float(cfg: Mapping[str, Any], key: str, default: float, *, aliases: tuple[str, ...] = ()) -> float:
    """读一个浮点配置。语义与 :func:`_cfg_int` 相同：键不在用默认，值不合法就抛。"""
    raw = _cfg_get(cfg, key, _MISSING, aliases=aliases)
    if raw is _MISSING:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"配置项 {key}={raw!r} 不是数字（也可写成 {aliases}）。"
            "阈值被静默改掉会让'哪些路径算 high'这类结论整体漂移，且没有任何地方会报错"
        ) from e
def _service_int(value: Any, *, name: str, default: int) -> int:
    """服务面参数（`depth` / `max_nodes` / `limit`）→ int。

    三种读法，不许压成两种（旧写法把后两种都折成"用默认值"）：

    - ``None``            ⇒ 用该方法的默认口径（调用方没表达意图）；
    - 合法整数            ⇒ 照用（再夹进服务上限；超上限会 `clamped`/`truncated` 并说明）；
    - 读不成整数      ⇒ `ValueError`（显式失败）。

    为什么最后一种必须炸：`contradictions(limit="三")` 旧写法会静默按上限算，
    而返回的 `meta["limit"]` 还是那个上限值 —— 调用方以为"我限了 3 条"，实际拿到的是
    "能取多少取多少"。一个读不懂的参数被读成另一个值，比报错危险得多。
    """
    if value is None:
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"{name}={value!r} 不是整数。服务面参数读不懂时必须显式失败："
            "静默改用默认/上限会让调用方以为'我限了'，而实际是'能取多少取多少'"
        ) from e
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
@dataclass
class AnalysisReport:
    """C 的返回对象（注意：与 `schema.AnalysisReport` 那个"登记行"不是同一个东西）。

    为什么要分成两个类：返回对象要带 `markdown` 全文与逐项评分明细（可能很大），
    而登记行是要落进 `analysis_reports` 表的结构化记录。把返回对象直接当行写入，
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
    #: 分析是否完成。False 表示"这次没能给出结论"（概念解析不到、关系表为空等），
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

        顺序是刻意的：先在事务内拿号、写文件，再写登记行、提交。

        - 先写文件：如果反过来（先提交登记行、再写文件），一旦写文件失败，
          表里就留下一行指向不存在文件的记录。D 读的是登记行，它会照着
          `markdown_path` 去打开一个不存在的文件 —— 这是最坏的失败形态。
          现在的顺序最坏情况只是一个没有登记行引用的孤儿文件，无害且可清理。
        - 登记行与 ID 在同一事务里：`alloc_id` 必须在持锁事务内进行，否则两个
          C 实例会拿到同一个 `report_id`，而按主键 upsert 会静默互相覆盖。

        `kind` 必须是 §schema 的受控词表之一。`handle()` 在无法分派时给出的
        `kind="unknown"` 不能落盘 —— 落进表里的 report 必须能被 D 按
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
            json.dumps(self.payload, ensure_ascii=False, default=str)
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
from ..specs.c import SPEC  # noqa: E402,F401
