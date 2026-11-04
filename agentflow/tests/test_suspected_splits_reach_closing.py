# -*- coding: utf-8 -*-
"""判据（件3）：建重那条路接上读数 —— `suspected_splits` 进 closing；没有正文也算归属。

## 两件事（业主 2026-11-04）

① `statementfission.suspected_splits` 生产面 0 个调用点（只报不拦 = 没报）：接进
   `closing` 的读数，与 `statements_unoptimized` 同档（不拦门、不产生 blocker）。
② "没有证明正文的重复登记"不进合并支（改前 `secretary.py` 那一支直接返回 None）⇒
   同一命题换一种写法、两次都没带证明，会落第二行。现在它也纳入归属判断：
   判得成同一条 ⇒ 不新建第二行（重复登记读数）。

## 这一份钉的四条

| 条 | 它要证明的事 | 改前（这一笔之前）为什么是红的 |
|---|---|---|
| a | 同一命题两种写法、都没正文 ⇒ 只落 1 行；另一种（键不同、相似度 0.9118）⇒ 2 行但 closing 点名疑似拆分 | 改前两次登记各建一行（2 行），且 `closing` 里 0 条读数 |
| b | `closing.readings["suspected_splits"]` 有 `count` 与逐簇的 `stmt_ids` | 改前这个键根本不存在（生产面 0 调用点） |
| c | 反真空：把接线摘掉 ⇒ 读数消失 | 证明 b 的读数来自这一笔接线 |
| d | 该读数不拦门：疑似拆分存在时收工门仍可 pass（`machine_pass=True`） | 保证它不是偷偷变成门 |

## 边界

全部 tmp 工作区；零真实模型调用（`suspected_splits` 是纯函数读数）。V 签走
`verifications.record_verification` 的真台账。不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import propositionkey as PK
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.secretary import Secretary
from agentflow.store import Store

#: 同一命题的两种写法：确定性键相同（"设/假设"、"是/为"、"；则/，于是" 都被规范化掉）。
NO_PROOF_A = "设 G 是 3-正则群；则弦长函数不是常值。"
NO_PROOF_B = "假设 G 为 3-正则群，于是弦长函数不是常值。"

#: 同一命题的词形变体：键不同（常值 / 常数值）、词面相似度 0.9118 ≥ 0.85。
#: 没查成时（fail-closed）它们落两行 —— 这正是 closing 那条读数要看见的形态。
MORPH_A = "设 G 是 3-正则群；则弦长函数不是常值。"
MORPH_B = "设 G 是 3-正则群；则弦长函数不是常数值。"

PROOF = "证明：由定义直接计算每个顶点的邻域大小，弦长只依赖邻域结构。"

_OK = {"verdict": "成立", "findings": []}


def _own(full: str) -> dict:
    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _closing(st: Store):
    """只跑读数那一层（`checks=()`）：这一份要测的是读数，不是八格。"""
    return CL.check_closing(st, checks=(), goal="测读数", goal_met=True, basis="夹具")


def _sign(st: Store, stmt_id: str, text: str) -> None:
    """把一条命题的 canonical 证明签住（第 3 位要连续 3 次「成立」）。"""
    for _ in range(3):
        VR.record_verification(st.root, statement_id=stmt_id, proof_text=text,
                               verdict=dict(_OK), verifier="agent-V", store=st,
                               proof_no=1)


def _split_without_proofs(base: pathlib.Path) -> Store:
    """两条同一命题的词形变体、都没带证明（fail-closed ⇒ 两行）—— b/c 的夹具。"""
    st = _ws(base)
    sec = Secretary("B", root=st.root, store=st)
    for full in (MORPH_A, MORPH_B):
        got = sec.record_statement(_own(full), role="B")
        assert got.get("checked") is True, got
    return st


# ============================================================ a) 没正文也要判归属

def test_a1_two_wordings_without_any_proof_stay_one_row(tmp_path: pathlib.Path) -> None:
    """a 的一半：同一命题两种写法、两次都没正文 ⇒ 只落 1 行（改前 2 行）。

    改前红：`_merge_into_proposition` 在没有证明正文时直接返回 None（"合并只针对第 N
    份证明"），于是换写法的同一命题建了第二行 —— 而它并不产生第二份证明，也没有任何
    读数说"这是同一条"。
    """
    assert PK.proposition_key(NO_PROOF_A) == PK.proposition_key(NO_PROOF_B), (
        "夹具前提：这一对的确定性键相同（否则判归属只能靠模型）")
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    first = sec.record_statement(_own(NO_PROOF_A), role="B")
    second = sec.record_statement(_own(NO_PROOF_B), role="B")
    rows = _rows(st)
    assert len(rows) == 1, f"同一命题换一种写法、都没正文，落成了 {len(rows)} 行（应 1 行）"
    assert first.get("created") is True, first
    assert second.get("created") is False and second.get("duplicate") is True, second
    assert str(second.get("stmt_id")) == str(first.get("stmt_id")), second
    assert second.get("proposition_state") == PK.STATE_SAME, second
    assert second.get("matched_by") == PK.BASIS_KEY, second
    assert "没有带证明正文" in str(second.get("reason") or ""), second.get("reason")
    # 没有第 2 份证明这回事：行上仍然只有 canonical 那一份（而且它是空的）。
    assert [no for no, _t in VR.proof_list(rows[0])] in ([], [1]), VR.proof_list(rows[0])


def test_a2_a_split_without_proofs_is_named_in_closing(tmp_path: pathlib.Path) -> None:
    """a 的另一半：键不同、相似度 0.9118、都没正文 ⇒ 两行，但 closing 点名疑似拆分。

    这一条守的是"只落 1 行"与"读数点名"之间那个缺口：fail-closed 之后它确实不并
    （条件/结论一致与否没人判过），所以必须有一条读数把这个形态摆出来。
    """
    assert PK.proposition_key(MORPH_A) != PK.proposition_key(MORPH_B), "夹具前提：键不同"
    assert PK.same_proposition(MORPH_A, MORPH_B)["similarity"] >= PK.SAME_PROPOSITION_JACCARD
    st = _split_without_proofs(tmp_path)
    rows = _rows(st)
    assert len(rows) == 2, f"fail-closed 之后这一对应当两行（实际 {len(rows)} 行）"
    reading = dict(_closing(st).readings.get("suspected_splits") or {})
    assert int(reading.get("count") or 0) == 1, reading
    named = list((reading.get("rows") or [{}])[0].get("stmt_ids") or [])
    assert named == sorted(str(r["stmt_id"]) for r in rows), named


# ============================================================ b) closing 里有这条读数

def test_b_closing_carries_the_suspected_splits_reading(tmp_path: pathlib.Path) -> None:
    """b：`closing.readings["suspected_splits"]` 含条数与命题号（改前这个键不存在）。"""
    st = _split_without_proofs(tmp_path)
    rep = _closing(st)
    assert "suspected_splits" in rep.readings, sorted(rep.readings)
    reading = dict(rep.readings["suspected_splits"])
    assert reading.get("checked") is True, reading
    assert int(reading.get("count") or 0) == 1, reading
    one = dict((reading.get("rows") or [{}])[0])
    assert int(one.get("count") or 0) == 2, one
    assert one.get("stmt_ids") == ["000000", "000001"], one
    assert "proof_no>1" in str(one.get("why") or ""), one.get("why")
    # 逐对读数也在（凭什么判同：相似度与依据）。
    assert one.get("pairs") and float(one["pairs"][0]["similarity"]) >= PK.SAME_PROPOSITION_JACCARD, one


# ============================================================ c) 反真空：摘掉接线

def test_c_unwiring_it_makes_the_reading_disappear(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：把接线摘掉（这一格不再产出读数）⇒ b 的读数消失（证明读数来自接线）。"""
    st = _split_without_proofs(tmp_path)
    assert dict(_closing(st).readings.get("suspected_splits") or {}).get("count") == 1, (
        "夹具前提：摘掉之前它必须读得出来")
    real = CL._run_reading

    def _without(rep, key, fn, *args, **kwargs):
        if key == "suspected_splits":
            return {}                 # 摘掉接线：这一格什么都不产出
        return real(rep, key, fn, *args, **kwargs)

    monkeypatch.setattr(CL, "_run_reading", _without)
    assert not (_closing(st).readings.get("suspected_splits") or {}), (
        "把接线摘掉之后读数还在 ⇒ 那条断言不是对着接线")


