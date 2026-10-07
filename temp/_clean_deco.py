# -*- coding: utf-8 -*-
"""清洗：把**注释与 docstring** 里的 Markdown 强调标记与 emoji 装饰去掉。

## 作用域（三条边界，都有实测依据）

1. **只清 `#` 注释与 docstring** —— 那是"源码里的说明文字"，Markdown/emoji 在那里是纯噪音
   （终端、grep、`help()` 都不渲染它）。
2. **不碰普通字符串字面量** —— 它们可能是**产品输出**（C/D 的报告正文本身就是 markdown，
   `**粗体**` 在那里是正确的）。实测：全仓只有 5 处判据依赖含装饰的字符串，
   且全部是"渲染出来的报告正文"。
3. **不碰禁改区**（`.noai-paths` 命中的文件）—— 它们冻结待人工走查（FC-27）。

## 两处必须小心的形态（上一版脚本在这里出过错）

- **反引号里的 `**` 是字面语法**，不是强调：`` `a/**/b` ``（glob）、
  ``handler(**params)``（Python 解包）、``2**20``（幂）。**先屏蔽代码跨度再替换**，
  否则会把 `` `a/**/b` `` 吃成 `` `a//b` `` —— 那是真损坏，不是清洗。
- **粗体可以跨行**（模块 docstring 里常见）：``**...\n...**``。
  按行替换会**留下孤立的 `**`**（实测 99 处）。所以按"整个 docstring 文本"替换，
  并把"清完之后不许再有 `**`"写成脚本自己的断言（除代码跨度外）。

## 纪律

- **默认干跑**，只有 `--apply` 才写盘；重复跑幂等（第二次应当报 0 处）。
- 逐处前后对照写进 `--diff`，供人核对：机械替换本身也必须可复核。
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(r"D:\Incubator\agentflow")

EMOJI_CLS = (
    "\U0001F300-\U0001FAFF"      # 各类 emoji
    "\u2600-\u27BF"              # 杂项符号与装饰符（⚠ ✅ ❌ ✗ ✓ ⭐ …）
    "\u2B00-\u2BFF\uFE0F"
)
_EMOJI = re.compile(f"[{EMOJI_CLS}]\\s?")
#: Markdown 强调：允许跨行（docstring 里常见），内容不含 `*`、首尾非空白。
_BOLD = re.compile(r"\*\*(?=\S)([^*]{1,300}?)(?<=\S)\*\*", re.S)
#: 代码跨度：``...`` 或 `...`（先长后短匹配，避免 `` `` 被拆成两个单反引号）
_CODE = re.compile(r"``[^`]+``|`[^`\n]+`")
_SENTINEL = "\x00"


def _mask_code(s: str) -> str:
    """把代码跨度换成等长哨兵（仅用于**自检**：判断清完之后是否还有 `**`）。"""
    return _CODE.sub(lambda m: _SENTINEL * len(m.group(0)), s)


def clean_segment(s: str) -> str:
    """清洗一段注释正文或 docstring 正文（不含定界符）。

    实现要点：代码跨度先**取出存表**并用 `\\x00<i>\\x00` 占位，替换完再**按编号还原**。
    不能用"等长占位符 + 按位置回填"—— 后续替换会**缩短**字符串，位置立刻错位
    （第一版就是这么错的，被本文件末尾的自检断言当场抓住）。
    """
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(m.group(0))
        return f"{_SENTINEL}{len(codes) - 1}{_SENTINEL}"

    masked = _CODE.sub(stash, s)
    masked = _BOLD.sub(lambda m: m.group(1), masked)
    masked = _EMOJI.sub("", masked)
    # 跨**两个 `#` 注释行**的粗体没法在本段内配对（每行是独立的 COMMENT token），
    # 会在两行各留一个孤立的 `**`。清掉它们 —— 但先证明"剩下的 `**` 不是字面语法"：
    # 代码跨度已被占位符屏蔽，所以此刻还匹配 `<ASCII 词字符>**<ASCII 词字符>` 的
    # 只可能是幂（`2**20`）/ 标识符相邻一类，那种必须原样留着（宁可漏清，不可误删）。
    #
    # ⚠️ 这里刻意**只用 ASCII 词字符**：Python 的 `\\w` 把汉字也算词字符，
    # 于是"而**一"（跨行粗体的开头被上一行末尾的汉字紧邻）会被误判成字面语法，
    # 让整次清洗中止。判据要贴着**目标语言**（Python 的 `**` 运算符两侧只可能是 ASCII）。
    stray = re.findall(r"[A-Za-z0-9_]\*\*[A-Za-z0-9_]", masked)
    if stray:
        raise AssertionError(f"疑似字面 `**`（幂/glob/解包），拒绝清洗：{stray[:5]}")
    masked = masked.replace("**", "")
    return re.sub(rf"{_SENTINEL}(\d+){_SENTINEL}", lambda m: codes[int(m.group(1))], masked)


def _char_col(line: str, byte_col: int) -> int:
    """把 CPython AST 的 `col_offset`（**UTF-8 字节**偏移）换成**字符**下标。

    ⚠️ 这一步不能省。`ast` 的列号是字节偏移，而本文件的偏移计算按字符走；
    一行里有中文时两者不等，区间就会**越界到代码上** —— 实测它一度去清洗
    `fetch.py` 的 `min(2.0**attempt, 30.0)`（那是真的 Python 代码）。
    """
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", "ignore"))


def _spans(text: str) -> list[tuple[int, int, str]]:
    """返回要清洗的绝对偏移区间 `(start, end, kind)`（**字符**偏移）。"""
    lines = text.splitlines(keepends=True)
    starts, acc = [], 0
    for ln in lines:
        starts.append(acc)
        acc += len(ln)

    def off_ast(row: int, col_bytes: int) -> int:
        """**`ast` 专用**：把字节列号换成字符偏移。"""
        return starts[row - 1] + _char_col(lines[row - 1], col_bytes)

    def off_tok(row: int, col_chars: int) -> int:
        """**`tokenize` 专用**：它的列号本来就是字符偏移，**不要再换算一次**。

        ⚠️ 两个来源的列号语义不同，第一版把它们混用了：对 `#:` 开头的行
        （前缀全是 ASCII，字符数与字节数相同）再折一次"字节→字符"会把注释区间
        **截短一半**，于是清洗只作用到半行、留下孤立的 `**`。
        """
        return starts[row - 1] + col_chars

    out: list[tuple[int, int, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            out.append((off_tok(tok.start[0], tok.start[1]) + 1,
                        off_tok(tok.end[0], tok.end[1]), "comment"))

    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                c = first.value
                a = off_ast(c.lineno, c.col_offset)
                b = off_ast(c.end_lineno, c.end_col_offset)
                prefix = 3 if text[a:a + 3] in ('"""', "'''") else 1
                out.append((a + prefix, b - prefix, "docstring"))
    return out


