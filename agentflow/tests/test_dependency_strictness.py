# -*- coding: utf-8 -*-
"""严格规矩 A 与 B 的机械判据（业主 2026-10-22：「转写是提示词侧点一下就行……其它要严格」）。

## 这一份守什么

| 判据 | 它要的读数 |
|---|---|
| ① 正控（A）：`source_stmt_id` 指向一条存在且 `active` 的命题 | 边写得进去 |
| ② 负控（A-不存在）：指向不存在的序号 | 拒绝，理由里点名"不存在" |
| ③ 负控（A-没 closed）：那一行是 `superseded` | 拒绝，理由里点名"没 closed" |
| ④ 负控（A-没查成）：`statements` 表读不出来 | 拒绝，理由里点名"没查成"（不许当通过） |
| ⑤ 正控（B-边）：上下文定理有重锚边（kind + page_range + quote） | 外部命题落库成功 |
| ⑥ 正控（B-声明）：`external_unavailable` + `not_in_our_graph:` | 落库成功，且那一行读得出来 |
| ⑦ 负控（B-都没有）：既无重锚边也无声明 | 拒绝落库，理由点名缺哪一件 |
| ⑦b 反真空：只有一条"裸边"（closed 但没有页码与引文） | 不算重锚 ⇒ 仍然拒绝 |
| ⑧ 三态（B-没查成）：`dependencies` 表读不出来 | 拒绝，理由里点名"没查成" |

## 两条规矩落在哪

规矩 A 在 `tools/doc_tools.py` 的 `register_dependency`：给了 `source_stmt_id` 的任何一条
边（不分 status）在写入前都要过三态核（存在 / `active` / 表读得出来）。
规矩 B 在 `agent_b/register_statement.py`：`register_statement` 在写库前调
`_context_theorem_gaps`，逐条判"重锚边"或"显式声明"，两件都没有就整笔不写。

## 零模型调用

这一份只走落库路径：`AgentB(extractor=None, extract_text=None)` 不起模型、也不抽取。
每一个用例都在 `tmp_path` 下的临时工作区里跑，禁改区一个字节都没碰。
"""
from __future__ import annotations

import pytest

from conftest import TS, add_literature, sync_counters
from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.store import Store
from agentflow.tools.doc_tools import register_dependency


# --------------------------------------------------------------------------- 夹具

def _lit(store: Store, lit_id: str = "") -> str:
    """往 literature 里插一行（外部命题的出处）。"""
    lid = lit_id or S.format_id(0)
    add_literature(store, lid, title="Brown 1971")
    return lid


def _stmt(store: Store, sid: str, *, label: str = "上下文定理 A",
          status: str = "active") -> dict:
    """往 statements 里插一条合法的命题行（自带校验，防止夹具本身不合法）。"""
    row = S.Statement(stmt_id=sid, origin="own_result", kind="theorem", label=label,
                      statement_full=f"设 G 是有限连通图；则 {label} 成立。",
                      proof_text="Proof. 由定义直接得到。", quote_reason="自产结果（判据夹具）",
                      status=status, created_at=TS)
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def _deps(store: Store) -> list[dict]:
    return list(store.rows("dependencies"))


def _external_rows(store: Store) -> list[dict]:
    """台账里 `origin="external_lit"` 的那些行（夹具自己插进去的上下文定理不算）。"""
    return [dict(r) for r in store.rows("statements")
            if str(r.get("origin") or "") == "external_lit"]


def _external(**patch) -> dict:
    """一次 `origin="external_lit"` 的 `register_statement` 参数（只含动作面声明过的键）。"""
    params = {
        "statement_full": "设 X 是紧致流形；则原文 Theorem 1.5 成立（含完整假设）。",
        "origin": "external_lit", "kind": "theorem", "label": "Theorem 1.5",
        "source_lit_id": S.format_id(0), "page_range": {"start": 12, "end": 13},
        "quote_verified": None,
        "quote_reason": "还没逐字核对（这一份判据只测落库闸门，不测引文回验）",
    }
    params.update(patch)
    return params


