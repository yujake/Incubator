# -*- coding: utf-8 -*-
"""
literature 那一类：`data/literature.json` 的号、类型、下载格与去重键。
"""

from __future__ import annotations

from typing import Mapping

from .. import litread as LR
from .. import schema as S
from .predicates import _ID6_OR_4, _Unchecked, _is_hex64, _is_int, _shown
from .registry import _Ctx, _local_finding, _rule
from .states import Finding


# ---- literature：`data/literature.json`

_LIT_TYPE_VOCAB: tuple[str, ...] = tuple(S.LIT_TYPES)
_DOWNLOAD_CORE: tuple[str, ...] = ("status", "http_status", "bytes", "sha256", "error")


@_rule("literature", "id_shape")
def _rule_lit_id(ctx: _Ctx) -> list[Finding]:
    """`lit_id` 的号形与唯一性。"""
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        lid = str(row.get("lit_id") or "")
        if not _ID6_OR_4.match(lid):
            out.append(_local_finding(
                ctx, "literature_id_shape",
                f"`lit_id` 读到 {_shown(row.get('lit_id'))}，不是六位号（老盘四位号照认）",
                row_no=n, field_name="lit_id"))
        if lid in seen:
            out.append(_local_finding(
                ctx, "literature_duplicate_id",
                f"`lit_id`={lid} 与第 {seen[lid]} 条重复 ⇒ 同一号两条记录，"
                "关系行的 lit_id 指哪一条都说不清", row_no=n, field_name="lit_id"))
        else:
            seen[lid] = n
    return out


@_rule("literature", "type")
def _rule_lit_type(ctx: _Ctx) -> list[Finding]:
    """`type` 必须在 `schema.LIT_TYPES` 里。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        got = row.get("type")
        if got is not None and str(got) not in _LIT_TYPE_VOCAB:
            out.append(_local_finding(
                ctx, "literature_type",
                f"`type` 读到 {_shown(got)}，不在受控词表 {_LIT_TYPE_VOCAB} 里",
                row_no=n, field_name="type", severity="warning"))
    return out


@_rule("literature", "download_shape")
def _rule_lit_download_shape(ctx: _Ctx) -> list[Finding]:
    """`download` 必须是对象且带核心五格（形状可扩展，核心不许缺）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        if "download" not in row:
            out.append(_local_finding(
                ctx, "literature_download_absent",
                "这一条没有 `download` 这一格 ⇒ 「取没取到正文」没有读数",
                row_no=n, field_name="download", severity="warning"))
            continue
        dl = row.get("download")
        if not isinstance(dl, Mapping):
            out.append(_local_finding(
                ctx, "literature_download_shape",
                f"`download` 读到 {_shown(dl)}，应为对象", row_no=n,
                field_name="download"))
            continue
        missing = [k for k in _DOWNLOAD_CORE if k not in dl]
        if missing:
            out.append(_local_finding(
                ctx, "literature_download_shape",
                f"`download` 缺核心格 {missing}（现有键：{sorted(dl)}）⇒ "
                "下游按这些格读「下没下成」，缺一格就只剩猜"
                "（早期登记的 download 只有 status/bytes/sha256/error）", row_no=n,
                field_name="download"))
    return out