def _code_signature(text: str) -> str:
    """模块的**代码**签名：把 docstring 内容抹成空串后 `ast.dump`。

    清洗不许改变它的任何一位 —— 这比"跑一遍测试"更强：测试只覆盖想得到的情形，
    而这个签名覆盖**全部**语法结构（含常量、运算符、装饰器、默认值）。
    注释本来就不进 AST，所以这个不变式只约束 docstring 与代码的边界是否算对。
    """
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body[0].value.value = ""
    return ast.dump(tree)


def _first_changed_line(before: str, after: str) -> tuple[str, str] | None:
    """这一段里**第一行**发生变化的前后文本（找不到返回 None）。

    为什么不拿"span 起始行"当对照行：模块 docstring 的 span 从第 1 行开始，
    而改动往往在第 3 行。第一版用起始行做前后对照，于是前后**相同**、
    这一处改动既没进对照表、也没被算作"有改动" —— 而 `main` 恰好拿对照表
    当"要不要写盘"的判据，结果 11 个文件的清洗被静默丢掉（判据真空通过）。
    """
    b, a = before.splitlines(), after.splitlines()
    if len(b) != len(a):
        return (before.strip()[:200], after.strip()[:200])
    for x, y in zip(b, a):
        if x != y:
            return (x.strip()[:200], y.strip()[:200])
    return None


