"""B 智能体：概念复用、related_concepts 派生、无文件不堵队列、抽取失败不置 processed。

（DESIGN.md §6.1/§6.2：写入顺序与自愈语义。）
"""

from __future__ import annotations

from abflow import dedup as D
from abflow.agent_b import AgentB
from abflow.extract import DocumentText, extract_text
from abflow.llm import ConceptDraft, RelationDraft
from abflow.schema import PageRange

from conftest import add_concept, add_literature, add_relation, write_library_file

QUOTE = "An abelian group is a group in which the commutative law holds."


# --------------------------------------------------------------------------- 替身


class StubExtractor:
    """确定性抽取器替身：返回预设 draft，可选择性地抛异常。"""

    def __init__(self, concepts=(), relations=(), error: Exception | None = None):
        self._concepts = list(concepts)
        self._relations = list(relations)
        self.error = error
        self.calls = 0
        self.metas: list[dict] = []

    def extract(self, doc, lit_id, meta):
        self.calls += 1
        self.metas.append(meta)
        if self.error is not None:
            raise self.error
        return list(self._concepts), list(self._relations)


class SameConceptEveryTime:
    """两篇文献都提到同一个概念名（用于验证"复用而非重复创建"）。"""

    def extract(self, doc, lit_id, meta):
        return (
            [ConceptDraft(name="群", definition=f"来自 {lit_id} 的定义", aliases=["group"], source_lit_id=lit_id)],
            [],
        )


def _agent_b(store, extractor, extract=extract_text, **cfg) -> AgentB:
    config = {"lease_seconds": 900, "max_attempts": 3, "dup_strong": 0.92, "dup_review": 0.72}
    config.update(cfg)
    return AgentB(store, extractor=extractor, extract_text=extract, config=config)


# --------------------------------------------------------------------------- 概念复用


def test_concept_is_reused_instead_of_created_twice(store):
    """两篇文献提到同一概念名时只允许建一个概念行（§6.1 第 4 步：解析在锁内做）。"""
    write_library_file(store, "0000/a.txt", "A group is a set with a binary operation.")
    write_library_file(store, "0001/b.txt", "A group is a set together with a binary operation and inverses.")
    add_literature(store, "0000", title="A", path="0000/a.txt")
    add_literature(store, "0001", title="B", path="0001/b.txt")

    b = _agent_b(store, SameConceptEveryTime())
    first = b.run_once()
    second = b.run_once()

    assert first.concepts_created == 1 and second.concepts_created == 0
    assert second.concepts_reused == 1
    concepts = store.rows("concepts")
    assert len(concepts) == 1, f"同名概念被重复创建：{concepts}"
    assert concepts[0]["name"] == "群"
    assert concepts[0]["related_concepts"] == []


# --------------------------------------------------------------------------- related_concepts 派生


def test_related_concepts_are_derived_from_relations(store):
    """related_concepts 必须由关系表整体派生：互相包含、升序、不含自身（§6.2）。"""
    write_library_file(store, "0001/c.txt", f"环是一个集合。{QUOTE}")
    add_literature(store, "0000", title="旧文献", path=None, processed=True)
    add_literature(store, "0001", title="新文献", path="0001/c.txt")
    add_concept(store, "0000", "群")
    add_concept(store, "0001", "阿贝尔群")
    add_relation(
        store,
        "0000",
        ["0000", "0001"],
        "0000",
        quote="A group is a set with a binary operation.",
        status="active",
    )

    extractor = StubExtractor(
        concepts=[ConceptDraft(name="环", definition="有两个运算的代数结构", aliases=[], source_lit_id="0001")],
        relations=[
            RelationDraft(
                concept_names=["群", "环"],
                description="环与群的关系",
                quote=QUOTE,
                page_range=PageRange(1, 1, "p. 1"),
            )
        ],
    )
    res = _agent_b(store, extractor).run_once()
    assert res.relations_added == 1 and res.relations_duplicate == 0

    concepts = {c["concept_id"]: c for c in store.rows("concepts")}
    relations = store.rows("relations")
    assert set(concepts) == {"0000", "0001", "0002"}

    # 手工构造的旧关系 (0000,0001) 与新关系 (0000,0002) 都应体现在两侧
    assert "0001" in concepts["0000"]["related_concepts"]
    assert "0002" in concepts["0000"]["related_concepts"]
    assert concepts["0001"]["related_concepts"] == ["0000"]
    assert concepts["0002"]["related_concepts"] == ["0000"]

    for cid, c in concepts.items():
        rel = c["related_concepts"]
        assert rel == sorted(set(rel)), "related_concepts 必须升序去重"
        assert cid not in rel, "related_concepts 不能含自身"
        assert rel == D.derive_related_concepts(cid, relations), "落库值必须等于关系表派生值"


