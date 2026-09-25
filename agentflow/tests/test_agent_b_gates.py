"""B 侧新增闸门的验收：I6 写入期一致性、I4 定向重抽取、I5 合并决定。

（`DESIGN-INTERACTIONS.md` §1 / §4；本项目历史上最贵的三类错误都在这三条里。）

三条纪律贯穿本文件，也是它存在的理由：

1. 三态：`True` / `False` / `None` 必须分得开。
   "没检查"不许被读成"不冲突"，"没做成"不许被写成"做过了、结论是没有"。
2. 只动该动的：I4 只允许改目标关系；诊断字段与计数器必须让"闸门跑了没有"
   从外部可见（否则"接上了"与"没接上"在数据上一模一样）。
3. 负控：先构造"它不该触发的场景"，断言它确实没触发。
   只有正向信号时，"有"和"没有"一样容易通过测试。

I6 这一节还有一条本任务期间发生的真实修复要守住（`interactions.py` 的两处行为修正）：

- `detect_contradictions` 原来的 `only_a != only_b` 把"提到肯定式"与
  "压根没提这个词"当成对立（中文里"是"无处不在 ⇒ 实测 24% 假报警）；
- `concept_pair_key` 原来是直接读行里的字段，而表里存的名字是
  `concept_group_key` ⇒ 对直接从表里读出来的行，函数恒返回空（完全静默）。

因此下面的用例既断"真实对立会被抓住"，也断"没有对立时不许报警"，
并且一律用真实表行的形状（只有 `concept_group_key`）当输入 ——
如果哪天又有人让闸门依赖"调用方预先算好 `concept_pair_key`"，这里会立刻红。
"""

from __future__ import annotations

import inspect
import json
import threading

import pytest

from agentflow import dedup as D
from agentflow import interactions as I
from agentflow import schema as S
from agentflow import textutil as T
from agentflow.agent_b import REPROCESS_RESULTS, AgentB
from agentflow.extract import extract_text
from agentflow.llm import RelationDraft
from agentflow.schema import PageRange
from agentflow.store import Store
from agentflow.verify import verify_all

from conftest import (
    TS,
    add_literature,
    add_relation,
    read_data_bytes,
    sync_counters,
    write_library_file,
)

QUOTE = "An abelian group is a group in which the commutative law holds."


# --------------------------------------------------------------------------- 替身与构造


class StubExtractor:
    """确定性抽取器替身：只返回预设草稿，不做任何判断。"""

    def __init__(self, concepts=(), relations=()):
        self._concepts = list(concepts)
        self._relations = list(relations)

    def extract(self, doc, lit_id, meta):
        return list(self._concepts), list(self._relations)


class PageExtractor:
    """把"这一页的原文"整段当成一条关系草稿（逐字，便于引文回验通过）。"""

    def extract(self, doc, lit_id, meta):
        pages = list(getattr(doc, "pages", None) or [])
        text = (pages[0] if pages else "").strip()
        return (
            [],
            [
                RelationDraft(
                    concept_names=["group", "abelian group"],
                    description=text,
                    quote=text,
                    page_range=PageRange(1, 1, "p. 1"),
                )
            ],
        )


def _agent_b(store: Store, extractor, extract=extract_text, **cfg) -> AgentB:
    config = {"lease_seconds": 900, "max_attempts": 3, "dup_strong": 0.92, "dup_review": 0.72}
    config.update(cfg)
    return AgentB(store, extractor=extractor, extract_text=extract, config=config)


def _concept(store, cid, name, *, definition="", aliases=(), related=(), **extra) -> dict:
    """插一条概念行，`normalized_name` 走 `textutil.normalize`（与 B 的写入路径一致）。

    conftest 的 `add_concept` 把 `normalized_name` 直接设成原始名字，因此造不出
    "同一个规范化名字的两个节点"（I5 要复现的正是这种历史脏数据）。
    """
    row = S.Concept(
        concept_id=cid,
        name=name,
        definition=definition,
        related_concepts=sorted(related),
        normalized_name=extra.pop("normalized_name", None) or T.normalize(name),
        aliases=list(aliases),
        created_at=TS,
        updated_at=TS,
        **extra,
    )
    row.validate()
    with store.tx("concepts", actor="test") as tx:
        tx.upsert("concepts", row.to_dict())
    return row.to_dict()


def _reprocess(store, pid, relation_ids, *, reason="quote_unverifiable", status="pending",
               result=None, note="", touched=()) -> dict:
    row = S.ReprocessRequest(
        reprocess_id=pid,
        timestamp=TS,
        reason=reason,
        submitted_by="agent-C",
        relation_ids=sorted(relation_ids),
        status=status,
        result=result,
        result_note=note,
        touched_relation_ids=sorted(touched),
    )
    row.validate()
    with store.tx("reprocess_requests", actor="test") as tx:
        tx.upsert("reprocess_requests", row.to_dict())
    return row.to_dict()


def _relation(store, rid) -> dict:
    row = next((r for r in store.rows("relations") if r["relation_id"] == rid), None)
    assert row is not None, f"关系 {rid} 不存在"
    return row


