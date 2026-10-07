"""对比 agentflow 与原型 test/test1/abflow 的**顶层符号集合**，给人工复核提供走查清单。

为什么用符号集合而不是行 diff：
  - 两份树的缩进/换行/包名都可能不同，行 diff 会淹没在噪声里；
  - 复核人要的是"**新增了哪些可被调用的东西**"，符号名正好是那个粒度；
  - 反过来，"原型有、正式版没有"的符号是**删除/改名**，同样需要人看。

三态：符号只在正式版 => NEW；只在原型 => GONE；两边都有 => 同名（可能是被改过的实现，
本脚本**不判断**它有没有被改 —— 不猜）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

A = Path(r"D:\Incubator\agentflow\src\agentflow")
B = Path(r"D:\Incubator\test\test1\src\abflow")

TARGETS = [
    "schema.py", "store.py", "verify.py", "interactions.py", "dedup.py",
    "providers.py", "extract.py", "quoteverify.py",
    "tools/__init__.py", "tools/base.py", "tools/verify_tools.py",
]


def symbols(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError) as exc:
        return {f"<ERR {type(exc).__name__}>"}
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(f"def {node.name}")
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out.add(f"{node.name}.{sub.name}")
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(f"var {t.id}")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(f"var {node.target.id}")
    return out


print(f"正式版 {A}")
print(f"原型   {B}")
print()
for rel in TARGETS:
    pa, pb = A / rel, B / rel
    if not pa.is_file():
        print(f"### {rel}: 正式版缺该文件")
        continue
    sa = symbols(pa)
    sb = symbols(pb) if pb.is_file() else set()
    new = sorted(sa - sb)
    gone = sorted(sb - sa)
    print(f"### {rel}")
    print(f"    正式版符号 {len(sa)}；原型符号 {len(sb)}  (原型{'存在' if pb.is_file() else '不存在'})")
    if new:
        print(f"    NEW  ({len(new)})：{', '.join(new)}")
    if gone:
        print(f"    GONE ({len(gone)})：{', '.join(gone)}")
    if not new and not gone:
        print("    符号集合相同（**实现是否被改过本脚本不判断**）")
    print()

# 顶层配置
for rel in ("pyproject.toml",):
    pa, pb = Path(r"D:\Incubator\agentflow") / rel, Path(r"D:\Incubator\test\test1") / rel
    print(f"### {rel}: 正式版{'存在' if pa.is_file() else '不存在'}；原型{'存在' if pb.is_file() else '不存在'}")
