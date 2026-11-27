"""C 包内部件共用的小工具（口径与包入口同一份）。

定位、各分析器口径、报告形态与服务面见 `agent_c/__init__.py` 的模块 docstring —— 这里
不复制一份会漂的副本。本文件只放图/路径工具、报告类型与受控小工具。
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
    keys = (key, *aliases)
    for k in keys:
        if k in cfg:
            return cfg[k]
    sub = cfg.get("score")
    if isinstance(sub, Mapping):
        for k in keys:
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
        
        - 先写文件：如果反过来（先提交登记行、再写文件），一旦写文件失败，表里就留下一行指向不存在文件的记录。D 读的是登记行，它会照着`markdown_path` 去打开一个
        不存在的文件 —— 这是最坏的失败形态。现在的顺序最坏情况只是一个没有登记行引用的孤儿文件，无害且可清理。- 登记行与 ID 在同一事务里：`alloc_id` 必须在持锁
        事务内进行，否则两个 C 实例会拿到同一个 `report_id`，而按主键 upsert 会静默互相覆盖。
        
        `kind` 必须是 §schema 的受控词表之一。`handle()` 在无法分派时给出的`kind="unknown"` 不能落盘 —— 落进表里的 report 必
        须能被 D 按`kind` 分派到对应的解析逻辑，塞一个表外的 kind 进去会让 D 的读取端出洞。
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
        out_dir = Path(reports_dir) if reports_dir else (Path(st.root) / "work" / "C")
        # 2026-11-27（MSOWN）：C 的分析报告稿改成落在 `manuscripts/C/`、用 C 自己的稿号
        # （族 `c-analysis`，号源 `cmanuscript`）—— 与 A 的汇报稿一样"一个角色一套稿号"。
        # `report_id` 仍是台账身份（`analysis_reports` 的主键），稿号是文件身份，两者并存。
        # 旧盘上的 `work/C/<rid>-<kind>.md` 读得通（`markdown_path` 逐行记着），不搬数据。
        use_family_landing = reports_dir is None
        if use_family_landing:
            from .. import manuscriptids as _MI  # 惰性：号源只有一处

            cid = _MI.next_manuscript_id(st.root, family="c-analysis",
                                         owner=str(who or ""), role="C")
            rel_name = _MI.canonical_rel(cid, family="c-analysis")
        else:
            cid = ""
        with st.tx("analysis_reports", actor=who, note=f"analysis_report:{self.kind}") as tx:
            rid = tx.alloc_id("report")
            if not use_family_landing:
                rel_name = f"work/C/{rid}-{self.kind}.md"
            abs_path = (Path(st.root) / rel_name) if use_family_landing else (out_dir / f"{rid}-{self.kind}.md")
            body = self.markdown
            if use_family_landing:
                # 稿头：归属与台账身份都写清（`manuscriptown` 只读 `产出者` 这一行判写权）
                body = (f"# C 的分析报告（{self.kind}）\n\n"
                        f"- 产出者：{who}\n- 报告号：{rid}\n- 报告种类：{self.kind}\n"
                        f"- 稿号：{cid}（族 c-analysis）\n\n" + body)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(abs_path, body)
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
        # ---- 产物归属（`ARTIFACTS.jsonl`）：报告 markdown 已经落盘 ⇒ 补"归谁产"。
        #
        # 放在事务之外：登记失败若让这笔事务回滚，盘上会留一份"有文件、没登记行"的报告
        # （`verify` 的 `report_file_missing` 反着查不出来）。放在提交之后：行与文件都
        # 在，"这一条没有归属"由异常大声说出（不是被回滚盖住）。
        # `reports_dir` 指到工作区外时这里同样会失败 —— 那是"产物离开沙箱"，本该报。
        from .. import artifacts as A

        _producer = str(who or "agent-C").strip()
        if _producer.startswith("agent-"):
            _producer = _producer[len("agent-"):]
        _entry, _problem = A.record_or_problem(
            st.root, path=rel_name, producer=_producer or "C",
            kind=f"analysis-report-{self.kind}",
            note=f"C 的分析报告（{self.kind}，agent_c.AnalysisReport.persist）")
        if _problem:
            raise RuntimeError(
                f"{_problem}。报告已写盘（{rel_name}）且 analysis_reports 行已落库，"
                "但这条路径没有产物归属登记 ⇒ 这次落盘按失败报（补登记："
                f"`agentflow artifacts record {rel_name} --producer {_producer or 'C'}`）")
        return {"report_id": rid, "markdown_path": rel_name, "abs_path": str(abs_path)}
from ..specs.c import SPEC  # noqa: E402,F401


