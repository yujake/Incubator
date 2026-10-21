"""把「docstring 压缩」这件事做成一个可复用、可判据的工具（业主 2026-10-21：「解决工装问题」）。

## 为什么要有它（而不是让每个清洁工自己手改）

2026-10-21 那一轮"代码清洁"里，四个执行者各自写了临时脚本，踩到两类事故：

1. 写回值不等于给的文本：docstring 是普通字符串字面量，`\\bibitem` 这样的写法在非 raw
   文档串里解析出来是 `\bibitem` —— 于是"给的文本"与"落盘后解析出来的值"永远不等，
   有人为了绕过去改了断言，有人把 `\bibitem` 写成了单反斜杠、当场变成退格符 U+0008。
2. CRLF 回来了：`Path.write_text` 在 Windows 上按 `os.linesep` 翻译换行。

所以这里的 `patch` 子命令做两件必须做对的事：
- 把文本序列化成安全的字面量（反斜杠、三引号、行尾引号都转义），再写盘 ——
  于是"解析出来的值 == 你给的文本"这条断言永远成立，不需要谁去改断言；
- 显式指定换行（`newline="\\n"`），写盘后立刻按字节复核 `\\r\\n` 计数为 0。

## 子命令

- `list <路径...>`：列出超限 docstring（模块 >20 行、类/函数 >12 行；行数 = 该常量在源码里跨的行数）。
- `patch <补丁.py>`：补丁文件里放 `PATCHES = [dict(file=..., kind=..., name=..., text=...)]`；
  按「kind + name + 首行」定位（不按行号，行号会漂），写回并断言值一致。
- `verify <路径...>`：四条硬检查 + 两条读数 ——
  ① 去 docstring 后 AST 与 `git show HEAD:<file>` 相同；
  ② 非 docstring 字符串字面量逐字节相同；
  ③ 文件里 `\\r\\n` 为 0；
  ④ 超限段为 0（对本文件而言）；
  ⑤ 指针零丢失（反引号标识符 / `draft/NN` / `§` / 日期 / `test_*` / `文件:行`）；
  ⑥ 首行文字未变（只允许去掉 `…` 的星号）。

## 退出码（三态纪律：没查成 ≠ 没问题）

```
0 = 全部通过
1 = 查过了，有失败项
2 = 没查成（文件不存在 / 不在 git 仓库 / 取不到 HEAD 基线 / 补丁定位不唯一）
```

## 与 FC-27 的关系

它只改 docstring，不改代码；但 `store.py` / `schema.py` / `verify.py` / `capabilities.py` /
`agentspec.py` 这些文件本身在禁改区 ⇒ 用本工具动它们的 docstring 仍要 2 名人审
（`scripts/noai_gate.py` 会照常拦）。本工具不替你签任何东西。
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

MODULE_LIMIT = 20
DEF_LIMIT = 12
DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

#: 指针：反引号标识符 / `draft/NN` / `§NN` / 日期 / `test_*` / `文件:行`
_POINTER_PATTERNS = (
    re.compile(r"`([^`\n]{1,80})`"),
    re.compile(r"draft/[\w.\-]+"),
    re.compile(r"§\s?\d+"),
    re.compile(r"\b20\d\d-\d\d-\d\d\b"),
    re.compile(r"\btest_[a-z0-9_]+\b"),
    re.compile(r"\b[\w./\\-]+\.py:\d+"),
)


# ---------------------------------------------------------------- 基本读数


def doc_line_count(node: ast.AST) -> int:
    """这个节点若是 docstring，返回它在源码里跨的行数（含首行）；否则 0。"""
    body = getattr(node, "body", [])
    if not body:
        return 0
    first = body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return 0
    return int(getattr(first.value, "end_lineno", first.value.lineno) - first.value.lineno) + 1


def limit_for(node: ast.AST) -> int:
    return MODULE_LIMIT if isinstance(node, ast.Module) else DEF_LIMIT


def name_of(node: ast.AST) -> str:
    return "<module>" if isinstance(node, ast.Module) else str(getattr(node, "name", "?"))


def kind_of(node: ast.AST) -> str:
    if isinstance(node, ast.Module):
        return "module"
    if isinstance(node, ast.ClassDef):
        return "class"
    return "func"


def over_limit(source: str) -> list[tuple[ast.AST, int, int]]:
    """返回 `[(节点, 行数, 限额)]`，只含超限的那些。"""
    tree = ast.parse(source)
    out: list[tuple[ast.AST, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, DOC_OWNERS):
            continue
        got = doc_line_count(node)
        if got and got > limit_for(node):
            out.append((node, got, limit_for(node)))
    out.sort(key=lambda item: (getattr(item[0], "lineno", 0), name_of(item[0])))
    return out


def pointers(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in _POINTER_PATTERNS:
        found.update(m.group(0) for m in pattern.finditer(text))
    return found


def first_line(text: str) -> str:
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def bare(text: str) -> str:
    """去掉强调标记与空白，用于"首行文字未变"的比较（只允许删星号/emoji）。"""
    return re.sub(r"\*\*|\s+", "", text)


def dedent(value: str, indent: str) -> str:
    """把 `literal()` 加在续行上的前缀缩进去掉（只去那一段前缀，不做 `expandtabs`）。

    为什么不用 `inspect.cleandoc`：它会对每一行 `expandtabs()`，而制表符展开后的宽度
    依赖行首列号 —— 带缩进与不带缩进的两份文本会展开成不同结果（实测过）。这里只做
    "把我知道自己加上的那段前缀删掉"这一件事，没有别的猜测。
    """
    if not indent:
        return value
    lines = value.split("\n")
    for i in range(1, len(lines)):
        if lines[i].startswith(indent):
            lines[i] = lines[i][len(indent):]
    return "\n".join(lines)


def literal(text: str, indent: str) -> str:
    """把 `text` 安全地序列化成一个三引号字面量（缩进后逐行落盘）。

    这是本工具存在的理由：反斜杠与三引号都要转义，否则"解析出来的值"会与 `text` 不等
    （真事故：`\\bibitem` 被写成单反斜杠 ⇒ 落盘后是退格符 U+0008）。
    """
    body = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if body.endswith('"'):
        body = body[:-1] + '\\"'
    lines = body.split("\n")
    rendered = ['"""' + lines[0]]
    for line in lines[1:]:
        rendered.append((indent + line) if line.strip() else "")
    rendered[-1] = rendered[-1] + '"""'
    return "\n".join(rendered)


