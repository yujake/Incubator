"""角色 A 的「落点回执」：字节已经在库、又下一份"为什么没落"必须说得出来。

## 为什么单独一个模块（而不是塞进 `run_once.py`）

2026-11-26 LANDINGIDENT 现场：`run_once` 的补下载分支给一条已经有字节的
`literature` 行又下了一份，盘上多出第二份 217,352 B 的 PDF（sha256 与既有那份全等）
和一份 2 020 B 的 WAF 页，而行上的 `path` / `download` 一个字没动、事件流里只有两条
`dup_by:` ⇒ "下过什么、从哪个 URL 下、为什么没落"事后全部不可复算。

判据本身（内容 sha 优先的落点身份、非文献页不进 `<文献号>/`）在
`locallib.library_landing` 与 `agent_a.core._attach_staged`；留痕这三件放在这里，
只因为 `agent_a/run_once.py` 已经贴着 `src_files_gt800_lines` 的 800 行软基线 ——
往它身上加 100 行会把"三格"顶出去。与 `agent_b/proof_receipt.py` 同一个做法：
一个概念一份回执，回执形状只写一处（三处分支都读它）。

本模块只做三件事：判定"这一行还缺字节吗"、把"拒绝再落"写成事件字段、把
`_attach_staged` 的落点回执转成事件。它不写任何表、不改任何行。
"""
from __future__ import annotations

from ._support import ARunResult, Any, Path


def _landing_allowed(existing: dict) -> bool:
    """这一行还缺字节吗：缺 ⇒ 准落（补下载），不缺 ⇒ 不许落第二份。

    判据只有一处（这里），因为它是"能不能落"与"要不要回填 `path`"两个问题共用的同一条
    事实：`path` 非空且 `download.status == "ok"` = 这一行已经有可用字节。

    为什么它得是一个单独的函数：改前这条判据只用来算 `backfilled`，搬文件那一步照样
    执行 —— "有字节的行再下一份就落成孤儿"。把它提出来之后，"不许落"这件事有名字、
    可被打桩（判据的反真空就打在它上面：桩成恒 True ⇒ 回到改前形态）。
    """
    old_dl = existing.get("download") or {}
    return (not existing.get("path")) or str(old_dl.get("status")) != "ok"


def _duplicate_download_receipt(store: Any, *, request_id: str, slot: str,
                               existing: dict, dl: dict) -> dict | None:
    """「字节已在库、又下一份」这条拒绝的留痕：谁、什么 URL、写到哪、为什么。

    ## 为什么要一条事件，而不是"不落就算了"

    真机 2026-11-25 21:23:46/48 的现场是：给一条已经有字节的行又下了两份，因为那里只判了
    "要不要回填 `path`"，搬文件那一步照样执行 ⇒ 盘上多两份、行上不留痕。于是"下过什么、
    从哪个 URL 下、为什么没落"全部不可复算 —— 事后只能靠 sha 撞运气。

    ## 返回什么

    `None` = 这一趟没有字节可谈（下载是 `skipped`：没有 PDF URL / 预算用尽），那一档
    不是"又下一份"，不许伪造一条"重复下载"回执（三态纪律：没下 ≠ 下了没落，两者处置
    完全不同 —— 前者去查 URL，后者去查落点判据）。否则返回事件字段：谁（`tx.info` 的
    actor 给）、什么 URL、现算的 sha256、字节数、落到哪（`wrote_to=None` = 本次零写入）、
    为什么，以及既有那一份的 path / sha（能当场回答"是不是同一份字节"）。
    """
    from ..locallib import sha256_file

    status = str((dl or {}).get("status") or "")
    if status not in ("ok", "content_mismatch"):
        return None
    staged = str((dl or {}).get("_staged_path") or "").strip()
    sha = str((dl or {}).get("sha256") or "").strip().lower() or None
    size: int | None = None
    staged_name: str | None = Path(staged).name if staged else None
    if staged:
        try:
            size = Path(staged).stat().st_size
            sha = sha256_file(Path(staged))   # 现算，不信下载器自述
        except OSError:                       # staged 已被清掉/读不到：如实留 None，不编数
            size = None
    existing_rel = str(existing.get("path") or "")
    existing_sha: str | None = None
    if existing_rel:
        try:
            existing_sha = sha256_file(Path(store.library) / existing_rel)
        except OSError:
            existing_sha = str((existing.get("download") or {}).get("sha256") or "") or None
    return {
        "where": "agent_a.run_once",
        "request_id": request_id,
        "slot": str(slot),
        "lit_id": str(existing.get("lit_id") or ""),
        "status": status,
        "url": (dl or {}).get("url"),
        "sha256": sha,
        "bytes": size,
        "staged_name": staged_name,
        "wrote_to": None,
        "existing_path": existing_rel or None,
        "existing_sha256": existing_sha,
        "same_bytes": bool(sha and existing_sha and sha == existing_sha),
        "why": ("这一行已经有可用字节（path 非空且 download.status=ok）⇒ 再落一份就是"
                "没有任何 literature 行指到的孤儿；本次下载的字节随 staging 一起丢弃"),
    }


def _note_landing_receipt(tx: Any, result: ARunResult, request_id: str, slot: str,
                         lit_id: str, dl: dict) -> None:
    """把 `_attach_staged` 的落点回执转成事件（三种"字节已在库 / 不在文献目录"的事实）。

    三条事件都不改任何行（行上的账由各自分支写，避免两处同时写同一格）：

    * `reused` —— 同一份字节已经在这个文献号目录里 ⇒ 本次零写入（落点名由内容定，
      名字差异不再产生第二份文件）；
    * `duplicate_in` —— 同一份字节在别的文献号目录里也有一份（跨号重复：允许，
      但不许静默 —— 两条题录可能真是同一篇，要人看一眼）；
    * `evidence_path` —— 下到的是网页/证据字节（WAF 页、cookie 页、错误体）⇒ 不进
      `library/<文献号>/`，落 `downloads/rejected/` 并在这里点名。
    """
    landing = (dl or {}).get("landing") or {}
    base = {
        "where": "agent_a.run_once",
        "request_id": request_id,
        "slot": str(slot),
        "lit_id": str(lit_id),
        "url": (dl or {}).get("url"),
        "sha256": landing.get("sha256") or (dl or {}).get("sha256"),
    }
    if landing.get("reused"):
        tx.info("download.same_content_already_at", **base,
                rel=landing.get("rel"), wrote_to=None,
                why="同一份字节已经在这个文献号目录里 ⇒ 本次零写入（落点名由内容定）")
        result.landing_reused += 1
    dup_in = list(landing.get("duplicate_in") or [])
    if dup_in:
        tx.info("download.same_bytes_other_entry", **base, duplicate_in=dup_in,
                rel=landing.get("rel"),
                why=("同一份字节在别的文献号目录里也有一份（跨号重复）：本路不拦，"
                     "但两条 literature 行要人看一眼是不是同一篇"))
    evidence = str((dl or {}).get("evidence_path") or "")
    if evidence:
        tx.info("download.evidence_not_literature", **base, evidence_path=evidence,
                wrote_to=evidence,
                why=("下到的是网页/证据字节（WAF 页、cookie 页、错误体）⇒ 不进 "
                     "library/<文献号>/；字节留着，是为了回答『对方到底返回了什么』"))