def _request(store, pid) -> dict:
    row = next((r for r in store.rows("reprocess_requests") if r["reprocess_id"] == pid), None)
    assert row is not None, f"重抽取请求 {pid} 不存在"
    return row


def _lit(store, lid) -> dict:
    row = next((r for r in store.rows("literature") if r["lit_id"] == lid), None)
    assert row is not None, f"文献 {lid} 不存在"
    return row


def _row_bytes(row: dict) -> str:
    """一行在快照里的字节形态（与 `Store._dump` 同一套 json 参数）。

    "非目标关系逐字节不变"必须按这个口径比：只比两个 dict 相等会漏掉
    "键顺序被重排 / 值被重新序列化"这类看起来没事、实际改动了文件的情况。
    """
    return json.dumps(row, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- I6 夹具

AFFIRM = "In this construction the commutative law holds for every subgroup."
OPPOSITE = "Every subgroup fails the commutative law: operations are non-commutative here."
EXISTING_NEUTRAL = "The identity element is unique in every subgroup."
NEW_NEUTRAL = "Every subgroup contains the identity element of the ambient structure."


def _i6_store(store, *, existing_statement=AFFIRM, new_text=OPPOSITE) -> None:
    """一条旧关系（概念组 0000|0001）+ 一条待处理的新文献。"""
    write_library_file(store, "0001/b.txt", new_text)
    add_literature(store, "0000", title="旧文献", path="0000/a.txt", processed=True,
                   download={"status": "ok"})
    add_literature(store, "0001", title="新文献", path="0001/b.txt", processed=False,
                   download={"status": "ok"})
    write_library_file(store, "0000/a.txt", existing_statement)
    _concept(store, "0000", "group", definition="a set with a binary operation", related=["0001"])
    _concept(store, "0001", "abelian group", definition="a commutative group", related=["0000"])
    add_relation(store, "0000", ["0000", "0001"], "0000", quote=existing_statement,
                 description=existing_statement, quote_verified=True, group_key="0000|0001")
    sync_counters(store)


def _i6_agent(store, new_text) -> AgentB:
    return _agent_b(
        store,
        StubExtractor(
            [],
            [
                RelationDraft(
                    concept_names=["group", "abelian group"],
                    description=new_text,
                    quote=new_text,
                    page_range=PageRange(1, 1, "p. 1"),
                )
            ],
        ),
    )


def _conflict(draft_text: str, existing_text: str, *, draft_id="0001", other_id="0000") -> dict:
    """直接调 I6 闸门（不经过写入路径），入参刻意用真实表行的形状。

    表里的行只有 `concept_group_key`，没有 `concept_pair_key`：闸门必须自己
    由 `concept_ids` 现场推导。这里刻意不给派生态，正是为了让"又有人改成依赖
    调用方预先算好"立刻暴露。
    """
    draft = {
        "relation_id": draft_id,
        "concept_ids": ["0000", "0001"],
        "concept_group_key": "0000|0001",
        "statement": draft_text,
        "description": draft_text,
    }
    existing = [
        {
            "relation_id": other_id,
            "concept_ids": ["0000", "0001"],
            "concept_group_key": "0000|0001",
            "statement": existing_text,
            "description": existing_text,
        }
    ]
    return I.check_conflict(draft, existing_relations=existing)


# =========================================================================== I6


def test_i6_conflicting_relation_is_written_but_marked_suspect(store):
    """I6 正向：与已有关系表述对立的新关系 → 仍然写入，但标 suspect 并记下对方代号。"""
    _i6_store(store)
    res = _i6_agent(store, OPPOSITE).run_once()

    new = _relation(store, "0001")
    assert new["status"] == "suspect"
    assert new["conflicts_with"] == ["0000"], "必须指向与之矛盾的那条已有关系"
    cc = new["_conflict_check"]
    assert cc["checked"] is True and cc["conflict"] is True
    assert cc["strength"] == "strong", "只有明确对立才允许驱动 suspect"
    assert cc["reason"], "冲突必须给出可读的理由（否则无法复核）"
    # 关键：这条关系的引文是通过回验的，所以 suspect 只可能来自 I6 闸门，
    # 而不是"引文不可核实"那条更宽松的降级路径。
    assert new["quote_verified"] is True
    assert res.conflicts_detected == 1
    assert res.conflict_checks_run == 1
    assert res.conflict_checks_skipped == 0


def test_i6_non_conflicting_draft_keeps_normal_status(store):
    """I6 负控 1：不矛盾的草稿 → `conflict is False`，status 保持正常，且真的比过。"""
    _i6_store(store, existing_statement=EXISTING_NEUTRAL, new_text=NEW_NEUTRAL)
    res = _i6_agent(store, NEW_NEUTRAL).run_once()

    new = _relation(store, "0001")
    assert new["status"] == "active"
    assert new["quote_verified"] is True
    cc = new["_conflict_check"]
    assert cc["checked"] is True and cc["conflict"] is False
    assert cc["strength"] == "none"
    assert cc["compared"] >= 1, "必须真的与同概念组的已有关系比过，不能是空范围假通过"
    assert "conflicts_with" not in new
    assert res.conflicts_detected == 0
    assert res.conflict_checks_skipped == 0


def test_i6_unavailable_scope_leaves_visible_not_checked_evidence(store):
    """I6 负控 2：`existing_relations=None` → 行照写，但必须留下"没检查"的证据。

    这是本项目最痛的历史缺陷的守门用例：把"没接上工具"写成"查了、没有"。
    因此这里断言的不是"status 正常"，而是"行里有 checked=False + 计数器加一"。
    """
    _i6_store(store, existing_statement=EXISTING_NEUTRAL, new_text=NEW_NEUTRAL)
    b = _i6_agent(store, NEW_NEUTRAL)
    # 生产路径永远返回 tx.rows("relations")；这里显式模拟"本次没有能力检查"。
    b._conflict_scope = lambda tx: None
    res = b.run_once()

    new = _relation(store, "0001")
    cc = new["_conflict_check"]
    assert cc["checked"] is False
    assert cc["conflict"] is None, "没检查必须是 None，不能是 False"
    assert cc["strength"] is None
    assert "没检查" in cc["reason"]
    assert new["status"] == "active", "没检查不等于拒绝写入"
    assert "conflicts_with" not in new
    assert res.conflict_checks_skipped == 1
    assert res.conflict_checks_run == 0
    assert res.conflicts_detected == 0
    assert any(
        d.get("skipped") == "conflict_check_unavailable" for d in res.details
    ), "run 摘要里也要能看见'这次没检查'"


def test_i6_judge_is_store_free_by_signature():
    """I6 结构：闸门签名里没有 store/tx，且导入期自检不抛。

    这条约束不是风格问题：B 在自己的事务内调用它，若它去拿锁就是同进程
    `filelock` 重入（抛错或死锁）。所以把它固定成签名级断言。
    """
    sig = inspect.signature(I.check_conflict)
    assert not ({p.lower() for p in sig.parameters} & {"store", "tx", "st"})
    assert "existing_relations" in sig.parameters
    assert (
        sig.parameters["existing_relations"].default is inspect.Parameter.empty
    ), "必须显式传：省略它就等于允许'没检查'被默认成'不冲突'"
    # 导入期自检（`import agentflow.interactions` 时已跑过一次，这里再显式跑一次）
    I.assert_store_free()
    assert "check_conflict" in I.__all__


def test_i6_two_agents_write_concurrently_without_deadlock(store):
    """I6 并发：两个 B 实例（各自一个 Store，模拟两个智能体）并发写入，不超时不死锁。

    每个线程用自己的 `Store` 实例指向同一个 root：这才是"两个智能体"的真实形态
    （`Store` 的计数器缓存 `_dirty_counters` 是实例状态，不是为线程共享设计的；
    并发安全由 filelock + 固定加锁顺序保证，而不是靠共享一个对象）。
    """
    write_library_file(store, "0000/a.txt", "Group theory studies algebraic structures.")
    write_library_file(store, "0001/b.txt", "Ring theory studies additive structures.")
    add_literature(store, "0000", title="A", path="0000/a.txt", download={"status": "ok"})
    add_literature(store, "0001", title="B", path="0001/b.txt", download={"status": "ok"})
    _concept(store, "0000", "group", definition="d")
    _concept(store, "0001", "abelian group", definition="d")
    sync_counters(store)

    errors: list[str] = []
    results: list = []

    def work() -> None:
        try:
            b = _agent_b(Store(store.root), PageExtractor())
            results.append(b.run_once())
        except BaseException as e:  # noqa: BLE001 - 测试要把任何异常变成断言失败
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=work) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads), "并发写入未在 60s 内结束：疑似事务内重入锁（死锁）"
    assert errors == [], f"并发写入报错：{errors}"

    assert len(results) == 2
    assert all(r.processed == 1 for r in results)
    rows = store.rows("relations")
    assert len(rows) == 2, "两条文献各产出一条关系（丢失更新会让它变成 1）"
    assert all("_conflict_check" in r for r in rows), "每个实例都必须真的跑了闸门"
    assert sum(r.conflict_checks_run for r in results) == 2
    assert sum(r.conflicts_detected for r in results) == 0
    assert all(_lit(store, lid)["processed"] is True for lid in ("0000", "0001"))


