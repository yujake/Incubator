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
