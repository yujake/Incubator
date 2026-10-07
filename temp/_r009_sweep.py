"""扫**全仓**的 R009 命中（不再是"被 linter 盖住的那一条"），并把它们一次清干净。

## 为什么不能靠 linter 的输出找靶子

实测：清掉两条之后 linter 的 `error` 数从 2 变 1，**但浮出来的是另一个文件**
（`src/agentflow/gates.py:420`）—— 说明 linter 的 error 列表**在某个上限处截断了**，
"按 linter 报的那几条逐个清"会变成挤牙膏。**靶子必须自己去扫。**

## 安全边界（防止踩到在飞写者）

- 每个文件的 mtime 在 `--min-age`（默认 180 秒）之内就**跳过**（有人在写它）；
- 清理走 `temp/_r009_scrub.py`，它自带三道护栏（清完无残留 / 区间外逐字未动 /
  区间内除装饰外逐字相同）；
- 只扫 `src/**/*.py` 与 `tests/**/*.py`（R009 的判据面就是这两处；`scripts/` 与 `tools/`
  另有各自的登记口径，不在本轮）。

用法：`python D:\\Incubator\\temp\\_r009_sweep.py [--apply]`
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path(r"D:\Incubator\agentflow")
HERE = Path(r"D:\Incubator\temp")


def hits(path: Path) -> int:
    p = subprocess.run([sys.executable, str(HERE / "_r009_lines.py"), str(path)],
                       cwd=str(PROJ), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"hits=(\d+)", p.stdout or "")
    return int(m.group(1)) if m else -1


def main() -> int:
    apply_ = "--apply" in sys.argv
    min_age = 180.0
    rows = []
    for sub in ("src", "tests"):
        for f in sorted((PROJ / sub).rglob("*.py")):
            h = hits(f)
            if h > 0:
                age = time.time() - f.stat().st_mtime
                rows.append((f.relative_to(PROJ).as_posix(), h, age))
    print(f"全仓 R009 命中的文件：{len(rows)} 个")
    for rel, h, age in rows:
        print(f"  {rel:<56} {h:>4} 处   最近写入 {age:6.0f} 秒前")
    if not apply_:
        print("\n（只扫描）加 `--apply` 才会清；清的规则见 `_r009_scrub.py` 的三道护栏。")
        return 0
    todo = [rel for rel, _, age in rows if age > min_age]
    skip = [rel for rel, _, age in rows if age <= min_age]
    if skip:
        print(f"\n跳过（最近 {min_age:.0f} 秒内有写入，可能有别的批次在改）：{skip}")
    if not todo:
        print("没有可清的文件")
        return 0
    p = subprocess.run([sys.executable, str(HERE / "_r009_scrub.py"), *todo],
                       cwd=str(PROJ), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print((p.stdout or "") + (p.stderr or ""))
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
