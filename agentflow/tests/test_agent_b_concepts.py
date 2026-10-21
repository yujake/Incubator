# -*- coding: utf-8 -*-
"""B 的概念行：`proof_text` / `origin` / 每轮配额 —— 本批缺陷一的六条判据（含三处负控）。

## 真机读数（`projects/mp3/data/statements.json`，2026-10-21 现算）

statements 1147 行：kind 分布 concept 1143 / theorem 2 / lemma 2；origin 分布 own_result 1145、external_lit 2；每一条
concept 都带 proof_text，值是 "concept:primitive"；其中 1142 条带 source_lit_id（术语确实出自文献）。

三处错（业主 2026-10-21 的验收词，逐条对应下面的判据）：

1. 概念行带 `proof_text` ⇒ 任何"有没有证明"的读数都被虚高（`proof_review_gap` 的 `proof_text` 非空判据、收工门的 reviewed 档、`closing`
的 `prose_reviewed_statements`）；
2. `origin=own_result` 错标：文献里来的术语是 `external_lit`，不是自己的结果；
3. 一轮灌进上千条：概念应按轮限量（一轮几十条以内）。

## 判据（每条都配一处负控；负控不红 = 这条判据没在咬）

① 写一条概念 ⇒ 落盘 `proof_text` 为空，且 `proof_review_gap` 不把它算成"有证明"；负控：给它塞 `concept:primitive` ⇒ 判据红，且 `why`
点名"概念行不该带证明文本"。
② 写概念时 `origin` 在受控集合里；`own_result` ⇒ 拒；负控：把闸门放开（`return ""`）⇒ 判据红。
③ 一轮写超过上限 ⇒ 第 N+1 条受控拒绝、读数可见、已写的保留；负控：让配额不拦也不记（"静默丢"）⇒ 判据红。"""
from __future__ import annotations

import pytest

from agentflow import conceptrows as CR
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.extract import DocumentText, extract_text
from agentflow.llm import ConceptDraft
from agentflow.store import Store

from conftest import add_literature, write_library_file

QUOTE = "An abelian group is a group in which the commutative law holds."


# ---------------------------------------------------------------- 替身与夹具


class _StubExtractor:
    """确定性抽取器替身：交回预设的概念草稿（不调模型、不读 PDF）。"""

    def __init__(self, concepts=()):
        self._concepts = list(concepts)
        self.calls = 0

    def extract(self, doc, lit_id, meta):
        self.calls += 1
        return list(self._concepts), []


def _agent_b(store: Store, extractor) -> AgentB:
    return AgentB(store, extractor=extractor, extract_text=extract_text,
                  config={"lease_seconds": 900, "max_attempts": 3})


def _one_paper(store: Store, lit_id: str = "0000") -> None:
    write_library_file(store, f"{lit_id}/a.txt", QUOTE)
    add_literature(store, lit_id, title="A", path=f"{lit_id}/a.txt")


def _concept_rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("statements") if str(r.get("kind") or "") == "concept"]


def _write_one_concept(store: Store, *, definition: str = "边上权重的倒数",
                       source_lit_id: str = "0000", label: str = "电导") -> dict:
    """走生产的写入侧（秘书那一笔）写一条概念，返回落盘的那一行。"""
    _one_paper(store)
    from agentflow.secretary import Secretary

    sec = Secretary("B", root=store.root, store=store)
    got = sec.record_statement(
        {"statement_full": "定理：对任意群 G，命题 ph 成立。", "kind": "theorem",
         "source_lit_id": source_lit_id, "page_range": {"start": 1, "end": 1},
         "quote_verified": True, "quote_mode": "verbatim",
         "concepts": [{"name": label, "definition": definition,
                       "source_lit_id": source_lit_id}]},
        role="B")
    assert got.get("created"), got
    rows = [r for r in _concept_rows(store) if str(r.get("label") or "") == label]
    assert len(rows) == 1, rows
    return rows[0]


# ================================================================ ① proof_text


