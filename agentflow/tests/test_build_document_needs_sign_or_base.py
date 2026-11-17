# -*- coding: utf-8 -*-
"""DOCGATE1 判据：`doc.build_document` 也必须过成文门（与 `doc.write_mapping` 同一处判据）。

## 真机现场（INV1 取证，`temp/inv1/REPORT-inv1.md` §2；`projects/lp-ball-6`）

19:39:43 M 的 `conductor.patrol` 读数逐字是「statements_unsigned×1；manuscript_missing×1…
下一动作：未签稿要补签」；18 秒后（19:40:01）M 把 G 派到 `doc.build_document`，
G 于 19:42:33 落 `doc:000000`，而全趟第一份 V 签在 19:43:40 —— 成文比签早 67 秒。

当时 `statements` 35 行、`proof_text` 非空 0 行、`quote_verified=true` 0 行、`out/vsigns/` 0 份。
全系统唯一的成文硬闸（`researchbase.research_base` 派生的 `no_evidence_chain`）只装在
`doc.write_mapping`；G 走的那个入口一道与"签/地基"有关的判据都没有 ⇒ 本判据把同一处判据
接到 `doc.build_document` 上（不复制一份：两个入口都调 `researchbase`）。

## 这一组守什么

a) 零签且无有效地基 ⇒ `doc.build_document` 受控拒（`kind="no_evidence_chain"`），
   `documents` 一行不写、盘上一个字节不写；拒信里四项读数齐全（当前签数 / 待签稿数 /
   有效地基条数 / 缺哪一条）并点名「先拿签/先补地基，再来成文」；
b) 正控（不许一刀切）：有 ≥1 条有效地基 ⇒ 放行；有 ≥1 份签 ⇒ 放行（即使地基为 0）；
   而且研究手稿与论文包同一口径（`doc.write_mapping` 在这两档上也不得判 `no_evidence_chain`）；
c) 反真空：把这道闸打桩关掉（`researchbase.research_base` 恒 `ready`）⇒ a 那条场景真的写出
   一行 `documents` ⇒ a 的"拒"是这道闸给的，不是别的检查碰巧拒的；
d) 三态：`statements` 台账读不到 ⇒ `kind="ledger_unreadable"`（不是"没有成果"）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import researchbase as RB
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import doc_tools
from agentflow.tools.base import ToolRegistry

#: 事故现场前后的一秒（19:42:33 落文 / 19:43:40 第一份签）；用例里所有时间戳都写死。
TS = "2026-11-17T19:42:33+08:00"


# ---------------------------------------------------------------- 夹具


def _store(tmp_path: pathlib.Path) -> Store:
    """工作区（`data/` 在这里，`out/vsigns/`、`reports/` 也在这里）。"""
    st = Store(tmp_path / "ws")
    st.init()
    (st.root / "reports").mkdir(parents=True, exist_ok=True)
    return st


def _statement(st: Store, stmt_id: str, *, proof: str = "", verified: bool | None = None) -> None:
    """一行命题：`proof=""` + `verified=None` = "只登记了个标题"（真机那 35 行的形状）。"""
    reason = "逐字比对通过" if verified is True else "还没校验：这一条没有可比的全文"
    stmt = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem", label=f"Theorem {stmt_id}",
        statement_text="命题短版", statement_full="若假设 A 成立，则结论 B 成立",
        proof_text=proof, quote_verified=verified, quote_reason=reason,
        evidence_kind="cross_check", status="active", created_at=TS)
    stmt.validate()
    with st.tx("statements", actor="test", note="stmt probe") as tx:
        tx.upsert("statements", stmt.to_dict(), note="stmt probe")


def _manuscript(st: Store, name: str = "f-proof-000000.md") -> str:
    """`reports/` 里一份签载体（内容无关；`vsigns.is_sign_carrier` 只看名字与目录）。"""
    (st.root / "reports" / name).write_text("# 证明\n\n推导……\n", encoding="utf-8")
    return f"reports/{name}"


def _sign(st: Store, artifact_path: str, *, sha: str = "a" * 64) -> str:
    """按 `vsigns.issue` 写出的那份签文件的形状落一份签（`signed_table` 只认这两格对上）。"""
    d = st.root / "out" / "vsigns"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "vsign/1", "artifact_sha": sha, "artifact_path": artifact_path,
           "statement_id": "", "at": "2026-11-17T19:43:40", "verdict": "成立",
           "streak": 3, "need": 3, "ledger": "", "written_by": "secretary:F"}
    (d / f"{sha}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return sha


def _claims() -> list[dict]:
    """一份形状合法的断言（引用 `stmt:000000` —— 夹具里那条命题真的存在）。"""
    return [{"text": "两族闭式的坐标型推导在交叉验证下成立", "citations": ["stmt:000000"],
             "evidence_kind": "cross_check", "section": "1",
             "disclaimer": "数值交叉验证，不构成证明"}]


def _registry(st: Store) -> ToolRegistry:
    reg = ToolRegistry(name="docgate1")
    reg.bound_role = "G"
    doc_tools.register(reg, store=st, workspace=st.root)
    return reg


def _build(st: Store):
    return _registry(st).call("doc.build_document", kind="note", title="研究手稿",
                              claims=_claims())


# ---------------------------------------------------------------- a) 零签且无地基 ⇒ 受控拒


def test_a_zero_sign_and_no_base_is_refused_with_the_four_readings(tmp_path: pathlib.Path):
    """真机现场的最小重放：一条只有标题的命题 + 一份没签的稿 ⇒ 成文门受控拒。"""
    st = _store(tmp_path)
    _statement(st, "000000")
    _manuscript(st, "f-proof-000000.md")
    res = _build(st)

    assert res.ok is False, res.data
    assert res.meta.get("kind") == "no_evidence_chain", res.meta
    assert res.meta.get("written") is False, res.meta
    # 一行 documents 都不许落、盘上也不许多出一份 markdown
    assert st.rows("documents") == [], st.rows("documents")
    assert list((st.root / "documents").glob("*.md")) == [] if (st.root / "documents").is_dir() else True

    # 四项读数：当前签数 / 待签稿数 / 有效地基条数 / 缺哪一条
    msg = str(res.error or "")
    assert "签 0 份" in msg, msg
    assert "待签稿 1 份" in msg, msg
    assert "f-proof-000000.md" in msg, msg          # 缺哪一份稿，逐份点名
    assert "有效地基 0 条" in msg, msg
    assert "proof_text 非空 0 行" in msg and "quote_verified=true 0 行" in msg, msg
    # 下一步：点名"先拿签/先补地基，再来成文"
    assert "先拿签/先补地基，再来成文" in msg, msg
    assert "谁产出谁送审" in msg and "不许杜撰" in msg, msg

    base = res.meta.get("research_base") or {}
    assert base.get("state") == "insufficient", base
    assert base.get("statements") == 1 and base.get("effective") == 0, base
    sign = res.meta.get("signing") or {}
    assert sign.get("checked") is True and sign.get("signs") == 0, sign
    assert sign.get("pending") == 1 and sign.get("pending_manuscripts") == ["reports/f-proof-000000.md"], sign


def test_a_the_gate_reads_the_same_criterion_as_the_paper_package(tmp_path: pathlib.Path):
    """同一处判据：同一条读数（`researchbase`），`doc.write_mapping` 现在也判它。"""
    st = _store(tmp_path)
    _statement(st, "000000")
    _manuscript(st)
    base = RB.research_base(st)
    assert base["state"] == "insufficient", base
    assert (base.get("signing") or {}).get("signs") == 0, base


# ---------------------------------------------------------------- b) 正控：不许一刀切


def test_b_one_effective_statement_lets_the_gate_through(tmp_path: pathlib.Path):
    """有 ≥1 条有效地基 ⇒ 照旧放行（这道门不是"禁止成文"）。"""
    st = _store(tmp_path)
    _statement(st, "000000", proof="Proof. 由定义直接得到。")
    res = _build(st)
    assert res.ok is True, (res.error, res.meta)
    assert len(st.rows("documents")) == 1, st.rows("documents")


def test_b_one_sign_also_lets_the_gate_through(tmp_path: pathlib.Path):
    """有 ≥1 份 V 签 ⇒ 照旧放行，即使一条有效地基都没有（签是第二张门票）。"""
    st = _store(tmp_path)
    _statement(st, "000000")                       # 地基 0 条
    path = _manuscript(st)
    _sign(st, path)                                # 但已经有一份签
    res = _build(st)
    assert res.ok is True, (res.error, res.meta)
    assert len(st.rows("documents")) == 1, st.rows("documents")


def test_b_the_paper_package_uses_the_same_measure(tmp_path: pathlib.Path):
    """研究手稿与论文包同一口径：有一份签时 `doc.write_mapping` 也不得判 `no_evidence_chain`。"""
    st = _store(tmp_path)
    paper = st.root / "projects" / "p1" / "out" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n正文\n\\end{document}\n", encoding="utf-8")
    _statement(st, "000000")
    _sign(st, _manuscript(st))
    rows = [{"kind": "theorem", "label": "Theorem 0.1", "env_no": 1,
             "ledger_id": "stmt:000000", "proof_no": 1, "file": "proofs/t1.md"}]
    res = _registry(st).call("doc.write_mapping", project="projects/p1", rows=rows)
    assert res.meta.get("kind") != "no_evidence_chain", res.meta


# ---------------------------------------------------------------- c) 反真空


def test_c_the_refusal_is_this_gate_and_not_something_else(tmp_path: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch):
    """反真空：把这把闸打桩关掉（`research_base` 恒 ready）⇒ a 那个场景真的写得出来。

    没有这一条，a 的"拒"也可能来自别的检查（断言形状 / 引用不存在），而那道门
    在这里就变成了一句没人验证过的声明。
    """
    st = _store(tmp_path)
    _statement(st, "000000")
    _manuscript(st)

    monkeypatch.setattr(RB, "research_base", lambda *a, **k: {
        "checked": True, "state": "ready", "statements": 1, "with_proof": 0,
        "verified_quotes": 0, "effective": 0, "cited_literature": [], "cited_documents": [],
        "missing": [], "next_steps": [], "reason": "（打桩：这道门被关掉）",
        "signing": {"checked": True, "signs": 0, "pending": 1,
                    "signed_manuscripts": [], "pending_manuscripts": [], "problems": [], "why": ""},
    })
    res = _build(st)
    assert res.ok is True, (res.error, res.meta)
    assert len(st.rows("documents")) == 1, "闸关掉了却仍写不出 ⇒ a 的拒不是这道闸给的"


# ---------------------------------------------------------------- d) 三态


def test_d_an_unreadable_ledger_is_not_an_empty_ledger(tmp_path: pathlib.Path):
    """台账读不到 ⇒ `ledger_unreadable`：既不是"研究成果够用"，也不是"没有成果"。"""
    st = _store(tmp_path)
    (st.root / "data" / "statements.json").write_text("{ 这不是 JSON", encoding="utf-8")
    res = _build(st)
    assert res.ok is False, res.data
    assert res.meta.get("kind") == "ledger_unreadable", res.meta
    assert res.meta.get("written") is False, res.meta
    assert st.rows("documents") == []
    base = res.meta.get("research_base") or {}
    assert base.get("checked") is False and base.get("state") == "unreadable", base


# ---------------------------------------------------------------- 读数本体


def test_the_sign_reading_counts_signs_and_pending_manuscripts(tmp_path: pathlib.Path):
    """`signs_reading` 三档：没目录 ⇒ 0 份签（查过了）；有稿没签 ⇒ 待签 1；签了 ⇒ 待签 0。"""
    st = _store(tmp_path)
    got = RB.signs_reading(st)
    assert got["checked"] is True and got["signs"] == 0 and got["pending"] == 0, got

    path = _manuscript(st)
    got = RB.signs_reading(st)
    assert got["checked"] is True and got["signs"] == 0 and got["pending"] == 1, got

    _sign(st, path)
    got = RB.signs_reading(st)
    assert got["checked"] is True and got["signs"] == 1 and got["pending"] == 0, got


def test_a_non_carrier_manuscript_is_not_counted_as_pending(tmp_path: pathlib.Path):
    """`e-num` 不是签的载体（绿色通道）⇒ 不进"待签稿"那一格。"""
    st = _store(tmp_path)
    (st.root / "reports" / "e-num-000012.md").write_text("# 穷举\n", encoding="utf-8")
    got = RB.signs_reading(st)
    assert got["checked"] is True and got["pending"] == 0, got
