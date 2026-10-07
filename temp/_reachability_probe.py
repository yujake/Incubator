# -*- coding: utf-8 -*-
"""活性三层判据的 **L2 读数**：一个符号的引用点，分别落在**哪个函数**里 / 那些函数是不是真入口。

为什么要这个工具（而不是 `grep` 数一遍）：`grep` 出来的"生产面 1 处"可能是 `selftest()` 里的调用 ——
实测 `secretary.handoff_revise` / `handoff_query` 各有一处引用，**两处都在 `secretary.selftest()` 里**
（`secretary.py:1161/1165`）。按活性三层判据的 L2 逐字要求「调用链递归到真入口，**selftest/测试/探针不算入口**」，
那两处必须判成"不是生产面"。本工具就是把这一条做成机器读数。

口径（逐条写清，免得下一次读成别的东西）：
- **引用点**：AST 里出现的 `Name(id=sym)` 或 `Attribute(attr=sym)` 节点。
  `def sym(...)` / 形参 / 字符串里的名字**不算**引用点。
- **归属函数**：引用点所在的**最内层 `def`/`async def`**（含嵌套 def），并给出它所在的最外层 def。
- **入口判定**（三档，逐条可核）：
  - `tests`：文件在 `tests/` 下 ⇒ 不是生产入口（按 L2 逐字）。
  - `selftest`：最外层函数名在 `SELFTEST_NAMES` 里、或文件是 `__main__.py`/模块级 `if __name__` 块 ⇒ 不算入口。
  - `prod`：其余 ⇒ **算生产面**（但请注意：本工具**只走一层**——不做传递闭包。
    "A 调 B、B 调 sym、而 A 从没人调"这种情况本工具判不出来，它会如实把它记成 `prod`，
    所以结论要用"**落在哪个函数里**"复核，不要只看计数）。
- **别名/间接调用判不出来**：`getattr(obj, "sym")`、字符串派发（注册表按名字调）都看不见 ⇒
  本工具的读数只用于**否证**（找出"其实只在 selftest 里"），不用于断言"生产面一定 > 0"。

用法：
  python -B temp/_reachability_probe.py sym1 sym2 ...
  python -B temp/_reachability_probe.py --json sym1 ...
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from collections import defaultdict

REPO = pathlib.Path(r"D:\Incubator")
AGENTFLOW = REPO / "agentflow"
sys.stdout.reconfigure(encoding="utf-8")

#: 按 L2 逐字"selftest/测试/探针不算入口" —— 这些最外层函数名不算生产入口
SELFTEST_NAMES = {"selftest", "main", "demo", "smoke", "_demo", "cli_main", "run_selftests"}


def _enclosing(tree: ast.AST) -> list[tuple[int, int, str, str]]:
    """每个 `def` 的 `(起始行, 结束行, 自己的名字, 最外层 def 的名字)`。

    用"行区间包含"来定最内层 def（比临时维护栈稳）：区间最小且包含该行的那个就是最内层。
    """
    spans: list[tuple[int, int, str, str]] = []

    def walk(node: ast.AST, outermost: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                top = outermost or child.name
                end = getattr(child, "end_lineno", child.lineno) or child.lineno
                spans.append((child.lineno, int(end), child.name, top))
                walk(child, top)
            else:
                walk(child, outermost)

    walk(tree, None)
    return spans


def _innermost(spans: list[tuple[int, int, str, str]], line: int) -> tuple[str, str]:
    best: tuple[int, int, str, str] | None = None
    for s in spans:
        if s[0] <= line <= s[1] and (best is None or (s[1] - s[0]) < (best[1] - best[0])):
            best = s
    return (best[2], best[3]) if best else ("<module>", "<module>")


def _scan(symbols: set[str]) -> list[dict]:
    rows: list[dict] = []
    for root, tag in ((AGENTFLOW / "src", "src"), (AGENTFLOW / "tests", "tests"),
                      (AGENTFLOW / "tools", "tools"), (AGENTFLOW / "scripts", "scripts")):
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(text)
            except (SyntaxError, OSError):
                continue
            rel = str(p.relative_to(AGENTFLOW)).replace("\\", "/")
            spans = _enclosing(tree)
            for node in ast.walk(tree):
                sym = None
                kind = "symbol"
                if isinstance(node, ast.Name) and node.id in symbols:
                    sym = node.id
                elif isinstance(node, ast.Attribute) and node.attr in symbols:
                    sym = node.attr
                elif isinstance(node, ast.keyword) and node.arg in symbols:
                    sym = node.arg
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in symbols:
                    #: **工具名是字符串字面量**（`self.tools.call("doc.paper_build", …)`）——
                    #: 只数符号会把这种调用点漏掉（实测 ⑬：A 改走工具名以后符号面仍是"生产面 1"，
                    #: 而那 1 处是它自己的工具登记）。所以字符串精确匹配单独记一档 `literal`，
                    #: **不并进符号档**：字面量也会出现在文档串/注释里，强度比符号引用弱。
                    sym = node.value
                    kind = "literal"
                if sym is None:
                    continue
                inner, outer = _innermost(spans, node.lineno)
                if tag == "tests":
                    bucket = "tests"
                elif inner in SELFTEST_NAMES or outer in SELFTEST_NAMES or p.name == "__main__.py":
                    bucket = "selftest"
                else:
                    bucket = "prod"
                rows.append({"sym": sym, "file": rel, "line": node.lineno,
                             "inner": inner, "outer": outer, "bucket": bucket, "kind": kind,
                             "text": (text.splitlines()[node.lineno - 1] or "").strip()[:110]})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = _scan(set(a.symbols))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["sym"]].append(r)
    for sym in a.symbols:
        got = by.get(sym) or []
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in got:
            buckets[r["bucket"]].append(r)
        sym_only = [r for r in buckets["prod"] if r["kind"] == "symbol"]
        lit_only = [r for r in buckets["prod"] if r["kind"] == "literal"]
        print(f"== {sym}")
        print(f"   生产面 {len(buckets['prod'])}（符号 {len(sym_only)} · **工具名字面量 {len(lit_only)}**） · "
              f"自检/入口 {len(buckets['selftest'])} · 测试 {len(buckets['tests'])}")
        for b in ("prod", "selftest", "tests"):
            for r in buckets[b][:8]:
                tag = "符号" if r["kind"] == "symbol" else "字面量"
                print(f"     [{b}/{tag}] {r['file']}:{r['line']}  在 {r['inner']}() 里（最外层 {r['outer']}）")
                print(f"            {r['text']}")
        if not got:
            print("   （零引用点）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
