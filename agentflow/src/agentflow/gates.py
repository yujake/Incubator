"""H（审校）的 G1–G15 门引擎 —— 15 道独立、有名字、可单独查询的检查器。

## 这个模块的规格来源

`draft/17-正式文稿体例（参考投影度量论）.md` §8.4（第 1054–1074 行）给出 H 应有的
15 道门。本模块逐条落地那张表：门号、判据、照搬哪个脚本、失败处置都写进
:data:`GATES` 的声明表里，一个门号都不许少。若某道门在我们这里暂时
没有可判定的对象，它仍然是一个门，并如实返回 `not_applicable` + 理由 ——
删门会让"15 道门都在跑"这句话变成假话（这正是本项目最忌讳的那种"看起来完整"）。

## 四条结构纪律（每一条都是参考体例里最值得抄的制度）

### 1. 每道门都要能返回"没做"（三态，`DEVELOPMENT.md` §3 纪律 1）

`verdict` 有三个互相独立的取值，绝不许折叠：

```text
pass            查过了，没有该门判据下的问题
fail            查过了，有该门判据下的问题
unknown         没查成（缺输入 / 依赖读不到 / 本轮没跑过）
not_applicable  这道门在本项目的数据模型上没有可判定的对象（附理由）
```

参考体例的教训逐字是（`draft/17-…md:675-676`）：
*"多数脚本不设退出码，于是『未报错』被误读为『无问题』"*。
所以本模块里"缺少输入"永远不是 `pass`：它必须带着一句
"我还缺什么才能判"的 reason。

### 2. 零发现必须自证（G13）

某道门报"零发现"时，报告里必须带"我用了什么过程、数出了什么数字"
（例如"扫了 37 条断言、15 个引用、0 个未解析"）。只写"无问题"不合规。
这条在结构上强制：:meth:`GateResult.__post_init__` 会让
"`pass` 且 `findings == []` 且 `self_attestation` 为空"直接抛 `ValueError` ——
于是 H 没法产出一份不合规的报告（缺一个就是 H 自己的格式违规）。

### 3. 报告必须钉住被审版本的 hash（G11）

审校结论要带上"被审对象的内容 hash"（:func:`agentflow.claimanatomy.revision_hash`），
否则行号/结论会失效。报告层把它写在头部（不是脚注）。

### 4. 报告里必须有"我这一轮犯的错"一节（G15）

缺失则退回。参考体例把这个字段放在报告头里，不许省。
本模块把它做成 :func:`gate_report` 的必填参数 `own_errors`：
不传就写"未登记"，而 G15 会因此判 `fail` —— "我没犯错"这句话必须
由人显式写出来，而不是由"没写"默认成立。

## 与 `claimanatomy` 的分工（FC-03：判据只有一份）

字段级/交叉轴的判据全部在 `claimanatomy`（G2/G3/G6/G7/G14 都只是
"把它的结论按门的口径汇总并附自证数字"）。本模块不重写任何一条字段判据。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import claimanatomy as CA
from . import schema as S
from .tools import doc_tools

__all__ = [
    "GATES",
    "GATE_IDS",
    "AXES",
    "GATE_AXIS",
    "AXIS_UNDECIDED",
    "GATE_CRITERIA_REVISION",
    "GateContext",
    "GateResult",
    "GatesReportError",
    "attest",
    "gate_report",
    "gate_verdict",
    "known_gate_ids",
    "render_review_report",
    "run_all_gates",
    "run_gate",
]

# ---------------------------------------------------------------- 受控词表

#: 轴见 `AXES`（`STYLE/RUBRIC.md:30-33` 的口径，见 §8.4 G10 行）。
#: 「每条发现必须有：轴 + 严重度 + 行号 + ≤20 词逐字引文 + 最小修法 + maths: yes/no」——
#: 所以"轴"是一个受控词，不是自由文本。
#:
#: 词表里有几个轴以元组本身为准（今天 4 个：数学 / 体例 / 工程 / 证据）：
#: 这里原先写的是"三道轴"，与元组不一致 —— 一个写着旧数字的注释会把人指向
#: 另一套口径，而没有任何判据会发现它（`temp/DRIFT-LIST.md` §2.2 登记过这一处）。
AXES = ("数学", "体例", "工程", "证据")

#: 门判不了轴时的占位（不是一个轴）。刻意与 `AXES` 分开：
#: 把"轴未知"塞进 `AXES` 会让"每条发现都有轴"这句话在计数上永远成立。
AXIS_UNDECIDED = "（轴未定）"

#: 15 个门号 —— 硬编码成元组是刻意的：它是"15 道门都在跑"这句话的机器可读形式。
#: `tests/test_gates.py::test_every_gate_id_from_the_spec_exists` 逐条比对。
GATE_IDS: tuple[str, ...] = tuple(f"G{i}" for i in range(1, 16))


class GatesReportError(ValueError):
    """报告自身不合规（缺"我犯的错"一节 / 缺 hash / 零发现却没有自证数字）。

    为什么单独一个异常类：这三种失败不是被测稿件的问题，
    而是审校报告自己的格式违规 —— 两者的处置完全不同
    （前者让 G 改稿，后者让 H 重写报告）。
    """


# ---------------------------------------------------------------- 门结果


@dataclass(frozen=True)
class GateResult:
    """一道门的结构化结论。

    字段刻意分成四组，对应 §8.4 表格的四列 + 两条结构纪律：

    ==================  ==================================================
    组                    字段
    ==================  ==================================================
    身份                 `gate_id` / `name` / `axis` / `criterion`
    结论                 `verdict` / `reason`
    发现                  `findings`（每条带 `evidence`）
    自证                  `self_attestation` / `counts` / `evidence_used`
    ==================  ==================================================
    """

    gate_id: str
    name: str
    axis: str
    criterion: str
    verdict: str
    reason: str
    findings: tuple[dict, ...] = ()
    #: 我用了什么过程（人话 + 可复跑的命令形态）。
    self_attestation: str = ""
    #: 我数出了什么数字（零发现时必须非空，见 `__post_init__`）。
    counts: dict[str, Any] = field(default_factory=dict)
    #: 我实际用了哪些证据（表名 / 字段名 / 文件 / 命令）。
    evidence_used: tuple[str, ...] = ()
    #: 判据是"逐字照搬 §8.4"还是"在我们数据模型上的适配"（见
    #: :data:`GATE_CRITERIA_REVISION`）。适配必须显式登记，否则
    #: "15 道门都在跑"会掩盖"其中几道跑的是被改写过的判据"。
    #:
    #: 这个默认值只是给本模块之外的临时构造留的兜底（例如测试里手捏一个
    #: `GateResult`）：15 道门一个都不许用到它 —— 每个 `gate_gN` 都从声明表取，
    #: `_no_doc` 那条返回路径也从声明表取。`tests/test_coverage_gates.py` 的 AST
    #: 断言会逐个数 `gate_g*` 函数里的 `GateResult(...)`：凡是没传
    #: `criterion_revision=` 的当场红（否则默认值会替一道适配过的门谎称
    #: "逐字照搬"，那正是 G-12 的形态）。
    criterion_revision: str = "逐字照搬 §8.4"

    def __post_init__(self) -> None:
        if self.gate_id not in GATE_IDS:
            raise ValueError(f"未知门号 {self.gate_id!r}；G1–G15 必须齐全（不许自造门）")
        if self.verdict not in ("pass", "fail", "unknown", "not_applicable"):
            raise ValueError(
                f"{self.gate_id} 的 verdict={self.verdict!r} 不在 "
                "('pass','fail','unknown','not_applicable') 里。"
                "三态纪律：『没查成』(unknown) 与『查过没问题』(pass) 不许折叠"
            )
        if self.verdict in ("fail", "unknown", "not_applicable") and not self.reason.strip():
            raise ValueError(f"{self.gate_id} 判 {self.verdict} 却没说理由 —— 结论没有依据")
        # 零发现自证（G13 的结构形式）：`pass` + 无发现 ⇒ 必须有自证数字。
        if self.verdict == "pass" and not self.findings:
            if not self.self_attestation.strip():
                raise ValueError(
                    f"{self.gate_id} 报了『零发现』却没写自证（用了什么过程、数出了什么数字）。"
                    "**只写『无问题』不合规** —— 参考体例 STYLE/RUBRIC.md:105-107："
                    "某个轴『零发现』时必须报告过程与数字（G13）"
                )
            if not self.counts:
                raise ValueError(
                    f"{self.gate_id} 的零发现自证里没有**任何数字**（counts 为空）。"
                    "自证的全部意义就是给出可核对的数字，例如"
                    "『扫了 37 条断言、15 个引用、0 个未解析』"
                )
        if self.findings:
            for i, f in enumerate(self.findings):
                if not str(f.get("evidence") or "").strip():
                    raise ValueError(
                        f"{self.gate_id}.findings[{i}] 没有 evidence —— "
                        "只写『看起来不对』的发现会让审校变成另一种幻觉的来源"
                        "（`schema.ReviewFinding.evidence` 必填非空的同一条纪律）"
                    )

    @property
    def finding_count(self) -> int:
        """发现条数（报告与测试都读它；与 `to_dict()` 的 `finding_count` 同一口径）。"""
        return len(self.findings)

    def to_dict(self) -> dict:
        return {
            "gate_id": self.gate_id,            "name": self.name,
            "axis": self.axis,
            "criterion": self.criterion,
            "criterion_revision": self.criterion_revision,
            "verdict": self.verdict,
            "reason": self.reason,
            "findings": [dict(f) for f in self.findings],
            "finding_count": len(self.findings),
            "self_attestation": self.self_attestation,
            "counts": dict(self.counts),
            "evidence_used": list(self.evidence_used),
        }


def attest(process: str, counts: Mapping[str, Any], *, evidence_used: Iterable[str] = ()) -> dict:
    """构造一份自证块（G13 的载体）。

    为什么单独一个构造函数而不是让每道门自己拼字符串：自证的判据是
    "有过程 + 有数字"，这两件都必须非空。把它做成构造函数，
    缺失就是当场失败，而不是等 G13 事后发现（事后发现意味着
    已经产出了一份不合规的报告）。

    `process` 空 ⇒ 抛。这不是形式主义：参考体例的实测范例
    （`p6_..._REFEREE.md:48-56`）逐字写出了"我扫了哪些文件、用什么规则"，
    而那正是它可被复核的原因。
    """
    if not str(process or "").strip():
        raise GatesReportError("自证必须写清『用了什么过程』（空过程 = 没有自证）")
    clean = {str(k): v for k, v in dict(counts).items()}
    if not clean:
        raise GatesReportError(
            "自证必须给出数字（counts 为空）。参考体例的范例形如"
            "『扫了 37 条断言、15 个引用、0 个未解析』"
        )
    return {"process": str(process), "counts": clean, "evidence_used": [str(x) for x in evidence_used]}


def _attest_text(block: Mapping[str, Any]) -> str:
    """把自证块压成一行可读文本（进报告头/表）。"""
    counts = "、".join(f"{k}={v}" for k, v in dict(block.get("counts") or {}).items())
    return f"{block.get('process')}（{counts}）"


# ---------------------------------------------------------------- 输入上下文


@dataclass
class GateContext:
    """跑 15 道门所需的全部输入。每一项的可缺失性都是刻意的。

    ==========================  ==============================================
    输入                          缺了会怎样
    ==========================  ==============================================
    `doc`                        门判 `unknown`（没有可审的对象）
    `dependencies=None`          依赖相关门判 `unknown`（没查，不是"都闭合"）
    `files`                      自含性/虚证/可复跑门判 `unknown`
    `workspace_root`             文件存在性判 `unknown`（读不到 ≠ 不存在）
    `run_evidence`               可复跑门（G8）判 `unknown`
    `findings`                   审校格式门（G10）判 `unknown`
    `claim_counts`               计数一致门（G9）判 `unknown`
    `banned_words`              禁词门（G5）判 `not_applicable`
    ==========================  ==============================================

    为什么用一个大 dataclass 而不是 15 个参数：门之间要交叉引用
    同一批输入（G4 要 `claim_counts`，G9 也要），而"每道门自己去找输入"
    会让"我用了哪些证据"这件事无法回答 —— 而它正是 §8.4 表格要求逐条给出的。
    """

    doc: Mapping[str, Any] | None = None
    dependencies: Sequence[Mapping[str, Any]] | None = None
    files: Sequence[str] | None = None
    workspace_root: Path | None = None
    run_evidence: Mapping[str, Any] | None = None
    findings: Sequence[Mapping[str, Any]] | None = None
    claim_counts: Mapping[str, Any] | None = None
    banned_words: Sequence[str] | None = None
    literals: Mapping[str, Any] | None = None
    #: 上一轮审校时钉住的 hash（G11：比对"审校期间文件有没有被改"）。
    observed_hash: str | None = None
    #: 版本是否真的冻结（G11 通过 = `observed_hash` 与 :attr:`revision_hash` 逐字相等）。
    #:
    #: `findings` 与 `observed_hash` 的耦合（`X-96.3-2`，依据 `draft/28` §96.3 第 2 条）：
    #: `line` 的判据是「G11 通过后必填」，而"G11 通过"这件事在跑 G10 的那一刻
    #: 只能由本上下文回答 —— 门与门之间不互相传 `verdict`（:func:`run_all_gates`
    #: 各跑各的），所以"冻没冻"必须在这里算一次、由两边共用同一份口径，
    #: 不许 G10 另写一遍 `observed_hash == revision_hash`（FC-03）。
    #:
    #: 三态，与 :meth:`build` 的推导逐字对应：
    #:   * `True`  = 冻结成立（G11 会 pass）⇒ `line` 这一格必填
    #:     （给 `line_unavailable_reason` 不再是合规的第三态：版本已冻结，
    #:     "行号拿不到"这句话与事实矛盾）；
    #:   * `False` = 没冻（`observed_hash` 没给 / 与 :attr:`revision_hash` 不匹配）
    #:     ⇒ `line` 这一格不判（G11 自己会判 `unknown` 或 `fail`）；
    #:   * `None`  = 判不了（没给 `findings`，或稿件为空/算不出 hash）
    #:     ⇒ 不据此判任何东西（三态纪律：判不了 ≠ 没冻）。
    #:
    #: 注意：这是 :meth:`build` 那一刻的快照（`build` 之后直接改
    #: `ctx.observed_hash` 不会刷新它 —— 夹具与调用方都这么干过）。所以消费方
    #: 不许读这一格：要用的是 :meth:`frozen_version`，它每次现算。
    findings_version_pinned: bool | None = None
    #: 调用方显式声明的"我这一轮犯的错"（G15 的输入）。
    own_errors: Sequence[str] | None = None
    #: 被审对象的内容 hash（G11 的输出，建上下文时算一次）。
    revision_hash: str = ""
    #: 依赖闭合是否真的查过（`dependencies=None` 时 False）。
    deps_checked: bool = False

    @classmethod
    def build(
        cls,
        doc: Mapping[str, Any] | None,
        *,
        dependencies: Sequence[Mapping[str, Any]] | None = None,
        **kw: Any,
    ) -> "GateContext":
        """建上下文并算一次被审版本 hash（G11 的输入）。

        `dependencies=None` 与 `dependencies=[]` 的区别就是三态纪律本身：
        前者是"没查"，后者是"查了、一条依赖都没有"。

        ---- `findings` 与 `observed_hash` 的接线（`X-96.3-2`）----

        这里多算一格 :attr:`findings_version_pinned`：`findings` 给了、且
        `observed_hash` 与刚算出的版本 hash 逐字相等 ⇒ 版本确实冻结，于是
        `line` 那一格从"可给可不给"变成"必填"（`G10` 消费它）。
        反过来 `findings` 没给 / hash 不匹配 / 算不出 hash ⇒ 这一格不适用
        （`None` / `False`），`G10` 不据此判任何东西 —— 它与 G11 各报各的，
        不折叠成一档（"没冻"与"判不了"必须分得开）。
        """
        deps: Sequence[Mapping[str, Any]] | None = dependencies
        checked = deps is not None
        revision_hash = CA.revision_hash(doc) if isinstance(doc, Mapping) else ""
        ctx = cls(
            doc=doc,
            dependencies=deps,
            deps_checked=checked,
            revision_hash=revision_hash,
            **kw,
        )
        # 在上面那一次构造之后推导：`observed_hash` 可能来自 `**kw`，
        # 在构造前读 `cls(...)` 的字段会漏掉调用方给的那一份。
        ctx.findings_version_pinned = _derive_findings_version_pinned(ctx)
        return ctx

    # ---- 小工具（门共用，避免每道门自己写一遍而漂移）

    def claims(self) -> list[Mapping[str, Any]]:
        """稿件的断言列表（归一后的视图：`text` 已改名成 `statement`）。"""
        if not isinstance(self.doc, Mapping):
            return []
        raw = self.doc.get("claims") or []
        out: list[Mapping[str, Any]] = []
        for c in raw:
            if not isinstance(c, Mapping):
                continue
            try:
                out.append(CA.migrate_claim(c))
            except ValueError:
                # 键名冲突（text 与 statement 不同）由 `validate_claim` 报 error，
                # 这里原样带上，让门仍然能数出"扫了几条断言"。
                out.append(dict(c))
        return out

    def workspace(self) -> Path | None:
        """工作区根（用于判断"文件在不在"）。没有就返回 None ⇒ 门判 unknown。"""
        return Path(self.workspace_root) if self.workspace_root is not None else None

    def frozen_version(self) -> bool | None:
        """现算的"版本冻结了吗"（`X-96.3-2`）—— 消费方只许用这一个入口。

        与 :attr:`findings_version_pinned`（`build()` 那一刻的快照）同一份判据
        （:func:`_derive_findings_version_pinned`），区别只在何时算：
        直接改过 `ctx.observed_hash` / `ctx.doc` 的调用方（夹具与 `gate_report`
        的调用路径都这么干）不会刷新那份快照，而门是在跑的那一刻判案的
        —— `gate_g10` 因此走这个入口，与 `gate_g11` 自己"每次现算
        `observed_hash == revision_hash`"的做法逐字对齐。
        """
        return _derive_findings_version_pinned(self)


def _derive_findings_version_pinned(ctx: "GateContext") -> bool | None:
    """`:attr:`GateContext.findings_version_pinned`` 的唯一推导处（`X-96.3-2`）。

    模块级而不是方法：它被 :meth:`GateContext.build` 与
    :meth:`GateContext.frozen_version` 两处调用，口径只此一份（FC-03）。
    私有（名字带下划线）是因为消费方不该直接调它 —— 要用的是
    :meth:`GateContext.frozen_version`。

    判据逐字来自 `draft/28` §96.3 第 2 条："`line` 的『G11 通过后必填』没接线
    （`GateContext` 里 `findings` 与 `observed_hash` 不相绑）"。
    "G11 通过"在这里等价于 :func:`gate_g11` 自己那一句
    `str(ctx.observed_hash) == ctx.revision_hash`（它 pass 的充要条件）——
    刻意不在 G10 里重写一遍那个比较（FC-03：判据只有一份）。

    三态（与 `findings_version_pinned` 的字段文档逐字对应）：

    * `None`：`findings is None`（没有可判的对象）或 `revision_hash` 为空
      （算不出被审版本的 hash ⇒ "冻没冻"这件事本身判不了）；
    * `True`：给了 `findings`、算得出 hash、且 `observed_hash` 与之逐字相等
      ⇒ 版本冻结成立 ⇒ `line` 必填；
    * `False`：其余（`observed_hash` 没给、给了但不匹配）⇒ 没冻，`line` 不判。
    """
    if ctx.findings is None or not ctx.revision_hash:
        return None
    return bool(ctx.observed_hash) and str(ctx.observed_hash) == ctx.revision_hash


# ---------------------------------------------------------------- 门实现
#
# 约定：每个实现函数只做"判定 + 数数 + 自证"，不重写 claimanatomy 的字段判据。


def _no_doc(gate_id: str, axis: str, criterion: str) -> GateResult:
    """没有可审对象时的统一出口 —— `unknown` + 说清缺什么。

    这里也必须从 :data:`GATE_CRITERIA_REVISION` 取值：15 道门各有一句
    `if ctx.doc is None: return _no_doc(...)`，所以"调用方没给稿件"这条返回路径
    同样会打印 `criterion_revision`。若让 `GateResult` 的默认值从这里漏出去，
    同一个门号在两条路径上就会打印两份不同的判据修订状态（G-12）。
    """
    return GateResult(
        gate_id=gate_id,
        name=GATES[gate_id]["name"],
        axis=axis,
        criterion=criterion,
        criterion_revision=GATE_CRITERIA_REVISION[gate_id],
        verdict="unknown",
        reason=(
            "调用方**没有提供被审稿件**（`doc=None`）⇒ 这道门**没跑**。"
            "这不是『没有问题』：没有对象就没有发现，而没有发现也不构成证据"
        ),
    )


def _iter_doc_files(ctx: GateContext) -> list[str]:
    """引用/路径来源：显式 `files`，否则从稿件里的 `proof_location` 与依赖里抽。"""
    out: list[str] = [str(f) for f in (ctx.files or [])]
    for c in ctx.claims():
        loc = str(c.get("proof_location") or "").strip()
        if loc:
            out.append(loc)
    for d in ctx.dependencies or []:
        for key in ("label", "status_reason"):
            val = str(d.get(key) or "")
            out.extend(re.findall(r"[\w./\\-]+\.[A-Za-z0-9]{1,6}", val))
    return out


def _looks_like_path(text: str) -> bool:
    """这段文字像不像一个路径引用（而不是一句人话或一个 claim 代号）。

    名字说的是"像路径"，不是"在工作区内"：判定内外是 G1 自己的事
    （见 :func:`_resolve_against_root`）。把两件事混在一个谓词里，
    正是 G-6 那个缺陷的形状 —— 候选筛选通过了，内外判定却把盘符切掉了。

    ## `D-7` 第 (1) 步：先切尾部 `:行号`，再判形态

    本函数此前直接拿原串判形态，于是框架自己规定的证明位置形态恰好
    落在候选之外：`claimanatomy.py` 把 `proof_location` 的形态定成
    "`file:line` 或 `claim_id`"，而 `"PROOF-DOES-NOT-EXIST.lean:1"` 的尾部是
    `:1` 而不是 `.lean` ⇒ 形态正则（要求 `.ext` 结尾）不命中，串上也没有
    `[/\\]` ⇒ 这个候选被静默丢掉。后果是 G1 数出"检查的路径数 = 0"、
    报 `pass` —— 一道"一条都没看见"的门用零发现伪装成通过（`D-7` 的实测）。

    切法复用 :func:`_strip_line_suffix`（同一处切法；本仓库已经有过
    "两处 `file:line` 切法不一致"的教训，不许再出现第三套）。
    切完再判形态，于是 `code/p1.py:12` 与 `PROOF-…​.lean:1` 走同一条路，
    而 `claim-1:3`（claim_id + 行号，G3 允许的自指形态）切完是 `claim-1`
    ⇒ 被下面那条 `claim` 形态排除，仍然不会被当成路径。
    """
    t = _strip_line_suffix(text.strip())
    if not t or " " in t and "." not in t:
        return False
    if re.match(r"^claim[-_\w]*$", t):
        return False
    return bool(re.search(r"[/\\]", t)) or bool(re.search(r"\.[A-Za-z0-9]{1,6}$", t))


#: 平台无关的绝对路径判据：`<盘符>:<分隔符>` 或 `/` / `\` 开头。
#:
#: 为什么不能依赖 `pathlib.Path.is_absolute()` —— 它是平台相关的，
#: 而本门要判的是一个字符串，不是本机的某个路径：
#:
#: * 在 Linux 上 `PurePosixPath("C:/x/y.py").is_absolute()` 为 False
#:   （`C:/x/y.py` 在那里只是一个合法的相对文件名）⇒ 依赖它就会把 Windows
#:   盘符绝对路径当成"工作区内的相对路径"，缺陷原样复现；
#: * 在 Windows 上 `PureWindowsPath("/abs/path.py").is_absolute()` 为 False
#:   （POSIX 根路径在 Windows 上算"当前盘符下的相对路径"）⇒ 依赖它就会漏掉
#:   `/etc/passwd` 这一档。
#:
#: 两条都是"在一台机器上判另一台机器的路径"，而 CI 与开发机不同平台，
#: 所以判据必须由字符串形态决定，与跑在哪个 OS 上无关。
_ABS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")

#: `file:line` 的尾部行号（只在最后一个 `:` 后面真的是数字时才切）。
_LINE_SUFFIX_RE = re.compile(r":(\d+)$")

#: 通配符形态（`*` / `?` / `[`）。带它的候选不判存在性：
#: `Path("*").exists()` 恒为 `False`，拿它去判会把一条合法的通配引用
#: 误判成"材料不存在"（假阳性）。通配符的解析归 G2 —— 它的判据逐字写着
#: "每个『材料/路径』引用可解析（含通配符）"，本门不抢那件事，
#: 只把它数出来（`counts["未展开的通配符"]`），不许静默放行。
_GLOB_TEXT_RE = re.compile(r"[*?\[]")


def _strip_line_suffix(raw: str) -> str:
    """把 `proof_location` 形态的 `file:line` 里的行号切掉，只切尾部且必须是数字。

    为什么不能写 `raw.split(":")[0]`（G-6 的原实现）：那会在第一个 `:` 处切，
    而 `C:/outside/p1.py:12` 的第一个 `:` 是盘符分隔符 ⇒ 得到 `"C"` ⇒
    `root / "C"` 落在工作区内 ⇒ 一条指向 `C:\\…` 的证明位置引用会通过自含性检查。

    本函数只切尾部 `:<数字>`，于是 `C:/x/y.py:12` 与 `C:/x/y.py` 都得到路径本体，
    而 `C:/x/y.py:abc`（冒号后不是数字）原样返回、交给内外判定去拒。
    """
    text = raw.strip()
    m = _LINE_SUFFIX_RE.search(text)
    match = m.group(1) if m else ""
    return text[: -len(match) - 1].strip() if m else text


def _is_absolute_path_text(text: str) -> bool:
    """按字符串形态判绝对路径（平台无关，理由见 :data:`_ABS_PATH_RE`）。"""
    return bool(_ABS_PATH_RE.match(text.strip()))


def _resolve_against_root(raw: str, root: Path) -> tuple[Path | None, str]:
    """把一个引用字符串解析成 `(绝对路径, 判定失败原因)` —— 内外判定的唯一入口。

    解析规则（三档，刻意分开写而不是"一把梭"）：

    * `C:/x/y.py:12` / `C:\\x\\y.py` / `/abs.py:3` —— 先切尾部 `:行号`，再当绝对路径；
    * `sub/dir/f.py:12` / `./a.py` / `../out/f.py` —— 切尾部 `:行号` 后相对 `root` 解析；
    * `C:foo`（盘符相对，不是绝对）—— 按相对 `root` 解析 ⇒ 由调用方判内外。

    `reason` 只在与平台的路径模型真的无法互操作时非空（例如拿一个 Windows 盘符
    路径去 `relative_to` 一个 POSIX 工作区）：那既不是"在内"也不是"在外"，
    必须如实报出来，不许折叠成两者之一。

    `Path.resolve()` 不要求路径存在（不带 `strict`），它做的是规范化
    （消掉 `..`），所以"存在与否"与"内外"是两件事，本函数只回答后者。
    """
    text = raw.strip()
    if not text:
        return None, "空字符串（不是一条可判定的路径）"
    path_text = _strip_line_suffix(text)
    if not path_text:
        return None, "冒号前没有路径本体（形如 `:12`）"
    candidate = Path(path_text)
    if not _is_absolute_path_text(path_text):
        candidate = root / path_text
    try:
        return candidate.resolve(), ""
    except (OSError, ValueError) as exc:
        # Windows 的 `relative_to` 对"盘符不同"抛 ValueError；跨平台混用（POSIX 根 +
        # Windows 盘符）抛 OSError。两者的共同含义是"没法比"，不是"在里面"。
        return None, f"{type(exc).__name__}: {exc}"


# ---- G1 自含性门 ----------------------------------------------------------


def gate_g1(ctx: GateContext) -> GateResult:
    """G1 自含性门（照搬 `selfcontain_check.py`）：正文不得引用工作区外的路径。

    判据文本的唯一来源是 `GATES["G1"]["criterion"]`（声明表），
    本函数只从那里取 —— 不再在函数体里写第二份字面量（FC-03）。

    失败处置：阻断交付。

    适配说明：文件引用的两个来源是 `claims[*].proof_location`（`file:line`）
    与 `dependencies[*]` 的自由文本标签。我们没有"包"这个概念，
    这里把"包内"读成"工作区内"。

    ## `D-7`：criterion 的第二句以前没有实现

    这道门的 `criterion` 逐字是两句："正文不得引用工作区外的路径；
    每个被引材料必须在工作区内存在"。第二句在 2026-09-27 之前的实现里
    一个字都没有（AST 实测：`gate_g1` 的函数体里没有任何一处
    对解析出来的目标调用 `Path.exists` —— 旧实现只做了一次 `relative_to`
    判内外），于是"指向一个盘上不存在的材料"与"指向一个真实文件"
    在 `counts` / `verdict` 上完全同形。

    这三步（`D-7` 的修法）是配套的，缺一步这条门就还是空的：

    1. 候选筛选先切尾部 `:行号` 再判形态（见 :func:`_looks_like_path`）
       —— 不切的话 `PROOF-….lean:1` 这种框架自己规定的形态根本进不了候选；
    2. 本函数里补存在性判据：工作区内、不含通配符的候选逐个判"盘上在不在"，
       不在 ⇒ `error` 发现（阻断交付）；连这个都抛异常 ⇒ `unknown`
       （"没查成"不许折成"通过"）；
    3. `criterion` 文本与实现对齐 —— 这一条选的是"实现第二句"而不是
       "改掉文本"，因为参考体例（`selfcontain_check.py`）的判据本来就是两句，
       删掉第二句等于把这道门的范围改窄（那是口径变更，不是修缺陷）。

    ## 自述读数纪律（`R2b-gates-1`）

    这道门的 `counts` 与 `reason` 是它自己的读数，两者必须逐档对齐：`reason`
    只在某一档计数非零时提它，并且带上那个数。反过来的两个坑各登记一条：

    - `pass` 那一支不许在存在性没判全时说"都存在" —— 未展开的通配符的存废
      本条不判（`Path.exists()` 对通配符恒为假），所以只要 `globbed > 0`，
      `reason` 就必须说明有几条没判过存在性，以及真正判过的那几条的结论；
    - "存在性没查成"（`exists()` 抛异常）在任何一支里都不许消失：单独出现时
      它把 verdict 降为 `unknown`；与真发现同时出现时 verdict 是 `fail`
      （更严的那一档优先），但 `reason` 必须显式写出这一档的条数 ——
      否则这条旁路会被发现分支永久吃掉；
    - 这一条是三支共同的：任一档非零就必须在 `reason` 里出现并带自己的数，
      包括 `unknown` 支里的 `globbed`（`R2b7-gates-1`：那里原来只报
      "存在性没查成"一档，而 `counts` 里通配符那档是非零的）。
      `globbed == 0` 时那半句不出现，所以它是"非零才出现"，不是恒加一句。

    绝对路径必须按字符串形态识别，不能靠 `Path.is_absolute()`：
    这个判据要判的是"这段文字写的是一个绝对路径吗"，而 `Path.is_absolute()`
    是平台相关的 —— Linux 上 `C:/x/y.py` 不是绝对路径、Windows 上
    `/abs/path.py` 不是绝对路径（逐条论证见 :data:`_ABS_PATH_RE`）。
    盘符绝对路径尤其危险：`C:/outside/p1.py:12` 的第一个 `:` 是盘符分隔符，
    任何"在第一个 `:` 处切 `file:line`"的写法都会把它切成 `"C"`，
    于是 `root / "C"` 落在工作区内、门报 `pass`（G-6）。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G1", "工程"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    root = ctx.workspace()
    if root is None:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason="没有给出 `workspace_root` ⇒ **无法判断一个路径是否在工作区内**（没查，不是『都在包内』）",
            evidence_used=("workspace_root",),
            criterion_revision=criterion_revision,
        )
    candidates = [p for p in _iter_doc_files(ctx) if _looks_like_path(p)]
    findings: list[dict] = []
    inside = outside = unresolvable = missing = globbed = existence_undecidable = 0
    root_resolved = root.resolve()
    for raw in candidates:
        target, why = _resolve_against_root(raw, root)
        if target is None:
            # 连"在里面还是外面"都判不了 ⇒ 不许算进任何一边（三种结论必须分开）。
            unresolvable += 1
            findings.append(
                {
                    "gate": gate_id,
                    "axis": axis,
                    "severity": "error",
                    "target": raw,
                    "message": "这条路径引用的**内外无法判定** ⇒ 按不自含处理（阻断交付）",
                    "evidence": f"路径 {raw!r} 相对工作区 {root} 无法解析：{why}",
                }
            )
            continue
        try:
            target.relative_to(root_resolved)
            inside += 1
        except ValueError:
            outside += 1
            findings.append(
                {
                    "gate": gate_id,
                    "axis": axis,
                    "severity": "error",
                    "target": raw,
                    "message": "引用了工作区**外**的路径 —— 交付物不自含",
                    "evidence": f"路径 {raw!r} 解析为 {target}，不在工作区 {root} 内",
                }
            )
            continue
        # ---- `D-7` 第 (2) 步：criterion 的第二句此前在实现里不存在。
        #
        # 旧实现只判"在不在工作区内"（一次 `relative_to`），于是
        # "指向一个盘上不存在的材料"与"指向一个真实文件"在 `counts` 与 `verdict`
        # 上完全同形（都是 `工作区内=1`、都是 `pass`）—— 而这道门的 criterion
        # 逐字写着两句，第二句是"每个被引材料必须在工作区内存在"。一条指向
        # `PROOF-DOES-NOT-EXIST.lean:1` 的证明引用因此拿到
        # `reason='0 条路径全部在工作区内'` 的"通过"（`D-7` 的原始读数）。
        #
        # 判据强度刻意停在 criterion 的字面口径（存在），不擅自升级成
        # `is_file()`：写入期 `doc_tools.check_proofs` 用的是 `is_file()`，
        # 那是另一条判据（`D-1`），混起来会造出第二份口径。
        if _GLOB_TEXT_RE.search(raw):
            globbed += 1
            continue
        try:
            exists = target.exists()
        except OSError:
            # 连"存在与否"都问不出来 ⇒ 三态里的第三档，不许折进 pass 或 fail。
            existence_undecidable += 1
            continue
        if not exists:
            missing += 1
            findings.append(
                {
                    "gate": gate_id,
                    "axis": axis,
                    "severity": "error",
                    "target": raw,
                    "message": "被引材料在**工作区内不存在** ⇒ 交付物不自含（criterion 第二句）",
                    "evidence": (
                        f"路径 {raw!r} 解析为 {target}，在工作区 {root} 内但盘上没有这个路径"
                    ),
                }
            )
    counts = {
        "检查的路径数": len(candidates),
        "工作区内": inside,
        "工作区内不存在": missing,
        "工作区外": outside,
        "内外无法判定": unresolvable,
        "未展开的通配符": globbed,
        "存在性无法判定": existence_undecidable,
    }
    proc = (
        f"从 claims[*].proof_location 与 dependencies[*] 的自由文本里抽出"
        f"{len(candidates)} 个像路径的字符串，逐个切掉尾部 `:行号`（只切数字）、"
        f"按盘符/POSIX 根判绝对路径、resolve() 后 relative_to(workspace_root)"
        f"（工作区 {root}）；再对工作区内、不含通配符的候选逐个判存在性"
        f"（`D-7` 补上的 criterion 第二句），存在性问不出来的记 `unknown`"
    )
    # `reason` 的每一句都必须对应一个真的数出来的分类（`R2b-gates-1`）。
    #
    # 旧写法在 `findings` 非空时无条件写"有 {outside} 条引用指向工作区外的路径"：
    # 一条"工作区内不存在"的发现因此被自述成一条区外引用（`outside` 记的是另一个
    # 集合，那时它是 0），而"未展开的通配符"与"存在性无法判定"这两条旁路在
    # `reason` 里一个字都不出现 —— 门自述的读数与它实际判过的东西不一致。
    # 现在每一档只在它非零时出现，且各自带自己的数；反过来，`pass` 那一支
    # 不许在存在性没判全的时候说"都存在"（通配符的存废本条不判）。
    # 这条纪律对下面四支一律成立（`R2b7-gates-1` 就是 `unknown` 支漏了 `globbed`）。
    if findings:
        verdict = "fail"
        parts: list[str] = []
        if outside:
            parts.append(f"有 {outside} 条引用指向工作区外的路径")
        if missing:
            parts.append(f"{missing} 条指向工作区内**不存在**的材料")
        if unresolvable:
            parts.append(f"{unresolvable} 条内外无法判定")
        if existence_undecidable:
            parts.append(
                f"另有 {existence_undecidable} 条的存在性没查成（`exists()` 抛异常）"
                "⇒ 这一档**没查成**，不许被上面的发现盖掉"
            )
        if globbed:
            parts.append(f"另有 {globbed} 条是未展开的通配符（本条不判它们的存废）")
        # 背景提名（`X-91.5-5 ②`）：上面每一句都是"有问题的那几档"，
        # 于是 fail 支的读者看不到"其实还有若干条在工作区内"这个上下文 ——
        # 一条 `工作区内不存在` 的发现会被读成"整篇都在引用区外材料"。
        # `FINAL-R5-04`：这一句改前用的是 `inside`，而 `missing ⊆ inside`
        # （"不存在"的路径当然也算在工作区内）⇒ 唯一一条候选就是缺材料时，
        # 这一句会说"有 1 条在区内"，把同一批材料数了两遍。现在只数
        # 判过存在性且真的在盘上的那些（= `inside - missing`，通配符另计）。
        # 放在末句（不是首句）：反过来的两个口径坑都要避开 ——
        # ① `pass` 支的"N 条路径都在工作区内"是结论，fail 支这句只是背景，
        #    换一个说法才不会让读者以为这一支也在说"都在"；
        # ② 与 `missing` 那句"…条指向工作区内不存在…的材料"不共用字面
        #    （同族：`R2b7-gates-1` 的"同一个计数键在两支里换一个说法"）。
        present = max(0, inside - missing - globbed)
        parts.append(f"背景：其余 {present} 条在工作区内且都在盘上")
        reason = "，".join(parts) + " ⇒ **阻断交付**"
    elif existence_undecidable:
        verdict = "unknown"
        # 这一支同样逐档自述：`existence_undecidable` 与 `globbed` 可以同时非零，
        # 而"没查成"这一档的存在不代表通配符那一档可以被省掉（`R2b7-gates-1`：
        # 形态是报告不实，不是假通过 —— 这一支的 verdict 反而比 pass 更严）。
        # 档名用与 fail 支同一处字面（"存在性没查成"），并保留旧读法
        # （"存在性问不出来"）：同一个计数键在两支里换一个说法，就是让读者
        # 拿两句不同的话去对同一个数。
        parts = [
            f"{inside} 条路径都在工作区内，但有 {existence_undecidable} 条的**存在性没查成**"
            f"（`exists()` 抛异常 ⇒ 存在性问不出来）"
        ]
        if globbed:
            parts.append(f"另有 {globbed} 条是未展开的通配符（本条不判它们的存废）")
        reason = "，".join(parts) + " ⇒ 记 `unknown`，**不记 pass**（没查成 ≠ 通过）"
    elif globbed:
        # 通配符不是一条"材料"：`Path.exists()` 对它恒为假，所以它的存废本条不判
        # （那是 G6 那一类"通配符匹配不到东西"的判据的地盘）。这一支仍然是
        # `pass`，但自述读数必须把"有几条没判过存在性"如实写出来。
        verdict = "pass"
        reason = (
            f"{inside} 条路径都在工作区内；其中 {globbed} 条是未展开的通配符，"
            f"本条不判它们的存废（`Path.exists()` 对通配符恒为假）；"
            f"真正判过存在性的 {inside - globbed} 条都在盘上"
        )
    else:
        verdict = "pass"
        reason = f"{inside} 条路径全部在工作区内且都存在"
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict=verdict,
        reason=reason,
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims", "dependencies", "workspace_root"))),
        counts=counts,
        evidence_used=("documents.claims[*].proof_location", "dependencies[*]", "workspace_root"),
        criterion_revision=criterion_revision,
    )


