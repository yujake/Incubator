# -- coding: utf-8 --
"""C 的两件台账工具：选根（`ledger.resolve`）与按需展开局部树（`ledger.expand`）。

业主 2026-11-10 的口径（逐字见 `draft/181`）：C 不建全图。代码侧把数据整理成索引
（`agentflow.ledgerindex.LedgerIndex`，本次唤醒缓存一次、不进上下文）；C 每需要一次，
就选定一个节点、自己定层数，向上展开父（依赖谁）、向下展开子（谁引用它），得到一棵
局部树；不够就按需拼接扩张。

两件工具为什么必须分开（不是两个参数、是两件事）：
- `ledger.resolve` 只回答"我要展开的根是哪一个"—— 候选节点列表（五格），不是树；按号 /
  按标签关键字走既有检索实现（`statementledger.by_id` / `by_keywords`），不另写一套；
- `ledger.expand` 只回答"从这个根往外看，`depth` 层内是什么"—— 局部树。层数必填、由 C
  自己决定：少给就返回"缺参数"提示（写清"层数由你决定、必填"并给可照抄的例子），不静默
  用默认值。

返回形状、有界与增量写在 `ledgerindex.LedgerIndex.expand` 的 docstring 里；本模块只做
工具层的三件事：参数判据、把索引建不起来的失败如实交回、把树的读数原样交回。
"""
from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import Any

from .. import ledgerindex as LI
from . import ToolError, ToolResult, fail, ok, tool

#: 只发给 C（业主：这两件是 C 的关系推断工具；D 若要用由 D 派 C）。
_ROLES: tuple[str, ...] = ("C",)

#: 缺 `depth` 时的提示（业主逐字要求：写清"层数由你决定、必填"并给可照抄的例子）。
_MISSING_DEPTH = (
    "缺参数 `depth`：**层数由你决定、必填**（本工具不替你选默认值）。"
    "例：`ledger.expand(node=\"stmt:000123\", depth=2)` —— 从这一条起上下各看两层；"
    "只看谁依赖它（污染面的查询模式）用 "
    "`ledger.expand(node=\"stmt:000123\", depth=2, direction=\"down\")`；"
    "深度上限是 " + str(LI.MAX_DEPTH) + " 层，再深就对 frontier 里的节点再 expand 一次（拼接）。"
)

#: `depth` 给了但不合法时的提示（同一个口径，不静默折成一个默认值）。
_BAD_DEPTH = (
    "`depth` 必须是 1..{max} 之间的整数（收到 {got!r}）—— 层数由你决定、必填："
    "给 1 表示只看直接父 / 直接引用者，给 2 表示再看一层；"
    "例：`ledger.expand(node=\"stmt:000123\", depth=2)`。"
)

_BAD_NODE = (
    "缺参数 `node`：给要展开的那一条的号（`stmt:000123` 或 `000123`）。"
    "不知道号就先 `ledger.resolve(query=...)` 选根 —— 它只给候选，不展开树。"
)

_BAD_DIRECTION = (
    "`direction` 只能是 up / down / both（收到 {got!r}）：up = 只向上展开它依赖的，"
    "down = 只向下展开引用它的（污染面的查询模式），both = 两边都展开（默认）。"
)


def _index_of(holder: LI.LedgerHolder) -> LI.LedgerIndex:
    """拿索引；建不起来 ⇒ `ToolError`（由工具层统一翻成 ok=False 的可读拒绝）。"""
    try:
        return holder.get()
    except LI.LedgerIndexError as exc:
        raise ToolError(
            f"台账索引建不起来 ⇒ 这两件工具这一趟没查成（不是「台账里没有」）：{exc}",
            tool="ledger",
        ) from None


@tool(
    "ledger.resolve",
    "按号 / 按标签关键字查命题台账，返回候选节点（命题号 / 类别 / 状态 / 等级 / 标签），"
    "不是树。找不到时明确说『没有这个号 / 没有命中』。选根之后再用 ledger.expand 展开。",
    {"type": "object",
     "properties": {
         "query": {"type": "string", "minLength": 1,
                   "description": "命题号（stmt:000123 / 000123）或标签 / 关键字"},
     },
     "required": ["query"], "additionalProperties": False},
    side_effect="read",
    roles=_ROLES,
    returns=(
        "{'query','checked','mode','found','hits_total','scanned',"
        "'candidates':[{'stmt_id','kind','status','grade','label'}],'why','reason'}"
    ),
)
def ledger_resolve(holder: LI.LedgerHolder, query: str) -> ToolResult:
    """工具体：选根（候选节点列表，不含证明正文、也不是树）。"""
    index = _index_of(holder)
    got = index.resolve(query)
    if not got["checked"]:
        return fail(str(got["why"]), kind="ledger_query_refused",
                    query=got["query"], mode=got["mode"])
    if not got["found"]:
        # 明确"没有"：这一档不是空列表了事（空列表会被读成"还没查"）。
        return fail(str(got["why"]), kind="ledger_not_found",
                    query=got["query"], mode=got["mode"],
                    hits_total=got["hits_total"], scanned=got["scanned"])
    return ok(got, **got)


