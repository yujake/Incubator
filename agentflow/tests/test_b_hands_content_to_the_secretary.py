# -*- coding: utf-8 -*-
"""B 交内容、秘书落盘：命题写入代理的四件活（业主 2026-10-09）。

业主逐字：「写入侧应该都是B的活，让B的秘书帮它洗格式、拿编号、改表、查重，即B不直接用增工具，
秘书实际操作增、改（比如一个定理在两个文献中都有证明，可以互相借鉴把证明写好点；如果证明路径
不唯一，可增另一组依赖，实现用二维列表）、查工具，B纯粹负责消化理解。」

这一组守什么：四件活各有一条判据，外加两条"这条路径不许有后备路"的反真空：① 洗格式
（`wash_statement`）：别名键认出来、裹了一层摊上来、一维 `deps` 包成一条路径，而内容一个字不动；
② 拿编号（`tx.alloc_id`）：号来自唯一分配器（四位数、不与既有行撞号）；③ 查重
（`textutil.normalize(statement_full)`）：同内容交两次 ⇒ 第二次是重复读数、不新建行；`force_new`
才另起；④ 改表（一笔事务）：`statements` + 概念行 + `dependencies`（二维列表按外层下标写
`path_group`）；⑤ 反真空一：没装 store ⇒ 受控拒绝且一行不落（不许退回"B 自己写"）；⑥ 反真空二：
`Secretary.writes` 必须真是这两张表（空集 = 这句声明没有内容）。

三态纪律在这条路上的落点：依赖里有一条指着不在册的 id ⇒ 整笔不写（`unresolved_dependency`），
而不是"少写一条边"：依赖图上少一环没有任何地方会报错，那正是这套东西要堵的形态。概念的定义空着
⇒ `concept_definition_pending`（`draft/93·续` D12 未裁之前不落那种行）。"""

from __future__ import annotations

import importlib

from conftest import TS, add_literature, sync_counters
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import secretary as SEC


def _rows(store, table: str) -> list[dict]:
    return list(store.rows(table))


def _sec(store, role: str = "B", **kw) -> SEC.Secretary:
    return SEC.Secretary(role, root=store.root, store=store, **kw)


def _exp(store, eid: str) -> dict:
    row = S.Experiment(
        experiment_id=eid, claim="K(m) 的谱", claim_key="SpecK(m)=[-m,m]", method="numeric",
        evidence_kind="cross_check", result="supports", negation_kind="not_proved",
        code_path="code/exp.py", code_hash="deadbeefdeadbeef", exit_code=0, created_at=TS)
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _payload(**kw) -> dict:
    base = dict(
        origin="external_lit", kind="theorem", label="Theorem 1.5",
        statement_text="随机游走的距离有 CLT 型极限",
        statement_full=("设 G 是有限连通图，且各边电导有正下界；则 (d(X_0,X_n)-E d)/sqrt(n) "
                        "依分布收敛到正态"),
        proof_text="Proof. By Theorem 6.5 of the companion book ...",
        source_lit_id=S.format_id(0), page_range={"start": 7, "end": 7},
        quote_verified=True, quote_reason="逐字比对通过（page 7）",
        evidence_kind="proof",
    )
    base.update(kw)
    return base


# ==================================================== 一、四件活（正控）

