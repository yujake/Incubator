#!/usr/bin/env python
"""第三轮：按**失败用例的函数体**整体改写四位号（同一函数内两边一起改，保持一致）。

为什么按函数而不是按行：这些用例是"用工具建一行（号是分配出来的）→ 再按写死的
四位字面量去引用它"。只改断言行不够（引用在别处），而函数内所有四位字面量一起改，
两边仍然指向同一行。

安全边界：只动**当前失败**的函数；跳过注释行与含三引号的行（文档字符串不动）。
"""
from __future__ import annotations

import pathlib
import re
import sys

TB = pathlib.Path(r"D:\Incubator\temp\_r104_tb2.txt")
LINE_RE = re.compile(r"^(?P<file>[A-Z]:\\[^:]+\.py):(?P<line>\d+):")
DEF_RE = re.compile(r"^(?:async )?def |^class ")
BARE = re.compile(r"""(?P<q>["'])(?P<num>\d{4})(?P=q)""")
PREFIXED = re.compile(r"""(?P<q>["'])(?P<pre>[rptvwqmic])-(?P<num>\d{4})(?P=q)""")
PFMT = re.compile(r"(?P<pre>[rptvwqmic])-\{(?P<expr>[^}:]+):04d\}")


def failing_functions() -> dict[str, set[str]]:
    """文件 → 失败用例所在的函数名集合。"""
    out: dict[str, set[str]] = {}
    for raw in TB.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        p = pathlib.Path(m.group("file"))
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8").splitlines()
        ln = int(m.group("line"))
        name = ""
        for i in range(min(ln, len(src)) - 1, -1, -1):
            if src[i].startswith("def "):
                name = src[i][4:].split("(")[0].strip()
                break
        if name:
            out.setdefault(str(p), set()).add(name)
    return out


def rewrite(body: list[str]) -> tuple[list[str], int]:
    changed = 0
    for i, line in enumerate(body):
        s = line.strip()
        if s.startswith("#") or '"""' in line or "'''" in line:
            continue
        new = PREFIXED.sub(lambda m: f'f"{m.group("pre")}-{{S.format_id({int(m.group("num"))})}}"',
                           line)
        new = BARE.sub(lambda m: f"S.format_id({int(m.group('num'))})", new)
        new = PFMT.sub(lambda m: f'S.format_id({m.group("expr").strip()})', new)
        if new != line:
            body[i] = new
            changed += 1
    return body, changed


def ensure_import(p: pathlib.Path) -> None:
    text = p.read_text(encoding="utf-8")
    if "from agentflow import schema as S" in text:
        return
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith("from agentflow") or ln.startswith("import agentflow"):
            lines.insert(i, "from agentflow import schema as S\n")
            p.write_text("".join(lines), encoding="utf-8", newline="")
            return


def main() -> int:
    write = "--write" in sys.argv
    for file, funcs in sorted(failing_functions().items()):
        p = pathlib.Path(file)
        src = p.read_text(encoding="utf-8").splitlines(keepends=True)
        # 切出每个顶层 def 的区间
        starts = [(i, ln) for i, ln in enumerate(src)
                  if ln.startswith("def ") or ln.startswith("class ")]
        bounds: list[tuple[int, int, str]] = []
        for k, (i, ln) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else len(src)
            name = ln.split("(")[0][4:].strip() if ln.startswith("def ") else ""
            bounds.append((i, end, name))
        total = 0
        for i, end, name in bounds:
            if name not in funcs:
                continue
            body, changed = rewrite(src[i:end])
            src[i:end] = body
            total += changed
            print(f"[fix] {p.name}::{name}  改了 {changed} 行")
        if total and write:
            p.write_text("".join(src), encoding="utf-8", newline="")
            ensure_import(p)
        print(f"  → {p.name}：共 {total} 行（write={write}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
