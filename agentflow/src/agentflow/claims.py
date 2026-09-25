"""原子断言拆分 —— 把一段模型答复切成一堆可逐条回验的断言（唯一判据来源）。

## 这个模块为什么存在

`run_topic` 此前的 `claims.json` 有两个耦合在一起的毛病：

1. 台账的条数等于"模型一次答复里给了几条引文"，而不是"这段答复里有多少条断言"。
   一段没有按 `- 结论 || 引文` 写的答复（例如一段普通散文）在台账里是零条 ——
   而零条读起来像"这篇没有结论"，不像"我们没拆"；
2. `NOT_WIRED_ITEMS` 里一直挂着 `claims_ledger`：把答复拆成完整断言台账的那一层
   没实现。一篇论文级的产出无法被拆成可逐条回验的原子断言，是"能不能比拼
   数学产出"的直接卡口。

拆分的判据（哪些算一条断言、依据是什么、超上限怎么办）只在本模块实现一次
（FC-03：同一判据只许一处实现）。`evidence.parse_claims` 与
`evidence.verify_claims` 都不另写一份：前者转发到 :func:`parse_claims`，
后者只负责判决，两者在本模块的 :func:`ledger_rows` 里合成台账。

本模块刻意不 import `evidence`：`evidence` 要用本模块的拆分，反向 import 会成环。
判决词表因此在本模块留了一份同名常量，并由测试断言它与 `evidence.VERDICTS` 逐字相同。

## 拆分的三层，顺序是刻意的

第一层是模型自己给出的结构：`- 结论 || 引文` 与 `断言：X | 引文：Y`。
这一层的依据最硬 —— 分隔符是模型写的，不是我们猜的，所以它先跑：
先切句子再切引文，会把引文里本来就含句末标点的那半句切成两条假断言。

第二层是列表结构：行首的项目符号与编号（`-` / `*` / `1.` / `2)`）。
一个列表项就是一条断言，这是作者写下来的结构。

第三层是句子边界：句末标点（`.。!！?？;；` 后跟空白或行尾）与换行。
这是兜底层，也是"散文式答复"能被拆开的唯一依据 —— 此前这类答复在台账里是零条。

每一层都写明它为什么在这里、以及它可能误判成什么。

## 三态，空集绝不许当成功

:data:`SPLIT_STATUSES` 只有三个值：

- `parsed`：拆出至少一条断言；
- `no_claims`：读过了，但这段答复里确实没有任何可断言的句子（例如
  "没有检索到相关材料，我无法给出结论"）—— 必须带理由，且 :func:`refusal_reason`
  用一个写下来的措辞表判定它，理由是它可以被反驳、被审计；
- `unparsable`：压根处理不了（空串、空白串，或一个非空输入里连一个可读的
  字符片段都没有）。

三个值之外没有第四个"成功但没有断言"。空集永远落在 `no_claims` 或 `unparsable`
上，且两者都必须带非空理由 —— 把空集当成功，正是 P16 记过的"判据真空通过"。

## 不许静默丢弃

两条纪律，各有对应用例：

1. 没有引文的断言也要落台账，判决是 `known_unverifiable`（已知无法逐字回验），
   绝不因为"它没有引文"就从台账里消失。从台账里删掉它，会让"我们没验这一条"
   看起来像"这条断言不存在"；
2. 截断要写在产物里：`max_claims` 是硬上限，超出的条数记在
   :attr:`SplitResult.truncated` 与 :attr:`SplitResult.total_found` 里，
   并原样写进 `claims.json`。静默截断会让"200 条"看起来像"一共 200 条"。

## 可复现性：确定性优先，注入的模型只做"补刀"

:func:`split_claims` 的 `parse_fn` 默认 `None`（生产即纯启发式，同一输入必得同一输出）。
注入 `parse_fn` 时它的结果同样经过归一、去重、按 `max_claims` 截断，
且 :attr:`SplitResult.fingerprint` 把输入、上限、用没用 `parse_fn` 与最终结论
一起钉进产物 —— 换一次拆分口径必须能从产物里看出来。

刻意不把拆分做成"再问一次模型，它说几条就是几条"：那种拆分无法复核 ——
同一份答复两次拆出不同条数时，没有任何东西会报错。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "BASES",
    "DEFAULT_MAX_CLAIMS",
    "LEDGER_ROW_KEYS",
    "NO_CLAIM_MARKERS",
    "PARSE_FN_ERROR",
    "SPLIT_STATUSES",
    "VERDICTS",
    "SplitClaim",
    "SplitResult",
    "ledger_rows",
    "merge_splits",
    "parse_claims",
    "refusal_reason",
    "split_claims",
]

#: 拆分结局的受控词表。空集绝不许折叠成"成功"。
SPLIT_STATUSES: tuple[str, ...] = ("parsed", "no_claims", "unparsable")

#: 判决词表（唯一权威定义在 `evidence.VERDICTS`；这一份是它的同名副本，
#: 存在的理由是 `evidence` 要 import 本模块、反向 import 会成环。
#: `tests/test_evidence.py::test_verdict_vocabulary_has_exactly_one_authority`
#: 断言两边逐字相同 —— 所以这不是第二份判据，而是一份被钉住的副本。
VERDICTS: tuple[str, ...] = ("verified", "not_found", "known_unverifiable", "unknown")

#: 台账每一行必须有的键。为什么写成常量：`run_topic` 的产物、报告的证据段
#: 与测试三处都要判"这一行齐不齐"，写在三处的判据早晚会漂移。
LEDGER_ROW_KEYS: tuple[str, ...] = (
    "claim_id", "text", "quote", "verdict", "level", "locator",
    "evidence_source", "checked", "reason", "basis",
)

#: 拆分依据的受控词表：每一条都对应上面某一层。产物里写的是这里的一个值，
#: 而不是一句自由文本 —— 自由文本没法被统计，于是"这次拆分为什么是这个粒度"
#: 会永远只能靠人读一遍答复去猜。
BASES: tuple[str, ...] = (
    "quote_marker",   # 模型自己写的 `||` 分隔符
    "parsed_fn",      # 注入的 parse_fn 给出的候选
    "labelled",       # `断言：X | 引文：Y` 这种带标签的写法
    "numbered",       # 行首编号（`1.` / `2)`）
    "bullet",         # 行首项目符号（`-` / `*` / `•`）
    "sentence_end",   # 句末标点或换行
)

#: 缺省上限。200 是一个刻意的数字：单条答复拆到 200 条已经远超一次调用的正常规模，
#: 超过它多半是"模型把一整篇复述回来了"，那种答复本来就该被截断并写明。
DEFAULT_MAX_CLAIMS = 200

#: 注入的 `parse_fn` 抛异常时，台账 :attr:`SplitResult.errors` 里的前缀。
PARSE_FN_ERROR = "parse_fn_failed"

#: "确实没有可断言内容"的措辞表。判据是写下来的、可反驳的：
#: 加了它，一段"我不知道"会被判 `no_claims`（带理由），而不是 `unparsable`。
#: 为什么不用"语义上像不像拒绝"去判：判不了的东西不该伪造成判据 ——
#: 表里的每一条都能被人一眼反驳，而"模型觉得像"不能。
NO_CLAIM_MARKERS: tuple[str, ...] = (
    "没有可依据的内容", "没有检索到", "无法给出结论", "无法给出任何结论",
    "无法确定", "不能确定", "不确定", "无法判断", "没有材料", "材料中没有",
    "没有相关材料", "i cannot", "i can't", "i don't know", "insufficient",
    "no material", "no relevant", "not enough information", "unable to determine",
    "unknown at this time", "无法作答", "无可奉告",
)

#: 行首列表标记（与 `evidence._BULLET` 同一形态；这里带上"是哪一种"的判据）。
_LINE_MARK = re.compile(r"^\s*(?P<mark>[-*\u2022\u00b7]|\d{1,3}\s*[.、)）])\s*")
#: 形如 `## 证据` / `# 报告` 的标题行：结构行，不是断言。
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
#: 代码围栏（``` 或 ~~~）：围栏内是代码，逐字回验的是自然语言断言。
_FENCE = re.compile(r"^\s*(?:```|~~~)")
#: 模型写的引文分隔符（`||` / `｜｜`）。
_QUOTE_BREAK = re.compile(r"\s*(?:\|\||｜｜)\s*")
#: 带标签的写法：`断言：X | 引文：Y` / `- 结论：X ｜ 引文：Y`。
#: 判据刻意只认这两个标签：放开成"任何 `A：B`"会把 `注：见上文` 这种行
#: 也当成断言 + 引文，而那是一次假的逐字回验。
_LABELLED = re.compile(
    r"^\s*(?:断言|结论)\s*[：:]\s*(?P<text>.*?)"
    r"(?:\s*[|｜]\s*引文\s*[：:]\s*(?P<quote>.*))?$"
)
#: 句末标点：后跟空白或行尾才算句子边界。为什么要求后跟空白：
#: 这样 `u.s.` 这类缩写内部不会被切开（`.` 后面是字母），
#: 而中文没有空格，所以 `。` 单独成一类（它后面允许直接接下一句）。
_SENTENCE_END = re.compile(r"(?<=[.!?;])(?=\s)|(?<=[。！？；…])")
#: 行内的换行（对已经按行切过的输入它不会再命中，留着是为了 `parse_fn`
#: 直接喂一整段多行文本的那种用法）。
_HARD_BREAK = re.compile(r"\n+")

#: `parse_fn` 的签名：`(text, *, max_claims) -> 候选断言序列`。
ParseFn = Callable[..., Sequence[Any]]


@dataclass(frozen=True)
class SplitClaim:
    """一条原子断言（拆分层的产物）。

    `text` 是断言本身，`quote` 是它依据的原文片段（可能为空 —— 空的会被
    :func:`ledger_rows` 判成 `known_unverifiable`，绝不消失）。
    `basis` 说明"它是被哪一层切出来的"：产物里少了它，读者只能逐条重读
    原始答复去猜拆分为什么是这个粒度，而那种猜法每次都不一样。
    """

    index: int
    text: str
    quote: str
    basis: str
    origin: str = ""

    def to_dict(self) -> dict:
        """落产物的扁平结构（键名与 `evidence.verify_claims` 的输入同形）。"""
        return {"index": self.index, "text": self.text, "quote": self.quote,
                "basis": self.basis, "origin": self.origin}


@dataclass
class SplitResult:
    """一次拆分的完整结论（三态 + 计数 + 截断 + 依据分布 + 指纹）。

    为什么每一件事都要在这里有一格：

    - `status` 与 `reason` 一起回答"这次拆成了什么"；`no_claims` 的 `reason`
      必须来自 :func:`refusal_reason` 的措辞表，不许写"没有断言"这种同义反复；
    - `truncated` 与 `total_found` 一起回答"被丢掉了多少条"，且满足一条恒等式：
      `len(claims) + truncated == total_found`（被丢掉的那些既不在台账里，
      也不参与任何计数 —— 所以这个差额必须写在产物里，不能靠读的人自己减）；
    - `basis_counts` 回答"这次是按哪一层拆的"（全是 `sentence_end` 说明模型
      没按约定格式作答，粒度是兜底给的）；
    - `fingerprint` 让"同一输入两次拆出不同结果"变成可测的事；
    - `parse_fn_error` 只记注入实现自己的失败（异常类型与消息），
       它不是判决 —— 判决在 `status` 里，且失败时通常是 `parsed`（退回启发式）。
    """

    status: str
    claims: list[SplitClaim] = field(default_factory=list)
    reason: str = ""
    max_claims: int = DEFAULT_MAX_CLAIMS
    total_found: int = 0
    truncated: int = 0
    basis_counts: dict[str, int] = field(default_factory=dict)
    parse_fn_used: bool = False
    parse_fn_error: str = ""
    errors: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def to_dict(self) -> dict:
        """落产物用的结构（`claim_count` 与 `claims` 的长度必须相等）。"""
        return {
            "status": self.status,
            "reason": self.reason,
            "claim_count": len(self.claims),
            "total_found": self.total_found,
            "truncated": self.truncated,
            "max_claims": self.max_claims,
            "basis_counts": dict(self.basis_counts),
            "parse_fn_used": self.parse_fn_used,
            "parse_fn_error": self.parse_fn_error,
            "errors": list(self.errors),
            "fingerprint": self.fingerprint,
            "claims": [c.to_dict() for c in self.claims],
        }


# ------------------------------------------------------------------ 拆分三个层


def _norm_ws(text: str) -> str:
    """压掉连续空白（保留单个空格），顺手去掉首尾空白。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _has_readable(text: str) -> bool:
    """输入里有没有可读字符（字母/数字/汉字）？

    为什么它是 `no_claims` 与 `unparsable` 的分界：三态要求"读过了、确实没有"
    与"压根读不动"分得开。一句拒绝（"我无法给出结论。"）是可读的文本 ⇒
    `no_claims`；一串标点（"????"）没有任何可断言的句子 ⇒ 也不该叫"读过了"。
    判据只认字母/数字/汉字，不认标点，是因为标点本身不承载断言。
    """
    return bool(re.search(r"[0-9A-Za-z\u4e00-\u9fff]", text or ""))