# ---------------------------------------------------------------- 定位与写回


def _find_node(tree: ast.AST, kind: str, name: str, head: str) -> ast.AST:
    """按 kind + name + 首行定位（不按行号：行号在并行编辑里会漂）。"""
    hits: list[ast.AST] = []
    for node in ast.walk(tree):
        if not isinstance(node, DOC_OWNERS) or kind_of(node) != kind or name_of(node) != name:
            continue
        got = ast.get_docstring(node, clean=False)
        if got is None:
            continue
        if bare(first_line(got)) != bare(head):
            continue
        hits.append(node)
    if len(hits) != 1:
        raise SystemExit(f"补丁定位失败（{name}/{kind}）：命中 {len(hits)} 个，要求恰好 1 个")
    return hits[0]


def _byte_layout(source: bytes) -> list[int]:
    """每一行起始字符的字节偏移（`ast` 的 `col_offset` 是 UTF-8 字节，不是字符）。"""
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def apply_patch(entry: Mapping[str, Any]) -> str:
    """把一个 docstring 换成 `entry["text"]`（转义、缩进、行尾全由本函数负责）。

    两个必须做对的地方（都是真事故）：

    1. 列偏移是 UTF-8 字节，不是字符：Python 3.8+ 的 `col_offset` / `end_col_offset`
       按字节算。拿它去切 `str`，只要那一行含中文，`tail_part` 就会取成空、
       把行尾换行吃掉，于是收尾三引号与下一条语句粘成一行 → SyntaxError。
       这里整段改在 bytes 上做（`_byte_layout` 给每行的字节起点）。
    2. 先在内存里验证再落盘：新源码必须能 `ast.parse`，且解析出的 docstring
       值（`dedent` 后）逐字等于 `text`；任何一条不成立就 SystemExit，不写盘。
    """
    path = Path(str(entry["file"]))
    if not path.is_file():
        raise SystemExit(f"{path}: 文件不存在（没查成，不是通过）")
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise SystemExit(f"{path}: 落盘前就是 CRLF —— 先统一换行再来打补丁")
    source = raw.decode("utf-8")
    node = _find_node(ast.parse(source), str(entry["kind"]), str(entry["name"]), str(entry.get("head", "")))
    body0 = node.body[0]
    value = body0.value
    assert isinstance(value, ast.Constant)
    text = str(entry["text"])

    starts = _byte_layout(raw)
    abs_start = starts[value.lineno - 1] + int(value.col_offset)
    abs_end = starts[(value.end_lineno or value.lineno) - 1] + int(value.end_col_offset or 0)
    indent = " " * int(value.col_offset)
    new_block = literal(text, indent).encode("utf-8")
    new_source = raw[:abs_start] + new_block + raw[abs_end:]

    # —— 先验后写：解析得出、值对得上，才落盘
    try:
        rebuilt = new_source.decode("utf-8")
        tree = ast.parse(rebuilt)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise SystemExit(f"{path} {entry['name']}: 生成的源码不合法（未写盘）：{exc}") from None
    got = None
    for node2 in ast.walk(tree):
        if not isinstance(node2, DOC_OWNERS) or kind_of(node2) != str(entry["kind"]):
            continue
        if name_of(node2) != str(entry["name"]):
            continue
        got = ast.get_docstring(node2, clean=False)
        break
    # 比较口径 = `dedent`：缩进是排版不是内容（`inspect.cleandoc` 会 expandtabs，不能用）
    if dedent(got or "", indent) != text:
        raise SystemExit(f"{path} {entry['name']}: 写回值与 text 不等（未写盘）")

    path.write_bytes(new_source)
    if b"\r\n" in path.read_bytes():
        raise SystemExit(f"{path}: 写回后出现 CRLF（换行没显式指定）")
    return f"ok   {path}: {entry['name']} 写入 {text.count(chr(10)) + 1} 行"


