# -*- coding: utf-8 -*-
"""安全清理 Markdown 强调标记：tokenize 定位 + AST 结构闸，只许动注释与文档串。

## 为什么需要它（2026-11-20 的真凭实据）

`2ab3bbdb`（"lint 清零"）用的 `temp/_fixdup.py` 是逐行 regex：先判行里有没有成对星号
（`if "**" in line`），再对整行做一次「两个星号 + 内容 + 两个星号」的替换
（`new = re.sub(...)` 那一段）。

它把 `agent_f/core.py` 里那条「两个字典解包并在一起」的字典字面量当成一对强调抹成
`{dict(fresh), dict(mine)}` —— 集合字面量，两个 dict 不可哈希 ⇒ 每次写回都
`TypeError: unhashable type: 'dict'`。它改的是 OP token，不是注释。
（原行的一个解包写作 `**dict(fresh)`；第二个解包紧跟着它，于是正好凑成一对。）

## 两道闸（缺一不可）

1. tokenize 闸：只在 `COMMENT` / `STRING` token 的内部替换字符；替换完重新
   tokenize，除注释/字符串内容外，token 序列必须逐字相同（NAME / OP / NUMBER /
   缩进 / 换行一个都不许变）。这直接堵死上面那次事故 —— 那行是 OP + NAME，
   根本不在可改范围里。
2. AST 闸：替换完 `ast.parse`，把字符串常量的内容抹平后 `ast.dump` 必须与改前
   逐字相等。也就是说：改的只能是内容，代码结构一格不许动。批量改动若过不了
   AST 闸，工具会逐条重放以定位是哪一条把结构改了，并把它拒掉（拒绝而不是硬写）。

## 用法（在 `agentflow/` 下；`--root` 缺省 = 当前目录）

    python scripts/safe_comment_fix.py --check              # 只报，不改；有候选 ⇒ 退出码 1
    python scripts/safe_comment_fix.py --apply              # 改并复核；有候选被拒 ⇒ 退出码 1
    python scripts/safe_comment_fix.py --check tests/x.py   # 只扫给定文件/目录

退出码沿用本仓的三态纪律：`0` = 查过、没有可清；`1` = 有候选（或需人看的残留星号）；
`2` = 没查成（读不出 / 解析不了）—— 没查成不是干净。

## 范围

- 默认只清 `COMMENT` 与文档串（模块/类/函数体的第一个表达式语句），与 lint R009
  的判据面一致。
- 非文档串（提示词、`exec` 的源码片段等）默认不动：AST 闸把字符串内容视为"内容"，
  结构上看不出语义变化，所以它们在默认面上必须保持原样。要用 `--strings all` 显式开。
- 残留的星号对（R009 也报）默认只报不改：注释里 `2.0` 后跟两个星号是乘方，
  去掉星号就变成另一句话了。`--stray drop` 才删。
- FC-27 禁改区（`scripts/noai_gate.py` 的清单）：`--check` 照报，`--apply` 跳过
  并打出来；要改必须显式 `--include-protected`（那意味着这活归人，不归 AI）。
  清单读不到时 `--apply` 以退出码 2 收场（没查成不是干净）。
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import re
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

#: 成对强调的判据与 lint R009 同形（星号 + 非空 + 非星号，上限 400 字符）。
_PAIR = re.compile(r"\*\*(?=\S)([^*]{1,400}?)(?<=\S)\*\*", re.S)
#: 代码跨度：双反引号与单反引号两种（先长后短）。跨度内的星号一律不动，与 R009 一致。
_CODE_SPAN = re.compile(r"``.+?``|`[^`\n]+`", re.S)
#: 残留的成对星号（成对强调清掉之后剩下的）。
_STRAY = re.compile(r"\*\*")

_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".pytest-tmp"}
_DEFAULT_ROOTS = ("src", "tests", "scripts", "tools")


@dataclass
class Change:
    """一条候选改动：token 在全文里的绝对字符区间 + 改前/改后 token 文本。"""

    start: int
    end: int
    lineno: int
    kind: str          # comment / docstring / string
    before: str
    after: str


@dataclass
class FileResult:
    path: Path
    changes: list[Change] = field(default_factory=list)
    strays: list[tuple[int, str]] = field(default_factory=list)
    rejected: list[tuple[Change, str]] = field(default_factory=list)
    error: str = ""

    @property
    def accepted(self) -> int:
        return len(self.changes) - len(self.rejected)


# ============================================================ 文本变换


def _masked(text: str) -> str:
    """把代码跨度换成等长占位符（等长是为了让下标仍对得上）。"""
    return _CODE_SPAN.sub(lambda m: "\x00" * len(m.group(0)), text)


def _apply_cuts(text: str, cuts: list[tuple[int, int]]) -> str:
    """按区间删字符（从后往前，区间互不重叠）。"""
    out = text
    for start, end in sorted(cuts, reverse=True):
        out = out[:start] + out[end:]
    return out


def strip_decoration(text: str, *, drop_stray: bool = False) -> tuple[str, int]:
    """去强调标记 ⇒ (新文本, 残留星号处数)。代码跨度里的星号一个都不碰。

    为什么先遮再找、却按原区间删：`re.sub` 直接跑在原文上会把代码跨度里的
    `dict` 解包（`**dict(fresh)` 那一段）当成一对强调（那正是这次事故的形态，只是发生在文档串里）。
    这里在"被遮住"的文本上定位、只删两端的四个星号字符，中段一个字节都不动。
    """
    masked = _masked(text)
    cuts: list[tuple[int, int]] = []
    for m in _PAIR.finditer(masked):
        cuts.append((m.start(), m.start() + 2))
        cuts.append((m.end() - 2, m.end()))
    new = _apply_cuts(text, cuts)
    stray_left = len(_STRAY.findall(_masked(new)))
    if drop_stray and stray_left:
        cuts = [(m.start(), m.end()) for m in _STRAY.finditer(_masked(new))]
        new = _apply_cuts(new, cuts)
        stray_left = 0
    return new, stray_left


# ============================================================ 结构闸


def structural_dump(src: str) -> str:
    """代码结构指纹：字符串常量的内容抹平，其余 AST 形状逐字保留。

    这就是"注释/docstring 内容可不同，代码结构必须完全相等"的机器读数。
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
        elif isinstance(node, ast.JoinedStr):
            # f-string 只看"有几个插值"；字面量段属于内容。
            node.values = [v for v in node.values if isinstance(v, ast.FormattedValue)]
    return ast.dump(tree)


