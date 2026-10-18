# -*- coding: utf-8 -*-
"""**只有元数据的文献，必须在看板上变成"该去补全文"的待办**（T5 第 2 趟驱动）。

那趟的答案自己写着"Frey 曲线：未核到"，而**没有任何后续动作** —— 因为"缺一篇"这件事
只活在模型的文字里，**台账上看不见**，主控也就无从派活。

修法：`Conductor.board_view` 把 `path` 空或 `download.status` 不是 ok 的在册文献
亮成 `pending_search` 板项（只亮、不点名动作）。两态都钉：
"""

from __future__ import annotations

import pathlib

from agentflow.conductor import Conductor
from agentflow.store import Store


def _row(st: Store, lit_id: str, path: str, status: str) -> None:
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", {"lit_id": lit_id, "title": f"t{lit_id}", "summary": "s",
                                 "year": "2022", "doi": "", "type": "J", "path": path,
                                 "processed": bool(path), "source_request_ids": [],
                                 "download": {"status": status}})


def test_a_metadata_only_literature_row_shows_up(tmp_path: pathlib.Path) -> None:
    """正控：只有元数据（`path` 空 / 下载没成）⇒ 板上有一条 `pending_search`。"""
    st = Store(tmp_path / "ws")
    st.init()
    _row(st, "000001", "", "skipped")
    view = Conductor(store=st).board_view(limit=50)
    assert view.get("pending_search_count") == 1, view
    assert [r.get("kind") for r in (view.get("open_items") or [])] == ["pending_search"]


def test_a_full_text_row_is_not_flagged(tmp_path: pathlib.Path) -> None:
    """负控：有全文（`path` ＋ `status=ok`）⇒ **不许**被亮成待办（不然板会被人为放大）。"""
    st = Store(tmp_path / "ws")
    st.init()
    _row(st, "000002", "a.pdf", "ok")
    view = Conductor(store=st).board_view(limit=50)
    assert view.get("pending_search_count") is None, view