def clean_source(text: str, rel: str) -> tuple[str, list[tuple[str, str]], int]:
    """返回 `(清洗后文本, 逐处前后对照, 真正改动的段数)`。

    第三个返回值是**"要不要写盘"的判据**，刻意与对照表分开：
    拿"对照表非空"当判据，就等于让一个**报告**去决定**是否落盘**，
    而报告可能因为格式原因少记（这个 bug 真的发生过）。
    """
    diffs: list[tuple[str, str]] = []
    changed = 0
    out = text
    for a, b, kind in sorted(_spans(text), key=lambda x: -x[0]):
        seg = out[a:b]
        new = clean_segment(seg)
        if new == seg:
            continue
        # 自检一：清完之后除了代码跨度，不许再有 `**`
        leftover = _mask_code(new)
        assert "**" not in leftover, f"{rel}: 清完仍有 `**`（{leftover[:80]!r}）"
        pair = _first_changed_line(seg, new)
        if pair is not None:
            diffs.append(pair)
        changed += 1
        out = out[:a] + new + out[b:]
    # 自检二（最强的一条）：代码签名逐字不变
    assert _code_signature(out) == _code_signature(text), \
        f"{rel}: 清洗改变了代码结构 —— 区间算错了，拒绝写盘"
    return out, diffs, changed


def zone_paths() -> set[str]:
    """`.noai-paths` 命中的文件（仓库相对、正斜杠）。这些文件不许动。"""
    gate = ROOT / "scripts" / "noai_gate.py"
    spec = importlib.util.spec_from_file_location("_noai_gate_for_clean", gate)
    assert spec and spec.loader
    ns = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ns
    spec.loader.exec_module(ns)
    rules = ns.load_manifest()
    out: set[str] = set()
    for f in ROOT.rglob("*"):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(ROOT).as_posix()
        for r in rules:
            if ns._glob_matches(ns._path_candidates(rel, ROOT), r.glob) is not None:
                out.add(rel)
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写盘（默认干跑）")
    ap.add_argument("--diff", default="", help="逐处前后对照写到该文件")
    args = ap.parse_args()

    zone = zone_paths()
    targets: list[Path] = []
    for g in ("src/agentflow/**/*.py", "scripts/*.py", "tools/*.py", "tests/*.py"):
        targets += sorted(ROOT.glob(g))
    targets = [p for p in targets if "__pycache__" not in p.parts]

    total = 0
    report, skipped = [], []
    for p in targets:
        rel = p.relative_to(ROOT).as_posix()
        if rel in zone:
            skipped.append(rel)
            continue
        text = p.read_text(encoding="utf-8")
        new, diffs, changed = clean_source(text, rel)
        # 判据是"文本真的变了"，不是"对照表非空"。
        if new == text:
            continue
        total += changed
        print(f"{rel:52s} {changed:4d} 处")
        report.append(f"\n### {rel}（{changed} 处）")
        for b, a in diffs:
            report.append(f"- 前：{b}\n  后：{a}")
        if args.apply:
            p.write_text(new, encoding="utf-8")
    print(f"\n合计 {total} 处；跳过禁改区 {len(skipped)} 个文件：{skipped}")
    if args.diff and report:
        Path(args.diff).write_text("\n".join(report), encoding="utf-8")
        print(f"逐处对照 -> {args.diff}")
    if not args.apply:
        print("（干跑，未写盘；加 --apply 才写。）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
