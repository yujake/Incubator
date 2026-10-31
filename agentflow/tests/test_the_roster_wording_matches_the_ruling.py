# -*- coding: utf-8 -*-
"""判据：名册那一套说法必须与改造后的口径逐字对齐（措辞也会腐烂）。

## 为什么单为"说法"立一条判据

`4e2963b4` 把 `_register_roster` 的"撞名 ⇒ 静默换名"整块删掉了，但解释这件事的
句子散在三处（活代码注释、判据文件头、`roster_repair` 的 docstring），它们不会跟
着代码一起变。改前实测的三句：

- `secretary.py` 的 `retire` 收工兜底写着「治本在登记侧（`Conductor._register_roster`：
  撞名字时改发新号，不许因此丢一行）」—— 改造后撞名是 `name_taken` 拒绝，不发新号；
- `test_retiring_repairs_the_roster_first.py` 的文件头写同一句；
- `roster_repair` 的 docstring 把"两个并发修复不会重复分配"归因给 `next_name`
  —— 真因是 `_roster_section` 的 per-owner 临界区（`b10cee3a`）。

这三句都读得出"代码还允许换名"，而代码已经不允许了；下一个照着注释改代码的人会
把 `4e2963b4` 的裁定改回去。

## 这一组守什么

1. 全仓（`src/` + `tests/` + `docs/`，不含 `draft/` `temp/` `projects/`）不再出现
   "撞名字改发新号" 这一说法（含"撞名字时改发新号"）；
2. `roster_repair` 的 docstring 必须点名真正的并发机制 `_roster_section`；
3. 反真空：`secretary.py` 里 `retire` 的收工兜底那一段必须还在（判据的扫描面没跑偏），
   且它必须说到 `name_taken`（不是"改发新号"）。
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "agentflow"

#: 改造后不许再出现的说法（逐字）。`draft/` 与 `temp/` 是审计与探针的落点，
#: 它们要引用旧说法才能说明改了什么，所以排除；`projects/` 是业主的工作区，不碰。
STALE_PHRASES: tuple[str, ...] = (
    "撞名字改发新号",
    "撞名字时改发新号",
)

#: 判据自己必须逐字点名这两句（否则它说不清在禁什么），所以它把自己排除在扫描面之外：
#: 除它以外一个文件都不例外 —— 包括本判据文件头引用的那三处。
_SELF = pathlib.Path(__file__).resolve()

#: 「顺延」这个词面拆成两句之后（业主 2026-11-02 批准动禁改区统一词面）：
#: - 留：事实「新派活时按序号发下一个未用名」（`next_name` 按已用最大序号 +1，
#:   今天仍然如此）—— 改用 `FACT_PHRASE`；
#: - 删：已废的「撞名 ⇒ 改用顺延名继续登记」（`4e2963b4` 已删）—— 它的历史留痕仍在
#:   `conductor.py` 的注释与 `test_a_taken_name_is_refused.py` 里，那几处继续写「顺延」。
#: 为什么禁的是这一整句而不是「顺延」两个字：历史留痕要用这个词才说得清"删掉的是哪条
#: 行为"；而事实句若与它共用词面，读者（和模型）会把两件事读成一件事。
DEPRECATED_FACT_PHRASE = "让秘书顺延发号"
FACT_PHRASE = "按序号发下一个未用名"

#: 事实句一旦被替换，这三处（模型看得见的声明 + 拒信）必须都换上新的说法。
FACT_PHRASE_OWNERS: tuple[str, ...] = (
    "src/agentflow/specs/d.py",
    "src/agentflow/specs/m.py",
    "src/agentflow/secretary.py",
)


def _texts() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for base, patterns in ((ROOT / "src", ("*.py",)),
                           (ROOT / "tests", ("*.py",)),
                           (ROOT / "docs", ("*.md",))):
        for pattern in patterns:
            out.extend(sorted(base.rglob(pattern)))
    return [p for p in out if p.resolve() != _SELF]


def test_the_stale_claim_about_renaming_a_taken_name_is_gone() -> None:
    """正题：全仓不再有"撞名字改发新号"这种说法（它描述的行为已经被删掉）。"""
    hits: list[str] = []
    for path in _texts():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # 读不出来不是"没有这句话"
            hits.append(f"{path.relative_to(ROOT)}: <读不出来>")
            continue
        for phrase in STALE_PHRASES:
            if phrase in text:
                line = text[:text.index(phrase)].count("\n") + 1
                hits.append(f"{path.relative_to(ROOT)}:{line}: {phrase}")
    assert not hits, (
        "这些地方还在说'撞名字改发新号'，而改造后的口径是 name_taken 受控拒绝"
        "（业主 2026-11-02，`4e2963b4`）：\n  - " + "\n  - ".join(hits))


def test_the_repair_docstring_names_the_real_concurrency_mechanism() -> None:
    """正题：`roster_repair` 的 docstring 必须点名 `_roster_section`（真正的并发机制）。"""
    import inspect

    from agentflow.secretary import Secretary

    doc = inspect.getdoc(Secretary.roster_repair) or ""
    assert "_roster_section" in doc, (
        "`roster_repair` 的 docstring 没有点名 per-owner 临界区 `_roster_section`："
        "今天'两个并发修复不会重复分配'靠的是它（`b10cee3a`），不是 `next_name` 的序号推导")
    assert "两个并发修复不会重复分配（名字在 `next_name` 里按已用最大序号推）" not in doc, (
        "旧归因还在：把一个锁的性质写成发号器的性质，会让下一个人以为删掉锁也没事")


def test_the_retire_backstop_comment_still_exists_and_names_the_ruling() -> None:
    """反真空：扫描面没跑偏 —— `retire` 的收工兜底那一段仍在，且说到 `name_taken`。"""
    src = (PKG / "secretary.py").read_text(encoding="utf-8")
    assert "收工兜底" in src, "扫描面跑偏了：`secretary.py` 里找不到'收工兜底'"
    window = src[max(0, src.index("收工兜底") - 200): src.index("收工兜底") + 1200]
    assert "name_taken" in window, (
        "收工兜底那一段没有再提 `name_taken`：它必须说清'派活那一刻撞名是拒绝、"
        "收口这一刻才补名字'这两件事（`draft/151` 三-6）")
    assert not re.search(r"撞名字.{0,6}改发新号", window), (
        "收工兜底那一段又写回'撞名字改发新号'了", window[:200])


def test_the_still_true_sentence_no_longer_borrows_the_retired_word() -> None:
    """正题：事实句不再写成「让秘书顺延发号」（它曾与已废的换名共用词面）。"""
    hits: list[str] = []
    for path in _texts():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # 读不出来不是"没有这句话"
            hits.append(f"{path.relative_to(ROOT)}: <读不出来>")
            continue
        if DEPRECATED_FACT_PHRASE in text:
            line = text[:text.index(DEPRECATED_FACT_PHRASE)].count("\n") + 1
            hits.append(f"{path.relative_to(ROOT)}:{line}: {DEPRECATED_FACT_PHRASE}")
    assert not hits, (
        "这些地方还把'不点名 ⇒ 按序号发一个新名'写成'让秘书顺延发号' —— 它和已废的"
        "「撞名 ⇒ 改用顺延名继续登记」共用词面（业主 2026-11-02 批准动禁改区统一词面）：\n  - "
        + "\n  - ".join(hits))


def test_the_new_wording_landed_and_the_history_keeps_its_word() -> None:
    """反真空：新事实句真的落到三处；历史留痕不许被一起洗掉（业主：别把「顺延」整个删掉）。"""
    for rel in FACT_PHRASE_OWNERS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert FACT_PHRASE in text, (
            f"{rel} 里没有「{FACT_PHRASE}」：事实句被删掉了，而不是换了词面"
            "（业主 2026-11-02 的口径：事实保留、只统一词面）")
    # 已删行为的历史留痕：`_register_roster` 的注释仍逐字说明"改前改发顺延的新名字"。
    conductor = (PKG / "conductor.py").read_text(encoding="utf-8")
    assert "顺延" in conductor, (
        "`conductor.py` 里已删换名行为的留痕被洗掉了：历史记录要继续用「顺延」这个词"
        "才说得清删的是哪一条")
    old_case = (ROOT / "tests" / "test_a_taken_name_is_refused.py").read_text(encoding="utf-8")
    assert "顺延" in old_case, (
        "`test_a_taken_name_is_refused.py` 里'改前改发顺延名'的读数被洗掉了 —— "
        "那一条证明的正是'静默换名已经删掉'")
