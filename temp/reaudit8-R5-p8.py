"""第 8 轮重审 R5 · 探针 P8：**独立**的整仓引用体检（比仓内判据更宽），
回答"F5-R7 这一批有没有留下/引入别的引用型缺陷"。

比仓内判据宽的地方：
  - 扫**整仓**（`agentflow/**` 的 .py/.md，排除 `temp/` 与 `draft/` 之外不算），不只 6 个文件；
  - 反引号里的私有符号名（含大写、含数字开头以外的形态）；
  - 反引号里的 `temp/...` 路径；另加**裸写**的 `temp/xxx.ext`（不带反引号）；
  - 显式把"全树只出现 1 次"的私有符号列为悬空。
"""
from __future__ import annotations

import os
import pathlib
import re

WS = pathlib.Path(r"D:\Incubator")
ROOT = WS / "agentflow"
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache"}

PRIV = re.compile(r"`(_[A-Za-z][A-Za-z0-9_]*)`")
TEMP_TICKED = re.compile(r"`(temp/[A-Za-z0-9_.\-]+)`")
TEMP_BARE = re.compile(r"(?<![`/\w])(temp/[A-Za-z0-9_.\-]*[A-Za-z0-9]\.(?:py|txt|json|md|tsv))")


def walk(root: pathlib.Path, exts: tuple[str, ...]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(exts):
                yield pathlib.Path(dirpath) / fn


def main() -> None:
    files = list(walk(ROOT, (".py", ".md")))
    print("[files] %d 个 .py/.md 在 %s 下" % (len(files), ROOT))
    corpus = {}
    for p in files:
        try:
            corpus[str(p)] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    dangling = []
    miss_ticked = []
    miss_bare = []
    n_priv = n_ticked = n_bare = 0
    for p in files:
        rel = p.relative_to(ROOT)
        t = corpus[str(p)]
        for tok in sorted(set(PRIV.findall(t))):
            n_priv += 1
            cnt = sum(x.count(tok) for x in corpus.values())
            if cnt <= 1:
                dangling.append("%s: `%s`（全树 %d 次）" % (rel, tok, cnt))
        for ref in sorted(set(TEMP_TICKED.findall(t))):
            n_ticked += 1
            if not (WS / ref).exists():
                miss_ticked.append("%s: `%s`" % (rel, ref))
        for ref in sorted(set(TEMP_BARE.findall(t))):
            n_bare += 1
            if not (WS / ref).exists():
                miss_bare.append("%s: %s" % (rel, ref))

    print("\n=== 悬空私有符号（全树仅出现 1 次）%d 条 ===" % len(dangling))
    for d in dangling:
        print("  " + d)
    print("\n=== `temp/...` 反引号引用缺失 %d / 扫到 %d ===" % (len(miss_ticked), n_ticked))
    for m in miss_ticked:
        print("  " + m)
    print("\n=== 裸写 temp/xxx.ext 引用缺失 %d / 扫到 %d ===" % (len(miss_bare), n_bare))
    for m in miss_bare[:40]:
        print("  " + m)
    print("\n[TOTALS] priv=%d ticked=%d bare=%d" % (n_priv, n_ticked, n_bare))


if __name__ == "__main__":
    main()
