# -*- coding: utf-8 -*-
"""`text.extract` 不许留下幽灵文件（T5 第 2 趟真机读数驱动，2026-10-17）。

## 现场

A 在真机上调的是 `text.extract({"lit_id": "lit:000000"})`（带 `lit:` 前缀）。
原实现把 `lit_id` 原样拼进文件名 ⇒ `lit:000000.txt` ⇒ 在 Windows 上那是个
NTFS 备用数据流（`lit` 文件的 ADS）⇒ 盘上留下一个 0 字节、无扩展名的
`library/lit`，谁也看不出它是谁写的。

## 修法

`_safe_stem()`：取冒号后的裸编号，再把 Windows 非法字符替换成 `_`。

这一组钉两件事（含负控）：
1. 带前缀的 `lit_id` ⇒ 落 `library/<裸编号>.txt`（文件名里没有冒号）；
2. 负控：`library/` 里不许出现"无扩展名的残留文件"（幽灵文件的形态）。
"""

from __future__ import annotations

import pathlib
import shutil

from agentflow.store import Store
from agentflow.tools import build_registry

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PDF = sorted((_ROOT / "temp" / "_lit_dl").glob("*.pdf"))


def _wired(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    if _PDF:
        shutil.copy2(_PDF[0], st.library_path(_PDF[0].name))
        name = _PDF[0].name
    else:                                    # 没有夹具时造一份"纯文本直通"的目标
        name = "source.txt"
        st.library_path(name).write_text("probe text\n", encoding="utf-8")
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", {"lit_id": "000000", "title": "p", "summary": "s",
                                 "year": "2022", "doi": "", "type": "J", "path": name,
                                 "processed": False, "source_request_ids": [],
                                 "download": {"status": "ok"}})
    return ws, build_registry(store=st, workspace_root=ws).registry


def test_a_prefixed_lit_id_lands_as_a_bare_named_txt(tmp_path: pathlib.Path) -> None:
    """正控：`lit_id="lit:000000"` ⇒ `library/000000.txt`，文件名里没有冒号。"""
    ws, reg = _wired(tmp_path)
    res = reg.call("text.extract", role="A", lit_id="lit:000000")
    data = dict(getattr(res, "data", None) or {})
    assert res.ok is True, (res, data)
    assert data.get("path") == "library/000000.txt", data.get("path")
    assert ":" not in str(data.get("path")), data.get("path")
    assert (ws / "library" / "000000.txt").is_file()


def test_no_extensionless_ghost_file_is_left(tmp_path: pathlib.Path) -> None:
    """负控：`library/` 里不许出现无扩展名的残留（幽灵文件的形态）。"""
    ws, reg = _wired(tmp_path)
    reg.call("text.extract", role="A", lit_id="lit:000000")
    ghosts = [p.name for p in (ws / "library").iterdir()
              if p.is_file() and not p.suffix]
    assert ghosts == [], f"留下了幽灵文件：{ghosts}"
