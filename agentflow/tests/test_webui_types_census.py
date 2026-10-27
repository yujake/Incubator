# -*- coding: utf-8 -*-
"""生成物里"声明了、但前端一次没读"的字段清单（2026-10-27 业主裁定 W10）。

## 为什么这是一条判据，而不是一次性的删字段

这些字段是后端真读数的投影。把它们从 `type_decls()` 里删掉，未来接线时 `tsc` 就
也看不见它们了（"少了一个可选字段"从来不红）—— 那正是 `types.ts` 生成物要挡的
那一类静默。所以本文件只做两件事：

1. 把清单算出来（`unused_fields()`：可被别的判据/脚本复用，输出是稳定排序的）；
2. 反真空：证明这个扫描真的接上了（字段总数有下限、三个到处都在用的键必须被判成
   "有人读"）—— 否则一张空清单会被读成"全都用上了"。

清单本身不是缺陷，是一份待裁的账：业主按"要用的"与"该删的"分别裁。跑法（要看到清单
本身）：`python -m pytest tests/test_webui_types_census.py -q -s`。
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
TYPES_TS = UI_SRC / "types.ts"

#: 生成物里一个字段行的形状（与契约判据 C 的解析器同一口径）。
_FIELD = re.compile(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??\s*:", re.M)

#: 扫描的下限（反真空）：今天的生成物有四百多个字段名，掉到这个数以下说明解析失配。
MIN_FIELDS = 300


def _generated_fields() -> list[str]:
    """生成物里出现过的全部字段名（去重、稳定排序）。"""
    text = TYPES_TS.read_text(encoding="utf-8")
    return sorted({m.group(1) for m in _FIELD.finditer(text)})


def _frontend_text() -> str:
    """`ui/src` 下除 `types.ts` 之外的全部源码（拼成一份）。"""
    parts: list[str] = []
    for path in sorted(UI_SRC.rglob("*")):
        if not path.is_file() or path.suffix not in (".ts", ".tsx"):
            continue
        if path.name == "types.ts":
            continue
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def unused_fields() -> list[str]:
    """生成物里声明了、而在其余前端源码里一次都没出现的字段名。"""
    body = _frontend_text()
    return [name for name in _generated_fields()
            if re.search(rf"\b{re.escape(name)}\b", body) is None]


def test_the_census_is_not_vacuous() -> None:
    """反真空：扫描真的读到了两棵树（生成物的字段、其余源码的正文）。

    三个到处都在用的键必须被判成"有人读"：`tri`（每个面都有）、`reason`、
    `sid`。它们要是一个都没被判成有人读，那说明扫描器读的是空串 —— 那时"清单为空"
    绝不等于"全都用上了"。
    """
    if not TYPES_TS.is_file():
        pytest.skip(f"{TYPES_TS} 不在盘上")
    fields = _generated_fields()
    assert len(fields) >= MIN_FIELDS, f"只解析出 {len(fields)} 个字段 ⇒ 解析器可能失配"
    unused = unused_fields()
    for key in ("tri", "reason", "sid"):
        assert key not in unused, f"{key} 被判成「没人读」⇒ 扫描器可能读的是空串"
    # 反向：清单必须真的非空过（今天确实有一批声明了没人读的字段）。
    assert unused, "清单是空的 ⇒ 要么全都接上了（好事），要么扫描失效了（坏事）——请核对"


def test_the_census_prints_the_list(capsys: pytest.CaptureFixture[str]) -> None:
    """把清单打出来（`-q -s` 可见）；同时钉住它是稳定排序的（可 diff、可贴进报告）。"""
    if not TYPES_TS.is_file():
        pytest.skip(f"{TYPES_TS} 不在盘上")
    unused = unused_fields()
    print(f"\n生成物里声明了但前端一次没读的字段：{len(unused)} 个")
    print("、".join(unused))
    captured = capsys.readouterr()
    assert "生成物里声明了但前端一次没读的字段" in captured.out
    assert unused == sorted(unused), "清单不是稳定排序的"
