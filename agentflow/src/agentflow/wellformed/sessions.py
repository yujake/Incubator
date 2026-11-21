# -*- coding: utf-8 -*-
"""
sessions 那一类：`sessions/*.jsonl` 的坏行、事件格与事件流顺序。
"""

from __future__ import annotations

from typing import Mapping

from .predicates import _is_int, _is_iso, _shown
from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- sessions：`sessions/*.jsonl`


@_rule("sessions", "lines")
def _rule_sess_lines(ctx: _Ctx) -> list[Finding]:
    """坏行（`jsonlfile` 的口径）逐条报出来。"""
    return [_local_finding(ctx, "session_bad_line", f"坏行：{why}")
            for why in ctx.line_problems]


@_rule("sessions", "fields")
def _rule_sess_fields(ctx: _Ctx) -> list[Finding]:
    """每条事件的 `kind` / `seq` / `ts` 形状。

    `seq` 是可选的：盘上的会话记录（2026-11 实测 7 个工作区）一条都不带它，顺序由文件
    行序表达。带了的才判形状与单调，没带的不是畸形（拿"没有这个字段"当畸形会把整份
    事件流读成 3040 条假读数）。
    """
    out: list[Finding] = []
    for n, ev in ctx.rows:
        kind = ev.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            out.append(_local_finding(
                ctx, "session_kind", f"`kind` 读到 {_shown(kind)}，应为非空字符串",
                row_no=n, field_name="kind"))
        if "seq" in ev and not _is_int(ev.get("seq")):
            out.append(_local_finding(
                ctx, "session_seq_shape",
                f"`seq` 读到 {_shown(ev.get('seq'))}，应为整数", row_no=n, field_name="seq"))
        if not _is_iso(ev.get("ts")):
            out.append(_local_finding(
                ctx, "session_ts_shape",
                f"`ts` 读到 {_shown(ev.get('ts'))}，不是可解析的 ISO 时刻",
                row_no=n, field_name="ts", severity="warning"))
    return out


@_rule("sessions", "order")
def _rule_sess_order(ctx: _Ctx) -> list[Finding]:
    """`seq` 严格递增；`ts` 不许倒序。"""
    out: list[Finding] = []
    last_seq: tuple[int, int] | None = None
    last_ts: tuple[str, int] | None = None
    for n, ev in ctx.rows:
        seq = ev.get("seq")
        if _is_int(seq):
            if last_seq is not None and seq <= last_seq[0]:
                out.append(_local_finding(
                    ctx, "session_seq_not_increasing",
                    f"`seq`={seq} 不大于上一行的 {last_seq[0]}（第 {last_seq[1]} 行）"
                    "⇒ 事件流的顺序坏了", row_no=n, field_name="seq"))
            last_seq = (seq, n)
        ts = ev.get("ts")
        if isinstance(ts, str) and _is_iso(ts):
            if last_ts is not None and ts < last_ts[0]:
                out.append(_local_finding(
                    ctx, "session_ts_descending",
                    f"`ts`={ts} 早于上一行的 {last_ts[0]}（第 {last_ts[1]} 行）⇒ 时间倒序",
                    row_no=n, field_name="ts", severity="warning"))
            last_ts = (ts, n)
    return out
