"""H 的工具：审校。

## 这个模块存在的最重要理由

审校者的判断也需要证据。

这是本项目上一阶段最刺痛的一条教训：评审方提出的一条「缺陷」
（「medium 置信度泄漏进了正文」）是错的，是实现方拿证据顶回来才纠正的。
如果审校记录可以只写「这里有问题」而不给依据，审校就会变成
另一种幻觉的来源 —— 而且因为审校者站在更高的位置，它更难被纠正。

因此：

1. `schema.ReviewFinding.evidence` 必填非空（写入时硬约束）；
2. 本模块的每个检查都给出 `evidence` 字段，内容是触发该发现的实际值
   （例如 `citations=[]`、`evidence_kind='cross_check' 且 disclaimer 为空`），
   而不是一句「看起来不对」；
3. H 只读：它提发现，不改稿。改稿由 G 做。这不是分工洁癖 ——
   若审校者能直接改，它就同时是「发现者」与「修正者」，
   于是「发现问题」与「掩盖问题」在结构上无法区分。

## 「H 只读」在本模块里的落地形态（两条，缺一不可）

- 默认注册面只读：`register()` 只注册 `review.scan_document`（`none`）
  与 `review.list_findings`（`read`）。会写盘的两个入口
  （`review.review_document` / `review.verify_fixes`，均为 `write_local`）
  必须显式 `include_writers=True` 才会被装配 —— 于是「H 的工具面」
  （默认装配结果）在结构上不含任何写工具。
- 它们是 H 的代理步骤，不是 H 的刀：这两个写工具的落点被钉死在
  `review_findings`（新增/改状态）与 `documents.status` 上，
  一个字都不改 `claims` / `knowledge tables`。改稿这件事在 H 侧根本没有入口。

## 判据只有一份（已修，历史见下）

`scan_document` 与 G 侧的 `doc_tools.scan_claim` 同词表（`schema.FINDING_KINDS`），
逐条检查项必须一致：引用是否为空、`evidence_kind` 是否合法、
`cross_check` 是否缺 disclaimer、正文是否过度声称、否定型断言的 `negation_kind`
是否合法/是否该有。

这里曾经是假的：本模块 docstring 声称"不另写一套检查"，而
`scan_document` 把 `scan_claim` 的检查复制了一份且已经漂移 ——
H 侧当时不检查非法 `evidence_kind`、不检查 `negation_kind` 是否在受控词表里、
也不检查"非否定断言却带了 negation_kind"。漂移的后果不是崩溃，而是
"G 认为合规、H 认为通过"这种没有任何报错的静默分裂。
现在这三条已在 `scan_document` 里补齐（与 `scan_claim` 同等级、同判据）。

本轮把根因也去掉了：字段级判据现在归 `claimanatomy`（`CLAIM_FIELDS` 是
唯一声明表），`doc_tools.scan_claim` 只是它的适配层。`scan_document` 仍保留
自己的循环，但它必须产出同一批 finding kind（`schema.FINDING_KINDS`），
且不许比 G 侧轻 —— 这一约束由 `tests/test_tools_audit_fixes.py` 的
双向对照用例钉住，由 `tests/test_gates.py` 的 G10/G14 用例补充。
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .. import claimanatomy as CA
from .. import gates as G
from .. import schema as S
from .base import ToolRegistry, ToolSpec, fail, ok, tool
from .doc_tools import OVERCLAIM_MARKERS, dependencies_for_doc, guard_result as _guard_result

#: H 审校；G 需要看到发现才能修订（看不到发现的 G 无法闭环）；
#: F/D 需要知道哪些结论还带着未闭合的发现。
_ROLES = ("H", "G", "F", "D")

#: 写盘入口的角色。刻意只挂 H：写发现是审校者的本职，而不是让作者替审校者记账。
_WRITER_ROLES = ("H",)

#: 默认值哨兵（沿用 `agent_d._UNSPECIFIED` 的用法）：
#: 不传 = 「自己去库里读依赖」；显式传 `None` = 「调用方没有依赖清单 ⇒ 没查」。
#: 「没查」与「查了、依赖都闭合」必须能分开（FC-01 三态纪律）。
_UNSPECIFIED: Any = object()

#: H 自己负责的 `claimanatomy` code（`scan_document` 的循环里已有对应检查）。
#:
#: 为什么需要这张"跳过表"而不是把所有 code 都交给 claimanatomy：
#: H 的发现带 `target` 与 `evidence`，措辞已被既有测试逐字钉住
#: （`test_agent_h.py` 的 `assert "citations" in f["evidence"]` 一类）。
#: 若让 claimanatomy 的码同时进入，同一条缺陷会被报两遍、且两遍的措辞不同 ——
#: 那不是"更严格"，那是让审校报告变成噪音。跳过表让两边的分工显式：
#: H 负责它原生就有的六组检查，claimanatomy 负责 H 原先根本没有的那些
#: （生命周期、降级规则、冻结/勘误、未声明字段）。
_H_OWN_CODES = frozenset(
    {
        "missing_field",       # 引用/否定分类缺失 —— H 的循环里各有一条
        "empty_required",      # citations 空 / disclaimer 缺失 —— H 的循环里各有一条
        "bad_enum",            # evidence_kind / negation_kind 非法 —— H 的循环里各有一条
        "bad_type",            # citations 含空元素 —— H 的循环里有一条
        "inconsistent_status", # 过度声称（措辞）—— H 的循环里有一条（旧 code）
        # `draft/39` §3.8 之后，过度声称与免责声明各自独立成 code（族 6 / 族 5）：
        # 它们仍然是 H 自己的循环里已经有的那两条检查 ⇒ 继续跳过，否则同一条缺陷报两遍
        # （措辞还不同 —— 那不是更严格，是让审校报告变成噪音）。
        "overclaim",
        "missing_disclaimer",
    }
)

#: `claimanatomy` 的 code 里，只有 H 才判的那些 → H 的 finding kind。
#: 不在表里的 code 落到 `garbled`（"表述无法解析"），并在 message 里带上 code，
#: 于是"哪条判据触发"永远可查。
_H_FINDING_KIND_OF_CA_CODE: dict[str, str] = {
    "undeclared_field": "scope_drift",
    "duplicate_claim_id": "inconsistent_number",
    "checker_error": "garbled",
    # `draft/39` §3.8 的两个新 code：H 自己没有这两条检查（一个查数值证据结构、
    # 一个查生命周期闭合）⇒ 它们要按语义落 kind，不能落 `garbled`。
    "incomplete_numeric_evidence": "unsupported_claim",
    "lifecycle_incomplete": "inconsistent_number",
}


# ---- `P-9` 候选 A 的四键 + 「最小修法」：产出侧的唯一声明表（`X-96.3-1`）
#
# 背景（`draft/28` §96.3 第 1 条，`temp/FIXG4.md` §9.1）：`gates.gate_g10` 只对
# `created_at >= schema.REVIEW_FINDING_FORMAT_SINCE`（2026-09-27）的发现要求四键齐，
# 而今天的真实产出方就是本模块 —— 本模块一个都不产，于是 G10 对每一条今天写出的
# 发现都只能报 `unknown`（"schema 里没有这四个字段"改判成"产出方还没补键"）。
# 四个字段本身已在 `schema.ReviewFinding` 里（禁 AI 区，2026-09-27 所有者裁定候选 A），
# 缺的只有产出侧，所以本文件的改动就是"补参 + 补 `scan_document` 的产出"。
#
# 两条纪律（写在 `schema.ReviewFinding` 的类 docstring 里，这里落地）：
#   1. 这四键不进去重键 —— `_dedup_key` 仍是 `(kind, target, message)`，一字未动。
#      把 `line`/`verbatim_quote` 塞进去会让稿件每改一个词就产生一批新发现，
#      并打断"标了 fixed 但其实还在"的重开逻辑。
#   2. 表里给出的取值全部非空。空值不是"更宽松"：G10 的六字段判据会把空值读成
#      "缺这一格" ⇒ 整批发现被打回（`fail`），比原来那句 `unknown` 更坏 ——
#      那等于把"产出方没给"报成"这一批不合格式"。
#
# 每条取值的判据（不是"看起来对"）：
#
# * `axis`（取值域 = `gates.AXES` = 数学/体例/工程/证据）—— 这条缺陷落在哪条轴上。
#   判据是"它判的是外部依据还是稿件自己的表述"：判外部依据的
#   （没有引用 / 引了拿不到的结论）走 `证据`（与 G2/G6/G7/G8 同轴）；判稿件自己
#   怎么写、字段合不合规、哪里自相矛盾的走 `体例`（与 G3/G4/G9/G13 同轴）。
# * `maths`（`yes`/`no`，取值域 = `schema.FINDING_MATHS_VALUES`）—— 同一把尺子的另
#   一半：这条发现要读断言本身（断言内容 / 它的证据等级 / 里面的数字 / 否定分类）
#   才能判 ⇒ `yes`；只判它的机械形态或登记簿（词表外的取值、未声明字段、
#   依赖登没登记原因）⇒ `no`。
# * `suggestion`（G10 六格里的"最小修法"，与历史键名 `minimal_fix` 同格）——
#   逐 kind 一句最小动作：它要能被执行，不是"请注意质量"。
_FOUR_GATE_KEYS_OF_KIND: dict[str, tuple[str, str, str]] = {
    # kind                    axis    maths  最小修法(suggestion)
    "unsupported_claim": ("证据", "yes",
                          "给这条断言补上出处（`citations` 非空），或把它降为 remark"),
    "overclaim": ("体例", "yes",
                  "把证明性措辞改成它实际的证据等级；`cross_check` 另需补 `disclaimer`"),
    "missing_negation_kind": ("体例", "yes",
                              "补 `negation_kind`，或把 `is_negative` 与它改成同一轴"),
    "inconsistent_number": ("体例", "yes",
                            "同一个 `claim_id` 只留一段正文（重复的那条改号或合并）"),
    "scope_drift": ("体例", "no",
                    "把这个字段写进 `claimanatomy.CLAIM_FIELDS`，或从断言里删掉它"),
    "garbled": ("体例", "no",
                "把这一格改回受控词表/合法类型的取值（是哪一格见本发现的 `message`）"),
    "dangling_dep": ("证据", "no",
                     "给这条依赖补 `status_reason`，或把它登记为 `external_unavailable`"),
}

#: 表外的 kind 的兜底档。为什么要有兜底而不是留空：留空会被 G10 读成"缺这一格"，
#: 于是"我们还没给这个 kind 登记最小修法"变成"这一批发现不合格式"。兜底档本身也
#: 是一条可执行的指令（去读 `message`），只是不假装知道逐条的修法。
#: 今天 `schema.FINDING_KINDS` 里没有走到这里的取值（`quote_mismatch` 是预留、
#: 无产出路径），所以它是反真空而不是常态。
_FOUR_GATE_KEYS_FALLBACK: tuple[str, str, str] = (
    "体例", "no", "按本发现 `message` 指出的那一格改正（这个 kind 还没登记逐条最小修法）"
)

# ---------------------------------------------------------------- 语义判据的接缝（`R-42`）
#
# `R-42`（`draft/28` §133）：P9 第 4 条的"结论强于引文"今天只有措辞级判据 ——
# `OVERCLAIM_MARKERS` 逐词匹配（上面那个循环）加"`cross_check` 缺 disclaimer"。
# 它能抓住"把交叉验证说成证明"，抓不住措辞干净但结论确实强于引文（引文给了 n=3 的
# 数值检查、断言写成一般性结论）。语义级要 LLM 或人 —— 而本框架默认零 LLM 调用。
#
# 所以这里给的不是"接一个模型"，而是一条接缝 + 一个显式的没查状态：
# 没接线时 `semantic_check["checked"] is False` 且理由逐字写明；
# 绝不允许把"没查"折成"没问题"（三态纪律，与 `dep_check` 逐条同形）。
#
# 为什么用既有的 `overclaim` 这个 kind 而不新造一个：`schema.FINDING_KINDS` 是受控词表，
# 新造一个取值要动 FC-27 的 `schema.py`，而这件事的语义就是"过度声称"的一种 ——
# 语义级判据是让同一个 kind 更锋利，不是发明新类别（`evidence` 里会写明来源是语义判据）。

#: 语义判据允许的三种判定。`unknown` 必须存在：模型答不上来与"我判过、没问题"
#: 是两件事，折平之后"判不了"会静默变成"通过"。
SEMANTIC_VERDICTS: tuple[str, ...] = ("consistent", "stronger_than_evidence", "unknown")

#: 接缝签名：`judge(claim, doc) -> Mapping | None`，返回
#: `{"verdict": <SEMANTIC_VERDICTS 之一>, "reason": str}`。返回 `None` 视作 `unknown`。
SemanticJudge = Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any] | None]

#: 没接线时那句理由（要能回答"是谁没接线、怎么接"）。
_SEMANTIC_NOT_WIRED_REASON = (
    "没接线：语义级判据（「结论是否强于引文」）需要 LLM 或人，本框架默认零 LLM 调用。"
    "接法：`scan_document(..., semantic_judge=<可调用>)`，签名见 `SemanticJudge`。"
    "⇒ 这一格的状态是**没查**，不是'查过、没问题' —— 措辞级判据仍然跑过（见 findings）"
)

#: `line` 这一格为什么是第三态（`None` + 自证理由），而不是一个数字。
#:
#: `P-9` 的口径逐字是"行号只有在版本冻结（G11）之后才有意义"（`docs/PROPOSALS.md:239-240`）。
#: 未冻结时记下的行号在改稿之后就是错的，而它看起来一样精确 —— `.noai-paths` 里
#: "理由里刻意不写行号"是与它同一条纪律的另一面。`scan_document` 是纯函数，只拿到
#: `documents` 那一行，没有任何行号来源；G11 的冻结结论也还没有接进 H 的产出方
#: （`draft/28` §96.3 第 2 条：`GateContext` 里 `findings` 与 `observed_hash` 不相绑）。
#: ⇒ 如实给 `None` + 这一句理由，而不是猜一个数字（猜出来的行号是一个发明出来的数字）。
_LINE_UNAVAILABLE_REASON = (
    "本次拿不到行号：审校是纯函数、只读 `documents` 那一行，没有行号来源；"
    "且 `P-9` 的口径是「行号只有在版本冻结（G11）之后才有意义」，"
    "而 G11 的冻结结论还没有接进本产出方（`draft/28` §96.3 第 2 条）"
)


def _verbatim_quote(seed: Any) -> str:
    """把触发这条发现的正文截成 ≤20 词的逐字引文（`X-96.3-1`）。

    两条口径都不在本文件另造：

    * 词数口径 = `gates._quote_word_count`（中文按字、英文按空白切词）。
      `schema.ReviewFinding.validate()` 读的也是它 —— 各写一份必然漂移，
      而漂移的表现是"写入期说 20 词、门说 21 词"。惰性引用私有名与
      `schema.py` 里那处 `from .gates import AXES, _quote_word_count` 同形。
    * 上限 = `draft/17` §8.4 的"≤20 词逐字引文"。

    截口用省略号标出：不重写、不概括 —— 引文一旦被改写就不再是"逐字"，
    而 G10 要的正是"你看到的那句话长什么样"。
    空种子返回空串（调用方保证非空；真为空说明这一行里连定位符都没有）。
    """
    text = " ".join(str(seed or "").split())
    if not text:
        return ""
    if G._quote_word_count(text) <= 20:
        return text
    keep: list[str] = []
    for ch in text:
        if G._quote_word_count("".join(keep) + ch) > 19:
            break
        keep.append(ch)
    return "".join(keep).rstrip() + "…"


def _finding(
    kind: str,
    *,
    level: str,
    target: str,
    evidence: str,
    message: str,
    quote: Any,
    line: int | None = None,
    line_reason: str = "",
) -> dict:
    """造一条 H 的发现：既有六格不变，另按声明表补齐 `P-9` 的四键 + 最小修法。

    这个构造函数存在的唯一理由是只有一处补齐逻辑（FC-03）：四键写在十几个
    `findings.append` 里，下一次改声明表就会漏掉其中几处，而漏掉的表现是
    G10 对部分发现报 `unknown` —— 比全缺更难发现。

    `quote` 是"这条发现指向的那段正文"（逐字取自本次输入；断言 → 它的正文，
    依赖 → 它的标签，拿不到就退到 `target` 一类逐字存在的定位符）。

    `line` / `line_reason`（`FINAL-R5-05`）：行号只有产出方拿得到带行号的正文时
    才给得出；`scan_document` 的输入是结构化的 `claims`/`dependencies`，
    正常没有正文，所以默认 `line=None` + 受控理由串。给了 `line` 时理由串留空。
    """
    axis, maths, suggestion = _FOUR_GATE_KEYS_OF_KIND.get(kind, _FOUR_GATE_KEYS_FALLBACK)
    return {
        "kind": kind,
        "level": level,
        "target": target,
        "evidence": evidence,
        "message": message,
        # ---- `P-9` 候选 A 的四键 + "最小修法"那一格（`X-96.3-1`）
        "axis": axis,
        "line": line,
        "line_unavailable_reason": "" if line is not None else (line_reason or _LINE_UNAVAILABLE_REASON),
        "verbatim_quote": _verbatim_quote(quote),
        "maths": maths,
        "suggestion": suggestion,
    }


def _line_of(text: str, needle: str) -> int | None:
    """在被审正文里找 `needle` 首次出现的 1 起行号；找不到（或没有正文）⇒ None。

    为什么要有它（`FINAL-R5-05`）：G10 在版本冻结时把 `行号(line)` 判成必填，
    而产出方此前结构上给不出行号 ⇒ 那一条判据在"先冻结再审校"的顺序下恒红。
    有了正文就现算：`needle` 逐字来自这份正文（引文/标签/registry 号），
    所以"找得到"这件事本身就是那个引文确实在正文里出现过的第二个证据。
    """
    body = text or ""
    if not body or not needle:
        return None
    pos = body.find(needle)
    if pos < 0:
        return None
    return body.count("\n", 0, pos) + 1


# ---------------------------------------------------------------- 纯函数判据


def scan_document(
    doc: Mapping[str, Any],
    *,
    dependencies: Sequence[Mapping[str, Any]] | None = None,
    semantic_judge: SemanticJudge | None = None,
) -> dict:
    """对一份稿件做全量机械审校。纯函数，不碰存储。

    检查项（每一项都可判定，且都给出 evidence）：

    - `unsupported_claim` —— 断言无引用；
    - `overclaim` —— `evidence_kind != "proof"` 却出现证明性措辞，或
      `cross_check` 缺 disclaimer；
    - `missing_negation_kind` —— 否定型断言未分类；
    - `dangling_dep` —— 该稿件登记的依赖里有 `dangling` / `external_unavailable` 的
      （这是 FC-23 的落地：引用了拿不到的定理，必须是一条可见的发现，而不是
      藏在引文角标里）；
    - `inconsistent_number` —— 同一份稿件里同一个 claim_key 出现互相矛盾的数字
      （当前版本只检查「同一 claim_id 重复出现且 text 不同」，这是可判定的那一层）。

    本函数不判断数学对不对。 它判的是「稿件有没有把自己说清楚」：
    有没有引用、证据等级有没有被夸大、依赖有没有闭合。把这两件事分清，
    是审校可被信任的前提 —— 一个声称「我检查了证明」的自动审校器是危险的。

    三态：`dependencies=None` ⇒ `dep_check.checked=False`（没查），
    与「查了、依赖都闭合」（`checked=True, findings=[]`）严格区分。
    `semantic_judge=None` ⇒ `semantic_check["checked"] is False`（没接线，同样是没查），
    与「判过、都说一致」严格区分（`R-42`：措辞级判据抓不住"措辞干净但结论强于引文"）。

    `verdict` 的受控词与分档顺序（必须与写入路径 `review_document` 完全一致）：

    | 条件 | verdict |
    |---|---|
    | 有 error 级发现 | `rejected` |
    | 无 error，但 `dep_check.checked is False` | `unverified`（不是 accepted） |
    | 无 error、依赖查过、有 warning | `accepted_with_warnings` |
    | 无 error、依赖查过、无 warning | `accepted` |

    为什么"没查依赖"要单独占一档：把它并进 `accepted` 会让"我们从未检查"
    伪装成"检查通过"；并进 `rejected` 又会把"没做"说成"做失败了"。
    """
    findings: list[dict] = []
    doc_id = str(doc.get("doc_id") or "?")
    claims = doc.get("claims") or []

    # ---- 覆盖率（`draft/31` P7 第 4 项：签名要带 `coverage{claims_total, claims_reviewed}`）
    #
    # 为什么要两个计数而不是一个布尔：`claims_reviewed` 是"逐条检查真的在这条上跑过"，
    # `claims_decided` 是"其中校验器判成了"（`validate_claim.checker_error` 那种
    # "检查器自己没跑成"必须与"跑过、没问题"分开）。只报一个比例会把两者折平 ——
    # 而"审了 100%"与"审的时候检查器崩了"是完全不同的两件事。
    #
    # 这一格只覆盖"稿件有没有把自己说清楚"（引用/证据等级/否定分类/字段合规），
    # 不覆盖"数学对不对" —— 后者的判据是 proof 级证据（FC-22），要另给。
    # 说清这一点是覆盖率可被信任的前提：一个声称"我审过全部断言"的自动审校器
    # 会被读成"数学被验过了"，那不是本函数做的事。
    claims_total = len(claims)
    reviewed = 0
    decided = 0
    seen_ids: dict[str, str] = {}
    for i, c in enumerate(claims):
        if not isinstance(c, Mapping):
            findings.append(
                _finding(
                    "garbled",
                    level="error",
                    target=f"claims[{i}]",
                    evidence=f"claims[{i}] 的类型是 {type(c).__name__}，不是对象",
                    message="断言必须是对象",
                    # 这一行连对象都不是 ⇒ 没有正文可引；引文退到这一行在稿件里的
                    # 定位符（它是这一格里唯一逐字存在的东西），不编一句话出来
                    quote=f"claims[{i}]",
                )
            )
            continue
        reviewed += 1
        cid = str(c.get("claim_id") or f"claims[{i}]")
        text = str(c.get("text") or "")
        cites = c.get("citations") or []
        ek = c.get("evidence_kind")

        # ---- 无引用
        if not cites:
            findings.append(
                _finding(
                    "unsupported_claim",
                    level="error",
                    target=cid,
                    evidence=f"claim_id={cid} 的 citations={cites!r}（空）",
                    message="断言没有引用：数学断言的价值取决于它来自哪里",
                    quote=text or cid,
                )
            )
        else:
            # 与 `doc_tools.scan_claim:205-214` 对齐：空元素/非字符串等于没有引用，
            # 但 `if not cites` 看不出来（[""] 是非空列表）。这条曾经只在 G 侧有。
            bad_cites = [x for x in cites if not isinstance(x, str) or not x.strip()]
            if bad_cites:
                findings.append(
                    _finding(
                        "garbled",
                        level="error",
                        target=cid,
                        evidence=f"claim_id={cid} 的 citations={cites!r} 含空/非字符串元素：{bad_cites!r}",
                        message="引用里有空元素：空引用等于没有引用",
                        quote=repr(cites),
                    )
                )
        # ---- 证据等级是否合法（与 `doc_tools.scan_claim:217-224` 对齐）
        #
        # 这一条曾经只有 G 侧有：H 遇到非法的 `evidence_kind` 时会因为
        # `ek in S.EVIDENCE_KINDS` 这个守卫而直接跳过下面两组检查，
        # 于是一条把 evidence_kind 写成 "prooof" 的断言在 H 眼里是干净的。
        if ek not in S.EVIDENCE_KINDS:
            findings.append(
                _finding(
                    "garbled",
                    level="error",
                    target=cid,
                    evidence=f"claim_id={cid} 的 evidence_kind={ek!r} 不在 {S.EVIDENCE_KINDS} 里",
                    message=f"证据等级必须是 {S.EVIDENCE_KINDS} 之一",
                    quote=repr(ek),
                )
            )
        # ---- 过度声称
        if ek == "cross_check" and not str(c.get("disclaimer") or "").strip():
            findings.append(
                _finding(
                    "overclaim",
                    level="error",
                    target=cid,
                    evidence=f"evidence_kind={ek!r} 且 disclaimer 为空",
                    message="数值交叉验证必须显式声明'不构成证明'",
                    quote=text or cid,
                )
            )
        if ek in S.EVIDENCE_KINDS and ek != "proof":
            hit = [m for m in OVERCLAIM_MARKERS if m in text]
            if hit:
                findings.append(
                    _finding(
                        "overclaim",
                        level="error",
                        target=cid,
                        evidence=f"evidence_kind={ek!r} 但正文含 {'、'.join(hit)}；正文摘要：{text[:80]!r}",
                        message="把交叉验证写成了证明",
                        # 触发的就是这几个词，它们逐字在正文里 ⇒ 引文直接用它们
                        # （与 `test_p910_p9_review_finding_format` 的正控夹具同形）
                        quote="、".join(hit),
                    )
                )
        # ---- 否定分类
        #
        # 证据里必须写出字段名与它的实际值：G 侧的同一条检查
        # （`claimanatomy` 的 2c 节）也把字段名写在 evidence 里，两边逐字对得上
        # 才可能被判据对照用例双向核对（`test_scan_document_checks_match_scan_claim_both_ways`）。
        if c.get("is_negative") is True and not c.get("negation_kind"):
            findings.append(
                _finding(
                    "missing_negation_kind",
                    level="error",
                    target=cid,
                    evidence=(
                        f"is_negative=True 且 negation_kind={c.get('negation_kind')!r}"
                        "（字段 `negation_kind` 缺失/为空）"
                    ),
                    message="'未证明'与'已证否'必须分开",
                    quote=text or cid,
                )
            )
        # ---- 与 G 侧判据对齐的两条
        #
        # "非否定断言却带了 negation_kind" 这条必须与 G 同级别（error）：
        # G 侧（`doc_tools.scan_claim` → `claimanatomy` 的 `bad_enum`）把它判成
        # `garbled/error`，而 H 侧此前判 `warning` —— 于是H 比 G 松：
        # G 拒绝的稿件在 H 那里照样通过（"G 认为违规、H 认为通过"的静默分裂，
        # 正是 INVENTORY 4.5#10 点名的那一类）。两边不一致时以更严的一侧为准：
        # 一条同时声称"不是否定型"又带否定分类的断言，它的否定计数一定是错的，
        # 那不是"提醒一下"就能放过的。
        if c.get("is_negative") is not True and c.get("negation_kind") is not None:
            findings.append(
                _finding(
                    "garbled",
                    level="error",
                    target=cid,
                    evidence=(
                        f"is_negative={c.get('is_negative')!r}（不是否定型）"
                        f"却带了 negation_kind={c.get('negation_kind')!r}"
                    ),
                    message="非否定型断言带了否定分类：两轴矛盾，否定计数必然虚高",
                    quote=repr(c.get("negation_kind")),
                )
            )
        if c.get("negation_kind") is not None and c.get("negation_kind") not in S.NEGATION_KINDS:
            findings.append(
                _finding(
                    "missing_negation_kind",
                    level="error",
                    target=cid,
                    evidence=(
                        f"claim_id={cid} 的 negation_kind={c.get('negation_kind')!r} "
                        f"不在 {S.NEGATION_KINDS} 里"
                    ),
                    message=f"否定分类必须是 {S.NEGATION_KINDS} 之一",
                    quote=repr(c.get("negation_kind")),
                )
            )
        # ---- 重复 claim_id 且文本不同（可判定的"自相矛盾"）
        if cid in seen_ids and seen_ids[cid] != text:
            findings.append(
                _finding(
                    "inconsistent_number",
                    level="error",
                    target=cid,
                    evidence=f"同一 claim_id={cid} 出现两次且 text 不同：{seen_ids[cid][:60]!r} vs {text[:60]!r}",
                    message="同一断言标识对应两段不同文字",
                    quote=text or cid,
                )
            )
        seen_ids[cid] = text

    # ---- 语义级判据（`R-42`）："结论强于引文"这一条措辞级判据看不见
    #
    # 上面那个循环用的是 `OVERCLAIM_MARKERS` 逐词匹配 —— 它只能抓"把交叉验证说成证明"
    # 这类写在脸上的形态。抓不住的是：措辞干净（没有 `证明`/`定理` 这类词），
    # 但结论的强度确实超过引文能支撑的范围（引文只做了 n=3 的数值检查，
    # 断言写成一般性结论）。那一层要读语义，只有 LLM 或人能判。
    #
    # 本框架默认零 LLM 调用 ⇒ 这里默认没查。三条纪律：
    #   ① 没接线时 `checked=False` + 逐字理由，不许折成"没问题"（与 `dep_check` 同形）；
    #   ② 判据答 `unknown` 也不算查过（`claims_unknown` 单独计数）——
    #      "模型答不上来"与"我判过、一致"是两件事；
    #   ③ 判据自己抛异常/返回不合法 ⇒ `checker_errors += 1` + 一条 warning 级 `garbled`
    #      （与 `claimanatomy` 的 `checker_error` 同一处置：检查器没跑成不是稿件的错，
    #      但绝不能静默）。
    #
    # 为什么语义级发现定 warning 而不是 error：措辞级那条是机械可判的（error 站得住），
    # 而语义判定来自一个可能犯错的判据 —— 判错一次就会把一份合格的稿件判成 `rejected`。
    # 定 warning 让它可见（verdict 落 `accepted_with_warnings`）而不越权。要不要升到
    # error 是口径问题，属 FC-27 的 `eval-criteria` 类 ⇒ 留给人裁，不在这里替人定。
    semantic_check: dict[str, Any] = {
        "checked": False,
        "judge": "",
        "reason": _SEMANTIC_NOT_WIRED_REASON,
        "claims_judged": 0,
        "claims_unknown": 0,
        "checker_errors": 0,
        "stronger_than_evidence": 0,
    }
    if semantic_judge is not None:
        semantic_check["checked"] = True
        semantic_check["judge"] = getattr(semantic_judge, "__name__", "") or type(semantic_judge).__name__
        reasons: list[str] = []
        for i, c in enumerate(claims):
            if not isinstance(c, Mapping):
                continue
            cid = str(c.get("claim_id") or f"claims[{i}]")
            try:
                got = semantic_judge(c, doc)
            except Exception as e:  # noqa: BLE001 - 判据自己没跑成，见上面第 ③ 条
                semantic_check["checker_errors"] += 1
                findings.append(
                    _finding(
                        "garbled", level="warning", target=cid,
                        evidence=f"语义判据在 claim_id={cid} 上抛了 {type(e).__name__}: {e}",
                        message="语义判据自己没跑成：这一条是**没查成**，不是'没问题'",
                        quote=str(c.get("text") or cid),
                    )
                )
                continue
            verdict_of = ""
            if got is None:
                verdict_of = "unknown"
            elif isinstance(got, Mapping):
                verdict_of = str(got.get("verdict") or "")
                reason_one = str(got.get("reason") or "")
                if reason_one:
                    reasons.append(f"{cid}: {reason_one}")
            if verdict_of not in SEMANTIC_VERDICTS:
                semantic_check["checker_errors"] += 1
                findings.append(
                    _finding(
                        "garbled", level="warning", target=cid,
                        evidence=f"语义判据返回 {got!r}（verdict={verdict_of!r} 不在 {SEMANTIC_VERDICTS} 里）",
                        message="语义判据的返回值不在受控词表里：这一条**没查成**",
                        quote=str(c.get("text") or cid),
                    )
                )
                continue
            if verdict_of == "unknown":
                semantic_check["claims_unknown"] += 1
                continue
            semantic_check["claims_judged"] += 1
            if verdict_of == "stronger_than_evidence":
                semantic_check["stronger_than_evidence"] += 1
                findings.append(
                    _finding(
                        "overclaim", level="warning", target=cid,
                        evidence=(
                            f"语义判据（{semantic_check['judge']}）判定结论强于引文："
                            f"claim_id={cid}，citations={list(c.get('citations') or [])}，"
                            f"理由={str((got or {}).get('reason') or '')[:160]!r}"
                        ),
                        message=(
                            "结论的强度超出引文能支撑的范围（措辞级判据看不见这一形态 —— "
                            "它没有出现证明性措辞）。处置：要么把结论减弱到引文支撑得住的范围，"
                            "要么补一条更强等级的引文（proof 级证据见 FC-22）。"
                            "本条定 warning 而不是 error：语义判定来自可能犯错的判据，"
                            "升级口径留给人裁"
                        ),
                        quote=str(c.get("text") or cid),
                    )
                )
        semantic_check["reason"] = (
            f"判过 {semantic_check['claims_judged']} 条、答不上来 {semantic_check['claims_unknown']} 条、"
            f"判据报错 {semantic_check['checker_errors']} 条、判定'结论强于引文' "
            f"{semantic_check['stronger_than_evidence']} 条"
            + ("；逐条理由：" + " ｜ ".join(reasons[:5]) if reasons else "")
        )

    # ---- 生命周期与降级（`claimanatomy` 的判据，H 侧此前完全没有）
    #
    # 这一段是本轮新增的能力：`status`（生命周期轴）与 `allowed_use`（降级规则）
    # 是 `draft/17` §8.3 的两个字段，本框架此前表达不了"这条断言已作废"。
    # 判据不在这里重写 —— 它来自 `claimanatomy.validate_claim`，
    # 本段只做"翻译成 H 的 finding 形状"。
    #
    # 去重规则（避免同一条缺陷报两遍、且两边级别不同）：
    # `_H_OWN_CODES` 列出的 code 由上面 H 自己的循环负责（它带 H 要的
    # `target`/`evidence` 措辞，且已有测试逐字钉住），这里跳过。
    for i, c in enumerate(claims):
        if not isinstance(c, Mapping):
            continue
        spec = CA.validate_claim(c)
        if spec.checked:
            decided += 1
        fallback_cid = str(c.get("claim_id") or f"claims[{i}]")
        for issue in spec.issues:
            if issue.code in _H_OWN_CODES:
                continue
            if issue.level == "info":
                # 三态第三态不进发现表：`unknown_status_axis`（"这条断言
                # 没有 `status` 字段 ⇒ 生命周期轴判不了"）是数据质量信息，
                # 不是一条要 G 去改的缺陷。把它塞进 `review_findings` 会让
                # "干净稿件 = 0 条发现"这条判据永远不成立 —— 而那条判据是
                # 防误伤的基线（`test_review_accepts_a_clean_document`）。
                # 它由 `claimanatomy.ClaimSpec.decided=False` + `undecided_reason`
                # 单独表达，并由 `gates` 的门（G9/G10）如实登记"判不了"。
                continue
            findings.append(
                _finding(
                    _H_FINDING_KIND_OF_CA_CODE.get(issue.code, "garbled"),
                    level=issue.level,
                    target=issue.claim_id if issue.claim_id not in ("", "?") else fallback_cid,
                    evidence=f"字段 `{issue.field_name}`：{issue.evidence}",
                    message=f"{issue.message}（判据出处：claimanatomy，code={issue.code}）",
                    quote=str(c.get("text") or "") or fallback_cid,
                )
            )

    # ---- 依赖闭合（FC-23）
    if dependencies is None:
        dep_check = {
            "checked": False,
            "reason": "调用方未提供 dependencies ⇒ **没查依赖闭合**（不得读成'依赖都闭合'）",
            "open": [],
        }
    else:
        open_deps = [
            {
                "dep_id": str(d.get("dep_id") or ""),
                "status": str(d.get("status") or ""),
                "label": str(d.get("label") or ""),
                "status_reason": str(d.get("status_reason") or ""),
            }
            for d in dependencies
            if str(d.get("status") or "") in ("dangling", "external_unavailable")
        ]
        for d in open_deps:
            # 分级（FC-13）：`external_unavailable` 是"我们已经知道并记录了这个前提
            # 拿不到" —— 那是已知边界，不是谎报，所以是 warning。
            # 而 `dangling` 是"登记了一个依赖却既没闭合、也没说明为什么拿不到" —— 那是
            # 没交代，属于 error。把两者都报成 error 会把红灯训练成噪音。
            lvl = "warning" if d["status"] == "external_unavailable" else "error"
            # `FINAL-R5-09`：`label` 与 `dep_id` 都为空的依赖不能再走 `dangling_dep` ——
            # 那时引文只能是空串，而 G10 把空 `verbatim_quote` 读成"缺 ≤20 词逐字引文"
            # 并把整批发现打回（fail）；这条依赖真正的问题是"对象本身不合法
            # （既没有标签也没有登记号）"，所以换一种发现 `garbled`，引文退到占位串
            # （它逐字就是被审那一行里的那个空字段）。
            has_anchor = bool(d["label"] or d["dep_id"])
            findings.append(
                _finding(
                    "dangling_dep" if has_anchor else "garbled",
                    level=lvl,
                    target=d["dep_id"] or d["label"] or "(空)",
                    evidence=(
                        f"dep_id={d['dep_id']} status={d['status']!r} label={d['label']!r}；"
                        f"status_reason={d['status_reason'][:120]!r}"
                    ),
                    message=(
                        "依赖项既没有 label 也没有 dep_id ⇒ 这条对象本身不合法"
                        if not has_anchor
                        else "引用了外部结论但本项目拿不到来源（已知边界，需人确认前提）"
                        if d["status"] == "external_unavailable"
                        else "依赖悬空且没有说明原因"
                    ),
                    # 引文取这条依赖在被审那一行里逐字存在的东西：标签优先（"引的是什么"），
                    # 退到 `dep_id`（登记号本身也是逐字的），再退到上面那个占位串。
                    quote=d["label"] or d["dep_id"] or "(空：既无 label 也无 dep_id)",
                )
            )
        dep_check = {"checked": True, "reason": f"检查了 {len(list(dependencies))} 条依赖", "open": open_deps}

    errors = [f for f in findings if f["level"] == "error"]
    warnings = [f for f in findings if f["level"] == "warning"]
    dep_checked = bool(dep_check.get("checked"))

    # ---- FC-10：三分档计数，禁止单一通过率。
    # "通过率 80%" 会掩盖"20% 是失败还是未检查"这个决定性差异。
    #
    # `verdict` 必须读 `dep_check["checked"]`（这是本函数曾经的真实缺陷）：
    # 只按 error/warning 分档时，`dependencies=None`（"调用方没给清单 ⇒ 没查"）
    # 会在同一个返回值里出现 `dep_check` 说"没查"、`verdict` 说"accepted" ——
    # 只看 `verdict` 或 `res.ok` 的调用方（AgentH、verify）就会把"依赖闭合从未检查"
    # 读成"稿件通过"。写入路径 `review_document` 从来不许这件事（见 `:429-438`），
    # 只读路径与它必须是同一口径 —— 否则审校的两个入口会对同一份稿件给出
    # 两个都"没有报错"的相反结论。
    #
    # 分档顺序：error 最重（有错就是 rejected，无论依赖查没查），
    # 其次"没查"（unverified —— 既不是通过也不是不通过），最后才是 warning/干净。
    if errors:
        verdict = "rejected"
    elif not dep_checked:
        verdict = "unverified"
    elif warnings:
        verdict = "accepted_with_warnings"
    else:
        verdict = "accepted"

    # `FINAL-R5-05`：有正文就把行号补上（G10 在版本冻结时把 `行号` 判成必填，
    # 而此前产出方在任何情形下都只给 `line=None` + 理由串 ⇒ 那条判据在
    # "先冻结再审校"的顺序下恒红）。逐条按引文在正文里定位：
    # 引文逐字来自这份正文，所以"找得到"本身就是它确实出现过的第二个证据。
    # 找不到（或调用方没给正文）⇒ 保持 `line=None` + 受控理由串，判据照旧判它。
    doc_text = str(doc.get("text") or doc.get("body") or doc.get("markdown") or "")
    lines_located = 0
    if doc_text:
        for f in findings:
            if f.get("line") is None:
                located = _line_of(doc_text, str(f.get("verbatim_quote") or ""))
                if located is not None:
                    f["line"] = located
                    f["line_unavailable_reason"] = ""
                    lines_located += 1

    coverage = {
        "claims_total": claims_total,
        "claims_reviewed": reviewed,
        "claims_decided": decided,
        # `R-42`：语义级判据真的判过几条。没接线时恒为 0 —— 它与 `claims_reviewed`
        # 并排出现，读者一眼能看出"机械检查跑了、语义检查没跑"，而不是把
        # `accepted` 读成"两层都查过"。
        "claims_semantically_judged": semantic_check["claims_judged"],
        "note": (
            "`claims_reviewed` = 逐条字段/引用/证据等级检查真的跑过的断言数；"
            "`claims_decided` = 其中校验器判成了的（判不了的另计）；"
            "`claims_semantically_judged` = 语义级判据（「结论是否强于引文」）真的判过的条数"
            "（没接线时为 0 = **没查**，不是'没问题'）。"
            "本覆盖率只覆盖「稿件有没有把自己说清楚」，不覆盖「数学对不对」——"
            "后者要 proof 级证据（FC-22），不由本函数给出。"
        ),
    }
    reason = (
        f"机械检查 error={len(errors)}、warning={len(warnings)}、info={len(findings) - len(errors) - len(warnings)}；"
        f"覆盖率 {reviewed}/{claims_total}（判成 {decided}）；"
        + (
            f"依赖闭合已检查（{dep_check.get('reason')}）"
            if dep_checked
            else f"依赖闭合**没查**（{dep_check.get('reason')}）⇒ 不能判 accepted"
        )
        + (
            f"；语义级判据已判 {semantic_check['claims_judged']} 条"
            if semantic_check["checked"]
            else "；语义级判据**没查**（未接线）—— 措辞级判据已跑，"
                 "但'措辞干净而结论强于引文'这一形态看不见"
        )
        + (f"；行号：按正文定位到 {lines_located} 条" if doc_text else "；行号：本次没有正文可定位")
    )
    return {
        "checked": True,
        "doc_id": doc_id,
        "findings": findings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(findings) - len(errors) - len(warnings),
        "dep_check": dep_check,
        # 语义级判据的三态（`R-42`）。与 `dep_check` 并排给：两个"没查"各自说清自己，
        # 合成一个"有些检查没做"就没人知道是哪一层没做、该怎么接。
        "semantic_check": semantic_check,
        "verdict": verdict,
        # 覆盖率与 verdict 必须一起给：`accepted` 只说"没查出问题"，
        # 说不出"这句话是在多少条断言上成立的"。
        "coverage": coverage,
        # `reason` 与 verdict 必须一起给：只给一个受控词，调用方看不出
        # "unverified" 到底是"没查依赖"还是"还缺别的输入"。
        "reason": reason,
    }


# ---------------------------------------------------------------- 内部工具


def _doc_of(store: Any, doc_id: str) -> dict:
    row = next((r for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)), None)
    if row is None:
        raise ValueError(f"稿件 {doc_id} 不存在（documents 表里没有这一行）⇒ 不能审一份不存在的稿件")
    return dict(row)


def _resolve_deps(store: Any, doc_id: str, dependencies: Any) -> tuple[Any, bool]:
    """把 `dependencies` 参数解析成 (传给 scan_document 的值, 是否查过)。

    哨兵 / 显式 None 的区别就是三态纪律本身：
    「我自己去库里读了」（查过）与「调用方没给清单」（没查）不能混。
    """
    if dependencies is _UNSPECIFIED:
        return dependencies_for_doc(store.rows("dependencies"), doc_id), True
    if dependencies is None:
        return None, False
    return [dict(d) for d in dependencies], True


def _set_doc_status(store: Any, doc_id: str, target: str, *, actor: str) -> tuple[bool, str | None, str]:
    """只改 `documents` 行的 `status` 字段。返回 (是否写成, 错误, 当前状态)。

    ## 为什么只改 status，连 `updated_at` 都不碰

    "H 只读"必须有一个可核对的形式：调用前后逐字节比对 `documents.json`，
    变化点应当有且只有 status。顺手更新 `updated_at` 看起来无害，
    但它会让"H 到底动了什么"从"一眼看清"退化成"要逐字段 diff 才知道"。

    ## 为什么这个写会失败（而且必须如实报告）

    `Document.validate` 会在提交时校验整张 documents 表。若盘上这份稿件
    本身不合 schema（例如是手工改坏的、或旧版本写的），那么连"把它的状态改成
    in_review"都写不进去。这不是可以掩盖的细节：发现照样落库，状态更新失败
    这件事本身也要出现在返回值里，否则调用方会以为"审校流程正常结束了"。
    """
    cur = next(
        (str(r.get("status")) for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)),
        "",
    )
    if cur == target:
        return True, None, cur
    try:
        with store.tx("documents", actor=actor, note=f"review status {cur}->{target}") as tx:
            row = tx.find("documents", doc_id=str(doc_id))
            if row is None:
                return False, f"稿件 {doc_id} 在事务内不存在", cur
            row["status"] = target
            tx.upsert("documents", row)
    except Exception as e:  # noqa: BLE001 - 见 docstring：失败必须被记录，不能被吞掉或上抛
        return False, f"{type(e).__name__}: {e}", cur
    return True, None, target


def _apply_finding_status(
    store: Any, changes: Sequence[Mapping[str, Any]], *, actor: str, note: str
) -> list[dict]:
    """批量改 finding 的 `status`（以及必要时补 `resolution_note`）。

    只允许改这两个字段：finding 的 `kind/level/target/evidence/message` 是
    H 当初的判断依据，重算时不许被改写 —— 否则"当初为什么这么判"就没有了。
    """
    done: list[dict] = []
    if not changes:
        return done
    with store.tx("review_findings", actor=actor, note=note) as tx:
        for ch in changes:
            row = tx.find("review_findings", finding_id=str(ch["finding_id"]))
            if row is None:
                continue
            if row.get("status") == ch["status"]:
                continue
            row["status"] = ch["status"]
            if ch.get("resolution_note"):
                row["resolution_note"] = str(ch["resolution_note"])
            tx.upsert("review_findings", row)
            done.append({"finding_id": row["finding_id"], "status": row["status"]})
    return done


def _dedup_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """去重键：`(kind, target, message)`（doc_id 在调用处限定）。"""
    return (str(row.get("kind")), str(row.get("target")), str(row.get("message")))


# ---------------------------------------------------------------- 审校（写发现）


def review_document(
    store: Any,
    doc_id: str,
    *,
    round_no: int | None = None,
    dependencies: Any = _UNSPECIFIED,
    actor: str = "agent-H",
    # 语义判据的接缝（`draft/28` §196）：默认 None = 没接线 ⇒ `semantic_check["checked"]`
    # 是 False 且理由逐字写明"没查"。接线由 `AgentH`（有 llm 时）与
    # `host.wired_llm_conductor(..., semantic_review=True)` 提供 ——
    # 默认路径一个 LLM 调用都不发。
    semantic_judge: Any = None,
) -> dict:
    """审一份稿件：把机械发现落成 `ReviewFinding` 行，并更新 `documents.status`。

    返回 ``{"doc_id","checked","round","new_findings","duplicate_skipped","reopened",
    "error_count","warning_count","info_count","dep_check","status","status_updated",
    "status_error","verdict","reason"}``。

    ## 三段式（为什么是三个事务而不是一个）

    1. 落发现（`review_findings`）：发现是审校的产出，必须落库 ——
       "发现了但没记下来"等于没发现。
    2. 重开谎报（`review_findings`）：G 把一条 finding 标成 `fixed` 之后，
       如果重跑检查仍然复现，这条 finding 会被重新打开。没有这一步，
       G 只要点一下"已修复"，审校就只看状态、成了盖章机。
    3. 改状态（`documents`，独立事务）：稿件可能本身不合 schema，
       于是这一步会失败。把它与落发现分开，失败时才不会连发现一起丢掉。

    ## 三态：`dependencies` 没查 ⇒ 不许判 accepted

    `dep_check.checked is False` 时 verdict 是 `"unverified"`，文档状态停在
    `in_review` —— 「依赖都闭合」这句话在没有查过的情况下不许说出口。
    """
    doc_id = str(doc_id)
    doc = _doc_of(store, doc_id)
    deps, _dep_provided = _resolve_deps(store, doc_id, dependencies)
    # 语义判据一路透传给 `scan_document`（`draft/28` §196）：不传就等于这一维永远"没查"，
    # 而 H 的报告里那一格会一直写着 0 —— "没接线"与"查过没问题"必须分得开。
    scan = scan_document(doc, dependencies=deps, semantic_judge=semantic_judge)

    existing = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    if round_no is None:
        # 轮次从"该稿件已有发现的最大轮次"往后走 —— 用库里的既有事实推，
        # 而不是用一个内存计数器：审校必须能被中断后接着跑。
        round_no = max((int(r.get("round") or 1) for r in existing), default=0) + 1
    round_no = int(round_no)
    if round_no < 1:
        raise ValueError("round_no 从 1 开始")

    seen = {_dedup_key(r) for r in existing}
    pending: list[dict] = []
    duplicate_skipped = 0
    for f in scan["findings"]:
        key = _dedup_key(f)
        if key in seen:
            duplicate_skipped += 1
            continue
        seen.add(key)
        pending.append(f)

    new_findings: list[dict] = []
    if pending:
        with store.tx(
            "review_findings", actor=actor, note=f"review_document doc:{doc_id} round {round_no}"
        ) as tx:
            for f in pending:
                row = S.ReviewFinding(
                    finding_id="",
                    doc_id=doc_id,
                    kind=str(f["kind"]),
                    level=str(f["level"]),
                    target=str(f["target"]),
                    # evidence 由 scan_document 给出（触发该发现的实际值）。
                    # 它绝不会是空的：schema.ReviewFinding.validate 会拒绝空 evidence，
                    # 这里也再核一次，让错误带上"是哪条检查没给证据"。
                    evidence=str(f["evidence"]),
                    message=str(f["message"]),
                    round=round_no,
                    suggestion=str(f.get("suggestion") or ""),
                    # ---- `P-9` 候选 A 的四键（`X-96.3-1`）----
                    # `scan_document` 已经把取值按声明表补齐，这里原样落库，不在这里
                    # 重算（重算就会出现两份判据）。`line` 走第三态：`None` + 自证理由
                    # （理由由 `_LINE_UNAVAILABLE_REASON` 给，见那里的口径）。
                    # 这四键不进去重键（`_dedup_key` 仍是 `(kind, target, message)`）。
                    axis=str(f.get("axis") or ""),
                    line=f.get("line"),
                    line_unavailable_reason=str(f.get("line_unavailable_reason") or ""),
                    verbatim_quote=str(f.get("verbatim_quote") or ""),
                    maths=str(f.get("maths") or ""),
                    status="open",
                    resolution_note="",
                    created_at=S.now_iso(),
                    created_by=actor,
                )
                row.finding_id = tx.alloc_id("finding")
                row.validate()
                payload = row.to_dict()
                tx.upsert("review_findings", payload)
                new_findings.append(payload)

    # ---- 重开"标了 fixed 但其实还在"的发现（防止 G 用点状态的方式修好问题）
    current_keys = {_dedup_key(f) for f in scan["findings"]}
    reopened: list[dict] = []
    to_reopen = [
        r
        for r in existing
        if str(r.get("status")) == "fixed" and _dedup_key(r) in current_keys
    ]
    if to_reopen:
        _apply_finding_status(
            store,
            [
                {
                    "finding_id": r["finding_id"],
                    "status": "open",
                    "resolution_note": (
                        f"[round {round_no}] 重跑对应检查**仍然复现** ⇒ 之前的 fixed 不成立，重新打开"
                    ),
                }
                for r in to_reopen
            ],
            actor=actor,
            note=f"reopen doc:{doc_id}",
        )
        reopened = [{"finding_id": r["finding_id"], "kind": r.get("kind"), "target": r.get("target")} for r in to_reopen]

    dep_checked = bool(scan["dep_check"].get("checked"))
    if scan["error_count"]:
        verdict = "rejected"
    elif not dep_checked:
        # 「依赖闭合没查」不等于「依赖闭合」—— 不许在这个前提下判 accepted。
        verdict = "unverified"
    elif scan["warning_count"]:
        verdict = "accepted_with_warnings"
    else:
        verdict = "accepted"

    target_status = "accepted" if (scan["error_count"] == 0 and dep_checked) else "in_review"
    status_updated, status_error, status_now = _set_doc_status(store, doc_id, target_status, actor=actor)
    # `T4-B`：判 accepted 就签一条（`draft/29` §8.8.3"接受档签一条，毫不犹豫"）。
    # 签在状态写成之后：签名钉的是那一版的内容哈希与它读到的发现，
    # 与状态更新是两个动作（状态失败时仍然可以签 —— 但那会让 signature 与 status 不符，
    # 所以这里只在状态真的成为 accepted 时签，并把失败如实带回去）。
    signature, signature_error = _sign_accepted_revision(
        store, doc_id, verdict=verdict, actor=actor, round_no=round_no,
        status_now=status_now, status_updated=status_updated,
        coverage=scan.get("coverage"),
    )

    reason_bits = [
        f"机械检查发现 error={scan['error_count']}、warning={scan['warning_count']}、info={scan['info_count']}",
        (
            f"依赖闭合已检查（{scan['dep_check'].get('reason')}）"
            if dep_checked
            else f"依赖闭合**没查**（{scan['dep_check'].get('reason')}）⇒ 不能判 accepted"
        ),
        f"新增发现 {len(new_findings)} 条、与已有发现重复被跳过 {duplicate_skipped} 条",
        f"覆盖率 {scan['coverage']['claims_reviewed']}/{scan['coverage']['claims_total']}"
        f"（判成 {scan['coverage']['claims_decided']}）",
        # `R-42`：写入路径也必须把"语义级没查"说出来 —— 否则 `accepted` 会被读成
        # "两层都查过了"。这里不改 verdict 分档（改动分档是口径，属禁改区）：
        # 语义级判据今天只能通过 `scan_document(semantic_judge=…)` 注入，
        # 而 `review_document` 走的是工具面（`additionalProperties: False`，塞不进判据）
        # ⇒ 这一格在写入路径上如实报没查，并由 `semantic_check` 字段带出去。
        (
            f"语义级判据已判 {scan['semantic_check']['claims_judged']} 条"
            if scan["semantic_check"]["checked"]
            else "语义级判据**没查**（未接线）—— '措辞干净而结论强于引文'这一形态看不见"
        ),
    ]
    if reopened:
        reason_bits.append(f"重开 {len(reopened)} 条「标了 fixed 但重跑仍复现」的发现")
    if not status_updated:
        reason_bits.append(f"⚠️ 文档状态**未能更新**（{status_error}）—— 这通常因为盘上这份稿件本身不合 schema")

    return {
        "doc_id": doc_id,
        "checked": True,
        "round": round_no,
        "new_findings": new_findings,
        "duplicate_skipped": duplicate_skipped,
        "reopened": reopened,
        "error_count": scan["error_count"],
        "warning_count": scan["warning_count"],
        "info_count": scan["info_count"],
        "dep_check": scan["dep_check"],
        # `R-42`：语义级判据的三态随写回结果一起给出（与 `dep_check` 并排）。
        # 这是"写回路径也不许把没查说成通过"的落点：`coverage` 里
        # `claims_semantically_judged=0` 与这里 `checked=False` 一起读。
        "semantic_check": scan["semantic_check"],
        "coverage": scan["coverage"],
        "status": status_now,
        "status_updated": status_updated,
        "status_error": status_error,
        "signature": signature,
        "signature_error": signature_error,
        "verdict": verdict,
        "reason": "；".join(reason_bits) + "。",
    }


# ---------------------------------------------------------------- 复审（判 fixed / open）


def _sign_accepted_revision(
    store: Any,
    doc_id: str,
    *,
    verdict: str,
    actor: str,
    round_no: int | None,
    status_now: str,
    status_updated: bool,
    coverage: Mapping[str, Any] | None = None,
) -> tuple[dict | None, str | None]:
    """判 accepted 之后签一条（`draft/29` §8.8；`draft/30` §T4-B）。

    - 只在状态真的成为 `accepted` 时签：签名钉的是"这一版被审过"，而状态没写成
      （例如盘上那行不合 schema）说明这一版还不是可引来源 ⇒ 签了会与 status 分家；
    - `instance_id` 取"谁 + 何时"（一次审就是一次调用）。它只作留痕，
      不作门槛（§8.8.4 收尾那一段逐字说了这件事）；
    - 返回 `(签名记录 或 None, 错误说明 或 None)` —— 失败如实带回，
      不吞掉（"审过了但没签上"与"审过并签上"必须分得开）。
    """
    if not (status_updated and status_now == "accepted"):
        return None, None
    from .. import schema as S
    from .. import signatures as SIG

    doc = next((r for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)), None)
    if doc is None:
        return None, f"签名时稿件 {doc_id} 读不出来"
    findings = [r for r in store.rows("review_findings") if str(r.get("doc_id")) == str(doc_id)]
    at = S.now_iso()
    try:
        return SIG.append_signature(
            store.root if getattr(store, "root", None) is not None else ".",
            {
                "doc_id": str(doc_id),
                "content_sha256": str(doc.get("content_sha256") or ""),
                "claims_hash": SIG.claims_hash_of(doc),
                "name": SIG.SIGNER_NAME,
                "at": at,
                "scope": "document",
                "verdict": verdict,
                "note": f"round={round_no}；机械检查判定 {verdict}",
                "instance_id": f"{actor}@{at}",
                "model": "",           # 机械审没有模型（有 LLM 时由接线层填，不在这儿编）
                "prompt_version": "",
                "temperature": None,
                # `draft/31` P7 第 4 项：签名要带"审了多少条断言"。
                # 它是元数据，不进 `content_sha256`（那一位只覆盖稿件内容）——
                # 所以补记覆盖率不会让已签的这一版失效，而漏记也不会让签名看起来通过。
                "coverage": dict(coverage or {}),
                "inputs": {"doc_sha256": str(doc.get("content_sha256") or ""),
                           "evidence_hashes": []},
                "basis": {
                    "codes_checked": sorted({str(f.get("kind") or "") for f in findings if f.get("kind")}),
                    "finding_ids": sorted({str(f.get("finding_id") or "") for f in findings if f.get("finding_id")}),
                    "rounds": int(round_no or 0),
                    "dimensions": sorted({str(f.get("axis") or "") for f in findings if f.get("axis")}),
                },
            },
            findings=findings,
        ), None
    except (ValueError, OSError) as e:
        return None, f"{type(e).__name__}: {e}"


def _is_semantic_finding(item: Mapping[str, Any]) -> bool:
    """这条 finding 是不是语义判据产出的那一支（`R-04-b` 的判据面）。

    判据逐字（与 `scan_document` 里那条 finding 的写法对齐）：`kind == "overclaim"`
    且 `evidence` 以 `语义判据（` 开头 —— 措辞级那条 `overclaim` 的 evidence
    是别的形态，所以两者分得开（"改了词"与"结论强于引文"的处置方向不同）。
    """
    return (str(item.get("kind") or "") == "overclaim"
            and str(item.get("evidence") or "").startswith("语义判据（"))


def verify_fixes(
    store: Any,
    doc_id: str,
    *,
    round_no: int,
    dependencies: Any = _UNSPECIFIED,
    max_review_rounds: int = 2,
    actor: str = "agent-H",
    semantic_judge: SemanticJudge | None = None,
) -> dict:
    """复审：对上一轮的每条 finding 重跑对应检查，判定 `fixed` / 仍 `open`。

    返回 ``{"doc_id","round","resolved","still_open","unresolved_findings","verdict",
    "reason",...}``。

    ## 终止性（FC-18 的同族要求）

    `error` 级发现一直不修、且已经到 `max_review_rounds` ⇒ 文档状态置
    `unresolved_review`，并且必须把未解决的 finding 明确列出来
    （`unresolved_findings` 非空）。「跑了 N 轮还是红」如果只体现在一个状态字符串上，
    接手的人就无从知道到底卡在哪一条 —— 不许隐藏。

    ## 判定口径

    判据不是 G 自称修好了，而是"重跑检查还复现吗"：
    复现 ⇒ `open`（即使 G 已经把它标成 `fixed`，也会被重新打开）；
    不复现 ⇒ `fixed`。此外当前扫描里新出现的问题会以 `source="new_issue"`
    出现在 `still_open` 里（复审不是"只看旧账"）。

    ## `R-04`（`draft/44` / `draft/52` D 族）：两半

    R-04-a（语义判据的注入面）：复审复扫与 `review_document` 走同一个
    `scan_document(..., semantic_judge=...)`。此前 `verify_fixes` 的复扫不带判据，
    于是"上一轮由语义判据产生的 `overclaim`"在这一轮结构上不可能复现 ⇒
    必然落进 `resolved` ⇒ 写成 `status="fixed"`（真机 `p8d` 的 claim-3/claim-4
    就是这样被"修好"的：库里是 `fixed`，而现行版内容上它们仍被判"结论强于引文"）。

    R-04-b（没查 ≠ 修好）：`resolved` 里凡是语义那一支的 finding，
    只有"这一轮真的重跑了语义判据、且它没有复现"才允许落 `fixed`；
    判据没接线（`semantic_judge is None`）或这一轮答不上来 / 判据报错
    （`claims_unknown` / `checker_errors`）⇒ 留在 `open` 并标
    `source="not_rechecked"`（返回值取值，不落表）。
    """
    doc_id = str(doc_id)
    round_no = int(round_no)
    if round_no < 1:
        raise ValueError("round_no 从 1 开始")
    max_review_rounds = int(max_review_rounds)
    if max_review_rounds < 1:
        raise ValueError("max_review_rounds 至少为 1")

    doc = _doc_of(store, doc_id)
    deps, dep_checked = _resolve_deps(store, doc_id, dependencies)
    # R-04-a：复扫与 `review_document` 共用同一个语义判据（`semantic_judge=None`
    # 时 `semantic_check["checked"] is False` —— 那是"没查"，不是"没问题"）。
    scan = scan_document(doc, dependencies=deps, semantic_judge=semantic_judge)
    current = {_dedup_key(f): f for f in scan["findings"]}
    semantic_check = dict(scan.get("semantic_check") or {})
    #: 这一轮语义判据真的判过吗（R-04-b 的判据面）。
    #: 没接线、或有断言答不上来 / 判据报错 ⇒ 语义那一支一律不许判 `fixed`。
    semantic_recheck_ok = bool(
        semantic_check.get("checked")
        and not int(semantic_check.get("claims_unknown") or 0)
        and not int(semantic_check.get("checker_errors") or 0)
    )
    findings = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    prev = [r for r in findings if int(r.get("round") or 1) < round_no]

    resolved: list[dict] = []
    still_open: list[dict] = []
    for r in prev:
        base = {
            "finding_id": r.get("finding_id"),
            "kind": r.get("kind"),
            "level": r.get("level"),
            "target": r.get("target"),
            "message": r.get("message"),
            # `R-04-b` 的判据面要用它：语义那一支的 finding 靠 `evidence` 的前缀分辨
            # （`语义判据（…）判定结论强于引文`）—— 不回填的话"没重跑判据"就认不出来。
            "evidence": r.get("evidence"),
            "round": r.get("round"),
            "status": r.get("status"),
        }
        key = _dedup_key(r)
        if key in current:
            base["evidence"] = current[key].get("evidence")
            base["source"] = "prev_round"
            still_open.append(base)
        else:
            resolved.append(base)
    prev_keys = {_dedup_key(r) for r in prev}
    for key, f in current.items():
        if key in prev_keys:
            continue
        still_open.append(
            {
                "finding_id": None,
                "kind": f["kind"],
                "level": f["level"],
                "target": f["target"],
                "message": f["message"],
                "evidence": f.get("evidence"),
                "round": None,
                "status": "open",
                "source": "new_issue",
            }
        )

    # ---- 落状态：resolved ⇒ fixed；复现的旧账 ⇒ 重新打开（含"谎报修好")
    #
    # R-04-b（没查 ≠ 修好）：`resolved` 里语义那一支的 finding 先过一道闸门 ——
    # 只有"这一轮真的重跑了语义判据、且没复现"才允许落 `fixed`；
    # 没接线 / 答不上来 / 判据报错 ⇒ 留在 `open`，标 `source="not_rechecked"`。
    # 为什么必须把这一支单独拎出来：语义 finding 的去重键里带 `message`
    # （`(kind,target,message)`），而"这一轮没跑判据"时它当然不出现在 `current` 里 ——
    # 于是"没查"被读成"修好了"，那正是最贵的那条方向（`R-04` 的原文）。
    changes: list[dict] = []
    not_rechecked: list[dict] = []
    for item in list(resolved):
        if _is_semantic_finding(item) and not semantic_recheck_ok:
            resolved.remove(item)
            item["source"] = "not_rechecked"
            item["status"] = "open"
            item["note"] = (
                f"[round {round_no}] 本轮未重跑语义判据 ⇒ 不许判 fixed（没查 ≠ 修好）"
                + (f"；semantic_check={semantic_check.get('reason') or semantic_check}"
                   if not semantic_check.get("checked") else "")
            )
            still_open.append(item)
            not_rechecked.append(item)
            # 更要紧的是盘上也要留在 open：只改返回值而库里仍是 `fixed`，
            # 下一轮/下一个人读到的还是"修好了"（那正是这条要堵的方向）。
            changes.append(
                {
                    "finding_id": item["finding_id"],
                    "status": "open",
                    "resolution_note": (
                        f"[round {round_no}] 本轮未重跑语义判据 ⇒ 不许判 fixed（没查 ≠ 修好）"
                    ),
                }
            )
            continue
        changes.append(
            {
                "finding_id": item["finding_id"],
                "status": "fixed",
                "resolution_note": f"[round {round_no}] 重跑对应检查不再复现 ⇒ fixed",
            }
        )
    for item in still_open:
        if item.get("source") != "prev_round":
            continue
        if str(item.get("status")) != "fixed":
            continue
        changes.append(
            {
                "finding_id": item["finding_id"],
                "status": "open",
                "resolution_note": (
                    f"[round {round_no}] G 曾标为 fixed，但重跑对应检查**仍然复现** ⇒ 判定不成立，重新打开"
                ),
            }
        )
        item["status"] = "open"
        item["reopened"] = True
    finding_updates = _apply_finding_status(
        store, changes, actor=actor, note=f"verify_fixes doc:{doc_id} round {round_no}"
    )

    # ---- 判定（用"当前仍存在的 error"作准，而不是用 G 的自述）
    blocking = [
        f for f in still_open if str(f.get("level")) == "error" and str(f.get("status")) in ("open", "fixed")
    ]
    if not still_open:
        verdict = "accepted"
    elif blocking and round_no >= max_review_rounds:
        verdict = "unresolved_review"
    elif blocking:
        verdict = "revise_again"
    elif not_rechecked:
        # R-04-b ③：这一轮没重跑语义判据 ⇒ 不许读成 `accepted`
        # （"没查"与"查过了没问题"必须分得开；它们也只是 warning，
        #  所以上面那两条 `blocking` 分支接不住）。处置方向是"去把判据接上再复审"，
        #  不是"再改一遍稿子" ⇒ 用 `revise_again` 这一档（`in_review`），不冒充终局。
        verdict = "revise_again"
    else:
        # 只剩 warning（已记录的已知边界）或已被人明确 wontfix 的项：
        # 它们仍然列在 still_open 里（不许隐藏），但不该把红灯训练成噪音（FC-13）。
        verdict = "accepted"

    target_status = {"accepted": "accepted", "revise_again": "in_review", "unresolved_review": "unresolved_review"}[
        verdict
    ]
    # ---- `R-59`（`draft/28` §161.4，口径 ②）：`accepted` 必须由"针对这一版"的签名背书
    #
    # 老形态是一条真的缺口（`_f4_probe_gh.py` 当场咬出来的）：改稿之后 `verify_fixes` 复审
    # 通过 ⇒ 它把 `documents.status` 置回 `accepted`，而签名台账里那条签的是旧版本 ⇒
    # `verify_all` 报 `stale_signature`。那不是误报：`draft/29` §8.8.4 的口径就是
    # "改稿之后旧审批不许沿用"。
    #
    # 判据用 `signatures.signed_revision`（不许用 `signed()`）：后者对非 `accepted`
    # 状态的稿件一律返回真（草稿本来就不该被签），拿它来判会得到"真" ⇒ 恰好放过这一格。
    # 两条出路里选了"不置 accepted"而不是"补签"：接受 = 有一次针对这一版的审+签，
    # 而 `verify_fixes` 不是一次审（它只重跑旧发现的对应检查、不重判全部判据）——
    # 让它也能签，等于把"谁能签发"从一处变成两处。
    accepted_without_signature_for_this_revision = False
    signed_revision_at: str = ""
    if target_status == "accepted":
        from .. import signatures as SIG

        _root = store.root if getattr(store, "root", None) is not None else "."
        _recs, _bad = SIG.read_ledger(SIG.ledger_path(_root))
        _pinned = SIG.signed_revision(doc, _recs)
        if _pinned is None:
            target_status = "in_review"
            accepted_without_signature_for_this_revision = True
        else:
            signed_revision_at = str(_pinned.get("at") or "")
    status_updated, status_error, status_now = _set_doc_status(store, doc_id, target_status, actor=actor)

    unresolved = [f for f in blocking]
    reason_bits = [
        f"第 {round_no} 轮复审（上限 max_review_rounds={max_review_rounds}）："
        f"上一轮 {len(prev)} 条发现里 resolved={len(resolved)}、仍复现={len(still_open) - len([f for f in still_open if f.get('source') == 'new_issue'])}",
        f"error 级未解决 {len(unresolved)} 条",
        # `R-04-b`：没重跑语义判据时，上一轮那几条语义发现留在 open
        # （读数必须逐条说出来，否则"resolved 变多了"看起来像"修好了"）。
        (
            f"其中 {len(not_rechecked)} 条是**语义判据产的发现**、本轮未重跑判据 ⇒ 留在 open、"
            f"不许判 fixed（没查 ≠ 修好）"
            if not_rechecked
            else ""
        ),
    ]
    if not dep_checked:
        reason_bits.append("⚠️ 依赖闭合**没查**（dependencies=None）⇒ 本轮结论不覆盖依赖闭合这一维")
    if accepted_without_signature_for_this_revision:
        reason_bits.append(
            "⚠️ **不置 `accepted`**（置 `in_review`）：本轮复审判定通过，但台账里没有任何签名"
            "**钉在当前这一版内容上** ⇒ 依 `draft/29` §8.8.4「改稿之后旧审批不许沿用」，"
            "现在置 accepted 会留下『状态 accepted + 签名钉旧版』（`stale_signature`）。"
            "请用 `review` 重新判一次并签名 —— 那是「接受 = 有一次针对这一版的审+签」的唯一入口"
            "（`R-59`，`draft/28` §161.4 的口径 ②）"
        )
    elif signed_revision_at and verdict == "accepted":
        reason_bits.append(
            f"本版已有签名钉住（{signed_revision_at}）⇒ `accepted` 由它背书，本轮不重复签"
        )
    if verdict == "unresolved_review":
        reason_bits.append(
            "已达轮数上限且 error 级发现仍 open ⇒ 停止自动修订，交人复核（**未解决的发现已全部列出**，未隐藏）"
        )
    if not status_updated:
        reason_bits.append(f"⚠️ 文档状态**未能更新**（{status_error}）")

    return {
        "doc_id": doc_id,
        "round": round_no,
        "resolved": resolved,
        "still_open": still_open,
        "unresolved_findings": unresolved,
        # R-04-b 的读数：这一轮没重跑语义判据因而留在 open 的那些（返回值取值，不落表）。
        "not_rechecked": not_rechecked,
        "semantic_check": semantic_check,
        "verdict": verdict,
        "reason": "；".join(reason_bits) + "。",
        "error_count": scan["error_count"],
        "warning_count": scan["warning_count"],
        "info_count": scan["info_count"],
        "dep_check": scan["dep_check"],
        "finding_updates": finding_updates,
        "status": status_now,
        "status_updated": status_updated,
        "status_error": status_error,
    }


# ---------------------------------------------------------------- 只读列举


def list_findings(
    store: Any,
    *,
    doc_id: str | None = None,
    status: str | None = None,
    level: str | None = None,
) -> dict:
    """只读列举审校发现。"""
    if status is not None and status not in S.FINDING_STATUSES:
        raise ValueError(f"status 必须是 {S.FINDING_STATUSES} 之一，收到 {status!r}")
    if level is not None and level not in S.FINDING_LEVELS:
        raise ValueError(f"level 必须是 {S.FINDING_LEVELS} 之一，收到 {level!r}")
    out: list[dict] = []
    for r in sorted(store.rows("review_findings"), key=lambda x: str(x.get("finding_id"))):
        if doc_id is not None and str(r.get("doc_id")) != str(doc_id):
            continue
        if status is not None and r.get("status") != status:
            continue
        if level is not None and r.get("level") != level:
            continue
        out.append(
            {
                "finding_id": r.get("finding_id"),
                "doc_id": r.get("doc_id"),
                "kind": r.get("kind"),
                "level": r.get("level"),
                "target": r.get("target"),
                "message": r.get("message"),
                "evidence": r.get("evidence"),
                "status": r.get("status"),
                "round": r.get("round"),
                "resolution_note": r.get("resolution_note"),
            }
        )
    return {"count": len(out), "findings": out}


# ---------------------------------------------------------------- 审校报告（G1–G15）

#: 审校报告默认落点（相对工作区）。沿用 `draft/17` §8.1 的目录树建议：
#: 报告与稿件分开放，且按被审对象命名，于是"这份报告审的是哪一版"靠文件名
#: 就能对上 —— 再加上报告头里的内容 hash，"行号失效"这件事才不可能悄悄发生。
DEFAULT_REPORT_SUBDIR = "reports"


def review_report(
    store: Any,
    doc_id: str,
    *,
    own_errors: Sequence[str] | None,
    out_path: Any = None,
    dependencies: Any = _UNSPECIFIED,
    run_evidence: Mapping[str, Any] | None = None,
    banned_words: Sequence[str] | None = None,
    claim_counts: Mapping[str, Any] | None = None,
    workspace_root: Any = None,    actor: str = "agent-H",
    round_no: int = 1,
    # 语义判据的接缝（`draft/28` §196）：报告里的 `coverage.claims_semantically_judged`
    # 就从这里来。不传 ⇒ 那一格是 0 且 `semantic_check["checked"] is False`（没查），
    # 与"判过、都说一致"严格分开。
    semantic_judge: Any = None,
) -> dict:
    """产出 G1–G15 的完整审校报告（markdown 落盘）—— §8.4 的落地入口。

    ## 三件被结构强制的事（缺一件就抛，见 `gates.gate_report`）

    1. 钉住被审版本 hash（G11）：报告头写 `revision_hash`
       （`claimanatomy.revision_hash`，算法逐字写进报告）。
    2. 『我这一轮犯的错』一节（G15）：`own_errors` 是必填参数；
       `None` ⇒ 抛（"没写"不等于"没犯错"），`[]` ⇒ 合法（显式声明零错误）。
    3. 零发现自证（G13）：每道报"零发现"的门都必须带"我用了什么过程、
       数出了什么数字" —— 由 `gates.GateResult` 的构造期校验保证，
       G13 再独立复核一遍。

    ## 它写哪里、写什么

    只写一个 markdown 文件（默认 `<workspace>/reports/<doc_id>-review.md`），
    不碰任何数据表、不碰 `claims`。这是 `AgentH` 落库代理的一个入口，
    因此它属于"能被显式拒绝的写工具"那一类（`include_writers=True` 才装配）。

    三态：`dependencies` 省略 = 从库里读该稿件的依赖（查过）；
    显式 `None` = 没查（`dep_check.checked=False`）。
    """
    if own_errors is None:
        raise ValueError(
            "审校报告必须包含『我这一轮犯的错』一节（`own_errors` 必填）。"
            "传空列表表示『本轮零自身错误』，但**必须由调用方显式写出来** —— "
            "若允许『没写』等于『没犯错』，这一节就会永远空着（§8.4 G15：缺失则退回）"
        )
    doc = _doc_of(store, doc_id)
    deps, deps_checked = _resolve_deps(store, str(doc_id), dependencies)

    root = Path(workspace_root).resolve() if workspace_root else Path(store.root).resolve()
    # 显式给了 `out_path` 就核边界（越界一律拒绝，不是"写到外面再警告"）；
    # 没给就用默认落点。`resolve()` 之后再 `relative_to()` 判断，
    # 而不是靠字符串 `..` 检查 —— 后者会被符号链接绕过。
    raw = str(out_path) if out_path else f"{DEFAULT_REPORT_SUBDIR}/{doc_id}-review.md"
    target = Path(raw)
    absolute = target if target.is_absolute() else (root / target)
    absolute = absolute.resolve()
    try:
        rel = absolute.relative_to(root)
    except ValueError as e:
        raise ValueError(
            f"审校报告的 out_path 越界：{raw!r} 不在工作区 {root} 内（{type(e).__name__}）。"
            "报告只允许写在工作区里 —— 这是沙箱边界，不是建议"
        ) from e

    ctx = G.GateContext.build(
        doc,
        dependencies=deps if deps_checked else None,
        files=None,
        workspace_root=root,
        run_evidence=run_evidence,
        findings=list(store.rows("review_findings")) if store is not None else None,
        claim_counts=claim_counts,
        banned_words=banned_words,
        own_errors=list(own_errors),
    )
    report = G.gate_report(ctx, own_errors=list(own_errors), reviewer=actor, round_no=round_no)
    markdown = G.render_review_report(report)
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_text(markdown, encoding="utf-8")
    # 覆盖率（`draft/31` P7 第 4 项）：就地重算而不是让调用方传进来 ——
    # 传进来的覆盖率是可以编的，而这一格的全部意义就是"如实"。
    # 与 `review_document` 同一份判据源（`scan_document`），所以两处不会给出两个数。
    coverage = scan_document(doc, dependencies=deps if deps_checked else None,
                             semantic_judge=semantic_judge)["coverage"]
    return {
        "doc_id": str(doc_id),
        "round": int(round_no),
        "report_path": str(rel).replace("\\", "/"),
        "revision_hash": report["revision_hash"],
        "verdict": report["verdict"]["verdict"],
        "gates_total": report["gates_total"],
        "pass_count": report["verdict"]["pass"],
        "fail_count": report["verdict"]["fail"],
        "unknown_count": report["verdict"]["unknown"],
        "not_applicable_count": report["verdict"]["not_applicable"],
        "failed_gates": list(report["verdict"]["failed_gates"]),
        "unknown_gates": list(report["verdict"]["unknown_gates"]),
        "own_error_count": len(list(own_errors)),
        "coverage": coverage,
        "markdown": markdown,
    }


# ---------------------------------------------------------------- 工具装配


@tool(
    "review.scan_document",
    "对一份稿件做全量机械审校（引用/证据等级/否定分类/依赖闭合），每条发现都带 evidence",
    {
           "type": "object",
           "properties": {
            "doc": {"type": "object"},
            "dependencies": {"type": "array", "items": {"type": "object"}},
           },
           "required": ["doc"],
           "additionalProperties": False,
           },
    # 省略 `dependencies` ⇒ 显式传 `None` ⇒ `dep_check.checked=False`，
    # 于是 `verdict` 是 `unverified`（不是 accepted）。
    # 这个工具没接 store（`side_effect="none"` 的只读工具不该去抢锁），
    # 因此"自己去库里读依赖"这条路径只在 `review_document` 里存在。
    side_effect="none",
    roles=_ROLES,
    returns=(
            "{'checked','doc_id','findings','error_count','warning_count','info_count',"
            "'dep_check','verdict','reason'}；verdict ∈ {rejected, unverified, "
            "accepted_with_warnings, accepted}，dep_check.checked=False 时**必为** unverified"
            ),
    tags=("review", "gate"),
)
def _review_scan_document_tool(doc, dependencies=_UNSPECIFIED):
    """review.scan_document 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（无）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    ok(
               scan_document(doc, dependencies=None if dependencies is _UNSPECIFIED else dependencies)
               )
    )

