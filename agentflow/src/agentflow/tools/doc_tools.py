"""G 的工具：论文撰写。

## 这一层唯一的核心规矩

没有引用的断言不允许进入稿件。

这不是文风要求，而是本领域可信度的技术基础：数学断言的价值完全取决于
"它来自哪里"。一旦允许无引用的断言，稿件就退化成一个听起来很合理的
文本 —— 而"听起来合理"与"有证据"之间的差距，正是幻觉最容易藏身的地方。

因此本模块把三条约束做成了可机械判定的检查（`scan_claim`），
并由 `schema.Document.validate` 在写入时强制执行：

1. `citations` 非空（FC-02）；
2. `evidence_kind="cross_check"` 的断言必须自带 `disclaimer`
   （"数值交叉验证，不构成证明"）—— 这句话由结构强制，不靠人记得写（FC-22）；
3. 否定型断言必须给 `negation_kind`（FC-25，"未证明"≠"已证否"）。

## 本模块的入口

| 函数 | 作用 | 关键纪律 |
|---|---|---|
| `scan_claim` | 一条断言的机械检查（纯函数） | 唯一判据；G 与 H 共用同一份 |
| `compose_claim` | 构造一条合规断言 | `cross_check` 自动补 disclaimer；否定型未分类、无引用、过度声称 ⇒ 构造时抛 |
| `build_document` | 落库 + 渲染 markdown | 先逐条 `scan_claim`、再核 citations 指向的对象真的存在（两张闸都过才写库） |
| `register_dependency` | 登记外部依赖（FC-23 第一道闸） | `closed` 必须用真实数据核到已入库来源 |
| `render_markdown` | 人可读渲染（FC-10 / FC-22 / FC-23 / FC-25 的呈现层） | 三分档计数、否定分类、依赖表都必须出现 |
| `list_documents` | 只读列举 | 供 H / F / D 消费 |

## 为什么"在构造时就抛"比"写库时才抛"重要

`schema.Document.validate` 已经拦得住无引用断言，但它的报错形如
"claims[3] 没有 citations" —— 读者得自己回去数"第 3 条到底是哪句话"，
而构造现场（手里正拿着那句话、那段引用）才是信息最全的地方。
写库时的 schema 是最后一道闸，不是唯一一道。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from .. import claimanatomy as CA
from .. import paperbuild as PB
from .. import schema as S
from .. import textutil as T
from ..store import StoreError
from .base import ToolRegistry, ToolSpec, fail, ok, tool

#: G 写稿；H 审稿（因此需要同一套判定函数 —— 审校者与撰写者必须用同一套判据，
#: 否则会出现"G 认为合规、H 认为违规"的静默分裂，而双方都不算错）；
#: F/D 需要读稿件的开问题清单。
_ROLES = ("G", "H", "F", "D")

#: 只有 G 能写稿。H 是审校（角色面必须全只读），F/D 是消费者。
#: 把写工具的角色收窄到 ("G",) 而不是沿用 _ROLES：一旦 H 手里有
#: `doc.build_document`，"发现问题的人"与"改写稿件的人"就变成了同一个，
#: 于是"发现问题"与"掩盖问题"在结构上无法区分。
_WRITER_ROLES = ("G",)

#: `cross_check` 类断言必须自带的声明。写成常量而不是各处手打，
#: 是为了让 H 能精确匹配它 —— 若允许多种写法，审校就只能靠语义判断，
#: 而"靠语义判断"正是我们要避免的东西。
CROSS_CHECK_DISCLAIMER = "数值交叉验证，不构成证明"

#: 视为"过度声称"的措辞。`evidence_kind != "proof"` 的断言里出现这些词即报。
#: 这份清单必须显式列出：隐含的判据无法被审阅、无法被反驳。
#:
#: `R4` 组 7⑤ 的未落地记录（重要，别照"并集"直接合）：曾按"与
#: `agent_d/_support._OVERCLAIM_MARKERS` 合并成并集（9 + 7 − 1 = 15 词）落过一版，
#: 实测打破了两条既有判据 ⇒ 已回滚：
#:   - `tests/test_paper_pack.py::test_claim_strength_ignores_a_theorem_name_and_a_negation`
#:     逐字要求"定理名不算过度声称"，而并集里的 `定理` 直接与它冲突；
#:   - `tests/test_core_audit_efgh.py::test_module_selftest_exits_zero[agentflow.agent_g]`
#:     也红了（自检夹具里的文本被新词命中）。
#: ⇒ 两份清单不是冗余：本表判"非 proof 断言正文里的说满措辞"（点定理名在这里合法），
#: `_support` 那份判"措辞 × confidence"（S-09，另一个消费者、另一套语境）。
#: 要合并必须先裁"哪些词在哪一档合法"，不许盲目取并集。
OVERCLAIM_MARKERS = (
    "已证明", "证明了", "严格证明", "定理成立", "由此得证",
    "proved", "we prove", "is proved", "rigorous proof",
)

#: 证据等级的中文标签（渲染层用）。英文枚举名是给机器用的受控词表，
#: 直接出现在给人读的稿件里会让人需要额外翻译一次才能确认它没被夸大。
EVIDENCE_LABELS = {
    "proof": "形式化核验（proof）",
    "cross_check": "交叉验证（cross_check）",
    "heuristic": "启发式（heuristic）",
}

#: FC-25 的四类否定。四类必须分开列：
#: "未证明"与"已证否"在数学上是两件事；"没搜过"与"搜了没有本地证据"也是。
NEGATION_LABELS = {
    "disproved": "已证否",
    "not_proved": "未证明",
    "not_searched_here": "未搜索",
    "no_local_evidence": "无本地证据",
}


# ---------------------------------------------------------------- 小工具


def _one_line(text: Any, width: int = 220) -> str:
    """单行化 + 截断：保证 markdown 表格不被打断。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"


def _claim_id_of(text: str, citations: Iterable[str]) -> str:
    """由内容派生一个稳定的 claim 代号。

    为什么不用自增序号：`compose_claim` 是纯函数，它不知道自己在稿件里排第几；
    让纯函数去持有全局计数器，会让"同样的输入给出不同的输出"，测试与重放都会失真。
    `build_document` 落库时会按顺序补齐 `claim-1…claim-N`（人可读、唯一定位）。
    """
    blob = "|".join([str(text or ""), *[str(c) for c in citations]])
    return "claim-" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]


def _coerce_page_range(value: Any) -> S.PageRange:
    """把 (start, end) / dict / "pp. 45-46" / PageRange 统一成 `PageRange`。

    刻意复用 `textutil.parse_page_range` 而不是自己写一套解析：
    页码口径若有两份实现，就会在"某本书的页码写法特殊"时静默分叉。
    """
    if value is None:
        return S.PageRange()
    if isinstance(value, S.PageRange):
        return value
    if isinstance(value, Mapping):
        return S.PageRange.from_dict(dict(value))
    if isinstance(value, str):
        return T.parse_page_range(value)
    if isinstance(value, (list, tuple)):
        if len(value) == 1:
            return S.PageRange(start=int(value[0]), end=int(value[0]))
        if len(value) == 2:
            s, e = int(value[0]), int(value[1])
            return S.PageRange(start=s, end=e, label=f"pp. {s}-{e}")
    raise ValueError(f"page_range 无法解析：{value!r}（支持 (start,end) / dict / 'pp. 45-46' / PageRange）")


def dependencies_for_doc(drows: Iterable[Mapping[str, Any]], doc_id: str) -> list[dict]:
    """筛出属于某份稿件的依赖行。

    归属判据是 `used_by` 的前缀（`"doc:0001"` 或 `"doc:0001#claim-3"`），
    与 `schema.Dependency.used_by` 的文档约定一致。集中在这里而不是各处
    自己 `startswith`：口径分叉会让"某份稿件的依赖"在两处给出不同的集合，
    而依赖集是 FC-23 的核心，不许有两份答案。
    """
    prefix = f"doc:{doc_id}"
    out: list[dict] = []
    for r in drows:
        u = str(r.get("used_by") or "").strip()
        if u == prefix or u.startswith(prefix + "#"):
            out.append(dict(r))
    return out


def resolve_out_path(
    root: Path, out_path: Any, doc_id: str, default_subdir: str
) -> tuple[str, Path]:
    """把 out_path 解析成工作区内的绝对路径，并返回 (相对路径, 绝对路径)。

    越界一律拒绝（而不是"写到外面再警告"）：工作区边界是沙箱契约的一部分，
    允许一次越界写就等于承认这个边界可以被绕开。用 `resolve()` 之后再
    `relative_to()` 判断，而不是靠字符串 `..` 检查 —— 后者会被符号链接绕过。

    ## 为什么它是公开的（`draft/37` §118）

    `D.write_report` 原先自己写 `Path(out_path)` —— 相对路径于是按「进程当前目录」
    解析。T2 第 1 趟真机：主控传 `out_path="out\\review\\D-analysis.md"`（工作区内的
    合法落点），文件却写到了 `D:\\Incubator\\agentflow\\out\\review\\D-analysis.md`
    （进程 cwd），「整个交付物静默离开工作区」，而那一趟记的是 `outcome=ok`。
    同一条规则不能有两份实现（那正是"两份判据必然漂移"），所以它在这里公开，
    由角色方法直接复用。
    """
    raw = str(out_path) if out_path else f"{default_subdir}/{doc_id}.md"
    p = Path(raw)
    absolute = p if p.is_absolute() else (root / p)
    try:
        absolute = absolute.resolve()
        rel = absolute.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError(
            f"out_path 越界：{raw!r} 不在工作区 {root} 内（{type(e).__name__}）。"
            "稿件只允许写在工作区里 —— 这是沙箱边界，不是建议"
        ) from e
    return str(rel).replace("\\", "/"), absolute


# ---------------------------------------------------------------- 断言检查


def scan_claim(claim: Mapping[str, Any]) -> dict:
    """对一条断言做可判定的机械检查（转发 `claimanatomy.validate_claim`）。

    返回 ``{"ok": bool, "findings": [{kind, level, message, evidence}], "checked": True, ...}``。

    `findings` 里的 `kind` 与 :data:`agentflow.schema.FINDING_KINDS` 同词表 ——
    这样 H 的审校发现与 G 的自检发现是同一批类型，可以互相印证，
    而不会出现"G 自查用一套名字、H 审查用另一套"的分裂。

    ## 判据只有一份（本函数现在只是适配层）

    字段级与交叉轴的判据全部在 :mod:`agentflow.claimanatomy`（`CLAIM_FIELDS`
    是一张可被文档生成与 CLI 读取的声明表）。本函数只做两件事：
    ① 把 `ClaimIssue.code` 翻成 `FINDING_KINDS` 的受控词（下游只认后者）；
    ② 把结论压成 `ok / error_count / warning_count` 的旧形状。
    它不再自己写任何一条检查 —— 这里曾经有过第二份实现，
    而"两份判据必然漂移，漂移的后果是 G 认为合规、H 认为通过，且没有任何报错"
    （FC-03 / INVENTORY 4.5#10）。

    三态纪律：`unknown_status_axis`（判定"判不了"）不计入 `error_count`，
    但会原样出现在 `findings` 里，并由 `decided` 位单独传出 ——
    "字段缺失"与"字段非法"与"检查器没跑成"必须能分开。
    """
    spec = CA.validate_claim(claim)
    findings: list[dict] = []
    for issue in spec.issues:
        findings.append(
            {
                "kind": _finding_kind_of(issue),
                "level": issue.level,
                "message": issue.message,
                "evidence": issue.evidence,
                "code": issue.code,
                "family": issue.family,
                "field": issue.field_name,
            }
        )
    errors = [f for f in findings if f["level"] == "error"]
    return {
        "checked": spec.checked,
        "claim_id": spec.claim_id,
        "ok": not errors,
        "findings": findings,
        "error_count": len(errors),
        "warning_count": len([f for f in findings if f["level"] == "warning"]),
        # 三态第三态：`decided=False` 时 `undecided_reason` 必非空。
        # 只暴露布尔会让调用方把"判不了"读成"判过、没问题"。
        "decided": spec.decided,
        "undecided_reason": spec.undecided_reason,
        "status_axis": spec.status_axis,
        "checked_fields": list(spec.fields_used),
        "revision_hash": spec.revision_hash,
    }


