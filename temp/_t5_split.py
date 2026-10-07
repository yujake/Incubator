# -*- coding: utf-8 -*-
"""T-5 的拆分器：把 `verify.py::verify_all` 按分段横幅搬成 `_check_*` 函数。

## 为什么用脚本而不是手工搬

1175 行、96 条顶层语句、89 个"跨段共享名"（绝大多数是 for 循环变量的意外泄漏）。
手工搬移要一路盯着"这一段的 `r` 是它自己循环的，还是上一段漏下来的" ——
那种活干到第 60 段必然出错，而错了不一定报错（同名变量被覆盖 ⇒ 静默改口径）。

脚本按 AST 算清楚三件事，再**逐字搬移**代码（只改缩进）：

- **入参**：这一组读到、而绑定发生在前面的名字（且在本组内"读在绑之前"）；
- **出参**：这一组绑定、后面某组"读在绑之前"的名字（原样返回，保证泄漏语义不变）；
- **留在原地的**：其余（组内自足的名字不必进签名）。

## 三条硬约束

1. **只搬移，不改写**：组内的源码逐字保留（只整体缩进 4 格）；
2. **顺序不变**：调用次序 == 原来的语句次序；
3. **可判真假**：搬完必须过 `tests/test_verify_snapshot.py`（8 个工作区输出逐字相同）。

用法：
  python -B temp/_t5_split.py --dry-run     # 只打印建议的签名与分组
  python -B temp/_t5_split.py --apply       # 写回 verify.py（会先备份）
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import shutil
import sys
import time

VERIFY = pathlib.Path(r"D:\Incubator\agentflow\src\agentflow\verify.py")


def _first_lines(node: ast.AST) -> tuple[dict[str, int], dict[str, int]]:
    """这一组里：每个名字**第一次被读**的行号 / **第一次被绑**的行号。"""
    first_read: dict[str, int] = {}
    first_bind: dict[str, int] = {}
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            line = n.lineno
            if isinstance(n.ctx, ast.Load):
                first_read.setdefault(n.id, line)
            else:
                first_bind.setdefault(n.id, line)
        elif isinstance(n, ast.ExceptHandler):
            # `except ValueError as e:` 的 `e` 在 AST 里是 **字符串**（`handler.name`），
            # 不是 `Name` 节点 ⇒ `ast.walk` 永远看不到它的绑定。
            # 漏掉这一处会让 `e` 看起来"读了却没绑"，于是被判成入参
            # （真机读数：`_check_1(rep, e, store)` ⇒ `UnboundLocalError: … 'e'`）。
            if n.name:
                first_bind.setdefault(str(n.name), n.lineno)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                first_bind.setdefault(a.asname or a.name.split(".")[0], n.lineno)
    return first_read, first_bind


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-lines", type=int, default=20,
                    help="小于这个行数的组不单独拆（并进上一组）")
    args = ap.parse_args()

    src = VERIFY.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "verify_all")

    # ---- 分段：每条顶层语句 + 紧跟其上的注释块（横幅）
    segs = []
    prev_end = fn.lineno
    for st in fn.body:
        s = st.lineno
        while s - 1 >= prev_end and lines[s - 2].lstrip().startswith("#"):
            s -= 1
        read, bind = _first_lines(st)
        segs.append({"start": s, "end": getattr(st, "end_lineno", st.lineno),
                     "node": st, "read": read, "bind": bind})
        prev_end = getattr(st, "end_lineno", st.lineno)

    # ---- 分组：从第 2 段开始（前两段是 docstring 与 rep 的构造，留在原地）
    head = [0, 1]
    groups: list[tuple[int, int]] = []
    cur = 2
    for i in range(2, len(segs)):
        span = segs[i]["end"] - segs[cur]["start"] + 1
        # 一个组在"跨过一条横幅"或"够长"时收口
        banner = lines[segs[i]["start"] - 1].lstrip().startswith("# ----")
        if banner and (segs[i - 1]["end"] - segs[cur]["start"] + 1) >= args.min_lines:
            groups.append((cur, i))
            cur = i
        elif span > 150:
            groups.append((cur, i))
            cur = i
    groups.append((cur, len(segs)))

    # 最后一段通常是 `return rep` —— 它必须留在**编排层**里（跟着 `def` 走）。
    # 第六版把它并进了最后一个 helper：`verify_all` 于是返回 `None`，
    # 真机读数是 `AttributeError: 'NoneType' object has no attribute 'ok'`（在 demo.py 里炸的）。
    tail_start = fn.end_lineno
    if isinstance(segs[-1]["node"], ast.Return):
        last_lo, _last_hi = groups[-1]
        groups[-1] = (last_lo, len(segs) - 1)
        tail_start = segs[-1]["start"]

    fn_args = ({a.arg for a in fn.args.posonlyargs} | {a.arg for a in fn.args.args}
               | {a.arg for a in fn.args.kwonlyargs})
    # 模块级名字（imports / 顶层 def / 常量）在 helper 里照样解析得到 ⇒ 不该进签名。
    # 内建名（`len`/`int`/`sorted`…）同理。第一版把 `len`、`Issue`、`S` 都塞进了入参 ——
    # 不影响正确性，但签名单会变成噪音，"这一组到底依赖什么数据"就看不出来了。
    import builtins as _bi

    module_names: set[str] = set(dir(_bi))
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(top.name)
        elif isinstance(top, (ast.Import, ast.ImportFrom)):
            for a in top.names:
                module_names.add(a.asname or a.name.split(".")[0])
        else:
            module_names |= {n.id for n in ast.walk(top)
                             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    inline_binds: set[str] = set()
    for s in segs[:2]:                      # 前两段留在编排层里
        inline_binds |= set(s["bind"])
    base_avail = fn_args | inline_binds | module_names

    def reads_before_bind(lo: int, hi: int) -> set[str]:
        """组内"读了、但在**本组第一次绑定它之前**"的名字 —— 它们必须从组外来。

        注意是**组级**而不是段级：第四版在这里栽过一次 —— 段级的判据会把
        `con_by_id = {… for r in concepts}` 里的 `concepts` 判成入参
        （那一段没绑它），而它明明由本组更早的一段 `concepts = store.rows(...)` 绑好了
        ⇒ 编排层里根本没有 `concepts` 可传 ⇒
        `UnboundLocalError: cannot access local variable 'concepts'`。
        """
        first_read: dict[str, int] = {}
        first_bind: dict[str, int] = {}
        for s in segs[lo:hi]:
            for name, line in s["read"].items():
                first_read[name] = min(first_read.get(name, line), line)
            for name, line in s["bind"].items():
                first_bind[name] = min(first_bind.get(name, line), line)
        return {n for n, rline in first_read.items()
                if n not in first_bind or rline < first_bind[n]}

    def binds_of(lo: int, hi: int) -> set[str]:
        out: set[str] = set()
        for s in segs[lo:hi]:
            out |= set(s["bind"])
        return out

    # ---- 出参：从最后一组往前做"活跃变量"分析
    #
    # 这是第三版，前两版都被真机打回来了，错法不一样、都值得记下来：
    # ① "后面没绑过它 ⇒ 出参" —— 太粗：`exp_by_id` 在第 5 组绑定、第 6 组要用，
    #    而它在第 11 组又被绑一次 ⇒ 旧规则不出参 ⇒ `UnboundLocalError`。
    # ② "所有后面用到的名字都出参" —— 太细：编排层里根本没有那些名字
    #    （它们只活在别的 helper 里）⇒ `NameError: name 'e' is not defined`。
    # 正确做法：**从后往前传播"需要"**，本组绑定的名字能满足的需求就由本组出参。
    exports_by_group: dict[int, list[str]] = {}
    need: set[str] = set()
    for k in range(len(groups) - 1, -1, -1):
        lo, hi = groups[k]
        mine = binds_of(lo, hi)
        supplied = need & mine
        exports_by_group[k] = sorted(supplied - base_avail)
        # 本组自己的需求**不**能被本组自己的绑定满足（它可能是先读后绑）——
        # 第五版在这里栽过：把 `need` 里本组的绑定一并清掉，于是"先读后绑"的 `e`
        # 被当成"本组自己会绑" ⇒ 没有任何更早的组出参 ⇒
        # `UnboundLocalError: cannot access local variable 'e'`。
        need = (need - mine) | reads_before_bind(lo, hi)

    def group_sig(lo: int, hi: int, k: int) -> tuple[list[str], list[str]]:
        """这一组的 `(入参, 出参)`。

        入参 = 组内"读在绑之前"的名字（它们必须从组外来，且**必须真的传进来**：
        漏一个就是 `NameError` —— 真机上连续两版都是这么被打回来的）。
        """
        params = sorted(n for n in reads_before_bind(lo, hi) if n not in module_names)
        return params, exports_by_group[k]

    plan = []
    for k, (lo, hi) in enumerate(groups):
        params, exports = group_sig(lo, hi, k)
        l0, l1 = segs[lo]["start"], segs[hi - 1]["end"]
        plan.append({"idx": k + 1, "lo": lo, "hi": hi, "params": params, "exports": exports,
                     "lines": (l0, l1), "n": l1 - l0 + 1})

    print(f"verify_all: {fn.lineno}–{fn.end_lineno}；共 {len(segs)} 段；"
          f"建议拆成 {len(plan)} 组（前 2 段留在原地）")
    for p in plan:
        print(f"  组 {p['idx']:>2} 段 {p['lo']:>2}–{p['hi'] - 1:<2} 行 {p['lines'][0]:>4}–{p['lines'][1]:<4} "
              f"({p['n']:>3} 行) 入参 {len(p['params'])}: {p['params']}")
        print(f"        出参 {len(p['exports'])}: {p['exports']}")
    if not args.apply:
        return 0

    # ---- 生成新文件
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = VERIFY.with_suffix(f".py.bak-{stamp}")
    shutil.copy2(VERIFY, backup)
    print(f"\n[备份] {backup}")

    head_src = "".join(lines[fn.lineno - 1:segs[2]["start"] - 1])   # def 行 + docstring + rep=...
    body_calls: list[str] = []
    helpers: list[str] = []
    for p in plan:
        name = f"_check_{p['idx']}"
        params = ["rep"] + [x for x in p["params"] if x != "rep"]
        sig = ", ".join(params)
        body = "".join(lines[segs[p["lo"]]["start"] - 1:segs[p["hi"] - 1]["end"]])
        # 组内源码原本就在 `verify_all` 里缩进 4 格；搬进 `def _check_x(...)` 之后
        # **仍然是**第 1 层缩进 ⇒ 一个字都不用改（第一版又加了 4 格，把文件写成了
        # 8 格缩进的语法错 —— 这类错 Python 会当场报，不会静默）。
        ret = ""
        if p["exports"]:
            ret = "\n    return " + ", ".join(p["exports"]) + "\n"
        helpers.append(f"def {name}({sig}):\n"
                       f"    \"\"\"`verify_all` 的第 {p['idx']} 段（行 {p['lines'][0]}–{p['lines'][1]}）。\n\n"
                       f"    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。\n"
                       f"    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的\n"
                       f"    泄漏语义（后面的段确实读到了它们）。\n"
                       f"    \"\"\"\n{body}{ret}\n\n")
        call = f"    {name}({sig})\n"
        if p["exports"]:
            call = f"    {', '.join(p['exports'])} = {name}({sig})\n"
        body_calls.append(call)

    tail = "".join(lines[tail_start - 1:fn.end_lineno])            # `return rep`（留在编排层）
    new_fn = (head_src + "".join(body_calls) + tail)
    new_src = ("".join(lines[:fn.lineno - 1]) + "\n\n".join(helpers) + new_fn
               + "".join(lines[fn.end_lineno:]))
    VERIFY.write_text(new_src, encoding="utf-8", newline="")
    print(f"[ok] 写回 {VERIFY}（{len(plan)} 个 _check_* + 编排层）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