@tool(
    "review.list_findings",
    "只读列举审校发现（可按稿件/状态/级别过滤），含每条发现的 evidence",
    {
           "type": "object",
           "properties": {
            "doc_id": {"type": "string"},
            "status": {"type": "string", "enum": list(S.FINDING_STATUSES)},
            "level": {"type": "string", "enum": list(S.FINDING_LEVELS)},
           },
           "additionalProperties": False,
           },
    side_effect="read",
    roles=_ROLES,
    returns="{'count','findings':[{'finding_id','doc_id','kind','level','target','message','evidence','status'}]}",
    tags=("review", "read"),
)
def _review_list_findings_tool(_not_wired, store, doc_id=None, status=None, level=None):
    """review.list_findings 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_not_wired, store）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _not_wired()
               if store is None
               else _guard_result(lambda: list_findings(store, doc_id=doc_id, status=status, level=level))
    )

@tool(
    "review.review_document",
    (
            "审一份稿件：把机械发现落成 ReviewFinding（每条带 evidence），并更新文档状态；"
            "只写 review_findings 与 documents.status，不改 claims"
            ),
    {
           "type": "object",
           "properties": {
            "doc_id": {"type": "string"},
            "round_no": {"type": "integer", "minimum": 1},
            "dependencies": {"type": "array", "items": {"type": "object"}},
           },
           "required": ["doc_id"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITER_ROLES,
    returns="{'doc_id','new_findings','duplicate_skipped','error_count','warning_count','verdict','status','signature','signature_error','coverage'}",
    tags=("review", "write"),
)
def _review_review_document_tool(_not_wired, store, actor, semantic_judge, **kw):
    """review.review_document 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_not_wired, store, actor, semantic_judge）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _not_wired()
               if store is None
               else _guard_result(lambda: review_document(store, actor=actor,
                                                         semantic_judge=semantic_judge, **kw))
    )