#: `ClaimIssue.code` → `schema.FINDING_KINDS` 的受控词。
#:
#: 为什么需要这一层：`claimanatomy` 的 code 是判据层的词（`missing_field`
#: / `bad_enum` / `inconsistent_status` …），而 `review_findings.kind` 是
#: 落库层的词（`schema.FINDING_KINDS`，而 `schema.py` 在禁 AI 区，
#: 不能给它加成员）。两者必须能对上，否则 H 的发现落库时会被 schema 拒。
#: 这张表是唯一的映射处（FC-03）：
#:
#: ==========================  ==========================  ================================
#: claimanatomy code             finding kind                为什么这样映射
#: ==========================  ==========================  ================================
#: `missing_field`               `unsupported_claim`         缺的字段是断言成立的前提（引用/正文）
#: `empty_required`              `unsupported_claim`         同上，只是"键在但值为空"
#: `bad_enum` / `bad_type`       `garbled`                   取值/类型非法 = 表述无法解析
#: `inconsistent_status`         `overclaim`                 两轴矛盾/过度声称
#: `unknown_status_axis`         `scope_drift`               "有个分类没法定"——不是 `garbled`，
#:                                                          也不是 `missing_negation_kind`：
#:                                                          前者会与"取值非法"撞同一个 kind，
#:                                                          后者会与"否定未分类"撞而级别不同
#:                                                          （一个是 info、一个是 error）
#: `undeclared_field`            `scope_drift`               未声明字段无法被任何门读到
#: `duplicate_claim_id`          `inconsistent_number`       同一标识对应两处不同内容
#: `checker_error`               `garbled`                   检查器自己没跑成
#: ==========================  ==========================  ================================
_FINDING_KIND_OF_CODE: dict[str, str] = {
    "missing_field": "unsupported_claim",
    "empty_required": "unsupported_claim",
    "bad_enum": "garbled",
    "bad_type": "garbled",
    "inconsistent_status": "overclaim",
    "unknown_status_axis": "scope_drift",
    "undeclared_field": "scope_drift",
    "duplicate_claim_id": "inconsistent_number",
    "checker_error": "garbled",
    # `draft/39` §3.8 的 8 族各自独立成 code 之后（族号要能直接印在拒信里），
    # 这四条必须在这里逐条登记 —— 未登记的 code 会显式失败（见 `_finding_kind_of`），
    # 而那是故意的：兜底成 `garbled` 会让"新增 code 忘了登记"静默通过。
    "overclaim": "overclaim",
    "incomplete_numeric_evidence": "unsupported_claim",
    "missing_disclaimer": "unsupported_claim",
    "lifecycle_incomplete": "inconsistent_number",
}


def _finding_kind_of(issue: "CA.ClaimIssue") -> str:
    """把判据层的 code 翻成落据层的受控词；未登记的 code 显式失败。

    为什么未登记就抛而不是兜底成 `garbled`：兜底会让"新增了一个 code 却忘了
    登记映射"这件事静默通过，于是 H 端的发现会带着一个语义不对的 kind
    落库 —— 而 kind 是审校分档的判据。宁可当场炸。
    """
    kind = _FINDING_KIND_OF_CODE.get(issue.code)
    if kind is None:
        raise KeyError(
            f"claimanatomy 的 code {issue.code!r} 没有登记到 schema.FINDING_KINDS 的映射。"
            f"新增 code 时必须同时更新 _FINDING_KIND_OF_CODE（已知 = {sorted(_FINDING_KIND_OF_CODE)}）"
        )
    if kind not in S.FINDING_KINDS:  # pragma: no cover - 防御：映射表写错就炸
        raise AssertionError(f"映射出的 finding kind {kind!r} 不在 schema.FINDING_KINDS 里")
    return kind


# ---------------------------------------------------------------- 引用存在性（FC-02 第二道闸）
#
# 这一节是 `scan_claim` 的补集：`scan_claim` 只查"有没有引用"（形状），
# 查不出"引用的东西在不在"（存在性）。两者缺一不可 ——
# `register_dependency` 早就对 `status='closed'` 用真实数据核过来源
# （见本文件 `:753-768` 的长注释），而 `build_document` 此前没有这道闸：
# `citations=["lit:9999"]` 能通过全部检查、写库、渲染，直到 `verify` 事后
# 才报 `dangling_citation` —— 那时坏引用已经进了稿件。
#
# 引用前缀 → 它必须存在于哪张表。与 `verify.py:585-602` 的
# `dangling_citation` 同口径（`partition(":")` 取前缀、`split("#")` 去页码后缀），
# 因为"什么算一条合法引用"只能有一处定义：写入期比审计期更严是可以的，
# 两处对同一个字符串给出不同结论则不行。
_CITATION_TABLES: dict[str, str] = {
    "rel": "relations",
    "lit": "literature",
    "exp": "experiments",
    "eval": "eval_results",
    # `stmt`（`R-03` / `draft/49` 裁"方案 A"）：命题台账也是可引的对象 ——
    # 一条断言引我们自己的另一条命题（`stmt:0004`）是完全正常的引用，而加它之前
    # 这里没有 `stmt` ⇒ 写入期把合法引用判成"前缀无法识别"（`draft/49:868` 逐字：
    # "照现状实现会错误拒收 `stmt:0004` 这类合法引用（比不查更糟）"）。
    # 为什么是"补齐"而不是新机制：`kind → 表`这层映射本来就是既有机制
    # （`schema.PROCESS_ID_PREFIXES` / `id_kind` 就是按前缀定表的同一条思路）。
    "stmt": "statements",
    # `doc`（主控 2026-10-07 裁 2）：补它之前是「写入期拒 `doc:`、审计期认 `doc:`」
    # （`verify.py` 有 `elif kind == "doc"` 那一档，说明 `doc:` 是有意的合法档：
    # 内部引用 `doc:<稿件>#<断言>@<内容哈希前 16 位>`）。该文件自己的注释逐字写着
    # "两处对同一个字符串给出不同结论则不行" ⇒ 这是"两处词表分家"的第二个实例。
    #
    # 注意：`doc:` 不能只靠下面那条通用存在性检查 —— 它只比 `ref`，而
    # `citation_ref_parts` 把 `#` 之后切掉了 ⇒ 那样只会核"稿件在不在"，
    # 断言与哈希都不看，于是过期哈希会被静默接受（比"错误拒收"更坏）。
    # 所以 `doc:` 走 `_doc_citation_problem` 的三段检查（与 `verify.py:923-961` 同口径；
    # 解析与哈希都复用 `signatures` 那一份实现，不另写一份）。
    "doc": "documents",
}

#: 裸号（4 位十进制、没有前缀）在这张表里不认。
#:
#: 现算证据（2026-10-07，`temp/b_probe_citation_shapes.py` / `b_probe_bare_ids_where.py`）：
#: 两个真实根下 `documents.claims[].citations` 共 593 条引用，全部带前缀
#: （`exp` 382 / `lit` 193 / `rel` 18），裸号 0 条；F 的 `cites` 共 20 条、也全是
#: `lit:`。真机上确实存在裸号的地方只有 4 个字段名自己就钉死了表的 id 列表：
#: `search_requests.result_lit_ids`（→ literature）、`relations.concept_ids` 与
#: `concepts.related_concepts`（→ concepts）、`conjectures.experiment_ids`（→ experiments）
#: —— 那些字段不走本函数，它们的"表"由字段名决定。
#:
#: 所以在这条引用面上裸号没有可定的表：`citations` 是一个混合列表，
#: 元素本身不说自己属于哪张表。让它"按顺序试"（先试 stmt 再试 lit）会静默错配
#: —— 同一个 `0004` 在 A 项目是文献、在 B 项目是命题。宁可不认，也不猜。
_CITATION_BARE_NUMBER = re.compile(r"^\d{4}$")


