"""G 的工具：**论文撰写**。

## 这一层唯一的核心规矩

**没有引用的断言不允许进入稿件。**

这不是文风要求，而是本领域可信度的技术基础：数学断言的价值完全取决于
"它来自哪里"。一旦允许无引用的断言，稿件就退化成一个**听起来很合理**的
文本 —— 而"听起来合理"与"有证据"之间的差距，正是幻觉最容易藏身的地方。

因此本模块把三条约束做成了**可机械判定的检查**（`scan_claim`），
并由 `schema.Document.validate` 在写入时强制执行：

1. `citations` 非空（FC-02）；
2. `evidence_kind="cross_check"` 的断言必须自带 `disclaimer`
   （"数值交叉验证，不构成证明"）—— 这句话由结构强制，**不靠人记得写**（FC-22）；
3. 否定型断言必须给 `negation_kind`（FC-25，"未证明"≠"已证否"）。

## 本模块的入口

| 函数 | 作用 | 关键纪律 |
|---|---|---|
| `scan_claim` | 一条断言的机械检查（纯函数） | 唯一判据；G 与 H 共用同一份 |
| `compose_claim` | **构造**一条合规断言 | `cross_check` 自动补 disclaimer；否定型未分类、无引用、过度声称 ⇒ **构造时抛** |
| `build_document` | 落库 + 渲染 markdown | 先逐条 `scan_claim`，再写库 ⇒ 报错能指出"哪一句话" |
| `register_dependency` | 登记外部依赖（FC-23 第一道闸） | `closed` 必须**用真实数据**核到已入库来源 |
| `render_markdown` | 人可读渲染（FC-10 / FC-22 / FC-23 / FC-25 的呈现层） | 三分档计数、否定分类、依赖表都必须出现 |
| `list_documents` | 只读列举 | 供 H / F / D 消费 |

## 为什么"在构造时就抛"比"写库时才抛"重要

`schema.Document.validate` 已经拦得住无引用断言，但它的报错形如
"claims[3] 没有 citations" —— 读者得自己回去数"第 3 条到底是哪句话"，
而**构造现场**（手里正拿着那句话、那段引用）才是信息最全的地方。
写库时的 schema 是最后一道闸，不是唯一一道。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .. import schema as S
from .. import textutil as T
from .base import ToolRegistry, ToolSpec, fail, ok

#: G 写稿；H 审稿（因此需要同一套判定函数 —— **审校者与撰写者必须用同一套判据**，
#: 否则会出现"G 认为合规、H 认为违规"的静默分裂，而双方都不算错）；
#: F/D 需要读稿件的开问题清单。
_ROLES = ("G", "H", "F", "D")

#: **只有 G 能写稿**。H 是审校（角色面必须全只读），F/D 是消费者。
#: 把写工具的角色收窄到 ("G",) 而不是沿用 _ROLES：一旦 H 手里有
#: `doc.build_document`，"发现问题的人"与"改写稿件的人"就变成了同一个，
#: 于是"发现问题"与"掩盖问题"在结构上无法区分。
_WRITER_ROLES = ("G",)

#: `cross_check` 类断言必须自带的声明。写成常量而不是各处手打，
#: 是为了让 H 能**精确匹配**它 —— 若允许多种写法，审校就只能靠语义判断，
#: 而"靠语义判断"正是我们要避免的东西。
CROSS_CHECK_DISCLAIMER = "数值交叉验证，不构成证明"

#: 视为"过度声称"的措辞。`evidence_kind != "proof"` 的断言里出现这些词即报。
#: 这份清单**必须显式列出**：隐含的判据无法被审阅、无法被反驳。
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

#: FC-25 的四类否定。**四类必须分开列**：
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

    为什么不用自增序号：`compose_claim` 是**纯函数**，它不知道自己在稿件里排第几；
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


def _resolve_out_path(
    root: Path, out_path: Any, doc_id: str, default_subdir: str
) -> tuple[str, Path]:
    """把 out_path 解析成工作区内的绝对路径，并返回 (相对路径, 绝对路径)。

    **越界一律拒绝**（而不是"写到外面再警告"）：工作区边界是沙箱契约的一部分，
    允许一次越界写就等于承认这个边界可以被绕开。用 `resolve()` 之后再
    `relative_to()` 判断，而不是靠字符串 `..` 检查 —— 后者会被符号链接绕过。
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
    """对**一条**断言做可判定的机械检查。纯函数，不碰存储。

    返回 ``{"ok": bool, "findings": [{kind, level, message}], "checked": True}``。

    `findings` 里的 `kind` 与 :data:`abflow.schema.FINDING_KINDS` 同词表 ——
    这样 H 的审校发现与 G 的自检发现是**同一批类型**，可以互相印证，
    而不会出现"G 自查用一套名字、H 审查用另一套"的分裂。

    ⚠️ 本函数只做**能判定**的检查。它不判断"这个数学论证对不对" ——
    那是形式的/人力的工作。把它不做的事说清楚，是它可被信任的前提。
    """
    findings: list[dict] = []
    cid = str(claim.get("claim_id") or "?")
    text = str(claim.get("text") or "")
    cites: Sequence[Any] = claim.get("citations") or []
    ek = claim.get("evidence_kind")

    if not text.strip():
        findings.append({"kind": "garbled", "level": "error", "message": f"断言 {cid} 的 text 为空"})

    # ---- 1. 无引用（FC-02）
    if not cites:
        findings.append(
            {
                "kind": "unsupported_claim",
                "level": "error",
                "message": f"断言 {cid} 没有任何 citations —— 无引用的断言不允许进入稿件",
            }
        )
    else:
        bad = [x for x in cites if not isinstance(x, str) or not x.strip()]
        if bad:
            findings.append(
                {
                    "kind": "garbled",
                    "level": "error",
                    "message": f"断言 {cid} 的 citations 含空/非字符串元素：{bad!r}",
                }
            )

    # ---- 2. 证据等级与过度声称（FC-22）
    if ek not in S.EVIDENCE_KINDS:
        findings.append(
            {
                "kind": "garbled",
                "level": "error",
                "message": f"断言 {cid} 的 evidence_kind={ek!r} 不在 {S.EVIDENCE_KINDS} 里",
            }
        )
    else:
        if ek == "cross_check" and not str(claim.get("disclaimer") or "").strip():
            findings.append(
                {
                    "kind": "overclaim",
                    "level": "error",
                    "message": (
                        f"断言 {cid} 的 evidence_kind='cross_check' 却没有 disclaimer。"
                        f"数值交叉验证必须显式写明「{CROSS_CHECK_DISCLAIMER}」"
                    ),
                }
            )
        if ek != "proof":
            hit = [m for m in OVERCLAIM_MARKERS if m in text]
            if hit:
                findings.append(
                    {
                        "kind": "overclaim",
                        "level": "error",
                        "message": (
                            f"断言 {cid} 的 evidence_kind={ek!r}（不是 proof），"
                            f"但正文出现「{'、'.join(hit)}」—— 这是把交叉验证说成了证明"
                        ),
                    }
                )

    # ---- 3. 否定分类（FC-25）
    is_neg = claim.get("is_negative") is True
    nk = claim.get("negation_kind")
    if is_neg and not nk:
        findings.append(
            {
                "kind": "missing_negation_kind",
                "level": "error",
                "message": (
                    f"断言 {cid} 是否定型断言却没有 negation_kind。"
                    "'未证明'与'已证否'在数学上是两件事，必须分开"
                ),
            }
        )
    if not is_neg and nk is not None:
        findings.append(
            {
                "kind": "missing_negation_kind",
                "level": "warning",
                "message": f"断言 {cid} 不是否定型却带了 negation_kind={nk!r}（会让否定计数虚高）",
            }
        )
    if nk is not None and nk not in S.NEGATION_KINDS:
        findings.append(
            {
                "kind": "missing_negation_kind",
                "level": "error",
                "message": f"断言 {cid} 的 negation_kind={nk!r} 不在 {S.NEGATION_KINDS} 里",
            }
        )

    errors = [f for f in findings if f["level"] == "error"]
    return {
        "checked": True,
        "claim_id": cid,
        "ok": not errors,
        "findings": findings,
        "error_count": len(errors),
        "warning_count": len(findings) - len(errors),
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
) -> dict:
    """构造一条**合规**的 claim dict。不合规就在**这里**抛 `ValueError`。

    ## 为什么把闸门放在构造函数里

    schema 也会拦（`Document.validate` 有同样的三条硬约束），但它的报错
    只能说到"claims[3] 没有 citations" —— 而在撰写现场，真正需要被指出来的是
    **"就是这一句话缺引用"**。等写库时才炸，会丢掉"哪一句话出的问题"这个信息，
    人还得回去数第 3 条是哪条。所以这里逐条检查并带上断言原文。

    ## 三条自动/强制的规则

    - `evidence_kind == "cross_check"` ⇒ **自动**填
      ``disclaimer = CROSS_CHECK_DISCLAIMER``。**不靠调用方记得写**：
      数值交叉验证不是证明，这句话必须由结构保证（FC-22）。
    - `is_negative=True` 且没给 `negation_kind` ⇒ 抛（**不静默填默认值**）。
      "未证明"、"已证否"、"没搜过"是三件不同的事，默认值等于替作者做了
      一个他可能不同意的数学判断。
    - `citations` 为空 ⇒ 抛。无引用的断言在结构上不允许存在（FC-02）。
    - 正文含 `OVERCLAIM_MARKERS` 而 `evidence_kind != "proof"` ⇒ 抛。
      把交叉验证说成"已证明"，是本领域最自然也最危险的过度声称。

    `claim_id` 可省略：此时按内容派生一个稳定代号（同样的内容得到同样的代号）。
    `build_document` 落库时会按顺序补成 `claim-1…claim-N`。
    """
    cites = [str(c) for c in (citations or [])]
    if not cites:
        raise ValueError(
            f"断言「{_one_line(text, 60) or '（空）'}」没有任何 citations："
            "**没有引用的断言不允许进入稿件**（FC-02）——数学断言的价值完全取决于它来自哪里"
        )
    bad = [c for c in cites if not c.strip()]
    if bad:
        raise ValueError(f"citations 含空元素：{bad!r}（空引用等于没有引用）")
    if evidence_kind not in S.EVIDENCE_KINDS:
        raise ValueError(f"evidence_kind 必须是 {S.EVIDENCE_KINDS} 之一，收到 {evidence_kind!r}")
    if not str(text or "").strip():
        raise ValueError("text 不能为空")

    if is_negative is True:
        if not negation_kind:
            raise ValueError(
                f"断言「{_one_line(text, 60)}」标了 is_negative=True 却没有 negation_kind。"
                f"必须是 {S.NEGATION_KINDS} 之一：'未证明'、'已证否'、'没搜过'、"
                "'搜了但没有本地证据'是三件（四件）不同的事，"
                "**不替调用方填默认值** —— 那等于替他做了一个数学判断"
            )
        if negation_kind not in S.NEGATION_KINDS:
            raise ValueError(f"negation_kind 必须是 {S.NEGATION_KINDS} 之一，收到 {negation_kind!r}")
    elif negation_kind is not None:
        raise ValueError(
            f"断言「{_one_line(text, 60)}」不是否定型（is_negative=False）却带了 "
            f"negation_kind={negation_kind!r}：会让'否定型结论'的计数虚高"
        )

    if evidence_kind != "proof":
        hit = [m for m in OVERCLAIM_MARKERS if m in str(text)]
        if hit:
            raise ValueError(
                f"断言「{_one_line(text, 60)}」的 evidence_kind={evidence_kind!r}（不是 proof），"
                f"正文却出现「{'、'.join(hit)}」：这是把交叉验证说成了证明。"
                "要主张已证明，必须走 evidence_kind='proof'（其来源只能是 method='formal' 的实验）"
            )

    claim = {
        "claim_id": str(claim_id).strip() if claim_id else _claim_id_of(text, cites),
        "section": str(section or ""),
        "text": str(text),
        "evidence_kind": evidence_kind,
        "citations": cites,
        "is_negative": is_negative is True,
        "negation_kind": negation_kind,
        #: cross_check 的"不构成证明"声明由**结构**强制，不靠人记得写（FC-22）。
        "disclaimer": CROSS_CHECK_DISCLAIMER if evidence_kind == "cross_check" else "",
    }
    # 自检一次：构造函数若产出了自己都过不了的断言，那是本函数的 bug，不是调用方的。
    check = scan_claim(claim)
    if check["error_count"]:
        raise AssertionError(
            "compose_claim 产出了不合规断言（本函数的 bug）："
            + "；".join(f["message"] for f in check["findings"] if f["level"] == "error")
        )
    return claim


