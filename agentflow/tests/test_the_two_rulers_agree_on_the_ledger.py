# -*- coding: utf-8 -*-
"""判据：「两把尺」在命题台账上已统一为一把（`table.search` × `statementledger`）。

## 钉的是什么（业主 2026-11-09：同一个查询两处结论必须一致）

统一之前：通用表工具 `table.search` 对 `statements` 的 18 个标量字符串字段做
`casefold` 裸子串；命题查口 `statementledger.by_keywords` 只比 `label` /
`statement_full`、用 `textutil.normalize`（全半角 / 大小写 / 标点 / 空白都折叠）。
同一份台账、同一个查询，模型与秘书会得到不同结论，而两边各自都自洽。
实测（`temp/_probe_two_rulers_before.py`）：`noether，环` 查口 1 条 / 工具层 0 条；
全角 `Ｐ 阶元` 查口 1 条 / 工具层 0 条；`Ｇ 是有限群` 查口 2 条 / 工具层 1 条。

| # | 判据 | 反真空 |
|---|---|---|
| a | 同一个查询（含全半角 / 大小写 / 标点差异）在 `table.search` 与 `by_keywords` 上给出同一批 `stmt_id`、`total == hits_total`；8 组，含一组两边都 0 命中 | 非 0 组都断言 `total > 0`；0 命中组断言查口 `checked=True`（"查过、0 条"不是"没查成"） |
| b | 反真空：把 statements 分支换回统一前的 `casefold` ⇒ 同一批查询里至少一组两边不一致（判据红） | 负控用统一前实测到不一致的那两问（`Ｐ 阶元` / `noether，环`） |
| c | 非 statements 表行为不变：`literature` / `research_questions` 与"改前算法"（`casefold` + 全部标量字符串字段）逐行对拍 | 全角查询在非 statements 表上仍 0 命中（证明统一没有外溢） |
| d | 返回形状不变：`data` / `meta` 键集、`select`、`limit` / `truncated`、`fields` 读数 | — |
| e | 边界：`query` 归一后为空 ⇒ 受控拒绝（statements），不是"0 命中"；查口同问 `checked=False` | — |
| f | 显式点名内容面之外的字段（`proof_text`）⇒ 受控拒绝并指路 `table.list` / `table.get` | 只点名内容面子集（`fields=["label"]`）照常工作 |

零模型调用：不起 provider、不写仓内文件（工作区在 `tmp_path`）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import statementledger as SL
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import table_tools as TT

from conftest import seed_statement_row

#: 夹具的 5 行（覆盖：半角 G、全角 Ｇ、大小写、全角逗号、裸标点 `^`、0 命中的诱饵）。
ROWS: tuple[tuple[str, str], ...] = (
    ("P 阶元", "设 G 是有限群且 |G| = p^a·m（p∤m），则 G 有 p 阶元。"),
    ("单位元", "设 Ｇ 是有限群，则 Ｇ 有单位元。"),
    ("Abelian", "An ABELIAN group satisfies gh = hg."),
    ("Noether 环", "设 R 是 Noether 环，则 R 是升链条件环。"),
    ("Q(n)", "另一条命题：设 n<=3，则 Q(n) 成立。"),
)

#: a 的 8 组：全半角 3 组、大小写 2 组、标点 1 组、普通 1 组、0 命中 1 组。
QUERIES: tuple[str, ...] = (
    "Ｐ 阶元",       # 全角 P ⇒ normalize 折成半角
    "Ｇ 是有限群",     # 全角 G ⇒ 半角 G 那一行也要算命中（统一前工具层漏）
    "ABELIAN",      # 大小写
    "abelian",      # 大小写（另一头）
    "noether，环",    # 全角逗号 ⇒ normalize 吃成空格（统一前工具层 0 命中）
    "p^a",          # 裸标点（两边本来就该都命中：文本里有同样的 `p^a`）
    "有限群",         # 普通中文
    "量子纠缠",       # 0 命中（两边都必须 0）
)


def _workspace(root: pathlib.Path) -> tuple[Store, object]:
    """一个铺好 5 行命题的台账 + 绑好 store 的工具面。"""
    ws = root / "ws"
    store = Store(ws)
    store.init()
    for label, full in ROWS:
        seed_statement_row(store, statement_full=full, label=label, kind="theorem")
    reg = build_registry(store=Store(ws), workspace_root=ws).registry
    return store, reg


@pytest.fixture()
def env(tmp_path: pathlib.Path):
    return _workspace(tmp_path)


def _search_ids(reg, query: str, **kw) -> list[str]:
    r = reg.call("table.search", role="B", table="statements", query=query, **kw)
    assert r.ok, r.error
    return sorted(str(row.get("stmt_id") or "") for row in r.data["rows"])


def _ledger_ids(store: Store, query: str) -> list[str]:
    got = SL.by_keywords(store, keywords=[query])
    assert got["checked"] is True, got
    return sorted(str(h["stmt_id"]) for h in got["hits"])


# ===================================================== a 同一个查询 ⇒ 同一批行
@pytest.mark.parametrize("query", QUERIES)
def test_a_the_two_rulers_answer_the_same_query_the_same_way(env, query: str) -> None:
    """a：同一份台账、同一个查询，两处给出同一批 `stmt_id` 与同一个计数。"""
    store, reg = env
    table_ids = _search_ids(reg, query)
    ledger = SL.by_keywords(store, keywords=[query])
    ledger_ids = sorted(str(h["stmt_id"]) for h in ledger["hits"])
    assert table_ids == ledger_ids, (
        f"查询 {query!r}：table.search 给 {table_ids}，by_keywords 给 {ledger_ids} —— "
        "两把尺又分家了（归一函数必须是同一份 `textutil.normalize`）")
    assert len(table_ids) == ledger["hits_total"], (
        f"查询 {query!r}：total={len(table_ids)} vs hits_total={ledger['hits_total']}")
    if query == "量子纠缠":
        # 0 命中那组：查口必须是"查过、0 条"，不是"没查成"（三态不许折平）。
        assert table_ids == [] and ledger["hits_total"] == 0, (table_ids, ledger)
        assert "命中 0 条" in ledger["why"], ledger["why"]
    else:
        # 反真空：其余 7 组必须真有命中，否则"两边相等"可能只是"两边都 0"。
        assert table_ids, f"查询 {query!r} 两边都是 0 命中 ⇒ 这一组比较是空的"


def test_a_statements_default_surface_is_the_ledger_content_surface(env) -> None:
    """a2：默认搜索面 = `label` / `statement_full`（18 → 2 是本次统一的一部分）。"""
    _, reg = env
    r = reg.call("table.search", role="B", table="statements", query="有限群")
    assert r.ok, r.error
    assert r.data["fields"] == ["label", "statement_full"], r.data["fields"]
    assert set(r.meta["matched_fields"]) == {
        str(row["stmt_id"]) for row in r.data["rows"]}, r.meta["matched_fields"]
    assert all(set(v) <= {"label", "statement_full"} for v in r.meta["matched_fields"].values())


# ===================================================== b 反真空：恢复 casefold ⇒ 红
def _casefold_fields(row, names, wanted) -> list[str]:
    """统一前的 statements 实现（`casefold` 裸子串）—— 只用于反真空。"""
    return [name for name in names
            if any(raw.casefold() in str(row.get(name) or "").casefold()
                   for raw, _norm in wanted)]


def test_b_restoring_casefold_makes_the_agreement_criterion_red(env, monkeypatch) -> None:
    """b：把 statements 分支换回 `casefold` ⇒ 一致性判据必须红（本判据不是恒真的）。

    负控用统一前实测到不一致的那两问：全角 `Ｐ 阶元`（工具层 0 / 查口 1）与
    `noether，环`（工具层 0 / 查口 1）。若换回 casefold 之后两边仍然一致，
    说明 a 的"一致"不是因为共用判据，而是因为这条判据根本没在比东西（真空）。
    """
    store, reg = env
    monkeypatch.setattr(TT, "_statement_matched_fields", _casefold_fields)
    disagreements = []
    for query in ("Ｐ 阶元", "noether，环"):
        if _search_ids(reg, query) != _ledger_ids(store, query):
            disagreements.append(query)
    assert disagreements, (
        "恢复 casefold 后，a 的一致性判据仍然全绿 —— 那条判据是真空的"
        "（它没有真的在比两处的命中集）")
    # 每一问都要红，不是"碰巧一问不同"。
    assert set(disagreements) == {"Ｐ 阶元", "noether，环"}, disagreements


# ===================================================== c 非 statements 表不变
def _old_algorithm_rows(table: str, rows, query: str, fields=None) -> list[str]:
    """统一前的通用算法（作为"不变"的对照物，不是被测实现）。"""
    scanned = list(fields) if fields else TT._scalar_str_fields(table)
    needle = query.casefold()
    out: list[str] = []
    id_field = TT._spec_of(table)["id_field"]
    for row in rows:
        hit = False
        for name in scanned:
            val = row.get(name)
            if isinstance(val, str) and needle in val.casefold():
                hit = True
            elif isinstance(val, (list, tuple)) and any(
                    isinstance(x, str) and needle in x.casefold() for x in val):
                hit = True
        if hit:
            out.append(str(row.get(id_field) or ""))
    return sorted(out)


@pytest.mark.parametrize("case", ("literature", "research_questions"))
def test_c_other_tables_keep_the_generic_casefold_search(env, case: str) -> None:
    """c：非 statements 表仍是"casefold 子串 + 全部标量字符串字段"（逐行对拍）。"""
    store, reg = env
    if case == "literature":
        created = reg.call("table.create", role="A", table="literature", row={
            "title": "An ABELIAN group survey", "type": "J", "summary": "群论综述",
            "path": "000001/abelian.pdf", "doi": "10.1000/ABC", "venue": "J. Algebra"})
    else:
        created = reg.call("table.create", role="A", table="research_questions", row={
            "question": "有限群是否有 p 阶元？", "origin": "topic", "priority": "high"})
    assert created.ok, created.error
    rows = store.rows(case)
    assert rows, f"{case} 没铺上 ⇒ 这一组比较是空的"
    for query in ("ABELIAN", "有限群", "000001/abelian.pdf"):
        r = reg.call("table.search", role="B", table=case, query=query)
        assert r.ok, r.error
        got = sorted(str(row.get(TT._spec_of(case)["id_field"]) or "") for row in r.data["rows"])
        assert got == _old_algorithm_rows(case, rows, query), (
            f"{case} 上查询 {query!r} 的通用搜索行为变了（统一只该动 statements）")
        assert r.data["fields"] == TT._scalar_str_fields(case), r.data["fields"]
    # 全角查询在非 statements 表上仍然不命中（casefold 不折全角）—— 统一没有外溢。
    full_width = reg.call("table.search", role="B", table=case, query="Ｇ")
    assert full_width.ok and full_width.data["total"] == 0, full_width.data


# ===================================================== d 返回形状不变
def test_d_the_tool_result_shape_is_unchanged(env) -> None:
    """d：`data` / `meta` 键集、`select` 投影、`limit` / `truncated` 与改前一致。"""
    _, reg = env
    r = reg.call("table.search", role="B", table="statements", query="有限群")
    assert set(r.data) == {"table", "query", "fields", "rows", "total", "returned"}, sorted(r.data)
    assert set(r.meta) == {"table", "total", "returned", "matched_fields", "truncated"}, sorted(r.meta)
    full = next(row for row in r.data["rows"] if row.get("label") == "P 阶元")
    assert "proof_text" in full and "statement_text" in full, "整行形态变了（缺字段）"

    sel = reg.call("table.search", role="B", table="statements", query="有限群",
                   select=["stmt_id", "label"])
    assert set(sel.data["rows"][0]) == {"stmt_id", "label"}, sel.data["rows"][0]
    assert sel.meta["select"] == ["stmt_id", "label"], sel.meta

    page = reg.call("table.search", role="B", table="statements", query="有限群", limit=1)
    assert page.data["total"] == 2 and page.data["returned"] == 1, page.data
    assert page.meta["truncated"] is True, page.meta


# ===================================================== e 空查询 / f 非内容字段
def test_e_a_query_with_nothing_to_compare_is_refused_not_zero_hits(env) -> None:
    """e：归一后为空的查询 ⇒ 受控拒绝（与查口的 `checked=False` 同义：不是一问）。"""
    store, reg = env
    r = reg.call("table.search", role="B", table="statements", query="，。 ")
    assert not r.ok, r.data
    assert str((getattr(r, "meta", None) or {}).get("kind")) == "param_error", r.meta
    assert "这一问不成立" in str(r.error), r.error
    kw = SL.by_keywords(store, keywords=["，。 "])
    assert kw["checked"] is False and kw["hits_total"] == 0, kw


def test_f_a_non_content_field_is_refused_with_the_way_out(env) -> None:
    """f：显式点名内容面之外的列 ⇒ 受控拒绝 + 指路；内容面子集照常工作。"""
    _, reg = env
    bad = reg.call("table.search", role="B", table="statements", query="p^a",
                   fields=["proof_text"])
    assert not bad.ok, bad.data
    assert str((getattr(bad, "meta", None) or {}).get("kind")) == "param_error", bad.meta
    body = str(bad.error)
    assert "proof_text" in body and "table.list" in body and "table.get" in body, body

    # 正控：内容面的子集照常搜（`p^a` 只在 statement_full 里）。
    only_full = reg.call("table.search", role="B", table="statements", query="p^a",
                         fields=["statement_full"])
    assert only_full.ok and only_full.data["total"] == 1, only_full.data
    only_label = reg.call("table.search", role="B", table="statements", query="p^a",
                          fields=["label"])
    assert only_label.ok and only_label.data["total"] == 0, only_label.data
