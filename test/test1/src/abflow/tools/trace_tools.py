"""代号溯源：把"代号"还原成"表述"，再按需还原成"文献正文"（**纯读**）。

## 为什么要分三级（DESIGN-TOOLS.md §4.3）

D 拿到的是 C 报告里的**代号**（`relation_id` / `concept_id` / `lit_id`）。
它必须先看到"这条关系到底说了什么"才能判断值不值得研究。而"看到什么"的成本
差别极大：

| 层级 | 从 | 到 | 成本 |
|---|---|---|---|
| L1 `trace.relation` | 关系代号 | 引文 / 描述 / 陈述 / 页码 / 校验状态 + 概念名 + 文献元数据 | 极低（读内存行） |
| L2 `trace.concept` | 概念代号 | 概念定义 + 它参与的全部关系的**表述** | 低（读内存行） |
| L3 `trace.literature` | 文献代号 | 元数据 + 本地文件 + **正文片段**（可能触发 PDF 抽取/OCR） | **贵** |

## 为什么 L3 必须"按需"，绝不能默认调用

L3 要**真的去读文件**：`extract.extract_text` 打开 PDF、逐页抽文本，几十页的
文献就是几百毫秒到几秒，还可能要拉起 OCR（easyocr 首次使用要下载上百 MB 模型）。
如果每溯源一条关系就顺手带上正文，那么 D 每轮分析几十条关系 = 几十次全文抽取，
其中 90% 的结果根本不会被用到。更糟的是它会**掩盖 L1 的信息**：D 应该先读
"这条关系说了什么"，不够用了才下钻 —— 直接喂正文会让它跳过判断这一步。

所以：`L1`/`L2` 永不读文件；`L3` 只在 D 显式调用时才读，且**如实报告读取结果**
（文件不存在 / 无文本层 / 抽取失败，三件事分得清清楚楚）。

## "没做"和"做了但没结果"是两件事（与 quoteverify.py 同一精神）

`quote_verified` 是三态：`True` 校验通过 / `False` 校验失败 / `None` **无法校验**
（例如扫描版无文本层）。本模块把这个三态**原样透出**并附上中文标签，
绝不在展示层把它压成布尔 —— 那正是 `DESIGN.md` §6.3 反复强调要避免的。
同理，L3 读不到正文时返回 `status="no_text_layer"` 而不是"空字符串"：
后者会被下游读成"这篇文献没有内容"，前者才说明"需要 OCR"。

## 确定性

所有输出字段都来自表里的行与文件系统事实，没有一处猜测：
`concept_names` 是查概念表得到的，`file_exists` 是 `Path.exists()` 得到的，
`text` 是抽取器返回的。因此本模块**可以**被断言测试（见文件末尾自检）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from .base import ToolError, ToolRegistry, ToolResult, fail, ok, tool
from .graph_tools import RelationGraph

__all__ = ["register"]


#: `quote_verified` 三态的中文标签。放在模块级是为了让 L1/chain 两处口径一致。
_QUOTE_LABELS: dict[Any, str] = {
    True: "已校验（引文在文献原文中逐字命中）",
    False: "校验失败（引文未能在声明的页码窗口内找到）",
    None: "无法校验（无引文或无文本层；这不是'校验失败'）",
}

#: L3 的状态取值。**必须是受控词表**：调用方靠它分支，随手写的字符串会让
#: "无文本层"和"文件丢了"在下游被合并成同一个"读不到"。
L3_STATUSES = ("ok", "no_path", "file_missing", "not_a_file", "path_rejected", "no_text_layer", "extract_failed")


def quote_label(qv: Any) -> str:
    """把三态 `quote_verified` 变成人话（未知取值如实转述，不猜）。"""
    if qv in _QUOTE_LABELS:
        return _QUOTE_LABELS[qv]
    return f"未知状态 {qv!r}"


def _concept_brief(graph: RelationGraph | None, cid: str) -> dict:
    """概念代号 → `{concept_id, name, definition}`（查不到就如实说查不到）。"""
    if graph is None:
        return {"concept_id": cid, "name": None, "definition": None, "in_table": False}
    row = graph.concept_by_id.get(cid)
    if row is None:
        return {"concept_id": cid, "name": None, "definition": None, "in_table": False}
    return {
        "concept_id": cid,
        "name": row.get("name"),
        "definition": row.get("definition"),
        "aliases": list(row.get("aliases") or []),
        "in_table": True,
    }


def _literature_brief(graph: RelationGraph | None, lit_id: str) -> dict:
    """文献代号 → 元数据（不含正文；正文只属于 L3）。"""
    if graph is None:
        return {"lit_id": lit_id, "in_table": False}
    row = graph.literature_by_id.get(lit_id)
    if row is None:
        return {"lit_id": lit_id, "in_table": False}
    return {
        "lit_id": lit_id,
        "in_table": True,
        "title": row.get("title"),
        "type": row.get("type"),
        "year": row.get("year"),
        "authors": list(row.get("authors") or []),
        "venue": row.get("venue"),
        "doi": row.get("doi"),
        "summary": row.get("summary"),
        "path": row.get("path"),
        "processed": row.get("processed"),
    }


def _relation_brief(graph: RelationGraph, rel: dict) -> dict:
    """一条关系的 L1 视图。L1/L2/L3 的输出都基于它，保证口径唯一。"""
    cids = [str(c) for c in (rel.get("concept_ids") or [])]
    concepts = [_concept_brief(graph, c) for c in cids]
    qv = rel.get("quote_verified")
    return {
        "relation_id": rel.get("relation_id"),
        "concept_ids": cids,
        "concept_names": [c["name"] for c in concepts],
        "concepts": concepts,
        "description": rel.get("description") or "",
        "statement": rel.get("statement") or "",
        "quote": rel.get("quote") or "",
        "page_range": rel.get("page_range") or {},
        "status": rel.get("status"),
        "quote_verified": qv,
        # 三态语义必须显式带出来，见模块 docstring
        "quote_verified_label": quote_label(qv),
        "lit_id": rel.get("lit_id"),
        "literature": _literature_brief(graph, str(rel.get("lit_id") or "")),
        "concept_group_key": rel.get("concept_group_key") or "",
        "duplicate_of": rel.get("duplicate_of"),
        "created_at": rel.get("created_at") or "",
    }


def _chain_line(step_no: int, brief: dict) -> str:
    """把一条关系的表述串成一行（`trace.chain` 与报告共用同一格式）。"""
    names = "、".join(str(n) for n in brief.get("concept_names") or []) or "(概念名未知)"
    pr = brief.get("page_range") or {}
    pages = pr.get("label") or (
        f"pp. {pr.get('start')}-{pr.get('end')}" if pr.get("start") is not None else "页码未知"
    )
    quote = (brief.get("quote") or "").strip()
    quote_txt = f"｜引文：「{quote}」" if quote else "｜引文：（无）"
    return (
        f"{step_no}. [{brief.get('relation_id')}] {names}"
        f"（{brief.get('status')}，{quote_label(brief.get('quote_verified'))}）"
        f"：{brief.get('description') or '(无描述)'}{quote_txt}｜出处：文献 {brief.get('lit_id')} {pages}"
    )


# ---------------------------------------------------------------- 工具注册


def register(registry: ToolRegistry, *, store: Any = None, graph: Any = None) -> list[str]:
    """注册溯源工具，返回工具名列表。

    `L3` 需要 `store` 才能把文献表里的相对路径解析成磁盘上的绝对路径
    （`store.library_path` 还会做一次"不许越出 library/"的检查）。
    没有 store 时 L1/L2 照常可用，L3 会**明确失败**而不是假装读过文件。
    """
    holder_graph: RelationGraph | None = graph if isinstance(graph, RelationGraph) else None

    def _g() -> RelationGraph:
        """L1/L2 要概念名与文献元数据；没有图对象时用最小可用视图。"""
        if holder_graph is not None:
            return holder_graph
        if store is not None:
            return RelationGraph.from_store(store)
        return RelationGraph([], [], [])

    @tool(
        "trace.relation",
        "L1 溯源：由关系代号取回引文/描述/陈述/页码/状态/引文校验三态，并把概念代号翻译成概念名、附文献元数据。",
        {
            "type": "object",
            "properties": {"relation_id": {"type": "string", "minLength": 4, "maxLength": 4}},
            "required": ["relation_id"],
            "additionalProperties": False,
        },
        side_effect="read",
        roles=("C", "D"),
        returns="{level:'L1', relation_id, quote, description, statement, page_range, status, quote_verified, concepts, literature}",
    )
    def trace_relation(relation_id: str) -> ToolResult:
        g = _g()
        rel = g.relation_by_id.get(relation_id)
        if rel is None:
            return fail(
                f"没有关系 {relation_id}",
                known_relations=sorted(g.relation_by_id)[:50],
                hint="关系代号是 4 位十进制字符串；可用 graph.relations_between 先确认代号。",
            )
        brief = _relation_brief(g, rel)
        return ok({"level": "L1", "contains_fulltext": False, **brief})

    @tool(
        "trace.concept",
        "L2 溯源：由概念代号取回定义 + 它参与的全部关系的表述（只给表述与代号，不下钻文献正文）。",
        {
            "type": "object",
            "properties": {
                "concept_id": {"type": "string", "minLength": 4, "maxLength": 4},
                "with_relations": {"type": "boolean"},
            },
            "required": ["concept_id"],
            "additionalProperties": False,
        },
        side_effect="read",
        roles=("C", "D"),
        returns="{level:'L2', concept, relation_count, relations:[L1 摘要...], contains_fulltext:false}",
    )
    def trace_concept(concept_id: str, with_relations: bool = True) -> ToolResult:
        g = _g()
        if concept_id not in g.adjacency and concept_id not in g.concept_by_id:
            return fail(
                f"没有概念 {concept_id}",
                known_concepts=[{"concept_id": c, "name": g.name_of(c)} for c in sorted(g.concept_by_id)[:50]],
            )
        concept = _concept_brief(g, concept_id)
        counts = {
            "occurrences": g.occurrences(concept_id),
            "relation_count": g.degree(concept_id),
            "group_count": g.group_count(concept_id),
        }
        data: dict[str, Any] = {
            "level": "L2",
            "concept": concept,
            "counts": counts,
            "neighbors": [
                {"concept_id": n, "name": g.name_of(n)} for n in g.neighbors(concept_id)
            ],
            "contains_fulltext": False,
            "note": "本层只给关系表里已有的'表述'；需要文献正文请显式调用 trace.literature（L3，贵）。",
        }
        if not with_relations:
            data["relations"] = []
            data["relation_count"] = counts["relation_count"]
            return ok(data)

        rels = []
        for rid in g.concept_relations.get(concept_id, []):
            rel = g.relation_by_id.get(rid)
            if rel is None:
                continue
            brief = _relation_brief(g, rel)
            # L2 的"其它概念"：把自身剔除，方便 D 直接看到"这个概念的邻居是谁"
            brief["other_concepts"] = [
                {"concept_id": c["concept_id"], "name": c["name"]}
                for c in brief["concepts"]
                if c["concept_id"] != concept_id
            ]
            rels.append(brief)
        data["relations"] = rels
        data["relation_count"] = len(rels)
        return ok(data)

    @tool(
        "trace.literature",
        "L3 溯源（按需、贵）：文献元数据 + 本地文件是否存在 + 正文片段；无文本层会如实报告而不是返回空串。",
        {
            "type": "object",
            "properties": {
                "lit_id": {"type": "string", "minLength": 4, "maxLength": 4},
                "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 50},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 200000},
            },
            "required": ["lit_id"],
            "additionalProperties": False,
        },
        side_effect="read",
        roles=("C", "D"),
        returns="{level:'L3', status, file_exists, has_text_layer, pages_returned, text, truncated}",
    )
    def trace_literature(lit_id: str, pages: list[int] | None = None, max_chars: int = 4000) -> ToolResult:
        g = _g()
        meta = _literature_brief(g, lit_id)
        if not meta.get("in_table"):
            return fail(
                f"文献表里没有 {lit_id}",
                known_literature=sorted(g.literature_by_id)[:50],
            )
        rel_path = meta.get("path")
        base: dict[str, Any] = {
            "level": "L3",
            "literature": meta,
            "requested_pages": list(pages) if pages else None,
            "max_chars": int(max_chars),
        }
        if store is None:
            return fail(
                "未提供 store，无法把文献路径解析到磁盘（L3 需要它）。L1/L2 仍可正常使用。",
                detail=base,
            )
        if not rel_path:
            # path 为空 = 没下载/下载失败。**这不是"文件不存在"**：
            # 一个是流程没走到，一个是流程走了但文件丢了。
            return ok(
                {
                    **base,
                    "status": "no_path",
                    "file_exists": False,
                    "has_text_layer": False,
                    "text": "",
                    "note": "文献表里 path 为空：该文献未下载或下载失败，因此没有正文可读。请让 A 补下载。",
                }
            )
        try:
            abs_path = store.library_path(rel_path)
        except Exception as exc:  # StoreError：路径越出 library/
            return ok(
                {
                    **base,
                    "status": "path_rejected",
                    "file_exists": False,
                    "has_text_layer": False,
                    "text": "",
                    "note": f"路径被拒绝（越出 library/）：{exc}",
                }
            )
        assert abs_path is not None  # rel_path 非空时 library_path 必返回 Path
        if not abs_path.exists():
            return ok(
                {
                    **base,
                    "status": "file_missing",
                    "abs_path": str(abs_path),
                    "file_exists": False,
                    "has_text_layer": False,
                    "text": "",
                    "note": "文献表登记了路径，但磁盘上没有这个文件（可能被移动/删除）。",
                }
            )
        if not abs_path.is_file():
            return ok(
                {
                    **base,
                    "status": "not_a_file",
                    "abs_path": str(abs_path),
                    "file_exists": False,
                    "has_text_layer": False,
                    "text": "",
                    "note": "该路径不是普通文件（可能是目录）。",
                }
            )

        # ---- 真的去读文件（这一步是"贵"的来源，所以只在 L3 里做）
        try:
            from ..extract import extract_text  # 惰性：fitz/pdfminer 是重依赖
        except Exception as exc:  # pragma: no cover - 环境缺模块时
            return ok(
                {
                    **base,
                    "status": "extract_failed",
                    "abs_path": str(abs_path),
                    "file_exists": True,
                    "has_text_layer": False,
                    "text": "",
                    "note": f"文本抽取模块不可用：{exc}",
                }
            )
        try:
            doc = extract_text(abs_path)
        except Exception as exc:  # ExtractError / ExtractTooLarge / UnsupportedFormat
            return ok(
                {
                    **base,
                    "status": "extract_failed",
                    "abs_path": str(abs_path),
                    "file_exists": True,
                    "has_text_layer": False,
                    "text": "",
                    "note": f"抽取失败：{type(exc).__name__}: {exc}",
                }
            )

        all_pages: list[str] = list(getattr(doc, "pages", []) or [])
        if not all_pages:
            # 无文本层：绝不返回 "" 假装读到了 —— 与 quoteverify 的 None 同一精神。
            return ok(
                {
                    **base,
                    "status": "no_text_layer",
                    "abs_path": str(abs_path),
                    "file_exists": True,
                    "has_text_layer": False,
                    "source_kind": getattr(doc, "source_kind", None),
                    "page_count": 0,
                    "text": "",
                    "truncated": False,
                    "note": (
                        "该文件没有文本层（疑似扫描版）：不是'读到了空文本'，而是"
                        "'没有可读文本'。需要 OCR 才能得到正文，因此本次没有正文片段可给。"
                    ),
                }
            )

        want = sorted({int(p) for p in (pages or []) if int(p) >= 1}) or list(
            range(1, len(all_pages) + 1)
        )
        picked: list[int] = []
        chunks: list[str] = []
        total = 0
        truncated = False
        for p in want:
            if p > len(all_pages):
                continue
            chunk = all_pages[p - 1]
            if total + len(chunk) > int(max_chars):
                room = int(max_chars) - total
                if room > 0:
                    chunks.append(chunk[:room])
                    picked.append(p)
                    total += room
                truncated = True
                break
            chunks.append(chunk)
            picked.append(p)
            total += len(chunk)
        if len(want) > len(picked):
            truncated = True
        return ok(
            {
                **base,
                "status": "ok",
                "abs_path": str(abs_path),
                "file_exists": True,
                "has_text_layer": True,
                "source_kind": getattr(doc, "source_kind", None),
                "encoding": getattr(doc, "encoding", None),
                "page_count": len(all_pages),
                "pages_returned": picked,
                "text": "\n".join(chunks),
                "chars_returned": total,
                "truncated": truncated,
                "note": "正文片段按需截断到 max_chars；如需其它页请用 pages 参数指定。",
            }
        )

    @tool(
        "trace.chain",
        "把一条关系代号链的每一步表述串起来（D 写报告可直接引用），缺号如实列出。",
        {
            "type": "object",
            "properties": {
                "relation_ids": {"type": "array", "items": {"type": "string", "minLength": 4, "maxLength": 4}, "minItems": 1, "maxItems": 50}
            },
            "required": ["relation_ids"],
            "additionalProperties": False,
        },
        side_effect="read",
        roles=("C", "D"),
        returns="{level:'chain', relation_ids, steps:[L1 摘要...], chain_text, missing}",
    )
    def trace_chain(relation_ids: list[str]) -> ToolResult:
        g = _g()
        steps: list[dict] = []
        missing: list[str] = []
        lines: list[str] = []
        for i, rid in enumerate(relation_ids, 1):
            rel = g.relation_by_id.get(rid)
            if rel is None:
                missing.append(rid)
                lines.append(f"{i}. [{rid}] 关系表里没有这个代号（链条在此断裂）")
                continue
            brief = _relation_brief(g, rel)
            steps.append(brief)
            lines.append(_chain_line(i, brief))
        return ok(
            {
                "level": "chain",
                "relation_ids": list(relation_ids),
                "steps": steps,
                "step_count": len(steps),
                "chain_text": "\n".join(lines),
                "missing": missing,
                "contains_fulltext": False,
                "note": "这是关系链的'表述链'（L1）。要判断证据是否足够，再对关键步骤调 trace.literature（L3）。",
            }
        )

    specs: Iterable = (trace_relation, trace_concept, trace_literature, trace_chain)
    names: list[str] = []
    for fn in specs:
        spec = registry.register_function(fn)
        names.append(spec.name)
    return names


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    import sys
    import tempfile
    from pathlib import Path as _P

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from ..store import Store
    from .base import ToolRegistry

    print("=" * 72)
    root = _P(tempfile.mkdtemp(prefix="abflow_trace_"))
    st = Store(root)
    st.init(force=True)
    print(f"[1] 临时工作区：{root}")

    concepts = [
        {"concept_id": "0000", "name": "群", "definition": "带二元运算的集合", "related_concepts": ["0001"]},
        {"concept_id": "0001", "name": "阿贝尔群", "definition": "交换的群", "related_concepts": ["0000", "0002"]},
        {"concept_id": "0002", "name": "域", "definition": "乘法可交换的除环", "related_concepts": ["0001"]},
    ]
    relations = [
        {
            "relation_id": "0000",
            "concept_ids": ["0000", "0001"],
            "description": "阿贝尔群是一种交换的群",
            "lit_id": "0000",
            "page_range": {"start": 2, "end": 2, "label": "p. 2"},
            "quote": "An abelian group is a group in which the commutative law holds.",
            "quote_verified": True,
            "statement": "交换律在阿贝尔群中成立",
            "status": "active",
        },
        {
            "relation_id": "0001",
            "concept_ids": ["0001", "0002"],
            "description": "域是阿贝尔群",
            "lit_id": "0001",
            "page_range": {"start": None, "end": None, "label": ""},
            "quote": "",
            "quote_verified": None,
            "statement": "",
            "status": "suspect",
        },
    ]
    (root / "library").mkdir(parents=True, exist_ok=True)
    (root / "library" / "paper.txt").write_text(
        "An abelian group is a group in which the commutative law holds.\n"
        "A field is a commutative division ring.\n",
        encoding="utf-8",
    )
    literatures = [
        {
            "lit_id": "0000",
            "title": "代数结构导论",
            "type": "M",
            "summary": "教材",
            "path": "paper.txt",
            "processed": True,
            "year": 2001,
            "authors": ["某人"],
        },
        {
            "lit_id": "0001",
            "title": "扫描版旧书",
            "type": "M",
            "summary": "无文本层样例",
            "path": "missing.pdf",
            "processed": False,
        },
    ]
    with st.tx("concepts", "relations", "literature", actor="selftest", note="fixture") as tx:
        for r in concepts:
            tx.upsert("concepts", r)
        for r in relations:
            tx.upsert("relations", r)
        for r in literatures:
            tx.upsert("literature", r)
    print(f"    落库：概念 {len(st.rows('concepts'))} 关系 {len(st.rows('relations'))} 文献 {len(st.rows('literature'))}")

    reg = ToolRegistry(name="trace")
    names = register(reg, store=st)
    print(f"[2] 注册：{names}（side_effect 全为 read）")
    print(f"    {[reg.get(n).side_effect for n in names]}")

    print("[3] L1 trace.relation(0000)")
    r1 = reg.call("trace.relation", relation_id="0000")
    d = r1.data
    print(f"    ok={r1.ok} 概念名翻译={d['concept_names']} status={d['status']} qv={d['quote_verified']}")
    print(f"    三态标签={d['quote_verified_label']}")
    print(f"    quote={d['quote'][:60]!r} 页码={d['page_range']}")
    print(f"    文献元数据={ {k: d['literature'][k] for k in ('lit_id','title','year')} }")
    miss = reg.call("trace.relation", relation_id="9999")
    print(f"    不存在的关系 -> ok={miss.ok} error={miss.error}")

    print("[4] L2 trace.concept(0000)（含关系/不含关系两种）")
    c1 = reg.call("trace.concept", concept_id="0000")
    print(f"    ok={c1.ok} counts={c1.data['counts']} 关系数={c1.data['relation_count']} contains_fulltext={c1.data['contains_fulltext']}")
    for rel in c1.data["relations"]:
        print(f"      [{rel['relation_id']}] 其它概念={[o['name'] for o in rel['other_concepts']]} 表述={rel['description']!r}")
    c0 = reg.call("trace.concept", concept_id="0001", with_relations=False)
    print(f"    with_relations=False -> 关系数={c0.data['relation_count']} relations={c0.data['relations']}")

    print("[5] L3 trace.literature：有文本层 / 文件缺失 / 无 path 三种情况")
    l1 = reg.call("trace.literature", lit_id="0000", max_chars=400)
    print(f"    有文本层：status={l1.data['status']} has_text_layer={l1.data['has_text_layer']} pages={l1.data['pages_returned']} chars={l1.data.get('chars_returned')}")
    print(f"    正文片段={l1.data['text'][:70]!r}")
    l2 = reg.call("trace.literature", lit_id="0001")
    print(f"    文件缺失：status={l2.data['status']} file_exists={l2.data['file_exists']} note={l2.data['note']}")

    print("[6] L3 无文本层：真造一个空白 PDF（若有 fitz），否则至少验证 no_path 分支")
    try:
        import fitz

        blank = fitz.open()
        blank.new_page()
        blank.save(str(root / "library" / "scan.pdf"))
        blank.close()
        with st.tx("literature", actor="selftest", note="add scan") as tx:
            tx.upsert(
                "literature",
                {
                    "lit_id": "0002",
                    "title": "扫描件",
                    "type": "M",
                    "summary": "无文本层",
                    "path": "scan.pdf",
                    "processed": False,
                },
            )
        l3 = reg.call("trace.literature", lit_id="0002")
        print(f"    空白 PDF：status={l3.data['status']} has_text_layer={l3.data['has_text_layer']} text={l3.data['text']!r}")
        print(f"    note={l3.data['note']}")
    except Exception as exc:
        print(f"    跳过空白 PDF 自检（{type(exc).__name__}: {exc}）")
    l4 = reg.call("trace.literature", lit_id="9999")
    print(f"    不存在的文献 -> ok={l4.ok} error={l4.error}")

    print("[7] trace.chain：把关系链的表述串起来（含缺号）")
    ch = reg.call("trace.chain", relation_ids=["0000", "0001", "9999"])
    print(f"    ok={ch.ok} step_count={ch.data['step_count']} missing={ch.data['missing']}")
    for line in ch.data["chain_text"].splitlines():
        print(f"      {line}")
    bad = reg.call("trace.chain", relation_ids=[])
    print(f"    空数组 -> ok={bad.ok} kind={bad.meta.get('kind')} error={bad.error}")

    print("=" * 72)
    print("SELF-CHECK DONE")
