"""T0-10 的判据：A 的"补下载"（依据 `draft/30` §T0-10）。

背景（验收 P1 实测撞出来的）：候选命中已存在的 `literature` 行时，A 原本只追加
`source_request_ids` 就跳过 ⇒ "在库却没有全文"的行永远补不上（Brown 1971 就是这样
卡住的：第一轮赶上 host 漏接 downloader，第二轮被去重跳过）。

这一组五条：正控（补上）、防误伤（已有全文不重下）、两条负控（没有 PDF URL / 搬文件失败
都不许写成"下来了"）、反真空（预算用尽时连补下载也不做）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.fetch import FetchResult
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"


class _Provider:
    """确定性替身：返回固定候选，不联网。"""

    name = "backfill-stub"

    def __init__(self, candidates):
        self.candidates = list(candidates)

    def search(self, topic, mode, description, limit):
        """按 `providers.SearchProvider` 的协议返回候选。"""
        return list(self.candidates)


class _Downloader:
    """落一个真文件并给出真 sha256（不联网）。"""

    def __init__(self, *, fail: Exception | None = None):
        self.fail = fail
        self.calls = 0

    def download(self, url, dest_dir, hint):
        """写一个字节确定的文件；`fail` 非空时模拟取到了但不是 PDF。"""
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        p = Path(dest_dir) / f"{hint or 'file'}.pdf"
        p.write_text("backfill payload", encoding="utf-8")
        data = p.read_bytes()
        return FetchResult(ok=True, path=str(p), http_status=200, bytes=len(data),
                           sha256=hashlib.sha256(data).hexdigest(), error=None)


def _cand(**kw) -> SimpleNamespace:
    """鸭子类型候选（与 `agent_a` 自检同一形态）。"""
    base = dict(title="Backfill literature", doi="10.9999/backfill", year=2026,
                pdf_url="http://example.invalid/backfill.pdf")
    base.update(kw)
    return SimpleNamespace(**base)


def _store(tmp_path: Path) -> Store:
    """空工作区。"""
    st = Store(tmp_path)
    st.init()
    return st


def _seed_existing(st: Store, *, path: str | None, status: str, today: str = "2026-01-01") -> str:
    """落一行"已在库"的文献（模拟早先那次处理留下的记录）。

    `dedup_key` 必须按 A 的口径算（`D.literature_keys`）—— 手写一个像模像样的键
    会让判重找不到这一行，于是用例测的就变成"新建一行"而不是"补下载"。
    """
    from agentflow import dedup as D

    keys = D.literature_keys("Backfill literature", 2026, "10.9999/backfill")
    row = S.Literature(lit_id="0000", title="Backfill literature", type="J", summary="",
                       path=path, processed=False, source_request_ids=["r-0000"],
                       dedup_key=keys[0] if keys else "title:backfill literature|*",
                       doi="10.9999/backfill", year=2026,
                       added_at=TS, download={"status": status, "error": "no_downloader",
                                              "http_status": None, "bytes": 0, "sha256": None})
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())
    return "0000"


def _seed_request(st: Store) -> None:
    """落一条待办检索请求（A 要有活才会跑）。"""
    row = S.SearchRequest(request_id="r-0001", timestamp=TS, topic="backfill", mode="broad",
                          content_description="", done=False, submitted_by="test",
                          priority="medium", attempts=0)
    with st.tx("search_requests", actor="test") as tx:
        tx.upsert("search_requests", row.to_dict())


def _agent(st: Store, *, downloader=None, candidates=None, max_downloads: int = 5) -> AgentA:
    """造一个只走替身的 A。"""
    return AgentA(st, providers=[_Provider(candidates or [_cand()])],
                  downloader=downloader if downloader is not None else _Downloader(),
                  config={"max_downloads_per_request": max_downloads, "lease_seconds": 900})


def _lit(st: Store) -> dict:
    """取那一行文献。"""
    rows = st.rows("literature")
    assert len(rows) == 1, rows
    return rows[0]


def test_backfill_attaches_the_file_to_an_existing_row(tmp_path: Path):
    """正控：在库行没有全文 + 这次候选有 PDF ⇒ 字节挂到那一行上，且旧记录不抹掉。"""
    st = _store(tmp_path)
    _seed_existing(st, path=None, status="skipped")
    _seed_request(st)
    res = _agent(st).run_once()
    row = _lit(st)
    assert row["path"], row
    f = st.library / row["path"]
    assert f.is_file() and f.stat().st_size > 0
    assert row["download"]["status"] == "ok"
    assert row["download"].get("backfilled") is True
    assert row["download"]["previous"]["status"] == "skipped"
    assert row["download"]["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()
    assert res.downloaded == 1 and res.registered == 0 and res.duplicated == 1


def test_no_backfill_when_the_row_already_has_a_working_file(tmp_path: Path):
    """防误伤：已经有 `status="ok"` 的全文 ⇒ 不重下（文件不动、计数不增）。"""
    st = _store(tmp_path)
    d = st.library / "0000"
    d.mkdir(parents=True, exist_ok=True)
    (d / "old.pdf").write_text("old", encoding="utf-8")
    _seed_existing(st, path="0000/old.pdf", status="ok")
    before = (d / "old.pdf").read_bytes()
    _seed_request(st)
    dl = _Downloader()
    res = _agent(st, downloader=dl).run_once()
    row = _lit(st)
    assert row["path"] == "0000/old.pdf"
    assert (d / "old.pdf").read_bytes() == before
    assert row["download"].get("backfilled") is None
    assert res.downloaded == 0 and res.duplicated == 1


def test_no_pdf_url_leaves_the_row_untouched(tmp_path: Path):
    """负控（注入）：候选没有 PDF URL ⇒ 行不许被改（"没下来"不许写成"下来了"）。"""
    st = _store(tmp_path)
    _seed_existing(st, path=None, status="skipped")
    _seed_request(st)
    res = _agent(st, candidates=[_cand(pdf_url=None)]).run_once()
    row = _lit(st)
    assert row["path"] is None, row
    assert row["download"]["status"] == "skipped"
    assert row["download"].get("error") == "no_downloader", "旧记录原样保留"
    assert res.downloaded == 0


def test_move_failure_is_recorded_as_failed_not_ok(tmp_path: Path):
    """负控（注入）：搬文件失败 ⇒ `status="failed"`、`path` 仍为空，且旧记录进 `previous`。

    构造法：把 `<library>/<lit_id>` 建成文件（不是目录）⇒ `mkdir` 抛错。
    """
    st = _store(tmp_path)
    _seed_existing(st, path=None, status="skipped")
    blocker = st.library / "0000"
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    _seed_request(st)
    res = _agent(st).run_once()
    row = _lit(st)
    assert row["path"] is None, row
    assert row["download"]["status"] == "failed", row["download"]
    assert "move_failed" in str(row["download"].get("error")), row["download"]
    assert row["download"]["previous"]["status"] == "skipped"
    assert res.downloaded == 0 and res.download_failed == 1


def test_backfill_respects_the_download_budget(tmp_path: Path):
    """反真空：`max_downloads_per_request=0` 时连补下载也不做（预算对两处一致）。"""
    st = _store(tmp_path)
    _seed_existing(st, path=None, status="skipped")
    _seed_request(st)
    res = _agent(st, max_downloads=0).run_once()
    row = _lit(st)
    assert row["path"] is None, row
    assert res.downloaded == 0


def test_backfill_does_not_touch_a_row_with_a_failed_download_only(tmp_path: Path) -> None:
    """正控（另一支）：旧状态是 `failed`（曾经真试过）也照样补 —— "没下来过"不是"不能补"。"""
    st = _store(tmp_path)
    _seed_existing(st, path=None, status="failed")
    _seed_request(st)
    res = _agent(st).run_once()
    row = _lit(st)
    assert row["path"], row
    assert row["download"]["status"] == "ok" and row["download"]["backfilled"] is True
    assert row["download"]["previous"]["status"] == "failed"
    assert res.downloaded == 1