# ---- G2 引用解析门 / G3 交叉引用门 ----------------------------------------


def _check_citation_resolution(
    ctx: GateContext, *, kinds: Sequence[str], strict_missing: bool
) -> tuple[list[dict], dict[str, Any], str]:
    """G2/G3 共用的引用解析实现（§8.4 明确允许合并，但门号必须齐全）。

    `citations` 的元素形如 `rel:0007` / `lit:0003#p.4` / `exp:0002` / `stmt:0004`。
    `kind` 决定了它属于"文献引用"（G2）还是"内部/上游交叉引用"（G3）。
    认得的 `kind` 由调用方给（G2 给的是 `schema.CITATION_PREFIXES` 的键 —— 唯一声明面）。

    这里不做存在性核对 —— 那是 `doc_tools.check_citations` 的活
    （它需要读表）。本函数做的是语法级解析：前缀可识别吗？代号非空吗？
    两件事分开的理由：解析不需要 store，解析失败与存在性失败是两种缺陷。
    """
    findings: list[dict] = []
    total = 0
    resolved = 0
    unknown_kind = 0
    for c in ctx.claims():
        cid = str(c.get("claim_id") or "?")
        for raw in c.get("citations") or []:
            total += 1
            kind, _, ref = str(raw).partition(":")
            ref = ref.split("#")[0]
            if not kind or not ref.strip():
                findings.append(
                    {
                        "axis": "证据",
                        "severity": "error",
                        "target": cid,
                        "message": "引用无法解析（空前缀或空代号）",
                        "evidence": f"claim_id={cid} citation={raw!r}",
                    }
                )
                continue
            if kind not in kinds:
                unknown_kind += 1
                if strict_missing:
                    # 裸文件名（无前缀）在参考体例里也必须能在包内解析 ⇒ fail；
                    # 我们这里只能报 warning：没有 store 就核不了它是不是文件名。
                    findings.append(
                        {
                            "axis": "证据",
                            "severity": "warning",
                            "target": cid,
                            "message": f"引用前缀 {kind!r} 不在本项目可解析的种类里",
                            "evidence": f"claim_id={cid} citation={raw!r}；可解析前缀={list(kinds)}",
                        }
                    )
                continue
            resolved += 1
    counts = {
        "扫描的引用数": total,
        "前缀可解析": resolved,
        "前缀不可解析": unknown_kind,
        "解析失败": len([f for f in findings if f["severity"] == "error"]),
    }
    proc = f"逐条 partition(':') 解析 claims[*].citations（共 {total} 条），核对前缀是否在 {list(kinds)} 内"
    return findings, counts, proc


