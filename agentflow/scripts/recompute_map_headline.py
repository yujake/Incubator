# -*- coding: utf-8 -*-
"""把 `docs/READING-MAP.md` 开头那句三格读数按现盘重算（对账 / 可选写回）。

## 为什么它是长期工具

那份读数（`N 个 .py`、总行数、`agent_loop.py` 行数）每加/删一个源文件就会变一次，
而它又写在文档第一句、被人当现状读 ⇒ 「重算它」跟着仓库长，不跟着某趟真机长。
（原稿：`temp/recompute_map_headline.py`，2026-11-20 提升进 `scripts/`。）

只改开头那一处读数（第一处 `N 个 .py、T 行` 与同一句里 `agent_loop.py，M 行`）；
历史 changelog 里的旧读数一个字不动。

## 用法（在 `agentflow/` 下）

    python scripts/recompute_map_headline.py            # 只报：0=一致 / 1=漂了 / 2=没查成
    python scripts/recompute_map_headline.py --write    # 写回开头那一句

退出码：0 = 查过、一致；1 = 查过、不一致；2 = 没查成（文档读不到 / 开头那句匹配不到）。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "agentflow"
DOC = ROOT / "docs" / "READING-MAP.md"

_HEADLINE = re.compile(r"\*\*(\d+) 个 `\.py`、([\d,]+) 行\*\*")
_LOOP = re.compile(r"`agent_loop\.py`，([\d,]+) 行")


def read_now() -> dict[str, int]:
    sizes = [len(p.read_text(encoding="utf-8").splitlines())
             for p in SRC.rglob("*.py") if "__pycache__" not in str(p)]
    return {
        "files": len(sizes),
        "total": sum(sizes),
        "big": sum(1 for n in sizes if n > 800),
        "loop": len((SRC / "agent_loop.py").read_text(encoding="utf-8").splitlines()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="重算 docs/READING-MAP.md 开头那句三格读数（缺省只报）")
    ap.add_argument("--write", action="store_true",
                    help="把开头那一句写成现算值（历史 changelog 一字不动）")
    args = ap.parse_args(argv)

    try:
        now = read_now()
        text = DOC.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[unknown] 读不出源码树/文档：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    found = _HEADLINE.search(text)
    loop_found = _LOOP.search(text)
    if not found or not loop_found:
        print("[unknown] 开头那句三格读数/agent_loop 行数匹配不到 ⇒ 没查成（不是已经一致）",
              file=sys.stderr)
        return 2

    old_files, old_total = int(found.group(1)), int(found.group(2).replace(",", ""))
    old_loop = int(loop_found.group(1).replace(",", ""))
    print(f"  现盘：{now['files']} 个 .py、{now['total']:,} 行；"
          f"agent_loop.py {now['loop']:,} 行；big(>800)={now['big']}")
    print(f"  文档：{old_files} 个 .py、{old_total:,} 行；agent_loop.py {old_loop:,} 行")

    drift = (old_files, old_total, old_loop) != (now["files"], now["total"], now["loop"])
    if not drift:
        print("[ok] 文档开头那一句与现盘一致")
        return 0
    if not args.write:
        print("[drift] 不一致（要落盘加 --write）")
        return 1

    out = text[:found.start()] + \
        f"**{now['files']} 个 `.py`、{now['total']:,} 行**" + text[found.end():]
    # 第二处在同一句里；区间可能因第一次替换而移动 ⇒ 重新定位。
    loop_hit = _LOOP.search(out)
    if loop_hit is not None:
        out = out[:loop_hit.start()] + \
            f"`agent_loop.py`，{now['loop']:,} 行" + out[loop_hit.end():]
    DOC.write_text(out, encoding="utf-8", newline="")
    print("[write] 已写回开头那一句")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