def _agent(store: Store) -> AgentB:
    """B 的真实现（没有抽取器、不花模型钱），秘书由它自己派生。"""
    return AgentB(store, extractor=None, extract_text=None)


# ==================================================== 一、规矩 A（写入期三态核）

def test_a_positive_control(store: Store) -> None:
    """① 正控：`source_stmt_id` 指向一条存在且 `active` 的命题 ⇒ 写入成功。"""
    _stmt(store, "000001")
    row = register_dependency(
        store, "doc:000001#claim-1", "theorem", "上下文定理 A",
        source_stmt_id="000001", status="closed",
        page_range={"start": 12}, quote="定理 A 的原文一句")
    assert row["source_stmt_id"] == "000001", row
    assert row["status"] == "closed", row
    assert len(_deps(store)) == 1, _deps(store)


def test_a_absent_sequence_is_refused(store: Store) -> None:
    """② 负控：指向一条不存在的序号 ⇒ 拒绝，理由点名"不存在"，零写入。"""
    _stmt(store, "000001")
    with pytest.raises(ValueError) as exc:
        register_dependency(
            store, "doc:000001#claim-1", "theorem", "不存在的上下文定理",
            source_stmt_id="000042", status="closed",
            page_range={"start": 1}, quote="随便一句")
    msg = str(exc.value)
    assert "不存在" in msg, msg
    assert "000042" in msg and "statements" in msg, msg
    assert _deps(store) == [], "被拒的依赖不许留下半行"
    # 同一件事在不闭合的那一档也必须核（改前的判据只在 status='closed' 时核）：
    # 一条 dangling 边指着一个不存在的号同样是坏数据 —— 它在盘上长得像"这条结论依赖
    # 某条命题"，而那条命题根本不存在。
    with pytest.raises(ValueError) as exc2:
        register_dependency(
            store, "doc:000001#claim-2", "theorem", "悬空也不能瞎指",
            source_stmt_id="000042", status="dangling",
            status_reason="这条边暂时没闭合（判据：任何 status 都要核那个号在不在）")
    assert "不存在" in str(exc2.value), str(exc2.value)
    assert _deps(store) == [], "任何 status 都不许留下一条指着空号的边"


def test_a_not_closed_sequence_is_refused(store: Store) -> None:
    """③ 负控：那一行在册但状态不是 `active` ⇒ 拒绝，理由点名"没 closed"。"""
    _stmt(store, "000001", status="superseded")
    with pytest.raises(ValueError) as exc:
        register_dependency(
            store, "doc:000001#claim-1", "theorem", "被取代的上下文定理",
            source_stmt_id="000001", status="closed",
            page_range={"start": 1}, quote="随便一句")
    msg = str(exc.value)
    assert "没 closed" in msg, msg
    assert "superseded" in msg, msg
    assert _deps(store) == [], "没 closed 的命题不许当依据，也不许留半行"


def test_a_unreadable_table_is_not_a_pass(store: Store) -> None:
    """④ 负控：`statements` 读不出来 ⇒ 拒绝并点名"没查成"（读不到不等于通过）。"""
    (store.data / S.TABLES["statements"]["file"]).write_bytes(b"{ this is not json\n")
    with pytest.raises(ValueError) as exc:
        register_dependency(
            store, "doc:000001#claim-1", "theorem", "读不到也得说",
            source_stmt_id="000001", status="closed",
            page_range={"start": 1}, quote="随便一句")
    msg = str(exc.value)
    assert "没查成" in msg, msg
    assert _deps(store) == [], "没查成 ⇒ 一行都不许落（不许当成核过了）"


# ==================================================== 二、规矩 B（重锚 或 显式声明）