@_rule("literature", "download_vocab")
def _rule_lit_download_vocab(ctx: _Ctx) -> list[Finding]:
    """`download.status` 走 `schema.DOWNLOAD_STATUSES`；`fulltext` 走 `litread.FULLTEXT_TIERS`。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        dl = row.get("download")
        if not isinstance(dl, Mapping):
            continue
        st = dl.get("status")
        if st is not None and str(st) not in S.DOWNLOAD_STATUSES:
            out.append(_local_finding(
                ctx, "literature_download_status",
                f"`download.status` 读到 {_shown(st)}，不在 {S.DOWNLOAD_STATUSES} 里",
                row_no=n, field_name="download.status"))
        ft = dl.get("fulltext")
        if ft is not None and str(ft) not in LR.FULLTEXT_TIERS:
            out.append(_local_finding(
                ctx, "literature_fulltext_vocab",
                f"`download.fulltext` 读到 {_shown(ft)}，不在 {LR.FULLTEXT_TIERS} 里"
                "（同一含义在 `litavail` 里是可用性档名，两条词表并存本身就是形状漂移）",
                row_no=n, field_name="download.fulltext", severity="warning"))
    return out


@_rule("literature", "download_consistency")
def _rule_lit_download_consistency(ctx: _Ctx) -> list[Finding]:
    """`download` 内部不许自相矛盾（说下成了就必须有字节、有 sha、有盘上路径）。"""
    out: list[Finding] = []
    for n, row in ctx.rows:
        dl = row.get("download")
        if not isinstance(dl, Mapping):
            continue
        st = str(dl.get("status") or "")
        sha = dl.get("sha256")
        if sha is not None and not _is_hex64(sha):
            out.append(_local_finding(
                ctx, "literature_download_sha",
                f"`download.sha256` 读到 {_shown(sha)}，不是 64 位小写十六进制",
                row_no=n, field_name="download.sha256"))
        b = dl.get("bytes")
        if b is not None and (not _is_int(b) or b < 0):
            out.append(_local_finding(
                ctx, "literature_download_bytes",
                f"`download.bytes` 读到 {_shown(b)}，应为非负整数",
                row_no=n, field_name="download.bytes"))
        if st == "ok":
            if not str(row.get("path") or "").strip():
                out.append(_local_finding(
                    ctx, "literature_ok_without_path",
                    "`download.status=ok` 而 `path` 是空的 ⇒ 说下成了却没有盘上位置",
                    row_no=n, field_name="path"))
            if not _is_hex64(sha):
                out.append(_local_finding(
                    ctx, "literature_ok_without_sha",
                    f"`download.status=ok` 而 `sha256` 读到 {_shown(sha)} ⇒ "
                    "没有内容指纹的「下成了」没法复核", row_no=n, field_name="download.sha256"))
        elif st and str(dl.get("fulltext") or "") == "ok":
            out.append(_local_finding(
                ctx, "literature_fulltext_status_conflict",
                f"`download.status`={st!r} 而 `download.fulltext`='ok' ⇒ "
                "没下成却说有可读正文，两格互相矛盾", row_no=n,
                field_name="download.fulltext"))
    return out


@_rule("literature", "path_on_disk")
def _rule_lit_path_on_disk(ctx: _Ctx) -> list[Finding]:
    """登记了 `path` 就要在盘上找得到（先按 `library/` 解析，老盘再按工作区根解析）。"""
    out: list[Finding] = []
    if ctx.root is None:
        raise _Unchecked("没有工作区根，`path` 指的文件在不在盘上查不了")
    for n, row in ctx.rows:
        raw = row.get("path")
        if not str(raw or "").strip():
            continue
        rel = str(raw)
        tried = [ctx.root / "library" / rel, ctx.root / rel]
        if any(p.is_file() for p in tried):
            continue
        out.append(_local_finding(
            ctx, "literature_path_missing",
            f"`path` 读到 {_shown(rel)}，而 `library/{rel}` 与 `{rel}` 都不是文件 ⇒ "
            "登记了位置却找不到内容；要么补回文件，要么把 path 置空并写清为什么没有全文",
            row_no=n, field_name="path", severity="warning"))
    return out


@_rule("literature", "dedup_key")
def _rule_lit_dedup(ctx: _Ctx) -> list[Finding]:
    """`dedup_key` 非空、出现在 `_keys` 里、且全体唯一。"""
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for n, row in ctx.rows:
        key = str(row.get("dedup_key") or "")
        if not key:
            out.append(_local_finding(
                ctx, "literature_dedup_key_absent",
                "`dedup_key` 是空的 ⇒ 这一条没有去重键，同一篇会被再收一次"
                "（去重键是后来才加的列，老盘的行没有它）",
                row_no=n, field_name="dedup_key", severity="warning"))
            continue
        keys = row.get("_keys")
        if isinstance(keys, list) and key not in [str(k) for k in keys]:
            out.append(_local_finding(
                ctx, "literature_dedup_not_in_keys",
                f"`dedup_key`={key!r} 不在 `_keys`={keys!r} 里 ⇒ 去重键与它的别名表不一致",
                row_no=n, field_name="_keys", severity="warning"))
        if key in seen:
            out.append(_local_finding(
                ctx, "literature_duplicate_dedup_key",
                f"`dedup_key`={key!r} 与第 {seen[key]} 条重复 ⇒ 同一篇文献两条记录",
                row_no=n, field_name="dedup_key"))
        else:
            seen[key] = n
    return out