def _split_sentences(segment: str) -> list[str]:
    """按句末标点把一个片段切成句子（空片段与全空白片段被丢掉）。

    为什么要单独成函数：它是第三层唯一的判据，而"哪算一个句子"这件事
    一旦散在几处，拆出来的条数就会随地漂移，且没有任何地方会报错。
    """
    out: list[str] = []
    for piece in _SENTENCE_END.split(segment):
        for sub in _HARD_BREAK.split(piece):
            clean = _norm_ws(sub)
            # 只有"含可读字符"的片段才算一句：一串纯标点（`?????`）切出来
            # 的"句子"不是句子，把它当成一条断言会让台账里出现一条
            # 谁也不认识的断言。
            if clean and _has_readable(clean):
                out.append(clean)
    return out


def _from_left(left: str, *, quote: str, basis: str) -> list[SplitClaim]:
    """把"引文左边的那段文字"展开成一到多条候选断言（还没有编号）。

    `basis` 是切出引文的那一层（`quote_marker` / `labelled`）。当左边本身
    含多句时，真正切分它的是句末标点，所以那一条的 `basis` 落 `sentence_end`
    —— 依据要写"实际起作用的那一条"，否则产物里的依据分布会撒谎。
    """
    text = _norm_ws(left)
    if not text:
        return []
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return [SplitClaim(index=0, text=text, quote=_norm_ws(quote), basis=basis)]
    return [SplitClaim(index=0, text=s, quote=_norm_ws(quote), basis="sentence_end")
            for s in sentences]