def test_b_positive_control_anchor_edge(store: Store) -> None:
    """⑤ 正控：上下文定理有重锚边（kind + source_stmt_id + page_range + quote）⇒ 落库成功。"""
    _lit(store)
    _stmt(store, "000001")
    register_dependency(
        store, f"stmt:{S.format_id(1)}", "theorem", "上下文定理 A",
        source_stmt_id="000001", status="closed",
        page_range={"start": 12}, quote="定理 A 的原文一句")
    out = _agent(store).register_statement(**_external(derived_from=["000001"]))
    assert out["ok"] is True, out
    rows = _external_rows(store)
    assert len(rows) == 1, store.rows("statements")
    assert rows[0]["stmt_id"] == str(out["stmt_id"]), rows[0]
    assert rows[0]["derived_from"] == ["000001"], rows[0]


def test_b_positive_control_explicit_declaration(store: Store) -> None:
    """⑥ 正控：`external_unavailable` + `not_in_our_graph:` 声明 ⇒ 落库成功，且那一行读得出来。"""
    _lit(store)
    register_dependency(
        store, f"stmt:{S.format_id(1)}", "theorem", "原文定理 2.3（不在我们的图内）",
        status="external_unavailable",
        status_reason=("not_in_our_graph: 000042 是原文定理 2.3，我们只收录了主定理，"
                       "没有把它单独登记进 statements"))
    out = _agent(store).register_statement(**_external(derived_from=["000042"]))
    assert out["ok"] is True, out
    rows = _deps(store)
    assert len(rows) == 1, rows
    decl = rows[0]
    assert decl["status"] == "external_unavailable", decl
    assert str(decl["status_reason"]).startswith("not_in_our_graph:"), decl
    assert "000042" in str(decl["status_reason"]), decl
    landed = store.rows("statements")
    assert len(landed) == 1 and landed[0]["derived_from"] == ["000042"], landed


def test_b_negative_control_neither_edge_nor_declaration(store: Store) -> None:
    """⑦ 负控：既无重锚边也无声明 ⇒ 拒绝落库，理由点名缺的是哪两件。"""
    _lit(store)
    _stmt(store, "000001")
    out = _agent(store).register_statement(**_external(derived_from=["000001", "000042"]))
    assert out["ok"] is False, out
    assert out["kind"] == "context_theorem_not_anchored", out
    err = str(out["error"])
    assert "000001" in err and "000042" in err, err
    assert "重锚边" in err, err
    assert "not_in_our_graph" in err, err
    assert "page_range" in err and "quote" in err, err
    assert _external_rows(store) == [], "拒绝落库 ⇒ 一条外部命题都不许留"


def test_b_a_bare_edge_without_page_and_quote_does_not_count(store: Store) -> None:
    """⑦b 反真空：只有一条没有页码与引文的裸边 ⇒ 不算重锚，仍然拒绝。"""
    _lit(store)
    _stmt(store, "000001")
    register_dependency(
        store, f"stmt:{S.format_id(1)}", "theorem", "上下文定理 A（光秃秃的边）",
        source_stmt_id="000001", status="closed")
    out = _agent(store).register_statement(**_external(derived_from=["000001"]))
    assert out["ok"] is False, out
    assert out["kind"] == "context_theorem_not_anchored", out
    assert _external_rows(store) == [], "裸边不算重锚 ⇒ 外部命题一行都不许落"


def test_b_unreadable_graph_is_not_a_pass(store: Store) -> None:
    """⑧ 三态：`dependencies` 读不出来 ⇒ 拒绝并点名"没查成"（不许当成"都处理过了"）。"""
    _lit(store)
    (store.data / S.TABLES["dependencies"]["file"]).write_bytes(b"{ this is not json\n")
    out = _agent(store).register_statement(**_external(derived_from=["000042"]))
    assert out["ok"] is False, out
    assert out["kind"] == "context_graph_unreadable", out
    assert "没查成" in str(out["error"]), out
    assert _external_rows(store) == [], "没查成 ⇒ 一行都不许落"