def _assert_concept_has_no_proof_text(row: dict) -> None:
    """① 的尺子：落盘那一格为空，而且 `proof_review_gap` 不把它算成"有证明"。

        两半都要判：只判"落盘为空"时，读侧仍可能把历史行（或别处塞进来的那一格）
        当成"有证明"；只判读侧时，写入侧可以继续往库里灌哨兵。"""
    assert str(row.get("proof_text") or "") == "", (
        f"概念行的 proof_text 必须是空的（它是“这段证明被审过”的比对对象，"
        f"概念不参与等级链）：实得 {row.get('proof_text')!r}")
    gap = VR.proof_review_gap(".", row)
    assert gap["ok"] is False, (
        f"`proof_review_gap` 把一条概念行算成了“有证明”：{gap}")
    assert gap["checked"] is True, f"判都没判（checked=False 不是“没问题”）：{gap}"
    assert "概念" in gap["why"], f"why 里没点明这是概念行：{gap['why']}"


def test_a_concept_row_lands_without_proof_text_and_is_not_counted_as_proof(store):
    """① 正控：写一条 concept ⇒ 落盘 `proof_text` 为空，且 `proof_review_gap` 不算它有证明。"""
    row = _write_one_concept(store)
    _assert_concept_has_no_proof_text(row)
    assert str(row.get("origin") or "") == "external_lit", (
        f"带文献出处的概念行 origin 必须是 external_lit：{row.get('origin')!r}")


def test_negative_control_a_concept_row_with_the_old_sentinel_turns_the_criterion_red(store):
    """① 负控：给这条概念行塞 `concept:primitive` ⇒ 判据必须红，且点名"概念行不该带证明文本"。

        这一格是存量行的形态（mp3 那 1143 条就是这个样子）：判据要能在数据面上
        认出它，而不是"反正写入侧不写了，读侧就看不见了"。"""
    row = dict(_write_one_concept(store))
    row["proof_text"] = "concept:primitive"
    gap = VR.proof_review_gap(".", row)
    assert gap["ok"] is False, gap
    assert "概念行不该带证明文本" in gap["why"], gap["why"]
    with pytest.raises(AssertionError):
        _assert_concept_has_no_proof_text(row)


def test_the_writer_refuses_to_write_proof_text_on_a_concept():
    """① 的第二半（写入侧闸）：`concept_statement` 收到 `proof_text` ⇒ 当场拒绝。

    静默丢掉是另一种坏：调用方会以为"概念也能带证明"，下一次还这么交。
    """
    with pytest.raises(ValueError) as exc:
        CR.concept_statement(stmt_id="000001", label="电导", definition="d",
                             source_lit_id="0000", proof_text="concept:primitive")
    assert "概念行不该带证明文本" in str(exc.value), str(exc.value)


def test_the_register_statement_action_drops_a_concept_proof_text_but_says_so(store):
    """① 的动作面：`B.register_statement` 交一条带 `proof_text` 的概念 ⇒ 不写那一格，但留痕。"""
    _one_paper(store)
    b = AgentB(store, extractor=None, extract_text=None,
               config={"lease_seconds": 900, "max_attempts": 3})
    out = b.register_statement(
        origin="external_lit", kind="concept", label="生僻概念 Y",
        statement_full="", source_lit_id="0000", page_range={"start": 3, "end": 4},
        proof_text="concept:primitive", quote_reason="定义还没从原文里抽到 ⇒ 待补")
    assert out["ok"] is True, out
    assert out["proof_text_dropped"] == "concept:primitive", out
    rows = [r for r in _concept_rows(store) if r["stmt_id"] == out["stmt_id"]]
    assert rows and rows[0]["proof_text"] == "", rows


# ================================================================ ② origin


