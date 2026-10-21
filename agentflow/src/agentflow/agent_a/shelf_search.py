"""角色 A 的动作 `shelf_search`（裁决 2 的族 1：`search.shelf` / `search.local` 的动作面）。

为什么需要（真机读数逼出来的那一格）：两件工具在 A/C/H 的工具面上，但动作面（`specs/a.py` 的
`ACTIONS`）里一个都没有 —— 主控只能 `conductor.summon` 动作，于是"在本地书架上找一找"派不出去；
后果与 `agent_a/ingest_local.py` 那一格同型（工具层通、编排层不通 ⇒ 盘上有全文，编排层看不见它）。
它服务的是一条不联网也能推进研究的路：全文已在盘上的文献本身就是可引用的来源，"缺哪条证据就去找
哪一条"不该每次都出网（`#1` 那一类无意义/重复外出的正解之一）。

一份口径，不是两份：本动作只调那两件工具（`search.shelf` 必调；`search.local` 给了 `query` 才调），
不另写一套检索；两件都是 `side_effect="read"`，所以本动作只读、不出网、一条判据都不改
（`T-8` 口径：工具层的判据是禁改面，这里只是"多一个入口"）。

三态纪律（这是它与"返回一个空书架"的分界）：工具报"没数成"（`ok=False` + `kind`）⇒ 原样透传，
不折成"书架是空的"；书架上真的没有全文在盘的文献 ⇒ `count=0` + `shelf.have_path=0`（有效结论）；
给了 `query` 但没命中 ⇒ `local.hits=[]`、`excerpt_count=0`（查了、没有）；没给 `query` ⇒
`local=None`（没查，不是"查了没命中"）。三处"这次调用本身不成立"走 :func:`agentflow.refusals.refuse`
（`draft/37` §88）：没有 store / `query` 不是字符串 / `limit` 非法。
"""
from __future__ import annotations

from ._support import Any, Path, Store
from ..refusals import refuse


def _tool_ctx(store: Store, actor: str) -> Any:
    """按工具层的装配口径造一个 `_Ctx`（与 `search_tools.register` 里那份同型）。

    为什么复用工具层的 `_Ctx` 而不是自带一个轻量对象：两件工具要的
    `workspace` / `store` / `actor` 三个字段的语义由那边定义
    （`workspace` 是解析相对路径的根）。自带一份会在"相对路径往哪解析"
    这种地方悄悄分叉，而分叉的表现是"工具找得到、动作找不到"。
    """
    from ..tools.search_tools import _Ctx

    root = Path(getattr(store, "root", ".")).resolve()
    return _Ctx(workspace=root, store=store, actor=str(actor or "agent-A"))


class _ShelfSearch:
    def shelf_search(self, *, query: str = "", limit: int = 20, lit_id: str = "",
                     local_limit: int = 5, max_chars: int = 1200) -> dict:
        """在本地书架上找文献：先列全文在盘的（`search.shelf`），再按需取逐字摘录。

        参数：query（可选，给了才调 `search.local`；不给只列清单 —— "列清单"与"找内容"是两件事）、
        limit（清单最多几本，工具侧上限 500）、lit_id（可选，只处理这一篇）、local_limit / max_chars
        （摘录条数与每段字符上限，工具侧 20 / 8000）。
        返回 `{"ok", "kind", "count", "shelf", "local", "lit_ids", "hits", "excerpt_count", "note"}`：
        `ok=True` 只说这次调用做完了，有没有找到东西看 `count` / `excerpt_count`；`shelf` / `local` 是
        两件工具的原样读数（"没数成"＝`ok=False` 与"查了、没有"从这两格分开读）；`local is None` =
        没给 `query` ⇒ 没查（第三态）。
        """
        from ..tools.search_tools import _h_local, _h_shelf

        if self.store is None:  # pragma: no cover - 装配面保证有 store；拒比"空书架"安全
            return refuse("no_store", "A 没有 store ⇒ 这次书架检索无从做起（零写入）")
        cap = int(limit)
        if cap < 1:
            return refuse("bad_limit", f"limit 必须 >= 1，收到 {limit!r}")
        if query is not None and not isinstance(query, str):
            return refuse("bad_query", f"query 必须是字符串，收到 {type(query).__name__}")
        text = "" if query is None else str(query).strip()

        ctx = _tool_ctx(self.store, self.actor)
        # ⚠️ 「2026-10-16（亲测时由判据当场抓出来的）」：`query` 此前「只」给了
        # `search.local`，「没给 `search.shelf`」 ⇒ 于是"带条件问书架"会「静默地」
        # 返回一份未过滤的清单（不报错、只是忽略条件）—— 那正是"让人困惑并浪费 token"
        # 的一类。现在两件工具都收到同一个 `query`：书架负责「按题名/路径过滤清单」，
        # `search.local` 负责「按主题取逐字摘录」（分工写进两边的说明）。
        shelf = _h_shelf(ctx, limit=cap, lit_id=str(lit_id or ""), query=text)
        shelf_ok = bool(getattr(shelf, "ok", False))
        shelf_data = dict(getattr(shelf, "data", None) or {})
        books = list(shelf_data.get("books") or [])
        lit_ids = [str(b.get("lit_id") or "") for b in books if b.get("lit_id")]

        local: Any = None
        hits: list[dict] = []
        if text:
            got = _h_local(ctx, query=text, limit=int(local_limit), max_chars=int(max_chars),
                           lit_id=str(lit_id or ""))
            local_data = dict(getattr(got, "data", None) or {})
            local = {
                "ok": bool(getattr(got, "ok", False)),
                "error": str(getattr(got, "error", "") or ""),
                "kind": str(getattr(got, "meta", {}).get("kind") or ""),
                "data": local_data,
            }
            hits = list(local_data.get("hits") or [])

        # 三态：两格里各自的失败原样透传；`kind` 取第一个非空的失败档（便于主控一眼归因）。
        failed = [str(getattr(shelf, "meta", {}).get("kind") or "") if not shelf_ok else "",
                  str((local or {}).get("kind") or "") if local and not local["ok"] else ""]
        kind = next((k for k in failed if k), "")
        pieces = [f"书架清单：{len(books)} 本全文在盘（工具读数 rows_total="
                  f"{shelf_data.get('rows_total')} / have_path={shelf_data.get('have_path')}）"]
        if local is None:
            pieces.append("没有给 `query` ⇒ 这一次**没有查内容**（不是「查了、没命中」）")
        else:
            pieces.append(f"按主题取摘录：{len(hits)} 条命中"
                          f"（scanned={local['data'].get('scanned')}）")
        return {
            "ok": bool(shelf_ok and (local is None or local["ok"])),
            "kind": kind,
            "count": len(books),
            "shelf": {"ok": shelf_ok, "error": str(getattr(shelf, "error", "") or ""),
                      "kind": str(getattr(shelf, "meta", {}).get("kind") or ""),
                      "data": shelf_data},
            "local": local,
            "lit_ids": lit_ids,
            "hits": hits,
            "excerpt_count": len(hits),
            "note": "；".join(pieces) + "。`ok` 只说这次调用做完了："
                    "找到了什么看 count / excerpt_count；工具报「没数成」时 "
                    "shelf.ok / local.ok 都是 False（那是第三态，不是「书架是空的」）。",
        }
