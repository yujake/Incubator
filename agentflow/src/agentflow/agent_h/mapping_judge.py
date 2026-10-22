# -*- coding: utf-8 -*-
"""H 的语义审校里"论文对应表"那一档（业主 2026-10-22）。

## 这一档判什么、凭什么拦

业主原话：「G 产出论文时需附上对应表……H 依据此核查」。表与正文的自洽性是客观的
（有没有这一行、指的文件在不在、证明号能不能解析），所以这一类归客观档：判出来
就拦门。另一半（逻辑颠倒、缺铺垫、术语没定义……）是读稿人的判断，维持只点名不拦。

四类客观 kind 的真身在 `papermapping.MAPPING_KINDS`（这里只导入，不抄第二份）；
`citation_loc` 那两格与"人读的那一份"分别由 `papermapping.CITATION_KINDS` /
`papermapping.MD_KINDS` 给 —— 它们同样是可判事实，所以也在拦门那一档。
Lean 那两格的四条（`mapping_lean_*`，业主 2026-10-22 追加）同样如此：
"验它的是哪一份源码、哪个声明名"可判，所以拦门；而"开关开着却没有 Lean 产物"
（`lean_on_but_no_artifact`）说的是另一件事（形式化一个文件都没落），落在 warning 档。

## 为什么 H 写不进 review_findings

`schema.FINDING_KINDS` 是禁改区（FC-27）里的受控词表，这几个 `mapping_*` 不在里面，
而 `tools/review_tools.record_finding` 按那张词表硬校验 —— 所以这一类暂时只能落
收工读数（`closing` 的 `mapping` 格），落不进 `review_findings`。
这是一条待批的边界，不是"忘了接"：要么批"给 FINDING_KINDS 加这些取值"，
要么长期接受"只在收工读数里可见"。本模块与 `papermapping` 都不许拿别的 kind 冒充。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .. import papermapping as PM

#: 客观档：表与正文对不对得上、指的文件在不在、证明号与引文位置能不能解析。
#: 真身是 `papermapping.MAPPING_KINDS`（业主点名的四类），这里是同一个对象的别名。
MAPPING_OBJECTIVE_KINDS: tuple[str, ...] = PM.MAPPING_KINDS

#: 客观档的第二组：`citation_loc` 两格（业主 2026-10-22 追加）。
CITATION_OBJECTIVE_KINDS: tuple[str, ...] = PM.CITATION_KINDS

#: 客观档的第三组：人读的那一份（少了它，交付物里只剩机器读的一份）。
MD_OBJECTIVE_KINDS: tuple[str, ...] = PM.MD_KINDS

#: 客观档的第四组：论文侧三条（包里有没有表 / 正文有没有印出来 / 印出来的与 json 一致）。
PAPER_OBJECTIVE_KINDS: tuple[str, ...] = PM.PAPER_KINDS

#: 客观档的第五组：Lean 那两格的四条（业主 2026-10-22 追加）。
#:
#: 「Lean 程序在哪一份源码里、验的是哪个声明名」是可判事实（文件在不在包里、
#: 名字在不在那份源码里、同一个名字有没有被两行共用），所以照 `level_of` 的既有写法
#: 归到拦门那一档 —— 判据的真身是 `papermapping.LEAN_KINDS`，这里只是别名。
LEAN_OBJECTIVE_KINDS: tuple[str, ...] = PM.LEAN_KINDS

#: 只进读数、不拦门的那一档：Lean 开关开着而盘上一个 Lean 产物都没有。
#:
#: 它说的不是"表与正文对不上"，而是"这一趟的形式化一个文件都没落"——
#: 那一件事由收工门的 `load_bearing` 与形式化门在管。这里让它在读数里可见
#: （`warnings_of` 会把它读出来，`level_of` 给 warning），不把每一份不使用形式化的
#: 论文都堵在对应表这一格上。
LEAN_WARN_KINDS: tuple[str, ...] = PM.LEAN_WARN_KINDS

#: 全部客观 kind（判出来就拦门）。
BLOCKING_KINDS: tuple[str, ...] = (
    MAPPING_OBJECTIVE_KINDS + CITATION_OBJECTIVE_KINDS + MD_OBJECTIVE_KINDS
    + PAPER_OBJECTIVE_KINDS + LEAN_OBJECTIVE_KINDS
)

#: 主观档：读稿人的判断。只点名、不拦门（业主口径："主观类维持只点名不拦"）。
#:
#: 取值就是 H 那遍"研究生读法"点名的那几种困惑（逻辑颠倒 / 缺铺垫 / 术语没定义 /
#: 承诺未回应 / 交叉引用错）—— 它们是品味与可读性，不是可复算的事实。
SUBJECTIVE_KINDS: tuple[str, ...] = (
    "logic_inverted", "missing_groundwork", "undefined_term",
    "unanswered_promise", "wrong_crossref",
)

#: 拦门那一档的级别名（`closing.Finding.level` 的取值）。
LEVEL_BLOCKER = "blocker"

#: 只点名那一档的级别名。
LEVEL_INFO = "info"

#: 看得见、但不动门的那一档（`closing.Finding.level` 也认它）。
#:
#: 与 `LEVEL_INFO` 的区别是读者：`info` 说的是"读稿人的判断"（主观档），
#: `warning` 说的是一条客观读数今天不该拦门（`LEAN_WARN_KINDS`）——
#: 两件事分得开，才不会把"这一档还留着没拦"读成"主观意见"。
LEVEL_WARNING = "warning"


def is_objective(kind: Any) -> bool:
    """这个 kind 属于客观档吗（判出来就拦门）。"""
    return str(kind or "") in BLOCKING_KINDS


def is_subjective(kind: Any) -> bool:
    """这个 kind 属于主观档吗（只点名、不拦门）。"""
    return str(kind or "") in SUBJECTIVE_KINDS


def is_warning(kind: Any) -> bool:
    """这个 kind 属于"客观读数、但今天不拦门"那一档吗（`LEAN_WARN_KINDS`）。"""
    return str(kind or "") in LEAN_WARN_KINDS


def level_of(kind: Any) -> str:
    """一个 kind 该落成哪一档级别：客观 ⇒ blocker，警告档 ⇒ warning，主观 ⇒ info。

    词表外的 kind 也落 blocker：它意味着"产出方与词表漂了"，把它降成 info 会让
    一整类问题静默消失（那种错没有任何东西会报）。宁可错拦，不可静默。
    """
    if is_subjective(kind):
        return LEVEL_INFO
    if is_warning(kind):
        return LEVEL_WARNING
    return LEVEL_BLOCKER


def findings_of(reading: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """把一次 `papermapping.mapping_reading` 的读数折成 H 形状的发现。

    只折 `problems`（拦门那一档）。`warnings` 走 `warnings_of`：它们不改 `state`、
    不动门的强度，所以不进这份清单 —— 但要照样读得出来（"没拦住"与"没看见"是两件事）。

    零条问题 ⇒ 返回空表（不是 None）：空表是"查过了、没问题"，None 会被读成
    "没查"。两者在收工输出上必须分得开，所以这个函数的返回值里没有"缺席"这一档。
    """
    out: list[dict[str, Any]] = []
    for item in ((reading or {}).get("problems") or ()):
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "")
        out.append({
            "kind": kind,
            "level": level_of(kind),
            "target": str(item.get("label") or item.get("where") or ""),
            "where": str(item.get("where") or ""),
            "message": str(item.get("detail") or ""),
        })
    return out


def warnings_of(reading: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """把读数里的 `warnings` 折成同样形状的发现（级别按 `level_of`，今天它是 warning）。

    为什么不并进 `findings_of`：那一份是拦门清单，`closing` 会把它逐条写成
    `Finding`；而 `lean_on_but_no_artifact` 这一档按口径不拦门（理由见 `LEAN_WARN_KINDS`）。
    并进去就等于让它拦门，而不并又会让它消失 —— 所以另开一个返回口，
    由 `closing` 数一遍并列进读数（"看见了、这一档不拦"）。
    """
    out: list[dict[str, Any]] = []
    for item in ((reading or {}).get("warnings") or ()):
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "")
        out.append({
            "kind": kind,
            "level": level_of(kind),
            "target": str(item.get("label") or item.get("where") or ""),
            "where": str(item.get("where") or ""),
            "message": str(item.get("detail") or ""),
        })
    return out


def problem_counts(findings: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """按 kind 数一遍（收工读数里那一行"逐条列"用的就是它）。"""
    counts: dict[str, int] = {}
    for item in findings or ():
        kind = str(item.get("kind") or "")
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


__all__ = [
    "BLOCKING_KINDS", "CITATION_OBJECTIVE_KINDS", "LEAN_OBJECTIVE_KINDS",
    "LEAN_WARN_KINDS", "LEVEL_BLOCKER", "LEVEL_INFO", "LEVEL_WARNING",
    "MAPPING_OBJECTIVE_KINDS", "MD_OBJECTIVE_KINDS", "PAPER_OBJECTIVE_KINDS",
    "SUBJECTIVE_KINDS", "findings_of", "is_objective", "is_subjective", "is_warning",
    "level_of", "problem_counts", "warnings_of",
]
