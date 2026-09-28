"""T1 猜想数据面的判据：10 处触点各一条，加上 `validate()` 的每条拒收条件各一条负控。

依据 `draft/30` §T1 与 `draft/29` §7.5 的状态机。这一组要证明三件事：

1. 猜想能当数据用：`table.*` 工具（既有的 8 个通用表操作）直接读写 `conjectures`，
   不需要任何新工具、新动作或新契约（这是 Shape C 之所以便宜的原因）；
2. `validate()` 把状态机写成拒收条件：每条状态"必须带什么"各有一条负控真的走进去；
3. `verify_all` 管跨对象那半边：引用的实验/文献/升格落点不存在时逐条报 error。

触点数的勘误（2026-09-29）：`draft/30` §T1 原写 7 处，实现时实测定为 10 处
（多出 `row_from_dict` 的逐表名分支、`ARRAY_FIELD_KINDS`、`tests/conftest.DATA_FILES`），
理由与逐条证据在那份文件的"实现后更正"一节。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow import verify as V
from agentflow.store import Store
from agentflow.tools import build_registry

GOOD = {
    "conjecture_id": "0000",
    "statement": "对一切 m，谱落在区间 [-m, m] 内。",
    "form": "universal",
    "testable": {"params": {"m": [2, 3, 4]}, "why": "逐 m 数值可判"},
    "origin": "report:0001",
    "status": "proposed",
}


def _store(tmp_path: Path) -> Store:
    """初始化过的临时工作区。"""
    st = Store(tmp_path)
    st.init()
    return st


def _make(**patch) -> S.Conjecture:
    """一条合法猜想（用关键字覆盖单字段来做负控）。"""
    return S.Conjecture(**{**GOOD, **patch})


# ---------------------------------------------------------------- 触点 1-4：schema

def test_touchpoints_one_to_four_are_in_the_schema():
    """触点 1-4：行结构 + TABLES 条目 + 两条词表 + ID 计数器。"""
    assert "conjectures" in S.TABLES
    spec = S.TABLES["conjectures"]
    assert spec["row"] is S.Conjecture and spec["id_field"] == "conjecture_id"
    assert spec["id_kind"] == "conjecture"
    assert S.ID_COUNTERS["conjecture"] == "conjecture_id"
    assert S.CONJECTURE_STATUSES and S.CONJECTURE_FORMS
    assert S.CONJECTURE_STATUSES != S.QUESTION_STATUSES, "猜想不与问题共用状态词表"


def test_touchpoint_five_lock_order_puts_conjectures_near_research_questions():
    """触点 5：加锁顺序里紧跟研究问题（同一层产生）。"""
    import agentflow.store as ST

    assert "conjectures" in ST.LOCK_ORDER
    assert ST.LOCK_ORDER.index("conjectures") == ST.LOCK_ORDER.index("research_questions") + 1
    assert ST.LOCK_ORDER[-1] == "counters", "counters 必须仍是最后一把锁"


def test_touchpoint_six_vocabulary_map_is_registered():
    """触点 6：`_VOCAB_BY_FIELD` 登记了状态与形态（漏登记 = 该字段静默不校验）。"""
    from agentflow.tools import table_tools as TT

    assert TT._VOCAB_BY_FIELD[("conjectures", "status")] == "CONJECTURE_STATUSES"
    assert TT._VOCAB_BY_FIELD[("conjectures", "form")] == "CONJECTURE_FORMS"


def test_conjectures_are_usable_through_the_existing_table_tools(tmp_path: Path):
    """猜想能当数据用：既有的 `table.*` 直接读写，不需要新工具/新动作/新契约。"""
    st = _store(tmp_path)
    reg = build_registry(store=st).registry
    created = reg.call("table.create", role="D", table="conjectures", row=dict(GOOD))
    assert created.ok, created.error
    got = reg.call("table.get", role="D", table="conjectures", id="0000")
    assert got.ok and got.data["statement"] == GOOD["statement"]
    patched = reg.call("table.update", role="D", table="conjectures", id="0000",
                       patch={"status": "withdrawn", "withdraw_reason": "与已知结果重复"})
    assert patched.ok, patched.error
    listed = reg.call("table.list", role="C", table="conjectures")
    assert listed.ok and listed.data["total"] == 1, "只读角色也应当看得到猜想"


def test_table_update_uses_the_registered_vocabulary(tmp_path: Path):
    """词表映射真的生效：写一个不在词表里的状态必须被拒。"""
    st = _store(tmp_path)
    reg = build_registry(store=st).registry
    reg.call("table.create", role="D", table="conjectures", row=dict(GOOD))
    bad = reg.call("table.update", role="D", table="conjectures", id="0000",
                   patch={"status": "answered"})
    assert bad.ok is False, "`answered` 不在猜想的词表里（那是问题的状态）"
    assert "CONJECTURE_STATUSES" in str(bad.error) or "status" in str(bad.error)


# ---------------------------------------------------------------- validate：九条负控

def test_positive_conjecture_validates():
    """正控：合法猜想过 `validate`（否则下面的负控证明不了什么）。"""
    _make().validate()


def test_negative_empty_statement():
    """负控 1：陈述句为空。"""
    with pytest.raises(ValueError, match="statement 不能为空"):
        _make(statement="  ").validate()


def test_negative_question_is_not_a_conjecture():
    """负控 2：含疑问词 ⇒ 它是问题而不是猜想。"""
    with pytest.raises(ValueError, match="疑问词"):
        _make(statement="是否存在反例？").validate()


def test_negative_origin_required():
    """负控 3：来源必填（防"凭空出现的猜想"）。"""
    with pytest.raises(ValueError, match="origin 必填"):
        _make(origin="").validate()


def test_negative_proposed_needs_testable_form():
    """负控 4：提出态必须给可检验形式；给不出就落 needs_evidence。"""
    with pytest.raises(ValueError, match="testable"):
        _make(testable={}).validate()


def test_negative_needs_evidence_needs_a_reason():
    """负控 5：`needs_evidence` 必须写清为什么提不出可检验形式。"""
    with pytest.raises(ValueError, match="needs_evidence"):
        _make(status="needs_evidence", testable={}).validate()
    _make(status="needs_evidence", testable={}, notes="只找到非构造性表述").validate()


def test_negative_supported_requires_experiments():
    """负控 6：`supported_not_proved` 必须记检验过它的实验。"""
    with pytest.raises(ValueError, match="supported_not_proved"):
        _make(status="supported_not_proved").validate()


def test_negative_refuted_requires_a_counterexample_experiment():
    """负控 7：`refuted` 必须给反例实验（`inconclusive` 不得转 `refuted`）。"""
    with pytest.raises(ValueError, match="counterexample_experiment_id"):
        _make(status="refuted").validate()


def test_negative_proved_requires_a_proof_experiment():
    """负控 8：`proved` 必须给证明实验。"""
    with pytest.raises(ValueError, match="proof_experiment_id"):
        _make(status="proved").validate()


def test_negative_promoted_requires_evidence_and_a_target():
    """负控 9：升格必须同时有证明实验与落点。"""
    with pytest.raises(ValueError, match="promoted"):
        _make(status="promoted", proof_experiment_id="0000").validate()
    with pytest.raises(ValueError, match="promoted"):
        _make(status="promoted", promoted_to={"kind": "document_claim", "id": "0000"}).validate()


def test_negative_known_in_literature_requires_a_lit_id():
    """负控 10：`known_in_literature` 必须给文献（别人证过 ≠ 我们证过）。"""
    with pytest.raises(ValueError, match="known_lit_id"):
        _make(status="known_in_literature").validate()


def test_negative_withdrawn_requires_a_reason():
    """负控 11：撤下必须写理由（不许静默消失）。"""
    with pytest.raises(ValueError, match="withdraw_reason"):
        _make(status="withdrawn").validate()


def test_negative_bad_vocabularies_and_ids():
    """负控 12：词表外的 form/status、非法 ID、乱序未去重的 experiment_ids 都要拒。"""
    with pytest.raises(ValueError, match="form"):
        _make(form="vibes").validate()
    with pytest.raises(ValueError, match="status"):
        _make(status="maybe").validate()
    with pytest.raises(ValueError, match="conjecture_id"):
        _make(conjecture_id="x").validate()
    with pytest.raises(ValueError, match="升序去重"):
        _make(status="supported_not_proved", experiment_ids=["0002", "0001"]).validate()


# ---------------------------------------------------------------- 触点 7：verify 的跨对象判据

def _seed_conjecture(st: Store, **patch) -> None:
    """把一条猜想直接写进表（绕开工具层，专测 verify）。"""
    row = {**GOOD, **patch}
    with st.tx("conjectures", actor="test") as tx:
        tx.upsert("conjectures", row)


def test_verify_flags_a_dangling_experiment(tmp_path: Path):
    """触点 7：引用的实验不存在 ⇒ 逐条 error（不是静默通过）。"""
    st = _store(tmp_path)
    _seed_conjecture(st, status="supported_not_proved", experiment_ids=["0000"])
    rep = V.verify_all(st)
    codes = [i.code for i in rep.issues if i.table == "conjectures"]
    assert "dangling_experiment" in codes, [i.to_dict() for i in rep.issues]


def test_verify_flags_a_dangling_literature_id(tmp_path: Path):
    """触点 7：`known_in_literature` 指了不存在的文献 ⇒ error。"""
    st = _store(tmp_path)
    _seed_conjecture(st, status="known_in_literature", known_lit_id="0000")
    rep = V.verify_all(st)
    assert "dangling_lit" in [i.code for i in rep.issues if i.table == "conjectures"]


def test_verify_flags_a_promotion_that_lands_nowhere(tmp_path: Path):
    """触点 7：升格指向不存在的稿件 ⇒ error（升格落空）。"""
    st = _store(tmp_path)
    _seed_conjecture(st, status="promoted", proof_experiment_id="0000",
                     promoted_to={"kind": "document_claim", "id": "0000#C1"})
    rep = V.verify_all(st)
    assert "promotion_target_missing" in [i.code for i in rep.issues if i.table == "conjectures"]


def test_verify_is_quiet_on_a_clean_conjecture_table(tmp_path: Path):
    """反真空：干净的猜想表不许产生任何 conjectures 相关的问题。"""
    st = _store(tmp_path)
    _seed_conjecture(st)
    rep = V.verify_all(st)
    assert [i.code for i in rep.issues if i.table == "conjectures"] == []