def test_a_statement_lands_in_one_transaction_with_its_dependency_groups(store):
    """交一条消化结果 ⇒ 三张表一次落：命题行、两组依赖（`path_group` 按外层下标）。"""
    add_literature(store, S.format_id(0))
    _exp(store, S.format_id(1))
    sec = _sec(store)
    # 路径 1 要指一条在册的命题 ⇒ 先落一条（依赖不许挂空号，见负控）
    target = sec.record_statement(_payload(statement_full="引理 A：电导有正下界", label="引理 A"),
                                  role="B")
    assert target["created"], target
    bits = EB.bits_of(proof=True, proof_process="逐步论证……")
    out = sec.record_statement(_payload(bits=bits, deps=[
        [{"kind": "theorem", "stmt_id": target["stmt_id"], "label": "引理 A"}],   # 路径 1
        [{"kind": "experiment", "exp": S.format_id(1)}],                                  # 路径 2
    ]), role="B")
    assert out["checked"] and out["created"], out
    assert out["path_groups"] == 2 and out["deps_written"] == 2
    sid = out["stmt_id"]
    assert len(sid) == S.ID_DIGITS and sid.isdigit(), sid
    stmts = {s["stmt_id"]: s for s in _rows(store, "statements")}
    assert set(stmts) == {target["stmt_id"], sid}, "这一笔只该多一行命题"
    assert stmts[sid]["bits"]["proof"] is True
    # 路径 1 指的那条命题得先在册（负控里有一条"不在册 ⇒ 整笔不写"）
    deps = _rows(store, "dependencies")
    assert len(deps) == 2, deps
    assert {d["path_group"] for d in deps} == {1, 2}
    assert all(d["used_by"] == f"stmt:{sid}" for d in deps)
    exp_edge = next(d for d in deps if d["path_group"] == 2)
    assert exp_edge["source_experiment_id"] == S.format_id(1) and exp_edge["kind"] == "experiment"


def test_the_wash_only_touches_the_format_face(store):
    """别名键 / 顶层裹了一层 / 一维 deps —— 洗成受控形状，内容一个字不动。"""
    add_literature(store, S.format_id(0))
    _exp(store, "0001")
    sec = _sec(store)
    full = _payload()["statement_full"]
    washed = sec.wash_statement({
        "theorem": full,                                  # 别名 ⇒ statement_full
        "proof": "Proof. ……",                             # 别名 ⇒ proof_text
        "lit_id": S.format_id(0),                                 # 别名 ⇒ source_lit_id
        "params": {"kind": "lemma", "label": " 引理 B "},  # 裹了一层 + 空白
        "deps": [{"stmt": "0002", "type": "experiment", "exp": "0001"}],   # 一维 + 别名
        "pages": {"start": 7, "end": 7},
    })
    assert washed["checked"] and washed["washed"], washed
    body = washed["payload"]
    assert body["statement_full"] == full, "内容面一个字都不许动"
    assert body["kind"] == "lemma" and body["label"] == "引理 B", body
    assert body["statement_full"] is not None and "params" not in body
    assert body["deps"] == [[{"stmt_id": "0002", "kind": "experiment",
                              "experiment_id": "0001"}]], body["deps"]
    assert any("一维列表" in c for c in washed["changes"]), washed["changes"]


def test_a_concept_row_carries_no_proof_text(store):
    """概念也入库：`kind="concept"`，而证明那一格必须是空的。

    这一条在 2026-10-21 改过一次口径（本批缺陷一，业主的验收词）：此前断言
    `proof_text == "concept:primitive"`（"良定义性证明"），而那个哨兵正是真机 mp3
    那 1143 条污染行的来源 —— 概念不参与等级链（`draft/97` §14.5），任何“有没有
    证明”的读数（`proof_review_gap`、收工门的 reviewed 档）都会被它顶高。
    改的是契约，不是把判据放宽：断言从“必须等于哨兵”变成“必须为空”。
    历史行一个字不动（读侧由 `verifications.proof_review_gap` 点名）。
    """
    add_literature(store, S.format_id(0))
    sec = _sec(store)
    out = sec.record_statement(_payload(
        source_lit_id=S.format_id(0),
        concepts=[{"name": "电导（conductance）", "definition": "边上权重的倒数",
                   "aliases": ["conductance"]}]), role="B")
    assert out["checked"] and out["created"], out
    rows = {s["kind"]: s for s in _rows(store, "statements")}
    c = rows["concept"]
    assert c["proof_text"] == "", (
        f"概念行不该带证明文本（它不参与等级链）：{c['proof_text']!r}")
    assert c["statement_full"] == "边上权重的倒数" and c["aliases"] == ["conductance"]
    assert c["quote_reason"].strip(), "quote_verified 不是 True ⇒ 必须写理由"
    # 出处按来源分档：这条概念带着文献出处 ⇒ external_lit（不是 own_result）
    assert c["origin"] == "external_lit", c["origin"]
    assert "dependencies" in out["tables"] and "statements" in out["tables"]


