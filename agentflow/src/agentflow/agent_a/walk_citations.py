"""角色 A 的动作 `walk_citations`（引文图那一步的**动作面**）。

业主 2026-10-15 逐字裁定：**「引文图是用新动作的方式落」**。

## 为什么必须有这一格（工具通了 ≠ 派得出去）

工具面 `search.walk_citations` 通了，不等于**编排层**能用它：主控只能
`conductor.summon` **动作**，而能力表里的每个动作都必须在 `AgentA` 上有一个
真实的公开方法 —— 这一条由 `capabilities.assert_capabilities()` 在**导入期**断言
（逐字：「能力表里的动作必须是真实代码里存在的公开方法，不许编造」）。
实测：先在 `specs/a.py` 里加动作、没写这个方法 ⇒ `import agentflow.capabilities`
当场以 `AssertionError: AgentA 上没有可调用的 'walk_citations'` 失败。
所以"引文图"要真能派出去，就得有这一格。

## 与工具层的关系（一份实现，不是两份）

本动作只调 `_h_walk_citations` 那**一个**工具处理器，不另写一套走查
（`T-8` 口径：工具层的判据是禁改面，这里只是"多一个入口"）。
它**只读**：没有写集，也**不替调用方判重或登记** ——
候选要不要、怎么进台账，走既有的 `search.dedup_check` → `search.register`。
为什么刻意不在这里登记：判重（`dedup_key` / `existing` / `is_new`）在本仓只有
一处实现，在动作层再写一份就是第二份"同一篇文献该不该合并"的判断，
而它漂了不会报错（这正是 `dedup.py` 被划进禁改区的那条理由）。

## 三态纪律（这是它与"返回一个空列表"的分界）

| 情形 | 落点 |
|---|---|
| 工具报"没做成"（`ok=False` ＋ `kind`） | **原样透传**（`unknown_lit_id` / `table_unreadable` / `no_store` / ...） |
| 走查做成了、这一篇这一侧确实没有邻居 | `count=0`（**有效结论**，不是失败） |
| 这次调用本身不成立 | `refuse(...)`（`draft/37` §88）：没 store / `lit_id` 空 / `direction` 非法 / `limit` < 1 |
"""
from __future__ import annotations

from .shelf_search import _tool_ctx
from ..refusals import refuse

#: 与工具面 `search.walk_citations` 的 `limit` 上限**同一个数**（那里是 schema 的 maximum）。
#: 这里再写一次是刻意的：动作层直接调工具处理器（不过注册表的 schema 校验），
#: 所以"上限"这件事必须在动作层自己守住，否则一条 `limit=100000` 的派活能把走查拉爆。
_MAX_LIMIT = 50


class _WalkCitations:
    def walk_citations(self, *, lit_id: str, direction: str = "backward",
                       limit: int = 20) -> dict:
        """由一篇**已登记的**文献出发走一步引文图（回溯 / 前推）。

        参数
        ----
        lit_id : 必给。盘上 `literature` 表的行号 —— 走查从**我们手上这一篇**出发
            （拿它的 DOI / OpenAlex id）。不接受任意 DOI：那样它就成了第二个检索入口，
            而"检索"这件事的账只在 `search_literature` 那一处记。
        direction : `backward`（这一篇**引了谁**）/ `forward`（**谁引了这一篇**）。
        limit : 最多交回几条候选，上限 50（与工具面同一格）；超出**截到 50 并在 note 里说明**。

        返回（给编排层读的形状）
        ----
        `{"ok", "kind", "lit_id", "doi", "openalex_id", "direction", "count",
        "candidates", "truncated_to_tool_max", "note"}`

        - `ok=True` 只说**这次走查做完了**；走到了什么看 `count` / `candidates`；
        - `ok=False` 时要读 `kind`（`unknown_lit_id` = 你说的那一篇不在表里、
          `table_unreadable` = 表坏了没读成、`no_source_key` = 这一行没有 doi/OpenAlex id）——
          这三种**都不是**"它没有引文邻居"；
        - `candidates[]` 带 `is_oa` 与 `oa_source`：前者说这一篇是不是开放获取，
          后者说那条可取全文的链接**是从哪个位置来的**（`best_oa_location` 是 OpenAlex
          按定义算出来的最佳合法 OA 位置）。
        """
        from ..tools.search_tools import _h_walk_citations

        if self.store is None:  # pragma: no cover - 装配面保证有 store
            return refuse("no_store", "A 没有 store ⇒ 不知道这一篇是哪一篇（零写入）")
        want = str(lit_id or "").strip()
        if not want:
            return refuse("bad_lit_id", f"lit_id 必须给（收到 {lit_id!r}）：走查要有起点")
        direct = str(direction or "").strip().lower()
        if direct not in ("backward", "forward"):
            return refuse("bad_direction",
                          f"direction 只能是 backward / forward，收到 {direction!r}")
        try:
            asked = int(limit)
        except (TypeError, ValueError):
            return refuse("bad_limit", f"limit 必须是整数，收到 {limit!r}")
        if asked < 1:
            return refuse("bad_limit", f"limit 必须 >= 1，收到 {limit!r}")
        cap = min(asked, _MAX_LIMIT)

        ctx = _tool_ctx(self.store, self.actor)
        got = _h_walk_citations(ctx, want, direct, cap)
        ok = bool(getattr(got, "ok", False))
        data = dict(getattr(got, "data", None) or {})
        kind = str(getattr(got, "meta", {}).get("kind") or "")
        cands = list(data.get("candidates") or [])
        truncated = asked > _MAX_LIMIT
        pieces = [
            f"引文走查（{direct}）：交回 {len(cands) if ok else 0} 条候选"
            + ("（**没做成**，见 kind）" if not ok else "")
        ]
        if truncated:
            pieces.append(f"你给的上限 {asked} 超过工具面上限 {_MAX_LIMIT} ⇒ **截到 {_MAX_LIMIT}**")
        if not ok:
            pieces.append(f"失败档 kind={kind or '(未给)'}：{str(getattr(got, 'error', '') or '')}")
        else:
            pieces.append("候选**没有**判重标注（本动作不复制判重实现）："
                          "登记前先 `search.dedup_check`，登记走 `search.register`")
            pieces.append("**按热度排序对找冷门/更短那条路是反的** ⇒ 这份结果别按被引次数选优")
        return {
            "ok": ok,
            "kind": kind,
            "lit_id": want,
            "doi": data.get("doi"),
            "openalex_id": data.get("openalex_id"),
            "direction": direct,
            "count": len(cands) if ok else 0,
            "candidates": cands,
            "truncated_to_tool_max": truncated,
            "note": "；".join(pieces) + "。`ok` 只说这次调用做完了："
                    "`count=0` 是**有效结论**（这一篇这一侧没有邻居），"
                    "而 `ok=False` 是**没做成**（两件事，别折成一件）。",
        }


__all__ = ["_WalkCitations"]
