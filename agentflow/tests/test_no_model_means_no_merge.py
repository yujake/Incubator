# -*- coding: utf-8 -*-
"""判据（件1）：模型判同一性没查成 ⇒ fail-closed 不并；词面相似度只许排序，不许决定并。

## 业主 2026-11-04 的裁定（这一份钉的就是它）
「没查成 ⇒ 不并（`unknown` 一律不同一行）；词面相似度只许用于候选表排序，不许决定并。」
以及合并判准那句：「条件有强弱/包含关系（素数 vs 奇素数）⇒ 不一致 ⇒ 不并」、
「不许用词面阈值之类的机械判据当判准」。

## 这一份钉的四条

| 条 | 它要证明的事 | 改前（这一笔之前）为什么是红的 |
|---|---|---|
| a | 「设 p 是素数；则 p 是奇数」vs「设 p 是奇素数；则 p 是奇数」⇒ 两行 | 改前没查成退回 `_same_proposition_candidate`（键 + 词面相似度 0.8889 ≥ 0.85）⇒ 并成一行、`proof_no=2` |
| b | 同一命题的词形变体（相似度 0.9118）⇒ 模型判 same 时仍能并、落成第 2 份证明 | 这一条是正控：fail-closed 不是"什么都不并" |
| c | 反真空：把 fail-closed 摘掉（候选表照旧收相似度那一档）⇒ a 回到 1 行 | 证明 a 的绿是 fail-closed 给的，不是夹具自带的 |
| d | 把词面相似度打桩成 0.99、而模型没查成 ⇒ 仍不许并 | 证明"相似度不再决定并"是有对象的：同一根桩摘掉 fail-closed 就会并 |

## 边界

- 全部 tmp 工作区、零真实模型调用（b 那一档的打桩只把"模型说了什么"填进
  `adjudicate_proposition` 的返回值形状，判据本体仍是秘书那一处）。
- 不碰 `projects/`（真机工作区只读）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from typing import Any, Mapping

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import propositionkey as PK
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.secretary import MERGED_BY_ADJUDICATION, Secretary
from agentflow.store import Store

from _proof_manuscript_fixture import carry_proof_manuscript
from conftest import BASIS_LIT_ID, ensure_basis_lit

#: 件1 判据 a 的那一对：条件有强弱关系（素数 / 奇素数）⇒ 语义不一致 ⇒ 两条。
#: 改前的读数：`state=same`、`similarity=0.8889`、`basis="prose_similarity"`。
PAIR_WEAK = "设 p 是素数；则 p 是奇数。"
PAIR_STRONG = "设 p 是奇素数；则 p 是奇数。"

#: 件1 判据 b 的那一对：同一命题的词形变体（常值 / 常数值），键不同、相似度 0.9118。
#: 它只在模型判 same 时才允许并（这正是"只要它在模型判准时走模型"那句话）。
MORPH_A = "设 G 是 3-正则群；则弦长函数不是常值。"
MORPH_B = "设 G 是 3-正则群；则弦长函数不是常数值。"

#: 两条互不相同的证明（避免"同种证明"那一档把第二次登记拒掉）。
PROOF_1 = ("证明：把弦长函数记为 f，由定义直接计算每个顶点的邻域大小，"
           "弦长只依赖邻域结构，故 f 在正则性下取常值，与假设矛盾。")
PROOF_2 = "证明：用对偶图的度数公式。常值弦长会逼出所有顶点同构，故弦长函数不是常值。"
PROOF_3 = "证明：对 p 的素因子分解作归纳，再取最小素因子（与上一行不同的写法）。"


def _own(full: str) -> dict:
    """自产命题的必填件（`doc_id` + `quote_reason`；与既有夹具同一个形状）。"""
    # 2026-11-17（GATE2 尾巴，业主「不许假来路」）：own_result 必须写清来路。
    # 这一份量的是"命题同一性判不判得成"（行数 / 合并 / proof_no），不是承重链；
    # 用一条真 literature 行当来路（`ensure_basis_lit`），它不进 statements 表，
    # 于是本文件量的行数与路径号读数一个字都不变。
    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture",
            "source_lit_id": BASIS_LIT_ID,
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    ensure_basis_lit(st)
    return st


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _record(sec: Secretary, st: Store, payload: Mapping[str, Any]) -> dict:
    """秘书直收的一笔：先给正文补手稿载体（稿 + 手稿签 + 五元位），再登记。"""
    return sec.record_statement(carry_proof_manuscript(st.root, payload), role="B")


@pytest.fixture(autouse=True)
def _proof_kind_default(monkeypatch):
    """同种证明那一问（`proof_kind`）的默认回答：`different`（另一条路径）。

    2026-11-12 起"同种证明"改由秘书的语义判定给（禁机械闸）：没有判定面时按
    fail-closed 拒收（`proof_kind_unjudged`），而这一份量的是"命题同一性判成 same
    之后能不能并起来"（b 的正控），不是证法是不是同一套 —— 两条证明本来就是
    不同的证法（见文件里的 PROOF_1 / PROOF_2），判 different 才是这个夹具的意思。
    真正的剧本桩（same / different / 没判成）在
    `tests/test_rehearsal_two_f_independent_proofs.py` 与
    `tests/test_unjudged_axes_are_fail_closed.py`。
    """
    import agentflow.secretary as _SEC

    real = _SEC.Secretary.judge

    def _judge(self, kind, context, **kw):
        if kind == "proof_kind":
            return {"checked": True, "decision": "different", "same_path": 0,
                    "reason": "夹具：不同种（这一份不量语义判别）", "basis": [], "cost": {}}
        return real(self, kind, context, **kw)

    monkeypatch.setattr(_SEC.Secretary, "judge", _judge)


def _proof_nos(row: dict) -> list[int]:
    return [int(no) for no, _text in VR.proof_list(row)]


def _stub_model_says_same(monkeypatch, *, target: str) -> None:
    """把"模型说了什么"填成 `verdict=same / same_as=<target>`（只替换那一次判定的返回值）。

    打桩打的是 `adjudicate_proposition`（判据入口），不是 `_same_proposition_candidate`
    （兜底那一档）：b 要证明的是"模型判 same 时并得成"，而模型的结论在真机上就是由
    这一处返回的。
    """
    def _judge(self, stmt_like, **_kw):
        return {"checked": True, "verdict": PK.STATE_SAME, "same_as": str(target),
                "basis": "打桩：条件组与结论组一致", "canonical_name": "", "route": "",
                "condition": "打桩：条件未读", "conclusion": "打桩：结论未读",
                "reason": "打桩：模型判 same", "candidates": [], "cost": {},
                "reused": False, "cached": False, "statement_sha256": "",
                "attempted": True, "seam_source": "打桩"}

    monkeypatch.setattr(Secretary, "adjudicate_proposition", _judge)


def _drop_fail_closed(monkeypatch) -> None:
    """把 fail-closed 摘掉：候选表照旧收"词面相似度达阈值"那一档（= 改前的行为）。"""
    real = Secretary._same_proposition_candidate

    def _candidate(self, tx, full, *, kind: str = "", key_only: bool = True):
        return real(self, tx, full, kind=kind, key_only=False)

    monkeypatch.setattr(Secretary, "_same_proposition_candidate", _candidate)


# ============================================================ a) 没查成 ⇒ 两条不同的命题

def test_a_two_condition_strengths_stay_two_rows_without_the_model(
        tmp_path: pathlib.Path) -> None:
    """a：素数 / 奇素数这一对（相似度 0.8889）在模型没查成时 ⇒ 两行，且读数说清为什么没并。

    改前红：兜底那一档拿词面相似度 0.8889 ≥ 0.85 判成同一条 ⇒ 一行、`proof_no=2`
    （`temp/probe_1_failclosed.py` 复现的就是这一条）。
    """
    # 夹具前提：这一对在旧兜底判据下确实是"同一条"（否则 a 不 sharp）。
    verdict = PK.same_proposition(PAIR_WEAK, PAIR_STRONG)
    assert verdict["state"] == PK.STATE_SAME, verdict
    assert float(verdict["similarity"]) >= PK.SAME_PROPOSITION_JACCARD, verdict
    assert PK.proposition_key(PAIR_WEAK) != PK.proposition_key(PAIR_STRONG), (
        "夹具前提：这一对的确定性键不同（所以只有词面相似度那一条会把它们并起来）")

    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)   # 没有缝 ⇒ 判定没查成
    first = _record(sec, st, {**_own(PAIR_WEAK), "proof_text": PROOF_1})
    second = _record(sec, st, {**_own(PAIR_STRONG), "proof_text": PROOF_3})

    rows = _rows(st)
    assert len(rows) == 2, f"条件强弱不同的两条命题落成了 {len(rows)} 行（应 2 行）"
    assert first.get("created") is True, first
    assert second.get("created") is True, second
    assert second.get("merged") is not True, second
    assert str(second.get("stmt_id") or "") != str(first.get("stmt_id") or ""), second
    assert _proof_nos(rows[0]) == [1] and _proof_nos(rows[1]) == [1], (
        [_proof_nos(r) for r in rows])
    # 变体留痕不许写：没有并进来，就没有"另一种写法"这回事。
    assert not list(rows[1].get("_proposition_matches") or []), rows[1].get("_proposition_matches")

    # 读数：为什么没并（不许折平 —— 这是"没有判断面"，不是"查过了、不同"）：
    # 2026-11-08 起判词只有两档，"没判成"的读数是 `verdict=""` + `checked=False`，
    # 不再有第三种结论词（`proposition_state` 的初值因此是空串）。
    assert second.get("proposition_state") == "", second.get("proposition_state")
    adj = dict(second.get("adjudication") or {})
    assert adj.get("checked") is False, adj
    assert adj.get("attempted") is False, adj
    assert adj.get("fail_closed") is True, adj
    why = str(adj.get("why_not_merged") or "")
    assert "不并" in why and "相似度" in why, why
    assert "0.8889" in why, f"读数要点名那一对的实际相似度（读的人才核得动）：{why!r}"
    assert "没有判断面" in str(second.get("proposition_reason") or ""), (
        second.get("proposition_reason"))


# ============================================================ b) 模型判 same ⇒ 仍能并

def test_b_the_morph_pair_still_merges_when_the_model_says_same(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b：同一命题的词形变体（相似度 0.9118）在模型判 same 时仍落成第 2 份证明。

    这一条是 fail-closed 的正控：它不许把"判得了"的那一档也一起关掉。
    """
    assert PK.proposition_key(MORPH_A) != PK.proposition_key(MORPH_B), (
        "夹具前提：这一对的键不同（相似度那一档才有意义）")
    assert PK.same_proposition(MORPH_A, MORPH_B)["state"] == PK.STATE_SAME

    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    first = _record(sec, st, {**_own(MORPH_A), "proof_text": PROOF_1})
    assert first.get("created") is True, first
    _stub_model_says_same(monkeypatch, target=str(first.get("stmt_id") or ""))

    second = _record(sec, st, {**_own(MORPH_B), "proof_text": PROOF_2})
    rows = _rows(st)
    assert len(rows) == 1, f"模型判 same 之后仍然落成 {len(rows)} 行（应 1 行）"
    assert second.get("merged") is True, second
    assert int(second.get("proof_no") or 0) == 2, second
    assert second.get("matched_by") == MERGED_BY_ADJUDICATION, second
    assert _proof_nos(rows[0]) == [1, 2], _proof_nos(rows[0])
    assert second.get("proposition_state") == PK.STATE_SAME, second.get("proposition_state")
    # 留痕：盘上要读得出"这一笔是那一条命题的另一种写法"。
    variants = list(rows[0].get("_proposition_matches") or [])
    assert variants and variants[-1].get("statement_full") == MORPH_B, variants


