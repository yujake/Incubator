# -*- coding: utf-8 -*-
"""证明三条主线**文件级零交**：两两不相交 + 并集覆盖 `required_all`。

用法：`python -B temp/_check_line_ownership.py`
读 `temp/_web_lines.json`（分工表；glob 只支持 `**` 与 `*`，用于目录级归属）。

三档读数：
  ① 两两相交的文件（应当为空）—— 判据：**空才是零交**；
  ② `required_all` 里**没有被任何线认领**的文件（应当为空）；
  ③ `required_all` 里被**多条线**认领的文件（= ①的另一种说法，单独列出来给人看）。
"""

from __future__ import annotations

import fnmatch
import itertools
import json
import pathlib
import sys

ROOT = pathlib.Path(r"D:\Incubator")
TABLE = ROOT / "temp" / "_web_lines.json"
sys.stdout.reconfigure(encoding="utf-8")


def owned(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
        if pat.endswith("/**") and (path == pat[:-3] or path.startswith(pat[:-2])):
            return True
    return False


def main() -> int:
    doc = json.loads(TABLE.read_text(encoding="utf-8"))
    lines: dict[str, list[str]] = doc["lines"]
    required: list[str] = doc["required_all"]

    print("  = 三条主线的 glob 数 =")
    for name, pats in lines.items():
        print(f"    {name}: {len(pats)} 条 glob")

    # ① 两两相交（对 required_all 的每个文件，看它被几条线认领）
    multi: list[tuple[str, list[str]]] = []
    none: list[str] = []
    for f in required:
        owners = [name for name, pats in lines.items() if owned(f, pats)]
        if not owners:
            none.append(f)
        elif len(owners) > 1:
            multi.append((f, owners))

    print("  = ① 被多条线认领的文件（应为 0） =")
    for f, owners in multi:
        print(f"    !! {f}  ←  {owners}")
    print(f"    条数：{len(multi)}")

    print("  = ② required_all 里没人认领的文件（应为 0） =")
    for f in none:
        print(f"    !! {f}")
    print(f"    条数：{len(none)}")

    # ③ 覆盖：并集是否等于 required_all
    covered = {f for f in required if any(owned(f, pats) for pats in lines.values())}
    missing = sorted(set(required) - covered)
    print(f"  = ③ 覆盖率：{len(covered)}/{len(required)}；缺 {len(missing)} =")
    for f in missing:
        print(f"    !! {f}")

    ok = not multi and not none and not missing
    print()
    print("结论：" + ("三条主线文件级零交、且覆盖全部计划文件 ✓" if ok else "**不满足零交或漏文件，见上面 !!**"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
