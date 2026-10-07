"""算出判据真正要求的那一栏：`mentioned_only`，并与登记表 `_REF_KNOWN_MENTION_TOKENS` 双向差集。

判据 `tests/test_r5_orchestration_cost.py::test_the_quoted_references_in_comments_all_exist` 的
第二条断言逐字是：

    mentioned_only = sorted(
        tok for tok in res["ticked_tokens"]
        if res["symbol_counts"].get(tok, 0) <= 1 and tok not in res["dangling_tokens"]
    )
    assert mentioned_only == sorted(_REF_KNOWN_MENTION_TOKENS)

所以"要加/要删"必须按这一栏算 —— 我第一次拿 `dangling_tokens` 去比，**比错了栏**
（那一栏是"未登记的"，永远不可能等于整张表）。这个脚本按判据自己的公式重算。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(r"D:\Incubator\agentflow")
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import test_r5_orchestration_cost as T  # noqa: E402


def main() -> int:
    tree, ws_root = T._reference_scan_roots()
    res = T._scan_ticked_references(tree, ws_root)
    mentioned_only = sorted(
        tok for tok in res["ticked_tokens"]
        if res["symbol_counts"].get(tok, 0) <= 1 and tok not in res["dangling_tokens"]
    )
    registered = sorted(T._REF_KNOWN_MENTION_TOKENS)
    only_live = [t for t in mentioned_only if t not in registered]
    only_reg = [t for t in registered if t not in mentioned_only]
    print(f"mentioned_only（判据那一栏）共 {len(mentioned_only)} 条；登记表 {len(registered)} 条")
    print(f"\n实际里有、表里没有（要加，{len(only_live)} 条）：")
    for row in only_live:
        print("  + " + row)
    print(f"\n表里有、实际里没有（要删，{len(only_reg)} 条）：")
    for row in only_reg:
        print("  - " + row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
