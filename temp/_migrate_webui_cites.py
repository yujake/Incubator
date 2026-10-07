"""把 draft 里对**旧单文件** `webui.py:NNN` 的引用迁到拆包后的 `webui/*.py:NNN`。

为什么需要它：W0 把 `src/agentflow/webui.py`（1268 行）拆成了 `webui/` 包里的九个文件
（`__init__ / __main__ / state / views / writes / routes / server / readers / sse`）。
draft/73–79 里大量按旧文件写死行号的引用于是全部失效 —— 自审器把它们如实报成"文件不存在"
（一次 72 条），这是**正确的报警**，但光报警没有出口。

这个脚本给的出口是**机械可验的**：旧行号那一行的**原文**从历史提交里取出来
（默认 `65746a5`，即拆包前的 master），再在拆包后的九个文件里找**同一行原文**
（strip 后逐字相等）：
- 只在**一个**新文件里出现 ⇒ 用新坐标替换（这条引用被迁移，且仍然可核）；
- 在多个/零个里出现 ⇒ **不猜**，打进"要人看"的清单，由人决定（宁可留着报警，不许猜错）。

用法：
    python -B temp/_migrate_webui_cites.py            # 只报告（dry-run）
    python -B temp/_migrate_webui_cites.py --write    # 落盘替换（会打印逐条迁移）
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(r"D:\Incubator")
BASE = "65746a5"  # 拆包前的 master（`webui.py` 还在的那个点）
OLD_REL = "agentflow/src/agentflow/webui.py"
PKG = REPO / "agentflow" / "src" / "agentflow" / "webui"
DRAFTS = [p for p in sorted((REPO / "draft").glob("7*.md"))]

CITE = re.compile(r"webui\.py:(\d+)")


def old_lines() -> list[str]:
    proc = subprocess.run(["git", "show", f"{BASE}:{OLD_REL}"], cwd=str(REPO),
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(f"取不到历史文件：{proc.stderr[:300]}")
    return proc.stdout.splitlines()


def new_index() -> dict[str, list[str]]:
    """拆包后每个文件的行表（`相对路径 -> 行表`）。"""
    out: dict[str, list[str]] = {}
    for path in sorted(PKG.glob("*.py")):
        out[path.name] = path.read_text(encoding="utf-8").splitlines()
    return out


def locate(needle: str, index: dict[str, list[str]]) -> list[tuple[str, int]]:
    """找 `needle` 落在哪些（文件, 行号）上（strip 后逐字相等）。"""
    hits: list[tuple[str, int]] = []
    want = needle.strip()
    if not want:
        return hits
    for name, lines in index.items():
        for n, line in enumerate(lines, 1):
            if line.strip() == want:
                hits.append((name, n))
    return hits


def main() -> int:
    write = "--write" in sys.argv
    olds = old_lines()
    index = new_index()
    print(f"旧文件 {OLD_REL}@{BASE}：{len(olds)} 行；拆包后 {len(index)} 个文件")
    migrated: list[tuple[str, str, str]] = []
    manual: list[tuple[str, str, str]] = []
    for doc in DRAFTS:
        text = doc.read_text(encoding="utf-8")
        if "webui.py:" not in text:
            continue
        def _sub(m: re.Match[str]) -> str:
            num = int(m.group(1))
            if not (1 <= num <= len(olds)):
                manual.append((doc.name, m.group(0), f"旧文件只有 {len(olds)} 行"))
                return m.group(0)
            hits = locate(olds[num - 1], index)
            if len(hits) == 1:
                name, line = hits[0]
                new = f"webui/{name}:{line}"
                migrated.append((doc.name, m.group(0), new))
                return new
            why = "没有同一行原文" if not hits else f"有 {len(hits)} 处同文：{hits}"
            manual.append((doc.name, m.group(0), why))
            return m.group(0)
        new_text = CITE.sub(_sub, text)
        if write and new_text != text:
            doc.write_text(new_text, encoding="utf-8", newline="")
    print(f"\n可机械迁移：{len(migrated)} 处")
    for doc, old, new in migrated:
        print(f"  {doc}: {old} -> {new}")
    print(f"\n要人看：{len(manual)} 处（**不猜**，留在原文里继续报红）")
    for doc, old, why in manual:
        print(f"  {doc}: {old} —— {why}")
    if not write:
        print("\n（dry-run；加 --write 才落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
