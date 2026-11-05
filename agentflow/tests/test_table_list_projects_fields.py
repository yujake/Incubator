# -*- coding: utf-8 -*-
"""`table.list` / `table.search` 的字段投影：F 查台账不该像读整本书。

## 现场（`temp/dep_probe/REPORT-dependency-surface.md` 第 4 条，2026-11-05 实测）

50 行 `statements` 的 `table.list` = 250 KB（`proof_text` 全文就在行里），
而 F 唯一便宜的清单是每轮第 4.1 段（最多 20 条、只收 `proof_review` 及以上）。
于是「查得到」与「顺手」之间差的正是这一格：有搜索、没有浏览 ——
想看一眼台账里有什么，代价是 250 KB 级。

## 口径（本文件逐条钉住）

- 给了投影 ⇒ 每行只有那几个键（多一个都不行，`proof_text` 不在其中）；
- 不给投影 ⇒ 与改前逐字相同（整行 + `statements` 的派生格，meta 键也不变）；
- 名字写错 ⇒ 受控拒绝（`param_error` ＋ 可用字段），不静默少一格；
- 命名分歧：`table.list` 用 `fields`，`table.search` 的 `fields` 已经是「搜哪些字段」
  ⇒ 它那一格叫 `select`（两者说的是同一件事：投影，只回这些键）。

反真空（②c）：把投影实现成「过滤后仍附整行」⇒ `set(row) == set(fields)` 那几条红。
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import table_tools as TT

TS = "2026-11-05T10:00:00+08:00"
#: 一条证明正文的正文长度（真机一份 2700–6300 字）：投影省下来的正是它。
PROOF_CHARS = 6000
FIELDS = ["stmt_id", "label", "kind", "evidence_kind"]


def _statement_row(no: int) -> dict:
    sid = f"{no:06d}"
    return {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": f"引理 {sid}", "statement_text": f"引理 {sid} 的陈述",
        "statement_full": f"引理 {sid} 的陈述全文。",
        "proof_text": "证明：" + ("这一步由前一步直接推出。" * (PROOF_CHARS // 14)),
        "quote_reason": "我方自产命题", "evidence_kind": "proof_review",
        "status": "active", "bits": {}, "created_at": TS, "created_by": "test",
    }


def _ws(root: pathlib.Path, rows: int = 5) -> pathlib.Path:
    """一个 `statements` 有 `rows` 行（每行带 PROOF_CHARS 字正文）的工作区。"""
    root = pathlib.Path(root)
    Store(root).init(force=True)
    path = root / "data" / str(S.TABLES["statements"]["file"])
    path.write_bytes((json.dumps(
        {"schema_version": 2, "rows": [_statement_row(i) for i in range(rows)]},
        ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return root


@pytest.fixture()
def env(tmp_path):
    """`(registry, store)`：判据要同时用"工具面"与"门店里的原行"两边对照。"""
    ws = _ws(tmp_path / "ws")
    store = Store(ws)
    return build_registry(store=store, workspace_root=ws).registry, store


@pytest.fixture()
def reg(env):
    return env[0]


def _size(data) -> int:
    return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))


# ============================================================ a 带投影：只有那几个键
def test_list_with_fields_returns_exactly_those_keys(reg):
    """a（正控）：`table.list(fields=...)` 每行只有那四个键，且不含 `proof_text`。"""
    r = reg.call("table.list", role="B", table="statements", fields=FIELDS)
    assert r.ok, r.error
    rows = r.data["rows"]
    assert len(rows) == 5, rows
    for row in rows:
        assert set(row) == set(FIELDS), (
            f"投影没生效：多出来的键 {sorted(set(row) - set(FIELDS))}"
            f"／少了的键 {sorted(set(FIELDS) - set(row))}")
        assert "proof_text" not in row, "投影行里还带着 proof_text 全文"
    # 体积：投影后必须显著小于整行（这就是"顺手"那件事的机器读数）。
    assert _size(r.data) * 10 < _size(reg.call(
        "table.list", role="B", table="statements").data), (
        f"投影 {_size(r.data)}B 与整行 {_size(reg.call('table.list', role='B', table='statements').data)}B "
        "差不多大 ⇒ 投影没省下东西")


def test_search_with_select_returns_exactly_those_keys(reg):
    """a（正控，search 那一格叫 `select`）：只回投影的键，不含 `proof_text`。"""
    r = reg.call("table.search", role="B", table="statements", query="引理", select=FIELDS)
    assert r.ok, r.error
    rows = r.data["rows"]
    assert rows, "搜索一条都没命中 ⇒ 这条判据是真空的"
    for row in rows:
        assert set(row) == set(FIELDS), (
            f"投影没生效：多出来的键 {sorted(set(row) - set(FIELDS))}")
        assert "proof_text" not in row
    # 反真空（③c 的同一件事）：不加 `select` 时它就是整行 —— 两档必须长得不一样。
    plain = reg.call("table.search", role="B", table="statements", query="引理")
    assert set(plain.data["rows"][0]) > set(FIELDS), plain.data["rows"][0].keys()


# ============================================================ b 不带投影：与今天逐字相同
def test_list_without_fields_is_the_same_row_as_before(env):
    """b（负控）：不给投影 ⇒ 仍是整行 + `statements` 的派生格，data 的键也一个不多。

    守住的是"默认形态不许被悄悄改掉"：这条断言的两边都按改前的实现算
    （`_rows` 原样 ＋ `_with_proof_routes`），投影那一笔若顺手动了默认路径，它立刻红。
    """
    reg, store = env
    r = reg.call("table.list", role="B", table="statements", limit=2)
    assert r.ok, r.error
    assert set(r.data) == {"table", "rows", "total", "returned", "limit", "offset"}, sorted(r.data)
    raw = TT._rows(TT.TableContext(store=store), "statements")[:2]
    expected = [TT._with_proof_routes("statements", row) for row in raw]
    assert r.data["rows"] == expected, "不带 fields 的默认形态变了"
    assert "proof_text" in r.data["rows"][0], "默认形态里 proof_text 没了（那不是投影该管的事）"


def test_search_without_select_is_the_same_row_as_before(env):
    """b（负控，search）：不给投影 ⇒ 行的键与门店里的原行一模一样。"""
    reg, store = env
    r = reg.call("table.search", role="B", table="statements", query="引理", limit=2)
    assert r.ok, r.error
    assert set(r.data) == {"table", "query", "fields", "rows", "total", "returned"}, sorted(r.data)
    stored = TT._rows(TT.TableContext(store=store), "statements")
    by_id = {str(row["stmt_id"]): row for row in stored}
    for row in r.data["rows"]:
        assert row == by_id[str(row["stmt_id"])], "不带 select 的默认形态变了"


# ============================================================ c 名字写错：可读拒信
def test_a_misspelled_projection_name_is_a_readable_refusal(reg):
    """c：投影名认不出 ⇒ `param_error` ＋ 可用字段（不静默少一格、也不回空行）。"""
    r = reg.call("table.list", role="B", table="statements", fields=["stmt_id", "nope"])
    assert not r.ok, r.data
    meta = getattr(r, "meta", None) or {}
    assert str(meta.get("kind")) == "param_error", meta
    assert "nope" in str(r.error), r.error
    assert "stmt_id" in str(r.error), "拒信里必须带可用字段，否则调用方没法自纠"

    r2 = reg.call("table.search", role="B", table="statements", query="引理", select=["nope"])
    assert not r2.ok, r2.data
    assert str((getattr(r2, "meta", None) or {}).get("kind")) == "param_error", r2.meta


def test_an_empty_projection_is_refused_not_an_empty_row(reg):
    """c2：空投影 `fields=[]` 是"把整行删光"，不是"省略投影" ⇒ 受控拒绝。"""
    r = reg.call("table.list", role="B", table="statements", fields=[])
    assert not r.ok, r.data
    assert str((getattr(r, "meta", None) or {}).get("kind")) == "param_error", r.meta
