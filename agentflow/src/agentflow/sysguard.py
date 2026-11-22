# -*- coding: utf-8 -*-
"""系统自动产物的写点校验：一处记读数，写侧与读数侧共用。

## 这一层补的是什么

业主 2026-11-21 的推论：系统自己自动产出的字段与文件，必须由系统保证每一格；既不能
让模型补，也不能靠读侧宽容。SIGNMAL 的事故形态是：框架在写口漏写一格（`object_sha256`
没传），模型全程没有机会发现异常，而产品三处签读口全放行，只有一次普查抓到它。

那一类缺陷的共同形状不是"某一格写错了"，而是"写口漏写之后没有人拦"：行照样落盘、
读侧照样放行、下游读数照旧自洽。本模块给这一族写口提供一个统一的读数形状，让
"写点拒了"与"写点补了"在世界里留得下痕迹，并且读不到痕迹时不折成"没问题"。

## 它不做两件事

- 它不当门：任何读数都不进收工门，也不新增 blocker（业主口径：畸形要看得见，
  而不是再拦一道）。
- 它不判"这个值对不对"：判据在各自的写口里（例如"说回验通过就必须带区间"）。
  本模块只负责把那一判的结论按同一个形状记下来。

## 三态（与 `wellformed` / `noai_gate` 同源）

- `ok`：这一项查过了，没有要记的（本模块不写 ok 行，省得台账被正常路径灌满）；
- `refused`：写点拒了（一个字节都没按这份输入写下去），带理由码与修法；
- `derived`：写点在同一处补了一个值（补值只许发生在写点，读侧不许猜）；
- `unchecked`：这一项没查成（读不到台账、判据自己抛了）。

`unchecked` 绝不折成 `ok`：`read()` 读不到文件时返回 `unchecked`，`summarize()`
的 `checked` 也是 False —— 与 `noai_gate` 的退出码 2 同一纪律。

## 台账

`<工作区>/out/sysguard/write-readings.jsonl`，一行一条。它是只读读数，不是表：
不参与 `store` 的重建、不进 `ARTIFACTS.jsonl`、不被任何门读。`errorstats` 把它的
`refused` / `derived` 计数进过程读数类目 `write_point_guarded`（看得见，不计错）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import schema as S

__all__ = [
    "DERIVED",
    "FIELDS",
    "LEDGER_NAME",
    "OK",
    "WriteReading",
    "REFUSED",
    "STATES",
    "UNCHECKED",
    "derived",
    "readings_path",
    "read_readings",
    "write_reading",
    "record_reading",
    "refused",
    "readings_summary",
    "unchecked",
]

#: 四态（理由见模块 docstring）。顺序即严重度：读的人从重到轻看。
OK = "ok"
REFUSED = "refused"
DERIVED = "derived"
UNCHECKED = "unchecked"
STATES: tuple[str, ...] = (OK, REFUSED, DERIVED, UNCHECKED)

#: 台账的目录与文件名（工作区相对）。
LEDGER_DIR: tuple[str, ...] = ("out", "sysguard")
LEDGER_NAME = "write-readings.jsonl"

#: 一行读数的字段全集。写侧逐字用；读侧容忍缺格但会如实报成坏行。
FIELDS: tuple[str, ...] = ("at", "point", "state", "code", "where", "detail", "how_to_fix")


@dataclass(frozen=True)
class WriteReading:
    """一次写点判据的结论（不可变：改结论要换一条新的，不许就地改）。"""

    point: str
    state: str
    code: str
    where: str
    detail: str
    how_to_fix: str

    def as_dict(self) -> dict[str, str]:
        return {"at": S.now_iso(), "point": self.point, "state": self.state,
                "code": self.code, "where": self.where,
                "detail": self.detail, "how_to_fix": self.how_to_fix}


def write_reading(point: str, *, state: str, code: str, where: str,
            detail: str = "", how_to_fix: str = "") -> WriteReading:
    """构造一条读数；空格 / 词表外的状态直接抛（写点不该随手造一个状态）。"""
    if state not in STATES:
        raise ValueError(f"读数状态必须是 {STATES} 之一，收到 {state!r}")
    if not str(point or "").strip():
        raise ValueError("读数必须点名是哪个写点（point 为空）")
    if not str(code or "").strip():
        raise ValueError("读数必须带一个受控理由码（code 为空）")
    return WriteReading(str(point), state, str(code), str(where or ""),
                   str(detail or ""), str(how_to_fix or ""))


def refused(point: str, *, code: str, where: str, detail: str = "",
            how_to_fix: str = "") -> WriteReading:
    """写点拒了这一份输入（一个字节都没按它写下去）。"""
    return write_reading(point, state=REFUSED, code=code, where=where,
                   detail=detail, how_to_fix=how_to_fix)


def derived(point: str, *, code: str, where: str, detail: str = "",
            how_to_fix: str = "") -> WriteReading:
    """写点在同一处补了一个值（补值只许发生在写点）。"""
    return write_reading(point, state=DERIVED, code=code, where=where,
                   detail=detail, how_to_fix=how_to_fix)


def unchecked(point: str, *, code: str, where: str, detail: str = "",
              how_to_fix: str = "") -> WriteReading:
    """这一格没查成（不是"查过了没问题"）。"""
    return write_reading(point, state=UNCHECKED, code=code, where=where,
                   detail=detail, how_to_fix=how_to_fix)


def readings_path(root: Any) -> Path:
    """台账路径（只算路径，不建目录）。"""
    return Path(str(root)).joinpath(*LEDGER_DIR, LEDGER_NAME)


def record_reading(root: Any, one: Reading) -> tuple[dict, str]:
    """追加一条读数；返回 `(行, 问题)`。问题非空 = 没记成（不抛）。

    为什么写不成就返回问题而不是抛：这一步是留痕，不是判据。一个因为磁盘只读抛出
    的异常会把"这一笔本来按什么处置"整个换掉 —— 而处置已经发生了。调用方拿到的
    问题串必须带进它自己的读数里（与 `artifacts.record_or_problem` 同一纪律）。
    """
    row = one.as_dict()
    path = readings_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                default=str) + "\n")
    except OSError as exc:
        return {}, f"写点读数没记成（{type(exc).__name__}: {exc}）"
    return row, ""


def read_readings(root: Any) -> tuple[list[dict], list[str], str]:
    """读台账；返回 `(行, 坏行说明, 状态)`。

    状态四档：`ok`（读到了若干行）/ `empty`（文件不存在 = 这一趟没有写点判据落过痕迹，
    是"没有"，不是"没查成"）/ `malformed`（有坏行，好行照给）/ `unreadable`
    （文件在但读不出来 —— 这一档绝不折成 empty 或 ok）。
    """
    path = readings_path(root)
    if not path.is_file():
        return ([], [], "empty")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ([], [f"读不出来（{type(exc).__name__}: {exc}）"], "unreadable")
    rows: list[dict] = []
    bad: list[str] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            bad.append(f"第 {n} 行不是合法 JSON（{exc.msg}）")
            continue
        if not isinstance(obj, Mapping):
            bad.append(f"第 {n} 行不是对象")
            continue
        missing = [k for k in ("point", "state", "code") if not str(obj.get(k) or "").strip()]
        if missing:
            bad.append(f"第 {n} 行缺 {missing}")
            continue
        if str(obj.get("state")) not in STATES:
            bad.append(f"第 {n} 行的 state 读到 {obj.get('state')!r}，不在 {STATES} 里")
            continue
        rows.append(dict(obj))
    return (rows, bad, "malformed" if bad else "ok")


def readings_summary(root: Any) -> dict:
    """台账汇总：条数 / 四态计数 / 理由码计数 / 三态。

    `checked=False` 只在读不出来时为真：坏行不算"没查成"（好行仍然数过），
    但坏行逐条列在 `problems` 里 —— 与 `artifacts.summarize` 同一手法。
    """
    rows, bad, state = read_readings(root)
    by_state: dict[str, int] = {}
    by_code: dict[str, int] = {}
    for row in rows:
        st = str(row.get("state") or "")
        by_state[st] = by_state.get(st, 0) + 1
        code = str(row.get("code") or "")
        by_code[code] = by_code.get(code, 0) + 1
    return {
        "checked": state != "unreadable",
        "state": state,
        "entries": len(rows),
        "by_state": dict(sorted(by_state.items())),
        "by_code": dict(sorted(by_code.items())),
        "problems": list(bad),
    }
