# -*- coding: utf-8 -*-
"""下载失败也要留"试过"的回执（2026-11-17，AL2·#5；2026-11-20 口径更新）。

## 这一条回执仍然要有多久

只有 `text.extract` 能写抽读回执（`litavail.record_read`），而 `search.download` 原先的
参数面没有候选绑定 ⇒ "一下载就失败、连文件都没有"的候选留不了一次尝试的读数。
所以给 `search.download` 加了 `cand`（候选槽位）：给了它、且下载失败 ⇒ 写一条
`extract_failed` 回执（不新造"下载失败"一档；差别"有没有字节"记在 `note` / `source`）。

## 2026-11-20 之后它不再是一张入库券

业主逐字：「读内容才能判东西，这样的话保证通过的肯定有内容，且能保证质量」。
`metadata_only` 不再可入（`litavail.ADMITTABLE_TIERS` 只剩 `readable`）。于是这一族
判据改成两件事同时守：

- 回执照旧要留：下载失败 / 落地页 / 超时 / 404 / DNS 都留下
  `search.download.<kind>` 的尝试回执（这是"试过没有"的唯一读数，判拒时要写得出为什么）；
- 留了也不许判收：`lit.admit` 对仅题录一律受控拒（`availability_not_admissible`），
  理由码按"有没有回执"分成 `metadata_only`（试过、只剩题录）/ `no_fulltext`（连试都没试）。
  两种理由码分得开，正是回执还在起作用的读数。

## 判据

| 判据 | 它要证明的事 |
|---|---|
| a 下载失败（mock） | 候选行上有回执；`lit.admit` 受控拒、理由码 `metadata_only`、一行都不进库 |
| b 零尝试 | 同一条形状、没有回执 ⇒ 仍受控拒，理由码 `no_fulltext`（回执的有无在读数上分得开） |
| c 反真空 | 把回执写点打桩关掉 ⇒ 理由码从 `metadata_only` 退成 `no_fulltext`（那个写点不是摆设） |
| d 落地页 | 落地页也留 `search.download.content_type_mismatch` 回执 ⇒ 同样不许判收 |
| e 超时 / 404 / DNS | 每档都留 `search.download.<fetch_kind>` 回执 |
| f 反真空（落地页那一支） | 关掉写点 ⇒ d 的理由码退成 `no_fulltext` |
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
    """按仅题录申请判收这一条（必须被受控拒 —— 没有正文不是入库券）。"""
    with calling_as("t-al2-5", "A"):
        listed = registry.call("lit.stage_list", request_id=RID)
        assert listed.ok, listed.error
        return registry.call("lit.admit", request_id=RID,
                             items=[{"slot": slot, "availability": LAV.METADATA_ONLY}])


def _refusal_code(result) -> str:
    """受控拒里那一条的理由码（`availability_bad[].code`）。"""
    bad = (result.meta or {}).get("availability_bad") or []
    return str((bad[0] if bad else {}).get("code") or "")


def test_a_a_failed_download_leaves_a_receipt_and_still_cannot_be_admitted(
        tmp_path: pathlib.Path) -> None:
    """a：mock 下载失败 ⇒ 候选行上有回执；但仅题录不许入库（理由码 `metadata_only`）。"""
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
    assert on_disk is not None, "下载失败没有在盘上留下回执 ⇒ 判拒时说不出'为什么没读到'"
    assert on_disk.get("tier") == LR.FULLTEXT_EXTRACT_FAILED, on_disk
    assert on_disk.get("candidate", {}).get("title") == "下载就失败的候选", (
        "回执没绑这一条候选的身份三格", on_disk)

    refused = _admit_metadata_only(registry, slot)
    assert refused.ok is False, "没有正文的仅题录被放行了"
    assert refused.meta.get("kind") == "availability_not_admissible", refused.meta
    assert _refusal_code(refused) == "metadata_only", refused.meta
    assert store.rows("literature") == [], "被拒却写进了 literature"


def test_d_a_landing_page_download_leaves_a_receipt_and_still_cannot_be_admitted(
        tmp_path: pathlib.Path) -> None:
    """d（2026-11-17 FX3·乙）：`ok=True` 但落到落地页 HTML。

    改前读数：这一支走的是 `ok=True` 的路，回执一个字都不写。现在两件事都守：
    回执要留（`search.download.content_type_mismatch`）；但落地页不是正文 ⇒ 不许判收。
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
    assert on_disk is not None, "落地页下载没有在盘上留下回执 ⇒ 判拒时说不出'为什么没读到'"
    assert on_disk.get("tier") == LR.FULLTEXT_EXTRACT_FAILED, on_disk
    assert on_disk.get("candidate", {}).get("title") == "Ball 1986 Cube Slicing in R^n", on_disk

    refused = _admit_metadata_only(registry, slot)
    assert refused.ok is False, "落地页被当成正文判收了"
    assert _refusal_code(refused) == "metadata_only", refused.meta
    assert store.rows("literature") == []


@pytest.mark.parametrize("kind,error", [
    ("timeout", "timeout: read timed out"),
    ("http_404", "HTTP 404"),
    ("network_error", "network_error: Name or service not known (DNS)"),
])
def test_e_timeout_404_and_dns_failures_all_leave_receipts(
        tmp_path: pathlib.Path, kind: str, error: str) -> None:
    """e：超时 / 404 / DNS（`network_error`）各自留下带形态名的回执；仍不许判收。"""
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
    refused = _admit_metadata_only(registry, slot)
    assert refused.ok is False and _refusal_code(refused) == "metadata_only", kind


def test_f_stubbing_the_landing_page_receipt_writer_moves_the_reason_code(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """f（反真空）：关掉唯一的回执写点 ⇒ 落地页那一支不再留回执，理由码退成 `no_fulltext`。"""
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
    assert refused.ok is False, "没有正文的仅题录被放行了"
    assert _refusal_code(refused) == "no_fulltext", (
        f"写点关掉之后理由码仍报 {_refusal_code(refused)!r} ⇒ 回执的有无在读数上不可见",
        refused.meta)


def test_b_zero_attempts_still_refuse_the_whole_batch(tmp_path: pathlib.Path) -> None:
    """b：零尝试 ⇒ 受控拒、理由码 `no_fulltext`（与"试过但只剩题录"分得开）。"""
    root, store, registry = _ws(tmp_path)
    slot = _stage(registry, ["一次都没试过的候选"])["一次都没试过的候选"]
    assert LAV.receipts_by_slot(root).get(slot) is None, "夹具不该预先写回执"

    res = _admit_metadata_only(registry, slot)
    assert res.ok is False, ("零尝试的仅题录被放行了 ⇒ 闸被放宽了", res)
    assert res.meta.get("kind") == "availability_not_admissible", res.meta
    assert _refusal_code(res) == "no_fulltext", res.meta
    assert not [r for r in store.rows("literature")], "整批拒之后 literature 里不该有行"


def test_c_stubbing_the_receipt_writer_turns_metadata_only_into_no_fulltext(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c（反真空）：把回执写点打桩关掉 ⇒ 同一次下载失败的理由码从 `metadata_only`
    退成 `no_fulltext`（a 的读数真的是那个写点给的）。

    打桩点是 `search_tools._record_download_attempt`（唯一的写点）：关掉之后下载
    照旧失败（返回值不变），但候选行上没有回执。
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
    assert refused.ok is False, "没有正文的仅题录被放行了"
    assert _refusal_code(refused) == "no_fulltext", (
        "写点关掉之后理由码仍是 metadata_only ⇒ a 的读数不是那个写点给的", refused.meta)