def _lines_of(text: str) -> tuple[list[str], list[str]]:
    """按行切，并返回 `(有效行, 代码围栏内被跳过的行)`。

    为什么跳过围栏内的行：围栏里是代码，逐字回验的对象是自然语言断言。
    把代码行当断言会在台账里造出一堆永远 `not_found` 的"断言"，
    而它们会稀释真正需要被看的那几条。跳过的行不静默消失 —— 它们计入
    :attr:`SplitResult.errors` 之外的一个计数（见 `_missing_reason` 的措辞）。
    """
    kept: list[str] = []
    fenced: list[str] = []
    inside = False
    for raw in str(text or "").splitlines():
        if _FENCE.match(raw):
            inside = not inside
            continue
        (fenced if inside else kept).append(raw)
    return kept, fenced


def _heuristic_claims(text: str) -> tuple[list[tuple[str, str, str]], list[str], int]:
    """三层启发式拆分：返回 `(候选, 备注, 被跳过的代码行数)`。

    候选是 `(text, quote, basis)` 三元组，顺序就是它们在原文里出现的顺序。
    这里不编号、不去重、不截断：那三件事由 :func:`split_claims` 统一做 ——
    判据只许有一处，写在两处必然漂移。
    """
    out: list[tuple[str, str, str]] = []
    notes: list[str] = []
    lines, fenced = _lines_of(text)
    if fenced:
        notes.append(f"跳过了 {len(fenced)} 行代码围栏内的内容"
                     "（围栏里是代码，逐字回验的对象是自然语言断言）")

    for raw in lines:
        if _HEADING.match(raw):
            # 标题行是结构，不是断言。它不落台账，但要留下计数：
            # 否则"这段答复里有多少行"与"拆出多少条断言"对不上时无人能解释。
            notes.append("跳过了标题行（`#` 开头：它是结构，不是断言）")
            continue
        mark = _LINE_MARK.match(raw)
        basis = "numbered" if mark and mark.group("mark")[0].isdigit() else (
            "bullet" if mark else "")
        line = _LINE_MARK.sub("", raw, count=1)
        if not line.strip():
            continue
        parts = _QUOTE_BREAK.split(line, maxsplit=1)
        if len(parts) == 2:
            left, quote = parts[0], parts[1]
            if _norm_ws(quote):
                out.extend((c.text, c.quote, c.basis)
                           for c in _from_left(left, quote=quote, basis="quote_marker"))
                continue
            # 分隔符写了、引文是空的：这仍然是一条断言（依据为空），
            # 但左边若含多句，得继续按句切 —— 所以下面走同一段兜底逻辑。
            notes.append("有一处 `||` 的右边是空的 ⇒ 那条断言按「没有可回验依据」登记")
            line = left
        m = _LABELLED.match(line)
        if m and _norm_ws(m.group("text")):
            label_basis = "labelled" if m.group("quote") else basis or "labelled"
            out.extend((c.text, c.quote, c.basis)
                       for c in _from_left(m.group("text"), quote=m.group("quote") or "",
                                           basis=label_basis))
            continue
        if basis:
            sentences = _split_sentences(line)
            for s in sentences:
                out.append((s, "", "sentence_end" if len(sentences) > 1 else basis))
            continue
        for s in _split_sentences(line):
            out.append((s, "", "sentence_end"))
    return out, notes, len(fenced)


