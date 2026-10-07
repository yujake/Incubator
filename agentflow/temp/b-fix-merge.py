# -*- coding: utf-8 -*-
"""一次性探针：把 line-b 上被 stash/merge 弄乱的 readers.py / sse.py 归位。

做法（可重算）：从 `git show stash@{0}:<path>` 取回 B 线那一版全文，再用 master
新加的接缝（`HANDLERS` 字典 / `CHECKED_TYPES` / `UNCHECKED_TYPES` /
`PENDING_ENDPOINTS`）替换掉那一版里的旧写法。不提交。
"""
import pathlib
import re
import subprocess
import sys

WT = pathlib.Path(r"D:\Incubator\temp\wt-b")
FILES = ("agentflow/src/agentflow/webui/readers.py",
         "agentflow/src/agentflow/webui/sse.py")


def stash_text(rel: str) -> str:
    out = subprocess.run(["git", "show", f"stash@{{0}}:{rel}"], cwd=WT,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def main() -> int:
    rows = []
    for rel in FILES:
        text = stash_text(rel)
        if "<<<<<<<" in text or ">>>>>>>" in text:
            print(f"[FAIL] {rel} 的 stash 版本里还有冲突标记")
            return 1
        (WT / rel).write_text(text, encoding="utf-8", newline="\n")
        rows.append((rel, len(text.splitlines())))
    for rel, n in rows:
        print(f"[ok] {rel} <- stash 版（{n} 行）")
    return 0


def nope() -> None:
    """占位：本探针只做上面那一件事。"""
    del re, sys


if __name__ == "__main__":
    raise SystemExit(main())