def gate_g2(ctx: GateContext) -> GateResult:
    """G2 引用解析门（照搬 `r75_verify_vol.py:39-64`）：每个引用可解析。

    判据（§8.4）："每个 `材料/路径` 引用可解析（含通配符）；裸文件名也能在包内解析。"
    失败处置：阻断交付（且必须返回非零退出码 —— 照 `:74`）。

    适配说明：我们的引用是 `lit:`/`rel:`/`exp:`/`eval:` 前缀式；
    "裸文件名"这一档在本项目不存在（写裸文件名进 citations 是写入期就拒的），
    所以这里只报 warning 并逐条留痕（§8.4 的"假阳性须逐条留痕"）。

    可解析前缀的唯一声明面是 `schema.CITATION_PREFIXES`（2026-10-07 所有者裁定
    `draft/68` 题 1 选 A，本次改动由所有者授权、主控代改）。改前本门内联了四个前缀
    `("lit","rel","exp","eval")`，于是它与写入期（`doc_tools._CITATION_TABLES`）
    对同一个字符串给出两个结论：`stmt:0004` 在写入期是合法引用、在本门是
    "不在可解析的种类里"。现在两边都从声明面派生 ⇒ 不可能再分家。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G2", "证据"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    findings, counts, proc = _check_citation_resolution(
        ctx, kinds=tuple(S.CITATION_PREFIXES), strict_missing=True
    )
    for f in findings:
        f["gate"] = gate_id
    errors = [f for f in findings if f["severity"] == "error"]
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if errors else "pass",
        reason=(
            f"{len(errors)} 条引用无法解析 ⇒ 阻断交付" if errors else f"{counts['前缀可解析']} 条引用全部可解析"
        ),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims[*].citations",))),
        counts=counts,
        evidence_used=("documents.claims[*].citations",),
        criterion_revision=criterion_revision,
    )


def gate_g3(ctx: GateContext) -> GateResult:
    """G3 交叉引用门（照抄 `strict_xref_check.py` + `series_xref_deep.py`）。

    判据（§8.4）："每个『外部/上游引用』的目标标签真实存在；窗口取最近锚点、
    不跨句号、允许自指。" 失败处置：阻断；假阳性须逐条留痕。

    适配说明（这道门的判据被适配过，必须显式登记）：
    "窗口取最近锚点、不跨句号"是散文文本里的引用消解规则；
    我们的稿件的引用是结构化字段（`citations` / `proof_location`），
    不存在"锚点窗口"这个对象。所以这里判的是结构可解性：
    每条 `proof_location` 要么是本文档的 `claim_id`（裸写或带行号，即"允许自指"），
    要么是一个可解析的 `file:line` 形态。

    注意：分类只有一份实现（`R2R2-R1`）：形态判定调
    `tools.doc_tools.classify_proof_location`，与写入期的 `check_proofs` 同一个函数。
    经实测，两处曾经各写一套正则，同一份数据 18 档里有 9 档给出不同分类
    （最难看的一档：断言自己没有 `claim_id` 时 `claim-1:3` 被本门当成 `file:line` 而 pass）。
    现在：
    - `self_ref` ⇒ pass（自指）；
    - `cross_ref` ⇒ error（形态是交叉引用但那个 id 不在本文档里。事后门分不清
      "忘了登记"与"根本不存在"，所以 fail-closed）；
    - `file` ⇒ pass（只判形态可解析、不读盘；存在性由写入期与 `verify` 侧负责）。
      注意：这一层比 `check_proofs` 弱，是刻意的：本门是事后门，历史行没有写入期判据兜。

    第三行那句"要么是本文档的 `claim_id`，要么是可解析的 `file:line`"因此是准确的；
    不要把它读成"本门会去查文件在不在"。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G3", "体例"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    claims = ctx.claims()
    known_ids = {str(c.get("claim_id")) for c in claims if c.get("claim_id")}
    findings: list[dict] = []
    declared = 0
    by_id = 0
    by_name = 0
    by_loc = 0
    for c in claims:
        cid = str(c.get("claim_id") or "?")
        loc = str(c.get("proof_location") or "").strip()
        if not loc:
            continue
        declared += 1
        # `R2R2-R2`：分类与实际一致，且三格分开计 —— 旧版把 `claim-1:12`
        # （乃至断言自己没有 claim_id 时的 `claim-1:3`）算进 `指向 file:line`，
        # 那是门在自述读数上撒谎（计数说有一堆 `file:line`，其实一条都没有）。
        kind, base = doc_tools.classify_proof_location(loc, known_ids)
        if kind == "self_ref":
            by_id += 1
            if base == loc:
                by_name += 1
            continue
        if kind == "file":
            by_loc += 1
            continue
        findings.append(
            {
                "gate": gate_id,
                "axis": axis,
                "severity": "error",
                "target": cid,
                "message": (
                    "`proof_location` 既不是本文档内真实存在的 `claim_id`，"
                    "也不是可解析的 `file:line` 形态"
                ),
                "evidence": (
                    f"claim_id={cid} proof_location={loc!r}；"
                    f"本文档已知 claim_id 数={len(known_ids)}；"
                    f"分类为 `cross_ref`（去掉行号后是 {base!r}，不在已知集合里）"
                ),
            }
        )
    counts = {
        "声明了 proof_location 的断言": declared,
        "指向本文档内 claim_id": by_id,
        "其中裸写 claim_id": by_name,
        "指向 file:line 形态": by_loc,
        "两者都不是": len(findings),
    }
    proc = (
        f"从 {len(claims)} 条断言里取出 {declared} 个 proof_location，"
        f"逐个与本文档的 {len(known_ids)} 个 claim_id 比对形态"
        "（分类函数与写入期 `doc_tools.classify_proof_location` 同一份）"
    )
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if findings else "pass",
        reason=(
            f"{len(findings)} 条交叉引用无法解析 ⇒ 阻断" if findings else f"{declared} 条交叉引用全部可解析"
        ),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims[*].proof_location",))),
        counts=counts,
        evidence_used=("documents.claims[*].proof_location", "documents.claims[*].claim_id"),
        criterion_revision=criterion_revision,
    )


# ---- G4 账本对账门 --------------------------------------------------------


