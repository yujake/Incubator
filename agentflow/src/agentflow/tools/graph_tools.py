"""图索引与查询：把"关系表"变成一张可反复查询的概念图（纯读）。

## 为什么要有这一层

需求原文是"用程序分析关系表"。既然分析主体是程序，那第一件要做对的事就是
把遍历集中到一处：如果每条查询各自去扫一遍 `relations`，那么

1. 同一个"两概念间有哪些关系"的口径会在五六个函数里各写一遍，早晚不一致；
2. 每次查询都要重算邻接关系，密图上是 O(查询数 × 关系数)；
3. 去重/排序规则散落各处，"稳定排序"这类要求无法被一次性保证。

因此 `RelationGraph` 采用 一次构建、多次查询：构造时把
`concept_relations` / `adjacency` / `group_counts` 全部建好，之后所有查询都是
字典查找 + 小列表排序，恒定且确定。

## 图模型（严格照 DESIGN-TOOLS.md §3.2）

- 节点 = 概念（`concept_id`）；
- 边 = 关系，但一条关系可以涉及 >2 个概念（需求里"概念代号组"是数组）。
  实现上按两两展开：`concept_ids=[A,B,C]` 的关系会产生 3 条两两边
  （A-B、A-C、B-C），三条边共享同一个 relation_id。
  这一点必须记住：路径输出的是关系代号链，不是概念链 —— 因为一条关系
  可能同时覆盖路径上的多跳。

## 为什么 `paths` 必须有界（这不是"优化"，是正确性问题）

概念图在真实数据里可能非常密（"群""集合""映射"这类概念会把所有东西连起来），
无界枚举简单路径的数量随跳数组合爆炸（10 个邻居、5 跳就是 10^5 量级，20 个
邻居则上亿）。跑不完的程序等于没有这个功能。所以这里有三道闸：

- `max_len`：最多几跳；
- `max_paths`：最多收集几条；
- `node_budget`：最多展开多少个节点（搜索预算）。

触及任何一道闸都要如实回报 `truncated=True` 并说明原因。假装"搜完了"
是最坏的失败模式：调用方会以为"这两点之间只有 3 条路径"，而真相是"我们
只搜了一部分"。所以 `paths()` 返回的是 `PathSearchResult` —— 它是 `list`
的子类（因此仍然是 `list[list[str]]`，签名不变），额外带 `truncated` /
`reasons` / `budget_used`。

## 确定性

所有列表返回前都排序：邻居按 `concept_id` 升序、关系按
`relation_sort_key`（§3.3(4) 的确定性序）。同分一律以 `relation_id` 兜底，
保证同输入同输出 —— 否则同一份数据每次跑出来的报告都不一样，D 无法引用。

## 两条修过的缺陷（读代码前先看这一段）

### 1. 四个 handler 的 `StoreError` 会逃出工具层

`graph.build` / `graph.stats` / `graph.neighbors` / `graph.relations_between`
此前只有"成功"一条路：`store.rows` 的 `StoreError`（表不是合法 JSON / 锁超时 /
编号用尽）直接逃出，被 `tools/base.py` 兜成 `kind="unexpected"`。那是环境故障，
不是"未预期的异常" —— 调用方看到 `unexpected` 就无法区分"重试可能成功"与
"表坏了，重试一百次也一样"。现在四个 handler 都过 `attack_tools._guard`
（守卫只有一份实现，本模块 import 它，不另写）。

### 2. `graph.neighbors` 的返回曾经不可截断

它返回"很多个很短的 dict"。上下文预算的剪枝只按字符长度剪字符串，
对"很多个短 dict"完全无效（实测 3000 个邻居剪枝后一条都没少），
而它又不像 `paths()` / `neighborhood()` 那样带 `truncated`。
现在它有 `max_neighbors`（默认 :data:`MAX_NEIGHBORS_DEFAULT`）并在截断时
返回 `truncated=True` + `reasons`。判据只有一份（:func:`bounded_neighbors`）。

`RelationGraph.neighbors()`（裸 list）刻意不改：`agent_c.gaps` 的
`set(g.neighbors(...)) & ...` 与 `trace_tools` 都按 `list` 用它，
改返回类型会静默破坏那些调用点。有界那一层加在 `neighbors_bounded()` 与
工具层上（见两处 docstring）。
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import Any, Callable, Iterable, Mapping, Sequence

from .. import textutil as T
from .attack_tools import _guard  # 守卫只有一份实现（FC-03）：定义在 attack_tools.py
from .base import ToolError, ToolRegistry, ToolResult, fail, tool

__all__ = [
    "MAX_NEIGHBORS_DEFAULT",
    "PathSearchResult",
    "RelationGraph",
    "bounded_neighbors",
    "register",
    "relation_info_len",
    "relation_sort_key",
]


#: `graph.neighbors` 返回的邻居条数上限（结果封装/剪枝的那道闸）。
#:
#: 为什么必须有一个数（FC-17 的上下文预算在这个工具上曾经完全失效）：
#: 上下文预算的剪枝（`contextbudget.prune_tool_result`）只按字符长度剪
#: `data` 里的字符串。`graph.neighbors` 的返回是"很多个很短的 dict"——
#: 实测 3000 个邻居 = 265960 字符的 JSON，剪枝后 `pruned=False`、
#: 条数一条都没少（每个 `name`/`concept_id` 都远短于 `threshold_chars`）。
#: 于是"结果太大"这条防线在它上面不生效，而它又不像 `paths()` /
#: `neighborhood()` 那样带 `truncated` —— 调用方会把"我只拿到前 N 个"
#: 读成"它就只有这些邻居"。
#:
#: 200 的来由：正常概念图里一个概念的邻居数是几个到几十个（概念是"概念组"，
#: 不是词项）；200 已经覆盖远超常规的稠密情形，同时把最坏返回量钉在
#: 数十 KB 量级。要更多邻居的调用方应当用 `graph.svc_neighbors`
#: （`AgentC.neighbors`，带 `depth`/`max_nodes` 与三态）按需展开，
#: 而不是让一次低层查询把整张邻接表拖出来。
MAX_NEIGHBORS_DEFAULT = 200


def bounded_neighbors(
    adjacency: Mapping[str, Mapping[str, Any]],
    concept_id: str,
    *,
    max_neighbors: int | None = None,
) -> dict:
    """取 `concept_id` 的邻居（升序）并如实回报"是不是只给了一部分"。

    这是 `graph.neighbors` 与 `RelationGraph.neighbors_bounded` 的唯一判据
    （FC-03：同一判据只有一份实现）：排序口径、上限、`truncated` 的含义都只在这里定义，
    两处调用都转发过来。

    与 `neighborhood()` / `PathSearchResult` 同一个理由：`neighbors` 的答案天然是
    "一个集合"，而被截断的集合与原集合在形状上完全一样。不把
    `truncated` 与 `reasons` 一起给出来，调用方就会把"我只展开了前 N 个"
    读成"这两个概念之间只有这些联系" —— 一条没有报错的确定性口吻错误结论。

    参数
    ----
    max_neighbors : int | None
        `None` ⇒ 用 :data:`MAX_NEIGHBORS_DEFAULT`（不是"无上限" ——
        "没给上限"与"不设上限"是两件事，后者正是本函数要消灭的形态）。
        小于 0 会按 0 处理（只给结论、不给邻居，但 `total` 仍如实给）。

    返回
    ----
    ``{"neighbors": [concept_id...], "total": int, "returned": int,
       "truncated": bool, "reasons": [str], "max_neighbors": int}``
    """
    limit = MAX_NEIGHBORS_DEFAULT if max_neighbors is None else max(0, int(max_neighbors))
    all_ids = sorted(str(k) for k in (adjacency.get(concept_id) or {}))
    kept = all_ids[:limit]
    truncated = len(all_ids) > len(kept)
    return {
        "neighbors": kept,
        "total": len(all_ids),
        "returned": len(kept),
        "truncated": truncated,
        "reasons": (
            [
                f"max_neighbors={limit} 截断了邻居列表：共 {len(all_ids)} 个，"
                f"只返回前 {len(kept)} 个（升序）。**这不等于'它只有这些邻居'**"
            ]
            if truncated
            else []
        ),
        "max_neighbors": limit,
    }


# ---------------------------------------------------------------- 确定性关系排序


#: `quote_verified` 的确定性优先级：True > None > False（DESIGN-TOOLS.md §3.3(4)）。
#: 语义：有原文支撑最强；"没校验过"（无文本层）次之；"校验失败"最差。
#: 注意 None 必须排在 False 前面 —— 把"没做"和"做了但失败"混为一谈
#: 会系统性低估扫描版文献里的关系（引文可能完全正确，只是没有文本层可查）。
_VERIFIED_RANK: dict[Any, int] = {True: 0, None: 1, False: 2}

#: `status` 的确定性优先级：active > suspect > rejected。
_STATUS_RANK: dict[str, int] = {"active": 0, "suspect": 1, "rejected": 2}

#: 未知枚举值的兜底排位（比任何已知值都差，但彼此之间保持稳定）。
_UNKNOWN_RANK = 9


def relation_info_len(rel: Mapping[str, Any]) -> int:
    """关系的"信息量"近似：`description` + `statement` 的字符数。

    这里刻意用原始字符数而不是规范化后的长度：规范化会去标点、折叠空白，
    对长短的相对比较没有帮助，却会引入一个"哪套规范化"的隐式约定。
    它只是一个排序键，不参与评分公式（评分公式在 agent_c 的 §3.4 里）。
    """
    desc = str(rel.get("description") or "")
    stmt = str(rel.get("statement") or "")
    return len(desc) + len(stmt)


def relation_sort_key(rel: Mapping[str, Any]) -> tuple:
    """§3.3(4) 的确定性排序键（越小越优先）。

    顺序即优先级：
    1. `quote_verified`：True > None > False；
    2. `status`：active > suspect > rejected；
    3. 信息量（`relation_info_len`，越长越优先）；
    4. `lit_id` 与 `relation_id` 兜底 —— 必须有这一层，否则同分关系的
       相对顺序取决于字典插入顺序，"稳定排序"就成了空话。
    """
    verified = rel.get("quote_verified")
    status = str(rel.get("status") or "")
    return (
        _VERIFIED_RANK.get(verified, _UNKNOWN_RANK),
        _STATUS_RANK.get(status, _UNKNOWN_RANK),
        -relation_info_len(rel),
        str(rel.get("lit_id") or ""),
        str(rel.get("relation_id") or ""),
    )


# ---------------------------------------------------------------- 路径搜索结果


class PathSearchResult(list):
    """`list[list[str]]` 的子类，额外携带"这次搜索到底做完了没有"的元信息。

    做成 `list` 子类是为了同时满足两件事：
    - `RelationGraph.paths()` 的签名仍然是 `-> list[list[str]]`，调用方
      `for p in g.paths(...)` / `len(...)` 不用改；
    - 又能在结果上挂 `truncated`，让"预算用尽被截断"这件事不可能被忽略
      （普通 list 上没法带这个信息，只能靠返回值元组，那就会污染签名）。
    """

    def __init__(
        self,
        paths: Iterable[list[str]] = (),
        *,
        truncated: bool = False,
        reasons: Iterable[str] = (),
        budget_used: int = 0,
        node_budget: int = 0,
        max_paths: int = 0,
        max_len: int = 0,
    ) -> None:
        super().__init__(paths)
        self.truncated = bool(truncated)
        #: 触发截断的原因，如 "node_budget" / "max_paths"。
        self.reasons: list[str] = list(reasons)
        self.budget_used = int(budget_used)
        self.node_budget = int(node_budget)
        self.max_paths = int(max_paths)
        self.max_len = int(max_len)

    def to_dict(self) -> dict:
        return {
            "paths": list(self),
            "path_count": len(self),
            "truncated": self.truncated,
            "reasons": list(self.reasons),
            "budget_used": self.budget_used,
            "node_budget": self.node_budget,
            "max_paths": self.max_paths,
            "max_len": self.max_len,
        }

    def __repr__(self) -> str:  # pragma: no cover - 只为日志好看
        return (
            f"PathSearchResult(n={len(self)}, truncated={self.truncated}, "
            f"reasons={self.reasons}, budget={self.budget_used}/{self.node_budget})"
        )


# ---------------------------------------------------------------- 主类


class RelationGraph:
    """关系表上的概念图索引（纯内存、纯读）。

    构造参数直接用 `store.rows(...)` 得到的行字典列表，不转成 dataclass：
    图分析要读的是 `concept_ids` / `status` / `quote_verified` / `lit_id` /
    `description` 这几个字段，而行字典天然向前兼容（多出来的诊断字段
    `_quote_check` 之类照样能看到）。转一层 dataclass 只会让字段丢失。
    """

    def __init__(
        self,
        concepts: list[dict],
        relations: list[dict],
        literatures: list[dict] | None = None,
    ) -> None:
        self.concepts: list[dict] = [dict(c) for c in (concepts or [])]
        self.relations: list[dict] = [dict(r) for r in (relations or [])]
        self.literatures: list[dict] = [dict(x) for x in (literatures or [])]

        # ---- 行索引
        self.concept_by_id: dict[str, dict] = {
            str(c["concept_id"]): c for c in self.concepts if c.get("concept_id")
        }
        self.literature_by_id: dict[str, dict] = {
            str(x["lit_id"]): x for x in self.literatures if x.get("lit_id")
        }
        self.relation_by_id: dict[str, dict] = {}
        for r in self.relations:
            rid = r.get("relation_id")
            if rid:
                self.relation_by_id[str(rid)] = r  # 同 ID 后写覆盖（表里本不该重复）

        # ---- 图索引
        #: concept_id -> [relation_id...]（参与的全部关系，含 rejected —— 见下方说明）
        self.concept_relations: dict[str, list[str]] = {}
        #: concept_id -> {neighbor_id: [relation_id...]}（两两展开）
        self.adjacency: dict[str, dict[str, list[str]]] = {}
        #: concept_group_key -> 出现次数（有多少条关系用了这个概念组）
        self.group_counts: dict[str, int] = {}

        # 为什么 concept_relations 要把 rejected 也算进来：
        # "度数/连接数"描述的是关系表里实际存在多少条记录，不是"多少条可信记录"。
        # 可信度由 status / quote_verified 另行表达（cold 的弱连接判据就要用它们）。
        # 如果这里悄悄过滤掉 rejected，那么"某概念的全部关系都被判重拒绝"这一
        # 重要事实会表现为"该概念没有关系"，恰恰是最该被看见的情况被藏起来。
        for r in self.relations:
            rid = str(r.get("relation_id") or "")
            cids = [str(c) for c in (r.get("concept_ids") or []) if c]
            if not rid or len(cids) < 2:
                continue
            uniq = sorted(set(cids))
            for cid in uniq:
                self.concept_relations.setdefault(cid, []).append(rid)
            # 两两展开：C(n,2) 对边共享同一个 relation_id（§3.2）
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    a, b = uniq[i], uniq[j]
                    self.adjacency.setdefault(a, {}).setdefault(b, []).append(rid)
                    self.adjacency.setdefault(b, {}).setdefault(a, []).append(rid)
            # 概念组键统一走 textutil.concept_group_key（"不要另写一套"）。
            # 不使用行里存的 concept_group_key 字段：那是写入时的产物，历史数据
            # 可能缺失或不一致；由 concept_ids 现场推导才是唯一权威。
            gk = T.concept_group_key(uniq)
            self.group_counts[gk] = self.group_counts.get(gk, 0) + 1

        # ---- 归一：去重 + 升序（确定性）
        for cid, rids in self.concept_relations.items():
            self.concept_relations[cid] = sorted(set(rids))
        for a, nbrs in self.adjacency.items():
            for b, rids in nbrs.items():
                nbrs[b] = sorted(set(rids))

        # 概念表里有、但没参与任何关系的节点也要有邻接条目（其值为空 dict），
        # 否则 `paths()` 无法区分"孤立概念"和"未知概念"。
        for cid in self.concept_by_id:
            self.adjacency.setdefault(cid, {})
            self.concept_relations.setdefault(cid, [])

    # ------------------------------------------------------------ 构造入口

    @classmethod
    def from_store(cls, store: Any) -> "RelationGraph":
        """从 `Store` 无锁快照读三张表建图。

        为什么允许无锁读：图分析是纯读，读到的是某一瞬间的一致快照即可；
        所有写路径都由 `Store.tx` 保护，图这边拿锁只会让 C 的多次查询互相排队，
        而它恰恰应该能任意多次、任意组合地查（DESIGN-TOOLS.md §1.1 的注释）。
        """
        return cls(
            concepts=list(store.rows("concepts")),
            relations=list(store.rows("relations")),
            literatures=list(store.rows("literature")),
        )

    # ------------------------------------------------------------ 基础查询

    def name_of(self, cid: str) -> str:
        """概念名（缺表时显式回退，不返回空串 —— 空串在报告里会被读成"匿名"）。"""
        row = self.concept_by_id.get(cid)
        if row is None:
            return f"(概念表无 {cid})"
        return str(row.get("name") or f"(概念 {cid} 无名称)")

    def degree(self, cid: str) -> int:
        """度数 = 参与的关系条数（§3.3(3) 用它定义"冷门"）。

        注意与 `occurrences` 的区别：一条涉及 3 个概念的关系，对其中每个
        概念的 degree 都贡献 1（它确实参与了这条关系）。
        """
        return len(self.concept_relations.get(cid, ()))

    def occurrences(self, cid: str) -> int:
        """在 `concept_ids` 数组里出现的总次数（§3.3(1) 的计数口径）。

        schema 保证 `concept_ids` 升序去重，因此对合规数据它等于 `degree`。
        仍然按"逐槽计数"实现（而不是直接返回 degree），是为了对历史/手工
        修过的数据也保持"说的和做的一致"：真出现了重复槽位，计数就如实是 2。
        """
        n = 0
        for rid in self.concept_relations.get(cid, ()):
            rel = self.relation_by_id.get(rid) or {}
            n += sum(1 for c in (rel.get("concept_ids") or []) if str(c) == cid)
        return n

    def group_count(self, cid: str) -> int:
        """该概念"作为概念组出现"的累计次数。

        口径（写清楚，免得下游各有各的理解）：把概念 `cid` 所在每一个
        概念组各自的出现次数加起来。也就是"包含 cid 的概念组一共被关系表
        写入了多少次"。同一概念组的多次出现（不同文献的同一组关系）会累加，
        这正是"这个概念组被反复研究"的信号。
        """
        total = 0
        seen: set[str] = set()
        for rid in self.concept_relations.get(cid, ()):
            rel = self.relation_by_id.get(rid) or {}
            cids = [str(c) for c in (rel.get("concept_ids") or []) if c]
            if len(cids) < 2:
                continue
            gk = T.concept_group_key(cids)
            if gk in seen:
                continue
            seen.add(gk)
            total += self.group_counts.get(gk, 0)
        return total

    def counts(self) -> dict[str, dict[str, int]]:
        """`cid -> {occurrences, relation_count, group_count}`（§3.3(1) 第 2 步）。

        概念表里的节点即使没有任何关系也会出现在结果里（计数为 0）——
        否则"完全孤立"这一类在 hottest/cold 里都会凭空消失。
        """
        out: dict[str, dict[str, int]] = {}
        for cid in sorted(set(self.concept_by_id) | set(self.concept_relations)):
            out[cid] = {
                "occurrences": self.occurrences(cid),
                "relation_count": self.degree(cid),
                "group_count": self.group_count(cid),
            }
        return out

    def neighbors(self, cid: str) -> list[str]:
        """邻居概念 id（升序）全量列表。

        这个方法是图层的内部查询，刻意保持"裸 list"的形状 ——
        调用方（`agent_c.gaps` 的集合运算、`trace_tools`）要的是可迭代的集合，
        把它们改成 dict 会破坏既有调用点。"结果太大"这件事由工具层负责
        （见 :meth:`neighbors_bounded` 与 `graph.neighbors` 的 `max_neighbors`）。
        """
        return sorted(self.adjacency.get(cid, {}))

    def neighbors_bounded(self, cid: str, *, max_neighbors: int | None = None) -> dict:
        """邻居（升序）+ 有界/截断元信息（送给工具层的那一份）。

        为什么不让 `neighbors()` 自己返回这个 dict：`neighbors()` 是图索引的
        内部查询，有既有调用方（`agent_c.gaps` 的 `set(g.neighbors(...)) & ...`、
        `trace_tools.trace.concept`）。改它的返回类型 = 一次静默的调用方破坏。

        也没有在这两个方法里各写一份排序+截断判据：两者都转发
        :func:`bounded_neighbors`（同一份实现，FC-03）。
        """
        return bounded_neighbors(self.adjacency, cid, max_neighbors=max_neighbors)

    def neighborhood(self, cid: str, *, depth: int = 1, max_nodes: int = 500) -> dict:
        """以 `cid` 为起点的有界广度优先邻域（I1 的"点菜"查询之一）。

        为什么这一层要负责"有界"，而不是让调用方自己截断：
        `neighbors()` 这个问题的答案天然是"一个集合"，而集合一旦被截断，
        返回值的形状与"完整集合"完全一样 —— 下游会把"我只展开了一部分"
        读成"就这些邻居"。这种错误没有任何报错，却会让 D 得出
        "这两个概念之间没有别的联系"这类确定性口吻的错误结论。
        所以这里把 `truncated` / `reasons` 与节点一起返回，让"不完整"
        成为返回值的一部分（与 `paths()` 的 `PathSearchResult` 同一个理由）。

        返回
        ----
        ``{"center", "depth", "max_nodes", "nodes": [{concept_id, name, distance}],
           "edges": [{from, to, relation_ids}], "truncated", "reasons", "node_count"}``

        - `nodes` 包含起点本身（`distance=0`）。不含起点的话，"查不到这个概念"
          与"它就是孤立节点"在返回值上无法区分，而那正是三态纪律要保住的东西。
        - 起点 `cid` 必须已经在 `adjacency` 里（概念表里的节点都在，见构造函数末尾）。
          不在时本函数仍然照常工作：返回只有 `reasons=["unknown_node"]` 的空结果，
          由调用方决定这是"没查"还是"查了没有"（图这一层不替它下语义判断）。
        - `depth` / `max_nodes` 只在此处收敛（至少 1），不设上限：
          "服务面的上限"是 agent_c 的策略，不是图索引的性质 —— 让策略留在策略层。
        """
        eff_depth = max(1, int(depth))
        budget = max(1, int(max_nodes))
        res: dict = {
            "center": cid,
            "depth": eff_depth,
            "max_nodes": budget,
            "nodes": [],
            "edges": [],
            "truncated": False,
            "reasons": [],
            "node_count": 0,
        }
        if cid not in self.adjacency:
            res["reasons"] = ["unknown_node"]
            return res

        distance: dict[str, int] = {cid: 0}
        order: list[str] = [cid]
        frontier: list[str] = [cid]
        truncated = False
        for d in range(1, eff_depth + 1):
            nxt: list[str] = []
            for u in frontier:
                for v in sorted(self.adjacency.get(u, {})):
                    if v in distance:
                        continue
                    if len(distance) >= budget:
                        truncated = True
                        if "max_nodes" not in res["reasons"]:
                            res["reasons"].append("max_nodes")
                        break
                    distance[v] = d
                    order.append(v)
                    nxt.append(v)
                if truncated:
                    break
            if truncated:
                break
            frontier = nxt
            if not frontier:
                break

        res["nodes"] = [
            {"concept_id": n, "name": self.name_of(n), "distance": distance[n]} for n in order
        ]
        # 边只收两端都在已展开节点集里的：把指向未展开节点的边也写出来，
        # 会让人误以为那些节点也在结果里（"边比节点多"是报告里最难解释的形态）。
        edges: list[dict] = []
        for u in sorted(distance):
            for v, rids in sorted(self.adjacency.get(u, {}).items()):
                if v in distance and u < v:
                    edges.append({"from": u, "to": v, "relation_ids": list(rids)})
        res["edges"] = edges
        res["truncated"] = truncated
        res["node_count"] = len(order)
        return res

    def relations_between(self, a: str, b: str) -> list[dict]:
        """连接 a、b 的全部关系（按 §3.3(4) 确定性序返回）。

        为什么必须是"全部"而不是"路径上那一条"（§3.3(2) 第 3 步）：
        搜索算法在扩展时只是随便挑了一条边把路径接起来，而这一对概念之间
        可能同时存在好几条关系（不同文献、不同表述）。"最合理的链"往往是
        搜索时没选中的那条。所以搜索只负责给出概念序列，关系链要重新选。
        """
        if a == b:
            return []
        rids = self.adjacency.get(a, {}).get(b, [])
        rels = [self.relation_by_id[r] for r in rids if r in self.relation_by_id]
        return sorted(rels, key=relation_sort_key)

    def best_relation(self, candidates: Sequence[dict], used_lit_ids: Iterable[str] = ()) -> dict | None:
        """在一组候选关系里挑"最合适"的一条（§3.3(4) 的确定性实现）。

        排序主键是 `relation_sort_key`（quote_verified → status → 信息量）。
        `used_lit_ids`（链上已用过的文献）只作为同主键桶内的偏好：
        在"可信度与信息量完全相同"的两条关系之间，优先选来自新文献的那条，
        因为跨文献的链条更可能反映真实的、被多方印证的知识联系（§3.4 的
        "不同文献数"项也是这个道理）。
        刻意不让文献多样性越过信息量主键 —— 那会让一条引文已校验、
        描述详尽的关系，输给一条引文没校验但"恰好来自新文献"的关系。
        """
        if not candidates:
            return None
        ordered = sorted(candidates, key=relation_sort_key)
        head = ordered[0]
        used = set(used_lit_ids)
        if used:
            head_key = relation_sort_key(head)[:3]  # 只比较 (verified, status, 信息量)
            bucket = [r for r in ordered if relation_sort_key(r)[:3] == head_key]
            for r in bucket:
                if str(r.get("lit_id") or "") not in used:
                    return r
        return head

    # ------------------------------------------------------------ 路径搜索

    def paths(
        self,
        a: str,
        b: str,
        *,
        max_len: int = 4,
        max_paths: int = 50,
        node_budget: int = 20000,
    ) -> PathSearchResult:
        """从 a 到 b 的有界简单路径枚举（节点不重复）。

        截断语义（必须如实回报，不能假装搜完了）：

        - `node_budget` 用尽 ⇒ `truncated=True`、`reasons=["node_budget"]`；
        - 收集到 `max_paths` 条 ⇒ `truncated=True`、`reasons=["max_paths"]`。

        两者都会让 `truncated` 为真，但含义不同：前者说明"还有没搜完的部分"，
        后者说明"搜到了足够多"。报告里要分开说，否则 D 无法判断"路径就这几条"
        还是"我们没搜完"。
        """
        res_kwargs = {
            "node_budget": int(node_budget),
            "max_paths": int(max_paths),
            "max_len": int(max_len),
        }
        if a == b:
            return PathSearchResult(reasons=["same_node"], **res_kwargs)
        if a not in self.adjacency or b not in self.adjacency:
            missing = [x for x in (a, b) if x not in self.adjacency]
            return PathSearchResult(reasons=[f"unknown_node:{','.join(missing)}"], **res_kwargs)
        if max_len <= 0 or max_paths <= 0:
            return PathSearchResult(reasons=["zero_limit"], **res_kwargs)

        found: list[list[str]] = []
        reasons: list[str] = []
        budget_used = 0
        visited: set[str] = {a}
        path: list[str] = [a]

        def dfs(cur: str) -> None:
            nonlocal budget_used
            if len(path) - 1 >= max_len:
                return
            for nb in sorted(self.adjacency.get(cur, {})):
                if nb in visited:
                    continue
                budget_used += 1
                if budget_used > int(node_budget):
                    if "node_budget" not in reasons:
                        reasons.append("node_budget")
                    return
                path.append(nb)
                visited.add(nb)
                if nb == b:
                    found.append(list(path))
                    if len(found) >= int(max_paths) and "max_paths" not in reasons:
                        reasons.append("max_paths")
                else:
                    # nb != b 才继续深入：简单路径里 b 一旦出现在中间就不可能
                    # 再回到 b（节点不重复），继续搜只是浪费预算。
                    dfs(nb)
                path.pop()
                visited.discard(nb)
                if reasons:
                    return

        dfs(a)
        return PathSearchResult(
            found,
            truncated=bool(reasons),
            reasons=reasons,
            budget_used=budget_used,
            **res_kwargs,
        )

    def reconstruct_edges(self, concept_path: Sequence[str]) -> list[str]:
        """概念路径 → 关系代号链（需求明确要求"路径需包含关系代号链"）。

        对每对相邻概念取"最合适"的关系（`best_relation`，§3.3(4) 的确定性序），
        并沿路径累积"已用文献"，让文献多样性在整条链上生效。

        对齐契约：返回的链长度恒等于 `len(concept_path) - 1`。
        某一跳确实没有任何关系时填 `""` 占位而不是跳过 —— 丢一个元素会让
        "第 k 个关系对应第 k 跳"这条对齐关系整体错位，D 拿着代号链去溯源时
        会指到错误的关系上，而这种错误在文本里看不出来。
        """
        nodes = [str(x) for x in (concept_path or [])]
        chain: list[str] = []
        used_lits: set[str] = set()
        for i in range(len(nodes) - 1):
            cands = self.relations_between(nodes[i], nodes[i + 1])
            best = self.best_relation(cands, used_lits)
            if best is None:
                chain.append("")
                continue
            chain.append(str(best.get("relation_id") or ""))
            used_lits.add(str(best.get("lit_id") or ""))
        return chain

    # ------------------------------------------------------------ 稳定性辅助

    def jaccard_nodes(self, p1: Sequence[str], p2: Sequence[str]) -> float:
        """两条路径的节点集合 Jaccard 相似度（§3.3(2) 第 2 步的判据）。

        为什么用节点集合而不是"路径是否相同"：两条只差一个中间节点的路径
        （a-x-b 与 a-x-y-b）在字面上是两条路径，实质上是同一条 —— 它们共享
        的推理内容远多于差异。只按"路径不同"去重等于没去重。
        """
        s1, s2 = set(p1), set(p2)
        if not s1 or not s2:
            return 0.0
        return len(s1 & s2) / len(s1 | s2)

    # ------------------------------------------------------------ 摘要

    def summary(self) -> dict:
        """`graph.build` / `graph.stats` 的返回体：图规模 + 数据完整性体检。"""
        degrees = {cid: self.degree(cid) for cid in self.adjacency}
        isolated = sorted(cid for cid, d in degrees.items() if d == 0)
        top = sorted(degrees.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        in_relations = set(self.concept_relations)
        missing_rows = sorted(in_relations - set(self.concept_by_id))
        status_counts: dict[str, int] = {}
        verified_counts = {"true": 0, "false": 0, "unknown": 0}
        for r in self.relations:
            st = str(r.get("status") or "?")
            status_counts[st] = status_counts.get(st, 0) + 1
            qv = r.get("quote_verified")
            if qv is True:
                verified_counts["true"] += 1
            elif qv is False:
                verified_counts["false"] += 1
            else:
                verified_counts["unknown"] += 1
        pair_count = 0
        for _a, nbrs in self.adjacency.items():
            pair_count += len(nbrs)
        pair_count //= 2  # 无向边计数（相邻表两边都记了一次）
        return {
            "concept_count": len(self.concept_by_id),
            "relation_count": len(self.relations),
            "literature_count": len(self.literature_by_id),
            "pair_count": pair_count,
            "group_count": len(self.group_counts),
            "isolated_concepts": isolated,
            "isolated_count": len(isolated),
            "degree_top": [
                {"concept_id": cid, "name": self.name_of(cid), "degree": d} for cid, d in top
            ],
            "status_counts": status_counts,
            "quote_verified_counts": verified_counts,
            # 诚实体检：关系里出现、概念表里查不到的概念代号。它们不影响图搜索，
            # 但会让报告里出现"(概念表无 0009)"这类名字 —— 与其让 D 困惑，
            # 不如在图摘要里直接点名。
            "concepts_missing_from_table": missing_rows,
        }


# ---------------------------------------------------------------- 图持有者


class _UnknownConceptError(ToolError):
    """`graph.neighbors` 的业务失败哨兵：概念不在图里。

    为什么要有这个类（而不是在 handler 里直接 `fail(...)`）：`_guard` 会把
    handler 返回的任何值包成 `ok(...)`，所以"提前返回一个失败结果"必须先变成
    异常才能穿过它。而这个类刻意不是"已知失败原因"三类之一 ——
    未登记的 kind 才能让它原样落到下面那个 `except` 里，
    翻回改动前那个形状（`ok=False` + `known_concepts`，meta 里没有 kind），
    由 `tests/test_tools_attack_graph_fixes.py::test_graph_honest_failures_survive_the_guard`
    钉住。

    它继承 `ToolError` 只是为了与工具层的异常族同源；不会被 `_guard` 当成
    "工具层自己的异常上抛"——`_guard` 只有一份，定义在 `attack_tools`，
    它不知道这个类（`_guard` 的 `except ToolError: raise` 会把哨兵原样上抛，
    正好被这里的 `except _UnknownConceptError` 接住）。
    """

    def __init__(self, concept_id: str, known_concepts: list[str]) -> None:
        super().__init__(
            f"图里没有概念 {concept_id}（既不在概念表，也没出现在任何关系里）",
            tool="graph.neighbors",
        )
        self.concept_id = concept_id
        #: 已知概念的前 50 个 —— 调用方据此改参数（这是"可操作提示"，不是装饰）
        self.known_concepts = list(known_concepts)


class _GraphHolder:
    """工具的图缓存。

    为什么要一个持有者：`graph.build` 与 `graph.stats` 这类工具是跨调用
    共享一张图的（"一次构建、多次查询"）。工具层的 handler 只能收到自己的
    参数，没法接收图对象，所以图必须挂在一个可变的闭包捕获对象上。
    同时它支持"外部传入已建好的图"（测试时最常用）。
    """

    def __init__(self, graph: Any = None, store: Any = None) -> None:
        self.store = store
        self._graph: RelationGraph | None = graph if isinstance(graph, RelationGraph) else None
        self._factory: Callable[[], RelationGraph] | None = graph if callable(graph) else None

    def get(self, *, build_if_missing: bool = True) -> RelationGraph:
        if self._graph is not None:
            return self._graph
        if self._factory is not None:
            self._graph = self._factory()
            return self._graph
        if build_if_missing and self.store is not None:
            self._graph = RelationGraph.from_store(self.store)
            return self._graph
        raise ToolError(
            "关系图尚未构建，且没有可用的 store。"
            "请先调用 graph.build，或在 register()/AgentC 里传入 store / 已建的 RelationGraph。"
        )

    def set(self, graph: RelationGraph) -> None:
        self._graph = graph


def _coerce_holder(graph: Any, store: Any) -> _GraphHolder:
    if isinstance(graph, _GraphHolder):
        if store is not None:
            graph.store = store
        return graph
    return _GraphHolder(graph, store)


# ---------------------------------------------------------------- 工具注册


@tool(
    "graph.build",
    "从 store 的三张表构建概念图索引，返回图规模摘要（节点/关系/两两边/孤立概念/度数前5/完整性体检）。",
    {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("C", "D"),
    # `returns=` 必须逐个列全，不许写 `...`：`tests` 逐字解析这个字符串
    # 去和实际返回的键集合比对（`test_graph_returns_declaration_matches_
    # implementation`）。写 `...` 就等于把"还有什么"交给读的人猜，
    # 而"声明与实现一致"这条判据必须机械可判（4.3#9：返回结构要有契约测试）。
    returns=(
        "{'built_from','concept_count','relation_count','literature_count','pair_count',"
        "'group_count','isolated_concepts','isolated_count','degree_top','status_counts',"
        "'quote_verified_counts','concepts_missing_from_table'}"
    ),
)
def graph_build(holder, ) -> ToolResult:
    def _build() -> dict:
        if holder.store is None and holder._graph is None and holder._factory is None:
            raise ToolError(
                "未提供 store，无法建图；请在 register(store=...) 时给出，或传入已建的 RelationGraph。"
            )
        if holder.store is not None:
            holder.set(RelationGraph.from_store(holder.store))
        g = holder.get()
        data = g.summary()
        data["built_from"] = "store" if holder.store is not None else "prebuilt"
        return data

    return _guard(_build)

@tool(
    "graph.stats",
    "返回当前图的统计摘要与热度前列（不重建索引；未建图时按需构建一次）。",
    {
        "type": "object",
        "properties": {"top_n": {"type": "integer", "minimum": 1, "maximum": 100}},
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("C", "D"),
    returns=(
        "{'top_n','hot','concept_count','relation_count','literature_count','pair_count',"
        "'group_count','isolated_concepts','isolated_count','degree_top','status_counts',"
        "'quote_verified_counts','concepts_missing_from_table'}"
    ),
)
def graph_stats(holder, top_n: int = 10) -> ToolResult:
    def _stats() -> dict:
        g = holder.get()
        counts = g.counts()
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1]["occurrences"], kv[0]))[: int(top_n)]
        data = g.summary()
        data["top_n"] = int(top_n)
        data["hot"] = [
            {"concept_id": cid, "name": g.name_of(cid), **vals} for cid, vals in ranked
        ]
        return data

    return _guard(_stats)

@tool(
    "graph.neighbors",
    "返回某概念的邻居概念代号（升序）及其连接的度数信息。"
    f"邻居列表**有界**（默认 max_neighbors={MAX_NEIGHBORS_DEFAULT}）：超过上限时 "
    "truncated=True 并说明只给了前几个 —— 绝不静默截断。",
    {
        "type": "object",
        "properties": {
            "concept_id": {"type": "string", "minLength": 4, "maxLength": 4},
            "max_neighbors": {"type": "integer", "minimum": 0},
        },
        "required": ["concept_id"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("C", "D"),
    # 这里刻意没有 `checked`：低层 `graph.neighbors` 与
    # `graph.svc_neighbors`（`AgentC.neighbors` 的三态服务版）是两种契约，
    # 由 `tests/test_core_audit_abc_cli.py::test_service_tool_names_resolve_the_
    # documented_collision` 钉住。有界/截断是三态之外的另一件事：
    # 它说的是"这一份结果完整不完整"，不是"这次到底查没查"。
    returns=(
        "{'concept_id','name','degree','total_neighbors','returned_neighbors',"
        "'truncated','reasons','neighbors':[{'concept_id','name','relation_count','relation_ids'}]}"
    ),
)
def graph_neighbors(holder, concept_id: str, max_neighbors: int | None = None) -> ToolResult:
    def _neighbors() -> dict:
        g = holder.get()
        if concept_id not in g.adjacency:
            # "这个概念不存在"是业务上的失败，不是异常 —— 它必须保持原来的
            # 形态：`ok=False` + `known_concepts`（可操作提示，调用方据此改参数），
            # 而不是被包成某个 `kind`（改动前实测：meta 里没有 kind）。
            # 所以用哨兵异常把它送出 `_guard`，出来之后再翻回那个形状 ——
            # `_guard` 会把任何返回值包成 `ok(...)`，"提前返回失败"只能经异常。
            raise _UnknownConceptError(concept_id, sorted(g.adjacency)[:50]) from None
        # 有界 + 截断留痕的判据只有一份：`RelationGraph.neighbors_bounded`
        # → `bounded_neighbors`。这里不自己切片（那会是第二份实现）。
        bounded = g.neighbors_bounded(concept_id, max_neighbors=max_neighbors)
        return {
            "concept_id": concept_id,
            "name": g.name_of(concept_id),
            "degree": g.degree(concept_id),
            "total_neighbors": bounded["total"],
            "returned_neighbors": bounded["returned"],
            "truncated": bounded["truncated"],
            "reasons": list(bounded["reasons"]),
            "neighbors": [
                {
                    "concept_id": n,
                    "name": g.name_of(n),
                    "relation_count": len(g.adjacency[concept_id][n]),
                    "relation_ids": list(g.adjacency[concept_id][n]),
                }
                for n in bounded["neighbors"]
            ],
        }

    try:
        return _guard(_neighbors)
    except _UnknownConceptError as e:
        return fail(str(e), known_concepts=list(e.known_concepts))

@tool(
    "graph.relations_between",
    "返回同时包含两个概念的全部关系（按 quote_verified/status/信息量确定性排序）。",
    {
        "type": "object",
        "properties": {
            "a": {"type": "string", "minLength": 4, "maxLength": 4},
            "b": {"type": "string", "minLength": 4, "maxLength": 4},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("C", "D"),
    returns=(
        "{'a','b','a_name','b_name','count',"
        "'relations':[{'relation_id','concept_ids','description','statement','quote',"
        "'status','quote_verified','lit_id','page_range'}]}"
    ),
)
def graph_relations_between(holder, a: str, b: str) -> ToolResult:
    def _between() -> dict:
        g = holder.get()
        rels = g.relations_between(a, b)
        return {
            "a": a,
            "b": b,
            "a_name": g.name_of(a),
            "b_name": g.name_of(b),
            "count": len(rels),
            "relations": [
                {
                    "relation_id": r.get("relation_id"),
                    "concept_ids": list(r.get("concept_ids") or []),
                    "description": r.get("description"),
                    "statement": r.get("statement"),
                    "quote": r.get("quote"),
                    "status": r.get("status"),
                    "quote_verified": r.get("quote_verified"),
                    "lit_id": r.get("lit_id"),
                    "page_range": r.get("page_range"),
                }
                for r in rels
            ],
        }

    return _guard(_between)

#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (graph_build, ('holder',)),
    (graph_stats, ('holder',)),
    (graph_neighbors, ('holder',)),
    (graph_relations_between, ('holder',)),
)


def register(registry: ToolRegistry, *, store: Any = None, graph: Any = None) -> list[str]:
    """把图查询工具注册进 `registry`，返回注册的工具名列表。

    参数
    ----
    store : Store | None
        用于 `graph.build` 现场建图；也可之后通过 `graph.build` 隐式使用。
    graph : RelationGraph | Callable[[], RelationGraph] | None
        预建好的图（或返回图的工厂）。传了它就不必依赖 store。

    四个工具全部 `side_effect="read"`（纯读）：C 的核心诉求是"用程序分析"，
    它应当能任意多次、任意组合地查询，而不触发任何审批或写盘
    （DESIGN-TOOLS.md §1.1 的注释就是为这件事写的）。
    """
    holder = _coerce_holder(graph, store)

    # T-8：声明与工具体都在模块级（@tool 写进 n.__tool_spec__），
    # 这里只把装配期算出来的 holder 按位置绑上去（partial）。
    _bound: dict[str, Any] = {}
    _bound['holder'] = holder
    names: list[str] = []
    for _fn, _deps in _TOOL_FUNCTIONS:
        names.append(registry.register(replace(
            _fn.__tool_spec__, handler=partial(_fn, *[_bound[k] for k in _deps]))).name)
    return names


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    import sys

    try:  # Windows 控制台/管道下强制 utf-8，避免中文输出报编码错
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 —— 理由：有些 stdout 替身（pytest capture / IDE / 重定向流）
        # 没有 `reconfigure`。切编码失败的唯一后果是中文输出乱码，而
        # "因为控制台编码问题自检根本没跑成"是更坏的结局（它会把一次真实的判定失败
        # 伪装成"没输出"）。自检的目的是报告判定结果，不是设置编码。
        pass

    from .base import ToolRegistry

    print("=" * 72)
    print("[1] 造一个小图：7 概念 / 10 关系（含一条 3 概念关系、一条孤立概念）")
    concepts = [
        {"concept_id": "0000", "name": "群"},
        {"concept_id": "0001", "name": "阿贝尔群"},
        {"concept_id": "0002", "name": "域"},
        {"concept_id": "0003", "name": "交换环"},
        {"concept_id": "0004", "name": "模"},
        {"concept_id": "0005", "name": "理想"},
        {"concept_id": "0006", "name": "孤立概念"},
    ]

    def rel(rid, cids, desc, *, lit="0000", qv=True, status="active"):
        return {
            "relation_id": rid,
            "concept_ids": sorted(cids),
            "description": desc,
            "lit_id": lit,
            "page_range": {"start": 1, "end": 1, "label": "p. 1"},
            "quote": f"引文 {rid}",
            "quote_verified": qv,
            "statement": desc,
            "status": status,
        }

    relations = [
        rel("0000", ["0000", "0001"], "阿贝尔群是一种交换的群", qv=True),
        rel("0001", ["0001", "0002"], "每个域都是阿贝尔群", qv=True),
        rel("0002", ["0000", "0003"], "交换环的加法群是阿贝尔群", qv=False),
        rel("0003", ["0002", "0003"], "域是交换环", qv=True),
        rel("0004", ["0000", "0004"], "模是群上的作用", qv=True),
        rel("0005", ["0004", "0005"], "理想是环的子结构", qv=None),
        rel("0006", ["0002", "0005"], "商环与理想的对应", qv=None, status="suspect"),
        rel("0007", ["0000", "0005"], "群作用下的不变量", qv=True),
        rel("0008", ["0001", "0004"], "阿贝尔群上的模", qv=True),
        rel("0009", ["0002", "0004", "0005"], "域/模/理想的三元关系", qv=True),
    ]
    g = RelationGraph(concepts, relations, [])
    s = g.summary()
    print(f"    概念={s['concept_count']} 关系={s['relation_count']} 两两边={s['pair_count']}")
    print(f"    孤立概念={s['isolated_concepts']}  度数前3={[(d['concept_id'], d['degree']) for d in s['degree_top'][:3]]}")
    print(f"    关系表里缺失的概念行={s['concepts_missing_from_table']}")

    print("[2] 计数：occurrences / relation_count / group_count（§3.3(1) 口径）")
    for cid, c in sorted(g.counts().items()):
        print(f"    {cid} {g.name_of(cid):<6} occ={c['occurrences']} rel={c['relation_count']} grp={c['group_count']}")

    print("[3] relations_between(0004,0005)：两两展开后同一对概念有多条关系")
    for r in g.relations_between("0004", "0005"):
        print(f"    {r['relation_id']} status={r['status']} qv={r['quote_verified']} desc={r['description']!r}")

    print("[4] paths(0000 -> 0002) 全部简单路径（max_len=4）")
    ps = g.paths("0000", "0002", max_len=4, max_paths=50)
    print(f"    {ps!r}")
    for p in sorted(ps, key=lambda x: (len(x), x)):
        print(f"    {'-'.join(p)}  关系链={g.reconstruct_edges(p)}")

    print("[5] 预算截断必须如实回报（node_budget=3 / max_paths=2）")
    t1 = g.paths("0000", "0002", node_budget=3)
    print(f"    node_budget=3  -> n={len(t1)} truncated={t1.truncated} reasons={t1.reasons} used={t1.budget_used}")
    t2 = g.paths("0000", "0002", max_paths=2)
    print(f"    max_paths=2    -> n={len(t2)} truncated={t2.truncated} reasons={t2.reasons} used={t2.budget_used}")
    t3 = g.paths("0000", "0006")
    print(f"    到孤立概念 0006 -> n={len(t3)} truncated={t3.truncated} reasons={t3.reasons}")

    print("[6] jaccard_nodes：只差一个中间节点的两条路径应被判为高重合")
    print(f"    a-x-b vs a-x-y-b = {g.jaccard_nodes(['0000','0001','0002'], ['0000','0001','0004','0002']):.3f}")
    print(f"    a-x-b vs a-y-b   = {g.jaccard_nodes(['0000','0001','0002'], ['0000','0003','0002']):.3f}")

    print("[7] 工具层：graph.build / stats / neighbors / relations_between（全为 read）")
    reg = ToolRegistry(name="selftest")
    # 绑定角色（`P-14`）：`graph.*` 的声明角色是 C/D，而这张表代表的是只读的 C。
    reg.bound_role = "C"
    names = register(reg, graph=g)
    print(f"    注册：{names}")
    for n in names:
        print(f"    {n} side_effect={reg.get(n).side_effect} needs_approval={reg.get(n).needs_approval}")
    b = reg.call("graph.build")
    print(f"    graph.build ok={b.ok} built_from={b.data.get('built_from') if b.ok else b.error}")
    st = reg.call("graph.stats", top_n=3)
    print(f"    graph.stats hot={[(h['concept_id'], h['occurrences']) for h in st.data['hot']]}")
    nb = reg.call("graph.neighbors", concept_id="0000")
    print(f"    graph.neighbors(0000) degree={nb.data['degree']} -> {[x['concept_id'] for x in nb.data['neighbors']]}")
    rb = reg.call("graph.relations_between", a="0001", b="0002")
    print(f"    graph.relations_between(0001,0002) count={rb.data['count']} ids={[x['relation_id'] for x in rb.data['relations']]}")
    bad = reg.call("graph.neighbors", concept_id="9999")
    print(f"    未知概念 -> ok={bad.ok} error={bad.error}")
    bad2 = reg.call("graph.neighbors", concept_id="1")
    print(f"    非法参数 -> ok={bad2.ok} kind={bad2.meta.get('kind')} error={bad2.error}")

    print("=" * 72)
    print("SELF-CHECK DONE")
