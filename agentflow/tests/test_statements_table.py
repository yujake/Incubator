# -*- coding: utf-8 -*-
"""命题台账（`statements` 表）：`draft/37` §16 P1 的数据面判据。

## 这一组守什么

真机那一轮"审阅并 polish 一篇论文"跑完后，台账里有依赖、有发现、有报告，
却没有一处放得下"定理 1.5 的假设是什么、它的证明原文长什么样"。
这张表就是那个落点，于是它的判据必须回答三个问题：

1. 进得来吗：一条合规的命题能写进去、能被 `table.*` 看见、`verify` 干净；
2. 进不来吗（负控）：缺假设、缺出处、缺证明、没校验却不写原因的，逐条都要炸——
   而且是在写入时炸（`schema.validate`），不是等报告印出来才发现；
3. 进来之后还管得住吗：`verify` 的三条不变量（出处悬空 / 承重链缺环 /
   `proof` 级命题压在不可用的命题上）各有一条注入负控 + 一条"好数据不许误伤"。

判据的第一条（缺 `statement_full` 的行不许进 `active`）是 §16 P1 逐字要求的那一条。
"""

from __future__ import annotations

import pytest
from conftest import TS, add_literature, sync_counters
from agentflow import schema as S
from agentflow.verify import verify_all


def _issues(store, *, level: str | None = None, kind: str | None = None):
    """取 verify 的 issue 列表（字段名是 `code`，不是 `kind` —— 用错会静默取空）。"""
    rep = verify_all(store)
    d = rep.to_dict()
    out = list(d["errors"]) + list(d["warnings"])
    if level is not None:
        out = [i for i in out if i["level"] == level]
    if kind is not None:
        out = [i for i in out if i["code"] == kind]
    return out


def _reject(**kw) -> str:
    """造一条命题并要求它在 `validate()` 时被拒，返回那句错误文本。

    为什么要这么写：本仓的纪律是"构造不做校验、`validate()` 才校验"
    （`store.tx` 与 `validate_table` 都会调它），所以负控必须走到 `validate()`
    才谈得上"拒"。只在构造函数上断言的话，负控会以 `DID NOT RAISE` 的形态假绿。
    """
    row = S.Statement(**kw)
    with pytest.raises(ValueError) as e:
        row.validate()
    return str(e.value)


def _stmt(store, sid: str, **kw) -> dict:
    """写一条合规的命题，返回它的行字典（不合规时由 `validate()` 抛）。"""
    base = dict(
        stmt_id=sid,
        origin="external_lit",
        kind="theorem",
        label="Theorem 1.5",
        statement_text="随机游走的距离有 CLT 型极限",
        statement_full=("设 G 是有限连通图，X_n 是室图上的随机游走，"
                        "且各边的电导有正下界；则 (d(X_0,X_n)-E d)/sqrt(n) 依分布收敛到正态"),
        proof_text="Proof. By Theorem 6.5 of the companion book ...",
        source_lit_id="0000",
        quote_verified=True,
        quote_reason="逐字比对通过（page 7）",
        evidence_kind="cross_check",
        status="active",
        created_at=TS,
    )
    base.update(kw)
    row = S.Statement(**base)
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sync_counters(store)
    return row.to_dict()


# ==================================================== 一、进得来（正控）

def test_a_complete_statement_row_round_trips(store):
    """正控：一条合规命题写进去、读回来、`verify` 不因它报任何 error。"""
    store.init()
    add_literature(store, "0000", title="Random walks on chamber graphs")
    want = _stmt(store, "0001")
    rows = store.rows("statements")
    assert len(rows) == 1, rows
    got = S.row_from_dict("statements", rows[0])
    assert got.statement_full == want["statement_full"], "含完整假设的那一栏必须逐字读回来"
    assert got.quote_verified is True
    assert got.page_range.to_dict() == {"start": None, "end": None, "label": ""}
    assert [i for i in _issues(store, level="error")] == [], _issues(store, level="error")


def test_the_new_table_is_visible_to_the_generic_table_tools(store):
    """新表自动获得通用表操作与词表暴露（`draft/29` §10.4 第 6 处触点的正面）。"""
    from agentflow.tools import build_registry

    store.init()
    reg = build_registry(store=store, workspace_root=store.root).registry
    res = reg.call("table.schema", role="B")
    assert res.ok, res
    tables = res.data["tables"]
    assert "statements" in tables, f"新表没进 table.schema 的反射面：{sorted(tables)}"
    spec = tables["statements"]
    assert spec["primary_key"] == "stmt_id" and spec["uses_id_counter"] is True, spec
    vocabs = spec["vocabularies"]
    assert vocabs["origin"]["values"] == list(S.STATEMENT_ORIGINS), vocabs
    assert vocabs["status"]["values"] == list(S.STATEMENT_STATUSES), vocabs
    assert vocabs["evidence_kind"]["values"] == list(S.EVIDENCE_KINDS), vocabs
    assert "kind" not in vocabs, (
        "kind 刻意不是受控词表（理由见 schema.Statement 的 docstring）—— "
        "登记了它就会凭空多出五六个没有产出点的死取值")
    # 反真空：一个不存在的词表字段必须真的不在（否则上面那条断言只是读了反射的空壳）
    assert "label" not in vocabs and "proof_text" not in vocabs


