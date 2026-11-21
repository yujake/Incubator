# -*- coding: utf-8 -*-
"""
artifacts 那一类：`ARTIFACTS.jsonl` 的登记格、盘上存在性与 sha 对拍。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .. import artifacts as ART
from .predicates import _Unchecked, _is_hex64, _is_iso, _shown
from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- artifacts：`ARTIFACTS.jsonl`


@_rule("artifacts", "lines")
def _rule_art_lines(ctx: _Ctx) -> list[Finding]:
    """坏行逐条报出来。"""
    return [_local_finding(ctx, "artifact_bad_line", f"坏行：{why}")
            for why in ctx.line_problems]


@_rule("artifacts", "fields")
def _rule_art_field_shape(ctx: _Ctx) -> list[Finding]:
    """每条登记的必填格与形状（路径、sha、时刻、生产者）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        rel = row.get("path")
        if not str(rel or "").strip():
            out.append(_local_finding(
                ctx, "artifact_path_absent", "这一条没有 `path` ⇒ 登记没有对象",
                row_no=n, field_name="path"))
        elif Path(str(rel)).is_absolute() or ".." in Path(str(rel)).parts:
            out.append(_local_finding(
                ctx, "artifact_path_escape",
                f"`path` 读到 {_shown(rel)}，不是工作区相对路径",
                row_no=n, field_name="path"))
        if not _is_hex64(row.get("sha256")):
            out.append(_local_finding(
                ctx, "artifact_sha_shape",
                f"`sha256` 读到 {_shown(row.get('sha256'))}，不是 64 位小写十六进制",
                row_no=n, field_name="sha256"))
        if not str(row.get("producer") or "").strip():
            out.append(_local_finding(
                ctx, "artifact_producer",
                "`producer` 是空的 ⇒ 这一件产物没有归属", row_no=n,
                field_name="producer", severity="warning"))
        if not _is_iso(row.get("at")):
            out.append(_local_finding(
                ctx, "artifact_at",
                f"`at` 读到 {_shown(row.get('at'))}，不是可解析的 ISO 时刻",
                row_no=n, field_name="at", severity="warning"))
    return out


@_rule("artifacts", "on_disk")
def _rule_art_on_disk(ctx: _Ctx) -> list[Finding]:
    """登记过的路径要在盘上；每个路径的最后一条登记要与盘上字节的 sha 相等。

    "最后一条之后文件又被改过"（例如手稿后来落了签块）分两档读：能解释的记 `info`
    （稿上现在有 `已签=true` 的签块 —— 签块是登记之后才落的），解释不了的记 `warning`。
    分两档是为了不把"签块落盘"这条正常路径读成畸形，也不把真被改过的内容藏起来。
    """
    out: list[Finding] = []
    if ctx.root is None:
        raise _Unchecked("没有工作区根，路径在不在盘上、sha 对不对都查不了")
    latest: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for n, row in ctx.rows:
        rel = str(row.get("path") or "")
        if rel:
            latest[rel] = (n, row)
    for rel, (n, row) in sorted(latest.items(), key=lambda kv: kv[1][0]):
        target = ctx.root / rel
        if not target.is_file():
            out.append(_local_finding(
                ctx, "artifact_missing",
                f"`path`={rel!r} 登记过，而盘上没有这个文件 ⇒ 产物不在了（或从没写过）",
                row_no=n, field_name="path"))
            continue
        try:
            # 复用 `artifacts.sha256_of`（流式哈希的唯一实现）：登记台账与核对台账
            # 必须用同一把尺，各写一份"读字节算 sha"迟早分家。
            digest = ART.sha256_of(target)
        except OSError as exc:
            raise _Unchecked(f"{rel} 读不出来（{type(exc).__name__}）") from exc
        want = str(row.get("sha256") or "")
        if digest == want:
            continue
        explained = _signed_after_registration(target)
        out.append(_local_finding(
            ctx, "artifact_sha_changed",
            f"最后一条登记（第 {n} 行）说 `{rel}` 的 sha256 是 {want[:12]}…，"
            f"盘上现在是 {digest[:12]}… ⇒ 登记之后文件被改过"
            + ("（可解释：这一份稿上有 `已签=true` 的签块，签块是登记之后落的）"
               if explained else "（没有可解释的原因）"),
            row_no=n, field_name="sha256",
            severity="info" if explained else "warning"))
    return out


def _signed_after_registration(path: Path) -> bool:
    """这份文件是不是"登记之后落了签块"的证明稿（用于解释 ARTIFACTS 的 sha 落后）。"""
    if path.suffix != ".md":
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    from .. import vsigns as VS

    reading = VS.manuscript_sign_reading(text, manuscript_path=path.name)
    return bool(reading.get("found")) and bool(reading.get("signed"))