def test_conflict_judge_known_false_positive_is_fixed_and_guarded():
    """负控（新增，重要）：一方压根没提那个术语 ⇒ 不冲突。

    旧实现把"提到肯定式"与"没提这个词"当成两种对立态度，于是
    "等号是公开问题" 与 "该结果取自配套书" 被报成矛盾 —— 中文里"是"无处不在，
    实测 24% 的关系被打成 suspect，那个标记随之失去意义。

    这里同时断"修复后的行为"（`conflict is False`）与"闸门确实看过"（`checked is True`
    且 `compared==1`）—— 否则"没报警"也可能只是因为它根本没跑。
    """
    cc = _conflict("该结果取自配套书", "等号是公开问题")
    assert cc["checked"] is True and cc["compared"] == 1
    assert cc["conflict"] is False
    assert cc["conflicts_with"] == []
    assert cc["strength"] == "none"


def test_i6_strong_opposite_assertions_drive_the_gate():
    """正向（表驱动）：明确对立才置 conflict=True，且 conflicts_with 指向对方。"""
    for existing, draft in (
        ("A 是 B", "A 不是 B"),
        (AFFIRM, OPPOSITE),
    ):
        cc = _conflict(draft, existing)
        assert cc["checked"] is True, (existing, draft, cc)
        assert cc["conflict"] is True, (existing, draft, cc)
        assert cc["conflicts_with"] == ["0000"], (existing, draft, cc)
        assert cc["strength"] == "strong"
        assert cc["reason"].strip(), "对立即必须给出可读理由"


