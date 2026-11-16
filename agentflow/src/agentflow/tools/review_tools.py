"""H 的工具：审校。

## 审校对象是论文，不是台账行（业主 2026-10-24 裁定）
「只对论文负责是正确的，documents 等都是中间产物」＋「H 审论文（`out/paper/main.tex` /
pdf），documents 只是它的登记行」。所以 `review.review_document` 的输入正文来自
`read_paper_body`：`<项目根>/out/paper/main.tex` 优先，退到 `main.pdf` 的文本层；正文带
行号（`_line_of` 因此能定位），本次审的那一份正文的 sha256 记进读数。两者都没有 ⇒
`checked=False` + `verdict="unreviewable"`，不落发现、不动状态：没审到不是"审过、没问题"。
`documents` 那一行仍只是中间产物 —— 审完只改它的 `status`，台账行缺失时论文照审。

## 这个模块存在的最重要理由
审校者的判断也需要证据：① `schema.ReviewFinding.evidence` 必填非空（写入时硬约束）；
② 每个检查都给出 `evidence`，内容是触发该发现的实际值（如 `citations=[]`、
`evidence_kind='cross_check' 且 disclaimer 为空`），而不是一句「看起来不对」。

## 「H 只读」在本模块里的落地形态（两条，缺一不可）
- 默认注册面只读：`register()` 只注册 `review.scan_document`（`none`）与
  `review.list_findings`（`read`）；会写盘的两个入口必须显式 `include_writers=True` 才会
  被装配 ⇒ 「H 的工具面」在结构上不含任何写工具。
- 它们是 H 的代理步骤，不是 H 的刀：落点钉死在 `review_findings`（新增/改状态）与
  `documents.status` 上，一个字都不改 `claims` / 知识表。

## 判据只有一份
`scan_document` 与 G 侧 `doc_tools.scan_claim` 同词表（`schema.FINDING_KINDS`），逐条检查
项必须一致：引用是否为空、`evidence_kind` 是否合法、`cross_check` 是否缺 disclaimer、正文
是否过度声称、否定型断言的 `negation_kind` 是否合法/是否该有。这里曾经是假的：docstring
声称"不另写一套检查"，而 `scan_document` 复制了一份且漂移（不查非法 `evidence_kind`、不查
`negation_kind` 词表、不查"非否定断言却带了 negation_kind"）。现在三条已补齐，字段级判据
归 `claimanatomy`（`CLAIM_FIELDS` 是唯一声明表），`doc_tools.scan_claim` 只是适配层。
`scan_document` 保留自己的循环，但必须产出同一批 finding kind 且不许比 G 侧轻 —— 由
`tests/test_tools_audit_fixes.py` 的双向对照与 `tests/test_gates.py` 的 G10/G14 钉住。
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .. import claimanatomy as CA
from .. import gates as G
from .. import schema as S
from .. import texaudit as TEX
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
    # 「2026-10-15 补登记」：`uncontrolled_disclaimer`（2026-10-13 加）同样漏了这里。
    # 本表的兜底是 `garbled`（见上面那句"不在表里的 code 落到 `garbled`"），
    # 所以它不像 `doc_tools` 那张表那样当场炸 —— 它「静默地」把
    # "声明不是受控那一句"读成"表述无法解析"，而 kind 是审校分档的判据。
    # 两条漏登记是同一个根因（新 code 只登记进了 `claimanatomy` 的表，
    # 没往两张落据表同步），但「故障形态相反」：G 侧炸、H 侧错。
    #
    # 为什么落 `unsupported_claim`：与 `missing_disclaimer`（H 自己那条
    # "disclaimer 为空"的检查，在 `_H_OWN_CODES` 里）同族同义 ——
    # 区别只在"没写"与"写错了"，该改的栏是同一个。
    # 这里刻意不把它加进 `_H_OWN_CODES`：H 的循环只判"空不空"，
    # 判"是不是受控那一句"是 `claimanatomy` 的新判据，交给它判。
    "uncontrolled_disclaimer": "unsupported_claim",
}


# ---- `P-9` 候选 A 的四键 + 「最小修法」：产出侧的唯一声明表（`X-96.3-1`）
# 背景（`draft/28` §96.3 第 1 条，`temp/FIXG4.md` §9.1）：`gates.gate_g10` 只对
# `created_at >= schema.REVIEW_FINDING_FORMAT_SINCE`（2026-09-27）的发现要求四键齐，而今天的真实产出方
# 就是本模块 —— 本模块一个都不产，于是 G10 对每一条今天写出的发现都只能报 `unknown`。四个字段本身已在
# `schema.ReviewFinding` 里（禁 AI 区，2026-09-27 所有者裁定候选 A），缺的只有产出侧。
# 两条纪律（详见 `schema.ReviewFinding` 的类 docstring）：① 这四键不进去重键 —— `_dedup_key` 仍是
# `(kind, target, message)`，塞进去会让稿件每改一个词就产生一批新发现并打断"标了 fixed 但其实还在"的重开；
# ② 取值全部非空 —— 空值不是"更宽松"，G10 的六字段判据会把它读成"缺这一格"⇒ 整批发现被打回（`fail`），
# 比原来那句 `unknown` 更坏。
# 取值判据：`axis`（取值域 = `gates.AXES`）判的是外部依据还是稿件自己的表述 —— 外部依据走 `证据`（与
# G2/G6/G7/G8 同轴），稿件怎么写/字段合不合规/哪里自相矛盾走 `体例`（与 G3/G4/G9/G13 同轴）；`maths`
# （`schema.FINDING_MATHS_VALUES`）要读断言本身才能判 ⇒ `yes`，只判机械形态或登记簿 ⇒ `no`；
# `suggestion`（与历史键名 `minimal_fix` 同格）逐 kind 一句可执行的最小动作。
_FOUR_GATE_KEYS_OF_KIND: dict[str, tuple[str, str, str]] = {
    # kind                    axis    maths  最小修法(suggestion)
    "unsupported_claim": ("证据", "yes",
                          "给这条断言补上出处（`citations` 非空），或把它降为 remark"),
    "overclaim": ("体例", "yes",
                  "把证明性措辞改成它实际的证据档位；`cross_check` 另需补 `disclaimer`"),
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

#: `line` 这一格为什么仍然可能是第三态（`None` + 自证理由），而不是一个数字。
#:
#: `P-9` 的口径逐字是"行号只有在版本冻结（G11）之后才有意义"（`docs/PROPOSALS.md:239-240`）。
#: 未冻结时记下的行号在改稿之后就是错的，而它看起来一样精确 —— `.noai-paths` 里
#: "理由里刻意不写行号"是与它同一条纪律的另一面。
#:
#: 2026-10-24 起行号来源有了：`review_document` 先把被审的论文正文读进来
#: （`read_paper_body`：`out/paper/main.tex`，退到 `main.pdf` 的文本层），
#: 那份正文连同它的行号一起进 `scan_document` ⇒ `_line_of` 能把每条发现的逐字引文
#: 定位到正文的某一行。此前这里写的是"审校是纯函数、只读 `documents` 那一行，
#: 没有行号来源" —— 那句话在业主裁定「H 审论文，`documents` 只是它的登记行」之后
#: 已经不成立了，所以去掉。仍然有 `None` 的那一档只剩两种情形（本串逐字写明它们）：
#: 本次没读到正文（三态第三态，见 `read_paper_body`），或这条发现的引文在那份正文里
#: 逐字找不到。加上 G11 的冻结结论还没有接进本产出方（`draft/28` §96.3 第 2 条）。
_LINE_UNAVAILABLE_REASON = (
    "本次拿不到行号：这条发现的逐字引文在被审论文正文里定位不到"
    "（本次没读到正文，或那句话不在正文里逐字出现）；"
    "且 `P-9` 的口径是「行号只有在版本冻结（G11）之后才有意义」，"
    "而 G11 的冻结结论还没有接进本产出方（`draft/28` §96.3 第 2 条）"
)


def _verbatim_quote(seed: Any) -> str:
    """把触发这条发现的正文截成 ≤20 词的逐字引文（`X-96.3-1`）。
    
    两条口径都不在本文件另造：
    
    * 词数口径 = `gates._quote_word_count`（中文按字、英文按空白切词）。`schema.ReviewFinding.validate()` 读的也
    是它 —— 各写一份必然漂移，而漂移的表现是"写入期说 20 词、门说 21 词"。惰性引用私有名与`schema.py` 里那处 
    `from .gates import AXES, _quote_word_count` 同形。* 上限 = `draft/17` §8.4 的"≤20 词逐字引文"。
    
    截口用省略号标出：不重写、不概括 —— 引文一旦被改写就不再是"逐字"，而 G10 要的正是"你看到的那句话长什么样"。空种子返回空串（调用方保证非空；真为空说明这一行里连
    定位符都没有）。
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
    
    这个构造函数存在的唯一理由是只有一处补齐逻辑（FC-03）：四键写在十几个`findings.append` 里，下一次改声明表就会漏掉其中几处，而漏掉的表现是 G10 对
    部分发现报 `unknown` —— 比全缺更难发现。
    
    `quote` 是"这条发现指向的那段正文"（逐字取自本次输入；断言 → 它的正文，依赖 → 它的标签，拿不到就退到 `target` 一类逐字存在的定位符）。
    
    `line` / `line_reason`（`FINAL-R5-05`）：行号只有产出方拿得到带行号的正文时才给得出；`scan_document` 的输入是结构化的 
    `claims`/`dependencies`，正常没有正文，所以默认 `line=None` + 受控理由串。给了 `line` 时理由串留空。
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


def _locate_quote(text: str, quote: Any) -> int | None:
    """在正文里定位一条发现的逐字引文，返回 1 起行号（找不到 ⇒ None）。

    比 `_line_of` 多两道判据，两道都是被真实数据逼出来的：

    1. 引文可能是被截过的（`_verbatim_quote` 超过 20 词时以 "…" 收尾）—— 那个省略号
       不在正文里，原样去找必然找不到。所以先去掉省略号再找；
    2. 引文进 `_verbatim_quote` 时连续空白被压成一个空格（`" ".join(text.split())`），
       而正文是 LaTeX：一句话可能跨行、行内也可能有连续空格。所以第二遍按"空白不敏感"
       的形态找：把正文压成单空格串、同时记住每个字符属于第几行，再在这条压平串上
       `find`，命中的位置直接翻译回行号。

    两遍都找不到才返回 `None`（调用方据此给"行号拿不到"的第三态与理由串）——
    不会因为"这一句长了点"就把整条发现的行号判死。
    """
    raw = str(quote or "").strip()
    if not (text or "") or not raw:
        return None
    direct = _line_of(text, raw)
    if direct is not None:
        return direct
    needle = raw.replace("…", "").strip()
    if not needle:
        return None
    direct = _line_of(text, needle)
    if direct is not None:
        return direct
    flat: list[str] = []
    owners: list[int] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        words = line.split()
        if not words:
            continue
        for word in words:
            flat.append(word)
            owners.extend([lineno] * len(word))
            flat.append(" ")
            owners.append(lineno)
    haystack = "".join(flat).rstrip()
    pos = haystack.find(" ".join(needle.split()))
    if pos < 0 or pos >= len(owners):
        return None
    return owners[pos]


# ---------------------------------------------------------------- 被审对象：论文正文
#
# 业主 2026-10-24 裁定（逐字）：「只对论文负责是正确的，documents等都是中间产物」，
# 并已确认：「H 审论文（out/paper/main.tex / pdf），documents 只是它的登记行」。
#
# 所以本模块的审校对象是论文正文，不是 `documents` 那一行：
#   * 正文优先读 `<项目根>/out/paper/main.tex`；没有 tex 就退到 `main.pdf` 抽出的文本；
#   * 两者都没有（或读不出来、或读出来是空的）⇒ 三态里的第三态：
#     `checked=False` + 逐字理由，不许折成 `accepted`（"没审到"不是"审过、没问题"）；
#   * 正文连同它的行号一起进 `scan_document`（`_line_of` 因此有行号来源）；
#   * `documents` 那一行仍然是中间产物：审完只改它的 `status`（现状保留），
#     本次审的正文 sha256 记进读数（`paper_body`）与本轮 `reason`，可追溯。
#
# 论文包的落点不在这里另写一份：`papercompile.package_dir` / `TEX_NAME` / `PDF_NAME`
# 就是"论文包在哪、正文叫什么"的唯一声明面（`draft/142` 之后 `out/paper/` 是那个包）。

#: 被审正文的来源档（读数 `paper_body["source"]` 的取值域；空串 = 没读到正文）。
#: 两个来源档必须分得开：同一句话在 tex 与 pdf 抽取文本里的行号本来就不是一回事。
PAPER_SOURCES: tuple[str, ...] = ("tex", "pdf")


def _checked_paper_reading(reading: dict) -> dict:
    """正文读数的唯一出口：顺手把 `source` 的取值域钉住（声明与实现对齐的自检）。

    为什么值得一行断言：`source` 决定"这个行号是 tex 的行号还是 pdf 抽取文本的行号"，
    而这两者混起来没有任何下游会报错 —— 它只会让行号变成一句假精确。
    """
    source = str(reading.get("source") or "")
    if source not in ("",) + PAPER_SOURCES:
        raise ValueError(
            f"正文读数里的 source={source!r} 不在 {PAPER_SOURCES} 里（空串 = 没读到正文）"
        )
    return reading


