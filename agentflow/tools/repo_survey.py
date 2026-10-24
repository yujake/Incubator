"""仓库体量巡检（只读）：把这棵树"有多大、哪里在长、注释够不够"量成数。

## 为什么要有它

清洁审计要问的不是"有没有坏味道"，而是"体量在不在变坏"。这两件事不一样：
坏味道能靠读代码看出来，体量只能靠量。所以这个脚本一条判据都不下 ——
它只负责把下面五组数算出来，判断留给 `tests/test_repo_survey_does_not_get_worse.py`
（软判据：现在不许比基线更差）与人的眼睛。

## 只读纪律（本脚本的契约）

不写盘、不改代码、不建目录、不联网、不 import `agentflow`。
它只做两件事：`Path.read_text` 与 `ast.parse`。因此它可以在任何一棵树上跑，
包括"别人正在施工"的那一棵 —— 跑它不会留下任何痕迹，也不会与别人抢锁。

## 五组读数与各自的口径（每个数都能复跑）

1. 扫描面：`src/agentflow/**/*.py` 与 `tests/**/*.py` 的文件数、总行数。
   行数用 `splitlines()` 的条数（末尾无换行不多算一行）。
2. 大文件：`>800` / `>1500` / `>3000` 行的 src 文件数与清单（各取前 N，默认 10）。
3. 长定义：`def` 与 `class` 的源码跨度（`end_lineno - lineno + 1`）`>200` /
   `>300` / `>500` 的个数与前 N。函数与类分开给，也合并给：
   "函数 >200 有 63 个"与"def/class 合计 >200 有 105 个"是两个都成立的事实，
   合成一个数就会在两个口径之间来回漂（本项目最贵的那类缺陷）。
4. 密度：docstring 行数 + 纯注释行数，各除以"扫描到的物理行数"再乘 100。
   分母是物理行（不是语句数、不是非空行）—— 换一个分母这个数就换一个意思，
   所以分母写死在这里，并由判据的基线钉住它的量级。
5. 重复 docstring 段：把每段 docstring 按空行切成段（段内逐行 `strip()` 后用换行连接），
   长度 `>= 80` 字符的段里，在两个及以上不同文件中逐字出现的那些。
   计的是"这样的段有几个"，不是"重复了多少次"。

## 退出码（三态）

`0` = 量到了（读数可用）；`2` = 没量成（扫描面里 0 个源文件 / 根目录不存在）。
"没扫到"与"扫到了、都很干净"必须是两个不同的结果 —— 把前者折成后者，
这个脚本就会在根路径写错时安静地报告一棵 0 行的树。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator

#: 扫描面（相对仓库根）。判据与文档引用的都是这两个相对路径。
SRC_REL = Path("src") / "agentflow"
TESTS_REL = Path("tests")

#: 大文件的三档阈值（严格大于）。
BIG_THRESHOLDS: tuple[int, ...] = (800, 1500, 3000)

#: 长定义的三档阈值（严格大于，按源码跨度算）。
LONG_THRESHOLDS: tuple[int, ...] = (200, 300, 500)

#: 重复 docstring 段的最小字符数（按段算，段内已 `strip()`）。
DUP_SEGMENT_MIN_CHARS = 80

#: 清单默认取前几。
DEFAULT_TOP = 10


def iter_py(base: Path) -> Iterator[Path]:
    """`base` 下全部 `.py` 文件（升序、跳过 `__pycache__` 与隐藏目录）。"""
    if not base.is_dir():
        return
    for p in sorted(base.rglob("*.py")):
        parts = p.relative_to(base).parts
        if any(part.startswith(".") or part == "__pycache__" for part in parts):
            continue
        if p.is_file():
            yield p


def count_lines(path: Path) -> int:
    """文件行数（`splitlines()` 的条数）。读不出来时抛 —— 读不到不许折成 0。"""
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _rel(path: Path, root: Path) -> str:
    """仓库根相对路径，统一用 `/` 分隔（Windows 与 POSIX 的读数因此可比）。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _docstring_segments(tree: ast.AST) -> list[str]:
    """一棵模块语法树里全部 docstring 的"段"（按空行切，段内逐行 strip 后拼回）。

    为什么按段而不是按整段 docstring：整段 docstring 的重复几乎只发生在
    "复制粘贴了整个模块头"，而真正会漂的是段 —— 一段说明被抄到第二个文件里、
    改了一边忘了另一边，那一段就是负债。按段计才能看见它。
    """
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        cur: list[str] = []
        for line in doc.splitlines():
            if line.strip():
                cur.append(line.strip())
            elif cur:
                out.append("\n".join(cur))
                cur = []
        if cur:
            out.append("\n".join(cur))
    return out


