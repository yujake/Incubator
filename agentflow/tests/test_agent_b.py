"""B 智能体：概念复用、related_concepts 派生、无文件不堵队列、抽取失败不置 processed。

（DESIGN.md §6.1/§6.2：写入顺序与自愈语义。）

并表（S1r）之后本文件有两处读法换了落点，判据本身没放宽：

- 概念行的读口是 `conceptrows.view(..., shape="legacy")`（老字段名投影）——
  `store.rows("concepts")` 在新 schema 下是受控错；
- `related_concepts` 是老表专有的一格，新标准里没有它的承载点：真相由 relations
  表回答（`dedup.derive_related_concepts` 仍是唯一实现）⇒ 原来断言"概念行里那一格
  == 派生值"的地方，改成断言"同一件事的派生面"（互含、升序、不含自身），
  并补一条负控证明它不是恒空。
"""

from __future__ import annotations

from agentflow import schema as S
from agentflow import conceptrows as CR
from agentflow import dedup as D
from agentflow.agent_b import AgentB
from agentflow.extract import DocumentText, extract_text
from agentflow.llm import ConceptDraft, RelationDraft
from agentflow.schema import PageRange
from agentflow.store import lease_expired
from agentflow.tools.base import ToolResult, fail, ok

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
    concepts = CR.view(store, shape="legacy")["rows"]
    assert len(concepts) == 1, f"同名概念被重复创建：{concepts}"
    assert concepts[0]["name"] == "群"
    # related_concepts 是老表专有的一格：(并表之后)新标准里没有它的承载点，读老字段名
    # 拿到的是空列表（"没有这一格"），不是"没有边"。真相在 relations 表 —— 这里断言
    # 从关系表现算出来的邻域为空（这条路径上一条关系都没写）。
    assert D.derive_related_concepts(concepts[0]["concept_id"], store.rows("relations"),
                                     include_suspect=True) == []


# --------------------------------------------------------------------------- related_concepts 派生