def test_i6_weak_negation_marker_is_recorded_but_does_not_drive_status(store):
    """负控（新增）：裸否定标记只是线索，不构成矛盾判定。

    两个方向都要断：① 它被记录了（`weak_signals` 非空、`strength=="weak_only"`）；
    ② 它没有驱动状态变更（`conflict is False`、关系仍是 active）。
    只断其中一个都会漏掉"线索被丢弃"或"线索被当成结论"这两种相反的坏结果。
    """
    weak_a = "端点 0 不必用数值搜索"
    weak_b = "|S|=0 的见证是显式的"
    cc = _conflict(weak_b, weak_a)
    assert cc["checked"] is True
    assert cc["conflict"] is False
    assert cc["strength"] == "weak_only"
    assert cc["weak_signals"], "弱线索必须被记录下来（否则线索就丢了）"
    assert cc["conflicts_with"] == []
    assert "不构成矛盾判定" in cc["reason"]

    # 端到端：weak 线索不许把关系打成 suspect
    write_library_file(store, "0001/b.txt", weak_b)
    add_literature(store, "0000", title="旧文献", path="0000/a.txt", processed=True,
                   download={"status": "ok"})
    add_literature(store, "0001", title="新文献", path="0001/b.txt", processed=False,
                   download={"status": "ok"})
    write_library_file(store, "0000/a.txt", weak_a)
    _concept(store, "0000", "group", definition="d", related=["0001"])
    _concept(store, "0001", "abelian group", definition="d", related=["0000"])
    add_relation(store, "0000", ["0000", "0001"], "0000", quote=weak_a, description=weak_a,
                 quote_verified=True, group_key="0000|0001")
    sync_counters(store)

    res = _i6_agent(store, weak_b).run_once()

    new = _relation(store, "0001")
    assert new["status"] == "active", "weak 线索不许置 suspect"
    assert new["quote_verified"] is True
    stored = new["_conflict_check"]
    assert stored["strength"] == "weak_only", "strength 必须原样存进行里（可审计）"
    assert stored["weak_signals"]
    assert res.conflicts_detected == 0
    assert res.conflict_checks_run == 1


def test_i6_counters_are_visible_from_run(store):
    """计数器必须从 `run()`（编排层唯一入口）就看得见 —— 否则等于"接了线没通电"。"""
    _i6_store(store)
    out = _i6_agent(store, OPPOSITE).run()

    assert out["conflicts_detected"] == 1
    assert out["conflict_checks_run"] == 1
    assert out["conflict_checks_skipped"] == 0
    assert out["reprocess"]["handled"] == 0
    assert out["reprocess"]["skipped_reason"] == "no_pending_reprocess"


def test_conflict_evidence_survives_rebuild(store):
    """诊断字段必须能从 `events.jsonl` 重建出来，否则"可审计"只维持到下一次 rebuild。"""
    _i6_store(store)
    _i6_agent(store, OPPOSITE).run_once()
    store.rebuild(backup=False)

    new = _relation(store, "0001")
    assert new["status"] == "suspect"
    assert new["conflicts_with"] == ["0000"]
    assert new["_conflict_check"]["strength"] == "strong"


# =========================================================================== I4 夹具

GARBAGE_QUOTE = "This quotation appears nowhere in the paper at all."
SECOND_SENTENCE = "A ring is a set with two operations."
SECOND_QUOTE = "Rings differ from groups in their operations."


def _i4_store(store, *, statement=QUOTE, quote=GARBAGE_QUOTE) -> None:
    """目标关系 0000（引文不可核实）+ 非目标关系 0001（必须逐字节不变）。"""
    write_library_file(store, "0000/a.txt", f"{QUOTE} {SECOND_SENTENCE}")
    add_literature(store, "0000", title="A", path="0000/a.txt", processed=True,
                   download={"status": "ok"})
    add_literature(store, "0001", title="B", path=None, processed=True,
                   download={"status": "skipped"})
    _concept(store, "0000", "group", definition="d", related=["0001"])
    _concept(store, "0001", "abelian group", definition="d", related=["0000", "0002"])
    _concept(store, "0002", "ring", definition="d", related=["0001"])
    add_relation(store, "0000", ["0000", "0001"], "0000", quote=quote, description=statement,
                 quote_verified=False, page_range=(1, 1))
    add_relation(store, "0001", ["0001", "0002"], "0001", quote=SECOND_QUOTE,
                 description=SECOND_QUOTE, quote_verified=True, page_range=(1, 1))
    sync_counters(store)