def _assert_writer_refuses_own_result(*, source_lit_id: str = "0000") -> None:
    """② 的尺子：带文献出处的概念写成 `own_result` ⇒ 必须被拒（`ValueError`）。

    刻意不用 `pytest.raises`：负控要的是"这条尺子抛 `AssertionError`"，
    而 `pytest.raises` 失败时抛的是 `Failed`（不是 `AssertionError`）——
    那样负控里的 `pytest.raises(AssertionError)` 永远捕不到东西。
    """
    try:
        CR.concept_statement(stmt_id="000002", label="noetherian", definition="d",
                             source_lit_id=source_lit_id, origin="own_result")
    except ValueError as exc:
        text = str(exc)
        assert "origin" in text and "own_result" in text, text
        return
    raise AssertionError(
        "带文献出处（source_lit_id=%r）的概念被允许写成 origin='own_result' —— "
        "那正是 mp3 那 1142 条错标的形态（文献里来的术语被读成我们自己的结果）"
        % (source_lit_id,))


def test_a_concept_cannot_be_our_own_result_when_it_has_a_literature_source():
    """② 正控：`origin=own_result` + `source_lit_id` ⇒ 拒（真机：1142/1143 条就是这么错的）。"""
    _assert_writer_refuses_own_result()


def test_negative_control_an_open_origin_gate_turns_the_criterion_red(
        monkeypatch: pytest.MonkeyPatch):
    """② 负控：把 origin 那道闸放开（恒返回空串）⇒ 同一把尺子必须红。

    没有这一条，"② 能红"这句话本身没人检验过 —— 一条永远绿的判据与"这条口径真的
    在判"在读数上长得一样。
    """
    monkeypatch.setattr(CR, "concept_origin_problem", lambda **_: "")
    with pytest.raises(AssertionError):
        _assert_writer_refuses_own_result()
    # 反真空：放开之后那条写真的会落成 own_result（判据红得有理由）
    row = CR.concept_statement(stmt_id="000003", label="noetherian", definition="d",
                               source_lit_id="0000", origin="own_result")
    assert row.origin == "own_result" and row.source_lit_id == "0000"


def test_a_self_authored_concept_is_allowed_only_when_declared():
    """② 的受控集合：自己定义的新概念可以 `own_result`，但必须显式声明。"""
    with pytest.raises(ValueError):
        CR.concept_statement(stmt_id="000004", label="我自己造的概念", definition="d",
                             origin="own_result")
    row = CR.concept_statement(stmt_id="000005", label="我自己造的概念", definition="d",
                               origin="own_result", self_authored=True)
    assert row.origin == "own_result" and row.proof_text == ""
    # 没有出处、也没声明 ⇒ 按"定义就在这一行上"推断成自己造的（待补档也不许凭空拒绝）
    inferred = CR.concept_statement(stmt_id="000006", label="基本概念", definition="")
    assert inferred.origin == "own_result" and inferred.status == "pending_definition"


def test_the_digest_path_labels_literature_concepts_as_external_lit(store):
    """② 的现实通道：B 消化文献时建的概念，`origin` 必须是 `external_lit`。

    mp3 的 1143 条概念全从这条通道来（`created_by=agent-B`），而它们全是 own_result。
    """
    _one_paper(store)
    b = _agent_b(store, _StubExtractor(
        concepts=[ConceptDraft(name="群", definition="d", aliases=[], source_lit_id="0000")]))
    res = b.run_once()
    assert res.concepts_created == 1, res.to_dict()
    (row,) = _concept_rows(store)
    assert row["origin"] == "external_lit", row
    assert row["source_lit_id"] == "0000", row
    assert row["proof_text"] == "", row


# ================================================================ ③ 每轮配额


def _assert_quota_bites(store: Store, out: dict, *, limit: int, wanted: int) -> None:
    """③ 的尺子：写到上限就停，第 N+1 条受控拒绝且读数可见，已写的保留。

        三件事缺一不可：
        ① 写下来的正好是 `limit` 条（不是"全写"也不是"全不写"）；
        ② 拒绝有读数（`concepts_refused` 非零 + `concept_quota.why` 写明上限与去处）；
        ③ 被拒的名字在 `details` 里点名（"静默丢"那一档就是没有这一格）。"""
    written = len(_concept_rows(store))
    assert written == limit, (
        f"配额 {limit} 但落了 {written} 条概念（写了 {wanted} 条）—— "
        "超额的不许静默落盘，也不许把已写的回滚")
    refused = int(out.get("concepts_refused") or 0)
    assert refused == wanted - limit, (
        f"被拒条数应当是 {wanted - limit}（{wanted} 条 - 上限 {limit}），实得 {refused}")
    quota = dict(out.get("concept_quota") or {})
    assert quota.get("limit") == limit and quota.get("refused_count") == refused, quota
    why = str(quota.get("why") or "")
    assert f"上限 {limit}" in why, f"读数里没写上限：{why!r}"
    assert "下一轮" in why and "报告" in why, f"读数里没说剩下的去哪儿：{why!r}"
    named = [d for d in (out.get("details") or []) if d.get("stage") == "concept_quota"]
    assert len(named) == refused, (
        f"`details` 里没有逐条点名被拒的概念（静默丢的形态）：{out.get('details')}")
    assert all(d.get("refused") for d in named), named