class DocToolError(ValueError):
    """带结构化明细的校验失败（`guard_result` 会把它原样透出）。

    为什么不能只用裸 `ValueError`：`guard_result` 只能把它压成一句话，
    而"到底哪几条引用不存在"必须逐条列给调用方 —— 只说"校验失败"，
    G 就得自己去猜是哪一条断言、哪一个代号。
    """

    def __init__(self, message: str, *, kind: str = "validation_error", details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.kind = kind
        self.details: dict[str, Any] = dict(details or {})


def citation_ref_parts(citation: Any) -> tuple[str, str]:
    """把一条 citation 拆成 `(前缀, 代号)`。

    这里是转发，不是实现：唯一实现在 `agentflow.textutil.citation_ref_parts`
    （`P-5` 把两份实现合成了一份）。转发体刻意只做"取到别处的对象并原样调用" ——
    在转发之外补默认值、吞异常或改返回值，就等于又长出一份语义不同的实现，
    而那正是 `P-5` 要消掉的东西（`lint_rules` 的 R003 也按这个形状识别转发）。

    曾经这里是第二份实现（抄了 `verify.py` 的 `dangling_citation` 内联解析），
    并带着一条"待修"注释。现在 `verify.py` 与这里调的是同一个函数：改口径只需改一处，
    而且"G 认为合法的引用"与"verify 认为悬空的引用"在结构上不可能再分家。
    """
    return T.citation_ref_parts(citation)


def _doc_citation_problem(raw: str, rows_of: Callable[[str], Iterable[Mapping[str, Any]]]) -> str:
    """`doc:` 内部引用的三段检查（空串 = 通过）。

    三段都要真（与 `verify.py:923-961` 同口径）：稿件在、那条断言在、
    钉的哈希就是目标稿件当前这一版。为什么不能只核第一段：第三段是"引用钉的是哪一版"，
    改稿之后旧引用必须失效 —— 只看"稿件还在"会让一份改过的稿件继续被旧哈希引着，
    而那正是 `draft/30` §T4-A 设计这三段要防的事。

    解析与哈希都复用 `signatures`（`P-5` 的纪律：口径只留一处实现），本函数只做
    "把三段结论翻成一句人话"。
    """
    from .. import signatures as SIG  # 惰性：与 `:1390` 同一处依赖，不新增模块级边

    parts = SIG.parse_doc_ref(raw)
    if parts is None:
        return (f"内部引用形状不对：应为 "
                f"doc:<稿件>#<断言>@<内容哈希前 {SIG.REF_HASH_LEN} 位>")
    tdoc_id, tclaim_id, thash = parts
    doc = next((r for r in rows_of("documents")
                if str(r.get("doc_id")) == str(tdoc_id)), None)
    if doc is None:
        return f"documents 表里没有 doc_id={tdoc_id!r}"
    claims = {str(cl.get("claim_id")) for cl in (doc.get("claims") or [])
              if isinstance(cl, Mapping)}
    if str(tclaim_id) not in claims:
        return f"稿件 {tdoc_id} 里没有断言 {tclaim_id!r}"
    cur = SIG.content_sha256_of(doc)[:SIG.REF_HASH_LEN]
    if str(thash) != cur:
        return (f"钉的是 {thash}，而稿件 {tdoc_id} 当前内容是 {cur} ⇒ "
                "改稿之后旧引用失效（不许静默沿用）")
    return ""


def check_citations(
    rows_of: Any, claims: Sequence[Mapping[str, Any]]) -> dict:
    """逐条核对 citations 指向的对象真的存在。

    三态（这是本函数的核心，不是细节）：

    ==============================  ============================================
    调用方式                          返回
    ==============================  ============================================
    `rows_of` 是读表函数             `checked=True`，`missing` 可能为空（=都查过了）
    `rows_of is None`（没有 store）  `checked=False`，不得读成"引用都存在"
    ==============================  ============================================

    `rows_of(table) -> 行序列`：给的是读表能力而不是 store 实例，
    这样它既能在事务内用 `tx.rows` 跑（拿到一致的快照），也能被单测直接喂假表。

    返回 ``{"checked", "reason", "missing": [{claim_id, citation, kind, ref, why}], "resolved": n}``。
    """
    if rows_of is None:
        return {
            "checked": False,
            "reason": (
                "没有 store ⇒ **没法核对引用是否存在**。这是'没查'，"
                "不是'引用都存在'（两者折叠会让假引用静默落库）"
            ),
            "missing": [],
            "resolved": 0,
        }

    # 只把用得到的表读出来，且每张表只读一次（引用多时不做 O(n²) 扫描）。
    id_sets: dict[str, set[str]] = {}
    missing: list[dict] = []
    resolved = 0
    for i, c in enumerate(claims, 1):
        cid = str((c or {}).get("claim_id") or f"claim-{i}")
        for raw in (c or {}).get("citations") or []:
            kind, ref = citation_ref_parts(raw)
            table = _CITATION_TABLES.get(kind)
            if table is None:
                # 未知前缀：`verify` 对历史数据记 warning，但新写的稿件没有
                # 理由带一个谁也核不了的前缀 ⇒ 写入期 fail-closed。
                #
                # 裸号与"未知前缀"分开报（`R-03` 的三态）：`citation_ref_parts("0004")`
                # 会把整串当 `kind`，于是它也落进这一支 —— 但处置不同：
                # 未知前缀要人确认"这个前缀该不该加进词表"，而裸号只要写成
                # `stmt:0004` 就立刻合法（表由前缀定，不由顺序试）。
                # 两种情形在读数上必须分得开，否则调用方会去改一个没错的前缀词表。
                why = (
                    (f"{str(raw)!r} 是裸号、没有 kind ⇒ 无法定表（`citations` 是混合列表，"
                     f"元素自己不说属于哪张表）⇒ 写成带前缀的形态，例如 `stmt:{str(raw)}`"
                     f"（引我们自己的命题）或 `lit:{str(raw)}`（引一篇文献）；"
                     f"可选前缀：{sorted(_CITATION_TABLES)}"
                     f"（注意 `doc:` 是三段式：`doc:<稿件>#<断言>@<内容哈希前 16 位>`）")
                    if _CITATION_BARE_NUMBER.match(str(raw).strip())
                    else (f"前缀 {kind!r} 无法识别（应为 {sorted(_CITATION_TABLES)}）"
                          "⇒ 无法核对存在性")
                )
                missing.append(
                    {
                        "claim_id": cid,
                        "citation": str(raw),
                        "kind": kind,
                        "ref": ref,
                        "why": why,
                    }
                )
                continue
            if kind == "doc":
                # 内部引用是三段的（稿件 / 断言 / 当前内容哈希前 16 位），
                # 而通用检查只看得到第一段 ⇒ 单独一支（`_doc_citation_problem`）。
                problem = _doc_citation_problem(str(raw), rows_of)
                if problem:
                    missing.append(
                        {
                            "claim_id": cid,
                            "citation": str(raw),
                            "kind": kind,
                            "ref": ref,
                            "why": problem,
                        }
                    )
                else:
                    resolved += 1
                continue
            if table not in id_sets:
                field = str(S.TABLES[table]["id_field"])
                id_sets[table] = {str(r.get(field)) for r in rows_of(table)}
            if ref and ref in id_sets[table]:
                resolved += 1
            else:
                missing.append(
                    {
                        "claim_id": cid,
                        "citation": str(raw),
                        "kind": kind,
                        "ref": ref,
                        "why": f"{table} 表里没有 {S.TABLES[table]['id_field']}={ref!r}",
                    }
                )
    return {
        "checked": True,
        "reason": (
            f"已核 {resolved + len(missing)} 条引用（{resolved} 条命中真实行）；"
            + (f"**{len(missing)} 条指向不存在的东西**" if missing else "没有坏引用")
        ),
        "missing": missing,
        "resolved": resolved,
    }


def classify_proof_location(loc: object, known_ids: Iterable[Any]) -> tuple[str, str]:
    """`proof_location` 的形态分类：整个仓库只有这一份实现（`R2R2-R1`/`R2R2-R2`）。

    为什么必须只有一份：写入期（本模块的 :func:`check_proofs`）与事后门
    （`gates.gate_g3`）对同一个字符串必须给出同一个分类。旧版各写一套正则、
    彼此没有交叉断言，实测同一份数据 18 档里有 9 档分歧 —— 其中最难看的一档是
    "断言自己连 `claim_id` 都没有，`proof_location="claim-1:3"`"：
    写入期报"指向一个不存在的断言"，事后门却判成 `file:line` 并 pass。

    返回 `(kind, base)`：

    - `("self_ref", base)`：`loc` 是本文档里真实存在的 `claim_id`（裸写、或
      `claim_id:行号`）；`base` 是那个 `claim_id`。
    - `("cross_ref", base)`：形态是 `名字:数字`（没有点号后缀 ⇒ 不是文件名），
      但 `base` 不在 `known_ids` 里。两个调用方对此处置不同、分类相同：
      `gate_g3` 报 error（事后分不清"忘了登记"与"根本不存在"，fail-closed）；
      `check_proofs` 报 `proof_location_not_found`（写入期能说得更准）。
      注意：这条差别是刻意的：分类同口径 ≠ 处置同强度。
    - `("file", base)`：其余一切，当路径看。是否真的存在由调用方决定 ——
      `check_proofs` 要求"工作区内、盘上真实存在"，`gate_g3` 只要求"形态可解析"
      （它是事后门，不读盘；这层强弱差别同样刻意的，见 `gate_g3` 的适配说明）。
    """
    rel = str(loc or "").strip().split("#")[0].strip()
    known = {str(x) for x in known_ids}
    #: 形态 `名字:数字`（或 `名字:数字-数字`）—— 本文档内交叉引用的写法。
    is_xref_form = re.match(r"^[^:\\/]+:\d+(-\d+)?$", rel) is not None
    head = rel.rsplit(":", 1)[0] if re.match(r"^.+:\d+(-\d+)?$", rel) else rel
    if rel in known:
        return "self_ref", rel
    if head in known:
        return "self_ref", head
    # 有"点号 + 1–6 位字母数字后缀"就当文件名（`real.lean:3` / `x.py` / `p1.py:12`）。
    looks_like_file = re.search(r"[.][A-Za-z0-9]{1,6}", rel) is not None
    if is_xref_form and not looks_like_file:
        return "cross_ref", head
    # 兜底：既没有扩展名、也没有任何路径分隔符的字符串不是文件描述
    # （`见上文所述` / `see above`）。旧版事后门把它判成 fail，写入期也报
    # `proof_location_not_found`；改成共用一份实现时这里必须先收窄，
    # 否则"抽公共函数"这一次改动会把事后门放宽（实测：旧用例
    # `test_gate_g3_rejects_a_proof_location_that_is_neither_id_nor_path` 变红）。
    if not looks_like_file and not re.search(r"[/\\]", rel):
        return "cross_ref", head
    return "file", (rel.rsplit(":", 1)[0] if re.match(r"^.+:\d+(-\d+)?$", rel) else rel)


def check_proofs(
    rows_of: Any,
    claims: Sequence[Mapping[str, Any]],
    *,
    workspace_root: Any = None,
) -> dict:
    """核对 `evidence_kind="proof"` 的断言真的挂在一份形式化证据上（`D-1`）。

    ## 为什么需要它（`temp/auditD-proof-selfreport.txt` 那次复现）

    `check_citations` 只回答"引用的对象存不存在"。而 `evidence_kind="proof"` 这一档
    在写入期一条判据都没有：实测（`temp/r2-d1-probe.txt`）下面四种形态全部写库成功：

    ① `proof_location="PROOF-DOES-NOT-EXIST.lean:1"`（文件根本不在盘上）；
    ② 连 `proof_location` 都不给；
    ③ 只引 `lit:`（不引任何 `exp:` —— 没有任何实验参与过）；
    ④ 引一条 `evidence_kind="cross_check"` 的数值实验却声称 proof。
    四种的共同后果：`documents` 里出现一条"看起来有形式化背书"的断言，
    而没有任何检查器参与过；下游（报告、gates）把 `evidence_kind` 当证据等级读。
    `verify` 侧只有"引用了 `exp:` 时才查那条实验的等级"（`verify.py` 的
    `proof_claim_rests_on_weaker_evidence`），所以 ③ 那种"一条 exp: 都不引"的形态
    连事后也查不出来。

    ## 四条判据（全部 fail-closed）

    ==========================================  ==========================================
    条件                                        要求
    ==========================================  ==========================================
    `evidence_kind == "proof"`                  必须至少有 1 条 `exp:` 引用
    被引用的 `exp:` 行                          `evidence_kind` 必须是 `"proof"`
    同一条断言                                  必须给出 `proof_location`
    `proof_location`                            必须指向工作区内真实存在的文件；或者
                                                是本文档里真实存在的 `claim_id`（自指）
    ==========================================  ==========================================

    第四条只证明"文件在"，不证明"文件里有那条证明" —— 那是形式化检查器
    （`formalgw`）的事，本函数不冒充它。这两件事必须分开写，否则读者会把
    "文件存在"读成"证明成立"（本项目最忌的那种折叠）。

    注意：第四条曾经有个可被满足的形态缺口（`R2-R1` / `R2-R2`，重审实测）：
    只要 `proof_location` 长得像 `名字:数字`（例如 `not-a-claim:7`）就整条跳过，
    于是"指向一个不存在的断言"与"指向工作区外的文件"两种写法都写库成功。
    现在两条都报问题。

    注意口径的准确说法（`R2R2-R1` 更正）：本函数与事后门 `gates.gate_g3`
    共用同一份形态分类实现（:func:`classify_proof_location`），但判据强度不同 ——
    `check_proofs` 在分类之上加两道（工作区包含性 + 盘上存在性），
    `gate_g3` 只做形态可解析（事后门，不读盘）。所以写入期拦下的，事后门不一定拦得住
    （历史行靠事后门兜）。说"两处口径一致"是错的；准确说法是"同分类、不同强度"。

    ## 三态

    与 `check_citations` 同形：`rows_of is None` ⇒ `checked=False`（没查成，
    不得读成"证据都齐"）。

    返回 ``{"checked", "reason", "problems": [{claim_id, kind, detail}], "resolved"}``。
    """
    if rows_of is None:
        return {
            "checked": False,
            "reason": (
                "没有 store ⇒ **没法核对 proof 级断言的证据**。这是'没查'，"
                "不是'证据都齐'（两者折叠会让自报的 proof 静默落库）"
            ),
            "problems": [],
            "resolved": 0,
        }

    exp_rows = rows_of("experiments")
    exp_by_id: dict[str, Mapping[str, Any]] = {}
    for r in exp_rows:
        rid = str(r.get("experiment_id") or "")
        if rid:
            exp_by_id[rid] = r

    base = Path(workspace_root).resolve() if workspace_root else None
    #: `R2-R1` 修法：本文档真实存在的 claim_id 集合（唯一来源 = claims 自己）。
    #: 旧版在这一段是 `continue` —— 只要 `proof_location` 长得像 `名字:数字` 就整条跳过，
    #: 于是 `not-a-claim:7`（不存在的字符串）也报 `problems=[]` + "proof_location 都成立"。
    #: 分类本身交给 `classify_proof_location`（`gate_g3` 用同一个函数，
    #: 所以两处对同一形态给同一分类；但本函数另外加了两道强度检查，见它的 docstring）。
    known_ids = {str(c.get("claim_id")) for c in claims if (c or {}).get("claim_id")}
    problems: list[dict] = []
    resolved = 0
    for i, c in enumerate(claims, 1):
        c = c or {}
        if str(c.get("evidence_kind") or "") != "proof":
            continue
        cid = str(c.get("claim_id") or f"claim-{i}")
        exp_refs = [
            citation_ref_parts(x)[1]
            for x in (c.get("citations") or [])
            if citation_ref_parts(x)[0] == "exp"
        ]
        if not exp_refs:
            problems.append({
                "claim_id": cid,
                "kind": "proof_claim_without_formal_experiment",
                "detail": (
                    "声称 evidence_kind='proof'，却**一条 `exp:` 引用都没有** ⇒ "
                    "没有任何形式化实验参与过这条断言。proof 级证据必须指向一条"
                    "真的跑过检查器的实验行（FC-22：断言不能强于它的依据）"
                ),
            })
        else:
            for ref in exp_refs:
                row = exp_by_id.get(ref)
                if row is None:
                    # 引用不存在由 `check_citations` 报（它先跑）⇒ 这里不重复报，
                    # 只把它算作"没有可用的形式化证据"。
                    continue
                if str(row.get("evidence_kind") or "") != "proof":
                    problems.append({
                        "claim_id": cid,
                        "kind": "proof_claim_rests_on_weaker_evidence",
                        "detail": (
                            f"声称 evidence_kind='proof'，但它引用的实验 {ref} 的等级是 "
                            f"{str(row.get('evidence_kind'))!r} ⇒ **断言不能强于它的依据**"
                            "（与 `verify.proof_claim_rests_on_weaker_evidence` 同一条口径，"
                            "只是提前到写入现场）"
                        ),
                    })
                else:
                    resolved += 1

        loc = str(c.get("proof_location") or "").strip()
        if not loc:
            problems.append({
                "claim_id": cid,
                "kind": "proof_claim_without_proof_location",
                "detail": (
                    "声称 evidence_kind='proof'，却没有 `proof_location` ⇒ "
                    "读者无法打开任何一个文件去复核。文件位置是形式化证据"
                    "唯一可被外部检查的锚点（`formalgw` 的检查器输出也落在这里）"
                ),
            })
            continue
        # `file:line` / `file` —— 行号部分不参与存在性判断（行号会漂，文件不会）。
        # 分类只有一份实现（`classify_proof_location`）：写入期与事后门 `gate_g3`
        # 必须对同一个字符串给同一个分类（`R2R2-R1` 的修法）。
        kind, rel = classify_proof_location(loc, known_ids)
        if kind == "self_ref":
            resolved += 1
            continue
        if kind == "cross_ref":
            # `R2-R1`：形态像交叉引用、但这个 claim_id 不在本文档里 ⇒ 报问题。
            # 旧版在这里整条 `continue`，于是"指向一个不存在的断言的锚点"写库成功。
            problems.append({
                "claim_id": cid,
                "kind": "proof_location_not_found",
                "detail": (
                    f"`proof_location={loc!r}` 既不是本文档里真实存在的 claim_id"
                    f"（本文档已知 {len(known_ids)} 个），也长得不像文件路径 —— "
                    "这种写法会让读者以为它指向本文档里的某条断言，而那条断言并不存在"
                ),
            })
            continue
        candidate = Path(rel)
        if candidate.is_absolute():
            full = candidate
        elif base is None:
            full = None
        else:
            full = base / rel
        if full is not None and base is not None:
            try:
                full.resolve().relative_to(base)
            except ValueError:
                # `R2-R2`：绝对路径与 `../` 都能"绕过"工作区 —— 旧版只判 `is_file()`，
                # 于是工作区外的文件（如 `../outside.lean`）也算"落点成立"。
                # 这是把"工作区内真实存在的文件"这句声明兑现掉，不是在放宽它。
                problems.append({
                    "claim_id": cid,
                    "kind": "proof_location_outside_workspace",
                    "detail": (
                        f"`proof_location={loc!r}` 解析到工作区之外（工作区根 {base}）⇒ "
                        "报告的可复核范围是工作区，落点跑到外面等于引用了一份读者拿不到的文件"
                    ),
                })
                continue
        if full is None or not full.is_file():
            problems.append({
                "claim_id": cid,
                "kind": "proof_location_not_found",
                "detail": (
                    f"`proof_location={loc!r}` 指向的文件在盘上找不到"
                    f"（按工作区根解析成 {full}）⇒ 这条 proof 级断言没有任何可复核的落点。"
                    "注意这一条只证明'文件在不在'，**不证明**文件里有那条证明"
                ),
            })
        else:
            resolved += 1

    return {
        "checked": True,
        "reason": (
            f"已核 {len(claims)} 条断言里的 proof 级条目；"
            + (f"**{len(problems)} 条不成立**" if problems else "证据锚与 proof_location 都成立")
        ),
        "problems": problems,
        "resolved": resolved,
    }


# ---------------------------------------------------------------- 构造一条断言


def compose_claim(
    text: str,
    *,
    citations: Sequence[str],
    evidence_kind: str,
    section: str,
    is_negative: bool = False,
    negation_kind: str | None = None,
    claim_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    proof_location: str | None = None,
    numeric_evidence: Mapping[str, Any] | None = None,
    counterexamples: Sequence[Any] | None = None,
    frozen: bool = False,
    freeze_reason: str = "",
    allowed_use: str | None = None,
    scope_caveat: str = "",
    revision_hash: str = "",
    errata_ids: Sequence[str] | None = None,
) -> dict:
    """构造一条合规的 claim dict。不合规就在这里抛 `ValueError`。

    ## 闸门在这里，但判据只有一份（`claimanatomy`）

    schema 也会拦（`Document.validate` 有同样的三条硬约束），但它的报错
    只能说到"claims[3] 没有 citations" —— 而在撰写现场，真正需要被指出来的是
    "就是这一句话缺引用"。等写库时才炸，会丢掉"哪一句话出的问题"这个信息。

    本函数不再自己写任何一条检查：它把参数装配成一条 claim，然后交给
    :func:`agentflow.claimanatomy.validate_claim` 判，把第一个 error 抛出来。
    这样 G 与 H 的判据不可能漂移（FC-03 / INVENTORY 4.5#10）。

    ## 强制的规则（全部由 `claimanatomy.CLAIM_FIELDS` 声明）

    - `evidence_kind == "cross_check"` ⇒ 自动填
      ``disclaimer = CROSS_CHECK_DISCLAIMER``。不靠调用方记得写（FC-22）。
    - `is_negative=True` 且没给 `negation_kind` ⇒ 抛（不静默填默认值）：
      "未证明"、"已证否"、"没搜过"是三件不同的事，默认值等于替作者做了
      一个他可能不同意的数学判断。
    - `citations` 为空 ⇒ 抛。无引用的断言在结构上不允许存在（FC-02）。
    - 正文含过度声称措辞而 `evidence_kind != "proof"` ⇒ 抛。
    - `status="作废"` 且既无 `errata_ids` 又无 `freeze_reason` ⇒ 抛
      （作废必须有原因）。
    - `frozen=True` 且 `freeze_reason` 为空 ⇒ 抛。

    ## §8.3 新增的 12 个字段（全部可选）

    `kind` / `status` / `proof_location` / `numeric_evidence` / `counterexamples`
    / `frozen`+`freeze_reason` / `allowed_use` / `scope_caveat` / `revision_hash`
    / `errata_ids` 都是可选参数：不给就不写进 dict（不是写一个假默认值）——
    "没提这件事"与"明确说了没有"必须能分开（三态纪律）。
    给了要用的但取值非法，在构造现场就抛。

    返回的是磁盘形态（正文字段名是 `text`）：`schema.Document.validate`
    逐字读 `c.get("text")`，而它在 FC-27 禁 AI 区、本任务无权改。
    判据层的正名是 `statement`，两者的往返由
    `claimanatomy.migrate_claim` / `to_storage_claim` 一处完成。

    `claim_id` 可省略：此时按内容派生一个稳定代号（同样的内容得到同样的代号）。
    `build_document` 落库时会按顺序补成 `claim-1…claim-N`。
    """
    cites = [str(c) for c in (citations or [])]
    # 这两条先判：它们要的报错信息里带着断言原文，而 claimanatomy 的
    # 通用报错说不出"就是这一句话"。判据没有第二份 —— 只是更早报同一个缺陷。
    if not cites:
        raise ValueError(
            f"断言「{_one_line(text, 60) or '（空）'}」没有任何 citations："
            "**没有引用的断言不允许进入稿件**（FC-02）——数学断言的价值完全取决于它来自哪里"
        )
    if not str(text or "").strip():
        raise ValueError("断言正文不能为空（一份没有正文的断言不是断言）")
    bad = [c for c in cites if not c.strip()]
    if bad:
        raise ValueError(f"citations 含空元素：{bad!r}（空引用等于没有引用）")

    claim: dict[str, Any] = {
        "claim_id": str(claim_id).strip() if claim_id else _claim_id_of(text, cites),
        "section": str(section or ""),
        "text": str(text),
        "evidence_kind": evidence_kind,
        "citations": cites,
        "is_negative": is_negative is True,
        "negation_kind": negation_kind,
        #: cross_check 的"不构成证明"声明由结构强制，不靠人记得写（FC-22）。
        "disclaimer": CROSS_CHECK_DISCLAIMER if evidence_kind == "cross_check" else "",
    }
    #: §8.3 的字段：给了才写（不给就不写键 —— 见 docstring 的三态理由）。
    extra = {
        "kind": kind,
        "status": status,
        "proof_location": proof_location,
        "numeric_evidence": dict(numeric_evidence) if numeric_evidence is not None else None,
        "counterexamples": list(counterexamples) if counterexamples is not None else None,
        "allowed_use": allowed_use,
        "scope_caveat": scope_caveat,
        "revision_hash": revision_hash,
        "errata_ids": list(errata_ids) if errata_ids is not None else None,
        "freeze_reason": freeze_reason,
    }
    for key, val in extra.items():
        if val is None:
            continue
        if key == "freeze_reason" and not str(val).strip():
            continue
        claim[key] = val

    # ---- EE-06 的产出方那一半（`status` / `allowed_use`）：只在该字段真有依据时写。
    #
    # 依据不是这里新造的判据，是 `claimanatomy` 早就写死的两条一致性规则：
    #   * `evidence_kind="proof"` ⇒ `status="证"`
    #     （`claimanatomy` 的规则表逐字："`status=证` + `evidence_kind != proof` ⇒ 不一致"，FC-22）；
    #   * `evidence_kind="cross_check"` ⇒ `status="验"` + `allowed_use="Remark only"`
    #     （`ALLOWED_USE_KINDS` 的 why 逐字："只有数值支撑的结论不得出现在摘要/主结果，必须降为 Remark"）；
    #   * 其余（`heuristic` 或空）⇒ 一个都不写 —— 没有依据就是没有依据。
    #
    # 三态的理由（EE-06 原本的读数是 `status` 0/449、`allowed_use` 0/449 = 这两个字段
    # 从来没有产出方）：正解是"有依据的写、没依据的不写"，不是"给每条补一个默认值"
    # —— 后者会把"从没问过"伪造成"待精化"（`docs/SCHEMA-MIGRATION-PROPOSAL-claims.md` §3.2 逐字）。
    # 调用方显式给了就以调用方为准（上面那个循环已经写进去了，这里不覆盖）。
    if status is None and evidence_kind == "proof":
        claim["status"] = "证"
    elif status is None and evidence_kind == "cross_check":
        claim["status"] = "验"
    if allowed_use is None and evidence_kind == "cross_check":
        claim["allowed_use"] = "Remark only"
    if frozen is True:
        claim["frozen"] = True

    # ---- 唯一的判据来源：claimanatomy。第一个 error 即抛（带断言原文）。
    #
    # 报错里必须带族号 + 该族正例（`draft/39` §3.11 四 D10，用户 2026-10-05 裁）：
    # 旧形态只说"断言不合规：<message>"，模型下一步只能猜该改什么 —— 而 §3.8 的 8 族
    # 本来就是判据的骨架，族号与正例是现成的（`claimanatomy.family_note`，一处派生）。
    check = CA.validate_claim(claim)
    errors = [i for i in check.issues if i.level == "error"]
    if errors:
        by_family = "；".join(f"{i.message} ⇒ {CA.family_note(i.code)}" for i in errors)
        raise ValueError(
            f"断言「{_one_line(text, 60)}」不合规：{by_family}"
            f"（判据出处：claimanatomy.CLAIM_FIELDS；issue code={[i.code for i in errors]}；"
            f"族号={[i.family for i in errors]}）"
        )
    # 自检一次：构造函数若产出了自己都过不了的断言，那是本函数的 bug，不是调用方的。
    if not check.checked:  # pragma: no cover - 判据层崩了才会到这里
        raise AssertionError(f"claimanatomy 检查器自身异常：{check.undecided_reason}")
    return claim


# ---------------------------------------------------------------- 渲染


def render_markdown(
    doc: Mapping[str, Any],
    *,
    dependencies: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """把稿件渲染成人可读的 markdown（中文、表格优先、每条断言带代号）。

    风格沿用 `agent_d.write_report`：中文、表格优先、每条结论带代号。

    渲染层强制包含四张表（不是排版选择，是 FC 的呈现要求）：

    ====================================  ==========================================
    表                                     对应约束
    ====================================  ==========================================
    证据等级统计（proof / cross_check /      FC-10：三档分开计数，禁止单一通过率
    heuristic）
    否定型结论分类（未证明/已证否/未搜索）   FC-25：四种否定分开计数
    依赖表（带 external_unavailable 标注）  FC-23：引用的外部结论必须显式可见
    断言清单（每条带 citations）            FC-02：每条断言都能回答"我引用谁"
    ====================================  ==========================================

    三态纪律：`dependencies=None` 表示调用方没给依赖清单（没查），
    此时表里写"未提供"，而不是写"0 条" —— "没查"和"查了、没有"必须能分开。

    ## 渲染层门（`draft/17` §8.4 的 G14 降级合规门在这里落地）

    `status="作废"` 的断言 —— 以及 `allowed_use="移入 open"` 的断言 ——
    不得出现在正文主结果区（§3 断言清单）。它们被移到附录 A，
    并必须带上撤销原因（`errata_ids` 或 `freeze_reason`）。
    判据只有一份：`claimanatomy.main_body_claims()` / `retracted_claims()`。

    为什么这是渲染层的职责而不是"作者自己记得别写进去"：
    证据等级与生命周期是数据，数据在写库时已经定稿；渲染是它变成"人能读到的正文"的
    最后一道闸 —— 一条已撤销的断言出现在主结果里，比它出现在附录里危险得多，
    而"记得别写"不是结构约束。
    """
    all_claims = [c for c in (doc.get("claims") or []) if isinstance(c, Mapping)]
    # G14 的渲染层落地：正文主结果区只放未被撤销、且未被降级为 open 的断言。
    claims = list(CA.main_body_claims(all_claims))
    retracted = list(CA.retracted_claims(all_claims))
    downgraded_open = [
        c for c in all_claims
        if isinstance(c, Mapping) and c.get("allowed_use") == "移入 open" and not CA.is_retracted(c)
    ]
    doc_id = str(doc.get("doc_id") or "?")
    deps_checked = dependencies is not None
    deps = list(dependencies or [])

    lines: list[str] = []
    lines.append(f"# {doc.get('title') or '（无标题）'}")
    lines.append("")
    lines.append(
        f"- 稿件代号：`doc:{doc_id}`；类型：`{doc.get('kind')}`；"
        f"状态：`{doc.get('status')}`；审校轮次：{doc.get('review_rounds', 0)}"
    )
    lines.append(
        f"- 断言数：{len(all_claims)}（正文主结果区 {len(claims)}、"
        f"**已作废 {len(retracted)}（在附录 A，不在正文）**、"
        f"移入 open {len(downgraded_open)}）；"
        f"依赖数：{len(deps) if deps_checked else '未提供（没查）'}"
    )
    if doc.get("markdown_path"):
        lines.append(f"- 本文件：`{doc['markdown_path']}`")
    lines.append("")

    # ---- 0. 阅读须知
    lines.append("## 0. 阅读须知")
    lines.append("")
    lines.append("1. **每条断言都带引用**（`citations`，形如 `rel:0007` / `lit:0003#p.4` / `exp:0002`）。")
    lines.append("   没有引用的断言在结构上无法进入本稿（`schema.Document.validate` 强制）。")
    lines.append("2. 证据等级只有三档，且**必须分列**：`proof`（形式化检查器核验）、")
    lines.append(f"   `cross_check`（数值/穷举交叉验证）、`heuristic`（启发式）。")
    lines.append(f"3. **`cross_check` 不是证明**：这类断言后面自动附「{CROSS_CHECK_DISCLAIMER}」。")
    lines.append("4. 否定型结论分四类：未证明 / 已证否 / 未搜索 / 无本地证据 —— 它们的含义完全不同，")
    lines.append("   合并计数会让人把「没搜过」读成「已证否」。")
    lines.append("")

    # ---- 1. 证据等级统计（FC-10）
    ek_count: dict[str, int] = {k: 0 for k in S.EVIDENCE_KINDS}
    unknown_ek = 0
    for c in claims:
        ek = str(c.get("evidence_kind") or "")
        if ek in ek_count:
            ek_count[ek] += 1
        else:
            unknown_ek += 1
    lines.append("## 1. 证据等级统计（三分档，不是单一通过率）")
    lines.append("")
    lines.append("| 证据等级 | 含义 | 条数 |")
    lines.append("|---|---|---|")
    for k in S.EVIDENCE_KINDS:
        lines.append(f"| `{k}` | {EVIDENCE_LABELS.get(k, '')} | {ek_count[k]} |")
    if unknown_ek:
        lines.append(f"| （非法等级） | 不在 {S.EVIDENCE_KINDS} 里的取值 | {unknown_ek} |")
    lines.append("")
    lines.append(
        "说明：一个「通过率 80%」会掩盖「另外 20% 是失败还是没校验」这个决定性差异，"
        "因此这里**只报三个分档计数**（FC-10）。"
    )
    lines.append("")

    # ---- 2. 否定型结论分类（FC-25）
    neg_count: dict[str, int] = {k: 0 for k in S.NEGATION_KINDS}
    neg_unclassified = 0
    positive = 0
    for c in claims:
        if c.get("is_negative") is True:
            nk = str(c.get("negation_kind") or "")
            if nk in neg_count:
                neg_count[nk] += 1
            else:
                neg_unclassified += 1
        else:
            positive += 1
    lines.append("## 2. 否定型结论分类（未证明 / 已证否 / 未搜索 必须分开）")
    lines.append("")
    lines.append("| 分类 | 含义 | 条数 |")
    lines.append("|---|---|---|")
    for k in S.NEGATION_KINDS:
        lines.append(f"| `{k}`（{NEGATION_LABELS.get(k, '')}） | 见 schema.NEGATION_KINDS | {neg_count[k]} |")
    if neg_unclassified:
        lines.append(f"| （未分类） | 否定型却没有合法 `negation_kind` —— **违规** | {neg_unclassified} |")
    lines.append(f"| （非否定型断言） | 本表不计入 | {positive} |")
    lines.append("")
    lines.append(
        "说明：「未证明」与「已证否」在数学上有天壤之别；检索上「库里没有」与「这世上没有」也是两件事（FC-25）。"
    )
    lines.append("")

    # ---- 3. 断言清单
    lines.append("## 3. 断言清单（每条带引用）")
    lines.append("")
    by_section: dict[str, list[Mapping[str, Any]]] = {}
    for c in claims:
        by_section.setdefault(str(c.get("section") or "（未分节）"), []).append(c)
    for i, (sec, group) in enumerate(by_section.items(), 1):
        lines.append(f"### 3.{i} {sec}")
        lines.append("")
        for c in group:
            cid = str(c.get("claim_id") or "?")
            ek = str(c.get("evidence_kind") or "")
            cites = [str(x) for x in (c.get("citations") or [])]
            lines.append(f"**`{cid}`**｜证据等级 `{ek}`｜引用：{('、'.join(f'`{x}`' for x in cites)) or '**（无引用 —— 违规）**'}")
            lines.append("")
            # ---- §8.3 的生命周期字段（有才显示；没有就不写，见三态纪律）
            meta: list[str] = []
            if c.get("kind"):
                meta.append(f"类型 `{c.get('kind')}`")
            if c.get("status"):
                meta.append(f"生命周期 `{c.get('status')}`")
            if c.get("allowed_use"):
                meta.append(f"可用范围 `{c.get('allowed_use')}`")
            if c.get("proof_location"):
                meta.append(f"证明位置 `{c.get('proof_location')}`")
            if c.get("revision_hash"):
                meta.append(f"版本 hash `{c.get('revision_hash')}`")
            if c.get("frozen") is True:
                meta.append(f"已冻结（理由：{_one_line(c.get('freeze_reason'), 60) or '**未登记 —— 违规**'}）")
            if meta:
                lines.append("- " + "；".join(meta))
                lines.append("")
            if c.get("scope_caveat"):
                lines.append(f"- **适用范围限定**：{_one_line(c.get('scope_caveat'), 160)}")
                lines.append("")
            ne = c.get("numeric_evidence")
            if isinstance(ne, Mapping):
                lines.append(
                    "- 数值证据：`script={}`、`range={}`、`n_cases={}`、`n_counterexamples={}`".format(
                        ne.get("script"), ne.get("range"), ne.get("n_cases"), ne.get("n_counterexamples")
                    )
                )
                lines.append("")
            if c.get("counterexamples"):
                lines.append(
                    f"- **反例 {len(list(c['counterexamples']))} 条**："
                    + "、".join(_one_line(x, 60) for x in list(c["counterexamples"])[:5])
                )
                lines.append("")
            if c.get("errata_ids"):
                lines.append("- 相关勘误：" + "、".join(f"`{x}`" for x in list(c["errata_ids"])))
                lines.append("")
            lines.append(CA.claim_statement(c))
            lines.append("")
            if ek == "cross_check":
                d = str(c.get("disclaimer") or "").strip()
                lines.append(
                    f"> ⚠️ {d or '（缺 disclaimer —— 违规：cross_check 必须声明「' + CROSS_CHECK_DISCLAIMER + '」）'}"
                )
                lines.append("")
            if c.get("is_negative") is True:
                nk = str(c.get("negation_kind") or "")
                lines.append(f"- 否定分类：`{nk}`（{NEGATION_LABELS.get(nk, '未分类/非法')}）")
                lines.append("")
    if not claims:
        lines.append("（本稿没有任何断言 —— 那它不是一份稿件。）")
        lines.append("")

    # ---- 4. 依赖（FC-23）
    lines.append("## 4. 依赖（FC-23：引用的外部结论必须显式标记）")
    lines.append("")
    if not deps_checked:
        lines.append(
            "> 依赖清单**未提供**（本次渲染没有查依赖）—— 这**不等于**「依赖都闭合」。"
        )
        lines.append("")
    else:
        lines.append("| 依赖代号 | kind | 标签 | 状态 | 来源 | 页码范围 | 未闭合原因 |")
        lines.append("|---|---|---|---|---|---|---|")
        if not deps:
            lines.append("| - | - | （本稿当前登记的依赖：**0 条**） | - | - | - | - |")
        for d in deps:
            st = str(d.get("status") or "")
            src = d.get("source_lit_id") or d.get("source_experiment_id") or "-"
            pr = d.get("page_range") or {}
            pr_label = pr.get("label") or (
                f"pp. {pr.get('start')}-{pr.get('end')}" if pr.get("start") else "-"
            )
            mark = "⚠️ **外部不可得**" if st == "external_unavailable" else ("❗悬空" if st == "dangling" else "")
            lines.append(
                f"| `dep:{d.get('dep_id')}` | {d.get('kind')} | {_one_line(d.get('label'), 60)} | "
                f"`{st}`{(' ' + mark) if mark else ''} | {src} | {pr_label} | "
                f"{_one_line(d.get('status_reason'), 80) or '-'} |"
            )
        lines.append("")
        ext = [d for d in deps if str(d.get("status")) == "external_unavailable"]
        dang = [d for d in deps if str(d.get("status")) == "dangling"]
        if ext:
            lines.append(
                f"> ⚠️ **本稿有 {len(ext)} 条依赖引用了本项目拿不到的来源**（表中带「外部不可得」者）："
                + "、".join(f"`dep:{d.get('dep_id')}`（{_one_line(d.get('label'), 40)}）" for d in ext)
            )
            lines.append("> ")
            lines.append(
                "> 这些前提**没有被本项目独立验证**：结论的适用范围必须按「假设」读，"
                "而不是按「已证事实」读（FC-23 的真实案例：论文里 `companion book [6, Thm 6.5]` 给出 "
                "Spec S̃_m = [−m, m]，而那本书不在本项目可得范围内）。"
            )
            lines.append("")
        if dang:
            lines.append(
                f"> ❗ 本稿还有 {len(dang)} 条依赖**悬空**（既没闭合、也没说明为什么拿不到）："
                + "、".join(f"`dep:{d.get('dep_id')}`" for d in dang)
            )
            lines.append("")

    # ---- 5. 未解决的问题
    lines.append("## 5. 未解决的问题")
    lines.append("")
    probs = [str(x) for x in (doc.get("open_problems") or [])]
    if probs:
        for p in probs:
            lines.append(f"- {p}")
    else:
        lines.append("（无）—— 注意：这只表示本稿没有登记开放问题，不表示所有问题都已解决。")
    lines.append("")

    # ---- 附录 A：已作废的断言（G14：它们不得出现在正文主结果区）
    #
    # 为什么正文里要显式承认有多少条被移出去了：只把作废断言删掉，
    # 读者会把"作者改过主意"这件事读成"这些结论从来没存在过"。
    # 参考体例里 `作废` 是常规状态，它的价值恰恰在于"看得见"。
    lines.append("## 附录 A. 已作废的断言（不在正文主结果区）")
    lines.append("")
    if not retracted and not downgraded_open:
        lines.append("（无。本稿没有 `status='作废'` 的断言。）")
        lines.append("")
    if retracted:
        lines.append(
            f"> ⚠️ 本稿有 **{len(retracted)} 条断言已作废**（`status='作废'`）。"
            "它们被**排除在正文主结果区之外**（`claimanatomy.main_body_claims`），"
            "并在此逐条留痕 —— 一条已撤销的断言被当成有效结论引用，是本项目最不愿看到的失效形态。"
        )
        lines.append("")
        lines.append("| 断言 | 撤销原因 | 原文（截断） |")
        lines.append("|---|---|---|")
        for c in retracted:
            cid = str(c.get("claim_id") or "?")
            reason = CA._retraction_reason(c) or "**（未登记原因 —— 违规）**"
            lines.append(
                f"| `{cid}` | {_one_line(reason, 80)} | {_one_line(CA.claim_statement(c), 120)} |"
            )
        lines.append("")
    for c in downgraded_open:
        lines.append(
            f"- `{c.get('claim_id')}` 被降级为 `allowed_use='移入 open'`："
            f"{_one_line(CA.claim_statement(c), 100)}（它属于开放问题，不属于本文的结论）"
        )
    if downgraded_open:
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 落库


def normalize_claims(claims: Sequence[Mapping[str, Any]]) -> list[dict]:
    """补齐/规范化断言，并用 `scan_claim` 逐条把关。有任何 error 级发现即抛。

    这里刻意不自动补 disclaimer（虽然 `compose_claim` 会补）：
    构造函数负责"帮作者构造出合规的断言"，落库闸门负责"拒绝不合规的断言"。
    让闸门顺手把违规项改好，会让"调用方漏写了声明"这件事从此不可见 ——
    那正是本框架最忌讳的静默修复。
    """
    if not claims:
        raise ValueError("claims 不能为空 —— 一份没有任何断言的稿件不是稿件")
    out: list[dict] = []
    seen: set[str] = set()
    # ---- `claim_id` 由脚本分配（`draft/39` §3.11 四 D10，用户 2026-10-05 裁）
    #
    # 为什么把模型写的那一个丢掉：第 8 族（同一稿件里代号重复）本该是判据，
    # 但它可以退化成"根本不可能发生"—— 只要代号不由模型发。语料里已经出现过
    # 重复代号的形态（同一次生成里两条断言都叫 `claim-2`），而"重复代号"的后果是
    # 审校定位失效（`proof_location` 指向两条里的一条，没人知道哪条）。
    # 丢掉不等于丢弃信息：模型自写的代号被当作别名，本文档内对它的引用
    # （`proof_location="claim-3:12"`）按别名表改写成本脚本分配的代号。
    # 别名不落进行里（它是"被丢掉的那个"）：落进去会变成 claimanatomy 的
    # `undeclared_field`（未声明字段），而那是第 1 族的告警 —— 一条本该干净的稿件
    # 会因为"我们记下了自己丢掉的东西"而多出一堆 warning。
    supplied_to_allocated: dict[str, str] = {}
    for i, c in enumerate(claims, 1):
        if isinstance(c, Mapping):
            given = str(c.get("claim_id") or "").strip()
            if given:
                supplied_to_allocated.setdefault(given, f"claim-{i}")
    for i, c in enumerate(claims, 1):
        if not isinstance(c, Mapping):
            raise ValueError(f"claims[{i}] 必须是对象，收到 {type(c).__name__}")
        row = dict(c)
        cid = f"claim-{i}"
        row["claim_id"] = cid
        # 本文档内的自指（`proof_location="claim-3:12"`）按别名表改写：
        # 不改写的话，"代号由脚本发"会把模型自己写的引用全部打断（那是把一条判据
        # 换成另一种坏法，而不是消除坏法）。
        loc = str(row.get("proof_location") or "").strip()
        if loc:
            base, _, rest = loc.partition(":")
            if base in supplied_to_allocated:
                row["proof_location"] = (supplied_to_allocated[base]
                                         + (f":{rest}" if rest else ""))
        row["section"] = str(row.get("section") or "")
        row["is_negative"] = row.get("is_negative") is True
        row.setdefault("negation_kind", None)
        # 正文字段名归一：判据层的正名是 `statement`，磁盘形态是 `text`
        # （`schema.Document.validate` 读 `text`，而它在禁 AI 区）。
        # 这一处转换是全项目唯一的迁移点（`claimanatomy.migrate_claim`）。
        row["text"] = CA.claim_statement(row)
        row["citations"] = [str(x) for x in (row.get("citations") or [])]
        if cid in seen:
            raise ValueError(f"claims 出现重复 claim_id：{cid}（重复代号会让审校无法定位）")
        seen.add(cid)
        check = scan_claim(row)
        if check["error_count"]:
            # 逐条带上族号 + 该族正例（`draft/39` §3.11 四 D10）：这条路才是落库现场
            # 真正会撞上的那道门（`build_document` → 这里），而被拒的写作者需要的是
            # "改哪一栏、照什么写"，不是一句"未通过机械检查"。
            detail = "；".join(
                f"{f['message']} ⇒ {CA.family_note(f.get('code') or '')}"
                for f in check["findings"] if f["level"] == "error")
            families = [f.get("family") for f in check["findings"] if f["level"] == "error"]
            # 报错里必须带断言原文：只说 `claims[3] 不合规`，人还得回去数第 3 条是哪条。
            # 原文放前面（"就是这句话出的问题"才是现场最需要的信息）。
            raise ValueError(
                f"断言原文：「{_one_line(row['text'], 80)}」"
                f"（claims[{i}]／{cid}）未通过机械检查：{detail}（族号={families}）"
            )
        out.append(row)
    return out


def build_document(
    store: Any,
    kind: str,
    title: str,
    *,
    claims: Sequence[Mapping[str, Any]],
    sections: Sequence[Mapping[str, Any]] | None = None,
    open_problems: Sequence[str] | None = None,
    out_path: Any = None,
    workspace_root: Any = None,
    actor: str = "agent-G",
    default_subdir: str = "documents",
) -> dict:
    """写一行 `documents`，并把 markdown 渲染到工作区内。返回落库后的行 dict。

    顺序刻意如此：先逐条机械检查 → 再核引用是否存在 → 再分配 ID → 再渲染 → 最后提交。
    这样任何一条不合规的断言、任何一条指向不存在对象的引用，都不会换来一个
    "半成品稿件 + 一个已经烧掉的 doc_id"。

    为什么 markdown 在工作区内渲染（而不是返回字符串了事）：`markdown_path` 是
    FC-02 追溯链的一环 —— 稿件必须有一个可被人打开的落点，
    否则"H 审的是哪个版本"就无法回答。

    ## 引用必须真的存在（本函数曾经的缺陷）

    `scan_claim` 只查"`citations` 非空"，从不解析 `lit:` / `rel:` / `exp:`
    指向的对象是否存在。于是 `citations=["lit:9999"]` 会照样写库 + 渲染，
    直到事后 `verify` 才报 `dangling_citation` —— 而那时坏引用已经进了稿件。
    现在写库前用 `check_citations` 核一遍四张表；有坏引用就整笔不写，
    并把每一条坏引用逐条列进失败详情（`kind="dangling_citation"`）。

    ## `evidence_kind="proof"` 的证据锚（`D-1`）

    引用存在还不够：一条自报 `proof` 的断言即使引用都存在，也可能"没有任何
    形式化检查参与过"（实测四种形态全部写库成功，见 `temp/r2-d1-probe.txt`）。
    所以紧接着再跑 `check_proofs`：必须有 `exp:` 引用、那条实验必须是 proof 级、
    必须有 `proof_location`、且那个文件必须真的在盘上。
    """
    if kind not in S.DOC_KINDS:
        raise ValueError(f"kind 必须是 {S.DOC_KINDS} 之一，收到 {kind!r}")
    if not str(title or "").strip():
        raise ValueError("title 不能为空")
    norm = normalize_claims(claims)
    secs: list[dict] = []
    for i, s in enumerate(sections or [], 1):
        if not isinstance(s, Mapping) or not str(s.get("heading") or "").strip():
            raise ValueError(f"sections[{i}] 必须是含 heading 的对象")
        secs.append({"heading": str(s.get("heading")), "body": str(s.get("body") or "")})
    probs = [str(x) for x in (open_problems or [])]

    root = Path(workspace_root).resolve() if workspace_root else Path(store.root).resolve()
    # 引用核对要读 literature/relations/experiments/eval_results ⇒ 一并纳入锁集合。
    # `Store.tx` 按 LOCK_ORDER 固定顺序加锁（store.py:318），所以多声明几张表
    # 不会引入加锁顺序问题；而放在同一笔事务里，"核引用"与"写 documents"
    # 看到的是同一个快照（在事务外先查、再另开事务写，中间有 TOCTOU 窗口）。
    with store.tx(
        "documents",
        "literature",
        "relations",
        "experiments",
        "eval_results",
        actor=actor,
        note="build_document",
    ) as tx:
        cites = check_citations(tx.rows, norm)
        if not cites["checked"]:
            # 理论上不可达（store 非空就 checked=True）；留着是为了让"没法查"这条
            # 状态有出口，而不是在某次重构里悄悄退化成"当作查过了"。
            raise DocToolError(
                f"无法核对引用是否存在：{cites['reason']}",
                kind="citation_check_not_possible",
                details={"created": False, "citation_check": cites},
            )
        if cites["missing"]:
            bad = "；".join(
                f"[{m['claim_id']}] {m['citation']!r}：{m['why']}" for m in cites["missing"]
            )
            raise DocToolError(
                f"稿件里有 {len(cites['missing'])} 条引用指向**不存在**的对象，整笔不写库：{bad}。"
                "引用一个不存在的代号，等于把外部结论当成自己的结论（FC-02）——"
                "`scan_claim` 只看 citations 非空，查不出这一点，所以必须在这里用真实数据核。",
                kind="dangling_citation",
                details={"created": False, "citation_check": cites, "missing": cites["missing"]},
            )
        # ---- `D-1`：proof 级断言必须真的挂在一份形式化证据上（判据见 `check_proofs`）
        proofs = check_proofs(tx.rows, norm, workspace_root=root)
        if not proofs["checked"]:
            raise DocToolError(
                f"无法核对 proof 级断言的证据：{proofs['reason']}",
                kind="proof_check_not_possible",
                details={"created": False, "proof_check": proofs},
            )
        if proofs["problems"]:
            bad = "；".join(f"[{p['claim_id']}] {p['detail']}" for p in proofs["problems"])
            raise DocToolError(
                f"稿件里有 {len(proofs['problems'])} 条 proof 级断言的证据不成立，整笔不写库：{bad}。"
                "`evidence_kind='proof'` 享受的是最高一档的证据待遇，所以在写入现场就要"
                "指向一条真的跑过检查器的实验行、并且给出一个盘上真的存在的落点 —— "
                "否则报告里会出现'看起来有形式化背书'的结论（`D-1`）。",
                kind="proof_evidence_not_found",
                details={"created": False, "proof_check": proofs, "problems": proofs["problems"]},
            )
        doc_id = tx.alloc_id("doc")
        rel, absolute = resolve_out_path(root, out_path, doc_id, default_subdir)
        # ---- 覆盖守卫（`draft/37` §91 的真机读数：一次调用把交付物覆盖成生成物）
        #
        # T1 第 5 趟：主控传 `out_path="out/paper/main.tex"`（它把"生成 markdown 的落点"
        # 当成了"论文本体该写在哪"，而那个参数当时没有任何描述），于是这一动作把
        # 26,155 字节的论文正文整份覆盖成 3,992 字节的台账稿（`render_markdown` 的产物）。
        # 后果不可逆：那一趟此后 28 步都在试图把正文从 `source/` 拼回来，
        # 26 KB 的 `fs.write` 被输出额度截断 ⇒ 连续三次坏 JSON ⇒ 整趟作废（exit 1）。
        #
        # 判据：允许覆盖本动作自己的产物（`documents` 里某行的 `markdown_path`，
        # 也就是 `refresh_markdown` 那条路），其余既有文件一律拒 —— 它们不是生成物，
        # 我们没有资格拿一份渲染结果去换掉它们。判据放在写之前（不是写完再警告），
        # 因为"覆盖了再道歉"对论文正文没有意义。
        ours = {str(r.get("markdown_path") or "") for r in tx.rows("documents")}
        if absolute.exists() and rel not in ours:
            size = absolute.stat().st_size
            raise DocToolError(
                f"拒绝覆盖 {rel}（已存在，{size} 字节，且它不是任何 documents 行的 "
                "`markdown_path`）：这个参数是生成 markdown 的落点，不是主稿 —— "
                "把它指到 `out/paper/main.tex` 会把论文本体换成一份台账稿，"
                "而那是不可逆的（真机实测：26 KB 正文被覆盖成 4 KB，那一趟就此作废）。"
                "要写主稿请用 `fs.edit` / `fs.write`；要生成稿件就换一个没被占用的路径"
                "（缺省是 `<工作区>/<documents>/<doc_id>.md`）。",
                kind="out_path_would_clobber",
                details={"created": False, "out_path": rel, "bytes": size,
                         "is_registered_markdown": False},
            )
        row = S.Document(
            doc_id=doc_id,
            kind=kind,
            title=str(title),
            markdown_path=rel,
            sections=secs,
            claims=norm,
            open_problems=probs,
            status="draft",
            review_rounds=0,
            revision=1,
            created_at=S.now_iso(),
            updated_at=S.now_iso(),
            created_by=actor,
        )
        # 内容哈希由写侧算一次（`draft/30` §T4-A）：没有它，审批与内部引用都
        # 钉不住"审/引的是哪一版"。算法只有一份实现（`signatures`），读侧会重算比对。
        from .. import signatures as SIG

        row.content_sha256 = SIG.content_sha256_of(row.to_dict())
        # 显式校验一次，让错误在写入前带着"哪一句话"抛出，而不是等到提交阶段
        # 变成一句泛泛的 "documents.rows[0] 校验失败"。
        row.validate()
        payload = row.to_dict()
        markdown = render_markdown(payload, dependencies=[])
        tx.upsert("documents", payload)
        # 文件写在事务体内：写失败 ⇒ 事务回滚 ⇒ 不会留下"有行没文件"的悬空指针。
        # （反过来"有文件没行"最多是一个无主的 md，可人工清理，危害小得多。）
        try:
            absolute.parent.mkdir(parents=True, exist_ok=True)
            absolute.write_text(markdown, encoding="utf-8")
        except OSError as e:
            raise ValueError(f"渲染 markdown 失败（{absolute}）：{type(e).__name__}: {e}") from e
    return payload


def register_dependency(
    store: Any,
    used_by: str,
    kind: str,
    label: str,
    *,
    source_lit_id: str | None = None,
    source_experiment_id: str | None = None,
    page_range: Any = None,
    quote: str = "",
    status: str = "dangling",
    status_reason: str = "",
    actor: str = "agent-G",
) -> dict:
    """登记一条外部依赖（FC-23）。返回落库后的行 dict。

    ## 为什么"closed 必须指向已入库来源"要在这里再核一遍

    `schema.Dependency.validate` 只能检查"`status='closed'` 时字段非空" ——
    它看不见 `literature` / `experiments` 表，因此一个不存在的 lit_id 也能通过 schema。
    而"这个 lit_id 真的存在"正是"依赖闭合"的全部含义。
    所以第一道闸必须在 G 手里用真实数据核：字段非空 ≠ 来源存在。

    第二道闸（依赖集的可查询闭合性）由 H/verify 侧的重算负责 —— 两道闸缺一不可：
    一个查"引用长得对不对"，一个查"引用的东西在不在"。
    """
    if not str(used_by or "").strip():
        raise ValueError("used_by 不能为空（依赖必须挂到某个具体的使用点，如 'doc:0001#claim-3'）")
    if kind not in S.DEP_KINDS:
        raise ValueError(f"kind 必须是 {S.DEP_KINDS} 之一，收到 {kind!r}")
    if status not in S.DEP_STATUSES:
        raise ValueError(f"status 必须是 {S.DEP_STATUSES} 之一，收到 {status!r}")
    if not str(label or "").strip():
        raise ValueError("label 不能为空（依赖要说清「引的是哪一条」，否则接手的人无从查起）")
    pr = _coerce_page_range(page_range)

    if status in ("dangling", "external_unavailable") and not str(status_reason or "").strip():
        raise ValueError(
            f"status={status!r} 时必须写 status_reason。"
            "只标一个状态而不说原因，等于把问题记了一笔却没人能接手"
            + ("（external_unavailable 尤其要说清「是哪本书/哪篇、为什么拿不到」）" if status == "external_unavailable" else "")
        )
    if status == "closed" and not (source_lit_id or source_experiment_id):
        raise ValueError("status='closed' 必须指向一个已入库来源（source_lit_id 或 source_experiment_id）")
    if kind == "experiment" and not source_experiment_id:
        raise ValueError("kind='experiment' 的依赖必须给 source_experiment_id")
    if source_lit_id is not None:
        S.require_id(source_lit_id, "source_lit_id")
    if source_experiment_id is not None:
        S.require_id(source_experiment_id, "source_experiment_id")

    with store.tx(
        "dependencies", "literature", "experiments", actor=actor, note="register_dependency"
    ) as tx:
        if status == "closed":
            if source_lit_id is not None and not any(
                str(r.get("lit_id")) == source_lit_id for r in tx.rows("literature")
            ):
                raise ValueError(
                    f"status='closed' 但 literature 表里没有 lit_id={source_lit_id!r}。"
                    "**schema 查不出这一点**（它只能查'字段非空'）—— 依赖闭合必须由 G 用真实数据核："
                    "引用一篇不存在的文献，等于把外部结论当成了自己的结论（FC-23）"
                )
            if source_experiment_id is not None and not any(
                str(r.get("experiment_id")) == source_experiment_id for r in tx.rows("experiments")
            ):
                raise ValueError(
                    f"status='closed' 但 experiments 表里没有 experiment_id={source_experiment_id!r}。"
                    "依赖闭合必须核到**已入库**的来源（FC-23）"
                )
        dep_id = tx.alloc_id("dep")
        row = S.Dependency(
            dep_id=dep_id,
            used_by=str(used_by),
            kind=kind,
            label=str(label),
            status=status,
            source_lit_id=source_lit_id,
            source_experiment_id=source_experiment_id,
            page_range=pr,
            quote=str(quote or ""),
            status_reason=str(status_reason or ""),
            created_at=S.now_iso(),
            created_by=actor,
        )
        row.validate()
        payload = row.to_dict()
        tx.upsert("dependencies", payload)
    return payload


def list_documents(
    store: Any, *, status: str | None = None, kind: str | None = None
) -> dict:
    """只读列举稿件。返回 ``{"count", "documents"}``。"""
    if status is not None and status not in S.DOC_STATUSES:
        raise ValueError(f"status 必须是 {S.DOC_STATUSES} 之一，收到 {status!r}")
    if kind is not None and kind not in S.DOC_KINDS:
        raise ValueError(f"kind 必须是 {S.DOC_KINDS} 之一，收到 {kind!r}")
    out: list[dict] = []
    for r in sorted(store.rows("documents"), key=lambda x: str(x.get("doc_id"))):
        if status is not None and r.get("status") != status:
            continue
        if kind is not None and r.get("kind") != kind:
            continue
        out.append(
            {
                "doc_id": r.get("doc_id"),
                "kind": r.get("kind"),
                "title": r.get("title"),
                "status": r.get("status"),
                "review_rounds": r.get("review_rounds"),
                "claim_count": len(r.get("claims") or []),
                "markdown_path": r.get("markdown_path"),
            }
        )
    return {"count": len(out), "documents": out}


# ---------------------------------------------------------------- 工具装配


def guard_result(fn: Any) -> Any:
    """把"业务失败"变成结构化结果，把"调用方写错了"与"环境故障"分开报。

    这里必须显式捕获 `StoreError`：它是 `RuntimeError`（`store.py:56`），
    而原先只捕 `ValueError`/`OSError` —— 于是 `store.rows`/`store.tx` 的
    "表坏了 / 锁超时 / 编号用尽"会逃出工具层，被 `base.py:381-382` 兜成一个
    没有任何类型信息的 `kind="unexpected"`，在脚本模式（直接调 handler）下更是
    直接抛。环境故障与调用方写错是两件事，必须能分开。
    """
    try:
        return ok(fn())
    except DocToolError as e:
        # 带结构化明细的校验失败：逐条明细原样透出（`missing` 等）
        return fail(str(e), kind=e.kind, **e.details)
    except ValueError as e:
        return fail(f"校验失败：{e}", kind="validation_error")
    except StoreError as e:
        return fail(f"存储故障：{e}", kind="store_error")
    except OSError as e:
        return fail(f"文件操作失败：{type(e).__name__}: {e}", kind="io_error")


@tool(
    "doc.scan_claim",
    "对一条断言做机械检查：有无引用、证据等级是否被夸大、否定是否分类",
    {
           "type": "object",
           "properties": {"claim": {"type": "object"}},
           "required": ["claim"],
           "additionalProperties": False,
           },
    side_effect="none",
    roles=_ROLES,
    returns="{'checked','claim_id','ok','findings','error_count','warning_count'}",
    tags=("document", "gate"),
)
def _doc_scan_claim(claim):
    """doc.scan_claim 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（无）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return ok(scan_claim(claim))

@tool(
    "doc.compose_claim",
    (
            "构造一条合规断言：cross_check 自动补「不构成证明」声明；无引用/否定未分类/过度声称/"
            "作废无原因在构造时就抛错（不等写库）。可带 §8.3 的生命周期字段"
            "（kind/status/proof_location/numeric_evidence/counterexamples/frozen/"
            "allowed_use/scope_caveat/revision_hash/errata_ids）"
            ),
    {
           "type": "object",
           "properties": {
            "text": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "evidence_kind": {"type": "string", "enum": list(S.EVIDENCE_KINDS)},
            "section": {"type": "string"},
            "is_negative": {"type": "boolean"},
            "negation_kind": {"type": "string", "enum": list(S.NEGATION_KINDS)},
            "claim_id": {"type": "string"},
    # ---- §8.3 的生命周期字段（全部可选；判据见 claimanatomy.CLAIM_FIELDS）
            "kind": {"type": "string", "enum": list(CA.CLAIM_KINDS)},
            "status": {"type": "string", "enum": list(CA.CLAIM_STATUSES)},
            "proof_location": {"type": "string"},
            "numeric_evidence": {"type": "object"},
            "counterexamples": {"type": "array"},
            "frozen": {"type": "boolean"},
            "freeze_reason": {"type": "string"},
            "allowed_use": {"type": "string", "enum": list(CA.ALLOWED_USE_KINDS)},
            "scope_caveat": {"type": "string"},
            "revision_hash": {"type": "string"},
            "errata_ids": {"type": "array", "items": {"type": "string"}},
           },
           "required": ["text", "citations", "evidence_kind", "section"],
           "additionalProperties": False,
           },
    side_effect="none",
    roles=_ROLES,
    # 键名逐个从实现读出（`compose_claim`）：必有的 8 个键列在这里；
    # §8.3 的字段（kind/status/proof_location/numeric_evidence/counterexamples/
    # allowed_use/scope_caveat/revision_hash/errata_ids/freeze_reason/frozen）
    # 给了才写 —— 所以它们不进这份键集合（否则就成了"承诺了却不保证给"）。
    returns=(
            "{'claim_id','section','text','evidence_kind','citations','is_negative',"
            "'negation_kind','disclaimer'}（合规的 claim dict）；带 §8.3 字段时原样透出。"
            "失败：ok=False + kind=validation_error + message（含 issue code）"
            ),
    tags=("document", "compose"),
)
def _doc_compose_claim(**kw):
    """doc.compose_claim 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（无）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return guard_result(lambda: compose_claim(**kw))

@tool(
    "doc.list_documents",
    "只读列举稿件（代号/类型/标题/状态/审校轮次/断言数与 markdown 路径）",
    {
           "type": "object",
           "properties": {
            "status": {"type": "string", "enum": list(S.DOC_STATUSES)},
            "kind": {"type": "string", "enum": list(S.DOC_KINDS)},
           },
           "additionalProperties": False,
           },
    side_effect="read",
    roles=_ROLES,
    returns="{'count','documents':[{'doc_id','kind','title','status','review_rounds','claim_count','markdown_path'}]}",
    tags=("document", "read"),
)
def _doc_list_documents(_not_wired, store, status=None, kind=None):
    """doc.list_documents 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_not_wired, store）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _not_wired() if store is None else guard_result(lambda: list_documents(store, status=status, kind=kind))

@tool(
    "doc.build_document",
    (
            "写一行 documents 并渲染 markdown 到工作区内（逐条机械检查 + 核对每条 citation "
            "指向的对象真的存在，两道闸都过才落库；out_path 越界即拒绝）"
            ),
    {
           "type": "object",
           "properties": {
            "kind": {"type": "string", "enum": list(S.DOC_KINDS)},
            "title": {"type": "string"},
            "claims": {
                "type": "array",
                "minItems": 1,
                "description": ("每条断言是一个对象。字段各有其位（2026-10-03，`draft/37` §86）："
                                "`evidence_kind='cross_check'` 的免责声明必须写在独立的 `disclaimer` 栏，"
                                "写进 `text` 里不算 —— T1 实测在这里连拒 7 次"),
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "断言原文（读者看到的那句话）"},
                        # 刻意不写 `minItems`：那会让通用参数校验先报
                        # 「claims.[0].citations 至少 1 项」—— 它丢掉了"是哪一条断言"，
                        # 而 G 自己的闸门（`claimanatomy.scan_claim`）会报出带 claim_id 的那句。
                        # 要求写在描述里（模型看得见），强制留在能给出可读回执的那一层。
                        "citations": {"type": "array", "items": {"type": "string"},
                                      "description": ("必须非空（FC-02）：`lit:<id>` / `stmt:<id>` / "
                                                      "`doc:<id>#<claim>` 这类可回查的引用。"
                                                      "没有引用的断言不许进稿件")},
                        "evidence_kind": {"type": "string", "enum": list(S.EVIDENCE_KINDS),
                                          "description": ("证据等级：proof / cross_check / heuristic。"
                                                          "注意没有 'own_result' 这个取值 —— "
                                                          "那是 `origin`（来源）的词表，不是这一栏的")},
                        "disclaimer": {"type": "string",
                                       "description": ("`evidence_kind='cross_check'` **必需**：逐字写"
                                                       "「数值交叉验证，不构成证明」。"
                                                       "它是这条断言的独立一栏，不写在 `text` 里")},
                        "section": {"type": "string", "description": "这条断言落在稿件的哪一节"},
                        "claim_id": {"type": "string", "description": "不给时按 text+citations 自动生成"},
                    },
                },
            },
            "sections": {"type": "array", "items": {"type": "object"}},
            "open_problems": {"type": "array", "items": {"type": "string"}},
            "out_path": {"type": "string", "description":
                         "生成 markdown 的落点（工作区内相对路径；缺省 "
                         "`<工作区>/<documents>/<doc_id>.md`）。它是这份稿件的渲染产物，"
                         "不是论文本体：指到 `out/paper/main.tex` 会把论文正文换成台账稿"
                         "（真机实测：26 KB → 4 KB，不可逆）⇒ 既有的、不属于任何 "
                         "`documents` 行的文件一律拒绝覆盖；要改主稿请用 `fs.edit`"},
           },
           "required": ["kind", "title", "claims"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITER_ROLES,
    # 键名从一个真实调用读出（`build_document`）：落库后的 documents 行
    # （`S.Document` 全字段，12 个）。
    returns=(
            "{'doc_id','kind','title','markdown_path','claims','sections','open_problems',"
            "'status','review_rounds','created_at','updated_at','created_by'}（落库后的 documents 行）；"
            "失败：ok=False + kind(dangling_citation/validation_error/store_error/io_error) + "
            "missing[]（逐条坏引用：claim_id/citation/kind/ref/why）+ created=False"
            ),
    tags=("document", "write"),
)
def _doc_build_document(_not_wired, store, workspace, actor, kind=None, title=None, claims=None, sections=None, open_problems=None, out_path=None):
    """doc.build_document 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_not_wired, store, workspace, actor）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _not_wired()
               if store is None
               else guard_result(
                   lambda: build_document(
                       store,
                       kind,
                       title,
                       claims=claims,
                       sections=sections,
                       open_problems=open_problems,
                       out_path=out_path,
                       workspace_root=workspace,
                       actor=actor,
                   )
               )
    )

@tool(
    "doc.register_dependency",
    (
            "登记外部依赖（FC-23）：status='closed' 会先用真实数据核 lit_id/experiment_id 是否已入库；"
            "dangling / external_unavailable 必须写 status_reason"
            ),
    {
           "type": "object",
           "properties": {
            "used_by": {"type": "string"},
            "kind": {"type": "string", "enum": list(S.DEP_KINDS)},
            "label": {"type": "string"},
            "source_lit_id": {"type": "string"},
            "source_experiment_id": {"type": "string"},
            "page_range": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
                "maxItems": 2,
            },
            "quote": {"type": "string"},
            "status": {"type": "string", "enum": list(S.DEP_STATUSES)},
            "status_reason": {"type": "string"},
           },
           "required": ["used_by", "kind", "label"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITER_ROLES,
    # 键名从一个真实调用读出（`register_dependency`）：落库后的 dependencies 行
    # （`S.Dependency` 全字段，12 个）。
    returns="{'dep_id','used_by','kind','label','source_lit_id','source_experiment_id','page_range','quote','status','status_reason','created_at','created_by'}（落库后的 dependencies 行）",
    tags=("document", "dependency", "write"),
)
def _doc_register_dependency(_not_wired, store, actor, **kw):
    """doc.register_dependency 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_not_wired, store, actor）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _not_wired()
               if store is None
               else guard_result(lambda: register_dependency(store, actor=actor, **kw))
    )

#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
#: 声明随函数走（`@tool` 写进 `fn.__tool_spec__`），这里只列装配要做的事。
_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_doc_scan_claim, ()),
    (_doc_compose_claim, ()),
    (_doc_list_documents, ('_not_wired', 'store')),
    (_doc_build_document, ('_not_wired', 'store', 'workspace', 'actor')),
    (_doc_register_dependency, ('_not_wired', 'store', 'actor')),
)


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    root: Any = None,
    workspace_root: Any = None,
    actor: str = "agent-G",
    **_: Any,
) -> None:
    """装配 G 的稿件工具。

    依赖注入按名取（见 `tools.__init__._call_register`）。`store` 缺失时
    工具照样注册，但一调用就返回 `ok=False, kind="not_wired"` ——
    这比"悄悄不注册"或"静默返回空列表"都好：前者让装配期看不见，后者
    会让调用方把"没接线"读成"库里没有稿件"（FC-08）。
    """
    ws = workspace_root if workspace_root is not None else root
    if ws is None and store is not None:
        ws = store.root
    workspace = Path(ws).resolve() if ws is not None else None

    def _not_wired() -> Any:
        return fail(
            "doc 工具未接线（装配时未提供 store）⇒ **没查**，不是『库里没有稿件』",
            kind="not_wired",
        )

    _bound: dict[str, Any] = {}
    _bound['_not_wired'] = _not_wired
    _bound['store'] = store
    _bound['workspace'] = workspace
    _bound['actor'] = actor
    for _fn, _deps in _TOOL_FUNCTIONS:
        registry.register(replace(_fn.__tool_spec__,
                                  handler=partial(_fn, *[_bound[k] for k in _deps])))





    _register_paper_tools(registry, workspace=workspace)


# ---------------------------------------------------------------- 论文包（打包 / 编译 / 查锚）


def _resolve_project_root(workspace: Path | None, project: str) -> tuple[Path | None, str]:
    """把 `project` 解析成工作区内一个真实目录。返回 `(路径, 问题)`。

    与 `resolve_out_path` 同一个纪律：越界（绝对路径、`..`、跳到工作区外）一律拒。
    这一层要起子进程并把它的工作目录设成这个路径 —— 放宽等于把"跑什么、在哪跑"
    交给调用方，而工具层把那个能力定义成 `exec`（需要审批）。
    """
    raw = str(project or "").strip()
    if not raw:
        return None, "project 不能为空（它是论文包所在的项目根，例如 projects/p2-review）"
    cand = Path(raw)
    if cand.is_absolute():
        return None, f"project 必须是工作区内的相对路径（收到绝对路径 {raw}）"
    if workspace is None:
        return None, "没接线：装配时既没给 workspace_root 也没给 store ⇒ 不知道该相对谁解析 project"
    root = workspace.resolve()
    target = (root / cand).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None, f"project 跑出工作区了：{raw}"
    if not target.is_dir():
        return None, f"项目目录不在盘上：{target}"
    return target, ""


def _paper_root(workspace: Path | None, project: str) -> Any:
    """解析项目根；失败时返回一个已经 `fail` 的结果（调用方直接返回它）。"""
    target, problem = _resolve_project_root(workspace, project)
    if target is None:
        return fail(f"论文包：{problem}", kind="bad_project", project=project)
    return target


def _paper_state(workspace: Path | None, project: str) -> Any:
    """`doc.paper_state`：进程内核一份论文包（不起子进程、不出网）。

    为什么要它（`draft/28` §191）：H 是只读角色，结构性拿不到 `exec` 工具，
    而"这份包与库一致吗"本该由审校者自己回答。判据在 `agentflow.renderanchor` 里，
    这里只把它读出来 —— 所以这条是 `read` 工具，H 拿得到。
    """
    root = _paper_root(workspace, project)
    if not isinstance(root, Path):
        return root
    got = PB.state(root)
    return ok({
        "verdict": got["verdict"], "dimensions": got["dimensions"], "drift": got["drift"],
        "problems": got["problems"], "why": got["why"], "anchor_path": got["anchor_path"],
        "anchor_present": got["anchor_present"], "receipt_path": got["receipt_path"],
        "receipt_present": got["receipt_present"], "rendered_at": got["rendered_at"],
        "compiled_at": got["compiled_at"], "checked": got["checked"],
        # 构建历史（`draft/28` §193）：它是读数不是判据 —— 回答"渲染/编译过几次、
        # 最近一次是什么时候"，不参与三维判定。
        "history": got.get("history") or {},
    })


#: 论文包四件工具的实现。它们刻意写在模块级而不是嵌在 `_register_paper_tools` 里：
#: `tests/test_tools_branch_key_sets.py` 的扫描器对每个函数做 `ast.walk`（含嵌套定义），
#: 四个嵌套 handler 会被算成外层函数的四处分支 ⇒ 判据报「同一个 handler 两种键集合」
#: （12/12/12/14 键 —— 查锚那件本来就不是同一个形状）。提出来之后每个 handler 各有一处
#: 成功支，静态判据读得清，且四条工具的键表各自可见。
def _paper_render(workspace: Path | None, project: str, script: str, timeout_sec: float) -> Any:
    root = _paper_root(workspace, project)
    if not isinstance(root, Path):
        return root
    got = PB.render(root, script=script or PB.DEFAULT_RENDER_SCRIPT, timeout_sec=timeout_sec)
    if not got["ok"]:
        return fail(f"渲染没走成：{got['problem'] or got['stderr_tail'][-200:]}",
                    kind="paper_render_failed", **got)
    # 成功支写成字面量键表（见模块里这条纪律的说明）：让"返回了哪些键"静态可见。
    return ok({
        "script": got["script"], "script_path": got["script_path"], "argv": got["argv"],
        "exit_code": got["exit_code"], "timed_out": got["timed_out"], "ok": got["ok"],
        "result": got["result"], "elapsed_sec": got["elapsed_sec"],
        "stdout_tail": got["stdout_tail"], "stderr_tail": got["stderr_tail"],
        "repro_found": got["repro_found"], "problem": got["problem"],
    })

def _paper_compile(workspace: Path | None, project: str, script: str, timeout_sec: float) -> Any:
    root = _paper_root(workspace, project)
    if not isinstance(root, Path):
        return root
    got = PB.compile_pdf(root, script=script or PB.DEFAULT_COMPILE_SCRIPT,
                         timeout_sec=timeout_sec)
    if not got["ok"]:
        return fail(f"编译没走成：{got['problem'] or got['stderr_tail'][-200:]}",
                    kind="paper_compile_failed", **got)
    return ok({
        "script": got["script"], "script_path": got["script_path"], "argv": got["argv"],
        "exit_code": got["exit_code"], "timed_out": got["timed_out"], "ok": got["ok"],
        "result": got["result"], "elapsed_sec": got["elapsed_sec"],
        "stdout_tail": got["stdout_tail"], "stderr_tail": got["stderr_tail"],
        "repro_found": got["repro_found"], "problem": got["problem"],
    })

def _paper_anchor(workspace: Path | None, project: str, script: str, timeout_sec: float) -> Any:
    root = _paper_root(workspace, project)
    if not isinstance(root, Path):
        return root
    got = PB.anchor_check_script(root, script=script or PB.DEFAULT_RENDER_SCRIPT,
                          timeout_sec=timeout_sec)
    # 三态：drifted 是"查过了、有漂移"（fail），unknown 是"没查成"（fail 但 kind 不同）。
    # 两者都 fail：工具层的 ok 只表示"这一步做成了"，而"包与库一致"由 verdict 说。
    if got["verdict"] == "consistent":
        return ok({
            "verdict": got["verdict"], "expected_exit_code": got["expected_exit_code"],
            "exit_code": got["exit_code"], "drift": got["drift"], "why": got["why"],
            "script": got["script"], "anchor_path": got["anchor_path"],
            "anchor_present": got["anchor_present"], "anchor_sha256": got["anchor_sha256"],
            "stdout_tail": got["stdout_tail"], "stderr_tail": got["stderr_tail"],
            "elapsed_sec": got["elapsed_sec"], "repro_found": got["repro_found"],
            "problem": got["problem"],
        })
    kind = "paper_anchor_unknown" if got["verdict"] == "unknown" else "paper_anchor_drifted"
    return fail(f"渲染锚没到 0 漂移：{got['why']}", kind=kind, **got)

def _paper_build(workspace: Path | None, project: str, render_script: str, compile_script: str, timeout_sec: float) -> Any:
    root = _paper_root(workspace, project)
    if not isinstance(root, Path):
        return root
    got = PB.build(root, render_script=render_script or PB.DEFAULT_RENDER_SCRIPT,
                   compile_script=compile_script or PB.DEFAULT_COMPILE_SCRIPT,
                   timeout_sec=timeout_sec)
    if not got["ok"]:
        return fail(f"从源重编没走成：{got['problem']}", kind="paper_build_failed", **got)
    return ok({
        "ok": got["ok"], "anchor": got["anchor"], "pdf_path": got["pdf_path"],
        "pdf_sha256": got["pdf_sha256"], "pdf_bytes": got["pdf_bytes"],
        "pdf_pages": got["pdf_pages"], "markers_missing": got["markers_missing"],
        "compiler_exit_codes": got["compiler_exit_codes"], "receipt": got["receipt"],
        "steps": got["steps"], "problem": got["problem"],
    })


def _register_paper_tools(registry: ToolRegistry, *, workspace: Path | None) -> None:
    """把"打包 / 编译 / 查渲染锚 / 一次重编"注册成 G 的工具。

    四条工具共用 `agentflow.paperbuild` 里那一份实现：判据在项目脚本里，
    这一层只负责受限地起子进程、读回 `REPRO_RESULT` 契约、把三态翻成 ok/fail。

    `declared_external="exec"` 是刻意的：它们执行的是项目里的脚本（调用方选路径）。
    声明成 `none` 等于说"这几个工具不执行任何东西"—— 而那正好是审批面最需要看的一栏。
    """
    registry.register(
        ToolSpec(
            name="doc.paper_render",
            summary="跑项目里的渲染脚本（默认 code/make_paper.py）：从库里的行重新产出主稿、"
            "四张表与六件配套，并写渲染锚。原始退出码与脚本的 REPRO_RESULT 结论一字不改带回。",
            params={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "minLength": 1, "maxLength": 300},
                    "script": {"type": "string", "maxLength": 300},
                    "timeout_sec": {"type": "number", "minimum": 1, "maximum": 7200},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
            handler=lambda project, script="", timeout_sec=900.0: _paper_render(
                workspace, project, script, timeout_sec),
            side_effect="write_local",
            declared_external="exec",
            roles=("G",),
            returns=(
                "{'script','script_path','argv','exit_code','timed_out','ok','result','elapsed_sec',"
                "'stdout_tail','stderr_tail','repro_found','problem'}；"
                "`result` 是脚本自己那行 `REPRO_RESULT: {json}`（渲染脚本给 claims/experiments/"
                "dependencies/conjectures/literature/findings/signature_verdict/coverage/"
                "render_anchor/anchor_tables 等读数）；"
                "失败：ok=False + kind=paper_render_failed + problem（超时/脚本不存在/越界/没有结论行）"
            ),
            tags=("document", "paper", "exec"),
        )
    )

    registry.register(
        ToolSpec(
            name="doc.paper_compile",
            summary="跑项目里的编译脚本（默认 code/compile_paper.py）：从 main.tex 重编 main.pdf。"
            "本机 MiKTeX 会写完 PDF 却以 0xC0000409 退出 ⇒ 判据是 PDF 的内容，退出码如实带回。",
            params={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "minLength": 1, "maxLength": 300},
                    "script": {"type": "string", "maxLength": 300},
                    "timeout_sec": {"type": "number", "minimum": 1, "maximum": 7200},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
            handler=lambda project, script="", timeout_sec=1800.0: _paper_compile(
                workspace, project, script, timeout_sec),
            side_effect="write_local",
            declared_external="exec",
            roles=("G",),
            returns=(
                "{'script','script_path','argv','exit_code','timed_out','ok','result','elapsed_sec',"
                "'stdout_tail','stderr_tail','repro_found','problem'}；"
                "`result` 含 {'ok','pdf','pdf_bytes','pdf_header','pages','text_extractor',"
                "'markers_missing','runs','compiler_exit_codes','log_tail','note'}；"
                "失败：ok=False + kind=paper_compile_failed"
            ),
            tags=("document", "paper", "exec"),
        )
    )

    registry.register(
        ToolSpec(
            name="doc.paper_anchor",
            summary="查渲染锚（默认 code/make_paper.py --check）：三态 —— 0 一致 / 1 有漂移 / "
            "2 没查成（锚不在盘上）。漂移逐条列出（哪张表、哪个文件）。",
            params={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "minLength": 1, "maxLength": 300},
                    "script": {"type": "string", "maxLength": 300},
                    "timeout_sec": {"type": "number", "minimum": 1, "maximum": 7200},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
            handler=lambda project, script="", timeout_sec=600.0: _paper_anchor(
                workspace, project, script, timeout_sec),
            side_effect="read",
            declared_external="exec",
            roles=("G",),
            returns=(
                "{'verdict','expected_exit_code','exit_code','drift','why','script','anchor_path',"
                "'anchor_present','anchor_sha256','stdout_tail','stderr_tail','elapsed_sec',"
                "'repro_found','problem'}；verdict ∈ consistent/drifted/unknown；"
                "退出码与它打印的漂移行互相矛盾时判 unknown（两个信号打架不许挑一个信）。"
                "失败：ok=False + kind=paper_anchor_drifted（查过了、有漂移）/ "
                "paper_anchor_unknown（没查成）"
            ),
            tags=("document", "paper", "anchor"),
        )
    )

    registry.register(
        ToolSpec(
            name="doc.paper_build",
            summary="从源重编一次论文包并核对渲染锚：渲染 → 编译 → 再渲染（把锚挪到新 PDF 上）"
            "→ 查锚，返回每一步的读数与最终漂移数。顺序是判据的一部分（见 draft/28 §188）。",
            params={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "minLength": 1, "maxLength": 300},
                    "render_script": {"type": "string", "maxLength": 300},
                    "compile_script": {"type": "string", "maxLength": 300},
                    "timeout_sec": {"type": "number", "minimum": 1, "maximum": 7200},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
            handler=lambda project, render_script="", compile_script="", timeout_sec=1800.0: _paper_build(
                workspace, project, render_script, compile_script, timeout_sec),
            side_effect="write_local",
            declared_external="exec",
            roles=("G",),
            returns=(
                "{'ok','anchor','pdf_path','pdf_sha256','pdf_bytes','pdf_pages','markers_missing',"
                "'compiler_exit_codes','receipt','steps','problem'}；"
                "`anchor` 含 {'verdict','dimensions','drift','problems','why','anchor_path',"
                "'anchor_present','receipt_path','receipt_present','anchor_sha256','rendered_at',"
                "'compiled_at'}；`receipt` 是编译回执（tex_sha256/pdf_sha256/pages/"
                "compiler_exit_codes）；`steps[]` 每项是 {'step','script','exit_code','ok',…}，"
                "step ∈ render/compile/anchor_check —— **三步**：锚只管渲染出的源文件，"
                "PDF 由编译回执管，所以不再需要再渲染一次；"
                "ok=True 只在锚 verdict=consistent（0 漂移）时为真；"
                "失败：ok=False + kind=paper_build_failed + problem（指出是哪一步没走成）"
            ),
            tags=("document", "paper", "build"),
        )
    )

    registry.register(
        ToolSpec(
            name="doc.paper_state",
            summary="只读核对一份论文包：进程内算渲染锚三维（源表 / 渲染出的源文件 / 编译回执），"
            "给三态结论与逐条漂移。不起子进程、不出网 —— 只读角色也能自己核。",
            params={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "minLength": 1, "maxLength": 300},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
            handler=lambda project: _paper_state(workspace, project),
            side_effect="read",
            roles=("G", "H"),
            returns=(
                "{'verdict','dimensions','drift','problems','why','anchor_path','anchor_present',"
                "'receipt_path','receipt_present','rendered_at','compiled_at','checked','history'}；"
                "verdict ∈ consistent/drifted/unknown（unknown = 有一维判不了，不是一致）；"
                "dimensions 含 {'tables','files','receipt'} 三维各自的结论；"
                "history 含 {'present','total','renders','compiles','last_render_at',"
                "'last_compile_at','problems'}（它是读数，不参与判定）"
            ),
            tags=("document", "paper", "read"),
        )
    )
