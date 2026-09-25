"""判重：文献 / 概念 / 关系。

集中在一个模块，因为三种判重的**哲学不同**，混在各自 agent 里最容易写歪：

- **文献**：可以而且应该激进判重（同一篇论文从三个 provider 命中是常态），
  用三级硬键（DOI → 标题+年 → 文件哈希），命中即复用，没有"模糊"档。
- **概念**：**只按规范化名字精确合并**，不做相似度自动归并。
  理由：把"群"和"环"合并的代价远大于漏合并，且错误归并会污染所有下游关系。
  相似但不相同 → 交给复核，不自动合。
  ⚠️ 已经被 I5 合并掉的节点（`merged_into` 非空）**不参与匹配** —— 见
  :func:`find_concept`：让墓碑参与匹配会让新知识挂到一个永远不再被读到的节点上。
- **关系**：分三档（精确 / 强相似 / 待复核），且**必须同概念组**才比较。
  理由见 DESIGN.md §3.3：不同概念组的文本相似是不同知识点。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import textutil as T

# ---------------------------------------------------------------- 文献


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "https://dx.doi.org/"):
        if d.startswith(prefix):
            d = d[len(prefix) :]
    return d.strip() or None


def literature_keys(title: str, year: int | None, doi: str | None) -> list[str]:
    """文献去重的键，按可信度降序。

    第三个键 `title:<norm>|*` **不是装饰**：预印本与正式版的年份常常不同，
    只按 `标题+年` 匹配会把同一篇工作登记两次。它在
    :func:`find_existing_literature` 的第 3 轮里被真正使用（并带年份容差保护）。
    """
    keys: list[str] = []
    nd = normalize_doi(doi)
    if nd:
        keys.append(f"doi:{nd}")
    t = T.normalize(title)
    if t:
        if year is not None:
            keys.append(f"title:{t}|{year}")
        keys.append(f"title:{t}|*")
    return keys


def title_key(title: str) -> str:
    return f"title:{T.normalize(title)}"


def _row_keys(row: dict) -> set[str]:
    """一行文献携带的全部去重键。

    为什么要同时看 `_keys` 和 `dedup_key`：`_keys` 是 agent_a 写入的诊断字段
    （记录**全部**候选键），`dedup_key` 是主键。历史数据或其它写入路径可能只有后者，
    所以两边都要看 —— 只认其中一个会让判重悄悄失效。
    """
    s = set(row.get("_keys") or [])
    if row.get("dedup_key"):
        s.add(row["dedup_key"])
    return s


def _row_doi(row: dict) -> str | None:
    """从显式字段或去重键里取 DOI。"""
    d = normalize_doi(row.get("doi"))
    if d:
        return d
    for k in _row_keys(row):
        if k.startswith("doi:"):
            return k[4:]
    return None


def _row_year(row: dict) -> int | None:
    """从显式字段或 `title:...|<year>` 键里取年份。

    必须能从键里反解年份：否则 `year` 字段缺失的行在第 3 轮（仅标题匹配）
    会被当成"年份未知"而**无条件合并**，把同名不同年的两份著作错判成同一篇。
    """
    y = row.get("year")
    if isinstance(y, int):
        return y
    for k in _row_keys(row):
        if k.startswith("title:") and k.endswith("|*"):
            continue
        if k.startswith("title:") and "|" in k:
            tail = k.rsplit("|", 1)[1]
            if tail.lstrip("-").isdigit():
                return int(tail)
    return None


def find_existing_literature(
    rows: list[dict],
    title: str,
    year: int | None,
    doi: str | None,
    *,
    year_tolerance: int = 2,
) -> tuple[dict | None, str | None]:
    """在既有文献表里找同一篇。返回 (行, 命中的键)。

    三轮匹配，**顺序即优先级**：

    1. **DOI 精确**：最强证据，命中即认定同一篇（即使标题完全不同）。
    2. **标题 + 年份精确**：没有 DOI 时的可靠替代。
    3. **仅标题**（忽略年份）：兜住"预印本 vs 正式版"这类年份漂移。
       但**必须带容差保护** —— 同名不同年的两份不同著作（教材第 1 版与第 3 版）
       不应该被合并。规则：只有**其中一侧年份确实缺失**，或两侧年份之差
       ≤ `year_tolerance` 时才认。
    """
    nd = normalize_doi(doi)
    nt = T.normalize(title)

    # --- 第 1 轮：DOI（显式字段或键都认）
    if nd:
        want = f"doi:{nd}"
        for row in rows:
            if _row_doi(row) == nd or want in _row_keys(row):
                return row, want

    # --- 第 2 轮：标题 + 年份
    if nt and year is not None:
        want = f"title:{nt}|{year}"
        for row in rows:
            if want in _row_keys(row):
                return row, want
            if T.normalize(row.get("title", "")) == nt and _row_year(row) == year:
                return row, want

    # --- 第 3 轮：仅标题（带年份容差）
    if nt:
        for row in rows:
            if T.normalize(row.get("title", "")) != nt:
                continue
            ry = _row_year(row)
            if year is None or ry is None or abs(ry - year) <= year_tolerance:
                return row, f"{title_key(title)}|*"
    return None, None


# ---------------------------------------------------------------- 概念


def find_concept(rows: list[dict], name: str, aliases: list[str] | None = None) -> dict | None:
    """按规范化名字（含别名）精确匹配。不做相似度。

    **已被合并的节点（`merged_into` 非空）不参与匹配**（I5）：

    合并后那个节点只是审计用的墓碑 —— 它的边已经被改写到 survivor 上。
    若还让它参与匹配，新来的同名概念会命中这个**幽灵节点**：survivor 永远接不到
    新知识，而 `merged_into` 是一条看起来完全正常的记录，**没有任何地方会报错**。
    这与"不删行以便审计"并不矛盾：墓碑要能被人查看，但不该被判重逻辑当成活节点。
    """
    targets = {T.normalize(name)}
    for a in aliases or []:
        targets.add(T.normalize(a))
    targets.discard("")
    if not targets:
        return None
    for row in rows:
        if row.get("merged_into"):
            continue
        cand = {row.get("normalized_name") or T.normalize(row.get("name", ""))}
        for a in row.get("aliases") or []:
            cand.add(T.normalize(a))
        if cand & targets:
            return row
    return None


# ---------------------------------------------------------------- 关系


@dataclass(frozen=True)
class DedupDecision:
    """判重结论。`kind` 决定 agent_b 的写入动作。"""

    kind: str  # "new" | "duplicate" | "suspect"
    score: float
    existing_id: str | None = None
    existing_quote: str | None = None
    detail: dict | None = None

    @property
    def should_write(self) -> bool:
        return self.kind in ("new", "suspect")

    @property
    def status(self) -> str:
        return {"new": "active", "suspect": "suspect", "duplicate": "rejected"}[self.kind]


def decide_relation(
    existing_relations: list[dict],
    *,
    concept_group_key: str,
    quote: str,
    description: str = "",
    dup_strong: float = 0.92,
    dup_review: float = 0.72,
) -> DedupDecision:
    """关系的三档判重（DESIGN.md §3.3）。

    比较用的是 `quote_normalized`（逐字引文）而不是 `description`：
    引文是客观的、可校验的；而 description 是转写，措辞自由度大，
    拿它判重会既漏判（同义改写）又误判（不同文献措辞相近）。

    若某行没有 quote（历史数据/无文本层），退化为比较 description。
    """
    same_group = [r for r in existing_relations if r.get("concept_group_key") == concept_group_key]
    if not same_group:
        return DedupDecision("new", 0.0)

    q = T.normalize_for_quote(quote) or T.normalize(description)
    if not q:
        # 引文为空：无法判重，保守地当新关系写入并置 suspect，交复核
        return DedupDecision("suspect", 0.0, detail={"reason": "empty_quote"})

    best: tuple[float, dict | None] = (-1.0, None)
    for r in same_group:
        if r.get("status") == "rejected":
            continue
        rq = r.get("quote_normalized") or T.normalize_for_quote(r.get("quote", "")) or T.normalize(r.get("description", ""))
        if not rq:
            continue
        if rq == q:
            return DedupDecision(
                "duplicate",
                1.0,
                existing_id=r.get("relation_id"),
                existing_quote=r.get("quote") or r.get("description"),
                detail={"reason": "exact_quote_match"},
            )
        s = T.similarity(rq, q)
        if s > best[0]:
            best = (s, r)

    score, row = best
    if row is None:
        return DedupDecision("new", 0.0)
    ex_id = row.get("relation_id")
    ex_quote = row.get("quote") or row.get("description")
    if score >= dup_strong:
        return DedupDecision(
            "duplicate",
            score,
            existing_id=ex_id,
            existing_quote=ex_quote,
            detail={"reason": "similarity>=dup_strong", "detail": T.similarity_detail(ex_quote, quote)},
        )
    if score >= dup_review:
        return DedupDecision(
            "suspect",
            score,
            existing_id=ex_id,
            existing_quote=ex_quote,
            detail={"reason": "similarity in [dup_review, dup_strong)", "detail": T.similarity_detail(ex_quote, quote)},
        )
    return DedupDecision("new", score, detail={"nearest": ex_id, "score": score})


def relation_dedup_key(concept_group_key: str, quote: str) -> str:
    """稳定的关系键：概念组 + 引文哈希。用于索引与幂等重跑。"""
    return f"{concept_group_key}::{T.short_hash(T.normalize_for_quote(quote), 16)}"


def derive_related_concepts(concept_id: str, relations: list[dict], include_suspect: bool = True) -> list[str]:
    """由关系表派生某概念的"相关概念"（DESIGN.md §6.2）。

    刻意**从关系派生**而不是增量 append：这样漏更新会在下一次重算时自愈，
    且 `verify` 可以用同一个函数独立复算来交叉检查。
    """
    out: set[str] = set()
    for r in relations:
        if r.get("status") == "rejected":
            continue
        if r.get("status") == "suspect" and not include_suspect:
            continue
        ids = r.get("concept_ids") or []
        if concept_id in ids:
            out.update(i for i in ids if i != concept_id)
    return sorted(out)
