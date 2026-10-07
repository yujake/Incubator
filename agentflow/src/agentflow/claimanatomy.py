"""断言解剖学 —— `documents.claims` 每个元素的唯一判据来源。

## [为什么] 这个模块为什么存在

一份数学稿件的可信度，取决于每一条断言能不能被单独解剖：
它是定义还是定理、它当前处于什么生命周期、它的证明在哪里、
它背后有没有数值证据、有没有被作废、允许被用在哪一层。

本项目此前把这件事散在两处：
`schema.Document.validate()`（写入期硬拦）与 `tools/doc_tools.scan_claim`（构造期检查），
而 H 侧又另抄了一份（`tools/review_tools.scan_document`）—— 三处判据必然漂移，
漂移的形态是"G 认为合规、H 认为通过"，没有任何报错。

本模块把这张"字段 → 规格"的表做成一份声明表（:data:`CLAIM_FIELDS`），
G 与 H 都调它。新增第二个实现 = 违反 FC-03。

规格出处：`draft/17-正式文稿体例（参考投影度量论）.md` §8.3（第 1021–1052 行）
给出"一条断言应有的 12 个字段"。本模块逐条落地它，并保留我们已有的
`citations` / `evidence_kind` / `is_negative` / `negation_kind` / `disclaimer`
（参考体例里没有这五个，但它们是我们三条 FC 的落地形态，不许为了对齐那张表而删）。

## [为什么] `statement` 与 `text`：为什么保留 `statement`，并让 `text` 成为它的别名

§8.3 的字段名是 `statement`，而我们的磁盘上、`schema.py`（禁 AI 区）、
既有测试与历史数据里一律叫 `text`。两者是同一件事，
所以只能留一条字段名，否则 `{"text": A, "statement": B}` 可以同时存在 ——
下游读 `text` 的（`schema.Document.validate`、渲染层、verify）与读 `statement` 的
（新代码）会看到两个不同的断言，而没有任何地方会报错。这正是 FC-03 的形态。

二选一，选 `statement`，理由两条：
1. 规格逐字要求的是 `statement`（§8.3 那张表是本任务的规格来源）；
2. 别名方向必须是"旧名 → 新名"，这样磁盘上的老行仍然能读（见下）。

迁移路径（不是两套字段名，是一处转换）：:func:`migrate_claim` 会把
`text` 归一成 `statement` 并删掉 `text` 键 —— 全项目只有这一处做这件事，
其余地方（`doc_tools` 的构造/落库/渲染、`review_tools` 的检查）不再碰 `text`。
读一条断言时永远用 :func:`claim_statement`（它同时认得两种键，给历史数据用）。

但落库那一层仍然是 `text`：`schema.Document.validate` 是禁 AI 区里的
FC-27 条目，本任务不许编辑它，它逐字检查 `c.get("text")`。
所以 `doc_tools` 在写入前把 `statement` 退回成 `text`（:func:`to_storage_claim`），
读取后再归一。这条往返由 `tests/test_claimanatomy.py` 的逐字断言钉住。

## [契约] `status` 与 `evidence_kind` 是两个正交的轴（本模块的核心设计点）

```text
evidence_kind ∈ {proof, cross_check, heuristic}   支撑它的证据是哪一类
status        ∈ {证, 验, 待精化, 作废}             它当前处于什么生命周期
```

`作废`（retracted）不是一种证据：它是"一条曾经存在的断言被撤销了"。
本框架此前表达不了这件事（`schema.py` 里 0 处 `retracted`），
这正是参考体例里 `❌作废` 是常规状态、而我们的模型缺的那一格。

因此本模块显式允许两者自由组合（13 种组合都能写），只把已知的不一致组合
写成可判定的门（:func:`status_evidence_consistency`）：

| 组合 | 判定 |
|---|---|
| `status=验` + `evidence_kind=proof` | 不一致（`proof` 级证据下的断言不该只标"验"） |
| `status=作废` 且既无 `errata_ids` 又无 `freeze_reason` | 不一致（作废必须有原因） |
| `status=证` + `evidence_kind != proof` | 不一致（"证"必须有 `proof` 级证据，FC-22） |
| 其余组合 | 一致 |
| 任一轴缺失 / 取值非法 | 未知（第三态，附 `reason`）—— 不猜 |

最后一行是三态纪律的落点（`DEVELOPMENT.md` §3 纪律 1）：
"字段缺失"与"字段存在但非法"与"检查器自己没跑成"必须能分开。

## [契约] 与 `schema.py` 的关系（本模块不替代它）

`schema.Document.validate` 仍是写入期最后一道闸，本模块是构造期/审校期的
同一份判据。两者的硬约束（无引用 / `cross_check` 缺 disclaimer / 否定未分类）
必须一致，`tests/test_claimanatomy.py` 有一组双向对照用例钉住这一点。

`status` / `kind` / `allowed_use` 这些受控词表的真身按 `DEVELOPMENT.md` §2.3
已经是 `schema.py`（唯一来源）：2026-10-07 所有者裁定 `draft/68` 题 2 选 B，
本次改动由所有者授权、主控代改，六张词表（`CLAIM_KINDS` / `CLAIM_STATUSES` /
`ALLOWED_USE_KINDS` / `NUMERIC_EVIDENCE_KEYS` / `CLAIM_SOURCE_KINDS` /
`CLAIM_CHECK_KINDS`）从本模块搬进 `schema.py`，本模块只 import。
留在本模块的是它们的使用方式（`CLAIM_FIELDS` 与派生的别名/家族表）与判据本身 ——
搬的是真身词表，不是判据表。两侧是同一个对象（`is`），不是两份同值拷贝。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ALLOWED_USE_KINDS",
    "CLAIM_FIELDS",
    "CLAIM_KINDS",
    "CLAIM_STATUSES",
    "CONSISTENT",
    "CONSISTENCY_UNKNOWN",
    "DECIDED_INCONSISTENT",
    "ClaimIssue",
    "ClaimSpec",
    "FieldSpec",
    "claim_content_hash",
    "claim_statement",
    "consolidate_issues",
    "count_by_code",
    "has_issue",
    "is_retracted",
    "lifecycle_verdict",
    "main_body_claims",
    "migrate_claim",
    "new_field_names",
    "optional_field_names",
    "presence_of",
    "required_field_names",
    "retracted_claims",
    "revision_hash",
    "status_evidence_consistency",
    "summary_counts",
    "to_storage_claim",
    "validate_claim",
    "validate_document_claims",
]

# ---------------------------------------------------------------- 受控词表（真身在 schema）
#
# 六张角色语义词表的真身现在在 `schema.py`（`DEVELOPMENT.md` §2.3 要的落点）。
# 2026-10-07 所有者裁定 `draft/68` 题 2 选 B，本次改动由所有者授权、主控代改。
# 这里只 import，不再留第二份字面量 —— 于是下面这些名字与本模块的
# `CLAIM_FIELDS[*].domain` 指向的是同一个对象（`is`，不是相等）。
#
# 为什么可以是模块级 import 而不是 `_evidence_kinds()` 那种惰性转发：
# `import agentflow.claimanatomy` 一定会先执行包 `__init__`，而它 import 了
# `interactions`（`CONTRACT_VERSION`），后者又 import `schema` 与 `store` ——
# 实测 `import agentflow.claimanatomy` 之后 `agentflow.schema` 与
# `agentflow.store` 都已在 `sys.modules` 里。所以"惰性"在这一层省不下任何东西，
# 反而需要一份同值兜底（那就是第二份字面量）。`schema` 不 import 本模块，无环。
from .schema import (  # noqa: E402 - 见上：位置放在词表这一节，不搬到文件顶部
    ALLOWED_USE_KINDS,
    CLAIM_CHECK_KINDS,
    CLAIM_KINDS,
    CLAIM_SOURCE_KINDS,
    CLAIM_STATUSES,
    NUMERIC_EVIDENCE_KEYS,
)

#: `evidence_kind` 的受控词表另一处在 `schema.EVIDENCE_KINDS`。
#: 这里不复制一份字面量 —— 见 `_evidence_kinds()`（惰性转发，理由是 FC-03）。
_EVIDENCE_KIND_FALLBACK = ("proof", "cross_check", "heuristic")


def _evidence_kinds() -> tuple[str, ...]:
    """`evidence_kind` 的受控词表，从 `schema.py` 取（唯一来源）。

    为什么用惰性转发而不是模块级 import：`import agentflow.schema` 会触发
    整张 schema 模块的导入期自检；而本模块是纯判据层，单测与文档生成
    应当能在不加载存储层的前提下 import 它。

    兜底值只在"schema 真的读不到"时生效，且与 schema 的字面量逐字相同 ——
    不一致会被 `tests/test_claimanatomy.py::test_evidence_kinds_are_not_a_second_copy`
    抓出来（那条测试断言两边是同一个对象）。
    """
    try:
        from . import schema as S

        return tuple(S.EVIDENCE_KINDS)
    except Exception:  # noqa: BLE001 - 见下：拿不到 schema 时用同值兜底，且不静默
        # 为什么可以忽略：这是纯判据层在"schema 不可导入"这一种环境下的
        # 降级路径（例如文档生成脚本只装了一半）。兜底值与 schema 逐字相同，
        # 且有测试断言"两者是同一个对象"——所以这里的降级不会造成两个词表。
        return _EVIDENCE_KIND_FALLBACK


#: 三态判定的三个取值。第三态不是一个错误，而是"判不了"这个事实本身。
CONSISTENT = "一致"
DECIDED_INCONSISTENT = "不一致"
CONSISTENCY_UNKNOWN = "未知"


# ---------------------------------------------------------------- 字段规格表


@dataclass(frozen=True)
class FieldSpec:
    """一个 claim 字段的规格。

    为什么 `why` 与 `source` 是必填而不是注释：`DEVELOPMENT.md` 的写作纪律是
    "每一个数字都有出处"。一张判据表若说不出"这个字段为什么存在、出处是哪一行"，
    它就会在下一轮重构里被当成可选项删掉。
    """

    name: str
    type_desc: str
    required: bool
    #: 取值域（`None` = 自由文本 / 无受控词表）。
    domain: tuple[str, ...] | None
    #: 为什么需要这个字段（不是复述类型，而是取舍）。
    why: str
    #: 出处（`文件:行号` 或权威条目）。
    source: str
    #: 是否由 `draft/17` §8.3 新增（False = 本框架既有字段，必须保留）。
    from_reference: bool
    #: 是否允许为 `None` / 空（可空字段）。
    nullable: bool = True
    #: 同义键名（归一化时被合并掉的旧名）。
    aliases: tuple[str, ...] = ()


#: 一份断言字段规格表。G 与 H 共调它；文档生成与 CLI 也读它。
#:
#: `required=True` 的口径刻意保守：只列 `schema.Document.validate()`
#: 已经在硬拦的字段。§8.3 新增的 9 个字段一律 `required=False` ——
#: 理由是磁盘上已有大量老 claim 行没有它们，把它们设成必填会让
#: 全部历史稿件立刻变成非法（而 `schema.py` 是禁改区，我们无法同步迁移）。
#: 它们由 `new_field_names()` 单列，由门（`gates.G10`）报 `warning` 提醒补齐。
CLAIM_FIELDS: dict[str, FieldSpec] = {
    # ---------------- §8.3 的 12 个字段 ----------------
    "claim_id": FieldSpec(
        name="claim_id",
        type_desc="str（唯一、稳定）",
        required=True,
        domain=None,
        why=(
            "断言在稿件内的唯一定位符。**必须稳定**：勘误里出现过"
            "「定理 3.4→3.3 五处」这类重编号事故，编号一漂，"
            "所有引用它的审校发现与依赖行同时失效。"
        ),
        source="draft/17 §8.3 第 1027 行；schema.py:1070（写入期硬拦）",
        from_reference=True,
        nullable=False,
    ),
    "kind": FieldSpec(
        name="kind",
        type_desc=f"enum（{'/'.join(CLAIM_KINDS)}）",
        required=False,
        domain=CLAIM_KINDS,
        why=(
            "数学对象的类型。检查脚本靠这个前缀建索引，编号规则是「按类型内连续」；"
            "没有它就无法回答「这份稿子里有几条定理」这类**必须一致**的计数。"
        ),
        source="draft/17 §8.3 第 1028 行",
        from_reference=True,
    ),
    "statement": FieldSpec(
        name="statement",
        type_desc="str（非空）",
        required=True,
        domain=None,
        why=(
            "断言正文。**这是 `text` 的正名**：两者是同一件事，只留一条字段名，"
            "否则 `text=A, statement=B` 能让下游看到两个不同的断言而无人报错。"
            "选 `statement` 的理由与迁移路径见模块 docstring。"
        ),
        source="draft/17 §8.3 第 1029 行；本框架既有键名为 `text`",
        from_reference=True,
        nullable=False,
        aliases=("text",),
    ),
    "status": FieldSpec(
        name="status",
        type_desc=f"enum（{'/'.join(CLAIM_STATUSES)}）",
        required=False,
        domain=CLAIM_STATUSES,
        why=(
            "**生命周期**轴，与 `evidence_kind`（**证据类型**轴）正交。"
            "`作废` 不是一种证据，而是「这条断言被撤销了」——"
            "本框架此前表达不了这件事，缺了它，「作废的断言仍被当有效结论引用」"
            "在数据模型里**不可见**。"
        ),
        source="draft/17 §8.3 第 1030 行（U0:6/16/160 的确切取值集合）",
        from_reference=True,
    ),
    "proof_location": FieldSpec(
        name="proof_location",
        type_desc="`file:line` 或 `claim_id`",
        required=False,
        domain=None,
        why=(
            "证明在哪。参考体例用「见 H2.3」「(H2.4)」这种**自由文本**表达，"
            "于是「这条断言到底有没有证明」无法机械回答 —— 这是我们该结构化的第一处。"
        ),
        source="draft/17 §8.3 第 1031 行",
        from_reference=True,
    ),
    "numeric_evidence": FieldSpec(
        name="numeric_evidence",
        type_desc=f"{{{', '.join(NUMERIC_EVIDENCE_KEYS)}}}",
        required=False,
        domain=None,
        why=(
            "行内 `[验](256 组, d≤33, 零反例)` 已经是这个四元组。"
            "**四键缺一不可**：没有 `script` 就无法复跑，没有 `range` 就不知道覆盖了什么，"
            "没有 `n_cases`/`n_counterexamples` 就无法把「零反例」与「没查」分开。"
        ),
        source="draft/17 §8.3 第 1032 行",
        from_reference=True,
    ),
    "counterexamples": FieldSpec(
        name="counterexamples",
        type_desc="list",
        required=False,
        domain=None,
        why=(
            "反例清单。参考体例里它是**单独一节**（U0 §二）—— "
            "反例不是脚注，它改变结论的适用范围。"
        ),
        source="draft/17 §8.3 第 1033 行",
        from_reference=True,
    ),
    "frozen": FieldSpec(
        name="frozen",
        type_desc="bool",
        required=False,
        domain=None,
        why=(
            "「结论可用、证明留痕、不再投入」。它必须与 `freeze_reason` 成对："
            "只标冻结不说原因，接手的人无从判断该不该解冻。"
        ),
        source="draft/17 §8.3 第 1034 行",
        from_reference=True,
        nullable=False,
    ),
    "freeze_reason": FieldSpec(
        name="freeze_reason",
        type_desc="str",
        required=False,
        domain=None,
        why=(
            "`frozen=True` 时**必填**（理由是「连败 N 次」这类可核查的事实）。"
            "它同时是 `status=作废` 的合法原因之一。"
        ),
        source="draft/17 §8.3 第 1034 行",
        from_reference=True,
    ),
    "allowed_use": FieldSpec(
        name="allowed_use",
        type_desc=f"enum（{'/'.join(ALLOWED_USE_KINDS)}）",
        required=False,
        domain=ALLOWED_USE_KINDS,
        why=(
            "论文线的**硬性降级规则**：只有数值支撑的结论不得出现在摘要/主结果，"
            "必须降为 Remark + 命令。本框架此前只有「自动附加免责声明」这一层保障，"
            "`allowed_use` 0 命中（见 docs/ROLE-SPECS.md §G.3）。"
        ),
        source="draft/17 §8.3 第 1035 行；RP/00_STANDARD.md:105-110",
        from_reference=True,
    ),
    "scope_caveat": FieldSpec(
        name="scope_caveat",
        type_desc="str（可空）",
        required=False,
        domain=None,
        why=(
            "装「只是交叉验证」这类**限定语**（如「仅限有限阶 θ，不构成存在性否定证据」）。"
            "把它放在结构化字段里而不是正文里，它才能被门（G14）读到。"
        ),
        source="draft/17 §8.3 第 1036 行",
        from_reference=True,
    ),
    "revision_hash": FieldSpec(
        name="revision_hash",
        type_desc="str",
        required=False,
        domain=None,
        why=(
            "审稿报告必须**钉住被审版本 hash**，否则行号失效 —— "
            "参考体例的 FIX_PROTOCOL 把「审校期间不改文件」写成硬纪律，"
            "而它可执行的前提就是有这么一串字节。"
        ),
        source="draft/17 §8.3 第 1037 行；STYLE/RUBRIC.md:113",
        from_reference=True,
    ),
    "errata_ids": FieldSpec(
        name="errata_ids",
        type_desc="list",
        required=False,
        domain=None,
        why=(
            "用**稳定 ID** 指勘误（`V10-X1` / `E-01`），而不是「附四…附十」这种"
            "会跳跃的编号。它同时是 `status=作废` 的合法原因之一。"
        ),
        source="draft/17 §8.3 第 1038 行；V10/README.md:122-128",
        from_reference=True,
    ),
    # ---------------- 本框架既有字段（参考体例里没有，必须保留） ----------------
    "citations": FieldSpec(
        name="citations",
        type_desc="list[str]（非空）",
        required=True,
        domain=None,
        why=(
            "**没有引用的断言不允许进入稿件**（FC-02）。数学断言的价值完全取决于"
            "它来自哪里；`schema.py:1079` 是硬拦。参考体例里没有这个字段 —— "
            "但删掉它等于把本框架最硬的一条闸拆掉。"
        ),
        source="本框架既有（schema.py:1078-1086）；FC-02",
        from_reference=False,
        nullable=False,
    ),
    "evidence_kind": FieldSpec(
        name="evidence_kind",
        type_desc=f"enum（{'/'.join(_EVIDENCE_KIND_FALLBACK)}）",
        required=True,
        domain=_EVIDENCE_KIND_FALLBACK,
        why=(
            "**证据类型**轴（FC-22）：`proof` 只能是形式化检查器的产出，"
            "计算类方法拿不到 `proof`。与 `status` **正交**，不是同一件事。"
        ),
        source="本框架既有（schema.py:651 EVIDENCE_KINDS）",
        from_reference=False,
        nullable=False,
    ),
    "is_negative": FieldSpec(
        name="is_negative",
        type_desc="bool",
        required=True,
        domain=None,
        why=(
            "`True` 时必须给 `negation_kind`：**「未证明」与「已证否」是两件事**（FC-25）。"
        ),
        source="本框架既有（schema.py:1097-1106）",
        from_reference=False,
        nullable=False,
    ),
    "negation_kind": FieldSpec(
        name="negation_kind",
        type_desc="enum（四类否定）或 None",
        required=False,
        domain=None,
        why=(
            "四类否定必须分开列：「未证明」/「已证否」/「未搜索」/「无本地证据」。"
            "合并计数会让人把「没搜过」读成「已证否」。词表在 `schema.NEGATION_KINDS`。"
        ),
        source="本框架既有（schema.py:665 NEGATION_KINDS）",
        from_reference=False,
    ),
    "disclaimer": FieldSpec(
        name="disclaimer",
        type_desc="str",
        required=False,
        domain=None,
        why=(
            "`cross_check` 断言**必须**自带「数值交叉验证，不构成证明」——"
            "这句话由结构强制，**不靠人记得写**（FC-22）。"
        ),
        source="本框架既有（schema.py:1091-1095；doc_tools.CROSS_CHECK_DISCLAIMER）",
        from_reference=False,
    ),
    "section": FieldSpec(
        name="section",
        type_desc="str",
        required=True,
        domain=None,
        why="章节归属。审校要求「每条发现必须能定位到行/节」，没有它就只剩一句泛泛的描述。",
        source="本框架既有（doc_tools.compose_claim 的必填参数）",
        from_reference=False,
        nullable=False,
    ),
    # ---------------- 断言台账的四列 + 两列出处（`draft/31` P3 / `draft/30` §T3-P3）
    #
    # 这六列此前是"断言里多出来的键"：`undeclared_field` 把它们逐条报成 warning，
    # 而那条 warning 的原文恰恰是「未声明的字段无法被门读到」——
    # 也就是说台账里的「来源 / 我方核到什么程度 / 能否证伪」落了库、却没有任何判据。
    # [踩过] 实测 2026-09-29（P3 首次派 H 审台账）：24 行台账被审出 240 条
    # `undeclared_field`（10 个自有键 × 24 条），error=0 而 warning 全是这一件事。
    # 处置是把它们变成声明的字段：取值域受控、类型受判，G 与 H 读的是同一份判据；
    # 而"这份台账的列"从此也进了 `known_field_names()`，"多出来的键"重新变成异常信号。
    "source_kind": FieldSpec(
        name="source_kind",
        type_desc=f"enum（{'/'.join(CLAIM_SOURCE_KINDS)}）",
        required=False,
        domain=CLAIM_SOURCE_KINDS,
        why=(
            "这条断言是自证的、引自文献的、还是来源至今未决的。"
            "三档合并计数会让人把「未决」读成「已核实」，"
            "也会让「我们自己算的」与「某篇文献说的」在计数上无法区分。"
        ),
        source="draft/31 P3（台账的「来源」列）；draft/30 §T3-P3",
        from_reference=False,
    ),
    "our_check": FieldSpec(
        name="our_check",
        type_desc=f"enum（{'/'.join(CLAIM_CHECK_KINDS)}）",
        required=False,
        domain=CLAIM_CHECK_KINDS,
        why=(
            "我方核到了哪一档。这一列的用途是防夸大："
            "把「只读了陈述」如实写出来，比把它省略掉更有价值 —— "
            "省略之后，一条没核过的断言与一条数值核过的断言在表里长得一模一样。"
        ),
        source="draft/31 P3（台账的「我方核到什么程度」列）；draft/30 §T3-P3",
        from_reference=False,
    ),
    "our_check_note": FieldSpec(
        name="our_check_note",
        type_desc="str",
        required=False,
        domain=None,
        why=(
            "`our_check` 那一档的依据：跑了哪个脚本、覆盖多大、核到了什么。"
            "与 `falsifiable_note` 分开：『我们核过它』与『我们试图推翻它』"
            "是两件不同的工作，合成一列之后，一条只被正面核对过的断言"
            "会看起来像一条被反例搜索过的断言。"
        ),
        source="draft/31 P3（台账的「我方核到什么程度」列）；draft/30 §T3-P3",
        from_reference=False,
    ),
    "falsifiable": FieldSpec(
        name="falsifiable",
        type_desc="bool",
        required=False,
        domain=None,
        why=(
            "这条断言能不能被证伪。`True` 是一个承诺：反例搜索的脚本与覆盖范围"
            "必须写在 `falsifiable_note` 里（「找不到反例」与「没找过」不许混）。"
            "`False` 也要说清为什么 —— 例如「它是外部定理，不是本文要证的」。"
        ),
        source="draft/31 P3（台账的「能否证伪」列）；draft/29 §11「找不到反例不许写 proof」",
        from_reference=False,
    ),
    "falsifiable_note": FieldSpec(
        name="falsifiable_note",
        type_desc="str",
        required=False,
        domain=None,
        why=(
            "`falsifiable` 那一格的依据：搜过什么、范围多大、有没有找到反例。"
            "单独一列而不是塞进 `statement`：反例搜索的记录属于我方工作，"
            "写进断言正文就会与「论文说了什么」混在一起。"
        ),
        source="draft/31 P3（同上）；draft/30 §T3-P3",
        from_reference=False,
    ),
    "paper_ref": FieldSpec(
        name="paper_ref",
        type_desc="str（`相对路径:行号#标签`）",
        required=False,
        domain=None,
        why=(
            "这条断言在被审论文里的定位，例如 `source/main.tex:211#prop:step`。"
            "`claim_id` 是我们起的名，论文里并没有这个字符串 ——"
            "没有这一列，接手的人只能靠猜把台账的每一行对回论文的哪一段。"
        ),
        source="draft/31 P3（台账逐条对应 `main.tex` 的定理类环境）",
        from_reference=False,
    ),
    "paper_excerpt": FieldSpec(
        name="paper_excerpt",
        type_desc="str（逐字原文片段）",
        required=False,
        domain=None,
        why=(
            "论文该环境的逐字原文。刻意不放进 `statement`：论文自己会用"
            "「we prove」「is proved」这类措辞，而台账给同一环境的证据等级往往是"
            "`cross_check` —— 把原话抄进正文，会让过度声称检查对着论文的措辞报警，"
            "或者诱使作者为了过检而删掉原话。原文留在这里、正文写我方转述，"
            "忠实与不过度声称两件事同时成立。"
        ),
        source="draft/30 §T3-P3（「原文照留、转述入正文」这一条）",
        from_reference=False,
    ),
}

#: `text` 键的正名。写成常量是为了让"哪个名字是权威"只有一处定义。
STATEMENT_KEY = "statement"

#: 历史键名 → 正名。只有一处做这个映射。
_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: name for name, spec in CLAIM_FIELDS.items() for alias in spec.aliases
}


# ---------------------------------------------------------------- 字段名查询


def required_field_names() -> tuple[str, ...]:
    """必填字段名（`schema.Document.validate()` 已经在硬拦的那些）。

    为什么这个划分是保守的：§8.3 新增的 9 个字段不在这里。它们不是不重要，
    而是磁盘上已有大量老行没有它们；把它们设成必填会让全部历史稿件立刻非法，
    而"让历史数据非法"与"让新数据合规"是两件事，不该用同一个开关。
    新增字段由 :func:`new_field_names` 单列，由 `gates.G10` 报 warning 提醒补齐。
    """
    return tuple(sorted(n for n, s in CLAIM_FIELDS.items() if s.required))


def optional_field_names() -> tuple[str, ...]:
    """可选字段名（含 §8.3 新增的全部字段）。"""
    return tuple(sorted(n for n, s in CLAIM_FIELDS.items() if not s.required))


def new_field_names() -> tuple[str, ...]:
    """由 `draft/17` §8.3 新增、而本框架此前没有的字段名。"""
    return tuple(sorted(n for n, s in CLAIM_FIELDS.items() if s.from_reference and not s.required))


def known_field_names() -> tuple[str, ...]:
    """全部已知字段名（含别名）。用于"未知键"这类可判定检查。"""
    return tuple(sorted(set(CLAIM_FIELDS) | set(_ALIAS_TO_CANONICAL)))


# ---------------------------------------------------------------- 判定结果


@dataclass(frozen=True)
class ClaimIssue:
    """一条关于某条断言的判定结果。

    `code` 是机器可读的，`message` 是给人读的，`evidence` 必须写触发它的实际值
    （`schema.ReviewFinding.evidence` 的同类纪律：只写"看起来不对"的发现，
    会让审校变成另一种幻觉的来源）。

    `code` 受控（`DEVELOPMENT.md` §6 的禁止形态之一是"隐含的判据无法被审阅"）；
    每条 code 还归入 `draft/39` §3.8 的 8 族之一（`CLAIM_FAMILY_BY_CODE`），
    拒信按族号报错（见 `family_note`）：

    ================================  =======  ==========================================
    code                                族      含义
    ================================  =======  ==========================================
    `missing_field`                     1       必填字段缺失（或为空）
    `empty_required`                    1       `frozen=True` 但 `freeze_reason` 为空这类"成对字段"缺失
    `undeclared_field`                  1       出现了不在 `CLAIM_FIELDS` 里的键
    `bad_enum`                          2       字段存在，取值不在受控词表里
    `bad_type`                          2       字段存在，类型不对（如 `frozen="yes"`）
    `inconsistent_status`               3       `status` 与 `evidence_kind` 的已知不一致组合
    `unknown_status_axis`               3       判不了（缺字段 / 取值非法）—— 第三态，不是违规
    `lifecycle_incomplete`              4       `frozen`/`is_negative`/`作废` 的生命周期不闭合
    `missing_disclaimer`                5       `cross_check` 缺那句"不构成证明"声明
    `overclaim`                         6       证据等级 < proof 却用了"证明/定理/必然"这类词
    `incomplete_numeric_evidence`       7       `numeric_evidence` 四元组缺键
    `duplicate_claim_id`                8       同一稿件里代号重复
    `checker_error`                     0       检查器自己没跑成（异常被捕获并如实登记）
    ================================  =======  ==========================================
    """

    code: str
    field_name: str
    level: str  # error | warning | info
    message: str
    evidence: str = ""
    claim_id: str = ""

    @property
    def family(self) -> int:
        """这一条属于 `draft/39` §3.8 的哪一族（`0` = 还没有族号，不是"第 8 族"）。

        族号由 `code` 一处派生（`family_of`）：拒信要点名族号 + 该族正例，
        而"这条判据属于哪一族"是判据自身的属性，不该由每个报错点各自记一遍。
        """
        return family_of(self.code)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "family": self.family,
            "field": self.field_name,
            "level": self.level,
            "message": self.message,
            "evidence": self.evidence,
            "claim_id": self.claim_id,
        }


#: `draft/39` §3.8 的 8 族（用户裁定：拒信一律点名族号 + 违反的那一条 + 该族正例）。
#:
#: 每一族三项：`name`（人话名字）、`rule`（这一族判什么）、`example`（正例 ——
#: 给模型看的"照这个写"）。为什么正例是判据的一部分：只说"你这不对"时，模型下一句
#: 往往是整条重写（结论随之漂移），而这里要救的通常只是一栏。
CLAIM_FAMILIES: dict[int, dict[str, str]] = {
    1: {"name": "字段存在性",
        "rule": "`CLAIM_FIELDS` 里的必填项要在、且非空（三态：present/empty/absent）",
        "example": '{"claim_id": "c1", "statement": "…", "kind": "定理", "citations": ["exp:0002"]}'},
    2: {"name": "受控词表",
        "rule": "`kind`/`status`/`source`/`our_check`/`allowed_use` 的取值必须在各自的词表里，"
                "且类型要对（`frozen` 是布尔、`numeric_evidence` 是对象）",
        "example": '{"kind": "引理", "status": "证", "source": "自证", "our_check": "证明"}'},
    3: {"name": "status × evidence_kind 交叉",
        "rule": "`status=\"证\"` 必须 `evidence_kind=\"proof\"`；不是 proof 就不许自称「证」",
        "example": '{"status": "证", "evidence_kind": "proof"} 或 {"status": "验", "evidence_kind": "cross_check"}'},
    4: {"name": "生命周期自洽",
        "rule": "`frozen` ⇒ 必须有 `freeze_reason`；`is_negative` ⇒ 必须有 `negation_kind`；"
                "`status=\"作废\"` ⇒ 必须有 `errata_ids` 或 `freeze_reason`",
        "example": '{"status": "作废", "errata_ids": ["e-0007"]} 或 {"frozen": true, "freeze_reason": "结论保留、不再投入"}'},
    5: {"name": "cross_check 的免责声明",
        "rule": "`evidence_kind=\"cross_check\"` 的断言必须自带那句「数值交叉验证，不构成证明」"
                "（写在独立的 `disclaimer` 一栏里）",
        "example": '{"evidence_kind": "cross_check", "disclaimer": "数值交叉验证，不构成证明"}'},
    6: {"name": "过度声称词表",
        "rule": "证据等级不是 proof 时，正文里不许出现「证明/定理/必然」这类词",
        "example": '证据是 cross_check 时正文写「数值上支持（未证明）」而不是「证明了」'},
    7: {"name": "数值证据结构",
        "rule": f"`numeric_evidence` 要有 {NUMERIC_EVIDENCE_KEYS} 四项（缺一即不可复跑/不可判定覆盖）",
        "example": '{"numeric_evidence": {"script": "code/scan.py", "range": "n<=12", "n_cases": 262, "n_counterexamples": 0}}'},
    8: {"name": "稿件级（代号与逐条汇总）",
        "rule": "同一稿件里 `claim_id` 不许重复；逐条问题要汇总成 error/warning",
        "example": "`claim_id` 由脚本按顺序发（claim-1…claim-N），模型不要自己编号"},
}

#: 一个 `code` 属于哪一族（未登记的 code ⇒ `0` = 「还没有族号」，不是"第 8 族"）。
#:
#: 为什么按 code 而不是按报错点：报错点有十几处，各记一遍必然漂移；而"这一族叫什么"
#: 只有一处。歧义的两处（同形不同义）已各自独立成 code：`missing_disclaimer`（第 5 族）、
#: `overclaim`（第 6 族）、`incomplete_numeric_evidence`（第 7 族）、`lifecycle_incomplete`（第 4 族）。
CLAIM_FAMILY_BY_CODE: dict[str, int] = {
    "missing_field": 1, "empty_required": 1, "undeclared_field": 1,
    "bad_enum": 2, "bad_type": 2,
    "inconsistent_status": 3, "unknown_status_axis": 3,
    "lifecycle_incomplete": 4,
    "missing_disclaimer": 5,
    "overclaim": 6,
    "incomplete_numeric_evidence": 7,
    "duplicate_claim_id": 8,
}


def family_of(code: str) -> int:
    """这一条 issue 的族号（`0` = 还没登记族号 —— 三态，不是"第 8 族"）。"""
    return int(CLAIM_FAMILY_BY_CODE.get(str(code or ""), 0))


def family_note(code: str, *, with_example: bool = True) -> str:
    """拒信里那一段：`族 N（名字）：判什么` ＋ `正例：…`（`draft/39` §3.11 四）。"""
    fam = family_of(code)
    if not fam or fam not in CLAIM_FAMILIES:
        return f"（这一条还没有族号：code={code} —— 请按 message 里那一条改）"
    info = CLAIM_FAMILIES[fam]
    text = f"族 {fam}（{info['name']}）：{info['rule']}"
    if with_example:
        text += f"；正例：{info['example']}"
    return text


#: 判定"这条断言的三态轴判不判得了"时用的键。
_AXIS_KEYS = ("status", "evidence_kind")


@dataclass
class ClaimSpec:
    """`validate_claim` 的结构化返回（供 H 的门与 CLI 读取）。

    三态纪律的落点在这里：:attr:`decided` 为 `False` 表示
    "检查器没判成"，此时 :attr:`undecided_reason` 必须非空 ——
    "没做"绝不折叠成"做了没问题"。
    """

    claim_id: str
    checked: bool
    decided: bool
    verdict: str = CONSISTENCY_UNKNOWN
    status_axis: str = CONSISTENCY_UNKNOWN
    undecided_reason: str = ""
    issues: list[ClaimIssue] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    #: 一致性门真正用到了哪些字段（门必须能说清自己看了什么）。
    fields_used: tuple[str, ...] = ()
    #: 被审断言的 `revision_hash`（空字符串 = 那条断言没钉 hash）。
    revision_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "checked": self.checked,
            "decided": self.decided,
            "verdict": self.verdict,
            "status_axis": self.status_axis,
            "undecided_reason": self.undecided_reason,
            "issues": [i.to_dict() for i in self.issues],
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "fields_used": list(self.fields_used),
            "revision_hash": self.revision_hash,
        }


# ---------------------------------------------------------------- 归一化 / 迁移


def claim_statement(claim: Mapping[str, Any]) -> str:
    """取一条断言的正文，同时认得 `statement` 与历史键 `text`。

    为什么读的时候要认两种键：磁盘上有历史行（`text`），而新代码写 `statement`。
    读点若不认旧键，历史稿件的正文会被读成空串 —— 而"空正文"在渲染层长得像
    "这条断言没写"。这是读取期的兼容，不是第二份字段名：
    写入期由 :func:`migrate_claim` 归一成唯一的 `statement`。
    """
    if not isinstance(claim, Mapping):
        return ""
    for key in (STATEMENT_KEY, *_ALIAS_TO_CANONICAL.get(STATEMENT_KEY, ())):
        val = claim.get(key)
        if val is not None and str(val).strip():
            return str(val)
    # 两个键都空/都没有：返回空串，由 `missing_field` 报出来（不在这里抛）。
    return str(claim.get(STATEMENT_KEY) or claim.get("text") or "")


def migrate_claim(claim: Mapping[str, Any]) -> dict:
    """把一条断言归一成唯一的字段名集合（`text` → `statement`）。

    全项目只有这一处做键名迁移（FC-03：同一个判据只能有一处实现）。

    行为：
    1. `statement` 缺失而 `text` 存在 ⇒ 取 `text` 的值写进 `statement`；
    2. 删掉 `text` 键（于是不可能出现"两个键说两句不同的话"）；
    3. 两个键都有且内容不同 ⇒ 抛 `ValueError`（不静默取其一：
       这正是"两个字段名"这种形态最危险的失效，必须炸出来）；
    4. 其余键原样保留（包括未知键 —— 未知键由 `validate_claim` 报，不在这里吞掉）。
    """
    if not isinstance(claim, Mapping):
        raise ValueError(f"claim 必须是对象，收到 {type(claim).__name__}")
    out = dict(claim)
    has_stmt = STATEMENT_KEY in out
    has_text = "text" in out
    if has_stmt and has_text:
        a = str(out.get(STATEMENT_KEY) or "")
        b = str(out.get("text") or "")
        if a.strip() != b.strip():
            raise ValueError(
                f"claim 同时给了 `{STATEMENT_KEY}` 与 `text` 且内容不同：{a[:60]!r} vs {b[:60]!r}。"
                f"`text` 是 `{STATEMENT_KEY}` 的历史别名，两者**只能有一条字段名** ——"
                "静默取其一，就等于让下游读到两个不同的断言而无人报错（FC-03）"
            )
        out.pop("text", None)
        return out
    if has_text:
        out[STATEMENT_KEY] = out.pop("text")
    return out


def to_storage_claim(claim: Mapping[str, Any]) -> dict:
    """把归一后的断言退回磁盘形态（`statement` → `text`）。

    ## 为什么必须退回（这是本模块唯一一处"往回走"）

    `schema.Document.validate` 逐字检查 `c.get("text")`，而它是 FC-27 禁 AI 区里的
    条目 —— 本任务不许编辑它。所以我们不能把 `statement` 直接写进磁盘：
    那样 `validate()` 会报"claims[i] 的 text 不能为空"，全部稿件无法落库。

    于是写入路径是：判据层用 `statement` → 落库前转回 `text` → 读出后
    :func:`migrate_claim` 再归一。往返逐字相等由
    `tests/test_claimanatomy.py::test_storage_round_trip_preserves_every_new_field` 钉住。

    这不是"两套字段名"：`text` 在这里只是磁盘格式的一个键，
    全项目的判据都只认 `statement`。
    """
    out = migrate_claim(claim)
    if STATEMENT_KEY in out:
        out["text"] = out.pop(STATEMENT_KEY)
    return out


# ---------------------------------------------------------------- 存在性判定


def presence_of(claim: Mapping[str, Any], name: str) -> str:
    """三态地报告一个字段的存在性：`"present"` / `"empty"` / `"absent"`。

    为什么不是布尔：`{"frozen": False}` 与"没有 `frozen` 键"是两件事 ——
    前者是"作者明确说了不冻结"，后者是"作者没提这件事"。
    把两者折叠，`frozen` 的默认值就会悄悄变成 False，而"我们没问过"这件事
    从此不可见（`DEVELOPMENT.md` §3 纪律 1）。

    别名算作存在：`text` 是 `statement` 的历史键名，一条只写 `text` 的老断言
    在 `statement` 这一项上是 `present` 而不是 `absent` —— 否则历史数据会被
    全部报成"缺 statement"，而那与"作者没写正文"是两件完全不同的事。
    """
    if not isinstance(claim, Mapping):
        return "absent"
    if name not in CLAIM_FIELDS:
        return "present" if name in claim else "absent"
    spec = CLAIM_FIELDS[name]
    keys = (spec.name, *spec.aliases)
    if not any(k in claim for k in keys):
        return "absent"
    val = _value_of(claim, name)
    if val is None:
        return "empty"
    if isinstance(val, str) and not val.strip():
        return "empty"
    # 空容器算 `present`：`citations=[]` 与"没有 citations 键"在 schema 里同罪，
    # 但在 `errata_ids` / `counterexamples` 这类"可以有、也可以没有"的清单上，
    # 空清单是"我查过、没有"的合法形态。
    return "present"


def _value_of(claim: Mapping[str, Any], name: str) -> Any:
    """取字段的值，别名优先于正名之后的第一个非 None 值。

    迁移期会同时存在 `statement` 与 `text` 两种键；这里只做取数，
    不做"两者内容是否打架"的判定 —— 那是 :func:`migrate_claim` 的职责
    （它会在两者不一致时抛错）。判据与迁移分开，是因为前者要被
    "只读地看一眼"的场景复用（`validate_claim` 就要）。
    """
    if not isinstance(claim, Mapping):
        return None
    spec = CLAIM_FIELDS.get(name)
    keys = (name, *(spec.aliases if spec else ()))
    for k in keys:
        if k in claim and claim.get(k) is not None:
            return claim.get(k)
    return claim.get(name)


# ---------------------------------------------------------------- 一致性门（三态）


def status_evidence_consistency(
    status: Any, evidence_kind: Any
) -> tuple[str, str]:
    """`status` 与 `evidence_kind` 的交叉一致性 —— 三态返回 `(判定, reason)`。

    返回 `(CONSISTENT | DECIDED_INCONSISTENT | CONSISTENCY_UNKNOWN, reason)`。

    ## 为什么是"两个正交的轴"而不是"一件事"

    `evidence_kind` 回答"支撑它的证据是哪一类"；`status` 回答
    "这条断言当前处于什么生命周期"。二者自由组合，不建立满射：

    - `status=待精化` + `evidence_kind=proof` ⇒ 一致（有形式化核验，但陈述还要精化）；
    - `status=证` + `evidence_kind=heuristic` ⇒ 不一致（"证"必须有 `proof` 级证据，FC-22）；
    - `status=验` + `evidence_kind=proof` ⇒ 不一致（有 `proof` 却只标"验"，
      等于把已证明的东西降级成"数值验过" —— 这看似"保守"，但它会让
      "证/验"这两档计数都失真，而计数失真在下游就是结论失真）；
    - `status=作废` + 任意 `evidence_kind` ⇒ 一致（撤销与证据类型无关）；
      但必须有 `errata_ids` 或 `freeze_reason` 说明为什么作废 ——
      这条由 :func:`validate_claim` 判定（它需要看另外两个字段）。
    - 任一轴缺失或取值非法 ⇒ `CONSISTENCY_UNKNOWN` + reason。

    最后一档是本模块最要紧的地方：判不了就说不判了。
    把"字段缺失"猜成"一致"，正是 `DEVELOPMENT.md` §3 纪律 1 说的那个坑
    （"下游把'我们没查'读成了'查了没有'"）。
    """
    kinds = _evidence_kinds()
    problems: list[str] = []
    if status is None or (isinstance(status, str) and not status.strip()):
        problems.append("`status` 缺失 ⇒ 生命周期轴**没有值可判**")
    elif status not in CLAIM_STATUSES:
        problems.append(f"`status={status!r}` 不在 {CLAIM_STATUSES} 里 ⇒ 无法判定它属于哪个生命周期档")
    if evidence_kind is None or (isinstance(evidence_kind, str) and not evidence_kind.strip()):
        problems.append("`evidence_kind` 缺失 ⇒ 证据类型轴**没有值可判**")
    elif evidence_kind not in kinds:
        problems.append(f"`evidence_kind={evidence_kind!r}` 不在 {kinds} 里 ⇒ 无法判定它属于哪一档证据")
    if problems:
        return CONSISTENCY_UNKNOWN, "；".join(problems) + "（**没判**，不是『判过、一致』）"

    if status == "证" and evidence_kind != "proof":
        return (
            DECIDED_INCONSISTENT,
            f"`status='证'` 却 `evidence_kind={evidence_kind!r}`："
            "「证」必须有 `proof` 级证据（形式化检查器的产出），"
            "把数值/交叉验证写成已证明是本领域最自然也最危险的过度声称（FC-22）",
        )
    if status == "验" and evidence_kind == "proof":
        return (
            DECIDED_INCONSISTENT,
            "`status='验'` 却 `evidence_kind='proof'`：有形式化核验却只标「验」，"
            "会让证/验两档计数同时失真（看似保守，后果与虚报同族）",
        )
    return CONSISTENT, f"`status={status!r}` 与 `evidence_kind={evidence_kind!r}` 是合法组合"


def lifecycle_verdict(claim: Mapping[str, Any]) -> tuple[bool | None, str]:
    """一条断言的生命周期是否自洽 —— 三态 `(True | False | None, reason)`。

    `None` = 判不了（缺字段/取值非法），`False` = 判过、不自洽，
    `True` = 判过、自洽。三态纪律要求调用方能分开处置这三者：
    `None` 的处置是"补齐字段"，`False` 的处置是"改声明或改证据"。

    这里只做交叉轴判定；字段级的类型/词表问题由 :func:`validate_claim` 报。
    """
    verdict, reason = status_evidence_consistency(
        claim.get("status") if isinstance(claim, Mapping) else None,
        claim.get("evidence_kind") if isinstance(claim, Mapping) else None,
    )
    if verdict == CONSISTENCY_UNKNOWN:
        return None, reason
    if verdict == DECIDED_INCONSISTENT:
        return False, reason
    if isinstance(claim, Mapping) and claim.get("status") == "作废":
        if not _retraction_reason(claim):
            return (
                False,
                "`status='作废'` 但没有 `errata_ids` 也没有 `freeze_reason`："
                "作废必须有原因（勘误编号或冻结理由），否则「为什么不算了」无人能接手",
            )
    return True, reason


def _retraction_reason(claim: Mapping[str, Any]) -> str:
    """作废的合法原因：勘误 ID 或冻结理由（两者任一即可，取可读的那一个）。"""
    errata = _value_of(claim, "errata_ids") or []
    if isinstance(errata, str):
        errata = [errata] if errata.strip() else []
    if errata:
        return "、".join(str(x) for x in errata)
    return str(_value_of(claim, "freeze_reason") or "").strip()


# ---------------------------------------------------------------- 单条断言判定


def _overclaim_markers() -> tuple[str, ...]:
    """视为"过度声称"的措辞，从 `tools/doc_tools.py` 取（唯一来源）。

    为什么是惰性转发而不是复制一份：这份清单是 `doc.compose_claim` 与
    `review.scan_document` 共用的判据，写第二份必然漂移 —— 而漂移的形态是
    "G 认为过度声称、H 认为没有"，没有任何报错（FC-03）。

    为什么不用模块级 import：`tools.doc_tools` 在导入期 import 本模块，
    模块级反向 import 会成环。惰性 import 在调用期执行，那时两边都已就绪；
    它同时保证"搬走这份清单"时只需改一处。
    """
    try:
        from .tools.doc_tools import OVERCLAIM_MARKERS

        return tuple(OVERCLAIM_MARKERS)
    except Exception:  # noqa: BLE001 - 见下：同值兜底 + 有测试断言两者是同一对象
        # 为什么可以忽略：这是纯判据层在"工具层不可导入"这一种环境下的降级路径。
        # 兜底值与 doc_tools 的字面量逐字相同，且
        # `tests/test_claimanatomy.py::test_overclaim_markers_are_not_a_second_copy`
        # 断言两边是同一个元组 —— 所以这里的降级不会造出第二份清单。
        return (
            "已证明", "证明了", "严格证明", "定理成立", "由此得证",
            "proved", "we prove", "is proved", "rigorous proof",
        )


def _cross_check_disclaimer() -> str:
    """`cross_check` 必需的那句声明，从 `tools/doc_tools.py` 取（唯一来源）。

    写成常量而不是各处手打，是为了让 H 能精确匹配它 ——
    若允许多种写法，审校就只能靠语义判断，而"靠语义判断"正是我们要避免的。
    """
    try:
        from .tools.doc_tools import CROSS_CHECK_DISCLAIMER

        return str(CROSS_CHECK_DISCLAIMER)
    except Exception:  # noqa: BLE001 - 同上：同值兜底且被测试钉住
        return "数值交叉验证，不构成证明"


def _bad_type(name: str, val: Any, spec: FieldSpec) -> str:
    """返回类型错误的说明（空串 = 类型没问题）。"""
    if name in ("frozen", "is_negative", "falsifiable"):
        if not isinstance(val, bool):
            return f"`{name}` 必须是 bool，收到 {type(val).__name__}（{val!r}）"
    elif name in ("counterexamples", "errata_ids", "citations"):
        if not isinstance(val, (list, tuple)):
            return f"`{name}` 必须是 list，收到 {type(val).__name__}（{val!r}）"
    elif name == "numeric_evidence":
        if not isinstance(val, Mapping):
            return f"`{name}` 必须是对象（四元组），收到 {type(val).__name__}（{val!r}）"
    elif name in ("claim_id", "statement", "kind", "status", "proof_location",
                  "freeze_reason", "allowed_use", "scope_caveat", "revision_hash",
                  "section",
                  # `draft/31` P3 的四列 + 两列出处：词表与类型都必须受判，
                  # 否则「来源=自证证」这种取值会静默通过（见 CLAIM_FIELDS 里那一段）。
                  "source_kind", "our_check", "our_check_note", "falsifiable_note",
                  "paper_ref", "paper_excerpt"):
        if not isinstance(val, str):
            return f"`{name}` 必须是 str，收到 {type(val).__name__}（{val!r}）"
    _ = spec
    return ""


def validate_claim(claim: Mapping[str, Any], *, strict: bool = False) -> ClaimSpec:
    """对一条断言做可判定的字段级 + 交叉轴判定。

    ## 三态纪律在这里的落点（这是本函数最要紧的部分）

    返回值里有两组互相独立的位：

    ==========================  ================================================
    位                            含义
    ==========================  ================================================
    `checked`                    检查器跑成了（False = 自己崩了，见 `checker_error`）
    `decided`                    一致性门判成了（False = 判不了，看 `undecided_reason`）
    ==========================  ================================================

    于是调用方能分开处置三件完全不同的事：字段缺失（补字段）、
    字段存在但非法（改声明）、检查器自己没跑成（修检查器）。
    它不会把 `None` 与 `False` 合并成一个"不通过"。

    ## `strict` 是什么

    `strict=False`（默认）：§8.3 新增的 9 个字段可以缺失 —— 磁盘上的历史行
    就是这样。缺失只让一致性门报 `decided=False`，不产生 error。
    `strict=True`：缺失的新字段报 `warning`（不是 error！），用于"新写的稿件
    应该补齐 12 字段"这一档要求。为什么缺失永远不是 error：
    把"没写 `allowed_use`"与"写了非法 `allowed_use`"报成同一档，
    会让 `documented-but-not-yet-migrated` 的历史数据在门里红灯长亮，
    而红灯长亮会训练人忽略红灯（`DEVELOPMENT.md` §5.1 的假报警教训）。
    """
    issues: list[ClaimIssue] = []
    fields_used: list[str] = []
    try:
        raw: Mapping[str, Any] = claim if isinstance(claim, Mapping) else {}
        cid = str(raw.get("claim_id") or "?")
        norm = migrate_claim(raw) if isinstance(raw, Mapping) else {}
    except ValueError as e:
        # `migrate_claim` 报的"text 与 statement 不一致"是确定的违规。
        return ClaimSpec(
            claim_id=str((claim or {}).get("claim_id") or "?") if isinstance(claim, Mapping) else "?",
            checked=True,
            decided=False,
            verdict=CONSISTENCY_UNKNOWN,
            status_axis=CONSISTENCY_UNKNOWN,
            undecided_reason=str(e),
            issues=[
                ClaimIssue(
                    code="bad_type",
                    field_name=STATEMENT_KEY,
                    level="error",
                    message=str(e),
                    evidence=f"claim={ {k: str(v)[:40] for k, v in dict(claim).items()}!r}"
                    if isinstance(claim, Mapping)
                    else repr(claim),
                    claim_id=str((claim or {}).get("claim_id") or "?") if isinstance(claim, Mapping) else "?",
                )
            ],
            error_count=1,
            fields_used=(STATEMENT_KEY, "text"),
        )
    except Exception as e:  # noqa: BLE001 - 见下：检查器自己崩了要如实登记，不许静默
        # 为什么可以忽略（构造上不会发生）：这里捕获的是判据层自身的意外异常。
        # 处置不是"当作通过"，而是产出一条 `checker_error` —— 三态里的
        # "检查器自己没跑成"必须有出口，否则它会被折叠成"没问题"。
        return ClaimSpec(
            claim_id="?",
            checked=False,
            decided=False,
            verdict=CONSISTENCY_UNKNOWN,
            status_axis=CONSISTENCY_UNKNOWN,
            undecided_reason=f"检查器自身异常：{type(e).__name__}: {e}",
            issues=[
                ClaimIssue(
                    code="checker_error",
                    field_name="",
                    level="error",
                    message=f"断言检查器自己没跑成：{type(e).__name__}: {e}",
                    evidence=repr(claim)[:200],
                )
            ],
            error_count=1,
        )

    # ---- 1. 未知键（可判定：不在声明表里）
    for key in norm:
        if key not in CLAIM_FIELDS and key not in _ALIAS_TO_CANONICAL:
            issues.append(
                ClaimIssue(
                    code="undeclared_field",
                    field_name=str(key),
                    level="warning",
                    message=(
                        f"断言 {cid} 有未声明字段 `{key}`：它不在 claimanatomy.CLAIM_FIELDS 里。"
                        "未声明的字段无法被门读到（`verify.undeclared_array_field` 是同族纪律）"
                    ),
                    evidence=f"未知键 {key!r}；已知键 = {known_field_names()}",
                    claim_id=cid,
                )
            )

    # ---- 2. 字段级：缺失 / 类型 / 词表 / 成对字段
    #
    # 取值一律走 `_value_of`（别名也算存在）：一条只写 `text` 的历史断言
    # 在 `statement` 这一项上应当是 `present`，否则全部历史稿件都会被报成
    # "缺少正文" —— 而"作者没写正文"与"键名是旧的"是两件事。
    for name, spec in sorted(CLAIM_FIELDS.items()):
        pres = presence_of(norm, name)
        if pres == "absent":
            if spec.required:
                issues.append(
                    ClaimIssue(
                        code="missing_field",
                        field_name=name,
                        level="error",
                        message=f"断言 {cid} 缺少必填字段 `{name}`：{spec.why}",
                        evidence=f"字段 {name!r} 在 claim 里**不存在**（不是空值 —— 两者必须分开）",
                        claim_id=cid,
                    )
                )
            elif strict:
                issues.append(
                    ClaimIssue(
                        code="missing_field",
                        field_name=name,
                        level="warning",
                        message=(
                            f"断言 {cid} 缺少 `{name}`（strict 模式下要求补齐 12 字段）：{spec.why}"
                        ),
                        evidence=f"字段 {name!r} 不存在；出处 {spec.source}",
                        claim_id=cid,
                    )
                )
            continue
        if pres == "empty" and spec.required and not spec.nullable:
            issues.append(
                ClaimIssue(
                    code="empty_required",
                    field_name=name,
                    level="error",
                    message=f"断言 {cid} 的必填字段 `{name}` 为空值",
                    evidence=f"{name}={_value_of(norm, name)!r}",
                    claim_id=cid,
                )
            )
            continue
        val = _value_of(norm, name)
        if pres == "present" or (pres == "empty" and val is not None):
            bad = _bad_type(name, val, spec)
            if bad:
                issues.append(
                    ClaimIssue(
                        code="bad_type",
                        field_name=name,
                        level="error",
                        message=f"断言 {cid} 的 {bad}",
                        evidence=f"{name}={val!r}（类型 {type(val).__name__}）",
                        claim_id=cid,
                    )
                )
                continue
        # 词表检查：只要键写了就判（`present` 与 `empty` 都算）——
        # 一个写错的取值（`evidence_kind='prooof'`）是确定的违规，
        # 不该因为"它同时还是空的 / 必填字段走了另一条分支"而被跳过。
        # 跳过的后果是：G 判 error、H 判 info，两边对同一份稿件给出相反结论。
        if spec.domain is not None and name in norm:
            enum_val = _value_of(norm, name)
            if name == "evidence_kind":
                domain = _evidence_kinds()
            elif name == "negation_kind":
                domain = _negation_kinds()
            else:
                domain = spec.domain
            if enum_val is not None and enum_val not in domain:
                issues.append(
                    ClaimIssue(
                        code="bad_enum",
                        field_name=name,
                        level="error",
                        message=f"断言 {cid} 的 `{name}={enum_val!r}` 不在受控词表 {domain} 里",
                        evidence=f"{name}={enum_val!r}；受控词表={domain}；出处 {spec.source}",
                        claim_id=cid,
                    )
                )
        if name == "numeric_evidence" and isinstance(val, Mapping):
            missing_keys = [k for k in NUMERIC_EVIDENCE_KEYS if k not in dict(val)]
            if missing_keys:
                issues.append(
                    ClaimIssue(
                        code="incomplete_numeric_evidence",
                        field_name=name,
                        level="error",
                        message=(
                            f"断言 {cid} 的 `numeric_evidence` 缺 {missing_keys}："
                            "四元组缺一即不可复跑/不可判定覆盖范围"
                        ),
                        evidence=f"numeric_evidence 的键={sorted(dict(val))}，应为 {NUMERIC_EVIDENCE_KEYS}",
                        claim_id=cid,
                    )
                )

    # ---- 2b. 证据等级的两条硬约束（FC-22，本框架既有，参考体例里没有）
    #
    # 它们与 `schema.Document.validate` 的两条逐字对应（`:1091-1095` 与
    # `scan_claim` 原有的过度声称检查）。放在这一处而不是各写一遍：
    # 这两条正是 INVENTORY 4.5#10 记录的"G/H 两份判据漂移"的重灾区。
    ek_norm = _value_of(norm, "evidence_kind")
    statement_text = claim_statement(norm)
    if ek_norm in _evidence_kinds():
        if ek_norm == "cross_check" and not str(_value_of(norm, "disclaimer") or "").strip():
            issues.append(
                ClaimIssue(
                    code="missing_disclaimer",
                    field_name="disclaimer",
                    level="error",
                    message=(
                        f"断言 {cid} 的 `evidence_kind='cross_check'` 却没有 disclaimer。"
                        f"数值交叉验证必须显式写明「{_cross_check_disclaimer()}」"
                        f"—— 找的是这条断言对象的**独立一栏** `disclaimer`"
                        f"（写进 `text` 不算，写在别的断言里也不算）；"
                        f"这条断言的 text 前 60 字：{statement_text[:60]!r}"
                    ),
                    evidence=(
                        f"evidence_kind={ek_norm!r} 且 disclaimer="
                        f"{_value_of(norm, 'disclaimer')!r}（空）"
                    ),
                    claim_id=cid,
                )
            )
        if ek_norm != "proof":
            hit = [m for m in _overclaim_markers() if m in statement_text]
            if hit:
                issues.append(
                    ClaimIssue(
                        code="overclaim",
                        field_name="evidence_kind",
                        level="error",
                        message=(
                            f"断言 {cid} 的 `evidence_kind={ek_norm!r}`（不是 proof），"
                            f"但正文出现「{'、'.join(hit)}」—— 这是把交叉验证说成了证明"
                        ),
                        evidence=(
                            f"evidence_kind={ek_norm!r}；命中的措辞={hit}；"
                            f"正文摘要={statement_text[:80]!r}"
                        ),
                        claim_id=cid,
                    )
                )

    # ---- 2c. 否定分类（FC-25，本框架既有）：四类否定必须分开，
    #          且"是否否定"与"否定分类"必须成对出现。
    #
    # 为什么这一条必须在这里（而不是留给构造期）：`evidence_kind` 是 schema 的
    # 硬约束字段，而 `negation_kind` 不是 —— 于是一条 `is_negative=True` 却
    # 不带 `negation_kind` 的断言能通过 schema 写进磁盘，只有这一层拦得住。
    # 它也把"未证明 / 已证否 / 未搜索 / 无本地证据"这四类的计数口径钉在一处。
    is_neg = _value_of(norm, "is_negative") is True
    nk_norm = _value_of(norm, "negation_kind")
    if is_neg and not nk_norm:
        issues.append(
            ClaimIssue(
                code="missing_field",
                field_name="negation_kind",
                level="error",
                message=(
                    f"断言 {cid} 标了 `is_negative=True` 却没有 `negation_kind`。"
                    "「未证明」与「已证否」在数学上是两件事，必须分开"
                ),
                evidence=f"is_negative={_value_of(norm, 'is_negative')!r}、negation_kind={nk_norm!r}",
                claim_id=cid,
            )
        )
    if not is_neg and nk_norm is not None:
        # 等级是 error 而不是 warning：`schema.Document.validate:1102-1106`
        # 对同一条硬拦（"会让'否定'的计数虚高"）。写入期拦、审校期只警告，
        # 就是两处判据两个结论 —— 那正是 FC-03 的形态。
        issues.append(
            ClaimIssue(
                code="bad_enum",
                field_name="negation_kind",
                level="error",
                message=(
                    f"断言 {cid} 不是否定型（`is_negative` 不是 True）却带了 "
                    f"`negation_kind={nk_norm!r}`：会让『否定型结论』的**计数虚高**，"
                    "而否定计数是结论适用范围的一部分（FC-25）"
                ),
                evidence=f"is_negative={_value_of(norm, 'is_negative')!r}、negation_kind={nk_norm!r}",
                claim_id=cid,
            )
        )

    # ---- 2d. `citations` 的结构（FC-02，本框架既有）
    #
    # `citations` 在声明表里只写了"list[str]（非空）"，但它的两条真实约束
    # 是"非空"与"不含空元素"，而且 `schema.py:1078-1086` 也这样硬拦。
    # 判据必须逐字对上：写入期与审校期对同一个字符串给出不同结论，
    # 就是 FC-03 说的那种"没有任何报错的分裂"。
    cites_norm = _value_of(norm, "citations")
    if isinstance(cites_norm, (list, tuple)):
        if not cites_norm:
            issues.append(
                ClaimIssue(
                    code="empty_required",
                    field_name="citations",
                    level="error",
                    message=(
                        f"断言 {cid} 没有任何 citations —— "
                        "无引用的断言不允许进入稿件（FC-02）"
                    ),
                    evidence=f"citations={list(cites_norm)!r}（空列表：与『没有 citations 键』同罪）",
                    claim_id=cid,
                )
            )
        else:
            bad_cites = [x for x in cites_norm if not isinstance(x, str) or not x.strip()]
            if bad_cites:
                issues.append(
                    ClaimIssue(
                        code="bad_type",
                        field_name="citations",
                        level="error",
                        message=f"断言 {cid} 的 citations 含空/非字符串元素：{bad_cites!r}",
                        evidence=f"citations={list(cites_norm)!r}；问题元素={bad_cites!r}",
                        claim_id=cid,
                    )
                )

    # ---- 3. 成对字段：`frozen=True` ⇒ `freeze_reason` 必填
    if _value_of(norm, "frozen") is True and not str(_value_of(norm, "freeze_reason") or "").strip():
        issues.append(
            ClaimIssue(
                code="empty_required",
                field_name="freeze_reason",
                level="error",
                message=(
                    f"断言 {cid} 标了 `frozen=True` 却没写 `freeze_reason`。"
                    "只标冻结不说原因，接手的人无从判断该不该解冻"
                ),
                evidence=f"frozen=True，freeze_reason={_value_of(norm, 'freeze_reason')!r}",
                claim_id=cid,
            )
        )

    # ---- 4. 交叉轴：status × evidence_kind（三态）
    status_val = _value_of(norm, "status")
    ek_val = _value_of(norm, "evidence_kind")
    verdict, reason = status_evidence_consistency(status_val, ek_val)
    fields_used.append("status")
    fields_used.append("evidence_kind")
    if verdict == DECIDED_INCONSISTENT:
        issues.append(
            ClaimIssue(
                code="inconsistent_status",
                field_name="status",
                level="error",
                message=f"断言 {cid} 的 status 与 evidence_kind 不自洽：{reason}",
                evidence=f"status={status_val!r}、evidence_kind={ek_val!r}",
                claim_id=cid,
            )
        )
    elif verdict == CONSISTENCY_UNKNOWN:
        # 第三态：判不了。它不是 error（没有证据说明作者错了），
        # 但也绝不是"一致" —— 用 info 级登记，并让 `decided=False` 传出去。
        #
        # 抑制条件：若 `evidence_kind` 本身已经非法（上面已报 `bad_enum`
        # error），就不再额外报"判不了" —— 那会把同一条缺陷说两遍，
        # 而且是以两种级别说两遍。三态纪律要的是"判不了有别于判错了"，
        # 不是"把判错了也说成判不了"。
        ek_illegal = ek_val not in _evidence_kinds()
        if not ek_illegal:
            issues.append(
                ClaimIssue(
                    code="unknown_status_axis",
                    field_name="status",
                    level="info",
                    message=f"断言 {cid} 的 status×evidence_kind 一致性**判不了**：{reason}",
                    evidence=f"status={status_val!r}、evidence_kind={ek_val!r}",
                    claim_id=cid,
                )
            )
    # ---- 5. 作废必须有原因（`status=作废` 是常规状态，不是错误；缺原因才是）
    undecided_reason = "" if verdict != CONSISTENCY_UNKNOWN else reason
    if status_val == "作废" and not _retraction_reason(norm):
        retract_reason = (
            "`status='作废'` 却没有 `errata_ids` 也没有 `freeze_reason`："
            "作废这件事**判不出原因**（缺的不是一个值，而是撤销的依据）"
        )
        issues.append(
            ClaimIssue(
                code="lifecycle_incomplete",
                field_name="errata_ids",
                level="error",
                message=(
                    f"断言 {cid} 标了 `status='作废'` 但没有 `errata_ids` 也没有 `freeze_reason`："
                    "作废必须说清为什么（参考体例用稳定 ID 指勘误，如 `E-01`）"
                ),
                evidence=(
                    f"status='作废'、errata_ids={_value_of(norm, 'errata_ids')!r}、"
                    f"freeze_reason={_value_of(norm, 'freeze_reason')!r}"
                ),
                claim_id=cid,
            )
        )
        if not undecided_reason:
            undecided_reason = retract_reason

    # ---- 6. `claim_id` / 正文为空（另有一档：字段存在但值为空）
    if not str(_value_of(norm, "claim_id") or "").strip():
        issues.append(
            ClaimIssue(
                code="empty_required",
                field_name="claim_id",
                level="error",
                message="断言缺少 claim_id（唯一稳定代号是审校定位的前提）",
                evidence=f"claim_id={_value_of(norm, 'claim_id')!r}",
                claim_id=cid,
            )
        )
    if not claim_statement(norm).strip():
        issues.append(
            ClaimIssue(
                code="empty_required",
                field_name=STATEMENT_KEY,
                level="error",
                message=f"断言 {cid} 的正文（`{STATEMENT_KEY}`）为空",
                evidence=f"{STATEMENT_KEY}={norm.get(STATEMENT_KEY)!r}、text={raw.get('text')!r}",
                claim_id=cid,
            )
        )

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    # `decided` 的判据：三件事都判成了才算判成。
    # 一条判不了（缺字段）与一条判成"不一致"（有 error）在这里分道扬镳：
    # 前者 `verdict=未知`，后者 `verdict=不一致` —— 呼叫方的处置完全不同。
    decided = verdict != CONSISTENCY_UNKNOWN and not errors
    if not decided and not undecided_reason:
        undecided_reason = "字段级判定报出了 error ⇒ 一致性门的结论以那些 error 为准（见 issues）"
    return ClaimSpec(
        claim_id=cid,
        checked=True,
        decided=decided,
        verdict=verdict,
        status_axis=verdict,
        undecided_reason=undecided_reason,
        issues=issues,
        error_count=len(errors),
        warning_count=len(warnings),
        fields_used=tuple(fields_used),
        revision_hash=str(norm.get("revision_hash") or ""),
    )


def _negation_kinds() -> tuple[str, ...]:
    """`negation_kind` 的受控词表，从 `schema.py` 取（同 :func:`_evidence_kinds`）。"""
    try:
        from . import schema as S

        return tuple(S.NEGATION_KINDS)
    except Exception:  # noqa: BLE001 - 同 `_evidence_kinds`：纯判据层的降级路径，同值兜底
        return ("disproved", "not_proved", "not_searched_here", "no_local_evidence")


# ---------------------------------------------------------------- 稿件级判定


def validate_document_claims(doc: Mapping[str, Any], *, strict: bool = False) -> list[ClaimIssue]:
    """对一份稿件的全部断言做判定（含代号重复）。

    为什么要把"代号重复"放在稿件层：它对单条断言不可判定 ——
    重复是两份断言之间的关系。`schema.Document.validate` 也拦它（`:1072`），
    这里再报一次是为了让 H 的只读路径在稿件未落库时也能看到它
    （只读审校时稿件可能来自内存，没经过 schema）。
    """
    claims = doc.get("claims") if isinstance(doc, Mapping) else None
    if claims is None:
        return [
            ClaimIssue(
                code="missing_field",
                field_name="claims",
                level="error",
                message="稿件没有 `claims` 字段 ⇒ 无从判定（**没查**，不是『没有断言』）",
                evidence=f"doc 的键={sorted(doc) if isinstance(doc, Mapping) else type(doc).__name__}",
            )
        ]
    issues: list[ClaimIssue] = []
    seen: dict[str, str] = {}
    for i, c in enumerate(claims, 1):
        spec = validate_claim(c, strict=strict)
        # 代号缺失时用位置当定位符（与 `schema.Document.validate` 的 `claims[i]` 同形态）：
        # 报"claims[3] 缺 claim_id"比报"断言 ? 缺 claim_id"可定位得多。
        cid = str((c or {}).get("claim_id") or "").strip() if isinstance(c, Mapping) else ""
        if not cid:
            cid = f"claims[{i}]"
        for issue in spec.issues:
            issues.append(
                ClaimIssue(
                    code=issue.code,
                    field_name=issue.field_name,
                    level=issue.level,
                    message=issue.message,
                    evidence=issue.evidence,
                    claim_id=issue.claim_id if issue.claim_id not in ("", "?") else cid,
                )
            )
        if not isinstance(c, Mapping):
            continue
        text = claim_statement(c)
        if cid in seen and seen[cid] != text:
            issues.append(
                ClaimIssue(
                    code="duplicate_claim_id",
                    field_name="claim_id",
                    level="error",
                    message=f"同一 claim_id={cid} 对应两段不同文字（审校将无法定位到唯一一条断言）",
                    evidence=f"{seen[cid][:60]!r} vs {text[:60]!r}",
                    claim_id=cid,
                )
            )
        elif cid in seen:
            issues.append(
                ClaimIssue(
                    code="duplicate_claim_id",
                    field_name="claim_id",
                    level="warning",
                    message=f"claim_id={cid} 出现两次且内容相同（重复条目会让计数虚高）",
                    evidence=f"同一代号两份内容相同的断言：{text[:60]!r}",
                    claim_id=cid,
                )
            )
        seen[cid] = text
    return issues


def consolidate_issues(issues: Sequence[ClaimIssue]) -> dict:
    """把一批 :class:`ClaimIssue` 汇总成 H 的门可以直接判定的结论。

    ## 为什么必须有这个入口（而不是让每道门自己数）

    三态纪律要求"分档计数，禁止单一通过率"（FC-10）：一个"通过率 80%"
    会掩盖"另外 20% 是失败还是没检查"这个决定性差异。所以汇总结果必须
    同时给出三个数字，并且单独给出"判不了"的那一档：

    ==================  ==============================================
    键                    含义
    ==================  ==============================================
    `error_count`        确定违规
    `warning_count`      很可能违规 / 建议补齐
    `info_count`         只是数字
    `undecidable_count`  判不了（三态第三态，不许并进任何一个别的档）
    `decided`            `decidable_count > 0 and undecidable_count == 0`
    `has_errors`         是否有 error（门据此判 fail）
    ==================  ==============================================
    """
    errs = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warning"]
    undec = [i for i in issues if i.code == "unknown_status_axis"]
    infos = [i for i in issues if i.level == "info" and i.code != "unknown_status_axis"]
    return {
        "total": len(issues),
        "error_count": len(errs),
        "warning_count": len(warns),
        "info_count": len(infos),
        # 第三态单独一档：把"判不了"并进 error 会把它说成"作者错了"，
        # 并进 info/通过 会让"我们没判"消失。
        "undecidable_count": len(undec),
        "decidable_count": len(issues) - len(undec),
        "decided": (len(issues) - len(undec)) > 0 and not undec,
        "has_errors": bool(errs),
        "codes": sorted({i.code for i in issues}),
    }


def has_issue(issues: Iterable[ClaimIssue], code: str) -> bool:
    """这批判定里有没有指定 `code`（机器可读判据的查询入口）。"""
    return any(i.code == code for i in issues)


def count_by_code(issues: Iterable[ClaimIssue]) -> dict[str, int]:
    """按 `code` 计数（自证数字用：门必须说清"我数出了什么"）。"""
    out: dict[str, int] = {}
    for i in issues:
        out[i.code] = out.get(i.code, 0) + 1
    return out


def summary_counts(issues: Iterable[ClaimIssue]) -> dict:
    """人可读的一行摘要（渲染/报告用）。"""
    issues = list(issues)
    agg = consolidate_issues(issues)
    return {
        "error_count": agg["error_count"],
        "warning_count": agg["warning_count"],
        "info_count": agg["info_count"],
        "undecidable_count": agg["undecidable_count"],
        "message": (
            f"error={agg['error_count']}、warning={agg['warning_count']}、"
            f"info={agg['info_count']}、**判不了={agg['undecidable_count']}**"
        ),
    }


# ---------------------------------------------------------------- 版本 hash（G11）

#: `revision_hash` 的算法标签。写进报告，让"这串字节是怎么算的"可复现。
REVISION_HASH_ALGO = "sha256(json(claims, sort_keys, ensure_ascii=False))[:16]"


def claim_content_hash(claim: Mapping[str, Any]) -> str:
    """一条断言的内容 hash（16 位十六进制）。

    刻意排除 `revision_hash` 自身：否则"给一条断言打 hash"会改变它的内容，
    于是 hash 永远无法稳定（自指）。这条排除必须在代码里显式写出来 ——
    否则下一轮重构会顺手把整条 claim 塞进 `json.dumps`，而没有任何测试会红
    （hash 仍然能算出来，只是再也对不上）。
    """
    norm = migrate_claim(claim) if isinstance(claim, Mapping) else {}
    payload = {k: v for k, v in sorted(norm.items()) if k != "revision_hash"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def revision_hash(doc: Mapping[str, Any]) -> str:
    """一份稿件的内容 hash（16 位十六进制）—— 审校报告必须钉住它（G11）。

    为什么钉住的是内容而不是文件名/时间戳：`STYLE/FIX_PROTOCOL.md:5-10`
    的纪律是"审校期间不改文件；报告钉住被审版本 hash"。文件名可以不变而内容已改，
    时间戳会因重新渲染而变 —— 只有内容 hash 能让"报告说的是哪一版"可复核。

    参与计算的字段：`doc_id` + `title` + `kind` + 全部 `claims`
    （断言逐条先归一、再去掉各自的 `revision_hash`，然后再汇总）。
    `status` / `review_rounds` 不参与：它们是审校过程的状态，
    参与进去会让"审校改状态"这件事本身改变被审版本的 hash —— 于是 hash 再也
    对不上报告（这是"审校期间不改文件"这条纪律反过来的那一半）。
    """
    claims = doc.get("claims") or []
    payload = {
        "doc_id": str(doc.get("doc_id") or ""),
        "kind": str(doc.get("kind") or ""),
        "title": str(doc.get("title") or ""),
        "claims": [claim_content_hash(c) for c in claims if isinstance(c, Mapping)],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- 渲染层的降级门（G14）

#: 正文主结果区不许出现的生命周期：作废。参考体例里 `❌作废` 是常规状态，
#: 但它不能出现在主结果里 —— 一条已撤销的断言被当成有效结论引用，
#: 是本项目最不愿看到的失效形态（`draft/17` §8.4 的 G14 降级合规门）。
_RETRACTED = "作废"


def is_retracted(claim: Mapping[str, Any]) -> bool:
    """这条断言是否已作废。只认 `status`，不认 `evidence_kind`（两轴正交）。"""
    return isinstance(claim, Mapping) and claim.get("status") == _RETRACTED


def main_body_claims(claims: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """正文主结果区允许出现的断言（渲染层的降级门）。

    排除两类（两类都必须排除，理由不同）：

    - `status='作废'` —— 已撤销的断言。渲染层门：它不得出现在正文主结果区，
      只能进附录（带撤销原因）。
    - `allowed_use='移入 open'` —— 参考体例的硬性降级规则：这类断言
      不属于本文的结论，它是一条开放问题的线索，只能进开放问题区。
    """
    out: list[Mapping[str, Any]] = []
    for c in claims:
        if not isinstance(c, Mapping):
            continue
        if is_retracted(c):
            continue
        if c.get("allowed_use") == "移入 open":
            continue
        out.append(c)
    return out


def retracted_claims(claims: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """已作废的断言（渲染层把它们放进附录，并带上撤销原因）。"""
    return [c for c in claims if isinstance(c, Mapping) and is_retracted(c)]