def test_related_concepts_are_derived_from_relations(store):
    """相关概念必须由关系表整体派生：互相包含、升序、不含自身（§6.2）。

    改写（并表 S1r）：原文断言"概念行里的 related_concepts == 派生值"。并表之后那一格
    在新标准里没有承载点（`view(shape="legacy")` 对 statements 那一档一律投影成空列表
    ⇒ 拿它比派生值会恒真/恒假），真相由 relations 表回答，`dedup.derive_related_concepts`
    仍是唯一实现。所以这里断的是同一件事的派生面：

    ① 互含（关系是无向的：a 的相关集合里有 b ⇔ b 的里面也有 a）；
    ② 形状（升序去重、不含自身）；
    ③ 负控：这条判据不是恒空 —— 0000 恰好同时连着 0001（旧关系）与 0002（新关系）。
    """
    write_library_file(store, "0001/c.txt", f"环是一个集合。{QUOTE}")
    add_literature(store, S.format_id(0), title="旧文献", path=None, processed=True)
    add_literature(store, S.format_id(1), title="新文献", path="0001/c.txt")
    add_concept(store, S.format_id(0), "群")
    add_concept(store, S.format_id(1), "阿贝尔群")
    add_relation(
        store,
        S.format_id(0),
        [S.format_id(0), S.format_id(1)],
        S.format_id(0),
        quote="A group is a set with a binary operation.",
        status="active",
    )

    extractor = StubExtractor(
        concepts=[ConceptDraft(name="环", definition="有两个运算的代数结构", aliases=[], source_lit_id=S.format_id(1))],
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

    concepts = {c["concept_id"]: c for c in CR.view(store, shape="legacy")["rows"]}
    relations = store.rows("relations")
    assert set(concepts) == {S.format_id(0), S.format_id(1), S.format_id(2)}

    derived = {
        cid: D.derive_related_concepts(cid, relations, include_suspect=True)
        for cid in concepts
    }
    # 手工构造的旧关系 (0000,0001) 与新关系 (0000,0002) 都应体现在两侧
    assert S.format_id(1) in derived[S.format_id(0)]
    assert S.format_id(2) in derived[S.format_id(0)]
    assert derived[S.format_id(1)] == [S.format_id(0)]
    assert derived[S.format_id(2)] == [S.format_id(0)]
    # ③ 负控：邻域非空且恰好这两条（"派生"不是恒空，也不是把整张表的邻域都算上）
    assert derived[S.format_id(0)] == [S.format_id(1), S.format_id(2)]

    for cid, rel in derived.items():
        assert rel == sorted(set(rel)), "派生集合必须升序去重"
        assert cid not in rel, "派生集合不能含自身"
        for other in rel:
            assert cid in derived[other], "关系是无向的：派生集合必须互含"

    # 老字段名那一格在新标准里没有权威值 —— 这件事必须显式（否则按老字段名读的人
    # 会把"没有这一格"读成"这个概念的邻域是空集"）。
    assert all(c["related_concepts"] == [] and c["legacy_related"] is False
               for c in concepts.values())


def test_related_concepts_ignores_rejected_relations(store):
    """被拒绝（rejected）的关系不计入相关概念（§6.2）。

    改写（并表 S1r）：真相在 relations 表 ⇒ 从它派生；并补一条负控（把那条关系改成
    active，派生结果必须变非空）——否则"派生结果为空"可能只是因为派生本身不工作。
    """
    write_library_file(store, "0002/d.txt", QUOTE)
    add_literature(store, "0002", title="D", path="0002/d.txt")
    add_concept(store, "0000", "群")
    add_concept(store, "0001", "阿贝尔群")
    add_relation(store, "0000", ["0000", "0001"], "0002", quote="q", status="rejected", sync=True)

    extractor = StubExtractor(concepts=[], relations=[])
    _agent_b(store, extractor).run_once()

    assert D.derive_related_concepts("0000", store.rows("relations"), include_suspect=True) == []
    assert D.derive_related_concepts("0001", store.rows("relations"), include_suspect=True) == []

    # 负控：同一条边一旦不是 rejected，它就必须出现在派生集合里
    with store.tx("relations", actor="test") as tx:
        row = tx.find("relations", relation_id="0000")
        row["status"] = "active"
        tx.upsert("relations", row, note="test:unreject")
    assert D.derive_related_concepts("0000", store.rows("relations"), include_suspect=True) == ["0001"]
    assert D.derive_related_concepts("0001", store.rows("relations"), include_suspect=True) == ["0000"]


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


# ------------------------------------------------- "没有产出"不许报成成功（T5 真机读数）


def test_the_digested_reading_does_not_count_rows_that_were_only_skipped():
    """判据（2026-10-15，T5 第 8 趟 `t5h`）：`digested` = `processed` − `unreadable`。

    `processed` 这一个布尔里同时装着**处置相反**的两件事：「我读过并抽了」与
    「我连文件都没有、跳过了」。下游读的全是 `processed` ⇒ 台账上写着"34 条已消化"，
    真相是"10 条有全文"。这一格就是把那一折打开的地方，所以它是**读数判据的第一条**：
    折回去了，后面两条就没意义了。
    """
    from agentflow.agent_b._support import BRunResult, task_outcome

    skipped = BRunResult(processed=5, unreadable=5, skipped_reason="no_unprocessed_literature")
    assert skipped.digested == 0
    assert task_outcome(skipped)[0] == "no_result"

    mixed = BRunResult(processed=5, unreadable=4, concepts_created=2)
    assert mixed.digested == 1 and task_outcome(mixed)[0] == "ok"

    # 失败那一档：一篇都没真消化、也没有产出 ⇒ `failed`（不是 no_result，也不是 ok）
    assert task_outcome(BRunResult(failed=3))[0] == "failed"

    # 只复用不新建（读了、判重后没新行）也是"真消化过"，不许算成没产出
    reused = BRunResult(processed=1, concepts_reused=3)
    assert reused.digested == 1 and task_outcome(reused)[0] == "ok"


def test_a_run_that_only_skipped_unreadable_rows_is_no_result_not_ok(store):
    """判据（同上，端到端）：**什么都没消化**不许报成 ok —— 这一趟就是 T5 那一趟的缩影。

    真机现场：A 取回 41 条，其中 31 条没有本地全文；B 连着跑了 11 次、11 次
    `outcome=ok`（`detail` 还是"执行完成（handler 未声明 outcome，按有产出处理）"），
    而新建概念 0 / 新增关系 0。主控据此以为"文献消化过了"，继续派同一种活 ——
    一整轮预算花在读不到的东西上。**"什么都没做成"被报成了成功。**
    """
    add_literature(store, "0000", title="没有全文", path=None)
    add_literature(store, "0001", title="文件被删", path="0001/gone.txt")
    b = _agent_b(store, StubExtractor())
    out = b.run()
    assert out["digested"] == 0, out
    assert out["unreadable"] == 2 and out["processed"] == 2, out
    assert out["outcome"] == "no_result", out
    assert "没有任何产出" in out["detail"], out["detail"]
    assert "没有本地全文 2 篇" in out["detail"], out["detail"]


def test_a_run_that_really_digested_is_ok_and_says_how_many(store):
    """反负控（与上一条配对）：真抽过必须是 `ok`，且 `digested` 与产出一起报出来。

    没有这一条，上一条可以靠"凡 run 都报 no_result"满足 —— 而那样主控会把**真干活**
    的那几趟也当成白跑，处置方向正好反了。
    """
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="有全文", path="0000/a.txt")
    b = _agent_b(store, StubExtractor(
        concepts=[ConceptDraft(name="群", definition="d", aliases=[], source_lit_id="0000")]))
    out = b.run()
    assert out["digested"] == 1 and out["outcome"] == "ok", out
    assert "真消化 1 篇" in out["detail"] and "新建概念 1" in out["detail"], out["detail"]