# ============================================================ c) 反真空：摘掉 fail-closed

def test_c_dropping_fail_closed_brings_the_one_row_back(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：把 fail-closed 摘掉 ⇒ a 那一对回到 1 行（证明 a 的绿是 fail-closed 给的）。"""
    _drop_fail_closed(monkeypatch)
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    first = _record(sec, st, {**_own(PAIR_WEAK), "proof_text": PROOF_1})
    second = _record(sec, st, {**_own(PAIR_STRONG), "proof_text": PROOF_3})
    rows = _rows(st)
    assert len(rows) == 1, f"摘掉 fail-closed 之后仍然是 {len(rows)} 行 ⇒ 那组断言不是对着它"
    assert second.get("merged") is True, second
    assert second.get("matched_by") == PK.BASIS_SIMILARITY, second
    assert str(second.get("stmt_id")) == str(first.get("stmt_id")), second
    assert _proof_nos(rows[0]) == [1, 2], _proof_nos(rows[0])


# ============================================================ d) 相似度 0.99 也不决定并

def test_d_similarity_does_not_decide_a_merge_even_at_099(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d：把词面相似度打桩成 0.99、模型没查成 ⇒ 仍不许并。

    这个桩只回"相似度达阈值"那一档（`basis="prose_similarity"`），它正是改前用来
    决定并的那一条判据。同一根桩、摘掉 fail-closed ⇒ 会并（所以这条桩是活的）。
    """
    def _always_similar(a: str, b: str, *, threshold: float = PK.SAME_PROPOSITION_JACCARD):
        return {"state": PK.STATE_SAME, "basis": PK.BASIS_SIMILARITY, "similarity": 0.99,
                "key_a": "", "key_b": "", "detail": {"unigram": 0.99, "bigram": 0.99},
                "reason": "打桩：词面相似度 0.99", "threshold": float(threshold),
                "what": "命题", "judgeable": {"a": {"ok": True}, "b": {"ok": True}}}

    monkeypatch.setattr(PK, "same_proposition", _always_similar)
    st = _ws(tmp_path / "fail-closed")
    sec = Secretary("B", root=st.root, store=st)
    _record(sec, st, {**_own(PAIR_WEAK), "proof_text": PROOF_1})
    second = _record(sec, st, {**_own(PAIR_STRONG), "proof_text": PROOF_3})
    assert len(_rows(st)) == 2, (
        f"词面相似度被抬到 0.99 之后仍然并了：在册 {len(_rows(st))} 行（应 2 行）")
    assert second.get("merged") is not True, second
    assert "0.9900" in str(dict(second.get("adjudication") or {}).get("why_not_merged") or ""), (
        dict(second.get("adjudication") or {}).get("why_not_merged"),
        "读数要点名被打桩的那个相似度（否则读的人分不出它是不是还好使）")

    # 反真空：同一根桩 + 摘掉 fail-closed ⇒ 并（证明上面那两行不是"桩没生效"）。
    _drop_fail_closed(monkeypatch)
    st2 = _ws(tmp_path / "before")
    sec2 = Secretary("B", root=st2.root, store=st2)
    _record(sec2, st2, {**_own(PAIR_WEAK), "proof_text": PROOF_1})
    again = _record(sec2, st2, {**_own(PAIR_STRONG), "proof_text": PROOF_3})
    assert len(_rows(st2)) == 1, f"摘掉 fail-closed 之后同一根桩应当并成 1 行：{len(_rows(st2))}"
    assert again.get("merged") is True and again.get("matched_by") == PK.BASIS_SIMILARITY, again