# ---------------------------------------------------------------- 验证


def _repo_relative(rel: str) -> str:
    """把"相对当前目录的路径"换算成 仓库根相对 的 posix 路径。

    本仓的 `.git` 在上一级（交付物在 `agentflow/` 子目录里）⇒ `git show HEAD:src/…` 一定失败，
    必须换算成 `agentflow/src/…`。换算不出来就报 SystemExit（没查成，不是通过）。
    """
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
    if top.returncode != 0:
        raise SystemExit("不在 git 仓库里 ⇒ 取不到 HEAD 基线（没查成，不是通过）")
    root = Path(top.stdout.decode("utf-8", "surrogateescape").strip())
    absolute = Path(rel).resolve()
    try:
        return absolute.relative_to(root).as_posix()
    except ValueError:
        raise SystemExit(f"{rel}: 不在仓根 {root} 之下 ⇒ 没查成") from None


def head_source(rel: str) -> str:
    repo_rel = _repo_relative(rel)
    proc = subprocess.run(["git", "show", f"HEAD:{repo_rel}"], capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"{rel}: 取不到 HEAD 基线（HEAD 里没有 {repo_rel}）⇒ 没查成，不是通过")
    return proc.stdout.decode("utf-8", "surrogateescape")


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, DOC_OWNERS):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body[0].value.value = ""
    return tree


