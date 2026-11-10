# -*- coding: utf-8 -*-
"""自产概念在 B 的动作面有入口（2026-11-10，业主亲跑概念彩排撞到的真洞）。

## 改前读数（真洞）

```
B 的模型面动作 `register_statement`（`specs/b.py` 声明 19 个参数）没有 `self_authored`，
而 `kind="concept"` 这条路上 `origin="own_result"` 被硬拒：
  {"ok": false, "kind": "concept_origin_refused",
   "error": "概念行的 origin 不许是 own_result：…确实是我们自己定义的新概念走秘书载荷的
             `self_authored` 那一档"}
⇒ 结论：自产概念（从零起的工作区，例如证明 DCT 时自己定义的「一致可积」）在 B 的
   动作面上没有入口。只有文献概念能登记。
```

底层能力一直在：`Secretary.write_concept_row(…, origin="own_result", self_authored=True)`
与 `conceptrows.concept_origin_problem`（`own_result` 必须显式 `self_authored=True`）
都支持，只是没接到 B 的动作参数上。本文件钉住接口那一格，判据本体不在这里抄第二份。

| # | 判据 | 反真空 |
|---|---|---|
| a | `kind=concept` + `origin=own_result` + `self_authored=True` ⇒ ok / 行落 / kind=concept / evidence_kind=heuristic / bits.grade=not_applicable | e：把 `self_authored` 传成常量 False ⇒ a 红 |
| b | 不给 `self_authored` ⇒ 仍 `concept_origin_refused`，零新行，拒信点名 `self_authored=True` | — |
| c | `self_authored=True` + `source_lit_id` ⇒ 受控拒（自相矛盾），零新行 | — |
| d | 自产概念登记 → B 落 b-稿 → V 三转签 → `ingest(apply, ["proof_text"])` ⇒ signed + 正文 == 稿那一节 | 未签 ⇒ `proof_without_v_sign` 零写（既有判据另有文件） |

零真实模型调用：`extractor=None`、签由 `_credential_fixture` 的真写口（三票 + `vsigns.issue`）
造；工作区全在 `tmp_path`，不读写 `projects/`。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import conceptrows as CR
from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow.agent_b import AgentB
from agentflow.extract import extract_text
from agentflow.store import Store

import conftest  # noqa: E402
from _credential_fixture import issue_credential  # noqa: E402

DEF = ("定义（一致可积，uniformly integrable）。给定概率空间上的随机变量族 {X_i}："
       "若对任意 ε>0 存在 K，使 sup_i E[|X_i|·1{|X_i|>K}] < ε，则称该族一致可积。")
WELLDEF = ("良定义性证明：\n"
           "1. 定义里的上确界取遍整个族，族非空 ⇒ 量词范围确定。\n"
           "2. 判定只依赖每个 X_i 的分布与一个公共的 K；给定族之后 K 的存在性唯一确定 "
           "⇒ 定义是良定义的。")
LABEL = "一致可积（uniformly integrable）"


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, AgentB(st, extractor=None, extract_text=extract_text, config={})


def _register(b: AgentB, **overrides) -> dict:
    args = dict(kind="concept", label=LABEL, origin="own_result",
                statement_full=DEF,
                line_range={"label": "self-defined: DCT 证明里自立的定义"},
                quote_reason="自产概念：定义就在这一行上，没有引文面可核")
    args.update(overrides)
    return dict(b.register_statement(**args))


def _rows(st: Store) -> int:
    return len([r for r in st.rows("statements") if r.get("status") != "superseded"])


def _row(st: Store, sid: str) -> dict:
    return next((dict(r) for r in st.rows("statements")
                 if str(r.get("stmt_id")) == sid), {})


# ================================================================ a 正控
def test_a_a_self_authored_concept_lands(tmp_path: pathlib.Path) -> None:
    """a：显式 `self_authored=True` ⇒ ok、行落、概念行的四格读数全对。"""
    st, b = _ws(tmp_path)
    assert _rows(st) == 0
    got = _register(b, self_authored=True)
    assert got.get("ok") is True, got
    sid = str(got.get("stmt_id") or "")
    assert sid, got
    assert _rows(st) == 1, "这一笔没有落成一行"

    row = _row(st, sid)
    assert row.get("kind") == "concept", row
    assert row.get("origin") == "own_result", row
    assert row.get("evidence_kind") == "heuristic", row
    bits = EB.bits_from_row(row)
    assert bits.get("grade") == "not_applicable", bits
    assert EB.derive_grade(bits, kind="concept") == "not_applicable", bits


# ================================================================ b 反控
def test_b_without_the_declaration_it_is_still_refused_with_zero_rows(
        tmp_path: pathlib.Path) -> None:
    """b：不传 `self_authored` ⇒ 仍 `concept_origin_refused`、零新行、拒信给改法。"""
    st, b = _ws(tmp_path)
    before = _rows(st)
    got = _register(b)  # 默认 False = 不声明
    assert got.get("ok") is False, got
    assert got.get("kind") == "concept_origin_refused", got
    assert "self_authored=True" in str(got.get("error") or ""), got.get("error")
    assert _rows(st) == before, "被拒的这一笔记了行"


# ================================================================ c 矛盾
def test_c_self_authored_with_a_literature_source_is_contradictory(
        tmp_path: pathlib.Path) -> None:
    """c：`self_authored=True` 又给 `source_lit_id` ⇒ 受控拒（判据取自 `conceptrows`）。"""
    st, b = _ws(tmp_path)
    conftest.write_library_file(st, "000000/a.txt", "dummy\n")
    conftest.add_literature(st, "000000", title="Dummy", path="000000/a.txt")
    before = _rows(st)
    got = _register(b, self_authored=True, source_lit_id="000000")
    assert got.get("ok") is False, got
    assert got.get("kind") == "concept_origin_refused", got
    assert "自相矛盾" in str(got.get("error") or ""), got.get("error")
    assert _rows(st) == before, "自相矛盾那一笔记了行"


# ================================================================ d 全链
def test_d_the_self_authored_concept_walks_the_same_chain(tmp_path: pathlib.Path) -> None:
    """d：登记 → 落 b-稿 → V 三转签 → 按位置与格收录 ⇒ 良定义证明 signed 且逐字相等。"""
    st, b = _ws(tmp_path)
    sid = str(_register(b, self_authored=True).get("stmt_id") or "")
    assert sid

    landed = b.land_manuscript(statement_id=sid, proof_text=WELLDEF)
    assert landed.get("ok") is True, landed
    rel = str(landed.get("path") or "")
    assert rel == f"reports/b-proof-{sid}.md", rel

    issue_credential(st.root, proof_text=WELLDEF, statement_id=sid,
                     manuscript=rel, proof_no=1)
    body = DS.proof_body(
        (pathlib.Path(st.root) / rel).read_text(encoding="utf-8"))

    ing = dict(b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                                   cells=["proof_text"], mode="apply"))
    assert ing.get("ok") is True, ing
    assert ing.get("refused") in ("", None), ing
    assert str((ing.get("well_definedness") or {}).get("state")) == "signed", ing

    row = _row(st, sid)
    assert str(row.get("proof_text") or "").strip() == str(body or "").strip(), row
    assert str(row.get("proof_text") or "").strip(), "收录之后正文仍空"
    reading = CR.well_definedness_reading(st.root, row, manuscript_path=rel, store=st)
    assert reading.get("state") == "signed", reading
    assert EB.bits_from_row(row).get("reviewed") is True, EB.bits_from_row(row)


# ================================================================ e 反真空
def test_e_forcing_the_declaration_to_false_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把 `self_authored` 传成常量 False ⇒ 同一个 a 必须红（参数真的在起作用）。"""
    st, b = _ws(tmp_path)
    real = AgentB.register_statement

    def _forced_false(self, **kw):
        kw["self_authored"] = False
        return real(self, **kw)

    monkeypatch.setattr(AgentB, "register_statement", _forced_false)
    before = _rows(st)
    got = _register(b, self_authored=True)
    assert got.get("ok") is False, (
        "把声明打成常量 False 之后仍然放行 ⇒ 这条判据没有牙")
    assert got.get("kind") == "concept_origin_refused", got
    assert _rows(st) == before, "反真空那一笔记了行"