# =========================================================================== I4


def test_reprocess_quote_touches_only_the_target_relation_and_keeps_processed(store):
    """I4 硬约束 ①+②：只改目标关系（其它逐字节不变）且绝不重置 `processed`。"""
    _i4_store(store)
    _reprocess(store, "p-0001", ["0000"])
    before_rows = {r["relation_id"]: _row_bytes(r) for r in store.rows("relations")}
    before_files = read_data_bytes(store)

    out = _agent_b(store, StubExtractor()).reprocess_once()

    assert out["handled"] is True and out["result"] == "found"
    after_rows = {r["relation_id"]: _row_bytes(r) for r in store.rows("relations")}
    assert set(after_rows) == set(before_rows)
    assert after_rows["0001"] == before_rows["0001"], "非目标关系必须逐字节不变"
    assert after_rows["0000"] != before_rows["0000"], "目标关系必须真的被改到了"

    # ② 绝不把 processed 置回 false（那会触发全量重抽）；不声明 literature 表 = 不可能改它
    after_files = read_data_bytes(store)
    assert _lit(store, "0000")["processed"] is True
    assert after_files["literature.json"] == before_files["literature.json"]
    assert after_files["concepts.json"] == before_files["concepts.json"]

    # ① 请求的终局结果 + "真正被改动的关系"
    req = _request(store, "p-0001")
    assert req["status"] == "done" and req["result"] == "found"
    assert req["touched_relation_ids"] == ["0000"]
    assert req["result_note"].strip()
    assert req["claimed_by"] is None and req["lease_until"] is None

    target = _relation(store, "0000")
    assert target["quote"] == QUOTE, "新引文必须是原文里找到的那一段（逐字）"
    assert target["quote_verified"] is True
    assert target["_quote_check"]["verified"] is True, "必须复用既有引文回验，而不是自己判"
    assert target["dedup_key"] == D.relation_dedup_key(target["concept_group_key"], QUOTE)


def test_reprocess_low_information_expands_the_statement(store):
    """I4 路径 2：`low_information` → 回到该页找包含当前陈述的更长片段。"""
    _i4_store(store)
    short = "abelian group is a group"
    with store.tx("relations", actor="test") as tx:
        row = tx.find("relations", relation_id="0000")
        row["description"] = short
        row["statement"] = short
        tx.upsert("relations", row, note="test:shorten")
    _reprocess(store, "p-0001", ["0000"], reason="low_information")

    out = _agent_b(store, StubExtractor()).reprocess_once()

    assert out["result"] == "improved"
    target = _relation(store, "0000")
    assert target["statement"] == QUOTE
    assert target["description"] == QUOTE
    assert target["quote"] == GARBAGE_QUOTE, "低信息量重抽取只改陈述，不该顺手换引文"
    assert _request(store, "p-0001")["touched_relation_ids"] == ["0000"]


def test_reprocess_need_context_only_records_the_passage(store):
    """I4 路径 3：`need_context` 是只读的 —— 片段只进 `result_note`，关系一个字节不动。"""
    _i4_store(store)
    _reprocess(store, "p-0001", ["0000"], reason="need_context")
    before_files = read_data_bytes(store)

    out = _agent_b(store, StubExtractor()).reprocess_once()

    assert out["result"] == "found"
    req = _request(store, "p-0001")
    assert req["status"] == "done" and req["result"] == "found"
    assert QUOTE in req["result_note"], "L3 溯源要的是原文片段本身（给人/给 D 核实）"
    assert req["touched_relation_ids"] == [], "只读路径不许记'改过'"
    assert read_data_bytes(store)["relations.json"] == before_files["relations.json"]


def test_reprocess_over_limit_is_rejected_and_changes_nothing(store):
    """I4 硬约束 ③：同一关系被受理超过 `max_reprocess_per_relation`(=2) 后拒绝。

    并且要断言"拒绝"与"做过"在配额上是分开的：`reprocess_counts` 不计 rejected。
    """
    _i4_store(store)
    _reprocess(store, "p-0001", ["0000"], status="done", result="not_found", note="第一次：没找到")
    _reprocess(store, "p-0002", ["0000"], status="done", result="unchanged", note="第二次：没变化")
    _reprocess(store, "p-0003", ["0000"])
    before_rows = {r["relation_id"]: _row_bytes(r) for r in store.rows("relations")}

    out = _agent_b(store, StubExtractor()).reprocess_once()

    assert out["handled"] is False
    assert [x["reprocess_id"] for x in out["rejected"]] == ["p-0003"]
    row = _request(store, "p-0003")
    assert row["status"] == "rejected", "超限是**拒绝**，不是 done"
    assert row["result"] == "rejected_target"
    assert "上限" in row["result_note"]
    assert {r["relation_id"]: _row_bytes(r) for r in store.rows("relations")} == before_rows
    assert I.reprocess_counts(store.rows("reprocess_requests")) == {"0000": 2}, (
        "被拒的不计入配额 —— 否则'我拒绝过'会被当成'我做过了'"
    )


