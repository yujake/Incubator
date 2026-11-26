# -*- coding: utf-8 -*-
"""`texaudit` 的读盘与展开层：`_read_text` / `_rel` / `_Corpus` / `structure_of` 的真身。

## 这一层管什么

`texaudit` 的七类扫描里，六类（cites / refs / duplicates / proofs / inputs /
ledger_match）吃的是同一份"展开后的正文"：`main.tex` 加上它递归 `\\input` 进来的文件，
按文档顺序切成片段、每段带文件与起始行号。把这份正文装起来的对象就是 `_Corpus`，
它同时负责三件事的唯一实现：

1. 读盘 —— 读不成（不是 UTF-8 / 含 NUL 字节 / 路径读不出来）如实记进 `problems`，
   绝不拿空串冒充空文件（"读不成"与"是空的"必须分得开）；
2. 定名 —— 读数里的 `file` 一律是工作区相对路径（`out/package/main.tex`），
   由 `pkg_prefix()` / `qualify()` 从"相对包根"补成"相对工作区根"；
3. 结构事实 —— `structure_of()` 把"每个 `\\label` 落在哪个环境/小节里、每个环境有没有
   label"数出来（2026-11-26 GTOOL-HARD：`refs` / `duplicates` 两类要它，而"该怎么判"
   仍留在 `texaudit`）。它只回答"盘上是什么"，不下判断：前缀该配哪一类环境是
   `texaudit.LABEL_PREFIX_KINDS` 的事。

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

#: 正文里"有编号、能被 `\\ref` / 对应表/附录点名"的环境名（结构事实的词表，不是判定）。
#:
#: 它比 `papermapping.ENV_KINDS`（对应表登记的六类）宽：`remark` / `definition` /
#: `conjecture` / `openproblem` 不进对应表，但它们同样印出编号、同样被 `\\ref` 指来指去，
#: 所以"一个 `prop:` 前缀该落在哪一类环境里"这件事必须看得见它们 —— 判它红不红仍由
#: `texaudit` 决定，这里只把名字认出来。印成 Lemma 的自定义宏由
#: `papermapping._printed_env_title` 折算（与"一条命题对一个环境"同一把尺）。
CONTAINER_KINDS: tuple[str, ...] = (
    "theorem", "lemma", "proposition", "corollary", "definition",
    "example", "remark", "conjecture", "openproblem",
)

#: 导言区 `\\newtheorem{名字}[共享计数器]{印出来的标题}`（标题那一段要能读出来）。
_NEWTHEOREM_TITLE_RE = re.compile(
    r"\\newtheorem\*?\s*\{(?P<name>[^{}]+)\}\s*(?:\[[^{}]*\]\s*)?\{(?P<title>[^{}]*)\}")

#: 结构事实要认的四个 token：环境的开闭、`\\label`、`\\appendix`、`\\section`。
_STRUCT_TOKEN_RE = re.compile(
    r"\\(?P<which>begin|end)\s*\{(?P<env>[^{}]+)\}"
    r"|\\label\s*\{(?P<label>[^{}]*)\}"
    r"|(?P<appendix>\\appendix)\b"
    r"|(?P<section>\\section\*?)\s*\{")

#: `\label` 前缀 → 它自称的那一类容器（`CONTAINER_KINDS` 的一员 + `section` / `appendix`）。
#:
#: 2026-11-26（GTOOL-HARD）：真论文里有 `\label{prop:planar}` 写在 `\begin{remark}` 里，
#: 11 处 `Remark~\ref{prop:planar}` 全指着它 —— 编号没错（`\ref` 给的是计数器值），但
#: "这条 label 自称是哪一类"没有任何地方核过。前缀就是一句可机械核的类型声明。
#: 只有登记过的前缀才判；没登记的（`eq:` / `fig:`）与不带前缀的只进 facts（三态）。
LABEL_PREFIX_KINDS: dict[str, tuple[str, ...]] = {
    "thm": ("theorem",), "lem": ("lemma",), "prop": ("proposition",),
    "cor": ("corollary",), "def": ("definition",), "ex": ("example",),
    "rem": ("remark",), "conj": ("conjecture",), "op": ("openproblem",),
    # 附录小节印的是 "A"，但它仍然是一条 section：两种前缀都收。
    "sec": ("section", "appendix"), "app": ("appendix",),
}

#: `Theorem~\ref{…}` 里那个词 → 它要求被引对象是哪一类（复数同义）。
#:
#: 与上面同一族、另一半：`\ref` 只印编号，所以 `Theorem~\ref{lem:x}` 会印成
#: "Theorem 3.2" 而对象是 Lemma 3.2 —— 读者看到的名词与对象的类型对不上。
REF_NOUN_KINDS: dict[str, tuple[str, ...]] = {
    "theorem": ("theorem",), "lemma": ("lemma",), "proposition": ("proposition",),
    "corollary": ("corollary",), "definition": ("definition",), "example": ("example",),
    "remark": ("remark",), "conjecture": ("conjecture",), "open problem": ("openproblem",),
    "section": ("section", "appendix"), "appendix": ("appendix",),
}
_REF_NOUN_RE = re.compile(
    r"(?P<noun>(?:Open\s+)?(?:Theorem|Lemma|Proposition|Corollary|Definition|Example|"
    r"Remark|Conjecture|Section|Appendix)s?)\s*~?\s*\\ref\s*\{(?P<key>[^{}]*)\}")

#: 固定声明段（审阅状态那一类）的词表：只有含这些词的 `\emph` 块 / 段落才参与"逐字重复"判。
#:
#: 声明本身该写几次是文风（软的那一半归提示词路）；同一段声明逐字复制是结构问题 ——
#: 它让同一句话在不同 scope 里各说一遍，读者读到第 5 遍时那句话已不再是"声明"而是样板。
DECLARATION_MARKERS: tuple[str, ...] = (
    "reviewed line by line", "checked by machine", "machine checking",
    "independent line-by-line review", "independent review",
    "corroboration only", "verified by machine",
)
_EMPH_BLOCK_RE = re.compile(r"\\emph\{([^{}]*)\}")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


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
        #: 结构事实（`structure()` 的缓存；refs / duplicates 两类共用）。
        self._structure: dict | None = None

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

    def structure(self) -> dict:
        """结构事实（只算一次；`structure_of` 的缓存口）。"""
        if self._structure is None:
            self._structure = structure_of(self.segments, self.main_text)
        return self._structure


def structure_of(segments: Sequence[tuple[str, str, int]], main_text: str = "") -> dict:
    """正文的结构事实：每个 `\\label` 落在哪个容器里、每个容器有没有 `\\label`。

    返回五格（都是事实，一条判断都没有）：

    | 键 | 意思 |
    |---|---|
    | `labels` | `{label 键: {file, line, kind}}`；`kind` 是它所在的容器（环境名折算成 `CONTAINER_KINDS` 里的一员；label 在小节里 ⇒ `section` / `appendix`；认不出 ⇒ 空串） |
    | `envs` | `[{name, file, line, labelled}]`（按开环境的位置，`line` 指向 `\\begin` 那一行） |
    | `ref_nouns` | `[(file, line, noun, key)]`：`Theorem~\\ref{thm:x}` 那类"名词 + 编号"的引用（名词原文），`formula~\\ref` 一类不收 |
    | `declarations` | `[(file, line, text)]`：含 `DECLARATION_MARKERS` 的固定声明块（`\\emph` 块优先；含 `\\emph` 块的段落不重复计） |
    | `unprefixed` | 不带 `:` 的 label 条数（"没有前缀"是事实，不据此判红） |

    为什么要这一层：`\\label{prop:planar}` 写在 `\\begin{remark}` 里，只有把"这条 label
    落在哪个环境"数出来才判得了（`LABEL_PREFIX_KINDS` 是词表、`texaudit` 是判据，
    本函数只给事实）。容器认定用栈、不用"往前找最近的 `\\begin`"：`\\begin{theorem}`
    里套 `enumerate` 时，往前找会认成 `enumerate`，而读者看到的是 Theorem 的编号。

    三态：容器认不出（自定义环境名且标题读不出）⇒ `kind=""`，调用方不许据此判红。
    `mode`（小节 / 附录）按文件跨片段保留 —— `\\input` 会把一份正文切成多段。
    """
    titles = {m.group("name").strip(): PM._printed_env_title(m.group("title"))  # noqa: SLF001
              for m in _NEWTHEOREM_TITLE_RE.finditer(str(main_text or ""))}

    def _kind(name: str) -> str:
        name = str(name or "").strip()
        if name in CONTAINER_KINDS:
            return name
        printed = titles.get(name, "")
        return printed if printed in CONTAINER_KINDS else ""

    labels: dict[str, dict] = {}
    envs: list[dict] = []
    ref_nouns: list[tuple[str, int, str, str]] = []
    declarations: list[tuple[str, int, str]] = []
    unprefixed = 0
    mode_by_file: dict[str, str] = {}
    for rel, seg, offset in segments:
        stack: list[dict] = []
        opened: list[dict] = []
        for m in _STRUCT_TOKEN_RE.finditer(seg):
            line = offset + seg.count("\n", 0, m.start()) + 1
            name = m.group("env")
            if name:
                if m.group("which") == "begin":
                    frame = {"name": name, "file": rel, "line": line, "labelled": False}
                    stack.append(frame)
                    opened.append(frame)
                elif stack and stack[-1]["name"] == name:
                    stack.pop()
                continue
            if m.group("label") is not None:
                key = m.group("label").strip()
                if not key:
                    continue
                if ":" not in key:
                    unprefixed += 1
                frame = next((f for f in reversed(stack) if _kind(f["name"])), None)
                kind = _kind(frame["name"]) if frame is not None else mode_by_file.get(rel, "")
                if frame is not None:
                    frame["labelled"] = True
                labels.setdefault(key, {"file": rel, "line": line, "kind": kind})
                continue
            mode_by_file[rel] = "appendix" if m.group("appendix") else (
                "appendix" if mode_by_file.get(rel) == "appendix" else "section")
        envs.extend(opened)
        for m in _REF_NOUN_RE.finditer(seg):
            line = offset + seg.count("\n", 0, m.start()) + 1
            ref_nouns.append((rel, line, " ".join(m.group("noun").lower().split()),
                              m.group("key").strip()))
        emph_spans: list[tuple[int, int]] = []
        for m in _EMPH_BLOCK_RE.finditer(seg):
            emph_spans.append((m.start(), m.end()))
            text = " ".join(m.group(1).split())
            if _is_declaration(text):
                declarations.append((rel, offset + seg.count("\n", 0, m.start()) + 1, text))
        spans = [(m.start(), m.end()) for m in _PARAGRAPH_SPLIT_RE.finditer(seg)]
        bounds = [(0, spans[0][0] if spans else len(seg))]
        bounds += [(spans[i][1], spans[i + 1][0] if i + 1 < len(spans) else len(seg))
                   for i in range(len(spans))]
        for start, end in bounds:
            if any(s >= start and e <= end for s, e in emph_spans):
                continue  # 这一段的声明已经在 `\emph` 块那一档数过了
            text = " ".join(seg[start:end].split())
            if text and _is_declaration(text):
                declarations.append((rel, offset + seg.count("\n", 0, start) + 1, text))
    return {"labels": labels, "envs": envs, "ref_nouns": ref_nouns,
            "declarations": declarations, "unprefixed": unprefixed}


def _is_declaration(text: str) -> bool:
    """这一段是不是"审阅状态"那一族固定声明（词表唯一来源 `DECLARATION_MARKERS`）。"""
    low = text.lower()
    return any(marker in low for marker in DECLARATION_MARKERS)