def _candidates_from_fn(parse_fn: ParseFn, text: str, *, max_claims: int
                        ) -> tuple[list[tuple[str, str, str]], str]:
    """调一次注入的 `parse_fn` 并把它的产物归一成与启发式同形的候选。

    为什么归一而不是信它："模型说有 7 条"与"答复里真有 7 条"是两件事。
    注入的只提供文本，编号、去重、上限与判决全部走同一套判据。
    抛异常不冒泡：那会把"辅助拆分失败"变成"整个拆分没跑成"，
    而降级到启发式仍然是一次有效的拆分 —— 失败事实记在
    :attr:`SplitResult.parse_fn_error` 与 `errors` 里。
    """
    try:
        raw = parse_fn(text, max_claims=max(1, int(max_claims)))
    except Exception as exc:  # 注入实现抛异常 = 辅助拆分没跑成，不许冒泡毁掉整次拆分
        # 前缀随错误一起返回：`parse_fn_error` 字段要能自证它属于哪一类失败
        # （"辅助拆分坏了"与"回验器坏了"是两件事，而两者的消息体可能都只是一个异常串）。
        return [], f"{PARSE_FN_ERROR}: {type(exc).__name__}: {exc}"
    if raw is None or isinstance(raw, (str, bytes, Mapping)):
        return [], (f"{PARSE_FN_ERROR}: 返回了 {type(raw).__name__} 而不是断言序列 ⇒ "
                    "无法判断是没拆出来还是坏掉了")
    out: list[tuple[str, str, str]] = []
    for item in list(raw):
        if isinstance(item, Mapping):
            claim_text = _norm_ws(item.get("text") or item.get("claim") or item.get("statement"))
            quote = _norm_ws(item.get("quote"))
        else:
            claim_text, quote = _norm_ws(item), ""
        if claim_text:
            out.append((claim_text, quote, "parsed_fn"))
    return out, ""


