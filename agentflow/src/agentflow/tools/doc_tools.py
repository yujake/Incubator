"""G 的工具：论文撰写。
## 这一层唯一的核心规矩
没有引用的断言不允许进入稿件。
这不是文风要求，而是本领域可信度的技术基础：数学断言的价值完全取决于"它来自哪里"。一旦允许无引用的断言，稿件就退化成一个听起来很合理的文本 —— 而"听起来合理"与"有证
据"之间的差距，正是幻觉最容易藏身的地方。
因此本模块把三条约束做成了可机械判定的检查（`scan_claim`），并由 `schema.Document.validate` 在写入时强制执行：
1. `citations` 非空（FC-02）； 2. `evidence_kind="cross_check"` 的断言必须自带 `disclaimer`（"数值交叉验
证，不构成证明"）—— 这句话由结构强制，不靠人记得写（FC-22）； 3. 否定型断言必须给 `negation_kind`（FC-25，"未证明"≠"已证否"）。
## 本模块的入口
| 函数 | 作用 | 关键纪律 ||---|---|---|| `scan_claim` | 一条断言的机械检查（纯函数） | 唯一判据；G 与 H 共用同一份 || 
`compose_claim` | 构造一条合规断言 | `cross_check` 自动补 disclaimer；否定型未分类、无引用、过度声称 ⇒ 构造时抛 || 
`build_document` | 落库 + 渲染 markdown | 先逐条 `scan_claim`、再核 citations 指向的对象真的存在（两张闸都过才写库）
|| `register_dependency` | 登记外部依赖（FC-23 第一道闸） | `closed` 必须用真实数据核到已入库来源 || 
`render_markdown` | 人可读渲染（FC-10 / FC-22 / FC-23 / FC-25 的呈现层） | 三分档计数、否定分类、依赖表都必须出现
|| `list_documents` | 只读列举 | 供 H / F / D 消费 |
|| `write_mapping` | 论文对应表的三份写口（json / md / 正文附录） | 内部只调 `papermapping.write_package`：不自己渲染任何一段，手抄就与渲染器逐字对不上 |
## 为什么"在构造时就抛"比"写库时才抛"重要
`schema.Document.validate` 已经拦得住无引用断言，但它的报错形如"claims[3] 没有 citations" —— 读者得自己回去数"第 3 
条到底是哪句话"，而构造现场（手里正拿着那句话、那段引用）才是信息最全的地方。写库时的 schema 是最后一道闸，不是唯一一道。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from .. import claimanatomy as CA
from .. import numericproof as NP
from .. import papercompile as PC
from .. import papermapping as PM
from .. import proofloc as _PL
from .. import schema as S
from .. import textutil as T
from .. import verifications as VR
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

#: `proof_review` 类断言必须自带的声明（业主 2026-10-12：「写论文那一档原先卡每个定理都要到
#: proof 水平，但没 Lean 显然做不到，但也要能写」）。它与上面那句同一族：读者必须在正文
#: 旁边就看到"这一档凭什么"。两档的差别只在这句话里，所以这句话不许被合并成一句。
PROOF_REVIEW_DISCLAIMER = "逐行审阅过的证明，未经机器检查"

#: 证据等级 → 那一档必须自带的声明（没有的档给空串）。一处定义，写入口与读入口共用。
DISCLAIMER_BY_EVIDENCE_KIND = {
    "cross_check": CROSS_CHECK_DISCLAIMER,
    "proof_review": PROOF_REVIEW_DISCLAIMER,
}


def _disclaimer_for(evidence_kind: str) -> str:
    """这一档要自动补的那句声明（没有这一档的要求就给空串）。"""
    return DISCLAIMER_BY_EVIDENCE_KIND.get(str(evidence_kind), "")


def wording_ceiling() -> tuple[str, ...]:
    """允许「定理 / 证明 / 必然」这类措辞的证据等级（唯一口径，两处消费者共用）。
    
    业主 2026-10-12 的口径（逐字）：「比如写论文那一档原先卡每个定理都要到 proof 水平，但没 Lean 显然做不到，但也要能写」。
    
    两档：
    
    - `proof` 永远在：检查器核过的证明，任何模式下都是最高一档；- `proof_review` 只在 Lean 开关关掉时在：那一档说的是"一份逐行审阅过的证明（`statements.proof_text`
    + V 签「成立」）"，是关掉 Lean 之后能达到的最高证据。开关开着时它不在这一档里 —— 老套路不变：只有检查器说过的才算证明，「逐行审阅过」仍然低于 `proof`，
    用了那些措辞照样判 `overclaim`。
    
    开关读不出来（设置文件写坏）时按开着处理（保守方向）：那一边会误报，而误报是可修的；反方向的漏报会让"数值/审阅"悄悄冒充"证明"。
    """
    kinds = ["proof"]
    try:
        from .. import settings as SET

        if not SET.lean_enabled()[0]:
            kinds.append("proof_review")
    except Exception:  # noqa: BLE001 —— 读不到开关就按开着（保守），见 docstring
        pass
    return tuple(kinds)


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
    "proof_review": "逐行审阅（proof_review）",
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
    
    越界一律拒绝（而不是"写到外面再警告"）：工作区边界是沙箱契约的一部分，允许一次越界写就等于承认这个边界可以被绕开。用 `resolve()` 之后再
    `relative_to()` 判断，而不是靠字符串 `..` 检查 —— 后者会被符号链接绕过。
    
    ## 为什么它是公开的（`draft/37` §118）
    
    `D.write_report` 原先自己写 `Path(out_path)` —— 相对路径于是按「进程当前目录」解析。T2 第 1 趟真机：主控传 
    `out_path="out\\review\\D-analysis.md"`（工作区内的合法落点），文件却写到了 
    `agentflow/out/review/D-analysis.md`（工作区根相对）（进程 cwd），「整个交付物静默离开工作区」，而那一趟记的是 
    `outcome=ok`。同一条规则不能有两份实现（那正是"两份判据必然漂移"），所以它在这里公开，由角色方法直接复用。
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
    `findings` 里的 `kind` 与 :data:`agentflow.schema.FINDING_KINDS` 同词表 ——这样 H 的审校发现与 G 的自检发现是同一批类
    型，可以互相印证，而不会出现"G 自查用一套名字、H 审查用另一套"的分裂。
    ## 判据只有一份（本函数现在只是适配层）
    字段级与交叉轴的判据全部在 :mod:`agentflow.claimanatomy`（`CLAIM_FIELDS`是一张可被文档生成与 CLI 读取的声明表）。本函数只做两件事：① 
    把 `ClaimIssue.code` 翻成 `FINDING_KINDS` 的受控词（下游只认后者）；② 把结论压成 
    `ok / error_count / warning_count` 的旧形状。它不再自己写任何一条检查 —— 这里曾经有过第二份实现，而"两份判据必然漂移，漂移的后果是 G 认为合规、
    H 认为通过，且没有任何报错"（FC-03 / INVENTORY 4.5#10）。
    三态纪律：`unknown_status_axis`（判定"判不了"）不计入 `error_count`，但会原样出现在 `findings` 里，并由 `decided` 位单独传出
    ——"字段缺失"与"字段非法"与"检查器没跑成"必须能分开。
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


#: `ClaimIssue.code` → `schema.FINDING_KINDS` 的受控词（唯一的映射处，FC-03）。
#: 为什么需要这一层：`claimanatomy` 的 code 是判据层的词（`missing_field` / `bad_enum` /
#: `inconsistent_status` …），而 `review_findings.kind` 是落库层的词（`schema.FINDING_KINDS`，
#: 而 `schema.py` 在禁 AI 区、不能加成员）；两者必须能对上，否则 H 的发现落库时会被 schema 拒。
#: 映射：`missing_field` / `empty_required` / `incomplete_numeric_evidence` / `missing_disclaimer` /
#: `uncontrolled_disclaimer` → `unsupported_claim`（缺的字段是断言成立的前提 / 数值证据四元组不齐 /
#: 受控声明没写或写错）；`bad_enum` / `bad_type` / `checker_error` → `garbled`（取值非法 / 检查器没跑成）；
#: `inconsistent_status` / `overclaim` → `overclaim`；`unknown_status_axis` / `undeclared_field` →
#: `scope_drift`（前者不与 `garbled` 撞 kind、也不与"否定未分类"撞级别）；`duplicate_claim_id` /
#: `lifecycle_incomplete` → `inconsistent_number`。
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
    # 「2026-10-15 补登记」：`uncontrolled_disclaimer` 是 `claimanatomy` 在 2026-10-13（无 Lean T2 的真机）
    # 新加的 code，它登记进了 `CLAIM_FAMILY_BY_CODE`（族 5）与 `test_lean_switch`，却漏了这里 ⇒ 落据那一步
    # 抛 `KeyError`，于是 `build_document` 整条失败（G 渲染不出稿件），而盘上看起来只是"G 拒绝了这次调用"。
    # 为什么是 `unsupported_claim` 而不是 `garbled`：它判的是"这条断言声称的那一档凭什么没被那受控的一句
    # 承诺住" —— 与 `missing_disclaimer` 同族同义（族 5），区别只在"没写"与"写错了"，两者该改的栏是同一个；
    # 落 `garbled`（"表述无法解析"）会把"声明不对"读成"读不懂"，下游按 kind 分档 ⇒ 分错档。
    # 教训：这张表"未登记就当场炸"，而这次炸在 G 的渲染上、不在判据自己身上；现在的防线是
    # `tests/test_claimanatomy.py` 里那条按 `CLAIM_FAMILY_BY_CODE` 逐 code 对账的判据。
    "uncontrolled_disclaimer": "unsupported_claim",
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
# 这一节是 `scan_claim` 的补集：`scan_claim` 只查"有没有引用"（形状），查不出"引用的东西在不在"
# （存在性）。两者缺一不可：`register_dependency` 早就对 `status='closed'` 用真实数据核过来源（见本文件
# `:753-768` 的长注释），而 `build_document` 此前没有这道闸 —— `citations=["lit:9999"]` 能通过全部检查、
# 写库、渲染，直到 `verify` 事后才报 `dangling_citation`，那时坏引用已经进了稿件。
# 引用前缀 → 它必须存在于哪张表。与 `verify.py` 的 `dangling_citation` 同口径（`partition(":")` 取前缀、
# `split("#")` 去页码后缀）：写入期比审计期更严可以，两处对同一个字符串给出不同结论则不行。
# 这张表不再内联：它从唯一声明面 `schema.CITATION_PREFIXES` 派生（2026-10-07 所有者裁定 `draft/68` 题 1
# 选 A）；改前它与 `verify.CITATION_KINDS`、`gates.gate_g2` 内联的四个前缀是三处各写一份，于是 `stmt:`
# 加进一处之后其余两处各自自洽 —— "写入期认、审计期不认"没有任何读数会响。
_CITATION_TABLES: dict[str, str] = dict(S.CITATION_PREFIXES)


def citation_prefix_examples() -> str:
    """引用前缀的用法示例串（`rel:<id>` / `lit:<id>` / …），按声明面的次序生成。
    
    唯一来源是 `_CITATION_TABLES`（= `schema.CITATION_PREFIXES`）：这一串出现在两处面向模型与读者的声明面上 —— 工具 
    `doc.build_document` 的 JSON schema 里`claims[].citations` 那一格的 `description`，以及渲染出来的稿件
    "0. 阅读须知"的第 1 条。两处各写一份的后果实测过（题 19，2026-10-07 所有者裁定 A）：
    
    - 工具面那一格只举了 `lit:` / `stmt:` / `doc:`；- 渲染说明只举了 `rel:` / `lit:` / `exp:`。
    
    一个模型照着其中任一处去写，都看不到另外几个前缀是合法的（`stmt:` 缺席时"引我们自己的命题"这条写法根本不可见），而没有任何读数会响。所以两处都改成从声明面派生：这
    里按 `_CITATION_TABLES` 的次序逐个生成，改口径只有一处可改。
    """
    return " / ".join(f"`{prefix}:<id>`" for prefix in _CITATION_TABLES)

# `doc:` 是唯一不能只靠下面那条通用存在性检查的一档：通用检查只比 `ref`，而
# `citation_ref_parts` 把 `#` 之后切掉了 ⇒ 那样只会核"稿件在不在"，断言与哈希
# 都不看，于是过期哈希会被静默接受（比"错误拒收"更坏）。所以 `doc:` 单独走
# `_doc_citation_problem` 的三段检查：三段判据的唯一实现是
# `signatures.doc_ref_verdict`（题 5/5a —— 写入期与审计期原先各有一份，靠
# "与 `verify.py:923-961` 同口径"那句注释对齐；那句注释连同行号已经作废，
# 现在两侧调的是同一个函数，改口径只有一处可改）。
#
# `stmt` / `doc` 的来历（`R-03` / `draft/49` 裁"方案 A"、主控 2026-10-07 裁 2）：
# 两者都是合法引用档（`stmt:` 引我们自己的命题、`doc:` 引本文档内的另一条断言），
# 而它们此前的形态都是"写入期与审计期各认一半"（`doc:` 曾写入期拒、审计期认）——
# 那正是把这张表并入 `schema.CITATION_PREFIXES` 的理由；逐条历史理由现在是这条
# 派生关系的注释，而不是第二份字面量。

#: 裸号（不带前缀的编号）在这张表里不认。
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
_CITATION_BARE_NUMBER = re.compile(rf"^{S.ID_OR_LEGACY_PATTERN}$")


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
    """`doc:` 内部引用的判定（空串 = 通过）。
    两种形状（业主 2026-10-09 的裁定，见 `signatures.doc_ref_verdict` 的 docstring）：
    - `doc:<稿件>#<断言>@<内容哈希前 16 位>` —— 引某条断言（三段式，`@哈希` 可省）；- `doc:<稿件>` / `doc:<稿件>@<内容哈希前 16 位>` —— 引我
    方那份手稿的整体成果。此前这一档被判"形状不对"⇒"用手稿里的成果"只剩"在正文里从零重搭"一条路。
    唯一实现在 `agentflow.signatures.doc_ref_verdict`（题 5/5a 把写入期与审计期原先各一份的三段逻辑合成了一份：两份各判一次时，漂了没有任何地方会报）。
    本函数只做两件事：把"查稿件"的能力递给那一份实现，再把判定码翻成一句人话。它不再自己解析、不再自己算哈希 —— 那样就等于又长出一份三段逻辑。钉了哈希就要对上：改稿之后旧引用必须失效（只看"稿件
    还在"会让一份改过的稿件继续被旧哈希引着，而那正是 `draft/30` §T4-A 设计这几段要防的事）；而两段式没钉版本是合法的一档（读数里 `pinned=False` 看得见）。
    写入期只判这几段，刻意不判"目标稿件必须 `accepted`"（`draft/68` 题 12 选 A：两侧保持不对称）—— 写稿阶段要能引一份还在审的稿子（否则"边写边审"会被挡住）；那一条是
    审计期独有的内容政策（`draft/29` §8.5 第 1 条）。两侧共用（`signatures.doc_ref_verdict`），调用方档不在那里 —— 见那个函数的 docstring。
    """
    from .. import signatures as SIG  # 惰性：与 `:1390` 同一处依赖，不新增模块级边

    verdict = SIG.doc_ref_verdict(raw, lambda did: next(
        (r for r in rows_of("documents") if str(r.get("doc_id")) == str(did)), None))
    if verdict.code == SIG.DOC_REF_BAD_SHAPE:
        return ("内部引用形状不对：引某条断言应为 "
                f"doc:<稿件>#<断言>@<内容哈希前 {SIG.REF_HASH_LEN} 位>；"
                "引我方那份手稿的整体成果写 doc:<稿件>（想钉版本就写 "
                f"doc:<稿件>@<内容哈希前 {SIG.REF_HASH_LEN} 位>）")
    if verdict.code == SIG.DOC_REF_NO_DOC:
        return f"documents 表里没有 doc_id={verdict.doc_id!r}"
    if verdict.code == SIG.DOC_REF_NO_CLAIM:
        return f"稿件 {verdict.doc_id} 里没有断言 {verdict.claim_id!r}"
    if verdict.code == SIG.DOC_REF_STALE:
        return (f"钉的是 {verdict.pinned_hash}，而稿件 {verdict.doc_id} 当前内容是 "
                f"{verdict.current_hash} ⇒ 改稿之后旧引用失效（不许静默沿用）")
    return ""


#: "正式论文"的那一格（`documents.kind` 的取值）。两阶段口径靠它分档
#: （业主 2026-10-09：「研究手稿阶段可以互相引用，正式论文阶段只能引用真实论文，
#: 正式论文中手稿内容不可直接引用，必须重建」）。词表真身是 `schema.DOC_KINDS`，
#: 这里只写"哪一个是正式论文"——不另抄一份词表（抄了就会漂）。
FORMAL_PAPER_KIND = "paper"


def check_citations(
    rows_of: Any, claims: Sequence[Mapping[str, Any]], *,
    citing_kind: str = "") -> dict:
    """逐条核对 citations 指向的对象真的存在。
    ==============================  ============================================调用方式                          返回
    ==============================  ============================================`rows_of` 是读表函数             `checked=True`，
    `missing` 可能为空（=都查过了）`rows_of is None`（没有 store）  `checked=False`，不得读成"引用都存在
    "==============================  ============================================`rows_of(table) -> 行序列`：给的是读表能力而不是 store 实例，这
    样它既能在事务内用 `tx.rows` 跑（拿到一致的快照），也能被单测直接喂假表。`citing_kind`：两阶段口径（业主 2026-10-09 逐字）- 研究手稿阶段（`note` / `survey` / 
    `reproduction_report` 等）：可以互相引用我方手稿 —— `doc:<稿件>`（引整体成果）与三段式`doc:<稿件>#<断言>@<哈希>` 都合法（后者更精确、能钉版本）；- 正式论文（`kind="paper"`）：只许
    引真实论文（`lit:`）。`doc:` 一律拒，理由写明"手稿里的内容要进论文必须在正文里重建"—— 重建出来的东西再以`stmt:` / `exp:` / `rel:` 落台账、被论文引用（`closing.PAPER_LEDGER_PREFIXES`
    要的正是这三种）。- 没给 `citing_kind`（历史调用点/单测）⇒ 只判形状与存在性（老行为逐字不变）。返回 ``{"checked", "reason", "missing": [{claim_id, citation, kind, ref, why}],"resolved": n, "doc_whole": [...], "doc_unpinned": [...]}``。
    后两格是读数（两阶段口径之后才有意义）：`doc_whole` = 引"我方那份手稿的整体成果"的那些引用（两段式）；`doc_unpinned` = 其中没钉版本的那些 ——没钉版本是合法的，但"改稿之后旧引用不会失效"这件事必须看得见，不许
    与"钉过了"混作一谈。
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
            "doc_whole": [],
            "doc_unpinned": [],
        }

    # 只把用得到的表读出来，且每张表只读一次（引用多时不做 O(n²) 扫描）。
    id_sets: dict[str, set[str]] = {}
    missing: list[dict] = []
    whole_docs: list[str] = []
    unpinned_docs: list[str] = []
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
                # 两阶段口径（业主 2026-10-09）：正式论文里不许直接引我方手稿。
                if str(citing_kind) == FORMAL_PAPER_KIND:
                    missing.append(
                        {
                            "claim_id": cid,
                            "citation": str(raw),
                            "kind": kind,
                            "ref": ref,
                            "why": (
                                "正式论文里不许直接引我方手稿（业主 2026-10-09："
                                "「正式论文阶段只能引用真实论文，正式论文中手稿内容不可"
                                "直接引用，必须重建」）⇒ **手稿里的成果若要用，只可在论文"
                                "正文里重建**：在正文里把那条内容重新立起来（自己的表述 + "
                                "自己的证据链），重建出来的东西再以 `stmt:` / `exp:` / "
                                "`rel:` 引它变成的台账行；要引真实论文写 `lit:`。"
                                "重建前先用 `C.proof_chain` 找这条成果的最短证明依赖链"
                                "（业主 2026-10-09：「这样重建会变轻松」）"
                            ),
                        }
                    )
                    continue
                # 内部引用分两档：三段式引某条断言、两段式引我方那份手稿的整体成果。
                # 通用检查只看得到第一段 ⇒ 单独一支（`_doc_citation_problem`）。
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
                    from .. import signatures as SIG

                    reading = SIG.doc_ref_reading(str(raw))
                    if reading.get("whole"):
                        whole_docs.append(str(raw))
                        if not reading.get("pinned"):
                            unpinned_docs.append(str(raw))
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
        "doc_whole": whole_docs,
        "doc_unpinned": unpinned_docs,
    }


