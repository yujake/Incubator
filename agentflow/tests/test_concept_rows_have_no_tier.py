# -*- coding: utf-8 -*-
"""D15'：概念 / 定义行的非平凡度落"不适用"，与"未判"是两个词。

## 真机证据（`projects/mp3-r3`，2026-10-26）

```
非平凡度账本 out/secretary/nontriviality.jsonl 里 3 条，其中 concept 一条都没有
（按设计概念不判力气）—— 但读侧只有一个"未判"，分不清"没判"与"不需要判"
```

概念行没有证明正文（`conceptrows.concept_statement` 明令 `proof_text` 留空），
于是四项力气读数一项都取不到。改前这一档的处置是"不落台账 / 落一条 None"，
而读侧对"没有记录"与"不需要记录"印同一个词 —— 于是"结构上不用判"看起来像"漏判了"。

## 四条判据

| 条 | 它要证明的事 | 改前为什么是红的 |
|---|---|---|
| a | 判档那一层对概念行落一条可判的读数：`level=null` + `basis="不适用：概念行没有证明正文，不做力气判档"` + `applicable=False` | 改前概念行一条记录都没有（`nontriviality.jsonl` 里没有它） |
| b | 读侧把两者印成两个词：不适用 ⇒ `不适用`，判不了 ⇒ `未判`；有档位 ⇒ `T0`…`T4`（三个词不折平） | 改前两者都是"未判" |
| c | 正控：概念行一次模型调用都不发（判档那一步对 concept 早退，`seam.calls == []`） | 这一条改前改后都该绿（护栏：早退不许顺手把调用放进来） |
| d | 反真空：把"不适用"打桩成 None（= 不落那一档）⇒ b 必红 | 它证明 b 的绿是那一条读数带来的 |

## 边界

全部 tmp 工作区、零真实模型调用、不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from agentflow import conceptrows as CR
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

#: 一条概念（定义就在正文里，没有证明）。
CONCEPT_LABEL = "有限维李代数"
CONCEPT_DEF = ("概念（有限维李代数）：设 K 为特征 0 的域，g 为 K 上的 Lie 代数；"
               "称 g 有限维，若 dim_K g < ∞。")

#: 一条真的命题（用来做负控：它的档位照旧是 T0–T4）。
THEOREM = "设 G 是有限 p-群，则 G 的中心非平凡。"


class _Seam:
    """一只只数调用次数的假模型缝（概念这一档一次都不该碰它）。"""

    class _Call:
        def __init__(self) -> None:
            self.ok, self.problem, self.detail = True, "", ""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def ask_json(self, prompt, **kw):
        self.calls.append(str(kw.get("note") or ""))
        return {}, self._Call()


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _concept(sec: Secretary) -> dict:
    """经秘书正常登记一条概念（返回落盘那一行）。"""
    out = sec.record_statement(
        {"statement_full": CONCEPT_DEF, "label": CONCEPT_LABEL,
         "statement_text": CONCEPT_LABEL, "kind": "concept", "origin": "own_result",
         "self_authored": True, "doc_id": S.format_id(0)}, role="B")
    assert out.get("checked") is True and out.get("created") is True, out
    sid = str(out.get("stmt_id") or "")
    return next(dict(r) for r in sec.store.rows("statements")
                if str(r.get("stmt_id") or "") == sid)


def _ledger(root: pathlib.Path) -> list[dict]:
    path = SEC.nontriviality_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# ============================================================ a) 写侧落一条可判的"不适用"

def test_a_concept_row_lands_a_not_applicable_reading(tmp_path: pathlib.Path) -> None:
    """a：概念行在旁支台账里落一条 `level=null` + `applicable=False` + 那句 basis。

    改前红：这一行根本不存在 —— 概念行从不过判档那一层（真机 mp3-r3 的 30 条概念行
    在 `out/secretary/nontriviality.jsonl` 里一条记录都没有）。
    """
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    row = _concept(sec)
    rows = _ledger(st.root)
    hit = [r for r in rows
           if str(r.get("statement_sha256") or "") == SEC._statement_sha(CONCEPT_DEF)]
    assert hit, f"概念行没落档位台账：{rows}"
    last = hit[-1]
    assert last.get("nontriviality") is None, last
    assert str(last.get("label") or "") == "", last
    assert last.get("applicable") is False, last
    assert str(last.get("basis") or "") == SEC.NONTRIVIALITY_NOT_APPLICABLE_BASIS, last
    assert "没有证明正文" in str(last.get("basis") or ""), last
    assert str(last.get("basis") or "") != "", last
    # 读侧的唯一读口也认这一档（不是只有台账里写着）
    got = SEC.nontriviality_of(st.root, str(row.get("statement_full") or ""))
    assert got.get("tri") == "not_applicable", got
    assert got.get("applicable") is False and got.get("level") is None, got


def test_a_concept_written_through_the_merge_layer_lands_it_too(store: Store) -> None:
    """a（第二条写口）：`conceptrows` 那条路（真机 mp3 的写侧）也落这一条读数。"""
    legacy = {"concept_id": "0000", "name": CONCEPT_LABEL, "definition": CONCEPT_DEF,
              "aliases": [], "related_concepts": []}
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.upsert_legacy_shaped(tx, legacy, actor="agent-B")
    rows = _ledger(pathlib.Path(store.root))
    assert any(r.get("applicable") is False for r in rows), rows
    # 而且那一行本身也在（这一条读数说的是它，不是一个空对象）
    assert [r.get("kind") for r in store.rows("statements")] == ["concept"]


def test_a_row_written_before_this_change_is_healed_on_its_next_touch(store: Store) -> None:
    """a（存量那一半）：改前直写进来的概念行，在它下一次经秘书时被补上那一格。

    存量行不在这一批的重写范围里（"零迁移"）：它盘上没有那一条读数，读侧只能给"未判"。
    但这一格是幂等的 —— 同号同步一次就补上，于是"补齐"不需要一次全库迁移脚本。
    """
    row = {"stmt_id": "0000", "origin": "own_result", "kind": "concept",
           "label": CONCEPT_LABEL, "statement_text": CONCEPT_DEF,
           "statement_full": CONCEPT_DEF, "proof_text": "", "quote_verified": None,
           "quote_reason": "改前那一笔的样子（没有证明、bits 空）",
           "evidence_kind": "heuristic", "status": "active", "aliases": [],
           "created_at": S.now_iso(), "created_by": "agent-B", "bits": {}}
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        tx.upsert("statements", dict(row), note="concept_upsert")
    assert not dict(store.rows("statements")[0].get("bits") or {}), "夹具没造出改前那一态"
    assert _ledger(pathlib.Path(store.root)) == [], "夹具不该自带台账"

    legacy = {"concept_id": "0000", "name": CONCEPT_LABEL, "definition": CONCEPT_DEF,
              "aliases": [], "related_concepts": []}
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.upsert_legacy_shaped(tx, legacy, actor="agent-B")
    healed = dict(store.rows("statements")[0])
    assert dict(healed.get("bits") or {}), healed.get("bits")
    assert healed.get("created_by") == "agent-B", (
        "同号同步不许改写 created_by（那是这一行当初的作者）")
    lines = _ledger(pathlib.Path(store.root))
    assert [r.get("applicable") for r in lines] == [False], lines

    # 幂等：同一段正文再同步一次，台账不追加第二行（append-only 不许被同一句话撑大）
    with store.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        CR.upsert_legacy_shaped(tx, legacy, actor="agent-B")
    assert len(_ledger(pathlib.Path(store.root))) == 1, _ledger(pathlib.Path(store.root))


# ============================================================ b) 读侧：三个词

def test_the_page_word_is_not_applicable_and_unjudged_and_t0_to_t4(
        tmp_path: pathlib.Path) -> None:
    """b：读侧把"不适用"与"判不了"印成两个词，档位是第三类词（三档不折平）。

    改前红：概念行与"没人判过"的命题都印"未判"。
    """
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    concept = _concept(sec)

    concept_tier = R._statement_tier_reading(st.root, concept)
    assert concept_tier["tri"] == "not_applicable", concept_tier
    assert concept_tier["word"] == "不适用", concept_tier
    assert concept_tier["level"] is None and concept_tier["label"] == "", concept_tier
    assert concept_tier["meaning"] == "", concept_tier
    assert concept_tier["word"] == R.NONTRIVIALITY_NOT_APPLICABLE_WORD, concept_tier

    # 没人判过的命题 ⇒ 未判
    unjudged = {"stmt_id": "0009", "kind": "theorem", "statement_full": THEOREM}
    unjudged_tier = R._statement_tier_reading(st.root, unjudged)
    assert unjudged_tier["tri"] == "unknown", unjudged_tier
    assert unjudged_tier["word"] == "未判", unjudged_tier

    # 判过一档的命题 ⇒ T2（这一档一个字都不许被上面两档挤掉）
    SEC.append_nontriviality(st.root, statement_full=THEOREM, level=2, basis="体量大")
    t2 = R._statement_tier_reading(st.root, unjudged)
    assert t2["tri"] == "computed" and t2["word"] == "T2", t2
    assert t2["label"] == "T2" and t2["meaning"].startswith("T2"), t2

    # 三个词各不相同（折平就只剩两个）
    assert len({concept_tier["word"], unjudged_tier["word"], t2["word"]}) == 3, (
        concept_tier["word"], unjudged_tier["word"], t2["word"])
    assert R.NONTRIVIALITY_NOT_APPLICABLE_WORD != R.NONTRIVIALITY_UNJUDGED_WORD
    assert R.TRI_NOT_APPLICABLE not in ("computed", "unknown"), R.TRI_NOT_APPLICABLE


def test_the_statement_row_reading_carries_the_word(tmp_path: pathlib.Path) -> None:
    """b（读数面那一格）：`evidence_chain` 的行上带 `nontriviality_word` 这一个词。"""
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    _concept(sec)
    rows = R.evidence_chain(pathlib.Path(st.root))["statements"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["nontriviality_word"] == "不适用", row.get("nontriviality_word")
    assert row["nontriviality_tri"] == "not_applicable", row.get("nontriviality_tri")
    assert row["nontriviality"] is None and row["nontriviality_label"] == "", row


# ============================================================ c) 正控：零调用

def test_the_concept_branch_costs_no_model_call(tmp_path: pathlib.Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """c：判档那一步对 concept 早退 —— 一次模型调用都不发。

    为什么这算判据：早退那一支要是写在取材料之后，判档的成本就变成"每条概念一次调用"
    （真机 mp3 一个工作区 1143 条概念）；而 `seam.calls == []` 是唯一能看见它的读数。
    """
    st = _ws(tmp_path)
    seam = _Seam()
    sec = Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    got = sec.judge_statement(statement_full=CONCEPT_DEF, kind="concept", task_id="t-1")
    assert seam.calls == [], seam.calls
    assert got.get("checked") is True and got.get("applicable") is False, got
    assert got.get("nontriviality") is None, got
    assert got.get("nontriviality_tri") == "not_applicable", got
    assert "没发调用" in str((got.get("cost") or {}).get("reason") or ""), got.get("cost")
    assert got.get("nontriviality_basis") == SEC.NONTRIVIALITY_NOT_APPLICABLE_BASIS, got

    # 整条登记路也一样：概念这一档的同一性判据是确定性的（`_merge_into_concept`）
    row = _concept(sec)
    assert seam.calls == [], seam.calls
    assert dict(row.get("bits")), row.get("bits")

    # 反面对照（"`calls == []` 不是恒真"）：把早退那一支关掉，同一条缝就会被调一次。
    monkeypatch.setattr(SEC, "_is_not_applicable_kind", lambda kind: False, raising=True)
    sec.judge_statement(statement_full=CONCEPT_DEF, kind="concept", task_id="t-2")
    assert seam.calls != [], ("早退关掉之后仍然一次调用都没发 ⇒ 上面那个 [] "
                              "说明不了'早退挡住了调用'")


# ============================================================ d) 反真空

def test_stubbing_the_not_applicable_branch_turns_the_word_into_unjudged(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d（反真空）：把"不适用"那一档摘掉（= 改前）⇒ b 必红（读成"未判"）。

    打桩的是"哪几档 kind 判档不适用"这一条判据本身（`_is_not_applicable_kind`），
    于是走的是改前那条路：概念行不进早退支、也不落任何台账行 —— 读侧只剩"未判"。
    """
    monkeypatch.setattr(SEC, "_is_not_applicable_kind", lambda kind: False, raising=True)
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    row = _concept(sec)
    tier = R._statement_tier_reading(st.root, row)
    assert tier["tri"] == "unknown", tier
    assert tier["word"] == "未判", "摘掉那一档之后仍然是「不适用」⇒ b 的绿不是它给的"
    assert tier["word"] != R.NONTRIVIALITY_NOT_APPLICABLE_WORD, tier
    assert not [r for r in _ledger(st.root) if r.get("applicable") is False], _ledger(st.root)