# ------------------------------------------------------------------ 无断言的理由


def refusal_reason(text: str) -> str:
    """为什么这段答复"确实没有可断言的句子" —— 返回非空理由。

    为什么需要它：`no_claims` 与 `unparsable` 都是空集，而它们要的处置完全不同 ——
    前者的处置是"这次主题没有材料可依据"，后者是"我们没拆成"。
    理由必须是一句能被人反驳的话，所以判据取自写下来的措辞表
    （:data:`NO_CLAIM_MARKERS`）加上两个结构事实（有没有句末标点、
    有没有任何可读的字母/数字）。措辞表可以被反驳、可以被审计；
    "模型觉得像拒绝"不能。
    """
    body = _norm_ws(text)
    hits = [m for m in NO_CLAIM_MARKERS if m.lower() in body.lower()]
    if hits:
        return (f"答复里命中了拒绝措辞「{'、'.join(hits)}」 ⇒ 本次确实没有"
                "可断言的结论（不是‘拆不出来’）")
    if not _has_readable(body):
        return ("整段输入里没有一个字母或数字（只有标点/符号/空白）⇒ "
                "它没有任何可原子化的句子（不是‘拆成了零条’）")
    if not _SENTENCE_END.search(body):
        return ("整段答复里没有一个句末标点，也没有列表项 ⇒ 它没有任何"
                "可原子化的句子（不是‘拆成了零条’）")
    return ("读过了，但没有一行构成可断言的句子（既没有可回验的引文，"
            "也没有独立的陈述句）⇒ 本次确实没有可断言的结论")


def _missing_reason(text: str, notes: Sequence[str], fenced: int) -> str:
    """一个非空输入拆出零条时，把"为什么"写清（含被跳过的行数与备注）。"""
    why = refusal_reason(text)
    bits = [why]
    if fenced:
        bits.append(f"另有 {fenced} 行代码围栏内容不在断言范围内")
    if notes:
        bits.append("备注：" + "；".join(dict.fromkeys(notes)))
    return "；".join(bits)


# ------------------------------------------------------------------ 主入口


def _fingerprint(text: str, *, max_claims: int, parse_fn_used: bool,
                 claims: Sequence[SplitClaim]) -> str:
    """把"这次拆的是哪段输入、用什么限度、拆成了什么"钉成一串哈希。

    为什么要它：同一份答复两次拆出不同条数时，若不记录输入与结论，
    就没有任何东西能发现口径漂移（而漂移的表现只是"报告里的数字不一样"）。
    输入参与哈希（不是只哈希结论）是刻意的：改了输入当然会改结论，
     但产物里必须能看出输入也变了。
    """
    digest = hashlib.sha256()
    digest.update(text.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(str(int(max_claims)).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(b"fn" if parse_fn_used else b"heuristic")
    for claim in claims:
        digest.update(b"\x01")
        digest.update(claim.text.encode("utf-8"))
        digest.update(b"\x02")
        digest.update(claim.quote.encode("utf-8"))
    return digest.hexdigest()


def _assemble(status: str, reason: str, *, raw: Sequence[tuple[str, str, str]],
              max_claims: int, parse_fn_used: bool, parse_fn_error: str,
              errors: Sequence[str], notes: Sequence[str], text: str,
              fenced: int = 0, found_before: int | None = None) -> SplitResult:
    """去重、编号、截断、算依据分布与指纹（`split_claims` 的唯一汇总点）。

    为什么去重按 `(text, quote)`：同一段答复里两行给出同一条断言，是模型
    重复了，不是两条独立结论。不去重会让台账条数虚高，而虚高的条数
    会让"逐字通过率"看起来更好也更容易被误读。

    截断的算法只有一条恒等式：`被丢掉的 = 共查出 - 登记`（见 :attr:`SplitResult`）。
    `found_before` 是给 :func:`merge_splits` 用的：合并多段答复时"共查出多少条"
    必须把每一段自己截掉的那些也算进来，否则总数会显得比实际小，
    而"截断"这个数字就不诚实了。
    """
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str, str]] = []
    for claim_text, quote, basis in raw:
        if not claim_text:
            continue
        key = (claim_text, quote)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((claim_text, quote, basis))

    limited = deduped[: max(1, int(max_claims))]
    total_found = len(deduped) if found_before is None else int(found_before)
    truncated = max(0, total_found - len(limited))
    claims = [SplitClaim(index=i, text=t, quote=q, basis=b)
              for i, (t, q, b) in enumerate(limited, start=1)]
    basis_counts: dict[str, int] = {name: 0 for name in BASES}
    for claim in claims:
        basis_counts[claim.basis] = basis_counts.get(claim.basis, 0) + 1

    all_errors = list(errors)
    if truncated:
        all_errors.append(
            f"断言数超过上限 {max_claims}：共拆出 {total_found} 条，"
            f"已截断 {truncated} 条（被截断的那些不在台账里，也不参与任何计数）"
        )
    if status == "parsed" and truncated:
        reason = (reason + "；" if reason else "") + \
            f"共拆出 {total_found} 条，按上限 {max_claims} 截断后登记 {len(claims)} 条"
    if status == "parsed" and notes:
        reason = (reason + "；" if reason else "") + "备注：" + "；".join(dict.fromkeys(notes))
    return SplitResult(
        status=status, claims=claims, reason=reason, max_claims=max(1, int(max_claims)),
        total_found=total_found, truncated=truncated, basis_counts=basis_counts,
        parse_fn_used=parse_fn_used, parse_fn_error=parse_fn_error, errors=all_errors,
        fingerprint=_fingerprint(text, max_claims=max_claims, parse_fn_used=parse_fn_used,
                                 claims=claims),
    )


