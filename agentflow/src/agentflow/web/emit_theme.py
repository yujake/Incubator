# -*- coding: utf-8 -*-
"""把 :mod:`agentflow.web.assets` 的令牌层写成前端的 `ui/src/theme/generated/theme.css`。

## 这是什么

一份生成器，不是一份样式。令牌的单一来源仍然是 `web/assets.py` 的
:data:`THEME_CSS`（逐字照搬 DSH，MIT，来源见 `docs/USER-END-DSH-STYLE.md`）；
前端工程只消费它 —— 于是「换皮只换一层」这条对前端同样成立。

## 为什么要有它（而不是让前端自己抄一份）

抄一份就有两份，而两份一定会漂。判据是「生成物与源一致」
（`tests/test_webui_contracts.py` 里的新鲜度那两条）：手改生成物一个字节就红。
这与裁定 M2（`types.ts` 由脚本生成）是同一条纪律的两个落点。

## 命名为什么不是 `render` / `emit` / `main`

lint 的 R003 会点"同一个公开名在多个模块里各有一份独立实现"，而本包两个生成器
做的事不同（一个吐 CSS、一个吐 TS），谁也不是谁的转发 —— 那就只能让名字各自
具体：`render_css` / `write_theme`。入口刻意私有（`_main`，由 `__main__` 块调用）：
`main` 这个名字在 `cli.py` 已经是"整套命令行"的入口，再要一个同名公开入口正是
R003 要问的那件事。

## 确定性

同样的 `THEME_CSS` 一定产出逐字节相同的文件：没有时间戳、没有随机、换行统一
成 LF、末尾恰好一个换行。判据要按字节比对，这一条是它的前提。

## 用法

    python -m agentflow.web.emit_theme            # 写默认落点
    python -m agentflow.web.emit_theme --target <路径>
"""

from __future__ import annotations

import argparse
import pathlib
from typing import Sequence

from .assets import THEME_CSS

__all__ = ["REPO_REL", "render_css", "write_theme"]

#: 相对交付包根（`agentflow/`）的落点。
REPO_REL = ("ui", "src", "theme", "generated", "theme.css")


def _default_target() -> pathlib.Path:
    """默认落点（由本文件的位置推出来，不看当前工作目录）。"""
    return pathlib.Path(__file__).resolve().parents[3].joinpath(*REPO_REL)


def render_css() -> str:
    """生成物的正文（纯函数：不碰盘，判据与写盘共用它）。"""
    body = THEME_CSS.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return body + "\n"


def write_theme(target: str | pathlib.Path | None = None) -> pathlib.Path:
    """把正文写到 `target`（缺省 = 前端工程里的落点），返回落点。"""
    path = pathlib.Path(target) if target is not None else _default_target()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_css())
    return path


def _main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：写文件并打印落点与字节数。"""
    ap = argparse.ArgumentParser(
        prog="python -m agentflow.web.emit_theme",
        description="把 web/assets.py 的令牌层生成到 ui/src/theme/generated/theme.css")
    ap.add_argument("--target", default="", help="写到哪个文件（缺省 = 前端工程里的落点）")
    args = ap.parse_args(list(argv) if argv is not None else None)
    path = write_theme(args.target or None)
    print(f"{path}（{path.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
