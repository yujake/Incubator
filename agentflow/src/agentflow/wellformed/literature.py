# -*- coding: utf-8 -*-
"""
literature 那一类：`data/literature.json` 的号、类型、下载格与去重键。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from .. import litread as LR
from .. import schema as S
from . import layout as _LAYOUT
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


#: 落点名里内容 hash 前缀的长度下限（与 `locallib.LANDING_HASH_CHARS` 同源：12 位）。
#: 这里不 import `locallib`：`wellformed` 是被 `statusreport` 拉起的轻入口，而
#: `locallib` 会连带拉起 extract / store —— 只为认一个下界的耦合不值得。
_LANDING_HASH_MIN = 12

#: 新落点的形状：`<12 位以上小写十六进制内容 hash>-<名>`（一段、扁平）。
_NEW_LANDING_RE = re.compile(r"^[0-9a-f]{%d,64}-" % _LANDING_HASH_MIN)


def _landing_verdict(rel: str, library: Path) -> str:
    """`path` 的落点判词：`layout.CANONICAL` / `layout.UNSUPPORTED` / `""`（判不了）。

    这是另一个问题，不是第二份 `layout.layout_of`：那个分类器回答"这一份文件落在
    哪个受管的一级目录（`reports/` / `documents/` / `manuscripts/` / `work/`）、合不合
    规范"，`library/` 不在它管的那四个目录里（`layout_of("library/…")` 一律
    `unrelated`）。这里回答的是"文献的 `path` 是旧落点还是新落点"，而且必须先
    `is_file()` —— 文件不在是"判不了"，不是"旧布局"。

    共用的只有判词与严重度那三格（`layout.CANONICAL` / `layout.UNSUPPORTED` /
    `layout.UNSUPPORTED_SEVERITY`）：它们从 `layout.py` 取，不在这里另写一份
    "旧布局算不算畸形"（业主 2026-11-22 裁定：旧工作区不必兼容）。

    判定只看盘上真有一份文件的那几种形态（`is_file()`）：

    * 一个路径段、且以内容 hash 前缀开头 ⇒ `CANONICAL`（`<hash>-<名>.pdf`，新写唯一形态）；
    * 一个路径段、没有 hash 前缀 ⇒ `UNSUPPORTED`（`locallib` 2026-09 起的裸扁平落点）；
    * 两个路径段、首段是六位（或老盘四位）文献号 ⇒ `UNSUPPORTED`（`<lit_id>/<名>`，
      `_adopt_file` 的旧落点）。

    读不到文件 ⇒ `""`：形态判不了是"文件不在"那件事（`path_on_disk` 的 warning
    在管），不许在这里折成 `UNSUPPORTED` 或 `CANONICAL` —— 三态纪律：没查成不等于查过
    没问题。其余形状（`downloads/x.pdf` 这种工作区坐标系、多层的目录）也一律 `""`：
    这一条只认"相对 library/ 的落点"，别的坐标系归别的判据。
    """
    text = str(rel or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    if text.startswith(S.LIT_PATH_PREFIX):
        # 旧工作区里还有"多带一层 library/"的历史写法（读侧 `store.library_path`
        # 同样剥这一层）：判形态时剥掉，否则整条会被读成 `""` 而永远不进读数。
        text = text[len(S.LIT_PATH_PREFIX):]
    parts = [p for p in text.split("/") if p]
    if not parts or not (library / text).is_file():
        return ""
    if len(parts) == 1:
        return _LAYOUT.CANONICAL if _NEW_LANDING_RE.match(parts[0]) else _LAYOUT.UNSUPPORTED
    if len(parts) == 2 and _ID6_OR_4.match(parts[0]):
        return _LAYOUT.UNSUPPORTED
    return ""


@_rule("literature", "layout")
def _rule_lit_layout(ctx: _Ctx) -> list[Finding]:
    """`literature.path` 的落点形态：旧布局（不再支持）报 `error`。

    ## 为什么这条规则存在（`draft/195` #7 / #17 / #18 / #51）

    `library/` 曾有三个写者、两套布局（`_adopt_file` 写 `<lit_id>/<名>`、`locallib`
    写裸扁平 `<名>`、`seedinject` 曾铺根）。读侧 `store.library_path` 只做拼接 ⇒ 两套
    都读得通，于是盘上两套并存而没有一条判据会报（真机 lp-ball-13 的 4 份 `<id>/`、
    lp-ball-15 顶层 24 份 `<hash>-名` + 1 个 `<id>/` 子目录；project1/4 一类老工作区
    则是 `locallib` 的裸扁平名）。B2a 之后写侧只剩一个落点（`<hash>-名` 扁平）。

    ## 旧布局现在报什么（业主 2026-11-22 裁定「旧工作区不必兼容」）

    改前这一条给旧布局一档 `severity=legacy`（读得通、不改三态、退出码 0）。裁定之后
    那一档取消：旧布局（`library/<lit_id>/<名>` 与裸扁平 `<名>`）现在报 `error`、把
    `literature` 这一类翻成 `malformed`、整份读数退出码 1 —— 与 `layout.py` 对
    `reports/` 一类的口径同一条（严重度共用 `layout.UNSUPPORTED_SEVERITY`，宽不宽容
    只有那一格说了算）。逐条列在输出里：不许静默当 ok、不许折成空。
    """
    out: list[Finding] = []
    if ctx.root is None:
        raise _Unchecked("没有工作区根，`path` 的落点形态查不了")
    library = ctx.root / "library"
    for n, row in ctx.rows:
        raw = str(row.get("path") or "").strip()
        if not raw:
            continue
        if _landing_verdict(raw, library) != _LAYOUT.UNSUPPORTED:
            continue
        out.append(_local_finding(
            ctx, "literature_layout_legacy",
            f"旧布局（不再支持）：`path` 读到 {_shown(raw)} —— 这是旧落点"
            "（`library/<lit_id>/<名>` 或裸扁平 `<名>`），业主 2026-11-22 裁定"
            "「旧工作区不必兼容」⇒ 不再按「读得通的历史形态」放行。新写一律扁平 "
            "`library/<内容 hash 前缀-名>`（`locallib.library_landing_name`）；"
            "这一行不在这里搬（搬动会打断已建立的引文定位），下一次被新写替换时"
            "自然迁移。",
            row_no=n, field_name="path", severity=_LAYOUT.UNSUPPORTED_SEVERITY))
    return out


@_rule("literature", "path_on_disk")
def _rule_lit_path_on_disk(ctx: _Ctx) -> list[Finding]:
    """登记了 `path` 就要在盘上找得到（唯一基准：`library/`，两基准已删）。

    ## 改前的两基准（2026-11-22 业主裁定「旧工作区不必兼容」后删掉）

    改前这里是 `tried = [root/library/rel, root/rel]`：两个基准`any(is_file())`，
    任一个探到就算"在盘上"。它比 `store.library_path` 宽 —— 同一份
    `literature.path`，写侧/工具面说"旧布局（不再支持）"，`wellformed` 却说
    "在盘上、没问题"。第二基准只服务过旧前缀/工作区形态，裁定之后整段不要。

    现在只走 `litread.resolve_literature_path`（与 `store.library_path` 同一套形态
    判据、同一句拒词，见 `tests/test_litread_and_library_path_give_the_same_answer.py`）：

    * 扁平形态、文件在 ⇒ 不报（正控）；
    * 扁平形态、文件不在 ⇒ `literature_path_missing`（warning）；
    * 旧布局且旧形态的那一份真在盘上 ⇒ 这里不报 —— 形态归 `_rule_lit_layout`
      的 `literature_layout_legacy`（`error`）。两边都报会让同一行既有"文件在"的
      `error`、又有"读不到"的 `warning`，读数自相矛盾；
    * 旧布局而那一份也不在 ⇒ `literature_path_missing`（形态规则判不了"文件不在"
      这件事，三态纪律：没查成不许折成"没问题"，否则"文件丢了"会永远藏在"旧形态"后面）；
    * 越界（`../` / 绝对路径绕出 `library/`）⇒ 同一档 warning，detail 点名越界。
    """
    out: list[Finding] = []
    if ctx.root is None:
        raise _Unchecked("没有工作区根，`path` 指的文件在不在盘上查不了")
    library = ctx.root / "library"
    for n, row in ctx.rows:
        raw = row.get("path")
        if not str(raw or "").strip():
            continue
        rel = str(raw)
        res = LR.resolve_literature_path(ctx.root, library, rel)
        if res.found:
            continue
        if _landing_verdict(rel, library) == _LAYOUT.UNSUPPORTED:
            # 旧形态、文件真在盘上：形态由 `literature_layout_legacy` 报（error）。
            continue
        why = ""
        if LR.OLD_LAYOUT_NOTE in res.reason:
            why = ("（这一行的 `path` 是旧布局（不再支持），而旧形态的那一份也不在盘上 ⇒ "
                   "「路径写旧了」与「文件不见了」两件事同时成立）")
        elif "越出" in res.reason:
            why = ("（这个写法越出 `library/`：唯一基准是 `library/<扁平名>`，"
                   "工作区外的文件不算这一行的全文）")
        out.append(_local_finding(
            ctx, "literature_path_missing",
            f"`path` 读到 {_shown(rel)}，而按唯一基准 `library/` 解析不到这一份{why} ⇒ "
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
