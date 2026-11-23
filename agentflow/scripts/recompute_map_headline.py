# -*- coding: utf-8 -*-
"""把 `docs/READING-MAP.md` 开头那句四格读数按现盘重算（对账 / 可选写回）。

## 为什么它是长期工具

那份读数（`N 个 .py`、总行数、`>800` 的文件数、`agent_loop.py` 行数）每加/删一个
源文件就会变一次，而它又写在文档第一句、被人当现状读 ⇒ 「重算它」跟着仓库长，
不跟着某趟真机长。（原稿：`temp/recompute_map_headline.py`，2026-11-20 提升进
`scripts/`。）

## 口径：根是 `src/`，不是 `src/agentflow/`

`src/agentflow/` 只是今天 `src/` 下唯一的子包（`src/` 里只有它一个含 `.py` 的目录），
所以两者此刻读数相同。但文档与本仓库的权威判据都把根写成 `src/`：

* `docs/READING-MAP.md:6` 自述「口径：`src/` 下全部 `*.py`」；
* `tests/test_reading_map_counts.py::_live()` 的 `SRC = ROOT / "src"`；
* `scripts/check_doc_numbers.py::headline_now()` 同样用 `root / "src"`。

本脚本此前用 `src/agentflow`，一旦有人在 `src/` 下新增一个独立的 `.py`（不在
`agentflow/` 里），它就会与文档/判据分家：文档写的是“`src/` 全部”，而本脚本只数
子包。统一到 `src/` —— 以“文档所指”为准，且与判据同一根，改口径只需改这一处。

`>800` 那一格（`big`）此前只打印、不参与比较：文档漂了它也不红。现在它和另外三格
一样进 `drift`，`--write` 也一起写回。

只改开头那一处读数（第一处 `N 个 .py、T 行`、同一段的 `F 个文件超过 800 行`
与 `agent_loop.py，M 行`）；历史 changelog 里的旧读数一个字不动。

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
SRC = ROOT / "src"
DOC = ROOT / "docs" / "READING-MAP.md"

_HEADLINE = re.compile(r"\*\*(\d+) 个 `\.py`、([\d,]+) 行\*\*")
_BIG = re.compile(r"(\d+)\s*个文件超过\s*800\s*行")
_LOOP = re.compile(r"`agent_loop\.py`，([\d,]+) 行")


def read_now() -> dict[str, int]:
    """现算四格；根是 `src/`（与文档自述、`test_reading_map_counts.py` 同根）。"""
    sizes = [(path, len(path.read_text(encoding="utf-8").splitlines()))
             for path in sorted(SRC.rglob("*.py"))
             if "__pycache__" not in str(path)]
    if not sizes:
        raise OSError(f"{SRC} 下一个 `*.py` 都没读到 ⇒ 扫的是空集，不是“一致”")
    loops = [count for path, count in sizes if path.name == "agent_loop.py"]
    if not loops:
        raise OSError(f"{SRC} 下没有 `agent_loop.py` ⇒ 那一格没对象")
    return {
        "files": len(sizes),
        "total": sum(count for _path, count in sizes),
        "big": sum(1 for _path, count in sizes if count > 800),
        "loop": loops[0],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="重算 docs/READING-MAP.md 开头那句四格读数（缺省只报）")
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
    big_found = _BIG.search(text)
    loop_found = _LOOP.search(text)
    if not found or not big_found or not loop_found:
        print("[unknown] 开头那句四格读数（含 `>800` 与 agent_loop 行数）匹配不到 ⇒ "
              "没查成（不是已经一致）", file=sys.stderr)
        return 2

    old_files, old_total = int(found.group(1)), int(found.group(2).replace(",", ""))
    old_big = int(big_found.group(1))
    old_loop = int(loop_found.group(1).replace(",", ""))
    print(f"  现盘：{now['files']} 个 .py、{now['total']:,} 行；"
          f"{now['big']} 个文件超过 800 行；agent_loop.py {now['loop']:,} 行")
    print(f"  文档：{old_files} 个 .py、{old_total:,} 行；"
          f"{old_big} 个文件超过 800 行；agent_loop.py {old_loop:,} 行")

    drift = ((old_files, old_total, old_big, old_loop)
             != (now["files"], now["total"], now["big"], now["loop"]))
    if not drift:
        print("[ok] 文档开头那一句与现盘一致")
        return 0
    if not args.write:
        print("[drift] 不一致（要落盘加 --write）")
        return 1

    out = text[:found.start()] + \
        f"**{now['files']} 个 `.py`、{now['total']:,} 行**" + text[found.end():]
    # 另外两处在同一段里；区间会因前一次替换而移动 ⇒ 每次重新定位。
    big_hit = _BIG.search(out)
    if big_hit is not None:
        out = out[:big_hit.start()] + \
            f"{now['big']} 个文件超过 800 行" + out[big_hit.end():]
    loop_hit = _LOOP.search(out)
    if loop_hit is not None:
        out = out[:loop_hit.start()] + \
            f"`agent_loop.py`，{now['loop']:,} 行" + out[loop_hit.end():]
    DOC.write_text(out, encoding="utf-8", newline="")
    print("[write] 已写回开头那一句")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
