"""只读探针：schema/store/providers/closing 的规模读数（调查 C 用）。"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(r"D:\Incubator\agentflow\src\agentflow")
FILES = ["schema.py", "store.py", "providers.py", "closing.py", "dedup.py",
         "quoteverify.py", "extract.py", "fetch.py", "locallib.py"]


def count_comment_lines(src: str) -> tuple[int, int]:
    """返回 (注释行数, 非空行数)。只看以 # 开头的行（不含 docstring）。"""
    comment = 0
    nonblank = 0
    for line in src.splitlines():
        s = line.strip()
        if not s:
            continue
        nonblank += 1
        if s.startswith("#"):
            comment += 1
    return comment, nonblank


def docstring_lines(src: str) -> int:
    tree = ast.parse(src)
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            ds = ast.get_docstring(node, clean=False)
            if ds:
                total += ds.count("\n") + 1
    return total


for name in FILES:
    p = SRC / name
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((node.end_lineno - node.lineno + 1, node.lineno, node.name))
    funcs.sort(reverse=True)
    comment, nonblank = count_comment_lines(src)
    ds = docstring_lines(src)
    total = len(src.splitlines())
    print(f"--- {name}: 总行 {total} / 非空 {nonblank} / 纯注释行 {comment} ({comment/nonblank:.1%}) / docstring 行 {ds} ({ds/total:.1%}) / 函数数 {len(funcs)}")
    print("    最长 5 个函数：")
    for n, ln, fname in funcs[:5]:
        print(f"      {n:>4} 行  {name}:{ln}  {fname}")