def docstring_lines(tree: ast.AST) -> int:
    """语法树里全部 docstring 占用的物理行数（按 `lineno..end_lineno` 的跨度算）。

    为什么按跨度而不是按 `splitlines()` 的条数：密度那一组数的分母是物理行，
    分子也必须是物理行 —— 同一段 docstring 里的空行照样占一行，把它漏掉，
    "每 100 行里有多少行在解释"这个数就偏小，而偏小的数永远不会被发现。
    """
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            end = getattr(first, "end_lineno", None) or first.lineno
            total += end - first.lineno + 1
    return total


def survey(
    root: Path | str = ".",
    *,
    src_rel: Path | str = SRC_REL,
    tests_rel: Path | str = TESTS_REL,
    top: int = DEFAULT_TOP,
) -> dict:
    """量一遍并返回一个纯数据字典（可 `json.dumps`，不含路径对象）。

    `src_rel` / `tests_rel` 是参数而不是常量：判据要能把"扫描面"打桩成空目录，
    以此证明"0 个文件"不会被读成"都很干净"（反真空）。生产调用一律用默认值。
    """
    root = Path(root).resolve()
    src_base = root / Path(src_rel)
    tests_base = root / Path(tests_rel)

    src_files = list(iter_py(src_base))
    tests_files = list(iter_py(tests_base))
    if not src_files:
        return {
            "root": str(root),
            "src_rel": str(src_rel),
            "tests_rel": str(tests_rel),
            "scanned_ok": False,
            "vacuum_reason": (
                f"扫描面 {root / Path(src_rel)} 下一个 .py 文件都没有 ⇒ 没扫到就是没查成，"
                "这一份读数不可用（根写错了不能被读成'这棵树很小'）"
            ),
            "scanned": {"src_files": 0, "tests_files": len(tests_files)},
        }

    src_lines = {p: count_lines(p) for p in src_files}
    tests_lines = {p: count_lines(p) for p in tests_files}

    # ---- 2. 大文件 ----
    big_counts: dict[str, int] = {}
    big_lists: dict[str, list[dict]] = {}
    for th in BIG_THRESHOLDS:
        rows = [
            {"path": _rel(p, root), "lines": n}
            for p, n in sorted(src_lines.items(), key=lambda kv: (-kv[1], str(kv[0])))
            if n > th
        ]
        big_counts[f"gt{th}"] = len(rows)
        big_lists[f"gt{th}"] = rows[: max(top, 0)]

    # ---- 3. 长定义（函数与类分开给，也合并给） ----
    rows: list[dict] = []
    bad_files: list[str] = []
    for p in src_files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            bad_files.append(_rel(p, root))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            span = (getattr(node, "end_lineno", None) or node.lineno) - node.lineno + 1
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            rows.append({
                "file": _rel(p, root), "line": node.lineno, "name": node.name,
                "kind": kind, "lines": span,
            })
    long_counts: dict[str, int] = {}
    long_lists: dict[str, list[dict]] = {}
    for th in LONG_THRESHOLDS:
        hits = [r for r in rows if r["lines"] > th]
        long_counts[f"function_gt{th}"] = sum(1 for r in hits if r["kind"] == "function")
        long_counts[f"class_gt{th}"] = sum(1 for r in hits if r["kind"] == "class")
        long_counts[f"any_gt{th}"] = len(hits)
        long_lists[f"gt{th}"] = sorted(
            hits, key=lambda r: (-r["lines"], r["file"], r["line"]))[: max(top, 0)]

    # ---- 4. 密度 ----
    doc_lines = 0
    comment_lines = 0
    for p in src_files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        doc_lines += docstring_lines(tree)
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("#"):
                comment_lines += 1
    total_lines = sum(src_lines.values())
    density = {
        "docstring_lines": doc_lines,
        "comment_lines": comment_lines,
        "total_lines": total_lines,
        "docstring_per_100_lines": round(doc_lines / total_lines * 100, 3) if total_lines else 0.0,
        "comment_per_100_lines": round(comment_lines / total_lines * 100, 3) if total_lines else 0.0,
    }

    # ---- 5. 重复 docstring 段 ----
    seg_files: dict[str, set[str]] = {}
    for p in src_files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = _rel(p, root)
        for seg in _docstring_segments(tree):
            if len(seg) < DUP_SEGMENT_MIN_CHARS:
                continue
            seg_files.setdefault(seg, set()).add(rel)
    dups = {seg: files for seg, files in seg_files.items() if len(files) >= 2}
    dup_rows = sorted(
        ({"chars": len(seg), "files": len(files), "preview": seg.splitlines()[0][:80]}
         for seg, files in dups.items()),
        key=lambda r: (-r["files"], -r["chars"], r["preview"]))

    return {
        "root": str(root),
        "src_rel": str(src_rel),
        "tests_rel": str(tests_rel),
        "scanned_ok": True,
        "vacuum_reason": "",
        "scanned_files_unparsable": bad_files,
        "scanned": {"src_files": len(src_files), "tests_files": len(tests_files)},
        "lines": {
            "src_total": total_lines,
            "tests_total": sum(tests_lines.values()),
            "src_mean": round(total_lines / len(src_files), 1),
        },
        "big_files": big_counts,
        "big_files_top": big_lists,
        "long_defs": long_counts,
        "long_defs_top": long_lists,
        "density": density,
        "dup_docstring_segments": len(dups),
        "dup_docstring_top": dup_rows[: max(top, 0)],
        "thresholds": {
            "big_files": list(BIG_THRESHOLDS),
            "long_defs": list(LONG_THRESHOLDS),
            "dup_segment_min_chars": DUP_SEGMENT_MIN_CHARS,
        },
    }


