#!/usr/bin/env python
"""探针：找出 src/ 里"引用前缀元组"形态（含 rel/lit 字面量并列）的所有落点。"""
from __future__ import annotations

import ast
import pathlib
import sys

TARGETS = {"rel", "lit", "exp", "eval", "doc", "stmt"}


def main() -> int:
    root = pathlib.Path("src")
    for p in sorted(root.rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.Dict)):
                continue
            if isinstance(node, ast.Dict):
                keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
                vals = [k.value for k in node.values if isinstance(k, ast.Constant)]
                got = {str(x) for x in keys if isinstance(x, str)}
                if len(got & TARGETS) >= 2:
                    print(f"{p}:{node.lineno}: dict {sorted(got)} -> {sorted(str(v) for v in vals)}")
                continue
            vals = {getattr(e, "value", None) for e in node.elts}
            got = {v for v in vals if isinstance(v, str)}
            if len(got & TARGETS) >= 2:
                print(f"{p}:{node.lineno}: {sorted(got)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