def merge_splits(parts: Sequence[Any], *, max_claims: int = DEFAULT_MAX_CLAIMS,
                 text: str = "") -> SplitResult:
    """把多段答复的拆分结论合成一份台账（跨次调用去重 + 全局截断）。

    为什么要它：`run_topic` 可能调多次模型，每次答复各拆一份。分开写进产物
    会让"这次一共拆出多少条"没有答案，而合在一处又必须重新去重（两次调用
    回同一句话是重复，不是两条结论）。

     截断在这里是全局判据：每一段自己可能已经截过一次，所以
    :attr:`SplitResult.total_found` 会把那些也算进来（见 `_assemble` 的
    `found_before` / `already_truncated`）。不这样算，多段合并后的
    "被截断多少条"会比实际小 —— 而那个数字正是本模块要保证诚实的东西。

    各段的状态在这里合成一条：任一段 `parsed` ⇒ 整份台账 `parsed`；
    全都没拆出时取最重的那一档（`unparsable` 重于 `no_claims`）——
    "有一段压根没拆成"不能被"另一段确实没有断言"盖掉。
    """
    limit = max(1, int(max_claims))
    raw: list[tuple[str, str, str]] = []
    found = 0
    seen_keys: set[tuple[str, str]] = set()
    statuses: list[str] = []
    reasons: list[str] = []
    errors: list[str] = []
    parse_fn_used = False
    parse_fn_error = ""
    for part in parts:
        if isinstance(part, Mapping):
            claims = part.get("claims") or []
            statuses.append(_norm_ws(part.get("status")))
            if _norm_ws(part.get("reason")):
                reasons.append(_norm_ws(part.get("reason")))
            errors.extend(str(e) for e in (part.get("errors") or []))
            found += int(part.get("total_found") or len(claims))
            parse_fn_used = parse_fn_used or bool(part.get("parse_fn_used"))
            parse_fn_error = parse_fn_error or _norm_ws(part.get("parse_fn_error"))
        else:
            claims = getattr(part, "claims", []) or []
            statuses.append(_norm_ws(getattr(part, "status", "")))
            if _norm_ws(getattr(part, "reason", "")):
                reasons.append(_norm_ws(getattr(part, "reason", "")))
            errors.extend(str(e) for e in (getattr(part, "errors", None) or []))
            found += int(getattr(part, "total_found", 0) or len(claims))
            parse_fn_used = parse_fn_used or bool(getattr(part, "parse_fn_used", False))
            parse_fn_error = parse_fn_error or _norm_ws(getattr(part, "parse_fn_error", ""))
        for claim in claims:
            if isinstance(claim, Mapping):
                claim_text, quote = _norm_ws(claim.get("text")), _norm_ws(claim.get("quote"))
                basis = _norm_ws(claim.get("basis")) or "quote_marker"
            else:
                claim_text = _norm_ws(getattr(claim, "text", ""))
                quote = _norm_ws(getattr(claim, "quote", ""))
                basis = _norm_ws(getattr(claim, "basis", "")) or "quote_marker"
            if not claim_text or (claim_text, quote) in seen_keys:
                continue
            seen_keys.add((claim_text, quote))
            raw.append((claim_text, quote, basis))

    if "parsed" in statuses:
        status = "parsed"
    elif not statuses:
        status = "unparsable"
    elif "unparsable" in statuses:
        status = "unparsable"
    else:
        status = "no_claims"
    reason = "；".join(dict.fromkeys(r for r in reasons if r))
    return _assemble(status, reason, raw=raw, max_claims=limit,
                     parse_fn_used=parse_fn_used, parse_fn_error=parse_fn_error,
                     errors=list(dict.fromkeys(errors)), notes=[], text=text,
                     found_before=found)


