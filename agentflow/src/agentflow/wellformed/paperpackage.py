# -*- coding: utf-8 -*-
"""论文包：`appendix.tex` 必须是片段、论文包必须有台账托着（PAPER-PKG-FIX）。

## 两类畸形（各一条规则）

1. 「appendix.tex 是整篇独立文档」（`appendix_is_standalone` / `appendix_not_input` /
   `appendix_without_main`）：真机两份 `appendix.tex` 都是整篇 `ctexart` 文档 ——
   `p4-polish` 那份是上一版论文逐字节（7605 B），`p5-polish` 那份 708 B 自带
   `\\documentclass`；两份都没被 `main.tex` `\\input`，所以谁也没进 PDF
   （`temp/paperpkg/REPORT.md` M11）。附录的合法形态只有一种：「片段」（不含
   `\\documentclass`、被 `main.tex` `\\input`）。
2. 「有台账渲染物、却没有台账」（`paper_without_ledger`）：`p5-polish` 的 `data/*` 全是
   `{"schema_version":1,"rows":[]}`、`events.jsonl` 0 字节，而 `out/package/tables/*.tex`
   四张表（证据等级 / 否定 / 依赖 / 猜想）与 51,285 B `main.tex`、14 页 PDF 都在
   （`temp/paperpkg/REPORT.md` B2）。判据只在"论文包里有台账渲染物"时说话：`tables/`
   四张表与 `MAPPING.json` 都是从这份工作区的台账渲染出来的，台账全空时它们只能是
   空占位；而 `source/main.tex` 是只读基线也不能当台账（被审对象不是研究成果）。

## 与写口的分工

这一层是「读数面」（`wellformed` 只报不拦，业主 2026-11-21）：它回答"盘上这份包有没有
这两类畸形"。不许把它当生成后的唯一防线：空台账不许出稿已由写口
（`researchbase.writing_gate` → `fs.write` 的成文门）在落笔前拒。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import researchbase as RB
from .. import schema as S
from ..papercompile import PACKAGE_REL, PDF_NAME, TEX_NAME
from .predicates import _Unchecked
from .registry import _Ctx, _rule
from .states import Finding

APPENDIX_NAME = "appendix.tex"
MAPPING_NAME = "MAPPING.json"
TABLES_DIR = "tables"

#: 附录片段里出现它就不是片段（一份可单独编译的整篇文档）。
DOCUMENTCLASS = "\\documentclass"

#: `main.tex` 里引附录的那一行（注释里不算；`.tex` 后缀可省）。
_APPENDIX_INPUT = re.compile(r"\\input\s*\{\s*appendix(?:\.tex)?\s*\}")


def _package(ctx: _Ctx) -> Path:
    if ctx.root is None:
        raise _Unchecked("没有工作区根，读不到论文包")
    return Path(ctx.root).joinpath(*PACKAGE_REL)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _Unchecked(f"{path.name} 读不出来（{type(exc).__name__}: {exc}）") from exc


def _strip_comments(text: str) -> str:
    """去掉 LaTeX 行注释（`%` 之后）：被注释掉的 `\\input{appendix}` 不算引用。"""
    return "\n".join(line.split("%", 1)[0] for line in text.splitlines())


@_rule("paper_package", "appendix")
def _rule_appendix(ctx: _Ctx) -> list[Finding]:
    """`appendix.tex` 必须是片段，且必须被 `main.tex` `\\input`。"""
    pkg = _package(ctx)
    appendix = pkg / APPENDIX_NAME
    if not appendix.is_file():
        return []
    text = _read_text(appendix)
    out: list[Finding] = []
    where = f"{'/'.join(PACKAGE_REL)}/{APPENDIX_NAME}"
    if DOCUMENTCLASS in text:
        out.append(Finding(
            ctx.kind, where,
            f"`appendix.tex` 里有 `{DOCUMENTCLASS}` ⇒ 它是一整篇可单独编译的文档，不是附录"
            "片段。附录的合法形态是片段：写进 `main.tex`；或单独写一份片段（不含 "
            "`\\documentclass`）并由 `main.tex` 的 `\\input{appendix}` 引进去（框架自己渲染的"
            "那一份是 `\\input{mapping-appendix}`）。整篇当附录的路径已经删掉。",
            "error", "appendix_is_standalone"))
    main_tex = pkg / TEX_NAME
    if not main_tex.is_file():
        out.append(Finding(
            ctx.kind, where,
            "`appendix.tex` 在盘上而 `main.tex` 不在 ⇒ 这一份附录没有正文可挂："
            "它不会被任何 PDF 印出来（附录不是独立落点）。",
            "error", "appendix_without_main"))
        return out
    main = _strip_comments(_read_text(main_tex))
    if not _APPENDIX_INPUT.search(main):
        out.append(Finding(
            ctx.kind, where,
            "`appendix.tex` 在盘上，但 `main.tex` 里没有 `\\input{appendix}`（注释里的不算）"
            "⇒ 它没进 PDF，只是躺在包里。处置：把附录内容写进 `main.tex`，"
            "或在正文里加一行 `\\input{appendix}`。",
            "error", "appendix_not_input"))
    return out


def _row_count(root: Path, table: str) -> int:
    """一张表的行数；文件不在 ⇒ 0（"这份工作区没有那张台账"），坏文件 ⇒ `_Unchecked`。"""
    path = root / "data" / str(S.TABLES[table]["file"])
    if not path.is_file():
        return 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Unchecked(f"{path.name} 读不出来（{type(exc).__name__}: {exc}）") from exc
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise _Unchecked(f"{path.name} 的 rows 不是数组（收到 {type(rows).__name__}）")
    return len(rows)


@_rule("paper_package", "ledger")
def _rule_ledger(ctx: _Ctx) -> list[Finding]:
    """论文包里有台账渲染物、而研究台账全空 ⇒ 点名"这篇论文没有台账托着"。"""
    pkg = _package(ctx)
    paper = any((pkg / name).is_file() for name in (TEX_NAME, PDF_NAME))
    rendered = (pkg / TABLES_DIR).is_dir() or (pkg / MAPPING_NAME).is_file()
    if not (paper and rendered):
        return []
    counts: dict[str, int] = {}
    try:
        for table in RB.RESEARCH_LEDGER_TABLES:
            counts[table] = _row_count(Path(ctx.root), table)
    except _Unchecked as exc:
        raise _Unchecked("读不全研究台账 ⇒ 判不了「论文有没有台账托着」：" + str(exc)) from exc
    events = Path(ctx.root) / "data" / "events.jsonl"
    if not events.is_file():
        raise _Unchecked("读不到 data/events.jsonl ⇒ 判不了这一份论文是不是在空台账上写的")
    try:
        events_bytes = events.stat().st_size
    except OSError as exc:
        raise _Unchecked(f"data/events.jsonl 读不出来（{type(exc).__name__}: {exc}）") from exc
    empty = sorted(t for t, n in counts.items() if not n)
    if len(empty) != len(counts) or events_bytes:
        return []
    return [Finding(
        ctx.kind, "/".join(PACKAGE_REL),
        f"论文包里有台账渲染物（`{TABLES_DIR}/` 或 `{MAPPING_NAME}`），而这份工作区的"
        f"研究台账全空：data/ 下这 {len(counts)} 张表都是 0 行"
        f"（{'、'.join(empty)}）、`events.jsonl` {events_bytes} 字节 —— 论文没有一行台账"
        "托着。处置：先把台账/证据落下来（A 检索入库 / B 收命题 / D 出手稿 / E 跑实验），"
        "再重生成论文包；只读基线 `source/main.tex` 不是台账，不能拿来顶。",
        "error", "paper_without_ledger")]
