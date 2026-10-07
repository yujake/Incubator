# -*- coding: utf-8 -*-
"""通用拆分器：把任意长函数按**段边界**逐字搬成 `_phase_N` / `_check_N` 函数。

T-5 用它拆了 `verify_all`（1175 行 → 30 行 + 12 个 `_check_*`）。这一版把它参数化
（`--file` / `--func` / `--boundaries` / `--prefix`），供 T-7 拆 `runflow.run_topic` 复用 ——
`draft/36` §5 说的"把『先快照、后搬移』的流程跑通，形成可复制的做法"就是指这个。

## 它算清的三件事（算法与 T-5 逐条相同，注释里记着八次踩坑）

1. **入参** = 组内"读了、但在本组第一次绑定它之前"的名字（组级判据，不是段级）；
2. **出参** = 从后往前传播"需要"（`need = (need - mine) | reads_before_bind(group)`）
   之后，本组绑定能满足的那些；
3. **模块级名字 / 内建名不进签名**（helper 是模块级函数，照样解析得到）。

另有三条硬约束：只搬移（组内源码逐字保留，只换位置）、顺序不变、
搬完必须过对应的"改前 = 改后"快照判据。

用法：
  python -B temp/_split_any.py --file src/agentflow/runflow.py --func run_topic \
      --boundaries 2,15,24,37,47,58 --prefix _phase_ --dry-run
  …（把 --dry-run 换成 --apply 就写回，会先备份到 temp/）
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(r"D:\Incubator\agentflow")
TEMP = pathlib.Path(r"D:\Incubator\temp")


def first_lines(node: ast.AST) -> tuple[dict[str, int], dict[str, int]]:
    """这一段里：每个名字**第一次被读** / **第一次被绑**的行号。

    `except X as e:` 的 `e` 在 AST 里是字符串（`handler.name`）而不是 `Name` 节点 ——
    T-5 的第七次踩坑就是漏了它（`e` 看起来"读了却没绑"，被当成入参 ⇒ `UnboundLocalError`）。
    """
    fr: dict[str, int] = {}
    fb: dict[str, int] = {}
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            (fr if isinstance(n.ctx, ast.Load) else fb).setdefault(n.id, n.lineno)
        elif isinstance(n, ast.ExceptHandler):
            if n.name:
                fb.setdefault(str(n.name), n.lineno)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                fb.setdefault(a.asname or a.name.split(".")[0], n.lineno)
    return fr, fb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="仓库根相对路径")
    ap.add_argument("--func", required=True)
    ap.add_argument("--boundaries", required=True, help="逗号分隔的段序号（首段之前留在编排层）")
    ap.add_argument("--prefix", default="_phase_")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    target = ROOT / args.file
    src = target.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == args.func), None)
    assert fn is not None, f"{args.file} 里没有 {args.func}"

    segs = []
    prev = fn.lineno
    for st in fn.body:
        s = st.lineno
        while s - 1 >= prev and lines[s - 2].lstrip().startswith("#"):
            s -= 1
        fr, fb = first_lines(st)
        segs.append({"start": s, "end": getattr(st, "end_lineno", st.lineno), "node": st,
                     "read": fr, "bind": fb})
        prev = getattr(st, "end_lineno", st.lineno)

    bounds = [int(x) for x in args.boundaries.split(",") if x.strip()]
    inline_upto = bounds[0]
    # 最后一段若是 `return …`，它留在编排层（T-5 的第八次踩坑：并进 helper 会让函数返回 None）
    end = len(segs) - 1 if isinstance(segs[-1]["node"], ast.Return) else len(segs)
    groups = [(bounds[i], bounds[i + 1] if i + 1 < len(bounds) else end)
              for i in range(len(bounds))]
    groups = [(lo, min(hi, end)) for lo, hi in groups if hi > lo]

    def reads_before_bind(lo: int, hi: int) -> set[str]:
        fr: dict[str, int] = {}
        fb: dict[str, int] = {}
        for s in segs[lo:hi]:
            for n, line in s["read"].items():
                fr[n] = min(fr.get(n, line), line)
            for n, line in s["bind"].items():
                fb[n] = min(fb.get(n, line), line)
        return {n for n, rl in fr.items() if n not in fb or rl < fb[n]}

    def binds_of(lo: int, hi: int) -> set[str]:
        out: set[str] = set()
        for s in segs[lo:hi]:
            out |= set(s["bind"])
        return out

    module_names: set[str] = set(dir(__builtins__)) if isinstance(__builtins__, dict) \
        else set(dir(__builtins__))
    import builtins as _bi

    module_names = set(dir(_bi))
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(top.name)
        elif isinstance(top, (ast.Import, ast.ImportFrom)):
            for a in top.names:
                module_names.add(a.asname or a.name.split(".")[0])
        else:
            module_names |= {n.id for n in ast.walk(top)
                             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    fn_args = ({a.arg for a in fn.args.posonlyargs} | {a.arg for a in fn.args.args}
               | {a.arg for a in fn.args.kwonlyargs} | {a.arg for a in fn.args.kwarg and [a] or []})
    base_avail = fn_args | module_names | binds_of(0, inline_upto)

    # 从后往前算：`demand` = "后面的组还需要哪些名字"。每算完一组，把这组的
    # **入参**并回 `demand`（而不只是"它绑不出来的那些"）—— 因为入参里可能有
    # **有条件的出参回填**（见下），那个值也得由更前面的组交出来。
    plan: list[dict] = []
    demand: set[str] = set()
    for k in range(len(groups) - 1, -1, -1):
        lo, hi = groups[k]
        mine = binds_of(lo, hi)
        bound_before = set(base_avail) | binds_of(0, lo)
        exports = sorted((demand & mine) - base_avail)
        # 出参的名字还必须**当入参传进来**：如果这个组只是**有条件地**绑定它
        # （典型：`if …: acquisition = …` 的 else 支不绑），那么没走那一支时，
        # 它要用的是**组外那个值**。T-7 第一次跑就是在这里栽的：
        # `_phase_2` 把 `acquisition = None` 绑好、`_phase_3` 只在 `else` 支里重新绑，
        # 于是 no-key 那一支跑到 `_phase_5` 时 `acquisition` 未绑定 ⇒
        # `UnboundLocalError: cannot access local variable 'acquisition'`。
        # （T-5 的 `verify_all` 没踩到，是因为它那 12 段的出参都是无条件绑定的。）
        params = sorted((reads_before_bind(lo, hi)
                         | (set(exports) & bound_before)) - module_names)
        plan.append({"idx": k + 1, "lo": lo, "hi": hi, "params": params, "exports": exports,
                     "lines": (segs[lo]["start"], segs[hi - 1]["end"])})
        demand = (demand - mine) | set(params)
    plan.reverse()

    print(f"{args.func}: {fn.lineno}–{fn.end_lineno}（{fn.end_lineno - fn.lineno + 1} 行）；"
          f"{len(segs)} 段 → {len(plan)} 组（前 {inline_upto} 段与 return 留在编排层）")
    for p in plan:
        n = p["lines"][1] - p["lines"][0] + 1
        print(f"  {args.prefix}{p['idx']} 段 {p['lo']:>2}–{p['hi'] - 1:<2} 行 "
              f"{p['lines'][0]:>5}–{p['lines'][1]:<5} ({n:>3} 行) 入参 {len(p['params'])}: {p['params']}")
        print(f"        出参 {len(p['exports'])}: {p['exports']}")
    if not args.apply:
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = TEMP / f"split-{args.func}-{stamp}.py.bak"
    shutil.copy2(target, backup)
    print(f"\n[备份] {backup}")

    head_src = "".join(lines[fn.lineno - 1:segs[inline_upto]["start"] - 1])
    tail_start = segs[-1]["start"] if isinstance(segs[-1]["node"], ast.Return) else fn.end_lineno + 1
    tail = "".join(lines[tail_start - 1:fn.end_lineno])
    helpers: list[str] = []
    calls: list[str] = []
    for p in plan:
        name = f"{args.prefix}{p['idx']}"
        params = ["rep"] if args.func == "verify_all" else []
        params += [x for x in p["params"]]
        sig = ", ".join(params)
        body = "".join(lines[segs[p["lo"]]["start"] - 1:segs[p["hi"] - 1]["end"]])
        ret = ("\n    return " + ", ".join(p["exports"]) + "\n") if p["exports"] else ""
        helpers.append(f"def {name}({sig}):\n"
                       f"    \"\"\"`{args.func}` 的第 {p['idx']} 段（行 {p['lines'][0]}–{p['lines'][1]}）。\n\n"
                       f"    由 `temp/_split_any.py` 逐字搬移而来：判据与行为一条没改，只是换了个位置。\n"
                       f"    入参 / 出参见脚本的 dry-run 输出。\n"
                       f"    \"\"\"\n{body}{ret}\n\n")
        call = f"    {name}({sig})\n"
        if p["exports"]:
            call = f"    {', '.join(p['exports'])} = {name}({sig})\n"
        calls.append(call)
    new_fn = head_src + "".join(calls) + tail
    target.write_text("".join(lines[:fn.lineno - 1]) + "\n\n".join(helpers) + new_fn
                      + "".join(lines[fn.end_lineno:]), encoding="utf-8", newline="")
    print(f"[ok] 写回 {target}（{len(plan)} 个 {args.prefix}* + 编排层）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
