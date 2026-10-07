# -*- coding: utf-8 -*-
"""R009 的修法（**只动注释与 docstring**，逐行保留原有行尾）：把 Markdown 强调标记与 emoji 去掉。

为什么必须"按区间改"而不是全文件正则替换：
- 全文件 `**` → `` 会改到**代码**（`2.0**attempt`、`**kwargs`、类型注解里的 `**`）；
- 全文件读-改-写会把 CRLF 归一成 LF（`table_tools.py` 等文件是 CRLF，§136 记过一次
  "裸 LF 让 git diff 把相邻行也显示成改动"的教训）。

做法：
1. 区间 = `tokenize` 的 COMMENT token + `ast` 的模块/类/函数 docstring（与 `_r009_scan` 同一套定义）；
2. 只在区间内替换：`**X**` → `X`、剩下的 `**` → ``、emoji → ``；
3. 反引号代码跨度（`` `x` ``）先遮掉 —— 规则本身也是这么做的（`_r009_mask_code`）；
4. 逐行拼接，**只改行的中段** ⇒ 行尾与未命中的行逐字节不变。

用法：
    python -B temp/_r009_fix.py            # dry-run：只报"每个文件会改几处"
    python -B temp/_r009_fix.py --apply    # 真改
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import pathlib
import re
import sys
import time
import tokenize

ROOT = pathlib.Path(r"D:\Incubator\agentflow")


def load_lint():
    spec = importlib.util.spec_from_file_location("_lint", ROOT / "scripts" / "lint_rules.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lint"] = mod
    spec.loader.exec_module(mod)
    return mod


L = load_lint()
BOLD, STRAY, EMOJI = L._R009_BOLD, L._R009_STRAY, L._R009_EMOJI
CODE = L._R009_CODE_SPAN
#: emoji 的**连排**（`⚠️` 是两个码位：U+26A0 + U+FE0F），按"一串"删。
EMOJI_RUN = re.compile(f"[{L._R009_EMOJI_CLS}]+")
#: 残留星号的删除点：连同紧邻的空格一起看 —— 见 `_drop` 的注释。
STRAY_SP = re.compile(r"([ \t]*)\*\*([ \t]*)")


def _drop(left: str, right: str) -> str:
    """删掉一处装饰后，这一点该留下什么。

    规则只有一条：**只要两侧本来有空格，就收敛成一个空格；否则什么都不留**。
    不这么做会留下 `##␣␣它是…` 这种双空格（第一版就是这样，肉眼一看就毛），
    而"把全行连续空格压成一个"又会毁掉注释里的对齐列（`x␣␣␣= 1`）。
    折中办法就是把作用域限制在**删除点**上。
    """
    return " " if (left or right) else ""


def char_col(line: str, byte_col: int) -> int:
    """`ast` 给的是 UTF-8 字节偏移，换算成字符下标（与 `_r009_scan` 用同一条换算）。"""
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", "ignore"))


def regions(text: str) -> list[tuple[int, int, int, int]]:
    """本次要动的区间（1 起行号 + 字符列），与 `_r009_scan` 的区间定义逐条相同。"""
    lines = text.split("\n")
    out: list[tuple[int, int, int, int]] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            out.append((tok.start[0], tok.start[1], tok.end[0], tok.end[1]))
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        srow, scol = first.value.lineno, char_col(lines[first.value.lineno - 1], first.value.col_offset)
        erow, ecol = first.value.end_lineno, char_col(lines[first.value.end_lineno - 1],
                                                      first.value.end_col_offset)
        out.append((srow, scol, erow, ecol))
    return out


def transform(fragment: str, *, at_eol: bool) -> tuple[str, int]:
    """在**一段文本**里去掉装饰；返回 `(新文本, 改了几处)`。代码跨度内的内容原样保留。

    刻意不做"把连续空格压成一个"：本仓库的注释里有对齐用的列（形如 `x   = 1`），
    压空格会把它们弄乱 —— 而去掉 emoji 后多出来的一个空格不是 lint 缺陷。
    只在片段顶到行尾时右截，免得 emoji 正好在行尾留下尾随空格。
    """
    pieces: list[str] = []
    changed = 0
    pos = 0
    for m in CODE.finditer(fragment):
        pieces.append(fragment[pos:m.start()])
        pieces.append(m.group(0))          # 代码跨度：原样
        pos = m.end()
    pieces.append(fragment[pos:])
    out: list[str] = []
    for i, piece in enumerate(pieces):
        if i % 2 == 1:                     # 奇数位 = 代码跨度
            out.append(piece)
            continue
        new, n = BOLD.subn(lambda mm: mm.group(1), piece)
        new, n2 = STRAY_SP.subn(lambda mm: _drop(mm.group(1), mm.group(2)), new)
        new, n3 = re.subn(
            f"([ \t]*)(?:[{L._R009_EMOJI_CLS}]+)([ \t]*)",
            lambda mm: _drop(mm.group(1), mm.group(2)), new)
        changed += n + n2 + n3
        out.append(new)
    text = "".join(out)
    if at_eol and changed:
        # 顶到行尾时才右截：删掉行尾的装饰后可能留下一个空格。
        # 不改动中间的空格（注释里有对齐列），只清尾部。
        text = text.rstrip()
    return text, changed


def fix_file(path: pathlib.Path, *, apply: bool) -> int:
    raw_bytes = path.read_bytes()
    raw = raw_bytes.decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    lines = text.split("\n")               # 无行尾（拼接时按 nl 还原）
    # 自检 1：不改动时逐字节还原。混用行尾的文件会在这里被拦下，
    # 而不是被悄悄归一（§136 记过"裸 LF 让 diff 显示成大片改动"）。
    if nl.join(lines).encode("utf-8") != raw_bytes:
        raise SystemExit(f"行尾自检失败（混用行尾？）：{path}")
    total = 0
    for srow, scol, erow, ecol in regions(text):
        for row in range(srow, erow + 1):
            if not 1 <= row <= len(lines):
                continue
            line = lines[row - 1]
            lo = scol if row == srow else 0
            hi = ecol if row == erow else len(line)
            lo, hi = max(0, min(lo, len(line))), max(0, min(hi, len(line)))
            if lo >= hi:
                continue
            new, n = transform(line[lo:hi], at_eol=(hi == len(line)))
            if n:
                lines[row - 1] = line[:lo] + new + line[hi:]
                total += n
    if apply and total:
        out = nl.join(lines).encode("utf-8")
        # 自检 2：改动后仍是合法 Python，且行数不变（"改了但语法坏了"比"没改"更糟）。
        try:
            compile(out.decode("utf-8"), str(path), "exec")
        except SyntaxError as exc:
            raise SystemExit(f"改完语法坏了，未写盘：{path}\n{exc}")
        if len(out.decode("utf-8").replace("\r\n", "\n").split("\n")) != len(lines):
            raise SystemExit(f"改完行数变了，未写盘：{path}")
        path.write_bytes(out)
    return total


def main() -> int:
    apply = "--apply" in sys.argv
    gate = L._r009_load_gate()
    rules = gate.load_manifest(ROOT / ".noai-paths")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = ROOT.parent / "temp" / f"R009-backup-{stamp}"
    manifest: list[str] = []
    grand = 0
    files = 0
    for base in ("src", "tests", "scripts", "tools"):
        for p in sorted((ROOT / base).rglob("*.py")):
            text = p.read_text(encoding="utf-8")
            hits, _ = L._r009_scan(text)
            if not hits:
                continue
            rel = p.relative_to(ROOT).as_posix()
            if gate.check_paths([rel], manifest=rules, root=ROOT).violations:
                continue                    # 禁改区内：R009 只报一条 info（人的待办），本脚本不动
            original = p.read_bytes()
            n = fix_file(p, apply=apply)
            if n:
                files += 1
                grand += n
                if apply:
                    dst = backup / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(original)
                    manifest.append(
                        f"{hashlib.sha256(original).hexdigest()}  {rel}")
                print(f"  {n:4d} 处  {rel}")
    if apply and manifest:
        backup.mkdir(parents=True, exist_ok=True)
        (backup / "SHA256SUMS.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
        print(f"\n备份（改前逐字节）：{backup}")
    print(f"\n{'已改' if apply else '将改'}：{files} 个文件 / {grand} 处")
    if not apply:
        print("（dry-run；加 --apply 才写盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