# --------------------------------------------------------------------------- 抽取失败


def test_extractor_failure_does_not_mark_processed(store):
    """抽取抛异常时不得置 processed=true（留给租约重试），但必须记 last_mine_error。

    这一条在 2026-10-02（`D-2`）改过一次期望值，这是修正不一致，不是放宽：
    原先断言 `lease_until is None`（理由是"必须释放租约以便重试"），可那条租约
    从来没有被写下来过，而 `_claim` 的跳过判据当时要求 `claimed_by` 非空 ——
    于是"释放"出来的行当轮就被重领，`mine_attempts` 在一次调用里烧到上限
    （读数：`temp/_probe_b_claim.py` 4 次连续 `run_once` 读到 0→3 并当场判死）。
    现在与 `agent_a` 同口径：持有者置空 + 写下未来时刻的退避租约。
    """
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")
    b = _agent_b(store, StubExtractor(error=RuntimeError("llm down")))
    res = b.run_once()

    assert res.failed == 1 and res.processed == 0
    row = store.rows("literature")[0]
    assert row["processed"] is False, "抽取失败不等于处理完成"
    assert "llm down" in (row["last_mine_error"] or "")
    assert row["claimed_by"] is None, "持有者要放开：这条活现在不属于任何实例"
    assert row["lease_until"], "退避租约必须真的被写下来（写了才有人认它）"
    assert not lease_expired(row["lease_until"]), "退避租约当场有效 ⇒ 本轮不许再领"
    assert row["mine_attempts"] == 1

    # 同一进程立刻再跑：不许重领（这正是上面那条租约的用处）。
    second = b.run_once()
    assert second.failed == 0 and second.processed == 0, "退避期内不许再抽一次"
    assert second.skipped_lease_backoff == 1, "被跳过的那条要记进'我们自己的退避'"
    assert second.skipped_lease_active == 0, "它不是'别人持着'"
    assert second.skipped_reason == "pending_literature_all_in_backoff"
    assert store.rows("literature")[0]["mine_attempts"] == 1, "退避期内不许烧重试预算"


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
    # 计数必须与最终落库状态一致：这条关系落库为 suspect，所以 relations_suspect
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
    # `E-11`：这一档必须单独可数，否则"页码不符"在聚合读数里看不见
    # （它原先只活在下面那个 `_quote_check` 字典里，没有检查器消费它）。
    assert res.quotes_out_of_declared_range == 1, res.to_dict()
    check = rel["_quote_check"]
    assert check["reason"] == "substring_match_outside_declared_range", "页码错误必须被显式记录"
    assert check["matched_page"] == 2