# ==================================================== 二、查重与编号（负控）

def test_the_same_statement_twice_is_a_duplicate_reading(store):
    """同内容交两次 ⇒ 第二次是重复读数、不新建行；`force_new` 才另起。"""
    add_literature(store, S.format_id(0))
    sec = _sec(store)
    first = sec.record_statement(_payload(), role="B")
    again = sec.record_statement(_payload(), role="B")
    assert again["checked"] and again["duplicate"] and not again["created"], again
    assert again["stmt_id"] == first["stmt_id"], "重复读数要指向既有那一条"
    assert len(_rows(store, "statements")) == 1
    forced = sec.record_statement(_payload(), role="B", force_new=True)
    assert forced["created"] and forced["stmt_id"] != first["stmt_id"]
    assert len(_rows(store, "statements")) == 2, "force_new 才允许另起一条"


def test_a_dependency_on_a_missing_id_writes_nothing(store):
    """依赖指着不在册的 id ⇒ 整笔不写（不许少写一条边了事）。"""
    add_literature(store, S.format_id(0))
    sec = _sec(store)
    out = sec.record_statement(_payload(deps=[[{"kind": "theorem", "stmt_id": "9999"}]]),
                               role="B")
    assert out["refused"] == "unresolved_dependency" and not out["created"], out
    assert "9999" in str(out["reason"]) or out.get("unresolved"), out
    assert out["unresolved"][0]["path_group"] == 1
    assert _rows(store, "statements") == [] and _rows(store, "dependencies") == []