def gate_g4(ctx: GateContext) -> GateResult:
    """G4 账本对账门（照搬 `readme_integrity.py:55-88`）。

    判据（§8.4）："索引/README 点名的文件存在、卷内文件全被列出、
    声明的字数在容差内、声明的标签在正文存在。" 失败处置：阻断。

    适配说明：我们的对应物是 `documents` 行与它渲染出的 markdown 文件之间的对账
    —— `markdown_path` 点名的文件必须存在，且稿件里声明的断言数必须与
    实际断言数一致（参考体例 §1.4 的十处计数漂移正是"没有任何脚本在查"）。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G4", "体例"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    doc = ctx.doc
    findings: list[dict] = []
    rel = str(doc.get("markdown_path") or "")
    file_exists: Any = "未提供工作区（没查）"
    if rel:
        root = ctx.workspace()
        if root is None:
            file_exists = "未提供工作区（没查）"
        else:
            file_exists = (root / rel).exists()
            if not file_exists:
                findings.append(
                    {
                        "gate": gate_id,
                        "axis": axis,
                        "severity": "error",
                        "target": str(doc.get("doc_id") or "?"),
                        "message": "`markdown_path` 点名的文件在盘上不存在 —— 账本与实物不符",
                        "evidence": f"doc_id={doc.get('doc_id')} markdown_path={rel!r} 在 {root} 下不存在",
                    }
                )
    actual = len(ctx.doc.get("claims") or [])
    declared = None
    if isinstance(ctx.claim_counts, Mapping):
        declared = ctx.claim_counts.get("declared_claim_count")
    if declared is not None and int(declared) != actual:
        findings.append(
            {
                "gate": gate_id,
                "axis": axis,
                "severity": "error",
                "target": str(doc.get("doc_id") or "?"),
                "message": "声明的断言数与实际断言数不一致（计数漂移）",
                "evidence": f"声明 declared_claim_count={declared}，实际 len(claims)={actual}",
            }
        )
    counts = {
        "markdown_path 存在": file_exists,
        "实际断言数": actual,
        "声明的断言数": declared if declared is not None else "未声明",
    }
    proc = f"核对 documents 行（doc_id={doc.get('doc_id')}）的 markdown_path={rel!r} 与 claims 计数"
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if findings else "pass",
        reason=(
            f"{len(findings)} 处账实不符 ⇒ 阻断" if findings else "账本（文档行）与实物（markdown 文件、claims）一致"
        ),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.markdown_path", "documents.claims"))),
        counts=counts,
        evidence_used=("documents.markdown_path", "documents.claims", "workspace_root"),
        criterion_revision=criterion_revision,
    )


# ---- G5 禁词/手糊门 -------------------------------------------------------


def gate_g5(ctx: GateContext) -> GateResult:
    """G5 禁词/手糊门（照搬 `series_banned_words.py:16-20` + `STYLE/RUBRIC.md:50-53`）。

    判据（§8.4）："中文 15 词表 + 英文 12 连词表；命中带上下文供人工裁。"
    失败处置：命中须逐条裁并记录（允许"元叙述"例外，`:22`）。

    词表刻意不写在这里（写死第二份词表就是 FC-03 的形态）：
    调用方通过 `banned_words` 显式传入；不传 ⇒ 本门判 `not_applicable`
    并如实说明"没有给出词表，所以这道门在本轮没有可判定的对象"。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G5", "体例"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    words = [str(w) for w in (ctx.banned_words or []) if str(w).strip()]
    if not words:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="not_applicable",
            reason=(
                "调用方没有提供 `banned_words` ⇒ 这道门在本轮**没有可判定的对象**。"
                "本项目**故意不在代码里写死一份词表**（写死第二份词表就是 FC-03 的形态）："
                "参考体例的词表来自 `STYLE/RUBRIC.md:50-53`，属于**人的文风决定**，"
                "应当由配置注入而不是由 AI 固化。门保留、如实报『没有对象』，而不是删门"
            ),
            counts={"提供的禁词数": 0, "扫描的断言数": len(ctx.claims())},
            self_attestation=_attest_text(
                attest(
                    f"检查 ctx.banned_words 是否为空（{len(ctx.claims())} 条断言在场）",
                    {"提供的禁词数": 0, "扫描的断言数": len(ctx.claims())},
                    evidence_used=("ctx.banned_words",),
                )
            ),
            evidence_used=("ctx.banned_words",),
            criterion_revision=criterion_revision,
        )
    findings: list[dict] = []
    scanned = 0
    for c in ctx.claims():
        scanned += 1
        cid = str(c.get("claim_id") or "?")
        text = CA.claim_statement(c)
        for w in words:
            if w and w in text:
                idx = text.index(w)
                findings.append(
                    {
                        "gate": gate_id,
                        "axis": axis,
                        "severity": "warning",
                        "target": cid,
                        "message": f"命中禁词 {w!r}（须逐条人工裁：允许『元叙述』例外）",
                        "evidence": f"claim_id={cid} 上下文={text[max(0, idx - 30): idx + len(w) + 30]!r}",
                    }
                )
    counts = {"扫描的断言数": scanned, "禁词数": len(words), "命中数": len(findings)}
    proc = f"在 {scanned} 条断言的正文里逐词查找 {len(words)} 个禁词（子串匹配），命中处截取 ±30 字上下文"
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if findings else "pass",
        reason=(f"命中 {len(findings)} 处，须逐条人工裁并留痕" if findings else "未命中任何禁词"),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("ctx.banned_words", "documents.claims[*].statement"))),
        counts=counts,
        evidence_used=("ctx.banned_words", "documents.claims[*].statement"),
        criterion_revision=criterion_revision,
    )


# ---- G6 虚证门 ------------------------------------------------------------


def gate_g6(ctx: GateContext) -> GateResult:
    """G6 虚证门（照搬 `check_yan_anchors.py:38-46` + `check_yan_scripts_local.py:38-50`）。

    判据（§8.4）："每个数值/经验断言点名的脚本与数据文件必须存在且在包内。"
    失败处置：阻断。

    适配说明：数值证据在我们这里是 `claims[*].numeric_evidence.script`（§8.3 的四元组）。
    "在包内"读成"在工作区内"。脚本路径允许通配符（参考体例支持 `*`），
    通配符按 `glob` 展开后必须至少命中一个真实文件 ——
    "通配符没命中"是最容易伪装成"存在"的形态。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G6", "证据"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    root = ctx.workspace()
    if root is None:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason="没有给出 `workspace_root` ⇒ **核不了脚本是否存在**（没查，不是『脚本都在』）",
            counts={"点名的脚本数": 0},
            evidence_used=("workspace_root",),
            criterion_revision=criterion_revision,
        )
    findings: list[dict] = []
    named = 0
    found = 0
    for c in ctx.claims():
        cid = str(c.get("claim_id") or "?")
        ne = c.get("numeric_evidence")
        if not isinstance(ne, Mapping):
            continue
        script = str(ne.get("script") or "").strip()
        if not script:
            continue
        named += 1
        try:
            if any(ch in script for ch in "*?["):
                hits = sorted(root.glob(script))
            else:
                hits = [root / script] if (root / script).is_file() else []
        except (OSError, ValueError, NotImplementedError) as e:
            # 为什么可以忽略：glob 对畸形模式会抛；处置不是"当作存在"而是报 error。
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "error", "target": cid,
                    "message": "numeric_evidence.script 的路径模式无法展开",
                    "evidence": f"claim_id={cid} script={script!r} 展开失败：{type(e).__name__}: {e}",
                }
            )
            continue
        if hits:
            found += 1
        else:
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "error", "target": cid,
                    "message": "数值证据点名的脚本/数据文件**不存在**（虚证）⇒ 阻断",
                    "evidence": f"claim_id={cid} script={script!r} 在 {root} 下没有任何命中",
                }
            )
    counts = {"点名的脚本数": named, "命中真实文件": found, "虚证数": len(findings)}
    proc = f"遍历 claims[*].numeric_evidence.script（{named} 个非空值），在工作区 {root} 下 glob/isfile 核对"
    if not named:
        # 一条数值证据都没点名：这不是"通过"，而是"没有任何可判定的对象"。
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="not_applicable",
            reason=(
                f"本稿 {len(ctx.claims())} 条断言**没有任何一条点名数值脚本**"
                "（`numeric_evidence.script` 全空）⇒ 虚证门本轮没有可判定的对象。"
                "注意这与『脚本都存在』是两件事 —— 所以判 not_applicable 而不是 pass"
            ),
            counts=counts,
            self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims[*].numeric_evidence",))),
            evidence_used=("documents.claims[*].numeric_evidence.script", "workspace_root"),
            criterion_revision=criterion_revision,
        )
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if findings else "pass",
        reason=(f"{len(findings)} 条数值证据的脚本不存在 ⇒ 阻断" if findings else f"{found} 个点名脚本全部存在"),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims[*].numeric_evidence",))),
        counts=counts,
        evidence_used=("documents.claims[*].numeric_evidence.script", "workspace_root"),
        criterion_revision=criterion_revision,
    )


# ---- G7 台账完整门 --------------------------------------------------------


def gate_g7(ctx: GateContext) -> GateResult:
    """G7 台账完整门（照搬 `build_yan_ledger.py:46-58`）。

    判据（§8.4）："每个 `[验]`/数值断言都在台账里有一行，且带『位置 + 逐字断言 +
    类别』。" 失败处置：阻断；禁止"仅泛证"（把路径直接写进正文，`:15`）。

    适配说明：我们的"台账行"就是 `documents.claims[*]` 本身 ——
    所以这道门在我们这里等价于"每条数值型断言都必须是结构化的一行"：
    正文里出现"验/数值/枚举/穷举"这类字样却没有 `numeric_evidence` 的行，
    就是"仅泛证型"（参考体例 §8.5 明确：我们体量小，应直接取消该档）。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G7", "证据"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    markers = ("[验]", "数值", "枚举", "穷举", "反例", "n_cases")
    findings: list[dict] = []
    scanned = 0
    with_ledger = 0
    for c in ctx.claims():
        scanned += 1
        cid = str(c.get("claim_id") or "?")
        text = CA.claim_statement(c)
        ne = c.get("numeric_evidence")
        has_ne = isinstance(ne, Mapping) and bool(str(ne.get("script") or "").strip())
        looks_numeric = any(m in text for m in markers) or c.get("status") == "验"
        if has_ne:
            with_ledger += 1
        if looks_numeric and not has_ne:
            findings.append(
                {
                    "gate": gate_id,
                    "axis": axis,
                    "severity": "error",
                    "target": cid,
                    "message": "数值型断言没有台账行（缺 numeric_evidence）—— 属『仅泛证型』，本项目直接取消该档",
                    "evidence": (
                        f"claim_id={cid} status={c.get('status')!r} "
                        f"numeric_evidence={ne!r}；正文摘要={text[:60]!r}"
                    ),
                }
            )
    counts = {"扫描的断言数": scanned, "有台账行": with_ledger, "缺台账行": len(findings)}
    proc = f"遍历 {scanned} 条断言，按正文关键词 {list(markers)} 与 status=='验' 识别数值型断言，核对 numeric_evidence.script 是否非空"
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if findings else "pass",
        reason=(f"{len(findings)} 条数值型断言缺台账行 ⇒ 阻断" if findings else f"{scanned} 条断言全部有台账形态"),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims[*].statement", "documents.claims[*].numeric_evidence"))),
        counts=counts,
        evidence_used=("documents.claims[*].statement", "documents.claims[*].numeric_evidence", "documents.claims[*].status"),
        criterion_revision=criterion_revision,
    )


# ---- G8 可复跑门 ----------------------------------------------------------


#: G8 回执（`run_evidence.commands[*]`）的必备键（业主 2026-10-18 裁定：
#: G8 改由 M 代跑、把回执交给 H 核，H 只判「回执是否合格」）。
#:
#: 为什么是这四个：`claim_id` 让回执与断面对上；`command` 是"精确命令"；
#: `exit_code` 是"跑过没有 + 绿还是红"的唯一机器读数（少了它，红与绿分不开 ——
#: 旧实现根本不读退出码，所以「跑过而且红了」与「跑过而且绿了」在门上同形）；
#: `output_tail` 是"留了输出"（§8.4 那半句"并留输出"）。
G8_RECEIPT_KEYS: tuple[str, ...] = ("claim_id", "command", "exit_code", "output_tail")


def g8_receipt_problems(commands: Sequence[Mapping[str, Any]]) -> list[str]:
    """逐条判「这份回执合不合格」⇒ 返回问题清单（空列表 = 合格）。

    为什么把"合格"做成判据而不是信任调用方：G8 的输入是调用方给的，
    而"调用方给了一份读不懂的回执"在旧实现里有两条静默路径 ——
      - `commands` 不是数组时（真机：`{"checked": true, "commands": "     "}`），
        旧代码 `[dict(x) for x in "     " if isinstance(x, Mapping)]` 得到 `[]`；
      - 逐条缺键时，那些键的缺失没有任何读数。
    两条路径都会让门在"什么都没有"的输入上继续往下判，而 §8.4 要的恰恰是
    "每条数值断言都有精确命令，且本轮实跑过并留输出"。
    """
    problems: list[str] = []
    for i, c in enumerate(commands):
        if not isinstance(c, Mapping):
            problems.append(f"第 {i + 1} 条：不是对象（{type(c).__name__}）")
            continue
        missing: list[str] = []
        for k in G8_RECEIPT_KEYS:
            if k == "exit_code":
                # 退出码必须是整数：它要参与"绿/红"判定，字符串或缺失都不合格。
                if not isinstance(c.get(k), int):
                    missing.append(k)
            elif not str(c.get(k) or "").strip():
                missing.append(k)
        if missing:
            problems.append(f"第 {i + 1} 条：缺 {missing}（回执不合格 ⇒ 分不出『跑过没有』）")
    return problems