@tool(
    "review.verify_fixes",
    (
            "复审：对上一轮每条 finding 重跑对应检查，判 fixed / 仍 open；"
            "到 max_review_rounds 仍红则置 unresolved_review 并**列出**未解决项"
            ),
    {
           "type": "object",
           "properties": {
            "doc_id": {"type": "string"},
            "round_no": {"type": "integer", "minimum": 1},
            "dependencies": {"type": "array", "items": {"type": "object"}},
            "max_review_rounds": {"type": "integer", "minimum": 1},
           },
           "required": ["doc_id", "round_no"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITER_ROLES,
    returns="{'doc_id','round','resolved','still_open','unresolved_findings','verdict','not_rechecked'}",
    tags=("review", "write"),
)
def _review_verify_fixes_tool(_not_wired, store, actor, semantic_judge=None, **kw):
    """review.verify_fixes 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_not_wired, store, actor, semantic_judge）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同：`semantic_judge` 不进模型参数表
    （`@tool` 的 properties / `additionalProperties: False` 一个字不改），
    它只由 `register(..., semantic_judge=...)` 在装配期绑进来（`R-04-a`）。

    `semantic_judge` 缺省 `None` ⇒ `R-04-b` 的兜底生效：上一轮由语义判据产生的
    `overclaim` 不许被判成 `fixed`（没查 ≠ 修好）。
    """
    return (
    _not_wired()
               if store is None
               else _guard_result(lambda: verify_fixes(store, actor=actor,
                                                       semantic_judge=semantic_judge, **kw))
    )

@tool(
    "review.report",
    (
            "产出 G1–G15 的完整审校报告（markdown 落盘）：报告头钉住被审版本 hash、"
            "每道门都带零发现自证数字、并强制包含『我这一轮犯的错』一节；"
            "只写一个报告文件，不碰任何数据表、不碰 claims"
            ),
    {
           "type": "object",
           "properties": {
            "doc_id": {"type": "string"},
            "own_errors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "我这一轮犯的错（§8.4 G15）。必填：不写就是退回，空数组=显式声明零错误",
            },
            "out_path": {"type": "string", "description": "工作区内的相对路径；越界即拒绝"},
            "round_no": {"type": "integer", "minimum": 1},
            "dependencies": {"type": "array", "items": {"type": "object"}},
            "banned_words": {"type": "array", "items": {"type": "string"}},
            "run_evidence": {
                "type": "object",
                "description": (
                    "本轮的实跑记录（G8 可复跑门）："
                    "{'checked':true,'commands':[{'claim_id','command','output_tail'}]}。"
                    "**不传 ⇒ G8 判 unknown**（『本轮实跑过』无法判定），"
                    "绝不判 pass —— 把『没报错』读成『没问题』正是参考体例记录的教训"
                ),
            },
            "claim_counts": {
                "type": "object",
                "description": "调用方声明的计数（G9 计数一致门）：declared_claim_count 等",
            },
           },
    # `own_errors` 是 required：G15 的判据是"缺失则退回"，
    # 而"参数可省略"正是"缺失"在工具层的形态。
           "required": ["doc_id", "own_errors"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITER_ROLES,
    returns=(
            "{'doc_id','round','report_path','revision_hash','verdict','gates_total',"
            "'pass_count','fail_count','unknown_count','not_applicable_count',"
            "'failed_gates','unknown_gates','own_error_count','coverage','markdown'}"
            ),
    tags=("review", "write", "gate"),
)
def _review_report_tool(_not_wired, store, actor, semantic_judge, **kw):
    """review.report 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_not_wired, store, actor, semantic_judge）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _not_wired()
               if store is None
               else _guard_result(lambda: review_report(store, actor=actor,
                                                        semantic_judge=semantic_judge, **kw))
    )

#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
#: 声明随函数走（`@tool` 写进 `fn.__tool_spec__`），这里只列装配要做的事。
_READ_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_review_scan_document_tool, ()),
    (_review_list_findings_tool, ('_not_wired', 'store')),
)

#: 会写盘的三个入口：默认不装（结构约束：H 的工具面必须全 read/none）。
#: 它们与只读面分表，正是因为"装与不装"由 `include_writers` 决定 ——
#: 混成一张表会让"默认不装"这件事无处表达（`T-8` 搬移时实测过：
#: 不拆表的话三个写工具会绕过那句早退，H 的工具面当场多出写入口）。
_WRITE_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_review_review_document_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
    (_review_verify_fixes_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
    (_review_report_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
)


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    include_writers: bool = False,
    actor: str = "agent-H",
    semantic_judge: Any = None,
    **_: Any,
) -> None:
    """装配审校工具。

    ## 为什么写工具默认不注册

    「H 的工具面必须全部 `side_effect in ("none","read")`」是结构约束，不是口号。
    默认注册面只有 `review.scan_document`（`none`）与 `review.list_findings`（`read`）；
    会写盘的两个入口必须由调用方显式 `include_writers=True` 才装配
    （`AgentH` 用它构造自己的"落库代理"，与它的自由工具箱分开）。
    默认把写工具塞进来，就等于承认这个约束只是写在文档里的愿望。
    """
    def _not_wired(**__: Any) -> Any:
        """未接线时显式失败（FC-08）：返回"没查"，绝不返回"没有发现"的空结果。"""
        return fail(
            "review 工具未接线（装配时未提供 store）⇒ **没查**，不是『没有发现』",
            kind="not_wired",
        )

    _bound: dict[str, Any] = {}
    _bound['_not_wired'] = _not_wired
    _bound['store'] = store
    _bound['actor'] = actor
    _bound['semantic_judge'] = semantic_judge
    for _fn, _deps in _READ_TOOL_FUNCTIONS:
        registry.register(replace(_fn.__tool_spec__,
                                  handler=partial(_fn, *[_bound[k] for k in _deps])))


    if not include_writers:
        # 默认面到此为止：全部 none/read。写入口需要显式打开。
        return

    for _fn, _deps in _WRITE_TOOL_FUNCTIONS:
        registry.register(replace(_fn.__tool_spec__,
                                  handler=partial(_fn, *[_bound[k] for k in _deps])))