# ==================================================== 二、进不来（负控）

def test_a_statement_without_full_assumptions_cannot_be_active(store):
    """§16 P1 逐字要求的那条负控：缺 `statement_full`（无假设）的行不许进 `active`。"""
    store.init()
    add_literature(store, "0000", title="L")
    msg = _reject(stmt_id="0001", origin="external_lit", source_lit_id="0000",
                  statement_full="", quote_verified=True, quote_reason="比对通过")
    assert "statement_full" in msg and "假设" in msg, msg
    # 反真空：同一条命题补上假设就能进（否则"永远拒绝"会冒充严格）
    row = S.Statement(stmt_id="0001", origin="external_lit", source_lit_id="0000",
                      statement_full="若 n 为奇数，则……", quote_verified=True,
                      quote_reason="比对通过")
    row.validate()


def test_an_external_statement_must_name_its_source(store):
    """负控：`external_lit` 不写出处 ⇒ 拒（逐字回验没有第二份文本可比）。"""
    store.init()
    msg = _reject(stmt_id="0001", origin="external_lit", statement_full="命题",
                  quote_verified=None, quote_reason="还没查")
    assert "source_lit_id" in msg, msg


def test_an_own_result_without_a_proof_cannot_enter(store):
    """负控：`own_result` 没有证明 ⇒ 拒（§10 的自产入库门落到数据面就是这一条）。"""
    store.init()
    msg = _reject(stmt_id="0001", origin="own_result", statement_full="我们猜……",
                  quote_verified=None, quote_reason="自产结果不走逐字回验")
    assert "proof_text" in msg and "自产" in msg, msg


def test_the_quote_check_is_three_state_and_must_say_why(store):
    """三态纪律：`False`（不一致）与 `None`（没校验）都必须写原因，`True` 也要留痕但可空。"""
    store.init()
    for verified in (False, None):
        msg = _reject(stmt_id="0001", origin="own_result", statement_full="命题",
                      proof_text="证明", quote_verified=verified, quote_reason="")
        assert "quote_reason" in msg, (verified, msg)
    S.Statement(stmt_id="0001", origin="own_result", statement_full="命题", proof_text="证明",
                quote_verified=False, quote_reason="原文写的是 n 为偶数，台账写反了").validate()
    S.Statement(stmt_id="0002", origin="own_result", statement_full="命题", proof_text="证明",
                quote_verified=None, quote_reason="这篇没有可抽取的文本层，还没法比对").validate()


def test_origin_is_required_and_the_counters_are_not_process_ids(store):
    """`origin` 必填（空串拒）；命题吃 4 位编号空间（它不是过程记录）。"""
    store.init()
    msg = _reject(stmt_id="0001", statement_full="命题")
    assert "origin" in msg, msg
    assert S.ID_COUNTERS["stmt"] == "stmt_id", "命题是知识实体，必须吃 4 位编号空间"
    assert "stmt" not in S.process_id_kinds(), (
        "走 ID_COUNTERS 的表不该被算成过程记录 —— 两半必须互斥（见 PROCESS_ID_PREFIXES）")


def test_derived_from_is_a_sorted_set_without_self_reference(store):
    """`derived_from` 是集合：升序去重、不含自身、每个都得是合法 id。"""
    store.init()
    base = dict(stmt_id="0001", origin="own_result", statement_full="命题", proof_text="证明",
                quote_verified=None, quote_reason="自产结果不走逐字回验")
    with pytest.raises(ValueError):
        S.Statement(**base, derived_from=["0003", "0002"]).validate()
    with pytest.raises(ValueError):
        S.Statement(**base, derived_from=["0001"]).validate()
    with pytest.raises(ValueError):
        S.Statement(**base, derived_from=["abc"]).validate()
    S.Statement(**base, derived_from=["0002", "0003"]).validate()


# ==================================================== 三、进来之后管得住

def test_a_refuted_dependency_cannot_carry_a_proof_level_claim(store):
    """§16 P1 的新不变量（照抄 `proof_claim_with_unclosed_dependency` 的形状）。

    `draft/37` §9：如果被引用的那条本身是错的，压在它上面的 proof 级断言
    就不能再算数 —— 这与"依赖没闭合"是两件事，处置方向相反（撤结论 vs 补来源）。
    """
    store.init()
    add_literature(store, "0000", title="L")
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", S.Document(
            doc_id="0001", kind="paper", title="未发表的论文", status="in_review",
            claims=[{"claim_id": "c1", "text": "已证明 x", "citations": ["lit:0000"],
                     "evidence_kind": "proof"}], created_at=TS).to_dict())
    with store.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", S.Dependency(
            dep_id="0001", used_by="doc:0001#c1", kind="theorem", label="Brown Thm",
            status="refuted", status_reason="复算发现原文条件少了正性假设",
            created_at=TS).to_dict())
    sync_counters(store)
    errs = _issues(store, level="error", kind="proof_claim_on_refuted_dependency")
    assert len(errs) == 1, (errs, _issues(store))
    assert "撤" in errs[0]["message"] or "降" in errs[0]["message"], errs[0]["message"]
    # 同时必须有一条"这条依赖本身被证否了"的读数（两条不是同一件事）
    assert len(_issues(store, level="error", kind="refuted_dependency_in_use")) == 1


