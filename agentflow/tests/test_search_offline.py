"""A 的「离线」文献来源：`search.shelf` 与 `search.local`（`draft/28` §187）。

## 这一组守什么

`draft/28` §184.5 第 4 步的判据：A 原先只有联网 provider（`search.literature` /
`search.providers` 都要出网），一旦没有网络，A 就"看不到任何文献" ——
而工作区里明明躺着已经下好的全文（真机账：`projects/p2-review/` 有 38 份在盘上，
98 条 literature 行里 60 条只有元数据没有全文）。这两种情况在旧的工具面上长得一样：
A 会如实报告"检索不到"，而真实原因是"没有源可用"。

所以这一组守两条性质：

1. 「离线可得」：书架上有什么、某主题在哪一页，都要能「不联网」答出来，
   而且摘录必须是原文里连续的一段（引文回验比的就是它）。
2. 「"没数成" ≠ "书架是空的"」：没有 store / 表读不出来时一律 `fail` +
   `counted=False`/`searched=False`，绝不给一个空列表 —— 空列表在下游是一个
   有效结论（"书架上没有"），折叠两者会让 A 静悄悄地失去来源而不自知。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import search_tools
from agentflow.tools.base import ToolRegistry


def _registry(store: Store | None, workspace: Path | None = None) -> ToolRegistry:
    """建一个绑定 A 的注册表（`P-14`：`search.*` 的 roles 只有 A）。"""
    reg = ToolRegistry(name="search-offline")
    reg.bound_role = "A"
    search_tools.register(reg, store=store, workspace=workspace or (store.root if store else None))
    return reg


def _put_book(store: Store, lit_id: str, title: str, pages_text: list[str], name: str) -> str:
    """在库里放一本书：真写一份文件 + 一行 literature（`path` 指向它）。

    刻意走 store 的公开路径（`library_path` / `tx`），不手搓内部结构：
    这样"书在不在盘上"这件事与生产路径是同一个判据。
    """
    rel = f"{lit_id}/{name}"
    dest = Path(store.library) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(pages_text), encoding="utf-8")
    with store.tx("literature", "counters", actor="test") as tx:
        tx.upsert(
            "literature",
            S.Literature(
                lit_id=lit_id,
                title=title,
                type="M",
                summary="测试用书",
                path=rel,
                processed=False,
                added_at=S.now_iso(),
                download={"status": "ok", "note": "本地文件（不是网络下载）", "pages": len(pages_text),
                          "has_text_layer": True, "bytes": dest.stat().st_size,
                          "sha256": "0" * 64, "source_path": str(dest)},
            ).to_dict(),
        )
    return rel


# ============================================================ search.shelf


def test_shelf_lists_only_books_whose_full_text_is_on_disk(store: Store):
    """正控：有全文的行进书架；只有元数据（`path` 为空）的行不进，并如实计入 `rows_total`。"""
    _put_book(store, "0001", "群论讲义", ["第一章 群的定义。", "第二章 商群。"], "book.txt")
    with store.tx("literature", "counters", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0002", title="只有元数据的文献", type="J",
                                             summary="没有全文", path=None, processed=False,
                                             added_at=S.now_iso()).to_dict())

    res = _registry(store).call("search.shelf")
    assert res.ok, res.error
    data = res.data
    assert data["count"] == 1, data
    assert data["rows_total"] == 2, data
    assert data["missing_files"] == 0, data
    assert [b["lit_id"] for b in data["books"]] == ["0001"]
    assert data["books"][0]["origin"] == "local_ingest", data["books"][0]


def test_shelf_counts_a_row_whose_file_vanished_as_missing_not_as_absent(store: Store):
    """负控（三态）：行上写了 path、文件却不在盘上 ⇒ 记 `missing_files`，不静默当成没有这本书。"""
    rel = _put_book(store, "0001", "会被删掉的书", ["一句话。"], "gone.txt")
    (Path(store.library) / rel).unlink()

    res = _registry(store).call("search.shelf")
    assert res.ok, res.error
    assert res.data["count"] == 0 and res.data["missing_files"] == 1, res.data
    assert res.data["have_path"] == 1, res.data


def test_shelf_without_a_store_is_not_checked(store: Store):
    """负控（三态）：没有 store ⇒ `fail` + `counted=False`，绝不是"书架是空的"。"""
    res = _registry(None, workspace=store.root).call("search.shelf")
    assert not res.ok, res.data
    assert res.meta.get("kind") == "no_store", res.meta
    assert res.meta.get("counted") is False, res.meta


def test_shelf_can_be_narrowed_to_one_lit_id(store: Store):
    """正控（参数面）：`lit_id` 只影响返回的那一条，`rows_total` 仍是全表 —— 两个数不许混。"""
    _put_book(store, "0001", "甲书", ["甲。"], "a.txt")
    _put_book(store, "0002", "乙书", ["乙。"], "b.txt")
    res = _registry(store).call("search.shelf", lit_id="0002")
    assert res.ok, res.error
    assert [b["lit_id"] for b in res.data["books"]] == ["0002"], res.data
    assert res.data["rows_total"] == 2 and res.data["count"] == 1, res.data


# ============================================================ search.local


def test_local_returns_a_verbatim_contiguous_excerpt_with_page_and_lit_id(store: Store):
    """正控（离线可得）：摘录必须是原文里连续的一段（引文回验比的就是它）。

    判据写成"摘录是「盘上那份文本」的连续子串"而不是"是某一段的字面量"：
    文本文件被 `extract_text` 当成一整页（这条实测过），所以"页"这一层是
    `extract` 给的口径，不是我在测试里假设的口径 —— 判据必须跟着真口径走。
    """
    body = "第一章：群是带运算的集合。\n这一页讲商群：设 N 是 G 的正规子群，则 G/N 是一个群，称为商群。\n第三章：同态基本定理。"
    _put_book(store, "0001", "群论讲义", [body], "book.txt")

    res = _registry(store).call("search.local", query="商群 正规子群", limit=2, max_chars=400)
    assert res.ok, res.error
    data = res.data
    assert data["searched"] is True and data["count"] >= 1, data
    hit = data["hits"][0]
    assert hit["lit_id"] == "0001" and hit["page"] >= 1, hit
    assert hit["excerpt"] and hit["excerpt"] in body, (
        "摘录不是原文的连续子串 ⇒ 模型照抄也过不了逐字回验"
    )
    assert "商群" in hit["excerpt"], hit
    # 三个"这一本没查到"的理由必须分开报（而不是只给一个空列表）
    assert set(data) >= {"skipped_no_file", "unreadable", "no_text_layer"}, data


def test_local_reports_unreadable_books_separately_from_empty_hits(store: Store):
    """负控（三态）：书在盘上但抽不出正文（坏文件）⇒ 记 `unreadable`，与"没有命中"分开。"""
    rel = "0001/broken.pdf"
    dest = Path(store.library) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4 this is not a real pdf")
    with store.tx("literature", "counters", actor="test") as tx:
        tx.upsert("literature", S.Literature(lit_id="0001", title="坏书", type="M", summary="x",
                                             path=rel, processed=False, added_at=S.now_iso(),
                                             download={"status": "ok", "note": "本地文件",
                                                       "pages": 1, "has_text_layer": True,
                                                       "bytes": dest.stat().st_size,
                                                       "sha256": "0" * 64}).to_dict())

    res = _registry(store).call("search.local", query="任何主题")
    assert res.ok, res.error
    assert res.data["count"] == 0, res.data
    assert res.data["unreadable"], "抽不出来的书必须逐本记下来，不能只是没有命中"
    assert res.data["scanned"] == 1, res.data


def test_local_ranks_books_by_relevance_not_by_excerpt_length(store: Store):
    """负控（§187 真机读数逼出来的判据）：排序键必须是相关度，不是摘录长度。

    造法：两本书都长得足够让窗口取满（于是"摘录长度"两者相等），
    而甲书真正谈这件事、乙书只顺带提了一个词。旧实现按 `-len(excerpt)` 排、
    并列时按 `lit_id` 字母序 ⇒ 乙书（0001）会排在甲书（0002）前面。
    真机上这个缺陷的表现是：query "martingale central limit theorem" 的第三名
    是一篇讲伊朗城市的论文（它命中的是 `central`）。
    """
    long_noise = "这是一段与主题无关的长文本。" * 40
    _put_book(store, "0001", "只顺带提一个词的书",
              [f"central 这个词出现了一次。{long_noise}"], "noise.txt")
    _put_book(store, "0002", "真正谈这件事的书",
              [f"martingale central limit theorem 讲的是鞅的中心极限定理。{long_noise}"], "real.txt")

    res = _registry(store).call("search.local", query="martingale central limit theorem",
                                limit=2, max_chars=400)
    assert res.ok, res.error
    hits = res.data["hits"]
    assert [h["lit_id"] for h in hits] == ["0002", "0001"], (
        f"排序没按相关度走：{[(h['lit_id'], h['score']) for h in hits]}"
    )
    assert hits[0]["score"] > hits[1]["score"], hits
    # 同一份口径：工具报的 score 必须就是 `locallib.page_scores` 的那个数
    # （否则"工具说它最相关"与"挑页用的是另一把尺子"会各说各话）。
    from agentflow import locallib as LL

    noise = f"central 这个词出现了一次。{long_noise}"
    real = f"martingale central limit theorem 讲的是鞅的中心极限定理。{long_noise}"
    assert LL.page_scores([noise], "martingale central limit theorem")[0] == hits[1]["score"]
    assert LL.page_scores([real], "martingale central limit theorem")[0] == hits[0]["score"]


def test_local_without_a_store_is_not_checked(store: Store):
    """负控（三态）：没有 store ⇒ `fail` + `searched=False`（没做成检索 ≠ 没有命中）。"""
    res = _registry(None, workspace=store.root).call("search.local", query="群")
    assert not res.ok
    assert res.meta.get("kind") == "no_store" and res.meta.get("searched") is False, res.meta


def test_local_does_not_egress(store: Store, monkeypatch: pytest.MonkeyPatch):
    """判据（离线这一条本身）：两个新工具的副作用面是 `read` 且「不出网」。

    为什么值得一条测试：`search.providers` / `search.literature` 的 `declared_external`
    是 `egress`（要审批）。新工具若被声明成出网，就等于"离线来源也要审批"；
    若声明成 `read` 而实际出网，则是权限面说谎。这里直接把 socket 封死来证否。
    """
    import socket

    def _boom(*a, **kw):  # noqa: ARG001
        raise AssertionError("离线工具不该建 socket")

    monkeypatch.setattr(socket, "socket", _boom)
    _put_book(store, "0001", "甲书", ["群是带运算的集合。"], "a.txt")
    reg = _registry(store)
    for name in ("search.shelf", "search.local"):
        spec = reg.get(name)
        assert spec.side_effect == "read", (name, spec.side_effect)
        assert spec.external == "none", (name, spec.external)
    assert reg.call("search.shelf").ok
    assert reg.call("search.local", query="群").ok


def test_the_offline_pair_is_declared_in_the_catalog_the_llm_sees(store: Store):
    """判据（提示词面）：工具目录里必须看得见这两个工具 —— 看不见就等于没有。"""
    catalog = _registry(store).text_catalog(role="A")
    for name in ("search.shelf", "search.local"):
        assert name in catalog, f"{name} 没有出现在 A 看到的目录里"
    assert "不联网" in catalog, "目录里要说清哪几个是不联网的（否则 A 无网时不知道还有路）"


def test_the_two_layer_capability_reconciliation_still_holds():
    """判据（接线面）：新增工具不许把能力层的两层对账弄红。

    为什么要点名跑它：`capabilities.py` 是 FC-27 禁改区，新工具的副作用/外部性
    只能靠「声明正确」来满足它，改不了那张表。这条测试把"我没动禁改区、也没让
    导入期断言变红"变成一个可复跑的读数，而不是一句承诺。
    """
    from agentflow import capabilities as C

    C.assert_capabilities()
    recon = C.two_layer_reconciliation()
    assert recon["compared"], recon
    assert json.dumps(recon, ensure_ascii=False, default=str)