def test_reprocess_without_a_found_passage_reports_not_found(store):
    """I4 三态：找不到等价表述 → `not_found` + 非空的 `result_note`（不假装 found）。"""
    _i4_store(store, statement="这一段陈述在文献里根本找不到对应的表述。")
    _reprocess(store, "p-0001", ["0000"])

    out = _agent_b(store, StubExtractor()).reprocess_once()

    assert out["handled"] is True and out["result"] == "not_found"
    req = _request(store, "p-0001")
    assert req["status"] == "done", "处理过了（结论是没有），这与'没处理'必须分得开"
    assert req["result"] == "not_found"
    assert req["result_note"].strip(), "必须写清找了多少、最高多少分"
    assert "相似度" in req["result_note"]
    assert req["touched_relation_ids"] == []
    assert _relation(store, "0000")["quote"] == GARBAGE_QUOTE, "没找到就不许改动引文"


def test_reprocess_without_local_file_says_why_it_could_not_redo(store):
    """I4 三态：环境缺料（没有下载到 PDF）→ 明确写出为什么没做到，而不是静默跳过。"""
    add_literature(store, "0000", title="没下到", path=None, processed=True,
                   download={"status": "failed"})
    _concept(store, "0000", "group", definition="d")
    _concept(store, "0001", "abelian group", definition="d")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote=GARBAGE_QUOTE,
                 description=QUOTE, quote_verified=False, page_range=(1, 1))
    sync_counters(store)
    _reprocess(store, "p-0001", ["0000"])

    out = _agent_b(store, StubExtractor()).reprocess_once()

    assert out["result"] == "not_found"
    note = _request(store, "p-0001")["result_note"]
    assert note.strip() and "没有本地文件" in note
    assert _relation(store, "0000")["quote"] == GARBAGE_QUOTE


def test_reprocess_rejects_missing_target_instead_of_guessing(store):
    """目标不存在（可能已被 I5 合并）→ 拒绝并说明，不做猜测性重抽。"""
    _i4_store(store)
    _reprocess(store, "p-0001", ["0009"])

    out = _agent_b(store, StubExtractor()).reprocess_once()

    assert out["handled"] is False
    row = _request(store, "p-0001")
    assert row["status"] == "rejected" and row["result"] == "rejected_target"
    assert "不存在" in row["result_note"]


def test_reprocess_rejects_structural_duplicate_reason_instead_of_merging(store):
    """`reason="structural_duplicate"` 无法用 relation_ids 判定同义 → 拒绝。

    合并必须有"C 的候选"（概念对 + 名字证据 + 邻域）作为输入；仅凭两条关系代号
    猜一个合并，就是绕过 I5 的"两路独立证据"规则。
    """
    _i4_store(store)
    _reprocess(store, "p-0001", ["0000"], reason="structural_duplicate")

    out = _agent_b(store, StubExtractor()).reprocess_once()

    assert out["handled"] is False
    row = _request(store, "p-0001")
    assert row["status"] == "rejected" and row["result"] == "rejected_target"
    assert "decide_structural_duplicate" in row["result_note"]


def test_empty_target_reprocess_request_is_forbidden_by_schema():
    """B 侧"目标非空"的复查是纵深防御：schema 已经让这种行根本写不进来。

    两条一起才有意义 —— schema 保证"正常的写入路径造不出无目标请求"，
    B 的复查保证"即使有人绕过校验直接塞一行，也不会退化成全量重抽"。
    """
    row = S.ReprocessRequest(reprocess_id="p-0001", timestamp=TS, reason="need_context")
    with pytest.raises(ValueError, match="relation_ids 不能为空"):
        row.validate()


def test_reprocess_results_vocabulary_covers_the_five_required_words():
    """结果词表必须包含这五个词：'做不到'与'做了没有'必须能分开。"""
    assert set(REPROCESS_RESULTS) == {
        "found",
        "not_found",
        "improved",
        "unchanged",
        "rejected_target",
    }


def test_run_drains_pending_reprocess_requests(store):
    """`run()` 必须真的会处理 pending 的重抽取请求（否则 I4 就是"接了线但没通电"）。"""
    _i4_store(store)
    _reprocess(store, "p-0001", ["0000"])

    out = _agent_b(store, StubExtractor()).run()

    assert out["reprocess"]["handled"] == 1
    assert out["reprocess"]["by_result"] == {"found": 1}
    assert out["reprocess"]["notes"][0]["touched_relation_ids"] == ["0000"]
    assert _request(store, "p-0001")["status"] == "done"


# =========================================================================== I5 夹具

DUP_QUOTE = "Every subgroup of an abelian group is abelian."
Q_SUB = "Every subgroup of a group is closed under the operation."
Q_HOMO = "Homomorphisms preserve the identity element by definition."


