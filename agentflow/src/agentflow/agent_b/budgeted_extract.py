"""B 的抽取段（文本 → 概念/关系）：协作式预算、进度读数、续跑游标。

`run_once` 的动作面（claim → 抽取 → 落库 → 标 processed）在 `run_once.py`；这里只放
抽取段那一半，因为它有自己的一组口径，混进动作文件会让那一个文件越过 800 行的
体量软基线（三格 `gt800`）。

## 三段与它们各自的截止（真机 lp-ball-21 的读数）

| 段 | 真机实测 | 加预算之前有没有截止 |
|---|---|---|
| 文本段 `extract_text` | 3.5 MB / 426 页：0.73 秒 | 没有（但实测不是瓶颈） |
| 抽取段 `extractor.extract` | 87 块 × 中位 58.5 秒 ≈ 85 分钟 | 没有（缺陷就在这一段） |
| 落库段 | 与块数同阶的判重/回验 | 不需要（它跟块数线性，且必须原子） |

所以预算主要作用在抽取段的块边界上；文本段给的是一个可选的页数窗口
（`extract_pages_per_call`，缺省 0 = 整篇，与原行为逐字相同），窗口截断时
`stopped_budget` 的 `stage` 写 `text_pages`，并把"已抽到的页"交回。

## 为什么"续跑"只需要一个游标（块号）

`extract_text` 的 `max_pages` 是从第 1 页起的前缀，而 `LLMExtractor._chunk_bodies`
是对同一个前缀的贪心切分 ⇒ 前缀变长时前面的块不变。于是"上一次已处理的块号"
仍然是这一次的同一个块号，不需要第二个游标；被截断那一份的最后一块只含文件的
一部分，`extract(..., doc_complete=False)` 会把它留到下一次（见那里的 docstring）。
"""

from __future__ import annotations

from typing import Any, Mapping

from .. import extractbudget as _EB
from ..extract import page_count as _page_count


def merge_definition(existing: Mapping[str, Any], definition: str, lit_id: str) -> bool:
    """续跑时把同一篇后面那些块带来的定义并进已有那一行。

    为什么必须有这一条（否则"续跑结果 = 一次跑完"不成立）：一次跑完时
    `LLMExtractor._merge_concepts` 在落库之前就把同名跨块定义按块序拼成
    `d1；d2`；被预算切成两段之后，第二段那一条同名概念只能落到"复用已有行"的
    分支上，而那个分支改前只合别名、不碰定义 ⇒ 两片跑完会少半句定义，而两条
    读数看起来都合格。

    合并口径与 `_merge_concepts` 逐字相同（`；` 接上，`extra in merged` 就不动）；
    `definition_source_lit_id` 不是本篇的一概不动 —— 那是另一篇的证据。
    返回"改没改"（改了就由调用方落盘）。
    """
    extra = str(definition or "").strip()
    if not extra:
        return False
    if str(existing.get("definition_source_lit_id") or "") != str(lit_id):
        return False
    merged = str(existing.get("definition") or "")
    if extra in merged:
        return False
    existing["definition"] = f"{merged}；{extra}" if merged else extra
    return True


def resume_cursor(*, stage: str, chunks_done: int, chunks_usable: int,
                  doc_complete: bool, pages: int, pages_total: int | None) -> dict[str, Any]:
    """这一篇的续跑游标（落在 `literature.extract_resume` 上，下一次照着它接）。

    `pages_done` 只在"有页"时才有意义（txt/md/html 的 `page_count` 是 None ⇒ 0）：
    它不是"读了 0 页"，是"这一份没有页"。
    """
    return {
        "chunks_done": int(chunks_done),
        "chunks_usable": int(chunks_usable),
        "pages_done": (int(pages_total or 0) if doc_complete else int(pages)),
        "stage": str(stage),
    }