@tool(
    "ledger.expand",
    "从选定节点起按 depth 层上下展开局部树：每个节点带相对关系 / 号 / 类别 / 内容 / 等级 /"
    " 依赖面（全路径按证明路径分组）/ 被引面（一层），并有界、可增量。depth 必填、由你决定。",
    {"type": "object",
     "properties": {
         "node": {"type": "string", "minLength": 1,
                  "description": "要展开的节点号（stmt:000123 / 000123）；先用 ledger.resolve 选"},
         "depth": {"type": "integer", "minimum": 1, "maximum": LI.MAX_DEPTH,
                   "description": "必填：展开几层（由你决定；1 = 只看直接父 / 直接引用者）"},
         "direction": {"type": "string", "enum": list(LI.DIRECTIONS),
                       "description": "展开方向：up（依赖谁）/ down（谁引用它）/ both（默认）"},
     },
     "required": ["node"], "additionalProperties": False},
    side_effect="read",
    roles=_ROLES,
    returns=(
        "{'checked','node','depth','direction','nodes':[{'stmt_id','kind','status','grade',"
        "'label','statement_full','proof_no','proof_nos','relation','dependency_face',"
        "'cited_face'}],'edges':[{'from','to','dir','dep_id','path_no','path_group',"
        "'used_at','used_at_known','status','to_is_statement','external_root'}],"
        "'frontier':[{'stmt_id','kind','label','distance','directions'}],'truncated','reasons',"
        "'budget_used':{'nodes','added','edges','chars','node_budget','char_budget',"
        "'depth_max'},'added_nodes','already_known','why'}"
    ),
)
def ledger_expand(holder: LI.LedgerHolder, node: str = "",
                  depth: Any = None, direction: str = "both") -> ToolResult:
    """工具体：局部树（层数必填；无句柄、同一问第二次只给增量）。"""
    if not str(node or "").strip():
        return fail(_BAD_NODE, kind="missing_param", missing=["node"],
                    example='ledger.expand(node="stmt:000123", depth=2)')
    if depth is None:
        # 业主逐字：不填 ⇒ 工具层返回"缺参数"提示，不许静默用默认值，也不返回树。
        return fail(_MISSING_DEPTH, kind="missing_param", missing=["depth"],
                    example='ledger.expand(node="stmt:000123", depth=2)')
    try:
        wanted = int(depth)
    except (TypeError, ValueError):
        return fail(_BAD_DEPTH.format(max=LI.MAX_DEPTH, got=depth),
                    kind="bad_param", bad=["depth"],
                    example='ledger.expand(node="stmt:000123", depth=2)')
    if wanted < 1 or wanted > LI.MAX_DEPTH:
        return fail(_BAD_DEPTH.format(max=LI.MAX_DEPTH, got=depth),
                    kind="bad_param", bad=["depth"],
                    example='ledger.expand(node="stmt:000123", depth=2)')
    if str(direction or "") not in LI.DIRECTIONS:
        return fail(_BAD_DIRECTION.format(got=direction), kind="bad_param",
                    bad=["direction"], allowed=list(LI.DIRECTIONS))
    index = _index_of(holder)
    tree = index.expand(node, wanted, str(direction or "both"))
    if not tree["checked"]:
        return fail(str(tree["why"]), kind="ledger_node_not_found",
                    node=tree["node"], reasons=tree["reasons"])
    return ok(tree, checked=True, node=tree["node"], depth=tree["depth"],
              direction=tree["direction"], truncated=tree["truncated"])


#: 装配清单（与 `attack_tools` / `manuscript_tools` 同一形态）。
_TOOL_FUNCTIONS: tuple[tuple[Any, tuple[str, ...]], ...] = (
    (ledger_resolve, ("holder",)),
    (ledger_expand, ("holder",)),
)


def register(registry: Any, *, store: Any = None, index: Any = None, **_: Any) -> None:
    """把 `ledger.` 两件装进注册表。

    `index` 可以是已建好的 `LedgerIndex`（测试 / 编排层给事务快照时用），也可以是一个
    返回 `LedgerIndex` 的工厂；都不给就按 `store` 现建（`LedgerHolder` 与 `_GraphHolder`
    同形）。`store` 为 None 时照样注册：调用时如实报"建不起来"，不折成空树
    （"没接线"与"台账里没有"是两件事）。
    """
    holder = LI.LedgerHolder(index=index, store=store)
    for fn, deps in _TOOL_FUNCTIONS:
        bound = [holder if name == "holder" else None for name in deps]
        registry.register(replace(fn.__tool_spec__, handler=partial(fn, *bound)))