# ---------------------------------------------------------------- 渲染


def render_markdown(
    doc: Mapping[str, Any],
    *,
    dependencies: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """把稿件渲染成人可读的 markdown（中文、表格优先、每条断言带代号）。

    风格沿用 `agent_d.write_report`：中文、表格优先、每条结论带代号。

    渲染层**强制**包含四张表（不是排版选择，是 FC 的呈现要求）：

    ====================================  ==========================================
    表                                     对应约束
    ====================================  ==========================================
    证据等级统计（proof / cross_check /      FC-10：三档分开计数，禁止单一通过率
    heuristic）
    否定型结论分类（未证明/已证否/未搜索）   FC-25：四种否定分开计数
    依赖表（带 external_unavailable 标注）  FC-23：引用的外部结论必须显式可见
    断言清单（每条带 citations）            FC-02：每条断言都能回答"我引用谁"
    ====================================  ==========================================

    三态纪律：`dependencies=None` 表示**调用方没给依赖清单**（没查），
    此时表里写"未提供"，而不是写"0 条" —— "没查"和"查了、没有"必须能分开。
    """
    claims = [c for c in (doc.get("claims") or []) if isinstance(c, Mapping)]
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
    lines.append(f"- 断言数：{len(claims)}；依赖数：{len(deps) if deps_checked else '未提供（没查）'}")
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
            lines.append(str(c.get("text") or ""))
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

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 落库


def normalize_claims(claims: Sequence[Mapping[str, Any]]) -> list[dict]:
    """补齐/规范化断言，并用 `scan_claim` 逐条把关。有任何 error 级发现即抛。

    ⚠️ 这里刻意**不自动补 disclaimer**（虽然 `compose_claim` 会补）：
    构造函数负责"帮作者构造出合规的断言"，落库闸门负责"拒绝不合规的断言"。
    让闸门顺手把违规项改好，会让"调用方漏写了声明"这件事**从此不可见** ——
    那正是本框架最忌讳的静默修复。
    """
    if not claims:
        raise ValueError("claims 不能为空 —— 一份没有任何断言的稿件不是稿件")
    out: list[dict] = []
    seen: set[str] = set()
    for i, c in enumerate(claims, 1):
        if not isinstance(c, Mapping):
            raise ValueError(f"claims[{i}] 必须是对象，收到 {type(c).__name__}")
        row = dict(c)
        cid = str(row.get("claim_id") or "").strip() or f"claim-{i}"
        row["claim_id"] = cid
        row["section"] = str(row.get("section") or "")
        row["is_negative"] = row.get("is_negative") is True
        row.setdefault("negation_kind", None)
        row["text"] = str(row.get("text") or "")
        row["citations"] = [str(x) for x in (row.get("citations") or [])]
        if cid in seen:
            raise ValueError(f"claims 出现重复 claim_id：{cid}（重复代号会让审校无法定位）")
        seen.add(cid)
        check = scan_claim(row)
        if check["error_count"]:
            detail = "；".join(f["message"] for f in check["findings"] if f["level"] == "error")
            raise ValueError(
                f"claims[{i}]（{cid}）未通过机械检查：{detail}。"
                f"断言原文：「{_one_line(row['text'], 80)}」"
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

    顺序刻意如此：**先逐条机械检查 → 再分配 ID → 再渲染 → 最后提交**。
    这样任何一条不合规的断言都不会换来一个"半成品稿件 + 一个已经烧掉的 doc_id"。

    为什么 markdown 在工作区内渲染（而不是返回字符串了事）：`markdown_path` 是
    FC-02 追溯链的一环 —— 稿件必须有一个**可被人打开**的落点，
    否则"H 审的是哪个版本"就无法回答。
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
    with store.tx("documents", actor=actor, note="build_document") as tx:
        doc_id = tx.alloc_id("doc")
        rel, absolute = _resolve_out_path(root, out_path, doc_id, default_subdir)
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
            created_at=S.now_iso(),
            updated_at=S.now_iso(),
            created_by=actor,
        )
        # 显式校验一次，让错误在**写入前**带着"哪一句话"抛出，而不是等到提交阶段
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
    """登记一条**外部依赖**（FC-23）。返回落库后的行 dict。

    ## 为什么"closed 必须指向已入库来源"要在**这里**再核一遍

    `schema.Dependency.validate` 只能检查"`status='closed'` 时字段非空" ——
    它看不见 `literature` / `experiments` 表，因此**一个不存在的 lit_id 也能通过 schema**。
    而"这个 lit_id 真的存在"正是"依赖闭合"的全部含义。
    所以第一道闸必须在 G 手里用真实数据核：**字段非空 ≠ 来源存在**。

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
    """把"业务失败"变成结构化结果，把"调用方写错了"与"环境故障"分开报。"""
    try:
        return ok(fn())
    except ValueError as e:
        return fail(f"校验失败：{e}", kind="validation_error")
    except OSError as e:
        return fail(f"文件操作失败：{type(e).__name__}: {e}", kind="io_error")


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
    工具**照样注册**，但一调用就返回 `ok=False, kind="not_wired"` ——
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

    registry.register(
        ToolSpec(
            name="doc.scan_claim",
            summary="对一条断言做机械检查：有无引用、证据等级是否被夸大、否定是否分类",
            params={
                "type": "object",
                "properties": {"claim": {"type": "object"}},
                "required": ["claim"],
                "additionalProperties": False,
            },
            handler=lambda claim: ok(scan_claim(claim)),
            side_effect="none",
            roles=_ROLES,
            returns="{'checked','claim_id','ok','findings','error_count','warning_count'}",
            tags=("document", "gate"),
        )
    )

    registry.register(
        ToolSpec(
            name="doc.compose_claim",
            summary=(
                "构造一条合规断言：cross_check 自动补「不构成证明」声明；无引用/否定未分类/过度声称"
                "在构造时就抛错（不等写库）"
            ),
            params={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "evidence_kind": {"type": "string", "enum": list(S.EVIDENCE_KINDS)},
                    "section": {"type": "string"},
                    "is_negative": {"type": "boolean"},
                    "negation_kind": {"type": "string", "enum": list(S.NEGATION_KINDS)},
                    "claim_id": {"type": "string"},
                },
                "required": ["text", "citations", "evidence_kind", "section"],
                "additionalProperties": False,
            },
            handler=lambda **kw: guard_result(lambda: compose_claim(**kw)),
            side_effect="none",
            roles=_ROLES,
            returns="合规的 claim dict（含 claim_id / disclaimer）",
            tags=("document", "compose"),
        )
    )

    registry.register(
        ToolSpec(
            name="doc.list_documents",
            summary="只读列举稿件（代号/类型/标题/状态/审校轮次/断言数与 markdown 路径）",
            params={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(S.DOC_STATUSES)},
                    "kind": {"type": "string", "enum": list(S.DOC_KINDS)},
                },
                "additionalProperties": False,
            },
            handler=lambda status=None, kind=None: (
                _not_wired() if store is None else guard_result(lambda: list_documents(store, status=status, kind=kind))
            ),
            side_effect="read",
            roles=_ROLES,
            returns="{'count','documents':[{'doc_id','kind','title','status','review_rounds','claim_count','markdown_path'}]}",
            tags=("document", "read"),
        )
    )

    registry.register(
        ToolSpec(
            name="doc.build_document",
            summary=(
                "写一行 documents 并渲染 markdown 到工作区内（逐条机械检查后再落库；"
                "out_path 越界即拒绝）"
            ),
            params={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(S.DOC_KINDS)},
                    "title": {"type": "string"},
                    "claims": {"type": "array", "items": {"type": "object"}, "minItems": 1},
                    "sections": {"type": "array", "items": {"type": "object"}},
                    "open_problems": {"type": "array", "items": {"type": "string"}},
                    "out_path": {"type": "string"},
                },
                "required": ["kind", "title", "claims"],
                "additionalProperties": False,
            },
            handler=lambda kind=None, title=None, claims=None, sections=None, open_problems=None, out_path=None: (
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
            ),
            side_effect="write_local",
            roles=_WRITER_ROLES,
            returns="落库后的 documents 行（含 doc_id / markdown_path）",
            tags=("document", "write"),
        )
    )

    registry.register(
        ToolSpec(
            name="doc.register_dependency",
            summary=(
                "登记外部依赖（FC-23）：status='closed' 会先用真实数据核 lit_id/experiment_id 是否已入库；"
                "dangling / external_unavailable 必须写 status_reason"
            ),
            params={
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
            handler=lambda **kw: (
                _not_wired()
                if store is None
                else guard_result(lambda: register_dependency(store, actor=actor, **kw))
            ),
            side_effect="write_local",
            roles=_WRITER_ROLES,
            returns="落库后的 dependencies 行（含 dep_id / status）",
            tags=("document", "dependency", "write"),
        )
    )
