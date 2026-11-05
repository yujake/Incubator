# -*- coding: utf-8 -*-
"""B 的登记回执必须说清"依赖边 N 条（其中命题→命题 M 条）"（缺陷 1c 的 B 半边）。

## 现场（`temp/dep_probe/REPORT-dependency-surface.md` 第三节 B 表）

盘上五个工作区的 `dependencies` 一共 3 行、`source_stmt_id` 非空 0 行 —— 边全是文献
来的。改前 B 的回执只有 `deps_written` 一个数（"这一笔落了几条"），于是 N=3、M=0 与
N=3、M=3 在回执上长得一模一样：读的人看不出"这条定理在依赖图上有没有上游"。

## 口径

- 回执里一行逐字 `依赖边 N 条（其中命题→命题 M 条）`（N = 这一笔写完之后台账里的边数，
  M = 其中 `source_stmt_id` 非空的那几条）；
- 同一句同时出现在 `note`（人读的那一行）与 `deps_missing.deps_receipt`（机器读的那一格）；
- 0 条也要写出来（写 0 条与写 5 条不许同价）；没有依赖面的出口（受控拒绝）不编这一行。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.store import Store


def _store(tmp_path: pathlib.Path) -> Store:
    ws = pathlib.Path(tmp_path) / "ws"
    Store(ws).init(force=True)
    return Store(ws)


def _manuscript(body: str, dep_rows: str = "") -> str:
    """一份框架渲染过的手稿（B 现在要求稿随正文一起来，缺稿整笔拒）。"""
    return DS.mark_washed(
        "## 证明\n\n" + body + "\n\n## 依赖\n\n"
        "| 引用 | 命题号 | 用在哪一步 | 路径号 |\n|---|---|---|---|\n" + dep_rows,
        actor="secretary-F")


def _add_theorem(store: Store, stmt_id: str) -> None:
    """落一条已经站到 `proof_review` 级的在册命题（引用门槛要的就是这一档）。

    先按 `heuristic` 写行，再走真的签口把它签上去（`conftest.sign_for_the_gate`）——
    直接写 `evidence_kind="proof_review"` 会被 `Store.upsert` 的"自称被审过"闸拒掉，
    而那正是这一档要守的东西。
    """
    from conftest import sign_for_the_gate

    proof = f"命题 {stmt_id} 的证明正文（判据夹具）。"
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=f"在册命题 {stmt_id}", statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文。",
        proof_text=proof,
        evidence_kind="heuristic", status="active", quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B")
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    sign_for_the_gate(store.root, statement_id=stmt_id, proof_text=proof, store=store)


def _register(store: Store, *, statement_full: str, body: str,
              dep_rows: str = "", derived_from: list[str] | None = None) -> dict:
    """登记一条命题（先按正文 sha 落一份 pending 签 —— 2026-11-02 起的准入闸要它）。"""
    from conftest import sign_before_registration

    sign_before_registration(store.root, proof_text=body)
    return AgentB(store, extractor=None, extract_text=None, config={}).register_statement(
        statement_full=statement_full, statement_text=statement_full[:20],
        origin="own_result", kind="conjecture", doc_id=S.format_id(0),
        quote_reason="我方自产命题（判据夹具）：没有外部引文要比对",
        proof_text=body,
        proof_manuscript=_manuscript(body, dep_rows),
        derived_from=list(derived_from or []),
    )


def test_a_registration_with_no_edge_still_says_zero_zero(tmp_path):
    """正控（0 条也要可见）：空依赖表 ⇒ `依赖边 0 条（其中命题→命题 0 条）`。"""
    store = _store(tmp_path)
    got = _register(store, statement_full="引理 A：自足的一条。", body="1. 直接验证。")
    assert got.get("ok") is True, got
    assert int(got.get("deps_written") or 0) == 0, got
    line = "依赖边 0 条（其中命题→命题 0 条）"
    assert line in str(got.get("note") or ""), got.get("note")
    assert line == str((got.get("deps_missing") or {}).get("deps_receipt") or ""), \
        got.get("deps_missing")


def test_a_statement_to_statement_edge_is_counted_separately(tmp_path):
    """正控：手稿的 `## 依赖` 表引了一条在册命题 ⇒ 那一条算"命题→命题"。"""
    store = _store(tmp_path)
    _add_theorem(store, S.format_id(0))
    got = _register(
        store, statement_full="引理 C：由在册命题推出。", body="1. 由在册命题直接推出。",
        dep_rows=f"| 由引理甲 | stmt:{S.format_id(0)} | 第 1 步 | 1 |\n")
    assert got.get("ok") is True, got
    total = int(got.get("deps_written") or 0)
    from_stmt = int(got.get("deps_stmt_edges") or 0)
    assert total >= 1, got
    assert from_stmt >= 1, (
        f"手稿的表里引的是 `stmt:{S.format_id(0)}`，却被数成 {from_stmt} 条命题→命题：{got}")
    line = f"依赖边 {total} 条（其中命题→命题 {from_stmt} 条）"
    assert line in str(got.get("note") or ""), got.get("note")
    assert line == str((got.get("deps_missing") or {}).get("deps_receipt") or ""), \
        got.get("deps_missing")


def test_a_refusal_has_no_dependency_receipt(tmp_path):
    """负控：受控拒绝没有依赖面 ⇒ 回执里不许编一个"依赖边 0 条"。"""
    store = _store(tmp_path)
    got = AgentB(store, extractor=None, extract_text=None, config={}).register_statement(
        statement_full="引理 D：没有稿的一条。", statement_text="引理 D",
        origin="own_result", kind="conjecture", doc_id=S.format_id(0),
        quote_reason="我方自产命题（判据夹具）：没有外部引文要比对",
        proof_text="证明正文（判据夹具）。",
    )
    assert got.get("ok") is False, got
    assert "依赖边" not in str(got.get("note") or got.get("error") or ""), got
    assert not (got.get("deps_missing") or {}).get("deps_receipt"), got.get("deps_missing")