def test_related_concepts_ignores_rejected_relations(store):
    """被拒绝（rejected）的关系不计入 related_concepts（§6.2）。"""
    write_library_file(store, "0002/d.txt", QUOTE)
    add_literature(store, "0002", title="D", path="0002/d.txt")
    add_concept(store, "0000", "群")
    add_concept(store, "0001", "阿贝尔群")
    add_relation(store, "0000", ["0000", "0001"], "0002", quote="q", status="rejected", sync=True)

    extractor = StubExtractor(concepts=[], relations=[])
    _agent_b(store, extractor).run_once()

    concepts = {c["concept_id"]: c for c in store.rows("concepts")}
    assert concepts["0000"]["related_concepts"] == []
    assert concepts["0001"]["related_concepts"] == []


# --------------------------------------------------------------------------- 无法读取的文献


def test_literature_without_local_file_is_marked_processed(store):
    """path=null 或文件缺失时必须置 processed=true 并记明原因，否则会永远堵住队列。"""
    add_literature(store, "0000", title="下载失败", path=None)
    add_literature(store, "0001", title="文件被删", path="0001/gone.txt")

    b = _agent_b(store, StubExtractor())
    first = b.run_once()
    second = b.run_once()
    assert first.unreadable == 1 and first.processed == 1
    assert second.unreadable == 1 and second.processed == 1

    rows = {r["lit_id"]: r for r in store.rows("literature")}
    assert rows["0000"]["processed"] is True
    assert rows["0000"]["last_mine_error"] == "no_local_file"
    assert rows["0001"]["processed"] is True
    assert "file_missing" in (rows["0001"]["last_mine_error"] or "")
    assert rows["0000"]["claimed_by"] is None

    assert b.run_once().skipped_reason == "no_unprocessed_literature", "队列必须被清空"


# --------------------------------------------------------------------------- 抽取失败


def test_extractor_failure_does_not_mark_processed(store):
    """抽取抛异常时不得置 processed=true（留给租约重试），但必须记 last_mine_error。"""
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")
    b = _agent_b(store, StubExtractor(error=RuntimeError("llm down")))
    res = b.run_once()

    assert res.failed == 1 and res.processed == 0
    row = store.rows("literature")[0]
    assert row["processed"] is False, "抽取失败不等于处理完成"
    assert "llm down" in (row["last_mine_error"] or "")
    assert row["claimed_by"] is None and row["lease_until"] is None, "必须释放租约以便重试"
    assert row["mine_attempts"] == 1


def test_extract_text_failure_also_keeps_processed_false(store):
    """文本抽取（读文件）阶段抛异常同样不得置 processed=true。"""
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")

    def boom(_path):
        raise RuntimeError("pdf backend exploded")

    b = _agent_b(store, StubExtractor(), extract=boom)
    res = b.run_once()
    assert res.failed == 1
    assert store.rows("literature")[0]["processed"] is False


# --------------------------------------------------------------------------- 引文不可校验