def test_a_round_over_the_concept_cap_is_controlled_and_the_written_ones_stay(store):
    """③ 正控：一轮交 `上限+5` 条概念 ⇒ 前 `上限` 条落盘、其余受控拒绝、读数可见。"""
    wanted = CR.CONCEPTS_PER_ROUND_MAX + 5
    _one_paper(store)
    b = _agent_b(store, _StubExtractor(concepts=[
        ConceptDraft(name=f"概念{i:03d}", definition=f"定义 {i}", aliases=[],
                     source_lit_id="0000") for i in range(wanted)]))
    out = b.run()
    _assert_quota_bites(store, out, limit=CR.CONCEPTS_PER_ROUND_MAX, wanted=wanted)


def test_negative_control_a_quota_that_does_not_refuse_turns_the_criterion_red(
        store, monkeypatch: pytest.MonkeyPatch):
    """③ 负控：让配额"不拦也不记"（静默丢 / 根本不受限）⇒ 同一把尺子必须红。

    这一格正是缺陷一第三处（一轮 1143 条）的形态：没有拒绝、没有读数，
    而"这一轮写了多少"看起来完全正常。
    """
    def _always_true(self, name: str = "") -> bool:  # noqa: ANN001
        self.written += 1
        return True

    monkeypatch.setattr(CR.ConceptQuota, "admit", _always_true)
    wanted = CR.CONCEPTS_PER_ROUND_MAX + 3
    _one_paper(store)
    b = _agent_b(store, _StubExtractor(concepts=[
        ConceptDraft(name=f"概念{i:03d}", definition="d", aliases=[],
                     source_lit_id="0000") for i in range(wanted)]))
    out = b.run()
    with pytest.raises(AssertionError):
        _assert_quota_bites(store, out, limit=CR.CONCEPTS_PER_ROUND_MAX, wanted=wanted)


def test_the_quota_is_per_round_not_per_paper(store):
    """③ 的口径：配额跨篇累加（按篇限量挡不住"篇数多"那种水漫）。

    两篇文献各交 20 条概念（合计 40 > 30）⇒ 第一轮总量仍然是 30；
    如果配额是"每篇 30"，这里会落 40 条 —— 判据当场红。
    """
    for lit in ("0000", "0001"):
        write_library_file(store, f"{lit}/a.txt", QUOTE)
        add_literature(store, lit, title=lit, path=f"{lit}/a.txt")
    drafts = [ConceptDraft(name=f"P{lit}-{i:02d}", definition="d", aliases=[],
                           source_lit_id=lit) for lit in ("0000", "0001") for i in range(20)]

    class _PerPaper(_StubExtractor):
        """每篇只交自己那 20 条（模拟抽取器按文献给草稿）。"""

        def extract(self, doc, lit_id, meta):
            self.calls += 1
            return [d for d in drafts if d.source_lit_id == lit_id], []

    b = _agent_b(store, _PerPaper())
    out = b.run()
    assert len(_concept_rows(store)) == CR.CONCEPTS_PER_ROUND_MAX, (
        f"配额是按轮的：两篇各 20 条也只许落 {CR.CONCEPTS_PER_ROUND_MAX} 条，"
        f"实得 {len(_concept_rows(store))}")
    assert int(out.get("concepts_refused") or 0) == 10, out
