"""代号溯源：把"代号"还原成"表述"，再按需还原成"文献正文"（纯读）。
## 为什么要分三级（DESIGN-TOOLS.md §4.3）
D 拿到的是 C 报告里的代号（`relation_id` / `concept_id` / `lit_id`）。它必须先看到"这条关系到底说了什么"才能判断值不值得研究。
而"看到什么"的成本差别极大：
| 层级 | 从 | 到 | 成本 ||---|---|---|---|| L1 `trace.relation` | 关系代号 | 引文 / 描述 / 陈述 / 页码
/ 校验状态 + 概念名 + 文献元数据 | 极低（读内存行） || L2 `trace.concept` | 概念代号 | 概念定义 + 它参与的全部关系的表述 | 低（读
内存行） || L3 `trace.literature` | 文献代号 | 元数据 + 本地文件 + 正文片段（可能触发 PDF 抽取/OCR） | 贵 |
## 为什么 L3 必须"按需"，绝不能默认调用
L3 要真的去读文件：`extract.extract_text` 打开 PDF、逐页抽文本，几十页的文献就是几百毫秒到几秒，还可能要拉起 OCR（easyocr 首次使用
要下载上百 MB 模型）。如果每溯源一条关系就顺手带上正文，那么 D 每轮分析几十条关系 = 几十次全文抽取，其中 90% 的结果根本不会被用到。更糟的是它会掩盖 L1 的
信息：D 应该先读"这条关系说了什么"，不够用了才下钻 —— 直接喂正文会让它跳过判断这一步。
所以：`L1`/`L2` 永不读文件；`L3` 只在 D 显式调用时才读，且如实报告读取结果（文件不存在 / 无文本层 / 抽取失败，三件事分得清清楚楚）。
## "没做"和"做了但没结果"是两件事（与 quoteverify.py 同一精神）
`quote_verified` 是三态：`True` 校验通过 / `False` 校验失败 / `None` 无法校验（例如扫描版无文本层）。本模块把这个三态原样透出并
附上中文标签，绝不在展示层把它压成布尔 —— 那正是 `DESIGN.md` §6.3 反复强调要避免的。同理，L3 读不到正文时返回 
`status="no_text_layer"` 而不是"空字符串"：后者会被下游读成"这篇文献没有内容"，前者才说明"需要 OCR"。
## 确定性
所有输出字段都来自表里的行与文件系统事实，没有一处猜测：`concept_names` 是查概念表得到的，`file_exists` 是 `Path.exists()` 得
到的，`text` 是抽取器返回的。因此本模块可以被断言测试（见文件末尾自检）。
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .. import conceptrows as CR   # 并表过渡期：夹具/自检走这一处写口
from .. import schema as S         # 编号形态的唯一来源（宽度随 schema.ID_DIGITS 走）
from .base import ToolError, ToolRegistry, ToolResult, fail, ok, tool
from .graph_tools import RelationGraph

__all__ = ["register"]


#: `quote_verified` 三态的中文标签。放在模块级是为了让 L1/chain 两处口径一致。
_QUOTE_LABELS: dict[Any, str] = {
    True: "已校验（引文在文献原文中逐字命中）",
    False: "校验失败（引文未能在声明的页码窗口内找到）",
    None: "无法校验（无引文或无文本层；这不是'校验失败'）",
}

#: L3 的状态取值。必须是受控词表：调用方靠它分支，随手写的字符串会让
#: "无文本层"和"文件丢了"在下游被合并成同一个"读不到"。
L3_STATUSES = ("ok", "no_path", "file_missing", "not_a_file", "path_rejected", "no_text_layer", "extract_failed")


def _status(value: str) -> str:
    """受控词表的执行点。

    这是被审计点名的缺陷（`INVENTORY.md` §4.5 #9）：`L3_STATUSES` 曾经
    全仓库只有定义行引用它，所有 `status` 都是散落各处的字面量 ——
    也就是说"受控词表"只是一句注释。一个拼错的 `"file_mising"` 会照样返回，
    调用方按 `== "file_missing"` 分支就会静默走错路。
    现在每个 `status` 都必须过这里：不在词表里就当场炸（导入期/调用期 fail-closed），
    而不是把一个编外的状态字符串交给下游。
    """
    if value not in L3_STATUSES:
        raise ToolError(f"L3 status={value!r} 不在受控词表 L3_STATUSES={L3_STATUSES} 里")
    return value


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


@tool(
    "trace.relation",
    "L1 溯源：由关系代号取回引文/陈述/页码/引文校验三态，概念代号翻成概念名、附文献元数据。",
    {
        "type": "object",
        "properties": {"relation_id": {"type": "string", "minLength": 4, "maxLength": S.ID_DIGITS}},
        "required": ["relation_id"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("C", "D"),
    returns=(
        "{'level','relation_id','concept_ids','concept_names','concepts','description','statement',"
        "'quote','page_range','status','quote_verified','quote_verified_label','lit_id','literature',"
        "'concept_group_key','duplicate_of','created_at','contains_fulltext'}"
        "（contains_fulltext 是**常量 False**：L1 永不读文件，它不是每次调用的检查结论）"
    ),
)
def trace_relation(_g, relation_id: str) -> ToolResult:
    g, err = _g("trace.relation")
    if err is not None:
        return err
    assert g is not None  # _g 的契约：err is None ⇒ g 非空
    rel = g.relation_by_id.get(relation_id)
    if rel is None:
        # `checked=True` = 查过了，确实没有（与 `_g` 的 kind="no_graph"
        # 严格区分：那个是"没查"）。
        return fail(
            f"没有关系 {relation_id}",
            kind="not_found",
            checked=True,
            known_relations=sorted(g.relation_by_id)[:50],
            hint=f"关系代号是 {S.ID_DIGITS} 位十进制字符串（旧数据里的 4 位号仍可读）；可用 graph.relations_between 先确认代号。",
        )
    brief = _relation_brief(g, rel)
    return ok({"level": "L1", "contains_fulltext": False, **brief})

@tool(
    "trace.concept",
    "L2 溯源：由概念代号取回定义 + 它参与的全部关系的表述（不下钻文献正文）。",
    {
        "type": "object",
        "properties": {
            "concept_id": {"type": "string", "minLength": 4, "maxLength": S.ID_DIGITS},
            "with_relations": {"type": "boolean"},
        },
        "required": ["concept_id"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("C", "D"),
    returns=(
        "{'level','concept','counts','neighbors','relations','relation_count','contains_fulltext','note'}"
    ),
)
def trace_concept(_g, concept_id: str, with_relations: bool = True) -> ToolResult:
    g, err = _g("trace.concept")
    if err is not None:
        return err
    assert g is not None
    if concept_id not in g.adjacency and concept_id not in g.concept_by_id:
        return fail(
            f"没有概念 {concept_id}",
            kind="not_found",
            checked=True,
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
    "L3 溯源（按需、贵）：文献元数据 + 本地文件是否存在 + 正文片段；无文本层如实报告。",
    {
        "type": "object",
        "properties": {
            "lit_id": {"type": "string", "minLength": 4, "maxLength": S.ID_DIGITS},
            "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 50},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 200000},
        },
        "required": ["lit_id"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("C", "D"),
    returns=(
        "{'level','literature','requested_pages','max_chars','pages_returned','truncated','status',"
        "'file_exists','has_text_layer','text','note',"
        "'source_kind','abs_path','chars_returned','encoding','page_count'}"
        "（不含 status/text/pages_returned/truncated 的早期分支**不存在了**："
        "这四项在每一条 ok 分支上都必须给，否则调用方区分不了'没有正文'与'工具忘了填'）"
    ),
)
def trace_literature(_g, store, lit_id: str, pages: list[int] | None = None, max_chars: int = 4000) -> ToolResult:
    g, err = _g("trace.literature")
    if err is not None:
        # 顺序很关键：这里此前先查 `meta.get("in_table")`，于是"没有 store
        # 也没有 graph"时会报"文献表里没有 X"（把"没查"说成"查了没有"），
        # 而下面那句更诚实的"未提供 store，无法解析磁盘路径"永远打不出来。
        return err
    assert g is not None
    meta = _literature_brief(g, lit_id)
    if not meta.get("in_table"):
        return fail(
            f"文献表里没有 {lit_id}",
            kind="not_found",
            checked=True,
            known_literature=sorted(g.literature_by_id)[:50],
        )
    rel_path = meta.get("path")
    base: dict[str, Any] = {
        "level": "L3",
        "literature": meta,
        "requested_pages": list(pages) if pages else None,
        "max_chars": int(max_chars),
        # 这两项在每一条分支上都必须存在：调用方拿不到它们时无法区分
        # "没有正文可返回"与"工具忘了填"。放在 base 里 = 不可能漏。
        "pages_returned": [],
        "truncated": False,
    }
    if store is None:
        return fail(
            "未提供 store，无法把文献路径解析到磁盘（L3 需要它）。L1/L2 仍可正常使用。",
            kind="no_store",
            checked=False,
            detail=base,
        )
    if not rel_path:
        # path 为空 = 没下载/下载失败。这不是"文件不存在"：
        # 一个是流程没走到，一个是流程走了但文件丢了。
        return ok(
            {
                **base,
                "status": _status("no_path"),
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
                "status": _status("path_rejected"),
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
                "status": _status("file_missing"),
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
                "status": _status("not_a_file"),
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
                "status": _status("extract_failed"),
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
                "status": _status("extract_failed"),
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
                "status": _status("no_text_layer"),
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
            "status": _status("ok"),
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
    "把一条关系代号链的每一步表述串起来，缺号如实列出。",
    {
        "type": "object",
        "properties": {
            "relation_ids": {"type": "array", "items": {"type": "string", "minLength": 4, "maxLength": S.ID_DIGITS}, "minItems": 1, "maxItems": 50}
        },
        "required": ["relation_ids"],
        "additionalProperties": False,
    },
    side_effect="read",
    roles=("C", "D"),
    returns=(
        "{'level','relation_ids','steps','step_count','chain_text','missing','checked','contains_fulltext','note'}"
        "；**没有图可查**时 ok=False + kind=no_graph + checked=False（与"
        "'查了、链条确实断裂'的 ok=True+checked=True+missing 非空严格区分）"
    ),
)
def trace_chain(_g, relation_ids: list[str]) -> ToolResult:
    g, err = _g("trace.chain")
    if err is not None:
        # 三态纪律（本函数曾经的缺陷）：无 store 无 graph 时 `_g()` 返回过一张
        # 空图，于是每个代号都落进 `missing`，函数仍然 `ok=True` +
        # `step_count=0` —— 调用方读到的结论是"这些关系代号都不存在"，
        # 而真相是"关系图从未构建"。现在：没图可查 ⇒ 明确失败 + checked=False。
        return err
    assert g is not None
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
            # `checked=True` 与 `missing` 非空可以同时成立，而且必须能区分：
            # 这里说的是"图查过了，这些代号确实不在里面"；
            # 上面 `_g` 的 `kind="no_graph"` 说的是"根本没图可查"。
            "checked": True,
            "contains_fulltext": False,
            "note": "这是关系链的'表述链'（L1）。要判断证据是否足够，再对关键步骤调 trace.literature（L3）。",
        }
    )

# ---------------------------------------------------------------- 父子链（一层）

@tool(
    "trace.children",
    "看我自己直接下级此刻在做什么：每个子任务给状态、最近 N 步（agent_step）、"
    "被拒次数与类目、产出是否真落盘、最近一次交接手稿摘要。"
    "非主控角色只给一层（传 depth 更大也按一层处理），返回值里逐字写明"
    "「更深要看请向 M 请求」以及那条上行调用的原文。",
    {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "minLength": 4, "maxLength": S.ID_DIGITS + 2,
                        "description": "要看谁的直接下级（缺省=我自己；非 M 角色只许填自己）"},
            "depth": {"type": "integer", "minimum": 1, "maximum": 12,
                      "description": ("想看几层。普通代理固定按 1 层给（更深的层要 M 才能看）；"
                                      "只有 M 调 conductor.watch 时才按传入值走")},
            "window": {"type": "integer", "minimum": 1, "maximum": 50,
                       "description": "每个子任务给最近几步（缺省 5）"},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="read",
    # 「普通代理能追一层」是业主原话里的前半句：这一件因此对所有可被召唤的角色开放
    # （C/H/V 是只读角色，side_effect="read" 让结构性过滤不会剥掉它）。主控不在这
    # 一份声明里：M 要看全树用 conductor.watch（业主原话的后半句）。
    roles=tuple(S.ROLES),
    returns=("{'checked','me','depth_requested','depth_granted','one_layer_only',"
             "'children','count','deeper','session'}；每个子任务里有 "
             "{'task_id','role','status','outcome','recent_steps','refusals',"
             "'products','last_handoff'}"),
)
def trace_children(store, root, *, task_id: str = "", depth: int = 1,
                   window: int = 5) -> ToolResult:
    """"我直接下级"的读数入口（判据在 `agenttrace.children_with_facts`）。

    身份从调用上下文读（`AgentLoop._do_tool` 用 `calling_as` 挂上），与
    `conductor.broadcast` 同一处挂点：工具的形状里没有"我是谁"这一格。
    非 M 角色只许看自己的下级 —— 传别人的台账号会被受控拒绝，否则"一层"这条
    约束只要换一个 task_id 就绕过去了。
    """
    from .. import agenttrace as AT
    from .. import conductor as COND

    if store is None:
        return fail("没有工作区（装配时既没给 store 也没给 root）⇒ 读不到台账，本次没查成",
                    kind="no_store", checked=False)
    mine = str(task_id or "") or str(COND.current_task_id() or "")
    role = str(COND.current_caller_role() or "")
    if not mine:
        return fail(
            "读不到'我是谁'（没有台账号，也没有传 task_id）⇒ 不猜一个实例来追。"
            "生产路径上这个号由 `AgentLoop._do_tool` 用 `calling_as` 挂上；"
            "脚本里可以显式传 task_id。",
            kind="no_identity", checked=False)
    try:
        rows = store.rows("tasks")
    except Exception as exc:  # noqa: BLE001 - 读不成不等于没有子代理
        return fail(f"tasks 台账读不成（{type(exc).__name__}: {exc}）⇒ 本次没查成",
                    kind="store_error", checked=False)
    me_row = next((r for r in rows if str(r.get("task_id") or "") == mine), None)
    if me_row is None:
        return fail(f"台账里没有 {mine} 这一行 ⇒ 不知道自己是谁，也不猜一个父",
                    kind="not_found", checked=True, task_id=mine)
    if role != S.CONDUCTOR_ROLE:
        my_task = str(COND.current_task_id() or "")
        if my_task and mine != my_task:
            return fail(
                f"非主控角色只能看自己的直接下级（你这一趟是 {my_task}，传的是 {mine}）"
                "⇒ 一层不是'换一个 task_id'就能绕过的。要看别人那一支请向 M 请求："
                "`conductor.escalate(need=\"深看请求：…\", kind=\"other\")`",
                kind="not_mine", checked=True, task_id=mine)
    data = AT.children_with_facts(store, root or getattr(store, "root", None) or ".",
                                  me_row, depth=depth, window=window)
    if not data.get("children"):
        data["note"] = ("台账里我名下没有直接下级（这是查过了、确实没有；"
                        "不是'没读成'）")
    return ok(data)


#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (trace_relation, ('_g',)),
    (trace_concept, ('_g',)),
    (trace_literature, ('_g', 'store')),
    (trace_chain, ('_g',)),
    # 父子链（2026-10-24 业主裁定）：store 读台账，root 读会话记录与手稿。
    (trace_children, ('store', 'root')),
)


def register(registry: ToolRegistry, *, store: Any = None, graph: Any = None,
             root: Any = None) -> list[str]:
    """注册溯源工具，返回工具名列表。
    数据源三态（不要把它读成布尔）：
    | 装配情况 | 行为 ||---|---|| 显式传入 `graph` | 四个工具都从这张图回答 || 没传 graph，但传了 `store` | 每次调用用 
    `RelationGraph.from_store(store)` 现建 || 两者都没有 | 四个工具一律 
    `fail(kind="no_graph", checked=False)` —— 没查 |
    最后一行是本模块曾经的缺陷：那时 `_g()` 会用一张空图兜底，于是"没有图可查"被显示成"查过了，这些代号都不存在"。现在宁可明确失败。
    `L3` 还需要 `store` 才能把文献表里的相对路径解析成磁盘上的绝对路径（`store.library_path` 还会做一次"不许越出 library/"的检查）。
    只有 graph、没有 store 时 L1/L2 照常可用，L3 会明确失败而不是假装读过文件。
    """
    holder_graph: RelationGraph | None = graph if isinstance(graph, RelationGraph) else None

    def _g(tool: str) -> tuple[RelationGraph | None, ToolResult | None]:
        """取关系图。三态 —— (图, None) / (None, 结构化失败)：
        
        | 情形 | 返回 ||---|---|| 显式给了 graph，或 store 能建出图 | `(graph, None)` || 没有图可查（既没给 graph 也没给
        store） | `(None, fail(kind="no_graph", checked=False))` || 有 store 但建图失败（表坏了 / 锁超时） | 
        `(None, fail(kind="store_error", checked=False))` |
        
        这里不能再用"空图"兜底（本函数曾经的缺陷）：空图会让每个代号都落进`missing`，`known_relations`/`known_concepts`/
        `known_literature` 全是 `[]`，于是调用方读到的是"查过了，确实没有这条代号" —— 而真相是"根本没有图可查"。这正是本模块第 26-32 行立的规
        矩（「没做」与「做了但没结果」是两件事）所禁止的折叠：它会让调用方以为自己的代号错了。
        """
        if holder_graph is not None:
            return holder_graph, None
        if store is None:
            return None, fail(
                f"{tool}：**没有图可查** —— 装配时既未提供 graph，也未提供 store，"
                "因此本次**没查**。这与「查了、没有这个代号」是两件事："
                "后者说明代号错了，前者说明数据源根本没接上。",
                kind="no_graph",
                checked=False,
            )
        try:
            return RelationGraph.from_store(store), None
        except Exception as exc:  # noqa: BLE001
            # StoreError（表损坏 / 锁超时）此前会逃出工具层，被 base.py:381-382
            # 兜成没有类型信息的 kind="unexpected"；这里把它变成可读的失败，
            # 并且明确 checked=False —— "读表失败"不是"图里没有"。
            return None, fail(
                f"{tool}：从 store 建关系图失败（{type(exc).__name__}: {exc}）⇒ **没查成**"
                "（不是「图里没有」）。请先修复/重建相关表。",
                kind="store_error",
                checked=False,
            )





    # \T-8\：声明与工具体都在模块级（\@tool\ 写进 \fn.__tool_spec__\），
    # 这里只把装配期算出来的值按位置绑上去（\partial\）。
    _bound: dict[str, Any] = {}
    _bound['_g'] = _g
    _bound['store'] = store
    _bound['root'] = root
    names: list[str] = []
    for _fn, _deps in _TOOL_FUNCTIONS:
        names.append(registry.register(replace(
            _fn.__tool_spec__, handler=partial(_fn, *[_bound[k] for k in _deps]))).name)
    return names


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    import sys
    import tempfile
    from pathlib import Path as _P

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: R001 - 自检块：控制台重配失败（老终端不支持 UTF-8）不影响自检结论
        pass

    from ..store import Store
    from .base import ToolRegistry

    print("=" * 72)
    root = _P(tempfile.mkdtemp(prefix="agentflow_trace_"))
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
    with st.tx(*CR.tables_for_concept_write("relations", "literature"),
               actor="selftest", note="fixture") as tx:
        for r in concepts:
            CR.upsert_legacy_shaped(tx, r)
        for r in relations:
            tx.upsert("relations", r)
        for r in literatures:
            tx.upsert("literature", r)
    print(f"    落库：概念 {len(CR.view(st, shape='legacy')['rows'])} 关系 {len(st.rows('relations'))} 文献 {len(st.rows('literature'))}")

    reg = ToolRegistry(name="trace")
    # 绑定角色（`P-14`）：`trace.*` 的声明角色是 C/D，而这张表代表的是只读的 C。
    reg.bound_role = "C"
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
