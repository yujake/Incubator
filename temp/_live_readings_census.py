"""仓级"活读数"普查：把 `G-32` 漏网的**定值型数字**一次找全（只读，候选清单，不是 finding）。

为什么要有它：`G3` 按 `G-32` 改过 22 组，但第 10 轮 `R6` 仍然**靠逐批撞见**又抓到 4 处
（`tools/release_all.py:385` 的"79 个文件"、`tools/vocab_census.py:65` 的"8 个词表"、
`DEVELOPMENT.md:208-211` 示范段、`tests/test_release_check_noai.py:58` 的"18 个/17 条"）。
⇒ 逐批撞见是碰运气；本脚本把"哪些行写了定值、且没有任何历史/观测标记"一次列出来。

判定口径（与仓内既有约定对齐）：
  · 候选 = 行里出现"定值型读数"的形态：
      `<n> passed` / `<n> 个(文件|测试|词表|条|组|处|项|行)` /
      `error <n> / warning <n> / info <n>` / `<n> 条…reviewer` / `<n> 个 pytest`
  · **豁免** = 同一行里出现 `_HISTORICAL_MARKERS`（历史/当时/原写/原值/旧版/改前/S1/S2）
             或观测标记（当次/观测）或命令标记（`python ` / `pytest ` / 反引号里的模块路径）
  · 只扫 `.py` 与 `.md`；跳过缓存与 `.git`；**只报候选，不下结论**（判它是不是缺陷要人/审计者）。

用法：`python D:\\Incubator\\temp\\_live_readings_census.py [--limit 40] [--tsv]`
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(r"D:\Incubator\agentflow")
OUT = pathlib.Path(r"D:\Incubator\temp\live-readings-census.tsv")
SKIP = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "node_modules"}

HIST = ("S1", "S2", "当时", "历史", "原写", "原值", "旧版", "改前", "当次", "观测")
#: 命令标记（出现即豁免）。**刻意不写裸词 `pytest`**：`tools/release_all.py:385` 那句
#: 「79 个文件各起一个 pytest 进程」是**读数**而不是命令，第一版因为这一条把它漏掉了（假阴性）。
CMD = ("python ", "python -m", "Select-String", "Get-ChildItem", "git ", "⇒", "->")

PATTERNS = [
    ("passed", re.compile(r"\b\d{3,}\s+passed\b")),
    ("个数量", re.compile(r"\d+\s*个\s*(?:文件|测试|词表|pytest|用例|test_\*)")),
    ("条数量", re.compile(r"\d+\s*条\s*(?:各|reviewer|entry|条目|断言)")),
    ("lint三元", re.compile(r"error\s*\d+\s*/\s*warning\s*\d+\s*/\s*info\s*\d+")),
    ("文件数", re.compile(r"\b\d{2,}\s*(?:个|条)\b(?=[^。\n]{0,20}(?:文件|测试|词表))")),
]


def files() -> list[pathlib.Path]:
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".py", ".md"):
            continue
        if any(part in SKIP for part in p.parts):
            continue
        out.append(p)
    return out


def tier(rel: str, line: str) -> str:
    """分档：**T1 = 要治的**（代码注释/docstring 或规范文档里自称"今天/当前"的行）；T2 = 历史叙述候选。

    为什么要分：第一版把 `docs/PROPOSALS.md` 的 49 行全报了 —— 但那份文件**本身就是**
    "过去测得什么"的登记册（`G-3` 的提案账），里面的定值是**历史事实**，不是"当前值"。
    照第一版去"治"，会把历史记录改成相对表述 ⇒ **篡改证据**。
    """
    is_code = rel.endswith(".py")
    code_comment = is_code and (line.lstrip().startswith("#") or line.lstrip().startswith('"')
                                or line.lstrip().startswith("'"))
    normative = rel in ("DEVELOPMENT.md", "README.md") and any(k in line for k in ("今天", "当前", "现在是", "当次"))
    if code_comment or normative:
        return "T1"
    return "T2"


def main() -> int:
    limit = 40
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    tsv = "--tsv" in sys.argv
    t1only = "--t1" in sys.argv

    rows: list[tuple[str, int, str, str, str, str]] = []
    for p in files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(ROOT))
        for i, line in enumerate(text.splitlines(), 1):
            hits = [name for name, rx in PATTERNS if rx.search(line)]
            if not hits:
                continue
            if any(m in line for m in HIST) or any(c in line for c in CMD):
                continue
            rows.append((rel, i, ",".join(hits), line.strip()[:220], "", tier(rel, line)))

    t1 = [r for r in rows if r[5] == "T1"]
    by_file: dict[str, int] = {}
    for rel, *_ in rows:
        by_file[rel] = by_file.get(rel, 0) + 1

    print(f"扫描 {len(files())} 个 .py/.md；候选 **{len(rows)}** 行（T1 要治的 **{len(t1)}** / T2 历史叙述候选 {len(rows)-len(t1)}）")
    print("\n=== 按文件（候选行数降序，前 25）===")
    for rel, n in sorted(by_file.items(), key=lambda kv: -kv[1])[:25]:
        n1 = sum(1 for r in rows if r[0] == rel and r[5] == "T1")
        print(f"  {n:>4}  (T1 {n1:>2})  {rel}")

    show = t1 if t1only else rows
    print(f"\n=== {'T1 全部' if t1only else '候选'}（前 {limit}）===")
    for rel, i, hits, line, _, t in show[:limit]:
        print(f"  [{t}] {rel}:{i}  [{hits}]  {line}")

    if tsv:
        OUT.write_text("档\t文件\t行\t命中形态\t行内容\n" + "\n".join(
            f"{f}\t{a}\t{b}\t{c}\t{d}" for a, b, c, d, _, f in rows) + "\n", encoding="utf-8", newline="\n")
        print(f"\n落盘 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
