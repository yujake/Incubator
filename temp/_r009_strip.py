"""把 R009 点名的成对 `**` 去掉 —— **只动注释与文档串**（tokenize 定位，不碰代码）。

为什么重写：第一版是按"行里有没有 `**...**`"做正则替换，于是把一行**代码**里的解包
`S.Task(**{**row, "error": None}).validate()` 改成了 `S.Task({row, ...})` —— 语法当场坏掉，
而所有单文件判据都没跑到它（那是"全量门"才撞出来的：全量 pytest 以 collection error 退出）。
教训记进 `draft/65` 那一类：批量文本处理工具必须先划出语法边界，不能拿"看起来像 markdown
强调"当判据。

现在的口径：用 `tokenize` 逐 token 走，只在
  - `COMMENT`（`# ...`），或
  - 作为**文档串**的 `STRING`（模块/类/函数体第一条表达式语句的那个）
里做 `**x**` → `x` 的替换；代码里的 `**`（解包、幂运算）**一个都不碰**。
替换后 `ast.parse` 自检：语法坏了就不写回并报错。

用法：
    python -B temp/_r009_strip.py <文件...>            # dry-run，只报会改哪里
    python -B temp/_r009_strip.py --write <文件...>
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize

PAIR = re.compile(r"\*\*([^*\n]+?)\*\*")


def _docstring_spans(source: str) -> list[tuple[int, int, int, int]]:
    """所有**文档串**的 `(start_row, start_col, end_row, end_col)`（行列均 1-based/0-based 混用按 tokenize 口径）。"""
    spans: list[tuple[int, int, int, int]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return spans
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            spans.append((first.value.lineno, first.value.col_offset,
                          first.value.end_lineno or first.value.lineno,
                          first.value.end_col_offset or 0))
    return spans


def _in_a_docstring(row: int, col: int, spans: list[tuple[int, int, int, int]]) -> bool:
    for srow, scol, erow, ecol in spans:
        if (srow, scol) <= (row, col) < (erow, ecol):
            return True
    return False


def strip_file(path: pathlib.Path, *, write: bool) -> tuple[int, list[str]]:
    source = path.read_text(encoding="utf-8")
    spans = _docstring_spans(source)
    lines = source.splitlines(keepends=True)
    editable: list[tuple[int, int, int, int]] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            editable.append((tok.start[0], tok.start[1], tok.end[0], tok.end[1]))
        elif tok.type == tokenize.STRING and _in_a_docstring(tok.start[0], tok.start[1], spans):
            editable.append((tok.start[0], tok.start[1], tok.end[0], tok.end[1]))
    changes: list[str] = []
    for row, start_col, end_row, end_col in editable:
        if row != end_row:
            continue  # 多行字符串逐行处理会错位；本仓的强调标记都在单行里
        line = lines[row - 1]
        segment = line[start_col:end_col]
        if not PAIR.search(segment):
            continue
        new_segment = PAIR.sub(lambda m: m.group(1), segment)
        new_line = line[:start_col] + new_segment + line[end_col:]
        changes.append(f"{path.name}:{row}\n  - {line.rstrip()}\n  + {new_line.rstrip()}")
        lines[row - 1] = new_line
    if not changes:
        return 0, []
    new_source = "".join(lines)
    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        raise SystemExit(f"{path}: 替换后语法坏了（{exc}）—— 不写回，请人工看")
    if write:
        path.write_text(new_source, encoding="utf-8", newline="")
    return len(changes), changes


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--write"]
    write = "--write" in sys.argv
    if not args:
        print("用法：python -B temp/_r009_strip.py [--write] <文件...>")
        return 2
    total = 0
    for rel in args:
        path = pathlib.Path(rel)
        if not path.is_file():
            print(f"  ?? {rel} 不在盘上")
            continue
        count, changes = strip_file(path, write=write)
        total += count
        if changes:
            print("\n".join(changes))
    print(f"\n共 {total} 处" + ("" if write else "（dry-run；加 --write 落盘）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