# ============================================================ d) 读数不拦门

def test_d_the_reading_does_not_block_the_gate(tmp_path: pathlib.Path) -> None:
    """d：疑似拆分存在时收工门仍可 pass（这条读数是读数，不是门）。"""
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    for full in (MORPH_A, MORPH_B):
        got = sec.record_statement({**_own(full), "proof_text": PROOF}, role="B")
        assert got.get("created") is True, got
    rows = _rows(st)
    assert len(rows) == 2, rows
    for row in rows:
        _sign(st, str(row["stmt_id"]), PROOF)
    rep = _closing(st)
    reading = dict(rep.readings.get("suspected_splits") or {})
    assert int(reading.get("count") or 0) == 1, reading
    assert rep.machine_pass is True, ([f.to_dict() for f in rep.findings], rep.to_dict())
    assert rep.blockers == [], [f.to_dict() for f in rep.blockers]
    assert CL.tri_state_exit_code(rep) == 0, rep.to_dict()
    assert not [f for f in rep.findings if f.check == "suspected_splits"
                and f.level == "blocker"], [f.to_dict() for f in rep.findings]


# ============================================================ 声明的入口（不 skip / 不 xfail）

def test_the_gate_reading_keeps_its_three_states(tmp_path: pathlib.Path) -> None:
    """附：`statements` 读不到 ⇒ `checked=False` + `reason`（不是"没有拆命题"）。"""
    rep = CL.check_closing(None, checks=(), goal="空", goal_met=True, basis="夹具")
    reading = dict(rep.readings.get("suspected_splits") or {})
    assert reading.get("checked") is False, reading
    assert str(reading.get("reason") or "").strip(), reading


#: 2026-11-02 准入闸默认 strict 之后，登记证明正文前要先有 V 签（见 conftest 同名 fixture）。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")
