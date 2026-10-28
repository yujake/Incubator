# -*- coding: utf-8 -*-
"""判据：G 不许在没有研究成果的地基上成文（业主 2026-10-28 口径）。

## 业主逐字

> 「G写论文时能依赖的只有系统侧的研究成果（B侧原文或B侧有引用记录的其它角色的手稿与
> 参考文献），总之G写论文只能用研究产出，如果产出不足不可杜撰，应上报父代理要求扩大研究面。」

## 真机（`projects/paper-rewrite-78-backup`，2026-10-28）

M 在第 17 分钟派 G 写正文，那一刻盘上是 `statements 0 / relations 0 / documents 0 /
literature 15（全是元数据、0 全文）`。G 写出 57KB `main.tex` 并编成 PDF —— 它不是伪造证明
（硬口径是"原稿的主张只能写成 the source manuscript claims"），但那份稿子没有一条命题、
一份手稿、一篇可引文献在下面托着。提示词里早有"落定才成文"，模型读了也照写 ⇒ 这一条
必须是判据。

## 这一组守什么

1. 空台账 ⇒ 拒绝成文：`doc.write_mapping` 受控拒绝（`kind=no_evidence_chain`），
   而且一个字节都不写（没有 MAPPING.json）；
2. "有命题但没证明"也是产出不足：登记了标题不等于有原料（这一档是判据的牙齿：
   把门放宽成"statements>0 就放行"，它就红）；
3. 拒绝要给出路：`next_steps` 非空，且逐字包含"扩大研究面"与"不许杜撰"；
4. 三态：台账读不到 ⇒ `ledger_unreadable`（不是"研究成果够用"，也不是"没有成果"）；
5. 正控：有一行带 `proof_text` 的命题 ⇒ 这道门不拦（它可能因别的理由失败，但
   `kind` 不许是 `no_evidence_chain`）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow.researchbase import RESEARCH_BASE_STATES, research_base
from agentflow.store import Store
from agentflow.tools import doc_tools
from agentflow.tools.base import ToolRegistry

TS = "2026-10-28T12:00:00+08:00"


# ---------------------------------------------------------------- 夹具


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    # `doc.write_mapping` 只写 `<项目根>/out/paper/`；项目根要真的存在。
    (st.root / "projects" / "p1" / "out" / "paper").mkdir(parents=True, exist_ok=True)
    (st.root / "projects" / "p1" / "out" / "paper" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n正文\n\\end{document}\n", encoding="utf-8")
    return st


def _statement(st: Store, stmt_id: str, *, proof: str = "", verified: bool | None = None,
               source_lit_id: str | None = None) -> None:
    # `quote_verified` 与 `quote_reason` 是一对：`None` 也要写清"为什么还没校验"
    # （`Statement.validate` 的硬约束：只留一个空字段等于把"没查"记成没人能接手的账）。
    reason = "逐字比对通过" if verified is True else "还没校验：这一条没有可比的全文"
    stmt = S.Statement(
        # `external_lit` 必须给 `source_lit_id`（`Statement.validate`）；这里要测的是
        # "有没有可依赖的成果"，与出处无关 ⇒ 用自产那一路（`own_result`）。
        stmt_id=stmt_id, origin="own_result", kind="theorem", label=f"Theorem {stmt_id}",
        statement_text="命题短版", statement_full="若假设 A 成立，则结论 B 成立",
        proof_text=proof, source_lit_id=source_lit_id,
        quote_verified=verified, quote_reason=reason,
        evidence_kind="cross_check", status="active", created_at=TS)
    stmt.validate()
    with st.tx("statements", actor="test", note="stmt probe") as tx:
        tx.upsert("statements", stmt.to_dict(), note="stmt probe")


def _registry(st: Store) -> ToolRegistry:
    reg = ToolRegistry(name="g-paper-gate")
    reg.bound_role = "G"
    doc_tools.register(reg, store=st, workspace=st.root)
    return reg


def _rows() -> list[dict]:
    """一份形状合法的对应表（门在后、解析在前；这里给的是"能把表写出来"的最小行）。"""
    return [{"kind": "theorem", "label": "Theorem 0.1", "env_no": 1,
             "ledger_id": "stmt:000000", "proof_no": 1, "file": "proofs/t1.md"}]


def _write_mapping(st: Store) -> object:
    return _registry(st).call("doc.write_mapping", project="projects/p1", rows=_rows())


# ---------------------------------------------------------------- 1) 空台账


def test_a_paper_cannot_be_written_on_an_empty_ledger(tmp_path: pathlib.Path):
    """空台账 ⇒ 受控拒绝，且一个字节都不写。"""
    st = _store(tmp_path)
    res = _write_mapping(st)
    assert res.ok is False, res.data
    assert res.meta.get("kind") == "no_evidence_chain", res.meta
    assert res.meta.get("written") is False, res.meta
    paper = st.root / "projects" / "p1" / "out" / "paper"
    assert not (paper / "MAPPING.json").exists(), "门拒了却把表写出来了"
    base = res.meta.get("research_base") or {}
    assert base.get("state") == "insufficient", base
    assert base.get("statements") == 0, base


def test_a_title_without_a_proof_is_still_not_a_research_output(tmp_path: pathlib.Path):
    """有 1 条命题、但没有证明正文也没有可核引文 ⇒ 仍是产出不足（判据的牙齿）。"""
    st = _store(tmp_path)
    _statement(st, "000000")            # 只有标题：proof 空、quote_verified 空
    res = _write_mapping(st)
    assert res.meta.get("kind") == "no_evidence_chain", res.meta
    base = res.meta.get("research_base") or {}
    assert base.get("statements") == 1 and base.get("with_proof") == 0, base
    assert base.get("verified_quotes") == 0, base
    assert any("proof_text" in m for m in base.get("missing") or []), base.get("missing")


# ---------------------------------------------------------------- 2) 拒绝要给出路


def test_the_refusal_says_how_to_widen_the_research_and_forbids_invention(tmp_path: pathlib.Path):
    """拒绝必须给出路：点名"扩大研究面"与"不许杜撰"，并指出正路（B 收录 / D 出稿）。"""
    st = _store(tmp_path)
    res = _write_mapping(st)
    steps = " ".join(res.meta.get("next_steps") or [])
    assert "扩大研究面" in steps, steps
    assert "杜撰" in steps, steps
    assert "B" in steps and "D" in steps, steps
    # `conductor.escalate` 是"上报父代理"的唯一入口，文案里要点名它
    assert "escalate" in steps, steps


# ---------------------------------------------------------------- 3) 三态


def test_an_unreadable_ledger_is_not_a_pass_and_not_an_empty_ledger(tmp_path: pathlib.Path):
    """台账读不到 ⇒ `ledger_unreadable`：既不是"够用"，也不是"没有成果"。"""
    st = _store(tmp_path)
    (st.root / "data" / "statements.json").write_text("{ 这不是 JSON", encoding="utf-8")
    res = _write_mapping(st)
    assert res.ok is False, res.data
    assert res.meta.get("kind") == "ledger_unreadable", res.meta
    assert res.meta.get("written") is False, res.meta
    base = res.meta.get("research_base") or {}
    assert base.get("checked") is False and base.get("state") == "unreadable", base


# ---------------------------------------------------------------- 4) 正控


def test_a_statement_with_proof_lets_the_gate_through(tmp_path: pathlib.Path):
    """正控（不许修过头）：有一行带 `proof_text` 的命题 ⇒ 这道门不拦。"""
    st = _store(tmp_path)
    _statement(st, "000000", proof="Proof. 由定义直接得到。", source_lit_id=None)
    res = _write_mapping(st)
    assert res.meta.get("kind") != "no_evidence_chain", res.meta
    base = research_base(st)
    assert base["state"] == "ready" and base["with_proof"] == 1, base


def test_the_base_reading_has_three_states_and_only_ready_is_green(tmp_path: pathlib.Path):
    """反真空：三档真的分得开（`ready` 只有一个入口：有证明或可核引文）。"""
    st = _store(tmp_path)
    assert research_base(st)["state"] == "insufficient"
    _statement(st, "000000")
    assert research_base(st)["state"] == "insufficient"
    _statement(st, "000001", verified=True)
    assert research_base(st)["state"] == "ready"
    assert set(RESEARCH_BASE_STATES) == {"ready", "insufficient", "unreadable"}
    assert json.dumps(research_base(st), ensure_ascii=False)          # 可 JSON 化（进返回/事件）