def mark_unfinished(row: dict[str, Any], *, got: Mapping[str, Any], now: str) -> dict[str, Any]:
    """预算到点那一支对 `literature` 行的全部改动（就地改 `row` 并返回它）。

    三件事一起做，因为它们必须同时成立：不算处理完（`processed=False`）、
    解掉认领（下一次能立刻再领到它）、留续跑游标（从同一块/同一页接着做）。
    `mine_attempts` 刻意不动：预算停止不是"抽了一次失败" —— 87 块的书按 240 秒要
    ~21 片，若每片都烧一次，`max_attempts=3` 会在第 3 片把这一篇判死，而它一次都没
    抽错过（`R3-⑩` 的计数语义是"真抽完一次"）。
    """
    row["processed"] = False
    row["claimed_by"] = None
    row["lease_until"] = None
    row["last_mine_error"] = None
    row["extract_resume"] = dict(
        resume_cursor(stage=str(got.get("stage") or ""),
                      chunks_done=int(got.get("chunks_done") or 0),
                      chunks_usable=int(got.get("chunks_usable") or 0),
                      doc_complete=bool(got.get("doc_complete")),
                      pages=int(got.get("pages") or 0),
                      pages_total=got.get("pages_total")),
        at=str(now))
    return row


class _BudgetedExtract:
    """`run_once` 的抽取段。异常照原样上抛：调用方那一条失败路径一个字没动。"""

    def _run_extraction(self, lit: Mapping[str, Any], lit_id: str, path: Any,
                        res: Any) -> dict[str, Any]:
        """文本段 + 抽取段；读数写进 `res`（`extract_text` / `budget` / `details`）。

        返回 `{"doc","concepts","relations","stopped","stage","chunks_done",
        "chunks_usable","doc_complete","pages_total"}`。
        """
        budget = _EB.make_budget(self.cfg, lit_id, root=self.store.root,
                                 factory=getattr(self, "_budget_factory", None))
        resume = lit.get("extract_resume")
        resume = dict(resume) if isinstance(resume, Mapping) else {}
        pages_total = _page_count(path)
        window = int(self.cfg.get("extract_pages_per_call", 0) or 0)
        cap: int | None = None
        if pages_total is not None and window > 0 and int(pages_total) > window:
            cap = min(int(pages_total),
                      max(window, int(resume.get("pages_done") or 0) + window))
        from_chunk = int(resume.get("chunks_done") or 0)
        applied = bool(getattr(self.extractor, "supports_extract_budget", False))
        doc = (self.extract_text(path, max_pages=cap) if cap is not None
               else self.extract_text(path))
        doc_complete = cap is None or int(cap) >= int(pages_total or 0)
        res.extract_text = {
            "pages": len(getattr(doc, "pages", []) or []),
            "pages_total": pages_total,
            "complete": bool(doc_complete),
            "window": int(window),
            "budget": budget.reading(stage="text"),
        }
        meta = self._extraction_meta(lit)
        if applied:
            concepts, relations = self.extractor.extract(
                doc, lit_id, meta, budget=budget, from_chunk=from_chunk,
                doc_complete=doc_complete)
        else:
            # 替身 / 第三方抽取器：没有预算回调 ⇒ 照老样子整篇一次调用（读数写
            # `budget_applied=False`："没接预算"与"接了但没到点"两档必须分得开）。
            concepts, relations = self.extractor.extract(doc, lit_id, meta)
        report = dict(getattr(self.extractor, "last_report", None) or {})
        res.budget_applied = bool(applied)
        res.budget = _EB.stop_reading(
            budget=budget, report=report, doc_complete=bool(doc_complete),
            pages=len(getattr(doc, "pages", []) or []), pages_total=pages_total)
        stage = str(res.budget.get("stopped_stage") or "")
        if stage:
            res.stopped_budget = True
            res.details.append({"lit_id": lit_id, "stage": "budget", "stopped": stage,
                                "done": int(report.get("chunks_done") or 0),
                                "total": int(report.get("chunks_usable") or 0),
                                "used_sec": res.budget.get("used_sec"),
                                "remaining_sec": res.budget.get("remaining_sec"),
                                "pages": res.budget.get("pages"),
                                "pages_total": res.budget.get("pages_total"),
                                "why": res.budget.get("why", "")})
        return {"doc": doc, "concepts": concepts, "relations": relations,
                "stopped": bool(stage), "stage": stage,
                "chunks_done": int(report.get("chunks_done") or 0),
                "chunks_usable": int(report.get("chunks_usable") or 0),
                "pages": len(getattr(doc, "pages", []) or []),
                "doc_complete": bool(doc_complete), "pages_total": pages_total}