def citation_coverage(
    rows_of: Any,
    claims: Sequence[Mapping[str, Any]],
    *,
    citing_kind: str = "",
    suggest: int = 5,
    library_root: str | Path | None = None,
) -> dict:
    """这份稿子引了哪几张表的凭据、库里还有多少可以引的东西 —— 只报数，不拦。
    ## 为什么要有这一格（T2 第 24 趟 `t2s` 的真机形态）
    那一趟：检索 2 条全 `ok`、17 篇文献全部消化、`relations` 73 条、C 跑了 3 次、 2 条实验 —— 而三份稿件的 9 条断言全引 `exp:0001`：`lit:` 0 条、
    `rel:` 0 条。收工门那一档（`closing` 的 `document_literature_citations`）读得出这个 0，但它只在 M 把那一行写进验收表时才进报告（这一趟 M 没写），而
    G/M 在写稿那一刻看不到任何数字：`build_document` 的返回值里只有落库后的那一行。
    ## 它与 `check_citations` 是两件事，不许合并
    - `check_citations` 判——引用指向的对象存不存在，fail-closed，拦下一笔写入；- 本函数只报数——引了什么、库里有什么、缺哪一类。它不拦任何一笔写入，也不改 `data`（那一行
    还要落库/算内容哈希）：读数走工具结果的 `meta`。
    ## 三态（与全项目同一条纪律）
    库读不到 ⇒ `readable=False` 且 `available` 全是 `-1`（"没查成"），不许读成"库里没有可引的东西"；`gaps` 那几句只在 `readable=True` 时才可能非空。
    返回 ``{"own", "counts", "available", "readable", "gaps", "suggest_lit","suggest_rel", "note"}``。
    """
    own: dict[str, list[str]] = {k: [] for k in ("lit", "rel", "exp", "stmt", "doc")}
    for i, c in enumerate(claims, 1):
        for raw in (c or {}).get("citations") or []:
            kind, _ref = citation_ref_parts(raw)
            if kind in own and str(raw) not in own[kind]:
                own[kind].append(str(raw))
    counts = {k: len(v) for k, v in own.items()}

    def _count(table: str, key: str = "") -> int:
        try:
            rows = list(rows_of(table))
        except Exception:  # noqa: BLE001 —— 读不到就是 -1（三态，不编 0）
            return -1
        if key:
            rows = [r for r in rows if r.get(key) is True]
        return len(rows)

    try:
        lit_rows = [dict(r) for r in rows_of("literature")]
        rel_rows = [dict(r) for r in rows_of("relations")]
    except Exception:  # noqa: BLE001
        return {
            "own": own, "counts": counts,
            "available": {"literature_total": -1, "literature_processed": -1,
                          "relations": -1, "experiments": -1, "statements": -1},
            "readable": False,
            "gaps": [],
            "suggest_lit": [], "suggest_rel": [],
            "note": ("库读不到 ⇒ 这份稿子**引了几条**给得出，"
                     "**库里有多少可以引**给不出（'没查成' ≠ '库里没有'）"),
        }

    digested = [r for r in lit_rows if r.get("processed") is True]
    # 「有多少篇真的有全文」——与「登记了几篇」是两件事（T4 第 7 趟 `t4g` 的真机读数：
    # 库里 15 篇，5 条 `download.status=skipped`（后端只给了元数据、没有可下的 URL）、
    # 4 条 `content_mismatch`（落成了 HTML 壳）、2 条 `ok`、4 条 `failed`（404/403/429）
    # ⇒ 真能逐字回验的只有 2 篇，而交付物因此退化成了"证据不足的报告"）。
    #
    # 判据：`download.status == "ok"` 且 `path` 在盘上真的存在（两件都要：
    # 状态说 ok 而文件没了，那是另一种"没查成"）。读不到盘就不编（-1）。
    # 判据：`download.status == "ok"` 且 `path` 在盘上真的存在（两件都要：
    # 状态说 ok 而文件没了，那是另一种"没查成"）。没给 `library_root` 时只按状态算，
    # 并在 `note` 里说清"没看盘"（三态：不把"没看"折成"有"）。
    def _has_fulltext(r: dict) -> bool:
        dl = r.get("download") if isinstance(r.get("download"), dict) else {}
        if str(dl.get("status") or "") != "ok":
            return False
        rel = str(r.get("path") or "")
        if not rel:
            return False
        if library_root is None:
            return True
        return (Path(library_root) / rel).exists()

    n_fulltext = sum(1 for r in lit_rows if _has_fulltext(r))

    try:
        n_questions = len(list(rows_of("research_questions")))
    except Exception:  # noqa: BLE001 —— 读不到就说读不到（-1，不编 0）
        n_questions = -1
    with_cites = sum(1 for c in claims if isinstance(c, Mapping) and (c.get("citations") or []))
    available = {
        "literature_total": len(lit_rows),
        "literature_processed": len(digested),
        # 真有全文的篇数（`download.status == "ok"` 且盘上文件在）——
        # 与"登记了几篇"是两件事：T4 第 7 趟 `t4g` 里 15 篇只 2 篇有全文，
        # 交付物因此退化成了"证据不足的报告"。
        "literature_with_fulltext": n_fulltext,
        "relations": len(rel_rows),
        "experiments": _count("experiments"),
        "statements": _count("statements"),
        "research_questions": n_questions,
    }
    # 「立了几条研究问题」与「这份稿件有几条带引文的断言」的对照（T4 第 4/5 趟的整改）。
    #
    # 两趟连着的 blocker 都是这一个形状：`t4d` 是 `retrieval_ok_rows` 5 < 6（研究问题 6 条）、
    # `t4e` 是 `document_claim_rows` 12 < 16（研究问题 16 条）—— 两档的隐式门槛都是
    # "研究问题条数"，而 M 在写稿那一刻多半没有回头数自己立了几条问题。
    # 这一格只把两个数摆在一起（读数，不拦），并说清默认门槛与两条出路
    # （把断言写够，或在验收表那一行显式声明更低的 `min` 并写明理由）。
    questions_vs_claims = {
        "research_questions": n_questions,
        "claims_with_citations": with_cites,
        # 差几条：不取负（"写得比立的多"不是缺口）；读不到研究问题表时是 -1
        # （与全项目同一条三态：-1 是"没查成"，不是"差 0 条"）。
        "short": (max(0, n_questions - with_cites) if n_questions >= 0 else -1),
    }
    suggest_lit = [
        {"lit_id": str(r.get("lit_id") or ""), "title": str(r.get("title") or "")[:110]}
        for r in sorted(digested, key=lambda r: str(r.get("lit_id") or ""))[: max(0, suggest)]
    ]
    suggest_rel = [
        {"relation_id": str(r.get("relation_id") or ""),
         "description": str(r.get("description") or "")[:110]}
        for r in sorted(rel_rows, key=lambda r: str(r.get("relation_id") or ""))[: max(0, suggest)]
    ]

    gaps: list[str] = []
    # ---- 引用对不对口（T4 第 3 趟 `t4c` 的整改；判据只有一份实现，见下）
    #
    # 那一趟：`documents/0000` 的 5 条断言里 2 条把数学教育论文当出处
    # （`lit:0000`《Promoting Problem Solving across Geometry…》/`lit:0003`《Creative
    # thinking level of visual-spatial students on geometry…》），收工门的 `citation_fit`
    # 点名了这两条，M 调了 5 次 `closing`、看到 blocker 之后仍按 met=true 收工。
    # 这一格原先只报"引了几条" ⇒ 写稿那一刻说不出"对不对口"。
    # 判据不另写一份：直接调 `closing.claim_evidence_fit`（那边 `citation_fit` 用的同一份）。
    fit_rows: list[dict] = []
    misfit: list[dict] = []
    counters = {"fit": 0, "mismatch": 0, "unjudged": 0}
    try:
        from .. import closing as CL  # 惰性：避免 `tools` ↔ `closing` 的 import 期耦合

        exps = {str(r.get("experiment_id") or ""): dict(r) for r in rows_of("experiments")}
        lits = {str(r.get("lit_id") or ""): r for r in lit_rows}
        for i, c in enumerate(claims, 1):
            if not isinstance(c, Mapping):
                continue
            one = CL.claim_evidence_fit(c, exps=exps, lits=lits)
            counters[one["verdict"]] = counters.get(one["verdict"], 0) + 1
            row = {"claim_id": str(c.get("claim_id") or f"claim-{i}"),
                   "citations": [str(x) for x in (c.get("citations") or [])],
                   "verdict": one["verdict"], "why": one["why"]}
            fit_rows.append(row)
            if one["verdict"] == "mismatch":
                misfit.append(row)
    except Exception as exc:  # noqa: BLE001 —— 这一半算不出不影响上面那些读数
        fit_rows, counters = [], {"fit": -1, "mismatch": -1, "unjudged": -1,
                                  "reason": f"{type(exc).__name__}: {exc}"}
    if counts["lit"] == 0 and len(digested) > 0:
        gaps.append(
            f"这份稿子 0 条 `lit:` 引用，而库里已有 **{len(digested)} 篇已消化的文献**"
            f"（例：{('、'.join(x['lit_id'] + '《' + x['title'] + '》' for x in suggest_lit[:3]))}）"
            " —— 研究型手稿要引它据以立论的那几篇；`lit:` 只指真实论文"
        )
    if counts["rel"] == 0 and len(rel_rows) > 0:
        gaps.append(
            f"这份稿子 0 条 `rel:` 引用，而库里有 **{len(rel_rows)} 条关系**"
            f"（例：{('、'.join(x['relation_id'] for x in suggest_rel[:3]))}）"
            " —— C 的关系读数要能被交付物引到（用户点名过「重点考察 C」）"
        )
    if counts["lit"] == 0 and not digested:
        # 反真空：库里本来就没有可引的文献时不喊（"你没引"与"没东西可引"
        # 是两件事）—— 这件事由 `available.literature_processed == 0` 如实记着。
        pass
    if counts["lit"] > 0 and n_fulltext == 0:
        # T4 第 7 趟 `t4g` 的形态：稿子引了 `lit:`，而库里一篇可用全文都没有
        # （只有元数据行）。这不是"不许引" —— 元数据级出处是允许的；要的是正文里写明
        # 哪些结论只有元数据支撑（`draft/38` §10 五 5 的诚实边界那一档）。
        gaps.append(
            f"这份稿子引了 {counts['lit']} 条 `lit:`，而库里**一篇有可用全文的都没有**"
            f"（登记 {len(lit_rows)} 篇、已消化 {len(digested)} 篇；"
            f"`download.status` 分布见各行）—— 元数据级出处可以引，但每条结论要在正文里"
            "写明它只有元数据支撑（该写「未核到」就写「未核到」，别让元数据看起来像读过全文）"
        )
    if questions_vs_claims["short"] > 0:
        gaps.append(
            f"库里立了 {n_questions} 条研究问题，而这份稿件只有 {with_cites} 条带引文的断言"
            f"（差 {questions_vs_claims['short']} 条）—— 收工门那一档（`document_claim_rows`）的"
            "默认门槛就是「研究问题条数」，而「检索」那一档（`retrieval_ok_rows`）同理。"
            "两条出路：把断言写够，**或**在验收表那两行上显式声明更低的 `min` 并写明理由"
            "（声明是你写的，门槛就按你写的判）"
        )
    if misfit:
        gaps.append(
            f"这份稿子有 {len(misfit)} 条断言的引文与原文对不上"
            f"（逐条见 `misfit`：断言的实词/数字与被引来源没有交集）"
            " —— 把引文换成真的支持这条断言的那一条（或把断言改成与证据相符），"
            "别让『引了一条不相关的』冒充『有出处』"
        )

    return {
        "own": own,
        "counts": counts,
        "available": available,
        "readable": True,
        "gaps": gaps,
        "fit": counters,
        "fit_rows": fit_rows,
        "misfit": misfit,
        "questions_vs_claims": questions_vs_claims,
        "suggest_lit": suggest_lit,
        "suggest_rel": suggest_rel,
        "note": ("只报数、不拦：引用的**存在性**由 `check_citations` 判（fail-closed）；"
                 "这一格是把「引了什么 / 库里有什么」放到写稿那一刻看得见。"
                 "`own` 里的号都是这份稿子真的写了的前缀引用（`doc:` 收在 `doc` 那一格）"),
    }


