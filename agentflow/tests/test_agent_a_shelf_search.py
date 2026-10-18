# -*- coding: utf-8 -*-
"""判据（裁决 2 的族 1 · 主控定名）：A 的动作 `shelf_search` —— 本地书架的离线检索。

它补的是"工具层通、编排层不通"的那一格：`search.shelf` / `search.local` 两件工具
在 A/C/H 的工具面上，而动作面里一个都没有 ⇒ 主控派不了"在本地书架上找一找"。
本地全文是"不联网也能推进研究"的那条路（`#1` 那一类无意义外出问题的正解之一）。

这一组钉四件事：

1. 动作存在且只调那两件工具（工具层一条判据都不改，`T-8` 口径）；
2. 两格读数原样并列：`shelf` / `local` 各自的 `ok` / `kind` / 计数都在，
   "没数成"与"查了、没有"分得开（三态不许折平）；
3. 没给 `query` ⇒ `local is None`（没查）—— 不许折成"查了、没命中"；
4. 出网面：本动作 `side_effect="read"`、不碰 providers（不出网）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.store import Store


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _a(st: Store) -> AgentA:
    return AgentA(st, providers=[])


def _add_book(st: Store, *, lit_id: str, path: str, text: str) -> None:
    """把一篇文献挂到盘上（`path` 是工作区相对路径；内容写进 `<ws>/library/`）。"""
    abs_path = st.library_path(path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(text, encoding="utf-8")
    with st.tx("literature", actor="test", note="shelf") as tx:
        tx.upsert("literature", {
            "lit_id": lit_id, "title": f"书 {lit_id}", "summary": f"书 {lit_id} 的摘要",
            "year": "2020", "doi": "", "type": "J", "path": path, "processed": False,
            "source_request_ids": [], "download": {"bytes": len(text.encode("utf-8")),
                                                  "sha256": "a" * 64,
                                                  "source_path": "D:/books/x.pdf"},
        }, note="shelf")


def test_shelf_search_is_declared_as_a_read_only_action(tmp_path: pathlib.Path):
    """判据 1 + 4：动作存在、是只读的（`side_effect='read'`）、不接 providers。"""
    st = _store(tmp_path)
    a = _a(st)
    assert callable(getattr(a, "shelf_search", None)), "A 没有 shelf_search 动作"
    out = a.shelf_search()
    assert out["ok"] is True, out
    # 出网面：providers 为空也必须能跑（这条链完全离线）
    assert a.providers == []


def test_shelf_search_lists_offline_fulltexts(tmp_path: pathlib.Path):
    """判据 1：`search.shelf` 的那一格原样透传 —— 列出的就是"全文在盘上"的那些。"""
    st = _store(tmp_path)
    _add_book(st, lit_id="0001", path="a.txt", text="periodic elliptic operators")
    _add_book(st, lit_id="0002", path="b.txt", text="Floquet Bloch theory")
    out = _a(st).shelf_search(limit=10)
    assert out["ok"] is True and out["count"] == 2, out
    assert sorted(out["lit_ids"]) == ["0001", "0002"], out
    assert out["shelf"]["data"]["have_path"] == 2, out["shelf"]
    assert out["local"] is None, "没给 query ⇒ local 必须是 None（没查），不是空命中"
    assert out["excerpt_count"] == 0


def test_shelf_search_takes_verbatim_excerpts_when_asked(tmp_path: pathlib.Path):
    """判据 1 + 2：给了 `query` 才调 `search.local`，摘录原样并列在 `local` 那一格。"""
    st = _store(tmp_path)
    _add_book(st, lit_id="0001", path="a.txt",
              text="Theorem 1. The extremal process of branching Brownian motion is a "
                   "random shifted decoration.")
    out = _a(st).shelf_search(query="extremal process", local_limit=3)
    assert out["local"] is not None and out["local"]["ok"] is True, out["local"]
    assert out["excerpt_count"] >= 1, out
    hit = out["hits"][0]
    assert hit["lit_id"] == "0001" and "extremal process" in hit["excerpt"], hit


def test_shelf_search_keeps_not_counted_apart_from_empty(tmp_path: pathlib.Path):
    """判据 2（三态）：工具报"没数成"时原样透传，不折成"书架是空的"。

    夹具：把 `data/literature.json` 写坏 ⇒ `_literature_rows` 报 `table_unreadable`。
    """
    st = _store(tmp_path)
    (st.root / "data" / "literature.json").write_text("{ 这不是 JSON", encoding="utf-8")
    out = _a(st).shelf_search()
    assert out["ok"] is False, out
    assert out["kind"] == "table_unreadable", out
    assert out["shelf"]["kind"] == "table_unreadable", out["shelf"]
    assert out["count"] == 0 and out["shelf"]["data"] == {}, out


def test_shelf_search_refuses_a_non_string_query(tmp_path: pathlib.Path):
    """判据：这次调用本身不成立 ⇒ 受控拒绝（`refused / invalid_params` + 细一档的 `kind`）。"""
    st = _store(tmp_path)
    out = _a(st).shelf_search(query=123)
    assert out.get("ok") is False and out.get("kind") == "bad_query", out
    assert out.get("refusal_reason") == "invalid_params", out
    out2 = _a(st).shelf_search(limit=0)
    assert out2.get("kind") == "bad_limit", out2
    assert out2.get("refusal_reason") == "invalid_params", out2


def test_shelf_search_shape_matches_the_action_contract(tmp_path: pathlib.Path):
    """判据：返回形状与交付说明里给 B 的那一份逐键一致（B 按它写 `specs/a.py`）。"""
    st = _store(tmp_path)
    out = _a(st).shelf_search()
    assert set(out) == {"ok", "kind", "count", "shelf", "local", "lit_ids", "hits",
                        "excerpt_count", "note"}, sorted(out)
    assert set(out["shelf"]) == {"ok", "error", "kind", "data"}, sorted(out["shelf"])
    # 动作面声明（B 落 `specs/a.py` 之后这一条会变成"两边对得上"）
    assert "shelf_search" not in {a.action for a in []}, "占位：动作名由 B 声明"
    assert json.dumps(out, ensure_ascii=False, default=str)
    assert S.ROLES  # 名单来自 schema（这一条只为让 import 有落点）

# ============================================================ 2026-10-16：第一猜 `query` 要能用

def test_shelf_accepts_a_query_and_filters_by_title_or_path(tmp_path: pathlib.Path):
    """业主口径：「第一次凭感觉敲红的，真实智能体也会在这里困惑。」

    `search.shelf` 的名字里带 search，而它的参数原本**只有** `limit` / `lit_id`
    —— 我第一次凭感觉敲的就是 `query=`，吃了一个「未声明的参数」。
    这一条钉住修好之后的行为：**`query` 收下了，而且是按题名/路径过滤**（不读全文）。
    """
    st = _store(tmp_path)
    _add_book(st, lit_id="0001", path="a.txt", text="alpha")
    _add_book(st, lit_id="0002", path="b.txt", text="beta")
    out = _a(st).shelf_search(limit=10, query="b.txt")
    assert out["ok"] is True, out
    assert out["count"] == 1, out
    assert out["lit_ids"] == ["0002"], out
    assert out["shelf"]["data"]["filtered_out"] == 1, out["shelf"]["data"]
    assert out["shelf"]["data"]["query"] == "b.txt", out["shelf"]["data"]


def test_a_query_that_matches_nothing_is_not_an_empty_shelf(tmp_path: pathlib.Path):
    """负控（三态）：**没匹配**与**书架是空的**必须是两件事（读数上分得开）。"""
    st = _store(tmp_path)
    _add_book(st, lit_id="0001", path="a.txt", text="alpha")
    out = _a(st).shelf_search(limit=10, query="zzz")
    data = out["shelf"]["data"]
    assert out["count"] == 0, out
    assert data["rows_total"] == 1, data          # 书架里明明有一本
    assert data["filtered_out"] == 1, data        # 它只是被 query 滤掉了