def test_a_concept_without_a_definition_lands_as_pending(store):
    """定义空着的概念行照落（`D12` 甲）：`pending_definition` + 待补标记，且不是依据。

    这一条改过一次口径（2026-10-09 业主选甲）：此前是"整笔不写"（等裁定），
    现在是"行先落、内容后到"——边界钉在这里：它落在
    `STATEMENT_UNUSABLE_STATUSES` 里（下游不许拿它当依据），
    而且必须带 `concept:pending_search` 标记（谁去补写在 reason 里）。
    """
    add_literature(store, S.format_id(0))
    sec = _sec(store)
    out = sec.record_statement(_payload(concepts=[{"name": "新概念", "definition": ""}]),
                               role="B")
    assert out["checked"] and out["created"] and out["pending_concepts"] == 1, out
    rows = [s for s in _rows(store, "statements") if s["kind"] == "concept"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["status"] == "pending_definition", row["status"]
    assert row["status"] in S.STATEMENT_UNUSABLE_STATUSES, "待补不是依据"
    assert "concept:pending_search" in row["quote_reason"], row["quote_reason"]
    assert row["statement_full"] == "" and row["label"] == "新概念"
    # 反真空：同一个概念再交一次 ⇒ 查重（不新建行、指向既有那一条）。
    # 查重按概念标签比（不是命题那一格）：所以这里交的是"只交一条概念"的载荷 ——
    # 那也正是 A 检索回来之前 B 交的形状（`kind="concept"` + 空 `statement_full`）。
    again = sec.record_statement(_payload(kind="concept", label="新概念", statement_full="",
                                          proof_text="concept:primitive"), role="B")
    assert again["duplicate"] and again["stmt_id"] == row["stmt_id"], again
    assert len([s for s in _rows(store, "statements") if s["kind"] == "concept"]) == 1


def test_a_theorem_without_full_statement_is_still_refused(store):
    """反真空的另一半：命题缺 `statement_full` 仍然拒（"待补"那一档只给概念）。"""
    add_literature(store, S.format_id(0))
    sec = _sec(store)
    out = sec.record_statement(_payload(statement_full="", kind="theorem"), role="B")
    assert out["refused"] == "empty_statement" and not out["created"], out
    assert _rows(store, "statements") == []


# ==================================================== 三、不许有后备路（反真空）

def test_without_a_store_the_secretary_refuses_instead_of_b_writing(store):
    """没装 store ⇒ 受控拒绝（`secretary_unavailable`），且一行都不落。"""
    sec = SEC.Secretary("B", root=store.root)          # 刻意不给 store
    out = sec.record_statement(_payload(), role="B")
    assert out["refused"] == "secretary_unavailable" and not out["created"], out
    assert _rows(store, "statements") == [], "拒绝之后一行都不许落"


def test_only_b_may_hand_content_to_the_writer(store):
    """写入侧是 B 的活：别的角色交内容 ⇒ 受控拒绝。"""
    sec = _sec(store)
    for role in ("A", "D", "G", "M"):
        out = sec.record_statement(_payload(), role=role)
        assert out["refused"] == "not_statement_writer", (role, out)
    assert _rows(store, "statements") == []


def test_the_declared_write_set_is_not_empty():
    """反真空：写集必须是那两张表 —— 空集会让"秘书有没有写集"这句声明没有内容。"""
    assert SEC.STATEMENT_WRITE_TABLES == ("statements", "dependencies")
    assert SEC.STATEMENT_WRITER_ROLES == ("B",)
    import pathlib

    text = pathlib.Path("src/agentflow/secretary.py").read_text(encoding="utf-8")
    assert "frozenset(STATEMENT_WRITE_TABLES)" in text, \
        "`self.writes` 必须由这一处常量给（两处各写一份必然漂）"


# ==================================================== 四、B 的动作真的走这条路径

def test_b_register_statement_writes_through_the_secretary(store):
    """B 的动作用秘书落盘：行上留痕是秘书，号来自唯一分配器，内容一字不改。"""
    from agentflow.agent_b import AgentB

    add_literature(store, S.format_id(0))
    b = AgentB(store, extractor=None, extract_text=None)
    assert b._statement_secretary() is not None, "生产口径下 B 必须能拿到秘书（自动派生）"
    out = b.register_statement(
        origin="external_lit", kind="theorem", label="Theorem 1.5",
        statement_text="短版", statement_full="设 G 是有限连通图；则结论成立。",
        proof_text="Proof. ……", source_lit_id=S.format_id(0), page_range={"start": 7},
        quote_verified=True, quote_reason="逐字比对通过", evidence_kind="proof")
    assert out["ok"] is True, out
    row = store.rows("statements")[0]
    assert row["created_by"] == "secretary-B", (
        "落盘那一笔要留痕是秘书（B 不直接用增工具）")
    assert row["statement_full"] == "设 G 是有限连通图；则结论成立。"
    assert row["stmt_id"] == out["stmt_id"]
    assert "秘书落盘" in out["note"] and "路径组" in out["note"]


def test_b_without_a_secretary_writes_nothing(store):
    """反真空：`auto_secretary=False` ⇒ 受控拒绝，一行都不落（没有"B 自己写"这条后备路）。"""
    from agentflow.agent_b import AgentB

    add_literature(store, S.format_id(0))
    b = AgentB(store, extractor=None, extract_text=None, auto_secretary=False)
    out = b.register_statement(
        origin="external_lit", statement_full="设 G 是有限连通图；则结论成立。",
        proof_text="Proof. ……", source_lit_id=S.format_id(0), page_range={"start": 7},
        quote_verified=True, quote_reason="逐字比对通过")
    assert out["ok"] is False and out["kind"] == "secretary_unavailable", out
    assert store.rows("statements") == [], "被拒的命题不许留下半行"