def split_claims(text: Any, *, max_claims: int = DEFAULT_MAX_CLAIMS,
                 parse_fn: ParseFn | None = None) -> SplitResult:
    """把一段模型答复拆成原子断言台账（三态 + 计数 + 截断 + 依据）。

    返回 :class:`SplitResult`。三态见模块 docstring；空集一律落在
    `no_claims`（带理由）或 `unparsable` 上，绝不落在 `parsed` 上。

    `parse_fn` 是唯一的测试/生产接缝，默认 `None` 即纯启发式（同一输入必得
    同一输出）。注入时它只提供候选，编号、去重、上限与指纹仍由本函数决定；
    它抛异常只是让本次退回启发式，并把失败写进 `parse_fn_error` 与 `errors`
    —— 让辅助拆分的一次失败把整次拆分化成"没拆成"，会把一次可用的拆分丢掉。

    为什么上限是参数而不是常量：上限必须能被调用方按场景收紧（例如某次运行
    只想看前 20 条），而"被截断多少条"必须随之一起记账 —— 截断与记账
    分开写在两处，就是"数字看起来对、实际少了几条"的那种缺陷。

    `no_claims` 与 `unparsable` 的分界只有一条结构判据：输入里有没有可读的
    字母/数字（:func:`_has_readable`）。拒绝措辞（:data:`NO_CLAIM_MARKERS`）
    优先于句子拆分，但只在没有引文候选时生效 —— 见函数体内的说明。
    """
    limit = max(1, int(max_claims))
    body = "" if text is None else str(text)
    stripped = body.strip()

    errors: list[str] = []
    parse_fn_error = ""
    parse_fn_used = parse_fn is not None
    from_fn: list[tuple[str, str, str]] = []
    if parse_fn is not None and stripped:
        from_fn, parse_fn_error = _candidates_from_fn(parse_fn, stripped, max_claims=limit)
        if parse_fn_error:
            errors.append(f"{parse_fn_error} ⇒ 本次退回启发式拆分（不是‘没拆出断言’）")
    if not stripped:
        return _assemble(
            "unparsable", "输入是空串或全空白 ⇒ 没有任何可处理的文本（不是‘没有断言’）",
            raw=[], max_claims=limit, parse_fn_used=parse_fn_used,
            parse_fn_error=parse_fn_error, errors=errors, notes=[], text=body,
        )

    heuristic, notes, fenced = _heuristic_claims(stripped)

    # 拒绝答复先判：一段"材料中没有可依据的内容，我无法给出结论。"按句子会被
    # 切成一条断言 —— 而它恰恰是"这次没有结论"的那句话。把它登记成一条断言，
    # 会让空台账看起来像"有 1 条断言"，那是本模块最要防的读法。
    # 判据只在没有引文候选时生效：模型真的给了引文时，"有引文"比"命中拒绝措辞"
    # 强，不许因为一句客套话把真断言丢掉。
    refusals = [m for m in NO_CLAIM_MARKERS if m.lower() in stripped.lower()]
    if refusals and not from_fn and not any(q for _t, q, _b in heuristic):
        reason = _missing_reason(stripped, notes, fenced)
        return _assemble("no_claims", reason, raw=[], max_claims=limit,
                         parse_fn_used=parse_fn_used, parse_fn_error=parse_fn_error,
                         errors=errors, notes=notes, text=body, fenced=fenced)

    raw = from_fn + heuristic

    if raw:
        basis_top = "parse_fn" if from_fn else "启发式"
        reason = (f"按{basis_top}拆分：查出 {len(raw)} 处候选，"
                  f"去重后按上限 {limit} 登记")
        return _assemble("parsed", reason, raw=raw, max_claims=limit,
                         parse_fn_used=parse_fn_used, parse_fn_error=parse_fn_error,
                         errors=errors, notes=notes, text=body, fenced=fenced)

    # 空集：读完这一段之后一句可断言的话都没有，或压根读不动。
    # 分界只有一条：输入里有没有可读的字母/数字。有 ⇒ 我们读过了、确实没有
    # 可断言的句子（no_claims）；没有 ⇒ 我们没拆成（unparsable）。
    status = "no_claims" if _has_readable(stripped) else "unparsable"
    reason = _missing_reason(stripped, notes, fenced)
    return _assemble(status, reason, raw=[], max_claims=limit,
                     parse_fn_used=parse_fn_used, parse_fn_error=parse_fn_error,
                     errors=errors, notes=notes, text=body, fenced=fenced)


