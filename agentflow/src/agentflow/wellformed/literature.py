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


def _normalized(rel: str) -> str:
    """`path` 的形态判据输入：与 `litread._normalized` / `store.library_path` 同一套归一。"""
    text = str(rel or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def _landing_verdict(rel: str, library: Path) -> str:
    """`path` 的落点判词：`layout.CANONICAL` / `layout.LEGACY` / `""`（判不了）。

    这一条回答的是"文献的 `path` 是规范形态、历史形态，还是判不了"，与
    `layout.layout_of` 不是同一个问题（后者管 `reports/` / `documents/` /
    `manuscripts/` / `work/` 四个受管目录，`library/` 对它一律 `unrelated`）。

    形态分类只有一份（`litread.path_shape`，与 `store.library_path` 同一套判据）：

    * `<6位号>/<名>` ⇒ `CANONICAL`（2026-11-25 业主裁定的规范形态）；
    * `<4位号>/<名>` ⇒ `LEGACY`（p9 那批 4 位号时代的老盘）；
    * 一位扁平名（含 `<内容 hash 前缀>-<名>`）⇒ `LEGACY`（B2a 的落点，已退役）。

    必须先 `is_file()`：文件不在是"判不了"（由 `path_on_disk` 的 warning 管），
    不是"历史形态" —— 三态纪律：没查成不等于查过没问题。
    """
    shape = LR.path_shape(rel)
    if shape in (LR.SHAPE_UNJUDGED, LR.SHAPE_BAD):
        return ""
    text = _normalized(rel)
    if not text or not (library / text).is_file():
        return ""
    return _LAYOUT.CANONICAL if shape == LR.SHAPE_ENTRY else _LAYOUT.LEGACY


@_rule("literature", "layout")
def _rule_lit_layout(ctx: _Ctx) -> list[Finding]:
    """`literature.path` 的落点形态：规范 `ok` / 历史形态 `legacy` / 判不了不报。

    ## 三次裁定的叠层（这就是为什么这一条有三态）

    1. 2026-09 的最初设计：`library/<lit_id>/<名>`（每条文献一个目录）；
    2. 2026-11-22 的 B2a（落地在 commit `b5175d00`，2026-11-23）：扁平
       `<内容 hash 前缀>-<名>`，把 `<id>/<名>` 报成 `error`；
    3. 2026-11-25 业主裁定：`<6位号>/<名>` 回归正确形态，推翻 B2a。

    新裁定要求"旧数据读得通、但不许再写"，所以形态读数分三档而不是两档：

    * `<6位号>/<名>` ⇒ 不报（`ok`）；
    * `<4位号>/<名>` ⇒ `legacy`（p9 那批老盘，读得通、新写不产出）；
    * 一位扁平名 ⇒ `legacy`（B2a 的落点，自 2026-11-25 起退役）；
    * 其余形状 ⇒ 这里不报（由 `path_on_disk` 的 warning 或 `store.library_path`
      的受控拒去说），因为"文件不在 / 形状非法"不是"历史形态"。

    `legacy` 不是 `error`：真实盘上有 lp-ball-15/22 这类历史数据，报 error 会让
    旧工作区整片变红；但 legacy 也不许静默 —— 它逐条进读数，并写明"新写不产出"。
    """
    out: list[Finding] = []
    if ctx.root is None:
        raise _Unchecked("没有工作区根，`path` 的落点形态查不了")
    library = ctx.root / "library"
    for n, row in ctx.rows:
        raw = str(row.get("path") or "").strip()
        if not raw:
            continue
        if _landing_verdict(raw, library) != _LAYOUT.LEGACY:
            continue
        note = LR.legacy_note(raw) or "遗留形态（读得通、新写不产出）"
        out.append(_local_finding(
            ctx, "literature_layout_legacy",
            f"{note}：`path` 读到 {_shown(raw)}。规范形态是 `<6位号>/<名>`"
            "（`locallib.library_landing_name`，2026-11-25 业主裁定）；"
            "这一行不在这里搬（搬动会打断已建立的引文定位），下一次被新写替换时自然迁移。",
            row_no=n, field_name="path", severity=_LAYOUT.LEGACY_SEVERITY))
    return out


@_rule("literature", "path_on_disk")
def _rule_lit_path_on_disk(ctx: _Ctx) -> list[Finding]:
    """登记了 `path` 就要在盘上找得到（唯一基准：`library/`）。

    只走 `litread.resolve_literature_path`（与 `store.library_path` 同一套形态判据、
    同一句拒词，见 `tests/test_litread_and_library_path_give_the_same_answer.py`）：

    * 规范形态或历史形态、文件在 ⇒ 不报（历史形态由 `_rule_lit_layout` 报 legacy）；
    * 文件不在 ⇒ `literature_path_missing`（warning）；
    * 历史形态且文件真在 ⇒ 这里不报（形态归 layout；两边都报会让同一行既有 legacy
      读数、又有"读不到"的 warning，互相冒充）；
    * 形状非法（带斜杠而首段不是 2–6 位数字 / 段数不对 / 带 `library/` 前缀）⇒
      warning，detail 点名"扁平落点已退役、规范是 `<6位号>/<名>`"；
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
        if _landing_verdict(rel, library) == _LAYOUT.LEGACY:
            # 历史形态、文件真在盘上：形态由 `literature_layout_legacy` 报（legacy）。
            continue
        why = ""
        if LR.RETIRED_LAYOUT_NOTE in res.reason:
            why = ("（这个写法既不是 `<6位号>/<名>`，也不是可读的历史形态 ⇒ "
                   "扁平落点自 2026-11-25 起退役、新写回归 `<6位号>/<名>`）")
        elif "越出" in res.reason:
            why = ("（这个写法越出 `library/`：唯一基准是 `library/<6位号>/<名>`，"
                   "工作区外的文件不算这一行的全文）")
        out.append(_local_finding(
            ctx, "literature_path_missing",
            f"`path` 读到 {_shown(rel)}，而按唯一基准 `library/` 解析不到这一份{why} ⇒ "
            "登记了位置却找不到内容；要么补回文件，要么把 path 置空并写清为什么没有全文",
            row_no=n, field_name="path", severity="warning"))
    return out


#: 二进制原件（正文不在它里面，抽出来的正文是另一份文件）。
_BINARY_SUFFIXES: tuple[str, ...] = (".pdf", ".html", ".htm")


@_rule("literature", "fulltext_on_disk")
def _rule_lit_fulltext_on_disk(ctx: _Ctx) -> list[Finding]:
    """`download.fulltext=ok` 就要在盘上找得到那份抽读件（与原件同目录、同 stem）。

    ## 为什么这条规则存在（2026-11-25 LIBRARY-SHAPE）

    真机 `demo/lp-ball-22` 的读数：25 行的 `download.fulltext` 全是 `ok`，而
    `library/` 里只有 4 份抽读件，其余 21 行的原件是 PDF。于是"这一行有可读正文"
    这句话在书架上是查不到的：`fs.read` 读 PDF 会拒（二进制），想读正文的人只能再抽一次。
    这不是路径错（`path` 都在），是声明与盘面不一致。

    ## 判据（三态：判不了不折成 ok）

    * 行上没有 `fulltext`、或不是 `ok` ⇒ 不管（"没抽过"由 `tier_of_literature` 那一档报）；
    * `path` 解析不到盘上 ⇒ 不管（`path_on_disk` 已经报了；两条同时报会让同一行既有
      "文件不在"、又有"抽读件不在"，读数互相冒充）；
    * `path` 指向的本身就是文本（`.txt` / `.md` …）⇒ 不报：那一份就是正文；
    * `path` 指向二进制原件（PDF / HTML）而它的抽读件（`litread.text_rel`：同目录、
      同 stem、`.txt`）不在 ⇒ 报 `warning`，detail 点名缺的是哪一份、两条出路。

    为什么是 `warning` 而不是 `error`：这一条不否定"原件在、能抽"，它只否定"已经抽好并
    可读"这句话；但 `warning` 在 `states.state_of`（`wellformed/states.py`）里同样把这一类翻成 `malformed` ——
    声明与盘面矛盾这件事不许静默。
    """
    out: list[Finding] = []
    if ctx.root is None:
        raise _Unchecked("没有工作区根，`download.fulltext` 与盘上抽读件对不了")
    library = ctx.root / "library"
    for n, row in ctx.rows:
        dl = row.get("download")
        if not isinstance(dl, Mapping):
            continue
        if str(dl.get("fulltext") or "") != LR.FULLTEXT_OK:
            continue
        raw = str(row.get("path") or "").strip()
        if not raw:
            continue
        res = LR.resolve_literature_path(ctx.root, library, raw)
        if not res.found or res.path is None:
            continue
        if res.path.suffix.casefold() not in _BINARY_SUFFIXES:
            continue
        text_rel = LR.text_rel(raw)
        if text_rel and (library / text_rel).is_file():
            continue
        out.append(_local_finding(
            ctx, "literature_fulltext_missing",
            f"`download.fulltext`='ok' 而抽读件 `library/{text_rel}` 不在盘上 ⇒ "
            f"这一行说「有可读正文」，书架里却只有二进制原件 {_shown(raw)}；"
            "两条出路：让 A 跑 `text.extract(path=…, lit_id=…)` 把正文写成那份 `.txt`"
            "（与原件同目录、同 stem），或把 `download.fulltext` 改成实档"
            "（还没抽就删掉这一格，别写 `ok`）",
            row_no=n, field_name="download.fulltext", severity="warning"))
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
