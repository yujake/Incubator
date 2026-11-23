# -*- coding: utf-8 -*-
"""`texaudit` 的读盘与展开层：`_read_text` / `_rel` / `_Corpus` 的真身。

## 这一层管什么

`texaudit` 的七类扫描里，六类（cites / refs / duplicates / proofs / inputs /
ledger_match）吃的是同一份"展开后的正文"：`main.tex` 加上它递归 `\\input` 进来的文件，
按文档顺序切成片段、每段带文件与起始行号。把这份正文装起来的对象就是 `_Corpus`，
它同时负责两件事的唯一实现：

1. 读盘 —— 读不成（不是 UTF-8 / 含 NUL 字节 / 路径读不出来）如实记进 `problems`，
   绝不拿空串冒充空文件（"读不成"与"是空的"必须分得开）；
2. 定名 —— 读数里的 `file` 一律是工作区相对路径（`out/package/main.tex`），
   由 `pkg_prefix()` / `qualify()` 从"相对包根"补成"相对工作区根"。

所以它与"哪一类该怎么判"是两件事：那一半留在 `texaudit`，这一半在这里。
依赖方向只有一条（`texaudit → texcorpus`），本模块不 import `texaudit`。

## 为什么搬出来（2026-11-22）

这一批把 `texaudit.py` 顶在 800 行软基线上：正文缺省落点改认
`PC.package_dir`（退役目录那一支在真机工作区里恒为空，审计会空跑）之后，
文件连一行的余量都没有了。业主口径是"不许抬体量软基线"，于是处置是搬、不是改：

- `_read_text` / `_rel` / `_Corpus` 三件逐字搬到这里；
- `texaudit.py` 在原位 `from .texcorpus import _Corpus, _read_text, _rel` 按名字回引；
- 三个名字本来都以下划线打头 ⇒ `dir()` 的公开名集合一个没少、一个没多；
- 行为等价由搬前/搬后两次 `dir()` 快照 + 关键读数 sha256 相同钉住
  （探针见 `temp/basefix2/`：`_equiv_live.py` 先把拆前那一版逐字节反推出来，
  再在同一进程里与拆后对拍）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from . import papermapping as PM


# ---------------------------------------------------------------- 读盘


def _read_text(path: Path) -> tuple[str | None, str]:
    """读一份 UTF-8 文本；读不成返回 `(None, 理由)`（绝不返回空串冒充空文件）。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"{path.name} 读不出来（{type(exc).__name__}: {exc}）"
    if b"\x00" in raw:
        return None, f"{path.name} 是二进制文件（含 NUL 字节）⇒ 它没有可数的正文"
    try:
        return raw.decode("utf-8"), ""
    except UnicodeDecodeError as exc:
        return None, f"{path.name} 不是 UTF-8 文本（{exc}）⇒ 它没有可数的正文"


def _rel(path: Path, root: Path | None) -> str:
    """读数里的 `file` 一律是工作区相对路径（posix 分隔符，与 `fs.*` 同一条）。"""
    if root is None:
        return path.name
    try:
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return path.name


class _Corpus:
    """这一次要扫的正文：`main.tex` + 它递归 `\\input` 进来的文件（按文档顺序切片段）。

    为什么要有这样一个对象：五类里有四类（cites/refs/proofs/duplicates）都要"按文档顺序、
    带文件与行号"地看同一份展开后的正文。每类自己展开一遍 = 同一件事四处口径。
    """

    def __init__(self, root: Path | None, files: Sequence[Path]):
        self.root = root
        self.files = list(files)
        self.segments: list[tuple[str, str, int]] = []   # (相对名, 片段, 起始行偏移)
        self.problems: list[dict] = []
        self.main: Path | None = None
        self.package: Path | None = None
        self.main_text = ""
        #: 两条派生读数各只算一次（proofs 与 ledger_match 共用同一份正文）。
        self._statement_names: tuple[str, ...] | None = None
        self._events: list[dict] | None = None

    def pkg_prefix(self) -> str:
        """论文包相对工作区根的前缀（`out/package/`）—— 读数里的 `file` 要带它。

        `papermapping._collect_tex_segments` 给的是"相对包根"的名字（`main.tex`、
        `mapping-appendix.tex`），而 H 拿到读数之后要按那个路径去改稿 —— 所以这一层
        把它补成工作区相对（`out/package/main.tex`）。补错的表现很隐蔽：H 会去改一个
        同名但不在包里的文件，或者干脆找不到。
        """
        if self.package is None or self.root is None:
            return ""
        prefix = _rel(self.package, self.root)
        return "" if prefix in ("", ".") else prefix.rstrip("/") + "/"

    def qualify(self, rel: str) -> str:
        """包内相对名 → 工作区相对名。"""
        prefix = self.pkg_prefix()
        if not prefix or not rel or rel.startswith(prefix):
            return rel
        return prefix + rel

    def load(self) -> None:
        """把文件展开成片段；读不成 / `\\input` 指不到都记进 `problems`（不静默丢）。"""
        self.main = next((p for p in self.files if p.name == PM.PC.TEX_NAME), None)
        if self.main is not None:
            body, why = _read_text(self.main)
            if body is None:
                self.problems.append({"file": _rel(self.main, self.root), "why": why})
                return
            self.main_text = body
            self.package = self.main.parent
            segments, _read_files, probs = PM._collect_tex_segments(  # noqa: SLF001 —— 生产实现
                self.package, self.main, body)
            self.segments = [(self.qualify(rel), seg, off) for rel, seg, off in segments]
            for prob in probs:
                self.problems.append({
                    "file": str(prob.get("where") or ""),
                    "why": str(prob.get("detail") or ""),
                })
            return
        # 没有 `main.tex`：逐份扫（不跟 `\input` —— 没有包根，跟了就是猜路径）
        for path in self.files:
            body, why = _read_text(path)
            if body is None:
                self.problems.append({"file": _rel(path, self.root), "why": why})
                continue
            self.segments.append((_rel(path, self.root), PM.strip_tex_comments(body), 0))

    @property
    def statement_names(self) -> tuple[str, ...]:
        """定理类环境名（含印成 Theorem/Lemma/… 的自定义宏）。"""
        if self._statement_names is None:
            text = self.main_text or "\n".join(seg for _r, seg, _o in self.segments)
            self._statement_names = PM.statement_env_names(text)
        return self._statement_names

    def hits(self, pattern: re.Pattern[str]) -> list[tuple[str, int, str, str]]:
        """逐片段跑一条正则：`(文件, 行号, 命中原文, 最后一组)`。"""
        out: list[tuple[str, int, str, str]] = []
        last = pattern.groups
        for rel, seg, offset in self.segments:
            line = offset + 1
            cursor = 0
            for m in pattern.finditer(seg):
                line += seg.count("\n", cursor, m.start())
                cursor = m.start()
                out.append((rel, line, m.group(0).strip(), m.group(last) if last else ""))
        return out