def _strings(tree: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def verify_one(rel: str) -> list[str]:
    """四条硬检查 + 两条读数；返回问题清单（空 = 绿）。"""
    path = Path(rel)
    if not path.is_file():
        raise SystemExit(f"{rel}: 文件不存在（没查成）")
    before = head_source(rel)
    after = path.read_bytes().decode("utf-8", "surrogateescape")
    problems: list[str] = []

    if ast.dump(_strip_docstrings(ast.parse(before))) != ast.dump(_strip_docstrings(ast.parse(after))):
        problems.append("AST-without-docstrings differs")
    if _strings(_strip_docstrings(ast.parse(before))) != _strings(_strip_docstrings(ast.parse(after))):
        problems.append("non-doc string literals differ")
    if b"\r\n" in path.read_bytes():
        problems.append("CRLF")

    still = over_limit(after)
    if still:
        problems.append(f"still over {len(still)}: " + ", ".join(
            f"{kind_of(n)} {name_of(n)} {got}>{lim}" for n, got, lim in still[:6]))

    # 指针 + 首行：逐节点比（按 kind+name 配对）
    old_docs = {(kind_of(n), name_of(n)): ast.get_docstring(n, clean=False)
                for n in ast.walk(ast.parse(before)) if isinstance(n, DOC_OWNERS)}
    new_docs = {(kind_of(n), name_of(n)): ast.get_docstring(n, clean=False)
                for n in ast.walk(ast.parse(after)) if isinstance(n, DOC_OWNERS)}
    dropped: list[str] = []
    heads: list[str] = []
    for key, old in old_docs.items():
        new = new_docs.get(key)
        if old is None or new is None or old == new:
            continue
        lost = pointers(old) - pointers(new)
        if lost:
            dropped.append(f"{key[1]} 丢了 {sorted(lost)[:4]}")
        if bare(first_line(old)) != bare(first_line(new)):
            heads.append(key[1])
    if dropped:
        problems.append("dropped pointers: " + "; ".join(dropped[:4]))
    if heads:
        problems.append("first line changed: " + ", ".join(heads[:4]))
    return problems


# ---------------------------------------------------------------- CLI


def _cmd_list(args: argparse.Namespace) -> int:
    total = 0
    for rel in args.paths:
        source = Path(rel).read_text(encoding="utf-8")
        rows = over_limit(source)
        total += len(rows)
        for node, got, lim in rows:
            print(f"### {rel}:{getattr(node, 'lineno', 1)} [{kind_of(node)}] {name_of(node)} {got}>{lim}")
            doc = ast.get_docstring(node, clean=False) or ""
            ptr = sorted(pointers(doc))
            print("POINTERS: " + " | ".join(ptr) if ptr else "POINTERS: (none)")
    print(f"== over-limit segments {total}")
    return 0 if total == 0 else 1


def _cmd_patch(args: argparse.Namespace) -> int:
    namespace: dict[str, Any] = {}
    exec(compile(Path(args.patch_file).read_text(encoding="utf-8"), args.patch_file, "exec"), namespace)
    entries = namespace.get("PATCHES") or []
    if not entries:
        print("补丁文件里没有 PATCHES ⇒ 没查成")
        return 2
    for entry in entries:
        print(apply_patch(entry))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    failed = 0
    for rel in args.paths:
        problems = verify_one(rel)
        if problems:
            failed += 1
            print(f"FAIL {rel}: " + " | ".join(problems))
        else:
            print(f"ok   {rel}")
    print(f"== files {len(args.paths)} fail {failed}")
    return 0 if failed == 0 else 1


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="docstring 压缩/校验（值一致性与换行都由工具保证）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="列出超限 docstring")
    p_list.add_argument("paths", nargs="+")
    p_list.set_defaults(func=_cmd_list)
    p_patch = sub.add_parser("patch", help="按 kind+name+首行定位并写回")
    p_patch.add_argument("patch_file")
    p_patch.set_defaults(func=_cmd_patch)
    p_verify = sub.add_parser("verify", help="四条硬检查 + 指针/首行读数")
    p_verify.add_argument("paths", nargs="+")
    p_verify.set_defaults(func=_cmd_verify)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
