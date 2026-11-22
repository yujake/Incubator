"""收口读数：`git ls-files --eol` 里「index 是 LF、工作区是 CRLF」的已跟踪文件。

## 这一条补的是什么洞

判据（`tests/test_mechanical_rewrite_guards.py`）比的是"改过的文件：HEAD 与盘上按
行折平后不等才算漂移。`.gitattributes` 的 `text eol=lf` 会在 `git diff` 时把工作区的 CRLF
折平 —— 于是一类文件对它完全隐形：

    盘上是 CRLF、折平之后与 HEAD 逐字节相同 ⇒ 判据看不见，`git status` 也是干净的。

这种文件不会自己红，但它是一颗定时炸弹：谁下一次改它，判据立刻红（改一次就把它的
CRLF 带进 diff）。本脚本把这一类直接读出来：

    i/lf  w/crlf   ⇒ 入库是 LF，工作区被写成了 CRLF（潜伏漂移，本脚本的判据）

## 三态

| 退出码 | 含义 |
|---|---|
| `0` | 查过了：没有 `i/lf w/crlf/mixed` 的已跟踪文件 |
| `1` | 查过了：有（逐条列出） |
| `2` | 没查成：缺 git / 不在仓库里 / `git ls-files --eol` 跑不通 —— `unknown` 绝不是 pass |

`2` 这一档是刻意的：编排层（`tools/release_all.py` 的 `eol` 步）把 `2` 记成 `unknown`；
把"没查成"折成"通过"正是本项目反复踩过的坑。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

#: 盘面/入库面都只关心这些后缀（与 `.gitattributes` 的 `text eol=lf` 那一段同口径）。
TEXT_SUFFIXES = frozenset({
    ".py", ".pyi", ".md", ".txt", ".toml", ".cfg", ".ini", ".yml", ".yaml",
    ".ps1", ".sh", ".ts", ".tsx", ".js", ".jsx", ".css", ".html",
})

#: 按字节 sha256 冻结的快照：git 用 `-text` 碰都不碰，它们入库就是 CRLF 也是对的。
FROZEN_DIRS = ("tests/fixtures", "tests/golden")


def _run(root: Path, *args: str, binary: bool = False):
    """起 git；任何"起不来"都交给调用方记 unknown（不在这里吞）。"""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
        errors=None if binary else "replace",
        timeout=120,
    )


def git_eol(root: Path) -> tuple[dict[str, tuple[str, str]] | None, str]:
    """`{项目根相对路径: (index 行尾, 工作区行尾)}`；读不到 ⇒ `(None, 原因)`。

    相对路径以 `root` 为基准（`root` 可以是 git 仓库的子目录：`agentflow/` 就是这种情况）。
    """
    root = root.resolve()
    try:
        top = _run(root, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git 起不来（{type(exc).__name__}: {exc}）"
    if top.returncode != 0:
        return None, f"不在 git 仓库里（`git rev-parse` 退出码 {top.returncode}）"
    toplevel = Path(top.stdout.strip())
    try:
        prefix = root.relative_to(toplevel.resolve()).as_posix()
    except ValueError:
        return None, f"扫描根 {root} 与仓库根 {toplevel} 对不上"
    pathspec = "." if prefix in ("", ".") else prefix
    try:
        out = _run(toplevel, "ls-files", "--eol", "-z", "--", pathspec, binary=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"`git ls-files --eol` 起不来（{type(exc).__name__}: {exc}）"
    if out.returncode != 0:
        err = out.stderr.decode("utf-8", "replace").strip()[:200]
        return None, f"`git ls-files --eol` 退出码 {out.returncode}：{err}"

    mapping: dict[str, tuple[str, str]] = {}
    for rec in out.stdout.split(b"\x00"):
        if not rec.strip():
            continue
        meta, sep, raw_path = rec.partition(b"\t")
        if not sep:
            return None, f"`git ls-files --eol` 的行格式不认识：{rec[:120]!r}"
        tokens = meta.split()
        if len(tokens) < 2 or not tokens[0].startswith(b"i/") or not tokens[1].startswith(b"w/"):
            return None, f"`git ls-files --eol` 的行格式不认识：{meta[:120]!r}"
        rel = raw_path.decode("utf-8", "surrogateescape")
        if prefix not in ("", "."):
            lead = prefix + "/"
            if not rel.startswith(lead):
                continue
            rel = rel[len(lead):]
        mapping[rel] = (tokens[0][2:].decode(), tokens[1][2:].decode())
    return mapping, ""


def _is_frozen(rel: str) -> bool:
    return any(rel == d or rel.startswith(d + "/") for d in FROZEN_DIRS)


def read(root: Path) -> dict:
    """一次完整读数（status=ok/unknown；ok 时带 drift 清单）。

    `drift` 只收 `i/lf` 而 `w/crlf|mixed` 的已跟踪文件 —— 那一条同时满足
    "git 认为它该是 LF"与"盘上不是 LF"，且折平后与 HEAD 同字节 ⇒ 判据的隐形面。
    """
    mapping, why = git_eol(root)
    if mapping is None:
        return {"status": "unknown", "why": why, "tracked": 0, "drift": [],
                "committed_crlf": [], "counts": {"drift": 0, "committed_crlf": 0}}
    drift: list[dict] = []
    committed: list[str] = []
    for rel, (index, work) in sorted(mapping.items()):
        if _is_frozen(rel) or Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        if index == "lf" and work in ("crlf", "mixed"):
            drift.append({"path": rel, "index": index, "worktree": work})
        elif index == "crlf" and work == "crlf":
            committed.append(rel)  # 入库就是 CRLF：不是漂移，单独给一个读数
    return {
        "status": "ok",
        "why": "",
        "tracked": len(mapping),
        "drift": drift,
        "committed_crlf": committed,
        "counts": {"drift": len(drift), "committed_crlf": len(committed)},
    }


def main(argv: list[str] | None = None) -> int:
    """0 = 没有漂移；1 = 有漂移（逐条列出）；2 = 没查成（unknown，不是 pass）。"""
    ap = argparse.ArgumentParser(description="git ls-files --eol 的潜伏漂移读数（三态退出码）",
                                 allow_abbrev=False)
    ap.add_argument("--root", default=".", help="项目根（默认当前目录；可以是 git 仓库的子目录）")
    ap.add_argument("--json-out", default="", help="把读数写到该 JSON 路径（纯 LF）")
    ap.add_argument("--quiet", action="store_true", help="只返回退出码")
    args = ap.parse_args(argv)

    reading = read(Path(args.root))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(reading, ensure_ascii=False, indent=2) + "\n")

    if not args.quiet:
        c = reading["counts"]
        print(f"[eol] 已跟踪 {reading['tracked']} 个；"
              f"i/lf 而 w/crlf|mixed = {c['drift']}；i/crlf（入库即 CRLF）= {c['committed_crlf']}")
        for item in reading["drift"]:
            print(f"  DRIFT {item['path']}  i/{item['index']} w/{item['worktree']}")
    if reading["status"] != "ok":
        if not args.quiet:
            print(f"[eol] UNKNOWN —— 没查成，不是通过：{reading['why']}", file=sys.stderr)
        return 2
    if reading["drift"]:
        if not args.quiet:
            print("[eol] 这些文件盘上是 CRLF、入库是 LF：折平后与 HEAD 同字节 ⇒ 换行判据看不见它们，"
                  "下一次改它们时才会红。用 `newline=\"\\n\"`（或 `write_bytes`）重写一遍即可清零。",
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