def token_skeleton(src: str) -> list[tuple[int, str]]:
    """token 骨架：注释/字符串只记类型（内容可变），其余按 (类型, 原文) 逐字比。"""
    out: list[tuple[int, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            out.append((tok.type, ""))
        else:
            out.append((tok.type, tok.string))
    return out


def _offsets(src: str) -> tuple[list[str], list[int]]:
    """返回 (按物理行切开的 lines, 每行起点的绝对字符偏移)。"""
    lines = src.splitlines(keepends=True)
    starts: list[int] = []
    pos = 0
    for line in lines:
        starts.append(pos)
        pos += len(line)
    return lines, starts


def _docstring_spans(src: str) -> list[tuple[int, int]]:
    """文档串在源码里的 (起始行, 起始字符列) 清单。

    为什么用 AST 定位、又把字节列换成字符列：`ast` 的 `col_offset` 是 UTF-8 字节
    偏移，`tokenize` 给的是字符偏移；本仓源码中文很多，混用会让区间滑进代码
    （R009 的注释里记过同一个坑）。这里只比"起始行 + 起始字符列"，不做区间裁剪。
    """
    lines = src.splitlines()

    def char_col(lineno: int, byte_col: int) -> int:
        if not 1 <= lineno <= len(lines):
            return byte_col
        return len(lines[lineno - 1].encode("utf-8")[:byte_col].decode("utf-8", "ignore"))

    spans: list[tuple[int, int]] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            const = first.value
            spans.append((const.lineno, char_col(const.lineno, const.col_offset)))
    return spans


def _is_docstring(tok: tokenize.TokenInfo, spans: list[tuple[int, int]]) -> bool:
    return (tok.start[0], tok.start[1]) in spans


# ============================================================ 找候选


def collect(src: str, *, strings: str, drop_stray: bool = False) -> FileResult:
    """扫一份源码 ⇒ 候选改动 + 残留星号（不改任何东西）。"""
    res = FileResult(path=Path("."))
    _lines, starts = _offsets(src)
    spans = _docstring_spans(src) if strings in ("doc", "all") else []

    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            kind = "comment"
        elif tok.type == tokenize.STRING:
            is_doc = _is_docstring(tok, spans)
            if not (is_doc or strings == "all"):
                continue
            kind = "docstring" if is_doc else "string"
        else:
            continue
        before = tok.string
        after, stray = strip_decoration(before, drop_stray=drop_stray)
        if stray:
            for idx, line in enumerate(before.splitlines() or [before]):
                if _STRAY.search(_masked(line)):
                    res.strays.append((tok.start[0] + idx, line.strip()))
        if after == before:
            continue
        res.changes.append(Change(
            start=starts[tok.start[0] - 1] + tok.start[1],
            end=starts[tok.end[0] - 1] + tok.end[1],
            lineno=tok.start[0], kind=kind, before=before, after=after))
    return res


# ============================================================ 应用 + 双闸


def splice(src: str, changes: list[Change]) -> str:
    out = src
    for ch in sorted(changes, key=lambda c: c.start, reverse=True):
        out = out[:ch.start] + ch.after + out[ch.end:]
    return out


def gate(src: str, new: str) -> str:
    """双闸复核 ⇒ 通过返回空串，否则返回拒绝理由。"""
    try:
        if structural_dump(src) != structural_dump(new):
            return "AST 结构不等（代码形状被改动）"
    except (SyntaxError, ValueError, tokenize.TokenError) as e:
        return f"AST 解析失败（{type(e).__name__}: {e}）"
    try:
        if token_skeleton(src) != token_skeleton(new):
            return "token 序列不等（注释/字符串之外有 token 被改动）"
    except (tokenize.TokenError, IndentationError) as e:
        return f"重新 tokenize 失败（{type(e).__name__}: {e}）"
    return ""


def apply_file(path: Path, *, strings: str, drop_stray: bool) -> FileResult:
    """对一份文件应用候选改动，逐条过双闸；被拒的那条不写。"""
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            src = fh.read()
    except OSError as e:
        res = FileResult(path=path)
        res.error = f"读不出（{type(e).__name__}: {e}）"
        return res
    try:
        res = collect(src, strings=strings, drop_stray=drop_stray)
    except (tokenize.TokenError, SyntaxError, IndentationError, ValueError) as e:
        res = FileResult(path=path)
        res.error = f"tokenize/AST 失败（{type(e).__name__}: {e}）"
        return res
    res.path = path
    if not res.changes:
        return res

    new = splice(src, res.changes)
    why = gate(src, new)
    if not why:
        _write(path, new)
        return res

    # 批量过不了 ⇒ 逐条重放，定位并拒绝真正破坏结构的那几条。
    accepted: list[Change] = []
    for ch in res.changes:
        why_one = gate(src, splice(src, accepted + [ch]))
        if why_one:
            res.rejected.append((ch, why_one))
        else:
            accepted.append(ch)
    if accepted:
        # 防御性复核：改动区间互不重叠 ⇒ 逐条过闸理论上蕴含合并过闸；
        # 真出现意外就一个字节都不写（fail closed，不许"先写再回滚"）。
        final = splice(src, accepted)
        why_final = gate(src, final)
        if why_final:
            res.rejected.extend((ch, f"合并后复核失败：{why_final}") for ch in accepted)
            accepted = []
    if accepted:
        _write(path, splice(src, accepted))
    return res


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


# ============================================================ 入口


def _iter_files(targets: list[Path]) -> list[Path]:
    got: list[Path] = []
    for t in targets:
        if t.is_file():
            if t.suffix == ".py":
                got.append(t)
            continue
        if not t.is_dir():
            continue
        for p in sorted(t.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            got.append(p)
    return got


def _load_protected(root: Path):
    """读 FC-27 禁改区清单 ⇒ (gate 包, "") 或 (None, 读不到的理由)。

    为什么清理脚本要自己读这张清单：它能改的正是注释/docstring —— 而 FC-27 里那
    23 个文件的注释只能由人改。一个"只改注释"的工具最容易变成绕开 FC-27 的暗门，
    所以 `--apply` 默认跳过禁改区，要改必须显式 `--include-protected`。
    """
    script = root / "scripts" / "noai_gate.py"
    manifest_path = root / ".noai-paths"
    if not script.is_file() or not manifest_path.is_file():
        return None, f"禁改区清单读不到（{script} / {manifest_path}）"
    try:
        spec = importlib.util.spec_from_file_location("_fixguard_noai_gate", script)
        if spec is None or spec.loader is None:
            return None, f"加载不了 {script}"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        manifest = mod.load_manifest(manifest_path)
    except Exception as e:  # noqa: BLE001
        return None, f"禁改区清单加载失败（{type(e).__name__}: {e}）"
    return (mod, manifest), ""


def _is_protected(path: Path, root: Path, gate_pack) -> bool:
    if gate_pack is None:
        return False
    mod, manifest = gate_pack
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    return bool(mod.check_paths([rel], manifest=manifest, root=root.resolve()).violations)


def _report(res: FileResult) -> tuple[bool, int]:
    """打印一份文件的读数 ⇒ (有没有需要人看的东西, 候选数)。"""
    attention = bool(res.changes or res.strays)
    rejected_ids = {id(ch) for ch, _ in res.rejected}
    for ch in res.changes:
        if id(ch) in rejected_ids:
            continue
        print(f"{res.path}:{ch.lineno}: {ch.kind} 候选")
        print(f"  改前: {ch.before.strip()[:160]}")
        print(f"  改后: {ch.after.strip()[:160]}")
    for lineno, line in res.strays:
        print(f"{res.path}:{lineno}: 残留星号（需人看，未自动改）: {line[:120]}")
    for ch, why in res.rejected:
        print(f"{res.path}:{ch.lineno}: 拒绝（{why}）")
    return attention, len(res.changes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tokenize + AST 双闸的注释/文档串清理（R009 口径）")
    ap.add_argument("--check", action="store_true", help="只报候选，不改文件")
    ap.add_argument("--apply", action="store_true", help="应用候选（逐条过双闸）")
    ap.add_argument("--strings", choices=("doc", "all", "none"), default="doc",
                    help="可改的字符串面：doc=只改文档串（默认）/ all=所有字符串 / none=只改注释")
    ap.add_argument("--stray", choices=("report", "drop"), default="report",
                    help="残留单个星号的处置：report=只报（默认）/ drop=删掉（有风险，见文件头）")
    ap.add_argument("--include-protected", action="store_true",
                    help="连 FC-27 禁改区一起改（默认跳过；这活归人）")
    ap.add_argument("--root", type=Path, default=Path("."), help="扫相对这个根（默认 cwd）")
    ap.add_argument("paths", nargs="*", type=Path,
                    help=f"文件或目录；默认扫 {' / '.join(_DEFAULT_ROOTS)}")
    args = ap.parse_args(argv)
    if args.check == args.apply:
        ap.error("--check 与 --apply 必须二选一")

    root: Path = args.root
    if args.paths:
        targets = [p if p.is_absolute() else root / p for p in args.paths]
    else:
        targets = [root / rel for rel in _DEFAULT_ROOTS]
    files = _iter_files(targets)

    gate_pack, gate_err = _load_protected(root)
    if gate_err:
        print(f"[guard] {gate_err}")
        if args.apply:
            print("[apply] 禁改区判定没查成 ⇒ 拒绝写（没查成不是干净）")
            return 2

    unknown: list[str] = []
    total_changes = 0
    attention = False
    skipped_protected: list[Path] = []
    applied: list[Path] = []
    for path in files:
        protected = _is_protected(path, root, gate_pack)
        if args.apply and protected and not args.include_protected:
            skipped_protected.append(path)
            continue
        if args.check:
            try:
                with path.open("r", encoding="utf-8", newline="") as fh:
                    src = fh.read()
                res = collect(src, strings=args.strings, drop_stray=args.stray == "drop")
            except (OSError, tokenize.TokenError, SyntaxError, IndentationError, ValueError) as e:
                unknown.append(f"{path}（{type(e).__name__}）")
                continue
            res.path = path
        else:
            res = apply_file(path, strings=args.strings, drop_stray=args.stray == "drop")
            if res.error:
                unknown.append(f"{path}（{res.error}）")
                continue
            applied.append(path)
        if protected:
            print(f"{path}: [FC-27 禁改区] {'--check 只报' if args.check else '绕过开关才改'}")
        need, n = _report(res)
        attention = attention or need
        total_changes += n

    mode = "check" if args.check else "apply"
    print(f"[{mode}] 扫了 {len(files)} 个 .py；涉及 {total_changes} 处候选"
          + (f"；跳过 FC-27 文件 {len(skipped_protected)} 个" if skipped_protected else ""))
    if unknown:
        print(f"[{mode}] {len(unknown)} 个文件没查成：{'；'.join(unknown[:5])}"
              + ("…" if len(unknown) > 5 else ""))
        return 2
    if args.apply:
        # 复核：应用后再扫一次，应当没有候选（被拒的那几条会再次出现）。
        leftover = 0
        try:
            for path in applied:
                with path.open("r", encoding="utf-8", newline="") as fh:
                    src = fh.read()
                leftover += len(collect(src, strings=args.strings,
                                        drop_stray=args.stray == "drop").changes)
        except (OSError, tokenize.TokenError, SyntaxError, IndentationError, ValueError):
            print("[apply] 复核没查成")
            return 2
        print(f"[apply] 复核：剩余候选 {leftover} 处")
        return 1 if leftover else 0
    return 1 if attention else 0


if __name__ == "__main__":
    sys.exit(main())
