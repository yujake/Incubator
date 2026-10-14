#!/usr/bin/env python
"""按 traceback 逐行修判据里写死的四位号（只动**当前失败**的那一行）。

口径：`"0001"` → `S.format_id(1)`；`"r-0001"` → `f"r-{S.format_id(1)}"`；
`f"{n:04d}"` → `S.format_id(n)`（同一个数的六位写法，语义等价）。

安全性来自"只改失败行"：夹具里那些**显式写 4 位号并且断言它**的用例不在这张表里
（它们本来就通过 —— `is_valid_id` 读侧两宽度都认）。
"""
from __future__ import annotations

import pathlib
import re
import sys

TB = pathlib.Path(r"D:\Incubator\temp\_r104_tb.txt")
ROOT = pathlib.Path(r"D:\Incubator\agentflow")

LINE_RE = re.compile(r"^(?P<file>[A-Z]:\\[^:]+\.py):(?P<line>\d+):")
BARE = re.compile(r"""(?P<q>["'])(?P<num>\d{4})(?P=q)""")
PREFIXED = re.compile(r"""(?P<q>["'])(?P<pre>[rptvwqmic])-(?P<num>\d{4})(?P=q)""")
PFMT = re.compile(r'f"(?P<pre>[rptvwqmic])-\{(?P<expr>[^}:]+):04d\}')


def parse_tb() -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for raw in TB.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        out.setdefault(m.group("file"), set()).add(int(m.group("line")))
    return out


def fix_line(text: str) -> tuple[str, bool]:
    changed = False

    def _bare(m: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f"S.format_id({int(m.group('num'))})"

    def _pref(m: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f'f"{m.group("pre")}-{{S.format_id({int(m.group("num"))})}}"'

    new = PREFIXED.sub(_pref, text)
    new = BARE.sub(_bare, new)
    new = PFMT.sub(lambda m: f'S.format_id({m.group("expr").strip()})', new)
    if raw_changed := (new != text):
        changed = True
    return new, raw_changed


def ensure_import(path: pathlib.Path, text: str) -> str:
    if "from agentflow import schema as S" in text:
        return text
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith("from agentflow") or ln.startswith("import agentflow"):
            lines.insert(i, "from agentflow import schema as S\n")
            path.write_text("".join(lines), encoding="utf-8", newline="")
            return "".join(lines)
    return text


def main() -> int:
    want = sys.argv[1] == "--write" if len(sys.argv) > 1 else False
    by_file = parse_tb()
    total = touched = 0
    for file, lines in sorted(by_file.items()):
        p = pathlib.Path(file)
        if not p.is_file():
            print(f"[miss] {file}")
            continue
        src = p.read_text(encoding="utf-8").splitlines(keepends=True)
        local = 0
        for ln in sorted(lines):
            if ln > len(src):
                continue
            total += 1
            new, changed = fix_line(src[ln - 1])
            if changed:
                print(f"[fix] {p.name}:{ln}: {src[ln - 1].strip()[:80]}")
                print(f"      → {new.strip()[:80]}")
                src[ln - 1] = new
                local += 1
            else:
                print(f"[skip] {p.name}:{ln}: {src[ln - 1].strip()[:90]}")
        if local and want:
            text = "".join(src)
            p.write_text(text, encoding="utf-8", newline="")
            ensure_import(p, text)
            touched += local
    print(f"\n扫了 {total} 行，改了 {touched} 行（write={want}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