def _check_citations_needs_kind() -> str:
    """`check_citations` 与 `build_document` 之间那一格的口径说明（只读，给读的人）。"""
    return (
        "`citing_kind` 是**发起引用的那一份文档**的类型（`build_document` 的 `kind`、"
        "`revise` 从被修订的那一行读）。业主 2026-10-09 的两阶段口径靠它落地："
        "研究手稿阶段（`note` / `survey` / `reproduction_report` 等）可以互相引用我方手稿"
        "（`doc:<稿件>`）；**正式论文**（`kind=\"paper\"`）只许引真实论文（`lit:`），"
        "手稿里的内容要进论文必须在正文里**重建**（重建出来的东西再以 `stmt:` / `exp:` / "
        "`rel:` 落台账、被论文引用）。没给 `citing_kind` ⇒ 只判形状与存在性（老行为）。"
    )


def classify_proof_location(loc: object, known_ids: Iterable[Any]) -> tuple[str, str]:
    """`proof_location` 的形态分类：整个仓库只有这一份实现（`R2R2-R1`/`R2R2-R2`）。
    为什么必须只有一份：写入期（本模块的 :func:`check_proofs`）与事后门（`gates.gate_g3`）对同一个字符串必须给出同一个分类。旧版各写一套正则、
    彼此没有交叉断言，实测同一份数据 18 档里有 9 档分歧 —— 其中最难看的一档是"断言自己连 `claim_id` 都没有，
    `proof_location="claim-1:3"`"：写入期报"指向一个不存在的断言"，事后门却判成 `file:line` 并 pass。
    返回 `(kind, base)`：
    - `("self_ref", base)`：`loc` 是本文档里真实存在的 `claim_id`（裸写、或`claim_id:行号`）；`base` 是那个 
    `claim_id`。- `("cross_ref", base)`：形态是 `名字:数字`（没有点号后缀 ⇒ 不是文件名），但 `base` 不在 `known_ids`
    里。两个调用方对此处置不同、分类相同：`gate_g3` 报 error（事后分不清"忘了登记"与"根本不存在"，fail-closed）；`check_proofs` 报
    `proof_location_not_found`（写入期能说得更准）。注意：这条差别是刻意的：分类同口径 ≠ 处置同强度。- `("file", base)`：其余一切，
    当路径看。是否真的存在由调用方决定 ——`check_proofs` 要求"工作区内、盘上真实存在"，`gate_g3` 只要求"形态可解析"（它是事后门，不读盘；这层强弱
    差别同样刻意的，见 `gate_g3` 的适配说明）。
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
    为什么需要它（`temp/auditD-proof-selfreport.txt` 那次复现）`check_citations` 只回答"引用的对象存不存在"。而 `evidence_kind="proof"` 这一档在写入期一条判据都没有：实
    测（`temp/r2-d1-probe.txt`）下面四种形态全部写库成功：
    ① `proof_location="PROOF-DOES-NOT-EXIST.lean:1"`（文件根本不在盘上）；② 连 `proof_location` 都不给；③ 只引 `lit:`（不引任何 `exp:` —— 没有任何实验参与过）；
    ④ 引一条 `evidence_kind="cross_check"` 的数值实验却声称 proof。四种的共同后果：`documents` 里出现一条"看起来有形式化背书"的断言，而没有任何检查器参与过；下游（报告、gates）把 
    `evidence_kind` 当证据等级读。`verify` 侧只有"引用了 `exp:` 时才查那条实验的等级"（`verify.py` 的`proof_claim_rests_on_weaker_evidence`），所以 ③ 那种"一条
    exp: 都不引"的形态连事后也查不出来。
    ==========================================  ==========================================条件
    要求==========================================  ==========================================引用的 `exp:` 行
    `result` 是 `"refutes"` 时必须是否定型断言（`is_negative` + `negation_kind="disproved"`）—— 2026-10-13 加：引一条否证当支撑此前一路过闸
    `evidence_kind == "proof"`                  必须至少有 1 条 `exp:` 引用被引用的 `exp:` 行                          `evidence_kind` 必须是 
    `"proof"`同一条断言                                  必须给出 `proof_location``proof_location`                            必须指向工作区内真
    实存在的文件；或者是本文档里真实存在的 `claim_id`（自指）==========================================  ==========================================
    第四条只证明"文件在"，不证明"文件里有那条证明" —— 那是形式化检查器（`formalgw`）的事，本函数不冒充它。
    注意：第四条曾经有个可被满足的形态缺口（`R2-R1` / `R2-R2`，重审实测）：只要 `proof_location` 长得像 `名字:数字`（例如 `not-a-claim:7`）就整条跳过，于是"指向一个不存在的断言"与"指向工作区
    外的文件"两种写法都写库成功。
    注意口径的准确说法（`R2R2-R1` 更正）：本函数与事后门 `gates.gate_g3`共用同一份形态分类实现（:func:`classify_proof_location`），但判据强度不同 ——`check_proofs` 在分类之上
    加两道（工作区包含性 + 盘上存在性），`gate_g3` 只做形态可解析（事后门，不读盘）。
    与 `check_citations` 同形：`rows_of is None` ⇒ `checked=False`（没查成，不得读成"证据都齐"）。
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
        cid = str(c.get("claim_id") or f"claim-{i}")
        exp_refs = [
            citation_ref_parts(x)[1]
            for x in (c.get("citations") or [])
            if citation_ref_parts(x)[0] == "exp"
        ]
        # ---- 第五道（2026-10-13，无 Lean T2 的真机）：引一条否证的实验当支撑。
        # 现场：`projects/p6t2-research-20261012b` 的 exp:0002 自己的结论是 `result="refutes"`
        # （`counterexample: criterion mismatch …, mismatches: 108`），而论文的 claim-2 把它列进 `citations`
        # 当支撑用。`check_citations` 只问"引用的对象在不在"，所以这条一路写库；而按 `evidence_kind` 分档，
        # "被自己的实验否证"与"被自己的实验支持"在纸面上长得一模一样。判据：引了 `result="refutes"` 的实验 ⇒
        # 这条断言必须是否定型里"已证否"那一档（`is_negative` 且 `negation_kind="disproved"`）—— "实验否证了 P"
        # 与"P 成立"是两件相反的事，不许靠读正文才分得出来。2026-10-21：判定本体搬进
        # `verifications.opposite_direction_evidence`（FC-03：同一句话两处各写一份必然漂移），本处只保留
        # "problem 的 kind / detail"这一层翻译；判据本身与"哪一半判不了"的上界都写在那个函数里。
        for ref in exp_refs:
            row = exp_by_id.get(ref)
            if row is None:
                continue
            if VR.opposite_direction_evidence(c, row) is None:
                continue
            problems.append({
                "claim_id": cid,
                "kind": "claim_cites_a_refuting_experiment",
                "detail": (
                    f"这条断言引了 {ref} 当支撑，而 {ref} 自己的结论是 "
                    f"`result={str(row.get('result'))!r}`（否证）⇒ 引一条否证当支撑。"
                    "要么把这条断言改成否定型并写 `negation_kind='disproved'`"
                    "（'我们证否了它'），要么换一条支持它的证据；"
                    "只在正文里解释'那只是脚本内部判据的问题'不算数 —— 台账上它仍是 refutes"
                ),
            })
        if str(c.get("evidence_kind") or "") != "proof":
            continue
        if not exp_refs:
            problems.append({
                "claim_id": cid,
                "kind": "proof_claim_without_formal_experiment",
                "detail": (
                    "声称 evidence_kind='proof'，却一条 `exp:` 引用都没有 ⇒ "
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
                            f"{str(row.get('evidence_kind'))!r} ⇒ 断言不能强于它的依据"
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
    闸门在这里，但判据只有一份（`claimanatomy`）schema 也会拦（`Document.validate` 有同样的三条硬约束），但它的报错只能说到"claims[3] 没有 citations" —— 而在撰写现场，真正需要被指出来的是"就是这一句话缺引用"。本函数不再自己写任
    何一条检查：它把参数装配成一条 claim，然后交给:func:`agentflow.claimanatomy.validate_claim` 判，把第一个 error 抛出来。这样 G 与 H 的判据不可能漂移（FC-03 / INVENTORY 4.5#10）。强制的规则（全部由 
    `claimanatomy.CLAIM_FIELDS` 声明）- `evidence_kind == "cross_check"` ⇒ 自动填``disclaimer = CROSS_CHECK_DISCLAIMER``。不靠调用方记得写（FC-22）。- 
    `is_negative=True` 且没给 `negation_kind` ⇒ 抛（不静默填默认值）："未证明"、"已证否"、"没搜过"是三件不同的事，默认值等于替作者做了一个他可能不同意的数学判断。-`citations` 为空 ⇒ 抛。无引用的断言在结构上不允许存在（FC-02）。- 
    正文含超过用词上限的措辞 ⇒ 抛（上限由 `wording_ceiling()` 现算：`proof` 永远在，关掉 Lean 时`proof_review` 也在 —— 2026-10-13 更正：这一行此前写的是"而 `evidence_kind != "proof"`"，那是加 
    `proof_review` 之前的旧口径，与代码不符；- `status="作废"`且既无 `errata_ids` 又无 `freeze_reason` ⇒ 抛（作废必须有原因）。- `frozen=True` 且 `freeze_reason` 为空 ⇒ 抛。§8.3 新增的 12 个
    字段（全部可选）`kind` / `status` / `proof_location` / `numeric_evidence` / `counterexamples`/ `frozen`+`freeze_reason` / `allowed_use` / `scope_caveat`
    / `revision_hash`/ `errata_ids` 都是可选参数：不给就不写进 dict（不是写一个假默认值）——"没提这件事"与"明确说了没有"必须能分开（三态纪律）。返回的是磁盘形态（正文字段名是 `text`）：`schema.Document.validate`逐字读 
    `c.get("text")`，而它在 FC-27 禁 AI 区、本任务无权改。判据层的正名是 `statement`，两者的往返由`claimanatomy.migrate_claim` / `to_storage_claim` 一处完成。`claim_id` 可省略：此时按内容派生一个稳
    定代号（同样的内容得到同样的代号）。`build_document` 落库时会按顺序补成 `claim-1…claim-N`。
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
        #: cross_check / proof_review 的那句声明由结构强制，不靠人记得写（FC-22）。
        "disclaimer": _disclaimer_for(evidence_kind),
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
    ====================================  ==========================================表
    对应约束====================================  ==========================================证据等级统计（proof / cross_check /      FC-10：
    三档分开计数，禁止单一通过率 heuristic）否定型结论分类（未证明/已证否/未搜索）   FC-25：四种否定分开计数依赖表（带 external_unavailable 标注）
    FC-23：引用的外部结论必须显式可见断言清单（每条带 citations）            FC-02：每条断言都能回答"我引用谁
    "====================================  ==========================================
    三态纪律：`dependencies=None` 表示调用方没给依赖清单（没查），此时表里写"未提供"，而不是写"0 条" —— "没查"和"查了、没有"必须能分开。
    ## 渲染层门（`draft/17` §8.4 的 G14 降级合规门在这里落地）
    `status="作废"` 的断言 —— 以及 `allowed_use="移入 open"` 的断言 ——不得出现在正文主结果区（§3 断言清单）。它们被移到附录 A，并必须带上撤销原因（`errata_ids`
    或 `freeze_reason`）。判据只有一份：`claimanatomy.main_body_claims()` / `retracted_claims()`。
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
    lines.append("1. **每条断言都带引用**（`citations`，形如 "
                 + citation_prefix_examples() + "）。")
    lines.append("   没有引用的断言在结构上无法进入本稿（`schema.Document.validate` 强制）。")
    # 证据等级那一段从词表现算（2026-10-13 修）：此前这里写死"只有三档"并列了
    # 三档（`proof` / `cross_check` / `heuristic`），而下面第 1 节的表按
    # `S.EVIDENCE_KINDS` 逐档出行 —— `proof_review` 加进来之后，同一篇稿子的第 0 节
    # 说"三档"、第 1 节的表却列出四行，自相矛盾。真机读数：
    # `projects/p6t2-research-20261012b/documents/0002.md`（无 Lean 模式那一趟）第 11 行
    # 逐字是"证据等级只有三档"，而第 19–24 行的表里赫然有 `proof_review` 一行。
    # 后果不只是难看：没有 Lean 的用户读到这句话，会以为"逐行审阅过的证明"这一档
    # 不存在 —— 而那一档正是他这个模式下唯一能承载"定理 / 证明"的凭据。
    _levels = "、".join(f"`{k}`（{EVIDENCE_LABELS.get(k, '')}）" for k in S.EVIDENCE_KINDS)
    lines.append(f"2. 证据等级共 {len(S.EVIDENCE_KINDS)} 档，且**必须分列**：{_levels}。")
    lines.append(f"3. **`cross_check` 不是证明**：这类断言后面自动附「{CROSS_CHECK_DISCLAIMER}」；")
    _pr = DISCLAIMER_BY_EVIDENCE_KIND.get("proof_review", "")
    if _pr and "proof_review" in S.EVIDENCE_KINDS:
        lines.append(f"   `proof_review` 那一档同样自带「{_pr}」—— 两条声明各写在自己那一栏里。")
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
    lines.append("## 1. 证据等级统计（分档计数，不是单一通过率）")
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
        f"因此这里**只报分档计数**（FC-10）：每一档一条，档数由 `schema.EVIDENCE_KINDS` 定，"
        f"今天是 {len(S.EVIDENCE_KINDS)} 档。"
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


# ---------------------------------------------------------------- 中间产物自己的 sha（`D-44`）
#
# 业主 2026-10-24：「只对论文负责是正确的，documents等都是中间产物」＋
# 「H 审论文（out/paper/main.tex / pdf），documents 只是它的登记行」。
#
# 于是 `documents` 这一行是中间产物，它指向的 markdown 只是 `render_markdown`
# 的一份呈现。这一节记的是"写这一行时盘上那份 markdown 的字节 sha256"：
#
#   * 唯一口径 = `artifacts.sha256_of`（字节级，不做任何归一化）。不接收调用方传进来的
#     值，也不在别处再算一份 —— sha 一旦有两个来源，"这一份有没有变过"就没有答案了；
#   * 落点是事件流里的一条 info（`Tx.info`），不是那一行上的新字段：`documents` 的
#     字段面归 `schema.py`（FC-27 禁改区）；而它现有的 `content_sha256` 是
#     "这一版内容"的规范哈希（`signatures.content_sha256_of`，签名台账与
#     `doc:@hash` 内部引用都钉它）——把文件 sha 塞进那一格会让 `verify` 的重算判据与
#     整条签名链同时失效（实测：改写侧每写一次文件就会换一次字节，而内容一个字节没变）；
#   * 它只用于人工追溯「这份中间产物后来有没有被人改过」，不作任何收工门的判据：
#     读侧 `document_artifact_readings` 的结论没有进 `verify`、也没有进 `closing`。
#
# 为什么"文件字节"不等于"内容哈希"（这也是这一条不能折进 `content_sha256` 的原因）：
# `render_markdown` 会把 `status` / 审校轮次画进文件，而 H 审完只改 `status` ⇒
# 同一份内容、状态一翻，盘上那份文件的 sha 就变了；`Path.write_text` 在 Windows 上
# 还会把 "\n" 翻成 "\r\n" ⇒ 同一份内容在两个平台上也是两个字节串。所以文件的 sha
# 只能是"这一份产物"的指纹，不能是"这一版内容"的指纹。

#: 事件流里记"这条中间产物的 sha"的 message（读侧按它反查）。
ARTIFACT_EVENT = "documents.markdown_sha256"


def note_markdown_artifact(store: Any, doc_id: Any, rel: Any, absolute: Any, *,
                           actor: str = "agent-G") -> dict:
    """给"已经写好的一份中间产物"补记一条 sha（自己开一笔只记日志的事务）。

    它是给"重画 markdown"那条路用的（`AgentG.refresh_markdown`：依赖是稿件写完之后
    才登记的，重画是正常动作）。为什么不把 `store.tx` 写进那个调用方：那条路的职责是
    只重画文件、不改任何数据行，而"写 documents 行的事务必须跑 normalize_claims"
    这条机械判据（`tests/test_core_audit_efgh.py`）会把它读成一次写稿 —— 在这里开事务
    就把两件事分清了：这里只追加一条 info 事件，一个字段都不写。
    """
    with store.tx("documents", actor=actor, note=f"{ARTIFACT_EVENT} doc:{doc_id}") as tx:
        return record_markdown_artifact(tx, doc_id, rel, absolute)


def record_markdown_artifact(tx: Any, doc_id: Any, rel: Any, absolute: Any) -> dict:
    """在那笔写 `documents` 行的事务里，记下盘上那份 markdown 的字节 sha256。

    必须在文件写完之后调（`D-44` 的现场就是"记的 sha 与盘上那份对不上"）。
    读不到文件时不编一个哈希：`sha256` 留空 + `problem` 写清原因 ——
    "我没读到"与"我读到了、就这么长"必须分得开（三态纪律）。

    返回的读数与事件里的字段逐字相同，方便调用方把它带进自己的返回值。
    """
    from .. import artifacts as A

    path = Path(str(absolute))
    sha256, size, problem = "", 0, ""
    try:
        sha256 = A.sha256_of(path)
        size = int(path.stat().st_size)
    except OSError as e:  # noqa: BLE001 —— 读不到是读数，不是异常上抛
        problem = f"{type(e).__name__}: {e}"
    reading = {
        "doc_id": str(doc_id),
        "path": str(rel or "").replace("\\", "/"),
        "sha256": sha256,
        "bytes": size,
        "problem": problem,
    }
    tx.info(ARTIFACT_EVENT, **reading, note=(
        "中间产物（documents 行指向的 markdown）写盘那一刻的字节 sha256；"
        "只作人工追溯，不作任何收工门判据"
    ))
    return reading


#: `document_artifact_readings` 每行的状态（四态 + 第三态"没记过"）。
ARTIFACT_STATUSES: tuple[str, ...] = ("ok", "changed", "missing", "unreadable", "unrecorded")


def document_artifact_readings(store: Any, doc_ids: Sequence[str] | None = None) -> dict:
    """逐行报：`documents` 行指向的那份中间产物，现在还是不是写它时那一份。

    `status` 取 :data:`ARTIFACT_STATUSES` 之一：

    - `ok`：盘上那份与写这一行时逐字节相同；
    - `changed`：文件还在，但字节变了（只作读数：`refresh_markdown` / `revise`
      正常改写它也是这一档）；
    - `missing` / `unreadable`：不在了 / 读不出来（两种处置不同，不折平）；
    - `unrecorded`：这条行没被记过 sha（改动之前写的行都是这一档）——
      那是"判不了"，不是"没问题"。

    为什么它不是判据：业主对这条的全部口径是"只用于人工追溯，不作收工门判据"。
    所以本函数不做通过/不通过，只给四态读数；任何门都不许拿它当收工条件。
    """
    from .. import artifacts as A

    want = {str(x) for x in doc_ids} if doc_ids is not None else None
    recorded: dict[str, dict] = {}
    for e in store.read_events():
        if str(e.get("op") or "") != "info":
            continue
        if str(e.get("message") or "") != ARTIFACT_EVENT:
            continue
        did = str(e.get("doc_id") or "")
        if not did:
            continue
        # 最后一次写入为准：同一份稿件可以改很多次（revise / refresh_markdown）
        recorded[did] = dict(e)
    root = Path(str(getattr(store, "root", "") or "."))
    rows: list[dict] = []
    for doc in store.rows("documents"):
        did = str(doc.get("doc_id") or "")
        if want is not None and did not in want:
            continue
        rel = str(doc.get("markdown_path") or "")
        got = recorded.get(did)
        row = {
            "doc_id": did,
            "markdown_path": rel,
            "sha256_recorded": str((got or {}).get("sha256") or ""),
            "sha256_now": "",
            "bytes_now": 0,
            "status": "unrecorded",
            "reason": "",
        }
        if got is None:
            row["reason"] = (
                "这一行没有被记过中间产物的 sha（改动之前写的行）⇒ 判不了它有没有变过"
            )
        elif not rel:
            row["status"] = "missing"
            row["reason"] = "这一行没有 markdown_path ⇒ 没有中间产物可核对"
        else:
            target = root / rel
            if not target.is_file():
                row["status"] = "missing"
                row["reason"] = f"{rel} 不在盘上了"
            else:
                try:
                    row["sha256_now"] = A.sha256_of(target)
                    row["bytes_now"] = int(target.stat().st_size)
                    row["status"] = (
                        "ok" if row["sha256_now"] == row["sha256_recorded"] else "changed"
                    )
                    if row["status"] == "changed":
                        row["reason"] = (
                            "中间产物内容已变：写这一行时是 "
                            f"{row['sha256_recorded'][:16]}…，盘上现在是 "
                            f"{row['sha256_now'][:16]}…（只作读数，不进任何门）"
                        )
                except OSError as e:  # noqa: BLE001 —— 读不出来是第三态，不是"没变"
                    row["status"] = "unreadable"
                    row["reason"] = f"{rel} 读不出来（{type(e).__name__}: {e}）"
        rows.append(row)
    # 出口自检：状态词表只有一个声明面（ARTIFACT_STATUSES），实现不许漏出一个新词。
    unknown_status = sorted({str(r["status"]) for r in rows} - set(ARTIFACT_STATUSES))
    if unknown_status:
        raise ValueError(f"中间产物读数的状态 {unknown_status} 不在 {ARTIFACT_STATUSES} 里")
    changed = [r["doc_id"] for r in rows if r["status"] == "changed"]
    return {
        # 三态：一条都没记过 ⇒ 这一维"没查成"（不是"都好好的"）
        "checked": bool(recorded),
        "reason": (
            f"核对了 {len(rows)} 行；内容已变 {len(changed)} 行"
            + (f"（{changed[:5]}）" if changed else "")
            if recorded
            else "没有任何一行被记过中间产物的 sha ⇒ 这一维**没查成**（不是'没变过'）"
        ),
        "rows": rows,
    }


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
    顺序刻意如此：先逐条机械检查 → 再核引用是否存在 → 再分配 ID → 再渲染 → 最后提交。这样任何一条不合规的断言、任何一条指向不存在对象的引用，都不会换来一个"半成品稿件 + 一个已经烧掉的
    doc_id"。
    为什么 markdown 在工作区内渲染（而不是返回字符串了事）：`markdown_path` 是 FC-02 追溯链的一环 —— 稿件必须有一个可被人打开的落点，否则"H 审的是哪个版本"就无法回答。
    ## 引用必须真的存在（本函数曾经的缺陷）
    `scan_claim` 只查"`citations` 非空"，从不解析 `lit:` / `rel:` / `exp:`指向的对象是否存在。于是 `citations=["lit:9999"]` 会照样写库
    + 渲染，直到事后 `verify` 才报 `dangling_citation` —— 而那时坏引用已经进了稿件。现在写库前用 `check_citations` 核一遍四张表；有坏引用就整笔不写，并把每一
    条坏引用逐条列进失败详情（`kind="dangling_citation"`）。
    ## `evidence_kind="proof"` 的证据锚（`D-1`）
    引用存在还不够：一条自报 `proof` 的断言即使引用都存在，也可能"没有任何形式化检查参与过"（实测四种形态全部写库成功，见 `temp/r2-d1-probe.txt`）。所以紧接着再跑 
    `check_proofs`：必须有 `exp:` 引用、那条实验必须是 proof 级、必须有 `proof_location`、且那个文件必须真的在盘上。
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
        # `statements` 必须在这里（2026-10-09，T1 第 20 趟实测抓出来的缺口）：
        # `check_citations` 按 `_CITATION_TABLES`（= `schema.CITATION_PREFIXES`，六张表）
        # 逐条核引用，而 `stmt:` 指的正是 `statements`。原先这一笔只声明了五张表 ⇒
        # 任何引用我们自己命题的稿件（`citations: ["stmt:0001"]`，正是提示词教的那种写法）
        # 都会在事务里读一张没声明的表 ⇒ `存储故障：事务未声明表 statements` ⇒
        # 整笔不写库、`documents` 永远是 0 行（P9 因此红了三趟）。
        # 教训与 S1g 那条同族：读哪些表由判据决定，声明必须与判据同源。
        "statements",
        actor=actor,
        note="build_document",
    ) as tx:
        cites = check_citations(tx.rows, norm, citing_kind=kind)
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
        # `D-44`：这一行是中间产物 ⇒ 记下盘上那份 markdown 的字节 sha256
        # （唯一口径 `artifacts.sha256_of`，不接收任何传进来的值）。
        # 必须写在文件落盘之后：改前的现场就是"记的 sha 与盘上那份对不上"。
        # 它是人工追溯用的读数，不作任何收工门判据（见 `record_markdown_artifact`）。
        record_markdown_artifact(tx, doc_id, rel, absolute)
    return payload


def register_dependency(
    store: Any,
    used_by: str,
    kind: str,
    label: str,
    *,
    source_lit_id: str | None = None,
    source_experiment_id: str | None = None,
    source_stmt_id: str | None = None,
    path_group: int = 1,
    proof_no: int = 1,
    page_range: Any = None,
    quote: str = "",
    status: str = "dangling",
    status_reason: str = "",
    actor: str = "agent-G",
) -> dict:
    """登记一条外部依赖（FC-23）。返回落库后的行 dict。
    ## 为什么"closed 必须指向已入库来源"要在这里再核一遍
    `schema.Dependency.validate` 只能检查"`status='closed'` 时字段非空" ——它看不见 `literature` / 
    `experiments` / `statements` 表，因此一个不存在的 lit_id 也能通过 schema。而"这个 lit_id 真的存在"正是"依赖闭合"的全
    部含义。所以第一道闸必须在 G 手里用真实数据核：字段非空 ≠ 来源存在。
    第二道闸（依赖集的可查询闭合性）由 H/verify 侧的重算负责 —— 两道闸缺一不可：一个查"引用长得对不对"，一个查"引用的东西在不在"。
    ## 第四种来源与"多组路径"（2026-10-09，业主两句裁定）
    `source_stmt_id`：被依赖的那一端是我们自己的一条命题（定理用到定理、定理用到某个概念）。此前那种边无处安放（`draft/97` §15.0 的 E2：字段
    表里没有它），于是"承重链"在数据面上断在命题之间。
    `path_group`：证明路径不唯一 ⇒ 一条定理可以有多组依赖（两个文献各有证明、或一条更漂亮的路径）。同一 `used_by` + 同一 `path_group`
    = 一条路径（组内 AND：都要走通）；不同 `path_group` = 可选路径（组间 OR：任一走通即可）。 B 那一侧交的是二维列表，秘书按外层下标写这一列（`Secretary.record_statement`）。
    ## 规矩 A（业主 2026-10-22）：`source_stmt_id` 按"实际收录过的序号"回填
    给了 `source_stmt_id` 的任何一条边（不分 status）在写入前都要过三态判定：那个号在
    `statements` 里存在吗 / 它 `active` 吗（口径取自 `schema.STATEMENT_UNUSABLE_STATUSES`）/
    `statements` 读得出来吗。三条读数各自有拒绝理由（"不存在" / "没 closed" / "没查成"），
    而不是一句"依赖不合法"；读不到绝不当成通过。判据在
    `tests/test_dependency_strictness.py`。
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
    if status == "closed" and not (source_lit_id or source_experiment_id or source_stmt_id):
        raise ValueError(
            "status='closed' 必须指向一个已入库来源（source_lit_id / source_experiment_id / "
            "source_stmt_id）—— 2026-10-09 起第四种来源是'我们自己的一条命题'")
    if kind == "experiment" and not source_experiment_id:
        raise ValueError("kind='experiment' 的依赖必须给 source_experiment_id")
    if source_lit_id is not None:
        S.require_id(source_lit_id, "source_lit_id")
    if source_experiment_id is not None:
        S.require_id(source_experiment_id, "source_experiment_id")
    if source_stmt_id is not None:
        S.require_id(source_stmt_id, "source_stmt_id")
    # ---- 被依赖的那一端最多给一个（与 `schema.Dependency.validate` 的"四选一"同一口径）。
    # 在这里先判一次是为了给出能行动的话（schema 那句话在事务里抛，读的人手里
    # 只有"最多给一个"，而这里能点名是哪两个撞上了）。
    ends = [("source_lit_id", source_lit_id), ("source_experiment_id", source_experiment_id),
            ("source_stmt_id", source_stmt_id)]
    given = [name for name, value in ends if value]
    if len(given) > 1:
        raise ValueError(
            f"被依赖的那一端最多给一个（给了 {given}）：给两个就说不清这条边到底依赖谁 —— "
            "要表达'两组证明路径'请用 `path_group`（同一 used_by 下组号从 1 起），"
            "一行一条边")
    try:
        group = int(path_group)
    except (TypeError, ValueError):
        raise ValueError(f"path_group 必须是正整数（收到 {path_group!r}）："
                         "同一 used_by + 同一组 = 一条路径（组内都要），不同组 = 可选路径") from None
    if group < 1:
        raise ValueError(
            f"path_group 必须是正整数（收到 {path_group!r}）：0 或负数会让'第几组'失去意义"
            "（同一 used_by + 同一组 = 一条路径，不同组 = 可选路径）")

    # ---- 多证明模型（业主 2026-10-22）：`used_by` 的 `#pN` 尾巴只在这里生成一次。
    # `proofloc` 是全仓拆/拼这个尾巴的唯一解析点（"台账上是第 2 条、读出来是第 1 条"
    # 这种错没有任何东西会报）。先按前缀分流：`doc:` 前缀的 `used_by` 也用 `#`
    # （`doc:0001#claim-3`，见 `dependencies_for_doc` 的归属判据），那个尾巴是 claim 号、
    # 不是证明号 —— 什么都不做，绝不往上拼。
    # 缺省 `proof_no=1` ⇒ 生成的 `used_by` 与改前逐字相同（canonical 不写尾巴）。
    try:
        no = int(proof_no or _PL.DEFAULT_PROOF_NO)
    except (TypeError, ValueError):
        raise ValueError(f"proof_no 必须是正整数（收到 {proof_no!r}）") from None
    if no < 1:
        raise ValueError(f"proof_no 必须是正整数（收到 {proof_no!r}）："
                         "第 0 条证明不存在（不带 `#pN` 等价于第 1 条）")
    if str(used_by).startswith("doc:"):
        if no > _PL.DEFAULT_PROOF_NO:
            raise ValueError(
                f"`doc:` 前缀的 used_by 没有证明号（收到 {used_by!r} + proof_no={no}）："
                "`doc:0001#claim-3` 的尾巴是 claim 号，证明号只挂在 `stmt:` 引用上")
        used_text = str(used_by)
    else:
        # 已经带着尾巴的写法先经 `proofloc` 归一到命题号，再挂上这一次的证明号。
        used_text = (str(used_by) if no <= _PL.DEFAULT_PROOF_NO
                     else _PL.used_by_of(_PL.parse_used_by(str(used_by))[0], no))

    with store.tx(
        "dependencies", "literature", "experiments", "statements",
        actor=actor, note="register_dependency"
    ) as tx:
        # ---- 严格规矩 A（业主 2026-10-22：「转写是提示词侧点一下就行……其它要严格」）
        # `source_stmt_id` 必须按"实际收录过的序号"回填：任何 status 都核，不再只在
        # `status='closed'` 时核（一条 `dangling` 边指着一个不存在的号同样是坏数据：
        # 它在盘上长得像"这条结论依赖某条命题"，而那条命题根本不存在）。
        #
        # 三态，各给一条能行动的理由，绝不当成通过：
        #   ① 那个号不在 `statements` 里 ⇒ 不存在；
        #   ② 在册但状态不是 `active` ⇒ 没 closed（`pending_definition` / `disputed` /
        #      `refuted` / `superseded` 都不是依据；口径直接读
        #      `schema.STATEMENT_UNUSABLE_STATUSES`，不在这里另立第二份名单）；
        #   ③ `statements` 读不出来 ⇒ 没查成（读不到绝不等价于"核过了"，也不等价于
        #      "库里没有这一条"）。
        # 为什么必须在写入期核：verify 的依赖闭合审计只看得到盘上已经有的行，一条回填错的
        # 序号进了库之后，"这条结论靠什么站着"就已经答错了，而报告照样亮绿。
        if source_stmt_id is not None:
            try:
                stmt_rows = list(tx.rows("statements"))
            except Exception as exc:  # noqa: BLE001 —— 读不到要如实说，不许当成通过
                raise ValueError(
                    f"source_stmt_id={source_stmt_id!r} 没查成：statements 表读不出来"
                    f"（{type(exc).__name__}: {exc}）⇒ 拒绝写入。三态纪律：'读不到'不是"
                    "'核过了'，也不是'库里没有这一条'—— 先用 `agentflow verify` 定位"
                    "（必要时 `agentflow rebuild` 重建），再登记这条边"
                ) from None
            anchor = next((r for r in stmt_rows
                           if str(r.get("stmt_id")) == source_stmt_id), None)
            if anchor is None:
                raise ValueError(
                    f"source_stmt_id={source_stmt_id!r} 不存在：statements 表里没有这一行"
                    f"（表里现有 {len(stmt_rows)} 条命题）。依赖边必须按实际收录过的序号"
                    "回填，不许指一个还没进库的号 —— 指一条不存在的命题，"
                    "'这条结论靠什么站着'就答不出来（`draft/97` §15.0 的第四种来源）"
                )
            anchor_status = str(anchor.get("status") or "").strip()
            if anchor_status != "active":
                shown = anchor_status or "（空）"
                raise ValueError(
                    f"source_stmt_id={source_stmt_id!r} 没 closed：那一行的 "
                    f"statements.status={shown!r}，只有在册可用的 'active' 才算已闭合"
                    f"（这几档都不是依据：{S.STATEMENT_UNUSABLE_STATUSES}）。"
                    "要么先让那条命题走到 active，要么这条边不许写成依赖它 —— "
                    "拿一条待补定义/有争议/被证否/被取代的命题当依据，是一条空头支票"
                )
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
            # `source_stmt_id` 那一档的核已经提到事务开头（规矩 A：任何 status 都核，
            # 三态分开命名）—— 这里刻意不留第二份判据：同一件事两处实现，漂移时
            # 没有任何东西会红。
        dep_id = tx.alloc_id("dep")
        row = S.Dependency(
            dep_id=dep_id,
            used_by=used_text,
            kind=kind,
            label=str(label),
            status=status,
            source_lit_id=source_lit_id,
            source_experiment_id=source_experiment_id,
            source_stmt_id=source_stmt_id,
            path_group=group,
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
    "对一条断言做机械检查：有无引用、证据等级是否被夸大、否定是否分类。",
    {
           "type": "object",
           "properties": {"claim": {"type": "object"}},
           "required": ["claim"],
           "additionalProperties": False,
           },
    side_effect="none",
    roles=_ROLES,
    # 2026-10-15 补齐：这五格实跑都在返回里，而声明里没有。
    # 为什么这件事要紧（`draft/124` §15.2 的更正）：`returns` 会拼进
    # function-calling 的 `description`（`tools/base.py:721`：`summary + "\n返回：" + returns`）
    # ⇒ 「模型看得到」。而它此前看不到 `status_axis` / `undecided_reason` ——
    # 那两格「正是三态」（"这条没查成"与"这条查过没问题"靠它们分开）。
    # 模型不知道存在的字段，它不会用；那样三态纪律在「模型这一侧」又折回去了。
    returns="{'checked','claim_id','ok','findings','error_count','warning_count',"
            "'checked_fields','decided','revision_hash','status_axis','undecided_reason'}",
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
            "构造一条合规断言：`cross_check` 自动补「不构成证明」声明；无引用 / 否定未分类 / 过度声称 / 作废无原因在构造时就抛错。"
            "可带生命周期字段（kind/status/proof_location/scope_caveat/allowed_use/frozen）。"
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
            "'negation_kind','disclaimer','revision_hash','scope_caveat'}"
            "（合规的 claim dict）；带 §8.3 字段时原样透出。"
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
    "只读列举稿件（代号/类型/标题/状态/审校轮次/断言数）。",
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
            "写一行 documents 并渲染 markdown 到工作区内（机械检查 + 核对每条 citation 指向的对象存在，两闸都过才落库；out_path "
            "越界拒绝）。"
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
                                      "description": ("必须非空（FC-02）："
                                                      + citation_prefix_examples()
                                                      + " 这类可回查的引用（前缀的全部"
                                                      "取值见 `schema.CITATION_PREFIXES`；"
                                                      "`doc:` 那一档还要带 "
                                                      "`#<断言>@<内容哈希前 16 位>`）。"
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
            # 「2026-10-15 补」：这一格此前是光秃秃的 `{"type":"array","items":{"type":"object"}}`
    # —— 没有说明、没有 `properties`。后果是「形状不可达」：
    #   · 模型照它填，只能猜每个元素是什么；
    #   · 被拒之后框架会给"完整参数表"（`agent_loop._param_table`），
    #     而那张表「也是照 schema 打的」 ⇒ 它同样只会说 "sections: array"。
    # 真机读数（九趟 T5 的 `events.jsonl`）：因它的形状被拒 「11 次」
    # （"`sections.[N]` 必须是对象，收到 string" 6 次 ＋ "`sections[N]` 必须是含 `heading` 的对象" 5 次）。
    # 紧邻的 `claims` 那一格「有」详尽说明（还记着"T1 实测在这里连拒 7 次"）⇒ 这里当年是「漏了」。
    "sections": {
        "type": "array",
        "description": ("正文分节：**每个元素是一个对象** `{heading, body}`"
                        "（写成字符串会被拒 —— 实测被拒过 11 次）。"
                        "`heading` 必填且非空（那一节的标题），`body` 可缺省（markdown 正文）。"),
        "items": {
            "type": "object",
            "properties": {
                "heading": {"type": "string", "description": "这一节的标题（必填、非空）"},
                "body": {"type": "string", "description": "这一节的 markdown 正文（可缺省）"},
            },
        },
    },
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
            "'status','review_rounds','created_at','updated_at','created_by',"
            "'content_sha256','revision','review_verdict','reviewed_at','reviewed_by'}（落库后的 documents 行）；"
            "**meta.citation_coverage** = 这份稿子引了几条 `lit:`/`rel:`/`exp:`/`stmt:`/`doc:` "
            "+ 库里有多少可引的（含 `gaps` 与 `suggest_lit`/`suggest_rel` 样例，只报数不拦）；"
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
    if store is None:
        return _not_wired()
    res = guard_result(
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
    # 「这份稿子引了几条台账凭据 / 库里还有多少可引的」放进工具结果的 meta：
    # `agent_loop` 把 `meta` 一并给模型看（`out = {tool, ok, data, error, meta}`），
    # 而 `data` 是落库的那一行（它要算内容哈希、要被 schema 校验）⇒ 不许往里加键。
    if res.ok and isinstance(res.data, Mapping):
        try:
            res.meta["citation_coverage"] = citation_coverage(
                store.rows, res.data.get("claims") or [], citing_kind=str(kind or ""),
                # 盘上那个 `library/` 的根：判"真有全文"要看盘（状态说 ok 而文件没了
                # 是另一种"没查成"）。
                library_root=(Path(workspace) / "library") if workspace else None,
            )
        except Exception as exc:  # noqa: BLE001 —— 读数算出问题不许影响这笔写入
            res.meta["citation_coverage"] = {"readable": False,
                                             "reason": f"{type(exc).__name__}: {exc}"}
    return res

@tool(
    "doc.register_dependency",
    (
            "登记外部依赖（FC-23）：`closed` 前用真实数据核 `lit_id`/`experiment_id`/`stmt_id` 已入库；`dangling`"
            "/`external_unavailable` 必须写 `status_reason`。`source_stmt_id` = 依赖的是我们自己的一条命题；`"
            "path_group` = 第几条证明路径（组内都要、组间任一）。"
            ),
    {
           "type": "object",
           "properties": {
            "used_by": {"type": "string"},
            "kind": {"type": "string", "enum": list(S.DEP_KINDS)},
            "label": {"type": "string"},
            "source_lit_id": {"type": "string"},
            "source_experiment_id": {"type": "string"},
            "source_stmt_id": {"type": "string"},
            "path_group": {"type": "integer",
                           "description": "证明路径的组号（从 1 起）。同一 used_by + "
                                          "同一组 = 一条路径（组内都要）；不同组 = 可选路径"},
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
    # （`S.Dependency` 全字段，2026-10-09 加 `source_stmt_id` 与 `path_group` 后 14 个；
    # 2026-10-15 补 `source_claim_id` / `source_doc_id` —— 它们是"这条依赖的「来源」"
    # 那一族的两格，此前只写在声明之外，而 `returns` 会进模型看得到的 `description`）。
    returns="{'dep_id','used_by','kind','label','source_lit_id','source_experiment_id','source_stmt_id','source_claim_id','source_doc_id','path_group','page_range','quote','status','status_reason','created_at','created_by'}（落库后的 dependencies 行）",
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


# ---------------------------------------------------------------- 正文编译（`doc.paper_compile`）


def _resolve_project_root(workspace: Path | None, project: str) -> tuple[Path | None, str]:
    """把 `project` 解析成工作区内一个真实目录。返回 `(路径, 问题)`。

    与 `resolve_out_path` 同一个纪律：越界（绝对路径、`..`、跳到工作区外）一律拒。
    这一层要起子进程并把它的工作目录设成这个路径 —— 放宽等于把"跑什么、在哪跑"
    交给调用方，而工具层把那个能力定义成 `exec`（需要审批）。
    """
    raw = str(project or "").strip()
    if not raw:
        return None, "project 不能为空（它是正文所在的项目根，例如 projects/p6t2-research-x）"
    cand = Path(raw)
    if cand.is_absolute():
        return None, f"project 必须是工作区内的相对路径（收到绝对路径 {raw}）"
    if workspace is None:
        return None, "没接线：装配时既没给 workspace_root 也没给 store ⇒ 不知道该相对谁解析 project"
    root = workspace.resolve()
    # 2026-10-17（复跑 T1 暴露的缺陷 61）：「工作区本身就是项目根」时，角色只知道项目叫
    # `t1s`，会传 `project="t1s"`；原来拼成 `projects/t1s/t1s` ⇒ "项目目录不在盘上"。
    # 接受三种写法：`.`、工作区自己的名字、以及相对 `projects/` 的路径。
    if raw in (".", root.name):
        return root, ""
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

def _paper_compile(workspace: Path | None, project: str, timeout_sec: float) -> Any:
    """`doc.paper_compile`：把 `<项目根>/out/paper/main.tex` 编成 `main.pdf`（框架内置编译）。

    它「不跑项目脚本」。旧路那一整套（`paper_render` / `paper_anchor` / `paper_build` /
    `paper_state` 四条工具 + `G.paper_package` 动作）随业主 2026-10-13 的裁定退场：
    「paper_package 里那些东西都是古早废案了，我们要智能体写文章」——
    正文由智能体自己写进 `out/paper/main.tex`，框架只负责把它编成 PDF 并留下回执
    （现状与理由逐条写在 `draft/117`，实现只有一处：`agentflow.papercompile`）。
    """
    root = _paper_root(workspace, project)
    if not isinstance(root, Path):
        return root
    got = PC.compile_paper(root, timeout_sec=timeout_sec)
    body = {
        "tri": got["tri"], "ok": got["ok"], "reason": got["reason"],
        "tex": got["tex"], "pdf": got["pdf"], "engine": got["engine"],
        "exit_codes": got["exit_codes"], "runs": got["runs"], "pages": got["pages"],
        "pdf_bytes": got["pdf_bytes"], "receipt_path": got["receipt_path"],
        "pdf_fresh": got["pdf_fresh"],
        "engine_stderr_tail": got["engine_stderr_tail"],
        "engine_stdout_tail": got["engine_stdout_tail"],
        "problems": got["problems"],
    }
    if got["tri"] == "not_applicable":
        return fail(f"还没有可编的正文：{got['reason']}", kind="paper_no_source", **body)
    if got["tri"] != "computed":
        return fail(f"编译没走成：{got['reason']}", kind="paper_compile_failed", **body)
    # 成功支写成字面量键表：让"返回了哪些键"静态可见（`tests/test_tools_branch_key_sets.py`
    # 的判据按调用点扫 `ok({…})`；写成 `ok(body)` 就成了"看不清"，那一格会红）。
    return ok({
        "tri": got["tri"], "ok": got["ok"], "reason": got["reason"],
        "tex": got["tex"], "pdf": got["pdf"], "engine": got["engine"],
        "exit_codes": got["exit_codes"], "runs": got["runs"], "pages": got["pages"],
        "pdf_bytes": got["pdf_bytes"], "receipt_path": got["receipt_path"],
        "pdf_fresh": got["pdf_fresh"],
        "engine_stderr_tail": got["engine_stderr_tail"],
        "engine_stdout_tail": got["engine_stdout_tail"],
        "problems": got["problems"],
    })


# ---------------------------------------------------------------- 论文对应表（`doc.write_mapping`）


#: 对应表一行的必填字段（与 `papermapping.ROW_FIELDS` 同源：那边的 schema 也不在这里
#: 另写一份）。行的解析与校验一律走 `papermapping.parse_rows`。
_MAPPING_ROW_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(PM.ENV_KINDS),
                 "description": "正文里的环境种类（与那个 \\begin{...} 一致）"},
        "label": {"type": "string", "description": "正文里 \\label{...} 的值（不带花括号）"},
        "env_no": {"type": "integer", "minimum": 1,
                   "description": "正文里第几个该环境（按类计数，1 起）"},
        "ledger_id": {"type": "string",
                      "description": "stmt:NNNNNN / exp:NNNNNN；多证明带 #pN（stmt:000004#p2）"},
        "proof_no": {"type": "integer", "minimum": 1,
                     "description": "第几号证明：1 = canonical（行上的 proof_text）"},
        "file": {"type": "string",
                 "description": "该条完整证明/实验所在的文件（论文包内的相对路径）"},
        "lean_file": {"type": "string",
                      "description": "验它的那份 Lean 源码在论文包里的相对路径"
                                     "（如 formal/000004.lean）。盘上有 Lean 产出时，"
                                     "定理/引理/命题/推论这几行必填"},
        "lean_target": {"type": "string",
                        "description": "那份源码里哪个声明验了它（写源码里字面出现的名字，"
                                       "如 FreeGroupFactor.isII1；不是正文里的 LaTeX label）。"
                                       "与 lean_file 成对：有 Lean 产出时同样必填"},
        "page_or_section": {"type": "string", "description": "给人看的定位（可缺省）"},
        "citation_loc": {"type": "object",
                         "description": "引文的本地位置 {file, page_range|line_range|char_range}"},
        "citation_loc_reason": {"type": "string",
                                "description": "不给 citation_loc 时那句理由"},
        # 数值实验定理那两格（业主 2026-10-23，E-1）：与 `papermapping.Row` 同一份口径，
        # 条件必填（定理类行、且那条命题的证明栏是程序）由读侧判，不在这里进 `required`。
        "numeric_evidence": {"type": "string",
                             "description": "这条定理压着的 E 那条穷举读数（exp:NNNNNN）。"
                                            "证明栏是程序的那几行必填"},
        "exhaustion_note": {"type": "string",
                            "description": "E 写的那两块（程序设计思路 / 穷举论证）与运行环境"
                                           "落在哪一份读数里（相对仓库根，如 "
                                           "out/experiments/000000/exhaustion.md）"},
        # 索引四格（D-34）：D 的报告是目录，B 顺着它去取正文（F 的证明 / E 的报告）。
        # 名字与列义只有一份（`numericproof.INDEX_*`），这里只是把形状告诉模型。
        "evidence_kind": {"type": "string", "enum": list(NP.INDEX_KINDS),
                          "description": "这一行的正文是哪一本：proof（F 的证明）/ "
                                         "report（E 的报告）。数值实验定理那一行填 report"},
        "evidence_path": {"type": "string",
                          "description": "正文在仓库里的相对路径（如 "
                                         "out/experiments/000000/exhaustion.md）"},
        "evidence_sha256": {"type": "string",
                            "description": "那份文件字节的 sha256（不是文本归一化之后的）"},
        "v_signature": {"type": "object",
                        "description": "{verdict, sha256}：V 的结论与它签的那一份的 sha256"},
    },
    "required": ["kind", "label", "env_no", "ledger_id", "proof_no", "file"],
}


def _doc_write_mapping(workspace: Path | None, project: str,
                       rows: Sequence[Mapping[str, Any]]) -> Any:
    """`doc.write_mapping`：把对应表交给 `papermapping.write_package`（唯一写口）。

    三份产物（`MAPPING.json` / `MAPPING.md` / `mapping-appendix.tex`，外加正文里那一行
    `\\input`）全部由 `write_package` 从同一批行渲染 —— 这一层不自己拼任何一段文本。
    手抄 md 或附录就是第二份渲染口径，而判据要的是"与渲染器逐字相同"
    （`md_drifted` / `mapping_paper_mismatch`）。

    行的形状也走读侧同一份判据（`papermapping.parse_rows`）：坏行逐条带回、一行都不写。
    半张表比没有表更坏 —— 它会让人以为"表交过了"。
    """
    root = _paper_root(workspace, project)
    if not isinstance(root, Path):
        return root
    payload = {"rows": [dict(r) for r in (rows or [])]}
    parsed, problems = PM.parse_rows(payload)
    if problems:
        return fail(f"对应表有 {len(problems)} 处读不懂 ⇒ 没有写盘（逐条见 problems）",
                    kind="mapping_unresolvable", written=False, problems=problems)
    if not parsed:
        return fail("对应表是空的 ⇒ 没有写盘（正文里每个定理类环境都该有一行）",
                    kind="mapping_empty", written=False)
    try:
        json_path, md_path, frag = PM.write_package(root, parsed)
    except OSError as exc:
        return fail(f"写论文包失败：{type(exc).__name__}: {exc}",
                    kind="io_error", written=False)
    # 写完立刻按读侧那份判据读一遍：三份在不在、与正文对不对得上，都由它回答
    # （工具这一层不另立一套"写成功了"的说辞）。
    reading = PM.mapping_reading(root, workspace_root=workspace)
    state = str(reading.get("state") or "")
    body = {
        "project": str(root), "json": str(json_path), "md": str(md_path),
        "appendix": str(frag), "rows": len(parsed), "state": state,
        "md_state": str(reading.get("md_state") or ""),
        "appendix_state": str(reading.get("appendix_state") or ""),
        # Lean 那两格的读数（业主 2026-10-22 追加）：`lean_state` 把"没开 Lean"与
        # "开关开着却没有产物"分成两档，`warnings` 里是只进读数、不拦门的那一档。
        "lean_state": str(reading.get("lean_state") or ""),
        "lean": dict(reading.get("lean") or {}),
        "warnings": list(reading.get("warnings") or []),
        "problems": list(reading.get("problems") or []),
        "reason": str(reading.get("reason") or ""),
    }
    if state != "pass":
        return fail(f"三份写出了，但这张表现在读不过（{state}）：{body['reason']}",
                    kind="mapping_not_clean", written=True, **body)
    return ok({
        "project": body["project"], "json": body["json"], "md": body["md"],
        "appendix": body["appendix"], "rows": body["rows"],
        "state": body["state"], "md_state": body["md_state"],
        "appendix_state": body["appendix_state"],
        "lean_state": body["lean_state"], "lean": body["lean"],
        "warnings": body["warnings"],
        "problems": body["problems"], "reason": body["reason"],
    })


def _register_paper_tools(registry: ToolRegistry, *, workspace: Path | None) -> None:
    """把论文这一层的两条工具注册进 G 的工具面。

    一条工具、一件事：`doc.paper_compile`。它 `declared_external="exec"` 是刻意的 ——
    它真的起 LaTeX 引擎（`pdflatex` / `xelatex` / `lualatex` 取第一个在 PATH 上的），
    所以执行面必须如实声明；声明成 `none` 等于说"这条工具不执行任何东西"。

    `doc.write_mapping` 是"先有对应表，再写正文"那条顺序的写入口（业主 2026-10-22）：
    `papermapping` 的三份产物此前没有任何调用方，而判据要求 md 与附录与渲染器逐字相同
    ⇒ 手抄不可达。它只写 `out/paper/` 下的三份（`write_local`），不起子进程。
    """
    registry.register(
        ToolSpec(
            name="doc.paper_compile",
            summary="把 <项目根>/out/paper/main.tex 编成 out/paper/main.pdf 并写编译回执。正文由你自己写（fs.write 到那个落点）"
            "—— 这一条只做编译。引擎写完 PDF 却异常退出时，产物与退出码分两栏带回。",
            params={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "minLength": 1, "maxLength": 300},
                    "timeout_sec": {"type": "number", "minimum": 1, "maximum": 7200},
                },
                "required": ["project"],
                "additionalProperties": False,
            },
            handler=lambda project, timeout_sec=1800.0: _paper_compile(
                workspace, project, timeout_sec),
            side_effect="write_local",
            declared_external="exec",
            roles=("G",),
            returns=(
                "{'tri','ok','reason','tex','pdf','engine','exit_codes','runs','pages',"
                "'pdf_bytes','receipt_path','pdf_fresh','engine_stderr_tail',"
                "'engine_stdout_tail','problems'}；"
                "tri ∈ not_applicable（还没有 main.tex，先写正文）/ unknown（没引擎、超时、"
                "这一次没编出 PDF —— `pdf_fresh=false` 就是「盘上那份是上一次编的」那一档）/ "
                "computed（**这一趟**拿到 PDF —— 页数与退出码如实带上，两栏不互相冒充）；"
                "`engine_stdout_tail` / `engine_stderr_tail` 是引擎自己说的话（截尾）—— "
                "编不过时先读它，别只看退出码；"
                "失败：ok=False + kind=paper_no_source（还没写正文）/ "
                "paper_compile_failed（编译没成）"
            ),
            tags=("document", "paper", "exec"),
        )
    )
    registry.register(
        ToolSpec(
            name="doc.write_mapping",
            summary="写论文对应表三份（out/paper/MAPPING.json + MAPPING.md + mapping-appendix.tex，"
            "并把 \\input 一行放进正文）。先写表、再写正文、最后 paper_compile；"
            "md 与附录由 json 渲染，别手写。有 Lean 产出时每行还要写 lean_file 与 "
            "lean_target（验它的源码在哪、验的是哪个声明）。数值实验定理那一行的证明栏"
            "写程序的相对路径（相对仓库根），另写 numeric_evidence（E 的 exp 读数）与 "
            "exhaustion_note（E 那两块读数落在哪）—— 缺任何一块都会拒。",
            params={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "minLength": 1, "maxLength": 300},
                    "rows": {"type": "array", "minItems": 1,
                             "description": "对应表的行：正文里每个定理/引理/命题/推论/例子/实验"
                                            "各占一行；多证明时每条证明各占一行",
                             "items": _MAPPING_ROW_PARAMS},
                },
                "required": ["project", "rows"],
                "additionalProperties": False,
            },
            handler=lambda project, rows: _doc_write_mapping(workspace, project, rows),
            side_effect="write_local",
            roles=("G",),
            returns=(
                "{'project','json','md','appendix','rows','state','md_state',"
                "'appendix_state','lean_state','lean','warnings','problems','reason'}；"
                "state ∈ pass（三份与正文逐一对上）/ fail（写出了，但逐条 problems）/"
                "unknown（没有正文，表没有可对的东西）；"
                "numeric_evidence / exhaustion_note 是数值实验定理那一行的条件必填："
                "缺程序路径 / 缺 E 的读数编号 / 缺两块读数 / 正文那一段指不回 E，都会进 "
                "problems 并让 state 落到 fail（工具随之 ok=False）；"
                "lean_state ∈ off（没开 Lean，`lean_file` / `lean_target` 允许为空）/ "
                "on（开关开着且有 Lean 产物 ⇒ 定理类那几行必须写两格）/ "
                "on_no_artifact（开关开着而一个 Lean 产物都没有，见 warnings）；"
                "json / md / appendix 是三个落点的绝对路径；"
                "失败：ok=False + kind=mapping_unresolvable（行读不懂，一行都没写）/ "
                "mapping_empty（给了一张空表）/ mapping_not_clean（写了，但现读判不过）/ "
                "io_error（写盘失败）/ bad_project（项目根不在工作区里）"
            ),
            tags=("document", "paper", "write"),
        )
    )
