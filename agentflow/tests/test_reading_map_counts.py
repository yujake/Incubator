# -*- coding: utf-8 -*-
"""判据：`docs/READING-MAP.md` 开头那三个读数必须等于盘上现算（2026-11-03，153-U-15）。

## 背景

`docs/READING-MAP.md` 是"要改的东西在哪"的那张图，开头一句写规模：

    **255 个 `.py`、209,413 行**，**69 个文件超过 800 行**
    （**全仓最大的是 `agent_loop.py`，12,063 行**）

它自己还给了复跑命令（`:10`），但**唯一会抓这三个数的是一个不在 `tests/` 里的探针**
（`temp/_probe_doc_vs_code.py` 的 ③，CI 不跑）⇒ 它漂了 8 天没人知道：
现算是 257 个 `.py` / 223,941 行 / 70 个超过 800 行 / `agent_loop.py` 12,760 行。

## 这条判据钉住什么

1. 那一句里的三格 == 现算（同一口径：`src/` 下全部 `*.py`，逐文件
   `read_text().splitlines()` 求和，`__pycache__` 不在里面）；
2. `agent_loop.py` 那个行数 == 盘上那个文件的行数；
3. 反真空：现算出来的三格必须非空（文件数 > 200、行数 > 100000、大文件数 > 50）——
   `src/` 都没扫到时，"零命中"不许被读成"没有过期读数"。

口径只核"当次读数"那一句（开头那一段），**不核带日期的历史读数**：那一段的格式就是
"某个日期 → 某个数"，全核会把历史当现状（`tests/test_tools_returns_declaration.py`
同族判据用的也是"带日期 = 历史读数"这条口径）。
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
READING_MAP = ROOT / "docs" / "READING-MAP.md"

#: 开头那一段（"当次读数"）。历史读数的补充行在这一段之后，不参与解析。
_HEAD_LINES = 12

#: `**N 个 `.py`、M 行**` —— 文件数与总行数同一句（改了排版要跟着改这条，不是放宽它）。
_BOLD_TRIPLE = re.compile(r"\*\*(?P<files>\d+)\s*个\s*`\.py`、\s*(?P<lines>[\d,]+)\s*行\*\*")
#: `N 个文件超过 800 行`
_BIG_FILES = re.compile(r"(?P<big>\d+)\s*个文件超过\s*800\s*行")
#: `全仓最大的是 `agent_loop.py`，M 行`
_LARGEST = re.compile(r"`agent_loop\.py`，\s*(?P<lines>[\d,]+)\s*行")


def _live() -> tuple[int, int, int, int]:
    """(文件数, 总行数, 超过 800 行的文件数, agent_loop.py 行数) —— 现算。"""
    sizes = [(p, len(p.read_text(encoding="utf-8").splitlines()))
             for p in sorted(SRC.rglob("*.py"))]
    assert sizes, f"{SRC} 下一个 `*.py` 都没读到 ⇒ 判据在扫空集"
    loop = [n for p, n in sizes if p.name == "agent_loop.py"]
    assert loop, "`src/` 下没有 `agent_loop.py` ⇒ 这条判据的对象没了"
    return (len(sizes), sum(n for _p, n in sizes),
            sum(1 for _p, n in sizes if n > 800), loop[0])


def _head() -> str:
    lines = READING_MAP.read_text(encoding="utf-8").splitlines()[:_HEAD_LINES]
    return "\n".join(lines)


def test_the_headline_counts_equal_the_disk() -> None:
    """① 开头那三格 == 现算（今天红：255/209,413/69 vs 257/223,941/70）。"""
    files, total, big, loop = _live()
    assert files > 200 and total > 100_000 and big > 50, (
        f"现算读数看起来不对（{files} 个文件 / {total} 行 / {big} 个大文件）⇒ 先查扫描口径，"
        "别把这条判据的失败读成'文档过期'")
    head = _head()
    triple = _BOLD_TRIPLE.search(head)
    assert triple, (
        "`docs/READING-MAP.md` 开头那段里找不到 `**N 个 `.py`、M 行**` 那一句 ⇒ "
        "要么它被改写了（要跟着改这条判据的解析），要么这份文档换了形态")
    got_files = int(triple.group("files"))
    got_lines = int(triple.group("lines").replace(",", ""))
    found_big = _BIG_FILES.search(head)
    assert found_big, "开头那段里找不到 `N 个文件超过 800 行`"
    got_big = int(found_big.group("big"))
    problems = []
    if got_files != files:
        problems.append(f"文件数：文档 {got_files} vs 现算 {files}")
    if got_lines != total:
        problems.append(f"行数：文档 {got_lines:,} vs 现算 {total:,}")
    if got_big != big:
        problems.append(f"超过 800 行的文件数：文档 {got_big} vs 现算 {big}")
    assert not problems, (
        "`docs/READING-MAP.md` 开头那三格过期了（口径见该文档 `:10` 的复跑命令）：\n  - "
        + "\n  - ".join(problems))


def test_the_largest_file_reading_equals_the_disk() -> None:
    """② `agent_loop.py` 的行数 == 盘上那个文件的行数（正文里出现两次，这里核开头那句）。"""
    loop = _live()  # 取 4 格，最后一个就是 agent_loop.py
    assert loop[3] > 1000, f"`agent_loop.py` 只有 {loop[3]} 行 ⇒ 读到别的文件了"
    found = _LARGEST.search(_head())
    assert found, "开头那段里找不到 `` `agent_loop.py`，M 行 ``"
    got = int(found.group("lines").replace(",", ""))
    assert got == loop[3], (
        f"`agent_loop.py` 的行数：文档 {got:,} vs 现算 {loop[3]:,}")