def read_paper_body(project_root: Any) -> dict:
    """读本次要审的论文正文，返回带行号、字节数与 sha256 的读数（三态）。

    返回的键（不含正文本身 —— 正文 25 KB，塞进工具返回值会把上下文烧光）：

    - `checked`：这一趟有没有真的拿到一份可审的正文；
    - `source`：`"tex"` / `"pdf"` / `""`（从哪一份读的；空串 = 没读到）；
    - `path`：相对项目根的 posix 路径（没读到就是该找而没找到的那个路径的说明）；
    - `sha256`：盘上那份文件的字节 sha256（唯一口径 = `papercompile.file_digest`，
      不做任何规范化 —— 与 `COMPILE-RECEIPT.json` 的 `tex_sha256` 同一把尺子）；
    - `bytes` / `lines` / `chars`：字节数、行数、字符数（`lines` 就是本次交给
      `scan_document` 的那份正文的行数，行号以它为准）；
    - `text`：正文本身（只有本函数与它的调用方看得见，不进读数）；
    - `reason`：没读到时的逐字理由（读到了就是空串）。

    PDF 那一档的行号是抽取出来的文本的行号（不是 PDF 的页/行），读数里
    `source="pdf"` 就是这句限定：同一句话在 pdf 与 tex 里的行号本来就不是一回事，
    所以两个来源档必须分得开（折平它会让"行号"变成一句假精确）。

    三态纪律（与 `dep_check` / `semantic_check` 同形）：读不到 ⇒ `checked=False`
    + 理由；绝不返回一个空正文却让 `checked=True`（那会被下游读成"审过、干净"）。
    """
    root = Path(str(project_root))
    from .. import papercompile as PC

    package = PC.package_dir(root)
    rel_dir = "/".join(PC.PACKAGE_REL)
    reading = {
        "checked": False,
        "source": "",
        "path": f"{rel_dir}/{PC.TEX_NAME}",
        "sha256": "",
        "bytes": 0,
        "lines": 0,
        "chars": 0,
        "text": "",
        "reason": "",
    }

    tex = package / PC.TEX_NAME
    if tex.is_file():
        try:
            raw = tex.read_bytes()
        except OSError as e:
            reading["reason"] = (
                f"没有可审的论文：{rel_dir}/{PC.TEX_NAME} 在盘上，但读不出来"
                f"（{type(e).__name__}: {e}）"
            )
            return _checked_paper_reading(reading)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            reading["reason"] = (
                f"没有可审的论文：{rel_dir}/{PC.TEX_NAME} 读出来了，但不是 UTF-8"
                f"（{e}）⇒ 这一份正文我方判不了行号"
            )
            return _checked_paper_reading(reading)
        reading.update(
            checked=bool(text.strip()),
            source="tex" if text.strip() else "",
            path=f"{rel_dir}/{PC.TEX_NAME}",
            # 字节 sha256 与回执里的 `tex_sha256` 同一口径（同一份实现）。
            sha256=PC.file_digest(tex),
            bytes=len(raw),
            lines=text.count("\n") + 1 if text else 0,
            chars=len(text),
            text=text,
        )
        if not reading["checked"]:
            reading["reason"] = (
                f"没有可审的论文：{rel_dir}/{PC.TEX_NAME} 在盘上，但它是空的 ⇒"
                "这一趟没有正文可审（不是『审过、没问题』）"
            )
        return _checked_paper_reading(reading)

    pdf = package / PC.PDF_NAME
    if pdf.is_file():
        try:
            from ..extract import extract_text

            got = extract_text(pdf)
            text = str(getattr(got, "text", "") or "")
        except Exception as e:  # noqa: BLE001 —— 抽不出来是"没查成"，如实带回
            reading.update(
                path=f"{rel_dir}/{PC.PDF_NAME}",
                reason=(
                    f"没有可审的论文：{rel_dir}/{PC.PDF_NAME} 在盘上，但正文抽不出来"
                    f"（{type(e).__name__}: {e}）"
                ),
            )
            return _checked_paper_reading(reading)
        reading.update(
            checked=bool(text.strip()),
            source="pdf" if text.strip() else "",
            path=f"{rel_dir}/{PC.PDF_NAME}",
            sha256=PC.file_digest(pdf),
            bytes=int(pdf.stat().st_size),
            lines=text.count("\n") + 1 if text else 0,
            chars=len(text),
            text=text,
        )
        if not reading["checked"]:
            reading["reason"] = (
                f"没有可审的论文：{rel_dir}/{PC.PDF_NAME} 在盘上，但它没有文本层"
                "（抽出来的正文是空的）⇒ PDF 那一档也审不了"
            )
        return _checked_paper_reading(reading)

    reading["reason"] = (
        "没有可审的论文："
        f"{rel_dir}/{PC.TEX_NAME} 与 {rel_dir}/{PC.PDF_NAME} 都不在盘上"
        "（项目根下这个论文包里没有正文）⇒ 这一趟**没有可审的论文**，"
        "不是『审过、没问题』；先让 G 写出正文再让 H 审"
    )
    return _checked_paper_reading(reading)


#: 读数里带的正文档位（`read_paper_body` 的返回里能进工具返回值的那些键）。
_PAPER_READING_KEYS: tuple[str, ...] = (
    "checked", "source", "path", "sha256", "bytes", "lines", "chars", "reason",
)


def paper_reading(paper: Mapping[str, Any]) -> dict:
    """把 `read_paper_body` 的返回压成读数（去掉正文本身）。

    为什么必须去掉 `text`：正文 25 KB，`review_document` 的返回值会进模型的上下文，
    把正文塞进去等于每审一次就多烧一次全文的 token —— 而模型要看的是读数。
    """
    return {k: paper.get(k) for k in _PAPER_READING_KEYS}


def _body_text_of(paper: Mapping[str, Any]) -> str:
    """一份正文读数里"能不能审"的判据只有一处：拿到了、且不是空白。"""
    return str(paper.get("text") or "") if paper.get("checked") else ""


def _blank(text: str) -> bool:
    """正文"没有可审的字"的判据（`not text.strip()` 的等价形式）。

    等价性：对 `str` 而言 `.strip()` 得空串 ⇔ 要么本来就是空串、要么每个字符都是空白
    （`str.isspace()` 的定义就是"非空且全为空白"）。正文可能有几十万字符，
    `.strip()` 会为问这一句整份拷一份字符串；`isspace()` 只扫一遍、不分配。
    """
    return not text or text.isspace()


# ---------------------------------------------------------------- 纯函数判据