def _i5_store(store) -> None:
    """4 个概念 / 4 条关系：

    - `0000` "Abelian Group" 与 `0001` "abelian group"：邻域相同且规范化名字相同
      ⇒ 真同义（C 应提 merge，B 应合并）；
    - `0002` "subgroup" 与 `0003` "homomorphism"：邻域相同但显然不同
      ⇒ 只有结构证据（C 只能提 review，B 必须拒绝）；
    - 改写后 `0000|0002` 会出现两条同组同引文的关系 ⇒ 必须走既有判重逻辑。
    """
    write_library_file(store, "0000/src.txt", DUP_QUOTE)
    add_literature(store, "0000", title="A", path="0000/src.txt", processed=True,
                   download={"status": "ok"})
    _concept(store, "0002", "subgroup", definition="闭包于运算的子集", related=["0000", "0001"])
    _concept(store, "0003", "homomorphism", definition="保持运算的映射", related=["0000", "0001"])
    _concept(store, "0000", "Abelian Group",
             definition="一个满足交换律的群，其二元运算对任意两个元素都可交换。",
             related=["0002", "0003"])
    _concept(store, "0001", "abelian group", definition="满足交换律的群。",
             aliases=["交换群"], related=["0002", "0003"])
    add_relation(store, "0000", ["0000", "0002"], "0000", quote=DUP_QUOTE,
                 description=DUP_QUOTE, group_key="0000|0002")
    add_relation(store, "0001", ["0001", "0002"], "0000", quote=DUP_QUOTE,
                 description=DUP_QUOTE, group_key="0001|0002")
    add_relation(store, "0002", ["0000", "0003"], "0000", quote=Q_SUB,
                 description=Q_SUB, group_key="0000|0003")
    add_relation(store, "0003", ["0001", "0003"], "0000", quote=Q_HOMO,
                 description=Q_HOMO, group_key="0001|0003")
    sync_counters(store)


def _i5_candidate(store, ids) -> dict:
    cands = I.structural_duplicate_pairs(store.rows("concepts"), store.rows("relations"))
    cand = next((c for c in cands if c.get("concept_ids") == list(ids)), None)
    assert cand is not None, f"C 应当提出候选 {ids}，实际只提出 {[c.get('concept_ids') for c in cands]}"
    return cand


# =========================================================================== I5


def test_i5_synonymous_pair_is_merged_with_reason_and_rewritten_relations(store):
    """I5 正向：同义对 → C 提出、B 合并；墓碑有理由，边被改写，重复关系走既有判重。"""
    _i5_store(store)
    cand = _i5_candidate(store, ["0000", "0001"])
    assert cand["proposal"] == "merge"
    assert cand["name_evidence"] == "same_normalized_name"

    out = _agent_b(store, StubExtractor()).resolve_structural_duplicate(cand)

    assert out["verdict"] == "merge" and out["applied"] is True
    assert out["survivor_id"] == "0000" and out["merged_id"] == "0001"

    concepts = {c["concept_id"]: c for c in store.rows("concepts")}
    tomb = concepts["0001"]
    assert tomb["merged_into"] == "0000"
    assert tomb["merge_reason"].strip(), "合并必须留下理由（可被人反驳的理由）"
    assert "结构等价" in tomb["merge_reason"] and "名字侧证据" in tomb["merge_reason"]
    assert tomb["merged_at"]
    assert tomb["related_concepts"] == [], "被吸收的节点的边已经全部改写到 survivor 上"

    survivor = concepts["0000"]
    assert "交换群" in survivor["aliases"], "被合并方的别名要并入 survivor"

    rels = {r["relation_id"]: r for r in store.rows("relations")}
    assert all("0001" not in r["concept_ids"] for r in rels.values()), "不该再有边指向墓碑"
    for r in rels.values():
        assert r["concept_group_key"] == T.concept_group_key(r["concept_ids"]), (
            "改写后 concept_group_key 必须重算（否则判重会静默失效）"
        )
    # 改写后 0001 与 0000 变成同一概念组、同一引文 ⇒ 由既有判重逻辑处理
    dup = rels["0001"]
    assert dup["concept_group_key"] == "0000|0002"
    assert dup["status"] == "rejected" and dup["duplicate_of"] == "0000"
    assert "判重" in dup["_merge_note"]
    assert rels["0000"]["status"] == "active"
    assert set(rels["0000"]["concept_ids"]) == {"0000", "0002"}
    assert set(rels["0002"]["concept_ids"]) == {"0000", "0003"}
    assert set(rels["0003"]["concept_ids"]) == {"0000", "0003"}
    # 前缀：合并后的数据仍要能通过全局不变量校验
    assert verify_all(store).errors == []


def test_i5_rejects_structural_equivalence_without_name_evidence(store):
    """I5 负控（重要）：邻域相同但显然不同的概念 → 拒绝，且理由说清"结构等价 ≠ 同义"。"""
    _i5_store(store)
    cand = _i5_candidate(store, ["0002", "0003"])
    assert cand["proposal"] == "review", "C 只有结构证据时不得给 merge 建议"
    assert cand["name_evidence"] == "none"
    before = read_data_bytes(store)

    out = _agent_b(store, StubExtractor()).resolve_structural_duplicate(cand)

    assert out["verdict"] == "reject"
    assert out["survivor_id"] is None and out["merged_id"] is None
    assert "结构等价" in out["reason"] and "同义" in out["reason"]
    assert out["reason"].strip(), "否决同样必须给理由（可被人反驳）"
    assert read_data_bytes(store) == before, "否决分支不许落盘任何数据"
    assert all(c.get("merged_into") is None for c in store.rows("concepts"))