def test_a_correct_page_does_not_count_as_out_of_declared_range(store):
    """`E-11` 正控的反面：页码正确的引文计 `verified`，不计"页码不符"。

    没有这一条，把判据写成"凡 verified 就 +1"也能让上面那条绿 ——
    而那样这一档就又折回 `quotes_verified` 里了（正是 `E-11` 的现状）。
    """
    write_library_file(store, "0000/a.txt", "占位")
    add_literature(store, "0000", title="A", path="0000/a.txt")
    doc = DocumentText(text=QUOTE, pages=[QUOTE, "第二页。"], source_kind="pdf")
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
                page_range=PageRange(1, 1, "p. 1"),   # 引文就在第 1 页
            )
        ],
    )
    res = _agent_b(store, extractor, extract=lambda _p: doc, quote_widen_pages=1).run_once()

    rel = store.rows("relations")[0]
    assert rel["_quote_check"]["reason"] == "substring_match"
    assert res.quotes_verified == 1
    assert res.quotes_out_of_declared_range == 0, (
        "页码正确的引文被算进了'页码不符'那一档 ⇒ 这一档又失去意义了"
    )


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
# --------------------------------------------------------------------------- R2b-⑫
# 无文本层 ⇒ 走 OCR 那条早就声明好、却没人调用的路（改前：直接放弃）
#
# 口径：`checked` 是"试没试"，不是"成没成"。三种"没成"必须分得开 ——
# 后端不可用（unavailable）／试过但没有结果（ran_empty）／两条读法互相矛盾。
# 负控：改前那一句 `无文本层（扫描版？）⇒ 无从逐字定位` 必须不再出现，
# 且 `ocr.detect_text_layer` 说"有文本层"时不许去调 `ocr.run`。

OLD_NO_TEXT_LAYER_REASON = "无文本层（扫描版？）⇒ 无从逐字定位"


class FakeOcrSurface:
    """假工具面：按工具名给预设读数，并记下调用顺序（不起真 OCR、不碰真注册表）。"""

    def __init__(self, *, detect=None, backends=None, run=None):
        self.script = {
            "ocr.detect_text_layer": detect,
            "ocr.backends": backends,
            "ocr.run": run,
        }
        self.calls: list[str] = []

    def __call__(self, name, params):
        self.calls.append(name)
        got = self.script.get(name)
        if got is None:
            return fail(f"假工具面没给 {name} 的读数", tool=name)
        return got if isinstance(got, ToolResult) else ok(dict(got))


class _NoTextDoc:
    """替身抽取器的产物：`pages == []`（无文本层）。"""

    pages: list[str] = []

    def text_at(self, lo, hi):
        return ""


def _ocr_agent(store, surface, extract=lambda _p: _NoTextDoc()) -> AgentB:
    b = _agent_b(store, StubExtractor())
    b.extract_text = extract
    b._ocr_surface = surface          # 夹具注入口
    return b


def _scan_lit(store) -> dict:
    write_library_file(store, "0000/a.txt", "空")
    add_literature(store, "0000", title="扫描件", path="0000/a.txt")
    return dict(store.rows("literature")[0])