def gate_g8(ctx: GateContext) -> GateResult:
    """G8 可复跑门（§8.4 标注为新增，摘自 `RP/00_STANDARD.md:149-150` 门 B）。

    判据（§8.4）："每条数值断言都有精确命令，且本轮实跑过并留输出。"
    失败处置：阻断。

    这道门是"必须能返回『没做』"的最典型例子：
    库里有没有"本轮实跑过的命令输出"这件事，门自己查不出来 ——
    它必须由调用方显式提供（`run_evidence`）。不提供 ⇒ `unknown` + reason，
    绝不是 `pass`。参考体例的教训逐字是"多数脚本不设退出码，
    于是『未报错』被误读为『无问题』"（`draft/17-…md:675-676`）。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；本函数只从那里取，不在函数体里写第二份字面量（FC-03）。
    """
    gate_id, axis = "G8", "证据"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    numeric = [
        c for c in ctx.claims()
        if isinstance(c.get("numeric_evidence"), Mapping)
        and str((c.get("numeric_evidence") or {}).get("script") or "").strip()
    ]
    ev = ctx.run_evidence
    if not isinstance(ev, Mapping):
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                "调用方**没有提供本轮的实跑记录**（`run_evidence` 缺失）⇒ 『本轮实跑过』这件事"
                "**无法判定**。它必须是调用方显式给出的证据：把『没报错』读成『没问题』，"
                "正是参考体例记录的那个坑（draft/17-…md:675-676）"
            ),
            counts={"需要命令的数值断言数": len(numeric), "本轮实跑记录": "未提供"},
            evidence_used=("ctx.run_evidence", "documents.claims[*].numeric_evidence"),
            criterion_revision=criterion_revision,
        )
    if ev.get("checked") is not True:
        # ---- 第三态（业主 2026-10-18：「没跑 ⇒ unknown 并写明为什么没跑，不许静默」）。
        #
        # 缺陷读数（本条的第一条负控）：`projects/mp3` 末节第 4 条与 `projects/t3d` 三·4
        # 都逐字写着「H 只读、拿不到执行工具 ⇒ G8 只能记 unknown」—— 那一档从"读数"退化成
        # "权限的必然结果"，谁都不会再问"这一轮到底跑了没有"。
        # 现在 unknown 也有义务：必须带一行原因，否则连"为什么没跑"都留不下来。
        why = str(ev.get("reason") or "").strip()
        if not why:
            return GateResult(
                gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
                verdict="unknown",
                reason=(
                    f"调用方**显式声明本轮没有实跑**（run_evidence.checked={ev.get('checked')!r}），"
                    "却**没有写为什么没跑** ⇒ 『没查』有读数，『为什么没查』没有。"
                    "按 2026-10-18 的口径，「H 只读、拿不到执行工具」与「忘了跑」必须分得开："
                    "前者要写清『该谁跑』（M 代跑并把回执交给 H），后者要写清『这一轮为什么不算数』。"
                ),
                findings=(
                    {
                        "gate": gate_id, "axis": axis, "severity": "warning",
                        "target": "run_evidence.reason",
                        "message": "G8 判 unknown 却没写「为什么没跑」",
                        "evidence": (
                            "run_evidence 给了 checked≠True，但没有 reason ⇒ "
                            "这一条 unknown 与『本轮只改措辞』、『权限不允许』都分不开"
                        ),
                    },
                ),
                counts={"需要命令的数值断言数": len(numeric), "本轮实跑记录": 0,
                        "没跑的理由": "**未写**"},
                evidence_used=("ctx.run_evidence",),
                criterion_revision=criterion_revision,
            )
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                f"调用方**显式声明本轮没有实跑**（run_evidence.checked={ev.get('checked')!r}）"
                f"⇒ 可复跑性**没查**。原因：{why}"
            ),
            counts={"需要命令的数值断言数": len(numeric), "本轮实跑记录": 0,
                    "没跑的理由": why},
            evidence_used=("ctx.run_evidence",),
            criterion_revision=criterion_revision,
        )
    # ---- 回执的形状：先要求"读得懂"，再判"覆盖了没有"。
    #
    # 真机读数（`projects/mp3` round 2，H 传给 `review.report` 的 run_evidence）：
    #   {"checked": true, "commands": "     "}
    # 旧实现把那个空白字符串当可迭代对象遍历了一遍（每个字符都不是 Mapping），
    # 得到 `commands = []`；而那一轮 `numeric = 0` ⇒ 差集为空 ⇒ G8 = pass，
    # 报告里写着"0 条实跑记录覆盖全部数值断言"。这就是"回执读不懂"被读成"覆盖了"。
    raw = ev.get("commands")
    if not isinstance(raw, (list, tuple)):
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                f"回执**不合格**：`run_evidence.commands` 是 {type(raw).__name__}，不是数组 ⇒ "
                "这份回执读不成逐条记录（『本轮实跑过』无法判定）。合格回执的形状是 "
                "`{'checked': true, 'commands': [{'claim_id','command','exit_code','output_tail'}]}`；"
                "空白字符串、`{}`、单个对象都不算 —— 把『读不懂』当『没问题』正是 G8 要防的形态"
            ),
            counts={"需要命令的数值断言数": len(numeric), "本轮实跑记录": "回执不合格",
                    "回执类型": type(raw).__name__},
            evidence_used=("ctx.run_evidence.commands",),
            criterion_revision=criterion_revision,
        )
    commands = [dict(x) for x in raw if isinstance(x, Mapping)]
    have = {str(c.get("claim_id")) for c in commands}
    findings: list[dict] = []
    for c in numeric:
        cid = str(c.get("claim_id") or "?")
        if cid not in have:
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "error", "target": cid,
                    "message": "数值断言没有本轮实跑过的精确命令 ⇒ 阻断",
                    "evidence": (
                        f"claim_id={cid} script={(c.get('numeric_evidence') or {}).get('script')!r}；"
                        f"本轮实跑记录覆盖的 claim_id={sorted(have)}"
                    ),
                }
            )
    # ---- 回执的资格（业主 2026-10-18）：H 只判"回执合不合格"，而这条判据必须在门上。
    #
    # 三态口径（与 G8 的其余部分一致）：
    #   * 没有实跑记录（`checked=true` 却一条都没有）⇒ `unknown`（不是 vacuous pass）；
    #   * 回执缺键 ⇒ `unknown` + 逐条问题（不许静默跳过缺键的那一条）；
    #   * 回执齐但退出码非零 ⇒ `fail`（"跑过而且红了"）。
    receipt_problems = g8_receipt_problems(commands)
    counts_base = {
        "需要命令的数值断言数": len(numeric),
        "本轮实跑记录": len(commands),
        "缺命令": len(findings),
        "留了输出": len([c for c in commands if str(c.get("output_tail") or "").strip()]),
    }
    if findings:
        # 差集非空 ⇒ 阻断（这一条优先：它是"没跑"的最硬形态）。
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="fail",
            reason=f"{len(findings)} 条数值断言没有本轮实跑命令 ⇒ 阻断",
            findings=tuple(findings),
            self_attestation=_attest_text(
                attest(f"把 claims 里 {len(numeric)} 条带 numeric_evidence.script 的断言与"
                       f"本轮 {len(commands)} 条实跑记录按 claim_id 求差集",
                       counts_base,
                       evidence_used=("ctx.run_evidence", "documents.claims[*].numeric_evidence"))),
            counts=counts_base,
            evidence_used=("ctx.run_evidence.commands", "documents.claims[*].numeric_evidence.script"),
            criterion_revision=criterion_revision,
        )
    if not commands:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                "调用方声明 checked=true，但 `run_evidence.commands` 是**空的** ⇒ "
                "『本轮实跑过』没有一条记录可判。空回执不是通过：没有实跑记录时，"
                "这一档要么由 M 代跑（派 E 用 `verify.run_experiment` 重跑那几条命令，"
                "把 `claim_id` / `command` / `exit_code` / `output_tail` 带回来给 H），"
                "要么按 checked=false 写清为什么没跑"
            ),
            counts={**counts_base, "本轮实跑记录": 0},
            evidence_used=("ctx.run_evidence.commands",),
            criterion_revision=criterion_revision,
        )
    if receipt_problems:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                f"回执**不合格**（{len(receipt_problems)} 处）：" + "；".join(receipt_problems[:4])
                + "。合格回执的每一条都必须带 "
                f"{list(G8_RECEIPT_KEYS)} —— 少了 `exit_code` 就分不出绿与红，"
                "少了 `output_tail` 就是『跑了但没留输出』（§8.4 那半句没兑现）"
            ),
            counts={**counts_base, "回执不合格": len(receipt_problems)},
            evidence_used=("ctx.run_evidence.commands",),
            criterion_revision=criterion_revision,
        )
    red = [c for c in commands if int(c.get("exit_code")) != 0]
    if red:
        red_findings = [
            {
                "gate": gate_id, "axis": axis, "severity": "error",
                "target": str(c.get("claim_id") or "?"),
                "message": f"实跑**跑挂了**（exit_code={c.get('exit_code')}）⇒ 阻断",
                "evidence": (
                    f"claim_id={c.get('claim_id')} command={str(c.get('command'))!r} "
                    f"exit_code={c.get('exit_code')} output_tail={str(c.get('output_tail'))[:160]!r}"
                ),
            }
            for c in red
        ]
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="fail",
            reason=(f"{len(red)} 条实跑记录**退出码非零** ⇒ 跑过但红了，"
                    f"不能算『可复跑』（绿的那几条已覆盖断言，红的是命令本身失败）"),
            findings=tuple(red_findings),
            counts={**counts_base, "退出码非零": len(red)},
            evidence_used=("ctx.run_evidence.commands", "documents.claims[*].numeric_evidence.script"),
            criterion_revision=criterion_revision,
        )
    proc = (f"把 claims 里 {len(numeric)} 条带 numeric_evidence.script 的断言与本轮 "
            f"{len(commands)} 条实跑记录按 claim_id 求差集；再逐条核回执的 "
            f"{len(G8_RECEIPT_KEYS)} 个键与退出码")
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="pass",
        reason=(f"{len(commands)} 条实跑记录覆盖全部数值断言，且逐条带退出码（全绿）与输出"),
        findings=(),
        self_attestation=_attest_text(
            attest(proc, {**counts_base, "退出码非零": 0},
                   evidence_used=("ctx.run_evidence", "documents.claims[*].numeric_evidence"))),
        counts={**counts_base, "退出码非零": 0},
        evidence_used=("ctx.run_evidence.commands", "documents.claims[*].numeric_evidence.script"),
        criterion_revision=criterion_revision,
    )


# ---- G9 计数一致门 --------------------------------------------------------