def parse_claims(text: Any, *, max_claims: int = DEFAULT_MAX_CLAIMS,
                 parse_fn: ParseFn | None = None) -> list[dict]:
    """拆分并只返回 `{"text", "quote"}` 列表（与旧 `evidence.parse_claims` 同形）。

    为什么保留这个更小的出口：`verify_claims` 的输入就是这么多字段，
    而旧调用方（`runflow._lean_stage`、既有测试）按列表断言。
    判据只有 :func:`split_claims` 一份，这里只做投影 —— 第二份拆分实现
    会让"同一段答复有两个条数"变成可能，而两者各自都自洽。
    """
    return [{"text": c.text, "quote": c.quote}
            for c in split_claims(text, max_claims=max_claims, parse_fn=parse_fn).claims]


# ------------------------------------------------------------------ 台账合成


def _index_verdicts(rows: Sequence[Any]) -> tuple[dict[tuple[str, str], dict], list[dict]]:
    """把判决行按 `(text, quote)` 建索引；返回 `(索引, 一模一样的副本列表)`。

    用 `(text, quote)` 而不是行号作为判据：两份清单的长度可能因为截断口径
    不同而不同，按行号对齐会在那种情况下把甲条的判决配给乙条 ——
    而错配出来的台账看起来完全正常。
    """
    index: dict[tuple[str, str], dict] = {}
    copies: list[dict] = []
    for row in rows:
        if isinstance(row, Mapping):
            item = dict(row)
        else:
            item = {"text": _norm_ws(getattr(row, "text", "")),
                    "quote": _norm_ws(getattr(row, "quote", "")),
                    "verdict": str(getattr(row, "verdict", "") or ""),
                    "reason": str(getattr(row, "reason", "") or ""),
                    "level": str(getattr(row, "level", "") or ""),
                    "locator": dict(getattr(row, "locator", {}) or {}),
                    "evidence_source": str(getattr(row, "evidence_source", "") or ""),
                    "checked": bool(getattr(row, "checked", False))}
        copies.append(item)
        key = (_norm_ws(item.get("text")), _norm_ws(item.get("quote")))
        if key[0] and key not in index:
            index[key] = item
    return index, copies


def ledger_rows(split: SplitResult, verdicts: Sequence[Any] = ()) -> list[dict]:
    """把拆出来的断言与逐条判决合成台账行（`claims.json` 的 `claims` 段）。

    每一行都有 :data:`LEDGER_ROW_KEYS` 里的全部键。判决的取值只许来自
    :data:`VERDICTS`。

    "不许静默丢弃"在这里落地：拆出来的每一条都会得到一行，即使它没有引文 ——
    那种没有引文的断言取 `known_unverifiable`（已知无法逐字回验），
    而不是从台账里消失。从台账里删掉它，会让"我们没验这一条"看起来像
    "这条断言不存在"。

    判决行里找不到对应项的断言（例如调用方只回验了前 N 条）同样落
    `known_unverifiable`，理由写明"没有这一条的判决行" —— 这一档与
    "回验器说它查不成"（`unknown`）不是一件事，不许混。
    """
    index, copies = _index_verdicts(verdicts)
    rows: list[dict] = []
    for claim in split.claims:
        matched = index.get((claim.text, claim.quote))
        if matched is None:
            for leftover in copies:
                if _norm_ws(leftover.get("text")) == claim.text:
                    matched = leftover
                    break
        if matched is None:
            row = {
                "text": claim.text, "quote": claim.quote, "verdict": "known_unverifiable",
                "checked": False, "level": "", "locator": {}, "evidence_source": "",
                "reason": ("没有这一条的判决行（本次回验没有覆盖到它）"
                           "⇒ 已知无法逐字回验，不是‘查过了、没找到’"),
            }
        else:
            verdict = _norm_ws(matched.get("verdict"))
            row = {
                "text": claim.text,
                "quote": claim.quote,
                "verdict": verdict if verdict in VERDICTS else "known_unverifiable",
                "checked": bool(matched.get("checked", False)),
                "level": _norm_ws(matched.get("level")),
                "locator": dict(matched.get("locator") or {}),
                "evidence_source": _norm_ws(matched.get("evidence_source")),
                "reason": _norm_ws(matched.get("reason")),
            }
            if not verdict:
                row["reason"] = (row["reason"] + "；" if row["reason"] else "") + \
                    "判决行没有给出 verdict ⇒ 按已知无法逐字回验登记（不许当成通过）"
        if not claim.quote and row["verdict"] != "known_unverifiable":
            # 没有引文却拿到一个"查过了"的判决：那是判决行与断言对错了位，
            # 不许把它写进产物 —— 它会让一条无法回验的断言看起来验过。
            row["verdict"] = "known_unverifiable"
            row["checked"] = False
            row["level"] = ""
            row["locator"] = {}
            row["reason"] = (row["reason"] + "；" if row["reason"] else "") + \
                "这一条没有引文 ⇒ 已知无法逐字回验（判决行与断言可能对错了位）"
        row["claim_id"] = f"C{claim.index}"
        row["basis"] = claim.basis
        rows.append({k: row[k] for k in LEDGER_ROW_KEYS})
    return rows