def test_no_text_layer_tries_ocr_and_reports_unavailable(store):
    """后端不可用必须报 `unavailable`，不是"无文本层"，也不是静默放弃。"""
    lit = _scan_lit(store)
    surface = FakeOcrSurface(
        detect={"has_text_layer": False, "pages": 0, "chars": 0, "source_kind": "pdf"},
        backends={"any_ocr_backend_available": False, "available": [],
                  "verdict": "无任何可用 OCR 后端：easyocr 与 pytesseract 都不可用"},
    )
    b = _ocr_agent(store, surface)
    doc, why = b._load_doc_for(lit)

    assert doc is None
    assert surface.calls == ["ocr.detect_text_layer", "ocr.backends"], (
        "没有可用后端时不该去跑 ocr.run：它只会先花几十秒栅格化，再 fail 在同一个原因上"
    )
    assert "unavailable" in why and "OCR" in why, f"原因必须点名 OCR 与 unavailable：{why}"
    assert OLD_NO_TEXT_LAYER_REASON not in why, "改前那一句『无文本层（扫描版？）』必须不再出现"
    assert b.ocr_readings == [{"lit_id": "0000", "checked": True, "via": "backends",
                               "reason": why,
                               "reading": {"any_ocr_backend_available": False}}]


def test_negative_control_text_layer_present_is_not_an_ocr_case(store):
    """负控：探测器说"有文本层"⇒ 不许去调 `ocr.run`（那是错的药），只如实报矛盾。"""
    lit = _scan_lit(store)
    surface = FakeOcrSurface(
        detect={"has_text_layer": True, "pages": 3, "chars": 120, "source_kind": "pdf"},
        backends={"any_ocr_backend_available": True, "available": ["easyocr"]},
        run={"backend": "easyocr", "total_chars": 4, "pages": [{"page": 1, "text": "识别的字"}]},
    )
    b = _ocr_agent(store, surface)
    doc, why = b._load_doc_for(lit)

    assert doc is None
    assert "ocr.run" not in surface.calls, "两条读法矛盾时做 OCR 会把矛盾盖掉"
    assert "矛盾" in why and OLD_NO_TEXT_LAYER_REASON not in why
    assert b.ocr_readings[-1]["via"] == "detect" and b.ocr_readings[-1]["checked"] is True


def test_ocr_text_lands_on_the_page_numbers_ocr_reports(store):
    """OCR 出来的文本按 `ocr.run` 自己报的页号落位（不按列表下标）。"""
    lit = _scan_lit(store)
    surface = FakeOcrSurface(
        detect={"has_text_layer": False, "pages": 0, "chars": 0, "source_kind": "pdf"},
        backends={"any_ocr_backend_available": True, "available": ["easyocr"]},
        run={"backend": "easyocr", "total_chars": 5, "pages_requested": [1, 3],
             "pages": [{"page": 1, "text": "A"}, {"page": 3, "text": "C"}]},
    )
    b = _ocr_agent(store, surface)
    doc, why = b._load_doc_for(lit)

    assert why == "" and doc is not None, f"识别出字符就不该再报不可用：{why}"
    assert doc.pages == ["A", "", "C"], (
        "第 3 页的内容被写进了第 2 页 ⇒ 逐字引文会出现『页码错、字面全对』这种最难查的错"
    )
    assert doc.text_at(3, 3) == "C"
    assert b.ocr_readings[-1]["via"] == "ocr" and b.ocr_readings[-1]["checked"] is True
    assert b.ocr_readings[-1]["reading"]["backend"] == "easyocr"


def test_ocr_ran_but_produced_nothing_is_not_no_text_layer(store):
    """后端真实执行过但产出为空 ⇒ 明说"试了还是没有"，不折成"无文本层"。"""
    lit = _scan_lit(store)
    surface = FakeOcrSurface(
        detect={"has_text_layer": False, "pages": 0, "chars": 0, "source_kind": "pdf"},
        backends={"any_ocr_backend_available": True, "available": ["easyocr"]},
        run={"backend": "easyocr", "total_chars": 0, "pages": [{"page": 1, "text": "   "}],
             "note": "backend=easyocr 真实执行，但产出为空（做了但没结果）。"},
    )
    b = _ocr_agent(store, surface)
    doc, why = b._load_doc_for(lit)

    assert doc is None
    assert "试过 OCR" in why and "ran_empty" in why, f"『试了还是没有』必须说出来：{why}"
    assert OLD_NO_TEXT_LAYER_REASON not in why
    assert b.ocr_readings[-1]["via"] == "run"
