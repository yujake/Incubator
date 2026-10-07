# -*- coding: utf-8 -*-
"""从 Python 侧生成前端的唯一类型来源 `ui/src/types.ts`（裁定 M2）。

## 为什么是生成物而不是手写

`draft/75 §1.3` 的每一个字段都来自盘上的真读数（`file:line` 级出处）。手写一份
TS 接口就是第二份口径：后端加一个键、前端没跟上时，`tsc` 只会觉得"少了一个可选
字段"，一声不吭。把类型交给这里生成之后，判据可以问一个更硬的问题：
生成物里的键集合与后端在夹具工作区上真读出来的键集合是不是同一批
（`tests/test_webui_contracts.py` 的 C 条）。手改生成物 ⇒ 新鲜度判据必红。

## 本批（W0）覆盖到哪

只覆盖后端此刻真的给得全的那些面。具体有哪些接口不写在这个文件里：
本生成器把三条零交线各自的 `type_decls()` 拼起来（`draft/78 §3` 的接缝）——

    `webui/state.type_decls()`（快照 / 场次 / 趟次）
  + `webui/readers.type_decls()`（B 线的只读面；W0 是空串）
  + `webui/writes.type_decls()`（C 线的写面：统一回执）

于是"加一个接口"发生在自己那一行里，本文件与 `emit_theme.py` 在本批之后不必再被碰。
还欠的接口同样不住在这里：每个模块用自己的 `MISSING_TYPES`（`(名字, 缺哪个 reader)`）
登记，本生成器把它们写成 `types.ts` 末尾的 TODO 注释 —— 那就是"其余接口留 TODO
注释并说明还缺哪个 reader"那条要求的落点。这些 TODO 只在注释里，不是真正的接口
声明，所以它们不会被 C 条误当成"前端多出来的键"。

## 命名（同 `emit_theme.py`）

lint 的 R003 会点"同一个公开名在多个模块里各有一份独立实现"：本包两个生成器
做的事不同，谁也不是谁的转发，所以名字各自具体（`render_types` / `write_types`），
入口私有（`_main`，由 `__main__` 块调用）—— `main` 这个名字在 `cli.py` 已经是
"整套命令行"的入口了。

## 确定性

同样的子表一定产出逐字节相同的文件（LF、末尾一个换行、无时间戳、无随机）：
新鲜度判据按字节比对，这是它的前提。

## 用法

    python -m agentflow.web.emit_types
"""

from __future__ import annotations

import argparse
import pathlib
from typing import Sequence

from ..webui import readers as _readers
from ..webui import state as _state
from ..webui import writes as _writes

__all__ = ["REPO_REL", "TYPES_PATH_LABEL", "render_types", "write_types"]

#: 相对交付包根（`agentflow/`）的落点。
REPO_REL = ("ui", "src", "types.ts")

#: 生成物头部必须出现的那句（判据读它：手改生成物的人先得把这句话删掉才敢改）。
TYPES_PATH_LABEL = "生成物，勿手改"

#: 文件头。逐字包含 :data:`TYPES_PATH_LABEL` —— 这是"这是一份生成物"的唯一声明点。
_HEADER = """\
// {label}；改 `agentflow/web/emit_types.py` 再重跑：
//   python -m agentflow.web.emit_types
//
// 唯一类型来源（`draft/75 §1` 的 C3 契约）：字段名逐字对应后端它自己的键，
// 不许在这里改名，也不许把后端一定会给的键写成可选。对齐由两条判据守着：
//   - 名字层：`tests/test_webui_contracts.py` 的 C 条（生成物键集合 vs 后端真读数）；
//   - 类型层：`pnpm typecheck`（`tsc --noEmit`，配 `strict` + `noUncheckedIndexedAccess`）。
//
// 手改本文件的任何一处都会让 C 条与新鲜度判据变红 —— 那是刻意的。
""".format(label=TYPES_PATH_LABEL)


def _default_target() -> pathlib.Path:
    """默认落点（由本文件的位置推出来，不看当前工作目录）。"""
    return pathlib.Path(__file__).resolve().parents[3].joinpath(*REPO_REL)


def _subtable_texts() -> tuple[str, ...]:
    """三条零交线各自的 TS 文本（`draft/78 §3` 的接缝）。"""
    return (_state.type_decls(), _readers.type_decls(), _writes.type_decls())


def _missing_text() -> str:
    """欠账清单：各模块自己登记的 `MISSING_TYPES` 渲染成 TODO 注释。

    清单住在那三个模块里，不住在这里 —— 于是 B/C 线补完一个接口只删自己文件里的
    一行，本生成器不必再被碰（`draft/78 §3` 那句"没有这三条，任何两条线都会撞在
    同一个文件上"）。
    """
    todo = ["// " + "-" * 74,
            "// 欠账清单：这些接口本批不生成（没有真读数就没有类型）。",
            "// 每一条都写明缺哪一个 reader —— 补上读数之后，把那一行从对应模块的",
            "// `MISSING_TYPES` 里删掉，并把接口加进那个模块的 `type_decls()`。",
            "// " + "-" * 74]
    for mod in (_state, _readers, _writes):
        for name, why in getattr(mod, "MISSING_TYPES", ()):
            todo.append(f"// TODO {name}：{why}。")
    return "\n".join(todo)


def render_types() -> str:
    """生成物的正文（纯函数：不碰盘，判据与写盘共用它）。"""
    parts: list[str] = [_HEADER]
    for text in _subtable_texts():
        if text.strip():
            parts.append(text)
    parts.append(_missing_text() + "\n")
    return "\n".join(parts)


def write_types(target: str | pathlib.Path | None = None) -> pathlib.Path:
    """把正文写到 `target`（缺省 = 前端工程里的落点），返回落点。"""
    path = pathlib.Path(target) if target is not None else _default_target()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_types())
    return path


def _main(argv: Sequence[str] | None = None) -> int:
    """命令行入口：写文件并打印落点与字节数。"""
    ap = argparse.ArgumentParser(
        prog="python -m agentflow.web.emit_types",
        description="从 Python 侧的表生成前端唯一类型来源 ui/src/types.ts")
    ap.add_argument("--target", default="", help="写到哪个文件（缺省 = 前端工程里的落点）")
    args = ap.parse_args(list(argv) if argv is not None else None)
    path = write_types(args.target or None)
    print(f"{path}（{path.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
