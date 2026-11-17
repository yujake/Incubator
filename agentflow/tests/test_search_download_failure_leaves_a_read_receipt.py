# -*- coding: utf-8 -*-
"""下载失败也要留"试过"的回执（2026-11-17，AL2·#5）。

## 改前是什么形态

只有 `text.extract` 能写抽读回执（`litavail.record_read`），而 `search.download` 的
参数面没有候选绑定 ⇒ "一下载就失败、连文件都没有"的候选留不了回执，只能判拒，
不能按仅题录入库。业主口径：`metadata_only` = 试过一次、拿不到可读文本 ——
下载尝试也应该算一次尝试。

## 改法（档位二选一的理由）

给 `search.download` 加 `cand`（候选槽位）。给了它、且下载失败 ⇒ 写一条回执，
档位复用既有的 `extract_failed`（不新造"下载失败"一档）：回执回答的是"试没试过"，
下载失败与抽取失败对下游是同一件事（试过、拿不到可读文本；差别"有没有字节"记在
`note` / `source` 里）。新造一档要同时改 `litread` 词表、`litavail` 收执两档、
`check_read` 与入库闸四处 —— 而闸的口径一个字都不许变（仍要"有尝试回执"才准
`metadata_only`）。

## 判据

| 判据 | 它要证明的事 |
|---|---|
| a 下载失败（mock） | 候选行上有回执（`extract_failed`），且这一条能按 `metadata_only` 入库 |
| b 零尝试 | 同一条形状、没有回执 ⇒ 仍 `no_read_evidence` 整批拒（闸没被放宽） |
| c 反真空 | 把回执写点打桩关掉 ⇒ a 必红（那条回执不是别的路径顺手写的） |
| d 落地页（`ok=True` + `content_type_mismatch`，真机同形） | 同样留 `search.download.content_type_mismatch` 回执 ⇒ 可按仅题录入库 |
| e 超时 / 404 / DNS | 每档都留 `search.download.<fetch_kind>` 回执 |
| f 反真空（落地页那一支） | 关掉写点 ⇒ d 必红 |
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import fetch as F
from agentflow import litavail as LAV
from agentflow import litread as LR
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import search_tools as ST
from agentflow.tools.base import ToolRegistry

RID = "r-000001"


class FailingDownloader:
    """注入的下载器：一律 404（离线、确定性）。"""

    max_bytes = 50 * 1024 * 1024

    def download(self, url: str, dest_dir: pathlib.Path, filename_hint: str) -> F.FetchResult:
        return F.FetchResult(ok=False, path=None, http_status=404, bytes=0,
                             error="HTTP 404", kind="http_404")


class LandingPageDownloader:
    """真机同形（`projects/lp-ball-4` 的 Ball 1986）：`ok=True`，落盘的是落地页 HTML。

    字节确实落盘（10 MB 那张的缩样），但 `kind=content_type_mismatch` —— 它不是可读
    全文。这一档不算"干净成功"，`search.download(cand=…)` 必须留下一次尝试的回执。
    """

    max_bytes = 50 * 1024 * 1024

    def download(self, url: str, dest_dir: pathlib.Path, filename_hint: str) -> F.FetchResult:
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / "ball-1986-landing.html"
        body = b"<html><body><h1>doi.org landing page</h1></body></html>"
        path.write_bytes(body)
        import hashlib
        return F.FetchResult(
            ok=True, path=str(path), http_status=200, bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            error="content_type_mismatch: text/html (URL 无后缀；可能是落地页/登录墙/跳转页，不是直链文件)",
            kind="content_type_mismatch")


class KindDownloader:
    """注入的下载器：一律按给定的受控失败档失败（超时 / 404 / DNS …）。"""

    max_bytes = 50 * 1024 * 1024

    def __init__(self, kind: str, error: str) -> None:
        self.kind = kind
        self.error = error

    def download(self, url: str, dest_dir: pathlib.Path, filename_hint: str) -> F.FetchResult:
        return F.FetchResult(ok=False, path=None, http_status=None, bytes=0,
                             error=self.error, kind=self.kind)


def _ws(path: pathlib.Path, downloader=None):
    root = path / "ws"
    store = Store(root)
    store.init()
    registry = ToolRegistry(name="al2-lit-download")
    ST.register(registry, store=store, downloader=downloader or FailingDownloader(),
                workspace=root, actor="agent-A")
    registry.bound_role = "A"
    return root, store, registry


def _stage(registry, titles: list[str]) -> dict[str, str]:
    """暂存候选，返回 `题名 -> 槽位`（每条都带 relevance 与 DOI 定位符）。"""
    entries = [{"title": t, "doi": f"10.9/{i}", "provider": "stub", "year": 2024,
                "type_code": "J", "relevance": f"与本次检索相关（{t}）"}
               for i, t in enumerate(titles)]
    with calling_as("t-al2-5", "A"):
        res = registry.call("lit.stage_add", request_id=RID, entries=entries)
    assert res.ok, res.error
    return {str(x["title"]): str(x["slot"]) for x in res.unwrap()["staged"]}


def _admit_metadata_only(registry, slot: str):
    """按仅题录判收这一条（relevance 已在暂存那一笔落进候选行）。

    先回读一遍清单：提交闸要求"这一次委托的回执覆盖要提交的槽位"，没有回读会先撞
    `no_readback`（那是另一道闸，不是本文件要测的 read-evidence 闸）。
    """
    with calling_as("t-al2-5", "A"):
        listed = registry.call("lit.stage_list", request_id=RID)
        assert listed.ok, listed.error
        return registry.call("lit.admit", request_id=RID,
                             items=[{"slot": slot, "availability": LAV.METADATA_ONLY}])


def test_a_a_failed_download_leaves_a_receipt_and_allows_metadata_only(
        tmp_path: pathlib.Path) -> None:
    """a：mock 下载失败 ⇒ 候选行上有回执，并且能按 metadata_only 入库。"""
    root, store, registry = _ws(tmp_path)
    slot = _stage(registry, ["下载就失败的候选"])["下载就失败的候选"]

    with calling_as("t-al2-5", "A"):
        res = registry.call("search.download", url="https://example.invalid/x.pdf",
                            cand=slot)
    assert res.ok is False and res.meta.get("kind") == "download_failed", res
    assert res.meta.get("cand") == slot, res.meta
    receipt = res.meta.get("read_receipt")
    assert isinstance(receipt, dict) and receipt.get("tier") == LR.FULLTEXT_EXTRACT_FAILED, (
        "下载失败没有在返回值里给出那条回执", res.meta)
    assert "search.download.http_404" in str(receipt.get("note") or ""), receipt

    on_disk = LAV.receipts_by_slot(root).get(slot)
    assert on_disk is not None, "下载失败没有在盘上留下回执 ⇒ 这一条只能判拒"
    assert on_disk.get("tier") == LR.FULLTEXT_EXTRACT_FAILED, on_disk
    assert on_disk.get("candidate", {}).get("title") == "下载就失败的候选", (
        "回执没绑这一条候选的身份三格", on_disk)

    admitted = _admit_metadata_only(registry, slot)
    assert admitted.ok is True, ("有回执的仅题录仍被拒 ⇒ 下载尝试没有算一次尝试", admitted)
    # 判收不发号（Q1）：整批提交那一刻才注册进 literature —— 这里把整条路走完。
    with calling_as("t-al2-5", "A"):
        settled = registry.call("lit.admit_all", request_id=RID)
    assert settled.ok is True, ("判收之后整批提交被拒 ⇒ 这一条并没有真的可入库", settled)
    rows = [dict(r) for r in store.rows("literature")]
    assert [r.get("title") for r in rows] == ["下载就失败的候选"], rows


def test_d_a_landing_page_download_leaves_a_receipt_and_allows_metadata_only(
        tmp_path: pathlib.Path) -> None:
    """d（2026-11-17 FX3·乙）：真机同形 —— `ok=True` 但落到落地页 HTML。

    改前读数：这一支走的是 `ok=True` 的路，回执一个字都不写；A 只拿到
    `content_warning=content_type_mismatch`，以为"拿不到全文 ⇒ 不能入库"，
    105 条候选一条都不敢按仅题录判（真机 `projects/lp-ball-4`）。
    """
    root, store, registry = _ws(tmp_path, LandingPageDownloader())
    slot = _stage(registry, ["Ball 1986 Cube Slicing in R^n"])["Ball 1986 Cube Slicing in R^n"]

    with calling_as("t-al2-5", "A"):
        res = registry.call("search.download",
                            url="https://doi.org/10.1090/s0002-9939-1986-0840631-0",
                            cand=slot)
    assert res.ok is True, res
    data = res.unwrap()
    assert "content_type_mismatch" in str(data.get("content_warning") or ""), data
    receipt = data.get("read_receipt")
    assert isinstance(receipt, dict) and receipt.get("tier") == LR.FULLTEXT_EXTRACT_FAILED, (
        "落地页下载没有在返回值里给出那条回执", data)
    assert "search.download.content_type_mismatch" in str(receipt.get("note") or ""), receipt

    on_disk = LAV.receipts_by_slot(root).get(slot)
    assert on_disk is not None, "落地页下载没有在盘上留下回执 ⇒ 这一条只能判拒"
    assert on_disk.get("tier") == LR.FULLTEXT_EXTRACT_FAILED, on_disk
    assert on_disk.get("candidate", {}).get("title") == "Ball 1986 Cube Slicing in R^n", on_disk

    admitted = _admit_metadata_only(registry, slot)
    assert admitted.ok is True, ("有回执的仅题录仍被拒 ⇒ 落地页不算一次尝试", admitted)
    with calling_as("t-al2-5", "A"):
        settled = registry.call("lit.admit_all", request_id=RID)
    assert settled.ok is True, settled
    rows = [dict(r) for r in store.rows("literature")]
    assert [r.get("title") for r in rows] == ["Ball 1986 Cube Slicing in R^n"], rows


@pytest.mark.parametrize("kind,error", [
    ("timeout", "timeout: read timed out"),
    ("http_404", "HTTP 404"),
    ("network_error", "network_error: Name or service not known (DNS)"),
])
def test_e_timeout_404_and_dns_failures_all_leave_receipts(
        tmp_path: pathlib.Path, kind: str, error: str) -> None:
    """e：超时 / 404 / DNS（`network_error`）各自留下带形态名的回执。"""
    root, store, registry = _ws(tmp_path, KindDownloader(kind, error))
    title = f"下载失败形态 {kind} 的候选"
    slot = _stage(registry, [title])[title]

    with calling_as("t-al2-5", "A"):
        res = registry.call("search.download", url="https://example.invalid/x.pdf", cand=slot)
    assert res.ok is False and res.meta.get("kind") == "download_failed", res
    receipt = res.meta.get("read_receipt")
    assert isinstance(receipt, dict), res.meta
    assert f"search.download.{kind}" in str(receipt.get("note") or ""), receipt
    assert LAV.receipts_by_slot(root).get(slot) is not None, kind
    assert _admit_metadata_only(registry, slot).ok is True, kind


def test_f_stubbing_the_landing_page_receipt_writer_turns_d_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """f（反真空）：关掉唯一的回执写点 ⇒ 落地页那一支不再留回执、d 的入库必红。"""
    monkeypatch.setattr(ST, "_record_download_attempt", lambda *a, **kw: None)
    root, store, registry = _ws(tmp_path, LandingPageDownloader())
    slot = _stage(registry, ["落地页写点关掉的候选"])["落地页写点关掉的候选"]

    with calling_as("t-al2-5", "A"):
        res = registry.call("search.download", url="https://example.invalid/y.pdf", cand=slot)
    assert res.ok is True, res
    assert res.unwrap().get("read_receipt") is None, res.unwrap()
    assert LAV.receipts_by_slot(root).get(slot) is None, (
        "写点已经打桩关掉了，盘上却还有回执 ⇒ 那一行不是这个写点落的")

    refused = _admit_metadata_only(registry, slot)
    assert refused.ok is False and refused.meta.get("kind") == "no_read_evidence", (
        "写点关掉之后仅题录仍被放行 ⇒ d 的绿不是那个写点给的", refused)


def test_b_zero_attempts_still_refuse_the_whole_batch(tmp_path: pathlib.Path) -> None:
    """b：零尝试 ⇒ 仍 `no_read_evidence` 整批拒（这条闸没有被放宽）。"""
    root, store, registry = _ws(tmp_path)
    slot = _stage(registry, ["一次都没试过的候选"])["一次都没试过的候选"]
    assert LAV.receipts_by_slot(root).get(slot) is None, "夹具不该预先写回执"

    res = _admit_metadata_only(registry, slot)
    assert res.ok is False, ("零尝试的仅题录被放行了 ⇒ 闸被放宽了", res)
    assert res.meta.get("kind") == "no_read_evidence", res.meta
    assert [str(x.get("slot")) for x in (res.meta.get("read_problems") or [])] == [slot], (
        "拒信没有逐槽点名", res.meta)
    assert not [r for r in store.rows("literature")], "整批拒之后 literature 里不该有行"


def test_c_stubbing_the_receipt_writer_turns_a_red(tmp_path: pathlib.Path,
                                                   monkeypatch) -> None:
    """c（反真空）：把回执写点打桩关掉 ⇒ 同一次下载失败不再留下回执、a 的入库必红。

    打桩点是 `search_tools._record_download_attempt`（唯一的写点）：关掉之后下载
    照旧失败（返回值不变），但候选行上没有回执 ⇒ `metadata_only` 按零读取尝试拒。
    """
    monkeypatch.setattr(ST, "_record_download_attempt", lambda *a, **kw: None)
    root, store, registry = _ws(tmp_path)
    slot = _stage(registry, ["写点打桩关掉的候选"])["写点打桩关掉的候选"]

    with calling_as("t-al2-5", "A"):
        res = registry.call("search.download", url="https://example.invalid/y.pdf",
                            cand=slot)
    assert res.ok is False and res.meta.get("kind") == "download_failed", res
    assert res.meta.get("read_receipt") is None, res.meta
    assert LAV.receipts_by_slot(root).get(slot) is None, (
        "写点已经打桩关掉了，盘上却还有回执 ⇒ 那一行不是这个写点落的")

    refused = _admit_metadata_only(registry, slot)
    assert refused.ok is False and refused.meta.get("kind") == "no_read_evidence", (
        "写点关掉之后仅题录仍被放行 ⇒ a 的绿不是那个写点给的", refused)