def test_i5_rejects_when_the_pair_is_already_related(store):
    """B 自己复算结构证据：两者之间已有直接关系 ⇒ 它们已被声明为不同 ⇒ 不得合并。

    （C 的检测器不会给出这种候选，但"候选是别人给的"这件事本身要求 B 复核。）
    """
    _i5_store(store)
    add_relation(store, "0004", ["0000", "0001"], "0000", quote="a ≅ b",
                 description="a ≅ b", group_key="0000|0001")
    cand = {
        "concept_ids": ["0000", "0001"],
        "name_evidence": "same_normalized_name",
        "proposal": "merge",
        "neighbors": ["0002", "0003"],
    }

    out = _agent_b(store, StubExtractor()).decide_structural_duplicate(cand)

    assert out["verdict"] == "reject"
    assert "直接关系" in out["reason"]


def test_i5_rejects_when_the_name_check_is_ambiguous(store):
    """名字侧复核必须"恰好查回对方"：查回第三个概念 ⇒ 有歧义 ⇒ 拒绝。

    （表的物理顺序决定 `find_concept` 先命中谁；这里刻意让歧义暴露成一次拒绝，
    而不是让合并悄悄发生。）
    """
    _concept(store, "0002", "Abelian Group", definition="第三个同义节点")
    _concept(store, "0000", "abelian group", definition="定义甲")
    _concept(store, "0001", "abelian-group", definition="定义乙")
    cand = {
        "concept_ids": ["0000", "0001"],
        "name_evidence": "same_normalized_name",
        "proposal": "merge",
        "neighbors": [],
    }

    out = _agent_b(store, StubExtractor()).decide_structural_duplicate(cand)

    assert out["verdict"] == "reject"
    assert "独立复核未通过" in out["reason"]
    assert "0002" in out["reason"], "理由里要指出它实际解析到了谁（可被人核实/反驳）"


def test_find_concept_does_not_match_merged_nodes(store):
    """I5：`find_concept` 必须跳过墓碑，否则新知识会挂到一个永远不再被读到的节点上。"""
    rows = [
        {
            "concept_id": "0000",
            "name": "群",
            "normalized_name": "群",
            "aliases": [],
            "merged_into": "0001",
            "merge_reason": "测试用墓碑",
        },
        {"concept_id": "0001", "name": "group", "normalized_name": "group", "aliases": []},
    ]
    assert D.find_concept(rows, "群") is None, "墓碑不得再被匹配到"
    assert D.find_concept(rows, "group")["concept_id"] == "0001"
    # 反向保护：去掉墓碑不该影响活节点的正常匹配（避免"修过头"）
    assert D.find_concept([rows[1]], "group")["concept_id"] == "0001"


def test_i5_merged_name_resolves_to_the_survivor_end_to_end(store):
    """合并后，被吸收的名字必须解析到 survivor（否则下一个同名概念又会新建一个节点）。"""
    _i5_store(store)
    cand = _i5_candidate(store, ["0000", "0001"])
    _agent_b(store, StubExtractor()).resolve_structural_duplicate(cand)

    rows = store.rows("concepts")
    assert D.find_concept(rows, "abelian group")["concept_id"] == "0000"
    assert D.find_concept(rows, "交换群")["concept_id"] == "0000", "被合并方的别名也要落到 survivor"


def test_i5_merge_decision_is_deterministic(store):
    """survivor 规则必须确定性：定义更长者存活，同长取 concept_id 较小者。"""
    _i5_store(store)
    cand = _i5_candidate(store, ["0000", "0001"])
    b = _agent_b(store, StubExtractor())
    first = b.decide_structural_duplicate(cand)
    second = b.decide_structural_duplicate(cand)
    assert first["survivor_id"] == second["survivor_id"] == "0000"
    assert first["merged_id"] == second["merged_id"] == "0001"

    # 同长时退化为 ID 较小者：把两边的定义改成一样长再判一次
    with store.tx("concepts", actor="test") as tx:
        for cid in ("0000", "0001"):
            row = tx.find("concepts", concept_id=cid)
            row["definition"] = "同样长的定义文本"
            tx.upsert("concepts", row, note="test:same_len")
    third = b.decide_structural_duplicate(cand)
    assert third["survivor_id"] == "0000", "同长时必须退化为 concept_id 较小者"


def test_i5_merge_evidence_survives_rebuild(store):
    """合并决定（墓碑 + 理由 + 关系改写清单）必须能从事件日志重建 —— 可审计性的一部分。"""
    _i5_store(store)
    cand = _i5_candidate(store, ["0000", "0001"])
    _agent_b(store, StubExtractor()).resolve_structural_duplicate(cand)
    store.rebuild(backup=False)

    tomb = {c["concept_id"]: c for c in store.rows("concepts")}["0001"]
    assert tomb["merged_into"] == "0000"
    assert tomb["merge_reason"].strip()
    assert tomb["_merge"]["rejected_relation_ids"] == ["0001"]
