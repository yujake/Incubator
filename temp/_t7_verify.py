# -*- coding: utf-8 -*-
"""T-7 的"只搬移"机器判据：`runflow.run_topic` 拆前 / 拆后的**代码行多重集**必须相同。

为什么还要这一条（黄金快照已经在管行为了）：
- 快照钉的是"可观察后果"，它**看不见**那些不影响产物的东西（比如一句被改写的注释、
  一个被顺手改掉的字面量、某个分支里没人跑到的代码）；
- 这一条钉的是**字面**：拆之前 `run_topic` 函数体里的每一行非空源码，拆之后必须
  一字不差地出现在 `run_topic` + `_phase_*` 里，且出现次数相同。

做法（不做任何智能推断，只做多重集比较）：
1. 拆前备份（`temp/split-run_topic-*.py.bak`）里 `run_topic` 的**函数体**所有语句的源码行；
2. 拆后 `runflow.py` 里 `run_topic` 与全部 `_phase_*` 的函数体语句源码行；
3. 各自按 `strip()` 后的非空行做 `Counter`，打印两个方向的差集。

**差集只允许是拆分器自己生成的那几行**（`def _phase_N(...):`、docstring 三行、
`return …`、编排层的调用/赋值行、空行）—— 脚本把差集逐条列出来，人看一眼就能判。
"""
from __future__ import annotations

import ast
import collections
import pathlib
import sys

ROOT = pathlib.Path(r"D:\Incubator\agentflow")
TEMP = pathlib.Path(r"D:\Incubator\temp")
NEW = ROOT / "src" / "agentflow" / "runflow.py"


def body_lines(path: pathlib.Path, names: set[str], *, prefix: str | None = None
               ) -> collections.Counter[str]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    out: collections.Counter[str] = collections.Counter()
    found = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name not in names and not (prefix and fn.name.startswith(prefix)):
            continue
        found.add(fn.name)
        for st in fn.body:
            for ln in lines[st.lineno - 1:st.end_lineno]:
                s = ln.strip()
                if s:
                    out[s] += 1
    missing = names - found
    assert not missing, f"{path.name} 里没有这些函数：{sorted(missing)}"
    return out


def main() -> int:
    baks = sorted(TEMP.glob("split-run_topic-*.py.bak"))
    if not baks:
        print("[unknown] temp/ 里没有 split-run_topic-*.py.bak —— 没查成，不是查过了")
        return 2
    bak = baks[-1]
    before = body_lines(bak, {"run_topic"})
    after = body_lines(NEW, {"run_topic"}, prefix="_phase_")
    gone = before - after          # 拆前有、拆后没有
    added = after - before         # 拆后有、拆前没有
    print(f"拆前（{bak.name}）非空代码行 {sum(before.values())} 行 / 去重 {len(before)} 种")
    print(f"拆后（runflow.py）非空代码行 {sum(after.values())} 行 / 去重 {len(after)} 种")
    print(f"\n[少了的行] {sum(gone.values())} 条：")
    for ln, n in sorted(gone.items()):
        print(f"  x{n}  {ln[:120]}")
    print(f"\n[多出来的行] {sum(added.values())} 条：")
    for ln, n in sorted(added.items()):
        print(f"  x{n}  {ln[:120]}")
    print("\n判据：『少了的行』必须为 0；『多出来的行』只允许是拆分器生成的"
          "（def / docstring / return / 调用行）。")
    return 0 if not gone else 1


if __name__ == "__main__":
    sys.exit(main())
