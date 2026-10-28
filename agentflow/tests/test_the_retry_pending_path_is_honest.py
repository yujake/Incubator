# -*- coding: utf-8 -*-
"""判据（阶段 ③ 第 2B 步）：`search.retry_pending` 的写路径必须诚实。

## 它补的是哪一格

真机（`draft/172` §4 第 4 轮 O-04 / §8 第 3 轮）：`literature` 32 行里 27 行
没有本地全文，而这 27 行各自都记着一个定位链接（`download.url`，note 逐字
「要全文请按它重取」）。A 当时只能一条一条手工 `search.download` + `search.register`，
而它已经吃过 404 / 429 / 400 各两次 —— 每一类失败的正确处置不同（429 等冷却、
404 换 landing、400 换 PDF 路由），手工重试既慢又容易把"没取到"写成"没有这篇"。

这一件工具把"逐行再试一次"做成一个可数的动作，并且只允许四种结局：

```
got          这一行现在真的在盘上、可离线引用（路径已写回 literature.path）
failed       我们发了请求，没拿到可用字节（`kind` 记受控档：http_404 / tls_cert …）
no_location  行上没有可重取的地址 ⇒ 我们没去取（不是「这篇不存在」）
cooled_down  这个源正在冷却（429 那次之后）⇒ 这一行跳过，不是失败
```

`failed` 是这一批我加上的第 4 档（业主写的"三结局"指三种处置）：
把 404 折进 `no_location` 就是"下载失败 = 这篇不存在"，而那正是要防的缺陷；
把它折进 `got` 更糟。三态纪律在这里的落法是："试了没成"与"没去试"必须分开。

## 这一组守什么

1. 三种（四种）结局各一条，且 `counts` 与 `rows[]` 逐条对得上（反真空：不是空表）；
2. 「下载失败 ≠ 这篇不存在」：404 之后那一行不许被记成 `no_location`，也不许冒出
   `not_found` 这类断言键；
3. 「冷却是跳过而非失败」：同一个源 429 之后，后续行不再发请求（下载器调用次数
   可数），结局是 `cooled_down` 且不计入 `failed`；
4. 它是写工具、只有 A 能拿到（C/H/V 没有）—— 工具面即权限面；
5. `returns=` 里四种结局逐字点名（模型看得到的就是它）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from agentflow import fetch as F
from agentflow import providers as P
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import ROLES, build_registry, search_tools
from agentflow.tools.base import ToolRegistry


# ---------------------------------------------------------------- 夹具


class _ScriptedDownloader:
    """按脚本回结果的假下载器（离线、确定性、调用次数可数）。"""

    max_bytes = 50 * 1024 * 1024

    def __init__(self, script: list[tuple]) -> None:
        self.script = list(script)
        self.calls: list[str] = []

    def download(self, url: str, dest: Any, hint: str = "paper") -> F.FetchResult:  # noqa: ARG002
        self.calls.append(url)
        action = self.script.pop(0) if self.script else ("ok", b"%PDF-1.4 retry-pending\n")
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        if action[0] == "ok":
            body = action[1]
            out = dest / f"retry-{len(self.calls)}.pdf"
            out.write_bytes(body)
            return F.FetchResult(ok=True, path=str(out), http_status=200, bytes=len(body),
                                 sha256=hashlib.sha256(body).hexdigest(), kind=None)
        kind = str(action[1])
        status = {"http_429": 429, "http_404": 404, "http_403": 403}.get(kind)
        return F.FetchResult(ok=False, kind=kind, error=f"桩：{kind}", http_status=status)


def _registry(store: Store | None, downloader: Any | None = None) -> ToolRegistry:
    """绑定 A 的注册表：`search.*` 只有 A 拿得到（`roles=('A',)`）。"""
    reg = ToolRegistry(name="retry-pending")
    reg.bound_role = "A"
    search_tools.register(reg, store=store, downloader=downloader,
                          workspace=(store.root if store else None))
    return reg


def _row(store: Store, lit_id: str, *, download: dict | None = None,
         path: str | None = None) -> dict[str, Any]:
    row = S.Literature(
        lit_id=lit_id, title=f"文献 {lit_id}", type="J", summary="判据用的行",
        path=path, processed=False, added_at=S.now_iso(),
        download=dict(download or {}),
    ).to_dict()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row)
    return row


def _pending_row(store: Store, lit_id: str, url: str, **extra: Any) -> dict[str, Any]:
    """一行「有元数据、有定位链接、没有本地全文」—— 这正是要重取的那一档。"""
    dl = {"status": "skipped", "error": "no_local_path", "url": url}
    dl.update(extra)
    return _row(store, lit_id, download=dl)


def _retry(store: Store, downloader: Any, **kw: Any) -> Any:
    return _registry(store, downloader).call("search.retry_pending", **kw)


def _stored(store: Store, lit_id: str) -> dict[str, Any]:
    """读回盘上的那一行（走 `Store.rows`，与工具读的是同一份快照）。"""
    for row in store.rows("literature"):
        if str(row.get("lit_id") or "") == lit_id:
            return row
    raise AssertionError(f"literature 里没有 {lit_id}")


# ---------------------------------------------------------------- 1) got


def test_a_row_with_a_usable_location_is_fetched_and_lands_on_the_shelf(store: Store):
    """正向：有地址的待取行 ⇒ 真发一次请求 ⇒ 字节进 library/ ⇒ 书架看得见。

    判据打在三个可核的事实上（不是"函数返回了 got"）：
    ① 下载器真的被调了一次；② `literature.path` 指向 library/ 下的文件且文件在盘上；
    ③ `search.shelf` 的覆盖率从 0/1 变成 1/1。
    """
    _pending_row(store, "0001", "https://arxiv.org/pdf/2210.06457v1")
    dl = _ScriptedDownloader([("ok", b"%PDF-1.4 khale\n")])

    res = _retry(store, dl)
    assert res.ok, (res.error, res.meta)
    data = res.data
    assert data["counts"] == {"got": 1, "failed": 0, "no_location": 0, "cooled_down": 0}, data
    assert data["attempted"] == 1 and data["scanned"] == 1, data
    assert dl.calls == ["https://arxiv.org/pdf/2210.06457v1"], dl.calls

    row = _stored(store, "0001")
    assert row["path"], f"下载成功却没把路径写回 literature.path：{row}"
    assert (Path(store.library) / str(row["path"])).is_file(), row["path"]
    assert row["download"]["status"] == "ok", row["download"]
    assert row["download"]["url"] == "https://arxiv.org/pdf/2210.06457v1", row["download"]

    shelf = _registry(store).call("search.shelf")
    assert shelf.data["count"] == 1, shelf.data
    cov = shelf.data["coverage"]
    assert (cov["with_fulltext"], cov["total"], cov["missing"]) == (1, 1, 0), cov

    assert data["coverage_before"]["with_fulltext"] == 0, data["coverage_before"]
    assert data["coverage_after"]["with_fulltext"] == 1, data["coverage_after"]


# ---------------------------------------------------------------- 2) no_location


def test_a_row_with_no_location_is_not_turned_into_the_paper_does_not_exist(store: Store):
    """`no_location`：行上没有可重取的地址 ⇒ 如实说「我们没去取」。

    反真空三段：
    ① 结局是 `no_location`，不是 `failed`（一个请求都没发：`attempted == 0`）；
    ② `counts.no_location == 1` 且 `counts.failed == 0` —— 折叠两者这条就红；
    ③ 返回里不许出现「这篇不存在」这类断言键/结局（`not_found` / `nonexistent` …），
       且 `rows[0].note` 与顶层 `note` 都必须写清两者不同。
    """
    _row(store, "0001", download={"status": "failed", "error": "no_open_access_location"})
    dl = _ScriptedDownloader([("ok", b"never used\n")])

    res = _retry(store, dl)
    assert res.ok, res.error
    data = res.data
    row = data["rows"][0]
    assert row["outcome"] == "no_location", row
    assert data["counts"] == {"got": 0, "failed": 0, "no_location": 1, "cooled_down": 0}, data
    assert data["attempted"] == 0, "没有地址的行不许发请求"
    assert dl.calls == [], dl.calls

    banned = {"not_found", "notfound", "nonexistent", "does_not_exist", "missing_paper"}
    assert not (banned & set(data)), sorted(banned & set(data))
    assert not (banned & set(row)), sorted(banned & set(row))
    assert row["outcome"] not in banned, row
    assert "不存在" in str(row["note"]), row["note"]
    assert "不存在" in str(data["note"]), data["note"]


# ---------------------------------------------------------------- 3) failed


def test_a_download_failure_is_not_recorded_as_no_location(store: Store):
    """「下载失败 ≠ 这篇不存在」：404 之后那一行是 `failed`，且失败原因留在行上。

    这一条是本批最容易写错的格：把 404 折成 `no_location` 会让下游读成
    "我们连地址都没有"（进而"这大概不存在"），而事实是我们知道地址、
    对方不给。所以判据同时钉：结局、受控档 `kind`、以及行上的账（`last_kind`）。
    """
    _pending_row(store, "0001", "https://onlinelibrary.wiley.com/doi/pdf/10.1112/x")
    dl = _ScriptedDownloader([("fail", "http_404")])

    res = _retry(store, dl)
    assert res.ok, res.error
    data = res.data
    row = data["rows"][0]
    assert row["outcome"] == "failed", row
    assert row["kind"] == "http_404" and row["http_status"] == 404, row
    assert data["counts"] == {"got": 0, "failed": 1, "no_location": 0, "cooled_down": 0}, data
    assert data["attempted"] == 1, data

    stored = _stored(store, "0001")
    assert not stored["path"], f"下载失败却给了一个 path：{stored}"
    assert stored["download"]["status"] == "failed", stored["download"]
    assert stored["download"]["last_kind"] == "http_404", stored["download"]
    assert stored["download"]["retry_attempts"] == 1, stored["download"]
    # 行仍然在表里、仍然带地址：一次 404 不许把这一篇从证据链里抹掉
    assert stored["download"]["url"], stored["download"]


# ---------------------------------------------------------------- 4) cooled_down


def test_a_cooling_source_is_skipped_not_failed(store: Store):
    """冷却是跳过，不是失败：同一个源 429 之后，后面几行一个请求都不发。

    真机依据（`draft/172` 缺陷 ⑰ 的同族）：A 曾对同一个源连续 8 次 429，
    时间全耗在上面。所以这里钉三件事：
    ① 第一行 429 ⇒ `failed` 一次，并且这个源进了冷却（`P._provider_cooling > 0`）；
    ② 第二、三行同源 ⇒ `cooled_down`，下载器没有被再调（调用次数可数）；
    ③ `counts.cooled_down == 2` 而 `counts.failed == 1` —— 跳过不计入失败。
    """
    host = "https://onlinelibrary.wiley.com/doi/pdf/10.1112/S0025579300013000"
    _pending_row(store, "0001", host)
    _pending_row(store, "0002", host.replace("S0025579300013000", "S0025579300013001"))
    _pending_row(store, "0003", host.replace("S0025579300013000", "S0025579300013002"))
    dl = _ScriptedDownloader([("fail", "http_429")])

    res = _retry(store, dl)
    assert res.ok, res.error
    data = res.data
    outcomes = [r["outcome"] for r in data["rows"]]
    assert outcomes == ["failed", "cooled_down", "cooled_down"], data["rows"]
    assert dl.calls == [host], f"冷却期间仍在打同一个源：{dl.calls}"
    assert data["attempted"] == 1, data
    assert data["counts"] == {"got": 0, "failed": 1, "no_location": 0, "cooled_down": 2}, data
    # 冷却表是真的被置上了（不是"这一次恰好跳了"）
    assert P._provider_cooling("wiley.com") > 0, "429 之后这个源必须进冷却"
    cooled = data["rows"][1]
    assert cooled["cooldown_left_sec"] and cooled["cooldown_left_sec"] > 0, cooled


# ---------------------------------------------------------------- 5) 工具面 = 权限面


def test_it_is_a_write_tool_that_only_a_can_reach(store: Store):
    """它是写路径（会落盘、会改 literature 行）、出网、只有 A 拿得到。

    `search.retry_pending` 一次调用会改盘上的既有行，所以它必须声明成
    `write_local` + `external=egress`；角色面只有 A（C/H 是只读角色、V 不做检索）。
    这两条一起才说明"权限面没被顺手放宽"。
    """
    reg = build_registry(roles=tuple(ROLES)).registry
    spec = reg.get("search.retry_pending")
    assert spec.side_effect == "write_local", spec.side_effect
    assert spec.declared_external == "egress", spec.declared_external
    assert tuple(spec.roles) == ("A",), spec.roles
    for role in ("C", "H", "V"):
        assert "search.retry_pending" not in [s.name for s in reg.for_role(role)], role
    assert "search.retry_pending" in [s.name for s in reg.for_role("A")]
    assert "'cooled_down'" in spec.returns, spec.returns


# ---------------------------------------------------------------- 6) 反真空 / 负控


def test_the_counts_always_add_up_and_the_attempts_are_counted_honestly(store: Store):
    """反真空：`counts` 之和 == `rows[]` 长度；`attempted` == 真发出去的请求数。

    没有这条，一个"永远回空 rows + 全 0"的实现会静默通过上面全部判据
    （空表在下游是一个看起来完全合理的结论）。
    """
    _pending_row(store, "0001", "https://arxiv.org/pdf/1")
    _pending_row(store, "0002", "https://projecteuclid.org/a")
    _row(store, "0003", download={"status": "failed", "error": "no_open_access_location"})
    dl = _ScriptedDownloader([("ok", b"%PDF-1.4 a\n"), ("fail", "tls_cert")])

    res = _retry(store, dl)
    assert res.ok, res.error
    data = res.data
    assert sum(data["counts"].values()) == len(data["rows"]) == 3, data
    assert data["attempted"] == len(dl.calls) == 2, (data["attempted"], dl.calls)
    # 同一个数组里每个元素的键集合必须一样（下游要能逐条读）
    keysets = {tuple(sorted(r)) for r in data["rows"]}
    assert len(keysets) == 1, keysets


def test_without_a_store_it_refuses_instead_of_reporting_nothing_to_retry(store: Store):
    """负控（三态）：没有 store ⇒ `no_store` 受控失败，绝不是"没有要重取的行"。"""
    res = _registry(None, _ScriptedDownloader([])).call("search.retry_pending")
    assert not res.ok, res.data
    assert res.meta.get("kind") == "no_store", res.meta
    assert "counts" not in (res.data or {}), res.data


def test_a_corrupt_literature_table_is_not_an_empty_retry_list(store: Store):
    """负控（三态）：表读不出来 ⇒ `table_unreadable`，不是"零条待取"。"""
    (store.root / "data" / "literature.json").write_text("{ 这不是 JSON", encoding="utf-8")
    res = _retry(store, _ScriptedDownloader([]))
    assert not res.ok, res.data
    assert res.meta.get("kind") == "table_unreadable", res.meta
    assert "counts" not in (res.data or {}), res.data


def test_the_limit_bounds_how_many_rows_one_call_touches(store: Store):
    """`limit` 是这次调用最多碰几行（省钱的那一格）；没碰到的行仍是待取。"""
    for i in range(3):
        _pending_row(store, f"{i:04d}", f"https://arxiv.org/pdf/{i}")
    dl = _ScriptedDownloader([("ok", b"%PDF-1.4 a\n"), ("ok", b"%PDF-1.4 b\n"),
                              ("ok", b"%PDF-1.4 c\n")])

    res = _retry(store, dl, limit=2)
    assert res.ok, res.error
    data = res.data
    assert len(data["rows"]) == 2 and data["stopped"] == "limit", data
    assert dl.calls == ["https://arxiv.org/pdf/0", "https://arxiv.org/pdf/1"], dl.calls
    shelf = _registry(store).call("search.shelf")
    assert (shelf.data["coverage"]["with_fulltext"], shelf.data["coverage"]["missing"]) == (2, 1)
