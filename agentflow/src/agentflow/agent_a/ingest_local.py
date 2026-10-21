"""角色 A 的动作 `ingest_local`（`draft/37` §46）：把盘上已有的外部文件登记成文献行。

为什么需要（`draft/37` §44 那趟真机读数逼出来的，不是设计洁癖）：A 的动作表里没有
`search.register` / `search.ingest_local`，而 B 的动作表只有"处理已存在的 literature 行" ——
工具层通（`search.ingest_local` 是 A 的工具）、编排层不通，于是盘上有论文、台账里没有它，
后面每一跳（B 登记命题 → G 建我方稿件 → H 审）全部因为没有 `lit_id` 而落空。

一份口径，不是两份：与工具同调 `locallib.ingest_directory` —— 判重键（内容 sha256）、provenance
三件事（`actor="agent-A"` / `submitted_by="unknown"` / `origin_note="由 agent-A 从一个本地目录登记"`）
与幂等语义全部来自那一份实现；判据 `tests/test_intake_actions.py::`
`test_the_action_and_the_tool_agree_on_provenance_and_idempotence` 钉住"两者对同一个目录给出同一份读数"。

它不假装能做的事：不支持的扩展名不会被硬塞进来（`.tex` 今天在 `extract` 的支持面之外：`main.tex`
落 `UnsupportedFormat`、`counts.unreadable=1`、零写入）——`unreadable` 非零是"这份没登记成"，
而 `ingested=0` 且 `unreadable=0` 是"这个 pattern 一个文件都没匹配上"，两件事必须分得开；
一篇论文的可读载体通常是 PDF（有文本层时 `has_text_layer=true`、`pages` 照实数记）。
不联网：这个动作的外部轴是 `none`（与 `run_once` / `search_literature` 的 `egress` 不同）。
"""
from __future__ import annotations

from ._support import Path
from ..refusals import refuse

#: 与 `tools/search_tools.py::_h_ingest_local` 逐字相同的 provenance 三件事。
#:
#: 为什么写在这里而不是各写一遍：这三句话回答的是"这篇文献从哪来"，
#: 借 `human` 会把那条链说成假话（`draft/28` §191）。两处口径不一致时，
#: 读台账的人无法判断哪一份才是真的 —— 所以判据会把它们逐字比一次。
INGEST_ACTOR = "agent-A"
INGEST_SUBMITTED_BY = "unknown"
INGEST_ORIGIN_NOTE = "由 agent-A 从一个本地目录登记"

#: 与工具同一条 provenance 说明（两处逐字相同；理由同上）。
INGEST_PROVENANCE_NOTE = "A 不是检索请求的提交方；这条链如实写「谁登记的」"

class _IngestLocal:
    def ingest_local(self, *, books_dir: str, pattern: str = "*.pdf",
                     limit: int | None = None, max_bytes: int = 25165824,
                     dry_run: bool = False) -> dict:
        """把一个本地目录里的文件登记进书架（按内容 sha256 幂等；不联网）。

        返回的键与工具 `search.ingest_local` 逐字一致（`test_tools_branch_key_sets.py` 那条纪律：
        成功支的键表要静态可见），另加两件本动作特有的读数：`literature_ids`（这次登记成的行，
        `already_present` 的也在里面 —— 幂等命中同样是"这篇文献在台账里"）与 `resolved`（真正去读
        的那个目录，相对路径会解析成工作区下的绝对路径）。
        三态纪律：`ok=True` 只表示这次调用做完了；有没有东西进来要看 `ingested` / `already_present` /
        `unreadable` 三个计数，不许把 `ok` 当"登记成功"。三处拒绝走 :func:`agentflow.refusals.refuse`
        （`draft/37` §88）：空目录名 / 目录不在 / 登记抛异常 —— 它们都是"这次调用本身不成立"，
        所以带受控的 `refusal_reason`；否则主控的台账会把它们记成 `ok`。
        """
        raw = str(books_dir or "").strip()
        if not raw:
            # 空目录名不是"没有书"，是这次调用没说清要读哪里 —— 零写入，如实报。
            return refuse("bad_books_dir",
                          "books_dir 不能为空（空目录名让这次登记无从做起）")
        root = Path(getattr(self.store, "root", ".")).resolve()
        base = Path(raw)
        target = base if base.is_absolute() else (root / base)
        if not target.is_dir():
            return refuse("dir_not_found",
                          f"目录不在盘上：{target}（零写入 —— 这不是「目录里没有书」）",
                          books_dir=raw, resolved=str(target))

        from ..locallib import ingest_directory

        try:
            report = ingest_directory(
                self.store, target, limit=limit, pattern=str(pattern or "*.pdf"),
                max_bytes=int(max_bytes), dry_run=bool(dry_run),
                note=f"agent-A 登记本地文献目录（{target}）",
                actor=INGEST_ACTOR, submitted_by=INGEST_SUBMITTED_BY,
                origin_note=INGEST_ORIGIN_NOTE,
            )
        except Exception as exc:  # noqa: BLE001 —— 登记没做成如实报，不编"登记成功"
            return refuse("io_error", f"登记没做成：{type(exc).__name__}: {exc}",
                          resolved=str(target))

        data = report.to_dict()
        counts = dict(data.get("counts") or {})
        books = list(data.get("books") or [])
        literature_ids = [str(b.get("lit_id")) for b in books if b.get("lit_id")]
        ingested = int(counts.get("ingested") or 0)
        already = int(counts.get("already_present") or 0)
        unreadable = int(counts.get("unreadable") or 0)
        skipped = int(counts.get("skipped_limit") or 0) + int(counts.get("skipped_too_large") or 0)
        if ingested or already:
            kind = ""
        elif unreadable:
            kind = "unsupported_format"
        elif skipped:
            kind = "skipped_by_limits"
        else:
            kind = "nothing_matched"
        return {
            "ok": True, "kind": kind,
            "resolved": str(target),
            "root": data.get("root"), "dry_run": bool(data.get("dry_run")),
            "limit": data.get("limit"), "books": books, "count": len(books),
            "ingested": ingested, "already_present": already,
            "skipped": skipped, "unreadable": unreadable,
            "text_layer_ok": int(data.get("text_layer_ok") or 0),
            "pages_total": int(data.get("pages_total") or 0),
            "literature_ids": literature_ids,
            "provenance": {"actor": INGEST_ACTOR, "submitted_by": INGEST_SUBMITTED_BY,
                           "origin_note": INGEST_ORIGIN_NOTE,
                           "note": INGEST_PROVENANCE_NOTE},
            "note": ("`ok` 只说这次调用做完了：有没有东西进台账看 ingested / already_present / "
                     "unreadable 三个计数。unreadable>0 是「这份没登记成」（例如 .tex 不在支持面内），"
                     "ingested=0 且 unreadable=0 才是「这个 pattern 没匹配上文件」。"),
        }