def scan_document(
    doc: Mapping[str, Any],
    *,
    dependencies: Sequence[Mapping[str, Any]] | None = None,
    semantic_judge: SemanticJudge | None = None,
) -> dict:
    """对一份稿件做全量机械审校。纯函数，不碰存储。
    - `unsupported_claim` —— 断言无引用；- `overclaim` —— `evidence_kind != "proof"` 却出现证明性措辞，或`cross_check` 缺 disclaimer；- 
    `missing_negation_kind` —— 否定型断言未分类；- `dangling_dep` —— 该稿件登记的依赖里有 `dangling` / `external_unavailable` 的（这是 FC-23 的落
    地：引用了拿不到的定理，必须是一条可见的发现，而不是藏在引文角标里）；- `inconsistent_number` —— 同一份稿件里同一个 claim_key 出现互相矛盾的数字（当前版本只检查「同一 claim_id 重复出现
    且 text 不同」，这是可判定的那一层）。
    三态：`dependencies=None` ⇒ `dep_check.checked=False`（没查），与「查了、依赖都闭合」（`checked=True, findings=[]`）严格区分。
    `semantic_judge=None` ⇒ `semantic_check["checked"] is False`（没接线，同样是没查），与「判过、都说一致」严格区分（`R-42`：措辞级判据抓不住"措辞干净但结论强于引文"）。
    `verdict` 的受控词与分档顺序（必须与写入路径 `review_document` 完全一致）：
    | 条件 | verdict ||---|---|| 有 error 级发现 | `rejected` || 无 error，但 `dep_check.checked is False` | `unverified`（不是
    accepted） || 无 error、依赖查过、有 warning | `accepted_with_warnings` || 无 error、依赖查过、无 warning | `accepted` |
    为什么"没查依赖"要单独占一档：把它并进 `accepted` 会让"我们从未检查"伪装成"检查通过"；并进 `rejected` 又会把"没做"说成"做失败了"。
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
    # 这一格只覆盖"稿件有没有把自己说清楚"（引用/证据档位/否定分类/字段合规），
    # 不覆盖"数学对不对" —— 后者的判据是 proof 级证据（FC-22），要另给。
    # 说清这一点是覆盖率可被信任的前提：一个声称"我审过全部断言"的自动审校器
    # 会被读成"数学被验过了"，那不是本函数做的事。
    claims_total = len(claims)
    reviewed = 0
    decided = 0
    seen_ids: dict[str, str] = {}
    # 用词上限（`doc_tools.wording_ceiling`：`proof` 永远到顶，Lean 开关关掉时
    # `proof_review` 也到顶 —— 业主 2026-10-12：「没 Lean 也要能写论文」）。
    # 它只读 `settings.lean_enabled()`（纯读，本函数体内不写任何全局态），
    # 同一个 `scan_document` 调用里每次读到的都是同一个元组 ⇒ 提到循环外算一次。
    # 读不到（工具层不可导入 / 设置文件写坏）时按最保守（只有 proof），与改前逐字相同。
    try:
        from .doc_tools import wording_ceiling

        _ceiling = tuple(wording_ceiling())
    except Exception:  # noqa: BLE001 —— 工具层读不到就按最保守（只有 proof）
        _ceiling = ("proof",)
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
        # ---- 证据档位是否合法（与 `doc_tools.scan_claim:217-224` 对齐）
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
                    message=f"证据档位必须是 {S.EVIDENCE_KINDS} 之一",
                    quote=repr(ek),
                )
            )
        # ---- 过度声称（用词上限的唯一实现在 `doc_tools.wording_ceiling`：`proof` 永远到顶，
        # Lean 开关关掉时 `proof_review` 也到顶 —— 业主 2026-10-12：「没 Lean 也要能写论文」）
        if ek in ("cross_check", "proof_review") and not str(c.get("disclaimer") or "").strip():
            want = ("数值交叉验证，不构成证明" if ek == "cross_check"
                    else "逐行审阅过的证明，未经机器检查")
            findings.append(
                _finding(
                    "overclaim",
                    level="error",
                    target=cid,
                    evidence=f"evidence_kind={ek!r} 且 disclaimer 为空",
                    message=f"这一档必须显式声明「{want}」",
                    quote=text or cid,
                )
            )
        if ek in S.EVIDENCE_KINDS and ek not in _ceiling:
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
    # 上面那个循环用 `OVERCLAIM_MARKERS` 逐词匹配 —— 只能抓"把交叉验证说成证明"这类写在脸上的形态。
    # 抓不住的是：措辞干净（没有 `证明`/`定理`），但结论强度确实超过引文能支撑的范围（引文只做了 n=3 的
    # 数值检查，断言写成一般性结论）。那一层要读语义，只有 LLM 或人能判。
    # 本框架默认零 LLM 调用 ⇒ 这里默认没查。三条纪律：① 没接线时 `checked=False` + 逐字理由，不许折成
    # "没问题"（与 `dep_check` 同形）；② 判据答 `unknown` 也不算查过（`claims_unknown` 单独计数）；③ 判据
    # 自己抛异常/返回不合法 ⇒ `checker_errors += 1` + 一条 warning 级 `garbled`（检查器没跑成不是稿件的错，
    # 但绝不能静默）。
    # 为什么定 warning 而不是 error：措辞级那条机械可判（error 站得住），语义判定来自一个可能犯错的判据 ——
    # 判错一次就会把合格稿件判成 `rejected`；定 warning 让它可见（`accepted_with_warnings`）而不越权。
    # 要不要升到 error 是口径问题（FC-27 的 `eval-criteria` 类）⇒ 留给人裁。
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
        # `dependencies` 的声明类型就是 `Sequence`（见签名）⇒ 直接取长度，
        # 不再为问一句"几条"把整份清单拷成一个 list（拷贝只服务这一句 str 插值）。
        dep_check = {"checked": True, "reason": f"检查了 {len(dependencies)} 条依赖", "open": open_deps}

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
    elif not bool(semantic_check.get("checked")):
        # 2026-10-17（业主：「通过标准和 V 一样」）：「语义层没查 ⇒ 不许判通过」。
        # 真机 t5e（`t5e-5`）现场：`semantic_check.checked=false`（没接线）却落了
        # `verdict=accepted`，于是审核轴被写成「成立」—— 把"没查"说成了"通过"。
        # 这一档与"依赖闭合没查"是同族，统一记 `unverified`（就是「没查成」那一档：
        # 不写裁决、checked=False；业主 2026-10-30 已取消「看不出来」）。
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
                located = _locate_quote(doc_text, f.get("verbatim_quote"))
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
            "`claims_reviewed` = 逐条字段/引用/证据档位检查真的跑过的断言数；"
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


def _advance_review_round(
    store: Any, doc_id: str, *, explicit: int | None = None, actor: str = "agent-H",
) -> tuple[int, str | None]:
    """H 做了一次复审 ⇒ `documents.review_rounds` +1（轮次账的唯一来源）。

    ## 为什么轮次必须跟着「复审」走（甲，2026-11-11 业主裁定）

    真机读数（`projects/dct-min6-20261111`）：`documents.review_rounds` 恒 2，而 H
    事实上复审过很多趟 —— 因为此前只有 `G.revise` 会 +1，而真机上 G 常常用
    `fs.edit` 改稿（不经过 `revise`）。于是"复审收过几次"这个读数与事实脱钩。

    现在的口径（全仓一份）：
      * `documents.review_rounds` = 第几轮复审。只有 H 的复审入口推进它
        （`review_document` / `verify_fixes`）；
      * `findings.round` = 这条判词是第几轮记的。同一轮取证时它必须等于当时的
        `documents.review_rounds`；
      * `record_finding` 不再自己 `max(round)+1` 造轮次（那就成了第二套轮次）。
        它盖的是当前 `review_rounds`（见 `record_finding` 里那段注释）。

    ## `explicit` 是什么（为什么不是第二个轮次来源）

    `review_document.round_no` 是可选的、`verify_fixes.round_no` 是必填的 —— 保留它们
    是为了断点续跑与旧调用的形状。这里把它当下限：正常流程（H 不传 / 传的正是
    下一轮）下 `new = cur + 1`；若调用方声明了一个更靠后的轮次（中断后接着跑），
    以它为准并让盘上的账对齐到它 —— 于是落盘之后 `documents.review_rounds`
    与这一轮判词的 `round` 永远相等。

    返回 `(这一轮的轮次, 写库失败原因或 None)`。`documents` 行不存在时（论文是真身、
    台账行缺失那一路）返回算出来的轮次且不写库 —— 那一缺由调用方在 reason 里如实报。
    """
    row = next(
        (r for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)), None)
    current = int(dict(row).get("review_rounds") or 0) if row is not None else 0
    new_round = current + 1
    if explicit is not None:
        new_round = max(new_round, int(explicit))
    if new_round < 1:
        new_round = 1
    if row is None:
        return new_round, f"documents 里没有稿件 {doc_id} ⇒ 轮次账没写回（只带读数）"
    try:
        with store.tx("documents", actor=actor,
                      note=f"review round {current}->{new_round}") as tx:
            live = tx.find("documents", doc_id=str(doc_id))
            if live is None:
                return new_round, f"稿件 {doc_id} 在事务内不存在 ⇒ 轮次账没写回"
            live["review_rounds"] = new_round
            tx.upsert("documents", live)
    except Exception as exc:  # noqa: BLE001 - 轮次账坏掉要如实报，不许静默
        return new_round, f"{type(exc).__name__}: {exc}"
    return new_round, None


#: 受控码：置 `accepted` 却没有"钉住被接受的是哪一版"的签名 ⇒ 拒绝写这一档
#: （不是静默置 accepted）。口径同 `verify_fixes` 的 `R-59`：
#: `accepted` 必须由一条 `signatures.signed_revision` 非空的签名背书。
CODE_ACCEPT_WITHOUT_PIN = "accept_without_pin"


def _accept_refusal(store: Any, doc_id: str, row: Mapping[str, Any]) -> str:
    """置 `accepted` 的收口：返回受控拒的理由；`""` = 可以写。

    判据用 `signatures.signed_revision`（不许用 `signed()`）：后者对非 `accepted`
    的稿件一律返回真（草稿本来就不该被签），拿它来判会恰好放过这一格
    （`verify_fixes` 的 `R-59` 用的就是同一条判据）。`content_sha256` 为空同样拒：
    `schema.Document.validate` 对 accepted 也有这一条（审批是对某一版的审批）。
    """
    from .. import signatures as SIG

    sha = str(row.get("content_sha256") or "").strip()
    if not sha:
        return (f"受控拒[{CODE_ACCEPT_WITHOUT_PIN}]：稿件 {doc_id} 没有 content_sha256 ⇒ "
                "钉不住被接受的是哪一版；状态未改")
    root = getattr(store, "root", None) or "."
    recs, bad = SIG.read_ledger(SIG.ledger_path(root))
    if SIG.signed_revision(row, recs) is not None:
        return ""
    return (f"受控拒[{CODE_ACCEPT_WITHOUT_PIN}]：拒绝把稿件 {doc_id} 置 accepted —— "
            f"签名台账里没有签名钉住当前这一版（content_sha256={sha[:16]}…）"
            + (f"；台账有坏行：{bad[0]}" if bad else "")
            + "。先让 H 走 `review` 签发（接受 = 有一次针对这一版的审+签）")


def _set_doc_status(
    store: Any,
    doc_id: str,
    target: str,
    *,
    actor: str,
    review_verdict: str = "",
    review_checked: bool = False,
    review_reason: str = "",
    pin: Callable[[dict], None] | None = None,
) -> tuple[bool, str | None, str]:
    """只改 `documents` 行的 `status` 字段，并按调用方给的结论写审核轴。

    返回 (是否写成, 错误, 当前状态)。

    ## `accepted` 的收口：钉版先于提交（`pin` 回调）

    任何把 status 置 `accepted` 的写口都走这里，所以"接受"与"钉住被接受的是哪一版"
    必须在这里合流：`pin` 由调用方给（`review_document` 传它的签发动作），在
    状态事务内、写 status 之前执行；随后 `_accept_refusal` 复读台账确认
    `signatures.signed_revision` 非空。钉不上 ⇒ 受控拒（`CODE_ACCEPT_WITHOUT_PIN`），
    status 一个字节不改 —— 不许静默置 accepted（改前正是这个形态：状态先提交、
    签名后写，签名失败只回报 `signature_error` ⇒ 留下"accepted 但没钉住"）。

    ## 审核轴不再从 status 推

    改前这里按 status 反推裁决（`in_review` ⇒ 有毛病、其余 ⇒ 看不出来）。那是把
    「这一维没查」折成一条裁决 —— 最贵的一种折平（业主 2026-10-30：「不应该有
    『看不出来』」）。现在 status 只表生命周期，裁决由调用方按这一轮真实的结论
    显式传进来：只有 `review_checked=True` 才写 `review_verdict` / `reviewed_at` /
    `reviewed_by`；没查成时这三格一个字节都不写（台账不留行），理由由调用方带回去。

    ## 为什么只改 status，连 `updated_at` 都不碰

    "H 只读"必须有一个可核对的形式：调用前后逐字节比对 `documents.json`，变化点应当有且只有 status（加审核轴三格）。
    顺手更新 `updated_at` 看起来无害，
    但它会让"H 到底动了什么"从"一眼看清"退化成"要逐字段 diff 才知道"。

    ## 为什么这个写会失败（而且必须如实报告）

    `Document.validate` 会在提交时校验整张 documents 表。若盘上这份稿件本身不合 schema（例如是手工改坏的、或旧版本写的），那么连"把它的状
    态改成 in_review"都写不进去。这不是可以掩盖的细节：发现照样落库，状态更新失败这件事本身也要出现在返回值里，否则调用方会以为"审校流程正常结束了"。
    """
    if review_checked and (not review_verdict or review_verdict not in S.REVIEW_VERDICTS):
        # 调用方说"查过了"却没给一个合法裁决 ⇒ 程序错误，当场抛（不许静默写成空串）。
        raise ValueError(
            f"review_checked=True 时 review_verdict 必须是 {S.REVIEW_VERDICTS} 里的非空值，"
            f"收到 {review_verdict!r}"
        )
    if not review_checked and not str(review_reason or "").strip():
        # 「没查成」也要有理由：否则"没审过"与"查了但没查成"在回执上同形。
        raise ValueError(
            "review_checked=False（没查成）必须给非空 review_reason —— "
            "这一档不写裁决，理由是它在回执里唯一的读数"
        )
    cur_row = next(
        (dict(r) for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)),
        None,
    )
    cur = str((cur_row or {}).get("status") or "")
    if cur == target:
        # 已经 accepted 的稿子再 review 一次照旧签一条（`pin` 在，就再钉一次这一版）；
        # 钉不上时如实拒（读到的是"终态未落全"，不是一次成功的接受）。
        if target == "accepted" and pin is not None and cur_row is not None:
            pin(cur_row)
            why = _accept_refusal(store, doc_id, cur_row)
            if why:
                return False, why, cur
        return True, None, cur
    try:
        with store.tx("documents", actor=actor, note=f"review status {cur}->{target}") as tx:
            row = tx.find("documents", doc_id=str(doc_id))
            if row is None:
                return False, f"稿件 {doc_id} 在事务内不存在", cur
            if target == "accepted":
                if pin is not None:
                    pin(row)   # 钉版：签名要钉住的就是下面这一版（写 status 之前落台账）
                why = _accept_refusal(store, doc_id, row)
                if why:
                    return False, why, cur
            row["status"] = target
            # 2026-10-17（业主：「「H 审过和通过是完全不同的状态」」）：状态被审校推到某一档时，
            # 同一次事务里把「审核轴」写上 —— 于是两件事分得开：
            #   审过 = `review_verdict != ""`；通过 = `review_verdict == "成立"`（与 V 的裁决同形）。
            # 这一笔是 `closing.accepted_documents` 唯一的数据来源。
            from datetime import datetime as _dt

            # 2026-10-30（业主裁定，2026-11-04 施工单）：H 的「看不出来」不是第三态。
            # 没查成 / 没结论 ⇒ 不写裁决（这三格一个字节都不动），`checked=False` +
            # 理由由调用方带回；只有真判出了结论才写两态之一。
            if review_checked:
                row["review_verdict"] = str(review_verdict)
                row["reviewed_at"] = _dt.now().astimezone().isoformat(timespec="seconds")
                row["reviewed_by"] = str(actor or "agent-H")
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
                # 来源标记属于 finding 的身份，不属于状态：手工判词的 `resolution_note`
                # 只追加、不整格覆写（判据在 `_note_after_status_update` 里，只有一处）。
                row["resolution_note"] = _note_after_status_update(
                    row, str(ch["resolution_note"]))
            tx.upsert("review_findings", row)
            done.append({"finding_id": row["finding_id"], "status": row["status"]})
    return done


def _dedup_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """去重键：`(kind, target, message)`（doc_id 在调用处限定）。"""
    return (str(row.get("kind")), str(row.get("target")), str(row.get("message")))


def _supersede_prior_open(
    tx: Any,
    existing: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    target: str,
    new_round: int,
    new_id: str,
) -> list[dict]:
    """乙（2026-11-11 业主裁定）：同一处的旧判词被更晚的新判覆盖（`superseded`）。

    语义边界（施工单逐条）：
      * 只在 `kind` 与 `target` 逐字完全相同时覆盖 —— target 差一个字都不算同一处
        （真机上同一处常被写成不同措辞，那是"同一处的两条"还是"两处"由人裁；
        本实现刻意只认逐字相同，粒度问题写在交付报告里）；
      * 只在更晚的轮次（`round < new_round`）覆盖 —— 同一轮里记的两条是并存的判词；
        （实现上写的是 `旧 round != 本轮 round`：真机老行的 round 是旧的 max+1 口径
        `max+1` 摊出来的 1..12，可能比新的 `review_rounds` 还大 —— 例如拷贝上
        `review_rounds=3` 而老判词 round=12。老行不可能是"将来某一轮"记的，所以
        "round 不同"就等价于"它是更早一次写入"；"round 相同"才是同一轮并存。）
      * `fixed` / `wontfix` / `disputed`（以及已是 `superseded` 的）不被覆盖：
        已了结的不动（g）；这里只动 `status == "open"` 的；
      * 不是删除：原文、轮次、证据、resolution_note 一个字不改，只加状态与指针；
      * `open` 的判定仍只看 `status == "open"` ⇒ 覆盖之后 open 数下降（e）。

    在调用方的事务里执行（与"写新判词"同一笔，避免出现"新的落了、旧的还 open"的中间态）。
    返回被覆盖的读数 `[{finding_id, round, superseded_by}]`（与 finding 的落库值同源）。
    """
    changed: list[dict] = []
    # 四个取值都只依赖入参（循环里没有任何东西改写它们）⇒ 循环外算一次。
    # 改前每一行都重算一遍 `str(kind)` / `str(target)` / `str(new_id)` / `int(new_round)`，
    # 而 `review_document` 是"每条新发现调一次本函数" ⇒ 同一批 `existing` 被扫 N 趟。
    kind_s, target_s = str(kind), str(target)
    new_id_s, new_round_i = str(new_id), int(new_round)
    for row in existing:
        if str(row.get("kind") or "") != kind_s:
            continue
        if str(row.get("target") or "") != target_s:
            continue
        if str(row.get("status") or "") != "open":
            continue
        rid = str(row.get("finding_id") or "")
        if not rid or rid == new_id_s:
            continue
        if int(row.get("round") or 1) == new_round_i:
            # 同一轮记的两条是并存的判词（都不覆盖对方）；不同轮 = 更早一次写入。
            # 为什么不写 `>=`：真机老行的 round 是旧的 max+1 口径（1..12），会比新的
            # `documents.review_rounds` 还大 —— 那些行仍然比"这一次写入"更早。
            continue
        live = tx.find("review_findings", finding_id=rid)
        if live is None:
            continue
        live["status"] = "superseded"
        live["superseded_by"] = new_id_s
        tx.upsert("review_findings", live)
        changed.append({"finding_id": rid, "round": int(live.get("round") or 1),
                        "superseded_by": new_id_s})
    return changed


# ---------------------------------------------------------------- 手工判词（P2-4）
#
# 现场（`projects/dct-min4-20261111`）：7 条 `record_finding` 落的手工判词全 `open`，而
# `verify_fixes` 的 resolved 判据是「上一轮的 key 不在本轮 scan 结果里」—— 手工判词的 key
# 是散文，永远不会出现在 scan 结果里 ⇒ 只要 H 跑一次 `verify_fixes`，这 7 条会被全部判成
# `fixed`，而一条检查都没重跑。那是把「没查」写成「修好了」，与 `R-04-b` 同一族。
#
# 本节的判据：「手工判词不许被自动复跑判掉」。
#   * 来源标识属于 finding 的身份，不属于状态：`record_finding` 落库时把
#     `MANUAL_FINDING_NOTE_PREFIX` 写进 `resolution_note`（既有自由文本字段，不进去重键、
#     不是审校内容；`schema` 在 FC-27 禁改区，本批「不加列」），而状态写口只许追加
#     （`_note_after_status_update`）—— 真机上就是 `_apply_finding_status` 的整格覆写
#     把它吃掉的（`projects/lp-ball` 000000 / 000002）；
#   * 离场只有一条路：H 自己显式复核 —— 以同一个去重键再登记一次，`evidence` 以
#     `RECHECK_FIXED_PREFIX` / `RECHECK_WONTFIX_PREFIX` 开头，把结论（fixed / wontfix +
#     理由）写进同一个 finding_id 的 `resolution_note`。为什么走 `evidence` 而不加参数：
#     工具声明面被两份冻结快照钉住，加参数就必须重冻 golden（FC-27，本批未获授权）；
#   * `verify_fixes` 读这两个标记：未显式复核的手工判词留在 `open`（读数进
#     `not_rechecked`，`source="manual_not_rechecked"`），已显式复核的不再被改写。
#: `record_finding` 落手工判词时写进 `resolution_note` 开头的来源标记。
MANUAL_FINDING_NOTE_PREFIX = "[manual] "
#: `resolution_note` 里"H 显式复核过这一条"的标记（由 `record_finding` 的复核通道写）。
MANUAL_RECHECK_MARK = "[H 复核] "
#: 显式复核的两个受控前缀（H 写在 `record_finding.evidence` 的开头）：
#: `复核 fixed：<理由>`（H 重新判过、这一条不再成立）/
#: `复核 wontfix：<理由>`（H 显式放弃，理由必填）。
RECHECK_FIXED_PREFIX = "复核 fixed："
RECHECK_WONTFIX_PREFIX = "复核 wontfix："
#: 未显式复核时 `verify_fixes` 写回 `open` 的理由（逐字可查）。
MANUAL_NOT_RECHECKED_NOTE = (
    "手工判词（`review.record_finding` 落的散文发现）**不能被自动复跑判掉**："
    "它的去重键不在机械 scan 的可产出集合里，「本轮没复现」不等于「H 复核过」。"
    "离场只有一条路：H 用 `review.record_finding` 以同一去重键再登记一次，"
    f"`evidence` 以 `{RECHECK_FIXED_PREFIX}` 或 `{RECHECK_WONTFIX_PREFIX}` 开头"
)


def _manual_origin_mark(row: Mapping[str, Any]) -> str:
    """`resolution_note` 里能证明「这条是 record_finding 落的手工判词」的那句原文（没有 ⇒ 空串）。

    ## 为什么来源标识单独成一个读口，而不是继续读「开头四个字符」
    来源标识属于 finding 的身份，不属于状态 —— 它一旦被某个写口覆写，这条判词就被
    永久地误认成机械发现：显式复核会拒它（"只对人工判词开放"），下一轮 verify_fixes
    又会把它当机械发现"没复现 ⇒ fixed"（不查就关）。两个方向都是错的，而唯一的开关
    就是这一格原文（真机 `projects/lp-ball` 的 000000 / 000002 就是被覆写之后两侧全错）。
    所以判定改成"这句话出现过没有"，而不是"它是不是还在开头"。

    ## 两种形态，都只有手工那条路会写
    1. `MANUAL_FINDING_NOTE_PREFIX`：record_finding 落库时写在头部；修好之后任何写口
       都不许把它吃掉（写侧判据是 `_note_after_status_update`）；
    2. `MANUAL_NOT_RECHECKED_NOTE`：verify_fixes 只对手工判词写的那句重开理由 ——
       2026-11-14 之前 `_apply_finding_status` 整格覆写，真机上 000000 / 000002 的头部
       前缀就是这样没的，只剩这一句能认出它们的来历。
    两种形态读的是同一格自由文本、都是本模块的受控常量，机械那一支一个字都不会写它们
    ⇒ 这不是第二套事实源，只是同一件事在盘上留下的两种残迹；第 2 种是给"修复之前
    已经落盘的损伤"的兼容读法，不许再往这张单子里加第三种。
    """
    note = str(row.get("resolution_note") or "")
    if MANUAL_FINDING_NOTE_PREFIX in note:
        return MANUAL_FINDING_NOTE_PREFIX
    if MANUAL_NOT_RECHECKED_NOTE in note:
        return MANUAL_NOT_RECHECKED_NOTE
    return ""


def _is_manual_finding(row: Mapping[str, Any]) -> bool:
    """这条发现是不是 record_finding 落的手工判词（来源标识出现过，见 `_manual_origin_mark`）。"""
    return bool(_manual_origin_mark(row))


def _note_after_status_update(row: Mapping[str, Any], new_note: str) -> str:
    """状态更新时 `resolution_note` 的新取值：手工判词的来源标识永不被覆写。

    判据只有一条：这一行有手工来历（`_is_manual_finding`）⇒ 追加，否则照旧替换。
    为什么是追加而不是"把前缀搬到开头再拼"：搬动会改写"谁在什么时候写了哪一句"的
    先后，而这一格是台账里唯一的判断理由；追加只做一件事 —— 新理由写在后、旧账一个字
    不丢。为什么机械行仍然替换：它们的这一格是"本轮为什么这么判"的读数，去重键在
    `kind/target/message` 三格、旧理由没有身份含义；替换也让这一格不随轮次无限增长。
    """
    old = str(row.get("resolution_note") or "").strip()
    if not old or not _is_manual_finding(row):
        return new_note
    return f"{old} {new_note}".strip()


def _manual_rechecked(row: Mapping[str, Any]) -> bool:
    """这条手工判词是否已被 H 显式复核过（fixed / wontfix 都算离场）。"""
    return _is_manual_finding(row) and MANUAL_RECHECK_MARK in str(row.get("resolution_note") or "")


def _recheck_verdict_of(evidence: str) -> tuple[str, str]:
    """`evidence` 的复核前缀 ⇒ `(verdict, reason)`；不是复核就是 `("", "")`。"""
    text = str(evidence or "")
    for verdict, prefix in (("fixed", RECHECK_FIXED_PREFIX),
                            ("wontfix", RECHECK_WONTFIX_PREFIX)):
        if text.startswith(prefix):
            return verdict, text[len(prefix):].strip()
    return "", ""


# ---------------------------------------------------------------- 审校（写发现）


def record_finding(
    store: Any,
    *,
    doc_id: str,
    kind: str,
    target: str,
    message: str,
    evidence: str,
    level: str = "warning",
    axis: str = "",
    suggestion: str = "",
    round_no: int | None = None,
    verbatim_quote: str = "",
    line: int | None = None,
    line_unavailable_reason: str = "",
    actor: str = "agent-H",
) -> dict:
    """把「H 自己读出来的」一条发现落成 `review_findings` 行（业主 2026-10-18 裁定）。
    ## 这是哪一条洞的修法（读数先于修法）
    `projects/mp3` 末节第 5 条那一类「面外操作」在 H 这一侧的同族形态是：`review_document` / `verify_fixes` 落的发现「全
    部来自机械扫描」（`scan_document`），而 H 自己读出来的那一条（「G8 回执没给退出码」「正文引用的那份材料盘上没有」）「没有任何落点」 —— 它只能写在回
    复或报告文件里。于是`review_findings` 里有的永远是机器算得出的那几类，人（角色）的判断进不了台账。
    ## 三条边界（与 `review_document` 同一套口径）
    1. 只写 `review_findings`：不改 `documents.status`（那是裁决那一档的事）、不碰任何知识表。改「稿件状态」需要走 
    `review_document` 的裁决路径 ——一审一判，不许用"补一条发现"顺手把状态挪一格。 2. 去重键仍是 `(kind, target, message)`（`_dedup_key`，
    全仓唯一一份）：同一条发现重复登记返回既有 `finding_id`（`created=False`），不制造重复行。 3. `evidence` 必填且非空：审校者的判断
    也要有依据（`schema.ReviewFinding` 的设计核心）。空 evidence 由 `validate()` 拒，这里不写第二份判据。
    ## 轮次：只读 `documents.review_rounds`，不再自己 `max(round)+1`（甲，2026-11-11）
    `findings.round` 是"第几轮记的判词"，而"第几轮"只由 H 的复审入口推进
    （`_advance_review_round`）。本工具不写 `documents`（写集只有 `review_findings`），
    所以它既不推进轮次、也不发明轮次：不给 `round_no` 时盖当前复审轮次
    （0 = 还没复审过的新稿 ⇒ 至少记 1，那条判词属于即将进行的第 1 轮）。旧调用显式
    给的 `round_no` 仍被尊重（断点续跑 / 旧夹具的形状），但正常 H 流程不传它。
    """
    doc_id = str(doc_id or "")
    doc_row = _doc_of(store, doc_id)  # 稿件不存在 ⇒  ValueError（不能给不存在的稿件落发现）
    kind_s, target_s = str(kind or ""), str(target or "")
    message_s, evidence_s = str(message or ""), str(evidence or "")
    level_s = str(level or "warning")
    axis_s = str(axis or "")
    # ---- G10 的 `maths` 那一格：按 kind 读同一张声明表（本批 ②） --------------------
    #
    # 现场（`projects/lp-ball`，2026-11-14）：11 条手工判词的 `maths` 全空 ⇒ G10 对
    # 任何 record_finding 产出恒红。根因是这一格没有输入通道：工具声明面里没有
    # `maths` 参数（加参数要动 `specs/h.py` 与两份 golden，FC-27），而
    # `schema.ReviewFinding.maths` 的默认值是空串。
    # 修法不是放宽 G10，也不是给"手工判词"另立一条判据：`_FOUR_GATE_KEYS_OF_KIND`
    # 已经按 kind 声明了 axis / maths / suggestion（机械那一支的 `_finding()` 就按它
    # 补齐），这里读同一张表 —— 一个 kind 的发现"要不要读断言本身才能判"只有这一处声明。
    # 表外 kind 走 `_FOUR_GATE_KEYS_FALLBACK`（今天走不到：表键恰好等于
    # `schema.FINDING_KINDS` 的 7 个取值，`ReviewFinding.validate()` 也会拒表外 kind）。
    maths_s = _FOUR_GATE_KEYS_OF_KIND.get(kind_s, _FOUR_GATE_KEYS_FALLBACK)[1]
    for name, value in (("kind", kind_s), ("target", target_s),
                        ("message", message_s), ("evidence", evidence_s)):
        if not value.strip():
            raise ValueError(
                f"record_finding：{name} 不能为空 —— "
                + {"kind": f"必须从受控词表 {S.FINDING_KINDS} 里挑一个",
                   "target": "要指明位置（claim-3 / section:2 / dep:0004）",
                   "message": "要写清这条发现说什么",
                   "evidence": "**审校者的判断也要有依据**：凭什么这么判"}[name]
            )

    existing = [dict(r) for r in store.rows("review_findings")
                if str(r.get("doc_id")) == doc_id]
    # ---- 甲（2026-11-11 业主裁定）：轮次只从 `documents.review_rounds` 来 -------------
    #
    # 这里原来是 `max(该稿已有发现的 round) + 1` —— 那是第二套轮次：真机
    # `projects/dct-min6-20261111` 上每落一条手工判词就把它推一格（12 条判词 ⇒
    # round 1..12），而 `documents.review_rounds` 恒 2，两套账互不相认。
    # 现在：不给 `round_no` ⇒ 记在当前复审轮次（0 只出现在"还没复审过"的新稿上，
    # 那一条属于即将进行的第 1 轮 ⇒ 至少 1）；给了 `round_no` ⇒ 以它为准（旧调用与
    # 断点续跑的形状；正常 H 流程不传）。不写 documents（本工具写集只有
    # `review_findings`），所以此处不推进轮次账。
    round_val = (int(round_no) if round_no is not None
                 else max(1, int(doc_row.get("review_rounds") or 0)))
    if round_val < 1:
        raise ValueError("round_no 从 1 开始")
    key = (kind_s, target_s, message_s)
    dup = next((r for r in existing if _dedup_key(r) == key), None)
    recheck_verdict, recheck_reason = _recheck_verdict_of(evidence_s)
    if recheck_verdict:
        # ---- H 的显式复核（P2-4 的唯一离场通道；见本节顶部那段注释）。
        if dup is None:
            raise ValueError(
                f"复核的对象不存在：稿件 {doc_id} 上没有去重键为 {key!r} 的发现 ⇒ "
                "显式复核只能针对**已经登记过**的发现（它是回执，不是新发现）"
            )
        if not _is_manual_finding(dup):
            raise ValueError(
                "显式复核只对**手工判词**（`record_finding` 落的发现）开放："
                "机械扫描产的发现由 `verify_fixes` 重跑对应检查判定，不许用这句话替它盖章"
            )
        if recheck_verdict == "wontfix" and not recheck_reason:
            raise ValueError(
                f"`{RECHECK_WONTFIX_PREFIX}` 必须带理由（显式放弃 = 说清为什么可以不改，"
                "与 `wontfix` 的 schema 硬要求同一条纪律）"
            )
        status_new = "fixed" if recheck_verdict == "fixed" else "wontfix"
        with store.tx("review_findings", actor=actor,
                      note=f"recheck doc:{doc_id} {dup['finding_id']} -> {status_new}") as tx:
            row = tx.find("review_findings", finding_id=str(dup["finding_id"]))
            if row is None:
                raise ValueError(f"发现 {dup['finding_id']} 在事务里读不到 ⇒ 复核不写库")
            row["status"] = status_new
            note_new = (
                f"{MANUAL_RECHECK_MARK}[round {round_val}] H 显式复核 ⇒ {status_new}"
                + (f"：{recheck_reason}" if recheck_reason else "")
            )
            row["resolution_note"] = (
                str(row.get("resolution_note") or "").strip() + " " + note_new
            ).strip()
            tx.upsert("review_findings", row)
        return {"checked": True, "created": False, "duplicate_skipped": 1,
                "finding_id": str(row["finding_id"]), "doc_id": doc_id,
                "kind": kind_s, "level": str(row.get("level") or level_s),
                "round": round_val, "status": status_new}
    if dup is not None:
        return {"checked": True, "created": False, "duplicate_skipped": 1,
                "finding_id": str(dup.get("finding_id") or ""), "doc_id": doc_id,
                "kind": kind_s, "level": str(dup.get("level") or level_s),
                "round": int(dup.get("round") or 1), "status": str(dup.get("status") or "")}
    with store.tx("review_findings", actor=actor,
                  note=f"record_finding doc:{doc_id} round {round_val}") as tx:
        row = S.ReviewFinding(
            finding_id="", doc_id=doc_id, kind=kind_s, level=level_s, target=target_s,
            evidence=evidence_s, message=message_s, round=round_val,
            suggestion=str(suggestion or ""), axis=axis_s, line=line,
            line_unavailable_reason=str(line_unavailable_reason or ""),
            verbatim_quote=str(verbatim_quote or ""),
            # ② G10 的 maths 那一格：没有输入通道，按 kind 从产出侧声明表读（见上面那段）。
            maths=maths_s,
            status="open",
            # P2-4：来源标记 —— 这条是 H 自己读出来的（不是机械 scan 的产物），
            # `verify_fixes` 因此不许拿「本轮 scan 里没有它」当「修好了」。
            resolution_note=(MANUAL_FINDING_NOTE_PREFIX
                             + "手工判词：H 自己读出来的发现（record_finding 落库）"),
            created_at=S.now_iso(), created_by=actor,
        )
        row.finding_id = tx.alloc_id("finding")
        row.validate()
        payload = row.to_dict()
        tx.upsert("review_findings", payload)
        # 乙（2026-11-11）：同一 (kind,target) 的更早 open 判词被这一条覆盖 ——
        # 与"写新判词"同一笔事务（见 `_supersede_prior_open` 的语义边界）。
        _supersede_prior_open(
            tx, existing, kind=kind_s, target=target_s,
            new_round=round_val, new_id=str(payload["finding_id"]))
    return {"checked": True, "created": True, "duplicate_skipped": 0,
            "finding_id": payload["finding_id"], "doc_id": doc_id, "kind": kind_s,
            "level": level_s, "round": round_val, "status": "open"}


def _open_findings_gate(*, existing: Sequence[Mapping[str, Any]],
                        reopened: Sequence[Mapping[str, Any]], round_no: int,
                        doc: Mapping[str, Any]) -> tuple[list[dict], dict[str, Any]]:
    """丙（2026-11-11）：「这一版还有没有 open findings」的判据 + 读数。

    返回 `(挡不挡, 读数)`：`挡不挡` 是这一版（盘上全部 finding 里）状态仍为
    `open` 的那些，含本轮刚重开的那几条；`读数` 的形状见下面 `reading`。

    为什么单独一格：收口侧（`review_document` 的 `target_status`）与判据侧
    （反真空把那一条摘掉 ⇒ 真机复现必须红）要用同一份判据；写在函数体里就打不了桩。
    它只读：不改 finding 的状态 —— 「要修的是产生矛盾的那一侧，不是把 findings 的
    状态改掉」（业主 2026-11-11）。
    """
    prior_open = [dict(r) for r in existing
                  if str(r.get("status") or "") == "open"]
    # 改前那一支写的是 `next((dict(r) for r in existing if ...), None)`：生成器会把
    # 命中之前扫过的每一行都先拷成 dict 再丢掉 —— 每个 rid 一份 O(N) 的拷贝。这里先
    # 只挑出那一行（不拷），命中之后才拷一次；`dict(row) not in prior_open` 与改前的
    # `row not in prior_open` 是同一次按内容比较（`row` 改前也只是那一行的副本）。
    for rid in {str(r.get("finding_id") or "") for r in reopened}:
        row = next((r for r in existing
                    if str(r.get("finding_id") or "") == rid), None)
        if row is None:
            continue
        copied = dict(row)
        if copied not in prior_open:
            prior_open.append(copied)
    reading = {
        "checked": True,
        "total": len(prior_open),
        "error": sum(1 for r in prior_open if str(r.get("level") or "") == "error"),
        "warning": sum(1 for r in prior_open if str(r.get("level") or "") == "warning"),
        "finding_ids": [str(r.get("finding_id") or "") for r in prior_open],
        "review_round": int(round_no),
        "review_rounds": int(dict(doc).get("review_rounds") or 0),
        "blocks_accept": bool(prior_open),
        "why": ("这一版没有 open findings" if not prior_open else
                f"还有 {len(prior_open)} 条 open findings 没被本轮复审收口"
                f"（{'、'.join(str(r.get('finding_id') or '?') for r in prior_open[:8])}）"),
    }
    return prior_open, reading


def _unreviewable_review(
    store: Any,
    doc_id: str,
    *,
    round_no: int | None,
    paper_view: Mapping[str, Any],
    doc: Mapping[str, Any],
    actor: str = "agent-H",
) -> dict:
    """没有可审的正文时的返回形状：一个字都不写盘，且不判 pass。

    为什么不是抛异常：这不是"调用方参数错"，而是"这一趟没有对象可审" —— 它必须是一个
    可读的结论（谁被审了、为什么审不了、下一步该干什么），而不是一次崩掉。但它与
    `accepted` 必须隔着一整个档：`checked=False` + `verdict="unreviewable"`。

    为什么不动 `documents.status`：状态是"审过之后"的裁决（`_set_doc_status` 会顺手写
    审核轴三格）。这一趟根本没审 —— 把状态推成 `in_review`/`accepted` 都是在替一次
    不存在的审校记账。返回值里的 `status` 是现在的状态（读数），不是本次写下的。

    键集合与正常路径逐字相同（`test_tools_returns_declaration` 的判据是
    "声明 ⊆ 实现"：两条返回路径少一个键都会当场变红）。
    """
    existing = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == str(doc_id)]
    # 没审成不是一次复审：这一趟不推进轮次账（`_advance_review_round` 只在真读到
    # 正文之后才调用）。这里带的 `round` 是"当前第几轮"的读数，不是本次写下的。
    round_no = int(round_no) if round_no is not None else max(
        int(dict(doc).get("review_rounds") or 0), 1)
    status_now = str(doc.get("status") or "")
    zero_coverage = {
        "claims_total": 0,
        "claims_reviewed": 0,
        "claims_decided": 0,
        "claims_semantically_judged": 0,
        "note": (
            "这一趟**没有可审的论文正文** ⇒ 覆盖率这一格全是 0，"
            "它是『没审到』的读数，不是『审过、零发现』"
        ),
    }
    return {
        "doc_id": str(doc_id),
        "checked": False,
        "round": round_no,
        "new_findings": [],
        # 乙：这一趟没审 ⇒ 一条旧判词也没被覆盖（键与正常路径逐字相同）。
        "duplicate_skipped": 0,
        "reopened": [],
        "error_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "dep_check": {
            "checked": False,
            "reason": "没有可审的论文 ⇒ 依赖闭合这一维没查（不得读成『依赖都闭合』）",
            "open": [],
        },
        "semantic_check": {
            "checked": False,
            "judge": "",
            "reason": "没有可审的论文 ⇒ 语义级判据这一维没查",
            "claims_judged": 0,
            "claims_unknown": 0,
            "checker_errors": 0,
            "stronger_than_evidence": 0,
        },
        "coverage": zero_coverage,
        "status": status_now,
        "status_updated": False,
        "status_error": "",
        "signature": None,
        "signature_error": None,
        "verdict": "unreviewable",
        # 丙（2026-11-11）：没有可审的正文 ⇒ 这一格同样要把"还有没有 open findings"
        # 带出来（键集合与正常路径逐字相同；这一趟没审，所以 `blocks_accept=False`）。
        "open_findings": {
            "checked": True,
            "total": sum(1 for r in existing if str(r.get("status") or "") == "open"),
            "error": sum(1 for r in existing if str(r.get("status") or "") == "open"
                         and str(r.get("level") or "") == "error"),
            "warning": sum(1 for r in existing if str(r.get("status") or "") == "open"
                           and str(r.get("level") or "") == "warning"),
            "finding_ids": [str(r.get("finding_id") or "") for r in existing
                            if str(r.get("status") or "") == "open"],
            "review_round": round_no,
            # 甲：这一格是盘上现有的轮次账读数（不是 0 —— 那会把"复审过 N 轮"
            # 读成"没复审过"）；这一趟没审，所以它没有推进。
            "review_rounds": int(dict(doc).get("review_rounds") or 0),
            "blocks_accept": False,
            "why": "这一趟没有可审的正文 ⇒ 状态一个字都没动（不是「没有 open findings」）",
        },
        "reason": (
            f"{paper_view.get('reason') or '没有可审的论文'}。"
            "⇒ 本次**没有判 pass**：一条发现都没落、`documents` 的状态一个字都没动"
            "（没审到不是『审过、没问题』）。下一步：让 G 先把正文写进 "
            "`out/paper/main.tex`（或编出带文本层的 `main.pdf`），再让 H 审。"
        ),
        "paper_body": dict(paper_view),
    }


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
    """审一份论文：把机械发现落成 `ReviewFinding` 行，并更新 `documents.status`。
    返回 ``{"doc_id","checked","round","new_findings","duplicate_skipped","reopened","error_count","warning_count","info_count","dep_check","semantic_check","coverage","status","status_updated","status_error","signature","signature_error","verdict","reason","paper_body"}``。
    ## 审的是论文，不是台账行（业主 2026-10-24 裁定）
    「只对论文负责是正确的，documents 等都是中间产物」＋「H 审论文（`out/paper/main.tex` /
    pdf），documents 只是它的登记行」。所以本函数的输入正文来自 `read_paper_body`：
    `<项目根>/out/paper/main.tex` 优先，退到 `main.pdf` 的文本层。那份正文连同它的行号
    一起交给 `scan_document`（`_line_of` 因此能把发现的逐字引文定位到正文某一行）。
    - 两者都没有（或读不出来 / 抽出来是空的）⇒ `checked=False`、`verdict="unreviewable"`，
      一个字都不写盘（不落发现、不动状态）：没审到不是"审过、没问题"；
    - `documents` 那一行是中间产物：审完只改它的 `status`（现状保留）。台账行缺失时
      仍可审（论文是真身），这一缺只记读数（`paper_body` 里的 `documents_row`）。
    ## 三段式（为什么是三个事务而不是一个）
    1. 落发现（`review_findings`）：发现是审校的产出，必须落库 ——"发现了但没记下来"等于没发现。 2. 重开谎报（`review_findings`）：
    G 把一条 finding 标成 `fixed` 之后，如果重跑检查仍然复现，这条 finding 会被重新打开。没有这一步， G 只要点一下"已修复"，审校就只看状态、成
    了盖章机。 3. 改状态（`documents`，独立事务）：稿件可能本身不合 schema，于是这一步会失败。把它与落发现分开，失败时才不会连发现一起丢掉。
    ## 三态：`dependencies` 没查 ⇒ 不许判 accepted
    `dep_check.checked is False` 时 verdict 是 `"unverified"`，文档状态停在`in_review` —— 「依赖都闭合」这句
    话在没有查过的情况下不许说出口。
    """
    doc_id = str(doc_id)
    # ---- 被审对象：论文正文（这一路输入此前根本不存在 ⇒ 原来那句"没有行号来源"成立）
    root = Path(getattr(store, "root", None) or ".")
    paper = read_paper_body(root)
    body = _body_text_of(paper)
    # 台账行缺失是允许的（③ 论文是真身）：只有"既没有台账行、又没有正文"才是真的没东西可审。
    row_missing = False
    try:
        doc = _doc_of(store, doc_id)
    except ValueError:
        if _blank(body):
            raise
        row_missing = True
        # 台账行缺了：按"这一行还没登记过"的形状起一份最小输入（claims 为空 ⇒
        # 断言级检查没有对象可查，但正文级读数与论文 sha256 照样如实给出）。
        doc = {"doc_id": doc_id, "kind": "paper", "title": "", "claims": [],
               "sections": [], "open_problems": [], "markdown_path": None}
    paper_view = paper_reading(paper)
    paper_view["documents_row"] = "missing" if row_missing else "present"
    if _blank(body):
        return _unreviewable_review(
            store, doc_id, round_no=round_no, paper_view=paper_view, doc=doc,
            actor=actor,
        )

    # 审校输入 = 台账行 + 正文（行号来源就是它；`scan_document` 只读 `doc["text"]`）
    submitted = dict(doc)
    submitted["text"] = body
    deps, _dep_provided = _resolve_deps(store, doc_id, dependencies)
    # 语义判据一路透传给 `scan_document`（`draft/28` §196）：不传就等于这一维永远"没查"，
    # 而 H 的报告里那一格会一直写着 0 —— "没接线"与"查过没问题"必须分得开。
    scan = scan_document(submitted, dependencies=deps, semantic_judge=semantic_judge)

    # ---- 甲（2026-11-11 业主裁定）：H 做了一次复审 ⇒ 轮次账 +1（唯一来源）。
    #
    # 这一笔在"确认真有正文可审"之后才落：没审成不是一次复审（上面已经早退）。
    # 轮次不再从"已有发现的最大 round +1"推 —— 那是第二套轮次（真机上
    # `record_finding` 每落一条就把它推一格，于是 24 条发现摊出 12 个"轮次"，
    # 而 `documents.review_rounds` 恒 2）。见 `_advance_review_round` 的口径。
    round_no, round_error = _advance_review_round(
        store, doc_id, explicit=round_no, actor=actor)
    doc = {**doc, "review_rounds": round_no}
    if round_no < 1:
        raise ValueError("round_no 从 1 开始")

    existing = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]

    # 一趟分完三件事：已有发现的去重键（`existing_keys`）、本轮扫描产出的全部去重键
    # （`current_keys`）、以及待落库的新发现。改前这三样要扫三趟 —— `existing` 两趟
    # （`seen` 一次、"标了 fixed 仍复现"的候选再一次）、`scan["findings"]` 两趟
    # （落库候选一次、`current_keys` 再一次），每一趟都为每行现算一次 `_dedup_key`
    # 的三段 `str()`。`_dedup_key` 只读行的 `kind/target/message` 三格，本段循环里
    # 没有任何东西改写这些行 ⇒ 同一行在任何一趟算出的键逐字相同。
    existing_keys = [_dedup_key(r) for r in existing]
    seen = set(existing_keys)
    current_keys: set[tuple[str, str, str]] = set()
    pending: list[dict] = []
    duplicate_skipped = 0
    for f in scan["findings"]:
        key = _dedup_key(f)
        current_keys.add(key)
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
                # 乙（2026-11-11）：机械扫描产出的这一条同样是"这一轮的新判词" ——
                # 同一 (kind,target) 的更早 open 判词被它覆盖（更晚轮次才覆盖）。
                _supersede_prior_open(
                    tx, existing, kind=str(f["kind"]), target=str(f["target"]),
                    new_round=round_no, new_id=str(payload["finding_id"]))
                new_findings.append(payload)

    # ---- 重开"标了 fixed 但其实还在"的发现（防止 G 用点状态的方式修好问题）
    # `current_keys` 与 `existing_keys` 都在上面那趟扫里算好了（同一行同一键）；
    # 这里按 `existing` 的原序配回每一行，判据表达式逐字未变。
    reopened: list[dict] = []
    to_reopen = [
        r
        for r, r_key in zip(existing, existing_keys)
        if str(r.get("status")) == "fixed" and r_key in current_keys
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
    #: 本次真的逐条检查过的断言数。`0` 是"一条断言都没审到"，不是"审过、零发现" ——
    #: 唯一会走到这里的正常形态就是 ③（`documents` 行缺失：论文照审，但没有断言可查）。
    claims_total = int(scan["coverage"].get("claims_total") or 0)
    if scan["error_count"]:
        verdict = "rejected"
    elif not claims_total:
        # 覆盖率 0 ⇒ 不许 accepted（"没审到"不是"审过、没问题"）。这一档与
        # "依赖没查"同族：都是"这一维没有证据"，所以落同一个第三态 `unverified`。
        verdict = "unverified"
    elif not dep_checked:
        # 「依赖闭合没查」不等于「依赖闭合」—— 不许在这个前提下判 accepted。
        verdict = "unverified"
    elif scan["warning_count"]:
        verdict = "accepted_with_warnings"
    else:
        verdict = "accepted"

    target_status = (
        "accepted" if (scan["error_count"] == 0 and dep_checked and claims_total) else "in_review"
    )
    # ---- 丙（2026-11-11，业主裁定「丙修」）：有 open findings 就不许 accepted ----------
    #
    # 真机现场（`projects/dct-min5r-20261111`）：H 21:42 落了 3 条 open findings，7 秒后调
    # 本函数（`round_no=4`），只按新扫的 `error_count=0` 就把 `documents.status` 写成
    # accepted、`review_verdict` 写成「成立」—— 台账自相矛盾（`verify_all` 的
    # `accepted_with_open_error` 就是这么抓到的）。矛盾的产生侧是这里，闸就加在这里。
    # 判据两条（缺一不许 accepted）：① 这一版没有 open findings —— 本函数不收口上一轮 /
    # 手工判词的 open 项（它只重跑机械判据、看不到手工判词），只要盘上还有 open 的就不许
    # 判成"通过"；② 本轮复审收过 —— 旧轮次的 open 项还挂着时，"本轮"并没有收过那一版的
    # 全部发现（`review_rounds` 与 `round_no` 一起进读数，供人判是哪一种）。
    # 处置方向是走 `review.verify_fixes`（逐条判 fixed / 仍 open），不是在这里改 findings。
    prior_open, open_findings_reading = _open_findings_gate(
        existing=existing, reopened=reopened, round_no=round_no, doc=doc)
    blocked_by_open_findings = bool(target_status == "accepted" and prior_open)
    if blocked_by_open_findings:
        target_status = "in_review"
    # ---- 审核轴：只有真判出了结论才写裁决（业主 2026-10-30，2026-11-04 施工单）
    #
    # 两态裁决只覆盖"查过之后"的两种结局：
    #   成立   = 查了、没找到缺陷（含只有 warning 的 accepted_with_warnings）
    #   有毛病 = 查了、找到了缺陷
    # 「没查成」不是裁决：覆盖率 0 / 依赖闭合没查 ⇒ review_verdict 留空，
    # review_checked=False + 理由；盘上审核轴一个字节都不写（台账不留行）。
    if verdict in ("accepted", "accepted_with_warnings"):
        _axis_verdict, _axis_checked, _axis_reason = "成立", True, ""
    elif verdict == "rejected":
        _axis_verdict, _axis_checked, _axis_reason = "有毛病", True, ""
    else:
        _missing = []
        if not claims_total:
            _missing.append("这一趟没有一条断言可查（覆盖率 0）")
        if not dep_checked:
            _missing.append("依赖闭合没查")
        _axis_verdict, _axis_checked = "", False
        _axis_reason = "没查成：" + "；".join(_missing) + " ⇒ 不写裁决（台账不留行）"
    if blocked_by_open_findings:
        # 有 open findings ⇒ 本轮不写「成立」：机械判据这一趟没找到缺陷，但它不覆盖
        # 上一轮/手工判词留下的 open 项 —— 在这个前提下写「成立」就是真机那个矛盾。
        _axis_verdict, _axis_checked = "", False
        _axis_reason = (
            "没查成：这一版还有 open findings 没被本轮复审收口（"
            + "、".join(str(x) for x in open_findings_reading["finding_ids"][:8])
            + f" 等 {len(open_findings_reading['finding_ids'])} 条；本轮 round={round_no}，"
            f"documents.review_rounds={open_findings_reading['review_rounds']}）"
            " ⇒ 不写裁决、不许 accepted；先去 `review.verify_fixes` 逐条判 fixed / 仍 open")
    # `T4-B`：判 accepted 就签一条（`draft/29` §8.8.3"接受档签一条，毫不犹豫"）。
    # 签在状态事务内、写 status 之前（`_set_doc_status` 的 `pin` 回调）：签名钉的是
    # 那一版的内容哈希与它读到的发现，钉不上就不许把状态写成 accepted ——
    # 改前是"先提交 accepted、再签"，签名失败只回报 `signature_error` ⇒ 留下
    # "accepted 但没钉住哪一版"（真机缺陷；`CODE_ACCEPT_WITHOUT_PIN` 是现在的受控拒码）。
    signature: dict | None = None
    signature_error: str | None = None

    def _pin(row: dict) -> None:
        nonlocal signature, signature_error
        signature, signature_error = _sign_accepted_revision(
            store, doc_id, verdict=verdict, actor=actor, round_no=round_no,
            coverage=scan.get("coverage"), doc_row=row)

    status_updated, status_error, status_now = _set_doc_status(
        store, doc_id, target_status, actor=actor,
        review_verdict=_axis_verdict, review_checked=_axis_checked,
        review_reason=_axis_reason,
        pin=_pin if target_status == "accepted" else None,
    )

    reason_bits = [
        # 被审的是什么，先于"查出什么"：这一格就是"这一轮 H 看的是哪一份正文"的可追溯读数
        # （业主 2026-10-24：「只对论文负责」）。`sha256` 取盘上那份文件的字节摘要，
        # 与编译回执的 `tex_sha256` 同一口径。
        (
            f"被审正文：{paper_view['path']}（{paper_view['source'] or '未知来源'}，"
            f"sha256={str(paper_view['sha256'] or '')[:16]}…，{paper_view['lines']} 行）"
            + ("；⚠️ `documents` 台账行缺失（论文是真身，缺的只是登记行，已按读数记下）"
               if row_missing else "")
        ),
        f"机械检查发现 error={scan['error_count']}、warning={scan['warning_count']}、info={scan['info_count']}",
        (
            f"依赖闭合已检查（{scan['dep_check'].get('reason')}）"
            if dep_checked
            else f"依赖闭合**没查**（{scan['dep_check'].get('reason')}）⇒ 不能判 accepted"
        ),
        f"新增发现 {len(new_findings)} 条、与已有发现重复被跳过 {duplicate_skipped} 条",
        f"覆盖率 {scan['coverage']['claims_reviewed']}/{scan['coverage']['claims_total']}"
        f"（判成 {scan['coverage']['claims_decided']}）",
        # 覆盖率 0 也是一条必须说出口的读数：它把"没有断言可查"与"断言都查过、都干净"
        # 分开（前者不许 accepted，见上面 verdict 分档里的那一支）。
        *(
            ["⚠️ 本次**一条断言都没审到**（覆盖率 0）⇒ 不判 accepted："
             + ("`documents` 台账行缺失，没有 claims 可查 —— 论文照审，"
                "但『没有断言』不等于『断言都对』" if row_missing else "这一行的 claims 是空的")]
            if not claims_total else []
        ),
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
    if blocked_by_open_findings:
        reason_bits.append(
            "⛔ 有 open findings ⇒ **不判 accepted**（status=in_review）："
            f"{open_findings_reading['why']}；本轮 round={round_no}、"
            f"documents.review_rounds={open_findings_reading['review_rounds']} —— "
            "先去 `review.verify_fixes` 逐条判 fixed / 仍 open（手工判词只有 H 的显式"
            "复核通道能判掉），收口之后再复审")
    if not status_updated:
        reason_bits.append(
            f"⚠️ 文档状态**未能更新**（{status_error}）—— 这通常因为盘上这份稿件本身不合 schema，"
            "或 `documents` 里根本没有这一行（论文照审，状态这一笔如实报失败）"
        )
    if round_error:
        reason_bits.append(
            f"⚠️ 轮次账**未能写回** `documents.review_rounds`（{round_error}）—— "
            f"这一轮的判词仍按 round={round_no} 记，但盘上的轮次可能与它对不上"
        )

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
        # 丙（2026-11-11）：这一版还有没有 open findings、拦没拦 accepted 的读数。
        "open_findings": open_findings_reading,
        # 本次审的论文正文是哪一份（可追溯）：`path` / `source` / `sha256` / `bytes` /
        # `lines` / `chars` 与"台账行在不在"。它是读数，不是判据 —— 判据是 verdict。
        "paper_body": dict(paper_view),
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
    coverage: Mapping[str, Any] | None = None,
    doc_row: Mapping[str, Any] | None = None,
) -> tuple[dict | None, str | None]:
    """判 accepted 时签一条：把"被接受的是哪一版"钉在台账上（`draft/29` §8.8；`draft/30` §T4-B）。

    - 由 `_set_doc_status` 的 `pin` 回调在状态事务内、写 status 之前调用 ——
      签名钉的是"这一版被审过"，所以钉版先于/同于 `accepted` 的提交：钉不上时调用方
      受控拒（`CODE_ACCEPT_WITHOUT_PIN`），不会留下"accepted 但没钉住"；
    - `doc_row` 由回调带进来（就是事务里要改的那一行），不另读一次盘；
    - `instance_id` 取"谁 + 何时"（一次审就是一次调用）。它只作留痕，
      不作门槛（§8.8.4 收尾那一段逐字说了这件事）；
    - 返回 `(签名记录 或 None, 错误说明 或 None)` —— 失败如实带回，
      不吞掉（"审过了但没签上"与"审过并签上"必须分得开）。
    """
    from .. import schema as S
    from .. import signatures as SIG

    doc = dict(doc_row) if doc_row is not None else next(
        (r for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)), None)
    if doc is None:
        return None, f"签名时稿件 {doc_id} 读不出来"
    if not str(doc.get("content_sha256") or "").strip():
        return None, ("稿件没有 content_sha256 ⇒ 钉不住被接受的是哪一版"
                      "（`signatures.content_sha256_of` 的口径）；不签发")
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


#: H 可以显式选择的收尾档（受控词）。
#:
#: 2026-11-15 业主裁定逐字：「撤掉这个上限，一切由智能体自行决定，不做读数」。
#: 于是 `verify_fixes` 不再有"到第几轮就收尾"的计数器；收不收尾由 H 自己判，
#: 要收尾就把这一档显式传进来。它是判断，不是读数：这里没有轮次、没有余量、
#: 没有上限 —— 只有一个受控词（`unresolved_review` 仍是 `schema.DOC_STATUSES` 里那一档）。
CLOSE_AS_VALUES: tuple[str, ...] = ("unresolved_review",)


def verify_fixes(
    store: Any,
    doc_id: str,
    *,
    round_no: int,
    dependencies: Any = _UNSPECIFIED,
    close_as: str | None = None,
    actor: str = "agent-H",
    semantic_judge: SemanticJudge | None = None,
) -> dict:
    """复审：对上一轮的每条 finding 重跑对应检查，判定 `fixed` / 仍 `open` 并逐条列出。
    返回 ``{"doc_id","round","resolved","still_open","unresolved_findings","verdict","reason",...}``。
    ## 收不收尾由 H 判断（2026-11-15 业主裁定，逐字：「撤掉这个上限，一切由智能体自行决定，不做读数」）
    轮数上限（`max_review_rounds`）已撤除：本函数不再按轮数把结论判成任何终态，
    也不再提供轮次读数（没有 `round_budget` / `remaining` / `capped` 这类字段）。
    本函数只负责"重审 + 逐条列出 still_open"；`unresolved_review` 保留为 H 可以自行选择
    的终态 —— 判据是调用方显式给的 `close_as`，不是计数器。不给 ⇒ 本趟不收尾。
    判据不是 G 自称修好了，而是"重跑检查还复现吗"：复现 ⇒ `open`（即使 G 已经把它标成 `fixed`，也会被重新打开）；不复现 ⇒ `fixed`。此外当前扫描里新出现的问题会以 
    `source="new_issue"`出现在 `still_open` 里（复审不是"只看旧账"）。
    `R-04`（`draft/44` / `draft/52` D 族）：两半R-04-a（语义判据的注入面）：复审复扫与 `review_document` 走同一个
    `scan_document(..., semantic_judge=...)`。此前 `verify_fixes` 的复扫不带判据，于是"上一轮由语义判据产生的 `overclaim`"在这一轮结构上不可能复现 ⇒必然
    落进 `resolved` ⇒ 写成 `status="fixed"`（真机 `p8d` 的 claim-3/claim-4 就是这样被"修好"的：库里是 `fixed`，而现行版内容上它们仍被判"结论强于引文"）。
    R-04-b（没查 ≠ 修好）：`resolved` 里凡是语义那一支的 finding，只有"这一轮真的重跑了语义判据、且它没有复现"才允许落 `fixed`；判据没接线（`semantic_judge is None`）
    或这一轮答不上来 / 判据报错（`claims_unknown` / `checker_errors`）⇒ 留在 `open` 并标`source="not_rechecked"`（返回值取值，不落表）。
    """
    doc_id = str(doc_id)
    # ---- H 的收尾判断先过词表，再动任何盘上读数：写错一个词不许静默落在"不收尾"上
    # （那会让 H 以为它已经交人复核了）；而且被拒的调用不许推进轮次账。
    if close_as is not None:
        close_as = str(close_as)
        if close_as not in CLOSE_AS_VALUES:
            raise ValueError(
                f"close_as 必须是 {CLOSE_AS_VALUES} 之一（或不给 = 不收尾），收到 {close_as!r}")
    # ---- 甲（2026-11-11 业主裁定）：复审裁决这条路每做一次也推进一格轮次。
    #
    # 与 `review_document` 共用 `_advance_review_round`（轮次账只有一份实现）；
    # 显式 `round_no` 只作下限 —— 断点续跑时调用方可能报一个更靠后的轮次，
    # 正常流程下这里是 `cur + 1`。`doc` 跟着换成写回之后的读数。
    round_no, round_error = _advance_review_round(
        store, doc_id, explicit=round_no, actor=actor)
    if round_no < 1:
        raise ValueError("round_no 从 1 开始")

    doc = {**_doc_of(store, doc_id), "review_rounds": round_no}
    deps, dep_checked = _resolve_deps(store, doc_id, dependencies)
    # 复审复扫与 `review_document` 用同一个被审对象（业主 2026-10-24：H 审论文）：
    # 有正文就把正文当输入（行号/引文都指着它），没有正文就照旧只读台账行 ——
    # 复审不因为"这一路上没正文"而拒绝干活，但也不许声称自己审过正文
    # （它的返回里 `paper_body.checked` 就是这一点的读数）。
    _paper = read_paper_body(Path(getattr(store, "root", None) or "."))
    _body = _body_text_of(_paper)
    _submitted: dict = dict(doc)
    if not _blank(_body):
        _submitted["text"] = _body
    # R-04-a：复扫与 `review_document` 共用同一个语义判据（`semantic_judge=None`
    # 时 `semantic_check["checked"] is False` —— 那是"没查"，不是"没问题"）。
    scan = scan_document(_submitted, dependencies=deps, semantic_judge=semantic_judge)
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
    # 乙（2026-11-11）：`superseded` 是"被更晚的同处判词取代"的终态 —— 它不是待判的
    # 旧账：再拿它去判 fixed / 仍 open 等于把已经翻篇的那一页又翻回来。所以复审的
    # "上一轮旧账"里排除它（`open` 的判定仍是 `status == "open"`，一个字没动）。
    prev = [r for r in findings
            if int(r.get("round") or 1) < round_no
            and str(r.get("status") or "") != "superseded"]
    #: 手工判词（P2-4）：它们的去重键永远不在 `current` 里，所以「本轮没复现」
    #: 对它们不是一个可用的判据。清单在循环外一次算清（不改 `_dedup_key`）。
    manual_ids = {str(r.get("finding_id")) for r in prev if _is_manual_finding(r)}
    manual_done_ids = {str(r.get("finding_id")) for r in prev if _manual_rechecked(r)}

    resolved: list[dict] = []
    still_open: list[dict] = []
    prev_keys: set[tuple[str, str, str]] = set()
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
        prev_keys.add(key)
        if key in current:
            base["evidence"] = current[key].get("evidence")
            base["source"] = "prev_round"
            still_open.append(base)
        else:
            resolved.append(base)
    # `prev_keys` 就是这趟里每一行的键（改前是又扫一趟 `prev` 重算一遍 `_dedup_key`，
    # 那一趟读的三格与这趟逐字相同、本段循环不写 `prev` 的任何行）。
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
    semantic_not: list[dict] = []
    manual_not: list[dict] = []
    manual_done: list[dict] = []
    # 改前是 `for item in list(resolved)` + 两条 `resolved.remove(item)`：先拷一份
    # O(N) 的快照，再为每条被摘掉的行做一次 O(N) 的按值删除（O(N²)，且 `remove`
    # 按内容相等找第一行）。改后一趟分拣：留下的按原序进 `kept_resolved`，
    # 摘掉的直接不进 —— 循环结束后 `resolved` 与改前逐项同序（`resolved` 在
    # 循环里没有被别处读过）。
    kept_resolved: list[dict] = []
    for item in resolved:
        fid = str(item.get("finding_id") or "")
        # ---- P2-4：手工判词不参与"本轮 scan 没复现 ⇒ fixed"这条判据。
        if fid in manual_done_ids:
            # H 已经显式复核过（fixed / wontfix，带理由）：`verify_fixes` 一个字都不改，
            # 也不许把它重新算成 open（那会把 H 的判词又盖掉）。它仍算 resolved
            # （读数里看得到 `source="manual_rechecked"`），但不进 `changes`。
            item["source"] = "manual_rechecked"
            item["status"] = "fixed" if str(item.get("status")) == "fixed" else "wontfix"
            manual_done.append(item)
            kept_resolved.append(item)
            continue
        if fid in manual_ids:
            item["source"] = "manual_not_rechecked"
            item["status"] = "open"
            item["note"] = f"[round {round_no}] {MANUAL_NOT_RECHECKED_NOTE}"
            # 盘上也要留在 `open`：G 在 `revise` 里把它标成 fixed 也不作数
            # （那只改状态、不改正文；是否真修好只有 H 复核说得清）。
            changes.append(
                {
                    "finding_id": fid,
                    "status": "open",
                    "resolution_note": f"[round {round_no}] {MANUAL_NOT_RECHECKED_NOTE}",
                }
            )
            still_open.append(item)
            manual_not.append(item)
            not_rechecked.append(item)
            continue
        if _is_semantic_finding(item) and not semantic_recheck_ok:
            item["source"] = "not_rechecked"
            item["status"] = "open"
            item["note"] = (
                f"[round {round_no}] 本轮未重跑语义判据 ⇒ 不许判 fixed（没查 ≠ 修好）"
                + (f"；semantic_check={semantic_check.get('reason') or semantic_check}"
                   if not semantic_check.get("checked") else "")
            )
            still_open.append(item)
            not_rechecked.append(item)
            semantic_not.append(item)
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
        kept_resolved.append(item)
    resolved = kept_resolved
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
    if close_as is not None:
        # H 自己的判断：它决定这一轮收尾、交人复核。不是计数器到点，也不是本函数的缺省。
        verdict = "unresolved_review"
    elif not still_open:
        verdict = "accepted"
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
    # ---- 审核轴：与 `review_document` 同一口径（业主 2026-10-30，2026-11-04 施工单）
    #
    #   成立   = 这一轮复审没找到缺陷（且依赖闭合查过）
    #   有毛病 = 这一轮复审仍有缺陷（`revise_again` 有 error、或 H 显式收尾 `unresolved_review`）
    #   没查成 = 依赖闭合没查 / 只因为语义判据没重跑而被卡在 `revise_again` ⇒ 不写裁决
    if verdict in ("revise_again", "unresolved_review") and blocking:
        _axis_verdict, _axis_checked, _axis_reason = "有毛病", True, ""
    elif verdict == "unresolved_review":
        # H 显式收尾、而当前没有 error 级未解决项：这仍是 H 判的"不通过"。
        # 不写这一支的话它会掉进下面的"没查成"分支，于是盘上留下一条空理由
        # （"没查成： ⇒ …"）—— 而 H 明明做了判断。
        _axis_verdict, _axis_checked, _axis_reason = "有毛病", True, ""
    elif verdict == "accepted" and dep_checked:
        _axis_verdict, _axis_checked, _axis_reason = "成立", True, ""
    elif verdict == "accepted":
        _axis_verdict, _axis_checked = "", False
        _axis_reason = "没查成：依赖闭合没查 ⇒ 不写裁决（台账不留行）"
    else:
        _axis_verdict, _axis_checked = "", False
        # P2-4：这一档现在有两个来源（语义判据没重跑 / 手工判词没有 H 的显式复核），
        # 理由必须逐条说出来，不能只留"没重跑语义判据"那一句。
        _not_checked_bits: list[str] = []
        if semantic_not:
            _not_checked_bits.append("本轮没有重跑语义判据")
        if manual_not:
            _not_checked_bits.append(
                f"{len(manual_not)} 条手工判词还没有 H 的显式复核（自动复跑判不掉它们）")
        _axis_reason = ("没查成：" + "；".join(_not_checked_bits)
                        + " ⇒ 不写裁决（台账不留行）")
    status_updated, status_error, status_now = _set_doc_status(
        store, doc_id, target_status, actor=actor,
        review_verdict=_axis_verdict, review_checked=_axis_checked,
        review_reason=_axis_reason,
    )

    unresolved = [f for f in blocking]
    reason_bits = [
        f"第 {round_no} 轮复审："
        f"上一轮 {len(prev)} 条发现里 resolved={len(resolved)}、仍复现={len(still_open) - sum(1 for f in still_open if f.get('source') == 'new_issue')}",
        f"error 级未解决 {len(unresolved)} 条",
        # `R-04-b`：没重跑语义判据时，上一轮那几条语义发现留在 open
        # （读数必须逐条说出来，否则"resolved 变多了"看起来像"修好了"）。
        (
            f"其中 {len(semantic_not)} 条是**语义判据产的发现**、本轮未重跑判据 ⇒ 留在 open、"
            f"不许判 fixed（没查 ≠ 修好）"
            if semantic_not
            else ""
        ),
        # P2-4：手工判词的读数（与语义那一支同形，但判据不同：它根本不在 scan 的
        # 可产出集合里，所以"没复现"永远不成立）。
        (
            f"其中 {len(manual_not)} 条是**手工判词**（`record_finding` 落的散文发现）、"
            f"本轮**没有 H 的显式复核** ⇒ 留在 open，不许判 fixed"
            f"（手工判词不能被自动复跑判掉；逐条见 `not_rechecked`）"
            if manual_not
            else ""
        ),
        (
            f"{len(manual_done)} 条手工判词已由 H 显式复核过（fixed / wontfix 带理由）"
            f"⇒ 本轮不改写它们"
            if manual_done
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
            "H 显式判 `unresolved_review`（`close_as`）⇒ 停止自动修订、交人复核"
            "（**未解决的发现已全部列出**，未隐藏）；轮数上限已按 2026-11-15 业主裁定撤除，"
            "这一档不是计数器触发的"
        )
    if not status_updated:
        reason_bits.append(f"⚠️ 文档状态**未能更新**（{status_error}）")
    if round_error:
        reason_bits.append(
            f"⚠️ 轮次账**未能写回** `documents.review_rounds`（{round_error}）—— "
            f"这一轮仍按 round={round_no} 判，但盘上的轮次可能与它对不上"
        )

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
        # 这一轮复扫用的是哪一份正文（与 `review_document` 同一个读数形状）：
        # `checked=False` 就是"这一轮没读到正文 ⇒ 复扫只看台账行"，不是"没问题"。
        "paper_body": paper_reading(_paper),
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
                # 乙（2026-11-11）：被哪一条更晚的同处判词覆盖（空串 = 未覆盖）。
                # 这是"覆盖"这件事在读数面上的唯一落点 —— 老行读成 ""（三态：
                # 未覆盖 / 被某条覆盖 / 这一格不存在的老行同样是未覆盖）。
                "superseded_by": r.get("superseded_by") or "",
            }
        )
    return {"count": len(out), "findings": out}


# ---------------------------------------------------------------- 审校报告（G1–G15）

#: 审校报告默认落点（相对工作区）。沿用 `draft/17` §8.1 的目录树建议：
#: 报告与稿件分开放，且按被审对象命名，于是"这份报告审的是哪一版"靠文件名
#: 就能对上 —— 再加上报告头里的内容 hash，"行号失效"这件事才不可能悄悄发生。
#:
#: 2026-10-13 从 `reports` 挪进 `out/review`（业主：「review 只是任务的一种，
#: 咋产出中稳定产出 review 文件夹呢？」）：`out/review/` 已经是 M 的交付说明
#: （`REPORT.md`）、体例声明（`REPORT-STYLE.json`）、状态报告（`STATUS-*`）与
#: M 判据（`m-verdicts.jsonl`）的落点 —— 审校报告住进同一个目录，"这一趟审过什么"
#: 就有「一个」可数的面（收工门那一档 `review_files` 数的就是它）。
#: 落点由框架定、不由模型挑：模型挑路径时，"稳定产出"这件事就只能靠运气。
DEFAULT_REPORT_SUBDIR = "out/review"


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
    1. 钉住被审版本 hash（G11）：报告头写 `revision_hash`（`claimanatomy.revision_hash`，算法逐字写进报告）。 2. 『我
    这一轮犯的错』一节（G15）：`own_errors` 是必填参数；`None` ⇒ 抛（"没写"不等于"没犯错"），`[]` ⇒ 合法（显式声明零错误）。 3. 零发现自
    证（G13）：每道报"零发现"的门都必须带"我用了什么过程、数出了什么数字" —— 由 `gates.GateResult` 的构造期校验保证， G13 再独立复核一遍。
    ## 它写哪里、写什么
    只写一个 markdown 文件（默认 `<workspace>/out/review/<doc_id>-review.md`），不碰任何数据表、不碰 `claims`。这
    是 `AgentH` 落库代理的一个入口，因此它属于"能被显式拒绝的写工具"那一类（`include_writers=True` 才装配）。
    三态：`dependencies` 省略 = 从库里读该稿件的依赖（查过）；显式 `None` = 没查（`dep_check.checked=False`）。
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
        # G8 的唯一证据来源：台账行（2026-11-16 AH2b）。`run_evidence` 只是旧调用面，
        # 传进来也不参与判定 —— 回执可以由任何一方自己写，台账行才是登记过的运行。
        experiments=[dict(r) for r in store.rows("experiments")] if store is not None else None,
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
    # ---- 产物归属（`ARTIFACTS.jsonl`）：审校报告已经落盘 ⇒ 补"这个路径归谁产"。
    #
    # 为什么在工具层而不是在读侧：读侧（`closing` 的 `review_files` 读数）只数文件，
    # 从不回答归属；而这份报告是框架自己写的（路径由框架定），不登记就永远 `unowned`。
    # 登记失败 ⇒ 抛（与越界 `out_path` 同一档）：工具调用按失败报，报告文件留在盘上。
    from .. import artifacts as A

    _producer = str(actor or "").strip()
    if _producer.startswith("agent-"):
        _producer = _producer[len("agent-"):]
    _entry, _reg_problem = A.record_or_problem(
        root, path=str(rel).replace("\\", "/"), producer=_producer or "H",
        kind="review-report", note=f"doc:{doc_id} 的审校报告（G1–G15 全量）")
    if _reg_problem:
        raise ValueError(
            f"{_reg_problem}。审校报告已写盘（{rel}），但这条路径没有产物归属登记 "
            "⇒ 这次调用按失败报（补登记：`agentflow artifacts record "
            f"{str(rel).replace(chr(92), '/')} --producer {_producer or 'H'}`）")
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
        # `own_errors` 的声明类型是 `Sequence[str]`（见签名），且上面两处
        # `list(own_errors)` 已经各自取过一份 ⇒ 数个数直接 `len`，不再为它拷第三份。
        "own_error_count": len(own_errors),
        "coverage": coverage,
        "markdown": markdown,
    }


# ---------------------------------------------------------------- 文本异常字符审计
# 业主 2026-10-30 裁定：「需要保证后续写论文不出现异常字符，给 H 加个工具审」。
#
# ## 为什么这一格必须是「只读 + 逐条给位置」
#
# 异常字符这一类错误的共同点是「看起来没问题」：编辑器不显示零宽字符，PDF 里
# 全角括号与半角括号一样好看，不换行空格唯一的效果是断行算法在那一段失效。
# 于是「读一遍，我觉得没有」这种审法对它们完全无效 —— 人对看不见的东西没有直觉。
# 读数必须逐条落到 文件:行:列 与码位上，H 才能拿着它去要一个修法（改的人是 G）。
#
# ## 六档的边界，以及「多一档 / 少一档」为什么都要红
#
# 六档的词表在 `TEXT_INTEGRITY_KINDS`（唯一来源）。分档不是学术分类，而是
# 处置分类：控制符与零宽几乎一定是管道污染的残留（删掉），替换符说明上游
# 解码已经丢了字符（要回去查那一份的来源），双向控制符能让人读到与实际
# 相反的文本（安全档），不换行空格只是断行（换成普通空格），CJK 在英文正文里
# 说明这一句没被改写成目标语言（要改写，不是删）。把两档折成一档，H 拿到的
# 修法就错了。
#
# ## `cjk` 为什么只在 `.tex` / `.md` 里报
#
# 论文正文不许有中文，但代码与注释里出现中文是另一回事（本仓的注释就是中文的）。
# 所以这一档挂在「正文类后缀」上，而不是挂在工具上 —— 同一个工具扫 `.py`
# 时不报 CJK，但它照样报控制符与零宽，那两档与文件类型无关。


#: 六档异常字符（读数 `counts` 的键域；顺序即报出来的顺序）。
TEXT_INTEGRITY_KINDS: tuple[str, ...] = (
    "cjk",
    "control",
    "zero_width",
    "replacement",
    "bidi",
    "nbsp",
)

#: `cjk` 那一档的码位域。为什么不是一个区间：业主那句是「CJK 统一表意
#: （U+4E00–9FFF 等）」，而真论文里最先出现的那一批恰恰在「等」里 ——
#: 实测 `projects/paper-rewrite-80/out/paper/main.tex:936` 那 9 个字符里只有 6 个
#: 落在 U+4E00–9FFF，另外 3 个是全角标点（U+FF08 `（` / U+FF0C `，` / U+FF09 `）`）。
#: 只认统一表意 ⇒ 那一行只报 6 个，而「9 个」这个读数是业主自己数出来的口径
#: （判据 `tests/test_h_can_audit_text_integrity.py` 的 g1 钉的就是它）。
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x2E80, 0x2EFF),   # CJK 部首补充
    (0x3000, 0x303F),   # CJK 标点（。「」等）
    (0x3400, 0x4DBF),   # 统一表意扩展 A
    (0x4E00, 0x9FFF),   # 统一表意
    (0xF900, 0xFAFF),   # 兼容表意
    (0xFF00, 0xFFEF),   # 全角/半角形式（（，）等）
)

#: `cjk` 只在这些后缀里报（正文类）。其余后缀照样扫，但那几档里没有 cjk。
_CJK_SUFFIXES: tuple[str, ...] = (".tex", ".md")

#: 目录递归时认的文本后缀。别的后缀不扫 —— 那不是「零命中」，是「不归它管」。
_SCAN_SUFFIXES: tuple[str, ...] = (".tex", ".md", ".txt", ".bib")

#: `limit` 的缺省值：这一次最多返回多少条 `findings`。
#: `counts` 不受它影响（与 `table.count` 同一条纪律：`counts` 是盘上的真总数，
#: `findings` 只是这一次给出的那一截；两者的差额在 `detail[].returned` 上看得见）。
DEFAULT_FINDINGS_LIMIT = 200


def _char_kind(ch: str, suffix: str) -> str | None:
    """一个字符属于哪一档（`None` = 不在六档里，正常字符）。

    `suffix` 只影响 `cjk` 那一档（见上面「`cjk` 为什么只在 `.tex` / `.md` 里报」）。
    判据顺序与词表顺序无关，但有两条是刻意的：双向控制符先判（它落在
    U+202A–202E / U+2066–2069，与别的档不重叠，先判只是让读源码的人一眼看到
    安全档在前）；`\\n` / `\\r` / `\\t` 从控制符里排除（它们是文本的结构，
    不是污染）。
    """
    cp = ord(ch)
    if 0x202A <= cp <= 0x202E or 0x2066 <= cp <= 0x2069:
        return "bidi"
    if 0x200B <= cp <= 0x200D or cp in (0xFEFF, 0x2060):
        return "zero_width"
    if cp == 0xFFFD:
        return "replacement"
    if cp == 0x00A0:
        return "nbsp"
    if (cp < 0x20 and cp not in (0x09, 0x0A, 0x0D)) or cp == 0x7F:
        return "control"
    if suffix in _CJK_SUFFIXES and any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
        return "cjk"
    return None


def _excerpt(line: str, column: int, width: int = 40) -> str:
    """命中位置附近的一段原文（给人看的定位辅助，不参与任何判据）。

    刻意不转义：所见即盘上那一行的片段（零宽字符在它里面也就"看不见"，
    这正是要让人看到的样子），可读的同一性由 `codepoint` 给。
    """
    start = max(0, column - 1 - width)
    end = min(len(line), column + width)
    return ("…" if start else "") + line[start:end] + ("…" if end < len(line) else "")


def _scan_text(rel: str, text: str, *, limit: int) -> tuple[list[dict], dict[str, int]]:
    """扫一份已解码的正文：返回 `(findings, counts)`（`counts` 是真总数）。"""
    findings: list[dict] = []
    counts: dict[str, int] = {k: 0 for k in TEXT_INTEGRITY_KINDS}
    suffix = Path(rel).suffix.lower()
    for lineno, line in enumerate(text.split("\n"), 1):
        for column, ch in enumerate(line, 1):
            kind = _char_kind(ch, suffix)
            if kind is None:
                continue
            counts[kind] += 1
            if len(findings) < limit:
                findings.append({
                    "path": rel,
                    "line": lineno,
                    "column": column,
                    "char": ch,
                    "codepoint": f"U+{ord(ch):04X}",
                    "kind": kind,
                    "excerpt": _excerpt(line, column),
                })
    return findings, counts


def _reject_path(raw: Any, why: str) -> str:
    return f"拒绝路径 {raw!r}：{why}"


def _resolve_under(root: Path, raw: Any) -> tuple[Path | None, str]:
    """把一条路径参数解析成「确定在工作区根之下」的绝对路径。

    规则与 `fs_tools._resolve` 逐条同形（拒绝绝对路径 / 盘符 / UNC / 设备命名空间 /
    NUL；`resolve()` 之后再 `relative_to(root)` 才是唯一判据）。不成立时返回
    `(None, 理由)` 而不是抛异常 —— 读不成在这件工具里是一个「读数」
    （`checked=False` + `reason`），不是一次崩溃。
    为什么这件只读工具也要这道闸：只读不等于无边界。给 H 一把能读整台机器的尺子，
    「H 审的是本项目的论文」这句话就不再成立（它可能审到上一版、或者别的项目）。
    """
    if not isinstance(raw, str):
        return None, f"paths 里必须是字符串，收到 {type(raw).__name__}"
    text = raw.strip()
    if not text:
        return None, "paths 里的空串：要表示工作区根请用 '.'"
    if "\x00" in text:
        return None, _reject_path(raw, "含 NUL 字节（绝对不是合法路径名）")
    norm = text.replace("\\", "/")
    if norm.startswith("/"):
        return None, _reject_path(raw, "只接受工作区内的相对路径（绝对路径/UNC/设备命名空间一律拒绝）")
    if len(norm) > 1 and norm[1] == ":":
        return None, _reject_path(raw, "只接受相对路径（盘符路径会被解析到工作区之外）")
    candidate = (root / norm).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, _reject_path(raw, f"越出工作区（解析为 {candidate}，工作区根为 {root}）")
    return candidate, ""


def _rel_posix(path: Path, root: Path) -> str:
    """工作区相对路径（posix 分隔符）。读数里的 `path` 一律用这个形态（与 `fs.*` 同一条）。"""
    return path.relative_to(root).as_posix()


def _read_body(path: Path) -> tuple[str | None, str]:
    """读一份文本；读不成返回 `(None, 理由)`（三态里的第三态，绝不返回空串冒充空文件）。

    二进制判据是两条：含 NUL 字节（文本文件不会有，而截断的二进制几乎一定有），
    或解码不出 UTF-8。两条都要 —— 只看解码的话，一份"恰好是合法 UTF-8 的二进制"
    会被解成乱码字符，然后报出一串 `control`（那是假发现，比漏报更坏）。
    """
    try:
        raw = path.read_bytes()
    except OSError as e:
        return None, f"{path.name} 读不出来（{type(e).__name__}: {e}）"
    if b"\x00" in raw:
        return None, f"{path.name} 是二进制文件（含 NUL 字节）⇒ 它没有可数的字符"
    try:
        return raw.decode("utf-8"), ""
    except UnicodeDecodeError as e:
        return None, f"{path.name} 不是 UTF-8 文本（{e}）⇒ 它没有可数的字符"


def _expand(root: Path, target: Path) -> tuple[list[Path], str]:
    """一条参数路径 → 要扫的文件清单（文件就是它自己；目录递归认那四个后缀）。"""
    if target.is_file():
        return [target], ""
    if not target.is_dir():
        return [], f"{_rel_posix(target, root)} 在盘上不存在"
    files = sorted(p for p in target.rglob("*")
                   if p.is_file() and p.suffix.lower() in _SCAN_SUFFIXES)
    if not files:
        return [], (f"{_rel_posix(target, root)} 里没有可扫的文件"
                    f"（认 {'/'.join(_SCAN_SUFFIXES)}）⇒ 这一条什么都没扫到")
    return files, ""


def scan_text_integrity(root: Any, paths: Any, *, limit: Any = None) -> dict:
    """扫一批文本里的异常字符，逐条给位置与码位（只读；不写任何东西）。

    返回的六个键在三条路径上（扫成了 / 一条都没扫成 / 部分扫成）完全一致：

    - `checked`：这些路径是不是全部读成了。有一条读不成 ⇒ `False`；
    - `reason`：读不成时逐字理由（全部读成 ⇒ 空串）。空串与非空串是这条读数
      唯一能分开「没查成」与「查过了、干净」的地方 —— 所以读不成时绝不
      返回 `checked=True` + 零命中（那会把「没查」折成「没问题」）；
    - `scanned`：这次真的读成并扫过的文件（工作区相对路径，posix 分隔符）；
    - `findings`：逐条 `{path, line, column, char, codepoint, kind, excerpt}`
      （`line` / `column` 从 1 起；`char` 是原字符本身，`codepoint` 是 `U+XXXX`）；
    - `counts`：按 `kind` 汇总的真总数（六档全在，零也写出来；不受 `limit` 影响）；
    - `detail`：逐条参数路径的读数 `{path, checked, reason, files, counts, returned}`。

    `limit`（缺省 `DEFAULT_FINDINGS_LIMIT`）只管返回多少条 `findings`：
    `counts` 仍是真总数，某一条路径少给了几条由 `detail[].counts` 之和
    减 `detail[].returned` 看得出来。
    """
    if limit is None:
        cap = DEFAULT_FINDINGS_LIMIT
    else:
        cap = int(limit)
        if cap < 1:
            raise ValueError(f"limit 必须是正整数，收到 {limit!r}")

    findings: list[dict] = []
    counts: dict[str, int] = {k: 0 for k in TEXT_INTEGRITY_KINDS}
    scanned: list[str] = []
    details: list[dict] = []
    reasons: list[str] = []

    if not isinstance(paths, (list, tuple)) or not paths:
        return {
            "checked": False,
            "reason": "paths 是空的（或不是数组）⇒ 这一趟什么都没扫，不是「查过了、干净」",
            "scanned": [],
            "findings": [],
            "counts": counts,
            "detail": [],
        }

    base = Path(str(root)).resolve() if root is not None else None
    if base is None:
        return {
            "checked": False,
            "reason": "装配时没有拿到工作区根 ⇒ 这些相对路径无从解析（没查成，不是零命中）",
            "scanned": [],
            "findings": [],
            "counts": counts,
            "detail": [],
        }

    for raw in paths:
        target, why = _resolve_under(base, raw)
        entry: dict = {
            "path": str(raw),
            "checked": False,
            "reason": why,
            "files": [],
            "counts": {k: 0 for k in TEXT_INTEGRITY_KINDS},
            "returned": 0,
        }
        if target is not None:
            files, why = _expand(base, target)
            if not why:
                entry["checked"] = True
            else:
                entry["reason"] = why
        if entry["checked"]:
            for path in files:
                rel = _rel_posix(path, base)
                body, why = _read_body(path)
                if body is None:
                    entry["checked"] = False
                    entry["reason"] = (entry["reason"] + "；" if entry["reason"] else "") + why
                    continue
                scanned.append(rel)
                entry["files"].append(rel)
                got, part = _scan_text(rel, body, limit=cap - len(findings))
                findings.extend(got)
                entry["returned"] += len(got)
                for kind in TEXT_INTEGRITY_KINDS:
                    counts[kind] += part[kind]
                    entry["counts"][kind] += part[kind]
        if not entry["checked"] and entry["reason"]:
            reasons.append(entry["reason"])
        details.append(entry)

    return {
        "checked": not reasons,
        "reason": "；".join(reasons),
        "scanned": scanned,
        "findings": findings,
        "counts": counts,
        "detail": details,
    }


# ---------------------------------------------------------------- 工具装配


@tool(
    "review.scan_document",
    "全量机械审校一份稿件（引用/证据等级/否定分类/依赖闭合），每条发现带 evidence。",
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
            "'dep_check','verdict','reason','coverage','semantic_check'}；verdict ∈ {rejected, unverified, "
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
    "只读列举审校发现（可按稿件/状态/级别过滤），含 evidence。",
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
            "审一份稿件：机械发现落成 ReviewFinding（带 evidence）并更新文档状态；只写 review_findings 与 documents.status，不改 claims。"
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
    returns="{'doc_id','new_findings','duplicate_skipped','error_count','warning_count','verdict','status','signature','signature_error','coverage','checked','dep_check','info_count','reason','reopened','round','semantic_check','status_error','status_updated','paper_body','open_findings'}",
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
            "复审：对上一轮每条 finding 重跑对应检查，判 fixed / 仍 open 并逐条列出仍 open 的；收不收尾由你判断 —— 给 `close_as=\"unresolved_review\"` 才把稿件置该终态并交人复核（轮数上限已撤除，没有任何计数器会替你收尾）。"
            ),
    {
           "type": "object",
           "properties": {
            "doc_id": {"type": "string"},
            "round_no": {"type": "integer", "minimum": 1},
            "dependencies": {"type": "array", "items": {"type": "object"}},
            "close_as": {
                "type": "string",
                "enum": list(CLOSE_AS_VALUES),
                "description": (
                    "H 自己决定收尾时才给：目前唯一受控值是 `unresolved_review`。"
                    "不给 = 本趟只重审并逐条列 still_open、不收尾（没有计数器会替你收尾）"
                ),
            },
           },
           "required": ["doc_id", "round_no"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITER_ROLES,
    returns="{'doc_id','round','resolved','still_open','unresolved_findings','verdict','not_rechecked','dep_check','error_count','finding_updates','info_count','reason','semantic_check','status','status_error','status_updated','warning_count','paper_body'}",
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
            "产出完整审校报告（markdown）：报告头钉住**被审版本 hash**、每道门带零发现自证数字、必含『**我这一轮犯的错**』一节；只写报告文件。"
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
                    "**已弃用（2026-11-16 AH2b）**：G8 不再读任何回执，证据只来自 "
                    "`experiments` 台账行（脚本 + `code_hash` + `exit_code`）。"
                    "这个参数保留只为旧调用方不炸；传什么都不会改变 G8 的读数 —— "
                    "回执可以由任何一方自己写出来，不是证据"
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

@tool(
    "review.record_finding",
    (
            "把**你自己读出来的**一条发现落成 `review_findings` 行（只读角色的产出通道）。机械扫描（`review_document`）覆盖不到的用它；`evidence` 必填。"
            ),
    {
           "type": "object",
           "properties": {
            "doc_id": {"type": "string", "description": "被审稿件号"},
            "kind": {"type": "string", "enum": list(S.FINDING_KINDS),
                     "description": f"发现类别（受控词表 {list(S.FINDING_KINDS)}）"},
            "target": {"type": "string",
                       "description": "位置：claim-3 / section:2 / dep:0004 / rel:0007"},
            "message": {"type": "string", "description": "这条发现说什么（一句话）"},
            "evidence": {"type": "string",
                         "description": "凭什么这么判（必填：读数、盘上路径、回执原样）"},
            "level": {"type": "string", "enum": list(S.FINDING_LEVELS),
                      "description": "严重度（缺省 warning）"},
            "axis": {"type": "string", "enum": list(G.AXES),
                     "description": "轴（数学 / 体例 / 工程 / 证据）"},
            "suggestion": {"type": "string", "description": "最小修法"},
            "round_no": {"type": "integer", "minimum": 1,
                         "description": "审校轮次（不给时 = `documents.review_rounds` 的当前值；正常不需要给）"},
            "verbatim_quote": {"type": "string",
                               "description": "≤20 词的逐字引文（G10 那一格）"},
            "line": {"type": "integer", "minimum": 1,
                     "description": "行号（只在版本冻结后才有意义；拿不到就别给）"},
            "line_unavailable_reason": {"type": "string",
                                        "description": "拿不到行号的理由（`line` 省略时必填）"},
           },
           "required": ["doc_id", "kind", "target", "message", "evidence"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    roles=_WRITER_ROLES,
    returns=("{'checked','created','duplicate_skipped','finding_id','doc_id','kind',"
             "'level','round','status'}（`created=False` = 与已有发现去重命中，"
             "返回既有 `finding_id`，不制造重复行）"),
    tags=("review", "write"),
)
def _review_record_finding_tool(_not_wired, store, actor, **kw):
    """`review.record_finding` 的工具体（注入值由装配期用 `partial` 绑定）。"""
    return (
    _not_wired()
               if store is None
               else _guard_result(lambda: record_finding(store, actor=actor, **kw))
    )


@tool(
    "review.scan_text_integrity",
    (
        "扫一批文本里的异常字符（CJK 正文/控制符/零宽/替换符/双向/不换行空格），"
        "逐条给 文件:行:列 与码位；读不成如实报 checked=False（不许读成"
        "『零命中』），计数不受 limit 影响。目录递归 .tex/.md/.txt/.bib。"
    ),
    {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "工作区内的相对路径（文件或目录；目录递归 .tex/.md/.txt/.bib）",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": ("这一次最多返回多少条 findings（缺省 200）；"
                                "counts 是盘上的真总数，不受它限制"),
            },
        },
        "required": ["paths"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("H",),
    returns="{'checked','reason','scanned','findings','counts','detail'}",
    tags=("review", "read", "gate"),
)
def _review_scan_text_integrity_tool(root, paths, limit=None):
    """`review.scan_text_integrity` 的工具体（注入值是工作区根 `root`）。

    返回值就是 `scan_text_integrity()` 的那六个键，一个不多一个不少：
    三条路径（扫成 / 一条都没扫成 / 部分扫成）的键集必须一致，否则调用方
    得先判 `ok` 才知道能不能读 `counts` —— 那正是三态纪律要避免的形态。
    """
    return ok(scan_text_integrity(root, paths, limit=limit))


#: `review.scan` 这一趟真的接上了的类（块 1 只接 `text_integrity`，块 2 扩到七类）。
#:
#: 为什么把"契约"与"接线"分成两步：工具声明的 `kinds` 枚举是契约（一次写完，不再动
#: 工具面），而"现在真的能跑哪几类"是接线。分开之后，块 2 只改这一个元组 ——
#: `tests/golden/tool_surface_snapshot.json` 一个字节都没有重冻（重冻一次就是一轮
#: 两人复核）。不在这个元组里的类会如实进 `bad[]`（"还没接线"），不是悄悄跳过。
#:
#: 2026-11-01（块 2）：七类全部接上。判据 `tests/test_h_scan_covers_seven_kinds.py`
#: 钉住"接线面 == 契约面"，并把七类各自跑一遍（每类都有一条该报的、也都有一条干净的）。
_WIRED_KINDS: tuple[str, ...] = TEX.SCAN_KINDS


@tool(
    "review.scan",
    (
        "把一份稿件的机械读数一次拿全（七类 kinds 任选）：异常字符 / \\cite 对 \\bibitem / "
        "\\input 目标 / \\ref 对 \\label / theorem 对 proof / 重复声明 / 正文与台账的数。"
        "只读、只给读数；七类各自的三态在 detail[]，没查成的在 bad[]。"
        ),
    {
        "type": "object",
        "properties": {
            "kinds": {
                "type": "array",
                "items": {"type": "string", "enum": list(TEX.SCAN_KINDS)},
                "description": (
                    "要查的类（可多选）。text_integrity=六类异常字符；cites=\\cite 键 ⊆ "
                    "\\bibitem 键；inputs=\\input 目标在盘上；refs=\\ref 家族键 ⊆ \\label 键；"
                    "proofs=定理类环境 ↔ proof 配对；duplicates=\\label/\\newtheorem 重名；"
                    "ledger_match=正文/台账/对应表的五个数与多出来的环境"),
                "minItems": 1,
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "工作区内的相对路径（文件或目录；目录递归 .tex/.md/.txt/.bib）。"
                    "缺省 = project 的 out/paper/main.tex（给了 project 才缺省）"),
            },
            "project": {
                "type": "string",
                "description": (
                    "论文项目根（工作区相对；`out/paper/main.tex` 在它下面）。"
                    "只有 ledger_match 必须给它；不给 ⇒ 那一类如实报没查成"),
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "这一次最多返回多少条 findings（缺省 200）；counts 是盘上真总数，"
                    "不受它限制"),
            },
        },
        "required": ["kinds"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("H",),
    returns=(
        "{'checked','kinds','findings','counts','bad','detail','scanned','reason'}；"
        "findings[] 每项九键 {'kind','severity','file','line','column','text','why','ref',"
        "'codepoint'}；detail[] 每项六键 {'kind','checked','reason','scanned','counts',"
        "'returned'}；counts={'files','findings','by_kind','by_severity','facts'}；"
        "checked=False 只表示没查成（哪一类没查成见 bad[]），不是『零命中』"
        ),
    tags=("review", "read", "gate"),
)
def _review_scan_tool(root, kinds, paths=None, project=None, limit=None):
    """`review.scan` 的工具体（注入值是工作区根 `root`）。

    这一层只做三件工具层该做的事，读数一律由 `texaudit.scan_tex()` 给：
    ① 路径解析与目录递归（复用 `_resolve_under` / `_expand`，与 `review.scan_text_integrity`
    同一道闸 —— 只读不等于无边界）；② 解析失败逐条记成 `path_problems`（不静默跳过）；
    ③ 把 `scan_text_integrity` 这件既有实现按引用传进去（六类字符只有一份实现，
    这里不另写一套）。
    """
    base = Path(str(root)).resolve() if root is not None else None
    files: list[Path] = []
    problems: list[dict] = []
    raw_paths = [str(p) for p in (paths or ())]
    if base is None:
        problems.append({"path": "", "why": (
            "装配时没有拿到工作区根 ⇒ 相对路径无从解析（这一趟没查成，不是零命中）")})
    else:
        for raw in raw_paths:
            target, why = _resolve_under(base, raw)
            if target is None:
                problems.append({"path": raw, "why": why})
                continue
            expanded, why = _expand(base, target)
            if why:
                problems.append({"path": raw, "why": why})
                continue
            files.extend(expanded)
    project_path = None
    if project is not None:
        if base is None:
            problems.append({"path": str(project), "why": "没有工作区根 ⇒ project 无从解析"})
        else:
            project_path, why = _resolve_under(base, str(project))
            if project_path is None:
                problems.append({"path": str(project), "why": why})
    return ok(TEX.scan_tex(
        base,
        kinds=list(kinds),
        files=files,
        path_problems=problems,
        project=project_path,
        limit=limit,
        text_integrity=scan_text_integrity,
        raw_paths=raw_paths,
        wired=_WIRED_KINDS,
    ))


#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
#: 声明随函数走（`@tool` 写进 `fn.__tool_spec__`），这里只列装配要做的事。
_READ_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_review_scan_document_tool, ()),
    (_review_list_findings_tool, ('_not_wired', 'store')),
    # 2026-10-30（业主：「给 H 加个工具审」）：唯一一件要工作区根的审校工具 ——
    # 其余四件的输入都是台账行或稿件对象，只有它按相对路径去盘上读正文。
    (_review_scan_text_integrity_tool, ('root',)),
    # 2026-11-01（业主：「将 H 的所有机械扫描工具统一成一个方便 H 使用」）：
    # 统一入口。默认面因此多一件只读工具（两条写死名单的判据要有人认一次账）。
    (_review_scan_tool, ('root',)),
)

#: 会写盘的三个入口：默认不装（结构约束：H 的工具面必须全 read/none）。
#: 它们与只读面分表，正是因为"装与不装"由 `include_writers` 决定 ——
#: 混成一张表会让"默认不装"这件事无处表达（`T-8` 搬移时实测过：
#: 不拆表的话三个写工具会绕过那句早退，H 的工具面当场多出写入口）。
_WRITE_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_review_review_document_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
    (_review_verify_fixes_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
    (_review_report_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
    # 2026-10-18：H 自己的发现也要有落点（`review_document` 只落机械扫描算出来的那批）。
    (_review_record_finding_tool, ('_not_wired', 'store', 'actor')),
)


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    include_writers: bool = False,
    actor: str = "agent-H",
    semantic_judge: Any = None,
    root: Any = None,
    **_: Any,
) -> None:
    """装配审校工具。

    `root`（2026-10-30 加）：工作区根，只喂给 `review.scan_text_integrity` 那一件
    —— 它按相对路径去盘上读正文，其余四件的输入是台账行或稿件对象，不需要根。
    由 `build_registry` 的装配期注入（`deps["workspace_root"]`）；直接调
    `register()` 而不给根时那件工具会如实报 `checked=False`（「没查成」），
    不会静默按当前工作目录去读一个别的项目。

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
    _bound['root'] = root
    for _fn, _deps in _READ_TOOL_FUNCTIONS:
        registry.register(replace(_fn.__tool_spec__,
                                  handler=partial(_fn, *[_bound[k] for k in _deps])))


    if not include_writers:
        # 默认面到此为止：全部 none/read。写入口需要显式打开。
        return

    for _fn, _deps in _WRITE_TOOL_FUNCTIONS:
        registry.register(replace(_fn.__tool_spec__,
                                  handler=partial(_fn, *[_bound[k] for k in _deps])))