def test_unverifiable_quote_is_suspect_not_dropped(store):
    """无文本层时引文无法校验 → 关系仍落库但 status=suspect、quote_verified=None（不假装通过）。"""
    write_library_file(store, "0000/a.txt", "占位")   # 文件存在，但抽取器返回无文本层
    add_literature(store, "0000", title="扫描件", path="0000/a.txt")

    extractor = StubExtractor(
        concepts=[
            ConceptDraft(name="群", definition="d", aliases=[], source_lit_id="0000"),
            ConceptDraft(name="阿贝尔群", definition="d", aliases=[], source_lit_id="0000"),
        ],
        relations=[
            RelationDraft(
                concept_names=["群", "阿贝尔群"],
                description="d",
                quote=QUOTE,
                page_range=PageRange(1, 1, "p. 1"),
            )
        ],
    )
    b = _agent_b(store, extractor, extract=lambda _p: DocumentText(text="", pages=[], source_kind="pdf"))
    res = b.run_once()

    assert res.quotes_unknown == 1
    rel = store.rows("relations")[0]
    assert rel["status"] == "suspect"
    assert rel["quote_verified"] is None, "无文本层必须是 None，不是 False/True"
    assert res.processed == 1, "有未校验引文也要把文献标记处理完（不堵队列）"
    # 计数必须与**最终落库状态**一致：这条关系落库为 suspect，所以 relations_suspect
    # 应计入它；而 suspect_by_quote 单独记"因引文不可校验而降级"的那部分。
    # （原实现只统计"判重判成 suspect"，会与表里的实际条数对不上。）
    assert res.relations_suspect == 1
    assert res.suspect_by_quote == 1
    assert res.relations_added == 0, "引文没通过校验的不能算作正常新增"


def test_misdeclared_page_is_flagged_in_stored_quote_check(store):
    """页码写错但在 ±widen 内命中 → 仍落库，且引文校验明细必须显式标出"页码不在声明范围"。"""
    write_library_file(store, "0000/a.txt", "占位")
    add_literature(store, "0000", title="A", path="0000/a.txt")
    doc = DocumentText(text=f"第一页内容。\n{QUOTE}", pages=["第一页内容。", QUOTE], source_kind="pdf")
    extractor = StubExtractor(
        concepts=[
            ConceptDraft(name="群", definition="d", aliases=[], source_lit_id="0000"),
            ConceptDraft(name="阿贝尔群", definition="d", aliases=[], source_lit_id="0000"),
        ],
        relations=[
            RelationDraft(
                concept_names=["群", "阿贝尔群"],
                description="d",
                quote=QUOTE,
                page_range=PageRange(1, 1, "p. 1"),   # 实际在第 2 页
            )
        ],
    )
    b = _agent_b(store, extractor, extract=lambda _p: doc, quote_widen_pages=1)
    res = b.run_once()

    rel = store.rows("relations")[0]
    assert rel["quote_verified"] is True
    assert rel["status"] == "active"
    assert res.quotes_verified == 1
    check = rel["_quote_check"]
    assert check["reason"] == "substring_match_outside_declared_range", "页码错误必须被显式记录"
    assert check["matched_page"] == 2


def test_not_found_quote_forces_suspect_status(store):
    """引文在文档里根本找不到 → verified=False 且关系降级为 suspect（保留证据而不是丢弃）。"""
    write_library_file(store, "0000/a.txt", "完全无关的一段话。")
    add_literature(store, "0000", title="A", path="0000/a.txt")
    extractor = StubExtractor(
        concepts=[
            ConceptDraft(name="群", definition="d", aliases=[], source_lit_id="0000"),
            ConceptDraft(name="阿贝尔群", definition="d", aliases=[], source_lit_id="0000"),
        ],
        relations=[
            RelationDraft(
                concept_names=["群", "阿贝尔群"],
                description="d",
                quote=QUOTE,
                page_range=PageRange(1, 1, "p. 1"),
            )
        ],
    )
    b = _agent_b(store, extractor)
    res = b.run_once()

    assert res.quotes_failed == 1
    rel = store.rows("relations")[0]
    assert rel["quote_verified"] is False
    assert rel["status"] == "suspect", "校验失败的关系必须落库并标黄，而不是丢弃"
    assert res.processed == 1
