# -*- coding: utf-8 -*-
"""
一条规则看到的现场（`_Ctx`）与登记表（`RULES[kind][name]`）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .predicates import _Unchecked
from .states import KINDS, Finding


# ---------------------------------------------------------------- 规则上下文与登记表


@dataclass
class _Ctx:
    """一条规则看到的现场：工作区根、当前文件、解析后的对象、逐行（条）读数。"""

    kind: str
    root: Path | None
    path: Path | None
    rel: str
    obj: Any
    rows: list[tuple[int, Mapping[str, Any]]] = field(default_factory=list)
    #: JSONL 的坏行说明（`jsonlfile.read_jsonl_state` 的第二个返回值）。
    line_problems: list[str] = field(default_factory=list)
    #: 规则顺带记下的"这不是畸形"的读数（例如空动作是 S2 的生产形态）。它们不改三态。
    notes: list[str] = field(default_factory=list)

    def where(self, row_no: int = 0, field_name: str = "") -> str:
        """拼出"文件 + 位置"的读数串（行号从 1 起，与 `read_jsonl_state` 一致）。"""
        base = self.rel or (self.path.name if self.path else self.kind)
        if not row_no:
            return base
        slot = f"第{row_no}行" if self.path is not None and self.path.suffix == ".jsonl" \
            else f"第{row_no}条"
        return f"{base}#{slot}" + (f".{field_name}" if field_name else "")


RuleFn = Callable[[_Ctx], list[Finding]]

#: `RULES[kind][规则名]` —— 规则登记表。判据把某一条打桩掉就能验证它是不是承重的那条。
RULES: dict[str, dict[str, RuleFn]] = {kind: {} for kind in KINDS}


def _rule(kind: str, name: str) -> Callable[[RuleFn], RuleFn]:
    """把一条规则登记进 `RULES[kind][name]`（装饰器）。"""

    def register(fn: RuleFn) -> RuleFn:
        RULES[kind][name] = fn
        return fn

    return register


def _local_finding(ctx: _Ctx, code: str, detail: str, *, row_no: int = 0,
                   field_name: str = "", severity: str = "error") -> Finding:
    """在当前文件（或某一行）上落一条 Finding。"""
    return Finding(kind=ctx.kind, where=ctx.where(row_no, field_name),
                   detail=detail, severity=severity, code=code)


def _table_rows(root: Path | None, table: str) -> list[Mapping[str, Any]]:
    """读另一张表（跨表核对用）。读不到就抛 `_Unchecked`，不许当成"零行"。"""
    if root is None:
        raise _Unchecked(f"没有工作区根，读不到 data/{table}.json（跨表核对做不了）")
    path = root / "data" / f"{table}.json"
    if not path.is_file():
        raise _Unchecked(f"读不到 {path.name}（跨表核对需要它，缺它就不是「没有畸形」）")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Unchecked(f"{path.name} 读不出来（{type(exc).__name__}: {exc}）") from exc
    rows = doc.get("rows") if isinstance(doc, Mapping) else None
    if not isinstance(rows, list):
        raise _Unchecked(f"{path.name} 的 rows 不是数组（收到 {type(rows).__name__}）")
    return [r for r in rows if isinstance(r, Mapping)]