def format_text(data: dict) -> str:
    """人读版（`--json` 之外的那一条路）。每个数都带口径，不写裸数字。"""
    if not data.get("scanned_ok"):
        return f"没查成：{data.get('vacuum_reason', '')}"

    out: list[str] = []
    sc, ln = data["scanned"], data["lines"]
    out.append(f"扫描面：src/agentflow 下 {sc['src_files']} 个 .py、{ln['src_total']} 行"
               f"（均 {ln['src_mean']} 行/文件）；tests 下 {sc['tests_files']} 个 .py、"
               f"{ln['tests_total']} 行")
    bad = data.get("scanned_files_unparsable") or []
    if bad:
        out.append(f"  解析不了（没查成的那几个）{len(bad)} 个：{bad[:5]}")

    out.append("")
    out.append("大文件（src，严格大于）：")
    for th in data["thresholds"]["big_files"]:
        n = data["big_files"][f"gt{th}"]
        out.append(f"  > {th:5d} 行：{n} 个")
        for r in data["big_files_top"][f"gt{th}"]:
            out.append(f"      {r['lines']:6d}  {r['path']}")

    out.append("")
    out.append("长定义（src，源码跨度 end_lineno - lineno + 1，严格大于）：")
    for th in data["thresholds"]["long_defs"]:
        fn = data["long_defs"][f"function_gt{th}"]
        cl = data["long_defs"][f"class_gt{th}"]
        any_n = data["long_defs"][f"any_gt{th}"]
        out.append(f"  > {th:4d} 行：def {fn} 个 / class {cl} 个 / 合计 {any_n} 个")
        for r in data["long_defs_top"][f"gt{th}"]:
            out.append(f"      {r['lines']:5d}  {r['file']}:{r['line']}  {r['kind']} {r['name']}")

    out.append("")
    d = data["density"]
    out.append(f"密度（分母 = src 物理行 {d['total_lines']} 行）："
               f"docstring {d['docstring_lines']} 行 = 每 100 行 {d['docstring_per_100_lines']}；"
               f"纯注释 {d['comment_lines']} 行 = 每 100 行 {d['comment_per_100_lines']}")
    out.append("")
    out.append(f"重复 docstring 段（>={data['thresholds']['dup_segment_min_chars']} 字符、"
               f"跨文件逐字）：{data['dup_docstring_segments']} 段")
    for r in data["dup_docstring_top"]:
        out.append(f"      {r['files']} 个文件 / {r['chars']} 字符：{r['preview']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。`0` = 量到了；`2` = 没量成（扫描面为空）。"""
    ap = argparse.ArgumentParser(
        prog="repo_survey",
        description="仓库体量巡检（只读）：不写盘、不改代码、不联网",
    )
    ap.add_argument("--root", default=".", help="仓库根（默认当前目录）")
    ap.add_argument("--src", default=str(SRC_REL), help=f"源码扫描面（默认 {SRC_REL.as_posix()}）")
    ap.add_argument("--tests", default=str(TESTS_REL), help=f"判据扫描面（默认 {TESTS_REL.as_posix()}）")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP, help="每份清单取前几条（默认 10）")
    ap.add_argument("--json", action="store_true", help="把读数打成一份 JSON")
    args = ap.parse_args(argv)

    data = survey(args.root, src_rel=args.src, tests_rel=args.tests, top=args.top)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_text(data))
    return 0 if data.get("scanned_ok") else 2


if __name__ == "__main__":
    sys.exit(main())