def gate_g9(ctx: GateContext) -> GateResult:
    """G9 计数一致门（§8.4 标注为新增：那套书没有，而 §1.4 有十处计数漂移）。

    判据（§8.4）："同一计数（定理数/反例数/脚本数/批次数）在所有文件中一致。"
    失败处置：阻断（见 §1.4 的十处漂移）。

    适配说明：我们的"所有文件"= 同一份稿件在不同读取路径下看到的数字：
    `documents` 行里的 `claims` 长度、调用方声明的计数、以及按 `kind`
    分类型的计数。三者必须一致 —— 这正是"U0 说 121 条、V2 说 116 条"的同族形态。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G9", "体例"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    claims = ctx.claims()
    actual_total = len(claims)
    by_kind: dict[str, int] = {}
    for c in claims:
        k = str(c.get("kind") or "（未标 kind）")
        by_kind[k] = by_kind.get(k, 0) + 1
    actual_counterexamples = sum(
        len(c.get("counterexamples") or []) for c in claims if isinstance(c.get("counterexamples"), (list, tuple))
    )
    actual_scripts = len(
        {
            str((c.get("numeric_evidence") or {}).get("script"))
            for c in claims
            if isinstance(c.get("numeric_evidence"), Mapping)
            and str((c.get("numeric_evidence") or {}).get("script") or "").strip()
        }
    )
    findings: list[dict] = []
    declared = ctx.claim_counts
    if not isinstance(declared, Mapping) or not declared:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                "调用方没有提供**声明侧的计数**（`claim_counts`）⇒ 没有『另一个文件』可对账，"
                "**判不了一致性**。注意：单看一处数字永远不能判『一致』 —— "
                "那正是 §1.4 十处漂移始终没被发现的原因（没有任何脚本在查）"
            ),
            counts={"实际断言数": actual_total, "按 kind": by_kind},
            evidence_used=("documents.claims", "ctx.claim_counts"),
            criterion_revision=criterion_revision,
        )
    pairs: list[tuple[str, Any, Any]] = [
        ("断言数", declared.get("declared_claim_count"), actual_total),
        ("反例数", declared.get("declared_counterexample_count"), actual_counterexamples),
        ("脚本数", declared.get("declared_script_count"), actual_scripts),
    ]
    declared_by_kind = declared.get("declared_kind_counts")
    if isinstance(declared_by_kind, Mapping):
        for k, v in declared_by_kind.items():
            pairs.append((f"kind={k}", v, by_kind.get(str(k), 0)))
    for label, want, got in pairs:
        if want is None:
            continue
        if int(want) != int(got):
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "error", "target": label,
                    "message": f"同一计数在两处不一致：声明 {want} vs 实际 {got} ⇒ 阻断",
                    "evidence": f"计数名={label}；声明值={want}；从稿件重算={got}；重算明细={by_kind}",
                }
            )
    counts = {
        "实际断言数": actual_total,
        "实际反例数": actual_counterexamples,
        "实际脚本数": actual_scripts,
        "对账的计数项": len([p for p in pairs if p[1] is not None]),
        "不一致项": len(findings),
    }
    proc = f"从 {actual_total} 条断言重算 断言数/反例数/脚本数/按 kind 计数，与调用方声明的 claim_counts 逐项比对"
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if findings else "pass",
        reason=(f"{len(findings)} 处计数漂移 ⇒ 阻断" if findings else f"{counts['对账的计数项']} 个计数项一致"),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims", "ctx.claim_counts"))),
        counts=counts,
        evidence_used=("documents.claims[*].kind", "documents.claims[*].counterexamples", "documents.claims[*].numeric_evidence", "ctx.claim_counts"),
        criterion_revision=criterion_revision,
    )


# ---- G10 审校格式门 -------------------------------------------------------


def _quote_word_count(text: str) -> int:
    """逐字引文的"词数"：中文按字计、英文按空白切词计（参考体例的 ≤20 词）。"""
    t = str(text or "").strip()
    if not t:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
    latin = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'_-]*", t))
    return cjk + latin


#: G10 六格里"最小修法"那一格的键名（`P-9` 候选 A 的对齐动作，2026-09-27 所有者裁定）。
#:
#: `schema.ReviewFinding` 里这一格叫 `suggestion`，而 `P-9` 正文与旧夹具写的是
#: `minimal_fix`。它们是同一个格子的两个键名，判据只有这一处实现（FC-03）：
#: 取值时正名优先、历史键名兜底；两个名字都不写才算缺这一格。
#: 只在一边改名的后果是实测过的：G10 会因为读不到键而把每一条发现都打成"不合格式"。
_MINIMAL_FIX_KEYS = ("suggestion", "minimal_fix")


def _minimal_fix_of(f: Mapping[str, Any]) -> str:
    """取"最小修法"那一格（正名 `suggestion` 优先，历史键名 `minimal_fix` 兜底）。"""
    for key in _MINIMAL_FIX_KEYS:
        value = f.get(key)
        if str(value or "").strip():
            return str(value)
    return ""


#: `created_at` 的日期形态（`YYYY-MM-DD` 前缀）。判据见 `_finding_format_in_scope`。
_CREATED_AT_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _finding_format_in_scope(f: Mapping[str, Any]) -> bool:
    """这条发现是否落在审校格式契约（`P-9` 候选 A）的作用面内。

    契约只对 `created_at >= schema.REVIEW_FINDING_FORMAT_SINCE` 的发现要求
    `line` / `verbatim_quote` / `suggestion` / `maths` 四键齐；更早的行是契约生效前
    落盘的历史行，按 `created_at` 豁免（不许回填 —— `line` 只能从 `target` 猜出来，
    猜出来的行号是一个发明出来的数字；理由见 `schema.REVIEW_FINDING_FORMAT_SINCE`）。

    `created_at` 缺失、为空、或不是 `YYYY-MM-DD` 形态，都不豁免：拿不到合法创建
    时刻就不能主张豁免，否则"把 created_at 删掉或截断"就成了绕过这道门的万能钥匙
    （三态纪律：未知不是通过）。判据是"日期形态命中后取前 10 个字符比较"，
    而不是纯字典序比较 —— 常量的真前缀（`'2026-09-2'` / `'2026-09-'` /
    `'2026-0'` / `'2'` 这四个截断串）字典序比常量小，纯比较会把它们读成
    "契约生效前的历史行"而豁免掉，比空串还宽松（第 10 轮独立重审 `R2b-AN-2` 实测）。
    """
    created = str(f.get("created_at") or "").strip()
    if not _CREATED_AT_DATE_PREFIX_RE.match(created):
        return True
    return created[:10] >= S.REVIEW_FINDING_FORMAT_SINCE


def _has_the_four_gate_keys(f: Mapping[str, Any]) -> bool:
    """四键是否"存在"（不管值有没有意义）。

    "键存在"与"值有意义"是两件事（`P-9` 候选 A 的口径）：前者由这道门判、
    后者由写入期的判据判。所以这里用 `in` 而不是真值 —— `line=None` 且给了
    `line_unavailable_reason` 的行是合规的第三态，它在这一格里算"有"。
    """
    return (
        "line" in f
        and "verbatim_quote" in f
        and "maths" in f
        and any(key in f for key in _MINIMAL_FIX_KEYS)
    )


def _line_cell(f: Mapping[str, Any]) -> str:
    """`行号(line)` 那一格的三态取值（供"缺字段"那条判据用）。

    返回非空 = 这一格有东西；返回空串 = 缺字段。三态：
      * 给了行号（不管合不合法）⇒ 返回它的字符串（不合法由下面的取值判据报，
        不在这里重复报成"缺字段"）；
      * 拿不到行号（缺键 / `None` / 空串）但自证了 `line_unavailable_reason`
        ⇒ 返回一个非空占位（"行号拿不到"是一个可判定的结论，不是空白）；
      * 其余 ⇒ 空串。
    """
    value = f.get("line")
    if value is not None and str(value).strip():
        return str(value)
    if str(f.get("line_unavailable_reason") or "").strip():
        return "未冻结（已自证）"
    return ""


def _line_cell_for_frozen_version(f: Mapping[str, Any]) -> str:
    """版本已冻结（G11 通过）时 `行号(line)` 那一格的取值（`X-96.3-2`）。

    与 :func:`_line_cell` 只差第三条支：`line=None` + `line_unavailable_reason`
    在未冻结时是合规的第三态，在已冻结时不是 —— 版本已经冻住了，
    "这一次拿不到行号"与事实矛盾，而 `line` 的判据逐字是"G11 通过后必填"。

    也就是说这一格的口径是"G11 通过 ⇒ 必填"，
    不是"G11 通过 ⇒ 必填或自证拿不到"（后者会让这条判据在版本冻结之后
    仍然可以被一句自证绕过 —— 那正是 `X-96.3-2` 说的"没接线"）。
    """
    value = f.get("line")
    if value is not None and str(value).strip():
        return str(value)
    return ""


def gate_g10(ctx: GateContext) -> GateResult:
    """G10 审校格式门（照搬 `STYLE/RUBRIC.md:30-33`、`:111-126`、`:128-134`）。

    判据（§8.4）："每条发现必须有：轴 + 严重度 + 行号 + ≤20 词逐字引文 +
    最小修法 + `maths: yes/no`。" 失败处置：不合格式的发现打回。

    这道门有多条返回路径，G-12 的核心事实就在这里（"实现者用证据反驳简报"的那一处）：
    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`（声明表），
    每条路径打的是同一句话。

    ---- `P-9` 候选 A 落地之后的形态（2026-09-27 所有者裁定）----

    `schema.ReviewFinding` 现在带 `axis` / `line` / `verbatim_quote` / `maths`
    四个字段（"最小修法"那一格与 `suggestion` 对齐），所以"本项目结构性不可判"
    这句话不再成立。剩下的判断分两半：

    * 键不全的行：仍然报 `unknown` 并把缺的键逐条列出来（不删门、不判 pass）。
      这些行是契约生效日之前落盘的历史行，或尚未补键的产出方写出的行 ——
      两种都要看得见；
    * 键齐全的行：按 §8.4 逐字判（六字段齐 + 引文 ≤20 词 + 轴与 maths 在
      取值域内 + 行号是 1 起的整数），不合格式的发现打回。

    两半之间还有一条按 `created_at` 的豁免（`_finding_format_in_scope`）：
    契约生效前的历史行不参与"四键齐不齐"这条判据 —— 它们落盘时契约还不存在，
    而 `store.rebuild()` 会把任何 `validate()` 抛异常的行静默丢掉，
    所以"补齐"这件事只能向前做，历史行不许回填。

    四条返回路径（第 10 轮独立重审 `R2b-AN-1`/`R2b-AN-3` 之后的口径）：

    * `findings is None`（调用方没给列表）⇒ `unknown`；
    * 零发现（`findings == []`，一篇没有任何发现的稿件）⇒ `pass`
      —— 有可判定的对象，只是列表里没有需要判格式的行；
    * 有发现而契约作用面内为空（全是生效日前的历史行）⇒ `not_applicable`；
      这一支要求发现数大于 0（`temp/FIXG4.md` §2.2 的原文）：零发现走上面那一支，
      否则 reason 会断言"0 条发现全部是历史行"而自己的 `counts` 说豁免 = 0；
    * 作用面内缺四键 ⇒ `unknown`；键齐但不合格式 ⇒ `fail`；其余 ⇒ `pass`。

    ---- `line` 那一格挂着 G11（`X-96.3-2`）----

    `line` 的判据不是"总要给行号"，而是"G11 通过后必填"：行号只有在版本冻结
    之后才有意义。判据的一头一尾因此必须接上，接法有两处、都在本模块里：

    1. :meth:`GateContext.build` 把"冻没冻"算一次（:attr:`GateContext.
       findings_version_pinned`，判据与 `gate_g11` 自己那一句同源）；
    2. 本门据它换掉 `行号(line)` 那一格的取值函数：冻结时用
       :func:`_line_cell_for_frozen_version`（`line_unavailable_reason` 不再是
       合规第三态），没冻/判不了时用 :func:`_line_cell`（原来的三态）。

    另有一条前置耦合：给了 `findings` 就必须同时给 `observed_hash`（反之亦然），
    否则本门返回 `unknown`（fail-closed）—— 两者缺一时"这一轮审的是哪一版"
    无从谈起，`line` 那一格也就没有依据。这一支不记 pass。

    字段词表与词数口径都只有一份实现：轴读 `AXES`、`maths` 读
    `schema.FINDING_MATHS_VALUES`、词数读 `_quote_word_count`（本模块自己那份）。
    """
    gate_id, axis = "G10", "体例"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.findings is None:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                "调用方没有提供发现列表（`findings`）⇒ 没有可判定的对象。"
                "（**注意**：这与『没有发现』不同 —— 后者才可能判 pass）"
            ),
            counts={"发现数": "未提供"},
            evidence_used=("ctx.findings",),
            criterion_revision=criterion_revision,
        )
    all_findings = list(ctx.findings)
    in_scope = [f for f in all_findings if _finding_format_in_scope(f)]
    exempt = len(all_findings) - len(in_scope)
    #: 版本是否冻结（G11 通过）—— `line` 那一格的判据挂着它（`X-96.3-2`）。
    #: 现算（不是读快照）：调用方可以在 `build()` 之后直接改 `observed_hash`。
    frozen_version = ctx.frozen_version()
    line_cell = _line_cell_for_frozen_version if frozen_version is True else _line_cell
    findings_out: list[dict] = []
    for f in in_scope:
        fid = str(f.get("finding_id") or f.get("id") or "?")
        missing = [
            name
            for name, getter in (
                ("轴(axis)", lambda x: x.get("axis")),
                ("严重度(severity)", lambda x: x.get("level")),
                ("行号(line)", line_cell),
                ("≤20 词逐字引文(verbatim_quote)", lambda x: x.get("verbatim_quote")),
                ("最小修法(suggestion；历史键名 minimal_fix)", _minimal_fix_of),
                ("maths: yes/no", lambda x: x.get("maths")),
            )
            if not str(getter(f) or "").strip()
        ]
        if missing:
            # `FINAL-R5-05`：`行号` 这一格在版本冻结时是必填，而唯一真实产出方
            # （`review_tools.scan_document`）只在调用方给了带行号的正文时才给得出 ——
            # 不给正文时它按设计给 `line=None` + 受控理由串。所以这里在不改判据
            # 的前提下把"是谁的缺口、怎么补"写进 evidence（判据照旧打回，只是不再
            # 让读者以为那是产出方格式马虎）。
            gap_hint = ""
            if "行号(line)" in missing:
                gap_hint = (
                    "；行号那一格：版本已冻结 ⇒ 必填。产出方只有在拿到带行号的正文时"
                    "才给得出（`review_tools.scan_document(doc)` 的 `doc['text'/'body'/'markdown']`）；"
                    "补法在产出侧或流程侧（冻结前补行号），不在本门放宽判据"
                )
            findings_out.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "warning", "target": fid,
                    "message": "发现不合参考体例的格式（缺字段）—— 打回",
                    "evidence": f"finding_id={fid} 缺 {missing}；实际键={sorted(f)}{gap_hint}",
                }
            )
        f_axis = str(f.get("axis") or "").strip()
        if f_axis and f_axis not in AXES:
            findings_out.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "warning", "target": fid,
                    "message": "轴不在参考体例的轴词表里 —— 打回",
                    "evidence": f"finding_id={fid} axis={f_axis!r} 不在 {AXES}",
                }
            )
        f_maths = str(f.get("maths") or "").strip()
        if f_maths and f_maths not in S.FINDING_MATHS_VALUES:
            findings_out.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "warning", "target": fid,
                    "message": "maths 取值不是 yes/no —— 打回",
                    "evidence": f"finding_id={fid} maths={f_maths!r} 不在 {S.FINDING_MATHS_VALUES}",
                }
            )
        f_line = f.get("line")
        if (
            f_line is not None
            and str(f_line).strip()
            and not (isinstance(f_line, int) and not isinstance(f_line, bool) and f_line >= 1)
        ):
            findings_out.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "warning", "target": fid,
                    "message": "行号必须是 1 起的整数（或给 line_unavailable_reason）—— 打回",
                    "evidence": f"finding_id={fid} line={f_line!r}",
                }
            )
        if str(f.get("verbatim_quote") or "").strip() and _quote_word_count(str(f["verbatim_quote"])) > 20:
            findings_out.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "warning", "target": fid,
                    "message": "逐字引文超过 20 词（参考体例：≤20 词）",
                    "evidence": f"finding_id={fid} 词数={_quote_word_count(str(f['verbatim_quote']))}",
                }
            )
    counts = {
        "发现数": len(all_findings),
        "契约作用面内": len(in_scope),
        "豁免(契约生效前的历史行)": exempt,
        "不合格式": len(findings_out),
    }
    # "版本冻结(G11 通过)"这一格只在真的判了行号那一格时才出现：
    # 作用面内为 0 时这道门没判过任何 `line`，凭空多一个键就是
    # 把"这一轮冻没冻"塞进一份与它无关的读数里（同名口径：非零才出现）。
    if in_scope:
        counts["版本冻结(G11 通过)"] = (
            "判不了" if frozen_version is None else ("是" if frozen_version else "否")
        )
    proc = (
        f"逐条检查 {len(in_scope)} 条落在格式契约作用面内的发现的六个必需字段、"
        f"引文词数上限（≤20 词）、轴与 maths 的取值域以及行号形态"
        # 豁免那一档只在非零时出现并带自己的数（`draft/28` §88.3）——
        # 0 豁免时连"另有 0 条…"这句都不出现（`R2b-AN-3`）。
        + (
            f"；另有 {exempt} 条为契约生效日（{S.REVIEW_FINDING_FORMAT_SINCE}）之前的历史行，"
            "按 created_at 豁免（不许回填）"
            if exempt
            else ""
        )
    )
    structural_gap = len(in_scope) - len([f for f in in_scope if _has_the_four_gate_keys(f)])
    # ---- `findings` 与 `observed_hash` 的耦合（`X-96.3-2`）----
    #
    # 接线前的实测形态（`draft/28` §96.3 第 2 条逐字）：`GateContext` 里这两个输入
    # 互不相干，于是"一条带行号的发现"可以在一份没钉版本 hash 的报告里通过 G10
    # —— 而 `line` 的判据是"G11 通过后必填"：它的全部意义恰恰是"版本冻住之后，
    # 行号才有意义"。不接线时的后果不是假通过那么远，而是这条判据的结论没有依据：
    # G10 读不到"冻没冻"，于是它判的 `line` 与它自述的判据是两回事。
    #
    # 这里的处置是 fail-closed（`unknown`，不是 `pass`）：给了 `findings` 就必须
    # 同时给出 `observed_hash`（"这一轮审的是哪一版"），反之亦然 —— 只有两样都在场，
    # `line` 那一格才是可判的。三态纪律：判不了 ⇒ 明说判不了，不许静默按"没冻"处理
    # （那正好把这条判据架空）。
    has_observed = bool(str(ctx.observed_hash or "").strip())
    if has_observed != (frozen_version is True):
        unpinned = [f for f in in_scope if f.get("line") is not None and str(f.get("line")).strip()]
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                "`findings` 与 `observed_hash` 不相绑 ⇒ 这道门的『行号(line)：G11 通过后必填』"
                "那一格判不了（`X-96.3-2`）："
                + (
                    f"调用方给了发现列表，却没给上一轮报告里钉住的 `observed_hash`"
                    f"（其中 {len(unpinned)} 条带行号 —— 而行号只有在版本冻结之后才有意义；"
                    "请把 `observed_hash` 一并给出，或把那些行号按第三态写成 `line_unavailable_reason`）"
                    if not has_observed
                    else
                    "调用方给的 `observed_hash` 与本轮重算的被审版本 hash 不一致"
                    "（G11 判定为『未冻结』/『审校期间被改过』）⇒ 这一轮不该带带行号的发现："
                    "行号指向的是一个已经失效的版本"
                )
                + "。不记 pass：判不了 ≠ 没冻（三态纪律）"
            ),
            findings=tuple(findings_out),
            self_attestation=_attest_text(attest(proc, counts, evidence_used=("ctx.findings", "ctx.observed_hash"))),
            counts=counts,
            evidence_used=("ctx.findings", "ctx.observed_hash", "schema.ReviewFinding"),
            criterion_revision=criterion_revision,
        )
    if structural_gap:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                f"{structural_gap} / {len(in_scope)} 条落在格式契约作用面内的发现**缺 `line`/"
                "`verbatim_quote`/`suggestion`(=`minimal_fix`)/`maths` 字段本身**（不是写错）"
                "⇒ 这道门的完整判据对这些行**不可判定**。字段本身已在 `schema.ReviewFinding`"
                "（禁 AI 区；2026-09-27 所有者裁定候选 A，AI 代录入台账）里补齐 ——"
                "缺键的行是契约生效日前落盘的历史行，或尚未补键的产出方写出的行："
                "保留门并如实报 unknown，而不是删门（删门会让『15 道门都在跑』变成假话）"
                + (f"；本次另有 {exempt} 条历史行按 created_at 豁免，不计入这个缺口" if exempt else "")
            ),
            findings=tuple(findings_out),
            self_attestation=_attest_text(attest(proc, counts, evidence_used=("ctx.findings", "schema.ReviewFinding 的字段集"))),
            counts=counts,
            evidence_used=("ctx.findings", "schema.ReviewFinding"),
            criterion_revision=criterion_revision,
        )
    if all_findings and not in_scope:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="not_applicable",
            reason=(
                f"{len(all_findings)} 条发现全部是格式契约生效日（{S.REVIEW_FINDING_FORMAT_SINCE}）"
                "之前落盘的历史行（发现数 > 0，但契约作用面内的行数为 0）⇒ "
                "这道门在本次输入上没有可判定的对象。"
                "这不是通过：历史行按 created_at 豁免，且不许回填 ——"
                "下一次拿到契约生效后产出的发现时，这道门才会真正判一次"
            ),
            counts=counts,
            evidence_used=("ctx.findings", "schema.ReviewFinding"),
            criterion_revision=criterion_revision,
        )
    # 三条出口共用一个 `GateResult(...)`：`findings_out` 非空 ⇒ fail；
    # 作用面内有行且无发现 ⇒ pass（reason 带上豁免那一档）；
    # 零发现（`all_findings == []`，走到这里说明不是"全是历史行"）⇒ pass。
    #
    # 走得到这里就说明"冻没冻"与"给没给 hash"是自洽的（上面那道耦合守卫已经过了），
    # 所以这一句是对得上号的口径说明、不是替调用方猜：判过 `line` 那一格时
    # 必须让读者看见"行号是必填还是可省"这件事是谁定的（`X-96.3-2`）。
    line_basis = (
        "；行号那一格按 G11 已通过（版本冻结）判必填"
        if frozen_version is True
        else "；版本未冻结 ⇒ 行号那一格按可省判（拿不到时自证理由）"
    )
    if findings_out:
        verdict = "fail"
        reason = f"{len(findings_out)} 条发现不合格式 ⇒ 打回" + (line_basis if in_scope else "")
    elif in_scope:
        verdict = "pass"
        reason = f"作用面内 {len(in_scope)} 条发现全部符合六字段格式" + line_basis
        if exempt:
            reason += f"；另有 {exempt} 条历史行按 created_at 豁免，未参与本判定"
    else:
        verdict = "pass"
        reason = (
            "0 条发现 ⇒ 本次输入里有可判定的对象（发现列表），但没有任何行需要判格式"
            "（与『调用方没有提供发现列表』的 unknown 不同）"
        )
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict=verdict,
        reason=reason,
        findings=tuple(findings_out),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("ctx.findings", "ctx.observed_hash"))),
        counts=counts,
        evidence_used=("ctx.findings", "ctx.observed_hash"),
        criterion_revision=criterion_revision,
    )


# ---- G11 版本冻结门 -------------------------------------------------------


def gate_g11(ctx: GateContext) -> GateResult:
    """G11 版本冻结门（照搬 `STYLE/FIX_PROTOCOL.md:5-10`）。

    判据（§8.4）："审校期间不改文件；报告钉住被审版本 hash；一次改完一篇，
    不二次编辑。" 失败处置：阻断。

    适配说明：`observed_hash` 是上一轮报告里钉下的 hash（可选）。
    不提供 ⇒ 本门只能证明"我这一轮钉住了 hash"，不能证明"审校期间没被改过" ——
    这两种结论必须分开，所以不提供时判 `unknown`（不是 pass）。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G11", "工程"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    if not ctx.revision_hash:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason="算不出被审版本的内容 hash（稿件为空/不可序列化）⇒ **钉不住版本**",
            counts={"被审版本 hash": ""},
            evidence_used=("documents.claims",),
            criterion_revision=criterion_revision,
        )
    counts = {"被审版本 hash": ctx.revision_hash, "上一轮钉住的 hash": ctx.observed_hash or "未提供"}
    if not ctx.observed_hash:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                f"本轮**已经钉住** hash={ctx.revision_hash}，但调用方**没有提供上一轮报告里钉住的 hash** ⇒ "
                "『审校期间文件有没有被改过』这件事**判不了**（钉住 hash ≠ 验证没被改）。"
                "三态纪律：这两种结论必须分开"
            ),
            counts=counts,
            self_attestation=_attest_text(
                attest(
                    "对 documents（doc_id/title/kind/claims 逐条内容 hash）算 sha256[:16]",
                    counts,
                    evidence_used=("documents",),
                )
            ),
            evidence_used=("documents", "ctx.observed_hash"),
            criterion_revision=criterion_revision,
        )
    frozen = str(ctx.observed_hash) == ctx.revision_hash
    findings: list[dict] = []
    if not frozen:
        findings.append(
            {
                "gate": gate_id, "axis": axis, "severity": "error",
                "target": str(ctx.doc.get("doc_id") or "?"),
                "message": "被审版本在审校期间被改过（hash 不匹配）⇒ 阻断，本次审校结论作废",
                "evidence": f"上一轮 hash={ctx.observed_hash}，本轮重算={ctx.revision_hash}",
            }
        )
    counts["是否冻结"] = frozen
    proc = "重算被审版本内容 hash（doc_id/title/kind/逐条 claim 内容 hash）并与上一轮报告钉住的 hash 逐字比对"
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if findings else "pass",
        reason=("被审版本在审校期间被改过 ⇒ 阻断" if findings else f"版本冻结：hash={ctx.revision_hash} 与上一轮一致"),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents", "ctx.observed_hash"))),
        counts=counts,
        evidence_used=("documents", "ctx.observed_hash"),
        criterion_revision=criterion_revision,
    )


# ---- G12 反方门 -----------------------------------------------------------


def gate_g12(ctx: GateContext) -> GateResult:
    """G12 反方门（照搬 `RP/00_STANDARD.md:157`（角色 C）+ `LESSONS.md:35-41`（L7））。

    判据（§8.4）："主动构造小参数反例；冲突时先手验最小实例，
    不许『用更多计算量去裁决计算与证明的冲突』。" 失败处置：阻断。

    适配说明：本门判两件事 ——
    ① 标了 `status='证'` 的断言必须有反例搜索的痕迹（`counterexamples`
       字段存在，或是 `numeric_evidence.n_counterexamples` 有值）：
       零反例与"没搜过"必须能分开（"没搜过"不许读成"没有反例"）；
    ② `counterexamples` 非空而 `status='证'` ⇒ 自相矛盾（有反例却标已证）。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G12", "数学"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    findings: list[dict] = []
    proved = 0
    with_counter_search = 0
    for c in ctx.claims():
        cid = str(c.get("claim_id") or "?")
        if c.get("status") != "证":
            continue
        proved += 1
        ne = c.get("numeric_evidence") if isinstance(c.get("numeric_evidence"), Mapping) else {}
        # 两条痕分开写清：`counterexamples` 键存在（哪怕是空列表）算"搜过并留了痕"，
        # `n_counterexamples` 有值是另一条。这里曾经写成 `has_search = has_search or True`
        # —— 恒真表达式，值与判据一致，但读者无法分辨它和笔误，且没有测试钉住这一格。
        has_search = ("counterexamples" in c) or (
            isinstance(ne, Mapping) and ne.get("n_counterexamples") is not None
        )
        if has_search:
            with_counter_search += 1
        else:
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "warning", "target": cid,
                    "message": "标了『证』但**没有反例搜索的痕迹**（既无 counterexamples 也无 n_counterexamples）",
                    "evidence": (
                        f"claim_id={cid} status='证' 但 counterexamples 键缺失、"
                        f"numeric_evidence={ne!r} —— 『没搜过』不许读成『没有反例』"
                    ),
                }
            )
        ces = c.get("counterexamples") or []
        if isinstance(ces, (list, tuple)) and ces:
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "error", "target": cid,
                    "message": "有反例却标了 `status='证'` ⇒ 自相矛盾，阻断",
                    "evidence": f"claim_id={cid} status='证' 但 counterexamples={list(ces)[:3]!r}（共 {len(ces)} 条）",
                }
            )
    counts = {"标『证』的断言数": proved, "有反例搜索痕迹": with_counter_search, "问题数": len(findings)}
    proc = f"在 {len(ctx.claims())} 条断言里筛出 {proved} 条 status=='证'，逐条核对 counterexamples / numeric_evidence.n_counterexamples 是否存在"
    if not proved:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="not_applicable",
            reason=(
                "本稿**没有任何 `status='证'` 的断言**（可能仍用旧字段、没有 status）⇒ "
                "反方门本轮没有可判定的对象。这不是『反例都搜过了』"
            ),
            counts=counts,
            self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims[*].status",))),
            evidence_used=("documents.claims[*].status",),
            criterion_revision=criterion_revision,
        )
    errors = [f for f in findings if f["severity"] == "error"]
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if errors else "pass",
        reason=(
            f"{len(errors)} 条『证』的断言存在反例（自相矛盾）⇒ 阻断"
            if errors
            else f"{with_counter_search} / {proved} 条『证』断言有反例搜索痕迹"
        ),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims[*].status", "documents.claims[*].counterexamples"))),
        counts=counts,
        evidence_used=("documents.claims[*].status", "documents.claims[*].counterexamples", "documents.claims[*].numeric_evidence"),
        criterion_revision=criterion_revision,
    )


# ---- G13 空结论自证门 -----------------------------------------------------


def gate_g13(ctx: GateContext, results: Mapping[str, GateResult] | None = None) -> GateResult:
    """G13 空结论自证门（照搬 `STYLE/RUBRIC.md:105-107`）。

    判据（§8.4）："某个轴『零发现』时必须报告『用了什么过程、数出了什么数字』。"
    失败处置：阻断（实测范例：`p6_..._REFEREE.md:48-56`）。

    这道门是对报告本身的检查：它遍历其余各门，凡是报"零发现"的，
    必须有自证块。缺一个就是 H 自己的格式违规 ——
    所以 `GateResult.__post_init__` 已经让那种对象构造不出来。
    本门再独立数一遍，是因为"构造不出来"只覆盖本模块的路径：
    若有人从别处塞进一个 `GateResult`（或未来加了旁路），这里仍然会红。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；本函数只从那里取，不在函数体里写第二份字面量（FC-03）。
    """
    gate_id, axis = "G13", "体例"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if results is None:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="unknown",
            reason=(
                "没有给出其余各门的结论（`results`）⇒ **无法判定谁报了零发现**。"
                "G13 是对报告自身的检查，缺了报告就没有对象"
            ),
            counts={"检查的门数": 0},
            evidence_used=("run_all_gates 的返回",),
            criterion_revision=criterion_revision,
        )
    findings: list[dict] = []
    zero_found = 0
    attested = 0
    for gid, r in sorted(results.items()):
        if gid == gate_id:
            continue
        if r.verdict == "pass" and not r.findings:
            zero_found += 1
            if r.self_attestation.strip() and r.counts:
                attested += 1
            else:
                findings.append(
                    {
                        "gate": gate_id, "axis": axis, "severity": "error", "target": gid,
                        "message": f"{r.name}（{gid}）报了『零发现』却没有自证数字 ⇒ 报告格式违规，阻断",
                        "evidence": f"{gid}.self_attestation={r.self_attestation!r} counts={dict(r.counts)!r}",
                    }
                )
    counts = {"检查的门数": len([g for g in results if g != gate_id]), "报零发现的门数": zero_found, "自证齐全": attested}
    proc = f"遍历其余 {counts['检查的门数']} 道门的结论，筛出 verdict=='pass' 且 findings 为空的门，核对 self_attestation 与 counts 是否都非空"
    errors = [f for f in findings if f["severity"] == "error"]
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if errors else "pass",
        reason=(
            f"{len(errors)} 道报零发现的门没有自证数字 ⇒ 报告格式违规" if errors
            else f"{zero_found} 道门报零发现，全部带自证数字（共 {attested} 道）"
        ),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("run_all_gates 的返回",))),
        counts=counts,
        evidence_used=("run_all_gates 的返回",),
        criterion_revision=criterion_revision,
    )


# ---- G14 降级合规门 -------------------------------------------------------


def gate_g14(ctx: GateContext) -> GateResult:
    """G14 降级合规门（照搬 `RP/00_STANDARD.md:105-110`）。

    判据（§8.4）："只有数值支撑的结论不得出现在摘要/主结果，必须降为 Remark + 命令。"
    失败处置：阻断。

    适配说明：降级的载体就是 §8.3 的 `allowed_use` 与 `status`：
    ① `status='作废'` 的断言不得出现在主结果区（渲染层门，
       `claimanatomy.main_body_claims` 是同一份判据）；
    ② `evidence_kind != 'proof'` 的断言若标 `allowed_use='主结果'` ⇒
       它必须有 `scope_caveat` 说明限定语，否则就是"把交叉验证写进主结果"。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；上面那段适配说明只是"为什么要适配"的论证，不构成第二份声明（FC-03）。
    """
    gate_id, axis = "G14", "数学"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    if ctx.doc is None:
        return _no_doc(gate_id, axis, criterion)
    findings: list[dict] = []
    scanned = 0
    retracted_in_body = 0
    must_downgrade = 0
    for c in ctx.claims():
        scanned += 1
        cid = str(c.get("claim_id") or "?")
        if CA.is_retracted(c):
            retracted_in_body += 1
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "error", "target": cid,
                    "message": "`status='作废'` 的断言出现在正文主结果区 ⇒ 阻断（它只能进附录）",
                    "evidence": (
                        f"claim_id={cid} status='作废'；"
                        f"撤销原因={CA._retraction_reason(c) or '（未登记）'}；"
                        "渲染层必须用 claimanatomy.main_body_claims() 过滤"
                    ),
                }
            )
        ek = c.get("evidence_kind")
        au = c.get("allowed_use")
        if ek in ("cross_check", "heuristic") and au == "主结果":
            must_downgrade += 1
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "error", "target": cid,
                    "message": (
                        f"`evidence_kind={ek!r}` 的断言标了 `allowed_use='主结果'` ⇒ 必须降为 "
                        "`Remark only` 或 `移入 open`（参考体例的硬性降级规则）"
                    ),
                    "evidence": f"claim_id={cid} evidence_kind={ek!r} allowed_use={au!r}",
                }
            )
        if c.get("allowed_use") == "移入 open":
            findings.append(
                {
                    "gate": gate_id, "axis": axis, "severity": "warning", "target": cid,
                    "message": "该断言被降级为『移入 open』：它不应出现在主结果区（须进开放问题区）",
                    "evidence": f"claim_id={cid} allowed_use='移入 open'",
                }
            )
    counts = {
        "扫描的断言数": scanned,
        "作废却在正文": retracted_in_body,
        "须降级却标主结果": must_downgrade,
        "问题数": len(findings),
    }
    proc = f"遍历 {scanned} 条断言，检查 status=='作废' 与 (evidence_kind, allowed_use) 组合是否符合降级规则"
    errors = [f for f in findings if f["severity"] == "error"]
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="fail" if errors else "pass",
        reason=(
            f"{len(errors)} 条断言违反降级规则 ⇒ 阻断" if errors else f"{scanned} 条断言的降级规则全部合规"
        ),
        findings=tuple(findings),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("documents.claims[*].status", "documents.claims[*].allowed_use", "documents.claims[*].evidence_kind"))),
        counts=counts,
        evidence_used=("documents.claims[*].status", "documents.claims[*].allowed_use", "documents.claims[*].evidence_kind"),
        criterion_revision=criterion_revision,
    )


# ---- G15 自己的错入册 -----------------------------------------------------


def gate_g15(ctx: GateContext) -> GateResult:
    """G15 自己的错入册（照搬 `RP/p6_.../EVIDENCE.md:74-83`）。

    判据（§8.4）："报告/审核记录里必须有『我在这轮里犯的错』一节。"
    失败处置：缺失则退回。

    这一节必须由调用方显式给出（`own_errors`）。不传 ⇒ 判 `fail`
    （"我没犯错"必须由人写出来，不许由"没写"默认成立）。
    传了空列表 `[]` ⇒ 判 `pass`，但自证里会写明"显式声明本轮零自身错误"——
    与"没写"严格区分：这正是三态纪律在报告字段上的形态。

    `criterion_revision` 的唯一来源是 `GATE_CRITERIA_REVISION[gate_id]`
    （声明表）；本函数只从那里取，不在函数体里写第二份字面量（FC-03）。
    """
    gate_id, axis = "G15", "工程"
    criterion = GATES[gate_id]["criterion"]
    criterion_revision = GATE_CRITERIA_REVISION[gate_id]
    errs = ctx.own_errors
    if errs is None:
        return GateResult(
            gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
            verdict="fail",
            reason=(
                "报告里**没有**『我这一轮犯的错』一节（调用方未提供 `own_errors`）⇒ **退回**。"
                "参考体例把它放在报告头里、不许省 —— 若允许『没写』等于『没犯错』，"
                "这一节就会永远空着"
            ),
            findings=tuple(
                [
                    {
                        "gate": gate_id, "axis": axis, "severity": "error", "target": "report",
                        "message": "缺少『我这一轮犯的错』一节 ⇒ 退回",
                        "evidence": "ctx.own_errors is None（既不是空列表也不是有内容）",
                    }
                ]
            ),
            counts={"自身错误条数": "未登记"},
            evidence_used=("ctx.own_errors",),
            criterion_revision=criterion_revision,
        )
    items = [str(x) for x in errs if str(x).strip()]
    counts = {"自身错误条数": len(items), "显式声明零错误": len(items) == 0}
    proc = "检查 ctx.own_errors 是否为 None（None=没写这一节 ⇒ fail；[]=显式声明零错误 ⇒ pass）"
    return GateResult(
        gate_id=gate_id, name=GATES[gate_id]["name"], axis=axis, criterion=criterion,
        verdict="pass",
        reason=(
            f"『我这一轮犯的错』一节已登记 {len(items)} 条" if items
            else "调用方**显式声明**本轮零自身错误（`own_errors=[]`，与『没写』严格区分）"
        ),
        findings=(),
        self_attestation=_attest_text(attest(proc, counts, evidence_used=("ctx.own_errors",))),
        counts=counts,
        evidence_used=("ctx.own_errors",),
        criterion_revision=criterion_revision,
    )


# ---------------------------------------------------------------- 门声明表

#: 15 个门号齐全的声明表。每个门号可单独查询到它的判据与实现。
#:
#: 为什么用声明表而不是"一个 15 分支的 if"：`docs/ROLE-SPECS.md` 的 §R0
#: 与 `verify.py` 的 `Issue.code` 都用同一种形态 —— 跨模块的清单只能有一处，
#: 而可被 `grep`/被 CLI 打印的清单才可能被审阅者核对。
GATES: dict[str, dict[str, Any]] = {
    "G1": {
        "name": "自含性门",
        "axis": "工程",
        "criterion": "正文不得引用工作区外的路径；每个被引材料必须在工作区内存在",
        "script": "selfcontain_check.py（:24-28、:43-47）",
        "on_failure": "阻断交付",
        "checker": gate_g1,
    },
    "G2": {
        "name": "引用解析门",
        "axis": "证据",
        "criterion": "每个『材料/路径』引用可解析（含通配符）；裸文件名也能在工作区内解析",
        "script": "r75_verify_vol.py（:39-64、:74）",
        "on_failure": "阻断交付（必须返回非零退出码）",
        "checker": gate_g2,
    },
    "G3": {
        "name": "交叉引用门",
        "axis": "体例",
        "criterion": "每个外部/上游引用的目标标签真实存在；窗口取最近锚点、不跨句号、允许自指",
        "script": "strict_xref_check.py（:37-40、:59-65）+ series_xref_deep.py（:42-44）",
        "on_failure": "阻断；假阳性须逐条留痕",
        "checker": gate_g3,
    },
    "G4": {
        "name": "账本对账门",
        "axis": "体例",
        "criterion": "索引/账本点名的文件存在、卷内文件全被列出、声明的字数在容差内、声明的标签在正文存在",
        "script": "readme_integrity.py（:55-88）",
        "on_failure": "阻断",
        "checker": gate_g4,
    },
    "G5": {
        "name": "禁词/手糊门",
        "axis": "体例",
        "criterion": "中文禁词表 + 英文连词表；命中带上下文供人工裁（允许元叙述例外）",
        "script": "series_banned_words.py（:16-20）+ STYLE/RUBRIC.md:50-53",
        "on_failure": "命中须逐条裁并记录",
        "checker": gate_g5,
    },
    "G6": {
        "name": "虚证门",
        "axis": "证据",
        "criterion": "每个数值/经验断言点名的脚本与数据文件必须存在且在工作区内",
        "script": "check_yan_anchors.py（:38-46）+ check_yan_scripts_local.py（:38-50）",
        "on_failure": "阻断",
        "checker": gate_g6,
    },
    "G7": {
        "name": "台账完整门",
        "axis": "证据",
        "criterion": "每个数值断言都在台账里有一行（位置 + 逐字断言 + 类别）；禁止『仅泛证』",
        "script": "build_yan_ledger.py（:46-58、:15）",
        "on_failure": "阻断",
        "checker": gate_g7,
    },
    "G8": {
        "name": "可复跑门",
        "axis": "证据",
        "criterion": "每条数值断言都有精确命令，且**本轮实跑过**并留输出",
        "script": "新增（摘自 RP/00_STANDARD.md:149-150 门 B）",
        "on_failure": "阻断",
        "checker": gate_g8,
    },
    "G9": {
        "name": "计数一致门",
        "axis": "体例",
        "criterion": "同一计数（定理数/反例数/脚本数/批次数）在所有文件中一致",
        "script": "新增（这套书没有；见 draft/17 §1.4 的十处漂移）",
        "on_failure": "阻断",
        "checker": gate_g9,
    },
    "G10": {
        "name": "审校格式门",
        "axis": "体例",
        "criterion": "每条发现必须有：轴 + 严重度 + 行号 + ≤20 词逐字引文 + 最小修法 + maths: yes/no",
        "script": "STYLE/RUBRIC.md:30-33、:111-126、:128-134",
        "on_failure": "不合格式的发现打回",
        "checker": gate_g10,
    },
    "G11": {
        "name": "版本冻结门",
        "axis": "工程",
        "criterion": "审校期间不改文件；报告钉住被审版本 hash；一次改完一篇,不二次编辑",
        "script": "STYLE/FIX_PROTOCOL.md:5-10",
        "on_failure": "阻断",
        "checker": gate_g11,
    },
    "G12": {
        "name": "反方门",
        "axis": "数学",
        "criterion": "主动构造小参数反例；冲突时先手验最小实例，不许『用更多计算量去裁决计算与证明的冲突』",
        "script": "RP/00_STANDARD.md:157（角色 C）+ LESSONS.md:35-41（L7）",
        "on_failure": "阻断",
        "checker": gate_g12,
    },
    "G13": {
        "name": "空结论自证门",
        "axis": "体例",
        "criterion": "某个轴『零发现』时必须报告『用了什么过程、数出了什么数字』",
        "script": "STYLE/RUBRIC.md:105-107（范例 p6_..._REFEREE.md:48-56）",
        "on_failure": "阻断",
        "checker": gate_g13,
    },
    "G14": {
        "name": "降级合规门",
        "axis": "数学",
        "criterion": "只有数值支撑的结论不得出现在摘要/主结果，必须降为 Remark + 命令",
        "script": "RP/00_STANDARD.md:105-110",
        "on_failure": "阻断",
        "checker": gate_g14,
    },
    "G15": {
        "name": "自己的错入册",
        "axis": "工程",
        "criterion": "报告/审核记录里必须有『我在这轮里犯的错』一节",
        "script": "RP/p6_.../EVIDENCE.md:74-83",
        "on_failure": "缺失则退回",
        "checker": gate_g15,
    },
}

#: 每道门的判据修订状态 —— `criterion_revision` 的唯一来源（G-12 修好后）。
#:
#: * `逐字照搬` 以外的都必须在这里说清改了什么 —— 否则"15 道门都在跑"会掩盖
#:   "其中几道跑的是被改写过的判据"；
#: * 这张表必须被真的读到：15 个 `gate_gN` 与 `_no_doc` 都写
#:   `criterion_revision = GATE_CRITERIA_REVISION[gate_id]`，函数体里不许再有
#:   第二份字面量（`tests/test_coverage_gates.py` 的 AST 断言 + 哨兵断言钉住）。
#:   修之前这张表是死表：`gates.py` 里只有 `if _gid not in GATE_CRITERIA_REVISION`
#:   这一处键检查在用它，报告里印的却是函数体里的字面量 ⇒ 15/15 全部漂移
#:   （`docs/PROPOSALS.md` G-12）。"查了键存在"不等于"读了值"。
#: * 每一条都是"声明表 vs 实现"逐门比过之后的裁决：大多数取实现那一份
#:   （它更完整：带 §8.3/§8.5 出处、带"为什么"），少数是两份互补后合成的一句，
#:   G10 尤其（那份 schema 缺口 + 字段齐全时逐字判，必须写在一起）。
#:   逐门理由写在
#:   `tests/test_coverage_gates.py::test_gate_criterion_revision_texts_are_a_single_source`
#:   的 docstring 里 —— 与 `criterion` 的 G-7 那张表同一形态。
#: * 若某道门的某档本实现不判（参考体例有、我们这里没有对象），在这里如实登记为
#:   缺口，不许静默丢弃：这段文字是"适配"这件事的唯一留痕。
GATE_CRITERIA_REVISION: dict[str, str] = {
    "G1": "适配：参考体例的『包』在这里读成『工作区』（我们没有卷/包的概念）",
    "G2": "适配：前缀式引用（lit/rel/exp/eval）；『裸文件名』档在本项目不存在，只留 warning",
    "G3": (
        "**适配**：参考体例判的是散文里的『锚点窗口、不跨句号』；我们的引用是结构化字段，"
        "没有『锚点窗口』这个对象 ⇒ 改判『目标必须是本文档内真实存在的 claim_id 或可解析的 file:line』"
    ),
    "G4": (
        "适配：参考体例对的是『索引/README 与卷内文件』；我们是『documents 行与它渲染出的 "
        "markdown 文件 + claims 计数』。参考体例的另三档（卷内文件全被列出 / 声明字数在容差内 / "
        "声明标签在正文存在）**本实现不判** ⇒ 如实登记为缺口，不静默丢弃"
    ),
    "G5": (
        "适配：词表由配置注入（**不写死第二份词表** —— 参考体例的 15 中文词 + 12 英文连词表"
        "属于人的文风决定）；缺词表时报 not_applicable 而不是 pass"
    ),
    "G6": (
        "适配：数值证据的载体是 §8.3 的 numeric_evidence 四元组；脚本路径支持通配符（按 glob 展开）。"
        "参考体例的『数据文件』这一档**本实现不判**（只核 `numeric_evidence.script`）⇒ 如实登记为缺口"
    ),
    "G7": (
        "适配：我们的『台账』就是 documents.claims 本身 ⇒ 这道门判『数值型断言必须结构化』；"
        "参考体例 §8.5 明确『仅泛证型』档我们应直接取消"
    ),
    "G8": "逐字照搬 §8.4（该行标注为『新增』，摘自 RP/00_STANDARD.md:149-150 门 B）",
    "G9": "适配：『所有文件』读成『同一份稿件在不同读取路径下的数字 + 调用方声明的计数』",
    "G10": (
        "适配（缺口已按裁决补齐）：`schema.ReviewFinding` 自 2026-09-27 起带 "
        "`axis` / `line` / `verbatim_quote` / `maths` 四个字段，'最小修法'那一格与 "
        "`suggestion` 对齐（`minimal_fix` 作为历史键名继续接受）—— `P-9` 候选 A，所有者裁定；"
        "生效日之前落盘的行按 `created_at` 豁免、缺键不计入结构缺口且**不许回填**；"
        "**字段齐全的发现按 §8.4 逐字判**（六字段 + ≤20 词逐字引文 + 轴/maths 取值域 + 行号形态）"
    ),
    "G11": "适配：`observed_hash` 来自上一轮报告；未提供时只能证明『钉住了 hash』，故判 unknown",
    "G12": "适配：反例搜索的痕迹载体是 counterexamples / numeric_evidence.n_counterexamples",
    "G13": "逐字照搬 §8.4（并把它做成结构强制：缺自证的 GateResult 构造不出来）",
    "G14": "适配：降级的载体是 §8.3 的 allowed_use 与 status（`main_body_claims` 是同一份判据）",
    "G15": "逐字照搬 §8.4（并把它做成必填参数：不写就 fail）",
}


#: 门号 → 轴（从声明表派生，不写第二份）。
GATE_AXIS: dict[str, str] = {g: str(spec["axis"]) for g, spec in GATES.items()}


def known_gate_ids() -> tuple[str, ...]:
    """声明表里的门号（必须与 `GATE_IDS` 逐条一致，由测试钉住）。"""
    return tuple(sorted(GATES, key=lambda g: int(g[1:])))


def gate_verdict(results: Mapping[str, "GateResult"]) -> dict:
    """把 15 道门的结论汇总成可判定的总体判定（三档计数，无通过率）。

    分档规则（顺序即优先级）：

    | 条件 | 总体结论 |
    |---|---|
    | 任一 `fail` | `rejected` |
    | 任一 `unknown`（且有 fail 之外的未知） | `unverified` |
    | 全是 `pass` / `not_applicable`，且有 `not_applicable` | `accepted_with_gaps` |
    | 全是 `pass` | `accepted` |

    为什么 `unknown` 单占一档：把它并进 `accepted` 会让"我们从未检查"伪装成
    "检查通过"；并进 `rejected` 又会把"没做"说成"做失败了"（FC-01）。
    """
    fails = sorted(g for g, r in results.items() if r.verdict == "fail")
    unknowns = sorted(g for g, r in results.items() if r.verdict == "unknown")
    nas = sorted(g for g, r in results.items() if r.verdict == "not_applicable")
    passes = sorted(g for g, r in results.items() if r.verdict == "pass")
    if fails:
        verdict = "rejected"
    elif unknowns:
        verdict = "unverified"
    elif nas:
        verdict = "accepted_with_gaps"
    else:
        verdict = "accepted"
    return {
        "verdict": verdict,
        "pass": len(passes),
        "fail": len(fails),
        "unknown": len(unknowns),
        "not_applicable": len(nas),
        "failed_gates": fails,
        "unknown_gates": unknowns,
        "not_applicable_gates": nas,
        "reason": (
            f"pass={len(passes)} fail={len(fails)} unknown={len(unknowns)} "
            f"not_applicable={len(nas)}；"
            + (
                f"失败门={fails}" if fails
                else (
                    f"**没查成的门={unknowns}**（不许读成『没问题』）" if unknowns
                    else (f"无对象可判的门={nas}" if nas else "15 道门全部通过")
                )
            )
        ),
    }


def run_gate(gate_id: str, ctx: GateContext) -> GateResult:
    """跑单独一道门（`G13` 需要 `results` 时自动先跑其余各门）。"""
    if gate_id not in GATES:
        raise ValueError(f"未知门号 {gate_id!r}；已知 = {known_gate_ids()}")
    if gate_id == "G13":
        return gate_g13(ctx, run_all_gates(ctx))
    return GATES[gate_id]["checker"](ctx)


def run_all_gates(ctx: GateContext) -> dict[str, GateResult]:
    """跑全部 15 道门，返回 `{门号: GateResult}`。

    顺序：G1–G15；G13（对报告自身的检查）在其余各门跑完之后跑，
    于是它数的是这一轮真实产出的报告，而不是一个空集合。
    """
    out: dict[str, GateResult] = {}
    for gid in known_gate_ids():
        if gid == "G13":
            continue
        out[gid] = GATES[gid]["checker"](ctx)
    out["G13"] = gate_g13(ctx, out)
    return dict(sorted(out.items(), key=lambda kv: int(kv[0][1:])))


# ---------------------------------------------------------------- 报告


def gate_report(
    ctx: GateContext,
    *,
    own_errors: Sequence[str] | None,
    reviewer: str = "agent-H",
    round_no: int = 1,
) -> dict:
    """产出一份合规的审校报告数据结构（15 门齐全 + hash 钉住 + 自身错误一节）。

    三件事在这里被强制（缺一件就抛 `GatesReportError`）：

    1. 钉住被审版本 hash（G11）：报告头的 `revision_hash` 非空；
    2. 『我这一轮犯的错』一节（G15）：`own_errors` 是必填参数，
       不传（`None`）⇒ 抛。空列表是合法的（= 显式声明零错误），
       "没写"不是；
    3. 零发现自证（G13）：由 :class:`GateResult` 的结构强制 + G13 独立复核。

    `own_errors=None` 与 `own_errors=[]` 的区别就是三态纪律本身：
    前者是"这一节没写"（违法，退回），后者是"我写了、内容是『没有』"。
    """
    if own_errors is None:
        raise GatesReportError(
            "审校报告必须包含『我这一轮犯的错』一节（`own_errors` 必填）。"
            "传空列表表示『本轮零自身错误』—— 但**必须由调用方显式写出来**："
            "若允许『没写』等于『没犯错』，这一节就会永远空着（§8.4 G15：缺失则退回）"
        )
    ctx.own_errors = list(own_errors)
    if not ctx.revision_hash:
        raise GatesReportError(
            "报告必须钉住被审版本的内容 hash（§8.4 G11）：算不出 hash ⇒ 行号与结论都会失效"
        )
    results = run_all_gates(ctx)
    agg = gate_verdict(results)
    return {
        "ok": agg["verdict"] == "accepted" and not agg["failed_gates"] and not agg["unknown_gates"],
        "reviewer": reviewer,
        "round": int(round_no),
        "doc_id": str((ctx.doc or {}).get("doc_id") or "?"),
        # 报告头三件（G11/G15 + 自证）
        "revision_hash": ctx.revision_hash,
        "revision_hash_algo": CA.REVISION_HASH_ALGO,
        "gates_total": len(results),
        "gates": {g: r.to_dict() for g, r in results.items()},
        "verdict": agg,
        "own_errors": list(own_errors),
        # 自证数字：报告也要能回答"我扫了多少、数出了什么"（G13 的精神）
        "counts": {
            "断言数": len(ctx.claims()),
            "引用数": sum(len(c.get("citations") or []) for c in ctx.claims()),
            "依赖数": ("未提供（没查）" if ctx.dependencies is None else len(list(ctx.dependencies))),
            "发现数": ("未提供（没查）" if ctx.findings is None else len(list(ctx.findings))),
            "pass 门数": agg["pass"],
            "fail 门数": agg["fail"],
            "unknown 门数": agg["unknown"],
            "not_applicable 门数": agg["not_applicable"],
        },
    }


def render_review_report(report: Mapping[str, Any]) -> str:
    """把 :func:`gate_report` 的结果渲染成人可读的 markdown（H 的审校报告）。

    报告结构沿用 `draft/17` §8.1 的目录树建议（`reports/` 下按稿件代号命名），
    并强制包含三节：版本 hash（头）、15 门结论表、我这一轮犯的错。
    """
    gates: Mapping[str, Any] = report.get("gates") or {}
    agg: Mapping[str, Any] = report.get("verdict") or {}
    lines: list[str] = []
    lines.append(f"# 审校报告：doc:{report.get('doc_id')}")
    lines.append("")
    lines.append(f"- 审校者：`{report.get('reviewer')}`；轮次：{report.get('round')}")
    # 报告头三件之一：被审版本 hash（G11）
    lines.append(
        f"- **被审版本 hash**：`{report.get('revision_hash')}`"
        f"（算法：`{report.get('revision_hash_algo')}`）"
    )
    lines.append(
        f"- 总体结论：**`{agg.get('verdict')}`**"
        f"（pass={agg.get('pass')} / fail={agg.get('fail')} / "
        f"unknown={agg.get('unknown')} / not_applicable={agg.get('not_applicable')}，共 {report.get('gates_total')} 道门）"
    )
    lines.append(f"- 结论依据：{agg.get('reason')}")
    counts = report.get("counts") or {}
    lines.append("- 本轮自证数字：" + "、".join(f"{k}={v}" for k, v in counts.items()))
    lines.append("")

    # 报告头三件之二：我这一轮犯的错（G15）—— 放在头里，不许省
    lines.append("## 0. 我这一轮犯的错（缺失则退回）")
    lines.append("")
    own = list(report.get("own_errors") or [])
    if own:
        for i, e in enumerate(own, 1):
            lines.append(f"{i}. {e}")
    else:
        lines.append("（调用方**显式声明**本轮零自身错误。注意：这与「没写这一节」是两件事。）")
    lines.append("")

    lines.append("## 1. G1–G15 逐门结论")
    lines.append("")
    lines.append("| 门 | 名称 | 轴 | 结论 | 发现数 | 判据 |")
    lines.append("|---|---|---|---|---:|---|")
    for gid in GATE_IDS:
        r = gates.get(gid)
        if r is None:
            lines.append(f"| {gid} | **（缺失 —— 报告违规）** | - | - | - | - |")
            continue
        lines.append(
            f"| {gid} | {r.get('name')} | {r.get('axis')} | `{r.get('verdict')}` | "
            f"{r.get('finding_count')} | {(r.get('criterion') or '')[:40]} |"
        )
    lines.append("")

    lines.append("## 2. 逐门自证与发现")
    lines.append("")
    for gid in GATE_IDS:
        r = gates.get(gid)
        if r is None:
            continue
        lines.append(f"### {gid} {r.get('name')} —— `{r.get('verdict')}`")
        lines.append("")
        lines.append(f"- 轴：{r.get('axis')}；判据：{r.get('criterion')}")
        lines.append(f"- 判据状态：{r.get('criterion_revision')}")
        lines.append(f"- 结论理由：{r.get('reason')}")
        lines.append(f"- **自证**：{r.get('self_attestation') or '**（无 —— 违规）**'}")
        lines.append(f"- 用到的证据：{'、'.join(r.get('evidence_used') or []) or '-'}")
        fs = r.get("findings") or []
        if fs:
            lines.append("")
            lines.append("| 严重度 | 目标 | 说明 | 证据 |")
            lines.append("|---|---|---|---|")
            for f in fs:
                lines.append(
                    f"| {f.get('severity')} | `{f.get('target')}` | "
                    f"{str(f.get('message') or '')[:60]} | {str(f.get('evidence') or '')[:110]} |"
                )
        lines.append("")

    lines.append("## 3. 判不了的门（**不许读成『没问题』**）")
    lines.append("")
    unknown = list(agg.get("unknown_gates") or [])
    na = list(agg.get("not_applicable_gates") or [])
    if unknown:
        for gid in unknown:
            lines.append(f"- `{gid}` **没查成**：{(gates.get(gid) or {}).get('reason')}")
    else:
        lines.append("- （本轮没有 unknown 的门）")
    for gid in na:
        lines.append(f"- `{gid}` 无对象可判：{(gates.get(gid) or {}).get('reason')}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _json_safe(obj: Any) -> Any:
    """把结果里的非 JSON 类型（Path 等）转成字符串，供 `json.dumps` 用。"""
    if isinstance(obj, Mapping):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def report_as_json(report: Mapping[str, Any]) -> str:
    """报告的 JSON 形态（落盘/机读用；与 markdown 报告是同一份数据）。"""
    return json.dumps(_json_safe(report), ensure_ascii=False, indent=2, sort_keys=True, default=str)


# 门实现函数与声明表的一致性：声明表里写的 checker 必须真的是本模块的顶层函数。
for _gid, _spec in GATES.items():
    _fn = _spec.get("checker")
    if _fn is None or not callable(_fn):
        raise AssertionError(f"GATES[{_gid!r}] 没有可调用的 checker（声明表与实现漂移）")
    if _gid not in GATE_CRITERIA_REVISION:
        raise AssertionError(
            f"GATES[{_gid!r}] 没有登记判据修订状态（GATE_CRITERIA_REVISION）—— "
            "适配过的判据必须显式登记，否则『15 道门都在跑』会掩盖『跑的是改写过的判据』"
        )
del _gid, _spec, _fn

if set(GATES) != set(GATE_IDS):  # pragma: no cover - 导入期自检，写错就炸
    raise AssertionError(
        f"G1–G15 必须齐全：声明表 {sorted(GATES)} vs 规格 {list(GATE_IDS)}。"
        "删门会让『15 道门都在跑』变成假话"
    )


#: `Callable` 的用途标注（类型别名），供 `checker` 字段的读者参考。
GateChecker = Callable[[GateContext], GateResult]