def test_a_disputed_dependency_blocks_proof_but_is_only_a_warning(store):
    """分级（FC-13）：`disputed` = 已知有争议、等裁决 ⇒ 依赖级 warning；
    但它撑不起 `proof` 级主张 ⇒ 那一条仍是 error。"""
    store.init()
    add_literature(store, "0000", title="L")
    with store.tx("documents", actor="test") as tx:
        tx.upsert("documents", S.Document(
            doc_id="0001", kind="paper", title="p", status="in_review",
            claims=[{"claim_id": "c1", "text": "已证明 x", "citations": ["lit:0000"],
                     "evidence_kind": "proof"}], created_at=TS).to_dict())
    with store.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", S.Dependency(
            dep_id="0001", used_by="doc:0001#c1", kind="theorem", label="有争议的定理",
            status="disputed", status_reason="两篇文献给出不同常数", created_at=TS).to_dict())
    sync_counters(store)
    assert len(_issues(store, level="warning", kind="disputed_dependency_in_use")) == 1
    assert len(_issues(store, level="error", kind="proof_claim_on_disputed_dependency")) == 1
    # 反真空：把同一行改成 closed（并补来源）之后，两条都必须消失
    with store.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", S.Dependency(
            dep_id="0001", used_by="doc:0001#c1", kind="theorem", label="有争议的定理",
            status="closed", source_lit_id="0000", status_reason="",
            created_at=TS).to_dict())
    assert _issues(store, kind="proof_claim_on_disputed_dependency") == []
    assert _issues(store, kind="disputed_dependency_in_use") == []


def test_a_proof_level_statement_may_not_rest_on_an_unusable_statement(store):
    """命题级同族不变量：`proof` 级命题不许压在 `refuted` / `superseded` / `disputed` 上。"""
    store.init()
    add_literature(store, "0000", title="L")
    _stmt(store, "0001", status="refuted", quote_reason="原文的证明有洞")
    _stmt(store, "0002", status="disputed", quote_reason="两版页码对不上")
    _stmt(store, "0003", evidence_kind="proof", derived_from=["0001", "0002"])
    errs = _issues(store, level="error", kind="proof_stmt_on_unusable_stmt")
    warns = _issues(store, level="warning", kind="proof_stmt_on_unusable_stmt")
    assert len(errs) == 1 and "0001" in errs[0]["message"], errs
    assert len(warns) == 1 and "0002" in warns[0]["message"], warns


def test_a_dangling_statement_reference_is_an_error(store):
    """承重链上少一环必须报（§4 的依赖图读数就是被这种缺口污染的）。"""
    store.init()
    add_literature(store, "0000", title="L")
    _stmt(store, "0001", derived_from=["0099"])
    errs = _issues(store, level="error", kind="dangling_stmt_ref")
    assert len(errs) == 1 and "0099" in errs[0]["message"], errs


def test_an_active_literature_statement_without_quote_check_warns(store):
    """三态在 verify 里的形态：`active` 的文献命题没逐字回验 ⇒ warning（可见但不拦）。"""
    store.init()
    add_literature(store, "0000", title="L")
    _stmt(store, "0001", quote_verified=None, quote_reason="还没查")
    warns = _issues(store, level="warning", kind="active_stmt_quote_unverified")
    assert len(warns) == 1, warns
    # 反真空：验过之后这条 warning 必须消失
    with store.tx("statements", actor="test") as tx:
        row = dict(store.rows("statements")[0])
        row["quote_verified"] = True
        row["quote_reason"] = "逐字比对通过"
        tx.upsert("statements", row)
    assert _issues(store, kind="active_stmt_quote_unverified") == []


def test_a_statement_whose_source_is_missing_is_an_error(store):
    """出处悬空（文献/稿件）必须报 —— 与 `dangling_dep` 同族，只是发生在命题级。"""
    store.init()
    _stmt(store, "0001", source_lit_id="0042", doc_id="0077")
    assert len(_issues(store, level="error", kind="dangling_lit_ref")) == 1
    assert len(_issues(store, level="error", kind="dangling_doc_ref")) == 1


def test_the_statements_reading_is_reported(store):
    """读数面：`checked['statements_usable']` 必须真的在数（否则"没查"与"查了没问题"同形）。"""
    store.init()
    add_literature(store, "0000", title="L")
    _stmt(store, "0001")
    _stmt(store, "0002", status="refuted", quote_reason="原文有洞")
    rep = verify_all(store)
    assert rep.checked["statements_usable"] == 1, rep.checked
